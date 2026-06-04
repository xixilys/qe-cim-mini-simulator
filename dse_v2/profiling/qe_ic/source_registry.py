#!/usr/bin/env python3
"""Profile-source loading and normalization for QE-IC Layer-2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from dse_v2.profiling.qe_ic.schema import (
    IMPLEMENTED_PROFILE_SOURCE_TYPES,
    QE_IC_PROFILE_SOURCES_SCHEMA_VERSION,
    SUPPORTED_PROFILE_SOURCE_TYPES,
)


def extract_profile_sources(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract profile_sources from the v1 fixture envelope."""

    if payload.get("schema_version") != QE_IC_PROFILE_SOURCES_SCHEMA_VERSION:
        raise ValueError("profile sources schema_version is incorrect")
    sources = payload.get("profile_sources")
    if not isinstance(sources, list):
        raise ValueError("profile_sources must be a list")
    return [dict(source) for source in sources if isinstance(source, Mapping)]


def normalize_profile_sources(
    profile_sources: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize supported source records and warn for unimplemented parsers."""

    normalized: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for index, source in enumerate(profile_sources):
        record = dict(source)
        source_type = record.get("profile_source_type")
        if source_type not in SUPPORTED_PROFILE_SOURCE_TYPES:
            warnings.append(
                {
                    "field": f"profile_sources[{index}].profile_source_type",
                    "message": f"unsupported profile_source_type {source_type!r}",
                }
            )
        elif source_type not in IMPLEMENTED_PROFILE_SOURCE_TYPES:
            warnings.append(
                {
                    "field": f"profile_sources[{index}].profile_source_type",
                    "message": "parser_not_implemented_for_source_type",
                }
            )
        normalized.append(record)
    return normalized, warnings

