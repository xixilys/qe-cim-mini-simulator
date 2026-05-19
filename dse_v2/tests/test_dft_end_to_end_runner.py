#!/usr/bin/env python3
"""DFT-first end-to-end runner contracts."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dse_v2.evidence.full_flow import build_gem5_l4_proof
from dse_v2.reference_workloads.dft_profile_schema import (
    dft_domain_validation_contract,
    dft_profile_metadata_contract,
)
from dse_v2.scripts.dse.audit_dft_first_end_to_end_run import (
    REQUIRED_GEM5_CHECKS,
    _forbidden_no_smoke_tokens,
)
from dse_v2.scripts.dse.audit_dft_first_goal_completion import build_goal_completion_audit
from dse_v2.scripts.dse.build_dft_first_goal_support_scans import build_goal_support_scans
from dse_v2.scripts.dse.run_dft_first_real_artifact_tamper_probe import run_real_artifact_tamper_probe
from dse_v2.scripts.dse.snapshot_dft_first_monitor_validation import (
    FULL_LABELS,
    build_monitor_validation_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_dft_first_end_to_end_dse.py"
AUDITOR = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "audit_dft_first_end_to_end_run.py"

QE_INPUT = """
&CONTROL
  calculation = 'scf'
/
&SYSTEM
  ibrav = 2, nat = 2, ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 8,
/
&ELECTRONS
  conv_thr = 1.0d-8,
  mixing_beta = 0.7,
  diagonalization = 'david'
/
K_POINTS automatic
  2 2 1 0 0 0
"""

QE_LOG = """
     number of k points=     2
     number of Kohn-Sham states= 8
     number of plane waves= 321
     FFT dimensions: ( 16, 16, 16)
     iteration # 1
     h_psi        :      0.10s CPU      1.20s WALL
     c_bands      :      0.05s CPU      0.20s WALL
     FFT          :      0.02s CPU      0.10s WALL
