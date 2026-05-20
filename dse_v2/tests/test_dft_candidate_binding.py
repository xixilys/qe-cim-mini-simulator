#!/usr/bin/env python3
"""DFT candidate binding-map tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_candidate_binding import (
    DFT_CANDIDATE_BINDING_MAP_SCHEMA,
    build_dft_candidate_binding_map,
    validate_dft_candidate_binding_map,
    write_dft_candidate_binding_map,
)
from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts


def test_dft_candidate_binding_map_binds_all_search_rows_without_claim_upgrade(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)

    status = write_dft_candidate_binding_map(
        tmp_path / "binding",
        hierarchical_search_report_path=release_dir / "hierarchical_funnel_search_report.json",
        candidate_universe_manifest_path=release_dir / "candidate_universe_manifest.json",
    )

    assert status["status"] == "passed"
    payload = json.loads((tmp_path / "binding" / "dft_candidate_binding_map.json").read_text())
    validation = json.loads((tmp_path / "binding" / "dft_candidate_binding_map_validation.json").read_text())
    assert payload["schema_version"] == DFT_CANDIDATE_BINDING_MAP_SCHEMA
    assert payload["search_candidate_count"] == payload["bound_candidate_count"]
    assert payload["unmatched_candidate_count"] == 0
    assert payload["deliverable_complete"] is False
    assert payload["completion_eligible"] is False
    assert validation["valid"] is True
    assert all(row["release_candidate_id"] for row in payload["binding_rows"])
    assert all(row["completion_eligible"] is False for row in payload["binding_rows"])


def test_dft_candidate_binding_validator_rejects_missing_release_duplicate_search_and_claim_upgrade(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    payload = build_dft_candidate_binding_map(
        hierarchical_search_report_path=release_dir / "hierarchical_funnel_search_report.json",
        candidate_universe_manifest_path=release_dir / "candidate_universe_manifest.json",
    )

    missing_release = json.loads(json.dumps(payload))
    missing_release["binding_rows"][0]["release_candidate_id"] = None
    missing_release["bound_candidate_count"] -= 1
    missing_release["unmatched_candidate_count"] = 1
    assert validate_dft_candidate_binding_map(missing_release)["valid"] is False

    duplicate_search = json.loads(json.dumps(payload))
    duplicate_search["binding_rows"][1]["search_candidate_id"] = duplicate_search["binding_rows"][0]["search_candidate_id"]
    assert validate_dft_candidate_binding_map(duplicate_search)["valid"] is False

    claim_upgrade = json.loads(json.dumps(payload))
    claim_upgrade["binding_rows"][0]["completion_eligible"] = True
    claim_upgrade["completion_eligible"] = True
    claim_upgrade["deliverable_complete"] = True
    assert validate_dft_candidate_binding_map(claim_upgrade)["valid"] is False


def test_build_dft_candidate_binding_map_cli_writes_fail_closed_artifacts(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    out_dir = tmp_path / "cli_binding"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_candidate_binding_map.py",
            "--out",
            str(out_dir),
            "--hierarchical-search-report",
            str(release_dir / "hierarchical_funnel_search_report.json"),
            "--candidate-universe-manifest",
            str(release_dir / "candidate_universe_manifest.json"),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "dft_candidate_binding_map.json").exists()
    assert (out_dir / "dft_candidate_binding_map_status.json").exists()
    validation = json.loads((out_dir / "dft_candidate_binding_map_validation.json").read_text())
    assert validation["valid"] is True
