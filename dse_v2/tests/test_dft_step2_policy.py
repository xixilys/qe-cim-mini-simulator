#!/usr/bin/env python3
"""Focused tests for the reference-scoped DFT Step2 policy."""

from __future__ import annotations

from dse_v2.architecture.catalog import seed_generic_dse_architecture_catalog
from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.workload import package_from_graph
from dse_v2.mapping.domain_policy import Step2PolicyInput
from dse_v2.reference_workloads.dft_step2_policy import (
    DFT_ARCHITECTURE_FAMILIES,
    DFT_HARD_REVIEW_FLAGS,
    DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS,
    DFT_SOFT_REVIEW_FLAGS,
    DftStep2ReferencePolicy,
    build_dft_hierarchical_funnel_search_report,
    build_dft_hierarchical_search_problem,
    dft_hardware_template_families,
)


def _dft_policy_graph() -> ComputeGraph:
    graph = ComputeGraph(graph_id="dft_policy_graph", metadata={"workload_family": "dft_reference"})
    spec = TensorSpec(shape=(16, 16), dtype="COMPLEX_FP64")
    graph.add_node(ComputeNode(
        "hpsi",
        "gemm",
        inputs=["psi", "h"],
        outputs=["hpsi_out"],
        input_specs={"psi": spec, "h": spec},
        output_specs={"hpsi_out": spec},
        estimated_flops=8192,
        estimated_memory_bytes=4096,
        attributes={"adapter:dft": {
            "phase_id": "h_psi",
            "source_fact_ids": ["fact:hpsi"],
            "evidence_level": "profile_observed",
            "dominance": "dominant",
        }},
    ))
    graph.add_node(ComputeNode(
        "ext_fft",
        "fft",
        inputs=["hpsi_out"],
        outputs=["rho_g"],
        input_specs={"hpsi_out": spec},
        output_specs={"rho_g": spec},
        estimated_flops=4096,
        estimated_memory_bytes=2048,
        attributes={"adapter:dft": {
            "phase_id": "extension:qe:custom_fft",
            "source_fact_ids": ["fact:ext"],
            "evidence_level": "declared",
        }},
    ))
    graph.add_node(ComputeNode(
        "unknown_custom",
        "custom_kernel",
        inputs=["rho_g"],
        outputs=["out"],
        input_specs={"rho_g": spec},
        output_specs={"out": spec},
        estimated_flops=1024,
        estimated_memory_bytes=1024,
        attributes={"adapter:dft": {
            "phase_id": "unknown:stable_custom",
            "source_fact_ids": ["fact:unknown"],
            "evidence_level": "heuristic_phase",
        }},
    ))
    graph.add_edge(DataEdge("hpsi", "ext_fft", "hpsi_out", spec))
    graph.add_edge(DataEdge("ext_fft", "unknown_custom", "rho_g", spec))
    return graph


def _policy_input(*, domain_metadata=None, workload_characterization=None) -> Step2PolicyInput:
    graph = _dft_policy_graph()
    package = package_from_graph(
        graph,
        workload_family="dft_reference",
        importer_id="dft_test_importer",
        domain_metadata=domain_metadata or {},
    )
    return Step2PolicyInput(
        workload_package=package,
        source_graph=graph,
        executable_graph=graph,
        lowering_report={"status": "ok"},
        workload_characterization=workload_characterization,
        backend="systemc",
        evidence_mode="summary",
    )


def _build_hints(policy_input: Step2PolicyInput):
    policy = DftStep2ReferencePolicy()
    catalog = seed_generic_dse_architecture_catalog()
    assert policy.matches(policy_input)
    return policy.build_hints(policy_input, catalog, "balanced-generic-systemc-v0").to_dict()


