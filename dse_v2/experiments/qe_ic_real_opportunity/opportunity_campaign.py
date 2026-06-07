#!/usr/bin/env python3
"""QE-IC real GPU-vs-FPGA/hybrid opportunity campaign runner."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.evidence.qe_ic import analyze_qe_ic_real_baseline_opportunity
from dse_v2.experiments.qe_ic_real_opportunity.campaign_config import (
    load_json_object,
    opportunity_config_from_campaign,
    validate_qe_ic_real_opportunity_campaign_config,
)
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import candidate_evidence_from_csv
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import candidate_evidence_from_ingest_payload
from dse_v2.experiments.qe_ic_real_opportunity.candidate_selection import select_layer4_candidates_for_campaign
from dse_v2.experiments.qe_ic_real_opportunity.case_setup import prepare_qe_ic_cases
from dse_v2.experiments.qe_ic_real_opportunity.environment_probe import probe_qe_ic_real_opportunity_environment
from dse_v2.experiments.qe_ic_real_opportunity.gpu_baseline import baseline_from_ingest_payload
from dse_v2.experiments.qe_ic_real_opportunity.gpu_baseline import run_gpu_baseline_commands_if_available
from dse_v2.experiments.qe_ic_real_opportunity.implementation_audit import audit_candidate_implementation_quality
from dse_v2.experiments.qe_ic_real_opportunity.profile_ingest import ingest_profile_logs
from dse_v2.experiments.qe_ic_real_opportunity.schema import (
    CAMPAIGN_LAYER,
    CLAIM_BOUNDARY,
    PRODUCER,
    QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION,
)


class QeIcRealOpportunityCampaignError(ValueError):
    """Raised for software/configuration errors in the real opportunity campaign."""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_optional_json(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    return load_json_object(path)


def _input_paths(config: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in _as_mapping(config.get("input_artifacts")).items()
        if isinstance(value, str)
    }


def _artifact_summary(evidence: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    artifact = _as_mapping(evidence.get("artifact"))
    if kind == "gpu_baseline":
        return {
            "evidence_status": evidence.get("evidence_status"),
            "measurements_are_real": evidence.get("measurements_are_real") is True,
            "baseline_record_count": len(_as_list(artifact.get("baseline_records"))),
            "blocker_reasons": list(_as_list(evidence.get("blocker_reasons"))),
        }
    return {
        "evidence_status": evidence.get("evidence_status"),
        "results_are_real": evidence.get("results_are_real") is True,
        "candidate_result_count": len(_as_list(artifact.get("candidate_results"))),
        "blocker_reasons": list(_as_list(evidence.get("blocker_reasons"))),
    }


def _candidate_evidence_by_id(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifact = _as_mapping(evidence.get("artifact"))
    return {
        str(record.get("candidate_id")): record
        for record in _as_list(artifact.get("candidate_results"))
        if isinstance(record, Mapping) and isinstance(record.get("candidate_id"), str)
    }


def _missing_opportunity_records(
    *,
    selected_candidates: list[Mapping[str, Any]],
    baseline_evidence: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers = sorted(
        set(
            str(row)
            for row in [
                *list(_as_list(baseline_evidence.get("blocker_reasons"))),
                *list(_as_list(candidate_evidence.get("blocker_reasons"))),
            ]
        )
    )
    if not blockers:
        blockers = ["evidence_missing"]
    rows: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        rows.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "target_type": candidate.get("target_type"),
                "architecture_summary": {
                    "template_id": candidate.get("template_id"),
                    "template_family": candidate.get("template_family"),
                },
                "gpu_baseline_id": None,
                "speedup_vs_gpu_mean": None,
                "speedup_vs_gpu_conservative_ci": None,
                "verdict": "evidence_missing",
                "claim_strength": "none",
                "claim_allowed": False,
                "claim_blockers": blockers,
                "failure_reasons": blockers,
                "implementation_quality_classification": "evidence_missing",
                "final_interpretation": "No claim is allowed until matching real GPU baseline and candidate high-fidelity evidence exist.",
            }
        )
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _temporary_gate_artifacts(
    *,
    out_dir: Path,
    config: Mapping[str, Any],
    baseline_artifact: Mapping[str, Any],
    candidate_artifact: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    input_paths = _input_paths(config)
    evidence_dir = out_dir / "_campaign_inputs"
    baseline_path = evidence_dir / "gpu_baseline_measurements.json"
    candidate_path = evidence_dir / "candidate_high_fidelity_results.json"
    opportunity_config_path = evidence_dir / "opportunity_config.json"
    _write_json(baseline_path, baseline_artifact)
    _write_json(candidate_path, candidate_artifact)
    gate_input_paths = {
        **{key: input_paths[key] for key in (
            "layer1_workload_suite",
            "layer2_motif_profile",
            "layer3_target_viability",
            "layer4_candidate_plan",
            "layer5a_l1_cost_model",
            "layer6_closed_loop_dse",
        )},
        "gpu_baseline_measurements": str(baseline_path),
        "candidate_high_fidelity_results": str(candidate_path),
    }
    opportunity_config = opportunity_config_from_campaign(config, gate_input_paths)
    _write_json(opportunity_config_path, opportunity_config)
    return gate_input_paths, opportunity_config


def _run_existing_gate(
    *,
    out_dir: Path,
    config: Mapping[str, Any],
    layer_artifacts: Mapping[str, Mapping[str, Any]],
    baseline_evidence: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
    selected_candidates: list[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline_artifact = _as_mapping(baseline_evidence.get("artifact"))
    candidate_artifact = _as_mapping(candidate_evidence.get("artifact"))
    if not baseline_artifact or not candidate_artifact:
        return {
            "claim_gate_invoked": False,
            "opportunity_records": _missing_opportunity_records(
                selected_candidates=selected_candidates,
                baseline_evidence=baseline_evidence,
                candidate_evidence=candidate_evidence,
            ),
            "system_conclusion": {
                "overall_verdict": "evidence_missing",
                "best_candidate_id": None,
                "best_speedup_vs_gpu": None,
                "what_evidence_is_missing": [
                    *list(_as_list(baseline_evidence.get("blocker_reasons"))),
                    *list(_as_list(candidate_evidence.get("blocker_reasons"))),
                ],
            },
            "claim_boundary": CLAIM_BOUNDARY,
        }

    gate_input_paths, opportunity_config = _temporary_gate_artifacts(
        out_dir=out_dir,
        config=config,
        baseline_artifact=baseline_artifact,
        candidate_artifact=candidate_artifact,
    )
    report = analyze_qe_ic_real_baseline_opportunity(
        workload_suite=layer_artifacts["layer1_workload_suite"],
        motif_profile=layer_artifacts["layer2_motif_profile"],
        target_viability=layer_artifacts["layer3_target_viability"],
        candidate_plan=layer_artifacts["layer4_candidate_plan"],
        l1_results=layer_artifacts["layer5a_l1_cost_model"],
        closed_loop_results=layer_artifacts["layer6_closed_loop_dse"],
        gpu_baseline_measurements=baseline_artifact,
        candidate_high_fidelity_results=candidate_artifact,
        opportunity_config=opportunity_config,
    )
    return {
        "claim_gate_invoked": True,
        "opportunity_records": list(_as_list(report.get("opportunity_records"))),
        "system_conclusion": dict(_as_mapping(report.get("system_conclusion"))),
        "gate_input_artifacts": gate_input_paths,
        "claim_boundary": report.get("claim_boundary"),
    }


def _top_level_from_gate(opportunity_summary: Mapping[str, Any], implementation_audit: list[Mapping[str, Any]]) -> str:
    records = _as_list(opportunity_summary.get("opportunity_records"))
    if any(isinstance(record, Mapping) and record.get("claim_allowed") is True for record in records):
        return "opportunity_found"
    classes = {str(row.get("implementation_quality_classification")) for row in implementation_audit if isinstance(row, Mapping)}
    if "implementation_limited" in classes:
        return "implementation_limited"
    if classes and classes <= {"fundamental_no_opportunity"}:
        return "fundamental_no_opportunity"
    if not opportunity_summary.get("claim_gate_invoked"):
        return "evidence_missing"
    conclusion = _as_mapping(opportunity_summary.get("system_conclusion"))
    missing = _as_list(conclusion.get("what_evidence_is_missing"))
    if missing:
        return "evidence_missing"
    if conclusion.get("overall_verdict") == "no_fpga_or_hybrid_opportunity_found":
        return "gpu_dominant_no_fpga_or_hybrid_opportunity"
    return "inconclusive"


def _attach_audit_to_opportunity_records(
    opportunity_summary: Mapping[str, Any],
    implementation_audit: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach implementation classification and interpretation to each opportunity row."""

    audit_by_id = {
        str(row.get("candidate_id")): row
        for row in implementation_audit
        if isinstance(row, Mapping) and isinstance(row.get("candidate_id"), str)
    }
    enriched = dict(opportunity_summary)
    rows: list[dict[str, Any]] = []
    for record in _as_list(opportunity_summary.get("opportunity_records")):
        if not isinstance(record, Mapping):
            continue
        row = dict(record)
        audit = _as_mapping(audit_by_id.get(str(row.get("candidate_id"))))
        classification = audit.get("implementation_quality_classification")
        if classification:
            row["implementation_quality_classification"] = classification
        if "final_interpretation" not in row:
            if row.get("claim_allowed") is True:
                row["final_interpretation"] = "Existing claim gate allows an opportunity claim for this candidate."
            elif classification == "implementation_limited":
                row["final_interpretation"] = (
                    "The current result does not allow a claim, but implementation quality leaves opportunity open."
                )
            elif classification == "fundamental_no_opportunity":
                row["final_interpretation"] = (
                    "The current evidence supports no opportunity for this candidate under the measured case."
                )
            else:
                row["final_interpretation"] = "No claim is allowed under the current evidence."
        rows.append(row)
    enriched["opportunity_records"] = rows
    return enriched


