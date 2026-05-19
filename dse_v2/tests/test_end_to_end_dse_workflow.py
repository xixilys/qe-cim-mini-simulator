#!/usr/bin/env python3
"""Coverage for the generic DSE catalog/search/report end-to-end CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.architecture.catalog import catalog_summary, seed_generic_dse_architecture_catalog
from dse_v2.core.workload import create_sparse_spmv_graph
from dse_v2.mapping.search import run_mapping_search, select_initial_mapping
from dse_v2.scripts.dse.run_full_flow_pilot import build_pilot_architecture


REPO_ROOT = Path(__file__).resolve().parents[2]
END_TO_END = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_end_to_end_dse.py"


def test_architecture_catalog_is_extensible_and_not_four_cluster_only():
    catalog = seed_generic_dse_architecture_catalog()
    summary = catalog_summary(catalog)
    artifact = catalog.to_dict()

    family_ids = {family["family_id"] for family in artifact["families"]}
    instance_ids = {instance["architecture_id"] for instance in artifact["instances"]}
    assert summary["validation"] == []
    assert summary["family_count"] >= 9
    assert {"cpu-only-baseline", "host-fpga-minimal", "host-fpga-cim", "balanced", "future-custom"} <= family_ids
    assert "balanced-generic-systemc-v0" in instance_ids
    assert len(instance_ids) > 1


def test_mapping_search_emits_promotion_sample_and_feedback():
    graph = create_sparse_spmv_graph(graph_id="sparse_profile_mapping_feedback")
    architecture = build_pilot_architecture()
    selected_mapping = select_initial_mapping(graph, architecture)
    artifacts = run_mapping_search(
        graph,
        architecture,
        selected_mapping=selected_mapping,
        simulation_result={
            "backend": "systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.25, "power_w": 80.0, "energy_j": 0.1, "total_data_movement_mb": 2.0},
        },
        trusted_sample=True,
    )

    assert artifacts["legality_matrix"]["summary"]["all_nodes_have_legal_target"] is True
    assert artifacts["seed_set"]["seeds"]
    assert artifacts["selected_record"]["state"] == "selected"
    assert artifacts["selected_record"]["trusted_final_eligible"] is True
    assert artifacts["selected_record"]["promotion_reason"]
    assert artifacts["simulation_samples"]["samples"][0]["trusted_final_eligible"] is True
    feedback = artifacts["feedback_state"]
    assert feedback["simulation_budget"]["trusted_completed_samples"] == 1
    assert feedback["ranking_update"]["source"] == "trusted_systemc_sample"
    assert feedback["ranking_update"]["low_fidelity_role"] == "candidate_generator_only"
    assert "pruning" in feedback["ranking_update"]["pruning_policy"]
    assert feedback["convergence"]["budget_exhausted"] is False
    assert artifacts["convergence_status"]["stop_reason"] == "incomplete"


def test_mapping_search_records_multi_candidate_feedback_and_budget_exhaustion():
    graph = create_sparse_spmv_graph(graph_id="sparse_profile_multi_feedback")
    architecture = build_pilot_architecture()
    selected_mapping = select_initial_mapping(graph, architecture)
    artifacts = run_mapping_search(
        graph,
        architecture,
        selected_mapping=selected_mapping,
        simulation_result={
            "backend": "systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.25, "power_w": 80.0, "energy_j": 0.1, "total_data_movement_mb": 2.0},
        },
        additional_feedback_samples=[
            {
                "candidate_id": "map_999_extra",
                "backend": "systemc",
                "fidelity": "L3",
                "status": "passed",
                "trusted_final_eligible": True,
                "metrics": {"latency_ms": 1.50, "power_w": 70.0, "energy_j": 0.105, "total_data_movement_mb": 1.8},
                "evidence_ids": [
                    "feedback_samples/map_999_extra/simulation_result.json",
                    "feedback_samples/map_999_extra/numerical_validation.json",
                ],
            }
        ],
        trusted_sample=True,
        beam_width=2,
    )

    samples = artifacts["simulation_samples"]["samples"]
    convergence = artifacts["convergence_status"]
    assert len(samples) == 2
    assert all(sample["trusted_final_eligible"] for sample in samples)
    assert artifacts["feedback_state"]["simulation_budget"]["trusted_completed_samples"] == 2
    assert convergence["simulation_budget"]["budget_exhausted"] is True
    assert convergence["stop_reason"] == "budget_exhausted"
    assert convergence["converged"] is False


def test_mapping_search_rejects_illegal_external_selected_mapping():
    graph = create_sparse_spmv_graph(graph_id="sparse_profile_illegal_mapping")
    architecture = build_pilot_architecture()
    illegal_mapping = {node_id: "missing-accelerator" for node_id in graph.nodes}

    artifacts = run_mapping_search(
        graph,
        architecture,
        selected_mapping=illegal_mapping,
        simulation_result={
            "backend": "systemc",
            "status": "passed",
            "metrics": {"latency_ms": 1.25, "power_w": 80.0, "energy_j": 0.1, "total_data_movement_mb": 2.0},
        },
        trusted_sample=True,
    )

    selected = artifacts["selected_record"]
    feedback = artifacts["feedback_state"]
    sample = artifacts["simulation_samples"]["samples"][0]

    assert selected["candidate_id"] == "external_selected_mapping"
    assert selected["state"] == "rejected"
    assert selected["trusted_final_eligible"] is False
    assert selected["violations"]
    assert sample["trusted_final_eligible"] is False
    assert sample["sample_role"] == "blocked_or_untrusted_attempt"
    assert feedback["simulation_budget"]["trusted_completed_samples"] == 0
    assert feedback["simulation_budget"]["blocked_samples"] == 1
    assert feedback["ranking_update"]["source"] == "untrusted_simulation_attempt"


def test_end_to_end_cli_writes_report_and_mapping_artifacts(tmp_path):
    out_dir = tmp_path / "systemc_run"
    cmd = [
        sys.executable,
        str(END_TO_END),
        "--profile",
        "sparse_la",
        "--importer",
        "generic_json",
        "--generator",
        "sparse_spmv",
        "--backend",
        "systemc",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    missing = [rel for rel in manifest["required_evidence_files"] if not (out_dir / rel).exists()]
    assert missing == []
    assert manifest["replay_metadata"]["python_replay_command"][:2] == ["python3", "dse_v2/scripts/dse/run_end_to_end_dse.py"]

    report = json.loads((out_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((out_dir / "claim_validation.json").read_text(encoding="utf-8"))
    selected = json.loads((out_dir / "mapping_selected_record.json").read_text(encoding="utf-8"))
    samples = json.loads((out_dir / "mapping_simulation_samples.json").read_text(encoding="utf-8"))
    feedback = json.loads((out_dir / "mapping_feedback_state.json").read_text(encoding="utf-8"))

    assert report["trusted_ranking"]
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert validation["passed"] is True
    assert selected["state"] == "selected"
    assert samples["samples"][0]["backend"] == "systemc"
    assert samples["samples"][0]["sample_role"] == "trusted_feedback"
    assert report["evidence_index"]["artifact_manifest.json"]["exists"] is True
    assert report["evidence_index"]["final_report.json"]["exists"] is True
    assert report["evidence_index"]["claim_validation.json"]["exists"] is True
    assert feedback["ranking_update"]["low_fidelity_role"] == "candidate_generator_only"
    assert feedback["simulation_budget"]["trusted_completed_samples"] == 1


def test_end_to_end_cli_writes_feedback_convergence_report_with_blocked_sample(tmp_path):
    out_dir = tmp_path / "systemc_feedback_run"
    cmd = [
        sys.executable,
        str(END_TO_END),
        "--profile",
        "sparse_la",
        "--importer",
        "generic_json",
        "--generator",
        "sparse_spmv",
        "--backend",
        "systemc",
        "--feedback-samples",
        "2",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

    samples = json.loads((out_dir / "mapping_simulation_samples.json").read_text(encoding="utf-8"))
    convergence = json.loads((out_dir / "convergence_status.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((out_dir / "claim_validation.json").read_text(encoding="utf-8"))

    assert len(samples["samples"]) == 2
    assert sum(1 for sample in samples["samples"] if sample["trusted_final_eligible"]) == 1
    blocked_sample = next(sample for sample in samples["samples"] if not sample["trusted_final_eligible"])
    assert any(
        blocker["id"] == "missing_step4_adjudication_for_feedback_sample"
        for blocker in blocked_sample["blockers"]
    )
    assert convergence["stop_reason"] == "budget_exhausted"
    assert convergence["converged"] is False
    assert report["feedback_loop"]["trusted_sample_count"] == 1
    assert report["selected_recommendation"]["selection_status"] == "trusted_feasibility_candidate_not_cross_candidate_winner"
    assert any(claim["claim_id"] == "feedback_convergence_status" for claim in report["claims"])
    assert validation["passed"] is True
    assert "generic_systemc_numeric_reference" in validation["trusted_claim_ids"]
    assert "feedback_convergence_status" in validation["blocked_or_predicted_claim_ids"]


def test_gem5_systemc_cli_requires_real_l4_flag(tmp_path):
    out_dir = tmp_path / "gem5_requires_real_l4"
    cmd = [
        sys.executable,
        str(END_TO_END),
        "--profile",
        "sparse_la",
        "--importer",
        "generic_json",
        "--generator",
        "sparse_spmv",
        "--backend",
        "gem5_systemc",
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)

    assert result.returncode == 2
    assert "--gem5-real-l4" in result.stderr
    assert "synthetic gem5 evidence generation has been removed" in result.stderr
    assert not (out_dir / "verdict.json").exists()
    assert not (out_dir / "mapping_feedback_state.json").exists()
