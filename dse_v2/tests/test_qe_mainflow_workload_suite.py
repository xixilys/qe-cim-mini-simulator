#!/usr/bin/env python3
"""QE mainflow workload-suite and patch-manifest regressions."""

from __future__ import annotations

import copy

from dse_v2.mapping.search_policy import HierarchicalFunnelSearchPolicy
from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import build_qe_workflow_fpga_abstraction
from dse_v2.reference_workloads.qe_mainflow import (
    build_qe_fpga_deployment_search_problem,
    default_qe_mainflow_workload_suite,
    example_qe_patch_runtime_manifest,
    package_qe_mainflow_case,
    qe_patch_runtime_manifest_schema,
    validate_qe_mainflow_workload_suite,
    validate_qe_patch_runtime_manifest,
)


def test_default_qe_mainflow_suite_covers_release_v1_mainflow_and_boundary():
    manifest = default_qe_mainflow_workload_suite()
    report = validate_qe_mainflow_workload_suite(manifest)

    assert report["valid"] is True
    assert report["release_v1_workload_suite_accepted"] is True
    assert report["trusted_closure_ready"] is False
    assert report["case_count"] >= 4
    assert {"scf", "nscf", "post_processing", "relax"}.issubset(set(report["mainflow_classes"]))
    assert manifest["candidate_identity_policy"]["workload_case_ids_participate"] is False
    assert all(case["candidate_identity_participation"] is False for case in manifest["cases"])
    assert all(case["adapter_boundary"]["generic_core_required_qe_fields"] == [] for case in manifest["cases"])
    assert all(case["baseline_run_provenance"] for case in manifest["cases"])
    assert all(case["tolerance_reference"]["required_fields"] for case in manifest["cases"])
    assert any("fft" in case["kernel_coverage"] for case in manifest["cases"])


def test_scf_only_qe_suite_is_rejected_for_release_acceptance():
    manifest = default_qe_mainflow_workload_suite()
    manifest["cases"] = [case for case in manifest["cases"] if case["stage_type"] == "scf"]
    manifest.pop("suite_hash", None)

    report = validate_qe_mainflow_workload_suite(manifest)

    assert report["valid"] is False
    assert report["release_v1_workload_suite_accepted"] is False
    messages = "\n".join(error["message"] for error in report["errors"])
    assert "not release-v1 mainflow complete" in messages
    assert "SCF-only suite" in messages


def test_qe_suite_case_round_trips_through_reference_importer_without_core_qe_fields():
    manifest = default_qe_mainflow_workload_suite()
    for case in manifest["cases"]:
        package = package_qe_mainflow_case(case)
        payload = package.to_dict()
        validation = package.validate()

        assert validation["valid"] is True
        assert payload["workload_family"] == "dft"
        assert payload["domain_metadata"]["dft"]["source_program"] == "qe"
        assert payload["source"]["kind"] == "qe_workflow_bundle"
        graph = payload["graph"]
        assert graph["schema_version"] == "dse.compute_graph.v1"
        assert graph["nodes"]
        assert all("npw" not in node and "nbnd" not in node for node in graph["nodes"].values())
        assert all("adapter:dft" in node["attributes"] for node in graph["nodes"].values())


def test_qe_patch_runtime_manifest_blocks_trusted_status_on_missing_safety_fields():
    schema = qe_patch_runtime_manifest_schema()
    assert "fallback_path is required" in schema["trusted_status_rules"][0]

    manifest = example_qe_patch_runtime_manifest()
    assert validate_qe_patch_runtime_manifest(manifest)["trusted_status_allowed"] is True

    broken = copy.deepcopy(manifest)
    broken["rows"][0].pop("fallback_path")
    broken["rows"][0]["tolerance_impact"] = {}
    report = validate_qe_patch_runtime_manifest(broken)

    assert report["valid"] is False
    assert report["trusted_status_allowed"] is False
    blocked_fields = {block["field"].split(".")[-1] for block in report["trusted_blocks"]}
    assert {"fallback_path", "tolerance_impact"}.issubset(blocked_fields)


