#!/usr/bin/env python3
"""Complete-DSE release cardinality and freeze-gate tests."""

from __future__ import annotations

import copy

from dse_v2.codesign.complete_dse_search_space import (
    build_freeze_gate_verdict,
    build_release_cardinality_budget,
    build_release_l4_runtime_cost_report,
    build_release_subset_manifest,
    build_research_space_manifest,
)


def test_release_cardinality_budget_enforces_ambition_floor_and_caps():
    budget = build_release_cardinality_budget()

    assert budget["legal_release_candidates_target_min"] == 64
    assert budget["legal_release_candidates_target_max"] == 256
    assert budget["legal_release_candidates_hard_cap"] == 512
    assert budget["frozen_workload_cases_hard_cap"] == 8
    assert budget["l4_evidence_rows_hard_cap"] == 4096
    assert budget["research_to_release_ratio_cap"] == 0.05
    assert (
        budget["ambition_floor"]["min_legal_candidate_per_required_taxonomy"]
        == 1
    )
    assert budget["claim_boundary"].startswith("budget sizes the freeze")


def test_freeze_gate_passes_default_predeclared_subset_with_under_5_percent_ratio():
    subset = build_release_subset_manifest()
    research_space = build_research_space_manifest()
    verdict = build_freeze_gate_verdict(
        subset,
        research_space=research_space,
    )

    assert verdict["status"] == "passed"
    assert verdict["blockers"] == []
    assert verdict["research_to_release_ratio"] <= 0.05
    assert verdict["hard_completion_rule_preserved"] is True
    assert verdict["top_k_or_representative_completion_allowed"] is False


def test_freeze_gate_rejects_over_budget_candidate_counts():
    subset = copy.deepcopy(build_release_subset_manifest())
    subset["legal_candidate_count"] = 513
    verdict = build_freeze_gate_verdict(subset)

    assert verdict["status"] == "blocked"
    assert any(
        blocker["id"] == "candidate_count_over_hard_cap"
        for blocker in verdict["blockers"]
    )


def test_freeze_gate_rejects_top_k_representative_and_fixed_candidate_downgrades():
    subset = build_release_subset_manifest()

    for selection_kind in [
        "top_k",
        "representative",
        "pareto",
        "promoted_only",
    ]:
        verdict = build_freeze_gate_verdict(
            subset,
            selection_policy={"selection_kind": selection_kind},
        )
        assert verdict["status"] == "blocked"
        assert any(
            blocker["id"] == "downgraded_subset_selection"
            for blocker in verdict["blockers"]
        )

    fixed = build_freeze_gate_verdict(
        subset,
        selection_policy={
            "selection_kind": "predeclared_finite_release_subset",
            "fixed_candidate_only": True,
        },
    )
    assert fixed["status"] == "blocked"
    assert any(
        blocker["id"] == "fixed_candidate_only_downgrade"
        for blocker in fixed["blockers"]
    )


def test_freeze_gate_rejects_release_subset_that_is_more_than_5_percent_of_research_space():
    subset = build_release_subset_manifest()
    tiny_research = build_research_space_manifest()
    tiny_research["estimated_broad_candidate_count"] = 10

    verdict = build_freeze_gate_verdict(subset, research_space=tiny_research)

    assert verdict["status"] == "blocked"
    assert any(
        blocker["id"] == "release_subset_not_ambitiously_pruned"
        for blocker in verdict["blockers"]
    )


def test_l4_runtime_cost_report_blocks_rows_above_hard_cap():
    subset = build_release_subset_manifest()
    passed = build_release_l4_runtime_cost_report(
        subset,
        frozen_workload_case_count=4,
    )
    blocked = build_release_l4_runtime_cost_report(
        subset,
        frozen_workload_case_count=500,
    )

    assert passed["status"] == "passed"
    assert passed["required_l4_evidence_rows"] == (
        subset["legal_candidate_count"] * 4
    )
    assert blocked["status"] == "blocked"
    assert blocked["required_l4_evidence_rows"] > blocked["hard_cap"]
    assert blocked["claim_boundary"].startswith("cost estimate only")
