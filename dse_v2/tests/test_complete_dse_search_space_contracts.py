#!/usr/bin/env python3
"""Complete-DSE search-space two-tier contract tests."""

from __future__ import annotations

import copy
import json
import subprocess
import sys

from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.codesign.complete_dse_search_space import (
    CLAIM_LABELS,
    IDENTITY_LAYER_KEYS,
    NON_IDENTITY_FIELDS,
    build_architecture_search_space,
    build_candidate_generation_report,
    build_complete_dse_search_effectiveness_report,
    build_freeze_gate_verdict,
    build_release_subset_manifest,
    build_search_space_schema,
    default_release_candidate_seed_rows,
    default_release_seed_rows,
    validate_architecture_search_space,
    validate_release_subset_candidate_bindings,
    write_complete_dse_search_space_artifacts,
)
from dse_v2.mapping.search_policy import (
    HierarchicalFunnelSearchPolicy,
    SearchProblem,
    build_search_iteration_plan,
    search_checkpoint_from_iteration_plan,
)


def test_search_space_schema_separates_research_and_release_tiers():
    schema = build_search_space_schema()

    assert (
        schema["schema_version"] == "dse.codesign.complete_dse_search_space.v1"
    )
    assert set(schema["tiers"]) == {"research_space", "release_subset"}
    assert schema["tiers"]["research_space"]["completion_eligible"] is False
    assert schema["tiers"]["release_subset"]["completion_eligible"] is True
    assert schema["tiers"]["research_space"]["finite_release_subset"] is False
    assert schema["tiers"]["release_subset"]["finite_release_subset"] is True
    assert (
        "deliverable_complete"
        not in schema["tiers"]["research_space"]["allowed_claims"]
    )
    assert (
        "deliverable_complete"
        in schema["tiers"]["release_subset"]["allowed_claims"]
    )
    assert schema["identity_layers"] == list(IDENTITY_LAYER_KEYS)
    assert schema["non_identity_fields"] == list(NON_IDENTITY_FIELDS)
    assert set(CLAIM_LABELS).issuperset(
        schema["tiers"]["release_subset"]["allowed_claims"]
    )
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
    assert (
        search_space["claim_boundary"]
        == "foundation artifacts only; no trusted speedup or completion claim"
    )
    assert (
        search_space["research_space_manifest"]["completion_eligible"] is False
    )
    assert search_space["release_subset_manifest"]["finite"] is True
    assert search_space["target_platform_space"]["required_target_platform_kinds"] == [
        "fpga",
        "asic",
    ]
    assert (
        search_space["candidate_generation_report"][
            "stable_candidate_ids_emitted"
        ]
        is True
    )
    assert (
        search_space["candidate_generation_report"][
            "candidate_identity_binding_valid"
        ]
        is True
    )
    assert (
        search_space["candidate_generation_report"]["generation_mode"]
        == "bounded_compatible_cartesian_product"
    )
    assert (
        search_space["complete_dse_search_effectiveness_report"]["status"]
        == "passed"
    )
    assert (
        search_space["complete_dse_search_effectiveness_report"][
            "can_name_best_fpga_or_asic"
        ]
        is False
    )
    budget = search_space["release_cardinality_budget"]
    assert (
        search_space["release_subset_manifest"]["legal_candidate_count"]
        >= budget["legal_release_candidates_target_min"]
    )
    assert (
        search_space["release_subset_manifest"]["legal_candidate_count"]
        <= budget["legal_release_candidates_target_max"]
    )
    assert (
        search_space["workload_architecture_prior_report"][
            "workload_facts_affect_identity"
        ]
        is False
    )
    assert (
        search_space["schedule_legality_report"]["summary"][
            "all_runtime_schedule_bindings_legal"
        ]
        is True
    )
    assert search_space["candidate_generation_report"][
        "excluded_from_identity"
    ] == list(NON_IDENTITY_FIELDS)
    assert (
        search_space["freeze_gate_verdict"][
            "top_k_or_representative_completion_allowed"
        ]
        is False
    )
    assert search_space["freeze_gate_verdict"]["status"] == "passed"


