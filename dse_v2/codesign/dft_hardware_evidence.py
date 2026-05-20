#!/usr/bin/env python3
"""DFT/QE hardware evidence matrix and IC/EDA availability contracts.

The helpers in this module are deliberately DFT-profile scoped.  They turn the
plan's Wave-2/Wave-3 requirements into replayable data structures without
claiming that a tool run succeeded unless the matching transcript evidence is
present.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Sequence

from .hardware_claim_gates import validate_hardware_claim_evidence


DFT_HARDWARE_EVIDENCE_SCHEMA = "dse.dft_scf.hardware_evidence_matrix.v1"
IC_EDA_TOOL_AVAILABILITY_SCHEMA = "dse.dft_scf.ic_eda_tool_availability.v1"

MAJOR_SCF_KERNELS: tuple[Dict[str, str], ...] = (
    {
        "kernel_id": "fft_ifft_ffft",
        "name": "FFT / iFFT / fFFT",
        "kernel_family": "spectral_transform",
    },
    {
        "kernel_id": "transpose_layout_conversion",
        "name": "3D transpose / layout conversion",
        "kernel_family": "data_movement",
    },
    {
        "kernel_id": "hpsi_local_potential",
        "name": "Hψ local potential path",
        "kernel_family": "hamiltonian_apply",
    },
    {
        "kernel_id": "kinetic_add",
        "name": "kinetic add",
        "kernel_family": "hamiltonian_apply",
    },
    {
        "kernel_id": "nonlocal_projector",
        "name": "nonlocal projector",
        "kernel_family": "projector",
    },
    {
        "kernel_id": "complex_gemm_gemv_tile",
        "name": "complex GEMM / GEMV tile",
        "kernel_family": "dense_linear_algebra",
    },
    {
        "kernel_id": "reduction_dot_tree",
        "name": "reduction / dot product tree",
        "kernel_family": "reduction",
    },
    {
        "kernel_id": "dma_hbm_movement_engine",
        "name": "DMA / HBM movement engine",
        "kernel_family": "memory_movement",
    },
)

MAJOR_SCF_KERNEL_IDS = tuple(item["kernel_id"] for item in MAJOR_SCF_KERNELS)

FIRST_PROTOTYPE_HOST_BOUND_STAGES = (
    "io",
    "input_parsing",
    "scf_control",
    "convergence_judgment",
    "diagonalization",
    "mixing",
)

REQUIRED_IC_EDA_TOOLS: tuple[str, ...] = ("dc_shell", "vcs", "vivado")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "passed"}
    return bool(value)


def _rows_by_kernel(evidence_rows: Iterable[Mapping[str, Any]]) -> Dict[str, list[Mapping[str, Any]]]:
    grouped: Dict[str, list[Mapping[str, Any]]] = {}
    for row in evidence_rows:
        if not isinstance(row, Mapping):
            continue
        kernel_id = str(row.get("kernel_id") or row.get("kernel") or "").strip()
        if not kernel_id:
            continue
        grouped.setdefault(kernel_id, []).append(row)
    return grouped


def build_major_kernel_evidence_matrix(
    kernel_dispositions: Iterable[Mapping[str, Any]],
    *,
    evidence_rows: Iterable[Mapping[str, Any]] = (),
    candidate_id: str | None = None,
) -> Dict[str, Any]:
    """Build a fail-closed coverage matrix for the eight major SCF kernels.

    Each major kernel must have an explicit disposition.  Accelerated claims are
    passed through the claim-specific FPGA/ASIC gate.  Host-bound rows are
    accepted only as honest first-prototype accounting and never as acceleration
    evidence.
    """

    dispositions = {
        str(row.get("kernel_id") or row.get("kernel") or "").strip(): dict(row)
        for row in kernel_dispositions
        if isinstance(row, Mapping)
    }
    grouped_evidence = _rows_by_kernel(evidence_rows)
    kernel_rows: list[Dict[str, Any]] = []
    blockers: list[Dict[str, Any]] = []

    for kernel in MAJOR_SCF_KERNELS:
        kernel_id = kernel["kernel_id"]
        disposition = dispositions.get(kernel_id)
        if not disposition:
            blocker = {
                "id": "missing_major_kernel_disposition",
                "kernel_id": kernel_id,
                "reason": "major SCF kernel has no acceleration, host-bound, or blocker row",
            }
            blockers.append(blocker)
            kernel_rows.append({**kernel, "status": "blocked", "blockers": [blocker]})
            continue

        mode = _norm(disposition.get("disposition") or disposition.get("status"))
        if mode in {"host_bound", "host", "cpu_bound"}:
            cost_accounted = _bool(disposition.get("host_cost_accounted"))
            row_blockers: list[Dict[str, Any]] = []
            if not cost_accounted:
                row_blockers.append(
                    {
                        "id": "host_bound_kernel_cost_not_accounted",
                        "kernel_id": kernel_id,
                        "reason": "host-bound kernel/stage must carry an explicit cost row",
                    }
                )
            if _bool(disposition.get("acceleration_claim")):
                row_blockers.append(
                    {
                        "id": "host_bound_row_cannot_claim_acceleration",
                        "kernel_id": kernel_id,
                        "reason": "host-bound rows cannot be reported as hardware acceleration",
                    }
                )
            blockers.extend(row_blockers)
            kernel_rows.append(
                {
                    **kernel,
                    "status": "host_bound" if not row_blockers else "blocked",
                    "disposition": "host_bound",
                    "host_cost_accounted": cost_accounted,
                    "claim_allowed": False,
                    "trusted": False,
                    "blockers": row_blockers,
                    "claim_boundary": (
                        "Host-bound rows are included in full-SCF cost and do not "
                        "support hardware acceleration claims."
                    ),
                }
            )
            continue

        if mode in {"accelerated_claim", "hardware_claim", "claimed_accelerated"}:
            claim_type = str(disposition.get("claim_type") or "fpga").strip().lower()
            rows = [
                row for row in list(disposition.get("evidence_rows") or [])
                if not str(row.get("kernel_id") or row.get("kernel") or "").strip()
                or str(row.get("kernel_id") or row.get("kernel")).strip() == kernel_id
            ] + grouped_evidence.get(kernel_id, [])
            gate = validate_hardware_claim_evidence(
                claim_type,
                rows,
                candidate_id=candidate_id,
                kernel_id=kernel_id,
            )
            row_blockers = [
                {
                    "id": "hardware_claim_gate_blocked",
                    "kernel_id": kernel_id,
                    "missing_or_blocked_stages": gate["missing_or_blocked_stages"],
                    "reasons": gate["reasons"],
                }
            ] if not gate["claim_allowed"] else []
            blockers.extend(row_blockers)
            kernel_rows.append(
                {
                    **kernel,
                    "status": "passed" if gate["claim_allowed"] else "blocked",
                    "disposition": "accelerated_claim",
                    "claim_type": claim_type,
                    "claim_allowed": gate["claim_allowed"],
                    "trusted": gate["trusted"],
                    "hardware_claim_gate": gate,
                    "blockers": row_blockers,
                }
            )
            continue

        row_blocker = {
            "id": "unsupported_kernel_disposition",
            "kernel_id": kernel_id,
            "reason": f"unsupported major-kernel disposition: {mode or '<empty>'}",
        }
        blockers.append(row_blocker)
        kernel_rows.append({**kernel, "status": "blocked", "blockers": [row_blocker]})

    return {
        "schema_version": DFT_HARDWARE_EVIDENCE_SCHEMA,
        "candidate_id": candidate_id,
        "major_kernel_count": len(MAJOR_SCF_KERNELS),
        "kernel_rows": kernel_rows,
        "status": "passed" if not blockers else "blocked",
        "trusted": not blockers,
        "blockers": blockers,
        "blocker_ids": [str(item["id"]) for item in blockers],
        "claim_boundary": (
            "The matrix proves only that every major kernel has an explicit "
            "disposition and that accelerated rows satisfy their own claim "
            "gate.  It is not full-SCF completion by itself."
        ),
    }


def build_ic_eda_tool_availability_report(
    tool_results: Iterable[Mapping[str, Any]],
    *,
    required_tools: Sequence[str] = REQUIRED_IC_EDA_TOOLS,
    environment: str = "ic-eda",
) -> Dict[str, Any]:
    """Normalize real IC/EDA tool probes into a fail-closed availability report."""

    by_tool: Dict[str, Dict[str, Any]] = {}
    for raw in tool_results:
        if not isinstance(raw, Mapping):
            continue
        tool = str(raw.get("tool") or raw.get("tool_id") or "").strip()
        if not tool:
            continue
        stdout = str(raw.get("stdout") or raw.get("output") or "")
        stderr = str(raw.get("stderr") or "")
        returncode = raw.get("returncode")
        explicit_status = _norm(raw.get("status"))
        version_like_output = any(
            marker in stdout.lower()
            for marker in ("version", "vivado", "vcs", "dc_shell")
        )
        not_found_error = any(
            marker in (stdout + "\n" + stderr).lower()
            for marker in ("command not found", "no such file", "not found")
        )
        available = (
            not not_found_error
            and (
                explicit_status in {"passed", "available", "success"}
                or (returncode == 0 and bool(stdout.strip()))
                or version_like_output
            )
        )
        if explicit_status in {"passed", "available", "success"} and not not_found_error:
            availability_evidence_kind = "explicit_status"
        elif returncode == 0 and bool(stdout.strip()) and not not_found_error:
            availability_evidence_kind = "zero_returncode_with_stdout"
        elif version_like_output and not not_found_error:
            availability_evidence_kind = "version_like_output_nonzero_returncode"
        elif not_found_error:
            availability_evidence_kind = "not_found_error"
        else:
            availability_evidence_kind = "blocked_or_missing_output"
        status = "passed" if available else "blocked"
        by_tool[tool] = {
            "tool": tool,
            "status": status,
            "available": available,
            "availability_probe_passed": available,
            "availability_evidence_kind": availability_evidence_kind,
            "command": raw.get("command"),
            "returncode": returncode,
            "version_text": stdout.strip(),
            "stderr": stderr.strip(),
            "hardware_completion_eligible": False,
            "kernel_ppa_evidence": False,
            "claim_boundary": (
                "This row proves tool reachability only; it is not a "
                "candidate-specific kernel simulation/synthesis/timing/area "
                "or FPGA implementation result."
            ),
            "completion_eligible": False,
        }

    missing_tools = [tool for tool in required_tools if tool not in by_tool]
    blocked_tools = [
        tool
        for tool in required_tools
        if tool in by_tool and by_tool[tool]["status"] != "passed"
    ]
    tool_rows = [by_tool[tool] for tool in required_tools if tool in by_tool]
    blockers: list[Dict[str, Any]] = []
    if missing_tools:
        blockers.append(
            {
                "id": "required_ic_eda_tool_not_attempted",
                "tools": missing_tools,
                "reason": "required IC/EDA tool has no recorded probe",
            }
        )
    if blocked_tools:
        blockers.append(
            {
                "id": "required_ic_eda_tool_blocked",
                "tools": blocked_tools,
                "reason": "required IC/EDA tool probe did not produce pass evidence",
            }
        )

    return {
        "schema_version": IC_EDA_TOOL_AVAILABILITY_SCHEMA,
        "environment": environment,
        "required_tools": list(required_tools),
        "tool_rows": tool_rows,
        "status": "passed" if not blockers else "blocked",
        "all_required_tools_available": not blockers,
        "artifact_role": "tool_availability_only_not_kernel_ppa",
        "completion_claim": "availability_only_not_kernel_ppa",
        "kernel_ppa_evidence": False,
        "timing_area_evidence": False,
        "implementation_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "required_next_step": (
            "Run per-kernel golden/sim/synth/Vivado/DC flows before allowing "
            "FPGA/ASIC acceleration claims."
        ),
        "blockers": blockers,
        "blocker_ids": [str(item["id"]) for item in blockers],
        "claim_boundary": (
            "Tool availability proves that commands are reachable.  It is not "
            "kernel synthesis, timing, area, implementation, or PPA evidence."
        ),
    }


def run_tool_probe_commands(
    commands: Mapping[str, Sequence[str]],
    *,
    runner: Callable[[Sequence[str]], Mapping[str, Any]],
    environment: str,
) -> Dict[str, Any]:
    """Run injected probe commands and return a normalized availability report.

    The injected runner keeps tests deterministic while production scripts can
    provide a subprocess-backed implementation.
    """

    results = []
    for tool, command in commands.items():
        outcome = dict(runner(command))
        outcome.setdefault("tool", tool)
        outcome.setdefault("command", " ".join(command))
        results.append(outcome)
    return build_ic_eda_tool_availability_report(results, environment=environment)
