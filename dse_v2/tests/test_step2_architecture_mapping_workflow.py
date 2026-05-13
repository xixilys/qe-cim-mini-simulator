#!/usr/bin/env python3
"""Step2 architecture/mapping workflow regressions."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload import (
    WorkloadPackage,
    create_dynamic_custom_graph,
    create_graph_analytics_graph,
    create_sparse_spmv_graph,
    create_stencil_streaming_graph,
    create_tensor_chain_graph,
    create_vector_search_graph,
    package_from_graph,
)
from dse_v2.reference_workloads.dft_qe import QE_SCF_REQUIRED_COVERAGE, create_qe_reference_package
from dse_v2.mapping.step2_workflow import (
    STEP2_LOW_FIDELITY_ARTIFACTS,
    STEP2_REQUIRED_MAPPING_ARTIFACTS,
    load_step2_design_point,
    run_step2_architecture_screening_workflow,
    run_step2_architecture_mapping_workflow,
    validate_step2_artifacts,
)


REPRESENTATIVE_BUILDERS = {
    "ml_tensor": create_tensor_chain_graph,
    "sparse_la": create_sparse_spmv_graph,
    "stencil_streaming": create_stencil_streaming_graph,
    "graph_analytics": create_graph_analytics_graph,
    "database_vector_search": create_vector_search_graph,
    "dynamic_custom": lambda graph_id: create_dynamic_custom_graph(graph_id, supported=True),
}


QE_PHASE_NAMES = {"h_psi", "s_psi", "diagonalize", "mix_rho", "veff"}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _policy_candidate_hints(graph: ComputeGraph, *, review_flags=None):
    node_ids = list(graph.nodes)
    return {
        "schema_version": "dse.step2.candidate_hints.v1",
        "policy_id": "dft_reference_step2",
        "domain_key": "dft",
        "matched": True,
        "review_flags": list(review_flags or ["insufficient_evidence"]),
        "review_required": True,
        "claim_boundary": "candidate_only",
        "node_target_preferences": [
            {
                "node_id": node_ids[0],
                "preferred_targets": ["fpga", "gpu", "host"],
                "reason": "phase-aware streaming offload preference",
            },
            {
                "node_id": node_ids[-1],
                "preferred_targets": ["gpu", "fpga", "host"],
                "reason": "phase-aware dense/offload preference",
            },
        ],
        "mapping_seeds": [
            {
                "seed_name": "phase_aware_balanced",
                "mapping": {node_ids[0]: "fpga", node_ids[-1]: "gpu"},
                "annotations": {"seed_fact_ids": ["fact:phase:0"]},
            }
        ],
        "phase_groups": [
            {
                "phase_group_id": "phase_group_0",
                "node_ids": [node_ids[0]],
                "source_fact_ids": ["fact:phase:0"],
            }
        ],
        "data_placement": {
            "policy_id": "dft_data_locality",
            "status": "candidate_only",
            "preferred_locations": {"density_grid": "hbm_or_host_visible"},
            "data_locality_intent": "keep streamed tensors close to legal accelerator memory",
        },
        "runtime_schedule": {
            "review_status": "review_required",
            "claim_boundary": "candidate_only",
        },
        "descriptor_protocol": {
            "magic": "0x00000000",
            "version": -1,
            "command_type": -1,
            "claim_boundary": "candidate_only",
        },
        "memory_policy": {
            "data_locality_intent": "hbm_streaming_candidate_only",
            "claim_boundary": "candidate_only",
        },
        "annotations": {
            "dft": {
                "phase_ids": ["phase_group_0"],
                "source_fact_ids": ["fact:phase:0"],
                "limitations": ["policy hints are candidate generation only"],
            }
        },
    }


def _roundtrip_backend_request(run_dir: Path):
    design_point = load_step2_design_point(run_dir)
    package = WorkloadPackage.from_dict(_load_json(run_dir / "workload_package.json"))
    executable_graph = ComputeGraph.from_dict(_load_json(run_dir / "executable_graph.json"))
    request = GenericSystemCBackend()._build_request(
        design_point,
        executable_graph,
        workload_package=package,
        output_dir=run_dir,
    )
    return design_point, package, executable_graph, request


def test_step2_runs_representative_non_qe_workloads_and_writes_required_artifacts(tmp_path):
    for family, build_graph in REPRESENTATIVE_BUILDERS.items():
        run_dir = tmp_path / family
        graph = build_graph(f"{family}_step2")
        package = package_from_graph(graph, workload_family=family, importer_id="generic_json")

        result = run_step2_architecture_mapping_workflow(package, output_dir=run_dir)

        assert result.status == "ready_for_step3_simulation", family
        assert result.design_point is not None, family
        assert result.executable_graph is not None, family
        for artifact_name in STEP2_REQUIRED_MAPPING_ARTIFACTS:
            assert (run_dir / artifact_name).exists(), f"{family}: missing {artifact_name}"
        for artifact_name in STEP2_LOW_FIDELITY_ARTIFACTS:
            assert (run_dir / artifact_name).exists(), f"{family}: missing {artifact_name}"
        for artifact_name in [
            "step2_status.json",
            "architecture_catalog.json",
            "architecture.json",
            "design_point.json",
            "workload_package.json",
            "workload_graph.json",
            "graph_lowering_report.json",
            "executable_graph.json",
            "mapping.json",
            "mapping_promotion_decision.json",
            "step2_artifact_validation.json",
        ]:
            assert (run_dir / artifact_name).exists(), f"{family}: missing {artifact_name}"

        status = _load_json(run_dir / "step2_status.json")
        architecture = _load_json(run_dir / "architecture.json")
        design_point = _load_json(run_dir / "design_point.json")
        selected = _load_json(run_dir / "mapping_selected_record.json")
        lowering = _load_json(run_dir / "graph_lowering_report.json")
        feedback = _load_json(run_dir / "mapping_feedback_state.json")
        convergence = _load_json(run_dir / "convergence_status.json")
        validation = _load_json(run_dir / "step2_artifact_validation.json")
        l1_result = _load_json(run_dir / "l1_evaluation_result.json")
        l1_decision = _load_json(run_dir / "l1_promotion_decision.json")
        l2_result = _load_json(run_dir / "l2_evaluation_result.json")
        l2_decision = _load_json(run_dir / "l2_promotion_decision.json")
        low_fidelity_summary = _load_json(run_dir / "low_fidelity_screening_summary.json")
        promotion = _load_json(run_dir / "mapping_promotion_decision.json")

        assert status["workload_family"] == family
        assert status["trusted_final_claim"] is False
        assert architecture["architecture_family"] == "balanced"
        assert architecture["components"]
        assert architecture["constraints"]["min_memory_bytes"] > 0
        assert architecture["simulation_bindings"]["systemc"]["trusted_eligible"] is True
        assert design_point["config"]["workload_id"] == package.workload_id
        assert design_point["config"]["architecture_id"] == "balanced-generic-systemc-v0"
        assert design_point["config"]["mapping_id"]
        assert design_point["config"]["scheduling_policy"] == "static_timing_level"
        assert design_point["config"]["precision_policy"]["default"] == "FP64"
        assert design_point["config"]["fallback_policy"]["unsupported_ops"] == "host_fallback_visible"
        assert design_point["config"]["simulation_config"]["backend"] == "systemc"
        assert design_point["config"]["output_config"]["required_mapping_artifacts"] == STEP2_REQUIRED_MAPPING_ARTIFACTS
        assert design_point["config"]["objective_directions"]["latency_ms"] == "minimize"
        assert design_point["config"]["graph_lowering"]["source_to_executable_nodes"]
        assert lowering["required_coverage"]
        assert QE_PHASE_NAMES.isdisjoint(set(lowering["required_coverage"]))
        assert selected["workload"]["workload_family"] == family
        assert selected["trusted_final_eligible"] is False
        assert feedback["ranking_update"]["low_fidelity_role"] == "candidate_generator_only"
        assert convergence["status"] == "awaiting_simulation"
        assert validation["valid"] is True
        assert l1_result["fidelity_level_achieved"] == "L1"
        assert l2_result["fidelity_level_achieved"] == "L2"
        assert l1_result["low_fidelity_role"] == "candidate_generator_only"
        assert l2_result["low_fidelity_role"] == "candidate_generator_only"
        assert l1_decision["low_fidelity_role"] == "candidate_generator_only"
        assert l2_decision["low_fidelity_role"] == "candidate_generator_only"
        assert l1_result["trusted_final_claim"] is False
        assert l2_result["trusted_final_claim"] is False
        assert low_fidelity_summary["required_for_step3"] is True
        assert low_fidelity_summary["passed"] is True
        assert low_fidelity_summary["low_fidelity_role"] == "candidate_generator_only"
        assert low_fidelity_summary["trusted_final_claim"] is False
        assert promotion["low_fidelity_screening"]["passed"] is True
        assert set(promotion["low_fidelity_screening"]["required_artifacts"]) == set(STEP2_LOW_FIDELITY_ARTIFACTS)
        assert promotion["low_fidelity_screening"]["trusted_final_claim"] is False
        assert promotion["promoted_for_simulation"] is True

        _, loaded_package, _, request = _roundtrip_backend_request(run_dir)
        workload = request["workload"]
        assert request["step2_handoff"]["present"] is True
        assert request["design_point"]["mapping_id"] == design_point["config"]["mapping_id"]
        assert request["mapping"] == design_point["task_mapping"]
        assert loaded_package.workload_family == family
        assert workload["workflow"]["workload_family"] == family
        assert workload["workload_package"]["importer"]["importer_id"] == "generic_json"
        assert QE_PHASE_NAMES.isdisjoint(set(workload["required_coverage"]))
        assert "npw" not in json.dumps(request)


def test_step2_qe_reference_regression_keeps_qe_seed_profile_scoped(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024, "graph_id": "qe_step2"})

    result = run_step2_architecture_mapping_workflow(package, output_dir=tmp_path)

    assert result.status == "ready_for_step3_simulation"
    seed_set = _load_json(tmp_path / "mapping_seed_set.json")
    seed_names = {seed["seed_name"] for seed in seed_set["seeds"]}
    request = GenericSystemCBackend()._build_request(
        load_step2_design_point(tmp_path),
        ComputeGraph.from_dict(_load_json(tmp_path / "executable_graph.json")),
        workload_package=WorkloadPackage.from_dict(_load_json(tmp_path / "workload_package.json")),
        output_dir=tmp_path,
    )

    assert seed_set["workload"]["workload_family"] == "dft_qe_reference"
    assert "dft_qe_reference_workflow_balanced" in seed_names
    assert "dft_qe_adapter_balanced" not in seed_names
    assert "qe_domain_balanced" not in seed_names
    assert request["workload"]["required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert request["workload"]["workload_package"]["profile"]["profile_id"] == "qe_scf_reference"
    assert request["workload"]["workload_package"]["importer"]["importer_id"] == "qe_reference_fixture"


def test_step2_writes_replayable_codesign_candidate_when_l4_proof_requested(tmp_path):
    graph = create_sparse_spmv_graph("sparse_codesign_step2")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")

    result = run_step2_architecture_mapping_workflow(
        package,
        output_dir=tmp_path,
        require_l4_proof=True,
        l4_reason="claim-critical L4 oracle sample",
    )

    candidate = _load_json(tmp_path / "codesign_candidate.json")
    protocol = _load_json(tmp_path / "descriptor_protocol.json")
    runtime = _load_json(tmp_path / "runtime_schedule.json")
    memory = _load_json(tmp_path / "memory_policy.json")
    promotion = _load_json(tmp_path / "mapping_promotion_decision.json")
    validation = _load_json(tmp_path / "codesign_artifact_validation.json")
    design_point = _load_json(tmp_path / "design_point.json")

    assert result.status == "ready_for_step3_simulation"
    assert candidate["design_point_id"] == design_point["design_point_id"]
    assert candidate["promotion_policy"]["l4_required"] is True
    assert candidate["promotion_policy"]["reason"] == "claim-critical L4 oracle sample"
    assert candidate["trusted_final_claim"] is False
    assert "software_visible_descriptor_ingestion" in candidate["expected_claims"]
    assert protocol["magic"] == "0x4753494d"
    assert protocol["completion"]["path"] == "guest_visible_memory_and_status_mmio"
    assert runtime["completion_policy"]["guest_visible_status_required"] is True
    assert memory["dma"]["enabled"] is True
    assert promotion["co_design"]["l4_required"] is True
    assert "codesign_verdict.json" in promotion["required_evidence"]
    assert validation["valid"] is True


def test_step2_policy_mapping_hints_dedupe_and_respect_legality(tmp_path):
    graph = create_sparse_spmv_graph("sparse_policy_mapping_step2")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    hints = _policy_candidate_hints(graph)

    result = run_step2_architecture_mapping_workflow(package, output_dir=tmp_path, candidate_hints=hints)

    seed_set = _load_json(tmp_path / "mapping_seed_set.json")
    candidate_records = _load_json(tmp_path / "mapping_candidate_records.json")
    selected = _load_json(tmp_path / "mapping_selected_record.json")
    legality = _load_json(tmp_path / "mapping_legality_matrix.json")
    domain_hints = _load_json(tmp_path / "domain_policy_hints.json")
    legal_by_node = {row["node_id"]: set(row["legal_targets"]) for row in legality["rows"]}
    seed_keys = [tuple(sorted(seed["mapping"].items())) for seed in seed_set["seeds"]]
    policy_seeds = [seed for seed in seed_set["seeds"] if seed["seed_name"].startswith("policy:dft_reference_step2:")]
    policy_candidates = [
        record
        for record in candidate_records["candidates"]
        if str(record.get("seed_name", "")).startswith("policy:dft_reference_step2:")
    ]

    assert result.status == "ready_for_step3_simulation"
    assert len(seed_keys) == len(set(seed_keys))
    assert policy_seeds
    assert policy_candidates
    assert domain_hints["policy_id"] == "dft_reference_step2"
    for seed in policy_seeds:
        assert seed["annotations"]["domain_policy"]["policy_id"] == "dft_reference_step2"
        assert seed["annotations"]["trusted_final_claim"] is False
        assert "phase_aware" in seed["description"] or "policy" in seed["description"] or "review-safe" in seed["description"]
        for node_id, target in seed["mapping"].items():
            assert target in legal_by_node[node_id]
    assert selected["domain_policy"]["policy_id"] == "dft_reference_step2"
    assert selected["review_required"] is True
    assert selected["review_flags"] == ["insufficient_evidence"]
    assert selected["trusted_final_claim"] is False
    assert all(not record.get("violations") for record in policy_candidates)
    assert all("h_psi" not in record["seed_name"] for record in policy_candidates)


def test_step2_codesign_policy_hints_preserve_descriptor_and_candidate_only_boundary(tmp_path):
    graph = create_sparse_spmv_graph("sparse_policy_codesign_step2")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    hints = _policy_candidate_hints(graph)

    run_step2_architecture_mapping_workflow(
        package,
        output_dir=tmp_path,
        require_l4_proof=True,
        l4_reason="claim-critical L4 oracle sample",
        candidate_hints=hints,
    )

    candidate = _load_json(tmp_path / "codesign_candidate.json")
    protocol = _load_json(tmp_path / "descriptor_protocol.json")
    runtime = _load_json(tmp_path / "runtime_schedule.json")
    memory = _load_json(tmp_path / "memory_policy.json")
    software = _load_json(tmp_path / "software_stack_config.json")
    lowering = _load_json(tmp_path / "compiler_lowering.json")
    validation = _load_json(tmp_path / "codesign_artifact_validation.json")
    promotion = _load_json(tmp_path / "mapping_promotion_decision.json")

    assert protocol["magic"] == "0x4753494d"
    assert protocol["version"] == 1
    assert protocol["command_type"] == 1
    assert candidate["descriptor_protocol"] == protocol
    assert candidate["runtime_schedule"] == runtime
    assert candidate["memory_policy"] == memory
    assert candidate["software_stack_config"] == software
    assert candidate["compiler_lowering"] == lowering
    assert candidate["trusted_final_claim"] is False
    assert candidate["review_required"] is True
    assert candidate["review_status"] == "review_required"
    assert candidate["domain_policy"]["policy_id"] == "dft_reference_step2"
    assert runtime["trusted_final_claim"] is False
    assert protocol["trusted_final_claim"] is False
    assert memory["trusted_final_claim"] is False
    assert memory["data_placement"]["trusted_final_claim"] is False
    assert memory["data_placement"]["data_locality_intent"] == "keep streamed tensors close to legal accelerator memory"
    assert promotion["review_required"] is True
    assert promotion["review_status"] == "review_required"
    assert promotion["promoted_for_simulation"] is True
    assert validation["valid"] is True


def test_step2_hard_policy_review_flags_block_promotion_without_losing_candidates(tmp_path):
    graph = create_sparse_spmv_graph("sparse_policy_hard_review_step2")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    hints = _policy_candidate_hints(graph, review_flags=["project_critical_conflict"])

    result = run_step2_architecture_mapping_workflow(package, output_dir=tmp_path, candidate_hints=hints)

    promotion = _load_json(tmp_path / "mapping_promotion_decision.json")
    candidate_records = _load_json(tmp_path / "mapping_candidate_records.json")
    status = _load_json(tmp_path / "step2_status.json")

    assert result.status == "candidate_only_or_blocked"
    assert promotion["promoted_for_simulation"] is False
    assert promotion["review_required"] is True
    assert promotion["review_status"] == "blocked_by_review_gate"
    assert any(reason["reason_id"] == "domain_review_gate_blocked" for reason in promotion["reasons"])
    assert status["review_flags"] == ["project_critical_conflict"]
    assert candidate_records["candidates"]
    assert all(record["trusted_final_eligible"] is False for record in candidate_records["candidates"] if record["state"] != "selected")


def test_step2_blocks_unsupported_lowering_before_mapping_promotion(tmp_path):
    graph = create_dynamic_custom_graph("unsupported_step2", supported=False)
    package = package_from_graph(graph, workload_family="dynamic_custom", importer_id="generic_json")

    result = run_step2_architecture_mapping_workflow(package, output_dir=tmp_path)

    status = _load_json(tmp_path / "step2_status.json")
    assert result.status == "blocked_unsupported_graph_lowering"
    assert result.design_point is None
    assert status["trusted_final_eligible"] is False
    assert status["reasons"][0]["reason_id"] == "unsupported_graph_lowering"
    assert not (tmp_path / "mapping_selected_record.json").exists()


def test_step2_downgrades_missing_binding_and_diagnostic_claim_boundary(tmp_path):
    graph = create_sparse_spmv_graph("sparse_candidate_only")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")

    unbound = run_step2_architecture_mapping_workflow(
        package,
        architecture_id="future-custom-candidate-v0",
        output_dir=tmp_path / "unbound",
    )
    unbound_status = _load_json(tmp_path / "unbound" / "step2_status.json")
    unbound_promotion = _load_json(tmp_path / "unbound" / "mapping_promotion_decision.json")
    assert unbound.status == "candidate_only_or_blocked"
    assert unbound.trusted_final_eligible is False
    assert unbound_promotion["promoted_for_simulation"] is False
    assert any(reason["reason_id"] in {"architecture_candidate_only", "missing_or_untrusted_binding"} for reason in unbound_status["reasons"])

    diagnostic_package = package_from_graph(
        graph,
        workload_id="sparse_smoke_boundary",
        workload_family="sparse_la",
        importer_id="generic_json",
        claim_boundary="smoke",
    )
    diagnostic = run_step2_architecture_mapping_workflow(diagnostic_package, output_dir=tmp_path / "diagnostic")
    diagnostic_status = _load_json(tmp_path / "diagnostic" / "step2_status.json")
    diagnostic_promotion = _load_json(tmp_path / "diagnostic" / "mapping_promotion_decision.json")
    assert diagnostic.status == "diagnostic_only_candidate"
    assert diagnostic.trusted_final_eligible is False
    assert diagnostic_promotion["promoted_for_simulation"] is False
    assert diagnostic_promotion["trusted_final_claim"] is False
    assert any(reason["reason_id"] == "diagnostic_claim_boundary" for reason in diagnostic_status["reasons"])


def test_step2_artifact_validation_rejects_illegal_mapping_and_predicted_final_claim(tmp_path):
    graph = create_vector_search_graph("vector_validation")
    package = package_from_graph(graph, workload_family="database_vector_search", importer_id="generic_json")
    result = run_step2_architecture_mapping_workflow(package, output_dir=tmp_path)

    artifacts = dict(result.artifacts)
    selected = dict(artifacts["selected_record"])
    mapping = dict(selected["mapping"])
    first_node = next(iter(mapping))
    mapping[first_node] = "missing-accelerator"
    selected["mapping"] = mapping
    selected["trusted_final_eligible"] = True
    artifacts["selected_record"] = selected
    artifacts["promotion_decision"] = {**artifacts["promotion_decision"], "trusted_final_claim": True}
    assert result.design_point is not None
    artifacts["system_architecture"] = result.design_point.system_architecture.to_dict()

    validation = validate_step2_artifacts(artifacts)
    candidate_records = _load_json(tmp_path / "mapping_candidate_records.json")
    predicted_records = [record for record in candidate_records["candidates"] if record["state"] == "predicted-only"]

    assert validation["valid"] is False
    assert any(error["field"] == "mapping" for error in validation["errors"])
    assert any(error["field"] == "promotion_decision.trusted_final_claim" for error in validation["errors"])
    assert all(record["trusted_final_eligible"] is False for record in predicted_records)


def test_step2_screens_multiple_architectures_without_breaking_step3_handoff(tmp_path):
    graph = create_sparse_spmv_graph("sparse_multi_arch_step2")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")

    result = run_step2_architecture_screening_workflow(
        package,
        architecture_ids=["balanced-generic-systemc-v0", "future-custom-candidate-v0"],
        output_dir=tmp_path,
    )

    records = result.artifacts["architecture_screening_records"]["records"]
    by_architecture = {record["architecture_id"]: record for record in records}
    balanced_dir = tmp_path / "architectures" / "balanced-generic-systemc-v0"
    future_dir = tmp_path / "architectures" / "future-custom-candidate-v0"

    assert result.status == "architecture_screening_completed"
    assert result.trusted_final_eligible is False
    assert (tmp_path / "architecture_screening_records.json").exists()
    assert set(by_architecture) == {"balanced-generic-systemc-v0", "future-custom-candidate-v0"}
    assert by_architecture["balanced-generic-systemc-v0"]["step2_status"] == "ready_for_step3_simulation"
    assert by_architecture["balanced-generic-systemc-v0"]["promoted_for_simulation"] is True
    assert by_architecture["future-custom-candidate-v0"]["promoted_for_simulation"] is False
    assert by_architecture["future-custom-candidate-v0"]["candidate_only_reasons"]
    assert (balanced_dir / "design_point.json").exists()
    assert (balanced_dir / "mapping_promotion_decision.json").exists()
    assert (future_dir / "mapping_promotion_decision.json").exists()

    _, _, _, request = _roundtrip_backend_request(balanced_dir)
    assert request["step2_handoff"]["present"] is True
    assert request["design_point"]["architecture_id"] == "balanced-generic-systemc-v0"
