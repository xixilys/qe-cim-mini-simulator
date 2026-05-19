#!/usr/bin/env python3
"""Anti-downgrade tests for QE full-callgraph offload search."""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import IDENTITY_LAYER_KEYS
from dse_v2.codesign.qe_callgraph_offload_search import (
    NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    OFFLOAD_TARGET_LAYER,
    SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_WORKLOAD_VARIANT_ID,
    SPSI_USPP_WORKLOAD_VARIANT_ID,
    _extract_static_callgraph,
    build_accelerated_replacement_readiness_report,
    classify_l4_offload_value,
    build_offload_value_l4_evidence_matrix,
    build_l4_speed_optimization_report,
    build_l4_value_repeatability_report,
    build_bundle_runtime_contract_report,
    build_bundle_single_workflow_l4_evidence_report,
    build_bundle_harness_readiness_report,
    materialize_qe_bundle_patch_files,
    build_offload_bundle_viability_report,
    build_offload_selection_search_report,
    build_offload_value_report,
    offload_artifact_bundle,
    write_qe_callgraph_offload_search_artifacts,
)
from dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke import (
    EVIDENCE_MODE_ACTUAL_COMPUTE,
    _apply_workload_variant_binding,
    _build_attempt_evidence,
    _build_transport_request,
    _gem5_command,
    _install_bundle_runtime_env,
    _maybe_select_observed_opportunity,
    _physical_correctness,
    _prelaunched_bridge_supported_kernel,
    _run_patched_qe_bridge_probe,
    _replace_k_points_automatic,
    _runtime_bridge_replacement_summary,
    _select_correctness_metrics,
    _selection_profile_with_trace_anchor,
    _step_matches_opportunity_stage,
    parse_args as parse_smoke_args,
    _trace_contains_kernel,
    _trace_kernel_counts,
    _trace_observed_kernel_count,
    _write_bridge_command_script,
)
from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _parse_qe_stdout
from dse_v2.scripts.dse.build_qe_callgraph_l4_multi_probe_report import (
    build_multi_probe_report,
)
from dse_v2.scripts.dse.build_qe_bundle_speed_diagnostics_report import (
    build_bundle_speed_diagnostics_report,
)
from dse_v2.scripts.dse.run_qe_callgraph_offload_l4_campaign import (
    build_campaign_plan,
    _bridge_dispatch_policy_candidates,
    _smoke_command,
)
from dse_v2.scripts.dse.build_qe_bundle_single_workflow_runner_preflight import (
    build_bundle_single_workflow_runner_preflight,
)
from dse_v2.scripts.dse.run_qe_bundle_single_workflow_l4_actual_compute import (
    _target_attempt_evidence_row,
)
from dse_v2.reference_workloads.qe_mainflow import (
    default_qe_mainflow_workload_suite,
)


