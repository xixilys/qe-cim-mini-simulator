#!/usr/bin/env python3
"""Fail-closed PPA ranking for DFT/QE hardware closure runs.

This module consumes the current Step5 DFT hardware closure artifacts and emits
hardware-specific ranking artifacts.  The ranking is deliberately narrower than
generic Step4/Step5 trusted workload ranking: it compares only candidates whose
major-kernel golden/sim/synth/Vivado/DC gates have already passed, and it keeps
the full-SCF deliverable-completion claim separate.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS
from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_HARDWARE_PPA_RANKING_SCHEMA = "dse.dft.hardware_ppa_ranking.v1"
DFT_HARDWARE_PPA_PARETO_SCHEMA = "dse.dft.hardware_ppa_pareto_frontier.v1"
DFT_HARDWARE_PPA_RANKING_VALIDATION_SCHEMA = "dse.dft.hardware_ppa_ranking_validation.v1"
DFT_HARDWARE_PPA_RANKING_STATUS_SCHEMA = "dse.dft.hardware_ppa_ranking_status.v1"

REQUIRED_STAGE_IDS: tuple[str, ...] = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)

_CLAIM_BOUNDARY = (
    "DFT hardware PPA ranking compares only candidate-stamped major-kernel "
    "closure evidence after golden/sim/synth/Vivado/DC gates pass. It is not a "
    "full-SCF deliverable-completion claim and must not be used to select a "
    "single trusted end-to-end architecture unless separate system-level tie "
    "breakers and the release claim gate also close."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_run_local_path(run_dir: Path, path_text: Any) -> Path:
    path = Path(str(path_text or ""))
    if path.is_absolute():
        return path
    return run_dir / path


def _raw_ref_paths(run_dir: Path, parsed_result: Mapping[str, Any], name: str) -> list[Path]:
    paths: list[Path] = []
    for ref in parsed_result.get("raw_evidence_refs", []) or []:
        if not isinstance(ref, Mapping):
            continue
        ref_path = str(ref.get("path", ""))
        if Path(ref_path).name == name:
            paths.append(_resolve_run_local_path(run_dir, ref_path))
    return paths


def _extract_vivado_table_used(text: str, site_type: str) -> int | None:
    # Vivado utilization rows look like:
    # | Slice LUTs*             | 1236 |     0 |     20800 |  5.94 |
    pattern = re.compile(rf"^\|\s*{re.escape(site_type)}\*?\s*\|\s*([0-9]+)\s*\|", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    return int(match.group(1))


def _extract_vivado_table_percent(text: str, site_type: str) -> float | None:
    pattern = re.compile(
        rf"^\|\s*{re.escape(site_type)}\*?\s*\|\s*[0-9]+\s*\|\s*[0-9]+\s*\|\s*[0-9]+\s*\|\s*([0-9.]+)\s*\|",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return _as_float(match.group(1))


def _extract_vivado_wns(text: str) -> float | None:
    # The first numeric row after the Design Timing Summary header is enough
    # for these generated reports.  "NA" remains unranked rather than invented.
    match = re.search(
        r"Design Timing Summary.*?\n\s*-+\s+.*?\n\s*([0-9.+-]+|NA)\s+",
        text,
        flags=re.DOTALL,
    )
    if not match or match.group(1) == "NA":
        return None
    return _as_float(match.group(1))


def _vivado_metrics(run_dir: Path, parsed_result: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = dict(parsed_result.get("metrics", {}) if isinstance(parsed_result.get("metrics"), Mapping) else {})
    utilization_paths = _raw_ref_paths(run_dir, parsed_result, "vivado_utilization.rpt")
    timing_paths = _raw_ref_paths(run_dir, parsed_result, "vivado_timing_summary.rpt")
    utilization_text = _read_text(utilization_paths[0]) if utilization_paths else ""
    timing_text = _read_text(timing_paths[0]) if timing_paths else ""
    lut = _extract_vivado_table_used(utilization_text, "Slice LUTs")
    registers = _extract_vivado_table_used(utilization_text, "Slice Registers")
    bram = _extract_vivado_table_used(utilization_text, "Block RAM Tile")
    dsp = _extract_vivado_table_used(utilization_text, "DSPs")
    iob = _extract_vivado_table_used(utilization_text, "Bonded IOB")
    util_percents = [
        value
        for value in (
            _extract_vivado_table_percent(utilization_text, "Slice LUTs"),
            _extract_vivado_table_percent(utilization_text, "Slice Registers"),
            _extract_vivado_table_percent(utilization_text, "Block RAM Tile"),
            _extract_vivado_table_percent(utilization_text, "DSPs"),
            _extract_vivado_table_percent(utilization_text, "Bonded IOB"),
        )
        if value is not None
    ]
    metrics.update(
        {
            "slice_luts": lut,
            "slice_registers": registers,
            "block_ram_tiles": bram,
            "dsps": dsp,
            "bonded_iob": iob,
            "max_util_percent": max(util_percents) if util_percents else None,
            "wns_ns": _extract_vivado_wns(timing_text),
            "utilization_report": str(utilization_paths[0]) if utilization_paths else None,
            "timing_report": str(timing_paths[0]) if timing_paths else None,
        }
    )
    return metrics


def _discover_candidate_universe_manifest(run_dir: Path, explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return Path(explicit)
    for candidate in (
        run_dir / "release_domain_current36" / "candidate_universe_manifest.json",
        run_dir / "release_domain" / "candidate_universe_manifest.json",
        run_dir / "candidate_universe_manifest.json",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _candidate_universe_by_id(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    payload = _load_json(path)
    rows = payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
    return {
        str(row.get("candidate_id")): dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("candidate_id")
    }


def _candidate_metadata_sidecar(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """Return audit-only candidate metadata that must not affect PPA ordering."""

    return {
        key: metadata.get(key)
        for key in (
            "candidate_id",
            "legacy_candidate_id",
            "design_candidate_id",
            "candidate_id_kind",
            "candidate_id_authoritative_for_design",
            "design_candidate_id_authoritative_for_design",
            "domain_hash",
            "evaluation_record_id",
            "assignments",
            "identity_assignments",
            "non_identity_assignments",
            "applicability_assignments",
            "evaluation_policy_assignments",
            "design_score",
            "design_legality",
            "screening",
            "promotion_requirements",
            "provenance",
        )
        if key in metadata
    }


def _candidate_parametric_ppa(
    *,
    candidate_id: str,
    totals: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return candidate assignment context as sidecar-only audit data.

    This intentionally does not compute alternative PPA totals.  Physical PPA
    ranking is based only on parsed Vivado/DC metrics; true candidate-parametric
    ranking requires generated RTL/tool evidence whose source or parameter
    hashes differ by candidate.
    """

    assignments = metadata.get("assignments")
    if not isinstance(assignments, Mapping):
        assignments = metadata.get("identity_assignments")
    if not isinstance(assignments, Mapping):
        assignments = {}
    return {
        "available": bool(assignments),
        "basis": "candidate_assignment_sidecar_only_not_physical_ppa",
        "candidate_id": candidate_id,
        "candidate_id_used_as_factor": False,
        "ranking_input": False,
        "winner_input": False,
        "assignments_used": dict(assignments),
        "raw_totals_remain_authoritative": True,
        "raw_totals": {
            key: totals.get(key)
            for key in (
                "fpga_total_slice_luts",
                "fpga_total_slice_registers",
                "fpga_total_block_ram_tiles",
                "fpga_total_dsps",
                "fpga_total_bonded_iob",
                "asic_total_cell_area",
                "asic_min_slack_ns",
                "asic_slack_deficit_ns",
            )
        },
        "attributed_totals": {},
        "audit_note": (
            "Sidecar metadata preserves design context only; it must not break ties "
            "in parsed Vivado/DC physical PPA metrics."
        ),
    }


