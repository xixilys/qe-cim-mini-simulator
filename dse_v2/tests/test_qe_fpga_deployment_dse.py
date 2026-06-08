#!/usr/bin/env python3
"""QE FPGA deployment DSE L1 screening regressions."""

from __future__ import annotations

import json
import os
import copy
import math
from pathlib import Path

import pytest
import dse_v2.reference_workloads.qe_fpga_deployment_dse as qe_fpga_dse
from dse_v2.mapping.search_policy import HierarchicalFunnelSearchPolicy
from dse_v2.reference_workloads.qe_fpga_deployment_dse import (
    build_qe_fpga_l2_calibration_report,
    build_qe_fpga_l2_request_bundle,
    build_qe_fpga_multi_workload_experiment_report,
    build_qe_fpga_search_baseline_report,
    build_qe_fpga_implementation_package_plan,
    build_qe_fpga_adaptive_multifidelity_search_report,
    build_qe_fpga_neural_multifidelity_search_report,
    build_qe_fpga_neuromf_policy_evaluation_report,
    build_qe_fpga_neural_surrogate_training_report,
    run_qe_fpga_l2_tlm_requests,
    build_qe_fpga_l1_screening_report,
    materialize_qe_fpga_implementation_packages,
    run_qe_fpga_hls_attempts_for_materialized_packages,
    run_qe_fpga_hls_attempt,
    run_qe_fpga_vivado_attempts_for_materialized_packages,
    run_qe_fpga_vivado_attempt,
)
from dse_v2.reference_workloads.qe_mainflow import (
    build_qe_fpga_deployment_search_problem,
    default_qe_mainflow_workload_suite,
)


def _candidate_payloads(limit: int = 48):
    manifest = default_qe_mainflow_workload_suite()
    problem = build_qe_fpga_deployment_search_problem(
        manifest,
        workload_run_id="qe_suite_run_001",
    )
    records = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
    ).propose(problem, budget=limit)
    return manifest, problem, [record.to_dict() for record in records]


def test_qe_fpga_workflow_abstraction_summary_does_not_treat_unknown_classes_as_not_scf_only():
    summary = qe_fpga_dse._wamf_workflow_abstraction_summary(
        {
            "workflow_scope": "external_qe_workflow_corpus",
            "workload_features": {
                "feature_source": "unit_missing_classes",
                "stage_count": 0,
                "workflow_classes": [],
            },
        }
    )

    assert summary["not_scf_only"] is False
    assert summary["workflow_classes"] == []


def _contract_first_workflow_abstraction(workload_id: str = "contract_first_neuromf_workflow"):
    return {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "workload_id": workload_id,
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            "stage_count": 4,
            "observed_runtime": True,
            "artifact_dependency_count": 2,
        },
        "graph": {
            "node_count": 4,
            "edge_count": 3,
            "nodes": [],
            "edges": [
                {"source_stage": "scf", "target_stage": "nscf", "edge_kind": "stage_order"},
                {"source_stage": "nscf", "target_stage": "bands", "edge_kind": "stage_order"},
                {"source_stage": "scf", "target_stage": "relax", "edge_kind": "stage_order"},
            ],
        },
        "features": {
            "workflow_classes": ["nscf", "post_processing", "relax", "scf"],
            "stage_count": 4,
            "kernel_weights": {"h_psi": 2.0, "fft": 0.8, "diagonalization": 0.4},
            "observed_total_phase_wall_seconds": 3.2,
            "estimated_total_data_movement_bytes": 128 * 1024 * 1024,
            "host_control_intensity": 0.22,
            "data_movement_intensity": 0.03,
            "scf_iteration_count_observed": 2,
            "stage_repetition": {"scf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 2}},
            "host_control_events": {
                "scf_convergence_check_count": 2,
                "post_processing_stage_count": 1,
                "io_checkpoint_event_count": 2,
                "retained_kernel_counts": {"diagonalization": 1},
            },
            "correctness_observables": {"workflow": ["total_energy", "eigenvalue_spectrum"], "per_stage": {}},
        },
        "data_objects": {
            "psi": {"object_kind": "wavefunction_coefficients", "bytes": 64 * 1024 * 1024},
            "rho": {"object_kind": "charge_density", "bytes": 8 * 1024 * 1024},
        },
        "source_facts": [{"field": "phase_timing.h_psi.wall_seconds", "evidence_level": "observed_profile"}],
        "workflow_feature_contract": {
            "schema_version": "dse.workflow_feature_contract.v1",
            "domain_neutral": True,
            "source_adapter": "qe_workflow_fpga_abstraction",
            "workload_family": "qe",
            "workflow_id": workload_id,
            "workflow_dag": {
                "stage_count": 4,
                "stages": [
                    {"stage_id": "scf", "stage_type": "scf", "stage_class": "scf"},
                    {"stage_id": "nscf", "stage_type": "nscf", "stage_class": "nscf"},
                    {"stage_id": "bands", "stage_type": "bands", "stage_class": "post_processing"},
                    {"stage_id": "relax", "stage_type": "relax", "stage_class": "relax"},
                ],
                "edges": [{"source_stage": "scf", "target_stage": "nscf", "edge_kind": "stage_order"}],
            },
            "stage_feature_table": [
                {"stage_id": "scf", "stage_type": "scf", "stage_class": "scf", "expected_repetition": 2},
                {"stage_id": "bands", "stage_type": "bands", "stage_class": "post_processing", "expected_repetition": 1},
            ],
            "data_object_table": [
                {
                    "object_id": "psi",
                    "bytes": 64 * 1024 * 1024,
                    "producer_stages": ["scf"],
                    "consumer_stages": ["nscf", "bands"],
                    "residency_constraint": "fpga_hbm_or_host_pinned_reuse",
                },
                {
                    "object_id": "rho",
                    "bytes": 8 * 1024 * 1024,
                    "producer_stages": ["scf"],
                    "consumer_stages": ["scf"],
                    "residency_constraint": "host_visible_checkpoint_with_optional_fpga_cache",
                },
            ],
            "compute_feature_table": [
                {"compute_id": "h_psi", "weight_seconds": 2.0},
                {"compute_id": "fft", "weight_seconds": 0.8},
            ],
            "correctness_observable_table": {"workflow": ["total_energy", "eigenvalue_spectrum"], "per_stage": {}},
            "search_objectives": ["latency", "energy", "edp", "resource_pressure", "data_movement", "feasibility_risk"],
            "claim_boundary": "workflow_features_only_not_evidence_not_candidate_identity",
        },
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }


def _contract_first_workflow_manifest(workload_id: str) -> dict:
    return {
        "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
        "suite_id": workload_id,
        "source_kind": "workflow_corpus_single_external_qe_workflow_bundle",
        "workflow_scope": "external_qe_workflow_corpus",
        "cases": [],
        "workflow_classes": ["nscf", "post_processing", "scf"],
        "claim_boundary": "workflow_corpus_manifest_only_not_representative_qe_runtime_or_fpga_evidence",
    }


def test_qe_fpga_l1_screening_scores_candidates_with_workflow_metrics():
    manifest, problem, candidates = _candidate_payloads()

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=4,
    )

    assert report["schema_version"] == "dse.qe_fpga_deployment_l1_screening.v1"
    assert report["method_name"] == "WAMF-DSE"
    assert report["prior_name"] == "WorkflowAwareParetoFunnel"
    assert report["component_role"] == "cheap_full_space_prior"
    assert report["workload_features"]["workflow_classes"] == ["nscf", "post_processing", "relax", "scf"]
    assert report["workload_features"]["stage_count"] >= 4
    assert report["workload_features"]["kernel_weights"]["h_psi"] > 0.0
    assert report["candidate_count"] == len(candidates)
    assert report["candidate_evaluations"]

    first = report["candidate_evaluations"][0]
    assert first["fidelity"] == "L1_analytical_workflow_model"
    assert first["metrics"]["estimated_workflow_wall_time_ms"] > 0.0
    assert first["metrics"]["estimated_energy_mj"] > 0.0
    assert first["metrics"]["estimated_edp"] > 0.0
    assert first["metrics"]["estimated_data_movement_mb"] > 0.0
    assert 0.0 <= first["metrics"]["implementation_feasibility"] <= 1.0
    assert first["explanation"]["offload_boundary"]
    assert first["claim_boundary"] == "l1_screening_only_not_fpga_implementation_evidence"