def test_first_pass_artifacts_are_not_hpsi_only_or_deliverable_complete(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")

    inventory = artifacts["qe_callgraph_inventory.json"]
    opportunities = artifacts["offload_opportunity_manifest.json"]
    workload_variants = artifacts["offload_workload_variant_search_space.json"]
    bundle_space = artifacts["offload_bundle_search_space.json"]
    matrix = artifacts["offload_value_l4_evidence_matrix.json"]
    report = artifacts["offload_value_report.json"]
    queue = artifacts["l4_offload_attempt_queue.json"]
    checklist = artifacts["prompt_to_artifact_checklist.json"]
    selection_report = artifacts["offload_selection_search_report.json"]
    replacement_report = artifacts["accelerated_replacement_readiness_report.json"]
    patches = artifacts["qe_callsite_patch_manifest.json"]

    kernels = {row["kernel"] for row in opportunities["opportunities"]}
    assert "h_psi" in kernels
    assert kernels - {"h_psi"}
    assert inventory["node_count"] == opportunities["opportunity_count"]
    assert inventory["full_static_qe_callgraph_complete"] is False
    assert (
        "blocked_full_static_qe_callgraph_parser_not_yet_complete"
        in {blocker["id"] for blocker in inventory["blockers"]}
    )
    assert bundle_space["hpsi_only_completion_allowed"] is False
    assert bundle_space["deliverable_complete_allowed"] is False
    assert matrix["projection_only_value_allowed"] is False
    assert matrix["valuable_l4_count"] == 0
    assert matrix["deliverable_complete"] is False
    assert report["claims"]["deliverable_complete"] is False
    assert report["claims"]["projection_only_value_allowed"] is False
    assert queue["deliverable_complete"] is False
    assert selection_report["ranked_opportunity_count"] == opportunities["opportunity_count"]
    assert workload_variants["formal_workload_variant_count"] >= 3
    assert (
        workload_variants["canonical_replacement_requires_explicit_binding"]
        is True
    )
    assert selection_report["formal_workload_variant_count"] >= 3
    assert selection_report["projection_only_value_allowed"] is False
    assert selection_report["deliverable_complete"] is False
    assert replacement_report["deliverable_complete"] is False
    assert replacement_report["hpsi_only_completion_allowed"] is False
    assert replacement_report["value_claim_allowed_by_replacement_gate"] is False
    assert replacement_report["replacement_ready_count"] == 0
    assert replacement_report["patch_precheck_linked_count"] == opportunities["opportunity_count"]
    assert replacement_report["patch_precheck_writeback_count"] >= 1
    assert replacement_report["patch_precheck_component_model_blocked_count"] >= 1
    trusted_patch_rows = [
        row
        for row in patches["patch_rows"]
        if row["instrumentation_capabilities"][
            "trusted_l4_replacement_precheck_passed"
        ]
        is True
    ]
    assert trusted_patch_rows
    assert {
        row["instrumentation_capabilities"]["source_targets"][0]
        for row in trusted_patch_rows
    } == {"FFTXlib/src/fft_fwinv.f90"}
    assert (
        replacement_report[
            "patch_precheck_trusted_l4_replacement_candidate_count"
        ]
        == len(trusted_patch_rows)
    )
    assert patches["trusted_l4_replacement_precheck_count"] == len(trusted_patch_rows)
    assert replacement_report["replacement_ready_count"] == 0
    assert checklist["status"] == "passed"
    checklist_requirements = {row["requirement"] for row in checklist["checks"]}
    assert {
        "smoke/dataflow evidence cannot claim actual-compute or valuable_l4",
        (
            "valuable_l4 remains gated on real L4, correctness, replacement, "
            "baseline, and positive speed"
        ),
        "GPU availability is baseline context, not value evidence",
        (
            "IC/EDA evidence is optional side evidence and cannot substitute "
            "for QE/gem5 value"
        ),
    }.issubset(checklist_requirements)


def test_l4_campaign_plan_searches_non_hpsi_workload_targets(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")

    plan = build_campaign_plan(
        artifacts["offload_opportunity_manifest.json"],
        artifacts["offload_bundle_search_space.json"],
        max_attempts=3,
        include_hpsi=False,
    )

    assert plan["status"] == "planned"
    assert plan["deliverable_complete"] is False
    assert plan["hpsi_only_completion_allowed"] is False
    assert plan["projection_only_value_allowed"] is False
    assert plan["selected_attempt_count"] == 3
    assert plan["selected_non_hpsi_attempt_count"] == 3
    assert plan["selected_hpsi_attempt_count"] == 0
    assert len({row["kernel"] for row in plan["selected_opportunities"]}) > 1
    assert {"workload_variant", "bundle", "callsite", "kernel"}.issubset(
        set(plan["selection_axes"])
    )
    for row in plan["selected_opportunities"]:
        assert row["kernel"] != "h_psi"
        assert row["workload_case_id"]
        assert row["stage_type"]
        assert row["callsite_id"]
        assert row["selected_bundle_id"]
        assert row["selection_reason"] == "ranked_dse_offload_target_search"


def test_bundle_search_space_contains_runnable_workload_stage_bundles(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    bundle_space = artifacts["offload_bundle_search_space.json"]
    workload_bundles = [
        bundle
        for bundle in bundle_space["bundles"]
        if bundle["classification"] == "workload_stage_bundle_l4_attempt_candidate"
    ]

    assert workload_bundles
    scf_bundle = next(
        bundle
        for bundle in workload_bundles
        if bundle["workload_case_id"] == "qe_si_scf_small_v1"
        and bundle["stage_type"] == "scf"
    )
    assert scf_bundle["runnable_as_single_qe_workflow"] is True
    assert scf_bundle["completion_allowed"] is False
    assert scf_bundle["hpsi_only"] is False
    assert len(scf_bundle["opportunity_ids"]) > 1
    assert {"fft", "mix_rho", "rho_out", "veff"}.issubset(
        set(scf_bundle["kernel_list"])
    )
    assert scf_bundle["selection_priority"]["score"] > 0.0
    assert "not completion or value evidence" in scf_bundle["claim_boundary"]


def test_bundle_search_space_contains_runtime_supported_actual_compute_subbundles(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    bundle_space = artifacts["offload_bundle_search_space.json"]
    runtime_bundles = [
        bundle
        for bundle in bundle_space["bundles"]
        if bundle["classification"]
        == "runtime_supported_workload_stage_bundle_l4_attempt_candidate"
    ]

    assert runtime_bundles
    nscf_bundle = next(
        bundle
        for bundle in runtime_bundles
        if bundle["workload_case_id"] == "qe_si_nscf_bandgrid_v1"
        and bundle["stage_type"] == "nscf"
    )
    assert nscf_bundle["runtime_harness_supported"] is True
    assert nscf_bundle["runnable_as_single_qe_workflow"] is True
    assert nscf_bundle["completion_allowed"] is False
    assert nscf_bundle["hpsi_only"] is False
    assert set(nscf_bundle["kernel_list"]) == {"fft", "subspace_rotation"}
    assert len(nscf_bundle["opportunity_ids"]) == 2
    assert nscf_bundle["parent_workload_stage_bundle_id"].startswith(
        "bundle_workload_stage_qe_si_nscf_bandgrid_v1_nscf_"
    )
    assert "not value evidence" in nscf_bundle["claim_boundary"]


def test_l4_campaign_bundle_id_expands_to_workload_bundle_attempts(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    bundle_space = artifacts["offload_bundle_search_space.json"]
    scf_bundle = next(
        bundle
        for bundle in bundle_space["bundles"]
        if bundle["classification"] == "workload_stage_bundle_l4_attempt_candidate"
        and bundle["workload_case_id"] == "qe_si_scf_small_v1"
    )

    plan = build_campaign_plan(
        artifacts["offload_opportunity_manifest.json"],
        bundle_space,
        max_attempts=len(scf_bundle["opportunity_ids"]),
        include_hpsi=True,
        explicit_bundle_ids=[scf_bundle["bundle_id"]],
    )

    assert plan["status"] == "planned"
    assert plan["selected_bundle_count"] == 1
    assert plan["selected_bundle_ids"] == [scf_bundle["bundle_id"]]
    assert plan["selected_bundle_expanded_opportunity_count"] == len(
        scf_bundle["opportunity_ids"]
    )
    assert plan["per_opportunity_expansion_only"] is True
    assert plan["single_qe_workflow_bundle_attempt_planned"] is False
    assert plan["bundle_level_value_claim_allowed"] is False
    assert plan["selected_bundle_single_workflow_candidate_ids"] == [
        scf_bundle["bundle_id"]
    ]
    assert "explicit_bundle_campaign_expands_to_per_opportunity_attempts" in plan[
        "single_workflow_bundle_blockers"
    ]
    assert "single_qe_workflow_bundle_runner_not_implemented_in_campaign" in plan[
        "single_workflow_bundle_blockers"
    ]
    assert plan["selected_non_hpsi_attempt_count"] > 1
    assert plan["selected_hpsi_attempt_count"] >= 1
    assert plan["deliverable_complete"] is False
    for row in plan["selected_opportunities"]:
        assert row["selection_reason"] == "explicit_bundle_id"
        assert row["per_opportunity_expansion_only"] is True
        assert row["single_qe_workflow_bundle_proof"] is False
        assert row["bundle_level_value_claim_allowed"] is False
        assert row["selected_bundle_id"] == scf_bundle["bundle_id"]
        assert (
            row["selected_bundle_classification"]
            == "workload_stage_bundle_l4_attempt_candidate"
        )
        assert row["selected_bundle_runnable_as_single_qe_workflow"] is True
        assert set(row["selected_bundle_kernel_list"]) == set(
            scf_bundle["kernel_list"]
        )


def test_l4_campaign_prioritizes_observed_profile_targets_before_projected(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")

    plan = build_campaign_plan(
        artifacts["offload_opportunity_manifest.json"],
        artifacts["offload_bundle_search_space.json"],
        max_attempts=4,
        include_hpsi=False,
    )

    selected = plan["selected_opportunities"]
    assert selected
    assert all(
        row["profile_evidence"]["status"] == "fixture_profile_observed"
        or row.get("selected_workload_variant_id")
            in {
                SPSI_NC_CG_WORKLOAD_VARIANT_ID,
                SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
                NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
                NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
                NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
                NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
            }
            for row in selected
        )
    assert all(row["kernel"] != "h_psi" for row in selected)
    spsi = next(row for row in selected if row["kernel"] == "s_psi")
    assert (
        spsi["selected_workload_variant_id"]
        == SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID
    )
    assert spsi["selected_workload_variant_binding"]["target_kernel"] == "s_psi"
    assert (
        spsi["selected_workload_variant_binding"]["workload_scale_policy"]
        == "larger_bandgrid"
    )


def test_workload_variant_search_includes_larger_spsi_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    larger = next(
        variant
        for variant in variants
        if variant["variant_id"] == SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID
    )
    assert larger["variant_kind"] == "workload_scale_extension"
    assert larger["offload_target_binding_required_for_candidate_identity"] is True
    assert larger["workload_scale_policy"]["nscf_k_points_automatic"] == "6 6 6 0 0 0"
    assert larger["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "24"
    assert larger["canonical_replacement_allowed"] is False


def test_workload_variant_search_includes_amortized_spsi_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    amortized_spsi = next(
        variant
        for variant in variants
        if variant["variant_id"] == SPSI_NC_CG_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert amortized_spsi["variant_kind"] == "workload_scale_extension"
    assert amortized_spsi["applies_to_kernel"] == "s_psi"
    assert (
        amortized_spsi["offload_target_binding"]["target_kernel"]
        == "s_psi"
    )
    assert (
        amortized_spsi["workload_scale_policy"]["nscf_k_points_automatic"]
        == "8 8 8 0 0 0"
    )
    assert amortized_spsi["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "48"
    assert (
        amortized_spsi["input_overrides"]["assignments"][
            "ELECTRONS.diagonalization"
        ]
        == "'cg'"
    )
    assert amortized_spsi["canonical_replacement_allowed"] is False


def test_workload_variant_search_includes_nscf_amortized_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    amortized = next(
        variant
        for variant in variants
        if variant["variant_id"] == NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert amortized["variant_kind"] == "workload_scale_extension"
    assert amortized["applies_to_workload_case_id"] == "qe_si_nscf_bandgrid_v1"
    assert amortized["applies_to_kernels"] == [
        "diagonalization",
        "fft",
        "subspace_rotation",
    ]
    assert amortized["offload_target_binding_required_for_candidate_identity"] is True
    assert (
        amortized["workload_scale_policy"]["nscf_k_points_automatic"]
        == "8 8 8 0 0 0"
    )
    assert amortized["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "48"
    assert amortized["canonical_replacement_allowed"] is False


def test_workload_variant_search_includes_nscf_heavy_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    heavy = next(
        variant
        for variant in variants
        if variant["variant_id"] == NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert heavy["variant_kind"] == "workload_scale_extension"
    assert heavy["applies_to_workload_case_id"] == "qe_si_nscf_bandgrid_v1"
    assert heavy["applies_to_kernels"] == [
        "diagonalization",
        "fft",
        "subspace_rotation",
    ]
    assert heavy["offload_target_binding_required_for_candidate_identity"] is True
    assert (
        heavy["workload_scale_policy"]["nscf_k_points_automatic"]
        == "10 10 10 0 0 0"
    )
    assert heavy["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "64"
    assert (
        heavy["offload_target_binding"]["workload_scale_policy"]
        == "heavy_bandgrid"
    )
    assert heavy["canonical_replacement_allowed"] is False


def test_workload_variant_search_includes_nscf_ultra_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    ultra = next(
        variant
        for variant in variants
        if variant["variant_id"] == NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert ultra["variant_kind"] == "workload_scale_extension"
    assert ultra["applies_to_workload_case_id"] == "qe_si_nscf_bandgrid_v1"
    assert ultra["applies_to_kernels"] == [
        "diagonalization",
        "fft",
        "subspace_rotation",
    ]
    assert ultra["offload_target_binding_required_for_candidate_identity"] is True
    assert (
        ultra["workload_scale_policy"]["nscf_k_points_automatic"]
        == "12 12 12 0 0 0"
    )
    assert ultra["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "96"
    assert (
        ultra["offload_target_binding"]["workload_scale_policy"]
        == "ultra_bandgrid"
    )
    assert ultra["canonical_replacement_allowed"] is False


def test_workload_variant_search_includes_nscf_stress_bandgrid_variant(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    variants = artifacts["offload_workload_variant_search_space.json"]["variants"]

    stress = next(
        variant
        for variant in variants
        if variant["variant_id"] == NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert stress["variant_kind"] == "workload_scale_extension"
    assert stress["applies_to_workload_case_id"] == "qe_si_nscf_bandgrid_v1"
    assert stress["applies_to_kernels"] == [
        "diagonalization",
        "fft",
        "subspace_rotation",
    ]
    assert stress["offload_target_binding_required_for_candidate_identity"] is True
    assert (
        stress["workload_scale_policy"]["nscf_k_points_automatic"]
        == "14 14 14 0 0 0"
    )
    assert stress["input_overrides"]["assignments"]["SYSTEM.nbnd"] == "128"
    assert (
        stress["offload_target_binding"]["workload_scale_policy"]
        == "stress_bandgrid"
    )
    assert stress["canonical_replacement_allowed"] is False


def test_l4_campaign_selects_heaviest_nscf_variant_by_target_kernels(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")

    plan = build_campaign_plan(
        artifacts["offload_opportunity_manifest.json"],
        artifacts["offload_bundle_search_space.json"],
        artifacts["offload_workload_variant_search_space.json"],
        max_attempts=4,
        include_hpsi=False,
    )

    selected_by_kernel = {
        row["kernel"]: row
        for row in plan["selected_opportunities"]
        if row["workload_case_id"] == "qe_si_nscf_bandgrid_v1"
    }
    assert {
        "diagonalization",
        "fft",
        "subspace_rotation",
    }.issubset(selected_by_kernel)
    for kernel in ("diagonalization", "fft", "subspace_rotation"):
        row = selected_by_kernel[kernel]
        assert (
            row["selected_workload_variant_id"]
            == NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID
        )
        assert row["selected_workload_variant_binding"]["target_kernels"] == [
            "diagonalization",
            "fft",
            "subspace_rotation",
        ]
        assert (
            row["selected_workload_variant_binding"]["workload_scale_policy"]
            == "stress_bandgrid"
        )


def test_materialized_diagonalization_patch_declares_l4_writeback_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"]
        == ["opp_qe_si_scf_small_v1_scf_diagonalization"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["accelerated_result_writeback_present"] is True
    assert caps["accelerated_consumption_marker_declared"] is True
    assert caps["kernel_work_replacement_marker_declared"] is True
    assert caps["accelerated_result_materialization_marker_declared"] is True
    assert caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert caps["accelerated_output_data_path_declared"] is True
    assert caps["trusted_l4_replacement_precheck_passed"] is False
    assert (
        caps["replacement_precheck_status"]
        == "blocked_replacement_evidence_incomplete"
    )
    assert (
        "accelerator_numeric_payload_marker_missing"
        in caps["value_gate_blockers"]
    )


def test_materialized_fft_patch_declares_strict_l4_zero_payload_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"] == ["opp_qe_si_scf_small_v1_scf_fft"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["generic_bridge_hook_present"] is True
    assert caps["runtime_replacement_evidence_hook_present"] is True
    assert caps["accelerated_result_writeback_present"] is True
    assert caps["accelerated_consumption_marker_declared"] is True
    assert caps["accelerated_output_data_path_declared"] is True
    assert caps["l4_execution_proof_declared"] is True
    assert caps["kernel_work_replacement_marker_declared"] is True
    assert caps["accelerated_result_materialization_marker_declared"] is True
    assert caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert caps["accelerator_numeric_payload_marker_declared"] is True
    assert caps["trusted_l4_replacement_precheck_passed"] is True
    assert caps["replacement_precheck_status"] == (
        "trusted_l4_replacement_candidate_precheck_only"
    )
    assert "FFTXlib/src/fft_fwinv.f90" in caps["source_targets"]
    assert caps["value_gate_blockers"] == []
    assert "accelerated_output_data_path_missing" not in caps["value_gate_blockers"]


def test_non_spsi_patch_precheck_accepts_fft_strict_zero_payload_candidate(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    replacement_report = artifacts["accelerated_replacement_readiness_report.json"]
    row = next(
        item
        for item in replacement_report["rows"]
        if item["opportunity_id"] == "opp_qe_si_nscf_bandgrid_v1_nscf_fft"
    )

    assert row["patch_accelerated_result_writeback_present"] is True
    assert row["patch_accelerated_output_data_path_declared"] is True
    assert row["patch_replacement_precheck_status"] == (
        "trusted_l4_replacement_candidate_precheck_only"
    )
    assert row["patch_trusted_l4_replacement_precheck_passed"] is True
    assert row["patch_value_gate_blockers"] == []
    assert row["ready_for_value_gate"] is False
    assert "real_l4_not_attempted" in row["replacement_blockers"]


def test_fft_runtime_output_path_list_removes_only_data_path_blocker():
    row = {
        "kernel": "fft",
        "evidence_kind": "real_qe_l4_attempt",
        "evidence_scope": "full_qe_actual_compute_blocked",
        "actual_compute_evidence": {
            "status": "blocked",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "blocked",
            "selected_kernel": "fft",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_output_data_path_present": True,
            "accelerated_output_data_paths": ["/tmp/qe_fft_accelerated_output.json"],
            "accelerated_result_materialized_in_qe_memory": False,
            "qe_software_kernel_execution_skipped": False,
            "qe_kernel_work_replaced_on_critical_path": False,
            "software_fallback_on_critical_path": True,
        },
        "speed_signal": {
            "status": "non_positive",
            "speedup_vs_pure_qe": 0.5,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert "accelerated_replacement_output_data_path_missing" not in verdict["blockers"]
    assert "accelerated_result_materialization_not_proven" in verdict["blockers"]
    assert "qe_software_kernel_execution_skip_not_proven" in verdict["blockers"]
    assert "qe_kernel_work_replacement_not_proven" in verdict["blockers"]
    assert "positive_speed_signal_missing" in verdict["blockers"]


def test_local_identity_writeback_without_numeric_payload_cannot_claim_l4_value():
    row = {
        "kernel": "s_psi",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "s_psi",
            "target_kernel": "s_psi",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "qe_software_kernel_execution_skipped": True,
            "software_kernel_execution_removed_from_critical_path": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_kernel_work_removed_from_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "source": "generic_accel_l4_spsi_identity_writeback",
                    "claim_boundary": (
                        "QE consumed GenericAccel-completed s_psi "
                        "identity-overlap writeback"
                    ),
                }
            ],
            "runtime_offload_provenance": {
                "offload_target": "generic_accel_l4_spsi",
                "claim_boundary": (
                    "GenericAccel L4 completed and QE consumed s_psi "
                    "identity-overlap writeback"
                ),
            },
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert (
        "accelerated_replacement_local_writeback_not_accelerator_numeric_output"
        in verdict["blockers"]
    )


def test_qe_memory_writeback_metadata_payload_cannot_claim_l4_value():
    row = {
        "kernel": "subspace_rotation",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "subspace_rotation",
            "target_kernel": "subspace_rotation",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_output_data_path_present": True,
            "accelerated_output_data_paths": ["/tmp/accelerated_output.json"],
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "qe_software_kernel_execution_skipped": True,
            "software_kernel_execution_removed_from_critical_path": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_kernel_work_removed_from_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.subspace_rotation.v1",
                "status": "passed",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": (
                    "L4 gated QE-memory replacement; QE correctness decides "
                    "validity"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "subspace_rotation",
                    "source": "generic_accel_l4_subspace_rotation_qe_memory_writeback",
                    "claim_boundary": (
                        "L4 completed; QE skipped local rotate_wfc software"
                    ),
                }
            ],
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert (
        "accelerated_replacement_local_writeback_not_accelerator_numeric_output"
        in verdict["blockers"]
    )


def test_genericaccel_completion_digest_is_not_kernel_numeric_payload():
    row = {
        "kernel": "diagonalization",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "diagonalization",
            "target_kernel": "diagonalization",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_output_data_path_present": True,
            "accelerated_output_data_paths": ["/tmp/accelerated_output.json"],
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "qe_software_kernel_execution_skipped": True,
            "software_kernel_execution_removed_from_critical_path": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_kernel_work_removed_from_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.genericaccel_bridge.v1",
                "target_kernel": "diagonalization",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_completion_result_json_digest"
                ),
                "payload_sha256": "abc123",
                "result_sha256": "abc123",
                "payload_bytes": 1024,
                "sample_values": [104, 1],
                "numeric_payload": {
                    "completion_cycles": 104,
                    "driver_iteration_count": 1,
                },
                "matrix_digest": "diagonalization_genericaccel_stdout_sha256:abc123",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": (
                    "GenericAccel completion metadata is visible to QE, but "
                    "does not contain diagonalization eigenvectors/eigenvalues"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "diagonalization",
                    "source": "generic_accel_l4_diagonalization_qe_memory_writeback",
                    "claim_boundary": (
                        "L4 completed; QE skipped local diagonalization software"
                    ),
                }
            ],
            "runtime_offload_provenance": {
                "offload_target": "generic_accel_l4_diagonalization",
                "claim_boundary": (
                    "L4 completed; QE skipped local diagonalization software"
                ),
            },
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert (
        "accelerated_replacement_local_writeback_not_accelerator_numeric_output"
        in verdict["blockers"]
    )


def test_synthetic_genericaccel_numeric_payload_cannot_claim_l4_value():
    row = {
        "kernel": "subspace_rotation",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "subspace_rotation",
            "target_kernel": "subspace_rotation",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_output_data_path_present": True,
            "accelerated_output_data_paths": ["/tmp/accelerated_output.json"],
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.genericaccel_bridge.v2",
                "target_kernel": "subspace_rotation",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload": {
                    "matrix_values": [[1.0, 0.0], [0.0, 1.0]],
                    "matrix_shape": [2, 2],
                    "replacement_policy": (
                        "genericaccel_identity_subspace_rotation_payload"
                    ),
                },
                "matrix_values": [[1.0, 0.0], [0.0, 1.0]],
                "replacement_policy": (
                    "genericaccel_identity_subspace_rotation_payload"
                ),
            }
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert (
        "accelerated_replacement_placeholder_numeric_payload:"
        "genericaccel_identity_subspace_rotation_payload"
        in verdict["blockers"]
    )


def test_identity_overlap_numeric_payload_cannot_claim_spsi_l4_value():
    row = {
        "kernel": "s_psi",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
            "qe_consumed_accelerated_outputs": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "s_psi",
            "target_kernel": "s_psi",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.genericaccel_bridge.v2",
                "target_kernel": "s_psi",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "output_values": [1.0, 0.0, 0.0, 0.0],
                "vector_values": [1.0, 0.0, 0.0, 0.0],
                "numeric_payload": {
                    "output_values": [1.0, 0.0, 0.0, 0.0],
                    "vector_values": [1.0, 0.0, 0.0, 0.0],
                    "replacement_policy": (
                        "genericaccel_identity_overlap_numeric_payload"
                    ),
                },
                "replacement_policy": "genericaccel_identity_overlap_numeric_payload",
            }
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.05,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] == "not_valuable_l4"
    assert (
        "accelerated_replacement_placeholder_numeric_payload:"
        "genericaccel_identity_overlap_numeric_payload"
        in verdict["blockers"]
    )


def test_runtime_summary_blocks_synthetic_placeholder_numeric_payload():
    summary = _runtime_bridge_replacement_summary(
        {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.genericaccel_bridge.v2",
                "target_kernel": "fft",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_placeholder_kernel_numeric_output_json"
                ),
                "placeholder_numeric_payload": True,
                "numeric_payload": {
                    "fft_values": [[0.0, 0.0]],
                    "replacement_policy": "genericaccel_fft_numeric_payload",
                },
                "fft_values": [[0.0, 0.0]],
                "replacement_policy": "genericaccel_fft_numeric_payload",
            },
            "runtime_offload_provenance": {
                "producer": "qe_fft_callsite_patch",
                "accelerated_runtime": "gem5_genericaccel_microarchitecture_v1",
                "offload_target": "generic_accel_l4_fft",
                "target_kernel": "fft",
                "accelerated_results_consumed_by_qe": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_output_data_path": "/tmp/accelerated_output.json",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "fft",
                    "kernel_scope": "full_fft",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_fft_numeric_output",
                }
            ],
        }
    )

    assert summary["status"] == "blocked"
    assert summary["accelerated_output_placeholder_payload_present"] is True
    assert summary["qe_kernel_work_replaced_on_critical_path"] is False
    assert (
        "runtime_accelerated_output_placeholder_numeric_payload:"
        "genericaccel_fft_numeric_payload"
        in summary["blockers"]
    )
    assert (
        "runtime_accelerated_output_placeholder_numeric_payload:"
        "genericaccel_placeholder_kernel_numeric_output_json"
        in summary["blockers"]
    )


def test_runtime_summary_blocks_identity_overlap_placeholder_payload():
    summary = _runtime_bridge_replacement_summary(
        {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.genericaccel_bridge.v2",
                "target_kernel": "s_psi",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "output_values": [1.0, 0.0, 0.0, 0.0],
                "vector_values": [1.0, 0.0, 0.0, 0.0],
                "replacement_policy": "genericaccel_identity_overlap_numeric_payload",
            },
            "runtime_offload_provenance": {
                "producer": "qe_spsi_callsite_patch",
                "accelerated_runtime": "gem5_genericaccel_microarchitecture_v1",
                "offload_target": "generic_accel_l4_s_psi",
                "target_kernel": "s_psi",
                "accelerated_results_consumed_by_qe": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "accelerated_results_consumed_by_qe": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "source": "generic_accel_l4_spsi_identity_overlap",
                }
            ],
        }
    )

    assert summary["status"] == "blocked"
    assert summary["accelerated_output_placeholder_payload_present"] is True
    assert summary["qe_kernel_work_replaced_on_critical_path"] is False
    assert (
        "runtime_accelerated_output_placeholder_numeric_payload:"
        "genericaccel_identity_overlap_numeric_payload"
        in summary["blockers"]
    )


def test_zero_force_writeback_metadata_payload_cannot_claim_l4_value():
    row = {
        "kernel": "forces",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "forces",
            "target_kernel": "forces",
            "accelerated_results_consumed_by_qe": True,
            "accelerated_output_data_path_present": True,
            "accelerated_output_data_paths": ["/tmp/accelerated_output.json"],
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "qe_software_kernel_execution_skipped": True,
            "software_kernel_execution_removed_from_critical_path": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_kernel_work_removed_from_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "patched_qe_bridge_evidence": {
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.forces.v1",
                "status": "passed",
                "target_kernel": "forces",
                "force_vector_policy": "zero_force_writeback",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": (
                    "L4 gated zero-force replacement; QE correctness decides "
                    "validity"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "forces",
                    "source": "generic_accel_l4_forces_zero_force_writeback",
                    "force_vector_policy": "zero_force_writeback",
                    "claim_boundary": (
                        "L4 gated zero-force replacement; QE skipped local "
                        "forces software"
                    ),
                }
            ],
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
        },
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert (
        "accelerated_replacement_local_writeback_not_accelerator_numeric_output"
        in verdict["blockers"]
    )


def test_band_projection_patch_is_bridge_only_without_runtime_replacement_hook(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"]
        == ["opp_qe_si_bands_path_v1_bands_band_path_projection"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["generic_bridge_hook_present"] is True
    assert caps["runtime_replacement_evidence_hook_present"] is False
    assert caps["accelerated_result_writeback_present"] is False
    assert caps["replacement_precheck_status"] == "blocked_bridge_or_trace_fallback_only"
    assert "runtime_replacement_evidence_hook_missing" in caps["value_gate_blockers"]
    assert "accelerated_result_writeback_missing" in caps["value_gate_blockers"]


def test_materialized_subspace_rotation_patch_declares_l4_writeback_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"]
        == ["opp_qe_si_nscf_bandgrid_v1_nscf_subspace_rotation"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["generic_bridge_hook_present"] is True
    assert caps["accelerated_result_writeback_present"] is True
    assert caps["accelerated_consumption_marker_declared"] is True
    assert caps["l4_execution_proof_declared"] is True
    assert caps["kernel_work_replacement_marker_declared"] is True
    assert caps["accelerated_result_materialization_marker_declared"] is True
    assert caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert caps["accelerated_output_data_path_declared"] is True
    assert caps["trusted_l4_replacement_precheck_passed"] is False
    assert (
        caps["replacement_precheck_status"]
        == "blocked_replacement_evidence_incomplete"
    )
    assert "PW/src/rotate_wfc.f90" in caps["source_targets"]
    assert (
        "accelerator_numeric_payload_marker_missing"
        in caps["value_gate_blockers"]
    )


def test_materialized_forces_patch_declares_l4_writeback_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"] == ["opp_qe_si_relax_forces_v1_relax_forces"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["generic_bridge_hook_present"] is True
    assert caps["accelerated_result_writeback_present"] is True
    assert caps["accelerated_consumption_marker_declared"] is True
    assert caps["l4_execution_proof_declared"] is True
    assert caps["kernel_work_replacement_marker_declared"] is True
    assert caps["accelerated_result_materialization_marker_declared"] is True
    assert caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert caps["accelerated_output_data_path_declared"] is True
    assert caps["trusted_l4_replacement_precheck_passed"] is False
    assert (
        caps["replacement_precheck_status"]
        == "blocked_replacement_evidence_incomplete"
    )
    assert "PW/src/forces.f90" in caps["source_targets"]
    assert (
        "accelerator_numeric_payload_marker_missing"
        in caps["value_gate_blockers"]
    )


def test_materialized_veff_patch_declares_l4_writeback_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]
    row = next(
        patch
        for patch in patches
        if patch["opportunity_ids"] == ["opp_qe_si_scf_small_v1_scf_veff"]
    )
    caps = row["instrumentation_capabilities"]

    assert row["status"] == "materialized_patch_available"
    assert caps["trace_hook_present"] is True
    assert caps["generic_bridge_hook_present"] is True
    assert caps["accelerated_result_writeback_present"] is True
    assert caps["accelerated_consumption_marker_declared"] is True
    assert caps["l4_execution_proof_declared"] is True
    assert caps["kernel_work_replacement_marker_declared"] is False
    assert caps["trusted_l4_replacement_precheck_passed"] is False
    assert (
        caps["replacement_precheck_status"]
        == "blocked_replacement_evidence_incomplete"
    )
    assert "PW/src/v_of_rho.f90" in caps["source_targets"]
    assert "kernel_work_replacement_marker_missing" in caps["value_gate_blockers"]


def test_materialized_density_patches_declare_l4_writeback_precheck(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    patches = artifacts["qe_callsite_patch_manifest.json"]["patch_rows"]

    for opportunity_id, source_target in [
        ("opp_qe_si_scf_small_v1_scf_rho_out", "PW/src/sum_band.f90"),
        ("opp_qe_si_scf_small_v1_scf_mix_rho", "PW/src/mix_rho.f90"),
    ]:
        row = next(
            patch
            for patch in patches
            if patch["opportunity_ids"] == [opportunity_id]
        )
        caps = row["instrumentation_capabilities"]

        assert row["status"] == "materialized_patch_available"
        assert caps["trace_hook_present"] is True
        assert caps["generic_bridge_hook_present"] is True
        assert caps["accelerated_result_writeback_present"] is True
        assert caps["accelerated_consumption_marker_declared"] is True
        assert caps["l4_execution_proof_declared"] is True
        assert caps["kernel_work_replacement_marker_declared"] is False
        assert caps["trusted_l4_replacement_precheck_passed"] is False
        assert (
            caps["replacement_precheck_status"]
            == "blocked_replacement_evidence_incomplete"
        )
        assert source_target in caps["source_targets"]
        assert "kernel_work_replacement_marker_missing" in caps["value_gate_blockers"]


def test_larger_spsi_workload_variant_binds_solver_and_scale_overrides():
    case = next(
        row
        for row in default_qe_mainflow_workload_suite(
            status="frozen", include_relax=True
        )["cases"]
        if row["case_id"] == "qe_si_nscf_bandgrid_v1"
    )
    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity={"kernel": "s_psi"},
        workload_variant_id=SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
    )

    assert bound_case["case_id"].endswith(SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID)
    assert profile["input_overrides"]["SYSTEM.ecutwfc"] == "20.0"
    nscf_step = next(
        step for step in bound_case["baseline_sequence"] if step["step_id"].endswith("nscf")
    )
    assert "diagonalization = 'cg'" in nscf_step["input"]
    assert "ecutwfc = 20.0" in nscf_step["input"]
    assert "nbnd = 24" in nscf_step["input"]
    assert "K_POINTS automatic\n6 6 6 0 0 0" in nscf_step["input"]


def test_nscf_amortized_workload_variant_binds_bandgrid_overrides():
    case = next(
        row
        for row in default_qe_mainflow_workload_suite(
            status="frozen", include_relax=True
        )["cases"]
        if row["case_id"] == "qe_si_nscf_bandgrid_v1"
    )
    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity={"kernel": "diagonalization"},
        workload_variant_id=NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    )

    assert bound_case["case_id"].endswith(
        NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID
    )
    assert (
        profile["workload_variant_binding"]["target_kernels"]
        == ["diagonalization", "fft", "subspace_rotation"]
    )
    assert profile["input_overrides"]["SYSTEM.ecutwfc"] == "20.0"
    assert profile["input_overrides"]["SYSTEM.nbnd"] == "48"
    assert (
        profile["input_overrides"]["stage_01_nscf.K_POINTS automatic"]
        == "8 8 8 0 0 0"
    )
    nscf_step = next(
        step
        for step in bound_case["baseline_sequence"]
        if step["step_id"].endswith("nscf")
    )
    assert "diagonalization = 'cg'" not in nscf_step["input"]
    assert "ecutwfc = 20.0" in nscf_step["input"]
    assert "nbnd = 48" in nscf_step["input"]
    assert "K_POINTS automatic\n8 8 8 0 0 0" in nscf_step["input"]


def test_nscf_heavy_workload_variant_binds_bandgrid_overrides():
    case = next(
        row
        for row in default_qe_mainflow_workload_suite(
            status="frozen", include_relax=True
        )["cases"]
        if row["case_id"] == "qe_si_nscf_bandgrid_v1"
    )
    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity={"kernel": "fft"},
        workload_variant_id=NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
    )

    assert bound_case["case_id"].endswith(NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID)
    assert (
        profile["workload_variant_binding"]["workload_scale_policy"]
        == "heavy_bandgrid"
    )
    assert profile["input_overrides"]["SYSTEM.ecutwfc"] == "20.0"
    assert profile["input_overrides"]["SYSTEM.nbnd"] == "64"
    assert (
        profile["input_overrides"]["stage_01_nscf.K_POINTS automatic"]
        == "10 10 10 0 0 0"
    )
    nscf_step = next(
        step
        for step in bound_case["baseline_sequence"]
        if step["step_id"].endswith("nscf")
    )
    assert "diagonalization = 'cg'" not in nscf_step["input"]
    assert "ecutwfc = 20.0" in nscf_step["input"]
    assert "nbnd = 64" in nscf_step["input"]
    assert "K_POINTS automatic\n10 10 10 0 0 0" in nscf_step["input"]


def test_nscf_ultra_workload_variant_binds_bandgrid_overrides():
    case = next(
        row
        for row in default_qe_mainflow_workload_suite(
            status="frozen", include_relax=True
        )["cases"]
        if row["case_id"] == "qe_si_nscf_bandgrid_v1"
    )
    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity={"kernel": "fft"},
        workload_variant_id=NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
    )

    assert bound_case["case_id"].endswith(NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID)
    assert (
        profile["workload_variant_binding"]["workload_scale_policy"]
        == "ultra_bandgrid"
    )
    assert profile["input_overrides"]["SYSTEM.ecutwfc"] == "20.0"
    assert profile["input_overrides"]["SYSTEM.nbnd"] == "96"
    assert (
        profile["input_overrides"]["stage_01_nscf.K_POINTS automatic"]
        == "12 12 12 0 0 0"
    )
    nscf_step = next(
        step
        for step in bound_case["baseline_sequence"]
        if step["step_id"].endswith("nscf")
    )
    assert "diagonalization = 'cg'" not in nscf_step["input"]
    assert "ecutwfc = 20.0" in nscf_step["input"]
    assert "nbnd = 96" in nscf_step["input"]
    assert "K_POINTS automatic\n12 12 12 0 0 0" in nscf_step["input"]


def test_nscf_stress_workload_variant_binds_bandgrid_overrides():
    case = next(
        row
        for row in default_qe_mainflow_workload_suite(
            status="frozen", include_relax=True
        )["cases"]
        if row["case_id"] == "qe_si_nscf_bandgrid_v1"
    )
    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity={"kernel": "fft"},
        workload_variant_id=NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
    )

    assert bound_case["case_id"].endswith(NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID)
    assert (
        profile["workload_variant_binding"]["workload_scale_policy"]
        == "stress_bandgrid"
    )
    assert profile["input_overrides"]["SYSTEM.ecutwfc"] == "20.0"
    assert profile["input_overrides"]["SYSTEM.nbnd"] == "128"
    assert (
        profile["input_overrides"]["stage_01_nscf.K_POINTS automatic"]
        == "14 14 14 0 0 0"
    )
    nscf_step = next(
        step
        for step in bound_case["baseline_sequence"]
        if step["step_id"].endswith("nscf")
    )
    assert "diagonalization = 'cg'" not in nscf_step["input"]
    assert "ecutwfc = 20.0" in nscf_step["input"]
    assert "nbnd = 128" in nscf_step["input"]
    assert "K_POINTS automatic\n14 14 14 0 0 0" in nscf_step["input"]


def test_smoke_cli_accepts_nscf_amortized_workload_variant(tmp_path):
    args = parse_smoke_args(
        [
            "--out",
            str(tmp_path / "attempt"),
            "--workload-variant-id",
            NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
        ]
    )

    assert args.workload_variant_id == NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID


def test_smoke_cli_accepts_nscf_heavy_workload_variant(tmp_path):
    args = parse_smoke_args(
        [
            "--out",
            str(tmp_path / "attempt"),
            "--workload-variant-id",
            NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
        ]
    )

    assert args.workload_variant_id == NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID


def test_smoke_cli_accepts_nscf_ultra_workload_variant(tmp_path):
    args = parse_smoke_args(
        [
            "--out",
            str(tmp_path / "attempt"),
            "--workload-variant-id",
            NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
        ]
    )

    assert args.workload_variant_id == NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID


def test_smoke_cli_accepts_nscf_stress_workload_variant(tmp_path):
    args = parse_smoke_args(
        [
            "--out",
            str(tmp_path / "attempt"),
            "--workload-variant-id",
            NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
        ]
    )

    assert args.workload_variant_id == NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID


def test_smoke_cli_accepts_prelaunch_driver_repeat_count(tmp_path):
    args = parse_smoke_args(
        [
            "--out",
            str(tmp_path / "attempt"),
            "--run-patched-qe-bridge",
            "--prelaunch-patched-qe-bridge",
            "--prelaunch-driver-repeat-count",
            "4",
        ]
    )

    assert args.prelaunch_driver_repeat_count == 4


def test_patched_bridge_stage_scope_distinguishes_scf_and_nscf_steps():
    nscf_opportunity = {"stage_type": "nscf"}
    scf_opportunity = {"stage_type": "scf"}

    assert _step_matches_opportunity_stage(
        {"step_id": "stage_01_nscf"},
        nscf_opportunity,
    )
    assert not _step_matches_opportunity_stage(
        {"step_id": "stage_00_scf_prerequisite"},
        nscf_opportunity,
    )
    assert _step_matches_opportunity_stage(
        {"step_id": "stage_00_scf_prerequisite"},
        scf_opportunity,
    )
    assert not _step_matches_opportunity_stage(
        {"step_id": "stage_01_nscf"},
        scf_opportunity,
    )


def test_replace_k_points_automatic_preserves_marker_and_replaces_grid():
    text = "K_POINTS automatic\n4 4 4 0 0 0\n"

    assert _replace_k_points_automatic(text, "6 6 6 0 0 0") == (
        "K_POINTS automatic\n6 6 6 0 0 0\n"
    )


def test_l4_campaign_dry_run_cli_writes_non_completion_plan(tmp_path):
    out_dir = tmp_path / "campaign"
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_callgraph_offload_l4_campaign.py",
            "--out",
            str(out_dir),
            "--source-root",
            str(tmp_path / "missing-qe-src"),
            "--max-attempts",
            "2",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    status = json.loads(completed.stdout)
    plan = json.loads((out_dir / "campaign_plan.json").read_text())
    assert status["status"] == "planned_only"
    assert status["deliverable_complete"] is False
    assert status["selected_non_hpsi_attempt_count"] == 2
    assert status["selected_hpsi_attempt_count"] == 0
    assert status["valuable_l4_count"] == 0
    assert plan["selected_attempt_count"] == 2
    assert plan["selected_non_hpsi_attempt_count"] == 2


def test_l4_smoke_cli_reuses_staged_artifact_root(tmp_path):
    artifact_dir = tmp_path / "staged_artifacts"
    write_qe_callgraph_offload_search_artifacts(
        artifact_dir, source_root=tmp_path / "missing-qe-src"
    )
    manifest_path = artifact_dir / "offload_opportunity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_hash"] = "sentinel_staged_manifest_hash"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    out_dir = tmp_path / "smoke"
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_callgraph_offload_l4_smoke.py",
            "--out",
            str(out_dir),
            "--source-root",
            str(tmp_path / "different-missing-qe-src"),
            "--artifact-root",
            str(artifact_dir),
            "--opportunity-id",
            "opp_qe_si_scf_small_v1_scf_mix_rho",
            "--baseline-policy",
            "preflight_only",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    status = json.loads(completed.stdout)
    copied_manifest = json.loads(
        (out_dir / "offload_opportunity_manifest.json").read_text(encoding="utf-8")
    )
    assert copied_manifest["manifest_hash"] == "sentinel_staged_manifest_hash"
    assert status["deliverable_complete"] is False
    assert status["selected_is_hpsi"] is False
    assert status["pure_qe_baseline_status"] == "blocked"


def test_campaign_smoke_command_passes_staged_artifact_root(tmp_path):
    args = argparse.Namespace(
        source_root=tmp_path / "qe-src",
        baseline_policy="real_if_ready",
        qe_baseline_timeout=120,
        gem5_transport_max_ticks=3000000000,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        qe_bin_dir=None,
        qe_pseudo_dir=None,
        trace_instrumented_qe=False,
        run_gem5_transport=False,
        run_patched_qe_bridge=False,
    )

    cmd = _smoke_command(
        args=args,
        smoke_runner=tmp_path / "run_qe_callgraph_offload_l4_smoke.py",
        artifact_root=tmp_path / "campaign",
        attempt_dir=tmp_path / "campaign" / "attempts" / "01",
        opportunity_id="opp_qe_si_scf_small_v1_scf_mix_rho",
    )

    assert "--artifact-root" in cmd
    assert cmd[cmd.index("--artifact-root") + 1] == str(tmp_path / "campaign")


def test_campaign_command_can_forward_actual_compute_and_batched_bridge(tmp_path):
    args = argparse.Namespace(
        source_root=tmp_path / "qe-src",
        baseline_policy="real_if_ready",
        qe_baseline_timeout=120,
        gem5_transport_max_ticks=3000000000,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        qe_bin_dir=None,
        qe_pseudo_dir=None,
        trace_instrumented_qe=True,
        run_gem5_transport=False,
        run_patched_qe_bridge=True,
        evidence_mode=EVIDENCE_MODE_ACTUAL_COMPUTE,
        batched_patched_qe_bridge=True,
        max_batched_bridge_trace_count=2048,
    )

    cmd = _smoke_command(
        args=args,
        smoke_runner=tmp_path / "run_qe_callgraph_offload_l4_smoke.py",
        artifact_root=tmp_path / "campaign",
        attempt_dir=tmp_path / "campaign" / "attempts" / "01",
        opportunity_id="opp_qe_si_scf_small_v1_scf_diagonalization",
    )

    assert "--evidence-mode" in cmd
    assert cmd[cmd.index("--evidence-mode") + 1] == EVIDENCE_MODE_ACTUAL_COMPUTE
    assert "--trace-instrumented-qe" in cmd
    assert "--run-patched-qe-bridge" in cmd
    assert "--batched-patched-qe-bridge" in cmd
    assert "--max-batched-bridge-trace-count" in cmd
    assert cmd[cmd.index("--max-batched-bridge-trace-count") + 1] == "2048"


def test_gem5_bridge_command_absolutizes_relative_driver_paths(tmp_path):
    repo_relative_driver = "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver_fast"
    command = _gem5_command(
        gem5_binary=tmp_path / "gem5.opt",
        m5out=tmp_path / "m5out",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=Path(repo_relative_driver),
        request_path=tmp_path / "simulation_request.json",
        simulator=tmp_path / "generic_sim",
        max_ticks=10,
    )

    driver_arg = command[command.index("--binary") + 1]
    assert driver_arg.endswith(repo_relative_driver)
    assert Path(driver_arg).is_absolute()


def test_prelaunched_bridge_script_reuses_existing_returncode(tmp_path):
    bridge_dir = tmp_path / "bridge"
    launched = tmp_path / "launched.txt"
    invocation_count = bridge_dir / "invocations.txt"
    launch_count = bridge_dir / "launches.txt"
    returncode = bridge_dir / "returncode.txt"
    bridge_dir.mkdir()
    invocation_count.write_text("1\n", encoding="utf-8")
    returncode.write_text("0\n", encoding="utf-8")

    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=["sh", "-c", f"echo launched >> {launched}"],
        stdout_path=bridge_dir / "stdout.txt",
        stderr_path=bridge_dir / "stderr.txt",
        returncode_path=returncode,
        invocation_count_path=invocation_count,
        gem5_launch_count_path=launch_count,
        reuse_prelaunched_result=True,
    )

    completed = subprocess.run([str(script)], check=False)

    assert completed.returncode == 0
    assert invocation_count.read_text(encoding="utf-8").strip() == "2"
    assert not launch_count.exists()
    assert not launched.exists()


def test_prelaunched_patched_bridge_supports_input_bound_fft_helper():
    assert _prelaunched_bridge_supported_kernel("fft") is True
    assert _prelaunched_bridge_supported_kernel("subspace_rotation") is True
    assert _prelaunched_bridge_supported_kernel("diagonalization") is False


def test_prelaunched_patched_bridge_blocks_unsupported_input_dependent_kernel(tmp_path):
    result = _run_patched_qe_bridge_probe(
        baseline={
            "status": "passed",
            "steps": [
                {
                    "step_id": "stage_00_scf",
                    "concrete_command": [sys.executable, "-c", "print('JOB DONE.')"],
                }
            ],
        },
        out_dir=tmp_path / "attempt",
        case_id="case",
        opportunity={
            "opportunity_id": "opp_diagonalization",
            "kernel": "diagonalization",
            "stage_type": "scf",
        },
        trace_evidence={"status": "passed", "trace_kernel_counts": {"diagonalization": 1}},
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=10,
        timeout=1,
        batched_bridge=True,
        prelaunch_bridge=True,
        evidence_mode=EVIDENCE_MODE_ACTUAL_COMPUTE,
    )

    assert result["status"] == "blocked"
    assert (
        "prelaunch_bridge_input_dependent_kernel_not_supported:diagonalization"
        in result["blockers"]
    )
    assert result["gem5_bridge_launch_count"] == 0


def test_l4_campaign_can_search_single_launch_and_batched_dispatch(tmp_path):
    args = argparse.Namespace(
        source_root=tmp_path / "qe-src",
        baseline_policy="real_if_ready",
        qe_baseline_timeout=120,
        gem5_transport_max_ticks=3000000000,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        qe_bin_dir=None,
        qe_pseudo_dir=None,
        trace_instrumented_qe=True,
        run_gem5_transport=False,
        run_patched_qe_bridge=True,
        evidence_mode=EVIDENCE_MODE_ACTUAL_COMPUTE,
        batched_patched_qe_bridge=True,
        max_batched_bridge_trace_count=2048,
        search_bridge_dispatch_policies=True,
    )

    candidates = _bridge_dispatch_policy_candidates(args)

    assert candidates == [("single_launch", False), ("trace_batched", True)]

    single_launch_cmd = _smoke_command(
        args=args,
        smoke_runner=tmp_path / "run_qe_callgraph_offload_l4_smoke.py",
        artifact_root=tmp_path / "campaign",
        attempt_dir=tmp_path / "campaign" / "attempts" / "01_single_launch",
        opportunity_id="opp_qe_si_nscf_bandgrid_v1_nscf_fft",
        batched_bridge_override=False,
    )
    trace_batched_cmd = _smoke_command(
        args=args,
        smoke_runner=tmp_path / "run_qe_callgraph_offload_l4_smoke.py",
        artifact_root=tmp_path / "campaign",
        attempt_dir=tmp_path / "campaign" / "attempts" / "01_trace_batched",
        opportunity_id="opp_qe_si_nscf_bandgrid_v1_nscf_fft",
        batched_bridge_override=True,
    )

    assert "--evidence-mode" in single_launch_cmd
    assert "--run-patched-qe-bridge" in single_launch_cmd
    assert "--batched-patched-qe-bridge" not in single_launch_cmd
    assert "--batched-patched-qe-bridge" in trace_batched_cmd
    assert "--max-batched-bridge-trace-count" in trace_batched_cmd
    assert trace_batched_cmd[
        trace_batched_cmd.index("--max-batched-bridge-trace-count") + 1
    ] == "2048"


def test_l4_campaign_artifact_root_preserves_optional_queue_artifacts(tmp_path):
    artifact_dir = tmp_path / "staged_artifacts"
    write_qe_callgraph_offload_search_artifacts(
        artifact_dir, source_root=tmp_path / "missing-qe-src"
    )
    queue_path = artifact_dir / "l4_offload_attempt_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["static_research_candidate_count"] = 12345
    queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

    out_dir = tmp_path / "campaign"
    subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_callgraph_offload_l4_campaign.py",
            "--out",
            str(out_dir),
            "--artifact-root",
            str(artifact_dir),
            "--max-attempts",
            "1",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    copied_queue = json.loads(
        (out_dir / "l4_offload_attempt_queue.json").read_text(encoding="utf-8")
    )
    assert copied_queue["static_research_candidate_count"] == 12345


def test_writer_and_cli_emit_required_machine_readable_artifacts(tmp_path):
    direct_out = tmp_path / "direct"
    status = write_qe_callgraph_offload_search_artifacts(
        direct_out, source_root=tmp_path / "missing-qe-src"
    )

    assert status["status"] == "partial_or_blocked"
    assert status["deliverable_complete"] is False
    for name in [
        "qe_callgraph_inventory.json",
        "offload_opportunity_manifest.json",
        "offload_workload_variant_search_space.json",
        "offload_target_identity_schema.json",
        "offload_bundle_search_space.json",
        "qe_callsite_patch_manifest.json",
        "l4_offload_attempt_queue.json",
        "offload_value_l4_evidence_matrix.json",
        "offload_value_report.json",
        "offload_value_report.md",
        "callgraph_offload_blocker_report.json",
        "callgraph_offload_blocker_report.md",
        "accelerated_replacement_readiness_report.json",
        "accelerated_replacement_readiness_report.md",
        "offload_selection_search_report.json",
        "offload_selection_search_report.md",
        "prompt_to_artifact_checklist.json",
        "prompt_to_artifact_checklist.md",
        "status.json",
    ]:
        assert (direct_out / name).exists()

    value_report = json.loads((direct_out / "offload_value_report.json").read_text())
    assert value_report["claims"]["deliverable_complete"] is False

    cli_out = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_qe_callgraph_offload_search_artifacts.py",
            "--out",
            str(cli_out),
            "--source-root",
            str(tmp_path / "missing-qe-src"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    cli_status = json.loads(result.stdout)
    assert cli_status["status"] == "partial_or_blocked"
    assert cli_status["deliverable_complete"] is False
    assert (cli_out / "l4_offload_attempt_queue.json").exists()


def test_l4_smoke_records_non_hpsi_blocker_without_value_claim(tmp_path):
    out_dir = tmp_path / "l4_smoke"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_callgraph_offload_l4_smoke.py",
            "--out",
            str(out_dir),
            "--source-root",
            str(tmp_path / "missing-qe-src"),
            "--baseline-policy",
            "preflight_only",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    status = json.loads(result.stdout)
    attempt = json.loads(
        (out_dir / "l4_offload_attempt_evidence.json").read_text()
    )
    matrix = json.loads(
        (out_dir / "offload_value_l4_evidence_matrix.json").read_text()
    )
    replacement_report = json.loads(
        (out_dir / "accelerated_replacement_readiness_report.json").read_text()
    )

    assert status["selected_is_hpsi"] is False
    assert status["valuable_l4"] is False
    assert status["valuable_l4_count"] == 0
    assert status["actual_compute_full_qe_evidence_required"] is True
    assert status["actual_compute_full_qe_evidence_blocked_count"] == 1
    assert status["smoke_dataflow_only_value_blocked_count"] == 1
    assert status["smoke_value_allowed"] is False
    assert status["replacement_ready_count"] == 0
    assert (
        status["target_kernel_mismatch_count"]
        == replacement_report["target_kernel_mismatch_count"]
    )
    assert status["deliverable_complete"] is False
    assert attempt["attempt_status"] == "blocked"
    assert attempt["evidence_kind"] == "real_qe_l4_dataflow_smoke"
    assert attempt["evidence_scope"] == "dataflow_smoke_only"
    assert attempt["actual_compute_evidence"]["status"] == "blocked"
    assert attempt["actual_compute_evidence"]["smoke_only"] is True
    assert "qe_source_patch_not_applied_to_build" in attempt["blockers"]
    assert attempt["value_verdict"]["valuable_l4"] is False
    assert (
        "smoke_dataflow_only_not_actual_compute"
        in attempt["value_verdict"]["blockers"]
    )
    assert (
        "actual_compute_full_qe_evidence_not_passed"
        in attempt["value_verdict"]["blockers"]
    )
    assert "actual_compute_marked_smoke_only" in attempt["value_verdict"]["blockers"]
    assert matrix["actual_compute_full_qe_evidence_required"] is True
    assert matrix["actual_compute_full_qe_evidence_blocked_count"] == 1
    assert matrix["smoke_dataflow_only_value_blocked_count"] == 1
    assert matrix["smoke_value_allowed"] is False
    assert matrix["valuable_l4_count"] == 0
    assert matrix["value_counts"]["blocked"] == 1
    assert replacement_report["replacement_ready_count"] == 0


def test_qe_offload_identity_extension_stays_out_of_generic_core_layers():
    assert OFFLOAD_TARGET_LAYER not in IDENTITY_LAYER_KEYS


def test_static_callgraph_keeps_fortran_unit_open_across_end_if(tmp_path):
    src = tmp_path / "PW" / "src"
    src.mkdir(parents=True)
    (src / "foo.f90").write_text(
        """
        subroutine foo()
          if (.true.) then
             call bar()
          end if
          call baz()
        end subroutine foo

        subroutine bar()
        end subroutine bar

        subroutine baz()
        end subroutine baz

        subroutine h_psi_probe()
          call vloc_psi()
        end subroutine h_psi_probe
        """,
        encoding="utf-8",
    )

    callgraph = _extract_static_callgraph(tmp_path)
    edges = {
        (row["caller"], row["callee"])
        for row in callgraph["edges_sample"]
    }

    assert callgraph["status"] == "passed"
    assert ("foo", "bar") in edges
    assert ("foo", "baz") in edges
    assert callgraph["offload_candidate_count"] >= 1
    assert callgraph["offload_candidate_kernel_counts"]["h_psi"] >= 1


def test_static_callgraph_uses_c_comment_and_function_parsing(tmp_path):
    src = tmp_path / "UtilXlib"
    src.mkdir()
    (src / "kernel.c").write_text(
        """
        /* The words function but returns are comments, not program units. */
        static int helper(int x) { return x; }
        int driver(void) { return helper(1); }
        """,
        encoding="utf-8",
    )

    callgraph = _extract_static_callgraph(tmp_path)
    definitions = {
        row["symbol"]: row["kind"] for row in callgraph["definitions_sample"]
    }
    edges = {
        (row["caller"], row["callee"])
        for row in callgraph["edges_sample"]
    }

    assert definitions["helper"] == "c_function"
    assert definitions["driver"] == "c_function"
    assert ("driver", "helper") in edges
    assert not any(
        str(blocker).startswith("unterminated_unit_probe")
        for blocker in callgraph["blockers"]
    )


def test_static_research_candidates_flow_into_queue_and_selection_report(tmp_path):
    src = tmp_path / "qe-src" / "PW" / "src"
    src.mkdir(parents=True)
    (src / "h_psi_probe.f90").write_text(
        """
        subroutine h_psi_probe()
          call vloc_psi()
        end subroutine h_psi_probe
        """,
        encoding="utf-8",
    )

    artifacts = offload_artifact_bundle(source_root=tmp_path / "qe-src")
    inventory = artifacts["qe_callgraph_inventory.json"]
    queue = artifacts["l4_offload_attempt_queue.json"]
    selection = artifacts["offload_selection_search_report.json"]

    assert inventory["static_offload_candidate_count"] >= 1
    assert inventory["static_offload_candidate_kernel_counts"]["h_psi"] >= 1
    assert queue["static_research_candidate_count"] >= 1
    assert queue["static_research_candidates_sample"]
    assert (
        queue["static_research_candidates_sample"][0]["attempt_status"]
        == "blocked_until_workload_stage_callsite_binding"
    )
    assert selection["static_research_candidate_count"] >= 1
    assert selection["static_research_candidates_sample"]
    assert selection["deliverable_complete"] is False


def test_transport_smoke_requires_trace_for_selected_kernel():
    trace = {
        "trace_kernel_counts": _trace_kernel_counts(
            [
                "QE_OFFLOAD_CALLSITE diagonalization 1 1",
                "QE_OFFLOAD_CALLSITE diagonalization 1 2",
            ]
        )
    }

    assert _trace_contains_kernel(trace, "diagonalization") is True
    assert _trace_contains_kernel(trace, "h_psi") is False
    assert _trace_observed_kernel_count(trace, "diagonalization") == 2


def test_patched_qe_speed_measurement_disables_trace_file_io(tmp_path, monkeypatch):
    """Patched-QE timing must not include per-call trace instrumentation I/O."""

    baseline_metrics = {
        "job_done": True,
        "band_energy_count": 2,
        "band_energy_min_ev": -1.0,
        "band_energy_max_ev": 1.0,
        "band_energy_sum_ev": 0.0,
        "fermi_energy_ev": 0.5,
    }
    baseline = {
        "status": "passed",
        "elapsed_seconds": 1.0,
        "performance_metrics": {"terminal_step_metrics": baseline_metrics},
        "steps": [
            {
                "step_id": "stage_00",
                "concrete_command": ["fake-pw.x", "-in", "si.in"],
                "metrics": baseline_metrics,
            }
        ],
    }
    opportunity = {
        "opportunity_id": "opp_spsi",
        "workload_case_id": "qe_case",
        "kernel": "s_psi",
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {"s_psi": 1},
        "trace_line_count": 1,
    }
    observed_envs: list[dict[str, str]] = []

    def fake_run(command, *, cwd, capture_output, text, timeout, env):
        observed_envs.append(dict(env))
        bridge_dir = tmp_path / "out" / "qe_patched_bridge"
        (bridge_dir / "gem5_bridge_returncode.txt").write_text(
            "0\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_stdout.txt").write_text(
            'generic_accel_l4_status=1 error_code=0\n{"status":"passed"}\n',
            encoding="utf-8",
        )
        (bridge_dir / "runtime_kernel_evidence.json").write_text(
            json.dumps(
                [
                    {
                        "kernel_id": "s_psi",
                        "accelerated_results_consumed_by_qe": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (bridge_dir / "runtime_offload_provenance.json").write_text(
            json.dumps(
                {
                    "target_kernel": "s_psi",
                    "accelerated_results_consumed_by_qe": True,
                    "l4_execution_proof": {"passed": True},
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="fake", stderr="")

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._parse_qe_stdout",
        lambda _stdout: dict(baseline_metrics),
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._gem5_marker_summary",
        lambda _log, _stdout, **_kwargs: {
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "driver_status_observed": True,
            "driver_iteration_count": 1,
            "completion_writeback_count": 1,
            "expected_driver_iterations": 1,
            "driver_repeat_completed": True,
            "result_prefix_passed": True,
        },
    )

    result = _run_patched_qe_bridge_probe(
        baseline=baseline,
        out_dir=tmp_path / "out",
        case_id="qe_case",
        opportunity=opportunity,
        trace_evidence=trace_evidence,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=1,
        timeout=10,
    )

    assert observed_envs
    assert all("QE_OFFLOAD_TRACE_FILE" not in env for env in observed_envs)
    assert all("QE_OFFLOAD_ACCELERATED_OUTPUT_JSON" in env for env in observed_envs)
    assert all("QE_OFFLOAD_BUNDLE_RUNTIME_MANIFEST" in env for env in observed_envs)
    assert all("QE_OFFLOAD_BUNDLE_TARGETS" in env for env in observed_envs)
    assert all(
        env["QE_OFFLOAD_BUNDLE_TARGETS"] == "opp_spsi:s_psi"
        for env in observed_envs
    )
    assert all("QE_OFFLOAD_BRIDGE_COMMAND_S_PSI" in env for env in observed_envs)
    assert all(
        "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON_S_PSI" in env
        for env in observed_envs
    )
    assert result["accelerated_output_json_path"].endswith("accelerated_output.json")
    assert result["accelerated_output_json_exists"] is False
    assert result["bundle_runtime_manifest_exists"] is True
    assert (
        result["bundle_runtime_contract"]["manifest"][
            "single_qe_workflow_multi_callsite_bundle"
        ]
        is False
    )
    assert result["bundle_runtime_contract"]["manifest"]["target_count"] == 1
    assert result["patched_trace_enabled"] is False
    assert (
        result["speed_measurement_policy"]["patched_qe_trace_file_io"]
        == "disabled_for_speed_measurement"
    )
    assert (
        result["speed_measurement_policy"][
            "gem5_bridge_invocation_count_on_qe_critical_path"
        ]
        == 1
    )
    assert (
        result["speed_measurement_policy"][
            "gem5_bridge_launch_count_on_qe_critical_path"
        ]
        == 1
    )
    assert result["dispatch_policy"]["policy"] == "execute_command_line_shell_bridge"
    assert (
        result["dispatch_policy"][
            "persistent_or_batched_dispatch_observed"
        ]
        is False
    )
    assert result["status"] == "passed"


def test_patched_qe_bridge_can_use_local_runtime_workspace(
    tmp_path,
    monkeypatch,
):
    """Bridge buffers may live on local storage while artifacts stay replayable."""

    baseline_metrics = {
        "job_done": True,
        "band_energy_count": 2,
        "band_energy_min_ev": -1.0,
        "band_energy_max_ev": 1.0,
        "band_energy_sum_ev": 0.0,
        "fermi_energy_ev": 0.5,
    }
    baseline = {
        "status": "passed",
        "elapsed_seconds": 1.0,
        "performance_metrics": {"terminal_step_metrics": baseline_metrics},
        "steps": [
            {
                "step_id": "stage_00",
                "concrete_command": ["fake-pw.x", "-in", "si.in"],
                "metrics": baseline_metrics,
            }
        ],
    }
    opportunity = {
        "opportunity_id": "opp_spsi",
        "workload_case_id": "qe_case",
        "kernel": "s_psi",
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {"s_psi": 1},
        "trace_line_count": 1,
    }
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("DSE_QE_L4_BRIDGE_RUNTIME_TMPDIR", str(runtime_root))
    observed_bridge_dirs: list[Path] = []

    def fake_run(command, *, cwd, capture_output, text, timeout, env):
        bridge_dir = Path(env["QE_OFFLOAD_KERNEL_EVIDENCE_JSON"]).parent
        observed_bridge_dirs.append(bridge_dir)
        assert str(bridge_dir.resolve()).startswith(str(runtime_root))
        (bridge_dir / "gem5_bridge_returncode.txt").write_text(
            "0\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_stdout.txt").write_text(
            'generic_accel_l4_status=1 error_code=0\n{"status":"passed"}\n',
            encoding="utf-8",
        )
        (bridge_dir / "runtime_kernel_evidence.json").write_text(
            json.dumps(
                [
                    {
                        "kernel_id": "s_psi",
                        "accelerated_results_consumed_by_qe": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (bridge_dir / "runtime_offload_provenance.json").write_text(
            json.dumps(
                {
                    "target_kernel": "s_psi",
                    "accelerated_results_consumed_by_qe": True,
                    "l4_execution_proof": {"passed": True},
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="fake", stderr="")

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._parse_qe_stdout",
        lambda _stdout: dict(baseline_metrics),
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._gem5_marker_summary",
        lambda _log, _stdout, **_kwargs: {
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "driver_status_observed": True,
            "driver_iteration_count": 1,
            "completion_writeback_count": 1,
            "expected_driver_iterations": 1,
            "driver_repeat_completed": True,
            "result_prefix_passed": True,
        },
    )

    result = _run_patched_qe_bridge_probe(
        baseline=baseline,
        out_dir=tmp_path / "out",
        case_id="qe_case",
        opportunity=opportunity,
        trace_evidence=trace_evidence,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=1,
        timeout=10,
    )

    artifact_bridge_dir = tmp_path / "out" / "qe_patched_bridge"
    assert len(observed_bridge_dirs) == 1
    assert str(observed_bridge_dirs[0]).startswith(str(runtime_root))
    assert artifact_bridge_dir.exists()
    assert not artifact_bridge_dir.is_symlink()
    assert (artifact_bridge_dir / "gem5_bridge_returncode.txt").exists()
    assert (
        artifact_bridge_dir / "patched_qe_bridge_evidence.json"
    ).exists()
    workspace = result["runtime_bridge_workspace"]
    assert workspace["runtime_storage_policy"] == "symlink_to_local_tmp"
    assert workspace["post_timing_materialized"] is True
    assert str(workspace["timed_runtime_bridge_dir"]).startswith(str(runtime_root))
    assert result["status"] == "passed"


def test_batched_qe_bridge_uses_trace_call_count_for_single_step_hot_kernel(
    tmp_path,
    monkeypatch,
):
    baseline_metrics = {
        "job_done": True,
        "band_energy_count": 2,
        "band_energy_min_ev": -1.0,
        "band_energy_max_ev": 1.0,
        "band_energy_sum_ev": 0.0,
        "fermi_energy_ev": 0.5,
    }
    baseline = {
        "status": "passed",
        "elapsed_seconds": 1.0,
        "performance_metrics": {"terminal_step_metrics": baseline_metrics},
        "steps": [
            {
                "step_id": "stage_00",
                "concrete_command": ["fake-pw.x", "-in", "si.in"],
                "metrics": baseline_metrics,
            }
        ],
    }
    opportunity = {
        "opportunity_id": "opp_fft",
        "workload_case_id": "qe_case",
        "kernel": "fft",
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {"fft": 3},
        "trace_line_count": 3,
    }
    observed_expected_driver_iterations: list[int] = []

    def fake_run(command, *, cwd, capture_output, text, timeout, env):
        bridge_dir = tmp_path / "out" / "qe_patched_bridge"
        (bridge_dir / "gem5_bridge_returncode.txt").write_text(
            "0\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_invocation_count.txt").write_text(
            "3\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_launch_count.txt").write_text(
            "1\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_stdout.txt").write_text(
            'generic_accel_l4_status=1 error_code=0\n{"status":"passed"}\n',
            encoding="utf-8",
        )
        (bridge_dir / "runtime_kernel_evidence.json").write_text(
            json.dumps(
                [
                    {
                        "kernel_id": "fft",
                        "full_kernel_recomputed": True,
                        "accelerated_results_consumed_by_qe": True,
                        "absolute_error": 0.0,
                        "relative_error": 0.0,
                        "source": "generic_accel_l4_fft_kernel",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (bridge_dir / "runtime_offload_provenance.json").write_text(
            json.dumps(
                {
                    "producer": "qe_fft_callsite_patch",
                    "accelerated_runtime": "qe_offload_runtime",
                    "offload_target": "generic_accel_l4_fft",
                    "target_kernel": "fft",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "l4_execution_proof": {
                        "passed": True,
                        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="fake", stderr="")

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._parse_qe_stdout",
        lambda _stdout: dict(baseline_metrics),
    )

    def fake_marker_summary(_log, _stdout, **kwargs):
        expected = int(kwargs["expected_driver_iterations"])
        observed_expected_driver_iterations.append(expected)
        return {
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "driver_status_observed": True,
            "driver_iteration_count": expected,
            "completion_writeback_count": expected,
            "expected_driver_iterations": expected,
            "driver_repeat_completed": True,
            "result_prefix_passed": True,
        }

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._gem5_marker_summary",
        fake_marker_summary,
    )

    result = _run_patched_qe_bridge_probe(
        baseline=baseline,
        out_dir=tmp_path / "out",
        case_id="qe_case",
        opportunity=opportunity,
        trace_evidence=trace_evidence,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=1,
        timeout=10,
        batched_bridge=True,
    )

    assert observed_expected_driver_iterations == [3]
    assert result["dispatch_policy"]["batched_request_count_per_launch"] == 3
    assert (
        result["dispatch_policy"]["gem5_bridge_invocation_count_on_qe_critical_path"]
        == 3
    )
    assert result["dispatch_policy"]["gem5_bridge_launch_count_on_qe_critical_path"] == 1
    assert result["dispatch_policy"]["persistent_or_batched_dispatch_observed"] is True
    assert result["status"] == "passed"


def test_batched_subspace_bridge_uses_single_selected_callsite_batch(
    tmp_path,
    monkeypatch,
):
    baseline_metrics = {
        "job_done": True,
        "band_energy_count": 2,
        "band_energy_min_ev": -1.0,
        "band_energy_max_ev": 1.0,
        "band_energy_sum_ev": 0.0,
        "fermi_energy_ev": 0.5,
    }
    baseline = {
        "status": "passed",
        "elapsed_seconds": 1.0,
        "performance_metrics": {"terminal_step_metrics": baseline_metrics},
        "steps": [
            {
                "step_id": "stage_00",
                "concrete_command": ["fake-pw.x", "-in", "si.in"],
                "metrics": baseline_metrics,
            }
        ],
    }
    opportunity = {
        "opportunity_id": "opp_subspace",
        "workload_case_id": "qe_case",
        "kernel": "subspace_rotation",
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {"subspace_rotation": 32},
        "trace_line_count": 32,
    }
    observed_expected_driver_iterations: list[int] = []

    def fake_run(command, *, cwd, capture_output, text, timeout, env):
        bridge_dir = tmp_path / "out" / "qe_patched_bridge"
        (bridge_dir / "gem5_bridge_returncode.txt").write_text(
            "0\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_invocation_count.txt").write_text(
            "1\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_launch_count.txt").write_text(
            "1\n", encoding="utf-8"
        )
        (bridge_dir / "gem5_bridge_stdout.txt").write_text(
            'generic_accel_l4_status=1 error_code=0\n{"status":"passed"}\n',
            encoding="utf-8",
        )
        (bridge_dir / "runtime_kernel_evidence.json").write_text(
            json.dumps(
                [
                    {
                        "kernel_id": "subspace_rotation",
                        "kernel_scope": "full_subspace_rotation",
                        "full_kernel_recomputed": True,
                        "accelerated_results_consumed_by_qe": True,
                        "absolute_error": 0.0,
                        "relative_error": 0.0,
                        "source": (
                            "generic_accel_l4_subspace_rotation_"
                            "qe_memory_writeback"
                        ),
                    }
                ]
            ),
            encoding="utf-8",
        )
        (bridge_dir / "runtime_offload_provenance.json").write_text(
            json.dumps(
                {
                    "producer": "qe_subspace_rotation_callsite_patch",
                    "accelerated_runtime": "qe_offload_runtime",
                    "offload_target": "generic_accel_l4_subspace_rotation",
                    "target_kernel": "subspace_rotation",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "software_fallback_on_critical_path": False,
                    "l4_execution_proof": {
                        "passed": True,
                        "transport_harness": (
                            "gem5_generic_accel_microarchitecture_v1"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="fake", stderr="")

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._parse_qe_stdout",
        lambda _stdout: dict(baseline_metrics),
    )

    def fake_marker_summary(_log, _stdout, **kwargs):
        expected = int(kwargs["expected_driver_iterations"])
        observed_expected_driver_iterations.append(expected)
        return {
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "driver_status_observed": True,
            "driver_iteration_count": expected,
            "completion_writeback_count": expected,
            "expected_driver_iterations": expected,
            "driver_repeat_completed": True,
            "result_prefix_passed": True,
        }

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke._gem5_marker_summary",
        fake_marker_summary,
    )

    result = _run_patched_qe_bridge_probe(
        baseline=baseline,
        out_dir=tmp_path / "out",
        case_id="qe_case",
        opportunity=opportunity,
        trace_evidence=trace_evidence,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=1,
        timeout=10,
        batched_bridge=True,
        max_batched_trace_count=4,
    )

    assert observed_expected_driver_iterations == [1]
    assert result["selected_trace_count"] == 32
    assert result["dispatch_policy"]["batched_request_count_per_launch"] == 1
    assert (
        result["dispatch_policy"]["gem5_bridge_invocation_count_on_qe_critical_path"]
        == 1
    )
    assert result["dispatch_policy"]["gem5_bridge_launch_count_on_qe_critical_path"] == 1
    assert (
        result["dispatch_policy"]["persistent_or_batched_dispatch_observed"] is False
    )
    assert result["status"] == "passed"


def test_gem5_transport_request_sizes_one_selected_call_not_whole_hot_trace(tmp_path):
    trace_evidence = {
        "status": "passed",
        "trace_line_count": 48986,
        "trace_kernel_counts": {"s_psi": 39060, "h_psi": 9813},
        "trace_lines_sample": [
            "QE_OFFLOAD_CALLSITE fft Rho 1",
            "QE_OFFLOAD_CALLSITE s_psi 412 411 1",
            "QE_OFFLOAD_CALLSITE h_psi 412 411 1 4",
        ],
    }
    opportunity = {
        "opportunity_id": "opp_qe_si_nscf_bandgrid_v1_nscf_s_psi",
        "workload_case_id": "qe_si_nscf_bandgrid_v1",
        "kernel": "s_psi",
    }

    request_path = _build_transport_request(
        out_dir=tmp_path / "bridge",
        trace_evidence=trace_evidence,
        opportunity=opportunity,
    )
    request = json.loads(request_path.read_text())
    node = request["workload"]["nodes"]["selected_callsite"]

    assert request["run_id"] == "qe_s_psi_callsite_transport"
    assert request["mapping"] == {"selected_callsite": "generic_accel_0"}
    assert node["op_type"] == "s_psi"
    assert node["trace_line_count"] == 1
    assert node["selected_trace_count"] == 39060
    assert node["total_trace_line_count"] == 48986
    assert node["selected_trace_line"] == "QE_OFFLOAD_CALLSITE s_psi 412 411 1"
    assert node["numeric_shape_tokens"] == [412.0, 411.0, 1.0]
    assert node["estimated_flops"] < 48986 * 8 * 8 * 8
    assert "single_selected_callsite_invocation" in node["sizing_policy"]


def test_batched_qe_bridge_blocks_pathological_hot_trace_before_gem5(tmp_path, monkeypatch):
    baseline = {
        "status": "passed",
        "elapsed_seconds": 1.0,
        "steps": [
            {
                "step_id": "stage_00",
                "concrete_command": ["fake-pw.x", "-in", "si.in"],
                "metrics": {"job_done": True, "total_energy_ry": -1.0},
            }
        ],
    }
    opportunity = {
        "opportunity_id": "opp_spsi_hot",
        "workload_case_id": "qe_case",
        "kernel": "s_psi",
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {"s_psi": 2048},
        "trace_line_count": 2048,
    }

    def fail_if_run(*_args, **_kwargs):
        raise AssertionError("pathological trace cap should block before subprocess.run")

    monkeypatch.setattr(
        "dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke.subprocess.run",
        fail_if_run,
    )

    result = _run_patched_qe_bridge_probe(
        baseline=baseline,
        out_dir=tmp_path / "out",
        case_id="qe_case",
        opportunity=opportunity,
        trace_evidence=trace_evidence,
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        max_ticks=1,
        timeout=10,
        batched_bridge=True,
        max_batched_trace_count=1024,
    )

    assert result["status"] == "blocked"
    assert result["selected_trace_count"] == 2048
    assert result["max_batched_trace_count"] == 1024
    assert result["gem5_bridge_launch_count"] == 0
    assert result["dispatch_policy"]["persistent_or_batched_dispatch_observed"] is False
    assert result["speed_signal"]["status"] == "blocked"
    assert "batched_bridge_trace_count_exceeds_limit" in result["speed_signal"]["blockers"]
    assert (
        tmp_path / "out" / "qe_patched_bridge" / "patched_qe_bridge_evidence.json"
    ).exists()


def test_bridge_command_script_records_real_invocation_count(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            "print('generic_accel_l4_status=1 error_code=0')",
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
    )

    subprocess.run([str(script)], check=True)
    subprocess.run([str(script)], check=True)

    assert invocation_count_path.read_text(encoding="utf-8").strip() == "2"
    assert gem5_launch_count_path.read_text(encoding="utf-8").strip() == "2"
    assert returncode_path.read_text(encoding="utf-8").strip() == "0"
    assert "generic_accel_l4_status=1" in stdout_path.read_text(
        encoding="utf-8"
    )


def test_bridge_command_script_materializes_genericaccel_numeric_payload(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=123 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\", "
                "\"metrics\": {\"latency_ms\": 0.001}}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="forces",
    )

    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert payload["producer"] == "gem5_genericaccel_l4_bridge"
    assert payload["target_kernel"] == "forces"
    assert payload["payload_sha256"]
    assert payload["result_sha256"]
    assert payload["payload_bytes"] > 0
    assert payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_placeholder_kernel_numeric_output_json"
    )
    assert payload["placeholder_numeric_payload"] is True
    assert payload["numeric_output_source"] == (
        "genericaccel_l4_placeholder_from_request_metadata"
    )
    assert payload["completion_metadata"]["completion_cycles"] == 123
    assert payload["completion_metadata"]["driver_iteration_count"] == 1
    assert payload["numeric_payload"]["completion_cycles"] == 123
    assert payload["numeric_payload"]["driver_iteration_count"] == 1
    assert payload["output_values"] == [[0.0, 0.0, 0.0]]
    assert payload["force_values"] == [[0.0, 0.0, 0.0]]
    assert payload["output_buffer_bytes"] > 0
    assert payload["output_buffer_sha256"]
    assert payload["force_vector_policy"] == "genericaccel_zero_force_numeric_payload"
    assert payload["placeholder_numeric_payload_policies"] == [
        "genericaccel_zero_force_numeric_payload"
    ]


def test_bridge_command_script_materializes_kernel_specific_strong_payloads(tmp_path):
    for target, expected_key in (
        ("s_psi", "vector_values"),
        ("subspace_rotation", "matrix_values"),
        ("diagonalization", "eigenvalues"),
        ("fft", "fft_values"),
    ):
        bridge_dir = tmp_path / target
        stdout_path = bridge_dir / "stdout.log"
        stderr_path = bridge_dir / "stderr.log"
        returncode_path = bridge_dir / "returncode.txt"
        invocation_count_path = bridge_dir / "invocation_count.txt"
        gem5_launch_count_path = bridge_dir / "launch_count.txt"
        accelerated_output = bridge_dir / "accelerated_output.json"
        request_path = bridge_dir / "simulation_request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(
                {
                    "workload": {
                        "nodes": {
                            "selected_callsite": {
                                "op_type": target,
                                "numeric_shape_tokens": [4, 4, 4],
                                "estimated_flops": 128.0,
                                "estimated_memory_bytes": 256.0,
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        script = _write_bridge_command_script(
            bridge_dir=bridge_dir,
            command=[
                sys.executable,
                "-c",
                (
                    "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                    "print('completion_magic=0x4753494d completion_status=0 "
                    "cycles=77 result_addr=0x0000000009200000'); "
                    "print('result_prefix={\"status\": \"passed\"}')"
                ),
            ],
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            returncode_path=returncode_path,
            invocation_count_path=invocation_count_path,
            gem5_launch_count_path=gem5_launch_count_path,
            accelerated_output_json_path=accelerated_output,
            target_kernel=target,
            request_path=request_path,
        )

        subprocess.run([str(script)], check=True)
        payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

        assert payload["accelerator_numeric_payload_kind"] == (
            "genericaccel_placeholder_kernel_numeric_output_json"
        )
        assert payload[expected_key]
        assert payload["numeric_payload"][expected_key]
        assert payload["output_buffer_bytes"] > 0
        assert payload["output_buffer_sha256"]
        assert payload["placeholder_numeric_payload"] is True
        assert payload["numeric_output_source"] == (
            "genericaccel_l4_placeholder_from_request_metadata"
        )
        if target == "s_psi":
            assert payload["placeholder_numeric_payload_policies"] == [
                "genericaccel_identity_overlap_numeric_payload"
            ]


def test_bridge_command_script_computes_fft_payload_from_qe_input_buffer(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input = bridge_dir / "accelerated_input.json"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "fft",
                            "numeric_shape_tokens": [2, 1, 1],
                            "estimated_flops": 16.0,
                            "estimated_memory_bytes": 32.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "values": [[1.0, 0.0], [0.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="fft",
        request_path=request_path,
        accelerated_input_json_path=accelerated_input,
        accelerated_output_data_path=accelerated_output_data,
    )

    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_json"
    )
    assert payload["placeholder_numeric_payload"] is False
    assert payload["replacement_policy"] == "genericaccel_cooley_tukey_fft_payload"
    assert payload["numeric_compute_backend"] == "numpy_fft"
    assert payload["qe_input_buffer_sha256"]
    assert payload["output_buffer_path"] == str(accelerated_output_data)
    assert accelerated_output_data.exists()
    assert payload["fft_values"] == [[1.0, 0.0], [1.0, 0.0]]


def test_bridge_command_script_matches_qe_forward_fft_scaling(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input = bridge_dir / "accelerated_input.json"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "fft",
                            "numeric_shape_tokens": [2, 1, 1],
                            "estimated_flops": 16.0,
                            "estimated_memory_bytes": 32.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "forward",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "values": [[1.0, 0.0], [0.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="fft",
        request_path=request_path,
        accelerated_input_json_path=accelerated_input,
        accelerated_output_data_path=accelerated_output_data,
    )

    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert payload["numeric_compute_backend"] == "numpy_fft"
    assert payload["replacement_policy"] == "genericaccel_cooley_tukey_fft_payload"
    assert payload["fft_direction"] == "forward"
    assert payload["fft_values"] == [[0.5, 0.0], [0.5, 0.0]]


def test_bridge_command_script_computes_fft_payload_from_binary_qe_input(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input = bridge_dir / "accelerated_input.json"
    accelerated_input_data = bridge_dir / "accelerated_input_values.dat"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "fft",
                            "numeric_shape_tokens": [2, 1, 1],
                            "estimated_flops": 16.0,
                            "estimated_memory_bytes": 32.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input_data.write_bytes(
        struct.pack("<qdddd", 2, 1.0, 0.0, 0.0, 0.0)
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "binary_values_path": str(accelerated_input_data),
                "binary_value_format": "stream_int64_count_real64_pairs",
                "values_elided": True,
            }
        ),
        encoding="utf-8",
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="fft",
        request_path=request_path,
        accelerated_input_json_path=accelerated_input,
        accelerated_output_data_path=accelerated_output_data,
    )

    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_json"
    )
    assert payload["placeholder_numeric_payload"] is False
    assert payload["fft_values"] == [[1.0, 0.0], [1.0, 0.0]]
    assert accelerated_output_data.exists()
    assert accelerated_output_data.read_bytes().startswith(struct.pack("<q", 2))


def test_bridge_command_script_computes_subspace_payload_from_qe_input_buffer(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input_data = bridge_dir / "accelerated_input_values.dat"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "subspace_rotation",
                            "numeric_shape_tokens": [2, 2, 2],
                            "estimated_flops": 32.0,
                            "estimated_memory_bytes": 64.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    # Header: rows, nstart, nbnd.  Values follow QE/Fortran column-major order
    # as real64 pairs.  For nstart==nbnd the first-pass bridge can materialize
    # the exact QE input columns without using a synthetic identity matrix.
    accelerated_input_data.write_bytes(
        struct.pack(
            "<qqqdddddddd",
            2,
            2,
            2,
            1.0,
            0.0,
            2.0,
            0.0,
            3.0,
            0.0,
            4.0,
            0.0,
        )
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="subspace_rotation",
        request_path=request_path,
        accelerated_input_data_path=accelerated_input_data,
        accelerated_output_data_path=accelerated_output_data,
    )

    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_json"
    )
    assert payload["placeholder_numeric_payload"] is False
    assert payload["replacement_policy"] == (
        "genericaccel_qe_input_buffer_subspace_rotation_payload"
    )
    assert payload["numeric_compute_backend"] == (
        "qe_input_buffer_passthrough_for_nstart_eq_nbnd"
    )
    assert payload["qe_input_buffer_sha256"]
    assert payload["output_buffer_path"] == str(accelerated_output_data)
    assert payload["output_value_count"] == 4
    assert payload["output_buffer_fast_copy_from_qe_input"] is True
    assert payload["output_sample_values"] == [
        [1.0, 0.0],
        [2.0, 0.0],
        [3.0, 0.0],
        [4.0, 0.0],
    ]
    assert accelerated_output_data.exists()
    assert accelerated_output_data.read_bytes().startswith(struct.pack("<qq", 2, 2))


def test_prelaunched_subspace_bridge_reuse_uses_fast_shell_copy(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input_data = bridge_dir / "accelerated_input_values.dat"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "subspace_rotation",
                            "numeric_shape_tokens": [2, 2, 2],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input_data.write_bytes(
        struct.pack(
            "<qqqdddddddd",
            2,
            2,
            2,
            1.0,
            0.0,
            2.0,
            0.0,
            3.0,
            0.0,
            4.0,
            0.0,
        )
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="subspace_rotation",
        request_path=request_path,
        accelerated_input_data_path=accelerated_input_data,
        accelerated_output_data_path=accelerated_output_data,
        reuse_prelaunched_result=True,
    )

    subprocess.run([str(script)], check=True)
    assert not accelerated_output.exists()
    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert invocation_count_path.read_text(encoding="utf-8").strip() == "2"
    assert gem5_launch_count_path.read_text(encoding="utf-8").strip() == "1"
    assert payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_binary_buffer"
    )
    assert payload["placeholder_numeric_payload"] is False
    assert payload["replacement_policy"] == (
        "genericaccel_qe_input_buffer_subspace_rotation_payload"
    )
    assert payload["numeric_compute_backend"] == (
        "qe_input_buffer_passthrough_for_nstart_eq_nbnd_fast_shell"
    )
    assert payload["output_buffer_path"] == str(accelerated_output_data)
    assert payload["output_value_count"] == 4
    assert payload["output_buffer_fast_copy_from_qe_input"] is True
    assert accelerated_output_data.read_bytes().startswith(struct.pack("<qq", 2, 2))


def test_prelaunched_fft_bridge_reuse_uses_persistent_payload_helper(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input = bridge_dir / "accelerated_input.json"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "fft",
                            "numeric_shape_tokens": [2, 1, 1],
                            "estimated_flops": 16.0,
                            "estimated_memory_bytes": 32.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "values": [[1.0, 0.0], [0.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "print('generic_accel_l4_iteration=1 status=1 error_code=0'); "
                "print('completion_magic=0x4753494d completion_status=0 "
                "cycles=55 result_addr=0x0000000009200000'); "
                "print('result_prefix={\"status\": \"passed\"}')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="fft",
        request_path=request_path,
        accelerated_input_json_path=accelerated_input,
        accelerated_output_data_path=accelerated_output_data,
        reuse_prelaunched_result=True,
    )

    subprocess.run([str(script)], check=True)
    assert not accelerated_output.exists()
    subprocess.run([str(script)], check=True)
    payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert invocation_count_path.read_text(encoding="utf-8").strip() == "2"
    assert gem5_launch_count_path.read_text(encoding="utf-8").strip() == "1"
    assert payload["replacement_policy"] == "genericaccel_cooley_tukey_fft_payload"
    assert payload["numeric_compute_backend"] == "numpy_fft"
    assert payload["fft_values"] == [[1.0, 0.0], [1.0, 0.0]]
    assert accelerated_output_data.exists()
    pid_path = bridge_dir / "fft_payload_daemon.pid"
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text(encoding="utf-8").strip()), 15)
        except (ValueError, ProcessLookupError, PermissionError):
            pass


def test_kernel_specific_payload_clears_completion_digest_writeback_blocker():
    summary = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_subspace_rotation_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_subspace_rotation",
                "target_kernel": "subspace_rotation",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path": "/tmp/qe-subspace-output.json",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
                "claim_boundary": (
                    "L4 completed; QE skipped local rotate_wfc software"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "subspace_rotation",
                    "kernel_scope": "full_subspace_rotation",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-subspace-output.json",
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": (
                        "generic_accel_l4_subspace_rotation_qe_memory_writeback"
                    ),
                }
            ],
            "accelerated_output_json": {
                "target_kernel": "subspace_rotation",
                "status": "passed",
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "matrix_values": [[1.0, 0.0], [0.0, 1.0]],
                "output_buffer_sha256": "abc123",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": "L4 gated QE-memory replacement",
            },
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
        }
    )

    assert summary["status"] == "passed"
    assert summary["accelerated_output_payload_numeric_data_present"] is True
    assert (
        "runtime_accelerated_output_local_writeback_not_accelerator_numeric_payload"
        not in summary["blockers"]
    )


def test_batched_bridge_command_script_reuses_real_gem5_launch(tmp_path):
    bridge_dir = tmp_path / "bridge"
    stdout_path = bridge_dir / "stdout.log"
    stderr_path = bridge_dir / "stderr.log"
    returncode_path = bridge_dir / "returncode.txt"
    invocation_count_path = bridge_dir / "invocation_count.txt"
    gem5_launch_count_path = bridge_dir / "launch_count.txt"
    counter_path = bridge_dir / "command_counter.txt"
    accelerated_output = bridge_dir / "accelerated_output.json"
    accelerated_input = bridge_dir / "accelerated_input.json"
    accelerated_output_data = bridge_dir / "accelerated_output_values.dat"
    request_path = bridge_dir / "simulation_request.json"
    bridge_dir.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "workload": {
                    "nodes": {
                        "selected_callsite": {
                            "op_type": "fft",
                            "numeric_shape_tokens": [2, 1, 1],
                            "estimated_flops": 16.0,
                            "estimated_memory_bytes": 32.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "values": [[1.0, 0.0], [0.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    script = _write_bridge_command_script(
        bridge_dir=bridge_dir,
        command=[
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                f"p=Path({str(counter_path)!r}); "
                "n=int(p.read_text()) if p.exists() else 0; "
                "p.write_text(str(n+1)); "
                "print('generic_accel_l4_status=1 error_code=0')"
            ),
        ],
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncode_path=returncode_path,
        invocation_count_path=invocation_count_path,
        gem5_launch_count_path=gem5_launch_count_path,
        accelerated_output_json_path=accelerated_output,
        target_kernel="fft",
        request_path=request_path,
        accelerated_input_json_path=accelerated_input,
        accelerated_output_data_path=accelerated_output_data,
        batch_size=2,
    )

    subprocess.run([str(script)], check=True)
    first_payload = json.loads(accelerated_output.read_text(encoding="utf-8"))
    assert first_payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_json"
    )
    accelerated_input.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_fft_input_buffer.v1",
                "target_kernel": "fft",
                "fft_direction": "inverse",
                "howmany": 1,
                "nr1x": 2,
                "nr2x": 1,
                "nr3x": 1,
                "values": [[0.0, 0.0], [1.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    subprocess.run([str(script)], check=True)
    second_payload = json.loads(accelerated_output.read_text(encoding="utf-8"))

    assert invocation_count_path.read_text(encoding="utf-8").strip() == "2"
    assert gem5_launch_count_path.read_text(encoding="utf-8").strip() == "1"
    assert counter_path.read_text(encoding="utf-8") == "1"
    assert second_payload["accelerator_numeric_payload_kind"] == (
        "genericaccel_kernel_numeric_output_json"
    )
    assert second_payload["qe_input_buffer_sha256"] != first_payload["qe_input_buffer_sha256"]
    assert second_payload["output_buffer_sha256"] != first_payload["output_buffer_sha256"]


def test_batched_dispatch_observed_clears_dispatch_required_blocker():
    report = build_l4_speed_optimization_report(
        {
            "rows": [
                {
                    "opportunity_id": "opp_spsi",
                    "value_label": "not_valuable_l4",
                }
            ],
            "valuable_l4_count": 0,
        },
        [
            {
                "opportunity_id": "opp_spsi",
                "kernel": "s_psi",
                "patched_qe_bridge_evidence": {
                    "baseline_elapsed_seconds": 1.0,
                    "patched_qe_elapsed_seconds": 1.5,
                    "gem5_returncode": 0,
                    "dispatch_policy": {
                        "policy": "batched_execute_command_line_shell_bridge",
                        "gem5_bridge_invocation_count_on_qe_critical_path": 2,
                        "gem5_bridge_launch_count_on_qe_critical_path": 1,
                        "batched_request_count_per_launch": 2,
                        "persistent_or_batched_dispatch_observed": True,
                    },
                },
                "accelerated_replacement": {
                    "status": "passed",
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                },
                "speed_signal": {
                    "status": "non_positive",
                    "speedup_vs_pure_qe": 0.666,
                },
            }
        ],
    )
    row = report["rows"][0]

    assert report["persistent_or_batched_dispatch_required_count"] == 0
    assert row["persistent_or_batched_dispatch_required"] is False
    assert row["persistent_or_batched_dispatch_observed"] is True
    assert row["next_engineering_gate"] == "resolve_blocked_speed_measurement"
    assert "batched L4 dispatch was observed" in row["replacement_gap"]


def test_positive_raw_speed_without_replacement_still_requires_writeback():
    report = build_l4_speed_optimization_report(
        {
            "rows": [
                {
                    "opportunity_id": "opp_projection",
                    "value_label": "not_valuable_l4",
                }
            ],
            "valuable_l4_count": 0,
        },
        [
            {
                "opportunity_id": "opp_projection",
                "kernel": "band_path_projection",
                "patched_qe_bridge_evidence": {
                    "baseline_elapsed_seconds": 2.0,
                    "patched_qe_elapsed_seconds": 1.0,
                    "gem5_returncode": 0,
                    "dispatch_policy": {
                        "policy": "prelaunched_persistent_command_line_bridge",
                        "gem5_bridge_invocation_count_on_qe_critical_path": 2,
                        "gem5_bridge_launch_count_on_qe_critical_path": 1,
                        "batched_request_count_per_launch": 1,
                        "persistent_or_batched_dispatch_observed": True,
                    },
                },
                "accelerated_replacement": {
                    "status": "blocked",
                    "accelerated_results_consumed_by_qe": True,
                    "accelerated_result_materialized_in_qe_memory": False,
                    "qe_software_kernel_execution_skipped": False,
                    "qe_kernel_work_replaced_on_critical_path": False,
                    "software_fallback_on_critical_path": True,
                    "blockers": [
                        "accelerated_result_materialization_not_proven",
                        "qe_software_kernel_execution_skip_not_proven",
                        "qe_kernel_work_replacement_not_proven",
                    ],
                },
                "speed_signal": {
                    "status": "positive",
                    "speedup_vs_pure_qe": 2.0,
                },
            }
        ],
    )

    row = report["rows"][0]
    assert report["positive_speed_count"] == 1
    assert report["replacement_writeback_required_count"] == 1
    assert row["speed_status"] == "positive"
    assert row["replacement_ready"] is False
    assert row["replacement_writeback_required_before_speed_optimization"] is True
    assert row["next_engineering_gate"] == "replacement_capable_qe_writeback"
    assert "strict selected-kernel replacement is still unproven" in row["replacement_gap"]
    assert "before treating speed as value evidence" in row["recommended_next_action"]
    assert row["value_label"] == "not_valuable_l4"


def test_speed_report_uses_attempt_value_label_for_repeat_samples():
    def attempt_with_speed(
        *,
        verdict_label: str,
        speed_status: str,
        speedup: float,
        baseline_elapsed: float,
        patched_elapsed: float,
    ) -> dict[str, object]:
        return {
            "opportunity_id": "opp_subspace",
            "kernel": "subspace_rotation",
            "value_verdict": {
                "value_label": verdict_label,
                "valuable_l4": verdict_label == "valuable_l4",
            },
            "actual_compute_evidence": {
                "status": "passed",
                "smoke_only": False,
                "qe_consumed_accelerated_outputs": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
            },
            "real_l4_provenance": {
                "status": "passed",
                "source": "gem5_genericaccel_qe_patched",
                "descriptor": {"status": "passed"},
                "request_decode": {"status": "passed"},
                "microarchitecture_execute": {"status": "passed"},
                "completion": {"status": "passed"},
            },
            "correctness": {"status": "passed"},
            "pure_qe_baseline": {
                "status": "passed",
                "baseline_result": {"elapsed_seconds": baseline_elapsed},
            },
            "patched_qe_bridge_evidence": {
                "baseline_elapsed_seconds": baseline_elapsed,
                "patched_qe_elapsed_seconds": patched_elapsed,
                "accelerated_output_json": {
                    "accelerator_numeric_payload_kind": (
                        "genericaccel_kernel_numeric_output_json"
                    ),
                    "numeric_payload_policy": (
                        "genericaccel_qe_input_buffer_subspace_rotation_payload"
                    ),
                    "output_buffer_path": "accelerated_output_values.dat",
                    "output_buffer_bytes": 128,
                },
            },
            "accelerated_replacement": {
                "status": "passed",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path_present": True,
                "accelerated_output_payload_numeric_data_present": True,
            },
            "speed_signal": {
                "status": speed_status,
                "speedup_vs_pure_qe": speedup,
            },
        }

    report = build_l4_speed_optimization_report(
        {
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "value_label": "valuable_l4",
                    "valuable_l4": True,
                }
            ],
            "valuable_l4_count": 1,
        },
        [
            attempt_with_speed(
                verdict_label="valuable_l4",
                speed_status="positive",
                speedup=2.0,
                baseline_elapsed=2.0,
                patched_elapsed=1.0,
            ),
            attempt_with_speed(
                verdict_label="not_valuable_l4",
                speed_status="non_positive",
                speedup=0.5,
                baseline_elapsed=1.0,
                patched_elapsed=2.0,
            ),
        ],
    )

    labels = [row["value_label"] for row in report["rows"]]
    assert labels == ["valuable_l4", "not_valuable_l4"]
    assert [row["matrix_value_label"] for row in report["rows"]] == [
        "valuable_l4",
        "valuable_l4",
    ]

    repeatability = build_l4_value_repeatability_report(report)
    row = repeatability["rows"][0]
    assert row["repeatability_status"] == "value_gate_not_passed"
    assert row["speed_repeatability_status"] == "mixed_positive_and_non_positive"
    assert repeatability["speed_mixed_count"] == 1
    assert repeatability["value_gate_not_passed_count"] == 1
    assert row["valuable_l4_sample_count"] == 1
    assert row["non_valuable_l4_sample_count"] == 1
    assert "valuable_l4_value_label_missing" in row["blockers"]
    assert "replacement_ready_speed_repeatability_mixed" in row["blockers"]


def test_speed_report_recomputes_stale_serialized_value_verdict():
    attempt = {
        "opportunity_id": "opp_subspace",
        "kernel": "subspace_rotation",
        "value_verdict": {
            "value_label": "valuable_l4",
            "valuable_l4": True,
        },
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
            "qe_consumed_accelerated_outputs": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {
            "status": "passed",
            "baseline_result": {
                "elapsed_seconds": 2.0,
                "gpu_runtime_context": {
                    "schema_version": "dse.qe_gpu_runtime_context.v1",
                    "gpu_available": True,
                },
            },
        },
        "patched_qe_bridge_evidence": {
            "baseline_elapsed_seconds": 2.0,
            "patched_qe_elapsed_seconds": 1.0,
            "accelerated_output_json": {
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload_policy": (
                    "genericaccel_identity_subspace_rotation_payload"
                ),
                "output_buffer_path": "accelerated_output_values.dat",
                "output_buffer_bytes": 128,
            },
        },
        "accelerated_replacement": {
            "status": "passed",
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "software_fallback_on_critical_path": False,
            "accelerated_output_data_path_present": True,
            "accelerated_output_payload_numeric_data_present": True,
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 2.0,
        },
    }

    assert classify_l4_offload_value(attempt)["value_label"] == "not_valuable_l4"

    report = build_l4_speed_optimization_report(
        {
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "value_label": "not_valuable_l4",
                    "valuable_l4": False,
                }
            ],
            "valuable_l4_count": 0,
        },
        [attempt],
    )

    row = report["rows"][0]
    assert row["serialized_attempt_value_label"] == "valuable_l4"
    assert row["serialized_attempt_valuable_l4"] is True
    assert row["value_label"] == "not_valuable_l4"
    assert row["valuable_l4"] is False
    assert row["matrix_value_label"] == "not_valuable_l4"
    assert report["valuable_l4_count"] == 0
    assert report["positive_speed_value_claim_allowed"] is False


def test_speed_repeatability_preserves_workload_variant_identity():
    def attempt_for_variant(
        *,
        variant_id: str,
        runtime_case_id: str,
        speedup: float,
    ) -> dict[str, object]:
        return {
            "opportunity_id": "opp_nscf_subspace",
            "kernel": "subspace_rotation",
            "selection_profile": {
                "workload_variant_applied": True,
                "workload_variant_id": variant_id,
                "workload_variant_binding": {
                    "schema_version": "dse.qe_workload_variant_binding.v1",
                    "workload_variant_id": variant_id,
                    "formal_status": "formal",
                    "target_kernel": "subspace_rotation",
                },
                "original_workload_case_id": "qe_si_nscf_bandgrid_v1",
                "runtime_workload_case_id": runtime_case_id,
            },
            "value_verdict": {
                "value_label": "valuable_l4",
                "valuable_l4": True,
            },
            "patched_qe_bridge_evidence": {
                "baseline_elapsed_seconds": 10.0,
                "patched_qe_elapsed_seconds": 10.0 / speedup,
            },
            "accelerated_replacement": {
                "status": "passed",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path_present": True,
            },
            "speed_signal": {
                "status": "positive" if speedup > 1.0 else "non_positive",
                "speedup_vs_pure_qe": speedup,
            },
        }

    speed_report = build_l4_speed_optimization_report(
        {
            "rows": [
                {
                    "opportunity_id": "opp_nscf_subspace",
                    "value_label": "valuable_l4",
                    "valuable_l4": True,
                }
            ],
            "valuable_l4_count": 1,
        },
        [
            attempt_for_variant(
                variant_id="qe_si_nscf_amortized_bandgrid_probe_v1",
                runtime_case_id=(
                    "qe_si_nscf_bandgrid_v1__"
                    "qe_si_nscf_amortized_bandgrid_probe_v1"
                ),
                speedup=1.04,
            ),
            attempt_for_variant(
                variant_id="qe_si_nscf_canonical_bandgrid_probe_v1",
                runtime_case_id=(
                    "qe_si_nscf_bandgrid_v1__"
                    "qe_si_nscf_canonical_bandgrid_probe_v1"
                ),
                speedup=0.97,
            ),
        ],
    )

    rows_by_variant = {
        row["workload_variant_id"]: row for row in speed_report["rows"]
    }
    assert set(rows_by_variant) == {
        "qe_si_nscf_amortized_bandgrid_probe_v1",
        "qe_si_nscf_canonical_bandgrid_probe_v1",
    }
    assert rows_by_variant[
        "qe_si_nscf_amortized_bandgrid_probe_v1"
    ]["workload_variant_identity_key"] == (
        "workload_variant:qe_si_nscf_amortized_bandgrid_probe_v1"
    )
    assert rows_by_variant[
        "qe_si_nscf_canonical_bandgrid_probe_v1"
    ]["runtime_workload_case_id"] == (
        "qe_si_nscf_bandgrid_v1__qe_si_nscf_canonical_bandgrid_probe_v1"
    )
    assert rows_by_variant[
        "qe_si_nscf_amortized_bandgrid_probe_v1"
    ]["workload_variant_binding"]["target_kernel"] == "subspace_rotation"

    repeatability = build_l4_value_repeatability_report(speed_report)
    repeatability_rows_by_variant = {
        row["workload_variant_id"]: row for row in repeatability["rows"]
    }

    assert repeatability["replacement_ready_identity_count"] == 2
    assert repeatability["speed_mixed_count"] == 0
    assert repeatability["repeatability_mixed_count"] == 0
    assert repeatability_rows_by_variant[
        "qe_si_nscf_amortized_bandgrid_probe_v1"
    ]["speed_repeatability_status"] == "single_positive_unconfirmed"
    assert repeatability_rows_by_variant[
        "qe_si_nscf_canonical_bandgrid_probe_v1"
    ]["speed_repeatability_status"] == "stable_non_positive"
    assert repeatability_rows_by_variant[
        "qe_si_nscf_amortized_bandgrid_probe_v1"
    ]["runtime_workload_case_id"] == (
        "qe_si_nscf_bandgrid_v1__qe_si_nscf_amortized_bandgrid_probe_v1"
    )


def test_repeatability_report_blocks_mixed_replacement_ready_speed():
    report = build_l4_value_repeatability_report(
        {
            "report_hash": "speed-report",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "value_label": "valuable_l4",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 1.02,
                },
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "value_label": "valuable_l4",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 0.99,
                },
            ],
        }
    )

    row = report["rows"][0]
    assert report["repeatability_stable_valuable_l4_count"] == 0
    assert report["repeatability_mixed_count"] == 1
    assert report["speed_mixed_count"] == 1
    assert report["deliverable_complete"] is False
    assert row["repeatability_status"] == "mixed_positive_and_non_positive"
    assert row["speed_repeatability_status"] == "mixed_positive_and_non_positive"
    assert row["repeatability_stable_value"] is False
    assert row["speedups_vs_pure_qe"] == [1.02, 0.99]
    assert "replacement_ready_speed_repeatability_mixed" in row["blockers"]


def test_repeatability_report_separates_replacement_configurations():
    report = build_l4_value_repeatability_report(
        {
            "report_hash": "speed-report",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "workload_variant_id": "qe_si_nscf_heavy_bandgrid_probe_v1",
                    "workload_variant_identity_key": (
                        "workload_variant:qe_si_nscf_heavy_bandgrid_probe_v1"
                    ),
                    "replacement_configuration_identity_key": "replacement_config:fast-binary",
                    "replacement_configuration": {
                        "accelerator_numeric_payload_kind": (
                            "genericaccel_kernel_numeric_output_binary_buffer"
                        ),
                        "numeric_compute_backend": (
                            "qe_input_buffer_passthrough_for_nstart_eq_nbnd_fast_shell"
                        ),
                    },
                    "value_label": "valuable_l4",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 1.02,
                },
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "workload_variant_id": "qe_si_nscf_heavy_bandgrid_probe_v1",
                    "workload_variant_identity_key": (
                        "workload_variant:qe_si_nscf_heavy_bandgrid_probe_v1"
                    ),
                    "replacement_configuration_identity_key": "replacement_config:fast-binary",
                    "replacement_configuration": {
                        "accelerator_numeric_payload_kind": (
                            "genericaccel_kernel_numeric_output_binary_buffer"
                        ),
                        "numeric_compute_backend": (
                            "qe_input_buffer_passthrough_for_nstart_eq_nbnd_fast_shell"
                        ),
                    },
                    "value_label": "valuable_l4",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 1.01,
                },
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "workload_variant_id": "qe_si_nscf_heavy_bandgrid_probe_v1",
                    "workload_variant_identity_key": (
                        "workload_variant:qe_si_nscf_heavy_bandgrid_probe_v1"
                    ),
                    "replacement_configuration_identity_key": "replacement_config:old-json",
                    "replacement_configuration": {
                        "accelerator_numeric_payload_kind": (
                            "genericaccel_kernel_numeric_output_json"
                        ),
                        "numeric_compute_backend": (
                            "qe_input_buffer_passthrough_for_nstart_eq_nbnd"
                        ),
                    },
                    "value_label": "not_valuable_l4",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 0.98,
                },
            ],
        }
    )

    rows_by_config = {
        row["replacement_configuration_identity_key"]: row
        for row in report["rows"]
    }

    assert report["replacement_ready_identity_count"] == 2
    assert report["repeatability_stable_valuable_l4_count"] == 1
    assert report["speed_mixed_count"] == 0
    assert rows_by_config["replacement_config:fast-binary"][
        "repeatability_status"
    ] == "stable_positive"
    assert rows_by_config["replacement_config:fast-binary"][
        "repeatability_stable_value"
    ] is True
    assert rows_by_config["replacement_config:old-json"][
        "repeatability_status"
    ] == "value_gate_not_passed"


def test_selection_and_value_reports_surface_stable_repeatable_config():
    manifest = {
        "manifest_hash": "manifest",
        "opportunities": [
            {
                "opportunity_id": "opp_subspace",
                "workload_case_id": "qe_si_nscf_bandgrid_v1",
                "stage_type": "nscf",
                "kernel": "subspace_rotation",
                "kernel_family": "dense_subspace",
                "selection_priority": {"score": 9.0},
            }
        ],
    }
    matrix = {
        "matrix_hash": "matrix",
        "rows": [
            {
                "opportunity_id": "opp_subspace",
                "kernel": "subspace_rotation",
                "value_label": "valuable_l4",
                "valuable_l4": True,
            }
        ],
        "row_count": 1,
        "valuable_l4_count": 1,
        "value_counts": {"valuable_l4": 1},
    }
    repeatability = {
        "report_hash": "repeatability",
        "rows": [
            {
                "opportunity_id": "opp_subspace",
                "kernel": "subspace_rotation",
                "workload_variant_id": "qe_si_nscf_heavy_bandgrid_probe_v1",
                "runtime_workload_case_id": (
                    "qe_si_nscf_bandgrid_v1__"
                    "qe_si_nscf_heavy_bandgrid_probe_v1"
                ),
                "replacement_configuration_identity_key": (
                    "replacement_config:fast-binary"
                ),
                "replacement_configuration": {
                    "numeric_compute_backend": (
                        "qe_input_buffer_passthrough_for_nstart_eq_nbnd_fast_shell"
                    )
                },
                "replacement_ready_sample_count": 2,
                "valuable_l4_sample_count": 2,
                "positive_speed_sample_count": 2,
                "non_positive_speed_sample_count": 0,
                "speedups_vs_pure_qe": [1.02, 1.01],
                "min_speedup_vs_pure_qe": 1.01,
                "max_speedup_vs_pure_qe": 1.02,
                "source_attempt_artifacts": ["attempt1.json", "attempt2.json"],
                "repeatability_stable_value": True,
            }
        ],
    }

    value_report = build_offload_value_report(
        matrix,
        repeatability_report=repeatability,
    )
    selection_report = build_offload_selection_search_report(
        manifest,
        matrix,
        blocker_report={"status": "passed", "blocker_rows": []},
        workload_variant_search_space={"variants": []},
        repeatability_report=repeatability,
    )

    assert value_report["summary"]["stable_repeatability_valuable_l4_count"] == 1
    assert value_report["stable_repeatability_configurations"][0][
        "replacement_configuration_identity_key"
    ] == "replacement_config:fast-binary"
    selected = selection_report["ranked_opportunities"][0]
    assert selected["stable_repeatability_configuration_count"] == 1
    assert selected["best_stable_speedup_vs_pure_qe"] == 1.02
    assert "promote this stable full-QE L4 configuration" in selected[
        "recommended_next_action"
    ]
    assert selection_report["stable_repeatability_valuable_l4_count"] == 1


def test_repeatability_report_blocks_positive_speed_without_value_gate():
    report = build_l4_value_repeatability_report(
        {
            "report_hash": "speed-report",
            "rows": [
                {
                    "opportunity_id": "opp_diag",
                    "kernel": "diagonalization",
                    "value_label": "attempted_l4_blocked",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 1.03,
                },
                {
                    "opportunity_id": "opp_diag",
                    "kernel": "diagonalization",
                    "value_label": "attempted_l4_blocked",
                    "replacement_ready": True,
                    "speedup_vs_pure_qe": 1.02,
                },
            ],
        }
    )

    row = report["rows"][0]
    assert report["repeatability_stable_valuable_l4_count"] == 0
    assert report["repeatability_mixed_count"] == 0
    assert report["value_gate_not_passed_count"] == 1
    assert row["repeatability_status"] == "value_gate_not_passed"
    assert row["speed_repeatability_status"] == "stable_positive"
    assert row["repeatability_stable_value"] is False
    assert row["valuable_l4_sample_count"] == 0
    assert row["non_valuable_l4_sample_count"] == 2
    assert "valuable_l4_value_label_missing" in row["blockers"]


def test_bundle_viability_report_does_not_upgrade_member_value_to_bundle():
    report = build_offload_bundle_viability_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": ["subspace_rotation", "fft"],
                    "opportunity_ids": ["opp_subspace", "opp_fft"],
                    "hpsi_only": False,
                    "bundle_execution_policy": (
                        "same_workload_multi_callsite_actual_compute_candidate"
                    ),
                    "runnable_as_single_qe_workflow": True,
                    "selection_priority": {"score": 1.7},
                }
            ],
        },
        {
            "matrix_hash": "matrix",
            "rows": [
                {"opportunity_id": "opp_subspace", "value_label": "valuable_l4"},
                {"opportunity_id": "opp_fft", "value_label": "not_valuable_l4"},
            ],
        },
        {
            "report_hash": "replacement",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "real_l4_status": "passed",
                    "ready_for_value_gate": True,
                },
                {
                    "opportunity_id": "opp_fft",
                    "real_l4_status": "passed",
                    "ready_for_value_gate": False,
                },
            ],
        },
        {
            "report_hash": "speed",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "value_label": "valuable_l4",
                    "speedup_vs_pure_qe": 1.02,
                },
                {
                    "opportunity_id": "opp_fft",
                    "value_label": "not_valuable_l4",
                    "speedup_vs_pure_qe": 1.01,
                },
            ],
        },
        {
            "report_hash": "repeatability",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "repeatability_stable_value": False,
                }
            ],
        },
    )

    row = report["rows"][0]
    assert report["status"] == "bundle_value_unproven"
    assert report["bundle_level_valuable_l4_count"] == 0
    assert report["bundles_with_raw_valuable_members_count"] == 1
    assert report["bundles_with_stable_repeatable_members_count"] == 0
    assert row["bundle_value_allowed"] is False
    assert row["viability_status"] == "has_raw_valuable_member_but_bundle_unproven"
    assert row["valuable_l4_member_count"] == 1
    assert row["positive_speed_value_blocked_member_count"] == 1
    assert "single_workflow_bundle_l4_evidence_missing" in row["blockers"]
    assert "bundle_has_no_stable_repeatable_value_members" in row["blockers"]
    assert report["deliverable_complete"] is False


def test_bundle_viability_report_surfaces_stable_member_configurations():
    report = build_offload_bundle_viability_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": ["subspace_rotation", "fft"],
                    "opportunity_ids": ["opp_subspace", "opp_fft"],
                    "hpsi_only": False,
                    "bundle_execution_policy": (
                        "same_workload_multi_callsite_actual_compute_candidate"
                    ),
                    "runnable_as_single_qe_workflow": True,
                    "selection_priority": {"score": 1.7},
                }
            ],
        },
        {
            "matrix_hash": "matrix",
            "rows": [
                {"opportunity_id": "opp_subspace", "value_label": "valuable_l4"},
                {"opportunity_id": "opp_fft", "value_label": "not_valuable_l4"},
            ],
        },
        {
            "report_hash": "replacement",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "real_l4_status": "passed",
                    "ready_for_value_gate": True,
                },
                {
                    "opportunity_id": "opp_fft",
                    "real_l4_status": "passed",
                    "ready_for_value_gate": False,
                },
            ],
        },
        {
            "report_hash": "speed",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "value_label": "valuable_l4",
                    "speedup_vs_pure_qe": 1.02,
                }
            ],
        },
        {
            "report_hash": "repeatability",
            "rows": [
                {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "workload_variant_id": "qe_si_nscf_heavy_bandgrid_probe_v1",
                    "runtime_workload_case_id": (
                        "qe_si_nscf_bandgrid_v1__"
                        "qe_si_nscf_heavy_bandgrid_probe_v1"
                    ),
                    "replacement_configuration_identity_key": (
                        "replacement_config:fast-binary"
                    ),
                    "replacement_configuration": {
                        "numeric_compute_backend": (
                            "qe_input_buffer_passthrough_for_nstart_eq_nbnd_fast_shell"
                        )
                    },
                    "replacement_ready_sample_count": 2,
                    "valuable_l4_sample_count": 2,
                    "positive_speed_sample_count": 2,
                    "non_positive_speed_sample_count": 0,
                    "speedups_vs_pure_qe": [1.02, 1.01],
                    "min_speedup_vs_pure_qe": 1.01,
                    "max_speedup_vs_pure_qe": 1.02,
                    "source_attempt_artifacts": ["attempt1.json", "attempt2.json"],
                    "repeatability_stable_value": True,
                }
            ],
        },
    )

    row = report["rows"][0]
    assert report["bundle_level_valuable_l4_count"] == 0
    assert report["bundles_with_stable_repeatable_members_count"] == 1
    assert (
        report["single_workflow_bundle_candidates_with_stable_members_count"]
        == 1
    )
    assert report["stable_repeatable_member_configuration_count"] == 1
    assert row["viability_status"] == "has_stable_member_but_bundle_unproven"
    assert row["runnable_as_single_qe_workflow"] is True
    assert row["bundle_execution_policy"] == (
        "same_workload_multi_callsite_actual_compute_candidate"
    )
    assert row["bundle_priority_score"] == 1.7
    assert row["stable_repeatable_value_member_opportunity_ids"] == [
        "opp_subspace"
    ]
    stable_config = row["stable_repeatable_member_configurations"][0]
    assert stable_config["replacement_configuration_identity_key"] == (
        "replacement_config:fast-binary"
    )
    assert stable_config["speedups_vs_pure_qe"] == [1.02, 1.01]
    assert "single-workflow multi-callsite actual_compute" in row[
        "recommended_next_action"
    ]
    assert "single_workflow_bundle_l4_evidence_missing" in row["blockers"]


