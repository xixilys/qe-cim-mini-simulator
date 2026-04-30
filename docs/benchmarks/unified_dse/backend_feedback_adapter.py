from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import domain_contracts
from . import stage_b3_gem5_smoke
from . import stage_c_qe_correctness
from . import stage_d_implementation_evidence


BACKEND_REPORT_COLLECTION_SCHEMA_VERSION = "backend_execution_report_collection_v0"


def load_backend_report_artifact(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_backend_report_artifact(payload)
    return payload


def _as_reports(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if payload.get("schema_version") == domain_contracts.BACKEND_EXECUTION_REPORT_SCHEMA_VERSION:
        return [payload]
    if payload.get("schema_version") == BACKEND_REPORT_COLLECTION_SCHEMA_VERSION:
        reports = payload.get("reports", [])
        if not isinstance(reports, list):
            raise ValueError("backend execution report collection requires reports list")
        return [item for item in reports if isinstance(item, Mapping)]
    # Compatibility dispatch: a SystemC feedback artifact can be normalized through
    # synthetic backend reports by carrying top-level backend/source fields.
    if payload.get("schema_version") == "qe_dse_systemc_feedback_artifact_v0":
        reports: list[dict[str, Any]] = []
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("SystemC feedback artifact requires rows list")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("SystemC feedback rows must be mappings")
            reports.append(
                {
                    "schema_version": domain_contracts.BACKEND_EXECUTION_REPORT_SCHEMA_VERSION,
                    "candidate_id": row.get("candidate_id"),
                    "backend_class": payload.get("backend_class", "systemc_timed_functional_proxy"),
                    "source_kind": payload.get("source_kind", "timed_functional_proxy"),
                    "fidelity": row.get("fidelity", "systemc_timed_functional"),
                    "execution_status": payload.get("execution_status", "executed"),
                    "metrics": row.get("metrics", {}),
                    "claim_ceiling": row.get("claim_ceiling", payload.get("claim_ceiling")),
                    "correctness_gate": row.get("correctness_gate", {}),
                    "non_claims": row.get(
                        "non_claims",
                        ["not_qe_equivalent_scf", "not_board_measured"],
                    ),
                    "artifact_refs": row.get("artifact_refs", {}),
                }
            )
        return reports
    if payload.get("schema_version") == stage_b3_gem5_smoke.GEM5_SYSTEMC_SMOKE_REPORT_SCHEMA_VERSION:
        stage_b3_gem5_smoke.validate_gem5_smoke_report(payload)
        return [
            {
                "schema_version": domain_contracts.BACKEND_EXECUTION_REPORT_SCHEMA_VERSION,
                "candidate_id": payload.get("candidate_id"),
                "backend_class": "gem5_systemc_smoke",
                "source_kind": "gem5_smoke_report",
                "fidelity": "gem5_smoke",
                "execution_status": "executed",
                "metrics": payload.get("metrics", {}),
                "claim_ceiling": domain_contracts.GEM5_SMOKE_CLAIM_CEILING,
                "correctness_gate": payload.get("correctness_gate", {}),
                "non_claims": [
                    "not_qe_equivalent_scf",
                    "not_timed_performance",
                    "not_board_measured",
                ],
                "artifact_refs": {"gem5_smoke_report": payload.get("run_id")},
            }
        ]
    if payload.get("schema_version") == stage_c_qe_correctness.QE_CORRECTNESS_REPORT_SCHEMA_VERSION:
        stage_c_qe_correctness.validate_qe_correctness_report(payload)
        return [
            {
                "schema_version": domain_contracts.BACKEND_EXECUTION_REPORT_SCHEMA_VERSION,
                "candidate_id": payload.get("candidate_id"),
                "backend_class": "qe_correctness",
                "source_kind": "qe_correctness_report",
                "fidelity": "qe_correctness",
                "execution_status": "executed",
                "metrics": {
                    "correctness_status": payload.get("correctness_status"),
                    "qe_equivalent_scf_claim": payload.get("qe_equivalent_scf_claim") is True,
                },
                "claim_ceiling": (
                    "qe_equivalent_scf_correctness_only"
                    if payload.get("qe_equivalent_scf_claim") is True
                    else domain_contracts.CORRECTNESS_CLAIM_CEILING
                ),
                "correctness_gate": {
                    "status": payload.get("correctness_status"),
                    "qe_equivalent_scf_claim": payload.get("qe_equivalent_scf_claim") is True,
                },
                "non_claims": ["not_performance_evidence", "not_board_measured"],
                "artifact_refs": dict(payload.get("evidence_refs", {})),
            }
        ]
    if payload.get("schema_version") == stage_d_implementation_evidence.IMPLEMENTATION_EVIDENCE_SCHEMA_VERSION:
        stage_d_implementation_evidence.validate_implementation_evidence(payload)
        evidence_kind = str(payload.get("evidence_kind"))
        target = str(payload.get("implementation_target_class"))
        report_ceiling = (
            domain_contracts.BOARD_MEASURED_CLAIM_CEILING
            if evidence_kind == "fpga_board"
            else domain_contracts.IMPLEMENTATION_CLAIM_CEILING
        )
        return [
            {
                "schema_version": domain_contracts.BACKEND_EXECUTION_REPORT_SCHEMA_VERSION,
                "candidate_id": payload.get("candidate_id"),
                "backend_class": f"{target}_implementation_evidence",
                "source_kind": "implementation_evidence_report",
                "fidelity": (
                    "board_physical_measured"
                    if evidence_kind == "fpga_board"
                    else "implementation_evidence"
                ),
                "execution_status": "external_artifact_referenced",
                "metrics": payload.get("metrics", {}),
                "claim_ceiling": report_ceiling,
                "correctness_gate": payload.get("correctness_dependency", {}),
                "non_claims": [
                    "not_frontend_executed",
                    "not_final_public_winner",
                    "not_production_release_ready",
                ],
                "artifact_refs": payload.get("artifact_refs", {}),
            }
        ]
    raise ValueError("unsupported backend report artifact schema_version")


def validate_backend_report_artifact(payload: Mapping[str, Any]) -> None:
    reports = _as_reports(payload)
    candidate_fidelity_keys: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for report in reports:
        domain_contracts.validate_backend_execution_report(report)
        candidate_id = str(report.get("candidate_id"))
        fidelity = str(report.get("fidelity"))
        key = (candidate_id, fidelity)
        if key in candidate_fidelity_keys:
            duplicates.add(key)
        candidate_fidelity_keys.add(key)
    if duplicates:
        raise ValueError(f"duplicate backend report candidate/fidelity key: {sorted(duplicates)}")


def normalize_backend_report_artifact(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_backend_report_artifact(payload)
    return [
        domain_contracts.evidence_from_backend_execution_report(report)
        for report in _as_reports(payload)
    ]


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    for key in ("systemc_feedback_contract", "candidate_descriptor"):
        value = row.get(key)
        if isinstance(value, Mapping) and value.get("candidate_id"):
            return str(value["candidate_id"])
    if row.get("candidate_id"):
        return str(row["candidate_id"])
    return None


def _known_candidates(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    known: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        candidate_id = _candidate_id(row)
        if candidate_id:
            known[candidate_id] = row
    return known


def validate_evidence_join(rows: Sequence[Mapping[str, Any]], evidence_rows: Sequence[Mapping[str, Any]]) -> None:
    known = _known_candidates(rows)
    unknown = sorted(
        str(evidence.get("candidate_id"))
        for evidence in evidence_rows
        if str(evidence.get("candidate_id")) not in known
    )
    if unknown:
        raise ValueError(f"backend evidence contains unknown candidate IDs: {unknown}")
    for evidence in evidence_rows:
        row = known[str(evidence.get("candidate_id"))]
        validation = row.get("design_validation", {})
        if not isinstance(validation, Mapping) or validation.get("validity_class") != "valid_executable":
            raise ValueError(
                f"backend evidence targets non-executable candidate: {evidence.get('candidate_id')}"
            )


def apply_evidence_to_rows(
    rows: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
    evidence_ref: str | None = None,
) -> list[dict[str, Any]]:
    validate_evidence_join(rows, evidence_rows)
    by_candidate = {str(evidence["candidate_id"]): evidence for evidence in evidence_rows}
    updated = []
    for row in rows:
        copied = deepcopy(dict(row))
        candidate_id = _candidate_id(copied)
        evidence = by_candidate.get(candidate_id or "")
        if evidence is None:
            updated.append(copied)
            continue
        copied["evidence_ir"] = deepcopy(dict(evidence))
        copied["evidence_refs"] = {"backend_report": evidence_ref}
        if evidence.get("execution_status") == "executed":
            copied["result_status"] = "executed"
        copied["source_kind"] = evidence.get("source_kind", copied.get("source_kind"))
        copied["metrics"] = deepcopy(dict(evidence.get("metrics", {})))
        copied["ranking_claim_ceiling"] = _ranking_claim_ceiling(evidence)
        copied["claim_ceiling"] = evidence.get("claim_ceiling")
        updated.append(copied)
    return updated


def _ranking_claim_ceiling(evidence: Mapping[str, Any]) -> str:
    fidelity = str(evidence.get("fidelity", ""))
    if fidelity.startswith("systemc"):
        return "systemc_feedback_ranked"
    if fidelity.startswith("gem5"):
        return "gem5_feedback_ranked"
    if fidelity == "fast_model_screening":
        return domain_contracts.FAST_MODEL_SCREENING_CLAIM_CEILING
    return domain_contracts.BACKEND_REPORT_REFERENCE_CLAIM_CEILING