def _source_bundle_signature(run_dir: Path, candidate_id: str, kernel_id: str) -> Dict[str, Any]:
    path = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / "source_bundle_manifest.json"
    payload = _load_json(path)
    refs = payload.get("source_refs", []) if isinstance(payload.get("source_refs"), list) else []
    rtl_refs = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        ref_path = str(ref.get("path", ""))
        if Path(ref_path).suffix != ".v":
            continue
        rtl_refs.append(
            {
                "path": ref_path,
                "name": Path(ref_path).name,
                "sha256": ref.get("sha256"),
                "exists": ref.get("exists"),
            }
        )
    param_hash = None
    for key in (
        "candidate_param_hash",
        "candidate_parameter_hash",
        "generated_rtl_param_hash",
        "candidate_parametric_source_hash",
    ):
        if payload.get(key):
            param_hash = str(payload.get(key))
            break
    return {
        "manifest": _source_ref(path),
        "rtl_source_refs": sorted(rtl_refs, key=lambda item: (str(item.get("name")), str(item.get("path")))),
        "rtl_source_signature": json.dumps(
            sorted(
                [{"name": item.get("name"), "sha256": item.get("sha256")} for item in rtl_refs],
                key=lambda item: str(item.get("name")),
            ),
            sort_keys=True,
        )
        if rtl_refs
        else None,
        "candidate_parametric_source_hash": param_hash,
    }