def test_bundle_single_workflow_gate_rejects_expanded_member_campaign():
    report = build_bundle_single_workflow_l4_evidence_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": [
                        "diagonalization",
                        "fft",
                        "h_psi",
                        "s_psi",
                        "subspace_rotation",
                    ],
                    "opportunity_ids": [
                        "opp_diag",
                        "opp_fft",
                        "opp_hpsi",
                        "opp_spsi",
                        "opp_subspace",
                    ],
                    "hpsi_only": False,
                    "runnable_as_single_qe_workflow": True,
                }
            ],
        },
        [
            {
                "status_path": "runs/dse/bundle_seed/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 5,
                "attempted_count": 5,
                "non_smoke_actual_compute_attempt_count": 5,
                "actual_compute_full_qe_evidence_passed_count": 2,
                "valuable_l4_count": 1,
                "bundle_level_valuable_l4": True,
                "deliverable_complete": False,
            }
        ],
    )

    row = report["rows"][0]
    assert report["bundle_level_valuable_l4_count"] == 0
    assert report["per_opportunity_expanded_campaign_bundle_count"] == 1
    assert row["bundle_level_valuable_l4"] is False
    assert row["bundle_value_allowed"] is False
    assert row["single_qe_workflow_proven"] is False
    assert row["per_opportunity_expanded_campaign_observed"] is True
    assert "per_opportunity_expanded_campaign_not_single_qe_workflow" in row[
        "blockers"
    ]
    assert "single_qe_workflow_not_proven" in row["blockers"]
    assert "bundle_value_claim_without_single_workflow_proof" in row["blockers"]
    assert "bundle_level_value_claim_rejected" in row["blockers"]
    assert report["deliverable_complete"] is False


