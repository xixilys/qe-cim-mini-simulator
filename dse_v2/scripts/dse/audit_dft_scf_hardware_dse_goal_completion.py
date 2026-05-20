#!/usr/bin/env python3
"""Audit the active DFT/QE full-SCF hardware DSE goal.

This is a goal-level anti-downgrade checklist.  It does not try to create new
evidence; it reads an existing Step5 final report and answers whether the goal
is complete, still in progress, or failed because a report over-claims.  The
date horizon is a first-class gate: before 2026-06-01 12:00 local time the audit
must remain in progress even if all technical evidence is green.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo


AUDIT_SCHEMA = "dse.dft_scf_hardware.goal_completion_audit.v1"
DEFAULT_HORIZON_LOCAL = "2026-06-01 12:00:00"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}




def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_semantic_source_path(ref_path: Any, *, run_dir: Optional[Path], closure_path: Optional[Path]) -> Optional[Path]:
    if not ref_path:
        return None
    path = Path(str(ref_path))
    if path.is_absolute():
        return path
    candidates = []
    if run_dir is not None:
        candidates.append(Path(run_dir) / path)
    if closure_path is not None:
        candidates.append(Path(closure_path).parent / path)
    candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else path


def _load_semantic_closure_payload(
    *,
    run_dir: Optional[Path],
    report: Mapping[str, Any],
    semantic_closure_path: Optional[Path],
) -> Dict[str, Any]:
    path: Optional[Path] = semantic_closure_path
    if path is None and run_dir is not None:
        path = Path(run_dir) / "dft_audit_semantic_closure.json"
    if path is not None and path.exists():
        payload = _load_json(path)
        source = {"kind": "file", "path": str(path), "sha256": _sha256(path)}
    else:
        payload = _mapping(report.get("dft_audit_semantic_closure"))
        path = None
        source = {"kind": "final_report_section", "path": None, "sha256": None}
    checks = _list_of_mappings(payload.get("checks"))
    check_ids = {str(item.get("check_id")) for item in checks if item.get("check_id")}
    required_check_ids = {
        "phase_hotspot_identity",
        "evaluation_policy_legality",
        "candidate_tier_absence",
        "coverage_vector_derivation",
        "reference_hash_admission",
    }
    source_artifacts = _mapping(payload.get("source_artifacts"))
    source_hash_errors: list[str] = []
    required_source_count = 0
    hashed_required_source_count = 0
    embedded_report_section = path is None
    for label, ref_any in source_artifacts.items():
        ref = _mapping(ref_any)
        if ref.get("required") is True:
            required_source_count += 1
            if ref.get("sha256"):
                hashed_required_source_count += 1
            else:
                source_hash_errors.append(f"{label}:missing_sha256")
            if not embedded_report_section and ref.get("exists") is not True:
                source_hash_errors.append(f"{label}:required_source_missing")
        if embedded_report_section or not ref.get("sha256") or ref.get("exists") is not True:
            continue
        resolved = _resolve_semantic_source_path(ref.get("path"), run_dir=run_dir, closure_path=path)
        if resolved is None or not resolved.exists() or not resolved.is_file():
            source_hash_errors.append(f"{label}:referenced_source_missing")
            continue
        actual = _sha256(resolved)
        if actual != ref.get("sha256"):
            source_hash_errors.append(f"{label}:source_hash_mismatch")
    missing_checks = sorted(required_check_ids - check_ids)
    failed_checks = [str(item.get("check_id")) for item in checks if item.get("passed") is not True]
    source_hash_backed = (
        bool(source_artifacts)
        and required_source_count > 0
        and hashed_required_source_count == required_source_count
        and not source_hash_errors
    )
    overall_passed = bool(payload.get("overall_passed") is True)
    valid = bool(
        payload
        and payload.get("schema_version") == "dse.dft_scf.semantic_audit_closure.v1"
        and overall_passed
        and source_hash_backed
        and not missing_checks
        and not failed_checks
    )
    return {
        "present": bool(payload),
        "valid": valid,
        "source": source,
        "schema_version": payload.get("schema_version"),
        "overall_passed": overall_passed,
        "source_hash_backed": source_hash_backed,
        "required_source_count": required_source_count,
        "hashed_required_source_count": hashed_required_source_count,
        "source_hash_errors": source_hash_errors,
        "missing_checks": missing_checks,
        "failed_checks": failed_checks,
        "checks": checks,
        "claim_boundary": payload.get("claim_boundary"),
    }


def _date_text() -> str:
    try:
        return subprocess.check_output(["date", "-Is"], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return datetime.now(LOCAL_TZ).isoformat()


def _parse_local_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=LOCAL_TZ)


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _status_item(requirement: str, status: str, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "requirement": requirement,
        "status": status,
        "evidence": dict(evidence),
    }


def _final_report_path(*, run_dir: Optional[Path], final_report: Optional[Path]) -> Path:
    if final_report is not None:
        return Path(final_report)
    if run_dir is None:
        raise ValueError("Either run_dir or final_report is required")
    return Path(run_dir) / "final_report.json"


def _release_gate_detail_payload(
    *,
    run_dir: Optional[Path],
    final_report_section: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the raw release gate when available, otherwise the Step5 section.

    Step5 summarizes release-gate artifacts for the final report and may not
    carry every per-candidate/per-kernel blocker.  The audit is more actionable
    when it is run with ``run_dir`` because it can read the adjacent raw
    ``dft_hardware_closure_release_gate.json`` without changing the gate
    semantics.
    """

    if run_dir is not None:
        raw_path = Path(run_dir) / "dft_hardware_closure_release_gate.json"
        raw = _load_json(raw_path)
        if raw:
            raw["detail_source"] = str(raw_path)
            return raw
    section = dict(final_report_section)
    section["detail_source"] = "final_report.dft_hardware_closure_release_gate"
    return section


def _synthesized_release_hardware_blockers(release_gate: Mapping[str, Any]) -> list[Dict[str, Any]]:
    blockers = _list_of_mappings(release_gate.get("hardware_eligibility_blockers"))
    if blockers:
        return blockers
    if release_gate.get("hardware_completion_eligible") is True:
        return []
    if release_gate.get("unit_count_complete") is False:
        blockers.append(
            {
                "blocker_id": "unit_count_incomplete",
                "reason": "actual unit_count must equal candidate_count*major_kernel_count",
                "expected_unit_count": release_gate.get("expected_unit_count"),
                "actual_unit_count": release_gate.get("actual_unit_count", release_gate.get("unit_count")),
                "unit_count_semantics": release_gate.get(
                    "unit_count_semantics",
                    "candidate_count*major_kernel_count",
                ),
            }
        )
    if release_gate.get("candidate_count_complete") is False:
        blockers.append(
            {
                "blocker_id": "candidate_count_incomplete",
                "reason": "actual candidate count does not match declared candidate_count",
                "candidate_count": release_gate.get("candidate_count"),
            }
        )
    if release_gate.get("per_candidate_kernel_coverage_complete") is False:
        blockers.append(
            {
                "blocker_id": "per_candidate_kernel_coverage_incomplete",
                "reason": "one or more candidates do not cover every required major kernel",
                "candidates_with_incomplete_kernel_coverage": release_gate.get(
                    "candidates_with_incomplete_kernel_coverage"
                ),
            }
        )
    if int(release_gate.get("failed_unit_count", 0) or 0) > 0:
        blockers.append(
            {
                "blocker_id": "failed_candidate_kernel_units",
                "reason": "one or more candidate×kernel units have failed hard-gate stages",
                "failed_unit_count": release_gate.get("failed_unit_count"),
            }
        )
    if int(release_gate.get("blocked_unit_count", 0) or 0) > 0:
        blockers.append(
            {
                "blocker_id": "blocked_candidate_kernel_units",
                "reason": "one or more candidate×kernel units are missing or blocked at hard-gate stages",
                "blocked_unit_count": release_gate.get("blocked_unit_count"),
            }
        )
    if not blockers:
        blockers.append(
            {
                "blocker_id": "hardware_completion_not_eligible",
                "reason": "release gate did not mark hardware_completion_eligible",
            }
        )
    return blockers