def test_qe_fpga_l1_screening_uses_workflow_abstraction_as_primary_feature_source():
    manifest, problem, candidates = _candidate_payloads(512)
    base_abstraction = {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "workload_id": "si_workflow_abstraction_unit",
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            "stage_count": 4,
            "observed_runtime": True,
            "artifact_dependency_count": 3,
        },
        "graph": {
            "node_count": 14,
            "edge_count": 18,
            "nodes": [],
            "edges": [
                {"edge_kind": "data_object_lifetime", "tensor_name": "psi"},
                {"edge_kind": "stage_artifact_dependency", "tensor_name": "qe_save_dir"},
            ],
        },
        "features": {
            "workflow_classes": ["nscf", "post_processing", "relax", "scf"],
            "stage_count": 4,
            "kernel_weights": {
                "h_psi": 2.0,
                "fft": 0.8,
                "diagonalization": 0.3,
                "mix_rho": 0.2,
                "band_path_projection": 0.4,
            },
            "observed_total_phase_wall_seconds": 3.7,
            "estimated_total_data_movement_bytes": 96 * 1024 * 1024,
            "host_control_intensity": 0.10,
            "data_movement_intensity": 0.020,
            "scf_iteration_count_observed": 2,
            "stage_repetition": {
                "scf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 2},
                "nscf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 1},
                "bands": {"repetition_kind": "single_post_processing_pass", "observed_iterations": 1},
            },
            "host_control_events": {
                "scf_convergence_check_count": 2,
                "post_processing_stage_count": 1,
                "io_checkpoint_event_count": 3,
                "retained_kernel_counts": {"mix_rho": 1, "diagonalization": 1},
            },
            "correctness_observables": {
                "workflow": ["total_energy", "charge_density_residual", "eigenvalue_spectrum", "band_structure"],
                "per_stage": {},
                "observed_values": {"final_total_energy_ry": -15.8, "scf_accuracy_ry": 1.0e-8},
            },
        },
        "data_objects": {
            "psi": {
                "object_kind": "wavefunction_coefficients",
                "bytes": 64 * 1024 * 1024,
                "lifetime": "scf_to_nscf_or_post_processing_reuse",
                "preferred_residency_hint": "fpga_hbm_or_host_pinned_reuse",
            },
            "rho": {
                "object_kind": "charge_density",
                "bytes": 8 * 1024 * 1024,
                "lifetime": "scf_iteration_feedback_and_checkpoint",
                "preferred_residency_hint": "host_visible_checkpoint_with_optional_fpga_cache",
            },
            "qe_save_dir": {
                "object_kind": "qe_prefix_save_directory",
                "bytes": 24 * 1024 * 1024,
                "lifetime": "disk_checkpoint_between_qe_programs",
                "preferred_residency_hint": "host_filesystem_checkpoint_not_accelerator_resident",
            },
        },
        "source_facts": [{"field": "phase_timing.h_psi.wall_seconds", "evidence_level": "observed_profile"}],
        "workflow_feature_contract": {
            "schema_version": "dse.workflow_feature_contract.v1",
            "domain_neutral": True,
            "source_adapter": "qe_workflow_fpga_abstraction",
            "workload_family": "qe",
            "workflow_id": "si_workflow_abstraction_unit",
            "workflow_dag": {
                "stage_count": 4,
                "stages": [
                    {"stage_id": "scf", "stage_type": "scf", "stage_class": "scf", "repetition": {"kind": "scf_iteration_loop", "observed_iterations": 2}},
                    {"stage_id": "nscf", "stage_type": "nscf", "stage_class": "nscf", "repetition": {"kind": "scf_iteration_loop", "observed_iterations": 1}},
                    {"stage_id": "bands", "stage_type": "bands", "stage_class": "post_processing", "repetition": {"kind": "single_post_processing_pass", "observed_iterations": 1}},
                ],
                "edges": [{"source_stage": "scf", "target_stage": "nscf", "edge_kind": "stage_order"}],
            },
            "stage_feature_table": [
                {"stage_id": "scf", "stage_type": "scf", "stage_class": "scf", "expected_repetition": 2, "host_control_barrier": True, "include_in_performance_model": True},
                {"stage_id": "bands", "stage_type": "bands", "stage_class": "post_processing", "expected_repetition": 1, "host_control_barrier": False, "include_in_performance_model": True},
            ],
            "data_object_table": [
                {"object_id": "psi", "bytes": 64 * 1024 * 1024, "producer_stages": ["scf"], "consumer_stages": ["nscf", "bands"], "residency_constraint": "fpga_hbm_or_host_pinned_reuse"},
                {"object_id": "rho", "bytes": 8 * 1024 * 1024, "producer_stages": ["scf"], "consumer_stages": ["scf"], "residency_constraint": "host_visible_checkpoint_with_optional_fpga_cache"},
            ],
            "compute_feature_table": [
                {"compute_id": "h_psi", "weight_seconds": 2.0, "source_confidence": "observed", "uncertainty": {"kind": "relative_weight_interval"}},
                {"compute_id": "fft", "weight_seconds": 0.8, "source_confidence": "observed", "uncertainty": {"kind": "relative_weight_interval"}},
            ],
            "correctness_observable_table": {
                "workflow": ["total_energy", "charge_density_residual", "eigenvalue_spectrum", "band_structure"],
                "per_stage": {},
            },
            "search_objectives": ["latency", "energy", "edp", "resource_pressure", "data_movement", "feasibility_risk"],
            "claim_boundary": "workflow_features_only_not_evidence_not_candidate_identity",
        },
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }
    heavy_abstraction = copy.deepcopy(base_abstraction)
    heavy_abstraction["features"]["estimated_total_data_movement_bytes"] = 2 * 1024 * 1024 * 1024
    heavy_abstraction["features"]["host_control_intensity"] = 0.65
    heavy_abstraction["features"]["host_control_events"] = {
        "scf_convergence_check_count": 14,
        "post_processing_stage_count": 3,
        "io_checkpoint_event_count": 9,
        "retained_kernel_counts": {"mix_rho": 4, "diagonalization": 4, "io": 3},
    }
    heavy_abstraction["data_objects"]["psi"]["bytes"] = 768 * 1024 * 1024
    heavy_abstraction["data_objects"]["rho"]["bytes"] = 192 * 1024 * 1024
    heavy_abstraction["data_objects"]["qe_save_dir"]["bytes"] = 512 * 1024 * 1024

    light_report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
        workflow_abstraction=base_abstraction,
    )
    heavy_report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
        workflow_abstraction=heavy_abstraction,
    )

    assert light_report["workload_features"]["feature_source"] == "qe_workflow_fpga_abstraction"
    assert light_report["workload_features"]["workflow_feature_contract"]["schema_version"] == "dse.workflow_feature_contract.v1"
    assert light_report["workload_features"]["workflow_feature_contract"]["domain_neutral"] is True
    assert light_report["workload_features"]["workflow_feature_contract"]["stage_count"] == 4
    assert light_report["workload_features"]["workflow_feature_contract"]["compute_feature_count"] == 2
    assert light_report["workload_features"]["workflow_feature_contract"]["claim_boundary"] == "workflow_features_only_not_evidence_not_candidate_identity"
    assert heavy_report["workload_features"]["feature_source"] == "qe_workflow_fpga_abstraction"
    assert light_report["workload_features"]["estimated_workflow_data_volume_mb"] < heavy_report["workload_features"]["estimated_workflow_data_volume_mb"]
    assert light_report["workload_features"]["host_control_event_counts"]["scf_convergence_check_count"] == 2
    assert heavy_report["workload_features"]["host_control_event_counts"]["scf_convergence_check_count"] == 14
    light_by_id = {row["candidate_id"]: row for row in light_report["candidate_evaluations"]}
    heavy_by_id = {row["candidate_id"]: row for row in heavy_report["candidate_evaluations"]}
    shared_candidate_id = next(iter(light_by_id))
    assert (
        heavy_by_id[shared_candidate_id]["metrics"]["estimated_data_movement_mb"]
        > light_by_id[shared_candidate_id]["metrics"]["estimated_data_movement_mb"]
    )
    assert (
        heavy_by_id[shared_candidate_id]["metrics"]["host_control_event_penalty_ms"]
        > light_by_id[shared_candidate_id]["metrics"]["host_control_event_penalty_ms"]
    )
    assert [row["candidate_id"] for row in light_report["promotion_queue"]] != [
        row["candidate_id"] for row in heavy_report["promotion_queue"]
    ]


def test_qe_fpga_l1_screening_rejects_contractless_workflow_abstraction_when_strict():
    manifest, problem, candidates = _candidate_payloads(128)
    contractless_abstraction = {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "workload_id": "strict_contractless",
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            "stage_count": 1,
            "observed_runtime": False,
            "artifact_dependency_count": 0,
        },
        "graph": {"node_count": 1, "edge_count": 0, "nodes": [], "edges": []},
        "features": {
            "workflow_classes": ["scf"],
            "stage_count": 1,
            "kernel_weights": {"h_psi": 1.0},
            "observed_total_phase_wall_seconds": 1.0,
            "estimated_total_data_movement_bytes": 8 * 1024 * 1024,
            "host_control_intensity": 0.1,
            "data_movement_intensity": 0.01,
            "scf_iteration_count_observed": 1,
            "stage_repetition": {"scf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 1}},
            "host_control_events": {"scf_convergence_check_count": 1, "post_processing_stage_count": 0, "io_checkpoint_event_count": 1, "retained_kernel_counts": {}},
            "correctness_observables": {"workflow": ["total_energy"], "per_stage": {}, "observed_values": {}},
        },
        "data_objects": {},
        "source_facts": [],
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }

    permissive_report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=4,
        workflow_abstraction=contractless_abstraction,
    )
    assert permissive_report["workload_features"]["feature_source"] == "qe_mainflow_manifest"

    with pytest.raises(ValueError, match="workflow_feature_contract"):
        build_qe_fpga_l1_screening_report(
            manifest,
            problem,
            candidates,
            promotion_budget=4,
            workflow_abstraction=contractless_abstraction,
            require_workflow_feature_contract=True,
        )


def test_qe_fpga_l1_screening_accepts_contract_first_workflow_manifest_when_strict():
    _, problem, candidates = _candidate_payloads(128)
    abstraction = _contract_first_workflow_abstraction("corpus_contract_first_workload")
    manifest = {
        "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
        "suite_id": "corpus_contract_first_workload",
        "source_kind": "workflow_corpus_single_external_qe_workflow_bundle",
        "workflow_scope": "external_qe_workflow_corpus",
        "cases": [],
        "workflow_classes": ["nscf", "post_processing", "scf"],
        "claim_boundary": "workflow_corpus_manifest_only_not_representative_qe_runtime_or_fpga_evidence",
    }

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=4,
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )

    assert report["schema_version"] == "dse.qe_fpga_deployment_l1_screening.v1"
    assert report["validation"]["valid"] is True
    assert report["validation"]["validation_source"] == "workflow_feature_contract"
    assert report["workload_features"]["feature_source"] == "qe_workflow_fpga_abstraction"
    assert report["workload_features"]["workflow_feature_contract"]["workflow_id"] == "corpus_contract_first_workload"
    assert report["candidate_count"] == len(candidates)
    assert report["promotion_queue"]


def test_qe_fpga_search_baseline_accepts_contract_first_workflow_manifest_when_strict():
    _, problem, candidates = _candidate_payloads(128)
    abstraction = _contract_first_workflow_abstraction("corpus_contract_first_baseline_workload")
    manifest = _contract_first_workflow_manifest("corpus_contract_first_baseline_workload")
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=4,
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )

    report = build_qe_fpga_search_baseline_report(
        manifest,
        problem,
        screening,
        evaluation_budget=4,
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )

    assert report["schema_version"] == "dse.qe_fpga_search_baseline_report.v1"
    assert report["validation"]["valid"] is True
    assert report["validation"]["validation_source"] == "workflow_feature_contract"
    assert report["workflow_abstraction"]["workflow_scope"] == "external_qe_workflow_corpus"
    assert report["policies"]
    assert report["budget_sweep"]["baseline_policy_results"]


