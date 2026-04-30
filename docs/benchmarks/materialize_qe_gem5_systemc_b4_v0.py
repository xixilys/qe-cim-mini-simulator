#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "qe_gem5_systemc_b4_materialization_manifest_v0"
TIMING_SIDECAR_SCHEMA_VERSION = "qe_gem5_systemc_b4_timing_sidecar_v0"
CANDIDATE_TIMING_PROFILE_SCHEMA_VERSION = "qe_gem5_systemc_b4_candidate_timing_profile_v0"
B4_STAGE_B0_FILE_INPUT_REF_KEYS = {
    "application_graph",
    "architecture_template",
    "mapping",
    "architecture_config",
    "systemc_config",
}
CLUSTER_WEIGHTS = {
    "operator_sweep": 0.68,
    "reduced_build": 0.04,
    "hardware_diag": 0.23,
    "refresh_residual": 0.05,
}
DEFAULT_NON_CLAIMS = [
    "no_qe_equivalent_scf_claim",
    "no_cycle_accuracy_claim",
    "no_rtl_hls_board_or_asic_implementation_claim",
    "no_physical_fpga_performance_measurement",
    "not_final_public_family_winner",
]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_root(stage_b0_request_path: Path) -> Path:
    request_dir = stage_b0_request_path.resolve().parent
    if request_dir.name in {
        "backend_execution_requests",
        "gem5_systemc_handoff",
        "backend_requests",
    }:
        return request_dir.parent
    return request_dir


