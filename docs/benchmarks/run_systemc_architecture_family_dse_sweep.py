#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json"
DEFAULT_OUTPUT_DIR = ROOT / "docs/benchmarks/results/systemc_architecture_family_dse_bootstrap"
DEFAULT_MODEL_BIN = ROOT / "model/qe_band_solver_model/build/qe_band_solver_model"
DEFAULT_COMPARE_HELPER = ROOT / "docs/benchmarks/compare_qe_gold_correctness.py"
DEFAULT_NORMALIZE_GOLD_HELPER = ROOT / "docs/benchmarks/normalize_qe_gold_baseline.py"
DEFAULT_GOLD_BASELINE_ROOT = ROOT / "docs/benchmarks/results/qe_workload_revalidation"
DEFAULT_GOLD_SUMMARY_JSON_NAME = "qe_gold_gate_summary_v0.json"
DEFAULT_GOLD_SUMMARY_MD_NAME = "qe_gold_gate_summary_v0.md"
RY_TO_EV = 13.605693009

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

DEFAULT_WORKLOADS = {
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
    "family",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "canonical_profile_match",
    "qe_baseline_id",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "algorithm_contract_deviation",
    "correctness_status",
    "gold_pass",
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
        "--canonical-only",
        action="store_true",
        help="Emit only canonical family-profile points instead of the full cross product.",
    )
    parser.add_argument(
        "--max-design-points",
        type=int,
        default=None,
        help="Optional cap applied after enumeration/filtering.",
    )
    parser.add_argument(
        "--assumption-set-id",
        default="pending_calibration_v0",
        help="Assumption set id attached to all projection placeholders.",
    )
    parser.add_argument(
        "--qe-tolerance-schema-id",
        default="pending_qe_numerical_tolerance_schema_v0",
        help="QE numerical tolerance schema id placeholder carried into each row.",
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
) -> bool:
    profile = FAMILY_PROFILES[family]
    return (
        diag_policy == profile["canonical_diag_policy"]
        and offload_scope == profile["canonical_offload_scope"]
        and resident_policy == profile["canonical_resident_policy"]
    )


def build_result_row(
    workload: dict[str, object],
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    result_id = "__".join(
        [
            str(workload["workload_id"]),
            family,
            diag_policy,
            offload_scope,
            resident_policy,
        ]
    )
    profile = FAMILY_PROFILES[family]
    return {
        "result_id": result_id,
        "result_status": "stub",
        "source_kind": args.source_kind,
        "workload": workload,
        "design_point": {
            "family": family,
            "diag_policy": diag_policy,
            "offload_scope": offload_scope,
            "resident_policy": resident_policy,
            "canonical_profile_match": canonical_profile_match(
                family, diag_policy, offload_scope, resident_policy
            ),
        },
        "comparison_contract": {
            "qe_baseline_id": "qe_cpu_only_gold_v0",
            "qe_tolerance_schema_id": args.qe_tolerance_schema_id,
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "algorithm_contract_deviation": False,
            "gold_required": workload["gold_required"],
        },
        "correctness": {
            "status": "pending",
            "gold_pass": None,
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
            "raw_trace_paths": None,
        },
        "stub_reason": (
            "Bootstrap placeholder for architecture-family sweep planning; "
            "fill metrics and correctness fields after SystemC model integration."
        ),
    }


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
                "result_count": result_count,
                "ranking_grade_status": "pending",
                "projection_grade_status": "pending",
                "confidence": "pending",
                "recommended_cpu_device_split": profile["recommended_cpu_device_split"],
                "recommended_operator_set": profile["recommended_operator_set"],
            }
        )
    return out


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
            "QEBS_ASSUMPTION_SET_ID": args.assumption_set_id,
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
    return env


