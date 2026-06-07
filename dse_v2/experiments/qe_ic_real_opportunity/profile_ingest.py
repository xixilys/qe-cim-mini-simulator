#!/usr/bin/env python3
"""Profile-log ingest placeholders for QE-IC real opportunity campaigns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def ingest_profile_logs(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return explicit profile ingest status without fabricating profile evidence."""

    if not isinstance(payload, Mapping):
        return {
            "profile_status": "evidence_missing",
            "profile_count": 0,
            "profiles_are_real": False,
            "blocker_reasons": ["profile_logs_missing"],
        }
    profiles = payload.get("profiles")
    count = len(profiles) if isinstance(profiles, list) else 0
    return {
        "profile_status": "ingested" if count else "evidence_missing",
        "profile_count": count,
        "profiles_are_real": bool(count),
        "blocker_reasons": [] if count else ["profile_logs_missing"],
    }