def _resolve_ref(value: Any, root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.expanduser().resolve(strict=False)


def _resolve_required_ref(refs: Mapping[str, Any], root: Path, key: str) -> Path:
    resolved = _resolve_ref(refs.get(key), root)
    if resolved is None:
        raise ValueError(f"Stage-B0 request missing input_refs.{key}")
    return resolved


def _request_context(request: Mapping[str, Any], stage_b0_request_path: Path) -> dict[str, Any]:
    candidate_identity = request.get("candidate_identity")
    candidate_identity = candidate_identity if isinstance(candidate_identity, Mapping) else {}
    design_axes = candidate_identity.get("design_axes")
    design_axes = design_axes if isinstance(design_axes, Mapping) else {}
    workload_identity = request.get("workload_identity")
    workload_identity = workload_identity if isinstance(workload_identity, Mapping) else {}
    domain_extension = request.get("domain_extension")
    domain_extension = domain_extension if isinstance(domain_extension, Mapping) else {}
    qe_extension = domain_extension.get("qe")
    qe_extension = qe_extension if isinstance(qe_extension, Mapping) else {}
    family = design_axes.get("family") or candidate_identity.get("candidate_family")
    family = family or candidate_identity.get("architecture_template_id")
    workload_id = workload_identity.get("workload_id") or qe_extension.get("workload_id") or qe_extension.get("case_id")
    case_id = qe_extension.get("case_id") or workload_identity.get("case_id") or workload_id
    return {
        "candidate_id": str(
            request.get("candidate_id")
            or candidate_identity.get("candidate_id")
            or stage_b0_request_path.stem
        ),
        "workload_id": str(workload_id) if workload_id is not None else None,
        "case_id": str(case_id) if case_id is not None else None,
        "family": str(family) if family is not None else None,
        "design_axes": dict(design_axes),
    }


def _as_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _cluster_ref_cycles(cluster: Mapping[str, Any], cluster_type: str) -> int:
    weight = CLUSTER_WEIGHTS.get(cluster_type, 0.10)
    buffer_kb = max(1, _as_int(cluster.get("on_chip_buffer_kb"), 128))
    pipeline_depth = max(1, _as_int(cluster.get("pipeline_depth"), 4))
    concurrent_ops = max(1, _as_int(cluster.get("max_concurrent_ops"), 8))
    base_cycles = 12_000_000.0 * weight
    buffer_scale = max(0.25, 256.0 / float(buffer_kb))
    pipeline_scale = max(0.25, 4.0 / float(pipeline_depth))
    concurrency_scale = max(0.25, 8.0 / float(concurrent_ops))
    return max(1_000, int(round(base_cycles * buffer_scale * pipeline_scale * concurrency_scale)))


def _build_timing_sidecar(
    *,
    request: Mapping[str, Any],
    stage_b0_request_path: Path,
    architecture_config_path: Path,
    systemc_config_path: Path,
) -> dict[str, Any]:
    context = _request_context(request, stage_b0_request_path)
    architecture_config = _load_json(architecture_config_path)
    clusters = architecture_config.get("clusters", [])
    if not isinstance(clusters, list):
        clusters = []

    cluster_breakdown: dict[str, Any] = {}
    total_cycles = 0
    total_dma_read_bytes = 0
    total_dma_write_bytes = 0
    total_compute_ns = 0
    total_dma_read_ns = 0
    total_dma_write_ns = 0
    backpressure_count = 0
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, Mapping):
            continue
        cluster_id = str(cluster.get("cluster_id") or f"cluster_{index}")
        cluster_type = str(cluster.get("type") or "unknown")
        cycles = _cluster_ref_cycles(cluster, cluster_type)
        buffer_kb = max(1, _as_int(cluster.get("on_chip_buffer_kb"), 128))
        dma_read = buffer_kb * 1024 * 2
        dma_write = buffer_kb * 1024
        dma_read_ns = max(100, int(round(dma_read / 64.0)))
        dma_write_ns = max(100, int(round(dma_write / 64.0)))
        compute_ns = max(1_000, cycles)
        if cluster.get("enable_backpressure") is True:
            backpressure_count += 1
        cluster_breakdown[cluster_id] = {
            "cluster_type": cluster_type,
            "ref_cycles": cycles,
            "device_busy_ns": compute_ns,
            "compute_ns": compute_ns,
            "dma_read_bytes": dma_read,
            "dma_write_bytes": dma_write,
            "dma_read_ns": dma_read_ns,
            "dma_write_ns": dma_write_ns,
            "pipeline_depth": _as_int(cluster.get("pipeline_depth"), 4),
            "max_concurrent_ops": _as_int(cluster.get("max_concurrent_ops"), 8),
            "source": "architecture_config_projection",
        }
        total_cycles += cycles
        total_dma_read_bytes += dma_read
        total_dma_write_bytes += dma_write
        total_compute_ns += compute_ns
        total_dma_read_ns += dma_read_ns
        total_dma_write_ns += dma_write_ns

    if total_cycles <= 0:
        total_cycles = 1_000
    logical_dma_bytes = total_dma_read_bytes + total_dma_write_bytes
    mmio_writes = max(4, 2 + len(cluster_breakdown) * 2)
    mmio_reads = max(4, 2 + len(cluster_breakdown))
    polling_reads = max(1, len(cluster_breakdown))
    command_issue_tick = 0
    device_accept_tick = 100
    dma_start_tick = device_accept_tick + 20
    dma_end_tick = dma_start_tick + max(1, total_dma_read_ns + total_dma_write_ns)
    systemc_start_tick = device_accept_tick + 10
    systemc_end_tick = systemc_start_tick + total_cycles
    completion_tick = systemc_end_tick + 100
    return {
        "schema_version": TIMING_SIDECAR_SCHEMA_VERSION,
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "candidate_id": context["candidate_id"],
        "workload_id": context["workload_id"],
        "case_id": context["case_id"],
        "family": context["family"],
        "design_axes": context["design_axes"],
        "architecture_config_ref": str(architecture_config_path),
        "systemc_config_ref": str(systemc_config_path),
        "timing_source": "timing_sidecar_projection",
        "cycle_source": "timing_sidecar_projection",
        "cluster_breakdown": cluster_breakdown,
        "control_path": {
            "host_launch_count": 1,
            "completion_count": 1,
            "fallback_count": 0,
            "deadlock": False,
            "completion_source": "gem5_systemc_timing_sidecar",
            "timing_source": "timing_sidecar_projection",
            "mmio_activity_source": "architecture_config_projection_sidecar",
            "event_timed_device_activity_observed": False,
            "mmio_read_count": mmio_reads,
            "mmio_write_count": mmio_writes,
            "polling_read_count": polling_reads,
            "interrupt_count": 0,
            "command_issue_tick": command_issue_tick,
            "device_accept_tick": device_accept_tick,
            "systemc_start_tick": systemc_start_tick,
            "systemc_end_tick": systemc_end_tick,
            "completion_tick": completion_tick,
            "dma_start_tick": dma_start_tick,
            "dma_end_tick": dma_end_tick,
        },
        "metrics": {
            "time_to_completion_s": None,
            "cycle_proxy": completion_tick,
            "cycle_source": "timing_sidecar_projection",
            "cycle_proxy_source": "timing_sidecar_projection",
            "event_timed_device_activity_observed": False,
            "candidate_device_event_delta_ticks": None,
            "host_wait_s": None,
            "device_busy_s": total_cycles / 1e9,
            "dma_read_bytes": total_dma_read_bytes,
            "dma_write_bytes": total_dma_write_bytes,
            "bytes_moved_to_convergence": logical_dma_bytes,
            "resident_reuse_ratio": 0.0,
            "spill_ratio": 0.0,
            "fallback_ratio": 0.0,
            "host_control_mmio_read_count": mmio_reads,
            "host_control_mmio_write_count": mmio_writes,
            "host_control_polling_read_count": polling_reads,
            "host_control_interrupt_count": 0,
            "host_control_queue_wait_ns": 0,
            "systemc_datapath_device_busy_ns": total_cycles,
            "systemc_datapath_compute_ns": total_compute_ns,
            "systemc_datapath_dma_read_ns": total_dma_read_ns,
            "systemc_datapath_dma_write_ns": total_dma_write_ns,
            "systemc_datapath_queue_depth": len(cluster_breakdown),
            "systemc_datapath_backpressure_count": backpressure_count,
            "systemc_datapath_dma_read_bytes": total_dma_read_bytes,
            "systemc_datapath_dma_write_bytes": total_dma_write_bytes,
            "logical_dma_payload_bytes": logical_dma_bytes,
            "observed_gem5_dma_stat_bytes": logical_dma_bytes,
            "successful_dma_transfer_bytes": logical_dma_bytes,
            "dma_warning_count": 0,
            "systemc_cluster_timing": cluster_breakdown,
        },
        "claim_ceiling": "gem5_systemc_timed_proxy_only",
        "non_claims": list(DEFAULT_NON_CLAIMS),
    }


