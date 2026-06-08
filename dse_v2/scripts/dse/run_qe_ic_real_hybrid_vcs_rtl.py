#!/usr/bin/env python3
"""Run non-HLS VCS RTL evidence for real hybrid QE-IC miniapp candidates."""

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
    build_real_hybrid_claim_closure,
    build_real_hybrid_architecture_specs,
    materialize_vcs_rtl_project,
    merge_vcs_rtl_evidence_into_summary,
    parse_vcs_rtl_run_log,
    render_real_hybrid_hls_report,
)

REMOTE_ALIAS = "ic-eda"
SCHEMA_VERSION = "dse.qe_ic.real_hybrid_vcs_rtl_evidence.v1"


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


def _load_gpu_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def run_vcs_rtl_for_architecture(
    spec: Mapping[str, Any],
    *,
    out_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_id = _safe_name(spec["architecture_id"])
    project = materialize_vcs_rtl_project(spec, out_dir / "runs")
    project_dir = Path(project["project_dir"])
    remote_dir = f"/tmp/dse_real_hybrid_vcs_rtl_{run_id}_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
    stdout_path = project_dir / "vcs.stdout.log"
    stderr_path = project_dir / "vcs.stderr.log"
    compile_log_path = project_dir / "vcs_compile.log"
    run_log_path = project_dir / "vcs_run.log"
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
            "architecture_id": spec.get("architecture_id"),
            "status": "failed",
            "reason": "remote_stage_failed",
            "returncode": stage.returncode,
            "vcs_attempted": False,
            "vcs_passed": False,
            "vcs_rtl_project": project,
            "start_timestamp": start_timestamp,
            "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    rtl_name = Path(str(project["rtl_sv"])).name
    tb_name = Path(str(project["tb_sv"])).name
    remote_cmd = (
        f"source ~/.bashrc; export LC_ALL=C LANG=C; cd {shlex.quote(remote_dir)} && "
        f"vcs -full64 -sverilog {shlex.quote(rtl_name)} {shlex.quote(tb_name)} -o simv > vcs_compile.log 2>&1 "
        f"&& ./simv > vcs_run.log 2>&1"
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
    compile_available = _fetch_remote_file(f"{remote_dir}/vcs_compile.log", compile_log_path)
    run_available = _fetch_remote_file(f"{remote_dir}/vcs_run.log", run_log_path)
    run_text = run_log_path.read_text(encoding="utf-8", errors="replace") if run_available else ""
    parsed = parse_vcs_rtl_run_log(run_text)
    vcs_passed = parsed.get("status") == "parsed" and parsed.get("rtl_status") == "Pass" and result.returncode == 0
    command = f"ssh {REMOTE_ALIAS} {remote_cmd}"
    claim_boundary = (
        f"Standalone handwritten RTL/VCS miniapp evidence for {spec.get('kernel_name')}; "
        "not full-QE integration, board measurement, or final FPGA superiority evidence."
    )
    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "architecture_id": spec.get("architecture_id"),
        "kernel_name": spec.get("kernel_name"),
        "status": "executed" if compile_available or run_available else "failed",
        "reason": None if vcs_passed else "vcs_returned_nonzero_or_rtl_test_failed",
        "tool": "vcs",
        "command": command,
        "returncode": result.returncode,
        "vcs_command": command,
        "vcs_returncode": result.returncode,
        "vcs_attempted": True,
        "vcs_passed": vcs_passed,
        "vcs_parsed": parsed,
        "vcs_rtl_project": project,
        "start_timestamp": start_timestamp,
        "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vcs_stdout_log_path": str(stdout_path),
        "vcs_stderr_log_path": str(stderr_path),
        "vcs_compile_log_path": str(compile_log_path),
        "vcs_run_log_path": str(run_log_path),
        "vcs_stdout_log_hash": _sha256_file(stdout_path),
        "vcs_stderr_log_hash": _sha256_file(stderr_path),
        "vcs_compile_log_hash": _sha256_file(compile_log_path),
        "vcs_run_log_hash": _sha256_file(run_log_path),
        "blockers": [] if vcs_passed else list(parsed.get("blockers") or ["vcs_rtl_sim_failed"]),
        "claim_boundary": claim_boundary,
    }
    _write_json(project_dir / "real_hybrid_vcs_rtl_evidence.json", row)
    row["vcs_evidence_json_path"] = str(project_dir / "real_hybrid_vcs_rtl_evidence.json")
    row["vcs_evidence_json_hash"] = _sha256_file(project_dir / "real_hybrid_vcs_rtl_evidence.json")
    return row


def run_campaign(args: argparse.Namespace) -> dict[str, Any]:
    out_dir: Path = args.out
    summary_path = args.summary or out_dir / "real_hybrid_hls_summary.json"
    summary = _load_summary(summary_path)
    specs = {str(spec["architecture_id"]): spec for spec in build_real_hybrid_architecture_specs()}
    if args.architecture_id not in specs:
        raise ValueError(f"unknown architecture id: {args.architecture_id}")
    result = run_vcs_rtl_for_architecture(specs[args.architecture_id], out_dir=out_dir, timeout_seconds=args.timeout_seconds)
    merged = merge_vcs_rtl_evidence_into_summary(summary, result)
    for row in merged.get("evidence_rows", []):
        if not isinstance(row, dict) or str(row.get("architecture_id")) != args.architecture_id:
            continue
        row_path_value = row.get("evidence_json_path")
        if row_path_value:
            row_path = Path(str(row_path_value))
            _write_json(row_path, row)
            row["evidence_json_hash"] = _sha256_file(row_path)
        break
    _write_json(summary_path, merged)
    baseline = _load_gpu_baseline(Path("artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json"))
    if baseline is not None and isinstance(merged.get("classification"), Mapping):
        claim_closure_path = Path(str(merged.get("claim_closure_path") or out_dir / "real_hybrid_claim_closure.json"))
        claim_closure = build_real_hybrid_claim_closure(baseline, [row for row in merged.get("evidence_rows", []) if isinstance(row, Mapping)], merged["classification"])
        _write_json(claim_closure_path, claim_closure)
        merged["claim_closure_path"] = str(claim_closure_path)
        _write_json(summary_path, merged)
    (out_dir / "real_hybrid_hls_report.md").write_text(render_real_hybrid_hls_report(merged), encoding="utf-8")
    return {"status": "passed" if result.get("vcs_passed") else "failed", "summary": str(summary_path), "vcs_result": result}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/qe_ic_real_hybrid_hls"))
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--architecture-id", default="hybrid_hpsi_local_potential_v1")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = run_campaign(args)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
