from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import result_analysis


SYSTEMC_FEEDBACK_ARTIFACT_SCHEMA_VERSION = "qe_dse_systemc_feedback_artifact_v0"


def load_systemc_feedback_artifact(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SYSTEMC_FEEDBACK_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported SystemC feedback artifact schema_version")
    if not isinstance(payload.get("rows"), list):
        raise ValueError("SystemC feedback artifact requires a rows list")
    return payload


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    contract = row.get("systemc_feedback_contract", {})
    if isinstance(contract, Mapping) and contract.get("candidate_id"):
        return str(contract["candidate_id"])
    return None


def _feedback_by_candidate(feedback: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    by_candidate: dict[str, Mapping[str, Any]] = {}
    rows = feedback.get("rows", [])
    if not isinstance(rows, Sequence):
        return by_candidate
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        candidate_id = item.get("candidate_id")
        if candidate_id:
            by_candidate[str(candidate_id)] = item
    return by_candidate


def _metrics_from_feedback(item: Mapping[str, Any]) -> dict[str, Any]:
    metrics = item.get("metrics", {})
    if not isinstance(metrics, Mapping):
        raise ValueError("SystemC feedback row metrics must be a mapping")
    return dict(metrics)


def apply_systemc_feedback(
    rows: Sequence[Mapping[str, Any]],
    feedback: Mapping[str, Any],
    feedback_ref: str | None = None,
) -> list[dict[str, Any]]:
    execution_status = str(feedback.get("execution_status", "not_executed"))
    source_kind = str(feedback.get("source_kind", "timed_functional_proxy"))
    by_candidate = _feedback_by_candidate(feedback)
    updated_rows: list[dict[str, Any]] = []
    for row in rows:
        copied = deepcopy(dict(row))
        candidate_id = _candidate_id(copied)
        feedback_row = by_candidate.get(candidate_id or "")
        if feedback_row is None:
            updated_rows.append(copied)
            continue

        copied["metrics"] = _metrics_from_feedback(feedback_row)
        copied["source_kind"] = source_kind
        copied["result_status"] = "executed" if execution_status == "executed" else "dry_run"
        projection = copied.get("projection", {})
        if not isinstance(projection, Mapping):
            projection = {}
        copied["projection"] = dict(projection)
        copied["projection"]["ranking_grade_ready"] = result_analysis.metrics_are_ranking_grade(
            copied["metrics"]
        )
        systemc_feedback = copied.get("systemc_feedback_contract", {})
        if isinstance(systemc_feedback, Mapping):
            copied["systemc_feedback_contract"] = dict(systemc_feedback)
            copied["systemc_feedback_contract"].update(
                {
                    "status": "feedback_artifact_ingested",
                    "execution_status": execution_status,
                    "metrics_ref": feedback_ref,
                    "claim_ceiling": "timed_functional_proxy_contract_only",
                    "subprocess_invoked": execution_status == "executed",
                }
            )
        copied["systemc_feedback_ingest"] = {
            "schema_version": "qe_dse_systemc_feedback_ingest_v0",
            "feedback_ref": feedback_ref,
            "candidate_id": candidate_id,
            "execution_status": execution_status,
            "source_kind": source_kind,
            "claim_ceiling": "timed_functional_proxy_feedback_only",
        }
        updated_rows.append(copied)
    return updated_rows
