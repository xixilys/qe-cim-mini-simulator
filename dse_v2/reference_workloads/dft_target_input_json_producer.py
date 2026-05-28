#!/usr/bin/env python3
"""Produce DFT deployment target input JSONs from hash-backed raw refs.

This producer accepts raw source references for FPGA capacity catalog rows and
ASIC target-library probe rows, validates the source hashes, and emits the two
target-selection inputs consumed by
``dft_hardware_deployment_target_selection``.  It deliberately rejects target
JSONs, Vivado part-support probes, placeholders, and self-referential source
refs as raw provenance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_TARGET_INPUT_JSON_PRODUCER_STATUS_SCHEMA = "dse.dft.target_input_json_producer_status.v1"
FPGA_TARGET_CATALOG_SCHEMA = "dse.dft.fpga_target_catalog.v1"
ASIC_TARGET_LIBRARY_PROBE_SCHEMA = "dse.dft.asic_target_library_probe.v1"
VIVADO_PART_SUPPORT_PROBE_SCHEMA = "dse.dft.vivado_part_support_probe.v1"

_CLAIM_BOUNDARY = (
    "DFT target input JSON producer only converts independently hash-backed raw "
    "FPGA capacity and ASIC target-library refs into target-selection inputs. "
    "It is not Vivado/DC PPA evidence, deployment selection, recommendation "
    "readiness, hardware-completion, or deliverable-completion evidence."
)

_PLACEHOLDER_KEYS = (
    "placeholder",
    "synthetic",
    "mock",
    "example_only",
    "self_hashed",
    "self_hash",
    "generated_placeholder",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _ref_path(raw_ref: Mapping[str, Any], *, ref_base_dir: Path | None = None) -> Path | None:
    value = raw_ref.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute() and ref_base_dir is not None:
        candidate = ref_base_dir / candidate
    return candidate


def _normalised_source_ref(path: Path, raw_ref: Mapping[str, Any], actual_sha256: str) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": True,
        "sha256": actual_sha256,
        "hash_algorithm": "sha256",
        "status": "present_hash_valid",
        "source_role": str(raw_ref.get("source_role") or "raw_target_input_reference"),
    }


def _contains_placeholder_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if key_text in _PLACEHOLDER_KEYS and nested not in (False, None, "", [], {}):
                return True
            if _contains_placeholder_marker(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_placeholder_marker(item) for item in value)
    return False


def _source_ref_points_to(ref: Mapping[str, Any], path: Path, *, base_dir: Path) -> bool:
    raw_path = ref.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return False
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return _resolved(candidate) == _resolved(path)


def _payload_has_self_ref(payload: Mapping[str, Any], path: Path) -> bool:
    base_dir = path.parent
    refs = payload.get("source_refs", [])
    if isinstance(refs, Mapping):
        refs = [refs]
    if not isinstance(refs, list):
        return False
    return any(
        isinstance(ref, Mapping) and _source_ref_points_to(ref, path, base_dir=base_dir)
        for ref in refs
    )


def _rows(payload: Mapping[str, Any], keys: Sequence[str]) -> list[Dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _validate_raw_ref(
    *,
    deployment: str,
    raw_ref: Mapping[str, Any],
    out_dir: Path,
    output_name: str,
    ref_base_dir: Path | None = None,
) -> tuple[Path | None, Dict[str, Any], Dict[str, Any] | None, list[Dict[str, Any]]]:
    blockers: list[Dict[str, Any]] = []
    path = _ref_path(raw_ref, ref_base_dir=ref_base_dir)
    if path is None:
        return None, {}, None, [{"blocker_id": f"{deployment}_raw_ref_missing_path"}]
    target_output_path = out_dir / output_name
    if _resolved(path) == _resolved(target_output_path):
        blockers.append({"blocker_id": f"{deployment}_raw_ref_points_to_target_json", "path": str(path)})
    if raw_ref.get("hash_algorithm", "sha256") != "sha256":
        blockers.append({"blocker_id": f"{deployment}_raw_ref_hash_algorithm_not_sha256", "path": str(path)})
    expected_sha256 = raw_ref.get("sha256")
    if not isinstance(expected_sha256, str) or not expected_sha256:
        blockers.append({"blocker_id": f"{deployment}_raw_ref_missing_sha256", "path": str(path)})
    if not path.exists() or not path.is_file():
        blockers.append({"blocker_id": f"{deployment}_raw_ref_missing_file", "path": str(path)})
        return path, {}, None, blockers
    actual_sha256 = sha256_file(path)
    if isinstance(expected_sha256, str) and expected_sha256 and expected_sha256 != actual_sha256:
        blockers.append(
            {
                "blocker_id": f"{deployment}_raw_ref_hash_mismatch",
                "path": str(path),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            }
        )
    payload = _load_json(path)
    if not payload:
        blockers.append({"blocker_id": f"{deployment}_raw_payload_not_json_object", "path": str(path)})
        return path, {}, None, blockers
    if _contains_placeholder_marker(payload):
        blockers.append({"blocker_id": f"{deployment}_raw_payload_placeholder_or_synthetic", "path": str(path)})
    if _payload_has_self_ref(payload, path):
        blockers.append({"blocker_id": f"{deployment}_raw_payload_self_referential_source_ref", "path": str(path)})
    source_ref = _normalised_source_ref(path, raw_ref, actual_sha256)
    return path, payload, source_ref, blockers


def _fpga_blockers_for_payload(payload: Mapping[str, Any], *, path: Path | None) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if payload.get("schema_version") == FPGA_TARGET_CATALOG_SCHEMA:
        blockers.append({"blocker_id": "fpga_raw_ref_points_to_target_json", "path": str(path)})
    if payload.get("schema_version") == VIVADO_PART_SUPPORT_PROBE_SCHEMA or (
        "requested_part_results" in payload and "supported_parts" in payload
    ):
        blockers.append(
            {
                "blocker_id": "fpga_raw_ref_vivado_part_support_probe_not_capacity_catalog",
                "path": str(path),
            }
        )
    rows = _rows(payload, ("targets", "devices", "fpga_targets"))
    if not rows:
        blockers.append({"blocker_id": "fpga_raw_payload_has_no_targets", "path": str(path)})
    for index, row in enumerate(rows):
        missing = [
            field
            for field in ("target_device_id", "vendor", "part")
            if row.get(field) in (None, "", [])
        ]
        if missing:
            blockers.append(
                {
                    "blocker_id": "fpga_raw_target_missing_required_fields",
                    "path": str(path),
                    "row_index": index,
                    "missing_fields": missing,
                }
            )
        capacity = row.get("capacity")
        if not isinstance(capacity, Mapping) or not capacity:
            blockers.append(
                {
                    "blocker_id": "fpga_raw_target_missing_capacity",
                    "path": str(path),
                    "row_index": index,
                }
            )
    return blockers


def _asic_blockers_for_payload(payload: Mapping[str, Any], *, path: Path | None) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if payload.get("schema_version") == ASIC_TARGET_LIBRARY_PROBE_SCHEMA:
        blockers.append({"blocker_id": "asic_raw_ref_points_to_target_json", "path": str(path)})
    rows = _rows(payload, ("target_libraries", "libraries", "targets", "library_rows"))
    if not rows:
        blockers.append({"blocker_id": "asic_raw_payload_has_no_target_libraries", "path": str(path)})
    for index, row in enumerate(rows):
        missing = [
            field
            for field in ("target_library_id", "process_node", "pvt_corner")
            if row.get(field) in (None, "", [])
        ]
        if missing:
            blockers.append(
                {
                    "blocker_id": "asic_raw_target_library_missing_required_fields",
                    "path": str(path),
                    "row_index": index,
                    "missing_fields": missing,
                }
            )
    return blockers


def _with_source_refs(rows: Sequence[Mapping[str, Any]], source_ref: Mapping[str, Any]) -> list[Dict[str, Any]]:
    normalised: list[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["source_refs"] = [dict(source_ref)]
        item.setdefault("hardware_completion_eligible", False)
        item.setdefault("deliverable_complete", False)
        item.setdefault("claim_boundary", _CLAIM_BOUNDARY)
        normalised.append(item)
    return normalised


def _build_fpga_catalog(payload: Mapping[str, Any], source_ref: Mapping[str, Any]) -> Dict[str, Any]:
    rows = _rows(payload, ("targets", "devices", "fpga_targets"))
    return {
        "schema_version": FPGA_TARGET_CATALOG_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed",
        "source_refs": [dict(source_ref)],
        "targets": _with_source_refs(rows, source_ref),
        "target_catalog_from_vivado_part_support_probe": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _build_asic_probe(payload: Mapping[str, Any], source_ref: Mapping[str, Any]) -> Dict[str, Any]:
    rows = _rows(payload, ("target_libraries", "libraries", "targets", "library_rows"))
    return {
        "schema_version": ASIC_TARGET_LIBRARY_PROBE_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed",
        "source_refs": [dict(source_ref)],
        "target_libraries": _with_source_refs(rows, source_ref),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_target_input_jsons_from_raw_refs(
    run_dir: Path,
    *,
    fpga_raw_ref: Mapping[str, Any],
    asic_raw_ref: Mapping[str, Any],
    fpga_ref_base_dir: Path | None = None,
    asic_ref_base_dir: Path | None = None,
) -> Dict[str, Any]:
    """Build target input JSON payloads from explicit hash-backed raw refs."""

    run_dir = Path(run_dir)
    blockers: list[Dict[str, Any]] = []
    fpga_path, fpga_payload, fpga_source_ref, fpga_ref_blockers = _validate_raw_ref(
        deployment="fpga",
        raw_ref=fpga_raw_ref,
        out_dir=run_dir,
        output_name="fpga_target_catalog.json",
        ref_base_dir=fpga_ref_base_dir,
    )
    asic_path, asic_payload, asic_source_ref, asic_ref_blockers = _validate_raw_ref(
        deployment="asic",
        raw_ref=asic_raw_ref,
        out_dir=run_dir,
        output_name="asic_target_library_probe.json",
        ref_base_dir=asic_ref_base_dir,
    )
    blockers.extend(fpga_ref_blockers)
    blockers.extend(asic_ref_blockers)
    if fpga_payload:
        blockers.extend(_fpga_blockers_for_payload(fpga_payload, path=fpga_path))
    if asic_payload:
        blockers.extend(_asic_blockers_for_payload(asic_payload, path=asic_path))
    if blockers:
        return {
            "schema_version": DFT_TARGET_INPUT_JSON_PRODUCER_STATUS_SCHEMA,
            "generated_at": _now_iso(),
            "status": "blocked",
            "blocked": True,
            "blockers": blockers,
            "outputs": {},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    assert fpga_source_ref is not None
    assert asic_source_ref is not None
    fpga_catalog = _build_fpga_catalog(fpga_payload, fpga_source_ref)
    asic_probe = _build_asic_probe(asic_payload, asic_source_ref)
    return {
        "schema_version": DFT_TARGET_INPUT_JSON_PRODUCER_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed",
        "blocked": False,
        "blockers": [],
        "outputs": {
            "fpga_target_catalog": fpga_catalog,
            "asic_target_library_probe": asic_probe,
        },
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_target_input_jsons_from_raw_refs(
    run_dir: Path,
    *,
    fpga_raw_ref: Mapping[str, Any],
    asic_raw_ref: Mapping[str, Any],
    fpga_ref_base_dir: Path | None = None,
    asic_ref_base_dir: Path | None = None,
) -> Dict[str, Any]:
    """Write target input JSONs or a fail-closed blocked status."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result = build_dft_target_input_jsons_from_raw_refs(
        run_dir,
        fpga_raw_ref=fpga_raw_ref,
        asic_raw_ref=asic_raw_ref,
        fpga_ref_base_dir=fpga_ref_base_dir,
        asic_ref_base_dir=asic_ref_base_dir,
    )
    status_payload = dict(result)
    outputs = result.get("outputs", {})
    if result.get("blocked") is not True and isinstance(outputs, Mapping):
        fpga_catalog = outputs.get("fpga_target_catalog")
        asic_probe = outputs.get("asic_target_library_probe")
        if isinstance(fpga_catalog, Mapping) and isinstance(asic_probe, Mapping):
            write_json(run_dir / "fpga_target_catalog.json", fpga_catalog)
            write_json(run_dir / "asic_target_library_probe.json", asic_probe)
            status_payload["outputs"] = {
                "fpga_target_catalog": str(run_dir / "fpga_target_catalog.json"),
                "asic_target_library_probe": str(run_dir / "asic_target_library_probe.json"),
            }
    write_json(run_dir / "dft_target_input_json_producer_status.json", status_payload)
    return result


def load_raw_ref_file(path: Path) -> tuple[Dict[str, Any], Path]:
    """Load a raw-ref JSON object and return it with its directory for relative paths."""

    payload = _load_json(Path(path))
    return payload, Path(path).parent


__all__ = [
    "ASIC_TARGET_LIBRARY_PROBE_SCHEMA",
    "DFT_TARGET_INPUT_JSON_PRODUCER_STATUS_SCHEMA",
    "FPGA_TARGET_CATALOG_SCHEMA",
    "build_dft_target_input_jsons_from_raw_refs",
    "load_raw_ref_file",
    "write_dft_target_input_jsons_from_raw_refs",
]
