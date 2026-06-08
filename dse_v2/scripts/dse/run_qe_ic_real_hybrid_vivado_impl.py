#!/usr/bin/env python3
"""Run Vivado implementation evidence for the integrated real-hybrid RTL sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.experiments.qe_ic_real_opportunity.real_hybrid_hls_evidence import (  # noqa: E402
    DEFAULT_FPGA_PART,
    build_combined_vcs_sidecar_accounting,
    build_integrated_vcs_sidecar_accounting,
    build_real_hybrid_architecture_specs,
    build_real_hybrid_claim_closure,
    materialize_integrated_pipelined_vivado_impl_project,
    materialize_integrated_streaming_vivado_impl_project,
    materialize_integrated_vivado_impl_project,
    merge_combined_vcs_sidecar_comparisons,
    merge_integrated_vcs_sidecar_comparisons,
    merge_integrated_vivado_impl_evidence_into_summary,
    parse_vivado_impl_timing_summary_report,
    parse_vivado_impl_utilization_report,
    render_real_hybrid_hls_report,
)

REMOTE_ALIAS = "ic-eda"
REMOTE_VIVADO = "/home/Xilinx/Vivado/2019.1/bin/vivado"
SCHEMA_VERSION = "dse.qe_ic.real_hybrid_vivado_impl_evidence.v1"
INTEGRATED_VCS_RESULT_KEYS = (
    "integrated_vcs_sidecar_result",
    "integrated_pipelined_vcs_sidecar_result",
    "integrated_streaming_vcs_sidecar_result",
)
INTEGRATED_VIVADO_RESULT_KEYS = {
    "hybrid_integrated_combined_sidecar_v1": "integrated_vivado_impl_result",
    "hybrid_integrated_pipelined_sidecar_v2": "integrated_pipelined_vivado_impl_result",
    "hybrid_integrated_streaming_pipeline_sidecar_v3": "integrated_streaming_vivado_impl_result",
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_name(value: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value)).strip("_").lower()
    return text[:96] or "architecture"


def _load_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"summary is not a JSON object: {path}")
    return payload


def _normalize_integrated_vivado_result_keys(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Move legacy non-v1 Vivado evidence into architecture-specific result keys."""

    normalized = json.loads(json.dumps(summary))
    legacy = normalized.get("integrated_vivado_impl_result")
    if isinstance(legacy, Mapping):
        architecture_id = str(legacy.get("architecture_id") or "")
        key = INTEGRATED_VIVADO_RESULT_KEYS.get(architecture_id)
        if key and key != "integrated_vivado_impl_result":
            normalized.setdefault(key, legacy)
            normalized.pop("integrated_vivado_impl_result", None)
    return normalized


def _load_gpu_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"GPU baseline is not a JSON object: {path}")
    return payload


def _gpu_runs_root_from_summary(summary: Mapping[str, Any], baseline_path: Path) -> Path:
    value = summary.get("gpu_runs_root")
    if isinstance(value, str) and value:
        return Path(value)
    return baseline_path.parent / "runs"


def _drop_stale_synthetic_sidecar_comparisons(classification: Mapping[str, Any]) -> dict[str, Any]:
    """Remove previously appended synthetic sidecar comparison rows before recomputing them."""

    cleaned = json.loads(json.dumps(classification))
    rows = []
    stale_architectures = {
        "hybrid_combined_vcs_sidecar_v1",
        "hybrid_integrated_combined_sidecar_v1",
        "hybrid_integrated_pipelined_sidecar_v2",
        "hybrid_integrated_streaming_pipeline_sidecar_v3",
    }
    for row in cleaned.get("architecture_comparisons", []):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("architecture_id") or "") in stale_architectures:
            continue
        rows.append(row)
    cleaned["architecture_comparisons"] = rows
    if rows:
        best = max(rows, key=lambda item: float(item.get("speedup_vs_gpu_mean") or 0.0))
        cleaned["best_architecture_id"] = best.get("architecture_id")
        cleaned["best_speedup_vs_gpu_mean"] = best.get("speedup_vs_gpu_mean")
    else:
        cleaned.pop("best_architecture_id", None)
        cleaned.pop("best_speedup_vs_gpu_mean", None)
    return cleaned


