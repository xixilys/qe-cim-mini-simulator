#!/usr/bin/env python3
"""Tests for fail-closed DFT L4/gem5 goal binding artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.codesign.dft_l4_goal_binding import (
    build_dft_l4_goal_binding,
    validate_dft_l4_goal_binding,
    write_dft_l4_goal_binding,
)
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_l4_root(root: Path, *, candidates=None, workloads=None) -> Path:
    l4 = root / "l4"
    candidates = list(candidates or ["cdse_a", "cdse_b"])
    workloads = list(workloads or ["qe_si_scf_small_v1", "qe_si_nscf_bandgrid_v1"])
    rows = []
    for candidate in candidates:
        for workload in workloads:
            rows.append({
                "schema_version": "dse.codesign.l4_evidence_matrix_row.v1",
                "candidate_id": candidate,
                "workload_case_id": workload,
                "row_status": "passed",
                "blockers": [],
            })
            _write_json(
                l4 / "rows" / candidate / workload / "l4_gem5" / "gem5_l4_proof.json",
                {"passed": True, "checks": {"descriptor_read_verified": True}},
            )
    _write_json(
        l4 / "l4_evidence_matrix.json",
        {
            "schema_version": "dse.codesign.l4_evidence_matrix.v1",
            "coverage_status": "passed",
            "row_count": len(rows),
            "expected_row_count": len(rows),
            "blocked_row_count": 0,
            "deliverable_complete_eligible": True,
            "legal_candidate_ids": candidates,
            "workload_case_ids": workloads,
            "matrix_hash": "hash-l4",
            "rows": rows,
        },
    )
    _write_json(
        l4 / "complete_dse_full_l4_evidence_report.json",
        {
            "schema_version": "dse.codesign.complete_dse_full_l4_report.v1",
            "status": "deliverable_complete",
            "row_count": len(rows),
            "expected_row_count": len(rows),
            "claims": {"deliverable_complete": True},
        },
    )
    _write_json(
        l4 / "evidence_rows.json",
        {
            "schema_version": "dse.codesign.complete_dse_full_l4_evidence_rows.v1",
            "row_count": len(rows),
            "expected_row_count": len(rows),
            "rows": rows,
        },
    )
    _write_json(
        l4 / "gem5_preflight.json",
        {
            "schema_version": "dse.codesign.gem5_preflight.v1",
            "blockers": [],
            "gem5_binary_exists": True,
            "driver_binary_exists": True,
            "gem5_config_exists": True,
        },
    )
    return l4


def _make_step5(root: Path) -> Path:
    step5 = root / "step5"
    _write_json(
        step5 / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "candidate_rows": [
                {"candidate_id": "cand_1"},
                {"candidate_id": "cand_2"},
            ],
        },
    )
    return step5


def test_l4_goal_binding_is_visible_but_unbound_without_crosswalk(tmp_path):
    l4 = _make_l4_root(tmp_path)
    step5 = _make_step5(tmp_path)

    payload = build_dft_l4_goal_binding(l4_root=l4, step5_run=step5)
    validation = validate_dft_l4_goal_binding(payload)

    assert validation["valid"] is True
    assert payload["l4_software_visible_proof_present"] is True
    assert payload["current_goal_binding"]["current_goal_l4_bound"] is False
    assert payload["status"] == "blocked_l4_visible_but_identity_or_workload_unbound"
    assert "candidate_identity_crosswalk_missing_or_incomplete" in payload["blockers"]
    assert payload["deliverable_complete"] is False


def test_l4_goal_binding_rejects_weak_partial_explicit_crosswalk_without_completion_claim(tmp_path):
    l4 = _make_l4_root(tmp_path)
    step5 = _make_step5(tmp_path)
    candidate_crosswalk = tmp_path / "candidate_crosswalk.json"
    workload_crosswalk = tmp_path / "workload_crosswalk.json"
    _write_json(candidate_crosswalk, {"candidate_crosswalk": {"cand_1": "cdse_a", "cand_2": "cdse_b"}})
    _write_json(workload_crosswalk, {
        "workload_crosswalk": {
            "small_multi_k_scf": "qe_si_scf_small_v1",
            "metal_smearing_scf": "qe_si_nscf_bandgrid_v1",
        }
    })

    status = write_dft_l4_goal_binding(
        tmp_path / "out",
        l4_root=l4,
        step5_run=step5,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
        candidate_mapping_policy="explicit_crosswalk",
        workload_mapping_policy="explicit_crosswalk",
    )
    payload = json.loads((tmp_path / "out" / "dft_l4_goal_binding.json").read_text())

    assert status["status"] == "passed"
    assert payload["status"] == "blocked_l4_visible_but_identity_or_workload_unbound"
    assert payload["final_closure_eligible"] is False
    assert payload["current_goal_binding"]["candidate_identity_binding_explicit"] is False
    assert payload["current_goal_binding"]["workload_identity_binding_explicit"] is False
    assert payload["deliverable_complete"] is False


def test_l4_goal_binding_can_validate_exact_structured_current_goal_crosswalk(tmp_path):
    workloads = [f"l4_{class_id}" for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES]
    l4 = _make_l4_root(tmp_path, workloads=workloads)
    step5 = _make_step5(tmp_path)
    candidate_crosswalk = tmp_path / "candidate_crosswalk.json"
    workload_crosswalk = tmp_path / "workload_crosswalk.json"
    _write_json(
        candidate_crosswalk,
        {
            "candidate_crosswalk": {
                "cand_1": {
                    "l4_candidate_id": "cdse_a",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                    "match_basis": "test exact current-goal candidate identity",
                },
                "cand_2": {
                    "l4_candidate_id": "cdse_b",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                    "match_basis": "test exact current-goal candidate identity",
                },
            }
        },
    )
    _write_json(
        workload_crosswalk,
        {
            "workload_crosswalk": {
                class_id: {
                    "l4_workload_case_ids": [f"l4_{class_id}"],
                    "equivalence_scope": "explicit_current_goal_l4_workload",
                    "confidence": 1.0,
                    "match_basis": "test exact strict-SCF workload identity",
                }
                for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES
            }
        },
    )

    status = write_dft_l4_goal_binding(
        tmp_path / "out",
        l4_root=l4,
        step5_run=step5,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
        candidate_mapping_policy="explicit_crosswalk",
        workload_mapping_policy="explicit_crosswalk",
    )
    payload = json.loads((tmp_path / "out" / "dft_l4_goal_binding.json").read_text())

    assert status["status"] == "passed"
    assert payload["status"] == "passed_current_goal_l4_bound"
    assert payload["current_goal_binding"]["candidate_keys_exact"] is True
    assert payload["current_goal_binding"]["mapped_l4_candidates_unique"] is True
    assert payload["current_goal_binding"]["workload_keys_exact"] is True
    assert payload["final_closure_eligible"] is True
    assert payload["deliverable_complete"] is False


def test_l4_goal_binding_accepts_real_l4_transport_when_qe_correctness_still_blocks_report(tmp_path):
    workloads = [f"l4_{class_id}" for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES]
    l4 = _make_l4_root(tmp_path, workloads=workloads)
    matrix = json.loads((l4 / "l4_evidence_matrix.json").read_text(encoding="utf-8"))
    matrix["coverage_status"] = "blocked"
    matrix["blocked_row_count"] = matrix["row_count"]
    matrix["deliverable_complete_eligible"] = False
    for row in matrix["rows"]:
        row["row_status"] = "blocked"
        row["blockers"] = ["missing_pure_software_qe_baseline"]
    _write_json(l4 / "l4_evidence_matrix.json", matrix)
    report = json.loads((l4 / "complete_dse_full_l4_evidence_report.json").read_text(encoding="utf-8"))
    report["status"] = "blocked_or_partial"
    report["claims"] = {"deliverable_complete": False, "mvp_partial": True}
    _write_json(l4 / "complete_dse_full_l4_evidence_report.json", report)
    step5 = _make_step5(tmp_path)
    candidate_crosswalk = tmp_path / "candidate_crosswalk.json"
    workload_crosswalk = tmp_path / "workload_crosswalk.json"
    _write_json(
        candidate_crosswalk,
        {
            "candidate_crosswalk": {
                "cand_1": {
                    "l4_candidate_id": "cdse_a",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                },
                "cand_2": {
                    "l4_candidate_id": "cdse_b",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                },
            }
        },
    )
    _write_json(
        workload_crosswalk,
        {
            "workload_crosswalk": {
                class_id: {
                    "l4_workload_case_ids": [f"l4_{class_id}"],
                    "equivalence_scope": "explicit_current_goal_l4_workload",
                    "confidence": 1.0,
                }
                for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES
            }
        },
    )

    payload = build_dft_l4_goal_binding(
        l4_root=l4,
        step5_run=step5,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
        candidate_mapping_policy="explicit_crosswalk",
        workload_mapping_policy="explicit_crosswalk",
    )
    validation = validate_dft_l4_goal_binding(payload)

    assert validation["valid"] is True
    assert payload["l4_software_visible_proof_present"] is True
    assert payload["current_goal_binding"]["current_goal_l4_bound"] is True
    assert payload["row_level_proofs"]["passed_gem5_l4_proof_count"] == matrix["row_count"]
    assert payload["deliverable_complete"] is False
    assert "l4_report_not_deliverable_complete_for_its_scope" in payload["non_l4_deliverable_blockers"]
    assert "l4_matrix_not_complete_for_its_scope" not in payload["blockers"]


def test_l4_goal_binding_rejects_many_to_one_candidate_crosswalk(tmp_path):
    workloads = [f"l4_{class_id}" for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES]
    l4 = _make_l4_root(tmp_path, candidates=["cdse_a"], workloads=workloads)
    step5 = _make_step5(tmp_path)
    candidate_crosswalk = tmp_path / "candidate_crosswalk.json"
    workload_crosswalk = tmp_path / "workload_crosswalk.json"
    _write_json(
        candidate_crosswalk,
        {
            "candidate_crosswalk": {
                "cand_1": {
                    "l4_candidate_id": "cdse_a",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                },
                "cand_2": {
                    "l4_candidate_id": "cdse_a",
                    "equivalence_scope": "explicit_current_goal_l4_candidate",
                    "confidence": 1.0,
                },
            }
        },
    )
    _write_json(
        workload_crosswalk,
        {
            "workload_crosswalk": {
                class_id: {
                    "l4_workload_case_ids": [f"l4_{class_id}"],
                    "equivalence_scope": "explicit_current_goal_l4_workload",
                    "confidence": 1.0,
                }
                for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES
            }
        },
    )

    payload = build_dft_l4_goal_binding(
        l4_root=l4,
        step5_run=step5,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
        candidate_mapping_policy="explicit_crosswalk",
        workload_mapping_policy="explicit_crosswalk",
    )

    assert payload["l4_software_visible_proof_present"] is True
    assert payload["current_goal_binding"]["mapped_l4_candidates_unique"] is False
    assert payload["current_goal_binding"]["current_goal_l4_bound"] is False
    assert "candidate_identity_crosswalk_missing_or_incomplete" in payload["blockers"]


def test_l4_goal_binding_fails_validation_when_row_proof_is_missing(tmp_path):
    l4 = _make_l4_root(tmp_path)
    (l4 / "rows" / "cdse_a" / "qe_si_scf_small_v1" / "l4_gem5" / "gem5_l4_proof.json").unlink()

    payload = build_dft_l4_goal_binding(l4_root=l4)
    validation = validate_dft_l4_goal_binding(payload)

    assert payload["l4_software_visible_proof_present"] is False
    assert validation["valid"] is False
    assert "l4_software_visible_proof_not_complete" in validation["errors"]
