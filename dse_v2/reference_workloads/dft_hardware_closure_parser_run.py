#!/usr/bin/env python3
"""Candidate-specific hard-gate parser runner for DFT/QE closure evidence.

This helper reads ``dft_hardware_closure_evidence_intake.json`` and writes
parsed stage-result JSON files only when the corresponding candidate bundle and
raw stage evidence files already exist.  Missing raw files become blocker rows,
not synthetic parsed results.  Parser outputs are still not hard-gate passes;
Wave20's parsed-evidence manifest and later adjudicators must consume them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (
    DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
)

DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA = "dse.dft.hardware_closure_parser_run.v1"
DFT_HARDWARE_CLOSURE_PARSER_RUN_VALIDATION_SCHEMA = "dse.dft.hardware_closure_parser_run_validation.v1"

_STAGE_IDS = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)

_CLAIM_BOUNDARY = (
    "dft_hardware_closure_parser_run.json records parser attempts and parsed "
    "stage-result files produced from existing candidate-specific raw evidence. "
    "Parser output is readiness evidence only; it cannot pass hard gates, certify "
    "numerical correctness, Vivado FPGA implementation, DC ASIC timing/area, "
    "trusted Pareto, or deliverable completion without separate adjudication."
)

_PASS_MARKERS = ("PASS", "PASSED", "SUCCESS", "MET")
_FAIL_MARKERS = ("FAIL", "FAILED", "ERROR", "VIOLATED", "FATAL")


def _load_json(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


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


def _relative_to_root(path: Path, root: Path) -> str | None:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return None


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [ch if ch.isalnum() or ch in "._-" else "_" for ch in text]
    return "".join(chars).strip("_") or "unknown"


def _parsed_result_path(unit: Mapping[str, Any], stage_id: str) -> str:
    return (
        "parsed_hard_gate_results/"
        f"{_safe_slug(unit.get('candidate_id'))}/"
        f"{_safe_slug(unit.get('kernel_id'))}/"
        f"{_safe_slug(stage_id)}_parsed_result.json"
    )


def _stage_files(unit: Mapping[str, Any], stage_id: str) -> list[Mapping[str, Any]]:
    files: list[Mapping[str, Any]] = []
    for item in unit.get("expected_evidence_files", []) or []:
        if isinstance(item, Mapping) and item.get("stage_id") == stage_id and item.get("required", True):
            files.append(item)
    return files


def _global_provenance_files(unit: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    files: list[Mapping[str, Any]] = []
    for item in unit.get("expected_evidence_files", []) or []:
        if isinstance(item, Mapping) and item.get("stage_id") == "all" and item.get("required", True):
            files.append(item)
    return files


def _present_paths(evidence_root: Path, files: Iterable[Mapping[str, Any]]) -> tuple[list[Path], list[str], list[str]]:
    present: list[Path] = []
    missing: list[str] = []
    invalid: list[str] = []
    for item in files:
        rel = str(item.get("path", ""))
        if item.get("path_valid") is False:
            invalid.append(rel)
            continue
        path, error = _safe_child_path(evidence_root, rel)
        if error:
            invalid.append(rel)
            continue
        if path is not None and path.exists() and path.is_file():
            present.append(path)
        else:
            missing.append(rel)
    return present, missing, invalid


def _missing_raw_blocker_details(
    *,
    stage_id: str,
    missing_files: Iterable[str],
    present_paths: Iterable[Path],
) -> list[Dict[str, Any]]:
    present_names = sorted(path.name for path in present_paths)
    details: list[Dict[str, Any]] = []
    for rel in missing_files:
        file_name = Path(rel).name
        if stage_id == "dc_asic_synth_timing_area" and file_name == "dc_synth.ddc":
            blocker_id = "missing_dc_synth_ddc_design_database"
            message = (
                "Packet requires a real Design Compiler .ddc design database "
                "for the ASIC claim gate; DC logs, mapped Verilog, and "
                "timing/area reports are not substitutes."
            )
        elif stage_id == "dc_asic_synth_timing_area":
            blocker_id = "missing_dc_asic_raw_stage_file"
            message = "Packet-required DC ASIC raw-stage evidence file is missing."
        else:
            blocker_id = f"missing_{stage_id}_raw_stage_file"
            message = "Packet-required raw-stage evidence file is missing."
        details.append(
            {
                "stage_id": stage_id,
                "path": rel,
                "file_name": file_name,
                "blocker_id": blocker_id,
                "message": message,
                "present_raw_file_names": present_names,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return details


def _provenance_blockers(
    *,
    evidence_root: Path,
    unit: Mapping[str, Any],
    stage_id: str,
    stage_raw_paths: Iterable[Path],
    global_paths: Iterable[Path],
) -> list[str]:
    """Return blockers that prevent shared smoke evidence from becoming candidate-specific closure."""

    candidate_id = str(unit.get("candidate_id", ""))
    kernel_id = str(unit.get("kernel_id", ""))
    paths_by_name = {path.name: path for path in global_paths}
    source_manifest_path = paths_by_name.get("source_bundle_manifest.json")
    for path in global_paths:
        if path.name == "source_bundle_manifest.json":
            source_manifest_path = path
            break
    if source_manifest_path is None:
        return ["missing_source_bundle_manifest"]
    manifest = _load_json(source_manifest_path)
    blockers: list[str] = []
    if str(manifest.get("candidate_id", "")) != candidate_id:
        blockers.append("source_bundle_candidate_id_mismatch")
    if str(manifest.get("kernel_id", "")) != kernel_id:
        blockers.append("source_bundle_kernel_id_mismatch")
    if manifest.get("candidate_specific_closure") is not True:
        blockers.append("source_bundle_not_candidate_specific_closure")
    if manifest.get("shared_microkernel_smoke_only") is True:
        blockers.append("source_bundle_is_shared_microkernel_smoke_only")
    if str(manifest.get("raw_evidence_scope", "")) not in {
        "candidate_specific_closure",
        "candidate_specific_unit",
    }:
        blockers.append("source_bundle_raw_evidence_scope_not_candidate_specific")
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if manifest.get(field) is True:
            blockers.append(f"source_bundle_invalid_{field}_claim")
    if _relative_to_root(source_manifest_path, evidence_root) is None:
        blockers.append("source_bundle_manifest_outside_evidence_root")
    for file_name in ("tool_versions.json", "command_manifest.json", "raw_transcript_index.json"):
        path = paths_by_name.get(file_name)
        if path is None:
            blockers.append(f"missing_{file_name.replace('.', '_')}")
            continue
        payload = _load_json(path)
        if str(payload.get("candidate_id", "")) != candidate_id:
            blockers.append(f"{file_name}_candidate_id_mismatch")
        if str(payload.get("kernel_id", "")) != kernel_id:
            blockers.append(f"{file_name}_kernel_id_mismatch")
        if payload.get("shared_microkernel_smoke_only") is True:
            blockers.append(f"{file_name}_is_shared_microkernel_smoke_only")
        if payload.get("hardware_completion_eligible") is True or payload.get("deliverable_complete") is True:
            blockers.append(f"{file_name}_invalid_completion_claim")
    raw_paths = list(stage_raw_paths)
    if raw_paths:
        transcript_path = paths_by_name.get("raw_transcript_index.json")
        transcript = _load_json(transcript_path) if transcript_path else {}
        refs = transcript.get("raw_transcript_refs", [])
        refs = refs if isinstance(refs, list) else []
        ref_map = {
            str(ref.get("path", "")): ref
            for ref in refs
            if isinstance(ref, Mapping) and str(ref.get("stage_id", "")) == stage_id
        }
        for raw_path in raw_paths:
            rel = _relative_to_root(raw_path, evidence_root)
            if rel is None:
                blockers.append("raw_stage_file_outside_evidence_root")
                continue
            ref = ref_map.get(rel)
            if not isinstance(ref, Mapping):
                blockers.append("raw_stage_file_missing_from_raw_transcript_index")
                continue
            if str(ref.get("candidate_id", "")) != candidate_id or str(ref.get("kernel_id", "")) != kernel_id:
                blockers.append("raw_transcript_ref_candidate_or_kernel_mismatch")
            if ref.get("candidate_specific") is not True or ref.get("shared_microkernel_smoke_only") is True:
                blockers.append("raw_transcript_ref_not_candidate_specific")
            expected_hash = ref.get("sha256")
            if not expected_hash:
                blockers.append("raw_transcript_ref_missing_hash")
            elif expected_hash != sha256_file(raw_path):
                blockers.append("raw_transcript_ref_hash_mismatch")
            if str(ref.get("hash_algorithm", "sha256")) != "sha256":
                blockers.append("raw_transcript_ref_hash_algorithm_not_sha256")
    return blockers


def _raw_refs(evidence_root: Path, paths: Iterable[Path]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    for path in paths:
        rel = _relative_to_root(path, evidence_root) or str(path)
        refs.append({"path": rel, "sha256": sha256_file(path), "hash_algorithm": "sha256"})
    return refs


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json_vote(payloads: Iterable[Mapping[str, Any]]) -> str | None:
    saw_pass = False
    for payload in payloads:
        if not payload:
            continue
        if payload.get("passed") is True or str(payload.get("verdict", payload.get("status", ""))).lower() in {"pass", "passed", "success", "met"}:
            saw_pass = True
        if payload.get("passed") is False or str(payload.get("verdict", payload.get("status", ""))).lower() in {"fail", "failed", "error", "violated"}:
            return "failed"
    if saw_pass:
        return "passed"
    return None


def _text_vote(paths: Iterable[Path]) -> str | None:
    combined = "\n".join(_text(path).upper() for path in paths)
    if any(re.search(rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])", combined) for marker in _FAIL_MARKERS):
        return "failed"
    if any(re.search(rf"(?<![A-Z0-9_]){re.escape(marker)}(?![A-Z0-9_])", combined) for marker in _PASS_MARKERS):
        return "passed"
    return None


def _combined_vote(paths: Iterable[Path], payloads: Iterable[Mapping[str, Any]]) -> str | None:
    json_vote = _json_vote(payloads)
    text_vote = _text_vote(paths)
    if json_vote == "failed" or text_vote == "failed":
        return "failed"
    if json_vote == "passed" or text_vote == "passed":
        return "passed"
    return None


def _first_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _dc_blocker_ids(text: str) -> list[str]:
    upper = text.upper()
    blockers: list[str] = []
    if "COULD NOT READ THE FOLLOWING TARGET LIBRARIES" in upper:
        blockers.append("dc_target_library_unavailable")
    if "CAN'T READ LINK_LIBRARY FILE" in upper:
        blockers.append("dc_link_library_unavailable")
    real_target_library_present = bool(re.search(r"\bFSA0A_C_GENERIC_CORE_[A-Z0-9_]*\b", upper))
    if re.search(r"\bGTECH\b", upper) and not real_target_library_present:
        blockers.append("dc_uses_gtech_library_only")
    if "UNMAPPED LOGIC" in upper:
        blockers.append("dc_unmapped_logic")
    if "PATH IS UNCONSTRAINED" in upper:
        blockers.append("dc_unconstrained_timing")
    if re.search(r"\bTOTAL\s+CELL\s+AREA\s*[:=]?\s*0+(?:\.0+)?\b", upper):
        blockers.append("dc_area_not_physical")
    # Preserve order while deduplicating overlapping report/log markers.
    return list(dict.fromkeys(blockers))


def _dc_target_libraries(text: str) -> list[str]:
    patterns = [
        r"\bLibrary:\s*(fsa0a_c_generic_core_[A-Za-z0-9_]+)\b",
        r"^\s*(fsa0a_c_generic_core_[A-Za-z0-9_]+)\s+\(File:",
        r"Loading link library '?(fsa0a_c_generic_core_[A-Za-z0-9_]+)'?",
    ]
    libraries: list[str] = []
    for pattern in patterns:
        libraries.extend(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    return sorted(set(libraries), key=str.lower)


def _parse_stage(stage_id: str, paths: list[Path]) -> tuple[str, Dict[str, Any], str, list[str]]:
    payloads = [_load_json(path) for path in paths if path.suffix.lower() == ".json"]
    metrics: Dict[str, Any] = {}
    vote = _combined_vote(paths, payloads)
    parser_id = f"dft_{stage_id}_parser_v1"
    if stage_id == "golden_correctness":
        for payload in payloads:
            for key in ("max_abs_error", "max_rel_error", "rms_error"):
                if key in payload:
                    metrics[key] = payload[key]
        return vote or "inconclusive", metrics, parser_id, []
    if stage_id == "hls_or_rtl_sim":
        return vote or "inconclusive", metrics, parser_id, []
    if stage_id == "hls_or_rtl_synth":
        for payload in payloads:
            for key in ("lut", "ff", "bram", "dsp", "latency_cycles"):
                if key in payload:
                    metrics[key] = payload[key]
        return vote or "inconclusive", metrics, parser_id, []
    if stage_id == "vivado_fpga_synth_or_impl":
        text = "\n".join(_text(path) for path in paths)
        wns = _first_float(r"\bWNS\s*[:=]?\s*(-?\d+(?:\.\d+)?)", text)
        if wns is not None:
            metrics["wns_ns"] = wns
        route_payloads = [
            payload
            for payload in payloads
            if payload.get("stage_id") == "vivado_fpga_synth_or_impl"
            or "implementation_route_completed" in payload
        ]
        route_completed_by_payload = any(
            payload.get("implementation_route_completed") is True
            for payload in route_payloads
        )
        status_text = text.upper()
        route_completed_by_log = "ROUTE_DESIGN COMPLETE" in status_text
        timing_met_by_log = "TIMING MET" in status_text
        route_completed = route_completed_by_payload or route_completed_by_log
        metrics["implementation_route_completed"] = route_completed
        metrics["implementation_route_completed_source"] = (
            "vivado_route_status_json"
            if route_completed_by_payload
            else "vivado_log_marker"
            if route_completed_by_log
            else "not_observed"
        )
        if not route_payloads and not route_completed_by_log:
            return "blocked", metrics, parser_id, ["vivado_route_status_missing"]
        if not route_completed:
            return "blocked", metrics, parser_id, ["vivado_implementation_route_not_completed"]
        if route_completed or timing_met_by_log:
            vote = vote or "passed"
        if wns is not None and wns < 0:
            vote = "failed"
        return vote or "inconclusive", metrics, parser_id, []
    if stage_id == "dc_asic_synth_timing_area":
        text_paths = [path for path in paths if path.suffix.lower() != ".ddc"]
        text = "\n".join(_text(path) for path in text_paths)
        vote = _combined_vote(text_paths, payloads)
        blocker_ids = _dc_blocker_ids(text)
        target_libraries = _dc_target_libraries(text)
        slack = _first_float(r"\bslack\s*\(?\w*\)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", text)
        area = _first_float(r"\b(?:total\s+cell\s+area|area)\s*[:=]?\s*(\d+(?:\.\d+)?)", text)
        if target_libraries:
            metrics["dc_target_libraries"] = target_libraries
            metrics["dc_target_library_discovery"] = "real_target_library_present"
        else:
            metrics["dc_target_library_discovery"] = "not_observed"
        if slack is not None:
            metrics["slack_ns"] = slack
        if area is not None:
            metrics["area"] = area
        if blocker_ids:
            metrics["dc_blocker_ids"] = blocker_ids
            return "blocked", metrics, parser_id, blocker_ids
        if slack is not None:
            vote = "passed" if slack >= 0 else "failed"
        return vote or "inconclusive", metrics, parser_id, []
    return "inconclusive", metrics, parser_id, []


def _write_parsed_result(
    *,
    parsed_root: Path,
    evidence_root: Path,
    unit: Mapping[str, Any],
    stage_id: str,
    raw_paths: list[Path],
) -> Dict[str, Any]:
    verdict, metrics, parser_id, blocker_ids = _parse_stage(stage_id, raw_paths)
    rel = _parsed_result_path(unit, stage_id)
    path = parsed_root / rel
    payload = {
        "schema_version": DFT_HARDWARE_PARSED_STAGE_RESULT_SCHEMA,
        "candidate_id": str(unit.get("candidate_id", "")),
        "kernel_id": str(unit.get("kernel_id", "")),
        "stage_id": stage_id,
        "verdict": verdict,
        "parser_id": parser_id,
        "blocker_ids": blocker_ids,
        "raw_evidence_refs": _raw_refs(evidence_root, raw_paths),
        "metrics": metrics,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(path, payload)
    return {
        "path": rel,
        "sha256": sha256_file(path),
        "hash_algorithm": "sha256",
        "verdict": verdict,
        "parser_id": parser_id,
        "blocker_ids": blocker_ids,
    }


def _parser_row(*, evidence_root: Path, parsed_root: Path, packet: Mapping[str, Any], unit: Mapping[str, Any], stage_id: str) -> Dict[str, Any]:
    stage_files = _stage_files(unit, stage_id)
    present_paths, missing_files, invalid_files = _present_paths(evidence_root, stage_files)
    global_paths, missing_global_files, invalid_global_files = _present_paths(evidence_root, _global_provenance_files(unit))
    raw_stage_blocker_details = _missing_raw_blocker_details(
        stage_id=stage_id,
        missing_files=missing_files,
        present_paths=present_paths,
    )
    provenance_blockers = (
        _provenance_blockers(
            evidence_root=evidence_root,
            unit=unit,
            stage_id=stage_id,
            stage_raw_paths=present_paths,
            global_paths=global_paths,
        )
        if not missing_global_files
        else []
    )
    bundle = unit.get("candidate_bundle", {}) if isinstance(unit.get("candidate_bundle", {}), Mapping) else {}
    bundle_present = bool(bundle.get("exists", False))
    if not bundle_present:
        status = "blocked_missing_candidate_bundle"
        parsed_ref = None
    elif invalid_files or invalid_global_files:
        status = "blocked_invalid_evidence_path"
        parsed_ref = None
    elif missing_global_files:
        status = "blocked_missing_candidate_specific_provenance"
        parsed_ref = None
    elif provenance_blockers:
        status = "blocked_invalid_candidate_specific_provenance"
        parsed_ref = None
    elif missing_files:
        status = "blocked_missing_raw_stage_evidence"
        parsed_ref = None
    else:
        parsed_ref = _write_parsed_result(
            parsed_root=parsed_root,
            evidence_root=evidence_root,
            unit=unit,
            stage_id=stage_id,
            raw_paths=present_paths,
        )
        status = "parsed_result_written_pending_adjudication"
    parsed_blocker_ids = (
        list(parsed_ref.get("blocker_ids", []) or [])
        if isinstance(parsed_ref, Mapping)
        else []
    )
    stage_blocker_ids = sorted(
        {
            *(str(item.get("blocker_id")) for item in raw_stage_blocker_details if item.get("blocker_id")),
            *(str(item) for item in provenance_blockers),
            *(str(item) for item in parsed_blocker_ids),
        }
    )
    return {
        "packet_id": packet.get("packet_id"),
        "shard_id": packet.get("shard_id"),
        "unit_id": unit.get("unit_id"),
        "candidate_id": unit.get("candidate_id"),
        "kernel_id": unit.get("kernel_id"),
        "stage_id": stage_id,
        "candidate_bundle_present": bundle_present,
        "required_raw_file_count": len(stage_files),
        "present_raw_file_count": len(present_paths),
        "missing_raw_file_count": len(missing_files),
        "missing_raw_files": missing_files,
        "raw_stage_blocker_details": raw_stage_blocker_details,
        "invalid_raw_file_count": len(invalid_files),
        "invalid_raw_files": invalid_files,
        "required_global_provenance_file_count": len(_global_provenance_files(unit)),
        "present_global_provenance_file_count": len(global_paths),
        "missing_global_provenance_file_count": len(missing_global_files),
        "missing_global_provenance_files": missing_global_files,
        "invalid_global_provenance_file_count": len(invalid_global_files),
        "invalid_global_provenance_files": invalid_global_files,
        "candidate_specific_provenance_blockers": provenance_blockers,
        "parsed_blocker_ids": parsed_blocker_ids,
        "stage_blocker_ids": stage_blocker_ids,
        "parsed_result": parsed_ref,
        "status": status,
        "adjudication_result": "not_adjudicated_by_parser_run",
        "passed": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_hardware_closure_parser_run(
    *,
    closure_evidence_intake_path: Path,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
) -> Dict[str, Any]:
    """Run parsers for raw evidence that already exists and return the report."""

    intake_path = Path(closure_evidence_intake_path)
    intake = _load_json(intake_path)
    evidence_root = Path(evidence_root or intake.get("evidence_root") or intake_path.parent)
    parsed_root = Path(parsed_root or evidence_root)
    rows: list[Dict[str, Any]] = []
    for packet in intake.get("packets", []) or []:
        if not isinstance(packet, Mapping):
            continue
        for unit in packet.get("unit_rows", []) or []:
            if not isinstance(unit, Mapping):
                continue
            rows.extend(_parser_row(evidence_root=evidence_root, parsed_root=parsed_root, packet=packet, unit=unit, stage_id=stage_id) for stage_id in _STAGE_IDS)
    written = [row for row in rows if row.get("parsed_result")]
    blocked = [row for row in rows if str(row.get("status", "")).startswith("blocked")]
    verdict_counts: Dict[str, int] = {"passed": 0, "failed": 0, "inconclusive": 0, "blocked": len(blocked)}
    for row in written:
        verdict = (row.get("parsed_result") or {}).get("verdict")
        if verdict in verdict_counts:
            verdict_counts[str(verdict)] += 1
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA,
        "status": "blocked_missing_raw_evidence" if blocked else "parsed_results_written_pending_adjudication" if rows else "failed_empty_intake",
        "source_artifacts": {"closure_evidence_intake": _source_ref(intake_path)},
        "evidence_root": str(evidence_root),
        "parsed_root": str(parsed_root),
        "release_id": intake.get("release_id"),
        "candidate_count": intake.get("candidate_count"),
        "major_kernel_count": intake.get("major_kernel_count"),
        "packet_count": intake.get("packet_count"),
        "unit_count": intake.get("unit_count"),
        "stage_count": len(rows),
        "parsed_result_written_count": len(written),
        "blocked_stage_count": len(blocked),
        "verdict_counts": verdict_counts,
        "adjudication_result": "not_adjudicated_by_parser_run",
        "passed_stage_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "parser_rows": rows,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_parser_run(payload_or_path: Mapping[str, Any] | Path) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
    else:
        payload = dict(payload_or_path)
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected parser-run schema"})
    rows = payload.get("parser_rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "parser_rows", "message": "non-empty parser rows required"})
        rows = []
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "parser run cannot upgrade claims"})
    if payload.get("adjudication_result") != "not_adjudicated_by_parser_run":
        errors.append({"field": "adjudication_result", "message": "parser run must not adjudicate"})
    if int(payload.get("passed_stage_count", 0) or 0) != 0:
        errors.append({"field": "passed_stage_count", "message": "parser run cannot pass stages"})
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"parser_rows[{index}]", "message": "parser row must be an object"})
            continue
        key = (str(row.get("candidate_id", "")), str(row.get("kernel_id", "")), str(row.get("stage_id", "")))
        if key in seen:
            errors.append({"field": f"parser_rows[{index}]", "message": "duplicate parser row"})
        seen.add(key)
        for field in ("passed", "hardware_completion_eligible", "deliverable_complete"):
            if row.get(field) is True:
                errors.append({"field": f"parser_rows[{index}].{field}", "message": "parser row cannot upgrade claims"})
        if row.get("adjudication_result") != "not_adjudicated_by_parser_run":
            errors.append({"field": f"parser_rows[{index}].adjudication_result", "message": "parser row must not adjudicate"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PARSER_RUN_VALIDATION_SCHEMA,
        "valid": not errors,
        "parser_row_count": len(rows),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_parser_run(
    out_dir: Path,
    *,
    closure_evidence_intake_path: Path,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_closure_parser_run(
        closure_evidence_intake_path=closure_evidence_intake_path,
        evidence_root=evidence_root,
        parsed_root=parsed_root,
    )
    write_json(out_dir / "dft_hardware_closure_parser_run.json", payload)
    validation = validate_dft_hardware_closure_parser_run(payload)
    write_json(out_dir / "dft_hardware_closure_parser_run_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_parser_run_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "parser_run": "dft_hardware_closure_parser_run.json",
        "validation": "dft_hardware_closure_parser_run_validation.json",
        "stage_count": payload["stage_count"],
        "parsed_result_written_count": payload["parsed_result_written_count"],
        "blocked_stage_count": payload["blocked_stage_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_parser_run_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_PARSER_RUN_SCHEMA",
    "DFT_HARDWARE_CLOSURE_PARSER_RUN_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_parser_run",
    "validate_dft_hardware_closure_parser_run",
    "write_dft_hardware_closure_parser_run",
]