def test_qe_fpga_multi_workload_experiment_accepts_contract_first_model_search_workload():
    _, _, _ = _candidate_payloads(4)
    workload_id = "contract_first_multi_workload_neuromf"
    abstraction = _contract_first_workflow_abstraction(workload_id)
    workload = {
        "workload_id": workload_id,
        "description": "contract-first workflow corpus fixture",
        "variant_knobs": {"workflow_source": "contract_first"},
        "manifest": _contract_first_workflow_manifest(workload_id),
        "workflow_abstraction": abstraction,
        "workflow_bundle": {
            "schema_version": "dse.qe_workflow_bundle.v1",
            "workflow_id": workload_id,
            "stages": [],
            "claim_boundary": "workflow_bundle_fixture_only",
        },
    }

    report = build_qe_fpga_multi_workload_experiment_report(
        workload_run_id_prefix="contract_first_multi",
        candidate_budget=96,
        promotion_budget=3,
        workloads=[workload],
        input_source={"source_kind": "unit_contract_first_workload", "workload_count": 1},
    )

    assert report["schema_version"] == "dse.qe_fpga_multi_workload_experiment_report.v1"
    assert report["workload_count"] == 1
    row = report["workloads"][0]
    assert row["workflow_abstraction"]["workflow_scope"] == "external_qe_workflow_corpus"
    assert row["neuromf_policy_evaluation_summary"]["policy_count"] >= 8
    assert row["neuromf_feedback_sample_count"] > 0
    assert report["oracle_fidelity"] == "L2_python_tlm"
    assert report["claim_boundary"] == "multi_workload_l2_tlm_experiment_only_not_final_hardware_evidence"


def test_qe_fpga_search_space_includes_explicit_fpga_microarchitecture_knobs():
    manifest, problem, candidates = _candidate_payloads(2500)
    problem_payload = problem.to_dict()

    assert problem_payload["parameters"]["vector_lanes"] == [2, 4, 8]
    assert problem_payload["parameters"]["hbm_channel_count"] == [0, 4, 8]
    assert problem_payload["parameters"]["tile_doubles"] == [1024, 2048, 4096]
    assert {
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
    }.issubset(set(problem_payload["constraints"]["required_parameters"]))

    parameter_rows = [row["parameters"] for row in candidates]
    assert {row["vector_lanes"] for row in parameter_rows} >= {2, 4, 8}
    assert {row["hbm_channel_count"] for row in parameter_rows} >= {0, 4, 8}
    assert {row["tile_doubles"] for row in parameter_rows} >= {1024, 2048, 4096}

    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    assert {
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
    }.issubset(set(screening["promotion_policy"]["design_key_fields"]))
    assert {
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
    }.issubset(set(screening["promotion_policy"]["hardware_microarchitecture_knobs"]))
    assert any("vector_lanes=8" in row["design_key"] for row in screening["candidate_evaluations"])
    assert all("vector_lanes" in row["parameters"] for row in screening["candidate_evaluations"])


def test_qe_fpga_step2_candidate_generation_filters_cross_axis_illegal_designs_before_budget():
    manifest = default_qe_mainflow_workload_suite()
    problem = build_qe_fpga_deployment_search_problem(
        manifest,
        workload_run_id="qe_suite_run_legality",
    )

    records = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
    ).propose(problem, budget=512)
    candidates = [record.to_dict() for record in records]

    assert candidates
    assert len(candidates) == 512
    assert all(not row["blocker_reasons"] for row in candidates)
    assert all(row["parameters"]["release_lane"] == "release" for row in candidates)
    assert all(row["parameters"]["precision_policy"] == "fp64_strict" for row in candidates)
    assert all(
        row["parameters"]["hbm_channel_count"] > 0
        for row in candidates
        if row["parameters"]["memory_topology"] == "hbm_multi_channel"
    )
    assert all(
        row["parameters"]["hbm_channel_count"] == 0
        for row in candidates
        if row["parameters"]["memory_topology"] != "hbm_multi_channel"
    )


def test_qe_fpga_l1_model_rewards_hbm_residency_and_overlap_for_workflow_data_movement():
    manifest, problem, candidates = _candidate_payloads(2500)

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=6,
    )

    release_rows = [
        row for row in report["candidate_evaluations"]
        if row["parameters"]["release_lane"] == "release"
        and row["parameters"]["precision_policy"] == "fp64_strict"
    ]
    hbm_rows = [
        row for row in release_rows
        if row["parameters"]["memory_topology"] == "hbm_multi_channel"
        and row["parameters"]["data_residency"] == "fpga_hbm_resident_hot_arrays"
        and row["parameters"]["runtime_schedule"] == "overlap_dma_compute"
    ]
    host_rows = [
        row for row in release_rows
        if row["parameters"]["memory_topology"] == "ddr_streaming"
        and row["parameters"]["data_residency"] == "host_resident_with_streaming_windows"
        and row["parameters"]["runtime_schedule"] == "cpu_orchestrated_sequential"
    ]

    assert hbm_rows
    assert host_rows
    assert min(row["metrics"]["estimated_data_movement_mb"] for row in hbm_rows) < min(
        row["metrics"]["estimated_data_movement_mb"] for row in host_rows
    )
    assert min(row["metrics"]["estimated_edp"] for row in hbm_rows) < min(
        row["metrics"]["estimated_edp"] for row in host_rows
    )


def test_qe_fpga_l1_scoring_uses_workflow_lifetime_and_host_control_features():
    manifest, problem, candidates = _candidate_payloads(2500)

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=6,
    )

    features = report["workload_features"]
    assert features["data_object_lifetime"]["hot_reuse_object_count"] >= 1
    assert features["data_object_lifetime"]["checkpoint_object_count"] >= 1
    assert features["host_control_event_counts"]["scf_convergence_check_count"] >= 1
    assert features["correctness_observables"]["workflow"]

    release_rows = [
        row for row in report["candidate_evaluations"]
        if row["parameters"]["release_lane"] == "release"
        and row["parameters"]["precision_policy"] == "fp64_strict"
    ]
    hbm_reuse_rows = [
        row for row in release_rows
        if row["parameters"]["memory_topology"] == "hbm_multi_channel"
        and row["parameters"]["data_residency"] == "fpga_hbm_resident_hot_arrays"
    ]
    host_stream_rows = [
        row for row in release_rows
        if row["parameters"]["memory_topology"] == "ddr_streaming"
        and row["parameters"]["data_residency"] == "host_resident_with_streaming_windows"
    ]
    assert hbm_reuse_rows
    assert host_stream_rows
    assert min(row["metrics"]["estimated_data_object_movement_mb"] for row in hbm_reuse_rows) < min(
        row["metrics"]["estimated_data_object_movement_mb"] for row in host_stream_rows
    )

    workflow_bundle = next(
        row for row in release_rows
        if row["parameters"]["offload_boundary"] == "workflow_hotspot_bundle"
        and row["parameters"]["architecture_template"] == "fpga_hbm_streaming_dataflow"
    )
    kernel_bundle = next(
        row for row in release_rows
        if row["parameters"]["offload_boundary"] == "kernel_callsite_bundle"
        and row["parameters"]["architecture_template"] == "fpga_hybrid_cpu_control_accel_kernels"
    )
    assert workflow_bundle["metrics"]["host_control_event_penalty_ms"] > kernel_bundle["metrics"]["host_control_event_penalty_ms"]
    assert workflow_bundle["metrics"]["correctness_gate_count"] >= 3
    assert "data_object_lifetime" in workflow_bundle["explanation"]["workload_basis"]
    assert "host_control_events" in workflow_bundle["explanation"]["workload_basis"]


def test_qe_fpga_l1_pareto_promotes_release_nondominated_candidates_only():
    manifest, problem, candidates = _candidate_payloads(2500)

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )

    pareto_ids = {row["candidate_id"] for row in report["pareto_frontier"]}
    promoted_ids = {row["candidate_id"] for row in report["promotion_queue"]}

    assert len(pareto_ids) >= 2
    assert len(promoted_ids) == 5
    assert promoted_ids & pareto_ids
    assert all(row["promotion"]["release_pareto_eligible"] is True for row in report["promotion_queue"])
    assert all(row["metrics"]["fpga_resource_pressure"] < 0.98 for row in report["promotion_queue"])
    assert all(row["parameters"]["release_lane"] == "release" for row in report["promotion_queue"])
    assert all(row["parameters"]["precision_policy"] == "fp64_strict" for row in report["promotion_queue"])
    assert all(row["promotion"]["recommended_next_fidelity"] == "L2_systemc_or_tlm" for row in report["promotion_queue"])

    assert all(row["parameters"]["release_lane"] == "release" for row in report["candidate_evaluations"])
    assert all(row["parameters"]["precision_policy"] == "fp64_strict" for row in report["candidate_evaluations"])


def test_qe_fpga_l1_promotion_queue_preserves_structural_diversity():
    manifest, problem, candidates = _candidate_payloads(2500)

    report = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )

    promoted = report["promotion_queue"]
    assert len(promoted) == 5
    promoted_architectures = {row["parameters"]["architecture_template"] for row in promoted}
    promoted_design_keys = {row["design_key"] for row in promoted}

    assert len(promoted_architectures) >= 2
    assert len(promoted_design_keys) == len(promoted)
    assert all(
        "diversity_preserved_for_expensive_followup" in row["promotion"]["rationale"]
        for row in promoted
    )


def test_qe_fpga_l2_request_bundle_materializes_promoted_candidates_without_execution():
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )

    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )

    assert bundle["schema_version"] == "dse.qe_fpga_l2_request_bundle.v1"
    assert bundle["request_count"] == 5
    assert bundle["backend"] == "systemc_or_tlm"
    assert bundle["execution_allowed"] is False
    assert bundle["claim_boundary"] == "l2_request_bundle_only_not_executed_systemc_or_fpga_evidence"

    first = bundle["requests"][0]
    assert first["schema_version"] == "dse.qe_fpga_l2_evaluation_request.v1"
    assert first["candidate_id"]
    assert first["design_key"]
    assert first["candidate_parameters"]["deployment_target"] == "fpga"
    assert first["workload_features"]["workflow_classes"] == ["nscf", "post_processing", "relax", "scf"]
    assert first["candidate_l1_metrics"]["estimated_workflow_wall_time_ms"] > 0.0
    assert first["simulation_intent"]["backend_candidates"] == ["tlm", "systemc"]
    assert first["simulation_intent"]["evaluate_host_device_transfers"] is True
    assert first["simulation_intent"]["evaluate_cpu_retained_stages"] is True
    assert first["request_payload"]["graph"]["nodes"]
    assert first["request_payload"]["architecture"]["accelerators"]
    assert first["request_payload"]["deployment"]["offload_boundary"] in {
        "workflow_hotspot_bundle",
        "stage_cluster_bundle",
        "kernel_callsite_bundle",
    }


