#!/usr/bin/env python3
"""Regression tests for generic DSE final report claim gating."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reporting.final_report import generate_final_report_artifacts, validate_report_claims


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_minimal_trusted_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    required = [
        "manifest.json",
        "artifact_manifest.json",
        "verdict.json",
        "design_point.json",
        "architecture.json",
        "mapping.json",
        "workload_graph.json",
        "simulation_request.json",
        "simulation_result.json",
        "phase_breakdown.csv",
        "resource_summary.csv",
        "data_movement_summary.csv",
        "systemc_stdout.log",
        "systemc_stderr.log",
        "gem5_systemc_blockers.json",
    ]
    _write_json(run_dir / "manifest.json", {
        "schema_version": "dse.manifest.v1",
        "run_id": "trusted_run",
        "workload": "qe_scf_shell",
        "backend": "systemc",
        "evidence_mode": "debug",
        "cli_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
        "simulator_command": ["generic_sim"],
        "replay_metadata": {
            "python_replay_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
            "simulator_replay_command": ["generic_sim"],
        },
        "required_evidence_files": required,
    })
    _write_json(run_dir / "artifact_manifest.json", {"schema_version": "dse.artifact_manifest.v1", "artifacts": []})
    _write_json(run_dir / "verdict.json", {
        "schema_version": "dse.verdict.v1",
        "run_id": "trusted_run",
        "backend": "systemc",
        "evidence_mode": "debug",
        "trusted_for_final_ranking": True,
        "required_qe_scf_phases": ["h_psi", "s_psi"],
        "missing_required_phases": [],
        "gem5_systemc_blockers": [
            {"id": "gem5_systemc_binding", "detail": "L4 binding is blocked in this run."}
        ],
        "evidence_gaps": ["gem5+SystemC path remains blocked."],
    })
    _write_json(run_dir / "design_point.json", {"design_point_id": "trusted_run"})
    _write_json(run_dir / "architecture.json", {
        "architecture_id": "arch-1",
        "architecture_family": "generic_heterogeneous_pilot",
        "status": "prototype",
        "trusted_final_eligible": True,
    })
    _write_json(run_dir / "mapping.json", {
        "mapping_id": "mapping-1",
        "mapping_policy": "seeded",
        "search_status": "single_candidate",
    })
    _write_json(run_dir / "workload_graph.json", {"graph_id": "qe", "nodes": {"h_psi": {}, "s_psi": {}}, "edges": []})
    _write_json(run_dir / "simulation_request.json", {"run_id": "trusted_run"})
    _write_json(run_dir / "simulation_result.json", {
        "status": "passed",
        "backend": "systemc",
        "metrics": {"latency_ms": 3.0, "power_w": 5.0, "energy_j": 0.015},
    })
    (run_dir / "phase_breakdown.csv").write_text(
        "phase,node_id,op_type,device,start_ns,end_ns,latency_ns,latency_ms,cycles_estimate,clock_mhz,status,unavailable_reason\n"
        "h_psi,h_psi,gemm,gpu-0,0,1000000,1000000,1.0,250000,250,available,\n"
        "s_psi,s_psi,gemm,gpu-0,1000000,3000000,2000000,2.0,500000,250,available,\n",
        encoding="utf-8",
    )
    (run_dir / "resource_summary.csv").write_text("device,compute_percent\ngpu-0,80\n", encoding="utf-8")
    (run_dir / "data_movement_summary.csv").write_text("edge_id,status\n", encoding="utf-8")
    (run_dir / "systemc_stdout.log").write_text("", encoding="utf-8")
    (run_dir / "systemc_stderr.log").write_text("", encoding="utf-8")
    _write_json(run_dir / "gem5_systemc_blockers.json", {"blockers": ["gem5_systemc_binding"]})


def test_final_report_artifacts_validate_trusted_claims(tmp_path):
    run_dir = tmp_path / "trusted_run"
    _seed_minimal_trusted_run(run_dir)

    result = generate_final_report_artifacts(run_dir)

    assert result["validation_passed"] is True
    assert result["trusted_claim_count"] == 2
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "claim_validation.json").read_text(encoding="utf-8"))
    assert report["selected_recommendation"]["status"] == "not_selected"
    assert report["trusted_ranking"][0]["trusted_scope"].startswith("single-run feasibility")
    assert validation["errors"] == []
    assert (run_dir / "final_report.md").exists()


def test_predicted_only_winner_is_rejected(tmp_path):
    report = {
        "claims": [
            {
                "claim_id": "bad:winner",
                "claim_type": "best_architecture",
                "trusted": False,
                "predicted_only": True,
                "blocked": False,
                "backend": "analytical",
                "source_fidelity": "L1",
                "evidence_ids": [],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("predicted-only candidate cannot be a winner" in error for error in validation["errors"])
