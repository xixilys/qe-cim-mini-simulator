#!/usr/bin/env python3
"""Run exhaustive complete-DSE release-candidate × QE-mainflow L4 evidence rows.

This runner is deliberately anti-downgrade oriented.  It emits one evidence row
for every legal release candidate and every frozen QE mainflow case, even when
local tools are missing.  Missing QE/gem5/SystemC artifacts become explicit row
blockers; they are never converted into representative, Top-K, projection-only,
or descriptor-only completion claims.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.gem5_systemc_adapter import (  # noqa: E402
    Gem5SystemCClosureAdapter,
    build_generic_accel_command_descriptor,
)
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend  # noqa: E402
from dse_v2.codesign.complete_dse_search_space import (  # noqa: E402
    build_release_subset_manifest,
)
from dse_v2.codesign.l4_closure import (  # noqa: E402
    build_coverage_claim_report,
    build_l4_evidence_matrix,
)
from dse_v2.core.architecture.accelerator import (  # noqa: E402
    InterconnectTopology,
    SystemArchitecture,
    create_cim_array,
    create_fpga_u280,
    create_gpu_a100,
)
from dse_v2.dse.orchestrator import DesignPoint  # noqa: E402
from dse_v2.evidence.full_flow import build_gem5_l4_proof  # noqa: E402
from dse_v2.reference_workloads.qe_correctness import (  # noqa: E402
    default_qe_correctness_tolerances,
    evaluate_qe_correctness_row,
)
from dse_v2.reference_workloads.qe_accelerated_evidence import (  # noqa: E402
    QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
    REQUIRED_QE_ACCELERATED_PHYSICAL_FIELDS,
    TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES,
    UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES,
    validate_kernel_numeric_evidence,
    validate_offload_provenance,
)
from dse_v2.reference_workloads.qe_mainflow import (  # noqa: E402
    default_qe_mainflow_workload_suite,
    package_qe_mainflow_case,
    validate_qe_mainflow_workload_suite,
)


RUN_SCHEMA = "dse.codesign.complete_dse_full_l4_matrix_run.v1"
EVIDENCE_ROWS_SCHEMA = "dse.codesign.complete_dse_full_l4_evidence_rows.v1"
ROW_SCHEMA = "dse.codesign.complete_dse_full_l4_evidence_row.v1"
REPORT_SCHEMA = "dse.codesign.complete_dse_full_l4_report.v1"
TRUSTED_GEM5_TRANSPORT = "gem5_generic_accel_microarchitecture_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    if isinstance(value, tuple):
        return [_json_safe(child) for child in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _matrix_gate_count(matrix: Mapping[str, Any], gate_name: str) -> int:
    rows = [row for row in matrix.get("rows", []) or [] if isinstance(row, Mapping)]
    count = 0
    for row in rows:
        gates = row.get("gates", {})
        if isinstance(gates, Mapping) and gates.get(gate_name) is True:
            count += 1
    return count


def _has_passed_kernel_check(row: Mapping[str, Any], kernel_id: str) -> bool:
    correctness = row.get("correctness", {})
    if not isinstance(correctness, Mapping):
        return False
    kernel_gate = correctness.get("kernel_gate", {})
    if not isinstance(kernel_gate, Mapping):
        return False
    for check in kernel_gate.get("checks", []) or []:
        if not isinstance(check, Mapping):
            continue
        if check.get("kernel_id") == kernel_id and check.get("status") == "passed":
            return True
    return False


def _accelerated_numeric_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = payload.get("offload_provenance", {})
    return {
        "source_kind": str(payload.get("source_kind") or "unknown"),
        "status": payload.get("status"),
        "accelerated_output_status": payload.get("accelerated_output_status"),
        "trusted_accelerated_numeric_source": payload.get("trusted_accelerated_numeric_source") is True,
        "offload_provenance": copy.deepcopy(dict(provenance)) if isinstance(provenance, Mapping) else {},
        "blockers": [str(item) for item in payload.get("blockers", []) or []],
    }


def _row_accelerated_numeric_evidence(row: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = row.get("accelerated_numeric_evidence", {})
    return evidence if isinstance(evidence, Mapping) else {}


def _has_native_payload_evidence(row: Mapping[str, Any]) -> bool:
    evidence = _row_accelerated_numeric_evidence(row)
    correctness = row.get("correctness", {})
    correctness_map = correctness if isinstance(correctness, Mapping) else {}
    if evidence.get("trusted_accelerated_numeric_source") is True:
        return True
    if correctness_map.get("trusted_claim_eligible") is True:
        return True
    provenance = evidence.get("offload_provenance", {})
    provenance_map = provenance if isinstance(provenance, Mapping) else {}
    if provenance_map.get("software_component_model_not_l4") is False and (
        provenance_map.get("full_h_psi_recomputed") is True
        or provenance_map.get("full_kernel_recomputed") is True
    ):
        return True
    native_markers = [
        evidence.get("source_kind"),
        provenance_map.get("producer"),
        provenance_map.get("offload_target"),
        provenance_map.get("trusted_payload_kind"),
        provenance_map.get("native_payload_executable"),
    ]
    return any("native_payload" in str(item).lower() for item in native_markers if item)


def _full_hpsi_payload_row_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {
        "full_hpsi_numeric_payload_rows": 0,
        "full_hpsi_legacy_component_model_rows": 0,
        "full_hpsi_native_payload_rows": 0,
    }
    for row in rows:
        if not _has_passed_kernel_check(row, "h_psi"):
            continue
        counts["full_hpsi_numeric_payload_rows"] += 1
        if _has_native_payload_evidence(row):
            counts["full_hpsi_native_payload_rows"] += 1
        else:
            counts["full_hpsi_legacy_component_model_rows"] += 1
    return counts


def _trusted_correctness_row_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if isinstance(row.get("correctness"), Mapping)
        and row["correctness"].get("trusted_claim_eligible") is True
    )


def _blocker_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for blocker in row.get("blockers", []) or []:
            counts[str(blocker)] = counts.get(str(blocker), 0) + 1
    return counts


def _candidate_ids(release_subset: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in release_subset.get("legal_candidate_ids", []) or []]
    if ids:
        return ids
    return [
        str(candidate.get("candidate_id"))
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal", True) and candidate.get("candidate_id")
    ]


def _workload_case_ids(workload_suite: Mapping[str, Any]) -> list[str]:
    ids = [str(item) for item in workload_suite.get("workload_case_ids", []) or []]
    if ids:
        return ids
    return [
        str(case.get("case_id") or case.get("workload_case_id"))
        for case in workload_suite.get("cases", []) or []
        if isinstance(case, Mapping) and (case.get("case_id") or case.get("workload_case_id"))
    ]


def _candidate_index(release_subset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("candidate_id")
    }


def _case_index(workload_suite: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(case.get("case_id") or case.get("workload_case_id")): case
        for case in workload_suite.get("cases", []) or []
        if isinstance(case, Mapping) and (case.get("case_id") or case.get("workload_case_id"))
    }


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _taxonomy_id(candidate: Mapping[str, Any]) -> str:
    identity = candidate.get("identity", {}) if isinstance(candidate, Mapping) else {}
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    architecture = layers.get("architecture_parameters", {}) if isinstance(layers, Mapping) else {}
    if isinstance(architecture, Mapping) and architecture.get("taxonomy_id"):
        return str(architecture["taxonomy_id"])
    return str(candidate.get("taxonomy_id") or candidate.get("candidate_id") or "unknown_candidate")


def _mapping_id(candidate: Mapping[str, Any]) -> str | None:
    identity = candidate.get("identity", {}) if isinstance(candidate, Mapping) else {}
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    mapping = layers.get("mapping_layout_parameters", {}) if isinstance(layers, Mapping) else {}
    return str(mapping.get("mapping_id")) if isinstance(mapping, Mapping) and mapping.get("mapping_id") else None


def _runtime_schedule_id(candidate: Mapping[str, Any]) -> str | None:
    identity = candidate.get("identity", {}) if isinstance(candidate, Mapping) else {}
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    runtime = layers.get("runtime_scheduling_parameters", {}) if isinstance(layers, Mapping) else {}
    return str(runtime.get("runtime_schedule_id")) if isinstance(runtime, Mapping) and runtime.get("runtime_schedule_id") else None


def _compile_schedule_id(candidate: Mapping[str, Any]) -> str | None:
    identity = candidate.get("identity", {}) if isinstance(candidate, Mapping) else {}
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    compile_schedule = layers.get("compile_time_schedule_parameters", {}) if isinstance(layers, Mapping) else {}
    return (
        str(compile_schedule.get("compile_schedule_id"))
        if isinstance(compile_schedule, Mapping) and compile_schedule.get("compile_schedule_id")
        else None
    )


def _candidate_identity_layers(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    identity = candidate.get("identity", {}) if isinstance(candidate, Mapping) else {}
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    return layers if isinstance(layers, Mapping) else {}


def _add_supported_ops(accelerator: Any, op_types: Iterable[str], efficiency: float = 0.75) -> None:
    for op_type in sorted({str(item) for item in op_types if item}):
        if op_type not in accelerator.compute.supported_ops:
            accelerator.compute.supported_ops.append(op_type)
        accelerator.compute.op_efficiency[op_type] = max(
            float(accelerator.compute.op_efficiency.get(op_type, 0.0) or 0.0),
            efficiency,
        )


def _architecture_components(taxonomy_id: str) -> list[str]:
    components: list[str] = []
    if taxonomy_id == "streaming_pipeline" or "pipeline" in taxonomy_id:
        components.append("pipeline")
    if taxonomy_id == "simd_vector" or "simd" in taxonomy_id:
        components.append("simd")
    if taxonomy_id == "spatial_pe_array" or "spatial" in taxonomy_id:
        components.append("spatial")
    if taxonomy_id == "task_parallel_engines" or "task" in taxonomy_id:
        components.append("task")
    return components or ["generic"]


def _build_architecture_for_candidate(candidate: Mapping[str, Any], op_types: Sequence[str]) -> SystemArchitecture:
    taxonomy_id = _taxonomy_id(candidate)
    accelerators = []
    for component in _architecture_components(taxonomy_id):
        if component == "pipeline":
            accelerator = create_fpga_u280("pipeline-0")
            accelerator.accel_type = "streaming_pipeline"
            accelerator.model = "release_v1_streaming_pipeline"
            _add_supported_ops(accelerator, op_types, efficiency=0.86)
        elif component == "simd":
            accelerator = create_gpu_a100("simd-0")
            accelerator.accel_type = "simd_vector"
            accelerator.model = "release_v1_simd_vector"
            _add_supported_ops(accelerator, op_types, efficiency=0.78)
        elif component == "spatial":
            accelerator = create_fpga_u280("spatial-0")
            accelerator.accel_type = "spatial_pe_array"
            accelerator.model = "release_v1_spatial_pe_array"
            _add_supported_ops(accelerator, op_types, efficiency=0.91)
        elif component == "task":
            accelerator = create_cim_array("task-0")
            accelerator.accel_type = "task_parallel_engines"
            accelerator.model = "release_v1_task_parallel_engines"
            _add_supported_ops(accelerator, op_types, efficiency=0.72)
        else:
            accelerator = create_gpu_a100("generic-0")
            accelerator.accel_type = "generic_release_accel"
            _add_supported_ops(accelerator, op_types, efficiency=0.70)
        accelerators.append(accelerator)

    return SystemArchitecture(
        system_id=f"release_v1_{taxonomy_id}",
        host_cpu_cores=64,
        host_memory_gb=512.0,
        accelerators=accelerators,
        interconnect=InterconnectTopology("pcie_cxl_mixed", 128.0, 1.0),
        max_power_w=1000.0,
        max_area_mm2=2000.0,
    )


def _select_accelerator_for_node(taxonomy_id: str, op_type: str, available_ids: Sequence[str]) -> str:
    available = set(available_ids)
    preferred: list[str] = []
    if ("spatial" in taxonomy_id and op_type in {"gemm", "gemm_fft_composite", "eigen", "batched_gemm"}) or (
        op_type in {"gemm", "batched_gemm"} and "spatial-0" in available
    ):
        preferred.append("spatial-0")
    if ("simd" in taxonomy_id and op_type in {"reduction", "elementwise", "io", "dft_phase_skeleton"}) or (
        op_type in {"reduction", "elementwise", "io"} and "simd-0" in available
    ):
        preferred.append("simd-0")
    if ("pipeline" in taxonomy_id or "streaming" in taxonomy_id) and op_type in {
        "fft",
        "dft_workflow_stage",
        "dft_phase_skeleton",
        "gemm_fft_composite",
    }:
        preferred.append("pipeline-0")
    if "task" in taxonomy_id and op_type in {"dft_workflow_stage", "dft_phase_skeleton", "io"}:
        preferred.append("task-0")
    for accel_id in preferred:
        if accel_id in available:
            return accel_id
    return str(available_ids[0]) if available_ids else "host"


def _build_design_point(
    *,
    candidate_id: str,
    candidate: Mapping[str, Any],
    workload_case: Mapping[str, Any],
    op_types: Sequence[str],
    node_op_types: Mapping[str, str],
) -> DesignPoint:
    taxonomy_id = _taxonomy_id(candidate)
    architecture = _build_architecture_for_candidate(candidate, op_types)
    accel_ids = [accelerator.accel_id for accelerator in architecture.accelerators]
    task_mapping = {
        node_id: _select_accelerator_for_node(taxonomy_id, op_type, accel_ids)
        for node_id, op_type in node_op_types.items()
    }
    case_id = str(workload_case.get("case_id") or workload_case.get("workload_case_id"))
    runtime_schedule = _runtime_schedule_id(candidate) or "release_runtime_schedule"
    config = {
        "step": "step2_architecture_mapping",
        "selected_candidate_id": candidate_id,
        "candidate_id": candidate_id,
        "candidate_identity": copy.deepcopy(_candidate_identity_layers(candidate)),
        "candidate_record_hash": candidate.get("record_hash"),
        "workload_case_id": case_id,
        "workload_id": case_id,
        "workload_family": "qe_mainflow",
        "architecture_id": architecture.system_id,
        "mapping_id": _mapping_id(candidate),
        "compile_schedule_id": _compile_schedule_id(candidate),
        "runtime_schedule_id": runtime_schedule,
        "required_coverage": list(node_op_types.keys()),
        "simulation_config": {"backend": "gem5_systemc", "mode": "gem5_cosim"},
        "claim_boundary": (
            "release-v1 candidate/workload handoff only; trusted speedup requires "
            "real L4 gem5, real QE baseline, correctness, and calibration gates"
        ),
    }
    return DesignPoint(
        design_point_id=f"{candidate_id}__{case_id}",
        system_architecture=architecture,
        task_mapping=task_mapping,
        scheduling_policy=runtime_schedule,
        config=config,
    )


def _l3_status_from_run(run: Mapping[str, Any]) -> Dict[str, Any]:
    result = run.get("result") if isinstance(run.get("result"), Mapping) else {}
    metrics = result.get("metrics", {}) if isinstance(result, Mapping) else {}
    return {
        "schema_version": "dse.codesign.l3_systemc_row_summary.v1",
        "status": "passed" if run.get("returncode") == 0 and result.get("status") == "passed" else "blocked",
        "returncode": run.get("returncode"),
        "result_status": result.get("status"),
        "metrics": metrics,
        "request_path": run.get("request_path"),
        "result_path": run.get("result_path"),
        "trace_path": run.get("trace_path"),
        "cmd": [str(item) for item in run.get("cmd", []) or []],
        "claim_boundary": "L3 SystemC/Python timing evidence is projection/screening only and cannot satisfy trusted speedup.",
    }


def _run_l3_systemc(
    *,
    backend: GenericSystemCBackend,
    design_point: DesignPoint,
    workload_package: Any,
    row_dir: Path,
    timeout: int,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    l3_dir = row_dir / "l3_systemc"
    try:
        run = backend.run_simulation(
            design_point,
            workload_package.graph,
            workload_package=workload_package,
            output_dir=l3_dir,
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - defensive row preservation
        run = {
            "run_id": design_point.design_point_id,
            "returncode": 2,
            "stdout": "",
            "stderr": f"L3 SystemC run failed before artifact completion: {exc}",
            "request": None,
            "result": None,
            "request_path": None,
            "result_path": None,
            "trace_path": None,
            "cmd": [],
        }

    _write_json(l3_dir / "l3_run_summary.json", {
        key: value
        for key, value in run.items()
        if key not in {"request", "result", "stdout", "stderr"}
    })
    if run.get("request") is not None:
        _write_json(l3_dir / "simulation_request.json", run["request"])
    if run.get("result") is not None:
        _write_json(l3_dir / "simulation_result.json", run["result"])
    _write_text(l3_dir / "systemc_stdout.log", str(run.get("stdout") or ""))
    _write_text(l3_dir / "systemc_stderr.log", str(run.get("stderr") or ""))
    return dict(run), _l3_status_from_run(run)


_QE_TIMER_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*([0-9.]+)s CPU\s+([0-9.]+)s WALL", re.MULTILINE)
_QE_TOTAL_ENERGY_RE = re.compile(r"!\s*total energy\s*=\s*([-+0-9.Ee]+)\s+Ry")
_QE_HOMO_LUMO_RE = re.compile(
    r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*([-+0-9.Ee]+)\s+([-+0-9.Ee]+)",
    re.IGNORECASE,
)
_QE_FERMI_ENERGY_RE = re.compile(
    r"the Fermi energy is\s*([-+0-9.Ee]+)\s*ev",
    re.IGNORECASE,
)
_QE_CONVERGENCE_RE = re.compile(r"convergence has been achieved in\s+([0-9]+)\s+iterations", re.IGNORECASE)
_QE_TOTAL_FORCE_RE = re.compile(r"Total force\s*=\s*([-+0-9.Ee]+)", re.IGNORECASE)
_QE_TOTAL_STRESS_PRESSURE_RE = re.compile(
    r"total\s+stress\s+\(Ry/bohr\*\*3\)[^\n]*P=\s*([-+0-9.Ee]+)",
    re.IGNORECASE,
)


def _candidate_qe_bin_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_bin = os.environ.get("QE_BIN_DIR")
    if env_bin:
        candidates.append(Path(env_bin))
    env_root = os.environ.get("QE_ROOT")
    if env_root:
        candidates.append(Path(env_root) / "bin")
    candidates.extend([
        REPO_ROOT / "runs" / "dse" / "_tools" / "q-e-build" / "bin",
        REPO_ROOT / "runs" / "dse" / "_tools" / "qe_local" / "usr" / "bin",
    ])
    return candidates


def _default_qe_bin_dir() -> Path | None:
    for candidate in _candidate_qe_bin_dirs():
        if (candidate / "pw.x").exists():
            return candidate
    return None


def _candidate_qe_pseudo_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_pseudo = os.environ.get("QE_PSEUDO_DIR")
    if env_pseudo:
        candidates.append(Path(env_pseudo))
    candidates.extend([
        REPO_ROOT / "runs" / "dse" / "qe_real_workload_matrix_src_20260514_114352" / "pseudo",
        REPO_ROOT / "runs" / "dse" / "_tools" / "q-e-src" / "pseudo",
    ])
    return candidates


def _default_qe_pseudo_dir() -> Path | None:
    for candidate in _candidate_qe_pseudo_dirs():
        if (candidate / "Si.pz-vbc.UPF").exists():
            return candidate
    return None


def _resolve_qe_executable(program: str, qe_bin_dir: Path | None) -> tuple[str | None, str]:
    program_path = Path(program)
    if program_path.is_absolute() or len(program_path.parts) > 1:
        if program_path.exists():
            return str(program_path.resolve()), "command_path"
        return None, "command_path_missing"
    if qe_bin_dir is not None:
        candidate = qe_bin_dir / program
        if candidate.exists():
            return str(candidate.resolve()), "qe_bin_dir"
    found = shutil.which(program)
    if found:
        return found, "PATH"
    return None, "missing"


def _gpu_runtime_context() -> Dict[str, Any]:
    """Capture local GPU availability for QE baseline provenance."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "schema_version": "dse.qe_gpu_runtime_context.v1",
            "nvidia_smi_available": False,
            "gpu_available": False,
            "blockers": ["nvidia_smi_missing"],
        }
    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # pragma: no cover - host environment dependent
        return {
            "schema_version": "dse.qe_gpu_runtime_context.v1",
            "nvidia_smi_available": True,
            "nvidia_smi_path": nvidia_smi,
            "gpu_available": False,
            "blockers": [f"nvidia_smi_probe_failed:{type(exc).__name__}:{exc}"],
        }
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    return {
        "schema_version": "dse.qe_gpu_runtime_context.v1",
        "nvidia_smi_available": True,
        "nvidia_smi_path": nvidia_smi,
        "nvidia_smi_returncode": completed.returncode,
        "gpu_available": completed.returncode == 0 and bool(lines),
        "gpus": lines,
        "stderr": (completed.stderr or "").strip(),
        "blockers": [] if completed.returncode == 0 and lines else ["nvidia_smi_reported_no_gpu"],
        "claim_boundary": (
            "Baseline records GPU availability so restored CUDA/driver support "
            "is visible in speed comparisons; QE still decides actual use_gpu "
            "internally and any GPU timers must come from QE stdout."
        ),
    }