def test_qe_fpga_l2_request_bundle_binds_workflow_feature_contract_when_available():
    manifest, problem, candidates = _candidate_payloads(2500)
    abstraction = _contract_first_workflow_abstraction("contract_first_l2_workflow")
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=4,
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )

    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )

    assert bundle["workflow_feature_contract"]["schema_version"] == "dse.workflow_feature_contract.v1"
    assert bundle["workflow_feature_contract"]["workflow_id"] == "contract_first_l2_workflow"
    assert bundle["feature_source_priority"][0] == "qe_workflow_fpga_abstraction"
    first = bundle["requests"][0]
    assert first["workload_features"]["workflow_feature_contract"]["workflow_id"] == "contract_first_l2_workflow"
    assert first["workflow_feature_contract"]["workflow_id"] == "contract_first_l2_workflow"
    assert first["request_payload"]["workflow_feature_contract"]["workflow_id"] == "contract_first_l2_workflow"
    assert first["request_payload"]["graph"]["workflow_feature_contract"]["workflow_id"] == "contract_first_l2_workflow"
    assert first["request_payload"]["graph"]["source"] == "workflow_feature_contract"
    graph = first["request_payload"]["graph"]
    assert sorted(graph["nodes"]) == ["bands", "nscf", "relax", "scf"]
    assert graph["nodes"]["scf"]["stage_class"] == "scf"
    assert graph["nodes"]["bands"]["stage_class"] == "post_processing"
    assert graph["nodes"]["scf"]["expected_repetition"] == 2
    assert any(
        edge["source"] == "scf" and edge["target"] == "nscf" and edge["edge_kind"] == "stage_order"
        for edge in graph["edges"]
    )
    psi_lifetime_edges = [
        edge
        for edge in graph["edges"]
        if edge["edge_kind"] == "data_object_lifetime" and edge.get("object_id") == "psi"
    ]
    assert {
        (edge["source"], edge["target"])
        for edge in psi_lifetime_edges
    } == {("scf", "nscf"), ("scf", "bands")}
    assert all(edge["data_mb"] == pytest.approx(64 * 1024 * 1024 / 1.0e6) for edge in psi_lifetime_edges)
    assert all(edge["object_bytes"] == 64 * 1024 * 1024 for edge in psi_lifetime_edges)
    assert not any(
        edge["edge_kind"] == "data_object_lifetime" and edge.get("object_id") == "rho"
        for edge in graph["edges"]
    )
    assert all(":" not in node_id for node_id in graph["nodes"])


def test_qe_fpga_l2_request_bundle_rejects_contractless_workflow_abstraction_when_strict():
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    contractless_abstraction = {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "workload_id": "strict_contractless_l2",
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            "stage_count": 1,
            "observed_runtime": False,
            "artifact_dependency_count": 0,
        },
        "graph": {"node_count": 1, "edge_count": 0, "nodes": [], "edges": []},
        "features": {
            "workflow_classes": ["scf"],
            "stage_count": 1,
            "kernel_weights": {"h_psi": 1.0},
            "observed_total_phase_wall_seconds": 1.0,
            "estimated_total_data_movement_bytes": 8 * 1024 * 1024,
            "host_control_intensity": 0.1,
            "data_movement_intensity": 0.01,
            "scf_iteration_count_observed": 1,
            "stage_repetition": {"scf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 1}},
            "host_control_events": {
                "scf_convergence_check_count": 1,
                "post_processing_stage_count": 0,
                "io_checkpoint_event_count": 1,
                "retained_kernel_counts": {},
            },
            "correctness_observables": {
                "workflow": ["total_energy"],
                "per_stage": {},
                "observed_values": {},
            },
        },
        "data_objects": {},
        "source_facts": [],
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }

    with pytest.raises(ValueError, match="workflow_feature_contract"):
        build_qe_fpga_l2_request_bundle(
            manifest,
            problem,
            screening["promotion_queue"],
            workflow_abstraction=contractless_abstraction,
            require_workflow_feature_contract=True,
        )


def test_qe_fpga_l2_tlm_runner_executes_requests_and_calibrates_l1_rank():
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )

    results = run_qe_fpga_l2_tlm_requests(bundle)
    calibration = build_qe_fpga_l2_calibration_report(screening, results)

    assert results["schema_version"] == "dse.qe_fpga_l2_tlm_results.v1"
    assert results["request_count"] == 5
    assert results["executed_count"] == 5
    assert results["fidelity"] == "L2_python_tlm"
    assert results["claim_boundary"] == "l2_tlm_model_result_not_systemc_gem5_or_fpga_implementation_evidence"
    assert all(row["status"] in {"passed", "failed"} for row in results["results"])
    assert all(row["metrics"]["tlm_workflow_wall_time_ms"] > 0.0 for row in results["results"])
    assert all(row["metrics"]["tlm_energy_mj"] > 0.0 for row in results["results"])
    assert all(row["l1_reference_metrics"]["estimated_workflow_wall_time_ms"] > 0.0 for row in results["results"])

    assert calibration["schema_version"] == "dse.qe_fpga_l1_l2_calibration.v1"
    assert calibration["sample_count"] == 5
    assert calibration["latency_mape_percent"] >= 0.0
    assert -1.0 <= calibration["spearman_rank_correlation"] <= 1.0
    assert calibration["calibration_status"] in {"usable_for_feedback", "needs_more_samples"}
    assert calibration["claim_boundary"] == "calibration_feedback_only_not_final_ranking_or_fpga_evidence"


def _synthetic_l1_l2_calibration_payloads(l2_latencies: list[float], l2_energies: list[float] | None = None):
    l1_latencies = [100.0, 200.0, 300.0, 400.0, 500.0]
    l1_energies = [10.0, 20.0, 30.0, 40.0, 50.0]
    if l2_energies is None:
        l2_energies = [2.0 * value + 5.0 for value in l1_energies]
    l1_screening = {
        "candidate_evaluations": [
            {
                "candidate_id": f"synthetic_{index}",
                "design_key": f"design_{index}",
                "metrics": {
                    "estimated_workflow_wall_time_ms": latency,
                    "estimated_energy_mj": energy,
                },
            }
            for index, (latency, energy) in enumerate(zip(l1_latencies, l1_energies))
        ],
        "promotion_queue": [],
    }
    l2_results = {
        "results": [
            {
                "candidate_id": f"synthetic_{index}",
                "design_key": f"design_{index}",
                "metrics": {
                    "tlm_workflow_wall_time_ms": latency,
                    "tlm_energy_mj": energy,
                },
            }
            for index, (latency, energy) in enumerate(zip(l2_latencies, l2_energies))
        ],
    }
    return l1_screening, l2_results


def test_qe_fpga_l2_calibration_fits_scale_bias_noise_and_intervals():
    l1_screening, l2_results = _synthetic_l1_l2_calibration_payloads(
        [175.0, 325.0, 475.0, 625.0, 775.0],
    )

    calibration = build_qe_fpga_l2_calibration_report(l1_screening, l2_results)

    assert calibration["calibration_status"] == "usable_for_feedback"
    assert calibration["blockers"] == []
    latency_model = calibration["calibration_model"]["latency_ms"]
    energy_model = calibration["calibration_model"]["energy_mj"]
    assert math.isclose(latency_model["scale"], 1.5, rel_tol=1.0e-9)
    assert math.isclose(latency_model["bias"], 25.0, rel_tol=1.0e-9)
    assert math.isclose(latency_model["residual_rmse"], 0.0, abs_tol=1.0e-9)
    assert latency_model["noise_cv"] == 0.0
    assert math.isclose(energy_model["scale"], 2.0, rel_tol=1.0e-9)
    assert math.isclose(energy_model["bias"], 5.0, rel_tol=1.0e-9)
    assert calibration["prediction_interval"]["latency_ms"]["p95_abs_error"] == 0.0
    assert calibration["prediction_interval"]["energy_mj"]["p95_abs_error"] == 0.0
    assert calibration["feedback_recommendation"]["use_l2_to_reorder_promoted_candidates"] is True
    assert all(
        sample["calibrated_l1_latency_ms"] == sample["l2_latency_ms"]
        for sample in calibration["samples"]
    )
    assert all(
        sample["calibrated_l1_energy_mj"] == sample["l2_energy_mj"]
        for sample in calibration["samples"]
    )


def test_qe_fpga_l2_calibration_blocks_negative_rank_feedback():
    l1_screening, l2_results = _synthetic_l1_l2_calibration_payloads(
        [775.0, 625.0, 475.0, 325.0, 175.0],
    )

    calibration = build_qe_fpga_l2_calibration_report(l1_screening, l2_results)

    assert calibration["calibration_status"] == "blocked_calibration_rank_inversion"
    assert "negative_rank_correlation_between_l1_and_l2" in calibration["blockers"]
    assert calibration["feedback_recommendation"]["use_l2_to_reorder_promoted_candidates"] is False
    assert calibration["feedback_recommendation"]["collect_more_l2_samples"] is True


def test_qe_fpga_l2_calibration_blocks_high_residual_feedback():
    l1_screening, l2_results = _synthetic_l1_l2_calibration_payloads(
        [100.0, 10000.0, 300.0, 12000.0, 500.0],
    )

    calibration = build_qe_fpga_l2_calibration_report(l1_screening, l2_results)

    assert calibration["calibration_status"] == "blocked_calibration_error_too_high"
    assert "calibration_prediction_error_above_feedback_threshold" in calibration["blockers"]
    assert calibration["prediction_interval"]["latency_ms"]["p95_abs_error"] > 1000.0
    assert calibration["feedback_recommendation"]["use_l2_to_reorder_promoted_candidates"] is False


