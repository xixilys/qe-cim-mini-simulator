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
from dse_v2.codesign.dft_hardware_evidence import (
    MAJOR_SCF_KERNEL_IDS,
    build_ic_eda_tool_availability_report,
    build_major_kernel_evidence_matrix,
)
from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts
from dse_v2.reference_workloads.dft_evidence_ledger import write_dft_candidate_evidence_artifacts
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    build_full_scf_evaluated_hybrid_payload,
    write_full_scf_evaluated_hybrid_artifacts,
)
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


def test_step5_cites_full_scf_evaluated_hybrid_bundle_without_claim_upgrade(tmp_path):
    run_dir = tmp_path / "step5_full_scf_hybrid"
    _step5_seed(run_dir, evidence_gap="Wave4 full-SCF evaluated hybrid accounting; not final completion")
    _write_json(run_dir / "simulation_result.json", {
        "schema_version": "dse.simulation_result.v1",
        "status": "passed",
        "backend": "systemc",
        "metrics": {
            "latency_ms": 10.0,
            "kernel_speedup": 4.0,
        },
    })
    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id="release-full-scf-hybrid",
        campaign_id="campaign-prd",
        workload_run_id="workload-prd",
        trial_id="trial-prd",
        accelerated_kernel_costs_s={
            kernel_id: 1.0 for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS
        },
        host_bound_costs_s={
            "io": 1.0,
            "scf_control": 2.0,
            "convergence": 3.0,
            "diagonalization": 4.0,
            "mixing": 5.0,
        },
        overhead_costs_s={
            "transfer": 0.5,
            "synchronization": 0.25,
            "queueing": 0.125,
            "layout": 0.75,
        },
        baseline_scf_time_s=100.0,
    )
    write_full_scf_evaluated_hybrid_artifacts(run_dir, payload)

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text(encoding="utf-8"))
    markdown = (run_dir / paths["final_report_markdown"]).read_text(encoding="utf-8")
    hybrid = report["dft_full_scf_evaluated_hybrid"]
    costs = report["full_scf_evaluated_hybrid_costs"]
    assert hybrid["present"] is True
    assert hybrid["required_artifacts_present"] is True
    assert hybrid["descriptor_validation_passed"] is True
    assert hybrid["completion_claim"] is False
    assert hybrid["prototype_boundary"] == "full_scf_evaluated_hybrid"
    assert hybrid["device_residency"] == "host_orchestrated_hybrid"
    assert hybrid["numerical_correctness_claim_eligible"] is False
    assert hybrid["ppa_claim_eligible"] is False
    assert set(hybrid["schedule_summary"]["accelerated_kernel_ids"]) == set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert costs["source"] == "full_scf_accelerator_descriptor.json"
    assert costs["kernel_speedup"] == 4.0
    assert costs["host_bound_compute_cost_s"] == 15.0
    assert costs["host_bound_compute_cost_ms"] == pytest.approx(15000.0)
    assert costs["transfer_cost_ms"] == pytest.approx(500.0)
    assert costs["synchronization_queueing_layout_cost_ms"] == pytest.approx(1125.0)
    assert costs["end_to_end_scf_speedup"] == pytest.approx(100.0 / 24.625)
    assert costs["required_cost_fields_present"] is True
    assert campaign_summary["dft_full_scf_evaluated_hybrid_summary"]["present"] is True
    assert "DFT Full-SCF Evaluated Hybrid" in markdown
    assert "do not prove full-SCF device residency" in markdown


