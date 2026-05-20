#!/usr/bin/env python3
"""Tests for the fail-closed DFT current-goal L4 bridge."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_current_goal_l4_bridge import (
    EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
    EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
    build_dft_current_goal_l4_bridge,
    write_dft_current_goal_l4_bridge,
)
from dse_v2.reference_workloads.dft_scf_six_class_suite import REQUIRED_DFT_SCF_CLASS_IDS


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _release_gate(path: Path, *, count: int = EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT) -> Path:
    candidate_rows = []
    unit_rows = []
    for index in range(count):
        candidate_id = f"cand_{index:02d}"
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "status": "candidate_hardware_gate_passed",
                "candidate_hardware_gate_passed": True,
                "distinct_kernel_count": 8,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
        unit_rows.append({"candidate_id": candidate_id, "kernel_id": "fft_3d", "unit_gate_passed": True})
    payload = {
        "schema_version": "dse.dft.hardware_closure_release_gate.v1",
        "status": "hardware_release_gate_passed_pending_deliverable_claim",
        "release_id": "dft_hw_current_goal",
        "candidate_count": count,
        "candidate_rows": candidate_rows,
        "unit_rows": unit_rows,
        "hardware_completion_eligible": count == EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
        "deliverable_complete": False,
    }
    _write_json(path, payload)
    return path


def _six_scf_manifest(path: Path) -> Path:
    cases = []
    for class_id in REQUIRED_DFT_SCF_CLASS_IDS:
        cases.append(
            {
                "case_id": f"{class_id}_case",
                "class_id": class_id,
                "workload_class": class_id,
                "descriptor": {"path": f"descriptors/{class_id}.json", "sha256": "0" * 64},
                "proof_class": "synthetic_descriptor_runnable_fixture_not_final_qe_evidence",
                "reference_output_hash": None,
                "final_real_qe_evidence": False,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
    payload = {
        "schema_version": "dse.dft_scf.six_class_descriptor_runnable_bundle.v1",
        "bundle_id": "six-scf-test",
        "suite_id": "dft_scf_six_class_suite_v1",
        "strict": True,
        "descriptor_plus_runnable_bundle": True,
        "case_count": len(cases),
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "workload_classes": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "cases": cases,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }
    _write_json(path, payload)
    return path


def test_bridge_emits_36_candidate_six_scf_crosswalk_and_blocked_l4_root(tmp_path):
    release_gate = _release_gate(tmp_path / "step5" / "dft_hardware_closure_release_gate.json")
    six_scf = _six_scf_manifest(tmp_path / "six" / "dft_scf_six_class_bundle_manifest.json")

    status = write_dft_current_goal_l4_bridge(
        tmp_path / "bridge",
        release_gate_path=release_gate,
        six_scf_manifest_path=six_scf,
    )

    release_subset = json.loads((tmp_path / "bridge" / "release_subset_manifest.json").read_text(encoding="utf-8"))
    workload_suite = json.loads((tmp_path / "bridge" / "workload_suite_manifest.json").read_text(encoding="utf-8"))
    crosswalk = json.loads((tmp_path / "bridge" / "current_goal_l4_crosswalk.json").read_text(encoding="utf-8"))
    matrix = json.loads((tmp_path / "bridge" / "current_goal_l4_root" / "l4_evidence_matrix.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "bridge" / "current_goal_l4_root" / "coverage_claim_report.json").read_text(encoding="utf-8"))
    complete_report = json.loads(
        (tmp_path / "bridge" / "current_goal_l4_root" / "complete_dse_full_l4_evidence_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert status["status"] == "passed"
    assert release_subset["candidate_count"] == 36
    assert len(release_subset["legal_candidate_ids"]) == 36
    assert all(candidate_id.startswith("cand_") for candidate_id in release_subset["legal_candidate_ids"])
    assert workload_suite["workload_case_count"] == 6
    assert workload_suite["workload_classes"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert crosswalk["candidate_crosswalk_count"] == 36
    assert crosswalk["workload_crosswalk_count"] == 6
    assert crosswalk["candidate_crosswalk"]["cand_00"]["l4_candidate_id"] == "cand_00"
    assert crosswalk["workload_crosswalk"]["small_multi_k_scf"]["l4_workload_case_ids"] == ["small_multi_k_scf_case"]
    assert crosswalk["legacy_9x4_crosswalk_assessment"]["status"] == "insufficient_for_current_goal"
    assert crosswalk["legacy_9x4_crosswalk_assessment"]["blocker_id"] == "old_9x4_crosswalk_insufficient_for_36x6_current_goal"
    assert matrix["expected_row_count"] == 36 * 6
    assert matrix["row_count"] == 36 * 6
    assert matrix["coverage_status"] == "blocked"
    assert matrix["deliverable_complete_eligible"] is False
    assert report["claims"]["deliverable_complete"] is False
    assert complete_report["schema_version"] == "dse.codesign.complete_dse_full_l4_report.v1"
    assert complete_report["status"] == "blocked_or_partial"
    assert complete_report["claims"]["deliverable_complete"] is False
    assert complete_report["row_count"] == 0
    assert complete_report["matrix_row_count"] == 36 * 6
    assert status["deliverable_complete"] is False


def test_bridge_fails_closed_for_old_9_candidate_shape_without_completion_claim(tmp_path):
    release_gate = _release_gate(tmp_path / "step5" / "dft_hardware_closure_release_gate.json", count=9)
    six_scf = _six_scf_manifest(tmp_path / "six" / "dft_scf_six_class_bundle_manifest.json")

    payload = build_dft_current_goal_l4_bridge(
        release_gate_path=release_gate,
        six_scf_manifest_path=six_scf,
        pending_l4_root=tmp_path / "pending_l4",
    )

    assert payload["status"] == "blocked_identity_bridge_inputs_invalid"
    assert payload["actual_candidate_count"] == 9
    assert payload["actual_l4_row_count"] == 9 * 6
    assert any(blocker["blocker_id"] == "current_goal_candidate_count_not_36" for blocker in payload["blockers"])
    assert payload["legacy_9x4_crosswalk_assessment"]["status"] == "insufficient_for_current_goal"
    assert payload["deliverable_complete"] is False
    matrix = json.loads((tmp_path / "pending_l4" / "l4_evidence_matrix.json").read_text(encoding="utf-8"))
    assert matrix["row_count"] == 9 * 6
    assert matrix["deliverable_complete_eligible"] is False


def test_bridge_does_not_fabricate_gem5_qe_or_ppa_passes(tmp_path):
    release_gate = _release_gate(tmp_path / "step5" / "dft_hardware_closure_release_gate.json")
    six_scf = _six_scf_manifest(tmp_path / "six" / "dft_scf_six_class_bundle_manifest.json")

    status = write_dft_current_goal_l4_bridge(
        tmp_path / "bridge",
        release_gate_path=release_gate,
        six_scf_manifest_path=six_scf,
    )
    bridge = json.loads((tmp_path / "bridge" / "dft_current_goal_l4_bridge.json").read_text(encoding="utf-8"))
    preflight = json.loads((tmp_path / "bridge" / "current_goal_l4_root" / "gem5_preflight.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert bridge["gem5_l4_evidence_present"] is False
    assert bridge["qe_reference_evidence_present"] is False
    assert bridge["ppa_evidence_fabricated"] is False
    assert bridge["final_closure_eligible"] is False
    assert bridge["deliverable_complete"] is False
    assert preflight["status"] == "blocked_pending_regenerated_l4_execution"
    assert "no_gem5_l4_proof_files_present" in preflight["blockers"]


def test_bridge_cli_writes_status_and_supports_blocked_exit_override(tmp_path):
    release_gate = _release_gate(tmp_path / "step5" / "dft_hardware_closure_release_gate.json", count=9)
    six_scf = _six_scf_manifest(tmp_path / "six" / "dft_scf_six_class_bundle_manifest.json")
    out = tmp_path / "cli_out"

    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_current_goal_l4_bridge.py",
            "--out",
            str(out),
            "--release-gate",
            str(release_gate),
            "--six-scf-manifest",
            str(six_scf),
            "--allow-blocked",
            "--quiet",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    status = json.loads((out / "dft_current_goal_l4_bridge_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked"
    assert status["legacy_9x4_crosswalk_status"] == "insufficient_for_current_goal"
    assert status["deliverable_complete"] is False
