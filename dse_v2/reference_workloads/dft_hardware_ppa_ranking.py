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
from dse_v2.contracts.candidate_identity import (
    build_candidate_identity,
    identity_for_target,
    validate_candidate_identity,
)
from dse_v2.reference_workloads.dft_candidate_set_consistency import (
    validate_dft_candidate_set_consistency,
)
from dse_v2.reference_workloads.dft_hardware_closure_release_gate import (
    validate_dft_hardware_closure_release_gate,
)
from dse_v2.reference_workloads.vivado_report_parsing import extract_vivado_design_timing_wns


DFT_HARDWARE_PPA_RANKING_SCHEMA = "dse.dft.hardware_ppa_ranking.v1"
DFT_HARDWARE_PPA_PARETO_SCHEMA = "dse.dft.hardware_ppa_pareto_frontier.v1"
DFT_HARDWARE_PPA_RANKING_VALIDATION_SCHEMA = "dse.dft.hardware_ppa_ranking_validation.v1"
DFT_HARDWARE_PPA_RANKING_STATUS_SCHEMA = "dse.dft.hardware_ppa_ranking_status.v1"
_DEPLOYMENT_FALLBACK_METADATA_SOURCE = "step2_deployment_hard_gate_metadata_fallback"

REQUIRED_STAGE_IDS: tuple[str, ...] = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)
FPGA_REQUIRED_STAGE_IDS: tuple[str, ...] = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
)
ASIC_REQUIRED_STAGE_IDS: tuple[str, ...] = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "dc_asic_synth_timing_area",
)
TARGET_REQUIRED_STAGE_IDS: Dict[str, tuple[str, ...]] = {
    "fpga": FPGA_REQUIRED_STAGE_IDS,
    "asic": ASIC_REQUIRED_STAGE_IDS,
}

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


def _root_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_dir(),
        "kind": "directory",
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


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [ch if ch.isalnum() or ch in "._-" else "_" for ch in text]
    return "".join(chars).strip("_") or "unknown"


def _resolve_run_local_path(run_dir: Path, path_text: Any) -> Path:
    path = Path(str(path_text or ""))
    if path.is_absolute():
        return path
    return run_dir / path


def _resolve_root_local_path(root: Path, path_text: Any) -> Path:
    return _resolve_run_local_path(root, path_text)


def _raw_ref_paths(evidence_root: Path, parsed_result: Mapping[str, Any], name: str) -> list[Path]:
    paths: list[Path] = []
    for ref in parsed_result.get("raw_evidence_refs", []) or []:
        if not isinstance(ref, Mapping):
            continue
        ref_path = str(ref.get("path", ""))
        if Path(ref_path).name == name:
            paths.append(_resolve_run_local_path(evidence_root, ref_path))
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


def _extract_vivado_header_value(text: str, label: str) -> str | None:
    pattern = re.compile(rf"^\|\s*{re.escape(label)}\s*:\s*([^|\n]+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _normalize_vivado_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _vivado_part_aliases(value: Any) -> set[str]:
    """Return audit-safe aliases for Vivado device/part strings.

    Vivado reports may omit the Xilinx ``xc`` device prefix that appears in a
    selected model part number.  Keep matching exact after punctuation/case
    normalization, plus explicit leading-prefix aliases only; do not collapse
    family/package/speed-grade content.
    """

    normalized = _normalize_vivado_part(value)
    aliases = {normalized} if normalized else set()
    if normalized.startswith("xc") and len(normalized) > 2:
        aliases.add(normalized[2:])
    if normalized.startswith("x") and len(normalized) > 1:
        aliases.add(normalized[1:])
    return aliases


def _extract_vivado_wns(text: str) -> float | None:
    return extract_vivado_design_timing_wns(text)


def _vivado_metrics(evidence_root: Path, parsed_result: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = dict(parsed_result.get("metrics", {}) if isinstance(parsed_result.get("metrics"), Mapping) else {})
    utilization_paths = _raw_ref_paths(evidence_root, parsed_result, "vivado_utilization.rpt")
    timing_paths = _raw_ref_paths(evidence_root, parsed_result, "vivado_timing_summary.rpt")
    utilization_text = _read_text(utilization_paths[0]) if utilization_paths else ""
    timing_text = _read_text(timing_paths[0]) if timing_paths else ""
    utilization_device = _extract_vivado_header_value(utilization_text, "Device")
    timing_device = _extract_vivado_header_value(timing_text, "Device")
    observed_devices = [
        value
        for value in (utilization_device, timing_device)
        if value
    ]
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
            "vivado_device": observed_devices[0] if observed_devices else None,
            "vivado_utilization_device": utilization_device,
            "vivado_timing_device": timing_device,
            "utilization_report": str(utilization_paths[0]) if utilization_paths else None,
            "timing_report": str(timing_paths[0]) if timing_paths else None,
        }
    )
    return metrics


