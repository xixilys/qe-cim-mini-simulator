#!/usr/bin/env python3
"""Run promoted QE FPGA requests through generic_sim and emit feedback samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GENERIC_SIM = REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l2-request-bundle", type=Path, required=True)
    parser.add_argument("--l2-results", type=Path, default=None, help="Optional paired L2 TLM results for L3-to-L2 calibration")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--generic-sim", type=Path, default=DEFAULT_GENERIC_SIM)
    parser.add_argument("--max-requests", type=int, default=0, help="Optional cap; 0 means all requests")
    parser.add_argument("--timeout-s", type=int, default=120)
    return parser.parse_args(list(argv))


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finite_float(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else default
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _round_metric(value: float) -> float:
    return round(float(value), 9) if math.isfinite(float(value)) else value


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ranks(values: Sequence[float]) -> List[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        rank = (position + 1 + end) / 2.0
        for original_index, _ in indexed[position:end]:
            ranks[original_index] = rank
        position = end
    return ranks


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    left_mean = _mean(left_ranks)
    right_mean = _mean(right_ranks)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_ranks, right_ranks))
    left_var = sum((a - left_mean) ** 2 for a in left_ranks)
    right_var = sum((b - right_mean) ** 2 for b in right_ranks)
    denominator = math.sqrt(left_var * right_var)
    if denominator <= 0.0:
        return None
    return _round_metric(numerator / denominator)


def _tie_fraction(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    counts: Dict[float, int] = {}
    for value in values:
        counts[float(value)] = counts.get(float(value), 0) + 1
    tied_count = sum(count for count in counts.values() if count > 1)
    return tied_count / float(len(values))


def _validation_metric_rows(
    requests: Sequence[Mapping[str, Any]],
    feedback_samples: Sequence[Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for request, sample in zip(requests, feedback_samples):
        sample_status = str(sample.get("status", "unknown"))
        if sample_status != "passed":
            excluded.append({
                "candidate_id": str(request.get("candidate_id") or sample.get("candidate_id", "")),
                "selection_role": str(sample.get("selection_role") or request.get("selection_role") or "promoted"),
                "status": sample_status,
                "reason": "sample_status_not_passed",
            })
            continue
        l1_metrics = request.get("candidate_l1_metrics", {}) if isinstance(request.get("candidate_l1_metrics"), Mapping) else {}
        sample_metrics = sample.get("metrics", {}) if isinstance(sample.get("metrics"), Mapping) else {}
        l1_edp = _finite_float(l1_metrics.get("estimated_edp"), default=float("nan"))
        l3_edp = _finite_float(sample_metrics.get("edp"), default=float("nan"))
        if not math.isfinite(l1_edp) or not math.isfinite(l3_edp) or l1_edp <= 0.0 or l3_edp <= 0.0:
            excluded.append({
                "candidate_id": str(request.get("candidate_id") or sample.get("candidate_id", "")),
                "selection_role": str(sample.get("selection_role") or request.get("selection_role") or "promoted"),
                "status": sample_status,
                "reason": "non_positive_or_non_finite_l1_or_l3_edp",
            })
            continue
        rows.append({
            "candidate_id": str(request.get("candidate_id") or sample.get("candidate_id", "")),
            "selection_role": str(sample.get("selection_role") or request.get("selection_role") or "promoted"),
            "sample_status": sample_status,
            "l1_estimated_edp": _round_metric(l1_edp),
            "l3_edp": _round_metric(l3_edp),
        })
    return rows, excluded


def _top_k_ids(rows: Sequence[Mapping[str, Any]], *, metric: str, k: int) -> List[str]:
    ranked = sorted(
        rows,
        key=lambda row: (
            _finite_float(row.get(metric), default=float("inf")),
            str(row.get("candidate_id", "")),
        ),
    )
    return [str(row.get("candidate_id", "")) for row in ranked[: max(0, int(k))]]


def _build_validation_metrics(
    *,
    requests: Sequence[Mapping[str, Any]],
    feedback_samples: Sequence[Mapping[str, Any]],
    selection_role_counts: Mapping[str, int],
) -> Dict[str, Any]:
    rows, excluded = _validation_metric_rows(requests, feedback_samples)
    usable_count = len(rows)
    usable_selection_role_counts: Dict[str, int] = {}
    for row in rows:
        role = str(row.get("selection_role", "promoted"))
        usable_selection_role_counts[role] = usable_selection_role_counts.get(role, 0) + 1
    k = min(5, usable_count) if usable_count <= 2 else min(5, max(1, usable_count // 2))
    l1_top_k_ids = _top_k_ids(rows, metric="l1_estimated_edp", k=k)
    l3_top_k_ids = _top_k_ids(rows, metric="l3_edp", k=k)
    l1_top_k = set(l1_top_k_ids)
    l3_top_k = set(l3_top_k_ids)
    top_overlap = l1_top_k.intersection(l3_top_k)
    top_union = l1_top_k.union(l3_top_k)
    promoted_ids = {str(row.get("candidate_id", "")) for row in rows if row.get("selection_role") == "promoted"}
    holdout_ids = {str(row.get("candidate_id", "")) for row in rows if row.get("selection_role") == "holdout"}
    promoted_in_l3_top_k = promoted_ids.intersection(l3_top_k)
    false_negative_holdout_top_k = sorted(holdout_ids.intersection(l3_top_k))
    spearman = _spearman(
        [_finite_float(row.get("l1_estimated_edp"), default=float("nan")) for row in rows],
        [_finite_float(row.get("l3_edp"), default=float("nan")) for row in rows],
    )
    l3_values = [_finite_float(row.get("l3_edp"), default=float("nan")) for row in rows]
    l3_tie_fraction = _tie_fraction([value for value in l3_values if math.isfinite(value)])
    validation_blockers: List[str] = []
    min_usable_samples = 8
    min_abs_spearman = 0.70
    max_tie_fraction = 0.50
    if usable_count < min_usable_samples:
        validation_blockers.append(f"min_usable_samples:{min_usable_samples}")
    if spearman is None:
        validation_blockers.append("rank_correlation_unavailable")
    elif abs(float(spearman)) < min_abs_spearman:
        validation_blockers.append(f"min_abs_spearman:{min_abs_spearman}")
    if l3_tie_fraction > max_tie_fraction:
        validation_blockers.append(f"max_l3_tie_fraction:{max_tie_fraction}")
    status = "usable_for_sampled_rank_validation" if not validation_blockers else "insufficient_for_sampled_rank_validation"
    precision_denominator = max(1, len(promoted_ids))
    recall_denominator = max(1, len(l3_top_k))
    return {
        "schema_version": "dse.qe_fpga_l3_feedback_validation_metrics.v1",
        "status": status,
        "sample_count": len(feedback_samples),
        "usable_sample_count": usable_count,
        "excluded_sample_count": len(excluded),
        "excluded_samples": excluded[:20],
        "validation_blockers": validation_blockers,
        "validation_thresholds": {
            "min_usable_samples": min_usable_samples,
            "min_abs_spearman": min_abs_spearman,
            "max_l3_tie_fraction": max_tie_fraction,
        },
        "selection_role_counts": dict(sorted(usable_selection_role_counts.items())),
        "raw_selection_role_counts": dict(sorted(selection_role_counts.items())),
        "rank_correlation": {
            "status": "usable" if status == "usable_for_sampled_rank_validation" else "insufficient",
            "overlap_count": usable_count,
            "l1_estimated_edp_vs_l3_edp_spearman": spearman,
            "l3_tie_fraction": _round_metric(l3_tie_fraction),
        },
        "top_k_overlap": {
            "k": k,
            "l1_top_k_candidate_ids": l1_top_k_ids,
            "l3_top_k_candidate_ids": l3_top_k_ids,
            "overlap_count": len(top_overlap),
            "jaccard": _round_metric(len(top_overlap) / len(top_union)) if top_union else None,
            "l3_top_k_recovered_by_l1_top_k": _round_metric(len(top_overlap) / max(1, len(l3_top_k))),
        },
        "promotion_quality": {
            "k": k,
            "evaluated_promoted_count": len(promoted_ids),
            "evaluated_holdout_count": len(holdout_ids),
            "promoted_in_l3_top_k_count": len(promoted_in_l3_top_k),
            "precision_at_k": _round_metric(len(promoted_in_l3_top_k) / precision_denominator),
            "precision_denominator": precision_denominator,
            "recall_at_k": _round_metric(len(promoted_in_l3_top_k) / recall_denominator),
            "recall_denominator": recall_denominator,
            "false_negative_holdout_top_k_candidate_ids": false_negative_holdout_top_k,
        },
        "sample_rows_preview": rows[:10],
        "limitations": [
            "metrics_cover_only_executed_generic_sim_samples",
            "failed_or_non_finite_samples_are_excluded_from_validation_metrics",
            "generic_sim_edp_is_projection_not_qe_or_hardware_measurement",
            "promotion_quality_requires_holdout_samples_to_detect_false_negatives",
        ],
        "claim_boundary": "l3_generic_sim_validation_metrics_only_not_hardware_or_qe_correctness_evidence",
    }


def _op_type_for_node(node: Mapping[str, Any]) -> str:
    kernels = {str(kernel).lower() for kernel in node.get("kernels", []) or []}
    stage_type = str(node.get("stage_type", "")).lower()
    if kernels.intersection({"h_psi", "projector", "band_path_projection"}):
        return "gemm"
    if kernels.intersection({"fft", "transpose", "v_of_rho"}):
        return "fft"
    if kernels.intersection({"diagonalization", "c_bands"}) or "nscf" in stage_type:
        return "eigen"
    if kernels.intersection({"reduction", "mix_rho", "forces", "stress", "rho_out"}):
        return "reduction"
    return "generic_op"


def _gsim_node(node_id: str, node: Mapping[str, Any]) -> Dict[str, Any]:
    weight_ms = max(0.001, _finite_float(node.get("estimated_weight_ms"), default=1.0))
    op_type = _op_type_for_node(node)
    return {
        "op_type": op_type,
        "inputs": [],
        "outputs": [f"{node_id}:out"],
        "estimated_flops": max(1.0, weight_ms * 1.0e6),
        "estimated_memory_bytes": max(8.0, weight_ms * 1024.0),
        "attributes": {
            "stage_type": str(node.get("stage_type", "")),
            "workflow_class": str(node.get("workflow_class", "")),
            "source_node_id": node_id,
        },
    }


def _memory_bandwidth_gbps(memory_topology: str) -> float:
    return {
        "hbm_multi_channel": 460.0,
        "ddr_streaming": 32.0,
        "pcie_host_streamed": 16.0,
    }.get(memory_topology, 32.0)


def _schedule_policy(runtime_schedule: str) -> str:
    if runtime_schedule in {"overlap_dma_compute", "persistent_device_pipeline"}:
        return "pipeline"
    if runtime_schedule in {"batched_stage_offload"}:
        return "dynamic"
    return "static"


def _fpga_capabilities(template: str) -> Dict[str, Dict[str, float]]:
    multiplier = {
        "fpga_hbm_streaming_dataflow": 1.15,
        "fpga_fft_transpose_pipeline": 1.05,
        "fpga_hybrid_cpu_control_accel_kernels": 0.9,
    }.get(template, 1.0)
    return {
        "generic_op": {"peak_gops": 180.0 * multiplier, "efficiency": 0.55},
        "gemm": {"peak_gops": 420.0 * multiplier, "efficiency": 0.72},
        "fft": {"peak_gops": 320.0 * multiplier, "efficiency": 0.70},
        "eigen": {"peak_gops": 160.0 * multiplier, "efficiency": 0.42},
        "reduction": {"peak_gops": 250.0 * multiplier, "efficiency": 0.68},
    }


def _execution_edge_kind(edge: Mapping[str, Any]) -> str:
    return str(edge.get("edge_kind") or edge.get("tensor_name") or "")


def _is_generic_sim_execution_edge(edge: Mapping[str, Any]) -> bool:
    return _execution_edge_kind(edge) in {
        "control",
        "data",
        "stage_artifact_dependency",
        "stage_order",
        "state",
        "workflow_dependency",
        "workflow_sequence",
    }


def build_gsim_request(l2_request: Mapping[str, Any]) -> Dict[str, Any]:
    payload = l2_request.get("request_payload", {}) if isinstance(l2_request.get("request_payload"), Mapping) else {}
    graph = payload.get("graph", {}) if isinstance(payload.get("graph"), Mapping) else {}
    deployment = payload.get("deployment", {}) if isinstance(payload.get("deployment"), Mapping) else {}
    parameters = l2_request.get("candidate_parameters", {}) if isinstance(l2_request.get("candidate_parameters"), Mapping) else {}
    memory_topology = str(deployment.get("memory_topology") or parameters.get("memory_topology") or "ddr_streaming")
    runtime_schedule = str(deployment.get("runtime_schedule") or parameters.get("runtime_schedule") or "batched_stage_offload")
    template = str(deployment.get("architecture_template") or parameters.get("architecture_template") or "fpga_hybrid_cpu_control_accel_kernels")

    source_nodes = graph.get("nodes", {}) if isinstance(graph.get("nodes"), Mapping) else {}
    nodes = {str(node_id): _gsim_node(str(node_id), node) for node_id, node in source_nodes.items() if isinstance(node, Mapping)}
    edges: List[Dict[str, Any]] = []
    omitted_edge_kind_counts: Dict[str, int] = {}
    for index, edge in enumerate(graph.get("edges", []) or []):
        if not isinstance(edge, Mapping):
            continue
        edge_kind = _execution_edge_kind(edge) or f"edge_{index:03d}"
        if not _is_generic_sim_execution_edge(edge):
            omitted_edge_kind_counts[edge_kind] = omitted_edge_kind_counts.get(edge_kind, 0) + 1
            continue
        source = str(edge.get("source", edge.get("source_node", "")))
        target = str(edge.get("target", edge.get("target_node", "")))
        if source not in nodes or target not in nodes:
            continue
        size_bytes = max(8, int(_finite_float(edge.get("data_mb"), default=0.001) * 1024.0 * 1024.0))
        edges.append({
            "source": source,
            "target": target,
            "tensor_name": edge_kind,
            "tensor_dtype": "FP64",
            "element_size": 8,
            "size_bytes": size_bytes,
        })
    mapping = {
        node_id: ("host" if node.get("op_type") == "eigen" else "candidate_fpga")
        for node_id, node in nodes.items()
    }
    return {
        "schema_version": "gsim.request.v1",
        "run_id": str(l2_request.get("request_id", l2_request.get("candidate_id", "qe_fpga_l3_gsim"))),
        "mode": "standalone_systemc",
        "workload": {
            "graph_id": str(payload.get("run_id", "qe_fpga_l3_gsim_graph")),
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "candidate_id": str(l2_request.get("candidate_id", "")),
                "design_key": str(l2_request.get("design_key", "")),
                "source_schema_version": str(l2_request.get("schema_version", "")),
                "omitted_non_execution_edge_count": sum(omitted_edge_kind_counts.values()),
                "omitted_non_execution_edge_kind_counts": dict(sorted(omitted_edge_kind_counts.items())),
                "claim_boundary": "translated_from_qe_fpga_l2_request_for_generic_sim_timing_only",
            },
        },
        "architecture": {
            "host": {"cpu_model": "abstract", "clock_mhz": 3000, "memory_bw_gbps": 100, "cores": 8},
            "interconnect": {
                "type": "pcie",
                "bandwidth_gbps": _memory_bandwidth_gbps(memory_topology),
                "latency_ns": 800,
            },
            "accelerators": [
                {
                    "accel_id": "host",
                    "accel_type": "cpu",
                    "clock_mhz": 3000,
                    "local_memory_kb": 32768,
                    "power": {"static_w": 8.0, "max_w": 35.0},
                    "capabilities": {
                        "generic_op": {"peak_gops": 120.0, "efficiency": 0.55},
                        "gemm": {"peak_gops": 120.0, "efficiency": 0.55},
                        "fft": {"peak_gops": 80.0, "efficiency": 0.45},
                        "eigen": {"peak_gops": 60.0, "efficiency": 0.35},
                        "reduction": {"peak_gops": 50.0, "efficiency": 0.50},
                    },
                },
                {
                    "accel_id": "candidate_fpga",
                    "accel_type": "fpga",
                    "clock_mhz": 250,
                    "local_memory_kb": 65536 if memory_topology == "hbm_multi_channel" else 16384,
                    "power": {"static_w": 6.0, "max_w": 35.0},
                    "capabilities": _fpga_capabilities(template),
                },
            ],
        },
        "mapping": mapping,
        "scheduling": {
            "policy": _schedule_policy(runtime_schedule),
            "allow_overlap_dma_compute": runtime_schedule in {"overlap_dma_compute", "persistent_device_pipeline"},
            "double_buffer": runtime_schedule in {"overlap_dma_compute", "persistent_device_pipeline"},
        },
        "output": {},
    }


def _artifact_ref(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _feedback_sample(
    *,
    l2_request: Mapping[str, Any],
    result: Mapping[str, Any],
    result_path: Path,
    request_path: Path,
    generic_sim: Path,
    status: str | None = None,
) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), Mapping) else {}
    l1_metrics = (
        l2_request.get("candidate_l1_metrics", {})
        if isinstance(l2_request.get("candidate_l1_metrics"), Mapping)
        else {}
    )
    latency_ms = _finite_float(metrics.get("latency_ms"), default=0.0)
    energy_mj = _finite_float(metrics.get("energy_j"), default=0.0) * 1000.0
    edp = latency_ms * energy_mj
    data_movement_mb = _l3_execution_data_movement_mb(l2_request, l1_metrics)
    return {
        "sample_id": f"l3_generic_sim_{l2_request.get('candidate_id', 'candidate')}",
        "candidate_id": str(l2_request.get("candidate_id", "")),
        "fidelity": "L3_generic_sim",
        "selection_role": str(l2_request.get("selection_role", "promoted")),
        "status": str(status or result.get("status", "unknown")),
        "metrics": {
            "workflow_wall_time_ms": _round_metric(latency_ms),
            "energy_mj": _round_metric(energy_mj),
            "edp": _round_metric(edp),
            "resource_pressure": _finite_float(
                l1_metrics.get("fpga_resource_pressure"),
                default=0.0,
            ),
            "data_movement_mb": _round_metric(max(0.0, data_movement_mb)),
        },
        "provenance": {
            "tool": str(generic_sim),
            "request_path": str(request_path),
            "result_path": str(result_path),
            "request_sha256": _file_sha256(request_path),
            "result_sha256": _file_sha256(result_path),
            "result_schema_version": str(result.get("schema_version", "")),
        },
        "claim_boundary": "l3_generic_sim_feedback_timing_projection_only_not_qe_correctness_or_bitstream_evidence",
    }


def _l3_execution_data_movement_mb(
    l2_request: Mapping[str, Any],
    l1_metrics: Mapping[str, Any],
) -> float:
    payload = l2_request.get("request_payload", {}) if isinstance(l2_request.get("request_payload"), Mapping) else {}
    graph = payload.get("graph", {}) if isinstance(payload.get("graph"), Mapping) else {}
    edges = graph.get("edges", []) if isinstance(graph.get("edges"), list) else []
    movement = sum(
        _finite_float(edge.get("data_mb"), default=0.0)
        for edge in edges
        if isinstance(edge, Mapping) and _is_generic_sim_execution_edge(edge)
    )
    if movement > 0.0:
        return movement
    return _finite_float(l1_metrics.get("estimated_data_movement_mb"), default=0.0)


def _l2_results_by_candidate(path: Path | None) -> Dict[str, Dict[str, Any]]:
    if path is None:
        return {}
    payload = _load_json_object(path)
    return {
        str(row.get("candidate_id", "")): dict(row)
        for row in payload.get("results", []) or []
        if isinstance(row, Mapping) and str(row.get("candidate_id", ""))
    }


def _fit_l3_to_l2_calibration(
    feedback_samples: Sequence[Mapping[str, Any]],
    l2_results_by_candidate: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    pairs: List[Dict[str, Any]] = []
    for sample in feedback_samples:
        if not isinstance(sample, Mapping) or str(sample.get("status", "")) != "passed":
            continue
        candidate_id = str(sample.get("candidate_id", ""))
        l2_row = l2_results_by_candidate.get(candidate_id, {})
        metrics = sample.get("metrics", {}) if isinstance(sample.get("metrics"), Mapping) else {}
        l2_metrics = l2_row.get("metrics", {}) if isinstance(l2_row.get("metrics"), Mapping) else {}
        l3_edp = _finite_float(metrics.get("edp"), default=0.0)
        l2_edp = _finite_float(l2_metrics.get("tlm_edp"), default=0.0)
        if l3_edp <= 0.0 or l2_edp <= 0.0:
            continue
        pairs.append({
            "candidate_id": candidate_id,
            "l3_edp": _round_metric(l3_edp),
            "l2_tlm_edp": _round_metric(l2_edp),
            "l3_workflow_wall_time_ms": _round_metric(_finite_float(metrics.get("workflow_wall_time_ms"), default=0.0)),
            "l3_energy_mj": _round_metric(_finite_float(metrics.get("energy_mj"), default=0.0)),
            "l2_tlm_workflow_wall_time_ms": _round_metric(_finite_float(l2_metrics.get("tlm_workflow_wall_time_ms"), default=0.0)),
            "l2_tlm_energy_mj": _round_metric(_finite_float(l2_metrics.get("tlm_energy_mj"), default=0.0)),
        })
    status = "not_evaluated"
    scale = float("nan")
    bias = float("nan")
    noise_cv = float("nan")
    blockers: List[str] = []
    if len(pairs) < 2:
        blockers.append("min_paired_samples:2")
    else:
        xs = [float(row["l3_edp"]) for row in pairs]
        ys = [float(row["l2_tlm_edp"]) for row in pairs]
        x_mean = _mean(xs)
        y_mean = _mean(ys)
        x_var = sum((value - x_mean) ** 2 for value in xs)
        if x_var <= 0.0:
            scale = y_mean / max(1.0e-9, x_mean)
            bias = 0.0
        else:
            scale = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / x_var
            bias = y_mean - scale * x_mean
        residuals = [y - (scale * x + bias) for x, y in zip(xs, ys)]
        rmse = math.sqrt(sum(value * value for value in residuals) / max(1, len(residuals)))
        noise_cv = rmse / max(1.0e-9, y_mean)
        rank_correlation = _spearman(xs, ys)
        if not math.isfinite(scale) or scale <= 0.0:
            blockers.append("non_positive_affine_scale_indicates_rank_inversion")
        if not math.isfinite(bias):
            blockers.append("non_finite_bias")
        if not math.isfinite(noise_cv):
            blockers.append("non_finite_noise_cv")
        if rank_correlation is not None and rank_correlation < 0.0:
            blockers.append("negative_l3_vs_l2_rank_correlation")
        if not blockers:
            status = "usable_for_model_level_common_objective"
    if blockers and status == "not_evaluated":
        status = "blocked_insufficient_pairs" if len(pairs) < 2 else "blocked_model_alignment"
    rank_correlation = _spearman(
        [float(row["l3_edp"]) for row in pairs],
        [float(row["l2_tlm_edp"]) for row in pairs],
    )
    return {
        "schema_version": "dse.qe_fpga_l3_to_l2_calibration.v1",
        "status": status,
        "common_objective_metric": "edp",
        "source_fidelity": "L3_generic_sim",
        "target_fidelity": "L2_python_tlm",
        "paired_sample_count": len(pairs),
        "scale": _round_metric(scale) if math.isfinite(scale) else None,
        "bias": _round_metric(bias) if math.isfinite(bias) else None,
        "noise_edp_cv": _round_metric(noise_cv) if math.isfinite(noise_cv) else None,
        "l3_vs_l2_edp_spearman": rank_correlation,
        "blockers": blockers,
        "pairs": pairs,
        "method": "least_squares_affine_l3_edp_to_l2_tlm_edp",
        "limitations": [
            "calibrates_generic_sim_projection_to_L2_python_tlm_common_objective",
            "does_not_establish_QE_correctness_or_hardware_timing_truth",
            "usable_only_for_model_level_active_search_feedback",
        ],
        "claim_boundary": "l3_to_l2_model_calibration_only_not_hardware_truth",
    }


def _attach_calibration_to_feedback_samples(
    feedback_samples: Sequence[Mapping[str, Any]],
    *,
    calibration: Mapping[str, Any],
    calibration_path: Path,
    calibration_sha256: str,
) -> List[Dict[str, Any]]:
    if calibration.get("status") != "usable_for_model_level_common_objective":
        return [dict(sample) for sample in feedback_samples if isinstance(sample, Mapping)]
    paired_ids = {
        str(row.get("candidate_id", ""))
        for row in calibration.get("pairs", []) or []
        if isinstance(row, Mapping)
    }
    calibrated: List[Dict[str, Any]] = []
    for sample in feedback_samples:
        if not isinstance(sample, Mapping):
            continue
        updated = dict(sample)
        candidate_id = str(updated.get("candidate_id", ""))
        metrics = updated.get("metrics", {}) if isinstance(updated.get("metrics"), Mapping) else {}
        edp = _finite_float(metrics.get("edp"), default=0.0)
        if candidate_id in paired_ids and str(updated.get("status", "")) == "passed" and edp > 0.0:
            updated["calibration"] = {
                "status": "calibrated_to_l2_common_objective",
                "common_objective_eligible": True,
                "common_objective_metric": "edp",
                "paired_sample_count": int(calibration.get("paired_sample_count", 0)),
                "scale": calibration.get("scale"),
                "bias": calibration.get("bias"),
                "noise_edp_cv": calibration.get("noise_edp_cv"),
                "calibration_artifact": str(calibration_path),
                "calibration_artifact_sha256": calibration_sha256,
            }
        calibrated.append(updated)
    return calibrated


def run_l3_feedback(args: argparse.Namespace) -> Dict[str, Any]:
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = _load_json_object(args.l2_request_bundle)
    requests = [request for request in bundle.get("requests", []) or [] if isinstance(request, Mapping)]
    if int(args.max_requests) > 0:
        requests = requests[: int(args.max_requests)]
    results: List[Dict[str, Any]] = []
    feedback_samples: List[Dict[str, Any]] = []
    generic_sim = Path(args.generic_sim)
    for index, request in enumerate(requests):
        candidate_id = str(request.get("candidate_id") or f"candidate_{index:03d}")
        safe_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in candidate_id)
        run_dir = out_dir / f"{index:03d}_{safe_id}"
        request_path = run_dir / "gsim_request.json"
        result_path = run_dir / "gsim_result.json"
        gsim_request = build_gsim_request(request)
        gsim_request["output"] = {"result_json": str(result_path), "trace_json": str(run_dir / "gsim_trace.json")}
        _write_json(request_path, gsim_request)
        cmd = [str(generic_sim), "--request", str(request_path), "--result", str(result_path)]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=int(args.timeout_s), check=False)
        except subprocess.TimeoutExpired as exc:
            completed = subprocess.CompletedProcess(cmd, returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout")
        result_payload: Dict[str, Any]
        if result_path.exists():
            result_payload = _load_json_object(result_path)
        else:
            result_payload = {
                "schema_version": "gsim.result.v1",
                "run_id": str(gsim_request.get("run_id", "")),
                "status": "failed",
                "error_message": "generic_sim_result_missing",
                "metrics": {},
            }
            _write_json(result_path, result_payload)
        result_status = "passed" if completed.returncode == 0 and result_payload.get("status") == "passed" else "failed"
        feedback_sample = _feedback_sample(
            l2_request=request,
            result=result_payload,
            result_path=result_path,
            request_path=request_path,
            generic_sim=generic_sim,
            status=result_status,
        )
        feedback_samples.append(feedback_sample)
        metrics = feedback_sample["metrics"]
        results.append({
            "candidate_id": candidate_id,
            "request_id": str(request.get("request_id", "")),
            "status": result_status,
            "returncode": completed.returncode,
            "cmd": cmd,
            "stdout_tail": str(completed.stdout)[-2000:],
            "stderr_tail": str(completed.stderr)[-2000:],
            "metrics": metrics,
            "gsim_request_ref": _artifact_ref(request_path),
            "gsim_result_ref": _artifact_ref(result_path),
            "claim_boundary": "l3_generic_sim_result_only_not_qe_correctness_or_fpga_bitstream_evidence",
        })
    passed_count = sum(1 for row in results if row.get("status") == "passed")
    selection_role_counts: Dict[str, int] = {}
    for sample in feedback_samples:
        role = str(sample.get("selection_role", "promoted"))
        selection_role_counts[role] = selection_role_counts.get(role, 0) + 1
    validation_metrics = _build_validation_metrics(
        requests=requests,
        feedback_samples=feedback_samples,
        selection_role_counts=selection_role_counts,
    )
    l2_results_by_candidate = _l2_results_by_candidate(args.l2_results)
    calibration: Dict[str, Any] = {
        "schema_version": "dse.qe_fpga_l3_to_l2_calibration.v1",
        "status": "not_requested",
        "claim_boundary": "l3_to_l2_model_calibration_only_not_hardware_truth",
    }
    calibration_ref: Dict[str, Any] | None = None
    if l2_results_by_candidate:
        calibration = _fit_l3_to_l2_calibration(feedback_samples, l2_results_by_candidate)
        calibration_path = out_dir / "qe_fpga_l3_l2_calibration.json"
        _write_json(calibration_path, calibration)
        calibration_ref = _artifact_ref(calibration_path)
        feedback_samples = _attach_calibration_to_feedback_samples(
            feedback_samples,
            calibration=calibration,
            calibration_path=calibration_path,
            calibration_sha256=str(calibration_ref["sha256"]),
        )
    feedback_payload = {
        "schema_version": "dse.qe_fpga_external_feedback_samples.v1",
        "sample_count": len(feedback_samples),
        "samples": feedback_samples,
        "selection_role_counts": dict(sorted(selection_role_counts.items())),
        "validation_metrics": validation_metrics,
        "calibration": {
            **{key: value for key, value in calibration.items() if key != "pairs"},
            **({"artifact_ref": calibration_ref} if calibration_ref else {}),
        },
        "claim_boundary": "feedback_samples_from_l3_generic_sim_only_not_hardware_implementation_evidence",
    }
    _write_json(out_dir / "feedback_samples.json", feedback_payload)
    report = {
        "schema_version": "dse.qe_fpga_l3_generic_sim_feedback.v1",
        "status": "passed" if passed_count == len(results) else "partial",
        "method_name": "QEFPGA_L3_GenericSimFeedback",
        "source_l2_request_bundle": {
            "path": str(args.l2_request_bundle),
            "sha256": _file_sha256(args.l2_request_bundle),
        },
        "generic_sim": {
            "path": str(generic_sim),
            "exists": generic_sim.exists(),
            "sha256": _file_sha256(generic_sim) if generic_sim.exists() and generic_sim.is_file() else None,
        },
        "request_count": len(results),
        "executed_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "feedback_sample_count": len(feedback_samples),
        "selection_role_counts": dict(sorted(selection_role_counts.items())),
        "validation_metrics": validation_metrics,
        "calibration": {
            **{key: value for key, value in calibration.items() if key != "pairs"},
            **({"artifact_ref": calibration_ref} if calibration_ref else {}),
        },
        "feedback_samples_preview": [
            {
                "candidate_id": str(sample.get("candidate_id", "")),
                "selection_role": str(sample.get("selection_role", "")),
                "edp": sample.get("metrics", {}).get("edp") if isinstance(sample.get("metrics"), Mapping) else None,
            }
            for sample in feedback_samples[:10]
        ],
        "feedback_samples_ref": _artifact_ref(out_dir / "feedback_samples.json"),
        "results": results,
        "artifact_payload_hashes": {
            "feedback_samples.json": _stable_payload_hash(feedback_payload),
        },
        "limitations": [
            "generic_sim_feedback_is_standalone_timing_projection_not_qe_physics_correctness",
            "not_hls_vivado_or_bitstream_evidence",
            "candidate_mapping_is_translated_from_L2_request_payload_for_step3_feedback",
        ],
        "claim_boundary": "l3_generic_sim_feedback_only_not_qe_correctness_or_fpga_bitstream_evidence",
    }
    _write_json(out_dir / "qe_fpga_l3_generic_sim_feedback.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run_l3_feedback(args)
    print(json.dumps({
        "status": report["status"],
        "out": str(args.out),
        "request_count": report["request_count"],
        "passed_count": report["passed_count"],
        "feedback_sample_count": report["feedback_sample_count"],
    }, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
