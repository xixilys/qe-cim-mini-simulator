from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION = "qe_dse_fpga_asic_implementation_evidence_v0"

EVIDENCE_KINDS_BY_TARGET = {
    "fpga": {"hls_synthesis", "rtl_simulation", "fpga_board", "implementation_projection"},
    "asic": {"rtl_simulation", "openroad_physical", "asic_ppa", "implementation_projection"},
}

CLAIM_CEILING_BY_EVIDENCE_KIND = {
    "hls_synthesis": "hls_synthesis_only",
    "rtl_simulation": "rtl_simulation_only",
    "fpga_board": "fpga_board_measurement_only",
    "openroad_physical": "openroad_physical_estimate_only",
    "asic_ppa": "asic_ppa_estimate_only",
    "implementation_projection": "implementation_evidence_only",
}

EVIDENCE_STATUSES = {"available", "partial", "failed"}


def load_and_validate_implementation_evidence(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_implementation_evidence(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"implementation evidence requires mapping field: {key}")
    return value


def validate_implementation_evidence(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "execution_status",
        "evidence_id",
        "candidate_id",
        "implementation_target_class",
        "evidence_kind",
        "evidence_status",
        "claim_ceiling",
        "artifact_refs",
        "metrics",
        "correctness_dependency",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"implementation evidence missing field: {key}")
    if payload["schema_version"] != IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported implementation evidence schema_version")
    if payload["execution_status"] != "external_evidence_referenced":
        raise ValueError("implementation evidence must be externally referenced, not run by the DSE CLI")

    target = str(payload["implementation_target_class"])
    evidence_kind = str(payload["evidence_kind"])
    if target not in EVIDENCE_KINDS_BY_TARGET:
        raise ValueError("implementation_target_class must be fpga or asic")
    if evidence_kind not in EVIDENCE_KINDS_BY_TARGET[target]:
        raise ValueError("evidence_kind is not valid for the implementation target class")
    expected_claim_ceiling = CLAIM_CEILING_BY_EVIDENCE_KIND[evidence_kind]
    if payload["claim_ceiling"] != expected_claim_ceiling:
        raise ValueError(f"implementation evidence claim_ceiling must be {expected_claim_ceiling}")
    if payload["evidence_status"] not in EVIDENCE_STATUSES:
        raise ValueError("invalid implementation evidence_status")

    _require_mapping(payload, "artifact_refs")
    _require_mapping(payload, "metrics")
    correctness_dependency = _require_mapping(payload, "correctness_dependency")
    if not isinstance(correctness_dependency.get("qe_equivalent_scf_claim"), bool):
        raise ValueError("correctness_dependency.qe_equivalent_scf_claim must be boolean")

    if payload.get("final_public_family_winner") is not None:
        raise ValueError("implementation evidence must not declare a final public family winner")
    if payload.get("public_winner_claim") is True:
        raise ValueError("implementation evidence must not claim a public winner")
    if payload.get("production_release_ready") is True:
        raise ValueError("implementation evidence must not claim production release readiness")


def summarize_implementation_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    correctness_dependency = payload.get("correctness_dependency", {})
    if not isinstance(correctness_dependency, Mapping):
        correctness_dependency = {}
    return {
        "schema_version": str(payload.get("schema_version")),
        "evidence_id": str(payload.get("evidence_id")),
        "candidate_id": str(payload.get("candidate_id")),
        "execution_status": str(payload.get("execution_status")),
        "implementation_target_class": str(payload.get("implementation_target_class")),
        "evidence_kind": str(payload.get("evidence_kind")),
        "evidence_status": str(payload.get("evidence_status")),
        "claim_ceiling": str(payload.get("claim_ceiling")),
        "qe_equivalent_scf_dependency_met": correctness_dependency.get("qe_equivalent_scf_claim") is True,
    }
