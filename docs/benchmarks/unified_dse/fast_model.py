from __future__ import annotations

import math
from typing import Any, Mapping

from . import domain_contracts
from .interfaces import DesignPoint, EvaluationResult, WorkloadDescriptor
from .stage_a_contracts import default_contract_fields


class FastModelBackend:
    def __init__(self, source_kind: str = "stub") -> None:
        self.source_kind = source_kind

    def evaluate(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        if self.source_kind == "fast_model_screening":
            return self._evaluate_screening(workload, design_point)
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="fast_model",
            result_status="stub",
            source_kind=self.source_kind,
            metrics={"stub_metrics_present": True},
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields=default_contract_fields(
                workload=workload,
                design_point=design_point,
                backend="fast_model",
                source_kind=self.source_kind,
            ),
        )

    def _evaluate_screening(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        metrics, metadata = _screening_estimate(workload.to_dict(), design_point.to_dict())
        extra_fields = default_contract_fields(
            workload=workload,
            design_point=design_point,
            backend="fast_model",
            source_kind=self.source_kind,
        )
        extra_fields.update(
            {
                "model_metadata": metadata,
                "claim_ceiling": domain_contracts.FAST_MODEL_SCREENING_CLAIM_CEILING,
                "ranking_claim_ceiling": domain_contracts.FAST_MODEL_SCREENING_CLAIM_CEILING,
            }
        )
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="fast_model",
            result_status="screened",
            source_kind=self.source_kind,
            metrics=metrics,
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields=extra_fields,
        )


def _positive_float(payload: Mapping[str, Any], key: str, fallback: float) -> float:
    try:
        value = float(payload.get(key, fallback))
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value) or value <= 0:
        return fallback
    return value


def _dse_v2_estimate(
    workload: Mapping[str, Any],
    design_point: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        from dse_v2.models.fast.performance_model import FastPerformanceModel  # type: ignore
    except Exception:
        return None

    npw = int(_positive_float(workload, "npw", _positive_float(workload, "dimension_n", 1.0)))
    nkb = int(_positive_float(workload, "nkb", max(1.0, npw / 4.0)))
    m = int(_positive_float(workload, "m", _positive_float(workload, "dimension_m", 1.0)))
    if npw <= 0 or nkb <= 0 or m <= 0:
        return None

    family = str(design_point.get("family", "F2"))
    parallel_units = {"F1": 2, "F2": 4, "F3": 6}.get(family, 2)
    pipeline_depth = {"F1": 2, "F2": 4, "F3": 5}.get(family, 2)
    mapped_design = {
        "offload_strategy": str(design_point.get("offload_scope", "balanced")),
        "pipeline_depth": pipeline_depth,
        "parallel_units": parallel_units,
        "dataflow_pattern": "streaming",
        "tile_npw": max(64, min(1024, npw)),
        "tile_nkb": max(16, min(128, nkb)),
        "tile_m": max(1, min(32, m)),
        "intermediate_buffer_kb": 256,
    }
    model = FastPerformanceModel(
        {
            "peak_gflops": 1300,
            "memory_bw_gbs": 77,
            "pcie_bw_gbs": 16,
            "bram_kb": 34000,
            "dsp_count": 12288,
        }
    )
    try:
        result = model.evaluate_design_point(mapped_design, {"npw": npw, "nkb": nkb, "m": m})
        metrics = _metrics_from_time_energy(
            time_s=float(result["time_s"]),
            energy_j=float(result["energy_j"]),
            npw=npw,
            nkb=nkb,
            m=m,
            scf_iterations=int(_positive_float(workload, "scf_iterations", 1.0)),
            design_point=design_point,
        )
    except Exception:
        return None
    metadata = _metadata("dse_v2_fast_performance_model", "dse_v2_available")
    return metrics, metadata


def _metrics_from_time_energy(
    *,
    time_s: float,
    energy_j: float,
    npw: int,
    nkb: int,
    m: int,
    scf_iterations: int,
    design_point: Mapping[str, Any],
) -> dict[str, Any]:
    iterations = max(1, scf_iterations)
    bytes_per_iteration = (npw * m * 16) + (npw * nkb * 16) + (m * m * 16)
    fallback_ratio = 1.0 if design_point.get("diag_policy") == "cpu_only" else 0.1
    if design_point.get("diag_policy") == "device_first_fallback":
        fallback_ratio = 0.05
    spill_ratio = 0.05 if design_point.get("resident_policy") == "fit_first" else 0.15
    return {
        "time_to_convergence_s": max(0.0, time_s * iterations),
        "energy_to_convergence_j": max(0.0, energy_j * iterations),
        "bytes_moved_to_convergence": float(bytes_per_iteration * iterations),
        "fallback_ratio": fallback_ratio,
        "spill_ratio": spill_ratio,
        "host_wait_s": max(0.0, time_s * iterations * 0.15),
        "device_busy_s": max(0.0, time_s * iterations * 0.85),
    }


def _metadata(model_kind: str, adapter_status: str) -> dict[str, Any]:
    return {
        "schema_version": "fast_model_metadata_v0",
        "model_kind": model_kind,
        "adapter_status": adapter_status,
        "calibration_status": "uncalibrated",
        "validity_domain": "fpga_host_device_tlm_proxy",
        "confidence": "low",
        "assumption_set_id": "stage_a_v0",
        "claim_ceiling": domain_contracts.FAST_MODEL_SCREENING_CLAIM_CEILING,
    }


def _screening_estimate(
    workload: Mapping[str, Any],
    design_point: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    dse_v2 = _dse_v2_estimate(workload, design_point)
    if dse_v2 is not None:
        return dse_v2

    npw = int(_positive_float(workload, "npw", _positive_float(workload, "dimension_n", 1.0)))
    nkb = int(_positive_float(workload, "nkb", max(1.0, npw / 4.0)))
    m = int(_positive_float(workload, "m", _positive_float(workload, "dimension_m", 1.0)))
    scf_iterations = int(_positive_float(workload, "scf_iterations", 1.0))
    family_factor = {"F1": 1.4, "F2": 1.0, "F3": 0.85}.get(
        str(design_point.get("family", "F2")),
        1.8,
    )
    offload_factor = {
        "single_hotpath": 1.35,
        "balanced": 1.0,
        "device_heavy": 0.92,
    }.get(str(design_point.get("offload_scope", "balanced")), 1.2)
    ops = max(1.0, (5.0 * npw * math.log2(max(2, npw)) * m) + (2.0 * npw * nkb * m))
    time_s = ops / 1.0e12 * family_factor * offload_factor
    energy_j = time_s * (45.0 + 5.0 / max(0.25, family_factor))
    return (
        _metrics_from_time_energy(
            time_s=time_s,
            energy_j=energy_j,
            npw=npw,
            nkb=nkb,
            m=m,
            scf_iterations=scf_iterations,
            design_point=design_point,
        ),
        _metadata("stdlib_roofline_proxy", "dse_v2_unavailable_or_not_used"),
    )
