#!/usr/bin/env python3
"""Run QE h_psi sidecar bridge rows from an accelerated-evidence requirements manifest.

The campaign runner is an orchestration helper only.  It never upgrades
boundary/component-model evidence into trusted L4 correctness: every row still
goes through ``run_qe_hpsi_sidecar_bridge.py --fail-on-trusted`` and remains
blocked unless a future runtime supplies real full-offload provenance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CAMPAIGN_SCHEMA = "dse.qe_hpsi_sidecar_bridge_campaign.v1"
BRIDGE = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_hpsi_sidecar_bridge.py"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_repo_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def _required_path(row: Mapping[str, Any], key: str) -> Path | None:
    required_outputs = row.get("required_outputs", {})
    if not isinstance(required_outputs, Mapping):
        return None
    return _resolve_repo_path(required_outputs.get(key))


def _row_out_dir(row: Mapping[str, Any]) -> Path:
    evidence_output = _resolve_repo_path(row.get("evidence_output"))
    if evidence_output is not None:
        return evidence_output.parent
    accelerated_stdout = _required_path(row, "accelerated_stdout")
    if accelerated_stdout is not None:
        return accelerated_stdout.parent
    return REPO_ROOT / "runs" / "dse" / "hpsi_sidecar_bridge_campaign" / str(row.get("candidate_id", "")) / str(
        row.get("workload_case_id", "")
    )


def _blocked_row(row: Mapping[str, Any], blockers: Sequence[str]) -> Dict[str, Any]:
    return {
        "candidate_id": str(row.get("candidate_id", "")),
        "workload_case_id": str(row.get("workload_case_id", "")),
        "status": "blocked",
        "trusted_accelerated_numeric_source": False,
        "blockers": sorted(dict.fromkeys(str(item) for item in blockers)),
        "claim_boundary": "No sidecar bridge row was run because required producer artifacts were missing or invalid.",
    }


def _run_row(
    row: Mapping[str, Any],
    *,
    simulator: Path,
    timeout: int,
) -> Dict[str, Any]:
    candidate_id = str(row.get("candidate_id", ""))
    workload_case_id = str(row.get("workload_case_id", ""))
    snapshot = _required_path(row, "kernel_boundary_snapshot_json")
    arrays = _required_path(row, "kernel_boundary_arrays_json")
    baseline = _resolve_repo_path(row.get("baseline_comparison"))
    accelerated_stdout = _required_path(row, "accelerated_stdout")
    out_dir = _row_out_dir(row)

    missing = [
        f"missing_hpsi_sidecar_input:{name}:{path}"
        for name, path in [
            ("kernel_boundary_snapshot_json", snapshot),
            ("kernel_boundary_arrays_json", arrays),
            ("baseline_comparison", baseline),
            ("accelerated_stdout", accelerated_stdout),
        ]
        if path is None or not path.exists()
    ]
    if missing:
        return _blocked_row(row, missing)

    cmd = [
        sys.executable,
        str(BRIDGE),
        "--candidate-id",
        candidate_id,
        "--workload-case-id",
        workload_case_id,
        "--snapshot",
        str(snapshot),
        "--boundary-arrays",
        str(arrays),
        "--baseline-comparison",
        str(baseline),
        "--accelerated-stdout",
        str(accelerated_stdout),
        "--out-dir",
        str(out_dir),
        "--simulator",
        str(simulator),
        "--timeout",
        str(timeout),
        "--fail-on-trusted",
    ]
    completed = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout + 30)
    bridge_index_path = out_dir / "hpsi_sidecar_bridge_index.json"
    bridge_index: Mapping[str, Any] = {}
    if bridge_index_path.exists():
        loaded = _load_json(bridge_index_path)
        bridge_index = loaded if isinstance(loaded, Mapping) else {}
    blockers = [str(item) for item in bridge_index.get("blockers", []) or []]
    if completed.returncode != 0:
        blockers.append(f"hpsi_sidecar_bridge_returncode:{completed.returncode}")
    return {
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "status": bridge_index.get("status", "blocked") if completed.returncode == 0 else "blocked",
        "trusted_accelerated_numeric_source": bridge_index.get("trusted_accelerated_numeric_source", False),
        "returncode": completed.returncode,
        "cmd": cmd,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "artifacts": {
            "out_dir": str(out_dir),
            "hpsi_sidecar_bridge_index": str(bridge_index_path),
            "qe_accelerated_numeric_evidence": str(out_dir / "qe_accelerated_numeric_evidence.json"),
            "kernel_evidence": str(out_dir / "kernel_evidence.json"),
            "offload_provenance": str(out_dir / "offload_provenance.json"),
        },
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "Campaign row is foundation/component-model evidence only. It remains blocked for trusted correctness "
            "unless future offload provenance proves full h_psi was recomputed by the L4/accelerated path."
        ),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--simulator", type=Path, default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim")
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--workload-case-id", default=None)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out-index", type=Path, default=None)
    parser.add_argument(
        "--out-evidence",
        type=Path,
        default=None,
        help="Optional bundle JSON containing only final qe_accelerated_numeric_evidence rows for matrix consumption.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    requirements_path = _resolve_repo_path(args.requirements) or args.requirements
    requirements = _load_json(requirements_path)
    rows = requirements.get("rows", []) if isinstance(requirements, Mapping) else []
    selected_rows = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and (args.candidate_id is None or str(row.get("candidate_id")) == args.candidate_id)
        and (args.workload_case_id is None or str(row.get("workload_case_id")) == args.workload_case_id)
    ]
    simulator = _resolve_repo_path(args.simulator) or args.simulator
    campaign_rows = [_run_row(row, simulator=simulator, timeout=args.timeout) for row in selected_rows]
    blocked_count = sum(1 for row in campaign_rows if str(row.get("status", "")).startswith("blocked"))
    out_index = args.out_index or (requirements_path.parent / "hpsi_sidecar_bridge_campaign_index.json")
    out_evidence = args.out_evidence or (out_index.parent / "hpsi_sidecar_bridge_evidence_bundle.json")
    evidence_rows: list[Dict[str, Any]] = []
    evidence_blockers: list[str] = []
    for row in campaign_rows:
        artifacts = row.get("artifacts", {})
        evidence_path = Path(str(artifacts.get("qe_accelerated_numeric_evidence", ""))) if isinstance(artifacts, Mapping) else None
        if evidence_path is None or not evidence_path.exists():
            evidence_blockers.append(
                f"missing_hpsi_sidecar_evidence_bundle_input:{row.get('candidate_id')}:{row.get('workload_case_id')}:{evidence_path}"
            )
            continue
        try:
            loaded = _load_json(evidence_path)
        except Exception as exc:  # pragma: no cover - defensive bundle preservation
            evidence_blockers.append(f"unreadable_hpsi_sidecar_evidence_bundle_input:{evidence_path}:{exc}")
            continue
        if isinstance(loaded, Mapping):
            evidence_rows.append(dict(loaded))
        else:
            evidence_blockers.append(f"non_object_hpsi_sidecar_evidence_bundle_input:{evidence_path}")
    evidence_bundle = {
        "schema_version": "dse.qe_hpsi_sidecar_bridge_evidence_bundle.v1",
        "requirements": str(requirements_path),
        "row_count": len(evidence_rows),
        "rows": evidence_rows,
        "blockers": sorted(dict.fromkeys(evidence_blockers)),
        "claim_boundary": (
            "Bundle contains final sidecar/component-model numeric evidence rows only. Rows remain untrusted "
            "unless their own provenance and the full L4 matrix gates pass."
        ),
    }
    _write_json(out_evidence, evidence_bundle)
    index = {
        "schema_version": CAMPAIGN_SCHEMA,
        "requirements": str(requirements_path),
        "simulator": str(simulator),
        "selected_row_count": len(selected_rows),
        "passed_foundation_row_count": len(campaign_rows) - blocked_count,
        "blocked_row_count": blocked_count,
        "trusted_row_count": sum(1 for row in campaign_rows if row.get("trusted_accelerated_numeric_source") is True),
        "evidence_bundle": str(out_evidence),
        "evidence_bundle_row_count": len(evidence_rows),
        "evidence_bundle_blockers": evidence_bundle["blockers"],
        "rows": campaign_rows,
        "claim_boundary": (
            "The campaign only automates sidecar/component evidence generation. Trusted completion still requires "
            "the full L4 matrix to pass every QE numerical, gem5, calibration, and provenance gate."
        ),
    }
    _write_json(out_index, index)
    print(json.dumps(index, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and blocked_count else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