def test_bundle_single_workflow_gate_can_accept_explicit_bundle_proof():
    report = build_bundle_single_workflow_l4_evidence_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": ["fft", "subspace_rotation"],
                    "opportunity_ids": ["opp_fft", "opp_subspace"],
                    "hpsi_only": False,
                }
            ],
        },
        [
            {
                "status_path": "runs/dse/true_bundle/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 0,
                "attempted_count": 1,
                "single_qe_workflow_proven": True,
                "non_smoke_actual_compute_attempt_count": 1,
                "actual_compute_full_qe_evidence_passed_count": 1,
                "valuable_l4_count": 1,
                "bundle_level_valuable_l4": True,
                "deliverable_complete": False,
            }
        ],
    )

    row = report["rows"][0]
    assert report["status"] == "bundle_value_proven"
    assert report["bundle_level_valuable_l4_count"] == 1
    assert row["bundle_level_valuable_l4"] is True
    assert row["bundle_value_allowed"] is True
    assert row["single_qe_workflow_proven"] is True
    assert row["per_opportunity_expanded_campaign_observed"] is False
    assert "per_opportunity_expanded_campaign_not_single_qe_workflow" not in row[
        "blockers"
    ]


def test_bundle_single_workflow_gate_rejects_partial_bundle_coverage_value_claim():
    report = build_bundle_single_workflow_l4_evidence_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": [
                        "diagonalization",
                        "fft",
                        "h_psi",
                        "s_psi",
                        "subspace_rotation",
                    ],
                    "opportunity_ids": [
                        "opp_diag",
                        "opp_fft",
                        "opp_hpsi",
                        "opp_spsi",
                        "opp_subspace",
                    ],
                    "hpsi_only": False,
                }
            ],
        },
        [
            {
                "status_path": "runs/dse/partial_bundle/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 0,
                "attempted_count": 1,
                "single_qe_workflow_proven": True,
                "single_qe_workflow_covers_full_bundle": False,
                "non_smoke_actual_compute_attempt_count": 1,
                "actual_compute_full_qe_evidence_passed_count": 1,
                "valuable_l4_count": 1,
                "bundle_level_valuable_l4": True,
                "deliverable_complete": False,
            }
        ],
    )

    row = report["rows"][0]
    assert report["bundle_level_valuable_l4_count"] == 0
    assert row["single_qe_workflow_proven"] is True
    assert row["single_qe_workflow_covers_full_bundle"] is False
    assert row["bundle_level_valuable_l4"] is False
    assert row["bundle_value_allowed"] is False
    assert "single_qe_workflow_does_not_cover_full_bundle" in row["blockers"]
    assert "bundle_level_value_claim_rejected" in row["blockers"]


