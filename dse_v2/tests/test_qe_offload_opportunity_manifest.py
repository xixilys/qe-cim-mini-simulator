#!/usr/bin/env python3
"""QE offload opportunity manifest tests."""

from __future__ import annotations

from dse_v2.codesign.qe_callgraph_offload_search import (
    build_l4_offload_attempt_queue,
    build_offload_bundle_search_space,
    build_offload_opportunity_manifest,
    build_workload_variant_search_space,
    build_qe_callgraph_inventory,
)


def test_every_offload_opportunity_has_search_and_oracle_metadata(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")
    manifest = build_offload_opportunity_manifest(inventory)

    assert manifest["opportunity_count"] == inventory["node_count"]
    assert manifest["all_opportunities_classified"] is True
    assert manifest["claim_boundary"] == "manifest can queue work but cannot claim valuable_l4"

    for row in manifest["opportunities"]:
        assert row["opportunity_id"].startswith("opp_")
        assert row["workload_case_id"]
        assert row["granularity"] == "callsite"
        assert row["programs"]
        assert row["stage_type"]
        assert row["phase"] == row["stage_type"]
        assert row["kernel"]
        assert row["callsite_id"].startswith("callsite_")
        assert "source_file" in row
        assert row["symbol_or_subroutine"]
        assert row["semantic_role"]
        assert row["source_provenance"]["inventory_hash"]
        assert row["profile_evidence"]["status"]
        assert row["workload_selection"]["workload_case_id"] == row["workload_case_id"]
        assert "workload_variant" in row["workload_selection"]["selection_axes"]
        assert row["workload_selection"]["claim_boundary"].endswith(
            "not value evidence"
        )
        assert row["selection_priority"]["policy"].endswith("not a value claim")
        assert row["data_shape_expression"]
        assert row["correctness_oracle_requirements"]
        assert row["patch_feasibility"]["status"]
        assert row["runtime_payload_requirements"]["schema"]
        assert row["classification"] == "queued_by_projection"
        assert row["value_label"] == "queued_by_projection"


def test_spsi_opportunities_record_uspp_workload_extension_candidate(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")
    manifest = build_offload_opportunity_manifest(inventory)
    spsi_rows = [row for row in manifest["opportunities"] if row["kernel"] == "s_psi"]

    assert spsi_rows
    for row in spsi_rows:
        workload_selection = row["workload_selection"]
        assert (
            "ultrasoft_or_paw_pseudopotential_or_nontrivial_overlap_operator"
            in workload_selection["exercise_requirements"]
        )
        assert workload_selection["extension_candidates"]
        extension = workload_selection["extension_candidates"][0]
        assert extension["pseudo_family"] == "uspp"
        assert extension["variant_status"] == "formal_workload_variant_candidate"
        assert extension["offload_target_binding"]["workload_variant_id"] == (
            "qe_si_uspp_spsi_probe_v1"
        )
        assert "workload_variant_binding" in extension["promotion_policy"]


def test_workload_variant_search_space_formalizes_uspp_spsi_boundary(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")
    manifest = build_offload_opportunity_manifest(inventory)
    variant_space = build_workload_variant_search_space(manifest)

    spsi_ids = {
        row["opportunity_id"]
        for row in manifest["opportunities"]
        if row["kernel"] == "s_psi"
    }
    assert variant_space["schema_version"] == "dse.qe_workload_variant_search_space.v1"
    assert variant_space["workload_case_ids_participate_in_generic_identity"] is False
    assert variant_space["formal_variant_binding_affects_offload_identity"] is True
    assert variant_space["formal_workload_variant_count"] >= 1
    uspp = next(
        variant
        for variant in variant_space["variants"]
        if variant["variant_id"] == "qe_si_uspp_spsi_probe_v1"
    )
    assert uspp["variant_status"] == "formal_workload_variant_candidate"
    assert uspp["offload_target_binding_required_for_candidate_identity"] is True
    assert uspp["canonical_replacement_allowed"] is False
    assert set(uspp["applies_to_opportunity_ids"]) == spsi_ids


def test_bundle_search_and_attempt_queue_are_profile_priority_ranked(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")
    manifest = build_offload_opportunity_manifest(inventory)
    bundle_space = build_offload_bundle_search_space(manifest)
    queue = build_l4_offload_attempt_queue(bundle_space, max_attempts=8)

    profiled_non_hpsi = [
        row
        for row in manifest["opportunities"]
        if row["kernel"] != "h_psi"
        and row["profile_evidence"]["status"] == "fixture_profile_observed"
    ]
    assert profiled_non_hpsi

    bundle_scores = [
        row["selection_priority"]["score"] for row in bundle_space["bundles"]
    ]
    assert bundle_scores == sorted(bundle_scores, reverse=True)
    assert any(not row["hpsi_only"] for row in bundle_space["bundles"][:8])

    queue_scores = [
        row["selection_priority"]["score"] for row in queue["attempts"]
    ]
    assert queue_scores == sorted(queue_scores, reverse=True)
    assert any(
        any("h_psi" not in opportunity_id for opportunity_id in row["opportunity_ids"])
        for row in queue["attempts"]
    )
    assert queue["deliverable_complete"] is False
