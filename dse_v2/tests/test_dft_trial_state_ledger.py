#!/usr/bin/env python3
"""DFT trial-state ledger and Step5/audit integration tests."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_step2_policy import build_dft_hierarchical_funnel_search_report
from dse_v2.reference_workloads.dft_trial_ledger import (
    DFT_TRIAL_STATE_LEDGER_SCHEMA,
    validate_dft_trial_state_ledger,
    write_dft_trial_state_ledger,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _source_artifacts(tmp_path: Path) -> dict[str, Path]:
    search_report = build_dft_hierarchical_funnel_search_report(budget=8)
    search_path = _write_json(tmp_path / "hierarchical_funnel_search_report.json", search_report)
    search_candidate_ids = [str(row["candidate_id"]) for row in search_report["all_records"]]
    first_release_candidate_id = "release-cand-0"
    evidence_ledger = {
        "schema_version": "dse.codesign.per_candidate_evidence_ledger.v1",
        "release_id": "test_release",
        "release_claim_gate": {"deliverable_complete": False},
        "rows": [
            {
                "candidate_id": first_release_candidate_id,
                "claim_eligibility": {"deliverable_complete": False},
                "blocker_status": {"status": "blocked_temporary"},
            }
        ],
    }
    ledger_path = _write_json(tmp_path / "per_candidate_evidence_ledger.json", evidence_ledger)
    binding_map = {
        "schema_version": "dse.dft.candidate_binding_map.v1",
        "status": "passed",
        "workload_suite_id": search_report["workload_suite_id"],
        "release_id": "test_release",
        "search_candidate_count": len(search_candidate_ids),
        "legal_release_candidate_count": len(search_candidate_ids),
        "bound_candidate_count": len(search_candidate_ids),
        "unmatched_candidate_count": 0,
        "unique_release_candidate_count": len(search_candidate_ids),
        "duplicate_release_candidate_ids": [],
        "binding_rows": [
            {
                "search_candidate_id": candidate_id,
                "release_candidate_id": f"release-cand-{index}",
                "binding_status": "matched_by_template_axis_heuristic",
                "confidence": 1.0,
                "template_family": search_report["all_records"][index]["parameters"].get("template_family"),
                "candidate_tier": search_report["all_records"][index]["parameters"].get("candidate_tier"),
                "release_assignments": {"test_axis": "test_value"},
                "evidence_row_present": index == 0,
                "reasons": ["unit_test_binding"],
                "completion_eligible": False,
                "claim_boundary": "unit-test binding is ID provenance only",
            }
            for index, candidate_id in enumerate(search_candidate_ids)
        ],
        "completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": "unit-test binding is ID provenance only",
    }
    binding_path = _write_json(tmp_path / "dft_candidate_binding_map.json", binding_map)
    binding_validation_path = _write_json(
        tmp_path / "dft_candidate_binding_map_validation.json",
        {
            "schema_version": "dse.dft.candidate_binding_map_validation.v1",
            "valid": True,
            "row_count": len(search_candidate_ids),
            "errors": [],
            "claim_boundary": "unit-test binding validation is structural only",
        },
    )
    eda_path = _write_json(
        tmp_path / "eda_all_candidate_evidence.json",
        {
            "schema_version": "dse.dft.eda_all_candidate_evidence.v1",
            "status": "blocked_temporary",
            "hardware_completion_eligible": False,
        },
    )
    final_report_path = _write_json(
        tmp_path / "final_report.json",
        {"schema_version": "dse.final_report.v1", "dft_evidence_ledger": {"present": True}},
    )
    goal_audit_path = _write_json(
        tmp_path / "dft_scf_hardware_goal_completion_audit.json",
        {"schema_version": "dse.dft_scf_hardware.goal_completion_audit.v1", "status": "in_progress"},
    )
    matrix_path = _write_json(
        tmp_path / "dft_hardware_evidence_matrix.json",
        {"schema_version": "dse.dft.hardware_evidence_matrix.v1", "status": "passed", "trusted": True},
    )
    tool_path = _write_json(
        tmp_path / "ic_eda_tool_availability.json",
        {"schema_version": "dse.dft.ic_eda_tool_availability.v1", "status": "passed"},
    )
    return {
        "search": search_path,
        "ledger": ledger_path,
        "binding": binding_path,
        "binding_validation": binding_validation_path,
        "eda": eda_path,
        "final_report": final_report_path,
        "goal_audit": goal_audit_path,
        "matrix": matrix_path,
        "tool": tool_path,
    }


def test_dft_trial_state_ledger_ties_search_evidence_step5_audit(tmp_path: Path) -> None:
    paths = _source_artifacts(tmp_path)
    out_dir = tmp_path / "trial_ledger"

    status = write_dft_trial_state_ledger(
        out_dir,
        hierarchical_search_report_path=paths["search"],
        per_candidate_evidence_ledger_path=paths["ledger"],
        eda_all_candidate_evidence_path=paths["eda"],
        candidate_binding_map_path=paths["binding"],
        final_report_path=paths["final_report"],
        goal_audit_path=paths["goal_audit"],
        dft_hardware_evidence_matrix_path=paths["matrix"],
        ic_eda_tool_availability_path=paths["tool"],
        campaign_id="campaign-test",
        workload_run_id="workload-test",
    )

    assert status["status"] == "passed"
    ledger = json.loads((out_dir / "dft_trial_state_ledger.json").read_text())
    validation = json.loads((out_dir / "dft_trial_state_ledger_validation.json").read_text())
    assert ledger["schema_version"] == DFT_TRIAL_STATE_LEDGER_SCHEMA
    assert validation["valid"] is True
    assert ledger["campaign_id"] == "campaign-test"
    assert ledger["workload_run_id"] == "workload-test"
    assert ledger["candidate_count"] == 8
    assert ledger["deliverable_complete"] is False
    assert ledger["blocked_trial_count"] > 0
    assert (out_dir / "dft_trial_ledger.sqlite").exists()

    first = ledger["trial_rows"][0]
    assert first["campaign_id"] == "campaign-test"
    assert first["workload_run_id"] == "workload-test"
    assert first["registry_trial_id"]
    assert first["search_refs"]["hierarchical_funnel_search_report"]["exists"] is True
    assert first["binding_refs"]["candidate_binding_map"]["exists"] is True
    assert first["evidence_refs"]["per_candidate_evidence_ledger"]["exists"] is True
    assert first["step5_refs"]["final_report"]["exists"] is True
    assert first["goal_audit_refs"]["goal_audit"]["exists"] is True
    assert first["state"] == "blocked"
    assert first["candidate_binding"]["release_candidate_id"] == "release-cand-0"
    assert first["candidate_binding"]["completion_eligible"] is False
    assert first["evidence_binding"]["binding_source"] == "candidate_binding_map"
    assert first["evidence_binding"]["evidence_candidate_id"] == "release-cand-0"
    assert [item["to_state"] for item in first["transition_history"]] == [
        "screened",
        "promoted",
        "scheduled_for_sim",
        "simulated",
        "adjudicated",
        "blocked",
    ]
    assert "eda_all_candidate_evidence.hardware_completion_eligible=false" in first["blocked_reasons"]
    assert all(ref["campaign_row_id"] == ledger["registry_campaign_id"] for ref in first["registry_artifact_refs"])
    assert all(ref["workload_run_row_id"] == ledger["registry_workload_run_id"] for ref in first["registry_artifact_refs"])
    assert all(ref["trial_row_id"] == first["registry_trial_id"] for ref in first["registry_artifact_refs"])


def test_dft_trial_state_ledger_policy_metadata_overrides_legacy_candidate_tier_param(tmp_path: Path) -> None:
    paths = _source_artifacts(tmp_path)
    search_report = json.loads(paths["search"].read_text(encoding="utf-8"))
    for record in search_report["all_records"]:
        record.setdefault("parameters", {})["candidate_tier"] = "exploratory"
    paths["search"].write_text(json.dumps(search_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_dir = tmp_path / "trial_ledger"

    write_dft_trial_state_ledger(
        out_dir,
        hierarchical_search_report_path=paths["search"],
        per_candidate_evidence_ledger_path=paths["ledger"],
        eda_all_candidate_evidence_path=paths["eda"],
        candidate_binding_map_path=paths["binding"],
        final_report_path=paths["final_report"],
        goal_audit_path=paths["goal_audit"],
    )

    ledger = json.loads((out_dir / "dft_trial_state_ledger.json").read_text(encoding="utf-8"))
    formal_metadata_ids = {
        str(record["candidate_id"])
        for record in search_report["all_records"]
        if record.get("policy_metadata", {}).get("formal_pareto_eligible") is True
    }
    release_rows = [
        row for row in ledger["trial_rows"]
        if row["candidate_id"] in formal_metadata_ids
    ]
    assert release_rows
    assert all("candidate_tier" not in row for row in release_rows)
    assert {row["release_policy"]["lane"] for row in release_rows} == {"release"}
    assert {row["release_lane"] for row in release_rows} == {"release"}
    assert all(row["release_policy"]["formal_pareto_allowed"] is True for row in release_rows)
    assert all(row["state"] == "blocked" for row in release_rows)

    with sqlite3.connect(out_dir / "dft_trial_ledger.sqlite") as conn:
        registry_params = [
            json.loads(row[0])
            for row in conn.execute("SELECT params_json FROM trials").fetchall()
        ]
    assert registry_params
    assert all("candidate_tier" not in params for params in registry_params)
    assert all("candidate_tier" not in params.get("parameters", {}) for params in registry_params)


def test_dft_trial_state_machine_rejects_invalid_or_claim_upgrading_transitions(tmp_path: Path) -> None:
    paths = _source_artifacts(tmp_path)
    out_dir = tmp_path / "trial_ledger"
    write_dft_trial_state_ledger(
        out_dir,
        hierarchical_search_report_path=paths["search"],
        per_candidate_evidence_ledger_path=paths["ledger"],
        eda_all_candidate_evidence_path=paths["eda"],
        candidate_binding_map_path=paths["binding"],
        final_report_path=paths["final_report"],
        goal_audit_path=paths["goal_audit"],
    )
    ledger_path = out_dir / "dft_trial_state_ledger.json"
    ledger = json.loads(ledger_path.read_text())

    broken_transition = json.loads(json.dumps(ledger))
    broken_transition["trial_rows"][0]["transition_history"][0]["to_state"] = "simulated"
    assert validate_dft_trial_state_ledger(broken_transition, base_dir=out_dir)["valid"] is False

    broken_claim = json.loads(json.dumps(ledger))
    broken_claim["trial_rows"][0]["state"] = "selected"
    broken_claim["trial_rows"][0]["transition_history"] = [
        {"from_state": "generated", "to_state": "screened"},
        {"from_state": "screened", "to_state": "promoted"},
        {"from_state": "promoted", "to_state": "scheduled_for_sim"},
        {"from_state": "scheduled_for_sim", "to_state": "simulated"},
        {"from_state": "simulated", "to_state": "adjudicated"},
        {"from_state": "adjudicated", "to_state": "reported"},
        {"from_state": "reported", "to_state": "finalist"},
        {"from_state": "finalist", "to_state": "selected"},
    ]
    assert validate_dft_trial_state_ledger(broken_claim, base_dir=out_dir)["valid"] is False

    broken_ref = json.loads(json.dumps(ledger))
    broken_ref["trial_rows"][0]["search_refs"]["hierarchical_funnel_search_report"]["path"] = "missing.json"
    assert validate_dft_trial_state_ledger(broken_ref, base_dir=out_dir)["valid"] is False


def test_build_dft_trial_state_ledger_cli_writes_artifacts(tmp_path: Path) -> None:
    paths = _source_artifacts(tmp_path)
    out_dir = tmp_path / "cli_trial_ledger"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_trial_state_ledger.py",
            "--out",
            str(out_dir),
            "--hierarchical-search-report",
            str(paths["search"]),
            "--per-candidate-evidence-ledger",
            str(paths["ledger"]),
            "--eda-all-candidate-evidence",
            str(paths["eda"]),
            "--candidate-binding-map",
            str(paths["binding"]),
            "--final-report",
            str(paths["final_report"]),
            "--goal-audit",
            str(paths["goal_audit"]),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "dft_trial_state_ledger.json").exists()
    assert json.loads((out_dir / "dft_trial_state_ledger_validation.json").read_text())["valid"] is True


def test_step5_and_goal_audit_include_dft_trial_state_ledger_fail_closed(tmp_path: Path) -> None:
    paths = _source_artifacts(tmp_path)
    run_dir = tmp_path / "step5_run"
    run_dir.mkdir()
    _write_json(run_dir / "verdict.json", {"run_id": "r", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    write_dft_trial_state_ledger(
        run_dir,
        hierarchical_search_report_path=paths["search"],
        per_candidate_evidence_ledger_path=paths["ledger"],
        eda_all_candidate_evidence_path=paths["eda"],
        candidate_binding_map_path=paths["binding"],
        final_report_path=paths["final_report"],
        goal_audit_path=paths["goal_audit"],
    )
    _write_json(run_dir / "dft_candidate_binding_map.json", json.loads(paths["binding"].read_text()))
    _write_json(run_dir / "dft_candidate_binding_map_validation.json", json.loads(paths["binding_validation"].read_text()))

    write_step5_report_artifacts(run_dir)
    report = json.loads((run_dir / "final_report.json").read_text())
    trial_section = report["dft_trial_state_ledger"]
    assert trial_section["present"] is True
    assert trial_section["validation"]["valid"] is True
    assert trial_section["deliverable_complete"] is False
    assert "orchestration and audit evidence only" in trial_section["claim_boundary"]
    binding_section = report["dft_candidate_binding_map"]
    assert binding_section["present"] is True
    assert binding_section["validation"]["valid"] is True
    assert binding_section["deliverable_complete"] is False

    audit = build_dft_scf_hardware_goal_completion_audit(run_dir=run_dir)
    requirements = {item["requirement"]: item for item in audit["prompt_to_artifact_checklist"]}
    trial_requirement = requirements["DFT trial-state ledger is Step5-visible and fail-closed"]
    assert trial_requirement["status"] == "passed"
    binding_requirement = requirements["DFT candidate binding map is Step5-visible and fail-closed"]
    assert binding_requirement["status"] == "passed"
    assert audit["summary"]["dft_trial_state_ledger_present"] is True
    assert audit["summary"]["dft_candidate_binding_map_present"] is True
    assert audit["status"] == "in_progress"