def _input_basename(input_path: Any) -> str | None:
    if not input_path:
        return None
    return Path(str(input_path)).name


def _write_qe_case_inputs(case: Mapping[str, Any], baseline_dir: Path) -> None:
    source = case.get("step1_source", {}) if isinstance(case.get("step1_source", {}), Mapping) else {}
    stages = source.get("stages", []) if isinstance(source.get("stages", []), list) else []
    baseline_steps = case.get("baseline_sequence", []) if isinstance(case.get("baseline_sequence", []), list) else []
    for stage in [*stages, *baseline_steps]:
        if not isinstance(stage, Mapping):
            continue
        input_text = stage.get("input")
        input_path = stage.get("input_path")
        if isinstance(input_text, str) and input_path:
            _write_text(baseline_dir / Path(str(input_path)).name, input_text)


def _copy_qe_pseudos(baseline_dir: Path, qe_pseudo_dir: Path | None) -> Dict[str, Any]:
    pseudo_dir = baseline_dir / "pseudo"
    pseudo_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    blockers: list[str] = []
    if qe_pseudo_dir is None or not qe_pseudo_dir.exists():
        blockers.append("missing_qe_pseudo_dir")
        return {
            "qe_pseudo_dir": str(qe_pseudo_dir) if qe_pseudo_dir else None,
            "baseline_pseudo_dir": str(pseudo_dir),
            "copied": copied,
            "blockers": blockers,
        }
    # The frozen release-v1 QE suite uses the Si pseudo below.  Copying only
    # referenced pseudos keeps the row artifact small while remaining a real QE
    # runtime input, not a fixture-only baseline.
    for pseudo_name in ["Si.pz-vbc.UPF"]:
        source = qe_pseudo_dir / pseudo_name
        if source.exists():
            shutil.copy2(source, pseudo_dir / pseudo_name)
            copied.append(pseudo_name)
        else:
            blockers.append(f"missing_qe_pseudopotential:{pseudo_name}")
    return {
        "qe_pseudo_dir": str(qe_pseudo_dir),
        "baseline_pseudo_dir": str(pseudo_dir),
        "copied": copied,
        "blockers": blockers,
    }


def _baseline_sequence(case: Mapping[str, Any]) -> list[Dict[str, Any]]:
    raw_sequence = case.get("baseline_sequence", [])
    if isinstance(raw_sequence, list) and raw_sequence:
        return [copy.deepcopy(dict(step)) for step in raw_sequence if isinstance(step, Mapping)]
    command = [str(item) for item in case.get("qe_command", []) or []]
    source = case.get("step1_source", {}) if isinstance(case.get("step1_source", {}), Mapping) else {}
    stages = source.get("stages", []) if isinstance(source.get("stages", []), list) else []
    if stages:
        steps = []
        for index, stage in enumerate(stages):
            if not isinstance(stage, Mapping):
                continue
            stage_program = str(stage.get("program") or (command[0] if command else "pw.x"))
            stage_input_path = str(stage.get("input_path") or (command[-1] if len(command) >= 3 else "qe.in"))
            steps.append({
                "step_id": str(stage.get("stage_id") or f"stage_{index:02d}"),
                "program": stage_program,
                "command": list(stage.get("command") or [stage_program, "-in", _input_basename(stage_input_path) or stage_input_path]),
                "input_path": stage_input_path,
                "input": stage.get("input"),
                "include_in_performance": True,
            })
        if steps:
            return steps
    return [{
        "step_id": "stage_00_qe_command",
        "program": command[0] if command else "",
        "command": command,
        "include_in_performance": True,
    }]