def test_qe_mainflow_suite_builds_fpga_deployment_search_problem_not_scf_slice():
    manifest = default_qe_mainflow_workload_suite()

    problem = build_qe_fpga_deployment_search_problem(manifest, workload_run_id="qe_suite_run_001")

    assert problem.problem_id == "qe_mainflow_fpga_deployment_dse"
    assert problem.workload_run_id == "qe_suite_run_001"
    assert problem.objective == "pareto_latency_energy_resource_feasibility"
    assert problem.parameter_grid_size() > 1

    parameter_keys = set(problem.parameters)
    assert {
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
        "precision_policy",
    }.issubset(parameter_keys)

    assert "scf_only" not in problem.parameters["offload_boundary"]
    assert problem.constraints["input_scope"] == "qe_multi_program_workflow"
    assert problem.constraints["requires_post_processing_stage"] is True
    assert problem.constraints["forbidden_shortcuts"] == [
        "single_kernel_speedup_as_workflow_result",
        "scf_only_as_final_boundary",
        "hls_report_without_implementation_feasibility",
    ]
    assert set(problem.constraints["workflow_stage_types"]).issuperset({"scf", "nscf", "bands", "relax"})
    assert problem.constraints["required_parameters"] == [
        "deployment_target",
        "release_lane",
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
        "vector_lanes",
        "hbm_channel_count",
        "tile_doubles",
        "precision_policy",
    ]
    assert problem.constraints["feedback_generalization_axes"] == [
        "architecture_template",
        "offload_boundary",
        "mapping_granularity",
        "runtime_schedule",
        "data_residency",
        "memory_topology",
    ]
    assert problem.constraints["feedback_generalization_strength"] == 0.15
    assert problem.constraints["formal_pareto_lane_field"] == "release_lane"
    assert problem.constraints["release_lane"] == "release"
    assert problem.constraints["proposal_only_before_model_promotion"] is True
    assert problem.constraints["model_objectives"] == [
        {
            "metric": "vector_lanes",
            "direction": "maximize",
            "weight": 0.25,
            "scale": 8.0,
            "role": "cheap_proxy_for_candidate_compute_parallelism_before_L1_screening",
        },
        {
            "metric": "hbm_channel_count",
            "direction": "maximize",
            "weight": 0.20,
            "scale": 8.0,
            "role": "cheap_proxy_for_memory_bandwidth_before_L1_screening",
        },
        {
            "metric": "tile_doubles",
            "direction": "maximize",
            "weight": 0.05,
            "scale": 4096.0,
            "role": "cheap_proxy_for_locality_before_L1_screening",
        },
    ]
    assert problem.constraints["model_objective_boundary"].startswith("pre_l1_candidate_ordering_only")
    assert problem.constraints["requires_physical_evidence"] is True
    assert problem.constraints["workflow_dependency_edges"]
    assert problem.constraints["workflow_data_artifacts"]
    assert problem.seed_candidates
    assert all(seed["deployment_target"] == "fpga" for seed in problem.seed_candidates)