def test_step5_recovers_full_scf_hybrid_bundle_from_dft_ledger_refs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "step5_full_scf_hybrid_from_ledger"
    _step5_seed(run_dir, evidence_gap="Wave7 ledger-attached full-SCF hybrid; not final completion")
    _write_json(run_dir / "simulation_result.json", {
        "schema_version": "dse.simulation_result.v1",
        "status": "passed",
        "backend": "systemc",
        "metrics": {"latency_ms": 10.0},
    })
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    bundle_dir = Path("external_full_scf_hybrid_bundle")
    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id="ledger-attached-full-scf-hybrid",
        campaign_id="campaign-ledger",
        workload_run_id="workload-ledger",
        trial_id="trial-ledger",
        accelerated_kernel_costs_s={
            kernel_id: 0.75 for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS
        },
        host_bound_costs_s={
            "io": 1.0,
            "scf_control": 2.0,
            "convergence": 3.0,
            "diagonalization": 4.0,
            "mixing": 5.0,
        },
        overhead_costs_s={
            "transfer": 0.25,
            "synchronization": 0.125,
            "queueing": 0.0625,
            "layout": 0.3125,
        },
        baseline_scf_time_s=80.0,
    )
    write_full_scf_evaluated_hybrid_artifacts(bundle_dir, payload)
    ledger_dir = run_dir / "dft_ledger"
    write_dft_candidate_evidence_artifacts(
        ledger_dir,
        release_artifact_dir=release_dir,
        full_scf_hybrid_artifact_dir=bundle_dir,
    )
    dft_artifacts = [
        f"dft_ledger/{name}"
        for name in [
            "per_candidate_evidence_ledger.json",
            "release_report.json",
            "claim_validation_report.json",
            "blocker_report.json",
            "prompt_to_artifact_checklist.json",
            "eda_all_candidate_evidence.json",
        ]
    ]

    paths = write_step5_report_artifacts(run_dir, claims=[], artifact_paths=dft_artifacts)

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text(encoding="utf-8"))
    hybrid = report["dft_full_scf_evaluated_hybrid"]
    costs = report["full_scf_evaluated_hybrid_costs"]
    assert not (run_dir / "full_scf_accelerator_descriptor.json").exists()
    assert hybrid["present"] is True
    assert hybrid["status"] == "ledger_artifact_bundle_present"
    assert hybrid["source"] == "dft_evidence_ledger.full_scf_hybrid_bundle"
    assert hybrid["required_artifacts_present"] is True
    assert hybrid["completion_claim"] is False
    assert hybrid["trusted_final_claim"] is False
    assert hybrid["descriptor_validation_passed"] is True
    assert hybrid["candidate_id"] == "ledger-attached-full-scf-hybrid"
    assert hybrid["campaign_id"] == "campaign-ledger"
    assert hybrid["workload_run_id"] == "workload-ledger"
    assert hybrid["trial_id"] == "trial-ledger"
    assert set(hybrid["schedule_summary"]["accelerated_kernel_ids"]) == set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    descriptor_ref = hybrid["artifacts"]["full_scf_accelerator_descriptor.json"]
    assert descriptor_ref["path"] == str(bundle_dir / "full_scf_accelerator_descriptor.json")
    assert descriptor_ref["resolved_path"] == str(
        (tmp_path / bundle_dir / "full_scf_accelerator_descriptor.json").resolve()
    )
    assert descriptor_ref["source"] == "dft_evidence_ledger.full_scf_hybrid_bundle"
    assert costs["source"] == "full_scf_accelerator_descriptor.json"
    assert costs["kernel_speedup"] == pytest.approx((80.0 - 15.0) / 6.0)
    assert costs["kernel_speedup_source"] == "derived_from_baseline_scf_minus_host_bound_cost"
    assert costs["baseline_accelerated_kernel_cost_s"] == pytest.approx(65.0)
    assert costs["host_bound_compute_cost_s"] == 15.0
    assert costs["host_bound_compute_cost_ms"] == pytest.approx(15000.0)
    assert costs["transfer_cost_ms"] == pytest.approx(250.0)
    assert costs["synchronization_queueing_layout_cost_ms"] == pytest.approx(500.0)
    assert costs["required_cost_fields_present"] is True
    assert campaign_summary["dft_full_scf_evaluated_hybrid_summary"]["source"] == (
        "dft_evidence_ledger.full_scf_hybrid_bundle"
    )
    assert report["dft_evidence_ledger"]["full_scf_hybrid_bundle"]["status"] == "present_hash_valid"
    assert report["selected_recommendation"]["trusted_winner"] is False


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


