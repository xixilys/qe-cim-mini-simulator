#!/usr/bin/env python3
"""Tests for seven-day preliminary FPGA/hybrid-vs-GPU classifier."""

from __future__ import annotations

from dse_v2.evidence.qe_ic.preliminary_classifier import (
    classify_preliminary_opportunity,
)


def _report(records, conclusion=None):
    return {
        "gpu_baseline_summary": {
            "measurements_are_real": True,
            "evidence_status": "measured",
            "baseline_record_count": 3,
        },
        "candidate_evidence_summary": {
            "results_are_real": True,
            "candidate_result_count": len(records),
            "by_evidence_level": {"systemc_timing": len(records)},
            "by_evidence_status": {"high_fidelity_estimate": len(records)},
        },
        "opportunity_records": records,
        "system_conclusion": conclusion or {"what_evidence_is_missing": []},
    }


def test_preliminary_classifier_reports_fpga_hybrid_stronger_when_claim_gate_passes():
    result = classify_preliminary_opportunity(
        _report(
            [
                {
                    "candidate_id": "hyb-1",
                    "target_type": "gpu_fpga_hybrid",
                    "verdict": "hybrid_opportunity_found",
                    "claim_allowed": True,
                    "speedup_vs_gpu_mean": 1.28,
                    "speedup_vs_gpu_conservative_ci": 1.08,
                    "evidence_level": "gem5_systemc",
                    "evidence_status": "high_fidelity_estimate",
                    "claim_blockers": [],
                    "failure_reasons": ["speedup_claim_gate_passed"],
                    "overhead_summary": {
                        "transfer_overhead_ratio": 0.08,
                        "workflow_overhead_ratio": 0.04,
                    },
                }
            ]
        )
    )

    assert result["preliminary_label"] == "fpga_hybrid_stronger"
    assert result["best_candidate_id"] == "hyb-1"
    assert result["evidence_tier"] == "high_fidelity_preliminary"
    assert result["final_claim_allowed"] is False
    assert "not_final_hardware_superiority_claim" in result["claim_boundary"]


def test_preliminary_classifier_reports_fpga_hybrid_weaker_for_measured_slow_candidate_without_gpu_dominance():
    result = classify_preliminary_opportunity(
        _report(
            [
                {
                    "candidate_id": "fpga-weak",
                    "target_type": "fpga_only",
                    "verdict": "fpga_or_hybrid_inconclusive",
                    "claim_allowed": False,
                    "speedup_vs_gpu_mean": 0.74,
                    "speedup_vs_gpu_conservative_ci": 0.61,
                    "evidence_level": "real_qe_run",
                    "evidence_status": "measured",
                    "claim_blockers": ["no_speedup_vs_gpu"],
                    "failure_reasons": ["no_speedup_vs_gpu"],
                    "overhead_summary": {
                        "transfer_overhead_ratio": 0.12,
                        "workflow_overhead_ratio": 0.06,
                    },
                }
            ]
        )
    )

    assert result["preliminary_label"] == "fpga_hybrid_weaker"
    assert result["dominant_reasons"][0] == "no_speedup_vs_gpu"
    assert result["confidence"] in {"medium", "high"}


def test_preliminary_classifier_reports_gpu_dominant_when_gpu_utilization_and_overheads_dominate():
    result = classify_preliminary_opportunity(
        _report(
            [
                {
                    "candidate_id": "hyb-slow",
                    "target_type": "gpu_fpga_hybrid",
                    "verdict": "gpu_dominant_no_fpga_opportunity",
                    "claim_allowed": False,
                    "speedup_vs_gpu_mean": 0.92,
                    "speedup_vs_gpu_conservative_ci": 0.80,
                    "evidence_level": "systemc_timing",
                    "evidence_status": "high_fidelity_estimate",
                    "claim_blockers": ["no_speedup_vs_gpu"],
                    "failure_reasons": [
                        "gpu_utilization_high",
                        "no_speedup_vs_gpu",
                        "transfer_overhead_dominates",
                    ],
                    "overhead_summary": {
                        "transfer_overhead_ratio": 0.34,
                        "workflow_overhead_ratio": 0.10,
                    },
                }
            ]
        )
    )

    assert result["preliminary_label"] == "gpu_dominant"
    assert "gpu_utilization_high" in result["dominant_reasons"]
    assert result["required_next_evidence"]


def test_preliminary_classifier_uses_fundamental_no_opportunity_only_for_structural_limits():
    result = classify_preliminary_opportunity(
        _report(
            [
                {
                    "candidate_id": "structural-noop",
                    "target_type": "gpu_fpga_hybrid",
                    "verdict": "fpga_or_hybrid_inconclusive",
                    "claim_allowed": False,
                    "speedup_vs_gpu_mean": 0.99,
                    "evidence_level": "gem5_systemc",
                    "evidence_status": "high_fidelity_estimate",
                    "claim_blockers": ["structural_upper_bound_below_threshold"],
                    "failure_reasons": [
                        "structural_upper_bound_below_threshold",
                        "low_removable_fraction",
                        "host_bound_full_scf_dominates",
                    ],
                    "overhead_summary": {
                        "transfer_overhead_ratio": 0.03,
                        "workflow_overhead_ratio": 0.02,
                    },
                }
            ],
            conclusion={
                "what_evidence_is_missing": [],
                "dominant_failure_modes": [
                    "structural_upper_bound_below_threshold",
                    "host_bound_full_scf_dominates",
                ],
            },
        )
    )

    assert result["preliminary_label"] == "fundamental_no_opportunity"
    assert result["confidence"] == "medium"
    assert "no_strong_fundamental_claim_without_structural_evidence" not in result["blockers"]


def test_preliminary_classifier_does_not_force_requested_labels_when_evidence_is_missing():
    result = classify_preliminary_opportunity(
        {
            "gpu_baseline_summary": {
                "measurements_are_real": False,
                "baseline_record_count": 0,
            },
            "candidate_evidence_summary": {
                "results_are_real": False,
                "candidate_result_count": 0,
            },
            "opportunity_records": [],
            "system_conclusion": {
                "what_evidence_is_missing": ["matching measured GPU-only baseline record"],
            },
        }
    )

    assert result["preliminary_label"] == "insufficient_evidence"
    assert "measured_gpu_baseline_missing" in result["blockers"]
    assert result["advisor_labels_supported"] is False
