#!/usr/bin/env python3
"""Complete-DSE reporting package regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dse_v2.reporting.complete_dse_claims import (
    FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS,
    GOAL_REQUIREMENT_EVIDENCE_SPECS,
    REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS,
    write_complete_dse_reporting_package,
)


def test_reporting_package_requires_release_candidate_trial_ledger(tmp_path: Path) -> None:
    out_dir = tmp_path / "reporting"
    manifest = write_complete_dse_reporting_package(
        out_dir,
        candidate_ids=["cdse_a", "cdse_b"],
        workload_case_ids=["scf_a", "scf_b", "scf_c", "scf_d", "scf_e", "scf_f"],
    )

    assert "release_candidate_trial_ledger.json" in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS
    assert "release_candidate_trial_ledger.json" in manifest["artifacts"]
    ledger = json.loads((out_dir / "release_candidate_trial_ledger.json").read_text(encoding="utf-8"))
    assert ledger["schema_version"] == "dse.codesign.complete_dse.release_candidate_trial_ledger.v1"
    assert ledger["candidate_count"] == 2
    assert ledger["frozen_workload_case_count"] == 6
    assert ledger["required_l4_evidence_row_count"] == 12
    assert ledger["release_completion_eligible"] is False
    assert ledger["trusted_final_claim"] is False

    coverage = json.loads((out_dir / "coverage_claim_report.json").read_text(encoding="utf-8"))
    assert "release_candidate_trial_ledger.json" in coverage["required_artifacts"]
    checklist = json.loads((out_dir / "prompt_to_artifact_checklist.json").read_text(encoding="utf-8"))
    requirements = {row["requirement"]: row for row in checklist["checklist"]}
    assert requirements["artifact::release_candidate_trial_ledger.json"]["status"] == "present_hash_valid"


def test_reporting_package_surfaces_qe_baseline_materialization_triplet_fail_closed(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "reporting"
    manifest = write_complete_dse_reporting_package(
        out_dir,
        candidate_ids=["cdse_a"],
        workload_case_ids=["scf_a"],
    )

    materialization_artifacts = (
        "dft_scf_six_class_qe_baseline_materialization.json",
        "dft_scf_six_class_qe_baseline_materialization_validation.json",
        "dft_scf_six_class_qe_baseline_materialization_status.json",
    )
    for name in materialization_artifacts:
        assert name in FULL_SCF_ACCOUNTING_REPORTING_ARTIFACTS
        assert name in REQUIRED_COMPLETE_DSE_REPORT_ARTIFACTS
        assert name in manifest["artifacts"]
        payload = json.loads((out_dir / name).read_text(encoding="utf-8"))
        assert payload["status"] == "blocked"
        assert payload["deliverable_complete"] is False
        assert payload["hardware_completion_eligible"] is False
        assert payload["release_completion_eligible"] is False
        assert payload["trusted_final_claim"] is False

    matrix = json.loads((out_dir / "requirement_evidence_matrix.json").read_text(encoding="utf-8"))
    rows = {row["requirement_id"]: row for row in matrix["requirement_rows"]}
    for requirement_id in ("done_when_11", "done_when_12"):
        row = rows[requirement_id]
        for name in materialization_artifacts:
            assert name in row["artifact_names"]
            assert name in row["artifact_refs"]
        assert row["claimable"] is False
        assert row["evidence_status"] == "blocked_missing_input"


def test_qe_baseline_materialization_refs_attach_to_candidate_workflow_ledger_without_claim_upgrade(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "reporting"
    materialization_artifacts = (
        "dft_scf_six_class_qe_baseline_materialization.json",
        "dft_scf_six_class_qe_baseline_materialization_validation.json",
        "dft_scf_six_class_qe_baseline_materialization_status.json",
    )
    source_refs = {
        name: {
            "path": f"run2/{name}",
            "sha256": f"{index + 1:064x}",
            "hash_algorithm": "sha256",
            "source_lane": "run2",
            "status": "passed",
            "pure_software_qe_baseline": True,
            "hardware_acceleration_evidence": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
        }
        for index, name in enumerate(materialization_artifacts)
    }

    write_complete_dse_reporting_package(
        out_dir,
        candidate_ids=["cdse_a"],
        workload_case_ids=["scf_a"],
        source_artifact_refs=source_refs,
    )

    ledger = json.loads(
        (out_dir / "candidate_workflow_evidence_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    row = ledger["rows"][0]
    baseline_ref = row["evidence_refs"]["pure_software_qe_baseline_materialization"]
    assert baseline_ref["artifact_names"] == list(materialization_artifacts)
    assert set(baseline_ref["artifact_refs"]) == set(materialization_artifacts)
    assert baseline_ref["candidate_id"] == "cdse_a"
    assert baseline_ref["workload_case_id"] == "scf_a"
    assert baseline_ref["workload_case_binding_status"] == "package_level_unbound"
    assert "qe_baseline_materialization_workload_case_id_missing" in baseline_ref["blockers"]
    assert baseline_ref["claim_upgrade_allowed"] is False
    assert baseline_ref["hardware_completion_eligible"] is False
    assert baseline_ref["release_completion_eligible"] is False
    assert baseline_ref["trusted_final_claim"] is False
    assert baseline_ref["deliverable_complete"] is False
    assert ledger["deliverable_complete"] is False

    target_ledger = json.loads(
        (out_dir / "dft_candidate_workflow_target_evidence_gate_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert target_ledger["rows"] == []
    assert target_ledger["deliverable_complete"] is False


def test_requirement_audit_surfaces_qe_baseline_row_accounting_attachment_without_claim_upgrade(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "reporting"
    qe_baseline_path = tmp_path / "qe_baseline_comparison_index.json"
    row_accounting_path = tmp_path / "full_scf_row_accounting.json"
    qe_baseline_payload = {
        "schema_version": "dse.dft.qe_baseline_comparison_index.v1",
        "status": "comparison_index_present",
        "comparison_case_count": 1,
        "comparison_rows": [{"case_id": "qe_a", "baseline_wall_time_s": 1.0}],
        "claim_upgrade_allowed": False,
        "hardware_completion_eligible": False,
        # Deliberately adversarial: source artifacts can be over-optimistic, but
        # requirement-matrix attachment fields must remain fail-closed.
        "deliverable_complete": True,
    }
    row_accounting_payload = {
        "schema_version": "dse.dft.numerical.full_scf_row_accounting.v1",
        "status": "passed",
        "passed": True,
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": True,
        "full_scf_schedule_consumed": True,
        "host_bound_costs_included": True,
        "runtime_trace_source": "qe_offload_runtime_trace",
        "candidate_id": "cand-a",
        "workload_case_id": "scf-a",
        "blockers": [],
        "claim_upgrade_allowed": False,
        "hardware_completion_eligible": False,
        # Deliberately adversarial: source artifacts can be over-optimistic, but
        # requirement-matrix attachment fields must remain fail-closed.
        "deliverable_complete": True,
    }
    qe_baseline_path.write_text(
        json.dumps(qe_baseline_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    row_accounting_path.write_text(
        json.dumps(row_accounting_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_artifact_refs = {
        "qe_baseline_comparison_index.json": {
            "path": str(qe_baseline_path),
            "sha256": hashlib.sha256(qe_baseline_path.read_bytes()).hexdigest(),
            "hash_algorithm": "sha256",
            "status": "present_hash_valid",
        },
        "full_scf_row_accounting.json": {
            "path": str(row_accounting_path),
            "sha256": hashlib.sha256(row_accounting_path.read_bytes()).hexdigest(),
            "hash_algorithm": "sha256",
            "status": "present_hash_valid",
        },
    }

    write_complete_dse_reporting_package(
        out_dir,
        candidate_ids=["cand-a"],
        workload_case_ids=["scf-a", "scf-b"],
        source_artifact_refs=source_artifact_refs,
    )

    requirement_audit = json.loads(
        (out_dir / "requirement_evidence_matrix.json").read_text(encoding="utf-8")
    )
    done_when_11 = {
        row["requirement_id"]: row for row in requirement_audit["requirement_rows"]
    }["done_when_11"]
    attachment = done_when_11["full_scf_evaluated_hybrid_status"][
        "qe_baseline_row_accounting_attachment"
    ]
    assert attachment["present"] is True
    assert attachment["claim_upgrade_allowed"] is False
    assert attachment["hardware_completion_eligible"] is False
    assert attachment["trusted_final_claim"] is False
    assert attachment["deliverable_complete"] is False
    assert attachment["artifact_refs"]["qe_baseline_comparison_index.json"][
        "path"
    ] == str(qe_baseline_path)
    assert attachment["artifact_refs"]["full_scf_row_accounting.json"][
        "path"
    ] == str(row_accounting_path)
    assert attachment["artifact_hashes"]["qe_baseline_comparison_index.json"] == (
        source_artifact_refs["qe_baseline_comparison_index.json"]["sha256"]
    )
    assert attachment["artifact_hashes"]["full_scf_row_accounting.json"] == (
        source_artifact_refs["full_scf_row_accounting.json"]["sha256"]
    )


def test_goal_requirement_specs_use_adaptive_five_slot_worker_contract() -> None:
    specs = {spec["requirement_id"]: spec for spec in GOAL_REQUIREMENT_EVIDENCE_SPECS}
    stale_ids = ("done_when_01", "done_when_02", "done_when_03", "done_when_16")

    for requirement_id in stale_ids:
        spec = specs[requirement_id]
        contract_text = " ".join(
            [spec["requirement"], *[str(name) for name in spec["artifact_names"]]]
        ).lower()
        assert "three-run" not in contract_text
        assert "three run" not in contract_text

    assert specs["done_when_01"]["artifact_names"] == (
        ".omx/context/adaptive-five-slot-preflight-<timestamp>.md",
    )
    assert "adaptive five-slot preflight" in specs["done_when_01"]["requirement"].lower()
    assert "process-backed" in specs["done_when_01"]["requirement"].lower()

    assert "each slot handoff" in specs["done_when_02"]["requirement"].lower()
    assert ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/final.md" in specs[
        "done_when_02"
    ]["artifact_names"]

    assert "required active slots" in specs["done_when_03"]["requirement"].lower()
    assert "monitor-classified blocker" in specs["done_when_03"]["requirement"].lower()
    assert ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/monitor.summary" in specs[
        "done_when_03"
    ]["artifact_names"]

    assert specs["done_when_16"]["artifact_names"] == (
        ".omx/context/adaptive-five-slot-preflight-<timestamp>.md",
        ".omx/context/adaptive-five-slot-round-<timestamp>.md",
        ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/final.md",
        ".omx/worker-runs/adaptive-five-slot-<timestamp>/slot*/monitor.summary",
        ".omx/context/adaptive-five-slot-barrier-<timestamp>.md",
    )
    assert "first successful slot" in specs["done_when_16"]["requirement"].lower()