def test_qe_fpga_deployment_search_problem_uses_workflow_contract_before_manifest():
    manifest = default_qe_mainflow_workload_suite()
    workflow_bundle = {
        "workflow_id": "contract_primary_workflow",
        "stages": [
            {
                "stage_id": "contract_scf",
                "program": "pw.x",
                "stage_type": "scf",
                "input": manifest["cases"][0]["step1_source"]["stages"][0]["input"],
                "log": """
                    number of Kohn-Sham states= 8
                    number of plane waves= 321
                    iteration # 1
                    h_psi        :      0.10s CPU      1.20s WALL
                    FFT          :      0.02s CPU      0.20s WALL
                    convergence has been achieved in 1 iterations
                """,
            },
            {
                "stage_id": "contract_projwfc",
                "program": "projwfc.x",
                "stage_type": "projwfc",
                "depends_on": ["contract_scf"],
                "profile": {"phases": {"projector": 0.9, "reduction": 0.3}},
            },
        ],
    }
    workflow_abstraction = build_qe_workflow_fpga_abstraction(
        workflow_bundle,
        workload_id="contract_primary_workflow",
    )
    poisoned_manifest = copy.deepcopy(manifest)
    poisoned_manifest["cases"] = [
        case for case in poisoned_manifest["cases"]
        if case["stage_type"] == "scf"
    ]
    poisoned_manifest["workflow_scope"] = "full_qe_mainflow"

    problem = build_qe_fpga_deployment_search_problem(
        poisoned_manifest,
        workload_run_id="contract_primary_run",
        workflow_abstraction=workflow_abstraction,
    )

    assert problem.constraints["search_problem_source"] == "workflow_feature_contract"
    assert problem.constraints["feature_source_priority"][0] == "workflow_feature_contract"
    assert problem.constraints["manifest_compatibility_fallback_used"] is False
    assert problem.constraints["workflow_feature_contract"]["workflow_id"] == "contract_primary_workflow"
    assert problem.constraints["workflow_stage_types"] == ["projwfc", "scf"]
    assert problem.constraints["workflow_classes"] == ["post_processing", "scf"]
    assert problem.constraints["requires_post_processing_stage"] is True
    assert set(problem.constraints["kernel_kinds"]).issuperset({"h_psi", "projector", "reduction"})
    assert any(
        row["compute_id"] == "projector" and row["accelerator_candidate"] is True
        for row in problem.constraints["workflow_compute_features"]
    )
    assert any(
        artifact["object_id"] == "qe_save_dir"
        for artifact in problem.constraints["workflow_data_artifacts"]
    )


def test_qe_fpga_deployment_search_problem_produces_step2_candidates():
    problem = build_qe_fpga_deployment_search_problem(
        default_qe_mainflow_workload_suite(),
        workload_run_id="qe_suite_run_001",
    )

    records = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
    ).propose(problem, budget=8)

    assert len(records) == 8
    payloads = [record.to_dict() for record in records]
    assert all(payload["parameters"]["deployment_target"] == "fpga" for payload in payloads)
    assert any(payload["parameters"]["memory_topology"] == "hbm_multi_channel" for payload in payloads)
    assert all(payload["provenance"]["model_acquisition"]["status"] == "applied" for payload in payloads)
    assert all(payload["provenance"]["model_acquisition"]["objective_count"] == 3 for payload in payloads)
    assert all(payload["claim_status"] == "step2_proposal_only" for payload in payloads)
    assert all(payload["deliverable_complete"] is False for payload in payloads)
    assert all("workflow_wall_time" in problem.constraints["optimization_metrics"] for _ in payloads)

    assert all(payload["parameters"]["precision_policy"] == "fp64_strict" for payload in payloads)
    assert all(payload["step2_screenable"] is True for payload in payloads)
    assert all(payload["simulation_eligible"] is False for payload in payloads)
    assert all(payload["simulation_blockers"] == ["not_promoted_for_simulation"] for payload in payloads)

    release_payloads = [
        payload for payload in payloads
        if payload["parameters"]["precision_policy"] == "fp64_strict"
        and payload["parameters"]["release_lane"] == "release"
    ]
    assert release_payloads
    assert all("hls_rtl_ppa_calibration" in [
        stage["stage_id"] for stage in payload["provenance"]["funnel_stages"]
    ] for payload in release_payloads)

    larger_budget_records = HierarchicalFunnelSearchPolicy(
        bottleneck_keys=("memory_topology", "data_residency", "offload_boundary"),
    ).propose(problem, budget=64)
    larger_payloads = [record.to_dict() for record in larger_budget_records]
    assert any(payload["parameters"]["architecture_template"] == "fpga_hbm_streaming_dataflow" for payload in larger_payloads)
