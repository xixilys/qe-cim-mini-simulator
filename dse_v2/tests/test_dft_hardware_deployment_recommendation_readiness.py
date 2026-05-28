#!/usr/bin/env python3
"""DFT hardware deployment recommendation readiness tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES
from dse_v2.reference_workloads.dft_hardware_deployment_recommendation_readiness import (
    DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA,
    build_dft_hardware_deployment_recommendation_readiness,
    validate_dft_hardware_deployment_recommendation_readiness,
    write_dft_hardware_deployment_recommendation_readiness,
)


STAGES = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _hashed_source_ref(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "hash_algorithm": "sha256",
    }


def _next_evidence_identity(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item.get("task_id") or ""),
        str(item.get("deployment") or ""),
        str(item.get("reason") or ""),
        str(item.get("evidence_scope") or ""),
    )


def _seed_ready_sources(run_dir: Path, *, include_target_selection: bool = True) -> None:
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    if include_target_selection:
        _seed_target_selection(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )


def _seed_workplan(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "release_id": "release-readiness-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "work_items": [
                {
                    "work_item_id": f"cand-a:fft_ifft_ffft:{stage_id}",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": stage_id,
                    "blocked": True,
                    "candidate_specific_evidence_present": False,
                }
                for stage_id in STAGES
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan_validation.json",
        {"schema_version": "dse.dft.hardware_completion_workplan_validation.v1", "valid": True, "errors": []},
    )


def _seed_closed_workplan(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "release_id": "release-ready-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "work_items": [
                {
                    "work_item_id": f"cand-a:fft_ifft_ffft:{stage_id}",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": stage_id,
                    "blocked": False,
                    "candidate_specific_evidence_present": True,
                }
                for stage_id in STAGES
            ],
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan_validation.json",
        {"schema_version": "dse.dft.hardware_completion_workplan_validation.v1", "valid": True, "errors": []},
    )


def _seed_closed_release_gate(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-ready-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "stage_gate_passed_count": len(STAGES),
            "unit_gate_passed_count": 1,
            "candidate_gate_passed_count": 1,
            "release_gate_result": "hardware_completion_eligible_pending_deliverable_claim",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_closure_release_gate_validation.json",
        {"schema_version": "dse.dft.hardware_closure_release_gate_validation.v1", "valid": True, "errors": []},
    )


def _seed_partial_closed_workplan(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "release_id": "release-partial-stage-coverage-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "work_items": [
                {
                    "work_item_id": "cand-a:fft_ifft_ffft:golden_correctness",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": "golden_correctness",
                    "blocked": False,
                    "candidate_specific_evidence_present": True,
                }
            ],
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan_validation.json",
        {"schema_version": "dse.dft.hardware_completion_workplan_validation.v1", "valid": True, "errors": []},
    )


def _seed_blocked_winner_resolution(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "blocked_no_unique_hardware_ppa_winners",
            "release_id": "release-readiness-test",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "hardware_winner_resolution_eligible": False,
            "deliverable_complete": False,
            "deployments": {
                "fpga": {
                    "status": "blocked_no_unique_hardware_ppa_winner",
                    "resolved": False,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [{"task_id": "fpga_candidate_specific_ppa_tie_breaker"}],
                },
                "asic": {
                    "status": "blocked_no_unique_hardware_ppa_winner",
                    "resolved": False,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [{"task_id": "asic_candidate_specific_ppa_tie_breaker"}],
                },
            },
            "blockers": [{"blocker_id": "candidate_specific_ppa_provenance_not_trusted"}],
            "blocker_count": 1,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )


def _seed_ready_winner_resolution(run_dir: Path) -> None:
    # The source winner-resolution artifact may contain winner objects.  The
    # readiness artifact must not copy those objects or name final winners.
    winner = {"candidate_id": "cand-a", "rank": 1}
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "resolved_hardware_ppa_deployment_winners",
            "release_id": "release-ready-test",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "hardware_winner_resolution_eligible": True,
            "deliverable_complete": False,
            "deployments": {
                "fpga": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "winner": winner,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [],
                },
                "asic": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "winner": winner,
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [],
                },
            },
            "fpga_best_architecture": winner,
            "asic_best_architecture": winner,
            "blockers": [],
            "blocker_count": 0,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )


def _seed_queue(run_dir: Path, *, empty: bool) -> None:
    work_items = [] if empty else [
        {
            "work_item_id": "fresh_ppa:cand-a:fft_ifft_ffft:vivado_fpga_synth_or_impl",
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "vivado_fpga_synth_or_impl",
            "fresh_execution_required": True,
        },
        {
            "work_item_id": "fresh_ppa:cand-a:fft_ifft_ffft:dc_asic_synth_timing_area",
            "candidate_id": "cand-a",
            "kernel_id": "fft_ifft_ffft",
            "stage_id": "dc_asic_synth_timing_area",
            "fresh_execution_required": True,
        },
    ]
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "no_tie_breaker_work_items" if empty else "fresh_candidate_specific_ppa_execution_required",
            "work_item_count": len(work_items),
            "work_items": work_items,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json",
        {"schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1", "valid": True, "errors": []},
    )


def _seed_tools(run_dir: Path) -> None:
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": False},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )


def _seed_target_scoped_ppa_ranking(
    run_dir: Path,
    *,
    fpga_candidate_id: str = "cand-a",
    asic_candidate_id: str = "cand-a",
    fpga_identity_target: str = "fpga",
    asic_identity_target: str = "asic",
    fpga_stage_target: str = "fpga",
    asic_stage_target: str = "asic",
) -> None:
    def row(candidate_id: str, ranking_target: str, identity_target: str, stage_target: str) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "rank": 1,
            "ranking_target": ranking_target,
            "target_required_stage_ids": [
                "golden_correctness",
                "hls_or_rtl_sim",
                "hls_or_rtl_synth",
                "vivado_fpga_synth_or_impl" if stage_target == "fpga" else "dc_asic_synth_timing_area",
            ],
            "ranking_eligible": True,
            "candidate_gate_passed": True,
            "target_specific_blockers": [],
            "candidate_identity": {
                "candidate_id": candidate_id,
                "deployment_boundary": {"accelerated_kernels": ["fft_ifft_ffft"]},
                "host_device_partition": {"accelerated_node_ids": ["fft_ifft_ffft"], "cpu_retained_node_ids": ["scf_control"]},
                "architecture_template_parameters": {"template_id": f"{identity_target}_template"},
                "mapping_layout": {"layout_id": "layout-a"},
                "runtime_co_scheduling": {"policy_id": "overlap_dma_compute"},
                "descriptor_granularity": {"granularity": "kernel_descriptor"},
                "fallback_policy": {"policy_id": "cpu_fallback"},
                "target_platform": {"deployment_target": identity_target},
            },
        }

    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "fpga_ranking": [row(fpga_candidate_id, "fpga", fpga_identity_target, fpga_stage_target)],
            "asic_ranking": [row(asic_candidate_id, "asic", asic_identity_target, asic_stage_target)],
            "deliverable_complete": False,
            "trusted_final_claim": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )


def _seed_target_selection(run_dir: Path) -> None:
    fpga_catalog_path = _write_json(
        run_dir / "fpga_target_catalog.json",
        {"schema_version": "test.fpga_target_catalog.v1", "targets": ["part_from_current_catalog"]},
    )
    asic_probe_path = _write_json(
        run_dir / "asic_target_library_probe.json",
        {"schema_version": "test.asic_target_library_probe.v1", "target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"]},
    )
    _write_json(
        run_dir / "dft_hardware_deployment_target_selection.json",
        {
            "schema_version": "dse.dft.hardware_deployment_target_selection.v1",
            "status": "target_selection_ready",
            "budget_policy": "unbounded_budget_current_catalog_required",
            "input_trust_gates": {
                "fpga_target_catalog": {
                    "trust_class": "fpga_target_catalog",
                    "trusted": True,
                    "source_ref_count": 1,
                    "source_refs": [_hashed_source_ref(fpga_catalog_path)],
                    "blockers": [],
                },
                "asic_target_library_probe": {
                    "trust_class": "asic_target_library_probe",
                    "trusted": True,
                    "source_ref_count": 1,
                    "source_refs": [_hashed_source_ref(asic_probe_path)],
                    "blockers": [],
                },
            },
            "deployments": {
                "fpga": {
                    "selection_status": "selected",
                    "target_device_id": "fpga_unbounded_budget_placeholder",
                    "vendor": "vendor_from_current_catalog",
                    "part": "part_from_current_catalog",
                    "family": "family_from_current_catalog",
                    "budget_policy": "unbounded_budget",
                    "capacity": {
                        "slice_luts": 1_000_000,
                        "dsps": 8_000,
                        "block_ram_tiles": 2_000,
                    },
                    "source_refs": [_hashed_source_ref(fpga_catalog_path)],
                },
                "asic": {
                    "selection_status": "selected",
                    "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                    "process_node": "library_defined",
                    "pvt_corner": "tt_1p8v_25c",
                    "voltage_v": 1.8,
                    "temperature_c": 25,
                    "source_refs": [_hashed_source_ref(asic_probe_path)],
                },
            },
        },
    )
    _write_json(
        run_dir / "dft_hardware_deployment_target_selection_validation.json",
        {
            "schema_version": "dse.dft.hardware_deployment_target_selection_validation.v1",
            "valid": True,
            "errors": [],
        },
    )


def _attach_target_selection_input_trust_gates(run_dir: Path) -> None:
    target_path = run_dir / "dft_hardware_deployment_target_selection.json"
    target_selection = json.loads(target_path.read_text(encoding="utf-8"))
    target_selection["input_trust_gates"] = {
        "fpga_target_catalog": {
            "trust_class": "fpga_target_catalog",
            "trusted": True,
            "source_ref_count": 1,
            "source_refs": target_selection["deployments"]["fpga"]["source_refs"],
            "blockers": [],
        },
        "asic_target_library_probe": {
            "trust_class": "asic_target_library_probe",
            "trusted": True,
            "source_ref_count": 1,
            "source_refs": target_selection["deployments"]["asic"]["source_refs"],
            "blockers": [],
        },
    }
    _write_json(target_path, target_selection)


def _seed_targeted_accounting(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_full_scf_targeted_deployment_accounting.json",
        {
            "schema_version": "dse.dft.full_scf_targeted_deployment_accounting.v1",
            "status": "targeted_accounting_ready_final_recommendation_blocked",
            "targeted_accounting_ready": True,
            "full_scf_numerical_gate_passed": False,
            "can_name_targeted_deployment_recommendation": False,
            "can_name_final_recommendation": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "deployments": {
                "fpga": {
                    "status": "targeted_accounting_ready_pending_full_scf_numerical_gate",
                    "accounting_ready": True,
                    "candidate_id": "cand-a",
                    "design_candidate_id": "design-a",
                    "selected_target": {"part": "xc7k480tffg1156-3"},
                    "full_scf_numerical_gate_passed": False,
                    "blocker_ids": [],
                    "final_claim_blockers": [{"blocker_id": "full_scf_numerical_gate_not_passed"}],
                },
                "asic": {
                    "status": "targeted_accounting_ready_pending_full_scf_numerical_gate",
                    "accounting_ready": True,
                    "candidate_id": "cand-a",
                    "design_candidate_id": "design-a",
                    "selected_target": {"target_library_id": "fsa0a_c_generic_core_tt1p8v25c"},
                    "full_scf_numerical_gate_passed": False,
                    "blocker_ids": [],
                    "final_claim_blockers": [{"blocker_id": "full_scf_numerical_gate_not_passed"}],
                },
            },
        },
    )
    _write_json(
        run_dir / "dft_full_scf_targeted_deployment_accounting_validation.json",
        {
            "schema_version": "dse.dft.full_scf_targeted_deployment_accounting_validation.v1",
            "valid": True,
            "errors": [],
        },
    )
    _write_json(
        run_dir / "dft_full_scf_targeted_deployment_accounting_status.json",
        {
            "schema_version": "dse.dft.full_scf_targeted_deployment_accounting_status.v1",
            "status": "passed",
            "targeted_accounting_ready": True,
            "full_scf_numerical_gate_passed": False,
            "can_name_targeted_deployment_recommendation": False,
            "can_name_final_recommendation": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
    )


def _full_scf_row(
    candidate_id: str,
    class_id: str,
    *,
    passed: bool,
    self_asserted_status_passed: bool = False,
) -> dict[str, object]:
    if passed:
        return {
            "candidate_id": candidate_id,
            "class_id": class_id,
            "status": "passed",
            "passed": True,
            "trusted_accelerated_numeric_source": True,
            "measurement_source": "qe_full_scf_host_accelerator_runtime",
            "measurement_source_kind": "qe_full_scf_host_accelerator_runtime",
            "execution_proof_present": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "full_scf_schedule_consumed": True,
            "host_accelerator_end_to_end": True,
            "host_bound_costs_included": True,
            "host_bound_costs_s": 1.0,
            "runtime_overhead_costs_s": 0.1,
            "accelerated_kernel_costs_s": {"fft_ifft_ffft": 0.2},
            "covered_accelerated_kernel_ids": ["fft_ifft_ffft"],
            "metric_checks": {
                "density_residual": {"passed": True},
                "total_energy_error_ry": {"passed": True},
            },
            "blockers": [],
        }
    return {
        "candidate_id": candidate_id,
        "class_id": class_id,
        "status": "passed" if self_asserted_status_passed else "blocked_temporary",
        "passed": False,
        "trusted_accelerated_numeric_source": False,
        "measurement_source": "",
        "measurement_source_kind": "",
        "execution_proof_present": False,
        "comparison_scope": "kernel_only",
        "full_scf_schedule_consumed": False,
        "host_accelerator_end_to_end": False,
        "host_bound_costs_included": False,
        "missing_accelerated_kernel_ids": ["projector", "reduction"],
        "artifact_ref": {"path": f"full_scf_numerical_rows/{candidate_id}/{class_id}.json"},
        "blockers": [
            "comparison_scope_not_full_scf_host_accelerator_end_to_end",
            "full_scf_schedule_consumed_not_true",
            "host_accelerator_end_to_end_not_true",
            "host_bound_costs_included_not_true",
            "host_bound_costs_s_missing",
            "runtime_overhead_costs_s_missing",
            "accelerated_kernel_costs_s_missing",
            "major_accelerated_kernels_not_all_covered",
            "trusted_accelerated_numeric_source_not_true",
            "missing_real_full_scf_execution_proof",
            "required_physical_metric_missing::density_residual",
            "required_physical_metric_missing::total_energy_error_ry",
        ],
    }


def _seed_full_scf_comparison(
    run_dir: Path,
    *,
    candidate_ids: tuple[str, ...] = ("cand-a", "cand-b"),
    passed: bool,
    self_asserted_status_passed: bool = False,
) -> None:
    strict_classes = tuple(STRICT_DFT_QE_WORKLOAD_CLASSES)
    rows = [
        _full_scf_row(
            candidate_id,
            class_id,
            passed=passed,
            self_asserted_status_passed=self_asserted_status_passed,
        )
        for candidate_id in candidate_ids
        for class_id in strict_classes
    ]
    candidate_records = [
        {
            "candidate_id": candidate_id,
            "status": "passed" if passed or self_asserted_status_passed else "blocked_temporary",
            "passed": passed,
            "trusted_accelerated_numeric_source": passed,
            "missing_accelerated_kernel_ids": [] if passed else ["projector", "reduction"],
            "blockers": [] if passed else ["not_all_strict_scf_rows_passed"],
        }
        for candidate_id in candidate_ids
    ]
    passed_rows = len(rows) if passed else 0
    passed_candidates = len(candidate_records) if passed else 0
    comparison = {
        "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
        "status": "passed" if passed or self_asserted_status_passed else "blocked_temporary",
        "passed": passed,
        "trusted_accelerated_numeric_source": passed,
        "candidate_ids": list(candidate_ids),
        "strict_scf_class_ids": list(strict_classes),
        "candidate_count": len(candidate_records),
        "passed_candidate_count": passed_candidates,
        "blocked_candidate_count": len(candidate_records) - passed_candidates,
        "row_record_count": len(rows),
        "passed_row_record_count": passed_rows,
        "blocked_row_record_count": len(rows) - passed_rows,
        "candidate_records": candidate_records,
        "row_records": rows,
        "blockers": []
        if passed
        else [
            "not_all_candidate_class_rows_passed_full_scf_comparison",
            "trusted_accelerated_numeric_source_not_true",
        ],
        "blocker_count": 0 if passed else 2,
        "claim_boundary": "unit-test full-SCF comparison fixture",
    }
    _write_json(run_dir / "full_scf_end_to_end_comparison.json", comparison)
    _write_json(
        run_dir / "full_scf_end_to_end_comparison_validation.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_validation.v1",
            "status": "passed" if passed else "blocked_temporary",
            "passed": passed,
            "valid": passed,
            "errors": [] if passed else ["full_scf_comparison_not_passed"],
        },
    )
    _write_json(
        run_dir / "full_scf_end_to_end_comparison_status.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_status.v1",
            "status": "comparison_passed" if passed else "comparison_blocked",
            "comparison_status": "passed" if passed else "blocked_temporary",
            "comparison_passed": passed,
            "validation_status": "passed" if passed else "blocked_temporary",
            "validation_passed": passed,
            "candidate_count": comparison["candidate_count"],
            "row_record_count": comparison["row_record_count"],
            "blocked_candidate_count": comparison["blocked_candidate_count"],
            "blocked_row_record_count": comparison["blocked_row_record_count"],
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "numerical_correctness_claim_eligible": False,
        },
    )


def _seed_full_scf_trusted_queue(
    run_dir: Path,
    *,
    candidate_id: str = "cand-a",
    target_scopes: tuple[str, ...] = ("fpga", "asic"),
    class_ids: tuple[str, ...] | None = None,
) -> None:
    classes = class_ids or tuple(STRICT_DFT_QE_WORKLOAD_CLASSES[:2])
    work_items = [
        {
            "work_item_id": f"full_scf_trusted_evidence:{candidate_id}:{class_id}",
            "candidate_id": candidate_id,
            "class_id": class_id,
            "workload_case_id": class_id,
            "target_scopes": list(target_scopes),
            "queue_state": "queued_blocked_until_trusted_full_scf_execution",
            "fresh_execution_required": True,
            "no_shared_evidence_allowed": True,
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "required_outputs": {
                "qe_accelerated_numeric_evidence": (
                    f"accelerated_numeric_inputs/{candidate_id}/{class_id}/"
                    "qe_accelerated_numeric_evidence.json"
                ),
                "full_scf_end_to_end_numerical_evidence": (
                    f"full_scf_numerical_rows/{candidate_id}/{class_id}/"
                    "full_scf_end_to_end_numerical_evidence.json"
                ),
                "runtime_proof": f"full_scf_numerical_rows/{candidate_id}/{class_id}/runtime_proof.json",
            },
        }
        for class_id in classes
    ]
    payload = {
        "schema_version": "dse.dft.full_scf_trusted_evidence_execution_queue.v1",
        "status": "trusted_full_scf_execution_required",
        "queue_materialization_status": "materialized_pending_trusted_full_scf_evidence",
        "execution_required": True,
        "work_item_count": len(work_items),
        "candidate_count": 1,
        "strict_scf_class_count": len(classes),
        "candidate_ids": [candidate_id],
        "strict_scf_class_ids": list(classes),
        "winner_prioritization_trusted": True,
        "source_blocker_id_counts": {"missing_real_full_scf_execution_proof": len(work_items)},
        "work_items": work_items,
        "prioritization_only": True,
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }
    _write_json(run_dir / "full_scf_trusted_evidence_execution_queue.json", payload)
    _write_json(
        run_dir / "full_scf_trusted_evidence_execution_queue_validation.json",
        {
            "schema_version": "dse.dft.full_scf_trusted_evidence_execution_queue_validation.v1",
            "valid": True,
            "errors": [],
            "work_item_count": len(work_items),
        },
    )
    _write_json(
        run_dir / "full_scf_trusted_evidence_execution_queue_status.json",
        {
            "schema_version": "dse.dft.full_scf_trusted_evidence_execution_queue_status.v1",
            "status": "passed",
            "validation_status": "passed",
            "queue_status": "trusted_full_scf_execution_required",
            "execution_required": True,
            "work_item_count": len(work_items),
            "candidate_count": 1,
            "strict_scf_class_count": len(classes),
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def test_deployment_readiness_blocks_and_summarizes_workplan_queue_and_tools(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_workplan(run_dir)
    _seed_blocked_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=False)
    _seed_tools(run_dir)

    status = write_dft_hardware_deployment_recommendation_readiness(run_dir)
    payload = json.loads((run_dir / "dft_hardware_deployment_recommendation_readiness.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_deployment_recommendation_readiness_validation.json").read_text())

    assert status["status"] == "passed"
    assert payload["schema_version"] == DFT_HARDWARE_DEPLOYMENT_RECOMMENDATION_READINESS_SCHEMA
    assert payload["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert payload["fpga_can_name_winner"] is False
    assert payload["asic_can_name_winner"] is False
    assert payload["deployment_target_selection_ready"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert payload["deployments"]["fpga"]["tie_breaker_queue"]["work_item_count"] == 1
    assert payload["deployments"]["asic"]["tie_breaker_queue"]["work_item_count"] == 1
    assert payload["deployments"]["fpga"]["workplan"]["pending_candidate_specific_work_item_count"] == 4
    assert payload["deployments"]["asic"]["workplan"]["pending_candidate_specific_work_item_count"] == 4
    assert payload["deployments"]["fpga"]["tool_readiness"]["unavailable_tools"] == ["vivado"]
    assert payload["deployments"]["fpga"]["target_selection"]["status"] == "target_selection_required"
    assert payload["deployments"]["fpga"]["next_runnable_work_item_counts"]["deployment_target_selection"] == 1
    assert payload["final_recommendation_required_next_evidence"]["fpga"]
    assert payload["required_next_evidence"]["fpga"]
    assert "DC-only evidence used for FPGA deployment claims" in payload["forbidden_shortcuts"]
    assert validation["valid"] is True


def test_deployment_readiness_can_report_hardware_name_ready_without_naming_winner(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "ready_to_name_hardware_ppa_winners_not_final_recommendation"
    assert payload["can_name_hardware_ppa_winners"] is True
    assert payload["deployments"]["fpga"]["can_name_winner"] is True
    assert payload["deployment_target_selection_ready"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["deployments"]["fpga"]["target_selection"]["ready_for_targeted_recommendation"] is False
    assert payload["required_next_evidence"]["fpga"]
    assert payload["deployments"]["fpga"]["required_next_evidence"]
    assert any(
        item.get("evidence_scope") == "final_deployment_recommendation"
        and item.get("reason") == "full_scf_targeted_deployment_accounting_required"
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert payload["final_recommendation_required_next_evidence"]["fpga"]
    assert payload["trusted_final_claim"] is False
    assert payload["hardware_completion_eligible"] is False
    assert payload["upstream_winner_resolution_hardware_completion_eligible"] is True
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert "fpga_best_architecture" not in encoded
    assert '"winner"' not in encoded
    assert validation["valid"] is True


def test_deployment_readiness_accepts_release_gate_closure_when_workplan_snapshot_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_winner_resolution(run_dir)
    _seed_closed_release_gate(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["status"] == "ready_to_name_hardware_ppa_winners_not_final_recommendation"
    assert payload["can_name_hardware_ppa_winners"] is True
    assert payload["hardware_completion_eligible"] is False
    assert payload["upstream_winner_resolution_hardware_completion_eligible"] is True
    assert payload["release_gate_hardware_completion_eligible"] is True
    assert payload["release_gate_validation_valid"] is True
    assert payload["deployments"]["fpga"]["workplan"]["covered_by_release_gate"] is True
    assert payload["deployments"]["fpga"]["workplan"]["closure_source"] == "dft_hardware_closure_release_gate"
    assert payload["deployments"]["fpga"]["can_name_hardware_ppa_winner"] is True
    assert payload["deployments"]["asic"]["can_name_hardware_ppa_winner"] is True
    assert not any(
        item.get("reason") == "missing_required_source_artifact:hardware_completion_workplan"
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_readiness_blocks_pending_candidate_specific_freshness_queue(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _write_json(
        run_dir / "dft_candidate_specific_ppa_freshness_queue.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_freshness_queue.v1",
            "status": "fresh_candidate_specific_ppa_execution_required",
            "work_item_count": 2,
            "work_items": [
                {
                    "work_item_id": "cand-a:fft_ifft_ffft:vivado_fpga_synth_or_impl:freshness_rerun",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "fresh_execution_required": True,
                },
                {
                    "work_item_id": "cand-a:fft_ifft_ffft:dc_asic_synth_timing_area:freshness_rerun",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": "dc_asic_synth_timing_area",
                    "fresh_execution_required": True,
                },
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert payload["can_name_hardware_ppa_winners"] is False
    assert payload["deployments"]["fpga"]["can_name_winner"] is False
    assert payload["deployments"]["asic"]["can_name_winner"] is False
    assert payload["deployments"]["fpga"]["tie_breaker_queue"]["work_item_count"] == 0
    assert payload["deployments"]["fpga"]["candidate_specific_ppa_freshness_queue"]["work_item_count"] == 1
    assert payload["deployments"]["asic"]["candidate_specific_ppa_freshness_queue"]["work_item_count"] == 1
    assert (
        payload["deployments"]["fpga"]["next_runnable_work_item_counts"][
            "candidate_specific_ppa_freshness_queue"
        ]
        == 1
    )
    assert any(
        blocker.get("blocker_id") == "candidate_specific_ppa_freshness_queue_pending"
        for blocker in payload["deployments"]["fpga"]["blockers"]
    )
    assert any(
        item.get("reason") == "candidate_specific_ppa_freshness_queue_pending"
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert validation["valid"] is True


def test_deployment_readiness_blocks_missing_deployment_stage_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_partial_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert payload["can_name_hardware_ppa_winners"] is False
    assert payload["deployments"]["fpga"]["can_name_hardware_ppa_winner"] is False
    assert payload["deployments"]["asic"]["can_name_hardware_ppa_winner"] is False
    assert "vivado_fpga_synth_or_impl" in payload["deployments"]["fpga"]["workplan"]["missing_stage_ids"]
    assert "dc_asic_synth_timing_area" in payload["deployments"]["asic"]["workplan"]["missing_stage_ids"]
    fpga_blockers = {
        blocker["blocker_id"]
        for blocker in payload["deployments"]["fpga"]["blockers"]
    }
    assert "deployment_workplan_missing_required_stage_rows" in fpga_blockers
    fpga_missing_stage_items = [
        item
        for item in payload["required_next_evidence"]["fpga"]
        if item.get("reason") == "completion_workplan_missing_required_deployment_stages"
    ]
    assert fpga_missing_stage_items
    assert "vivado_fpga_synth_or_impl" in fpga_missing_stage_items[0]["missing_stage_ids"]
    assert validation["valid"] is True


def test_deployment_readiness_blocks_resolved_winner_when_workplan_or_tools_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert payload["can_name_hardware_ppa_winners"] is False
    assert payload["deployments"]["fpga"]["can_name_winner"] is False
    assert payload["deployments"]["asic"]["can_name_winner"] is False
    fpga_blockers = {
        blocker["blocker_id"]
        for blocker in payload["deployments"]["fpga"]["blockers"]
    }
    assert "missing_required_source_artifact:hardware_completion_workplan" in fpga_blockers
    assert "deployment_workplan_has_no_stage_rows" in fpga_blockers
    assert "required_eda_tools_not_available" in fpga_blockers
    fpga_next = payload["required_next_evidence"]["fpga"]
    assert fpga_next
    reasons = {item.get("reason") for item in fpga_next}
    assert "missing_required_source_artifact:hardware_completion_workplan" in reasons
    assert "completion_workplan_has_no_deployment_stage_rows" in reasons
    assert "required_tool_availability_unknown" in reasons
    assert validation["valid"] is True


def test_deployment_readiness_records_target_selection_without_upgrading_final_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _seed_target_selection(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["deployment_target_selection_ready"] is True
    assert payload["can_name_hardware_ppa_winners"] is True
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert payload["deployments"]["fpga"]["target_selection"]["status"] == "target_selection_ready"
    assert payload["deployments"]["asic"]["target_selection"]["selected_target"]["target_library_id"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert payload["deployments"]["fpga"]["next_runnable_work_item_counts"]["deployment_target_selection"] == 0
    assert any(
        item.get("evidence_scope") == "final_deployment_recommendation"
        and item.get("task_id") == "fpga_full_scf_targeted_deployment_accounting"
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert payload["deployments"]["fpga"]["required_next_evidence"]
    assert validation["valid"] is True


def test_deployment_readiness_propagates_target_selection_trust_gates_without_final_upgrade(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _seed_target_selection(run_dir)
    _attach_target_selection_input_trust_gates(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    trust_gates = payload["deployment_target_selection_trust_gates"]
    assert trust_gates["all_trusted"] is True
    assert trust_gates["gates"]["fpga_target_catalog"]["trusted"] is True
    assert trust_gates["gates"]["asic_target_library_probe"]["trusted"] is True
    assert (
        payload["deployments"]["fpga"]["target_selection"]["input_trust_gate"]["trust_class"]
        == "fpga_target_catalog"
    )
    assert payload["deployments"]["asic"]["target_selection"]["input_trust_gate"]["trusted"] is True
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["trusted_final_claim"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_readiness_accepts_targeted_accounting_without_upgrading_final_claim(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _seed_target_selection(run_dir)
    _seed_targeted_accounting(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["full_scf_targeted_deployment_accounting"]["targeted_accounting_ready"] is True
    assert payload["deployments"]["fpga"]["targeted_deployment_accounting"]["accounting_ready"] is True
    assert (
        payload["deployments"]["fpga"]["next_runnable_work_item_counts"][
            "targeted_deployment_accounting"
        ]
        == 0
    )
    assert not any(
        item.get("reason") == "full_scf_targeted_deployment_accounting_required"
        for item in payload["deployments"]["fpga"]["final_recommendation_required_next_evidence"]
    )
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_readiness_revalidates_stale_target_selection_payload(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    target_path = run_dir / "dft_hardware_deployment_target_selection.json"
    target_selection = json.loads(target_path.read_text(encoding="utf-8"))
    target_selection["deployments"]["fpga"]["winner"] = {"candidate_id": "cand-a"}
    _write_json(target_path, target_selection)

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["deployment_target_selection_validation"]["companion_valid"] is True
    assert payload["deployment_target_selection_validation"]["recomputed_valid"] is False
    assert (
        "target_selection_must_not_name_winners"
        in payload["deployment_target_selection_validation"]["recomputed_errors"]
    )
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["target_selection"]["ready_for_targeted_recommendation"] is False
    assert any(
        blocker["blocker_id"] == "deployment_target_selection_validation_not_valid"
        for blocker in payload["deployments"]["fpga"]["target_selection"]["blockers"]
    )
    assert validation["valid"] is True


def test_deployment_readiness_reuses_tool_probe_from_target_selection_source_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    tool_probe = tmp_path / "target-inputs" / "ic_eda_tool_availability.json"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(run_dir)
    _seed_target_selection(run_dir)
    _write_json(
        tool_probe,
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )
    target_selection = json.loads((run_dir / "dft_hardware_deployment_target_selection.json").read_text())
    target_selection["source_artifacts"] = {
        "ic_eda_tool_availability": {
            "path": str(tool_probe),
            "required": False,
            "exists": True,
        }
    }
    _write_json(run_dir / "dft_hardware_deployment_target_selection.json", target_selection)

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["source_artifacts"]["ic_eda_tool_availability"]["path"] == str(tool_probe)
    assert payload["deployments"]["fpga"]["tool_readiness"]["status"] == "all_required_tools_available"
    assert payload["deployments"]["asic"]["tool_readiness"]["status"] == "all_required_tools_available"
    assert payload["can_name_hardware_ppa_winners"] is True
    assert validation["valid"] is True


def test_deployment_readiness_validator_rejects_winner_leak_and_final_claim_upgrade(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_blocked_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=False)
    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)

    leaked = json.loads(json.dumps(payload))
    leaked["fpga_best_architecture"] = {"candidate_id": "cand-a"}
    assert validate_dft_hardware_deployment_recommendation_readiness(leaked)["valid"] is False

    upgraded = json.loads(json.dumps(payload))
    upgraded["deliverable_complete"] = True
    upgraded["can_name_final_recommendation"] = True
    upgraded["hardware_completion_eligible"] = True
    assert validate_dft_hardware_deployment_recommendation_readiness(upgraded)["valid"] is False

    targeted = json.loads(json.dumps(payload))
    targeted["can_name_targeted_deployment_recommendation"] = True
    assert validate_dft_hardware_deployment_recommendation_readiness(targeted)["valid"] is False


def test_deployment_readiness_validator_rejects_unmirrored_deployment_final_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir, include_target_selection=False)
    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    assert validate_dft_hardware_deployment_recommendation_readiness(payload)["valid"] is True
    assert len(payload["deployments"]["fpga"]["final_recommendation_required_next_evidence"]) > 1

    mutated = json.loads(json.dumps(payload))
    final_item = mutated["deployments"]["fpga"]["final_recommendation_required_next_evidence"][0]
    final_identity = _next_evidence_identity(final_item)
    mutated["deployments"]["fpga"]["required_next_evidence"] = [
        item
        for item in mutated["deployments"]["fpga"]["required_next_evidence"]
        if _next_evidence_identity(item) != final_identity
    ]
    assert any(
        item.get("evidence_scope") == "final_deployment_recommendation"
        for item in mutated["deployments"]["fpga"]["required_next_evidence"]
    )

    validation = validate_dft_hardware_deployment_recommendation_readiness(mutated)

    assert validation["valid"] is False
    assert "fpga_final_evidence_not_mirrored_in_required_next_evidence" in validation["errors"]


def test_deployment_readiness_validator_rejects_unmirrored_top_level_final_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir, include_target_selection=False)
    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    assert validate_dft_hardware_deployment_recommendation_readiness(payload)["valid"] is True
    assert len(payload["final_recommendation_required_next_evidence"]["fpga"]) > 1

    mutated = json.loads(json.dumps(payload))
    final_item = mutated["final_recommendation_required_next_evidence"]["fpga"][0]
    final_identity = _next_evidence_identity(final_item)
    mutated["required_next_evidence"]["fpga"] = [
        item
        for item in mutated["required_next_evidence"]["fpga"]
        if _next_evidence_identity(item) != final_identity
    ]
    assert any(
        item.get("evidence_scope") == "final_deployment_recommendation"
        for item in mutated["required_next_evidence"]["fpga"]
    )

    validation = validate_dft_hardware_deployment_recommendation_readiness(mutated)

    assert validation["valid"] is False
    assert "fpga_final_evidence_not_mirrored_in_required_next_evidence" in validation["errors"]
def test_deployment_readiness_surfaces_full_scf_closure_workplan_directly(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _seed_full_scf_comparison(run_dir, passed=False)

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    gate = payload["full_scf_numerical_gate"]
    workplan = payload["full_scf_numerical_closure_workplan"]
    release_gates = payload["release_completion_gates"]

    assert payload["can_name_hardware_ppa_winners"] is True
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert gate["present"] is True
    assert gate["passed"] is False
    assert gate["row_record_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES) * 2
    assert gate["blocked_row_record_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES) * 2
    assert workplan["status"] == "full_scf_numerical_closure_required"
    assert workplan["required"] is True
    assert workplan["work_item_count"] == 2
    assert workplan["candidate_work_item_count"] == 2
    assert workplan["class_row_work_item_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES) * 2
    assert workplan["execution_allowed"] is False
    assert workplan["trusted_final_claim"] is False
    assert workplan["deliverable_complete"] is False
    assert release_gates["full_scf_numerical_passed"] is False
    assert release_gates["full_scf_numerical_closure_required"] is True
    assert release_gates["full_scf_numerical_closure_work_item_count"] == 2
    assert release_gates["full_scf_numerical_closure_class_row_work_item_count"] == len(
        STRICT_DFT_QE_WORKLOAD_CLASSES
    ) * 2
    categories = workplan["blocker_category_counts"]
    for category in (
        "scope_and_schedule",
        "host_bound_cost_accounting",
        "runtime_overhead_accounting",
        "accelerated_kernel_cost_coverage",
        "trusted_runtime_accounting_source",
        "execution_proof",
        "physical_metrics",
    ):
        assert categories[category] > 0
    assert validation["valid"] is True


def test_deployment_readiness_surfaces_trusted_full_scf_execution_queue_as_final_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _seed_full_scf_comparison(run_dir, candidate_ids=("cand-a",), passed=False)
    _seed_full_scf_trusted_queue(run_dir, candidate_id="cand-a")

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    queue = payload["full_scf_trusted_evidence_execution_queue"]

    assert payload["can_name_hardware_ppa_winners"] is True
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert queue["present"] is True
    assert queue["execution_required"] is True
    assert queue["work_item_count"] == 2
    assert queue["deployment_work_item_counts"] == {"fpga": 2, "asic": 2}
    assert queue["trusted_final_claim"] is False
    assert queue["deliverable_complete"] is False
    assert (
        payload["deployments"]["fpga"]["next_runnable_work_item_counts"][
            "full_scf_trusted_evidence_execution_queue"
        ]
        == 2
    )
    assert any(
        item.get("reason") == "full_scf_trusted_execution_queue_pending"
        and item.get("evidence_scope") == "final_deployment_recommendation"
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert any(
        item.get("reason") == "full_scf_trusted_execution_queue_pending"
        for item in payload["final_recommendation_required_next_evidence"]["asic"]
    )
    assert validation["valid"] is True


def test_deployment_readiness_full_scf_passed_gate_has_no_closure_work_items(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _seed_full_scf_comparison(run_dir, candidate_ids=("cand-a",), passed=True)

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    gate = payload["full_scf_numerical_gate"]
    workplan = payload["full_scf_numerical_closure_workplan"]
    release_gates = payload["release_completion_gates"]

    assert gate["present"] is True
    assert gate["passed"] is True
    assert release_gates["full_scf_numerical_passed"] is True
    assert release_gates["full_scf_numerical_closure_required"] is False
    assert workplan["status"] == "full_scf_numerical_closure_not_required"
    assert workplan["required"] is False
    assert workplan["work_item_count"] == 0
    assert workplan["trusted_final_claim"] is False
    assert workplan["deliverable_complete"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_deployment_readiness_blocks_contradictory_full_scf_self_assertions(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _seed_full_scf_comparison(
        run_dir,
        candidate_ids=("cand-a",),
        passed=False,
        self_asserted_status_passed=True,
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)
    gate = payload["full_scf_numerical_gate"]
    workplan = payload["full_scf_numerical_closure_workplan"]
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }

    assert gate["status"] == "passed"
    assert gate["passed"] is False
    assert payload["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    assert "row_passed_flag_not_true" in merged_blockers
    assert "candidate_passed_flag_not_true" in merged_blockers
    assert "trusted_accelerated_numeric_source_not_true" in merged_blockers
    assert validation["valid"] is True


def test_deployment_readiness_validator_rejects_full_scf_section_overclaims(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_sources(run_dir)
    _seed_full_scf_comparison(run_dir, passed=False)
    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)

    mutated = json.loads(json.dumps(payload))
    mutated["full_scf_numerical_closure_workplan"]["deliverable_complete"] = True
    mutated["full_scf_numerical_closure_workplan"]["work_items"][0]["trusted_final_claim"] = True
    mutated["release_completion_gates"]["trusted_final_claim"] = True
    mutated["release_completion_gates"]["full_scf_numerical_passed"] = True
    mutated["release_completion_gates"]["full_scf_numerical_closure_required"] = False
    mutated["full_scf_numerical_gate"]["passed"] = True
    mutated["full_scf_numerical_gate"]["comparison_artifact_passed"] = False

    validation = validate_dft_hardware_deployment_recommendation_readiness(mutated)

    assert validation["valid"] is False
    assert "full_scf_numerical_closure_workplan: must not set deliverable_complete true" in validation["errors"]
    assert "full_scf_numerical_closure_workplan.work_items[0]: must not set trusted_final_claim true" in validation["errors"]
    assert "release_completion_gates: must not set trusted_final_claim true" in validation["errors"]
    assert "full_scf_numerical_gate: passed requires comparison_artifact_passed true" in validation["errors"]
    assert (
        "release_completion_gates: full_scf_numerical_closure_required false conflicts with required workplan"
        in validation["errors"]
    )


def test_deployment_readiness_blocks_dc_only_fpga_and_vivado_only_asic_ppa_rows_before_winner_naming(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_closed_workplan(run_dir)
    _seed_ready_winner_resolution(run_dir)
    _seed_queue(run_dir, empty=True)
    _seed_target_scoped_ppa_ranking(
        run_dir,
        fpga_identity_target="asic",
        asic_identity_target="fpga",
        fpga_stage_target="asic",
        asic_stage_target="fpga",
    )
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
                {"tool": "dc_shell", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_recommendation_readiness(run_dir)
    validation = validate_dft_hardware_deployment_recommendation_readiness(payload)

    assert payload["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert payload["can_name_hardware_ppa_winners"] is False
    assert payload["deployments"]["fpga"]["can_name_hardware_ppa_winner"] is False
    assert payload["deployments"]["asic"]["can_name_hardware_ppa_winner"] is False
    assert payload["deployments"]["fpga"]["target_ppa_ranking"]["ready"] is False
    assert payload["deployments"]["asic"]["target_ppa_ranking"]["ready"] is False
    fpga_blockers = {
        blocker["blocker_id"]
        for blocker in payload["deployments"]["fpga"]["blockers"]
    }
    asic_blockers = {
        blocker["blocker_id"]
        for blocker in payload["deployments"]["asic"]["blockers"]
    }
    assert "target_ppa_ranking_rows_not_target_scoped" in fpga_blockers
    assert "target_ppa_ranking_rows_not_target_scoped" in asic_blockers
    assert any(
        item.get("reason") == "target_ppa_ranking_rows_not_target_scoped"
        and "DC-only evidence used for FPGA deployment claims" in item.get("forbidden_shortcuts", [])
        for item in payload["required_next_evidence"]["fpga"]
    )
    assert validation["valid"] is True
