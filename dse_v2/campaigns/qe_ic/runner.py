#!/usr/bin/env python3
"""System-level QE-IC closed-loop DSE campaign runner."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.campaigns.qe_ic.campaign_config import validate_qe_ic_closed_loop_dse_campaign_config
from dse_v2.campaigns.qe_ic.schema import (
    CLAIM_BOUNDARY,
    LAYER_NAME,
    PRODUCER,
    QE_IC_CLOSED_LOOP_RESULTS_SCHEMA_VERSION,
    REQUIRED_LAYERS,
)
from dse_v2.candidates.qe_ic import validate_qe_ic_candidate_plan, write_qe_ic_candidate_plan_artifacts
from dse_v2.evaluation.qe_ic.l1_cost_model import (
    validate_qe_ic_l1_cost_model_results,
    write_qe_ic_l1_cost_model_artifacts,
)
from dse_v2.feedback.qe_ic import run_qe_ic_feedback_calibration, validate_qe_ic_feedback_calibration
from dse_v2.feedback.qe_ic.feedback_config import validate_qe_ic_feedback_config
from dse_v2.feedback.qe_ic.replay import validate_qe_ic_synthetic_high_fidelity_labels
from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile, write_qe_ic_motif_profile_artifacts
from dse_v2.viability.qe_ic import validate_qe_ic_target_viability, write_qe_ic_target_viability_artifacts
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite, write_qe_ic_workload_suite_artifacts


class QeIcClosedLoopCampaignError(ValueError):
    """Raised when closed-loop campaign inputs cannot be loaded or validated."""


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise QeIcClosedLoopCampaignError(f"{path} does not exist") from exc
    if not isinstance(payload, dict):
        raise QeIcClosedLoopCampaignError(f"{path} did not contain a JSON object")
    return payload


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _artifact_path(config: Mapping[str, Any], key: str) -> Path:
    return Path(str(_as_mapping(config.get("artifact_paths")).get(key, "")))


def _regeneration_path(config: Mapping[str, Any], key: str) -> Path:
    return Path(str(_as_mapping(config.get("regeneration_inputs")).get(key, "")))


def _status_row(layer: str, path: Path, validation: Mapping[str, Any], source: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "artifact": str(path),
        "source": source,
        "status": validation.get("status", "failed"),
        "error_count": len(_as_list(validation.get("errors"))),
        "warning_count": len(_as_list(validation.get("warnings"))),
    }


def _ensure_or_regenerate_layer_artifacts(config: Mapping[str, Any]) -> None:
    if config.get("artifact_mode") != "regenerate_missing":
        return
    if not _artifact_path(config, "layer1_workload_suite").exists():
        write_qe_ic_workload_suite_artifacts(_artifact_path(config, "layer1_workload_suite").parent)
    if not _artifact_path(config, "layer2_motif_profile").exists():
        write_qe_ic_motif_profile_artifacts(
            _artifact_path(config, "layer2_motif_profile").parent,
            _artifact_path(config, "layer1_workload_suite"),
            _regeneration_path(config, "layer2_profile_sources"),
        )
    if not _artifact_path(config, "layer3_target_viability").exists():
        write_qe_ic_target_viability_artifacts(
            _artifact_path(config, "layer3_target_viability").parent,
            _artifact_path(config, "layer1_workload_suite"),
            _artifact_path(config, "layer2_motif_profile"),
            _regeneration_path(config, "layer3_target_config"),
        )
    if not _artifact_path(config, "layer4_candidate_plan").exists():
        write_qe_ic_candidate_plan_artifacts(
            _artifact_path(config, "layer4_candidate_plan").parent,
            _artifact_path(config, "layer1_workload_suite"),
            _artifact_path(config, "layer2_motif_profile"),
            _artifact_path(config, "layer3_target_viability"),
            _regeneration_path(config, "layer4_campaign_config"),
        )
    if not _artifact_path(config, "layer5a_l1_cost_model").exists():
        write_qe_ic_l1_cost_model_artifacts(
            _artifact_path(config, "layer5a_l1_cost_model").parent,
            _artifact_path(config, "layer1_workload_suite"),
            _artifact_path(config, "layer2_motif_profile"),
            _artifact_path(config, "layer3_target_viability"),
            _artifact_path(config, "layer4_candidate_plan"),
            _regeneration_path(config, "layer5a_l1_model_config"),
        )


def _candidate_by_id(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("candidate_id")): candidate
        for candidate in _as_list(plan.get("candidates"))
        if isinstance(candidate, Mapping)
    }


def _decision_by_candidate(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(decision.get("candidate_id")): decision
        for decision in _as_list(plan.get("promotion_decisions"))
        if isinstance(decision, Mapping)
    }


def _l1_by_candidate(l1_results: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(result.get("candidate_id")): result
        for result in _as_list(l1_results.get("results"))
        if isinstance(result, Mapping)
    }


def _feedback_by_candidate(feedback_calibration: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(record.get("candidate_id")): record
        for record in _as_list(feedback_calibration.get("candidate_feedback_records"))
        if isinstance(record, Mapping)
    }


def _validity_level(
    *,
    decision: Mapping[str, Any],
    l1_result: Mapping[str, Any],
    feedback_record: Mapping[str, Any],
) -> str:
    label = feedback_record.get("synthetic_label")
    if label in {"useful", "false_rejection"}:
        return "C2_synthetic_feedback_useful"
    if label in {"false_promotion", "resource_invalid", "overhead_invalid"}:
        return "C3_synthetic_feedback_false_promotion"
    if decision.get("decision") == "promote" and l1_result:
        return "C1_l1_plausible"
    if decision.get("decision") in {"hold", "reject"} or label == "inconclusive":
        return "C4_high_fidelity_required"
    return "C0_contract_valid"


def _build_candidate_trajectory(
    *,
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    feedback_calibration: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = _candidate_by_id(candidate_plan)
    decisions = _decision_by_candidate(candidate_plan)
    l1_by_candidate = _l1_by_candidate(l1_results)
    feedback_by_candidate = _feedback_by_candidate(feedback_calibration)
    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]
        decision = _as_mapping(decisions.get(candidate_id))
        l1_result = _as_mapping(l1_by_candidate.get(candidate_id))
        feedback_record = _as_mapping(feedback_by_candidate.get(candidate_id))
        rows.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "template_id": candidate.get("template_id"),
                "target_type": candidate.get("target_type"),
                "layer4_decision": decision.get("decision"),
                "layer4_promotion_score": decision.get("promotion_score"),
                "has_l1_result": bool(l1_result),
                "l1_next_fidelity_suggestion": _as_mapping(l1_result.get("next_fidelity_suggestion")).get("suggestion") if l1_result else None,
                "synthetic_label": feedback_record.get("synthetic_label"),
                "next_round_suggestion": feedback_record.get("feedback_class"),
                "candidate_validity_level": _validity_level(
                    decision=decision,
                    l1_result=l1_result,
                    feedback_record=feedback_record,
                ),
            }
        )
    return rows


def _system_summary(
    *,
    suite: Mapping[str, Any],
    motif_profile: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    candidate_plan: Mapping[str, Any],
    l1_results: Mapping[str, Any],
    feedback_calibration: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _as_mapping(feedback_calibration.get("metrics"))
    stopping = _as_mapping(feedback_calibration.get("stopping_condition_evaluation"))
    return {
        "workload_family_count": len(_as_list(suite.get("workload_families"))),
        "motif_profile_count": len(_as_list(motif_profile.get("family_target_profiles"))),
        "target_viability_record_count": len(_as_list(target_viability.get("viability_records"))),
        "candidate_count": len(_as_list(candidate_plan.get("candidates"))),
        "promoted_candidate_count": _as_mapping(candidate_plan.get("summary")).get("promote_count", 0),
        "l1_result_count": len(_as_list(l1_results.get("results"))),
        "synthetic_label_count": _as_mapping(metrics.get("candidate_label_coverage")).get("labeled_candidate_count", 0),
        "useful_candidate_count": metrics.get("useful_candidate_count", 0),
        "false_promotion_count": metrics.get("false_promotion_count", 0),
        "promotion_precision": metrics.get("promotion_precision", 0.0),
        "wasted_budget_ratio": metrics.get("wasted_budget_ratio", 0.0),
        "stop_decision": stopping.get("stop_decision"),
        "stop_reasons": list(_as_list(stopping.get("stop_reasons"))),
    }


def _next_round_plan(feedback_calibration: Mapping[str, Any]) -> dict[str, Any]:
    adaptive = _as_mapping(feedback_calibration.get("adaptive_policy_state"))
    return {
        "policy_version": adaptive.get("policy_version"),
        "acquisition_priorities": list(_as_list(adaptive.get("next_round_priority_rules"))),
        "candidate_suggestions": list(_as_list(adaptive.get("next_round_candidate_suggestions"))),
        "stopping_condition_evaluation": dict(_as_mapping(feedback_calibration.get("stopping_condition_evaluation"))),
        "decision_basis": "synthetic_replay_stop_decision",
    }


def run_qe_ic_closed_loop_dse_campaign(config: Mapping[str, Any]) -> dict[str, Any]:
    """Run the system-level QE-IC closed-loop synthetic replay campaign."""

    config_validation = validate_qe_ic_closed_loop_dse_campaign_config(config)
    if config_validation.get("status") != "passed":
        raise QeIcClosedLoopCampaignError(f"invalid campaign config: {config_validation['errors']}")
    _ensure_or_regenerate_layer_artifacts(config)

    suite_path = _artifact_path(config, "layer1_workload_suite")
    motif_path = _artifact_path(config, "layer2_motif_profile")
    viability_path = _artifact_path(config, "layer3_target_viability")
    candidate_path = _artifact_path(config, "layer4_candidate_plan")
    l1_path = _artifact_path(config, "layer5a_l1_cost_model")
    labels_path = _artifact_path(config, "layer6_synthetic_labels")
    feedback_config_path = _artifact_path(config, "layer6_feedback_config")

    suite = _load_json_object(suite_path)
    motif_profile = _load_json_object(motif_path)
    target_viability = _load_json_object(viability_path)
    candidate_plan = _load_json_object(candidate_path)
    l1_results = _load_json_object(l1_path)
    labels = _load_json_object(labels_path)
    feedback_config = _load_json_object(feedback_config_path)

    validations = {
        "layer1_workload_suite": validate_qe_ic_workload_suite(suite),
        "layer2_motif_profile": validate_qe_ic_motif_profile(motif_profile),
        "layer3_target_viability": validate_qe_ic_target_viability(target_viability),
        "layer4_candidate_plan": validate_qe_ic_candidate_plan(candidate_plan),
        "layer5a_l1_cost_model": validate_qe_ic_l1_cost_model_results(l1_results),
        "layer6_synthetic_labels": validate_qe_ic_synthetic_high_fidelity_labels(labels),
        "layer6_feedback_config": validate_qe_ic_feedback_config(feedback_config),
    }
    failures = [
        f"{key}: {validation.get('errors')}"
        for key, validation in validations.items()
        if validation.get("status") != "passed"
    ]
    if failures:
        raise QeIcClosedLoopCampaignError("; ".join(failures))

    feedback_calibration = run_qe_ic_feedback_calibration(
        candidate_plan,
        l1_results,
        labels,
        feedback_config,
    )
    feedback_validation = validate_qe_ic_feedback_calibration(feedback_calibration)
    if feedback_validation.get("status") != "passed":
        raise QeIcClosedLoopCampaignError(f"invalid feedback calibration: {feedback_validation['errors']}")

    artifact_index = {
        "layer1_workload_suite": str(suite_path),
        "layer2_motif_profile": str(motif_path),
        "layer3_target_viability": str(viability_path),
        "layer4_candidate_plan": str(candidate_path),
        "layer5a_l1_cost_model": str(l1_path),
        "layer6_feedback_calibration": "embedded_feedback_summary",
    }
    layer_status = [
        _status_row("layer1_workload_suite", suite_path, validations["layer1_workload_suite"], "artifact_replay"),
        _status_row("layer2_motif_profile", motif_path, validations["layer2_motif_profile"], "artifact_replay"),
        _status_row("layer3_target_viability", viability_path, validations["layer3_target_viability"], "artifact_replay"),
        _status_row("layer4_candidate_plan", candidate_path, validations["layer4_candidate_plan"], "artifact_replay"),
        _status_row("layer5a_l1_cost_model", l1_path, validations["layer5a_l1_cost_model"], "artifact_replay"),
        _status_row("layer6_feedback_calibration", Path("embedded_feedback_summary"), feedback_validation, "synthetic_replay"),
    ]
    source_artifacts = {
        "layer1_workload_suite": copy.deepcopy(suite),
        "layer2_motif_profile": copy.deepcopy(motif_profile),
        "layer3_target_viability": copy.deepcopy(target_viability),
        "layer4_candidate_plan": copy.deepcopy(candidate_plan),
        "layer5a_l1_cost_model": copy.deepcopy(l1_results),
    }
    return {
        "schema_version": QE_IC_CLOSED_LOOP_RESULTS_SCHEMA_VERSION,
        "campaign_id": config.get("campaign_id"),
        "layer": LAYER_NAME,
        "producer": PRODUCER,
        "campaign_config": copy.deepcopy(config),
        "artifact_index": artifact_index,
        "layer_status": layer_status,
        "source_artifacts": source_artifacts,
        "system_summary": _system_summary(
            suite=suite,
            motif_profile=motif_profile,
            target_viability=target_viability,
            candidate_plan=candidate_plan,
            l1_results=l1_results,
            feedback_calibration=feedback_calibration,
        ),
        "candidate_trajectory": _build_candidate_trajectory(
            candidate_plan=candidate_plan,
            l1_results=l1_results,
            feedback_calibration=feedback_calibration,
        ),
        "feedback_summary": feedback_calibration,
        "adaptive_policy_state": copy.deepcopy(feedback_calibration.get("adaptive_policy_state")),
        "next_round_plan": _next_round_plan(feedback_calibration),
        "claim_boundary": CLAIM_BOUNDARY,
    }
