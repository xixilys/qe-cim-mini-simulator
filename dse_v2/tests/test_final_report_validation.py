#!/usr/bin/env python3
"""Regression tests for generic DSE final report claim gating."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dse_v2.reference_workloads.dft_architecture_winner_resolution import (
    write_dft_architecture_winner_resolution,
)
from dse_v2.reference_workloads.dft_hardware_deployment_recommendation_readiness import (
    write_dft_hardware_deployment_recommendation_readiness,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
    build_full_scf_evaluated_hybrid_payload,
    write_full_scf_evaluated_hybrid_artifacts,
)
from dse_v2.reference_workloads.dft_scf_six_class_suite import REQUIRED_DFT_SCF_CLASS_IDS
from dse_v2.reporting.final_report import (
    generate_final_report,
    generate_final_report_artifacts,
    validate_report_claims,
    write_step5_report_artifacts,
)
from dse_v2.reporting.complete_dse_claims import write_complete_dse_reporting_package
from dse_v2.scripts.dse.audit_dft_scf_hardware_dse_goal_completion import (
    build_dft_scf_hardware_goal_completion_audit,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hashed_source_ref(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "hash_algorithm": "sha256",
    }


def _target_scoped_ppa_row(
    *,
    candidate_id: str,
    deployment: str,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "rank": 1,
        "ranking_target": deployment,
        "target_required_stage_ids": [
            "golden_correctness",
            "hls_or_rtl_sim",
            "hls_or_rtl_synth",
            "vivado_fpga_synth_or_impl"
            if deployment == "fpga"
            else "dc_asic_synth_timing_area",
        ],
        "ranking_eligible": True,
        "candidate_gate_passed": True,
        "target_specific_blockers": [],
        "candidate_identity": {
            "candidate_id": candidate_id,
            "deployment_boundary": {"accelerated_kernels": ["fft_ifft_ffft"]},
            "host_device_partition": {
                "accelerated_node_ids": ["fft_ifft_ffft"],
                "cpu_retained_node_ids": ["scf_control"],
            },
            "architecture_template_parameters": {"template_id": f"{deployment}_template"},
            "mapping_layout": {"layout_id": "layout-a"},
            "runtime_co_scheduling": {"policy_id": "overlap_dma_compute"},
            "descriptor_granularity": {"granularity": "kernel_descriptor"},
            "fallback_policy": {"policy_id": "cpu_fallback"},
            "target_platform": {"deployment_target": deployment},
        },
    }


def _target_selection_trust_gates() -> dict[str, object]:
    return {
        "schema_version": (
            "dse.dft.hardware_deployment_recommendation_readiness."
            "target_selection_trust_gates.v1"
        ),
        "present": True,
        "all_trusted": True,
        "gates": {
            "fpga_target_catalog": {
                "trust_class": "fpga_target_catalog",
                "trusted": True,
                "source_ref_count": 1,
                "blockers": [],
            },
            "asic_target_library_probe": {
                "trust_class": "asic_target_library_probe",
                "trusted": True,
                "source_ref_count": 1,
                "blockers": [],
            },
        },
        "claim_boundary": "target trust gates are audit inputs only",
    }


def _attach_target_selection_input_trust_gates(run_dir: Path) -> None:
    target_selection_path = run_dir / "dft_hardware_deployment_target_selection.json"
    target_selection = json.loads(target_selection_path.read_text(encoding="utf-8"))
    target_selection["input_trust_gates"] = _target_selection_trust_gates()["gates"]
    _write_json(target_selection_path, target_selection)


def _seed_ready_deployment_recommendation_inputs(run_dir: Path) -> None:
    fpga_catalog_probe = run_dir / "fpga_catalog_probe.json"
    dc_library_probe = run_dir / "dc_library_probe.json"
    _write_json(
        fpga_catalog_probe,
        {"schema_version": "test.fpga_catalog_probe.v1", "targets": ["part_from_catalog"]},
    )
    _write_json(
        dc_library_probe,
        {
            "schema_version": "test.dc_library_probe.v1",
            "target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "release_id": "release-final-report-target-selection-test",
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
                for stage_id in (
                    "golden_correctness",
                    "hls_or_rtl_sim",
                    "hls_or_rtl_synth",
                    "vivado_fpga_synth_or_impl",
                    "dc_asic_synth_timing_area",
                )
            ],
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan_validation.json",
        {"schema_version": "dse.dft.hardware_completion_workplan_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "no_tie_breaker_work_items",
            "work_item_count": 0,
            "work_items": [],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json",
        {"schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "resolved_hardware_ppa_deployment_winners",
            "release_id": "release-final-report-target-selection-test",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "hardware_winner_resolution_eligible": True,
            "deliverable_complete": False,
            "deployments": {
                "fpga": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "top_rank_candidate_count": 1,
                    "top_rank_design_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "winner": {
                        "candidate_id": "cand-a",
                        "rank": 1,
                        "deployment": "fpga",
                        "metrics": {},
                        "trusted_final_claim": False,
                        "deliverable_complete": False,
                    },
                    "required_next_evidence": [],
                },
                "asic": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "top_rank_candidate_count": 1,
                    "top_rank_design_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "winner": {
                        "candidate_id": "cand-a",
                        "rank": 1,
                        "deployment": "asic",
                        "metrics": {},
                        "trusted_final_claim": False,
                        "deliverable_complete": False,
                    },
                    "required_next_evidence": [],
                },
            },
            "blockers": [],
            "blocker_count": 0,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "fpga_ranking": [_target_scoped_ppa_row(candidate_id="cand-a", deployment="fpga")],
            "asic_ranking": [_target_scoped_ppa_row(candidate_id="cand-a", deployment="asic")],
            "deliverable_complete": False,
            "trusted_final_claim": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
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
    _write_json(
        run_dir / "dft_hardware_deployment_target_selection.json",
        {
            "schema_version": "dse.dft.hardware_deployment_target_selection.v1",
            "status": "target_selection_ready",
            "budget_policy": "unbounded_budget_current_catalog_required",
            "deployments": {
                "fpga": {
                    "selection_status": "selected",
                    "target_device_id": "fpga_unbounded_budget_test",
                    "vendor": "vendor_from_catalog",
                    "part": "part_from_catalog",
                    "family": "family_from_catalog",
                    "capacity": {"slice_luts": 1_000_000, "dsps": 8_000},
                    "source_refs": [_hashed_source_ref(fpga_catalog_probe)],
                },
                "asic": {
                    "selection_status": "selected",
                    "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                    "process_node": "library_defined",
                    "pvt_corner": "tt_1p8v_25c",
                    "voltage_v": 1.8,
                    "temperature_c": 25,
                    "source_refs": [_hashed_source_ref(dc_library_probe)],
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


def _seed_blocked_full_scf_numerical_rows(run_dir: Path) -> None:
    blockers = [
        "accelerated_kernel_costs_s_missing",
        "comparison_scope_not_full_scf_host_accelerator_end_to_end",
        "full_scf_schedule_consumed_not_true",
        "host_accelerator_end_to_end_not_true",
        "host_bound_costs_included_not_true",
        "host_bound_costs_s_missing",
        "major_accelerated_kernels_not_all_covered",
        "required_physical_metric_missing::density_residual",
        "required_physical_metric_missing::total_energy_error_ry",
        "row_missing_passed_execution_proof",
        "row_status_not_passed",
        "row_untrusted_runtime_source:missing",
        "runtime_overhead_costs_s_missing",
        "trusted_accelerated_numeric_source_not_true",
    ]
    row_records = []
    candidate_records = []
    for candidate_id, class_id in (
        ("cand-fpga", "gamma_only_supercell_scf"),
        ("cand-asic", "insulator_scf"),
    ):
        row_records.append({
            "candidate_id": candidate_id,
            "class_id": class_id,
            "status": "blocked_temporary",
            "passed": False,
            "comparison_scope": None,
            "full_scf_schedule_consumed": False,
            "host_accelerator_end_to_end": False,
            "host_bound_costs_included": False,
            "host_bound_costs_s": {},
            "runtime_overhead_costs_s": {},
            "accelerated_kernel_costs_s": {},
            "covered_accelerated_kernel_ids": [],
            "missing_accelerated_kernel_ids": [
                "fft_ifft_ffft",
                "transpose_layout_conversion",
            ],
            "trusted_accelerated_numeric_source": False,
            "execution_proof_present": False,
            "measurement_source": "",
            "metric_checks": [],
            "row_evidence_root": "full_scf_numerical_rows",
            "artifact_ref": {
                "exists": True,
                "path": (
                    "full_scf_numerical_rows/"
                    f"{candidate_id}/{class_id}/full_scf_end_to_end_numerical_evidence.json"
                ),
            },
            "blockers": blockers,
        })
        candidate_records.append({
            "candidate_id": candidate_id,
            "status": "blocked_temporary",
            "passed": False,
            "strict_scf_class_ids": [class_id],
            "missing_strict_scf_class_ids": [],
            "covered_accelerated_kernel_ids": [],
            "missing_accelerated_kernel_ids": [
                "fft_ifft_ffft",
                "transpose_layout_conversion",
            ],
            "trusted_accelerated_numeric_source": False,
            "host_accelerator_end_to_end": False,
            "comparison_scope": None,
            "blockers": [f"{class_id}::{blocker}" for blocker in blockers]
            + ["not_all_strict_scf_rows_passed"],
        })
    _write_json(
        run_dir / "full_scf_end_to_end_comparison.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
            "status": "blocked_temporary",
            "passed": False,
            "candidate_ids": ["cand-fpga", "cand-asic"],
            "candidate_count": 2,
            "passed_candidate_count": 0,
            "blocked_candidate_count": 2,
            "row_record_count": 2,
            "passed_row_record_count": 0,
            "blocked_row_record_count": 2,
            "blocker_count": 1,
            "blockers": ["not_all_legal_candidates_passed_full_scf_comparison"],
            "strict_scf_class_ids": [
                "gamma_only_supercell_scf",
                "insulator_scf",
            ],
            "candidate_records": candidate_records,
            "row_records": row_records,
            "trusted_accelerated_numeric_source": False,
            "claim_boundary": "blocked full-SCF numerical fixture",
        },
    )


def _seed_passed_full_scf_numerical_gate(run_dir: Path) -> None:
    row_records = []
    candidate_records = []
    for candidate_id in ("cand-fpga", "cand-asic"):
        for class_id in REQUIRED_DFT_SCF_CLASS_IDS:
            row_records.append({
                "candidate_id": candidate_id,
                "class_id": class_id,
                "status": "passed",
                "passed": True,
                "comparison_scope": "full_scf_host_accelerator_end_to_end",
                "full_scf_schedule_consumed": True,
                "host_accelerator_end_to_end": True,
                "host_bound_costs_included": True,
                "host_bound_costs_s": {"scf_control": 1.0},
                "runtime_overhead_costs_s": {"dma": 0.1},
                "accelerated_kernel_costs_s": {"fft_ifft_ffft": 0.2},
                "covered_accelerated_kernel_ids": ["fft_ifft_ffft"],
                "missing_accelerated_kernel_ids": [],
                "trusted_accelerated_numeric_source": True,
                "execution_proof_present": True,
                "measurement_source": "qe_full_scf_host_accelerator_runtime",
                "measurement_source_kind": "qe_full_scf_host_accelerator_runtime",
                "metric_checks": [
                    {"metric": "density_residual", "passed": True},
                    {"metric": "total_energy_error_ry", "passed": True},
                ],
                "blockers": [],
            })
        candidate_records.append({
            "candidate_id": candidate_id,
            "status": "passed",
            "passed": True,
            "strict_scf_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "missing_strict_scf_class_ids": [],
            "covered_accelerated_kernel_ids": ["fft_ifft_ffft"],
            "missing_accelerated_kernel_ids": [],
            "trusted_accelerated_numeric_source": True,
            "host_accelerator_end_to_end": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "blockers": [],
        })
    payload = {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
            "status": "passed",
            "passed": True,
            "candidate_ids": ["cand-fpga", "cand-asic"],
            "candidate_count": 2,
            "passed_candidate_count": 2,
            "blocked_candidate_count": 0,
            "row_record_count": len(row_records),
            "passed_row_record_count": len(row_records),
            "blocked_row_record_count": 0,
            "blocker_count": 0,
            "blockers": [],
            "strict_scf_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "candidate_records": candidate_records,
            "row_records": row_records,
            "trusted_accelerated_numeric_source": True,
            "claim_boundary": "passed full-SCF numerical fixture",
    }
    _write_json(
        run_dir / "full_scf_end_to_end_comparison.json",
        payload,
    )
    _write_json(
        run_dir / "full_scf_end_to_end_comparison_validation.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_validation.v1",
            "status": "passed",
            "passed": True,
            "valid": True,
            "errors": [],
            "candidate_count": payload["candidate_count"],
            "row_record_count": payload["row_record_count"],
        },
    )
    _write_json(
        run_dir / "full_scf_end_to_end_comparison_status.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison_status.v1",
            "status": "comparison_passed",
            "comparison_status": "passed",
            "comparison_passed": True,
            "validation_status": "passed",
            "validation_passed": True,
            "candidate_count": payload["candidate_count"],
            "row_record_count": payload["row_record_count"],
            "blocked_candidate_count": payload["blocked_candidate_count"],
            "blocked_row_record_count": payload["blocked_row_record_count"],
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
    )


def _seed_minimal_trusted_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    required = [
        "manifest.json",
        "artifact_manifest.json",
        "verdict.json",
        "design_point.json",
        "architecture.json",
        "mapping.json",
        "workload_package.json",
        "workload_graph.json",
        "graph_lowering_report.json",
        "simulation_request.json",
        "simulation_result.json",
        "numerical_validation.json",
        "phase_breakdown.csv",
        "resource_summary.csv",
        "data_movement_summary.csv",
        "systemc_stdout.log",
        "systemc_stderr.log",
        "gem5_systemc_blockers.json",
    ]
    _write_json(run_dir / "manifest.json", {
        "schema_version": "dse.manifest.v1",
        "run_id": "trusted_run",
        "workload": "sparse_profile",
        "workload_family": "sparse_la",
        "workload_profile": "sparse_la",
        "workload_importer": "generic_json",
        "backend": "systemc",
        "evidence_mode": "debug",
        "cli_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
        "simulator_command": ["generic_sim"],
        "replay_metadata": {
            "python_replay_command": ["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"],
            "simulator_replay_command": ["generic_sim"],
        },
        "required_evidence_files": required,
    })
    _write_json(run_dir / "artifact_manifest.json", {"schema_version": "dse.artifact_manifest.v1", "artifacts": []})
    _write_json(run_dir / "verdict.json", {
        "schema_version": "dse.verdict.v1",
        "run_id": "trusted_run",
        "backend": "systemc",
        "evidence_mode": "debug",
        "trusted_for_final_ranking": True,
        "numerical_validation_passed": True,
        "numerical_validation_scope": "generic_systemc_timing_numeric_reference",
        "numerical_error_metrics": {"failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        "required_coverage": ["load_csr", "spmv", "norm"],
        "missing_required_coverage": [],
        "gem5_systemc_blockers": [
            {"id": "gem5_systemc_binding", "detail": "L4 binding is blocked in this run."}
        ],
        "evidence_gaps": ["gem5+SystemC path remains blocked."],
    })
    _write_json(run_dir / "design_point.json", {"design_point_id": "trusted_run"})
    _write_json(run_dir / "architecture.json", {
        "architecture_id": "arch-1",
        "architecture_family": "generic_heterogeneous_pilot",
        "status": "implemented",
        "trusted_final_eligible": True,
    })
    _write_json(run_dir / "mapping.json", {
        "mapping_id": "mapping-1",
        "mapping_policy": "seeded",
        "search_status": "single_candidate",
    })
    _write_json(run_dir / "workload_package.json", {
        "schema_version": "dse.workload_package.v1",
        "workload_id": "sparse_profile",
        "workload_family": "sparse_la",
        "source": {"kind": "generated", "provenance": "test"},
        "profile": {"profile_id": "sparse_la", "profile_version": "v1", "required_coverage": ["load_csr", "spmv", "norm"]},
        "importer": {"importer_id": "generic_json", "importer_version": "v1", "claim_boundary": "full_workload"},
        "graph": {"graph_id": "sparse_profile", "nodes": {"load_csr": {}, "spmv": {}, "norm": {}}, "edges": []},
        "constraints": {},
        "calibration": {},
        "domain_metadata": {},
    })
    _write_json(run_dir / "workload_graph.json", {"graph_id": "sparse_profile", "nodes": {"load_csr": {}, "spmv": {}, "norm": {}}, "edges": []})
    _write_json(run_dir / "graph_lowering_report.json", {
        "schema_version": "dse.graph_lowering_report.v1",
        "source_graph_id": "sparse_profile",
        "executable_graph_id": "sparse_profile.lowered",
        "status": "lowered",
        "full_workload_eligible": True,
        "unsupported_constructs": [],
    })
    _write_json(run_dir / "simulation_request.json", {"run_id": "trusted_run"})
    _write_json(run_dir / "simulation_result.json", {
        "status": "passed",
        "backend": "systemc",
        "metrics": {"latency_ms": 3.0, "power_w": 5.0, "energy_j": 0.015},
        "numerical_validation": {
            "artifact": "numerical_validation.json",
            "status": "pass",
            "passed": True,
            "scope": "generic_systemc_timing_numeric_reference",
            "summary": {"failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        },
    })
    _write_json(run_dir / "numerical_validation.json", {
        "schema_version": "dse.numerical_validation.v1",
        "status": "pass",
        "passed": True,
        "scope": "generic_systemc_timing_numeric_reference",
        "profile_domain_correctness_claimed": False,
        "domain_correctness_boundary": "Validates timing-level numeric outputs only.",
        "summary": {"check_count": 4, "failed_check_count": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
        "checks": [],
    })
    (run_dir / "phase_breakdown.csv").write_text(
        "phase,node_id,op_type,device,start_ns,end_ns,latency_ns,latency_ms,cycles_estimate,clock_mhz,status,unavailable_reason\n"
        "load_csr,load_csr,dma_load,fpga-0,0,1000000,1000000,1.0,250000,250,available,\n"
        "spmv,spmv,spmv,fpga-0,1000000,2500000,1500000,1.5,375000,250,available,\n"
        "norm,norm,reduction,fpga-0,2500000,3000000,500000,0.5,125000,250,available,\n",
        encoding="utf-8",
    )
    (run_dir / "resource_summary.csv").write_text("device,compute_percent\ngpu-0,80\n", encoding="utf-8")
    (run_dir / "data_movement_summary.csv").write_text("edge_id,status\n", encoding="utf-8")
    (run_dir / "systemc_stdout.log").write_text("", encoding="utf-8")
    (run_dir / "systemc_stderr.log").write_text("", encoding="utf-8")
    _write_json(run_dir / "gem5_systemc_blockers.json", {"blockers": ["gem5_systemc_binding"]})


def _downgrade_to_hardware_ppa_only_run(run_dir: Path) -> None:
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})


def _hardware_ppa_row(candidate_id: str, *, rank: int, lut: int, area: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "design_candidate_id": f"design-{candidate_id}",
        "identity_assignments": {
            "hardware_microarchitecture": "host_fpga_minimal_v0",
            "mapping_data_layout": "fft_grid_hbm_tiled",
        },
        "non_identity_assignments": {
            "dft_phase_hotspot_selection": "scf_hpsi_density",
            "evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder",
        },
        "rank": rank,
        "tie_key": [lut, 2, 1, 12],
        "fpga_total_slice_luts": lut,
        "fpga_total_dsps": 2,
        "fpga_total_block_ram_tiles": 1,
        "fpga_total_bonded_iob": 12,
        "vivado_route_completed_kernel_count": 8,
        "asic_total_cell_area": area,
        "asic_min_slack_ns": 0.5,
        "asic_slack_deficit_ns": 0.0,
        "dc_real_target_library_kernel_count": 8,
        "kernel_count": 8,
    }


def _seed_resolved_hardware_ppa_winner_artifacts(run_dir: Path) -> None:
    fpga_winner = _hardware_ppa_row("cand-fpga", rank=1, lut=100, area=2000.0)
    fpga_runner_up = _hardware_ppa_row("cand-asic", rank=2, lut=180, area=1000.0)
    asic_winner = _hardware_ppa_row("cand-asic", rank=1, lut=180, area=1000.0)
    asic_runner_up = _hardware_ppa_row("cand-fpga", rank=2, lut=100, area=2000.0)
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "release_id": "release-ppa",
            "candidate_count": 2,
            "major_kernel_count": 8,
            "ranking_eligible_candidate_count": 2,
            "blocked_candidate_count": 0,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "winner_selection_status": "ranked_candidates_available",
            "all_candidates_metric_tied": False,
            "metric_signature_count": 2,
            "source_artifacts": {
                "candidate_universe_manifest": {
                    "exists": True,
                    "path": str(run_dir / "candidate_universe_manifest.json"),
                    "sha256": "fixture-candidate-universe",
                }
            },
            "fpga_ranking": [fpga_winner, fpga_runner_up],
            "asic_ranking": [asic_winner, asic_runner_up],
            "ranking_policy": {"candidate_specific_metrics_required": True},
            "claim_boundary": "hardware PPA only",
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_pareto_frontier.json",
        {
            "schema_version": "dse.dft.hardware_ppa_pareto_frontier.v1",
            "pareto_candidate_count": 2,
            "pareto_alternatives": [fpga_winner, asic_winner],
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_status.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking_status.v1",
            "status": "passed",
            "ranking_status": "trusted_hardware_ppa_ranking_available",
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit.v1",
            "status": "trusted_candidate_specific_ppa_provenance",
            "winner_provenance_eligible": True,
            "candidate_count": 2,
            "major_kernel_count": 8,
            "unit_count": 16,
            "trusted_unit_count": 16,
            "blocked_unit_count": 0,
            "trusted_stage_count": 80,
            "blocked_stage_count": 0,
            "blocker_count": 0,
            "blocker_id_counts": {},
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "provenance test fixture",
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json",
        {"schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_status.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_status.v1",
            "status": "passed",
            "winner_provenance_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "no_fresh_candidate_specific_ppa_execution_required",
            "work_item_count": 0,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    write_dft_architecture_winner_resolution(run_dir)


def _seed_deployment_decision_support_artifacts(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_fpga_asic_deployment_summary.json",
        {
            "schema_version": "dse.dft.fpga_asic_deployment_summary.v1",
            "status": "resolved_best_deployment",
            "hardware_winner_resolution_eligible": True,
            "trusted_best_architecture_claim_eligible": True,
            "best_deployment_claim_eligible": True,
            "deliverable_complete": False,
            "fpga": {
                "deployment": "fpga",
                "status": "recommended_with_bound_target",
                "best_candidate_id": "cand-fpga",
                "best_design_candidate_id": "design-cand-fpga",
                "equivalent_top_candidate_ids": ["cand-fpga"],
                "metrics": {"fpga_total_slice_luts": 100, "vivado_route_completed_kernel_count": 8},
            },
            "asic": {
                "deployment": "asic",
                "status": "recommended_with_bound_target",
                "best_candidate_id": "cand-asic",
                "best_design_candidate_id": "design-cand-asic",
                "equivalent_top_candidate_ids": ["cand-asic"],
                "metrics": {"asic_total_cell_area": 1000.0, "dc_real_target_library_kernel_count": 8},
            },
            "claim_boundary": "hardware-PPA deployment summary only",
        },
    )
    _write_json(
        run_dir / "dft_fpga_asic_deployment_summary_validation.json",
        {"schema_version": "dse.dft.fpga_asic_deployment_summary_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_fpga_asic_deployment_summary_status.json",
        {
            "schema_version": "dse.dft.fpga_asic_deployment_summary_status.v1",
            "status": "passed",
            "best_deployment_claim_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_feasibility.json",
        {
            "schema_version": "dse.dft.deployment_target_feasibility.v1",
            "status": "target_feasibility_ready",
            "target_feasibility_ready": True,
            "deliverable_complete": False,
            "fpga_target_feasibility": {
                "status": "raw_package_feasible_target_selected",
                "selected_device": "xc7a35tcsg324-1",
                "selected_part": "XCVU19P",
                "selected_package": "A3824-class raw package",
                "resource_fit": True,
            },
            "asic_target_binding": {
                "status": "bound_from_dc_kernel_row_consensus",
                "selected_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                "target_binding_claim_eligible": True,
            },
            "claim_boundary": "target feasibility only",
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_feasibility_validation.json",
        {"schema_version": "dse.dft.deployment_target_feasibility_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_deployment_target_feasibility_status.json",
        {
            "schema_version": "dse.dft.deployment_target_feasibility_status.v1",
            "status": "passed",
            "target_feasibility_ready": True,
        },
    )
    _write_json(
        run_dir / "full_scf_end_to_end_comparison.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
            "status": "blocked_temporary",
            "passed": False,
            "candidate_count": 36,
            "blocked_candidate_count": 36,
            "blocked_row_record_count": 216,
            "blocker_count": 1,
            "blockers": ["not_all_legal_candidates_passed_full_scf_comparison"],
            "strict_scf_class_ids": [
                "small_multi_k_scf",
                "metal_smearing_scf",
                "insulator_scf",
                "slab_vacuum_large_fft_scf",
                "gamma_only_supercell_scf",
                "projector_orthogonalization_heavy_scf",
            ],
            "candidate_blocker_category_histogram": {
                "host_bound_cost_accounting": 216,
                "runtime_overhead_accounting": 216,
            },
            "trusted_accelerated_numeric_source": False,
        },
    )
    _write_json(
        run_dir / "numerical_correctness_evidence.json",
        {
            "schema_version": "dse.dft.numerical_correctness_evidence.v1",
            "status": "blocked_temporary",
            "candidate_count": 36,
        },
    )
    _write_json(
        run_dir / "dft_scf_hardware_goal_completion_audit_current.json",
        {
            "schema_version": "dse.dft_scf_hardware.goal_completion_audit.v1",
            "status": "in_progress",
            "completion_decision": "do_not_mark_complete_before_date_horizon",
            "horizon_reached": False,
            "deliverable_completion_blockers": [
                {"blocker_id": "release_claim_gate_deliverable_complete_false"}
            ],
            "hardware_eligibility_blockers": [],
            "summary": {"deliverable_complete": False},
        },
    )
    _write_json(
        run_dir / "dft_scf_hardware_dse_goal_audit_current.json",
        {
            "schema_version": "dse.dft_scf_hardware.goal_completion_audit.v1",
            "status": "in_progress",
            "completion_decision": "do_not_mark_complete_before_date_horizon",
            "horizon_reached": False,
            "deliverable_completion_blockers": [
                {"blocker_id": "release_claim_gate_deliverable_complete_false"}
            ],
            "hardware_eligibility_blockers": [
                {
                    "blocker_id": "release_gate_candidate_set_does_not_match_candidate_binding_map",
                    "release_gate_only_candidate_ids": ["cand-extra"],
                    "binding_map_only_candidate_ids": [],
                }
            ],
            "summary": {"hardware_completion_eligible": False, "deliverable_complete": False},
        },
    )
    _write_json(
        run_dir / "status.json",
        {
            "schema_version": "dse.dft.candidate_evidence_artifact_status.v1",
            "status": "passed",
            "claim_status": "partial_mvp_blocked_for_deliverable",
        },
    )
    _write_json(
        run_dir / "blocker_report.json",
        {
            "schema_version": "dse.dft.blocker_report.v1",
            "status": "blocked_temporary",
            "blocked_fields": ["numerical_status"],
            "blocked_candidate_count": 36,
        },
    )
    _write_json(
        run_dir / "dft_deployment_coordination_summary.json",
        {
            "schema_version": "dse.dft.deployment_coordination_summary.v1",
            "status": "coordinated_current_best_with_open_release_blockers",
            "deployment_recommendations": {
                "fpga": {
                    "deployment": "fpga",
                    "status": "recommended_with_bound_target",
                    "best_candidate_id": "cand-fpga",
                    "best_design_candidate_id": "design-cand-fpga",
                    "selected_device": "xc7a35tcsg324-1",
                    "target_feasibility_status": "raw_package_feasible_target_selected",
                    "fpga_selected_part": "XCVU19P",
                    "fpga_selected_package": "A3824-class raw package",
                    "metrics": {"fpga_total_slice_luts": 100, "vivado_route_completed_kernel_count": 8},
                    "targeted_kernel_count": 8,
                    "expected_kernel_count": 8,
                    "blocker_count": 0,
                    "blockers": [],
                },
                "asic": {
                    "deployment": "asic",
                    "status": "recommended_with_bound_target",
                    "best_candidate_id": "cand-asic",
                    "best_design_candidate_id": "design-cand-asic",
                    "selected_device": "fsa0a_c_generic_core_tt1p8v25c",
                    "target_feasibility_status": "bound_from_dc_kernel_row_consensus",
                    "metrics": {"asic_total_cell_area": 1000.0, "dc_real_target_library_kernel_count": 8},
                    "targeted_kernel_count": 8,
                    "expected_kernel_count": 8,
                    "blocker_count": 0,
                    "blockers": [],
                },
            },
            "current_best_available": True,
            "target_feasibility_ready": True,
            "best_deployment_claim_eligible": True,
            "release_completion_eligible": False,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "goal_audit_status": "in_progress",
            "coordination_blocker_count": 1,
            "coordination_blockers": [
                {"blocker_id": "full_goal_audit_not_complete", "goal_audit_status": "in_progress"}
            ],
            "recommended_next_actions": [
                "Close full-SCF host+accelerator numerical evidence before final claims."
            ],
            "claim_boundary": "decision-support only",
        },
    )
    _write_json(
        run_dir / "dft_deployment_coordination_summary_validation.json",
        {"schema_version": "dse.dft.deployment_coordination_summary_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_deployment_coordination_summary_status.json",
        {
            "schema_version": "dse.dft.deployment_coordination_summary_status.v1",
            "status": "passed",
            "coordination_status": "coordinated_current_best_with_open_release_blockers",
            "coordination_blocker_count": 1,
        },
    )


def _seed_matching_candidate_set_consistency_artifact(run_dir: Path) -> None:
    candidate_ids = ["cand-asic", "cand-fpga"]
    candidate_sets = {
        source: {
            "present": True,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "raw_candidate_ids": candidate_ids,
            "duplicate_candidate_ids": [],
        }
        for source in ("release_gate", "binding_map", "trial_ledger")
    }
    _write_json(
        run_dir / "dft_candidate_set_consistency.json",
        {
            "schema_version": "dse.dft.candidate_set_consistency.v1",
            "status": "passed",
            "candidate_set_consistency_status": "candidate_sets_match",
            "required_sources": ["release_gate", "binding_map", "trial_ledger"],
            "candidate_sets": candidate_sets,
            "required_source_count": 3,
            "present_source_count": 3,
            "missing_sources": [],
            "empty_sources": [],
            "duplicate_sources": [],
            "all_required_sources_present": True,
            "all_sources_nonempty": True,
            "all_required_sources_match_and_nonempty": True,
            "union_candidate_count": len(candidate_ids),
            "union_candidate_ids": candidate_ids,
            "common_candidate_count": len(candidate_ids),
            "common_candidate_ids": candidate_ids,
            "source_only_candidate_ids": {"release_gate": [], "binding_map": [], "trial_ledger": []},
            "source_missing_candidate_ids": {"release_gate": [], "binding_map": [], "trial_ledger": []},
            "release_gate_only_candidate_ids": [],
            "binding_map_only_candidate_ids": [],
            "trial_ledger_only_candidate_ids": [],
            "release_gate_missing_candidate_ids": [],
            "binding_map_missing_candidate_ids": [],
            "trial_ledger_missing_candidate_ids": [],
            "pairwise_mismatch_count": 0,
            "pairwise_mismatches": [],
            "blocker_count": 0,
            "blockers": [],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_set_consistency_validation.json",
        {
            "schema_version": "dse.dft.candidate_set_consistency_validation.v1",
            "valid": True,
            "status": "passed",
            "candidate_set_consistency_status": "candidate_sets_match",
            "errors": [],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_set_consistency_status.json",
        {
            "schema_version": "dse.dft.candidate_set_consistency_status.v1",
            "status": "passed",
            "validation_status": "passed",
            "artifact_validation_valid": True,
            "candidate_set_consistency_passed": True,
            "consistency_result": "passed",
            "candidate_set_consistency_status": "candidate_sets_match",
            "deliverable_complete": False,
        },
    )


def _seed_full_scf_candidate_ids(run_dir: Path, candidate_ids: list[str]) -> None:
    full_scf_path = run_dir / "full_scf_end_to_end_comparison.json"
    payload = (
        json.loads(full_scf_path.read_text(encoding="utf-8"))
        if full_scf_path.exists()
        else {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_comparison.v1",
            "status": "blocked_temporary",
            "passed": False,
        }
    )
    payload["candidate_ids"] = candidate_ids
    payload["candidate_count"] = len(candidate_ids)
    payload["candidate_records"] = [
        {"candidate_id": candidate_id, "passed": False}
        for candidate_id in candidate_ids
    ]
    _write_json(full_scf_path, payload)


def _rewrite_fpga_target_to_consistent_vu19p(run_dir: Path) -> None:
    target_path = run_dir / "dft_deployment_target_feasibility.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    target["fpga_target_feasibility"]["selected_device"] = "VU19P"
    target["fpga_target_feasibility"]["selected_part"] = "XCVU19P"
    _write_json(target_path, target)

    coordination_path = run_dir / "dft_deployment_coordination_summary.json"
    coordination = json.loads(coordination_path.read_text(encoding="utf-8"))
    coordination["deployment_recommendations"]["fpga"]["selected_device"] = "VU19P"
    coordination["deployment_recommendations"]["fpga"]["fpga_selected_part"] = "XCVU19P"
    _write_json(coordination_path, coordination)


def _inject_winner_resolution_fpga_target(
    run_dir: Path,
    *,
    selected_target: str = "xc7a35tcsg324-1",
) -> None:
    winner_path = run_dir / "dft_architecture_winner_resolution.json"
    winner = json.loads(winner_path.read_text(encoding="utf-8"))
    winner["fpga_best_architecture"]["deployment_target_evidence"] = {
        "schema_version": "dse.dft.deployment_target_evidence.v1",
        "deployment": "fpga",
        "candidate_id": winner["fpga_best_architecture"]["candidate_id"],
        "status": "resolved_from_kernel_row_evidence",
        "selected_target": selected_target,
        "all_major_kernel_consistency": True,
        "observed_kernel_count": 8,
        "expected_kernel_count": 8,
        "targeted_kernel_count": 8,
        "blocker_count": 0,
        "blockers": [],
        "claim_boundary": "winner-resolution target evidence only",
    }
    _write_json(winner_path, winner)


def _audit_current_final_report(run_dir: Path) -> dict:
    return build_dft_scf_hardware_goal_completion_audit(
        final_report=run_dir / "final_report.json",
        now=datetime(2026, 6, 1, 12, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def test_final_report_artifacts_validate_trusted_claims(tmp_path):
    run_dir = tmp_path / "trusted_run"
    _seed_minimal_trusted_run(run_dir)

    result = generate_final_report_artifacts(run_dir)

    assert result["validation_passed"] is True
    assert result["trusted_claim_count"] == 3
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "claim_validation.json").read_text(encoding="utf-8"))
    assert report["selected_recommendation"]["status"] == "not_selected"
    assert report["trusted_ranking"][0]["trusted_scope"].startswith("single-run feasibility")
    assert report["numerical_validation"]["passed"] is True
    assert report["workload"]["profile_id"] == "sparse_la"
    assert report["workload"]["importer_id"] == "generic_json"
    assert validation["errors"] == []
    assert (run_dir / "final_report.md").exists()


def _seed_search_admission_handoff(
    run_dir: Path,
    *,
    queue_ref: str,
    include_sidecar_scope: bool = True,
) -> None:
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )
    _write_json(
        run_dir / "campaign_evaluation_plan.json",
        {
            "schema_version": "dse.contract.v1",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "trial_id": "trial-a",
            "plan_id": "campaign_evaluation_plan::a",
            "step3_simulation_queue_ref": queue_ref,
            "selected_entry_only": True,
            "planned_entry_count": 0,
            "planned_entries": [],
            "deferred_entries": [],
            "broad_evidence_run": False,
            "admission_control": {"hidden_evidence_fanout_allowed": False},
            "trusted_final_claim": False,
            "release_completion_eligible": False,
        },
    )
    _write_json(
        run_dir / "search_iteration_plan.json",
        _valid_empty_search_iteration_plan(queue_ref),
    )
    _write_json(
        run_dir / "search_iteration_plan_validation.json",
        {
            "schema_version": "dse.step2.search_iteration_plan_validation.v1",
            "status": "passed",
            "valid": True,
            "error_count": 0,
            "errors": [],
            "trusted_final_claim": False,
        },
    )
    _write_json(
        run_dir / "campaign_search_admission_plan.json",
        {
            "schema_version": "dse.contract.v1",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "trial_id": "trial-a",
            "plan_id": "campaign_search_admission_plan::a",
            "status": "active",
            "admission_status": "proposal_only",
            "campaign_evaluation_plan_ref": "campaign_evaluation_plan.json",
            "search_iteration_plan_ref": "search_iteration_plan.json",
            "search_iteration_plan_validation_ref": "search_iteration_plan_validation.json",
            "step3_simulation_queue_ref": queue_ref,
            "admitted_entry_count": 0,
            "materialized_step3_queue_entry_count": 0,
            "materialized_step3_queue_entries": [],
            "step2_iteration_request_count": 0,
            "step2_iteration_requests": [],
            "deferred_candidate_count": 0,
            "deferred_candidates": [],
            "execution_allowed": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "hidden_evidence_fanout_allowed": False,
            "broad_evidence_run": False,
            "top_k_queue_provenance_only": True,
        },
    )
    sidecar_payload = {
        "schema_version": "dse.step3.admission_queue_validation.v1",
        "status": "passed",
        "valid": True,
        "error_count": 0,
        "errors": [],
        "trusted_final_claim": False,
    }
    if include_sidecar_scope:
        sidecar_payload["campaign_scope_validation"] = {
            "schema_version": "dse.campaign.scope_validation.v1",
            "status": "passed",
            "valid": True,
            "conflict_count": 0,
            "row_scope_error_count": 0,
            "total_scope_error_count": 0,
            "conflicts": [],
            "row_scope_errors": [],
        }
    _write_json(run_dir / "step3_admission_queue_validation.json", sidecar_payload)


def _valid_empty_search_iteration_plan(queue_ref: str) -> dict:
    return {
        "schema_version": "dse.step2.search_iteration_plan.v1",
        "campaign_id": "campaign-a",
        "workload_run_id": "workload-a",
        "trial_id": "trial-a",
        "policy_name": "test_policy",
        "problem_id": "problem-a",
        "top_k_queue_provenance_only": True,
        "hidden_evidence_fanout_allowed": False,
        "next_step3_admission_queue_ref": queue_ref,
        "step3_admission_queue": queue_ref,
        "next_candidates": [],
        "next_proposed_count": 0,
        "next_step3_admission_candidate_count": 0,
        "next_step3_admission_candidates": [],
        "next_proposal_budget": 0,
        "next_best_candidate_id": None,
        "next_checkpoint": {
            "schema_version": "dse.step2.search_checkpoint.v1",
            "policy_name": "test_policy",
            "problem_id": "problem-a",
            "candidate_count": 0,
            "proposed_count": 0,
            "proposal_budget": 0,
            "best_candidate_id": None,
            "observed_count": 0,
            "candidates": [],
        },
        "applied_feedback_count": 0,
        "input_observed_count": 0,
        "output_observed_count": 0,
        "candidate_alias_count": 0,
        "feedback_observation_routing": [],
        "feedback_observation_count": 0,
        "feedback_unresolved_observation_count": 0,
        "feedback_routing_status": "no_feedback_observations",
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    }


def _write_empty_step3_queue(run_dir: Path, queue_ref: str) -> None:
    queue_path = run_dir / queue_ref
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        queue_path,
        {
            "schema_version": "dse.step3.simulation_queue.v1",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "trial_id": "trial-a",
            "queue_mode": "complete-dse-release-universe",
            "entry_count": 0,
            "entries": [],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
        },
    )


def test_step5_recomputes_search_iteration_plan_validation_from_present_plan(tmp_path):
    run_dir = tmp_path / "stale_search_iteration_validation"
    _seed_minimal_trusted_run(run_dir)
    _seed_search_admission_handoff(
        run_dir,
        queue_ref="step2/step3_simulation_queue.json",
    )
    plan = _valid_empty_search_iteration_plan("step2/step3_simulation_queue.json")
    plan["hidden_evidence_fanout_allowed"] = True
    plan["top_k_queue_provenance_only"] = False
    _write_json(run_dir / "search_iteration_plan.json", plan)
    _write_empty_step3_queue(run_dir, "step2/step3_simulation_queue.json")

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
            "step2/step3_simulation_queue.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is False
    assert report["claim_validation"]["passed"] is False
    assert search_admission["search_iteration_plan_recomputed_validation"]["valid"] is False
    error_fields = {error["field"] for error in search_admission["errors"]}
    assert "search_iteration_plan_recomputed_validation.valid" in error_fields


def test_step5_requires_referenced_search_iteration_plan_before_trusting_sidecar(tmp_path):
    run_dir = tmp_path / "missing_referenced_search_iteration_plan"
    _seed_minimal_trusted_run(run_dir)
    _seed_search_admission_handoff(
        run_dir,
        queue_ref="step2/step3_simulation_queue.json",
    )
    (run_dir / "search_iteration_plan.json").unlink()
    _write_empty_step3_queue(run_dir, "step2/step3_simulation_queue.json")

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
            "step2/step3_simulation_queue.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is False
    assert search_admission["artifact_refs"]["search_iteration_plan.json"]["exists"] is False
    assert report["claim_validation"]["passed"] is False
    error_fields = {error["field"] for error in search_admission["errors"]}
    assert "search_iteration_plan.json" in error_fields


def test_step5_rejects_non_run_local_step3_queue_refs(tmp_path):
    run_dir = tmp_path / "search_admission_external_queue_ref"
    _seed_minimal_trusted_run(run_dir)
    external_queue = tmp_path / "external_queue.json"
    _write_json(
        external_queue,
        {
            "schema_version": "dse.step3.simulation_queue.v1",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "trial_id": "trial-a",
            "queue_mode": "complete-dse-release-universe",
            "entry_count": 0,
            "entries": [],
        },
    )
    _seed_search_admission_handoff(run_dir, queue_ref=str(external_queue))

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is False
    assert search_admission["artifact_refs"]["step3_simulation_queue.json"]["path"] is None
    assert report["claim_validation"]["passed"] is False
    error_fields = {error["field"] for error in search_admission["errors"]}
    assert "step3_simulation_queue_ref.invalid_run_local_path" in error_fields


def test_step5_rejects_parent_traversal_step3_queue_refs(tmp_path):
    run_dir = tmp_path / "search_admission_traversal_queue_ref"
    _seed_minimal_trusted_run(run_dir)
    _seed_search_admission_handoff(
        run_dir,
        queue_ref="step2_input/../../external_queue.json",
    )

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is False
    assert search_admission["artifact_refs"]["step3_simulation_queue.json"]["path"] is None
    assert report["claim_validation"]["passed"] is False
    error_fields = {error["field"] for error in search_admission["errors"]}
    assert "step3_simulation_queue_ref.invalid_run_local_path" in error_fields


def test_step5_reports_missing_referenced_queue_instead_of_basename_fallback(tmp_path):
    run_dir = tmp_path / "search_admission_queue_basename_fallback"
    _seed_minimal_trusted_run(run_dir)
    _seed_search_admission_handoff(
        run_dir,
        queue_ref="step2_input/step3_simulation_queue.json",
    )
    _write_empty_step3_queue(run_dir, "step2/step3_simulation_queue.json")

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
            "step2/step3_simulation_queue.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is False
    assert search_admission["artifact_refs"]["step3_simulation_queue.json"]["path"] == (
        "step2_input/step3_simulation_queue.json"
    )
    assert search_admission["artifact_refs"]["step3_simulation_queue.json"]["exists"] is False
    error_fields = {error["field"] for error in search_admission["errors"]}
    assert "step3_simulation_queue.json" in error_fields


def test_step5_allows_older_scope_sidecar_when_queue_recomputation_passes(tmp_path):
    run_dir = tmp_path / "search_admission_older_scope_sidecar"
    _seed_minimal_trusted_run(run_dir)
    _seed_search_admission_handoff(
        run_dir,
        queue_ref="step2/step3_simulation_queue.json",
        include_sidecar_scope=False,
    )
    _write_empty_step3_queue(run_dir, "step2/step3_simulation_queue.json")

    paths = write_step5_report_artifacts(
        run_dir,
        claims=[],
        artifact_paths=[
            "campaign_evaluation_plan.json",
            "search_iteration_plan.json",
            "search_iteration_plan_validation.json",
            "step3_admission_queue_validation.json",
            "campaign_search_admission_plan.json",
            "step2/step3_simulation_queue.json",
        ],
    )

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    search_admission = report["search_admission_validation"]

    assert search_admission["valid"] is True
    assert search_admission["step3_admission_queue_recomputed_validation"]["valid"] is True
    assert report["claim_validation"]["passed"] is True
    assert any(
        warning["field"] == "step3_admission_queue_validation.campaign_scope_validation"
        for warning in search_admission["warnings"]
    )


def test_final_report_surfaces_low_fidelity_screening_without_trusting_it(tmp_path):
    run_dir = tmp_path / "trusted_run_with_low_fidelity"
    _seed_minimal_trusted_run(run_dir)
    low_fidelity_artifacts = [
        "l1_evaluation_result.json",
        "l1_promotion_decision.json",
        "l2_evaluation_result.json",
        "l2_promotion_decision.json",
        "low_fidelity_screening_summary.json",
    ]
    _write_json(run_dir / "l1_evaluation_result.json", {
        "schema_version": "dse.step2.l1_evaluation_result.v1",
        "fidelity_level_achieved": "L1",
        "status": "passed",
        "design_point_id": "trusted_run",
        "family": "F1",
        "metrics": {"latency_ms": 2.5, "energy_j": 0.012},
        "feasible": True,
        "confidence": 0.82,
        "promotion_score": 0.88,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l1_promotion_decision.json", {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": "l1_promotion_decision.json",
        "from_layer": "L1",
        "to_layer": "L2",
        "decision": "promote",
        "promote": True,
        "promotion_score": 0.88,
        "confidence": 0.82,
        "threshold": 0.60,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l2_evaluation_result.json", {
        "schema_version": "dse.step2.l2_evaluation_result.v1",
        "fidelity_level_achieved": "L2",
        "status": "passed",
        "design_point_id": "trusted_run",
        "family": "F1",
        "metrics": {"latency_ms": 2.8, "energy_j": 0.014},
        "feasible": True,
        "confidence": 0.74,
        "mape_percent": 9.0,
        "promotion_score": 0.78,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "l2_promotion_decision.json", {
        "schema_version": "dse.step2.low_fidelity_promotion_decision.v1",
        "artifact": "l2_promotion_decision.json",
        "from_layer": "L2",
        "to_layer": "L3",
        "decision": "promote",
        "promote": True,
        "promotion_score": 0.78,
        "confidence": 0.74,
        "threshold": 0.65,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
    })
    _write_json(run_dir / "low_fidelity_screening_summary.json", {
        "schema_version": "dse.step2.low_fidelity_screening_summary.v1",
        "required_for_step3": True,
        "passed": True,
        "status": "passed",
        "candidate_id": "candidate-1",
        "mapping_id": "mapping-1",
        "artifact_refs": {
            "l1_evaluation_result": "l1_evaluation_result.json",
            "l1_promotion_decision": "l1_promotion_decision.json",
            "l2_evaluation_result": "l2_evaluation_result.json",
            "l2_promotion_decision": "l2_promotion_decision.json",
            "low_fidelity_summary": "low_fidelity_screening_summary.json",
        },
        "required_artifacts": low_fidelity_artifacts,
        "promotion_scores": {"l1_to_l2": 0.88, "l2_to_l3": 0.78},
        "thresholds": {"l1_to_l2": 0.60, "l2_to_l3": 0.65},
        "confidence": {"l1": 0.82, "l2": 0.74},
        "blockers": [],
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "trusted_final_eligible": False,
    })

    result = generate_final_report_artifacts(run_dir)

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "claim_validation.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    low_fidelity = report["low_fidelity_screening"]
    predicted_ids = {item["claim"]["claim_id"] for item in report["predicted_only_candidates"]}
    validation_by_id = {item["claim_id"]: item for item in validation["validations"]}

    assert result["trusted_claim_count"] == 3
    assert low_fidelity["present"] is True
    assert low_fidelity["passed"] is True
    assert low_fidelity["low_fidelity_role"] == "candidate_generator_only"
    assert low_fidelity["trusted_final_claim"] is False
    assert low_fidelity["excluded_from_trusted_ranking"] is True
    assert low_fidelity["missing_artifacts"] == []
    assert low_fidelity["l1"]["status"] == "passed"
    assert low_fidelity["l2"]["status"] == "passed"
    assert "l1_screening_candidate_signal" in predicted_ids
    assert "l2_screening_candidate_signal" in predicted_ids
    assert validation_by_id["l1_screening_candidate_signal"]["validation_status"] == "predicted_only"
    assert validation_by_id["l2_screening_candidate_signal"]["trusted"] is False
    assert all(item["backend"] == "systemc" for item in report["trusted_ranking"])
    assert "## Low-Fidelity Screening" in markdown


def test_predicted_only_winner_is_rejected(tmp_path):
    report = {
        "claims": [
            {
                "claim_id": "bad:winner",
                "claim_type": "best_architecture",
                "trusted": False,
                "predicted_only": True,
                "blocked": False,
                "backend": "analytical",
                "source_fidelity": "L1",
                "evidence_ids": [],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("predicted-only candidate cannot be a winner" in error for error in validation["errors"])


def test_trusted_blocked_winner_is_rejected(tmp_path):
    _write_json(tmp_path / "verdict.json", {"trusted_for_final_ranking": False})
    report = {
        "claims": [
            {
                "claim_id": "bad:blocked-winner",
                "claim_type": "best_architecture",
                "trusted": True,
                "predicted_only": False,
                "blocked": True,
                "backend": "systemc",
                "source_fidelity": "L3",
                "evidence_ids": ["verdict.json"],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("trusted claim cannot be blocked" in error for error in validation["errors"])


def test_trusted_claim_rejects_unresolved_evidence_path(tmp_path):
    report = {
        "claims": [
            {
                "claim_id": "bad:missing-evidence",
                "claim_type": "feasibility",
                "trusted": True,
                "predicted_only": False,
                "blocked": False,
                "backend": "systemc",
                "source_fidelity": "L3",
                "evidence_ids": ["missing-verdict.json"],
            }
        ],
        "selected_recommendation": {"status": "not_selected"},
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("evidence id does not resolve" in error for error in validation["errors"])


def test_selected_recommendation_rejects_nonlocal_evidence_path(tmp_path):
    report = {
        "claims": [],
        "selected_recommendation": {
            "status": "selected",
            "backend": "systemc",
            "predicted_only": False,
            "evidence_ids": ["../outside-verdict.json"],
        },
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    assert any("run-local relative path" in error for error in validation["errors"])


def test_step5_surfaces_hardware_ppa_ranking_without_selecting_winner(tmp_path):
    run_dir = tmp_path / "hardware_ppa_only"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    hardware_entry = {
        "candidate_id": "cand-a",
        "design_candidate_id": "design-cand-a",
        "rank": 1,
        "fpga_total_slice_luts": 100,
        "fpga_total_dsps": 2,
        "fpga_total_block_ram_tiles": 1,
        "fpga_total_bonded_iob": 12,
        "asic_total_cell_area": 1234.0,
        "asic_min_slack_ns": 0.5,
        "kernel_count": 8,
    }
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_tied",
            "release_id": "release-ppa",
            "candidate_count": 1,
            "major_kernel_count": 8,
            "ranking_eligible_candidate_count": 1,
            "blocked_candidate_count": 0,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "winner_selection_status": "tied_by_identical_kernel_ppa_no_single_winner",
            "all_candidates_metric_tied": True,
            "metric_signature_count": 1,
            "source_artifacts": {
                "candidate_universe_manifest": {
                    "exists": True,
                    "path": str(run_dir / "candidate_universe_manifest.json"),
                    "sha256": "fixture-candidate-universe",
                }
            },
            "fpga_ranking": [hardware_entry],
            "asic_ranking": [hardware_entry],
            "ranking_policy": {"non_identity_axes_excluded_from_score": True},
            "pareto_frontier": {
                "schema_version": "dse.dft.hardware_ppa_pareto_frontier.v1",
                "pareto_candidate_count": 1,
                "pareto_alternatives": [hardware_entry],
            },
            "claim_boundary": "hardware PPA only",
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_pareto_frontier.json",
        {
            "schema_version": "dse.dft.hardware_ppa_pareto_frontier.v1",
            "pareto_candidate_count": 1,
            "pareto_alternatives": [hardware_entry],
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_status.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking_status.v1",
            "status": "passed",
            "ranking_status": "trusted_hardware_ppa_ranking_tied",
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "blocked_no_unique_hardware_ppa_winners",
            "release_id": "release-ppa",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "ppa_winner_selection_status": "tied_by_identical_kernel_ppa_no_single_winner",
            "all_candidates_metric_tied": True,
            "metric_signature_count": 1,
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
            "fpga_best_architecture": None,
            "asic_best_architecture": None,
            "blockers": [{"blocker_id": "fpga_winner_not_resolved"}],
            "blocker_count": 1,
            "hardware_winner_resolution_eligible": False,
            "trusted_best_architecture_claim_eligible": False,
            "deliverable_complete": False,
            "completion_claim": "blocked",
            "claim_boundary": "winner resolution test fixture",
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_status.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution_status.v1",
            "status": "passed",
            "winner_resolution_status": "blocked_no_unique_hardware_ppa_winners",
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit.v1",
            "status": "blocked_candidate_specific_ppa_provenance",
            "winner_provenance_eligible": False,
            "unit_count": 8,
            "trusted_unit_count": 0,
            "blocked_unit_count": 8,
            "trusted_stage_count": 0,
            "blocked_stage_count": 40,
            "blocker_count": 40,
            "blocker_id_counts": {"commands_not_executed": 40},
            "tied_candidate_ids_requiring_fresh_ppa": ["cand-a"],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "provenance test fixture",
        },
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json",
        {"schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_candidate_specific_ppa_provenance_audit_status.json",
        {
            "schema_version": "dse.dft.candidate_specific_ppa_provenance_audit_status.v1",
            "status": "passed",
            "winner_provenance_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "fresh_candidate_specific_ppa_execution_required",
            "work_item_count": 40,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue_validation.json",
        {"schema_version": "dse.dft.hardware_tie_breaker_execution_queue_validation.v1", "valid": True, "errors": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "pareto_frontier.json").read_text(encoding="utf-8"))
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert report["selected_recommendation"]["selection_status"] == "hardware_ppa_ranking_available_no_full_dse_winner"
    assert report["selected_recommendation"]["winner_resolution_status"] == "blocked_no_unique_hardware_ppa_winners"
    assert report["dft_architecture_winner_resolution"]["present"] is True
    assert report["dft_architecture_winner_resolution"]["hardware_winner_resolution_eligible"] is False
    assert report["dft_candidate_specific_ppa_provenance"]["present"] is True
    assert report["dft_candidate_specific_ppa_provenance"]["winner_provenance_eligible"] is False
    assert report["dft_candidate_specific_ppa_provenance"]["tie_breaker_work_item_count"] == 40
    assert report["trusted_ranking"][0]["trusted_scope"].startswith("candidate-stamped major-kernel hardware PPA only")
    assert trusted["ranking_scope"] == "hardware_ppa_only"
    assert trusted["dft_architecture_winner_resolution"] == "dft_architecture_winner_resolution.json"
    assert pareto["frontier_scope"] == "hardware_ppa_only"
    assert len(pareto["pareto_alternatives"]) == 1


def test_step5_recomputes_hardware_ppa_ranking_validation_when_sidecar_is_stale(tmp_path):
    run_dir = tmp_path / "hardware_ppa_stale_valid_sidecar"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    ppa_path = run_dir / "dft_hardware_ppa_ranking.json"
    ppa = json.loads(ppa_path.read_text(encoding="utf-8"))
    ppa["source_artifacts"] = {"candidate_universe_manifest": {"exists": False}}
    _write_json(ppa_path, ppa)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    ranking = report["dft_hardware_ppa_ranking"]

    assert ranking["present"] is True
    assert ranking["trusted_hardware_ppa_scope"] is False
    assert ranking["status"] == "invalid_hardware_ppa_ranking"
    assert ranking["validation"]["companion_valid"] is True
    assert ranking["validation"]["recomputed_valid"] is False
    assert (
        "ranking_candidates_require_candidate_universe_manifest"
        in ranking["validation"]["recomputed_errors"]
    )


def test_step5_recomputes_candidate_specific_ppa_provenance_validation_when_sidecar_is_stale(tmp_path):
    run_dir = tmp_path / "candidate_specific_ppa_stale_valid_sidecar"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    provenance_path = run_dir / "dft_candidate_specific_ppa_provenance_audit.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["status"] = "trusted_candidate_specific_ppa_provenance"
    provenance["winner_provenance_eligible"] = True
    provenance["trusted_unit_count"] = 0
    provenance["blocked_unit_count"] = provenance["unit_count"]
    provenance["blocker_count"] = 1
    _write_json(provenance_path, provenance)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    provenance_section = report["dft_candidate_specific_ppa_provenance"]

    assert provenance_section["present"] is True
    assert provenance_section["source_winner_provenance_eligible"] is True
    assert provenance_section["winner_provenance_eligible"] is False
    assert provenance_section["status"] == "invalid_candidate_specific_ppa_provenance_validation"
    assert provenance_section["validation"]["companion_valid"] is True
    assert provenance_section["validation"]["recomputed_valid"] is False
    assert (
        "winner_provenance_eligible_with_blocked_units"
        in provenance_section["validation"]["recomputed_errors"]
    )


def test_step5_writes_requirement_evidence_matrix_and_keeps_fail_closed_when_incomplete(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "step5_requirement_matrix_visibility"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / paths["final_report_json"]).read_text(encoding="utf-8"))
    matrix_json = run_dir / "requirement_evidence_matrix.json"
    matrix_md = run_dir / "requirement_evidence_matrix.md"

    assert matrix_json.exists()
    assert matrix_md.exists()
    assert report["requirement_evidence_matrix"]["schema_version"] == (
        "dse.complete_dse.requirement_evidence_audit_matrix.v1"
    )
    assert report["requirement_evidence_matrix"]["source_goal"] == "docs/goal.md"
    assert report["requirement_evidence_matrix"]["deliverable_complete_allowed"] is False
    assert report["requirement_evidence_matrix"]["claimability"] == "blocked"
    assert report["requirement_evidence_matrix"]["requirement_count"] > 0
    assert report["requirement_evidence_matrix"]["blocked_requirement_count"] > 0
    assert report["claim_validation"]["deliverable_complete_allowed"] is False
    assert report["trusted_final_claim"] is False
    assert report["deliverable_complete"] is False


def test_step5_surfaces_resolved_fpga_asic_deployment_recommendations_without_trusted_winner(tmp_path):
    run_dir = tmp_path / "hardware_ppa_resolved_deployments"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "pareto_frontier.json").read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / "campaign_summary.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    assert report["selected_recommendation"]["trusted_winner"] is False
    assert report["selected_recommendation"]["selection_status"] == (
        "hardware_ppa_deployment_recommendations_available_no_full_scf_winner"
    )
    assert report["selected_recommendation"]["deployment_recommendation_status"] == (
        "hardware_ppa_deployment_recommendations_available"
    )
    assert report["dft_architecture_winner_resolution"]["hardware_winner_resolution_eligible"] is True
    assert report["dft_architecture_winner_resolution"]["fpga_best_architecture"]["candidate_id"] == "cand-fpga"
    assert report["dft_architecture_winner_resolution"]["asic_best_architecture"]["candidate_id"] == "cand-asic"

    deployment_recommendations = report["deployment_recommendations"]
    assert deployment_recommendations["status"] == "hardware_ppa_deployment_recommendations_available"
    assert deployment_recommendations["trusted_winner"] is False
    assert deployment_recommendations["trusted_final_claim"] is False
    assert deployment_recommendations["deliverable_complete"] is False
    assert deployment_recommendations["recommendations"]["fpga"]["candidate_id"] == "cand-fpga"
    assert deployment_recommendations["recommendations"]["asic"]["candidate_id"] == "cand-asic"
    assert deployment_recommendations["recommendations"]["fpga"]["trusted_winner"] is False
    assert deployment_recommendations["recommendations"]["asic"]["deliverable_complete"] is False
    assert trusted["ranking_scope"] == "hardware_ppa_only"
    assert trusted["deployment_recommendations"]["status"] == "hardware_ppa_deployment_recommendations_available"
    assert pareto["frontier_scope"] == "hardware_ppa_only"
    assert campaign_summary["deployment_recommendations_summary"]["resolved_recommendation_count"] == 2
    assert deployment_sidecar["schema_version"] == "dse.step5.deployment_recommendations.v1"
    assert deployment_sidecar["status"] == "hardware_ppa_deployment_recommendations_available"
    assert deployment_sidecar["recommendations"]["fpga"]["candidate_id"] == "cand-fpga"
    assert deployment_sidecar["recommendations"]["asic"]["candidate_id"] == "cand-asic"
    assert deployment_sidecar["trusted_winner"] is False
    assert deployment_sidecar["trusted_final_claim"] is False
    assert deployment_sidecar["deliverable_complete"] is False
    assert deployment_sidecar["source_step5_artifacts"] == ["final_report.json"]
    target_sections = report["target_scoped_recommendation_sections"]
    assert target_sections["fpga"]["target"] == "fpga"
    assert target_sections["fpga"]["recommendation_kind"] == "best_or_pareto"
    assert target_sections["fpga"]["candidate_id"] == "cand-fpga"
    assert target_sections["fpga"]["status"] == "resolved_hardware_ppa_deployment_recommendation"
    assert target_sections["fpga"]["deliverable_complete"] is False
    assert target_sections["asic"]["target"] == "asic"
    assert target_sections["asic"]["candidate_id"] == "cand-asic"
    assert target_sections["asic"]["status"] == "resolved_hardware_ppa_deployment_recommendation"
    assert target_sections["asic"]["trusted_final_claim"] is False
    assert "FPGA/ASIC Deployment Recommendations" in markdown
    assert "FPGA Best/Pareto Recommendation" in markdown
    assert "ASIC Best/Pareto Recommendation" in markdown
    assert "`cand-fpga`" in markdown
    assert "`cand-asic`" in markdown

    report["deployment_recommendations"]["recommendations"]["fpga"]["trusted_winner"] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "deployment_recommendations.fpga: must not set trusted_winner true" in error
        for error in validation["errors"]
    )


def test_step5_readiness_artifact_blocks_hardware_ppa_recommendation_naming_when_present(tmp_path):
    run_dir = tmp_path / "hardware_ppa_readiness_blocked"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)

    readiness_status = write_dft_hardware_deployment_recommendation_readiness(run_dir)
    assert readiness_status["status"] == "passed"

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / "campaign_summary.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    assert readiness["present"] is True
    assert readiness["status"] == "blocked_deployment_recommendation_evidence_pending"
    assert readiness["validation"]["valid"] is True
    assert readiness["can_name_hardware_ppa_winners"] is False
    assert readiness["trusted_final_claim"] is False
    assert readiness["deliverable_complete"] is False
    assert readiness["deployments"]["fpga"]["can_name_hardware_ppa_winner"] is False
    assert readiness["deployments"]["asic"]["can_name_hardware_ppa_winner"] is False

    deployment_recommendations = report["deployment_recommendations"]
    assert deployment_recommendations["status"] == "blocked_by_deployment_recommendation_readiness"
    assert deployment_recommendations["deployment_readiness_present"] is True
    assert deployment_recommendations["deployment_readiness_status"] == (
        "blocked_deployment_recommendation_evidence_pending"
    )
    assert deployment_recommendations["resolved_recommendation_count"] == 0
    assert deployment_recommendations["readiness_blocked_recommendation_count"] == 2
    assert deployment_recommendations["recommendations"]["fpga"]["candidate_id"] is None
    assert deployment_recommendations["recommendations"]["fpga"]["blocked_candidate_id_hint"] == "cand-fpga"
    assert deployment_recommendations["recommendations"]["asic"]["candidate_id"] is None
    assert deployment_recommendations["trusted_final_claim"] is False
    assert deployment_recommendations["deliverable_complete"] is False
    assert report["selected_recommendation"]["deployment_recommendation_status"] == (
        "blocked_by_deployment_recommendation_readiness"
    )
    assert report["selected_recommendation"]["selection_status"] == (
        "hardware_ppa_ranking_available_no_full_dse_winner"
    )
    assert trusted["deployment_recommendations"]["status"] == "blocked_by_deployment_recommendation_readiness"
    assert campaign_summary["dft_hardware_deployment_recommendation_readiness_summary"]["present"] is True
    assert deployment_sidecar["status"] == "blocked_by_deployment_recommendation_readiness"
    assert deployment_sidecar["deployment_readiness"]["status"] == (
        "blocked_deployment_recommendation_evidence_pending"
    )
    assert "DFT Hardware Deployment Recommendation Readiness" in markdown

    report["dft_hardware_deployment_recommendation_readiness"]["can_name_final_recommendation"] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "dft_hardware_deployment_recommendation_readiness: must not set can_name_final_recommendation true"
        in error
        for error in validation["errors"]
    )


def test_step5_surfaces_direct_full_scf_targeted_accounting_projection_without_claim_upgrade(tmp_path):
    run_dir = tmp_path / "full_scf_targeted_accounting_direct"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _write_json(
        run_dir / "dft_full_scf_targeted_deployment_accounting.json",
        {
            "schema_version": "dse.dft.full_scf_targeted_deployment_accounting.v1",
            "status": "targeted_accounting_ready_final_recommendation_blocked",
            "targeted_accounting_ready": True,
            "projection_only": True,
            "full_scf_numerical_gate_passed": False,
            "can_name_targeted_deployment_recommendation": False,
            "can_name_final_recommendation": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "blocker_ids": [],
            "deployments": {
                deployment: {
                    "deployment": deployment,
                    "status": "targeted_accounting_ready_pending_full_scf_numerical_gate",
                    "accounting_ready": True,
                    "projection_only": True,
                    "candidate_id": f"cand-{deployment}",
                    "design_candidate_id": f"design-{deployment}",
                    "selected_target": {"target_id": f"target-{deployment}"},
                    "host_bound_costs_included": True,
                    "runtime_overheads_included": True,
                    "accelerated_kernel_costs_included": True,
                    "host_bound_phase_ids": list(REQUIRED_HOST_BOUND_PHASE_IDS),
                    "runtime_overhead_ids": list(REQUIRED_OVERHEAD_PHASE_IDS),
                    "covered_accelerated_kernel_ids": list(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
                    "host_bound_phase_costs_s": {
                        phase_id: 0.1 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS
                    },
                    "runtime_overhead_costs_s": {
                        overhead_id: 0.01 for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS
                    },
                    "accelerated_kernel_costs_s": {
                        kernel_id: 0.001 for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS
                    },
                    "full_scf_numerical_gate_passed": False,
                    "blocker_ids": [],
                    "final_claim_blockers": [
                        {"blocker_id": "full_scf_numerical_gate_not_passed"}
                    ],
                    "can_name_targeted_deployment_recommendation": False,
                    "can_name_final_recommendation": False,
                    "trusted_final_claim": False,
                    "deliverable_complete": False,
                }
                for deployment in ("fpga", "asic")
            },
            "final_claim_blockers": [
                {"deployment": "fpga", "blocker_id": "full_scf_numerical_gate_not_passed"},
                {"deployment": "asic", "blocker_id": "full_scf_numerical_gate_not_passed"},
            ],
            "claim_boundary": "fixture accounting only",
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
            "projection_only": True,
            "full_scf_numerical_gate_passed": False,
            "can_name_targeted_deployment_recommendation": False,
            "can_name_final_recommendation": False,
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    accounting = readiness["full_scf_targeted_deployment_accounting"]
    assert accounting["present"] is True
    assert accounting["validation_valid"] is True
    assert accounting["targeted_accounting_ready"] is True
    assert accounting["projection_only"] is True
    assert accounting["fpga"]["candidate_id"] == "cand-fpga"
    assert accounting["asic"]["candidate_id"] == "cand-asic"
    assert accounting["fpga"]["host_bound_costs_included"] is True
    assert accounting["fpga"]["runtime_overheads_included"] is True
    assert accounting["fpga"]["accelerated_kernel_costs_included"] is True
    assert accounting["fpga"]["host_bound_phase_ids"] == list(REQUIRED_HOST_BOUND_PHASE_IDS)
    assert accounting["fpga"]["runtime_overhead_ids"] == list(REQUIRED_OVERHEAD_PHASE_IDS)
    assert accounting["fpga"]["covered_accelerated_kernel_ids"] == list(
        MAJOR_SCF_ACCELERATED_KERNEL_IDS
    )
    assert accounting["fpga"]["host_bound_phase_costs_s"]["mixing"] == 0.1
    assert accounting["fpga"]["runtime_overhead_costs_s"]["synchronization"] == 0.01
    assert (
        accounting["fpga"]["accelerated_kernel_costs_s"][MAJOR_SCF_ACCELERATED_KERNEL_IDS[0]]
        == 0.001
    )
    assert readiness["can_name_targeted_deployment_recommendation"] is False
    assert readiness["can_name_final_recommendation"] is False
    assert readiness["deliverable_complete"] is False
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "Full-SCF targeted deployment accounting" in markdown
    assert "projection-only `True`" in markdown
    assert "blockers `0`" in markdown
    assert "Full-SCF targeted accounting visibility" in markdown


def test_step5_surfaces_qe_baseline_materialization_without_claim_upgrade(tmp_path):
    run_dir = tmp_path / "qe_baseline_materialization_direct"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _write_json(
        run_dir / "dft_scf_six_class_qe_baseline_materialization.json",
        {
            "schema_version": "dse.dft_scf.six_class_qe_baseline_materialization.v1",
            "status": "passed",
            "case_count": len(REQUIRED_DFT_SCF_CLASS_IDS),
            "passed_case_count": len(REQUIRED_DFT_SCF_CLASS_IDS),
            "blocked_case_count": 0,
            "strict_scf_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "blocker_id_counts": {},
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "pure-software QE baseline materialization only",
        },
    )
    _write_json(
        run_dir / "dft_scf_six_class_qe_baseline_materialization_validation.json",
        {
            "schema_version": (
                "dse.dft_scf.six_class_qe_baseline_materialization_validation.v1"
            ),
            "valid": True,
            "errors": [],
        },
    )
    _write_json(
        run_dir / "dft_scf_six_class_qe_baseline_materialization_status.json",
        {
            "schema_version": (
                "dse.dft_scf.six_class_qe_baseline_materialization_status.v1"
            ),
            "status": "passed",
            "materialization_complete": True,
            "trusted_final_claim": False,
            "hardware_completion_eligible": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    materialization = readiness["full_scf_qe_baseline_materialization"]
    assert materialization["present"] is True
    assert materialization["artifact"]["exists"] is True
    assert materialization["validation_artifact"]["exists"] is True
    assert materialization["status_artifact"]["exists"] is True
    assert materialization["status"] == "passed"
    assert materialization["materialization_status"] == "passed"
    assert materialization["validation_valid"] is True
    assert materialization["case_count"] == len(REQUIRED_DFT_SCF_CLASS_IDS)
    assert materialization["passed_case_count"] == len(REQUIRED_DFT_SCF_CLASS_IDS)
    assert materialization["blocked_case_count"] == 0
    assert materialization["trusted_final_claim"] is False
    assert materialization["hardware_completion_eligible"] is False
    assert materialization["release_completion_eligible"] is False
    assert materialization["deliverable_complete"] is False
    assert readiness["can_name_final_recommendation"] is False
    assert readiness["deliverable_complete"] is False
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "Full-SCF QE baseline materialization" in markdown
    assert "present `True`" in markdown
    assert f"passed `{len(REQUIRED_DFT_SCF_CLASS_IDS)}`" in markdown


def test_report_validation_rejects_qe_baseline_materialization_claim_upgrade_tampering(tmp_path):
    report = {
        "claims": [],
        "selected_recommendation": {"status": "not_selected"},
        "dft_hardware_deployment_recommendation_readiness": {
            "full_scf_qe_baseline_materialization": {
                "trusted_final_claim": True,
                "hardware_completion_eligible": True,
                "release_completion_eligible": True,
                "deliverable_complete": True,
            },
        },
    }

    validation = validate_report_claims(report, tmp_path)

    assert validation["passed"] is False
    for field in (
        "trusted_final_claim",
        "hardware_completion_eligible",
        "release_completion_eligible",
        "deliverable_complete",
    ):
        assert any(
            "dft_hardware_deployment_recommendation_readiness."
            f"full_scf_qe_baseline_materialization: must not set {field} true"
            in error
            for error in validation["errors"]
        )


def test_step5_blocks_deployment_recommendations_when_winner_resolution_validation_fails(tmp_path):
    run_dir = tmp_path / "hardware_ppa_winner_resolution_invalid_sidecar"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution_validation.v1",
            "valid": False,
            "errors": ["stale_winner_resolution_sidecar_detected"],
            "claim_boundary": "invalid validation sidecar blocks deployment recommendations",
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_status.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution_status.v1",
            "status": "failed",
            "winner_resolution_status": "resolved_hardware_ppa_deployment_winners",
            "hardware_winner_resolution_eligible": True,
            "deliverable_complete": False,
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))

    winner_resolution = report["dft_architecture_winner_resolution"]
    assert winner_resolution["source_hardware_winner_resolution_eligible"] is True
    assert winner_resolution["hardware_winner_resolution_eligible"] is False
    assert winner_resolution["validation"]["valid"] is False
    assert winner_resolution["status_artifact"]["status"] == "failed"
    assert report["deployment_recommendations"]["status"] == "blocked_no_hardware_ppa_deployment_recommendations"
    assert report["deployment_recommendations"]["resolved_recommendation_count"] == 0
    assert report["selected_recommendation"]["selection_status"] == "hardware_ppa_ranking_available_no_full_dse_winner"
    assert deployment_sidecar["status"] == "blocked_no_hardware_ppa_deployment_recommendations"
    assert any(
        "FPGA/ASIC architecture winner resolution validation failed" in limitation
        for limitation in report["limitations"]
    )


def test_step5_recomputes_winner_resolution_validation_when_sidecar_is_stale(tmp_path):
    run_dir = tmp_path / "hardware_ppa_winner_resolution_stale_valid_sidecar"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    winner_path = run_dir / "dft_architecture_winner_resolution.json"
    winner = json.loads(winner_path.read_text(encoding="utf-8"))
    winner["deployments"]["fpga"]["top_rank_candidate_count"] = 2
    winner["deployments"]["fpga"]["top_rank_candidate_ids"] = ["cand-fpga", "cand-extra"]
    _write_json(winner_path, winner)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))

    winner_resolution = report["dft_architecture_winner_resolution"]
    assert winner_resolution["source_hardware_winner_resolution_eligible"] is True
    assert winner_resolution["hardware_winner_resolution_eligible"] is False
    assert winner_resolution["validation"]["companion_valid"] is True
    assert winner_resolution["validation"]["recomputed_valid"] is False
    assert (
        "fpga_resolved_without_single_top_candidate_or_design_collapse"
        in winner_resolution["validation"]["recomputed_errors"]
    )
    assert report["deployment_recommendations"]["status"] == "blocked_no_hardware_ppa_deployment_recommendations"
    assert report["deployment_recommendations"]["resolved_recommendation_count"] == 0
    assert deployment_sidecar["status"] == "blocked_no_hardware_ppa_deployment_recommendations"
    assert any(
        "FPGA/ASIC architecture winner resolution validation failed" in limitation
        for limitation in report["limitations"]
    )


def test_step5_surfaces_deployment_decision_support_and_release_blockers(tmp_path):
    run_dir = tmp_path / "deployment_decision_support"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    campaign_summary = json.loads((run_dir / "campaign_summary.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    support = report["dft_deployment_decision_support"]
    assert support["present"] is True
    assert support["status"] == "coordinated_current_best_with_open_release_blockers"
    assert support["current_best_available"] is True
    assert support["target_feasibility_ready"] is True
    assert support["recommendations"]["fpga"]["candidate_id"] == "cand-fpga"
    assert support["recommendations"]["fpga"]["selected_part"] == "XCVU19P"
    assert support["recommendations"]["asic"]["selected_device"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert support["full_scf_numerical_gate"]["passed"] is False
    assert support["full_scf_numerical_gate"]["blocked_row_record_count"] == 216
    assert support["release_completion_gates"]["candidate_set_consistency_status"] == "candidate_set_mismatch"
    assert support["release_completion_gates"]["deployment_target_consensus_status"] == (
        "deployment_target_consensus_mismatch"
    )
    assert support["release_completion_gates"]["release_gate_only_candidate_ids"] == ["cand-extra"]
    assert support["release_completion_gates"]["status_claim"] == "partial_mvp_blocked_for_deliverable"
    assert support["hardware_completion_eligible"] is False
    assert support["trusted_winner"] is False
    assert support["trusted_final_claim"] is False
    assert support["deliverable_complete"] is False
    assert campaign_summary["dft_deployment_decision_support_summary"]["release_completion_gates"][
        "full_scf_numerical_passed"
    ] is False
    assert deployment_sidecar["decision_support"]["status"] == (
        "coordinated_current_best_with_open_release_blockers"
    )
    assert deployment_sidecar["decision_support"]["full_scf_numerical_gate"]["passed"] is False
    assert deployment_sidecar["decision_support"]["release_completion_gates"][
        "candidate_set_consistency_status"
    ] == "candidate_set_mismatch"
    assert "DFT Deployment Decision Support" in markdown
    assert "`cand-fpga` / `xc7a35tcsg324-1` / `XCVU19P`" in markdown
    assert any(
        "Full-SCF host+accelerator numerical gate is not passed" in limitation
        for limitation in report["limitations"]
    )
    assert any(
        "Release-gate candidate IDs do not exactly match" in limitation
        for limitation in report["limitations"]
    )
    assert any(
        "Deployment target selection artifacts disagree" in limitation
        for limitation in report["limitations"]
    )

    report["dft_deployment_decision_support"]["deliverable_complete"] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "dft_deployment_decision_support: must not set deliverable_complete true" in error
        for error in validation["errors"]
    )


def test_step5_prefers_explicit_candidate_set_consistency_over_goal_audit_blocker(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_candidate_sets"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))

    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    assert release_gates["candidate_set_consistency_source"] == "dft_candidate_set_consistency.json"
    assert release_gates["candidate_set_consistency_status"] == "candidate_sets_match"
    assert release_gates["candidate_set_consistency_checked"] is True
    assert release_gates["candidate_set_consistency_artifact_status"] == "passed"
    assert release_gates["candidate_set_consistency_validation_valid"] is True
    assert release_gates["deployment_source_consensus_status"] == "deployment_source_consensus_passed"
    assert release_gates["deployment_source_consensus_passed"] is True
    assert release_gates["deployment_candidate_alignment_status"] == "deployment_candidate_alignment_passed"
    assert release_gates["deployment_candidate_alignment_passed"] is True
    assert release_gates["release_gate_only_candidate_ids"] == []
    assert release_gates["binding_map_only_candidate_ids"] == []
    assert release_gates["trial_ledger_only_candidate_ids"] == []
    assert report["dft_deployment_decision_support"]["recommendations"]["fpga"][
        "evidence_alignment_ready"
    ] is True
    assert report["dft_deployment_decision_support"]["recommendations"]["fpga"][
        "source_consensus_passed"
    ] is True
    assert not any(
        "Release-gate candidate IDs do not exactly match" in limitation
        for limitation in report["limitations"]
    )
    assert deployment_sidecar["decision_support"]["release_completion_gates"][
        "candidate_set_consistency_source"
    ] == "dft_candidate_set_consistency.json"


def test_step5_fails_closed_when_explicit_candidate_set_consistency_validation_is_invalid(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_candidate_set_validation"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _write_json(
        run_dir / "dft_candidate_set_consistency_validation.json",
        {
            "schema_version": "dse.dft.candidate_set_consistency_validation.v1",
            "valid": False,
            "status": "passed",
            "candidate_set_consistency_status": "candidate_sets_match",
            "errors": [{"field": "candidate_sets", "message": "synthetic invalid sidecar"}],
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]

    assert release_gates["candidate_set_consistency_source"] == "dft_candidate_set_consistency.json"
    assert release_gates["candidate_set_consistency_status"] == "candidate_sets_not_checked_validation_invalid"
    assert release_gates["candidate_set_consistency_validation_valid"] is False
    assert release_gates["deployment_candidate_alignment_status"] == (
        "deployment_candidate_alignment_blocked_candidate_set_gate"
    )
    assert any(
        blocker["blocker_id"] == "candidate_set_consistency_validation_not_passed"
        for blocker in release_gates["candidate_set_blockers"]
    )
    assert any(
        "Candidate-set consistency artifact validation did not pass" in limitation
        for limitation in report["limitations"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False
    assert report["dft_deployment_decision_support"]["trusted_final_claim"] is False
    assert report["dft_deployment_decision_support"]["deliverable_complete"] is False


def test_step5_fails_closed_when_candidate_set_sidecar_forges_union(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_forged_candidate_set_mismatch"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    forged = json.loads(
        (run_dir / "dft_candidate_set_consistency.json").read_text(encoding="utf-8")
    )
    for source, source_row in forged["candidate_sets"].items():
        if source == "release_gate":
            continue
        source_row["candidate_count"] = 1
        source_row["candidate_ids"] = ["cand-asic"]
        source_row["raw_candidate_ids"] = ["cand-asic"]
    forged["union_candidate_count"] = 2
    forged["union_candidate_ids"] = ["cand-asic", "cand-fpga"]
    forged["common_candidate_count"] = 2
    forged["common_candidate_ids"] = ["cand-asic", "cand-fpga"]
    _write_json(run_dir / "dft_candidate_set_consistency.json", forged)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]

    assert release_gates["candidate_set_consistency_status"] == (
        "candidate_sets_not_checked_validation_invalid"
    )
    assert release_gates["candidate_set_consistency_validation_valid"] is False
    assert release_gates["candidate_set_candidate_id_count"] == 2
    assert release_gates["binding_map_missing_candidate_ids"] == ["cand-fpga"]
    assert release_gates["trial_ledger_missing_candidate_ids"] == ["cand-fpga"]
    assert release_gates["deployment_candidate_alignment_status"] == (
        "deployment_candidate_alignment_blocked_candidate_set_gate"
    )
    assert any(
        blocker["blocker_id"] == "candidate_set_mismatch"
        for blocker in release_gates["candidate_set_blockers"]
    )
    assert any(
        blocker["blocker_id"] == "candidate_set_consistency_validation_not_passed"
        for blocker in release_gates["candidate_set_blockers"]
    )
    assert any(
        "Candidate-set consistency artifact validation did not pass" in limitation
        for limitation in report["limitations"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False
    assert report["dft_deployment_decision_support"]["trusted_final_claim"] is False
    assert report["dft_deployment_decision_support"]["deliverable_complete"] is False


def test_step5_fails_closed_when_deployment_recommendation_not_in_full_scf_candidate_set(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_candidate_alignment"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic"])

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]

    assert release_gates["candidate_set_consistency_status"] == "candidate_sets_match"
    assert release_gates["deployment_candidate_alignment_status"] == "deployment_candidate_alignment_mismatch"
    assert release_gates["deployment_candidate_alignment_passed"] is False
    assert release_gates["deployment_candidate_ids_missing_from_full_scf"] == {
        "fpga": ["cand-fpga"]
    }
    assert any(
        blocker["blocker_id"] == "deployment_candidate_not_in_full_scf_candidate_set"
        and blocker["candidate_id"] == "cand-fpga"
        for blocker in release_gates["deployment_candidate_alignment_blockers"]
    )
    assert report["dft_deployment_decision_support"]["recommendations"]["fpga"][
        "full_scf_candidate_membership"
    ] == "missing"
    assert report["dft_deployment_decision_support"]["recommendations"]["asic"][
        "full_scf_candidate_membership"
    ] == "present"
    assert any(
        "Deployment recommendation candidate IDs are not fully aligned" in limitation
        for limitation in report["limitations"]
    )
    assert deployment_sidecar["decision_support"]["release_completion_gates"][
        "deployment_candidate_alignment_status"
    ] == "deployment_candidate_alignment_mismatch"


def test_step5_fails_closed_when_deployment_sources_disagree_on_candidate_identity(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_source_mismatch"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga", "cand-other-fpga"])
    summary = json.loads(
        (run_dir / "dft_fpga_asic_deployment_summary.json").read_text(encoding="utf-8")
    )
    summary["fpga"]["best_candidate_id"] = "cand-other-fpga"
    _write_json(run_dir / "dft_fpga_asic_deployment_summary.json", summary)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]

    assert release_gates["deployment_source_consensus_status"] == "deployment_source_consensus_mismatch"
    assert release_gates["deployment_source_consensus_passed"] is False
    assert any(
        blocker["blocker_id"] == "deployment_candidate_source_mismatch"
        and blocker["deployment"] == "fpga"
        for blocker in release_gates["deployment_source_consensus_blockers"]
    )
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]
    assert fpga["source_consensus_status"] == "deployment_source_consensus_mismatch"
    assert fpga["candidate_id_by_source"]["winner_resolution"] == "cand-fpga"
    assert fpga["candidate_id_by_source"]["deployment_summary"] == "cand-other-fpga"
    assert any(
        "Deployment recommendation source artifacts disagree" in limitation
        for limitation in report["limitations"]
    )


def test_step5_fails_closed_when_recommendation_source_coverage_is_mixed(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_source_mixed_coverage"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)
    summary = json.loads(
        (run_dir / "dft_fpga_asic_deployment_summary.json").read_text(encoding="utf-8")
    )
    summary["asic"].pop("best_candidate_id", None)
    summary["asic"].pop("best_design_candidate_id", None)
    _write_json(run_dir / "dft_fpga_asic_deployment_summary.json", summary)
    coordination = json.loads(
        (run_dir / "dft_deployment_coordination_summary.json").read_text(encoding="utf-8")
    )
    coordination["deployment_recommendations"]["asic"].pop("best_candidate_id", None)
    coordination["deployment_recommendations"]["asic"].pop("best_design_candidate_id", None)
    _write_json(run_dir / "dft_deployment_coordination_summary.json", coordination)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    audit = _audit_current_final_report(run_dir)

    assert release_gates["deployment_source_consensus_status"] == (
        "deployment_source_consensus_not_checked_insufficient_sources"
    )
    assert release_gates["deployment_source_consensus_passed"] is False
    assert release_gates[
        "deployment_source_consensus_recommendation_bearing_deployments"
    ] == ["asic", "fpga"]
    assert report["dft_deployment_decision_support"]["recommendations"]["fpga"][
        "source_consensus_status"
    ] == "deployment_source_consensus_passed"
    assert report["dft_deployment_decision_support"]["recommendations"]["asic"][
        "source_consensus_status"
    ] == "deployment_source_consensus_not_checked_insufficient_sources"
    assert any(
        blocker["blocker_id"] == "deployment_source_consensus_insufficient_sources"
        and blocker["deployment"] == "asic"
        for blocker in release_gates["deployment_source_consensus_blockers"]
    )
    assert any(
        "insufficient independent sources" in limitation
        for limitation in report["limitations"]
    )
    assert any(
        blocker["blocker_id"] == "deployment_source_consensus_not_passed"
        and blocker["deployment_source_consensus_status"]
        == "deployment_source_consensus_not_checked_insufficient_sources"
        for blocker in audit["hardware_eligibility_blockers"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False


def test_step5_fails_closed_when_design_identity_source_coverage_is_sparse(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_design_source_sparse"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)
    summary = json.loads(
        (run_dir / "dft_fpga_asic_deployment_summary.json").read_text(encoding="utf-8")
    )
    summary["fpga"].pop("best_design_candidate_id", None)
    _write_json(run_dir / "dft_fpga_asic_deployment_summary.json", summary)
    coordination = json.loads(
        (run_dir / "dft_deployment_coordination_summary.json").read_text(encoding="utf-8")
    )
    coordination["deployment_recommendations"]["fpga"].pop("best_design_candidate_id", None)
    _write_json(run_dir / "dft_deployment_coordination_summary.json", coordination)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]

    assert fpga["candidate_id_by_source"] == {
        "winner_resolution": "cand-fpga",
        "deployment_summary": "cand-fpga",
        "coordination_summary": "cand-fpga",
    }
    assert fpga["design_candidate_id_by_source"] == {
        "winner_resolution": "design-cand-fpga",
    }
    assert fpga["source_consensus_status"] == (
        "deployment_source_consensus_not_checked_insufficient_design_sources"
    )
    assert release_gates["deployment_source_consensus_status"] == (
        "deployment_source_consensus_not_checked_insufficient_design_sources"
    )
    assert release_gates["deployment_source_consensus_passed"] is False
    assert any(
        blocker["blocker_id"] == "deployment_source_consensus_insufficient_design_sources"
        and blocker["deployment"] == "fpga"
        for blocker in release_gates["deployment_source_consensus_blockers"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False


def test_step5_reports_target_consensus_passed_when_fpga_target_fields_agree(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_target_consensus_pass"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]

    assert release_gates["deployment_target_consensus_status"] == "deployment_target_consensus_passed"
    assert release_gates["deployment_target_consensus_passed"] is True
    assert fpga["target_consensus_status"] == "deployment_target_consensus_passed"
    assert fpga["target_consensus_passed"] is True
    assert fpga["selected_device_by_source"] == {
        "coordination_summary": "VU19P",
        "target_feasibility": "VU19P",
    }
    assert fpga["selected_part_by_source"] == {
        "coordination_summary": "XCVU19P",
        "target_feasibility": "XCVU19P",
    }


def test_step5_blocks_deployment_decision_support_when_coordination_validation_fails(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_invalid_coordination_validation"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)
    _write_json(
        run_dir / "dft_deployment_coordination_summary_validation.json",
        {
            "schema_version": "dse.dft.deployment_coordination_summary_validation.v1",
            "valid": False,
            "errors": ["coordination_summary_stale_or_invalid"],
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    decision_support = report["dft_deployment_decision_support"]
    release_gates = decision_support["release_completion_gates"]

    assert release_gates["deployment_sidecar_validation_passed"] is False
    assert release_gates["coordination_validation_valid"] is False
    assert any(
        blocker["blocker_id"] == "deployment_coordination_validation_not_valid"
        for blocker in release_gates["deployment_sidecar_validation_blockers"]
    )
    assert release_gates["decision_support_eligibility_gates_passed"] is False
    assert decision_support["best_deployment_claim_eligible"] is False
    assert decision_support["current_best_available"] is False
    assert any(
        "Deployment decision-support sidecar validation did not pass" in limitation
        for limitation in report["limitations"]
    )


def test_step5_compares_winner_resolution_target_evidence_with_target_feasibility(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_winner_target_mismatch"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _inject_winner_resolution_fpga_target(run_dir, selected_target="xc7a35tcsg324-1")
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)
    coordination_path = run_dir / "dft_deployment_coordination_summary.json"
    coordination = json.loads(coordination_path.read_text(encoding="utf-8"))
    coordination["deployment_recommendations"]["fpga"].pop("selected_device", None)
    coordination["deployment_recommendations"]["fpga"].pop("fpga_selected_part", None)
    coordination["deployment_recommendations"]["fpga"].pop("fpga_selected_package", None)
    _write_json(coordination_path, coordination)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]
    workplan = report["dft_deployment_decision_support"]["target_reconciliation_workplan"]
    deployment_rec = report["deployment_recommendations"]["recommendations"]["fpga"]
    deployment_sidecar = json.loads((run_dir / "deployment_recommendations.json").read_text(encoding="utf-8"))

    assert deployment_rec["deployment_target_evidence"]["selected_target"] == "xc7a35tcsg324-1"
    assert deployment_rec["selected_device"] == "xc7a35tcsg324-1"
    assert fpga["selected_device_by_source"] == {
        "winner_resolution": "xc7a35tcsg324-1",
        "target_feasibility": "VU19P",
    }
    assert fpga["selected_part_by_source"] == {
        "winner_resolution": "xc7a35tcsg324-1",
        "target_feasibility": "XCVU19P",
    }
    assert fpga["target_consensus_status"] == "deployment_target_consensus_mismatch"
    assert release_gates["deployment_target_consensus_status"] == "deployment_target_consensus_mismatch"
    assert release_gates["deployment_target_consensus_passed"] is False
    assert any(
        blocker["blocker_id"] == "fpga_selected_device_source_mismatch"
        and blocker["deployment"] == "fpga"
        for blocker in release_gates["deployment_target_consensus_blockers"]
    )
    assert release_gates["deployment_target_reconciliation_required"] is True
    assert release_gates["deployment_target_reconciliation_work_item_count"] == 1
    assert workplan["status"] == "target_reconciliation_required"
    assert workplan["trusted_final_claim"] is False
    assert workplan["deliverable_complete"] is False
    assert workplan["work_items"][0]["deployment"] == "fpga"
    assert workplan["work_items"][0]["candidate_id"] == "cand-fpga"
    assert workplan["work_items"][0]["execution_allowed"] is False
    assert "vivado_implementation" in workplan["work_items"][0]["required_gate_sequence"]
    assert "fpga_selected_device_source_mismatch" in workplan["work_items"][0]["blocker_ids"]
    assert deployment_sidecar["decision_support"]["target_reconciliation_workplan"][
        "work_item_count"
    ] == 1
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False

    report["dft_deployment_decision_support"]["target_reconciliation_workplan"][
        "deliverable_complete"
    ] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "dft_deployment_decision_support.target_reconciliation_workplan: "
        "must not set deliverable_complete true" in error
        for error in validation["errors"]
    )


def test_step5_fails_closed_when_recommendation_target_coverage_is_mixed(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_target_mixed_coverage"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    _rewrite_fpga_target_to_consistent_vu19p(run_dir)
    target = json.loads(
        (run_dir / "dft_deployment_target_feasibility.json").read_text(encoding="utf-8")
    )
    target["asic_target_binding"].pop("selected_target_library", None)
    _write_json(run_dir / "dft_deployment_target_feasibility.json", target)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    audit = _audit_current_final_report(run_dir)

    assert release_gates["deployment_target_consensus_status"] == (
        "deployment_target_consensus_not_checked_insufficient_sources"
    )
    assert release_gates["deployment_target_consensus_passed"] is False
    assert release_gates[
        "deployment_target_consensus_recommendation_bearing_deployments"
    ] == ["asic", "fpga"]
    assert report["dft_deployment_decision_support"]["recommendations"]["fpga"][
        "target_consensus_status"
    ] == "deployment_target_consensus_passed"
    assert report["dft_deployment_decision_support"]["recommendations"]["asic"][
        "target_consensus_status"
    ] == "deployment_target_consensus_not_checked_insufficient_sources"
    assert any(
        blocker["blocker_id"] == "deployment_target_consensus_insufficient_sources"
        and blocker["deployment"] == "asic"
        for blocker in release_gates["deployment_target_consensus_blockers"]
    )
    assert any(
        "insufficient independent sources" in limitation
        for limitation in report["limitations"]
    )
    assert any(
        blocker["blocker_id"] == "deployment_target_consensus_not_passed"
        and blocker["deployment_target_consensus_status"]
        == "deployment_target_consensus_not_checked_insufficient_sources"
        for blocker in audit["hardware_eligibility_blockers"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False


def test_step5_fails_closed_when_target_sources_have_no_overlapping_identity_field(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_target_sparse_overlap"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    target = json.loads(
        (run_dir / "dft_deployment_target_feasibility.json").read_text(encoding="utf-8")
    )
    target["fpga_target_feasibility"].pop("selected_device", None)
    target["fpga_target_feasibility"].pop("selected_part", None)
    target["fpga_target_feasibility"]["selected_package"] = "A3824-class raw package"
    _write_json(run_dir / "dft_deployment_target_feasibility.json", target)
    coordination = json.loads(
        (run_dir / "dft_deployment_coordination_summary.json").read_text(encoding="utf-8")
    )
    coordination["deployment_recommendations"]["fpga"]["selected_device"] = "VU19P"
    coordination["deployment_recommendations"]["fpga"].pop("fpga_selected_part", None)
    coordination["deployment_recommendations"]["fpga"].pop("fpga_selected_package", None)
    _write_json(run_dir / "dft_deployment_coordination_summary.json", coordination)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]

    assert fpga["selected_device_by_source"] == {"coordination_summary": "VU19P"}
    assert fpga["selected_package_by_source"] == {
        "target_feasibility": "A3824-class raw package"
    }
    assert fpga["target_consensus_status"] == (
        "deployment_target_consensus_not_checked_sparse_target_identity"
    )
    assert release_gates["deployment_target_consensus_status"] == (
        "deployment_target_consensus_not_checked_sparse_target_identity"
    )
    assert release_gates["deployment_target_consensus_passed"] is False
    assert any(
        blocker["blocker_id"] == "deployment_target_consensus_sparse_target_identity"
        and blocker["deployment"] == "fpga"
        for blocker in release_gates["deployment_target_consensus_blockers"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False


def test_step5_fails_closed_when_fpga_target_overlap_is_package_only(tmp_path):
    run_dir = tmp_path / "deployment_decision_support_target_package_only_overlap"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    _seed_resolved_hardware_ppa_winner_artifacts(run_dir)
    _seed_deployment_decision_support_artifacts(run_dir)
    _seed_matching_candidate_set_consistency_artifact(run_dir)
    _seed_full_scf_candidate_ids(run_dir, ["cand-asic", "cand-fpga"])
    target = json.loads(
        (run_dir / "dft_deployment_target_feasibility.json").read_text(encoding="utf-8")
    )
    target["fpga_target_feasibility"].pop("selected_device", None)
    target["fpga_target_feasibility"].pop("selected_part", None)
    target["fpga_target_feasibility"]["selected_package"] = "A3824"
    _write_json(run_dir / "dft_deployment_target_feasibility.json", target)
    coordination = json.loads(
        (run_dir / "dft_deployment_coordination_summary.json").read_text(encoding="utf-8")
    )
    coordination["deployment_recommendations"]["fpga"].pop("selected_device", None)
    coordination["deployment_recommendations"]["fpga"].pop("fpga_selected_part", None)
    coordination["deployment_recommendations"]["fpga"]["fpga_selected_package"] = "A3824"
    _write_json(run_dir / "dft_deployment_coordination_summary.json", coordination)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    release_gates = report["dft_deployment_decision_support"]["release_completion_gates"]
    fpga = report["dft_deployment_decision_support"]["recommendations"]["fpga"]

    assert fpga["selected_package_by_source"] == {
        "coordination_summary": "A3824",
        "target_feasibility": "A3824",
    }
    assert fpga["overlapping_target_identity_fields"] == ["selected_package"]
    assert fpga["target_consensus_status"] == (
        "deployment_target_consensus_not_checked_sparse_target_identity"
    )
    assert release_gates["deployment_target_consensus_status"] == (
        "deployment_target_consensus_not_checked_sparse_target_identity"
    )
    assert release_gates["deployment_target_consensus_passed"] is False
    assert any(
        blocker["blocker_id"] == "deployment_target_consensus_sparse_target_identity"
        and blocker["deployment"] == "fpga"
        for blocker in release_gates["deployment_target_consensus_blockers"]
    )
    assert report["dft_deployment_decision_support"]["best_deployment_claim_eligible"] is False
    assert report["dft_deployment_decision_support"]["hardware_completion_eligible"] is False


def test_step5_report_surfaces_deployment_target_selection_without_final_upgrade(tmp_path):
    run_dir = tmp_path / "targeted_deployment_readiness"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _attach_target_selection_input_trust_gates(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    assert readiness["present"] is True
    assert readiness["can_name_hardware_ppa_winners"] is True
    assert readiness["deployment_target_selection_ready"] is True
    assert readiness["can_name_targeted_deployment_recommendation"] is False
    assert readiness["can_name_final_recommendation"] is False
    assert readiness["deliverable_complete"] is False
    assert readiness["readiness_upgrade_detected"] is False
    assert readiness["deployment_target_selection_artifact"]["exists"] is True
    assert readiness["fpga_target_selection"]["selected_target"]["part"] == "part_from_catalog"
    assert (
        readiness["asic_target_selection"]["selected_target"]["target_library_id"]
        == "fsa0a_c_generic_core_tt1p8v25c"
    )
    assert readiness["final_recommendation_required_next_evidence_counts"]["fpga"] >= 1
    assert readiness["final_recommendation_required_next_evidence_counts"]["asic"] >= 1
    assert trusted["dft_hardware_deployment_target_selection"] == "dft_hardware_deployment_target_selection.json"
    assert "Deployment target selection ready: `True`" in markdown
    assert "Can name targeted deployment recommendation: `False`" in markdown
    assert "part `part_from_catalog`" in markdown
    assert "library `fsa0a_c_generic_core_tt1p8v25c`" in markdown


def test_step5_report_consumes_target_selection_trust_gates_without_final_upgrade(tmp_path):
    run_dir = tmp_path / "targeted_deployment_trust_gates"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _attach_target_selection_input_trust_gates(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    readiness = report["dft_hardware_deployment_recommendation_readiness"]

    assert readiness["deployment_target_selection_trust_gates"]["all_trusted"] is True
    assert readiness["deployment_target_selection_trust_gate_summary"] == {
        "present": True,
        "all_trusted": True,
        "trusted_gate_count": 2,
        "gate_count": 2,
        "blocked_gate_count": 0,
    }
    assert (
        readiness["target_selection_input_trust_gates"]["fpga"]["trust_class"]
        == "fpga_target_catalog"
    )
    assert readiness["target_selection_input_trust_gates"]["asic"]["trusted"] is True
    assert (
        readiness["deployments"]["fpga"]["target_selection_input_trust_gate"]["trusted"]
        is True
    )
    assert readiness["can_name_final_recommendation"] is False
    assert readiness["trusted_final_claim"] is False
    assert readiness["deliverable_complete"] is False
    assert report["trusted_final_claim"] is False
    assert report["deliverable_complete"] is False
    assert "Target trust gates: present `True`, all trusted `True`, trusted gates `2/2`, blocked gates `0`" in markdown
    assert "FPGA input trust gate: class `fpga_target_catalog`, trusted `True`, blockers `0`" in markdown
    assert "ASIC input trust gate: class `asic_target_library_probe`, trusted `True`, blockers `0`" in markdown


def test_step5_report_clamps_mutated_targeted_recommendation_flag(tmp_path):
    run_dir = tmp_path / "mutated_targeted_deployment_readiness"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    readiness_path = run_dir / "dft_hardware_deployment_recommendation_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["can_name_targeted_deployment_recommendation"] = True
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness_report = report["dft_hardware_deployment_recommendation_readiness"]
    assert readiness_report["can_name_targeted_deployment_recommendation"] is False
    assert readiness_report["raw_readiness_flags"]["can_name_targeted_deployment_recommendation"] is True
    assert readiness_report["targeted_recommendation_upgrade_detected"] is True
    assert readiness_report["readiness_upgrade_detected"] is True
    assert readiness_report["validation"]["valid"] is False


def test_step5_report_blocks_partial_full_scf_accounting_completeness(tmp_path):
    run_dir = tmp_path / "partial_full_scf_accounting"
    _seed_minimal_trusted_run(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    missing_host = "mixing"
    missing_overhead = "synchronization"
    missing_kernel = MAJOR_SCF_ACCELERATED_KERNEL_IDS[-1]
    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id="cand-partial",
        campaign_id="campaign-partial",
        workload_run_id="workload-partial",
        trial_id="trial-partial",
        accelerated_kernel_costs_s={kernel_id: 0.01 for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS},
        host_bound_costs_s={phase_id: 0.1 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
        overhead_costs_s={overhead_id: 0.001 for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS},
        baseline_scf_time_s=2.0,
    )
    write_full_scf_evaluated_hybrid_artifacts(run_dir, payload)
    descriptor_path = run_dir / "full_scf_accelerator_descriptor.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["cost_model"]["host_bound_phase_costs_s"].pop(missing_host)
    descriptor["cost_model"]["runtime_overhead_costs_s"].pop(missing_overhead)
    descriptor["cost_model"]["accelerated_kernel_costs_s"].pop(missing_kernel)
    _write_json(descriptor_path, descriptor)
    ppa_path = run_dir / "full_scf_ppa_summary.json"
    ppa = json.loads(ppa_path.read_text(encoding="utf-8"))
    ppa["cost_model"] = descriptor["cost_model"]
    _write_json(ppa_path, ppa)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    completeness = report["full_scf_accounting_completeness"]

    assert completeness["present"] is True
    assert completeness["status"] == "blocked_partial_accounting"
    assert completeness["complete"] is False
    assert completeness["projection_only"] is True
    assert completeness["trusted_final_claim"] is False
    assert completeness["deliverable_complete"] is False
    assert completeness["host_retained_stages"]["missing_ids"] == [missing_host]
    assert completeness["runtime_overheads"]["missing_ids"] == [missing_overhead]
    assert completeness["accelerated_major_kernels"]["missing_ids"] == [missing_kernel]
    assert "host_retained_stage_costs_missing:mixing" in completeness["blocker_ids"]
    assert "runtime_overhead_costs_missing:synchronization" in completeness["blocker_ids"]
    assert f"accelerated_major_kernel_costs_missing:{missing_kernel}" in completeness["blocker_ids"]
    assert report["dft_full_scf_evaluated_hybrid"]["accounting_completeness"]["complete"] is False
    assert report["full_scf_evaluated_hybrid_costs"]["accounting_completeness_status"] == "blocked_partial_accounting"
    assert "Full-SCF accounting completeness: status `blocked_partial_accounting`, complete `False`" in markdown


def test_step5_report_surfaces_complete_full_scf_accounting_buckets_without_final_upgrade(tmp_path):
    run_dir = tmp_path / "complete_full_scf_accounting"
    _seed_minimal_trusted_run(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )
    _write_json(
        run_dir / "qe_baseline_comparison_index.json",
        {
            "schema_version": "dse.dft.qe_baseline_comparison_index.v1",
            "status": "comparison_index_present",
            "comparison_case_count": 2,
            "comparison_rows": [
                {"case_id": "qe_a", "baseline_wall_time_s": 1.0, "accelerated_wall_time_s": 0.8},
                {"case_id": "qe_b", "baseline_wall_time_s": 1.4, "accelerated_wall_time_s": 0.9},
            ],
            "claim_upgrade_allowed": False,
            "hardware_completion_eligible": False,
            # Deliberately adversarial: raw source summaries are visible only and
            # must not upgrade final report claim fields.
            "deliverable_complete": True,
        },
    )
    _write_json(
        run_dir / "full_scf_row_accounting.json",
        {
            "schema_version": "dse.dft.numerical.full_scf_row_accounting.v1",
            "status": "passed",
            "passed": True,
            "comparison_scope": "full_scf_host_accelerator_end_to_end",
            "host_accelerator_end_to_end": True,
            "full_scf_schedule_consumed": True,
            "host_bound_costs_included": True,
            "runtime_trace_source": "qe_offload_runtime_trace",
            "candidate_id": "cand-complete",
            "workload_case_id": "workload-complete",
            "blockers": [],
            "claim_upgrade_allowed": False,
            "hardware_completion_eligible": False,
            # Deliberately adversarial: raw source summaries are visible only and
            # must not upgrade final report claim fields.
            "deliverable_complete": True,
        },
    )
    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id="cand-complete",
        campaign_id="campaign-complete",
        workload_run_id="workload-complete",
        trial_id="trial-complete",
        accelerated_kernel_costs_s={kernel_id: 0.01 for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS},
        host_bound_costs_s={phase_id: 0.1 for phase_id in REQUIRED_HOST_BOUND_PHASE_IDS},
        overhead_costs_s={overhead_id: 0.001 for overhead_id in REQUIRED_OVERHEAD_PHASE_IDS},
        baseline_scf_time_s=2.0,
    )
    write_full_scf_evaluated_hybrid_artifacts(run_dir, payload)

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    completeness = report["full_scf_accounting_completeness"]
    hybrid = report["dft_full_scf_evaluated_hybrid"]

    assert completeness["present"] is True
    assert completeness["status"] == "complete"
    assert completeness["complete"] is True
    assert completeness["projection_only"] is False
    assert completeness["host_retained_stages"]["missing_ids"] == []
    assert completeness["runtime_overheads"]["required_ids"] == list(REQUIRED_OVERHEAD_PHASE_IDS)
    assert completeness["runtime_overheads"]["missing_ids"] == []
    assert completeness["accelerated_major_kernels"]["required_ids"] == list(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert completeness["accelerated_major_kernels"]["missing_ids"] == []
    assert completeness["descriptor_runtime_abi"]["descriptor_present"] is True
    assert completeness["descriptor_runtime_abi"]["descriptor_validation_passed"] is True
    assert completeness["descriptor_runtime_abi"]["runtime_schedule_present"] is True
    assert completeness["descriptor_runtime_abi"]["host_orchestrated"] is True
    assert completeness["descriptor_runtime_abi"]["data_residency_plan_present"] is True
    assert completeness["qe_baseline_row_accounting_attachment"]["present"] is True
    assert (
        completeness["qe_baseline_row_accounting_attachment"][
            "qe_baseline_comparison"
        ]["deliverable_complete"]
        is True
    )
    assert (
        completeness["qe_baseline_row_accounting_attachment"][
            "full_scf_row_accounting"
        ]["deliverable_complete"]
        is True
    )
    assert completeness["qe_baseline_row_accounting_attachment"]["claim_upgrade_allowed"] is False
    assert completeness["qe_baseline_row_accounting_attachment"]["hardware_completion_eligible"] is False
    assert completeness["qe_baseline_row_accounting_attachment"]["deliverable_complete"] is False
    assert completeness["trusted_final_claim"] is False
    assert completeness["deliverable_complete"] is False
    assert report["trusted_final_claim"] is False
    assert report["deliverable_complete"] is False
    assert report["qe_baseline_row_accounting_attachment"]["present"] is True
    assert (
        report["qe_baseline_row_accounting_attachment"]["qe_baseline_comparison"][
            "deliverable_complete"
        ]
        is True
    )
    assert (
        report["qe_baseline_row_accounting_attachment"]["full_scf_row_accounting"][
            "deliverable_complete"
        ]
        is True
    )
    assert report["qe_baseline_row_accounting_attachment"]["claim_upgrade_allowed"] is False
    assert report["qe_baseline_row_accounting_attachment"]["hardware_completion_eligible"] is False
    assert report["qe_baseline_row_accounting_attachment"]["deliverable_complete"] is False
    assert hybrid["artifact_hashes"] == {
        "full_scf_accelerator_descriptor.json": hybrid["artifacts"][
            "full_scf_accelerator_descriptor.json"
        ]["sha256"],
        "full_scf_correctness_report.json": hybrid["artifacts"][
            "full_scf_correctness_report.json"
        ]["sha256"],
        "full_scf_data_residency_plan.json": hybrid["artifacts"][
            "full_scf_data_residency_plan.json"
        ]["sha256"],
        "full_scf_ppa_summary.json": hybrid["artifacts"]["full_scf_ppa_summary.json"][
            "sha256"
        ],
        "full_scf_runtime_schedule.json": hybrid["artifacts"][
            "full_scf_runtime_schedule.json"
        ]["sha256"],
    }
    assert hybrid["hash_bound_artifact_count"] == 5
    assert hybrid["partial"] is False
    assert hybrid["projection_only"] is True
    assert hybrid["blocked"] is True
    assert hybrid["deliverable_complete"] is False
    assert report["full_scf_evaluated_hybrid_costs"]["accounting_complete"] is True
    partition = report["dft_full_scf_evaluated_hybrid"]["host_device_partition"]
    assert partition["prototype_boundary"] == "full_scf_evaluated_hybrid"
    assert partition["device_residency"] == "host_orchestrated_hybrid"
    assert partition["accelerated_kernel_ids"] == list(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert partition["cpu_retained_stage_ids"] == list(REQUIRED_HOST_BOUND_PHASE_IDS)
    assert partition["runtime_overhead_ids"] == list(REQUIRED_OVERHEAD_PHASE_IDS)
    assert partition["host_orchestrated"] is True
    assert partition["hardware_acceleration_claim_limited_to_major_kernels"] is True
    assert partition["cpu_retained_stages_counted_in_end_to_end_cost"] is True
    assert partition["runtime_overheads_counted_in_end_to_end_cost"] is True
    assert partition["partial"] is False
    assert partition["projection_only"] is True
    assert partition["blocked"] is True
    assert partition["trusted_final_claim"] is False
    assert partition["deliverable_complete"] is False
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "qe_baseline_comparison_index.json" in report["qe_baseline_row_accounting_attachment"]["artifacts"]
    assert "full_scf_row_accounting.json" in report["qe_baseline_row_accounting_attachment"]["artifacts"]
    assert "qe_baseline_comparison_index.json" in markdown
    assert "full_scf_row_accounting.json" in markdown


def test_step5_readiness_builds_full_scf_numerical_closure_workplan_from_blocked_rows(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_workplan"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_blocked_full_scf_numerical_rows(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    release_gates = readiness["release_completion_gates"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    assert readiness["full_scf_numerical_gate"]["present"] is True
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["full_scf_numerical_gate"]["blocked_row_record_count"] == 2
    assert workplan["status"] == "full_scf_numerical_closure_required"
    assert workplan["required"] is True
    assert workplan["work_item_count"] == 2
    assert workplan["candidate_work_item_count"] == 2
    assert workplan["class_row_work_item_count"] == 2
    assert workplan["execution_allowed"] is False
    assert workplan["trusted_winner"] is False
    assert workplan["trusted_final_claim"] is False
    assert workplan["numerical_correctness_claim_eligible"] is False
    assert workplan["hardware_completion_eligible"] is False
    assert workplan["release_completion_eligible"] is False
    assert workplan["deliverable_complete"] is False
    assert release_gates["full_scf_numerical_closure_required"] is True
    assert release_gates["full_scf_numerical_closure_work_item_count"] == 2
    assert release_gates["full_scf_numerical_closure_class_row_work_item_count"] == 2
    assert release_gates["full_scf_numerical_closure_blocker_category_counts"]["physical_metrics"] >= 4

    fpga_item = next(item for item in workplan["work_items"] if item["candidate_id"] == "cand-fpga")
    assert fpga_item["provenance_only"] is True
    assert fpga_item["execution_allowed"] is False
    assert fpga_item["trusted_final_claim"] is False
    assert fpga_item["deliverable_complete"] is False
    assert "host_bound_cost_accounting" in fpga_item["blocker_categories"]
    assert "runtime_overhead_accounting" in fpga_item["blocker_categories"]
    assert "accelerated_kernel_cost_coverage" in fpga_item["blocker_categories"]
    assert "trusted_runtime_accounting_source" in fpga_item["blocker_categories"]
    assert "execution_proof" in fpga_item["blocker_categories"]
    assert fpga_item["required_physical_metrics"] == [
        "density_residual",
        "total_energy_error_ry",
    ]
    assert "host_bound_costs_s" in fpga_item["required_evidence_fields"]
    assert fpga_item["class_rows"][0]["class_id"] == "gamma_only_supercell_scf"
    assert fpga_item["class_rows"][0]["passed"] is False
    assert "row_missing_passed_execution_proof" in fpga_item["class_rows"][0]["blocker_ids"]
    assert "Full-SCF numerical closure workplan is provenance-only" in "\n".join(
        report["limitations"]
    )
    assert "Full-SCF numerical closure workplan: required `True`, work items `2`" in markdown

    report["dft_hardware_deployment_recommendation_readiness"][
        "full_scf_numerical_closure_workplan"
    ]["deliverable_complete"] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "dft_hardware_deployment_recommendation_readiness."
        "full_scf_numerical_closure_workplan: must not set deliverable_complete true" in error
        for error in validation["errors"]
    )


def test_step5_readiness_emits_no_full_scf_numerical_work_items_after_passed_gate(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_passed"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    release_gates = readiness["release_completion_gates"]
    workplan = readiness["full_scf_numerical_closure_workplan"]

    assert readiness["full_scf_numerical_gate"]["present"] is True
    assert readiness["full_scf_numerical_gate"]["passed"] is True
    assert release_gates["full_scf_numerical_passed"] is True
    assert release_gates["full_scf_numerical_closure_required"] is False
    assert release_gates["full_scf_numerical_closure_work_item_count"] == 0
    assert workplan["status"] == "full_scf_numerical_closure_not_required"
    assert workplan["required"] is False
    assert workplan["work_item_count"] == 0
    assert workplan["trusted_winner"] is False
    assert workplan["trusted_final_claim"] is False
    assert workplan["numerical_correctness_claim_eligible"] is False
    assert workplan["hardware_completion_eligible"] is False
    assert workplan["release_completion_eligible"] is False
    assert workplan["deliverable_complete"] is False


def test_step5_readiness_treats_contradictory_full_scf_status_as_blocked(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_contradictory_status"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    full_scf_path = run_dir / "full_scf_end_to_end_comparison.json"
    full_scf = json.loads(full_scf_path.read_text(encoding="utf-8"))
    full_scf.update({
        "status": "passed",
        "passed": False,
        "trusted_accelerated_numeric_source": False,
        "blocked_row_record_count": 1,
        "blocked_candidate_count": 1,
        "blocker_count": 1,
        "blockers": [],
    })
    full_scf["row_records"][0]["status"] = "passed"
    full_scf["row_records"][0]["passed"] = False
    full_scf["row_records"][0]["trusted_accelerated_numeric_source"] = False
    full_scf["row_records"][0]["execution_proof_present"] = False
    full_scf["row_records"][0]["blockers"] = []
    full_scf["candidate_records"][0]["status"] = "passed"
    full_scf["candidate_records"][0]["passed"] = False
    full_scf["candidate_records"][0]["trusted_accelerated_numeric_source"] = False
    full_scf["candidate_records"][0]["blockers"] = []
    full_scf_path.write_text(json.dumps(full_scf, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    release_gates = readiness["release_completion_gates"]

    assert readiness["full_scf_numerical_gate"]["present"] is True
    assert readiness["full_scf_numerical_gate"]["status"] == "passed"
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert release_gates["full_scf_numerical_passed"] is False
    assert release_gates["full_scf_numerical_closure_required"] is True
    assert workplan["status"] == "full_scf_numerical_closure_required"
    assert workplan["required"] is True
    assert workplan["work_item_count"] >= 1
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "row_passed_flag_not_true" in merged_blockers
    assert "candidate_passed_flag_not_true" in merged_blockers
    assert "trusted_accelerated_numeric_source_not_true" in merged_blockers
    assert workplan["trusted_final_claim"] is False
    assert workplan["deliverable_complete"] is False


def test_step5_readiness_treats_negative_full_scf_blocked_counts_as_blocked(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_negative_counts"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    full_scf_path = run_dir / "full_scf_end_to_end_comparison.json"
    full_scf = json.loads(full_scf_path.read_text(encoding="utf-8"))
    full_scf["row_record_count"] = str(full_scf["row_record_count"])
    full_scf["blocked_row_record_count"] = -1
    full_scf["blocked_candidate_count"] = "-1"
    full_scf["blocker_count"] = -1
    full_scf_path.write_text(json.dumps(full_scf, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "row_record_count_mismatch" in merged_blockers
    assert "blocked_row_record_count_mismatch" in merged_blockers
    assert "blocked_candidate_count_mismatch" in merged_blockers
    assert "blocker_count_nonzero_or_invalid" in merged_blockers


def test_step5_readiness_requires_full_scf_validation_artifact_pass_flags(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_invalid_validation"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    validation_path = run_dir / "full_scf_end_to_end_comparison_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation.update({
        "status": "passed",
        "passed": True,
        "valid": False,
        "errors": [],
    })
    validation_path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    assert readiness["full_scf_numerical_gate"]["comparison_artifact_passed"] is True
    assert readiness["full_scf_numerical_gate"]["validation_passed"] is False
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "full_scf_comparison_validation_artifact_missing_or_failed" in merged_blockers


def test_step5_readiness_requires_full_scf_status_artifact_pass_flags(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_invalid_status"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    status_path = run_dir / "full_scf_end_to_end_comparison_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({
        "status": "comparison_passed",
        "comparison_passed": True,
        "validation_passed": True,
        "blocked_row_record_count": 1,
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    assert readiness["full_scf_numerical_gate"]["comparison_artifact_passed"] is True
    assert readiness["full_scf_numerical_gate"]["validation_passed"] is True
    assert readiness["full_scf_numerical_gate"]["status_artifact_passed"] is False
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "full_scf_comparison_status_artifact_missing_or_failed" in merged_blockers


def test_step5_readiness_rejects_full_scf_status_artifact_overclaim_flags(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_status_overclaim"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    status_path = run_dir / "full_scf_end_to_end_comparison_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["trusted_final_claim"] = True
    status["deliverable_complete"] = True
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    assert readiness["full_scf_numerical_gate"]["status_artifact_passed"] is False
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "full_scf_comparison_status_artifact_missing_or_failed" in merged_blockers


def test_step5_readiness_rejects_fixture_full_scf_runtime_source_even_if_self_asserted(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_fixture_source"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_passed_full_scf_numerical_gate(run_dir)
    full_scf_path = run_dir / "full_scf_end_to_end_comparison.json"
    full_scf = json.loads(full_scf_path.read_text(encoding="utf-8"))
    full_scf["row_records"][0]["measurement_source"] = "fixture"
    full_scf["row_records"][0]["measurement_source_kind"] = "fixture"
    full_scf_path.write_text(json.dumps(full_scf, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    workplan = readiness["full_scf_numerical_closure_workplan"]
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    assert readiness["release_completion_gates"]["full_scf_numerical_passed"] is False
    assert workplan["required"] is True
    merged_blockers = {
        blocker
        for item in workplan["work_items"]
        for blocker in item["candidate_blocker_ids"]
    }
    assert "row_untrusted_runtime_source:fixture" in merged_blockers


def test_report_validation_rejects_full_scf_release_gate_completion_tampering(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_gate_tamper"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_blocked_full_scf_numerical_rows(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    report["dft_hardware_deployment_recommendation_readiness"]["release_completion_gates"][
        "trusted_final_claim"
    ] = True
    report["dft_hardware_deployment_recommendation_readiness"]["release_completion_gates"][
        "deliverable_complete"
    ] = True
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any("release_completion_gates: must not set trusted_final_claim true" in error for error in validation["errors"])
    assert any("release_completion_gates: must not set deliverable_complete true" in error for error in validation["errors"])


def test_report_validation_rejects_full_scf_release_gate_passed_tampering(tmp_path):
    run_dir = tmp_path / "deployment_readiness_full_scf_gate_pass_tamper"
    _seed_minimal_trusted_run(run_dir)
    _seed_ready_deployment_recommendation_inputs(run_dir)
    _seed_blocked_full_scf_numerical_rows(run_dir)
    write_dft_hardware_deployment_recommendation_readiness(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {"schema_version": "dse.claim_validation.v1", "passed": True, "errors": []},
    )
    _write_json(
        run_dir / "evidence_requirements.json",
        {"schema_version": "dse.evidence_requirements.v1", "requirements": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    readiness = report["dft_hardware_deployment_recommendation_readiness"]
    assert readiness["full_scf_numerical_gate"]["passed"] is False
    readiness["release_completion_gates"]["full_scf_numerical_passed"] = True
    readiness["release_completion_gates"]["full_scf_numerical_closure_required"] = False
    validation = validate_report_claims(report, run_dir)
    assert validation["passed"] is False
    assert any(
        "release_completion_gates: full_scf_numerical_passed requires full_scf_numerical_gate.passed true" in error
        for error in validation["errors"]
    )
    assert any(
        "release_completion_gates: full_scf_numerical_closure_required false conflicts with required workplan" in error
        for error in validation["errors"]
    )

# --- run2 comparator/selector/admissibility regression coverage merged during RUN5 integration ---
def test_step5_normalizes_legacy_one_sided_deployment_comparator_eligibility(tmp_path):
    run_dir = tmp_path / "legacy_one_sided_deployment_comparator"
    _seed_minimal_trusted_run(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    _write_json(
        run_dir / "dft_deployment_comparator.json",
        {
            "schema_version": "dse.dft.deployment_comparator.v1",
            "status": "partial_recommendation_available",
            "deployment_comparison_status": "partial_recommendation_available",
            "fpga_recommendation": {
                "status": "blocked_no_fpga_recommendation",
                "recommendation_kind": "blocked",
                "top_candidate_count": 0,
                "top_candidate_ids": [],
                "top_candidates": [],
                "blockers": [{"blocker_id": "no_target_ranking_rows"}],
                "non_physical_tie_breakers_used": False,
            },
            "asic_recommendation": {
                "status": "unique_physical_winner",
                "recommendation_kind": "unique_candidate",
                "unique_winner": {"candidate_id": "asic-cand"},
                "top_candidate_count": 1,
                "top_candidate_ids": ["asic-cand"],
                "top_candidates": [{"candidate_id": "asic-cand"}],
                "blockers": [],
                "non_physical_tie_breakers_used": False,
            },
            "target_recommendation_available_count": 1,
            "cross_target_comparison_eligible": False,
            "hardware_completion_eligible_for_deployment_comparison": True,
            "cross_target_recommendation": {
                "status": "no_single_cross_target_winner_without_user_objective",
                "single_cross_target_winner": None,
                "objective_required": True,
            },
            "non_physical_tie_breakers_used": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_deployment_comparator_validation.json",
        {"schema_version": "dse.dft.deployment_comparator_validation.v1", "valid": True, "errors": []},
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment = report["dft_deployment_comparator"]
    assert deployment["target_recommendation_available_count"] == 1
    assert deployment["cross_target_comparison_eligible"] is False
    assert deployment["hardware_completion_eligible_for_deployment_comparison"] is False


def test_step5_surfaces_ic_eda_availability_transcript_refs_without_ppa_upgrade(tmp_path):
    run_dir = tmp_path / "ic_eda_transcript_refs"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    transcript = run_dir / "commands" / "ssh_dc_shell.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        "tool: dc_shell\ntransport: ssh\navailability_only_not_kernel_ppa: true\n",
        encoding="utf-8",
    )
    transcript_ref = {
        "path": "commands/ssh_dc_shell.txt",
        "exists": True,
        "sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
        "hash_algorithm": "sha256",
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
    }
    first_attempt = {
        "tool": "dc_shell",
        "transport": "ssh",
        "command": "ssh ic-eda source ~/.bashrc; dc_shell -version",
        "returncode": 1,
        "stdout": "dc_shell version O-2018.06-SP1",
        "stderr": "",
        "availability_only_not_kernel_ppa": True,
        "kernel_ppa_evidence": False,
        "hardware_completion_eligible": False,
        "raw_command_transcript_ref": transcript_ref,
    }
    _write_json(run_dir / "ic_eda_tool_attempts.json", [first_attempt])
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "completion_claim": "availability_only_not_kernel_ppa",
            "artifact_role": "tool_availability_only_not_kernel_ppa",
            "kernel_ppa_evidence": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "all_required_tools_available": True,
            "required_tools": ["dc_shell", "vcs", "vivado"],
            "tool_rows": [
                {"tool": "dc_shell", "available": True},
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
            ],
            "raw_attempts": [first_attempt],
            "raw_command_transcript_refs": [transcript_ref],
            "raw_command_transcript_ref_count": 1,
        },
    )
    ledger_dir = run_dir / "dft_ledger"
    _write_json(
        ledger_dir / "per_candidate_evidence_ledger.json",
        {
            "schema_version": "dse.dft.per_candidate_evidence_ledger.v1",
            "release_id": "ic-eda-transcript-test",
            "legal_candidate_count": 0,
            "release_claim_gate": {"deliverable_complete": False},
            "deliverable_complete": False,
        },
    )
    _write_json(
        ledger_dir / "eda_all_candidate_evidence.json",
        {
            "schema_version": "dse.dft.eda_all_candidate_evidence.v1",
            "status": "blocked_temporary",
            "tool_availability_status": "passed",
            "ic_eda_tool_availability": {
                "path": "ic_eda_tool_availability.json",
                "exists": True,
                "sha256": hashlib.sha256((run_dir / "ic_eda_tool_availability.json").read_bytes()).hexdigest(),
            },
            "ic_eda_tool_attempts": {
                "path": "ic_eda_tool_attempts.json",
                "exists": True,
                "sha256": hashlib.sha256((run_dir / "ic_eda_tool_attempts.json").read_bytes()).hexdigest(),
            },
            "hardware_evidence_attachment_policy": {
                "claim_boundary": "availability remains prerequisite evidence only",
            },
        },
    )

    paths = write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    markdown = (run_dir / paths["final_report_markdown"]).read_text(encoding="utf-8")
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    assert eda_summary["ic_eda_tool_availability_file_list"]["availability"]["path"] == (
        "ic_eda_tool_availability.json"
    )
    assert eda_summary["ic_eda_tool_availability_file_list"]["attempts"]["path"] == (
        "ic_eda_tool_attempts.json"
    )
    assert eda_summary["ic_eda_tool_availability_first_verification_source"] == (
        "ic_eda_tool_attempts.json"
    )
    assert eda_summary["ic_eda_tool_availability_first_verification"]["tool"] == "dc_shell"
    assert eda_summary["ic_eda_tool_availability_first_verification"]["kernel_ppa_evidence"] is False
    assert eda_summary["ic_eda_tool_availability_raw_transcript_ref_count"] == 1
    assert eda_summary["ic_eda_tool_availability_raw_transcript_refs"] == [transcript_ref]
    assert eda_summary["ic_eda_tool_availability_completion_claim"] == "availability_only_not_kernel_ppa"
    assert eda_summary["ic_eda_tool_availability_kernel_ppa_evidence"] is False
    assert eda_summary["ic_eda_tool_availability_hardware_completion_eligible"] is False
    assert eda_summary["ic_eda_tool_availability_deliverable_complete"] is False
    assert "IC/EDA availability file list" in markdown
    assert "IC/EDA first verification source" in markdown
    assert "IC/EDA availability transcript refs" in markdown
    assert "commands/ssh_dc_shell.txt" in markdown
    assert transcript_ref["sha256"] in markdown


def test_step5_drops_malformed_ic_eda_availability_transcript_refs(tmp_path):
    run_dir = tmp_path / "ic_eda_malformed_transcript_refs"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    malformed_ref = {
        "path": "commands/ssh_vcs.txt",
        "exists": True,
        "sha256": "not-a-sha256",
        "hash_algorithm": "md5",
        "artifact_role": "raw_command_transcript_only_not_kernel_ppa",
    }
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "completion_claim": "availability_only_not_kernel_ppa",
            "artifact_role": "tool_availability_only_not_kernel_ppa",
            "kernel_ppa_evidence": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "all_required_tools_available": False,
            "required_tools": ["dc_shell", "vcs", "vivado"],
            "tool_rows": [{"tool": "vcs", "available": False}],
            "raw_attempts": [{"tool": "vcs", "raw_command_transcript_ref": malformed_ref}],
            "raw_command_transcript_refs": [malformed_ref],
            "raw_command_transcript_ref_count": 1,
        },
    )
    ledger_dir = run_dir / "dft_ledger"
    _write_json(
        ledger_dir / "per_candidate_evidence_ledger.json",
        {
            "schema_version": "dse.dft.per_candidate_evidence_ledger.v1",
            "release_id": "ic-eda-malformed-transcript-test",
            "legal_candidate_count": 0,
            "release_claim_gate": {"deliverable_complete": False},
            "deliverable_complete": False,
        },
    )
    _write_json(
        ledger_dir / "eda_all_candidate_evidence.json",
        {
            "schema_version": "dse.dft.eda_all_candidate_evidence.v1",
            "status": "blocked_temporary",
            "tool_availability_status": "blocked",
            "ic_eda_tool_availability": {
                "path": "ic_eda_tool_availability.json",
                "exists": True,
                "sha256": hashlib.sha256((run_dir / "ic_eda_tool_availability.json").read_bytes()).hexdigest(),
            },
            "hardware_evidence_attachment_policy": {
                "claim_boundary": "availability remains prerequisite evidence only",
            },
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    assert eda_summary["ic_eda_tool_availability_raw_transcript_ref_count"] == 0
    assert eda_summary["ic_eda_tool_availability_raw_transcript_refs"] == []
    assert eda_summary["ic_eda_tool_availability_transcript_ref_malformed_count"] == 1
    assert eda_summary["ic_eda_tool_availability_kernel_ppa_evidence"] is False
    assert eda_summary["ic_eda_tool_availability_hardware_completion_eligible"] is False
    assert eda_summary["ic_eda_tool_availability_deliverable_complete"] is False


def test_step5_surfaces_standalone_hardware_evidence_matrix(tmp_path):
    run_dir = tmp_path / "hardware_matrix_only"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    _write_json(
        run_dir / "dft_hardware_evidence_matrix.json",
        {
            "schema_version": "dse.dft_scf.hardware_evidence_matrix.v1",
            "status": "passed",
            "trusted": True,
            "source": "dft_hardware_closure_release_gate",
            "candidate_count": 4,
            "unit_count": 32,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "major_kernel_count": len(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
            "kernel_rows": [
                {
                    "kernel_id": kernel_id,
                    "name": kernel_id,
                    "kernel_family": "test",
                    "status": "passed",
                    "disposition": "accelerated_claim",
                    "claim_allowed": True,
                    "trusted": True,
                    "blockers": [],
                }
                for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS
            ],
            "claim_boundary": "standalone matrix fixture; not deliverable completion",
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    matrix_ref = eda_summary["dft_hardware_evidence_matrix"]
    matrix = report["major_kernel_matrix"]
    assert report["dft_evidence_ledger"]["present"] is False
    assert report["dft_evidence_ledger"]["ledger_present"] is False
    assert report["dft_evidence_ledger"]["hardware_matrix_present"] is True
    assert report["dft_evidence_ledger"]["status"] == "hardware_matrix_only"
    assert eda_summary["major_kernel_matrix_status"] == "passed"
    assert eda_summary["major_kernel_matrix_trusted"] is True
    assert eda_summary["hardware_completion_eligible"] is True
    assert matrix["present_row_count"] == len(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert matrix["missing_kernel_ids"] == []
    assert matrix["status"] == "passed"
    assert matrix["trusted"] is True
    assert matrix["hardware_completion_eligible"] is True
    assert report["dft_evidence_ledger"]["major_kernel_matrix"]["rows"][0]["present"] is True
    assert matrix_ref["path"] == "dft_hardware_evidence_matrix.json"
    assert matrix_ref["trusted"] is True
    assert "Major-kernel matrix rows: `8` / `8`" in (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert report["selected_recommendation"]["trusted_winner"] is False


def test_step5_blocks_major_kernel_matrix_with_missing_rows(tmp_path):
    run_dir = tmp_path / "hardware_matrix_missing_rows"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    missing_kernel = MAJOR_SCF_ACCELERATED_KERNEL_IDS[-1]
    _write_json(
        run_dir / "dft_hardware_evidence_matrix.json",
        {
            "schema_version": "dse.dft_scf.hardware_evidence_matrix.v1",
            "status": "passed",
            "trusted": True,
            "source": "dft_hardware_closure_release_gate",
            "candidate_count": 4,
            "unit_count": 32,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "major_kernel_count": len(MAJOR_SCF_ACCELERATED_KERNEL_IDS),
            "kernel_rows": [
                {
                    "kernel_id": kernel_id,
                    "name": kernel_id,
                    "kernel_family": "test",
                    "status": "passed",
                    "disposition": "accelerated_claim",
                    "claim_allowed": True,
                    "trusted": True,
                    "blockers": [],
                }
                for kernel_id in MAJOR_SCF_ACCELERATED_KERNEL_IDS[:-1]
            ],
            "claim_boundary": "standalone matrix fixture; missing rows must fail closed",
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    eda_summary = report["dft_evidence_ledger"]["eda_summary"]
    matrix = report["major_kernel_matrix"]
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert matrix["status"] == "blocked_partial_major_kernel_matrix"
    assert matrix["trusted"] is False
    assert matrix["hardware_completion_eligible"] is False
    assert matrix["present_row_count"] == len(MAJOR_SCF_ACCELERATED_KERNEL_IDS) - 1
    assert matrix["missing_kernel_ids"] == [missing_kernel]
    assert f"major_kernel_matrix_row_missing:{missing_kernel}" in matrix["blocker_ids"]
    assert eda_summary["major_kernel_matrix_status"] == "blocked_partial_major_kernel_matrix"
    assert eda_summary["major_kernel_matrix_trusted"] is False
    assert eda_summary["hardware_completion_eligible"] is False
    assert f"Major-kernel matrix missing rows: `{missing_kernel}`" in markdown
    assert "Major-kernel matrix rows: `7` / `8`" in markdown


def test_step5_report_surfaces_id_provenance_refs_without_ledger_claim_upgrade(tmp_path):
    run_dir = tmp_path / "step5_id_provenance"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})

    _write_json(
        run_dir / "dft_trial_state_ledger.json",
        {
            "schema_version": "dse.dft.trial_state_ledger.v1",
            "status": "malformed_test_fixture",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "candidate_count": 2,
            "release_trial_count": 2,
            "exploratory_trial_count": 0,
            "blocked_trial_count": 0,
            "rejected_trial_count": 0,
            "selected_trial_count": 1,
            "completion_eligible": True,
            "deliverable_complete": True,
            "blocked_reasons": [],
            "next_actions": [],
            "claim_boundary": "trial state is orchestration/audit provenance only",
        },
    )
    _write_json(
        run_dir / "dft_trial_state_ledger_validation.json",
        {
            "schema_version": "dse.dft.trial_state_ledger_validation.v1",
            "valid": False,
            "errors": [{"field": "deliverable_complete", "message": "forced invalid fixture"}],
            "warnings": [],
        },
    )
    _write_json(
        run_dir / "dft_trial_transition_report.json",
        {
            "schema_version": "dse.dft.trial_transition_report.v1",
            "status": "transitions_recorded",
            "trial_count": 2,
            "transition_rows": [{"trial_id": "trial-a"}, {"trial_id": "trial-b"}],
        },
    )
    _write_json(
        run_dir / "dft_trial_artifact_refs.json",
        {
            "schema_version": "dse.dft.trial_artifact_refs.v1",
            "status": "artifact_refs_recorded",
            "campaign_artifact_refs": [{"path": "hierarchical_funnel_search_report.json"}],
            "trial_artifact_refs": [{"path": "candidate-a.json"}, {"path": "candidate-b.json"}],
            "registry": {"path": "dft_trial_ledger.sqlite"},
        },
    )
    _write_json(
        run_dir / "dft_candidate_binding_map.json",
        {
            "schema_version": "dse.dft.candidate_binding_map.v1",
            "workload_suite_id": "workload-a",
            "release_id": "release-a",
            "search_candidate_count": 2,
            "legal_release_candidate_count": 2,
            "bound_candidate_count": 2,
            "unmatched_candidate_count": 0,
            "unique_release_candidate_count": 2,
            "duplicate_release_candidate_ids": [],
            "completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": "candidate binding is heuristic ID provenance only",
        },
    )
    _write_json(
        run_dir / "dft_candidate_binding_map_validation.json",
        {
            "schema_version": "dse.dft.candidate_binding_map_validation.v1",
            "valid": True,
            "errors": [],
        },
    )
    required_semantic_sources = [
        "domain_freeze",
        "candidate_universe_manifest",
        "candidate_legality_report",
        "hierarchical_funnel_search_report",
        "dft_candidate_binding_map",
        "dft_trial_state_ledger",
        "dft_scf_six_class_bundle_manifest",
        "reference_admission_ledger",
    ]
    semantic_source_refs = {}
    for name in required_semantic_sources:
        source_path = run_dir / f"{name}.json"
        if not source_path.exists():
            _write_json(
                source_path,
                {
                    "schema_version": f"test.{name}.v1",
                    "source_id": name,
                },
            )
        semantic_source_refs[name] = {
            "path": f"{name}.json",
            "exists": True,
            "required": True,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "hash_algorithm": "sha256",
        }
    _write_json(
        run_dir / "dft_audit_semantic_closure.json",
        {
            "schema_version": "dse.dft_scf.semantic_audit_closure.v1",
            "overall_passed": True,
            "source_hash_backed": True,
            "source_artifacts": semantic_source_refs,
            "checks": [
                {"check_id": check_id, "passed": True, "blockers": []}
                for check_id in (
                    "phase_hotspot_identity",
                    "evaluation_policy_legality",
                    "candidate_tier_absence",
                    "coverage_vector_derivation",
                    "reference_hash_admission",
                )
            ],
            "claim_boundary": "semantic closure only; not hardware completion",
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "pareto_frontier.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    trial = report["dft_trial_state_ledger"]
    assert trial["present"] is True
    assert trial["status"] == "invalid_trial_ledger"
    assert trial["validation"]["valid"] is False
    assert trial["reported_completion_eligible"] is True
    assert trial["reported_deliverable_complete"] is True
    assert trial["completion_eligible"] is False
    assert trial["deliverable_complete"] is False
    assert trial["transition_report"]["transition_row_count"] == 2
    assert trial["artifact_refs_report"]["campaign_artifact_ref_count"] == 1
    assert trial["artifact_refs_report"]["trial_artifact_ref_count"] == 2
    assert "do not upgrade Step4 trust" in trial["claim_boundary"]

    binding = report["dft_candidate_binding_map"]
    assert binding["present"] is True
    assert binding["status"] == "fail_closed_candidate_binding_map_present"
    assert binding["completion_eligible"] is False
    assert binding["deliverable_complete"] is False
    assert report["dft_audit_semantic_closure"]["status"] == "semantic_audit_closure_passed"
    assert report["selected_recommendation"]["trusted_winner"] is False
    assert trusted["dft_trial_state_ledger"] == "dft_trial_state_ledger.json"
    assert trusted["dft_trial_transition_report"] == "dft_trial_transition_report.json"
    assert trusted["dft_trial_artifact_refs"] == "dft_trial_artifact_refs.json"
    assert trusted["dft_candidate_binding_map"] == "dft_candidate_binding_map.json"
    assert trusted["dft_audit_semantic_closure"] == "dft_audit_semantic_closure.json"
    assert pareto["dft_trial_state_ledger"] == "dft_trial_state_ledger.json"
    assert pareto["dft_candidate_binding_map"] == "dft_candidate_binding_map.json"
    assert pareto["dft_audit_semantic_closure"] == "dft_audit_semantic_closure.json"
    assert "Transition report rows: `2`" in markdown
    assert "Artifact refs campaign/trial: `1` / `2`" in markdown
    assert "cannot upgrade Step4 trust, numerical correctness, trusted Pareto, or FPGA/ASIC PPA claims" in markdown


def test_step5_queue_report_surfaces_parent_dft_provenance_artifacts(tmp_path):
    root_dir = tmp_path / "queue_parent"
    run_dir = root_dir / "step3_queue"
    _seed_minimal_trusted_run(run_dir)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    _write_json(
        run_dir / "step3_queue_execution_status.json",
        {
            "schema_version": "dse.step3.queue_execution_status.v1",
            "queue_mode": "simulation-eligible-candidates",
            "planned_entry_count": 1,
            "executed_entry_count": 1,
        },
    )
    _write_json(
        root_dir / "dft_trial_state_ledger.json",
        {
            "schema_version": "dse.dft.trial_state_ledger.v1",
            "status": "blocked_hard_gates_pending",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "candidate_count": 1,
            "release_trial_count": 1,
            "exploratory_trial_count": 0,
            "blocked_trial_count": 1,
            "rejected_trial_count": 0,
            "selected_trial_count": 0,
            "completion_eligible": False,
            "deliverable_complete": False,
            "blocked_reasons": ["hard_gates_pending"],
            "next_actions": ["run candidate-specific hard gates"],
        },
    )
    (root_dir / "dft_ledger").mkdir(parents=True, exist_ok=True)
    _write_json(
        root_dir / "dft_ledger" / "per_candidate_evidence_ledger.json",
        {
            "schema_version": "dse.codesign.per_candidate_evidence_ledger.v1",
            "release_id": "release-a",
            "legal_candidate_count": 1,
            "release_claim_gate": {"deliverable_complete": False},
            "rows": [
                {
                    "candidate_id": "release-a::candidate-0",
                    "claim_eligibility": {"deliverable_complete": False},
                    "blocker_status": {"status": "blocked_temporary"},
                }
            ],
            "deliverable_complete": False,
        },
    )
    _write_json(
        root_dir / "dft_trial_state_ledger_validation.json",
        {"schema_version": "dse.dft.trial_state_ledger_validation.v1", "valid": True, "errors": [], "warnings": []},
    )
    _write_json(
        root_dir / "dft_trial_transition_report.json",
        {
            "schema_version": "dse.dft.trial_transition_report.v1",
            "status": "transitions_recorded",
            "trial_count": 1,
            "transition_rows": [{"trial_id": "trial-a"}],
        },
    )
    _write_json(
        root_dir / "dft_trial_artifact_refs.json",
        {
            "schema_version": "dse.dft.trial_artifact_refs.v1",
            "status": "artifact_refs_recorded",
            "campaign_artifact_refs": [{"path": "dft_candidate_binding_map.json"}],
            "trial_artifact_refs": [{"path": "dft_trial_state_ledger.json"}],
            "registry": {},
        },
    )
    _write_json(
        root_dir / "dft_candidate_binding_map.json",
        {
            "schema_version": "dse.dft.candidate_binding_map.v1",
            "workload_suite_id": "workload-a",
            "release_id": "release-a",
            "search_candidate_count": 1,
            "legal_release_candidate_count": 1,
            "bound_candidate_count": 1,
            "unmatched_candidate_count": 0,
            "unique_release_candidate_count": 1,
            "duplicate_release_candidate_ids": [],
            "completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        root_dir / "dft_candidate_binding_map_validation.json",
        {"schema_version": "dse.dft.candidate_binding_map_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        root_dir / "dft_deployment_decision_summary.json",
        {
            "schema_version": "dse.dft.deployment_decision_summary.v1",
            "status": "deployment_decision_summary_fail_closed",
            "best_current_deployment_recommendation": {
                "status": "blocked_hard_gates_pending",
                "recommended_target": None,
                "recommended_candidate_id": None,
                "objective_id": "explicit-cost",
            },
            "selected_deployment_target": None,
            "selected_candidate_id": None,
            "fpga_deployment_assessment": {"target_model_binding_status": "blocked", "blocker_ids": ["vivado"]},
            "asic_deployment_assessment": {"target_model_binding_status": "blocked", "blocker_ids": ["dc"]},
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        root_dir / "dft_deployment_decision_summary_validation.json",
        {"schema_version": "dse.dft.deployment_decision_summary_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        root_dir / "dft_deployment_decision_summary_status.json",
        {
            "schema_version": "dse.dft.deployment_decision_summary_status.v1",
            "decision_summary_status": "deployment_decision_summary_fail_closed",
            "best_recommendation_status": "blocked_hard_gates_pending",
        },
    )
    _write_json(
        root_dir / "dft_audit_semantic_closure.json",
        {
            "schema_version": "dse.dft_scf.semantic_audit_closure.v1",
            "overall_passed": False,
            "source_hash_backed": False,
            "source_artifacts": {},
            "checks": [],
            "claim_boundary": "semantic closure blocked; not hardware completion",
        },
    )
    _write_json(
        root_dir / "dft_l4_goal_binding.json",
        {
            "schema_version": "dse.dft.l4_goal_binding.v1",
            "status": "blocked_l4_visible_but_identity_or_workload_unbound",
            "l4_root": "runs/dse/l4",
            "l4_software_visible_proof_present": True,
            "current_goal_binding": {"current_goal_l4_bound": False},
            "l4_matrix": {"row_count": 2, "expected_row_count": 2},
            "row_level_proofs": {"passed_gem5_l4_proof_count": 2},
            "final_closure_eligible": False,
            "deliverable_complete": False,
            "blockers": ["candidate_identity_crosswalk_missing_or_incomplete"],
            "claim_boundary": "software-visible transport only; not hardware completion",
        },
    )
    _write_json(
        root_dir / "dft_l4_goal_binding_validation.json",
        {"schema_version": "dse.dft.l4_goal_binding_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        root_dir / "dft_l4_goal_binding_status.json",
        {
            "schema_version": "dse.dft.l4_goal_binding_status.v1",
            "status": "passed",
            "binding_status": "blocked_l4_visible_but_identity_or_workload_unbound",
            "deliverable_complete": False,
        },
    )

    artifact_paths = [
        "../dft_trial_state_ledger.json",
        "../dft_trial_state_ledger_validation.json",
        "../dft_trial_transition_report.json",
        "../dft_trial_artifact_refs.json",
        "../dft_candidate_binding_map.json",
        "../dft_candidate_binding_map_validation.json",
        "../dft_deployment_decision_summary.json",
        "../dft_deployment_decision_summary_validation.json",
        "../dft_deployment_decision_summary_status.json",
        "../dft_audit_semantic_closure.json",
        "../dft_l4_goal_binding.json",
        "../dft_l4_goal_binding_validation.json",
        "../dft_l4_goal_binding_status.json",
        "../dft_ledger/per_candidate_evidence_ledger.json",
    ]
    write_step5_report_artifacts(run_dir, claims=[], artifact_paths=artifact_paths)

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trusted = json.loads((run_dir / "trusted_ranking.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "pareto_frontier.json").read_text(encoding="utf-8"))

    assert report["dft_trial_state_ledger"]["present"] is True
    assert report["dft_trial_state_ledger"]["artifacts"]["dft_trial_state_ledger.json"]["path"] == (
        "../dft_trial_state_ledger.json"
    )
    assert report["dft_candidate_binding_map"]["present"] is True
    assert report["dft_candidate_binding_map"]["artifacts"]["dft_candidate_binding_map.json"]["path"] == (
        "../dft_candidate_binding_map.json"
    )
    assert report["dft_deployment_decision_summary"]["present"] is True
    assert report["dft_deployment_decision_summary"]["artifacts"]["dft_deployment_decision_summary.json"]["path"] == (
        "../dft_deployment_decision_summary.json"
    )
    assert report["dft_audit_semantic_closure"]["present"] is True
    assert report["dft_audit_semantic_closure"]["status"] == "semantic_audit_closure_blocked"
    assert report["dft_l4_goal_binding"]["present"] is True
    assert report["dft_l4_goal_binding"]["status"] == "fail_closed_l4_goal_binding_present"
    assert report["dft_l4_goal_binding"]["artifacts"]["dft_l4_goal_binding.json"]["path"] == (
        "../dft_l4_goal_binding.json"
    )
    assert report["dft_evidence_ledger"]["present"] is True
    assert report["dft_evidence_ledger"]["deliverable_complete"] is False
    assert report["dft_evidence_ledger"]["artifacts"]["per_candidate_evidence_ledger.json"]["path"] == (
        "../dft_ledger/per_candidate_evidence_ledger.json"
    )
    assert report["step3_queue_aggregation"]["dft_step5_root_artifact_refs"] == {
        "dft_evidence_ledger": "../dft_ledger/per_candidate_evidence_ledger.json",
        "dft_candidate_binding_map": "../dft_candidate_binding_map.json",
        "dft_trial_state_ledger": "../dft_trial_state_ledger.json",
        "dft_deployment_decision_summary": "../dft_deployment_decision_summary.json",
        "dft_l4_goal_binding": "../dft_l4_goal_binding.json",
        "dft_audit_semantic_closure": "../dft_audit_semantic_closure.json",
    }
    assert trusted["dft_trial_state_ledger"] == "../dft_trial_state_ledger.json"
    assert trusted["dft_candidate_binding_map"] == "../dft_candidate_binding_map.json"
    assert trusted["dft_deployment_decision_summary"] == "../dft_deployment_decision_summary.json"
    assert trusted["dft_evidence_ledger"] == "../dft_ledger/per_candidate_evidence_ledger.json"
    assert trusted["dft_l4_goal_binding"] == "../dft_l4_goal_binding.json"
    assert trusted["dft_audit_semantic_closure"] == "../dft_audit_semantic_closure.json"
    assert pareto["dft_evidence_ledger"] == "../dft_ledger/per_candidate_evidence_ledger.json"
    assert pareto["dft_trial_state_ledger"] == "../dft_trial_state_ledger.json"
    assert pareto["dft_candidate_binding_map"] == "../dft_candidate_binding_map.json"
    assert pareto["dft_l4_goal_binding"] == "../dft_l4_goal_binding.json"
    assert pareto["dft_audit_semantic_closure"] == "../dft_audit_semantic_closure.json"


def test_step5_report_clamps_valid_trial_ledger_completion_claim(tmp_path):
    run_dir = tmp_path / "trial_ledger_claim_upgrade"
    _seed_minimal_trusted_run(run_dir)
    verdict = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    verdict["trusted_for_final_ranking"] = False
    _write_json(run_dir / "verdict.json", verdict)
    _write_json(
        run_dir / "claim_validation.json",
        {
            "schema_version": "dse.claim_validation.v1",
            "passed": True,
            "validations": [],
            "errors": [],
        },
    )
    _write_json(run_dir / "evidence_requirements.json", {"schema_version": "dse.evidence_requirements.v1"})
    _write_json(
        run_dir / "dft_trial_state_ledger.json",
        {
            "schema_version": "dse.dft.trial_state_ledger.v1",
            "status": "deliverable_complete",
            "campaign_id": "campaign-a",
            "workload_run_id": "workload-a",
            "candidate_count": 1,
            "release_trial_count": 1,
            "exploratory_trial_count": 0,
            "blocked_trial_count": 0,
            "rejected_trial_count": 0,
            "selected_trial_count": 1,
            "completion_eligible": True,
            "deliverable_complete": True,
            "blocked_reasons": [],
            "next_actions": [],
            "claim_boundary": "trial state is orchestration/audit provenance only",
        },
    )
    _write_json(
        run_dir / "dft_trial_state_ledger_validation.json",
        {
            "schema_version": "dse.dft.trial_state_ledger_validation.v1",
            "valid": True,
            "errors": [],
            "warnings": [],
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    trial = report["dft_trial_state_ledger"]
    assert trial["present"] is True
    assert trial["validation"]["valid"] is True
    assert trial["reported_completion_eligible"] is True
    assert trial["reported_deliverable_complete"] is True
    assert trial["status"] == "invalid_trial_ledger_claim_upgrade"
    assert trial["completion_eligible"] is False
    assert trial["deliverable_complete"] is False
    assert report["selected_recommendation"]["trusted_winner"] is False


def test_final_report_semantic_closure_blocks_missing_and_mismatched_source_hashes(tmp_path: Path) -> None:
    run_dir = tmp_path
    source_path = run_dir / "semantic_sources" / "domain_freeze.json"
    _write_json(source_path, {"schema_version": "test.domain_freeze.v1", "value": 1})
    stale_hash = "0" * 64
    check_ids = [
        "phase_hotspot_identity",
        "evaluation_policy_legality",
        "candidate_tier_absence",
        "coverage_vector_derivation",
        "reference_hash_admission",
    ]
    _write_json(
        run_dir / "dft_audit_semantic_closure.json",
        {
            "schema_version": "dse.dft_scf.semantic_audit_closure.v1",
            "overall_passed": True,
            "source_hash_backed": True,
            "source_artifacts": {
                "domain_freeze": {
                    "path": "semantic_sources/domain_freeze.json",
                    "exists": True,
                    "required": True,
                    "sha256": stale_hash,
                    "hash_algorithm": "sha256",
                },
                "candidate_universe_manifest": {
                    "path": "semantic_sources/candidate_universe_manifest.json",
                    "exists": True,
                    "required": True,
                },
            },
            "checks": [{"check_id": check_id, "passed": True} for check_id in check_ids],
        },
    )

    report, _, _ = generate_final_report(run_dir, claims=[])
    semantic = report["dft_audit_semantic_closure"]

    assert semantic["present"] is True
    assert semantic["status"] == "semantic_audit_closure_blocked"
    assert semantic["source_hash_backed"] is False
    assert "candidate_universe_manifest:missing_sha256" in semantic["source_hash_errors"]
    assert "domain_freeze:source_hash_mismatch" in semantic["source_hash_errors"]


def test_final_report_preserves_blocker_report_source_producer_refs_without_claim_upgrade(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "blocker_producer_refs"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    source_producer_refs = {
        "complete_dse_release_artifact_package.json": {
            "path": ".omx/context/run1/release/complete_dse_release_artifact_package.json",
            "sha256": "a" * 64,
            "hash_algorithm": "sha256",
            "source_lane": "run1",
            "status": "partial",
            "release_candidate_identity_provenance_status": "blocked",
            "release_candidate_identity_provenance_blocker_ids": [
                "deployment_decision_summary_not_bound",
                "strict_qe_release_lane_bundle_not_supplied_to_audit",
            ],
            "release_candidate_identity_provenance_package_status": "partial",
            "release_candidate_identity_provenance_canonical_bundle_bound": False,
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": False,
            "deliverable_complete": False,
            "claimable": False,
        },
        "dft_candidate_workflow_target_evidence_gate_ledger_status.json": {
            "path": ".omx/context/run2/target_ledger/dft_candidate_workflow_target_evidence_gate_ledger_status.json",
            "sha256": "b" * 64,
            "hash_algorithm": "sha256",
            "source_lane": "run2",
            "status": "failed",
            "stable_blocker_reason_counts": {"blocked_tool_unavailable": 3},
            "replayable_tool_transcript_ref_count": 6,
            "availability_probe_only_row_count": 3,
            "candidate_kernel_axis_unbound_row_count": 4,
            "candidate_kernel_axis_bound_row_count": 12,
            "parsed_stage_result_ref_count": 2,
            "claim_upgrade_allowed_count": 0,
            "claimable": False,
        },
    }
    _write_json(
        run_dir / "blocker_report.json",
        {
            "schema_version": "dse.complete_dse.blocker_report.v1",
            "status": "blocked",
            "blocked_fields": ["done_when_07"],
            "source_producer_artifact_refs": source_producer_refs,
            "source_producer_artifact_ref_count": len(source_producer_refs),
            "source_producer_artifact_rationale": (
                "Preserves latest run1/run2 producer refs for fail-closed "
                "traceability only."
            ),
            "deliverable_complete": False,
        },
    )

    write_step5_report_artifacts(run_dir, claims=[])
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")
    support = report["dft_deployment_decision_support"]

    assert support["blocker_report_source_producer_artifact_refs"] == source_producer_refs
    assert support["blocker_report_source_producer_artifact_ref_count"] == 2
    assert support["blocker_report_source_lane_summary"] == {
        "run1": {
            "artifact_count": 1,
            "artifact_names": ["complete_dse_release_artifact_package.json"],
            "statuses": ["partial"],
            "claimable_count": 0,
            "deliverable_complete_count": 0,
            "claim_upgrade_allowed_count": 0,
            "release_candidate_identity_provenance_statuses": ["blocked"],
            "release_candidate_identity_provenance_blocker_ids": [
                "deployment_decision_summary_not_bound",
                "strict_qe_release_lane_bundle_not_supplied_to_audit",
            ],
            "release_candidate_identity_provenance_trusted_count": 0,
            "release_candidate_identity_provenance_canonical_bundle_bound_count": 0,
        },
        "run2": {
            "artifact_count": 1,
            "artifact_names": [
                "dft_candidate_workflow_target_evidence_gate_ledger_status.json"
            ],
            "statuses": ["failed"],
            "claimable_count": 0,
            "deliverable_complete_count": 0,
            "claim_upgrade_allowed_count": 0,
            "stable_blocker_reason_counts": {"blocked_tool_unavailable": 3},
            "replayable_tool_transcript_ref_count": 6,
            "availability_probe_only_row_count": 3,
            "candidate_kernel_axis_unbound_row_count": 4,
            "candidate_kernel_axis_bound_row_count": 12,
            "parsed_stage_result_ref_count": 2,
        },
    }
    assert support["release_completion_gates"]["blocker_report_source_lanes"] == [
        "run1",
        "run2",
    ]
    assert "fail-closed traceability only" in support["blocker_report_source_producer_artifact_rationale"]
    assert support["trusted_final_claim"] is False
    assert support["deliverable_complete"] is False
    assert (
        support["release_completion_gates"]["blocker_report_source_producer_artifact_ref_count"]
        == 2
    )
    assert "Blocker producer refs: `2`" in markdown
    assert "Blocker producer lanes: `run1:1, run2:1`" in markdown
    assert "Release provenance: `run1:blocked`" in markdown
    assert "Candidate/kernel axis gaps: `run2:unbound=4, parsed_refs=2`" in markdown


def test_step5_generated_reporting_package_sidecar_surfaces_run1_run2_refs_fail_closed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "generated_reporting_package_step5_smoke"
    _seed_minimal_trusted_run(run_dir)
    _downgrade_to_hardware_ppa_only_run(run_dir)
    source_producer_refs = {
        "complete_dse_release_artifact_package.json": {
            "path": ".omx/context/run1/release/complete_dse_release_artifact_package.json",
            "sha256": "a" * 64,
            "hash_algorithm": "sha256",
            "source_lane": "run1",
            "status": "partial",
            "release_candidate_identity_provenance_status": "blocked",
            "release_candidate_identity_provenance_blocker_ids": [
                "deployment_decision_summary_not_bound",
            ],
            "release_candidate_identity_provenance_canonical_bundle_bound": False,
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": False,
            "runtime_scheduling_provenance": {
                "runtime_schedule_id": "runtime_latency_balanced",
                "co_scheduling_policy_id": "overlap_dma_compute",
                "queue_policy": "bounded_fifo_depth_2",
            },
            "artifact_provenance": {
                "release_subset_hash": "run1-release-subset-hash",
                "candidate_workflow_deployment_target_matrix_hash": "run1-target-matrix-hash",
            },
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
        "dft_candidate_workflow_target_evidence_gate_ledger_status.json": {
            "path": ".omx/context/run2/target_ledger/dft_candidate_workflow_target_evidence_gate_ledger_status.json",
            "sha256": "b" * 64,
            "hash_algorithm": "sha256",
            "source_lane": "run2",
            "status": "failed",
            "stable_blocker_reason_counts": {"blocked_tool_unavailable": 3},
            "replayable_tool_transcript_ref_count": 6,
            "availability_probe_only_row_count": 3,
            "candidate_kernel_axis_unbound_row_count": 4,
            "candidate_kernel_axis_bound_row_count": 12,
            "candidate_kernel_target_axis_count": 16,
            "candidate_kernel_target_axis_counts_by_target": {"asic": 4, "fpga": 12},
            "row_counts_by_target_platform_kind": {"asic": 4, "fpga": 12},
            "unknown_target_platform_kind_row_count": 1,
            "parsed_stage_result_ref_count": 2,
            "blocker_count": 5,
            "blocker_id_counts": {
                "parsed_result_missing": 4,
                "unknown_target_platform_kind": 1,
            },
            "claim_upgrade_allowed_count": 0,
            "trusted_final_claim": False,
            "deliverable_complete": False,
        },
    }
    package_manifest = write_complete_dse_reporting_package(
        run_dir,
        candidate_ids=["cand-a"],
        workload_case_ids=["qe-scf"],
        status="draft",
        source_artifact_refs=source_producer_refs,
    )

    write_step5_report_artifacts(run_dir, claims=[])

    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    deployment_sidecar = json.loads(
        (run_dir / "deployment_recommendations.json").read_text(encoding="utf-8")
    )
    campaign_summary = json.loads(
        (run_dir / "campaign_summary.json").read_text(encoding="utf-8")
    )
    markdown = (run_dir / "final_report.md").read_text(encoding="utf-8")

    support = report["dft_deployment_decision_support"]
    sidecar_support = deployment_sidecar["decision_support"]

    assert package_manifest["deliverable_complete"] is False
    assert support["blocker_report_source_lanes"] == ["run1", "run2"]
    assert support["blocker_report_source_producer_artifact_ref_count"] == 2
    assert sidecar_support["blocker_report_source_lanes"] == ["run1", "run2"]
    assert sidecar_support["blocker_report_source_producer_artifact_ref_count"] == 2
    assert sidecar_support["blocker_report_source_lane_summary"]["run1"][
        "release_candidate_identity_provenance_statuses"
    ] == ["blocked"]
    assert sidecar_support["blocker_report_source_lane_summary"]["run1"][
        "runtime_schedule_ids"
    ] == ["runtime_latency_balanced"]
    assert sidecar_support["blocker_report_source_lane_summary"]["run1"][
        "co_scheduling_policy_ids"
    ] == ["overlap_dma_compute"]
    assert sidecar_support["blocker_report_source_lane_summary"]["run1"][
        "artifact_provenance_release_subset_hashes"
    ] == ["run1-release-subset-hash"]
    assert sidecar_support["blocker_report_source_lane_summary"]["run1"][
        "artifact_provenance_candidate_workflow_deployment_target_matrix_hashes"
    ] == ["run1-target-matrix-hash"]
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "candidate_kernel_axis_unbound_row_count"
    ] == 4
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "candidate_kernel_axis_bound_row_count"
    ] == 12
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "replayable_tool_transcript_ref_count"
    ] == 6
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "availability_probe_only_row_count"
    ] == 3
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "stable_blocker_reason_counts"
    ] == {"blocked_tool_unavailable": 3}
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "candidate_kernel_target_axis_count"
    ] == 16
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "candidate_kernel_target_axis_counts_by_target"
    ] == {"asic": 4, "fpga": 12}
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "unknown_target_platform_kind_row_count"
    ] == 1
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "blocker_count"
    ] == 5
    assert sidecar_support["blocker_report_source_lane_summary"]["run2"][
        "blocker_id_counts"
    ] == {"parsed_result_missing": 4, "unknown_target_platform_kind": 1}
    assert campaign_summary["dft_deployment_decision_support_summary"][
        "blocker_report_source_lane_summary"
    ]["run2"]["parsed_stage_result_ref_count"] == 2
    assert deployment_sidecar["trusted_final_claim"] is False
    assert deployment_sidecar["deliverable_complete"] is False
    assert report["trusted_final_claim"] is False
    assert report["deliverable_complete"] is False
    assert "Blocker producer lanes: `run1:1, run2:1`" in markdown
    assert (
        "Release runtime/co-scheduling: `run1:runtime=runtime_latency_balanced, "
        "co_schedule=overlap_dma_compute, queue=bounded_fifo_depth_2, "
        "release_hashes=1, matrix_hashes=1`"
        in markdown
    )
    assert (
        "Target ledger counters: `run2:axis=16, targets=asic:4+fpga:12, "
        "bound=12, unbound=4, parsed_refs=2, replayable_transcripts=6, "
        "availability_probe_only=3, unknown_target=1, blocker_count=5, "
        "blockers=blocked_tool_unavailable:3, "
        "blocker_ids=parsed_result_missing:4+unknown_target_platform_kind:1`"
        in markdown
    )