def _build_candidate_timing_profile(
    *,
    timing_sidecar: Mapping[str, Any],
    timing_sidecar_path: Path,
) -> dict[str, Any]:
    """Build the runtime profile consumed by strict gem5 event/tick proxy runs.

    The timing sidecar remains a projection artifact.  This profile makes that
    projection explicit and packages only scalar, runtime-swappable values for a
    stable gem5 SimObject contract.  It is not a hardware cycle-accuracy source.
    """

    control_path = timing_sidecar.get("control_path")
    control_path = control_path if isinstance(control_path, Mapping) else {}
    metrics = timing_sidecar.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    command_issue_tick = _as_int(control_path.get("command_issue_tick"), 0)
    device_accept_tick = _as_int(control_path.get("device_accept_tick"), command_issue_tick + 100)
    systemc_start_tick = _as_int(control_path.get("systemc_start_tick"), device_accept_tick)
    systemc_end_tick = max(_as_int(control_path.get("systemc_end_tick"), systemc_start_tick + 1), systemc_start_tick)
    completion_tick = max(_as_int(control_path.get("completion_tick"), systemc_end_tick + 1), systemc_end_tick)
    candidate_event_delta_ticks = max(1, completion_tick - command_issue_tick)
    device_busy_ticks = max(1, systemc_end_tick - systemc_start_tick)
    dma_read_bytes = _as_int(metrics.get("systemc_datapath_dma_read_bytes"), _as_int(metrics.get("dma_read_bytes"), 0))
    dma_write_bytes = _as_int(metrics.get("systemc_datapath_dma_write_bytes"), _as_int(metrics.get("dma_write_bytes"), 0))
    return {
        "schema_version": CANDIDATE_TIMING_PROFILE_SCHEMA_VERSION,
        "generated_at_utc": timing_sidecar.get("generated_at_utc"),
        "candidate_id": timing_sidecar.get("candidate_id"),
        "workload_id": timing_sidecar.get("workload_id"),
        "case_id": timing_sidecar.get("case_id"),
        "family": timing_sidecar.get("family"),
        "design_axes": dict(timing_sidecar.get("design_axes") or {}),
        "profile_source": "dse_architecture_config_projection",
        "runtime_timing_role": "strict_b4_runtime_profile_input",
        "timing_sidecar_ref": str(timing_sidecar_path),
        "register_model": {
            "model_id": "qebs_fixed_pio_electrons_v0",
            "command_register": "REG_CONTROL",
            "status_register": "REG_STATUS",
            "cycle_register": "REG_CYCLES",
            "completion_bit": 1,
        },
        "event_schedule": {
            "command_issue_tick": command_issue_tick,
            "device_accept_tick": device_accept_tick,
            "systemc_start_tick": systemc_start_tick,
            "systemc_end_tick": systemc_end_tick,
            "completion_tick": completion_tick,
            "candidate_event_delta_ticks": candidate_event_delta_ticks,
            "device_busy_ticks": device_busy_ticks,
            "source": "timing_sidecar_projection_packaged_for_gem5_event_scheduling",
        },
        "dma_profile": {
            "dma_read_bytes": dma_read_bytes,
            "dma_write_bytes": dma_write_bytes,
            "logical_dma_payload_bytes": _as_int(metrics.get("logical_dma_payload_bytes"), dma_read_bytes + dma_write_bytes),
        },
        "cluster_breakdown": dict(timing_sidecar.get("cluster_breakdown") or {}),
        "claim_ceiling": "gem5_event_scheduled_tick_observed_proxy_input_only",
        "non_claims": list(DEFAULT_NON_CLAIMS) + [
            "runtime_profile_is_projection_input_not_observed_execution",
            "gem5_event_observation_required_before_cycle_source_promotion",
        ],
    }


