#!/usr/bin/env python3
"""Complete-DSE release universe matrix closure tests."""

from __future__ import annotations

import copy

from dse_v2.codesign.complete_dse_search_space import (
    DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
    RELEASE_MATRIX_ROW_STATUSES,
    build_candidate_workflow_deployment_target_matrix,
    build_freeze_gate_verdict,
    build_release_subset_manifest,
    validate_candidate_workflow_deployment_target_matrix,
)


def _blocker_ids(validation):
    return {blocker["id"] for blocker in validation["blockers"]}


def test_release_subset_emits_reproducible_candidate_workflow_deployment_target_gate_matrix():
    subset = build_release_subset_manifest()
    matrix = subset["candidate_workflow_deployment_target_matrix"]
    rebuilt = build_candidate_workflow_deployment_target_matrix(subset)
    validation = validate_candidate_workflow_deployment_target_matrix(subset, matrix)

    assert matrix == rebuilt
    assert validation["valid"] is True
    assert validation["blockers"] == []
    assert matrix["allowed_row_statuses"] == list(RELEASE_MATRIX_ROW_STATUSES)
    assert set(row["status"] for row in matrix["rows"]).issubset(
        RELEASE_MATRIX_ROW_STATUSES
    )
    assert matrix["candidate_count"] == subset["legal_candidate_count"]
    assert matrix["workflow_case_count"] == DEFAULT_FROZEN_WORKLOAD_CASE_COUNT == 6
    assert matrix["workflow_case_ids"] == [
        "release_workflow_case_00",
        "release_workflow_case_01",
        "release_workflow_case_02",
        "release_workflow_case_03",
        "release_workflow_case_04",
        "release_workflow_case_05",
    ]
    assert matrix["evidence_gate_count"] >= 1
    assert matrix["row_count"] == matrix["expected_row_count"]
    assert (
        matrix["matrix_hash"]
        == subset["candidate_workflow_deployment_target_matrix_rows_hash"]
    )
    assert (
        subset["generation_provenance"][
            "candidate_workflow_deployment_target_matrix_rows_hash"
        ]
        == matrix["matrix_hash"]
    )
    assert (
        subset["generation_provenance"][
            "candidate_workflow_deployment_target_matrix_validation_hash"
        ]
        == validation["validation_hash"]
    )
    assert matrix["deliverable_complete"] is False
    assert matrix["claim_boundary"].startswith("Step2 release-universe matrix")

    sample = matrix["rows"][0]
    assert sample["candidate_id"] in subset["legal_candidate_ids"]
    assert sample["deployment_boundary_id"]
    assert sample["target_platform_id"]
    assert sample["target_platform_kind"] in {"fpga", "asic"}
    assert sample["runtime_scheduling"]["runtime_schedule_id"]
    assert sample["runtime_scheduling"]["co_scheduling_policy_id"]
    assert sample["runtime_scheduling"]["queue_policy"]
    assert sample["workflow_case_id"] in matrix["workflow_case_ids"]
    assert sample["evidence_gate_id"] in matrix["evidence_gate_ids"]
    assert sample["row_provenance"]["candidate_identity_hash"]
    assert sample["row_provenance"]["release_subset_hash"] == subset[
        "release_subset_hash"
    ]
    assert sample["row_provenance"]["runtime_schedule_affects_row"] is True
    identity_provenance = sample["candidate_identity_provenance"]
    assert identity_provenance["identity_hash"] == sample["row_provenance"][
        "candidate_identity_hash"
    ]
    assert {
        "deployment_boundary_parameters",
        "algorithm_parameters",
        "architecture_parameters",
        "mapping_layout_parameters",
        "compile_time_schedule_parameters",
        "runtime_scheduling_parameters",
        "target_platform_parameters",
    } == set(identity_provenance["identity_layers"])
    deployment = identity_provenance["identity_layers"][
        "deployment_boundary_parameters"
    ]
    assert deployment["host_device_partition_id"]
    assert deployment["accelerated_kernels"]
    assert deployment["cpu_retained_stages"]
    assert deployment["descriptor_granularity"]
    assert deployment["fallback_policy"]