def _apply_candidate_parametric_source_blockers(candidate_rows: list[Dict[str, Any]]) -> None:
    """Fail closed when fresh source bundles prove static RTL across candidates.

    Candidate-universe assignments are useful audit context, but they are not
    physical evidence. If fresh source manifests show all currently eligible
    candidates used the same RTL source for a kernel and no explicit generated
    RTL parameter hash differentiates them, physical PPA attribution is not
    candidate-parametric enough to rank a trusted winner.
    """

    eligible_rows = [row for row in candidate_rows if row.get("ranking_eligible")]
    if len(eligible_rows) < 2:
        return
    kernel_ids = sorted(
        {
            str(kernel.get("kernel_id"))
            for row in eligible_rows
            for kernel in row.get("kernel_rows", []) or []
            if isinstance(kernel, Mapping) and kernel.get("kernel_id")
        }
    )
    for kernel_id in kernel_ids:
        rows_with_sources: list[tuple[Dict[str, Any], Mapping[str, Any]]] = []
        for row in eligible_rows:
            kernel = next(
                (
                    item
                    for item in row.get("kernel_rows", []) or []
                    if isinstance(item, Mapping) and str(item.get("kernel_id")) == kernel_id
                ),
                None,
            )
            if not isinstance(kernel, Mapping):
                continue
            source_bundle = kernel.get("candidate_source_bundle", {})
            if (
                isinstance(source_bundle, Mapping)
                and source_bundle.get("manifest", {}).get("exists") is True
                and source_bundle.get("rtl_source_signature")
            ):
                rows_with_sources.append((row, source_bundle))
        if len(rows_with_sources) < 2:
            continue
        signatures = {str(source.get("rtl_source_signature")) for _, source in rows_with_sources}
        param_hashes = {
            str(source.get("candidate_parametric_source_hash"))
            for _, source in rows_with_sources
            if source.get("candidate_parametric_source_hash")
        }
        if len(signatures) == 1 and len(param_hashes) <= 1:
            for row, source in rows_with_sources:
                row.setdefault("blockers", []).append(
                    {
                        "candidate_id": row.get("candidate_id"),
                        "kernel_id": kernel_id,
                        "stage_id": "candidate_parametric_source",
                        "blocker_id": "candidate_parametric_source_not_distinguished",
                        "source_bundle_manifest": source.get("manifest", {}).get("path"),
                    }
                )
                row["ranking_eligible"] = False


def _parsed_result(run_dir: Path, candidate_id: str, kernel_id: str, stage_id: str) -> Dict[str, Any]:
    return _load_json(
        run_dir
        / "parsed_hard_gate_results"
        / candidate_id
        / kernel_id
        / f"{stage_id}_parsed_result.json"
    )


def _passed_candidate_ids(release_gate: Mapping[str, Any]) -> list[str]:
    candidate_rows = release_gate.get("candidate_rows", [])
    if not isinstance(candidate_rows, list):
        return []
    return sorted(
        str(row.get("candidate_id"))
        for row in candidate_rows
        if isinstance(row, Mapping)
        and row.get("candidate_id")
        and row.get("candidate_hardware_gate_passed") is True
        and row.get("candidate_claim_eligible", True) is True
    )


def _kernel_ids(release_gate: Mapping[str, Any]) -> list[str]:
    expected = release_gate.get("expected_kernel_ids")
    if isinstance(expected, list) and expected:
        return sorted(str(item) for item in expected if item)
    return sorted(MAJOR_SCF_KERNEL_IDS)


def _gate_blocker(
    *,
    candidate_id: str,
    kernel_id: str,
    stage_id: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "kernel_id": kernel_id,
        "stage_id": stage_id,
        "blocker_id": reason,
    }


