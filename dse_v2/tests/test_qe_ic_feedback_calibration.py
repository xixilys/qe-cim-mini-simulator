#!/usr/bin/env python3
"""QE-IC Layer-6 synthetic feedback calibration regressions."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from dse_v2.feedback import qe_ic as feedback


CANDIDATE_PLAN_PATH = Path("artifacts/qe_ic_candidate_plan/qe_ic_candidate_plan.json")
L1_RESULTS_PATH = Path("artifacts/qe_ic_l1_cost_model/qe_ic_l1_cost_model_results.json")
LABELS_PATH = Path("dse_v2/testdata/qe_ic_feedback/qe_ic_synthetic_high_fidelity_labels_fixture.json")
CONFIG_PATH = Path("dse_v2/testdata/qe_ic_feedback/qe_ic_feedback_config_fixture.json")
CHECKED_IN_RESULTS_DIR = Path("artifacts/qe_ic_feedback")

FALSE_PROMOTION_LABELS = {"false_promotion", "resource_invalid", "overhead_invalid"}
WASTED_BUDGET_LABELS = FALSE_PROMOTION_LABELS | {"inconclusive"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _inputs() -> tuple[dict, dict, dict, dict]:
    return (
        _load_json(CANDIDATE_PLAN_PATH),
        _load_json(L1_RESULTS_PATH),
        _load_json(LABELS_PATH),
        _load_json(CONFIG_PATH),
    )


def _run_feedback(
    candidate_plan: dict | None = None,
    l1_results: dict | None = None,
    labels: dict | None = None,
    config: dict | None = None,
) -> dict:
    plan, l1, synthetic_labels, feedback_config = _inputs()
    return feedback.run_qe_ic_feedback_calibration(
        candidate_plan or plan,
        l1_results or l1,
        labels or synthetic_labels,
        config or feedback_config,
    )


def _decision_by_candidate(plan: dict) -> dict[str, dict]:
    return {
        decision["candidate_id"]: decision
        for decision in plan["promotion_decisions"]
    }


def _candidate_by_id(plan: dict) -> dict[str, dict]:
    return {
        candidate["candidate_id"]: candidate
        for candidate in plan["candidates"]
    }


def _labels_by_candidate(labels: dict) -> dict[str, dict]:
    return {
        label["candidate_id"]: label
        for label in labels["labels"]
    }


def test_feedback_public_api_exports_expected_functions():
    assert feedback.run_qe_ic_feedback_calibration
    assert feedback.validate_qe_ic_feedback_calibration
    assert feedback.write_qe_ic_feedback_artifacts
    assert feedback.load_qe_ic_feedback_calibration


def test_feedback_config_fixture_loads():
    config = _load_json(CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.feedback_config.v1"
    assert config["config_id"] == "qe_ic_feedback_fixture_config"
    assert config["stopping_conditions"]["decision_basis"] == "synthetic_replay_stop_decision"


def test_synthetic_labels_fixture_loads():
    labels = _load_json(LABELS_PATH)

    assert labels["schema_version"] == "dse.qe_ic.synthetic_high_fidelity_labels.v1"
    assert labels["labels"]
    assert {label["label"] for label in labels["labels"]}.issuperset(
        {"useful", "false_promotion", "resource_invalid", "overhead_invalid", "inconclusive"}
    )


def test_feedback_references_known_candidates():
    plan, _l1, labels, _config = _inputs()
    candidate_ids = set(_candidate_by_id(plan))
    result = _run_feedback()

    assert {label["candidate_id"] for label in labels["labels"]}.issubset(candidate_ids)
    assert {
        record["candidate_id"]
        for record in result["candidate_feedback_records"]
    }.issubset(candidate_ids)


def test_feedback_metrics_match_labels():
    plan, _l1, labels, _config = _inputs()
    result = _run_feedback()
    decisions = _decision_by_candidate(plan)
    labels_by_candidate = _labels_by_candidate(labels)
    promoted = {
        candidate_id
        for candidate_id, decision in decisions.items()
        if decision["decision"] == "promote"
    }
    promoted_labeled = promoted & set(labels_by_candidate)
    useful_promoted = {
        candidate_id
        for candidate_id in promoted_labeled
        if labels_by_candidate[candidate_id]["label"] == "useful"
    }

    assert result["metrics"]["candidate_label_coverage"]["labeled_candidate_count"] == len(labels["labels"])
    assert result["metrics"]["useful_candidate_count"] == sum(
        1 for label in labels["labels"] if label["label"] == "useful"
    )
    assert result["metrics"]["promotion_precision"] == len(useful_promoted) / len(promoted_labeled)


def test_false_promotion_rate_computed_correctly():
    plan, _l1, labels, _config = _inputs()
    result = _run_feedback()
    decisions = _decision_by_candidate(plan)
    labels_by_candidate = _labels_by_candidate(labels)
    promoted_labeled = {
        candidate_id
        for candidate_id, decision in decisions.items()
        if decision["decision"] == "promote" and candidate_id in labels_by_candidate
    }
    false_promotions = {
        candidate_id
        for candidate_id in promoted_labeled
        if labels_by_candidate[candidate_id]["label"] in FALSE_PROMOTION_LABELS
    }

    assert result["metrics"]["false_promotion_rate"] == len(false_promotions) / len(promoted_labeled)


def test_wasted_budget_ratio_computed_correctly():
    plan, _l1, labels, _config = _inputs()
    result = _run_feedback()
    decisions = _decision_by_candidate(plan)
    labels_by_candidate = _labels_by_candidate(labels)
    promoted_labeled = {
        candidate_id
        for candidate_id, decision in decisions.items()
        if decision["decision"] == "promote" and candidate_id in labels_by_candidate
    }
    wasted = {
        candidate_id
        for candidate_id in promoted_labeled
        if labels_by_candidate[candidate_id]["label"] in WASTED_BUDGET_LABELS
    }

    assert result["metrics"]["wasted_budget_count"] == len(wasted)
    assert result["metrics"]["wasted_budget_ratio"] == len(wasted) / len(promoted_labeled)


def test_adaptive_policy_state_has_version_and_updates():
    result = _run_feedback()

    assert result["adaptive_policy_state"]["policy_version"] == "qe_ic_layer6_heuristic_policy_v1"
    assert result["calibration_update"]["risk_threshold_updates"]
    assert result["calibration_update"]["template_adjustments"]
    assert result["adaptive_policy_state"]["next_round_priority_rules"]


def test_next_round_suggestions_reference_known_entities():
    plan, _l1, _labels, _config = _inputs()
    candidates = _candidate_by_id(plan)
    result = _run_feedback()

    for suggestion in result["adaptive_policy_state"]["next_round_candidate_suggestions"]:
        candidate = candidates[suggestion["candidate_id"]]
        assert suggestion["motif_id"] == candidate["motif_id"]
        assert suggestion["template_id"] == candidate["template_id"]
        assert suggestion["target_type"] == candidate["target_type"]
        assert suggestion["suggestion"] in {"promote", "hold", "reject"}


def test_stopping_conditions_are_evaluated():
    result = _run_feedback()
    evaluation = result["stopping_condition_evaluation"]
    condition_names = {condition["condition"] for condition in evaluation["conditions"]}

    assert evaluation["decision_basis"] == "synthetic_replay_stop_decision"
    assert {
        "max_rounds_reached",
        "high_fidelity_synthetic_label_budget_exhausted",
        "no_new_useful_candidate_for_n_rounds",
        "false_promotion_rate_below_target_threshold",
        "expected_improvement_below_threshold",
        "top_k_useful_count_target_reached",
    }.issubset(condition_names)
    assert evaluation["stop_decision"] in {"continue", "stop"}


def test_feedback_validation_passes_default_fixture():
    result = _run_feedback()
    validation = feedback.validate_qe_ic_feedback_calibration(result)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["candidate_feedback_record_count"] == len(result["candidate_feedback_records"])


def test_feedback_validation_fails_unknown_candidate_label():
    result = _run_feedback()
    result["synthetic_high_fidelity_labels"][0]["candidate_id"] = "missing_candidate"

    validation = feedback.validate_qe_ic_feedback_calibration(result)

    assert validation["status"] == "failed"
    assert any("unknown candidate" in error["message"] for error in validation["errors"])


def test_feedback_validation_fails_inconsistent_metrics():
    result = _run_feedback()
    result["metrics"]["promotion_precision"] = 0.123

    validation = feedback.validate_qe_ic_feedback_calibration(result)

    assert validation["status"] == "failed"
    assert any("promotion_precision" in error["field"] for error in validation["errors"])


def test_feedback_validation_fails_hardware_proven_claim():
    result = _run_feedback()
    result["adaptive_policy_state"]["next_round_candidate_suggestions"][0][
        "candidate_validity_level"
    ] = "C5_hardware_proven"

    validation = feedback.validate_qe_ic_feedback_calibration(result)

    assert validation["status"] == "failed"
    assert any("hardware_proven" in error["message"] for error in validation["errors"])


def test_feedback_writer_fail_closed(tmp_path: Path):
    bad_labels = _load_json(LABELS_PATH)
    bad_labels["labels"][0]["candidate_id"] = "missing_candidate"
    bad_labels_path = tmp_path / "bad_labels.json"
    bad_labels_path.write_text(json.dumps(bad_labels))
    feedback.write_qe_ic_feedback_artifacts(
        tmp_path,
        CANDIDATE_PLAN_PATH,
        L1_RESULTS_PATH,
        LABELS_PATH,
        CONFIG_PATH,
    )

    result = feedback.write_qe_ic_feedback_artifacts(
        tmp_path,
        CANDIDATE_PLAN_PATH,
        L1_RESULTS_PATH,
        bad_labels_path,
        CONFIG_PATH,
    )

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_feedback_validation.json"]
    assert (tmp_path / "qe_ic_feedback_validation.json").exists()
    assert not (tmp_path / "qe_ic_feedback_calibration.json").exists()
    assert not (tmp_path / "qe_ic_feedback_manifest.json").exists()
    assert not (tmp_path / "qe_ic_feedback_readme.md").exists()


def test_feedback_checked_in_artifacts_match_builder_output(tmp_path: Path):
    feedback.write_qe_ic_feedback_artifacts(
        tmp_path,
        CANDIDATE_PLAN_PATH,
        L1_RESULTS_PATH,
        LABELS_PATH,
        CONFIG_PATH,
    )

    for artifact in [
        "qe_ic_feedback_calibration.json",
        "qe_ic_feedback_validation.json",
        "qe_ic_feedback_manifest.json",
        "qe_ic_feedback_readme.md",
    ]:
        assert (CHECKED_IN_RESULTS_DIR / artifact).read_text() == (tmp_path / artifact).read_text()
