#!/usr/bin/env python3
"""QE call-site patch manifest safety tests."""

from __future__ import annotations

import copy
from pathlib import Path

from dse_v2.codesign.qe_callgraph_offload_search import (
    build_offload_bundle_search_space,
    build_offload_opportunity_manifest,
    build_qe_callgraph_inventory,
    build_qe_callsite_patch_manifest,
    validate_qe_callsite_patch_manifest,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _patch_manifest(tmp_path):
    inventory = build_qe_callgraph_inventory(source_root=tmp_path / "missing-qe-src")
    opportunities = build_offload_opportunity_manifest(inventory)
    bundles = build_offload_bundle_search_space(opportunities)
    return build_qe_callsite_patch_manifest(bundles)


def test_patch_manifest_rows_have_fallback_tolerance_correctness_and_payload(tmp_path):
    manifest = _patch_manifest(tmp_path)

    assert manifest["status"] == "passed"
    assert manifest["all_rows_have_fallback_tolerance_correctness"] is True
    assert manifest["materialized_patch_row_count"] >= 1
    assert manifest["trace_hook_patch_row_count"] >= 1
    assert manifest["replacement_writeback_patch_row_count"] >= 1
    assert manifest["component_model_boundary_patch_row_count"] >= 1
    trusted_rows = [
        row
        for row in manifest["patch_rows"]
        if row["instrumentation_capabilities"][
            "trusted_l4_replacement_precheck_passed"
        ]
        is True
    ]
    assert manifest["trusted_l4_replacement_precheck_count"] == len(trusted_rows)
    assert trusted_rows
    assert {
        row["instrumentation_capabilities"]["replacement_precheck_status"]
        for row in trusted_rows
    } == {"trusted_l4_replacement_candidate_precheck_only"}
    assert {
        row["instrumentation_capabilities"]["source_targets"][0]
        for row in trusted_rows
    } == {"FFTXlib/src/fft_fwinv.f90"}
    for row in trusted_rows:
        caps = row["instrumentation_capabilities"]
        assert len(row["opportunity_ids"]) == 1
        assert (
            caps["replacement_precheck_status"]
            == "trusted_l4_replacement_candidate_precheck_only"
        )
        assert caps["value_gate_blockers"] == []
        assert caps["accelerated_result_materialization_marker_declared"] is True
        assert caps["qe_software_kernel_execution_skip_marker_declared"] is True
        assert caps["l4_execution_proof_declared"] is True
    assert not [
        row
        for row in manifest["patch_rows"]
        if len(row["opportunity_ids"]) > 1
        and row["instrumentation_capabilities"][
            "trusted_l4_replacement_precheck_passed"
        ]
        is True
    ]
    assert validate_qe_callsite_patch_manifest(manifest)["valid"] is True
    for row in manifest["patch_rows"]:
        assert row["changed_files"]
        assert row["materialized_patch_files"]
        assert row["materialized_patch_capabilities"]
        assert row["instrumentation_capabilities"]
        assert row["callsite_ids"]
        assert row["runtime_extension_payload"]["schema"] == "qe.offload.extension_payload.v1"
        assert row["fallback_path"] == "pure_qe_software_fallback"
        assert row["tolerance_impact"]["review_required"] is True
        assert row["correctness_oracle"]
        assert row["performance_impact_hypothesis"] == "requires_real_l4_measurement"
        assert "real_l4_required_for_value" in row["trusted_status_rules"]
        assert (
            "materialized_patch_capabilities_are_precheck_only"
            in row["trusted_status_rules"]
        )
    assert any(
        item["exists"]
        for row in manifest["patch_rows"]
        for item in row["materialized_patch_files"]
        if item["path"].endswith(
            (
                "opp_qe_si_scf_small_v1_scf_s_psi.patch",
                "opp_qe_si_scf_small_v1_scf_diagonalization.patch",
            )
        )
    )
    hpsi_row = next(
        row
        for row in manifest["patch_rows"]
        if row["opportunity_ids"] == ["opp_qe_si_scf_small_v1_scf_h_psi"]
    )
    hpsi_caps = hpsi_row["instrumentation_capabilities"]
    assert hpsi_caps["accelerated_result_writeback_present"] is True
    assert hpsi_caps["accelerated_consumption_marker_declared"] is True
    assert hpsi_caps["component_model_boundary_declared"] is True
    assert hpsi_caps["replacement_precheck_status"] == "blocked_component_model_not_l4"
    assert "component_model_boundary_not_l4" in hpsi_caps["value_gate_blockers"]

    spsi_row = next(
        row
        for row in manifest["patch_rows"]
        if row["opportunity_ids"] == ["opp_qe_si_scf_small_v1_scf_s_psi"]
    )
    spsi_caps = spsi_row["instrumentation_capabilities"]
    assert spsi_caps["trace_hook_present"] is True
    assert spsi_caps["generic_bridge_hook_present"] is True
    assert spsi_caps["accelerated_result_writeback_present"] is True
    assert spsi_caps["accelerated_consumption_marker_declared"] is True
    assert spsi_caps["kernel_work_replacement_marker_declared"] is True
    assert spsi_caps["accelerated_result_materialization_marker_declared"] is True
    assert spsi_caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert spsi_caps["l4_execution_proof_declared"] is True
    assert (
        spsi_caps["replacement_precheck_status"]
        == "blocked_replacement_evidence_incomplete"
    )
    assert spsi_caps["trusted_l4_replacement_precheck_passed"] is False
    assert (
        "accelerator_numeric_payload_marker_missing"
        in spsi_caps["value_gate_blockers"]
    )


def test_hpsi_runtime_evidence_is_gated_when_selected_kernel_is_not_hpsi():
    patch_dir = _REPO_ROOT / "patches" / "qe_callsite_offload_hooks"
    hpsi_patches = sorted(patch_dir.glob("*_h_psi.patch"))

    assert hpsi_patches, "expected materialized h_psi QE patch files"
    for patch_path in hpsi_patches:
        text = patch_path.read_text()
        assert "LOGICAL :: qe_hpsi_runtime_evidence_enabled" in text
        assert "qe_hpsi_runtime_evidence_enabled = .TRUE." in text
        assert "qe_hpsi_runtime_evidence_enabled = .FALSE." in text
        assert "qe_offload_bridge_kernel(:qe_offload_bridge_kernel_len) /= 'h_psi'" in text
        assert (
            "qe_env_status == 0 .AND. qe_env_len > 0 .AND. "
            "qe_hpsi_runtime_evidence_enabled"
        ) in text
        assert (
            "qe_hpsi_runtime_evidence_enabled .AND. "
            "( qe_sidecar_consumed .OR. qe_sidecar_consumed_once )"
        ) in text


def test_spsi_patch_declares_strict_nc_identity_writeback_precheck_only():
    patch_dir = _REPO_ROOT / "patches" / "qe_callsite_offload_hooks"
    spsi_patches = sorted(patch_dir.glob("*_s_psi.patch"))

    assert spsi_patches, "expected materialized s_psi QE patch files"
    for patch_path in spsi_patches:
        text = patch_path.read_text()
        assert "SUBROUTINE s_psi_(" in text
        assert "QE_OFFLOAD_ACCELERATED_WRITEBACK" in text
        assert "generic_accel_l4_spsi" in text
        assert '"kernel_scope": "full_s_psi"' in text
        assert '"target_kernel": "s_psi"' in text
        assert '"accelerated_results_consumed_by_qe": true' in text
        assert '"accelerated_result_materialized_in_qe_memory": true' in text
        assert '"accelerated_output_written_to_qe_buffer": true' in text
        assert '"qe_consumed_accelerator_output_buffer": true' in text
        assert '"qe_software_kernel_execution_skipped": true' in text
        assert '"software_kernel_execution_removed_from_critical_path": true' in text
        assert '"qe_kernel_work_replaced_on_critical_path": true' in text
        assert '"accelerated_results_consumed_by_qe": false' in text
        assert '"qe_kernel_work_replaced_on_critical_path": false' in text
        assert '"accelerated_kernel_work_removed_from_critical_path": false' in text
        assert "norm-conserving/identity" in text


def test_fft_patch_declares_strict_l4_zero_payload_replacement_precheck(tmp_path):
    manifest = _patch_manifest(tmp_path)
    fft_row = next(
        row
        for row in manifest["patch_rows"]
        if row["opportunity_ids"] == ["opp_qe_si_nscf_bandgrid_v1_nscf_fft"]
    )
    fft_caps = fft_row["instrumentation_capabilities"]

    assert fft_caps["accelerated_result_writeback_present"] is True
    assert fft_caps["accelerated_result_materialization_denial_declared"] is False
    assert fft_caps["qe_software_kernel_execution_skip_denial_declared"] is False
    assert fft_caps["accelerated_result_materialization_marker_declared"] is True
    assert fft_caps["qe_software_kernel_execution_skip_marker_declared"] is True
    assert fft_caps["kernel_work_replacement_marker_declared"] is True
    assert fft_caps["accelerator_numeric_payload_marker_declared"] is True
    assert fft_caps["software_fallback_on_critical_path_declared"] is True
    assert fft_caps["trusted_l4_replacement_precheck_passed"] is True
    assert fft_caps["replacement_precheck_status"] == (
        "trusted_l4_replacement_candidate_precheck_only"
    )
    assert fft_caps["value_gate_blockers"] == []


def test_diagonalization_patch_declares_strict_replacement_and_fallback_evidence():
    patch_dir = _REPO_ROOT / "patches" / "qe_callsite_offload_hooks"
    diagonalization_patches = sorted(patch_dir.glob("*_diagonalization.patch"))

    assert diagonalization_patches, "expected materialized diagonalization QE patches"
    for patch_path in diagonalization_patches:
        text = patch_path.read_text()
        assert "LOGICAL :: qe_diag_runtime_evidence_enabled" in text
        assert "LOGICAL :: qe_diag_replacement_consumed" in text
        assert "QE_OFFLOAD_STRICT_REPLACEMENT" in text
        assert "QE_OFFLOAD_KERNEL_EVIDENCE_JSON" in text
        assert "QE_OFFLOAD_PROVENANCE_JSON" in text
        assert "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON" in text
        assert '"kernel_id": "diagonalization"' in text
        assert '"target_kernel": "diagonalization"' in text
        assert '"full_kernel_recomputed": true' in text
        assert '"accelerated_result_materialized_in_qe_memory": true' in text
        assert '"accelerated_output_written_to_qe_buffer": true' in text
        assert '"qe_consumed_accelerator_output_buffer": true' in text
        assert '"qe_software_kernel_execution_skipped": true' in text
        assert '"software_kernel_execution_removed_from_critical_path": true' in text
        assert '"qe_kernel_work_replaced_on_critical_path": true' in text
        assert '"accelerated_kernel_work_removed_from_critical_path": true' in text
        assert '"accelerated_output_data_path": "' in text
        assert '"l4_execution_proof": {' in text
        assert '"accelerated_results_consumed_by_qe": false' in text
        assert '"qe_kernel_work_replaced_on_critical_path": false' in text
        assert "QE retained diagonalization software fallback" in text


def test_forces_patch_declares_strict_zero_force_replacement_precheck_only():
    patch_path = (
        _REPO_ROOT
        / "patches"
        / "qe_callsite_offload_hooks"
        / "opp_qe_si_relax_forces_v1_relax_forces.patch"
    )

    text = patch_path.read_text()

    assert "QE_OFFLOAD_STRICT_REPLACEMENT" in text
    assert "QE_OFFLOAD_KERNEL_EVIDENCE_JSON" in text
    assert "QE_OFFLOAD_PROVENANCE_JSON" in text
    assert "QE_OFFLOAD_ACCELERATED_OUTPUT_JSON" in text
    assert '"kernel_id": "forces"' in text
    assert '"target_kernel": "forces"' in text
    assert '"force_vector_policy": "zero_force_writeback"' in text
    assert '"full_kernel_recomputed": true' in text
    assert '"accelerated_result_materialized_in_qe_memory": true' in text
    assert '"accelerated_output_written_to_qe_buffer": true' in text
    assert '"qe_consumed_accelerator_output_buffer": true' in text
    assert '"qe_software_kernel_execution_skipped": true' in text
    assert '"software_kernel_execution_removed_from_critical_path": true' in text
    assert '"qe_kernel_work_replaced_on_critical_path": true' in text
    assert '"accelerated_kernel_work_removed_from_critical_path": true' in text
    assert '"accelerated_output_data_path": "' in text
    assert '"l4_execution_proof": {' in text
    assert '"accelerated_results_consumed_by_qe": false' in text
    assert '"qe_kernel_work_replaced_on_critical_path": false' in text
    assert "QE retained local forces software path" in text
    assert "QE correctness decides validity" in text


def test_missing_patch_safety_fields_blocks_trusted_l4_value(tmp_path):
    manifest = _patch_manifest(tmp_path)
    broken = copy.deepcopy(manifest)
    broken["patch_rows"][0].pop("fallback_path")
    broken["patch_rows"][0]["tolerance_impact"] = {}
    broken["patch_rows"][0]["correctness_oracle"] = []

    report = validate_qe_callsite_patch_manifest(broken)

    assert report["valid"] is False
    assert report["trusted_l4_value_allowed"] is False
    blocked_fields = {block["field"] for block in report["trusted_blocks"]}
    assert {"fallback_path", "tolerance_impact", "correctness_oracle"}.issubset(
        blocked_fields
    )
