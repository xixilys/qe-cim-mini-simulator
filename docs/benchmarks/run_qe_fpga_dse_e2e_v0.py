#!/usr/bin/env python3
"""Run the QE FPGA DSE JSON-v0 frontend/backend closed loop.

This orchestrator is intentionally claim-conservative: it runs frontend DSE,
executes the backend SystemC timed-functional proxy for one executable Stage-B0
candidate, ingests that report back into frontend EvidenceIR, and optionally
adds gem5 smoke-only evidence. It does not claim QE numerical equivalence,
cycle accuracy, RTL/HLS/board evidence, or physical FPGA performance.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_DESIGN_SPACE = REPO_ROOT / "docs/benchmarks/qe_architecture_family_design_space_spec_v0.json"
DEFAULT_WORKLOAD = REPO_ROOT / "docs/benchmarks/testdata/unified_dse/minimal_workload.json"
DEFAULT_B3_REQUEST = REPO_ROOT / "docs/benchmarks/testdata/unified_dse/backend_execution_request_b3_smoke.json"
DEFAULT_LEGACY_B3_REPORT = REPO_ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"


class E2EError(RuntimeError):
    pass


def _json_load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise E2EError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _run(cmd: Sequence[str], *, cwd: Path, log_dir: Path, name: str, timeout_s: int | None = None) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / f"{name}.stdout.log"
    stderr = log_dir / f"{name}.stderr.log"
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        completed = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            env=env,
            stdout=out,
            stderr=err,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    result = {
        "name": name,
        "cmd": list(cmd),
        "returncode": completed.returncode,
        "stdout_log": str(stdout),
        "stderr_log": str(stderr),
    }
    if completed.returncode != 0:
        raise E2EError(
            f"command failed ({name}, rc={completed.returncode}); "
            f"stdout={stdout} stderr={stderr}"
        )
    return result


def _first_stage_b0_request(frontend_dir: Path) -> Path:
    manifest_path = frontend_dir / "stage_b0_descriptor_manifest_v0.json"
    manifest = _json_load(manifest_path)
    descriptors = manifest.get("descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise E2EError(f"no Stage-B0 descriptors in {manifest_path}")
    for item in descriptors:
        if isinstance(item, dict) and item.get("backend_execution_request_ref"):
            request = frontend_dir / str(item["backend_execution_request_ref"])
            if request.exists():
                return request
    raise E2EError(f"Stage-B0 manifest has no usable backend request: {manifest_path}")


def _metric(report: Mapping[str, Any], key: str) -> Any:
    metrics = report.get("metrics")
    if isinstance(metrics, Mapping):
        return metrics.get(key)
    return None


def _report_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": report.get("candidate_id"),
        "execution_status": report.get("execution_status"),
        "fidelity": report.get("fidelity"),
        "claim_ceiling": report.get("claim_ceiling"),
        "backend_class": report.get("backend_class"),
        "source_kind": report.get("source_kind"),
        "time_to_completion_s": _metric(report, "time_to_completion_s"),
        "device_busy_s": _metric(report, "device_busy_s"),
        "host_wait_s": _metric(report, "host_wait_s"),
        "dma_read_bytes": _metric(report, "dma_read_bytes"),
        "dma_write_bytes": _metric(report, "dma_write_bytes"),
        "bytes_moved_to_convergence": _metric(report, "bytes_moved_to_convergence"),
        "resident_reuse_ratio": _metric(report, "resident_reuse_ratio"),
        "fallback_ratio": _metric(report, "fallback_ratio"),
        "spill_ratio": _metric(report, "spill_ratio"),
        "cycle_proxy": _metric(report, "cycle_proxy"),
        "systemc_converged": _metric(report, "systemc_converged"),
        "non_claims": list(report.get("non_claims", [])) if isinstance(report.get("non_claims"), list) else [],
    }


def run_e2e(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if output_dir.exists() and args.clean:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir / "logs"
    frontend_dir = output_dir / "frontend_dse"
    backend_dir = output_dir / "backend_reports"
    ingest_dir = output_dir / "frontend_ingest_systemc"
    gem5_ingest_dir = output_dir / "frontend_ingest_gem5_smoke"
    commands: list[dict[str, Any]] = []

    frontend_cmd = [
        sys.executable,
        "docs/benchmarks/run_unified_dse_v0.py",
        "--design-space-spec",
        str(Path(args.design_space_spec)),
        "--workload",
        str(Path(args.workload)),
        "--output-dir",
        str(frontend_dir),
        "--source-kind",
        args.source_kind,
        "--search-backend",
        args.search_backend,
        "--shortlist-policy",
        args.shortlist_policy,
        "--shortlist-size",
        str(args.shortlist_size),
        "--emit-multi-fidelity-plan",
        "--emit-stage-b0-descriptors",
        "--emit-release-bundle",
        "--dry-run",
        "--max-design-points",
        str(args.max_design_points),
    ]
    commands.append(_run(frontend_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_dse", timeout_s=args.timeout_s))

    request_path = _first_stage_b0_request(frontend_dir)
    systemc_report = backend_dir / "systemc_timed_functional_report.json"
    backend_cmd = [
        sys.executable,
        "backend/runners/run_backend_execution_v0.py",
        "--request",
        str(request_path),
        "--output",
        str(systemc_report),
        "--mode",
        "systemc_timed_functional",
        "--allow-execute",
        "--timeout-s",
        str(args.timeout_s),
    ]
    commands.append(_run(backend_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="backend_systemc", timeout_s=args.timeout_s + 5))

    ingest_cmd = [
        sys.executable,
        "docs/benchmarks/qedse_frontend.py",
        "frontend",
        "ingest-feedback",
        "--backend-report",
        str(systemc_report),
        "--output-dir",
        str(ingest_dir),
    ]
    commands.append(_run(ingest_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_ingest_systemc", timeout_s=args.timeout_s))

    systemc_payload = _json_load(systemc_report)
    gem5_report: Path | None = None
    gem5_payload: dict[str, Any] | None = None
    gem5_mode = "skipped"
    if args.include_gem5_smoke:
        gem5_report = backend_dir / "gem5_systemc_smoke_report.json"
        gem5_cmd = [
            sys.executable,
            "backend/runners/run_backend_execution_v0.py",
            "--request",
            str(Path(args.gem5_smoke_request)),
            "--output",
            str(gem5_report),
            "--mode",
            "gem5_systemc_smoke",
        ]
        if args.require_real_gem5_smoke:
            gem5_cmd.extend(["--allow-execute", "--timeout-s", str(args.gem5_timeout_s)])
            gem5_mode = "real_gem5_requested"
        else:
            gem5_cmd.extend(["--legacy-b3-report", str(Path(args.legacy_b3_report))])
            gem5_mode = "legacy_b3_conversion"
        commands.append(_run(gem5_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="backend_gem5_smoke", timeout_s=args.gem5_timeout_s + 5))
        gem5_payload = _json_load(gem5_report)
        gem5_ingest_cmd = [
            sys.executable,
            "docs/benchmarks/qedse_frontend.py",
            "frontend",
            "ingest-feedback",
            "--backend-report",
            str(gem5_report),
            "--output-dir",
            str(gem5_ingest_dir),
        ]
        commands.append(_run(gem5_ingest_cmd, cwd=REPO_ROOT, log_dir=log_dir, name="frontend_ingest_gem5_smoke", timeout_s=args.timeout_s))

    summary = {
        "schema_version": "qe_fpga_dse_performance_summary_v0",
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "claim_boundary": "proxy_and_smoke_only_no_qe_equivalence_no_rtl_hls_board_claim",
        "selected_request_ref": str(request_path),
        "systemc_timed_functional": _report_summary(systemc_payload),
        "gem5_smoke": _report_summary(gem5_payload) if gem5_payload is not None else None,
        "known_metric_limits": [
            "systemc_timed_functional_proxy_only",
            "gem5_systemc_smoke_only_when_present",
            "cycle_proxy/device_busy may be absent or proxy-grade depending on backend report",
        ],
    }
    summary_path = output_dir / "qe_fpga_dse_performance_summary_v0.json"
    _write_json(summary_path, summary)

    manifest = {
        "schema_version": "qe_fpga_dse_e2e_manifest_v0",
        "generated_at_utc": summary["generated_at_utc"],
        "repo_root": str(REPO_ROOT),
        "frontend_dse_dir": str(frontend_dir),
        "selected_backend_request": str(request_path),
        "systemc_backend_report": str(systemc_report),
        "systemc_frontend_evidence_ir": str(ingest_dir / "evidence_ir_collection_v0.json"),
        "gem5_smoke_mode": gem5_mode,
        "gem5_smoke_report": str(gem5_report) if gem5_report else None,
        "gem5_frontend_evidence_ir": str(gem5_ingest_dir / "evidence_ir_collection_v0.json") if gem5_report else None,
        "performance_summary": str(summary_path),
        "commands": commands,
        "non_claims": [
            "not_qe_equivalent_scf_claim",
            "not_cycle_accurate_claim",
            "not_rtl_hls_board_or_asic_implementation_claim",
            "not_physical_fpga_performance_measurement",
        ],
    }
    manifest_path = output_dir / "qe_fpga_dse_e2e_manifest_v0.json"
    _write_json(manifest_path, manifest)
    return {"manifest": manifest_path, "summary": summary_path, "manifest_payload": manifest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run QE FPGA DSE frontend/backend JSON-v0 E2E flow")
    parser.add_argument("--design-space-spec", default=str(DEFAULT_DESIGN_SPACE))
    parser.add_argument("--workload", default=str(DEFAULT_WORKLOAD))
    parser.add_argument("--output-dir", default="tmp/qe_fpga_dse_e2e_v0")
    parser.add_argument("--max-design-points", type=int, default=8)
    parser.add_argument("--source-kind", default="fast_model_screening")
    parser.add_argument("--search-backend", default="stratified_cartesian")
    parser.add_argument("--shortlist-policy", default="top_fast_uncertain_diverse")
    parser.add_argument("--shortlist-size", type=int, default=3)
    parser.add_argument("--timeout-s", type=int, default=10)
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.add_argument("--include-gem5-smoke", action="store_true")
    parser.add_argument("--require-real-gem5-smoke", action="store_true")
    parser.add_argument("--gem5-timeout-s", type=int, default=60)
    parser.add_argument("--gem5-smoke-request", default=str(DEFAULT_B3_REQUEST))
    parser.add_argument("--legacy-b3-report", default=str(DEFAULT_LEGACY_B3_REPORT))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.require_real_gem5_smoke:
        args.include_gem5_smoke = True
    try:
        result = run_e2e(args)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"manifest: {result['manifest']}")
    print(f"summary: {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
