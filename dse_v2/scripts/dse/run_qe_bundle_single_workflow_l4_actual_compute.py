#!/usr/bin/env python3
"""Attempt a non-smoke single-QE-workflow multi-callsite bundle run.

This runner is intentionally conservative.  It runs one pure QE baseline, one
trace pass, and one patched QE workflow with per-kernel bundle runtime slots.
It may prove that multiple supported callsites consumed accelerated replacement
outputs in the same QE process, but it only allows bundle-level ``valuable_l4``
when the run covers the whole selected bundle, passes correctness, and has a
positive speed signal.  Partial supported-kernel probes remain progress
evidence, not bundle value.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    build_offload_value_l4_evidence_matrix,
    build_offload_value_report,
    build_bundle_single_workflow_l4_evidence_report,
    classify_l4_offload_value,
)
from dse_v2.reference_workloads.qe_mainflow import (  # noqa: E402
    default_qe_mainflow_workload_suite,
)
from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import (  # noqa: E402
    _default_qe_bin_dir,
    _default_qe_pseudo_dir,
    _gem5_preflight,
    _parse_qe_stdout,
    _run_qe_baseline,
)
from dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke import (  # noqa: E402
    DEFAULT_MAX_BATCHED_BRIDGE_TRACE_COUNT,
    NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_WORKLOAD_VARIANT_ID,
    _apply_workload_variant_binding,
    _build_transport_request,
    _gem5_command,
    _gem5_marker_summary,
    _install_bundle_runtime_env,
    _load_optional_json,
    _materialize_bridge_runtime_workspace,
    _physical_correctness,
    _prepare_bridge_runtime_workspace,
    _runtime_bridge_replacement_summary,
    _run_trace_probe,
    _select_correctness_metrics,
    _step_matches_opportunity_stage,
    _trace_contains_kernel,
    _trace_observed_kernel_count,
    _write_bridge_command_script,
)

SUPPORTED_ACTUAL_COMPUTE_KERNELS = ("fft", "subspace_rotation")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_path_component(value: Any) -> str:
    return "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
        for ch in str(value)
    ).strip("_") or "target"


def _bundle_by_id(bundle_space: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("bundle_id")): dict(row)
        for row in bundle_space.get("bundles", []) or []
        if isinstance(row, Mapping) and row.get("bundle_id")
    }


def _opportunity_by_id(opportunity_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("opportunity_id")): dict(row)
        for row in opportunity_manifest.get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }


def _case_index() -> dict[str, Mapping[str, Any]]:
    suite = default_qe_mainflow_workload_suite(status="frozen", include_relax=True)
    return {
        str(case.get("case_id")): case
        for case in suite.get("cases", []) or []
        if isinstance(case, Mapping) and case.get("case_id")
    }


def _read_int_file(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _copytree_or_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _select_bundle_targets(
    *,
    bundle: Mapping[str, Any],
    opportunities: Mapping[str, Mapping[str, Any]],
    target_kernels: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    wanted = {str(kernel) for kernel in target_kernels if str(kernel)}
    blockers: list[str] = []
    targets: list[dict[str, Any]] = []
    for opportunity_id in bundle.get("opportunity_ids", []) or []:
        opportunity = opportunities.get(str(opportunity_id))
        if not isinstance(opportunity, Mapping):
            blockers.append(f"bundle_unknown_opportunity_id:{opportunity_id}")
            continue
        kernel = str(opportunity.get("kernel") or "")
        if kernel in wanted:
            targets.append(dict(opportunity))
    missing_kernels = sorted(wanted - {str(row.get("kernel")) for row in targets})
    blockers.extend(f"target_kernel_not_in_bundle:{kernel}" for kernel in missing_kernels)
    return targets, blockers


def _make_target_runtime(
    *,
    out_dir: Path,
    opportunity: Mapping[str, Any],
    trace_evidence: Mapping[str, Any],
    gem5_binary: Path,
    gem5_config: Path,
    gem5_driver: Path,
    simulator: Path,
    max_ticks: int,
    max_batched_trace_count: int,
    max_driver_repeat_per_kernel: int,
    prelaunch_kernels: set[str],
) -> tuple[dict[str, Any], list[str]]:
    kernel = str(opportunity.get("kernel") or "")
    artifact_target_dir = (
        out_dir / "bundle_runtime_slots" / _safe_path_component(kernel)
    ).absolute()
    target_dir, runtime_workspace = _prepare_bridge_runtime_workspace(
        artifact_target_dir
    )
    target_dir = target_dir.absolute()
    blockers: list[str] = []
    selected_trace_count = max(1, _trace_observed_kernel_count(trace_evidence, kernel))
    if selected_trace_count > max_batched_trace_count > 0 and kernel != "subspace_rotation":
        blockers.append(
            f"batched_bridge_trace_count_exceeds_limit:{kernel}:"
            f"{selected_trace_count}>{max_batched_trace_count}"
        )
    driver_repeat = 1 if kernel == "subspace_rotation" else selected_trace_count
    if kernel != "subspace_rotation" and max_driver_repeat_per_kernel > 0:
        driver_repeat = max(1, min(driver_repeat, max_driver_repeat_per_kernel))
    request_path = _build_transport_request(
        out_dir=target_dir,
        trace_evidence=trace_evidence,
        opportunity=opportunity,
    )
    m5out = target_dir / "m5out"
    gem5_stdout = target_dir / "gem5_bridge_stdout.txt"
    gem5_stderr = target_dir / "gem5_bridge_stderr.txt"
    returncode_path = target_dir / "gem5_bridge_returncode.txt"
    invocation_count_path = target_dir / "gem5_bridge_invocation_count.txt"
    gem5_launch_count_path = target_dir / "gem5_bridge_launch_count.txt"
    runtime_kernel_evidence_path = target_dir / "runtime_kernel_evidence.json"
    runtime_offload_provenance_path = target_dir / "runtime_offload_provenance.json"
    accelerated_output_json_path = target_dir / "accelerated_output.json"
    accelerated_input_json_path = target_dir / "accelerated_input.json"
    accelerated_input_data_path = target_dir / "accelerated_input_values.dat"
    accelerated_output_data_path = target_dir / "accelerated_output_values.dat"
    prelaunch_bridge = kernel in prelaunch_kernels
    command = _gem5_command(
        gem5_binary=gem5_binary,
        m5out=m5out,
        gem5_config=gem5_config,
        gem5_driver=gem5_driver,
        request_path=request_path.resolve(),
        simulator=simulator,
        max_ticks=max_ticks,
        driver_repeat=driver_repeat,
    )
    bridge_script = _write_bridge_command_script(
        bridge_dir=target_dir,
        command=command,
        stdout_path=gem5_stdout,
        stderr_path=gem5_stderr,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output_json_path,
        target_kernel=kernel,
        request_path=request_path,
        accelerated_input_json_path=accelerated_input_json_path,
        accelerated_input_data_path=accelerated_input_data_path,
        accelerated_output_data_path=accelerated_output_data_path,
        batch_size=driver_repeat,
        reuse_prelaunched_result=prelaunch_bridge,
    )
    return (
        {
            "opportunity": dict(opportunity),
            "kernel": kernel,
            "target_dir": target_dir,
            "runtime_bridge_workspace": dict(runtime_workspace)
            if runtime_workspace is not None
            else {
                "schema_version": "dse.qe_l4_bridge_runtime_workspace.v1",
                "artifact_bridge_dir": str(artifact_target_dir),
                "runtime_storage_policy": "artifact_directory",
                "post_timing_materialized": False,
                "blockers": [],
            },
            "bridge_script": bridge_script,
            "gem5_command": command,
            "request_path": request_path,
            "m5out": m5out,
            "gem5_stdout": gem5_stdout,
            "gem5_stderr": gem5_stderr,
            "returncode_path": returncode_path,
            "invocation_count_path": invocation_count_path,
            "gem5_launch_count_path": gem5_launch_count_path,
            "runtime_kernel_evidence_path": runtime_kernel_evidence_path,
            "runtime_offload_provenance_path": runtime_offload_provenance_path,
            "accelerated_output_json_path": accelerated_output_json_path,
            "accelerated_input_json_path": accelerated_input_json_path,
            "accelerated_input_data_path": accelerated_input_data_path,
            "accelerated_output_data_path": accelerated_output_data_path,
            "fft_payload_daemon_pid_path": target_dir / "fft_payload_daemon.pid",
            "selected_trace_count": selected_trace_count,
            "expected_driver_iterations": driver_repeat,
            "prelaunch_bridge": prelaunch_bridge,
        },
        blockers,
    )


def _target_result(target: Mapping[str, Any]) -> dict[str, Any]:
    kernel = str(target.get("kernel") or "")
    m5out = Path(target["m5out"])
    gem5_stdout = Path(target["gem5_stdout"])
    returncode_path = Path(target["returncode_path"])
    invocation_count_path = Path(target["invocation_count_path"])
    launch_count_path = Path(target["gem5_launch_count_path"])
    gem5_returncode = _read_int_file(returncode_path)
    marker_summary = _gem5_marker_summary(
        m5out / "gem5.log",
        gem5_stdout,
        expected_driver_iterations=int(target.get("expected_driver_iterations") or 1),
    )
    patched_bridge_like = {
        "gem5_returncode": gem5_returncode,
        "markers": marker_summary.get("markers", {}),
        "driver_status_observed": marker_summary.get("driver_status_observed"),
        "result_prefix_passed": marker_summary.get("result_prefix_passed"),
        "runtime_kernel_evidence": _load_optional_json(
            Path(target["runtime_kernel_evidence_path"])
        ),
        "runtime_offload_provenance": _load_optional_json(
            Path(target["runtime_offload_provenance_path"])
        ),
        "accelerated_output_json": _load_optional_json(
            Path(target["accelerated_output_json_path"])
        ),
    }
    replacement = _runtime_bridge_replacement_summary(patched_bridge_like)
    blockers: list[str] = []
    if gem5_returncode != 0:
        blockers.append(f"gem5_bridge_returncode:{kernel}:{gem5_returncode}")
    for marker, ok in dict(marker_summary.get("markers") or {}).items():
        if not ok:
            blockers.append(f"gem5_marker_missing:{kernel}:{marker}")
    if marker_summary.get("driver_status_observed") is not True:
        blockers.append(f"gem5_driver_status_missing:{kernel}")
    if marker_summary.get("driver_repeat_completed") is not True:
        blockers.append(f"gem5_driver_repeat_incomplete:{kernel}")
    invocation_count = _read_int_file(invocation_count_path)
    driver_iteration_count = marker_summary.get("driver_iteration_count")
    if (
        isinstance(invocation_count, int)
        and isinstance(driver_iteration_count, int)
        and (
            invocation_count - 1
            if target.get("prelaunch_bridge") is True
            else invocation_count
        )
        > driver_iteration_count
    ):
        effective_invocation_count = (
            invocation_count - 1
            if target.get("prelaunch_bridge") is True
            else invocation_count
        )
        blockers.append(
            f"gem5_driver_iterations_less_than_bridge_invocations:"
            f"{kernel}:{driver_iteration_count}<{effective_invocation_count}"
        )
    if marker_summary.get("result_prefix_passed") is not True:
        blockers.append(f"gem5_result_prefix_not_passed:{kernel}")
    blockers.extend(str(item) for item in replacement.get("blockers", []) or [])
    return {
        "kernel": kernel,
        "opportunity_id": dict(target.get("opportunity") or {}).get("opportunity_id"),
        "status": "passed" if not blockers else "blocked",
        "gem5_returncode": gem5_returncode,
        "gem5_bridge_invocation_count": invocation_count,
        "gem5_bridge_launch_count": _read_int_file(launch_count_path),
        "selected_trace_count": target.get("selected_trace_count"),
        "expected_driver_iterations": target.get("expected_driver_iterations"),
        "prelaunch_bridge": target.get("prelaunch_bridge") is True,
        "runtime_bridge_workspace": dict(target.get("runtime_bridge_workspace") or {}),
        "markers": marker_summary.get("markers", {}),
        "driver_status_observed": marker_summary.get("driver_status_observed"),
        "driver_iteration_count": marker_summary.get("driver_iteration_count"),
        "completion_writeback_count": marker_summary.get("completion_writeback_count"),
        "driver_repeat_completed": marker_summary.get("driver_repeat_completed"),
        "result_prefix_passed": marker_summary.get("result_prefix_passed"),
        "bridge_script": str(target["bridge_script"]),
        "runtime_kernel_evidence_path": str(target["runtime_kernel_evidence_path"]),
        "runtime_offload_provenance_path": str(target["runtime_offload_provenance_path"]),
        "accelerated_output_json_path": str(target["accelerated_output_json_path"]),
        "accelerated_output_data_path": str(target["accelerated_output_data_path"]),
        "replacement_summary": replacement,
        "blockers": sorted(dict.fromkeys(blockers)),
    }


def _target_attempt_evidence_row(
    *,
    target_result: Mapping[str, Any],
    target: Mapping[str, Any],
    baseline: Mapping[str, Any],
    trace_evidence: Mapping[str, Any],
    gem5_preflight: Mapping[str, Any],
    correctness: Mapping[str, Any],
    speed_signal: Mapping[str, Any],
    actual_compute_passed: bool,
    bundle_id: str,
    full_bundle_target_coverage: bool,
    out_dir: Path,
) -> dict[str, Any]:
    """Expose a bundle target as a normal L4 attempt row.

    The single-workflow bundle gate decides whether a *bundle* can claim value.
    The ordinary value matrix still needs per-opportunity evidence rows so DSE
    can honestly report that the concrete kernels were attempted under
    non-smoke QE/gem5 actual-compute, even when the bundle remains not valuable
    because the shared speed signal is non-positive.
    """

    opportunity = dict(target.get("opportunity") or {})
    kernel = str(target_result.get("kernel") or opportunity.get("kernel") or "")
    target_passed = target_result.get("status") == "passed"
    replacement = {
        **dict(target_result.get("replacement_summary") or {}),
        "selected_kernel": kernel or None,
        "target_kernel": kernel or None,
        "claim_boundary": (
            "Target row extracted from a single-QE-workflow bundle run; "
            "bundle-level value still requires the separate bundle gate."
        ),
    }
    target_actual_compute_passed = actual_compute_passed and target_passed
    actual_compute_evidence = {
        "status": "passed" if target_actual_compute_passed else "blocked",
        "smoke_only": False,
        "full_qe_run": baseline.get("status") == "passed",
        "non_smoke_actual_compute_run": True,
        "single_qe_workflow_bundle_run": True,
        "single_qe_workflow_covers_full_bundle": full_bundle_target_coverage,
        "bundle_id": bundle_id,
        "qe_consumed_accelerated_outputs": (
            replacement.get("accelerated_results_consumed_by_qe") is True
        ),
        "accelerated_result_materialized_in_qe_memory": (
            replacement.get("accelerated_result_materialized_in_qe_memory")
            is True
        ),
        "qe_software_kernel_execution_skipped": (
            replacement.get("qe_software_kernel_execution_skipped") is True
        ),
        "qe_kernel_work_replaced_on_critical_path": (
            replacement.get("qe_kernel_work_replaced_on_critical_path") is True
        ),
        "accelerated_output_data_path_present": (
            replacement.get("accelerated_output_data_path_present") is True
        ),
        "accelerated_output_data_paths": list(
            replacement.get("accelerated_output_data_paths") or []
        ),
        "software_fallback_on_critical_path": replacement.get(
            "software_fallback_on_critical_path"
        ),
        "runtime_l4_execution_proof_passed": replacement.get(
            "runtime_l4_execution_proof_passed"
        ),
        "target_kernel": kernel or None,
        "selected_kernel": kernel or None,
        "blockers": [] if target_actual_compute_passed else list(target_result.get("blockers") or []),
        "claim_boundary": (
            "Non-smoke full QE actual-compute target evidence emitted from "
            "the bundle runner; speed/value remains gated separately and "
            "partial bundle coverage cannot claim value."
        ),
    }
    l4_passed = target_passed and gem5_preflight.get("can_call_real_adapter") is True
    row = {
        "schema_version": "dse.qe_callgraph_l4_offload_attempt_evidence.v1",
        "opportunity_id": opportunity.get("opportunity_id"),
        "kernel": kernel or opportunity.get("kernel"),
        "stage_type": opportunity.get("stage_type"),
        "callsite_id": opportunity.get("callsite_id"),
        "selected_bundle_id": bundle_id,
        "single_qe_workflow_covers_full_bundle": full_bundle_target_coverage,
        "evidence_kind": "real_qe_l4" if target_actual_compute_passed else "real_qe_l4_attempt",
        "evidence_scope": (
            "full_qe_actual_compute"
            if target_actual_compute_passed
            else "full_qe_actual_compute_blocked"
        ),
        "evidence_mode": "actual_compute",
        "actual_compute_evidence": actual_compute_evidence,
        "attempt_status": "attempted_l4" if l4_passed else "blocked",
        "trace_evidence": dict(trace_evidence),
        "trace_target_observed": True,
        "patched_qe_bundle_target_evidence": dict(target_result),
        "real_l4_provenance": {
            "status": "passed" if l4_passed else "blocked",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed" if l4_passed else "blocked"},
            "request_decode": {"status": "passed" if l4_passed else "blocked"},
            "microarchitecture_execute": {
                "status": "passed" if l4_passed else "blocked"
            },
            "completion": {"status": "passed" if l4_passed else "blocked"},
            "gem5_preflight": dict(gem5_preflight),
            "target_result": {
                "gem5_returncode": target_result.get("gem5_returncode"),
                "markers": dict(target_result.get("markers") or {}),
                "driver_iteration_count": target_result.get(
                    "driver_iteration_count"
                ),
                "completion_writeback_count": target_result.get(
                    "completion_writeback_count"
                ),
            },
        },
        "correctness": dict(correctness),
        "pure_qe_baseline": {
            "status": "passed" if baseline.get("status") == "passed" else "blocked",
            "baseline_result": dict(baseline),
            "baseline_path": str(out_dir / "qe_baselines"),
            "gpu_runtime_context": dict(baseline.get("gpu_runtime_context") or {}),
        },
        "baseline_gpu_runtime_context": dict(
            baseline.get("gpu_runtime_context") or {}
        ),
        "accelerated_replacement": replacement,
        "speed_signal": dict(speed_signal),
        "commands": {
            "pure_qe_baseline_command": baseline.get("qe_command"),
            "bundle_runner": [
                sys.executable,
                str(Path(__file__).resolve()),
                "--bundle-id",
                bundle_id,
            ],
            "target_bridge_script": target_result.get("bridge_script"),
        },
        "blockers": list(target_result.get("blockers") or []),
        "claim_boundary": (
            "Per-target non-smoke actual-compute evidence extracted from a "
            "single-QE-workflow bundle run; not a bundle-level value claim."
        ),
    }
    row["value_verdict"] = classify_l4_offload_value(row)
    return row


def _write_target_attempt_evidence(
    *,
    out_dir: Path,
    opportunity_manifest: Mapping[str, Any],
    target_runtime_rows: Sequence[Mapping[str, Any]],
    target_results: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Any],
    trace_evidence: Mapping[str, Any],
    gem5_preflight: Mapping[str, Any],
    correctness: Mapping[str, Any],
    speed_signal: Mapping[str, Any],
    actual_compute_passed: bool,
    bundle_id: str,
    full_bundle_target_coverage: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target_by_kernel = {
        str(target.get("kernel") or ""): target for target in target_runtime_rows
    }
    for target_result in target_results:
        kernel = str(target_result.get("kernel") or "")
        target = target_by_kernel.get(kernel, {})
        row = _target_attempt_evidence_row(
            target_result=target_result,
            target=target,
            baseline=baseline,
            trace_evidence=trace_evidence,
            gem5_preflight=gem5_preflight,
            correctness=correctness,
            speed_signal=speed_signal,
            actual_compute_passed=actual_compute_passed,
            bundle_id=bundle_id,
            full_bundle_target_coverage=full_bundle_target_coverage,
            out_dir=out_dir,
        )
        rows.append(row)
        target_dir = out_dir / "target_attempts" / _safe_path_component(kernel)
        _write_json(target_dir / "l4_offload_attempt_evidence.json", row)

    evidence_rows_payload = {
        "schema_version": "dse.qe_bundle_target_l4_attempt_evidence_rows.v1",
        "bundle_id": bundle_id,
        "row_count": len(rows),
        "rows": rows,
        "deliverable_complete": False,
        "claim_boundary": (
            "Per-target rows make the bundle actual-compute run visible to the "
            "normal value matrix; bundle-level value remains separately gated."
        ),
    }
    _write_json(out_dir / "l4_offload_attempt_evidence_rows.json", evidence_rows_payload)
    matrix = build_offload_value_l4_evidence_matrix(opportunity_manifest, rows)
    report = build_offload_value_report(matrix)
    _write_json(out_dir / "offload_value_l4_evidence_matrix.json", matrix)
    _write_json(out_dir / "offload_value_report.json", report)
    return rows, matrix, report


def run_bundle_single_workflow_actual_compute(
    *,
    out_dir: Path,
    artifact_root: Path,
    bundle_id: str,
    target_kernels: Sequence[str],
    qe_bin_dir: Path | None,
    qe_pseudo_dir: Path | None,
    qe_timeout: int,
    workload_variant_id: str | None,
    gem5_binary: Path,
    gem5_config: Path,
    gem5_driver: Path,
    simulator: Path,
    max_ticks: int,
    max_batched_trace_count: int,
    max_driver_repeat_per_kernel: int,
    prelaunch_kernels: set[str],
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_space = _load_json(artifact_root / "offload_bundle_search_space.json")
    opportunity_manifest = _load_json(artifact_root / "offload_opportunity_manifest.json")
    _copytree_or_file(
        artifact_root / "offload_bundle_search_space.json",
        out_dir / "offload_bundle_search_space.json",
    )
    _copytree_or_file(
        artifact_root / "offload_opportunity_manifest.json",
        out_dir / "offload_opportunity_manifest.json",
    )

    blockers: list[str] = []
    bundle = _bundle_by_id(bundle_space).get(str(bundle_id))
    if bundle is None:
        blockers.append(f"unknown_bundle_id:{bundle_id}")
        bundle = {"bundle_id": bundle_id, "opportunity_ids": []}
    opportunities = _opportunity_by_id(opportunity_manifest)
    selected_targets, target_blockers = _select_bundle_targets(
        bundle=bundle,
        opportunities=opportunities,
        target_kernels=target_kernels,
    )
    blockers.extend(target_blockers)
    if len(selected_targets) < 2:
        blockers.append("single_workflow_bundle_requires_at_least_two_targets")
    full_bundle_target_coverage = set(bundle.get("opportunity_ids", []) or []) == {
        str(target.get("opportunity_id")) for target in selected_targets
    }
    if not full_bundle_target_coverage:
        blockers.append("single_qe_workflow_does_not_cover_full_bundle")

    cases = _case_index()
    case_id = str(bundle.get("workload_case_id") or "")
    case = cases.get(case_id)
    if not isinstance(case, Mapping):
        blockers.append(f"bundle_workload_case_unknown:{case_id}")
        case = {}
    workload_variant_profile: dict[str, Any] = {
        "workload_variant_applied": False,
        "workload_variant_id": None,
    }
    if case and workload_variant_id:
        case, workload_variant_profile = _apply_workload_variant_binding(
            case=case,
            opportunity=selected_targets[0] if selected_targets else {},
            workload_variant_id=workload_variant_id,
        )
        case_id = str(case.get("case_id") or case_id)

    baseline = (
        _run_qe_baseline(
            case,
            out_dir / "qe_baselines",
            qe_timeout,
            qe_bin_dir=qe_bin_dir or _default_qe_bin_dir(),
            qe_pseudo_dir=qe_pseudo_dir or _default_qe_pseudo_dir(),
        )
        if case
        else {"status": "blocked", "blockers": ["bundle_workload_case_unknown"]}
    )
    if baseline.get("status") != "passed":
        blockers.append("pure_qe_baseline_not_passed")

    trace_evidence = (
        _run_trace_probe(
            baseline=baseline,
            out_dir=out_dir,
            case_id=case_id,
            timeout=qe_timeout,
        )
        if baseline.get("status") == "passed"
        else {"status": "blocked", "blockers": ["pure_qe_baseline_not_passed"]}
    )
    if trace_evidence.get("status") != "passed":
        blockers.append("trace_evidence_not_passed")
    for target in selected_targets:
        kernel = str(target.get("kernel") or "")
        if not _trace_contains_kernel(trace_evidence, kernel):
            blockers.append(f"trace_evidence_missing_selected_kernel:{kernel}")

    gem5_preflight = _gem5_preflight(
        gem5_binary=gem5_binary,
        gem5_config=gem5_config,
        driver_binary=gem5_driver,
        simulator_binary=simulator,
    )
    _write_json(out_dir / "gem5_preflight.json", gem5_preflight)
    if gem5_preflight.get("can_call_real_adapter") is not True:
        blockers.append("gem5_preflight_not_ready")

    target_runtime_rows: list[dict[str, Any]] = []
    target_setup_blockers: list[str] = []
    if trace_evidence.get("status") == "passed":
        for target in selected_targets:
            runtime, runtime_blockers = _make_target_runtime(
                out_dir=out_dir,
                opportunity=target,
                trace_evidence=trace_evidence,
                gem5_binary=gem5_binary,
                gem5_config=gem5_config,
                gem5_driver=gem5_driver,
                simulator=simulator,
                max_ticks=max_ticks,
                max_batched_trace_count=max_batched_trace_count,
                max_driver_repeat_per_kernel=max_driver_repeat_per_kernel,
                prelaunch_kernels=prelaunch_kernels,
            )
            target_runtime_rows.append(runtime)
            target_setup_blockers.extend(runtime_blockers)
    blockers.extend(target_setup_blockers)

    bridge_root = (out_dir / "qe_bundle_patched_bridge").resolve()
    env = os.environ.copy()
    env.pop("QE_OFFLOAD_TRACE_FILE", None)
    env["QE_OFFLOAD_STRICT_REPLACEMENT"] = "1"
    manifest_payload = _install_bundle_runtime_env(
        env,
        bridge_dir=bridge_root,
        bundle_id=str(bundle_id),
        targets=target_runtime_rows,
        runtime_mode="single_qe_workflow_multi_callsite_actual_compute",
    )
    manifest = dict(manifest_payload.get("manifest") or {})
    manifest["single_qe_workflow_multi_callsite_bundle"] = False
    manifest["actual_compute_execution_attempted"] = True
    manifest["full_bundle_target_coverage"] = full_bundle_target_coverage
    _write_json(Path(manifest_payload["manifest_path"]), manifest)
    manifest_payload["manifest"] = manifest

    baseline_dir = out_dir / "qe_baselines" / case_id
    steps = [
        step
        for step in baseline.get("steps", []) or []
        if isinstance(step, Mapping) and step.get("concrete_command")
    ]
    stage_scoped_bridge = any(
        _step_matches_opportunity_stage(step, target)
        for step in steps
        for target in selected_targets
    )
    prelaunch_processes: list[subprocess.Popen[str]] = []
    for target in target_runtime_rows:
        if target.get("prelaunch_bridge") is True:
            prelaunch_processes.append(
                subprocess.Popen(
                    [str(Path(target["bridge_script"]).resolve())],
                    cwd=baseline_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    env=env,
                )
            )

    step_results: list[dict[str, Any]] = []
    total_elapsed = 0.0
    workflow_start = time.monotonic()
    if not steps:
        blockers.append("patched_qe_baseline_steps_missing")
    for index, step in enumerate(steps):
        command_line = [str(item) for item in step.get("concrete_command", [])]
        step_id = str(step.get("step_id") or f"stage_{index:02d}")
        bridge_active_for_step = (
            any(_step_matches_opportunity_stage(step, target) for target in selected_targets)
            if stage_scoped_bridge
            else True
        )
        step_env = env.copy()
        if not bridge_active_for_step:
            for key in list(step_env):
                if key in {
                    "QE_OFFLOAD_STRICT_REPLACEMENT",
                    "QE_OFFLOAD_BUNDLE_RUNTIME_MANIFEST",
                    "QE_OFFLOAD_BUNDLE_TARGETS",
                } or key.startswith(
                    (
                        "QE_OFFLOAD_BRIDGE_COMMAND_",
                        "QE_OFFLOAD_KERNEL_EVIDENCE_JSON_",
                        "QE_OFFLOAD_PROVENANCE_JSON_",
                        "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON_",
                        "QE_OFFLOAD_ACCELERATED_INPUT_JSON_",
                        "QE_OFFLOAD_ACCELERATED_INPUT_DATA_",
                        "QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_",
                    )
                ):
                    step_env.pop(key, None)
        stdout_path = bridge_root / f"patched_{step_id}.stdout.log"
        stderr_path = bridge_root / f"patched_{step_id}.stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                command_line,
                cwd=baseline_dir,
                capture_output=True,
                text=True,
                timeout=qe_timeout + 180,
                env=step_env,
            )
            elapsed = time.monotonic() - start
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            returncode: int | None = completed.returncode
            timeout_hit = False
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - start
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else str(exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr or "")
            )
            returncode = None
            timeout_hit = True
        total_elapsed += elapsed
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        metrics = _parse_qe_stdout(stdout)
        step_blockers: list[str] = []
        if timeout_hit:
            step_blockers.append("patched_qe_bundle_timeout")
        if returncode not in {0, None}:
            step_blockers.append(f"patched_qe_bundle_returncode:{returncode}")
        step_results.append(
            {
                "step_id": step_id,
                "command": command_line,
                "returncode": returncode,
                "timeout": timeout_hit,
                "elapsed_seconds": elapsed,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "metrics": metrics,
                "bridge_active_for_selected_stage": bridge_active_for_step,
                "blockers": step_blockers,
            }
        )
        blockers.extend(step_blockers)
        if step_blockers:
            break

    for process in prelaunch_processes:
        if process.poll() is None:
            try:
                process.wait(timeout=qe_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                blockers.append("prelaunched_bundle_gem5_bridge_timeout")
    if prelaunch_processes:
        total_elapsed = time.monotonic() - workflow_start
    for target in target_runtime_rows:
        pid_value = target.get("fft_payload_daemon_pid_path")
        if not pid_value:
            continue
        pid_path = Path(pid_value)
        if not pid_path.exists():
            continue
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            continue
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass

    baseline_terminal_metrics = (
        baseline.get("performance_metrics", {}).get("terminal_step_metrics", {})
        if isinstance(baseline.get("performance_metrics"), Mapping)
        else {}
    )
    baseline_metrics = _select_correctness_metrics(
        baseline_terminal_metrics if isinstance(baseline_terminal_metrics, Mapping) else {},
        baseline.get("steps", []) if isinstance(baseline.get("steps"), list) else [],
    )
    patched_terminal_metrics = step_results[-1].get("metrics", {}) if step_results else {}
    patched_metrics = _select_correctness_metrics(
        patched_terminal_metrics if isinstance(patched_terminal_metrics, Mapping) else {},
        step_results,
    )
    correctness = _physical_correctness(baseline_metrics, patched_metrics)
    if correctness.get("status") != "passed":
        blockers.extend(correctness.get("blockers", []) or [])

    target_results = [_target_result(target) for target in target_runtime_rows]
    for target in target_runtime_rows:
        workspace = target.get("runtime_bridge_workspace")
        if isinstance(workspace, Mapping):
            _materialize_bridge_runtime_workspace(workspace)
            workspace["post_timing_materialized"] = (
                workspace.get("runtime_storage_policy") == "symlink_to_local_tmp"
            )
    for target_result in target_results:
        blockers.extend(target_result.get("blockers", []) or [])

    baseline_elapsed = baseline.get("elapsed_seconds")
    speedup = (
        float(baseline_elapsed) / float(total_elapsed)
        if isinstance(baseline_elapsed, (int, float)) and total_elapsed > 0
        else None
    )
    speed_positive = isinstance(speedup, float) and speedup > 1.0
    if speedup is None:
        blockers.append("speed_signal_elapsed_missing")
    elif not speed_positive:
        blockers.append("positive_speed_signal_missing")

    target_count = len(target_results)
    target_pass_count = sum(1 for row in target_results if row.get("status") == "passed")
    multi_target_consumed = target_count >= 2 and target_pass_count >= 2
    actual_compute_passed = (
        baseline.get("status") == "passed"
        and trace_evidence.get("status") == "passed"
        and gem5_preflight.get("can_call_real_adapter") is True
        and multi_target_consumed
        and correctness.get("status") == "passed"
    )
    single_qe_workflow_proven = actual_compute_passed
    bundle_level_valuable_l4 = (
        actual_compute_passed and full_bundle_target_coverage and speed_positive
    )
    claim_boundary = (
        "single-QE-workflow non-smoke bundle attempt; bundle actual-compute "
        "coverage is proven for the selected bundle, but bundle value remains "
        "false unless correctness and positive speed both pass"
        if full_bundle_target_coverage
        else (
            "single-QE-workflow non-smoke bundle attempt; partial supported "
            "target coverage proves progress only, and bundle value remains "
            "false unless the full bundle is covered with correctness and "
            "positive speed"
        )
    )
    speed_signal = {
        "status": "positive" if speed_positive else "non_positive",
        "speedup_vs_pure_qe": speedup,
        "blockers": [] if speed_positive else ["positive_speed_signal_missing"],
    }
    (
        target_attempt_rows,
        target_attempt_matrix,
        target_attempt_value_report,
    ) = _write_target_attempt_evidence(
        out_dir=out_dir,
        opportunity_manifest=opportunity_manifest,
        target_runtime_rows=target_runtime_rows,
        target_results=target_results,
        baseline=baseline,
        trace_evidence=trace_evidence,
        gem5_preflight=gem5_preflight,
        correctness=correctness,
        speed_signal=speed_signal,
        actual_compute_passed=actual_compute_passed,
        bundle_id=str(bundle_id),
        full_bundle_target_coverage=full_bundle_target_coverage,
    )

    report = {
        "schema_version": "dse.qe_bundle_single_workflow_actual_compute.v1",
        "status": (
            "valuable_l4"
            if bundle_level_valuable_l4
            else (
                "actual_compute_not_valuable_l4"
                if actual_compute_passed
                else "blocked"
            )
        ),
        "bundle_id": str(bundle_id),
        "selected_bundle_ids": [str(bundle_id)],
        "workload_case_id": case_id,
        "workload_variant_profile": workload_variant_profile,
        "stage_type": bundle.get("stage_type"),
        "target_kernels": [str(row.get("kernel")) for row in selected_targets],
        "target_opportunity_ids": [
            str(row.get("opportunity_id")) for row in selected_targets
        ],
        "full_bundle_opportunity_ids": list(bundle.get("opportunity_ids") or []),
        "target_count": target_count,
        "target_pass_count": target_pass_count,
        "full_bundle_target_coverage": full_bundle_target_coverage,
        "single_qe_workflow_covers_full_bundle": full_bundle_target_coverage,
        "single_qe_workflow_proven": single_qe_workflow_proven,
        "single_qe_workflow_bundle_attempt_executed": bool(step_results),
        "non_smoke_actual_compute": True,
        "non_smoke_actual_compute_attempt_count": 1,
        "actual_compute_full_qe_evidence_passed_count": (
            1 if actual_compute_passed else 0
        ),
        "valuable_l4_count": 1 if bundle_level_valuable_l4 else 0,
        "bundle_level_valuable_l4": bundle_level_valuable_l4,
        "bundle_value_allowed": bundle_level_valuable_l4,
        "selected_bundle_expanded_opportunity_count": 0,
        "attempted_count": 1,
        "baseline_elapsed_seconds": baseline_elapsed,
        "patched_qe_elapsed_seconds": total_elapsed if step_results else None,
        "speed_signal": speed_signal,
        "target_attempt_evidence_rows_path": str(
            out_dir / "l4_offload_attempt_evidence_rows.json"
        ),
        "target_attempt_evidence_row_count": len(target_attempt_rows),
        "target_attempt_value_matrix_path": str(
            out_dir / "offload_value_l4_evidence_matrix.json"
        ),
        "target_attempt_value_report_path": str(out_dir / "offload_value_report.json"),
        "target_attempt_value_matrix_summary": {
            "valuable_l4_count": target_attempt_matrix.get("valuable_l4_count", 0),
            "non_smoke_actual_compute_attempt_count": target_attempt_matrix.get(
                "non_smoke_actual_compute_attempt_count", 0
            ),
            "actual_compute_full_qe_evidence_passed_count": target_attempt_matrix.get(
                "actual_compute_full_qe_evidence_passed_count", 0
            ),
            "actual_compute_not_valuable_l4_count": target_attempt_matrix.get(
                "actual_compute_not_valuable_l4_count", 0
            ),
            "actual_compute_attempted_kernels": target_attempt_matrix.get(
                "actual_compute_attempted_kernels", []
            ),
        },
        "target_attempt_value_report_summary": dict(
            target_attempt_value_report.get("summary") or {}
        ),
        "pure_qe_baseline": baseline,
        "trace_evidence": trace_evidence,
        "gem5_preflight": gem5_preflight,
        "bundle_runtime_manifest_path": manifest_payload.get("manifest_path"),
        "bundle_runtime_manifest": manifest_payload.get("manifest"),
        "patched_qe_steps": step_results,
        "correctness": correctness,
        "target_results": target_results,
        "blockers": sorted(dict.fromkeys(str(item) for item in blockers)),
        "deliverable_complete": False,
        "claim_boundary": claim_boundary,
    }
    _write_json(out_dir / "bundle_single_workflow_actual_compute_report.json", report)
    bundle_gate = build_bundle_single_workflow_l4_evidence_report(
        bundle_space,
        [
            {
                **report,
                "status_path": str(out_dir / "status.json"),
                "campaign_root": str(out_dir),
            }
        ],
    )
    _write_json(out_dir / "bundle_single_workflow_l4_evidence_report.json", bundle_gate)
    status = {
        "schema_version": "dse.qe_bundle_single_workflow_actual_compute_status.v1",
        "status": report["status"],
        "report_path": str(out_dir / "bundle_single_workflow_actual_compute_report.json"),
        "bundle_single_workflow_l4_evidence_report": str(
            out_dir / "bundle_single_workflow_l4_evidence_report.json"
        ),
        "selected_bundle_ids": [str(bundle_id)],
        "attempted_count": report["attempted_count"],
        "selected_bundle_expanded_opportunity_count": 0,
        "non_smoke_actual_compute_attempt_count": 1,
        "actual_compute_full_qe_evidence_passed_count": report[
            "actual_compute_full_qe_evidence_passed_count"
        ],
        "valuable_l4_count": report["valuable_l4_count"],
        "single_qe_workflow_proven": report["single_qe_workflow_proven"],
        "single_qe_workflow_covers_full_bundle": full_bundle_target_coverage,
        "bundle_level_valuable_l4": report["bundle_level_valuable_l4"],
        "bundle_value_allowed": report["bundle_value_allowed"],
        "target_count": target_count,
        "target_pass_count": target_pass_count,
        "target_kernels": report["target_kernels"],
        "workload_variant_profile": workload_variant_profile,
        "target_opportunity_ids": report["target_opportunity_ids"],
        "full_bundle_target_coverage": full_bundle_target_coverage,
        "baseline_elapsed_seconds": baseline_elapsed,
        "patched_qe_elapsed_seconds": report["patched_qe_elapsed_seconds"],
        "speed_signal": report["speed_signal"],
        "bundle_gate_status": bundle_gate.get("status"),
        "bundle_gate_bundle_level_valuable_l4_count": bundle_gate.get(
            "bundle_level_valuable_l4_count", 0
        ),
        "blockers": report["blockers"],
        "deliverable_complete": False,
        "claim_boundary": report["claim_boundary"],
    }
    _write_json(out_dir / "status.json", status)
    return status


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument(
        "--target-kernel",
        action="append",
        default=[],
        help=(
            "Kernel to include in the single-workflow attempt. Defaults to "
            "the currently supported non-placeholder kernels."
        ),
    )
    parser.add_argument("--qe-bin-dir", type=Path, default=None)
    parser.add_argument("--qe-pseudo-dir", type=Path, default=None)
    parser.add_argument("--qe-baseline-timeout", type=int, default=120)
    parser.add_argument(
        "--workload-variant-id",
        default=None,
        choices=[
            SPSI_NC_CG_WORKLOAD_VARIANT_ID,
            SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
            SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
            NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
            NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
            NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
            NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
        ],
        help=(
            "Optional real-QE workload scaling variant. Variant binding is "
            "selection context only and never upgrades value by itself."
        ),
    )
    parser.add_argument("--gem5-transport-max-ticks", type=int, default=3_000_000_000)
    parser.add_argument(
        "--max-batched-bridge-trace-count",
        type=int,
        default=DEFAULT_MAX_BATCHED_BRIDGE_TRACE_COUNT,
    )
    parser.add_argument(
        "--max-driver-repeat-per-kernel",
        type=int,
        default=0,
        help=(
            "Optional cap for GenericAccel driver-repeat on non-prelaunched "
            "kernels. The report blocks if actual bridge invocations exceed "
            "completed driver iterations."
        ),
    )
    parser.add_argument(
        "--prelaunch-kernel",
        action="append",
        default=["subspace_rotation"],
        help=(
            "Kernel bridge to prelaunch before QE reaches the selected stage. "
            "May be repeated; defaults to subspace_rotation."
        ),
    )
    parser.add_argument(
        "--prelaunch-all-targets",
        action="store_true",
        help="Prelaunch every selected target bridge and reuse completed L4 results at QE callsites.",
    )
    parser.add_argument(
        "--gem5-binary",
        type=Path,
        default=REPO_ROOT
        / "gem5_integration"
        / "gem5"
        / "build"
        / "X86"
        / "gem5.opt",
    )
    parser.add_argument(
        "--gem5-config",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py",
    )
    parser.add_argument(
        "--gem5-driver",
        type=Path,
        default=REPO_ROOT
        / "gem5_integration"
        / "test_programs"
        / "generic_accel"
        / "generic_accel_l4_driver",
    )
    parser.add_argument(
        "--simulator",
        type=Path,
        default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target_kernels = args.target_kernel or list(SUPPORTED_ACTUAL_COMPUTE_KERNELS)
    prelaunch_kernels = set(target_kernels) if args.prelaunch_all_targets else set(
        args.prelaunch_kernel or []
    )
    status = run_bundle_single_workflow_actual_compute(
        out_dir=args.out,
        artifact_root=args.artifact_root,
        bundle_id=args.bundle_id,
        target_kernels=target_kernels,
        qe_bin_dir=args.qe_bin_dir,
        qe_pseudo_dir=args.qe_pseudo_dir,
        qe_timeout=args.qe_baseline_timeout,
        workload_variant_id=args.workload_variant_id,
        gem5_binary=args.gem5_binary,
        gem5_config=args.gem5_config,
        gem5_driver=args.gem5_driver,
        simulator=args.simulator,
        max_ticks=args.gem5_transport_max_ticks,
        max_batched_trace_count=args.max_batched_bridge_trace_count,
        max_driver_repeat_per_kernel=args.max_driver_repeat_per_kernel,
        prelaunch_kernels=prelaunch_kernels,
    )
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
