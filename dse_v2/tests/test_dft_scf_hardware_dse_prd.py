#!/usr/bin/env python3
"""PRD invariant regressions for DFT/QE full-SCF hardware DSE workstreams."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from dse_v2.contracts import (
    ARTIFACT_CATALOG,
    ArtifactDefinition,
    ArtifactRef,
    ContractValidationError,
    validate_artifact_catalog,
)
from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts
from dse_v2.reference_workloads.dft_evidence_ledger import write_dft_candidate_evidence_artifacts
from dse_v2.reference_workloads.qe_mainflow import (
    default_qe_mainflow_workload_suite,
    validate_qe_mainflow_workload_suite,
)
from dse_v2.reporting.complete_dse_claims import (
    ROW_REQUIRED_GATES,
    trusted_l4_row,
    validate_l4_evidence_matrix_claims,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _trusted_refs() -> dict[str, str]:
    return {gate: f"{gate}.json" for gate in ROW_REQUIRED_GATES}


def _step5_seed(run_dir: Path, *, evidence_gap: str = "progress-only; not final completion") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "verdict.json", {
        "schema_version": "dse.verdict.v1",
        "run_id": "wave15-progress",
        "backend": "systemc",
        "trusted_for_final_ranking": False,
        "evidence_gaps": [evidence_gap],
    })
    _write_json(run_dir / "claim_validation.json", {
        "schema_version": "dse.claim_validation.v1",
        "passed": True,
        "validations": [],
        "errors": [],
    })
    _write_json(run_dir / "evidence_requirements.json", {
        "schema_version": "dse.evidence_requirements.v1",
        "requirements": [],
    })
    _write_json(run_dir / "simulation_result.json", {
        "schema_version": "dse.simulation_result.v1",
        "status": "passed",
        "backend": "systemc",
        "metrics": {
            "latency_ms": 10.0,
            "kernel_speedup": 2.5,
            "end_to_end_scf_speedup": 1.2,
            "host_bound_compute_cost_ms": 3.0,
            "transfer_cost_ms": 1.5,
            "synchronization_cost_ms": 0.4,
            "queueing_cost_ms": 0.2,
            "layout_cost_ms": 0.1,
        },
    })


def test_strict_bundle_rejects_missing_assets():
    bundle = default_qe_mainflow_workload_suite()
    broken = copy.deepcopy(bundle)
    broken["cases"][0].pop("qe_command")
    broken["cases"][0].pop("input_hashes")
    broken["cases"][0].pop("expected_outputs")
    broken["cases"][0].pop("baseline_run_provenance")
    broken["cases"][0].pop("tolerance_reference")
    broken.pop("suite_hash", None)

    report = validate_qe_mainflow_workload_suite(broken)

    assert report["valid"] is False
    assert report["release_v1_workload_suite_accepted"] is False
    fields = {error["field"] for error in report["errors"]}
    assert {
        "cases[0].qe_command",
        "cases[0].input_hashes",
        "cases[0].expected_outputs",
        "cases[0].baseline_run_provenance",
        "cases[0].tolerance_reference",
    } <= fields


def test_exploratory_candidate_excluded_from_formal_pareto():
    release_row = trusted_l4_row("release_candidate", "qe_scf", evidence_refs=_trusted_refs())
    exploratory_row = trusted_l4_row("exploratory_candidate", "qe_scf", evidence_refs=_trusted_refs())

    validation = validate_l4_evidence_matrix_claims(
        {
            "candidate_ids": ["release_candidate"],
            "workload_case_ids": ["qe_scf"],
            "rows": [release_row, exploratory_row],
        },
        expected_candidate_ids=["release_candidate"],
        expected_workload_case_ids=["qe_scf"],
    )

    assert validation["deliverable_complete_allowed"] is False
    assert validation["valid"] is False
    assert validation["errors"][0]["message"] == "matrix contains rows outside the frozen release cross-product"
    assert validation["errors"][0]["extra_rows"] == [
        {"candidate_id": "exploratory_candidate", "workload_case_id": "qe_scf"}
    ]


def test_unavailable_tool_log_is_blocker_not_pass():
    row = trusted_l4_row("release_candidate", "qe_scf", evidence_refs=_trusted_refs())
    row["tool_status"] = "unavailable"

    validation = validate_l4_evidence_matrix_claims(
        {
            "candidate_ids": ["release_candidate"],
            "workload_case_ids": ["qe_scf"],
            "rows": [row],
        }
    )

    assert validation["deliverable_complete_allowed"] is False
    assert validation["blockers"][0]["reasons"] == [
        "tool_status_cannot_support_passed_row:unavailable"
    ]


@pytest.fixture()
def dft_eda_evidence(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    out_dir = tmp_path / "ledger"
    write_dft_candidate_evidence_artifacts(out_dir, release_artifact_dir=release_dir)
    return json.loads((out_dir / "eda_all_candidate_evidence.json").read_text(encoding="utf-8"))


def test_dc_only_rejected_for_fpga_claim(dft_eda_evidence):
    required_tools = set(dft_eda_evidence["real_toolchain_policy"]["required_tools"])

    assert {"dc_shell", "vcs", "vivado"} <= required_tools
    assert dft_eda_evidence["real_toolchain_policy"]["completion_eligible_without_real_tool_artifacts"] is False
    assert all("vivado" in record["toolchain_status"]["required_tools"] for record in dft_eda_evidence["candidate_records"])


def test_vivado_only_rejected_for_asic_claim(dft_eda_evidence):
    required_tools = set(dft_eda_evidence["real_toolchain_policy"]["required_tools"])

    assert {"dc_shell", "vcs", "vivado"} <= required_tools
    assert dft_eda_evidence["tool_unavailability_failure_policy"]["completion_eligible"] is False
    assert all("dc_shell" in record["toolchain_status"]["required_tools"] for record in dft_eda_evidence["candidate_records"])


def test_step5_reports_host_transfer_sync_costs(tmp_path):
    run_dir = tmp_path / "step5"
    _step5_seed(run_dir)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    costs = report["full_scf_evaluated_hybrid_costs"]
    assert costs["kernel_speedup"] == 2.5
    assert costs["end_to_end_scf_speedup"] == 1.2
    assert costs["host_bound_compute_cost_ms"] == 3
    assert costs["transfer_cost_ms"] == 1.5
    assert costs["synchronization_cost_ms"] == 0.4
    assert costs["queueing_cost_ms"] == 0.2
    assert costs["layout_cost_ms"] == 0.1
    assert costs["synchronization_queueing_layout_cost_ms"] == pytest.approx(0.7)
    assert costs["required_cost_fields_present"] is True


def test_artifact_ids_propagate_campaign_workload_trial_scope():
    artifact = ArtifactRef(
        artifact_id="artifact-step5-report",
        canonical_name="final_report.json",
        path="runs/campaign/step5/final_report.json",
        schema_id="dse.contract.final_report.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:abc",
        producer_activity_id="activity-step5",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
        trial_id="trial-001",
    )

    artifact.validate_scope("step5")

    missing_trial = ArtifactRef(
        artifact_id="artifact-bad-step5-report",
        canonical_name="final_report.json",
        path="runs/campaign/step5/final_report.json",
        schema_id="dse.contract.final_report.v1",
        schema_version="dse.contracts.v1",
        content_hash="sha256:def",
        producer_activity_id="activity-step5",
        campaign_id="campaign-001",
        workload_run_id="workload-run-001",
    )
    with pytest.raises(ValueError, match="trial_id is required"):
        missing_trial.validate_scope("step5")


def test_step_artifact_ownership_rejects_cross_writes():
    final_report = next(item for item in ARTIFACT_CATALOG if item.canonical_name == "final_report.json")
    cross_write = ArtifactDefinition(
        canonical_name=final_report.canonical_name,
        producer_stage="step3",
        schema_id=final_report.schema_id,
        consumers=final_report.consumers,
        example=final_report.example,
    )

    with pytest.raises(ContractValidationError, match="duplicate artifact name"):
        validate_artifact_catalog([final_report, cross_write])


def test_wave15_trace_reaches_step5_without_completion_claim(tmp_path):
    bundle = default_qe_mainflow_workload_suite()
    bundle_report = validate_qe_mainflow_workload_suite(bundle)
    run_dir = tmp_path / "wave15"
    _step5_seed(run_dir, evidence_gap="Wave 1.5 progress-only trace; not final completion")

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text(encoding="utf-8"))
    assert bundle_report["release_v1_workload_suite_accepted"] is True
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert report["selected_recommendation"]["selection_status"] == "no_trusted_recommendation"
    assert any("Wave 1.5 progress-only" in limitation for limitation in report["limitations"])
    assert campaign_summary["trusted_ranking_count"] == 0