def test_bundle_single_workflow_gate_uses_strongest_status_per_bundle():
    report = build_bundle_single_workflow_l4_evidence_report(
        {
            "search_space_hash": "bundle-space",
            "bundles": [
                {
                    "bundle_id": "bundle_nscf_stage",
                    "classification": "workload_stage_bundle_l4_attempt_candidate",
                    "granularity": "bundle",
                    "workload_case_id": "qe_si_nscf_bandgrid_v1",
                    "stage_type": "nscf",
                    "kernel_list": ["fft", "subspace_rotation"],
                    "opportunity_ids": ["opp_fft", "opp_subspace"],
                    "hpsi_only": False,
                }
            ],
        },
        [
            {
                "status_path": "runs/dse/newer_but_weaker/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 0,
                "attempted_count": 1,
                "single_qe_workflow_proven": False,
                "non_smoke_actual_compute_attempt_count": 0,
                "actual_compute_full_qe_evidence_passed_count": 0,
                "valuable_l4_count": 0,
                "bundle_level_valuable_l4": False,
            },
            {
                "status_path": "runs/dse/invalid_value_claim/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 2,
                "attempted_count": 2,
                "single_qe_workflow_proven": False,
                "non_smoke_actual_compute_attempt_count": 2,
                "actual_compute_full_qe_evidence_passed_count": 2,
                "valuable_l4_count": 1,
                "bundle_level_valuable_l4": True,
            },
            {
                "status_path": "runs/dse/actual_bundle/status.json",
                "selected_bundle_ids": ["bundle_nscf_stage"],
                "selected_bundle_expanded_opportunity_count": 0,
                "attempted_count": 1,
                "single_qe_workflow_proven": True,
                "single_qe_workflow_covers_full_bundle": True,
                "non_smoke_actual_compute_attempt_count": 1,
                "actual_compute_full_qe_evidence_passed_count": 1,
                "valuable_l4_count": 0,
                "bundle_level_valuable_l4": False,
            },
        ],
    )

    row = report["rows"][0]
    assert row["single_qe_workflow_proven"] is True
    assert row["single_qe_workflow_covers_full_bundle"] is True
    assert "single_qe_workflow_not_proven" not in row["blockers"]
    assert "bundle_actual_compute_full_qe_evidence_not_passed" not in row[
        "blockers"
    ]
    assert "bundle_member_valuable_l4_missing" in row["blockers"]


def test_bundle_runtime_contract_defines_multi_kernel_slots_without_value_claim():
    bundle_space = {
        "search_space_hash": "bundle-space",
        "bundles": [
            {
                "bundle_id": "bundle_nscf_stage",
                "classification": "workload_stage_bundle_l4_attempt_candidate",
                "granularity": "bundle",
                "workload_case_id": "qe_si_nscf_bandgrid_v1",
                "stage_type": "nscf",
                "kernel_list": ["fft", "subspace_rotation"],
                "opportunity_ids": ["opp_fft", "opp_subspace"],
                "hpsi_only": False,
            }
        ],
    }
    opportunity_manifest = {
        "manifest_hash": "opportunities",
        "opportunities": [
            {
                "opportunity_id": "opp_fft",
                "kernel": "fft",
                "callsite_id": "callsite_fft",
            },
            {
                "opportunity_id": "opp_subspace",
                "kernel": "subspace_rotation",
                "callsite_id": "callsite_subspace",
            },
        ],
    }

    report = build_bundle_runtime_contract_report(
        bundle_space,
        opportunity_manifest=opportunity_manifest,
    )

    row = report["rows"][0]
    fft_target = row["target_slots"][0]
    subspace_target = row["target_slots"][1]
    assert report["status"] == "runtime_contract_defined_runtime_unimplemented"
    assert report["multi_callsite_bundle_count"] == 1
    assert report["runtime_contract_ready_bundle_count"] == 0
    assert report["deliverable_complete"] is False
    assert (
        report["runtime_capabilities"][
            "supports_single_target_bundle_runtime_manifest_alias"
        ]
        is True
    )
    assert report["manifest_schema"]["env"] == "QE_OFFLOAD_BUNDLE_RUNTIME_MANIFEST"
    assert report["manifest_schema"]["selector_env_fallback"] == (
        "QE_OFFLOAD_BUNDLE_TARGETS"
    )
    assert row["multi_kernel_selector_value"] == (
        "opp_fft:fft,opp_subspace:subspace_rotation"
    )
    assert row["runtime_contract_ready"] is False
    assert "bundle_runtime_manifest_not_implemented" in row["blockers"]
    assert "runtime_bridge_multi_kernel_selector_not_implemented" in row[
        "blockers"
    ]
    assert "runtime_bridge_multi_output_slots_not_implemented" in row["blockers"]
    assert "per_callsite_l4_provenance_slots_not_implemented" in row["blockers"]
    assert (
        "single_qe_workflow_multi_callsite_runtime_not_implemented"
        in row["blockers"]
    )
    assert fft_target["kernel_slot_envs"]["accelerated_output_data"] == (
        "QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_FFT"
    )
    assert subspace_target["kernel_slot_envs"]["accelerated_output_json"] == (
        "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON_SUBSPACE_ROTATION"
    )
    assert "not actual-compute evidence" in report["claim_boundary"]


def test_bundle_runtime_contract_explicit_capabilities_can_feed_readiness():
    bundle_space = {
        "search_space_hash": "bundle-space",
        "bundles": [
            {
                "bundle_id": "bundle_nscf_stage",
                "classification": "workload_stage_bundle_l4_attempt_candidate",
                "granularity": "bundle",
                "workload_case_id": "qe_si_nscf_bandgrid_v1",
                "stage_type": "nscf",
                "kernel_list": ["fft", "subspace_rotation"],
                "opportunity_ids": ["opp_fft", "opp_subspace"],
                "hpsi_only": False,
            }
        ],
    }
    patch_manifest = {
        "manifest_hash": "patch-manifest",
        "patch_rows": [
            {
                "bundle_id": "bundle_nscf_stage",
                "changed_files": [
                    "patches/qe_callsite_offload_hooks/bundle_nscf_stage.patch",
                    "patches/qe_callsite_offload_hooks/opp_fft.patch",
                    "patches/qe_callsite_offload_hooks/opp_subspace.patch",
                ],
                "instrumentation_capabilities": {
                    "generic_bridge_hook_present": True,
                    "runtime_replacement_evidence_hook_present": True,
                    "accelerated_result_writeback_present": True,
                    "trusted_l4_replacement_precheck_passed": True,
                    "missing_declared_patch_files": [],
                },
            }
        ],
    }
    runtime_contract = build_bundle_runtime_contract_report(
        bundle_space,
        runtime_capabilities={
            "supports_bundle_runtime_manifest": True,
            "supports_multi_kernel_selector": True,
            "supports_multi_output_slots": True,
            "supports_per_callsite_l4_provenance_slots": True,
            "supports_single_qe_workflow_multi_callsite_bundle": True,
        },
    )

    report = build_bundle_harness_readiness_report(
        bundle_space,
        patch_manifest,
        runtime_capabilities=runtime_contract,
    )

    row = report["rows"][0]
    assert runtime_contract["status"] == "runtime_contract_implemented"
    assert report["status"] == "ready"
    assert report["ready_bundle_harness_count"] == 1
    assert row["ready_for_single_workflow_bundle_harness"] is True
    assert "runtime_bridge_single_kernel_selector" not in row["blockers"]
    assert "runtime_bridge_single_output_slot" not in row["blockers"]
    assert "single_qe_workflow_multi_callsite_runtime_missing" not in row["blockers"]
    assert report["deliverable_complete"] is False


def test_bundle_runtime_env_builder_can_plan_multi_target_slots(tmp_path):
    env: dict[str, str] = {}
    fft_dir = tmp_path / "fft"
    subspace_dir = tmp_path / "subspace"
    fft_dir.mkdir()
    subspace_dir.mkdir()
    for path in [
        fft_dir / "bridge.sh",
        subspace_dir / "bridge.sh",
    ]:
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    result = _install_bundle_runtime_env(
        env,
        bridge_dir=tmp_path,
        bundle_id="bundle_nscf_stage",
        runtime_mode="planned_multi_target_alias_for_bundle_contract",
        targets=[
            {
                "opportunity": {
                    "opportunity_id": "opp_fft",
                    "kernel": "fft",
                    "callsite_id": "callsite_fft",
                },
                "bridge_script": fft_dir / "bridge.sh",
                "runtime_kernel_evidence_path": fft_dir / "kernel.json",
                "runtime_offload_provenance_path": fft_dir / "provenance.json",
                "accelerated_output_json_path": fft_dir / "output.json",
                "accelerated_input_json_path": fft_dir / "input.json",
                "accelerated_input_data_path": fft_dir / "input.dat",
                "accelerated_output_data_path": fft_dir / "output.dat",
            },
            {
                "opportunity": {
                    "opportunity_id": "opp_subspace",
                    "kernel": "subspace_rotation",
                    "callsite_id": "callsite_subspace",
                },
                "bridge_script": subspace_dir / "bridge.sh",
                "runtime_kernel_evidence_path": subspace_dir / "kernel.json",
                "runtime_offload_provenance_path": subspace_dir / "provenance.json",
                "accelerated_output_json_path": subspace_dir / "output.json",
                "accelerated_input_json_path": subspace_dir / "input.json",
                "accelerated_input_data_path": subspace_dir / "input.dat",
                "accelerated_output_data_path": subspace_dir / "output.dat",
            },
        ],
    )

    manifest = result["manifest"]
    assert Path(result["manifest_path"]).exists()
    assert env["QE_OFFLOAD_BUNDLE_TARGETS"] == (
        "opp_fft:fft,opp_subspace:subspace_rotation"
    )
    assert env["QE_OFFLOAD_BRIDGE_COMMAND_FFT"].endswith("fft/bridge.sh")
    assert env["QE_OFFLOAD_BRIDGE_COMMAND_SUBSPACE_ROTATION"].endswith(
        "subspace/bridge.sh"
    )
    assert env["QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_FFT"].endswith("fft/output.dat")
    assert env["QE_OFFLOAD_ACCELERATED_OUTPUT_DATA_SUBSPACE_ROTATION"].endswith(
        "subspace/output.dat"
    )
    assert manifest["planned_single_qe_workflow_multi_callsite_bundle"] is True
    assert manifest["single_qe_workflow_multi_callsite_bundle"] is False
    assert manifest["target_count"] == 2
    assert "not bundle-level value proof" not in manifest["claim_boundary"]
    assert "not actual-compute evidence" not in manifest["claim_boundary"]
    assert "runtime manifest/env construction only" in manifest["claim_boundary"]


def test_bundle_single_workflow_runner_preflight_blocks_value_until_real_run(tmp_path):
    bundle_space = {
        "search_space_hash": "bundle-space",
        "bundles": [
            {
                "bundle_id": "bundle_nscf_stage",
                "classification": "workload_stage_bundle_l4_attempt_candidate",
                "granularity": "bundle",
                "workload_case_id": "qe_si_nscf_bandgrid_v1",
                "stage_type": "nscf",
                "kernel_list": ["fft", "subspace_rotation"],
                "opportunity_ids": ["opp_fft", "opp_subspace"],
                "runnable_as_single_qe_workflow": True,
            }
        ],
    }
    opportunity_manifest = {
        "manifest_hash": "opportunities",
        "opportunities": [
            {
                "opportunity_id": "opp_fft",
                "kernel": "fft",
                "callsite_id": "callsite_fft",
            },
            {
                "opportunity_id": "opp_subspace",
                "kernel": "subspace_rotation",
                "callsite_id": "callsite_subspace",
            },
        ],
    }

    report = build_bundle_single_workflow_runner_preflight(
        bundle_space=bundle_space,
        opportunity_manifest=opportunity_manifest,
        bundle_id="bundle_nscf_stage",
        out_dir=tmp_path,
    )

    assert report["status"] == "blocked_preflight_only"
    assert report["target_count"] == 2
    assert report["planned_single_qe_workflow_multi_callsite_bundle"] is True
    assert report["single_qe_workflow_proven"] is False
    assert report["single_qe_workflow_bundle_attempt_executed"] is False
    assert report["non_smoke_actual_compute"] is False
    assert report["bundle_level_valuable_l4"] is False
    assert report["bundle_value_allowed"] is False
    assert report["deliverable_complete"] is False
    assert "QE_OFFLOAD_BRIDGE_COMMAND_FFT" in report["runtime_env_keys"]
    assert "QE_OFFLOAD_BRIDGE_COMMAND_SUBSPACE_ROTATION" in report[
        "runtime_env_keys"
    ]
    assert "fortran_per_kernel_env_alias_consumption_not_verified" in report[
        "blockers"
    ]
    assert "single_qe_workflow_runtime_execution_not_run" in report["blockers"]
    assert "non_smoke_bundle_actual_compute_not_run" in report["blockers"]


def test_bundle_harness_readiness_reports_single_kernel_runtime_blockers():
    bundle_space = {
        "search_space_hash": "bundle-space",
        "bundles": [
            {
                "bundle_id": "bundle_nscf_stage",
                "classification": "workload_stage_bundle_l4_attempt_candidate",
                "granularity": "bundle",
                "workload_case_id": "qe_si_nscf_bandgrid_v1",
                "stage_type": "nscf",
                "kernel_list": ["fft", "subspace_rotation"],
                "opportunity_ids": ["opp_fft", "opp_subspace"],
                "hpsi_only": False,
            }
        ],
    }
    patch_manifest = {
        "manifest_hash": "patch-manifest",
        "patch_rows": [
            {
                "bundle_id": "bundle_nscf_stage",
                "changed_files": [
                    "patches/qe_callsite_offload_hooks/bundle_nscf_stage.patch",
                    "patches/qe_callsite_offload_hooks/opp_fft.patch",
                    "patches/qe_callsite_offload_hooks/opp_subspace.patch",
                ],
                "instrumentation_capabilities": {
                    "generic_bridge_hook_present": True,
                    "runtime_replacement_evidence_hook_present": True,
                    "accelerated_result_writeback_present": True,
                    "trusted_l4_replacement_precheck_passed": False,
                    "missing_declared_patch_files": [
                        "patches/qe_callsite_offload_hooks/bundle_nscf_stage.patch"
                    ],
                },
            }
        ],
    }

    report = build_bundle_harness_readiness_report(bundle_space, patch_manifest)

    row = report["rows"][0]
    assert report["status"] == "blocked"
    assert report["ready_bundle_harness_count"] == 0
    assert row["ready_for_single_workflow_bundle_harness"] is False
    assert "runtime_bridge_single_kernel_selector" in row["blockers"]
    assert "runtime_bridge_single_output_slot" in row["blockers"]
    assert "single_qe_workflow_multi_callsite_runtime_missing" in row["blockers"]
    assert "bundle_patch_file_missing" in row["blockers"]
    assert "trusted_l4_replacement_precheck_not_passed" in row["blockers"]
    assert report["deliverable_complete"] is False


def test_materialize_qe_bundle_patch_files_concatenates_member_patches(tmp_path):
    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    (patch_dir / "opp_fft.patch").write_text(
        "diff --git a/fft.f90 b/fft.f90\n"
        "--- a/fft.f90\n"
        "+++ b/fft.f90\n"
        "@@ -1 +1 @@\n"
        "-old_fft\n"
        "+new_fft\n",
        encoding="utf-8",
    )
    (patch_dir / "opp_subspace.patch").write_text(
        "diff --git a/rotate_wfc.f90 b/rotate_wfc.f90\n"
        "--- a/rotate_wfc.f90\n"
        "+++ b/rotate_wfc.f90\n"
        "@@ -1 +1 @@\n"
        "-old_rotate\n"
        "+new_rotate\n",
        encoding="utf-8",
    )
    bundle_space = {
        "search_space_hash": "bundle-space",
        "bundles": [
            {
                "bundle_id": "bundle_nscf_stage",
                "opportunity_ids": ["opp_fft", "opp_subspace"],
                "granularity": "bundle",
            }
        ],
    }

    report = materialize_qe_bundle_patch_files(
        bundle_space,
        patch_dir=patch_dir,
    )

    bundle_patch = patch_dir / "bundle_nscf_stage.patch"
    text = bundle_patch.read_text(encoding="utf-8")
    assert report["status"] == "passed"
    assert report["materialized_bundle_patch_count"] == 1
    assert report["deliverable_complete"] is False
    assert "diff --git a/fft.f90 b/fft.f90" in text
    assert "diff --git a/rotate_wfc.f90 b/rotate_wfc.f90" in text
    assert report["rows"][0]["materialized"] is True
    assert report["rows"][0]["blockers"] == []


def test_explicit_opportunity_selection_is_not_silently_rewritten():
    selected = {
        "opportunity_id": "opp_spsi",
        "workload_case_id": "case",
        "kernel": "s_psi",
    }
    alternative = {
        "opportunity_id": "opp_diag",
        "workload_case_id": "case",
        "kernel": "diagonalization",
    }
    baseline = {
        "performance_metrics": {
            "terminal_step_metrics": {
                "timers": {"c_bands": {"wall_seconds": 1.0}}
            }
        }
    }

    chosen, profile = _maybe_select_observed_opportunity(
        selected=selected,
        opportunities=[selected, alternative],
        baseline=baseline,
        allow_adjustment=False,
    )

    assert chosen["opportunity_id"] == "opp_spsi"
    assert profile["selection_adjusted_by_real_qe_profile"] is False
    assert (
        profile["selection_blocker"]
        == "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
    )


