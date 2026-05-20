#!/usr/bin/env python3
"""Run the aggregate DFT/QE hardware-closure Step5 sequence.

This runner stitches the existing fail-closed closure stages together for an
already packetized closure run.  It intentionally reuses the stage writers and
keeps each stage's claim boundary intact: raw materialization copies/wraps
existing source-flow outputs, parser output feeds hard-gate adjudication, and
release eligibility remains fail-closed unless every candidate×kernel unit gate
passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.evidence_ledger import sha256_file, write_json  # noqa: E402
from dse_v2.reference_workloads.dft_hardware_closure_adjudication import (  # noqa: E402
    write_dft_hardware_closure_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_bundle import (  # noqa: E402
    write_dft_hardware_closure_candidate_bundles,
)
from dse_v2.reference_workloads.dft_hardware_closure_evidence import (  # noqa: E402
    write_dft_hardware_closure_evidence_intake,
)
from dse_v2.reference_workloads.dft_hardware_closure_gate_adjudication import (  # noqa: E402
    write_dft_hardware_closure_gate_adjudication,
)
from dse_v2.reference_workloads.dft_hardware_closure_parsed_evidence import (  # noqa: E402
    write_dft_hardware_closure_parsed_evidence_manifest,
)
from dse_v2.reference_workloads.dft_hardware_closure_parser_run import (  # noqa: E402
    write_dft_hardware_closure_parser_run,
)
from dse_v2.reference_workloads.dft_hardware_closure_raw_stage_materialization import (  # noqa: E402
    DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA,
    DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_STATUS_SCHEMA,
    validate_dft_hardware_closure_raw_stage_materialization,
    write_dft_hardware_closure_raw_stage_materialization,
)
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_plan import (  # noqa: E402
    materialization_entries_from_source_flow_plan,
    write_dft_hardware_closure_source_flow_plan,
)
from dse_v2.reference_workloads.dft_hardware_closure_raw_transcript_registration import (  # noqa: E402
    write_dft_hardware_closure_raw_transcript_registration,
)
from dse_v2.reference_workloads.dft_hardware_closure_release_gate import (  # noqa: E402
    write_dft_hardware_closure_release_gate,
)
from dse_v2.reference_workloads.dft_hardware_closure_unit_provenance import (  # noqa: E402
    write_dft_hardware_closure_unit_provenance,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts  # noqa: E402

_CLAIM_BOUNDARY = (
    "Aggregate Step5 closure sequencing only orchestrates existing fail-closed "
    "DFT hardware closure writers. It does not run EDA tools, invent raw "
    "evidence, certify PPA, select trusted winners, or mark deliverable "
    "completion."
)


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


def _relative_source_ref(path: Path, *, root: Path) -> Dict[str, Any]:
    """Return a file ref whose path is relative to ``root`` when possible."""

    candidate = Path(path)
    try:
        display_path = str(candidate.relative_to(root))
    except ValueError:
        display_path = str(candidate)
    return {
        "path": display_path,
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _safe_child_path(root: Path, rel_path: Any) -> Path | None:
    rel = str(rel_path or "")
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        return None
    root_resolved = Path(root).resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def _packet_path(packet_index_path: Path, packet_summary: Mapping[str, Any]) -> Path | None:
    ref = packet_summary.get("packet_json", {})
    if not isinstance(ref, Mapping):
        ref = {}
    return _safe_child_path(packet_index_path.parent, ref.get("path", ""))


def _unit_key(unit: Mapping[str, Any]) -> tuple[str, str]:
    return str(unit.get("candidate_id", "")), str(unit.get("kernel_id", ""))


def _source_flow_plan_blocker_summary(plan: Mapping[str, Any]) -> Dict[str, Any]:
    units = plan.get("units", []) if isinstance(plan.get("units", []), list) else []
    blocker_counts: Dict[str, int] = {}
    materialization_eligible_count = 0
    for row in units:
        if not isinstance(row, Mapping):
            continue
        if row.get("materialization_eligible") is True and row.get("source_flow_present") is True:
            materialization_eligible_count += 1
        for blocker_id in row.get("blocker_ids", []) or []:
            key = str(blocker_id)
            blocker_counts[key] = blocker_counts.get(key, 0) + 1
    return {
        "unit_count": len(units),
        "materialization_eligible_unit_count": materialization_eligible_count,
        "blocked_unit_count": sum(
            1
            for row in units
            if isinstance(row, Mapping) and row.get("source_flow_present") is not True
        ),
        "error_count": int(plan.get("error_count", 0) or 0),
        "blocker_id_counts": dict(sorted(blocker_counts.items())),
        "errors": [dict(item) for item in plan.get("errors", [])[:20] if isinstance(item, Mapping)],
    }


def _write_materialization_eligible_packet_index(
    *,
    out_dir: Path,
    closure_packet_index_path: Path,
    source_flow_plan_path: Path,
    selected_entries: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Path, Dict[str, Any]]:
    """Write a packet index containing only source-flow-plan eligible units.

    Candidate/kernel rows that are missing, ambiguous, wrong-candidate,
    wrong-kernel, reused, or otherwise blocked by the source-flow plan must not
    reach raw transcript registration or parser execution.  The original packet
    index remains the source of truth for source-flow-plan blocker counts and
    fail-closed final reporting.
    """

    original_index = _load_json(closure_packet_index_path)
    source_flow_plan = _load_json(source_flow_plan_path)
    eligible_keys = {
        _unit_key(row)
        for row in source_flow_plan.get("units", []) or []
        if isinstance(row, Mapping)
        and row.get("source_flow_present") is True
        and row.get("materialization_eligible") is True
        and not (row.get("blocker_ids", []) or [])
    }
    if selected_entries is not None:
        selected_keys = {_unit_key(entry) for entry in selected_entries}
        eligible_keys &= selected_keys
    packets_dir = out_dir / "dft_hardware_closure_materialization_eligible_packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    packet_summaries: list[Dict[str, Any]] = []
    candidate_ids: set[str] = set()
    kernel_ids: set[str] = set()
    expected_evidence_file_count = 0
    work_item_count = 0
    blocked_work_item_count = 0
    skipped_unit_count = 0
    for packet_summary in original_index.get("packets", []) or []:
        if not isinstance(packet_summary, Mapping):
            continue
        packet_path = _packet_path(closure_packet_index_path, packet_summary)
        packet = _load_json(packet_path) if packet_path is not None else {}
        original_units = [unit for unit in packet.get("units", []) or [] if isinstance(unit, Mapping)]
        filtered_units = [dict(unit) for unit in original_units if _unit_key(unit) in eligible_keys]
        skipped_unit_count += len(original_units) - len(filtered_units)
        if not filtered_units:
            continue
        packet_candidate_ids = sorted({_unit_key(unit)[0] for unit in filtered_units})
        packet_kernel_ids = sorted({_unit_key(unit)[1] for unit in filtered_units})
        candidate_ids.update(packet_candidate_ids)
        kernel_ids.update(packet_kernel_ids)
        packet_expected_count = sum(
            len(
                [
                    item
                    for item in unit.get("expected_evidence_files", []) or []
                    if isinstance(item, Mapping) and item.get("required", True)
                ]
            )
            for unit in filtered_units
        )
        packet_work_items = sum(len(unit.get("work_item_ids", []) or []) for unit in filtered_units)
        packet_blocked_work_items = packet_work_items
        expected_evidence_file_count += packet_expected_count
        work_item_count += packet_work_items
        blocked_work_item_count += packet_blocked_work_items
        filtered_packet = {
            **packet,
            "status": "materialization_eligible_packet_filtered_by_source_flow_plan",
            "blocking_condition": "filtered_to_validated_materialization_eligible_source_flow_units",
            "candidate_ids": packet_candidate_ids,
            "kernel_ids": packet_kernel_ids,
            "unit_count": len(filtered_units),
            "work_item_count": packet_work_items,
            "blocked_work_item_count": packet_blocked_work_items,
            "expected_evidence_file_count": packet_expected_count,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "units": filtered_units,
            "source_artifacts": {
                **(
                    packet.get("source_artifacts", {})
                    if isinstance(packet.get("source_artifacts", {}), Mapping)
                    else {}
                ),
                "original_closure_packet_index": _source_ref(closure_packet_index_path),
                "source_flow_plan": _source_ref(source_flow_plan_path),
            },
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        packet_id = str(
            packet.get("packet_id")
            or packet_summary.get("packet_id")
            or f"packet_{len(packet_summaries):04d}"
        )
        filtered_packet_path = packets_dir / f"{packet_id}_materialization_eligible_packet.json"
        write_json(filtered_packet_path, filtered_packet)
        summary = {
            **dict(packet_summary),
            "status": "materialization_eligible_packet_filtered_by_source_flow_plan",
            "packet_json": _relative_source_ref(filtered_packet_path, root=out_dir),
            "candidate_ids": packet_candidate_ids,
            "kernel_ids": packet_kernel_ids,
            "unit_count": len(filtered_units),
            "work_item_count": packet_work_items,
            "blocked_work_item_count": packet_blocked_work_items,
            "expected_evidence_file_count": packet_expected_count,
            "candidate_specific_bundle_count": 0,
            "candidate_specific_evidence_present": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        packet_summaries.append(summary)

    filtered_index = {
        **original_index,
        "status": "materialization_eligible_packet_index_filtered_by_source_flow_plan",
        "blocking_condition": "filtered_to_validated_materialization_eligible_source_flow_units",
        "source_artifacts": {
            "original_closure_packet_index": _source_ref(closure_packet_index_path),
            "source_flow_plan": _source_ref(source_flow_plan_path),
        },
        "candidate_count": len(candidate_ids),
        "major_kernel_count": len(kernel_ids),
        "shard_count": len(packet_summaries),
        "packet_count": len(packet_summaries),
        "unit_count": len(eligible_keys),
        "work_item_count": work_item_count,
        "blocked_work_item_count": blocked_work_item_count,
        "expected_evidence_file_count": expected_evidence_file_count,
        "candidate_specific_bundle_count": 0,
        "candidate_specific_evidence_present_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "packets": packet_summaries,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    filtered_index_path = out_dir / "dft_hardware_closure_materialization_eligible_packet_index.json"
    write_json(filtered_index_path, filtered_index)
    status = {
        "schema_version": "dse.dft.hardware_closure_materialization_eligible_packet_index_status.v1",
        "status": "passed" if eligible_keys else "failed",
        "packet_index": "dft_hardware_closure_materialization_eligible_packet_index.json",
        "original_unit_count": int(original_index.get("unit_count", 0) or 0),
        "materialization_eligible_unit_count": len(eligible_keys),
        "skipped_ineligible_unit_count": skipped_unit_count,
        "packet_count": len(packet_summaries),
        "source_flow_plan_blockers": _source_flow_plan_blocker_summary(source_flow_plan),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_materialization_eligible_packet_index_status.json", status)
    return filtered_index_path, status



def _split_csv(values: Iterable[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def _entry_path(path_value: Any, *, base_dir: Path | None) -> Path:
    path = Path(str(path_value))
    if path.is_absolute() or base_dir is None:
        return path
    # Source-flow maps copied from prior run artifacts commonly contain
    # repo/run-root-relative paths such as ``runs/dse/...``.  Preserve those
    # when they resolve from the current workspace; otherwise interpret the
    # value relative to the map file for portable sidecar maps.
    if path.exists():
        return path
    return base_dir / path


def _entry_from_mapping(item: Mapping[str, Any], *, base_dir: Path | None) -> Dict[str, Any] | None:
    raw_path = (
        item.get("source_flow_dir")
        or item.get("source_flow")
        or item.get("flow_dir")
        or item.get("path")
        or item.get("dir")
    )
    if raw_path is None:
        return None
    return {
        "candidate_id": str(item.get("candidate_id", "") or ""),
        "kernel_id": str(item.get("kernel_id", "") or ""),
        "source_flow_dir": _entry_path(raw_path, base_dir=base_dir),
    }


def _entries_from_mapping(payload: Mapping[str, Any], *, base_dir: Path | None) -> list[Dict[str, Any]]:
    for key in ("flows", "entries", "source_flows", "kernel_flows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [entry for item in rows if isinstance(item, Mapping) for entry in [_entry_from_mapping(item, base_dir=base_dir)] if entry]
    entries: list[Dict[str, Any]] = []
    for outer_key, value in payload.items():
        if isinstance(value, str):
            entries.append({"candidate_id": "", "kernel_id": str(outer_key), "source_flow_dir": _entry_path(value, base_dir=base_dir)})
        elif isinstance(value, Mapping):
            direct = _entry_from_mapping(value, base_dir=base_dir)
            if direct:
                direct.setdefault("kernel_id", str(outer_key))
                if not direct.get("kernel_id"):
                    direct["kernel_id"] = str(outer_key)
                entries.append(direct)
            else:
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, str):
                        entries.append(
                            {
                                "candidate_id": str(outer_key),
                                "kernel_id": str(inner_key),
                                "source_flow_dir": _entry_path(inner_value, base_dir=base_dir),
                            }
                        )
    return entries


def _source_flow_map_entries(path: Path | None) -> list[Dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    base_dir = Path(path).parent
    if isinstance(payload, list):
        return [entry for item in payload if isinstance(item, Mapping) for entry in [_entry_from_mapping(item, base_dir=base_dir)] if entry]
    if isinstance(payload, Mapping):
        return _entries_from_mapping(payload, base_dir=base_dir)
    return []


def _source_flow_entry(value: str) -> Dict[str, Any]:
    """Parse candidate/kernel source-flow CLI entries.

    Accepted forms:
    - ``candidate_id:kernel_id=/path/to/flow``;
    - ``kernel_id=/path/to/flow``;
    - ``/path/to/flow`` for the caller's current candidate/kernel filters.
    """

    if "=" not in value:
        return {"candidate_id": "", "kernel_id": "", "source_flow_dir": Path(value)}
    selector, raw_path = value.split("=", 1)
    candidate_id = ""
    kernel_id = ""
    if ":" in selector:
        candidate_id, kernel_id = selector.split(":", 1)
    else:
        kernel_id = selector
    return {"candidate_id": candidate_id.strip(), "kernel_id": kernel_id.strip(), "source_flow_dir": Path(raw_path)}


def _dedupe_entries(entries: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    deduped: list[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        path = Path(entry.get("source_flow_dir", ""))
        key = (str(entry.get("candidate_id", "")), str(entry.get("kernel_id", "")), str(path))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"candidate_id": key[0], "kernel_id": key[1], "source_flow_dir": path})
    return deduped


def _entry_filter_values(entry_value: str, global_values: Sequence[str]) -> list[str]:
    if not entry_value:
        return list(global_values)
    if global_values and entry_value not in set(global_values):
        return []
    return [entry_value]


def _merge_raw_materialization_payloads(
    *,
    out_dir: Path,
    closure_packet_index_path: Path,
    evidence_root: Path,
    source_flow_map_path: Path | None,
    entries: Sequence[Mapping[str, Any]],
    payloads: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    packet_index = _load_json(closure_packet_index_path)
    units_by_id: Dict[str, Dict[str, Any]] = {}
    errors: list[Dict[str, Any]] = []
    for payload in payloads:
        payload_status = str(payload.get("status", ""))
        if payload_status.startswith("failed"):
            errors.append(
                {
                    "field": "raw_stage_materialization",
                    "status": payload_status,
                    "source_flow_dir": (payload.get("source_artifacts") or {}).get("source_flow_dir"),
                    "message": "source-flow entry did not materialize any matching closure unit",
                }
            )
        for error in payload.get("errors", []) or []:
            if isinstance(error, Mapping):
                errors.append(dict(error))
            else:
                errors.append({"message": str(error)})
        for unit in payload.get("units", []) or []:
            if not isinstance(unit, Mapping):
                continue
            unit_id = str(unit.get("unit_id", ""))
            key = unit_id or f"{unit.get('candidate_id')}:{unit.get('kernel_id')}"
            units_by_id[key] = dict(unit)
    units = [units_by_id[key] for key in sorted(units_by_id)]
    materialized_count = sum(int(row.get("materialized_file_count", 0) or 0) for row in units)
    missing_required_count = sum(int(row.get("missing_required_raw_stage_file_count", 0) or 0) for row in units)
    blocked_count = sum(1 for row in units if str(row.get("status", "")).startswith("blocked"))
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
    payload = {
        "schema_version": DFT_HARDWARE_CLOSURE_RAW_STAGE_MATERIALIZATION_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": _source_ref(closure_packet_index_path),
            "source_flow_map": _source_ref(source_flow_map_path) if source_flow_map_path else None,
            "source_flow_entries": [
                {
                    "candidate_id": entry.get("candidate_id", ""),
                    "kernel_id": entry.get("kernel_id", ""),
                    "source_flow_dir": str(entry.get("source_flow_dir", "")),
                }
                for entry in entries
            ],
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
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization.json", payload)
    validation = validate_dft_hardware_closure_raw_stage_materialization(payload)
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization_validation.json", validation)
    status_payload = {
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
    write_json(out_dir / "dft_hardware_closure_raw_stage_materialization_status.json", status_payload)
    return status_payload


def _run_raw_materialization_map(
    *,
    out_dir: Path,
    closure_packet_index_path: Path,
    evidence_root: Path,
    source_flow_map_path: Path | None,
    source_flow_entries: Sequence[str],
    prevalidated_entries: Sequence[Mapping[str, Any]] | None = None,
    candidate_ids: Sequence[str],
    kernel_ids: Sequence[str],
    max_units: int | None,
) -> Dict[str, Any]:
    if prevalidated_entries is not None:
        entries = _dedupe_entries(prevalidated_entries)
    else:
        entries = _dedupe_entries(
            [
                *_source_flow_map_entries(source_flow_map_path),
                *(_source_flow_entry(item) for item in source_flow_entries),
            ]
        )
    payloads: list[Dict[str, Any]] = []
    executed_entries: list[Dict[str, Any]] = []
    if not entries:
        empty_payload = _merge_raw_materialization_payloads(
            out_dir=out_dir,
            closure_packet_index_path=closure_packet_index_path,
            evidence_root=evidence_root,
            source_flow_map_path=source_flow_map_path,
            entries=[],
            payloads=[],
        )
        return empty_payload
    for entry in entries:
        entry_candidate_ids = _entry_filter_values(str(entry.get("candidate_id", "")), candidate_ids)
        entry_kernel_ids = _entry_filter_values(str(entry.get("kernel_id", "")), kernel_ids)
        if (str(entry.get("candidate_id", "")) and not entry_candidate_ids) or (
            str(entry.get("kernel_id", "")) and not entry_kernel_ids
        ):
            continue
        status = write_dft_hardware_closure_raw_stage_materialization(
            out_dir,
            closure_packet_index_path=closure_packet_index_path,
            source_flow_dir=Path(entry["source_flow_dir"]),
            evidence_root=evidence_root,
            candidate_ids=entry_candidate_ids,
            kernel_ids=entry_kernel_ids,
            max_units=max_units,
        )
        payload = _load_json(out_dir / status["raw_stage_materialization"])
        payloads.append(payload)
        executed_entries.append(dict(entry))
    return _merge_raw_materialization_payloads(
        out_dir=out_dir,
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        source_flow_map_path=source_flow_map_path,
        entries=executed_entries,
        payloads=payloads,
    )


def _selected_materialization_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    candidate_ids: Sequence[str],
    kernel_ids: Sequence[str],
    max_units: int | None,
) -> list[Dict[str, Any]]:
    """Apply Step5 debug/shard filters to prevalidated source-flow entries."""

    selected: list[Dict[str, Any]] = []
    candidate_filter = set(candidate_ids)
    kernel_filter = set(kernel_ids)
    for entry in entries:
        candidate_id = str(entry.get("candidate_id", ""))
        kernel_id = str(entry.get("kernel_id", ""))
        if candidate_filter and candidate_id not in candidate_filter:
            continue
        if kernel_filter and kernel_id not in kernel_filter:
            continue
        selected.append(dict(entry))
        if max_units is not None and len(selected) >= max_units:
            break
    return selected


def _ensure_step4_prerequisites(out_dir: Path) -> None:
    """Seed conservative Step4 prerequisites only when the run has none."""

    if not (out_dir / "verdict.json").exists():
        write_json(
            out_dir / "verdict.json",
            {
                "run_id": "dft-hardware-closure-step5-sequence",
                "backend": "step5_closure_sequence",
                "trusted_for_final_ranking": False,
            },
        )
    if not (out_dir / "claim_validation.json").exists():
        write_json(
            out_dir / "claim_validation.json",
            {
                "schema_version": "dse.claim_validation.v1",
                "passed": False,
                "fail_closed_reason": "aggregate Step5 closure runner seeded prerequisites for report visibility only",
            },
        )
    if not (out_dir / "evidence_requirements.json").exists():
        write_json(
            out_dir / "evidence_requirements.json",
            {
                "schema_version": "dse.evidence_requirements.v1",
                "requirements": [],
                "fail_closed_reason": "aggregate Step5 closure runner seeded prerequisites for report visibility only",
            },
        )


def run_sequence(
    *,
    out_dir: Path,
    closure_packet_index_path: Path,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
    candidate_ids: Sequence[str] = (),
    kernel_ids: Sequence[str] = (),
    source_flow_map_path: Path | None = None,
    source_flow_entries: Sequence[str] = (),
    max_units: int | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    closure_packet_index_path = Path(closure_packet_index_path)
    evidence_root = Path(evidence_root or out_dir)
    parsed_root = Path(parsed_root or evidence_root)
    candidate_ids = list(candidate_ids)
    kernel_ids = list(kernel_ids)

    statuses: Dict[str, Any] = {}
    statuses["candidate_bundles"] = write_dft_hardware_closure_candidate_bundles(
        out_dir,
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        max_units=max_units,
    )
    statuses["unit_provenance"] = write_dft_hardware_closure_unit_provenance(
        out_dir,
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    statuses["source_flow_plan"] = write_dft_hardware_closure_source_flow_plan(
        out_dir,
        closure_packet_index_path=closure_packet_index_path,
        source_flow_map_path=source_flow_map_path,
        source_flow_entries=source_flow_entries,
    )
    source_flow_plan_path = out_dir / statuses["source_flow_plan"]["source_flow_plan"]
    materialization_entries = _selected_materialization_entries(
        materialization_entries_from_source_flow_plan(source_flow_plan_path),
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    statuses["raw_stage_materialization"] = _run_raw_materialization_map(
        out_dir=out_dir,
        closure_packet_index_path=closure_packet_index_path,
        evidence_root=evidence_root,
        source_flow_map_path=source_flow_map_path,
        source_flow_entries=source_flow_entries,
        prevalidated_entries=materialization_entries,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    (
        materialization_packet_index_path,
        materialization_packet_index_status,
    ) = _write_materialization_eligible_packet_index(
        out_dir=out_dir,
        closure_packet_index_path=closure_packet_index_path,
        source_flow_plan_path=source_flow_plan_path,
        selected_entries=materialization_entries,
    )
    statuses["materialization_eligible_packet_index"] = materialization_packet_index_status
    statuses["raw_transcript_registration"] = write_dft_hardware_closure_raw_transcript_registration(
        out_dir,
        closure_packet_index_path=materialization_packet_index_path,
        evidence_root=evidence_root,
        candidate_ids=candidate_ids,
        kernel_ids=kernel_ids,
        max_units=max_units,
    )
    statuses["evidence_intake"] = write_dft_hardware_closure_evidence_intake(
        out_dir,
        closure_packet_index_path=materialization_packet_index_path,
        evidence_root=evidence_root,
    )
    intake_path = out_dir / statuses["evidence_intake"]["intake"]
    statuses["parser_run"] = write_dft_hardware_closure_parser_run(
        out_dir,
        closure_evidence_intake_path=intake_path,
        evidence_root=evidence_root,
        parsed_root=parsed_root,
    )
    statuses["adjudication"] = write_dft_hardware_closure_adjudication(
        out_dir,
        closure_evidence_intake_path=intake_path,
    )
    statuses["parsed_manifest"] = write_dft_hardware_closure_parsed_evidence_manifest(
        out_dir,
        closure_adjudication_path=out_dir / statuses["adjudication"]["adjudication"],
        parsed_root=parsed_root,
    )
    statuses["gate_adjudication"] = write_dft_hardware_closure_gate_adjudication(
        out_dir,
        parsed_evidence_manifest_path=out_dir / statuses["parsed_manifest"]["manifest"],
    )
    statuses["release_gate"] = write_dft_hardware_closure_release_gate(
        out_dir,
        gate_adjudication_path=out_dir / statuses["gate_adjudication"]["gate_adjudication"],
    )
    _ensure_step4_prerequisites(out_dir)
    statuses["step5_report"] = write_step5_report_artifacts(out_dir, claims=[])

    release = _load_json(out_dir / statuses["release_gate"]["release_gate"])
    source_flow_plan = _load_json(source_flow_plan_path)
    source_flow_plan_blockers = _source_flow_plan_blocker_summary(source_flow_plan)
    failed_stage_keys = [
        key
        for key, value in statuses.items()
        if isinstance(value, Mapping) and value.get("status") == "failed"
    ]
    summary = {
        "schema_version": "dse.dft.hardware_closure_step5_sequence_status.v1",
        "status": "failed" if failed_stage_keys else "passed",
        "failed_stage_keys": failed_stage_keys,
        "closure_packet_index": str(closure_packet_index_path),
        "materialization_eligible_packet_index": str(materialization_packet_index_path),
        "evidence_root": str(evidence_root),
        "parsed_root": str(parsed_root),
        "candidate_ids": list(candidate_ids),
        "kernel_ids": list(kernel_ids),
        "source_flow_plan_blockers": source_flow_plan_blockers,
        "stage_statuses": statuses,
        "release_gate_result": release.get("release_gate_result"),
        "hardware_completion_eligible": bool(release.get("hardware_completion_eligible", False))
        and source_flow_plan_blockers["blocked_unit_count"] == 0
        and source_flow_plan_blockers["error_count"] == 0,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_step5_sequence_status.json", summary)
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Step5 run/output directory")
    parser.add_argument("--closure-packet-index", type=Path, required=True, help="Existing dft_hardware_closure_packet_index.json")
    parser.add_argument("--evidence-root", type=Path, default=None, help="Root for candidate bundle/provenance/raw evidence paths; defaults to --out")
    parser.add_argument("--parsed-root", type=Path, default=None, help="Root for parsed hard-gate result files; defaults to evidence root")
    parser.add_argument("--candidate-id", action="append", default=[], help="Candidate filter; repeatable or comma-separated")
    parser.add_argument("--kernel-id", action="append", default=[], help="Kernel filter; repeatable or comma-separated")
    parser.add_argument("--source-flow-map", type=Path, default=None, help="JSON map of candidate/kernel selectors to source flow directories")
    parser.add_argument("--source-flow-entry", action="append", default=[], help="Extra source flow entry: candidate:kernel=DIR, kernel=DIR, or DIR")
    parser.add_argument("--max-units", type=int, default=None, help="Optional per-stage unit limit for debugging/sharded runs")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = run_sequence(
        out_dir=args.out,
        closure_packet_index_path=args.closure_packet_index,
        evidence_root=args.evidence_root,
        parsed_root=args.parsed_root,
        candidate_ids=_split_csv(args.candidate_id),
        kernel_ids=_split_csv(args.kernel_id),
        source_flow_map_path=args.source_flow_map,
        source_flow_entries=args.source_flow_entry,
        max_units=args.max_units,
    )
    if not args.quiet:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
