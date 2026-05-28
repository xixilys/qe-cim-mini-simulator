#!/usr/bin/env python3
"""Replayable deployment target-model selection for DFT/QE hardware DSE.

This artifact is an admission/provenance bridge between Step4 deployment
planning and candidate-specific hard-gate execution.  It chooses the model
that should be checked by the target-model binding gate, but it never claims
Vivado/DC support, timing closure, PPA, a deployment winner, or deliverable
completion.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_SCHEMA = (
    "dse.dft.deployment_target_model_selection.v1"
)
DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_VALIDATION_SCHEMA = (
    "dse.dft.deployment_target_model_selection_validation.v1"
)
DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_STATUS_SCHEMA = (
    "dse.dft.deployment_target_model_selection_status.v1"
)

_CLAIM_BOUNDARY = (
    "Deployment target-model selection is a replayable admission decision only. "
    "It can bind the intended FPGA/ASIC model for later support checks, but it "
    "does not prove Vivado/DC support, PPA, timing closure, winner selection, "
    "hardware completion, or deliverable completion."
)

_DEFAULT_MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "amd_alveo_u280_a_u280": {
        "model_id": "amd_alveo_u280_a_u280",
        "vendor": "AMD",
        "board_or_device_model": "AMD Alveo U280 Data Center Accelerator Card",
        "part_number": "A-U280",
        "device_family": "Xilinx UltraScale+ XCU280 HBM FPGA",
        "memory_capacity_bytes": 8 * 1024**3,
        "memory_bandwidth_gbps": 460,
        "vivado_part": "xcu280-fsvh2892-2L-e",
        "vivado_board_part": None,
        "claim_level": "deployment_target_planned_not_locally_closed",
        "source_refs": [
            "AMD Alveo U280 UG1314 reconfigurable acceleration stack user guide",
            "AMD DS963 Alveo U280 Data Center Accelerator Card Data Sheet",
        ],
    },
    "amd_alveo_u50_a_u50_p00g_pq_g": {
        "model_id": "amd_alveo_u50_a_u50_p00g_pq_g",
        "vendor": "AMD",
        "board_or_device_model": "AMD Alveo U50 Data Center Accelerator Card",
        "part_number": "A-U50-P00G-PQ-G",
        "device_family": "Xilinx UltraScale+ XCU50 HBM FPGA",
        "memory_capacity_bytes": 8 * 1024**3,
        "memory_bandwidth_gbps": 316,
        "vivado_part": "xcu50-fsvh2104-2-e",
        "vivado_board_part": None,
        "claim_level": "deployment_target_planned_not_locally_closed",
        "source_refs": [
            "AMD Alveo U50 UG1371 reconfigurable acceleration stack user guide",
            "AMD DS965 Alveo U50 Data Center Accelerator Card Data Sheet",
        ],
    },
    "artix7_xc7a35t_smoke": {
        "model_id": "artix7_xc7a35t_smoke",
        "vendor": "AMD/Xilinx",
        "board_or_device_model": "Artix-7 XC7A35T local smoke/progress target",
        "part_number": "XC7A35T-CSG324-1",
        "memory_capacity_bytes": 0,
        "memory_bandwidth_gbps": 0,
        "vivado_part": "xc7a35tcsg324-1",
        "claim_level": "smoke_progress_only_not_hbm_alveo_deployment",
        "deployment_equivalent_to_hbm_alveo": False,
        "local_tool_closure_scope": "vivado_smoke_progress_only",
        "source_refs": [
            "Local Vivado 2019.1 get_parts probe for xc7a35tcsg324-1",
        ],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _deployment_plan_path(run_dir: Path, deployment_plan_path: Path | None) -> Path:
    if deployment_plan_path is not None:
        return Path(deployment_plan_path)
    for candidate in (
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        run_dir / "deployment_recommendation_plan.json",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return run_dir / "deployment_recommendation_plan.json"


def _deployment_candidate_id(item: Mapping[str, Any]) -> str:
    return str(item.get("candidate_id") or item.get("architecture_id") or "").strip()


def _hard_gate_items(plan: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows = plan.get("hard_gate_work_items", [])
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _recommended_model_candidates(profile: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows = [
        dict(row)
        for row in profile.get("recommended_model_candidates", []) or []
        if isinstance(row, Mapping)
    ]
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("rank", 1_000_000) or 1_000_000),
            str(row.get("model_id") or ""),
        ),
    )


def _normalize_tool_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _model_vivado_parts(model: Mapping[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("vivado_part", "vivado_device"):
        value = model.get(key)
        if value:
            parts.append(str(value))
    return sorted(dict.fromkeys(parts))


def _model_matches_supported_vivado_part(
    model: Mapping[str, Any],
    supported_parts: Sequence[str],
) -> bool:
    normalized_supported = {
        _normalize_tool_part(part)
        for part in supported_parts
        if _normalize_tool_part(part)
    }
    if not normalized_supported:
        return False
    normalized_model_parts = {
        _normalize_tool_part(part)
        for part in _model_vivado_parts(model)
        if _normalize_tool_part(part)
    }
    return bool(normalized_model_parts.intersection(normalized_supported))


def _local_vivado_supported_fpga_model(
    profile: Mapping[str, Any],
    supported_parts: Sequence[str],
) -> tuple[Dict[str, Any], str, str]:
    """Select an FPGA model whose Vivado part was explicitly probe-supported.

    This is intentionally opt-in: the default unlimited-budget FPGA target
    remains the HBM Alveo model, while local tool closure can select a clearly
    labeled smoke/progress part when a real Vivado probe only supports that
    part.  The returned model remains admission evidence only.
    """

    for candidate in _recommended_model_candidates(profile):
        if _model_matches_supported_vivado_part(candidate, supported_parts):
            return (
                dict(candidate),
                "deployment_plan_recommended_model_candidates_vivado_supported_part",
                "selected_recommended_vivado_supported_model_pending_binding",
            )
    for model in sorted(
        _DEFAULT_MODEL_CATALOG.values(),
        key=lambda row: str(row.get("model_id") or ""),
    ):
        if _model_matches_supported_vivado_part(model, supported_parts):
            return (
                dict(model),
                "builtin_dft_model_catalog_vivado_supported_part",
                "selected_local_vivado_supported_model_pending_binding",
            )
    return {}, "missing", "blocked_no_vivado_supported_fpga_model"


def _preferred_model_id(
    target: str,
    profile: Mapping[str, Any],
    selected_model_ids: Mapping[str, str],
) -> str:
    if selected_model_ids.get(target):
        return str(selected_model_ids[target])
    recommended = profile.get("recommended_model_selection", {})
    if isinstance(recommended, Mapping) and recommended.get("recommended_model_id"):
        return str(recommended["recommended_model_id"])
    candidates = _recommended_model_candidates(profile)
    if candidates and candidates[0].get("model_id"):
        return str(candidates[0]["model_id"])
    if target == "fpga":
        return "amd_alveo_u280_a_u280"
    return ""


def _selected_model_from_profile_or_catalog(
    *,
    target: str,
    profile: Mapping[str, Any],
    selected_model_ids: Mapping[str, str],
    fpga_vivado_supported_parts: Sequence[str],
    prefer_fpga_model_with_supported_vivado_part: bool,
) -> tuple[Dict[str, Any], str, str]:
    existing = profile.get("selected_model")
    if isinstance(existing, Mapping) and existing:
        return (
            dict(existing),
            "explicit_target_execution_profile",
            "selected_model_already_present",
        )

    if (
        target == "fpga"
        and prefer_fpga_model_with_supported_vivado_part
        and not selected_model_ids.get(target)
        and fpga_vivado_supported_parts
    ):
        selected, source, status = _local_vivado_supported_fpga_model(
            profile,
            fpga_vivado_supported_parts,
        )
        if selected:
            return selected, source, status

    preferred_id = _preferred_model_id(target, profile, selected_model_ids)
    for candidate in _recommended_model_candidates(profile):
        if preferred_id and candidate.get("model_id") != preferred_id:
            continue
        return (
            dict(candidate),
            "deployment_plan_recommended_model_candidates",
            "selected_recommended_model_pending_local_binding",
        )
    if preferred_id in _DEFAULT_MODEL_CATALOG:
        return (
            dict(_DEFAULT_MODEL_CATALOG[preferred_id]),
            "builtin_dft_model_catalog",
            "selected_catalog_model_pending_local_binding",
        )
    return {}, "missing", "blocked_no_selected_or_recommended_model"


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


def _corner_fields_from_dc_library_name(library_name: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    match = re.search(r"(tt|ff|ss)([0-9]+(?:p[0-9]+)?)v(m?[0-9]+)c", library_name.lower())
    if match:
        corner, voltage_text, temp_text = match.groups()
        fields["voltage_corner"] = f"{voltage_text.replace('p', '.')}V"
        fields["temperature_corner"] = f"{'-' if temp_text.startswith('m') else ''}{temp_text.lstrip('m')}C"
        fields["process_corner"] = corner
    if "_" in library_name:
        fields["process_node"] = library_name.split("_", 1)[0]
    return fields


def _infer_asic_selected_model_from_dc_probe(
    dc_supported_target_libraries: Sequence[str],
    dc_library_db_paths: Sequence[str],
) -> Dict[str, Any]:
    path_by_name: Dict[str, str] = {}
    for path_text in dc_library_db_paths:
        library_name = _library_name_from_path_or_name(path_text)
        if library_name:
            path_by_name.setdefault(library_name, str(path_text))
    library_names = [
        _library_name_from_path_or_name(item)
        for item in [*dc_supported_target_libraries, *dc_library_db_paths]
        if _library_name_from_path_or_name(item)
    ]
    library_names = sorted(dict.fromkeys(library_names))
    if not library_names:
        return {}
    library_name = library_names[0]
    model: Dict[str, Any] = {
        "model_id": f"dc_target_library:{library_name}",
        "library_name": library_name,
        "dc_target_library": library_name,
        "model_source": "dc_target_library_probe",
        "claim_level": "asic_admission_binding_not_tapeout_selection",
    }
    db_path = path_by_name.get(library_name)
    if db_path:
        model["library_db_path"] = db_path
    model.update(_corner_fields_from_dc_library_name(library_name))
    return model


def _infer_asic_selected_model_from_override(
    selected_model_id: str,
    dc_supported_target_libraries: Sequence[str],
    dc_library_db_paths: Sequence[str],
) -> Dict[str, Any]:
    value = str(selected_model_id or "").strip()
    if not value:
        return {}
    if "/" in value or "\\" in value or value.endswith(".db"):
        supported_libraries = list(dc_supported_target_libraries)
        library_paths = [value, *dc_library_db_paths]
    else:
        supported_libraries = [value, *dc_supported_target_libraries]
        library_paths = list(dc_library_db_paths)
    model = _infer_asic_selected_model_from_dc_probe(
        supported_libraries,
        library_paths,
    )
    if model:
        model["model_source"] = "selected_model_id_override"
    return model


def _required_model_fields(target: str, profile: Mapping[str, Any]) -> list[str]:
    fields = [
        str(field)
        for field in profile.get("required_model_fields", []) or []
        if str(field)
    ]
    if target == "fpga":
        # Board-part strings are installed-board-file evidence, not a stable
        # public model identity.  Keep the raw Vivado part mandatory and record
        # board parts only after a real get_board_parts probe.  The legacy
        # generic "device" label is descriptive metadata, not a Vivado part
        # binding key.
        fields = [
            field
            for field in fields
            if field not in {"device", "vivado_board_part"}
        ]
    return sorted(dict.fromkeys(fields))


def _model_field_present(model: Mapping[str, Any], field: str) -> bool:
    if field in {"vivado_part", "vivado_device"}:
        return bool(model.get("vivado_part") or model.get("vivado_device"))
    return model.get(field) not in (None, "", [], {})


def _missing_model_fields(model: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    return [
        field
        for field in fields
        if not _model_field_present(model, field)
    ]


def _selection_row(
    *,
    item: Mapping[str, Any],
    selected_model_ids: Mapping[str, str],
    fpga_vivado_supported_parts: Sequence[str],
    prefer_fpga_model_with_supported_vivado_part: bool,
    dc_supported_target_libraries: Sequence[str],
    dc_library_db_paths: Sequence[str],
    allow_asic_model_inference_from_dc_probe: bool,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    target = str(item.get("target") or "")
    candidate_id = _deployment_candidate_id(item)
    profile = item.get("target_execution_profile", {})
    profile = dict(profile) if isinstance(profile, Mapping) else {}
    profile_id = str(profile.get("profile_id") or f"{target}:default_profile")

    if target == "asic":
        existing = profile.get("selected_model")
        selected_model_id_override = str(selected_model_ids.get(target) or "")
        if isinstance(existing, Mapping) and existing:
            selected_model = dict(existing)
            source = "explicit_target_execution_profile"
            status = "selected_model_already_present"
        elif selected_model_id_override:
            selected_model = _infer_asic_selected_model_from_override(
                selected_model_id_override,
                dc_supported_target_libraries,
                dc_library_db_paths,
            )
            source = "selected_model_id_override"
            status = (
                "selected_model_from_override_pending_binding"
                if selected_model
                else "blocked_no_asic_selected_model_override"
            )
        elif allow_asic_model_inference_from_dc_probe:
            selected_model = _infer_asic_selected_model_from_dc_probe(
                dc_supported_target_libraries,
                dc_library_db_paths,
            )
            source = "dc_target_library_probe"
            status = (
                "selected_model_inferred_from_dc_probe_pending_binding"
                if selected_model
                else "blocked_no_dc_target_library_probe_model"
            )
        else:
            selected_model = {}
            source = "missing"
            status = "blocked_no_asic_selected_model"
    else:
        selected_model, source, status = _selected_model_from_profile_or_catalog(
            target=target,
            profile=profile,
            selected_model_ids=selected_model_ids,
            fpga_vivado_supported_parts=fpga_vivado_supported_parts,
            prefer_fpga_model_with_supported_vivado_part=(
                prefer_fpga_model_with_supported_vivado_part
            ),
        )

    required_fields = _required_model_fields(target, profile)
    if selected_model and target == "fpga":
        if not required_fields:
            required_fields = [
                "board_or_device_model",
                "memory_bandwidth_gbps",
                "memory_capacity_bytes",
                "part_number",
                "vendor",
                "vivado_part",
            ]
        elif not any(field in {"vivado_part", "vivado_device"} for field in required_fields):
            required_fields = sorted([*required_fields, "vivado_part"])
    missing_fields = _missing_model_fields(selected_model, required_fields)
    if not selected_model:
        return None, {
            "target": target,
            "candidate_id": candidate_id,
            "profile_id": profile_id,
            "blocker_id": status,
        }

    row = {
        "target": target,
        "candidate_id": candidate_id,
        "profile_id": profile_id,
        "source_deployment_work_item_id": item.get("work_item_id"),
        "selected_model_source": source,
        "selection_status": status,
        "selected_model": selected_model,
        "required_model_fields": required_fields,
        "missing_required_model_fields": missing_fields,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    blocker = None
    if missing_fields:
        blocker = {
            "target": target,
            "candidate_id": candidate_id,
            "profile_id": profile_id,
            "blocker_id": "selected_model_missing_required_fields",
            "missing_required_model_fields": missing_fields,
        }
    return row, blocker


def build_dft_deployment_target_model_selection(
    run_dir: Path,
    *,
    deployment_plan_path: Path | None = None,
    targets: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
    selected_model_ids: Mapping[str, str] | None = None,
    fpga_vivado_supported_parts: Sequence[str] = (),
    prefer_fpga_model_with_supported_vivado_part: bool = False,
    dc_supported_target_libraries: Sequence[str] = (),
    dc_library_db_paths: Sequence[str] = (),
    allow_asic_model_inference_from_dc_probe: bool = False,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    plan_path = _deployment_plan_path(run_dir, deployment_plan_path)
    plan = _load_json(plan_path)
    target_filter = {str(item) for item in targets if str(item)}
    candidate_filter = {str(item) for item in candidate_ids if str(item)}
    selected_model_ids = dict(selected_model_ids or {})
    fpga_vivado_supported_parts = sorted(
        dict.fromkeys(str(item) for item in fpga_vivado_supported_parts if str(item))
    )

    rows: list[Dict[str, Any]] = []
    blockers: list[Dict[str, Any]] = []
    skipped_rows: list[Dict[str, Any]] = []
    items = _hard_gate_items(plan)
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        target = str(item.get("target") or "")
        candidate_id = _deployment_candidate_id(item)
        profile = item.get("target_execution_profile", {})
        profile = profile if isinstance(profile, Mapping) else {}
        profile_id = str(profile.get("profile_id") or f"{target}:default_profile")
        key = (target, candidate_id, profile_id)
        if key in seen:
            continue
        seen.add(key)
        if target_filter and target not in target_filter:
            skipped_rows.append({"target": target, "candidate_id": candidate_id, "reason": "target_filter_excluded"})
            continue
        if candidate_filter and candidate_id not in candidate_filter:
            skipped_rows.append({"target": target, "candidate_id": candidate_id, "reason": "candidate_filter_excluded"})
            continue
        row, blocker = _selection_row(
            item=item,
            selected_model_ids=selected_model_ids,
            fpga_vivado_supported_parts=fpga_vivado_supported_parts,
            prefer_fpga_model_with_supported_vivado_part=(
                prefer_fpga_model_with_supported_vivado_part
            ),
            dc_supported_target_libraries=dc_supported_target_libraries,
            dc_library_db_paths=dc_library_db_paths,
            allow_asic_model_inference_from_dc_probe=allow_asic_model_inference_from_dc_probe,
        )
        if row is not None:
            rows.append(row)
        if blocker is not None:
            blockers.append(blocker)

    if not plan:
        status = "blocked_missing_deployment_recommendation_plan"
        blockers.append({"blocker_id": "missing_deployment_recommendation_plan", "path": str(plan_path)})
    elif not items:
        status = "blocked_no_deployment_hard_gate_work_items"
        blockers.append({"blocker_id": "no_deployment_hard_gate_work_items"})
    elif rows and blockers:
        status = "partial_target_model_selection_available"
    elif rows:
        status = "target_model_selection_available"
    else:
        status = "blocked_no_target_model_selection_rows"
        if not blockers:
            blockers.append({"blocker_id": "no_target_model_selection_rows"})

    return {
        "schema_version": DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": {
            "deployment_recommendation_plan": _source_ref(plan_path),
        },
        "selection_policy": {
            "selected_model_ids": dict(selected_model_ids),
            "target_filter": sorted(target_filter),
            "candidate_filter": sorted(candidate_filter),
            "allow_asic_model_inference_from_dc_probe": bool(allow_asic_model_inference_from_dc_probe),
            "prefer_fpga_model_with_supported_vivado_part": bool(
                prefer_fpga_model_with_supported_vivado_part
            ),
            "fpga_vivado_supported_parts": fpga_vivado_supported_parts,
            "dc_supported_target_libraries": sorted(dict.fromkeys(str(item) for item in dc_supported_target_libraries if str(item))),
            "dc_library_db_paths": sorted(dict.fromkeys(str(item) for item in dc_library_db_paths if str(item))),
            "fpga_default_model_id": "amd_alveo_u280_a_u280",
            "claim_boundary": _CLAIM_BOUNDARY,
        },
        "selection_row_count": len(rows),
        "blocker_count": len(blockers),
        "selection_rows": rows,
        "blockers": blockers,
        "skipped_rows": skipped_rows,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_target_model_selection(payload: Mapping[str, Any]) -> Dict[str, Any]:
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected target-model selection schema"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "target-model selection cannot upgrade claims"})
    rows = payload.get("selection_rows", [])
    if not isinstance(rows, list):
        errors.append({"field": "selection_rows", "message": "must be a list"})
        rows = []
    if int(payload.get("selection_row_count", 0) or 0) != len(rows):
        errors.append({"field": "selection_row_count", "message": "must match selection_rows length"})
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append({"field": f"selection_rows[{index}]", "message": "row must be an object"})
            continue
        if not row.get("target"):
            errors.append({"field": f"selection_rows[{index}].target", "message": "required"})
        if not row.get("candidate_id"):
            errors.append({"field": f"selection_rows[{index}].candidate_id", "message": "required"})
        selected_model = row.get("selected_model")
        if not isinstance(selected_model, Mapping) or not selected_model:
            errors.append({"field": f"selection_rows[{index}].selected_model", "message": "must be a non-empty object"})
            continue
        required_fields = [str(field) for field in row.get("required_model_fields", []) or [] if str(field)]
        missing_fields = _missing_model_fields(selected_model, required_fields)
        if missing_fields != list(row.get("missing_required_model_fields", []) or []):
            errors.append({
                "field": f"selection_rows[{index}].missing_required_model_fields",
                "message": "must reflect selected_model and required_model_fields",
            })
    return {
        "schema_version": DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_VALIDATION_SCHEMA,
        "generated_at": _now_iso(),
        "valid": not errors,
        "errors": errors,
        "selection_row_count": len(rows),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_target_model_selection(
    run_dir: Path,
    *,
    out_path: Path | None = None,
    deployment_plan_path: Path | None = None,
    targets: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
    selected_model_ids: Mapping[str, str] | None = None,
    fpga_vivado_supported_parts: Sequence[str] = (),
    prefer_fpga_model_with_supported_vivado_part: bool = False,
    dc_supported_target_libraries: Sequence[str] = (),
    dc_library_db_paths: Sequence[str] = (),
    allow_asic_model_inference_from_dc_probe: bool = False,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    out_path = Path(out_path or run_dir / "dft_deployment_target_model_selection.json")
    payload = build_dft_deployment_target_model_selection(
        run_dir,
        deployment_plan_path=deployment_plan_path,
        targets=targets,
        candidate_ids=candidate_ids,
        selected_model_ids=selected_model_ids,
        fpga_vivado_supported_parts=fpga_vivado_supported_parts,
        prefer_fpga_model_with_supported_vivado_part=(
            prefer_fpga_model_with_supported_vivado_part
        ),
        dc_supported_target_libraries=dc_supported_target_libraries,
        dc_library_db_paths=dc_library_db_paths,
        allow_asic_model_inference_from_dc_probe=allow_asic_model_inference_from_dc_probe,
    )
    write_json(out_path, payload)
    validation = validate_dft_deployment_target_model_selection(payload)
    validation_path = out_path.with_name(out_path.stem + "_validation.json")
    status_path = out_path.with_name(out_path.stem + "_status.json")
    write_json(validation_path, validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": payload["status"] if validation["valid"] else "failed",
        "validation_status": "passed" if validation["valid"] else "failed",
        "selection_row_count": payload.get("selection_row_count"),
        "blocker_count": payload.get("blocker_count"),
        "blocker_ids": [
            str(blocker.get("blocker_id"))
            for blocker in payload.get("blockers", []) or []
            if isinstance(blocker, Mapping) and blocker.get("blocker_id")
        ],
        "target_model_selection": str(out_path),
        "target_model_selection_validation": str(validation_path),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(status_path, status)
    return status


__all__ = [
    "DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_SCHEMA",
    "DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_TARGET_MODEL_SELECTION_VALIDATION_SCHEMA",
    "build_dft_deployment_target_model_selection",
    "validate_dft_deployment_target_model_selection",
    "write_dft_deployment_target_model_selection",
]
