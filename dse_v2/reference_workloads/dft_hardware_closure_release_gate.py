#!/usr/bin/env python3
"""Release-level rollup for DFT/QE hardware closure gates.

This layer consumes ``dft_hardware_closure_gate_adjudication.json`` and rolls
per-stage/per-unit hard-gate verdicts up to candidate and release scope.  It is
the first layer that may mark ``hardware_completion_eligible=True``, but only
when every required candidate×kernel unit has passed all hard-gate stages with
no blocked or failed units.  It never marks ``deliverable_complete`` by itself;
the goal/release claim gate must still combine full-SCF, reporting, date, and
other evidence requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS

DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA = "dse.dft.hardware_closure_release_gate.v1"
DFT_HARDWARE_CLOSURE_RELEASE_GATE_VALIDATION_SCHEMA = "dse.dft.hardware_closure_release_gate_validation.v1"

_REQUIRED_STAGE_ORDER = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_release_gate.json rolls hard-gate adjudication up to "
    "candidate/release scope. It may set hardware_completion_eligible only when "
    "all required candidate×kernel unit gates pass, but it never marks "
    "deliverable_complete; final deliverable completion requires the separate "
    "goal/release claim gate."
)

_CANDIDATE_METADATA_FIELDS = (
    "design_candidate_id",
    "assignments",
    "identity_assignments",
    "non_identity_assignments",
    "applicability_assignments",
    "evaluation_policy_assignments",
)


def _load_json(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _default_evaluation_routing() -> Dict[str, Any]:
    return {
        "schema_version": "dse.dft.release_gate_evaluation_policy_routing.v1",
        "status": "not_attached",
        "routing_recorded": False,
        "routing_compatible": True,
        "evaluation_policy_id": None,
        "evaluation_policy_assignments": {},
        "promotion_requirements": [],
        "routing_blockers": [],
        "routing_blocker_count": 0,
        "affects_design_legality": False,
        "affects_design_score": False,
        "claim_eligibility_blocker": False,
        "claim_boundary": (
            "No evaluation-routing ledger was attached to the release gate. "
            "The release gate therefore preserves historical hard-gate behavior; "
            "when routing is attached, blockers affect claim eligibility only."
        ),
    }


def _normalise_evaluation_routing(raw_routing: Any) -> Dict[str, Any]:
    if not isinstance(raw_routing, Mapping):
        return _default_evaluation_routing()
    blockers = [
        dict(item)
        for item in raw_routing.get("routing_blockers", []) or []
        if isinstance(item, Mapping)
    ]
    routing_compatible = bool(raw_routing.get("routing_compatible", not blockers)) and not blockers
    evaluation_assignments = (
        raw_routing.get("evaluation_policy_assignments")
        if isinstance(raw_routing.get("evaluation_policy_assignments"), Mapping)
        else {}
    )
    promotion_requirements = raw_routing.get("promotion_requirements", [])
    if not isinstance(promotion_requirements, list):
        promotion_requirements = []
    return {
        "schema_version": "dse.dft.release_gate_evaluation_policy_routing.v1",
        "status": "compatible" if routing_compatible else "blocked_for_claim_eligibility",
        "routing_recorded": True,
        "routing_compatible": routing_compatible,
        "evaluation_policy_id": raw_routing.get("evaluation_policy_id"),
        "evaluation_policy_assignments": dict(evaluation_assignments),
        "promotion_requirements": [str(item) for item in promotion_requirements],
        "routing_blockers": blockers,
        "routing_blocker_count": len(blockers),
        "affects_design_legality": False,
        "affects_design_score": False,
        "claim_eligibility_blocker": not routing_compatible,
        "claim_boundary": (
            "Evaluation routing schedules or blocks evidence/promotion work. "
            "Routing blockers affect candidate/release claim eligibility only; "
            "they do not change design legality, design score, or stable design identity."
        ),
    }


def _evaluation_routing_by_candidate(
    *,
    gate: Mapping[str, Any],
    per_candidate_evidence_ledger_path: Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Load candidate routing from an attached ledger or gate rows."""

    routing_by_candidate: Dict[str, Dict[str, Any]] = {}
    ledger = _load_json(per_candidate_evidence_ledger_path) if per_candidate_evidence_ledger_path else {}
    for row in ledger.get("rows", []) or []:
        if isinstance(row, Mapping) and row.get("candidate_id"):
            routing_by_candidate[str(row["candidate_id"])] = _normalise_evaluation_routing(
                row.get("evaluation_policy_routing")
            )
    embedded = gate.get("evaluation_policy_routing_by_candidate", {})
    if isinstance(embedded, Mapping):
        for candidate_id, routing in embedded.items():
            routing_by_candidate.setdefault(
                str(candidate_id),
                _normalise_evaluation_routing(routing),
            )
    for row in gate.get("unit_rows", []) or []:
        if isinstance(row, Mapping) and row.get("candidate_id") and row.get("evaluation_policy_routing"):
            routing_by_candidate.setdefault(
                str(row["candidate_id"]),
                _normalise_evaluation_routing(row.get("evaluation_policy_routing")),
            )
    return routing_by_candidate


