#!/usr/bin/env python3
"""Small Vivado report parsing helpers shared by DFT evidence consumers."""

from __future__ import annotations

import re


_VIVADO_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_vivado_design_timing_wns(text: str) -> float | None:
    """Extract final setup WNS from Vivado's Design Timing Summary.

    Vivado logs often contain earlier placement/intermediate lines such as
    ``Post Placement Timing Summary WNS=...`` before ``route_design`` finishes.
    Physical-PPA ranking needs the final routed timing report, so this helper
    prefers the table-style ``Design Timing Summary`` section and only falls
    back to the section's ``Setup: ... Worst Slack`` summary.  ``NA`` remains a
    missing metric rather than being converted to a pass.
    """

    design_section_match = re.search(
        r"Design Timing Summary(?P<section>.*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    section = design_section_match.group("section") if design_section_match else text
    table_match = re.search(
        rf"^\s*\|?\s*WNS\(ns\)[^\n]*\n"
        rf"^\s*-+(?:\s+-+)*[^\n]*\n"
        rf"^\s*({_VIVADO_NUMBER}|NA)\b",
        section,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if table_match:
        value = table_match.group(1)
        return None if value.upper() == "NA" else _as_float(value)

    setup_match = re.search(
        rf"^\s*Setup\s*:\s*[^,\n]*,\s*Worst Slack\s+({_VIVADO_NUMBER}|NA)\s*(?:ns)?\b",
        section,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if setup_match:
        value = setup_match.group(1)
        return None if value.upper() == "NA" else _as_float(value)
    return None


def extract_last_vivado_wns_marker(text: str) -> float | None:
    """Return the last generic ``WNS=``/``WNS:`` marker in Vivado text."""

    matches = list(
        re.finditer(
            rf"\bWNS\s*[:=]\s*({_VIVADO_NUMBER})",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return None
    return _as_float(matches[-1].group(1))
