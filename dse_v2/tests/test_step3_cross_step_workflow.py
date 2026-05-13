#!/usr/bin/env python3
"""Step1 -> Step2 -> Step3 cross-step workflow tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.core.workload import (
    create_dynamic_custom_graph,
    create_sparse_spmv_graph,
    create_vector_search_graph,
    package_from_graph,
)
from dse_v2.reference_workloads.dft_qe import QE_SCF_REQUIRED_COVERAGE, create_qe_reference_package
from dse_v2.evidence.step3_workflow import (
    STEP2_INPUT_ARTIFACTS,
    run_step3_simulation_evidence_workflow,
    validate_step2_handoff_for_step3,
)
from dse_v2.mapping.step2_workflow import run_step2_architecture_mapping_workflow


QE_ONLY_TOKENS = {"npw", "nkb", "h_psi", "s_psi", "diagonalize", "mix_rho", "veff"}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_sparse_step1_step2_step3_full_flow_evidence_without_qe_fields(tmp_path):
    graph = create_sparse_spmv_graph("sparse_cross_step")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2"
    step3_dir = tmp_path / "step3"

    step2 = run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)
    validation = validate_step2_handoff_for_step3(step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)

    request = _load(step3_dir / "simulation_request.json")
    result = _load(step3_dir / "simulation_result.json")
    verdict = _load(step3_dir / "verdict.json")
    report = _load(step3_dir / "final_report.json")
    claim_validation = _load(step3_dir / "claim_validation.json")
    status = _load(step3_dir / "step3_status.json")

    assert step2.status == "ready_for_step3_simulation"
    assert validation["valid"] is True
    assert step3.status == "trusted_full_flow_evidence_emitted"
    assert step3.trusted_for_final_ranking is True
    assert status["full_flow_simulation_attempted"] is True
    assert result["status"] == "passed"
    assert verdict["trusted_for_final_ranking"] is True
    assert "required_qe_scf_phases" not in verdict
    assert verdict["required_coverage"] == ["load_csr", "spmv", "norm"]
    assert verdict["profile_required_coverage"] == ["load_csr", "spmv", "norm"]
    assert report["workload"]["workload_family"] == "sparse_la"
    assert report["workload"]["required_coverage"] == ["load_csr", "spmv", "norm"]
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert claim_validation["passed"] is True
    assert request["step2_handoff"]["present"] is True
    assert request["design_point"]["mapping_id"]
    assert request["mapping"] == _load(step2_dir / "design_point.json")["task_mapping"]
    request_text = json.dumps(request)
    assert all(token not in request_text for token in QE_ONLY_TOKENS)
    for artifact in STEP2_INPUT_ARTIFACTS:
        if (step2_dir / artifact).exists():
            assert (step3_dir / "step2_input" / artifact).exists(), artifact
    assert report["evidence_index"]["step2_input/design_point.json"]["exists"] is True


def test_database_vector_search_cross_step_request_has_no_qe_required_phases(tmp_path):
    graph = create_vector_search_graph("vector_cross_step")
    package = package_from_graph(graph, workload_family="database_vector_search", importer_id="generic_json")
    step2_dir = tmp_path / "step2_vector"
    step3_dir = tmp_path / "step3_vector"

    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)

    request = _load(step3_dir / "simulation_request.json")
    verdict = _load(step3_dir / "verdict.json")
    report = _load(step3_dir / "final_report.json")

    assert step3.trusted_for_final_ranking is True
    assert request["workload"]["workflow"]["workload_family"] == "database_vector_search"
    assert QE_ONLY_TOKENS.isdisjoint(set(request["workload"]["required_coverage"]))
    assert "required_qe_scf_phases" not in verdict
    assert report["workload"]["importer_id"] == "generic_json"
    assert report["workload"]["profile_domain_validation"]["status"] == "unavailable_unclaimed"
    assert any("Query" in limitation or "recall" in limitation for limitation in report["limitations"])
    assert "npw" not in json.dumps(report)


def test_gem5_systemc_step3_blocks_when_real_l4_config_is_missing(tmp_path):
    graph = create_sparse_spmv_graph("sparse_l4_codesign")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2_l4"
    step3_dir = tmp_path / "step3_l4"

    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir, require_l4_proof=True)
    step3 = run_step3_simulation_evidence_workflow(
        step2_dir,
        output_dir=step3_dir,
        backend="gem5_systemc",
        simulator_path=tmp_path / "missing-generic-sim",
        gem5_binary=tmp_path / "missing-gem5.opt",
        gem5_config=tmp_path / "missing-config.py",
        driver_binary=tmp_path / "missing-driver",
        timeout=1,
    )

    codesign_verdict = _load(step3_dir / "codesign_verdict.json")
    l4_trace = _load(step3_dir / "l4_execution_trace.json")
    completion = _load(step3_dir / "completion_proof.json")
    proof = _load(step3_dir / "gem5_l4_proof.json")
    report = _load(step3_dir / "final_report.json")
    verdict = _load(step3_dir / "verdict.json")

    assert step3.status == "simulation_completed_untrusted"
    assert step3.trusted_for_final_ranking is False
    assert codesign_verdict["status"] == "blocked"
    assert codesign_verdict["trusted_for_codesign_ranking"] is False
    assert codesign_verdict["blocked_claims"]
    assert l4_trace["trace_status"] == "blocked"
    assert any(event["event"] == "gem5_microarchitecture_model_executed_from_device_path" for event in l4_trace["events"])
    assert completion["passed"] is False
    assert verdict["codesign_verdict"]["status"] == "blocked"
    assert report["codesign"]["status"] == "blocked"
    assert report["codesign"]["trusted_for_codesign_ranking"] is False
    assert (step3_dir / "step2_input" / "codesign_candidate.json").exists()
    assert proof["passed"] is False
    assert "gem5.log must contain microarchitecture_execute verified=true" in proof["missing_evidence"]


def test_qe_reference_step1_step2_step3_regression_preserves_profile_importer_boundary(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024, "graph_id": "qe_cross_step"})
    step2_dir = tmp_path / "step2_qe"
    step3_dir = tmp_path / "step3_qe"

    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)

    request = _load(step3_dir / "simulation_request.json")
    verdict = _load(step3_dir / "verdict.json")
    report = _load(step3_dir / "final_report.json")
    seed_set = _load(step2_dir / "mapping_seed_set.json")
    seed_names = {seed["seed_name"] for seed in seed_set["seeds"]}

    assert step3.trusted_for_final_ranking is True
    assert request["workload"]["workload_package"]["profile"]["profile_id"] == "qe_scf_reference"
    assert request["workload"]["workload_package"]["importer"]["importer_id"] == "qe_reference_fixture"
    assert request["workload"]["required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert "required_qe_scf_phases" not in verdict
    assert verdict["required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert verdict["profile_required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert report["workload"]["workload_family"] == "dft_qe_reference"
    assert report["workload"]["profile_id"] == "qe_scf_reference"
    assert "dft_qe_reference_workflow_balanced" in seed_names
    assert "dft_qe_adapter_balanced" not in seed_names
    assert "qe_domain_balanced" not in seed_names
    assert report["selected_recommendation"]["trusted_winner"] is False


def test_step3_blocks_unsupported_lowering_before_simulation(tmp_path):
    graph = create_dynamic_custom_graph("unsupported_cross_step", supported=False)
    package = package_from_graph(graph, workload_family="dynamic_custom", importer_id="generic_json")
    step2_dir = tmp_path / "step2_unsupported"
    step3_dir = tmp_path / "step3_unsupported"

    step2 = run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)
    validation = validate_step2_handoff_for_step3(step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)

    status = _load(step3_dir / "step3_status.json")
    reason_ids = {reason["reason_id"] for reason in status["reasons"]}

    assert step2.status == "blocked_unsupported_graph_lowering"
    assert validation["valid"] is False
    assert step3.status == "blocked_before_simulation"
    assert step3.trusted_for_final_ranking is False
    assert status["full_flow_simulation_attempted"] is False
    assert "missing_executable_graph" in reason_ids
    assert "step2_not_promoted_for_simulation" in reason_ids
    assert not (step3_dir / "simulation_result.json").exists()


def test_step3_blocks_candidate_only_missing_binding_and_smoke_boundary(tmp_path):
    graph = create_sparse_spmv_graph("blocked_cross_step")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    unbound_step2 = tmp_path / "step2_unbound"
    unbound_step3 = tmp_path / "step3_unbound"

    run_step2_architecture_mapping_workflow(package, architecture_id="future-custom-candidate-v0", output_dir=unbound_step2)
    unbound = run_step3_simulation_evidence_workflow(unbound_step2, output_dir=unbound_step3, timeout=30)
    unbound_status = _load(unbound_step3 / "step3_status.json")
    unbound_reasons = {reason["reason_id"] for reason in unbound_status["reasons"]}

    assert unbound.status == "blocked_before_simulation"
    assert unbound.trusted_for_final_ranking is False
    assert unbound_status["full_flow_simulation_attempted"] is False
    assert "step2_not_promoted_for_simulation" in unbound_reasons

    smoke_package = package_from_graph(
        graph,
        workload_id="smoke_cross_step",
        workload_family="sparse_la",
        importer_id="generic_json",
        claim_boundary="smoke",
    )
    smoke_step2 = tmp_path / "step2_smoke"
    smoke_step3 = tmp_path / "step3_smoke"
    run_step2_architecture_mapping_workflow(smoke_package, output_dir=smoke_step2)
    smoke = run_step3_simulation_evidence_workflow(smoke_step2, output_dir=smoke_step3, timeout=30)
    smoke_status = _load(smoke_step3 / "step3_status.json")
    smoke_reasons = {reason["reason_id"] for reason in smoke_status["reasons"]}

    assert smoke.status == "blocked_before_simulation"
    assert smoke.trusted_for_final_ranking is False
    assert smoke_status["full_flow_simulation_attempted"] is False
    assert "diagnostic_claim_boundary" in smoke_reasons
    assert "step2_not_promoted_for_simulation" in smoke_reasons


def test_step3_blocks_illegal_step2_mapping_and_missing_required_artifact(tmp_path):
    graph = create_sparse_spmv_graph("illegal_cross_step")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2_illegal"
    step3_dir = tmp_path / "step3_illegal"
    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)

    selected = _load(step2_dir / "mapping_selected_record.json")
    first_node = next(iter(selected["mapping"]))
    selected["mapping"][first_node] = "missing-accelerator"
    selected["violations"] = [f"{first_node}:missing-accelerator:illegal_target"]
    (step2_dir / "mapping_selected_record.json").write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (step2_dir / "mapping_promotion_decision.json").unlink()

    validation = validate_step2_handoff_for_step3(step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)
    status = _load(step3_dir / "step3_status.json")
    reason_ids = {reason["reason_id"] for reason in status["reasons"]}

    assert validation["valid"] is False
    assert step3.status == "blocked_before_simulation"
    assert status["full_flow_simulation_attempted"] is False
    assert "missing_step2_artifacts" in reason_ids
    assert "step2_not_promoted_for_simulation" in reason_ids
    assert "illegal_selected_mapping" in reason_ids
    assert "step2_artifact_validation_failed" in reason_ids


def test_step3_blocks_promoted_handoff_missing_low_fidelity_artifact(tmp_path):
    graph = create_sparse_spmv_graph("missing_low_fidelity_cross_step")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2_missing_low_fidelity"
    step3_dir = tmp_path / "step3_missing_low_fidelity"
    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)

    (step2_dir / "l2_evaluation_result.json").unlink()

    validation = validate_step2_handoff_for_step3(step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)
    status = _load(step3_dir / "step3_status.json")
    reason_ids = {reason["reason_id"] for reason in status["reasons"]}

    assert validation["valid"] is False
    assert step3.status == "blocked_before_simulation"
    assert status["full_flow_simulation_attempted"] is False
    assert "missing_step2_artifacts" in reason_ids
    assert "missing_low_fidelity_artifacts" in reason_ids
    assert "step2_artifact_validation_failed" in reason_ids
    assert not (step3_dir / "simulation_result.json").exists()


def test_step3_blocks_promoted_handoff_failed_low_fidelity_summary(tmp_path):
    graph = create_sparse_spmv_graph("failed_low_fidelity_cross_step")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2_failed_low_fidelity"
    step3_dir = tmp_path / "step3_failed_low_fidelity"
    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)

    summary = _load(step2_dir / "low_fidelity_screening_summary.json")
    summary["passed"] = False
    summary["status"] = "failed"
    summary["blockers"] = [{"reason_id": "forced_l2_gate_failure", "detail": "test failure injection"}]
    (step2_dir / "low_fidelity_screening_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_step2_handoff_for_step3(step2_dir)
    step3 = run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)
    status = _load(step3_dir / "step3_status.json")
    reason_ids = {reason["reason_id"] for reason in status["reasons"]}

    assert validation["valid"] is False
    assert step3.status == "blocked_before_simulation"
    assert status["full_flow_simulation_attempted"] is False
    assert "low_fidelity_screening_failed" in reason_ids
    assert "step2_artifact_validation_failed" in reason_ids
    assert not (step3_dir / "simulation_result.json").exists()
