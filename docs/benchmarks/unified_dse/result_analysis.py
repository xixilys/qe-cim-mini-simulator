from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


PROMOTION_STATES = ("reject", "explain-only", "promotion-eligible")

REQUIRED_PROMOTION_METRICS = (
    "time_to_convergence_s",
    "energy_to_convergence_j",
    "bytes_moved_to_convergence",
    "fallback_ratio",
    "spill_ratio",
)


def validate_promotion_state(state: str) -> None:
    if state not in PROMOTION_STATES:
        raise ValueError(f"invalid promotion state: {state}")


def _has_required_metrics(metrics: Mapping[str, Any]) -> bool:
    return all(key in metrics for key in REQUIRED_PROMOTION_METRICS)


def _promotion_state_for_row(row: Mapping[str, Any]) -> str:
    if row.get("result_status") == "model_error":
        return "reject"
    if row.get("result_status") != "executed":
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
    return {
        "rows": copied_rows,
        "promotion_state_counts": counts,
    }