def test_artifact_writer_and_cli_emit_machine_readable_foundation_files(
    tmp_path,
):
    out_dir = tmp_path / "direct"
    status = write_complete_dse_search_space_artifacts(out_dir)
    assert status["status"] == "passed"
    for name in [
        "search_space_schema.json",
        "architecture_search_space.json",
        "target_platform_space.json",
        "workload_architecture_prior_report.json",
        "parameter_profile_manifest.json",
        "release_subset_manifest.json",
        "candidate_generation_report.json",
        "complete_dse_search_effectiveness_report.json",
        "release_pruning_rationale_report.json",
        "schedule_legality_report.json",
        "freeze_gate_verdict.json",
        "validation_report.json",
        "status.json",
    ]:
        assert (out_dir / name).exists()

    architecture_search_space = json.loads(
        (out_dir / "architecture_search_space.json").read_text(
            encoding="utf-8"
        )
    )
    assert architecture_search_space["search_space_hash"]
    assert architecture_search_space["freeze_gate_verdict"][
        "claim_boundary"
    ].startswith("freeze gate only")

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
    assert (cli_out / "complete_dse_search_effectiveness_report.json").exists()
    assert (cli_out / "status.json").exists()


def test_release_subset_and_freeze_gate_are_deterministically_replayable(
    tmp_path,
):
    first_subset = build_release_subset_manifest()
    second_subset = build_release_subset_manifest()
    assert first_subset["release_subset_hash"] == second_subset[
        "release_subset_hash"
    ]
    assert first_subset["deterministic_replay"]["replay_hash"] == second_subset[
        "deterministic_replay"
    ]["replay_hash"]
    assert first_subset["generation_provenance"]["candidate_order"] == [
        candidate["candidate_id"] for candidate in first_subset["candidates"]
    ]

    verdict = build_freeze_gate_verdict(first_subset)
    assert verdict["status"] == "passed"
    assert verdict["freeze_inputs"]["release_subset_hash"] == first_subset[
        "release_subset_hash"
    ]
    assert verdict["provenance"] == {
        "predeclared_release_subset": True,
        "generated_parameterized_release_universe": True,
        "all_candidates_classified_before_freeze": True,
        "candidate_ids_recomputed_from_identity": True,
        "post_hoc_top_k_or_fixed_list": False,
        "workload_or_evidence_axes_in_identity_allowed": False,
    }
    assert verdict["deterministic_replay"]["artifact_name"] == (
        "freeze_gate_verdict.json"
    )

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    write_complete_dse_search_space_artifacts(first_dir)
    write_complete_dse_search_space_artifacts(second_dir)
    for name in [
        "release_subset_manifest.json",
        "complete_dse_search_effectiveness_report.json",
        "freeze_gate_verdict.json",
        "architecture_search_space.json",
    ]:
        assert json.loads((first_dir / name).read_text()) == json.loads(
            (second_dir / name).read_text()
        )


def test_release_candidates_are_recommendation_inputs_derived_from_search_universe():
    subset = build_release_subset_manifest()
    report = build_candidate_generation_report(subset)
    matrix = subset["candidate_workflow_deployment_target_matrix"]
    legal_ids = set(subset["legal_candidate_ids"])

    assert report["recommendation_candidate_input_contract"][
        "fixed_or_manual_top_k_seed_source_allowed"
    ] is False
    assert report["recommendation_candidate_input_contract"][
        "derived_from_reproducible_release_universe"
    ] is True
    assert report["recommendation_candidate_input_contract"][
        "candidate_workflow_deployment_target_matrix_hash"
    ] == matrix["matrix_hash"]
    assert report["recommendation_candidate_input_contract"][
        "evidence_rows_fail_closed_by_default"
    ] is True
    assert report["recommendation_candidate_input_contract"][
        "artifact_provenance"
    ]["release_subset_hash"] == subset["release_subset_hash"]

    for candidate in subset["candidates"]:
        assert candidate["candidate_id"] in legal_ids
        assert candidate["generation_source"] == "bounded_parameterized_release_generator_v1"
        provenance = candidate["recommendation_input_provenance"]
        assert provenance["release_subset_hash"] == subset["release_subset_hash"]
        assert provenance["candidate_record_hash"] == candidate["record_hash"]
        assert provenance["fixed_or_manual_top_k_seed"] is False
        assert provenance["search_policy_provenance"]["generation_source"] == (
            "bounded_parameterized_release_generator_v1"
        )
        assert provenance["search_policy_provenance"]["pruning_rationale_hash"] == (
            subset["generation_provenance"]["pruning_rationale_hash"]
        )
        assert provenance["legality_provenance"]["legal"] is True
        assert provenance["legality_provenance"]["illegal_reasons"] == []
        assert provenance["deployment_boundary_provenance"][
            "deployment_boundary_id"
        ]
        assert provenance["target_platform_provenance"]["platform_kind"] in {
            "fpga",
            "asic",
        }
        assert provenance["runtime_scheduling_provenance"][
            "runtime_schedule_id"
        ]
        assert provenance["runtime_scheduling_provenance"][
            "co_scheduling_policy_id"
        ]
        assert provenance["artifact_provenance"]["release_subset_hash"] == subset[
            "release_subset_hash"
        ]
        evidence = provenance["evidence_matrix_provenance"]
        assert evidence["matrix_hash"] == matrix["matrix_hash"]
        assert evidence["missing_evidence_rows_fail_closed"] is True
        assert evidence["trusted_ppa_evidence_ready"] is False
        assert "blocked_missing_input" in evidence["observed_row_statuses"]


