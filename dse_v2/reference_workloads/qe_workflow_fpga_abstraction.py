#!/usr/bin/env python3
"""QE workflow bundle abstraction for FPGA deployment DSE.

This module is QE-adapter scoped.  It converts QE workflow source bundles into
workload graph/features that Step2 FPGA deployment search can consume.  It does
not choose an architecture, mapping, schedule, or implementation result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from dse_v2.reference_workloads.dft import SourceFact, canonicalize_phase_id
from dse_v2.reference_workloads.dft_qe import (
    parse_qe_data_file_schema_xml,
    parse_qe_profile,
    parse_qe_pw_input,
    parse_qe_pw_log,
)


QE_WORKFLOW_FPGA_ABSTRACTION_SCHEMA = "dse.qe_workflow_fpga_abstraction.v1"
QE_NATIVE_WORKFLOW_BUNDLE_SCHEMA = "dse.qe.native_workflow_bundle.v1"

_POST_PROCESSING_STAGE_TYPES = {"bands", "dos", "projwfc"}
_ACCELERATOR_ELIGIBLE_KERNELS = {
    "fft",
    "h_psi",
    "projector",
    "reduction",
    "transpose",
    "band_path_projection",
    "forces",
    "stress",
    "v_of_rho",
}
_HOST_RETAINED_KERNELS = {
    "mix_rho",
    "mixing",
    "diagonalization",
    "scf_control",
    "io",
    "write_bands",
    "convergence_check",
    "charge_density",
}

_DEFAULT_BUNDLE_MANIFEST_NAMES = (
    "qe_workflow_bundle.json",
    "workflow_bundle.json",
    "bundle.json",
)


def load_qe_workflow_bundle(path: str | Path) -> Dict[str, Any]:
    """Load a QE workflow bundle manifest or directory.

    The returned mapping is normalized for downstream abstraction: manifest
    provenance is stamped into private metadata keys, and stage-local path
    fields are resolved relative to the manifest directory.
    """

    manifest_path = _resolve_bundle_manifest_path(Path(path))
    try:
        bundle = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid QE workflow bundle JSON: {manifest_path}: {exc}") from exc
    if not isinstance(bundle, Mapping):
        raise ValueError(f"QE workflow bundle must be a JSON object: {manifest_path}")
    root = manifest_path.parent
    normalized = dict(bundle)
    normalized["_bundle_manifest_path"] = str(manifest_path)
    normalized["_bundle_manifest_sha256"] = _sha256_file(manifest_path)
    normalized["_bundle_root"] = str(root)
    normalized.setdefault("schema_version", QE_NATIVE_WORKFLOW_BUNDLE_SCHEMA)
    stages = normalized.get("stages", [])
    if isinstance(stages, Sequence) and not isinstance(stages, (str, bytes)):
        normalized["stages"] = [
            _resolve_stage_paths(dict(stage), root=root) if isinstance(stage, Mapping) else stage
            for stage in stages
        ]
    return normalized


def build_qe_workflow_fpga_abstraction(
    bundle: Mapping[str, Any],
    *,
    workload_id: str | None = None,
) -> Dict[str, Any]:
    """Build a replayable QE workflow graph/feature abstraction for FPGA DSE."""

    stages = _bundle_stages(bundle)
    resolved_workload_id = str(workload_id or bundle.get("workflow_id") or bundle.get("workload_id") or "qe_workflow_bundle")
    stage_rows = [
        _stage_row(stage, index=index)
        for index, stage in enumerate(stages)
    ]
    nodes, edges = _graph_from_stage_rows(stage_rows)
    features = _features_from_stage_rows(stage_rows)
    data_objects = _data_objects_from_stage_rows(stage_rows, features)
    _append_data_object_lifetime_edges(edges, data_objects)
    _append_stage_artifact_dependency_edges(edges, stage_rows, data_objects)
    graph_summary = _graph_summary(nodes, edges)
    source_facts = [
        _fact_with_stage(fact, stage_id=row["stage_id"], stage_type=row["stage_type"])
        for row in stage_rows
        for fact in row["facts"]
    ]
    workflow_feature_contract = _workflow_feature_contract(
        workload_id=resolved_workload_id,
        stage_rows=stage_rows,
        nodes=nodes,
        edges=edges,
        features=features,
        data_objects=data_objects,
    )
    return {
        "schema_version": QE_WORKFLOW_FPGA_ABSTRACTION_SCHEMA,
        "workload_id": resolved_workload_id,
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            **_bundle_provenance(bundle),
            "workflow_id": str(bundle.get("workflow_id", resolved_workload_id)),
            "stage_count": len(stage_rows),
            "qe_programs": sorted({str(row["program"]) for row in stage_rows}),
            "observed_runtime": any(
                fact.get("evidence_level", "").startswith("observed")
                for fact in source_facts
            ),
            "artifact_dependency_count": _artifact_dependency_count(stage_rows),
        },
        "graph": {
            "graph_id": f"{resolved_workload_id}_fpga_dse_graph",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        },
        "graph_summary": graph_summary,
        "features": features,
        "data_objects": data_objects,
        "source_facts": source_facts,
        "workflow_feature_contract": workflow_feature_contract,
        "accelerator_eligible_kernel_hints": sorted(_ACCELERATOR_ELIGIBLE_KERNELS.intersection(features["kernel_weights"])),
        "host_retained_stage_hints": sorted(_HOST_RETAINED_KERNELS.intersection(features["kernel_weights"])),
        "model_assumptions": {
            "wavefunction_bytes": "max(nk,1) * max(nbnd,1) * max(npw,1) * sizeof(complex_fp64)",
            "charge_density_bytes": "max(nfft,1) * sizeof(fp64)",
            "data_movement_bytes": "stage artifact flow plus repeated wavefunction and charge-density traffic hints",
            "host_control_intensity": "observed host-retained phase time divided by observed phase time, plus SCF iteration pressure",
        },
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }


def write_qe_workflow_fpga_abstraction(
    bundle: Mapping[str, Any],
    out_path: str | Path,
    *,
    workload_id: str | None = None,
) -> Dict[str, Any]:
    payload = build_qe_workflow_fpga_abstraction(bundle, workload_id=workload_id)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def _resolve_bundle_manifest_path(path: Path) -> Path:
    if path.is_dir():
        for name in _DEFAULT_BUNDLE_MANIFEST_NAMES:
            candidate = path / name
            if candidate.is_file():
                return candidate
        names = ", ".join(_DEFAULT_BUNDLE_MANIFEST_NAMES)
        raise FileNotFoundError(f"QE workflow bundle directory lacks a manifest ({names}): {path}")
    if path.is_file():
        return path
    raise FileNotFoundError(f"QE workflow bundle manifest does not exist: {path}")


def _resolve_stage_paths(stage: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    for key in (
        "input_path",
        "pw_input_path",
        "log_path",
        "pw_log_path",
        "profile_path",
        "save_dir",
        "prefix_save_dir",
    ):
        if stage.get(key):
            stage[key] = _resolve_bundle_path(stage[key], root=root)
    if isinstance(stage.get("pseudopotential_paths"), Sequence) and not isinstance(stage.get("pseudopotential_paths"), (str, bytes)):
        stage["pseudopotential_paths"] = [
            _resolve_bundle_path(path, root=root)
            for path in stage.get("pseudopotential_paths", []) or []
        ]
    return stage


def _resolve_bundle_path(path: Any, *, root: Path) -> str:
    candidate = Path(str(path))
    if candidate.is_absolute():
        return str(candidate)
    return str(root / candidate)


def _bundle_provenance(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    source: Dict[str, Any] = {}
    if bundle.get("_bundle_manifest_path"):
        source["bundle_manifest"] = {
            "path": str(bundle.get("_bundle_manifest_path")),
            "sha256": str(bundle.get("_bundle_manifest_sha256", "")),
            "schema_version": str(bundle.get("schema_version", "")) or None,
        }
    if bundle.get("_bundle_root"):
        source["bundle_root"] = str(bundle.get("_bundle_root"))
    return source


def _bundle_stages(bundle: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    raw_stages = bundle.get("stages", [])
    if isinstance(raw_stages, Sequence) and not isinstance(raw_stages, (str, bytes)):
        return [stage if isinstance(stage, Mapping) else {"input": stage} for stage in raw_stages]
    return [{"program": "pw.x", "input": bundle}]


def _stage_row(stage: Mapping[str, Any], *, index: int) -> Dict[str, Any]:
    program = str(stage.get("program", "pw.x"))
    stage_type = _infer_stage_type(stage, program=program)
    stage_id = str(stage.get("stage_id") or f"stage_{index:02d}_{stage_type}")
    facts = _collect_stage_facts(stage, stage_id=stage_id, program=program)
    artifact_refs, artifact_facts = _stage_artifact_refs(stage, stage_id=stage_id)
    facts.extend(artifact_facts)
    values = _latest_fact_values(facts)
    timings = _phase_timings(facts)
    kernels = _stage_kernels(stage_type, timings)
    return {
        "stage_id": stage_id,
        "stage_type": stage_type,
        "program": program,
        "depends_on": [str(item) for item in stage.get("depends_on", []) or []],
        "artifact_refs": artifact_refs,
        "facts": facts,
        "values": values,
        "timings": timings,
        "kernels": kernels,
    }


def _collect_stage_facts(stage: Mapping[str, Any], *, stage_id: str, program: str) -> List[SourceFact]:
    run_id = str(stage.get("run_id", stage_id))
    facts: List[SourceFact] = []
    input_source = _first_present(stage, "pw_input", "input", "input_text")
    log_source = _first_present(stage, "pw_log", "log", "log_text", "stdout")
    profile_source = _first_present(stage, "profile", "profile_text", "profile_json", "timing")
    if input_source is not None and program.lower() == "pw.x":
        facts.extend(parse_qe_pw_input(input_source, source_path=_source_path_hint(stage, "input_path", "pw_input_path"), run_id=run_id))
    if log_source is not None:
        facts.extend(parse_qe_pw_log(log_source, source_path=_source_path_hint(stage, "log_path", "pw_log_path"), run_id=run_id))
    if profile_source is not None:
        facts.extend(parse_qe_profile(profile_source, source_path=_source_path_hint(stage, "profile_path"), run_id=run_id))
    for key, parser in [
        ("input_path", parse_qe_pw_input),
        ("pw_input_path", parse_qe_pw_input),
        ("log_path", parse_qe_pw_log),
        ("pw_log_path", parse_qe_pw_log),
        ("profile_path", parse_qe_profile),
    ]:
        if stage.get(key):
            facts.extend(parser(str(stage[key]), source_path=str(stage[key]), run_id=run_id))
    return facts


def _latest_fact_values(facts: Sequence[SourceFact]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    precedence: Dict[str, int] = {}
    for fact in facts:
        current = precedence.get(fact.field, -1)
        if fact.precedence >= current:
            values[fact.field] = fact.value
            precedence[fact.field] = fact.precedence
    return values


def _phase_timings(facts: Sequence[SourceFact]) -> Dict[str, float]:
    timings: Dict[str, float] = {}
    for fact in facts:
        if not fact.field.startswith("phase_timing.") or not fact.field.endswith(".wall_seconds"):
            continue
        phase = fact.field[len("phase_timing."):-len(".wall_seconds")]
        timings[phase] = timings.get(phase, 0.0) + _float(fact.value)
    return dict(sorted(timings.items()))


def _stage_kernels(stage_type: str, timings: Mapping[str, float]) -> List[str]:
    kernels = list(timings)
    if kernels:
        return sorted(kernels)
    defaults = {
        "scf": ["h_psi", "fft", "v_of_rho", "mix_rho", "diagonalization"],
        "nscf": ["h_psi", "fft", "diagonalization"],
        "relax": ["h_psi", "fft", "forces", "mix_rho"],
        "vc_relax": ["h_psi", "fft", "forces", "stress", "mix_rho"],
        "bands": ["band_path_projection", "write_bands"],
        "dos": ["reduction", "io"],
        "projwfc": ["projector", "reduction", "io"],
    }
    return defaults.get(stage_type, ["stage_compute"])


def _graph_from_stage_rows(stage_rows: Sequence[Mapping[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    previous_stage_control: str | None = None
    stage_ids = {str(row["stage_id"]) for row in stage_rows}
    for row in stage_rows:
        stage_id = str(row["stage_id"])
        stage_type = str(row["stage_type"])
        values = row["values"] if isinstance(row.get("values"), Mapping) else {}
        timings = row["timings"] if isinstance(row.get("timings"), Mapping) else {}
        control_node = f"{stage_id}:control"
        nodes.append(_node(control_node, stage_id, stage_type, "host_control", values, 0.0))
        explicit_dependencies = [dep for dep in row.get("depends_on", []) or [] if str(dep) in stage_ids]
        if explicit_dependencies:
            for source_stage in explicit_dependencies:
                edges.append(_edge(f"{source_stage}:control", control_node, "stage_order", "stage_order"))
        elif previous_stage_control is not None:
            edges.append(_edge(previous_stage_control, control_node, "stage_order", "stage_order"))
        last_kernel_node = control_node
        for kernel in row.get("kernels", []) or []:
            kernel_id = str(kernel)
            kernel_node = f"{stage_id}:{kernel_id}"
            nodes.append(_node(kernel_node, stage_id, stage_type, kernel_id, values, _float(timings.get(kernel_id))))
            edges.append(_edge(control_node, kernel_node, f"{stage_id}_{kernel_id}_dispatch", "control"))
            if last_kernel_node != control_node:
                edges.append(_edge(last_kernel_node, kernel_node, f"{stage_id}_{kernel_id}_dataflow", "data"))
            last_kernel_node = kernel_node
        previous_stage_control = control_node
    return nodes, edges


def _graph_summary(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    node_by_id = {
        str(node.get("node_id", "")): node
        for node in nodes
        if isinstance(node, Mapping) and node.get("node_id")
    }
    placement_counts: Dict[str, int] = {}
    op_type_counts: Dict[str, int] = {}
    in_degree: Dict[str, int] = {node_id: 0 for node_id in node_by_id}
    out_degree: Dict[str, int] = {node_id: 0 for node_id in node_by_id}
    edge_kind_counts: Dict[str, int] = {}
    inter_stage_edges = 0
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        placement = str(node.get("placement_hint", "unknown"))
        placement_counts[placement] = placement_counts.get(placement, 0) + 1
        op_type = str(node.get("op_type", "unknown"))
        op_type_counts[op_type] = op_type_counts.get(op_type, 0) + 1
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("source_node", ""))
        target = str(edge.get("target_node", ""))
        edge_kind = str(edge.get("edge_kind", "unknown"))
        edge_kind_counts[edge_kind] = edge_kind_counts.get(edge_kind, 0) + 1
        if source in out_degree:
            out_degree[source] += 1
        if target in in_degree:
            in_degree[target] += 1
        source_stage = str(node_by_id.get(source, {}).get("stage_id", ""))
        target_stage = str(node_by_id.get(target, {}).get("stage_id", ""))
        if source_stage and target_stage and source_stage != target_stage:
            inter_stage_edges += 1
    node_count = len(node_by_id)
    edge_count = len([edge for edge in edges if isinstance(edge, Mapping)])
    host_node_count = placement_counts.get("host", 0)
    accelerator_node_count = placement_counts.get("fpga_candidate", 0)
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "host_node_count": host_node_count,
        "accelerator_node_count": accelerator_node_count,
        "host_node_ratio": _round(host_node_count / float(max(1, node_count))),
        "accelerator_node_ratio": _round(accelerator_node_count / float(max(1, node_count))),
        "control_edge_count": edge_kind_counts.get("control", 0),
        "data_edge_count": edge_kind_counts.get("data", 0),
        "state_edge_count": edge_kind_counts.get("state", 0),
        "inter_stage_edge_count": inter_stage_edges,
        "inter_stage_edge_ratio": _round(inter_stage_edges / float(max(1, edge_count))),
        "max_in_degree": max(in_degree.values()) if in_degree else 0,
        "max_out_degree": max(out_degree.values()) if out_degree else 0,
        "mean_in_degree": _round(sum(in_degree.values()) / float(max(1, node_count))),
        "mean_out_degree": _round(sum(out_degree.values()) / float(max(1, node_count))),
        "graph_density": _round(edge_count / float(max(1, node_count))),
        "edge_kind_counts": dict(sorted(edge_kind_counts.items())),
        "placement_hint_counts": dict(sorted(placement_counts.items())),
        "op_type_counts": dict(sorted(op_type_counts.items())),
    }


def _node(
    node_id: str,
    stage_id: str,
    stage_type: str,
    op_type: str,
    values: Mapping[str, Any],
    observed_wall_seconds: float,
) -> Dict[str, Any]:
    dims = _dimensions(values)
    memory_bytes = _kernel_memory_hint(op_type, dims)
    flops = _kernel_flop_hint(op_type, dims)
    return {
        "node_id": node_id,
        "stage_id": stage_id,
        "stage_type": stage_type,
        "op_type": op_type,
        "observed_wall_seconds": observed_wall_seconds,
        "estimated_flops": flops,
        "estimated_memory_bytes": memory_bytes,
        "dimensions": dims,
        "placement_hint": "host" if op_type in _HOST_RETAINED_KERNELS or op_type == "host_control" else "fpga_candidate",
    }


def _edge(source: str, target: str, tensor_name: str, edge_kind: str) -> Dict[str, Any]:
    return {
        "source_node": source,
        "target_node": target,
        "tensor_name": tensor_name,
        "edge_kind": edge_kind,
    }


def _features_from_stage_rows(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    workflow_classes = sorted({_workflow_class(str(row["stage_type"])) for row in stage_rows})
    max_dims = {"nbnd": 0, "npw": 0, "nfft": 0, "kpoint_count": 0, "nat": 0, "ntyp": 0}
    kernel_weights: Dict[str, float] = {}
    total_timing = 0.0
    scf_iteration_count = 0
    for row in stage_rows:
        values = row["values"] if isinstance(row.get("values"), Mapping) else {}
        dims = _dimensions(values)
        for key in max_dims:
            max_dims[key] = max(max_dims[key], int(dims.get(key, 0)))
        scf_iteration_count = max(scf_iteration_count, int(_float(values.get("iteration.scf.count"))))
        timings = row["timings"] if isinstance(row.get("timings"), Mapping) else {}
        if timings:
            for kernel, seconds in timings.items():
                kernel_weights[str(kernel)] = kernel_weights.get(str(kernel), 0.0) + _float(seconds)
                total_timing += _float(seconds)
        else:
            for kernel in row.get("kernels", []) or []:
                kernel_weights[str(kernel)] = kernel_weights.get(str(kernel), 0.0) + 0.1
                total_timing += 0.1
    wavefunction_bytes = max_dims["kpoint_count"] * max(1, max_dims["nbnd"]) * max(1, max_dims["npw"]) * 16
    charge_density_bytes = max(1, max_dims["nfft"]) * 8
    total_data_movement = wavefunction_bytes * max(1, len(stage_rows)) + charge_density_bytes * max(1, len(stage_rows) - 1)
    host_time = sum(value for key, value in kernel_weights.items() if key in _HOST_RETAINED_KERNELS)
    host_control_intensity = min(1.0, (host_time / total_timing) if total_timing > 0 else 0.0)
    if scf_iteration_count > 1:
        host_control_intensity = min(1.0, host_control_intensity + 0.05 * (scf_iteration_count - 1))
    return {
        "workflow_classes": workflow_classes,
        "stage_count": len(stage_rows),
        "kernel_weights": dict(sorted(kernel_weights.items())),
        "observed_total_phase_wall_seconds": _round(total_timing),
        "max_dimensions": max_dims,
        "runtime_environment": _runtime_environment(stage_rows),
        "pseudopotentials": _pseudopotentials(stage_rows),
        "scf_iteration_count_observed": scf_iteration_count,
        "stage_repetition": _stage_repetition(stage_rows),
        "host_control_events": _host_control_events(stage_rows),
        "correctness_observables": _correctness_observables(stage_rows),
        "estimated_wavefunction_bytes": int(wavefunction_bytes),
        "estimated_charge_density_bytes": int(charge_density_bytes),
        "estimated_total_data_movement_bytes": int(total_data_movement),
        "host_control_intensity": _round(host_control_intensity),
        "data_movement_intensity": _round(total_data_movement / max(1.0, total_timing * 1.0e9)),
    }


def _stage_repetition(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    repetitions: Dict[str, Dict[str, Any]] = {}
    for row in stage_rows:
        stage_id = str(row["stage_id"])
        stage_type = str(row["stage_type"])
        values = row["values"] if isinstance(row.get("values"), Mapping) else {}
        observed_iterations = int(_float(values.get("iteration.scf.count")))
        declared_maxstep = int(_float(values.get("iteration.scf.maxstep")))
        if stage_type == "scf":
            repetition_kind = "scf_iteration_loop"
        elif stage_type == "nscf":
            repetition_kind = "single_electronic_spectrum_pass"
        elif stage_type in {"relax", "vc_relax"}:
            repetition_kind = "ionic_outer_loop"
        elif stage_type in _POST_PROCESSING_STAGE_TYPES:
            repetition_kind = "single_post_processing_pass"
        else:
            repetition_kind = "single_stage"
        repetitions[stage_id] = {
            "stage_type": stage_type,
            "repetition_kind": repetition_kind,
            "observed_iterations": max(1, observed_iterations) if repetition_kind == "scf_iteration_loop" else 1,
            "declared_max_iterations": declared_maxstep if declared_maxstep > 0 else None,
            "host_control_barrier_per_iteration": repetition_kind == "scf_iteration_loop",
        }
    return repetitions


def _host_control_events(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    scf_checks = 0
    diagonalization_events = 0
    post_processing_stage_count = 0
    io_checkpoint_events = 0
    retained_kernels: Dict[str, int] = {}
    for row in stage_rows:
        stage_type = str(row["stage_type"])
        values = row["values"] if isinstance(row.get("values"), Mapping) else {}
        iterations = max(1, int(_float(values.get("iteration.scf.count"))))
        if stage_type in {"scf", "relax", "vc_relax"}:
            scf_checks += iterations
        if stage_type in {"scf", "nscf", "relax", "vc_relax"}:
            io_checkpoint_events += 1
        if stage_type in _POST_PROCESSING_STAGE_TYPES:
            post_processing_stage_count += 1
            io_checkpoint_events += 1
        for kernel in row.get("kernels", []) or []:
            kernel_id = str(kernel)
            if kernel_id in _HOST_RETAINED_KERNELS:
                retained_kernels[kernel_id] = retained_kernels.get(kernel_id, 0) + 1
                if kernel_id == "diagonalization":
                    diagonalization_events += iterations
    return {
        "scf_convergence_check_count": scf_checks,
        "diagonalization_event_count": diagonalization_events,
        "post_processing_stage_count": post_processing_stage_count,
        "io_checkpoint_event_count": io_checkpoint_events,
        "retained_kernel_counts": dict(sorted(retained_kernels.items())),
    }


def _correctness_observables(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    stage_types = {str(row["stage_type"]) for row in stage_rows}
    workflow = ["total_energy", "charge_density_residual", "eigenvalue_spectrum"]
    if stage_types.intersection(_POST_PROCESSING_STAGE_TYPES):
        workflow.append("band_structure")
    if stage_types.intersection({"relax", "vc_relax"}):
        workflow.extend(["forces", "stress"])
    per_stage: Dict[str, List[str]] = {}
    for row in stage_rows:
        stage_id = str(row["stage_id"])
        stage_type = str(row["stage_type"])
        observables = ["stage_exit_status"]
        if stage_type in {"scf", "nscf", "relax", "vc_relax"}:
            observables.extend(["total_energy", "charge_density_residual", "eigenvalue_spectrum"])
        if stage_type in {"relax", "vc_relax"}:
            observables.extend(["forces", "stress"])
        if stage_type in _POST_PROCESSING_STAGE_TYPES:
            observables.append("post_processing_output")
        per_stage[stage_id] = observables
    observed_values = _observed_correctness_values(stage_rows)
    return {
        "workflow": workflow,
        "per_stage": per_stage,
        "observed_values": observed_values,
        "kernel_tolerance_policy": {
            "fp64_relative_tolerance": 1.0e-10,
            "energy_absolute_tolerance_ry": 1.0e-8,
            "force_absolute_tolerance_ry_per_bohr": 1.0e-6,
        },
    }


def _runtime_environment(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    values = _merged_values(stage_rows)
    return {
        "qe_version": str(values.get("runtime.qe_version", "")) or None,
        "mpi_processes": int(_float(values.get("runtime.mpi_processes"))) or None,
        "openmp_threads": int(_float(values.get("runtime.openmp_threads"))) or None,
    }


def _pseudopotentials(stage_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for row in stage_rows:
        for artifact in row.get("artifact_refs", []) or []:
            if not isinstance(artifact, Mapping) or artifact.get("artifact_kind") != "pseudopotential":
                continue
            path = str(artifact.get("path", ""))
            if path:
                rows[path] = dict(artifact)
    return [rows[path] for path in sorted(rows)]


def _observed_correctness_values(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    values = _merged_values(stage_rows)
    fields = {
        "final_total_energy_ry": "observable.final_total_energy_ry",
        "scf_accuracy_ry": "observable.scf_accuracy_ry",
        "fermi_energy_ev": "observable.fermi_energy_ev",
        "eigenvalue_count": "observable.eigenvalue_count",
        "occupation_count": "observable.occupation_count",
        "eigenvalue_min_ev": "observable.eigenvalue_min_ev",
        "eigenvalue_max_ev": "observable.eigenvalue_max_ev",
    }
    observed: Dict[str, Any] = {}
    for output_name, fact_name in fields.items():
        if fact_name in values:
            observed[output_name] = values[fact_name]
    return observed


def _merged_values(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for row in stage_rows:
        values = row.get("values", {})
        if isinstance(values, Mapping):
            merged.update(values)
    return merged


def _data_objects_from_stage_rows(
    stage_rows: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    wavefunction_bytes = int(features.get("estimated_wavefunction_bytes", 0))
    charge_density_bytes = int(features.get("estimated_charge_density_bytes", 0))
    observed_save_dir = _observed_save_dir(stage_rows)
    if observed_save_dir:
        wavefunction_bytes = max(wavefunction_bytes, int(observed_save_dir.get("wavefunction_bytes", 0)))
        charge_density_bytes = max(charge_density_bytes, int(observed_save_dir.get("charge_density_bytes", 0)))
    stage_ids = [str(row["stage_id"]) for row in stage_rows]
    scf_like = [str(row["stage_id"]) for row in stage_rows if str(row["stage_type"]) in {"scf", "nscf", "relax", "vc_relax"}]
    post_processing = [str(row["stage_id"]) for row in stage_rows if str(row["stage_type"]) in _POST_PROCESSING_STAGE_TYPES]
    first_scf = scf_like[0] if scf_like else (stage_ids[0] if stage_ids else "")
    last_scf = scf_like[-1] if scf_like else (stage_ids[-1] if stage_ids else "")
    return {
        "psi": {
            "object_kind": "wavefunction_coefficients",
            "bytes": wavefunction_bytes,
            "producer_stages": [first_scf] if first_scf else [],
            "consumer_stages": [stage for stage in stage_ids if stage != first_scf],
            "lifetime": "scf_to_nscf_or_post_processing_reuse",
            "preferred_residency_hint": "fpga_hbm_or_host_pinned_reuse",
        },
        "rho": {
            "object_kind": "charge_density",
            "bytes": charge_density_bytes,
            "producer_stages": scf_like[:1],
            "consumer_stages": scf_like[1:] + post_processing,
            "lifetime": "scf_iteration_feedback_and_checkpoint",
            "preferred_residency_hint": "host_visible_checkpoint_with_optional_fpga_cache",
        },
        "v_of_rho": {
            "object_kind": "effective_potential",
            "bytes": charge_density_bytes,
            "producer_stages": scf_like[:1],
            "consumer_stages": scf_like,
            "lifetime": "within_scf_iteration_recomputed",
            "preferred_residency_hint": "fpga_local_cache_when_v_of_rho_accelerated",
        },
        "eigenvalues": {
            "object_kind": "eigenvalue_spectrum",
            "bytes": max(1, len(stage_rows)) * max(1, int(features.get("max_dimensions", {}).get("nbnd", 0))) * 8,
            "producer_stages": scf_like,
            "consumer_stages": post_processing,
            "lifetime": "workflow_metadata_reused_by_post_processing",
            "preferred_residency_hint": "host_metadata_with_optional_device_shadow",
        },
        "qe_save_dir": {
            "object_kind": "qe_prefix_save_directory",
            "bytes": int(observed_save_dir.get("bytes", wavefunction_bytes + charge_density_bytes)) if observed_save_dir else wavefunction_bytes + charge_density_bytes,
            "producer_stages": [last_scf] if last_scf else [],
            "consumer_stages": post_processing,
            "lifetime": "disk_checkpoint_between_qe_programs",
            "preferred_residency_hint": "host_filesystem_checkpoint_not_accelerator_resident",
            **({
                "observed_path": observed_save_dir["path"],
                "observed_file_count": observed_save_dir["file_count"],
                "metadata_xml_count": observed_save_dir.get("metadata_xml_count", 0),
                "artifacts": observed_save_dir["artifacts"],
            } if observed_save_dir else {}),
        },
    }


def _workflow_feature_contract(
    *,
    workload_id: str,
    stage_rows: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
    data_objects: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    stage_repetition = features.get("stage_repetition", {}) if isinstance(features.get("stage_repetition"), Mapping) else {}
    return {
        "schema_version": "dse.workflow_feature_contract.v1",
        "domain_neutral": True,
        "source_adapter": "qe_workflow_fpga_abstraction",
        "workload_family": "qe",
        "workflow_id": workload_id,
        "workflow_dag": {
            "stage_count": len(stage_rows),
            "stages": [
                _contract_stage_row(row, stage_repetition)
                for row in stage_rows
            ],
            "edges": _contract_stage_edges(stage_rows, edges),
        },
        "stage_feature_table": [
            _contract_stage_feature(row, features, stage_repetition)
            for row in stage_rows
        ],
        "stage_compute_feature_table": _contract_stage_compute_features(stage_rows, features),
        "data_object_table": [
            _contract_data_object(object_id, payload)
            for object_id, payload in sorted(data_objects.items())
            if isinstance(payload, Mapping)
        ],
        "compute_feature_table": _contract_compute_features(features, nodes),
        "correctness_observable_table": copy_mapping(
            features.get("correctness_observables", {})
            if isinstance(features.get("correctness_observables"), Mapping)
            else {}
        ),
        "search_objectives": [
            "latency",
            "energy",
            "edp",
            "resource_pressure",
            "data_movement",
            "feasibility_risk",
        ],
        "model_update_policy": {
            "cheap_models": ["analytical", "tlm", "surrogate"],
            "calibration_feedback": ["systemc", "gem5", "hls_synthesis", "vivado_implementation"],
            "final_validation": ["golden_correctness", "vivado_bitstream_or_board"],
            "evidence_role": "calibration_validation_and_reporting_not_search_objective",
        },
        "claim_boundary": "workflow_features_only_not_evidence_not_candidate_identity",
    }


def _contract_stage_row(
    row: Mapping[str, Any],
    stage_repetition: Mapping[str, Any],
) -> Dict[str, Any]:
    stage_id = str(row["stage_id"])
    repetition = stage_repetition.get(stage_id, {}) if isinstance(stage_repetition.get(stage_id), Mapping) else {}
    return {
        "stage_id": stage_id,
        "stage_type": str(row["stage_type"]),
        "stage_class": _workflow_class(str(row["stage_type"])),
        "program": str(row["program"]),
        "depends_on": [str(item) for item in row.get("depends_on", []) or []],
        "repetition": {
            "kind": str(repetition.get("repetition_kind", "single_stage")),
            "observed_iterations": int(_float(repetition.get("observed_iterations", 1))),
            "declared_max_iterations": repetition.get("declared_max_iterations"),
            "host_control_barrier_per_iteration": bool(repetition.get("host_control_barrier_per_iteration", False)),
        },
    }


def _contract_stage_edges(
    stage_rows: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    stage_ids = {str(row["stage_id"]) for row in stage_rows}
    rows: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("source_node", "")).split(":", 1)[0]
        target = str(edge.get("target_node", "")).split(":", 1)[0]
        if source not in stage_ids or target not in stage_ids or source == target:
            continue
        tensor_name = str(edge.get("tensor_name", ""))
        edge_kind = str(edge.get("edge_kind", "unknown"))
        if tensor_name == "stage_order":
            edge_kind = "stage_order"
        key = (source, target, edge_kind, tensor_name)
        rows[key] = {
            "source_stage": source,
            "target_stage": target,
            "edge_kind": edge_kind,
            "tensor_name": tensor_name,
            "estimated_bytes": int(_float(edge.get("estimated_bytes", 0))),
            "residency_hint": str(edge.get("residency_hint", "")),
        }
    return [rows[key] for key in sorted(rows)]


def _contract_stage_feature(
    row: Mapping[str, Any],
    features: Mapping[str, Any],
    stage_repetition: Mapping[str, Any],
) -> Dict[str, Any]:
    stage_id = str(row["stage_id"])
    stage_type = str(row["stage_type"])
    repetition = stage_repetition.get(stage_id, {}) if isinstance(stage_repetition.get(stage_id), Mapping) else {}
    values = row.get("values", {}) if isinstance(row.get("values"), Mapping) else {}
    return {
        "stage_id": stage_id,
        "stage_type": stage_type,
        "stage_class": _workflow_class(stage_type),
        "program": str(row["program"]),
        "dimensions": _dimensions(values),
        "expected_repetition": max(1, int(_float(repetition.get("observed_iterations", 1)))),
        "host_control_barrier": bool(repetition.get("host_control_barrier_per_iteration", False)),
        "include_in_performance_model": True,
        "observed_wall_seconds": _round(sum(_float(value) for value in (row.get("timings", {}) if isinstance(row.get("timings"), Mapping) else {}).values())),
        "source_confidence": "observed" if row.get("timings") else "estimated",
        "compute_ids": list(row.get("kernels", []) or []),
    }


def _contract_stage_compute_features(
    stage_rows: Sequence[Mapping[str, Any]],
    features: Mapping[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    kernel_weights = features.get("kernel_weights", {}) if isinstance(features.get("kernel_weights"), Mapping) else {}
    contract: Dict[str, List[Dict[str, Any]]] = {}
    for row in stage_rows:
        stage_id = str(row["stage_id"])
        compute_rows: List[Dict[str, Any]] = []
        timings = row.get("timings", {}) if isinstance(row.get("timings"), Mapping) else {}
        for compute_id in list(row.get("kernels", []) or []):
            compute_name = str(compute_id)
            weight_seconds = _float(timings.get(compute_name))
            if weight_seconds <= 0.0:
                weight_seconds = _float(kernel_weights.get(compute_name))
            if weight_seconds <= 0.0:
                weight_seconds = 0.1
            compute_rows.append({
                "compute_id": compute_name,
                "weight_seconds": _round(weight_seconds),
                "source_confidence": "observed" if compute_name in timings else "estimated",
                "uncertainty": {
                    "kind": "relative_weight_interval",
                    "relative_low": 0.85 if compute_name in timings else 0.50,
                    "relative_high": 1.15 if compute_name in timings else 1.75,
                },
            })
        contract[stage_id] = compute_rows
    return contract


def _contract_data_object(object_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "object_id": str(object_id),
        "object_kind": str(payload.get("object_kind", "")),
        "bytes": int(_float(payload.get("bytes", 0))),
        "producer_stages": [str(item) for item in payload.get("producer_stages", []) or []],
        "consumer_stages": [str(item) for item in payload.get("consumer_stages", []) or []],
        "lifetime": str(payload.get("lifetime", "")),
        "residency_constraint": str(payload.get("preferred_residency_hint", "")),
        "transfer_sync_requirement": _transfer_sync_requirement(payload),
    }


def _contract_compute_features(
    features: Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    kernel_weights = features.get("kernel_weights", {}) if isinstance(features.get("kernel_weights"), Mapping) else {}
    observed_total = _float(features.get("observed_total_phase_wall_seconds"))
    rows: List[Dict[str, Any]] = []
    node_by_op: Dict[str, List[Mapping[str, Any]]] = {}
    for node in nodes:
        if isinstance(node, Mapping):
            node_by_op.setdefault(str(node.get("op_type", "")), []).append(node)
    for compute_id, raw_weight in sorted(kernel_weights.items()):
        weight = _float(raw_weight)
        if weight <= 0.0:
            continue
        related_nodes = node_by_op.get(str(compute_id), [])
        memory_bytes = max([_float(node.get("estimated_memory_bytes")) for node in related_nodes] or [0.0])
        flops = max([_float(node.get("estimated_flops")) for node in related_nodes] or [0.0])
        source_confidence = "observed" if observed_total > 0.0 else "estimated"
        rows.append({
            "compute_id": str(compute_id),
            "weight_seconds": _round(weight),
            "source_confidence": source_confidence,
            "uncertainty": {
                "kind": "relative_weight_interval",
                "relative_low": 0.85 if source_confidence == "observed" else 0.50,
                "relative_high": 1.15 if source_confidence == "observed" else 1.75,
            },
            "estimated_memory_bytes": int(memory_bytes),
            "estimated_flops": int(flops),
            "accelerator_candidate": str(compute_id) in _ACCELERATOR_ELIGIBLE_KERNELS,
            "host_retained_hint": str(compute_id) in _HOST_RETAINED_KERNELS,
        })
    return rows


def _transfer_sync_requirement(payload: Mapping[str, Any]) -> str:
    residency = str(payload.get("preferred_residency_hint", ""))
    if "host_filesystem" in residency:
        return "host_checkpoint_barrier"
    if "host_visible" in residency:
        return "host_visible_sync"
    if "fpga" in residency:
        return "device_residency_or_dma_overlap"
    return "unspecified"


def copy_mapping(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _stage_artifact_refs(stage: Mapping[str, Any], *, stage_id: str) -> tuple[List[Dict[str, Any]], List[SourceFact]]:
    refs: List[Dict[str, Any]] = []
    facts: List[SourceFact] = []
    save_dir = stage.get("save_dir") or stage.get("prefix_save_dir")
    if save_dir:
        scanned = _scan_path_artifacts(Path(str(save_dir)), artifact_kind="qe_save_dir")
        refs.append(scanned)
        facts.append(SourceFact(
            "artifact.qe_save_dir.bytes",
            scanned["bytes"],
            unit="bytes",
            source_type="generated",
            source_path=scanned["path"],
            evidence_level="observed_artifact",
            confidence="high" if scanned["exists"] else "low",
            run_id=stage_id,
        ))
        facts.append(SourceFact(
            "artifact.qe_save_dir.file_count",
            scanned["file_count"],
            unit="count",
            source_type="generated",
            source_path=scanned["path"],
            evidence_level="observed_artifact",
            confidence="high" if scanned["exists"] else "low",
            run_id=stage_id,
        ))
        for xml_ref in scanned.get("artifacts", []) or []:
            if not isinstance(xml_ref, Mapping) or xml_ref.get("artifact_kind") != "qe_metadata_xml":
                continue
            xml_path = str(xml_ref.get("path", ""))
            if not xml_path:
                continue
            facts.append(SourceFact(
                "artifact.qe_metadata_xml.sha256",
                xml_ref.get("sha256"),
                source_type="generated",
                source_path=xml_path,
                evidence_level="observed_artifact",
                confidence="high" if xml_ref.get("exists") else "low",
                run_id=stage_id,
            ))
            if xml_ref.get("exists"):
                facts.extend(parse_qe_data_file_schema_xml(xml_path, source_path=xml_path, run_id=stage_id))
    for path_value in stage.get("pseudopotential_paths", []) or []:
        path = Path(str(path_value))
        ref = _file_artifact_ref(path, artifact_kind="pseudopotential")
        refs.append(ref)
        facts.append(SourceFact(
            "artifact.pseudopotential.sha256",
            ref["sha256"],
            source_type="input",
            source_path=ref["path"],
            evidence_level="observed_input_artifact",
            confidence="high" if ref["exists"] else "low",
            run_id=stage_id,
        ))
    return refs, facts


def _scan_path_artifacts(path: Path, *, artifact_kind: str) -> Dict[str, Any]:
    artifacts: List[Dict[str, Any]] = []
    total_bytes = 0
    wavefunction_bytes = 0
    charge_density_bytes = 0
    exists = path.exists()
    if exists and path.is_dir():
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            ref = _file_artifact_ref(child, artifact_kind=_qe_save_artifact_kind(child))
            artifacts.append(ref)
            size = int(ref.get("size_bytes", 0))
            total_bytes += size
            lower_name = child.name.lower()
            if lower_name.startswith("wfc") or "wave" in lower_name:
                wavefunction_bytes += size
            if "charge" in lower_name or "rho" in lower_name:
                charge_density_bytes += size
    elif exists and path.is_file():
        ref = _file_artifact_ref(path, artifact_kind=artifact_kind)
        artifacts.append(ref)
        total_bytes = int(ref.get("size_bytes", 0))
    return {
        "artifact_kind": artifact_kind,
        "path": str(path),
        "exists": exists,
        "bytes": total_bytes,
        "file_count": len(artifacts),
        "wavefunction_bytes": wavefunction_bytes,
        "charge_density_bytes": charge_density_bytes,
        "artifacts": artifacts,
    }


def _file_artifact_ref(path: Path, *, artifact_kind: str) -> Dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "artifact_kind": artifact_kind,
        "path": str(path),
        "exists": exists,
        "size_bytes": int(path.stat().st_size) if exists else 0,
        "sha256": _sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _qe_save_artifact_kind(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("wfc") or "wave" in name:
        return "wavefunction_checkpoint"
    if "charge" in name or "rho" in name:
        return "charge_density_checkpoint"
    if name.endswith(".xml"):
        return "qe_metadata_xml"
    return "qe_save_file"


def _observed_save_dir(stage_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    save_dirs = [
        artifact
        for row in stage_rows
        for artifact in row.get("artifact_refs", []) or []
        if isinstance(artifact, Mapping) and artifact.get("artifact_kind") == "qe_save_dir"
    ]
    if not save_dirs:
        return {}
    merged = {
        "path": str(save_dirs[0].get("path", "")),
        "bytes": sum(int(item.get("bytes", 0)) for item in save_dirs),
        "file_count": sum(int(item.get("file_count", 0)) for item in save_dirs),
        "metadata_xml_count": 0,
        "wavefunction_bytes": sum(int(item.get("wavefunction_bytes", 0)) for item in save_dirs),
        "charge_density_bytes": sum(int(item.get("charge_density_bytes", 0)) for item in save_dirs),
        "artifacts": [],
    }
    for item in save_dirs:
        artifacts = list(item.get("artifacts", []) or [])
        merged["artifacts"].extend(artifacts)
        merged["metadata_xml_count"] += sum(
            1
            for artifact in artifacts
            if isinstance(artifact, Mapping) and artifact.get("artifact_kind") == "qe_metadata_xml"
        )
    return merged


def _artifact_dependency_count(stage_rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(row.get("depends_on", []) or []) for row in stage_rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _append_data_object_lifetime_edges(
    edges: List[Dict[str, Any]],
    data_objects: Mapping[str, Mapping[str, Any]],
) -> None:
    for object_id, payload in data_objects.items():
        producers = [str(stage) for stage in payload.get("producer_stages", []) or []]
        consumers = [str(stage) for stage in payload.get("consumer_stages", []) or []]
        for producer in producers:
            for consumer in consumers:
                if producer == consumer:
                    continue
                edges.append({
                    "source_node": f"{producer}:control",
                    "target_node": f"{consumer}:control",
                    "tensor_name": str(object_id),
                    "edge_kind": "data_object_lifetime",
                    "estimated_bytes": int(payload.get("bytes", 0)),
                    "residency_hint": str(payload.get("preferred_residency_hint", "")),
                })


def _append_stage_artifact_dependency_edges(
    edges: List[Dict[str, Any]],
    stage_rows: Sequence[Mapping[str, Any]],
    data_objects: Mapping[str, Mapping[str, Any]],
) -> None:
    qe_save_dir = data_objects.get("qe_save_dir", {})
    estimated_bytes = int(qe_save_dir.get("bytes", 0)) if isinstance(qe_save_dir, Mapping) else 0
    stage_ids = {str(row["stage_id"]) for row in stage_rows}
    for row in stage_rows:
        target_stage = str(row["stage_id"])
        explicit_dependencies = [dep for dep in row.get("depends_on", []) or [] if str(dep) in stage_ids]
        for source_stage in explicit_dependencies:
            edges.append({
                "source_node": f"{source_stage}:control",
                "target_node": f"{target_stage}:control",
                "tensor_name": "qe_save_dir",
                "edge_kind": "stage_artifact_dependency",
                "estimated_bytes": estimated_bytes,
                "residency_hint": "host_filesystem_checkpoint_not_accelerator_resident",
            })


def _dimensions(values: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "nbnd": int(_float(values.get("dimension.nbnd"))),
        "npw": int(_float(values.get("dimension.npw"))),
        "nfft": int(_float(values.get("dimension.nfft"))),
        "kpoint_count": int(_float(values.get("dimension.kpoint_count"))),
        "nat": int(_float(values.get("dimension.nat"))),
        "ntyp": int(_float(values.get("dimension.ntyp"))),
    }


def _kernel_memory_hint(op_type: str, dims: Mapping[str, int]) -> float:
    nbnd = max(1, int(dims.get("nbnd", 0)))
    npw = max(1, int(dims.get("npw", 0)))
    nfft = max(1, int(dims.get("nfft", 0)))
    if op_type in {"h_psi", "projector", "band_path_projection"}:
        return float(nbnd * npw * 16 * 2)
    if op_type in {"fft", "v_of_rho", "transpose"}:
        return float(nfft * 16 * 2)
    if op_type in {"mix_rho", "reduction", "forces", "stress"}:
        return float(nfft * 8 * 2)
    return float(max(nbnd * npw * 16, nfft * 8))


def _kernel_flop_hint(op_type: str, dims: Mapping[str, int]) -> float:
    nbnd = max(1, int(dims.get("nbnd", 0)))
    npw = max(1, int(dims.get("npw", 0)))
    nfft = max(1, int(dims.get("nfft", 0)))
    if op_type == "h_psi":
        return float(nbnd * npw * 64)
    if op_type == "fft":
        return float(nfft * 5)
    if op_type == "diagonalization":
        return float(nbnd ** 3)
    if op_type in {"projector", "band_path_projection"}:
        return float(nbnd * npw * 16)
    return float(max(nbnd * npw, nfft))


def _infer_stage_type(stage: Mapping[str, Any], *, program: str) -> str:
    if stage.get("stage_type"):
        return _normalize_stage_type(str(stage["stage_type"]))
    if stage.get("calculation"):
        return _normalize_stage_type(str(stage["calculation"]))
    program_lower = program.lower()
    if "bands" in program_lower:
        return "bands"
    if "dos" in program_lower:
        return "dos"
    if "projwfc" in program_lower:
        return "projwfc"
    input_source = _first_present(stage, "pw_input", "input", "input_text")
    if input_source is not None:
        for fact in parse_qe_pw_input(input_source):
            if fact.field == "input.calculation":
                return _normalize_stage_type(str(fact.value))
    for key in ("input_path", "pw_input_path"):
        if stage.get(key):
            try:
                for fact in parse_qe_pw_input(str(stage[key]), source_path=str(stage[key])):
                    if fact.field == "input.calculation":
                        return _normalize_stage_type(str(fact.value))
            except Exception:
                pass
    return "scf" if program_lower == "pw.x" else "unknown"


def _normalize_stage_type(value: str) -> str:
    normalized = str(value).strip().strip("'\"").lower().replace("-", "_")
    if normalized in {"scf", "nscf", "relax", "vc_relax", "bands", "dos", "projwfc"}:
        return normalized
    if "relax" in normalized:
        return "relax"
    return normalized or "unknown"


def _workflow_class(stage_type: str) -> str:
    if stage_type in _POST_PROCESSING_STAGE_TYPES:
        return "post_processing"
    return stage_type


def _fact_with_stage(fact: SourceFact, *, stage_id: str, stage_type: str) -> Dict[str, Any]:
    payload = fact.to_dict()
    payload["stage_id"] = stage_id
    payload["stage_type"] = stage_type
    return payload


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _source_path_hint(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        if mapping.get(key):
            return str(mapping[key])
    return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _round(value: float) -> float:
    return round(float(value), 6)