def _final_answer(
    *,
    opportunity_summary: Mapping[str, Any],
    implementation_audit: list[Mapping[str, Any]],
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
) -> dict[str, Any]:
    overall = _top_level_from_gate(opportunity_summary, implementation_audit)
    records = [record for record in _as_list(opportunity_summary.get("opportunity_records")) if isinstance(record, Mapping)]
    claimable = [record for record in records if record.get("claim_allowed") is True]
    claimable.sort(key=lambda row: float(row.get("speedup_vs_gpu_mean") or 0.0), reverse=True)
    best = claimable[0] if claimable else None
    missing: list[str] = []
    missing.extend(str(row) for row in _as_list(baseline_summary.get("blocker_reasons")))
    missing.extend(str(row) for row in _as_list(candidate_summary.get("blocker_reasons")))
    missing.extend(str(row) for row in _as_list(_as_mapping(opportunity_summary.get("system_conclusion")).get("what_evidence_is_missing")))
    missing = sorted(set(missing))

    if best:
        answer_text = (
            f"Candidate {best.get('candidate_id')} passes the claim gate with "
            f"{best.get('speedup_vs_gpu_mean'):.6g}x mean speedup versus GPU-only."
        )
        what_we_can_say = "A claim-gated opportunity is present for the selected case and candidate."
        what_we_cannot_say = "This does not generalize beyond the measured case, motif, architecture, and claim gates."
        next_actions = ["reproduce the measured runs", "promote adjacent workload cases", "collect tool-specific PPA evidence"]
    elif overall == "implementation_limited":
        answer_text = (
            "The current candidate evidence does not beat GPU-only, but the failure is classified as "
            "implementation_limited because implementation quality or idealized upper-bound evidence leaves opportunity open."
        )
        what_we_can_say = "The current implementation is weak or insufficiently calibrated."
        what_we_cannot_say = "We cannot conclude the FPGA/hybrid idea has no opportunity."
        next_actions = ["improve pipeline utilization", "calibrate SystemC/proxy evidence", "repeat workflow-level measurements"]
    elif overall == "fundamental_no_opportunity":
        answer_text = (
            "The candidate fails the claim gate, implementation quality passes, and the idealized upper bound is below 1.0."
        )
        what_we_can_say = "For this measured case and candidate, the evidence supports no FPGA/hybrid opportunity."
        what_we_cannot_say = "This does not rule out other motifs, architectures, or workload families."
        next_actions = ["try a different candidate family", "inspect workload motifs with lower GPU dominance"]
    elif overall == "evidence_missing":
        answer_text = (
            "Evidence is missing. No GPU-vs-FPGA or GPU-vs-hybrid claim is allowed without a validated real GPU "
            "baseline and candidate high-fidelity evidence."
        )
        what_we_can_say = "The campaign can prepare cases, select Layer-4 candidates, and report exact missing evidence."
        what_we_cannot_say = (
            "We cannot say FPGA-only or GPU+FPGA is faster than the GPU-only baseline without "
            "measured baseline and high-fidelity candidate evidence."
        )
        next_actions = [
            "provide at least three GPU-only QE baseline runs",
            "provide workflow-level trace replay/SystemC/gem5/real-QE candidate evidence",
            "provide Vivado or DC resource/timing evidence when making FPGA/ASIC feasibility claims",
        ]
    else:
        answer_text = "The campaign is inconclusive under the available evidence."
        what_we_can_say = "No claim gate passed."
        what_we_cannot_say = "We cannot classify the opportunity without stronger evidence."
        next_actions = ["collect missing evidence", "rerun the campaign"]

    return {
        "overall_answer": overall,
        "best_candidate_id": best.get("candidate_id") if best else None,
        "best_speedup_vs_gpu": best.get("speedup_vs_gpu_mean") if best else None,
        "answer_text": answer_text,
        "what_we_can_say": what_we_can_say,
        "what_we_cannot_say": what_we_cannot_say,
        "missing_evidence": missing,
        "next_actions": next_actions,
    }


