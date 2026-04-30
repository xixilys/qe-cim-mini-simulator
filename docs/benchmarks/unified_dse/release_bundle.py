from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import domain_contracts


RELEASE_BUNDLE_NAME = "frontend_release_bundle_v0.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _refs(root: Path, subdir: str) -> list[str]:
    path = root / subdir
    if not path.exists():
        return []
    return [str(item.relative_to(root)) for item in sorted(path.rglob("*.json"))]


def build_release_bundle(
    *,
    result_bundle_ref: str,
    manifest_ref: str,
    stage_status_ref: str | None = None,
    stage_b0_descriptor_manifest_ref: str | None = None,
    multi_fidelity_plan_ref: str | None = None,
    evidence_refs: Sequence[str] | None = None,
    calibration_metadata_ref: str | None = None,
    calibration_model_ref: str | None = None,
    adjudication_summary_ref: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    root_path = Path(root) if root is not None else Path(".")
    return {
        "schema_version": domain_contracts.RELEASE_BUNDLE_SCHEMA_VERSION,
        "authority_scope": "supporting_evidence_only",
        "claim_posture": "evidence_grade_recommendation_no_public_winner",
        "claim_ceiling": "release_index_only",
        "decision_authority": "adjudicator_memo_only",
        "final_public_family_winner": None,
        "result_bundle_ref": result_bundle_ref,
        "manifest_ref": manifest_ref,
        "stage_status_ref": stage_status_ref,
        "stage_b0_descriptor_manifest_ref": stage_b0_descriptor_manifest_ref,
        "multi_fidelity_plan_ref": multi_fidelity_plan_ref,
        "candidate_descriptor_refs": _refs(root_path, "candidate_descriptors"),
        "backend_execution_request_refs": _refs(root_path, "backend_execution_requests"),
        "ir_sidecar_refs": {
            "application_graphs": _refs(root_path, "application_graphs"),
            "architecture_templates": _refs(root_path, "architecture_templates"),
            "mappings": _refs(root_path, "mappings"),
        },
        "evidence_refs": list(evidence_refs or []),
        "calibration_metadata_ref": calibration_metadata_ref,
        "calibration_model_ref": calibration_model_ref or calibration_metadata_ref,
        "adjudication_summary_ref": adjudication_summary_ref,
        "reproducibility_metadata": {
            "schema_version": "frontend_reproducibility_metadata_v0",
            "artifact_hash_manifest_ref": "frontend_release_sha256_manifest_v0.json",
            "frontend_only": True,
        },
        "non_touch_guard": {
            "status": "frontend_only_by_construction",
            "forbidden_paths": ["model/", "gem5_integration/", "soft/qe-7.5/", "soft/ge-7.5/"],
            "backend_execution_performed_by_frontend": False,
        },
        "non_claims": [
            "no_hidden_systemc_execution",
            "no_hidden_gem5_execution",
            "no_hidden_qe_execution",
            "no_board_physical_measurement_claim",
            "no_final_public_winner",
        ],
    }


def emit_release_bundle(
    output_dir: Path | str,
    *,
    result_bundle_ref: str = "unified_dse_results_v0.json",
    manifest_ref: str = "unified_dse_manifest_v0.json",
    stage_status_ref: str | None = None,
    stage_b0_descriptor_manifest_ref: str | None = None,
    multi_fidelity_plan_ref: str | None = None,
    evidence_refs: Sequence[str] | None = None,
    calibration_metadata_ref: str | None = None,
    calibration_model_ref: str | None = None,
    adjudication_summary_ref: str | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    payload = build_release_bundle(
        result_bundle_ref=result_bundle_ref,
        manifest_ref=manifest_ref,
        stage_status_ref=stage_status_ref,
        stage_b0_descriptor_manifest_ref=stage_b0_descriptor_manifest_ref,
        multi_fidelity_plan_ref=multi_fidelity_plan_ref,
        evidence_refs=evidence_refs,
        calibration_metadata_ref=calibration_metadata_ref,
        calibration_model_ref=calibration_model_ref,
        adjudication_summary_ref=adjudication_summary_ref,
        root=root,
    )
    _write_json(root / RELEASE_BUNDLE_NAME, payload)
    _write_json(root / "frontend_release_sha256_manifest_v0.json", build_sha256_manifest(root))
    return payload


def validate_release_bundle(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "authority_scope",
        "claim_posture",
        "decision_authority",
        "final_public_family_winner",
        "claim_ceiling",
        "result_bundle_ref",
        "manifest_ref",
        "non_touch_guard",
        "non_claims",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"release bundle missing field: {key}")
    if payload["schema_version"] != domain_contracts.RELEASE_BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported release bundle schema_version")
    if payload.get("final_public_family_winner") is not None:
        raise ValueError("release bundle must not declare final public family winner")
    if payload.get("claim_ceiling") != "release_index_only":
        raise ValueError("release bundle claim_ceiling must be release_index_only")
    guard = payload.get("non_touch_guard")
    if not isinstance(guard, Mapping) or guard.get("backend_execution_performed_by_frontend") is not False:
        raise ValueError("release bundle non-touch guard failed")


def build_sha256_manifest(root: Path | str) -> dict[str, Any]:
    root_path = Path(root)
    entries = []
    for path in sorted(root_path.rglob("*.json")):
        if path.name == "frontend_release_sha256_manifest_v0.json":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"path": str(path.relative_to(root_path)), "sha256": digest})
    return {
        "schema_version": "frontend_release_sha256_manifest_v0",
        "artifact_count": len(entries),
        "artifacts": entries,
    }


def validate_release_bundle_links(payload: Mapping[str, Any], root: Path | str) -> None:
    validate_release_bundle(payload)
    root_path = Path(root)
    refs: list[str] = []
    for key in (
        "result_bundle_ref",
        "manifest_ref",
        "stage_status_ref",
        "stage_b0_descriptor_manifest_ref",
        "multi_fidelity_plan_ref",
        "calibration_metadata_ref",
        "calibration_model_ref",
        "adjudication_summary_ref",
    ):
        value = payload.get(key)
        if value:
            refs.append(str(value))
    refs.extend(str(item) for item in payload.get("candidate_descriptor_refs", []))
    refs.extend(str(item) for item in payload.get("backend_execution_request_refs", []))
    ir_refs = payload.get("ir_sidecar_refs", {})
    if isinstance(ir_refs, Mapping):
        for values in ir_refs.values():
            if isinstance(values, list):
                refs.extend(str(item) for item in values)
    refs.extend(str(item) for item in payload.get("evidence_refs", []))

    def ref_exists(ref: str) -> bool:
        path = Path(ref)
        if path.is_absolute():
            return path.exists()
        return (root_path / path).exists() or path.exists()

    missing = sorted(ref for ref in refs if not ref_exists(ref))
    if missing:
        raise ValueError(f"release bundle has missing artifact refs: {missing}")
