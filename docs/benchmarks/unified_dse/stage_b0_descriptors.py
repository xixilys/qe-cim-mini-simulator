from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .backend_execution import validate_backend_execution_request
except ImportError:  # pragma: no cover - script-path fallback
    from backend_execution import validate_backend_execution_request  # type: ignore


DESCRIPTOR_MANIFEST_NAME = "stage_b0_descriptor_manifest_v0.json"
SYSTEMC_CONFIG_SCHEMA_VERSION = "qe_dse_systemc_candidate_config_stage_b0_v0"
GEM5_HANDOFF_DESCRIPTOR_SCHEMA_VERSION = "qe_dse_gem5_systemc_handoff_descriptor_stage_b0_v0"
BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION = "backend_execution_request_v0"


def _require_mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"row missing Stage B0 mapping: {key}")
    return value


def _candidate_id(row: Mapping[str, Any]) -> str:
    systemc_feedback = _require_mapping(row, "systemc_feedback_contract")
    candidate_id = systemc_feedback.get("candidate_id")
    if not candidate_id:
        raise ValueError("row missing systemc_feedback_contract.candidate_id")
    return str(candidate_id)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workload_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    workload = _require_mapping(row, "workload")
    qe_anchor_refs = _require_mapping(row, "qe_anchor_refs")
    return {
        "workload_id": workload.get("workload_id"),
        "case_id": qe_anchor_refs.get("case_id"),
        "workload_group_id": workload.get("workload_group_id"),
        "signature_id": workload.get("signature_id"),
        "pseudopotential_family": workload.get("pseudopotential_family"),
        "qe_tolerance_schema_id": workload.get("qe_tolerance_schema_id"),
        "accounting_boundary_id": workload.get("accounting_boundary_id"),
        "observability_contract_id": workload.get("observability_contract_id"),
    }


def _candidate_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    design_point = _require_mapping(row, "design_point")
    systemc_feedback = _require_mapping(row, "systemc_feedback_contract")
    backend_neutral_schema = _require_mapping(row, "backend_neutral_schema")
    projection = row.get("projection", {})
    if not isinstance(projection, Mapping):
        projection = {}
    return {
        "candidate_id": systemc_feedback.get("candidate_id"),
        "candidate_family": systemc_feedback.get("candidate_family"),
        "architecture_template_id": systemc_feedback.get("architecture_template_id"),
        "implementation_target_class": systemc_feedback.get("implementation_target_class"),
        "backend_profile_id": systemc_feedback.get("backend_profile_id"),
        "runtime_projection_family": projection.get("runtime_projection_family"),
        "implementation_backend": backend_neutral_schema.get("implementation_backend"),
        "source_kind": backend_neutral_schema.get("source_kind"),
        "design_axes": dict(design_point),
    }


def _systemc_config(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SYSTEMC_CONFIG_SCHEMA_VERSION,
        "execution_status": "not_executed",
        "claim_ceiling": "systemc_config_descriptor_only",
        "candidate_identity": _candidate_identity(row),
        "workload_identity": _workload_identity(row),
        "design_point": dict(_require_mapping(row, "design_point")),
        "backend_neutral_schema": dict(_require_mapping(row, "backend_neutral_schema")),
        "systemc_feedback_contract": dict(_require_mapping(row, "systemc_feedback_contract")),
        "qe_anchor_refs": dict(_require_mapping(row, "qe_anchor_refs")),
        "non_claims": [
            "not_systemc_executed",
            "not_gem5_executed",
            "not_qe_equivalent_scf",
            "not_rtl_hls_board_evidence",
        ],
    }


def _gem5_descriptor(row: Mapping[str, Any], systemc_config_ref: str) -> dict[str, Any]:
    gem5_handoff = _require_mapping(row, "gem5_handoff_contract")
    return {
        "schema_version": GEM5_HANDOFF_DESCRIPTOR_SCHEMA_VERSION,
        "execution_status": "not_executed",
        "claim_ceiling": "stage_b0_handoff_descriptor_only",
        "candidate_identity": _candidate_identity(row),
        "workload_identity": _workload_identity(row),
        "systemc_config_ref": systemc_config_ref,
        "expected_command": gem5_handoff.get("expected_command"),
        "expected_report_ref": gem5_handoff.get("expected_report_ref"),
        "output_report_expected_keys": list(gem5_handoff.get("output_report_expected_keys", [])),
        "systemc_feedback_contract": dict(_require_mapping(row, "systemc_feedback_contract")),
        "gem5_handoff_contract": dict(gem5_handoff),
        "qe_anchor_refs": dict(_require_mapping(row, "qe_anchor_refs")),
        "non_claims": [
            "descriptor_only",
            "not_gem5_controlled_systemc_execution",
            "not_qe_equivalent_scf",
        ],
    }


