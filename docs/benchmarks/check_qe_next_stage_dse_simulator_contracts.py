#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN_PATH = ROOT / ".omx/plans/ralplan-final-qe-next-stage-dse-simulator-20260414.md"
DEFAULT_CHECKLIST_PATH = ROOT / "docs/benchmarks/qe_next_stage_dse_simulator_execution_checklist_v0.md"
DEFAULT_PHASE_CONFIG_PATH = ROOT / "docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json"
DEFAULT_RESULT_SCHEMA_PATH = ROOT / "docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json"
DEFAULT_PHASE_RUNNER_PATH = ROOT / "docs/benchmarks/run_qe_next_stage_dse_phase.py"

MAIN_CASES = ["si4_pbe_uspp_small", "graphene_pbe_uspp"]
ANCHOR_CASE = "si8_pbe_nc"
CANONICAL_COVERAGE_CASE = "si8_pbe_uspp"
GENERALIZATION_CASES = ["si4_pbe_uspp_small", "graphene_pbe_uspp", "graphene_pbe_paw", "h2_tiny"]
PRIMARY_FAMILIES = ["F1", "F2"]
CONDITIONAL_FAMILIES = ["F3"]
PRIMARY_OBJECTIVE = "time_to_convergence_s"
SECONDARY_OBJECTIVE = "energy_to_convergence_j"
CONSTRAINT_METRICS = ["bytes_moved_to_convergence", "fallback_ratio", "spill_ratio"]
ACCURATE_FIELDS = [
    "gold_pass",
    "convergence_comparable_pass",
    "final_total_energy_ry",
    "final_converged",
    "final_residual_threshold_reached",
]
STATE_MACHINE = ["reject", "explain-only", "promotion-eligible"]
REJECT_STATUSES = [
    "model_error",
    "candidate_missing",
    "baseline_missing",
    "baseline_normalization_error",
    "compare_error",
]
TIE_BAND_MARGIN = 0.05


class ContractError(RuntimeError):
    pass


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise ContractError(msg)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_phase_config(path: Path) -> None:
    payload = load_json(path)
    require(payload["schema_version"] == "qe_next_stage_dse_simulator_phase_config_v0", "phase config schema_version drifted")
    require(payload["scope"]["software_family"] == "QE", "phase config software_family must be QE")
    require(payload["scope"]["rtl_deferred"] is True, "phase config must keep rtl_deferred=true")
    require(payload["scope"]["architecture_families_primary"] == PRIMARY_FAMILIES, "phase config primary families drifted")
    require(payload["scope"]["architecture_families_conditional"] == CONDITIONAL_FAMILIES, "phase config conditional families drifted")
    require(payload["layers"]["fast_layer"]["main_cases"] == MAIN_CASES, "phase config main DSE cases drifted")
    require(payload["layers"]["accurate_layer"]["anchor_cases"] == [ANCHOR_CASE], "phase config accurate anchor drifted")
    require(
        payload["layers"]["accurate_layer"]["coverage_cases"] == [CANONICAL_COVERAGE_CASE],
        "phase config accurate coverage case drifted",
    )
    require(
        payload["layers"]["accurate_layer"]["generalization_cases"] == GENERALIZATION_CASES,
        "phase config generalization cases drifted",
    )
    require(
        payload["layers"]["accurate_layer"]["generalization_release_blocking"] is False,
        "phase config generalization_release_blocking drifted",
    )
    require(payload["layers"]["fast_layer"]["primary_objective"] == PRIMARY_OBJECTIVE, "phase config primary objective drifted")
    require(payload["layers"]["fast_layer"]["secondary_objective"] == SECONDARY_OBJECTIVE, "phase config secondary objective drifted")
    require(payload["layers"]["fast_layer"]["constraint_metrics"] == CONSTRAINT_METRICS, "phase config constraint metrics drifted")
    require(payload["layers"]["accurate_layer"]["required_checks"] == ACCURATE_FIELDS, "phase config accurate fields drifted")
    require(payload["promotion_policy"]["state_machine"] == STATE_MACHINE, "phase config promotion state machine drifted")
    require(payload["promotion_policy"]["reject_statuses"] == REJECT_STATUSES, "phase config reject statuses drifted")
    require(
        payload["promotion_policy"]["explain_only_when"] == ["missing_fast_layer_metrics", "ranking_grade_ready_false"],
        "phase config explain-only policy drifted",
    )
    require(
        payload["promotion_policy"]["tie_band_rule"]["kind"] == "relative_time_margin_after_energy_tiebreak",
        "phase config tie-band kind drifted",
    )
    require(
        abs(float(payload["promotion_policy"]["tie_band_rule"]["max_relative_margin"]) - TIE_BAND_MARGIN) < 1e-12,
        "phase config tie-band margin drifted",
    )