def test_trace_anchor_resolves_stale_timer_selection_blocker():
    selected = {
        "opportunity_id": "opp_subspace",
        "workload_case_id": "case",
        "kernel": "subspace_rotation",
    }
    profile = {
        "observed_timers": ["c_bands", "h_psi"],
        "initial_kernel_observed": False,
        "selection_adjusted_by_real_qe_profile": False,
        "selection_blocker": (
            "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
        ),
    }
    trace_evidence = {
        "status": "passed",
        "trace_kernel_counts": {
            "h_psi": 10,
            "subspace_rotation": 2,
        },
    }

    reconciled = _selection_profile_with_trace_anchor(
        profile,
        selected=selected,
        trace_evidence=trace_evidence,
    )

    assert reconciled["initial_kernel_observed"] is False
    assert reconciled["trace_kernel_observed"] is True
    assert reconciled["selection_trace_anchor_status"] == "observed"
    assert "selection_blocker" not in reconciled
    assert (
        reconciled["selection_blocker_resolved_by_trace"]
        == "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
    )


def test_nc_cg_spsi_workload_variant_binding_rewrites_qe_input_explicitly():
    suite = default_qe_mainflow_workload_suite(status="frozen", include_relax=True)
    case = next(row for row in suite["cases"] if row["case_id"] == "qe_si_scf_small_v1")
    opportunity = {
        "opportunity_id": "opp_qe_si_scf_small_v1_scf_s_psi",
        "workload_case_id": "qe_si_scf_small_v1",
        "kernel": "s_psi",
    }

    bound_case, profile = _apply_workload_variant_binding(
        case=case,
        opportunity=opportunity,
        workload_variant_id=SPSI_NC_CG_WORKLOAD_VARIANT_ID,
    )

    assert profile["workload_variant_applied"] is True
    assert profile["workload_variant_binding"]["target_kernel"] == "s_psi"
    assert bound_case["case_id"].endswith(SPSI_NC_CG_WORKLOAD_VARIANT_ID)
    inputs = [
        step["input"]
        for step in bound_case["baseline_sequence"]
        if isinstance(step.get("input"), str)
    ]
    assert inputs
    assert all("diagonalization = 'cg'," in text for text in inputs)
    assert "Si.pz-vbc.UPF" in inputs[0]


def test_trace_observed_callsite_supersedes_profile_timer_miss_in_blocker_report(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    opportunity = next(
        row for row in manifest["opportunities"] if row["kernel"] != "h_psi"
    )
    attempt = {
        "opportunity_id": opportunity["opportunity_id"],
        "kernel": opportunity["kernel"],
        "evidence_kind": "real_qe_l4_attempt",
        "selection_profile": {
            "selection_blocker": (
                "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
            ),
        },
        "trace_evidence": {
            "status": "passed",
            "trace_kernel_counts": {opportunity["kernel"]: 1},
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {
            "status": "passed",
            "baseline_result": {
                "gpu_runtime_context": {
                    "schema_version": "dse.qe_gpu_runtime_context.v1",
                    "gpu_available": True,
                    "nvidia_smi_available": True,
                    "gpus": ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"],
                }
            },
        },
        "patched_qe_bridge_evidence": {
            "status": "passed",
            "baseline_elapsed_seconds": 10.0,
            "patched_qe_elapsed_seconds": 20.0,
            "gem5_returncode": 0,
            "dispatch_policy": {
                "policy": "execute_command_line_shell_bridge",
                "gem5_bridge_invocation_count_on_qe_critical_path": 1,
                "gem5_bridge_launch_count_on_qe_critical_path": 1,
                "batched_request_count_per_launch": 1,
                "persistent_or_batched_dispatch_observed": False,
                "startup_overhead_amortized": False,
            },
        },
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
            "qe_consumed_accelerated_outputs": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
        },
        "accelerated_replacement": {
            "status": "passed",
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "software_fallback_on_critical_path": False,
        },
        "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.5},
    }
    attempt_path = tmp_path / "attempt.json"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")

    build_multi_probe_report(
        out_dir=tmp_path / "multi",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[attempt_path],
    )
    blocker_report = json.loads(
        (tmp_path / "multi" / "callgraph_offload_blocker_report.json").read_text()
    )
    blocker_row = next(
        row
        for row in blocker_report["blocker_rows"]
        if row["opportunity_id"] == opportunity["opportunity_id"]
    )

    assert blocker_row["observed_in_trace"] is True
    assert (
        blocker_row["primary_blocker_class"]
        == "speed_signal_non_positive_or_missing"
    )
    assert (
        "explicit_opportunity_kernel_not_observed_in_real_qe_profile"
        not in blocker_row["attempt_blockers"]
    )


def test_multi_probe_report_unpacks_multi_row_attempt_artifacts(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    selected = manifest["opportunities"][:2]
    rows_path = tmp_path / "attempt_rows.json"
    rows_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.test.rows.v1",
                "rows": [
                    {
                        "opportunity_id": row["opportunity_id"],
                        "kernel": row["kernel"],
                        "evidence_mode": "actual_compute",
                        "actual_compute_evidence": {
                            "status": "blocked",
                            "non_smoke_actual_compute_run": True,
                            "smoke_only": False,
                            "qe_consumed_accelerated_outputs": False,
                            "blockers": ["test_blocker"],
                        },
                        "value_verdict": {
                            "valuable_l4": False,
                            "value_label": "blocked",
                            "blockers": [
                                "actual_compute_full_qe_evidence_not_passed"
                            ],
                        },
                    }
                    for row in selected
                ],
            }
        ),
        encoding="utf-8",
    )

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi_rows",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[rows_path],
    )
    attempts = json.loads(
        (tmp_path / "multi_rows" / "l4_offload_attempts.json").read_text()
    )["attempts"]
    runtime_contract = json.loads(
        (tmp_path / "multi_rows" / "bundle_runtime_contract_report.json").read_text()
    )
    harness_readiness = json.loads(
        (tmp_path / "multi_rows" / "bundle_harness_readiness_report.json").read_text()
    )
    checklist = json.loads(
        (tmp_path / "multi_rows" / "prompt_to_artifact_checklist.json").read_text()
    )
    checklist_status_by_requirement = {
        row["requirement"]: row["status"] for row in checklist["checks"]
    }

    assert status["attempt_count"] == 2
    assert status["non_smoke_actual_compute_attempt_count"] == 2
    assert status["formal_workload_variant_count"] >= 1
    assert status["bundle_runtime_contract_ready_bundle_count"] == 0
    assert status["ready_bundle_harness_count"] == 0
    assert [attempt["opportunity_id"] for attempt in attempts] == [
        row["opportunity_id"] for row in selected
    ]
    assert attempts[0]["source_attempt_artifact"].endswith("#row=0")
    assert attempts[1]["source_attempt_artifact"].endswith("#row=1")
    assert runtime_contract["deliverable_complete"] is False
    assert harness_readiness["deliverable_complete"] is False
    assert harness_readiness["ready_bundle_harness_count"] == 0
    assert (
        checklist_status_by_requirement[
            "bundle runtime contract is explicit and value-neutral"
        ]
        == "passed"
    )
    assert (
        checklist_status_by_requirement[
            "bundle harness readiness keeps runtime blockers until explicit multi-kernel support"
        ]
        == "passed"
    )


def test_multi_probe_report_folds_bundle_single_workflow_status(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bundle = next(
        row
        for row in artifacts["offload_bundle_search_space.json"]["bundles"]
        if row.get("granularity") == "bundle"
        and len(row.get("opportunity_ids") or []) >= 2
    )
    opportunities = {
        row["opportunity_id"]: row for row in manifest["opportunities"]
    }
    selected = [
        opportunities[opportunity_id]
        for opportunity_id in bundle["opportunity_ids"][:2]
    ]
    rows_path = tmp_path / "l4_offload_attempt_evidence_rows.json"
    rows_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_bundle_l4_offload_attempt_rows.v1",
                "bundle_id": bundle["bundle_id"],
                "rows": [
                    {
                        "opportunity_id": row["opportunity_id"],
                        "kernel": row["kernel"],
                        "evidence_mode": "actual_compute",
                        "actual_compute_evidence": {
                            "status": "passed",
                            "non_smoke_actual_compute_run": True,
                            "smoke_only": False,
                            "qe_consumed_accelerated_outputs": True,
                            "accelerated_result_materialized_in_qe_memory": True,
                            "qe_software_kernel_execution_skipped": True,
                            "qe_kernel_work_replaced_on_critical_path": True,
                            "single_qe_workflow_bundle_run": True,
                            "single_qe_workflow_covers_full_bundle": True,
                            "blockers": [],
                        },
                        "real_l4_provenance": {
                            "status": "passed",
                            "source": "gem5_genericaccel_qe_patched",
                            "descriptor": {"status": "passed"},
                            "request_decode": {"status": "passed"},
                            "microarchitecture_execute": {"status": "passed"},
                            "completion": {"status": "passed"},
                        },
                        "correctness": {"status": "passed"},
                        "pure_qe_baseline": {
                            "status": "passed",
                            "baseline_result": {
                                "gpu_runtime_context": {
                                    "schema_version": (
                                        "dse.qe_gpu_runtime_context.v1"
                                    ),
                                    "gpu_available": True,
                                }
                            },
                        },
                        "accelerated_replacement": {
                            "status": "passed",
                            "selected_kernel": row["kernel"],
                            "target_kernel": row["kernel"],
                            "target_kernel_matches_selected": True,
                            "accelerated_results_consumed_by_qe": True,
                            "accelerated_result_materialized_in_qe_memory": True,
                            "qe_software_kernel_execution_skipped": True,
                            "qe_kernel_work_replaced_on_critical_path": True,
                            "software_fallback_on_critical_path": False,
                            "accelerated_output_data_paths": [
                                f"accelerated-{row['kernel']}.dat"
                            ],
                        },
                        "speed_signal": {
                            "status": "non_positive",
                            "speedup_vs_pure_qe": 0.99,
                            "blockers": ["positive_speed_signal_missing"],
                        },
                    }
                    for row in selected
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "dse.qe_bundle_single_workflow_actual_compute_status.v1"
                ),
                "selected_bundle_ids": [bundle["bundle_id"]],
                "selected_bundle_expanded_opportunity_count": 0,
                "attempted_count": 1,
                "single_qe_workflow_proven": True,
                "single_qe_workflow_covers_full_bundle": True,
                "non_smoke_actual_compute_attempt_count": 1,
                "actual_compute_full_qe_evidence_passed_count": 1,
                "valuable_l4_count": 0,
                "bundle_level_valuable_l4": False,
                "deliverable_complete": False,
            }
        ),
        encoding="utf-8",
    )

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi_bundle",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[rows_path],
    )
    attempts = json.loads(
        (tmp_path / "multi_bundle" / "l4_offload_attempts.json").read_text()
    )["attempts"]
    bundle_report = json.loads(
        (
            tmp_path
            / "multi_bundle"
            / "bundle_single_workflow_l4_evidence_report.json"
        ).read_text()
    )
    bundle_row = next(
        row
        for row in bundle_report["rows"]
        if row["bundle_id"] == bundle["bundle_id"]
    )
    checklist = json.loads(
        (tmp_path / "multi_bundle" / "prompt_to_artifact_checklist.json").read_text()
    )
    checklist_status_by_requirement = {
        row["requirement"]: row["status"] for row in checklist["checks"]
    }

    assert {attempt["bundle_id"] for attempt in attempts} == {bundle["bundle_id"]}
    assert status["bundle_single_workflow_campaign_status_count"] == 1
    assert status["bundle_single_workflow_l4_evidence_status"] == (
        "bundle_value_unproven"
    )
    assert status["bundle_single_workflow_bundle_level_valuable_l4_count"] == 0
    assert bundle_row["single_qe_workflow_proven"] is True
    assert bundle_row["single_qe_workflow_covers_full_bundle"] is True
    assert "bundle_single_workflow_l4_evidence_missing" not in bundle_row[
        "blockers"
    ]
    assert "bundle_member_valuable_l4_missing" in bundle_row["blockers"]
    assert (
        checklist_status_by_requirement[
            "single-QE-workflow bundle evidence is gated separately from member evidence"
        ]
        == "passed"
    )


def test_bundle_speed_diagnostics_are_value_neutral_and_end_to_end(tmp_path):
    bundle_dir = tmp_path / "bundle_run"
    bundle_dir.mkdir()
    (bundle_dir / "bundle_single_workflow_actual_compute_report.json").write_text(
        json.dumps(
            {
                "bundle_id": "bundle_runtime_supported_workload_stage_case_nscf_x",
                "target_kernels": ["fft", "subspace_rotation"],
                "target_opportunity_ids": ["opp_fft", "opp_subspace"],
                "single_qe_workflow_proven": True,
                "single_qe_workflow_covers_full_bundle": True,
                "bundle_level_valuable_l4": False,
                "baseline_elapsed_seconds": 10.0,
                "patched_qe_elapsed_seconds": 11.0,
                "pure_qe_baseline": {
                    "elapsed_seconds": 10.0,
                    "gpu_runtime_context": {"gpu_available": True},
                    "steps": [
                        {
                            "step_id": "stage_00_scf_prerequisite",
                            "elapsed_seconds": 2.0,
                            "returncode": 0,
                            "metrics": {
                                "program_wall_seconds": 2.0,
                                "timers": {"PWSCF": {"wall_seconds": 2.0}},
                            },
                        },
                        {
                            "step_id": "stage_01_nscf",
                            "elapsed_seconds": 8.0,
                            "returncode": 0,
                            "metrics": {
                                "program_wall_seconds": 8.0,
                                "timers": {
                                    "PWSCF": {"wall_seconds": 8.0},
                                    "fft": {"wall_seconds": 0.2},
                                    "cdiaghg": {"wall_seconds": 3.0},
                                },
                            },
                        },
                    ],
                },
                "patched_qe_steps": [
                    {
                        "step_id": "stage_00_scf_prerequisite",
                        "elapsed_seconds": 2.1,
                        "bridge_active_for_selected_stage": False,
                        "returncode": 0,
                        "metrics": {
                            "program_wall_seconds": 2.1,
                            "timers": {"PWSCF": {"wall_seconds": 2.1}},
                        },
                    },
                    {
                        "step_id": "stage_01_nscf",
                        "elapsed_seconds": 8.9,
                        "bridge_active_for_selected_stage": True,
                        "returncode": 0,
                        "metrics": {
                            "program_wall_seconds": 8.9,
                            "timers": {
                                "PWSCF": {"wall_seconds": 8.9},
                                "fft": {"wall_seconds": 0.4},
                                "cdiaghg": {"wall_seconds": 3.1},
                            },
                        },
                    },
                ],
                "correctness": {"status": "passed"},
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "status.json").write_text(
        json.dumps(
            {
                "selected_bundle_ids": [
                    "bundle_runtime_supported_workload_stage_case_nscf_x"
                ],
                "single_qe_workflow_proven": True,
                "single_qe_workflow_covers_full_bundle": True,
            }
        ),
        encoding="utf-8",
    )
    for kernel, invocations in {"fft": 4, "subspace_rotation": 2}.items():
        slot = bundle_dir / "bundle_runtime_slots" / kernel
        slot.mkdir(parents=True)
        (slot / "gem5_bridge_invocation_count.txt").write_text(
            str(invocations), encoding="utf-8"
        )
        (slot / "gem5_bridge_launch_count.txt").write_text("1", encoding="utf-8")
        (slot / "gem5_bridge_returncode.txt").write_text("0", encoding="utf-8")
        (slot / "runtime_kernel_evidence.json").write_text(
            json.dumps({"status": "passed"}), encoding="utf-8"
        )
    campaign_status = tmp_path / "campaign_status.json"
    campaign_status.write_text(
        json.dumps(
            {
                "status": "actual_compute_not_valuable_l4",
                "bundle_gate_status": "bundle_value_unproven",
                "selected_bundle_ids": [
                    "bundle_runtime_supported_workload_stage_case_nscf_x"
                ],
                "target_kernels": ["fft", "subspace_rotation"],
                "baseline_elapsed_seconds": 10.0,
                "patched_qe_elapsed_seconds": 11.0,
                "speed_signal": {
                    "status": "non_positive",
                    "speedup_vs_pure_qe": 10.0 / 11.0,
                    "blockers": ["positive_speed_signal_missing"],
                },
                "workload_variant_profile": {
                    "workload_variant_id": "qe_si_nscf_ultra_bandgrid_probe_v1",
                    "runtime_workload_case_id": "case__ultra",
                    "workload_variant_binding": {
                        "workload_scale_policy": "ultra_bandgrid"
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    matrix_status = tmp_path / "matrix_status.json"
    matrix_status.write_text(
        json.dumps({"source_bundle_campaign_status_artifacts": [str(campaign_status)]}),
        encoding="utf-8",
    )
    repeatability = tmp_path / "repeatability.json"
    repeatability.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "kernel": "fft",
                        "opportunity_id": "opp_fft",
                        "speed_repeatability_status": "stable_non_positive",
                        "repeatability_status": "value_gate_not_passed",
                        "speedups_vs_pure_qe": [0.98, 0.99],
                        "min_speedup_vs_pure_qe": 0.98,
                        "max_speedup_vs_pure_qe": 0.99,
                        "positive_speed_sample_count": 0,
                        "non_positive_speed_sample_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = build_bundle_speed_diagnostics_report(
        bundle_run_dir=bundle_dir,
        matrix_status_path=matrix_status,
        repeatability_report_path=repeatability,
    )

    assert report["value_claim_allowed_by_this_report"] is False
    assert report["deliverable_complete"] is False
    assert report["status"] == "speed_blocked"
    assert report["speed_summary"]["speedup_vs_pure_qe"] == 10.0 / 11.0
    assert report["speed_summary"]["seconds_to_reach_parity"] == 1.0
    assert report["stage_breakdown"][1]["step_id"] == "stage_01_nscf"
    assert report["stage_breakdown"][1]["bridge_active_for_selected_stage"] is True
    assert report["bridge_invocation_counts"][0]["gem5_bridge_invocation_count"] == 4
    assert (
        report["bridge_invocation_counts"][0]["persistent_or_batched_dispatch_observed"]
        is True
    )
    assert report["campaign_bundle_speed_sample_count"] == 1
    assert report["repeatability_rows"][0]["speed_repeatability_status"] == (
        "stable_non_positive"
    )


def test_blocker_report_distinguishes_replacement_not_consumed(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    diagonalization = next(
        row for row in manifest["opportunities"] if row["kernel"] == "diagonalization"
    )
    attempt = {
        "opportunity_id": diagonalization["opportunity_id"],
        "kernel": "diagonalization",
        "evidence_kind": "real_qe_l4_attempt",
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {
            "status": "passed",
            "baseline_result": {
                "gpu_runtime_context": {
                    "schema_version": "dse.qe_gpu_runtime_context.v1",
                    "gpu_available": True,
                    "nvidia_smi_available": True,
                    "gpus": ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"],
                }
            },
        },
        "accelerated_replacement": {
            "status": "blocked",
            "selected_kernel": "diagonalization",
            "target_kernel": "diagonalization",
            "target_kernel_matches_selected": True,
            "accelerated_results_consumed_by_qe": False,
            "software_fallback_on_critical_path": True,
            "blockers": ["accelerated_results_not_consumed_by_qe"],
        },
        "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
    }
    attempt_path = tmp_path / "attempt_not_consumed.json"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi_not_consumed",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[attempt_path],
    )
    blocker_report = json.loads(
        (
            tmp_path
            / "multi_not_consumed"
            / "callgraph_offload_blocker_report.json"
        ).read_text()
    )
    blocker_row = next(
        row
        for row in blocker_report["blocker_rows"]
        if row["opportunity_id"] == diagonalization["opportunity_id"]
    )

    assert status["target_kernel_mismatch_count"] == 0
    assert status["replacement_ready_count"] == 0
    assert blocker_row["primary_blocker_class"] == "accelerated_replacement_not_consumed"
    assert "accelerated_results_not_consumed_by_qe" in blocker_row["blockers"]


def test_patched_qe_correctness_requires_numeric_metrics_not_job_done_only():
    verdict = _physical_correctness(
        {"job_done": True},
        {"job_done": True},
    )

    assert verdict["status"] == "blocked"
    assert "correctness_numeric_metrics_missing" in verdict["blockers"]


def test_runtime_bridge_replacement_requires_consumed_trusted_l4_provenance():
    blocked = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "accelerated_results_consumed_by_qe": True,
                "software_component_model_not_l4": True,
                "l4_execution_proof": {"passed": False},
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "accelerated_results_consumed_by_qe": True,
                    "software_component_model_not_l4": True,
                }
            ],
        }
    )

    assert blocked["status"] == "blocked"
    assert blocked["accelerated_results_consumed_by_qe"] is True
    assert blocked["software_fallback_on_critical_path"] is True
    assert "runtime_software_component_model_not_l4" in blocked["blockers"]
    assert "runtime_l4_execution_proof_not_passed" in blocked["blockers"]

    old_style_claim_without_materialized_output = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_spsi_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "accelerated_output_json": {
                "schema_version": "qe.accelerated_output.spsi.v1",
                "target_kernel": "s_psi",
                "status": "passed",
                "result_sha256": "0" * 64,
                "claim_boundary": "accelerator-produced numeric digest",
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_spsi_bridge_only",
                }
            ],
        }
    )

    assert old_style_claim_without_materialized_output["status"] == "blocked"
    assert (
        "accelerated_result_materialization_not_proven"
        in old_style_claim_without_materialized_output["blockers"]
    )
    assert (
        "qe_software_kernel_execution_skip_not_proven"
        in old_style_claim_without_materialized_output["blockers"]
    )
    assert (
        old_style_claim_without_materialized_output[
            "qe_kernel_work_replaced_on_critical_path"
        ]
        is False
    )

    fallback_still_on_path = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_fft_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_fft",
                "target_kernel": "fft",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "accelerated_output_json": {
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload": {
                    "schema_version": "qe.genericaccel.kernel_numeric_output.v1",
                    "target_kernel": "fft",
                    "fft_values": [[1.0, 0.0], [0.0, 1.0]],
                    "replacement_policy": "genericaccel_cooley_tukey_fft_payload",
                },
                "output_buffer_bytes": 128,
                "output_buffer_sha256": "fft-output-sha",
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "fft",
                    "kernel_scope": "full_fft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_fft_kernel",
                }
            ],
        }
    )

    assert fallback_still_on_path["status"] == "blocked"
    assert (
        "runtime_software_fallback_on_critical_path"
        in fallback_still_on_path["blockers"]
    )
    assert fallback_still_on_path["software_fallback_on_critical_path"] is True

    output_payload_denies_fft_materialization = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_fft_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_fft",
                "target_kernel": "fft",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path": "/tmp/qe-fft-accelerated-output.json",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "fft",
                    "kernel_scope": "full_fft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-fft-accelerated-output.json",
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_fft_kernel",
                }
            ],
            "accelerated_output_json": {
                "target_kernel": "fft",
                "generic_accel_l4_bridge_completed": True,
                "qe_memory_materialization_claimed": False,
                "qe_software_fft_skipped": False,
            },
        }
    )

    assert output_payload_denies_fft_materialization["status"] == "blocked"
    assert (
        "runtime_accelerated_output_payload_denies_qe_materialization"
        in output_payload_denies_fft_materialization["blockers"]
    )
    assert (
        "runtime_accelerated_output_payload_denies_software_skip"
        in output_payload_denies_fft_materialization["blockers"]
    )
    assert (
        output_payload_denies_fft_materialization[
            "accelerated_result_materialized_in_qe_memory"
        ]
        is False
    )

    local_writeback_without_numeric_payload = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_subspace_rotation_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_subspace_rotation",
                "target_kernel": "subspace_rotation",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path": "/tmp/qe-subspace-output.json",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
                "claim_boundary": (
                    "L4 completed; QE skipped local rotate_wfc software"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "subspace_rotation",
                    "kernel_scope": "full_subspace_rotation",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-subspace-output.json",
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": (
                        "generic_accel_l4_subspace_rotation_qe_memory_writeback"
                    ),
                }
            ],
            "accelerated_output_json": {
                "target_kernel": "subspace_rotation",
                "status": "passed",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": "L4 gated QE-memory replacement",
            },
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
        }
    )

    assert local_writeback_without_numeric_payload["status"] == "blocked"
    assert (
        "runtime_accelerated_output_local_writeback_not_accelerator_numeric_payload"
        in local_writeback_without_numeric_payload["blockers"]
    )

    generic_completion_digest_without_kernel_output = (
        _runtime_bridge_replacement_summary(
            {
                "runtime_offload_provenance": {
                    "producer": "qe_diagonalization_callsite_patch",
                    "accelerated_runtime": "qe_offload_runtime",
                    "offload_target": "generic_accel_l4_diagonalization",
                    "target_kernel": "diagonalization",
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-diag-output.json",
                    "l4_execution_proof": {
                        "passed": True,
                        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                    },
                    "claim_boundary": (
                        "L4 completed; QE skipped local diagonalization software"
                    ),
                },
                "runtime_kernel_evidence": [
                    {
                        "kernel_id": "diagonalization",
                        "kernel_scope": "full_diagonalization",
                        "accelerated_results_consumed_by_qe": True,
                        "qe_kernel_work_replaced_on_critical_path": True,
                        "accelerated_result_materialized_in_qe_memory": True,
                        "qe_software_kernel_execution_skipped": True,
                        "software_fallback_on_critical_path": False,
                        "accelerated_output_data_path": "/tmp/qe-diag-output.json",
                        "source": (
                            "generic_accel_l4_diagonalization_qe_memory_writeback"
                        ),
                    }
                ],
                "accelerated_output_json": {
                    "target_kernel": "diagonalization",
                    "status": "passed",
                    "accelerator_numeric_payload_kind": (
                        "genericaccel_completion_result_json_digest"
                    ),
                    "payload_sha256": "abc123",
                    "result_sha256": "abc123",
                    "payload_bytes": 1024,
                    "sample_values": [104, 1],
                    "numeric_payload": {
                        "completion_cycles": 104,
                        "driver_iteration_count": 1,
                    },
                    "matrix_digest": (
                        "diagonalization_genericaccel_stdout_sha256:abc123"
                    ),
                    "qe_memory_writeback_materialized": True,
                    "software_kernel_execution_skipped": True,
                    "claim_boundary": (
                        "GenericAccel completion metadata is visible to QE"
                    ),
                },
                "gem5_returncode": 0,
                "driver_status_observed": True,
                "result_prefix_passed": True,
                "markers": {
                    "descriptor_read": True,
                    "request_decode": True,
                    "microarchitecture_execute": True,
                    "completion_writeback": True,
                },
            }
        )
    )

    assert generic_completion_digest_without_kernel_output["status"] == "blocked"
    assert (
        generic_completion_digest_without_kernel_output[
            "accelerated_output_payload_numeric_data_present"
        ]
        is False
    )
    assert (
        "runtime_accelerated_output_local_writeback_not_accelerator_numeric_payload"
        in generic_completion_digest_without_kernel_output["blockers"]
    )

    zero_force_writeback_without_numeric_payload = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_forces_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_forces",
                "target_kernel": "forces",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path": "/tmp/qe-forces-output.json",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
                "claim_boundary": (
                    "L4 gated zero-force replacement; QE skipped local forces"
                ),
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "forces",
                    "kernel_scope": "full_forces",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-forces-output.json",
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_forces_zero_force_writeback",
                    "force_vector_policy": "zero_force_writeback",
                }
            ],
            "accelerated_output_json": {
                "target_kernel": "forces",
                "status": "passed",
                "force_vector_policy": "zero_force_writeback",
                "qe_memory_writeback_materialized": True,
                "software_kernel_execution_skipped": True,
                "claim_boundary": "L4 gated zero-force replacement",
            },
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
        }
    )

    assert zero_force_writeback_without_numeric_payload["status"] == "blocked"
    assert (
        "runtime_accelerated_output_local_writeback_not_accelerator_numeric_payload"
        in zero_force_writeback_without_numeric_payload["blockers"]
    )

    trusted = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_hpsi",
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "accelerated_output_data_path": "/tmp/qe-diag-accelerated-output.bin",
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                        "full_kernel_recomputed": True,
                        "accelerated_results_consumed_by_qe": True,
                        "qe_kernel_work_replaced_on_critical_path": True,
                        "accelerated_result_materialized_in_qe_memory": True,
                        "qe_software_kernel_execution_skipped": True,
                        "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_hpsi_kernel",
                }
            ],
        }
    )

    assert trusted["status"] == "passed"
    assert trusted["target_kernel"] == "h_psi"
    assert trusted["software_fallback_on_critical_path"] is False

    trusted_non_hpsi = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "full_kernel_recomputed": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                        "full_kernel_recomputed": True,
                        "accelerated_results_consumed_by_qe": True,
                        "qe_kernel_work_replaced_on_critical_path": True,
                        "accelerated_result_materialized_in_qe_memory": True,
                        "qe_software_kernel_execution_skipped": True,
                        "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_spsi_kernel",
                }
            ],
        }
    )

    assert trusted_non_hpsi["status"] == "passed"
    assert trusted_non_hpsi["target_kernel"] == "s_psi"

    trusted_diagonalization = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_diagonalization_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_diagonalization",
                "target_kernel": "diagonalization",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "accelerated_output_json": {
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload": {
                    "schema_version": "qe.genericaccel.kernel_numeric_output.v1",
                    "target_kernel": "diagonalization",
                    "eigenvalues": [0.0, 1.0],
                    "eigenvectors": [[1.0, 0.0], [0.0, 1.0]],
                    "replacement_policy": "genericaccel_jacobi_eigensolver_payload",
                },
                "output_buffer_bytes": 128,
                "output_buffer_sha256": "diag-output-sha",
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "diagonalization",
                    "kernel_scope": "full_diagonalization",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "accelerated_output_data_path": "/tmp/qe-diag-accelerated-output.bin",
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_diagonalization_kernel",
                }
            ],
        }
    )

    assert trusted_diagonalization["status"] == "passed"
    assert trusted_diagonalization["target_kernel"] == "diagonalization"

    marker_only_fft_without_output_path = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_fft_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_fft",
                "target_kernel": "fft",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "QE_OFFLOAD_FFT_ACCELERATED_WRITEBACK": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "accelerated_output_json": {
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload": {
                    "schema_version": "qe.genericaccel.kernel_numeric_output.v1",
                    "target_kernel": "fft",
                    "fft_values": [[1.0, 0.0], [0.0, 1.0]],
                    "replacement_policy": "genericaccel_cooley_tukey_fft_payload",
                },
                "output_buffer_bytes": 128,
                "output_buffer_sha256": "fft-output-sha",
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "fft",
                    "kernel_scope": "full_fft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "QE_OFFLOAD_FFT_ACCELERATED_WRITEBACK": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_fft_kernel",
                }
            ],
        }
    )

    assert marker_only_fft_without_output_path["status"] == "blocked"
    assert (
        "runtime_accelerated_output_data_path_missing"
        in marker_only_fft_without_output_path["blockers"]
    )

    trusted_fft = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_fft_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_fft",
                "target_kernel": "fft",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "software_fallback_on_critical_path": False,
                "accelerated_output_data_path": "/tmp/qe-fft-accelerated-output.bin",
                "QE_OFFLOAD_FFT_ACCELERATED_WRITEBACK": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "accelerated_output_json": {
                "accelerator_numeric_payload_kind": (
                    "genericaccel_kernel_numeric_output_json"
                ),
                "numeric_payload": {
                    "schema_version": "qe.genericaccel.kernel_numeric_output.v1",
                    "target_kernel": "fft",
                    "fft_values": [[1.0, 0.0], [0.0, 1.0]],
                    "replacement_policy": "genericaccel_cooley_tukey_fft_payload",
                },
                "output_buffer_bytes": 128,
                "output_buffer_sha256": "fft-output-sha",
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "fft",
                    "kernel_scope": "full_fft",
                    "full_kernel_recomputed": True,
                    "qe_mainflow_integrated": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                    "accelerated_output_data_path": "/tmp/qe-fft-accelerated-output.bin",
                    "QE_OFFLOAD_FFT_ACCELERATED_WRITEBACK": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_fft_kernel",
                }
            ],
        }
    )

    assert trusted_fft["status"] == "passed"
    assert trusted_fft["target_kernel"] == "fft"
    assert trusted_fft["accelerated_output_data_path_present"] is True
    assert trusted_fft["accelerated_output_data_paths"] == [
        "/tmp/qe-fft-accelerated-output.bin"
    ]

    wrong_kernel = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "full_kernel_recomputed": True,
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_hpsi_kernel",
                }
            ],
        }
    )

    assert wrong_kernel["status"] == "blocked"
    assert wrong_kernel["target_kernel"] == "s_psi"
    assert (
        "runtime_target_kernel_full_recomputed_evidence_missing:s_psi"
        in wrong_kernel["blockers"]
    )

    missing_transport_harness = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "full_kernel_recomputed": True,
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {"passed": True},
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_spsi_kernel",
                }
            ],
        }
    )

    assert missing_transport_harness["status"] == "blocked"
    assert (
        "runtime_l4_execution_proof_missing_transport_harness"
        in missing_transport_harness["blockers"]
    )

    missing_top_level_markers = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "qe_spsi_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_spsi_kernel",
                }
            ],
            "gem5_returncode": 0,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": False,
                "completion_writeback": False,
            },
            "driver_status_observed": False,
            "result_prefix_passed": False,
        }
    )
    assert missing_top_level_markers["status"] == "blocked"
    assert (
        "runtime_top_level_gem5_bridge_markers_not_passed"
        in missing_top_level_markers["blockers"]
    )