def test_dft_step2_policy_extracts_phase_summary_review_flags_and_adapter_attributes():
    characterization = {
        "domain_phase_summary": {
            "schema_version": "dse.domain_phase_summary.v1",
            "source_program": "qe-pw.x",
            "phase_summaries": [
                {"phase_id": "h_psi", "dominance": "dominant", "evidence_level": "profile_observed"},
                {"phase_id": "extension:qe:custom_fft", "dominance": "candidate"},
            ],
            "dominance_summary": {"dominant_phase_ids": ["h_psi"]},
            "review_flags": ["important_input_parameter"],
        }
    }
    hints = _build_hints(_policy_input(
        domain_metadata={"dft": {"source_program": "qe-pw.x", "review_flags": ["insufficient_evidence"]}},
        workload_characterization=characterization,
    ))

    dft = hints["annotations"]["dft"]
    node_map = {item["node_id"]: item for item in dft["node_phase_map"]}
    assert hints["domain_key"] == "dft"
    assert hints["trusted_final_claim"] is False
    assert hints["review_required"] is True
    assert hints["review_required_flags"] == ["important_input_parameter", "insufficient_evidence"]
    assert dft["source_program"] == "qe-pw.x"
    assert dft["dominant_phase_ids"] == ["h_psi"]
    assert node_map["hpsi"]["source_fact_ids"] == ["fact:hpsi"]
    assert node_map["hpsi"]["evidence_level"] == "profile_observed"
    assert hints["node_target_preferences"]["hpsi"][:2] == ["fpga", "gpu"]


def test_dft_step2_policy_maps_canonical_extension_and_unknown_phases_safely():
    hints = _build_hints(_policy_input(domain_metadata={"dft": {"source_program": "qe-pw.x"}}))

    node_map = {item["node_id"]: item for item in hints["annotations"]["dft"]["node_phase_map"]}
    assert node_map["hpsi"]["phase_group"] == "dense_linear_algebra"
    assert node_map["hpsi"]["candidate_only"] is False
    assert node_map["ext_fft"]["phase_group"] == "extension_or_unknown"
    assert node_map["ext_fft"]["candidate_only"] is False
    assert "generic op-type" in node_map["ext_fft"]["reason"]
    assert hints["node_target_preferences"]["ext_fft"][:2] == ["fpga", "gpu"]
    assert node_map["unknown_custom"]["candidate_only"] is True
    assert hints["node_target_preferences"]["unknown_custom"] == ["host"]
    assert "segmentation_uncertain" not in hints["review_flags"]


def test_dft_step2_policy_emits_only_generic_hints_with_dft_annotations_namespaced():
    hints = _build_hints(_policy_input(domain_metadata={"dft": {"source_program": "qe-pw.x"}}))

    top_level_forbidden_dft_details = {"phase_ids", "node_phase_map", "source_fact_ids", "source_program"}
    assert top_level_forbidden_dft_details.isdisjoint(hints)
    assert "dft" in hints["annotations"]
    assert set(hints["node_target_preferences"]) == {"hpsi", "ext_fft", "unknown_custom"}
    assert all(seed["seed_name"].startswith("policy:") for seed in hints["mapping_seeds"])
    assert all(seed["trusted_final_claim"] is False for seed in hints["mapping_seeds"])
    assert all(candidate["trusted_final_claim"] is False for candidate in hints["architecture_candidates"])


def test_dft_step2_policy_emits_research_derived_step3_searchable_architecture_candidates():
    hints = _build_hints(_policy_input(domain_metadata={"dft": {"source_program": "qe-pw.x"}}))

    expected_ids = {record["architecture_id"] for record in DFT_ARCHITECTURE_FAMILIES}
    candidates = {record["architecture_id"]: record for record in hints["architecture_candidates"]}
    preferences = {record["architecture_id"]: record for record in hints["architecture_preferences"]}

    assert expected_ids.issubset(candidates)
    assert expected_ids.issubset(preferences)
    assert all(candidates[architecture_id]["step3_searchable"] is True for architecture_id in expected_ids)
    assert all(candidates[architecture_id]["candidate_only"] is False for architecture_id in expected_ids)
    assert all(candidates[architecture_id]["source_refs"] for architecture_id in expected_ids)
    assert preferences["dft-fpga-systolic-gemm-v0"]["matched_phase_groups"]
    assert hints["annotations"]["dft"]["architecture_taxonomy_doc"] == "docs/architecture/dft_architecture_family_research.md"


