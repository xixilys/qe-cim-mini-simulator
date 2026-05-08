#!/usr/bin/env python3

import copy
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator


HASH = "a" * 64


def now_iso():
    return datetime(2026, 1, 1, 0, 0, 0).isoformat()


def workload_profile():
    return {
        "schema_version": "workload_profile_v1",
        "workload_id": "si8_smoke",
        "compute_graph": {
            "nodes": [
                {"id": "h_psi", "type": "GEMM", "dominance": 0.68, "flops_per_call": 1.0e9, "precision": "FP64"},
                {"id": "build_H_sub", "type": "GEMM", "dominance": 0.04, "flops_per_call": 1.0e8, "precision": "FP64"},
                {"id": "cdiaghg", "type": "EIGEN", "dominance": 0.23, "flops_per_call": 1.0e8, "precision": "FP64"},
                {"id": "refresh", "type": "VECTOR", "dominance": 0.05, "flops_per_call": 1.0e7, "precision": "FP64"},
            ],
            "edges": [],
        },
        "execution_profile": {"total_iterations": 8, "stability": "stable", "dominant_solver": "Davidson"},
        "memory_profile": {"working_set_mb": 64.0, "peak_mb": 96.0, "memory_access_pattern": "streaming_with_reuse"},
        "data_movement": {"host_to_device_mb_per_iter": 8.0, "device_to_host_mb_per_iter": 2.0, "bandwidth_requirement_gbps": 16.0},
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest"},
    }


def architecture_spec():
    return {
        "schema_version": "architecture_spec_v1",
        "spec_id": "arch_si8",
        "workload_profile_ref": HASH,
        "partition": {"host_scope": ["rho_Veff"], "device_scope": ["h_psi", "build_H_sub"], "fallback_scope": ["cdiaghg"]},
        "interfaces": {
            "host_to_runtime": {"protocol": "PCIe", "bandwidth_gbps": 64},
            "runtime_to_chip": {"protocol": "AXI", "bandwidth_gbps": 256},
            "completion_handshake": {"protocol": "Interrupt"},
        },
        "selected_family": "F4",
        "family_rationale": "Tile-based architecture balances GEMM and eigensolver work.",
        "architecture_variants_considered": [{"variant_id": "V1", "name": "F4", "score": 0.91, "is_pareto": True}],
        "frozen_at": now_iso(),
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest"},
    }


def design_point():
    return {
        "schema_version": "design_point_v1",
        "design_point_id": "dp_arch_si8_001",
        "architecture_spec_ref": HASH,
        "parameters": {
            "system_level": {
                "family": "F4", "offload_scope": "balanced", "resident_policy": "fit_first",
                "partition_strategy": "operator_build_fused__diag__refresh", "diag_policy": "device_first_fallback",
                "n_gemm_tiles": 6, "n_eigen_tiles": 2, "tile_local_mem_kb": 1024,
                "mesh_topology": "2x4", "tile_link_bw_gbps": 64,
            },
            "kernel_mapping": {"tile_npw": 128, "tile_nkb": 32, "tile_m": 16, "loop_ordering": "(npw,m,nkb)", "dataflow": "weight_stationary"},
        },
        "constraints": {"max_area_mm2": 100, "max_power_w": 75, "max_latency_ms": 1000, "min_throughput_gops": 100},
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest"},
    }


def evaluation_config(fidelity="L2"):
    return {
        "schema_version": "evaluation_config_v1",
        "config_id": "cfg_dp_arch_si8_001",
        "design_point_ref": HASH,
        "fidelity_level": fidelity,
        "fidelity_config": {
            "L0": {"model": "analytical", "accuracy_target": 0.5, "max_cost_seconds": 1},
            "L1": {"model": "python_tlm", "accuracy_target": 0.3, "max_cost_seconds": 60},
            "L2": {"model": "systemc_tlm", "accuracy_target": 0.15, "max_cost_seconds": 3600},
            "L3": {"model": "cycle_accurate", "accuracy_target": 0.05, "max_cost_seconds": 86400},
            "L4": {"model": "rtl_synthesis", "accuracy_target": 0.0, "max_cost_seconds": 604800},
        },
        "promotion_policy": {"threshold_for_promotion": 0.7, "max_evaluations_per_level": 100, "early_termination": True},
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest"},
    }


