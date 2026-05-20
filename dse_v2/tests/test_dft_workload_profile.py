#!/usr/bin/env python3
"""DFT workload profile coverage/admission boundary tests."""

from __future__ import annotations

from dse_v2.reference_workloads.dft_workload_profile import (
    build_coverage_derivation_audit,
    build_coverage_vector,
)


def _raw_facts(*, nbnd: int = 32, calculation: str = "scf") -> dict:
    return {
        "schema_version": "dse.dft.raw_input_facts.v1",
        "class_id": "feature_pressure_case",
        "calculation": calculation,
        "structure": {"nat": 8, "ntyp": 1, "ibrav": 1},
        "system": {
            "occupations": "fixed",
            "nbnd": {"explicit": True, "input_value": nbnd},
        },
    }


def test_coverage_gates_are_feature_derived_not_stress_tag_driven():
    low_features = {
        "fft": {"nfft": None, "nfft_total": None},
        "hpsi": {"nbnd": 8, "kpoints": 1, "npw_effective": None},
        "nonlocal_projector": {"projector_count": None, "estimated_projector_work": None},
        "dense_linear_algebra": {"nbnd": 8, "gemm_shape_estimates": [], "orthogonalization_shape": [8, 8]},
        "reductions": {"dot_products_per_scf_estimate": None},
        "host_device": {"transfer_bytes_per_scf_estimate": None},
    }

    coverage = build_coverage_vector(
        class_id="tag_only_pressure_case",
        stress_tags=("large_fft", "transpose", "nonlocal_projector", "orthogonalization", "gemm_gemv"),
        raw_input_facts=_raw_facts(nbnd=8),
        derived_features=low_features,
        resolved_run_facts={"resolved_nfft": {"grid": None}},
    )

    gates = set(coverage["required_kernel_gates"])
    assert "fft3d_forward_inverse_batch" in gates
    assert "hpsi_local_potential" in gates
    assert "kinetic_energy_apply" in gates
    assert "reduction_dot_tree" in gates
    assert "dma_hbm_movement_engine" in gates
    assert "transpose_layout_conversion" not in gates
    assert "nonlocal_projector_apply" not in gates
    assert "complex_gemm_tile" not in gates
    assert "complex_gemv_tile" not in gates
    assert coverage["display_stress_tags"] == [
        "gemm_gemv",
        "large_fft",
        "nonlocal_projector",
        "orthogonalization",
        "transpose",
    ]
    assert coverage["suite_intent_tags"] == coverage["display_stress_tags"]
    assert coverage["stress_tag_gate_policy"] == "display_only_not_authoritative"
    assert coverage["coverage_derivation_audit"]["all_required_gates_have_non_tag_derivation"] is True
    assert coverage["coverage_derivation_audit"]["stress_tags_used_for_gate_authority"] is False


