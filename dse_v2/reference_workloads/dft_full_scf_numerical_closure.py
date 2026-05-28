#!/usr/bin/env python3
"""Shared fail-closed DFT full-SCF numerical closure helpers.

These helpers are used by both the DFT hardware deployment readiness artifact
and the final report so blocked full-SCF host+accelerator evidence produces the
same gate/workplan semantics everywhere.  They intentionally emit
provenance-only closure tasks and never upgrade final deployment claims.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES


def _string_list(value: Any) -> List[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def _unique_string_list(value: Any) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in _string_list(value):
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


_FULL_SCF_NUMERICAL_CLOSURE_CATEGORY_ACTIONS: Dict[str, str] = {
    "scope_and_schedule": (
        "Attach full-SCF host+accelerator end-to-end row evidence with "
        "comparison_scope=full_scf_host_accelerator_end_to_end, "
        "full_scf_schedule_consumed=true, and host_accelerator_end_to_end=true."
    ),
    "host_bound_cost_accounting": (
        "Populate host_bound_costs_s and set host_bound_costs_included=true so "
        "CPU-retained I/O, SCF control, convergence, diagonalization, mixing, "
        "and synchronization costs remain in the end-to-end model."
    ),
    "runtime_overhead_accounting": (
        "Populate runtime_overhead_costs_s with transfer, synchronization, "
        "layout-conversion, launch/proxy, and scheduling overheads."
    ),
    "accelerated_kernel_cost_coverage": (
        "Populate accelerated_kernel_costs_s and covered_accelerated_kernel_ids "
        "for every major claimed accelerated kernel."
    ),
    "trusted_runtime_accounting_source": (
        "Bind the row to a trusted runtime/accounting source and set "
        "trusted_accelerated_numeric_source=true."
    ),
    "execution_proof": (
        "Attach a passed execution proof for the candidate/class row and mark "
        "the row status/passed fields as passed only after the proof exists."
    ),
    "physical_metrics": (
        "Attach physical full-SCF metrics and tolerance checks, including total "
        "energy error and density residual, with force/stress metrics when the "
        "SCF class requires them."
    ),
    "suite_identity_coverage": (
        "Cover every strict SCF workload class for the candidate and remove "
        "missing/duplicate/superseded candidate-class rows."
    ),
    "other": (
        "Inspect the row/candidate blocker and attach the missing evidence "
        "before re-running the full-SCF numerical gate."
    ),
}


def _full_scf_numerical_blocker_category(blocker_id: str) -> str:
    if blocker_id in {
        "comparison_scope_not_full_scf_host_accelerator_end_to_end",
        "full_scf_schedule_consumed_not_true",
        "host_accelerator_end_to_end_not_true",
    }:
        return "scope_and_schedule"
    if blocker_id in {
        "host_bound_costs_included_not_true",
        "host_bound_costs_s_missing",
    }:
        return "host_bound_cost_accounting"
    if blocker_id == "runtime_overhead_costs_s_missing":
        return "runtime_overhead_accounting"
    if blocker_id in {
        "accelerated_kernel_costs_s_missing",
        "major_accelerated_kernels_not_all_covered",
    }:
        return "accelerated_kernel_cost_coverage"
    if (
        blocker_id == "trusted_accelerated_numeric_source_not_true"
        or blocker_id.startswith("row_untrusted_runtime_source")
    ):
        return "trusted_runtime_accounting_source"
    if blocker_id in {
        "row_missing_passed_execution_proof",
        "row_status_not_passed",
        "row_passed_flag_not_true",
        "candidate_status_not_passed",
        "candidate_passed_flag_not_true",
        "missing_real_full_scf_execution_proof",
    }:
        return "execution_proof"
    if blocker_id.startswith("required_physical_metric_missing"):
        return "physical_metrics"
    if blocker_id in {
        "not_all_strict_scf_rows_passed",
        "missing_strict_scf_class_rows",
        "duplicate_candidate_class_rows",
        "superseded_candidate_class_rows",
    }:
        return "suite_identity_coverage"
    if blocker_id.endswith("_mismatch") or blocker_id in {
        "blocker_count_nonzero_or_invalid",
        "row_records_not_list",
        "candidate_records_not_list",
        "missing_full_scf_row_records",
        "missing_full_scf_candidate_records",
        "missing_full_scf_candidate_ids",
        "strict_scf_class_ids_not_canonical_six",
        "row_record_non_object",
        "candidate_record_non_object",
        "candidate_ids_record_mismatch",
        "row_candidate_class_id_missing",
        "candidate_class_cartesian_coverage_mismatch",
    }:
        return "suite_identity_coverage"
    return "other"


def _split_full_scf_class_blocker(
    raw_blocker: Any,
    strict_classes: Sequence[str],
) -> Tuple[Optional[str], str]:
    blocker = str(raw_blocker)
    for class_id in strict_classes:
        prefix = f"{class_id}::"
        if blocker.startswith(prefix):
            return class_id, blocker[len(prefix):]
    return None, blocker


def _full_scf_required_physical_metrics(blocker_ids: Iterable[str]) -> List[str]:
    metrics: set[str] = set()
    prefix = "required_physical_metric_missing::"
    for blocker_id in blocker_ids:
        if blocker_id.startswith(prefix):
            metric = blocker_id[len(prefix):]
            if metric:
                metrics.add(metric)
    return sorted(metrics)


def _full_scf_count_value(payload: Mapping[str, Any], key: str) -> tuple[bool, int | None]:
    if key not in payload:
        return False, None
    value = payload.get(key)
    if type(value) is not int or value < 0:
        return False, None
    return True, value


def _full_scf_count_is_exact(payload: Mapping[str, Any], key: str, expected: int) -> bool:
    valid, value = _full_scf_count_value(payload, key)
    return valid and value == expected


def _full_scf_count_is_zero(payload: Mapping[str, Any], key: str) -> bool:
    return _full_scf_count_is_exact(payload, key, 0)


_TRUSTED_FULL_SCF_MEASUREMENT_SOURCE_KINDS = {
    "qe_full_scf_host_accelerator_runtime",
    "full_scf_host_accelerator_runtime",
    "validated_qe_full_scf_runtime",
}
_UNTRUSTED_FULL_SCF_SOURCE_MARKERS = {
    "fixture",
    "synthetic",
    "baseline",
    "timing_only",
    "step3",
    "model_only",
}


def _full_scf_row_source_trust_blockers(row: Mapping[str, Any]) -> List[str]:
    measurement_source = str(row.get("measurement_source") or "").strip()
    source_kind = str(
        row.get("measurement_source_kind")
        or row.get("runtime_source_kind")
        or measurement_source
    ).strip()
    lowered = source_kind.lower()
    blockers: List[str] = []
    if not source_kind or source_kind not in _TRUSTED_FULL_SCF_MEASUREMENT_SOURCE_KINDS:
        blockers.append(f"row_untrusted_runtime_source:{source_kind or 'missing'}")
    if any(marker in lowered for marker in _UNTRUSTED_FULL_SCF_SOURCE_MARKERS):
        blockers.append(f"row_untrusted_runtime_source:{source_kind}")
    return sorted(set(blockers))


def _full_scf_row_source_trusted(row: Mapping[str, Any]) -> bool:
    return not _full_scf_row_source_trust_blockers(row)


def _full_scf_row_record_passed(row: Mapping[str, Any]) -> bool:
    """Fail-closed passed predicate for full-SCF candidate/class rows."""

    return (
        row.get("passed") is True
        and row.get("status") == "passed"
        and row.get("trusted_accelerated_numeric_source") is True
        and _full_scf_row_source_trusted(row)
        and row.get("execution_proof_present") is True
        and not _string_list(row.get("blockers", []))
    )


def _full_scf_candidate_record_passed(record: Mapping[str, Any]) -> bool:
    """Fail-closed passed predicate for full-SCF candidate records."""

    return (
        record.get("passed") is True
        and record.get("status") == "passed"
        and record.get("trusted_accelerated_numeric_source") is True
        and not _string_list(record.get("blockers", []))
    )


def _full_scf_row_consistency_blockers(row: Mapping[str, Any]) -> List[str]:
    blockers = _string_list(row.get("blockers", []))
    if row.get("passed") is not True:
        blockers.append("row_passed_flag_not_true")
    if row.get("status") != "passed":
        blockers.append("row_status_not_passed")
    if row.get("trusted_accelerated_numeric_source") is not True:
        blockers.append("trusted_accelerated_numeric_source_not_true")
    blockers.extend(_full_scf_row_source_trust_blockers(row))
    if row.get("execution_proof_present") is not True:
        blockers.append("row_missing_passed_execution_proof")
    return sorted(set(blockers))


def _full_scf_candidate_consistency_blockers(candidate_record: Mapping[str, Any]) -> List[str]:
    blockers = _string_list(candidate_record.get("blockers", []))
    if candidate_record.get("passed") is not True:
        blockers.append("candidate_passed_flag_not_true")
    if candidate_record.get("status") != "passed":
        blockers.append("candidate_status_not_passed")
    if candidate_record.get("trusted_accelerated_numeric_source") is not True:
        blockers.append("trusted_accelerated_numeric_source_not_true")
    return sorted(set(blockers))


def _full_scf_numerical_gate_blockers(full_scf: Mapping[str, Any]) -> List[str]:
    """Return top-level consistency blockers; empty means the gate may pass.

    The gate is intentionally stricter than historical status-string checks:
    ``status == "passed"`` is only descriptive and cannot override
    ``passed: false``, blocked counts, blockers, or untrusted accelerated
    numerical sources.
    """

    blockers = _string_list(full_scf.get("blockers", []))
    if not full_scf:
        blockers.append("missing_full_scf_end_to_end_comparison")
        return sorted(set(blockers))
    if full_scf.get("passed") is not True:
        blockers.append("full_scf_passed_flag_not_true")
    if full_scf.get("status") != "passed":
        blockers.append("full_scf_status_not_passed")
    if full_scf.get("trusted_accelerated_numeric_source") is not True:
        blockers.append("trusted_accelerated_numeric_source_not_true")
    candidate_ids = _unique_string_list(full_scf.get("candidate_ids", []))
    if not candidate_ids:
        blockers.append("missing_full_scf_candidate_ids")
    strict_class_ids = _unique_string_list(full_scf.get("strict_scf_class_ids", []))
    required_class_ids = list(STRICT_DFT_QE_WORKLOAD_CLASSES)
    if set(strict_class_ids) != set(required_class_ids) or len(strict_class_ids) != len(required_class_ids):
        blockers.append("strict_scf_class_ids_not_canonical_six")
    row_records = full_scf.get("row_records", [])
    if not isinstance(row_records, Sequence) or isinstance(row_records, (str, bytes)):
        blockers.append("row_records_not_list")
        row_records = []
    row_mappings = [row for row in row_records if isinstance(row, Mapping)]
    if len(row_mappings) != len(row_records):
        blockers.append("row_record_non_object")
    if not row_mappings:
        blockers.append("missing_full_scf_row_records")
    passed_row_count = sum(1 for row in row_mappings if _full_scf_row_record_passed(row))
    blocked_row_count = len(row_mappings) - passed_row_count
    if passed_row_count != len(row_mappings):
        blockers.append("row_record_not_passed")
    for key, expected in (
        ("row_record_count", len(row_mappings)),
        ("passed_row_record_count", passed_row_count),
        ("blocked_row_record_count", blocked_row_count),
    ):
        if not _full_scf_count_is_exact(full_scf, key, expected):
            blockers.append(f"{key}_mismatch")

    candidate_records = full_scf.get("candidate_records", [])
    if not isinstance(candidate_records, Sequence) or isinstance(candidate_records, (str, bytes)):
        blockers.append("candidate_records_not_list")
        candidate_records = []
    candidate_mappings = [
        candidate for candidate in candidate_records if isinstance(candidate, Mapping)
    ]
    if len(candidate_mappings) != len(candidate_records):
        blockers.append("candidate_record_non_object")
    if not candidate_mappings:
        blockers.append("missing_full_scf_candidate_records")
    candidate_record_ids = _unique_string_list([
        candidate.get("candidate_id")
        for candidate in candidate_mappings
        if candidate.get("candidate_id")
    ])
    if set(candidate_record_ids) != set(candidate_ids) or len(candidate_record_ids) != len(candidate_ids):
        blockers.append("candidate_ids_record_mismatch")
    passed_candidate_count = sum(
        1 for candidate in candidate_mappings if _full_scf_candidate_record_passed(candidate)
    )
    blocked_candidate_count = len(candidate_mappings) - passed_candidate_count
    if passed_candidate_count != len(candidate_mappings):
        blockers.append("candidate_record_not_passed")
    for key, expected in (
        ("candidate_count", len(candidate_mappings)),
        ("passed_candidate_count", passed_candidate_count),
        ("blocked_candidate_count", blocked_candidate_count),
    ):
        if not _full_scf_count_is_exact(full_scf, key, expected):
            blockers.append(f"{key}_mismatch")
    if not _full_scf_count_is_zero(full_scf, "blocker_count"):
        blockers.append("blocker_count_nonzero_or_invalid")
    row_pairs = [
        (str(row.get("candidate_id") or ""), str(row.get("class_id") or ""))
        for row in row_mappings
    ]
    if any(not candidate_id or not class_id for candidate_id, class_id in row_pairs):
        blockers.append("row_candidate_class_id_missing")
    if len(set(row_pairs)) != len(row_pairs):
        blockers.append("duplicate_candidate_class_rows")
    if candidate_ids and strict_class_ids:
        expected_pairs = {
            (candidate_id, class_id)
            for candidate_id in candidate_ids
            for class_id in strict_class_ids
        }
        actual_pairs = set(row_pairs)
        if actual_pairs != expected_pairs:
            blockers.append("candidate_class_cartesian_coverage_mismatch")

    return sorted(set(blockers))


def _full_scf_numerical_gate_passed(full_scf: Mapping[str, Any]) -> bool:
    return bool(full_scf) and not _full_scf_numerical_gate_blockers(full_scf)


def _full_scf_validation_artifact_passed(validation: Mapping[str, Any]) -> bool:
    return (
        bool(validation)
        and validation.get("valid") is True
        and validation.get("passed") is True
        and validation.get("status") == "passed"
        and not _string_list(validation.get("errors", []))
    )


def _full_scf_status_artifact_passed(
    status_artifact: Mapping[str, Any],
    comparison: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> bool:
    if not status_artifact:
        return False
    if status_artifact.get("schema_version") != "dse.dft.numerical.full_scf_end_to_end_comparison_status.v1":
        return False
    if status_artifact.get("status") != "comparison_passed":
        return False
    if status_artifact.get("comparison_status") != "passed":
        return False
    if status_artifact.get("comparison_passed") is not True:
        return False
    if status_artifact.get("validation_status") != "passed":
        return False
    if status_artifact.get("validation_passed") is not True:
        return False
    for forbidden_field in (
        "trusted_final_claim",
        "deliverable_complete",
        "hardware_completion_eligible",
        "release_completion_eligible",
        "numerical_correctness_claim_eligible",
    ):
        if status_artifact.get(forbidden_field) is True:
            return False
    for key in (
        "candidate_count",
        "row_record_count",
        "blocked_candidate_count",
        "blocked_row_record_count",
    ):
        if status_artifact.get(key) != comparison.get(key):
            return False
    if validation and status_artifact.get("validation_status") != validation.get("status"):
        return False
    return True


def _full_scf_numerical_closure_workplan(
    full_scf: Mapping[str, Any],
    *,
    artifact: Optional[str],
) -> Dict[str, Any]:
    """Convert failed full-SCF numerical rows into provenance-only closure tasks."""

    full_scf_present = bool(full_scf)
    full_scf_passed = _full_scf_numerical_gate_passed(full_scf)
    strict_classes = full_scf.get("strict_scf_class_ids", [])
    if not isinstance(strict_classes, Sequence) or isinstance(strict_classes, (str, bytes)):
        strict_classes = []
    strict_class_ids = [str(class_id) for class_id in strict_classes if str(class_id)]

    if full_scf_present and full_scf_passed:
        return {
            "schema_version": "dse.final_report.dft_full_scf_numerical_closure_workplan.v1",
            "status": "full_scf_numerical_closure_not_required",
            "required": False,
            "source_artifact": artifact,
            "work_item_count": 0,
            "candidate_work_item_count": 0,
            "class_row_work_item_count": 0,
            "blocker_category_counts": {},
            "work_items": [],
            "not_a_step3_queue": True,
            "provenance_only": True,
            "execution_allowed": False,
            "trusted_accelerated_numeric_source": False,
            "trusted_winner": False,
            "trusted_final_claim": False,
            "numerical_correctness_claim_eligible": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "No full-SCF numerical closure work items are emitted after the "
                "comparison artifact itself reports a passed gate."
            ),
        }

    grouped: Dict[str, Dict[str, Any]] = {}
    category_counts: Dict[str, int] = {}

    def ensure_candidate(candidate_id: Any) -> Dict[str, Any]:
        candidate_key = str(candidate_id) if candidate_id not in (None, "") else "unbound"
        if candidate_key not in grouped:
            grouped[candidate_key] = {
                "candidate_id": None if candidate_key == "unbound" else candidate_key,
                "candidate_blocker_ids": set(),
                "candidate_blocker_categories": set(),
                "class_ids": set(),
                "class_rows": [],
                "missing_accelerated_kernel_ids": set(),
                "required_physical_metrics": set(),
                "source_artifacts": set(),
            }
        return grouped[candidate_key]

    def record_blockers(
        target: Dict[str, Any],
        raw_blockers: Iterable[Any],
        *,
        class_id_hint: Optional[str] = None,
        candidate_level: bool = False,
    ) -> Tuple[List[str], List[str], List[str]]:
        blocker_ids: List[str] = []
        categories: List[str] = []
        class_ids: set[str] = set()
        for raw_blocker in raw_blockers:
            class_id, blocker_id = _split_full_scf_class_blocker(raw_blocker, strict_class_ids)
            effective_class_id = class_id or class_id_hint
            if effective_class_id:
                class_ids.add(str(effective_class_id))
                target["class_ids"].add(str(effective_class_id))
            if not blocker_id:
                continue
            blocker_ids.append(blocker_id)
            category = _full_scf_numerical_blocker_category(blocker_id)
            categories.append(category)
            target["candidate_blocker_ids"].add(blocker_id)
            target["candidate_blocker_categories"].add(category)
            category_counts[category] = category_counts.get(category, 0) + 1
            if candidate_level and effective_class_id:
                target["source_artifacts"].add(artifact or "full_scf_end_to_end_comparison.json")
        return sorted(set(blocker_ids)), sorted(set(categories)), sorted(class_ids)

    row_records = full_scf.get("row_records", [])
    if isinstance(row_records, Sequence) and not isinstance(row_records, (str, bytes)):
        for row in row_records:
            if not isinstance(row, Mapping):
                continue
            row_passed = _full_scf_row_record_passed(row)
            row_blockers = _full_scf_row_consistency_blockers(row)
            if row_passed and not row_blockers:
                continue
            if not row_blockers:
                row_blockers = ["row_status_not_passed"]
            candidate = ensure_candidate(row.get("candidate_id"))
            class_id = str(row.get("class_id")) if row.get("class_id") else None
            blocker_ids, categories, parsed_class_ids = record_blockers(
                candidate,
                row_blockers,
                class_id_hint=class_id,
            )
            effective_class_id = class_id or (parsed_class_ids[0] if parsed_class_ids else None)
            if effective_class_id:
                candidate["class_ids"].add(effective_class_id)
            missing_kernels = _unique_string_list(row.get("missing_accelerated_kernel_ids", []))
            for kernel_id in missing_kernels:
                candidate["missing_accelerated_kernel_ids"].add(kernel_id)
            for metric in _full_scf_required_physical_metrics(blocker_ids):
                candidate["required_physical_metrics"].add(metric)
            artifact_ref = row.get("artifact_ref", {}) if isinstance(row.get("artifact_ref", {}), Mapping) else {}
            artifact_path = artifact_ref.get("path")
            if artifact_path:
                candidate["source_artifacts"].add(str(artifact_path))
            candidate["class_rows"].append({
                "class_id": effective_class_id,
                "status": row.get("status"),
                "passed": row_passed,
                "blocker_ids": blocker_ids,
                "blocker_categories": categories,
                "required_physical_metrics": _full_scf_required_physical_metrics(blocker_ids),
                "missing_accelerated_kernel_ids": missing_kernels,
                "comparison_scope": row.get("comparison_scope"),
                "full_scf_schedule_consumed": row.get("full_scf_schedule_consumed"),
                "host_accelerator_end_to_end": row.get("host_accelerator_end_to_end"),
                "host_bound_costs_included": row.get("host_bound_costs_included"),
                "trusted_accelerated_numeric_source": row.get(
                    "trusted_accelerated_numeric_source"
                ),
                "execution_proof_present": row.get("execution_proof_present"),
                "measurement_source": row.get("measurement_source"),
                "measurement_source_kind": row.get("measurement_source_kind"),
                "row_evidence_root": row.get("row_evidence_root"),
                "artifact_ref": artifact_ref,
            })

    candidate_records = full_scf.get("candidate_records", [])
    if isinstance(candidate_records, Sequence) and not isinstance(candidate_records, (str, bytes)):
        for candidate_record in candidate_records:
            if not isinstance(candidate_record, Mapping):
                continue
            candidate_passed = _full_scf_candidate_record_passed(candidate_record)
            candidate_blockers = _full_scf_candidate_consistency_blockers(candidate_record)
            if candidate_passed and not candidate_blockers:
                continue
            if not candidate_blockers:
                candidate_blockers = ["candidate_status_not_passed"]
            candidate = ensure_candidate(candidate_record.get("candidate_id"))
            blocker_ids, _categories, parsed_class_ids = record_blockers(
                candidate,
                candidate_blockers,
                candidate_level=True,
            )
            for metric in _full_scf_required_physical_metrics(blocker_ids):
                candidate["required_physical_metrics"].add(metric)
            for class_id in parsed_class_ids:
                candidate["class_ids"].add(class_id)
            for kernel_id in _unique_string_list(
                candidate_record.get("missing_accelerated_kernel_ids", [])
            ):
                candidate["missing_accelerated_kernel_ids"].add(kernel_id)

    if not grouped and full_scf_present and not full_scf_passed:
        candidate = ensure_candidate(None)
        top_level_blockers = _full_scf_numerical_gate_blockers(full_scf) or [
            "full_scf_numerical_gate_not_passed"
        ]
        record_blockers(candidate, top_level_blockers, candidate_level=True)

    work_items: List[Dict[str, Any]] = []
    category_order = list(_FULL_SCF_NUMERICAL_CLOSURE_CATEGORY_ACTIONS)
    for candidate_key in sorted(grouped):
        candidate = grouped[candidate_key]
        categories = sorted(
            candidate["candidate_blocker_categories"],
            key=lambda category: (
                category_order.index(category) if category in category_order else len(category_order),
                category,
            ),
        )
        required_actions = [
            _FULL_SCF_NUMERICAL_CLOSURE_CATEGORY_ACTIONS[category]
            for category in categories
            if category in _FULL_SCF_NUMERICAL_CLOSURE_CATEGORY_ACTIONS
        ]
        work_items.append({
            "work_item_id": f"full-scf-numerical-closure::{candidate_key}",
            "candidate_id": candidate["candidate_id"],
            "status": "blocked_pending_full_scf_numerical_closure",
            "source_artifact": artifact,
            "class_ids": sorted(candidate["class_ids"]),
            "class_row_count": len(candidate["class_rows"]),
            "class_rows": sorted(
                candidate["class_rows"],
                key=lambda row: str(row.get("class_id") or ""),
            )[:12],
            "candidate_blocker_ids": sorted(candidate["candidate_blocker_ids"]),
            "blocker_categories": categories,
            "missing_accelerated_kernel_ids": sorted(candidate["missing_accelerated_kernel_ids"]),
            "required_physical_metrics": (
                sorted(candidate["required_physical_metrics"])
                or (
                    ["density_residual", "total_energy_error_ry"]
                    if "physical_metrics" in categories
                    else []
                )
            ),
            "required_evidence_fields": [
                "comparison_scope=full_scf_host_accelerator_end_to_end",
                "full_scf_schedule_consumed=true",
                "host_accelerator_end_to_end=true",
                "host_bound_costs_included=true",
                "host_bound_costs_s",
                "runtime_overhead_costs_s",
                "accelerated_kernel_costs_s",
                "covered_accelerated_kernel_ids",
                "trusted_accelerated_numeric_source=true",
                "execution_proof_present=true",
                "metric_checks",
            ],
            "required_artifacts": [
                "full_scf_runtime_schedule.json",
                "full_scf_end_to_end_numerical_evidence.json",
                "full_scf_end_to_end_comparison.json",
            ],
            "required_closure_actions": required_actions,
            "source_row_artifacts": sorted(candidate["source_artifacts"])[:12],
            "not_a_step3_queue_entry": True,
            "provenance_only": True,
            "execution_allowed": False,
            "trusted_accelerated_numeric_source": False,
            "trusted_winner": False,
            "trusted_final_claim": False,
            "numerical_correctness_claim_eligible": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "Full-SCF numerical closure work items are coordination/runbook "
                "records only. They do not execute tools, prove numerical "
                "correctness, or upgrade FPGA/ASIC/full-SCF claims."
            ),
        })

    class_row_work_item_count = sum(
        int(item.get("class_row_count", 0) or 0)
        for item in work_items
    )
    status = (
        "full_scf_numerical_closure_required"
        if work_items
        else "full_scf_numerical_closure_blocked_missing_comparison"
        if not full_scf_present
        else "full_scf_numerical_closure_required_no_candidate_rows"
    )
    return {
        "schema_version": "dse.final_report.dft_full_scf_numerical_closure_workplan.v1",
        "status": status,
        "required": bool(work_items) or not full_scf_present,
        "source_artifact": artifact,
        "work_item_count": len(work_items),
        "candidate_work_item_count": len([
            item for item in work_items if item.get("candidate_id")
        ]),
        "class_row_work_item_count": class_row_work_item_count,
        "blocker_category_counts": dict(sorted(category_counts.items())),
        "work_items": work_items,
        "not_a_step3_queue": True,
        "provenance_only": True,
        "execution_allowed": False,
        "trusted_accelerated_numeric_source": False,
        "trusted_winner": False,
        "trusted_final_claim": False,
        "numerical_correctness_claim_eligible": False,
        "hardware_completion_eligible": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "This workplan translates full-SCF host+accelerator numerical "
            "blockers into candidate/class-scoped closure tasks. It is not "
            "runtime evidence and cannot mark numerical correctness or "
            "deliverable completion by itself."
        ),
    }


def build_full_scf_numerical_readiness_sections(
    full_scf: Mapping[str, Any],
    *,
    validation: Mapping[str, Any] | None = None,
    status_artifact: Mapping[str, Any] | None = None,
    artifact: str | None,
    validation_artifact: str | None = None,
    status_artifact_path: str | None = None,
) -> Dict[str, Any]:
    """Build full-SCF gate, closure workplan, and release-gate sections.

    ``full_scf`` is the comparison artifact payload.  ``validation`` and
    ``status_artifact`` must also pass before the gate is considered passed;
    a self-asserted comparison ``status: passed`` is not sufficient.
    """

    validation = validation or {}
    status_artifact = status_artifact or {}
    full_scf_validation_passed = _full_scf_validation_artifact_passed(validation)
    full_scf_status_artifact_passed = _full_scf_status_artifact_passed(
        status_artifact,
        full_scf,
        validation,
    )
    comparison_artifact_passed = _full_scf_numerical_gate_passed(full_scf)
    full_scf_passed = (
        comparison_artifact_passed
        and full_scf_validation_passed
        and full_scf_status_artifact_passed
    )
    full_scf_for_workplan: Mapping[str, Any] = full_scf
    if full_scf and (not full_scf_validation_passed or not full_scf_status_artifact_passed):
        adjusted_full_scf = dict(full_scf)
        blockers = _string_list(adjusted_full_scf.get("blockers", []))
        if not full_scf_validation_passed:
            blockers.append("full_scf_comparison_validation_artifact_missing_or_failed")
        if not full_scf_status_artifact_passed:
            blockers.append("full_scf_comparison_status_artifact_missing_or_failed")
        adjusted_full_scf["blockers"] = sorted(set(blockers))
        adjusted_full_scf["blocker_count"] = len(adjusted_full_scf["blockers"])
        adjusted_full_scf["passed"] = False
        adjusted_full_scf["status"] = (
            "blocked_temporary"
            if adjusted_full_scf.get("status") == "passed"
            else adjusted_full_scf.get("status", "blocked_temporary")
        )
        full_scf_for_workplan = adjusted_full_scf
    full_scf_workplan = _full_scf_numerical_closure_workplan(
        full_scf_for_workplan,
        artifact=artifact,
    )
    return {
        "full_scf_numerical_gate": {
            "present": bool(full_scf),
            "artifact": artifact,
            "validation_artifact": validation_artifact,
            "status_artifact": status_artifact_path,
            "status": full_scf.get("status") if full_scf else "not_present",
            "passed": bool(full_scf_passed),
            "comparison_artifact_passed": bool(comparison_artifact_passed),
            "validation_passed": bool(full_scf_validation_passed),
            "validation_status": (
                validation.get("status")
                if validation
                else "missing_validation_artifact"
                if full_scf
                else "not_present"
            ),
            "status_artifact_status": status_artifact.get("status"),
            "status_artifact_passed": bool(full_scf_status_artifact_passed),
            "candidate_count": full_scf.get("candidate_count"),
            "passed_candidate_count": full_scf.get("passed_candidate_count"),
            "blocked_candidate_count": full_scf.get("blocked_candidate_count"),
            "row_record_count": full_scf.get("row_record_count"),
            "passed_row_record_count": full_scf.get("passed_row_record_count"),
            "blocked_row_record_count": full_scf.get("blocked_row_record_count"),
            "trusted_accelerated_numeric_source": bool(
                full_scf.get("trusted_accelerated_numeric_source", False)
            ),
            "claim_boundary": (
                full_scf.get("claim_boundary")
                if isinstance(full_scf.get("claim_boundary"), str)
                else "Full-SCF numerical comparison is a hard release gate and cannot be inferred from PPA or target readiness."
            ),
        },
        "full_scf_numerical_closure_workplan": full_scf_workplan,
        "release_completion_gates": {
            "full_scf_numerical_present": bool(full_scf),
            "full_scf_numerical_passed": bool(full_scf_passed),
            "full_scf_numerical_artifact": artifact,
            "full_scf_numerical_closure_required": bool(full_scf_workplan.get("required", False)),
            "full_scf_numerical_closure_work_item_count": full_scf_workplan.get("work_item_count"),
            "full_scf_numerical_closure_class_row_work_item_count": full_scf_workplan.get(
                "class_row_work_item_count"
            ),
            "full_scf_numerical_closure_blocker_category_counts": full_scf_workplan.get(
                "blocker_category_counts", {}
            ),
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "Deployment readiness release gates expose remaining full-SCF "
                "numerical closure work only; they do not upgrade FPGA/ASIC "
                "deployment recommendations or deliverable completion."
            ),
        },
    }


__all__ = [
    "build_full_scf_numerical_readiness_sections",
    "_full_scf_numerical_closure_workplan",
    "_full_scf_numerical_gate_blockers",
    "_full_scf_numerical_gate_passed",
    "_full_scf_status_artifact_passed",
    "_full_scf_validation_artifact_passed",
]
