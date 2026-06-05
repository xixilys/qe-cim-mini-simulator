#!/usr/bin/env python3
"""Synthetic high-fidelity replay label helpers for QE-IC Layer-6."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from dse_v2.feedback.qe_ic.schema import (
    QE_IC_SYNTHETIC_LABELS_SCHEMA_VERSION,
    SYNTHETIC_LABELS,
)


def _error(errors: list[dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_bounded(value: Any) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def validate_qe_ic_synthetic_high_fidelity_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    """Validate synthetic replay labels without interpreting them as hardware evidence."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(labels, Mapping):
        _error(errors, "$", "synthetic label set must be a mapping")
        return {
            "schema_version": "dse.qe_ic.synthetic_high_fidelity_labels_validation.v1",
            "status": "failed",
            "errors": errors,
            "warnings": warnings,
            "label_count": 0,
        }

    if labels.get("schema_version") != QE_IC_SYNTHETIC_LABELS_SCHEMA_VERSION:
        _error(errors, "schema_version", "synthetic label schema_version is incorrect")
    if labels.get("labels_are_real_hardware_evidence") is not False:
        _error(
            errors,
            "labels_are_real_hardware_evidence",
            "synthetic replay labels must not be marked as real hardware evidence",
        )
    rows = _as_list(labels.get("labels"))
    if not rows:
        _error(errors, "labels", "labels must be non-empty")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        prefix = f"labels[{index}]"
        if not isinstance(row, Mapping):
            _error(errors, prefix, "label row must be a mapping")
            continue
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            _error(errors, f"{prefix}.candidate_id", "candidate_id must be non-empty")
        elif candidate_id in seen:
            _error(errors, f"{prefix}.candidate_id", "candidate_id must be unique")
        else:
            seen.add(candidate_id)
        if row.get("label") not in SYNTHETIC_LABELS:
            _error(errors, f"{prefix}.label", "label is unsupported")
        if not _is_bounded(row.get("label_confidence")):
            _error(errors, f"{prefix}.label_confidence", "label_confidence must be in [0, 1]")
        if not isinstance(row.get("synthetic_rank"), int) or row.get("synthetic_rank") <= 0:
            _error(errors, f"{prefix}.synthetic_rank", "synthetic_rank must be a positive integer")
        if not _is_number(row.get("expected_improvement")):
            _error(errors, f"{prefix}.expected_improvement", "expected_improvement must be numeric")
        if not isinstance(row.get("round_observed"), int) or row.get("round_observed") <= 0:
            _error(errors, f"{prefix}.round_observed", "round_observed must be a positive integer")
        reason_codes = row.get("reason_codes")
        if not isinstance(reason_codes, list) or not reason_codes:
            _error(errors, f"{prefix}.reason_codes", "reason_codes must be non-empty")
    boundary = str(labels.get("claim_boundary", "")).lower()
    for term in ("synthetic high-fidelity replay labels", "not measured", "does not prove hardware performance"):
        if term not in boundary:
            _error(errors, "claim_boundary", f"claim_boundary must mention {term}")

    return {
        "schema_version": "dse.qe_ic.synthetic_high_fidelity_labels_validation.v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "label_count": len([row for row in rows if isinstance(row, Mapping)]),
    }
