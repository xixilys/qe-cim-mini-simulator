#!/usr/bin/env python3
"""QE L4 offload value gate regressions."""

from __future__ import annotations

import copy

from dse_v2.codesign.qe_callgraph_offload_search import (
    classify_l4_offload_value,
)


def _trusted_l4_row():
    return {
        "opportunity_id": "opp_qe_si_scf_small_v1_scf_h_psi",
        "evidence_kind": "real_qe_l4",
        "evidence_scope": "full_qe_actual_compute",
        "actual_compute_evidence": {
            "status": "passed",
            "smoke_only": False,
            "qe_consumed_accelerated_outputs": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
        },
        "real_l4_provenance": {
            "status": "passed",
            "source": "gem5_genericaccel_qe_patched",
            "descriptor": {"status": "passed"},
            "request_decode": {"status": "passed"},
            "microarchitecture_execute": {"status": "passed"},
            "completion": {"status": "passed"},
        },
        "correctness": {"status": "passed"},
        "pure_qe_baseline": {"status": "passed"},
        "accelerated_replacement": {
            "status": "passed",
            "accelerated_results_consumed_by_qe": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "qe_software_kernel_execution_skipped": True,
            "software_fallback_on_critical_path": False,
        },
        "speed_signal": {
            "status": "positive",
            "speedup_vs_pure_qe": 1.05,
        },
    }


def test_real_qe_l4_correctness_and_speed_can_be_valuable_but_not_complete():
    verdict = classify_l4_offload_value(_trusted_l4_row())

    assert verdict["valuable_l4"] is True
    assert verdict["value_label"] == "valuable_l4"
    assert verdict["deliverable_complete"] is False
    assert verdict["blockers"] == []


def test_projection_sidecar_component_and_descriptor_only_evidence_is_banned():
    for evidence_kind in [
        "l3_timing_projection",
        "python_sidecar",
        "component_model",
        "descriptor_only",
    ]:
        row = _trusted_l4_row()
        row["evidence_kind"] = evidence_kind

        verdict = classify_l4_offload_value(row)

        assert verdict["valuable_l4"] is False
        assert verdict["value_label"] != "valuable_l4"
        assert f"banned_value_evidence_kind:{evidence_kind}" in verdict["blockers"]


def test_smoke_dataflow_evidence_cannot_claim_actual_compute_value():
    row = _trusted_l4_row()
    row["evidence_kind"] = "real_qe_l4_dataflow_smoke"
    row["evidence_scope"] = "dataflow_smoke_only"
    row["actual_compute_evidence"] = {
        "status": "blocked",
        "smoke_only": True,
    }

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] != "valuable_l4"
    assert "smoke_dataflow_only_not_actual_compute" in verdict["blockers"]
    assert "actual_compute_full_qe_evidence_not_passed" in verdict["blockers"]


def test_real_l4_with_blocked_actual_compute_is_attempt_blocked_not_not_valuable():
    row = _trusted_l4_row()
    row["actual_compute_evidence"]["status"] = "blocked"
    row["actual_compute_evidence"]["qe_consumed_accelerated_outputs"] = False

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] == "blocked"
    assert "actual_compute_full_qe_evidence_not_passed" in verdict["blockers"]


def test_transport_only_genericaccel_trace_cannot_claim_l4_value():
    row = _trusted_l4_row()
    row["real_l4_provenance"]["source"] = "gem5_genericaccel_trace_transport_only"

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] != "valuable_l4"
    assert "real_l4_source_not_qe_patched_genericaccel" in verdict["blockers"]


def test_positive_speed_without_replacement_cannot_claim_l4_value():
    row = _trusted_l4_row()
    row.pop("accelerated_replacement")

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] == "not_valuable_l4"
    assert "accelerated_replacement_not_passed" in verdict["blockers"]


def test_positive_speed_without_kernel_work_replacement_cannot_claim_l4_value():
    row = _trusted_l4_row()
    row["accelerated_replacement"].pop("qe_kernel_work_replaced_on_critical_path")

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] == "not_valuable_l4"
    assert "qe_kernel_work_replacement_not_proven" in verdict["blockers"]
    assert "accelerated_replacement_not_passed" not in verdict["blockers"]


def test_positive_speed_without_materialized_accelerator_output_cannot_claim_l4_value():
    row = _trusted_l4_row()
    row["accelerated_replacement"].pop("accelerated_result_materialized_in_qe_memory")

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert "accelerated_result_materialization_not_proven" in verdict["blockers"]
    assert "qe_kernel_work_replacement_not_proven" in verdict["blockers"]


def test_positive_speed_without_skipped_software_kernel_cannot_claim_l4_value():
    row = _trusted_l4_row()
    row["accelerated_replacement"].pop("qe_software_kernel_execution_skipped")

    verdict = classify_l4_offload_value(row)

    assert verdict["valuable_l4"] is False
    assert "qe_software_kernel_execution_skip_not_proven" in verdict["blockers"]
    assert "qe_kernel_work_replacement_not_proven" in verdict["blockers"]


def test_real_l4_row_without_execute_completion_correctness_or_speed_is_blocked():
    missing_execute = _trusted_l4_row()
    missing_execute["real_l4_provenance"].pop("microarchitecture_execute")
    verdict = classify_l4_offload_value(missing_execute)
    assert verdict["valuable_l4"] is False
    assert (
        "real_l4_microarchitecture_execute_evidence_missing_or_failed"
        in verdict["blockers"]
    )

    missing_correctness = copy.deepcopy(_trusted_l4_row())
    missing_correctness["correctness"] = {"status": "failed"}
    verdict = classify_l4_offload_value(missing_correctness)
    assert verdict["valuable_l4"] is False
    assert "correctness_not_passed" in verdict["blockers"]

    no_speed = copy.deepcopy(_trusted_l4_row())
    no_speed["speed_signal"] = {"status": "flat", "speedup_vs_pure_qe": 1.0}
    verdict = classify_l4_offload_value(no_speed)
    assert verdict["valuable_l4"] is False
    assert verdict["value_label"] == "not_valuable_l4"
    assert "positive_speed_signal_missing" in verdict["blockers"]