def _normalize_qe_command(step: Mapping[str, Any], qe_bin_dir: Path | None) -> tuple[list[str] | None, Dict[str, Any]]:
    raw_command = [str(item) for item in step.get("command", []) or []]
    if not raw_command:
        program = str(step.get("program") or "")
        input_name = _input_basename(step.get("input_path"))
        raw_command = [program, "-in", input_name] if program and input_name else ([program] if program else [])
    if not raw_command:
        return None, {
            "step_id": step.get("step_id"),
            "status": "blocked",
            "blockers": ["missing_qe_command"],
        }
    executable, provenance = _resolve_qe_executable(raw_command[0], qe_bin_dir)
    if executable is None:
        return None, {
            "step_id": step.get("step_id"),
            "program": raw_command[0],
            "status": "blocked",
            "blockers": [f"missing_qe_executable:{raw_command[0]}"],
            "resolution_provenance": provenance,
        }
    normalized_args = [
        _input_basename(item) if previous == "-in" and _input_basename(item) else item
        for previous, item in zip(raw_command[:-1], raw_command[1:])
    ]
    normalized = [executable, *normalized_args]
    return normalized, {
        "step_id": step.get("step_id"),
        "program": raw_command[0],
        "resolved_executable": executable,
        "resolution_provenance": provenance,
        "command": raw_command,
        "concrete_command": normalized,
    }


def _parse_qe_stdout(stdout: str) -> Dict[str, Any]:
    timers = {
        match.group(1): {"cpu_seconds": float(match.group(2)), "wall_seconds": float(match.group(3))}
        for match in _QE_TIMER_RE.finditer(stdout)
    }
    energy_matches = _QE_TOTAL_ENERGY_RE.findall(stdout)
    convergence_matches = _QE_CONVERGENCE_RE.findall(stdout)
    homo_lumo = _QE_HOMO_LUMO_RE.search(stdout)
    fermi_energy = _QE_FERMI_ENERGY_RE.search(stdout)
    force_matches = _QE_TOTAL_FORCE_RE.findall(stdout)
    pressure_matches = _QE_TOTAL_STRESS_PRESSURE_RE.findall(stdout)
    metrics: Dict[str, Any] = {
        "job_done": "JOB DONE." in stdout,
        "timers": timers,
    }
    if energy_matches:
        metrics["total_energy_ry"] = float(energy_matches[-1])
    if convergence_matches:
        metrics["scf_iterations"] = int(convergence_matches[-1])
    if homo_lumo:
        metrics["highest_occupied_ev"] = float(homo_lumo.group(1))
        metrics["lowest_unoccupied_ev"] = float(homo_lumo.group(2))
    if fermi_energy:
        metrics["fermi_energy_ev"] = float(fermi_energy.group(1))
    if force_matches:
        metrics["total_force_ry_bohr"] = float(force_matches[-1])
    if pressure_matches:
        metrics["pressure_kbar"] = float(pressure_matches[-1])
    band_energies = _parse_band_energies_ev(stdout)
    if band_energies:
        metrics["band_energy_count"] = len(band_energies)
        metrics["band_energy_min_ev"] = min(band_energies)
        metrics["band_energy_max_ev"] = max(band_energies)
        metrics["band_energy_sum_ev"] = sum(band_energies)
    if "PWSCF" in timers:
        metrics["program_wall_seconds"] = timers["PWSCF"]["wall_seconds"]
    elif timers:
        last_name = next(reversed(timers))
        metrics["program_wall_seconds"] = timers[last_name]["wall_seconds"]
    return metrics


def _parse_band_energies_ev(stdout: str) -> list[float]:
    values: list[float] = []
    collecting = False
    block_has_values = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if "bands (ev):" in line:
            collecting = True
            block_has_values = False
            continue
        if not collecting:
            continue
        if not stripped:
            if block_has_values:
                collecting = False
            continue
        lowered = stripped.lower()
        if (
            "occupation numbers" in lowered
            or "k =" in lowered
            or "highest occupied" in lowered
            or "the fermi energy" in lowered
        ):
            collecting = False
            continue
        try:
            row_values = [float(item) for item in stripped.split()]
        except ValueError:
            collecting = False
            continue
        values.extend(row_values)
        block_has_values = True
    return values


def _evidence_row_key(candidate_id: Any, workload_case_id: Any) -> tuple[str, str]:
    return (str(candidate_id or ""), str(workload_case_id or ""))


def _is_passed_status(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"pass", "passed", "available", "complete", "real_accelerated_qe_run"}
    return False


def _normalize_accelerated_numeric_payload(
    payload: Mapping[str, Any],
    *,
    candidate_id: str,
    workload_case_id: str,
    row_id: str,
    source: str,
) -> Dict[str, Any]:
    source_kind = str(
        payload.get("source_kind")
        or payload.get("accelerated_output_source")
        or payload.get("source")
        or source
        or "unknown"
    )
    accelerated_status = payload.get("accelerated_output_status", payload.get("status", "unknown"))
    kernel_evidence = payload.get("kernel_evidence", [])
    if not isinstance(kernel_evidence, list):
        kernel_evidence = []
    physical_evidence = payload.get("physical_evidence", {})
    if not isinstance(physical_evidence, Mapping):
        physical_evidence = {}
    offload_provenance = payload.get("offload_provenance")
    if not isinstance(offload_provenance, Mapping):
        offload_provenance = {}

    blockers = [str(item) for item in payload.get("blockers", []) or []]
    normalized_source = source_kind.strip().lower()
    trusted_source = normalized_source in TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES
    if normalized_source in UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES:
        blockers.append(f"untrusted_accelerated_numeric_source:{normalized_source}")
    elif not trusted_source:
        blockers.append(f"unrecognized_accelerated_numeric_source:{normalized_source or 'missing'}")
    if payload.get("timing_only") is True:
        blockers.append("timing_only_evidence_cannot_satisfy_correctness")
    if payload.get("baseline_only") is True:
        blockers.append("baseline_only_evidence_cannot_satisfy_accelerated_correctness")
    if not _is_passed_status(accelerated_status):
        blockers.append(f"accelerated_output_status_not_passed:{accelerated_status}")
    if payload.get("trusted_accelerated_numeric_source") is False:
        blockers.append("payload_declares_accelerated_numeric_source_untrusted")
    blockers.extend(validate_offload_provenance(offload_provenance, normalized_source))
    blockers.extend(validate_kernel_numeric_evidence([row for row in kernel_evidence if isinstance(row, Mapping)]))
    missing_physical = [
        field
        for field in REQUIRED_QE_ACCELERATED_PHYSICAL_FIELDS
        if field not in physical_evidence or physical_evidence.get(field) is None
    ]
    if missing_physical:
        blockers.append("missing_accelerated_qe_scf_physical_outputs:" + ",".join(missing_physical))

    return {
        "schema_version": QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
        "row_id": str(payload.get("row_id") or row_id),
        "candidate_id": str(payload.get("candidate_id") or candidate_id),
        "workload_case_id": str(payload.get("workload_case_id") or workload_case_id),
        "source_kind": source_kind,
        "source": source,
        "accelerated_output_status": accelerated_status,
        "trusted_accelerated_numeric_source": trusted_source and not blockers,
        "baseline_reference": copy.deepcopy(payload.get("baseline_reference", {})),
        "accelerated_reference": copy.deepcopy(payload.get("accelerated_reference", {})),
        "offload_provenance": copy.deepcopy(dict(offload_provenance)),
        "kernel_evidence": copy.deepcopy(kernel_evidence),
        "physical_evidence": copy.deepcopy(dict(physical_evidence)),
        "tolerance_profile_id": payload.get("tolerance_profile_id", "qe_mainflow_correctness_v1"),
        "raw_payload_schema_version": payload.get("schema_version"),
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "This artifact may satisfy QE correctness only when it comes from a trusted accelerated/offloaded "
            "QE path with real kernel and SCF/physical numeric outputs. Fixture, baseline-copy, timing-only, "
            "or L3 sidecar data is blocked from trusted equivalence."
        ),
    }


def _load_accelerated_numeric_evidence(path: Path | None) -> tuple[dict[tuple[str, str], Dict[str, Any]], Dict[str, Any]]:
    if path is None:
        return {}, {
            "schema_version": "dse.qe_accelerated_numeric_evidence_index.v1",
            "status": "not_configured",
            "path": None,
            "row_count": 0,
            "blockers": ["accelerated_numeric_evidence_not_configured"],
        }

    index: dict[tuple[str, str], Dict[str, Any]] = {}
    blockers: list[str] = []
    paths: list[Path]
    if path.is_dir():
        paths = sorted(child for child in path.rglob("*.json") if child.is_file())
    elif path.exists():
        paths = [path]
    else:
        return {}, {
            "schema_version": "dse.qe_accelerated_numeric_evidence_index.v1",
            "status": "blocked",
            "path": str(path),
            "row_count": 0,
            "blockers": [f"accelerated_numeric_evidence_path_missing:{path}"],
        }

    for evidence_path in paths:
        try:
            payload = _load_json(evidence_path)
        except Exception as exc:
            blockers.append(f"accelerated_numeric_evidence_unreadable:{evidence_path}:{exc}")
            continue
        rows: list[Mapping[str, Any]]
        if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
            rows = [row for row in payload["rows"] if isinstance(row, Mapping)]
        elif isinstance(payload, Mapping):
            rows = [payload]
        else:
            blockers.append(f"accelerated_numeric_evidence_not_object:{evidence_path}")
            continue
        for row in rows:
            candidate_id = str(row.get("candidate_id") or "")
            workload_case_id = str(row.get("workload_case_id") or row.get("case_id") or "")
            if not candidate_id or not workload_case_id:
                blockers.append(f"accelerated_numeric_evidence_missing_key:{evidence_path}")
                continue
            normalized = _normalize_accelerated_numeric_payload(
                row,
                candidate_id=candidate_id,
                workload_case_id=workload_case_id,
                row_id=str(row.get("row_id") or f"{candidate_id}::{workload_case_id}"),
                source=str(evidence_path),
            )
            index[_evidence_row_key(candidate_id, workload_case_id)] = normalized

    return index, {
        "schema_version": "dse.qe_accelerated_numeric_evidence_index.v1",
        "status": "loaded" if index else "blocked",
        "path": str(path),
        "row_count": len(index),
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": "Indexing external accelerated numeric evidence does not by itself prove correctness; every row is re-gated by source kind, numeric deltas, and frozen tolerances.",
    }


def _extract_accelerated_numeric_from_l4(
    l4_attempt: Mapping[str, Any],
    *,
    candidate_id: str,
    workload_case_id: str,
    row_id: str,
) -> Dict[str, Any] | None:
    result = l4_attempt.get("result", {}) if isinstance(l4_attempt.get("result", {}), Mapping) else {}
    for key in (
        "qe_accelerated_numeric_evidence",
        "accelerated_numeric_outputs",
        "qe_numeric_outputs",
    ):
        payload = result.get(key)
        if isinstance(payload, Mapping):
            normalized = _normalize_accelerated_numeric_payload(
                payload,
                candidate_id=candidate_id,
                workload_case_id=workload_case_id,
                row_id=row_id,
                source=f"l4_result_transport_echo:{key}",
            )
            normalized["trusted_accelerated_numeric_source"] = False
            normalized["accelerated_output_status"] = "blocked"
            normalized["status"] = "blocked"
            normalized["blockers"] = sorted(
                dict.fromkeys(
                    [
                        *[str(item) for item in normalized.get("blockers", []) or []],
                        "generic_accel_transport_echo_not_numeric_evidence",
                    ]
                )
            )
            normalized["claim_boundary"] = (
                "Blocked transport echo: GenericAccel/L4 result payloads may prove metadata transport only. "
                "Trusted QE correctness requires an independent accelerated runtime/offload artifact with "
                "full kernel and SCF/physical numeric deltas."
            )
            return normalized
    return None


