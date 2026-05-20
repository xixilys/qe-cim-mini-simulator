#!/usr/bin/env python3
"""Materialize existing kernel-flow outputs into candidate-specific raw slots.

This helper is a narrow bridge from a real kernel RTL/HLS flow directory into a
DFT hardware-closure packet's expected raw evidence filenames.  It copies or
wraps files that already exist in the source flow and writes them under
``candidate_specific_evidence/<candidate>/<kernel>/`` for one packet unit.

It does not run EDA tools, does not adjudicate hard gates, and does not upgrade
hardware or deliverable completion.  The raw transcript registration and parser
layers must still hash, parse, and adjudicate the materialized files.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA = "dse.dft.hardware_closure_raw_stage_materialization.v1"
DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_raw_stage_materialization_validation.v1"
)
DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_raw_stage_materialization_status.v1"
)

_CLAIM_BOUNDARY = (
    "DFT hardware closure raw-stage materialization copies or wraps existing "
    "candidate/kernel flow outputs into packet-expected raw evidence filenames. "
    "It does not run tools, adjudicate hard gates, certify PPA, select Pareto "
    "winners, or upgrade hardware/deliverable completion."
)

_PASS_MARKERS = ("PASS", "PASSED", "SUCCESS", "MET", "COMPLETED SUCCESSFULLY")
_FAIL_MARKERS = ("FAIL", "FAILED", "ERROR", "FATAL", "VIOLATED")


def _load_json(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _safe_child_path(root: Path, rel_path: Any) -> tuple[Path | None, str | None]:
    rel = str(rel_path or "")
    if not rel:
        return None, "relative path is empty"
    candidate = Path(rel)
    if candidate.is_absolute():
        return None, f"absolute paths are not allowed: {rel}"
    if any(part == ".." for part in candidate.parts):
        return None, f"parent traversal is not allowed: {rel}"
    root_resolved = Path(root).resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"path escapes evidence root: {rel}"
    return resolved, None


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _materialized_ref(path: Path, evidence_root: Path, *, source: Path | None, generated: bool) -> Dict[str, Any]:
    rel = str(Path(path).resolve().relative_to(Path(evidence_root).resolve()))
    ref: Dict[str, Any] = {
        "path": rel,
        "exists": path.exists() and path.is_file(),
        "sha256": sha256_file(path) if path.exists() and path.is_file() else None,
        "hash_algorithm": "sha256",
        "generated_wrapper": generated,
    }
    if source is not None:
        ref["source"] = _source_ref(source)
    return ref


def _packet_path(packet_index_path: Path, packet_summary: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    ref = packet_summary.get("packet_json", {})
    if not isinstance(ref, Mapping):
        ref = {}
    return _safe_child_path(packet_index_path.parent, ref.get("path", ""))


def _unit_matches(unit: Mapping[str, Any], *, candidate_ids: set[str], kernel_ids: set[str]) -> bool:
    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    if candidate_ids and candidate_id not in candidate_ids:
        return False
    if kernel_ids and kernel_id not in kernel_ids:
        return False
    return True


def _expected_path(
    evidence_root: Path,
    unit: Mapping[str, Any],
    file_name: str,
) -> tuple[Path | None, str | None, str | None, str | None]:
    for row in unit.get("expected_evidence_files", []) or []:
        if not isinstance(row, Mapping):
            continue
        rel = str(row.get("path", ""))
        if Path(rel).name == file_name:
            path, error = _safe_child_path(evidence_root, rel)
            return path, error, rel, str(row.get("stage_id", ""))
    return None, f"expected evidence filename not found: {file_name}", None, None


def _json_status(path: Path) -> str:
    payload = _load_json(path)
    status = str(payload.get("status", payload.get("verdict", ""))).lower()
    if payload.get("passed") is True or status in {"pass", "passed", "success", "met"}:
        return "passed"
    if payload.get("passed") is False or status in {"fail", "failed", "error", "violated"}:
        return "failed"
    return "unknown"


def _text_status(path: Path, *, pass_markers: Sequence[str] = _PASS_MARKERS) -> str:
    text = _read_text(path).upper()
    if not text:
        return "missing"
    if any(re.search(rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])", text) for marker in _FAIL_MARKERS):
        return "failed"
    if any(marker in text for marker in pass_markers):
        return "passed"
    return "unknown"


def _write_wrapper(path: Path, payload: Mapping[str, Any]) -> None:
    write_json(path, payload)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _source_refs(source_flow_dir: Path, names: Sequence[str]) -> list[Dict[str, Any]]:
    return [
        {"role": name, **_source_ref(source_flow_dir / name)}
        for name in names
        if (source_flow_dir / name).exists()
    ]


def _source_alternatives(
    *,
    source_flow_dir: Path,
    stage_id: str,
    missing_file_name: str,
) -> list[Dict[str, Any]]:
    """Return real source-flow artifacts that are informative but not substitutes.

    This is intentionally diagnostic-only.  For example, a DC mapped Verilog
    netlist or timing report is useful blocker evidence for a missing
    ``dc_synth.ddc`` slot, but it must not be copied into that slot or used to
    satisfy the packet contract.
    """

    candidate_names: list[str] = []
    if stage_id == "dc_asic_synth_timing_area":
        candidate_names = [
            missing_file_name,
            "complex_gemm_gemv_tile_dc_mapped.v",
            "dc_timing.rpt",
            "dc_area.rpt",
            "dc_check_design.rpt",
            "dc_stdout.log",
            "dc_stderr.log",
            "results_dc.tgz",
        ]
    elif stage_id == "vivado_fpga_synth_or_impl":
        candidate_names = ["vivado_stdout.log", "vivado_timing_summary.rpt", "vivado_utilization.rpt", "results_vivado.tgz"]
    elif stage_id == "hls_or_rtl_sim":
        candidate_names = ["vcs_compile.log", "vcs_run.log", "results_vcs.tgz"]
    elif stage_id == "hls_or_rtl_synth":
        candidate_names = ["vivado_stdout.log", "vivado_stderr.log", "vivado_utilization.rpt"]
    elif stage_id == "golden_correctness":
        candidate_names = ["golden_correctness.json", "manifest.json"]

    seen: set[str] = set()
    refs: list[Dict[str, Any]] = []
    for name in candidate_names:
        if name in seen:
            continue
        seen.add(name)
        path = source_flow_dir / name
        if path.exists() and path.is_file():
            refs.append({"role": name, **_source_ref(path)})
    return refs


def _missing_blocker_id(stage_id: str, file_name: str) -> str:
    if stage_id == "dc_asic_synth_timing_area" and file_name == "dc_synth.ddc":
        return "missing_dc_synth_ddc_design_database"
    if stage_id == "dc_asic_synth_timing_area":
        return "missing_dc_asic_raw_stage_file"
    return f"missing_{stage_id}_raw_stage_file"


def _missing_reason(stage_id: str, file_name: str) -> str:
    if stage_id == "dc_asic_synth_timing_area" and file_name == "dc_synth.ddc":
        return (
            "Packet requires a real Design Compiler .ddc design database for "
            "the ASIC hard gate; mapped Verilog, logs, and timing/area reports "
            "are diagnostic evidence only and are not substitutes."
        )
    return "Packet-required candidate-specific raw stage file was not present after source-flow materialization."


def _missing_required_stage_files(
    *,
    evidence_root: Path,
    unit: Mapping[str, Any],
    source_flow_dir: Path,
) -> list[Dict[str, Any]]:
    missing: list[Dict[str, Any]] = []
    for row in unit.get("expected_evidence_files", []) or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("required", True) is not True:
            continue
        stage_id = str(row.get("stage_id", ""))
        if not stage_id or stage_id == "all":
            continue
        rel = str(row.get("path", ""))
        path, error = _safe_child_path(evidence_root, rel)
        file_name = Path(rel).name
        if error:
            missing.append(
                {
                    "stage_id": stage_id,
                    "path": rel,
                    "file_name": file_name,
                    "blocker_id": "invalid_expected_raw_stage_path",
                    "message": error,
                    "source_alternatives_present": [],
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
            )
            continue
        if path is not None and path.exists() and path.is_file():
            continue
        missing.append(
            {
                "stage_id": stage_id,
                "path": rel,
                "file_name": file_name,
                "blocker_id": _missing_blocker_id(stage_id, file_name),
                "message": _missing_reason(stage_id, file_name),
                "source_alternatives_present": _source_alternatives(
                    source_flow_dir=source_flow_dir,
                    stage_id=stage_id,
                    missing_file_name=file_name,
                ),
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return missing


def _golden_payloads(
    *,
    source_flow_dir: Path,
    candidate_id: str,
    kernel_id: str,
) -> Dict[str, Mapping[str, Any]]:
    source = _load_json(source_flow_dir / "golden_correctness.json")
    status = _json_status(source_flow_dir / "golden_correctness.json")
    passed = status == "passed"
    common = {
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "stage_id": "golden_correctness",
        "source_flow_dir": str(source_flow_dir),
        "source_refs": _source_refs(source_flow_dir, ["golden_correctness.json", "manifest.json"]),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return {
        "golden_correctness_report.json": {
            "schema_version": "dse.dft.hardware_closure.raw_golden_correctness_report.v1",
            **common,
            "status": "passed" if passed else "blocked",
            "verdict": "passed" if passed else "inconclusive",
            "passed": passed,
            "max_abs_error": 0.0 if passed else None,
        },
        "golden_reference_trace.json": {
            "schema_version": "dse.dft.hardware_closure.raw_golden_reference_trace.v1",
            **common,
            "status": "passed" if passed else "blocked",
            "verdict": "passed" if passed else "inconclusive",
            "passed": passed,
            "inputs": source.get("inputs", {}),
            "expected": source.get("expected", {}),
        },
        "candidate_input_manifest.json": {
            "schema_version": "dse.dft.hardware_closure.raw_candidate_input_manifest.v1",
            **common,
            "status": "passed" if passed else "blocked",
            "verdict": "passed" if passed else "inconclusive",
            "passed": passed,
            "input_source": "source_flow_golden_correctness",
        },
    }


def _sim_payloads(
    *,
    source_flow_dir: Path,
    candidate_id: str,
    kernel_id: str,
) -> Dict[str, Mapping[str, Any]]:
    status = _text_status(source_flow_dir / "vcs_run.log", pass_markers=("RTL_PASS", "PASS"))
    passed = status == "passed"
    return {
        "rtl_or_hls_sim_result.json": {
            "schema_version": "dse.dft.hardware_closure.raw_rtl_or_hls_sim_result.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "stage_id": "hls_or_rtl_sim",
            "status": "passed" if passed else "blocked",
            "verdict": "passed" if passed else "inconclusive",
            "passed": passed,
            "source_flow_dir": str(source_flow_dir),
            "source_refs": _source_refs(source_flow_dir, ["vcs_compile.log", "vcs_run.log"]),
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "sim_waveform_manifest.json": {
            "schema_version": "dse.dft.hardware_closure.raw_sim_waveform_manifest.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "stage_id": "hls_or_rtl_sim",
            "status": "passed" if passed else "blocked",
            "verdict": "passed" if passed else "inconclusive",
            "passed": passed,
            "waveform_available": False,
            "source_flow_dir": str(source_flow_dir),
            "source_refs": _source_refs(source_flow_dir, ["vcs_run.log"]),
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        },
    }


def _synth_payloads(
    *,
    source_flow_dir: Path,
    candidate_id: str,
    kernel_id: str,
) -> Dict[str, Mapping[str, Any]]:
    vivado_stdout = _read_text(source_flow_dir / "vivado_stdout.log")
    vivado_status = _text_status(source_flow_dir / "vivado_stdout.log", pass_markers=("SYNTH_DESIGN COMPLETED SUCCESSFULLY",))
    synth_passed = vivado_status == "passed"
    route_completed = "ROUTE_DESIGN COMPLETE" in vivado_stdout.upper()
    common = {
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "source_flow_dir": str(source_flow_dir),
        "source_refs": _source_refs(
            source_flow_dir,
            ["vivado_stdout.log", "vivado_stderr.log", "vivado_utilization.rpt", "vivado_timing_summary.rpt"],
        ),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return {
        "hls_or_rtl_synth_report.json": {
            "schema_version": "dse.dft.hardware_closure.raw_hls_or_rtl_synth_report.v1",
            **common,
            "stage_id": "hls_or_rtl_synth",
            "status": "passed" if synth_passed else "blocked",
            "verdict": "passed" if synth_passed else "inconclusive",
            "passed": synth_passed,
            "synth_tool": "vivado",
            "synth_design_completed": synth_passed,
        },
        "hls_or_rtl_synth_utilization.json": {
            "schema_version": "dse.dft.hardware_closure.raw_hls_or_rtl_synth_utilization.v1",
            **common,
            "stage_id": "hls_or_rtl_synth",
            "status": "passed" if synth_passed else "blocked",
            "verdict": "passed" if synth_passed else "inconclusive",
            "passed": synth_passed,
        },
        "vivado_route_status.json": {
            "schema_version": "dse.dft.hardware_closure.raw_vivado_route_status.v1",
            **common,
            "stage_id": "vivado_fpga_synth_or_impl",
            "status": "passed" if route_completed else "blocked",
            "verdict": "passed" if route_completed else "blocked",
            "passed": route_completed,
            "synth_design_completed": synth_passed,
            "implementation_route_completed": route_completed,
            "route_claim_boundary": (
                "Vivado synth_design evidence alone is not enough for the FPGA "
                "claim gate; implementation route completion is required."
            ),
        },
    }


def _dc_payloads(
    *,
    source_flow_dir: Path,
    candidate_id: str,
    kernel_id: str,
) -> Dict[str, Mapping[str, Any]]:
    status = "passed" if (source_flow_dir / "dc_timing.rpt").exists() and (source_flow_dir / "dc_area.rpt").exists() else "blocked"
    return {
        "dc_qor.rpt": {
            "schema_version": "dse.dft.hardware_closure.raw_dc_qor_summary.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "stage_id": "dc_asic_synth_timing_area",
            "status": status,
            "verdict": "inconclusive" if status != "passed" else "passed",
            "passed": status == "passed",
            "source_flow_dir": str(source_flow_dir),
            "source_refs": _source_refs(
                source_flow_dir,
                ["dc_stdout.log", "dc_stderr.log", "dc_timing.rpt", "dc_area.rpt", "dc_synth.ddc"],
            ),
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    }


def _materialization_plan(source_flow_dir: Path, *, candidate_id: str, kernel_id: str) -> Dict[str, tuple[str, Path | Mapping[str, Any]]]:
    """Return destination filename -> (operation, source_or_payload)."""

    plan: Dict[str, tuple[str, Path | Mapping[str, Any]]] = {}
    for name, payload in _golden_payloads(source_flow_dir=source_flow_dir, candidate_id=candidate_id, kernel_id=kernel_id).items():
        plan[name] = ("write_json", payload)
    if (source_flow_dir / "vcs_run.log").exists():
        plan["hls_csim_or_rtl_sim_transcript.log"] = ("copy", source_flow_dir / "vcs_run.log")
        for name, payload in _sim_payloads(source_flow_dir=source_flow_dir, candidate_id=candidate_id, kernel_id=kernel_id).items():
            plan[name] = ("write_json", payload)
    if (source_flow_dir / "vivado_stdout.log").exists():
        plan["hls_or_rtl_synth_transcript.log"] = ("copy", source_flow_dir / "vivado_stdout.log")
        plan["vivado_synth_or_impl.log"] = ("copy", source_flow_dir / "vivado_stdout.log")
        for source_name, dest_name in (
            ("vivado_timing_summary.rpt", "vivado_timing_summary.rpt"),
            ("vivado_utilization.rpt", "vivado_utilization.rpt"),
        ):
            if (source_flow_dir / source_name).exists():
                plan[dest_name] = ("copy", source_flow_dir / source_name)
        for name, payload in _synth_payloads(source_flow_dir=source_flow_dir, candidate_id=candidate_id, kernel_id=kernel_id).items():
            plan[name] = ("write_json", payload)
    for source_name, dest_name in (
        ("dc_stdout.log", "dc_shell.log"),
        ("dc_timing.rpt", "dc_timing.rpt"),
        ("dc_area.rpt", "dc_area.rpt"),
        ("dc_synth.ddc", "dc_synth.ddc"),
    ):
        if (source_flow_dir / source_name).exists():
            plan[dest_name] = ("copy", source_flow_dir / source_name)
    if any((source_flow_dir / name).exists() for name in ("dc_stdout.log", "dc_timing.rpt", "dc_area.rpt")):
        for name, payload in _dc_payloads(source_flow_dir=source_flow_dir, candidate_id=candidate_id, kernel_id=kernel_id).items():
            plan[name] = ("write_json", payload)
    return plan


def _write_materialized_file(
    *,
    evidence_root: Path,
    unit: Mapping[str, Any],
    file_name: str,
    operation: str,
    source_or_payload: Path | Mapping[str, Any],
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    dest, error, rel, stage_id = _expected_path(evidence_root, unit, file_name)
    if dest is None or rel is None:
        return None, {"file_name": file_name, "message": error or "missing destination"}
    if operation == "copy":
        source = Path(source_or_payload)
        if not source.exists() or not source.is_file():
            return None, {"file_name": file_name, "message": f"source missing: {source}"}
        _copy_file(source, dest)
        return {
            "file_name": file_name,
            "stage_id": stage_id,
            "operation": "copy",
            "artifact": _materialized_ref(dest, evidence_root, source=source, generated=False),
        }, None
    _write_wrapper(dest, source_or_payload if isinstance(source_or_payload, Mapping) else {})
    return {
        "file_name": file_name,
        "stage_id": stage_id,
        "operation": "write_json",
        "artifact": _materialized_ref(dest, evidence_root, source=None, generated=True),
    }, None


def build_dft_hardware_closure_raw_stage_materialization(
    *,
    closure_packet_index_path: Path,
    source_flow_dir: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    packet_index_path = Path(closure_packet_index_path)
    source_flow_dir = Path(source_flow_dir)
    evidence_root = Path(evidence_root or packet_index_path.parent)
    packet_index = _load_json(packet_index_path)
    candidate_filter = {str(item) for item in candidate_ids}
    kernel_filter = {str(item) for item in kernel_ids}
    unit_budget = max_units if max_units and max_units > 0 else None
    units: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []
    if not source_flow_dir.exists() or not source_flow_dir.is_dir():
        errors.append({"field": "source_flow_dir", "message": f"source flow directory missing: {source_flow_dir}"})

    for packet_summary in packet_index.get("packets", []) or []:
        if errors:
            break
        if not isinstance(packet_summary, Mapping):
            continue
        packet_path, packet_error = _packet_path(packet_index_path, packet_summary)
        if packet_path is None:
            errors.append({"packet_id": packet_summary.get("packet_id"), "message": packet_error})
            continue
        packet = _load_json(packet_path)
        for unit in packet.get("units", []) or []:
            if not isinstance(unit, Mapping):
                continue
            if not _unit_matches(unit, candidate_ids=candidate_filter, kernel_ids=kernel_filter):
                continue
            if unit_budget is not None and len(units) >= unit_budget:
                break
            candidate_id = str(unit.get("candidate_id", ""))
            kernel_id = str(unit.get("kernel_id", ""))
            plan = _materialization_plan(source_flow_dir, candidate_id=candidate_id, kernel_id=kernel_id)
            materialized: list[Dict[str, Any]] = []
            blockers: list[Dict[str, Any]] = []
            for file_name, (operation, source_or_payload) in sorted(plan.items()):
                ref, error = _write_materialized_file(
                    evidence_root=evidence_root,
                    unit=unit,
                    file_name=file_name,
                    operation=operation,
                    source_or_payload=source_or_payload,
                )
                if error:
                    blockers.append(error)
                elif ref:
                    materialized.append(ref)
            missing_required = _missing_required_stage_files(
                evidence_root=evidence_root,
                unit=unit,
                source_flow_dir=source_flow_dir,
            )
            blocker_count = len(blockers) + len(missing_required)
            status = (
                "blocked_materialization_errors"
                if blockers
                else "blocked_missing_required_raw_stage_files"
                if missing_required
                else "candidate_specific_raw_stage_files_materialized_pending_registration"
                if materialized
                else "blocked_no_source_flow_outputs"
            )
            units.append(
                {
                    "unit_id": str(unit.get("unit_id", "")),
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "packet_id": packet.get("packet_id"),
                    "shard_id": packet.get("shard_id"),
                    "status": status,
                    "source_flow_dir": str(source_flow_dir),
                    "materialized_file_count": len(materialized),
                    "materialized_files": materialized,
                    "missing_required_raw_stage_file_count": len(missing_required),
                    "missing_required_raw_stage_files": missing_required,
                    "materialization_error_count": len(blockers),
                    "blocker_count": blocker_count,
                    "blockers": blockers,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "claim_boundary": _CLAIM_BOUNDARY,
                }
            )
        if unit_budget is not None and len(units) >= unit_budget:
            break
    materialized_count = sum(int(row.get("materialized_file_count", 0) or 0) for row in units)
    blocked_count = sum(1 for row in units if str(row.get("status", "")).startswith("blocked"))
    missing_required_count = sum(int(row.get("missing_required_raw_stage_file_count", 0) or 0) for row in units)
    status = (
        "failed_invalid_inputs"
        if errors
        else "blocked_materialization_errors"
        if any(str(row.get("status", "")) == "blocked_materialization_errors" for row in units)
        else "blocked_missing_required_raw_stage_files"
        if missing_required_count
        else "blocked_no_source_flow_outputs"
        if blocked_count
        else "candidate_specific_raw_stage_files_materialized_pending_registration"
        if materialized_count
        else "failed_no_matching_units"
    )
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": _source_ref(packet_index_path),
            "source_flow_dir": str(source_flow_dir),
        },
        "evidence_root": str(evidence_root),
        "release_id": packet_index.get("release_id"),
        "candidate_count": packet_index.get("candidate_count"),
        "major_kernel_count": packet_index.get("major_kernel_count"),
        "unit_count": len(units),
        "materialized_unit_count": sum(1 for row in units if row.get("materialized_file_count")),
        "materialized_file_count": materialized_count,
        "missing_required_raw_stage_file_count": missing_required_count,
        "blocked_unit_count": blocked_count,
        "error_count": len(errors),
        "errors": errors,
        "units": units,
        "adjudication_result": "not_adjudicated_by_raw_stage_materialization",
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _ref_inside_root(root: Path, ref: Mapping[str, Any]) -> tuple[Path | None, str | None]:
    raw = str(ref.get("path", ""))
    if not raw:
        return None, "file reference path is empty"
    candidate = Path(raw)
    root_resolved = Path(root).resolve()
    resolved = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"file reference escapes evidence root: {raw}"
    return resolved, None


def validate_dft_hardware_closure_raw_stage_materialization(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    payload = _load_json(payload_or_path) if isinstance(payload_or_path, Path) else dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    evidence_root = Path(str(payload.get("evidence_root") or "."))
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected raw stage materialization schema"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "raw materialization cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated_by_raw_stage_materialization":
        errors.append({"field": "adjudication_result", "message": "raw materialization cannot adjudicate gates"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "raw materialization cannot pass stages"})
    for error_index, build_error in enumerate(payload.get("errors", []) or []):
        errors.append({"field": f"errors[{error_index}]", "message": str(build_error)})
    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append({"field": "units", "message": "non-empty unit rows required"})
        units = []
    materialized_total = 0
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            errors.append({"field": f"units[{unit_index}]", "message": "unit row must be an object"})
            continue
        for field in ("hardware_completion_eligible", "deliverable_complete"):
            if unit.get(field) is True:
                errors.append({"field": f"units[{unit_index}].{field}", "message": "unit cannot upgrade claims"})
        files = unit.get("materialized_files", [])
        if not isinstance(files, list):
            errors.append({"field": f"units[{unit_index}].materialized_files", "message": "materialized_files must be a list"})
            files = []
        materialized_total += len(files)
        for file_index, item in enumerate(files):
            if not isinstance(item, Mapping):
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}]", "message": "file row must be an object"})
                continue
            artifact = item.get("artifact", {})
            if not isinstance(artifact, Mapping):
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}].artifact", "message": "artifact ref required"})
                continue
            path, path_error = _ref_inside_root(evidence_root, artifact)
            if path is None:
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}].artifact.path", "message": str(path_error)})
                continue
            if not path.exists() or not path.is_file():
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}].artifact.path", "message": "materialized file must exist"})
                continue
            if artifact.get("sha256") != sha256_file(path):
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}].artifact.sha256", "message": "materialized file hash mismatch"})
            if artifact.get("hash_algorithm") != "sha256":
                errors.append({"field": f"units[{unit_index}].materialized_files[{file_index}].artifact.hash_algorithm", "message": "hash_algorithm must be sha256"})
    if materialized_total != int(payload.get("materialized_file_count", 0) or 0):
        errors.append({"field": "materialized_file_count", "message": "materialized total must equal unit sum"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_VALIDATION_SCHEMA,
        "valid": not errors,
        "unit_count": len(units),
        "materialized_file_count": materialized_total,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_raw_stage_materialization(
    out_dir: Path,
    *,
    closure_packet_index_path: Path,
    source_flow_dir: Path,
    evidence_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_raw_stage_materialization(
        closure_packet_index_path=closure_packet_index_path,
        source_flow_dir=source_flow_dir,
        evidence_root=evidence_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization.json", payload)
    validation = validate_dft_hardware_closure_raw_stage_materialization(payload)
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_STATUS_SCHEMA,
        "status": "passed" if validation["valid"] else "failed",
        "raw_stage_materialization": "dft_hardware_closure_raw_stage_materialization.json",
        "validation": "dft_hardware_closure_raw_stage_materialization_validation.json",
        "unit_count": payload["unit_count"],
        "materialized_unit_count": payload["materialized_unit_count"],
        "materialized_file_count": payload["materialized_file_count"],
        "missing_required_raw_stage_file_count": payload["missing_required_raw_stage_file_count"],
        "blocked_unit_count": payload["blocked_unit_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_VALIDATION_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_STATUS_SCHEMA",
    "build_dft_hardware_closure_raw_stage_materialization",
    "validate_dft_hardware_closure_raw_stage_materialization",
    "write_dft_hardware_closure_raw_stage_materialization",
]