def _campaign_status(final_answer: Mapping[str, Any], environment: Mapping[str, Any]) -> str:
    if final_answer.get("overall_answer") == "opportunity_found":
        return "measured"
    if final_answer.get("overall_answer") == "evidence_missing":
        return "evidence_missing"
    if environment.get("environment_status") in {"ready", "partially_ready"}:
        return "partially_ready"
    return "blocked"


def run_qe_ic_real_opportunity_campaign(config_path: Path, *, out_dir: Path | None = None) -> dict[str, Any]:
    """Run or ingest a QE-IC real opportunity campaign."""

    config = load_json_object(config_path)
    config_validation = validate_qe_ic_real_opportunity_campaign_config(config)
    if config_validation["status"] != "passed":
        raise QeIcRealOpportunityCampaignError(f"invalid campaign config: {config_validation['errors']}")

    input_paths = _input_paths(config)
    layer_artifacts = {
        key: load_json_object(Path(input_paths[key]))
        for key in (
            "layer1_workload_suite",
            "layer2_motif_profile",
            "layer3_target_viability",
            "layer4_candidate_plan",
            "layer5a_l1_cost_model",
            "layer6_closed_loop_dse",
        )
    }
    output_dir = out_dir or Path("artifacts/qe_ic_real_opportunity_campaign")
    environment = probe_qe_ic_real_opportunity_environment()
    cases = prepare_qe_ic_cases(config, out_dir=Path("artifacts/qe_ic_real_opportunity_campaign"))
    profile_summary = ingest_profile_logs(_load_optional_json(input_paths.get("profile_logs")))
    selection = select_layer4_candidates_for_campaign(
        candidate_plan=layer_artifacts["layer4_candidate_plan"],
        candidate_selection_config=_as_mapping(config.get("candidate_selection")),
    )
    selected_candidates = list(_as_list(selection.get("selected_candidates")))
    baseline_payload = _load_optional_json(input_paths.get("gpu_baseline_measurements")) or _load_optional_json(
        input_paths.get("gpu_baseline_runs")
    )
    candidate_path_text = input_paths.get("candidate_high_fidelity_results") or input_paths.get("candidate_evidence")
    if candidate_path_text and Path(candidate_path_text).suffix.lower() == ".csv":
        candidate_payload = None
    else:
        candidate_payload = _load_optional_json(input_paths.get("candidate_high_fidelity_results")) or _load_optional_json(
            input_paths.get("candidate_evidence")
        )
    if baseline_payload is None and config.get("mode") in {"run_if_available", "run_if_available_or_ingest_only"}:
        baseline_evidence = run_gpu_baseline_commands_if_available(
            cases=cases,
            environment_summary=environment,
            repeat_count=int(_as_mapping(config.get("claim_policy")).get("minimum_repeated_runs", 3)),
        )
    else:
        baseline_evidence = baseline_from_ingest_payload(baseline_payload)
    if candidate_payload is None and candidate_path_text and Path(candidate_path_text).suffix.lower() == ".csv" and Path(candidate_path_text).exists():
        candidate_evidence = candidate_evidence_from_csv(Path(candidate_path_text), selected_candidates=selected_candidates)
    else:
        candidate_evidence = candidate_evidence_from_ingest_payload(
            candidate_payload,
            selected_candidates=selected_candidates,
        )
    if not candidate_payload:
        environment.setdefault("blockers", []).append("blocked_by_missing_candidate_design")
    opportunity_summary = _run_existing_gate(
        out_dir=output_dir,
        config=config,
        layer_artifacts=layer_artifacts,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
        selected_candidates=selected_candidates,
    )
    implementation_audit = audit_candidate_implementation_quality(
        candidate_selection=selected_candidates,
        opportunity_records=[
            record
            for record in _as_list(opportunity_summary.get("opportunity_records"))
            if isinstance(record, Mapping)
        ],
        candidate_evidence_by_id=_candidate_evidence_by_id(candidate_evidence),
    )
    opportunity_summary = _attach_audit_to_opportunity_records(opportunity_summary, implementation_audit)
    baseline_summary = _artifact_summary(baseline_evidence, kind="gpu_baseline")
    candidate_summary = _artifact_summary(candidate_evidence, kind="candidate")
    final_answer = _final_answer(
        opportunity_summary=opportunity_summary,
        implementation_audit=implementation_audit,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
    )
    return {
        "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION,
        "campaign_id": config.get("campaign_id"),
        "campaign_layer": CAMPAIGN_LAYER,
        "producer": PRODUCER,
        "campaign_status": _campaign_status(final_answer, environment),
        "mode": config.get("mode"),
        "research_question": config.get("research_question"),
        "input_artifact_index": input_paths,
        "environment_summary": environment,
        "case_summary": cases,
        "profile_summary": profile_summary,
        "gpu_baseline_summary": baseline_summary,
        "candidate_selection": selected_candidates,
        "candidate_selection_summary": {
            key: value
            for key, value in selection.items()
            if key != "selected_candidates"
        },
        "candidate_evidence_summary": candidate_summary,
        "implementation_audit": implementation_audit,
        "opportunity_summary": opportunity_summary,
        "final_answer": final_answer,
        "claim_boundary": CLAIM_BOUNDARY,
    }
