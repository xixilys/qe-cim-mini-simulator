#!/usr/bin/env python3

import time

import pytest

from dse_v2.models.fast.family_models import (
    F1PipelineModel,
    F2SystolicModel,
    F3DataflowModel,
    F4CimDspHbmModel,
    F5CgraModel,
    F6CustomModel,
    F7FutureModel,
)
from dse_v2.models.fast.performance_model import FastPerformanceModel
from interfaces.types import DesignPoint, ResourceLimits, WorkloadSpecialization


FPGA_SPECS = {
    "peak_gflops": 1300,
    "memory_bw_gbs": 77,
    "pcie_bw_gbs": 16,
    "bram_kb": 34000,
    "dsp_count": 12288,
}


FAMILY_MODELS = {
    "F1": F1PipelineModel(),
    "F2": F2SystolicModel(),
    "F3": F3DataflowModel(),
    "F4": F4CimDspHbmModel(),
    "F5": F5CgraModel(),
    "F6": F6CustomModel(),
    "F7": F7FutureModel(),
}


def design_point_for_family(family: str, **overrides) -> DesignPoint:
    parameters = {
        "system_level": {
            "family": family,
            "n_gemm_tiles": 4,
            "n_eigen_tiles": 2,
            "tile_local_mem_kb": 1024,
            "array_size": 1024,
            "f_pe": 1.0,
            "utilization": 0.85,
            "compute_scale": 1.0,
            "memory_scale": 1.0,
            "interconnect_scale": 1.0,
            "chiplets": 4,
        }
    }
    parameters["system_level"].update(overrides)
    return DesignPoint(
        design_point_id=f"dp_{family.lower()}_001",
        family=family,
        topology_type="mesh_2d",
        parameters=parameters,
        workload_specialization=WorkloadSpecialization(
            workload_id="qe_cbands_si8",
            kernels=["h_psi", "cdiaghg", "reduction", "refresh"],
            precision="FP64",
        ),
        target_layers=["L1"],
        resource_limits=ResourceLimits(max_area_mm2=120.0, max_power_w=80.0, max_latency_ms=1000.0),
        architecture_spec_ref="b" * 64,
        constraints={"max_area_mm2": 120.0, "max_power_w": 80.0, "max_latency_ms": 1000.0},
        provenance={"input_hash": "b" * 64, "generated_at": "2026-01-01T00:00:00", "tool_version": "pytest"},
    )


def gemm_heavy_workload():
    return {
        "npw": 4096,
        "nkb": 256,
        "m": 32,
        "kernel_mix": {"h_psi": 0.78, "cdiaghg": 0.14, "reduction": 0.04, "refresh": 0.04},
        "iterations": 2,
    }


def balanced_workload():
    return {
        "npw": 2945,
        "nkb": 144,
        "m": 16,
        "kernel_mix": {"h_psi": 0.68, "cdiaghg": 0.23, "reduction": 0.04, "refresh": 0.05},
        "iterations": 1,
    }


@pytest.mark.parametrize("family,model", list(FAMILY_MODELS.items()))
def test_each_family_model_produces_a_unique_evaluation(family, model):
    result = model.evaluate(design_point_for_family(family), gemm_heavy_workload())

    assert result.family == family
    assert result.status in {"passed", "failed"}
    assert result.time_s > 0.0
    assert result.energy_j > 0.0
    assert {"h_psi", "cdiaghg", "reduction", "refresh"}.issubset(result.kernel_times_s)


def test_f1_is_slower_than_f4_for_gemm_heavy_workload():
    f1 = FAMILY_MODELS["F1"].evaluate(design_point_for_family("F1"), gemm_heavy_workload())
    f4 = FAMILY_MODELS["F4"].evaluate(design_point_for_family("F4"), gemm_heavy_workload())

    assert f1.time_s > f4.time_s


def test_resource_budget_is_enforced():
    constrained_point = design_point_for_family("F2", dsp_budget=0.2, bram_budget=0.2, area_scale=6.0)
    result = FastPerformanceModel(FPGA_SPECS).evaluate_design_point(constrained_point, balanced_workload())

    assert result.status == "failed"
    assert result.resource_utilization["dsp_utilization"] > 1.0 or result.resource_utilization["bram_utilization"] > 1.0


def test_fast_model_returns_evaluation_result_schema_and_is_fast():
    model = FastPerformanceModel(FPGA_SPECS)
    point = design_point_for_family("F3")

    start = time.perf_counter()
    result = model.evaluate_design_point(point, balanced_workload())
    elapsed = time.perf_counter() - start

    assert result.schema_version == "evaluation_result_v1"
    assert result.design_point_id == point.design_point_id
    assert result.layer_results[0].model_used == "F3DataflowModel"
    assert result.metrics["time_s"] > 0.0
    assert elapsed < 1.0