def _evaluation_routing_summary(candidate_rows: list[Mapping[str, Any]]) -> Dict[str, Any]:
    blocked_ids = [
        str(row.get("candidate_id"))
        for row in candidate_rows
        if isinstance(row.get("evaluation_policy_routing", {}), Mapping)
        and row["evaluation_policy_routing"].get("routing_compatible") is not True
    ]
    blocker_rows = [
        {
            "candidate_id": str(row.get("candidate_id")),
            "routing_blockers": list(row["evaluation_policy_routing"].get("routing_blockers", []) or []),
            "affects_design_legality": False,
        }
        for row in candidate_rows
        if isinstance(row.get("evaluation_policy_routing", {}), Mapping)
        and row["evaluation_policy_routing"].get("routing_blockers")
    ]
    return {
        "schema_version": "dse.dft.release_gate_evaluation_policy_routing_summary.v1",
        "candidate_count": len(candidate_rows),
        "routing_recorded_candidate_count": sum(
            1
            for row in candidate_rows
            if isinstance(row.get("evaluation_policy_routing", {}), Mapping)
            and row["evaluation_policy_routing"].get("routing_recorded") is True
        ),
        "routing_compatible_candidate_count": sum(
            1
            for row in candidate_rows
            if isinstance(row.get("evaluation_policy_routing", {}), Mapping)
            and row["evaluation_policy_routing"].get("routing_compatible") is True
        ),
        "routing_blocked_candidate_count": len(blocked_ids),
        "routing_blocked_candidate_ids": blocked_ids,
        "routing_blocker_count": sum(len(row["routing_blockers"]) for row in blocker_rows),
        "routing_blocker_rows": blocker_rows,
        "affects_design_legality": False,
        "affects_design_score": False,
        "claim_boundary": (
            "Evaluation-routing blockers are release/candidate claim blockers "
            "only. They do not rewrite candidate hardware-gate pass/fail facts "
            "or design-legality decisions."
        ),
    }


def _expected_kernel_ids(gate: Mapping[str, Any], unit_rows: list[Mapping[str, Any]]) -> list[str]:
    """Return the most specific expected kernel id list available.

    The release gate must preserve strict ``candidate_count * kernel_count``
    semantics, but older upstream artifacts sometimes carry only
    ``major_kernel_count``.  Prefer explicit artifact lists; fall back to the
    canonical eight DFT accelerated kernels only when the count says this is the
    all-kernel closure.  For smaller filtered closure runs, use observed kernel
    ids only when they exactly satisfy the declared count so one-kernel smoke
    closures are not reinterpreted as the first canonical kernel.
    """

    for field in ("major_kernel_ids", "kernel_ids", "required_kernel_ids"):
        explicit = _as_string_list(gate.get(field))
        if explicit:
            return sorted(set(explicit))
    expected_count = _as_int(gate.get("major_kernel_count"))
    observed = sorted({str(row.get("kernel_id", "")) for row in unit_rows if row.get("kernel_id")})
    if expected_count == len(MAJOR_SCF_KERNEL_IDS):
        return list(MAJOR_SCF_KERNEL_IDS)
    if expected_count > 0 and len(observed) == expected_count:
        return observed
    return observed


def _stage_reason(
    *,
    unit: Mapping[str, Any],
    stage_id: str,
    status: str,
    adjudication_result: str,
    blocker_id: str,
    parsed_verdict: Any = None,
    parsed_blocker_ids: Any = None,
) -> Dict[str, Any]:
    return {
        "unit_id": unit.get("unit_id"),
        "candidate_id": str(unit.get("candidate_id", "")),
        "kernel_id": str(unit.get("kernel_id", "")),
        "kernel_name": unit.get("kernel_name"),
        "stage_id": stage_id,
        "status": status,
        "adjudication_result": adjudication_result,
        "blocker_id": blocker_id,
        "reason": blocker_id or adjudication_result or status,
        "parsed_verdict": parsed_verdict,
        "parsed_blocker_ids": parsed_blocker_ids if isinstance(parsed_blocker_ids, list) else [],
    }