def _write_generated_systemc(
    generated_dir: Path,
    *,
    candidate_id: str,
    timing_sidecar_ref: Path,
    candidate_timing_profile_ref: Path,
    candidate_timing_profile: Mapping[str, Any],
) -> dict[str, str]:
    generated_dir.mkdir(parents=True, exist_ok=True)
    safe_symbol = "".join(ch if ch.isalnum() else "_" for ch in candidate_id)
    safe_name = safe_symbol or "candidate"
    header = generated_dir / f"{safe_name}_candidate_bridge.hpp"
    source = generated_dir / f"{safe_name}_candidate_bridge.cpp"
    event_schedule = candidate_timing_profile.get("event_schedule")
    event_schedule = event_schedule if isinstance(event_schedule, Mapping) else {}
    candidate_event_delta_ticks = _as_int(event_schedule.get("candidate_event_delta_ticks"), 1)
    device_busy_ticks = _as_int(event_schedule.get("device_busy_ticks"), candidate_event_delta_ticks)
    header.write_text(
        "#pragma once\n"
        "\n"
        "// Generated candidate-specific B4 timing-profile shim.\n"
        "// This file is optional compile/provenance evidence. Runtime gem5 B4\n"
        "// uses the JSON candidate timing profile so per-candidate DSE runs do\n"
        "// not require rebuilding gem5 or relinking the bridge.\n"
        "\n"
        "namespace qebs_generated {\n"
        "struct CandidateTimingProfile {\n"
        "    const char* candidate_id;\n"
        "    const char* timing_sidecar_ref;\n"
        "    const char* candidate_timing_profile_ref;\n"
        "    unsigned long long candidate_event_delta_ticks;\n"
        "    unsigned long long device_busy_ticks;\n"
        "};\n"
        "\n"
        f"const char* {safe_symbol}_candidate_id();\n"
        f"const char* {safe_symbol}_timing_sidecar_ref();\n"
        f"const char* {safe_symbol}_candidate_timing_profile_ref();\n"
        f"unsigned long long {safe_symbol}_candidate_event_delta_ticks();\n"
        f"CandidateTimingProfile {safe_symbol}_candidate_timing_profile();\n"
        "}  // namespace qebs_generated\n",
        encoding="utf-8",
    )
    source.write_text(
        f'#include "{header.name}"\n'
        "\n"
        "namespace qebs_generated {\n"
        f"const char* {safe_symbol}_candidate_id() {{ return {json.dumps(candidate_id)}; }}\n"
        f"const char* {safe_symbol}_timing_sidecar_ref() {{ return {json.dumps(str(timing_sidecar_ref))}; }}\n"
        f"const char* {safe_symbol}_candidate_timing_profile_ref() {{ return {json.dumps(str(candidate_timing_profile_ref))}; }}\n"
        f"unsigned long long {safe_symbol}_candidate_event_delta_ticks() {{ return {candidate_event_delta_ticks}ULL; }}\n"
        f"CandidateTimingProfile {safe_symbol}_candidate_timing_profile() {{\n"
        "    return CandidateTimingProfile{\n"
        f"        {safe_symbol}_candidate_id(),\n"
        f"        {safe_symbol}_timing_sidecar_ref(),\n"
        f"        {safe_symbol}_candidate_timing_profile_ref(),\n"
        f"        {candidate_event_delta_ticks}ULL,\n"
        f"        {device_busy_ticks}ULL,\n"
        "    };\n"
        "}\n"
        "}  // namespace qebs_generated\n",
        encoding="utf-8",
    )
    return {
        "header": str(header),
        "source": str(source),
    }


