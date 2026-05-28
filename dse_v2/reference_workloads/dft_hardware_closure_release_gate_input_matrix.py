#!/usr/bin/env python3
"""Missing-input matrix for the DFT/QE hardware closure release gate."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA = (
    "dse.dft.hardware_closure_release_gate_input_matrix.v1"
)
DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_VALIDATION_SCHEMA = (
    "dse.dft.hardware_closure_release_gate_input_matrix_validation.v1"
)
DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_release_gate_input_matrix_status.v1"
)

_CLAIM_BOUNDARY = (
    "This matrix records the concrete upstream inputs needed before "
    "dft_hardware_closure_release_gate.json can be built. It may bind "
    "target-source catalogs and discovered ledgers for traceability, but it "
    "does not adjudicate hard gates, does not create PPA evidence, and never "
    "marks hardware or deliverable completion."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(path: Path | None, *, required: bool) -> Dict[str, Any]:
    if path is None:
        return {"path": None, "required": required, "exists": False, "sha256": None, "hash_algorithm": "sha256"}
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    return {
        "path": str(candidate),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(candidate) if exists else None,
        "hash_algorithm": "sha256",
    }


def _maybe(path: Path) -> Path | None:
    return path if path.exists() and path.is_file() else None


def _load_json(path: Path | None, *, max_bytes: int = 2_000_000) -> Dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    if path.stat().st_size > max_bytes:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _artifact_status(ref: Mapping[str, Any]) -> str:
    return "present" if ref.get("exists") is True else "missing"


def _consumer_path(root: Path | None, name: str) -> Path | None:
    if root is None:
        return None
    return _maybe(root / name)


def build_dft_hardware_closure_release_gate_input_matrix(
    run_dir: Path,
    *,
    slot2_target_input_dir: Path | None = None,
    slot2_target_consumer_run_dir: Path | None = None,
    parsed_evidence_manifest_path: Path | None = None,
    gate_adjudication_path: Path | None = None,
    per_candidate_evidence_ledger_path: Path | None = None,
    candidate_workflow_target_evidence_gate_ledger_path: Path | None = None,
    release_subset_manifest_path: Path | None = None,
    hardware_ppa_ranking_path: Path | None = None,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    slot2_target_input_dir = Path(slot2_target_input_dir) if slot2_target_input_dir else None
    slot2_target_consumer_run_dir = (
        Path(slot2_target_consumer_run_dir) if slot2_target_consumer_run_dir else None
    )

    parsed_evidence_manifest_path = parsed_evidence_manifest_path or _maybe(
        run_dir / "dft_hardware_closure_parsed_evidence_manifest.json"
    )
    gate_adjudication_path = gate_adjudication_path or _maybe(run_dir / "dft_hardware_closure_gate_adjudication.json")
    per_candidate_evidence_ledger_path = per_candidate_evidence_ledger_path or _maybe(
        run_dir / "per_candidate_evidence_ledger.json"
    )
    candidate_workflow_target_evidence_gate_ledger_path = (
        candidate_workflow_target_evidence_gate_ledger_path
        or _maybe(run_dir / "dft_candidate_workflow_target_evidence_gate_ledger.json")
    )
    release_subset_manifest_path = release_subset_manifest_path or _maybe(run_dir / "release_subset_manifest.json")
    hardware_ppa_ranking_path = hardware_ppa_ranking_path or _maybe(run_dir / "dft_hardware_ppa_ranking.json")
    fpga_target_catalog_path = (
        _maybe(slot2_target_input_dir / "fpga_target_catalog.json") if slot2_target_input_dir else None
    )
    asic_target_library_probe_path = (
        _maybe(slot2_target_input_dir / "asic_target_library_probe.json") if slot2_target_input_dir else None
    )
    slot2_target_selection_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_hardware_deployment_target_selection.json",
    )
    slot2_consumer_summary_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "run2_target_consumer_final_summary.json",
    )
    slot2_gate_ledger_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_candidate_workflow_target_evidence_gate_ledger.json",
    )
    slot2_gate_ledger_status_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_candidate_workflow_target_evidence_gate_ledger_status.json",
    )
    slot2_ppa_worklist_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "candidate_kernel_target_ppa_gate_worklist.json",
    )
    slot2_release_gate_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_hardware_closure_release_gate.json",
    )
    slot2_release_gate_validation_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_hardware_closure_release_gate_validation.json",
    )
    slot2_provenance_audit_path = _consumer_path(
        slot2_target_consumer_run_dir,
        "dft_candidate_specific_ppa_provenance_audit.json",
    )

    slot2_gate_ledger_status = _load_json(slot2_gate_ledger_status_path)
    slot2_consumer_summary = _load_json(slot2_consumer_summary_path)
    slot2_release_gate = _load_json(slot2_release_gate_path)
    slot2_release_gate_validation = _load_json(slot2_release_gate_validation_path)

    source_artifacts = {
        "parsed_evidence_manifest": _source_ref(parsed_evidence_manifest_path, required=True),
        "gate_adjudication": _source_ref(gate_adjudication_path, required=True),
        "per_candidate_evidence_ledger": _source_ref(per_candidate_evidence_ledger_path, required=False),
        "candidate_workflow_target_evidence_gate_ledger": _source_ref(
            candidate_workflow_target_evidence_gate_ledger_path,
            required=False,
        ),
        "release_subset_manifest": _source_ref(release_subset_manifest_path, required=False),
        "hardware_ppa_ranking": _source_ref(hardware_ppa_ranking_path, required=False),
        "slot2_fpga_target_catalog": _source_ref(fpga_target_catalog_path, required=False),
        "slot2_asic_target_library_probe": _source_ref(asic_target_library_probe_path, required=False),
        "slot2_deployment_target_selection": _source_ref(slot2_target_selection_path, required=False),
        "slot2_target_consumer_final_summary": _source_ref(slot2_consumer_summary_path, required=False),
        "slot2_candidate_workflow_target_evidence_gate_ledger": _source_ref(
            slot2_gate_ledger_path,
            required=False,
        ),
        "slot2_candidate_workflow_target_evidence_gate_ledger_status": _source_ref(
            slot2_gate_ledger_status_path,
            required=False,
        ),
        "slot2_candidate_kernel_target_ppa_gate_worklist": _source_ref(
            slot2_ppa_worklist_path,
            required=False,
        ),
        "slot2_hardware_closure_release_gate": _source_ref(slot2_release_gate_path, required=False),
        "slot2_hardware_closure_release_gate_validation": _source_ref(
            slot2_release_gate_validation_path,
            required=False,
        ),
        "slot2_candidate_specific_ppa_provenance_audit": _source_ref(
            slot2_provenance_audit_path,
            required=False,
        ),
    }

    blockers: list[Dict[str, Any]] = []
    if not source_artifacts["parsed_evidence_manifest"]["exists"]:
        blockers.append(
            {
                "blocker_id": "missing_parsed_evidence_manifest",
                "expected_path": str(run_dir / "dft_hardware_closure_parsed_evidence_manifest.json"),
                "producer": "dse_v2/scripts/dse/build_dft_hardware_closure_parser_run.py or Step5 source-flow parser",
                "upstream_input": "candidate-stamped golden/sim/synth/Vivado/DC hard-gate raw evidence",
            }
        )
    if not source_artifacts["gate_adjudication"]["exists"]:
        blockers.append(
            {
                "blocker_id": "missing_gate_adjudication",
                "expected_path": str(run_dir / "dft_hardware_closure_gate_adjudication.json"),
                "producer": "dse_v2/scripts/dse/build_dft_hardware_closure_gate_adjudication.py",
                "upstream_input": "dft_hardware_closure_parsed_evidence_manifest.json",
            }
        )
    if not source_artifacts["slot2_fpga_target_catalog"]["exists"]:
        blockers.append(
            {
                "blocker_id": "slot2_fpga_target_catalog_not_bound",
                "producer": "dse_v2/scripts/dse/build_dft_target_input_json_producer.py",
                "upstream_input": "hash-backed live Vivado target capacity raw source",
            }
        )
    if not source_artifacts["slot2_asic_target_library_probe"]["exists"]:
        blockers.append(
            {
                "blocker_id": "slot2_asic_target_library_probe_not_bound",
                "producer": "dse_v2/scripts/dse/build_dft_target_input_json_producer.py",
                "upstream_input": "hash-backed live DC target-library raw source",
            }
        )
    if slot2_target_consumer_run_dir is not None:
        for artifact_name, blocker_id, producer in (
            (
                "slot2_candidate_workflow_target_evidence_gate_ledger",
                "slot2_target_consumer_gate_ledger_not_bound",
                "dse_v2/scripts/dse/build_dft_candidate_workflow_target_evidence_gate_ledger.py",
            ),
            (
                "slot2_candidate_kernel_target_ppa_gate_worklist",
                "slot2_target_consumer_ppa_worklist_not_bound",
                "run2 target-consumer PPA-gate worklist producer",
            ),
            (
                "slot2_hardware_closure_release_gate",
                "slot2_target_consumer_release_gate_not_bound",
                "dse_v2/scripts/dse/build_dft_hardware_closure_release_gate.py",
            ),
            (
                "slot2_hardware_closure_release_gate_validation",
                "slot2_target_consumer_release_gate_validation_not_bound",
                "dse_v2/scripts/dse/build_dft_hardware_closure_release_gate.py",
            ),
        ):
            if not source_artifacts[artifact_name]["exists"]:
                blockers.append(
                    {
                        "blocker_id": blocker_id,
                        "producer": producer,
                        "upstream_input": "run2 target-consumer/PPA-gate handoff",
                    }
                )
        if (
            source_artifacts["slot2_hardware_closure_release_gate_validation"]["exists"]
            and slot2_release_gate_validation.get("valid") is not True
        ):
            blockers.append(
                {
                    "blocker_id": "slot2_target_consumer_release_gate_not_valid",
                    "release_gate_status": slot2_release_gate.get("status"),
                    "validation_valid": slot2_release_gate_validation.get("valid"),
                    "upstream_input": (
                        "candidate-specific parsed hard-gate evidence; the current run2 "
                        "target-consumer gate is a fail-closed empty/all-missing-input "
                        "gate and must not be used as release-usable PPA evidence"
                    ),
                }
            )

    release_gate_buildable = source_artifacts["gate_adjudication"]["exists"] is True
    target_source_inputs_bound = (
        source_artifacts["slot2_fpga_target_catalog"]["exists"] is True
        and source_artifacts["slot2_asic_target_library_probe"]["exists"] is True
    )
    target_consumer_inputs_bound = (
        source_artifacts["slot2_candidate_workflow_target_evidence_gate_ledger"]["exists"] is True
        and source_artifacts["slot2_candidate_workflow_target_evidence_gate_ledger_status"]["exists"] is True
        and source_artifacts["slot2_candidate_kernel_target_ppa_gate_worklist"]["exists"] is True
        and source_artifacts["slot2_hardware_closure_release_gate"]["exists"] is True
        and source_artifacts["slot2_hardware_closure_release_gate_validation"]["exists"] is True
    )
    target_consumer_summary = {
        "schema_version": "dse.dft.hardware_closure_release_gate_target_consumer_input_summary.v1",
        "target_consumer_run_dir": str(slot2_target_consumer_run_dir) if slot2_target_consumer_run_dir else None,
        "inputs_bound": target_consumer_inputs_bound,
        "ledger_status": slot2_gate_ledger_status.get("status"),
        "ledger_row_count": slot2_gate_ledger_status.get("row_count")
        or slot2_consumer_summary.get("ledger_row_count"),
        "ledger_blocked_row_count": slot2_gate_ledger_status.get("blocked_row_count")
        or slot2_consumer_summary.get("blocked_row_count"),
        "worklist_hash": slot2_consumer_summary.get("worklist_hash"),
        "release_gate_status": slot2_release_gate.get("status"),
        "release_gate_result": slot2_release_gate.get("release_gate_result"),
        "release_gate_validation_valid": slot2_release_gate_validation.get("valid"),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "The run2 target-consumer ledger/worklist/release-gate artifacts are "
            "bound as upstream scheduling and blocker evidence only. They cannot "
            "satisfy run1 parsed hard-gate adjudication or release-usable PPA "
            "recommendation requirements while their rows remain missing-input "
            "or their release-gate validation is not valid."
        ),
    }
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA,
        "generated_at": _now_iso(),
        "status": "ready_for_release_gate_build" if release_gate_buildable else "blocked_missing_release_gate_inputs",
        "run_dir": str(run_dir),
        "source_artifacts": source_artifacts,
        "input_rows": [
            {
                "artifact": name,
                "status": _artifact_status(ref),
                "required": ref.get("required"),
                "path": ref.get("path"),
                "sha256": ref.get("sha256"),
            }
            for name, ref in source_artifacts.items()
        ],
        "release_gate_buildable": release_gate_buildable,
        "target_source_inputs_bound": target_source_inputs_bound,
        "target_consumer_inputs_bound": target_consumer_inputs_bound,
        "target_consumer_summary": target_consumer_summary,
        "blocker_count": len(blockers),
        "blocker_ids": [str(item["blocker_id"]) for item in blockers],
        "blockers": blockers,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_hardware_closure_release_gate_input_matrix(payload: Mapping[str, Any]) -> Dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("input_matrix_must_not_mark_deliverable_complete")
    if payload.get("hardware_completion_eligible") is True:
        errors.append("input_matrix_must_not_mark_hardware_completion_eligible")
    source_artifacts = payload.get("source_artifacts")
    if not isinstance(source_artifacts, Mapping):
        errors.append("source_artifacts_missing_or_not_mapping")
        source_artifacts = {}
    for required_name in ("parsed_evidence_manifest", "gate_adjudication"):
        ref = source_artifacts.get(required_name)
        if not isinstance(ref, Mapping):
            errors.append(f"{required_name}_source_ref_missing")
        elif ref.get("required") is not True:
            errors.append(f"{required_name}_must_be_required")
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        errors.append("blockers_must_be_list")
        blockers = []
    if payload.get("blocker_count") != len(blockers):
        errors.append("blocker_count_mismatch")
    if payload.get("release_gate_buildable") is True and "missing_gate_adjudication" in (
        payload.get("blocker_ids") or []
    ):
        errors.append("release_gate_buildable_with_missing_gate_adjudication")
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_release_gate_input_matrix(
    run_dir: Path,
    *,
    slot2_target_input_dir: Path | None = None,
    slot2_target_consumer_run_dir: Path | None = None,
    parsed_evidence_manifest_path: Path | None = None,
    gate_adjudication_path: Path | None = None,
    per_candidate_evidence_ledger_path: Path | None = None,
    candidate_workflow_target_evidence_gate_ledger_path: Path | None = None,
    release_subset_manifest_path: Path | None = None,
    hardware_ppa_ranking_path: Path | None = None,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    matrix = build_dft_hardware_closure_release_gate_input_matrix(
        run_dir,
        slot2_target_input_dir=slot2_target_input_dir,
        slot2_target_consumer_run_dir=slot2_target_consumer_run_dir,
        parsed_evidence_manifest_path=parsed_evidence_manifest_path,
        gate_adjudication_path=gate_adjudication_path,
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
        candidate_workflow_target_evidence_gate_ledger_path=candidate_workflow_target_evidence_gate_ledger_path,
        release_subset_manifest_path=release_subset_manifest_path,
        hardware_ppa_ranking_path=hardware_ppa_ranking_path,
    )
    validation = validate_dft_hardware_closure_release_gate_input_matrix(matrix)
    write_json(run_dir / "dft_hardware_closure_release_gate_input_matrix.json", matrix)
    write_json(run_dir / "dft_hardware_closure_release_gate_input_matrix_validation.json", validation)
    status = {
        "schema_version": DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "matrix": "dft_hardware_closure_release_gate_input_matrix.json",
        "validation": "dft_hardware_closure_release_gate_input_matrix_validation.json",
        "matrix_status": matrix.get("status"),
        "release_gate_buildable": matrix.get("release_gate_buildable"),
        "target_source_inputs_bound": matrix.get("target_source_inputs_bound"),
        "target_consumer_inputs_bound": matrix.get("target_consumer_inputs_bound"),
        "blocker_ids": matrix.get("blocker_ids"),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_hardware_closure_release_gate_input_matrix_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_STATUS_SCHEMA",
    "DFT_HARDWARE_CLOSURE_RELEASE_GATE_INPUT_MATRIX_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_release_gate_input_matrix",
    "validate_dft_hardware_closure_release_gate_input_matrix",
    "write_dft_hardware_closure_release_gate_input_matrix",
]
