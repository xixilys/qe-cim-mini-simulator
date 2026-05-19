#!/usr/bin/env python3
"""Run a QE h_psi boundary snapshot through the GenericAccel/SystemC sidecar path.

This is a foundation/evidence-progress runner.  It packages a real QE
``h_psi`` boundary snapshot into a Generic SystemC request, runs the local
``generic_sim`` backend, and writes the standard accelerated-numeric artifact
shape.  The produced kernel/provenance artifacts deliberately state
``boundary_norm_probe_only`` and ``full_h_psi_recomputed=false`` so downstream
anti-downgrade gates keep the row blocked for trusted QE correctness until a
future runtime recomputes the full kernel.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_accelerated_evidence import build_evidence_from_files  # noqa: E402
from dse_v2.reference_workloads.qe_hpsi_sidecar import (  # noqa: E402
    build_hpsi_component_closure_report,
    build_hpsi_component_target_arrays,
    build_hpsi_boundary_probe_request,
    build_sidecar_kernel_evidence,
    build_sidecar_offload_provenance,
    build_sidecar_result,
    compute_hpsi_kinetic_component,
    compute_hpsi_vloc_delta_component,
    compute_hpsi_vnl_delta_component,
    compute_hpsi_stage_decomposition,
    load_hpsi_boundary_arrays,
    load_hpsi_boundary_snapshot,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_repo_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else REPO_ROOT / path


def _default_simulator() -> Path:
    return REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim"


def _run_generic_sim(simulator: Path, request_path: Path, result_path: Path, timeout: int) -> Dict[str, Any]:
    if not simulator.exists():
        return {
            "returncode": 127,
            "stdout": "",
            "stderr": f"generic_sim not found: {simulator}",
            "result": None,
            "blockers": [f"generic_sim_missing:{simulator}"],
        }
    completed = subprocess.run(
        [str(simulator), "--request", str(request_path), "--result", str(result_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = _load_json(result_path) if result_path.exists() else None
    blockers = [] if completed.returncode == 0 and isinstance(result, dict) and result.get("status") == "passed" else [
        f"generic_sim_returncode:{completed.returncode}",
    ]
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "result": result,
        "blockers": blockers,
    }


def _has_full_hpsi_component_model(evidence: Dict[str, Any]) -> bool:
    kernel_rows = evidence.get("kernel_evidence", [])
    if not isinstance(kernel_rows, list):
        return False
    return any(
        isinstance(row, dict)
        and row.get("kernel_id") == "h_psi"
        and row.get("kernel_scope") == "full_h_psi"
        and row.get("full_kernel_recomputed") is True
        and row.get("boundary_norm_probe_only") is not True
        and row.get("source") == "python_qe_hpsi_component_model"
        for row in kernel_rows
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--workload-case-id", required=True)
    parser.add_argument("--snapshot", type=Path, required=True, help="QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON artifact")
    parser.add_argument(
        "--boundary-arrays",
        type=Path,
        default=None,
        help="Optional QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON artifact for partial kinetic-component computation.",
    )
    parser.add_argument("--baseline-comparison", type=Path, required=True)
    parser.add_argument(
        "--accelerated-stdout",
        type=Path,
        required=True,
        help="QE stdout from the instrumented/offload replay. Used only for SCF physical delta extraction.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--simulator", type=Path, default=_default_simulator())
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--source-kind", default="gem5_generic_accel_qe_extension")
    parser.add_argument("--fail-on-trusted", action="store_true", help="Fail if this probe is accidentally trusted.")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = _resolve_repo_path(args.out_dir) or args.out_dir
    snapshot_path = _resolve_repo_path(args.snapshot) or args.snapshot
    boundary_arrays_path = _resolve_repo_path(args.boundary_arrays)
    baseline_path = _resolve_repo_path(args.baseline_comparison) or args.baseline_comparison
    accelerated_stdout_path = _resolve_repo_path(args.accelerated_stdout) or args.accelerated_stdout
    simulator = _resolve_repo_path(args.simulator) or args.simulator

    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = load_hpsi_boundary_snapshot(snapshot_path)
    request = build_hpsi_boundary_probe_request(
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        snapshot=snapshot,
    )
    request_path = out_dir / "simulation_request.json"
    generic_sim_result_path = out_dir / "generic_sim_result.json"
    sidecar_result_path = out_dir / "hpsi_sidecar_result.json"
    kinetic_component_result_path = out_dir / "hpsi_kinetic_component_result.json"
    vloc_component_result_path = out_dir / "hpsi_vloc_component_result.json"
    vnl_component_result_path = out_dir / "hpsi_vnl_component_result.json"
    stage_decomposition_path = out_dir / "hpsi_stage_decomposition.json"
    component_closure_report_path = out_dir / "hpsi_component_closure_report.json"
    component_target_arrays_path = out_dir / "hpsi_component_target_arrays.json"
    kernel_evidence_path = out_dir / "kernel_evidence.json"
    provenance_path = out_dir / "offload_provenance.json"
    evidence_path = out_dir / "qe_accelerated_numeric_evidence.json"
    index_path = out_dir / "hpsi_sidecar_bridge_index.json"

    _write_json(request_path, request)
    sim_run = _run_generic_sim(simulator, request_path, generic_sim_result_path, args.timeout)
    sim_result = sim_run["result"] if isinstance(sim_run.get("result"), dict) else {}
    sidecar_result = build_sidecar_result(
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        snapshot=snapshot,
        simulator_result=sim_result,
        simulator_result_path=generic_sim_result_path,
        request_path=request_path,
    )
    if sim_run.get("blockers"):
        sidecar_result["status"] = "blocked"
        sidecar_result["blockers"] = sim_run["blockers"]
    kinetic_component_result = None
    vloc_component_result = None
    vnl_component_result = None
    stage_decomposition = None
    component_closure_report = None
    component_target_arrays = None
    if boundary_arrays_path is not None:
        arrays = load_hpsi_boundary_arrays(boundary_arrays_path)
        kinetic_component_result = compute_hpsi_kinetic_component(arrays)
        vloc_component_result = compute_hpsi_vloc_delta_component(arrays)
        vnl_component_result = compute_hpsi_vnl_delta_component(arrays)
        stage_decomposition = compute_hpsi_stage_decomposition(arrays)
        component_target_arrays = build_hpsi_component_target_arrays(arrays)
        component_closure_report = build_hpsi_component_closure_report(
            kinetic_component_result=kinetic_component_result,
            stage_decomposition=stage_decomposition,
            vloc_component_result=vloc_component_result,
            vnl_component_result=vnl_component_result,
        )
        sidecar_result["artifacts"]["kernel_boundary_arrays_json"] = str(boundary_arrays_path)
        sidecar_result["artifacts"]["hpsi_kinetic_component_result_json"] = str(kinetic_component_result_path)
        sidecar_result["artifacts"]["hpsi_vloc_component_result_json"] = str(vloc_component_result_path)
        sidecar_result["artifacts"]["hpsi_vnl_component_result_json"] = str(vnl_component_result_path)
        sidecar_result["artifacts"]["hpsi_stage_decomposition_json"] = str(stage_decomposition_path)
        sidecar_result["artifacts"]["hpsi_component_closure_report_json"] = str(component_closure_report_path)
        sidecar_result["artifacts"]["hpsi_component_target_arrays_json"] = str(component_target_arrays_path)
        sidecar_result["kinetic_component_status"] = kinetic_component_result.get("status")
        sidecar_result["vloc_component_status"] = vloc_component_result.get("status")
        sidecar_result["vnl_component_status"] = vnl_component_result.get("status")
        sidecar_result["stage_decomposition_status"] = stage_decomposition.get("status")
        sidecar_result["component_target_arrays_status"] = component_target_arrays.get("status")
        sidecar_result["component_closure_status"] = component_closure_report.get("status")
        _write_json(kinetic_component_result_path, kinetic_component_result)
        _write_json(vloc_component_result_path, vloc_component_result)
        _write_json(vnl_component_result_path, vnl_component_result)
        _write_json(stage_decomposition_path, stage_decomposition)
        _write_json(component_target_arrays_path, component_target_arrays)
        _write_json(component_closure_report_path, component_closure_report)
    _write_json(sidecar_result_path, sidecar_result)
    _write_json(
        kernel_evidence_path,
        build_sidecar_kernel_evidence(
            sidecar_result,
            kinetic_component_result,
            stage_decomposition,
            vloc_component_result,
            vnl_component_result,
        ),
    )
    _write_json(
        provenance_path,
        build_sidecar_offload_provenance(
            sidecar_result=sidecar_result,
            producer="dse_v2/scripts/dse/run_qe_hpsi_sidecar_bridge.py",
            density_residual=0.0,
        ),
    )

    try:
        evidence = build_evidence_from_files(
            candidate_id=args.candidate_id,
            workload_case_id=args.workload_case_id,
            baseline_comparison_path=baseline_path,
            accelerated_stdout_path=accelerated_stdout_path,
            source_kind=args.source_kind,
            kernel_evidence_path=kernel_evidence_path,
            offload_provenance_path=provenance_path,
        )
    except Exception as exc:
        evidence = {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "candidate_id": args.candidate_id,
            "workload_case_id": args.workload_case_id,
            "source_kind": args.source_kind,
            "accelerated_output_status": "blocked",
            "trusted_accelerated_numeric_source": False,
            "blockers": [f"hpsi_sidecar_evidence_build_exception:{exc}"],
            "claim_boundary": "Sidecar bridge evidence build failed; no trusted correctness claim is made.",
        }
    evidence.setdefault("accelerated_reference", {})
    if isinstance(evidence["accelerated_reference"], dict):
        evidence["accelerated_reference"].update(
            {
                "kernel_boundary_snapshot_json": str(snapshot_path),
                "kernel_boundary_arrays_json": str(boundary_arrays_path) if boundary_arrays_path is not None else None,
                "hpsi_sidecar_result_json": str(sidecar_result_path),
                "hpsi_kinetic_component_result_json": str(kinetic_component_result_path)
                if kinetic_component_result is not None
                else None,
                "hpsi_vloc_component_result_json": str(vloc_component_result_path)
                if vloc_component_result is not None
                else None,
                "hpsi_vnl_component_result_json": str(vnl_component_result_path)
                if vnl_component_result is not None
                else None,
                "hpsi_stage_decomposition_json": str(stage_decomposition_path)
                if stage_decomposition is not None
                else None,
                "hpsi_component_closure_report_json": str(component_closure_report_path)
                if component_closure_report is not None
                else None,
                "hpsi_component_target_arrays_json": str(component_target_arrays_path)
                if component_target_arrays is not None
                else None,
                "generic_sim_request_json": str(request_path),
                "generic_sim_result_json": str(generic_sim_result_path),
            }
        )
    evidence["hpsi_sidecar_result"] = sidecar_result
    evidence["trusted_accelerated_numeric_source"] = False
    evidence["accelerated_output_status"] = "blocked"
    full_component_model = _has_full_hpsi_component_model(evidence)
    bridge_blocker = (
        "hpsi_component_model_not_l4_offload_provenance"
        if full_component_model
        else "hpsi_sidecar_boundary_probe_not_full_kernel_recompute"
    )
    evidence["blockers"] = sorted(
        dict.fromkeys(
            [
                *[str(item) for item in evidence.get("blockers", []) or []],
                bridge_blocker,
            ]
        )
    )
    evidence["hpsi_component_model_full_hpsi_recomputed"] = full_component_model
    _write_json(evidence_path, evidence)

    index = {
        "schema_version": "dse.qe_hpsi_sidecar_bridge_index.v1",
        "candidate_id": args.candidate_id,
        "workload_case_id": args.workload_case_id,
        "status": (
            "passed_component_model_blocked_for_l4_provenance"
            if sidecar_result.get("status") == "passed" and full_component_model
            else (
                "passed_foundation_blocked_for_trusted_correctness"
                if sidecar_result.get("status") == "passed"
                else "blocked"
            )
        ),
        "trusted_accelerated_numeric_source": evidence.get("trusted_accelerated_numeric_source"),
        "hpsi_component_model_full_hpsi_recomputed": full_component_model,
        "blockers": evidence.get("blockers", []),
        "artifacts": {
            "snapshot": str(snapshot_path),
            "boundary_arrays": str(boundary_arrays_path) if boundary_arrays_path is not None else None,
            "baseline_comparison": str(baseline_path),
            "accelerated_stdout": str(accelerated_stdout_path),
            "simulation_request": str(request_path),
            "generic_sim_result": str(generic_sim_result_path),
            "hpsi_sidecar_result": str(sidecar_result_path),
            "hpsi_kinetic_component_result": str(kinetic_component_result_path)
            if kinetic_component_result is not None
            else None,
            "hpsi_vloc_component_result": str(vloc_component_result_path)
            if vloc_component_result is not None
            else None,
            "hpsi_vnl_component_result": str(vnl_component_result_path)
            if vnl_component_result is not None
            else None,
            "hpsi_stage_decomposition": str(stage_decomposition_path) if stage_decomposition is not None else None,
            "hpsi_component_closure_report": str(component_closure_report_path)
            if component_closure_report is not None
            else None,
            "hpsi_component_target_arrays": str(component_target_arrays_path)
            if component_target_arrays is not None
            else None,
            "kernel_evidence": str(kernel_evidence_path),
            "offload_provenance": str(provenance_path),
            "qe_accelerated_numeric_evidence": str(evidence_path),
        },
        "claim_boundary": (
            "Component-model progress only: the sidecar may recompute full h_psi numerically from captured QE arrays, "
            "but the row remains blocked until L4/offload provenance proves the accelerated path, not Python sidecar "
            "or host instrumentation, performed the full h_psi recompute."
            if full_component_model
            else (
                "Foundation progress only: a real Generic SystemC sidecar consumed a QE h_psi boundary snapshot. "
                "The row remains blocked because full QE h_psi recomputation has not been implemented."
            )
        ),
    }
    _write_json(index_path, index)
    print(json.dumps(index, indent=2, sort_keys=True))
    if args.fail_on_trusted and evidence.get("trusted_accelerated_numeric_source") is True:
        return 3
    return 0 if sidecar_result.get("status") == "passed" else 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