def test_dft_step2_policy_hard_and_soft_review_flags_are_classified():
    metadata = {
        "dft": {
            "review_flags": ["project_critical_conflict"],
            "coverage": {"review_flags": ["insufficient_evidence"]},
            "conflicts": [{"review_flags": ["important_input_parameter"]}],
        }
    }
    characterization = {
        "domain_phase_summary": {
            "schema_version": "dse.domain_phase_summary.v1",
            "phase_summaries": [{"phase_id": "h_psi", "dominance": "dominant"}],
            "coverage_summary": {"review_flags": ["segmentation_uncertain"]},
        }
    }
    hints = _build_hints(_policy_input(domain_metadata=metadata, workload_characterization=characterization))

    assert set(hints["hard_block_flags"]) == DFT_HARD_REVIEW_FLAGS
    assert set(hints["review_required_flags"]) == DFT_SOFT_REVIEW_FLAGS
    assert set(hints["review_flags"]) == DFT_HARD_REVIEW_FLAGS | DFT_SOFT_REVIEW_FLAGS
    assert hints["hard_blocked"] is True
    assert hints["review_required"] is True
    assert hints["step3_queue"]["review_required"] is True


def test_dft_step2_policy_uses_workflow_stage_skeleton_for_fpga_candidate_groups():
    metadata = {
        "dft": {
            "source_program": "qe-pw.x",
            "workflow": {
                "schema_version": "dse.dft.workflow_spec.v1",
                "stages": [
                    {
                        "stage_id": "stage_00_scf",
                        "stage_type": "scf",
                        "phase_skeleton": [
                            {"phase_id": "exact_exchange", "evidence_level": "predicted_static"},
                            {"phase_id": "uspp_augmentation", "evidence_level": "predicted_static"},
                        ],
                    }
                ],
                "hotspot_claims": [
                    {
                        "phase_id": "exact_exchange",
                        "claim_kind": "dominance",
                        "kernel_kind": "batched_gemm",
                        "evidence_level": "predicted_static",
                    }
                ],
            },
        }
    }
    graph = ComputeGraph(graph_id="dft_workflow_policy_graph", metadata={"workload_family": "dft_reference"})
    spec = TensorSpec(shape=(8, 8), dtype="COMPLEX_FP64")
    graph.add_node(ComputeNode(
        "exx",
        "batched_gemm",
        inputs=["psi"],
        outputs=["fock_psi"],
        input_specs={"psi": spec},
        output_specs={"fock_psi": spec},
        estimated_flops=4096,
        estimated_memory_bytes=2048,
        attributes={"adapter:dft": {"phase_id": "exact_exchange", "source_fact_ids": ["fact:exx"]}},
    ))
    graph.add_node(ComputeNode(
        "uspp",
        "reduction",
        inputs=["beta"],
        outputs=["aug"],
        input_specs={"beta": spec},
        output_specs={"aug": spec},
        estimated_flops=1024,
        estimated_memory_bytes=1024,
        attributes={"adapter:dft": {"phase_id": "uspp_augmentation", "source_fact_ids": ["fact:uspp"]}},
    ))
    package = package_from_graph(
        graph,
        workload_family="dft_reference",
        importer_id="dft_test_importer",
        domain_metadata=metadata,
    )
    policy_input = Step2PolicyInput(
        workload_package=package,
        source_graph=graph,
        executable_graph=graph,
        lowering_report={"status": "ok"},
        workload_characterization={},
        backend="systemc",
        evidence_mode="summary",
    )

    hints = _build_hints(policy_input)
    node_map = {item["node_id"]: item for item in hints["annotations"]["dft"]["node_phase_map"]}

    assert node_map["exx"]["phase_group"] == "hybrid_exchange"
    assert node_map["uspp"]["phase_group"] == "projector_augmentation"
    assert hints["node_target_preferences"]["exx"][:2] == ["fpga", "gpu"]
    assert hints["node_target_preferences"]["uspp"][:2] == ["fpga", "gpu"]
    assert "hybrid_exchange" in hints["data_placement"]["phase_groups"]
    assert "projector_augmentation" in hints["data_placement"]["phase_groups"]


