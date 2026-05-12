#!/usr/bin/env python3
# pyright: reportIndexIssue=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false, reportOptionalSubscript=false, reportOperatorIssue=false
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json"
ADJUDICATOR_RUNNER_PATH = ROOT / "tools/benchmarks/run_qe_system_design_adjudicator.py"
DEFAULT_OUTPUT_DIR = ROOT / "docs/benchmarks/archive/results/systemc_architecture_family_dse_bootstrap"
DEFAULT_CASE_PACK_PATH = ROOT / "docs/benchmarks/archive/results/qe_ic_case_pack_v0.json"
DEFAULT_MODEL_BIN = ROOT / "model/qe_band_solver_model/build/qe_band_solver_model"
DEFAULT_COMPARE_HELPER = ROOT / "tools/benchmarks/compare_qe_gold_correctness.py"
DEFAULT_NORMALIZE_GOLD_HELPER = ROOT / "tools/benchmarks/normalize_qe_gold_baseline.py"
DEFAULT_GOLD_BASELINE_ROOT = ROOT / "docs/benchmarks/archive/results/qe_workload_revalidation"
DEFAULT_CPU_SHELL_AGGREGATE_PATH = (
    ROOT / "docs/benchmarks/archive/results/qe_cpu_shell_aggregate_extract_20260402.json"
)
DEFAULT_ARCHITECTURE_TEMPLATE_DIR = ROOT / "docs/architecture/architecture_templates"
DEFAULT_FAST_LAYER_PROXY_ASSUMPTIONS_PATH = (
    ROOT / "docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json"
)
GRAPH_SCHEMA_PATH = ROOT / "docs/architecture/qe_ic_graph_schema_v0.json"
GRAPH_EXPORT_EXAMPLES_PATH = ROOT / "docs/architecture/qe_ic_graph_export_examples_v0.json"
GRAPH_SEED_TEMPLATES_PATH = ROOT / "docs/architecture/qe_ic_graph_seed_templates_v0.json"
DEFAULT_GOLD_SUMMARY_JSON_NAME = "qe_gold_gate_summary_v0.json"
DEFAULT_GOLD_SUMMARY_MD_NAME = "qe_gold_gate_summary_v0.md"
DEFAULT_STAGE_A_COVERAGE_MANIFEST_NAME = "stage_a_coverage_manifest_v0.json"
WORKLOAD_GROUP_CONTRACT_PATH = (
    ROOT / "docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md"
)
FAIRNESS_POWER_CONTRACT_PATH = (
    ROOT / "docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md"
)
OBSERVABILITY_CONTRACT_PATH = (
    ROOT / "docs/benchmarks/qe_simulator_board_observability_contract_v0.md"
)
ALGORITHM_REWRITE_MANIFEST_CONTRACT_PATH = (
    ROOT / "docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md"
)
CPU_GPU_BASELINE_RUNBOOK_PATH = (
    ROOT / "docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md"
)
OPTIMIZED_SYSTEM_DELTA_PATH = (
    ROOT / "docs/architecture/qe_system_optimized_delta_20260413.md"
)
RY_TO_EV = 13.605693009

PHASE1_WORKLOAD_GROUP_ID = "qe_fpga_phase1_workload_group_v0"
PHASE1_FAIRNESS_POLICY_ID = "qe_cpu_gpu_fpga_fairness_and_power_contract_v0"
PHASE1_POWER_BOUNDARY_ID = "whole_node_steady_state_single_cpu_single_accelerator_v0"
PHASE1_OBSERVABILITY_CONTRACT_ID = "qe_simulator_board_observability_contract_v0"
PHASE1_REWRITE_MANIFEST_ID = "qe_algorithm_rewrite_manifest_v0"

CPU_SHELL_BASELINE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
PROXY_ASSUMPTION_CACHE: dict[str, dict[str, Any]] = {}
GRAPH_SCHEMA_VERSION_CACHE: dict[str, str] = {}
GRAPH_EXPORT_EXAMPLES_CACHE: dict[str, dict[str, Any]] = {}
GRAPH_SEED_TEMPLATE_CACHE: dict[str, dict[tuple[str, str, str, str, str], dict[str, Any]]] = {}
IC_SIGNATURE_MATRIX_PATH = ROOT / "docs/benchmarks/qe_ic_case_signature_matrix_v0.json"

LEAF_COMPONENT_ORDER = [
    "near_sram_support",
    "context_loader",
    "digit_serial_input_boundary",
    "conjugate_sign_selector",
    "cim_operator_subchain",
    "cim_array_core",
    "residue_3m_core",
    "coefficient_accumulator",
    "near_sram_coeff_buffer",
    "near_sram_row_buffer",
    "row_merge_tree",
    "reduction_closure_engine",
]

CONTROL_COMPONENT_ORDER = [
    "system_container",
    "host_controller",
    "chip_execution_facade",
    "cluster_flow_executor",
    "episode_controller",
    "command_scheduler",
]

CLUSTER_COMPONENT_GROUPS = {
    "cluster_a": [
        "near_memory_domain",
        "near_sram_support",
        "context_loader",
        "digit_serial_input_boundary",
        "conjugate_sign_selector",
        "cim_operator_subchain",
        "cim_array_core",
        "residue_3m_core",
        "coefficient_accumulator",
        "near_sram_coeff_buffer",
        "near_sram_row_buffer",
        "row_merge_tree",
        "fft_unit",
        "cim_array",
    ],
    "cluster_b": [
        "near_memory_domain",
        "near_sram_support",
        "reduction_closure_engine",
        "reduction_unit",
    ],
    "cluster_c": [
        "diag_unit",
        "vector_diag_companion",
    ],
    "cluster_d": [
        "refresh_unit",
    ],
}

QE_GOLD_GATE_CONTRACT = {
    "canonical_gold_matrix_id": "qe_canonical_gold_matrix_v0",
    "canonical_gold_matrix_version": "2026-04-13",
    "canonical_gold_workloads": [
        "si8_pbe_nc",
        "si8_pbe_uspp",
    ],
    "first_priority_convergence_case": "si8_pbe_nc",
    "first_priority_convergence_family": "F1",
    "first_priority_convergence_family_rationale": (
        "host_cpu_fallback is the least-coupled first-pass target relative to QE CPU-side behavior."
    ),
    "required_field_order": [
        "final_total_energy_ry",
        "final_converged",
        "final_residual_threshold_reached",
    ],
}

GOLD_STATUS_TAXONOMY = [
    "pass",
    "mismatch",
    "baseline_missing",
    "baseline_normalization_error",
    "candidate_missing",
    "model_error",
    "compare_error",
    "pending",
    "not_required",
]

FAMILY_PROFILES = {
    "F1": {
        "label": "Host-heavy / Single-hotpath",
        "canonical_diag_policy": "cpu_only",
        "canonical_offload_scope": "single_hotpath",
        "canonical_resident_policy": "fit_first",
        "canonical_partition_strategy": "single_hotpath_partition",
        "complexity_proxy": "low",
        "recommended_cpu_device_split": (
            "CPU owns outer SCF + diag; hardware owns h_psi/s_psi and reduced build only."
        ),
        "recommended_operator_set": ["h_psi", "s_psi", "build_h_sub", "build_s_sub"],
    },
    "F2": {
        "label": "Balanced hybrid / Multi-operator pipeline",
        "canonical_diag_policy": "device_first_fallback",
        "canonical_offload_scope": "balanced",
        "canonical_resident_policy": "fit_first",
        "canonical_partition_strategy": "operator__build__diag__refresh",
        "complexity_proxy": "medium",
        "recommended_cpu_device_split": (
            "CPU owns outer SCF + exception paths; hardware owns hot inner-loop pipeline with diag fallback."
        ),
        "recommended_operator_set": [
            "h_psi",
            "s_psi",
            "build_h_sub",
            "build_s_sub",
            "refresh",
            "residual",
        ],
    },
    "F3": {
        "label": "Device-heavy / Full inner-loop offload",
        "canonical_diag_policy": "aggressive_device",
        "canonical_offload_scope": "device_heavy",
        "canonical_resident_policy": "spill_tolerant",
        "canonical_partition_strategy": "operator__build__diag__refresh",
        "complexity_proxy": "high",
        "recommended_cpu_device_split": (
            "CPU owns outer SCF + final convergence check; hardware owns most inner-loop stages."
        ),
        "recommended_operator_set": [
            "h_psi",
            "s_psi",
            "build_h_sub",
            "build_s_sub",
            "diag",
            "refresh",
            "residual",
            "p_next_update",
        ],
    },
}

CANDIDATE_FAMILIES = ["F1", "F2", "F3", "F4", "F5", "custom"]
RUNTIME_PROJECTION_FAMILIES = ["F1", "F2", "F3", "none", "reserved"]
EVALUATOR_BACKENDS = [
    "analytical_stub",
    "systemc_timed_functional",
    "trace_proxy",
    "qe_gold_compare",
    "gem5_systemc_cosim_stub",
    "reserved",
]
FIDELITY_CLASSES = [
    "stub",
    "projection_only",
    "timed_functional_proxy",
    "trace_calibrated_proxy",
    "correctness_capable",
    "measured",
    "reserved",
]
SUPPORT_STATUSES = [
    "native_runtime_supported",
    "projected_runtime_supported",
    "projection_only",
    "stub_reserved",
    "unsupported",
]

DIAG_POLICIES = [
    "cpu_only",
    "device_first_fallback",
    "aggressive_device",
]

OFFLOAD_SCOPES = [
    "single_hotpath",
    "balanced",
    "device_heavy",
]

RESIDENT_POLICIES = [
    "fit_first",
    "spill_tolerant",
]

PARTITION_STRATEGIES = [
    "single_hotpath_partition",
    "operator_build_fused__diag__refresh",
    "operator__build__diag__refresh",
    "operator__build_diag_fused__refresh",
    "operator_build_fused__diag_refresh_fused",
]

