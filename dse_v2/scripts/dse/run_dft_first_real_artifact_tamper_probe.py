#!/usr/bin/env python3
"""Probe that DFT-first audits fail when copied real Step4 artifacts are tampered.

The prompt requires real, non-smoke gem5 evidence and rejects completion by
claim alone.  This probe copies an existing DFT-first run, mutates raw Step4
evidence inside the copy, reruns the normal end-to-end audit, and records
whether the expected checks fail.  It intentionally relies on the production
auditor rather than duplicating proof logic here.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.audit_dft_first_end_to_end_run import audit_run  # noqa: E402


TAMPER_PROBE_SCHEMA = "dse.dft_first.real_artifact_tamper_probe.v3"

STATS_ZERO_EXPECTED = {
    "step4_artifact_manifest_hashes",
    "step4_gem5_stats_semantics_present",
}
LOG_MARKER_EXPECTED = {
    "step4_artifact_manifest_hashes",
    "step4_proof_recomputed_from_raw_artifacts",
    "step4_raw_gem5_evidence_consistent",
}


def _date_text() -> str:
    return subprocess.check_output(["date", "+%Y-%m-%d %H:%M:%S %Z (%z)"], text=True).strip()


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selected_architecture_id(run_dir: Path) -> str:
    summary = _load_json(run_dir / "dft_end_to_end_summary.json")
    step4 = summary.get("step4_gem5") if isinstance(summary.get("step4_gem5"), Mapping) else {}
    architecture_id = step4.get("architecture_id")
    if not architecture_id:
        best = summary.get("best_architecture") if isinstance(summary.get("best_architecture"), Mapping) else {}
        architecture_id = best.get("architecture_id")
    if not architecture_id:
        raise ValueError(f"cannot resolve selected Step4 architecture in {run_dir}")
    return str(architecture_id)


def _copy_run(source_run: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_run, destination, symlinks=True)


def _step4_dir(run_dir: Path, architecture_id: str) -> Path:
    return run_dir / "step4_gem5" / architecture_id


def _tamper_stats_zero(run_dir: Path, architecture_id: str) -> None:
    stats = _step4_dir(run_dir, architecture_id) / "stats.txt"
    if not stats.exists():
        raise FileNotFoundError(stats)
    with stats.open("a", encoding="utf-8") as handle:
        handle.write("\n# tamper probe overrides required scalar counters\n")
        for metric in ("simTicks", "finalTick", "simInsts", "simOps", "system.cpu.numCycles"):
            handle.write(f"{metric} 0 # tampered by DFT-first artifact probe\n")


def _tamper_gem5_log_markers(run_dir: Path, architecture_id: str) -> None:
    log_path = _step4_dir(run_dir, architecture_id) / "gem5.log"
    if not log_path.exists():
        raise FileNotFoundError(log_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for marker in (
        "descriptor_read verified=true",
        "uarch_request_decode verified=true",
        "microarchitecture_execute verified=true",
        "completion_writeback verified=true",
    ):
        text = text.replace(marker, marker.replace("verified=true", "verified=false"))
    log_path.write_text(text, encoding="utf-8")


def _run_audit(case_dir: Path) -> Dict[str, Any]:
    audit = audit_run(case_dir)
    audit_path = case_dir / "dft_end_to_end_audit.json"
    _write_json(audit_path, audit)
    return {
        "audit_path": str(audit_path),
        "audit_status": audit.get("status"),
        "audit_failed_count": audit.get("failed_count"),
        "failed_check_ids": [
            str(check.get("check_id"))
            for check in audit.get("checks", []) or []
            if isinstance(check, Mapping) and check.get("passed") is False
        ],
        "returncode": 0 if audit.get("passed") else 2,
    }


def _case_result(
    *,
    source_run: Path,
    case_dir: Path,
    architecture_id: str,
    case_name: str,
    expected_failed_checks_subset: set[str],
    tamper_fn,
) -> Dict[str, Any]:
    _copy_run(source_run, case_dir)
    tamper_fn(case_dir, architecture_id)
    result = _run_audit(case_dir)
    failed_ids = set(result["failed_check_ids"])
    return {
        "case": case_name,
        "expected_failed_checks_subset": sorted(expected_failed_checks_subset),
        "passed_probe": result["audit_status"] == "failed" and expected_failed_checks_subset.issubset(failed_ids),
        "result": result,
    }


def run_real_artifact_tamper_probe(*, source_run: Path, out_dir: Path) -> Dict[str, Any]:
    architecture_id = _selected_architecture_id(source_run)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        _case_result(
            source_run=source_run,
            case_dir=out_dir / "stats_zero_tamper",
            architecture_id=architecture_id,
            case_name="stats_zero_tamper",
            expected_failed_checks_subset=STATS_ZERO_EXPECTED,
            tamper_fn=_tamper_stats_zero,
        ),
        _case_result(
            source_run=source_run,
            case_dir=out_dir / "gem5_log_marker_tamper_all_decode_markers",
            architecture_id=architecture_id,
            case_name="gem5_log_marker_tamper_all_decode_markers",
            expected_failed_checks_subset=LOG_MARKER_EXPECTED,
            tamper_fn=_tamper_gem5_log_markers,
        ),
    ]
    payload = {
        "schema_version": TAMPER_PROBE_SCHEMA,
        "checked_at_local": _date_text(),
        "source_run": str(source_run),
        "architecture_id": architecture_id,
        "fix_verified": "proof source_artifacts are rebased to audited copy before recompute",
        "probe_status": "passed" if all(case["passed_probe"] for case in cases) else "failed",
        "cases": cases,
    }
    _write_json(out_dir / "tamper_probe_result.json", payload)
    return payload


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = run_real_artifact_tamper_probe(source_run=args.source_run, out_dir=args.out)
    if not args.quiet:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("probe_status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
