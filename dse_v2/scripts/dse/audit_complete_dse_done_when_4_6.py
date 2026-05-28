#!/usr/bin/env python3
"""Emit the current-goal Complete-DSE Done-when 4-6 audit report."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.reference_workloads.complete_dse_done_when_4_6_audit import (  # noqa: E402
    REPORT_NAME,
    STATUS_NAME,
    build_complete_dse_done_when_4_6_audit,
    write_complete_dse_done_when_4_6_audit,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--control-root", type=Path, default=None)
    parser.add_argument("--goal-path", type=Path, default=None)
    parser.add_argument("--barrier-path", type=Path, default=None)
    parser.add_argument("--preflight-path", type=Path, default=None)
    parser.add_argument("--north-star-path", type=Path, default=None)
    parser.add_argument("--strict-qe-release-bundle-manifest-path", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger-validation", type=Path, default=None)
    parser.add_argument("--target-evidence-ledger-status", type=Path, default=None)
    parser.add_argument("--gate-adjudication", type=Path, default=None)
    parser.add_argument("--gate-adjudication-validation", type=Path, default=None)
    parser.add_argument("--gate-adjudication-status", type=Path, default=None)
    return parser.parse_args(argv)


def _load_json(path: Path | None) -> dict:
    if path is None:
        return {}
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_ref(path: Path | None, *, required: bool) -> dict:
    if path is None:
        return {
            "path": None,
            "required": required,
            "exists": False,
            "status": "missing_required" if required else "not_attached",
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    candidate = Path(path)
    exists = candidate.is_file()
    return {
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "status": "present_hash_valid" if exists else "missing_required" if required else "not_attached",
        "sha256": _sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
    }


def _build_target_counter_audit(args: argparse.Namespace) -> dict:
    ledger = _load_json(args.target_evidence_ledger)
    ledger_validation = _load_json(args.target_evidence_ledger_validation)
    ledger_status = _load_json(args.target_evidence_ledger_status)
    gate_adjudication = _load_json(args.gate_adjudication)
    gate_validation = _load_json(args.gate_adjudication_validation)
    gate_status = _load_json(args.gate_adjudication_status)

    artifact_refs = {
        "target_evidence_gate_ledger": _source_ref(args.target_evidence_ledger, required=False),
        "target_evidence_gate_ledger_validation": _source_ref(args.target_evidence_ledger_validation, required=False),
        "target_evidence_gate_ledger_status": _source_ref(args.target_evidence_ledger_status, required=False),
        "gate_adjudication": _source_ref(args.gate_adjudication, required=False),
        "gate_adjudication_validation": _source_ref(args.gate_adjudication_validation, required=False),
        "gate_adjudication_status": _source_ref(args.gate_adjudication_status, required=False),
    }
    source_artifacts_present = all(ref.get("exists") is True for ref in artifact_refs.values())
    ledger_counters = {
        "candidate_kernel_target_axis_count": ledger_status.get(
            "candidate_kernel_target_axis_count",
            ledger.get("candidate_kernel_target_axis_count"),
        ),
        "candidate_kernel_target_axis_counts_by_target": ledger_status.get(
            "candidate_kernel_target_axis_counts_by_target",
            ledger.get("candidate_kernel_target_axis_counts_by_target", {}),
        ),
        "row_counts_by_candidate_kernel_target_axis": ledger_status.get(
            "row_counts_by_candidate_kernel_target_axis",
            ledger.get("row_counts_by_candidate_kernel_target_axis", {}),
        ),
        "row_counts_by_target_platform_kind": ledger_status.get(
            "row_counts_by_target_platform_kind",
            ledger.get("row_counts_by_target_platform_kind", {}),
        ),
        "unknown_target_platform_kind_row_count": ledger_status.get(
            "unknown_target_platform_kind_row_count",
            ledger.get("unknown_target_platform_kind_row_count", 0),
        ),
        "parsed_stage_result_ref_count": ledger_status.get(
            "parsed_stage_result_ref_count",
            ledger.get("parsed_stage_result_ref_count", 0),
        ),
        "stable_blocker_reason_counts": ledger_status.get(
            "stable_blocker_reason_counts",
            ledger.get("stable_blocker_reason_counts", {}),
        ),
        "blocker_count": ledger_status.get("blocker_count", ledger.get("blocker_count", 0)),
        "claim_upgrade_allowed_count": ledger_status.get(
            "claim_upgrade_allowed_count",
            0,
        ),
        "availability_probe_only_row_count": ledger_status.get(
            "availability_probe_only_row_count",
            0,
        ),
    }
    gate_counters = {
        "candidate_kernel_target_axis_count": gate_status.get(
            "candidate_kernel_target_axis_count",
            gate_adjudication.get("candidate_kernel_target_axis_count", 0),
        ),
        "candidate_kernel_target_axis_counts_by_target": gate_status.get(
            "candidate_kernel_target_axis_counts_by_target",
            gate_adjudication.get("candidate_kernel_target_axis_counts_by_target", {}),
        ),
        "stage_counts_by_target": gate_status.get(
            "stage_counts_by_target",
            gate_adjudication.get("stage_counts_by_target", {}),
        ),
        "unknown_target_platform_kind_unit_count": gate_status.get(
            "unknown_target_platform_kind_unit_count",
            gate_adjudication.get("unknown_target_platform_kind_unit_count", 0),
        ),
        "unknown_target_platform_kind_stage_count": gate_status.get(
            "unknown_target_platform_kind_stage_count",
            gate_adjudication.get("unknown_target_platform_kind_stage_count", 0),
        ),
        "blocker_id_counts": gate_status.get(
            "blocker_id_counts",
            gate_adjudication.get("blocker_id_counts", {}),
        ),
        "stage_gate_passed_count": gate_status.get(
            "stage_gate_passed_count",
            gate_adjudication.get("stage_gate_passed_count", 0),
        ),
        "blocked_stage_count": gate_status.get(
            "blocked_stage_count",
            gate_adjudication.get("blocked_stage_count", 0),
        ),
        "failed_stage_count": gate_status.get(
            "failed_stage_count",
            gate_adjudication.get("failed_stage_count", 0),
        ),
        "unit_gate_passed_count": gate_status.get(
            "unit_gate_passed_count",
            gate_adjudication.get("unit_gate_passed_count", 0),
        ),
        "candidate_kernel_axis_unbound_stage_count": gate_status.get(
            "candidate_kernel_axis_unbound_stage_count",
            gate_adjudication.get("candidate_kernel_axis_unbound_stage_count", 0),
        ),
        "parsed_stage_result_ref_count": gate_status.get(
            "parsed_stage_result_ref_count",
            gate_adjudication.get("parsed_stage_result_ref_count", 0),
        ),
    }
    blocker_ids = sorted(
        {
            *(str(blocker) for blocker in ledger_counters["stable_blocker_reason_counts"] if blocker),
            *(str(blocker) for blocker in gate_counters["blocker_id_counts"] if blocker),
            *(
                str(blocker.get("id") or "")
                for blocker in ledger_validation.get("blockers", [])
                if isinstance(blocker, dict) and blocker.get("id")
            ),
            *(
                str(blocker.get("id") or "")
                for blocker in gate_validation.get("errors", [])
                if isinstance(blocker, dict) and blocker.get("id")
            ),
        }
    )
    source_status = "passed" if source_artifacts_present else "blocked"
    status = "blocked" if not source_artifacts_present else "partial"
    target_counter_audit = {
        "schema_version": "dse.dft.current_goal.target_counter_audit.v1",
        "status": status,
        "source_counter_status": source_status,
        "counter_source": "producer_output_artifacts",
        "hard_gate_counter_source": "gate_adjudication_artifacts",
        "producer_output_visible": source_artifacts_present,
        "test_fixture_only_visible": False,
        "artifact_refs": artifact_refs,
        "ledger_counters": ledger_counters,
        "gate_adjudication_counters": gate_counters,
        "blocker_ids": blocker_ids,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Target counter audit binds producer outputs and hard-gate audit "
            "surfaces only. It keeps unknown target rows and unavailable-tool "
            "evidence fail-closed and cannot upgrade FPGA/ASIC/PPA claims."
        ),
    }
    target_counter_audit["audit_hash"] = stable_json_hash(
        {key: value for key, value in target_counter_audit.items() if key != "audit_hash"}
    )
    return target_counter_audit


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_complete_dse_done_when_4_6_audit(
        repo_root=args.repo_root,
        control_root=args.control_root,
        goal_path=args.goal_path,
        barrier_path=args.barrier_path,
        preflight_path=args.preflight_path,
        north_star_path=args.north_star_path,
        strict_qe_release_bundle_manifest_path=args.strict_qe_release_bundle_manifest_path,
    )
    status = write_complete_dse_done_when_4_6_audit(args.out, payload)
    if any(
        getattr(args, name) is not None
        for name in (
            "target_evidence_ledger",
            "target_evidence_ledger_validation",
            "target_evidence_ledger_status",
            "gate_adjudication",
            "gate_adjudication_validation",
            "gate_adjudication_status",
        )
    ):
        target_counter_audit = _build_target_counter_audit(args)
        report_path = args.out / REPORT_NAME
        status_path = args.out / STATUS_NAME
        report = _load_json(report_path)
        report["target_counter_audit"] = target_counter_audit
        report["audit_hash"] = stable_json_hash(
            {key: value for key, value in report.items() if key != "audit_hash"}
        )
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        status.update(
            {
                "target_counter_audit_status": target_counter_audit["status"],
                "target_counter_audit_hash": target_counter_audit["audit_hash"],
                "target_counter_audit_blocker_ids": list(target_counter_audit["blocker_ids"]),
                "target_counter_audit_producer_output_visible": target_counter_audit[
                    "producer_output_visible"
                ],
                "target_counter_audit_test_fixture_only_visible": target_counter_audit[
                    "test_fixture_only_visible"
                ],
                "deliverable_complete": False,
            }
        )
        status["status_hash"] = stable_json_hash(
            {key: value for key, value in status.items() if key != "status_hash"}
        )
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": status["artifact"],
                "status_path": status["status_path"],
                "status": status["status"],
                "deliverable_complete": False,
                "blocker_ids": status["blocker_ids"],
                "target_counter_audit_status": status.get("target_counter_audit_status"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
