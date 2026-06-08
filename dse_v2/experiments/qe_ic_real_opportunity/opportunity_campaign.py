#!/usr/bin/env python3
"""QE-IC real GPU-vs-FPGA/hybrid opportunity campaign runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dse_v2.evidence.qe_ic import analyze_qe_ic_real_baseline_opportunity
from dse_v2.experiments.qe_ic_real_opportunity.campaign_config import (
    load_json_object,
    opportunity_config_from_campaign,
    validate_qe_ic_real_opportunity_campaign_config,
)
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import build_candidate_high_fidelity_evidence
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import candidate_evidence_from_csv
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import candidate_evidence_from_ingest_payload
from dse_v2.experiments.qe_ic_real_opportunity.candidate_selection import select_layer4_candidates_for_campaign
from dse_v2.experiments.qe_ic_real_opportunity.case_setup import generate_qe_ic_benchmark_cases
from dse_v2.experiments.qe_ic_real_opportunity.case_setup import prepare_qe_ic_cases
from dse_v2.experiments.qe_ic_real_opportunity.eda_stub_evidence import build_generated_eda_stub_evidence
from dse_v2.experiments.qe_ic_real_opportunity.environment_probe import probe_qe_ic_real_opportunity_environment
from dse_v2.experiments.qe_ic_real_opportunity.gpu_baseline import baseline_from_ingest_payload
from dse_v2.experiments.qe_ic_real_opportunity.gpu_baseline import run_cpu_baseline_commands_if_available
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _input_paths(config: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in _as_mapping(config.get("input_artifacts")).items()
        if isinstance(value, str)
    }


def _artifact_summary(evidence: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    artifact = _as_mapping(evidence.get("artifact"))
    if kind in {"gpu_baseline", "cpu_baseline"}:
        return {
            "evidence_status": evidence.get("evidence_status"),
            "measurements_are_real": evidence.get("measurements_are_real") is True,
            "baseline_record_count": len(_as_list(artifact.get("baseline_records"))),
            "blocker_reasons": list(_as_list(evidence.get("blocker_reasons"))),
            "target_type": "cpu_only" if kind == "cpu_baseline" else "gpu_only",
        }
    return {
        "evidence_status": evidence.get("evidence_status"),
        "results_are_real": evidence.get("results_are_real") is True,
        "candidate_result_count": len(_as_list(artifact.get("candidate_results"))),
        "blocker_reasons": list(_as_list(evidence.get("blocker_reasons"))),
        "proxy_evidence_generated": evidence.get("proxy_evidence_generated") is True,
    }


def _candidate_evidence_by_id(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifact = _as_mapping(evidence.get("artifact"))
    return {
        str(record.get("candidate_id")): record
        for record in _as_list(artifact.get("candidate_results"))
        if isinstance(record, Mapping) and isinstance(record.get("candidate_id"), str)
    }


def _candidate_evidence_attempts(
    *,
    config: Mapping[str, Any],
    input_paths: Mapping[str, str],
    environment: Mapping[str, Any],
    candidate_path_text: str | None,
    candidate_payload: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    tools = _as_mapping(environment.get("tools"))
    profilers = _as_mapping(tools.get("profilers"))
    systemc = _as_mapping(tools.get("systemc"))
    eda = _as_mapping(tools.get("eda"))
    evidence_policy = _as_mapping(config.get("evidence_policy"))
    trace_source = input_paths.get("profile_logs")
    design_artifacts = _as_mapping(config.get("candidate_design_artifacts"))
    return [
        {
            "attempt": "ingest_existing_candidate_evidence",
            "status": "available" if candidate_payload is not None else "not_configured",
            "path": candidate_path_text,
            "reason": None if candidate_payload is not None else "no configured candidate evidence artifact was loadable",
        },
        {
            "attempt": "trace_replay",
            "status": "blocked",
            "path": trace_source,
            "reason": (
                "profile trace input is missing"
                if not trace_source or not Path(trace_source).exists()
                else "trace replay runner is not configured for this campaign"
            ),
            "tool_available": any(profilers.get(tool) for tool in ("nsys", "ncu")),
            "policy_enabled": evidence_policy.get("allow_trace_replay") is True,
        },
        {
            "attempt": "systemc_timing",
            "status": "blocked",
            "path": systemc.get("systemc_runner") or systemc.get("generic_sim"),
            "reason": (
                "SystemC/generic simulator runner is missing"
                if not (systemc.get("systemc_runner") or systemc.get("generic_sim"))
                else "candidate SystemC model/config is not configured"
            ),
            "policy_enabled": evidence_policy.get("allow_systemc_timing") is True,
        },
        {
            "attempt": "eda_resource_timing",
            "status": "blocked",
            "path": None,
            "reason": (
                "candidate design artifacts are missing"
                if not design_artifacts
                else "EDA execution requires an explicit candidate design artifact binding"
            ),
            "available_tools": _as_mapping(eda.get("available_tools")),
            "policy_enabled": evidence_policy.get("allow_vivado_or_dc_resource_timing") is True,
        },
    ]


def _execution_attempt_config(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(config.get("candidate_evidence_execution")).get(key))


def _run_candidate_evidence_command(
    *,
    attempt_name: str,
    execution_config: Mapping[str, Any],
    out_dir: Path,
    selected_candidates: list[Mapping[str, Any]],
    timeout_seconds: int = 3600,
) -> tuple[dict[str, Any], dict[str, Any]]:
    command = execution_config.get("command")
    output_json = execution_config.get("output_json")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        return (
            {
                "attempt": attempt_name,
                "status": "not_configured",
                "reason": "candidate evidence command is not configured",
            },
            candidate_evidence_from_ingest_payload(None, selected_candidates=selected_candidates),
        )
    if not isinstance(output_json, str) or not output_json:
        return (
            {
                "attempt": attempt_name,
                "status": "blocked",
                "reason": "candidate evidence output_json is not configured",
                "command": command,
            },
            candidate_evidence_from_ingest_payload(None, selected_candidates=selected_candidates),
        )
    run_dir = out_dir / "runs" / "candidate_evidence" / attempt_name
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    start_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        attempt = {
            "attempt": attempt_name,
            "status": "failed",
            "reason": str(exc),
            "command": command,
            "start_timestamp": start_timestamp,
            "end_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return attempt, candidate_evidence_from_ingest_payload(None, selected_candidates=selected_candidates)
    end_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    output_path = Path(output_json)
    attempt = {
        "attempt": attempt_name,
        "status": "executed" if result.returncode == 0 and output_path.exists() else "failed",
        "command": command,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "returncode": result.returncode,
        "stdout_log_path": str(stdout_path),
        "stderr_log_path": str(stderr_path),
        "stdout_hash": _sha256_file(stdout_path),
        "stderr_hash": _sha256_file(stderr_path),
        "output_json": str(output_path),
        "output_artifact_hash": _sha256_file(output_path) if output_path.exists() else None,
        "tool": str(execution_config.get("tool") or attempt_name),
        "version": str(execution_config.get("version") or "unknown"),
    }
    if attempt["status"] != "executed":
        attempt["reason"] = "candidate evidence command failed or did not produce output_json"
        return attempt, candidate_evidence_from_ingest_payload(None, selected_candidates=selected_candidates)
    payload = load_json_object(output_path)
    evidence = candidate_evidence_from_ingest_payload(payload, selected_candidates=selected_candidates)
    if evidence.get("results_are_real") is not True:
        attempt["status"] = "failed"
        attempt["reason"] = "candidate evidence output failed validation"
        attempt["validation"] = evidence.get("validation")
        return attempt, evidence
    artifact = _as_mapping(evidence.get("artifact"))
    records: list[dict[str, Any]] = []
    for record in _as_list(artifact.get("candidate_results")):
        if not isinstance(record, Mapping):
            continue
        row = dict(record)
        provenance = dict(_as_mapping(row.get("tool_provenance")))
        provenance.setdefault("tool", attempt["tool"])
        provenance.setdefault("version", attempt["version"])
        provenance.setdefault("run_id", f"{attempt_name}_{_stable_hash({'command': command, 'output_json': output_json})[-12:]}")
        provenance.setdefault("config_hash", _stable_hash(dict(execution_config)))
        provenance["output_artifact_hash"] = str(attempt["output_artifact_hash"])
        row["tool_provenance"] = provenance
        row["evidence_artifact_hash"] = str(attempt["output_artifact_hash"])
        records.append(row)
    evidence = build_candidate_high_fidelity_evidence(candidate_records=records, selected_candidates=selected_candidates)
    attempt["validation"] = evidence.get("validation")
    return attempt, evidence


def _run_candidate_evidence_if_available(
    *,
    config: Mapping[str, Any],
    input_paths: Mapping[str, str],
    environment: Mapping[str, Any],
    out_dir: Path,
    selected_candidates: list[Mapping[str, Any]],
    candidate_path_text: str | None,
    candidate_payload: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts = _candidate_evidence_attempts(
        config=config,
        input_paths=input_paths,
        environment=environment,
        candidate_path_text=candidate_path_text,
        candidate_payload=candidate_payload,
    )
    for attempt_name in ("trace_replay", "systemc_timing", "eda_resource_timing"):
        execution_config = _execution_attempt_config(config, attempt_name)
        if not execution_config:
            continue
        attempt, evidence = _run_candidate_evidence_command(
            attempt_name=attempt_name,
            execution_config=execution_config,
            out_dir=out_dir,
            selected_candidates=selected_candidates,
            timeout_seconds=int(_as_mapping(config.get("claim_policy")).get("candidate_evidence_timeout_seconds", 3600)),
        )
        attempts = [attempt if row.get("attempt") == attempt_name else row for row in attempts]
        if evidence.get("results_are_real") is True:
            return evidence, attempts
    return candidate_evidence_from_ingest_payload(None, selected_candidates=selected_candidates), attempts


def _proxy_candidate_evidence(
    *,
    selected_candidates: list[Mapping[str, Any]],
    baseline_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_artifact = _as_mapping(baseline_evidence.get("artifact"))
    baseline_records = _as_list(baseline_artifact.get("baseline_records"))
    baseline = _as_mapping(baseline_records[0] if baseline_records else {})
    runtime_mean = baseline.get("runtime_seconds_mean") if isinstance(baseline.get("runtime_seconds_mean"), int | float) else 100.0
    records: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected_candidates):
        candidate_id = str(candidate.get("candidate_id"))
        proxy_runtime = float(runtime_mean) * (1.20 + 0.05 * index)
        records.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": str(candidate.get("workload_family_id") or baseline.get("workload_family_id") or "generated_benchmark"),
                "motif_id": str(candidate.get("motif_id") or "generated_proxy_motif"),
                "target_type": str(candidate.get("target_type") or "fpga_only"),
                "case_id": str(baseline.get("case_id") or "generated_proxy_case"),
                "program": str(baseline.get("program") or "proxy"),
                "input_deck_hash": str(baseline.get("input_deck_hash") or "sha256:" + "0" * 64),
                "precision": str(baseline.get("precision") or "unknown_precision"),
                "evidence_level": "generated_trace_proxy",
                "evidence_status": "proxy_estimate",
                "implementation_maturity": "generated_stub",
                "trace_origin": "generated_from_qe_runtime_and_layer2_profile",
                "claim_strength": "none",
                "architecture_summary": {
                    "architecture_id": f"{candidate_id}_generated_proxy_stub",
                    "architecture_family": str(candidate.get("template_family") or "generated_proxy"),
                    "gpu_role": "baseline_reference",
                    "fpga_role": str(candidate.get("target_candidate_kind") or "generated_stub"),
                    "host_role": "scf_control_retained",
                    "dataflow_summary": "generated analytical trace proxy from baseline runtime and Layer-4 motif metadata",
                    "memory_interface": "proxy_memory_interface",
                    "synchronization_model": "proxy_barrier",
                },
                "runtime_seconds_runs": [proxy_runtime * 0.99, proxy_runtime, proxy_runtime * 1.01],
                "runtime_seconds_mean": proxy_runtime,
                "runtime_seconds_std": proxy_runtime * 0.01,
                "confidence_interval_95": {"low": proxy_runtime * 0.98, "high": proxy_runtime * 1.02},
                "workflow_runtime_seconds_mean": proxy_runtime,
                "kernel_runtime_seconds_mean": proxy_runtime * 0.75,
                "transfer_overhead_seconds": proxy_runtime * 0.10,
                "workflow_overhead_seconds": proxy_runtime * 0.05,
                "resource": {
                    "resource_feasible": True,
                    "timing_feasible": True,
                    "lut_utilization": 0.10,
                    "ff_utilization": 0.10,
                    "bram_utilization": 0.05,
                    "dsp_utilization": 0.05,
                    "hbm_port_utilization": 0.0,
                    "fmax_mhz": 200.0,
                },
                "evidence_artifact_hash": _stable_hash({"candidate_id": candidate_id, "proxy_runtime": proxy_runtime}),
                "tool_provenance": {
                    "tool": "generated_trace_proxy",
                    "version": "v0",
                    "run_id": f"{candidate_id}_generated_proxy",
                    "config_hash": _stable_hash(dict(candidate)),
                    "output_artifact_hash": _stable_hash({"candidate_id": candidate_id, "kind": "generated_proxy"}),
                },
            }
        )
    return {
        "evidence_status": "proxy_estimate",
        "results_are_real": False,
        "artifact": {
            "schema_version": "dse.qe_ic.candidate_high_fidelity_results.v1",
            "results_are_real": False,
            "candidate_results": records,
        },
        "validation": {"status": "not_applicable", "errors": [], "warnings": [{"field": "candidate_results", "message": "generated proxy evidence is not claim-gate eligible"}]},
        "blocker_reasons": [],
        "proxy_evidence_generated": True,
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
    return "inconclusive"


def _proxy_opportunity_records(
    *,
    selected_candidates: list[Mapping[str, Any]],
    baseline_evidence: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    baseline_artifact = _as_mapping(baseline_evidence.get("artifact"))
    baseline_records = _as_list(baseline_artifact.get("baseline_records"))
    baseline = _as_mapping(baseline_records[0] if baseline_records else {})
    baseline_runtime = baseline.get("runtime_seconds_mean") if isinstance(baseline.get("runtime_seconds_mean"), int | float) else None
    candidate_records = {
        str(record.get("candidate_id")): record
        for record in _as_list(_as_mapping(candidate_evidence.get("artifact")).get("candidate_results"))
        if isinstance(record, Mapping)
    }
    records: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        candidate_id = str(candidate.get("candidate_id"))
        candidate_record = _as_mapping(candidate_records.get(candidate_id))
        candidate_runtime = candidate_record.get("workflow_runtime_seconds_mean")
        speedup = float(baseline_runtime) / float(candidate_runtime) if isinstance(baseline_runtime, int | float) and isinstance(candidate_runtime, int | float) and candidate_runtime else None
        records.append(
            {
                "candidate_id": candidate_id,
                "workload_family_id": candidate.get("workload_family_id"),
                "motif_id": candidate.get("motif_id"),
                "target_type": candidate.get("target_type"),
                "architecture_summary": {
                    "template_id": candidate.get("template_id"),
                    "template_family": candidate.get("template_family"),
                },
                "gpu_baseline_id": baseline.get("baseline_id"),
                "speedup_vs_gpu_mean": speedup,
                "speedup_vs_gpu_conservative_ci": None,
                "verdict": "proxy_only_inconclusive",
                "claim_strength": "none",
                "claim_allowed": False,
                "claim_blockers": ["generated_proxy_not_claim_gate_eligible"],
                "failure_reasons": ["generated_proxy_not_claim_gate_eligible"],
                "implementation_quality_classification": "proxy_only_inconclusive",
                "final_interpretation": "Generated proxy/stub evidence is not eligible for a strong GPU-vs-FPGA claim.",
            }
        )
    return records


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


def _campaign_status(
    final_answer: Mapping[str, Any],
    environment: Mapping[str, Any],
    *,
    execute_real: bool = False,
    nonblocking: bool = False,
    candidate_summary: Mapping[str, Any] | None = None,
) -> str:
    if final_answer.get("overall_answer") == "opportunity_found":
        return "completed_real_claimable" if nonblocking else "measured"
    if nonblocking:
        if final_answer.get("overall_answer") == "proxy_only_inconclusive":
            return "completed_proxy_only"
        if final_answer.get("overall_answer") == "implementation_limited":
            return "completed_implementation_limited"
        if final_answer.get("overall_answer") == "fundamental_no_opportunity":
            return "completed_no_opportunity"
        if final_answer.get("overall_answer") == "gpu_or_eda_failure":
            return "gpu_execution_failed"
        if final_answer.get("overall_answer") == "gpu_qe_build_failed":
            return "gpu_qe_build_failed"
        if final_answer.get("overall_answer") == "gpu_qe_binary_cpu_only":
            return "gpu_qe_binary_cpu_only"
        if _as_mapping(candidate_summary).get("proxy_evidence_generated") is True:
            return "completed_proxy_only"
        return "completed_proxy_only"
    if execute_real:
        blockers = set(str(row) for row in _as_list(environment.get("blockers")))
        if "blocked_by_missing_qe" in blockers:
            return "blocked_by_missing_qe"
        if "blocked_by_missing_input_deck" in blockers:
            return "blocked_by_missing_input_deck"
        if "blocked_by_missing_candidate_evidence" in blockers:
            return "blocked_by_missing_candidate_evidence"
    if final_answer.get("overall_answer") == "evidence_missing":
        return "evidence_missing"
    if environment.get("environment_status") in {"ready", "partially_ready"}:
        return "partially_ready"
    return "blocked"


def _write_real_run_evidence_artifacts(
    *,
    out_dir: Path,
    cpu_baseline_evidence: Mapping[str, Any],
    baseline_evidence: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
    eda_stub_evidence: Mapping[str, Any] | None = None,
    candidate_attempts: list[Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    artifact_paths: dict[str, str] = {}
    cpu_baseline_artifact = _as_mapping(cpu_baseline_evidence.get("artifact"))
    if cpu_baseline_artifact:
        cpu_baseline_payload = dict(cpu_baseline_artifact)
        cpu_baseline_payload["run_records"] = list(_as_list(cpu_baseline_evidence.get("run_records")))
    else:
        cpu_baseline_payload = {
            "evidence_status": cpu_baseline_evidence.get("evidence_status"),
            "measurements_are_real": False,
            "target_type": "cpu_only",
            "blocker_reasons": list(_as_list(cpu_baseline_evidence.get("blocker_reasons"))),
            "run_records": list(_as_list(cpu_baseline_evidence.get("run_records"))),
        }
    baseline_artifact = _as_mapping(baseline_evidence.get("artifact"))
    if baseline_artifact:
        baseline_payload = dict(baseline_artifact)
        baseline_payload["run_records"] = list(_as_list(baseline_evidence.get("run_records")))
    else:
        baseline_payload = {
            "evidence_status": baseline_evidence.get("evidence_status"),
            "measurements_are_real": False,
            "target_type": "gpu_only",
            "blocker_reasons": list(_as_list(baseline_evidence.get("blocker_reasons"))),
            "run_records": list(_as_list(baseline_evidence.get("run_records"))),
        }
    candidate_payload = _as_mapping(candidate_evidence.get("artifact")) or {
        "evidence_status": candidate_evidence.get("evidence_status"),
        "results_are_real": False,
        "blocker_reasons": list(_as_list(candidate_evidence.get("blocker_reasons"))),
        "candidate_evidence_attempts": list(candidate_attempts or []),
    }
    baseline_path = out_dir / "qe_ic_gpu_baseline_measurements_real_run.json"
    cpu_baseline_path = out_dir / "qe_ic_cpu_baseline_measurements_real_run.json"
    candidate_path = out_dir / "qe_ic_candidate_high_fidelity_results_real_run.json"
    eda_stub_path = out_dir / "qe_ic_candidate_eda_stub_evidence_real_run.json"
    _write_json(cpu_baseline_path, cpu_baseline_payload)
    _write_json(baseline_path, baseline_payload)
    _write_json(candidate_path, candidate_payload)
    if eda_stub_evidence is not None and _as_mapping(eda_stub_evidence.get("artifact")):
        _write_json(eda_stub_path, _as_mapping(eda_stub_evidence.get("artifact")))
        artifact_paths["candidate_eda_stub_evidence_real_run"] = str(eda_stub_path)
    artifact_paths["cpu_baseline_measurements_real_run"] = str(cpu_baseline_path)
    artifact_paths["gpu_baseline_measurements_real_run"] = str(baseline_path)
    artifact_paths["candidate_high_fidelity_results_real_run"] = str(candidate_path)
    return artifact_paths


def _shell_env_prefix(env: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key, value in env.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            continue
        escaped = value.replace("'", "'\\''")
        parts.append(f"{key}='{escaped}'")
    return " ".join(parts)


def _bind_discovered_qe_paths(
    cases: list[dict[str, Any]],
    environment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tools = _as_mapping(environment.get("tools"))
    qe_tools = _as_mapping(tools.get("qe"))
    runtime_env = {str(key): str(value) for key, value in _as_mapping(tools.get("qe_runtime_env")).items() if isinstance(value, str)}
    env_prefix = _shell_env_prefix(runtime_env)
    bound: list[dict[str, Any]] = []
    for case in cases:
        row = dict(case)
        program = str(row.get("program"))
        executable = qe_tools.get(program)
        input_deck = row.get("input_deck_path")
        if row.get("case_status") == "ready" and isinstance(executable, str) and executable and isinstance(input_deck, str):
            row["qe_executable_path"] = executable
            row["run_environment"] = runtime_env
            command = f"{executable} -in {input_deck}"
            row["run_command"] = f"{env_prefix} {command}".strip()
            profile_command = f"nsys profile {executable} -in {input_deck}"
            row["profile_command"] = f"{env_prefix} {profile_command}".strip()
        bound.append(row)
    return bound


def run_qe_ic_real_opportunity_campaign(
    config_path: Path,
    *,
    out_dir: Path | None = None,
    execute_real: bool = False,
    allow_generated_inputs: bool = False,
    nonblocking: bool = False,
) -> dict[str, Any]:
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
    environment = probe_qe_ic_real_opportunity_environment(
        config=config,
        repo_root=Path(__file__).resolve().parents[3],
        include_qe_discovery=execute_real,
    )
    cases = prepare_qe_ic_cases(
        config,
        out_dir=output_dir if execute_real else Path("artifacts/qe_ic_real_opportunity_campaign"),
    )
    if execute_real:
        cases = _bind_discovered_qe_paths(cases, environment)
    if execute_real and allow_generated_inputs and nonblocking and not any(case.get("case_status") == "ready" for case in cases):
        cases = generate_qe_ic_benchmark_cases(cases, out_dir=output_dir, config=config)
        cases = _bind_discovered_qe_paths(cases, environment)
    if execute_real and not any(case.get("case_status") == "ready" for case in cases):
        environment.setdefault("blockers", []).append("blocked_by_missing_input_deck")
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
    should_run_baseline = execute_real and baseline_payload is None and config.get("mode") in {
        "run_if_available",
        "run_if_available_or_ingest_only",
    }
    if should_run_baseline:
        cpu_baseline_evidence = run_cpu_baseline_commands_if_available(
            cases=cases,
            environment_summary=environment,
            repeat_count=int(_as_mapping(config.get("claim_policy")).get("minimum_repeated_runs", 3)),
            run_root=output_dir / "runs",
        )
    else:
        cpu_baseline_evidence = {
            "evidence_status": "not_attempted",
            "measurements_are_real": False,
            "artifact": None,
            "validation": {
                "status": "not_applicable",
                "errors": [],
                "warnings": [{"field": "cpu_baseline", "message": "CPU baseline was not attempted in ingest mode"}],
            },
            "blocker_reasons": ["cpu_baseline_not_attempted"],
            "run_records": [],
        }
    if should_run_baseline:
        baseline_evidence = run_gpu_baseline_commands_if_available(
            cases=cases,
            environment_summary=environment,
            repeat_count=int(_as_mapping(config.get("claim_policy")).get("minimum_repeated_runs", 3)),
            run_root=output_dir / "runs",
        )
    else:
        baseline_evidence = baseline_from_ingest_payload(baseline_payload)
    if candidate_payload is None and candidate_path_text and Path(candidate_path_text).suffix.lower() == ".csv" and Path(candidate_path_text).exists():
        candidate_evidence = candidate_evidence_from_csv(Path(candidate_path_text), selected_candidates=selected_candidates)
        candidate_attempts = _candidate_evidence_attempts(
            config=config,
            input_paths=input_paths,
            environment=environment,
            candidate_path_text=candidate_path_text,
            candidate_payload=candidate_payload,
        )
    elif execute_real and candidate_payload is None and _as_mapping(config.get("candidate_evidence_execution")):
        candidate_evidence, candidate_attempts = _run_candidate_evidence_if_available(
            config=config,
            input_paths=input_paths,
            environment=environment,
            out_dir=output_dir,
            selected_candidates=selected_candidates,
            candidate_path_text=candidate_path_text,
            candidate_payload=candidate_payload,
        )
    else:
        candidate_evidence = candidate_evidence_from_ingest_payload(
            candidate_payload,
            selected_candidates=selected_candidates,
        )
        candidate_attempts = _candidate_evidence_attempts(
            config=config,
            input_paths=input_paths,
            environment=environment,
            candidate_path_text=candidate_path_text,
            candidate_payload=candidate_payload,
        )
    if nonblocking and candidate_evidence.get("results_are_real") is not True and baseline_evidence.get("measurements_are_real") is True:
        candidate_evidence = _proxy_candidate_evidence(
            selected_candidates=selected_candidates,
            baseline_evidence=baseline_evidence,
        )
        candidate_attempts = [
            *candidate_attempts,
            {
                "attempt": "generated_trace_proxy",
                "status": "generated",
                "reason": "candidate design/trace evidence missing; generated non-claimable proxy evidence",
            },
        ]
    eda_stub_evidence: dict[str, Any] | None = None
    if execute_real and nonblocking and selected_candidates:
        eda_stub_evidence = build_generated_eda_stub_evidence(
            selected_candidates=selected_candidates,
            environment=environment,
            out_dir=output_dir,
            timeout_seconds=int(_as_mapping(config.get("claim_policy")).get("candidate_evidence_timeout_seconds", 120)),
        )
        candidate_attempts = [
            *candidate_attempts,
            dict(_as_mapping(eda_stub_evidence.get("attempt"))),
        ]
    if candidate_evidence.get("results_are_real") is not True:
        environment.setdefault("blockers", []).append("blocked_by_missing_candidate_evidence")
        if not eda_stub_evidence or eda_stub_evidence.get("blocker_reasons"):
            environment.setdefault("blockers", []).append("blocked_by_missing_candidate_design")
    if nonblocking and candidate_evidence.get("proxy_evidence_generated") is True:
        opportunity_summary = {
            "claim_gate_invoked": False,
            "opportunity_records": _proxy_opportunity_records(
                selected_candidates=selected_candidates,
                baseline_evidence=baseline_evidence,
                candidate_evidence=candidate_evidence,
            ),
            "system_conclusion": {
                "overall_verdict": "proxy_only_inconclusive",
                "best_candidate_id": None,
                "best_speedup_vs_gpu": None,
                "what_evidence_is_missing": [],
            },
            "claim_boundary": CLAIM_BOUNDARY,
        }
    else:
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
    cpu_baseline_summary = _artifact_summary(cpu_baseline_evidence, kind="cpu_baseline")
    baseline_summary = _artifact_summary(baseline_evidence, kind="gpu_baseline")
    candidate_summary = _artifact_summary(candidate_evidence, kind="candidate")
    candidate_summary["attempt_count"] = len(candidate_attempts)
    final_answer = _final_answer(
        opportunity_summary=opportunity_summary,
        implementation_audit=implementation_audit,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
    )
    if nonblocking and candidate_summary.get("proxy_evidence_generated") is True and final_answer.get("overall_answer") == "inconclusive":
        final_answer["overall_answer"] = "proxy_only_inconclusive"
        final_answer["answer_text"] = (
            "Generated benchmark/proxy evidence was produced, but it is not claim-gate eligible; "
            "no strong GPU-vs-FPGA superiority claim is allowed."
        )
        final_answer["what_we_can_say"] = "The campaign continued with generated benchmark/proxy evidence."
        final_answer["what_we_cannot_say"] = "Generated proxy/stub evidence is not final measured acceleration evidence."
    if nonblocking and candidate_summary.get("proxy_evidence_generated") is True and final_answer.get("overall_answer") == "evidence_missing":
        final_answer["overall_answer"] = "proxy_only_inconclusive"
        final_answer["answer_text"] = (
            "Generated benchmark/proxy evidence was produced, but it is not claim-gate eligible; "
            "no strong GPU-vs-FPGA superiority claim is allowed."
        )
    if nonblocking and candidate_summary.get("proxy_evidence_generated") is True and final_answer.get("overall_answer") == "implementation_limited":
        final_answer["overall_answer"] = "proxy_only_inconclusive"
        final_answer["answer_text"] = (
            "Generated proxy/stub evidence is available, but it is not final measured performance; "
            "no strong GPU-vs-FPGA superiority claim is allowed."
        )
    if nonblocking and baseline_summary.get("measurements_are_real") is not True and final_answer.get("overall_answer") == "evidence_missing":
        baseline_blockers = set(str(row) for row in _as_list(baseline_summary.get("blocker_reasons")))
        if "gpu_qe_build_failed" in baseline_blockers:
            final_answer["overall_answer"] = "gpu_qe_build_failed"
            final_answer["answer_text"] = (
                "GPU-enabled QE build or discovery failed; no strong GPU-vs-FPGA superiority claim is allowed."
            )
        elif "gpu_qe_binary_cpu_only" in baseline_blockers:
            final_answer["overall_answer"] = "gpu_qe_binary_cpu_only"
            final_answer["answer_text"] = (
                "The available QE binary is CPU-only; no strong GPU-vs-FPGA superiority claim is allowed."
            )
        else:
            final_answer["overall_answer"] = "gpu_or_eda_failure"
            final_answer["answer_text"] = "Campaign could not answer the question because GPU/QE execution was unavailable."
    real_run_artifacts = (
        _write_real_run_evidence_artifacts(
            out_dir=output_dir,
            cpu_baseline_evidence=cpu_baseline_evidence,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
            eda_stub_evidence=eda_stub_evidence,
            candidate_attempts=candidate_attempts,
        )
        if execute_real
        else {}
    )
    return {
        "schema_version": QE_IC_REAL_OPPORTUNITY_CAMPAIGN_REPORT_SCHEMA_VERSION,
        "campaign_id": config.get("campaign_id"),
        "campaign_layer": CAMPAIGN_LAYER,
        "producer": PRODUCER,
        "campaign_status": _campaign_status(
            final_answer,
            environment,
            execute_real=execute_real,
            nonblocking=nonblocking,
            candidate_summary=candidate_summary,
        ),
        "mode": config.get("mode"),
        "execution_mode": "execute_real" if execute_real else "safe_template",
        "nonblocking_mode": nonblocking,
        "allow_generated_inputs": allow_generated_inputs,
        "research_question": config.get("research_question"),
        "input_artifact_index": input_paths,
        "real_run_artifacts": real_run_artifacts,
        "environment_summary": environment,
        "case_summary": cases,
        "profile_summary": profile_summary,
        "cpu_baseline_summary": cpu_baseline_summary,
        "gpu_baseline_summary": baseline_summary,
        "candidate_selection": selected_candidates,
        "candidate_selection_summary": {
            key: value
            for key, value in selection.items()
            if key != "selected_candidates"
        },
        "candidate_evidence_summary": candidate_summary,
        "candidate_evidence_attempts": candidate_attempts,
        "implementation_audit": implementation_audit,
        "opportunity_summary": opportunity_summary,
        "final_answer": final_answer,
        "claim_boundary": CLAIM_BOUNDARY,
    }
