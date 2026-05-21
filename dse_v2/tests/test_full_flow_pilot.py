#!/usr/bin/env python3
"""Regression coverage for profile-driven full-flow SystemC evidence pilots."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import dse_v2.backends.gem5_systemc_adapter as gem5_adapter_module
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.backends.gem5_systemc_adapter import Gem5SystemCClosureAdapter
from dse_v2.codesign.artifacts import build_codesign_l4_evidence, build_default_codesign_artifacts
from dse_v2.contracts import SCHEMA_REGISTRY, validate_instance
from dse_v2.core.workload import create_sparse_spmv_graph, package_from_graph
from dse_v2.reference_workloads.dft_qe import QE_SCF_REQUIRED_COVERAGE, create_qe_reference_package
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.evidence.full_flow import (
    REQUIRED_EVIDENCE_FILES,
    build_gem5_l4_proof,
    classify_gem5_l4_non_smoke,
    claim_can_be_trusted,
    write_full_flow_evidence,
)
from dse_v2.mapping.search import select_initial_mapping
from dse_v2.registry import ExperimentRegistry
from dse_v2.scripts.dse.run_full_flow_pilot import _build_campaign_evaluation_plan, build_pilot_architecture


REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_full_flow_pilot.py"


def _run_pilot(tmp_path, backend: str, extra_args=None):
    out_dir = tmp_path / f"qe_scf_shell_{backend}"
    cmd = [
        sys.executable,
        str(PILOT),
        "--workload",
        "qe_scf_shell",
        "--backend",
        backend,
        "--evidence-mode",
        "debug",
        "--npw",
        "128",
        "--nkb",
        "16",
        "--m",
        "8",
        "--nfft",
        "1024",
        "--out",
        str(out_dir),
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    return out_dir, result


def _flatten_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_strings(item)


def test_full_flow_pilot_writes_required_evidence(tmp_path):
    out_dir, result = _run_pilot(tmp_path, "systemc")
    assert result.returncode == 0, result.stdout + result.stderr

    for rel in REQUIRED_EVIDENCE_FILES:
        assert (out_dir / rel).exists(), f"missing evidence artifact: {rel}"
    for rel in [
        "step1/step1_status.json",
        "step1/workload_package.json",
        "step1/workload_graph.json",
        "step1/graph_lowering_report.json",
        "step1/executable_graph.json",
        "step1/profile_manifest.json",
        "step1/importer_manifest.json",
        "step1/step1_artifact_validation.json",
    ]:
        assert (out_dir / rel).exists(), f"missing Step1 artifact: {rel}"

    step1_status = json.loads((out_dir / "step1" / "step1_status.json").read_text())
    assert step1_status["status"] == "complete"
    assert step1_status["profile_id"] == "qe_scf_reference"
    assert step1_status["importer_id"] == "qe_reference_fixture"
    assert step1_status["full_workload_eligible"] is True

    for rel in [
        "step2/step2_status.json",
        "step2/architecture_search_space.json",
        "step2/search_checkpoint.json",
        "step2/top_k_candidate_queue.json",
        "step2/architecture_candidate_generation_report.json",
        "step2/architecture_screening_report.json",
        "step2/trial_state_ledger.json",
        "step2/step3_simulation_queue.json",
        "step2/step2_artifact_validation.json",
    ]:
        assert (out_dir / rel).exists(), f"missing Step2 artifact: {rel}"

    step2_validation = json.loads((out_dir / "step2" / "step2_artifact_validation.json").read_text())
    step2_ledger = json.loads((out_dir / "step2" / "trial_state_ledger.json").read_text())
    step2_checkpoint = json.loads((out_dir / "step2" / "search_checkpoint.json").read_text())
    step2_top_k = json.loads((out_dir / "step2" / "top_k_candidate_queue.json").read_text())
    candidate_generation = json.loads((out_dir / "step2" / "architecture_candidate_generation_report.json").read_text())
    screening_report = json.loads((out_dir / "step2" / "architecture_screening_report.json").read_text())
    assert step2_validation["valid"] is True
    assert step2_ledger["schema_version"] == "dse.step2.trial_state_ledger.v1"
    assert step2_ledger["trusted_final_claim"] is False
    assert step2_ledger["queue_mode"] == "selected-entry-only"
    assert step2_ledger["all_candidates_have_parameter_hash"] is True
    assert "queued_for_step3" in step2_ledger["state_counts"]
    assert step2_checkpoint["policy_name"] == step2_top_k["policy_name"]
    assert step2_checkpoint["policy_name"] == "hierarchical_funnel"
    assert step2_checkpoint["top_k_candidate_queue_artifact"] == "top_k_candidate_queue.json"
    assert step2_checkpoint["top_k_queue_provenance_only"] is True
    assert step2_checkpoint["release_completion_eligible"] is False
    assert step2_checkpoint["trusted_final_claim"] is False
    assert step2_top_k["queue_mode"] == "top-k-provenance-only"
    assert step2_top_k["step3_queue_mode"] == "selected-entry-only"
    assert step2_top_k["provenance_only"] is True
    assert step2_top_k["execution_order_suggestion_only"] is True
    assert step2_top_k["top_k_or_representative_completion_allowed"] is False
    assert step2_top_k["release_completion_eligible"] is False
    assert step2_top_k["trusted_final_claim"] is False
    assert candidate_generation["search_checkpoint_artifact"] == "search_checkpoint.json"
    assert candidate_generation["top_k_candidate_queue_artifact"] == "top_k_candidate_queue.json"
    assert candidate_generation["trial_state_ledger_artifact"] == "trial_state_ledger.json"
    assert candidate_generation["search_policy_name"] == "hierarchical_funnel"
    assert candidate_generation["search_policy_provenance_only"] is True
    assert candidate_generation["trusted_final_claim"] is False
    assert screening_report["search_checkpoint_artifact"] == "search_checkpoint.json"
    assert screening_report["top_k_candidate_queue_artifact"] == "top_k_candidate_queue.json"
    assert screening_report["top_k_queue_mode"] == "top-k-provenance-only"
    assert screening_report["top_k_queue_provenance_only"] is True
    assert screening_report["trusted_final_claim"] is False

    assert (out_dir / "campaign.json").exists()
    assert (out_dir / "campaign_ledger.json").exists()
    assert (out_dir / "campaign_evaluation_plan.json").exists()
    campaign = json.loads((out_dir / "campaign.json").read_text())
    campaign_ledger = json.loads((out_dir / "campaign_ledger.json").read_text())
    evaluation_plan = json.loads((out_dir / "campaign_evaluation_plan.json").read_text())
    validate_instance(campaign, SCHEMA_REGISTRY["dse.contract.campaign.v1"])
    validate_instance(campaign_ledger, SCHEMA_REGISTRY["dse.contract.campaign_ledger.v1"])
    validate_instance(evaluation_plan, SCHEMA_REGISTRY["dse.contract.campaign_evaluation_plan.v1"])
    assert campaign["campaign_id"] == step2_ledger["campaign_id"]
    assert campaign["status"] == "active"
    assert campaign["final_completion_status"] is None
    assert campaign["budgets"]["broad_evidence_run"] is False
    assert campaign["budgets"]["step3_queue_entry_budget"] == 1
    assert campaign["budgets"]["step3_admission_policy"] == "selected_entry_only"
    assert campaign["budgets"]["top_k_widening_requested"] is False
    assert campaign["budgets"]["top_k_widening_allowed"] is False
    assert campaign["budgets"]["top_k_budget_requires_materialized_step3_queue"] is True
    assert campaign["policies"]["top_k_queue_role"] == "provenance_only_not_step3_admission"
    assert "DFT" not in "".join(campaign.keys())
    assert campaign_ledger["campaign_id"] == step2_ledger["campaign_id"]
    assert campaign_ledger["workload_run_id"] == step2_ledger["workload_run_id"]
    assert campaign_ledger["trial_id"] == step2_ledger["trial_id"]
    assert campaign_ledger["broad_evidence_run"] is False
    assert campaign_ledger["trusted_final_claim"] is False
    assert campaign_ledger["release_completion_eligible"] is False
    assert campaign_ledger["workload_run_ref"]["workload_package"] == "step1/workload_package.json"
    assert campaign_ledger["control_plane_refs"]["campaign_evaluation_plan"] == "campaign_evaluation_plan.json"
    assert campaign_ledger["campaign_evaluation_plan_ref"] == "campaign_evaluation_plan.json"
    assert campaign_ledger["step2_refs"]["trial_state_ledger"] == "step2/trial_state_ledger.json"
    assert campaign_ledger["step2_refs"]["search_checkpoint"] == "step2/search_checkpoint.json"
    assert campaign_ledger["step3_refs"]["simulation_request"] == "simulation_request.json"
    assert campaign_ledger["step3_refs"]["simulation_result"] == "simulation_result.json"
    assert campaign_ledger["selected_trial_refs"]["queue_mode"] == "selected-entry-only"
    assert not any("dft rtl/ppa" in item.lower() for item in campaign_ledger["resume_next_actions"])
    assert evaluation_plan["campaign_id"] == step2_ledger["campaign_id"]
    assert evaluation_plan["workload_run_id"] == step2_ledger["workload_run_id"]
    assert evaluation_plan["trial_id"] == step2_ledger["trial_id"]
    assert evaluation_plan["plan_scope"] == "bounded_selected_entry_pilot"
    assert evaluation_plan["selected_entry_only"] is True
    assert evaluation_plan["broad_evidence_run"] is False
    assert evaluation_plan["release_completion_eligible"] is False
    assert evaluation_plan["trusted_final_claim"] is False
    assert evaluation_plan["top_k_candidate_queue_ref"] == "step2/top_k_candidate_queue.json"
    assert evaluation_plan["step3_simulation_queue_ref"] == "step2/step3_simulation_queue.json"
    assert evaluation_plan["planned_entry_count"] == 1
    assert len(evaluation_plan["planned_entries"]) == evaluation_plan["planned_entry_count"]
    assert evaluation_plan["planned_entries"][0]["admission_source"] == "step2/step3_simulation_queue.json"
    assert evaluation_plan["planned_entries"][0]["execution_allowed"] is True
    assert evaluation_plan["admission_control"]["step3_admission_authority"] == "step2/step3_simulation_queue.json"
    assert evaluation_plan["admission_control"]["top_k_queue_role"] == "provenance_only_not_step3_admission"
    assert evaluation_plan["admission_control"]["widening_requested_by_budget"] is False
    assert evaluation_plan["admission_control"]["hidden_evidence_fanout_allowed"] is False
    assert evaluation_plan["search_feedback_loop"]["observe_api"] == "SearchPolicy.observe(candidate_id, metrics)"
    assert evaluation_plan["search_feedback_loop"]["feedback_update_ref"] == "feedback_update.json"
    ledger_candidate_ids = {row["candidate_id"] for row in step2_ledger["candidates"]}
    assert evaluation_plan["planned_entries"][0]["mapping_candidate_id"] in ledger_candidate_ids

    verdict = json.loads((out_dir / "verdict.json").read_text())
    assert verdict["trusted_for_final_ranking"] is True
    assert verdict["binding_status"]["standalone_systemc_full_workload"] == "implemented"
    assert verdict["binding_status"]["gem5_systemc_full_workload"] == "not_run"
    assert verdict["numerical_validation_passed"] is True
    assert verdict["numerical_validation_scope"] == "generic_systemc_timing_numeric_reference"
    assert verdict["status_boundary"]["fixed_timing_smoke_done_evidence"] == "unsupported"
    assert verdict["status_boundary"]["predicted_only_done_evidence"] == "unsupported"

    sim_result = json.loads((out_dir / "simulation_result.json").read_text())
    feedback_update = json.loads((out_dir / "feedback_update.json").read_text())
    search_policy_updates = [
        update for update in feedback_update["updates"]
        if update.get("target") == "search_policy"
    ]
    assert search_policy_updates
    assert search_policy_updates[0]["observe_api"] == "SearchPolicy.observe(candidate_id, metrics)"
    assert search_policy_updates[0]["candidate_refs"]["mapping_candidate_id"]
    assert search_policy_updates[0]["candidate_refs"]["mapping_parameter_hash"].startswith("sha256:")
    assert search_policy_updates[0]["metrics"]["step4_verdict"] == "trusted_pass"
    assert search_policy_updates[0]["metrics"]["promoted"] is True
    assert sim_result["status"] == "passed"
    assert sim_result["missing_required_coverage"] == []
    assert sim_result["numerical_validation"]["passed"] is True
    for phase in QE_SCF_REQUIRED_COVERAGE:
        phase_result = sim_result["phase_results"][phase]
        assert phase_result["status"] == "available"
        assert phase_result["latency_ms"] >= 0.0
        assert phase_result["cycles_estimate"] is not None

    artifact_manifest = json.loads((out_dir / "artifact_manifest.json").read_text())
    artifacts = {entry["path"]: entry for entry in artifact_manifest["artifacts"]}
    for rel in REQUIRED_EVIDENCE_FILES:
        assert artifacts[rel]["exists"] is True
    assert artifacts["campaign.json"]["exists"] is True
    assert artifacts["campaign_ledger.json"]["exists"] is True
    assert artifacts["campaign_evaluation_plan.json"]["exists"] is True
    assert artifacts["step1/step1_status.json"]["exists"] is True
    assert artifacts["step1/step1_artifact_validation.json"]["exists"] is True
    assert artifacts["step2/search_checkpoint.json"]["exists"] is True
    assert artifacts["step2/top_k_candidate_queue.json"]["exists"] is True
    assert artifacts["step2/trial_state_ledger.json"]["exists"] is True
    assert artifacts["step2/step2_artifact_validation.json"]["exists"] is True

    architecture = json.loads((out_dir / "architecture.json").read_text())
    accelerator_types = {
        accelerator["accel_type"]
        for accelerator in architecture["system_architecture"]["accelerators"]
    }
    assert {"gpu", "fpga", "cim"}.issubset(accelerator_types)
    assert "4-cluster" not in architecture["architecture_scope"]

    mapping = json.loads((out_dir / "mapping.json").read_text())
    for phase in QE_SCF_REQUIRED_COVERAGE:
        assert phase in mapping["placements"]
    assert len(set(mapping["placements"].values())) >= 3
    assert mapping["trusted_final_eligible"] is True

    numerical = json.loads((out_dir / "numerical_validation.json").read_text())
    assert numerical["passed"] is True
    assert numerical["status"] == "pass"
    assert numerical["scope"] == "generic_systemc_timing_numeric_reference"
    assert numerical["summary"]["failed_check_count"] == 0

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["trusted_for_final_ranking"] is True
    replay = manifest["replay_metadata"]
    assert replay["python_replay_command"][:2] == [
        "python3",
        "dse_v2/scripts/dse/run_full_flow_pilot.py",
    ]
    assert replay["simulator_replay_command"]


def test_campaign_evaluation_plan_requires_step3_queue_materialization_for_top_k_widening(tmp_path):
    step2_dir = tmp_path / "step2"
    step2_dir.mkdir()
    (step2_dir / "step3_simulation_queue.json").write_text(json.dumps({
        "schema_version": "dse.step3.simulation_queue.v1",
        "queue_mode": "selected-entry-only",
        "entry_count": 1,
        "entries": [
            {
                "queue_entry_id": "q-selected",
                "candidate_id": "arch::m-selected",
                "mapping_candidate_id": "m-selected",
                "architecture_id": "arch",
                "design_point_id": "dp",
                "mapping_id": "mapping",
                "promoted_for_simulation": True,
                "queue_state": "scheduled_for_simulation",
            }
        ],
    }), encoding="utf-8")
    (step2_dir / "top_k_candidate_queue.json").write_text(json.dumps({
        "schema_version": "dse.step2.top_k_candidate_queue.v1",
        "queue_mode": "top-k-provenance-only",
        "entry_count": 2,
        "entries": [
            {
                "top_k_entry_id": "top-k-1",
                "candidate_id": "m-selected",
                "mapping_candidate_id": "m-selected",
                "architecture_id": "arch",
                "top_k_rank": 1,
                "parameter_hash": "sha256:selected",
                "priority_score": 10.0,
            },
            {
                "top_k_entry_id": "top-k-2",
                "candidate_id": "m-other",
                "mapping_candidate_id": "m-other",
                "architecture_id": "arch",
                "top_k_rank": 2,
                "parameter_hash": "sha256:other",
                "priority_score": 9.0,
            },
        ],
    }), encoding="utf-8")
    package = package_from_graph(create_sparse_spmv_graph("campaign_budget_widening_guard"))

    plan = _build_campaign_evaluation_plan(
        args=SimpleNamespace(),
        run_dir=tmp_path,
        run_id="run",
        workload_package=package,
        scope={"campaign_id": "campaign", "workload_run_id": "workload", "trial_id": "trial"},
        budgets={
            "top_k_widening_requested": True,
            "top_k_widening_allowed": True,
            "top_k_admission_budget": 1,
            "broad_evidence_run": False,
        },
    )

    assert plan["selected_entry_only"] is True
    assert plan["broad_evidence_run"] is False
    assert plan["planned_entry_count"] == 1
    assert plan["deferred_entry_count"] == 1
    assert plan["admission_control"]["widening_requested_by_budget"] is True
    assert plan["admission_control"]["widening_allowed_by_budget"] is True
    assert plan["admission_control"]["materialized_step3_queue_required"] is True
    assert plan["admission_control"]["hidden_evidence_fanout_allowed"] is False
    assert plan["deferred_entries"][0]["mapping_candidate_id"] == "m-other"
    assert plan["deferred_entries"][0]["admission_status"] == "deferred_requires_step3_queue_materialization"
    assert "materialized_step3_queue_entry_required" in plan["deferred_entries"][0]["budget_widening_blockers"]


def test_generic_full_flow_pilot_campaign_ledger_is_domain_neutral(tmp_path):
    out_dir, result = _run_pilot(tmp_path, "systemc", extra_args=[
        "--workload",
        "generic_tensor_chain",
        "--profile",
        "ml_tensor",
        "--importer",
        "generic_json",
        "--generator",
        "tensor_chain",
    ])
    assert result.returncode == 0, result.stdout + result.stderr

    ledger = json.loads((out_dir / "campaign_ledger.json").read_text())
    evaluation_plan = json.loads((out_dir / "campaign_evaluation_plan.json").read_text())
    assert ledger["workload_family"] == "ml_tensor"
    assert ledger["broad_evidence_run"] is False
    assert ledger["selected_trial_refs"]["queue_mode"] == "selected-entry-only"
    assert evaluation_plan["planned_entry_count"] == 1
    assert evaluation_plan["selected_entry_only"] is True
    assert evaluation_plan["broad_evidence_run"] is False
    assert not any("dft" in item.lower() or "qe" in item.lower() for item in _flatten_strings(ledger))
    assert not any("dft" in item.lower() or "qe" in item.lower() for item in _flatten_strings(evaluation_plan))


def test_full_flow_pilot_optionally_records_registry_trial(tmp_path):
    registry_db = tmp_path / "campaign.sqlite"
    out_dir, result = _run_pilot(
        tmp_path,
        "systemc",
        extra_args=[
            "--registry-db",
            str(registry_db),
            "--registry-campaign",
            "pilot_campaign",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr

    registry = ExperimentRegistry(registry_db)
    campaigns = registry.list_campaigns()

    assert len(campaigns) == 1
    assert campaigns[0].name == "pilot_campaign"
    assert campaigns[0].status == "running"
    assert campaigns[0].metadata["runner"] == "run_full_flow_pilot"
    assert campaigns[0].metadata["logical_campaign_id"].startswith("campaign::")
    workload_runs = registry.query_workload_runs(campaign_id=campaigns[0].campaign_id)
    assert len(workload_runs) == 1
    assert workload_runs[0].status == "ready_for_step2"
    assert workload_runs[0].campaign_id == campaigns[0].campaign_id

    trials = registry.query_trials(campaign_id=campaigns[0].campaign_id, fidelity="L3")
    assert len(trials) == 1
    assert trials[0].status == "simulated"
    assert trials[0].workload_run_id == workload_runs[0].workload_run_id
    assert trials[0].params["workload"] == "qe_scf_shell"
    assert trials[0].params["backend"] == "systemc"
    assert trials[0].params["run_id"] == "qe_scf_reference_systemc"
    assert trials[0].metrics["trusted_for_final_ranking"] is True
    assert trials[0].artifacts["run_dir"] == str(out_dir)
    assert trials[0].artifacts["campaign"] == str(out_dir / "campaign.json")
    assert trials[0].artifacts["campaign_ledger"] == str(out_dir / "campaign_ledger.json")
    assert trials[0].artifacts["campaign_evaluation_plan"] == str(out_dir / "campaign_evaluation_plan.json")
    assert trials[0].artifacts["verdict"] == str(out_dir / "verdict.json")
    artifact_refs = registry.list_artifact_refs(campaign_id=campaigns[0].campaign_id)
    assert {ref.path for ref in artifact_refs}.issuperset({
        "campaign.json",
        "campaign_ledger.json",
        "campaign_evaluation_plan.json",
        "step1/workload_package.json",
        "step2/trial_state_ledger.json",
        "step2/step3_simulation_queue.json",
        "simulation_request.json",
        "simulation_result.json",
    })
    step1_refs = [ref for ref in artifact_refs if ref.path.startswith("step1/")]
    trial_refs = [
        ref for ref in artifact_refs
        if ref.path.startswith("step2/") or ref.path in {"simulation_request.json", "simulation_result.json"}
    ]
    plan_refs = [ref for ref in artifact_refs if ref.path == "campaign_evaluation_plan.json"]
    assert step1_refs
    assert all(ref.workload_run_id == workload_runs[0].workload_run_id for ref in step1_refs)
    assert all(ref.trial_id is None for ref in step1_refs)
    assert len(plan_refs) == 1
    assert plan_refs[0].workload_run_id == workload_runs[0].workload_run_id
    assert plan_refs[0].trial_id == trials[0].trial_id
    assert trial_refs
    assert all(ref.workload_run_id == workload_runs[0].workload_run_id for ref in trial_refs)
    assert all(ref.trial_id == trials[0].trial_id for ref in trial_refs)


def test_missing_required_phase_blocks_systemc_trusted_verdict(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="missing_phase_systemc",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "systemc"},
    )

    omitted_phase = "veff"
    events = []
    current_ns = 0.0
    for phase in QE_SCF_REQUIRED_COVERAGE:
        if phase == omitted_phase:
            continue
        node = graph.nodes[phase]
        events.append({
            "node_id": phase,
            "op_type": node.op_type,
            "device": mapping.get(phase, "host"),
            "start_ns": current_ns,
            "end_ns": current_ns + 1000.0,
        })
        current_ns += 1000.0

    out_dir = tmp_path / "missing_phase_systemc"
    evidence = write_full_flow_evidence(
        run_dir=out_dir,
        backend="systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request={
            "run_id": "missing_phase_systemc",
            "architecture": architecture.to_dict(),
        },
        simulation_result={
            "schema_version": "gsim.result.v1",
            "run_id": "missing_phase_systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.0, "power_w": 10.0, "energy_j": 0.01},
            "events": events,
        },
        simulator_cmd=["generic_sim"],
        simulator_returncode=0,
        systemc_stdout="",
        systemc_stderr="",
        cli_command=["python3", "dse_v2/scripts/dse/run_end_to_end_dse.py"],
        workload_package=package,
    )

    verdict = json.loads((out_dir / "verdict.json").read_text())
    report = json.loads((out_dir / "final_report.json").read_text())
    validation = json.loads((out_dir / "claim_validation.json").read_text())

    assert evidence["trusted_for_final_ranking"] is False
    assert omitted_phase in evidence["missing_required_coverage"]
    assert verdict["trusted_for_final_ranking"] is False
    assert verdict["phase_coverage_passed"] is False
    assert verdict["numerical_validation_passed"] is False
    assert verdict["binding_status"]["standalone_systemc_full_workload"] == "blocked"
    assert report["trusted_ranking"] == []
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert validation["passed"] is True


def test_numerical_validation_failure_blocks_systemc_trusted_verdict(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="bad_numeric_systemc",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "systemc"},
    )
    backend = GenericSystemCBackend(mode="standalone_systemc")
    request = backend._build_request(design_point, graph, workload_package=package, output_dir=tmp_path / "bad_numeric_systemc")
    events = [
        {
            "node_id": phase,
            "op_type": graph.nodes[phase].op_type,
            "device": mapping.get(phase, "host"),
            "start_ns": 0.0,
            "end_ns": 0.0,
        }
        for phase in QE_SCF_REQUIRED_COVERAGE
    ]

    out_dir = tmp_path / "bad_numeric_systemc"
    evidence = write_full_flow_evidence(
        run_dir=out_dir,
        backend="systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request=request,
        simulation_result={
            "schema_version": "gsim.result.v1",
            "run_id": "bad_numeric_systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.0, "power_w": 10.0, "energy_j": 0.01},
            "events": events,
        },
        simulator_cmd=["generic_sim"],
        simulator_returncode=0,
        systemc_stdout="",
        systemc_stderr="",
        cli_command=["python3", "dse_v2/scripts/dse/run_end_to_end_dse.py"],
        workload_package=package,
    )

    verdict = json.loads((out_dir / "verdict.json").read_text())
    numerical = json.loads((out_dir / "numerical_validation.json").read_text())
    report = json.loads((out_dir / "final_report.json").read_text())

    assert evidence["trusted_for_final_ranking"] is False
    assert verdict["phase_coverage_passed"] is True
    assert verdict["numerical_validation_passed"] is False
    assert numerical["passed"] is False
    assert numerical["summary"]["failed_check_count"] > 0
    assert report["trusted_ranking"] == []
    assert any("Numerical validation failed" in gap for gap in verdict["evidence_gaps"])


def test_gem5_systemc_backend_requires_real_l4_flag(tmp_path):
    out_dir, result = _run_pilot(tmp_path, "gem5_systemc")

    assert result.returncode == 2
    assert "--gem5-real-l4" in result.stderr
    assert "synthetic gem5 evidence generation has been removed" in result.stderr
    assert (out_dir / "step1" / "step1_status.json").exists()
    assert not (out_dir / "verdict.json").exists()
    assert not (out_dir / "simulation_result.json").exists()

    gem5_claim = {
        "claim_type": "feasibility",
        "source_fidelity": "L4",
        "backend": "gem5_systemc",
        "predicted_only": False,
        "evidence_ids": [],
    }
    assert claim_can_be_trusted(gem5_claim, {"trusted_for_final_ranking": False}) is False


def test_gem5_systemc_good_result_requires_and_accepts_l4_proof(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="trusted_gem5_systemc",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "gem5_systemc"},
    )
    backend = GenericSystemCBackend(mode="standalone_systemc")
    run = backend.run_simulation(design_point, graph, workload_package=package, output_dir=tmp_path / "trusted_gem5_systemc_raw")
    assert run["returncode"] == 0
    assert run["result"]["status"] == "passed"

    out_dir = tmp_path / "trusted_gem5_systemc"
    gem5_log = "\n".join([
        "100: system.generic_accel: descriptor_read verified=true addr=0x8000000 request_addr=0x8001000 result_addr=0x8120000 request_bytes=1024",
        "120: system.generic_accel: uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 request_bytes=1024 micro_ops=4 result_bytes=2048 result_path=/tmp/result.json result_file_written=true total_cycles=123 total_payload_bytes=4096",
        "180: system.generic_accel: microarchitecture_execute verified=true engine=gem5_generic_accel_microarchitecture_v1 micro_ops=4 result_bytes=2048 result_path=/tmp/result.json cycles=123",
        "200: system.generic_accel: completion_writeback verified=true result_addr=0x8120000 completion_addr=0x8110000 result_bytes=2048 cycles=123 error_code=0",
    ])
    driver_stdout = "\n".join([
        "generic_accel_l4_status=1 error_code=0",
        "completion_magic=0x4753494d completion_status=0 cycles=123 result_addr=0x8120000",
    ])

    evidence = write_full_flow_evidence(
        run_dir=out_dir,
        backend="gem5_systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request=run["request"],
        simulation_result=run["result"],
        simulator_cmd=["gem5.opt", "generic_accel_l4_test.py"],
        simulator_returncode=0,
        systemc_stdout=driver_stdout,
        systemc_stderr="",
        cli_command=["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py", "--backend", "gem5_systemc", "--gem5-real-l4"],
        gem5_attempted=True,
        gem5_log=gem5_log,
        workload_package=package,
    )

    verdict = json.loads((out_dir / "verdict.json").read_text())
    proof = json.loads((out_dir / "gem5_l4_proof.json").read_text())
    report = json.loads((out_dir / "final_report.json").read_text())
    validation = json.loads((out_dir / "claim_validation.json").read_text())

    assert evidence["trusted_for_final_ranking"] is True
    assert verdict["trusted_for_final_ranking"] is True
    assert verdict["binding_status"]["gem5_systemc_full_workload"] == "implemented"
    assert verdict["gem5_l4_proof_passed"] is True
    assert verdict["gem5_systemc_blockers"] == []
    assert proof["passed"] is True
    assert proof["proof_status"] == "passed"
    assert set(proof["required_checks"]) == {
        "descriptor_read_verified",
        "request_decode_verified",
        "microarchitecture_execute_verified",
        "completion_writeback_verified",
        "driver_status_verified",
        "driver_completion_descriptor_verified",
        "result_status_passed",
        "non_smoke_l4_activity",
    }
    assert proof["non_smoke_classification"]["classification"] == "non_smoke"
    assert proof["missing_evidence"] == []
    assert proof["source_artifacts"]["gem5_log"] == "gem5.log"
    trusted_claims = [item for item in validation["validations"] if item["trusted"]]
    assert trusted_claims
    assert all("gem5_l4_proof.json" in item["evidence_ids"] for item in trusted_claims)
    assert "gem5_l4_proof.json" in report["trusted_ranking"][0]["evidence_ids"]
    assert "gem5_l4_proof.json" in report["selected_recommendation"]["evidence_ids"]


def test_codesign_artifacts_expose_l4_calibration_and_reference_feedback_hooks():
    graph = create_sparse_spmv_graph("codesign_calibration_hooks")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="codesign_calibration_hooks",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"backend": "gem5_systemc"},
    )

    artifacts = build_default_codesign_artifacts(
        design_point=design_point,
        workload_package=package,
        executable_graph=graph,
        architecture_artifact=architecture.to_dict(),
        selected_record={"mapping_candidate_id": "seeded_candidate", "score": 1.0},
        promotion_decision={"step3_evaluable": True, "reason": "test calibration hook"},
        backend="gem5_systemc",
        evidence_mode="summary",
        l4_required=True,
    )

    assert artifacts["runtime_schedule"]["copy_compute_overlap"]["requires_l4_calibration"] is True
    assert artifacts["codesign_candidate"]["promotion_policy"]["l4_required"] is True

    l4 = build_codesign_l4_evidence(
        codesign_candidate=artifacts["codesign_candidate"],
        backend="gem5_systemc",
        sim_result={
            "status": "passed",
            "metrics": {"latency_ms": 3.5, "dma_time_ms": 0.4, "device_time_ms": 2.6},
            "resource_utilization": {"accelerator_busy_fraction": 0.75},
            "gem5_systemc_blockers": [],
        },
        gem5_l4_proof={
            "passed": True,
            "checks": {
                "descriptor_read_verified": True,
                "request_decode_verified": True,
                "microarchitecture_execute_verified": True,
                "completion_writeback_verified": True,
                "driver_status_verified": True,
                "driver_completion_descriptor_verified": True,
                "result_status_passed": True,
            },
            "missing_evidence": [],
            "source_artifacts": {"gem5_log": "gem5.log", "systemc_stdout": "systemc_stdout.log"},
        },
        gem5_log=(
            "descriptor_read verified=true request_bytes=1024\n"
            "uarch_request_decode verified=true result_bytes=2048\n"
            "microarchitecture_execute verified=true cycles=123\n"
            "completion_writeback verified=true cycles=123\n"
        ),
        gem5_stdout="generic_accel_l4_status=1 error_code=0\ncompletion_magic=0x4753494d completion_status=0 cycles=123\n",
        trusted_for_final=True,
    )

    feedback = l4["codesign_verdict"]["calibration_feedback"]
    assert feedback["status"] == "available"
    assert feedback["latency_ms"] == 3.5
    assert feedback["dma_time_ms"] == 0.4
    assert l4["dma_trace"]["total_payload_bytes_observed"] == 3072
    assert l4["mmio_trace"]["mmio_count"] >= 4


def test_gem5_microarchitecture_result_uses_internal_consistency_gate(tmp_path):
    graph = create_sparse_spmv_graph("trusted_gem5_uarch")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    architecture = build_pilot_architecture()
    mapping = {node_id: "host" for node_id in graph.nodes}
    design_point = DesignPoint(
        design_point_id="trusted_gem5_uarch",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "sparse_spmv", "backend": "gem5_systemc"},
    )
    backend = GenericSystemCBackend(mode="gem5_systemc")
    request = backend._build_request(design_point, graph, workload_package=package, output_dir=tmp_path / "trusted_gem5_uarch")
    total_flops = sum(float(node.estimated_flops or 0.0) for node in graph.nodes.values())
    events = [
        {"node_id": "load_csr", "op_type": "dma_load", "device": "host", "start_ns": 100.0, "end_ns": 200.0},
        {"node_id": "spmv", "op_type": "spmv", "device": "host", "start_ns": 200.0, "end_ns": 700.0},
        {"node_id": "norm", "op_type": "reduction", "device": "host", "start_ns": 700.0, "end_ns": 800.0},
    ]
    device_time_ms = sum(event["end_ns"] - event["start_ns"] for event in events) / 1e6
    latency_ms = 0.001
    power_w = 10.0
    resource_utilization = {
        device: {"compute_percent": 0.0, "memory_percent": 0.0, "bandwidth_percent": 0.0}
        for device in ["host", "gpu-0", "fpga-0", "cim-0"]
    }
    resource_utilization["host"]["compute_percent"] = device_time_ms / latency_ms * 100.0
    microarchitecture_details = {
        device: {
            "accel_type": "host" if device == "host" else "accelerator",
            "compute_cycles": 1 if device == "host" else 0,
            "dma_cycles": 0,
            "stall_cycles": 0,
            "memory_accesses": 0,
            "pipeline_utilization": 0.1 if device == "host" else 0.0,
            "array_utilization": 0.1 if device == "host" else 0.0,
            "power_breakdown": {"compute_w": 0.0, "memory_w": 0.0, "interconnect_w": 0.0},
        }
        for device in ["host", "gpu-0", "fpga-0", "cim-0"]
    }
    sim_result = {
        "schema_version": "gsim.result.v2",
        "run_id": "trusted_gem5_uarch",
        "status": "passed",
        "execution_engine": "gem5_generic_accel_microarchitecture_v1",
        "metrics": {
            "latency_ms": latency_ms,
            "host_time_ms": 0.0,
            "device_time_ms": device_time_ms,
            "dma_time_ms": 0.0,
            "throughput_gops": total_flops / latency_ms / 1e6,
            "power_w": power_w,
            "energy_j": power_w * latency_ms / 1000.0,
            "area_mm2": 0.0,
            "total_data_movement_mb": 0.0,
        },
        "resource_utilization": resource_utilization,
        "microarchitecture_details": microarchitecture_details,
        "events": events,
        "uncertainty": {"fidelity_level": "L4-gem5-uarch", "confidence_level": 0.9, "mape_percent": 8.0},
        "microarchitecture_summary": {
            "engine": "gem5_generic_accel_microarchitecture_v1",
            "micro_op_count": len(events) + 2,
            "total_cycles": 250,
            "total_flops": int(total_flops),
        },
    }
    gem5_log = "\n".join([
        "100: system.generic_accel: descriptor_read verified=true addr=0x8000000 request_addr=0x8001000 result_addr=0x8120000 request_bytes=1024",
        "120: system.generic_accel: uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 request_bytes=1024 micro_ops=5 result_bytes=2048 result_path=/tmp/result.json result_file_written=true total_cycles=250 total_payload_bytes=4096",
        "180: system.generic_accel: microarchitecture_execute verified=true engine=gem5_generic_accel_microarchitecture_v1 micro_ops=5 result_bytes=2048 result_path=/tmp/result.json cycles=250",
        "200: system.generic_accel: completion_writeback verified=true result_addr=0x8120000 completion_addr=0x8110000 result_bytes=2048 cycles=250 error_code=0",
    ])

    evidence = write_full_flow_evidence(
        run_dir=tmp_path / "trusted_gem5_uarch",
        backend="gem5_systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request=request,
        simulation_result=sim_result,
        simulator_cmd=["gem5.opt", "generic_accel_l4_test.py"],
        simulator_returncode=0,
        systemc_stdout="generic_accel_l4_status=1 error_code=0\ncompletion_magic=0x4753494d completion_status=0 cycles=250 result_addr=0x8120000\n",
        systemc_stderr="",
        cli_command=["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py", "--backend", "gem5_systemc", "--gem5-real-l4"],
        gem5_attempted=True,
        gem5_log=gem5_log,
        workload_package=package,
    )

    out_dir = tmp_path / "trusted_gem5_uarch"
    verdict = json.loads((out_dir / "verdict.json").read_text())
    numerical = json.loads((out_dir / "numerical_validation.json").read_text())
    validation = json.loads((out_dir / "claim_validation.json").read_text())

    assert evidence["trusted_for_final_ranking"] is True
    assert verdict["trusted_for_final_ranking"] is True
    assert verdict["gem5_l4_proof_passed"] is True
    assert verdict["gem5_systemc_blockers"] == []
    assert numerical["passed"] is True
    assert numerical["scope"] == "gem5_microarchitecture_timing_internal_consistency"
    trusted_claim_ids = set(validation["trusted_claim_ids"])
    assert "gem5_microarchitecture_timing_consistency" in trusted_claim_ids
    assert "generic_systemc_numeric_reference" not in trusted_claim_ids


def test_gem5_l4_proof_fails_when_required_fields_are_missing():
    proof = build_gem5_l4_proof(
        gem5_log="100: system.generic_accel: descriptor_read verified=true",
        gem5_stdout="generic_accel_l4_status=1 error_code=0",
        sim_result={"schema_version": "gsim.result.v1", "status": "failed"},
        source_artifacts={"gem5_log": "gem5.log", "simulation_result": "simulation_result.json"},
    )

    assert proof["passed"] is False
    assert proof["proof_status"] == "failed"
    assert proof["checks"]["descriptor_read_verified"] is True
    assert proof["checks"]["request_decode_verified"] is False
    assert proof["checks"]["microarchitecture_execute_verified"] is False
    assert proof["checks"]["completion_writeback_verified"] is False
    assert proof["checks"]["driver_status_verified"] is True
    assert proof["checks"]["driver_completion_descriptor_verified"] is False
    assert proof["checks"]["non_smoke_l4_activity"] is False
    assert proof["non_smoke_classification"]["classification"] == "descriptor_only"
    assert proof["checks"]["result_status_passed"] is False
    assert "gem5.log must contain uarch_request_decode verified=true" in proof["missing_evidence"]
    assert "gem5.log must contain microarchitecture_execute verified=true" in proof["missing_evidence"]
    assert "L4 result JSON must have status=passed" in proof["missing_evidence"]
    assert any("descriptor-only" in item for item in proof["missing_evidence"])
    assert proof["source_artifacts"]["gem5_log"] == "gem5.log"
    assert proof["source_artifacts"]["gem5_command_descriptor"] == "gem5_command_descriptor.json"


def test_non_smoke_classifier_rejects_descriptor_only_and_host_only_l4_evidence():
    descriptor_only = classify_gem5_l4_non_smoke(
        "100: system.generic_accel: descriptor_read verified=true\n"
        "200: system.generic_accel: completion_writeback verified=true\n",
        {"schema_version": "gsim.result.v2", "status": "passed", "events": [], "microarchitecture_summary": {}},
    )
    host_only = classify_gem5_l4_non_smoke(
        "100: system.generic_accel: descriptor_read verified=true\n"
        "120: system.generic_accel: uarch_request_decode verified=true\n"
        "180: system.generic_accel: microarchitecture_execute verified=true\n",
        {
            "schema_version": "gsim.result.v2",
            "status": "passed",
            "events": [{"node_id": "noop", "device": "host", "start_ns": 0, "end_ns": 1}],
            "microarchitecture_summary": {"micro_op_count": 1, "total_cycles": 1},
        },
    )
    non_smoke = classify_gem5_l4_non_smoke(
        "100: system.generic_accel: descriptor_read verified=true\n"
        "120: system.generic_accel: uarch_request_decode verified=true\n"
        "180: system.generic_accel: microarchitecture_execute verified=true\n",
        {
            "schema_version": "gsim.result.v2",
            "status": "passed",
            "events": [{"node_id": "spmv", "device": "fpga-0", "start_ns": 0, "end_ns": 10}],
            "microarchitecture_summary": {"micro_op_count": 3, "total_cycles": 128},
        },
    )

    assert descriptor_only["classification"] == "descriptor_only"
    assert descriptor_only["completion_eligible"] is False
    assert host_only["classification"] == "smoke_or_host_only"
    assert host_only["completion_eligible"] is False
    assert non_smoke["classification"] == "non_smoke"
    assert non_smoke["completion_eligible"] is True


def test_gem5_systemc_failed_l4_proof_remains_untrusted_with_blocker(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="failed_gem5_systemc",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "gem5_systemc"},
    )
    backend = GenericSystemCBackend(mode="standalone_systemc")
    run = backend.run_simulation(design_point, graph, workload_package=package, output_dir=tmp_path / "failed_gem5_systemc_raw")
    assert run["returncode"] == 0

    out_dir = tmp_path / "failed_gem5_systemc"
    evidence = write_full_flow_evidence(
        run_dir=out_dir,
        backend="gem5_systemc",
        evidence_mode="summary",
        design_point=design_point,
        compute_graph=graph,
        simulation_request=run["request"],
        simulation_result=run["result"],
        simulator_cmd=["gem5.opt", "generic_accel_l4_test.py"],
        simulator_returncode=0,
        systemc_stdout="generic_accel_l4_status=1 error_code=0",
        systemc_stderr="",
        cli_command=["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py", "--backend", "gem5_systemc", "--gem5-real-l4"],
        gem5_attempted=True,
        gem5_log="100: system.generic_accel: descriptor_read verified=true",
        workload_package=package,
    )

    verdict = json.loads((out_dir / "verdict.json").read_text())
    samples = json.loads((out_dir / "mapping_simulation_samples.json").read_text())
    proof = json.loads((out_dir / "gem5_l4_proof.json").read_text())

    assert evidence["trusted_for_final_ranking"] is False
    assert verdict["gem5_l4_proof_passed"] is False
    assert verdict["binding_status"]["gem5_systemc_full_workload"] == "untrusted"
    assert proof["passed"] is False
    assert samples["samples"][0]["trusted_final_eligible"] is False
    assert samples["samples"][0]["blockers"][0]["id"] == "missing_or_failed_l4_proof"


def test_gem5_systemc_adapter_builds_available_artifacts_but_blocks_missing_real_gem5_config(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="missing_l4_harness",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "gem5_systemc"},
    )
    adapter = Gem5SystemCClosureAdapter(GenericSystemCBackend(mode="gem5_systemc"))
    run = adapter.run_verified_l4(
        design_point=design_point,
        compute_graph=graph,
        output_dir=tmp_path / "missing_l4_harness",
        gem5_binary=tmp_path / "missing-gem5.opt",
        gem5_config=tmp_path / "missing-config.py",
        driver_binary=tmp_path / "missing-driver",
        simulator_binary=tmp_path / "missing-generic-sim",
        workload_package=package,
        timeout=1,
    )

    assert run["returncode"] == 2
    assert run["result"]["status"] == "blocked"
    blocker_ids = {blocker["id"] for blocker in run["result"]["gem5_systemc_blockers"]}
    assert "gem5_config" in blocker_ids
    assert "gem5_driver" not in blocker_ids
    assert blocker_ids <= {"gem5_config", "gem5_binary", "gem5_source_tree_missing", "gem5_build_failed"}
    assert run["gem5_l4_transport_proof"]["result_status_passed"] is False
    assert (tmp_path / "missing_l4_harness" / "gem5_command_descriptor.json").exists()


def test_gem5_systemc_adapter_can_disable_local_l4_transport_fallback(tmp_path):
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    graph = package.graph
    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id="strict_missing_l4_harness",
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={"workload": "qe_scf_shell", "backend": "gem5_systemc"},
    )
    adapter = Gem5SystemCClosureAdapter(GenericSystemCBackend(mode="gem5_systemc"))
    run = adapter.run_verified_l4(
        design_point=design_point,
        compute_graph=graph,
        output_dir=tmp_path / "strict_missing_l4_harness",
        gem5_config=tmp_path / "missing-config.py",
        workload_package=package,
        timeout=1,
        allow_local_transport_fallback=False,
    )

    assert run["returncode"] == 2
    assert run["result"]["status"] == "blocked"
    blocker_ids = {blocker["id"] for blocker in run["result"]["gem5_systemc_blockers"]}
    assert "gem5_config" in blocker_ids
    assert run["gem5_l4_transport_proof"]["result_status_passed"] is False
    assert (tmp_path / "strict_missing_l4_harness" / "gem5_command_descriptor.json").exists()


def test_gem5_rebuilds_when_active_generic_accel_source_is_newer(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    gem5_root = root / "gem5_integration" / "gem5"
    active_dir = root / "gem5_integration" / "src" / "dev" / "generic_accel"
    vendored_dir = gem5_root / "src" / "dev" / "generic_accel"
    binary = gem5_root / "build" / "X86" / "gem5.opt"
    for path in [active_dir, vendored_dir, binary.parent, gem5_root / "src" / "dev"]:
        path.mkdir(parents=True, exist_ok=True)
    (gem5_root / "SConstruct").write_text("# fake sconstruct\n", encoding="utf-8")
    (gem5_root / "src" / "dev" / "SConscript").write_text("SimObject('generic_accel/GenericAccel.py')\n", encoding="utf-8")
    (active_dir / "SConscript").write_text("SimObject('GenericAccel.py')\nSource('generic_accel.cc')\n", encoding="utf-8")
    for filename in ["GenericAccel.py", "generic_accel.cc", "generic_accel.hh"]:
        (active_dir / filename).write_text(f"active {filename}\n", encoding="utf-8")
        (vendored_dir / filename).write_text(f"old {filename}\n", encoding="utf-8")
    binary.write_text("old binary\n", encoding="utf-8")

    old_time = 1_700_000_000
    new_time = old_time + 100
    os.utime(binary, (old_time, old_time))
    for path in vendored_dir.iterdir():
        os.utime(path, (old_time, old_time))
    for path in active_dir.iterdir():
        os.utime(path, (new_time, new_time))

    calls = []

    def fake_run_command(cmd, *, cwd, timeout=300):
        calls.append((cmd, cwd, timeout))
        binary.write_text("rebuilt binary\n", encoding="utf-8")
        os.utime(binary, (new_time + 1, new_time + 1))
        return True, "scons ok"

    monkeypatch.setattr(gem5_adapter_module, "_run_command", fake_run_command)

    selected, blockers = gem5_adapter_module._ensure_gem5(binary, root)

    assert selected == binary
    assert blockers == []
    assert calls and calls[0][0][0] == "scons"
    for filename in ["GenericAccel.py", "generic_accel.cc", "generic_accel.hh"]:
        assert (vendored_dir / filename).read_text(encoding="utf-8") == (active_dir / filename).read_text(encoding="utf-8")


def test_predicted_only_claim_cannot_enter_trusted_final_ranking():
    trusted_verdict = {"trusted_for_final_ranking": True}
    predicted_claim = {
        "claim_type": "best_architecture",
        "source_fidelity": "L1",
        "backend": "analytical",
        "predicted_only": True,
        "evidence_ids": ["screening-row-1"],
    }
    systemc_claim = {
        "claim_type": "feasibility",
        "source_fidelity": "L3",
        "backend": "systemc",
        "predicted_only": False,
        "evidence_ids": ["verdict.json", "simulation_result.json"],
    }
    assert claim_can_be_trusted(predicted_claim, trusted_verdict) is False
    assert claim_can_be_trusted(systemc_claim, trusted_verdict) is True
