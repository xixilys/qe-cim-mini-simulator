from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .interfaces import DESIGN_POINT_IDENTITY_KEYS, WORKLOAD_IDENTITY_KEYS


IDENTITY_KEYS = WORKLOAD_IDENTITY_KEYS + DESIGN_POINT_IDENTITY_KEYS


def apply_calibration_feedback(row: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    for key in IDENTITY_KEYS:
        if key in feedback:
            raise ValueError(f"calibration feedback cannot update identity key: {key}")

    updated = deepcopy(row)
    feedback_copy: Mapping[str, Any] = deepcopy(feedback)
    if "source_kind" in feedback_copy:
        updated["source_kind"] = feedback_copy["source_kind"]
    updated["calibration"] = dict(feedback_copy)
    return updated
