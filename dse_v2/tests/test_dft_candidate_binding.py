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


def test_candidate_binding_scores_use_design_axes_only_not_scope_or_evidence_policy(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    manifest = json.loads((release_dir / "candidate_universe_manifest.json").read_text())
    payload = build_dft_candidate_binding_map(
        hierarchical_search_report_path=release_dir / "hierarchical_funnel_search_report.json",
        candidate_universe_manifest_path=release_dir / "candidate_universe_manifest.json",
    )

    by_eval_id = {row["evaluation_record_id"]: row for row in payload["binding_rows"]}
    # At least one bound row should carry the authoritative ID vocabulary.
    first = payload["binding_rows"][0]
    assert first["candidate_id_kind"] == "evaluation_record_id"
    assert first["candidate_id_authoritative_for_design"] is False
    assert first["design_candidate_id"].startswith("design_cand_")
    assert set(first["binding_axis_ids"]) == {
        "algorithm_variants",
        "mapping_data_layout",
        "hardware_microarchitecture",
        "interface_descriptor_protocol",
        "schedule_runtime_policy",
    }
    assert first["non_scoring_axis_ids"] == [
        "dft_phase_hotspot_selection",
        "evidence_fidelity_promotion_policy",
    ]
    assert first["applicability_match"]["affects_binding_score"] is False
    assert first["evaluation_routing"]["affects_binding_score"] is False

    # Directly compare release candidates that differ only by non-design axes: their design score and
    # stable design id are already equal, and any binding-row metadata must not make row id authoritative.
    candidates_by_design: dict[str, list[dict]] = {}
    for candidate in manifest["candidates"]:
        if candidate["legal"]:
            candidates_by_design.setdefault(candidate["design_candidate_id"], []).append(candidate)
    paired = next(rows for rows in candidates_by_design.values() if len(rows) == 4)
    assert len({row["design_score"] for row in paired}) == 1
    assert len({row["design_candidate_id"] for row in paired}) == 1
    assert {row["candidate_id_authoritative_for_design"] for row in paired} == {False}


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