def _annotate_best_vivado_implemented_comparison(classification: Mapping[str, Any]) -> dict[str, Any]:
    annotated = json.loads(json.dumps(classification))
    rows = [
        row
        for row in annotated.get("architecture_comparisons", [])
        if isinstance(row, Mapping)
        and row.get("architecture_id")
        in {
            "hybrid_integrated_combined_sidecar_v1",
            "hybrid_integrated_pipelined_sidecar_v2",
            "hybrid_integrated_streaming_pipeline_sidecar_v3",
        }
        and row.get("latency_source") == "integrated_vcs_rtl"
    ]
    if rows:
        best = max(rows, key=lambda item: float(item.get("speedup_vs_gpu_mean") or 0.0))
        annotated["best_vivado_implemented_architecture_id"] = best.get("architecture_id")
        annotated["best_vivado_implemented_speedup_vs_gpu_mean"] = best.get("speedup_vs_gpu_mean")
    return annotated


def _fetch_remote_file(remote_path: str, local_path: Path, *, timeout_seconds: int = 60) -> bool:
    result = subprocess.run(
        ["ssh", REMOTE_ALIAS, f"cat {shlex.quote(remote_path)} 2>/dev/null"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
    return bool(result.stdout)


def run_integrated_vivado_impl(
    *,
    out_dir: Path,
    fpga_part: str,
    clock_period_ns: float,
    timeout_seconds: int,
    architecture_id: str = "hybrid_integrated_combined_sidecar_v1",
) -> dict[str, Any]:
    """Run remote Vivado synth/place/route for the integrated sidecar."""

    if architecture_id == "hybrid_integrated_streaming_pipeline_sidecar_v3":
        project = materialize_integrated_streaming_vivado_impl_project(
            build_real_hybrid_architecture_specs(),
            out_dir / "runs",
            fpga_part=fpga_part,
            clock_period_ns=clock_period_ns,
        )
        evidence_name = "real_hybrid_integrated_streaming_vivado_impl_evidence.json"
        boundary = "Integrated Vivado implementation evidence for the II=1 streaming RTL sidecar; not physical board measurement or full QE kernel integration."
    elif architecture_id == "hybrid_integrated_pipelined_sidecar_v2":
        project = materialize_integrated_pipelined_vivado_impl_project(
            build_real_hybrid_architecture_specs(),
            out_dir / "runs",
            fpga_part=fpga_part,
            clock_period_ns=clock_period_ns,
        )
        evidence_name = "real_hybrid_integrated_pipelined_vivado_impl_evidence.json"
        boundary = "Integrated Vivado implementation evidence for the pipelined RTL sidecar; not physical board measurement or full QE kernel integration."
    else:
        project = materialize_integrated_vivado_impl_project(
            build_real_hybrid_architecture_specs(),
            out_dir / "runs",
            fpga_part=fpga_part,
            clock_period_ns=clock_period_ns,
        )
        evidence_name = "real_hybrid_integrated_vivado_impl_evidence.json"
        boundary = "Integrated Vivado implementation evidence for the single RTL sidecar; not physical board measurement or full QE kernel integration."
    project_dir = Path(project["project_dir"])
    run_id = _safe_name(project["architecture_id"])
    remote_dir = f"/tmp/dse_real_hybrid_vivado_impl_{run_id}_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
    stdout_path = project_dir / "vivado.stdout.log"
    stderr_path = project_dir / "vivado.stderr.log"
    utilization_path = project_dir / "vivado_utilization.rpt"
    timing_path = project_dir / "vivado_timing_summary.rpt"
    start_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tar_cmd = f"mkdir -p {shlex.quote(remote_dir)} && tar -xzf - -C {shlex.quote(remote_dir)}"
    stage = subprocess.run(
        f"tar -czf - -C {shlex.quote(str(project_dir))} . | ssh {REMOTE_ALIAS} {shlex.quote(tar_cmd)}",
        shell=True,
        check=False,
        capture_output=True,
        text=False,
        timeout=120,
    )
    if stage.returncode != 0:
        stdout_path.write_bytes(stage.stdout or b"")
        stderr_path.write_bytes(stage.stderr or b"")
        return {
            "schema_version": SCHEMA_VERSION,
            "architecture_id": project.get("architecture_id"),
            "status": "failed",
            "reason": "remote_stage_failed",
            "returncode": stage.returncode,
            "vivado_impl_attempted": False,
            "vivado_impl_passed": False,
            "vivado_impl_project": project,
            "start_timestamp": start_timestamp,
            "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "blockers": ["remote_stage_failed"],
        }

    remote_cmd = (
        f"source ~/.bashrc; export LC_ALL=C LANG=C; cd {shlex.quote(remote_dir)} && "
        f"{shlex.quote(REMOTE_VIVADO)} -mode batch -source vivado_impl.tcl"
    )
    result = subprocess.run(
        ["ssh", REMOTE_ALIAS, remote_cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
    stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
    utilization_available = _fetch_remote_file(f"{remote_dir}/vivado_utilization.rpt", utilization_path)
    timing_available = _fetch_remote_file(f"{remote_dir}/vivado_timing_summary.rpt", timing_path)
    utilization_text = utilization_path.read_text(encoding="utf-8", errors="replace") if utilization_available else ""
    timing_text = timing_path.read_text(encoding="utf-8", errors="replace") if timing_available else ""
    utilization = parse_vivado_impl_utilization_report(utilization_text)
    timing = parse_vivado_impl_timing_summary_report(timing_text)
    vivado_passed = (
        result.returncode == 0
        and utilization.get("resource_feasible") is True
        and timing.get("timing_met") is True
        and utilization.get("status") == "parsed"
        and timing.get("status") == "parsed"
    )
    command = f"ssh {REMOTE_ALIAS} {remote_cmd}"
    blockers = list(utilization.get("blockers") or []) + list(timing.get("blockers") or [])
    if result.returncode != 0:
        blockers.append("vivado_impl_returned_nonzero")
    if not utilization_available:
        blockers.append("vivado_impl_utilization_report_unavailable")
    if not timing_available:
        blockers.append("vivado_impl_timing_report_unavailable")
    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "architecture_id": project.get("architecture_id"),
        "kernel_name": project.get("kernel_name"),
        "status": "executed" if utilization_available or timing_available else "failed",
        "reason": None if vivado_passed else "vivado_impl_failed_or_unmet_timing_resource",
        "tool": "vivado",
        "tool_path": f"ssh://{REMOTE_ALIAS}{REMOTE_VIVADO}",
        "fpga_part": fpga_part,
        "clock_period_ns": clock_period_ns,
        "implemented_clock_ns": clock_period_ns if vivado_passed else None,
        "implemented_clock_source": "vivado_post_route_timing_met" if vivado_passed else None,
        "command": command,
        "returncode": result.returncode,
        "vivado_impl_command": command,
        "vivado_impl_returncode": result.returncode,
        "vivado_impl_attempted": True,
        "vivado_impl_passed": vivado_passed,
        "vivado_impl_utilization_report_available": utilization_available,
        "vivado_impl_timing_report_available": timing_available,
        "vivado_impl_utilization_parsed": utilization,
        "vivado_impl_timing_parsed": timing,
        "vivado_impl_project": project,
        "start_timestamp": start_timestamp,
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vivado_stdout_log_path": str(stdout_path),
        "vivado_stderr_log_path": str(stderr_path),
        "vivado_utilization_report_path": str(utilization_path),
        "vivado_timing_summary_report_path": str(timing_path),
        "vivado_stdout_log_hash": _sha256_file(stdout_path),
        "vivado_stderr_log_hash": _sha256_file(stderr_path),
        "vivado_utilization_report_hash": _sha256_file(utilization_path),
        "vivado_timing_summary_report_hash": _sha256_file(timing_path),
        "blockers": sorted(set(str(item) for item in blockers if item)),
        "claim_boundary": boundary,
    }
    evidence_path = project_dir / evidence_name
    _write_json(evidence_path, row)
    row["vivado_impl_evidence_json_path"] = str(evidence_path)
    row["vivado_impl_evidence_json_hash"] = _sha256_file(evidence_path)
    _write_json(evidence_path, row)
    row["vivado_impl_evidence_json_hash"] = _sha256_file(evidence_path)
    return row


def run_campaign(args: argparse.Namespace) -> dict[str, Any]:
    out_dir: Path = args.out
    summary_path = args.summary or out_dir / "real_hybrid_hls_summary.json"
    summary = _normalize_integrated_vivado_result_keys(_load_summary(summary_path))
    architecture_id = getattr(args, "architecture_id", "hybrid_integrated_combined_sidecar_v1")
    result = run_integrated_vivado_impl(
        out_dir=out_dir,
        fpga_part=args.fpga_part,
        clock_period_ns=args.clock_period_ns,
        timeout_seconds=args.timeout_seconds,
        architecture_id=architecture_id,
    )
    merged = merge_integrated_vivado_impl_evidence_into_summary(summary, result)
    merged[INTEGRATED_VIVADO_RESULT_KEYS.get(architecture_id, "integrated_vivado_impl_result")] = result

    baseline_path = Path(str(merged.get("gpu_baseline_path") or "artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json"))
    baseline = _load_gpu_baseline(baseline_path)
    if baseline is not None and isinstance(merged.get("classification"), Mapping):
        rows = [row for row in merged.get("evidence_rows", []) if isinstance(row, Mapping)]
        gpu_runs_root = _gpu_runs_root_from_summary(merged, baseline_path)
        classification = _drop_stale_synthetic_sidecar_comparisons(merged["classification"])
        combined_vcs_sidecar_accounting = build_combined_vcs_sidecar_accounting(baseline, gpu_runs_root, rows)
        classification = merge_combined_vcs_sidecar_comparisons(baseline, classification, combined_vcs_sidecar_accounting)
        if architecture_id == "hybrid_integrated_streaming_pipeline_sidecar_v3":
            integrated_key = "integrated_streaming_vcs_sidecar_result"
        elif architecture_id == "hybrid_integrated_pipelined_sidecar_v2":
            integrated_key = "integrated_pipelined_vcs_sidecar_result"
        else:
            integrated_key = "integrated_vcs_sidecar_result"
        integrated_result = merged.get(integrated_key)
        if isinstance(integrated_result, dict) and result.get("vivado_impl_passed") is True and isinstance(result.get("implemented_clock_ns"), (int, float)):
            integrated_result["implemented_clock_ns"] = result["implemented_clock_ns"]
            integrated_result["implemented_clock_source"] = result.get("implemented_clock_source") or "vivado_post_route_timing_met"
            merged[integrated_key] = integrated_result
        integrated_vcs_sidecar_accounting = []
        for key in INTEGRATED_VCS_RESULT_KEYS:
            integrated_candidate = merged.get(key)
            integrated_vcs_sidecar_accounting.extend(build_integrated_vcs_sidecar_accounting(baseline, gpu_runs_root, integrated_candidate))
        classification = merge_integrated_vcs_sidecar_comparisons(baseline, classification, integrated_vcs_sidecar_accounting)
        classification = merge_integrated_vivado_impl_evidence_into_summary({"classification": classification, "evidence_rows": rows}, result)["classification"]
        classification = _annotate_best_vivado_implemented_comparison(classification)
        merged["combined_vcs_sidecar_accounting"] = combined_vcs_sidecar_accounting
        merged["integrated_vcs_sidecar_accounting"] = integrated_vcs_sidecar_accounting
        merged["classification"] = classification
        claim_closure_path = Path(str(merged.get("claim_closure_path") or out_dir / "real_hybrid_claim_closure.json"))
        claim_closure = build_real_hybrid_claim_closure(baseline, rows, classification)
        _write_json(claim_closure_path, claim_closure)
        merged["claim_closure_path"] = str(claim_closure_path)

    _write_json(summary_path, merged)
    (out_dir / "real_hybrid_hls_report.md").write_text(render_real_hybrid_hls_report(merged), encoding="utf-8")
    return {"status": "passed" if result.get("vivado_impl_passed") else "failed", "summary": str(summary_path), "vivado_impl_result": result}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls"))
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--architecture-id", default="hybrid_integrated_combined_sidecar_v1")
    parser.add_argument("--fpga-part", default=DEFAULT_FPGA_PART)
    parser.add_argument("--clock-period-ns", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = run_campaign(args)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
