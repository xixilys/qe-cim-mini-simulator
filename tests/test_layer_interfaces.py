#!/usr/bin/env python3

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interfaces.validator import InterfaceValidator
from interfaces.types import (
    DesignPoint,
    EvaluationResult,
    LayerResult,
    ResourceLimits,
    WorkloadSpecialization,
)


HASH = "b" * 64


def schema_validator(schema_name):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text())
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def design_point_for_family(family):
    return DesignPoint(
        design_point_id=f"dp_{family.lower()}_001",
        family=family,
        topology_type="mesh_2d",
        parameters={
            "system_level": {
                "family": family,
                "n_gemm_tiles": 4,
                "n_eigen_tiles": 2,
                "tile_local_mem_kb": 1024,
            }
        },
        workload_specialization=WorkloadSpecialization(
            workload_id="qe_cbands_si8",
            kernels=["h_psi", "build_H_sub", "cdiaghg"],
            precision="FP64",
        ),
        target_layers=["L1", "L2"],
        resource_limits=ResourceLimits(max_area_mm2=120.0, max_power_w=80.0, max_latency_ms=1000.0),
        architecture_spec_ref=HASH,
        constraints={"max_area_mm2": 120.0, "max_power_w": 80.0, "max_latency_ms": 1000.0},
        provenance={"input_hash": HASH, "generated_at": "2026-01-01T00:00:00", "tool_version": "pytest"},
    )


def test_design_point_creation_and_serialization():
    point = design_point_for_family("F4")
    payload = point.to_dict()

    assert payload["schema_version"] == "design_point_v1"
    assert payload["family"] == "F4"
    assert payload["workload_specialization"]["kernels"] == ["h_psi", "build_H_sub", "cdiaghg"]
    assert payload["resource_limits"]["max_power_w"] == 80.0
    assert json.loads(json.dumps(payload))["design_point_id"] == "dp_f4_001"

    result = InterfaceValidator().validate(payload, "design_point_v1")
    assert result.valid, result.errors
    schema_validator("design_point_v1.json").validate(payload)


def test_evaluation_result_with_multiple_layer_results():
    layer_l1 = LayerResult(
        layer_id="L1",
        fidelity_level="L1",
        status="passed",
        metrics={"latency_ms": 120.0, "throughput_gops": 410.0, "power_w": 54.0, "accuracy_vs_reference": 0.72},
        promotion_score=0.72,
    )
    layer_l2 = LayerResult(
        layer_id="L2",
        fidelity_level="L2",
        status="passed",
        metrics={"latency_ms": 96.0, "throughput_gops": 520.0, "power_w": 63.0, "accuracy_vs_reference": 0.86},
        promotion_score=0.86,
    )
    result = EvaluationResult(
        result_id="res_dp_f4_001",
        design_point_id="dp_f4_001",
        evaluation_config_ref=HASH,
        fidelity_level_achieved="L2",
        layer_results=[layer_l1, layer_l2],
        promotion_recommendation="promote",
        promotion_score=0.86,
        metrics=layer_l2.metrics,
        status="passed",
        provenance={
            "input_hash": HASH,
            "generated_at": "2026-01-01T00:00:00",
            "tool_version": "pytest",
            "execution_time_seconds": 2.0,
        },
    )
    payload = result.to_dict()

    assert [layer["fidelity_level"] for layer in payload["layer_results"]] == ["L1", "L2"]
    assert payload["layer_results"][1]["metrics"]["accuracy_vs_reference"] == 0.86
    assert json.loads(json.dumps(payload))["promotion_recommendation"] == "promote"

    validation = InterfaceValidator().validate(payload, "evaluation_result_v1")
    assert validation.valid, validation.errors
    schema_validator("evaluation_result_v1.json").validate(payload)


@pytest.mark.parametrize("family", ["F1", "F2", "F3", "F4", "F5", "F6", "F7"])
def test_design_point_schema_supports_all_architecture_families(family):
    payload = design_point_for_family(family).to_dict()
    result = InterfaceValidator().validate(payload, "design_point_v1")
    assert result.valid, result.errors
    schema_validator("design_point_v1.json").validate(payload)
    assert payload["family"] == family


def test_dataclasses_are_plain_serializable_containers():
    layer = LayerResult(
        layer_id="L1",
        fidelity_level="L1",
        status="passed",
        metrics={"latency_ms": 1.0, "throughput_gops": 2.0, "power_w": 3.0},
    )
    assert asdict(layer)["layer_id"] == "L1"
    assert layer.to_dict()["metrics"]["power_w"] == 3.0


def test_legacy_failed_result_without_promotion_recommendation_remains_schema_valid():
    payload = {
        "schema_version": "evaluation_result_v1",
        "result_id": "res_legacy_failed",
        "evaluation_config_ref": HASH,
        "metrics": {"latency_ms": 1.0, "throughput_gops": 2.0, "power_w": 3.0},
        "status": "failed",
        "provenance": {
            "input_hash": HASH,
            "generated_at": "2026-01-01T00:00:00",
            "tool_version": "pytest",
            "execution_time_seconds": 1.0,
        },
    }

    schema_validator("evaluation_result_v1.json").validate(payload)


def test_schema_rejects_promoted_result_that_did_not_pass():
    payload = {
        "schema_version": "evaluation_result_v1",
        "result_id": "res_bad_promote",
        "evaluation_config_ref": HASH,
        "metrics": {"latency_ms": 1.0, "throughput_gops": 2.0, "power_w": 3.0},
        "status": "failed",
        "promotion_recommendation": "promote",
        "promotion_score": 0.9,
        "provenance": {
            "input_hash": HASH,
            "generated_at": "2026-01-01T00:00:00",
            "tool_version": "pytest",
            "execution_time_seconds": 1.0,
        },
    }

    with pytest.raises(ValidationError):
        schema_validator("evaluation_result_v1.json").validate(payload)