def _backend_execution_request(
    row: Mapping[str, Any],
    systemc_config_ref: str,
    gem5_descriptor_ref: str,
    *,
    request_dir_ref: str,
) -> dict[str, Any]:
    workload = _require_mapping(row, "workload")
    qe_anchor_refs = _require_mapping(row, "qe_anchor_refs")
    systemc_feedback = _require_mapping(row, "systemc_feedback_contract")
    backend_neutral_schema = _require_mapping(row, "backend_neutral_schema")
    gem5_handoff = _require_mapping(row, "gem5_handoff_contract")
    candidate_id = _candidate_id(row)
    return {
        "schema_version": BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "requested_fidelity": "B2",
        "execution_mode": "systemc_timed_functional",
        "workload_identity": {
            "workload_id": workload.get("workload_id"),
            "domain": "dft",
            "adapter": "qe",
            "workload_group_id": workload.get("workload_group_id"),
            "signature_id": workload.get("signature_id"),
        },
        "candidate_identity": {
            "architecture_template_id": systemc_feedback.get("architecture_template_id"),
            "target_class": systemc_feedback.get("implementation_target_class", "unknown"),
            "design_axes": dict(_require_mapping(row, "design_point")),
            "backend_profile_id": systemc_feedback.get("backend_profile_id"),
            "candidate_family": systemc_feedback.get("candidate_family"),
            "implementation_backend": backend_neutral_schema.get("implementation_backend"),
        },
        "input_refs": {
            "systemc_config": f"{request_dir_ref}/{systemc_config_ref}",
            "gem5_handoff_descriptor": f"{request_dir_ref}/{gem5_descriptor_ref}",
            "proxy_runtime": gem5_handoff.get("expected_command"),
        },
        "software_runtime": {
            "mode": "proxy_runtime",
            "control_policy": "sync",
        },
        "domain_extension": {
            "qe": {
                "case_id": qe_anchor_refs.get("case_id"),
                "pseudopotential_family": workload.get("pseudopotential_family"),
                "solver_path_class": "standard_band",
                "qe_tolerance_schema_id": workload.get("qe_tolerance_schema_id"),
                "qe_equivalent_scf_claim": False,
            }
        },
        "expected_report_schema": "backend_execution_report_v0",
        "non_claims": [
            "descriptor_only",
            "not_systemc_executed",
            "not_gem5_executed",
            "not_qe_equivalent_scf",
            "not_rtl_hls_board_asic_evidence",
        ],
    }


def emit_stage_b0_descriptors(
    output_dir: Path | str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root = Path(output_dir)
    descriptors = []
    for row in rows:
        candidate_id = _candidate_id(row)
        systemc_config_ref = f"systemc_configs/{candidate_id}.json"
        gem5_descriptor_ref = f"gem5_systemc_handoff/{candidate_id}.json"
        backend_request_ref = f"backend_execution_requests/{candidate_id}.json"
        backend_request = _backend_execution_request(
            row,
            systemc_config_ref,
            gem5_descriptor_ref,
            request_dir_ref="..",
        )
        validate_backend_execution_request(backend_request)
        _write_json(root / systemc_config_ref, _systemc_config(row))
        _write_json(root / gem5_descriptor_ref, _gem5_descriptor(row, systemc_config_ref))
        _write_json(root / backend_request_ref, backend_request)
        descriptors.append(
            {
                "candidate_id": candidate_id,
                "systemc_config_ref": systemc_config_ref,
                "gem5_descriptor_ref": gem5_descriptor_ref,
                "backend_execution_request_ref": backend_request_ref,
                "execution_status": "not_executed",
                "claim_ceiling": "descriptor_generation_only",
            }
        )

    manifest = {
        "schema_version": DESCRIPTOR_MANIFEST_NAME.removesuffix(".json"),
        "execution_status": "not_executed",
        "claim_ceiling": "descriptor_generation_only",
        "descriptor_count": len(descriptors),
        "backend_execution_request_generation_status": "generated_not_executed",
        "backend_execution_request_count": len(descriptors),
        "backend_execution_request_claim_ceiling": "descriptor_generation_only",
        "descriptors": descriptors,
    }
    _write_json(root / DESCRIPTOR_MANIFEST_NAME, manifest)
    return manifest
