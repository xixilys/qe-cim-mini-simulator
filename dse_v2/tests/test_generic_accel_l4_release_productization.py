#!/usr/bin/env python3
"""Productization tests for GenericAccel L4 replay/release evidence tooling."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path

import pytest

from dse_v2.codesign.generic_accel_l4_release import (
    generate_release_artifacts,
    probe_gem5_local_rebuild,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_repo_root(root: Path) -> Path:
    repo = root / "repo"
    (repo / "gem5_integration/configs").mkdir(parents=True)
    (repo / "gem5_integration/configs/generic_accel_l4_test.py").write_text("# config\n", encoding="utf-8")
    driver = repo / "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver"
    driver.parent.mkdir(parents=True)
    driver.write_text("driver", encoding="utf-8")
    driver.chmod(0o755)
    sim = repo / "model/generic_sim_backend/build/generic_sim"
    sim.parent.mkdir(parents=True)
    sim.write_text("sim", encoding="utf-8")
    sim.chmod(0o755)
    (repo / "dse_v2/scripts/dse").mkdir(parents=True)
    return repo


def _proof() -> dict:
    return {
        "passed": True,
        "checks": {
            "descriptor_read_verified": True,
            "request_decode_verified": True,
            "microarchitecture_execute_verified": True,
            "completion_writeback_verified": True,
            "driver_status_verified": True,
            "driver_completion_descriptor_verified": True,
            "result_status_passed": True,
            "non_smoke_l4_activity": True,
            "stats_txt_present": True,
            "stats_semantics_present": True,
            "config_present": True,
            "nonzero_accelerator_activity": True,
        },
        "fallback_from_gem5": False,
        "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        "source_artifacts": {"transport_harness": "gem5_generic_accel_microarchitecture_v1"},
    }


def _make_expanded_runroot(
    root: Path,
    *,
    candidate_id: str = "slot4_fpga_fft_candidate",
    workload_case_id: str = "qe_scf_fft_smoke",
) -> Path:
    runroot = root / "runroot"
    row_dir = runroot / "proof_runs" / "valid_fft"
    _write_json(row_dir / "gem5_l4_proof.json", _proof())
    _write_json(row_dir / "l4_interface_metrics.json", {"schema_version": "dse.l4_interface_metrics.v1", "status": "passed"})
    _write_json(row_dir / "raw_l4_interface_observations.json", {"schema_version": "dse.raw_l4_interface_observations.v1"})
    _write_json(row_dir / "simulation_request.json", {"run_id": "req"})
    _write_json(row_dir / "simulation_result.raw.json", {"status": "passed"})
    neg_dir = runroot / "proof_runs" / "bad_descriptor"
    _write_json(neg_dir / "gem5_l4_proof.json", {"passed": False, "proof_status": "expected_descriptor_error"})
    expanded = {
        "schema_version": "dse.slot4.generic_accel_l4_expanded_proof_matrix.v1",
        "created_at": "2026-05-27T00:00:00+00:00",
        "gem5_binary": str(root / "external" / "gem5.opt"),
        "gem5_binary_sha256": "sha-gem5",
        "row_count": 2,
        "passed_runtime_rows": 1,
        "expected_negative_rows": 1,
        "rows": [
            {
                "row_id": "valid_fft",
                "candidate_id": candidate_id,
                "workload_case_id": workload_case_id,
                "expected": "passed",
                "driver_repeat": 1,
                "gem5_returncode": 0,
                "elapsed_s": 0.1,
                "run_dir": str(row_dir),
                "proof_passed": True,
                "proof_status": "passed",
                "metrics_status": "passed",
                "log_markers": {"descriptor_read_true_count": 1},
            },
            {
                "row_id": "bad_descriptor",
                "candidate_id": "slot4_bad_descriptor_candidate",
                "workload_case_id": "descriptor_validation_bad_magic",
                "expected": "descriptor_error",
                "run_dir": str(neg_dir),
                "proof_passed": False,
                "proof_status": "expected_descriptor_error",
                "descriptor_error_observed": True,
            },
        ],
    }
    _write_json(runroot / "generic_accel_l4_expanded_proof_matrix.json", expanded)
    _write_json(
        runroot / "local_rebuild_probe_report.json",
        {
            "schema_version": "dse.slot4.local_rebuild_probe_report.v1",
            "status": "blocked_precise",
            "local_rebuild_claim_supported": False,
            "blockers": [
                {"id": "current_worktree_gem5_source_tree_missing", "detail": "missing SConstruct"},
                {"id": "swig_provider_missing", "detail": "missing swig"},
            ],
        },
    )
    return runroot


def test_release_artifacts_are_repo_owned_and_fail_closed_without_cdse_crosswalk(tmp_path):
    repo = _make_repo_root(tmp_path)
    runroot = _make_expanded_runroot(tmp_path)
    worklist = tmp_path / "worklist.json"
    _write_json(
        worklist,
        {
            "schema_version": "dse.dft.run2.candidate_kernel_target_ppa_gate_worklist.v1",
            "status": "recorded_fail_closed_worklist",
            "candidate_kernel_target_axis_count": 1,
            "gate_row_count": 24,
            "trusted_pass_count": 0,
            "work_items": [
                {
                    "candidate_id": "cdse_1",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "claimable": False,
                    "dominant_status": "blocked_missing_input",
                    "gate_row_count": 24,
                    "blocker_ids": ["missing_target_specific_gate_evidence:golden_correctness"],
                }
            ],
        },
    )

    status = generate_release_artifacts(runroot=runroot, repo_root=repo, slot2_worklist=worklist)

    step4 = json.loads((runroot / "step4_l4_evidence_rows.json").read_text(encoding="utf-8"))
    coverage = json.loads((runroot / "candidate_workload_l4_coverage_matrix.json").read_text(encoding="utf-8"))
    binding = json.loads((runroot / "release_gate_l4_binding_status.json").read_text(encoding="utf-8"))
    replay = (runroot / "replay_contract.sh").read_text(encoding="utf-8")

    assert status["deliverable_complete"] is False
    assert step4["producer"] == "dse_v2.scripts.dse.build_generic_accel_l4_release_artifacts"
    assert step4["row_count"] == 1
    assert step4["rows"][0]["claim_label"] == "mvp_partial_l4_runtime_only"
    assert "synthetic_slot4_candidate_not_cdse_run2_candidate" in step4["rows"][0]["blockers"]
    assert coverage["actual_run2_cdse_scope"]["mapped_l4_evidence_row_count"] == 0
    assert coverage["actual_run2_cdse_scope"]["mapped_trusted_l4_evidence_row_count"] == 0
    assert binding["deliverable_complete"] is False
    assert "dse_v2/scripts/dse/run_generic_accel_l4_release_replay.py" in replay
    assert "dse_v2/scripts/dse/build_generic_accel_l4_release_artifacts.py" in replay
    assert "$RUNROOT/replay/run_expanded_gem5_l4_matrix.py" not in replay


def test_cdse_crosswalk_counts_mapped_rows_but_keeps_release_blocked_until_trusted(tmp_path):
    repo = _make_repo_root(tmp_path)
    runroot = _make_expanded_runroot(tmp_path, candidate_id="slot4_l4_cand", workload_case_id="l4_fft")
    worklist = tmp_path / "worklist.json"
    _write_json(
        worklist,
        {
            "schema_version": "dse.dft.run2.candidate_kernel_target_ppa_gate_worklist.v1",
            "status": "recorded_fail_closed_worklist",
            "candidate_kernel_target_axis_count": 1,
            "gate_row_count": 24,
            "trusted_pass_count": 0,
            "work_items": [
                {
                    "candidate_id": "cdse_1",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "claimable": False,
                    "dominant_status": "blocked_missing_input",
                    "gate_row_count": 24,
                    "blocker_ids": ["missing_target_specific_gate_evidence:vivado_fpga_synth_or_impl"],
                }
            ],
        },
    )
    candidate_crosswalk = tmp_path / "candidate_crosswalk.json"
    workload_crosswalk = tmp_path / "workload_crosswalk.json"
    _write_json(
        candidate_crosswalk,
        {
            "candidate_crosswalk": {
                "cdse_1": {
                    "l4_candidate_id": "slot4_l4_cand",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                }
            }
        },
    )
    _write_json(
        workload_crosswalk,
        {
            "workload_crosswalk": {
                "fft_ifft_ffft": {
                    "l4_workload_case_ids": ["l4_fft"],
                    "equivalence_scope": "explicit_current_goal_l4_workload",
                    "confidence": 1.0,
                }
            }
        },
    )

    generate_release_artifacts(
        runroot=runroot,
        repo_root=repo,
        slot2_worklist=worklist,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
    )

    coverage = json.loads((runroot / "candidate_workload_l4_coverage_matrix.json").read_text(encoding="utf-8"))
    binding = json.loads((runroot / "release_gate_l4_binding_status.json").read_text(encoding="utf-8"))

    assert coverage["actual_run2_cdse_scope"]["mapped_l4_evidence_row_count"] == 1
    assert coverage["actual_run2_cdse_scope"]["mapped_trusted_l4_evidence_row_count"] == 0
    assert coverage["actual_run2_cdse_scope"]["mapped_rows"][0]["l4_candidate_id"] == "slot4_l4_cand"
    assert coverage["deliverable_complete"] is False
    assert "mapped_l4_rows_not_trusted_for_speedup_claim" in coverage["blockers"]
    assert binding["release_consumable_integration_status"]["actual_cdse_mapped_l4_rows"] == 1
    assert binding["deliverable_complete"] is False


def test_local_rebuild_probe_records_gitlink_missing_submodule_and_swig_blockers(tmp_path):
    repo = tmp_path / "repo"
    (repo / "gem5_integration").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            "160000,76a49b93e7df350755d9cce0ef19f7bd28da5422,gem5_integration/gem5",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    runroot = tmp_path / "runroot"

    report = probe_gem5_local_rebuild(
        repo_root=repo,
        runroot=runroot,
        swig_lookup=lambda: None,
        source_roots=[repo / "gem5_integration/gem5"],
    )

    blocker_ids = {item["id"] for item in report["blockers"]}
    assert report["local_rebuild_claim_supported"] is False
    assert "current_worktree_gem5_source_tree_missing" in blocker_ids
    assert "gitlink_without_gitmodules_mapping" in blocker_ids
    assert "swig_provider_missing" in blocker_ids
    assert report["gitlink_status"]["is_gitlink"] is True
    assert report["gitlink_status"]["has_gitmodules_mapping"] is False


def test_release_artifacts_emit_local_rebuild_contract_and_cdse_intake_queue(tmp_path):
    repo = _make_repo_root(tmp_path)
    runroot = _make_expanded_runroot(tmp_path)
    worklist = tmp_path / "worklist.json"
    _write_json(
        worklist,
        {
            "schema_version": "dse.dft.run2.candidate_kernel_target_ppa_gate_worklist.v1",
            "status": "recorded_fail_closed_worklist",
            "candidate_kernel_target_axis_count": 2,
            "gate_row_count": 48,
            "trusted_pass_count": 0,
            "work_items": [
                {
                    "candidate_id": "cdse_1",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "claimable": False,
                    "dominant_status": "blocked_missing_input",
                    "gate_row_count": 24,
                    "blocker_ids": ["missing_target_specific_gate_evidence:golden_correctness"],
                },
                {
                    "candidate_id": "cdse_2",
                    "kernel_id": "nonlocal_projector",
                    "target_platform_kind": "asic",
                    "claimable": False,
                    "dominant_status": "blocked_missing_input",
                    "gate_row_count": 24,
                    "blocker_ids": ["missing_target_specific_gate_evidence:dc_asic_synth_or_timing"],
                },
            ],
        },
    )
    provider = tmp_path / "gem5_provider"
    generic = provider / "src/dev/generic_accel"
    generic.mkdir(parents=True)
    (provider / "SConstruct").write_text("# gem5 source root\n", encoding="utf-8")
    for name in ("GenericAccel.py", "SConscript", "generic_accel.cc", "generic_accel.hh"):
        (generic / name).write_text(f"{name}\n", encoding="utf-8")
    local_report = json.loads((runroot / "local_rebuild_probe_report.json").read_text(encoding="utf-8"))
    local_report["source_candidates"] = [
        {
            "root": str(provider),
            "exists": True,
            "sconstruct_exists": True,
            "generic_accel_dir_exists": True,
            "active_vs_source": {
                name: {"active_exists": True, "source_exists": True, "same_sha256": True}
                for name in ("GenericAccel.py", "SConscript", "generic_accel.cc", "generic_accel.hh")
            },
        }
    ]
    local_report["swig_provider_search"] = {"candidate_count": 1, "usable": [], "probes": [{"path": "/missing/swig", "exists": False}]}
    _write_json(runroot / "local_rebuild_probe_report.json", local_report)

    status = generate_release_artifacts(runroot=runroot, repo_root=repo, slot2_worklist=worklist)

    local_contract = json.loads((runroot / "local_rebuild_contract.json").read_text(encoding="utf-8"))
    local_script = (runroot / "local_rebuild_contract.sh").read_text(encoding="utf-8")
    intake = json.loads((runroot / "cdse_l4_binding_intake_queue.json").read_text(encoding="utf-8"))
    binding = json.loads((runroot / "release_gate_l4_binding_status.json").read_text(encoding="utf-8"))

    assert local_contract["selected_source_provider"]["root"] == str(provider)
    assert local_contract["status"] == "blocked_missing_swig_provider"
    assert local_contract["local_rebuild_claim_supported"] is False
    assert local_contract["rebuild_executed"] is False
    assert any("scons build/X86/gem5.opt" in cmd for cmd in local_contract["rebuild_commands"])
    assert "sudo" not in local_script
    assert "scons build/X86/gem5.opt" in local_script
    assert intake["status"] == "awaiting_cdse_l4_binding_inputs"
    assert intake["work_item_count"] == 2
    assert intake["queue_items"][0]["expected_l4_request_artifact"].endswith("simulation_request.json")
    assert "gem5_l4_proof_passed" in intake["queue_items"][0]["required_artifacts"]
    assert binding["release_consumable_integration_status"]["local_rebuild_contract"].endswith("local_rebuild_contract.json")
    assert binding["release_consumable_integration_status"]["cdse_l4_binding_intake_queue"].endswith("cdse_l4_binding_intake_queue.json")
    assert "local_rebuild_contract.json" in status["artifacts"]
    assert "cdse_l4_binding_intake_queue.json" in status["artifacts"]
    assert status["deliverable_complete"] is False


def test_release_artifacts_promote_local_rebuild_only_after_matching_replay_evidence(tmp_path):
    repo = _make_repo_root(tmp_path)
    runroot = _make_expanded_runroot(tmp_path)
    worklist = tmp_path / "worklist.json"
    _write_json(
        worklist,
        {
            "schema_version": "dse.dft.run2.candidate_kernel_target_ppa_gate_worklist.v1",
            "status": "recorded_fail_closed_worklist",
            "candidate_kernel_target_axis_count": 1,
            "gate_row_count": 24,
            "trusted_pass_count": 0,
            "work_items": [
                {
                    "candidate_id": "cdse_1",
                    "kernel_id": "fft_ifft_ffft",
                    "target_platform_kind": "fpga",
                    "claimable": False,
                    "dominant_status": "blocked_missing_input",
                    "gate_row_count": 24,
                    "blocker_ids": ["missing_target_specific_gate_evidence:golden_correctness"],
                }
            ],
        },
    )
    provider = tmp_path / "gem5_provider"
    generic = provider / "src/dev/generic_accel"
    generic.mkdir(parents=True)
    (provider / "SConstruct").write_text("# gem5 source root\n", encoding="utf-8")
    for name in ("GenericAccel.py", "SConscript", "generic_accel.cc", "generic_accel.hh"):
        (generic / name).write_text(f"{name}\n", encoding="utf-8")
    gem5_bin = provider / "build/X86/gem5.opt"
    gem5_bin.parent.mkdir(parents=True)
    gem5_bin.write_text("rebuilt-gem5\n", encoding="utf-8")
    gem5_bin.chmod(0o755)
    gem5_sha = hashlib.sha256(gem5_bin.read_bytes()).hexdigest()

    expanded = json.loads((runroot / "generic_accel_l4_expanded_proof_matrix.json").read_text(encoding="utf-8"))
    expanded["gem5_binary"] = str(gem5_bin)
    expanded["gem5_binary_sha256"] = gem5_sha
    _write_json(runroot / "generic_accel_l4_expanded_proof_matrix.json", expanded)

    local_report = json.loads((runroot / "local_rebuild_probe_report.json").read_text(encoding="utf-8"))
    local_report["source_candidates"] = [
        {
            "root": str(provider),
            "exists": True,
            "sconstruct_exists": True,
            "generic_accel_dir_exists": True,
            "active_vs_source": {
                name: {"active_exists": True, "source_exists": True, "same_sha256": True}
                for name in ("GenericAccel.py", "SConscript", "generic_accel.cc", "generic_accel.hh")
            },
        }
    ]
    local_report["swig_provider_search"] = {"candidate_count": 1, "usable": ["/tooling/swig"], "probes": []}
    _write_json(runroot / "local_rebuild_probe_report.json", local_report)

    logs = runroot / "logs"
    logs.mkdir()
    (runroot / "local_rebuild_gem5_binary.sha256").write_text(
        f"{gem5_sha}  build/X86/gem5.opt\n",
        encoding="utf-8",
    )
    (logs / "local_rebuild_contract_20260527T000000Z.log").write_text(
        "\n".join([
            "scons: done building targets.",
            f"Local rebuild binary: {gem5_bin}",
        ]),
        encoding="utf-8",
    )
    (logs / "replay_contract_20260527T000100Z.log").write_text(
        "\n".join([
            f"python3 dse_v2/scripts/dse/run_generic_accel_l4_release_replay.py --gem5-bin {gem5_bin} --external-binary-ok",
            "Replay contract completed.",
        ]),
        encoding="utf-8",
    )

    generate_release_artifacts(runroot=runroot, repo_root=repo, slot2_worklist=worklist)

    local_contract = json.loads((runroot / "local_rebuild_contract.json").read_text(encoding="utf-8"))
    binding = json.loads((runroot / "release_gate_l4_binding_status.json").read_text(encoding="utf-8"))
    complete_report = json.loads((runroot / "complete_dse_full_l4_evidence_report.json").read_text(encoding="utf-8"))

    assert local_contract["status"] == "local_rebuild_and_replay_verified"
    assert local_contract["local_rebuild_claim_supported"] is True
    assert local_contract["rebuild_executed"] is True
    assert local_contract["verified_execution"]["rebuilt_gem5_binary"]["path"] == str(gem5_bin)
    assert local_contract["verified_execution"]["rebuilt_gem5_binary"]["sha256"] == gem5_sha
    assert local_contract["verified_execution"]["replay_verified_with_rebuilt_binary"] is True
    assert binding["local_rebuild_status"]["local_rebuild_claim_supported"] is True
    assert "local_rebuild_not_proven_current_lane" not in binding["blockers"]
    assert binding["deliverable_complete"] is False
    checklist = {item["requirement"]: item for item in complete_report["prompt_to_artifact_checklist"]}
    assert checklist["local source rebuild and replay verified"]["passed"] is True
