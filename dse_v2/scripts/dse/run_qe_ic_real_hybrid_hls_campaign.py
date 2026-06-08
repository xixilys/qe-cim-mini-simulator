#!/usr/bin/env python3
"""Run real non-stub hybrid HLS evidence campaign for QE-IC candidates."""

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
    build_real_hybrid_architecture_specs,
    build_trace_replay_workflow_accounting,
    classify_real_hybrid_vs_gpu,
    materialize_hls_project,
    parse_vivado_hls_cosim_report,
    parse_vivado_hls_csynth_report,
)

REMOTE_ALIAS = "ic-eda"
REMOTE_VIVADO_HLS = "/home/Xilinx/Vivado/2019.1/bin/vivado_hls"
SCHEMA_VERSION = "dse.qe_ic.real_hybrid_hls_campaign.v1"


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


def _load_gpu_baseline(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"GPU baseline is not a JSON object: {path}")
    return payload


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


def run_one_architecture(
    spec: Mapping[str, Any],
    *,
    out_dir: Path,
    fpga_part: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_id = _safe_name(spec["architecture_id"])
    local_dir = out_dir / "runs" / run_id
    project = materialize_hls_project(spec, local_dir, fpga_part=fpga_part)
    project_dir = Path(project["project_dir"])
    remote_dir = f"/tmp/dse_real_hybrid_hls_{run_id}_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
    stdout_path = project_dir / "vivado_hls.stdout.log"
    stderr_path = project_dir / "vivado_hls.stderr.log"
    csynth_path = project_dir / "csynth.rpt"
    cosim_path = project_dir / "cosim.rpt"
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
            "architecture_id": spec.get("architecture_id"),
            "status": "failed",
            "reason": "remote_stage_failed",
            "returncode": stage.returncode,
            "implementation_maturity": spec.get("implementation_maturity"),
            "stdout_log_path": str(stdout_path),
            "stderr_log_path": str(stderr_path),
            "start_timestamp": start_timestamp,
            "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    remote_cmd = f"export LC_ALL=C LANG=C; cd {shlex.quote(remote_dir)} && {shlex.quote(REMOTE_VIVADO_HLS)} -f run_hls.tcl"
    result = subprocess.run(
        ["ssh", REMOTE_ALIAS, remote_cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
    stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
    kernel_name = str(spec["kernel_name"])
    report_base = f"{remote_dir}/real_hybrid_hls/sol1"
    csynth_available = _fetch_remote_file(f"{report_base}/syn/report/{kernel_name}_csynth.rpt", csynth_path)
    cosim_available = _fetch_remote_file(f"{report_base}/sim/report/{kernel_name}_cosim.rpt", cosim_path)
    csynth_text = csynth_path.read_text(encoding="utf-8", errors="replace") if csynth_available else ""
    parsed = (
        parse_vivado_hls_csynth_report(csynth_text, fallback_trip_count=int(spec.get("golden_vector_length") or 0) or None)
        if csynth_text
        else {"status": "missing", "blockers": ["csynth_report_missing"]}
    )
    cosim_text = cosim_path.read_text(encoding="utf-8", errors="replace") if cosim_available else ""
    cosim_parsed = parse_vivado_hls_cosim_report(cosim_text)
    stdout = result.stdout or ""
    cosim_passed = cosim_parsed.get("status") == "parsed" and cosim_parsed.get("rtl_status") == "Pass"
    row = {
        "architecture_id": spec.get("architecture_id"),
        "kernel_name": kernel_name,
        "target_type": spec.get("target_type"),
        "motif_id": spec.get("motif_id"),
        "implementation_maturity": spec.get("implementation_maturity"),
        "evidence_level": spec.get("evidence_level"),
        "status": "executed" if result.returncode == 0 or csynth_available else "failed",
        "reason": None if result.returncode == 0 else "vivado_hls_returned_nonzero_or_cosim_failed",
        "tool": "vivado_hls",
        "tool_path": f"ssh://{REMOTE_ALIAS}{REMOTE_VIVADO_HLS}",
        "fpga_part": fpga_part,
        "returncode": result.returncode,
        "command": f"ssh {REMOTE_ALIAS} {remote_cmd}",
        "csim_passed": "DSE_REAL_HLS_PASS" in stdout,
        "csynth_report_available": csynth_available,
        "csynth_parsed": parsed,
        "cosim_attempted": "cosim_design" in stdout or "cosim" in stdout.lower(),
        "cosim_report_available": cosim_available,
        "cosim_passed": cosim_passed,
        "cosim_parsed": cosim_parsed,
        "vcs_passed": False,
        "vcs_attempted": False,
        "blockers": [],
        "project": project,
        "start_timestamp": start_timestamp,
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "csynth_report_path": str(csynth_path),
        "cosim_report_path": str(cosim_path),
        "stdout_hash": _sha256_file(stdout_path),
        "stderr_hash": _sha256_file(stderr_path),
        "csynth_report_hash": _sha256_file(csynth_path),
        "cosim_report_hash": _sha256_file(cosim_path),
        "transfer_overhead_seconds": 0.00005,
        "workflow_overhead_seconds": None,
        "workflow_accounting": {
            "status": "not_available_microkernel_only",
            "reason": "standalone HLS motif is not yet coupled to QE full-SCF host/device schedule",
        },
    }
    if not row["csim_passed"]:
        row["blockers"].append("golden_csim_not_passed")
    if not csynth_available:
        row["blockers"].append("csynth_report_missing")
    if not cosim_passed:
        row["blockers"].append("cosim_not_passed_or_unavailable")
    row_path = project_dir / "real_hybrid_hls_evidence.json"
    _write_json(row_path, row)
    row["evidence_json_path"] = str(row_path)
    row["evidence_json_hash"] = _sha256_file(row_path)
    return row


def run_campaign(args: argparse.Namespace) -> dict[str, Any]:
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = _load_gpu_baseline(args.gpu_baseline)
    specs = build_real_hybrid_architecture_specs()[: args.max_architectures]
    rows = [
        run_one_architecture(spec, out_dir=out_dir, fpga_part=args.fpga_part, timeout_seconds=args.timeout_seconds)
        for spec in specs
    ]
    gpu_runs_root = args.gpu_runs_root or args.gpu_baseline.parent / "runs"
    for row in rows:
        row["workflow_accounting"] = build_trace_replay_workflow_accounting(baseline, gpu_runs_root, row)
        row_path_value = row.get("evidence_json_path")
        if row_path_value:
            row_path = Path(str(row_path_value))
            _write_json(row_path, row)
            row["evidence_json_hash"] = _sha256_file(row_path)
    classification = classify_real_hybrid_vs_gpu(baseline, rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gpu_baseline_path": str(args.gpu_baseline),
        "architecture_specs": specs,
        "evidence_rows": rows,
        "classification": classification,
        "claim_boundary": "Non-stub HLS kernels with real Vivado-HLS attempts; final hardware superiority still requires full QE integration and board/implementation closure.",
    }
    _write_json(out_dir / "real_hybrid_hls_summary.json", summary)
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-baseline", type=Path, default=Path("artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls"))
    parser.add_argument("--max-architectures", type=int, default=3)
    parser.add_argument("--fpga-part", default=DEFAULT_FPGA_PART)
    parser.add_argument("--gpu-runs-root", type=Path, default=None, help="Root containing <case_id>/gpu_only_baseline/run_*.stdout.log timer traces")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = run_campaign(args)
    print(json.dumps({
        "status": "passed",
        "summary": str(args.out / "real_hybrid_hls_summary.json"),
        "preliminary_label": summary["classification"].get("preliminary_label"),
        "architectures": len(summary["evidence_rows"]),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
