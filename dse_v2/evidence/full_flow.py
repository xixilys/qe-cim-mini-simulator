#!/usr/bin/env python3
"""Evidence contract implementation for full-flow QE SCF shell pilots."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from dse_v2.core.ir.compute_graph import ComputeGraph, DataEdge
from dse_v2.dse.orchestrator import DesignPoint

REQUIRED_QE_SCF_PHASES = [
    "h_psi",
    "s_psi",
    "build_H_sub",
    "build_S_sub",
    "diagonalize",
    "subspace_rotation",
    "refresh",
    "residual",
    "rho_out",
    "mix_rho",
    "veff",
]

REQUIRED_EVIDENCE_FILES = [
    "manifest.json",
    "artifact_manifest.json",
    "verdict.json",
    "design_point.json",
    "architecture.json",
    "mapping.json",
    "workload_graph.json",
    "simulation_request.json",
    "simulation_result.json",
    "phase_breakdown.csv",
    "resource_summary.csv",
    "data_movement_summary.csv",
    "systemc_stdout.log",
    "systemc_stderr.log",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _event_map(sim_result: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    events = sim_result.get("events", []) if sim_result else []
    return {str(event.get("node_id")): event for event in events if event.get("node_id")}


def _device_clock_map(sim_request: Mapping[str, Any]) -> Dict[str, float]:
    architecture = sim_request.get("architecture", {}) if sim_request else {}
    host = architecture.get("host", {})
    clocks = {"host": float(host.get("clock_mhz", 3000.0) or 3000.0)}
    for accel in architecture.get("accelerators", []) or []:
        accel_id = accel.get("accel_id")
        if accel_id:
            clocks[str(accel_id)] = float(accel.get("clock_mhz", 250.0) or 250.0)
    return clocks


def build_phase_results(
    sim_result: Mapping[str, Any],
    sim_request: Mapping[str, Any],
    required_phases: Iterable[str] = REQUIRED_QE_SCF_PHASES,
) -> Dict[str, Dict[str, Any]]:
    events = _event_map(sim_result)
    clocks = _device_clock_map(sim_request)
    phases: Dict[str, Dict[str, Any]] = {}
    for phase in required_phases:
        event = events.get(phase)
        if not event:
            phases[phase] = {
                "status": "unavailable",
                "unavailable_reason": "no timing event emitted by simulator for required QE SCF phase",
            }
            continue
        start_ns = float(event.get("start_ns", 0.0) or 0.0)
        end_ns = float(event.get("end_ns", 0.0) or 0.0)
        latency_ns = max(0.0, end_ns - start_ns)
        device = str(event.get("device", "unknown"))
        clock_mhz = clocks.get(device)
        phases[phase] = {
            "status": "available",
            "node_id": phase,
            "op_type": event.get("op_type", "unknown"),
            "device": device,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "latency_ns": latency_ns,
            "latency_ms": latency_ns / 1e6,
            "cycles_estimate": latency_ns * clock_mhz / 1000.0 if clock_mhz else None,
            "clock_mhz": clock_mhz,
        }
    return phases


def _write_phase_breakdown(path: Path, phase_results: Mapping[str, Mapping[str, Any]]) -> None:
    fields = [
        "phase",
        "node_id",
        "op_type",
        "device",
        "start_ns",
        "end_ns",
        "latency_ns",
        "latency_ms",
        "cycles_estimate",
        "clock_mhz",
        "status",
        "unavailable_reason",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for phase, data in phase_results.items():
            row = {field: data.get(field, "") for field in fields}
            row["phase"] = phase
            writer.writerow(row)


def _write_resource_summary(
    path: Path,
    sim_result: Mapping[str, Any],
) -> None:
    events = sim_result.get("events", []) if sim_result else []
    event_compute_ms: Dict[str, float] = {}
    for event in events:
        device = str(event.get("device", "unknown"))
        latency_ms = max(0.0, float(event.get("end_ns", 0.0) or 0.0) - float(event.get("start_ns", 0.0) or 0.0)) / 1e6
        event_compute_ms[device] = event_compute_ms.get(device, 0.0) + latency_ms
    utilization = sim_result.get("resource_utilization", {}) if sim_result else {}
    devices = sorted(set(event_compute_ms) | set(utilization))
    fields = ["device", "compute_percent", "memory_percent", "bandwidth_percent", "event_compute_time_ms"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for device in devices:
            util = utilization.get(device, {}) or {}
            writer.writerow({
                "device": device,
                "compute_percent": util.get("compute_percent", ""),
                "memory_percent": util.get("memory_percent", ""),
                "bandwidth_percent": util.get("bandwidth_percent", ""),
                "event_compute_time_ms": event_compute_ms.get(device, 0.0),
            })


def _edge_size(edge: DataEdge) -> Tuple[int, float]:
    if edge.tensor_spec is None:
        return 0, 0.0
    size_bytes = edge.tensor_spec.size_bytes()
    return size_bytes, size_bytes / (1024.0 * 1024.0)


def _write_data_movement_summary(
    path: Path,
    graph: ComputeGraph,
    mapping: Mapping[str, str],
) -> None:
    fields = [
        "edge_id",
        "source",
        "target",
        "tensor_name",
        "source_device",
        "target_device",
        "size_bytes",
        "size_mb",
        "cross_device",
        "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, edge in enumerate(graph.edges):
            source_device = mapping.get(edge.source_node, "host")
            target_device = mapping.get(edge.target_node, "host")
            size_bytes, size_mb = _edge_size(edge)
            cross = source_device != target_device
            writer.writerow({
                "edge_id": f"edge_{idx}",
                "source": edge.source_node,
                "target": edge.target_node,
                "tensor_name": edge.tensor_name,
                "source_device": source_device,
                "target_device": target_device,
                "size_bytes": size_bytes,
                "size_mb": f"{size_mb:.9f}",
                "cross_device": str(cross).lower(),
                "status": "cross_device_transfer" if cross else "same_device",
            })


def claim_can_be_trusted(claim: Mapping[str, Any], verdict: Optional[Mapping[str, Any]] = None) -> bool:
    """Return whether a final report claim is allowed in trusted ranking.

    L1/L2 analytical/TLM or predicted-only claims are never trusted final-ranking
    evidence. A claim needs SystemC/gem5+SystemC backing and at least one evidence id.
    """
    if claim.get("predicted_only"):
        return False
    fidelity = str(claim.get("fidelity", claim.get("source_fidelity", ""))).lower()
    if fidelity in {"l1", "l2", "analytical", "tlm", "surrogate", "predicted"}:
        return False
    backend = str(claim.get("backend", claim.get("source_backend", ""))).lower()
    if backend not in {"systemc", "gem5_systemc"}:
        return False
    if not claim.get("evidence_ids"):
        return False
    if verdict is not None and not verdict.get("trusted_for_final_ranking", False):
        return False
    return True


def _artifact_entries(run_dir: Path, required_files: Iterable[str]) -> List[Dict[str, Any]]:
    entries = []
    for rel in sorted(set(required_files)):
        path = run_dir / rel
        entry: Dict[str, Any] = {
            "path": rel,
            "required": rel in REQUIRED_EVIDENCE_FILES,
            "exists": path.exists(),
        }
        if path.exists() and path.is_file():
            entry.update({
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
        else:
            entry["unavailable_reason"] = "not generated for this backend/run"
        entries.append(entry)
    return entries


def write_full_flow_evidence(
    *,
    run_dir: Path,
    backend: str,
    evidence_mode: str,
    design_point: DesignPoint,
    compute_graph: ComputeGraph,
    simulation_request: Mapping[str, Any],
    simulation_result: Optional[Mapping[str, Any]],
    simulator_cmd: List[str],
    simulator_returncode: int,
    systemc_stdout: str,
    systemc_stderr: str,
    cli_command: List[str],
    gem5_attempted: bool = False,
    gem5_log: Optional[str] = None,
) -> Dict[str, Any]:
    """Write all required evidence artifacts for a full QE SCF shell pilot."""
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_result = dict(simulation_result or {})
    phase_results = build_phase_results(raw_result, simulation_request)
    missing_phases = [p for p, r in phase_results.items() if r.get("status") != "available"]
    simulation_passed = simulator_returncode == 0 and raw_result.get("status") == "passed"
    trusted_systemc = backend == "systemc" and simulation_passed and not missing_phases
    trusted_gem5_systemc = backend == "gem5_systemc" and simulation_passed and not missing_phases and gem5_attempted
    trusted_for_final = trusted_systemc or trusted_gem5_systemc
    run_id = str(simulation_request.get("run_id", design_point.design_point_id))

    design_point_payload = design_point.to_dict()
    architecture_payload = {
        "architecture_id": design_point.system_architecture.system_id,
        "architecture_family": "generic_heterogeneous_pilot",
        "architecture_scope": "broad host plus heterogeneous accelerator timing-level pilot; not hardcoded to any single cluster template",
        "status": "prototype",
        "trusted_final_eligible": trusted_for_final,
        "system_architecture": design_point.system_architecture.to_dict(),
    }
    mapping_payload = {
        "mapping_id": f"{run_id}_mapping",
        "mapping_policy": "domain_seeded_full_qe_scf_shell_timing_mapping",
        "placements": design_point.task_mapping,
        "search_status": "seeded_candidate_for_p0_p1_vertical_slice",
        "trusted_final_eligible": trusted_for_final,
        "notes": [
            "Mapping is a reproducible seeded candidate for the P0/P1 vertical slice.",
            "Mapping search and architecture catalog expansion are reserved for later goals.",
        ],
    }
    workload_payload = compute_graph.to_dict()

    public_result = dict(raw_result)
    public_result.update({
        "backend": backend,
        "timing_level": True,
        "trusted_timing_source": "SystemC/generic timing backend" if backend == "systemc" else "gem5+SystemC",
        "required_qe_scf_phases": REQUIRED_QE_SCF_PHASES,
        "phase_results": phase_results,
        "missing_required_phases": missing_phases,
        "simulator_returncode": simulator_returncode,
        "unavailable_metrics": [] if not missing_phases else [
            {"metric": "phase_timing", "phases": missing_phases, "reason": "simulator did not emit events"}
        ],
    })

    gem5_blockers = []
    if backend != "gem5_systemc" or not gem5_attempted:
        gem5_blockers = [
            {
                "id": "gem5_descriptor_ingestion",
                "status": "blocked",
                "detail": "No verified full QE SCF shell descriptor ingestion path from gem5 software/driver to SystemC backend in this run.",
            },
            {
                "id": "gem5_completion_result_writeback",
                "status": "blocked",
                "detail": "No verified completion/result writeback path visible to gem5 software side for this full-flow workload.",
            },
            {
                "id": "gem5_systemc_binding",
                "status": "blocked",
                "detail": "Standalone SystemC timing-level backend executed; gem5+SystemC L4 binding remains prototype/blocked for final L4 claims.",
            },
        ]

    evidence_gaps = []
    if missing_phases:
        evidence_gaps.append(f"Missing required phase timing events: {', '.join(missing_phases)}")
    if gem5_blockers:
        evidence_gaps.append("gem5+SystemC descriptor/completion path is blocked for this run; no L4 completion claim is made.")

    verdict = {
        "schema_version": "dse.verdict.v1",
        "run_id": run_id,
        "backend": backend,
        "evidence_mode": evidence_mode,
        "trusted_for_final_ranking": trusted_for_final,
        "trusted_paths": [backend] if trusted_for_final else [],
        "simulation_passed": simulation_passed,
        "phase_coverage_passed": not missing_phases,
        "binding_status": {
            "standalone_systemc_full_qe_scf_shell": "implemented" if trusted_systemc else "blocked",
            "gem5_systemc_full_qe_scf_shell": "implemented" if trusted_gem5_systemc else "blocked",
            "gem5_generic_accel_mmio_stub": "prototype",
            "l1_l2_predicted_final_ranking": "unsupported",
        },
        "status_boundary": {
            "full_qe_scf_shell_workload_adapter": "implemented",
            "timing_level_phase_execution": "implemented" if simulation_passed else "blocked",
            "fixed_timing_smoke_done_evidence": "unsupported",
            "predicted_only_done_evidence": "unsupported",
            "architecture_catalog_full_expansion": "planned",
            "mapping_search_optimizer": "planned",
        },
        "required_qe_scf_phases": REQUIRED_QE_SCF_PHASES,
        "missing_required_phases": missing_phases,
        "evidence_gaps": evidence_gaps,
        "gem5_systemc_blockers": gem5_blockers,
        "claim_gating": {
            "best_architecture": "not_claimed_by_single_pilot; requires trusted multi-candidate SystemC/gem5+SystemC evidence",
            "mapping_comparison": "not_claimed_by_single_pilot; requires comparable trusted runs",
            "bottleneck": "allowed_only_if_phase_breakdown_csv_and_simulation_result_phase_results_are_cited",
            "feasibility": "allowed_for_this_design_only_if_verdict_and_simulation_result_are_cited",
            "pareto_frontier": "not_claimed_by_single_pilot",
            "debug_replay": "allowed_if_manifest_and_artifact_manifest_are_cited",
        },
        "forbidden_claims": [
            "L4 gem5+SystemC complete" if gem5_blockers else "predicted-only final ranking",
            "L1/L2 analytical/TLM winner as final trusted result",
            "toy smoke/fixed-timing diagnostic as Done evidence",
            "numerical QE correctness beyond this timing-level shell model",
        ],
    }

    _write_json(run_dir / "design_point.json", design_point_payload)
    _write_json(run_dir / "architecture.json", architecture_payload)
    _write_json(run_dir / "mapping.json", mapping_payload)
    _write_json(run_dir / "workload_graph.json", workload_payload)
    _write_json(run_dir / "simulation_request.json", simulation_request)
    _write_json(run_dir / "simulation_result.json", public_result)
    _write_json(run_dir / "simulation_result.raw.json", raw_result)
    _write_text(run_dir / "systemc_stdout.log", systemc_stdout)
    _write_text(run_dir / "systemc_stderr.log", systemc_stderr)
    _write_phase_breakdown(run_dir / "phase_breakdown.csv", phase_results)
    _write_resource_summary(run_dir / "resource_summary.csv", raw_result)
    _write_data_movement_summary(run_dir / "data_movement_summary.csv", compute_graph, design_point.task_mapping)
    _write_json(run_dir / "gem5_systemc_blockers.json", {"blockers": gem5_blockers})
    if gem5_log is not None:
        _write_text(run_dir / "gem5.log", gem5_log)
    _write_json(run_dir / "verdict.json", verdict)

    manifest = {
        "schema_version": "dse.manifest.v1",
        "run_id": run_id,
        "created_at": _now_iso(),
        "workload": "qe_scf_shell",
        "backend": backend,
        "evidence_mode": evidence_mode,
        "cwd": os.getcwd(),
        "cli_command": cli_command,
        "simulator_command": simulator_cmd,
        "replay_metadata": {
            "python_replay_command": cli_command,
            "simulator_replay_command": simulator_cmd,
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
        },
        "trusted_for_final_ranking": trusted_for_final,
        "required_evidence_files": REQUIRED_EVIDENCE_FILES,
        "optional_evidence_files": ["simulation_result.raw.json", "gem5_systemc_blockers.json", "gem5.log"],
    }
    _write_json(run_dir / "manifest.json", manifest)

    artifact_paths = list(REQUIRED_EVIDENCE_FILES) + ["simulation_result.raw.json", "gem5_systemc_blockers.json"]
    if gem5_log is not None:
        artifact_paths.append("gem5.log")
    artifact_entries = _artifact_entries(run_dir, artifact_paths)
    for entry in artifact_entries:
        if entry["path"] == "artifact_manifest.json":
            entry["exists"] = True
            entry.pop("unavailable_reason", None)
            entry["self_referential_manifest"] = True
            entry["hash_unavailable_reason"] = "artifact_manifest.json is generated from this artifact listing"
    artifact_manifest = {
        "schema_version": "dse.artifact_manifest.v1",
        "run_id": run_id,
        "generated_at": _now_iso(),
        "artifacts": artifact_entries,
    }
    _write_json(run_dir / "artifact_manifest.json", artifact_manifest)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "trusted_for_final_ranking": trusted_for_final,
        "missing_required_phases": missing_phases,
        "verdict": verdict,
    }