DEFAULT_WORKLOADS = {
    "si4_pbe_uspp_small": {
        "workload_id": "si4_pbe_uspp_small",
        "label": "QE small-Si proxy",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "USPP-heavy",
        "lane": "qe_next_stage_mainline",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "si8_pbe_uspp": {
        "workload_id": "si8_pbe_uspp",
        "label": "QE USPP-heavy",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "USPP-heavy",
        "lane": "qe_gold",
        "gold_required": True,
        "first_priority_convergence_case": False,
    },
    "si8_pbe_nc": {
        "workload_id": "si8_pbe_nc",
        "label": "QE NC-light",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "NC-light",
        "lane": "qe_gold",
        "gold_required": True,
        "first_priority_convergence_case": True,
    },
    "graphene_pbe_uspp": {
        "workload_id": "graphene_pbe_uspp",
        "label": "QE graphene USPP 2D proxy",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "2D-USPP",
        "lane": "qe_next_stage_mainline",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "graphene_pbe_paw": {
        "workload_id": "graphene_pbe_paw",
        "label": "QE graphene PAW 2D coverage",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "2D-PAW",
        "lane": "qe_generalization",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "au_slab_subspace": {
        "workload_id": "au_slab_subspace",
        "label": "QE Au slab interface signature coverage",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "slab-interface-USPP",
        "lane": "qe_signature_stage_b",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "sic32_subspace": {
        "workload_id": "sic32_subspace",
        "label": "QE SiC32 wide-bandgap signature coverage",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "wide-bandgap-USPP",
        "lane": "qe_signature_stage_b",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "h2_tiny": {
        "workload_id": "h2_tiny",
        "label": "QE tiny-H2 molecule",
        "software_family": "QE",
        "flow_family": "QE_SCF",
        "trait_bucket": "molecular-USPP",
        "lane": "qe_generalization",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "vasp_blocked_davidson_paw_heavy": {
        "workload_id": "vasp_blocked_davidson_paw_heavy",
        "label": "VASP PAW-heavy",
        "software_family": "VASP",
        "flow_family": "BLOCKED_DAVIDSON",
        "trait_bucket": "PAW-heavy",
        "lane": "portability",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
    "cp2k_qs_ot_small_batch": {
        "workload_id": "cp2k_qs_ot_small_batch",
        "label": "CP2K OT-like small batch",
        "software_family": "CP2K",
        "flow_family": "QS_OT",
        "trait_bucket": "NC-light",
        "lane": "portability",
        "gold_required": False,
        "first_priority_convergence_case": False,
    },
}


def load_ic_signature_case_map() -> dict[str, dict[str, Any]]:
    if not IC_SIGNATURE_MATRIX_PATH.exists():
        return {}
    payload = json.loads(IC_SIGNATURE_MATRIX_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    return {str(item["machine_workload_id"]): item for item in cases}


IC_SIGNATURE_CASE_MAP = load_ic_signature_case_map()
for workload_id, workload in DEFAULT_WORKLOADS.items():
    signature = IC_SIGNATURE_CASE_MAP.get(workload_id)
    if signature is None:
        continue
    workload["signature_id"] = signature.get("signature_id")
    workload["property_target"] = signature.get("property_target")
    workload["pseudopotential_family"] = signature.get("pseudopotential_family")
    workload["solver_path_class"] = signature.get("solver_path_class")
    workload["workload_topology"] = signature.get("workload_topology")
    workload["post_scf_extension_level"] = signature.get("post_scf_extension_level")
    operator_signature = signature.get("operator_signature", {})
    workload["projector_pressure"] = operator_signature.get("projector_pressure")
    workload["nonlocal_pressure"] = operator_signature.get("nonlocal_pressure")
    workload["generalized_ratio_bucket"] = operator_signature.get("generalized_ratio_bucket")
    workload["diag_dominance"] = operator_signature.get("diag_dominance")
    workload["fft_grid_pressure"] = operator_signature.get("fft_grid_pressure")

EXCLUDED_ENGINEERING_KNOBS = [
    "dma_width",
    "buffer_depth",
    "bram_uram_hbm_budget",
]

CSV_FIELDS = [
    "schema_version",
    "run_id",
    "generated_at_utc",
    "result_id",
    "result_status",
    "source_kind",
    "workload_id",
    "workload_label",
    "software_family",
    "flow_family",
    "trait_bucket",
    "lane",
    "gold_required",
    "first_priority_convergence_case",
    "signature_id",
    "property_target",
    "pseudopotential_family",
    "solver_path_class",
    "workload_topology",
    "post_scf_extension_level",
    "projector_pressure",
    "nonlocal_pressure",
    "generalized_ratio_bucket",
    "diag_dominance",
    "fft_grid_pressure",
    "family",
    "candidate_family",
    "runtime_projection_family",
    "evaluator_backend",
    "fidelity_class",
    "support_status",
    "executor_claim_allowed",
    "native_runtime_evidence_path",
    "projection_reason",
    "future_backend_note",
    "claim_boundary",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "partition_strategy",
    "canonical_profile_match",
    "architecture_template_id",
    "candidate_id",
    "projected_config_path",
    "template_family",
    "template_validation_status",
    "template_risk_level",
    "template_tags",
    "template_artifact_sha256",
    "design_space_spec_id",
    "design_space_spec_sha256",
    "qe_baseline_id",
    "workload_group_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "algorithm_rewrite_manifest_id",
    "algorithm_contract_deviation",
    "correctness_status",
    "gold_pass",
    "convergence_comparable_pass",
    "final_total_energy_match",
    "residual_threshold_state_match",
    "converged_state_match",
    "required_field_failures",
    "baseline_scf_iterations",
    "candidate_scf_iterations",
    "final_total_energy_abs_err_ev",
    "final_total_energy_rel_err",
    "time_to_convergence_s",
    "speedup_to_convergence",
    "energy_to_convergence_j",
    "avg_system_power_proxy_w",
    "scf_iterations_to_convergence",
    "bytes_moved_to_convergence",
    "fallback_count_to_convergence",
    "device_busy_ref_cycles",
    "dma_ref_cycles",
    "host_assist_ref_cycles",
    "resident_reuse_hits",
    "spill_ratio",
    "fallback_ratio",
    "complexity_proxy",
    "runtime_last_diag_path",
    "runtime_last_support_grid_mode",
    "runtime_last_workload_bucket",
    "runtime_last_band_count",
    "runtime_last_panel_count",
    "runtime_configured_max_inner_steps",
    "runtime_realized_inner_steps",
    "runtime_last_max_diag_condition_estimate",
    "runtime_spill_active_count",
    "runtime_host_cpu_fallback_count",
    "graph_seed_template_id",
    "graph_schema_version",
    "graph_module_instance_count",
    "graph_link_count",
    "graph_flow_count",
    "graph_export_authority",
    "graph_lossless_export_pass",
    "graph_topology_style",
    "graph_control_plane_summary",
    "graph_datapath_stage_summary",
    "graph_key_component_refs_summary",
    "graph_leaf_component_refs_summary",
    "graph_bottleneck_component_summary",
    "graph_leaf_bottleneck_component_summary",
    "graph_risk_driver_component_summary",
    "graph_component_score_summary",
    "graph_component_score_source",
    "graph_execution_plan_summary",
    "graph_cluster_cycle_summary",
    "graph_component_score_signal_summary",
    "graph_iteration_behavior_summary",
    "graph_dataflow_bottleneck_summary",
    "graph_mapping_risk_summary",
    "graph_evidence_path",
    "E_host_j",
    "E_device_runtime_j",
    "E_dma_j",
    "E_hardware_datapath_j",
    "E_idle_static_j",
    "speedup_range_lower",
    "speedup_range_upper",
    "energy_range_lower_j",
    "energy_range_upper_j",
    "projection_confidence",
    "assumption_set_id",
    "ranking_grade_ready",
    "projection_grade_ready",
    "model_run_id",
    "stdout_path",
    "metrics_path",
    "compare_report_path",
    "raw_trace_paths",
    "stub_reason",
]

REQUIRED_RANKING_PRIMARY_METRICS = [
    "time_to_convergence_s",
    "speedup_to_convergence",
    "energy_to_convergence_j",
    "bytes_moved_to_convergence",
]

REQUIRED_RANKING_SECONDARY_METRICS = [
    "fallback_ratio",
    "spill_ratio",
]

PROJECTION_ONLY_TEMPLATE_FAMILIES = {"F4", "F5", "custom"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(ts: datetime) -> str:
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_run_id(ts: datetime) -> str:
    return "systemc_architecture_family_dse_" + ts.strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enumerate the v1 SystemC architecture-family DSE sweep space and emit JSON/CSV "
            "stub bundles for later model integration."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for emitted JSON/CSV artifacts.",
    )
    parser.add_argument(
        "--json-name",
        default="systemc_architecture_family_dse_bootstrap_v0.json",
        help="Output JSON bundle filename.",
    )
    parser.add_argument(
        "--csv-name",
        default="systemc_architecture_family_dse_bootstrap_v0.csv",
        help="Output CSV filename.",
    )
    parser.add_argument(
        "--coverage-manifest-name",
        default=DEFAULT_STAGE_A_COVERAGE_MANIFEST_NAME,
        help="Output Stage-A coverage/readiness manifest filename.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run id. Defaults to a UTC timestamp-derived id.",
    )
    parser.add_argument(
        "--workloads",
        nargs="*",
        default=list(DEFAULT_WORKLOADS),
        help="Subset of workload ids to enumerate. Defaults to the v1 matrix.",
    )
    parser.add_argument(
        "--case-pack",
        type=Path,
        default=None,
        help="Optional case-pack descriptor bundle; when provided, workload rows are read from it instead of DEFAULT_WORKLOADS.",
    )
    parser.add_argument(
        "--case-pack-sections",
        nargs="*",
        default=None,
        help=(
            "Optional subset of case-pack sections to consume. "
            "Use this when the same workload_id appears in multiple sections."
        ),
    )
    parser.add_argument(
        "--gold-required-only",
        action="store_true",
        help="Restrict the sweep to workloads that require QE gold comparison.",
    )
    parser.add_argument(
        "--families",
        nargs="*",
        default=None,
        help="Optional subset of architecture families to enumerate.",
    )
    parser.add_argument(
        "--diag-policies",
        nargs="*",
        default=None,
        help="Optional subset of diag policies to enumerate.",
    )
    parser.add_argument(
        "--offload-scopes",
        nargs="*",
        default=None,
        help="Optional subset of offload scopes to enumerate.",
    )
    parser.add_argument(
        "--resident-policies",
        nargs="*",
        default=None,
        help="Optional subset of resident policies to enumerate.",
    )
    parser.add_argument(
        "--partition-strategies",
        nargs="*",
        default=None,
        help="Optional subset of partition strategies to enumerate.",
    )
    parser.add_argument(
        "--canonical-only",
        action="store_true",
        help="Emit only canonical family-profile points instead of the full cross product.",
    )
    parser.add_argument(
        "--template-driven",
        action="store_true",
        help="Enumerate architecture templates instead of the legacy F1/F2/F3 axis cross product.",
    )
    parser.add_argument(
        "--architecture-template-dir",
        type=Path,
        default=DEFAULT_ARCHITECTURE_TEMPLATE_DIR,
        help=f"Directory containing architecture template JSON files (default: {DEFAULT_ARCHITECTURE_TEMPLATE_DIR}).",
    )
    parser.add_argument(
        "--architecture-template-ids",
        nargs="*",
        default=None,
        help="Optional template ids to include. Defaults to all templates in --architecture-template-dir.",
    )
    parser.add_argument(
        "--design-space-spec",
        type=Path,
        default=None,
        help="Optional design-space spec JSON; parsed for metadata/hash only in this scaffold mode.",
    )
    parser.add_argument(
        "--emit-projected-configs",
        action="store_true",
        help="Emit projected SystemC ArchitectureConfig sidecars for template-driven rows.",
    )
    parser.add_argument(
        "--max-design-points",
        type=int,
        default=None,
        help="Optional cap applied after enumeration/filtering.",
    )
    parser.add_argument(
        "--assumption-set-id",
        default="qe_next_stage_phase_v0",
        help="Assumption set id attached to all projection placeholders.",
    )
    parser.add_argument(
        "--qe-tolerance-schema-id",
        default="qe_gold_numerical_tolerance_schema_v0",
        help="QE numerical tolerance schema id carried into each row.",
    )
    parser.add_argument(
        "--source-model",
        default="model/qe_band_solver_model",
        help="Model path or identifier to record in the bundle metadata.",
    )
    parser.add_argument(
        "--source-kind",
        default="stub",
        choices=["stub", "timed_functional_proxy", "trace_calibrated_proxy", "measured", "mixed"],
        help="Source kind label attached to emitted rows.",
    )
    parser.add_argument(
        "--execute-model",
        action="store_true",
        help="Run the SystemC runnable model for each enumerated design point and fill result rows.",
    )
    parser.add_argument(
        "--model-bin",
        type=Path,
        default=DEFAULT_MODEL_BIN,
        help=f"Runnable model binary path (default: {DEFAULT_MODEL_BIN}).",
    )
    parser.add_argument(
        "--model-max-scf-iters",
        type=int,
        default=1,
        help="QEBS_MAX_SCF_ITERS value used when --execute-model is enabled.",
    )
    parser.add_argument(
        "--auto-match-baseline-iters",
        action="store_true",
        help=(
            "When running QE gold workloads, derive QEBS_MAX_SCF_ITERS from the canonical "
            "baseline scf_iterations field instead of using --model-max-scf-iters."
        ),
    )
    parser.add_argument(
        "--cpu-shell-aggregate-path",
        type=Path,
        default=DEFAULT_CPU_SHELL_AGGREGATE_PATH,
        help=(
            "Measured QE CPU shell aggregate JSON used to derive convergence-scope "
            "speedup_to_convergence and fast-layer SCF-iteration budgets for mainline QE cases."
        ),
    )
    parser.add_argument(
        "--fast-layer-proxy-assumptions-path",
        type=Path,
        default=DEFAULT_FAST_LAYER_PROXY_ASSUMPTIONS_PATH,
        help="JSON contract that defines the fast-layer proxy energy assumption sets.",
    )
    parser.add_argument(
        "--compare-helper",
        type=Path,
        default=DEFAULT_COMPARE_HELPER,
        help=f"QE gold compare helper path (default: {DEFAULT_COMPARE_HELPER}).",
    )
    parser.add_argument(
        "--normalize-gold-helper",
        type=Path,
        default=DEFAULT_NORMALIZE_GOLD_HELPER,
        help=f"QE gold normalization helper path (default: {DEFAULT_NORMALIZE_GOLD_HELPER}).",
    )
    parser.add_argument(
        "--gold-baseline-root",
        type=Path,
        default=DEFAULT_GOLD_BASELINE_ROOT,
        help=f"Root directory containing QE metadata/stdout cases (default: {DEFAULT_GOLD_BASELINE_ROOT}).",
    )
    parser.add_argument(
        "--fail-on-gold-mismatch",
        action="store_true",
        help="Return nonzero when any gold-required row fails, errors, or lacks a compare result.",
    )
    parser.add_argument(
        "--list-workloads",
        action="store_true",
        help="List known workload ids and exit.",
    )
    return parser.parse_args()


def validate_workloads(workload_ids: list[str]) -> list[dict[str, object]]:
    bad = [workload_id for workload_id in workload_ids if workload_id not in DEFAULT_WORKLOADS]
    if bad:
        raise ValueError("Unknown workloads: " + ", ".join(bad))
    return [DEFAULT_WORKLOADS[workload_id] for workload_id in workload_ids]


def validate_axis_subset(name: str, requested: list[str] | None, allowed: list[str]) -> list[str]:
    if requested is None:
        return list(allowed)
    bad = [item for item in requested if item not in allowed]
    if bad:
        raise ValueError(f"Unknown {name}: " + ", ".join(bad))
    return list(requested)


def filter_gold_required_workloads(workloads: list[dict[str, object]]) -> list[dict[str, object]]:
    return [workload for workload in workloads if bool(workload["gold_required"])]


def load_cpu_shell_baselines(path: Path) -> dict[str, dict[str, Any]]:
    cache_key = str(path.resolve())
    if cache_key in CPU_SHELL_BASELINE_CACHE:
        return CPU_SHELL_BASELINE_CACHE[cache_key]
    if not path.exists():
        CPU_SHELL_BASELINE_CACHE[cache_key] = {}
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        CPU_SHELL_BASELINE_CACHE[cache_key] = {}
        return {}

    baselines: dict[str, dict[str, Any]] = {}
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get("case_id"), str):
            baselines[item["case_id"]] = item
    CPU_SHELL_BASELINE_CACHE[cache_key] = baselines
    return baselines


def get_cpu_shell_baseline(
    workload: dict[str, object], args: argparse.Namespace
) -> dict[str, Any] | None:
    if workload.get("software_family") != "QE":
        return None
    baselines = load_cpu_shell_baselines(args.cpu_shell_aggregate_path)
    return baselines.get(str(workload["workload_id"]))


def load_proxy_assumption_payload(path: Path) -> dict[str, Any]:
    cache_key = str(path.resolve())
    if cache_key in PROXY_ASSUMPTION_CACHE:
        return PROXY_ASSUMPTION_CACHE[cache_key]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid fast-layer proxy assumption payload: {path}")
    PROXY_ASSUMPTION_CACHE[cache_key] = payload
    return payload


def split_cli_values(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    out: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def load_template_projector() -> Any:
    benchmarks_dir = Path(__file__).resolve().parent
    if str(benchmarks_dir) not in sys.path:
        sys.path.insert(0, str(benchmarks_dir))
    from template_to_systemc_config import TemplateProjector

    return TemplateProjector()


def template_basic_validation_status(template: dict[str, Any]) -> str:
    required_fields = ["template_id", "template_version", "family", "clusters", "policies"]
    missing = [field for field in required_fields if field not in template]
    if missing:
        return "invalid:missing_" + ",".join(missing)
    clusters = template.get("clusters")
    policies = template.get("policies")
    if not isinstance(clusters, list) or not clusters:
        return "invalid:no_clusters"
    if not isinstance(policies, dict):
        return "invalid:no_policies"
    enabled_clusters = [cluster for cluster in clusters if isinstance(cluster, dict) and cluster.get("enabled", True)]
    if not enabled_clusters:
        return "invalid:no_enabled_clusters"
    return str(template.get("notes", {}).get("validation_status") or "basic_valid")


def template_runtime_family(template_family: str) -> str:
    if template_family in FAMILY_PROFILES:
        return template_family
    return "F2"


def candidate_family_for_template(template: dict[str, Any]) -> str:
    family = str(template.get("family") or template.get("base_family") or "custom")
    return family if family in CANDIDATE_FAMILIES else "custom"


def runtime_projection_family_for_candidate(candidate_family: str) -> str:
    if candidate_family in FAMILY_PROFILES:
        return candidate_family
    return "F2"


def evaluator_backend_for_row(args: argparse.Namespace, support_status: str) -> str:
    source_model = str(getattr(args, "source_model", ""))
    source_kind = str(getattr(args, "source_kind", "stub"))
    if "gem5" in source_model.lower() or source_kind == "gem5_systemc_cosim_stub":
        return "gem5_systemc_cosim_stub"
    if support_status == "stub_reserved":
        return "reserved"
    if source_kind == "stub":
        return "analytical_stub"
    if source_kind == "timed_functional_proxy":
        return "systemc_timed_functional"
    if source_kind == "trace_calibrated_proxy":
        return "trace_proxy"
    if source_kind == "measured":
        return "qe_gold_compare"
    return "reserved"


def support_status_for_candidate(
    candidate_family: str,
    runtime_projection_family: str,
    template_tags: list[str],
    args: argparse.Namespace,
    native_runtime_evidence_path: str | None = None,
) -> str:
    source_model = str(getattr(args, "source_model", ""))
    source_kind = str(getattr(args, "source_kind", "stub"))
    if "gem5" in source_model.lower() or source_kind == "gem5_systemc_cosim_stub":
        return "stub_reserved"
    tag_set = {str(tag) for tag in template_tags}
    if "projection_only" in tag_set or candidate_family in PROJECTION_ONLY_TEMPLATE_FAMILIES:
        return "projection_only"
    if native_runtime_evidence_path:
        if candidate_family == runtime_projection_family:
            return "native_runtime_supported"
        if runtime_projection_family not in {"none", "reserved"}:
            return "projected_runtime_supported"
    return "projection_only"


def fidelity_class_for_row(args: argparse.Namespace, support_status: str) -> str:
    source_kind = str(getattr(args, "source_kind", "stub"))
    if support_status == "stub_reserved":
        return "reserved"
    if support_status == "projection_only":
        return "projection_only"
    if source_kind == "stub":
        return "stub"
    if source_kind == "timed_functional_proxy":
        return "timed_functional_proxy"
    if source_kind == "trace_calibrated_proxy":
        return "trace_calibrated_proxy"
    if source_kind == "measured":
        return "measured"
    return "reserved"


def projection_reason_for_row(
    candidate_family: str,
    runtime_projection_family: str,
    support_status: str,
    template_tags: list[str],
    native_runtime_evidence_path: str | None,
) -> str | None:
    if support_status == "stub_reserved":
        return None
    if support_status == "native_runtime_supported":
        return None
    if candidate_family != runtime_projection_family:
        return (
            f"{candidate_family} candidate semantics are evaluated through the current "
            f"{runtime_projection_family}-compatible runtime projection."
        )
    if "projection_only" in {str(tag) for tag in template_tags}:
        return "Template is explicitly marked projection_only in Stage-A metadata."
    if not native_runtime_evidence_path:
        return "No executable runtime evidence artifact is attached for this row."
    return "Candidate uses an executable proxy path with mapped runtime semantics."


def future_backend_note_for_candidate(candidate_family: str, evaluator_backend: str) -> str | None:
    if evaluator_backend == "gem5_systemc_cosim_stub":
        return "gem5/SystemC co-simulation is reserved metadata only until an executable co-sim artifact exists."
    if candidate_family == "F4":
        return "Native F4 fused/hybrid CIM+DSP executor is future work."
    if candidate_family == "F5":
        return "Native F5 CGRA/dataflow executor is future work."
    if candidate_family == "custom":
        return "Native custom-family executor support is future work and must be evidenced per template."
    return None


def support_evidence_for_row(
    candidate_family: str,
    runtime_projection_family: str,
    support_status: str,
    evaluator_backend: str,
    template_tags: list[str],
    native_runtime_evidence_path: str | None = None,
) -> dict[str, object]:
    executor_claim_allowed = support_status in {
        "native_runtime_supported",
        "projected_runtime_supported",
    }
    projection_reason = projection_reason_for_row(
        candidate_family,
        runtime_projection_family,
        support_status,
        template_tags,
        native_runtime_evidence_path,
    )
    claim_boundary = (
        "Executor/proxy path claim only; final architecture, public performance, CPU/GPU/FPGA, "
        "and board-power claims require adjudicator and closure evidence."
        if executor_claim_allowed
        else "Stage-A evidence only; no executor, final architecture, public performance, CPU/GPU/FPGA, or board-power claim."
    )
    return {
        "executor_claim_allowed": executor_claim_allowed,
        "native_runtime_evidence_path": native_runtime_evidence_path if support_status == "native_runtime_supported" else None,
        "projection_reason": projection_reason,
        "future_backend_note": future_backend_note_for_candidate(candidate_family, evaluator_backend),
        "claim_boundary": claim_boundary,
    }


def validate_evidence_tuple(row: dict[str, object]) -> list[str]:
    errors: list[str] = []
    support_evidence = row.get("support_evidence", {})
    if not isinstance(support_evidence, dict):
        return ["support_evidence_missing_or_invalid"]
    evaluator_backend = str(row.get("evaluator_backend") or "")
    fidelity_class = str(row.get("fidelity_class") or "")
    support_status = str(row.get("support_status") or "")
    runtime_projection_family = str(row.get("runtime_projection_family") or "")
    candidate_family = str(row.get("candidate_family") or "")
    executor_claim_allowed = support_evidence.get("executor_claim_allowed") is True
    native_path = support_evidence.get("native_runtime_evidence_path")
    projection_reason = support_evidence.get("projection_reason")
    artifacts = row.get("artifacts", {})
    metrics_path = artifacts.get("metrics_path") if isinstance(artifacts, dict) else None
    compare_path = artifacts.get("compare_report_path") if isinstance(artifacts, dict) else None

    if candidate_family not in CANDIDATE_FAMILIES:
        errors.append("candidate_family_invalid")
    if runtime_projection_family not in RUNTIME_PROJECTION_FAMILIES:
        errors.append("runtime_projection_family_invalid")
    if evaluator_backend not in EVALUATOR_BACKENDS:
        errors.append("evaluator_backend_invalid")
    if fidelity_class not in FIDELITY_CLASSES:
        errors.append("fidelity_class_invalid")
    if support_status not in SUPPORT_STATUSES:
        errors.append("support_status_invalid")

    if evaluator_backend == "gem5_systemc_cosim_stub":
        if fidelity_class != "reserved":
            errors.append("gem5_stub_requires_reserved_fidelity")
        if support_status != "stub_reserved":
            errors.append("gem5_stub_requires_stub_reserved_support")
        if executor_claim_allowed:
            errors.append("gem5_stub_cannot_allow_executor_claim")
        if native_path:
            errors.append("gem5_stub_cannot_have_native_evidence")

    if support_status == "projection_only":
        if fidelity_class != "projection_only":
            errors.append("projection_only_requires_projection_fidelity")
        if executor_claim_allowed:
            errors.append("projection_only_cannot_allow_executor_claim")
        if not projection_reason:
            errors.append("projection_only_requires_projection_reason")

    if support_status == "projected_runtime_supported":
        if runtime_projection_family in {"none", "reserved", ""}:
            errors.append("projected_runtime_supported_requires_runtime_projection")
        if not executor_claim_allowed:
            errors.append("projected_runtime_supported_requires_executor_claim")
        if not projection_reason:
            errors.append("projected_runtime_supported_requires_projection_reason")

    if support_status == "native_runtime_supported":
        if not native_path:
            errors.append("native_runtime_supported_requires_evidence_artifact")
        if candidate_family != runtime_projection_family:
            errors.append("native_runtime_supported_requires_candidate_runtime_match")
        if not executor_claim_allowed:
            errors.append("native_runtime_supported_requires_executor_claim")

    if fidelity_class == "measured" and not (native_path or metrics_path or compare_path):
        errors.append("measured_requires_evidence_artifact")

    return errors


def assert_valid_evidence_tuple(row: dict[str, object]) -> None:
    errors = validate_evidence_tuple(row)
    if errors:
        raise ValueError("invalid equal-candidate evidence tuple: " + ", ".join(errors))


def apply_equal_candidate_fields(
    row: dict[str, object],
    args: argparse.Namespace,
    candidate_family: str,
    runtime_projection_family: str,
    template_tags: list[str] | None = None,
    native_runtime_evidence_path: str | None = None,
) -> None:
    tags = [str(tag) for tag in (template_tags or [])]
    support_status = support_status_for_candidate(
        candidate_family,
        runtime_projection_family,
        tags,
        args,
        native_runtime_evidence_path,
    )
    evaluator_backend = evaluator_backend_for_row(args, support_status)
    fidelity_class = fidelity_class_for_row(args, support_status)
    row["candidate_family"] = candidate_family
    row["runtime_projection_family"] = runtime_projection_family
    row["evaluator_backend"] = evaluator_backend
    row["fidelity_class"] = fidelity_class
    row["support_status"] = support_status
    row["support_evidence"] = support_evidence_for_row(
        candidate_family,
        runtime_projection_family,
        support_status,
        evaluator_backend,
        tags,
        native_runtime_evidence_path,
    )
    assert_valid_evidence_tuple(row)


def load_architecture_templates(
    template_dir: Path,
    requested_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if not template_dir.exists():
        raise FileNotFoundError(f"Architecture template directory not found: {template_dir}")
    by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for template_path in sorted(template_dir.glob("*.json")):
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        template_id = str(payload.get("template_id") or template_path.stem)
        payload["_template_path"] = str(template_path)
        payload["_template_sha256"] = file_sha256(template_path)
        payload["_template_validation_status"] = template_basic_validation_status(payload)
        by_id[template_id] = (template_path, payload)

    ids = split_cli_values(requested_ids)
    if ids:
        missing = [template_id for template_id in ids if template_id not in by_id]
        if missing:
            raise ValueError("Unknown architecture template ids: " + ", ".join(missing))
        return [by_id[template_id][1] for template_id in ids]
    return [payload for _, payload in sorted(by_id.values(), key=lambda item: str(item[1].get("template_id", "")))]


def load_design_space_spec_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "schema_version": None,
        "design_space_spec_id": None,
        "sha256": None,
        "artifact_ids": [],
    }
    if not path.exists():
        return summary
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary["sha256"] = file_sha256(path)
    summary["schema_version"] = payload.get("schema_version")
    summary["design_space_spec_id"] = (
        payload.get("design_space_spec_id")
        or payload.get("design_space_id")
        or payload.get("spec_id")
        or payload.get("id")
    )
    artifact_ids: list[str] = []
    artifacts = payload.get("artifacts") or payload.get("artifact_manifest") or []
    if isinstance(artifacts, dict):
        artifact_ids.extend(str(key) for key in sorted(artifacts))
    elif isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict):
                artifact_id = artifact.get("artifact_id") or artifact.get("id") or artifact.get("path")
                if artifact_id is not None:
                    artifact_ids.append(str(artifact_id))
            elif artifact is not None:
                artifact_ids.append(str(artifact))
    summary["artifact_ids"] = artifact_ids
    return summary


def load_graph_schema_version(path: Path) -> str:
    cache_key = str(path.resolve())
    if cache_key in GRAPH_SCHEMA_VERSION_CACHE:
        return GRAPH_SCHEMA_VERSION_CACHE[cache_key]
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = str(payload.get("properties", {}).get("graph_schema_version", {}).get("const", "unknown"))
    GRAPH_SCHEMA_VERSION_CACHE[cache_key] = version
    return version


def load_graph_export_examples(path: Path) -> dict[str, Any]:
    cache_key = str(path.resolve())
    if cache_key in GRAPH_EXPORT_EXAMPLES_CACHE:
        return GRAPH_EXPORT_EXAMPLES_CACHE[cache_key]
    payload = json.loads(path.read_text(encoding="utf-8"))
    examples = payload.get("examples", [])
    by_seed = {
        str(item["seed_template_id"]): item
        for item in examples
        if isinstance(item, dict) and isinstance(item.get("seed_template_id"), str)
    }
    GRAPH_EXPORT_EXAMPLES_CACHE[cache_key] = by_seed
    return by_seed


def load_graph_seed_templates(path: Path) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    cache_key = str(path.resolve())
    if cache_key in GRAPH_SEED_TEMPLATE_CACHE:
        return GRAPH_SEED_TEMPLATE_CACHE[cache_key]
    payload = json.loads(path.read_text(encoding="utf-8"))
    templates = payload.get("templates", [])
    by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in templates:
        if not isinstance(item, dict):
            continue
        join_keys = item.get("join_keys", {})
        key = (
            str(join_keys.get("family", "")),
            str(join_keys.get("diag_policy", "")),
            str(join_keys.get("offload_scope", "")),
            str(join_keys.get("resident_policy", "")),
            str(join_keys.get("partition_strategy", "")),
        )
        if all(key):
            by_key[key] = item
    GRAPH_SEED_TEMPLATE_CACHE[cache_key] = by_key
    return by_key


def graph_dataflow_bottleneck_summary(
    family: str,
    offload_scope: str,
    resident_policy: str,
    partition_strategy: str,
) -> str:
    if family == "F1" or offload_scope == "single_hotpath":
        return "host_to_fpga single-hotpath DMA handoff dominates"
    if resident_policy == "spill_tolerant":
        return "resident pressure and spill-mediated datapath reuse dominate"
    if partition_strategy == "operator__build__diag__refresh":
        return "operator-build-diag-refresh handoff dominates reduced-space dataflow"
    return "balanced multi-stage operator and transfer handoff dominates"


def graph_mapping_risk_summary(
    family: str,
    offload_scope: str,
    resident_policy: str,
) -> str:
    if family == "F3" or offload_scope == "device_heavy":
        return "higher mapping risk: device-heavy overlay may exceed current SSOT export envelope"
    if resident_policy == "spill_tolerant":
        return "moderate mapping risk: spill-tolerant policy adds sidecar-only memory semantics"
    return "low mapping risk: compatible with current family-scaffold export path"


def graph_key_component_refs(
    template: dict[str, Any],
    seed_template_id: str,
) -> list[str]:
    example = load_graph_export_examples(GRAPH_EXPORT_EXAMPLES_PATH).get(seed_template_id) or {}
    topology_summary = example.get("graph_topology_summary") or {}
    refs = topology_summary.get("key_component_refs")
    if isinstance(refs, list) and refs:
        return [str(ref) for ref in refs]
    preferred_order = [
        "system_container",
        "host_controller",
        "dma_channel",
        "chip_execution_facade",
        "cluster_flow_executor",
        "episode_controller",
        "command_scheduler",
        "near_memory_domain",
        *LEAF_COMPONENT_ORDER,
        "fft_unit",
        "cim_array",
        "reduction_unit",
        "diag_unit",
        "vector_diag_companion",
        "refresh_unit",
    ]
    present = {str(module.get("component_ref")) for module in template.get("modules", [])}
    return [component_ref for component_ref in preferred_order if component_ref in present]


def graph_leaf_component_refs(key_component_refs: list[str]) -> list[str]:
    return [component_ref for component_ref in LEAF_COMPONENT_ORDER if component_ref in key_component_refs]


def graph_control_plane_summary(
    placement: dict[str, Any],
    key_component_refs: list[str],
) -> str | None:
    control_plane = placement.get("control_plane")
    control_components = [
        component_ref
        for component_ref in key_component_refs
        if component_ref
        in {
            "system_container",
            "host_controller",
            "chip_execution_facade",
            "cluster_flow_executor",
            "episode_controller",
            "command_scheduler",
        }
    ]
    if control_plane and control_components:
        return f"{control_plane}: {', '.join(control_components)}"
    if control_plane:
        return str(control_plane)
    if control_components:
        return ", ".join(control_components)
    return None


def graph_datapath_stage_summary(key_component_refs: list[str]) -> str | None:
    datapath_order = [
        "near_memory_domain",
        *LEAF_COMPONENT_ORDER,
        "fft_unit",
        "cim_array",
        "reduction_unit",
        "diag_unit",
        "vector_diag_companion",
        "refresh_unit",
    ]
    stages = [component_ref for component_ref in datapath_order if component_ref in key_component_refs]
    return " -> ".join(stages) if stages else None


def graph_component_score_weights(
    family: str,
    resident_policy: str,
) -> dict[str, float]:
    if family == "F1":
        return {
            "dma_channel": 0.14,
            "chip_execution_facade": 0.08,
            "command_scheduler": 0.06,
            "context_loader": 0.08,
            "digit_serial_input_boundary": 0.06,
            "conjugate_sign_selector": 0.05,
            "cim_operator_subchain": 0.08,
            "cim_array_core": 0.12,
            "residue_3m_core": 0.10,
            "coefficient_accumulator": 0.06,
            "near_sram_coeff_buffer": 0.04,
            "near_sram_row_buffer": 0.04,
            "row_merge_tree": 0.05,
            "cim_array": 0.08,
            "diag_unit": 0.06,
        }
    if family == "F3" or resident_policy == "spill_tolerant":
        return {
            "episode_controller": 0.06,
            "command_scheduler": 0.04,
            "near_memory_domain": 0.06,
            "near_sram_support": 0.08,
            "context_loader": 0.06,
            "digit_serial_input_boundary": 0.04,
            "conjugate_sign_selector": 0.04,
            "cim_operator_subchain": 0.05,
            "cim_array_core": 0.09,
            "residue_3m_core": 0.08,
            "coefficient_accumulator": 0.05,
            "near_sram_coeff_buffer": 0.04,
            "near_sram_row_buffer": 0.04,
            "row_merge_tree": 0.05,
            "fft_unit": 0.04,
            "cim_array": 0.06,
            "reduction_closure_engine": 0.07,
            "reduction_unit": 0.05,
            "diag_unit": 0.05,
            "vector_diag_companion": 0.04,
            "refresh_unit": 0.05,
        }
    return {
        "episode_controller": 0.06,
        "command_scheduler": 0.04,
        "near_memory_domain": 0.06,
        "near_sram_support": 0.07,
        "context_loader": 0.06,
        "digit_serial_input_boundary": 0.04,
        "conjugate_sign_selector": 0.04,
        "cim_operator_subchain": 0.05,
        "cim_array_core": 0.09,
        "residue_3m_core": 0.08,
        "coefficient_accumulator": 0.05,
        "near_sram_coeff_buffer": 0.04,
        "near_sram_row_buffer": 0.04,
        "row_merge_tree": 0.05,
        "fft_unit": 0.05,
        "cim_array": 0.06,
        "reduction_closure_engine": 0.07,
        "reduction_unit": 0.06,
        "diag_unit": 0.05,
        "vector_diag_companion": 0.04,
    }


def graph_component_scores(
    family: str,
    key_component_refs: list[str],
    resident_policy: str,
) -> list[tuple[str, float]]:
    weights = graph_component_score_weights(family, resident_policy)
    present = [(component_ref, weight) for component_ref, weight in weights.items() if component_ref in key_component_refs]
    total = sum(weight for _, weight in present)
    if total <= 0.0:
        return []
    normalized = [(component_ref, weight / total) for component_ref, weight in present]
    return sorted(normalized, key=lambda item: (-item[1], item[0]))


def graph_component_score_summary(
    component_scores: list[tuple[str, float]],
    *,
    top_n: int = 6,
) -> str | None:
    if not component_scores:
        return None
    return ", ".join(f"{component_ref}={score:.2f}" for component_ref, score in component_scores[:top_n])


def graph_leaf_bottleneck_component_summary(
    component_scores: list[tuple[str, float]],
    *,
    top_n: int = 4,
) -> str | None:
    leafs = [(component_ref, score) for component_ref, score in component_scores if component_ref in LEAF_COMPONENT_ORDER]
    if not leafs:
        return None
    return ", ".join(component_ref for component_ref, _ in leafs[:top_n])


def signature_level_bias(level: Any) -> float:
    normalized = str(level or "").strip().lower()
    if normalized == "high":
        return 1.0
    if normalized == "medium":
        return 0.5
    return 0.0


def signature_descriptor(
    candidate: dict[str, Any],
    workload: dict[str, Any] | None,
) -> dict[str, str]:
    run_config = candidate.get("run_config", {})
    descriptor: dict[str, str] = {}
    for field in (
        "projector_pressure",
        "nonlocal_pressure",
        "generalized_ratio_bucket",
        "diag_dominance",
        "fft_grid_pressure",
    ):
        value = run_config.get(field)
        if value in (None, "") and workload is not None:
            value = workload.get(field)
        descriptor[field] = str(value or "")
    return descriptor


def apply_signature_biases(
    score_map: dict[str, float],
    signature: dict[str, str],
) -> list[str]:
    applied: list[str] = []

    def add_bias(
        signal_name: str,
        level: str,
        targets: list[str],
        scale: float,
    ) -> None:
        bias = signature_level_bias(level)
        if bias <= 0.0:
            return
        for component_ref in targets:
            if component_ref in score_map:
                score_map[component_ref] += scale * bias
        applied.append(f"{signal_name}={level}")

    add_bias(
        "projector",
        signature.get("projector_pressure", ""),
        ["near_memory_domain", "context_loader", "cim_operator_subchain", "cim_array_core", "residue_3m_core"],
        0.04,
    )
    add_bias(
        "nonlocal",
        signature.get("nonlocal_pressure", ""),
        ["digit_serial_input_boundary", "conjugate_sign_selector", "coefficient_accumulator", "near_sram_coeff_buffer"],
        0.03,
    )
    add_bias(
        "generalized",
        signature.get("generalized_ratio_bucket", ""),
        ["reduction_closure_engine", "reduction_unit", "diag_unit", "vector_diag_companion"],
        0.04,
    )
    add_bias(
        "diag",
        signature.get("diag_dominance", ""),
        ["diag_unit", "vector_diag_companion"],
        0.05,
    )
    add_bias(
        "fft",
        signature.get("fft_grid_pressure", ""),
        ["fft_unit", "near_sram_support", "near_memory_domain"],
        0.04,
    )
    return applied


def iteration_behavior_summary(
    iteration_diagnostics: list[dict[str, Any]],
) -> str | None:
    if not iteration_diagnostics:
        return None
    total = len(iteration_diagnostics)
    host_fallback = sum(
        1
        for item in iteration_diagnostics
        if item.get("cpu_diag_fallback") is True or item.get("diag_path") == "host_cpu_fallback"
    )
    spill = sum(1 for item in iteration_diagnostics if item.get("spill_active") is True)
    fft_active = sum(
        1
        for item in iteration_diagnostics
        if item.get("support_grid_mode") not in (None, "", "BYPASS")
    )
    inner_cap_hits = sum(
        1
        for item in iteration_diagnostics
        if item.get("inner_steps") == item.get("max_inner_steps") and item.get("inner_steps") is not None
    )
    return (
        f"iters={total}, host_fallback={host_fallback}/{total}, "
        f"spill={spill}/{total}, fft_active={fft_active}/{total}, "
        f"inner_cap_hits={inner_cap_hits}/{total}"
    )


def component_score_signal_summary(
    signature_signals: list[str],
) -> str | None:
    if not signature_signals:
        return None
    return "signature=" + ",".join(signature_signals)


def candidate_cluster_metrics(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = candidate.get("cluster_metrics")
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for cluster_name in ("cluster_a", "cluster_b", "cluster_c", "cluster_d"):
        item = payload.get(cluster_name)
        if isinstance(item, dict):
            result[cluster_name] = item
    return result


def cluster_cycle_weights(
    cluster_metrics: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], float]:
    raw: dict[str, float] = {}
    total = 0.0
    for cluster_name, item in cluster_metrics.items():
        ref_cycles = item.get("accounted_ref_cycles")
        if ref_cycles is None:
            continue
        ref_cycles_f = float(ref_cycles)
        if ref_cycles_f <= 0.0:
            continue
        raw[cluster_name] = ref_cycles_f
        total += ref_cycles_f
    if total <= 0.0:
        return {}, 0.0
    return ({cluster_name: value / total for cluster_name, value in raw.items()}, total)


def normalize_score_map(score_map: dict[str, float]) -> list[tuple[str, float]]:
    positive = {component_ref: score for component_ref, score in score_map.items() if score > 0.0}
    total = sum(positive.values())
    if total <= 0.0:
        return []
    normalized = [(component_ref, score / total) for component_ref, score in positive.items()]
    return sorted(normalized, key=lambda item: (-item[1], item[0]))


def graph_component_scores_runtime_aware(
    family: str,
    key_component_refs: list[str],
    resident_policy: str,
    candidate: dict[str, Any],
    workload: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, float]], str, str | None, str | None, str | None]:
    base_weights = {
        component_ref: weight
        for component_ref, weight in graph_component_score_weights(family, resident_policy).items()
        if component_ref in key_component_refs
    }
    if not base_weights:
        return [], "seed_proxy", None, None, None

    cluster_metrics = candidate_cluster_metrics(candidate)
    cluster_weights, cluster_total_cycles = cluster_cycle_weights(cluster_metrics)
    if not cluster_weights:
        return graph_component_scores(family, key_component_refs, resident_policy), "seed_proxy", None, None, None

    dynamic_scores = {component_ref: 0.0 for component_ref in key_component_refs}

    for cluster_name, cluster_share in cluster_weights.items():
        group = [
            component_ref
            for component_ref in CLUSTER_COMPONENT_GROUPS.get(cluster_name, [])
            if component_ref in key_component_refs
        ]
        if not group:
            continue
        group_weight_total = sum(base_weights.get(component_ref, 0.0) for component_ref in group)
        if group_weight_total <= 0.0:
            group_weight_total = float(len(group))
            for component_ref in group:
                dynamic_scores[component_ref] += cluster_share / group_weight_total
        else:
            for component_ref in group:
                dynamic_scores[component_ref] += (
                    cluster_share * base_weights.get(component_ref, 0.0) / group_weight_total
                )

    metrics = candidate.get("metrics", {})
    run_summary = candidate.get("run_summary", {})
    total_ref_cycles = run_summary.get("total_ref_cycles")
    if total_ref_cycles not in (None, 0):
        total_ref_cycles_f = float(total_ref_cycles)
        dma_ref_cycles = metrics.get("dma_ref_cycles")
        if dma_ref_cycles not in (None, 0) and "dma_channel" in dynamic_scores:
            dynamic_scores["dma_channel"] += float(dma_ref_cycles) / total_ref_cycles_f
        host_assist_ref_cycles = metrics.get("host_assist_ref_cycles")
        if host_assist_ref_cycles not in (None, 0):
            host_assist_share = float(host_assist_ref_cycles) / total_ref_cycles_f
            for component_ref in ("host_controller", "system_container", "chip_execution_facade"):
                if component_ref in dynamic_scores:
                    dynamic_scores[component_ref] += host_assist_share / 3.0

    iteration_diagnostics = [
        item for item in candidate.get("iteration_diagnostics", []) if isinstance(item, dict)
    ]
    host_fallback_count = sum(
        1
        for item in iteration_diagnostics
        if item.get("cpu_diag_fallback") is True
        or item.get("diag_path") == "host_cpu_fallback"
    )
    if host_fallback_count > 0:
        boost = 0.08 * host_fallback_count
        for component_ref in ("diag_unit", "vector_diag_companion"):
            if component_ref in dynamic_scores:
                dynamic_scores[component_ref] += boost

    spill_count = sum(1 for item in iteration_diagnostics if item.get("spill_active") is True)
    if spill_count > 0:
        boost = 0.05 * spill_count
        for component_ref in (
            "near_memory_domain",
            "near_sram_support",
            "context_loader",
            "near_sram_coeff_buffer",
            "near_sram_row_buffer",
            "reduction_closure_engine",
        ):
            if component_ref in dynamic_scores:
                dynamic_scores[component_ref] += boost

    support_grid_modes = {
        str(item.get("support_grid_mode"))
        for item in iteration_diagnostics
        if item.get("support_grid_mode") not in (None, "", "BYPASS")
    }
    if support_grid_modes and "fft_unit" in dynamic_scores:
        dynamic_scores["fft_unit"] += 0.05 * len(support_grid_modes)

    signature = signature_descriptor(candidate, workload)
    signature_signals = apply_signature_biases(dynamic_scores, signature)
    iteration_summary_text = iteration_behavior_summary(iteration_diagnostics)

    control_present = [component_ref for component_ref in CONTROL_COMPONENT_ORDER if component_ref in dynamic_scores]
    assigned = sum(dynamic_scores.values())
    if assigned < 1.0 and control_present:
        remaining = 1.0 - assigned
        control_weight_total = sum(base_weights.get(component_ref, 0.0) for component_ref in control_present)
        if control_weight_total <= 0.0:
            control_weight_total = float(len(control_present))
        for component_ref in control_present:
            weight = base_weights.get(component_ref, 0.0)
            if weight <= 0.0:
                weight = 1.0
            dynamic_scores[component_ref] += remaining * weight / control_weight_total

    component_scores = normalize_score_map(dynamic_scores)
    cluster_cycle_summary = ", ".join(
        f"{cluster_name}={cluster_share:.2f}"
        for cluster_name, cluster_share in sorted(cluster_weights.items())
    )
    score_source = "runtime_cluster_signature_weighted" if signature_signals else "runtime_cluster_weighted"
    return (
        component_scores,
        score_source,
        cluster_cycle_summary,
        component_score_signal_summary(signature_signals),
        iteration_summary_text,
    )


def graph_bottleneck_component_summary(
    family: str,
    key_component_refs: list[str],
    resident_policy: str,
) -> str | None:
    if family == "F1":
        preferred = ["dma_channel", "context_loader", "cim_array_core", "residue_3m_core", "diag_unit"]
    elif resident_policy == "spill_tolerant" or family == "F3":
        preferred = [
            "near_sram_support",
            "context_loader",
            "cim_array_core",
            "residue_3m_core",
            "reduction_closure_engine",
            "vector_diag_companion",
            "refresh_unit",
        ]
    else:
        preferred = [
            "near_sram_support",
            "context_loader",
            "cim_array_core",
            "residue_3m_core",
            "reduction_closure_engine",
            "diag_unit",
        ]
    selected = [component_ref for component_ref in preferred if component_ref in key_component_refs]
    return ", ".join(selected) if selected else None


def graph_risk_driver_component_summary(
    family: str,
    key_component_refs: list[str],
    resident_policy: str,
) -> str | None:
    if family == "F1":
        preferred = ["host_controller", "dma_channel", "command_scheduler", "context_loader", "diag_unit"]
    elif resident_policy == "spill_tolerant" or family == "F3":
        preferred = [
            "episode_controller",
            "near_memory_domain",
            "near_sram_support",
            "context_loader",
            "reduction_closure_engine",
            "vector_diag_companion",
            "refresh_unit",
        ]
    else:
        preferred = [
            "episode_controller",
            "near_memory_domain",
            "near_sram_support",
            "context_loader",
            "reduction_closure_engine",
            "vector_diag_companion",
        ]
    selected = [component_ref for component_ref in preferred if component_ref in key_component_refs]
    return ", ".join(selected) if selected else None


def build_graph_evidence(
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    partition_strategy: str,
    result_id: str,
) -> dict[str, Any]:
    key = (family, diag_policy, offload_scope, resident_policy, partition_strategy)
    template = load_graph_seed_templates(GRAPH_SEED_TEMPLATES_PATH).get(key)
    if template is None:
        return {
            "graph_id": None,
            "graph_schema_version": load_graph_schema_version(GRAPH_SCHEMA_PATH),
            "seed_template_id": None,
            "graph_export_authority": "sidecar_evidence",
            "lossless_export_pass": False,
            "module_instance_count": None,
            "link_count": None,
            "flow_count": None,
            "topology_style": None,
            "control_plane_summary": None,
            "datapath_stage_summary": None,
            "key_component_refs_summary": None,
            "leaf_component_refs_summary": None,
            "bottleneck_component_summary": None,
            "leaf_bottleneck_component_summary": None,
            "risk_driver_component_summary": None,
            "component_score_summary": None,
            "component_score_source": "seed_proxy",
            "execution_plan_summary": None,
            "cluster_cycle_summary": None,
            "component_score_signal_summary": None,
            "iteration_behavior_summary": None,
            "critical_path_summary": None,
            "dataflow_bottleneck_summary": None,
            "mapping_risk_summary": "no_matching_seed_template",
        }
    seed_template_id = str(template["seed_template_id"])
    modules = template.get("modules", [])
    links = template.get("links", [])
    flows = template.get("flows", [])
    placement = template.get("placement", {})
    key_component_refs = graph_key_component_refs(template, seed_template_id)
    leaf_component_refs = graph_leaf_component_refs(key_component_refs)
    component_scores = graph_component_scores(family, key_component_refs, resident_policy)
    critical_path_summary = " -> ".join(flows[0].get("steps", [])) if flows else None
    return {
        "graph_id": f"{result_id}::graph",
        "graph_schema_version": load_graph_schema_version(GRAPH_SCHEMA_PATH),
        "seed_template_id": seed_template_id,
        "graph_export_authority": "sidecar_evidence",
        "lossless_export_pass": True,
        "module_instance_count": len(modules),
        "link_count": len(links),
        "flow_count": len(flows),
        "topology_style": placement.get("style"),
        "control_plane_summary": graph_control_plane_summary(placement, key_component_refs),
        "datapath_stage_summary": graph_datapath_stage_summary(key_component_refs),
        "key_component_refs_summary": ", ".join(key_component_refs) if key_component_refs else None,
        "leaf_component_refs_summary": ", ".join(leaf_component_refs) if leaf_component_refs else None,
        "bottleneck_component_summary": graph_bottleneck_component_summary(
            family, key_component_refs, resident_policy
        ),
        "leaf_bottleneck_component_summary": graph_leaf_bottleneck_component_summary(
            component_scores
        ),
        "risk_driver_component_summary": graph_risk_driver_component_summary(
            family, key_component_refs, resident_policy
        ),
        "component_score_summary": graph_component_score_summary(component_scores),
        "component_score_source": "seed_proxy",
        "execution_plan_summary": None,
        "cluster_cycle_summary": None,
        "component_score_signal_summary": None,
        "iteration_behavior_summary": None,
        "critical_path_summary": critical_path_summary,
        "dataflow_bottleneck_summary": graph_dataflow_bottleneck_summary(
            family, offload_scope, resident_policy, partition_strategy
        ),
        "mapping_risk_summary": graph_mapping_risk_summary(
            family, offload_scope, resident_policy
        ),
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_graph_execution_plan_profile(
    profile: dict[str, Any] | None,
) -> str | None:
    if not isinstance(profile, dict):
        return None
    parts: list[str] = []
    requested = profile.get("requested_cluster_sequence")
    resolved = profile.get("resolved_cluster_sequence")
    executed = profile.get("executed_cluster_sequence")
    source = profile.get("execution_plan_source")
    constraints = profile.get("sequence_constraints")
    if requested:
        parts.append(f"requested={requested}")
    if resolved:
        parts.append(f"resolved={resolved}")
    if executed:
        parts.append(f"executed={executed}")
    if source:
        parts.append(f"source={source}")
    if constraints:
        parts.append(f"constraints={constraints}")
    return " | ".join(parts) if parts else None


def load_case_pack(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_pack_workload_ids(case_pack: dict[str, Any]) -> set[str]:
    sections = [
        "stage_a_bringup_descriptors",
        "stage_b_nonblocking_signature_descriptors",
        "accurate_layer_anchor_descriptors",
        "accurate_layer_coverage_descriptors",
        "accurate_layer_generalization_descriptors",
    ]
    workload_ids: set[str] = set()
    for section in sections:
        for item in case_pack.get(section, []):
            workload_id = item.get("workload_id")
            if workload_id:
                workload_ids.add(str(workload_id))
    return workload_ids


def normalize_case_pack_workload(descriptor: dict[str, Any]) -> dict[str, Any]:
    workload = dict(descriptor)
    if "display_label" in workload and "label" not in workload:
        workload["label"] = workload["display_label"]
    return workload


def workload_rows_from_case_pack(
    workload_ids: list[str],
    case_pack: dict[str, Any],
    *,
    sections: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected_sections = sections or [
        "stage_a_bringup_descriptors",
        "stage_b_nonblocking_signature_descriptors",
        "accurate_layer_anchor_descriptors",
        "accurate_layer_coverage_descriptors",
        "accurate_layer_generalization_descriptors",
    ]
    descriptors_by_id: dict[str, dict[str, Any]] = {}
    source_section_by_id: dict[str, str] = {}
    for section in selected_sections:
        for item in case_pack.get(section, []):
            workload_id = str(item.get("workload_id", ""))
            if workload_id:
                if workload_id in descriptors_by_id:
                    previous = source_section_by_id[workload_id]
                    raise ValueError(
                        f"case pack workload {workload_id} appears in multiple selected sections: "
                        f"{previous}, {section}. Use --case-pack-sections to disambiguate."
                    )
                descriptors_by_id[workload_id] = normalize_case_pack_workload(item)
                source_section_by_id[workload_id] = section
    missing = [workload_id for workload_id in workload_ids if workload_id not in descriptors_by_id]
    if missing:
        raise ValueError("case pack missing workloads: " + ", ".join(missing))
    return [descriptors_by_id[workload_id] for workload_id in workload_ids]


def seconds_from_ref_cycles(
    ref_cycles: int | float | None,
    total_ref_cycles: int | float | None,
    wall_time_s: float | int | None,
) -> float | None:
    if (
        ref_cycles is None
        or total_ref_cycles is None
        or wall_time_s is None
        or float(total_ref_cycles) <= 0.0
    ):
        return None
    return float(ref_cycles) * float(wall_time_s) / float(total_ref_cycles)


def nonnegative_ref_cycles(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if float(value) < 0.0:
        return None
    return float(value)


def positive_ref_cycles(value: object) -> float | None:
    cycles = nonnegative_ref_cycles(value)
    if cycles is None or cycles <= 0.0:
        return None
    return cycles


def sum_positive_cycle_field(items: list[dict[str, Any]], field: str) -> float | None:
    total = 0.0
    found = False
    for item in items:
        cycles = positive_ref_cycles(item.get(field))
        if cycles is not None:
            total += cycles
            found = True
    return total if found else None


def cluster_accounted_ref_cycles(candidate: dict[str, Any]) -> float | None:
    cluster_metrics = candidate.get("cluster_metrics", {})
    if not isinstance(cluster_metrics, dict):
        return None
    total = 0.0
    found = False
    for item in cluster_metrics.values():
        if not isinstance(item, dict):
            continue
        cycles = positive_ref_cycles(item.get("accounted_ref_cycles"))
        if cycles is not None:
            total += cycles
            found = True
    return total if found else None


def candidate_cycle_metric(
    candidate: dict[str, Any],
    metrics: dict[str, Any],
    iteration_diagnostics: list[dict[str, Any]],
    field: str,
) -> float | None:
    raw_cycles = nonnegative_ref_cycles(metrics.get(field))
    if raw_cycles is not None and raw_cycles > 0.0:
        return raw_cycles

    diagnostic_cycles = sum_positive_cycle_field(iteration_diagnostics, field)
    if diagnostic_cycles is not None:
        return diagnostic_cycles

    if field == "device_busy_ref_cycles":
        cluster_cycles = cluster_accounted_ref_cycles(candidate)
        if cluster_cycles is not None:
            return cluster_cycles

    return raw_cycles


def candidate_total_ref_cycles(
    candidate: dict[str, Any] | None,
    device_busy_ref_cycles: object,
    dma_ref_cycles: object,
    host_assist_ref_cycles: object,
) -> float | None:
    run_summary = {} if candidate is None else candidate.get("run_summary", {})
    if isinstance(run_summary, dict):
        total_ref_cycles = positive_ref_cycles(run_summary.get("total_ref_cycles"))
        if total_ref_cycles is not None:
            return total_ref_cycles

    component_total = 0.0
    found = False
    for cycles in (device_busy_ref_cycles, dma_ref_cycles, host_assist_ref_cycles):
        numeric_cycles = nonnegative_ref_cycles(cycles)
        if numeric_cycles is None:
            continue
        component_total += numeric_cycles
        if numeric_cycles > 0.0:
            found = True
    return component_total if found else None


def energy_proxy_assumptions(assumption_set_id: str, path: Path) -> dict[str, Any]:
    payload = load_proxy_assumption_payload(path)
    default_assumption_set_id = str(payload.get("default_assumption_set_id", "qe_next_stage_phase_v0"))
    assumption_sets = payload.get("assumption_sets", {})
    if not isinstance(assumption_sets, dict):
        raise ValueError(f"assumption_sets must be a mapping in {path}")
    if assumption_set_id in assumption_sets:
        selected = assumption_sets[assumption_set_id]
    elif assumption_set_id == "":
        selected = assumption_sets.get(default_assumption_set_id)
    else:
        available = ", ".join(sorted(assumption_sets))
        raise KeyError(
            f"unknown fast-layer proxy assumption set '{assumption_set_id}' in {path}; available: {available}"
        )
    if not isinstance(selected, dict):
        raise KeyError(
            f"missing fast-layer proxy assumption set '{assumption_set_id}' and default '{default_assumption_set_id}' in {path}"
        )
    return selected


def gold_status_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts = {status: 0 for status in GOLD_STATUS_TAXONOMY}
    for row in rows:
        status = str(row["correctness"]["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def is_gold_gate_blocking_status(status: str) -> bool:
    return status not in {"pass", "not_required"}


def canonical_profile_match(
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    partition_strategy: str,
) -> bool:
    profile = FAMILY_PROFILES[family]
    return (
        diag_policy == profile["canonical_diag_policy"]
        and offload_scope == profile["canonical_offload_scope"]
        and resident_policy == profile["canonical_resident_policy"]
        and partition_strategy == profile["canonical_partition_strategy"]
    )


def canonical_partition_strategy_for(family: str, offload_scope: str) -> str:
    profile = FAMILY_PROFILES[family]
    return str(profile.get("canonical_partition_strategy", "operator__build__diag__refresh"))


def build_result_row(
    workload: dict[str, object],
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    args: argparse.Namespace,
    partition_strategy: str | None = None,
) -> dict[str, object]:
    resolved_partition_strategy = partition_strategy or canonical_partition_strategy_for(
        family, offload_scope
    )
    result_id = "__".join(
        [
            str(workload["workload_id"]),
            family,
            diag_policy,
            offload_scope,
            resident_policy,
            resolved_partition_strategy,
        ]
    )
    profile = FAMILY_PROFILES[family]
    graph_evidence = build_graph_evidence(
        family,
        diag_policy,
        offload_scope,
        resident_policy,
        resolved_partition_strategy,
        result_id,
    )
    row = {
        "result_id": result_id,
        "result_status": "stub",
        "source_kind": args.source_kind,
        "workload": workload,
        "design_point": {
            "family": family,
            "diag_policy": diag_policy,
            "offload_scope": offload_scope,
            "resident_policy": resident_policy,
            "partition_strategy": resolved_partition_strategy,
            "canonical_profile_match": canonical_profile_match(
                family, diag_policy, offload_scope, resident_policy, resolved_partition_strategy
            ),
        },
        "architecture_template_id": None,
        "candidate_id": None,
        "projected_config_path": None,
        "template_family": None,
        "template_validation_status": None,
        "template_risk_level": None,
        "template_tags": [],
        "template_artifact_sha256": None,
        "design_space_spec_id": None,
        "design_space_spec_sha256": None,
        "comparison_contract": {
            "qe_baseline_id": "qe_cpu_only_gold_v0",
            "workload_group_id": PHASE1_WORKLOAD_GROUP_ID,
            "qe_tolerance_schema_id": args.qe_tolerance_schema_id,
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "fairness_policy_id": PHASE1_FAIRNESS_POLICY_ID,
            "power_boundary_id": PHASE1_POWER_BOUNDARY_ID,
            "observability_contract_id": PHASE1_OBSERVABILITY_CONTRACT_ID,
            "algorithm_rewrite_manifest_id": PHASE1_REWRITE_MANIFEST_ID,
            "algorithm_contract_deviation": False,
            "gold_required": workload["gold_required"],
        },
        "correctness": {
            "status": "pending",
            "gold_pass": None,
            "convergence_comparable_pass": None,
            "final_total_energy_match": None,
            "residual_threshold_state_match": None,
            "converged_state_match": None,
            "required_field_failures": [],
            "baseline_scf_iterations": None,
            "candidate_scf_iterations": None,
            "final_total_energy_abs_err_ev": None,
            "final_total_energy_rel_err": None,
            "notes": [],
        },
        "primary_metrics": {
            "time_to_convergence_s": None,
            "speedup_to_convergence": None,
            "energy_to_convergence_j": None,
            "avg_system_power_proxy_w": None,
            "scf_iterations_to_convergence": None,
            "bytes_moved_to_convergence": None,
            "fallback_count_to_convergence": None,
        },
        "secondary_metrics": {
            "device_busy_ref_cycles": None,
            "dma_ref_cycles": None,
            "host_assist_ref_cycles": None,
            "resident_reuse_hits": None,
            "spill_ratio": None,
            "fallback_ratio": None,
            "complexity_proxy": profile["complexity_proxy"],
        },
        "runtime_observability": {
            "last_diag_path": None,
            "last_support_grid_mode": None,
            "last_workload_bucket": None,
            "last_band_count": None,
            "last_panel_count": None,
            "configured_max_inner_steps": None,
            "realized_inner_steps": None,
            "last_max_diag_condition_estimate": None,
            "spill_active_count": None,
            "host_cpu_fallback_count": None,
        },
        "graph_evidence": graph_evidence,
        "energy_ledger": {
            "E_host_j": None,
            "E_device_runtime_j": None,
            "E_dma_j": None,
            "E_hardware_datapath_j": None,
            "E_idle_static_j": None,
        },
        "projection": {
            "speedup_to_convergence_range": None,
            "energy_to_convergence_range_j": None,
            "confidence": "pending",
            "assumption_set_id": args.assumption_set_id,
            "ranking_grade_ready": False,
            "projection_grade_ready": False,
        },
        "artifacts": {
            "model_run_id": None,
            "stdout_path": None,
            "metrics_path": None,
            "compare_report_path": None,
            "graph_evidence_path": None,
            "raw_trace_paths": None,
        },
        "stub_reason": (
            "Bootstrap placeholder for architecture-family sweep planning; "
            "fill metrics and correctness fields after SystemC model integration."
        ),
    }
    apply_equal_candidate_fields(
        row,
        args,
        candidate_family=family,
        runtime_projection_family=family,
        template_tags=[],
    )
    return row


def emit_projected_systemc_config(
    template: dict[str, Any],
    candidate_id: str,
    args: argparse.Namespace,
    design_space_summary: dict[str, Any] | None,
    candidate_family: str,
    runtime_projection_family: str,
    evaluator_backend: str,
    fidelity_class: str,
    support_status: str,
    support_evidence: dict[str, object],
) -> str | None:
    if not getattr(args, "template_driven", False):
        return None
    if not (getattr(args, "emit_projected_configs", False) or getattr(args, "template_driven", False)):
        return None
    projector = load_template_projector()
    projection_input = dict(template)
    projection_input.setdefault("base_family", template.get("family"))
    config = projector.project_template(projection_input)
    config["projection_metadata"] = {
        "candidate_id": candidate_id,
        "candidate_family": candidate_family,
        "runtime_projection_family": runtime_projection_family,
        "evaluator_backend": evaluator_backend,
        "fidelity_class": fidelity_class,
        "support_status": support_status,
        "support_evidence": support_evidence,
        "source_template_id": template.get("template_id"),
        "source_template_sha256": template.get("_template_sha256"),
        "template_validation_status": template.get("_template_validation_status"),
        "design_space_spec_id": None if design_space_summary is None else design_space_summary.get("design_space_spec_id"),
        "design_space_spec_sha256": None if design_space_summary is None else design_space_summary.get("sha256"),
    }
    config_dir = args.output_dir / "artifacts" / "architecture_configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{candidate_id}.systemc_config.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    return str(config_path)


def build_template_result_row(
    workload: dict[str, object],
    template: dict[str, Any],
    args: argparse.Namespace,
    candidate_index: int,
    design_space_summary: dict[str, Any] | None,
) -> dict[str, object]:
    template_id = str(template.get("template_id") or f"template_{candidate_index:04d}")
    policies = template.get("policies", {}) if isinstance(template.get("policies"), dict) else {}
    template_family = str(template.get("family") or template.get("base_family") or "custom")
    candidate_family = candidate_family_for_template(template)
    runtime_projection_family = runtime_projection_family_for_candidate(candidate_family)
    family = runtime_projection_family
    diag_policy = str(policies.get("diag_policy") or FAMILY_PROFILES[family]["canonical_diag_policy"])
    offload_scope = str(policies.get("offload_scope") or FAMILY_PROFILES[family]["canonical_offload_scope"])
    resident_policy = str(policies.get("resident_policy") or FAMILY_PROFILES[family]["canonical_resident_policy"])
    partition_strategy = str(
        policies.get("partition_strategy") or FAMILY_PROFILES[family]["canonical_partition_strategy"]
    )
    if diag_policy not in DIAG_POLICIES:
        diag_policy = str(FAMILY_PROFILES[family]["canonical_diag_policy"])
    if offload_scope not in OFFLOAD_SCOPES:
        offload_scope = str(FAMILY_PROFILES[family]["canonical_offload_scope"])
    if resident_policy not in RESIDENT_POLICIES:
        resident_policy = str(FAMILY_PROFILES[family]["canonical_resident_policy"])
    if partition_strategy not in PARTITION_STRATEGIES:
        partition_strategy = str(FAMILY_PROFILES[family]["canonical_partition_strategy"])

    row = build_result_row(
        workload,
        family,
        diag_policy,
        offload_scope,
        resident_policy,
        args,
        partition_strategy,
    )
    candidate_id = f"{candidate_index:04d}__{template_id}__{workload['workload_id']}"
    row["result_id"] = candidate_id
    graph_evidence = row.get("graph_evidence")
    if isinstance(graph_evidence, dict) and graph_evidence.get("graph_id") is not None:
        graph_evidence["graph_id"] = f"{candidate_id}::graph"
    row["architecture_template_id"] = template_id
    row["candidate_id"] = candidate_id
    row["template_family"] = template_family
    row["template_validation_status"] = template.get("_template_validation_status")
    dse_metadata = template.get("dse_metadata", {}) if isinstance(template.get("dse_metadata"), dict) else {}
    template_tags = dse_metadata.get("tags", [])
    if not isinstance(template_tags, list):
        template_tags = []
    row["template_risk_level"] = dse_metadata.get("risk_level")
    row["template_tags"] = [str(tag) for tag in template_tags]
    row["template_artifact_sha256"] = template.get("_template_sha256")
    apply_equal_candidate_fields(
        row,
        args,
        candidate_family=candidate_family,
        runtime_projection_family=runtime_projection_family,
        template_tags=row["template_tags"],
    )
    if design_space_summary is not None:
        row["design_space_spec_id"] = design_space_summary.get("design_space_spec_id")
        row["design_space_spec_sha256"] = design_space_summary.get("sha256")
    row["projected_config_path"] = emit_projected_systemc_config(
        template,
        candidate_id,
        args,
        design_space_summary,
        str(row["candidate_family"]),
        str(row["runtime_projection_family"]),
        str(row["evaluator_backend"]),
        str(row["fidelity_class"]),
        str(row["support_status"]),
        row["support_evidence"] if isinstance(row.get("support_evidence"), dict) else {},
    )
    return row


def missing_ranking_metric_names(row: dict[str, object]) -> list[str]:
    primary = row.get("primary_metrics", {})
    secondary = row.get("secondary_metrics", {})
    missing = [
        metric
        for metric in REQUIRED_RANKING_PRIMARY_METRICS
        if not isinstance(primary, dict) or primary.get(metric) is None
    ]
    missing.extend(
        metric
        for metric in REQUIRED_RANKING_SECONDARY_METRICS
        if not isinstance(secondary, dict) or secondary.get(metric) is None
    )
    return missing


def row_is_projection_only(row: dict[str, object]) -> bool:
    support_status = row.get("support_status")
    if support_status is not None:
        return str(support_status) == "projection_only"
    template_tags = row.get("template_tags")
    if isinstance(template_tags, list) and "projection_only" in {str(tag) for tag in template_tags}:
        return True
    template_family = row.get("template_family")
    if template_family in PROJECTION_ONLY_TEMPLATE_FAMILIES:
        return True
    design_point = row.get("design_point", {})
    if not isinstance(design_point, dict):
        return bool(template_family)
    return bool(template_family and template_family != design_point.get("family"))


def projection_readiness_failures(
    row: dict[str, object],
    case_pack_summary: dict[str, object] | None,
) -> list[str]:
    failures = []
    if not case_pack_summary or case_pack_summary.get("all_requested_workloads_present") is not True:
        failures.append("case_pack_not_attached")

    if row.get("architecture_template_id") is not None:
        if not row.get("projected_config_path"):
            failures.append("projected_config_missing")
        validation_status = str(row.get("template_validation_status") or "")
        if validation_status.startswith("invalid:"):
            failures.append("template_basic_validation_failed")
        if not row.get("template_artifact_sha256"):
            failures.append("template_artifact_hash_missing")
    else:
        graph_evidence = row.get("graph_evidence")
        if not isinstance(graph_evidence, dict) or graph_evidence.get("lossless_export_pass") is not True:
            failures.append("graph_projection_not_lossless")

    return failures


def refresh_projection_grade_readiness(bundle: dict[str, object]) -> None:
    experiment = bundle.get("experiment", {})
    case_pack_summary = None
    if isinstance(experiment, dict):
        raw_summary = experiment.get("case_pack_summary")
        if isinstance(raw_summary, dict):
            case_pack_summary = raw_summary

    for row in bundle["results"]:
        failures = projection_readiness_failures(row, case_pack_summary)
        ready = not failures
        row["projection"]["projection_grade_ready"] = ready
        if ready and row["projection"].get("confidence") == "pending":
            row["projection"]["confidence"] = "exploratory"


def build_family_summary(results: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for family, profile in FAMILY_PROFILES.items():
        result_count = sum(1 for row in results if row["design_point"]["family"] == family)
        out.append(
            {
                "family": family,
                "canonical_diag_policy": profile["canonical_diag_policy"],
                "canonical_offload_scope": profile["canonical_offload_scope"],
                "canonical_resident_policy": profile["canonical_resident_policy"],
                "canonical_partition_strategy": profile["canonical_partition_strategy"],
                "result_count": result_count,
                "ranking_grade_status": "pending",
                "projection_grade_status": "pending",
                "confidence": "pending",
                "recommended_cpu_device_split": profile["recommended_cpu_device_split"],
                "recommended_operator_set": profile["recommended_operator_set"],
            }
        )
    return out


def build_candidate_family_summary(results: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for candidate_family in CANDIDATE_FAMILIES:
        family_rows = [
            row for row in results if str(row.get("candidate_family") or "") == candidate_family
        ]
        support_counts = Counter(str(row.get("support_status") or "unknown") for row in family_rows)
        evaluator_counts = Counter(str(row.get("evaluator_backend") or "unknown") for row in family_rows)
        fidelity_counts = Counter(str(row.get("fidelity_class") or "unknown") for row in family_rows)
        out.append(
            {
                "candidate_family": candidate_family,
                "result_count": len(family_rows),
                "runtime_projection_families": sorted(
                    {str(row.get("runtime_projection_family") or "") for row in family_rows if row.get("runtime_projection_family")}
                ),
                "architecture_template_ids": sorted(
                    {str(row.get("architecture_template_id")) for row in family_rows if row.get("architecture_template_id")}
                ),
                "candidate_ids": sorted(
                    {str(row.get("candidate_id")) for row in family_rows if row.get("candidate_id")}
                ),
                "support_status_counts": dict(sorted(support_counts.items())),
                "evaluator_backend_counts": dict(sorted(evaluator_counts.items())),
                "fidelity_class_counts": dict(sorted(fidelity_counts.items())),
                "projection_only_rows": sum(1 for row in family_rows if row_is_projection_only(row)),
            }
        )
    return out


def populate_fast_layer_proxy_metrics(
    row: dict[str, object],
    candidate: dict[str, Any],
    cpu_shell_baseline: dict[str, Any] | None,
    args: argparse.Namespace,
) -> None:
    final = candidate.get("final", {})
    metrics = candidate.get("metrics", {})
    timing = candidate.get("timing", {})
    run_summary = candidate.get("run_summary", {})
    last_iteration = candidate.get("last_iteration", {})
    iteration_diagnostics = [
        item for item in candidate.get("iteration_diagnostics", []) if isinstance(item, dict)
    ]

    wall_time_s = timing.get("wall_time_s")
    row["primary_metrics"]["time_to_convergence_s"] = wall_time_s
    row["primary_metrics"]["scf_iterations_to_convergence"] = final.get("scf_iterations")

    if cpu_shell_baseline is not None:
        baseline_wall_s = cpu_shell_baseline.get("electrons_wall_s")
        row["comparison_contract"]["qe_baseline_id"] = (
            f"{row['workload']['workload_id']}_qe_cpu_shell_aggregate_v0"
        )
        if baseline_wall_s is not None and wall_time_s not in (None, 0):
            row["primary_metrics"]["speedup_to_convergence"] = float(baseline_wall_s) / float(
                wall_time_s
            )

    total_data_movement_kib = metrics.get("total_data_movement_kib")
    row["primary_metrics"]["bytes_moved_to_convergence"] = (
        None if total_data_movement_kib is None else float(total_data_movement_kib) * 1024.0
    )
    row["primary_metrics"]["fallback_count_to_convergence"] = metrics.get("cpu_fallbacks")

    device_busy_ref_cycles = candidate_cycle_metric(
        candidate, metrics, iteration_diagnostics, "device_busy_ref_cycles"
    )
    dma_ref_cycles = candidate_cycle_metric(candidate, metrics, iteration_diagnostics, "dma_ref_cycles")
    host_assist_ref_cycles = candidate_cycle_metric(
        candidate, metrics, iteration_diagnostics, "host_assist_ref_cycles"
    )
    row["secondary_metrics"]["device_busy_ref_cycles"] = device_busy_ref_cycles
    row["secondary_metrics"]["dma_ref_cycles"] = dma_ref_cycles
    row["secondary_metrics"]["host_assist_ref_cycles"] = host_assist_ref_cycles
    row["secondary_metrics"]["resident_reuse_hits"] = metrics.get("resident_reuse_hits")

    total_episodes = run_summary.get("total_episodes")
    cpu_fallbacks = metrics.get("cpu_fallbacks")
    if isinstance(total_episodes, int) and total_episodes > 0 and isinstance(cpu_fallbacks, int):
        row["secondary_metrics"]["fallback_ratio"] = cpu_fallbacks / total_episodes

    if iteration_diagnostics:
        spill_events = sum(1 for item in iteration_diagnostics if item.get("spill_active") is True)
        row["secondary_metrics"]["spill_ratio"] = spill_events / len(iteration_diagnostics)
        last_iteration_diag = iteration_diagnostics[-1]
        runtime = row["runtime_observability"]
        runtime["last_diag_path"] = last_iteration_diag.get("diag_path")
        runtime["last_support_grid_mode"] = last_iteration_diag.get("support_grid_mode")
        runtime["last_workload_bucket"] = last_iteration_diag.get("workload_bucket")
        runtime["last_band_count"] = last_iteration_diag.get("band_count")
        runtime["last_panel_count"] = last_iteration_diag.get("panel_count")
        runtime["configured_max_inner_steps"] = last_iteration_diag.get("max_inner_steps")
        runtime["realized_inner_steps"] = last_iteration_diag.get("inner_steps")
        runtime["last_max_diag_condition_estimate"] = last_iteration_diag.get(
            "max_diag_condition_estimate"
        )
        runtime["spill_active_count"] = spill_events
        runtime["host_cpu_fallback_count"] = sum(
            1
            for item in iteration_diagnostics
            if item.get("cpu_diag_fallback") is True
            or item.get("diag_path") == "host_cpu_fallback"
        )

    assumptions = energy_proxy_assumptions(
        str(args.assumption_set_id), args.fast_layer_proxy_assumptions_path
    )
    total_ref_cycles = candidate_total_ref_cycles(
        candidate,
        device_busy_ref_cycles,
        dma_ref_cycles,
        host_assist_ref_cycles,
    )
    device_busy_s = seconds_from_ref_cycles(
        device_busy_ref_cycles, total_ref_cycles, wall_time_s
    )
    dma_s = seconds_from_ref_cycles(dma_ref_cycles, total_ref_cycles, wall_time_s)
    host_assist_s = seconds_from_ref_cycles(
        host_assist_ref_cycles, total_ref_cycles, wall_time_s
    )
    host_control_s = (
        None
        if wall_time_s is None
        else max(float(wall_time_s) - float(host_assist_s or 0.0), 0.0)
    )

    family = str(row["design_point"]["family"])
    family_powers = assumptions["family_device_power_w"][family]
    energy_ledger = row["energy_ledger"]
    energy_ledger["E_host_j"] = (
        None
        if host_control_s is None
        else host_control_s * float(assumptions["host_control_w"])
        + float(host_assist_s or 0.0) * float(assumptions["host_assist_w"])
    )
    energy_ledger["E_device_runtime_j"] = (
        None
        if device_busy_s is None
        else device_busy_s * float(family_powers["runtime"])
    )
    energy_ledger["E_dma_j"] = None if dma_s is None else dma_s * float(assumptions["dma_w"])
    energy_ledger["E_hardware_datapath_j"] = (
        None
        if device_busy_s is None
        else device_busy_s * float(family_powers["datapath"])
    )
    energy_ledger["E_idle_static_j"] = (
        None
        if wall_time_s is None
        else float(wall_time_s) * float(assumptions["idle_static_w"])
    )

    if all(value is not None for value in energy_ledger.values()):
        row["primary_metrics"]["energy_to_convergence_j"] = sum(
            float(value) for value in energy_ledger.values()
        )
        if wall_time_s not in (None, 0):
            row["primary_metrics"]["avg_system_power_proxy_w"] = (
                float(row["primary_metrics"]["energy_to_convergence_j"]) / float(wall_time_s)
            )

    graph_evidence = row.get("graph_evidence")
    if isinstance(graph_evidence, dict):
        graph_evidence["execution_plan_summary"] = summarize_graph_execution_plan_profile(
            candidate.get("graph_frontdoor_profile")
        )
        (
            runtime_scores,
            score_source,
            cluster_cycle_summary,
            score_signal_summary,
            iteration_behavior_text,
        ) = graph_component_scores_runtime_aware(
            str(row["design_point"]["family"]),
            [
                component_ref.strip()
                for component_ref in str(graph_evidence.get("key_component_refs_summary") or "").split(",")
                if component_ref.strip()
            ],
            str(row["design_point"]["resident_policy"]),
            candidate,
            row.get("workload"),
        )
        if runtime_scores:
            graph_evidence["component_score_summary"] = graph_component_score_summary(runtime_scores)
            graph_evidence["leaf_bottleneck_component_summary"] = graph_leaf_bottleneck_component_summary(
                runtime_scores
            )
            graph_evidence["bottleneck_component_summary"] = ", ".join(
                component_ref for component_ref, _ in runtime_scores[:4]
            )
            graph_evidence["component_score_source"] = score_source
            graph_evidence["cluster_cycle_summary"] = cluster_cycle_summary
            graph_evidence["component_score_signal_summary"] = score_signal_summary
            graph_evidence["iteration_behavior_summary"] = iteration_behavior_text

    confidence_label = last_iteration.get("confidence_label")
    if confidence_label in {"high", "medium", "exploratory"}:
        row["projection"]["confidence"] = confidence_label

    required_metrics = (
        row["primary_metrics"]["time_to_convergence_s"],
        row["primary_metrics"]["speedup_to_convergence"],
        row["primary_metrics"]["energy_to_convergence_j"],
        row["primary_metrics"]["bytes_moved_to_convergence"],
        row["secondary_metrics"]["fallback_ratio"],
        row["secondary_metrics"]["spill_ratio"],
    )
    row["projection"]["ranking_grade_ready"] = (
        final.get("converged") is True and all(value is not None for value in required_metrics)
    )


def load_candidate_payload_for_row(row: dict[str, object]) -> dict[str, Any] | None:
    metrics_path = row["artifacts"].get("metrics_path")
    if not metrics_path:
        return None
    path = Path(str(metrics_path))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def finalize_fast_layer_bundle_metrics(
    bundle: dict[str, object], args: argparse.Namespace
) -> None:
    mainline_rows = [
        row
        for row in bundle["results"]
        if row["workload"].get("lane") == "qe_next_stage_mainline"
        and row["workload"].get("software_family") == "QE"
        and row["result_status"] in {"executed", "compared"}
    ]
    by_workload: dict[str, list[dict[str, object]]] = {}
    for row in mainline_rows:
        by_workload.setdefault(str(row["workload"]["workload_id"]), []).append(row)

    for workload_id, workload_rows in by_workload.items():
        baseline = get_cpu_shell_baseline(workload_rows[0]["workload"], args)
        baseline_time_s = None if baseline is None else baseline.get("pwscf_wall_s") or baseline.get("electrons_wall_s")
        anchor_row = next(
            (
                row
                for row in workload_rows
                if row["design_point"]["family"] == "F1"
                and row["design_point"]["canonical_profile_match"]
            ),
            None,
        )
        anchor_payload = None if anchor_row is None else load_candidate_payload_for_row(anchor_row)
        anchor_ref_cycles = None
        if anchor_payload is not None and anchor_row is not None:
            anchor_ref_cycles = candidate_total_ref_cycles(
                anchor_payload,
                anchor_row["secondary_metrics"].get("device_busy_ref_cycles"),
                anchor_row["secondary_metrics"].get("dma_ref_cycles"),
                anchor_row["secondary_metrics"].get("host_assist_ref_cycles"),
            )

        for row in workload_rows:
            candidate = load_candidate_payload_for_row(row)
            final = {} if candidate is None else candidate.get("final", {})
            total_ref_cycles = candidate_total_ref_cycles(
                candidate,
                row["secondary_metrics"].get("device_busy_ref_cycles"),
                row["secondary_metrics"].get("dma_ref_cycles"),
                row["secondary_metrics"].get("host_assist_ref_cycles"),
            )
            if (
                baseline_time_s is None
                or total_ref_cycles is None
                or anchor_ref_cycles in (None, 0)
            ):
                required_metrics = (
                    row["primary_metrics"]["time_to_convergence_s"],
                    row["primary_metrics"]["speedup_to_convergence"],
                    row["primary_metrics"]["energy_to_convergence_j"],
                    row["primary_metrics"]["bytes_moved_to_convergence"],
                    row["secondary_metrics"]["fallback_ratio"],
                    row["secondary_metrics"]["spill_ratio"],
                )
                row["projection"]["ranking_grade_ready"] = (
                    final.get("converged") is True
                    and all(value is not None for value in required_metrics)
                )
                continue

            derived_time_s = float(baseline_time_s) * float(total_ref_cycles) / float(anchor_ref_cycles)
            row["primary_metrics"]["time_to_convergence_s"] = derived_time_s
            row["primary_metrics"]["speedup_to_convergence"] = (
                None if derived_time_s == 0.0 else float(baseline_time_s) / derived_time_s
            )
            row["comparison_contract"]["qe_baseline_id"] = f"{workload_id}_qe_cpu_shell_aggregate_v0"

            assumptions = energy_proxy_assumptions(
                str(args.assumption_set_id), args.fast_layer_proxy_assumptions_path
            )
            device_busy_s = seconds_from_ref_cycles(
                row["secondary_metrics"]["device_busy_ref_cycles"],
                total_ref_cycles,
                derived_time_s,
            )
            dma_s = seconds_from_ref_cycles(
                row["secondary_metrics"]["dma_ref_cycles"],
                total_ref_cycles,
                derived_time_s,
            )
            host_assist_s = seconds_from_ref_cycles(
                row["secondary_metrics"]["host_assist_ref_cycles"],
                total_ref_cycles,
                derived_time_s,
            )
            host_control_s = max(derived_time_s - float(host_assist_s or 0.0), 0.0)
            family = str(row["design_point"]["family"])
            family_powers = assumptions["family_device_power_w"][family]
            energy_ledger = row["energy_ledger"]
            energy_ledger["E_host_j"] = host_control_s * float(assumptions["host_control_w"]) + float(
                host_assist_s or 0.0
            ) * float(assumptions["host_assist_w"])
            energy_ledger["E_device_runtime_j"] = (
                None if device_busy_s is None else device_busy_s * float(family_powers["runtime"])
            )
            energy_ledger["E_dma_j"] = None if dma_s is None else dma_s * float(assumptions["dma_w"])
            energy_ledger["E_hardware_datapath_j"] = (
                None if device_busy_s is None else device_busy_s * float(family_powers["datapath"])
            )
            energy_ledger["E_idle_static_j"] = derived_time_s * float(assumptions["idle_static_w"])
            if all(value is not None for value in energy_ledger.values()):
                row["primary_metrics"]["energy_to_convergence_j"] = sum(
                    float(value) for value in energy_ledger.values()
                )
                if derived_time_s not in (None, 0):
                    row["primary_metrics"]["avg_system_power_proxy_w"] = (
                        float(row["primary_metrics"]["energy_to_convergence_j"]) / float(derived_time_s)
                    )

            row["projection"]["confidence"] = "exploratory"
            required_metrics = (
                row["primary_metrics"]["time_to_convergence_s"],
                row["primary_metrics"]["speedup_to_convergence"],
                row["primary_metrics"]["energy_to_convergence_j"],
                row["primary_metrics"]["bytes_moved_to_convergence"],
                row["secondary_metrics"]["fallback_ratio"],
                row["secondary_metrics"]["spill_ratio"],
            )
            row["projection"]["ranking_grade_ready"] = (
                final.get("converged") is True and all(value is not None for value in required_metrics)
            )


def refresh_family_summary(bundle: dict[str, object]) -> None:
    mainline_workloads = {
        str(workload["workload_id"])
        for workload in bundle["experiment"]["workloads"]
        if workload.get("lane") == "qe_next_stage_mainline"
    }
    confidence_order = {"pending": 0, "exploratory": 1, "medium": 2, "high": 3}
    for summary in bundle["family_summary"]:
        family = summary["family"]
        family_rows = [
            row
            for row in bundle["results"]
            if row["design_point"]["family"] == family
            and row["workload"].get("lane") == "qe_next_stage_mainline"
        ]
        ready_workloads = {
            str(row["workload"]["workload_id"])
            for row in family_rows
            if row["projection"]["ranking_grade_ready"]
        }
        summary["ranking_grade_status"] = (
            "ready" if mainline_workloads and ready_workloads >= mainline_workloads else "pending"
        )

        projection_ready_workloads = {
            str(row["workload"]["workload_id"])
            for row in family_rows
            if row["projection"]["projection_grade_ready"]
        }
        summary["projection_grade_status"] = (
            "ready"
            if mainline_workloads and projection_ready_workloads >= mainline_workloads
            else "pending"
        )

        confidences = [
            str(row["projection"]["confidence"])
            for row in family_rows
            if row["projection"]["ranking_grade_ready"]
            and str(row["projection"]["confidence"]) in confidence_order
        ]
        summary["confidence"] = (
            min(confidences, key=lambda value: confidence_order[value])
            if confidences
            else "pending"
        )


def refresh_candidate_family_summary(bundle: dict[str, object]) -> None:
    bundle["candidate_family_summary"] = build_candidate_family_summary(bundle["results"])


def normalize_flow_family_for_model(workload: dict[str, object]) -> str:
    software_family = str(workload["software_family"])
    flow_family = str(workload["flow_family"])
    if software_family == "QE" and flow_family == "QE_SCF":
        return "CBANDS_DIAG"
    return flow_family


def model_env(
    workload: dict[str, object],
    row: dict[str, object],
    candidate_json_path: Path,
    args: argparse.Namespace,
    model_max_scf_iters: int,
) -> dict[str, str]:
    design = row["design_point"]
    env = os.environ.copy()
    diag_policy = str(design["diag_policy"])
    env.update(
        {
            "QEBS_SOFTWARE_FAMILY": str(workload["software_family"]),
            "QEBS_FLOW_FAMILY": normalize_flow_family_for_model(workload),
            "QEBS_ARCH_FAMILY": str(design["family"]),
            "QEBS_CANDIDATE_FAMILY": str(row.get("candidate_family") or design["family"]),
            "QEBS_RUNTIME_PROJECTION_FAMILY": str(
                row.get("runtime_projection_family") or design["family"]
            ),
            "QEBS_ASSUMPTION_SET_ID": args.assumption_set_id,
            "QEBS_SIGNATURE_ID": str(workload.get("signature_id") or ""),
            "QEBS_PROPERTY_TARGET": str(workload.get("property_target") or ""),
            "QEBS_PSEUDOPOTENTIAL_FAMILY": str(workload.get("pseudopotential_family") or ""),
            "QEBS_SOLVER_PATH_CLASS": str(workload.get("solver_path_class") or ""),
            "QEBS_WORKLOAD_TOPOLOGY": str(workload.get("workload_topology") or ""),
            "QEBS_POST_SCF_EXTENSION_LEVEL": str(workload.get("post_scf_extension_level") or ""),
            "QEBS_PROJECTOR_PRESSURE": str(workload.get("projector_pressure") or ""),
            "QEBS_NONLOCAL_PRESSURE": str(workload.get("nonlocal_pressure") or ""),
            "QEBS_GENERALIZED_RATIO_BUCKET": str(workload.get("generalized_ratio_bucket") or ""),
            "QEBS_DIAG_DOMINANCE": str(workload.get("diag_dominance") or ""),
            "QEBS_FFT_GRID_PRESSURE": str(workload.get("fft_grid_pressure") or ""),
            "QEBS_OFFLOAD_SCOPE": str(design["offload_scope"]),
            "QEBS_RESIDENT_POLICY": str(design["resident_policy"]),
            "QEBS_MAX_SCF_ITERS": str(model_max_scf_iters),
            "QEBS_CASE_ID": str(workload["workload_id"]),
            "QEBS_RESULT_JSON": str(candidate_json_path),
        }
    )
    if diag_policy == "cpu_only":
        env["QEBS_FORCE_HOST_DIAG"] = "1"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "1"
    elif diag_policy == "aggressive_device":
        env["QEBS_FORCE_HOST_DIAG"] = "0"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "0"
    else:
        env["QEBS_FORCE_HOST_DIAG"] = "0"
        env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = "1"
    graph_frontdoor_hints = workload.get("graph_frontdoor_execution_hints")
    if isinstance(graph_frontdoor_hints, dict):
        if "enable_fft" in graph_frontdoor_hints:
            env["QEBS_ENABLE_FFT"] = "1" if graph_frontdoor_hints["enable_fft"] else "0"
        if "allow_cpu_diag_fallback" in graph_frontdoor_hints:
            env["QEBS_ALLOW_CPU_DIAG_FALLBACK"] = (
                "1" if graph_frontdoor_hints["allow_cpu_diag_fallback"] else "0"
            )
        if "force_host_diag" in graph_frontdoor_hints:
            env["QEBS_FORCE_HOST_DIAG"] = "1" if graph_frontdoor_hints["force_host_diag"] else "0"
        if graph_frontdoor_hints.get("device_diag_max_dim") is not None:
            env["QEBS_DEVICE_DIAG_MAX_DIM"] = str(graph_frontdoor_hints["device_diag_max_dim"])
        if graph_frontdoor_hints.get("graph_id") is not None:
            env["QEBS_GRAPH_ID"] = str(graph_frontdoor_hints["graph_id"])
        if graph_frontdoor_hints.get("topology_style") is not None:
            env["QEBS_GRAPH_TOPOLOGY_STYLE"] = str(graph_frontdoor_hints["topology_style"])
        if graph_frontdoor_hints.get("graph_module_count") is not None:
            env["QEBS_GRAPH_MODULE_COUNT"] = str(graph_frontdoor_hints["graph_module_count"])
        if graph_frontdoor_hints.get("graph_flow_count") is not None:
            env["QEBS_GRAPH_FLOW_COUNT"] = str(graph_frontdoor_hints["graph_flow_count"])
        if graph_frontdoor_hints.get("leaf_component_count") is not None:
            env["QEBS_GRAPH_LEAF_COMPONENT_COUNT"] = str(graph_frontdoor_hints["leaf_component_count"])
        if graph_frontdoor_hints.get("has_fft_unit") is not None:
            env["QEBS_GRAPH_HAS_FFT_UNIT"] = "1" if graph_frontdoor_hints["has_fft_unit"] else "0"
        if graph_frontdoor_hints.get("has_reduction_unit") is not None:
            env["QEBS_GRAPH_HAS_REDUCTION"] = "1" if graph_frontdoor_hints["has_reduction_unit"] else "0"
        if graph_frontdoor_hints.get("has_diag_unit") is not None:
            env["QEBS_GRAPH_HAS_DIAG"] = "1" if graph_frontdoor_hints["has_diag_unit"] else "0"
        if graph_frontdoor_hints.get("has_vector_diag_companion") is not None:
            env["QEBS_GRAPH_HAS_VECTOR_DIAG"] = (
                "1" if graph_frontdoor_hints["has_vector_diag_companion"] else "0"
            )
        if graph_frontdoor_hints.get("has_refresh_unit") is not None:
            env["QEBS_GRAPH_HAS_REFRESH"] = "1" if graph_frontdoor_hints["has_refresh_unit"] else "0"
        if graph_frontdoor_hints.get("has_leaf_hotpath_flow") is not None:
            env["QEBS_GRAPH_HAS_LEAF_FLOW"] = (
                "1" if graph_frontdoor_hints["has_leaf_hotpath_flow"] else "0"
            )
        if graph_frontdoor_hints.get("prefers_diag_before_reduction") is not None:
            env["QEBS_GRAPH_PREFERS_DIAG_BEFORE_REDUCTION"] = (
                "1" if graph_frontdoor_hints["prefers_diag_before_reduction"] else "0"
            )
        if graph_frontdoor_hints.get("prefers_refresh_before_diag") is not None:
            env["QEBS_GRAPH_PREFERS_REFRESH_BEFORE_DIAG"] = (
                "1" if graph_frontdoor_hints["prefers_refresh_before_diag"] else "0"
            )
        if graph_frontdoor_hints.get("requested_cluster_sequence") is not None:
            env["QEBS_GRAPH_REQUESTED_CLUSTER_SEQUENCE"] = str(
                graph_frontdoor_hints["requested_cluster_sequence"]
            )
        if graph_frontdoor_hints.get("resolved_cluster_sequence") is not None:
            env["QEBS_GRAPH_RESOLVED_CLUSTER_SEQUENCE"] = str(
                graph_frontdoor_hints["resolved_cluster_sequence"]
            )
        if graph_frontdoor_hints.get("sequence_constraint_notes") is not None:
            env["QEBS_GRAPH_SEQUENCE_CONSTRAINTS"] = str(
                graph_frontdoor_hints["sequence_constraint_notes"]
            )
        env["QEBS_GRAPH_FRONTDOOR_MODE"] = str(
            graph_frontdoor_hints.get("execution_mode", "projected_design_point_only")
        )
    projected_config_path = row.get("projected_config_path")
    if projected_config_path:
        env["QEBS_ARCH_CONFIG"] = str(projected_config_path)
    return env


def run_model_for_row(
    bundle: dict[str, object],
    row: dict[str, object],
    args: argparse.Namespace,
    artifacts_dir: Path,
    baseline_payload: dict[str, object] | None = None,
) -> tuple[bool, str]:
    workload = row["workload"]
    cpu_shell_baseline = get_cpu_shell_baseline(workload, args)
    candidate_json_path = artifacts_dir / "candidate" / f"{row['result_id']}.json"
    stdout_path = artifacts_dir / "stdout" / f"{row['result_id']}.log"
    candidate_json_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)

    model_max_scf_iters = args.model_max_scf_iters
    if baseline_payload is not None and args.auto_match_baseline_iters:
        final = baseline_payload.get("final", {})
        baseline_iters = final.get("scf_iterations")
        if isinstance(baseline_iters, int) and baseline_iters > 0:
            model_max_scf_iters = baseline_iters
    elif cpu_shell_baseline is not None and args.auto_match_baseline_iters:
        baseline_iters = cpu_shell_baseline.get("scf_iterations")
        if isinstance(baseline_iters, int) and baseline_iters > 0:
            model_max_scf_iters = baseline_iters

    env = model_env(workload, row, candidate_json_path, args, model_max_scf_iters)
    with stdout_path.open("w", encoding="utf-8") as log_fh:
        proc = subprocess.run(
            [str(args.model_bin)],
            cwd=ROOT,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    artifacts = row["artifacts"]
    artifacts["model_run_id"] = f"{bundle['experiment']['run_id']}::{row['result_id']}"
    artifacts["stdout_path"] = str(stdout_path)
    artifacts["metrics_path"] = str(candidate_json_path)
    artifacts["raw_trace_paths"] = [str(stdout_path)]
    row["primary_metrics"]["scf_iterations_to_convergence"] = model_max_scf_iters

    if proc.returncode != 0:
        row["result_status"] = "model_error"
        row["stub_reason"] = f"model_returncode={proc.returncode}"
        row["correctness"]["status"] = "model_error"
        return False, f"model returned {proc.returncode}"
    if not candidate_json_path.exists():
        row["result_status"] = "candidate_missing"
        row["stub_reason"] = "candidate JSON was not emitted"
        row["correctness"]["status"] = "candidate_missing"
        return False, "candidate JSON missing"

    row["result_status"] = "executed"
    row["stub_reason"] = ""
    apply_equal_candidate_fields(
        row,
        args,
        candidate_family=str(row.get("candidate_family") or row["design_point"]["family"]),
        runtime_projection_family=str(
            row.get("runtime_projection_family") or row["design_point"]["family"]
        ),
        template_tags=row.get("template_tags") if isinstance(row.get("template_tags"), list) else [],
        native_runtime_evidence_path=str(candidate_json_path),
    )
    candidate = json.loads(candidate_json_path.read_text(encoding="utf-8"))
    populate_fast_layer_proxy_metrics(row, candidate, cpu_shell_baseline, args)
    return True, "executed"


def prepare_qe_gold_baseline(
    workload: dict[str, object],
    args: argparse.Namespace,
    artifacts_dir: Path,
) -> tuple[dict[str, object] | None, Path | None, str | None]:
    if not workload["gold_required"]:
        return None, None, None

    baseline_dir = args.gold_baseline_root / str(workload["workload_id"])
    metadata_path = baseline_dir / "metadata.json"
    stdout_path = baseline_dir / "stdout.out"
    if not metadata_path.exists() and not stdout_path.exists():
        return None, None, f"missing QE baseline under {baseline_dir}"

    baseline_json_path = artifacts_dir / "baseline" / f"{workload['workload_id']}.gold.json"
    baseline_json_path.parent.mkdir(parents=True, exist_ok=True)

    normalize_cmd = [sys.executable, str(args.normalize_gold_helper)]
    if metadata_path.exists():
        normalize_cmd += ["--metadata", str(metadata_path)]
    if stdout_path.exists():
        normalize_cmd += ["--stdout", str(stdout_path)]
    normalize_cmd += ["--case-id", str(workload["workload_id"]), "--output", str(baseline_json_path)]
    normalize_proc = subprocess.run(
        normalize_cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if normalize_proc.returncode != 0:
        error = normalize_proc.stderr.strip() or normalize_proc.stdout.strip()
        return None, None, error or "baseline normalization failed"

    payload = json.loads(baseline_json_path.read_text(encoding="utf-8"))
    return payload, baseline_json_path, None


def is_si8_f1_convergence_target(row: dict[str, object]) -> bool:
    workload = row["workload"]
    design = row["design_point"]
    return (
        workload["workload_id"] == "si8_pbe_nc"
        and design["family"] == "F1"
        and design["canonical_profile_match"] is True
    )


def nested_dict_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def energy_gap_snapshot(
    baseline_total_energy_ry: float | int | None,
    candidate_total_energy_ry: float | int | None,
    scf_iteration: int | None,
) -> dict[str, object]:
    if baseline_total_energy_ry is None or candidate_total_energy_ry is None:
        return {
            "scf_iteration": scf_iteration,
            "candidate_total_energy_ry": candidate_total_energy_ry,
            "final_total_energy_abs_err_ev": None,
            "final_total_energy_rel_err": None,
        }

    baseline_energy = float(baseline_total_energy_ry)
    candidate_energy = float(candidate_total_energy_ry)
    abs_err_ry = abs(candidate_energy - baseline_energy)
    rel_err = abs_err_ry / max(abs(baseline_energy), 1.0)
    return {
        "scf_iteration": scf_iteration,
        "candidate_total_energy_ry": candidate_energy,
        "final_total_energy_abs_err_ev": abs_err_ry * RY_TO_EV,
        "final_total_energy_rel_err": rel_err,
    }


def classify_si8_f1_convergence_blocker(
    compare_report: dict[str, Any],
    candidate_payload: dict[str, Any],
    baseline_payload: dict[str, Any],
) -> tuple[str, str, str]:
    field_map = {item["name"]: item for item in compare_report["field_results"]}
    baseline_final = baseline_payload.get("final", {})
    candidate_final = candidate_payload.get("final", {})
    candidate_iterations = candidate_payload.get("iteration_diagnostics", [])
    last_iteration = candidate_iterations[-1] if candidate_iterations else {}
    last_diag_path = str(last_iteration.get("diag_path") or "unknown")
    candidate_scf_iterations = candidate_final.get("scf_iterations")
    baseline_scf_iterations = baseline_final.get("scf_iterations")
    max_scf_iters = nested_dict_get(candidate_payload, "run_config", "max_scf_iters")
    energy_abs_err_ev = energy_gap_snapshot(
        baseline_final.get("total_energy_ry"),
        candidate_final.get("total_energy_ry"),
        candidate_scf_iterations if isinstance(candidate_scf_iterations, int) else None,
    )["final_total_energy_abs_err_ev"]

    if compare_report["overall_pass"] is True:
        reason = (
            "Candidate matches the frozen QE gold-required end-state for si8_pbe_nc/F1, so "
            "this lane now serves as the accurate-layer passing anchor rather than an active "
            "narrowing blocker."
        )
        next_move = (
            "Keep si8_pbe_nc/F1 fixed as the accurate-layer passing reference and reuse this "
            "calibrated lane when promoting projection-grade recommendations."
        )
        return "gold_passed", reason, next_move

    if (
        field_map.get("final_converged", {}).get("status") == "fail"
        or field_map.get("final_residual_threshold_reached", {}).get("status") == "fail"
    ):
        reason = (
            "Candidate does not preserve the frozen QE convergence-state contract for "
            f"si8_pbe_nc/F1: converged={candidate_final.get('converged')}, "
            f"residual_threshold_reached={candidate_final.get('residual_threshold_reached')}."
        )
        next_move = (
            "Keep F1 fixed and narrow on convergence-state progression first; do not touch "
            "other families or the frozen compare thresholds."
        )
        return "convergence_state_mismatch", reason, next_move

    if (
        compare_report["overall_pass"] is False
        and candidate_final.get("converged") is not True
        and isinstance(candidate_scf_iterations, int)
        and isinstance(max_scf_iters, int)
        and candidate_scf_iterations >= max_scf_iters
    ):
        reason = (
            "Candidate exhausts the configured SCF budget before reaching the QE gold end-state "
            f"(candidate iters={candidate_scf_iterations}, max_scf_iters={max_scf_iters}, "
            f"baseline iters={baseline_scf_iterations})."
        )
        next_move = (
            "Keep si8_pbe_nc/F1 as the only active convergence target and retune the F1 iteration "
            "path so the model can approach the QE baseline without expanding to other families."
        )
        return "iteration_cap_mismatch", reason, next_move

    reason = (
        "Candidate reaches the QE end-state flags but its energy path remains far from the QE gold "
        f"baseline (final_total_energy_abs_err_ev={energy_abs_err_ev}, "
        f"candidate iters={candidate_scf_iterations}, baseline iters={baseline_scf_iterations}, "
        f"last_diag_path={last_diag_path})."
    )
    next_move = (
        "Keep si8_pbe_nc/F1 fixed and calibrate the host_cpu_fallback energy update/diag path "
        "against the QE gold energy trajectory before changing any other family or tolerance."
    )
    return "energy_trajectory_mismatch", reason, next_move


def build_si8_f1_convergence_report(
    row: dict[str, object],
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    compare_report: dict[str, Any],
) -> dict[str, Any]:
    baseline_final = baseline_payload.get("final", {})
    candidate_final = candidate_payload.get("final", {})
    iteration_diagnostics = [
        item for item in candidate_payload.get("iteration_diagnostics", []) if isinstance(item, dict)
    ]

    before_iteration = iteration_diagnostics[0] if iteration_diagnostics else {}
    after_iteration = iteration_diagnostics[-1] if iteration_diagnostics else {}
    diag_path_counts = Counter(
        str(item["diag_path"])
        for item in iteration_diagnostics
        if item.get("diag_path")
    )
    blocker_kind, blocker_reason, next_move = classify_si8_f1_convergence_blocker(
        compare_report,
        candidate_payload,
        baseline_payload,
    )
    field_map = {item["name"]: item for item in compare_report["field_results"]}
    required_failed_fields = [
        item["name"]
        for item in compare_report["field_results"]
        if item["required"] and item["status"] != "pass"
    ]

    report = {
        "report_kind": "si8_f1_convergence_lane_report_v0",
        "generated_at_utc": iso_utc(utc_now()),
        "case_id": row["workload"]["workload_id"],
        "family": row["design_point"]["family"],
        "priority_target": {
            "first_priority_convergence_case": True,
            "fixed_first_family": True,
            "rationale": (
                "F1 stays fixed as the first convergence family because host_cpu_fallback is the "
                "least-coupled first-pass target relative to QE CPU-side behavior."
            ),
        },
        "gold_snapshot": {
            "overall_pass": compare_report["overall_pass"],
            "required_failed_fields": required_failed_fields,
            "energy_field_status": field_map.get("final_total_energy_ry", {}).get("status"),
            "converged_field_status": field_map.get("final_converged", {}).get("status"),
            "residual_field_status": field_map.get(
                "final_residual_threshold_reached", {}
            ).get("status"),
        },
        "baseline_final": {
            "final_total_energy_ry": baseline_final.get("total_energy_ry"),
            "final_converged": baseline_final.get("converged"),
            "final_residual_threshold_reached": baseline_final.get(
                "residual_threshold_reached"
            ),
            "scf_iterations": baseline_final.get("scf_iterations"),
        },
        "candidate_final": {
            "final_total_energy_ry": candidate_final.get("total_energy_ry"),
            "final_converged": candidate_final.get("converged"),
            "final_residual_threshold_reached": candidate_final.get(
                "residual_threshold_reached"
            ),
            "scf_iterations": candidate_final.get("scf_iterations"),
            "residual_norm": candidate_final.get("residual_norm"),
            "density_delta": candidate_final.get("density_delta"),
        },
        "gap_report": {
            "before": energy_gap_snapshot(
                baseline_final.get("total_energy_ry"),
                before_iteration.get("total_energy_ry", candidate_final.get("total_energy_ry")),
                before_iteration.get("scf_iteration"),
            ),
            "after": energy_gap_snapshot(
                baseline_final.get("total_energy_ry"),
                after_iteration.get("total_energy_ry", candidate_final.get("total_energy_ry")),
                after_iteration.get("scf_iteration", candidate_final.get("scf_iterations")),
            ),
            "final_total_energy_abs_err_ev": field_map.get("final_total_energy_ry", {}).get(
                "abs_err", 0.0
            )
            * RY_TO_EV
            if field_map.get("final_total_energy_ry", {}).get("abs_err") is not None
            else None,
            "final_total_energy_rel_err": field_map.get("final_total_energy_ry", {}).get(
                "rel_err"
            ),
            "candidate_iterations": candidate_final.get("scf_iterations"),
            "baseline_iterations": baseline_final.get("scf_iterations"),
            "scf_iteration_delta": (
                candidate_final.get("scf_iterations") - baseline_final.get("scf_iterations")
                if isinstance(candidate_final.get("scf_iterations"), int)
                and isinstance(baseline_final.get("scf_iterations"), int)
                else None
            ),
            "final_converged": candidate_final.get("converged"),
            "final_residual_threshold_reached": candidate_final.get(
                "residual_threshold_reached"
            ),
        },
        "iteration_context": {
            "energy_path_ry": [
                item["total_energy_ry"]
                for item in iteration_diagnostics
                if item.get("total_energy_ry") is not None
            ],
            "diag_path_counts": dict(diag_path_counts),
            "last_diag_path": after_iteration.get("diag_path"),
            "cpu_diag_fallback_count": sum(
                1 for item in iteration_diagnostics if item.get("cpu_diag_fallback") is True
            ),
            "resident_reuse_count": sum(
                1 for item in iteration_diagnostics if item.get("resident_reused") is True
            ),
            "spill_active_count": sum(
                1 for item in iteration_diagnostics if item.get("spill_active") is True
            ),
            "used_device_fft_count": sum(
                1 for item in iteration_diagnostics if item.get("used_device_fft") is True
            ),
        },
        "iteration_diagnostics": iteration_diagnostics,
        "dominant_blocker": {
            "kind": blocker_kind,
            "reason": blocker_reason,
        },
        "explicit_next_narrowing_move": next_move,
    }
    return report


def render_si8_f1_convergence_markdown(report: dict[str, Any]) -> str:
    before = report["gap_report"]["before"]
    after = report["gap_report"]["after"]
    lines = [
        "# si8_pbe_nc / F1 convergence lane report",
        "",
        f"- generated_at_utc: {report['generated_at_utc']}",
        f"- gold_pass: {'yes' if report['gold_snapshot']['overall_pass'] else 'no'}",
        f"- blocker: {report['dominant_blocker']['kind']}",
        f"- last_diag_path: {report['iteration_context']['last_diag_path']}",
        "",
        "## Final gap snapshot",
        "",
        f"- baseline_final_total_energy_ry: {report['baseline_final']['final_total_energy_ry']}",
        f"- candidate_final_total_energy_ry: {report['candidate_final']['final_total_energy_ry']}",
        f"- final_total_energy_abs_err_ev: {report['gap_report']['final_total_energy_abs_err_ev']}",
        f"- final_total_energy_rel_err: {report['gap_report']['final_total_energy_rel_err']}",
        f"- baseline_iterations: {report['gap_report']['baseline_iterations']}",
        f"- candidate_iterations: {report['gap_report']['candidate_iterations']}",
        f"- final_converged: {report['gap_report']['final_converged']}",
        f"- final_residual_threshold_reached: {report['gap_report']['final_residual_threshold_reached']}",
        "",
        "## Before / after within-run energy gap",
        "",
        f"- before_iter: {before['scf_iteration']}, before_abs_err_ev: {before['final_total_energy_abs_err_ev']}",
        f"- after_iter: {after['scf_iteration']}, after_abs_err_ev: {after['final_total_energy_abs_err_ev']}",
        "",
        "## Dominant blocker",
        "",
        report["dominant_blocker"]["reason"],
        "",
        "## Next narrowing move",
        "",
        report["explicit_next_narrowing_move"],
        "",
    ]
    return "\n".join(lines)


def emit_si8_f1_convergence_artifacts(
    row: dict[str, object],
    artifacts_dir: Path,
    baseline_payload: dict[str, Any],
    compare_report: dict[str, Any],
) -> list[Path]:
    if not is_si8_f1_convergence_target(row):
        return []

    candidate_path = Path(str(row["artifacts"]["metrics_path"]))
    if not candidate_path.exists():
        return []

    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    report = build_si8_f1_convergence_report(
        row,
        baseline_payload,
        candidate_payload,
        compare_report,
    )

    convergence_dir = artifacts_dir / "convergence"
    convergence_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = convergence_dir / f"{row['result_id']}.si8_f1_convergence.json"
    report_md_path = convergence_dir / f"{row['result_id']}.si8_f1_convergence.md"
    report_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_md_path.write_text(render_si8_f1_convergence_markdown(report), encoding="utf-8")

    row["correctness"]["notes"].append(f"si8_f1_convergence_report={report_json_path}")
    row["correctness"]["notes"].append(f"si8_f1_convergence_summary={report_md_path}")
    raw_trace_paths = row["artifacts"].get("raw_trace_paths") or []
    row["artifacts"]["raw_trace_paths"] = list(raw_trace_paths) + [
        str(report_json_path),
        str(report_md_path),
    ]
    return [report_json_path, report_md_path]


def maybe_run_qe_gold_compare(
    row: dict[str, object],
    args: argparse.Namespace,
    artifacts_dir: Path,
    baseline_payload: dict[str, object] | None = None,
    baseline_json_path: Path | None = None,
) -> tuple[bool, str]:
    workload = row["workload"]
    if not workload["gold_required"]:
        row["correctness"]["status"] = "not_required"
        return True, "gold compare not required"

    if baseline_payload is None or baseline_json_path is None:
        baseline_payload, baseline_json_path, error = prepare_qe_gold_baseline(
            workload, args, artifacts_dir
        )
        if error is not None:
            if "missing QE baseline" in error:
                row["result_status"] = "baseline_missing"
                row["correctness"]["status"] = "baseline_missing"
            else:
                row["result_status"] = "baseline_normalization_error"
                row["correctness"]["status"] = "baseline_normalization_error"
            row["stub_reason"] = error
            return False, error

    if baseline_payload is None or baseline_json_path is None:
        row["result_status"] = "baseline_missing"
        row["correctness"]["status"] = "baseline_missing"
        row["stub_reason"] = "baseline payload unavailable"
        return False, "baseline missing"

    compare_report_path = artifacts_dir / "compare" / f"{row['result_id']}.compare.json"
    compare_report_path.parent.mkdir(parents=True, exist_ok=True)
    row["artifacts"]["compare_report_path"] = str(compare_report_path)

    compare_cmd = [
        sys.executable,
        str(args.compare_helper),
        "--baseline",
        str(baseline_json_path),
        "--candidate",
        str(row["artifacts"]["metrics_path"]),
        "--output",
        str(compare_report_path),
    ]
    compare_proc = subprocess.run(
        compare_cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if compare_proc.returncode not in (0, 1):
        row["result_status"] = "compare_error"
        row["correctness"]["status"] = "compare_error"
        row["stub_reason"] = compare_proc.stderr.strip() or compare_proc.stdout.strip()
        return False, "compare helper failed"

    report = json.loads(compare_report_path.read_text(encoding="utf-8"))
    field_map = {item["name"]: item for item in report["field_results"]}
    energy_field = field_map.get("final_total_energy_ry", {})
    converged_field = field_map.get("final_converged", {})
    residual_field = field_map.get("final_residual_threshold_reached", {})
    scf_iterations_field = field_map.get("scf_iterations", {})

    row["comparison_contract"]["qe_baseline_id"] = f"{workload['workload_id']}_qe_gold"
    row["result_status"] = "compared"
    row["correctness"]["status"] = "pass" if report["overall_pass"] else "mismatch"
    row["correctness"]["gold_pass"] = report["overall_pass"]
    row["correctness"]["final_total_energy_match"] = energy_field.get("status") == "pass"
    row["correctness"]["converged_state_match"] = converged_field.get("status") == "pass"
    row["correctness"]["residual_threshold_state_match"] = residual_field.get("status") == "pass"
    row["correctness"]["convergence_comparable_pass"] = (
        row["correctness"]["converged_state_match"] is True
        and row["correctness"]["residual_threshold_state_match"] is True
    )
    row["correctness"]["required_field_failures"] = list(
        report["summary"].get("failed_required_fields", [])
    )
    row["correctness"]["baseline_scf_iterations"] = scf_iterations_field.get("baseline", {}).get(
        "value"
    )
    row["correctness"]["candidate_scf_iterations"] = scf_iterations_field.get(
        "candidate", {}
    ).get("value")
    abs_err_ry = energy_field.get("abs_err")
    row["correctness"]["final_total_energy_abs_err_ev"] = (
        None if abs_err_ry is None else float(abs_err_ry) * RY_TO_EV
    )
    row["correctness"]["final_total_energy_rel_err"] = energy_field.get("rel_err")
    row["correctness"]["notes"] = list(report["summary"].get("required_failure_messages", []))
    raw_trace_paths = row["artifacts"].get("raw_trace_paths") or []
    row["artifacts"]["raw_trace_paths"] = list(raw_trace_paths) + [
        str(baseline_json_path),
        str(compare_report_path),
    ]
    emit_si8_f1_convergence_artifacts(
        row,
        artifacts_dir,
        baseline_payload,
        report,
    )
    return report["overall_pass"], "compared"


def build_bundle(
    args: argparse.Namespace,
    ts: datetime,
    workloads: list[dict[str, object]],
    families: list[str],
    diag_policies: list[str],
    offload_scopes: list[str],
    resident_policies: list[str],
    partition_strategies: list[str] | None,
) -> dict[str, object]:
    run_id = args.run_id or default_run_id(ts)
    proxy_assumption_payload = load_proxy_assumption_payload(args.fast_layer_proxy_assumptions_path)
    design_space_summary = load_design_space_spec_summary(getattr(args, "design_space_spec", None))
    selected_templates: list[dict[str, Any]] = []
    if getattr(args, "template_driven", False):
        selected_templates = load_architecture_templates(
            args.architecture_template_dir,
            getattr(args, "architecture_template_ids", None),
        )
        results = []
        candidate_index = 0
        for workload, template in product(workloads, selected_templates):
            if args.max_design_points is not None and len(results) >= args.max_design_points:
                break
            candidate_index += 1
            results.append(
                build_template_result_row(
                    workload,
                    template,
                    args,
                    candidate_index,
                    design_space_summary,
                )
            )
    else:
        resolved_partition_axis = partition_strategies or [None]
        results = [
            build_result_row(
                workload,
                family,
                diag_policy,
                offload_scope,
                resident_policy,
                args,
                partition_strategy,
            )
            for workload, family, diag_policy, offload_scope, resident_policy, partition_strategy in product(
                workloads,
                families,
                diag_policies,
                offload_scopes,
                resident_policies,
                resolved_partition_axis,
            )
        ]
        if args.canonical_only:
            results = [row for row in results if row["design_point"]["canonical_profile_match"]]
    if args.max_design_points is not None and not getattr(args, "template_driven", False):
        results = results[: args.max_design_points]
    resolved_partition_values = sorted(
        {str(row["design_point"]["partition_strategy"]) for row in results}
    )
    resolved_template_ids = [str(template.get("template_id")) for template in selected_templates]
    return {
        "schema_version": "systemc_architecture_family_dse_result_schema_v0",
        "result_bundle_kind": "architecture_family_dse_bundle",
        "generated_at_utc": iso_utc(ts),
        "experiment": {
            "run_id": run_id,
            "producer_script": str(Path(__file__).resolve()),
            "schema_path": str(SCHEMA_PATH),
            "source_model": args.source_model,
            "assumption_set_id": args.assumption_set_id,
            "fast_layer_proxy_assumptions_path": str(args.fast_layer_proxy_assumptions_path),
            "fast_layer_proxy_assumptions_schema_version": str(
                proxy_assumption_payload.get("schema_version", "unknown")
            ),
            "fast_layer_proxy_assumptions_sha256": file_sha256(
                args.fast_layer_proxy_assumptions_path
            ),
            "qe_tolerance_schema_id": args.qe_tolerance_schema_id,
            "workload_group_contract_path": str(WORKLOAD_GROUP_CONTRACT_PATH),
            "fairness_power_contract_path": str(FAIRNESS_POWER_CONTRACT_PATH),
            "observability_contract_path": str(OBSERVABILITY_CONTRACT_PATH),
            "algorithm_rewrite_manifest_contract_path": str(
                ALGORITHM_REWRITE_MANIFEST_CONTRACT_PATH
            ),
            "cpu_gpu_baseline_runbook_path": str(CPU_GPU_BASELINE_RUNBOOK_PATH),
            "optimized_system_delta_path": str(OPTIMIZED_SYSTEM_DELTA_PATH),
            "source_kind": args.source_kind,
            "template_driven": bool(getattr(args, "template_driven", False)),
            "architecture_template_dir": (
                str(args.architecture_template_dir) if getattr(args, "template_driven", False) else None
            ),
            "architecture_template_ids": resolved_template_ids,
            "design_space_spec_summary": design_space_summary,
            "gate_contract": {
                **QE_GOLD_GATE_CONTRACT,
                "status_taxonomy": GOLD_STATUS_TAXONOMY,
            },
            "sweep_axes": {
                "family": sorted({str(row["design_point"]["family"]) for row in results}) if results else families,
                "diag_policy": sorted({str(row["design_point"]["diag_policy"]) for row in results}) if results else diag_policies,
                "offload_scope": sorted({str(row["design_point"]["offload_scope"]) for row in results}) if results else offload_scopes,
                "resident_policy": sorted({str(row["design_point"]["resident_policy"]) for row in results}) if results else resident_policies,
                "partition_strategy": resolved_partition_values,
                "architecture_template_id": resolved_template_ids,
            },
            "workloads": workloads,
            "excluded_engineering_knobs": EXCLUDED_ENGINEERING_KNOBS,
        },
        "results": results,
        "family_summary": build_family_summary(results),
        "candidate_family_summary": build_candidate_family_summary(results),
        "notes": [
            "v1 sweep excludes DMA width, buffer depth, and final BRAM/URAM/HBM budget tuning.",
            "Fast-layer ranking metrics are populated only when --execute-model is enabled and the runnable model emits enough proxy data.",
            "Projection range fields remain null until calibrated energy/power and accurate-layer promotion evidence are available.",
            "QE tolerance schema id is carried as metadata so the correctness gate can be frozen before execution.",
            "QE gold summary artifacts add formal workload/family status reporting without changing compare semantics or thresholds.",
        ],
    }


def execute_bundle(bundle: dict[str, object], args: argparse.Namespace, artifacts_dir: Path) -> None:
    baseline_cache: dict[str, tuple[dict[str, object] | None, Path | None, str | None]] = {}
    for row in bundle["results"]:
        workload = row["workload"]
        baseline_payload = None
        baseline_json_path = None
        if workload["gold_required"]:
            workload_id = str(workload["workload_id"])
            if workload_id not in baseline_cache:
                baseline_cache[workload_id] = prepare_qe_gold_baseline(
                    workload, args, artifacts_dir
                )
            baseline_payload, baseline_json_path, baseline_error = baseline_cache[workload_id]
            if baseline_error is not None:
                row["stub_reason"] = baseline_error
                row["correctness"]["status"] = (
                    "baseline_missing"
                    if "missing QE baseline" in baseline_error
                    else "baseline_normalization_error"
                )
                row["result_status"] = (
                    "baseline_missing"
                    if row["correctness"]["status"] == "baseline_missing"
                    else "baseline_normalization_error"
                )
                continue

        ok, reason = run_model_for_row(
            bundle, row, args, artifacts_dir, baseline_payload=baseline_payload
        )
        if not ok:
            row["stub_reason"] = reason
            continue
        compared, compare_reason = maybe_run_qe_gold_compare(
            row,
            args,
            artifacts_dir,
            baseline_payload=baseline_payload,
            baseline_json_path=baseline_json_path,
        )
        if not compared and not row["workload"]["gold_required"]:
            row["stub_reason"] = ""
            continue
        if not compared and compare_reason != "compared":
            row["stub_reason"] = compare_reason
    finalize_fast_layer_bundle_metrics(bundle, args)
    refresh_family_summary(bundle)


def gold_summary_row(row: dict[str, object]) -> dict[str, object]:
    workload = row["workload"]
    design = row["design_point"]
    correctness = row["correctness"]
    return {
        "workload_id": workload["workload_id"],
        "workload_label": workload["label"],
        "family": design["family"],
        "status": correctness["status"],
        "gold_pass": correctness["gold_pass"],
        "first_priority_convergence_case": workload["first_priority_convergence_case"],
        "required_field_failures": correctness["required_field_failures"],
        "field_matches": {
            "final_total_energy_ry": correctness["final_total_energy_match"],
            "final_converged": correctness["converged_state_match"],
            "final_residual_threshold_reached": correctness["residual_threshold_state_match"],
        },
        "final_total_energy_abs_err_ev": correctness["final_total_energy_abs_err_ev"],
        "final_total_energy_rel_err": correctness["final_total_energy_rel_err"],
        "baseline_scf_iterations": correctness["baseline_scf_iterations"],
        "candidate_scf_iterations": correctness["candidate_scf_iterations"],
        "notes": correctness["notes"],
        "stdout_path": row["artifacts"]["stdout_path"],
        "metrics_path": row["artifacts"]["metrics_path"],
        "compare_report_path": row["artifacts"]["compare_report_path"],
        "stub_reason": row["stub_reason"],
    }


def summarize_gold_results(bundle: dict[str, object]) -> dict[str, object]:
    gold_rows = [row for row in bundle["results"] if row["workload"]["gold_required"]]
    status_counts = gold_status_counts(gold_rows)
    return {
        "gold_rows": len(gold_rows),
        "gold_passed": status_counts.get("pass", 0),
        "gold_mismatches": status_counts.get("mismatch", 0),
        "gold_errors": sum(
            status_counts.get(status, 0)
            for status in (
                "baseline_missing",
                "baseline_normalization_error",
                "candidate_missing",
                "model_error",
                "compare_error",
            )
        ),
        "status_counts": status_counts,
    }


def build_gold_gate_summary(bundle: dict[str, object]) -> dict[str, object]:
    gold_rows = [row for row in bundle["results"] if row["workload"]["gold_required"]]
    rows = [gold_summary_row(row) for row in gold_rows]
    by_workload: list[dict[str, object]] = []
    for workload_id in QE_GOLD_GATE_CONTRACT["canonical_gold_workloads"]:
        workload_rows = [row for row in rows if row["workload_id"] == workload_id]
        if not workload_rows:
            continue
        by_workload.append(
            {
                "workload_id": workload_id,
                "workload_label": workload_rows[0]["workload_label"],
                "first_priority_convergence_case": workload_rows[0][
                    "first_priority_convergence_case"
                ],
                "status_counts": gold_status_counts(
                    [
                        {
                            "correctness": {"status": workload_row["status"]},
                        }
                        for workload_row in workload_rows
                    ]
                ),
                "families": workload_rows,
            }
        )

    by_family: list[dict[str, object]] = []
    for family in FAMILY_PROFILES:
        family_rows = [row for row in rows if row["family"] == family]
        if not family_rows:
            continue
        by_family.append(
            {
                "family": family,
                "status_counts": gold_status_counts(
                    [
                        {
                            "correctness": {"status": family_row["status"]},
                        }
                        for family_row in family_rows
                    ]
                ),
                "workloads": family_rows,
            }
        )

    gold_summary = summarize_gold_results(bundle)
    return {
        "schema_version": "qe_gold_gate_summary_v0",
        "generated_at_utc": bundle["generated_at_utc"],
        "run_id": bundle["experiment"]["run_id"],
        "gate_contract": bundle["experiment"]["gate_contract"],
        "gold_rows": rows,
        "status_counts": gold_summary["status_counts"],
        "required_fields": QE_GOLD_GATE_CONTRACT["required_field_order"],
        "by_workload": by_workload,
        "by_family": by_family,
    }


def render_gold_gate_summary_markdown(summary: dict[str, object]) -> str:
    lines = [
        "# QE gold gate summary (v0)",
        "",
        f"- Run id: `{summary['run_id']}`",
        f"- Generated at (UTC): `{summary['generated_at_utc']}`",
        f"- Canonical gold matrix: `{summary['gate_contract']['canonical_gold_matrix_id']}`",
        f"- Canonical gold workloads: `{', '.join(summary['gate_contract']['canonical_gold_workloads'])}`",
        (
            "- First-priority convergence lane: "
            f"`{summary['gate_contract']['first_priority_convergence_case']}` / "
            f"`{summary['gate_contract']['first_priority_convergence_family']}`"
        ),
        "",
        "## Status taxonomy",
        "",
        "- `pass` — all required fields matched under the frozen QE gold contract.",
        "- `mismatch` — compare helper ran, but one or more required fields failed.",
        "- `baseline_missing` / `baseline_normalization_error` — baseline-side infrastructure failure.",
        "- `candidate_missing` / `model_error` / `compare_error` — candidate or compare-side infrastructure failure.",
        "",
        "## Aggregate status counts",
        "",
    ]
    for status in GOLD_STATUS_TAXONOMY:
        lines.append(f"- `{status}`: {summary['status_counts'].get(status, 0)}")

    lines.extend(
        [
            "",
            "## Per-workload view",
            "",
            "| Workload | Family | Status | Failed required fields | Energy abs err (eV) | Energy rel err | Baseline SCF iters | Candidate SCF iters |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for workload_group in summary["by_workload"]:
        for row in workload_group["families"]:
            workload_label = str(workload_group["workload_id"])
            if row["first_priority_convergence_case"]:
                workload_label += " *(first-priority convergence case)*"
            failed_fields = ", ".join(row["required_field_failures"]) or "—"
            abs_err = (
                "—"
                if row["final_total_energy_abs_err_ev"] is None
                else f"{row['final_total_energy_abs_err_ev']:.6e}"
            )
            rel_err = (
                "—"
                if row["final_total_energy_rel_err"] is None
                else f"{row['final_total_energy_rel_err']:.6e}"
            )
            baseline_iters = (
                "—" if row["baseline_scf_iterations"] is None else str(row["baseline_scf_iterations"])
            )
            candidate_iters = (
                "—"
                if row["candidate_scf_iterations"] is None
                else str(row["candidate_scf_iterations"])
            )
            lines.append(
                "| {workload} | {family} | {status} | {failed_fields} | {abs_err} | {rel_err} | {baseline_iters} | {candidate_iters} |".format(
                    workload=workload_label,
                    family=row["family"],
                    status=row["status"],
                    failed_fields=failed_fields,
                    abs_err=abs_err,
                    rel_err=rel_err,
                    baseline_iters=baseline_iters,
                    candidate_iters=candidate_iters,
                )
            )

    lines.extend(
        [
            "",
            "## Per-family view",
            "",
            "| Family | Workload | Status | Failed required fields | Baseline SCF iters | Candidate SCF iters |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for family_group in summary["by_family"]:
        for row in family_group["workloads"]:
            failed_fields = ", ".join(row["required_field_failures"]) or "—"
            baseline_iters = (
                "—" if row["baseline_scf_iterations"] is None else str(row["baseline_scf_iterations"])
            )
            candidate_iters = (
                "—"
                if row["candidate_scf_iterations"] is None
                else str(row["candidate_scf_iterations"])
            )
            workload_label = str(row["workload_id"])
            if row["first_priority_convergence_case"]:
                workload_label += " *(first-priority convergence case)*"
            lines.append(
                "| {family} | {workload} | {status} | {failed_fields} | {baseline_iters} | {candidate_iters} |".format(
                    family=family_group["family"],
                    workload=workload_label,
                    status=row["status"],
                    failed_fields=failed_fields,
                    baseline_iters=baseline_iters,
                    candidate_iters=candidate_iters,
                )
            )
    return "\n".join(lines) + "\n"


def flatten_result(
    bundle: dict[str, object],
    row: dict[str, object],
) -> dict[str, object]:
    workload = row["workload"]
    design = row["design_point"]
    contract = row["comparison_contract"]
    correctness = row["correctness"]
    primary = row["primary_metrics"]
    secondary = row["secondary_metrics"]
    runtime = row["runtime_observability"]
    graph = row["graph_evidence"]
    energy = row["energy_ledger"]
    projection = row["projection"]
    artifacts = row["artifacts"]
    support_evidence = row.get("support_evidence", {})
    if not isinstance(support_evidence, dict):
        support_evidence = {}
    speedup_range = projection["speedup_to_convergence_range"] or {}
    energy_range = projection["energy_to_convergence_range_j"] or {}
    raw_trace_paths = artifacts["raw_trace_paths"]
    return {
        "schema_version": bundle["schema_version"],
        "run_id": bundle["experiment"]["run_id"],
        "generated_at_utc": bundle["generated_at_utc"],
        "result_id": row["result_id"],
        "result_status": row["result_status"],
        "source_kind": row["source_kind"],
        "workload_id": workload["workload_id"],
        "workload_label": workload["label"],
        "software_family": workload["software_family"],
        "flow_family": workload["flow_family"],
        "trait_bucket": workload["trait_bucket"],
        "lane": workload["lane"],
        "gold_required": workload["gold_required"],
        "first_priority_convergence_case": workload["first_priority_convergence_case"],
        "signature_id": workload.get("signature_id"),
        "property_target": workload.get("property_target"),
        "pseudopotential_family": workload.get("pseudopotential_family"),
        "solver_path_class": workload.get("solver_path_class"),
        "workload_topology": workload.get("workload_topology"),
        "post_scf_extension_level": workload.get("post_scf_extension_level"),
        "projector_pressure": workload.get("projector_pressure"),
        "nonlocal_pressure": workload.get("nonlocal_pressure"),
        "generalized_ratio_bucket": workload.get("generalized_ratio_bucket"),
        "diag_dominance": workload.get("diag_dominance"),
        "fft_grid_pressure": workload.get("fft_grid_pressure"),
        "family": design["family"],
        "candidate_family": row.get("candidate_family"),
        "runtime_projection_family": row.get("runtime_projection_family"),
        "evaluator_backend": row.get("evaluator_backend"),
        "fidelity_class": row.get("fidelity_class"),
        "support_status": row.get("support_status"),
        "executor_claim_allowed": support_evidence.get("executor_claim_allowed"),
        "native_runtime_evidence_path": support_evidence.get("native_runtime_evidence_path"),
        "projection_reason": support_evidence.get("projection_reason"),
        "future_backend_note": support_evidence.get("future_backend_note"),
        "claim_boundary": support_evidence.get("claim_boundary"),
        "diag_policy": design["diag_policy"],
        "offload_scope": design["offload_scope"],
        "resident_policy": design["resident_policy"],
        "partition_strategy": design["partition_strategy"],
        "canonical_profile_match": design["canonical_profile_match"],
        "architecture_template_id": row.get("architecture_template_id"),
        "candidate_id": row.get("candidate_id"),
        "projected_config_path": row.get("projected_config_path"),
        "template_family": row.get("template_family"),
        "template_validation_status": row.get("template_validation_status"),
        "template_risk_level": row.get("template_risk_level"),
        "template_tags": ";".join(str(tag) for tag in row.get("template_tags", []))
        if isinstance(row.get("template_tags"), list)
        else "",
        "template_artifact_sha256": row.get("template_artifact_sha256"),
        "design_space_spec_id": row.get("design_space_spec_id"),
        "design_space_spec_sha256": row.get("design_space_spec_sha256"),
        "qe_baseline_id": contract["qe_baseline_id"],
        "workload_group_id": contract["workload_group_id"],
        "qe_tolerance_schema_id": contract["qe_tolerance_schema_id"],
        "accounting_boundary_id": contract["accounting_boundary_id"],
        "fairness_policy_id": contract["fairness_policy_id"],
        "power_boundary_id": contract["power_boundary_id"],
        "observability_contract_id": contract["observability_contract_id"],
        "algorithm_rewrite_manifest_id": contract["algorithm_rewrite_manifest_id"],
        "algorithm_contract_deviation": contract["algorithm_contract_deviation"],
        "correctness_status": correctness["status"],
        "gold_pass": correctness["gold_pass"],
        "convergence_comparable_pass": correctness["convergence_comparable_pass"],
        "final_total_energy_match": correctness["final_total_energy_match"],
        "residual_threshold_state_match": correctness["residual_threshold_state_match"],
        "converged_state_match": correctness["converged_state_match"],
        "required_field_failures": ";".join(correctness["required_field_failures"]),
        "baseline_scf_iterations": correctness["baseline_scf_iterations"],
        "candidate_scf_iterations": correctness["candidate_scf_iterations"],
        "final_total_energy_abs_err_ev": correctness["final_total_energy_abs_err_ev"],
        "final_total_energy_rel_err": correctness["final_total_energy_rel_err"],
        "time_to_convergence_s": primary["time_to_convergence_s"],
        "speedup_to_convergence": primary["speedup_to_convergence"],
        "energy_to_convergence_j": primary["energy_to_convergence_j"],
        "avg_system_power_proxy_w": primary["avg_system_power_proxy_w"],
        "scf_iterations_to_convergence": primary["scf_iterations_to_convergence"],
        "bytes_moved_to_convergence": primary["bytes_moved_to_convergence"],
        "fallback_count_to_convergence": primary["fallback_count_to_convergence"],
        "device_busy_ref_cycles": secondary["device_busy_ref_cycles"],
        "dma_ref_cycles": secondary["dma_ref_cycles"],
        "host_assist_ref_cycles": secondary["host_assist_ref_cycles"],
        "resident_reuse_hits": secondary["resident_reuse_hits"],
        "spill_ratio": secondary["spill_ratio"],
        "fallback_ratio": secondary["fallback_ratio"],
        "complexity_proxy": secondary["complexity_proxy"],
        "runtime_last_diag_path": runtime["last_diag_path"],
        "runtime_last_support_grid_mode": runtime["last_support_grid_mode"],
        "runtime_last_workload_bucket": runtime["last_workload_bucket"],
        "runtime_last_band_count": runtime["last_band_count"],
        "runtime_last_panel_count": runtime["last_panel_count"],
        "runtime_configured_max_inner_steps": runtime["configured_max_inner_steps"],
        "runtime_realized_inner_steps": runtime["realized_inner_steps"],
        "runtime_last_max_diag_condition_estimate": runtime["last_max_diag_condition_estimate"],
        "runtime_spill_active_count": runtime["spill_active_count"],
        "runtime_host_cpu_fallback_count": runtime["host_cpu_fallback_count"],
        "graph_seed_template_id": graph["seed_template_id"],
        "graph_schema_version": graph["graph_schema_version"],
        "graph_module_instance_count": graph["module_instance_count"],
        "graph_link_count": graph["link_count"],
        "graph_flow_count": graph["flow_count"],
        "graph_export_authority": graph["graph_export_authority"],
        "graph_lossless_export_pass": graph["lossless_export_pass"],
        "graph_topology_style": graph["topology_style"],
        "graph_control_plane_summary": graph["control_plane_summary"],
        "graph_datapath_stage_summary": graph["datapath_stage_summary"],
        "graph_key_component_refs_summary": graph["key_component_refs_summary"],
        "graph_leaf_component_refs_summary": graph["leaf_component_refs_summary"],
        "graph_bottleneck_component_summary": graph["bottleneck_component_summary"],
        "graph_leaf_bottleneck_component_summary": graph["leaf_bottleneck_component_summary"],
        "graph_risk_driver_component_summary": graph["risk_driver_component_summary"],
        "graph_component_score_summary": graph["component_score_summary"],
        "graph_component_score_source": graph["component_score_source"],
        "graph_execution_plan_summary": graph["execution_plan_summary"],
        "graph_cluster_cycle_summary": graph["cluster_cycle_summary"],
        "graph_component_score_signal_summary": graph["component_score_signal_summary"],
        "graph_iteration_behavior_summary": graph["iteration_behavior_summary"],
        "graph_dataflow_bottleneck_summary": graph["dataflow_bottleneck_summary"],
        "graph_mapping_risk_summary": graph["mapping_risk_summary"],
        "graph_evidence_path": artifacts["graph_evidence_path"],
        "E_host_j": energy["E_host_j"],
        "E_device_runtime_j": energy["E_device_runtime_j"],
        "E_dma_j": energy["E_dma_j"],
        "E_hardware_datapath_j": energy["E_hardware_datapath_j"],
        "E_idle_static_j": energy["E_idle_static_j"],
        "speedup_range_lower": speedup_range.get("lower"),
        "speedup_range_upper": speedup_range.get("upper"),
        "energy_range_lower_j": energy_range.get("lower"),
        "energy_range_upper_j": energy_range.get("upper"),
        "projection_confidence": projection["confidence"],
        "assumption_set_id": projection["assumption_set_id"],
        "ranking_grade_ready": projection["ranking_grade_ready"],
        "projection_grade_ready": projection["projection_grade_ready"],
        "model_run_id": artifacts["model_run_id"],
        "stdout_path": artifacts["stdout_path"],
        "metrics_path": artifacts["metrics_path"],
        "compare_report_path": artifacts["compare_report_path"],
        "raw_trace_paths": "" if raw_trace_paths is None else ";".join(raw_trace_paths),
        "stub_reason": row["stub_reason"],
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, bundle: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in bundle["results"]:
            writer.writerow(flatten_result(bundle, row))


def build_stage_a_coverage_manifest(
    bundle: dict[str, object],
    bundle_json_path: Path,
) -> dict[str, object]:
    results = list(bundle["results"])
    experiment = bundle.get("experiment", {})
    status_counts = Counter(str(row["result_status"]) for row in results)
    missing_metric_counts: Counter[str] = Counter()
    for row in results:
        missing_metric_counts.update(missing_ranking_metric_names(row))

    workloads = sorted({str(row["workload"]["workload_id"]) for row in results})
    candidate_families = sorted({str(row.get("candidate_family") or row["design_point"]["family"]) for row in results})
    runtime_families = sorted({str(row.get("runtime_projection_family") or row["design_point"]["family"]) for row in results})
    design_point_runtime_families = sorted({str(row["design_point"]["family"]) for row in results})
    evaluator_backend_counts = Counter(str(row.get("evaluator_backend") or "unknown") for row in results)
    fidelity_class_counts = Counter(str(row.get("fidelity_class") or "unknown") for row in results)
    support_status_counts = Counter(str(row.get("support_status") or "unknown") for row in results)
    template_ids = sorted(
        {str(row.get("architecture_template_id")) for row in results if row.get("architecture_template_id")}
    )

    template_coverage = []
    for template_id in template_ids:
        template_rows = [row for row in results if row.get("architecture_template_id") == template_id]
        template_coverage.append(
            {
                "architecture_template_id": template_id,
                "template_family": sorted({str(row.get("template_family")) for row in template_rows}),
                "candidate_family": sorted(
                    {str(row.get("candidate_family") or row.get("template_family")) for row in template_rows}
                ),
                "runtime_projection_family": sorted(
                    {str(row.get("runtime_projection_family") or row["design_point"]["family"]) for row in template_rows}
                ),
                "evaluator_backend_counts": dict(
                    sorted(Counter(str(row.get("evaluator_backend") or "unknown") for row in template_rows).items())
                ),
                "fidelity_class_counts": dict(
                    sorted(Counter(str(row.get("fidelity_class") or "unknown") for row in template_rows).items())
                ),
                "support_status_counts": dict(
                    sorted(Counter(str(row.get("support_status") or "unknown") for row in template_rows).items())
                ),
                "projection_only": any(row_is_projection_only(row) for row in template_rows),
                "row_count": len(template_rows),
                "projected_config_rows": sum(1 for row in template_rows if row.get("projected_config_path")),
                "ranking_grade_ready_rows": sum(
                    1 for row in template_rows if row["projection"]["ranking_grade_ready"]
                ),
                "projection_grade_ready_rows": sum(
                    1 for row in template_rows if row["projection"]["projection_grade_ready"]
                ),
                "metrics_complete_rows": sum(
                    1 for row in template_rows if not missing_ranking_metric_names(row)
                ),
            }
        )

    family_coverage = []
    for family in runtime_families:
        family_rows = [
            row
            for row in results
            if str(row.get("runtime_projection_family") or row["design_point"]["family"]) == family
        ]
        family_coverage.append(
            {
                "runtime_family": family,
                "row_count": len(family_rows),
                "workload_count": len({str(row["workload"]["workload_id"]) for row in family_rows}),
                "ranking_grade_ready_rows": sum(
                    1 for row in family_rows if row["projection"]["ranking_grade_ready"]
                ),
                "projection_grade_ready_rows": sum(
                    1 for row in family_rows if row["projection"]["projection_grade_ready"]
                ),
                "metrics_complete_rows": sum(
                    1 for row in family_rows if not missing_ranking_metric_names(row)
                ),
            }
        )

    candidate_family_coverage = []
    for family in candidate_families:
        family_rows = [
            row for row in results if str(row.get("candidate_family") or row["design_point"]["family"]) == family
        ]
        candidate_family_coverage.append(
            {
                "candidate_family": family,
                "row_count": len(family_rows),
                "workload_count": len({str(row["workload"]["workload_id"]) for row in family_rows}),
                "runtime_projection_families": sorted(
                    {str(row.get("runtime_projection_family") or row["design_point"]["family"]) for row in family_rows}
                ),
                "architecture_template_ids": sorted(
                    {str(row.get("architecture_template_id")) for row in family_rows if row.get("architecture_template_id")}
                ),
                "candidate_ids": sorted(
                    {str(row.get("candidate_id")) for row in family_rows if row.get("candidate_id")}
                ),
                "projection_only_rows": sum(1 for row in family_rows if row_is_projection_only(row)),
                "support_status_counts": dict(
                    sorted(Counter(str(row.get("support_status") or "unknown") for row in family_rows).items())
                ),
                "evaluator_backend_counts": dict(
                    sorted(Counter(str(row.get("evaluator_backend") or "unknown") for row in family_rows).items())
                ),
                "fidelity_class_counts": dict(
                    sorted(Counter(str(row.get("fidelity_class") or "unknown") for row in family_rows).items())
                ),
            }
        )

    projection_failures = Counter()
    case_pack_summary = None
    if isinstance(experiment, dict) and isinstance(experiment.get("case_pack_summary"), dict):
        case_pack_summary = experiment["case_pack_summary"]
    for row in results:
        projection_failures.update(projection_readiness_failures(row, case_pack_summary))

    return {
        "artifact_kind": "stage_a_dse_coverage_manifest_v0",
        "generated_at_utc": bundle["generated_at_utc"],
        "run_id": experiment.get("run_id") if isinstance(experiment, dict) else None,
        "bundle_json_path": str(bundle_json_path),
        "authority_scope": "stage_a_evidence_only",
        "claim_boundary": "Coverage and readiness accounting only; not a final architecture decision or performance claim.",
        "execution": {
            "template_driven": bool(experiment.get("template_driven")) if isinstance(experiment, dict) else False,
            "execute_model": any(str(row["result_status"]) in {"executed", "compared"} for row in results),
            "source_kind": experiment.get("source_kind") if isinstance(experiment, dict) else None,
            "case_pack_summary": experiment.get("case_pack_summary") if isinstance(experiment, dict) else None,
        },
        "coverage": {
            "result_count": len(results),
            "workload_count": len(workloads),
            "workloads": workloads,
            "candidate_families": candidate_families,
            "runtime_families": runtime_families,
            "design_point_runtime_families": design_point_runtime_families,
            "architecture_template_count": len(template_ids),
            "architecture_template_ids": template_ids,
            "result_status_counts": dict(sorted(status_counts.items())),
            "evaluator_backend_counts": dict(sorted(evaluator_backend_counts.items())),
            "fidelity_class_counts": dict(sorted(fidelity_class_counts.items())),
            "support_status_counts": dict(sorted(support_status_counts.items())),
        },
        "readiness_counts": {
            "ranking_grade_ready": sum(1 for row in results if row["projection"]["ranking_grade_ready"]),
            "projection_grade_ready": sum(1 for row in results if row["projection"]["projection_grade_ready"]),
            "metrics_complete": sum(1 for row in results if not missing_ranking_metric_names(row)),
            "projection_only_rows": sum(1 for row in results if row_is_projection_only(row)),
        },
        "missing_metric_counts": dict(sorted(missing_metric_counts.items())),
        "projection_readiness_failure_counts": dict(sorted(projection_failures.items())),
        "family_coverage": family_coverage,
        "candidate_family_coverage": candidate_family_coverage,
        "template_coverage": template_coverage,
        "next_result_gate": {
            "ranking_grade_ready_requires_execute_model": True,
            "projection_grade_ready_requires_case_pack": True,
            "final_claim_requires_adjudicator": True,
        },
    }


def write_stage_a_coverage_manifest(
    output_dir: Path,
    bundle: dict[str, object],
    bundle_json_path: Path,
    manifest_name: str,
) -> Path:
    manifest = build_stage_a_coverage_manifest(bundle, bundle_json_path)
    path = output_dir / manifest_name
    write_json(path, manifest)
    return path


def write_gold_gate_summary(output_dir: Path, bundle: dict[str, object]) -> tuple[Path, Path] | None:
    gold_rows = [row for row in bundle["results"] if row["workload"]["gold_required"]]
    if not gold_rows:
        return None
    summary = build_gold_gate_summary(bundle)
    json_path = output_dir / DEFAULT_GOLD_SUMMARY_JSON_NAME
    md_path = output_dir / DEFAULT_GOLD_SUMMARY_MD_NAME
    write_json(json_path, summary)
    md_path.write_text(render_gold_gate_summary_markdown(summary), encoding="utf-8")
    return json_path, md_path


def write_graph_evidence_sidecars(output_dir: Path, bundle: dict[str, object]) -> None:
    graph_dir = output_dir / "graph_evidence"
    graph_dir.mkdir(parents=True, exist_ok=True)
    for row in bundle["results"]:
        graph_evidence = row.get("graph_evidence")
        if not isinstance(graph_evidence, dict):
            continue
        sidecar = {
            "result_id": row["result_id"],
            "workload_id": row["workload"]["workload_id"],
            "design_point": row["design_point"],
            "comparison_contract": {
                "workload_group_id": row["comparison_contract"]["workload_group_id"],
                "fairness_policy_id": row["comparison_contract"]["fairness_policy_id"],
                "observability_contract_id": row["comparison_contract"]["observability_contract_id"],
            },
            "graph_evidence": graph_evidence,
        }
        path = graph_dir / f"{row['result_id']}.graph.json"
        path.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8")
        row["artifacts"]["graph_evidence_path"] = str(path)


def load_adjudicator_runner() -> object:
    spec = importlib.util.spec_from_file_location(
        "qe_system_design_adjudicator",
        ADJUDICATOR_RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import adjudicator runner from {ADJUDICATOR_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_adjudicator_reference(output_dir: Path, bundle_json_path: Path) -> tuple[dict[str, object], Path] | None:
    try:
        adjudicator = load_adjudicator_runner()
        memo, memo_json_path, memo_md_path = adjudicator.write_decision_memo_artifacts(
            dse_bundle_path=bundle_json_path,
            output_dir=output_dir / "adjudicator",
        )
    except Exception as exc:
        reference = {
            "artifact_kind": "qe_system_design_adjudicator_reference_v0",
            "authority_scope": "adjudicator_only",
            "reference_status": "error",
            "bundle_json_path": str(bundle_json_path),
            "decision_memo_json": None,
            "decision_memo_md": None,
            "error": str(exc),
            "notes": [
                "The DSE bundle remains an evidence input only. Final decision authority is reserved for the adjudicator memo when present.",
            ],
        }
    else:
        reference = {
            "artifact_kind": "qe_system_design_adjudicator_reference_v0",
            "authority_scope": "adjudicator_only",
            "reference_status": "present",
            "bundle_json_path": str(bundle_json_path),
            "decision_memo_json": str(memo_json_path),
            "decision_memo_md": str(memo_md_path),
            "decision_stage": memo["memo_metadata"]["stage"],
            "public_family_decision_status": memo["decision"]["public_family_decision_status"],
            "recommended_family": memo["decision"]["recommended_family"],
            "release_posture": memo["decision"]["release_posture"],
            "notes": [
                "This reference is evidence-oriented only. The adjudicator memo remains the single top-level decision authority.",
            ],
        }
    reference_path = output_dir / "qe_system_design_adjudicator_reference.json"
    reference["reference_path"] = str(reference_path)
    write_json(reference_path, reference)
    return reference, reference_path


def main() -> int:
    args = parse_args()
    if args.list_workloads:
        for workload_id in DEFAULT_WORKLOADS:
            print(workload_id)
        return 0
    if args.execute_model and args.source_kind == "stub":
        args.source_kind = "timed_functional_proxy"

    case_pack_summary = None
    if args.case_pack is not None:
        case_pack = load_case_pack(args.case_pack)
        available_workloads = case_pack_workload_ids(case_pack)
        requested_workloads = list(args.workloads)
        missing = [workload_id for workload_id in requested_workloads if workload_id not in available_workloads]
        if missing:
            raise ValueError("case pack missing workloads: " + ", ".join(missing))
        workloads = workload_rows_from_case_pack(
            requested_workloads,
            case_pack,
            sections=args.case_pack_sections,
        )
        case_pack_summary = {
            "schema_version": case_pack.get("schema_version"),
            "case_pack_path": str(args.case_pack),
            "bundle_role": case_pack.get("bundle_role"),
            "seed_family": case_pack.get("seed_family"),
            "all_requested_workloads_present": True,
            "selected_sections": args.case_pack_sections,
        }
    else:
        workloads = validate_workloads(args.workloads)
    if args.gold_required_only:
        workloads = filter_gold_required_workloads(workloads)
        if not workloads:
            raise ValueError("No gold-required workloads remain after --gold-required-only")
    families = validate_axis_subset("families", args.families, list(FAMILY_PROFILES))
    diag_policies = validate_axis_subset("diag policies", args.diag_policies, DIAG_POLICIES)
    offload_scopes = validate_axis_subset("offload scopes", args.offload_scopes, OFFLOAD_SCOPES)
    resident_policies = validate_axis_subset(
        "resident policies", args.resident_policies, RESIDENT_POLICIES
    )
    partition_strategies = (
        None
        if args.partition_strategies is None
        else validate_axis_subset(
            "partition strategies", args.partition_strategies, PARTITION_STRATEGIES
        )
    )

    if args.execute_model:
        for required_path in (
            args.model_bin,
            args.compare_helper,
            args.normalize_gold_helper,
            args.fast_layer_proxy_assumptions_path,
        ):
            if not required_path.exists():
                raise FileNotFoundError(f"Required path not found: {required_path}")

    ts = utc_now()
    bundle = build_bundle(
        args,
        ts,
        workloads,
        families,
        diag_policies,
        offload_scopes,
        resident_policies,
        partition_strategies,
    )
    bundle["experiment"]["case_pack_summary"] = case_pack_summary
    refresh_projection_grade_readiness(bundle)
    refresh_family_summary(bundle)
    refresh_candidate_family_summary(bundle)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.execute_model:
        execute_bundle(bundle, args, args.output_dir / "artifacts")
        refresh_projection_grade_readiness(bundle)
        refresh_family_summary(bundle)
        refresh_candidate_family_summary(bundle)
    write_graph_evidence_sidecars(args.output_dir, bundle)
    json_path = args.output_dir / args.json_name
    csv_path = args.output_dir / args.csv_name
    write_json(json_path, bundle)
    write_csv(csv_path, bundle)
    adjudicator_reference = write_adjudicator_reference(args.output_dir, json_path)
    if adjudicator_reference is not None:
        reference_payload, reference_path = adjudicator_reference
        bundle["notes"] = list(bundle.get("notes", []))
        bundle["notes"].append(
            "Authority note: this DSE bundle is an evidence input only; final recommendation authority belongs to the adjudicator memo."
        )
        bundle["notes"].append(
            f"Adjudicator reference JSON: {reference_path}"
        )
        bundle["notes"] = list(dict.fromkeys(bundle["notes"]))
        write_json(json_path, bundle)
    gold_gate_summary_paths = write_gold_gate_summary(args.output_dir, bundle)
    gold_summary = summarize_gold_results(bundle)
    coverage_manifest_path = write_stage_a_coverage_manifest(
        args.output_dir,
        bundle,
        json_path,
        args.coverage_manifest_name,
    )
    bundle["notes"] = list(bundle.get("notes", []))
    bundle["notes"].append(f"Stage-A coverage manifest JSON: {coverage_manifest_path}")
    bundle["notes"] = list(dict.fromkeys(bundle["notes"]))
    write_json(json_path, bundle)

    print(f"[ok] wrote JSON bundle: {json_path}")
    print(f"[ok] wrote CSV rows:   {csv_path}")
    print(f"[ok] wrote Stage-A coverage manifest JSON: {coverage_manifest_path}")
    if adjudicator_reference is not None:
        _, reference_path = adjudicator_reference
        print(f"[ok] wrote adjudicator reference JSON: {reference_path}")
    if gold_gate_summary_paths is not None:
        gold_summary_json_path, gold_summary_md_path = gold_gate_summary_paths
        print(f"[ok] wrote gold summary JSON: {gold_summary_json_path}")
        print(f"[ok] wrote gold summary MD:   {gold_summary_md_path}")
    print(
        f"[summary] rows={len(bundle['results'])} families={len(families)} "
        f"workloads={len(workloads)} execute_model={'yes' if args.execute_model else 'no'}"
    )
    if gold_summary["gold_rows"] > 0:
        print(
            "[gold] rows={gold_rows} passed={gold_passed} mismatches={gold_mismatches} errors={gold_errors} pending={pending}".format(
                pending=gold_summary["status_counts"].get("pending", 0),
                **gold_summary,
            )
        )

    if args.fail_on_gold_mismatch and any(
        is_gold_gate_blocking_status(str(row["correctness"]["status"]))
        for row in bundle["results"]
        if row["workload"]["gold_required"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