def materialize_b4_from_stage_b0(
    stage_b0_request_path: Path | str,
    output_dir: Path | str,
    *,
    gem5_executable: Path | str,
    gem5_config: Path | str,
    systemc_bridge: Path | str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    stage_b0_request = Path(stage_b0_request_path).expanduser().resolve(strict=False)
    root = _artifact_root(stage_b0_request)
    output_root = Path(output_dir).expanduser().resolve(strict=False)
    repo_root_path = Path(repo_root).expanduser().resolve(strict=False) if repo_root is not None else Path.cwd()
    request = _load_json(stage_b0_request)
    refs = request.get("input_refs")
    if not isinstance(refs, Mapping):
        raise ValueError(f"input_refs is not a JSON object in {stage_b0_request}")

    architecture_config_path = _resolve_required_ref(refs, root, "architecture_config")
    systemc_config_path = _resolve_required_ref(refs, root, "systemc_config")
    context = _request_context(request, stage_b0_request)
    candidate_id = str(context["candidate_id"])
    generated_dir = output_root / "generated_systemc"
    timing_sidecar_path = output_root / "timing_sidecar.json"
    candidate_timing_profile_path = output_root / "candidate_timing_profile_v0.json"
    manifest_path = output_root / "manifest_v0.json"
    b4_request_path = output_root / "backend_execution_request.json"

    timing_sidecar = _build_timing_sidecar(
        request=request,
        stage_b0_request_path=stage_b0_request,
        architecture_config_path=architecture_config_path,
        systemc_config_path=systemc_config_path,
    )
    _write_json(timing_sidecar_path, timing_sidecar)
    candidate_timing_profile = _build_candidate_timing_profile(
        timing_sidecar=timing_sidecar,
        timing_sidecar_path=timing_sidecar_path,
    )
    _write_json(candidate_timing_profile_path, candidate_timing_profile)
    generated_refs = _write_generated_systemc(
        generated_dir,
        candidate_id=candidate_id,
        timing_sidecar_ref=timing_sidecar_path,
        candidate_timing_profile_ref=candidate_timing_profile_path,
        candidate_timing_profile=candidate_timing_profile,
    )

    b4_request = dict(request)
    b4_request["requested_fidelity"] = "B4"
    b4_request["execution_mode"] = "gem5_systemc_timed_proxy"
    b4_refs = dict(refs)
    for key in B4_STAGE_B0_FILE_INPUT_REF_KEYS:
        resolved = _resolve_ref(b4_refs.get(key), root)
        if resolved is not None:
            b4_refs[key] = str(resolved)
    b4_refs["gem5_executable"] = str(_resolve_ref(str(gem5_executable), repo_root_path) or gem5_executable)
    b4_refs["gem5_config"] = str(_resolve_ref(str(gem5_config), repo_root_path) or gem5_config)
    b4_refs["systemc_bridge_library"] = str(_resolve_ref(str(systemc_bridge), repo_root_path) or systemc_bridge)
    b4_refs["timing_sidecar"] = str(timing_sidecar_path)
    b4_refs["candidate_timing_profile"] = str(candidate_timing_profile_path)
    b4_refs["strict_b4_runtime_timing_input"] = str(candidate_timing_profile_path)
    b4_refs["generated_systemc_header"] = generated_refs["header"]
    b4_refs["generated_systemc_source"] = generated_refs["source"]
    b4_request["input_refs"] = b4_refs
    profile = b4_request.setdefault("backend_capability_profile", {})
    if not isinstance(profile, dict):
        raise ValueError(f"backend_capability_profile is not a JSON object in {stage_b0_request}")
    profile["supports_gem5_timed_proxy"] = True
    profile["supports_real_bridge"] = True
    profile["supports_gem5_event_timed_device_proxy"] = True
    profile["claim_ceiling"] = "gem5_systemc_timed_proxy_only"
    non_claims = profile.setdefault("non_claims", [])
    if isinstance(non_claims, list):
        for item in (
            "real_bridge_requires_explicit_systemc_bridge_artifact",
            "candidate_specific_timing_sidecar_required",
            "candidate_runtime_profile_required_for_strict_event_b4",
            "no_cycle_accuracy_claim",
        ):
            if item not in non_claims:
                non_claims.append(item)
    b4_request["claim_ceiling"] = "descriptor_only"
    _write_json(b4_request_path, b4_request)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": timing_sidecar["generated_at_utc"],
        "candidate_id": candidate_id,
        "workload_id": context["workload_id"],
        "case_id": context["case_id"],
        "stage_b0_request_ref": str(stage_b0_request),
        "b4_backend_execution_request_ref": str(b4_request_path),
        "timing_sidecar_ref": str(timing_sidecar_path),
        "candidate_timing_profile_ref": str(candidate_timing_profile_path),
        "generated_systemc_refs": generated_refs,
        "runtime_timing_interface": {
            "strict_b4_timing_input_ref": str(candidate_timing_profile_path),
            "generated_systemc_role": "optional_compile_and_provenance_evidence",
            "per_candidate_gem5_rebuild_required": False,
        },
        "architecture_config_ref": str(architecture_config_path),
        "systemc_config_ref": str(systemc_config_path),
        "claim_ceiling": "gem5_systemc_timed_proxy_only",
        "non_claims": list(DEFAULT_NON_CLAIMS),
    }
    _write_json(manifest_path, manifest)
    return {
        "manifest": manifest_path,
        "manifest_payload": manifest,
        "request": b4_request_path,
        "timing_sidecar": timing_sidecar_path,
        "candidate_timing_profile": candidate_timing_profile_path,
        "generated_systemc": generated_refs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize candidate-specific B4 gem5/SystemC request artifacts.")
    parser.add_argument("--stage-b0-request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gem5-executable", type=Path, required=True)
    parser.add_argument("--gem5-config", type=Path, required=True)
    parser.add_argument("--systemc-bridge-library", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = materialize_b4_from_stage_b0(
        args.stage_b0_request,
        args.output_dir,
        gem5_executable=args.gem5_executable,
        gem5_config=args.gem5_config,
        systemc_bridge=args.systemc_bridge_library,
        repo_root=args.repo_root,
    )
    print(f"manifest: {result['manifest']}")
    print(f"request: {result['request']}")
    print(f"timing_sidecar: {result['timing_sidecar']}")
    print(f"candidate_timing_profile: {result['candidate_timing_profile']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