def test_search_iteration_plan_proposals_and_checkpoints_preserve_runtime_and_artifact_provenance():
    subset = build_release_subset_manifest()
    candidate = subset["candidates"][0]
    identity_layers = candidate["identity"]["identity_layers"]
    runtime = identity_layers["runtime_scheduling_parameters"]
    problem = SearchProblem(
        problem_id="p-release-runtime-provenance",
        workload_run_id="w-release-runtime-provenance",
        objective="maximize throughput",
        parameters={
            "release_lane": ["release"],
            "complete_dse_candidate_id": [candidate["candidate_id"]],
            "architecture_id": [
                identity_layers["architecture_parameters"]["taxonomy_id"]
            ],
            "taxonomy_id": [identity_layers["architecture_parameters"]["taxonomy_id"]],
            "mapping_id": [identity_layers["mapping_layout_parameters"]["mapping_id"]],
            "compile_schedule_id": [
                identity_layers["compile_time_schedule_parameters"][
                    "compile_schedule_id"
                ]
            ],
            "runtime_schedule_id": [runtime["runtime_schedule_id"]],
            "co_scheduling_policy_id": [runtime["co_scheduling_policy_id"]],
            "queue_policy": [runtime["queue_policy"]],
            "engine_assignment": [runtime["engine_assignment"]],
            "queue_depth": [runtime["queue_depth"]],
            "overlap_window": [runtime["overlap_window"]],
            "parameter_profile_id": [runtime["parameter_profile_id"]],
            "candidate_identity": [candidate["identity"]],
            "recommendation_input_provenance": [
                candidate["recommendation_input_provenance"]
            ],
            "candidate_record_hash": [candidate["record_hash"]],
            "release_subset_hash": [subset["release_subset_hash"]],
            "step2_candidate_rank_score": [candidate["record_hash"] != ""],
        },
    )
    policy = HierarchicalFunnelSearchPolicy(bottleneck_keys=("step2_candidate_rank_score",))
    checkpoint = policy.checkpoint(problem).to_dict()

    plan = build_search_iteration_plan(
        search_checkpoint={
            "schema_version": "dse.step2.search_checkpoint_summary.v1",
            "search_policy_name": policy.policy_name,
            "search_policy_problem": problem.to_dict(),
            "search_policy_checkpoint": checkpoint,
            "search_policy_proposal_budget": 1,
        },
        feedback_update={
            "schema_version": "dse.contract.feedback_update.v1",
            "campaign_id": "campaign",
            "workload_run_id": problem.workload_run_id,
            "trial_id": "trial",
            "updates": [],
            "source_artifact_hashes": {},
        },
    )
    summary = search_checkpoint_from_iteration_plan(
        plan,
        refs={"search_iteration_plan": "step2/search_iteration_plan.json"},
    )

    proposal = plan["next_candidates"][0]
    checkpoint_candidate = summary["search_policy_checkpoint"]["candidates"][0]

    assert proposal["runtime_scheduling_provenance"]["runtime_schedule_id"] == runtime[
        "runtime_schedule_id"
    ]
    assert proposal["runtime_scheduling_provenance"]["co_scheduling_policy_id"] == runtime[
        "co_scheduling_policy_id"
    ]
    assert proposal["runtime_scheduling_provenance"]["queue_policy"] == runtime["queue_policy"]
    assert proposal["artifact_provenance"]["release_subset_hash"] == subset[
        "release_subset_hash"
    ]
    assert proposal["artifact_provenance"]["candidate_record_hash"] == candidate["record_hash"]
    assert proposal["artifact_provenance"]["candidate_identity_hash"] == candidate["identity_hash"]
    assert summary["source_artifact_provenance"]["input_search_checkpoint"]["ref"] == "step2/search_checkpoint.json"
    assert summary["source_artifact_provenance"]["search_iteration_plan"]["ref"] == "step2/search_iteration_plan.json"
    assert summary["search_policy_candidates"][0]["runtime_scheduling_provenance"]["queue_depth"] == runtime[
        "queue_depth"
    ]
    assert summary["search_policy_candidates"][0]["artifact_provenance"]["release_subset_hash"] == subset[
        "release_subset_hash"
    ]
    assert checkpoint_candidate["runtime_scheduling_provenance"]["overlap_window"] == runtime[
        "overlap_window"
    ]
    assert checkpoint_candidate["artifact_provenance"]["candidate_record_hash"] == candidate["record_hash"]