"""

GEM5_STATS_TEXT = """
simTicks                                   1000000                       # Number of ticks simulated (Tick)
finalTick                                  1000000                       # Number of ticks from beginning of simulation (Tick)
simInsts                                      1000                       # Number of instructions simulated (Count)
simOps                                        2000                       # Number of ops simulated (Count)
system.cpu.numCycles                          1500                       # Number of cpu cycles simulated (Cycle)
"""


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_step3_artifact_manifest(step3: Path) -> None:
    artifacts = []
    for rel in [
        "simulation_request.json",
        "simulation_result.raw.json",
        "simulation_result.json",
        "numerical_validation.json",
        "verdict.json",
    ]:
        path = step3 / rel
        artifacts.append({
            "exists": path.exists(),
            "path": rel,
            "required": rel != "simulation_result.raw.json",
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        })
    _write_json(step3 / "artifact_manifest.json", {"artifacts": artifacts})


def _write_step4_artifact_manifest(step4: Path) -> None:
    artifacts = []
    for rel in [
        "manifest.json",
        "gem5.log",
        "systemc_stdout.log",
        "systemc_stderr.log",
        "stats.txt",
        "config.ini",
        "gem5_command_descriptor.json",
        "gem5_completion_descriptor.json",
        "gem5_l4_proof.json",
        "gem5_activity_summary.json",
        "simulation_request.json",
        "simulation_result.raw.json",
    ]:
        path = step4 / rel
        artifacts.append({
            "exists": path.exists(),
            "path": rel,
            "required": rel in {
                "manifest.json",
                "gem5.log",
                "stats.txt",
                "gem5_l4_proof.json",
                "gem5_activity_summary.json",
                "simulation_result.raw.json",
            },
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        })
    _write_json(step4 / "artifact_manifest.json", {"artifacts": artifacts})


def _write_step4_adjudication_fixture(run_dir: Path, arch: str) -> dict:
    step3 = run_dir / "architectures" / arch / "step3_systemc"
    step4 = run_dir / "architectures" / arch / "step4_adjudication"
    _write_json(step4 / "kernel_numerical_validation.json", {
        "schema_version": "dse.kernel_numerical_validation.v1",
        "step": "step4",
        "owner": "evidence_adjudication",
        "architecture_id": arch,
        "status": "passed",
        "passed": True,
        "source_step3_artifact": str(step3 / "numerical_validation.json"),
    })
    _write_json(step4 / "domain_physics_validation.json", {
        "schema_version": "dse.dft.domain_physics_validation.v1",
        "step": "step4",
        "owner": "domain_profile_adjudication",
        "architecture_id": arch,
        "status": "not_claimed",
        "passed": False,
        "claim_boundary": "DFT scientific correctness is not inferred from timing evidence.",
    })
    _write_json(step4 / "verdict.json", {
        "schema_version": "dse.verdict.v1",
        "step": "step4",
        "owner": "evidence_adjudication",
        "architecture_id": arch,
        "step3_simulation_passed": True,
        "kernel_numerical_validation_passed": True,
        "domain_physics_validation_passed": False,
        "trusted_for_final_ranking": False,
    })
    _write_json(step4 / "claim_validation.json", {
        "schema_version": "dse.claim_validation.v1",
        "step": "step4",
        "owner": "claim_validation",
        "architecture_id": arch,
        "trusted_final_ranking": False,
        "claim_levels": {
            "timing_evidence": True,
            "kernel_numerical_evidence": True,
            "domain_physics_evidence": False,
            "software_visible_evidence": False,
        },
    })
    _write_json(step4 / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "owner": "evidence_adjudication"})
    _write_json(step4 / "provenance.json", {
        "schema_version": "dse.provenance.v1",
        "owner": "evidence_adjudication",
        "source_step3_artifacts": {"simulation_result_raw": str(step3 / "simulation_result.raw.json")},
    })
    _write_json(step4 / "manifest.json", {"schema_version": "dse.step4.manifest.v1", "owner": "evidence_adjudication"})
    artifacts = []
    for rel in [
        "claim_validation.json",
        "domain_physics_validation.json",
        "evidence_requirements.json",
        "kernel_numerical_validation.json",
        "manifest.json",
        "provenance.json",
        "verdict.json",
    ]:
        artifact = step4 / rel
        artifacts.append({"exists": True, "path": rel, "required": True, "sha256": _sha256(artifact), "size_bytes": artifact.stat().st_size})
    _write_json(step4 / "artifact_manifest.json", {"schema_version": "dse.artifact_manifest.v1", "step": "step4", "owner": "evidence_adjudication", "artifacts": artifacts})
    return {
        "schema_version": "dse.dft.step4_adjudication_summary.v1",
        "step4_dir": str(step4),
        "kernel_numerical_validation": str(step4 / "kernel_numerical_validation.json"),
        "domain_physics_validation": str(step4 / "domain_physics_validation.json"),
        "verdict": str(step4 / "verdict.json"),
        "claim_validation": str(step4 / "claim_validation.json"),
        "evidence_requirements": str(step4 / "evidence_requirements.json"),
        "provenance": str(step4 / "provenance.json"),
        "artifact_manifest": str(step4 / "artifact_manifest.json"),
    }


def _make_complete_audit_fixture(run_dir: Path) -> Path:
    step1 = run_dir / "step1"
    step4 = run_dir / "step4_gem5" / "arch_b"
    for name, latency in [("arch_a", 1.2), ("arch_b", 0.9)]:
        step2 = run_dir / "architectures" / name / "step2"
        step3 = run_dir / "architectures" / name / "step3_systemc"
        for artifact in [
            "l1_evaluation_result.json",
            "l2_evaluation_result.json",
            "low_fidelity_screening_summary.json",
            "mapping_seed_set.json",
            "architecture_candidate_set.json",
            "step3_simulation_queue.json",
        ]:
            _write_json(step2 / artifact, {"artifact": artifact, "architecture_id": name, "trusted_final_claim": False})
        _write_json(step2 / "domain_policy_hints.json", {
            "schema_version": "dse.step2.domain_policy_hints.v1",
            "policy_id": "dft-fpga-reference-v1",
            "domain_key": "dft",
            "matched": True,
            "architecture_candidates": [
                {
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "candidate_role": "FPGA/HBM candidate",
                    "trusted_final_claim": False,
                }
            ],
            "node_target_preferences": {"phase_00_fft": ["fpga", "gpu", "host"]},
            "trusted_final_claim": False,
        })
        _write_json(step3 / "simulation_result.json", {
            "schema_version": "gsim.result.v1",
            "status": "passed",
            "metrics": {"latency_ms": latency},
        })
        _write_json(step3 / "simulation_result.raw.json", {
            "schema_version": "gsim.result.v1",
            "status": "passed",
            "metrics": {"latency_ms": latency},
        })
        _write_json(step3 / "simulation_request.json", {
            "schema_version": "gsim.request.v1",
            "run_id": name,
            "workload": {"nodes": {}},
        })
        _write_json(step3 / "manifest.json", {
            "replay_metadata": {
                "simulation_request": "simulation_request.json",
                "simulation_result": "simulation_result.json",
                "simulator_replay_command": [
                    "model/generic_sim_backend/build/generic_sim",
                    "--request",
                    str(step3 / "simulation_request.json"),
                    "--result",
                    str(step3 / "simulation_result.raw.json"),
                ],
            }
        })
        _write_json(step3 / "numerical_validation.json", {
            "schema_version": "dse.numerical_validation.v1",
            "passed": True,
        })
        _write_json(step3 / "verdict.json", {
            "schema_version": "dse.verdict.v1",
            "simulation_passed": True,
            "numerical_validation_passed": True,
            "trusted_for_final_ranking": False,
        })
        _write_json(step3 / "step3_status.json", {
            "schema_version": "dse.step3.status.v1",
            "step": "step3",
            "owner": "simulation_execution",
            "architecture_id": name,
            "status": "passed",
            "timing_verified": True,
        })
        _write_step3_artifact_manifest(step3)

    step4_adjudication_by_arch = {
        "arch_a": _write_step4_adjudication_fixture(run_dir, "arch_a"),
        "arch_b": _write_step4_adjudication_fixture(run_dir, "arch_b"),
    }

    _write_json(step1 / "workload_package.json", {
        "schema_version": "dse.step1.workload_package.v1",
        "workload_family": "dft",
        "profile": {
            "domain_validation": dft_domain_validation_contract(source_program="qe_pw"),
        },
        "domain_metadata": {
            "dft": {
                "profile_metadata": dft_profile_metadata_contract(source_program="qe_pw"),
                "source_facts": [
                    {
                        "schema_version": "dse.dft.source_fact.v1",
                        "field": "input.calculation",
                        "value": "scf",
                        "source_type": "input",
                        "source_path": "qe.in",
                    },
                    {
                        "schema_version": "dse.dft.source_fact.v1",
                        "field": "phase_timing.h_psi.wall_seconds",
                        "value": 1.2,
                        "source_type": "log",
                        "source_path": "qe.out",
                    },
                ]
            }
        },
    })
    _write_json(step1 / "workload_graph.json", {"graph_id": "qe_graph", "nodes": {}})
    _write_json(step1 / "workload_characterization.json", {
        "schema_version": "dse.workload_characterization.v1",
        "analysis_scope": "architecture_independent",
        "domain_phase_summary": {"schema_version": "dse.domain_phase_summary.v1"},
        "domain_workflow_summary": {"schema_version": "dse.domain_workflow_summary.v1"},
        "domain_claim_summary": {"schema_version": "dse.domain_claim_summary.v1"},
    })
    step4.mkdir(parents=True, exist_ok=True)
    (step4 / "gem5.log").write_text("\n".join([
        "descriptor_read verified=true",
        "uarch_request_decode verified=true",
        "microarchitecture_execute verified=true",
        "completion_writeback verified=true",
    ]) + "\n", encoding="utf-8")
    (step4 / "gem5_stdout.txt").write_text(
        "generic_accel_l4_status=1 error_code=0\n"
        "completion_magic=0x4753494d completion_status=0 cycles=123 result_addr=0x8120000\n",
        encoding="utf-8",
    )
    (step4 / "systemc_stdout.log").write_text((step4 / "gem5_stdout.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (step4 / "systemc_stderr.log").write_text("", encoding="utf-8")
    (step4 / "stats.txt").write_text(GEM5_STATS_TEXT, encoding="utf-8")
    (step4 / "config.ini").write_text("[system]\n", encoding="utf-8")
    _write_json(step4 / "manifest.json", {
        "replay_metadata": {
            "simulator_replay_command": [
                "/tmp/gem5/build/X86/gem5.opt",
                "gem5_integration/configs/generic_accel_l4_test.py",
                "--binary",
                "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver",
                "--request",
                str(step4 / "simulation_request.json"),
                "--simulator",
                "model/generic_sim_backend/build/generic_sim",
            ]
        }
    })
    _write_json(step4 / "gem5_command_descriptor.json", {
        "schema_version": "gsim.gem5_command_descriptor_observed.v1",
        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        "verified_in_gem5_log": True,
    })
    _write_json(step4 / "gem5_completion_descriptor.json", {"completion": {"status": 0}})
    _write_json(step4 / "simulation_request.json", {"schema_version": "gsim.request.v1"})
    _write_json(step4 / "simulation_result.raw.json", {
        "schema_version": "gsim.result.v1",
        "status": "passed",
        "execution_engine": "gem5_generic_accel_microarchitecture_v1",
        "microarchitecture_summary": {
            "engine": "gem5_generic_accel_microarchitecture_v1",
            "micro_op_count": 4,
            "total_cycles": 123,
            "total_flops": 456,
        },
        "events": [
            {"node_id": "phase_host", "op_type": "setup", "device": "host", "start_ns": 0.0, "end_ns": 1.0},
            {"node_id": "phase_accel_a", "op_type": "fft", "device": "fpga-0", "start_ns": 1.0, "end_ns": 2.0},
            {"node_id": "phase_accel_b", "op_type": "eigen", "device": "fpga-0", "start_ns": 2.0, "end_ns": 3.0},
        ],
    })
    checks = {
        "descriptor_read_verified": True,
        "request_decode_verified": True,
        "microarchitecture_execute_verified": True,
        "completion_writeback_verified": True,
        "driver_status_verified": True,
        "driver_completion_descriptor_verified": True,
        "result_status_passed": True,
        "stats_txt_present": True,
        "config_present": True,
        "nonzero_accelerator_activity": True,
    }
    _write_json(step4 / "gem5_l4_proof.json", {
        "schema_version": "dse.gem5_l4_proof.v1",
        "passed": True,
        "fallback_from_gem5": False,
        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        "checks": checks,
        "missing_evidence": [],
        "source_artifacts": {
            "require_gem5_stats_config": True,
            "gem5_log": str(step4 / "gem5.log"),
            "gem5_stdout": str(step4 / "gem5_stdout.txt"),
            "gem5_stats": str(step4 / "stats.txt"),
            "gem5_config_ini": str(step4 / "config.ini"),
            "gem5_command_descriptor": str(step4 / "gem5_command_descriptor.json"),
            "gem5_completion_descriptor": str(step4 / "gem5_completion_descriptor.json"),
            "gem5_activity_summary": str(step4 / "gem5_activity_summary.json"),
            "simulation_request": str(step4 / "simulation_request.json"),
            "simulation_result": str(step4 / "simulation_result.raw.json"),
        },
    })
    _write_json(step4 / "gem5_activity_summary.json", {
        "schema_version": "dse.gem5_activity_summary.v1",
        "execution_engine": "gem5_generic_accel_microarchitecture_v1",
        "nonzero_accelerator_activity": True,
        "accelerator_event_count": 2,
        "event_count": 3,
        "accelerator_devices": ["fpga-0"],
        "micro_op_count": 4,
        "total_cycles": 123,
        "total_flops": 456,
    })
    _write_step4_artifact_manifest(step4)
    _write_json(run_dir / "dft_end_to_end_summary.json", {
        "schema_version": "dse.dft_end_to_end_summary.v1",
        "status": "complete",
        "run_dir": str(run_dir),
        "scope": {
            "workload_focus": "QE pw.x/source-fact DFT-first flow only",
            "domain_neutral_core": True,
            "dft_logic_location": "dse_v2/reference_workloads",
            "trusted_final_dft_correctness_claimed": False,
        },
        "completion": {
            "end_to_end_timing_complete": True,
            "requires_real_gem5_non_smoke": True,
            "trusted_final_dft_correctness_claimed": False,
        },
        "step1": {"status": "complete", "run_dir": str(step1), "facts_only": True},
        "step2_step3_records": [
            {
                "architecture_id": "arch_a",
                "step2_dir": str(run_dir / "architectures" / "arch_a" / "step2"),
                "step3_dir": str(run_dir / "architectures" / "arch_a" / "step3_systemc"),
                "timing_verified": True,
                "step2_estimated_screening": {"trusted_final_claim": False},
                "step3_measured_timing": {
                    "latency_ms": 1.2,
                    "simulation_result": str(run_dir / "architectures" / "arch_a" / "step3_systemc" / "simulation_result.json"),
                    "numerical_validation": str(run_dir / "architectures" / "arch_a" / "step3_systemc" / "numerical_validation.json"),
                    "verdict": str(run_dir / "architectures" / "arch_a" / "step3_systemc" / "verdict.json"),
                },
                "step4_adjudication": step4_adjudication_by_arch["arch_a"],
            },
            {
                "architecture_id": "arch_b",
                "step2_dir": str(run_dir / "architectures" / "arch_b" / "step2"),
                "step3_dir": str(run_dir / "architectures" / "arch_b" / "step3_systemc"),
                "timing_verified": True,
                "step2_estimated_screening": {"trusted_final_claim": False},
                "step3_measured_timing": {
                    "latency_ms": 0.9,
                    "simulation_result": str(run_dir / "architectures" / "arch_b" / "step3_systemc" / "simulation_result.json"),
                    "numerical_validation": str(run_dir / "architectures" / "arch_b" / "step3_systemc" / "numerical_validation.json"),
                    "verdict": str(run_dir / "architectures" / "arch_b" / "step3_systemc" / "verdict.json"),
                },
                "step4_adjudication": step4_adjudication_by_arch["arch_b"],
            },
        ],
        "best_architecture": {
            "architecture_id": "arch_b",
            "latency_ms": 0.9,
            "selected_by": "minimum measured Step3 generic_sim latency within requested architecture_ids",
        },
        "step4_gem5": {
            "architecture_id": "arch_b",
            "attempted": True,
            "status": "passed",
            "trusted_step4_timing": True,
            "run_dir": str(step4),
            "step3_latency_ms": 0.9,
            "attempts": [
                {
                    "architecture_id": "arch_b",
                    "attempted": True,
                    "status": "passed",
                    "trusted_step4_timing": True,
                    "run_dir": str(step4),
                    "step3_latency_ms": 0.9,
                }
            ],
        },
    })
    return run_dir


def test_no_smoke_token_guard_does_not_flag_non_smoke_phrase():
    assert _forbidden_no_smoke_tokens(["non-smoke", "non_smoke", "nonsmoke"]) == []
    assert _forbidden_no_smoke_tokens([
        "--skip-gem5-l4",
        "--smoke",
        "smoke_test.py",
        "fake_demo.py",
    ]) == ["--skip-gem5-l4", "--smoke", "smoke_test.py", "fake_demo.py"]


def test_goal_support_scan_builder_emits_reusable_guard_artifacts(tmp_path):
    main_run = _make_complete_audit_fixture(tmp_path / "main_run")
    official_run = _make_complete_audit_fixture(tmp_path / "official_run")
    scan_root = tmp_path / "generic_layer"
    scan_root.mkdir()
    (scan_root / "ops.py").write_text("SUPPORTED = ['fft', 'gemm']\n", encoding="utf-8")

    manifest = build_goal_support_scans(
        main_run=main_run,
        official_run=official_run,
        out_dir=tmp_path / "support_scans",
        scan_roots=[scan_root],
    )

    assert manifest["status"] == "passed"
    no_smoke = json.loads(Path(manifest["outputs"]["no_smoke_scan"]).read_text(encoding="utf-8"))
    domain = json.loads(Path(manifest["outputs"]["domain_boundary_scan"]).read_text(encoding="utf-8"))
    external = json.loads(Path(manifest["outputs"]["external_reference_scan"]).read_text(encoding="utf-8"))
    assert no_smoke["schema_version"] == "dse.dft_first.no_smoke_guard_scan.v3"
    assert [item["passed_guard"] for item in no_smoke["items"]] == [True, True]
    assert domain["status"] == "passed"
    assert domain["blocked_hit_count"] == 0
    assert domain["context_hits"][0]["classification"] == "generic_fft_not_dft_specific"
    assert external["integration_decision"]["no_final_claim_from_external_models"] is True
    assert {source["id"] for source in external["sources"]} >= {"qe_gitlab_official", "gem5_build_docs"}


def test_real_artifact_tamper_probe_rejects_mutated_copied_step4_evidence(tmp_path):
    source_run = _make_complete_audit_fixture(tmp_path / "source_run")

    probe = run_real_artifact_tamper_probe(
        source_run=source_run,
        out_dir=tmp_path / "tamper_probe",
    )

    assert probe["probe_status"] == "passed"
    cases = {case["case"]: case for case in probe["cases"]}
    assert cases["stats_zero_tamper"]["passed_probe"] is True
    assert "step4_gem5_stats_semantics_present" in cases["stats_zero_tamper"]["result"]["failed_check_ids"]
    assert cases["gem5_log_marker_tamper_all_decode_markers"]["passed_probe"] is True
    assert "step4_raw_gem5_evidence_consistent" in cases["gem5_log_marker_tamper_all_decode_markers"]["result"]["failed_check_ids"]


def test_goal_completion_auditor_keeps_goal_in_progress_until_horizon(tmp_path):
    main_run = _make_complete_audit_fixture(tmp_path / "main_run")
    official_run = _make_complete_audit_fixture(tmp_path / "official_run")
    support = tmp_path / "support"
    no_smoke_scan = support / "no_smoke_guard_scan.json"
    domain_scan = support / "domain_boundary_scan.json"
    external_scan = support / "external_reference_scan.json"
    tamper_probe = support / "tamper_probe_result.json"
    monitor_dir = support / "monitor"
    monitor_snapshot = support / "monitor_validation_snapshot.json"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / "monitor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (monitor_dir / "monitor_no_sleep.sh").write_text(
        "# monitor intentionally avoids sleep\nwhile true; do\n  date >/dev/null\n  break\ndone\n",
        encoding="utf-8",
    )
    _write_json(monitor_dir / "monitor_status.json", {
        "schema_version": "dse.dft_first.continuous_monitor.v6",
        "last_status": "passed_diff_check",
        "last_failure": "",
        "no_sleep_command_used": True,
        "preserve_full_suite_logs": True,
    })
    _write_json(no_smoke_scan, {
        "status": "passed",
        "items": [{"passed_guard": True}, {"passed_guard": True}],
    })
    _write_json(domain_scan, {"status": "passed", "blocked_hit_count": 0})
    _write_json(external_scan, {
        "status": "passed",
        "sources": [{"id": "qe_gitlab_official"}],
        "integration_decision": {"no_final_claim_from_external_models": True},
    })
    _write_json(tamper_probe, {
        "probe_status": "passed",
        "cases": [{"passed_probe": True}, {"passed_probe": True}],
    })
    _write_json(monitor_snapshot, {
        "schema_version": "dse.dft_first.monitor_validation_snapshot.v6",
        "latest_full_validation_passed": True,
        "all_full_logs_preserved": True,
        "failure_file_exists": False,
        "latest_full_validation_iteration": 20,
    })
    (monitor_dir / "monitor_failures.jsonl").write_text(
        json.dumps({"iteration": 5, "label": "targeted_pytest", "returncode": 1}) + "\n",
        encoding="utf-8",
    )

    before_horizon = build_goal_completion_audit(
        main_run=main_run,
        official_run=official_run,
        no_smoke_scan=no_smoke_scan,
        domain_boundary_scan=domain_scan,
        external_reference_scan=external_scan,
        tamper_probe=tamper_probe,
        monitor_dir=monitor_dir,
        monitor_snapshot=monitor_snapshot,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert before_horizon["status"] == "in_progress"
    assert before_horizon["completion_decision"] == "do_not_mark_complete_before_midnight_horizon"
    assert before_horizon["in_progress_requirements"][0]["requirement"].startswith("Use date")

    after_horizon = build_goal_completion_audit(
        main_run=main_run,
        official_run=official_run,
        no_smoke_scan=no_smoke_scan,
        domain_boundary_scan=domain_scan,
        external_reference_scan=external_scan,
        tamper_probe=tamper_probe,
        monitor_dir=monitor_dir,
        monitor_snapshot=monitor_snapshot,
        now=datetime(2026, 5, 15, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert after_horizon["status"] == "complete"
    assert after_horizon["completion_decision"] == "ready_to_mark_complete"


def test_goal_completion_auditor_rejects_sleep_in_monitor_script(tmp_path):
    main_run = _make_complete_audit_fixture(tmp_path / "main_run")
    official_run = _make_complete_audit_fixture(tmp_path / "official_run")
    support = tmp_path / "support"
    no_smoke_scan = support / "no_smoke_guard_scan.json"
    domain_scan = support / "domain_boundary_scan.json"
    external_scan = support / "external_reference_scan.json"
    tamper_probe = support / "tamper_probe_result.json"
    monitor_dir = support / "monitor"
    monitor_snapshot = support / "monitor_validation_snapshot.json"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / "monitor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (monitor_dir / "monitor_no_sleep.sh").write_text("while true; do\n  sleep 1\ndone\n", encoding="utf-8")
    _write_json(monitor_dir / "monitor_status.json", {
        "schema_version": "dse.dft_first.continuous_monitor.v6",
        "last_status": "passed_diff_check",
        "last_failure": "",
        "no_sleep_command_used": True,
    })
    _write_json(no_smoke_scan, {"status": "passed", "items": [{"passed_guard": True}]})
    _write_json(domain_scan, {"status": "passed", "blocked_hit_count": 0})
    _write_json(external_scan, {
        "status": "passed",
        "integration_decision": {"no_final_claim_from_external_models": True},
    })
    _write_json(tamper_probe, {"probe_status": "passed", "cases": [{"passed_probe": True}]})
    _write_json(monitor_snapshot, {
        "schema_version": "dse.dft_first.monitor_validation_snapshot.v6",
        "latest_full_validation_passed": True,
        "all_full_logs_preserved": True,
        "failure_file_exists": False,
        "latest_full_validation_iteration": 20,
    })

    audit = build_goal_completion_audit(
        main_run=main_run,
        official_run=official_run,
        no_smoke_scan=no_smoke_scan,
        domain_boundary_scan=domain_scan,
        external_reference_scan=external_scan,
        tamper_probe=tamper_probe,
        monitor_dir=monitor_dir,
        monitor_snapshot=monitor_snapshot,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "failed"
    assert audit["failed_requirements"][0]["evidence"]["sleep_command_hits"][0]["line"] == 2


def test_goal_completion_auditor_rejects_stale_monitor_snapshot(tmp_path):
    main_run = _make_complete_audit_fixture(tmp_path / "main_run")
    official_run = _make_complete_audit_fixture(tmp_path / "official_run")
    support = tmp_path / "support"
    no_smoke_scan = support / "no_smoke_guard_scan.json"
    domain_scan = support / "domain_boundary_scan.json"
    external_scan = support / "external_reference_scan.json"
    tamper_probe = support / "tamper_probe_result.json"
    monitor_dir = support / "monitor"
    monitor_snapshot = support / "monitor_validation_snapshot.json"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / "monitor.pid").write_text(str(os.getpid()), encoding="utf-8")
    (monitor_dir / "monitor_no_sleep.sh").write_text(
        "while true; do\n  date >/dev/null\n  break\ndone\n",
        encoding="utf-8",
    )
    _write_json(monitor_dir / "monitor_status.json", {
        "schema_version": "dse.dft_first.continuous_monitor.v6",
        "iteration": 200,
        "full_suite_every_iterations": 20,
        "last_status": "completed_horizon",
        "last_failure": "",
        "no_sleep_command_used": True,
    })
    _write_json(no_smoke_scan, {"status": "passed", "items": [{"passed_guard": True}]})
    _write_json(domain_scan, {"status": "passed", "blocked_hit_count": 0})
    _write_json(external_scan, {
        "status": "passed",
        "integration_decision": {"no_final_claim_from_external_models": True},
    })
    _write_json(tamper_probe, {"probe_status": "passed", "cases": [{"passed_probe": True}]})
    _write_json(monitor_snapshot, {
        "schema_version": "dse.dft_first.monitor_validation_snapshot.v6",
        "latest_full_validation_passed": True,
        "all_full_logs_preserved": True,
        "failure_file_exists": False,
        "latest_full_validation_iteration": 120,
    })

    audit = build_goal_completion_audit(
        main_run=main_run,
        official_run=official_run,
        no_smoke_scan=no_smoke_scan,
        domain_boundary_scan=domain_scan,
        external_reference_scan=external_scan,
        tamper_probe=tamper_probe,
        monitor_dir=monitor_dir,
        monitor_snapshot=monitor_snapshot,
        now=datetime(2026, 5, 15, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert audit["status"] == "failed"
    snapshot_failure = [
        item for item in audit["failed_requirements"]
        if item["requirement"].startswith("Continuous monitor")
    ][0]
    assert snapshot_failure["evidence"]["snapshot_fresh_enough"] is False
    assert snapshot_failure["evidence"]["snapshot_iteration_lag"] == 80


def test_monitor_validation_snapshot_requires_full_logs_after_latest_failure(tmp_path):
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    _write_json(monitor / "monitor_status.json", {"schema_version": "dse.dft_first.continuous_monitor.v6"})
    events = []
    for label in sorted(FULL_LABELS):
        log = monitor / f"{label}_iter20.log"
        log.write_text(f"{label} ok\n", encoding="utf-8")
        events.append({
            "iteration": 20,
            "label": label,
            "returncode": 0,
            "log": str(log),
            "start": "2026-05-14 11:00:00 CST (+0800)",
            "end": "2026-05-14 11:00:01 CST (+0800)",
        })
    (monitor / "monitor_events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    (monitor / "monitor_failures.jsonl").write_text(
        json.dumps({"iteration": 10, "label": "targeted_pytest", "returncode": 1}) + "\n",
        encoding="utf-8",
    )

    snapshot = build_monitor_validation_snapshot(monitor)

    assert snapshot["latest_full_validation_iteration"] == 20
    assert snapshot["latest_failure_iteration"] == 10
    assert snapshot["all_full_logs_preserved"] is True
    assert snapshot["full_validation_after_latest_failure"] is True


def test_dft_first_runner_screens_real_qe_source_before_untrusted_skip_step4(tmp_path):
    qe_in = tmp_path / "qe.in"
    qe_out = tmp_path / "qe.out"
    out_dir = tmp_path / "run"
    qe_in.write_text(QE_INPUT, encoding="utf-8")
    qe_out.write_text(QE_LOG, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--qe-input",
            str(qe_in),
            "--qe-log",
            str(qe_out),
            "--case-id",
            "qe_runner_contract",
            "--out",
            str(out_dir),
            "--skip-gem5-l4",
            "--timeout",
            "30",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    summary = json.loads((out_dir / "dft_end_to_end_summary.json").read_text(encoding="utf-8"))
    audit = json.loads((out_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    assert summary["status"] == "blocked_or_untrusted_step4"
    assert audit["status"] == "failed"
    assert audit["passed"] is False
    assert summary["step1"]["facts_only"] is True
    assert summary["scope"]["trusted_final_dft_correctness_claimed"] is False
    dft_default_architectures = {
        "dft-cpu-baseline-v0",
        "dft-fpga-hbm-streaming-v0",
        "dft-fpga-fft-grid-v0",
        "dft-fpga-systolic-gemm-v0",
        "dft-fpga-gpu-diag-hybrid-v0",
        "dft-memory-rich-hbm-v0",
        "dft-low-power-fpga-v0",
    }
    assert summary["best_architecture"]["architecture_id"] in dft_default_architectures
    assert summary["best_architecture"]["latency_ms"] > 0.0
    assert len(summary["step2_step3_records"]) == len(dft_default_architectures)
    assert {record["architecture_id"] for record in summary["step2_step3_records"]} == dft_default_architectures
    assert all(record["timing_verified"] is True for record in summary["step2_step3_records"])
    assert all(record["step3_searchable"] is True for record in summary["step2_step3_records"])
    assert all(record["step3_search_blockers"] == [] for record in summary["step2_step3_records"])
    assert all(record["candidate_only_reasons"] for record in summary["step2_step3_records"])
    assert all(record["step2_status"] in {"ready_for_step3_simulation", "diagnostic_only_candidate"} for record in summary["step2_step3_records"])
    assert all(record["step3_measured_timing"]["full_flow_trusted_final_ranking"] is False for record in summary["step2_step3_records"])
    assert summary["step4_gem5"]["trusted_step4_timing"] is False
    assert summary["completion"]["requires_real_gem5_non_smoke"] is True
    assert summary["completion"]["trusted_final_dft_correctness_claimed"] is False
    ownership = json.loads((out_dir / "dft_artifact_ownership.json").read_text(encoding="utf-8"))
    assert ownership["schema_version"] == "dse.dft.step_artifact_ownership.v1"
    assert "step3_status.json" in ownership["step3_artifacts"]
    assert "domain_physics_validation.json" in ownership["step4_artifacts"]
    first_record = summary["step2_step3_records"][0]
    step4_adj = first_record["step4_adjudication"]
    assert Path(step4_adj["domain_physics_validation"]).exists()
    domain_validation = json.loads(Path(step4_adj["domain_physics_validation"]).read_text(encoding="utf-8"))
    assert domain_validation["schema_version"] == "dse.dft.domain_physics_validation.v1"
    assert domain_validation["status"] == "not_claimed"

    step1_characterization = json.loads((out_dir / "step1" / "workload_characterization.json").read_text(encoding="utf-8"))
    assert step1_characterization["domain_phase_summary"]["schema_version"] == "dse.domain_phase_summary.v1"
    assert step1_characterization["domain_claim_summary"]["observed_hotspots"]


def test_dft_first_runner_materializes_qe_workflow_bundle_paths_before_skip_step4(tmp_path):
    qe_in = tmp_path / "qe.in"
    qe_out = tmp_path / "qe.out"
    profile = tmp_path / "profile.json"
    workflow = tmp_path / "workflow.json"
    out_dir = tmp_path / "workflow_run"
    qe_in.write_text(QE_INPUT, encoding="utf-8")
    qe_out.write_text(QE_LOG, encoding="utf-8")
    _write_json(profile, {"phases": {"h_psi": 2.0, "fft": 0.25}})
    _write_json(workflow, {
        "stages": [
            {
                "program": "pw.x",
                "input_path": "qe.in",
                "log_path": "qe.out",
                "profile_path": "profile.json",
            },
            {
                "program": "bands.x",
                "profile": {"phases": {"diagonalization": 0.5}},
            },
        ]
    })

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--workflow-json",
            str(workflow),
            "--case-id",
            "qe_workflow_runner_contract",
            "--out",
            str(out_dir),
            "--skip-gem5-l4",
            "--timeout",
            "30",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    summary = json.loads((out_dir / "dft_end_to_end_summary.json").read_text(encoding="utf-8"))
    characterization = json.loads((out_dir / "step1" / "workload_characterization.json").read_text(encoding="utf-8"))
    package = json.loads((out_dir / "step1" / "workload_package.json").read_text(encoding="utf-8"))
    audit = json.loads((out_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))

    assert summary["source"]["source_kind"] == "qe_workflow_bundle"
    assert summary["source"]["stage_count"] == 2
    assert summary["status"] == "blocked_or_untrusted_step4"
    assert audit["passed"] is False
    assert characterization["domain_workflow_summary"]["stage_count"] == 2
    assert characterization["domain_claim_summary"]["observed_hotspots"]
    assert characterization["domain_claim_summary"]["observed_dominance"][0]["phase_id"] == "h_psi"
    assert package["domain_metadata"]["dft"]["workflow"]["stages"][0]["source_program"] == "pw.x"


def test_dft_first_runner_writes_failed_audit_for_bad_workflow_path(tmp_path):
    workflow = tmp_path / "bad_workflow.json"
    out_dir = tmp_path / "bad_workflow_run"
    _write_json(workflow, {"stages": [{"program": "pw.x", "input_path": "missing.in"}]})

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--workflow-json",
            str(workflow),
            "--case-id",
            "qe_bad_workflow_contract",
            "--out",
            str(out_dir),
            "--skip-gem5-l4",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    summary = json.loads((out_dir / "dft_end_to_end_summary.json").read_text(encoding="utf-8"))
    audit = json.loads((out_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    assert summary["status"] == "blocked_source_load"
    assert summary["source"]["error_type"] == "FileNotFoundError"
    assert audit["passed"] is False


def test_gem5_l4_proof_can_require_stats_config_and_nonzero_activity(tmp_path):
    stats = tmp_path / "stats.txt"
    config = tmp_path / "config.ini"
    stats.write_text(GEM5_STATS_TEXT, encoding="utf-8")
    config.write_text("[system]\n", encoding="utf-8")
    log = "\n".join([
        "100: system.generic_accel: descriptor_read verified=true",
        "120: system.generic_accel: uarch_request_decode verified=true",
        "180: system.generic_accel: microarchitecture_execute verified=true",
        "200: system.generic_accel: completion_writeback verified=true",
    ])
    stdout = "generic_accel_l4_status=1 error_code=0\ncompletion_magic=0x4753494d completion_status=0\n"
    sim_result = {
        "status": "passed",
        "execution_engine": "gem5_generic_accel_microarchitecture_v1",
        "microarchitecture_summary": {
            "engine": "gem5_generic_accel_microarchitecture_v1",
            "micro_op_count": 4,
            "total_cycles": 123,
            "total_flops": 64,
        },
        "events": [
            {"node_id": "h_psi", "op_type": "gemm", "device": "fpga-0", "start_ns": 0.0, "end_ns": 10.0},
        ],
    }

    proof = build_gem5_l4_proof(
        log,
        stdout,
        sim_result,
        {
            "require_gem5_stats_config": True,
            "gem5_stats": str(stats),
            "gem5_config_ini": str(config),
        },
    )

    assert proof["passed"] is True
    assert proof["checks"]["stats_txt_present"] is True
    assert proof["checks"]["stats_semantics_present"] is True
    assert proof["checks"]["config_present"] is True
    assert proof["checks"]["nonzero_accelerator_activity"] is True
    assert proof["checks"]["systemc_submit_verified"] is False
    assert proof["checks"]["legacy_systemc_or_microarchitecture_verified"] is True

    no_stats = build_gem5_l4_proof(log, stdout, sim_result, {"require_gem5_stats_config": True})
    assert no_stats["passed"] is False
    assert "gem5 m5out stats.txt" in "\n".join(no_stats["missing_evidence"])

    stats.write_text(
        "simTicks 0\nfinalTick 0\nsimInsts 0\nsimOps 0\nsystem.cpu.numCycles 0\n",
        encoding="utf-8",
    )
    bad_stats = build_gem5_l4_proof(
        log,
        stdout,
        sim_result,
        {
            "require_gem5_stats_config": True,
            "gem5_stats": str(stats),
            "gem5_config_ini": str(config),
        },
    )
    assert bad_stats["passed"] is False
    assert bad_stats["checks"]["stats_semantics_present"] is False


def test_dft_end_to_end_auditor_maps_completion_requirements_to_artifacts(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_pass")

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert audit["passed"] is True
    assert audit["failed_count"] == 0
    assert {check["check_id"] for check in audit["checks"]} >= {
        "step1_facts_only",
        "best_architecture_from_measured_step3",
        "step4_non_smoke_artifacts_present",
        "step4_gem5_stats_semantics_present",
        "step4_gem5_proof_checks_pass",
        "step4_no_smoke_demo_or_fallback_tokens",
    }


def test_dft_end_to_end_auditor_rejects_missing_non_smoke_gem5_evidence(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_fail")
    (run_dir / "step4_gem5" / "arch_b" / "stats.txt").unlink()

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_non_smoke_artifacts_present" in failed


def test_dft_end_to_end_auditor_reads_raw_gem5_log_markers(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_log")
    (run_dir / "step4_gem5" / "arch_b" / "gem5.log").write_text(
        "descriptor_read verified=true\ncompletion_writeback verified=true\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert "step4_raw_gem5_evidence_consistent" in failed


def test_dft_end_to_end_auditor_rejects_placeholder_gem5_stats(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_stats_semantics")
    (run_dir / "step4_gem5" / "arch_b" / "stats.txt").write_text(
        "\n".join([
            "simTicks 0",
            "finalTick 0",
            "simInsts 0",
            "simOps 0",
            "system.cpu.numCycles 0",
        ]) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_gem5_stats_semantics_present" in failed


def test_dft_end_to_end_auditor_rejects_step3_artifact_latency_mismatch(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_step3")
    sim_path = run_dir / "architectures" / "arch_b" / "step3_systemc" / "simulation_result.json"
    sim_result = json.loads(sim_path.read_text(encoding="utf-8"))
    sim_result["metrics"]["latency_ms"] = 42.0
    _write_json(sim_path, sim_result)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step3_raw_timing_artifacts_consistent:arch_b" in failed


def test_dft_end_to_end_auditor_rejects_step3_true_raw_result_tamper(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_step3_raw")
    raw_path = run_dir / "architectures" / "arch_b" / "step3_systemc" / "simulation_result.raw.json"
    raw_result = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_result["status"] = "failed"
    raw_result["metrics"]["latency_ms"] = 999.0
    _write_json(raw_path, raw_result)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step3_raw_timing_artifacts_consistent:arch_b" in failed
    assert "step3_artifact_manifest_hashes:arch_b" in failed


def test_dft_end_to_end_auditor_rejects_step3_raw_non_latency_tamper(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_step3_power")
    raw_path = run_dir / "architectures" / "arch_b" / "step3_systemc" / "simulation_result.raw.json"
    raw_result = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_result["metrics"]["power_w"] = 708.456
    _write_json(raw_path, raw_result)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step3_artifact_manifest_hashes:arch_b" in failed


def test_dft_end_to_end_auditor_rejects_non_replayable_step3_manifest(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_step3_manifest")
    _write_json(run_dir / "architectures" / "arch_b" / "step3_systemc" / "manifest.json", {
        "replay_metadata": {
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
            "simulator_replay_command": ["python3", "demo_skip.py", "--request", "simulation_request.json", "--result", "simulation_result.json"],
        }
    })

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step3_replay_manifest_consistent:arch_b" in failed


def test_dft_end_to_end_auditor_rejects_step3_manifest_result_not_raw(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_step3_result_arg")
    step3 = run_dir / "architectures" / "arch_b" / "step3_systemc"
    _write_json(step3 / "manifest.json", {
        "replay_metadata": {
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
            "simulator_replay_command": [
                "model/generic_sim_backend/build/generic_sim",
                "--request",
                str(step3 / "simulation_request.json"),
                "--result",
                str(step3 / "simulation_result.json"),
            ],
        }
    })

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step3_raw_result_replay_bound:arch_b" in failed


def test_dft_end_to_end_auditor_rejects_non_replayable_gem5_manifest(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_manifest")
    _write_json(run_dir / "step4_gem5" / "arch_b" / "manifest.json", {
        "replay_metadata": {
            "simulator_replay_command": ["python3", "fake_demo.py", "--skip-gem5-l4"]
        }
    })

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_manifest_replays_real_gem5" in failed


def test_dft_end_to_end_auditor_rejects_step4_smoke_or_demo_markers(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_smoke_marker")
    step4 = run_dir / "step4_gem5" / "arch_b"
    _write_json(step4 / "manifest.json", {
        "replay_metadata": {
            "simulator_replay_command": [
                "/tmp/gem5/build/X86/gem5.opt",
                "gem5_integration/configs/generic_accel_l4_test.py",
                "--binary",
                "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver",
                "--request",
                str(step4 / "simulation_request.json"),
                "--simulator",
                "model/generic_sim_backend/build/generic_sim",
                "--smoke",
            ]
        }
    })
    _write_step4_artifact_manifest(step4)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_no_smoke_demo_or_fallback_tokens" in failed


def test_dft_end_to_end_auditor_rejects_broken_gem5_proof_source_artifact(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_source_artifact")
    proof_path = run_dir / "step4_gem5" / "arch_b" / "gem5_l4_proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["source_artifacts"]["simulation_result"] = str(run_dir / "missing_simulation_result.raw.json")
    _write_json(proof_path, proof)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_proof_source_artifacts_exist" in failed


def test_dft_end_to_end_auditor_rejects_gem5_proof_not_recomputed_from_raw_stdout(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_stdout")
    (run_dir / "step4_gem5" / "arch_b" / "gem5_stdout.txt").write_text(
        "generic_accel_l4_status=2 error_code=99\ncompletion_magic=0x4753494d completion_status=1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_proof_recomputed_from_raw_artifacts" in failed


def test_dft_end_to_end_auditor_rejects_activity_summary_mismatch(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_bad_activity")
    activity_path = run_dir / "step4_gem5" / "arch_b" / "gem5_activity_summary.json"
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    activity["total_cycles"] = 999
    _write_json(activity_path, activity)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step4_activity_matches_raw_result" in failed


def test_dft_end_to_end_auditor_uses_copy_local_step1_and_step4_artifacts(tmp_path):
    source = _make_complete_audit_fixture(tmp_path / "audit_copy_source")
    copied = tmp_path / "audit_copy"
    import shutil
    shutil.copytree(source, copied)

    package_path = copied / "step1" / "workload_package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["schema_version"] = "tampered.step1"
    _write_json(package_path, package)
    (copied / "step4_gem5" / "arch_b" / "gem5.log").write_text("tampered\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(copied), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((copied / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    failed = {check["check_id"] for check in audit["failed_checks"]}
    assert result.returncode == 2
    assert audit["passed"] is False
    assert "step1_package_schema" in failed
    assert "step4_raw_gem5_evidence_consistent" in failed
    assert "step4_proof_recomputed_from_raw_artifacts" in failed


def test_dft_end_to_end_auditor_accepts_step4_iterated_best_when_fastest_fails(tmp_path):
    run_dir = _make_complete_audit_fixture(tmp_path / "audit_iterated")
    summary_path = run_dir / "dft_end_to_end_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["step2_step3_records"][0]["step3_measured_timing"]["latency_ms"] = 0.5
    summary["step2_step3_records"][1]["step3_measured_timing"]["latency_ms"] = 0.9
    arch_a_sim_path = run_dir / "architectures" / "arch_a" / "step3_systemc" / "simulation_result.json"
    arch_a_sim = json.loads(arch_a_sim_path.read_text(encoding="utf-8"))
    arch_a_sim["metrics"]["latency_ms"] = 0.5
    _write_json(arch_a_sim_path, arch_a_sim)
    arch_a_raw_path = run_dir / "architectures" / "arch_a" / "step3_systemc" / "simulation_result.raw.json"
    arch_a_raw = json.loads(arch_a_raw_path.read_text(encoding="utf-8"))
    arch_a_raw["metrics"]["latency_ms"] = 0.5
    _write_json(arch_a_raw_path, arch_a_raw)
    _write_step3_artifact_manifest(run_dir / "architectures" / "arch_a" / "step3_systemc")
    summary["best_architecture"] = {
        "architecture_id": "arch_b",
        "latency_ms": 0.9,
        "selected_by": "minimum measured Step3 latency among candidates that passed real gem5 GenericAccel non-smoke proof",
    }
    summary["step4_gem5"]["attempts"] = [
        {
            "architecture_id": "arch_a",
            "step3_latency_ms": 0.5,
            "trusted_step4_timing": False,
            "status": "blocked_or_failed",
            "run_dir": str(run_dir / "step4_gem5" / "arch_a"),
        },
        {
            "architecture_id": "arch_b",
            "step3_latency_ms": 0.9,
            "trusted_step4_timing": True,
            "status": "passed",
            "run_dir": str(run_dir / "step4_gem5" / "arch_b"),
        },
    ]
    _write_json(summary_path, summary)

    result = subprocess.run(
        [sys.executable, str(AUDITOR), str(run_dir), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    audit = json.loads((run_dir / "dft_end_to_end_audit.json").read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert audit["passed"] is True


def test_run_step4_gem5_attempts_all_step3_ranked_candidates_and_selects_fastest_non_smoke_pass(tmp_path, monkeypatch):
    from dse_v2.scripts.dse import run_dft_first_end_to_end_dse as runner

    attempted = []

    class FakeAdapter:
        def __init__(self, backend):
            self.backend = backend

        def run_verified_l4(self, **kwargs):
            output_dir = Path(kwargs["output_dir"])
            architecture_id = output_dir.name
            attempted.append(architecture_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            passed = architecture_id in {"slow_pass", "slower_pass"}
            checks = {key: passed for key in REQUIRED_GEM5_CHECKS}
            _write_json(output_dir / "gem5_l4_proof.json", {
                "schema_version": "dse.gem5_l4_proof.v1",
                "passed": passed,
                "fallback_from_gem5": False,
                "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                "checks": checks,
                "missing_evidence": [] if passed else ["injected failed candidate"],
            })
            _write_json(output_dir / "gem5_activity_summary.json", {
                "schema_version": "dse.gem5_activity_summary.v1",
                "execution_engine": "gem5_generic_accel_microarchitecture_v1",
                "nonzero_accelerator_activity": passed,
                "accelerator_event_count": 1 if passed else 0,
                "accelerator_devices": ["fpga-0"] if passed else [],
                "total_cycles": 100 if passed else 0,
                "total_flops": 200 if passed else 0,
            })
            return {
                "request": {},
                "result": {},
                "cmd": ["gem5.opt"],
                "stdout": "",
                "stderr": "",
                "returncode": 0 if passed else 2,
                "gem5_returncode": 0 if passed else 2,
                "gem5_l4_transport_proof": {
                    "source_artifacts": {"fallback_from_gem5": False}
                },
            }

    monkeypatch.setattr(runner, "Gem5SystemCClosureAdapter", FakeAdapter)
    monkeypatch.setattr(
        runner,
        "write_full_flow_evidence",
        lambda **kwargs: {"trusted_for_final_ranking": kwargs.get("gem5_attempted") is True},
    )

    step2 = SimpleNamespace(
        design_point=SimpleNamespace(design_point_id="dp"),
        executable_graph=SimpleNamespace(graph_id="graph"),
        workload_package=SimpleNamespace(workload_id="wl"),
        artifacts={},
    )
    args = SimpleNamespace(
        simulator=Path("model/generic_sim_backend/build/generic_sim"),
        gem5_binary=Path("/tmp/gem5/build/X86/gem5.opt"),
        gem5_config=Path("gem5_integration/configs/generic_accel_l4_test.py"),
        gem5_driver=Path("gem5_integration/test_programs/generic_accel/generic_accel_l4_driver"),
        gem5_max_ticks=1_000_000,
        gem5_cpu_type="atomic",
        timeout=5,
        evidence_mode="debug",
        skip_gem5_l4=False,
    )
    best = {
        "ranked_candidates": [
            {"architecture_id": "fast_fail", "latency_ms": 0.1, "step2_result": step2, "step3_dir": tmp_path / "s_fast"},
            {"architecture_id": "slow_pass", "latency_ms": 0.2, "step2_result": step2, "step3_dir": tmp_path / "s_slow"},
            {"architecture_id": "slower_pass", "latency_ms": 0.3, "step2_result": step2, "step3_dir": tmp_path / "s_slower"},
        ]
    }

    step4 = runner._run_step4_gem5(best=best, run_dir=tmp_path, args=args, cli_argv=[])

    assert attempted == ["fast_fail", "slow_pass", "slower_pass"]
    assert step4["status"] == "passed"
    assert step4["architecture_id"] == "slow_pass"
    assert step4["trusted_step4_timing"] is True
    assert len(step4["attempts"]) == 3
    assert step4["trusted_step4_candidate_count"] == 2
    assert step4["attempts"][0]["status"] == "blocked_or_failed"
    assert step4["attempts"][1]["status"] == "passed"
    assert step4["attempts"][2]["status"] == "passed"