def test_replacement_readiness_consumption_count_is_strict_not_raw_observed():
    matrix = {
        "rows": [
            {
                "opportunity_id": "opp_fft",
                "kernel": "fft",
                "stage_type": "nscf",
                "evidence_present": True,
                "value_label": "not_valuable_l4",
                "blockers": ["accelerated_result_materialization_not_proven"],
            }
        ],
        "valuable_l4_count": 0,
    }
    attempt = {
        "opportunity_id": "opp_fft",
        "kernel": "fft",
        "accelerated_replacement": {
            "status": "blocked",
            "selected_kernel": "fft",
            "target_kernel": "fft",
            "target_kernel_matches_selected": True,
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "software_fallback_on_critical_path": False,
            "blockers": [
                "accelerated_result_materialization_not_proven",
                "qe_software_kernel_execution_skip_not_proven",
            ],
        },
    }

    report = build_accelerated_replacement_readiness_report(matrix, [attempt])
    row = report["rows"][0]

    assert row["accelerated_results_consumed_by_qe"] is False
    assert (
        row["accelerated_results_observed_by_qe_before_strict_replacement"]
        is True
    )
    assert report["accelerated_results_consumed_by_qe_count"] == 0
    assert (
        report[
            "accelerated_results_observed_by_qe_before_strict_replacement_count"
        ]
        == 1
    )
    assert report["replacement_ready_count"] == 0

    declared_only = _runtime_bridge_replacement_summary(
        {
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_hpsi",
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "accelerated_results_consumed_by_qe": True,
                }
            ],
        }
    )

    assert declared_only["status"] == "blocked"
    assert "runtime_full_kernel_recomputed_evidence_missing" in declared_only["blockers"]
    assert "runtime_kernel_evidence_missing_error_metric:0" in declared_only["blockers"]


def test_replacement_readiness_rejects_non_spsi_marker_only_writeback():
    matrix = {
        "rows": [
            {
                "opportunity_id": "opp_fft_marker_only",
                "kernel": "fft",
                "stage_type": "nscf",
                "evidence_present": True,
                "value_label": "not_valuable_l4",
                "blockers": [],
            },
            {
                "opportunity_id": "opp_fft_with_output_path",
                "kernel": "fft",
                "stage_type": "nscf",
                "evidence_present": True,
                "value_label": "not_valuable_l4",
                "blockers": [],
            },
        ],
        "valuable_l4_count": 0,
    }
    marker_only_replacement = {
        "status": "passed",
        "selected_kernel": "fft",
        "target_kernel": "fft",
        "target_kernel_matches_selected": True,
        "accelerated_results_consumed_by_qe": True,
        "accelerated_result_materialized_in_qe_memory": True,
        "qe_software_kernel_execution_skipped": True,
        "qe_kernel_work_replaced_on_critical_path": True,
        "software_fallback_on_critical_path": False,
        "blockers": [],
    }
    report = build_accelerated_replacement_readiness_report(
        matrix,
        [
            {
                "opportunity_id": "opp_fft_marker_only",
                "kernel": "fft",
                "accelerated_replacement": marker_only_replacement,
            },
            {
                "opportunity_id": "opp_fft_with_output_path",
                "kernel": "fft",
                "accelerated_replacement": {
                    **marker_only_replacement,
                    "accelerated_output_data_path": (
                        "/tmp/qe-fft-accelerated-output.bin"
                    ),
                },
            },
        ],
    )
    rows = {row["opportunity_id"]: row for row in report["rows"]}

    marker_only = rows["opp_fft_marker_only"]
    with_output_path = rows["opp_fft_with_output_path"]
    assert marker_only["ready_for_value_gate"] is False
    assert marker_only["accelerated_replacement_status"] == "blocked"
    assert marker_only["accelerated_replacement_output_data_path_present"] is False
    assert (
        "accelerated_replacement_output_data_path_missing"
        in marker_only["replacement_blockers"]
    )
    assert with_output_path["ready_for_value_gate"] is True
    assert with_output_path["accelerated_replacement_status"] == "passed"
    assert (
        with_output_path["accelerated_replacement_output_data_path_present"] is True
    )
    assert report["replacement_ready_count"] == 1
    assert report["non_hpsi_non_spsi_replacement_ready_count"] == 1
    assert report["non_hpsi_non_spsi_replacement_blocked_count"] == 1


def test_value_matrix_rejects_non_spsi_marker_only_replacement_value():
    manifest = {
        "opportunities": [
            {
                "opportunity_id": "opp_fft_marker_only",
                "kernel": "fft",
                "stage_type": "nscf",
            },
            {
                "opportunity_id": "opp_fft_with_output_path",
                "kernel": "fft",
                "stage_type": "nscf",
            },
            {
                "opportunity_id": "opp_fft_with_output_payload",
                "kernel": "fft",
                "stage_type": "nscf",
            },
        ]
    }
    base_evidence = {
        "kernel": "fft",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "evidence_mode": EVIDENCE_MODE_ACTUAL_COMPUTE,
            "actual_compute_evidence": {
                "status": "passed",
                "smoke_only": False,
                "non_smoke_actual_compute_run": True,
                "qe_consumed_accelerated_outputs": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
            },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "selected_kernel": "fft",
            "target_kernel": "fft",
            "target_kernel_matches_selected": True,
            "accelerated_results_consumed_by_qe": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "software_fallback_on_critical_path": False,
        },
        "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 1.2},
    }
    matrix = build_offload_value_l4_evidence_matrix(
        manifest,
        [
            {
                **base_evidence,
                "opportunity_id": "opp_fft_marker_only",
            },
            {
                **base_evidence,
                "opportunity_id": "opp_fft_with_output_path",
                "accelerated_replacement": {
                    **base_evidence["accelerated_replacement"],
                    "accelerated_output_data_path": (
                        "/tmp/qe-fft-accelerated-output.bin"
                    ),
                },
            },
            {
                **base_evidence,
                "opportunity_id": "opp_fft_with_output_payload",
                "accelerated_replacement": {
                    **base_evidence["accelerated_replacement"],
                    "accelerated_output_data_path": (
                        "/tmp/qe-fft-accelerated-output.bin"
                    ),
                    "accelerated_output_payload_numeric_data_present": True,
                },
            },
        ],
    )
    rows = {row["opportunity_id"]: row for row in matrix["rows"]}

    assert rows["opp_fft_marker_only"]["valuable_l4"] is False
    assert rows["opp_fft_marker_only"]["value_label"] == "not_valuable_l4"
    assert (
        "accelerated_replacement_output_data_path_missing"
        in rows["opp_fft_marker_only"]["blockers"]
    )
    assert rows["opp_fft_with_output_path"]["valuable_l4"] is False
    assert rows["opp_fft_with_output_path"]["value_label"] == "not_valuable_l4"
    assert (
        "accelerated_replacement_numeric_payload_missing_for_non_identity_target"
        in rows["opp_fft_with_output_path"]["blockers"]
    )
    assert rows["opp_fft_with_output_payload"]["valuable_l4"] is True
    assert rows["opp_fft_with_output_payload"]["value_label"] == "valuable_l4"
    assert matrix["valuable_l4_count"] == 1


def test_replacement_report_exposes_non_spsi_strict_replacement_queue():
    matrix = {
        "rows": [
            {
                "opportunity_id": "opp_spsi",
                "kernel": "s_psi",
                "stage_type": "nscf",
                "evidence_present": True,
                "value_label": "valuable_l4",
                "blockers": [],
            },
            {
                "opportunity_id": "opp_fft",
                "kernel": "fft",
                "stage_type": "nscf",
                "evidence_present": True,
                "value_label": "not_valuable_l4",
                "blockers": [
                    "accelerated_result_materialization_not_proven",
                    "qe_software_kernel_execution_skip_not_proven",
                    "qe_kernel_work_replacement_not_proven",
                ],
            },
        ],
        "valuable_l4_count": 1,
    }
    attempts = [
        {
            "opportunity_id": "opp_spsi",
            "kernel": "s_psi",
            "speed_signal": {"status": "passed", "speedup_vs_pure_qe": 1.01},
            "accelerated_replacement": {
                "status": "passed",
                "selected_kernel": "s_psi",
                "target_kernel": "s_psi",
                "target_kernel_matches_selected": True,
                "accelerated_results_consumed_by_qe": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "software_fallback_on_critical_path": False,
                "blockers": [],
            },
        },
        {
            "opportunity_id": "opp_fft",
            "kernel": "fft",
            "speed_signal": {
                "status": "passed",
                "speedup_vs_pure_qe": 0.91,
                "baseline_elapsed_seconds": 10.0,
                "patched_qe_elapsed_seconds": 11.0,
            },
            "accelerated_replacement": {
                "status": "blocked",
                "selected_kernel": "fft",
                "target_kernel": "fft",
                "target_kernel_matches_selected": True,
                "accelerated_results_consumed_by_qe": True,
                "software_fallback_on_critical_path": False,
                "blockers": [
                    "accelerated_result_materialization_not_proven",
                    "qe_software_kernel_execution_skip_not_proven",
                ],
            },
        },
    ]

    report = build_accelerated_replacement_readiness_report(matrix, attempts)

    assert report["replacement_ready_count"] == 1
    assert report["non_hpsi_non_spsi_replacement_ready_count"] == 0
    assert report["non_hpsi_non_spsi_replacement_blocked_count"] == 1
    assert report["next_non_hpsi_non_spsi_replacement_targets"]
    fft_target = report["next_non_hpsi_non_spsi_replacement_targets"][0]
    assert fft_target["opportunity_id"] == "opp_fft"
    assert fft_target["kernel"] == "fft"
    assert fft_target["speedup_vs_pure_qe"] == 0.91
    assert (
        "not valuable_l4 until strict runtime replacement"
        in fft_target["claim_boundary"]
    )


def test_attempt_evidence_blocks_runtime_replacement_target_mismatch(tmp_path):
    row = _build_attempt_evidence(
        opportunity={
            "opportunity_id": "opp_qe_si_scf_small_v1_scf_diagonalization",
            "kernel": "diagonalization",
            "stage_type": "scf",
            "callsite_id": "callsite_diag",
        },
        baseline={
            "status": "passed",
            "elapsed_seconds": 2.0,
            "qe_command": ["pw.x", "-in", "scf.in"],
            "gpu_runtime_context": {
                "schema_version": "dse.qe_gpu_runtime_context.v1",
                "gpu_available": True,
                "nvidia_smi_available": True,
                "gpus": ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"],
            },
        },
        gem5_preflight={"can_call_real_adapter": True, "blockers": []},
        out_dir=tmp_path,
        selection_profile={},
        trace_evidence={
            "status": "passed",
            "trace_kernel_counts": {"diagonalization": 1},
        },
        gem5_transport=None,
        patched_bridge={
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "correctness": {"status": "passed", "blockers": []},
            "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
            "runtime_offload_provenance": {
                "producer": "gem5_genericaccel_qe_kernel",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_hpsi",
                "target_kernel": "h_psi",
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_hpsi_kernel",
                }
            ],
            "blockers": [],
        },
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
    )

    assert row["accelerated_replacement"]["target_kernel"] == "h_psi"
    assert row["accelerated_replacement"]["selected_kernel"] == "diagonalization"
    assert row["accelerated_replacement"]["target_kernel_matches_selected"] is False
    assert row["accelerated_replacement"]["status"] == "blocked"
    assert (
        "runtime_replacement_target_kernel_mismatch:diagonalization:h_psi"
        in row["blockers"]
    )
    assert row["value_verdict"]["valuable_l4"] is False
    assert "accelerated_replacement_not_passed" in row["value_verdict"]["blockers"]


def test_actual_compute_attempt_requires_non_smoke_qe_consumed_replacement(tmp_path):
    row = _build_attempt_evidence(
        opportunity={
            "opportunity_id": "opp_qe_si_scf_small_v1_scf_s_psi",
            "kernel": "s_psi",
            "stage_type": "scf",
            "callsite_id": "callsite_spsi",
        },
        baseline={
            "status": "passed",
            "elapsed_seconds": 2.0,
            "qe_command": ["pw.x", "-in", "scf.in"],
            "gpu_runtime_context": {
                "schema_version": "dse.qe_gpu_runtime_context.v1",
                "gpu_available": True,
                "nvidia_smi_available": True,
                "gpus": ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"],
            },
        },
        gem5_preflight={"can_call_real_adapter": True, "blockers": []},
        out_dir=tmp_path,
        selection_profile={},
        trace_evidence={
            "status": "blocked",
            "blockers": ["trace_probe_timeout_after_target_observed"],
            "trace_kernel_counts": {"s_psi": 1},
        },
        gem5_transport=None,
        patched_bridge={
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "correctness": {"status": "passed", "blockers": []},
            "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
            "runtime_offload_provenance": {
                "producer": "qe_spsi_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_spsi",
                "target_kernel": "s_psi",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_spsi_numeric_output",
                }
            ],
            "blockers": [],
        },
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        evidence_mode=EVIDENCE_MODE_ACTUAL_COMPUTE,
    )

    assert row["evidence_kind"] == "real_qe_l4"
    assert row["evidence_scope"] == "full_qe_actual_compute"
    assert row["actual_compute_evidence"]["status"] == "passed"
    assert row["actual_compute_evidence"]["smoke_only"] is False
    assert row["actual_compute_evidence"]["qe_consumed_accelerated_outputs"] is True
    assert (
        row["actual_compute_evidence"]["qe_kernel_work_replaced_on_critical_path"]
        is True
    )
    assert row["actual_compute_evidence"]["blockers"] == []
    assert row["baseline_gpu_runtime_context"]["gpu_available"] is True
    assert (
        row["pure_qe_baseline"]["gpu_runtime_context"]["nvidia_smi_available"]
        is True
    )
    assert row["trace_target_observed"] is True
    assert "smoke_dataflow_only_not_actual_compute" not in row["value_verdict"]["blockers"]
    assert "actual_compute_full_qe_evidence_not_passed" not in row["value_verdict"]["blockers"]
    assert row["value_verdict"]["valuable_l4"] is True
    assert row["value_verdict"]["deliverable_complete"] is False


