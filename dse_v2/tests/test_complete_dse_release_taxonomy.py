#!/usr/bin/env python3
"""Release-v1 taxonomy and legality tests for complete DSE."""

from __future__ import annotations

import copy

from dse_v2.codesign.complete_dse_search_space import (
    REQUIRED_BASE_FAMILIES,
    REQUIRED_HYBRID_TEMPLATES,
    build_architecture_taxonomy_manifest,
    build_freeze_gate_verdict,
    build_hybrid_template_manifest,
    build_legality_pruning_report,
    build_release_pruning_rationale_report,
    build_release_subset_manifest,
    build_runtime_schedule_space,
    build_schedule_legality_report,
    build_workload_architecture_prior_report,
    classify_candidate_legality,
    default_release_candidate_seed_rows,
    default_release_seed_rows,
)


def test_release_taxonomy_contains_required_base_families_and_finite_hybrids():
    taxonomy = build_architecture_taxonomy_manifest()
    entries = {entry["id"]: entry for entry in taxonomy["entries"]}

    assert set(REQUIRED_BASE_FAMILIES).issubset(entries)
    assert set(REQUIRED_HYBRID_TEMPLATES).issubset(entries)
    assert taxonomy["arbitrary_base_family_cross_product_allowed"] is False
    for family_id in REQUIRED_BASE_FAMILIES:
        assert entries[family_id]["kind"] == "base_family"
        assert entries[family_id]["release_v1_status"] == "required"
    for template_id in REQUIRED_HYBRID_TEMPLATES:
        assert entries[template_id]["kind"] == "hybrid_template"
        assert (
            entries[template_id]["release_v1_status"]
            == "required_finite_hybrid"
        )
        assert entries[template_id]["arbitrary_cross_product"] is False

    hybrids = build_hybrid_template_manifest()
    assert [row["id"] for row in hybrids["templates"]] == list(
        REQUIRED_HYBRID_TEMPLATES
    )


def test_release_subset_covers_bounded_release_universe_per_required_taxonomy_entry():
    manifest = build_release_subset_manifest()
    included = set(manifest["included_taxonomy_ids"])
    release_seed_rows = default_release_candidate_seed_rows()

    assert manifest["finite"] is True
    assert manifest["predeclared"] is True
    assert manifest["candidate_count"] == len(release_seed_rows)
    assert manifest["legal_candidate_count"] == manifest["candidate_count"]
    assert set(REQUIRED_BASE_FAMILIES).issubset(included)
    assert set(REQUIRED_HYBRID_TEMPLATES).issubset(included)
    assert {
        row["taxonomy_id"] for row in release_seed_rows
    } == set(REQUIRED_BASE_FAMILIES) | set(REQUIRED_HYBRID_TEMPLATES)
    assert len(manifest["legal_candidate_ids"]) == len(
        set(manifest["legal_candidate_ids"])
    )
    assert manifest["stable_id_status"] == (
        "emitted_after_all_identity_layers_present"
    )


def test_legality_rejects_ad_hoc_hybrid_and_incompatible_schedule_bindings():
    manifest = build_release_subset_manifest()
    layers = copy.deepcopy(
        manifest["candidates"][0]["identity"]["identity_layers"]
    )

    layers["architecture_parameters"] = {
        "taxonomy_id": "streaming_pipeline+spatial_pe_array",
        "kind": "ad_hoc_composite",
        "compute_organization": "unlisted composite",
        "release_v1_status": "not_predeclared",
    }
    legal, reasons = classify_candidate_legality(layers)
    assert legal is False
    assert any("arbitrary base-family" in reason for reason in reasons)

    incompatible = copy.deepcopy(
        manifest["candidates"][0]["identity"]["identity_layers"]
    )
    taxonomy_id = incompatible["architecture_parameters"]["taxonomy_id"]
    runtime = next(
        row
        for row in build_runtime_schedule_space()["runtime_schedules"]
        if taxonomy_id not in row["compatible_taxonomy_ids"]
    )
    incompatible["runtime_scheduling_parameters"] = {
        "runtime_schedule_id": runtime["id"],
        "co_scheduling_policy_id": runtime["queue_policy"],
        "queue_policy": runtime["queue_policy"],
        "engine_assignment": runtime["engine_assignment"],
    }
    legal, reasons = classify_candidate_legality(incompatible)
    assert legal is False
    assert any("runtime schedule" in reason for reason in reasons)