def test_release_subset_validation_rejects_forged_candidate_identity_bindings():
    subset = build_release_subset_manifest()
    forged = json.loads(json.dumps(subset))
    forged["candidates"][0]["candidate_id"] = "cdse_forged_release_candidate"
    forged["legal_candidate_ids"][0] = "cdse_forged_release_candidate"

    binding = validate_release_subset_candidate_bindings(forged)
    report = build_candidate_generation_report(forged)
    verdict = build_freeze_gate_verdict(forged)

    assert binding["valid"] is False
    fields = {error["field"] for error in binding["errors"]}
    assert "candidates[0].candidate_id" in fields
    assert "release_subset_hash" in fields
    assert report["status"] == "failed"
    assert report["candidate_identity_binding_valid"] is False
    assert verdict["status"] == "blocked"
    assert any(
        blocker["id"] == "candidate_identity_binding_invalid"
        for blocker in verdict["blockers"]
    )


def test_release_subset_validation_rejects_non_object_candidate_rows():
    subset = build_release_subset_manifest()
    forged = json.loads(json.dumps(subset))
    forged_index = len(forged["candidates"])
    forged["candidates"].append("not-a-candidate")
    forged["release_subset_hash"] = stable_json_hash(
        {
            key: value
            for key, value in forged.items()
            if key != "release_subset_hash"
        }
    )

    binding = validate_release_subset_candidate_bindings(forged)

    assert binding["valid"] is False
    assert any(
        error["field"] == f"candidates[{forged_index}]"
        and error["message"] == "candidate row must be an object"
        for error in binding["errors"]
    )
    assert "release_subset_hash" not in {
        error["field"] for error in binding["errors"]
    }


def test_release_subset_validation_rejects_custom_seed_source_order():
    reordered_subset = build_release_subset_manifest(
        seed_rows=list(reversed(default_release_candidate_seed_rows()))
    )

    binding = validate_release_subset_candidate_bindings(reordered_subset)
    verdict = build_freeze_gate_verdict(reordered_subset)

    assert binding["valid"] is False
    fields = {error["field"] for error in binding["errors"]}
    assert "generation_provenance.seed_rows_hash" in fields
    assert "generation_provenance.candidate_order" in fields
    assert "deterministic_replay.input_hash" in fields
    assert verdict["status"] == "blocked"


def test_architecture_search_space_validation_rejects_stale_release_subset_sidecars():
    search_space = build_architecture_search_space()
    reordered_subset = build_release_subset_manifest(
        seed_rows=list(reversed(default_release_candidate_seed_rows()))
    )
    stale = json.loads(json.dumps(search_space))
    stale["release_subset_manifest"] = reordered_subset

    validation = validate_architecture_search_space(stale)

    assert validation["status"] == "failed"
    assert validation["checks"][
        "release_subset_candidate_identity_binding_valid"
    ] is False
    assert validation["checks"][
        "candidate_generation_report_matches_release_subset"
    ] is False
    assert validation["checks"][
        "legality_pruning_report_matches_release_subset"
    ] is False
    assert validation["checks"][
        "release_pruning_rationale_report_matches_release_subset"
    ] is False
    assert validation["checks"][
        "release_l4_runtime_cost_report_matches_release_subset"
    ] is False
    assert validation["checks"][
        "freeze_gate_verdict_matches_release_subset"
    ] is False


