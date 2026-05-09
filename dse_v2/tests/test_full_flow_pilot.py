#!/usr/bin/env python3
"""Regression coverage for the full QE SCF shell SystemC evidence pilot."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.evidence.full_flow import REQUIRED_EVIDENCE_FILES, REQUIRED_QE_SCF_PHASES, claim_can_be_trusted


REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_full_flow_pilot.py"


def _run_pilot(tmp_path, backend: str):
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
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    return out_dir, result


def test_full_flow_pilot_writes_required_evidence(tmp_path):
    out_dir, result = _run_pilot(tmp_path, "systemc")
    assert result.returncode == 0, result.stdout + result.stderr

    for rel in REQUIRED_EVIDENCE_FILES:
        assert (out_dir / rel).exists(), f"missing evidence artifact: {rel}"

    verdict = json.loads((out_dir / "verdict.json").read_text())
    assert verdict["trusted_for_final_ranking"] is True
    assert verdict["binding_status"]["standalone_systemc_full_qe_scf_shell"] == "implemented"
    assert verdict["binding_status"]["gem5_systemc_full_qe_scf_shell"] == "blocked"
    assert verdict["status_boundary"]["fixed_timing_smoke_done_evidence"] == "unsupported"
    assert verdict["status_boundary"]["predicted_only_done_evidence"] == "unsupported"

    sim_result = json.loads((out_dir / "simulation_result.json").read_text())
    assert sim_result["status"] == "passed"
    assert sim_result["missing_required_phases"] == []
    for phase in REQUIRED_QE_SCF_PHASES:
        phase_result = sim_result["phase_results"][phase]
        assert phase_result["status"] == "available"
        assert phase_result["latency_ms"] >= 0.0
        assert phase_result["cycles_estimate"] is not None

    artifact_manifest = json.loads((out_dir / "artifact_manifest.json").read_text())
    artifacts = {entry["path"]: entry for entry in artifact_manifest["artifacts"]}
    for rel in REQUIRED_EVIDENCE_FILES:
        assert artifacts[rel]["exists"] is True

    architecture = json.loads((out_dir / "architecture.json").read_text())
    accelerator_types = {
        accelerator["accel_type"]
        for accelerator in architecture["system_architecture"]["accelerators"]
    }
    assert {"gpu", "fpga", "cim"}.issubset(accelerator_types)
    assert "4-cluster" not in architecture["architecture_scope"]

    mapping = json.loads((out_dir / "mapping.json").read_text())
    for phase in REQUIRED_QE_SCF_PHASES:
        assert phase in mapping["placements"]
    assert len(set(mapping["placements"].values())) >= 3
    assert mapping["trusted_final_eligible"] is True

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["trusted_for_final_ranking"] is True
    replay = manifest["replay_metadata"]
    assert replay["python_replay_command"][:2] == [
        "python3",
        "dse_v2/scripts/dse/run_full_flow_pilot.py",
    ]
    assert replay["simulator_replay_command"]


def test_gem5_systemc_backend_writes_blocked_verdict_without_trusted_claims(tmp_path):
    out_dir, result = _run_pilot(tmp_path, "gem5_systemc")
    assert result.returncode == 2

    summary = json.loads(result.stdout)
    assert summary["gem5_systemc"] == "blocked"
    assert summary["trusted_for_final_ranking"] is False
    assert summary["missing_required_phases"] == REQUIRED_QE_SCF_PHASES

    for rel in REQUIRED_EVIDENCE_FILES:
        assert (out_dir / rel).exists(), f"missing blocked evidence artifact: {rel}"
    assert (out_dir / "gem5_systemc_blockers.json").exists()

    verdict = json.loads((out_dir / "verdict.json").read_text())
    assert verdict["trusted_for_final_ranking"] is False
    assert verdict["trusted_paths"] == []
    assert verdict["binding_status"]["gem5_systemc_full_qe_scf_shell"] == "blocked"
    assert verdict["binding_status"]["standalone_systemc_full_qe_scf_shell"] == "blocked"
    assert verdict["status_boundary"]["timing_level_phase_execution"] == "blocked"
    assert verdict["missing_required_phases"] == REQUIRED_QE_SCF_PHASES
    assert {blocker["status"] for blocker in verdict["gem5_systemc_blockers"]} == {"blocked"}

    sim_result = json.loads((out_dir / "simulation_result.json").read_text())
    assert sim_result["status"] == "blocked"
    for phase in REQUIRED_QE_SCF_PHASES:
        assert sim_result["phase_results"][phase]["status"] == "unavailable"

    gem5_claim = {
        "claim_type": "feasibility",
        "source_fidelity": "L4",
        "backend": "gem5_systemc",
        "predicted_only": False,
        "evidence_ids": ["verdict.json", "simulation_result.json"],
    }
    assert claim_can_be_trusted(gem5_claim, verdict) is False


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