def _stage_summary(
    run_dir: Path,
    *,
    candidate_id: str,
    kernel_id: str,
) -> tuple[Dict[str, Dict[str, Any]], list[Dict[str, Any]]]:
    stages: Dict[str, Dict[str, Any]] = {}
    blockers: list[Dict[str, Any]] = []
    for stage_id in REQUIRED_STAGE_IDS:
        parsed = _parsed_result(run_dir, candidate_id, kernel_id, stage_id)
        if not parsed:
            blockers.append(
                _gate_blocker(
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    stage_id=stage_id,
                    reason="missing_parsed_stage_result",
                )
            )
            stages[stage_id] = {"present": False, "verdict": None}
            continue
        verdict = str(parsed.get("verdict", ""))
        if verdict != "passed":
            blockers.append(
                _gate_blocker(
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                    stage_id=stage_id,
                    reason="parsed_stage_not_passed",
                )
            )
        if stage_id == "vivado_fpga_synth_or_impl":
            metrics = _vivado_metrics(run_dir, parsed)
            if metrics.get("implementation_route_completed") is not True:
                blockers.append(
                    _gate_blocker(
                        candidate_id=candidate_id,
                        kernel_id=kernel_id,
                        stage_id=stage_id,
                        reason="vivado_route_not_completed",
                    )
                )
        elif stage_id == "dc_asic_synth_timing_area":
            metrics = dict(parsed.get("metrics", {}) if isinstance(parsed.get("metrics"), Mapping) else {})
            if metrics.get("dc_target_library_discovery") != "real_target_library_present":
                blockers.append(
                    _gate_blocker(
                        candidate_id=candidate_id,
                        kernel_id=kernel_id,
                        stage_id=stage_id,
                        reason="dc_real_target_library_missing",
                    )
                )
            if _as_float(metrics.get("area")) is None:
                blockers.append(
                    _gate_blocker(
                        candidate_id=candidate_id,
                        kernel_id=kernel_id,
                        stage_id=stage_id,
                        reason="dc_area_metric_missing",
                    )
                )
            if _as_float(metrics.get("slack_ns")) is None:
                blockers.append(
                    _gate_blocker(
                        candidate_id=candidate_id,
                        kernel_id=kernel_id,
                        stage_id=stage_id,
                        reason="dc_slack_metric_missing",
                    )
                )
        else:
            metrics = dict(parsed.get("metrics", {}) if isinstance(parsed.get("metrics"), Mapping) else {})
        stages[stage_id] = {
            "present": True,
            "verdict": verdict,
            "parser_id": parsed.get("parser_id"),
            "metrics": metrics,
            "raw_evidence_refs": parsed.get("raw_evidence_refs", []),
        }
    return stages, blockers


def _candidate_metric_signature(candidate: Mapping[str, Any]) -> str:
    rows = []
    for kernel in candidate.get("kernel_rows", []) or []:
        if not isinstance(kernel, Mapping):
            continue
        rows.append(
            {
                "kernel_id": kernel.get("kernel_id"),
                "dc_area": kernel.get("asic", {}).get("area"),
                "dc_slack": kernel.get("asic", {}).get("slack_ns"),
                "fpga_lut": kernel.get("fpga", {}).get("slice_luts"),
                "fpga_reg": kernel.get("fpga", {}).get("slice_registers"),
                "fpga_bram": kernel.get("fpga", {}).get("block_ram_tiles"),
                "fpga_dsp": kernel.get("fpga", {}).get("dsps"),
                "fpga_iob": kernel.get("fpga", {}).get("bonded_iob"),
                "route": kernel.get("fpga", {}).get("implementation_route_completed"),
            }
        )
    return json.dumps(sorted(rows, key=lambda item: str(item["kernel_id"])), sort_keys=True)


def _rank_with_ties(rows: Sequence[Dict[str, Any]], key: Any) -> list[Dict[str, Any]]:
    ranked: list[Dict[str, Any]] = []
    previous_key = None
    rank = 0
    sort_key = lambda item: (key(item), str(item.get("candidate_id")))
    for index, row in enumerate(sorted(rows, key=sort_key), start=1):
        current = key(row)
        if previous_key is None or current != previous_key:
            rank = index
            previous_key = current
        ranked.append({**row, "rank": rank, "tie_key": list(current) if isinstance(current, tuple) else current})
    return ranked


