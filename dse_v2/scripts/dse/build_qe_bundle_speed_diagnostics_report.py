#!/usr/bin/env python3
"""Build a value-neutral speed diagnostics report for QE bundle L4 runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "dse.qe_bundle_speed_diagnostics_report.v1"
CLAIM_BOUNDARY = (
    "speed diagnostics only; this report explains end-to-end timing deltas and "
    "bridge/runtime overhead, but cannot upgrade smoke, projection, member-only, "
    "or non-positive-speed evidence into valuable_l4"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return {}
    return _load_json(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _read_int(path: Path) -> int | None:
    if not path.exists():
        return None
    return _as_int(path.read_text(encoding="utf-8"))


def _step_metrics(step: Mapping[str, Any]) -> dict[str, Any]:
    metrics = step.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    timers = metrics.get("timers")
    if not isinstance(timers, Mapping):
        timers = {}
    pwscf = timers.get("PWSCF") if isinstance(timers.get("PWSCF"), Mapping) else {}
    return {
        "elapsed_seconds": _as_float(step.get("elapsed_seconds")),
        "program_wall_seconds": _as_float(metrics.get("program_wall_seconds")),
        "pwscf_wall_seconds": _as_float(pwscf.get("wall_seconds") if isinstance(pwscf, Mapping) else None),
        "bridge_active_for_selected_stage": step.get("bridge_active_for_selected_stage") is True,
        "returncode": step.get("returncode"),
        "timeout": step.get("timeout") is True,
    }


def _steps_by_id(steps: Sequence[Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for step in steps or []:
        if not isinstance(step, Mapping):
            continue
        step_id = str(step.get("step_id") or "").strip()
        if not step_id:
            continue
        result[step_id] = _step_metrics(step)
    return result


def _build_stage_breakdown(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    baseline = report.get("pure_qe_baseline")
    if not isinstance(baseline, Mapping):
        baseline = {}
    baseline_steps = _steps_by_id(baseline.get("steps") if isinstance(baseline.get("steps"), Sequence) else [])
    patched_steps = _steps_by_id(report.get("patched_qe_steps") if isinstance(report.get("patched_qe_steps"), Sequence) else [])
    stage_ids = sorted(set(baseline_steps) | set(patched_steps))
    rows: list[dict[str, Any]] = []
    for step_id in stage_ids:
        base = baseline_steps.get(step_id, {})
        patched = patched_steps.get(step_id, {})
        baseline_elapsed = _as_float(base.get("elapsed_seconds"))
        patched_elapsed = _as_float(patched.get("elapsed_seconds"))
        delta = None
        ratio = None
        if baseline_elapsed is not None and patched_elapsed is not None:
            delta = patched_elapsed - baseline_elapsed
            ratio = baseline_elapsed / patched_elapsed if patched_elapsed > 0 else None
        rows.append(
            {
                "step_id": step_id,
                "baseline_elapsed_seconds": baseline_elapsed,
                "patched_elapsed_seconds": patched_elapsed,
                "patched_minus_baseline_seconds": delta,
                "stage_speedup_vs_pure_qe": ratio,
                "bridge_active_for_selected_stage": patched.get("bridge_active_for_selected_stage") is True,
                "baseline_program_wall_seconds": base.get("program_wall_seconds"),
                "patched_program_wall_seconds": patched.get("program_wall_seconds"),
                "baseline_pwscf_wall_seconds": base.get("pwscf_wall_seconds"),
                "patched_pwscf_wall_seconds": patched.get("pwscf_wall_seconds"),
                "baseline_returncode": base.get("returncode"),
                "patched_returncode": patched.get("returncode"),
            }
        )
    return rows


def _timer_lookup(step: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = step.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    timers = metrics.get("timers")
    if not isinstance(timers, Mapping):
        return {}
    return timers


def _terminal_step(steps: Sequence[Any] | None) -> Mapping[str, Any]:
    for step in reversed(list(steps or [])):
        if isinstance(step, Mapping):
            return step
    return {}


def _build_timer_diagnostics(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    target_kernels = [str(item) for item in report.get("target_kernels") or []]
    baseline = report.get("pure_qe_baseline")
    if not isinstance(baseline, Mapping):
        baseline = {}
    baseline_terminal = _terminal_step(baseline.get("steps") if isinstance(baseline.get("steps"), Sequence) else [])
    patched_terminal = _terminal_step(report.get("patched_qe_steps") if isinstance(report.get("patched_qe_steps"), Sequence) else [])
    baseline_timers = _timer_lookup(baseline_terminal)
    patched_timers = _timer_lookup(patched_terminal)
    aliases = {
        "fft": ["fft", "fftw"],
        "subspace_rotation": ["cdiaghg", "cegterg", "c_bands"],
        "diagonalization": ["cdiaghg", "cegterg", "c_bands"],
        "h_psi": ["h_psi"],
        "s_psi": ["s_psi"],
        "forces": ["forces"],
        "mix_rho": ["mix_rho"],
        "rho_out": ["v_of_rho", "v_h", "v_xc"],
        "veff": ["v_of_rho", "v_h", "v_xc"],
    }
    rows: list[dict[str, Any]] = []
    for kernel in target_kernels:
        timer_names = aliases.get(kernel, [kernel])
        entries: list[dict[str, Any]] = []
        for name in timer_names:
            base = baseline_timers.get(name) if isinstance(baseline_timers.get(name), Mapping) else {}
            patched = patched_timers.get(name) if isinstance(patched_timers.get(name), Mapping) else {}
            base_wall = _as_float(base.get("wall_seconds") if isinstance(base, Mapping) else None)
            patched_wall = _as_float(patched.get("wall_seconds") if isinstance(patched, Mapping) else None)
            if base_wall is None and patched_wall is None:
                continue
            entries.append(
                {
                    "timer": name,
                    "baseline_wall_seconds": base_wall,
                    "patched_wall_seconds": patched_wall,
                    "patched_minus_baseline_wall_seconds": (
                        patched_wall - base_wall
                        if base_wall is not None and patched_wall is not None
                        else None
                    ),
                }
            )
        rows.append(
            {
                "kernel": kernel,
                "timer_aliases": timer_names,
                "timer_entries": entries,
                "timer_observed": bool(entries),
                "claim_boundary": "QE timer attribution is diagnostic only; valuable_l4 uses end-to-end workflow speed.",
            }
        )
    return rows


def _build_bridge_counts(bundle_run_dir: Path) -> list[dict[str, Any]]:
    slots_dir = bundle_run_dir / "bundle_runtime_slots"
    rows: list[dict[str, Any]] = []
    if not slots_dir.exists():
        return rows
    for slot in sorted(path for path in slots_dir.iterdir() if path.is_dir()):
        kernel_evidence = _maybe_load_json(slot / "runtime_kernel_evidence.json")
        kernel_evidence_rows = kernel_evidence if isinstance(kernel_evidence, list) else []
        if isinstance(kernel_evidence, Mapping):
            kernel_evidence_map: Mapping[str, Any] = kernel_evidence
        elif kernel_evidence_rows and isinstance(kernel_evidence_rows[0], Mapping):
            kernel_evidence_map = kernel_evidence_rows[0]
        else:
            kernel_evidence_map = {}
        provenance = _maybe_load_json(slot / "runtime_offload_provenance.json")
        if not isinstance(provenance, Mapping):
            provenance = {}
        invocation_count = _read_int(slot / "gem5_bridge_invocation_count.txt")
        launch_count = _read_int(slot / "gem5_bridge_launch_count.txt")
        evidence_status = kernel_evidence_map.get("status")
        if evidence_status is None and (
            kernel_evidence_map.get("accelerated_results_consumed_by_qe") is True
            or kernel_evidence_map.get("qe_kernel_work_replaced_on_critical_path")
            is True
        ):
            evidence_status = "passed"
        provenance_status = provenance.get("status")
        if provenance_status is None and (
            provenance.get("accelerated_results_consumed_by_qe") is True
            or provenance.get("qe_kernel_work_replaced_on_critical_path") is True
        ):
            provenance_status = "passed"
        rows.append(
            {
                "kernel": slot.name,
                "gem5_bridge_invocation_count": invocation_count,
                "gem5_bridge_launch_count": launch_count,
                "gem5_bridge_returncode": _read_int(slot / "gem5_bridge_returncode.txt"),
                "runtime_kernel_evidence_status": evidence_status,
                "runtime_offload_provenance_status": provenance_status,
                "runtime_kernel_evidence_count": len(kernel_evidence_rows)
                if kernel_evidence_rows
                else (1 if kernel_evidence_map else 0),
                "persistent_or_batched_dispatch_observed": (
                    kernel_evidence_map.get("persistent_or_batched_dispatch_observed") is True
                    or provenance.get("persistent_or_batched_dispatch_observed") is True
                    or (
                        isinstance(invocation_count, int)
                        and isinstance(launch_count, int)
                        and invocation_count > launch_count >= 1
                    )
                ),
            }
        )
    return rows


def _campaign_status_rows(matrix_status_path: Path | None) -> list[dict[str, Any]]:
    status = _maybe_load_json(matrix_status_path)
    rows: list[dict[str, Any]] = []
    artifacts = status.get("source_bundle_campaign_status_artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        return rows
    for artifact in artifacts:
        path = Path(str(artifact))
        if not path.exists():
            continue
        payload = _load_json(path)
        speed_signal = payload.get("speed_signal")
        if not isinstance(speed_signal, Mapping):
            speed_signal = {}
        workload_variant = payload.get("workload_variant_profile")
        if not isinstance(workload_variant, Mapping):
            workload_variant = {}
        rows.append(
            {
                "source_status_artifact": str(path),
                "status": payload.get("status"),
                "bundle_gate_status": payload.get("bundle_gate_status"),
                "selected_bundle_ids": payload.get("selected_bundle_ids") or [],
                "target_kernels": payload.get("target_kernels") or [],
                "baseline_elapsed_seconds": _as_float(payload.get("baseline_elapsed_seconds")),
                "patched_qe_elapsed_seconds": _as_float(payload.get("patched_qe_elapsed_seconds")),
                "speedup_vs_pure_qe": _as_float(speed_signal.get("speedup_vs_pure_qe")),
                "speed_status": speed_signal.get("status"),
                "blockers": payload.get("blockers") or speed_signal.get("blockers") or [],
                "workload_variant_id": workload_variant.get("workload_variant_id"),
                "runtime_workload_case_id": workload_variant.get("runtime_workload_case_id"),
                "workload_scale_policy": (
                    workload_variant.get("workload_variant_binding") or {}
                ).get("workload_scale_policy")
                if isinstance(workload_variant.get("workload_variant_binding"), Mapping)
                else None,
            }
        )
    return rows


def _repeatability_rows(
    repeatability_report_path: Path | None,
    *,
    target_kernels: Sequence[str],
    target_opportunity_ids: Sequence[str],
) -> list[dict[str, Any]]:
    report = _maybe_load_json(repeatability_report_path)
    raw_rows = report.get("rows")
    if not isinstance(raw_rows, list):
        return []
    kernel_set = set(target_kernels)
    opportunity_set = set(target_opportunity_ids)
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("kernel") not in kernel_set and row.get("opportunity_id") not in opportunity_set:
            continue
        rows.append(
            {
                "kernel": row.get("kernel"),
                "opportunity_id": row.get("opportunity_id"),
                "runtime_workload_case_id": row.get("runtime_workload_case_id"),
                "workload_variant_id": row.get("workload_variant_id"),
                "speed_repeatability_status": row.get("speed_repeatability_status"),
                "repeatability_status": row.get("repeatability_status"),
                "repeatability_stable_value": row.get("repeatability_stable_value") is True,
                "speedups_vs_pure_qe": row.get("speedups_vs_pure_qe") or [],
                "min_speedup_vs_pure_qe": _as_float(row.get("min_speedup_vs_pure_qe")),
                "max_speedup_vs_pure_qe": _as_float(row.get("max_speedup_vs_pure_qe")),
                "positive_speed_sample_count": row.get("positive_speed_sample_count"),
                "non_positive_speed_sample_count": row.get("non_positive_speed_sample_count"),
                "blockers": row.get("blockers") or [],
            }
        )
    return rows


def _speed_summary(
    baseline_elapsed: float | None,
    patched_elapsed: float | None,
) -> dict[str, Any]:
    speedup = None
    delta = None
    status = "missing_timing"
    blockers: list[str] = ["timing_missing"]
    if baseline_elapsed is not None and patched_elapsed is not None and patched_elapsed > 0:
        speedup = baseline_elapsed / patched_elapsed
        delta = patched_elapsed - baseline_elapsed
        if speedup > 1.0:
            status = "positive"
            blockers = []
        else:
            status = "non_positive"
            blockers = ["positive_speed_signal_missing"]
    return {
        "formula": "pure_qe_baseline_elapsed_seconds / patched_qe_elapsed_seconds",
        "baseline_elapsed_seconds": baseline_elapsed,
        "patched_qe_elapsed_seconds": patched_elapsed,
        "speedup_vs_pure_qe": speedup,
        "patched_minus_baseline_seconds": delta,
        "positive_speed_required": "speedup_vs_pure_qe > 1.0, equivalent to patched_qe_elapsed_seconds < pure_qe_baseline_elapsed_seconds",
        "status": status,
        "blockers": blockers,
        "seconds_to_reach_parity": max(0.0, delta) if delta is not None else None,
        "minimum_additional_reduction_for_strict_positive_seconds": max(0.0, delta)
        if delta is not None
        else None,
        "measurement_margin_note": "strict positivity needs any reduction beyond parity plus an experiment-specific noise margin; this report records parity debt, not a statistical confidence interval",
    }


def build_bundle_speed_diagnostics_report(
    *,
    bundle_run_dir: Path,
    matrix_status_path: Path | None = None,
    repeatability_report_path: Path | None = None,
) -> dict[str, Any]:
    bundle_run_dir = bundle_run_dir.resolve()
    actual_report_path = bundle_run_dir / "bundle_single_workflow_actual_compute_report.json"
    status_path = bundle_run_dir / "status.json"
    report = _load_json(actual_report_path)
    status_payload = _maybe_load_json(status_path)
    baseline = report.get("pure_qe_baseline")
    if not isinstance(baseline, Mapping):
        baseline = {}
    baseline_elapsed = _as_float(
        report.get("baseline_elapsed_seconds") or baseline.get("elapsed_seconds")
    )
    patched_elapsed = _as_float(report.get("patched_qe_elapsed_seconds"))
    target_kernels = [str(item) for item in report.get("target_kernels") or []]
    target_opportunity_ids = [
        str(item) for item in report.get("target_opportunity_ids") or []
    ]
    speed_summary = _speed_summary(baseline_elapsed, patched_elapsed)
    rows = _campaign_status_rows(matrix_status_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "bundle_run_dir": str(bundle_run_dir),
        "source_actual_compute_report": str(actual_report_path),
        "source_status": str(status_path) if status_path.exists() else None,
        "source_matrix_status": str(matrix_status_path) if matrix_status_path else None,
        "source_repeatability_report": str(repeatability_report_path) if repeatability_report_path else None,
        "deliverable_complete": False,
        "value_claim_allowed_by_this_report": False,
        "bundle_id": report.get("bundle_id") or (status_payload.get("selected_bundle_ids") or [None])[0],
        "target_kernels": target_kernels,
        "target_opportunity_ids": target_opportunity_ids,
        "single_qe_workflow_proven": report.get("single_qe_workflow_proven") is True
        or status_payload.get("single_qe_workflow_proven") is True,
        "single_qe_workflow_covers_full_bundle": report.get("single_qe_workflow_covers_full_bundle") is True
        or status_payload.get("single_qe_workflow_covers_full_bundle") is True,
        "bundle_level_valuable_l4": report.get("bundle_level_valuable_l4") is True,
        "speed_summary": speed_summary,
        "stage_breakdown": _build_stage_breakdown(report),
        "target_timer_diagnostics": _build_timer_diagnostics(report),
        "bridge_invocation_counts": _build_bridge_counts(bundle_run_dir),
        "campaign_bundle_speed_samples": rows,
        "campaign_bundle_speed_sample_count": len(rows),
        "repeatability_rows": _repeatability_rows(
            repeatability_report_path,
            target_kernels=target_kernels,
            target_opportunity_ids=target_opportunity_ids,
        ),
        "gpu_runtime_context": baseline.get("gpu_runtime_context"),
        "correctness_status": (report.get("correctness") or {}).get("status")
        if isinstance(report.get("correctness"), Mapping)
        else None,
        "recommended_next_actions": _recommended_next_actions(speed_summary, rows),
        "status": "speed_positive" if speed_summary["status"] == "positive" else "speed_blocked",
    }


def _recommended_next_actions(
    speed_summary: Mapping[str, Any],
    campaign_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    if speed_summary.get("status") == "positive":
        return [
            "keep this report value-neutral and verify correctness/replacement/L4 provenance gates in the value matrix",
            "repeat enough runs to distinguish stable value from single-run noise",
        ]
    actions = [
        "reduce patched QE elapsed below pure QE baseline before any bundle-level value claim",
        "inspect bridge invocation/launch counts for per-callsite overhead and batch/persist the critical-path dispatch",
        "compare SCF prerequisite vs selected-stage deltas so non-offloaded workflow noise is not mistaken for acceleration",
    ]
    if campaign_rows:
        actions.append(
            "continue workload/stage/kernel/bundle search using campaign rows rather than forcing the current bundle to pass"
        )
    return actions


def render_bundle_speed_diagnostics_markdown(report: Mapping[str, Any]) -> str:
    speed = report.get("speed_summary") if isinstance(report.get("speed_summary"), Mapping) else {}
    lines = [
        "# QE Bundle Speed Diagnostics Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Claim boundary: {report.get('claim_boundary')}",
        f"- Bundle: `{report.get('bundle_id')}`",
        f"- Target kernels: `{', '.join(report.get('target_kernels') or [])}`",
        f"- Formula: `{speed.get('formula')}`",
        f"- Baseline elapsed: `{speed.get('baseline_elapsed_seconds')}` seconds",
        f"- Patched elapsed: `{speed.get('patched_qe_elapsed_seconds')}` seconds",
        f"- Speedup vs pure QE: `{speed.get('speedup_vs_pure_qe')}`",
        f"- Patched minus baseline: `{speed.get('patched_minus_baseline_seconds')}` seconds",
        f"- Seconds to parity: `{speed.get('seconds_to_reach_parity')}`",
        f"- Value claim allowed by this report: `{report.get('value_claim_allowed_by_this_report')}`",
        f"- Deliverable complete: `{report.get('deliverable_complete')}`",
        "",
        "## Stage breakdown",
        "",
        "| Step | Baseline s | Patched s | Delta s | Stage speedup | Bridge active |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report.get("stage_breakdown") or []:
        lines.append(
            "| {step} | {base} | {patched} | {delta} | {speedup} | {bridge} |".format(
                step=row.get("step_id"),
                base=row.get("baseline_elapsed_seconds"),
                patched=row.get("patched_elapsed_seconds"),
                delta=row.get("patched_minus_baseline_seconds"),
                speedup=row.get("stage_speedup_vs_pure_qe"),
                bridge=row.get("bridge_active_for_selected_stage"),
            )
        )
    lines.extend(
        [
            "",
            "## Bridge invocation counts",
            "",
            "| Kernel | Invocations | Launches | Returncode | Persistent/batched observed |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in report.get("bridge_invocation_counts") or []:
        lines.append(
            "| {kernel} | {inv} | {launch} | {rc} | {persistent} |".format(
                kernel=row.get("kernel"),
                inv=row.get("gem5_bridge_invocation_count"),
                launch=row.get("gem5_bridge_launch_count"),
                rc=row.get("gem5_bridge_returncode"),
                persistent=row.get("persistent_or_batched_dispatch_observed"),
            )
        )
    lines.extend(["", "## Recommended next actions", ""])
    for action in report.get("recommended_next_actions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-run-dir", type=Path, required=True)
    parser.add_argument("--matrix-status", type=Path)
    parser.add_argument("--repeatability-report", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_bundle_speed_diagnostics_report(
        bundle_run_dir=args.bundle_run_dir,
        matrix_status_path=args.matrix_status,
        repeatability_report_path=args.repeatability_report,
    )
    out_json = args.out_json or args.bundle_run_dir / "bundle_speed_diagnostics_report.json"
    out_md = args.out_md or args.bundle_run_dir / "bundle_speed_diagnostics_report.md"
    _write_json(out_json, report)
    _write_text(out_md, render_bundle_speed_diagnostics_markdown(report))
    print(out_json)
    print(out_md)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