def run_model_for_row(
    bundle: dict[str, object],
    row: dict[str, object],
    args: argparse.Namespace,
    artifacts_dir: Path,
    baseline_payload: dict[str, object] | None = None,
) -> tuple[bool, str]:
    workload = row["workload"]
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

    candidate = json.loads(candidate_json_path.read_text(encoding="utf-8"))
    final = candidate.get("final", {})
    metrics = candidate.get("metrics", {})
    timing = candidate.get("timing", {})
    run_summary = candidate.get("run_summary", {})
    last_iteration = candidate.get("last_iteration", {})

    row["result_status"] = "executed"
    row["stub_reason"] = ""
    row["primary_metrics"]["time_to_convergence_s"] = timing.get("wall_time_s")
    row["primary_metrics"]["scf_iterations_to_convergence"] = final.get("scf_iterations")
    total_data_movement_kib = metrics.get("total_data_movement_kib")
    row["primary_metrics"]["bytes_moved_to_convergence"] = (
        None if total_data_movement_kib is None else float(total_data_movement_kib) * 1024.0
    )
    row["primary_metrics"]["fallback_count_to_convergence"] = metrics.get("cpu_fallbacks")

    row["secondary_metrics"]["device_busy_ref_cycles"] = metrics.get("device_busy_ref_cycles")
    row["secondary_metrics"]["dma_ref_cycles"] = metrics.get("dma_ref_cycles")
    row["secondary_metrics"]["host_assist_ref_cycles"] = metrics.get("host_assist_ref_cycles")
    row["secondary_metrics"]["resident_reuse_hits"] = metrics.get("resident_reuse_hits")

    total_episodes = run_summary.get("total_episodes")
    cpu_fallbacks = metrics.get("cpu_fallbacks")
    if isinstance(total_episodes, int) and total_episodes > 0 and isinstance(cpu_fallbacks, int):
        row["secondary_metrics"]["fallback_ratio"] = cpu_fallbacks / total_episodes

    row["projection"]["confidence"] = last_iteration.get("confidence_label", "pending")
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
    return report["overall_pass"], "compared"


def build_bundle(
    args: argparse.Namespace,
    ts: datetime,
    workloads: list[dict[str, object]],
    families: list[str],
    diag_policies: list[str],
    offload_scopes: list[str],
    resident_policies: list[str],
) -> dict[str, object]:
    run_id = args.run_id or default_run_id(ts)
    results = [
        build_result_row(workload, family, diag_policy, offload_scope, resident_policy, args)
        for workload, family, diag_policy, offload_scope, resident_policy in product(
            workloads,
            families,
            diag_policies,
            offload_scopes,
            resident_policies,
        )
    ]
    if args.canonical_only:
        results = [row for row in results if row["design_point"]["canonical_profile_match"]]
    if args.max_design_points is not None:
        results = results[: args.max_design_points]
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
            "qe_tolerance_schema_id": args.qe_tolerance_schema_id,
            "source_kind": args.source_kind,
            "gate_contract": {
                **QE_GOLD_GATE_CONTRACT,
                "status_taxonomy": GOLD_STATUS_TAXONOMY,
            },
            "sweep_axes": {
                "family": families,
                "diag_policy": diag_policies,
                "offload_scope": offload_scopes,
                "resident_policy": resident_policies,
            },
            "workloads": workloads,
            "excluded_engineering_knobs": EXCLUDED_ENGINEERING_KNOBS,
        },
        "results": results,
        "family_summary": build_family_summary(results),
        "notes": [
            "v1 sweep excludes DMA width, buffer depth, and final BRAM/URAM/HBM budget tuning.",
            "Projection fields are intentionally null in bootstrap output until the SystemC model is wired in.",
            "QE tolerance schema id is carried as metadata so the correctness gate can be frozen before execution.",
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
    energy = row["energy_ledger"]
    projection = row["projection"]
    artifacts = row["artifacts"]
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
        "family": design["family"],
        "diag_policy": design["diag_policy"],
        "offload_scope": design["offload_scope"],
        "resident_policy": design["resident_policy"],
        "canonical_profile_match": design["canonical_profile_match"],
        "qe_baseline_id": contract["qe_baseline_id"],
        "qe_tolerance_schema_id": contract["qe_tolerance_schema_id"],
        "accounting_boundary_id": contract["accounting_boundary_id"],
        "algorithm_contract_deviation": contract["algorithm_contract_deviation"],
        "correctness_status": correctness["status"],
        "gold_pass": correctness["gold_pass"],
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


def main() -> int:
    args = parse_args()
    if args.list_workloads:
        for workload_id in DEFAULT_WORKLOADS:
            print(workload_id)
        return 0
    if args.execute_model and args.source_kind == "stub":
        args.source_kind = "timed_functional_proxy"

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

    if args.execute_model:
        for required_path in (args.model_bin, args.compare_helper, args.normalize_gold_helper):
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
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.execute_model:
        execute_bundle(bundle, args, args.output_dir / "artifacts")
    json_path = args.output_dir / args.json_name
    csv_path = args.output_dir / args.csv_name
    write_json(json_path, bundle)
    write_csv(csv_path, bundle)
    gold_gate_summary_paths = write_gold_gate_summary(args.output_dir, bundle)
    gold_summary = summarize_gold_results(bundle)

    print(f"[ok] wrote JSON bundle: {json_path}")
    print(f"[ok] wrote CSV rows:   {csv_path}")
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
            "[gold] rows={gold_rows} passed={gold_passed} mismatches={gold_mismatches} errors={gold_errors}".format(
                **gold_summary
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