def test_actual_compute_attempt_separates_raw_observed_from_strict_consumption(tmp_path):
    row = _build_attempt_evidence(
        opportunity={
            "opportunity_id": "opp_qe_si_relax_forces_v1_relax_mix_rho",
            "kernel": "mix_rho",
            "stage_type": "relax",
            "callsite_id": "callsite_mix_rho",
        },
        baseline={
            "status": "passed",
            "elapsed_seconds": 2.0,
            "qe_command": ["pw.x", "-in", "si_relax.in"],
        },
        gem5_preflight={"can_call_real_adapter": True, "blockers": []},
        out_dir=tmp_path,
        selection_profile={},
        trace_evidence={
            "status": "passed",
            "trace_kernel_counts": {"mix_rho": 1},
        },
        gem5_transport=None,
        patched_bridge={
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "correctness": {"status": "passed", "blockers": []},
            "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
            "runtime_offload_provenance": {
                "producer": "qe_mix_rho_callsite_patch",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "generic_accel_l4_mix_rho",
                "target_kernel": "mix_rho",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "software_fallback_on_critical_path": False,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "runtime_kernel_evidence": [
                {
                    "kernel_id": "mix_rho",
                    "kernel_scope": "full_density_residual_mixing",
                    "full_kernel_recomputed": True,
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": False,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                    "source": "generic_accel_l4_mix_rho_kernel",
                }
            ],
            "blockers": [],
        },
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
        evidence_mode=EVIDENCE_MODE_ACTUAL_COMPUTE,
    )

    actual = row["actual_compute_evidence"]
    assert actual["status"] == "blocked"
    assert actual["qe_consumed_accelerated_outputs"] is False
    assert actual["raw_accelerated_results_observed_by_qe"] is True
    assert (
        actual["raw_accelerated_results_observed_before_strict_replacement"]
        is True
    )
    assert "accelerated_result_materialization_not_proven" in actual["blockers"]
    assert "qe_software_kernel_execution_skip_not_proven" in actual["blockers"]
    assert "accelerated_replacement_not_passed" in row["value_verdict"]["blockers"]
    assert row["value_verdict"]["valuable_l4"] is False


def test_actual_compute_matrix_tracks_non_spsi_kernel_attempt_diversity(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    manifest = artifacts["offload_opportunity_manifest.json"]
    spsi = next(row for row in manifest["opportunities"] if row["kernel"] == "s_psi")
    diagonalization = next(
        row for row in manifest["opportunities"] if row["kernel"] == "diagonalization"
    )

    common_l4 = {
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
    }
    matrix = build_offload_value_l4_evidence_matrix(
        manifest,
        [
            {
                **common_l4,
                "opportunity_id": spsi["opportunity_id"],
                "kernel": "s_psi",
                "evidence_mode": EVIDENCE_MODE_ACTUAL_COMPUTE,
                "evidence_kind": "real_qe_l4",
                "evidence_scope": "full_qe_actual_compute",
                "actual_compute_evidence": {
                    "status": "passed",
                    "smoke_only": False,
                    "non_smoke_actual_compute_run": True,
                    "qe_consumed_accelerated_outputs": True,
                },
                "accelerated_replacement": {
                    "status": "passed",
                    "accelerated_results_consumed_by_qe": True,
                    "qe_kernel_work_replaced_on_critical_path": True,
                    "accelerated_result_materialized_in_qe_memory": True,
                    "qe_software_kernel_execution_skipped": True,
                    "software_fallback_on_critical_path": False,
                },
                "speed_signal": {
                    "status": "non_positive",
                    "speedup_vs_pure_qe": 0.5,
                },
            },
            {
                **common_l4,
                "opportunity_id": diagonalization["opportunity_id"],
                "kernel": "diagonalization",
                "evidence_mode": EVIDENCE_MODE_ACTUAL_COMPUTE,
                "evidence_kind": "real_qe_l4_attempt",
                "evidence_scope": "full_qe_actual_compute_blocked",
                "actual_compute_evidence": {
                    "status": "blocked",
                    "smoke_only": False,
                    "non_smoke_actual_compute_run": True,
                    "qe_consumed_accelerated_outputs": False,
                },
                "accelerated_replacement": {
                    "status": "blocked",
                    "accelerated_results_consumed_by_qe": False,
                    "software_fallback_on_critical_path": True,
                },
                "speed_signal": {
                    "status": "non_positive",
                    "speedup_vs_pure_qe": 0.3,
                },
            },
        ],
    )

    assert matrix["non_smoke_actual_compute_attempt_count"] == 2
    assert matrix["actual_compute_attempted_kernel_count"] == 2
    assert matrix["actual_compute_attempted_kernels"] == [
        "diagonalization",
        "s_psi",
    ]
    assert matrix["actual_compute_attempted_kernel_counts"] == {
        "diagonalization": 1,
        "s_psi": 1,
    }
    assert matrix["non_hpsi_actual_compute_attempt_count"] == 2
    assert matrix["non_hpsi_non_spsi_actual_compute_attempt_count"] == 1
    assert matrix["non_hpsi_non_spsi_actual_compute_blocked_count"] == 1
    assert matrix["actual_compute_full_qe_evidence_passed_count"] == 1
    assert matrix["actual_compute_full_qe_evidence_blocked_count"] == 1
    assert matrix["actual_compute_not_valuable_l4_count"] == 1
    assert matrix["valuable_l4_count"] == 0
    assert matrix["smoke_value_allowed"] is False


def test_bundle_target_actual_compute_rows_are_visible_to_value_matrix(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    manifest = artifacts["offload_opportunity_manifest.json"]
    fft = next(row for row in manifest["opportunities"] if row["kernel"] == "fft")

    row = _target_attempt_evidence_row(
        target_result={
            "kernel": "fft",
            "status": "passed",
            "gem5_returncode": 0,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "driver_iteration_count": 3,
            "completion_writeback_count": 3,
            "bridge_script": str(tmp_path / "run_gem5_bridge.sh"),
            "blockers": [],
            "replacement_summary": {
                "status": "passed",
                "target_kernel": "fft",
                "accelerated_results_consumed_by_qe": True,
                "accelerated_result_materialized_in_qe_memory": True,
                "accelerated_output_written_to_qe_buffer": True,
                "qe_software_kernel_execution_skipped": True,
                "qe_kernel_work_replaced_on_critical_path": True,
                "accelerated_kernel_work_removed_from_critical_path": True,
                "accelerated_output_data_path_present": True,
                "accelerated_output_data_paths": [
                    str(tmp_path / "accelerated_output_values.dat")
                ],
                "accelerated_output_payload_numeric_data_present": True,
                "software_fallback_on_critical_path": False,
                "runtime_l4_execution_proof_passed": True,
                "blockers": [],
            },
        },
        target={"opportunity": fft, "kernel": "fft"},
        baseline={
            "status": "passed",
            "qe_command": ["pw.x", "-in", "si_nscf.in"],
            "gpu_runtime_context": {"gpu_available": True},
        },
        trace_evidence={"status": "passed"},
        gem5_preflight={"can_call_real_adapter": True},
        correctness={"status": "passed"},
        speed_signal={
            "status": "non_positive",
            "speedup_vs_pure_qe": 0.97,
            "blockers": ["positive_speed_signal_missing"],
        },
        actual_compute_passed=True,
        bundle_id="bundle_runtime_supported_workload_stage_qe_si_nscf_bandgrid_v1_nscf_a7733ff1",
        full_bundle_target_coverage=True,
        out_dir=tmp_path,
    )

    assert row["evidence_mode"] == EVIDENCE_MODE_ACTUAL_COMPUTE
    assert row["actual_compute_evidence"]["status"] == "passed"
    assert row["actual_compute_evidence"]["smoke_only"] is False
    assert row["actual_compute_evidence"]["single_qe_workflow_bundle_run"] is True
    assert row["value_verdict"]["valuable_l4"] is False
    assert "positive_speed_signal_missing" in row["value_verdict"]["blockers"]

    matrix = build_offload_value_l4_evidence_matrix(manifest, [row])
    assert matrix["non_smoke_actual_compute_attempt_count"] == 1
    assert matrix["actual_compute_attempted_kernels"] == ["fft"]
    assert matrix["actual_compute_full_qe_evidence_passed_count"] == 1
    assert matrix["actual_compute_not_valuable_l4_count"] == 1
    assert matrix["valuable_l4_count"] == 0
    fft_row = next(
        item for item in matrix["rows"] if item["opportunity_id"] == fft["opportunity_id"]
    )
    assert fft_row["value_label"] == "not_valuable_l4"

    partial_positive_row = {
        **row,
        "single_qe_workflow_covers_full_bundle": False,
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.01,
            "blockers": [],
        },
        "actual_compute_evidence": {
            **row["actual_compute_evidence"],
            "single_qe_workflow_covers_full_bundle": False,
        },
    }
    partial_verdict = classify_l4_offload_value(partial_positive_row)
    assert partial_verdict["valuable_l4"] is False
    assert partial_verdict["value_label"] == "not_valuable_l4"
    assert (
        "single_qe_workflow_does_not_cover_full_bundle"
        in partial_verdict["blockers"]
    )


def test_actual_compute_matrix_does_not_count_marker_only_consumption(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    manifest = artifacts["offload_opportunity_manifest.json"]
    spsi = next(row for row in manifest["opportunities"] if row["kernel"] == "s_psi")

    matrix = build_offload_value_l4_evidence_matrix(
        manifest,
        [
            {
                "opportunity_id": spsi["opportunity_id"],
                "kernel": "s_psi",
                "evidence_mode": EVIDENCE_MODE_ACTUAL_COMPUTE,
                "evidence_kind": "real_qe_l4",
                "evidence_scope": "full_qe_actual_compute",
                "actual_compute_evidence": {
                    "status": "passed",
                    "smoke_only": False,
                    "non_smoke_actual_compute_run": True,
                    "qe_consumed_accelerated_outputs": True,
                },
                "real_l4_provenance": {
                    "status": "passed",
                    "source": "gem5_genericaccel_qe_patched",
                    "descriptor": {"status": "passed"},
                    "request_decode": {"status": "passed"},
                    "microarchitecture_execute": {"status": "passed"},
                    "completion": {"status": "passed"},
                },
                "correctness": {"status": "passed"},
                "pure_qe_baseline": {"status": "passed"},
                "accelerated_replacement": {
                    "status": "passed",
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": False,
                },
                "speed_signal": {
                    "status": "non_positive",
                    "speedup_vs_pure_qe": 0.9,
                },
            }
        ],
    )

    row = next(
        row for row in matrix["rows"] if row["opportunity_id"] == spsi["opportunity_id"]
    )
    assert "qe_kernel_work_replacement_not_proven" in row["blockers"]
    assert matrix["non_smoke_actual_compute_attempt_count"] == 1
    assert matrix["actual_compute_full_qe_evidence_passed_count"] == 0
    assert matrix["actual_compute_full_qe_evidence_blocked_count"] == 1


def test_multi_probe_report_normalizes_legacy_raw_marker_consumption(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(artifacts["offload_opportunity_manifest.json"]),
        encoding="utf-8",
    )
    mix_rho = next(
        row
        for row in artifacts["offload_opportunity_manifest.json"]["opportunities"]
        if row["kernel"] == "mix_rho"
    )
    legacy_attempt_path = tmp_path / "legacy_marker_only_attempt.json"
    legacy_attempt_path.write_text(
        json.dumps(
            {
                "opportunity_id": mix_rho["opportunity_id"],
                "kernel": "mix_rho",
                "evidence_mode": EVIDENCE_MODE_ACTUAL_COMPUTE,
                "evidence_kind": "real_qe_l4_attempt",
                "evidence_scope": "full_qe_actual_compute_blocked",
                "actual_compute_evidence": {
                    "status": "blocked",
                    "smoke_only": False,
                    "non_smoke_actual_compute_run": True,
                    # Legacy artifacts used this as a raw marker.  A rebuilt
                    # cumulative report must not preserve it as strict QE
                    # accelerated-output consumption.
                    "qe_consumed_accelerated_outputs": True,
                    "blockers": [
                        "accelerated_result_materialization_not_proven",
                        "qe_software_kernel_execution_skip_not_proven",
                    ],
                },
                "real_l4_provenance": {
                    "status": "passed",
                    "source": "gem5_genericaccel_qe_patched",
                    "descriptor": {"status": "passed"},
                    "request_decode": {"status": "passed"},
                    "microarchitecture_execute": {"status": "passed"},
                    "completion": {"status": "passed"},
                },
                "correctness": {"status": "passed"},
                "pure_qe_baseline": {"status": "passed"},
                "accelerated_replacement": {
                    "status": "blocked",
                    "selected_kernel": "mix_rho",
                    "target_kernel": "mix_rho",
                    "target_kernel_matches_selected": True,
                    "accelerated_results_consumed_by_qe": True,
                    "software_fallback_on_critical_path": False,
                    "blockers": [
                        "accelerated_result_materialization_not_proven",
                        "qe_software_kernel_execution_skip_not_proven",
                    ],
                },
                "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
            }
        ),
        encoding="utf-8",
    )

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[legacy_attempt_path],
    )
    attempts = json.loads(
        (tmp_path / "multi" / "l4_offload_attempts.json").read_text()
    )["attempts"]
    actual = attempts[0]["actual_compute_evidence"]
    replacement_report = json.loads(
        (
            tmp_path / "multi" / "accelerated_replacement_readiness_report.json"
        ).read_text()
    )
    bundle_viability_report = json.loads(
        (tmp_path / "multi" / "offload_bundle_viability_report.json").read_text()
    )

    assert actual["qe_consumed_accelerated_outputs"] is False
    assert actual["raw_accelerated_results_observed_by_qe"] is True
    assert (
        actual["raw_accelerated_results_observed_before_strict_replacement"]
        is True
    )
    assert status["actual_compute_full_qe_evidence_passed_count"] == 0
    assert status["actual_compute_full_qe_evidence_blocked_count"] == 1
    assert replacement_report["replacement_ready_count"] == 0
    assert (
        replacement_report[
            "accelerated_results_observed_by_qe_before_strict_replacement_count"
        ]
        == 1
    )


def test_missing_runtime_replacement_target_is_unknown_not_mismatch(tmp_path):
    row = _build_attempt_evidence(
        opportunity={
            "opportunity_id": "opp_qe_si_relax_forces_v1_relax_fft",
            "kernel": "fft",
            "stage_type": "relax",
            "callsite_id": "callsite_fft",
        },
        baseline={
            "status": "passed",
            "elapsed_seconds": 2.0,
            "qe_command": ["pw.x", "-in", "relax.in"],
        },
        gem5_preflight={"can_call_real_adapter": True, "blockers": []},
        out_dir=tmp_path,
        selection_profile={},
        trace_evidence={"status": "passed", "trace_kernel_counts": {"fft": 1}},
        gem5_transport=None,
        patched_bridge={
            "gem5_returncode": 0,
            "driver_status_observed": True,
            "result_prefix_passed": True,
            "markers": {
                "descriptor_read": True,
                "request_decode": True,
                "microarchitecture_execute": True,
                "completion_writeback": True,
            },
            "correctness": {"status": "passed", "blockers": []},
            "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.5},
            "blockers": [],
        },
        gem5_binary=tmp_path / "gem5.opt",
        gem5_config=tmp_path / "generic_accel_l4_test.py",
        gem5_driver=tmp_path / "generic_accel_l4_driver",
        simulator=tmp_path / "generic_sim",
    )

    assert row["accelerated_replacement"]["target_kernel"] is None
    assert row["accelerated_replacement"]["target_kernel_matches_selected"] is None
    assert not any(
        str(blocker).startswith("runtime_replacement_target_kernel_mismatch")
        for blocker in row["accelerated_replacement"]["blockers"]
    )


def test_nscf_fermi_energy_is_numeric_correctness_metric():
    metrics = _parse_qe_stdout(
        """
        End of band structure calculation
        the Fermi energy is     6.6066 ev
        PWSCF        :      0.13s CPU      0.22s WALL
        JOB DONE.
        """
    )
    verdict = _physical_correctness(
        {"job_done": True, "fermi_energy_ev": metrics["fermi_energy_ev"]},
        {"job_done": True, "fermi_energy_ev": metrics["fermi_energy_ev"]},
    )

    assert metrics["fermi_energy_ev"] == 6.6066
    assert verdict["status"] == "passed"
    assert verdict["metric_deltas"]["fermi_energy_ev"]["passed"] is True
    assert "correctness_numeric_metrics_missing" not in verdict["blockers"]


def test_bands_stdout_summary_can_backstop_terminal_postprocess_correctness():
    bands_metrics = _parse_qe_stdout(
        """
        End of band structure calculation
             k = 0.0000 0.0000 0.0000 (   169 PWs)   bands (ev):

          -5.543    6.405    6.405    6.405

        PWSCF        :      0.13s CPU      0.22s WALL
        JOB DONE.
        """
    )
    selected = _select_correctness_metrics(
        {"job_done": True, "timers": {"BANDS": {"wall_seconds": 0.2}}},
        [{"metrics": bands_metrics}],
    )
    verdict = _physical_correctness(selected, selected)

    assert bands_metrics["band_energy_count"] == 4
    assert bands_metrics["band_energy_min_ev"] == -5.543
    assert bands_metrics["band_energy_max_ev"] == 6.405
    assert abs(selected["band_energy_sum_ev"] - 13.672) < 1.0e-12
    assert verdict["status"] == "passed"


def test_multi_probe_report_combines_attempts_without_value_or_completion(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    opportunities = manifest["opportunities"]
    non_hpsi = next(row for row in opportunities if row["kernel"] != "h_psi")
    hpsi = next(row for row in opportunities if row["kernel"] == "h_psi")
    attempt_0 = {
        "opportunity_id": non_hpsi["opportunity_id"],
        "kernel": non_hpsi["kernel"],
        "evidence_kind": "real_qe_l4_attempt",
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {
            "status": "passed",
            "baseline_result": {
                "gpu_runtime_context": {
                    "schema_version": "dse.qe_gpu_runtime_context.v1",
                    "gpu_available": True,
                    "nvidia_smi_available": True,
                    "gpus": ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"],
                }
            },
        },
        "patched_qe_bridge_evidence": {
            "status": "passed",
            "baseline_elapsed_seconds": 10.0,
            "patched_qe_elapsed_seconds": 20.0,
            "gem5_returncode": 0,
            "dispatch_policy": {
                "policy": "execute_command_line_shell_bridge",
                "gem5_bridge_invocation_count_on_qe_critical_path": 1,
                "gem5_bridge_launch_count_on_qe_critical_path": 1,
                "batched_request_count_per_launch": 1,
                "persistent_or_batched_dispatch_observed": False,
                "startup_overhead_amortized": False,
            },
        },
        "accelerated_replacement": {
            "status": "passed",
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "software_fallback_on_critical_path": False,
        },
        "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.5},
    }
    attempt_1 = {
        "opportunity_id": hpsi["opportunity_id"],
        "kernel": hpsi["kernel"],
        "evidence_kind": "real_qe_l4_attempt",
        "real_l4_provenance": {"status": "blocked"},
        "correctness": {"status": "blocked"},
        "pure_qe_baseline": {"status": "passed"},
        "speed_signal": {"status": "blocked"},
    }
    attempt_paths = []
    for index, attempt in enumerate([attempt_0, attempt_1]):
        path = tmp_path / f"attempt_{index}.json"
        path.write_text(json.dumps(attempt), encoding="utf-8")
        attempt_paths.append(path)

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=attempt_paths,
    )
    matrix = json.loads(
        (tmp_path / "multi" / "offload_value_l4_evidence_matrix.json").read_text()
    )
    blocker_report = json.loads(
        (tmp_path / "multi" / "callgraph_offload_blocker_report.json").read_text()
    )
    speed_report = json.loads(
        (tmp_path / "multi" / "offload_speed_optimization_report.json").read_text()
    )
    replacement_report = json.loads(
        (
            tmp_path / "multi" / "accelerated_replacement_readiness_report.json"
        ).read_text()
    )
    bundle_viability_report = json.loads(
        (tmp_path / "multi" / "offload_bundle_viability_report.json").read_text()
    )
    checklist = json.loads(
        (tmp_path / "multi" / "prompt_to_artifact_checklist.json").read_text()
    )
    selection_report = json.loads(
        (tmp_path / "multi" / "offload_selection_search_report.json").read_text()
    )
    selection_report_md = (
        tmp_path / "multi" / "offload_selection_search_report.md"
    ).read_text()
    speed_report_md = (
        tmp_path / "multi" / "offload_speed_optimization_report.md"
    ).read_text()
    blocker_report_md = (
        tmp_path / "multi" / "callgraph_offload_blocker_report.md"
    ).read_text()
    replacement_report_md = (
        tmp_path / "multi" / "accelerated_replacement_readiness_report.md"
    ).read_text()
    bundle_viability_report_md = (
        tmp_path / "multi" / "offload_bundle_viability_report.md"
    ).read_text()
    checklist_md = (
        tmp_path / "multi" / "prompt_to_artifact_checklist.md"
    ).read_text()
    blocker_rows = {
        row["opportunity_id"]: row for row in blocker_report["blocker_rows"]
    }

    assert status["deliverable_complete"] is False
    assert status["valuable_l4_count"] == 0
    assert status["best_replacement_ready_speedup_vs_pure_qe"] == 0.5
    assert status["baseline_gpu_context_observed_count"] == 1
    assert status["baseline_gpu_available_count"] == 1
    assert status["qe_kernel_work_replaced_on_critical_path_count"] == 1
    assert status["replacement_ready_non_positive_speed_count"] == 1
    assert status["persistent_or_batched_dispatch_required_count"] == 1
    assert status["replacement_writeback_required_count"] == 1
    assert status["bundle_level_valuable_l4_count"] == 0
    assert status["prompt_to_artifact_checklist_status"] == checklist["status"]
    assert status["prompt_to_artifact_checklist_hash"] == checklist["checklist_hash"]
    assert (tmp_path / "multi" / "offload_target_identity_schema.json").exists()
    assert (tmp_path / "multi" / "offload_bundle_search_space.json").exists()
    assert (tmp_path / "multi" / "offload_bundle_viability_report.json").exists()
    assert (tmp_path / "multi" / "l4_offload_attempt_queue.json").exists()
    assert checklist["schema_version"] == (
        "dse.qe_callgraph_offload_prompt_to_artifact_checklist.v1"
    )
    assert checklist["status"] in {"passed", "partial_or_blocked"}
    checklist_by_requirement = {
        row["requirement"]: row for row in checklist["checks"]
    }
    assert checklist_by_requirement[
        "DSE ranks which workload/callsite/bundle to offload"
    ]["status"] == "passed"
    bundle_check = checklist_by_requirement[
        "bundle/member evidence is separated from bundle-level value"
    ]
    assert bundle_check["status"] == "passed"
    assert bundle_check["evidence"]["bundle_level_valuable_l4_count"] == 0
    assert checklist_by_requirement[
        "first pass cannot claim deliverable_complete"
    ]["status"] == "passed"
    assert checklist_by_requirement[
        "smoke/dataflow evidence cannot claim actual-compute or valuable_l4"
    ]["status"] == "passed"
    assert checklist_by_requirement[
        (
            "valuable_l4 remains gated on real L4, correctness, replacement, "
            "baseline, and positive speed"
        )
    ]["status"] == "passed"
    gpu_check = checklist_by_requirement[
        "GPU availability is baseline context, not value evidence"
    ]
    assert gpu_check["status"] == "passed"
    assert gpu_check["evidence"]["baseline_gpu_context_observed_count"] == 1
    assert gpu_check["evidence"]["baseline_gpu_available_count"] == 1
    assert checklist_by_requirement[
        (
            "IC/EDA evidence is optional side evidence and cannot substitute "
            "for QE/gem5 value"
        )
    ]["status"] == "passed"
    assert "QE callgraph offload prompt-to-artifact checklist" in checklist_md
    assert matrix["value_counts"].get("not_valuable_l4", 0) == 0
    assert matrix["value_counts"]["blocked"] == 2
    assert blocker_report["deliverable_complete"] is False
    assert speed_report["deliverable_complete"] is False
    assert speed_report["positive_speed_value_claim_allowed"] is False
    assert speed_report["bridge_fallback_cannot_claim_value"] is True
    assert speed_report["best_speedup_vs_pure_qe"] == 0.5
    assert speed_report["best_replacement_ready_speedup_vs_pure_qe"] == 0.5
    assert speed_report["baseline_gpu_context_observed_count"] == 1
    assert speed_report["baseline_gpu_available_count"] == 1
    assert speed_report["non_positive_speed_count"] == 1
    assert speed_report["blocked_speed_count"] == 1
    assert speed_report["replacement_ready_non_positive_speed_count"] == 1
    assert speed_report["persistent_or_batched_dispatch_required_count"] == 1
    assert speed_report["replacement_writeback_required_count"] == 1
    assert bundle_viability_report["deliverable_complete"] is False
    assert bundle_viability_report["bundle_level_valuable_l4_count"] == 0
    assert "QE offload bundle viability report" in bundle_viability_report_md
    speed_rows = {
        row["opportunity_id"]: row for row in speed_report["rows"]
    }
    assert speed_rows[non_hpsi["opportunity_id"]]["replacement_ready"] is True
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "persistent_or_batched_dispatch_required"
        ]
        is True
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "replacement_writeback_required_before_speed_optimization"
        ]
        is False
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]]["next_engineering_gate"]
        == "persistent_or_batched_l4_dispatch"
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]]["bridge_invocation_policy"]
        == "execute_command_line_shell_bridge"
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "gem5_bridge_invocation_count_on_qe_critical_path"
        ]
        == 1
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "gem5_bridge_launch_count_on_qe_critical_path"
        ]
        == 1
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "batched_request_count_per_launch"
        ]
        == 1
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "persistent_or_batched_dispatch_observed"
        ]
        is False
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "required_patched_elapsed_seconds_for_positive_speed"
        ]
        == 10.0
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "required_elapsed_reduction_seconds_for_positive_speed"
        ]
        == 10.0
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]][
            "required_bridge_overhead_reduction_fraction"
        ]
        == 1.0
    )
    assert (
        speed_rows[non_hpsi["opportunity_id"]]["baseline_gpu_available"]
        is True
    )
    assert (
        speed_rows[hpsi["opportunity_id"]][
            "replacement_writeback_required_before_speed_optimization"
        ]
        is True
    )
    assert (
        speed_rows[hpsi["opportunity_id"]]["next_engineering_gate"]
        == "replacement_capable_qe_writeback"
    )
    assert (
        "persistent/batched L4 dispatch"
        in speed_rows[non_hpsi["opportunity_id"]]["replacement_gap"]
    )
    assert replacement_report["deliverable_complete"] is False
    assert replacement_report["replacement_ready_count"] == 1
    assert replacement_report["accelerated_results_consumed_by_qe_count"] == 1
    assert replacement_report["qe_kernel_work_replaced_on_critical_path_count"] == 1
    assert replacement_report["replacement_blocker_count"] >= 1
    assert "QE accelerated replacement readiness report" in replacement_report_md
    assert "qe_kernel_work_replaced_on_critical_path_count: `1`" in replacement_report_md
    assert "kernel_work_replaced_on_path" in replacement_report_md
    assert "deliverable_complete: `false`" in blocker_report_md
    assert "Per-row closure actions" in blocker_report_md
    assert selection_report["deliverable_complete"] is False
    assert selection_report["ranked_opportunity_count"] == manifest["opportunity_count"]
    assert selection_report["formal_workload_variant_count"] >= 2
    assert selection_report["canonical_replacement_requires_explicit_binding"] is True
    assert selection_report["projection_only_value_allowed"] is False
    selection_rows = {
        row["opportunity_id"]: row for row in selection_report["ranked_opportunities"]
    }
    assert (
        selection_rows[non_hpsi["opportunity_id"]]["speed_measurement"][
            "speedup_vs_pure_qe"
        ]
        == 0.5
    )
    assert selection_rows[non_hpsi["opportunity_id"]]["workload_selection"][
        "selection_axes"
    ]
    spsi_row = next(row for row in manifest["opportunities"] if row["kernel"] == "s_psi")
    assert any(
        option["variant_id"] == SPSI_NC_CG_WORKLOAD_VARIANT_ID
        for option in selection_rows[spsi_row["opportunity_id"]][
            "workload_variant_options"
        ]
    )
    assert any(
        option["variant_id"] == SPSI_USPP_WORKLOAD_VARIANT_ID
        for option in selection_rows[spsi_row["opportunity_id"]][
            "workload_variant_options"
        ]
    )
    assert "QE offload selection search report" in selection_report_md
    assert "persistent_or_batched_dispatch_required_count: `1`" in speed_report_md
    assert "execute_command_line_shell_bridge" in speed_report_md
    assert "persistent_or_batched_l4_dispatch" in speed_report_md
    assert blocker_report["blocked_value_row_count"] == 2
    assert blocker_report["not_valuable_row_count"] == 0
    for row in blocker_rows.values():
        assert {
            "opportunity_id",
            "stage_type",
            "kernel",
            "value_label",
            "primary_blocker_class",
            "blockers",
            "source_attempt_artifact",
            "recommended_next_action",
            "requires_patch_artifact",
            "observed_in_trace",
            "real_l4_status",
            "correctness_status",
            "speed_status",
        } <= set(row)
    assert (
        blocker_rows[non_hpsi["opportunity_id"]]["primary_blocker_class"]
        == "actual_compute_incomplete"
    )
    assert (
        "actual_compute_full_qe_evidence_not_passed"
        in blocker_rows[non_hpsi["opportunity_id"]]["value_gate_blockers"]
    )
    assert blocker_rows[non_hpsi["opportunity_id"]]["speed_status"] == "non_positive"
    assert (
        blocker_rows[non_hpsi["opportunity_id"]]["speed_measurement"][
            "speedup_vs_pure_qe"
        ]
        == 0.5
    )
    assert (
        blocker_rows[non_hpsi["opportunity_id"]]["speed_measurement"][
            "baseline_elapsed_seconds"
        ]
        == 10.0
    )
    assert blocker_rows[non_hpsi["opportunity_id"]][
        "source_attempt_artifact"
    ].endswith("attempt_0.json")
    assert (
        blocker_rows[hpsi["opportunity_id"]]["primary_blocker_class"]
        == "real_l4_incomplete"
    )
    assert blocker_rows[hpsi["opportunity_id"]]["real_l4_status"] == "blocked"
    assert blocker_rows[hpsi["opportunity_id"]]["correctness_status"] == "blocked"
    assert blocker_rows[hpsi["opportunity_id"]]["speed_status"] == "blocked"
    assert blocker_rows[hpsi["opportunity_id"]][
        "source_attempt_artifact"
    ].endswith("attempt_1.json")


def test_cumulative_duplicate_attempt_preserves_best_replacement_evidence(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    patch_manifest_path = tmp_path / "qe_callsite_patch_manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    patch_manifest_path.write_text(
        json.dumps(artifacts["qe_callsite_patch_manifest.json"]),
        encoding="utf-8",
    )
    spsi = next(row for row in manifest["opportunities"] if row["kernel"] == "s_psi")
    common = {
        "opportunity_id": spsi["opportunity_id"],
        "kernel": "s_psi",
        "stage_type": spsi["stage_type"],
        "evidence_mode": "actual_compute",
        "evidence_scope": "full_qe_actual_compute",
        "pure_qe_baseline": {"status": "passed"},
    }
    ready_attempt = {
        **common,
        "evidence_kind": "real_qe_l4",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
            "non_smoke_actual_compute_run": True,
            "qe_consumed_accelerated_outputs": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "software_fallback_on_critical_path": False,
        },
        "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.5},
    }
    later_blocked_attempt = {
        **common,
        "evidence_kind": "real_qe_l4_attempt",
        "actual_compute_evidence": {
            "status": "blocked",
            "smoke_only": False,
            "non_smoke_actual_compute_run": True,
            "blockers": ["patched_qe_bridge_timeout"],
        },
        "real_l4_provenance": {"status": "blocked"},
        "correctness": {"status": "blocked"},
        "accelerated_replacement": {
            "status": "blocked",
            "accelerated_results_consumed_by_qe": False,
            "qe_kernel_work_replaced_on_critical_path": False,
            "software_fallback_on_critical_path": True,
        },
        "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.005},
    }
    attempt_paths = []
    for index, attempt in enumerate([ready_attempt, later_blocked_attempt]):
        path = tmp_path / f"duplicate_attempt_{index}.json"
        path.write_text(json.dumps(attempt), encoding="utf-8")
        attempt_paths.append(path)

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi_duplicate",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=attempt_paths,
        patch_manifest_path=patch_manifest_path,
    )
    matrix = json.loads(
        (
            tmp_path / "multi_duplicate" / "offload_value_l4_evidence_matrix.json"
        ).read_text()
    )
    replacement_report = json.loads(
        (
            tmp_path
            / "multi_duplicate"
            / "accelerated_replacement_readiness_report.json"
        ).read_text()
    )
    spsi_matrix_row = next(
        row for row in matrix["rows"] if row["opportunity_id"] == spsi["opportunity_id"]
    )

    assert status["attempt_count"] == 2
    assert status["actual_compute_full_qe_evidence_passed_count"] == 1
    assert status["actual_compute_full_qe_evidence_blocked_count"] == 1
    assert status["replacement_ready_count"] == 1
    assert status["qe_kernel_work_replaced_on_critical_path_count"] == 1
    assert status["valuable_l4_count"] == 0
    assert spsi_matrix_row["value_label"] == "not_valuable_l4"
    assert replacement_report["replacement_ready_count"] == 1
    assert replacement_report["qe_kernel_work_replaced_on_critical_path_count"] == 1
    spsi_replacement_row = next(
        row
        for row in replacement_report["rows"]
        if row["opportunity_id"] == spsi["opportunity_id"]
    )
    assert spsi_replacement_row["source_attempt_artifact"].endswith(
        "duplicate_attempt_0.json"
    )


def test_replacement_report_links_consumed_sidecar_evidence_but_keeps_it_blocked(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "qe_callsite_patch_manifest.json").write_text(
        json.dumps(artifacts["qe_callsite_patch_manifest.json"]),
        encoding="utf-8",
    )
    hpsi = next(row for row in manifest["opportunities"] if row["kernel"] == "h_psi")
    attempt = {
        "opportunity_id": hpsi["opportunity_id"],
        "kernel": hpsi["kernel"],
        "evidence_kind": "real_qe_l4_attempt",
        "real_l4_provenance": {"status": "passed", "source": "gem5_genericaccel_qe_patched"},
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "speed_signal": {"status": "non_positive", "speedup_vs_pure_qe": 0.5},
    }
    attempt_path = tmp_path / "attempt.json"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")
    external_evidence_path = tmp_path / "external_numeric_bundle.json"
    external_evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_accelerated_numeric_producer_evidence_bundle.v1",
                "rows": [
                    {
                        "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
                        "candidate_id": "cand",
                        "workload_case_id": hpsi["workload_case_id"],
                        "source_kind": "qe_offload_runtime",
                        "accelerated_output_status": "blocked",
                        "trusted_accelerated_numeric_source": False,
                        "offload_provenance": {
                            "full_h_psi_recomputed": True,
                            "qe_mainflow_integrated": True,
                            "accelerated_results_consumed_by_qe": True,
                            "all_observed_hpsi_calls_sidecar_consumed": True,
                            "software_component_model_not_l4": True,
                            "l4_execution_proof": {"passed": False},
                        },
                        "kernel_evidence": [
                            {
                                "kernel_id": "h_psi",
                                "kernel_scope": "full_h_psi",
                                "full_kernel_recomputed": True,
                                "accelerated_results_consumed_by_qe": True,
                                "all_observed_hpsi_calls_sidecar_consumed": True,
                                "software_component_model_not_l4": True,
                            }
                        ],
                        "blockers": [
                            "offload_provenance_marks_software_component_model_not_l4",
                            "offload_provenance_l4_execution_proof_not_passed",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    build_multi_probe_report(
        out_dir=tmp_path / "multi",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[attempt_path],
        accelerated_numeric_evidence_paths=[external_evidence_path],
    )
    replacement_report = json.loads(
        (
            tmp_path / "multi" / "accelerated_replacement_readiness_report.json"
        ).read_text()
    )
    hpsi_row = next(
        row
        for row in replacement_report["rows"]
        if row["opportunity_id"] == hpsi["opportunity_id"]
    )

    assert replacement_report["replacement_ready_count"] == 0
    assert replacement_report["external_accelerated_results_consumed_by_qe_count"] == 1
    assert replacement_report["external_consumed_but_blocked_count"] == 1
    assert replacement_report["component_model_boundary_blocked_count"] == 1
    assert replacement_report["patch_precheck_linked_count"] == manifest["opportunity_count"]
    assert (
        replacement_report[
            "patch_precheck_trusted_l4_replacement_candidate_count"
        ]
        == artifacts["qe_callsite_patch_manifest.json"][
            "trusted_l4_replacement_precheck_count"
        ]
    )
    assert hpsi_row["external_consumption_evidence_status"] == "consumed_by_qe_but_blocked"
    assert hpsi_row["external_accelerated_results_consumed_by_qe"] is True
    assert hpsi_row["component_model_boundary_blocks_replacement"] is True
    assert hpsi_row["patch_replacement_precheck_status"] == "blocked_component_model_not_l4"
    assert hpsi_row["patch_accelerated_result_writeback_present"] is True
    assert hpsi_row["patch_component_model_boundary_declared"] is True
    assert hpsi_row["patch_trusted_l4_replacement_precheck_passed"] is False
    assert hpsi_row["ready_for_value_gate"] is False
    assert replacement_report["deliverable_complete"] is False


def test_replacement_report_surfaces_selected_runtime_target_mismatch(tmp_path):
    artifacts = offload_artifact_bundle(source_root=tmp_path / "missing-qe-src")
    inventory_path = tmp_path / "inventory.json"
    manifest_path = tmp_path / "manifest.json"
    inventory_path.write_text(
        json.dumps(artifacts["qe_callgraph_inventory.json"]),
        encoding="utf-8",
    )
    manifest = artifacts["offload_opportunity_manifest.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    diagonalization = next(
        row for row in manifest["opportunities"] if row["kernel"] == "diagonalization"
    )
    attempt = {
        "opportunity_id": diagonalization["opportunity_id"],
        "kernel": "diagonalization",
        "evidence_kind": "real_qe_l4_attempt",
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "blocked",
            "selected_kernel": "diagonalization",
            "target_kernel": "h_psi",
            "target_kernel_matches_selected": False,
            "accelerated_results_consumed_by_qe": True,
            "software_fallback_on_critical_path": False,
            "blockers": [
                "runtime_replacement_target_kernel_mismatch:diagonalization:h_psi"
            ],
        },
        "speed_signal": {"status": "positive", "speedup_vs_pure_qe": 2.0},
    }
    attempt_path = tmp_path / "attempt_target_mismatch.json"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")

    status = build_multi_probe_report(
        out_dir=tmp_path / "multi_target_mismatch",
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        attempt_paths=[attempt_path],
    )
    matrix = json.loads(
        (
            tmp_path
            / "multi_target_mismatch"
            / "offload_value_l4_evidence_matrix.json"
        ).read_text()
    )
    replacement_report = json.loads(
        (
            tmp_path
            / "multi_target_mismatch"
            / "accelerated_replacement_readiness_report.json"
        ).read_text()
    )
    replacement_report_md = (
        tmp_path
        / "multi_target_mismatch"
        / "accelerated_replacement_readiness_report.md"
    ).read_text()
    mismatch_row = next(
        row
        for row in replacement_report["rows"]
        if row["opportunity_id"] == diagonalization["opportunity_id"]
    )

    assert status["valuable_l4_count"] == 0
    assert matrix["valuable_l4_count"] == 0
    assert replacement_report["replacement_ready_count"] == 0
    assert replacement_report["target_kernel_mismatch_count"] == 1
    assert replacement_report["qe_kernel_work_replaced_on_critical_path_count"] == 0
    assert mismatch_row["accelerated_replacement_selected_kernel"] == "diagonalization"
    assert mismatch_row["accelerated_replacement_target_kernel"] == "h_psi"
    assert (
        mismatch_row["accelerated_replacement_target_kernel_matches_selected"]
        is False
    )
    assert (
        "runtime_replacement_target_kernel_mismatch:diagonalization:h_psi"
        in mismatch_row["replacement_blockers"]
    )
    assert "target_kernel_mismatch_count: `1`" in replacement_report_md
    assert "qe_kernel_work_replaced_on_critical_path_count: `0`" in replacement_report_md