def test_pruning_report_classifies_pruned_rows_with_stable_reasons():
    report = build_legality_pruning_report()
    rationale = build_release_pruning_rationale_report()

    assert report["status"] == "passed"
    assert report["all_pruned_rows_have_stable_reason"] is True
    assert {row["classification"] for row in report["pruned_rows"]}.issubset(
        {"illegal", "research_only", "over_budget", "blocked"}
    )
    assert any(
        row["classification"] == "illegal" for row in report["pruned_rows"]
    )
    assert report["claim_boundary"].startswith("pruning explains pre-freeze")
    assert rationale["schema_version"].endswith(
        "release_pruning_rationale_report.v1"
    )
    assert (
        rationale["provenance"]["post_freeze_row_removal_allowed"] is False
    )


def test_workload_priors_and_schedule_legality_are_pre_freeze_only():
    prior = build_workload_architecture_prior_report()
    schedule = build_schedule_legality_report()

    assert prior["status"] == "passed"
    assert prior["workload_facts_affect_identity"] is False
    assert prior["workload_facts_affect_post_freeze_pruning"] is False
    assert prior["seed_row_count"] == len(default_release_seed_rows())
    assert all(
        row["candidate_identity_participation"] is False
        and row["may_remove_frozen_rows"] is False
        for row in prior["seed_rows"]
    )

    assert schedule["status"] == "passed"
    assert schedule["summary"] == {
        "row_count": len(default_release_seed_rows()),
        "all_algorithm_bindings_legal": True,
        "all_mapping_bindings_legal": True,
        "all_compile_schedule_bindings_legal": True,
        "all_runtime_schedule_bindings_legal": True,
    }


def test_freeze_gate_rejects_missing_required_taxonomy_entries():
    manifest = copy.deepcopy(build_release_subset_manifest())
    manifest["candidates"] = [
        row
        for row in manifest["candidates"]
        if row["identity"]["identity_layers"]["architecture_parameters"][
            "taxonomy_id"
        ]
        != "pipeline_task_overlap"
    ]
    manifest["included_taxonomy_ids"] = [
        row["identity"]["identity_layers"]["architecture_parameters"][
            "taxonomy_id"
        ]
        for row in manifest["candidates"]
    ]
    manifest["candidate_count"] = len(manifest["candidates"])
    manifest["legal_candidate_count"] = len(manifest["candidates"])

    verdict = build_freeze_gate_verdict(manifest)

    assert verdict["status"] == "blocked"
    assert any(
        blocker["id"] == "missing_required_taxonomy_entries"
        for blocker in verdict["blockers"]
    )


def test_freeze_gate_rejects_unpredeclared_or_illegal_release_candidates():
    manifest = copy.deepcopy(build_release_subset_manifest())
    row = copy.deepcopy(manifest["candidates"][0])
    row["candidate_id"] = "cdse_unpredeclared_probe"
    row["legal"] = False
    row["identity"]["identity_layers"]["architecture_parameters"] = {
        "taxonomy_id": "streaming_pipeline+spatial_pe_array",
        "kind": "ad_hoc_composite",
        "compute_organization": "unlisted composite",
        "release_v1_status": "not_predeclared",
    }
    manifest["candidates"].append(row)
    manifest["included_taxonomy_ids"].append(
        "streaming_pipeline+spatial_pe_array"
    )
    manifest["candidate_count"] += 1

    verdict = build_freeze_gate_verdict(manifest)

    assert verdict["status"] == "blocked"
    assert any(
        blocker["id"] == "unpredeclared_release_taxonomy"
        for blocker in verdict["blockers"]
    )
    assert any(
        blocker["id"] == "illegal_candidate_in_release_subset"
        for blocker in verdict["blockers"]
    )
