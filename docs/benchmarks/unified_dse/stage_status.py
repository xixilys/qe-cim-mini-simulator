from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


FULL_STAGE_STATUS_NAME = "unified_dse_full_stage_status_v0.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _external_stage_status(
    artifact_ref: str | None,
    present_status: str,
    blocked_status: str,
    claim_ceiling: str,
) -> dict[str, Any]:
    if artifact_ref is None:
        return {
            "status": blocked_status,
            "artifact_ref": None,
            "execution_status": "not_executed",
            "claim_ceiling": claim_ceiling,
        }
    return {
        "status": present_status,
        "artifact_ref": artifact_ref,
        "execution_status": "external_artifact_referenced",
        "claim_ceiling": claim_ceiling,
    }


def _stage_c_status(
    artifact_ref: str | None,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if artifact_ref is None:
        return {
            "status": "blocked_waiting_qe_equivalent_correctness_report",
            "artifact_ref": None,
            "execution_status": "not_executed",
            "qe_equivalent_scf_claim": False,
            "claim_ceiling": "not_applicable",
        }
    if summary is None:
        return {
            "status": "external_correctness_report_referenced_not_proven",
            "artifact_ref": artifact_ref,
            "execution_status": "external_artifact_referenced",
            "qe_equivalent_scf_claim": False,
            "claim_ceiling": "correctness_report_reference_only",
        }
    qe_claim = summary.get("qe_equivalent_scf_claim") is True
    return {
        "status": (
            "external_qe_equivalent_correctness_pass_referenced"
            if qe_claim
            else "external_correctness_report_referenced_not_proven"
        ),
        "artifact_ref": artifact_ref,
        "execution_status": "external_artifact_referenced",
        "correctness_status": summary.get("correctness_status"),
        "compare_overall_pass": summary.get("compare_overall_pass"),
        "qe_equivalent_scf_claim": qe_claim,
        "claim_ceiling": summary.get(
            "claim_ceiling",
            "qe_equivalent_scf_correctness_only" if qe_claim else "correctness_report_reference_only",
        ),
    }


def _stage_d_status(
    artifact_ref: str | None,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if artifact_ref is None:
        return {
            "status": "blocked_waiting_fpga_asic_implementation_evidence",
            "artifact_ref": None,
            "execution_status": "not_executed",
            "claim_ceiling": "not_applicable",
        }
    if summary is None:
        return {
            "status": "external_implementation_evidence_referenced_not_release_ready",
            "artifact_ref": artifact_ref,
            "execution_status": "external_artifact_referenced",
            "claim_ceiling": "implementation_evidence_reference_only",
        }
    evidence_status = summary.get("evidence_status")
    return {
        "status": (
            "external_implementation_evidence_referenced"
            if evidence_status == "available"
            else "external_implementation_evidence_referenced_not_release_ready"
        ),
        "artifact_ref": artifact_ref,
        "execution_status": "external_artifact_referenced",
        "implementation_target_class": summary.get("implementation_target_class"),
        "evidence_kind": summary.get("evidence_kind"),
        "evidence_status": evidence_status,
        "qe_equivalent_scf_dependency_met": summary.get("qe_equivalent_scf_dependency_met"),
        "claim_ceiling": summary.get("claim_ceiling", "implementation_evidence_reference_only"),
    }


def emit_full_stage_status(
    output_dir: Path | str,
    manifest: Mapping[str, Any],
    stage_b0_descriptor_manifest_ref: str | None,
    systemc_feedback_ref: str | None,
    gem5_smoke_report_ref: str | None = None,
    backend_execution_report_ref: str | None = None,
    backend_execution_report_summary: Mapping[str, Any] | None = None,
    qe_correctness_report_ref: str | None = None,
    qe_correctness_summary: Mapping[str, Any] | None = None,
    implementation_evidence_ref: str | None = None,
    implementation_evidence_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    stage_a_gates = {
        key: bool(manifest.get(key))
        for key in (
            "backend_neutral_schema_present",
            "systemc_feedback_contract_present",
            "gem5_handoff_contract_present",
            "qe_anchor_refs_present",
            "ranking_semantics_present",
            "claim_boundary_present",
        )
    }
    stage_a_complete = all(stage_a_gates.values()) and manifest.get("stage_a_gate_blockers") == {}
    stage_b0_generated = manifest.get("stage_b0_descriptor_generation_status") == "generated_not_executed"
    payload = {
        "schema_version": "unified_dse_full_stage_status_v0",
        "authority_scope": "supporting_evidence_only",
        "claim_posture": "no_public_winner_until_adjudicator",
        "final_public_family_winner": None,
        "stages": {
            "stage_a_dse_core": {
                "status": "complete" if stage_a_complete else "blocked",
                "gates": stage_a_gates,
                "claim_ceiling": "stage_a_screening_only",
            },
            "stage_b0_descriptor_handoff": {
                "status": "generated_not_executed" if stage_b0_generated else "not_requested",
                "descriptor_manifest_ref": stage_b0_descriptor_manifest_ref,
                "claim_ceiling": "descriptor_generation_only",
            },
            "stage_b1_b2_systemc_feedback": {
                "status": (
                    "feedback_artifact_ingested"
                    if systemc_feedback_ref is not None
                    else "blocked_waiting_systemc_feedback_artifact"
                ),
                "artifact_ref": systemc_feedback_ref,
                "claim_ceiling": (
                    "timed_functional_proxy_feedback_only"
                    if systemc_feedback_ref is not None
                    else "not_applicable"
                ),
            },
            "stage_b3_gem5_systemc_smoke": _external_stage_status(
                gem5_smoke_report_ref,
                present_status="external_smoke_report_referenced",
                blocked_status="blocked_waiting_gem5_systemc_smoke_report",
                claim_ceiling="gem5_systemc_smoke_only",
            ),
            "stage_b_backend_execution_report": {
                "status": (
                    "external_backend_report_referenced"
                    if backend_execution_report_ref is not None
                    else "blocked_waiting_backend_execution_report"
                ),
                "artifact_ref": backend_execution_report_ref,
                "execution_status": (
                    str(backend_execution_report_summary.get("execution_status"))
                    if backend_execution_report_summary is not None
                    else "not_executed"
                ),
                "fidelity": (
                    backend_execution_report_summary.get("fidelity")
                    if backend_execution_report_summary is not None
                    else None
                ),
                "claim_ceiling": (
                    backend_execution_report_summary.get("claim_ceiling")
                    if backend_execution_report_summary is not None
                    else "not_applicable"
                ),
            },
            "stage_c_qe_equivalent_scf": _stage_c_status(
                qe_correctness_report_ref,
                qe_correctness_summary,
            ),
            "stage_d_fpga_asic_implementation": _stage_d_status(
                implementation_evidence_ref,
                implementation_evidence_summary,
            ),
        },
        "non_claims": [
            "no_hidden_systemc_execution",
            "no_hidden_gem5_execution",
            "no_qe_equivalent_scf_without_correctness_report",
            "no_rtl_hls_board_claim_without_external_evidence",
            "no_final_public_winner",
        ],
    }
    _write_json(Path(output_dir) / FULL_STAGE_STATUS_NAME, payload)
    return payload