def test_qe_fpga_search_baseline_report_compares_policies_with_l2_oracle():
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )

    report = build_qe_fpga_search_baseline_report(
        manifest,
        problem,
        screening,
        evaluation_budget=5,
    )

    assert report["schema_version"] == "dse.qe_fpga_search_baseline_report.v1"
    assert report["oracle_fidelity"] == "L2_python_tlm"
    assert report["evaluation_budget"] == 5
    assert report["candidate_count"] == screening["candidate_count"]
    assert report["policy_count"] >= 5
    assert report["claim_boundary"] == "search_baseline_l2_tlm_only_not_final_hardware_evidence"

    policies = {row["policy_id"]: row for row in report["policies"]}
    required = {
        "wamf_generic_active_pareto",
        "workflow_aware_pareto_funnel",
        "random_seeded",
        "manual_hbm_streaming_heuristic",
        "nsga2_lite_multi_objective",
        "single_fidelity_l1_edp",
        "kernel_level_hotspot_only",
        "no_workflow_abstraction_ablation",
    }
    assert required.issubset(policies)

    method = policies["wamf_generic_active_pareto"]
    prior = policies["workflow_aware_pareto_funnel"]
    random = policies["random_seeded"]
    nsga2 = policies["nsga2_lite_multi_objective"]
    ablation = policies["no_workflow_abstraction_ablation"]
    assert report["proposed_method_policy_id"] == "wamf_generic_active_pareto"
    assert report["cheap_prior_policy_id"] == "workflow_aware_pareto_funnel"
    assert method["selected_count"] == 5
    assert method["l2_oracle"]["evaluated_count"] == 5
    assert method["l2_oracle"]["passed_count"] >= 1
    assert method["l2_oracle"]["best_tlm_edp"] > 0.0
    assert method["l2_oracle"]["oracle_rank_of_best_selected"] >= 1
    assert method["selection_basis"]["baseline_type"] == "proposed_generic_algorithm_kernel"
    assert method["selection_basis"]["generic_kernel_policy"] == "wamf_constrained_active_pareto"
    assert method["selection_basis"]["uses_generic_acquisition_kernel"] is True
    assert method["selection_basis"]["uses_workflow_abstraction"] is True
    assert prior["selection_basis"]["baseline_type"] == "cheap_workflow_prior"
    assert prior["selection_basis"]["uses_generic_acquisition_kernel"] is False
    assert random["selection_basis"]["baseline_type"] == "random"
    assert nsga2["selection_basis"]["baseline_type"] == "evolutionary_multi_objective"
    assert nsga2["selection_basis"]["uses_pareto_selection"] is True
    assert nsga2["selection_basis"]["objective_count"] >= 4
    assert nsga2["selection_basis"]["selection_algorithm"] == "deterministic_nsga2_lite"
    assert ablation["selection_basis"]["uses_workflow_abstraction"] is False
    assert all("candidate_ids" in row and row["candidate_ids"] for row in report["policies"])
    assert report["best_policy_by_l2_edp"]["policy_id"] in policies
    assert all(
        row["l2_oracle"]["best_status"] == "passed"
        for row in report["policies"]
        if row["l2_oracle"]["passed_count"] > 0
    )
    assert all("status" in row for policy in report["policies"] for row in policy["result_summaries"])

    sweep = report["budget_sweep"]
    assert sweep["schema_version"] == "dse.qe_fpga_search_budget_sweep.v1"
    assert sweep["oracle_fidelity"] == "L2_python_tlm"
    assert sweep["budgets"] == [1, 2, 4, 5]
    assert sweep["random_seed_count"] >= 5
    assert sweep["claim_boundary"] == "budget_sweep_l2_tlm_only_not_hardware_evidence"
    assert {
        "wamf_generic_active_pareto",
        "workflow_aware_pareto_funnel",
        "single_fidelity_l1_edp",
        "kernel_level_hotspot_only",
        "manual_hbm_streaming_heuristic",
        "nsga2_lite_multi_objective",
        "random_seeded_multi_seed",
    }.issubset({row["policy_id"] for row in sweep["policy_curves"]})

    method_curve = next(row for row in sweep["policy_curves"] if row["policy_id"] == "wamf_generic_active_pareto")
    nsga2_curve = next(row for row in sweep["policy_curves"] if row["policy_id"] == "nsga2_lite_multi_objective")
    manual_curve = next(row for row in sweep["policy_curves"] if row["policy_id"] == "manual_hbm_streaming_heuristic")
    random_curve = next(row for row in sweep["policy_curves"] if row["policy_id"] == "random_seeded_multi_seed")
    assert len(method_curve["points"]) == len(sweep["budgets"])
    assert len(nsga2_curve["points"]) == len(sweep["budgets"])
    assert len(manual_curve["points"]) == len(sweep["budgets"])
    assert len(random_curve["points"]) == len(sweep["budgets"])
    assert method_curve["points"][-1]["budget"] == 5
    assert method_curve["points"][-1]["best_tlm_edp"] == method["l2_oracle"]["best_tlm_edp"]
    assert method_curve["points"][-1]["oracle_rank_of_best"] == method["l2_oracle"]["oracle_rank_of_best_selected"]
    assert nsga2_curve["points"][-1]["budget"] == 5
    assert manual_curve["points"][-1]["budget"] == 5
    assert random_curve["points"][-1]["random_seed_count"] == sweep["random_seed_count"]
    assert random_curve["points"][-1]["best_tlm_edp_mean"] > 0.0
    assert random_curve["points"][-1]["best_tlm_edp_std"] >= 0.0
    assert report["feature_ablation_report"]["schema_version"] == "dse.qe_fpga_feature_ablation_report.v1"
    assert report["feature_ablation_report"]["oracle_fidelity"] == "L2_python_tlm"
    assert report["feature_ablation_report"]["evaluation_budget"] == 5
    assert report["feature_ablation_report"]["claim_boundary"] == "feature_ablation_l2_tlm_only_not_hardware_evidence"
    ablations = {row["ablation_id"]: row for row in report["feature_ablation_report"]["ablations"]}
    assert {
        "full_workflow_structural_features",
        "remove_data_object_lifetime",
        "remove_host_control_events",
        "remove_correctness_gate_pressure",
        "kernel_histogram_only",
    }.issubset(ablations)
    full = ablations["full_workflow_structural_features"]
    no_lifetime = ablations["remove_data_object_lifetime"]
    no_host = ablations["remove_host_control_events"]
    kernel_only = ablations["kernel_histogram_only"]
    assert full["removed_feature_groups"] == []
    assert full["selection_basis"]["baseline_type"] == "workflow_feature_prior_baseline"
    assert full["selection_basis"]["component_role"] == "l1_workflow_prior_full_features"
    assert no_lifetime["removed_feature_groups"] == ["data_object_lifetime"]
    assert no_host["removed_feature_groups"] == ["host_control_event_counts"]
    assert kernel_only["selection_basis"]["uses_workflow_abstraction"] is False
    assert all(row["l2_oracle"]["best_tlm_edp"] > 0.0 for row in ablations.values())
    assert full["l2_oracle"]["oracle_rank_of_best_selected"] >= 1
    feature_removed_rows = [no_lifetime, no_host, ablations["remove_correctness_gate_pressure"]]
    assert any(row["candidate_ids"] != full["candidate_ids"] for row in feature_removed_rows)
    assert any(
        row["l2_oracle"]["oracle_rank_of_best_selected"] > full["l2_oracle"]["oracle_rank_of_best_selected"]
        for row in feature_removed_rows
    )
    assert full["comparison_to_full"]["decision_changed"] is False
    assert full["comparison_to_full"]["candidate_jaccard_with_full"] == 1.0
    assert any(row["comparison_to_full"]["decision_changed"] is True for row in feature_removed_rows)
    assert any(row["comparison_to_full"]["rank_delta_vs_full"] > 0 for row in feature_removed_rows)
    assert all(row["comparison_to_full"]["best_edp_ratio_vs_full"] >= 1.0 for row in feature_removed_rows)
    assert "random_multi_seed_reproducible_not_statistical_proof" in report["experiment_limitations"]


def test_qe_fpga_wamf_policy_uses_global_generic_acquisition_batch():
    manifest, problem, candidates = _candidate_payloads(256)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=8,
    )

    selected = qe_fpga_dse._policy_wamf_generic_active_pareto(
        screening["candidate_evaluations"],
        screening,
        budget=4,
    )

    assert len(selected) == 4
    assert len({row["candidate_id"] for row in selected}) == 4
    assert len({row["design_key"] for row in selected}) == 4

    report = qe_fpga_dse._wamf_generic_acquisition_kernel_report(
        screening,
        {"evaluation_trace": []},
        budget=4,
    )
    assert report["policy_id"] == "wamf_constrained_active_pareto"
    release_count = sum(
        1
        for row in screening["candidate_evaluations"]
        if row["promotion"]["release_pareto_eligible"] is True
    )
    assert report["candidate_count"] == release_count
    assert report["algorithm_contract"]["selection_scope"] == "global_candidate_set"
    assert report["algorithm_contract"]["batch_rescoring"] is True
    assert report["selected_candidate_ids"] == [row["candidate_id"] for row in selected]


def test_qe_fpga_active_acquisition_risk_axes_include_data_lifetime_communication_fit():
    manifest, problem, candidates = _candidate_payloads(2500)
    abstraction = _contract_first_workflow_abstraction("contract_first_acquisition_workflow")
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
        workflow_abstraction=abstraction,
        require_workflow_feature_contract=True,
    )
    release_rows = [
        row
        for row in screening["candidate_evaluations"]
        if row["promotion"]["release_pareto_eligible"] is True
    ]
    hbm_fit = next(
        row
        for row in release_rows
        if row["parameters"]["memory_topology"] == "hbm_multi_channel"
        and row["parameters"]["data_residency"] == "fpga_hbm_resident_hot_arrays"
    )
    host_streaming = next(
        row
        for row in release_rows
        if row["parameters"]["memory_topology"] == "ddr_streaming"
        and row["parameters"]["data_residency"] == "host_resident_with_streaming_windows"
    )

    hbm_candidate = qe_fpga_dse._active_search_candidate_from_qe_row(hbm_fit, screening["workload_features"])
    host_candidate = qe_fpga_dse._active_search_candidate_from_qe_row(host_streaming, screening["workload_features"])

    assert hbm_candidate.risk_axes["data_lifetime_communication"] > host_candidate.risk_axes["data_lifetime_communication"]
    assert hbm_candidate.risk_axes["data_lifetime_communication"] > hbm_candidate.risk_axes["data_object_lifetime"]
    assert hbm_candidate.risk_axes["hbm_lifetime_residency_fit"] > 0.0
    assert host_candidate.risk_axes["hbm_lifetime_residency_fit"] == 0.0