def test_architecture_search_space_validation_rejects_rehashed_foundation_tamper():
    search_space = build_architecture_search_space()
    forged = json.loads(json.dumps(search_space))
    forged["architecture_taxonomy"]["required_release_v1_taxonomy_ids"] = [
        "streaming_pipeline"
    ]
    forged["architecture_taxonomy"]["taxonomy_hash"] = "self-authorized-forgery"
    forged["search_space_hash"] = stable_json_hash(
        {
            key: value
            for key, value in forged.items()
            if key != "search_space_hash"
        }
    )

    validation = validate_architecture_search_space(forged)

    assert validation["status"] == "failed"
    assert validation["checks"]["search_space_hash_matches_content"] is True
    assert validation["checks"]["architecture_taxonomy_matches_builder"] is False
    assert validation["checks"][
        "release_subset_candidate_identity_binding_valid"
    ] is True


def test_architecture_search_space_validation_rejects_non_object_sidecars_without_crashing():
    search_space = build_architecture_search_space()
    forged = json.loads(json.dumps(search_space))
    forged["candidate_generation_report"] = []
    forged["freeze_gate_verdict"] = "not-a-verdict"

    validation = validate_architecture_search_space(forged)

    assert validation["status"] == "failed"
    assert {
        error["field"] for error in validation["shape_errors"]
    } == {"candidate_generation_report", "freeze_gate_verdict"}
    assert validation["checks"]["candidate_generation_report_passed"] is False
    assert validation["checks"]["freeze_gate_passed"] is False


def test_search_effectiveness_report_audits_default_axis_and_queue_diversity():
    from dse_v2.codesign.complete_dse_step2_binding import (
        build_complete_dse_step2_binding_bundle,
    )

    subset = build_release_subset_manifest()
    queue = build_complete_dse_step2_binding_bundle(subset)[
        "step3_simulation_queue.json"
    ]
    report = build_complete_dse_search_effectiveness_report(
        subset,
        step3_queue=queue,
    )

    assert report["status"] == "passed"
    assert report["candidate_counts"]["legal_candidate_count"] == subset[
        "legal_candidate_count"
    ]
    assert report["axis_coverage"]["taxonomy"]["observed_id_count"] == 9
    assert report["axis_coverage"]["algorithm"]["observed_id_count"] == 4
    assert report["axis_coverage"]["mapping"]["observed_id_count"] == 4
    assert report["axis_coverage"]["compile_schedule"]["observed_id_count"] == 4
    assert report["axis_coverage"]["runtime_schedule"]["observed_id_count"] == 4
    assert report["axis_coverage"]["parameter_profile"]["observed_id_count"] == 2
    assert report["axis_coverage"]["target_platform"]["observed_id_count"] == 2
    assert report["template_coverage"]["passed"] is True
    assert report["cross_axis_diversity"]["unique_identity_tuple_count"] == subset[
        "legal_candidate_count"
    ]
    assert report["queue_preservation"]["status"] == "passed"
    assert report["score_diversity"]["status"] == "not_applicable"
    assert report["deliverable_complete"] is False
    assert report["can_name_best_fpga_or_asic"] is False


