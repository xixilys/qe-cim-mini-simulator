#!/usr/bin/env python3
"""DFT hardware closure release-gate rollup tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_hardware_closure_release_gate import (
    DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA,
    build_dft_hardware_closure_release_gate,
    validate_dft_hardware_closure_release_gate,
    write_dft_hardware_closure_release_gate,
)
from dse_v2.reporting.final_report import write_step5_report_artifacts
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


STAGES = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
]


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _stage_row(stage_id: str, *, passed: bool = False, failed: bool = False) -> dict:
    if failed:
        status = "failed_parsed_result"
        adjudication_result = "failed_stage_gate"
        blocker_id = "parsed_result_failed"
        parsed_verdict = "failed"
    elif passed:
        status = "stage_gate_passed_pending_unit_closure"
        adjudication_result = "passed_stage_gate"
        blocker_id = None
        parsed_verdict = "passed"
    else:
        status = "blocked_missing_parsed_result"
        adjudication_result = "blocked_stage_gate"
        blocker_id = "parsed_result_missing"
        parsed_verdict = None
    return {
        "unit_id": "cand-a:fft_ifft_ffft",
        "candidate_id": "cand-a",
        "kernel_id": "fft_ifft_ffft",
        "kernel_name": "FFT / iFFT / fFFT",
        "stage_id": stage_id,
        "parsed_result_present": passed or failed,
        "parsed_result_schema_valid": passed or failed,
        "parsed_verdict": parsed_verdict,
        "stage_gate_passed": passed,
        "status": status,
        "blocker_id": blocker_id,
        "adjudication_result": adjudication_result,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
    }


def _gate_adjudication(path: Path, *, all_passed: bool = False, one_failed: bool = False) -> Path:
    stage_rows = []
    for index, stage_id in enumerate(STAGES):
        stage_rows.append(_stage_row(stage_id, passed=all_passed, failed=one_failed and index == 0))
    passed_count = sum(1 for row in stage_rows if row["stage_gate_passed"])
    failed_count = sum(1 for row in stage_rows if row["adjudication_result"] == "failed_stage_gate")
    blocked_count = sum(1 for row in stage_rows if row["adjudication_result"] == "blocked_stage_gate")
    unit_passed = passed_count == len(STAGES)
    if failed_count:
        status = "failed_stage_gate"
        adjudication_result = "failed_unit_gate"
    elif unit_passed:
        status = "all_stage_gates_passed_pending_release_claim"
        adjudication_result = "passed_unit_gate_pending_release_claim"
    else:
        status = "blocked_incomplete_stage_gates"
        adjudication_result = "blocked_unit_gate"
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "status": "all_unit_stage_gates_passed_pending_release_claim"
            if unit_passed
            else "failed_hard_gate"
            if failed_count
            else "blocked_incomplete_hard_gate_evidence",
            "release_id": "release-release-gate",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "packet_count": 1,
            "unit_count": 1,
            "stage_count": len(STAGES),
            "stage_gate_passed_count": passed_count,
            "blocked_stage_count": blocked_count,
            "failed_stage_count": failed_count,
            "unit_gate_passed_count": 1 if unit_passed else 0,
            "blocked_unit_count": 0 if unit_passed or failed_count else 1,
            "failed_unit_count": 1 if failed_count else 0,
            "adjudication_result": "all_stage_gates_passed_pending_release_claim"
            if unit_passed
            else "failed_hard_gate"
            if failed_count
            else "blocked_incomplete_hard_gate_evidence",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "unit_rows": [
                {
                    "unit_id": "cand-a:fft_ifft_ffft",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "kernel_name": "FFT / iFFT / fFFT",
                    "stage_count": len(STAGES),
                    "stage_gate_passed_count": passed_count,
                    "blocked_stage_count": blocked_count,
                    "failed_stage_count": failed_count,
                    "unit_gate_passed": unit_passed,
                    "status": status,
                    "adjudication_result": adjudication_result,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                    "stage_rows": stage_rows,
                }
            ],
        },
    )


def _gate_adjudication_matrix(path: Path, *, candidate_count: int = 36, major_kernel_count: int = 8) -> Path:
    kernel_ids = [
        "fft_ifft_ffft",
        "transpose_layout_conversion",
        "hpsi_local_potential",
        "kinetic_add",
        "nonlocal_projector",
        "complex_gemm_gemv_tile",
        "reduction_dot_tree",
        "dma_hbm_movement_engine",
    ][:major_kernel_count]
    unit_rows = []
    for candidate_index in range(candidate_count):
        candidate_id = f"cand-{candidate_index:02d}"
        for kernel_id in kernel_ids:
            unit_rows.append(
                {
                    "unit_id": f"{candidate_id}:{kernel_id}",
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "kernel_name": kernel_id,
                    "stage_count": len(STAGES),
                    "stage_gate_passed_count": len(STAGES),
                    "blocked_stage_count": 0,
                    "failed_stage_count": 0,
                    "unit_gate_passed": True,
                    "status": "all_stage_gates_passed_pending_release_claim",
                    "adjudication_result": "passed_unit_gate_pending_release_claim",
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                }
            )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "status": "all_unit_stage_gates_passed_pending_release_claim",
            "release_id": "release-release-gate",
            "candidate_count": candidate_count,
            "major_kernel_count": major_kernel_count,
            "packet_count": 1,
            "unit_count": len(unit_rows),
            "stage_count": len(unit_rows) * len(STAGES),
            "stage_gate_passed_count": len(unit_rows) * len(STAGES),
            "blocked_stage_count": 0,
            "failed_stage_count": 0,
            "unit_gate_passed_count": len(unit_rows),
            "blocked_unit_count": 0,
            "failed_unit_count": 0,
            "adjudication_result": "all_stage_gates_passed_pending_release_claim",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "unit_rows": unit_rows,
        },
    )


def _per_candidate_evidence_ledger_with_routing_blocker(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "dse.codesign.per_candidate_evidence_ledger.v1",
            "legal_candidate_count": 1,
            "legal_candidate_ids": ["cand-a"],
            "rows": [
                {
                    "candidate_id": "cand-a",
                    "evaluation_policy_routing": {
                        "schema_version": "dse.dft.ledger_evaluation_policy_routing.v1",
                        "status": "blocked_for_claim_eligibility",
                        "routing_recorded": True,
                        "routing_compatible": False,
                        "evaluation_policy_id": "policy-route-a",
                        "evaluation_policy_assignments": {},
                        "promotion_requirements": ["release_candidate_only"],
                        "routing_blockers": [
                            {
                                "rule_id": "evaluation_policy_routing_missing",
                                "reason": "routing metadata is intentionally blocked for claim eligibility",
                            }
                        ],
                        "routing_blocker_count": 1,
                        "affects_design_legality": False,
                        "affects_design_score": False,
                        "claim_eligibility_blocker": True,
                        "claim_boundary": (
                            "Evaluation routing schedules or blocks evidence/promotion work. "
                            "Routing blockers affect release/candidate claim eligibility only; "
                            "they do not change design legality, design score, or stable design identity."
                        ),
                    },
                }
            ],
        },
    )


def test_release_gate_blocks_incomplete_unit_gates_fail_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json")

    status = write_dft_hardware_closure_release_gate(run_dir, gate_adjudication_path=gate_path)

    assert status["status"] == "passed"
    release = json.loads((run_dir / "dft_hardware_closure_release_gate.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_closure_release_gate_validation.json").read_text())
    assert release["schema_version"] == DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA
    assert release["status"] == "blocked_incomplete_hardware_release_gate"
    assert release["release_gate_result"] == "blocked_incomplete_hardware_release_gate"
    assert release["unit_gate_passed_count"] == 0
    assert release["blocked_unit_count"] == 1
    assert release["failed_unit_count"] == 0
    assert release["candidate_gate_passed_count"] == 0
    assert release["blocked_candidate_count"] == 1
    assert release["unit_count_semantics"] == "candidate_count*major_kernel_count"
    assert release["unit_stage_blockers"][0]["blocker_id"] == "parsed_result_missing"
    assert len(release["unit_stage_blockers"]) == len(STAGES)
    assert release["candidate_kernel_blockers"][0]["candidate_id"] == "cand-a"
    assert release["candidate_kernel_blockers"][0]["kernel_id"] == "fft_ifft_ffft"
    assert release["hardware_eligibility_blockers"][0]["blocker_id"] == "candidate_has_blocked_unit_gates"
    assert {
        item["blocker_id"] for item in release["deliverable_completion_blockers"]
    } == {
        "release_gate_cannot_mark_deliverable_complete",
        "hardware_completion_not_eligible",
    }
    assert release["hardware_completion_eligible"] is False
    assert release["deliverable_complete"] is False
    assert validation["valid"] is True


def test_release_gate_all_unit_gates_pass_sets_hardware_eligible_not_deliverable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json", all_passed=True)

    release = build_dft_hardware_closure_release_gate(gate_adjudication_path=gate_path)

    assert release["status"] == "hardware_release_gate_passed_pending_deliverable_claim"
    assert release["release_gate_result"] == "hardware_completion_eligible_pending_deliverable_claim"
    assert release["unit_gate_passed_count"] == 1
    assert release["blocked_unit_count"] == 0
    assert release["failed_unit_count"] == 0
    assert release["candidate_gate_passed_count"] == 1
    assert release["hardware_completion_eligible"] is True
    assert release["deliverable_complete"] is False
    assert release["hardware_eligibility_blockers"] == []
    assert release["candidate_kernel_blockers"] == []
    assert release["unit_stage_blockers"] == []
    assert release["deliverable_completion_blockers"][0]["blocker_id"] == (
        "release_gate_cannot_mark_deliverable_complete"
    )
    assert release["candidate_rows"][0]["candidate_hardware_gate_passed"] is True
    assert release["candidate_rows"][0]["deliverable_complete"] is False


def test_release_gate_routing_blockers_affect_claim_eligibility_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json", all_passed=True)
    ledger_path = _per_candidate_evidence_ledger_with_routing_blocker(
        run_dir / "per_candidate_evidence_ledger.json"
    )

    release = build_dft_hardware_closure_release_gate(
        gate_adjudication_path=gate_path,
        per_candidate_evidence_ledger_path=ledger_path,
    )

    assert release["status"] == "blocked_incomplete_hardware_release_gate"
    assert release["release_gate_result"] == "blocked_incomplete_hardware_release_gate"
    candidate = release["candidate_rows"][0]
    routing = candidate["evaluation_policy_routing"]
    assert candidate["candidate_hardware_gate_passed"] is True
    assert candidate["candidate_claim_eligible"] is False
    assert candidate["routing_affects_design_legality"] is False
    assert routing["routing_compatible"] is False
    assert routing["affects_design_legality"] is False
    assert routing["claim_eligibility_blocker"] is True
    assert release["evaluation_policy_routing_summary"]["routing_blocked_candidate_ids"] == ["cand-a"]
    assert release["evaluation_policy_routing_summary"]["routing_blocked_candidate_count"] == 1
    assert any(
        blocker["blocker_id"] == "candidate_evaluation_policy_routing_blocked"
        for blocker in release["hardware_eligibility_blockers"]
    )
    assert release["hardware_completion_eligible"] is False
    assert release["deliverable_complete"] is False
    assert validate_dft_hardware_closure_release_gate(release)["valid"] is True

    status = write_dft_hardware_closure_release_gate(
        run_dir,
        gate_adjudication_path=gate_path,
        per_candidate_evidence_ledger_path=ledger_path,
    )
    assert status["routing_blocker_count"] == 1
    assert status["routing_blocked_candidate_ids"] == ["cand-a"]
    _write_json(run_dir / "verdict.json", {"run_id": "routing-release-gate", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])
    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    section = report["dft_hardware_closure_release_gate"]
    assert section["routing_blocker_count"] == 1
    assert section["routing_blocked_candidate_ids"] == ["cand-a"]
    assert section["evaluation_policy_routing_summary"]["affects_design_legality"] is False


def test_release_gate_rejects_partial_all_pass_subset_when_expected_matrix_is_larger(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json", all_passed=True)
    gate = json.loads(gate_path.read_text())
    gate["candidate_count"] = 36
    gate["major_kernel_count"] = 8
    gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    release = build_dft_hardware_closure_release_gate(gate_adjudication_path=gate_path)
    validation = validate_dft_hardware_closure_release_gate(release)

    assert release["status"] == "blocked_incomplete_hardware_release_gate"
    assert release["expected_unit_count"] == 288
    assert release["actual_unit_count"] == 1
    assert release["unit_count_semantics"] == "candidate_count*major_kernel_count"
    assert release["unit_count_complete"] is False
    assert release["candidate_count_complete"] is False
    assert release["per_candidate_kernel_coverage_complete"] is False
    assert release["candidate_rows"][0]["missing_kernel_count"] == 7
    assert set(release["candidate_rows"][0]["missing_kernel_ids"]) == {
        "transpose_layout_conversion",
        "hpsi_local_potential",
        "kinetic_add",
        "nonlocal_projector",
        "complex_gemm_gemv_tile",
        "reduction_dot_tree",
        "dma_hbm_movement_engine",
    }
    blocker_ids = {item["blocker_id"] for item in release["hardware_eligibility_blockers"]}
    assert "candidate_count_incomplete" in blocker_ids
    assert "unit_count_incomplete" in blocker_ids
    assert "candidate_kernel_coverage_incomplete" in blocker_ids
    assert release["hardware_completion_eligible"] is False
    assert validation["valid"] is True


def test_release_gate_all288_style_matrix_sets_hardware_eligible_not_deliverable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication_matrix(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        candidate_count=36,
        major_kernel_count=8,
    )

    release = build_dft_hardware_closure_release_gate(gate_adjudication_path=gate_path)
    validation = validate_dft_hardware_closure_release_gate(release)

    assert release["expected_unit_count"] == 288
    assert release["unit_count"] == 288
    assert release["stage_count"] == 1440
    assert release["unit_gate_passed_count"] == 288
    assert release["candidate_gate_passed_count"] == 36
    assert release["candidate_count_complete"] is True
    assert release["unit_count_complete"] is True
    assert release["per_candidate_kernel_coverage_complete"] is True
    assert release["hardware_completion_eligible"] is True
    assert release["deliverable_complete"] is False
    assert validation["valid"] is True


def test_release_gate_failed_unit_fails_release_but_not_deliverable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json", one_failed=True)

    release = build_dft_hardware_closure_release_gate(gate_adjudication_path=gate_path)

    assert release["status"] == "failed_hardware_release_gate"
    assert release["release_gate_result"] == "failed_hardware_release_gate"
    assert release["failed_unit_count"] == 1
    assert release["failed_candidate_count"] == 1
    assert release["unit_stage_blockers"][0]["blocker_id"] == "parsed_result_failed"
    assert release["candidate_kernel_blockers"][0]["non_passing_stage_reasons"][0]["stage_id"] == (
        "golden_correctness"
    )
    assert release["hardware_eligibility_blockers"][0]["blocker_id"] == "candidate_has_failed_unit_gate"
    assert release["hardware_completion_eligible"] is False
    assert release["deliverable_complete"] is False


def test_release_gate_validator_rejects_fake_hardware_eligible_and_deliverable_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json")
    release = build_dft_hardware_closure_release_gate(gate_adjudication_path=gate_path)

    tampered = json.loads(json.dumps(release))
    tampered["hardware_completion_eligible"] = True
    tampered["deliverable_complete"] = True
    tampered["unit_gate_passed_count"] = 1
    tampered["candidate_gate_passed_count"] = 1
    tampered["unit_rows"][0]["hardware_completion_eligible"] = True
    tampered["candidate_rows"][0]["candidate_hardware_gate_passed"] = True
    validation = validate_dft_hardware_closure_release_gate(tampered)

    assert validation["valid"] is False
    fields = {err["field"] for err in validation["errors"]}
    assert "hardware_completion_eligible" in fields
    assert "deliverable_complete" in fields
    assert "unit_gate_passed_count" in fields
    assert "candidate_rows[0].candidate_hardware_gate_passed" in fields


def test_release_gate_cli_step5_and_goal_audit_visibility(tmp_path: Path) -> None:
    run_dir = tmp_path / "step5"
    gate_path = _gate_adjudication(run_dir / "dft_hardware_closure_gate_adjudication.json")
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_closure_release_gate.py",
            "--out",
            str(run_dir),
            "--gate-adjudication",
            str(gate_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr

    _write_json(run_dir / "verdict.json", {"run_id": "release-gate-step5", "backend": "systemc", "trusted_for_final_ranking": False})
    _write_json(run_dir / "claim_validation.json", {"schema_version": "dse.claim_validation.v1", "passed": True})
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1", "requirements": []})
    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text())
    campaign_summary = json.loads((run_dir / paths["campaign_summary"]).read_text())
    markdown = (run_dir / paths["final_report_markdown"]).read_text()
    section = report["dft_hardware_closure_release_gate"]
    assert section["present"] is True
    assert section["status"] == "fail_closed_hardware_closure_release_gate_present"
    assert section["unit_gate_passed_count"] == 0
    assert section["blocked_unit_count"] == 1
    assert section["candidate_gate_passed_count"] == 0
    assert section["hardware_completion_eligible"] is False
    assert section["deliverable_complete"] is False
    assert section["trusted_final_claim"] is False
    assert section["completion_claim"] == "blocked"
    assert campaign_summary["dft_hardware_closure_release_gate_summary"]["present"] is True
    assert "DFT Hardware Closure Release Gate" in markdown

    audit = build_dft_scf_hardware_goal_completion_audit(
        run_dir=run_dir,
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    requirements = {item["requirement"]: item["status"] for item in audit["prompt_to_artifact_checklist"]}
    assert requirements["DFT hardware closure release gate is Step5-visible and fail-closed"] == "passed"
    assert audit["summary"]["dft_hardware_closure_release_gate_present"] is True
    assert audit["summary"]["release_gate_detail_source"].endswith("dft_hardware_closure_release_gate.json")
    assert audit["summary"]["candidate_kernel_blocker_count"] == 1
    assert audit["summary"]["unit_stage_blocker_count"] == len(STAGES)
    assert audit["hardware_eligibility_blockers"][0]["blocker_id"] == "candidate_has_blocked_unit_gates"