def test_qe_fpga_action_selection_treats_l2_python_tlm_as_l2_prerequisite_feedback():
    manifest, problem, candidates = _candidate_payloads(512)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    release_rows = [
        row for row in screening["candidate_evaluations"]
        if row["promotion"]["release_pareto_eligible"] is True
    ]
    l2_results = run_qe_fpga_l2_tlm_requests(
        build_qe_fpga_l2_request_bundle(
            manifest,
            problem,
            release_rows,
        )
    )["results"]
    l2_result = next(row for row in l2_results if row["status"] == "passed")
    first_release = next(row for row in release_rows if row["candidate_id"] == l2_result["candidate_id"])
    assert l2_result["fidelity"] == "L2_python_tlm"
    l2_observation = qe_fpga_dse._active_search_observation_from_l2_result(
        l2_result,
        source="unit_test_l2_feedback",
    )

    assert l2_observation is not None
    assert l2_observation.fidelity == "L2_systemc_or_tlm"
    report = qe_fpga_dse.MultiFidelityActiveSearchPolicy(
        objective_names=(
            "estimated_workflow_wall_time_ms",
            "estimated_energy_mj",
            "fpga_resource_pressure",
            "estimated_data_movement_mb",
            "infeasibility_penalty",
        )
    ).action_selection_report(
        [qe_fpga_dse._active_search_candidate_from_qe_row(first_release, screening["workload_features"])],
        fidelities=qe_fpga_dse._qe_fpga_default_fidelity_actions(),
        observations=[l2_observation],
        action_budget=1,
        cost_budget=6.0,
    )

    assert report["selected_candidate_fidelity_pairs"]
    selected = report["selection"][0]
    assert selected["candidate_id"] == first_release["candidate_id"]
    assert selected["fidelity"] in {"L3_systemc_or_gem5", "HLS_c_synthesis"}
    assert selected["action_components"]["prerequisites_satisfied"] == 1.0
    assert selected["action_components"]["already_observed_action"] == 0.0


def test_qe_fpga_implementation_package_plan_targets_promoted_l2_candidates():
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)

    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=2,
    )

    assert plan["schema_version"] == "dse.qe_fpga_implementation_package_plan.v1"
    assert plan["method_name"] == "WAMF-DSE"
    assert plan["package_count"] == 2
    assert plan["status"] == "packages_planned_not_synthesized"
    assert plan["claim_boundary"] == "implementation_package_plan_only_not_hls_vivado_or_bitstream_evidence"
    assert all(package["status"] == "ready_to_materialize_sources" for package in plan["packages"])

    first = plan["packages"][0]
    assert first["candidate_id"]
    assert first["source_files"] == [
        "candidate_manifest.json",
        "hls/qe_workflow_accel.cpp",
        "hls/qe_workflow_accel.hpp",
        "host/host_stub.cpp",
        "scripts/run_hls.tcl",
        "scripts/run_vivado_packaging.tcl",
        "README.md",
    ]
    assert first["tool_flow"]["hls_tool"] == "vivado_hls_or_vitis_hls"
    assert first["tool_flow"]["fpga_packaging_tool"] == "vivado_or_vitis"
    assert "write_bitstream_or_xclbin" in first["tool_flow"]["blocked_until_real_tool_run"]
    assert first["closure_contract"]["schema_version"] == "dse.qe_fpga_implementation_closure_contract.v1"
    assert first["closure_contract"]["candidate_bound"] is True
    assert first["closure_contract"]["source_kind"] == "candidate_bound_scaffold"
    assert first["closure_contract"]["performance_feedback_allowed"] is False
    assert first["closure_contract"]["gates"]["candidate_manifest"] == "planned"
    assert first["closure_contract"]["gates"]["hls_sources"] == "planned"
    assert first["closure_contract"]["gates"]["qe_golden_vectors"] == "missing"
    assert first["closure_contract"]["gates"]["hls_csim"] == "not_run"
    assert first["closure_contract"]["gates"]["hls_csynth"] == "not_run"
    assert first["closure_contract"]["gates"]["vivado_implementation"] == "not_run"
    assert first["closure_contract"]["gates"]["bitstream"] == "not_run"
    assert "replace_scaffold_with_qe_kernel_or_workflow_source" in first["closure_contract"]["blocking_requirements"]
    assert "attach_qe_golden_vector_manifest" in first["closure_contract"]["blocking_requirements"]