def test_feature_pressure_gates_have_derivation_reasons_independent_of_tags():
    high_features = {
        "fft": {
            "nfft": [128, 128, 64],
            "nfft_total": 1_048_576,
            "transforms_per_scf_estimate": 512,
            "estimated_fft_points_per_scf": 536_870_912,
        },
        "hpsi": {"nbnd": 32, "kpoints": 8, "npw_effective": 4096, "estimated_complex_points": 1_048_576},
        "nonlocal_projector": {"projector_count": 12, "estimated_projector_work": 3072},
        "dense_linear_algebra": {
            "nbnd": 32,
            "gemm_shape_estimates": [[32, 32, 4096]],
            "orthogonalization_shape": [32, 32],
        },
        "reductions": {"dot_products_per_scf_estimate": 8192},
        "host_device": {"transfer_bytes_per_scf_estimate": 134_217_728},
    }

    with_tags = build_coverage_vector(
        class_id="feature_pressure_case",
        stress_tags=("large_fft", "nonlocal_projector"),
        raw_input_facts=_raw_facts(),
        derived_features=high_features,
        resolved_run_facts={"resolved_nfft": {"grid": [128, 128, 64]}},
    )
    without_tags = build_coverage_vector(
        class_id="feature_pressure_case",
        stress_tags=("display_only_changed",),
        raw_input_facts=_raw_facts(),
        derived_features=high_features,
        resolved_run_facts={"resolved_nfft": {"grid": [128, 128, 64]}},
    )

    assert with_tags["required_kernel_gates"] == without_tags["required_kernel_gates"]
    gates = set(with_tags["required_kernel_gates"])
    assert {
        "fft3d_forward_inverse_batch",
        "transpose_layout_conversion",
        "hpsi_local_potential",
        "kinetic_energy_apply",
        "nonlocal_projector_apply",
        "complex_gemm_tile",
        "complex_gemv_tile",
        "reduction_dot_tree",
        "dma_hbm_movement_engine",
    } <= gates
    reasons = with_tags["gate_derivation_reasons"]
    assert set(reasons) == gates
    assert any(reason["fact"] == "fft.nfft_total" for reason in reasons["transpose_layout_conversion"])
    assert any(reason["fact"] == "nonlocal_projector.projector_count" for reason in reasons["nonlocal_projector_apply"])
    assert any(reason["fact"] == "dense_linear_algebra.nbnd" for reason in reasons["complex_gemm_tile"])
    assert all(reason["source"] != "stress_tags" for gate_reasons in reasons.values() for reason in gate_reasons)
    assert with_tags["coverage_derivation_audit"]["all_required_gates_have_non_tag_derivation"] is True
    assert with_tags["coverage_derivation_audit"]["stress_tags_used_for_gate_authority"] is False


def test_stress_tags_do_not_authorize_pressure_gates_without_feature_facts():
    low_features = {
        "fft": {"nfft": None, "nfft_total": None},
        "hpsi": {"nbnd": 8, "kpoints": 1, "npw_effective": None},
        "nonlocal_projector": {"projector_count": 0, "estimated_projector_work": 0},
        "dense_linear_algebra": {"nbnd": 8, "gemm_shape_estimates": [], "orthogonalization_shape": [8, 8]},
        "reductions": {"dot_products_per_scf_estimate": None},
        "host_device": {"transfer_bytes_per_scf_estimate": None},
    }

    coverage = build_coverage_vector(
        class_id="display_tags_without_features",
        stress_tags=("large_fft", "transpose", "nonlocal_projector", "dma"),
        raw_input_facts=_raw_facts(nbnd=8, calculation="unknown"),
        derived_features=low_features,
        resolved_run_facts={"resolved_nfft": {"grid": None}},
    )

    gates = set(coverage["required_kernel_gates"])
    assert "transpose_layout_conversion" not in gates
    assert "nonlocal_projector_apply" not in gates
    assert "dma_hbm_movement_engine" not in gates
    assert coverage["display_stress_tags"] == ["dma", "large_fft", "nonlocal_projector", "transpose"]
    assert coverage["coverage_derivation_audit"]["all_required_gates_have_non_tag_derivation"] is True
    assert coverage["coverage_derivation_audit"]["stress_tags_used_for_gate_authority"] is False


def test_coverage_derivation_audit_flags_tag_only_required_gate_authority():
    audit = build_coverage_derivation_audit({
        "required_kernel_gates": ["transpose_layout_conversion"],
        "gate_derivation_reasons": {
            "transpose_layout_conversion": [
                {
                    "source": "stress_tags",
                    "fact": "stress_tags.large_fft",
                    "value": "large_fft",
                    "rule": "invalid tag-only authority",
                }
            ]
        },
    })

    assert audit["all_required_gates_have_non_tag_derivation"] is False
    assert audit["stress_tags_used_for_gate_authority"] is True
    assert audit["stress_tag_only_required_gates"] == ["transpose_layout_conversion"]