def _discover_candidate_universe_manifest(
    run_dir: Path,
    explicit: Optional[Path],
    *,
    evidence_root: Path | None = None,
) -> Optional[Path]:
    if explicit is not None:
        return Path(explicit)
    search_roots = [run_dir]
    if evidence_root is not None and Path(evidence_root) != run_dir:
        search_roots.append(Path(evidence_root))
    for root in search_roots:
        for candidate in (
            root / "release_domain_current36" / "candidate_universe_manifest.json",
            root / "release_domain" / "candidate_universe_manifest.json",
            root / "candidate_universe_manifest.json",
        ):
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _candidate_universe_by_id(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    payload = _load_json(path)
    rows = payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
    metadata: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("candidate_id"):
            continue
        candidate_id = str(row.get("candidate_id"))
        metadata[candidate_id] = dict(row)
        metadata[candidate_id].setdefault("candidate_metadata_source", "candidate_universe_manifest")
        metadata[candidate_id]["_release_candidate_universe_member"] = True
    return metadata


def _load_jsonl_rows(path: Path) -> list[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _index_by_first_present_key(
    rows: Iterable[Mapping[str, Any]],
    keys: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            value = row.get(key)
            if value:
                indexed.setdefault(str(value), dict(row))
                break
    return indexed


def _ordered_stage_ids(stage_ids: Iterable[Any]) -> list[str]:
    observed = [str(stage_id) for stage_id in stage_ids if str(stage_id)]
    required_order = {stage_id: index for index, stage_id in enumerate(REQUIRED_STAGE_IDS)}
    return sorted(set(observed), key=lambda item: (required_order.get(item, len(required_order)), item))


def _deployment_candidate_metadata_fallback(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Return audit-only metadata for Step2 deployment candidate IDs.

    Queue-style Step5 runs may carry real Step2 search artifacts and deployment
    hard-gate queue rows without copying a frozen release-domain
    ``candidate_universe_manifest.json`` into the run root.  This fallback
    preserves candidate identity/provenance context for ranking sidecars only;
    it never upgrades hardware gates or changes physical Vivado/DC PPA ordering.
    """

    queue = _load_json(run_dir / "dft_deployment_hard_gate_execution_queue.json")
    plan = _load_json(run_dir / "step3_queue" / "deployment_recommendation_plan.json")
    architecture_set = _load_json(run_dir / "step2" / "architecture_candidate_set.json")
    search_checkpoint = _load_json(run_dir / "step2" / "search_checkpoint.json")
    mapping_rows = _load_jsonl_rows(run_dir / "step2" / "mapping_candidates.jsonl")

    architecture_rows = [
        row
        for row in architecture_set.get("candidates", []) or []
        if isinstance(row, Mapping)
    ]
    architecture_rows.extend(
        row
        for row in search_checkpoint.get("candidates", []) or []
        if isinstance(row, Mapping) and row.get("candidate_type") == "architecture"
    )
    architecture_by_id = _index_by_first_present_key(
        architecture_rows,
        ("architecture_id", "candidate_id"),
    )
    mapping_by_id = _index_by_first_present_key(
        mapping_rows,
        ("mapping_candidate_id", "candidate_id"),
    )
    mapping_by_id.update(
        _index_by_first_present_key(
            (
                row
                for row in search_checkpoint.get("candidates", []) or []
                if isinstance(row, Mapping) and row.get("candidate_type") == "mapping"
            ),
            ("mapping_candidate_id", "candidate_id"),
        )
    )

    deployment_items: list[Dict[str, Any]] = []
    deployment_items.extend(
        dict(item)
        for item in queue.get("work_items", []) or []
        if isinstance(item, Mapping)
    )
    for key in ("hard_gate_work_items", "candidate_recommendations"):
        deployment_items.extend(
            dict(item)
            for item in plan.get(key, []) or []
            if isinstance(item, Mapping)
        )

    grouped: Dict[str, Dict[str, Any]] = {}
    for item in deployment_items:
        candidate_id = str(item.get("candidate_id") or item.get("architecture_id") or "").strip()
        if not candidate_id:
            continue
        row = grouped.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "targets": set(),
                "required_stage_ids": set(),
                "target_execution_profile_ids": set(),
                "items": [],
            },
        )
        row["items"].append(item)
        if item.get("target"):
            row["targets"].add(str(item.get("target")))
        if item.get("stage_id"):
            row["required_stage_ids"].add(str(item.get("stage_id")))
        for stage_id in item.get("canonical_stage_ids", []) or []:
            if stage_id:
                row["required_stage_ids"].add(str(stage_id))
        profile = item.get("target_execution_profile", {})
        if isinstance(profile, Mapping) and profile.get("profile_id"):
            row["target_execution_profile_ids"].add(str(profile.get("profile_id")))

    metadata: Dict[str, Dict[str, Any]] = {}
    for candidate_id, grouped_row in grouped.items():
        items = grouped_row["items"]
        first_item = items[0] if items else {}
        architecture_id = str(first_item.get("architecture_id") or "").strip()
        mapping_candidate_id = str(first_item.get("mapping_candidate_id") or "").strip()
        if not architecture_id and "::" in candidate_id:
            architecture_id = candidate_id.split("::", 1)[0]
        if not mapping_candidate_id and "::" in candidate_id:
            mapping_candidate_id = candidate_id.split("::", 1)[1]
        architecture = architecture_by_id.get(architecture_id, {})
        mapping = mapping_by_id.get(mapping_candidate_id, {})
        targets = sorted(str(target) for target in grouped_row["targets"] if target)
        required_stage_ids = _ordered_stage_ids(grouped_row["required_stage_ids"])
        target_profile_ids = sorted(str(item) for item in grouped_row["target_execution_profile_ids"] if item)
        architecture_parameters = (
            dict(architecture.get("parameters", {}))
            if isinstance(architecture.get("parameters"), Mapping)
            else {}
        )
        mapping_parameters = (
            dict(mapping.get("parameters", {}))
            if isinstance(mapping.get("parameters"), Mapping)
            else {}
        )
        assignments = {
            "architecture_id": architecture_id,
            "mapping_candidate_id": mapping_candidate_id,
            "hardware_target": targets[0] if len(targets) == 1 else targets,
            "architecture_family": architecture.get("architecture_family"),
            "backend": architecture_parameters.get("backend") or mapping_parameters.get("backend"),
            "architecture_parameter_hash": architecture.get("parameter_hash"),
            "mapping_parameter_hash": mapping.get("parameter_hash"),
        }
        assignments = {
            key: value
            for key, value in assignments.items()
            if value not in (None, "", [], {})
        }
        metadata[candidate_id] = {
            "candidate_id": candidate_id,
            "legacy_candidate_id": candidate_id,
            "design_candidate_id": str(first_item.get("design_candidate_id") or candidate_id),
            "candidate_id_kind": "deployment_hard_gate_candidate_id",
            "candidate_id_authoritative_for_design": False,
            "design_candidate_id_authoritative_for_design": True,
            "assignments": assignments,
            "identity_assignments": {
                key: value
                for key, value in {
                    "architecture_id": architecture_id,
                    "mapping_candidate_id": mapping_candidate_id,
                    "hardware_target": targets[0] if len(targets) == 1 else targets,
                }.items()
                if value not in (None, "", [], {})
            },
            "non_identity_assignments": {
                key: value
                for key, value in {
                    "target_execution_profile_ids": target_profile_ids,
                    "required_stage_ids": required_stage_ids,
                }.items()
                if value
            },
            "applicability_assignments": {
                key: value
                for key, value in {
                    "hardware_targets": targets,
                    "major_kernel_gate_scope": "all_major_scf_kernels",
                }.items()
                if value
            },
            "evaluation_policy_assignments": {
                key: value
                for key, value in {
                    "required_stage_ids": required_stage_ids,
                    "fresh_execution_required": True,
                    "no_shared_evidence_allowed": True,
                }.items()
                if value not in (None, "", [], {})
            },
            "design_score": architecture.get("score"),
            "screening": architecture.get("screening", {}),
            "promotion_requirements": {
                "required_stage_ids": required_stage_ids,
                "targets": targets,
            },
            "provenance": {
                "source": _DEPLOYMENT_FALLBACK_METADATA_SOURCE,
                "metadata_not_candidate_universe": True,
                "artifact_refs": {
                    "deployment_hard_gate_execution_queue": "dft_deployment_hard_gate_execution_queue.json",
                    "deployment_recommendation_plan": "step3_queue/deployment_recommendation_plan.json",
                    "architecture_candidate_set": "step2/architecture_candidate_set.json",
                    "mapping_candidates": "step2/mapping_candidates.jsonl",
                    "search_checkpoint": "step2/search_checkpoint.json",
                },
                "architecture_candidate_id": architecture.get("candidate_id"),
                "mapping_candidate_id": mapping_candidate_id,
                "claim_boundary": (
                    "Metadata fallback preserves candidate identity/search provenance "
                    "for PPA audit sidecars only; it is not a release-domain freeze, "
                    "hardware gate pass, or PPA ranking input."
                ),
            },
            "candidate_metadata_source": _DEPLOYMENT_FALLBACK_METADATA_SOURCE,
            "_metadata_context_only_not_release_universe": True,
        }
    return metadata


def _load_jsonl_rows(path: Path) -> list[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _index_by_first_present_key(rows: Iterable[Mapping[str, Any]], keys: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            value = row.get(key)
            if value:
                indexed.setdefault(str(value), dict(row))
                break
    return indexed


def _deployment_candidate_metadata_fallback(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Return audit-only metadata for Step2 deployment candidate IDs.

    Some launch/pilot runs carry real Step2 search artifacts and deployment
    hard-gate queue rows but do not copy a frozen release-domain
    ``candidate_universe_manifest.json`` into the Step5 run root.  That should
    not erase candidate identity/provenance context from the PPA sidecar.  This
    fallback reconstructs metadata only from existing Step2/deployment artifacts
    and never upgrades hardware gates or affects physical PPA ordering.
    """

    queue = _load_json(run_dir / "dft_deployment_hard_gate_execution_queue.json")
    target_model_binding = _load_json(run_dir / "dft_deployment_target_model_binding.json")
    plan = _load_json(run_dir / "step3_queue" / "deployment_recommendation_plan.json")
    architecture_set = _load_json(run_dir / "step2" / "architecture_candidate_set.json")
    search_checkpoint = _load_json(run_dir / "step2" / "search_checkpoint.json")
    mapping_rows = _load_jsonl_rows(run_dir / "step2" / "mapping_candidates.jsonl")

    architecture_rows = [
        row
        for row in architecture_set.get("candidates", []) or []
        if isinstance(row, Mapping)
    ]
    architecture_rows.extend(
        row
        for row in search_checkpoint.get("candidates", []) or []
        if isinstance(row, Mapping) and row.get("candidate_type") == "architecture"
    )
    architecture_by_id = _index_by_first_present_key(architecture_rows, ("architecture_id", "candidate_id"))
    mapping_by_id = _index_by_first_present_key(mapping_rows, ("mapping_candidate_id", "candidate_id"))
    mapping_by_id.update(
        _index_by_first_present_key(
            (
                row
                for row in search_checkpoint.get("candidates", []) or []
                if isinstance(row, Mapping) and row.get("candidate_type") == "mapping"
            ),
            ("mapping_candidate_id", "candidate_id"),
        )
    )

    deployment_items: list[Dict[str, Any]] = []
    deployment_items.extend(
        dict(item)
        for item in queue.get("work_items", []) or []
        if isinstance(item, Mapping)
    )
    for key in ("hard_gate_work_items", "candidate_recommendations"):
        deployment_items.extend(
            dict(item)
            for item in plan.get(key, []) or []
            if isinstance(item, Mapping)
        )

    target_binding_by_candidate_profile: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for binding_row in target_model_binding.get("target_binding_rows", []) or []:
        if not isinstance(binding_row, Mapping):
            continue
        selected_model = binding_row.get("selected_model", {})
        if not isinstance(selected_model, Mapping) or not selected_model:
            continue
        status = str(binding_row.get("binding_status") or "")
        if not status.startswith("bound_model"):
            continue
        target = str(binding_row.get("target") or "")
        profile_id = str(binding_row.get("profile_id") or "")
        for candidate_id in binding_row.get("candidate_ids", []) or []:
            if candidate_id and target and profile_id:
                target_binding_by_candidate_profile[
                    (str(candidate_id), target, profile_id)
                ] = dict(binding_row)

    grouped: Dict[str, Dict[str, Any]] = {}
    for item in deployment_items:
        candidate_id = str(item.get("candidate_id") or item.get("architecture_id") or "").strip()
        if not candidate_id:
            continue
        row = grouped.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "targets": set(),
                "required_stage_ids": set(),
                "target_execution_profile_ids": set(),
                "target_execution_profiles": {},
                "items": [],
            },
        )
        row["items"].append(item)
        if item.get("target"):
            row["targets"].add(str(item.get("target")))
        if item.get("stage_id"):
            row["required_stage_ids"].add(str(item.get("stage_id")))
        for stage_id in item.get("canonical_stage_ids", []) or []:
            if stage_id:
                row["required_stage_ids"].add(str(stage_id))
        profile = item.get("target_execution_profile", {})
        if isinstance(profile, Mapping) and profile.get("profile_id"):
            profile = dict(profile)
            profile_id = str(profile.get("profile_id"))
            target_binding = target_binding_by_candidate_profile.get(
                (candidate_id, str(item.get("target") or profile.get("target") or ""), profile_id)
            )
            if (
                target_binding
                and not (
                    isinstance(profile.get("selected_model"), Mapping)
                    and profile.get("selected_model")
                )
                and isinstance(target_binding.get("selected_model"), Mapping)
            ):
                profile["selected_model"] = dict(target_binding["selected_model"])
                profile["selected_model_source"] = target_binding.get("selected_model_source")
                profile["model_binding_status"] = target_binding.get("binding_status")
                profile["model_binding_artifact"] = "dft_deployment_target_model_binding.json"
            row["target_execution_profile_ids"].add(profile_id)
            row["target_execution_profiles"].setdefault(profile_id, profile)

    metadata: Dict[str, Dict[str, Any]] = {}
    for candidate_id, grouped_row in grouped.items():
        items = grouped_row["items"]
        first_item = items[0] if items else {}
        architecture_id = str(first_item.get("architecture_id") or "").strip()
        mapping_candidate_id = str(first_item.get("mapping_candidate_id") or "").strip()
        if not architecture_id and "::" in candidate_id:
            architecture_id = candidate_id.split("::", 1)[0]
        if not mapping_candidate_id and "::" in candidate_id:
            mapping_candidate_id = candidate_id.split("::", 1)[1]
        architecture = architecture_by_id.get(architecture_id, {})
        mapping = mapping_by_id.get(mapping_candidate_id, {})
        targets = sorted(str(target) for target in grouped_row["targets"] if target)
        required_stage_ids = _ordered_stage_ids(grouped_row["required_stage_ids"])
        target_profile_ids = sorted(str(item) for item in grouped_row["target_execution_profile_ids"] if item)
        architecture_parameters = (
            dict(architecture.get("parameters", {}))
            if isinstance(architecture.get("parameters"), Mapping)
            else {}
        )
        mapping_parameters = (
            dict(mapping.get("parameters", {}))
            if isinstance(mapping.get("parameters"), Mapping)
            else {}
        )
        assignments = {
            "architecture_id": architecture_id,
            "mapping_candidate_id": mapping_candidate_id,
            "hardware_target": targets[0] if len(targets) == 1 else targets,
            "architecture_family": architecture.get("architecture_family"),
            "backend": architecture_parameters.get("backend") or mapping_parameters.get("backend"),
            "architecture_parameter_hash": architecture.get("parameter_hash"),
            "mapping_parameter_hash": mapping.get("parameter_hash"),
        }
        assignments = {key: value for key, value in assignments.items() if value not in (None, "", [], {})}
        metadata[candidate_id] = {
            "candidate_id": candidate_id,
            "legacy_candidate_id": candidate_id,
            "design_candidate_id": str(first_item.get("design_candidate_id") or candidate_id),
            "candidate_id_kind": "deployment_hard_gate_candidate_id",
            "candidate_id_authoritative_for_design": False,
            "design_candidate_id_authoritative_for_design": True,
            "assignments": assignments,
            "identity_assignments": {
                key: value
                for key, value in {
                    "architecture_id": architecture_id,
                    "mapping_candidate_id": mapping_candidate_id,
                    "hardware_target": targets[0] if len(targets) == 1 else targets,
                }.items()
                if value not in (None, "", [], {})
            },
            "non_identity_assignments": {
                key: value
                for key, value in {
                    "target_execution_profile_ids": target_profile_ids,
                    "required_stage_ids": required_stage_ids,
                }.items()
                if value
            },
            "applicability_assignments": {
                key: value
                for key, value in {
                    "hardware_targets": targets,
                    "major_kernel_gate_scope": "all_major_scf_kernels",
                }.items()
                if value
            },
            "evaluation_policy_assignments": {
                key: value
                for key, value in {
                    "required_stage_ids": required_stage_ids,
                    "fresh_execution_required": True,
                    "no_shared_evidence_allowed": True,
                }.items()
                if value not in (None, "", [], {})
            },
            "design_score": architecture.get("score"),
            "screening": architecture.get("screening", {}),
            "promotion_requirements": {
                "required_stage_ids": required_stage_ids,
                "targets": targets,
            },
            "target_execution_profiles": {
                key: dict(value)
                for key, value in grouped_row["target_execution_profiles"].items()
                if isinstance(value, Mapping)
            },
            "provenance": {
                "source": "step2_deployment_hard_gate_metadata_fallback",
                "metadata_not_candidate_universe": True,
                "artifact_refs": {
                    "deployment_hard_gate_execution_queue": "dft_deployment_hard_gate_execution_queue.json",
                    "deployment_recommendation_plan": "step3_queue/deployment_recommendation_plan.json",
                    "architecture_candidate_set": "step2/architecture_candidate_set.json",
                    "mapping_candidates": "step2/mapping_candidates.jsonl",
                    "search_checkpoint": "step2/search_checkpoint.json",
                },
                "architecture_candidate_id": architecture.get("candidate_id"),
                "mapping_candidate_id": mapping_candidate_id,
                "claim_boundary": (
                    "Metadata fallback preserves candidate identity/search provenance "
                    "for PPA audit sidecars only; it is not a release-domain freeze, "
                    "hardware gate pass, or PPA ranking input."
                ),
            },
            "candidate_metadata_source": "step2_deployment_hard_gate_metadata_fallback",
        }
    return metadata


def _metadata_by_candidate_id(
    run_dir: Path,
    candidate_universe_manifest: Optional[Path],
    *,
    evidence_root: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    metadata = _candidate_universe_by_id(candidate_universe_manifest)
    binding = _load_json(run_dir / "dft_candidate_binding_map.json")
    for row in binding.get("binding_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        candidate_id = str(row.get("release_candidate_id") or row.get("candidate_id") or "")
        if not candidate_id:
            continue
        existing = metadata.setdefault(candidate_id, {"candidate_id": candidate_id})
        if row.get("design_candidate_id"):
            existing.setdefault("design_candidate_id", row.get("design_candidate_id"))
        if isinstance(row.get("release_assignments"), Mapping):
            existing.setdefault("assignments", dict(row["release_assignments"]))
        existing.setdefault("candidate_metadata_source", "candidate_binding_map")
        existing.setdefault("_candidate_binding_map_member", True)
    fallback_roots = [run_dir]
    if evidence_root is not None and Path(evidence_root) != run_dir:
        fallback_roots.append(Path(evidence_root))
    for fallback_root in fallback_roots:
        for candidate_id, fallback in _deployment_candidate_metadata_fallback(fallback_root).items():
            existing = metadata.setdefault(candidate_id, {"candidate_id": candidate_id})
            for key, value in fallback.items():
                existing.setdefault(key, value)
    return metadata


def _metadata_is_release_universe_member(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("_release_candidate_universe_member") is True


def _metadata_is_context_only(metadata: Mapping[str, Any]) -> bool:
    provenance = metadata.get("provenance", {})
    return (
        metadata.get("_metadata_context_only_not_release_universe") is True
        or metadata.get("candidate_metadata_source") == _DEPLOYMENT_FALLBACK_METADATA_SOURCE
        or (isinstance(provenance, Mapping) and provenance.get("metadata_not_candidate_universe") is True)
    )


def _candidate_set_consistency_gate(run_dir: Path) -> Dict[str, Any]:
    """Return optional candidate-set reconciliation gate context.

    Standalone ranking can still run from a frozen candidate universe manifest
    when the Step5 consistency sidecar has not been attached.  If the sidecar is
    present, however, it is treated as authoritative reconciliation evidence and
    must have passed before PPA rows can become ranking-eligible, except for the
    explicitly classified filtered-import case where missing binding/trial
    sources are covered by the release candidate-universe manifest.
    """

    consistency_path = run_dir / "dft_candidate_set_consistency.json"
    validation_path = run_dir / "dft_candidate_set_consistency_validation.json"
    status_path = run_dir / "dft_candidate_set_consistency_status.json"
    consistency = _load_json(consistency_path)
    validation = _load_json(validation_path)
    status = _load_json(status_path)
    consistency_attached = consistency_path.exists() and consistency_path.is_file()
    validation_attached = validation_path.exists() and validation_path.is_file()
    candidate_sets = consistency.get("candidate_sets", {}) if isinstance(consistency.get("candidate_sets"), Mapping) else {}
    present_candidate_set_sources = [
        str(source_id)
        for source_id, source in candidate_sets.items()
        if isinstance(source, Mapping) and source.get("present") is True
    ]
    pairwise_mismatches = (
        consistency.get("pairwise_mismatches", []) if isinstance(consistency.get("pairwise_mismatches"), list) else []
    )
    present_source_pairwise_mismatch_count = 0
    for mismatch in pairwise_mismatches:
        if not isinstance(mismatch, Mapping):
            continue
        left_source = str(mismatch.get("left_source") or "")
        right_source = str(mismatch.get("right_source") or "")
        if left_source in present_candidate_set_sources and right_source in present_candidate_set_sources:
            present_source_pairwise_mismatch_count += 1
    recomputed_validation = (
        validate_dft_candidate_set_consistency(consistency)
        if consistency_attached
        else {}
    )
    companion_validation_valid = validation.get("valid") if validation_attached else None
    recomputed_validation_valid = (
        recomputed_validation.get("valid") if consistency_attached else None
    )
    validation_valid = (
        companion_validation_valid is True and recomputed_validation_valid is True
        if consistency_attached
        else None
    )
    passed = True
    blockers: list[Dict[str, Any]] = []
    if consistency_attached:
        passed = (
            consistency.get("status") == "passed"
            and consistency.get("candidate_set_consistency_status") == "candidate_sets_match"
            and consistency.get("all_required_sources_match_and_nonempty") is True
        )
        if not passed:
            blockers.append(
                {
                    "blocker_id": "candidate_set_consistency_not_passed",
                    "path": str(consistency_path),
                    "status": consistency.get("status"),
                    "candidate_set_consistency_status": consistency.get("candidate_set_consistency_status"),
                }
            )
        if not validation_attached:
            passed = False
            blockers.append(
                {
                    "blocker_id": "candidate_set_consistency_validation_missing",
                    "path": str(validation_path),
                }
            )
        elif validation.get("valid") is not True:
            passed = False
            blockers.append(
                {
                    "blocker_id": "candidate_set_consistency_validation_not_valid",
                    "path": str(validation_path),
                    "validation_valid": validation.get("valid"),
                }
            )
        if recomputed_validation.get("valid") is not True:
            passed = False
            blockers.append(
                {
                    "blocker_id": "candidate_set_consistency_recomputed_validation_not_valid",
                    "path": str(consistency_path),
                    "validation_valid": recomputed_validation.get("valid"),
                    "errors": recomputed_validation.get("errors", []),
                }
            )
    return {
        "attached": consistency_attached,
        "validation_attached": validation_attached,
        "passed": passed,
        "status": consistency.get("status") if consistency_attached else "not_attached",
        "candidate_set_consistency_status": (
            consistency.get("candidate_set_consistency_status") if consistency_attached else "not_attached"
        ),
        "validation_valid": validation_valid,
        "companion_validation_valid": companion_validation_valid,
        "companion_validation_errors": validation.get("errors", []) if validation_attached else [],
        "recomputed_validation_valid": recomputed_validation_valid,
        "recomputed_validation_errors": recomputed_validation.get("errors", [])
        if recomputed_validation
        else [],
        "status_artifact_status": status.get("status"),
        "missing_sources": (
            list(consistency.get("missing_sources", []))
            if consistency_attached and isinstance(consistency.get("missing_sources"), list)
            else []
        ),
        "present_source_count": consistency.get("present_source_count") if consistency_attached else None,
        "present_candidate_set_sources": present_candidate_set_sources if consistency_attached else [],
        "present_source_pairwise_mismatch_count": (
            present_source_pairwise_mismatch_count if consistency_attached else 0
        ),
        "blockers": blockers,
    }


def _candidate_set_consistency_ranking_blocking(
    gate: Mapping[str, Any],
    candidate_ids: Sequence[str],
    candidate_universe_metadata_by_id: Mapping[str, Mapping[str, Any]],
    candidate_universe_manifest: Optional[Path],
) -> tuple[bool, str | None]:
    """Return whether candidate-set sidecar blockers must block PPA ranking.

    Filtered Step5 imports can intentionally omit binding-map/trial-ledger
    sidecars while still carrying a fresh release gate plus a frozen
    release-domain candidate universe manifest.  Treat only that missing-source
    condition as non-ranking-blocking; mismatched present sources, missing or
    invalid validation, absent candidate universe coverage, and all other
    sidecar failures remain fail-closed ranking blockers.
    """

    if not gate.get("blockers"):
        return False, None
    present_sources = (
        [str(source_id) for source_id in gate.get("present_candidate_set_sources", [])]
        if isinstance(gate.get("present_candidate_set_sources"), list)
        else []
    )
    present_source_count = int(gate.get("present_source_count", 0) or 0)
    missing_source_only = (
        gate.get("attached") is True
        and gate.get("passed") is not True
        and gate.get("status") == "blocked_missing_candidate_set_sources"
        and gate.get("candidate_set_consistency_status") == "candidate_sets_not_checked_missing_sources"
        and gate.get("validation_attached") is True
        and gate.get("companion_validation_valid", gate.get("validation_valid")) is True
        and bool(gate.get("missing_sources"))
        and "release_gate" in present_sources
        and present_source_count == len(present_sources)
        and int(gate.get("present_source_pairwise_mismatch_count", 0) or 0) == 0
    )
    candidate_universe_covers_release_ids = (
        candidate_universe_manifest is not None
        and Path(candidate_universe_manifest).exists()
        and Path(candidate_universe_manifest).is_file()
        and bool(candidate_ids)
        and all(candidate_id in candidate_universe_metadata_by_id for candidate_id in candidate_ids)
    )
    if missing_source_only and candidate_universe_covers_release_ids:
        return False, (
            "candidate_set_consistency_missing_binding_or_trial_sources_but_release_candidate_ids_are_"
            "covered_by_candidate_universe_manifest"
        )
    return True, None


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
            "target_execution_profiles",
            "provenance",
            "candidate_metadata_source",
        )
        if key in metadata
    }


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _candidate_identity(
    *,
    candidate_id: str,
    metadata: Mapping[str, Any],
    deployment_target: str | None = None,
) -> Dict[str, Any]:
    """Build or normalize the identity sidecar bound into PPA/ranking rows."""

    existing = _as_mapping(metadata.get("candidate_identity"))
    if existing:
        return identity_for_target(existing, deployment_target=deployment_target) if deployment_target else dict(existing)

    assignments = _as_mapping(metadata.get("assignments"))
    identity_assignments = _as_mapping(metadata.get("identity_assignments"))
    architecture_id = str(
        metadata.get("architecture_id")
        or metadata.get("design_candidate_id")
        or identity_assignments.get("hardware_microarchitecture")
        or assignments.get("hardware_microarchitecture")
        or candidate_id
    )
    mapping_candidate_id = str(
        metadata.get("mapping_candidate_id")
        or assignments.get("mapping_data_layout")
        or f"mapping::{candidate_id}"
    )
    mapping_id = str(metadata.get("mapping_id") or f"mapping::{mapping_candidate_id}")
    design_point_id = str(metadata.get("design_point_id") or metadata.get("evaluation_record_id") or candidate_id)
    accelerated_nodes = metadata.get("accelerated_node_ids")
    if not isinstance(accelerated_nodes, list) or not accelerated_nodes:
        accelerated_nodes = ["dft_accelerated_kernel_set"]
    cpu_nodes = metadata.get("cpu_retained_node_ids")
    if not isinstance(cpu_nodes, list):
        cpu_nodes = ["scf_control", "io", "mixing", "diagonalization"]
    node_to_target = _as_mapping(metadata.get("node_to_target"))
    if not node_to_target:
        node_to_target = {str(node): "accelerator" for node in accelerated_nodes}
        node_to_target.update({str(node): "host" for node in cpu_nodes})
    target_platform = _as_mapping(metadata.get("target_platform"))
    if deployment_target:
        target_platform["deployment_target"] = deployment_target
    return build_candidate_identity(
        candidate_id=candidate_id,
        architecture_id=architecture_id,
        architecture_family=str(metadata.get("architecture_family") or "dft_reference_hardware_candidate"),
        mapping_candidate_id=mapping_candidate_id,
        mapping_id=mapping_id,
        design_point_id=design_point_id,
        node_to_target=node_to_target,
        scheduling_policy=str(
            metadata.get("scheduling_policy")
            or assignments.get("schedule_runtime_policy")
            or "host_orchestrated_sync"
        ),
        simulation_backend=str(metadata.get("simulation_backend") or "candidate_specific_eda"),
        architecture_template_parameters={
            "architecture_id": architecture_id,
            "template_parameters": _as_mapping(metadata.get("template_parameters")) or dict(identity_assignments),
            "assignments": dict(assignments),
        },
        data_placement=_as_mapping(metadata.get("data_placement"))
        or {"mapping_data_layout": assignments.get("mapping_data_layout")},
        runtime_schedule_id=str(metadata.get("runtime_schedule_id") or f"runtime::{design_point_id}"),
        descriptor_granularity=str(
            metadata.get("descriptor_granularity")
            or assignments.get("interface_descriptor_protocol")
            or "graph_node_command"
        ),
        fallback_policy=_as_mapping(metadata.get("fallback_policy"))
        or {"unsupported_ops": "host_fallback_and_mark_untrusted"},
        deployment_boundary=str(metadata.get("deployment_boundary") or "full_scf_evaluated_hybrid"),
        target_platform=target_platform,
        accelerated_node_ids=accelerated_nodes,
        cpu_retained_node_ids=cpu_nodes,
    )


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
                "fpga_min_wns_ns",
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


def _source_bundle_signature(evidence_root: Path, candidate_id: str, kernel_id: str) -> Dict[str, Any]:
    path = evidence_root / "candidate_specific_evidence" / candidate_id / kernel_id / "source_bundle_manifest.json"
    unit_dir = path.parent
    payload = _load_json(path)
    command_manifest_path = unit_dir / "command_manifest.json"
    tool_versions_path = unit_dir / "tool_versions.json"
    command_manifest = _load_json(command_manifest_path)
    tool_versions = _load_json(tool_versions_path)
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
    source_ref_paths = [str(ref.get("path", "")) for ref in refs if isinstance(ref, Mapping)]
    return {
        "manifest": _source_ref(path),
        "schema_version": payload.get("schema_version"),
        "candidate_id": payload.get("candidate_id"),
        "kernel_id": payload.get("kernel_id"),
        "candidate_specific_closure": payload.get("candidate_specific_closure"),
        "shared_microkernel_smoke_only": payload.get("shared_microkernel_smoke_only"),
        "raw_evidence_scope": payload.get("raw_evidence_scope"),
        "fresh_execution_work_dir": payload.get("fresh_execution_work_dir"),
        "fresh_command_run_id": payload.get("fresh_command_run_id"),
        "candidate_parameter_manifest": payload.get("candidate_parameter_manifest"),
        "rtl_parameter_values_present": isinstance(payload.get("rtl_parameter_values"), Mapping),
        "command_manifest_ref_present": any(Path(item).name == "command_manifest.json" for item in source_ref_paths),
        "tool_versions_ref_present": any(Path(item).name == "tool_versions.json" for item in source_ref_paths),
        "command_manifest": _source_ref(command_manifest_path),
        "command_manifest_schema_version": command_manifest.get("schema_version"),
        "commands_executed": command_manifest.get("commands_executed"),
        "executed_command_count": len(command_manifest.get("executed_commands", []) or [])
        if isinstance(command_manifest.get("executed_commands", []), list)
        else 0,
        "tool_versions": _source_ref(tool_versions_path),
        "tool_versions_schema_version": tool_versions.get("schema_version"),
        "tool_versions_recorded": tool_versions.get("tool_versions_recorded"),
        "tool_row_count": len(tool_versions.get("tool_rows", []) or [])
        if isinstance(tool_versions.get("tool_rows", []), list)
        else 0,
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


def _source_bundle_blockers(
    source_bundle: Mapping[str, Any],
    *,
    candidate_id: str,
    kernel_id: str,
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    manifest = _as_mapping(source_bundle.get("manifest"))

    def add(reason: str, **extra: Any) -> None:
        row = _gate_blocker(
            candidate_id=candidate_id,
            kernel_id=kernel_id,
            stage_id="candidate_parametric_source",
            reason=reason,
        )
        row.update(extra)
        blockers.append(row)

    if manifest.get("exists") is not True:
        # Source bundles are strict when present because forged/stale/smoke
        # candidate-specific RTL provenance must fail closed.  Older target-
        # scoped PPA fixtures and filtered Step5 imports may carry admissible
        # parsed Vivado/DC gate evidence without a source-bundle sidecar; absence
        # therefore cannot invalidate the hardware gate by itself.  It only
        # means winner/source-parametric proof remains unavailable.
        return blockers
    if source_bundle.get("schema_version") != "dse.dft.hardware_closure.source_bundle_manifest.v1":
        add("source_bundle_schema_version_invalid", schema_version=source_bundle.get("schema_version"))
    if str(source_bundle.get("candidate_id") or "") != candidate_id:
        add("source_bundle_candidate_id_mismatch", actual_candidate_id=source_bundle.get("candidate_id"))
    if str(source_bundle.get("kernel_id") or "") != kernel_id:
        add("source_bundle_kernel_id_mismatch", actual_kernel_id=source_bundle.get("kernel_id"))
    if source_bundle.get("candidate_specific_closure") is not True:
        add("source_bundle_not_candidate_specific_closure")
    if source_bundle.get("shared_microkernel_smoke_only") is True:
        add("source_bundle_shared_microkernel_smoke_only")
    if source_bundle.get("raw_evidence_scope") != "candidate_specific_closure":
        add("source_bundle_raw_scope_not_candidate_specific_closure", raw_evidence_scope=source_bundle.get("raw_evidence_scope"))
    if not source_bundle.get("fresh_execution_work_dir"):
        add("source_bundle_fresh_execution_work_dir_missing")
    if not source_bundle.get("fresh_command_run_id"):
        add("source_bundle_fresh_command_run_id_missing")
    if not source_bundle.get("candidate_parametric_source_hash"):
        add("candidate_parametric_source_hash_missing")
    if not source_bundle.get("candidate_parameter_manifest"):
        add("candidate_parameter_manifest_missing")
    if source_bundle.get("rtl_parameter_values_present") is not True:
        add("rtl_parameter_values_missing")
    if source_bundle.get("command_manifest_ref_present") is not True:
        add("source_bundle_command_manifest_ref_missing")
    if source_bundle.get("tool_versions_ref_present") is not True:
        add("source_bundle_tool_versions_ref_missing")
    if _as_mapping(source_bundle.get("command_manifest")).get("exists") is not True:
        add("missing_command_manifest")
    if source_bundle.get("command_manifest_schema_version") != "dse.dft.hardware_closure.command_manifest.v1":
        add("command_manifest_schema_version_invalid", schema_version=source_bundle.get("command_manifest_schema_version"))
    if source_bundle.get("commands_executed") is not True or int(source_bundle.get("executed_command_count") or 0) <= 0:
        add("commands_not_executed")
    if _as_mapping(source_bundle.get("tool_versions")).get("exists") is not True:
        add("missing_tool_versions_manifest")
    if source_bundle.get("tool_versions_schema_version") != "dse.dft.hardware_closure.tool_versions.v1":
        add("tool_versions_schema_version_invalid", schema_version=source_bundle.get("tool_versions_schema_version"))
    if source_bundle.get("tool_versions_recorded") is not True or int(source_bundle.get("tool_row_count") or 0) <= 0:
        add("tool_versions_not_recorded")
    return blockers


def _metadata_target_execution_profiles(metadata: Mapping[str, Any]) -> list[Dict[str, Any]]:
    profiles = metadata.get("target_execution_profiles")
    if isinstance(profiles, Mapping):
        return [
            dict(profile)
            for profile in profiles.values()
            if isinstance(profile, Mapping)
        ]
    if isinstance(profiles, list):
        return [
            dict(profile)
            for profile in profiles
            if isinstance(profile, Mapping)
        ]
    return []


def _fpga_profile_ids(metadata: Mapping[str, Any]) -> list[str]:
    non_identity = (
        metadata.get("non_identity_assignments", {})
        if isinstance(metadata.get("non_identity_assignments", {}), Mapping)
        else {}
    )
    return [
        str(item)
        for item in non_identity.get("target_execution_profile_ids", []) or []
        if str(item).startswith("fpga_")
    ]


def _target_profile_ids(metadata: Mapping[str, Any], prefix: str) -> list[str]:
    non_identity = (
        metadata.get("non_identity_assignments", {})
        if isinstance(metadata.get("non_identity_assignments", {}), Mapping)
        else {}
    )
    return [
        str(item)
        for item in non_identity.get("target_execution_profile_ids", []) or []
        if str(item).startswith(prefix)
    ]


def _library_name_from_path_or_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("dc_target_library:"):
        text = text.split(":", 1)[1].strip()
    name = Path(text).name if "/" in text or "\\" in text else text
    if name.endswith(".db"):
        name = name[:-3]
    return name


def _normalize_dc_library(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _library_name_from_path_or_name(value).lower())


def _model_dc_target_libraries(model: Mapping[str, Any]) -> list[str]:
    libraries: list[str] = []
    for key in ("dc_target_library", "target_library", "library_name"):
        value = model.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            libraries.extend(str(item) for item in value if str(item))
        elif value:
            libraries.append(str(value))
    if model.get("library_db_path"):
        libraries.append(_library_name_from_path_or_name(model.get("library_db_path")))
    return sorted(dict.fromkeys(item for item in libraries if item))


def _fpga_target_model_binding(
    metadata: Mapping[str, Any],
    *,
    observed_devices: Sequence[str],
    required_stage_ids: Sequence[str],
) -> Dict[str, Any]:
    """Return target-device binding status for FPGA deployment evidence.

    A Vivado implementation on an arbitrary/default part is useful progress
    evidence, but it must not satisfy an FPGA deployment ranking row when the
    target execution profile says a model/board binding is still required.
    """

    if "vivado_fpga_synth_or_impl" not in set(required_stage_ids):
        return {
            "required": False,
            "status": "not_fpga_candidate",
            "blocker_id": None,
        }

    profiles = _metadata_target_execution_profiles(metadata)
    fpga_profiles = [
        profile for profile in profiles
        if str(profile.get("target") or "fpga").lower() == "fpga"
        or str(profile.get("profile_id") or "").startswith("fpga_")
    ]
    profile_ids = _fpga_profile_ids(metadata)
    binding_required = bool(fpga_profiles) or bool(profile_ids)
    if not binding_required:
        return {
            "required": False,
            "status": "no_target_execution_profile_binding_required",
            "blocker_id": None,
            "observed_vivado_devices": sorted(set(observed_devices)),
        }

    selected_models = [
        profile.get("selected_model")
        for profile in fpga_profiles
        if isinstance(profile.get("selected_model"), Mapping)
    ]
    if not selected_models:
        return {
            "required": True,
            "status": "missing_selected_model",
            "blocker_id": "fpga_target_model_binding_missing",
            "target_execution_profile_ids": profile_ids
            or [str(profile.get("profile_id")) for profile in fpga_profiles if profile.get("profile_id")],
            "observed_vivado_devices": sorted(set(observed_devices)),
            "claim_boundary": (
                "Vivado PPA on an unbound/default FPGA part is progress evidence only; "
                "a deployment FPGA ranking requires a selected model with Vivado part "
                "binding before the row can be ranking-eligible."
            ),
        }

    normalized_observed = set().union(
        *(_vivado_part_aliases(device) for device in observed_devices)
    ) if observed_devices else set()
    expected_parts = []
    for model in selected_models:
        for key in ("vivado_part", "vivado_device"):
            if model.get(key):
                expected_parts.append(str(model.get(key)))
    normalized_expected = set().union(
        *(_vivado_part_aliases(part) for part in expected_parts)
    ) if expected_parts else set()
    if not normalized_expected:
        return {
            "required": True,
            "status": "selected_model_missing_vivado_part",
            "blocker_id": "fpga_selected_model_missing_vivado_part",
            "target_execution_profile_ids": profile_ids
            or [str(profile.get("profile_id")) for profile in fpga_profiles if profile.get("profile_id")],
            "selected_model_ids": [
                str(model.get("model_id") or model.get("part_number") or "unknown")
                for model in selected_models
            ],
            "observed_vivado_devices": sorted(set(observed_devices)),
            "claim_boundary": (
                "A selected FPGA model must name the Vivado part/device used for "
                "implementation before candidate-specific PPA can be treated as "
                "deployment-target evidence."
            ),
        }
    if not normalized_observed:
        return {
            "required": True,
            "status": "vivado_device_not_observed",
            "blocker_id": "fpga_vivado_device_not_observed",
            "expected_vivado_parts": sorted(set(expected_parts)),
            "claim_boundary": (
                "The Vivado reports must expose the implemented device so the "
                "target model binding can be audited."
            ),
        }
    if not normalized_observed.intersection(normalized_expected):
        return {
            "required": True,
            "status": "vivado_device_mismatch",
            "blocker_id": "fpga_vivado_device_mismatch",
            "expected_vivado_parts": sorted(set(expected_parts)),
            "observed_vivado_devices": sorted(set(observed_devices)),
            "claim_boundary": (
                "The implemented Vivado part does not match the selected FPGA "
                "deployment model, so the raw PPA cannot satisfy that target."
            ),
        }
    return {
        "required": True,
        "status": "bound_model_matches_evidence",
        "blocker_id": None,
        "expected_vivado_parts": sorted(set(expected_parts)),
        "observed_vivado_devices": sorted(set(observed_devices)),
    }


def _asic_target_model_binding(
    metadata: Mapping[str, Any],
    *,
    observed_target_libraries: Sequence[str],
    required_stage_ids: Sequence[str],
) -> Dict[str, Any]:
    """Return ASIC target-library binding status for deployment evidence."""

    if "dc_asic_synth_timing_area" not in set(required_stage_ids):
        return {
            "required": False,
            "status": "not_asic_candidate",
            "blocker_id": None,
        }

    profiles = _metadata_target_execution_profiles(metadata)
    asic_profiles = [
        profile for profile in profiles
        if str(profile.get("target") or "asic").lower() == "asic"
        or str(profile.get("profile_id") or "").startswith("asic_")
    ]
    profile_ids = _target_profile_ids(metadata, "asic_") or [
        str(profile.get("profile_id")) for profile in asic_profiles if profile.get("profile_id")
    ]
    binding_required = bool(asic_profiles) or bool(profile_ids)
    if not binding_required:
        return {
            "required": False,
            "status": "no_target_execution_profile_binding_required",
            "blocker_id": None,
            "observed_dc_target_libraries": sorted(set(observed_target_libraries)),
        }

    selected_models = [
        profile.get("selected_model")
        for profile in asic_profiles
        if isinstance(profile.get("selected_model"), Mapping)
    ]
    if not selected_models:
        return {
            "required": True,
            "status": "missing_selected_model",
            "blocker_id": "asic_target_model_binding_missing",
            "target_execution_profile_ids": profile_ids,
            "observed_dc_target_libraries": sorted(set(observed_target_libraries)),
            "claim_boundary": (
                "DC timing/area on an unbound/default ASIC library is progress "
                "evidence only; a deployment ASIC ranking requires a selected "
                "technology/library model whose target library matches the DC evidence."
            ),
        }

    expected_libraries: list[str] = []
    for model in selected_models:
        expected_libraries.extend(_model_dc_target_libraries(model))
    normalized_expected = {
        _normalize_dc_library(library)
        for library in expected_libraries
        if _normalize_dc_library(library)
    }
    normalized_observed = {
        _normalize_dc_library(library)
        for library in observed_target_libraries
        if _normalize_dc_library(library)
    }
    if not normalized_expected:
        return {
            "required": True,
            "status": "selected_model_missing_dc_target_library",
            "blocker_id": "asic_selected_model_missing_dc_target_library",
            "target_execution_profile_ids": profile_ids,
            "selected_model_ids": [
                str(model.get("model_id") or model.get("library_name") or "unknown")
                for model in selected_models
            ],
            "observed_dc_target_libraries": sorted(set(observed_target_libraries)),
            "claim_boundary": (
                "A selected ASIC model must name the dc_target_library/library_name "
                "used for DC timing/area before PPA can be treated as deployment-target evidence."
            ),
        }
    if not normalized_observed:
        return {
            "required": True,
            "status": "dc_target_library_not_observed",
            "blocker_id": "asic_dc_target_library_not_observed",
            "expected_dc_target_libraries": sorted(set(expected_libraries)),
            "claim_boundary": (
                "The parsed DC evidence must expose the target library so the "
                "ASIC target model binding can be audited."
            ),
        }
    if not normalized_observed.intersection(normalized_expected):
        return {
            "required": True,
            "status": "dc_target_library_mismatch",
            "blocker_id": "asic_dc_target_library_mismatch",
            "expected_dc_target_libraries": sorted(set(expected_libraries)),
            "observed_dc_target_libraries": sorted(set(observed_target_libraries)),
            "claim_boundary": (
                "The DC target library does not match the selected ASIC deployment "
                "model, so the raw PPA cannot satisfy that target."
            ),
        }
    return {
        "required": True,
        "status": "bound_model_matches_evidence",
        "blocker_id": None,
        "expected_dc_target_libraries": sorted(set(expected_libraries)),
        "observed_dc_target_libraries": sorted(set(observed_target_libraries)),
    }


def _apply_candidate_parametric_source_policy(candidate_rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Record no-winner policy blockers when source bundles are not distinct.

    Candidate-universe assignments are useful audit context, but they are not
    physical evidence. If fresh source manifests show all currently eligible
    candidates used the same RTL source for a kernel and no explicit generated
    RTL parameter hash differentiates them, physical PPA attribution is not
    candidate-parametric enough to select a trusted winner.  The parsed
    Vivado/DC PPA rows are still valid hardware-only ranking evidence, so this
    policy must not hide tied rankings or Pareto rows.
    """

    winner_policy_blockers: list[Dict[str, Any]] = []
    eligible_rows_by_target: Dict[str, list[Dict[str, Any]]] = {}
    for row in candidate_rows:
        if row.get("ranking_eligible"):
            target_key = str(row.get("target") or "mixed_target")
            eligible_rows_by_target.setdefault(target_key, []).append(row)
    for target_key, eligible_rows in eligible_rows_by_target.items():
        if len(eligible_rows) < 2:
            continue
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
                attribution_signatures = {
                    json.dumps(
                        row.get("candidate_parametric_ppa", {}).get("assignments_used", {}),
                        sort_keys=True,
                    )
                    for row, _source in rows_with_sources
                    if isinstance(row.get("candidate_parametric_ppa"), Mapping)
                    and row["candidate_parametric_ppa"].get("available") is True
                }
                warning_id = (
                    "static_rtl_source_signature_ranked_by_assignment_attribution"
                    if len(attribution_signatures) > 1
                    else "static_rtl_source_signature_no_winner_policy"
                )
                # Assignment-derived attribution is audit-only.  Even when
                # assignment sidecars differ by candidate, identical generated
                # RTL source signatures and absent/identical parameter hashes
                # prove that the physical Vivado/DC PPA evidence is not
                # candidate-parametric enough to select a trusted winner.  Keep
                # the parsed PPA rows ranking-visible; block winner proof only.
                for row, source in rows_with_sources:
                    blocker = {
                        "candidate_id": row.get("candidate_id"),
                        "kernel_id": kernel_id,
                        "target": target_key,
                        "stage_id": "candidate_parametric_source",
                        "blocker_id": "candidate_parametric_source_not_distinguished",
                        "source_bundle_manifest": source.get("manifest", {}).get("path"),
                        "scope": "winner_selection_only",
                        "ranking_eligible_unchanged": True,
                    }
                    row.setdefault("candidate_parametric_source_warnings", []).append(
                        {
                            "candidate_id": row.get("candidate_id"),
                            "kernel_id": kernel_id,
                            "target": target_key,
                            "warning_id": warning_id,
                            "source_bundle_manifest": source.get("manifest", {}).get("path"),
                            "ranking_eligible_unchanged": True,
                        }
                    )
                    row.setdefault("winner_policy_blockers", []).append(blocker)
                    winner_policy_blockers.append(dict(blocker))
    return winner_policy_blockers


def _ordered_stage_ids(stage_ids: Iterable[Any]) -> list[str]:
    seen = {str(stage_id) for stage_id in stage_ids if stage_id}
    ordered = [stage_id for stage_id in REQUIRED_STAGE_IDS if stage_id in seen]
    ordered.extend(sorted(seen - set(REQUIRED_STAGE_IDS)))
    return ordered


def _target_from_stage_ids(stage_ids: Sequence[str]) -> str | None:
    stage_set = set(stage_ids)
    has_fpga = "vivado_fpga_synth_or_impl" in stage_set
    has_asic = "dc_asic_synth_timing_area" in stage_set
    if has_fpga and not has_asic:
        return "fpga"
    if has_asic and not has_fpga:
        return "asic"
    return None


def _fallback_stage_ids_for_candidate(candidate_id: str) -> tuple[str, ...]:
    candidate_lower = candidate_id.lower()
    if "asic" in candidate_lower:
        return ASIC_REQUIRED_STAGE_IDS
    if "fpga" in candidate_lower or "hbm" in candidate_lower:
        return FPGA_REQUIRED_STAGE_IDS
    return REQUIRED_STAGE_IDS


def _candidate_unit_stage_scope(
    release_gate: Mapping[str, Any],
    gate_adjudication: Mapping[str, Any],
) -> Dict[tuple[str, str], list[str]]:
    """Return target-scoped required stage IDs by candidate/kernel unit.

    The release gate is the candidate pass/fail owner, but older release rows do
    not always carry ``required_stage_ids`` on passed units.  Gate adjudication
    still preserves the exact observed stage rows, so prefer it before falling
    back to release-row hints.  This prevents ASIC units from being re-expanded
    to a Vivado requirement and FPGA units from being re-expanded to a DC
    requirement during ranking.
    """

    stage_scope: Dict[tuple[str, str], list[str]] = {}
    for unit in gate_adjudication.get("unit_rows", []) or []:
        if not isinstance(unit, Mapping):
            continue
        candidate_id = str(unit.get("candidate_id") or "")
        kernel_id = str(unit.get("kernel_id") or "")
        if not candidate_id or not kernel_id:
            continue
        stage_rows = unit.get("stage_rows", [])
        if not isinstance(stage_rows, list):
            continue
        stage_ids = _ordered_stage_ids(
            row.get("stage_id")
            for row in stage_rows
            if isinstance(row, Mapping) and row.get("stage_id")
        )
        if stage_ids:
            stage_scope[(candidate_id, kernel_id)] = stage_ids

    for candidate in release_gate.get("candidate_rows", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        candidate_stage_ids = _ordered_stage_ids(candidate.get("required_stage_ids", []) or [])
        for kernel in candidate.get("kernel_rows", []) or []:
            if not isinstance(kernel, Mapping):
                continue
            kernel_id = str(kernel.get("kernel_id") or "")
            if not kernel_id or (candidate_id, kernel_id) in stage_scope:
                continue
            stage_ids = _ordered_stage_ids(kernel.get("required_stage_ids", []) or [])
            if not stage_ids:
                stage_ids = _ordered_stage_ids(
                    reason.get("stage_id")
                    for reason in kernel.get("non_passing_stage_reasons", []) or []
                    if isinstance(reason, Mapping) and reason.get("stage_id")
                )
            if not stage_ids:
                stage_ids = candidate_stage_ids
            if stage_ids:
                stage_scope[(candidate_id, kernel_id)] = stage_ids
    return stage_scope


def _parsed_result(parsed_root: Path, candidate_id: str, kernel_id: str, stage_id: str) -> Dict[str, Any]:
    candidate_paths = [
        parsed_root
        / "parsed_hard_gate_results"
        / _safe_slug(candidate_id)
        / _safe_slug(kernel_id)
        / f"{_safe_slug(stage_id)}_parsed_result.json",
        parsed_root
        / "parsed_hard_gate_results"
        / candidate_id
        / kernel_id
        / f"{stage_id}_parsed_result.json",
    ]
    for path in candidate_paths:
        payload = _load_json(path)
        if payload:
            return payload
    return {}


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
    parsed_root: Path,
    evidence_root: Path,
    *,
    candidate_id: str,
    kernel_id: str,
    required_stage_ids: Sequence[str] = REQUIRED_STAGE_IDS,
) -> tuple[Dict[str, Dict[str, Any]], list[Dict[str, Any]]]:
    stages: Dict[str, Dict[str, Any]] = {}
    blockers: list[Dict[str, Any]] = []
    for stage_id in _ordered_stage_ids(required_stage_ids):
        parsed = _parsed_result(parsed_root, candidate_id, kernel_id, stage_id)
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
            metrics = _vivado_metrics(evidence_root, parsed)
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
                "fpga_wns": kernel.get("fpga", {}).get("wns_ns"),
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
        ("fpga_total_slice_luts", "minimize"),
        ("fpga_total_slice_registers", "minimize"),
        ("fpga_total_dsps", "minimize"),
        ("fpga_total_block_ram_tiles", "minimize"),
        ("fpga_total_bonded_iob", "minimize"),
        ("fpga_min_wns_ns", "maximize"),
        ("asic_total_cell_area", "minimize"),
        ("asic_slack_deficit_ns", "minimize"),
    )
    frontier: list[Dict[str, Any]] = []
    for row in rows:
        dominated = False
        for other in rows:
            if other is row:
                continue
            comparisons = []
            for obj, sense in objectives:
                other_value = _as_float(other.get(obj))
                row_value = _as_float(row.get(obj))
                if other_value is None:
                    other_value = float("inf") if sense == "minimize" else float("-inf")
                if row_value is None:
                    row_value = float("inf") if sense == "minimize" else float("-inf")
                if sense == "maximize":
                    comparisons.append((other_value >= row_value, other_value > row_value))
                else:
                    comparisons.append((other_value <= row_value, other_value < row_value))
            no_worse = all(item[0] for item in comparisons)
            strictly_better = any(item[1] for item in comparisons)
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


def _ranking_metric_desc(row: Mapping[str, Any], raw_key: str, *, parametric_available: bool) -> float:
    value = _as_float(row.get(raw_key))
    if value is None:
        return float("inf")
    return -value


def _refresh_target_eligibility(row: Dict[str, Any]) -> None:
    target_identities = _as_mapping(row.get("target_identities"))
    blockers = [dict(blocker) for blocker in row.get("blockers", []) or [] if isinstance(blocker, Mapping)]
    target_eligibility: Dict[str, Dict[str, Any]] = {}
    scoped_target = str(row.get("target") or "")
    if scoped_target not in TARGET_REQUIRED_STAGE_IDS:
        scoped_target = ""
    target_independent_stage_ids = {
        "candidate_universe_metadata",
        "candidate_identity",
        "candidate_parametric_source",
        "candidate_set_consistency",
        "release_gate",
    }
    for target, required_stages in TARGET_REQUIRED_STAGE_IDS.items():
        if scoped_target and target != scoped_target:
            target_eligibility[target] = {
                "target": target,
                "required_stage_ids": list(required_stages),
                "ranking_eligible": False,
                "blocker_count": 1,
                "blockers": [
                    {
                        "candidate_id": row.get("candidate_id"),
                        "stage_id": "target_scope",
                        "blocker_id": "target_not_in_candidate_scope",
                        "candidate_target": scoped_target,
                        "target": target,
                    }
                ],
                "candidate_identity": target_identities.get(target, {}),
            }
            row[f"{target}_ranking_eligible"] = False
            continue
        required_stage_set = set(required_stages)
        target_blockers = [
            blocker
            for blocker in blockers
            if str(blocker.get("stage_id") or "") in required_stage_set
            or str(blocker.get("stage_id") or "") in target_independent_stage_ids
        ]
        target_eligibility[target] = {
            "target": target,
            "required_stage_ids": list(required_stages),
            "ranking_eligible": not target_blockers,
            "blocker_count": len(target_blockers),
            "blockers": target_blockers,
            "candidate_identity": target_identities.get(target, {}),
        }
        row[f"{target}_ranking_eligible"] = not target_blockers
    row["target_eligibility"] = target_eligibility


def _target_ranking_rows(rows: Sequence[Dict[str, Any]], target: str) -> list[Dict[str, Any]]:
    ranked_rows: list[Dict[str, Any]] = []
    for row in rows:
        target_payload = _as_mapping(_as_mapping(row.get("target_eligibility")).get(target))
        if target_payload.get("ranking_eligible") is not True:
            continue
        ranked_row = dict(row)
        ranked_row["ranking_target"] = target
        ranked_row["target_required_stage_ids"] = list(TARGET_REQUIRED_STAGE_IDS[target])
        ranked_row["candidate_identity"] = target_payload.get("candidate_identity", {})
        ranked_row["target_specific_blockers"] = list(target_payload.get("blockers", []) or [])
        ranked_rows.append(ranked_row)
    return ranked_rows


def build_dft_hardware_ppa_ranking(
    run_dir: Path,
    *,
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
    candidate_universe_manifest: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a fail-closed hardware PPA ranking payload."""

    run_dir = Path(run_dir)
    evidence_root = Path(evidence_root or run_dir)
    parsed_root = Path(parsed_root or evidence_root)
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    release_validation_path = run_dir / "dft_hardware_closure_release_gate_validation.json"
    parser_run_path = run_dir / "dft_hardware_closure_parser_run.json"
    gate_adjudication_path = run_dir / "dft_hardware_closure_gate_adjudication.json"
    release_gate = _load_json(release_gate_path)
    release_validation = _load_json(release_validation_path)
    parser_run = _load_json(parser_run_path)
    gate_adjudication = _load_json(gate_adjudication_path)
    release_recomputed_validation = (
        validate_dft_hardware_closure_release_gate(release_gate)
        if release_gate
        else {}
    )
    release_companion_validation_valid = release_validation.get("valid")
    release_recomputed_validation_valid = (
        release_recomputed_validation.get("valid") if release_gate else None
    )
    release_validation_summary = {
        "companion_valid": release_companion_validation_valid,
        "companion_errors": release_validation.get("errors", []) if release_validation else [],
        "recomputed_valid": release_recomputed_validation_valid,
        "recomputed_errors": release_recomputed_validation.get("errors", [])
        if release_recomputed_validation
        else [],
        "valid": (
            release_companion_validation_valid is True
            or (release_companion_validation_valid is None and release_recomputed_validation_valid is True)
        )
        if release_gate
        else False,
    }
    resolved_candidate_universe_manifest = _discover_candidate_universe_manifest(
        run_dir,
        candidate_universe_manifest,
        evidence_root=evidence_root,
    )
    candidate_universe_metadata_by_id = _candidate_universe_by_id(resolved_candidate_universe_manifest)
    metadata_by_candidate_id = _metadata_by_candidate_id(
        run_dir,
        resolved_candidate_universe_manifest,
        evidence_root=evidence_root,
    )
    candidate_set_consistency_gate = _candidate_set_consistency_gate(run_dir)
    stage_scope = _candidate_unit_stage_scope(release_gate, gate_adjudication)
    blockers: list[Dict[str, Any]] = []
    release_gate_blockers: list[Dict[str, Any]] = []

    if not release_gate:
        release_gate_blockers.append({"blocker_id": "missing_release_gate", "path": str(release_gate_path)})
    if release_companion_validation_valid is not True:
        release_gate_blockers.append(
            {
                "blocker_id": "release_gate_validation_not_valid",
                "validation_valid": release_companion_validation_valid,
                "errors": release_validation.get("errors", []) if release_validation else [],
            }
        )
    if (
        release_gate
        and release_recomputed_validation_valid is not True
        and release_companion_validation_valid is not True
    ):
        release_gate_blockers.append(
            {
                "blocker_id": "release_gate_recomputed_validation_not_valid",
                "validation_valid": release_recomputed_validation_valid,
                "errors": release_recomputed_validation.get("errors", []),
            }
        )
    if release_gate.get("hardware_completion_eligible") is not True:
        release_gate_blockers.append(
            {
                "blocker_id": "release_gate_not_hardware_completion_eligible",
                "release_gate_result": release_gate.get("release_gate_result"),
            }
        )
    blockers.extend(release_gate_blockers)

    candidate_ids = _passed_candidate_ids(release_gate)
    kernel_ids = _kernel_ids(release_gate)
    missing_universe_metadata_candidate_ids = [
        candidate_id for candidate_id in candidate_ids if candidate_id not in metadata_by_candidate_id
    ]
    if missing_universe_metadata_candidate_ids:
        blockers.append(
            {
                "blocker_id": "missing_candidate_universe_metadata",
                "path": str(resolved_candidate_universe_manifest) if resolved_candidate_universe_manifest else None,
                "candidate_ids": missing_universe_metadata_candidate_ids,
            }
        )
    context_only_candidate_ids = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id in metadata_by_candidate_id
        and candidate_id not in candidate_universe_metadata_by_id
        and _metadata_is_context_only(metadata_by_candidate_id[candidate_id])
    ]
    (
        candidate_set_consistency_ranking_blocking,
        candidate_set_consistency_ranking_bypass_reason,
    ) = _candidate_set_consistency_ranking_blocking(
        candidate_set_consistency_gate,
        candidate_ids,
        candidate_universe_metadata_by_id,
        resolved_candidate_universe_manifest,
    )
    candidate_set_consistency_gate = dict(candidate_set_consistency_gate)
    candidate_set_consistency_gate["ranking_blocking"] = candidate_set_consistency_ranking_blocking
    candidate_set_consistency_gate["ranking_bypass_reason"] = candidate_set_consistency_ranking_bypass_reason
    candidate_set_consistency_gate["candidate_universe_covers_release_candidate_ids"] = (
        resolved_candidate_universe_manifest is not None
        and Path(resolved_candidate_universe_manifest).exists()
        and Path(resolved_candidate_universe_manifest).is_file()
        and bool(candidate_ids)
        and not missing_universe_metadata_candidate_ids
    )
    if candidate_set_consistency_ranking_blocking:
        blockers.extend(candidate_set_consistency_gate["blockers"])
    candidate_rows: list[Dict[str, Any]] = []
    for candidate_id in candidate_ids:
        candidate_gate_blockers: list[Dict[str, Any]] = []
        candidate_ranking_blockers: list[Dict[str, Any]] = []
        metadata = metadata_by_candidate_id.get(candidate_id, {})
        if not metadata:
            candidate_ranking_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "stage_id": "candidate_universe_metadata",
                    "blocker_id": "missing_candidate_universe_metadata",
                }
            )
        elif not _metadata_is_release_universe_member(metadata) and not _metadata_is_context_only(metadata):
            candidate_ranking_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "stage_id": "candidate_universe_metadata",
                    "blocker_id": "missing_candidate_universe_metadata",
                    "path": str(resolved_candidate_universe_manifest) if resolved_candidate_universe_manifest else None,
                    "metadata_source": metadata.get("candidate_metadata_source"),
                }
            )
        target_identities = {
            target: _candidate_identity(
                candidate_id=candidate_id,
                metadata=metadata,
                deployment_target=target,
            )
            for target in TARGET_REQUIRED_STAGE_IDS
        }
        base_identity = _candidate_identity(candidate_id=candidate_id, metadata=metadata)
        for target, identity in target_identities.items():
            for error in validate_candidate_identity(
                identity,
                field_prefix=f"candidate_rows[{candidate_id}].target_identities.{target}",
            ):
                candidate_ranking_blockers.append(
                    {
                        "candidate_id": candidate_id,
                        "stage_id": "candidate_identity",
                        "target": target,
                        "blocker_id": "candidate_identity_invalid",
                        "field": error.get("field"),
                        "message": error.get("message"),
                    }
                )
        if candidate_set_consistency_ranking_blocking and candidate_set_consistency_gate["blockers"]:
            for blocker in candidate_set_consistency_gate["blockers"]:
                candidate_ranking_blockers.append(
                    {
                        "candidate_id": candidate_id,
                        "stage_id": "candidate_set_consistency",
                        **blocker,
                    }
                )
        if release_gate_blockers:
            for blocker in release_gate_blockers:
                candidate_ranking_blockers.append(
                    {
                        "candidate_id": candidate_id,
                        "stage_id": "release_gate",
                        **blocker,
                    }
                )
        kernel_rows: list[Dict[str, Any]] = []
        candidate_required_stage_ids: set[str] = set()
        candidate_targets: set[str] = set()
        fpga_vivado_devices: set[str] = set()
        asic_dc_target_libraries: set[str] = set()
        totals = {
            "fpga_total_slice_luts": 0,
            "fpga_total_slice_registers": 0,
            "fpga_total_block_ram_tiles": 0,
            "fpga_total_dsps": 0,
            "fpga_total_bonded_iob": 0,
            "fpga_min_wns_ns": None,
            "asic_total_cell_area": 0.0,
            "asic_min_slack_ns": None,
            "vivado_route_completed_kernel_count": 0,
            "dc_real_target_library_kernel_count": 0,
        }
        for kernel_id in kernel_ids:
            required_stage_ids = stage_scope.get(
                (candidate_id, kernel_id),
                list(_fallback_stage_ids_for_candidate(candidate_id)),
            )
            required_stage_ids = _ordered_stage_ids(required_stage_ids)
            candidate_required_stage_ids.update(required_stage_ids)
            kernel_target = _target_from_stage_ids(required_stage_ids)
            if kernel_target:
                candidate_targets.add(kernel_target)
            stages, stage_blockers = _stage_summary(
                parsed_root,
                evidence_root,
                candidate_id=candidate_id,
                kernel_id=kernel_id,
                required_stage_ids=required_stage_ids,
            )
            candidate_gate_blockers.extend(stage_blockers)
            fpga = dict(stages.get("vivado_fpga_synth_or_impl", {}).get("metrics", {}))
            asic = dict(stages.get("dc_asic_synth_timing_area", {}).get("metrics", {}))
            for device_key in ("vivado_device", "vivado_utilization_device", "vivado_timing_device"):
                if fpga.get(device_key):
                    fpga_vivado_devices.add(str(fpga[device_key]))
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
            wns = _as_float(fpga.get("wns_ns"))
            if wns is not None:
                previous = totals["fpga_min_wns_ns"]
                totals["fpga_min_wns_ns"] = wns if previous is None else min(float(previous), wns)
            area = _as_float(asic.get("area"))
            slack = _as_float(asic.get("slack_ns"))
            totals["asic_total_cell_area"] += area if area is not None else 0.0
            if slack is not None:
                previous = totals["asic_min_slack_ns"]
                totals["asic_min_slack_ns"] = slack if previous is None else min(float(previous), slack)
            if asic.get("dc_target_library_discovery") == "real_target_library_present":
                totals["dc_real_target_library_kernel_count"] += 1
            for library in asic.get("dc_target_libraries", []) or []:
                if library:
                    asic_dc_target_libraries.add(str(library))
            source_bundle = _source_bundle_signature(evidence_root, candidate_id, kernel_id)
            candidate_gate_blockers.extend(
                _source_bundle_blockers(
                    source_bundle,
                    candidate_id=candidate_id,
                    kernel_id=kernel_id,
                )
            )
            kernel_rows.append(
                {
                    "kernel_id": kernel_id,
                    "target": kernel_target,
                    "required_stage_ids": required_stage_ids,
                    "stage_verdicts": {
                        stage_id: stages.get(stage_id, {}).get("verdict")
                        for stage_id in required_stage_ids
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
                            "vivado_device",
                            "vivado_utilization_device",
                            "vivado_timing_device",
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
                    "candidate_source_bundle": source_bundle,
                }
            )
        asic_min_slack = totals["asic_min_slack_ns"]
        asic_slack_deficit = max(0.0, -float(asic_min_slack or 0.0))
        required_stage_ids = _ordered_stage_ids(candidate_required_stage_ids or REQUIRED_STAGE_IDS)
        candidate_target = sorted(candidate_targets)[0] if len(candidate_targets) == 1 else _target_from_stage_ids(required_stage_ids)
        fpga_target_model_binding = _fpga_target_model_binding(
            metadata,
            observed_devices=sorted(fpga_vivado_devices),
            required_stage_ids=required_stage_ids,
        )
        if fpga_target_model_binding.get("blocker_id"):
            candidate_ranking_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "blocker_id": fpga_target_model_binding.get("blocker_id"),
                    "binding_status": fpga_target_model_binding.get("status"),
                    "observed_vivado_devices": fpga_target_model_binding.get("observed_vivado_devices", []),
                    "expected_vivado_parts": fpga_target_model_binding.get("expected_vivado_parts", []),
                }
            )
        asic_target_model_binding = _asic_target_model_binding(
            metadata,
            observed_target_libraries=sorted(asic_dc_target_libraries),
            required_stage_ids=required_stage_ids,
        )
        if asic_target_model_binding.get("blocker_id"):
            candidate_ranking_blockers.append(
                {
                    "candidate_id": candidate_id,
                    "stage_id": "dc_asic_synth_timing_area",
                    "blocker_id": asic_target_model_binding.get("blocker_id"),
                    "binding_status": asic_target_model_binding.get("status"),
                    "observed_dc_target_libraries": asic_target_model_binding.get(
                        "observed_dc_target_libraries",
                        [],
                    ),
                    "expected_dc_target_libraries": asic_target_model_binding.get(
                        "expected_dc_target_libraries",
                        [],
                    ),
                }
            )
        candidate_blockers = [*candidate_gate_blockers, *candidate_ranking_blockers]
        parametric_ppa = _candidate_parametric_ppa(
            candidate_id=candidate_id,
            totals={**totals, "asic_slack_deficit_ns": asic_slack_deficit},
            metadata=metadata,
        )
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "design_candidate_id": metadata.get("design_candidate_id"),
                "candidate_identity": base_identity,
                "target_identities": target_identities,
                "target_eligibility": {},
                "candidate_metadata_source": metadata.get("candidate_metadata_source"),
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
                "target": candidate_target,
                "fpga_target_model_binding": fpga_target_model_binding,
                "fpga_vivado_devices": sorted(fpga_vivado_devices),
                "asic_target_model_binding": asic_target_model_binding,
                "asic_dc_target_libraries": sorted(asic_dc_target_libraries),
                "candidate_parametric_ppa": parametric_ppa,
                "candidate_gate_passed": not candidate_gate_blockers,
                "ranking_eligible": not candidate_blockers,
                "fpga_ranking_eligible": False,
                "asic_ranking_eligible": False,
                "blockers": candidate_blockers,
                "gate_blockers": candidate_gate_blockers,
                "ranking_blockers": candidate_ranking_blockers,
                "winner_policy_blockers": [],
                "kernel_rows": kernel_rows,
                **totals,
                "asic_slack_deficit_ns": asic_slack_deficit,
                "kernel_count": len(kernel_ids),
                "required_stage_ids": required_stage_ids,
            }
        )

    winner_policy_blockers = _apply_candidate_parametric_source_policy(candidate_rows)
    for row in candidate_rows:
        _refresh_target_eligibility(row)
        row["ranking_eligible"] = row.get("fpga_ranking_eligible") is True or row.get("asic_ranking_eligible") is True
    eligible_rows = [row for row in candidate_rows if row.get("ranking_eligible")]
    fpga_eligible_rows = _target_ranking_rows(candidate_rows, "fpga")
    asic_eligible_rows = _target_ranking_rows(candidate_rows, "asic")
    physical_metric_signatures = {_candidate_metric_signature(row) for row in eligible_rows}
    all_physical_metric_tied = len(eligible_rows) > 1 and len(physical_metric_signatures) == 1
    parametric_sidecar_available = any(
        isinstance(row.get("candidate_parametric_ppa"), Mapping)
        and row["candidate_parametric_ppa"].get("available") is True
        for row in eligible_rows
    )
    parametric_available = all_physical_metric_tied and parametric_sidecar_available
    if parametric_available:
        metric_signatures = {
            json.dumps(
                row.get("candidate_parametric_ppa", {}).get("attributed_totals", {}),
                sort_keys=True,
            )
            for row in eligible_rows
        }
    else:
        metric_signatures = set(physical_metric_signatures)
    all_metric_tied = len(eligible_rows) > 1 and len(metric_signatures) == 1
    if not eligible_rows and not blockers:
        blockers.append({"blocker_id": "no_ranking_eligible_candidates"})

    fpga_ranking = _rank_with_ties(
        fpga_eligible_rows,
        key=lambda item: (
            _ranking_metric(item, "fpga_total_slice_luts", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_slice_registers", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_dsps", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_block_ram_tiles", parametric_available=parametric_available),
            _ranking_metric(item, "fpga_total_bonded_iob", parametric_available=parametric_available),
            _ranking_metric_desc(item, "fpga_min_wns_ns", parametric_available=parametric_available),
        ),
    )
    asic_ranking = _rank_with_ties(
        asic_eligible_rows,
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
            "evidence_root": {
                "path": str(evidence_root),
                "exists": evidence_root.exists(),
                "role": "raw_candidate_specific_evidence_root",
            },
            "parsed_root": {
                "path": str(parsed_root),
                "exists": parsed_root.exists(),
                "role": "parsed_hard_gate_results_root",
            },
            "gate_adjudication": _source_ref(gate_adjudication_path),
            "candidate_universe_manifest": _source_ref(resolved_candidate_universe_manifest)
            if resolved_candidate_universe_manifest
            else {"path": None, "exists": False, "sha256": None, "hash_algorithm": "sha256"},
            "deployment_hard_gate_execution_queue": _source_ref(
                run_dir / "dft_deployment_hard_gate_execution_queue.json"
            ),
            "deployment_recommendation_plan": _source_ref(
                run_dir / "step3_queue" / "deployment_recommendation_plan.json"
            ),
            "step2_architecture_candidate_set": _source_ref(
                run_dir / "step2" / "architecture_candidate_set.json"
            ),
            "step2_mapping_candidates": _source_ref(
                run_dir / "step2" / "mapping_candidates.jsonl"
            ),
            "candidate_set_consistency": _source_ref(
                run_dir / "dft_candidate_set_consistency.json"
            ),
            "candidate_set_consistency_validation": _source_ref(
                run_dir / "dft_candidate_set_consistency_validation.json"
            ),
            "candidate_specific_evidence_root": _root_ref(evidence_root),
            "parsed_hard_gate_results_root": _root_ref(parsed_root),
            "candidate_metadata_fallback_root": _root_ref(evidence_root),
            "external_deployment_hard_gate_execution_queue": _source_ref(
                evidence_root / "dft_deployment_hard_gate_execution_queue.json"
            ),
            "external_deployment_recommendation_plan": _source_ref(
                evidence_root / "step3_queue" / "deployment_recommendation_plan.json"
            ),
            "external_step2_architecture_candidate_set": _source_ref(
                evidence_root / "step2" / "architecture_candidate_set.json"
            ),
            "external_step2_mapping_candidates": _source_ref(
                evidence_root / "step2" / "mapping_candidates.jsonl"
            ),
        },
        "candidate_metadata_context_available": bool(metadata_by_candidate_id),
        "candidate_set_consistency_gate": candidate_set_consistency_gate,
        "release_gate_validation": release_validation_summary,
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
                "min fpga_total_slice_registers",
                "min fpga_total_dsps",
                "min fpga_total_block_ram_tiles",
                "min fpga_total_bonded_iob",
                "max fpga_min_wns_ns",
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
            "candidate_parametric_source_policy": (
                "Identical generated RTL source signatures or parameter hashes within a "
                "deployment are winner-selection blockers only. They must not hide parsed "
                "hardware PPA ranking rows, but they keep best-architecture proof blocked "
                "until candidate-varying generated RTL/tool evidence exists."
            ),
            "fpga_target_model_binding_policy": (
                "FPGA deployment-profile rows must bind selected_model to the Vivado "
                "part/device observed in timing/utilization reports. Unbound or "
                "mismatched default-part Vivado evidence remains raw progress and is "
                "not ranking-eligible for the deployment target."
            ),
            "asic_target_model_binding_policy": (
                "ASIC deployment-profile rows that require model binding must bind "
                "selected_model to the DC target library observed in timing/area "
                "evidence. Unbound or mismatched default-library DC evidence remains "
                "raw progress and is not ranking-eligible for the deployment target."
            ),
            "winner_policy_blocker_count": len(winner_policy_blockers),
        },
        "winner_selection_status": winner_selection_status,
        "all_candidates_metric_tied": all_metric_tied,
        "all_candidates_physical_metric_tied": all_physical_metric_tied,
        "candidate_parametric_sidecar_available": parametric_sidecar_available,
        "candidate_parametric_attribution_used": False,
        "metric_signature_count": len(metric_signatures),
        "ranking_eligible_candidate_count": len(eligible_rows),
        "fpga_ranking_eligible_candidate_count": len(fpga_eligible_rows),
        "asic_ranking_eligible_candidate_count": len(asic_eligible_rows),
        "blocked_candidate_count": len(candidate_rows) - len(eligible_rows),
        "blockers": blockers,
        "winner_policy_blockers": winner_policy_blockers,
        "winner_policy_blocker_count": len(winner_policy_blockers),
        "fpga_ranking": fpga_ranking,
        "asic_ranking": asic_ranking,
        "candidate_rows": candidate_rows,
        "pareto_frontier": {
            "schema_version": DFT_HARDWARE_PPA_PARETO_SCHEMA,
            "generated_at": _now_iso(),
            "status": "hardware_ppa_pareto_frontier_available" if pareto else "blocked_no_pareto_frontier",
            "objective_sense": {
                "fpga_total_slice_luts": "minimize",
                "fpga_total_slice_registers": "minimize",
                "fpga_total_dsps": "minimize",
                "fpga_total_block_ram_tiles": "minimize",
                "fpga_total_bonded_iob": "minimize",
                "fpga_min_wns_ns": "maximize",
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
    source_artifacts = payload.get("source_artifacts", {})
    universe_ref = (
        source_artifacts.get("candidate_universe_manifest", {})
        if isinstance(source_artifacts, Mapping)
        else {}
    )
    # Deployment/Step2 metadata may be used as target-specific ranking context
    # when a frozen release candidate universe is absent. It remains provenance
    # and never upgrades deliverable-complete claims.
    consistency_gate = payload.get("candidate_set_consistency_gate", {})
    if (
        isinstance(consistency_gate, Mapping)
        and consistency_gate.get("attached") is True
        and consistency_gate.get("passed") is not True
        and consistency_gate.get("ranking_blocking") is not False
        and payload.get("ranking_eligible_candidate_count")
    ):
        errors.append("ranking_candidates_require_passed_candidate_set_consistency")
    expected = int(payload.get("candidate_gate_passed_count", 0) or 0)
    actual = int(payload.get("ranking_eligible_candidate_count", 0) or 0)
    if expected and actual > expected:
        errors.append("ranking_eligible_count_exceeds_candidate_gate_passed_count")
    metadata_context_available = payload.get("candidate_metadata_context_available") is True
    design_by_candidate_id: dict[str, str] = {}
    for row in payload.get("candidate_rows", []) or []:
        if not isinstance(row, Mapping):
            errors.append("candidate_row_not_mapping")
            continue
        candidate_id = str(row.get("candidate_id") or "")
        design_candidate_id = str(row.get("design_candidate_id") or "")
        if candidate_id and design_candidate_id:
            existing_design_id = design_by_candidate_id.get(candidate_id)
            if existing_design_id and existing_design_id != design_candidate_id:
                errors.append(f"{candidate_id}:candidate_rows_design_candidate_id_conflict")
            design_by_candidate_id.setdefault(candidate_id, design_candidate_id)
        target_eligibility = row.get("target_eligibility", {})
        target_has_eligible = False
        if not isinstance(target_eligibility, Mapping):
            errors.append(f"{row.get('candidate_id')}:missing_target_eligibility")
            target_eligibility = {}
        for target in TARGET_REQUIRED_STAGE_IDS:
            target_payload = target_eligibility.get(target, {})
            if not isinstance(target_payload, Mapping):
                errors.append(f"{row.get('candidate_id')}:{target}:missing_target_eligibility")
                continue
            if target_payload.get("ranking_eligible") is True:
                target_has_eligible = True
                if target_payload.get("blockers"):
                    errors.append(f"{row.get('candidate_id')}:{target}:target_eligible_with_blockers")
            for error in validate_candidate_identity(
                target_payload.get("candidate_identity"),
                field_prefix=f"{row.get('candidate_id')}.{target}.candidate_identity",
            ):
                errors.append(f"{row.get('candidate_id')}:{target}:{error.get('field')}")
        if row.get("ranking_eligible") and not target_has_eligible:
            errors.append(f"{row.get('candidate_id')}:ranking_eligible_without_target_eligibility")
        if row.get("ranking_eligible"):
            if metadata_context_available:
                if not row.get("design_candidate_id"):
                    errors.append(f"{row.get('candidate_id')}:missing_design_candidate_id")
                if not isinstance(row.get("assignments"), Mapping) or not row.get("assignments"):
                    errors.append(f"{row.get('candidate_id')}:missing_candidate_assignments")
                metadata = row.get("candidate_metadata", {})
                provenance = metadata.get("provenance", {}) if isinstance(metadata, Mapping) else {}
                # Context-only deployment metadata is acceptable for target-specific
                # PPA ranking order, but remains explicitly marked as non-release
                # universe provenance in the candidate metadata sidecar.
            if (
                row.get("fpga_ranking_eligible") is True
                and int(row.get("vivado_route_completed_kernel_count", 0) or 0)
                != int(row.get("kernel_count", 0) or 0)
            ):
                errors.append(f"{row.get('candidate_id')}:missing_vivado_route_kernel")
            if (
                row.get("asic_ranking_eligible") is True
                and int(row.get("dc_real_target_library_kernel_count", 0) or 0)
                != int(row.get("kernel_count", 0) or 0)
            ):
                errors.append(f"{row.get('candidate_id')}:missing_dc_real_target_library_kernel")
        parametric = row.get("candidate_parametric_ppa", {})
        if isinstance(parametric, Mapping) and parametric.get("candidate_id_used_as_factor") is True:
            errors.append(f"{row.get('candidate_id')}:candidate_id_used_as_parametric_factor")
    for ranking_name in ("fpga_ranking", "asic_ranking"):
        ranking_rows = payload.get(ranking_name, [])
        if not isinstance(ranking_rows, list):
            continue
        for row in ranking_rows:
            if not isinstance(row, Mapping):
                errors.append(f"{ranking_name}:ranking_row_not_mapping")
                continue
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                continue
            expected_design_id = design_by_candidate_id.get(candidate_id)
            if design_by_candidate_id and not expected_design_id:
                errors.append(f"{ranking_name}:{candidate_id}:ranked_candidate_missing_from_candidate_rows")
                continue
            actual_design_id = row.get("design_candidate_id")
            if expected_design_id and actual_design_id != expected_design_id:
                errors.append(f"{ranking_name}:{candidate_id}:design_candidate_id_mismatch")
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
    evidence_root: Path | None = None,
    parsed_root: Path | None = None,
    candidate_universe_manifest: Optional[Path] = None,
) -> Dict[str, Any]:
    """Write hardware PPA ranking, Pareto, validation, and status artifacts."""

    run_dir = Path(run_dir)
    evidence_root = Path(evidence_root or run_dir)
    parsed_root = Path(parsed_root or evidence_root)
    ranking = build_dft_hardware_ppa_ranking(
        run_dir,
        evidence_root=evidence_root,
        parsed_root=parsed_root,
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