def test_qe_fpga_implementation_packages_materialize_candidate_bound_hls_sources(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=2,
    )

    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)

    assert materialized["schema_version"] == "dse.qe_fpga_implementation_package_materialization.v1"
    assert materialized["method_name"] == "WAMF-DSE"
    assert materialized["status"] == "sources_materialized_not_synthesized"
    assert materialized["package_count"] == 2
    assert materialized["closure_summary"]["schema_version"] == "dse.qe_fpga_implementation_closure_summary.v1"
    assert materialized["closure_summary"]["package_count"] == 2
    assert materialized["closure_summary"]["performance_feedback_allowed_count"] == 0
    assert materialized["closure_summary"]["synthesis_ready_count"] == 0
    assert "qe_golden_vectors" in materialized["closure_summary"]["blocked_gate_counts"]
    assert "hls_csynth" in materialized["closure_summary"]["blocked_gate_counts"]
    assert materialized["claim_boundary"] == "materialized_hls_sources_only_not_synthesis_or_bitstream_evidence"
    assert all(row["status"] == "sources_materialized_not_synthesized" for row in materialized["packages"])

    first = materialized["packages"][0]
    package_root = tmp_path / first["package_dir"]
    for rel_path in plan["packages"][0]["source_files"]:
        assert (package_root / rel_path).exists(), rel_path

    manifest_payload = json.loads((package_root / "candidate_manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["candidate_id"] == first["candidate_id"]
    assert manifest_payload["status"] == "sources_materialized_not_synthesized"
    assert manifest_payload["closure_contract"]["source_kind"] == "candidate_bound_scaffold"
    assert manifest_payload["closure_contract"]["gates"]["qe_golden_vectors"] == "missing"
    assert manifest_payload["closure_contract"]["performance_feedback_allowed"] is False
    assert manifest_payload["candidate_parameters"]["deployment_target"] == "fpga"
    assert manifest_payload["candidate_parameters"]["vector_lanes"] in {2, 4, 8}
    assert manifest_payload["candidate_parameters"]["hbm_channel_count"] in {0, 4, 8}
    assert manifest_payload["candidate_parameters"]["tile_doubles"] in {1024, 2048, 4096}
    assert manifest_payload["claim_boundary"] == "materialized_hls_sources_only_not_synthesis_or_bitstream_evidence"

    hls_source = (package_root / "hls" / "qe_workflow_accel.cpp").read_text(encoding="utf-8")
    assert "extern \"C\" void qe_workflow_accel" in hls_source
    assert "#pragma HLS INTERFACE m_axi port=in" in hls_source
    assert "#pragma HLS INTERFACE s_axilite port=return" in hls_source
    assert f"Candidate id: {first['candidate_id']}" in hls_source
    assert plan["packages"][0]["candidate_parameters"]["architecture_template"] in hls_source
    assert f"QE_FPGA_VECTOR_LANES = {manifest_payload['candidate_parameters']['vector_lanes']}" in hls_source
    assert f"QE_FPGA_HBM_CHANNELS = {manifest_payload['candidate_parameters']['hbm_channel_count']}" in hls_source
    assert f"QE_FPGA_TILE_DOUBLES = {manifest_payload['candidate_parameters']['tile_doubles']}" in hls_source

    hls_tcl = (package_root / "scripts" / "run_hls.tcl").read_text(encoding="utf-8")
    assert "open_project qe_workflow_accel_hls" in hls_tcl
    assert "set_top qe_workflow_accel" in hls_tcl
    assert "csim_design" in hls_tcl
    assert "csynth_design" in hls_tcl

    vivado_tcl = (package_root / "scripts" / "run_vivado_packaging.tcl").read_text(encoding="utf-8")
    assert "write_bitstream" in vivado_tcl
    assert "requires a real board part, constraints, and synthesized RTL" in vivado_tcl

    closure_path = package_root / "implementation_closure_contract.json"
    assert closure_path.exists()
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert closure == manifest_payload["closure_contract"]
    assert "run_hls_csim_or_rtl_sim_against_qe_golden_vectors" in closure["next_actions"]


def test_qe_fpga_hls_attempt_rejects_fake_tool_as_hardware_feedback(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=1,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)
    package_root = tmp_path / materialized["packages"][0]["package_dir"]

    fake_hls = tmp_path / "fake_vivado_hls"
    fake_hls.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Vivado HLS fake tool for regression'\n"
        "echo 'csim_design PASS'\n"
        "echo 'csynth_design PASS'\n"
        "mkdir -p qe_workflow_accel_hls/solution1/syn/report\n"
        "cat > qe_workflow_accel_hls/solution1/syn/report/qe_workflow_accel_csynth.rpt <<'EOF'\n"
        "== Performance Estimates\n"
        "Latency (cycles): min = 64 max = 64\n"
        "Interval Min = 1\n"
        "Timing: 4.000 ns\n"
        "== Utilization Estimates\n"
        "BRAM_18K: 3\n"
        "DSP48E: 5\n"
        "FF: 1024\n"
        "LUT: 2048\n"
        "EOF\n",
        encoding="utf-8",
    )
    fake_hls.chmod(0o755)

    attempt = run_qe_fpga_hls_attempt(
        package_root,
        hls_tool=str(fake_hls),
        timeout_s=20,
    )

    assert attempt["schema_version"] == "dse.qe_fpga_hls_attempt.v1"
    assert attempt["method_name"] == "WAMF-DSE"
    assert attempt["status"] == "hls_attempt_non_evidence"
    assert attempt["candidate_id"] == materialized["packages"][0]["candidate_id"]
    assert attempt["commands"][0]["returncode"] == 0
    assert attempt["commands"][0]["tool"] == str(fake_hls)
    assert "csynth_design PASS" in attempt["commands"][0]["stdout_tail"]
    assert attempt["tool_evidence_classification"]["classification"] == "synthetic_or_test_tool"
    assert "tool_name_contains_fake_or_mock" in attempt["tool_evidence_classification"]["blockers"]
    assert attempt["evidence_gate_summary"]["hls_tool_gate"] == "failed"
    assert attempt["evidence_gate_summary"]["source_semantics_gate"] == "failed"
    assert attempt["evidence_gate_summary"]["hls_csim_gate"] == "passed"
    assert attempt["evidence_gate_summary"]["hls_csynth_gate"] == "passed"
    assert attempt["evidence_gate_summary"]["performance_feedback_allowed"] is False
    assert attempt["evidence_gate_summary"]["synthesis_evidence_allowed"] is False
    assert attempt["evidence_gate_summary"]["vivado_implementation_gate"] == "not_attempted"
    assert attempt["evidence_gate_summary"]["bitstream_gate"] == "not_attempted"
    assert "tool_name_contains_fake_or_mock" in attempt["evidence_gate_summary"]["blockers"]
    assert "kernel_source_is_candidate_bound_scaffold" in attempt["evidence_gate_summary"]["blockers"]
    assert attempt["hls_csim_status"] == "passed"
    assert attempt["hls_csynth_status"] == "passed"
    assert attempt["report_refs"]["csynth_report"]["exists"] is True
    assert attempt["parsed_reports"]["csynth"]["status"] == "parsed"
    assert attempt["parsed_reports"]["csynth"]["latency_cycles_min"] == 64
    assert attempt["parsed_reports"]["csynth"]["latency_cycles_max"] == 64
    assert attempt["parsed_reports"]["csynth"]["initiation_interval"] == 1
    assert attempt["parsed_reports"]["csynth"]["clock_period_ns"] == 4.0
    assert attempt["parsed_reports"]["csynth"]["resource_estimates"]["bram_18k"] == 3
    assert attempt["parsed_reports"]["csynth"]["resource_estimates"]["dsp"] == 5
    assert attempt["parsed_reports"]["csynth"]["resource_estimates"]["ff"] == 1024
    assert attempt["parsed_reports"]["csynth"]["resource_estimates"]["lut"] == 2048
    assert attempt["feedback_sample"] is None
    assert (
        attempt["claim_boundary"]
        == "hls_attempt_records_tool_execution_only_not_vivado_implementation_or_bitstream_evidence"
    )

    persisted = json.loads((package_root / "hls_attempt.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "hls_attempt_non_evidence"


def test_qe_fpga_hls_attempt_rejects_scaffold_sources_even_with_real_named_tool(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=1,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)
    package_root = tmp_path / materialized["packages"][0]["package_dir"]

    real_named_hls = tmp_path / "vivado_hls"
    real_named_hls.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Vivado HLS v2019.1'\n"
        "echo 'csim_design PASS'\n"
        "echo 'csynth_design PASS'\n"
        "mkdir -p qe_workflow_accel_hls/solution1/syn/report\n"
        "cat > qe_workflow_accel_hls/solution1/syn/report/qe_workflow_accel_csynth.rpt <<'EOF'\n"
        "== Performance Estimates\n"
        "Latency (cycles): min = 64 max = 64\n"
        "Interval Min = 1\n"
        "Timing: 4.000 ns\n"
        "== Utilization Estimates\n"
        "BRAM_18K: 3\n"
        "DSP48E: 5\n"
        "FF: 1024\n"
        "LUT: 2048\n"
        "EOF\n",
        encoding="utf-8",
    )
    real_named_hls.chmod(0o755)

    attempt = run_qe_fpga_hls_attempt(
        package_root,
        hls_tool=str(real_named_hls),
        timeout_s=20,
    )

    assert attempt["tool_evidence_classification"]["classification"] == "synthetic_or_test_tool"
    assert "tool_identity_probe_failed" in attempt["tool_evidence_classification"]["blockers"]
    assert attempt["package_evidence_classification"]["classification"] == "scaffold_sources_only"
    assert "kernel_source_is_candidate_bound_scaffold" in attempt["package_evidence_classification"]["blockers"]
    assert "qe_golden_vector_manifest_missing" in attempt["package_evidence_classification"]["blockers"]
    assert attempt["evidence_gate_summary"]["hls_tool_gate"] == "failed"
    assert attempt["evidence_gate_summary"]["source_semantics_gate"] == "failed"


def test_qe_fpga_hls_attempt_rejects_ordinary_script_named_like_hls_tool(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=1,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)
    package_root = tmp_path / materialized["packages"][0]["package_dir"]

    forged_hls = tmp_path / "vivado_hls"
    forged_hls.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Vivado HLS v2019.1'\n"
        "echo 'csim_design PASS'\n"
        "echo 'csynth_design PASS'\n"
        "mkdir -p qe_workflow_accel_hls/solution1/syn/report\n"
        "cat > qe_workflow_accel_hls/solution1/syn/report/qe_workflow_accel_csynth.rpt <<'EOF'\n"
        "== Performance Estimates\n"
        "Latency (cycles): min = 64 max = 64\n"
        "Interval Min = 1\n"
        "Timing: 4.000 ns\n"
        "== Utilization Estimates\n"
        "BRAM_18K: 3\n"
        "DSP48E: 5\n"
        "FF: 1024\n"
        "LUT: 2048\n"
        "EOF\n",
        encoding="utf-8",
    )
    forged_hls.chmod(0o755)

    attempt = run_qe_fpga_hls_attempt(
        package_root,
        hls_tool=str(forged_hls),
        timeout_s=20,
    )

    assert attempt["tool_evidence_classification"]["classification"] == "synthetic_or_test_tool"
    assert "tool_identity_probe_failed" in attempt["tool_evidence_classification"]["blockers"]
    assert attempt["tool_evidence_classification"]["allowed_feedback_use"] is False
    assert attempt["evidence_gate_summary"]["hls_tool_gate"] == "failed"
    assert attempt["evidence_gate_summary"]["performance_feedback_allowed"] is False
    assert attempt["evidence_gate_summary"]["hls_csim_gate"] == "passed"
    assert attempt["evidence_gate_summary"]["hls_csynth_gate"] == "passed"
    assert attempt["evidence_gate_summary"]["performance_feedback_allowed"] is False
    assert attempt["evidence_gate_summary"]["synthesis_evidence_allowed"] is False
    assert "kernel_source_is_candidate_bound_scaffold" in attempt["evidence_gate_summary"]["blockers"]
    assert attempt["status"] == "hls_attempt_non_evidence"
    assert attempt["feedback_sample"] is None
    assert attempt["parsed_reports"]["csynth"]["status"] == "parsed"


def test_qe_fpga_hls_attempt_fails_closed_when_hls_tool_is_missing(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=1,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)
    package_root = tmp_path / materialized["packages"][0]["package_dir"]
    missing_tool = tmp_path / "missing_vivado_hls"

    attempt = run_qe_fpga_hls_attempt(
        package_root,
        hls_tool=str(missing_tool),
        timeout_s=20,
    )

    assert attempt["schema_version"] == "dse.qe_fpga_hls_attempt.v1"
    assert attempt["status"] == "blocked_hls_tool_unavailable"
    assert attempt["hls_csim_status"] == "blocked"
    assert attempt["hls_csynth_status"] == "blocked"
    assert attempt["blockers"] == ["hls_tool_unavailable"]
    assert attempt["commands"] == []
    assert os.path.isabs(attempt["tool_resolution"]["requested_tool"])
    assert attempt["evidence_gate_summary"]["hls_tool_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["source_semantics_gate"] == "failed"
    assert attempt["evidence_gate_summary"]["hls_csim_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["hls_csynth_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["performance_feedback_allowed"] is False
    assert attempt["evidence_gate_summary"]["synthesis_evidence_allowed"] is False
    assert "hls_tool_unavailable" in attempt["evidence_gate_summary"]["blockers"]


def test_qe_fpga_hls_attempt_summary_runs_materialized_final_candidate_packages(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=2,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)

    summary = run_qe_fpga_hls_attempts_for_materialized_packages(
        materialized,
        tmp_path,
        hls_tool=str(tmp_path / "missing_vitis_hls"),
        timeout_s=5,
    )

    assert summary["schema_version"] == "dse.qe_fpga_hls_attempt_summary.v1"
    assert summary["method_name"] == "WAMF-DSE"
    assert summary["status"] == "hls_attempts_blocked_or_non_evidence"
    assert summary["attempt_count"] == 2
    assert summary["attempt_status_counts"] == {"blocked_hls_tool_unavailable": 2}
    assert summary["performance_feedback_allowed_count"] == 0
    assert summary["synthesis_evidence_allowed_count"] == 0
    assert summary["vivado_implementation_count"] == 0
    assert summary["bitstream_count"] == 0
    assert summary["package_source"]["schema_version"] == "dse.qe_fpga_implementation_package_materialization.v1"
    assert summary["hls_tool_request"].endswith("missing_vitis_hls")
    assert summary["claim_boundary"] == "hls_attempt_summary_downstream_validation_only_not_search_objective"
    assert summary["required_next_tool_steps"] == [
        "install_or_activate_real_vitis_hls_or_vivado_hls",
        "replace_scaffold_with_qe_kernel_or_workflow_source",
        "attach_qe_golden_vector_manifest",
        "rerun_hls_csim_and_csynth",
        "run_vivado_implementation_and_bitstream_when_platform_constraints_exist",
        "feed_allowed_feedback_samples_back_to_calibration",
    ]
    assert all(row["status"] == "blocked_hls_tool_unavailable" for row in summary["attempts"])
    assert all(row["candidate_id"] for row in summary["attempts"])
    assert all(row["package_dir"].startswith("implementation_packages/") for row in summary["attempts"])
    assert all("hls_tool_unavailable" in row["blockers"] for row in summary["attempts"])
    for row in summary["attempts"]:
        attempt_path = tmp_path / row["package_dir"] / "hls_attempt.json"
        assert attempt_path.exists()
        persisted = json.loads(attempt_path.read_text(encoding="utf-8"))
        assert persisted["candidate_id"] == row["candidate_id"]
        assert persisted["status"] == row["status"]


def test_qe_fpga_vivado_attempt_fails_closed_when_tool_or_rtl_is_missing(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=1,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)
    package_root = tmp_path / materialized["packages"][0]["package_dir"]

    attempt = run_qe_fpga_vivado_attempt(
        package_root,
        vivado_tool=str(tmp_path / "missing_vivado"),
        timeout_s=5,
    )

    assert attempt["schema_version"] == "dse.qe_fpga_vivado_attempt.v1"
    assert attempt["method_name"] == "WAMF-DSE"
    assert attempt["status"] == "blocked_vivado_tool_unavailable"
    assert attempt["candidate_id"] == materialized["packages"][0]["candidate_id"]
    assert attempt["commands"] == []
    assert attempt["tool_resolution"]["requested_tool"].endswith("missing_vivado")
    assert attempt["evidence_gate_summary"]["vivado_tool_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["hls_rtl_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["vivado_synthesis_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["vivado_implementation_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["bitstream_gate"] == "blocked"
    assert attempt["evidence_gate_summary"]["implementation_evidence_allowed"] is False
    assert attempt["evidence_gate_summary"]["bitstream_evidence_allowed"] is False
    assert "vivado_tool_unavailable" in attempt["evidence_gate_summary"]["blockers"]
    assert "hls_synthesized_rtl_missing" in attempt["evidence_gate_summary"]["blockers"]
    assert attempt["report_refs"]["vivado_script"]["exists"] is True
    persisted = json.loads((package_root / "vivado_attempt.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "blocked_vivado_tool_unavailable"


def test_qe_fpga_vivado_attempt_summary_runs_materialized_packages(tmp_path: Path):
    manifest, problem, candidates = _candidate_payloads(2500)
    screening = build_qe_fpga_l1_screening_report(
        manifest,
        problem,
        candidates,
        promotion_budget=5,
    )
    bundle = build_qe_fpga_l2_request_bundle(
        manifest,
        problem,
        screening["promotion_queue"],
    )
    results = run_qe_fpga_l2_tlm_requests(bundle)
    plan = build_qe_fpga_implementation_package_plan(
        manifest,
        bundle,
        results,
        package_budget=2,
    )
    materialized = materialize_qe_fpga_implementation_packages(plan, tmp_path)

    summary = run_qe_fpga_vivado_attempts_for_materialized_packages(
        materialized,
        tmp_path,
        vivado_tool=str(tmp_path / "missing_vivado"),
        timeout_s=5,
    )

    assert summary["schema_version"] == "dse.qe_fpga_vivado_attempt_summary.v1"
    assert summary["method_name"] == "WAMF-DSE"
    assert summary["status"] == "vivado_attempts_blocked_or_non_evidence"
    assert summary["attempt_count"] == 2
    assert summary["attempt_status_counts"] == {"blocked_vivado_tool_unavailable": 2}
    assert summary["implementation_evidence_allowed_count"] == 0
    assert summary["bitstream_evidence_allowed_count"] == 0
    assert summary["vivado_implementation_count"] == 0
    assert summary["bitstream_count"] == 0
    assert summary["package_source"]["schema_version"] == "dse.qe_fpga_implementation_package_materialization.v1"
    assert summary["vivado_tool_request"].endswith("missing_vivado")
    assert summary["claim_boundary"] == "vivado_attempt_summary_downstream_validation_only_not_search_objective"
    assert summary["required_next_tool_steps"] == [
        "install_or_activate_real_vivado",
        "complete_hls_csynth_to_materialize_rtl",
        "add_real_fpga_part_constraints_and_timing_constraints",
        "rerun_vivado_synthesis_implementation_and_bitstream",
        "feed_allowed_implementation_reports_back_to_calibration",
    ]
    assert all(row["status"] == "blocked_vivado_tool_unavailable" for row in summary["attempts"])
    assert all(row["candidate_id"] for row in summary["attempts"])
    assert all(row["attempt_ref"].endswith("/vivado_attempt.json") for row in summary["attempts"])
    for row in summary["attempts"]:
        attempt_path = tmp_path / row["package_dir"] / "vivado_attempt.json"
        assert attempt_path.exists()


def test_qe_fpga_l2_request_graph_uses_stage_local_compute_bindings():
    workflow_abstraction = {
        "schema_version": "dse.qe_workflow_fpga_abstraction.v1",
        "workload_id": "stage_local_compute",
        "source": {
            "kind": "qe_workflow_bundle",
            "input_model": "qe_native_workflow_bundle",
            "stage_count": 3,
            "observed_runtime": True,
            "artifact_dependency_count": 2,
        },
        "graph": {
            "node_count": 3,
            "edge_count": 2,
            "nodes": [],
            "edges": [
                {"source_stage": "scf", "target_stage": "nscf", "edge_kind": "stage_artifact_dependency"},
                {"source_stage": "nscf", "target_stage": "bands", "edge_kind": "stage_artifact_dependency"},
            ],
        },
        "features": {
            "workflow_classes": ["scf", "nscf", "post_processing"],
            "stage_count": 3,
            "kernel_weights": {"h_psi": 1.2, "fft": 0.8, "band_path_projection": 0.4, "write_bands": 0.2},
            "observed_total_phase_wall_seconds": 2.6,
            "estimated_total_data_movement_bytes": 96 * 1024 * 1024,
            "host_control_intensity": 0.14,
            "data_movement_intensity": 0.02,
            "scf_iteration_count_observed": 2,
            "stage_repetition": {
                "scf": {"repetition_kind": "scf_iteration_loop", "observed_iterations": 2},
                "nscf": {"repetition_kind": "single_electronic_spectrum_pass", "observed_iterations": 1},
                "bands": {"repetition_kind": "single_post_processing_pass", "observed_iterations": 1},
            },
            "host_control_events": {
                "scf_convergence_check_count": 2,
                "post_processing_stage_count": 1,
                "io_checkpoint_event_count": 2,
                "retained_kernel_counts": {},
            },
            "correctness_observables": {"workflow": ["total_energy", "eigenvalue_spectrum"], "per_stage": {}},
            "workflow_feature_contract": {
                "schema_version": "dse.workflow_feature_contract.v1",
                "domain_neutral": True,
                "source_adapter": "qe_workflow_fpga_abstraction",
                "workload_family": "qe",
                "workflow_id": "stage_local_compute",
                "workflow_dag": {
                    "stage_count": 3,
                    "stages": [
                        {"stage_id": "scf", "stage_type": "scf", "stage_class": "scf"},
                        {"stage_id": "nscf", "stage_type": "nscf", "stage_class": "nscf"},
                        {"stage_id": "bands", "stage_type": "bands", "stage_class": "post_processing"},
                    ],
                    "edges": [
                        {"source_stage": "scf", "target_stage": "nscf", "edge_kind": "stage_artifact_dependency"},
                        {"source_stage": "nscf", "target_stage": "bands", "edge_kind": "stage_artifact_dependency"},
                    ],
                },
                "stage_feature_table": [
                    {
                        "stage_id": "scf",
                        "stage_type": "scf",
                        "stage_class": "scf",
                        "program": "pw.x",
                        "compute_ids": ["h_psi", "fft", "mix_rho"],
                        "expected_repetition": 2,
                        "host_control_barrier": True,
                        "include_in_performance_model": True,
                    },
                    {
                        "stage_id": "nscf",
                        "stage_type": "nscf",
                        "stage_class": "nscf",
                        "program": "pw.x",
                        "compute_ids": ["h_psi", "c_bands"],
                        "expected_repetition": 1,
                        "host_control_barrier": False,
                        "include_in_performance_model": True,
                    },
                    {
                        "stage_id": "bands",
                        "stage_type": "bands",
                        "stage_class": "post_processing",
                        "program": "bands.x",
                        "compute_ids": ["band_path_projection", "write_bands"],
                        "expected_repetition": 1,
                        "host_control_barrier": False,
                        "include_in_performance_model": True,
                    },
                ],
                "stage_compute_feature_table": {
                    "scf": [
                        {"compute_id": "h_psi", "weight_seconds": 1.2},
                        {"compute_id": "fft", "weight_seconds": 0.8},
                        {"compute_id": "mix_rho", "weight_seconds": 0.1},
                    ],
                    "nscf": [
                        {"compute_id": "h_psi", "weight_seconds": 1.0},
                        {"compute_id": "c_bands", "weight_seconds": 0.3},
                    ],
                    "bands": [
                        {"compute_id": "band_path_projection", "weight_seconds": 0.4},
                        {"compute_id": "write_bands", "weight_seconds": 0.2},
                    ],
                },
                "data_object_table": [],
                "compute_feature_table": [
                    {"compute_id": "h_psi", "weight_seconds": 1.2},
                    {"compute_id": "fft", "weight_seconds": 0.8},
                    {"compute_id": "band_path_projection", "weight_seconds": 0.4},
                    {"compute_id": "write_bands", "weight_seconds": 0.2},
                ],
                "correctness_observable_table": {"workflow": ["total_energy", "eigenvalue_spectrum"], "per_stage": {}},
                "search_objectives": ["latency", "energy", "edp", "resource_pressure", "data_movement", "feasibility_risk"],
                "claim_boundary": "workflow_features_only_not_evidence_not_candidate_identity",
            },
        },
        "claim_boundary": "workload_abstraction_only_not_fpga_performance_evidence",
    }

    report = qe_fpga_dse._request_graph_from_workflow_feature_contract(workflow_abstraction["features"])

    assert report["schema_version"] == "dse.qe_workflow_request_graph.v1"
    assert set(report["nodes"].keys()) == {"scf", "nscf", "bands"}
    assert report["nodes"]["scf"]["kernels"] == ["h_psi", "fft", "mix_rho"]
    assert report["nodes"]["nscf"]["kernels"] == ["h_psi", "c_bands"]
    assert report["nodes"]["bands"]["kernels"] == ["band_path_projection", "write_bands"]
    assert {edge["edge_kind"] for edge in report["edges"]} == {"stage_artifact_dependency"}


def test_qe_fpga_request_graph_falls_back_to_manifest_sequence_without_contract():
    manifest = {
        "cases": [
            {
                "case_id": "qe_case_a",
                "stage_type": "scf",
                "kernel_coverage": ["h_psi", "fft"],
                "baseline_sequence": [
                    {"step_id": "scf", "stage_type": "scf", "program": "pw.x"},
                    {"step_id": "bands", "stage_type": "post_processing", "program": "bands.x"},
                ],
            }
        ]
    }
    features = {
        "workflow_classes": ["scf", "post_processing"],
        "kernel_weights": {"h_psi": 1.2, "fft": 0.8},
        "estimated_workflow_data_volume_mb": 16.0,
        "workflow_dependency_edge_count": 1,
        "total_profile_seconds": 2.0,
        "stage_count": 2,
    }

    report = qe_fpga_dse._request_graph(manifest, features)

    assert report["schema_version"] == "dse.qe_workflow_request_graph.v1"
    assert report["source"] == "qe_mainflow_manifest"
    assert set(report["nodes"]) == {"qe_case_a:scf", "qe_case_a:bands"}
    assert report["nodes"]["qe_case_a:scf"]["estimated_weight_ms"] > 0.0
    assert report["nodes"]["qe_case_a:bands"]["estimated_weight_ms"] > 0.0
    assert any(
        edge["source"] == "qe_case_a:scf"
        and edge["target"] == "qe_case_a:bands"
        and edge["edge_kind"] == "workflow_sequence"
        for edge in report["edges"]
    )
