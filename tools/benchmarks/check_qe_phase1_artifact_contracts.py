#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
BASELINE_TEMPLATE_PATH = BENCHMARKS_DIR / "qe_cpu_gpu_baseline_manifest_template_v0.json"
REWRITE_TEMPLATE_PATH = BENCHMARKS_DIR / "qe_algorithm_rewrite_manifest_template_v0.json"
DEFAULT_BOARD_FILES = {
    "manifest": "board_manifest.json",
    "metrics": "board_metrics.json",
    "power": "board_power.json",
    "compare": "board_compare.json",
}
JOIN_KEY_FIELDS = [
    "workload_id",
    "workload_group_id",
    "architecture_family",
    "assumption_set_id",
    "diag_policy",
    "offload_scope",
    "resident_policy",
    "qe_tolerance_schema_id",
    "accounting_boundary_id",
    "fairness_policy_id",
    "power_boundary_id",
    "observability_contract_id",
    "algorithm_rewrite_manifest_id",
    "algorithm_contract_deviation",
]


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_runner_module() -> Any:
    module_path = TOOLS_BENCHMARKS_DIR / "run_systemc_architecture_family_dse_sweep.py"
    spec = importlib.util.spec_from_file_location("qe_phase1_dse_runner", module_path)
    if spec is None or spec.loader is None:
        raise ValidationError(f"cannot import runner module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def top_level_keys(payload: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(payload))
    require(not missing, f"{label} missing required keys: {', '.join(missing)}")


def validate_baseline_manifest_template(
    payload: dict[str, Any],
    runner: Any,
    path: Path | None = None,
) -> None:
    label = str(path) if path is not None else "baseline manifest template"
    top_level_keys(
        payload,
        {
            "schema_version",
            "baseline_class",
            "case_id",
            "gpu_mode",
            "workload_group_id",
            "fairness_policy_id",
            "algorithm_rewrite_manifest_id",
            "gpu_mode_attempts",
            "mode_attempt_exemption_note",
            "shared_rewrite_closed",
            "host_platform_comparable",
            "qe_tolerance_schema_id",
            "accounting_boundary_id",
            "power_boundary_id",
            "artifact_paths",
            "baseline_state",
        },
        label,
    )
    require(
        payload["schema_version"] == "qe_cpu_gpu_baseline_manifest_template_v0",
        f"{label} schema_version must stay frozen",
    )
    require(payload["baseline_class"] == "CPU+GPU", f"{label} baseline_class must be CPU+GPU")
    require(payload["gpu_mode"] in {"strict_fp64", "practical"}, f"{label} gpu_mode invalid")
    require(
        payload["workload_group_id"] == runner.PHASE1_WORKLOAD_GROUP_ID,
        f"{label} workload_group_id drifted",
    )
    require(
        payload["fairness_policy_id"] == runner.PHASE1_FAIRNESS_POLICY_ID,
        f"{label} fairness_policy_id drifted",
    )
    require(
        payload["algorithm_rewrite_manifest_id"] == runner.PHASE1_REWRITE_MANIFEST_ID,
        f"{label} algorithm_rewrite_manifest_id drifted",
    )
    require(
        isinstance(payload["gpu_mode_attempts"], list)
        and payload["gpu_mode_attempts"]
        and all(mode in {"strict_fp64", "practical"} for mode in payload["gpu_mode_attempts"]),
        f"{label} gpu_mode_attempts invalid",
    )
    require(
        isinstance(payload["mode_attempt_exemption_note"], str),
        f"{label} mode_attempt_exemption_note must be a string",
    )
    require(
        isinstance(payload["shared_rewrite_closed"], bool),
        f"{label} shared_rewrite_closed must be boolean",
    )
    require(
        isinstance(payload["host_platform_comparable"], bool),
        f"{label} host_platform_comparable must be boolean",
    )
    require(
        payload["qe_tolerance_schema_id"] == "qe_gold_numerical_tolerance_schema_v0",
        f"{label} qe_tolerance_schema_id drifted",
    )
    require(
        payload["accounting_boundary_id"] == "scf_shell_convergence_scope_v1",
        f"{label} accounting_boundary_id drifted",
    )
    require(
        payload["power_boundary_id"] == runner.PHASE1_POWER_BOUNDARY_ID,
        f"{label} power_boundary_id drifted",
    )
    require(
        payload["baseline_state"] in ALLOWED_BASELINE_STATES,
        f"{label} baseline_state invalid",
    )
    artifact_paths = payload["artifact_paths"]
    top_level_keys(
        artifact_paths,
        {"stdout", "stderr", "timing", "correctness", "convergence", "power", "summary"},
        f"{label} artifact_paths",
    )


ALLOWED_REWRITE_CLASSES = {"shared_semantic", "shared_engineering", "fpga_specific_arch"}
ALLOWED_TRI = {"yes", "no", "unclear"}
ALLOWED_BASELINE_ENABLEMENT = {"yes", "no", "deferred"}
ALLOWED_CONTRACT_IMPACT = {"none", "bounded", "requires-review", "incompatible"}
ALLOWED_REVIEW_STATUS = {"draft", "accepted", "conditionally-accepted", "rejected"}
ALLOWED_ADMISSION_RISK = {"none", "medium", "high"}
ALLOWED_BENEFIT_AXIS = {"time", "power", "size", "convergence-stability", "mixed"}
ALLOWED_SEMANTICS = {"yes", "no", "qualified"}
ALLOWED_BASELINE_STATES = {
    "pending",
    "running",
    "measured_not_yet_validated",
    "reference_only",
    "deferred",
    "thesis_eligible",
}


def validate_algorithm_rewrite_manifest_template(
    payload: dict[str, Any],
    runner: Any,
    path: Path | None = None,
) -> None:
    label = str(path) if path is not None else "algorithm rewrite manifest template"
    top_level_keys(payload, {"schema_version", "manifest_id", "fairness_policy_id", "workload_group_id", "entries"}, label)
    require(
        payload["schema_version"] == "qe_algorithm_rewrite_manifest_template_v0",
        f"{label} schema_version must stay frozen",
    )
    require(
        payload["manifest_id"] == runner.PHASE1_REWRITE_MANIFEST_ID,
        f"{label} manifest_id drifted",
    )
    require(
        payload["fairness_policy_id"] == runner.PHASE1_FAIRNESS_POLICY_ID,
        f"{label} fairness_policy_id drifted",
    )
    require(
        payload["workload_group_id"] == runner.PHASE1_WORKLOAD_GROUP_ID,
        f"{label} workload_group_id drifted",
    )
    entries = payload["entries"]
    require(isinstance(entries, list) and entries, f"{label} entries must be a non-empty list")
    for index, entry in enumerate(entries):
        entry_label = f"{label} entries[{index}]"
        top_level_keys(
            entry,
            {
                "rewrite_id",
                "title",
                "rewrite_class",
                "scope",
                "description",
                "motivation",
                "changes_algorithm_semantics",
                "correctness_contract_impact",
                "tolerance_contract_note",
                "gpu_applicable",
                "gpu_applicability_basis",
                "gpu_enabled_in_baseline",
                "gpu_enablement_note",
                "fpga_required_arch_feature",
                "expected_benefit_axis",
                "expected_benefit_note",
                "ablation_required",
                "admission_risk",
                "evidence_note",
                "review_status",
                "owner_note",
                "affected_workload_ids",
                "affected_family_ids",
                "simulator_hook_ids",
                "board_observability_rows",
                "fallback_behavior",
                "shared_rewrite_dependency_ids",
                "claim_dependency_ids",
            },
            entry_label,
        )
        require(entry["rewrite_class"] in ALLOWED_REWRITE_CLASSES, f"{entry_label} rewrite_class invalid")
        require(entry["changes_algorithm_semantics"] in ALLOWED_SEMANTICS, f"{entry_label} changes_algorithm_semantics invalid")
        require(entry["correctness_contract_impact"] in ALLOWED_CONTRACT_IMPACT, f"{entry_label} correctness_contract_impact invalid")
        require(entry["gpu_applicable"] in ALLOWED_TRI, f"{entry_label} gpu_applicable invalid")
        require(entry["gpu_enabled_in_baseline"] in ALLOWED_BASELINE_ENABLEMENT, f"{entry_label} gpu_enabled_in_baseline invalid")
        require(entry["expected_benefit_axis"] in ALLOWED_BENEFIT_AXIS, f"{entry_label} expected_benefit_axis invalid")
        require(entry["ablation_required"] in {"yes", "no"}, f"{entry_label} ablation_required invalid")
        require(entry["admission_risk"] in ALLOWED_ADMISSION_RISK, f"{entry_label} admission_risk invalid")
        require(entry["review_status"] in ALLOWED_REVIEW_STATUS, f"{entry_label} review_status invalid")
        require(
            set(entry["affected_family_ids"]).issubset(set(runner.FAMILY_PROFILES)),
            f"{entry_label} affected_family_ids contain unknown family",
        )
        require(
            all(obs.startswith("OBS-") for obs in entry["board_observability_rows"]),
            f"{entry_label} board_observability_rows must use OBS-* ids",
        )
        require(
            all(claim.startswith("CL") for claim in entry["claim_dependency_ids"]),
            f"{entry_label} claim_dependency_ids must use CL* ids",
        )
        if entry["rewrite_class"] == "fpga_specific_arch":
            require(
                entry["gpu_applicable"] != "yes",
                f"{entry_label} fpga_specific_arch cannot claim gpu_applicable=yes",
            )


BOARD_SCHEMA_IDS = {
    "manifest": {"qe_fpga_board_manifest_template_v0", "qe_fpga_board_manifest_v0"},
    "metrics": {"qe_fpga_board_metrics_template_v0", "qe_fpga_board_metrics_v0"},
    "power": {"qe_fpga_board_power_template_v0", "qe_fpga_board_power_v0"},
    "compare": {"qe_fpga_board_compare_template_v0", "qe_fpga_board_compare_v0"},
}


def manifest_join_key(manifest: dict[str, Any]) -> dict[str, Any]:
    join_key = {}
    for field in JOIN_KEY_FIELDS:
        if field in manifest:
            join_key[field] = manifest[field]
    return join_key


def expected_join_key_for_kind(manifest: dict[str, Any], kind: str) -> dict[str, Any]:
    base_fields = [
        "workload_id",
        "workload_group_id",
        "architecture_family",
        "assumption_set_id",
        "diag_policy",
        "offload_scope",
        "resident_policy",
        "accounting_boundary_id",
        "fairness_policy_id",
        "power_boundary_id",
        "observability_contract_id",
        "algorithm_rewrite_manifest_id",
        "algorithm_contract_deviation",
        "request_id",
    ]
    if kind in {"metrics", "compare"}:
        base_fields.append("qe_tolerance_schema_id")
    if kind == "metrics":
        base_fields.extend(["scf_iteration", "episode_id"])
    return {field: manifest[field] for field in base_fields}


def validate_board_artifact_bundle(bundle_dir: Path, runner: Any) -> None:
    payloads = {kind: load_json(bundle_dir / name) for kind, name in DEFAULT_BOARD_FILES.items()}

    manifest = payloads["manifest"]
    top_level_keys(
        manifest,
        {
            "schema_version",
            "artifact_kind",
            "board_manifest_id",
            "board_run_id",
            "generated_at_utc",
            "workload_id",
            "workload_group_id",
            "architecture_family",
            "assumption_set_id",
            "diag_policy",
            "offload_scope",
            "resident_policy",
            "qe_tolerance_schema_id",
            "accounting_boundary_id",
            "fairness_policy_id",
            "power_boundary_id",
            "observability_contract_id",
            "algorithm_rewrite_manifest_id",
            "algorithm_contract_deviation",
            "request_id",
            "scf_iteration",
            "episode_id",
            "board_system",
            "ref_cycle_contract",
            "measurement_boundary",
            "artifact_paths",
        },
        "board_manifest",
    )
    require(
        manifest["schema_version"] in BOARD_SCHEMA_IDS["manifest"],
        "board_manifest schema_version invalid",
    )
    require(manifest["artifact_kind"] == "board_manifest", "board_manifest artifact_kind invalid")
    top_level_keys(
        manifest["board_system"],
        {"host_id", "fpga_board_id", "fpga_image_id", "driver_rev", "runtime_rev", "qe_rev"},
        "board_manifest board_system",
    )
    top_level_keys(
        manifest["ref_cycle_contract"],
        {"ref_clock_hz", "ref_cycle_unit", "normalization_note"},
        "board_manifest ref_cycle_contract",
    )
    top_level_keys(
        manifest["measurement_boundary"],
        {"start_event", "stop_event", "boundary_note"},
        "board_manifest measurement_boundary",
    )
    top_level_keys(
        manifest["artifact_paths"],
        {
            "stdout_path",
            "metrics_path",
            "power_path",
            "compare_report_path",
            "command_log_path",
            "env_snapshot_path",
        },
        "board_manifest artifact_paths",
    )
    manifest_key = manifest_join_key(manifest)
    top_level_keys(manifest_key, set(JOIN_KEY_FIELDS), "board_manifest join_key")
    require(
        manifest_key["workload_group_id"] == runner.PHASE1_WORKLOAD_GROUP_ID,
        "board_manifest workload_group_id drifted",
    )
    require(
        manifest_key["fairness_policy_id"] == runner.PHASE1_FAIRNESS_POLICY_ID,
        "board_manifest fairness_policy_id drifted",
    )
    require(
        manifest_key["power_boundary_id"] == runner.PHASE1_POWER_BOUNDARY_ID,
        "board_manifest power_boundary_id drifted",
    )
    require(
        manifest_key["observability_contract_id"] == runner.PHASE1_OBSERVABILITY_CONTRACT_ID,
        "board_manifest observability_contract_id drifted",
    )
    require(
        manifest_key["algorithm_rewrite_manifest_id"] == runner.PHASE1_REWRITE_MANIFEST_ID,
        "board_manifest algorithm_rewrite_manifest_id drifted",
    )

    metrics = payloads["metrics"]
    top_level_keys(
        metrics,
        {
            "schema_version",
            "artifact_kind",
            "board_run_id",
            "join_key",
            "obs_rows_present",
            "timing",
            "data_movement",
            "cycles",
            "policy_counters",
            "counter_sources",
            "raw_trace_paths",
        },
        "board_metrics",
    )
    require(metrics["schema_version"] in BOARD_SCHEMA_IDS["metrics"], "board_metrics schema_version invalid")
    require(metrics["artifact_kind"] == "board_metrics", "board_metrics artifact_kind invalid")
    top_level_keys(metrics["join_key"], set(expected_join_key_for_kind(manifest, "metrics")), "board_metrics join_key")
    require(
        metrics["join_key"] == expected_join_key_for_kind(manifest, "metrics"),
        "board_metrics join_key must match board_manifest",
    )
    top_level_keys(
        metrics["timing"],
        {
            "wall_time_s",
            "scf_iterations_to_convergence",
            "iteration_wall_times_s",
            "qe_stdout_total_time_s",
            "electrons_total_time_s",
        },
        "board_metrics timing",
    )
    top_level_keys(
        metrics["data_movement"],
        {"total_data_movement_kib", "dma_read_kib", "dma_write_kib", "dma_ledger_closure_abs_kib"},
        "board_metrics data_movement",
    )
    top_level_keys(
        metrics["cycles"],
        {
            "device_busy_ref_cycles",
            "dma_ref_cycles",
            "host_assist_ref_cycles",
            "accounted_ref_cycles",
            "accounted_backpressure_ref_cycles",
            "backpressure_ratio",
        },
        "board_metrics cycles",
    )
    top_level_keys(
        metrics["policy_counters"],
        {
            "cpu_fallbacks",
            "fallback_ratio",
            "resident_reuse_hits",
            "resident_reuse_ratio",
            "spill_events",
            "spill_ratio",
        },
        "board_metrics policy_counters",
    )
    top_level_keys(
        metrics["counter_sources"],
        {
            "dma_bytes_source",
            "device_busy_source",
            "host_assist_source",
            "fallback_source",
            "resident_source",
            "spill_source",
            "timeline_source",
        },
        "board_metrics counter_sources",
    )

    power = payloads["power"]
    top_level_keys(
        power,
        {
            "schema_version",
            "artifact_kind",
            "board_run_id",
            "join_key",
            "obs_rows_present",
            "power_window",
            "total_energy",
            "energy_ledger",
            "measurement_sources",
            "confidence",
        },
        "board_power",
    )
    require(power["schema_version"] in BOARD_SCHEMA_IDS["power"], "board_power schema_version invalid")
    require(power["artifact_kind"] == "board_power", "board_power artifact_kind invalid")
    top_level_keys(power["join_key"], set(expected_join_key_for_kind(manifest, "power")), "board_power join_key")
    require(
        power["join_key"] == expected_join_key_for_kind(manifest, "power"),
        "board_power join_key must match board_manifest",
    )
    top_level_keys(
        power["power_window"],
        {"start_event", "stop_event", "warmup_policy", "sampling_period_ms"},
        "board_power power_window",
    )
    top_level_keys(
        power["total_energy"],
        {"energy_to_convergence_j", "avg_power_w", "peak_power_w"},
        "board_power total_energy",
    )
    top_level_keys(
        power["energy_ledger"],
        {
            "E_host_j",
            "E_device_runtime_j",
            "E_dma_j",
            "E_hardware_datapath_j",
            "E_idle_static_j",
            "ledger_total_j",
            "ledger_closure_rel_err",
        },
        "board_power energy_ledger",
    )
    top_level_keys(
        power["measurement_sources"],
        {"host_energy_source", "fpga_board_energy_source", "idle_static_accounting_note", "rail_split_note"},
        "board_power measurement_sources",
    )
    top_level_keys(
        power["confidence"],
        {"power_claim_ready", "confidence_grade", "downgrade_reasons"},
        "board_power confidence",
    )
    require(
        power["join_key"]["power_boundary_id"] == runner.PHASE1_POWER_BOUNDARY_ID,
        "board_power power_boundary_id drifted",
    )

    compare = payloads["compare"]
    top_level_keys(
        compare,
        {
            "schema_version",
            "artifact_kind",
            "board_run_id",
            "join_key",
            "obs_rows_present",
            "correctness",
            "projection_cross_check",
            "claim_dependency_ids",
            "compare_inputs",
        },
        "board_compare",
    )
    require(compare["schema_version"] in BOARD_SCHEMA_IDS["compare"], "board_compare schema_version invalid")
    require(compare["artifact_kind"] == "board_compare", "board_compare artifact_kind invalid")
    top_level_keys(compare["join_key"], set(expected_join_key_for_kind(manifest, "compare")), "board_compare join_key")
    require(
        compare["join_key"] == expected_join_key_for_kind(manifest, "compare"),
        "board_compare join_key must match board_manifest",
    )
    top_level_keys(
        compare["correctness"],
        {
            "status",
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
            "notes",
        },
        "board_compare correctness",
    )
    top_level_keys(
        compare["projection_cross_check"],
        {
            "speedup_to_convergence_range",
            "energy_to_convergence_range_j",
            "realized_speedup_to_convergence",
            "realized_energy_to_convergence_j",
            "projection_confidence",
            "ranking_grade_ready",
            "projection_grade_ready",
            "range_margin_rel",
            "projection_consistency_status",
        },
        "board_compare projection_cross_check",
    )
    top_level_keys(
        compare["compare_inputs"],
        {"gold_baseline_path", "candidate_report_path", "simulator_projection_source"},
        "board_compare compare_inputs",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate phase-1 QE artifact contracts.")
    parser.add_argument(
        "--baseline-template",
        type=Path,
        default=BASELINE_TEMPLATE_PATH,
        help="Path to qe_cpu_gpu_baseline_manifest_template_v0.json",
    )
    parser.add_argument(
        "--rewrite-template",
        type=Path,
        default=REWRITE_TEMPLATE_PATH,
        help="Path to qe_algorithm_rewrite_manifest_template_v0.json",
    )
    parser.add_argument(
        "--board-dir",
        type=Path,
        help="Optional directory containing board_manifest.json, board_metrics.json, board_power.json, and board_compare.json",
    )
    parser.add_argument(
        "--require-board-bundle",
        action="store_true",
        help="Fail when --board-dir is absent or the board bundle is incomplete.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    runner = load_runner_module()
    validate_baseline_manifest_template(load_json(args.baseline_template), runner, args.baseline_template)
    print(f"[PASS] baseline template contract: {args.baseline_template}")
    validate_algorithm_rewrite_manifest_template(load_json(args.rewrite_template), runner, args.rewrite_template)
    print(f"[PASS] algorithm rewrite template contract: {args.rewrite_template}")

    if args.board_dir is not None:
        missing = [name for name in DEFAULT_BOARD_FILES.values() if not (args.board_dir / name).exists()]
        require(not missing, f"board bundle missing files: {', '.join(missing)}")
        validate_board_artifact_bundle(args.board_dir, runner)
        print(f"[PASS] board artifact contract bundle: {args.board_dir}")
    elif args.require_board_bundle:
        raise ValidationError("--require-board-bundle was set but --board-dir was not provided")
    else:
        print("[SKIP] board artifact contract bundle: no --board-dir provided")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
