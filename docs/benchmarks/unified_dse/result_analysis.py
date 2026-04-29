from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence


PROMOTION_STATES = ("reject", "explain-only", "promotion-eligible")

REQUIRED_PROMOTION_METRICS = (
    "time_to_convergence_s",
    "energy_to_convergence_j",
    "bytes_moved_to_convergence",
    "fallback_ratio",
    "spill_ratio",
)

RANKING_CLAIM_CEILING = "stage_a_screening_only"
FAST_MODEL_RANKING_CLAIM_CEILING = "fast_model_screening_only"
RANKING_CLAIM_CEILINGS = (
    RANKING_CLAIM_CEILING,
    FAST_MODEL_RANKING_CLAIM_CEILING,
    "systemc_feedback_ranked",
    "gem5_feedback_ranked",
    "fast_model_calibrated_screening",
    "backend_report_reference_only",
)
PARETO_NOT_EVALUATED = "not_evaluated"
PARETO_SCREENING_CANDIDATE = "screening_candidate"
SHORTLIST_NOT_RANKED = "insufficient_metrics_for_shortlist"
SHORTLIST_RANKED = "artifact_backed_screening_metrics"


def validate_promotion_state(state: str) -> None:
    if state not in PROMOTION_STATES:
        raise ValueError(f"invalid promotion state: {state}")


def _has_required_metrics(metrics: Mapping[str, Any]) -> bool:
    return all(_finite_metric(metrics, key) is not None for key in REQUIRED_PROMOTION_METRICS)


def metrics_are_ranking_grade(metrics: Mapping[str, Any]) -> bool:
    return _has_required_metrics(metrics)


def _finite_metric(metrics: Mapping[str, Any], key: str) -> float | None:
    try:
        value = float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _is_valid_executable_row(row: Mapping[str, Any]) -> bool:
    design_validation = row.get("design_validation", {})
    return (
        isinstance(design_validation, Mapping)
        and design_validation.get("validity_class") == "valid_executable"
    )


def _promotion_state_for_row(row: Mapping[str, Any]) -> str:
    if row.get("result_status") == "model_error":
        return "reject"
    if row.get("result_status") not in {"executed", "screened"}:
        return "explain-only"
    if not _is_valid_executable_row(row):
        return "explain-only"

    projection = row.get("projection", {})
    metrics = row.get("metrics", {})
    if (
        isinstance(projection, Mapping)
        and projection.get("ranking_grade_ready") is True
        and isinstance(metrics, Mapping)
        and _has_required_metrics(metrics)
    ):
        return "promotion-eligible"
    return "explain-only"


def _ranking_sort_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    metrics = row.get("metrics", {})
    if not isinstance(metrics, Mapping):
        metrics = {}
    values = [_finite_metric(metrics, key) for key in REQUIRED_PROMOTION_METRICS]
    return (
        *(value if value is not None else float("inf") for value in values),
    )


def _apply_stage_a_ranking_defaults(row: dict[str, Any], screening_rank: int | None) -> None:
    default_claim = (
        FAST_MODEL_RANKING_CLAIM_CEILING
        if row.get("source_kind") == "fast_model_screening"
        else RANKING_CLAIM_CEILING
    )
    row["ranking_claim_ceiling"] = row.get("ranking_claim_ceiling") or default_claim
    row["final_public_family_winner"] = None
    if screening_rank is None:
        row["screening_rank"] = None
        row["pareto_membership"] = row.get("pareto_membership") or PARETO_NOT_EVALUATED
        row["shortlist_reason"] = row.get("shortlist_reason") or SHORTLIST_NOT_RANKED
        return

    row["screening_rank"] = screening_rank
    row["pareto_membership"] = PARETO_SCREENING_CANDIDATE
    row["shortlist_reason"] = SHORTLIST_RANKED


def summarize_results(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    copied_rows = []
    counts = {state: 0 for state in PROMOTION_STATES}
    for row in rows:
        copied = deepcopy(dict(row))
        state = _promotion_state_for_row(copied)
        validate_promotion_state(state)
        copied["promotion_state"] = state
        counts[state] += 1
        copied_rows.append(copied)
    rank_by_index = {
        row_index: rank
        for rank, row_index in enumerate(
            sorted(
                (
                    row_index
                    for row_index, row in enumerate(copied_rows)
                    if row["promotion_state"] == "promotion-eligible"
                ),
                key=lambda row_index: _ranking_sort_key(copied_rows[row_index]),
            ),
            start=1,
        )
    }
    for row_index, copied in enumerate(copied_rows):
        _apply_stage_a_ranking_defaults(copied, rank_by_index.get(row_index))
    return {
        "rows": copied_rows,
        "promotion_state_counts": counts,
    }