def _release_deliverable_blockers(
    release_gate: Mapping[str, Any],
    *,
    deliverable_complete: bool,
) -> list[Dict[str, Any]]:
    if deliverable_complete and release_gate.get("hardware_completion_eligible") is True:
        return []
    blockers = _list_of_mappings(release_gate.get("deliverable_completion_blockers"))
    if not blockers:
        blockers = [
            {
                "blocker_id": "release_gate_cannot_mark_deliverable_complete",
                "reason": "hardware release gate is not the final deliverable claim gate",
            }
        ]
        if release_gate.get("hardware_completion_eligible") is not True:
            blockers.append(
                {
                    "blocker_id": "hardware_completion_not_eligible",
                    "reason": "hardware completion eligibility is still blocked",
                }
            )
    if not deliverable_complete:
        blockers.append(
            {
                "blocker_id": "release_claim_gate_deliverable_complete_false",
                "reason": "final release claim gate has not marked deliverable_complete",
            }
        )
    return blockers


def build_dft_scf_hardware_goal_completion_audit(
    *,
    run_dir: Optional[Path] = None,
    final_report: Optional[Path] = None,
    horizon_local: str = DEFAULT_HORIZON_LOCAL,
    now: Optional[datetime] = None,
    semantic_closure_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return a fail-closed prompt-to-artifact audit for the active goal."""

    report_path = _final_report_path(run_dir=run_dir, final_report=final_report)
    report = _load_json(report_path)
    dft_audit_semantic_closure = _load_semantic_closure_payload(
        run_dir=run_dir,
        report=report,
        semantic_closure_path=semantic_closure_path,
    )
    now_dt = now or datetime.now(LOCAL_TZ)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=LOCAL_TZ)
    horizon_dt = _parse_local_datetime(horizon_local)
    horizon_reached = now_dt >= horizon_dt

    dft_ledger = _mapping(report.get("dft_evidence_ledger"))
    dft_trial_ledger = _mapping(report.get("dft_trial_state_ledger"))
    dft_candidate_binding = _mapping(report.get("dft_candidate_binding_map"))
    dft_hardware_workplan = _mapping(report.get("dft_hardware_completion_workplan"))
    dft_hardware_shards = _mapping(report.get("dft_hardware_closure_shards"))
    dft_hardware_packets = _mapping(report.get("dft_hardware_closure_packets"))
    dft_hardware_bundles = _mapping(report.get("dft_hardware_closure_candidate_bundles"))
    dft_hardware_unit_provenance = _mapping(report.get("dft_hardware_closure_unit_provenance"))
    dft_hardware_source_flow_plan = _mapping(report.get("dft_hardware_closure_source_flow_plan"))
    dft_hardware_raw_materialization = _mapping(report.get("dft_hardware_closure_raw_stage_materialization"))
    dft_hardware_raw_registration = _mapping(report.get("dft_hardware_closure_raw_transcript_registration"))
    dft_hardware_intake = _mapping(report.get("dft_hardware_closure_evidence_intake"))
    dft_hardware_adjudication = _mapping(report.get("dft_hardware_closure_adjudication"))
    dft_hardware_parsed = _mapping(report.get("dft_hardware_closure_parsed_evidence"))
    dft_hardware_parser_run = _mapping(report.get("dft_hardware_closure_parser_run"))
    dft_hardware_gate_adjudication = _mapping(report.get("dft_hardware_closure_gate_adjudication"))
    dft_hardware_release_gate = _mapping(report.get("dft_hardware_closure_release_gate"))
    dft_l4_goal_binding = _mapping(report.get("dft_l4_goal_binding"))
    release_claim_gate = _mapping(dft_ledger.get("release_claim_gate"))
    eda_summary = _mapping(dft_ledger.get("eda_summary"))
    dft_hybrid = _mapping(report.get("dft_full_scf_evaluated_hybrid"))
    hybrid_costs = _mapping(report.get("full_scf_evaluated_hybrid_costs"))
    selected = _mapping(report.get("selected_recommendation"))

    deliverable_complete = bool(
        release_claim_gate.get(
            "deliverable_complete",
            dft_ledger.get("deliverable_complete", False),
        )
    )
    trial_ledger_deliverable_complete = bool(dft_trial_ledger.get("deliverable_complete", False))
    candidate_binding_deliverable_complete = bool(dft_candidate_binding.get("deliverable_complete", False))
    candidate_binding_completion_eligible = bool(dft_candidate_binding.get("completion_eligible", False))
    workplan_deliverable_complete = bool(dft_hardware_workplan.get("deliverable_complete", False))
    workplan_hardware_completion_eligible = bool(dft_hardware_workplan.get("hardware_completion_eligible", False))
    shards_deliverable_complete = bool(dft_hardware_shards.get("deliverable_complete", False))
    shards_hardware_completion_eligible = bool(dft_hardware_shards.get("hardware_completion_eligible", False))
    packets_deliverable_complete = bool(dft_hardware_packets.get("deliverable_complete", False))
    packets_hardware_completion_eligible = bool(dft_hardware_packets.get("hardware_completion_eligible", False))
    bundles_deliverable_complete = bool(dft_hardware_bundles.get("deliverable_complete", False))
    bundles_hardware_completion_eligible = bool(dft_hardware_bundles.get("hardware_completion_eligible", False))
    unit_provenance_deliverable_complete = bool(dft_hardware_unit_provenance.get("deliverable_complete", False))
    unit_provenance_hardware_completion_eligible = bool(
        dft_hardware_unit_provenance.get("hardware_completion_eligible", False)
    )
    source_flow_plan_deliverable_complete = bool(dft_hardware_source_flow_plan.get("deliverable_complete", False))
    source_flow_plan_hardware_completion_eligible = bool(
        dft_hardware_source_flow_plan.get("hardware_completion_eligible", False)
    )
    raw_materialization_deliverable_complete = bool(dft_hardware_raw_materialization.get("deliverable_complete", False))
    raw_materialization_hardware_completion_eligible = bool(
        dft_hardware_raw_materialization.get("hardware_completion_eligible", False)
    )
    raw_registration_deliverable_complete = bool(dft_hardware_raw_registration.get("deliverable_complete", False))
    raw_registration_hardware_completion_eligible = bool(
        dft_hardware_raw_registration.get("hardware_completion_eligible", False)
    )
    intake_deliverable_complete = bool(dft_hardware_intake.get("deliverable_complete", False))
    intake_hardware_completion_eligible = bool(dft_hardware_intake.get("hardware_completion_eligible", False))
    adjudication_deliverable_complete = bool(dft_hardware_adjudication.get("deliverable_complete", False))
    adjudication_hardware_completion_eligible = bool(dft_hardware_adjudication.get("hardware_completion_eligible", False))
    parsed_deliverable_complete = bool(dft_hardware_parsed.get("deliverable_complete", False))
    parsed_hardware_completion_eligible = bool(dft_hardware_parsed.get("hardware_completion_eligible", False))
    parser_run_deliverable_complete = bool(dft_hardware_parser_run.get("deliverable_complete", False))
    parser_run_hardware_completion_eligible = bool(dft_hardware_parser_run.get("hardware_completion_eligible", False))
    gate_adjudication_deliverable_complete = bool(dft_hardware_gate_adjudication.get("deliverable_complete", False))
    gate_adjudication_hardware_completion_eligible = bool(dft_hardware_gate_adjudication.get("hardware_completion_eligible", False))
    release_gate_deliverable_complete = bool(dft_hardware_release_gate.get("deliverable_complete", False))
    l4_goal_binding_deliverable_complete = bool(dft_l4_goal_binding.get("deliverable_complete", False))
    l4_goal_binding_final_closure_eligible = bool(dft_l4_goal_binding.get("final_closure_eligible", False))
    l4_goal_binding_validation = _mapping(dft_l4_goal_binding.get("validation"))
    l4_current_goal_binding = _mapping(dft_l4_goal_binding.get("current_goal_binding"))
    trusted_winner = bool(selected.get("trusted_winner", False))
    hybrid_completion_claim = bool(dft_hybrid.get("completion_claim", False))
    hybrid_ppa_claim = bool(dft_hybrid.get("ppa_claim_eligible", False))
    hybrid_numerical_claim = bool(dft_hybrid.get("numerical_correctness_claim_eligible", False))
    availability_completion_claim = str(
        eda_summary.get("ic_eda_tool_availability_completion_claim") or ""
    )
    availability_kernel_ppa_evidence = bool(
        eda_summary.get("ic_eda_tool_availability_kernel_ppa_evidence", False)
    )
    availability_hardware_completion_eligible = bool(
        eda_summary.get("ic_eda_tool_availability_hardware_completion_eligible", False)
    )
    current_release_hardware_completion_eligible = bool(
        dft_hardware_release_gate.get("hardware_completion_eligible", False)
    )
    release_gate_details = _release_gate_detail_payload(
        run_dir=run_dir,
        final_report_section=dft_hardware_release_gate,
    )
    current_release_hardware_completion_eligible = bool(
        dft_hardware_release_gate.get(
            "hardware_completion_eligible",
            release_gate_details.get("hardware_completion_eligible", False),
        )
        or release_gate_details.get("hardware_completion_eligible", False)
    )
    release_hardware_blockers = _synthesized_release_hardware_blockers(release_gate_details)
    release_deliverable_blockers = _release_deliverable_blockers(
        release_gate_details,
        deliverable_complete=deliverable_complete,
    )
    release_candidate_kernel_blockers = _list_of_mappings(
        release_gate_details.get("candidate_kernel_blockers")
    )
    release_unit_stage_blockers = _list_of_mappings(release_gate_details.get("unit_stage_blockers"))
    availability_probe_present = bool(_mapping(eda_summary.get("ic_eda_tool_availability")).get("path"))
    availability_raw_attempt_count = int(eda_summary.get("ic_eda_tool_availability_raw_attempt_count", 0) or 0)
    availability_payload_boundary_valid = bool(
        eda_summary.get("ic_eda_tool_availability_payload_claim_boundary_valid", False)
    )

    checklist = [
        _status_item(
            f"Use date and keep working until {horizon_dt.isoformat()} before goal completion",
            "passed" if horizon_reached else "in_progress",
            {
                "checked_at_date_command": _date_text(),
                "now_iso": now_dt.isoformat(),
                "horizon_local": horizon_dt.isoformat(),
                "horizon_reached": horizon_reached,
            },
        ),
        _status_item(
            "Step5 final_report.json is present and readable",
            "passed" if bool(report) else "failed",
            {"final_report": str(report_path), "schema_version": report.get("schema_version")},
        ),
        _status_item(
            "DFT semantic audit closure artifact is source-hash backed and passed",
            "passed" if dft_audit_semantic_closure.get("valid") is True else "blocked",
            {
                "present": dft_audit_semantic_closure.get("present"),
                "schema_version": dft_audit_semantic_closure.get("schema_version"),
                "source": dft_audit_semantic_closure.get("source"),
                "overall_passed": dft_audit_semantic_closure.get("overall_passed"),
                "source_hash_backed": dft_audit_semantic_closure.get("source_hash_backed"),
                "required_source_count": dft_audit_semantic_closure.get("required_source_count"),
                "hashed_required_source_count": dft_audit_semantic_closure.get("hashed_required_source_count"),
                "source_hash_errors": dft_audit_semantic_closure.get("source_hash_errors"),
                "missing_checks": dft_audit_semantic_closure.get("missing_checks"),
                "failed_checks": dft_audit_semantic_closure.get("failed_checks"),
                "claim_boundary": dft_audit_semantic_closure.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT evidence ledger is cited by Step5",
            "passed" if dft_ledger.get("present") is True else "blocked",
            {
                "present": dft_ledger.get("present"),
                "status": dft_ledger.get("status"),
                "release_id": dft_ledger.get("release_id"),
            },
        ),
        _status_item(
            "IC/EDA availability bridge is Step5-visible and not PPA evidence",
            "passed"
            if dft_ledger.get("present") is True
            and availability_probe_present
            and eda_summary.get("tool_availability_status") == "passed"
            and eda_summary.get("ic_eda_tool_availability_payload_status") == "passed"
            and eda_summary.get("ic_eda_tool_availability_all_required_tools_available") is True
            and availability_raw_attempt_count > 0
            and "not_kernel_ppa" in availability_completion_claim
            and availability_payload_boundary_valid
            and not availability_kernel_ppa_evidence
            and not availability_hardware_completion_eligible
            else "blocked",
            {
                "probe_present": availability_probe_present,
                "tool_availability_status": eda_summary.get("tool_availability_status"),
                "ic_eda_tool_availability": eda_summary.get("ic_eda_tool_availability"),
                "payload_status": eda_summary.get("ic_eda_tool_availability_payload_status"),
                "all_required_tools_available": eda_summary.get(
                    "ic_eda_tool_availability_all_required_tools_available"
                ),
                "raw_attempt_count": availability_raw_attempt_count,
                "completion_claim": availability_completion_claim,
                "raw_completion_claim": eda_summary.get("ic_eda_tool_availability_raw_completion_claim"),
                "payload_claim_boundary_valid": availability_payload_boundary_valid,
                "payload_claim_upgrade_detected": eda_summary.get(
                    "ic_eda_tool_availability_payload_claim_upgrade_detected"
                ),
                "kernel_ppa_evidence": availability_kernel_ppa_evidence,
                "availability_hardware_completion_eligible": availability_hardware_completion_eligible,
                "claim_boundary": eda_summary.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT trial-state ledger is Step5-visible and fail-closed",
            "passed"
            if dft_trial_ledger.get("present") is True
            and (not trial_ledger_deliverable_complete or deliverable_complete)
            and _mapping(dft_trial_ledger.get("validation")).get("valid") is True
            else "blocked",
            {
                "present": dft_trial_ledger.get("present"),
                "status": dft_trial_ledger.get("status"),
                "candidate_count": dft_trial_ledger.get("candidate_count"),
                "blocked_trial_count": dft_trial_ledger.get("blocked_trial_count"),
                "completion_eligible": dft_trial_ledger.get("completion_eligible"),
                "deliverable_complete": trial_ledger_deliverable_complete,
                "validation": dft_trial_ledger.get("validation"),
                "claim_boundary": dft_trial_ledger.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT candidate binding map is Step5-visible and fail-closed",
            "passed"
            if dft_candidate_binding.get("present") is True
            and _mapping(dft_candidate_binding.get("validation")).get("valid") is True
            and not candidate_binding_completion_eligible
            and not candidate_binding_deliverable_complete
            else "blocked",
            {
                "present": dft_candidate_binding.get("present"),
                "status": dft_candidate_binding.get("status"),
                "search_candidate_count": dft_candidate_binding.get("search_candidate_count"),
                "bound_candidate_count": dft_candidate_binding.get("bound_candidate_count"),
                "unmatched_candidate_count": dft_candidate_binding.get("unmatched_candidate_count"),
                "duplicate_release_candidate_ids": dft_candidate_binding.get("duplicate_release_candidate_ids"),
                "completion_eligible": candidate_binding_completion_eligible,
                "deliverable_complete": candidate_binding_deliverable_complete,
                "validation": dft_candidate_binding.get("validation"),
                "claim_boundary": dft_candidate_binding.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware completion workplan is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_workplan.get("present") is True
            and _mapping(dft_hardware_workplan.get("validation")).get("valid") is True
            and not workplan_hardware_completion_eligible
            and not workplan_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_workplan.get("present"),
                "status": dft_hardware_workplan.get("status"),
                "candidate_count": dft_hardware_workplan.get("candidate_count"),
                "major_kernel_count": dft_hardware_workplan.get("major_kernel_count"),
                "required_work_item_count": dft_hardware_workplan.get("required_work_item_count"),
                "blocked_work_item_count": dft_hardware_workplan.get("blocked_work_item_count"),
                "candidate_specific_evidence_present_count": dft_hardware_workplan.get("candidate_specific_evidence_present_count"),
                "hardware_completion_eligible": workplan_hardware_completion_eligible,
                "deliverable_complete": workplan_deliverable_complete,
                "validation": dft_hardware_workplan.get("validation"),
                "claim_boundary": dft_hardware_workplan.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure shard queue is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_shards.get("present") is True
            and _mapping(dft_hardware_shards.get("validation")).get("valid") is True
            and not shards_hardware_completion_eligible
            and not shards_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_shards.get("present"),
                "status": dft_hardware_shards.get("status"),
                "unit_count": dft_hardware_shards.get("unit_count"),
                "shard_count": dft_hardware_shards.get("shard_count"),
                "work_item_count": dft_hardware_shards.get("work_item_count"),
                "blocked_work_item_count": dft_hardware_shards.get("blocked_work_item_count"),
                "candidate_specific_bundle_count": dft_hardware_shards.get("candidate_specific_bundle_count"),
                "hardware_completion_eligible": shards_hardware_completion_eligible,
                "deliverable_complete": shards_deliverable_complete,
                "validation": dft_hardware_shards.get("validation"),
                "claim_boundary": dft_hardware_shards.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure packet/runbook index is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_packets.get("present") is True
            and _mapping(dft_hardware_packets.get("validation")).get("valid") is True
            and not packets_hardware_completion_eligible
            and not packets_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_packets.get("present"),
                "status": dft_hardware_packets.get("status"),
                "packet_count": dft_hardware_packets.get("packet_count"),
                "unit_count": dft_hardware_packets.get("unit_count"),
                "work_item_count": dft_hardware_packets.get("work_item_count"),
                "blocked_work_item_count": dft_hardware_packets.get("blocked_work_item_count"),
                "expected_evidence_file_count": dft_hardware_packets.get("expected_evidence_file_count"),
                "command_template_ids": dft_hardware_packets.get("command_template_ids"),
                "packet_artifact_ref_count": len(dft_hardware_packets.get("packet_artifact_refs", []) or [])
                if isinstance(dft_hardware_packets.get("packet_artifact_refs", []), list)
                else None,
                "candidate_specific_bundle_count": dft_hardware_packets.get("candidate_specific_bundle_count"),
                "candidate_specific_evidence_present_count": dft_hardware_packets.get("candidate_specific_evidence_present_count"),
                "hardware_completion_eligible": packets_hardware_completion_eligible,
                "deliverable_complete": packets_deliverable_complete,
                "validation": dft_hardware_packets.get("validation"),
                "claim_boundary": dft_hardware_packets.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure candidate-bundle templates are Step5-visible and fail-closed",
            "passed"
            if dft_hardware_bundles.get("present") is True
            and _mapping(dft_hardware_bundles.get("validation")).get("valid") is True
            and dft_hardware_bundles.get("bundle_template_only") is True
            and int(dft_hardware_bundles.get("raw_evidence_file_count", 0) or 0) == 0
            and not bundles_hardware_completion_eligible
            and not bundles_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_bundles.get("present"),
                "status": dft_hardware_bundles.get("status"),
                "bundle_count": dft_hardware_bundles.get("bundle_count"),
                "bundle_ref_count": dft_hardware_bundles.get("bundle_ref_count"),
                "expected_evidence_file_count": dft_hardware_bundles.get("expected_evidence_file_count"),
                "raw_evidence_file_count": dft_hardware_bundles.get("raw_evidence_file_count"),
                "bundle_template_only": dft_hardware_bundles.get("bundle_template_only"),
                "hardware_completion_eligible": bundles_hardware_completion_eligible,
                "deliverable_complete": bundles_deliverable_complete,
                "validation": dft_hardware_bundles.get("validation"),
                "claim_boundary": dft_hardware_bundles.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure unit provenance staging is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_unit_provenance.get("present") is True
            and _mapping(dft_hardware_unit_provenance.get("validation")).get("valid") is True
            and int(dft_hardware_unit_provenance.get("raw_stage_evidence_file_count", 0) or 0) == 0
            and not unit_provenance_hardware_completion_eligible
            and not unit_provenance_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_unit_provenance.get("present"),
                "status": dft_hardware_unit_provenance.get("status"),
                "staged_unit_count": dft_hardware_unit_provenance.get("staged_unit_count"),
                "unit_ref_count": dft_hardware_unit_provenance.get("unit_ref_count"),
                "global_provenance_file_count": dft_hardware_unit_provenance.get("global_provenance_file_count"),
                "raw_stage_evidence_file_count": dft_hardware_unit_provenance.get("raw_stage_evidence_file_count"),
                "hardware_completion_eligible": unit_provenance_hardware_completion_eligible,
                "deliverable_complete": unit_provenance_deliverable_complete,
                "validation": dft_hardware_unit_provenance.get("validation"),
                "claim_boundary": dft_hardware_unit_provenance.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure source-flow plan is Step5-visible and fail-closed",
            "passed"
            if (
                dft_hardware_source_flow_plan.get("present") is not True
                or (
                    _mapping(dft_hardware_source_flow_plan.get("validation")).get("valid") is True
                    and not source_flow_plan_hardware_completion_eligible
                    and not source_flow_plan_deliverable_complete
                    and dft_hardware_source_flow_plan.get("adjudication_result")
                    == "not_adjudicated_by_source_flow_plan"
                    and int(dft_hardware_source_flow_plan.get("passed_stage_count", 0) or 0) == 0
                )
            )
            else "blocked",
            {
                "present": dft_hardware_source_flow_plan.get("present"),
                "status": dft_hardware_source_flow_plan.get("status"),
                "unit_count": dft_hardware_source_flow_plan.get("unit_count"),
                "materialization_eligible_unit_count": dft_hardware_source_flow_plan.get(
                    "materialization_eligible_unit_count"
                ),
                "source_flow_present_count": dft_hardware_source_flow_plan.get("source_flow_present_count"),
                "source_flow_missing_count": dft_hardware_source_flow_plan.get("source_flow_missing_count"),
                "blocked_unit_count": dft_hardware_source_flow_plan.get("blocked_unit_count"),
                "source_flow_map": dft_hardware_source_flow_plan.get("source_flow_map"),
                "error_count": dft_hardware_source_flow_plan.get("error_count"),
                "errors": dft_hardware_source_flow_plan.get("errors"),
                "blocker_id_counts": dft_hardware_source_flow_plan.get("blocker_id_counts"),
                "blocked_wrong_candidate_reuse_count": dft_hardware_source_flow_plan.get(
                    "blocked_wrong_candidate_reuse_count"
                ),
                "blocked_wrong_kernel_reuse_count": dft_hardware_source_flow_plan.get(
                    "blocked_wrong_kernel_reuse_count"
                ),
                "adjudication_result": dft_hardware_source_flow_plan.get("adjudication_result"),
                "passed_stage_count": dft_hardware_source_flow_plan.get("passed_stage_count"),
                "hardware_completion_eligible": source_flow_plan_hardware_completion_eligible,
                "deliverable_complete": source_flow_plan_deliverable_complete,
                "validation": dft_hardware_source_flow_plan.get("validation"),
                "claim_boundary": dft_hardware_source_flow_plan.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure raw-stage materialization is Step5-visible and fail-closed",
            "passed"
            if (
                dft_hardware_raw_materialization.get("present") is not True
                or (
                    _mapping(dft_hardware_raw_materialization.get("validation")).get("valid") is True
                    and not raw_materialization_hardware_completion_eligible
                    and not raw_materialization_deliverable_complete
                    and dft_hardware_raw_materialization.get("adjudication_result")
                    == "not_adjudicated_by_raw_stage_materialization"
                    and int(dft_hardware_raw_materialization.get("passed_stage_count", 0) or 0) == 0
                )
            )
            else "blocked",
            {
                "present": dft_hardware_raw_materialization.get("present"),
                "status": dft_hardware_raw_materialization.get("status"),
                "unit_count": dft_hardware_raw_materialization.get("unit_count"),
                "materialized_unit_count": dft_hardware_raw_materialization.get("materialized_unit_count"),
                "blocked_unit_count": dft_hardware_raw_materialization.get("blocked_unit_count"),
                "materialized_file_count": dft_hardware_raw_materialization.get("materialized_file_count"),
                "adjudication_result": dft_hardware_raw_materialization.get("adjudication_result"),
                "passed_stage_count": dft_hardware_raw_materialization.get("passed_stage_count"),
                "hardware_completion_eligible": raw_materialization_hardware_completion_eligible,
                "deliverable_complete": raw_materialization_deliverable_complete,
                "validation": dft_hardware_raw_materialization.get("validation"),
                "claim_boundary": dft_hardware_raw_materialization.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure raw transcript registration is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_raw_registration.get("present") is True
            and _mapping(dft_hardware_raw_registration.get("validation")).get("valid") is True
            and not raw_registration_hardware_completion_eligible
            and not raw_registration_deliverable_complete
            and dft_hardware_raw_registration.get("adjudication_result")
            == "not_adjudicated_by_raw_transcript_registration"
            and int(dft_hardware_raw_registration.get("passed_stage_count", 0) or 0) == 0
            else "blocked",
            {
                "present": dft_hardware_raw_registration.get("present"),
                "status": dft_hardware_raw_registration.get("status"),
                "unit_count": dft_hardware_raw_registration.get("unit_count"),
                "registered_unit_count": dft_hardware_raw_registration.get("registered_unit_count"),
                "blocked_unit_count": dft_hardware_raw_registration.get("blocked_unit_count"),
                "registered_raw_stage_evidence_file_count": dft_hardware_raw_registration.get(
                    "registered_raw_stage_evidence_file_count"
                ),
                "present_raw_stage_evidence_file_count": dft_hardware_raw_registration.get(
                    "present_raw_stage_evidence_file_count"
                ),
                "missing_raw_stage_evidence_file_count": dft_hardware_raw_registration.get(
                    "missing_raw_stage_evidence_file_count"
                ),
                "invalid_raw_stage_evidence_file_count": dft_hardware_raw_registration.get(
                    "invalid_raw_stage_evidence_file_count"
                ),
                "adjudication_result": dft_hardware_raw_registration.get("adjudication_result"),
                "passed_stage_count": dft_hardware_raw_registration.get("passed_stage_count"),
                "hardware_completion_eligible": raw_registration_hardware_completion_eligible,
                "deliverable_complete": raw_registration_deliverable_complete,
                "validation": dft_hardware_raw_registration.get("validation"),
                "claim_boundary": dft_hardware_raw_registration.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure evidence intake is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_intake.get("present") is True
            and _mapping(dft_hardware_intake.get("validation")).get("valid") is True
            and not intake_hardware_completion_eligible
            and not intake_deliverable_complete
            and dft_hardware_intake.get("adjudication_status") == "not_adjudicated_by_intake"
            else "blocked",
            {
                "present": dft_hardware_intake.get("present"),
                "status": dft_hardware_intake.get("status"),
                "packet_count": dft_hardware_intake.get("packet_count"),
                "unit_count": dft_hardware_intake.get("unit_count"),
                "expected_evidence_file_count": dft_hardware_intake.get("expected_evidence_file_count"),
                "present_evidence_file_count": dft_hardware_intake.get("present_evidence_file_count"),
                "missing_evidence_file_count": dft_hardware_intake.get("missing_evidence_file_count"),
                "candidate_bundle_count": dft_hardware_intake.get("candidate_bundle_count"),
                "adjudication_status": dft_hardware_intake.get("adjudication_status"),
                "hardware_completion_eligible": intake_hardware_completion_eligible,
                "deliverable_complete": intake_deliverable_complete,
                "validation": dft_hardware_intake.get("validation"),
                "claim_boundary": dft_hardware_intake.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure adjudication ledger is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_adjudication.get("present") is True
            and _mapping(dft_hardware_adjudication.get("validation")).get("valid") is True
            and not adjudication_hardware_completion_eligible
            and not adjudication_deliverable_complete
            and dft_hardware_adjudication.get("adjudication_result") == "not_adjudicated"
            and int(dft_hardware_adjudication.get("passed_stage_count", 0) or 0) == 0
            else "blocked",
            {
                "present": dft_hardware_adjudication.get("present"),
                "status": dft_hardware_adjudication.get("status"),
                "packet_count": dft_hardware_adjudication.get("packet_count"),
                "unit_count": dft_hardware_adjudication.get("unit_count"),
                "stage_count": dft_hardware_adjudication.get("stage_count"),
                "passed_stage_count": dft_hardware_adjudication.get("passed_stage_count"),
                "blocked_stage_count": dft_hardware_adjudication.get("blocked_stage_count"),
                "files_present_unadjudicated_stage_count": dft_hardware_adjudication.get("files_present_unadjudicated_stage_count"),
                "expected_evidence_file_count": dft_hardware_adjudication.get("expected_evidence_file_count"),
                "present_evidence_file_count": dft_hardware_adjudication.get("present_evidence_file_count"),
                "missing_evidence_file_count": dft_hardware_adjudication.get("missing_evidence_file_count"),
                "candidate_bundle_count": dft_hardware_adjudication.get("candidate_bundle_count"),
                "adjudication_result": dft_hardware_adjudication.get("adjudication_result"),
                "hardware_completion_eligible": adjudication_hardware_completion_eligible,
                "deliverable_complete": adjudication_deliverable_complete,
                "validation": dft_hardware_adjudication.get("validation"),
                "claim_boundary": dft_hardware_adjudication.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure parsed-evidence manifest is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_parsed.get("present") is True
            and _mapping(dft_hardware_parsed.get("validation")).get("valid") is True
            and not parsed_hardware_completion_eligible
            and not parsed_deliverable_complete
            and dft_hardware_parsed.get("adjudication_result") == "not_adjudicated_by_parsed_manifest"
            and int(dft_hardware_parsed.get("passed_stage_count", 0) or 0) == 0
            else "blocked",
            {
                "present": dft_hardware_parsed.get("present"),
                "status": dft_hardware_parsed.get("status"),
                "packet_count": dft_hardware_parsed.get("packet_count"),
                "unit_count": dft_hardware_parsed.get("unit_count"),
                "stage_count": dft_hardware_parsed.get("stage_count"),
                "expected_parsed_result_count": dft_hardware_parsed.get("expected_parsed_result_count"),
                "present_parsed_result_count": dft_hardware_parsed.get("present_parsed_result_count"),
                "missing_parsed_result_count": dft_hardware_parsed.get("missing_parsed_result_count"),
                "valid_parsed_result_count": dft_hardware_parsed.get("valid_parsed_result_count"),
                "invalid_parsed_result_count": dft_hardware_parsed.get("invalid_parsed_result_count"),
                "parsed_verdict_counts": dft_hardware_parsed.get("parsed_verdict_counts"),
                "adjudication_result": dft_hardware_parsed.get("adjudication_result"),
                "passed_stage_count": dft_hardware_parsed.get("passed_stage_count"),
                "hardware_completion_eligible": parsed_hardware_completion_eligible,
                "deliverable_complete": parsed_deliverable_complete,
                "validation": dft_hardware_parsed.get("validation"),
                "claim_boundary": dft_hardware_parsed.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure parser run is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_parser_run.get("present") is True
            and _mapping(dft_hardware_parser_run.get("validation")).get("valid") is True
            and not parser_run_hardware_completion_eligible
            and not parser_run_deliverable_complete
            and dft_hardware_parser_run.get("adjudication_result") == "not_adjudicated_by_parser_run"
            and int(dft_hardware_parser_run.get("passed_stage_count", 0) or 0) == 0
            else "blocked",
            {
                "present": dft_hardware_parser_run.get("present"),
                "status": dft_hardware_parser_run.get("status"),
                "packet_count": dft_hardware_parser_run.get("packet_count"),
                "unit_count": dft_hardware_parser_run.get("unit_count"),
                "stage_count": dft_hardware_parser_run.get("stage_count"),
                "parsed_result_written_count": dft_hardware_parser_run.get("parsed_result_written_count"),
                "blocked_stage_count": dft_hardware_parser_run.get("blocked_stage_count"),
                "verdict_counts": dft_hardware_parser_run.get("verdict_counts"),
                "adjudication_result": dft_hardware_parser_run.get("adjudication_result"),
                "passed_stage_count": dft_hardware_parser_run.get("passed_stage_count"),
                "hardware_completion_eligible": parser_run_hardware_completion_eligible,
                "deliverable_complete": parser_run_deliverable_complete,
                "validation": dft_hardware_parser_run.get("validation"),
                "claim_boundary": dft_hardware_parser_run.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure gate adjudication is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_gate_adjudication.get("present") is True
            and _mapping(dft_hardware_gate_adjudication.get("validation")).get("valid") is True
            and not gate_adjudication_hardware_completion_eligible
            and not gate_adjudication_deliverable_complete
            else "blocked",
            {
                "present": dft_hardware_gate_adjudication.get("present"),
                "status": dft_hardware_gate_adjudication.get("status"),
                "packet_count": dft_hardware_gate_adjudication.get("packet_count"),
                "unit_count": dft_hardware_gate_adjudication.get("unit_count"),
                "stage_count": dft_hardware_gate_adjudication.get("stage_count"),
                "stage_gate_passed_count": dft_hardware_gate_adjudication.get("stage_gate_passed_count"),
                "blocked_stage_count": dft_hardware_gate_adjudication.get("blocked_stage_count"),
                "failed_stage_count": dft_hardware_gate_adjudication.get("failed_stage_count"),
                "unit_gate_passed_count": dft_hardware_gate_adjudication.get("unit_gate_passed_count"),
                "blocked_unit_count": dft_hardware_gate_adjudication.get("blocked_unit_count"),
                "failed_unit_count": dft_hardware_gate_adjudication.get("failed_unit_count"),
                "adjudication_result": dft_hardware_gate_adjudication.get("adjudication_result"),
                "hardware_completion_eligible": gate_adjudication_hardware_completion_eligible,
                "deliverable_complete": gate_adjudication_deliverable_complete,
                "validation": dft_hardware_gate_adjudication.get("validation"),
                "claim_boundary": dft_hardware_gate_adjudication.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT hardware closure release gate is Step5-visible and fail-closed",
            "passed"
            if dft_hardware_release_gate.get("present") is True
            and _mapping(dft_hardware_release_gate.get("validation")).get("valid") is True
            and not release_gate_deliverable_complete
            and (
                not deliverable_complete
                or dft_hardware_release_gate.get("hardware_completion_eligible") is True
            )
            else "blocked",
            {
                "present": dft_hardware_release_gate.get("present"),
                "status": dft_hardware_release_gate.get("status"),
                "unit_count": dft_hardware_release_gate.get("unit_count"),
                "stage_count": dft_hardware_release_gate.get("stage_count"),
                "stage_gate_passed_count": dft_hardware_release_gate.get("stage_gate_passed_count"),
                "blocked_stage_count": dft_hardware_release_gate.get("blocked_stage_count"),
                "failed_stage_count": dft_hardware_release_gate.get("failed_stage_count"),
                "expected_unit_count": dft_hardware_release_gate.get("expected_unit_count"),
                "actual_unit_count": dft_hardware_release_gate.get("actual_unit_count"),
                "candidate_count_complete": dft_hardware_release_gate.get("candidate_count_complete"),
                "unit_count_complete": dft_hardware_release_gate.get("unit_count_complete"),
                "per_candidate_kernel_coverage_complete": dft_hardware_release_gate.get(
                    "per_candidate_kernel_coverage_complete"
                ),
                "unit_gate_passed_count": dft_hardware_release_gate.get("unit_gate_passed_count"),
                "blocked_unit_count": dft_hardware_release_gate.get("blocked_unit_count"),
                "failed_unit_count": dft_hardware_release_gate.get("failed_unit_count"),
                "candidate_gate_passed_count": dft_hardware_release_gate.get("candidate_gate_passed_count"),
                "blocked_candidate_count": dft_hardware_release_gate.get("blocked_candidate_count"),
                "failed_candidate_count": dft_hardware_release_gate.get("failed_candidate_count"),
                "release_gate_result": dft_hardware_release_gate.get("release_gate_result"),
                "hardware_completion_eligible": dft_hardware_release_gate.get("hardware_completion_eligible"),
                "hardware_eligibility_blockers": release_hardware_blockers,
                "deliverable_completion_blockers": release_deliverable_blockers,
                "candidate_kernel_blockers": release_candidate_kernel_blockers,
                "unit_stage_blockers": release_unit_stage_blockers,
                "detail_source": release_gate_details.get("detail_source"),
                "deliverable_complete": release_gate_deliverable_complete,
                "validation": dft_hardware_release_gate.get("validation"),
                "claim_boundary": dft_hardware_release_gate.get("claim_boundary"),
            },
        ),
        _status_item(
            "DFT L4/gem5 goal binding artifact is Step5-visible and fail-closed",
            "passed"
            if dft_l4_goal_binding.get("present") is True
            and l4_goal_binding_validation.get("valid") is True
            and dft_l4_goal_binding.get("l4_software_visible_proof_present") is True
            and not l4_goal_binding_deliverable_complete
            else "blocked",
            {
                "present": dft_l4_goal_binding.get("present"),
                "status": dft_l4_goal_binding.get("status"),
                "binding_status": dft_l4_goal_binding.get("binding_status"),
                "l4_software_visible_proof_present": dft_l4_goal_binding.get(
                    "l4_software_visible_proof_present"
                ),
                "final_closure_eligible": l4_goal_binding_final_closure_eligible,
                "deliverable_complete": l4_goal_binding_deliverable_complete,
                "l4_matrix": dft_l4_goal_binding.get("l4_matrix"),
                "row_level_proofs": dft_l4_goal_binding.get("row_level_proofs"),
                "validation": dft_l4_goal_binding.get("validation"),
                "blockers": dft_l4_goal_binding.get("blockers"),
                "claim_boundary": dft_l4_goal_binding.get("claim_boundary"),
            },
        ),
        _status_item(
            "L4/gem5 proof is explicitly bound to current DFT candidates and workloads",
            "passed"
            if dft_l4_goal_binding.get("present") is True
            and l4_goal_binding_validation.get("valid") is True
            and l4_current_goal_binding.get("current_goal_l4_bound") is True
            and l4_goal_binding_final_closure_eligible
            and not l4_goal_binding_deliverable_complete
            else "blocked",
            {
                "present": dft_l4_goal_binding.get("present"),
                "binding_status": dft_l4_goal_binding.get("binding_status"),
                "candidate_mapping_policy": l4_current_goal_binding.get("candidate_mapping_policy"),
                "workload_mapping_policy": l4_current_goal_binding.get("workload_mapping_policy"),
                "step5_candidate_count": l4_current_goal_binding.get("step5_candidate_count"),
                "candidate_crosswalk_count": l4_current_goal_binding.get("candidate_crosswalk_count"),
                "candidate_structured_crosswalk_count": l4_current_goal_binding.get(
                    "candidate_structured_crosswalk_count"
                ),
                "candidate_identity_binding_explicit": l4_current_goal_binding.get(
                    "candidate_identity_binding_explicit"
                ),
                "candidate_keys_exact": l4_current_goal_binding.get("candidate_keys_exact"),
                "mapped_l4_candidates_unique": l4_current_goal_binding.get("mapped_l4_candidates_unique"),
                "workload_crosswalk_count": l4_current_goal_binding.get("workload_crosswalk_count"),
                "workload_structured_crosswalk_count": l4_current_goal_binding.get(
                    "workload_structured_crosswalk_count"
                ),
                "workload_identity_binding_explicit": l4_current_goal_binding.get(
                    "workload_identity_binding_explicit"
                ),
                "workload_keys_exact": l4_current_goal_binding.get("workload_keys_exact"),
                "current_goal_l4_bound": l4_current_goal_binding.get("current_goal_l4_bound"),
                "final_closure_eligible": l4_goal_binding_final_closure_eligible,
                "claim_boundary": dft_l4_goal_binding.get("claim_boundary"),
            },
        ),
        _status_item(
            "Release claim gate allows deliverable_complete only after all required evidence closes",
            "passed" if deliverable_complete else "blocked",
            {
                "deliverable_complete": deliverable_complete,
                "release_claim_gate": release_claim_gate,
                "claim_boundary": dft_ledger.get("claim_boundary"),
            },
        ),
        _status_item(
            "Full-SCF evaluated-hybrid bundle is Step5-visible with all required artifacts",
            "passed"
            if dft_hybrid.get("present") is True and dft_hybrid.get("required_artifacts_present") is True
            else "blocked",
            {
                "present": dft_hybrid.get("present"),
                "status": dft_hybrid.get("status"),
                "source": dft_hybrid.get("source"),
                "required_artifacts_present": dft_hybrid.get("required_artifacts_present"),
            },
        ),
        _status_item(
            "Full-SCF hybrid report keeps evaluated-hybrid boundary and does not claim device-resident completion",
            "failed" if hybrid_completion_claim else "passed",
            {
                "prototype_boundary": dft_hybrid.get("prototype_boundary"),
                "device_residency": dft_hybrid.get("device_residency"),
                "completion_claim": hybrid_completion_claim,
                "numerical_correctness_claim_eligible": hybrid_numerical_claim,
                "ppa_claim_eligible": hybrid_ppa_claim,
            },
        ),
        _status_item(
            "Step5 reports kernel and end-to-end full-SCF cost fields",
            "passed" if hybrid_costs.get("required_cost_fields_present") is True else "blocked",
            {
                "source": hybrid_costs.get("source"),
                "required_cost_fields_present": hybrid_costs.get("required_cost_fields_present"),
                "kernel_speedup": hybrid_costs.get("kernel_speedup"),
                "end_to_end_scf_speedup": hybrid_costs.get("end_to_end_scf_speedup"),
            },
        ),
        _status_item(
            "Major-kernel hardware evidence matrix is trusted and attached",
            "passed" if eda_summary.get("major_kernel_matrix_trusted") is True else "blocked",
            {
                "major_kernel_matrix_status": eda_summary.get("major_kernel_matrix_status"),
                "major_kernel_matrix_trusted": eda_summary.get("major_kernel_matrix_trusted"),
                "dft_hardware_evidence_matrix": eda_summary.get("dft_hardware_evidence_matrix"),
            },
        ),
        _status_item(
            "FPGA/ASIC hardware completion gate is eligible only after full per-kernel hard evidence",
            "passed"
            if eda_summary.get("hardware_completion_eligible") is True
            or current_release_hardware_completion_eligible
            else "blocked",
            {
                "hardware_completion_eligible": (
                    bool(eda_summary.get("hardware_completion_eligible", False))
                    or current_release_hardware_completion_eligible
                ),
                "dft_ledger_hardware_completion_eligible": eda_summary.get("hardware_completion_eligible"),
                "current_release_gate_hardware_completion_eligible": current_release_hardware_completion_eligible,
                "current_release_gate_stage_gate_passed_count": dft_hardware_release_gate.get(
                    "stage_gate_passed_count"
                ),
                "current_release_gate_unit_gate_passed_count": dft_hardware_release_gate.get(
                    "unit_gate_passed_count"
                ),
                "current_release_gate_candidate_gate_passed_count": dft_hardware_release_gate.get(
                    "candidate_gate_passed_count"
                ),
                "hardware_eligibility_blockers": release_hardware_blockers,
                "candidate_kernel_blockers": release_candidate_kernel_blockers,
                "unit_stage_blockers": release_unit_stage_blockers,
                "tool_availability_status": eda_summary.get("tool_availability_status"),
                "claim_boundary": eda_summary.get("claim_boundary"),
            },
        ),
        _status_item(
            "Step5 trusted winner is not upgraded while DFT deliverable completion is false",
            "failed" if trusted_winner and not deliverable_complete else "passed",
            {
                "trusted_winner": trusted_winner,
                "deliverable_complete": deliverable_complete,
                "selection_status": selected.get("selection_status"),
            },
        ),
    ]

    failed = [item for item in checklist if item["status"] == "failed"]
    in_progress = [item for item in checklist if item["status"] == "in_progress"]
    blocked = [item for item in checklist if item["status"] == "blocked"]
    status = "failed" if failed else "in_progress" if in_progress or blocked else "complete"
    if status == "complete":
        decision = "ready_to_mark_complete"
    elif failed:
        decision = "do_not_mark_complete_failed_requirements"
    elif in_progress:
        decision = "do_not_mark_complete_before_date_horizon"
    else:
        decision = "do_not_mark_complete_blocked_or_incomplete"

    return {
        "schema_version": AUDIT_SCHEMA,
        "checked_at_date_command": _date_text(),
        "status": status,
        "completion_decision": decision,
        "horizon_reached": horizon_reached,
        "final_report": str(report_path),
        "prompt_to_artifact_checklist": checklist,
        "failed_requirements": failed,
        "blocked_requirements": blocked,
        "in_progress_requirements": in_progress,
        "hardware_eligibility_blockers": release_hardware_blockers,
        "deliverable_completion_blockers": release_deliverable_blockers,
        "summary": {
            "deliverable_complete": deliverable_complete,
            "trusted_winner": trusted_winner,
            "full_scf_hybrid_present": dft_hybrid.get("present") is True,
            "dft_trial_state_ledger_present": dft_trial_ledger.get("present") is True,
            "dft_candidate_binding_map_present": dft_candidate_binding.get("present") is True,
            "dft_hardware_completion_workplan_present": dft_hardware_workplan.get("present") is True,
            "dft_hardware_closure_shards_present": dft_hardware_shards.get("present") is True,
            "dft_hardware_closure_packets_present": dft_hardware_packets.get("present") is True,
            "dft_hardware_closure_candidate_bundles_present": dft_hardware_bundles.get("present") is True,
            "dft_hardware_closure_unit_provenance_present": dft_hardware_unit_provenance.get("present") is True,
            "dft_hardware_closure_raw_stage_materialization_present": (
                dft_hardware_raw_materialization.get("present") is True
            ),
            "dft_hardware_closure_raw_transcript_registration_present": (
                dft_hardware_raw_registration.get("present") is True
            ),
            "dft_hardware_closure_evidence_intake_present": dft_hardware_intake.get("present") is True,
            "dft_hardware_closure_adjudication_present": dft_hardware_adjudication.get("present") is True,
            "dft_hardware_closure_parsed_evidence_present": dft_hardware_parsed.get("present") is True,
            "dft_hardware_closure_parser_run_present": dft_hardware_parser_run.get("present") is True,
            "dft_hardware_closure_gate_adjudication_present": dft_hardware_gate_adjudication.get("present") is True,
            "dft_hardware_closure_release_gate_present": dft_hardware_release_gate.get("present") is True,
            "dft_l4_goal_binding_present": dft_l4_goal_binding.get("present") is True,
            "dft_audit_semantic_closure_present": dft_audit_semantic_closure.get("present") is True,
            "dft_audit_semantic_closure_valid": dft_audit_semantic_closure.get("valid") is True,
            "dft_audit_semantic_closure_source_hash_backed": dft_audit_semantic_closure.get("source_hash_backed") is True,
            "l4_software_visible_proof_present": dft_l4_goal_binding.get("l4_software_visible_proof_present") is True,
            "current_goal_l4_bound": l4_current_goal_binding.get("current_goal_l4_bound") is True,
            "l4_goal_binding_final_closure_eligible": l4_goal_binding_final_closure_eligible,
            "ic_eda_availability_bridge_completion_claim": availability_completion_claim,
            "ic_eda_availability_kernel_ppa_evidence": availability_kernel_ppa_evidence,
            "ic_eda_availability_probe_present": availability_probe_present,
            "ic_eda_availability_raw_attempt_count": availability_raw_attempt_count,
            "ic_eda_availability_payload_claim_boundary_valid": availability_payload_boundary_valid,
            "major_kernel_matrix_trusted": eda_summary.get("major_kernel_matrix_trusted") is True,
            "hardware_completion_eligible": (
                eda_summary.get("hardware_completion_eligible") is True
                or current_release_hardware_completion_eligible
            ),
            "current_release_gate_hardware_completion_eligible": current_release_hardware_completion_eligible,
            "hardware_eligibility_blocker_count": len(release_hardware_blockers),
            "deliverable_completion_blocker_count": len(release_deliverable_blockers),
            "candidate_kernel_blocker_count": len(release_candidate_kernel_blockers),
            "unit_stage_blocker_count": len(release_unit_stage_blockers),
            "release_gate_detail_source": release_gate_details.get("detail_source"),
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--final-report", type=Path, default=None)
    parser.add_argument("--horizon-local", default=DEFAULT_HORIZON_LOCAL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--semantic-closure-path", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--allow-in-progress", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=args.run_dir,
        final_report=args.final_report,
        horizon_local=args.horizon_local,
        semantic_closure_path=args.semantic_closure_path,
    )
    if args.out:
        _write_json(args.out, audit)
    if not args.quiet:
        print(json.dumps(audit, indent=2, sort_keys=True))
    if audit["status"] == "complete":
        return 0
    if audit["status"] == "in_progress" and args.allow_in_progress:
        return 0
    return 3 if audit["status"] == "in_progress" else 2


if __name__ == "__main__":
    raise SystemExit(main())
