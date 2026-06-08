#!/usr/bin/env python3
"""DFT/QE hardware evidence matrix and IC/EDA availability contracts.

The helpers in this module are deliberately DFT-profile scoped.  They turn the
plan's Wave-2/Wave-3 requirements into replayable data structures without
claiming that a tool run succeeded unless the matching transcript evidence is
present.
"""

from __future__ import annotations

from collections import defaultdict
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
OPTIONAL_IC_EDA_TOOL_GROUPS: Dict[str, tuple[str, ...]] = {
    "hls": ("vitis_hls", "vivado_hls"),
}


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


def build_major_kernel_evidence_matrix_from_release_gate(
    release_gate: Mapping[str, Any],
    *,
    source_ref: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an all-candidate major-kernel matrix from a Step5 release gate.

    This is intentionally stricter than the historical disposition-only matrix:
    it trusts only a release-gate payload whose candidate×kernel units and
    required hard-gate stages have already passed.  The result is still an
    attachment/visibility artifact, not a deliverable-completion or winner
    selection claim.
    """

    blockers: list[Dict[str, Any]] = []
    if not isinstance(release_gate, Mapping):
        blockers.append({"id": "release_gate_not_mapping", "reason": "release gate payload is not an object"})
        release_gate = {}
    if release_gate.get("schema_version") != "dse.dft.hardware_closure_release_gate.v1":
        blockers.append(
            {
                "id": "unexpected_release_gate_schema",
                "reason": "release gate must use dse.dft.hardware_closure_release_gate.v1",
                "schema_version": release_gate.get("schema_version"),
            }
        )
    if release_gate.get("hardware_completion_eligible") is not True:
        blockers.append(
            {
                "id": "release_gate_not_hardware_completion_eligible",
                "reason": "release gate has not passed all candidate×kernel hard gates",
            }
        )
    expected_kernel_ids = tuple(str(item) for item in release_gate.get("expected_kernel_ids", []) or [])
    missing_expected = sorted(set(MAJOR_SCF_KERNEL_IDS) - set(expected_kernel_ids))
    extra_expected = sorted(set(expected_kernel_ids) - set(MAJOR_SCF_KERNEL_IDS))
    if missing_expected or extra_expected:
        blockers.append(
            {
                "id": "release_gate_kernel_set_mismatch",
                "missing_kernel_ids": missing_expected,
                "extra_kernel_ids": extra_expected,
                "reason": "release gate expected kernels must match the eight major SCF kernels",
            }
        )
    if int(release_gate.get("blocked_stage_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_blocked_stages", "count": release_gate.get("blocked_stage_count")})
    if int(release_gate.get("failed_stage_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_failed_stages", "count": release_gate.get("failed_stage_count")})
    if int(release_gate.get("blocked_unit_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_blocked_units", "count": release_gate.get("blocked_unit_count")})
    if int(release_gate.get("failed_unit_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_failed_units", "count": release_gate.get("failed_unit_count")})
    if int(release_gate.get("blocked_candidate_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_blocked_candidates", "count": release_gate.get("blocked_candidate_count")})
    if int(release_gate.get("failed_candidate_count", 0) or 0) != 0:
        blockers.append({"id": "release_gate_has_failed_candidates", "count": release_gate.get("failed_candidate_count")})

    unit_rows = [
        row for row in release_gate.get("unit_rows", []) or []
        if isinstance(row, Mapping)
    ]
    candidate_rows = [
        row for row in release_gate.get("candidate_rows", []) or []
        if isinstance(row, Mapping)
    ]
    candidate_ids = sorted(
        {
            str(row.get("candidate_id"))
            for row in candidate_rows
            if row.get("candidate_id")
        }
        | {
            str(row.get("candidate_id"))
            for row in unit_rows
            if row.get("candidate_id")
        }
    )
    if not candidate_ids:
        blockers.append({"id": "release_gate_missing_candidate_rows", "reason": "no candidate ids were found"})

    required_stage_ids = {
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
        "dc_asic_synth_timing_area",
    }
    rows_by_kernel: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in unit_rows:
        kernel_id = str(row.get("kernel_id") or "")
        rows_by_kernel[kernel_id].append(row)
        if row.get("unit_gate_passed") is not True:
            blockers.append(
                {
                    "id": "release_gate_unit_not_passed",
                    "candidate_id": row.get("candidate_id"),
                    "kernel_id": kernel_id,
                    "status": row.get("status"),
                }
            )
        observed = {str(item) for item in row.get("observed_stage_ids", []) or []}
        missing_stages = sorted(required_stage_ids - observed)
        if missing_stages:
            blockers.append(
                {
                    "id": "release_gate_unit_missing_required_stages",
                    "candidate_id": row.get("candidate_id"),
                    "kernel_id": kernel_id,
                    "missing_stage_ids": missing_stages,
                }
            )

    kernel_rows: list[Dict[str, Any]] = []
    for kernel in MAJOR_SCF_KERNELS:
        kernel_id = kernel["kernel_id"]
        rows = rows_by_kernel.get(kernel_id, [])
        passed_rows = [row for row in rows if row.get("unit_gate_passed") is True]
        missing_candidate_ids = sorted(
            set(candidate_ids)
            - {
                str(row.get("candidate_id"))
                for row in rows
                if row.get("candidate_id")
            }
        )
        if missing_candidate_ids:
            blockers.append(
                {
                    "id": "release_gate_kernel_missing_candidate_units",
                    "kernel_id": kernel_id,
                    "missing_candidate_ids": missing_candidate_ids,
                }
            )
        kernel_rows.append(
            {
                **kernel,
                "status": "passed" if rows and not missing_candidate_ids and len(passed_rows) == len(rows) else "blocked",
                "disposition": "accelerated_claim",
                "claim_allowed": bool(rows and not missing_candidate_ids and len(passed_rows) == len(rows)),
                "trusted": bool(rows and not missing_candidate_ids and len(passed_rows) == len(rows)),
                "candidate_count": len(candidate_ids),
                "unit_count": len(rows),
                "passed_unit_count": len(passed_rows),
                "required_stage_ids": sorted(required_stage_ids),
                "claim_type": "fpga_and_asic",
                "source": "dft_hardware_closure_release_gate",
                "claim_boundary": (
                    "This row is derived from candidate-stamped release-gate "
                    "hard-gate results; it is not a standalone EDA run and "
                    "does not select a trusted winner."
                ),
            }
        )

    trusted = not blockers
    return {
        "schema_version": DFT_HARDWARE_EVIDENCE_SCHEMA,
        "candidate_id": "all_release_candidates",
        "source": "dft_hardware_closure_release_gate",
        "source_artifacts": {"release_gate": dict(source_ref or {})},
        "release_id": release_gate.get("release_id"),
        "major_kernel_count": len(MAJOR_SCF_KERNELS),
        "candidate_count": len(candidate_ids),
        "unit_count": len(unit_rows),
        "stage_count": release_gate.get("stage_count"),
        "stage_gate_passed_count": release_gate.get("stage_gate_passed_count"),
        "unit_gate_passed_count": release_gate.get("unit_gate_passed_count"),
        "candidate_gate_passed_count": release_gate.get("candidate_gate_passed_count"),
        "kernel_rows": kernel_rows,
        "status": "passed" if trusted else "blocked",
        "trusted": trusted,
        "hardware_completion_eligible": bool(
            trusted and release_gate.get("hardware_completion_eligible") is True
        ),
        "deliverable_complete": False,
        "blockers": blockers,
        "blocker_ids": [str(item["id"]) for item in blockers],
        "claim_boundary": (
            "Release-gate-derived matrix records that the current candidate×kernel "
            "hard gates are attached and passed. It is not full-SCF numerical "
            "correctness, not a single best architecture decision, and not "
            "deliverable completion."
        ),
    }


def build_ic_eda_tool_availability_report(
    tool_results: Iterable[Mapping[str, Any]],
    *,
    required_tools: Sequence[str] = REQUIRED_IC_EDA_TOOLS,
    optional_tool_groups: Mapping[str, Sequence[str]] | None = None,
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
            for marker in ("version", "vivado", "vcs", "dc_shell", "vitis hls", "vivado hls")
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
    optional_groups: Dict[str, Dict[str, Any]] = {}
    for group_id, group_tools in (optional_tool_groups or {}).items():
        available_tools = [
            tool for tool in group_tools
            if tool in by_tool and by_tool[tool]["status"] == "passed"
        ]
        attempted_tools = [tool for tool in group_tools if tool in by_tool]
        blocked_group_tools = [
            tool for tool in group_tools
            if tool in by_tool and by_tool[tool]["status"] != "passed"
        ]
        missing_group_tools = [tool for tool in group_tools if tool not in by_tool]
        group_status = "passed" if available_tools else "blocked"
        optional_groups[str(group_id)] = {
            "group_id": str(group_id),
            "availability_policy": "any_of",
            "required_for_ic_eda_availability_status": False,
            "tools": list(group_tools),
            "attempted_tools": attempted_tools,
            "available_tools": available_tools,
            "blocked_tools": blocked_group_tools,
            "missing_tools": missing_group_tools,
            "status": group_status,
            "available": bool(available_tools),
            "availability_probe_passed": bool(available_tools),
            "tool_rows": [by_tool[tool] for tool in group_tools if tool in by_tool],
            "hardware_completion_eligible": False,
            "kernel_ppa_evidence": False,
            "claim_boundary": (
                "Optional tool-group reachability supports planning downstream "
                "tool runs only; it is not synthesis, implementation, timing, "
                "area, PPA, bitstream, or QE correctness evidence."
            ),
        }
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

    report = {
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
    if optional_groups:
        report["optional_tool_groups"] = optional_groups
        if "hls" in optional_groups:
            report["hls_tool_available"] = bool(optional_groups["hls"]["available"])
            report["hls_tool_available_tools"] = list(optional_groups["hls"]["available_tools"])
    return report


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