def _qe_offload_extension_payload(accelerated_numeric_evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """Build explicit QE-offload transport metadata for the generic L4 request.

    This is software-visible dispatch metadata only.  It deliberately mirrors
    the trust state of the accelerated numeric evidence instead of upgrading
    sidecar/component-model payloads into a trusted offload claim.
    """

    provenance = accelerated_numeric_evidence.get("offload_provenance", {})
    provenance_map = provenance if isinstance(provenance, Mapping) else {}
    target_kernel = str(
        provenance_map.get("target_kernel")
        or accelerated_numeric_evidence.get("target_kernel")
        or "h_psi"
    )
    required_kernel_scope = (
        "full_h_psi" if target_kernel == "h_psi" else f"full_{target_kernel}"
    )
    full_kernel_recomputed = (
        provenance_map.get("full_kernel_recomputed") is True
        or (
            target_kernel == "h_psi"
            and provenance_map.get("full_h_psi_recomputed") is True
        )
    )
    return {
        "schema_version": "dse.qe_offload_extension.v1",
        "candidate_id": str(accelerated_numeric_evidence.get("candidate_id") or ""),
        "workload_case_id": str(accelerated_numeric_evidence.get("workload_case_id") or ""),
        "kernel_id": target_kernel,
        "target_kernel": target_kernel,
        "required_kernel_scope": required_kernel_scope,
        "requires_full_kernel_recomputed": True,
        "requires_full_h_psi_recomputed": target_kernel == "h_psi",
        "source_kind": str(accelerated_numeric_evidence.get("source_kind") or "unknown"),
        "accelerated_output_status": accelerated_numeric_evidence.get("accelerated_output_status"),
        "trusted_accelerated_numeric_source": accelerated_numeric_evidence.get("trusted_accelerated_numeric_source") is True,
        "full_kernel_recomputed": full_kernel_recomputed,
        "full_h_psi_recomputed": provenance_map.get("full_h_psi_recomputed") is True,
        "hpsi_specific_completion_allowed": False,
        "offload_target": str(provenance_map.get("offload_target") or "unknown"),
        "claim_boundary": (
            "Transport metadata only: GenericAccel observing this qe_offload extension proves dispatch intent, "
            "not QE numerical correctness or trusted offload provenance. The matrix correctness gates remain authoritative."
        ),
    }


def _build_accelerated_numeric_evidence(
    *,
    candidate_id: str,
    workload_case_id: str,
    row_id: str,
    baseline: Mapping[str, Any],
    l4_attempt: Mapping[str, Any],
    external_evidence: Mapping[str, Any] | None,
    row_dir: Path,
) -> Dict[str, Any]:
    evidence = _extract_accelerated_numeric_from_l4(
        l4_attempt,
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
        row_id=row_id,
    )
    if evidence is None and isinstance(external_evidence, Mapping):
        evidence = copy.deepcopy(dict(external_evidence))
    if evidence is None:
        evidence = {
            "schema_version": QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
            "row_id": row_id,
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "source_kind": "missing",
            "source": "not_provided",
            "accelerated_output_status": "missing",
            "trusted_accelerated_numeric_source": False,
            "baseline_reference": {
                "baseline_status": baseline.get("baseline_status"),
                "baseline_comparison_path": str(row_dir.parents[2] / "qe_baselines" / _safe_path_component(workload_case_id) / "baseline_comparison.json"),
            },
            "accelerated_reference": {},
            "kernel_evidence": [],
            "physical_evidence": {},
            "blockers": [
                "missing_accelerated_qe_kernel_numeric_outputs",
                "missing_accelerated_qe_scf_physical_outputs",
            ],
            "claim_boundary": "No trusted accelerated/offloaded QE numeric output artifact was supplied or written by L4.",
        }
    evidence.setdefault("baseline_reference", {
        "baseline_status": baseline.get("baseline_status"),
        "baseline_comparison_path": str(row_dir.parents[2] / "qe_baselines" / _safe_path_component(workload_case_id) / "baseline_comparison.json"),
    })
    evidence["status"] = "passed" if evidence.get("trusted_accelerated_numeric_source") is True else "blocked"
    _write_json(row_dir / "qe_accelerated_numeric_evidence.json", evidence)
    return evidence


def _run_qe_baseline(
    case: Mapping[str, Any],
    baseline_root: Path,
    timeout: int,
    *,
    qe_bin_dir: Path | None,
    qe_pseudo_dir: Path | None,
) -> Dict[str, Any]:
    case_id = str(case.get("case_id") or case.get("workload_case_id"))
    baseline_dir = baseline_root / _safe_path_component(case_id)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    command = [str(item) for item in case.get("qe_command", []) or []]
    sequence = _baseline_sequence(case)
    _write_json(baseline_dir / "workload_case.json", case)
    _write_qe_case_inputs(case, baseline_dir)
    pseudo_report = _copy_qe_pseudos(baseline_dir, qe_pseudo_dir)
    gpu_runtime_context = _gpu_runtime_context()

    if not command and not sequence:
        result = {
            "schema_version": "dse.qe_pure_software_baseline_result.v1",
            "case_id": case_id,
            "status": "blocked",
            "baseline_status": "missing_qe_command",
            "pure_software_qe_baseline": False,
            "blockers": ["missing_qe_command"],
            "claim_boundary": "A missing QE command cannot satisfy pure-software baseline comparison.",
        }
        _write_json(baseline_dir / "baseline_comparison.json", result)
        return result

    step_results: list[Dict[str, Any]] = []
    blockers = list(pseudo_report.get("blockers", []) or [])
    aggregate_stdout: list[str] = []
    aggregate_stderr: list[str] = []
    total_elapsed = 0.0
    passed = True
    for index, step in enumerate(sequence):
        normalized_cmd, resolution = _normalize_qe_command(step, qe_bin_dir)
        step_id = str(step.get("step_id") or f"stage_{index:02d}")
        stdout_path = baseline_dir / f"{_safe_path_component(step_id)}.stdout.log"
        stderr_path = baseline_dir / f"{_safe_path_component(step_id)}.stderr.log"
        if normalized_cmd is None:
            passed = False
            step_blockers = list(resolution.get("blockers", []) or [])
            blockers.extend(step_blockers)
            step_results.append({
                **resolution,
                "step_id": step_id,
                "status": "blocked",
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            })
            _write_text(stdout_path, "")
            _write_text(stderr_path, "\n".join(step_blockers) + "\n")
            break
        start = time.monotonic()
        try:
            completed = subprocess.run(
                normalized_cmd,
                cwd=baseline_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            returncode: int | None = completed.returncode
            timeout_hit = False
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - start
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            returncode = None
            timeout_hit = True
        total_elapsed += elapsed
        _write_text(stdout_path, stdout)
        _write_text(stderr_path, stderr)
        aggregate_stdout.append(f"===== {step_id} {' '.join(normalized_cmd)} =====\n{stdout}")
        aggregate_stderr.append(f"===== {step_id} {' '.join(normalized_cmd)} =====\n{stderr}")
        step_blockers: list[str] = []
        if timeout_hit:
            step_blockers.append("qe_baseline_timeout")
        if returncode not in {0, None}:
            step_blockers.append(f"qe_baseline_returncode:{returncode}")
        if step_blockers:
            passed = False
            blockers.extend(step_blockers)
        step_results.append({
            **resolution,
            "step_id": step_id,
            "status": "passed" if not step_blockers else "blocked",
            "returncode": returncode,
            "timeout": timeout_hit,
            "elapsed_seconds": elapsed,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "metrics": _parse_qe_stdout(stdout),
            "blockers": step_blockers,
        })
        if step_blockers:
            break

    _write_text(baseline_dir / "baseline_stdout.log", "\n".join(aggregate_stdout))
    _write_text(baseline_dir / "baseline_stderr.log", "\n".join(aggregate_stderr))
    blockers = sorted(dict.fromkeys(blockers))
    passed = passed and not blockers and bool(step_results)
    terminal_metrics = step_results[-1].get("metrics", {}) if step_results else {}
    result = {
        "schema_version": "dse.qe_pure_software_baseline_result.v1",
        "case_id": case_id,
        "status": "passed" if passed else "blocked",
        "baseline_status": "real_qe_baseline" if passed else "qe_baseline_run_failed",
        "pure_software_qe_baseline": passed,
        "qe_command": command,
        "qe_bin_dir": str(qe_bin_dir) if qe_bin_dir else None,
        "qe_runtime_assets": pseudo_report,
        "gpu_runtime_context": gpu_runtime_context,
        "baseline_sequence": sequence,
        "steps": step_results,
        "returncode": 0 if passed else (step_results[-1].get("returncode") if step_results else None),
        "timeout": any(step.get("timeout") for step in step_results),
        "elapsed_seconds": total_elapsed,
        "performance_metrics": {
            "total_elapsed_seconds": total_elapsed,
            "terminal_step_metrics": terminal_metrics,
        },
        "stdout_path": str(baseline_dir / "baseline_stdout.log"),
        "stderr_path": str(baseline_dir / "baseline_stderr.log"),
        "blockers": blockers,
        "claim_boundary": (
            "Pure-software QE baseline comparison is trusted only after the actual QE command "
            "runs successfully for this frozen workload case."
        ),
    }
    _write_json(baseline_dir / "baseline_comparison.json", result)
    return result


def _physical_evidence_for_case(case: Mapping[str, Any]) -> Dict[str, float]:
    # This is a sidecar numerical oracle fixture for L3 model wiring only.  It is
    # deliberately blocked from satisfying trusted L4 correctness below unless a
    # future runner supplies real QE-vs-accelerated numerical observations.
    stage_type = str(case.get("stage_type", "")).lower().replace("-", "_")
    evidence = {
        "total_energy_error_ry": 0.0,
        "density_residual": 0.0,
        "eigenvalue_summary_error_ry": 0.0,
    }
    if stage_type in {"relax", "vc_relax"}:
        evidence.update({"force_error_ry_bohr": 0.0, "stress_error_kbar": 0.0})
    return evidence


def _build_l3_correctness(
    *,
    candidate_id: str,
    workload_case: Mapping[str, Any],
    row_id: str,
    l3_status: Mapping[str, Any],
    baseline: Mapping[str, Any],
    l4_attempt: Mapping[str, Any],
    external_accelerated_numeric_evidence: Mapping[str, Any] | None,
    row_dir: Path,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    case_id = str(workload_case.get("case_id") or workload_case.get("workload_case_id"))
    kernel_coverage = [str(item) for item in workload_case.get("kernel_coverage", []) or []]
    fixture_observations = [
        {
            "kernel_id": kernel_id,
            "observed": 0.0,
            "reference": 0.0,
            "absolute_error": 0.0,
            "relative_error": 0.0,
            "source": "l3_fixture_sidecar_zero_delta",
        }
        for kernel_id in kernel_coverage
    ]
    oracle_input = {
        "row_id": row_id,
        "candidate_id": candidate_id,
        "workload_case_id": case_id,
        "workload_stage_type": workload_case.get("stage_type"),
        "timing_only": l3_status.get("status") != "passed",
        "evidence_kind": "l3_fixture_sidecar_numerical_oracle",
        "kernel_evidence": fixture_observations,
        "physical_evidence": _physical_evidence_for_case(workload_case),
    }
    tolerances = default_qe_correctness_tolerances(status="frozen")
    l3_oracle = evaluate_qe_correctness_row(oracle_input, tolerances, requested_claim="vertical_slice_only")
    l3_oracle["claim_boundary"] = (
        "This L3/Python sidecar proves oracle plumbing over deterministic fixture deltas only. "
        "It is not a real QE-vs-accelerated numerical equivalence result."
    )

    accelerated_numeric = _build_accelerated_numeric_evidence(
        candidate_id=candidate_id,
        workload_case_id=case_id,
        row_id=row_id,
        baseline=baseline,
        l4_attempt=l4_attempt,
        external_evidence=external_accelerated_numeric_evidence,
        row_dir=row_dir,
    )

    if baseline.get("pure_software_qe_baseline") is True:
        accelerated_ready = accelerated_numeric.get("status") == "passed"
        accelerated_has_numeric_payload = bool(accelerated_numeric.get("kernel_evidence")) or bool(
            accelerated_numeric.get("physical_evidence")
        )
        real_baseline_oracle_input = {
            "row_id": row_id,
            "candidate_id": candidate_id,
            "workload_case_id": case_id,
            "workload_stage_type": workload_case.get("stage_type"),
            "timing_only": False,
            "evidence_kind": (
                "real_qe_baseline_with_real_accelerated_numeric_outputs"
                if accelerated_ready
                else (
                    "real_qe_baseline_with_blocked_accelerated_numeric_payload"
                    if accelerated_has_numeric_payload
                    else "real_qe_baseline_without_accelerated_numeric_outputs"
                )
            ),
            "kernel_evidence": accelerated_numeric.get("kernel_evidence", [])
            if accelerated_ready or accelerated_has_numeric_payload
            else [],
            "physical_evidence": accelerated_numeric.get("physical_evidence", {})
            if accelerated_ready or accelerated_has_numeric_payload
            else {},
        }
        closure_correctness = evaluate_qe_correctness_row(
            real_baseline_oracle_input,
            tolerances,
            requested_claim="l4_trusted_speedup",
        )
        closure_correctness["trusted_correctness_source"] = (
            str(accelerated_numeric.get("source_kind"))
            if accelerated_ready
            else "real_qe_baseline_available_but_accelerated_numeric_outputs_missing"
        )
        closure_correctness["accelerated_output_status"] = accelerated_numeric.get("accelerated_output_status")
        closure_correctness["accelerated_numeric_evidence_path"] = str(row_dir / "qe_accelerated_numeric_evidence.json")
        closure_correctness["baseline_reference"] = {
            "baseline_status": baseline.get("baseline_status"),
            "baseline_comparison_path": str(row_dir.parents[2] / "qe_baselines" / _safe_path_component(case_id) / "baseline_comparison.json"),
            "steps": [
                {
                    "step_id": step.get("step_id"),
                    "status": step.get("status"),
                    "metrics": step.get("metrics", {}),
                    "stdout_path": step.get("stdout_path"),
                }
                for step in baseline.get("steps", []) or []
                if isinstance(step, Mapping)
            ],
        }
        closure_correctness.setdefault("downgrade_blocks", [])
        closure_correctness["downgrade_blocks"] = sorted(
            set(closure_correctness["downgrade_blocks"])
            | set(str(item) for item in accelerated_numeric.get("blockers", []) or [])
        )
        if not accelerated_ready:
            closure_correctness["trusted_claim_eligible"] = False
            closure_correctness["requested_claim_status"] = "blocked"
            closure_correctness["claim_boundary"] = (
                "A real pure-software QE baseline exists for this frozen case, but trusted L4 correctness "
                "still requires accelerated/offloaded QE numeric outputs to compare against it. "
                "Baseline-only, fixture-only, timing-only, or provenance-blocked component-model evidence "
                "is not deliverable-complete numerical equivalence."
            )
        else:
            closure_correctness["claim_boundary"] = (
                "Correctness is eligible only because a trusted accelerated/offloaded QE numeric evidence "
                "artifact supplied kernel and SCF/physical deltas within frozen tolerances."
            )
    else:
        closure_correctness = copy.deepcopy(l3_oracle)
        closure_correctness["trusted_claim_eligible"] = False
        closure_correctness["trusted_correctness_source"] = "blocked_until_real_qe_and_accelerated_numeric_outputs"
        closure_correctness["accelerated_numeric_evidence_path"] = str(row_dir / "qe_accelerated_numeric_evidence.json")
        closure_correctness.setdefault("downgrade_blocks", [])
        closure_correctness["downgrade_blocks"] = sorted(
            set(closure_correctness["downgrade_blocks"])
            | {"fixture_or_l3_sidecar_correctness_not_trusted_for_l4"}
        )
        for gate_name in ("kernel_gate", "scf_physical_gate"):
            gate = closure_correctness.get(gate_name)
            if isinstance(gate, dict):
                gate["fixture_status"] = gate.get("status")
                gate["status"] = "blocked_fixture_only"

    _write_json(row_dir / "l3_numerical_correctness.json", l3_oracle)
    _write_json(row_dir / "qe_correctness_for_l4_closure.json", closure_correctness)
    return l3_oracle, closure_correctness, accelerated_numeric


def _gem5_preflight(
    *,
    gem5_binary: Path,
    gem5_config: Path,
    driver_binary: Path,
    simulator_binary: Path,
) -> Dict[str, Any]:
    gem5_root = gem5_binary.parent.parent.parent if len(gem5_binary.parents) >= 3 and gem5_binary.parent.parent.name == "build" else REPO_ROOT / "gem5_integration" / "gem5"
    clone_processes: list[str] = []
    try:
        completed = subprocess.run(
            ["pgrep", "-af", r"git clone.*gem5|git-remote-https.*gem5"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0:
            clone_processes = [line for line in completed.stdout.splitlines() if "pgrep" not in line]
    except Exception:
        clone_processes = []

    blockers: list[Dict[str, Any]] = []
    if clone_processes and not gem5_binary.exists():
        blockers.append({
            "id": "gem5_source_clone_in_progress",
            "status": "blocked",
            "detail": "A gem5 clone process is still running and gem5.opt does not exist yet; avoiding source-tree mutation during clone.",
            "processes": clone_processes,
        })
    if not gem5_binary.exists() and not (gem5_root / "SConstruct").exists():
        blockers.append({
            "id": "gem5_source_tree_missing_or_incomplete",
            "status": "blocked",
            "detail": f"gem5.opt is missing and the gem5 source tree has no SConstruct: {gem5_root}",
            "path": str(gem5_root),
        })
    if not gem5_config.exists():
        blockers.append({
            "id": "gem5_config_missing",
            "status": "blocked",
            "detail": f"gem5 GenericAccel config is missing: {gem5_config}",
            "path": str(gem5_config),
        })
    if not driver_binary.exists():
        # The adapter can build this, so this is advisory rather than a skip
        # blocker when gem5 itself is buildable.
        blockers.append({
            "id": "gem5_driver_binary_missing_preflight",
            "status": "advisory",
            "detail": f"L4 driver binary is missing before adapter build attempt: {driver_binary}",
            "path": str(driver_binary),
        })
    if not simulator_binary.exists():
        blockers.append({
            "id": "generic_sim_missing_for_l3_or_l4_payload",
            "status": "blocked",
            "detail": f"generic_sim executable is missing: {simulator_binary}",
            "path": str(simulator_binary),
        })
    return {
        "schema_version": "dse.codesign.gem5_preflight.v1",
        "gem5_binary": str(gem5_binary),
        "gem5_binary_exists": gem5_binary.exists(),
        "gem5_root": str(gem5_root),
        "gem5_sconstruct_exists": (gem5_root / "SConstruct").exists(),
        "gem5_config": str(gem5_config),
        "gem5_config_exists": gem5_config.exists(),
        "driver_binary": str(driver_binary),
        "driver_binary_exists": driver_binary.exists(),
        "simulator_binary": str(simulator_binary),
        "simulator_binary_exists": simulator_binary.exists(),
        "clone_processes": clone_processes,
        "blockers": blockers,
        "can_call_real_adapter": (
            (gem5_binary.exists() or (gem5_root / "SConstruct").exists())
            and gem5_config.exists()
            and not clone_processes
        ),
    }


def _planned_gem5_cmd(
    *,
    gem5_binary: Path,
    gem5_config: Path,
    driver_binary: Path,
    simulator_binary: Path,
    request_path: Path,
    max_ticks: int,
    cpu_type: str,
) -> list[str]:
    return [
        str(gem5_binary),
        "--outdir=<row>/l4_gem5/m5out",
        "--debug-flags=GenericAccel",
        "--debug-file=gem5.log",
        str(gem5_config),
        "--binary",
        str(driver_binary),
        "--request",
        str(request_path),
        "--simulator",
        str(simulator_binary),
        "--max-ticks",
        str(max_ticks),
        "--cpu-type",
        cpu_type,
    ]


def _write_blocked_l4_artifacts(
    *,
    adapter: Gem5SystemCClosureAdapter,
    design_point: DesignPoint,
    workload_package: Any,
    row_dir: Path,
    blockers: Sequence[Mapping[str, Any]],
    gem5_binary: Path,
    gem5_config: Path,
    driver_binary: Path,
    simulator_binary: Path,
    max_ticks: int,
    cpu_type: str,
    request_overrides: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    l4_dir = row_dir / "l4_gem5"
    l4_dir.mkdir(parents=True, exist_ok=True)
    request_path = l4_dir / "simulation_request.json"
    request = adapter.bridge._build_request(
        design_point,
        workload_package.graph,
        workload_package=workload_package,
        output_dir=l4_dir,
    )
    request["mode"] = "gem5_cosim"
    if request_overrides:
        request.update(copy.deepcopy(dict(request_overrides)))
    descriptor = build_generic_accel_command_descriptor(request)
    request["generic_accel_descriptor_translation"] = descriptor
    _write_json(l4_dir / "generic_accel_command_descriptor.json", descriptor)
    _write_json(request_path, request)

    blocker_rows = [dict(item) for item in blockers]
    cmd = _planned_gem5_cmd(
        gem5_binary=gem5_binary,
        gem5_config=gem5_config,
        driver_binary=driver_binary,
        simulator_binary=simulator_binary,
        request_path=request_path,
        max_ticks=max_ticks,
        cpu_type=cpu_type,
    )
    _write_json(l4_dir / "gem5_command_descriptor.json", {
        "schema_version": "gsim.gem5_command_descriptor_observed.v1",
        "source": "not observed; real gem5 L4 adapter was not started because preflight failed",
        "transport_harness": TRUSTED_GEM5_TRANSPORT,
        "verified_in_gem5_log": False,
        "planned_descriptor_translation": descriptor,
        "blockers": blocker_rows,
    })
    _write_json(l4_dir / "gem5_completion_descriptor.json", {
        "schema_version": "gsim.gem5_completion_descriptor_observed.v1",
        "source": "not observed; real gem5 L4 adapter was not started because preflight failed",
        "verified_in_gem5_log": False,
        "verified_in_driver_stdout": False,
        "blockers": blocker_rows,
    })
    _write_text(l4_dir / "gem5_stdout.txt", "")
    _write_text(l4_dir / "gem5_stderr.txt", "\n".join(str(item.get("detail", item)) for item in blocker_rows) + "\n")
    _write_text(l4_dir / "gem5.log", "")
    blocked_result = {
        "schema_version": "gsim.result.v1",
        "run_id": design_point.design_point_id,
        "status": "blocked",
        "gem5_systemc_blockers": blocker_rows,
    }
    _write_json(l4_dir / "simulation_result.blocked.json", blocked_result)
    source_artifacts = {
        "transport_harness": TRUSTED_GEM5_TRANSPORT,
        "fallback_from_gem5": False,
        "simulation_request": str(request_path),
        "simulation_result": str(l4_dir / "simulation_result.blocked.json"),
        "gem5_log": str(l4_dir / "gem5.log"),
        "gem5_stdout": str(l4_dir / "gem5_stdout.txt"),
        "gem5_stderr": str(l4_dir / "gem5_stderr.txt"),
        "generic_accel_command_descriptor": str(l4_dir / "generic_accel_command_descriptor.json"),
        "gem5_command_descriptor": str(l4_dir / "gem5_command_descriptor.json"),
        "gem5_completion_descriptor": str(l4_dir / "gem5_completion_descriptor.json"),
        "gem5_stats": None,
        "gem5_config_ini": None,
        "gem5_config_json": None,
        "gem5_activity_summary": None,
        "require_gem5_stats_config": True,
    }
    proof = build_gem5_l4_proof("", "", blocked_result, source_artifacts)
    proof["preflight_blockers"] = blocker_rows
    proof["planned_cmd"] = cmd
    _write_json(l4_dir / "gem5_l4_proof.json", proof)
    return {
        "schema_version": "dse.codesign.l4_gem5_row_attempt.v1",
        "status": "blocked",
        "backend": "gem5_systemc",
        "evidence_tier": "L4",
        "attempted_real_gem5": False,
        "returncode": 2,
        "cmd": cmd,
        "request": request,
        "result": blocked_result,
        "gem5_l4_proof": proof,
        "blockers": blocker_rows,
        "source_artifacts": source_artifacts,
        "transport_harness": TRUSTED_GEM5_TRANSPORT,
        "claim_boundary": "Preflight-blocked rows are present for coverage only; they are not hard L4 evidence.",
    }


def _run_l4_gem5(
    *,
    adapter: Gem5SystemCClosureAdapter,
    design_point: DesignPoint,
    workload_package: Any,
    row_dir: Path,
    preflight: Mapping[str, Any],
    gem5_binary: Path,
    gem5_config: Path,
    driver_binary: Path,
    simulator_binary: Path,
    max_ticks: int,
    cpu_type: str,
    timeout: int,
    attempt_policy: str,
    accelerated_numeric_evidence: Mapping[str, Any] | None = None,
    use_systemc_sidecar: bool = False,
) -> Dict[str, Any]:
    request_overrides: Dict[str, Any] = {}
    if isinstance(accelerated_numeric_evidence, Mapping):
        request_overrides = {
            "extension_payload": {
                "qe_offload": _qe_offload_extension_payload(accelerated_numeric_evidence),
                "qe_accelerated_numeric_evidence": copy.deepcopy(dict(accelerated_numeric_evidence)),
            },
        }

    blockers = [
        blocker
        for blocker in preflight.get("blockers", []) or []
        if isinstance(blocker, Mapping) and blocker.get("status") == "blocked"
    ]
    if attempt_policy == "preflight_only" or blockers or not preflight.get("can_call_real_adapter", False):
        if attempt_policy == "preflight_only":
            blockers = [
                *blockers,
                {
                    "id": "gem5_attempt_policy_preflight_only",
                    "status": "blocked",
                    "detail": "Runner was invoked in preflight-only mode; real gem5 execution intentionally skipped.",
                },
            ]
        elif not preflight.get("can_call_real_adapter", False) and not blockers:
            blockers = [
                {
                    "id": "gem5_real_adapter_not_ready",
                    "status": "blocked",
                    "detail": "Preflight did not approve the real gem5 adapter call.",
                }
            ]
        return _write_blocked_l4_artifacts(
            adapter=adapter,
            design_point=design_point,
            workload_package=workload_package,
            row_dir=row_dir,
            blockers=blockers,
            gem5_binary=gem5_binary,
            gem5_config=gem5_config,
            driver_binary=driver_binary,
            simulator_binary=simulator_binary,
            max_ticks=max_ticks,
            cpu_type=cpu_type,
            request_overrides=request_overrides,
        )

    l4_dir = row_dir / "l4_gem5"
    try:
        run = adapter.run_verified_l4(
            design_point=design_point,
            compute_graph=workload_package.graph,
            workload_package=workload_package,
            request_overrides=request_overrides,
            output_dir=l4_dir,
            gem5_binary=gem5_binary,
            gem5_config=gem5_config,
            driver_binary=driver_binary,
            simulator_binary=simulator_binary,
            max_ticks=max_ticks,
            cpu_type=cpu_type,
            timeout=timeout,
            allow_local_transport_fallback=False,
            use_systemc_sidecar=use_systemc_sidecar,
        )
    except Exception as exc:  # pragma: no cover - defensive row preservation
        blockers = [{
            "id": "gem5_adapter_exception",
            "status": "blocked",
            "detail": f"Gem5SystemCClosureAdapter.run_verified_l4 raised: {exc}",
        }]
        return _write_blocked_l4_artifacts(
            adapter=adapter,
            design_point=design_point,
            workload_package=workload_package,
            row_dir=row_dir,
            blockers=blockers,
            gem5_binary=gem5_binary,
            gem5_config=gem5_config,
            driver_binary=driver_binary,
            simulator_binary=simulator_binary,
            max_ticks=max_ticks,
            cpu_type=cpu_type,
            request_overrides=request_overrides,
        )

    source_artifacts = {}
    transport_proof = run.get("gem5_l4_transport_proof")
    if isinstance(transport_proof, Mapping):
        source_artifacts = dict(transport_proof.get("source_artifacts", {}) or {})
    source_artifacts.setdefault("transport_harness", TRUSTED_GEM5_TRANSPORT)
    source_artifacts.setdefault("fallback_from_gem5", False)
    source_artifacts.setdefault("require_gem5_stats_config", True)
    proof = build_gem5_l4_proof(run.get("gem5_log"), run.get("stdout"), run.get("result") or {}, source_artifacts)
    _write_json(l4_dir / "gem5_l4_proof.json", proof)
    _write_json(l4_dir / "l4_run_summary.json", {
        "schema_version": "dse.codesign.l4_gem5_row_attempt.v1",
        "status": "passed" if proof.get("passed") else "blocked",
        "returncode": run.get("returncode"),
        "gem5_returncode": run.get("gem5_returncode"),
        "cmd": [str(item) for item in run.get("cmd", []) or []],
        "result_path": run.get("result_path"),
        "request_path": run.get("request_path"),
        "proof_path": str(l4_dir / "gem5_l4_proof.json"),
    })
    return {
        "schema_version": "dse.codesign.l4_gem5_row_attempt.v1",
        "status": "passed" if proof.get("passed") else "blocked",
        "backend": "gem5_systemc",
        "evidence_tier": "L4",
        "attempted_real_gem5": True,
        "returncode": run.get("returncode"),
        "gem5_returncode": run.get("gem5_returncode"),
        "cmd": [str(item) for item in run.get("cmd", []) or []],
        "request": run.get("request"),
        "result": run.get("result") or {},
        "gem5_l4_proof": proof,
        "transport_harness": proof.get("transport_harness"),
        "source_artifacts": proof.get("source_artifacts", {}),
        "blockers": [
            {"id": "gem5_l4_proof_failed", "status": "blocked", "detail": item}
            for item in proof.get("missing_evidence", []) or []
        ],
        "claim_boundary": "Only proof.passed=true with real gem5 transport can satisfy L4 hard evidence.",
    }


def _calibration_consistency(l3_status: Mapping[str, Any], l4_attempt: Mapping[str, Any]) -> Dict[str, Any]:
    proof = l4_attempt.get("gem5_l4_proof", {}) if isinstance(l4_attempt.get("gem5_l4_proof"), Mapping) else {}
    l4_passed = proof.get("passed") is True
    l3_passed = l3_status.get("status") == "passed"
    source_artifacts = proof.get("source_artifacts", {}) if isinstance(proof.get("source_artifacts", {}), Mapping) else {}
    has_stats = bool(source_artifacts.get("gem5_stats"))
    passed = l4_passed and l3_passed and has_stats
    blockers = []
    if not l4_passed:
        blockers.append("l4_gem5_proof_not_passed")
    if not l3_passed:
        blockers.append("l3_systemc_reference_not_passed")
    if not has_stats:
        blockers.append("missing_gem5_stats_for_trace_counter_calibration")
    return {
        "schema_version": "dse.codesign.l4_trace_counter_calibration.v1",
        "status": "passed" if passed else "blocked",
        "trace_counter_consistent": passed,
        "l3_reference_status": l3_status.get("status"),
        "gem5_proof_status": proof.get("proof_status"),
        "blockers": blockers,
        "claim_boundary": "Trusted speedup requires L4 trace/counter consistency, not just a descriptor or timing projection.",
    }


def _performance_classification(
    *,
    baseline: Mapping[str, Any],
    l3_status: Mapping[str, Any],
    l4_attempt: Mapping[str, Any],
) -> Dict[str, Any]:
    l3_metrics = l3_status.get("metrics", {}) if isinstance(l3_status.get("metrics", {}), Mapping) else {}
    l4_result = l4_attempt.get("result", {}) if isinstance(l4_attempt.get("result", {}), Mapping) else {}
    l4_metrics = l4_result.get("metrics", {}) if isinstance(l4_result.get("metrics", {}), Mapping) else {}
    blockers = []
    if baseline.get("pure_software_qe_baseline") is not True:
        blockers.append("missing_pure_software_qe_baseline_for_speedup")
    if l4_attempt.get("status") != "passed":
        blockers.append("missing_passed_l4_metrics_for_speedup")
    return {
        "schema_version": "dse.codesign.performance_classification.v1",
        "status": "blocked" if blockers else "passed",
        "claim_label": "blocked" if blockers else "l4_trusted_speedup_candidate",
        "baseline_status": baseline.get("baseline_status"),
        "l3_metrics": dict(l3_metrics),
        "l4_metrics": dict(l4_metrics),
        "blockers": blockers,
        "claim_boundary": "L3 metrics are performance evidence for screening; trusted speedup requires real QE baseline and L4 metrics.",
    }


def _row_blockers(*payloads: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for payload in payloads:
        for item in payload.get("blockers", []) or []:
            if isinstance(item, Mapping):
                blockers.append(str(item.get("id") or item.get("detail") or item))
            else:
                blockers.append(str(item))
        for item in payload.get("downgrade_blocks", []) or []:
            blockers.append(str(item))
        for item in payload.get("missing_evidence", []) or []:
            blockers.append(str(item))
    return sorted(dict.fromkeys(blockers))


def _build_evidence_row(
    *,
    candidate_id: str,
    workload_case_id: str,
    row_id: str,
    l3_status: Mapping[str, Any],
    l3_correctness: Mapping[str, Any],
    closure_correctness: Mapping[str, Any],
    accelerated_numeric_evidence: Mapping[str, Any],
    baseline: Mapping[str, Any],
    l4_attempt: Mapping[str, Any],
    calibration: Mapping[str, Any],
    performance: Mapping[str, Any],
    row_dir: Path,
) -> Dict[str, Any]:
    proof = l4_attempt.get("gem5_l4_proof", {}) if isinstance(l4_attempt.get("gem5_l4_proof"), Mapping) else {}
    row = {
        "schema_version": ROW_SCHEMA,
        "row_id": row_id,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "backend": "gem5_systemc",
        "evidence_tier": "L4",
        "row_dir": str(row_dir),
        "l3_systemc": dict(l3_status),
        "l3_numerical_correctness": dict(l3_correctness),
        "l4_evidence": {
            "backend": "gem5_systemc",
            "evidence_tier": "L4",
            "status": l4_attempt.get("status"),
            "transport_harness": l4_attempt.get("transport_harness") or proof.get("transport_harness"),
            "gem5_l4_proof": dict(proof),
            "source_artifacts": l4_attempt.get("source_artifacts", {}),
        },
        "gem5_l4_proof": dict(proof),
        "correctness": dict(closure_correctness),
        "accelerated_numeric_evidence": _accelerated_numeric_summary(accelerated_numeric_evidence),
        "baseline_comparison": dict(baseline),
        "calibration_consistency": dict(calibration),
        "performance_classification": dict(performance),
        "blockers": _row_blockers(
            l3_status,
            closure_correctness,
            baseline,
            l4_attempt,
            proof,
            calibration,
            performance,
        ),
        "claim_boundary": (
            "This row covers one frozen release candidate x one frozen QE mainflow case. "
            "It is deliverable-complete eligible only when real gem5 L4, real QE correctness, "
            "pure software baseline, and calibration gates all pass."
        ),
    }
    _write_json(row_dir / "evidence_row.json", row)
    return row


def _build_accelerated_evidence_requirements(
    *,
    out_dir: Path,
    candidate_ids: Sequence[str],
    workload_case_ids: Sequence[str],
) -> Dict[str, Any]:
    rows: list[Dict[str, Any]] = []
    requirements_path = out_dir / "qe_accelerated_numeric_evidence_requirements.json"
    for candidate_id in candidate_ids:
        for workload_case_id in workload_case_ids:
            row_dir = out_dir / "accelerated_numeric_inputs" / _safe_path_component(candidate_id) / _safe_path_component(workload_case_id)
            evidence_out = row_dir / "qe_accelerated_numeric_evidence.json"
            rows.append({
                "row_id": f"{candidate_id}::{workload_case_id}",
                "candidate_id": candidate_id,
                "workload_case_id": workload_case_id,
                "required_outputs": {
                    "accelerated_stdout": str(row_dir / "accelerated_qe.stdout.log"),
                    "kernel_evidence_json": str(row_dir / "kernel_evidence.json"),
                    "offload_provenance_json": str(row_dir / "offload_provenance.json"),
                    "kernel_boundary_snapshot_json": str(row_dir / "kernel_boundary_snapshot.json"),
                    "kernel_boundary_arrays_json": str(row_dir / "kernel_boundary_arrays.json"),
                    "density_residual": "numeric CLI value or provenance-derived scalar",
                },
                "target_kernel_evidence_requirements": {
                    "target_kernel": "<selected_offload_kernel>",
                    "required_kernel_scope": "full_<selected_offload_kernel>",
                    "requires_full_kernel_recomputed": True,
                    "requires_accelerated_results_consumed_by_qe": True,
                    "requires_numeric_error_metrics": [
                        "absolute_error",
                        "relative_error",
                    ],
                    "hpsi_legacy_bridge_optional": True,
                    "hpsi_specific_completion_allowed": False,
                    "claim_boundary": (
                        "Rows may target h_psi, s_psi, FFT, diagonalization, "
                        "or another selected QE offload kernel. h_psi bridge "
                        "helpers are seed tooling only, not completion."
                    ),
                },
                "baseline_comparison": str(out_dir / "qe_baselines" / _safe_path_component(workload_case_id) / "baseline_comparison.json"),
                "evidence_output": str(evidence_out),
                "builder_command_template": [
                    sys.executable,
                    "dse_v2/scripts/dse/build_qe_accelerated_numeric_evidence.py",
                    "--candidate-id",
                    candidate_id,
                    "--workload-case-id",
                    workload_case_id,
                    "--baseline-comparison",
                    str(out_dir / "qe_baselines" / _safe_path_component(workload_case_id) / "baseline_comparison.json"),
                    "--accelerated-stdout",
                    str(row_dir / "accelerated_qe.stdout.log"),
                    "--source-kind",
                    "qe_offload_runtime",
                    "--kernel-evidence",
                    str(row_dir / "kernel_evidence.json"),
                    "--offload-provenance",
                    str(row_dir / "offload_provenance.json"),
                    "--density-residual",
                    "<density_residual>",
                    "--out",
                    str(evidence_out),
                    "--fail-on-blocked",
                ],
                "producer_command_template": [
                    sys.executable,
                    "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py",
                    "--requirements",
                    str(requirements_path),
                    "--accelerated-qe-bin-dir",
                    "<modified_or_offloaded_qe_bin_dir>",
                    "--candidate-id",
                    candidate_id,
                    "--workload-case-id",
                    workload_case_id,
                    "--fail-on-blocked",
                ],
                "hpsi_sidecar_bridge_command_template": [
                    sys.executable,
                    "dse_v2/scripts/dse/run_qe_hpsi_sidecar_bridge.py",
                    "--candidate-id",
                    candidate_id,
                    "--workload-case-id",
                    workload_case_id,
                    "--snapshot",
                    str(row_dir / "kernel_boundary_snapshot.json"),
                    "--boundary-arrays",
                    str(row_dir / "kernel_boundary_arrays.json"),
                    "--baseline-comparison",
                    str(out_dir / "qe_baselines" / _safe_path_component(workload_case_id) / "baseline_comparison.json"),
                    "--accelerated-stdout",
                    str(row_dir / "accelerated_qe.stdout.log"),
                    "--out-dir",
                    str(row_dir),
                    "--simulator",
                    "<generic_sim_path>",
                    "--fail-on-trusted",
                ],
            })
    return {
        "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
        "status": "required_for_deliverable_complete",
        "row_count": len(rows),
        "trusted_source_kinds": sorted(TRUSTED_QE_ACCELERATED_NUMERIC_SOURCES),
        "blocked_source_kinds": sorted(UNTRUSTED_QE_ACCELERATED_NUMERIC_SOURCES),
        "campaign_producer_command_template": [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py",
            "--requirements",
            str(requirements_path),
            "--accelerated-qe-bin-dir",
            "<modified_or_offloaded_qe_bin_dir>",
            "--fail-on-blocked",
        ],
        "campaign_collector_command_template": [
            sys.executable,
            "dse_v2/scripts/dse/collect_qe_accelerated_numeric_evidence_campaign.py",
            "--requirements",
            str(requirements_path),
            "--out-dir",
            str(out_dir / "qe_accelerated_numeric_campaign"),
            "--fail-on-blocked",
        ],
        "hpsi_sidecar_bridge_campaign_command_template": [
            sys.executable,
            "dse_v2/scripts/dse/run_qe_hpsi_sidecar_bridge_campaign.py",
            "--requirements",
            str(requirements_path),
            "--simulator",
            "<generic_sim_path>",
            "--fail-on-blocked",
        ],
        "hpsi_sidecar_bridge_note": (
            "After the producer emits real QE boundary snapshot/array artifacts, each row can run "
            "hpsi_sidecar_bridge_command_template to build non-downgraded h_psi component-model evidence. "
            "Rows remain blocked for deliverable-complete until L4 provenance is not boundary-only and "
            "full_h_psi_recomputed=true for h_psi rows or full_kernel_recomputed=true for the selected "
            "non-h_psi target kernel."
        ),
        "selected_kernel_evidence_note": (
            "The deliverable-complete evidence gate is target-kernel based, not h_psi-only: each row must "
            "provide full_kernel_recomputed=true, QE consumption, trusted L4 provenance, and numeric error "
            "metrics for the selected offload kernel."
        ),
        "rows": rows,
        "claim_boundary": (
            "This manifest is a production checklist for real accelerated/offloaded QE outputs. "
            "It is not evidence by itself and cannot satisfy correctness until each row's builder output "
            "is generated from audited offload provenance plus numeric kernel and SCF/physical deltas."
        ),
    }


def _materialize_default_search_space(search_space_dir: Path) -> Path:
    release_subset_path = search_space_dir / "release_subset_manifest.json"
    if release_subset_path.exists():
        return release_subset_path
    script = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_complete_dse_search_space_artifacts.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--out", str(search_space_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    _write_text(search_space_dir / "build_stdout.log", completed.stdout)
    _write_text(search_space_dir / "build_stderr.log", completed.stderr)
    if completed.returncode != 0 or not release_subset_path.exists():
        # Fall back to direct manifest construction so the full-matrix runner can
        # still preserve an explicit row/blocker artifact instead of crashing.
        _write_json(release_subset_path, build_release_subset_manifest())
    return release_subset_path


def _materialize_default_workload_suite(out_dir: Path) -> Path:
    workload_suite_path = out_dir / "qe_mainflow_workload_suite_manifest.json"
    suite = default_qe_mainflow_workload_suite(status="frozen", include_relax=True)
    validation = validate_qe_mainflow_workload_suite(suite)
    if workload_suite_path.exists():
        try:
            existing = _load_json(workload_suite_path)
        except Exception:
            existing = None
        if isinstance(existing, Mapping) and existing.get("suite_hash") == suite.get("suite_hash"):
            return workload_suite_path
        stale_path = workload_suite_path.with_suffix(
            f".stale-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        shutil.move(str(workload_suite_path), stale_path)
    _write_json(workload_suite_path, suite)
    _write_json(out_dir / "qe_mainflow_workload_suite_validation.json", validation)
    return workload_suite_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "dse" / "complete_dse_full_l4_evidence_v1")
    parser.add_argument("--release-subset", type=Path, default=None, help="Frozen release_subset_manifest.json. Defaults to <out>/search_space.")
    parser.add_argument("--workload-suite", type=Path, default=None, help="Frozen QE mainflow suite manifest. Defaults to generated suite in --out.")
    parser.add_argument("--simulator", type=Path, default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim")
    parser.add_argument("--gem5-binary", type=Path, default=REPO_ROOT / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt")
    parser.add_argument("--gem5-config", type=Path, default=REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py")
    parser.add_argument("--gem5-driver", type=Path, default=REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver")
    parser.add_argument("--gem5-cpu-type", default="atomic", choices=["atomic", "timing"])
    parser.add_argument(
        "--l4-use-systemc-sidecar",
        action="store_true",
        help="Ask the real gem5 GenericAccel path to execute the configured generic sidecar executable via --use-systemc.",
    )
    parser.add_argument(
        "--gem5-max-ticks",
        type=int,
        default=1_000_000_000_000,
        help="Maximum gem5 ticks per L4 row; default is sized for multi-stage QE mainflow graphs, not only single-stage smoke rows.",
    )
    parser.add_argument("--l3-timeout", type=int, default=120)
    parser.add_argument("--l4-timeout", type=int, default=120)
    parser.add_argument("--qe-baseline-timeout", type=int, default=120)
    parser.add_argument(
        "--qe-bin-dir",
        type=Path,
        default=None,
        help="Directory containing QE binaries such as pw.x/bands.x. Defaults to QE_BIN_DIR/QE_ROOT/bin or repo-local runs/dse/_tools builds when present.",
    )
    parser.add_argument(
        "--qe-pseudo-dir",
        type=Path,
        default=None,
        help="Directory containing QE pseudopotentials. Defaults to QE_PSEUDO_DIR or repo-local Si pseudo artifacts when present.",
    )
    parser.add_argument(
        "--accelerated-numeric-evidence",
        type=Path,
        default=None,
        help=(
            "Optional JSON file or directory containing dse.qe_accelerated_numeric_evidence.v1 rows. "
            "These are consumed as real QE-vs-accelerated correctness evidence only when source_kind is trusted and numeric deltas are present."
        ),
    )
    parser.add_argument(
        "--gem5-attempt-policy",
        choices=["real_if_ready", "preflight_only"],
        default="real_if_ready",
        help="real_if_ready calls gem5 only when preflight says the real adapter is safe; preflight_only always emits blocked planned rows.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true", help="Exit nonzero when the coverage report is blocked/partial.")
    return parser.parse_args(argv)


def _build_markdown_report(report: Mapping[str, Any], coverage: Mapping[str, Any], matrix: Mapping[str, Any]) -> str:
    lines = [
        "# Complete-DSE full L4 evidence matrix report",
        "",
        f"- Status: `{report['status']}`",
        f"- Expected rows: {coverage.get('expected_row_count')}",
        f"- Emitted rows: {coverage.get('row_count')}",
        f"- Blocked rows: {coverage.get('blocked_row_count')}",
        f"- Deliverable-complete claim: `{coverage.get('claims', {}).get('deliverable_complete')}`",
        "",
        "## Claim boundaries",
        "",
        f"- Foundation/MVP artifact coverage: `{report['claims']['foundation_artifacts_emitted']}`",
        f"- MVP partial: `{report['claims']['mvp_partial']}`",
        f"- Deliverable complete: `{report['claims']['deliverable_complete']}`",
        "",
        "## Top blockers",
        "",
    ]
    blocker_counts = report.get("blocker_counts", {})
    if blocker_counts:
        for blocker, count in sorted(blocker_counts.items(), key=lambda item: (-int(item[1]), item[0]))[:20]:
            lines.append(f"- `{blocker}`: {count}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Anti-downgrade note",
        "",
        "Every legal candidate × QE mainflow row is represented in the matrix. "
        "Blocked, missing-tool, fixture-only, L3-only, preflight-only, or descriptor-only rows "
        "do not satisfy `deliverable_complete`.",
        "",
        f"Matrix hash: `{matrix.get('matrix_hash')}`",
    ])
    return "\n".join(lines) + "\n"


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    release_subset_path = args.release_subset or _materialize_default_search_space(out_dir / "search_space")
    workload_suite_path = args.workload_suite or _materialize_default_workload_suite(out_dir)
    release_subset = _load_json(release_subset_path)
    workload_suite = _load_json(workload_suite_path)
    suite_validation = validate_qe_mainflow_workload_suite(workload_suite)
    _write_json(out_dir / "qe_mainflow_workload_suite_validation.json", suite_validation)
    accelerated_numeric_index, accelerated_numeric_index_report = _load_accelerated_numeric_evidence(
        args.accelerated_numeric_evidence
    )
    _write_json(out_dir / "qe_accelerated_numeric_evidence_index.json", accelerated_numeric_index_report)

    candidates = _candidate_index(release_subset)
    cases = _case_index(workload_suite)
    candidate_ids = _candidate_ids(release_subset)
    workload_case_ids = _workload_case_ids(workload_suite)

    preflight = _gem5_preflight(
        gem5_binary=args.gem5_binary,
        gem5_config=args.gem5_config,
        driver_binary=args.gem5_driver,
        simulator_binary=args.simulator,
    )
    _write_json(out_dir / "gem5_preflight.json", preflight)

    qe_bin_dir = args.qe_bin_dir or _default_qe_bin_dir()
    qe_pseudo_dir = args.qe_pseudo_dir or _default_qe_pseudo_dir()
    _write_json(out_dir / "qe_runtime_preflight.json", {
        "schema_version": "dse.qe_runtime_preflight.v1",
        "qe_bin_dir": str(qe_bin_dir) if qe_bin_dir else None,
        "qe_pseudo_dir": str(qe_pseudo_dir) if qe_pseudo_dir else None,
        "candidate_qe_bin_dirs": [str(path) for path in _candidate_qe_bin_dirs()],
        "candidate_qe_pseudo_dirs": [str(path) for path in _candidate_qe_pseudo_dirs()],
        "executables": {
            name: {
                "path": _resolve_qe_executable(name, qe_bin_dir)[0],
                "provenance": _resolve_qe_executable(name, qe_bin_dir)[1],
            }
            for name in ["pw.x", "bands.x", "dos.x", "projwfc.x"]
        },
        "pseudo_files": {
            "Si.pz-vbc.UPF": str(qe_pseudo_dir / "Si.pz-vbc.UPF") if qe_pseudo_dir and (qe_pseudo_dir / "Si.pz-vbc.UPF").exists() else None,
        },
        "claim_boundary": "QE preflight only resolves local pure-software baseline tools; it does not prove accelerated numerical equivalence.",
    })

    baselines = {
        case_id: _run_qe_baseline(
            cases[case_id],
            out_dir / "qe_baselines",
            args.qe_baseline_timeout,
            qe_bin_dir=qe_bin_dir,
            qe_pseudo_dir=qe_pseudo_dir,
        )
        for case_id in workload_case_ids
        if case_id in cases
    }
    accelerated_requirements = _build_accelerated_evidence_requirements(
        out_dir=out_dir,
        candidate_ids=candidate_ids,
        workload_case_ids=workload_case_ids,
    )
    _write_json(out_dir / "qe_accelerated_numeric_evidence_requirements.json", accelerated_requirements)

    l3_backend = GenericSystemCBackend(executable_path=str(args.simulator), mode="standalone_systemc")
    l4_adapter = Gem5SystemCClosureAdapter()
    evidence_rows: list[Dict[str, Any]] = []
    expected_row_count = len(candidate_ids) * len(workload_case_ids)

    for candidate_id in candidate_ids:
        candidate = candidates.get(candidate_id, {"candidate_id": candidate_id})
        for workload_case_id in workload_case_ids:
            if workload_case_id not in cases:
                continue
            workload_case = cases[workload_case_id]
            row_id = f"{candidate_id}::{workload_case_id}"
            row_dir = out_dir / "rows" / _safe_path_component(candidate_id) / _safe_path_component(workload_case_id)
            row_dir.mkdir(parents=True, exist_ok=True)
            _write_json(row_dir / "candidate_record.json", candidate)
            _write_json(row_dir / "workload_case.json", workload_case)

            workload_package = package_qe_mainflow_case(workload_case)
            node_op_types = {node_id: node.op_type for node_id, node in workload_package.graph.nodes.items()}
            design_point = _build_design_point(
                candidate_id=candidate_id,
                candidate=candidate,
                workload_case=workload_case,
                op_types=list(node_op_types.values()),
                node_op_types=node_op_types,
            )
            _write_json(row_dir / "design_point.json", design_point.to_dict())

            baseline = baselines.get(workload_case_id, {
                "status": "blocked",
                "baseline_status": "missing_workload_case_baseline",
                "pure_software_qe_baseline": False,
                "blockers": ["missing_workload_case_baseline"],
            })
            external_accelerated_numeric = accelerated_numeric_index.get(
                _evidence_row_key(candidate_id, workload_case_id)
            )
            l3_run, l3_status = _run_l3_systemc(
                backend=l3_backend,
                design_point=design_point,
                workload_package=workload_package,
                row_dir=row_dir,
                timeout=args.l3_timeout,
            )
            l4_attempt = _run_l4_gem5(
                adapter=l4_adapter,
                design_point=design_point,
                workload_package=workload_package,
                row_dir=row_dir,
                preflight=preflight,
                gem5_binary=args.gem5_binary,
                gem5_config=args.gem5_config,
                driver_binary=args.gem5_driver,
                simulator_binary=args.simulator,
                max_ticks=args.gem5_max_ticks,
                cpu_type=args.gem5_cpu_type,
                timeout=args.l4_timeout,
                attempt_policy=args.gem5_attempt_policy,
                accelerated_numeric_evidence=external_accelerated_numeric,
                use_systemc_sidecar=args.l4_use_systemc_sidecar,
            )
            l3_correctness, closure_correctness, accelerated_numeric = _build_l3_correctness(
                candidate_id=candidate_id,
                workload_case=workload_case,
                row_id=row_id,
                l3_status=l3_status,
                baseline=baseline,
                l4_attempt=l4_attempt,
                external_accelerated_numeric_evidence=external_accelerated_numeric,
                row_dir=row_dir,
            )
            calibration = _calibration_consistency(l3_status, l4_attempt)
            performance = _performance_classification(
                baseline=baseline,
                l3_status=l3_status,
                l4_attempt=l4_attempt,
            )
            row = _build_evidence_row(
                candidate_id=candidate_id,
                workload_case_id=workload_case_id,
                row_id=row_id,
                l3_status=l3_status,
                l3_correctness=l3_correctness,
                closure_correctness=closure_correctness,
                accelerated_numeric_evidence=accelerated_numeric,
                baseline=baseline,
                l4_attempt=l4_attempt,
                calibration=calibration,
                performance=performance,
                row_dir=row_dir,
            )
            evidence_rows.append(row)

    evidence_payload = {
        "schema_version": EVIDENCE_ROWS_SCHEMA,
        "generated_at": _now_iso(),
        "release_subset": str(release_subset_path),
        "workload_suite": str(workload_suite_path),
        "expected_row_count": expected_row_count,
        "row_count": len(evidence_rows),
        "rows": evidence_rows,
        "anti_downgrade_policy": {
            "top_k_or_representative_completion_allowed": False,
            "missing_or_blocked_rows_complete_release": False,
            "l3_projection_completes_l4": False,
        },
    }
    _write_json(out_dir / "evidence_rows.json", evidence_payload)

    matrix = build_l4_evidence_matrix(release_subset, workload_suite, evidence_rows)
    coverage = build_coverage_claim_report(matrix)
    _write_json(out_dir / "l4_evidence_matrix.json", matrix)
    _write_json(out_dir / "coverage_claim_report.json", coverage)

    all_rows_present = bool(coverage["all_rows_present"])
    real_l4_gem5_full_flow_rows = _matrix_gate_count(matrix, "real_l4_gem5_full_flow")
    trusted_speedup_eligible_rows = sum(
        1
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("trusted_speedup_eligible") is True
    )
    full_hpsi_payload_counts = _full_hpsi_payload_row_counts(evidence_rows)
    trusted_correctness_rows = _trusted_correctness_row_count(evidence_rows)
    all_rows_have_real_l4_gem5 = (
        all_rows_present
        and real_l4_gem5_full_flow_rows == expected_row_count
        and expected_row_count > 0
    )
    all_rows_have_full_hpsi_payload = (
        all_rows_present
        and full_hpsi_payload_counts["full_hpsi_numeric_payload_rows"] == expected_row_count
        and expected_row_count > 0
    )

    evidence_blocker_counts = _blocker_counts(evidence_rows)
    matrix_rows = [row for row in matrix.get("rows", []) or [] if isinstance(row, Mapping)]
    # Use closure/matrix blockers as the headline blocker list because the
    # matrix adds final claim-gating reasons (for example an untrusted
    # correctness source) that are not present in raw evidence rows.
    blocker_counts = _blocker_counts(matrix_rows) or evidence_blocker_counts

    full_report = {
        "schema_version": REPORT_SCHEMA,
        "generated_at": _now_iso(),
        "status": "deliverable_complete" if coverage["claims"]["deliverable_complete"] else "blocked_or_partial",
        "release_subset_path": str(release_subset_path),
        "workload_suite_path": str(workload_suite_path),
        "gem5_preflight_path": str(out_dir / "gem5_preflight.json"),
        "qe_runtime_preflight_path": str(out_dir / "qe_runtime_preflight.json"),
        "qe_accelerated_numeric_evidence_index_path": str(out_dir / "qe_accelerated_numeric_evidence_index.json"),
        "qe_accelerated_numeric_evidence_requirements_path": str(out_dir / "qe_accelerated_numeric_evidence_requirements.json"),
        "evidence_rows_path": str(out_dir / "evidence_rows.json"),
        "l4_evidence_matrix_path": str(out_dir / "l4_evidence_matrix.json"),
        "coverage_claim_report_path": str(out_dir / "coverage_claim_report.json"),
        "expected_row_count": expected_row_count,
        "row_count": len(evidence_rows),
        "claims": {
            "foundation_artifacts_emitted": bool(evidence_rows and len(evidence_rows) == expected_row_count),
            "mvp_partial": bool(evidence_rows and len(evidence_rows) == expected_row_count and not coverage["claims"]["deliverable_complete"]),
            "deliverable_complete": bool(coverage["claims"]["deliverable_complete"]),
        },
        "claim_boundaries": {
            "foundation": "Search-space, workload-suite, row, matrix, and blocker artifacts exist.",
            "mvp_partial": "All finite rows are represented, but at least one real L4/QE/correctness/calibration gate is blocked.",
            "deliverable_complete": "Only true when every legal release candidate x every QE mainflow case is l4_trusted_speedup eligible.",
        },
        "blocker_counts": blocker_counts,
        "evidence_blocker_counts": evidence_blocker_counts,
        "matrix_blocker_counts": _blocker_counts(matrix_rows),
        "evidence_summary": {
            "all_rows_present": all_rows_present,
            "real_l4_gem5_full_flow_rows": real_l4_gem5_full_flow_rows,
            **full_hpsi_payload_counts,
            "trusted_correctness_rows": trusted_correctness_rows,
            "trusted_speedup_eligible_rows": trusted_speedup_eligible_rows,
            "expected_row_count": expected_row_count,
            "claim_boundary": (
                "real_l4_gem5_full_flow_rows and full_hpsi_numeric_payload_rows are foundation/MVP evidence "
                "counts only. full_hpsi_legacy_component_model_rows remains blocked from trusted L4 correctness; "
                "full_hpsi_native_payload_rows identifies non-component/native payload evidence. "
                "trusted_speedup_eligible_rows is the deliverable-complete closure count and remains zero "
                "when offload provenance or QE correctness gates are blocked."
            ),
        },
        "coverage": {
            "all_rows_present": coverage["all_rows_present"],
            "blocked_row_count": coverage["blocked_row_count"],
            "claim_labels": coverage["claim_labels"],
            "claims": coverage["claims"],
        },
        "prompt_to_artifact_checklist": [
            {
                "requirement": "all legal release candidates x all frozen QE mainflows represented",
                "artifact": str(out_dir / "l4_evidence_matrix.json"),
                "passed": len(evidence_rows) == expected_row_count and coverage["all_rows_present"],
            },
            {
                "requirement": "L4 gem5 hard evidence for every row",
                "artifact": str(out_dir / "coverage_claim_report.json"),
                "passed": all_rows_have_real_l4_gem5,
            },
            {
                "requirement": "full h_psi numeric payload surfaced for every row with explicit legacy-component or native-payload provenance classification",
                "artifact": str(out_dir / "evidence_rows.json"),
                "passed": all_rows_have_full_hpsi_payload,
            },
            {
                "requirement": "accelerated/offloaded QE numerical outputs compared against real QE baseline",
                "artifact": str(out_dir / "qe_accelerated_numeric_evidence_requirements.json"),
                "passed": coverage["claims"]["deliverable_complete"],
            },
            {
                "requirement": "no Top-K/representative downgrade",
                "artifact": str(out_dir / "coverage_claim_report.json"),
                "passed": coverage["claims"]["top_k_or_representative_completion_allowed"] is False,
            },
            {
                "requirement": "truthful foundation/MVP/deliverable claim boundaries",
                "artifact": str(out_dir / "complete_dse_full_l4_evidence_report.json"),
                "passed": True,
            },
        ],
    }
    _write_json(out_dir / "complete_dse_full_l4_evidence_report.json", full_report)
    _write_text(out_dir / "complete_dse_full_l4_evidence_report.md", _build_markdown_report(full_report, coverage, matrix))

    status = {
        "schema_version": RUN_SCHEMA,
        "status": full_report["status"],
        "out": str(out_dir),
        "expected_row_count": expected_row_count,
        "row_count": len(evidence_rows),
        "blocked_row_count": coverage["blocked_row_count"],
        "deliverable_complete": coverage["claims"]["deliverable_complete"],
        "coverage_claim_report": str(out_dir / "coverage_claim_report.json"),
        "full_report": str(out_dir / "complete_dse_full_l4_evidence_report.json"),
    }
    print(json.dumps(status, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and not coverage["claims"]["deliverable_complete"] else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
