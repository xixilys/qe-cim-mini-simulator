#!/usr/bin/env python3
"""DFT seven-axis release-domain and candidate-universe tests."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.reference_workloads.dft_codesign_domain import (
    DFT_SEVEN_AXIS_IDS,
    build_search_space_report,
    dft_candidate_universe,
    dft_legality_constraints,
    write_dft_seven_axis_artifacts,
)


def test_dft_release_domain_freezes_all_seven_axes_with_versions_and_sources():
    freeze, manifest, legality = dft_candidate_universe()

    assert freeze["schema_version"] == "dse.codesign.release_domain_freeze.v1"
    assert tuple(axis["axis_id"] for axis in freeze["axes"]) == DFT_SEVEN_AXIS_IDS
    assert freeze["axis_count"] == 7
    assert freeze["finite"] is True
    assert freeze["small_release_domain_policy"] == {
        "finite": True,
        "cited": True,
        "explicit_scope": "DFT-first seven-axis release v1, two values per axis",
        "complete_for_frozen_scope": True,
        "represents_infinite_dft_space": False,
        "claim_boundary": (
            "This small release domain is complete only for the frozen cited scope; "
            "it is not represented as the infinite DFT design space."
        ),
    }
    constraints = dft_legality_constraints()
    assert freeze["legality_constraints"] == constraints
    assert constraints
    assert all(set(item["axis_ids"]).issubset(DFT_SEVEN_AXIS_IDS) for item in constraints)
    assert all(item["claim_boundary"] == "DFT plugin data for generic legality evaluation; not core coupling." for item in constraints)
    assert freeze["domain_hash"]
    assert manifest["axis_count"] == 7
    assert manifest["cartesian_count"] == 128
    assert manifest["legal_candidate_count"] > 0
    assert legality["summary"]["all_candidates_classified"] is True

    for axis in freeze["axes"]:
        assert axis["finite"] is True
        assert axis["version"] == "v1"
        assert axis["axis_hash"]
        assert axis["source_refs"]
        assert len(axis["values"]) == 2
        for value in axis["values"]:
            assert value["version"] == "v1"
            assert value["source_refs"]


def test_candidate_universe_manifest_contains_every_cartesian_candidate_and_stable_ids():
    freeze, manifest, legality = dft_candidate_universe()
    repeat_freeze, repeat_manifest, repeat_legality = dft_candidate_universe()
    candidate_ids = [candidate["candidate_id"] for candidate in manifest["candidates"]]
    legality_ids = [row["candidate_id"] for row in legality["rows"]]
    repeat_candidate_ids = [candidate["candidate_id"] for candidate in repeat_manifest["candidates"]]

    assert len(candidate_ids) == len(set(candidate_ids)) == manifest["cartesian_count"]
    assert set(candidate_ids) == set(legality_ids)
    assert candidate_ids == repeat_candidate_ids
    assert freeze["domain_hash"] == repeat_freeze["domain_hash"]
    assert manifest["universe_hash"] == repeat_manifest["universe_hash"]
    assert legality["legality_hash"] == repeat_legality["legality_hash"]
    assert set(manifest["legal_candidate_ids"]).issubset(candidate_ids)
    assert manifest["domain_hash"] == freeze["domain_hash"]
    assert legality["domain_hash"] == freeze["domain_hash"]
    assert legality["universe_hash"] == manifest["universe_hash"]
    assert legality["status"] == "passed"
    illegal_rows = [row for row in legality["rows"] if row["legal"] is False]
    assert len(illegal_rows) == manifest["illegal_candidate_count"] == 92
    assert all(row["reasons"] for row in illegal_rows)
    assert manifest["candidate_id_provenance"]["candidate_id_rule"].startswith("cand_ + sha256")
    assert manifest["candidate_id_provenance"]["assignment_order"] == list(DFT_SEVEN_AXIS_IDS)

    for candidate in manifest["candidates"]:
        assert tuple(candidate["assignments"]) == DFT_SEVEN_AXIS_IDS
        assert candidate["provenance"]["source"] == "frozen_release_domain_cartesian_product"
        assert candidate["provenance"]["assignment_order"] == list(DFT_SEVEN_AXIS_IDS)
        assert candidate["screening"]["all_axes_used"] is True
        assert tuple(sorted(candidate["screening"]["axis_terms"])) == tuple(sorted(DFT_SEVEN_AXIS_IDS))


def test_search_space_report_uses_every_axis_in_generation_screening_promotion_and_feedback():
    freeze, manifest, legality = dft_candidate_universe()
    report = build_search_space_report(
        freeze,
        manifest,
        legality,
        timing_evidence_summary={
            "run_dir": "runs/dse/dft_first_qe_real_gem5_hardened_audit",
            "step4_trusted_timing": True,
        },
    )

    assert report["status"] == "passed"
    assert report["axis_ids"] == list(DFT_SEVEN_AXIS_IDS)
    assert report["candidate_generation"]["all_candidates_have_all_axes"] is True
    assert report["cardinality_cost_estimator"]["stage"] == "before_full_evidence_execution"
    assert report["cardinality_cost_estimator"]["cartesian_candidate_count"] == 128
    assert report["cardinality_cost_estimator"]["legal_candidate_count"] == 36
    assert report["cardinality_cost_estimator"]["estimated_candidate_evidence_rows"] == 36
    assert report["cardinality_cost_estimator"]["estimated_hard_evidence_slots"] == 36 * 9
    assert "not completion evidence" in report["cardinality_cost_estimator"]["claim_boundary"]
    assert report["screening"]["all_legal_candidates_have_axis_terms"] is True
    assert report["screening"]["priority_queue_policy"] == {
        "top_k_or_representative_subset_allowed_for_execution_order": True,
        "completion_requires_all_legal_candidates": True,
        "subset_satisfies_release_completion": False,
        "claim_boundary": (
            "Screening scores may prioritize expensive evidence execution, "
            "but top-K or representative-only evidence cannot replace "
            "all-candidate evidence closure for the frozen release domain."
        ),
    }
    assert report["promotion_queue"]
    assert report["universe_backed_queue"]["queue_mode"] == "all_legal_candidates"
    assert report["universe_backed_queue"]["entry_count"] == manifest["legal_candidate_count"]
    assert report["universe_backed_queue"]["candidate_ids"] == manifest["legal_candidate_ids"]
    assert report["universe_backed_queue"]["all_legal_candidates_once"] is True
    assert len(set(report["universe_backed_queue"]["candidate_ids"])) == manifest["legal_candidate_count"]
    assert all(item["all_axes_used"] for item in report["promotion_queue"])
    assert report["feedback_trace"]["source"] == "existing_non_smoke_timing_sample"
    assert report["feedback_trace"]["all_axes_updated_or_ready"] is True
    for axis_id in DFT_SEVEN_AXIS_IDS:
        usage = report["axis_usage"][axis_id]
        assert usage["candidate_generation"] is True
        assert usage["screening"] is True
        assert usage["non_smoke_timing_promotion"] is True
        assert usage["feedback"] is True


def test_seven_axis_artifact_writer_and_cli_emit_required_files(tmp_path):
    status = write_dft_seven_axis_artifacts(tmp_path / "direct")
    assert status["status"] == "passed"
    for path in status["artifacts"].values():
        assert (tmp_path / "direct" / path.split("/")[-1]).exists()

    cli_out = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_seven_axis_release_artifacts.py",
            "--out",
            str(cli_out),
            "--timing-run-dir",
            "runs/dse/dft_first_qe_real_gem5_hardened_audit",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    cli_status = json.loads(result.stdout)
    assert cli_status["status"] == "passed"
    for name in [
        "seven_axis_domain_freeze.json",
        "candidate_universe_manifest.json",
        "candidate_legality_report.json",
        "seven_axis_search_space_report.json",
        "closed_loop_feedback_trace.json",
        "status.json",
    ]:
        assert (cli_out / name).exists()
