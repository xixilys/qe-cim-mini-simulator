#!/usr/bin/env python3
"""Contract tests for Step3/Step4/Step5 artifact ownership."""

from __future__ import annotations

import inspect
import json

import pytest

from dse_v2.contracts import CONTRACT_VERSION, SCHEMA_REGISTRY, validate_instance
from dse_v2.core.workload import create_sparse_spmv_graph, package_from_graph
from dse_v2.evidence import step3_workflow
from dse_v2.evidence.step4_adjudication import run_step4_evidence_adjudication
from dse_v2.mapping.step2_workflow import run_step2_architecture_mapping_workflow
from dse_v2.reporting.final_report import write_step5_report_artifacts


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_step3_step4_step5_canonical_artifact_ownership(tmp_path):
    graph = create_sparse_spmv_graph("ownership_split")
    package = package_from_graph(graph, workload_family="sparse_la", importer_id="generic_json")
    step2_dir = tmp_path / "step2"
    step3_dir = tmp_path / "step3"

    run_step2_architecture_mapping_workflow(package, output_dir=step2_dir)
    step3 = step3_workflow.run_step3_simulation_evidence_workflow(step2_dir, output_dir=step3_dir, timeout=30)

    assert step3.status == "simulation_completed"
    assert (step3_dir / "simulation_request.json").exists()
    assert (step3_dir / "simulation_result.json").exists()
    assert (step3_dir / "step3_status.json").exists()
    for forbidden in [
        "manifest.json",
        "artifact_manifest.json",
        "verdict.json",
        "evidence_requirements.json",
        "claim_validation.json",
        "final_report.json",
        "final_report.md",
        "campaign_summary.json",
        "trusted_ranking.json",
        "pareto_frontier.json",
        "numerical_validation.json",
    ]:
        assert not (step3_dir / forbidden).exists(), forbidden
    with pytest.raises(ValueError, match="requires Step4 adjudication artifacts"):
        write_step5_report_artifacts(step3_dir)

    step4 = run_step4_evidence_adjudication(step3_dir)
    assert step4.status == "adjudicated"
    for step4_artifact in [
        "manifest.json",
        "artifact_manifest.json",
        "provenance.json",
        "verdict.json",
        "evidence_requirements.json",
        "claim_validation.json",
        "simulator_consistency_check.json",
        "timing_model_calibration.json",
        "calibration_record.json",
        "feedback_update.json",
    ]:
        assert (step3_dir / step4_artifact).exists(), step4_artifact
    assert not (step3_dir / "final_report.json").exists()
    assert _load(step3_dir / "claim_validation.json")["passed"] is True
    calibration_record = _load(step3_dir / "calibration_record.json")
    feedback_update = _load(step3_dir / "feedback_update.json")
    validate_instance(calibration_record, SCHEMA_REGISTRY["dse.contract.calibration_record.v1"])
    validate_instance(feedback_update, SCHEMA_REGISTRY["dse.contract.feedback_update.v1"])
    assert calibration_record["schema_version"] == CONTRACT_VERSION
    assert feedback_update["schema_version"] == CONTRACT_VERSION
    for artifact in ["simulation_result.json", "simulator_consistency_check.json"]:
        assert artifact in calibration_record["source_artifact_hashes"]
        assert calibration_record["source_artifact_hashes"][artifact].startswith("sha256:")
    assert "simulation_result.json" in feedback_update["source_artifact_hashes"]
    assert feedback_update["updates"][0]["target"] == "promotion_policy"

    step5_paths = write_step5_report_artifacts(step3_dir)
    assert step5_paths["final_report_json"] == "final_report.json"
    for step5_artifact in [
        "final_report.json",
        "final_report.md",
        "campaign_summary.json",
        "trusted_ranking.json",
        "pareto_frontier.json",
    ]:
        assert (step3_dir / step5_artifact).exists(), step5_artifact
    report = _load(step3_dir / "final_report.json")
    assert report["run_metadata"]["verdict"] == "verdict.json"
    assert report["run_metadata"]["source_step4_claim_validation"] == "claim_validation.json"
    assert report["run_metadata"]["source_step4_claim_validation_passed"] is True
    assert report["claim_validation"]["passed"] is True


def test_step5_report_does_not_upgrade_unpassed_step4_claim_validation(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "verdict.json").write_text(
        json.dumps(
            {
                "run_id": "step5-fail-closed-source-claim-validation",
                "backend": "step5_contract",
                "trusted_for_final_ranking": False,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "claim_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "dse.claim_validation.v1",
                "passed": False,
                "fail_closed_reason": "Step4 gate intentionally blocked",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "evidence_requirements.json").write_text(
        json.dumps({"schema_version": "dse.evidence_requirements.v1", "requirements": []}),
        encoding="utf-8",
    )

    paths = write_step5_report_artifacts(run_dir, claims=[])
    report = _load(run_dir / paths["final_report_json"])

    assert report["run_metadata"]["source_step4_claim_validation_passed"] is False
    assert report["claim_validation"]["passed"] is False
    assert report["claim_validation"]["source_step4_claim_validation_passed"] is False
    assert report["claim_validation"]["fail_closed_reason"].startswith(
        "Step5 final_report.json cannot upgrade"
    )
    assert any(
        "Step4 gate intentionally blocked" in error
        for error in report["claim_validation"]["errors"]
    )


def test_step3_workflow_does_not_call_final_report_writer_directly():
    source = inspect.getsource(step3_workflow)
    assert "write_final_report_artifacts(" not in source
    assert "write_step5_report_artifacts(" not in source
