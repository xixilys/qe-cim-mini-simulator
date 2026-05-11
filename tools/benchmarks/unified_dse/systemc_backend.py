from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .fast_model import FastModelBackend
from .interfaces import DesignPoint, EvaluationConfig, EvaluationResult, WorkloadDescriptor
from .stage_a_contracts import default_contract_fields


REF_CLOCK_HZ = 1.0e9
FAMILY_POWER_W = {
    "F1": {"host": 55.0, "device": 65.0, "dma": 10.0, "idle": 18.0},
    "F2": {"host": 55.0, "device": 82.0, "dma": 12.0, "idle": 20.0},
    "F3": {"host": 55.0, "device": 105.0, "dma": 14.0, "idle": 24.0},
}


class SystemCBackend:
    def __init__(
        self,
        model_path: Path | str,
        dry_run: bool | None = None,
        allow_execute: bool | None = None,
        config: EvaluationConfig | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        if config is None:
            config = EvaluationConfig(
                fidelity_level="L0" if dry_run else "L2",
                dry_run=bool(dry_run),
                allow_execute=bool(allow_execute),
            )
        if dry_run is not None or allow_execute is not None:
            config = EvaluationConfig(
                fidelity_level=config.fidelity_level,
                output_dir=config.output_dir,
                allow_execute=config.allow_execute if allow_execute is None else bool(allow_execute),
                dry_run=config.dry_run if dry_run is None else bool(dry_run),
                timeout_s=config.timeout_s,
                max_scf_iters=config.max_scf_iters,
            )
        self.config = config

    def evaluate(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        if self.config.fidelity_level == "L0":
            return self._evaluate_l0(workload, design_point)
        if self.config.fidelity_level == "L2":
            return self._evaluate_l2(workload, design_point)
        return self._unsupported_fidelity(workload, design_point)

    def _evaluate_l0(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        result = FastModelBackend(source_kind="fast_model_screening").evaluate(workload, design_point)
        metrics = _with_summary_metric_aliases(result.metrics, design_point)
        extra_fields = deepcopy(result.extra_fields or {})
        extra_fields["evaluation_config"] = self.config.to_dict()
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend=result.backend,
            result_status=result.result_status,
            source_kind=result.source_kind,
            metrics=metrics,
            authority_scope=result.authority_scope,
            promotion_state=result.promotion_state,
            final_public_family_winner=None,
            extra_fields=extra_fields,
        )

    def _evaluate_l2(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        extra_fields = default_contract_fields(
            workload=workload,
            design_point=design_point,
            backend="systemc",
            source_kind="timed_functional_proxy",
        )
        candidate_id = str(extra_fields["systemc_feedback_contract"]["candidate_id"])
        output_dir = self.config.output_dir or Path("tmp/unified_dse_systemc")
        candidate_json = output_dir / "systemc_candidates" / f"{candidate_id}.json"
        stdout_log = output_dir / "systemc_logs" / f"{candidate_id}.stdout.log"
        stderr_log = output_dir / "systemc_logs" / f"{candidate_id}.stderr.log"

        if self.config.dry_run:
            extra_fields["backend_observability"] = {"executed": False, "reason": "dry_run"}
            return EvaluationResult(
                workload=workload,
                design_point=design_point,
                backend="systemc",
                result_status="dry_run",
                source_kind="stub",
                metrics={},
                authority_scope="supporting_evidence_only",
                promotion_state="explain-only",
                final_public_family_winner=None,
                extra_fields=extra_fields,
            )
        if not self.config.allow_execute:
            raise ValueError("L2 SystemC execution requires EvaluationConfig.allow_execute=True")
        if not self.model_path.exists():
            raise FileNotFoundError(f"SystemC model executable not found: {self.model_path}")

        candidate_json.parent.mkdir(parents=True, exist_ok=True)
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        if candidate_json.exists():
            candidate_json.unlink()
        env = os.environ.copy()
        env.update(_systemc_env(workload, design_point, candidate_json, self.config))
        completed = subprocess.run(
            [str(self.model_path)],
            cwd=str(self.model_path.parent),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_s,
        )
        stdout_log.write_text(completed.stdout, encoding="utf-8")
        stderr_log.write_text(completed.stderr, encoding="utf-8")
        extra_fields["backend_observability"] = {
            "executed": True,
            "returncode": completed.returncode,
            "metrics_path": str(candidate_json),
            "stdout_path": str(stdout_log),
            "stderr_path": str(stderr_log),
        }
        if completed.returncode != 0:
            return _systemc_result(
                workload,
                design_point,
                "model_error",
                {},
                extra_fields,
            )
        if not candidate_json.exists():
            return _systemc_result(
                workload,
                design_point,
                "candidate_missing",
                {},
                extra_fields,
            )

        candidate = json.loads(candidate_json.read_text(encoding="utf-8"))
        metrics = _metrics_from_systemc_candidate(candidate, design_point)
        feedback = extra_fields["systemc_feedback_contract"]
        feedback.update(
            {
                "status": "feedback_artifact_ingested",
                "execution_status": "executed",
                "metrics_ref": str(candidate_json),
                "subprocess_invoked": True,
                "calibration_status": "uncalibrated_systemc_tlm",
            }
        )
        extra_fields["evaluation_config"] = self.config.to_dict()
        extra_fields["non_claims"] = [
            "not_qe_equivalent_correctness",
            "not_gem5_executed",
            "not_fpga_board_measured",
            "not_final_architecture_recommendation",
        ]
        return _systemc_result(workload, design_point, "executed", metrics, extra_fields)

    def _unsupported_fidelity(
        self,
        workload: WorkloadDescriptor,
        design_point: DesignPoint,
    ) -> EvaluationResult:
        extra_fields = default_contract_fields(
            workload=workload,
            design_point=design_point,
            backend="systemc",
            source_kind="stub",
        )
        extra_fields["evaluation_config"] = self.config.to_dict()
        extra_fields["backend_observability"] = {
            "executed": False,
            "reason": f"fidelity {self.config.fidelity_level} is reserved",
        }
        return EvaluationResult(
            workload=workload,
            design_point=design_point,
            backend="systemc",
            result_status="unsupported_fidelity",
            source_kind="stub",
            metrics={},
            authority_scope="supporting_evidence_only",
            promotion_state="explain-only",
            final_public_family_winner=None,
            extra_fields=extra_fields,
        )


def _systemc_result(
    workload: WorkloadDescriptor,
    design_point: DesignPoint,
    result_status: str,
    metrics: dict[str, Any],
    extra_fields: dict[str, Any],
) -> EvaluationResult:
    return EvaluationResult(
        workload=workload,
        design_point=design_point,
        backend="systemc",
        result_status=result_status,
        source_kind="timed_functional_proxy",
        metrics=metrics,
        authority_scope="supporting_evidence_only",
        promotion_state="explain-only",
        final_public_family_winner=None,
        extra_fields=extra_fields,
    )


def _systemc_env(
    workload: WorkloadDescriptor,
    design_point: DesignPoint,
    candidate_json: Path,
    config: EvaluationConfig,
) -> dict[str, str]:
    payload = workload.to_dict()
    design = design_point.to_dict()
    env = {
        "QEBS_SOFTWARE_FAMILY": "QE" if workload.app_adapter == "qe" else workload.app_adapter.upper(),
        "QEBS_FLOW_FAMILY": "CBANDS_DIAG",
        "QEBS_ARCH_FAMILY": design_point.family,
        "QEBS_CANDIDATE_FAMILY": design_point.family,
        "QEBS_ASSUMPTION_SET_ID": str(payload.get("assumption_set_id") or "stage_a_dry_run_assumption_set"),
        "QEBS_CASE_ID": workload.workload_id,
        "QEBS_RESULT_JSON": str(candidate_json),
        "QEBS_MAX_SCF_ITERS": str(config.max_scf_iters),
        "QEBS_OFFLOAD_SCOPE": design_point.offload_scope,
        "QEBS_RESIDENT_POLICY": design_point.resident_policy,
        "QEBS_SIGNATURE_ID": workload.signature_id,
        "QEBS_PSEUDOPOTENTIAL_FAMILY": workload.pseudopotential_family,
        "QEBS_SOLVER_PATH_CLASS": workload.solver_path_class,
        "QEBS_WORKLOAD_TOPOLOGY": workload.workload_topology,
        "QEBS_PROJECTOR_PRESSURE": workload.projector_pressure,
        "QEBS_NONLOCAL_PRESSURE": workload.nonlocal_pressure,
    }
    if design.get("diag_policy") == "cpu_only":
        env["QEBS_FORCE_HOST_DIAG"] = "1"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "1"
    elif design.get("diag_policy") == "aggressive_device":
        env["QEBS_FORCE_HOST_DIAG"] = "0"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "0"
    else:
        env["QEBS_FORCE_HOST_DIAG"] = "0"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "1"
    return env


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _metrics_from_systemc_candidate(
    candidate: Mapping[str, Any],
    design_point: DesignPoint,
) -> dict[str, Any]:
    metrics_in = _as_mapping(candidate.get("metrics"))
    run_summary = _as_mapping(candidate.get("run_summary"))
    timing = _as_mapping(candidate.get("timing"))
    final = _as_mapping(candidate.get("final"))
    iteration_diagnostics = [
        item for item in candidate.get("iteration_diagnostics", []) if isinstance(item, Mapping)
    ]

    wall_time_s = _as_float(timing.get("wall_time_s"))
    total_cycles = _as_int(run_summary.get("total_ref_cycles"))
    total_episodes = _as_int(run_summary.get("total_episodes"))
    device_cycles = _as_float(metrics_in.get("device_busy_ref_cycles"))
    dma_cycles = _as_float(metrics_in.get("dma_ref_cycles"))
    host_cycles = _as_float(metrics_in.get("host_assist_ref_cycles"))
    total_kib = _as_float(metrics_in.get("total_data_movement_kib"))
    dma_read_kib = _as_float(metrics_in.get("dma_read_kib"))
    dma_write_kib = _as_float(metrics_in.get("dma_write_kib"))
    fallback_count = _as_int(metrics_in.get("cpu_fallbacks"))
    resident_hits = _as_int(metrics_in.get("resident_reuse_hits"))
    spill_count = sum(1 for item in iteration_diagnostics if item.get("spill_active") is True)

    if wall_time_s is None and total_cycles is not None:
        wall_time_s = float(total_cycles) / REF_CLOCK_HZ
    energy_j = _energy_proxy_j(
        wall_time_s=wall_time_s,
        total_cycles=total_cycles,
        device_cycles=device_cycles,
        dma_cycles=dma_cycles,
        host_cycles=host_cycles,
        family=design_point.family,
    )
    avg_power_w = None if wall_time_s in (None, 0.0) or energy_j is None else energy_j / wall_time_s
    throughput = None if wall_time_s in (None, 0.0) else 1.0 / wall_time_s
    bytes_moved = None if total_kib is None else int(round(total_kib * 1024.0))
    out = {
        "latency_s": wall_time_s,
        "time_to_completion_s": wall_time_s,
        "time_to_convergence_s": wall_time_s,
        "throughput_workloads_per_s": throughput,
        "cycle_proxy": total_cycles,
        "energy_to_convergence_j": energy_j,
        "avg_system_power_proxy_w": avg_power_w,
        "device_busy_ref_cycles": device_cycles,
        "dma_ref_cycles": dma_cycles,
        "host_assist_ref_cycles": host_cycles,
        "device_busy_s": _seconds_from_cycles(device_cycles),
        "host_wait_s": _seconds_from_cycles(host_cycles),
        "dma_read_bytes": None if dma_read_kib is None else int(round(dma_read_kib * 1024.0)),
        "dma_write_bytes": None if dma_write_kib is None else int(round(dma_write_kib * 1024.0)),
        "bytes_moved_to_convergence": bytes_moved,
        "fallback_count_to_convergence": fallback_count,
        "fallback_ratio": _ratio(fallback_count, total_episodes),
        "resident_reuse_ratio": _ratio(resident_hits, total_episodes),
        "resident_reuse_hits": resident_hits,
        "spill_ratio": _ratio(spill_count, total_episodes),
        "systemc_converged": final.get("converged"),
        "systemc_scf_iterations": final.get("scf_iterations"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _seconds_from_cycles(cycles: float | int | None) -> float | None:
    if cycles is None:
        return None
    return float(cycles) / REF_CLOCK_HZ


def _energy_proxy_j(
    *,
    wall_time_s: float | None,
    total_cycles: int | None,
    device_cycles: float | None,
    dma_cycles: float | None,
    host_cycles: float | None,
    family: str,
) -> float | None:
    if wall_time_s is None:
        return None
    powers = FAMILY_POWER_W.get(family, FAMILY_POWER_W["F2"])
    if total_cycles and total_cycles > 0:
        device_s = wall_time_s * float(device_cycles or 0.0) / float(total_cycles)
        dma_s = wall_time_s * float(dma_cycles or 0.0) / float(total_cycles)
        host_s = wall_time_s * float(host_cycles or 0.0) / float(total_cycles)
        idle_s = max(wall_time_s - device_s - dma_s - host_s, 0.0)
    else:
        device_s = wall_time_s * 0.7
        dma_s = wall_time_s * 0.2
        host_s = wall_time_s * 0.1
        idle_s = 0.0
    return (
        host_s * powers["host"]
        + device_s * powers["device"]
        + dma_s * powers["dma"]
        + idle_s * powers["idle"]
    )


def _with_summary_metric_aliases(
    metrics: Mapping[str, Any],
    design_point: DesignPoint,
) -> dict[str, Any]:
    copied = dict(metrics)
    latency = _as_float(copied.get("time_to_convergence_s"))
    energy = _as_float(copied.get("energy_to_convergence_j"))
    if latency is not None:
        copied.setdefault("latency_s", latency)
        copied.setdefault("time_to_completion_s", latency)
        copied.setdefault("throughput_workloads_per_s", None if latency == 0 else 1.0 / latency)
    if energy is not None and latency not in (None, 0.0):
        copied.setdefault("avg_system_power_proxy_w", energy / latency)
    if "avg_system_power_proxy_w" not in copied and latency is not None:
        copied["avg_system_power_proxy_w"] = _energy_proxy_j(
            wall_time_s=latency,
            total_cycles=None,
            device_cycles=None,
            dma_cycles=None,
            host_cycles=None,
            family=design_point.family,
        ) / latency
    return copied