def _pareto_rows(rows: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
    objectives = (
        "fpga_total_slice_luts",
        "fpga_total_dsps",
        "fpga_total_block_ram_tiles",
        "asic_total_cell_area",
        "asic_slack_deficit_ns",
    )
    frontier: list[Dict[str, Any]] = []
    for row in rows:
        dominated = False
        for other in rows:
            if other is row:
                continue
            no_worse = all(float(other.get(obj, 0.0) or 0.0) <= float(row.get(obj, 0.0) or 0.0) for obj in objectives)
            strictly_better = any(float(other.get(obj, 0.0) or 0.0) < float(row.get(obj, 0.0) or 0.0) for obj in objectives)
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(dict(row))
    return sorted(frontier, key=lambda item: str(item.get("candidate_id")))


def _ranking_metric(row: Mapping[str, Any], raw_key: str, *, parametric_available: bool) -> float:
    # ``parametric_available`` is intentionally ignored for ranking.  Candidate
    # assignments are audit context until generated RTL/tool evidence varies by
    # candidate; using assignment heuristics here would silently turn a physical
    # Vivado/DC tie into an unsupported winner claim.
    return float(row.get(raw_key) or 0.0)


def build_dft_hardware_ppa_ranking(
    run_dir: Path,
    *,
    candidate_universe_manifest: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a fail-closed hardware PPA ranking payload."""

    run_dir = Path(run_dir)
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    release_validation_path = run_dir / "dft_hardware_closure_release_gate_validation.json"
    parser_run_path = run_dir / "dft_hardware_closure_parser_run.json"
    release_gate = _load_json(release_gate_path)
    release_validation = _load_json(release_validation_path)
    parser_run = _load_json(parser_run_path)
    resolved_candidate_universe_manifest = _discover_candidate_universe_manifest(
        run_dir,
        candidate_universe_manifest,
    )
    universe = _candidate_universe_by_id(resolved_candidate_universe_manifest)
    blockers: list[Dict[str, Any]] = []

    if not release_gate:
        blockers.append({"blocker_id": "missing_release_gate", "path": str(release_gate_path)})
    if release_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "release_gate_validation_not_valid",
                "validation_valid": release_validation.get("valid"),
            }
        )
    if release_gate.get("hardware_completion_eligible") is not True:
        blockers.append(
            {
                "blocker_id": "release_gate_not_hardware_completion_eligible",
                "release_gate_result": release_gate.get("release_gate_result"),
            }
        )

    candidate_ids = _passed_candidate_ids(release_gate)
    kernel_ids = _kernel_ids(release_gate)
    if candidate_ids and not universe:
        blockers.append(
            {
                "blocker_id": "missing_candidate_universe_metadata",
                "path": str(resolved_candidate_universe_manifest) if resolved_candidate_universe_manifest else None,
            }
        )
    candidate_rows: list[Dict[str, Any]] = []
    for candidate_id in candidate_ids:
        candidate_blockers: list[Dict[str, Any]] = []
        metadata = universe.get(candidate_id, {})
        if not metadata:
            candidate_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "stage_id": "candidate_universe_metadata",
                    "blocker_id": "missing_candidate_universe_metadata",
                }
            )
        kernel_rows: list[Dict[str, Any]] = []
        totals = {
            "fpga_total_slice_luts": 0,
            "fpga_total_slice_registers": 0,
            "fpga_total_block_ram_tiles": 0,
            "fpga_total_dsps": 0,
            "fpga_total_bonded_iob": 0,
            "asic_total_cell_area": 0.0,
            "asic_min_slack_ns": None,
            "vivado_route_completed_kernel_count": 0,
            "dc_real_target_library_kernel_count": 0,
        }
        for kernel_id in kernel_ids:
            stages, stage_blockers = _stage_summary(run_dir, candidate_id=candidate_id, kernel_id=kernel_id)
            candidate_blockers.extend(stage_blockers)
            fpga = dict(stages.get("vivado_fpga_synth_or_impl", {}).get("metrics", {}))
            asic = dict(stages.get("dc_asic_synth_timing_area", {}).get("metrics", {}))
            for key, total_key in (
                ("slice_luts", "fpga_total_slice_luts"),
                ("slice_registers", "fpga_total_slice_registers"),
                ("block_ram_tiles", "fpga_total_block_ram_tiles"),
                ("dsps", "fpga_total_dsps"),
                ("bonded_iob", "fpga_total_bonded_iob"),
            ):
                totals[total_key] += int(fpga.get(key) or 0)
            if fpga.get("implementation_route_completed") is True:
                totals["vivado_route_completed_kernel_count"] += 1
            area = _as_float(asic.get("area"))
            slack = _as_float(asic.get("slack_ns"))
            totals["asic_total_cell_area"] += area if area is not None else 0.0
            if slack is not None:
                previous = totals["asic_min_slack_ns"]
                totals["asic_min_slack_ns"] = slack if previous is None else min(float(previous), slack)
            if asic.get("dc_target_library_discovery") == "real_target_library_present":
                totals["dc_real_target_library_kernel_count"] += 1
            kernel_rows.append(
                {
                    "kernel_id": kernel_id,
                    "stage_verdicts": {
                        stage_id: stages.get(stage_id, {}).get("verdict")
                        for stage_id in REQUIRED_STAGE_IDS
                    },
                    "fpga": {
                        key: fpga.get(key)
                        for key in (
                            "implementation_route_completed",
                            "implementation_route_completed_source",
                            "slice_luts",
                            "slice_registers",
                            "block_ram_tiles",
                            "dsps",
                            "bonded_iob",
                            "max_util_percent",
                            "wns_ns",
                        )
                    },
                    "asic": {
                        key: asic.get(key)
                        for key in (
                            "dc_target_library_discovery",
                            "dc_target_libraries",
                            "slack_ns",
                            "area",
                        )
                    },
                    "evidence_ids": [
                        str(ref.get("path"))
                        for stage in stages.values()
                        for ref in stage.get("raw_evidence_refs", []) or []
                        if isinstance(ref, Mapping) and ref.get("path")
                    ],
                    "candidate_source_bundle": _source_bundle_signature(run_dir, candidate_id, kernel_id),
                }
            )
        asic_min_slack = totals["asic_min_slack_ns"]
        asic_slack_deficit = max(0.0, -float(asic_min_slack or 0.0))
        parametric_ppa = _candidate_parametric_ppa(
            candidate_id=candidate_id,
            totals={**totals, "asic_slack_deficit_ns": asic_slack_deficit},
            metadata=metadata,
        )
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "design_candidate_id": metadata.get("design_candidate_id"),
                "candidate_metadata": _candidate_metadata_sidecar(metadata),
                "assignments": metadata.get("assignments", {}),
                "identity_assignments": metadata.get("identity_assignments", {}),
                "non_identity_assignments": metadata.get("non_identity_assignments", {}),
                "applicability_assignments": metadata.get("applicability_assignments", {}),
                "evaluation_policy_assignments": metadata.get("evaluation_policy_assignments", {}),
                "design_score": metadata.get("design_score"),
                "candidate_metadata_sidecar": _candidate_metadata_sidecar(metadata),
                "candidate_parameter_signature": json.dumps(
                    {
                        "identity_assignments": metadata.get("identity_assignments", {}),
                        "assignments": metadata.get("assignments", {}),
                    },
                    sort_keys=True,
                ),
                "candidate_parametric_ppa": parametric_ppa,
                "candidate_gate_passed": not candidate_blockers,
                "ranking_eligible": not candidate_blockers,
                "blockers": candidate_blockers,
                "kernel_rows": kernel_rows,
                **totals,
                "asic_slack_deficit_ns": asic_slack_deficit,
                "kernel_count": len(kernel_ids),
                "required_stage_ids": list(REQUIRED_STAGE_IDS),
            }
        )

    _apply_candidate_parametric_source_blockers(candidate_rows)
    eligible_rows = [row for row in candidate_rows if row.get("ranking_eligible")]
    physical_metric_signatures = {_candidate_metric_signature(row) for row in eligible_rows}
    all_physical_metric_tied = bool(eligible_rows) and len(physical_metric_signatures) == 1
    parametric_sidecar_available = any(
        isinstance(row.get("candidate_parametric_ppa"), Mapping)
        and row["candidate_parametric_ppa"].get("available") is True
        for row in eligible_rows
    )
    parametric_available = False
    metric_signatures = set(physical_metric_signatures)
    all_metric_tied = bool(eligible_rows) and len(metric_signatures) == 1
    if not eligible_rows and not blockers:
        blockers.append({"blocker_id": "no_ranking_eligible_candidates"})

    fpga_ranking = _rank_with_ties(
        eligible_rows,
        key=lambda item: (
            _ranking_metric(item, "fpga_total_slice_luts", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_dsps", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_block_ram_tiles", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_bonded_iob", parametric_available=parametric_available),
        ),
    )
    asic_ranking = _rank_with_ties(
        eligible_rows,
        key=lambda item: (
            _ranking_metric(item, "asic_total_cell_area", parametric_available=parametric_available),
            -_ranking_metric(item, "asic_min_slack_ns", parametric_available=parametric_available),
        ),
    )
    pareto = _pareto_rows(eligible_rows)
    status = (
        "trusted_hardware_ppa_ranking_tied"
        if eligible_rows and all_metric_tied
        else "trusted_hardware_ppa_ranking_available"
        if eligible_rows and not blockers
        else "blocked_hardware_ppa_ranking"
    )
    winner_selection_status = (
        "tied_by_identical_kernel_ppa_no_single_winner"
        if eligible_rows and all_metric_tied
        else "ranked_candidates_available"
        if eligible_rows
        else "blocked_no_hardware_ppa_winner"
    )
    return {
        "schema_version": DFT_HARDWARE_PPA_RANKING_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": {
            "release_gate": _source_ref(release_gate_path),
            "release_gate_validation": _source_ref(release_validation_path),
            "parser_run": _source_ref(parser_run_path),
            "candidate_universe_manifest": _source_ref(resolved_candidate_universe_manifest)
            if resolved_candidate_universe_manifest
            else {"path": None, "exists": False, "sha256": None, "hash_algorithm": "sha256"},
        },
        "candidate_metadata_context_available": bool(universe),
        "release_id": release_gate.get("release_id"),
        "candidate_count": release_gate.get("candidate_count"),
        "major_kernel_count": release_gate.get("major_kernel_count"),
        "stage_gate_passed_count": release_gate.get("stage_gate_passed_count"),
        "unit_gate_passed_count": release_gate.get("unit_gate_passed_count"),
        "candidate_gate_passed_count": release_gate.get("candidate_gate_passed_count"),
        "hardware_completion_eligible": bool(release_gate.get("hardware_completion_eligible", False)),
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
        "ranking_policy": {
            "score_scope": "candidate-stamped major-kernel PPA only",
            "fpga_sort_order": [
                "min fpga_total_slice_luts",
                "min fpga_total_dsps",
                "min fpga_total_block_ram_tiles",
                "min fpga_total_bonded_iob",
                "shared rank for equal physical metrics; listing order is not winner evidence",
            ],
            "asic_sort_order": [
                "min asic_total_cell_area",
                "max asic_min_slack_ns",
                "shared rank for equal physical metrics; listing order is not winner evidence",
            ],
            "non_identity_axes_excluded_from_score": True,
            "candidate_metadata_sidecar_only": True,
            "system_level_tie_breaker_required": all_metric_tied,
            "physical_metric_signature_count": len(physical_metric_signatures),
            "all_candidates_physical_metric_tied": all_physical_metric_tied,
            "candidate_parametric_sidecar_available": parametric_sidecar_available,
            "candidate_parametric_attribution_used": False,
            "candidate_parametric_attribution_policy": (
                "Candidate assignments are reported as sidecar audit context only. "
                "They must not alter physical Vivado/DC PPA ranking, Pareto membership, "
                "or winner status; true candidate-parametric ranking requires generated "
                "RTL/tool evidence whose source or parameter hashes vary by candidate."
            ),
        },
        "winner_selection_status": winner_selection_status,
        "all_candidates_metric_tied": all_metric_tied,
        "all_candidates_physical_metric_tied": all_physical_metric_tied,
        "candidate_parametric_sidecar_available": parametric_sidecar_available,
        "candidate_parametric_attribution_used": False,
        "metric_signature_count": len(metric_signatures),
        "ranking_eligible_candidate_count": len(eligible_rows),
        "blocked_candidate_count": len(candidate_rows) - len(eligible_rows),
        "blockers": blockers,
        "fpga_ranking": fpga_ranking,
        "asic_ranking": asic_ranking,
        "candidate_rows": candidate_rows,
        "pareto_frontier": {
            "schema_version": DFT_HARDWARE_PPA_PARETO_SCHEMA,
            "generated_at": _now_iso(),
            "status": "hardware_ppa_pareto_frontier_available" if pareto else "blocked_no_pareto_frontier",
            "objective_sense": {
                "fpga_total_slice_luts": "minimize",
                "fpga_total_dsps": "minimize",
                "fpga_total_block_ram_tiles": "minimize",
                "asic_total_cell_area": "minimize",
                "asic_slack_deficit_ns": "minimize",
            },
            "pareto_candidate_count": len(pareto),
            "all_candidates_metric_tied": all_metric_tied,
            "pareto_alternatives": pareto,
            "claim_boundary": _CLAIM_BOUNDARY,
        },
    }


def validate_dft_hardware_ppa_ranking(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate ranking payload consistency without upgrading claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_PPA_RANKING_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("ppa_ranking_must_not_mark_deliverable_complete")
    if payload.get("hardware_completion_eligible") is not True and payload.get("ranking_eligible_candidate_count"):
        errors.append("ranking_candidates_require_release_gate_hardware_completion_eligible")
    expected = int(payload.get("candidate_gate_passed_count", 0) or 0)
    actual = int(payload.get("ranking_eligible_candidate_count", 0) or 0)
    if expected and actual > expected:
        errors.append("ranking_eligible_count_exceeds_candidate_gate_passed_count")
    metadata_context_available = payload.get("candidate_metadata_context_available") is True
    for row in payload.get("candidate_rows", []) or []:
        if not isinstance(row, Mapping):
            errors.append("candidate_row_not_mapping")
            continue
        if row.get("ranking_eligible") and row.get("blockers"):
            errors.append(f"{row.get('candidate_id')}:ranking_eligible_with_blockers")
        if row.get("ranking_eligible"):
            if metadata_context_available:
                if not row.get("design_candidate_id"):
                    errors.append(f"{row.get('candidate_id')}:missing_design_candidate_id")
                if not isinstance(row.get("assignments"), Mapping) or not row.get("assignments"):
                    errors.append(f"{row.get('candidate_id')}:missing_candidate_assignments")
            if int(row.get("vivado_route_completed_kernel_count", 0) or 0) != int(row.get("kernel_count", 0) or 0):
                errors.append(f"{row.get('candidate_id')}:missing_vivado_route_kernel")
            if int(row.get("dc_real_target_library_kernel_count", 0) or 0) != int(row.get("kernel_count", 0) or 0):
                errors.append(f"{row.get('candidate_id')}:missing_dc_real_target_library_kernel")
        parametric = row.get("candidate_parametric_ppa", {})
        if isinstance(parametric, Mapping) and parametric.get("candidate_id_used_as_factor") is True:
            errors.append(f"{row.get('candidate_id')}:candidate_id_used_as_parametric_factor")
    if payload.get("candidate_parametric_attribution_used") is True:
        ranked_ids = [row.get("candidate_id") for row in payload.get("fpga_ranking", []) or [] if isinstance(row, Mapping)]
        if len(ranked_ids) != len(set(ranked_ids)):
            errors.append("duplicate_candidate_id_in_parametric_ranking")
    return {
        "schema_version": DFT_HARDWARE_PPA_RANKING_VALIDATION_SCHEMA,
        "generated_at": _now_iso(),
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_ppa_ranking(
    run_dir: Path,
    *,
    candidate_universe_manifest: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write hardware PPA ranking, Pareto, validation, and status artifacts."""

    run_dir = Path(run_dir)
    ranking = build_dft_hardware_ppa_ranking(
        run_dir,
        candidate_universe_manifest=candidate_universe_manifest,
    )
    validation = validate_dft_hardware_ppa_ranking(ranking)
    pareto = dict(ranking.get("pareto_frontier", {}))
    write_json(run_dir / "dft_hardware_ppa_ranking.json", ranking)
    write_json(run_dir / "dft_hardware_ppa_pareto_frontier.json", pareto)
    write_json(run_dir / "dft_hardware_ppa_ranking_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_PPA_RANKING_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation.get("valid") else "failed",
        "ranking_status": ranking.get("status"),
        "winner_selection_status": ranking.get("winner_selection_status"),
        "ranking_eligible_candidate_count": ranking.get("ranking_eligible_candidate_count"),
        "pareto_candidate_count": pareto.get("pareto_candidate_count"),
        "all_candidates_metric_tied": ranking.get("all_candidates_metric_tied"),
        "hardware_completion_eligible": ranking.get("hardware_completion_eligible"),
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_hardware_ppa_ranking_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_PPA_PARETO_SCHEMA",
    "DFT_HARDWARE_PPA_RANKING_SCHEMA",
    "DFT_HARDWARE_PPA_RANKING_STATUS_SCHEMA",
    "DFT_HARDWARE_PPA_RANKING_VALIDATION_SCHEMA",
    "build_dft_hardware_ppa_ranking",
    "validate_dft_hardware_ppa_ranking",
    "write_dft_hardware_ppa_ranking",
]