def evaluation_result():
    return {
        "schema_version": "evaluation_result_v1",
        "result_id": "res_cfg_dp_arch_si8_001",
        "evaluation_config_ref": HASH,
        "metrics": {"latency_ms": 92.0, "throughput_gops": 530.0, "power_w": 63.0, "area_mm2": 90.0, "energy_efficiency_gops_per_w": 8.41, "accuracy_vs_reference": 0.85},
        "uncertainty": {"latency_ci_95": [82.8, 101.2], "throughput_ci_95": [477.0, 583.0], "confidence_level": 0.95, "mape_percent": 15.0, "sample_size": 10},
        "resource_utilization": {"compute_percent": 75, "memory_percent": 60, "bandwidth_percent": 45},
        "status": "passed",
        "promotion_recommendation": "promote",
        "promotion_score": 0.85,
        "fidelity_level_achieved": "L2",
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest", "execution_time_seconds": 1.0},
    }


def release_bundle():
    return {
        "schema_version": "release_bundle_v1",
        "bundle_id": "bundle_001",
        "evaluation_results": [HASH],
        "pareto_frontier": [HASH],
        "recommendation": {"primary_design_point": HASH, "rationale": "F4 design is the best tested point for this evidence bundle.", "confidence": 0.85},
        "authority": {"stage": "A", "claim_posture": "evidence_only", "adjudicator_approval": False, "limitations": ["Stage A only"]},
        "quality_gates": {"correctness_validated": True, "power_constraints_met": True},
        "provenance": {"input_hash": HASH, "generated_at": now_iso(), "tool_version": "pytest"},
    }


VALID_ARTIFACTS = {
    "workload_profile_v1": workload_profile,
    "architecture_spec_v1": architecture_spec,
    "design_point_v1": design_point,
    "evaluation_config_v1": evaluation_config,
    "evaluation_result_v1": evaluation_result,
    "release_bundle_v1": release_bundle,
}


@pytest.mark.parametrize("schema_name,artifact_factory", VALID_ARTIFACTS.items())
def test_all_interface_schemas_accept_valid_artifacts(schema_name, artifact_factory):
    result = InterfaceValidator().validate(artifact_factory(), schema_name)
    assert result.valid, result.errors
    assert result.schema_version == schema_name


def test_validator_loads_every_schema_file_declared_by_interface_contract():
    validator = InterfaceValidator()
    assert set(validator._schemas) == set(InterfaceValidator.SCHEMAS)


@pytest.mark.parametrize("schema_name,artifact_factory", VALID_ARTIFACTS.items())
def test_schema_version_mismatch_is_rejected(schema_name, artifact_factory):
    artifact = artifact_factory()
    artifact["schema_version"] = "wrong_schema"
    result = InterfaceValidator().validate(artifact, schema_name)
    assert not result.valid
    assert any("Schema version mismatch" in error for error in result.errors)


def test_workload_profile_rejects_dominance_sum_above_one():
    artifact = workload_profile()
    artifact["compute_graph"]["nodes"][0]["dominance"] = 0.95
    result = InterfaceValidator().validate(artifact, "workload_profile_v1")
    assert not result.valid
    assert any("Total dominance" in error for error in result.errors)


def test_architecture_spec_rejects_overlapping_partitions():
    artifact = architecture_spec()
    artifact["partition"]["host_scope"].append("h_psi")
    result = InterfaceValidator().validate(artifact, "architecture_spec_v1")
    assert not result.valid
    assert any("overlap" in error for error in result.errors)


def test_design_point_rejects_invalid_resource_parameters():
    artifact = design_point()
    artifact["parameters"]["system_level"]["n_gemm_tiles"] = 32
    result = InterfaceValidator().validate(artifact, "design_point_v1")
    assert not result.valid
    assert any("n_gemm_tiles" in error for error in result.errors)


def test_evaluation_config_rejects_non_monotonic_fidelity_costs():
    artifact = evaluation_config()
    artifact["fidelity_config"]["L2"]["max_cost_seconds"] = 10
    result = InterfaceValidator().validate(artifact, "evaluation_config_v1")
    assert not result.valid
    assert any("Cost not monotonic" in error for error in result.errors)


def test_evaluation_result_rejects_invalid_confidence_intervals():
    artifact = evaluation_result()
    artifact["uncertainty"]["latency_ci_95"] = [100.0, 90.0]
    result = InterfaceValidator().validate(artifact, "evaluation_result_v1")
    assert not result.valid
    assert any("Invalid confidence interval" in error for error in result.errors)


def test_release_bundle_rejects_pareto_entries_missing_from_results():
    artifact = release_bundle()
    artifact["pareto_frontier"] = ["b" * 64]
    result = InterfaceValidator().validate(artifact, "release_bundle_v1")
    assert not result.valid
    assert any("pareto_frontier contains" in error for error in result.errors)


def test_schema_files_are_valid_json_objects_with_required_lists():
    for schema_path in (ROOT / "schemas").glob("*_v1.json"):
        schema = json.loads(schema_path.read_text())
        assert schema["type"] == "object"
        assert isinstance(schema.get("required"), list)
        assert "schema_version" in schema["required"]
