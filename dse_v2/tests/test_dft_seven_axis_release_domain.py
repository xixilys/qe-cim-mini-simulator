#!/usr/bin/env python3
"""DFT seven-axis release-domain and candidate-universe tests."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.reference_workloads.dft_codesign_domain import (
    DFT_APPLICABILITY_AXIS_IDS,
    DFT_DESIGN_AXIS_IDS,
    DFT_EVALUATION_POLICY_AXIS_IDS,
    DFT_LEGALITY_CONSTRAINTS,
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
    assert "dft_phase_hotspot_selection" not in DFT_DESIGN_AXIS_IDS
    assert "evidence_fidelity_promotion_policy" not in DFT_DESIGN_AXIS_IDS
    assert freeze["candidate_identity_policy"]["design_identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert freeze["candidate_identity_policy"]["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert freeze["candidate_identity_policy"]["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)
    assert freeze["candidate_identity_policy"]["evidence_policy_affects_identity"] is False
    assert "dft_phase_hotspot_selection" in freeze["candidate_identity_policy"]["candidate_identity_excludes"]
    assert "evidence_fidelity_promotion_policy" in freeze["candidate_identity_policy"]["candidate_identity_excludes"]
    assert freeze["axis_partitions"]["design_identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert freeze["axis_partitions"]["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert freeze["axis_partitions"]["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)
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
    assert all(
        "dft_phase_hotspot_selection" not in {*item["when"], *item["requires"]}
        and "evidence_fidelity_promotion_policy" not in {*item["when"], *item["requires"]}
        for item in constraints
    )
    assert all(
        item["claim_boundary"] == "DFT plugin data for generic design legality evaluation; not core coupling."
        for item in constraints
    )
    assert freeze["domain_hash"]
    assert manifest["axis_count"] == 7
    assert manifest["identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert manifest["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert manifest["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)
    assert manifest["non_identity_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS)
    assert manifest["candidate_id_provenance"]["phase_hotspot_affects_identity"] is False
    assert manifest["candidate_id_provenance"]["evidence_policy_affects_identity"] is False
    assert manifest["unique_design_candidate_count"] == 32
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
    assert len(illegal_rows) == manifest["illegal_candidate_count"] == 72
    assert all(row["reasons"] for row in illegal_rows)
    assert manifest["candidate_id_provenance"]["candidate_id_rule"].startswith("cand_ + sha256")
    assert manifest["candidate_id_provenance"]["candidate_id_kind"] == "evaluation_record_id"
    assert manifest["candidate_id_provenance"]["design_candidate_id_rule"].startswith("design_cand_ + sha256")
    assert manifest["candidate_id_provenance"]["assignment_order"] == list(DFT_SEVEN_AXIS_IDS)
    assert manifest["candidate_id_provenance"]["identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert manifest["candidate_id_provenance"]["non_identity_axis_ids"] == list(
        DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS
    )
    assert manifest["candidate_id_provenance"]["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert manifest["candidate_id_provenance"]["phase_hotspot_affects_identity"] is False
    assert manifest["candidate_id_provenance"]["evidence_policy_affects_identity"] is False

    for candidate in manifest["candidates"]:
        assert tuple(candidate["assignments"]) == DFT_SEVEN_AXIS_IDS
        assert tuple(candidate["identity_assignments"]) == DFT_DESIGN_AXIS_IDS
        assert tuple(candidate["non_identity_assignments"]) == DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS
        assert tuple(candidate["applicability_assignments"]) == DFT_APPLICABILITY_AXIS_IDS
        assert tuple(candidate["evaluation_policy_assignments"]) == DFT_EVALUATION_POLICY_AXIS_IDS
        assert candidate["design_legality"]["passed"] is candidate["legal"]
        assert candidate["applicability_compatibility"]["affects_design_legality"] is False
        assert candidate["evaluation_policy_routing"]["affects_design_legality"] is False
        assert candidate["candidate_id_kind"] == "evaluation_record_id"
        assert candidate["candidate_id"].startswith("cand_")
        assert candidate["design_candidate_id"].startswith("design_cand_")
        assert candidate["provenance"]["source"] == "frozen_release_domain_cartesian_product"
        assert candidate["provenance"]["assignment_order"] == list(DFT_SEVEN_AXIS_IDS)
        assert candidate["provenance"]["identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
        assert candidate["provenance"]["non_identity_axis_ids"] == list(
            DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS
        )
        assert candidate["provenance"]["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
        assert candidate["provenance"]["phase_hotspot_affects_identity"] is False
        assert candidate["provenance"]["evidence_policy_affects_identity"] is False
        assert candidate["screening"]["all_axes_used"] is False
        assert candidate["screening"]["all_design_axes_used"] is True
        assert tuple(sorted(candidate["screening"]["axis_terms"])) == tuple(sorted(DFT_DESIGN_AXIS_IDS))
        assert "dft_phase_hotspot_selection" not in candidate["screening"]["axis_terms"]
        assert "evidence_fidelity_promotion_policy" not in candidate["screening"]["axis_terms"]

    by_design_id: dict[str, list[dict]] = {}
    for candidate in manifest["candidates"]:
        by_design_id.setdefault(candidate["design_candidate_id"], []).append(candidate)
    paired_rows = [rows for rows in by_design_id.values() if len(rows) == 4]
    assert paired_rows
    for rows in paired_rows:
        identity_assignments = {json.dumps(row["identity_assignments"], sort_keys=True) for row in rows}
        applicability_values = {row["assignments"]["dft_phase_hotspot_selection"] for row in rows}
        evidence_values = {row["assignments"]["evidence_fidelity_promotion_policy"] for row in rows}
        assert len(identity_assignments) == 1
        assert applicability_values == {"scf_hpsi_density", "hybrid_exx_fft"}
        assert evidence_values == {"systemc_then_gem5_non_smoke", "systemc_gem5_eda_formal_ladder"}


def test_phase_and_evaluation_policy_do_not_affect_design_identity_legality_or_score():
    _, manifest, _ = dft_candidate_universe()
    forbidden_legality_axes = {"dft_phase_hotspot_selection", "evidence_fidelity_promotion_policy"}
    assert all(
        not forbidden_legality_axes.intersection({*constraint["when"], *constraint["requires"]})
        for constraint in DFT_LEGALITY_CONSTRAINTS
    )

    by_design_assignment: dict[str, list[dict]] = {}
    for candidate in manifest["candidates"]:
        key = json.dumps(candidate["identity_assignments"], sort_keys=True)
        by_design_assignment.setdefault(key, []).append(candidate)

    rows = next(group for group in by_design_assignment.values() if len(group) == 4)
    design_ids = {row["design_candidate_id"] for row in rows}
    design_legality = {json.dumps(row["design_legality"], sort_keys=True) for row in rows}
    design_scores = {row["design_score"] for row in rows}
    design_score_terms = {json.dumps(row["screening"]["axis_terms"], sort_keys=True) for row in rows}
    applicability_scope_ids = {row["applicability_scope_id"] for row in rows}
    applicability_values = {row["applicability_assignments"]["dft_phase_hotspot_selection"] for row in rows}
    evaluation_policy_ids = {row["evaluation_policy_id"] for row in rows}
    promotion_requirement_sets = {tuple(row["promotion_requirements"]) for row in rows}

    assert len(design_ids) == 1
    assert len(design_legality) == 1
    assert len(design_scores) == 1
    assert len(design_score_terms) == 1
    assert len(applicability_scope_ids) == 2
    assert applicability_values == {"scf_hpsi_density", "hybrid_exx_fft"}
    assert len(evaluation_policy_ids) == 2
    assert len(promotion_requirement_sets) == 2
    assert all(row["applicability_compatibility"]["affects_design_legality"] is False for row in rows)
    assert all(row["evaluation_policy_routing"]["affects_design_score"] is False for row in rows)
    assert any(
        blocker["rule_id"] == "hybrid_exx_requires_batched_gemm"
        for row in rows
        for blocker in row["applicability_compatibility"]["blockers"]
    )
    assert any(
        blocker["rule_id"] == "eda_formal_ladder_routes_to_genericaccel_descriptor"
        for row in manifest["candidates"]
        for blocker in row["evaluation_policy_routing"]["routing_blockers"]
    )


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
    assert report["design_identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert report["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert report["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)
    assert report["candidate_identity_policy"]["evidence_policy_affects_identity"] is False
    assert report["candidate_generation"]["all_candidates_have_all_axes"] is True
    assert report["candidate_generation"]["all_design_identities_exclude_evaluation_policy"] is True
    assert report["candidate_generation"]["all_design_identities_exclude_applicability"] is True
    assert report["candidate_generation"]["all_candidates_have_applicability_assignments"] is True
    assert report["candidate_generation"]["all_candidates_have_evaluation_policy_assignments"] is True
    assert report["candidate_generation"]["unique_design_candidate_count"] == 32
    assert report["cardinality_cost_estimator"]["stage"] == "before_full_evidence_execution"
    assert report["cardinality_cost_estimator"]["cartesian_candidate_count"] == 128
    assert report["cardinality_cost_estimator"]["legal_candidate_count"] == 56
    assert report["cardinality_cost_estimator"]["estimated_candidate_evidence_rows"] == 56
    assert report["cardinality_cost_estimator"]["estimated_hard_evidence_slots"] == 56 * 9
    assert "not completion evidence" in report["cardinality_cost_estimator"]["claim_boundary"]
    assert report["screening"]["all_legal_candidates_have_axis_terms"] is True
    assert report["screening"]["design_scoring_ignores_applicability_and_evaluation_policy"] is True
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
    assert report["universe_backed_queue"]["legal_design_candidate_ids"] == manifest["legal_design_candidate_ids"]
    assert all(item["all_axes_used"] for item in report["promotion_queue"])
    assert all(item["stable_design_identity_excludes_evidence_policy"] for item in report["promotion_queue"])
    assert all(item["stable_design_identity_excludes_applicability"] for item in report["promotion_queue"])
    assert all(item["applicability_assignments"] for item in report["promotion_queue"])
    assert all(item["evaluation_policy_assignments"] for item in report["promotion_queue"])
    assert all(item["promotion_requirements"] for item in report["promotion_queue"])
    assert all(item["design_candidate_id"].startswith("design_cand_") for item in report["promotion_queue"])
    assert report["feedback_trace"]["source"] == "existing_non_smoke_timing_sample"
    assert report["feedback_trace"]["all_axes_updated_or_ready"] is True
    for axis_id in DFT_SEVEN_AXIS_IDS:
        usage = report["axis_usage"][axis_id]
        assert usage["candidate_generation"] is True
        assert usage["non_smoke_timing_promotion"] is True
        assert usage["feedback"] is True
    for axis_id in DFT_DESIGN_AXIS_IDS:
        assert report["axis_usage"][axis_id]["design_legality"] is True
        assert report["axis_usage"][axis_id]["screening"] is True
    for axis_id in DFT_APPLICABILITY_AXIS_IDS:
        assert report["axis_usage"][axis_id]["design_legality"] is False
        assert report["axis_usage"][axis_id]["screening"] is False
        assert report["axis_usage"][axis_id]["applicability_compatibility"] is True
    for axis_id in DFT_EVALUATION_POLICY_AXIS_IDS:
        assert report["axis_usage"][axis_id]["design_legality"] is False
        assert report["axis_usage"][axis_id]["screening"] is False
        assert report["axis_usage"][axis_id]["evaluation_policy_routing"] is True


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
    assert cli_status["design_identity_axis_ids"] == list(DFT_DESIGN_AXIS_IDS)
    assert cli_status["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert cli_status["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)
    assert cli_status["legal_design_candidate_count"] > 0
    for name in [
        "seven_axis_domain_freeze.json",
        "candidate_universe_manifest.json",
        "candidate_legality_report.json",
        "seven_axis_search_space_report.json",
        "closed_loop_feedback_trace.json",
        "hierarchical_funnel_search_report.json",
        "status.json",
    ]:
        assert (cli_out / name).exists()

    hierarchical = json.loads((cli_out / "hierarchical_funnel_search_report.json").read_text())
    assert hierarchical["status"] == "passed"
    assert hierarchical["wide_space_policy"]["wide_space_can_enter_formal_pareto_without_release_gate"] is False