def test_dft_release_search_space_contains_required_hardware_template_families():
    families = dft_hardware_template_families()
    by_id = {row["template_family_id"]: row for row in families}

    assert set(DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS).issubset(by_id)
    assert by_id["streaming_fft_hpsi_pipeline"]["release_policy"]["lane"] == "release"
    assert by_id["projector_heavy_gemm_gemv"]["release_policy"]["lane"] == "release"
    assert by_id["memory_hbm_dma_transpose"]["release_policy"]["lane"] == "release"
    assert by_id["hybrid_cpu_fpga_scf_sidecar"]["release_policy"]["lane"] == "release"
    assert by_id["asic_tile_array_template"]["release_policy"]["lane"] == "release"
    assert by_id["wide_exploratory_noc_hls_variants"]["release_policy"]["lane"] == "exploratory"
    assert all("candidate_tier" not in row for row in families)
    assert "fft_ifft_ffft" in by_id["streaming_fft_hpsi_pipeline"]["major_kernel_ids"]
    assert "nonlocal_projector" in by_id["projector_heavy_gemm_gemv"]["major_kernel_ids"]
    assert "dma_hbm_movement_engine" in by_id["memory_hbm_dma_transpose"]["major_kernel_ids"]
    assert "reduction_dot_tree" in by_id["asic_tile_array_template"]["major_kernel_ids"]
    assert all(row["source_refs"] for row in families)
    assert all("no hardware acceleration" in row["claim_boundary"] for row in families)


def test_dft_hierarchical_funnel_report_keeps_wide_search_out_of_formal_pareto():
    problem = build_dft_hierarchical_search_problem()
    report = build_dft_hierarchical_funnel_search_report(budget=32)

    assert "candidate_tier" not in problem.parameters
    assert "candidate_tier" not in problem.constraints["required_parameters"]
    assert "release_lane" not in problem.parameters
    assert "release_lane" not in problem.constraints["required_parameters"]
    assert all("candidate_tier" not in seed for seed in problem.seed_candidates)
    assert all("release_lane" not in seed for seed in problem.seed_candidates)
    assert report["status"] == "passed"
    assert report["funnel_stage_order"] == [
        "template_legality_enumeration",
        "analytic_screen",
        "bottleneck_guided_refinement",
        "hls_rtl_ppa_calibration",
        "evidence_eligible_pareto",
    ]
    assert report["candidate_generation"]["missing_release_template_family_ids"] == []
    assert report["candidate_generation"]["exploratory_candidate_ids_in_formal_pareto"] == []
    assert report["wide_space_policy"]["wide_space_lane"] == "exploratory"
    assert report["wide_space_policy"]["wide_space_can_enter_formal_pareto_without_release_gate"] is False
    assert all("candidate_tier" not in record["parameters"] for record in report["all_records"])
    assert all("release_lane" not in record["parameters"] for record in report["all_records"])
    assert all(
        record["policy_metadata"]["policy_source"] == "dft_hardware_template_families"
        for record in report["all_records"]
    )
    assert report["formal_pareto_records"]
    assert all(
        record["policy_metadata"]["formal_pareto_eligible"] is True
        and record["policy_metadata"]["template_policy"]["release_policy"]["formal_pareto_allowed"] is True
        and record["parameters"]["template_family"] in DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS
        and record["parameters"]["precision_mode"] == "fp64_strict"
        and record["simulation_eligible"] is True
        for record in report["formal_pareto_records"]
    )
    assert report["exploratory_records"]
    assert all(
        record["policy_metadata"]["formal_pareto_eligible"] is False
        or record["parameters"]["template_family"] not in DFT_REQUIRED_HARDWARE_TEMPLATE_FAMILY_IDS
        or record["parameters"]["precision_mode"] != "fp64_strict"
        or record["simulation_eligible"] is False
        for record in report["exploratory_records"]
    )
    exhaustive_report = build_dft_hierarchical_funnel_search_report(
        budget=len(problem.parameter_grid()) + len(problem.seed_candidates)
    )
    assert all(
        "candidate_tier" not in record["parameters"]
        and "release_lane" not in record["parameters"]
        for record in exhaustive_report["all_records"]
    )
    assert any(
        record["parameters"]["template_family"] == "wide_exploratory_noc_hls_variants"
        and record["policy_metadata"]["template_policy"]["release_policy"]["lane"] == "exploratory"
        and record["policy_metadata"]["formal_pareto_eligible"] is False
        and record["policy_metadata"]["exploratory_queue_allowed"] is True
        for record in exhaustive_report["exploratory_records"]
    )
    assert all(
        record["parameters"]["template_family"] != "wide_exploratory_noc_hls_variants"
        for record in exhaustive_report["formal_pareto_records"]
    )
    assert "trusted Pareto" in report["claim_boundary"]