def test_matrix_validation_fails_closed_for_missing_target_rows_wrong_target_and_invalid_status():
    subset = build_release_subset_manifest()
    matrix = copy.deepcopy(subset["candidate_workflow_deployment_target_matrix"])
    asic_row = next(
        row for row in matrix["rows"] if row["target_platform_kind"] == "asic"
    )
    matrix["rows"] = [
        row for row in matrix["rows"] if row["row_id"] != asic_row["row_id"]
    ]
    missing = validate_candidate_workflow_deployment_target_matrix(subset, matrix)

    assert missing["valid"] is False
    assert "missing_expected_matrix_rows" in _blocker_ids(missing)
    assert "matrix_row_count_mismatch" in _blocker_ids(missing)

    wrong_target = copy.deepcopy(subset["candidate_workflow_deployment_target_matrix"])
    asic_index = next(
        index
        for index, row in enumerate(wrong_target["rows"])
        if row["target_platform_kind"] == "asic"
    )
    wrong_target["rows"][asic_index]["target_platform_id"] = "fpga_vivado_release_v1"
    wrong_target["rows"][asic_index]["target_platform_kind"] = "fpga"
    wrong_validation = validate_candidate_workflow_deployment_target_matrix(subset, wrong_target)

    assert wrong_validation["valid"] is False
    assert "matrix_row_axis_mismatch" in _blocker_ids(wrong_validation)
    assert "unexpected_matrix_rows" in _blocker_ids(wrong_validation)

    invalid_status = copy.deepcopy(subset["candidate_workflow_deployment_target_matrix"])
    invalid_status["rows"][0]["status"] = "passed"
    status_validation = validate_candidate_workflow_deployment_target_matrix(
        subset, invalid_status
    )

    assert status_validation["valid"] is False
    assert "invalid_matrix_row_status" in _blocker_ids(status_validation)


def test_matrix_validation_rejects_collapsed_fpga_asic_candidate_id_rows():
    subset = build_release_subset_manifest()
    matrix = copy.deepcopy(subset["candidate_workflow_deployment_target_matrix"])
    fpga_id = next(
        row["candidate_id"]
        for row in matrix["rows"]
        if row["target_platform_kind"] == "fpga"
    )
    for row in matrix["rows"]:
        if row["target_platform_kind"] == "asic":
            row["candidate_id"] = fpga_id
            row["row_provenance"]["candidate_id"] = fpga_id
            break

    validation = validate_candidate_workflow_deployment_target_matrix(subset, matrix)

    assert validation["valid"] is False
    assert "matrix_row_candidate_target_identity_mismatch" in _blocker_ids(
        validation
    )
    assert "matrix_row_axis_mismatch" in _blocker_ids(validation)


def test_final_release_universe_claim_still_rejects_top_k_fixed_or_missing_matrix_provenance():
    subset = build_release_subset_manifest()
    no_matrix = copy.deepcopy(subset)
    no_matrix.pop("candidate_workflow_deployment_target_matrix", None)
    no_matrix.pop("candidate_workflow_deployment_target_matrix_rows_hash", None)
    no_matrix["generation_provenance"].pop(
        "candidate_workflow_deployment_target_matrix_rows_hash", None
    )
    no_matrix["generation_provenance"].pop(
        "candidate_workflow_deployment_target_matrix_validation_hash", None
    )

    missing = build_freeze_gate_verdict(
        no_matrix,
        selection_policy={
            "selection_kind": "predeclared_finite_release_subset",
            "final_release_universe_claim": True,
        },
    )
    top_k = build_freeze_gate_verdict(
        subset,
        selection_policy={
            "selection_kind": "top_k",
            "final_release_universe_claim": True,
            "candidate_workflow_deployment_target_matrix_rows_hash": subset[
                "candidate_workflow_deployment_target_matrix_rows_hash"
            ],
        },
    )
    fixed = build_freeze_gate_verdict(
        subset,
        selection_policy={
            "selection_kind": "predeclared_finite_release_subset",
            "fixed_candidate_only": True,
            "final_release_universe_claim": True,
            "candidate_workflow_deployment_target_matrix_rows_hash": subset[
                "candidate_workflow_deployment_target_matrix_rows_hash"
            ],
        },
    )

    assert missing["status"] == "blocked"
    assert "missing_candidate_workflow_deployment_target_matrix_provenance" in {
        blocker["id"] for blocker in missing["blockers"]
    }
    assert top_k["status"] == "blocked"
    assert "downgraded_subset_selection" in {blocker["id"] for blocker in top_k["blockers"]}
    assert fixed["status"] == "blocked"
    assert "fixed_candidate_only_downgrade" in {blocker["id"] for blocker in fixed["blockers"]}
    assert top_k["final_release_universe_eligible"] is False
    assert fixed["final_release_universe_eligible"] is False


def test_final_release_universe_claim_rejects_invalid_matrix_even_with_provenance_hash():
    subset = build_release_subset_manifest()
    forged = copy.deepcopy(subset)
    forged["candidate_workflow_deployment_target_matrix"]["rows"].pop()
    forged["candidate_workflow_deployment_target_matrix"]["row_count"] -= 1

    verdict = build_freeze_gate_verdict(
        forged,
        selection_policy={
            "selection_kind": "predeclared_finite_release_subset",
            "final_release_universe_claim": True,
            "candidate_workflow_deployment_target_matrix_rows_hash": subset[
                "candidate_workflow_deployment_target_matrix_rows_hash"
            ],
        },
    )

    assert verdict["status"] == "blocked"
    assert "candidate_workflow_deployment_target_matrix_invalid" in {
        blocker["id"] for blocker in verdict["blockers"]
    }
    assert verdict["final_release_universe_eligible"] is False