def check_checklist(path: Path) -> None:
    text = load_text(path)
    require("QE-only" in text, "checklist missing QE-only scope")
    require("RTL" in text and "暂不作为下一阶段主结果" in text, "checklist missing RTL-deferred wording")
    for case_id in MAIN_CASES + [ANCHOR_CASE, CANONICAL_COVERAGE_CASE]:
        require(case_id in text, f"checklist missing case {case_id}")
    for metric in [PRIMARY_OBJECTIVE, SECONDARY_OBJECTIVE] + CONSTRAINT_METRICS:
        require(metric in text, f"checklist missing metric {metric}")
    require("快层" in text and "准层" in text, "checklist missing dual-layer framing")
    require("generalization coverage" in text, "checklist missing generalization coverage wording")
    require("reject" in text and "explain-only" in text and "promotion-eligible" in text, "checklist missing promotion state machine")
    require("<= 5%" in text, "checklist missing explicit tie-band threshold")
    require("projection review package" in text, "checklist missing projection review package")
    require("stage-main recommendation package" in text, "checklist missing stage-main recommendation package")
    require("stage artifact bundle manifest" in text, "checklist missing stage artifact bundle manifest")


def check_result_schema(path: Path) -> None:
    text = load_text(path)
    for metric in [PRIMARY_OBJECTIVE, SECONDARY_OBJECTIVE] + CONSTRAINT_METRICS:
        require(metric in text, f"result schema missing metric {metric}")
    require("ranking_grade_ready" in text, "result schema missing ranking_grade_ready")
    require("projection_grade_ready" in text, "result schema missing projection_grade_ready")


def check_phase_runner(path: Path) -> None:
    text = load_text(path)
    require("primary_candidate" in text, "phase runner missing primary_candidate artifact surface")
    require("fallback_candidate" in text, "phase runner missing fallback_candidate artifact surface")
    require("promotion-eligible" in text, "phase runner missing promotion state usage")
    require("tie_band_rule" in text, "phase runner missing tie-band policy wiring")
    require("projection_review" in text, "phase runner missing projection_review surface")
    require("stage_main_recommendation_package" in text, "phase runner missing stage_main_recommendation_package surface")
    require("stage_artifact_bundle_manifest" in text, "phase runner missing stage_artifact_bundle_manifest surface")
    require(
        "qe_next_stage_artifact_bundle_manifest.json" in text,
        "phase runner missing artifact bundle manifest output file",
    )


def check_plan(path: Path) -> None:
    text = load_text(path)
    require("Simulator/DSE is the next-stage mainline" in text, "plan missing simulator/DSE mainline principle")
    require("RTL is explicitly deferred" in text or "RTL deferred" in text, "plan missing RTL deferred wording")
    for case_id in MAIN_CASES + [ANCHOR_CASE, CANONICAL_COVERAGE_CASE]:
        require(case_id in text, f"plan missing case {case_id}")
    for metric in [PRIMARY_OBJECTIVE, SECONDARY_OBJECTIVE] + CONSTRAINT_METRICS:
        require(metric in text, f"plan missing metric {metric}")
    require("reject`, `explain-only`, or `promotion-eligible" in text, "plan missing reject/explain/promote state machine")
    require("tie-band rule" in text, "plan missing tie-band rule")
    require("cannot become a stage-main recommendation" in text, "plan missing F3 recommendation gate")
    for field in ACCURATE_FIELDS:
        require(field in text, f"plan missing accurate-layer field {field}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate that the next-stage QE DSE/simulator plan, checklist, phase config, runner, and result schema remain aligned."
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST_PATH)
    parser.add_argument("--phase-config", type=Path, default=DEFAULT_PHASE_CONFIG_PATH)
    parser.add_argument("--result-schema", type=Path, default=DEFAULT_RESULT_SCHEMA_PATH)
    parser.add_argument("--phase-runner", type=Path, default=DEFAULT_PHASE_RUNNER_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    check_phase_config(args.phase_config)
    print(f"[PASS] phase config: {args.phase_config}")
    check_checklist(args.checklist)
    print(f"[PASS] execution checklist: {args.checklist}")
    check_plan(args.plan)
    print(f"[PASS] plan draft/final: {args.plan}")
    check_result_schema(args.result_schema)
    print(f"[PASS] result schema: {args.result_schema}")
    check_phase_runner(args.phase_runner)
    print(f"[PASS] phase runner: {args.phase_runner}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
