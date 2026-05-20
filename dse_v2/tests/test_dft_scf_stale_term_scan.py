#!/usr/bin/env python3
"""Stale-term scan tests for the active DFT/QE hardware DSE objective."""

from __future__ import annotations

from pathlib import Path

from dse_v2.scripts.dse.scan_dft_scf_stale_terms import scan_paths


def test_stale_term_scan_blocks_old_date_and_removed_mainline_conflict(tmp_path):
    stale = tmp_path / "README.md"
    stale.write_text(
        "DFT removed from mainline; wait until 2026-05-15 00:00 CST.\n",
        encoding="utf-8",
    )

    report = scan_paths([stale])

    assert report["status"] == "blocked"
    assert report["must_fix_count"] == 2
    rule_ids = {hit["rule_id"] for hit in report["hits"]}
    assert "old_date_horizon" in rule_ids
    assert "dft_removed_mainline_conflict" in rule_ids


def test_stale_term_scan_allows_legacy_step3_alias_as_migration_reminder(tmp_path):
    code = tmp_path / "workflow.py"
    code.write_text(
        "payload = {'step3_searchable': True}  # legacy compatibility\n",
        encoding="utf-8",
    )

    report = scan_paths([code])

    assert report["status"] == "passed"
    assert report["must_fix_count"] == 0
    assert report["status_counts"]["legacy_allowed"] == 1
    assert report["hits"][0]["canonical_replacement"].startswith("step2_screenable")


def test_stale_term_scan_current_frontdoor_has_no_must_fix_terms():
    paths = [
        Path("AGENTS.md"),
        Path("README.md"),
        Path("CLAUDE.md"),
        Path("docs/AGENTS.md"),
        Path("docs/architecture/AGENTS.md"),
        Path("docs/architecture/dft_scf_hardware_dse_design_manual.md"),
        Path("docs/architecture/dft_first_completion_checklist.md"),
    ]

    report = scan_paths(paths)

    assert report["must_fix_count"] == 0