def test_search_effectiveness_report_blocks_collapsed_or_missing_axes():
    subset = copy.deepcopy(build_release_subset_manifest())
    subset["candidates"] = [
        row
        for row in subset["candidates"]
        if row["identity"]["identity_layers"]["algorithm_parameters"][
            "algorithm_id"
        ]
        == "streaming_fft_rho_pipeline"
    ]
    subset["candidate_count"] = len(subset["candidates"])
    subset["legal_candidate_count"] = len(subset["candidates"])
    subset["legal_candidate_ids"] = [
        row["candidate_id"] for row in subset["candidates"]
    ]

    report = build_complete_dse_search_effectiveness_report(subset)
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}

    assert report["status"] == "blocked"
    assert "axis_missing_expected_values" in blocker_ids
    assert "axis_degenerate" in blocker_ids
    assert report["axis_coverage"]["algorithm"]["degenerate"] is True

    profile_collapsed = copy.deepcopy(build_release_subset_manifest())
    profile_collapsed["candidates"] = [
        row
        for row in profile_collapsed["candidates"]
        if row["identity"]["identity_layers"]["algorithm_parameters"][
            "parameter_profile_id"
        ]
        == "latency_balanced"
    ]
    profile_collapsed["candidate_count"] = len(profile_collapsed["candidates"])
    profile_collapsed["legal_candidate_count"] = len(
        profile_collapsed["candidates"]
    )
    profile_collapsed["legal_candidate_ids"] = [
        row["candidate_id"] for row in profile_collapsed["candidates"]
    ]

    profile_report = build_complete_dse_search_effectiveness_report(
        profile_collapsed
    )

    assert profile_report["status"] == "blocked"
    assert profile_report["axis_coverage"]["parameter_profile"][
        "missing_expected_ids"
    ] == ["throughput_scaled"]


def test_search_effectiveness_report_blocks_duplicate_identity_and_hashes():
    subset = copy.deepcopy(build_release_subset_manifest())
    duplicate = copy.deepcopy(subset["candidates"][0])
    subset["candidates"].append(duplicate)
    subset["candidate_count"] = len(subset["candidates"])
    subset["legal_candidate_count"] = len(subset["candidates"])
    subset["legal_candidate_ids"] = [
        row["candidate_id"] for row in subset["candidates"]
    ]

    report = build_complete_dse_search_effectiveness_report(subset)
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}

    assert report["status"] == "blocked"
    assert {
        "duplicate_candidate_ids",
        "duplicate_identity_hashes",
        "duplicate_record_hashes",
        "duplicate_identity_tuples",
    }.issubset(blocker_ids)


def test_search_effectiveness_report_blocks_missing_identity_integrity_fields():
    subset = copy.deepcopy(build_release_subset_manifest())
    subset["candidates"][0]["identity_hash"] = None
    subset["candidates"][1]["record_hash"] = None
    subset["candidates"][2]["identity"]["identity_layers"][
        "runtime_scheduling_parameters"
    ].pop("runtime_schedule_id")

    report = build_complete_dse_search_effectiveness_report(subset)
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}

    assert report["status"] == "blocked"
    assert {
        "missing_identity_hash",
        "missing_record_hash",
        "missing_identity_tuple_fields",
    }.issubset(blocker_ids)
    assert report["identity_integrity"]["all_identity_hashes_present"] is False
    assert report["identity_integrity"]["all_record_hashes_present"] is False
    assert (
        report["identity_integrity"]["all_identity_tuple_fields_present"]
        is False
    )


def test_search_effectiveness_report_marks_top_k_policy_non_exhaustive():
    subset = build_release_subset_manifest()
    report = build_complete_dse_search_effectiveness_report(
        subset,
        selection_policy={"selection_kind": "top_k"},
    )

    assert report["status"] == "blocked"
    assert any(
        blocker["id"] == "downgraded_subset_selection"
        for blocker in report["blockers"]
    )
    assert report["search_policy"]["intended_exhaustive_release_universe"] is True
    assert report["search_policy"]["exhaustive_release_universe"] is False
    assert (
        report["search_policy"]["validated_exhaustive_release_universe"]
        is False
    )


def test_search_effectiveness_report_blocks_step2_queue_candidate_drop():
    from dse_v2.codesign.complete_dse_step2_binding import (
        build_complete_dse_step2_binding_bundle,
    )

    subset = build_release_subset_manifest()
    queue = copy.deepcopy(
        build_complete_dse_step2_binding_bundle(subset)[
            "step3_simulation_queue.json"
        ]
    )
    queue["entries"] = queue["entries"][:-1]
    queue["candidate_ids"] = [
        entry["candidate_id"] for entry in queue["entries"]
    ]
    queue["entry_count"] = len(queue["entries"])

    report = build_complete_dse_search_effectiveness_report(
        subset,
        step3_queue=queue,
    )
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}

    assert report["status"] == "blocked"
    assert "step2_queue_drops_release_candidate" in blocker_ids
    assert report["queue_preservation"]["status"] == "blocked"