def _unit_stage_rollup(row: Mapping[str, Any]) -> Dict[str, Any]:
    stage_rows = row.get("stage_rows", [])
    stage_rows = stage_rows if isinstance(stage_rows, list) else []
    stage_maps = [stage for stage in stage_rows if isinstance(stage, Mapping)]
    stage_ids = [str(stage.get("stage_id", "")) for stage in stage_maps if stage.get("stage_id")]
    missing_stage_ids = [
        stage_id
        for stage_id in _REQUIRED_STAGE_ORDER
        if stage_maps and stage_id not in stage_ids
    ]
    non_passing_reasons: list[Dict[str, Any]] = []
    failed_stage_ids: list[str] = []
    blocked_stage_ids: list[str] = []
    for stage in stage_maps:
        if stage.get("stage_gate_passed") is True:
            continue
        stage_id = str(stage.get("stage_id", ""))
        adjudication_result = str(stage.get("adjudication_result", "") or "")
        blocker_id = str(stage.get("blocker_id", "") or "")
        reason = _stage_reason(
            unit=row,
            stage_id=stage_id,
            status=str(stage.get("status", "") or ""),
            adjudication_result=adjudication_result,
            blocker_id=blocker_id or "stage_gate_not_passed",
            parsed_verdict=stage.get("parsed_verdict"),
            parsed_blocker_ids=stage.get("parsed_blocker_ids"),
        )
        non_passing_reasons.append(reason)
        if adjudication_result == "failed_stage_gate":
            failed_stage_ids.append(stage_id)
        else:
            blocked_stage_ids.append(stage_id)
    for stage_id in missing_stage_ids:
        non_passing_reasons.append(
            _stage_reason(
                unit=row,
                stage_id=stage_id,
                status="blocked_missing_stage_row",
                adjudication_result="blocked_stage_gate",
                blocker_id="stage_row_missing",
            )
        )
        blocked_stage_ids.append(stage_id)
    if not stage_maps and not row.get("unit_gate_passed"):
        non_passing_reasons.append(
            _stage_reason(
                unit=row,
                stage_id="unknown",
                status=str(row.get("status", "") or "blocked_unit_gate"),
                adjudication_result=str(row.get("adjudication_result", "") or "blocked_unit_gate"),
                blocker_id=str(row.get("blocker_id", "") or "stage_rows_not_available"),
            )
        )
    return {
        "stage_rows_present": bool(stage_maps),
        "required_stage_ids": list(_REQUIRED_STAGE_ORDER),
        "observed_stage_ids": sorted(set(stage_ids)),
        "missing_stage_ids": missing_stage_ids,
        "failed_stage_ids": sorted(set(failed_stage_ids)),
        "blocked_stage_ids": sorted(set(blocked_stage_ids)),
        "non_passing_stage_reasons": non_passing_reasons,
    }


