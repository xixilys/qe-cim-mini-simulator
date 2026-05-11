from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


ADJUDICATION_SCHEMA_VERSION = "adjudication_summary_v0"


def _candidate_id(row: Mapping[str, Any]) -> str:
    for key in ("candidate_descriptor", "evidence_ir", "backend_execution_request"):
        value = row.get(key)
        if isinstance(value, Mapping) and value.get("candidate_id"):
            return str(value["candidate_id"])
    return str(row.get("candidate_id", "unknown_candidate"))


def _ranked_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        [row for row in rows if row.get("screening_rank") is not None],
        key=lambda row: int(row.get("screening_rank") or 10**9),
    )


def build_adjudication_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    result_bundle_ref: str | None = None,
    calibration_model_ref: str | None = None,
    evidence_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    ranked = _ranked_rows(rows)
    recommendations = []
    for row in ranked[:10]:
        recommendations.append(
            {
                "candidate_id": _candidate_id(row),
                "screening_rank": row.get("screening_rank"),
                "promotion_state": row.get("promotion_state"),
                "ranking_claim_ceiling": row.get("ranking_claim_ceiling"),
                "claim_ceiling": row.get("claim_ceiling"),
                "source_kind": row.get("source_kind"),
                "metrics": deepcopy(row.get("calibrated_metrics") or row.get("metrics", {})),
                "evidence_ir_ref": row.get("evidence_refs"),
                "non_claims": list(row.get("non_claims", []))
                if isinstance(row.get("non_claims", []), list)
                else [],
            }
        )
    return {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "authority_scope": "supporting_evidence_only",
        "decision_authority": "adjudicator_memo_only",
        "claim_posture": "evidence_grade_recommendation_no_public_winner",
        "final_public_family_winner": None,
        "result_bundle_ref": result_bundle_ref,
        "calibration_model_ref": calibration_model_ref,
        "evidence_refs": list(evidence_refs or []),
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
        "non_claims": [
            "no_final_public_winner",
            "not_thesis_grade_authority",
            "not_board_measured_unless_reported_by_backend",
        ],
    }


def validate_adjudication_summary(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "authority_scope",
        "decision_authority",
        "claim_posture",
        "final_public_family_winner",
        "recommendations",
        "non_claims",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"adjudication summary missing field: {key}")
    if payload["schema_version"] != ADJUDICATION_SCHEMA_VERSION:
        raise ValueError("unsupported adjudication summary schema_version")
    if payload.get("final_public_family_winner") is not None:
        raise ValueError("adjudication summary must not declare final public family winner")
    if not isinstance(payload.get("recommendations"), list):
        raise ValueError("adjudication summary recommendations must be a list")