def test_step5_cites_dft_ledger_hardware_artifacts_without_completion_upgrade(tmp_path):
    run_dir = tmp_path / "step5_with_dft_ledger"
    _step5_seed(run_dir, evidence_gap="Wave2 DFT hardware ledger citation; not full-SCF completion")
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    hardware_dir = tmp_path / "hardware"
    hardware_dir.mkdir()
    tool_report = build_ic_eda_tool_availability_report(
        [
            {"tool": "dc_shell", "returncode": 1, "stdout": "dc_shell version O-2018.06-SP1"},
            {"tool": "vcs", "returncode": 0, "stdout": "VCS version O-2018.09"},
            {"tool": "vivado", "returncode": 0, "stdout": "Vivado v2019.1"},
        ],
        environment="ssh ic-eda",
    )
    matrix = build_major_kernel_evidence_matrix(
        [
            {
                "kernel_id": kernel_id,
                "disposition": "host_bound",
                "host_cost_accounted": True,
            }
            for kernel_id in MAJOR_SCF_KERNEL_IDS
        ],
        candidate_id="step5-dft-ledger-citation-smoke",
    )
    tool_path = hardware_dir / "ic_eda_tool_availability.json"
    matrix_path = hardware_dir / "dft_hardware_evidence_matrix.json"
    _write_json(tool_path, tool_report)
    _write_json(matrix_path, matrix)
    ledger_dir = run_dir / "dft_ledger"
    write_dft_candidate_evidence_artifacts(
        ledger_dir,
        release_artifact_dir=release_dir,
        ic_eda_tool_availability_path=tool_path,
        dft_hardware_evidence_matrix_path=matrix_path,
    )
    dft_artifacts = [
        f"dft_ledger/{name}"
        for name in [
            "per_candidate_evidence_ledger.json",
            "release_report.json",
            "claim_validation_report.json",
            "blocker_report.json",
            "prompt_to_artifact_checklist.json",
            "eda_all_candidate_evidence.json",
        ]
    ]

    paths = write_step5_report_artifacts(run_dir, claims=[], artifact_paths=dft_artifacts)

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text(encoding="utf-8"))
    markdown = (run_dir / paths["final_report_markdown"]).read_text(encoding="utf-8")
    dft_section = report["dft_evidence_ledger"]
    assert dft_section["present"] is True
    assert dft_section["deliverable_complete"] is False
    assert dft_section["trusted_final_claim"] is False
    assert dft_section["eda_summary"]["tool_availability_status"] == "passed"
    assert dft_section["eda_summary"]["major_kernel_matrix_status"] == "passed"
    assert dft_section["eda_summary"]["major_kernel_matrix_trusted"] is True
    assert dft_section["eda_summary"]["hardware_completion_eligible"] is False
    assert dft_section["eda_summary"]["ic_eda_tool_availability"]["path"] == str(tool_path)
    assert dft_section["eda_summary"]["ic_eda_tool_availability_payload_status"] == "passed"
    assert dft_section["eda_summary"]["ic_eda_tool_availability_completion_claim"] == (
        "availability_only_not_kernel_ppa"
    )
    assert dft_section["eda_summary"]["ic_eda_tool_availability_kernel_ppa_evidence"] is False
    assert dft_section["eda_summary"]["ic_eda_tool_availability_hardware_completion_eligible"] is False
    assert dft_section["eda_summary"]["dft_hardware_evidence_matrix"]["path"] == str(matrix_path)
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert campaign_summary["dft_evidence_ledger_summary"]["present"] is True
    assert campaign_summary["dft_evidence_ledger_summary"]["deliverable_complete"] is False
    assert "does not prove full-SCF completion" in markdown


def test_step5_clamps_mislabeled_ic_eda_availability_payload(tmp_path):
    run_dir = tmp_path / "step5_with_bad_ic_eda_payload"
    _step5_seed(run_dir, evidence_gap="Mislabeled IC/EDA availability must not become PPA")
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    hardware_dir = tmp_path / "hardware"
    hardware_dir.mkdir()
    tool_report = build_ic_eda_tool_availability_report(
        [
            {"tool": "dc_shell", "returncode": 1, "stdout": "dc_shell version O-2018.06-SP1"},
            {"tool": "vcs", "returncode": 0, "stdout": "VCS version O-2018.09"},
            {"tool": "vivado", "returncode": 0, "stdout": "Vivado v2019.1"},
        ],
        environment="ssh ic-eda",
    )
    tool_report["completion_claim"] = "kernel_ppa"
    tool_report["kernel_ppa_evidence"] = True
    tool_report["hardware_completion_eligible"] = True
    tool_report["deliverable_complete"] = True
    matrix = build_major_kernel_evidence_matrix(
        [
            {
                "kernel_id": kernel_id,
                "disposition": "host_bound",
                "host_cost_accounted": True,
            }
            for kernel_id in MAJOR_SCF_KERNEL_IDS
        ],
        candidate_id="bad-ic-eda-payload-smoke",
    )
    tool_path = hardware_dir / "ic_eda_tool_availability.json"
    matrix_path = hardware_dir / "dft_hardware_evidence_matrix.json"
    _write_json(tool_path, tool_report)
    _write_json(matrix_path, matrix)
    ledger_dir = run_dir / "dft_ledger"
    write_dft_candidate_evidence_artifacts(
        ledger_dir,
        release_artifact_dir=release_dir,
        ic_eda_tool_availability_path=tool_path,
        dft_hardware_evidence_matrix_path=matrix_path,
    )

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    assert eda_summary["ic_eda_tool_availability_raw_completion_claim"] == "kernel_ppa"
    assert eda_summary["ic_eda_tool_availability_payload_claim_boundary_valid"] is False
    assert eda_summary["ic_eda_tool_availability_payload_claim_upgrade_detected"] is True
    assert eda_summary["ic_eda_tool_availability_completion_claim"] == "availability_only_not_kernel_ppa"
    assert eda_summary["ic_eda_tool_availability_kernel_ppa_evidence"] is False
    assert eda_summary["ic_eda_tool_availability_hardware_completion_eligible"] is False
    assert eda_summary["ic_eda_tool_availability_deliverable_complete"] is False