def _unit_rollup(row: Mapping[str, Any]) -> Dict[str, Any]:
    stage_rollup = _unit_stage_rollup(row)
    unit_gate_passed = bool(row.get("unit_gate_passed", False)) and not stage_rollup["non_passing_stage_reasons"]
    failed_stage_count = _as_int(row.get("failed_stage_count", 0))
    blocked_stage_count = _as_int(row.get("blocked_stage_count", 0))
    if stage_rollup["stage_rows_present"]:
        failed_stage_count = len(stage_rollup["failed_stage_ids"])
        blocked_stage_count = len(stage_rollup["blocked_stage_ids"])
    if row.get("adjudication_result") == "failed_unit_gate" or failed_stage_count:
        status = "failed_unit_gate"
        blocker_id = "unit_has_failed_stage_gate"
    elif unit_gate_passed:
        status = "unit_gate_passed"
        blocker_id = None
    else:
        status = "blocked_unit_gate"
        blocker_id = "unit_has_blocked_or_missing_stage_gates"
    return {
        "unit_id": row.get("unit_id"),
        "candidate_id": str(row.get("candidate_id", "")),
        **{
            field: (
                dict(row.get(field, {}))
                if isinstance(row.get(field), Mapping)
                else row.get(field)
            )
            for field in _CANDIDATE_METADATA_FIELDS
            if row.get(field) not in (None, {}, [])
        },
        "kernel_id": str(row.get("kernel_id", "")),
        "kernel_name": row.get("kernel_name"),
        "stage_count": int(row.get("stage_count", 0) or 0),
        "stage_gate_passed_count": int(row.get("stage_gate_passed_count", 0) or 0),
        "blocked_stage_count": blocked_stage_count,
        "failed_stage_count": failed_stage_count,
        "unit_gate_passed": unit_gate_passed,
        "status": status,
        "blocker_id": blocker_id,
        "stage_rows_present": stage_rollup["stage_rows_present"],
        "required_stage_ids": stage_rollup["required_stage_ids"],
        "observed_stage_ids": stage_rollup["observed_stage_ids"],
        "missing_stage_ids": stage_rollup["missing_stage_ids"],
        "failed_stage_ids": stage_rollup["failed_stage_ids"],
        "blocked_stage_ids": stage_rollup["blocked_stage_ids"],
        "non_passing_stage_reasons": stage_rollup["non_passing_stage_reasons"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _candidate_rollups(
    unit_rows: list[Dict[str, Any]],
    *,
    major_kernel_count: int | None = None,
    expected_kernel_ids: list[str] | None = None,
    evaluation_routing_by_candidate: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Dict[str, Any]]:
    evaluation_routing_by_candidate = evaluation_routing_by_candidate or {}
    grouped: Dict[str, list[Dict[str, Any]]] = {}
    for row in unit_rows:
        grouped.setdefault(str(row.get("candidate_id", "")), []).append(row)
    candidates: list[Dict[str, Any]] = []
    for candidate_id, rows in sorted(grouped.items()):
        metadata_source = rows[0] if rows else {}
        distinct_kernel_ids = sorted(str(row.get("kernel_id", "")) for row in rows)
        unique_kernel_ids = sorted(set(distinct_kernel_ids))
        expected_ids = sorted(set(expected_kernel_ids or []))
        duplicate_kernel_ids = sorted(
            kernel_id for kernel_id in set(distinct_kernel_ids) if distinct_kernel_ids.count(kernel_id) > 1
        )
        passed = sum(1 for row in rows if row.get("unit_gate_passed"))
        failed = sum(1 for row in rows if row.get("status") == "failed_unit_gate")
        blocked = sum(1 for row in rows if row.get("status") == "blocked_unit_gate")
        expected_kernel_count = int(major_kernel_count or 0)
        missing_kernel_ids = sorted(set(expected_ids) - set(unique_kernel_ids)) if expected_ids else []
        unknown_missing_kernel_count = (
            max(expected_kernel_count - len(unique_kernel_ids), 0)
            if expected_kernel_count > 0 and not expected_ids
            else 0
        )
        kernel_coverage_complete = (
            not duplicate_kernel_ids
            and (
                expected_kernel_count <= 0
                or (
                    len(unique_kernel_ids) == expected_kernel_count
                    and not missing_kernel_ids
                    and unknown_missing_kernel_count == 0
                )
            )
        )
        by_kernel: Dict[str, list[Dict[str, Any]]] = {}
        for row in rows:
            by_kernel.setdefault(str(row.get("kernel_id", "")), []).append(row)
        kernel_row_ids = sorted(set(unique_kernel_ids) | set(expected_ids))
        kernel_rows: list[Dict[str, Any]] = []
        candidate_kernel_blockers: list[Dict[str, Any]] = []
        for kernel_id in kernel_row_ids:
            kernel_units = by_kernel.get(kernel_id, [])
            if not kernel_units:
                kernel_row = {
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "unit_id": None,
                    "status": "missing_kernel_unit",
                    "unit_gate_passed": False,
                    "blocker_id": "candidate_kernel_unit_missing",
                    "non_passing_stage_reasons": [],
                }
                candidate_kernel_blockers.append(
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "unit_id": None,
                        "blocker_id": "candidate_kernel_unit_missing",
                        "reason": "expected candidate×kernel unit row is missing",
                    }
                )
            elif len(kernel_units) > 1:
                kernel_row = {
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "unit_id": [unit.get("unit_id") for unit in kernel_units],
                    "status": "duplicate_kernel_units",
                    "unit_gate_passed": False,
                    "blocker_id": "candidate_kernel_unit_duplicate",
                    "non_passing_stage_reasons": [],
                }
                candidate_kernel_blockers.append(
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "unit_id": [unit.get("unit_id") for unit in kernel_units],
                        "blocker_id": "candidate_kernel_unit_duplicate",
                        "reason": "candidate×kernel unit row appears more than once",
                    }
                )
            else:
                unit = kernel_units[0]
                kernel_row = {
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "unit_id": unit.get("unit_id"),
                    "status": unit.get("status"),
                    "unit_gate_passed": bool(unit.get("unit_gate_passed")),
                    "blocker_id": unit.get("blocker_id"),
                    "non_passing_stage_reasons": unit.get("non_passing_stage_reasons", []),
                }
                if unit.get("unit_gate_passed") is not True:
                    candidate_kernel_blockers.append(
                        {
                            "candidate_id": candidate_id,
                            "kernel_id": kernel_id,
                            "unit_id": unit.get("unit_id"),
                            "blocker_id": unit.get("blocker_id") or "candidate_kernel_unit_not_passed",
                            "reason": "candidate×kernel unit gate did not pass",
                            "non_passing_stage_reasons": unit.get("non_passing_stage_reasons", []),
                        }
                    )
            kernel_rows.append(kernel_row)
        if unknown_missing_kernel_count:
            candidate_kernel_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "kernel_id": None,
                    "unit_id": None,
                    "blocker_id": "candidate_kernel_coverage_incomplete_unknown_kernel_ids",
                    "reason": "declared major_kernel_count exceeds observed kernel ids but expected kernel ids were not provided",
                    "missing_kernel_count": unknown_missing_kernel_count,
                }
            )
        ready = (
            bool(rows)
            and passed == len(rows)
            and failed == 0
            and blocked == 0
            and kernel_coverage_complete
        )
        evaluation_routing = _normalise_evaluation_routing(
            evaluation_routing_by_candidate.get(candidate_id)
        )
        routing_compatible = evaluation_routing["routing_compatible"] is True
        claim_eligibility_blockers = [
            {
                "blocker_id": "candidate_evaluation_policy_routing_blocked",
                "reason": "evaluation policy routing blocks release/hardware claim eligibility",
                "routing_blockers": evaluation_routing["routing_blockers"],
                "affects_design_legality": False,
            }
        ] if not routing_compatible else []
        if failed:
            status = "failed_candidate_hardware_gate"
            blocker_id = "candidate_has_failed_unit_gate"
        elif ready:
            status = "candidate_hardware_gate_passed"
            blocker_id = None
        else:
            status = "blocked_candidate_hardware_gate"
            blocker_id = (
                "candidate_kernel_coverage_incomplete"
                if not kernel_coverage_complete
                else "candidate_has_blocked_unit_gates"
            )
        candidates.append(
            {
                "candidate_id": candidate_id,
                **{
                    field: (
                        dict(metadata_source.get(field, {}))
                        if isinstance(metadata_source.get(field), Mapping)
                        else metadata_source.get(field)
                    )
                    for field in _CANDIDATE_METADATA_FIELDS
                    if metadata_source.get(field) not in (None, {}, [])
                },
                "unit_count": len(rows),
                "kernel_ids": unique_kernel_ids,
                "expected_kernel_ids": expected_ids,
                "expected_kernel_count": expected_kernel_count or None,
                "distinct_kernel_count": len(unique_kernel_ids),
                "missing_kernel_ids": missing_kernel_ids,
                "missing_kernel_count": len(missing_kernel_ids) + unknown_missing_kernel_count,
                "duplicate_kernel_ids": duplicate_kernel_ids,
                "kernel_coverage_complete": kernel_coverage_complete,
                "unit_gate_passed_count": passed,
                "blocked_unit_count": blocked,
                "failed_unit_count": failed,
                "candidate_hardware_gate_passed": ready,
                "status": status,
                "blocker_id": blocker_id,
                "evaluation_policy_routing": evaluation_routing,
                "candidate_claim_eligible": bool(ready and routing_compatible),
                "claim_eligibility_blockers": claim_eligibility_blockers,
                "routing_affects_design_legality": False,
                "kernel_rows": kernel_rows,
                "candidate_kernel_blockers": candidate_kernel_blockers,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return candidates


def _release_coverage(
    unit_rows: list[Dict[str, Any]],
    candidate_rows: list[Dict[str, Any]],
    *,
    candidate_count: Any,
    major_kernel_count: Any,
) -> Dict[str, Any]:
    try:
        expected_candidate_count = int(candidate_count or 0)
    except (TypeError, ValueError):
        expected_candidate_count = 0
    try:
        expected_major_kernel_count = int(major_kernel_count or 0)
    except (TypeError, ValueError):
        expected_major_kernel_count = 0
    expected_unit_count = (
        expected_candidate_count * expected_major_kernel_count
        if expected_candidate_count > 0 and expected_major_kernel_count > 0
        else None
    )
    seen_units: set[tuple[str, str]] = set()
    duplicate_units: list[Dict[str, str]] = []
    for row in unit_rows:
        key = (str(row.get("candidate_id", "")), str(row.get("kernel_id", "")))
        if key in seen_units:
            duplicate_units.append({"candidate_id": key[0], "kernel_id": key[1]})
        seen_units.add(key)
    candidate_ids = {str(row.get("candidate_id", "")) for row in candidate_rows if row.get("candidate_id")}
    candidates_with_incomplete_kernel_coverage = [
        str(row.get("candidate_id"))
        for row in candidate_rows
        if row.get("kernel_coverage_complete") is not True
    ]
    return {
        "expected_candidate_count": expected_candidate_count or None,
        "expected_major_kernel_count": expected_major_kernel_count or None,
        "expected_unit_count": expected_unit_count,
        "unit_count_semantics": "candidate_count*major_kernel_count",
        "strict_unit_count_required": expected_unit_count is not None,
        "actual_candidate_count": len(candidate_ids),
        "actual_unit_count": len(unit_rows),
        "duplicate_unit_count": len(duplicate_units),
        "duplicate_units": duplicate_units,
        "candidates_with_incomplete_kernel_coverage": candidates_with_incomplete_kernel_coverage,
        "candidate_count_complete": expected_candidate_count <= 0 or len(candidate_ids) == expected_candidate_count,
        "unit_count_complete": expected_unit_count is None or len(unit_rows) == expected_unit_count,
        "no_duplicate_units": not duplicate_units,
        "per_candidate_kernel_coverage_complete": not candidates_with_incomplete_kernel_coverage,
    }


def _release_ready(
    unit_rows: list[Dict[str, Any]],
    candidate_rows: list[Dict[str, Any]],
    coverage: Mapping[str, Any],
) -> bool:
    return (
        bool(unit_rows)
        and bool(candidate_rows)
        and coverage.get("candidate_count_complete") is True
        and coverage.get("unit_count_complete") is True
        and coverage.get("no_duplicate_units") is True
        and coverage.get("per_candidate_kernel_coverage_complete") is True
        and all(row.get("unit_gate_passed") for row in unit_rows)
        and all(row.get("candidate_hardware_gate_passed") for row in candidate_rows)
        and all(row.get("candidate_claim_eligible") for row in candidate_rows)
    )


def _hardware_eligibility_blockers(
    *,
    unit_rows: list[Dict[str, Any]],
    candidate_rows: list[Dict[str, Any]],
    coverage: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if not unit_rows:
        blockers.append({"blocker_id": "gate_adjudication_has_no_unit_rows", "reason": "no candidate×kernel unit rows are available"})
    if coverage.get("candidate_count_complete") is not True:
        blockers.append(
            {
                "blocker_id": "candidate_count_incomplete",
                "reason": "actual candidate count does not match declared candidate_count",
                "expected_candidate_count": coverage.get("expected_candidate_count"),
                "actual_candidate_count": coverage.get("actual_candidate_count"),
            }
        )
    if coverage.get("unit_count_complete") is not True:
        blockers.append(
            {
                "blocker_id": "unit_count_incomplete",
                "reason": "actual unit_count must equal candidate_count*major_kernel_count",
                "expected_unit_count": coverage.get("expected_unit_count"),
                "actual_unit_count": coverage.get("actual_unit_count"),
                "unit_count_semantics": coverage.get("unit_count_semantics"),
            }
        )
    if coverage.get("no_duplicate_units") is not True:
        blockers.append(
            {
                "blocker_id": "duplicate_candidate_kernel_units",
                "reason": "candidate×kernel unit rows must be unique",
                "duplicate_units": coverage.get("duplicate_units"),
            }
        )
    for candidate in candidate_rows:
        if candidate.get("candidate_hardware_gate_passed") is not True:
            blockers.append(
                {
                    "blocker_id": candidate.get("blocker_id") or "candidate_hardware_gate_not_passed",
                    "reason": "candidate hardware gate did not pass",
                    "candidate_id": candidate.get("candidate_id"),
                    "missing_kernel_ids": candidate.get("missing_kernel_ids"),
                    "missing_kernel_count": candidate.get("missing_kernel_count"),
                    "duplicate_kernel_ids": candidate.get("duplicate_kernel_ids"),
                    "blocked_unit_count": candidate.get("blocked_unit_count"),
                    "failed_unit_count": candidate.get("failed_unit_count"),
                }
            )
        if candidate.get("candidate_claim_eligible") is not True:
            blockers.extend(
                {
                    **dict(blocker),
                    "candidate_id": candidate.get("candidate_id"),
                }
                for blocker in candidate.get("claim_eligibility_blockers", []) or []
                if isinstance(blocker, Mapping)
            )
    return blockers


def _deliverable_completion_blockers(hardware_completion_eligible: bool) -> list[Dict[str, Any]]:
    blockers = [
        {
            "blocker_id": "release_gate_cannot_mark_deliverable_complete",
            "reason": "deliverable_complete remains owned by the separate goal/release claim gate",
        }
    ]
    if not hardware_completion_eligible:
        blockers.append(
            {
                "blocker_id": "hardware_completion_not_eligible",
                "reason": "hardware release gate has not passed all expected candidate×kernel hard gates",
            }
        )
    return blockers


def build_dft_hardware_closure_release_gate(
    *,
    gate_adjudication_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    """Return candidate/release closure rollup from hard-gate adjudication."""

    gate_path = Path(gate_adjudication_path)
    gate = _load_json(gate_path)
    unit_rows = [
        _unit_rollup(row)
        for row in gate.get("unit_rows", []) or []
        if isinstance(row, Mapping)
    ]
    expected_kernel_ids = _expected_kernel_ids(gate, unit_rows)
    evaluation_routing_by_candidate = _evaluation_routing_by_candidate(
        gate=gate,
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
    )
    candidate_rows = _candidate_rollups(
        unit_rows,
        major_kernel_count=gate.get("major_kernel_count"),
        expected_kernel_ids=expected_kernel_ids,
        evaluation_routing_by_candidate=evaluation_routing_by_candidate,
    )
    evaluation_policy_routing_summary = _evaluation_routing_summary(candidate_rows)
    coverage = _release_coverage(
        unit_rows,
        candidate_rows,
        candidate_count=gate.get("candidate_count"),
        major_kernel_count=gate.get("major_kernel_count"),
    )
    failed_unit_count = sum(1 for row in unit_rows if row.get("status") == "failed_unit_gate")
    blocked_unit_count = sum(1 for row in unit_rows if row.get("status") == "blocked_unit_gate")
    unit_gate_passed_count = sum(1 for row in unit_rows if row.get("unit_gate_passed"))
    candidate_gate_passed_count = sum(1 for row in candidate_rows if row.get("candidate_hardware_gate_passed"))
    hardware_completion_eligible = _release_ready(unit_rows, candidate_rows, coverage)
    hardware_blockers = _hardware_eligibility_blockers(
        unit_rows=unit_rows,
        candidate_rows=candidate_rows,
        coverage=coverage,
    )
    deliverable_blockers = _deliverable_completion_blockers(hardware_completion_eligible)
    if not unit_rows:
        status = "failed_empty_gate_adjudication"
        release_gate_result = "failed_empty_gate_adjudication"
    elif failed_unit_count:
        status = "failed_hardware_release_gate"
        release_gate_result = "failed_hardware_release_gate"
    elif hardware_completion_eligible:
        status = "hardware_release_gate_passed_pending_deliverable_claim"
        release_gate_result = "hardware_completion_eligible_pending_deliverable_claim"
    else:
        status = "blocked_incomplete_hardware_release_gate"
        release_gate_result = "blocked_incomplete_hardware_release_gate"
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA,
        "status": status,
        "source_artifacts": {
            "gate_adjudication": _source_ref(gate_path),
            "per_candidate_evidence_ledger": (
                _source_ref(per_candidate_evidence_ledger_path)
                if per_candidate_evidence_ledger_path is not None
                else {
                    "path": None,
                    "exists": False,
                    "sha256": None,
                    "hash_algorithm": "sha256",
                    "status": "not_attached",
                }
            ),
        },
        "release_id": gate.get("release_id"),
        "candidate_count": gate.get("candidate_count"),
        "major_kernel_count": gate.get("major_kernel_count"),
        "expected_kernel_ids": expected_kernel_ids,
        "packet_count": gate.get("packet_count"),
        "unit_count": len(unit_rows),
        "stage_count": gate.get("stage_count"),
        "stage_gate_passed_count": gate.get("stage_gate_passed_count"),
        "blocked_stage_count": gate.get("blocked_stage_count"),
        "failed_stage_count": gate.get("failed_stage_count"),
        "expected_unit_count": coverage.get("expected_unit_count"),
        "unit_count_semantics": coverage.get("unit_count_semantics"),
        "strict_unit_count_required": coverage.get("strict_unit_count_required"),
        "actual_unit_count": coverage.get("actual_unit_count"),
        "duplicate_unit_count": coverage.get("duplicate_unit_count"),
        "duplicate_units": coverage.get("duplicate_units"),
        "candidate_count_complete": coverage.get("candidate_count_complete"),
        "unit_count_complete": coverage.get("unit_count_complete"),
        "per_candidate_kernel_coverage_complete": coverage.get("per_candidate_kernel_coverage_complete"),
        "candidates_with_incomplete_kernel_coverage": coverage.get("candidates_with_incomplete_kernel_coverage"),
        "unit_gate_passed_count": unit_gate_passed_count,
        "blocked_unit_count": blocked_unit_count,
        "failed_unit_count": failed_unit_count,
        "candidate_gate_passed_count": candidate_gate_passed_count,
        "blocked_candidate_count": sum(1 for row in candidate_rows if row.get("status") == "blocked_candidate_hardware_gate"),
        "failed_candidate_count": sum(1 for row in candidate_rows if row.get("status") == "failed_candidate_hardware_gate"),
        "release_gate_result": release_gate_result,
        "hardware_completion_eligible": hardware_completion_eligible,
        "deliverable_complete": False,
        "evaluation_policy_routing_summary": evaluation_policy_routing_summary,
        "routing_blocker_count": evaluation_policy_routing_summary["routing_blocker_count"],
        "routing_blocked_candidate_ids": evaluation_policy_routing_summary["routing_blocked_candidate_ids"],
        "hardware_eligibility_blockers": hardware_blockers,
        "deliverable_completion_blockers": deliverable_blockers,
        "candidate_kernel_blockers": [
            blocker
            for candidate in candidate_rows
            for blocker in candidate.get("candidate_kernel_blockers", [])
        ],
        "unit_stage_blockers": [
            reason
            for unit in unit_rows
            for reason in unit.get("non_passing_stage_reasons", [])
        ],
        "candidate_rows": candidate_rows,
        "unit_rows": unit_rows,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_release_gate(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected release gate schema"})
    units = payload.get("unit_rows", [])
    candidates = payload.get("candidate_rows", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "unit_rows", "message": "non-empty unit rows required"})
        units = []
    if not isinstance(candidates, list) or not candidates:
        errors.append({"field": "candidate_rows", "message": "non-empty candidate rows required"})
        candidates = []
    if payload.get("deliverable_complete") is True:
        errors.append({"field": "deliverable_complete", "message": "release gate cannot directly mark deliverable_complete"})
    unit_passed = sum(1 for row in units if isinstance(row, Mapping) and row.get("unit_gate_passed"))
    unit_failed = sum(1 for row in units if isinstance(row, Mapping) and row.get("status") == "failed_unit_gate")
    unit_blocked = sum(1 for row in units if isinstance(row, Mapping) and row.get("status") == "blocked_unit_gate")
    candidate_passed = sum(1 for row in candidates if isinstance(row, Mapping) and row.get("candidate_hardware_gate_passed"))
    if int(payload.get("unit_gate_passed_count", 0) or 0) != unit_passed:
        errors.append({"field": "unit_gate_passed_count", "message": "unit pass count does not match rows"})
    if int(payload.get("blocked_unit_count", 0) or 0) != unit_blocked:
        errors.append({"field": "blocked_unit_count", "message": "blocked unit count does not match rows"})
    if int(payload.get("failed_unit_count", 0) or 0) != unit_failed:
        errors.append({"field": "failed_unit_count", "message": "failed unit count does not match rows"})
    if int(payload.get("candidate_gate_passed_count", 0) or 0) != candidate_passed:
        errors.append({"field": "candidate_gate_passed_count", "message": "candidate pass count does not match rows"})
    all_units_passed = bool(units) and unit_passed == len(units) and unit_failed == 0 and unit_blocked == 0
    all_candidates_passed = bool(candidates) and candidate_passed == len(candidates)
    all_candidate_claims_eligible = bool(candidates) and all(
        isinstance(row, Mapping)
        and row.get("candidate_claim_eligible") is True
        for row in candidates
    )
    coverage_complete = (
        payload.get("candidate_count_complete") is True
        and payload.get("unit_count_complete") is True
        and int(payload.get("duplicate_unit_count", 0) or 0) == 0
        and payload.get("per_candidate_kernel_coverage_complete") is True
    )
    if payload.get("hardware_completion_eligible") is True and not (
        all_units_passed
        and all_candidates_passed
        and all_candidate_claims_eligible
        and coverage_complete
    ):
        errors.append({"field": "hardware_completion_eligible", "message": "hardware completion eligibility requires every expected candidate×kernel unit to pass exactly once and every candidate claim to be routing-eligible"})
    if payload.get("hardware_completion_eligible") is False and all_units_passed and all_candidates_passed:
        if coverage_complete and all_candidate_claims_eligible:
            errors.append({"field": "hardware_completion_eligible", "message": "hardware completion eligibility must be true when every expected unit and candidate gate passes"})
    expected_unit_count = payload.get("expected_unit_count")
    if expected_unit_count is not None and int(expected_unit_count or 0) != len(units):
        if payload.get("unit_count_complete") is True:
            errors.append({"field": "unit_count_complete", "message": "unit_count_complete cannot be true when unit rows do not match expected_unit_count"})
    if expected_unit_count is not None:
        expected_candidate_count = _as_int(payload.get("candidate_count"))
        expected_major_kernel_count = _as_int(payload.get("major_kernel_count"))
        if expected_candidate_count > 0 and expected_major_kernel_count > 0:
            formula_count = expected_candidate_count * expected_major_kernel_count
            if int(expected_unit_count or 0) != formula_count:
                errors.append({"field": "expected_unit_count", "message": "expected_unit_count must equal candidate_count*major_kernel_count"})
        if int(payload.get("unit_count", 0) or 0) != len(units):
            errors.append({"field": "unit_count", "message": "unit_count must equal actual unit row count"})
    if payload.get("candidate_count") and int(payload.get("candidate_count") or 0) != len(candidates):
        if payload.get("candidate_count_complete") is True:
            errors.append({"field": "candidate_count_complete", "message": "candidate_count_complete cannot be true when candidate rows do not match candidate_count"})
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"unit_rows[{unit_index}]", "message": "unit row must be an object"})
            continue
        if unit.get("deliverable_complete") is True or unit.get("hardware_completion_eligible") is True:
            errors.append({"field": f"unit_rows[{unit_index}].completion_claim", "message": "unit rollup cannot upgrade completion claims"})
        if unit.get("unit_gate_passed") is True and unit.get("non_passing_stage_reasons"):
            errors.append({"field": f"unit_rows[{unit_index}].unit_gate_passed", "message": "unit pass cannot include non-passing stage reasons"})
    for candidate_index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            errors.append({"field": f"candidate_rows[{candidate_index}]", "message": "candidate row must be an object"})
            continue
        if candidate.get("deliverable_complete") is True or candidate.get("hardware_completion_eligible") is True:
            errors.append({"field": f"candidate_rows[{candidate_index}].completion_claim", "message": "candidate rollup cannot upgrade completion claims"})
        unit_count = int(candidate.get("unit_count", 0) or 0)
        passed_count = int(candidate.get("unit_gate_passed_count", 0) or 0)
        blocked_count = int(candidate.get("blocked_unit_count", 0) or 0)
        failed_count = int(candidate.get("failed_unit_count", 0) or 0)
        candidate_ready = bool(candidate.get("candidate_hardware_gate_passed", False))
        if candidate_ready and (not unit_count or passed_count != unit_count or blocked_count or failed_count):
            errors.append({"field": f"candidate_rows[{candidate_index}].candidate_hardware_gate_passed", "message": "candidate pass requires all units to pass"})
        if candidate_ready and candidate.get("kernel_coverage_complete") is not True:
            errors.append({"field": f"candidate_rows[{candidate_index}].kernel_coverage_complete", "message": "candidate pass requires complete per-kernel coverage"})
        if candidate_ready and candidate.get("candidate_kernel_blockers"):
            errors.append({"field": f"candidate_rows[{candidate_index}].candidate_kernel_blockers", "message": "candidate pass cannot include kernel blockers"})
        routing = candidate.get("evaluation_policy_routing", {})
        routing_compatible = not isinstance(routing, Mapping) or routing.get("routing_compatible") is True
        if candidate.get("candidate_claim_eligible") is True and not candidate_ready:
            errors.append({"field": f"candidate_rows[{candidate_index}].candidate_claim_eligible", "message": "claim eligibility requires candidate hardware gate pass"})
        if candidate.get("candidate_claim_eligible") is True and not routing_compatible:
            errors.append({"field": f"candidate_rows[{candidate_index}].candidate_claim_eligible", "message": "claim eligibility cannot be true while evaluation routing is blocked"})
        if isinstance(routing, Mapping) and routing.get("affects_design_legality") is not False:
            errors.append({"field": f"candidate_rows[{candidate_index}].evaluation_policy_routing.affects_design_legality", "message": "evaluation routing must not affect design legality"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RELEASE_GATE_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "candidate_count": len(candidates),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_release_gate(
    out_dir: Path,
    *,
    gate_adjudication_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_release_gate(
        gate_adjudication_path=gate_adjudication_path,
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
    )
    write_json(out_dir / "dft_hardware_closure_release_gate.json", payload)
    validation = validate_dft_hardware_closure_release_gate(payload)
    write_json(out_dir / "dft_hardware_closure_release_gate_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_release_gate_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "release_gate": "dft_hardware_closure_release_gate.json",
        "validation": "dft_hardware_closure_release_gate_validation.json",
        "unit_count": payload["unit_count"],
        "unit_gate_passed_count": payload["unit_gate_passed_count"],
        "blocked_unit_count": payload["blocked_unit_count"],
        "failed_unit_count": payload["failed_unit_count"],
        "candidate_gate_passed_count": payload["candidate_gate_passed_count"],
        "release_gate_result": payload["release_gate_result"],
        "hardware_completion_eligible": payload["hardware_completion_eligible"],
        "deliverable_complete": False,
        "routing_blocker_count": payload["routing_blocker_count"],
        "routing_blocked_candidate_ids": payload["routing_blocked_candidate_ids"],
        "hardware_eligibility_blocker_count": len(payload.get("hardware_eligibility_blockers", []) or []),
        "deliverable_completion_blocker_count": len(payload.get("deliverable_completion_blockers", []) or []),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_release_gate_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RELEASE_GATE_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_release_gate",
    "validate_dft_hardware_closure_release_gate",
    "write_dft_hardware_closure_release_gate",
]
