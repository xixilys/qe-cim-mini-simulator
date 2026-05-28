#!/usr/bin/env python3
"""Fail-closed FPGA/ASIC deployment target selection for DFT/QE.

This DFT-profile helper records the deployment *context* needed before a final
FPGA/ASIC recommendation can be made: an FPGA part/SKU under the declared
budget policy and an ASIC target library/process/PVT context.  It is not PPA,
winner, or deliverable-completion evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA = (
    "dse.dft.hardware_deployment_target_selection.v1"
)
DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_VALIDATION_SCHEMA = (
    "dse.dft.hardware_deployment_target_selection_validation.v1"
)
DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_STATUS_SCHEMA = (
    "dse.dft.hardware_deployment_target_selection_status.v1"
)

_DEPLOYMENTS = ("fpga", "asic")
_READY_STATUSES = {"selected", "passed", "ready", "target_selected"}
_FORBIDDEN_SHORTCUTS = (
    "target selection treated as candidate PPA evidence",
    "tool availability treated as ASIC target-library timing/area evidence",
    "FPGA part selected without source refs for current capacity",
    "ASIC library selected without source refs for library/process/PVT",
    "deployment target context used to name final FPGA/ASIC recommendation",
)
_SOURCE_REF_KEYS = (
    "source_refs",
    "raw_source_refs",
    "vendor_source_refs",
    "catalog_source_refs",
    "probe_source_refs",
    "tool_source_refs",
)
_PLACEHOLDER_TOKENS = (
    "placeholder",
    "synthetic_placeholder",
    "generated_synthetic",
    "generated_placeholder",
    "mock",
    "toy",
)
_PLACEHOLDER_KEY_FRAGMENTS = (
    "status",
    "source",
    "source_kind",
    "provenance",
    "target",
    "device",
    "part",
    "library",
    "claim_role",
    "claim_level",
)
_CLAIM_BOUNDARY = (
    "DFT hardware deployment target selection records FPGA part/SKU and ASIC "
    "library/process/PVT context for later targeted full-SCF accounting. It is "
    "planning context only: it does not run Vivado/DC, does not provide "
    "candidate-specific PPA, does not name architecture winners, and cannot mark "
    "a targeted deployment recommendation or deliverable completion ready."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return {}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path | None, *, required: bool) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "required": required,
            "exists": False,
            "status": "missing_required" if required else "not_attached",
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    return {
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "status": "present_hash_valid" if exists else "missing_required" if required else "not_attached",
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
    }


def _source_ref_is_fresh(ref: Mapping[str, Any]) -> bool:
    return (
        bool(ref.get("path"))
        and ref.get("exists") is True
        and ref.get("status") == "present_hash_valid"
        and isinstance(ref.get("sha256"), str)
        and bool(ref.get("sha256"))
        and ref.get("hash_algorithm", "sha256") == "sha256"
    )


def _fresh_source_refs(refs: Any) -> list[Dict[str, Any]]:
    if not isinstance(refs, list):
        return []
    return [
        dict(ref)
        for ref in refs
        if isinstance(ref, Mapping) and _source_ref_is_fresh(ref)
    ]


def _source_refs_are_fresh(refs: Any) -> bool:
    if not isinstance(refs, list) or not refs:
        return False
    return len(_fresh_source_refs(refs)) == len(refs)


def _rows(payload: Mapping[str, Any], keys: Sequence[str]) -> list[Dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _as_source_refs(
    item: Mapping[str, Any],
    *,
    fallback_refs: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    refs = [
        dict(ref)
        for ref in item.get("source_refs", []) or []
        if isinstance(ref, Mapping)
    ]
    fresh_refs = _fresh_source_refs(refs)
    if fresh_refs:
        return fresh_refs
    fallback = [dict(ref) for ref in fallback_refs if _source_ref_is_fresh(ref)]
    if fallback:
        return fallback
    return []


def _declared_source_refs(payload: Mapping[str, Any], row_keys: Sequence[str]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    for key in _SOURCE_REF_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            refs.extend(dict(ref) for ref in value if isinstance(ref, Mapping))
        elif isinstance(value, Mapping):
            refs.append(dict(value))
    for row in _rows(payload, row_keys):
        for key in _SOURCE_REF_KEYS:
            value = row.get(key)
            if isinstance(value, list):
                refs.extend(dict(ref) for ref in value if isinstance(ref, Mapping))
            elif isinstance(value, Mapping):
                refs.append(dict(value))
    return refs


def _placeholder_marker_reasons(value: Any, *, path: str = "$") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            lowered_key = key_text.lower()
            if lowered_key in {"claim_boundary", "selection_rationale", "pvt_selection_policy"}:
                continue
            nested_path = f"{path}.{key_text}"
            if isinstance(nested, (Mapping, list)):
                reasons.extend(_placeholder_marker_reasons(nested, path=nested_path))
                continue
            if not any(fragment in lowered_key for fragment in _PLACEHOLDER_KEY_FRAGMENTS):
                continue
            lowered_value = str(nested or "").strip().lower()
            if any(token in lowered_value for token in _PLACEHOLDER_TOKENS):
                reasons.append(nested_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(_placeholder_marker_reasons(item, path=f"{path}[{index}]"))
    return reasons


def _resolve_ref_path(path_text: str, *, base_dir: Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _paths_match(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _verified_raw_source_refs(
    refs: Sequence[Mapping[str, Any]],
    *,
    artifact_path: Path,
) -> tuple[list[Dict[str, Any]], int, int]:
    verified: list[Dict[str, Any]] = []
    self_ref_count = 0
    stale_ref_count = 0
    base_dir = artifact_path.parent
    for ref in refs:
        path_text = str(ref.get("path") or "").strip()
        if not path_text:
            stale_ref_count += 1
            continue
        ref_path = _resolve_ref_path(path_text, base_dir=base_dir)
        if _paths_match(ref_path, artifact_path):
            self_ref_count += 1
            continue
        if not ref_path.exists() or not ref_path.is_file():
            stale_ref_count += 1
            continue
        if ref.get("hash_algorithm", "sha256") != "sha256":
            stale_ref_count += 1
            continue
        declared_sha = ref.get("sha256")
        if not isinstance(declared_sha, str) or not declared_sha:
            stale_ref_count += 1
            continue
        current_sha = sha256_file(ref_path)
        if declared_sha != current_sha:
            stale_ref_count += 1
            continue
        normalized = dict(ref)
        normalized.update({
            "path": str(ref_path),
            "exists": True,
            "status": "present_hash_valid",
            "sha256": current_sha,
            "hash_algorithm": "sha256",
        })
        verified.append(normalized)
    return verified, self_ref_count, stale_ref_count


def _target_input_gate(
    *,
    payload: Mapping[str, Any],
    artifact_path: Path,
    trust_class: str,
    row_keys: Sequence[str],
) -> Dict[str, Any]:
    if not payload:
        return {
            "trust_class": trust_class,
            "trusted": False,
            "source_refs": [],
            "blockers": [],
        }
    blockers: list[Dict[str, Any]] = []
    placeholder_reasons = _placeholder_marker_reasons(payload)
    if placeholder_reasons:
        blockers.append({
            "blocker_id": f"{trust_class}_placeholder_input",
            "placeholder_fields": placeholder_reasons,
        })
    declared_refs = _declared_source_refs(payload, row_keys)
    verified_refs, self_ref_count, stale_ref_count = _verified_raw_source_refs(
        declared_refs,
        artifact_path=artifact_path,
    )
    if not verified_refs:
        if not declared_refs or self_ref_count:
            blocker_id = f"{trust_class}_self_hashed_without_raw_source_refs"
        else:
            blocker_id = f"{trust_class}_missing_trusted_raw_source_refs"
        blockers.append({
            "blocker_id": blocker_id,
            "declared_source_ref_count": len(declared_refs),
            "self_source_ref_count": self_ref_count,
            "stale_source_ref_count": stale_ref_count,
        })
    return {
        "trust_class": trust_class,
        "trusted": not blockers,
        "source_ref_count": len(verified_refs),
        "source_refs": verified_refs,
        "blockers": blockers,
    }


def _capacity_value(capacity: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = capacity.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ""))
            except ValueError:
                continue
    return 0.0


def _fpga_capacity_score(item: Mapping[str, Any]) -> tuple[float, float, float, float]:
    capacity = item.get("capacity", {})
    if not isinstance(capacity, Mapping):
        capacity = {}
    return (
        _capacity_value(capacity, "slice_luts", "luts", "logic_cells", "lut"),
        _capacity_value(capacity, "dsps", "dsp", "dsp_slices"),
        _capacity_value(capacity, "block_ram_tiles", "bram", "brams", "bram_tiles"),
        _capacity_value(capacity, "hbm_gb", "memory_gb", "dram_gb"),
    )


def _tool_available(tool_availability: Mapping[str, Any], tool: str) -> bool | None:
    rows = tool_availability.get("tool_rows", [])
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("tool", "")).lower() == tool.lower():
            return row.get("available") is True
    return None


def _normalize_fpga_target(
    row: Mapping[str, Any],
    *,
    fallback_source_refs: Sequence[Mapping[str, Any]],
    budget_policy: str,
) -> Dict[str, Any]:
    capacity = row.get("capacity", {})
    if not isinstance(capacity, Mapping):
        capacity = {}
    return {
        "selection_status": "selected",
        "target_device_id": row.get("target_device_id") or row.get("device_id") or row.get("id") or row.get("part"),
        "vendor": row.get("vendor"),
        "part": row.get("part") or row.get("sku"),
        "family": row.get("family") or row.get("device_family"),
        "budget_policy": budget_policy,
        "capacity": dict(capacity),
        "capacity_units": row.get("capacity_units") or "vendor_catalog_native_units",
        "source_refs": _as_source_refs(row, fallback_refs=fallback_source_refs),
        "input_trust_class": "fpga_target_catalog",
        "selection_rationale": (
            "unbounded budget policy selects the highest-capacity catalog row "
            "by LUT/logic, DSP, BRAM, and memory tuple; this is target context only."
        ),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _normalize_asic_target(
    row: Mapping[str, Any],
    *,
    fallback_source_refs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "selection_status": "selected",
        "target_library_id": row.get("target_library_id") or row.get("library_id") or row.get("name"),
        "process_node": row.get("process_node") or row.get("node") or "library_defined",
        "pvt_corner": row.get("pvt_corner") or row.get("corner"),
        "voltage_v": row.get("voltage_v") or row.get("voltage"),
        "temperature_c": row.get("temperature_c") or row.get("temperature"),
        "source_refs": _as_source_refs(row, fallback_refs=fallback_source_refs),
        "input_trust_class": "asic_target_library_probe",
        "preferred": row.get("preferred") is True,
        "pvt_selection_policy": (
            "prefer explicit preferred row, then nominal/typical TT corner, "
            "then deterministic library id"
        ),
        "selection_rationale": (
            "ASIC target selection records the real target library/process/PVT "
            "context discovered by an explicit probe and prefers nominal/typical "
            "TT context when multiple process corners are available; it is not "
            "timing/area PPA."
        ),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _asic_target_preference_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    """Return a deterministic selection key for target-library planning.

    ASIC deployment target context should default to the nominal/typical PVT
    corner rather than accidentally selecting a fast or slow corner only because
    its library id sorts first.  This remains planning context; per-candidate DC
    timing/area still has to run against the selected library before any ASIC
    PPA claim is allowed.
    """

    target_id = str(
        row.get("target_library_id")
        or row.get("library_id")
        or row.get("name")
        or ""
    )
    corner_text = " ".join(
        str(row.get(key) or "")
        for key in (
            "pvt_corner",
            "corner",
            "target_library_id",
            "library_id",
            "name",
        )
    ).lower()
    if row.get("preferred") is True:
        preferred_rank = 0
    else:
        preferred_rank = 1
    if "tt" in corner_text or "typical" in corner_text or "nominal" in corner_text:
        pvt_rank = 0
    elif "ff" in corner_text or "fast" in corner_text:
        pvt_rank = 1
    elif "ss" in corner_text or "slow" in corner_text:
        pvt_rank = 2
    else:
        pvt_rank = 3
    return (preferred_rank, pvt_rank, target_id)


def _blocked_deployment(deployment: str, blockers: Sequence[Mapping[str, Any]], *, budget_policy: str) -> Dict[str, Any]:
    required_artifact = (
        "fpga_target_catalog.json with current FPGA part/SKU capacity rows"
        if deployment == "fpga"
        else "asic_target_library_probe.json with target library/process/PVT rows"
    )
    return {
        "selection_status": "blocked_target_selection_required",
        "deployment": deployment,
        "budget_policy": budget_policy if deployment == "fpga" else None,
        "blockers": [dict(item) for item in blockers],
        "required_next_evidence": [
            {
                "task_id": f"{deployment}_build_deployment_target_selection_inputs",
                "deployment": deployment,
                "reason": blockers[0].get("blocker_id") if blockers else "target_selection_missing",
                "required_artifacts": [required_artifact],
                "acceptance_checks": [
                    "artifact has source refs/hash-backed provenance",
                    "selected target has all required fields",
                    "selection remains planning context and does not name final deployment winners",
                ],
                "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
            }
        ],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _select_fpga(
    *,
    catalog: Mapping[str, Any],
    input_gate: Mapping[str, Any],
    budget_policy: str,
) -> Dict[str, Any]:
    blockers: list[Dict[str, Any]] = []
    if not catalog:
        blockers.append({"blocker_id": "fpga_target_catalog_missing"})
    blockers.extend(
        dict(blocker)
        for blocker in input_gate.get("blockers", []) or []
        if isinstance(blocker, Mapping)
    )
    rows = _rows(catalog, ("targets", "devices", "fpga_targets"))
    if catalog and not rows:
        blockers.append({"blocker_id": "fpga_target_catalog_has_no_targets"})
    legal_rows = [
        row
        for row in rows
        if (row.get("status") in (None, "", "available", "candidate", "supported", "selected"))
    ]
    if rows and not legal_rows:
        blockers.append({"blocker_id": "fpga_target_catalog_has_no_available_targets"})
    if blockers:
        return _blocked_deployment("fpga", blockers, budget_policy=budget_policy)
    selected = sorted(
        legal_rows,
        key=lambda row: (_fpga_capacity_score(row), str(row.get("target_device_id") or row.get("part") or "")),
        reverse=True,
    )[0]
    item = _normalize_fpga_target(
        selected,
        fallback_source_refs=[
            dict(ref)
            for ref in input_gate.get("source_refs", []) or []
            if isinstance(ref, Mapping)
        ],
        budget_policy=budget_policy,
    )
    missing = [
        field
        for field in ("target_device_id", "vendor", "part")
        if item.get(field) in (None, "", [])
    ]
    if missing:
        return _blocked_deployment(
            "fpga",
            [{"blocker_id": "fpga_target_missing_required_fields", "missing_fields": missing}],
            budget_policy=budget_policy,
        )
    if not item.get("source_refs"):
        return _blocked_deployment(
            "fpga",
            [{"blocker_id": "fpga_target_missing_source_refs"}],
            budget_policy=budget_policy,
        )
    return item


def _select_asic(
    *,
    probe: Mapping[str, Any],
    tool_availability: Mapping[str, Any],
    input_gate: Mapping[str, Any],
) -> Dict[str, Any]:
    blockers: list[Dict[str, Any]] = []
    dc_available = _tool_available(tool_availability, "dc_shell")
    if dc_available is False:
        blockers.append({"blocker_id": "dc_shell_unavailable_for_target_library_probe"})
    if not probe:
        blockers.append({"blocker_id": "asic_target_library_probe_missing"})
    blockers.extend(
        dict(blocker)
        for blocker in input_gate.get("blockers", []) or []
        if isinstance(blocker, Mapping)
    )
    rows = _rows(probe, ("target_libraries", "libraries", "targets", "library_rows"))
    if probe and not rows:
        single = {
            key: probe.get(key)
            for key in (
                "target_library_id",
                "library_id",
                "name",
                "process_node",
                "node",
                "pvt_corner",
                "corner",
                "voltage_v",
                "temperature_c",
                "source_refs",
            )
            if key in probe
        }
        if single:
            rows = [single]
    if probe and not rows:
        blockers.append({"blocker_id": "asic_target_library_probe_has_no_libraries"})
    real_rows = [
        row
        for row in rows
        if str(row.get("discovery_status") or row.get("status") or "passed").lower()
        in {"passed", "available", "real_target_library_present", "selected", "target_selected"}
    ]
    if rows and not real_rows:
        blockers.append({"blocker_id": "asic_target_library_not_real_or_available"})
    if blockers:
        return _blocked_deployment("asic", blockers, budget_policy="")
    selected = sorted(real_rows, key=_asic_target_preference_key)[0]
    item = _normalize_asic_target(
        selected,
        fallback_source_refs=[
            dict(ref)
            for ref in input_gate.get("source_refs", []) or []
            if isinstance(ref, Mapping)
        ],
    )
    missing = [
        field
        for field in ("target_library_id", "process_node", "pvt_corner")
        if item.get(field) in (None, "", [])
    ]
    if missing:
        return _blocked_deployment(
            "asic",
            [{"blocker_id": "asic_target_missing_required_fields", "missing_fields": missing}],
            budget_policy="",
        )
    if not item.get("source_refs"):
        return _blocked_deployment(
            "asic",
            [{"blocker_id": "asic_target_missing_source_refs"}],
            budget_policy="",
        )
    return item


def _deployment_ready(item: Mapping[str, Any], required_fields: Sequence[str]) -> bool:
    return (
        str(item.get("selection_status") or "").lower() in _READY_STATUSES
        and all(item.get(field) not in (None, "", []) for field in required_fields)
        and _source_refs_are_fresh(item.get("source_refs"))
    )


def build_dft_hardware_deployment_target_selection(
    run_dir: Path,
    *,
    fpga_target_catalog_path: Path | None = None,
    asic_target_library_probe_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    budget_policy: str = "unbounded_budget_current_catalog_required",
) -> Dict[str, Any]:
    """Build a fail-closed target-selection artifact from explicit source refs."""

    run_dir = Path(run_dir)
    fpga_path = Path(fpga_target_catalog_path) if fpga_target_catalog_path else run_dir / "fpga_target_catalog.json"
    asic_path = Path(asic_target_library_probe_path) if asic_target_library_probe_path else run_dir / "asic_target_library_probe.json"
    tool_path = Path(ic_eda_tool_availability_path) if ic_eda_tool_availability_path else run_dir / "ic_eda_tool_availability.json"
    source_artifacts = {
        "fpga_target_catalog": _source_ref(fpga_path, required=True),
        "asic_target_library_probe": _source_ref(asic_path, required=True),
        "ic_eda_tool_availability": _source_ref(tool_path, required=False),
    }
    fpga_catalog = _load_json(fpga_path)
    asic_probe = _load_json(asic_path)
    tool_availability = _load_json(tool_path)
    fpga_input_gate = _target_input_gate(
        payload=fpga_catalog,
        artifact_path=fpga_path,
        trust_class="fpga_target_catalog",
        row_keys=("targets", "devices", "fpga_targets"),
    )
    asic_input_gate = _target_input_gate(
        payload=asic_probe,
        artifact_path=asic_path,
        trust_class="asic_target_library_probe",
        row_keys=("target_libraries", "libraries", "targets", "library_rows"),
    )
    fpga = _select_fpga(
        catalog=fpga_catalog,
        input_gate=fpga_input_gate,
        budget_policy=budget_policy,
    )
    asic = _select_asic(
        probe=asic_probe,
        tool_availability=tool_availability,
        input_gate=asic_input_gate,
    )
    fpga_ready = _deployment_ready(fpga, ("target_device_id", "part", "vendor"))
    asic_ready = _deployment_ready(asic, ("target_library_id", "process_node", "pvt_corner"))
    blockers: list[Dict[str, Any]] = []
    for deployment, item in (("fpga", fpga), ("asic", asic)):
        for blocker in item.get("blockers", []) or []:
            if isinstance(blocker, Mapping):
                blockers.append({"deployment": deployment, **dict(blocker)})
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA,
        "generated_at": _now_iso(),
        "status": "target_selection_ready" if fpga_ready and asic_ready else "target_selection_required",
        "budget_policy": budget_policy,
        "selection_policy": {
            "fpga": "unbounded_budget_highest_capacity_catalog_row",
            "asic": "explicit_preferred_or_nominal_tt_real_target_library_probe_row",
            "candidate_ppa_or_winner_evidence": False,
        },
        "input_trust_gates": {
            "fpga_target_catalog": fpga_input_gate,
            "asic_target_library_probe": asic_input_gate,
        },
        "source_artifacts": source_artifacts,
        "deployments": {
            "fpga": fpga,
            "asic": asic,
        },
        "deployment_target_selection_ready": bool(fpga_ready and asic_ready),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "forbidden_shortcuts": list(_FORBIDDEN_SHORTCUTS),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _contains_reserved_winner_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in {
                "winner",
                "winner_candidate_id",
                "best_architecture",
                "fpga_best_architecture",
                "asic_best_architecture",
                "named_winner",
            }:
                return True
            if _contains_reserved_winner_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_reserved_winner_key(item) for item in value)
    return False


def validate_dft_hardware_deployment_target_selection(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate target-selection consistency without upgrading final claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("can_name_targeted_deployment_recommendation") is True:
        errors.append("target_selection_must_not_mark_targeted_recommendation_ready")
    if payload.get("can_name_final_recommendation") is True:
        errors.append("target_selection_must_not_mark_final_recommendation_ready")
    if payload.get("trusted_final_claim") is True:
        errors.append("target_selection_must_not_mark_trusted_final_claim")
    if payload.get("hardware_completion_eligible") is True:
        errors.append("target_selection_must_not_mark_hardware_completion_eligible")
    if payload.get("deliverable_complete") is True:
        errors.append("target_selection_must_not_mark_deliverable_complete")
    if _contains_reserved_winner_key(payload):
        errors.append("target_selection_must_not_name_winners")
    deployments = payload.get("deployments", {})
    if not isinstance(deployments, Mapping):
        errors.append("deployments_missing_or_not_mapping")
        deployments = {}
    input_trust_gates = payload.get("input_trust_gates", {})
    if not isinstance(input_trust_gates, Mapping):
        errors.append("input_trust_gates_missing_or_not_mapping")
        input_trust_gates = {}
    ready_flags = []
    for deployment, required_fields in (
        ("fpga", ("target_device_id", "part", "vendor")),
        ("asic", ("target_library_id", "process_node", "pvt_corner")),
    ):
        item = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
        gate = input_trust_gates.get(
            "fpga_target_catalog" if deployment == "fpga" else "asic_target_library_probe",
            {},
        )
        if not isinstance(item, Mapping):
            errors.append(f"{deployment}_target_selection_not_mapping")
            ready_flags.append(False)
            continue
        selected = str(item.get("selection_status") or "").lower() in _READY_STATUSES
        if selected and not (isinstance(gate, Mapping) and gate.get("trusted") is True):
            errors.append(f"{deployment}_selected_target_has_untrusted_input_gate")
        ready = _deployment_ready(item, required_fields)
        ready_flags.append(ready)
        if selected and not ready:
            missing = [
                field
                for field in required_fields
                if item.get(field) in (None, "", [])
            ]
            if missing:
                errors.append(f"{deployment}_selected_target_missing_required_fields")
            source_refs = item.get("source_refs")
            if not source_refs:
                errors.append(f"{deployment}_selected_target_missing_source_refs")
            elif not _source_refs_are_fresh(source_refs):
                errors.append(f"{deployment}_selected_target_stale_source_refs")
        if not selected and not item.get("blockers"):
            errors.append(f"{deployment}_blocked_target_without_blockers")
        if item.get("deliverable_complete") is True:
            errors.append(f"{deployment}_target_must_not_mark_deliverable_complete")
        if item.get("hardware_completion_eligible") is True:
            errors.append(f"{deployment}_target_must_not_mark_hardware_completion_eligible")
    if payload.get("deployment_target_selection_ready") is True and not all(ready_flags):
        errors.append("target_selection_ready_without_all_deployments_ready")
    if payload.get("status") == "target_selection_ready" and not all(ready_flags):
        errors.append("ready_status_without_all_deployments_ready")
    if payload.get("status") == "target_selection_required" and not payload.get("blockers"):
        errors.append("blocked_status_without_blockers")
    return {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_deployment_target_selection(
    run_dir: Path,
    *,
    fpga_target_catalog_path: Path | None = None,
    asic_target_library_probe_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    budget_policy: str = "unbounded_budget_current_catalog_required",
) -> Dict[str, Any]:
    """Write target-selection, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_dft_hardware_deployment_target_selection(
        run_dir,
        fpga_target_catalog_path=fpga_target_catalog_path,
        asic_target_library_probe_path=asic_target_library_probe_path,
        ic_eda_tool_availability_path=ic_eda_tool_availability_path,
        budget_policy=budget_policy,
    )
    validation = validate_dft_hardware_deployment_target_selection(payload)
    write_json(run_dir / "dft_hardware_deployment_target_selection.json", payload)
    write_json(run_dir / "dft_hardware_deployment_target_selection_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "target_selection_status": payload.get("status"),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "deliverable_complete": False,
        "blocker_count": payload.get("blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_hardware_deployment_target_selection_status.json", status)
    return {
        "schema_version": "dse.dft.hardware_deployment_target_selection_artifact_status.v1",
        "status": status["status"],
        "target_selection": str(run_dir / "dft_hardware_deployment_target_selection.json"),
        "target_selection_validation": str(run_dir / "dft_hardware_deployment_target_selection_validation.json"),
        "target_selection_status": str(run_dir / "dft_hardware_deployment_target_selection_status.json"),
        "deployment_target_selection_ready": payload.get("deployment_target_selection_ready"),
        "can_name_targeted_deployment_recommendation": False,
        "can_name_final_recommendation": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_STATUS_SCHEMA",
    "DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_VALIDATION_SCHEMA",
    "build_dft_hardware_deployment_target_selection",
    "validate_dft_hardware_deployment_target_selection",
    "write_dft_hardware_deployment_target_selection",
]
