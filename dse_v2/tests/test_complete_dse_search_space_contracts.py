#!/usr/bin/env python3
"""Complete-DSE search-space two-tier contract tests."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.codesign.complete_dse_search_space import (
    CLAIM_LABELS,
    IDENTITY_LAYER_KEYS,
    NON_IDENTITY_FIELDS,
    build_architecture_search_space,
    build_search_space_schema,
    validate_architecture_search_space,
    write_complete_dse_search_space_artifacts,
)


def test_search_space_schema_separates_research_and_release_tiers():
    schema = build_search_space_schema()

    assert schema["schema_version"] == "dse.codesign.complete_dse_search_space.v1"
    assert set(schema["tiers"]) == {"research_space", "release_subset"}
    assert schema["tiers"]["research_space"]["completion_eligible"] is False
    assert schema["tiers"]["release_subset"]["completion_eligible"] is True
    assert schema["tiers"]["research_space"]["finite_release_subset"] is False
    assert schema["tiers"]["release_subset"]["finite_release_subset"] is True
    assert "deliverable_complete" not in schema["tiers"]["research_space"]["allowed_claims"]
    assert "deliverable_complete" in schema["tiers"]["release_subset"]["allowed_claims"]
    assert schema["identity_layers"] == list(IDENTITY_LAYER_KEYS)
    assert schema["non_identity_fields"] == list(NON_IDENTITY_FIELDS)
    assert set(CLAIM_LABELS).issuperset(schema["tiers"]["release_subset"]["allowed_claims"])
    assert schema["anti_downgrade_rules"] == {
        "research_rows_can_claim_deliverable_complete": False,
        "top_k_or_representative_subset_can_complete": False,
        "projection_or_descriptor_only_can_complete": False,
        "blocked_rows_can_complete": False,
    }
    assert schema["schema_hash"]


def test_architecture_search_space_bundle_is_valid_but_not_completion_evidence():
    search_space = build_architecture_search_space()
    validation = validate_architecture_search_space(search_space)

    assert validation["status"] == "passed"
    assert all(validation["checks"].values())
    assert search_space["claim_boundary"] == "foundation artifacts only; no trusted speedup or completion claim"
    assert search_space["research_space_manifest"]["completion_eligible"] is False
    assert search_space["release_subset_manifest"]["finite"] is True
    assert search_space["candidate_generation_report"]["stable_candidate_ids_emitted"] is True
    assert search_space["candidate_generation_report"]["excluded_from_identity"] == list(NON_IDENTITY_FIELDS)
    assert search_space["freeze_gate_verdict"]["top_k_or_representative_completion_allowed"] is False
    assert search_space["freeze_gate_verdict"]["status"] == "passed"


def test_artifact_writer_and_cli_emit_machine_readable_foundation_files(tmp_path):
    out_dir = tmp_path / "direct"
    status = write_complete_dse_search_space_artifacts(out_dir)
    assert status["status"] == "passed"
    for name in [
        "search_space_schema.json",
        "architecture_search_space.json",
        "release_subset_manifest.json",
        "candidate_generation_report.json",
        "freeze_gate_verdict.json",
        "validation_report.json",
        "status.json",
    ]:
        assert (out_dir / name).exists()

    architecture_search_space = json.loads((out_dir / "architecture_search_space.json").read_text(encoding="utf-8"))
    assert architecture_search_space["search_space_hash"]
    assert architecture_search_space["freeze_gate_verdict"]["claim_boundary"].startswith("freeze gate only")

    cli_out = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_complete_dse_search_space_artifacts.py",
            "--out",
            str(cli_out),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    cli_status = json.loads(result.stdout)
    assert cli_status["status"] == "passed"
    assert (cli_out / "architecture_search_space.json").exists()
    assert (cli_out / "status.json").exists()
