#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
BASELINE_TEMPLATE_PATH = BENCHMARKS_DIR / "qe_cpu_gpu_baseline_manifest_template_v0.json"
REWRITE_TEMPLATE_PATH = BENCHMARKS_DIR / "qe_algorithm_rewrite_manifest_template_v0.json"
BOARD_TEMPLATE_PATHS = {
    "manifest": BENCHMARKS_DIR / "qe_fpga_board_manifest_template_v0.json",
    "metrics": BENCHMARKS_DIR / "qe_fpga_board_metrics_template_v0.json",
    "power": BENCHMARKS_DIR / "qe_fpga_board_power_template_v0.json",
    "compare": BENCHMARKS_DIR / "qe_fpga_board_compare_template_v0.json",
}
BOARD_OUTPUT_FILES = {
    "manifest": "board_manifest.json",
    "metrics": "board_metrics.json",
    "power": "board_power.json",
    "compare": "board_compare.json",
}
BASELINE_OUTPUT_FILE = "cpu_gpu_baseline_manifest.json"
REWRITE_OUTPUT_FILE = "algorithm_rewrite_manifest.json"
QE_TOLERANCE_SCHEMA_ID = "qe_gold_numerical_tolerance_schema_v0"
ACCOUNTING_BOUNDARY_ID = "scf_shell_convergence_scope_v1"
WARMUP_POLICY = "symmetric_warmup_once"


class InitError(RuntimeError):
    pass


def first_attr(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def load_runner_module() -> Any:
    module_path = BENCHMARKS_DIR / "run_systemc_architecture_family_dse_sweep.py"
    spec = importlib.util.spec_from_file_location("qe_phase1_dse_runner", module_path)
    if spec is None or spec.loader is None:
        raise InitError(f"cannot import runner module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise InitError(f"refusing to overwrite existing file: {path}")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InitError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_family_profile(runner: Any, family: str) -> dict[str, Any]:
    require(family in runner.FAMILY_PROFILES, f"unknown architecture family: {family}")
    return runner.FAMILY_PROFILES[family]


def baseline_artifact_paths(workload_id: str, gpu_mode: str, run_tag: str) -> dict[str, str]:
    prefix = f"qe_{workload_id}__cpu_gpu__{gpu_mode}__{run_tag}"
    return {
        "stdout": f"{prefix}.stdout.txt",
        "stderr": f"{prefix}.stderr.txt",
        "timing": f"{prefix}.timing.json",
        "correctness": f"{prefix}.correctness.json",
        "convergence": f"{prefix}.convergence.json",
        "power": f"{prefix}.power.json",
        "summary": f"{prefix}.summary.md",
    }


def board_artifact_paths(workload_id: str, family: str, run_tag: str) -> dict[str, str]:
    prefix = f"qe_{workload_id}__cpu_fpga__{family}__{run_tag}"
    return {
        "stdout_path": f"{prefix}.stdout.txt",
        "metrics_path": BOARD_OUTPUT_FILES["metrics"],
        "power_path": BOARD_OUTPUT_FILES["power"],
        "compare_report_path": BOARD_OUTPUT_FILES["compare"],
        "command_log_path": f"{prefix}.command.log",
        "env_snapshot_path": f"{prefix}.env.json",
    }


def instantiate_rewrite_manifest(runner: Any, workload_group_id: str, fairness_policy_id: str) -> dict[str, Any]:
    payload = copy.deepcopy(load_json(REWRITE_TEMPLATE_PATH))
    payload["manifest_id"] = runner.PHASE1_REWRITE_MANIFEST_ID
    payload["workload_group_id"] = workload_group_id
    payload["fairness_policy_id"] = fairness_policy_id
    return payload


def instantiate_baseline_bundle(args: argparse.Namespace, runner: Any) -> dict[str, Any]:
    payload = copy.deepcopy(load_json(BASELINE_TEMPLATE_PATH))
    payload["case_id"] = args.workload_id
    payload["gpu_mode"] = args.gpu_mode
    payload["run_tag"] = args.run_tag
    payload["host_id"] = args.host_id
    payload["gpu_id"] = args.gpu_id
    payload["qe_rev"] = args.qe_rev
    payload["workload_group_id"] = args.workload_group_id
    payload["fairness_policy_id"] = args.fairness_policy_id
    payload["algorithm_rewrite_manifest_id"] = args.algorithm_rewrite_manifest_id
    payload["gpu_mode_attempts"] = [args.gpu_mode]
    payload["mode_attempt_exemption_note"] = ""
    payload["shared_rewrite_closed"] = False
    payload["host_platform_comparable"] = False
    payload["qe_tolerance_schema_id"] = args.qe_tolerance_schema_id
    payload["accounting_boundary_id"] = args.accounting_boundary_id
    payload["power_boundary_id"] = args.power_boundary_id
    payload["command"] = args.command
    payload["env"]["CUDA_VISIBLE_DEVICES"] = args.cuda_visible_devices
    payload["host_normalization_note"] = args.host_normalization_note
    payload["rewrite_mode"] = args.rewrite_mode
    payload["artifact_paths"] = baseline_artifact_paths(args.workload_id, args.gpu_mode, args.run_tag)
    rewrite_manifest = instantiate_rewrite_manifest(runner, args.workload_group_id, args.fairness_policy_id)
    rewrite_manifest["manifest_id"] = args.algorithm_rewrite_manifest_id
    return {
        BASELINE_OUTPUT_FILE: payload,
        REWRITE_OUTPUT_FILE: rewrite_manifest,
    }


def board_join_key(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "workload_id": args.workload_id,
        "workload_group_id": args.workload_group_id,
        "architecture_family": args.architecture_family,
        "assumption_set_id": args.assumption_set_id,
        "diag_policy": args.diag_policy,
        "offload_scope": args.offload_scope,
        "resident_policy": args.resident_policy,
        "qe_tolerance_schema_id": args.qe_tolerance_schema_id,
        "accounting_boundary_id": args.accounting_boundary_id,
        "fairness_policy_id": args.fairness_policy_id,
        "power_boundary_id": args.power_boundary_id,
        "observability_contract_id": args.observability_contract_id,
        "algorithm_rewrite_manifest_id": args.algorithm_rewrite_manifest_id,
        "algorithm_contract_deviation": args.algorithm_contract_deviation,
        "request_id": args.request_id,
        "scf_iteration": args.scf_iteration,
        "episode_id": args.episode_id,
    }


def instantiate_board_bundle(args: argparse.Namespace, runner: Any) -> dict[str, Any]:
    manifest = copy.deepcopy(load_json(BOARD_TEMPLATE_PATHS["manifest"]))
    metrics = copy.deepcopy(load_json(BOARD_TEMPLATE_PATHS["metrics"]))
    power = copy.deepcopy(load_json(BOARD_TEMPLATE_PATHS["power"]))
    compare = copy.deepcopy(load_json(BOARD_TEMPLATE_PATHS["compare"]))

    join_key = board_join_key(args)
    manifest.update(join_key)
    manifest["board_run_id"] = args.board_run_id
    manifest["generated_at_utc"] = args.generated_at_utc
    manifest["claim_ids_supported"] = args.claim_ids_supported
    manifest["board_system"].update(
        {
            "host_id": args.host_id,
            "fpga_board_id": args.fpga_board_id,
            "fpga_image_id": args.fpga_image_id,
            "driver_rev": args.driver_rev,
            "runtime_rev": args.runtime_rev,
            "qe_rev": args.qe_rev,
        }
    )
    manifest["ref_cycle_contract"]["ref_clock_hz"] = args.ref_clock_hz
    manifest["ref_cycle_contract"]["normalization_note"] = args.ref_cycle_note
    manifest["measurement_boundary"].update(
        {
            "start_event": args.measurement_start_event,
            "stop_event": args.measurement_stop_event,
            "boundary_note": args.measurement_boundary_note,
        }
    )
    manifest["artifact_paths"] = board_artifact_paths(args.workload_id, args.architecture_family, args.run_tag)

    metrics["board_run_id"] = args.board_run_id
    metrics["join_key"] = join_key
    power["board_run_id"] = args.board_run_id
    compare["board_run_id"] = args.board_run_id

    power_join_key = {
        key: value
        for key, value in join_key.items()
        if key not in {"qe_tolerance_schema_id", "scf_iteration", "episode_id"}
    }
    compare_join_key = {
        key: value
        for key, value in join_key.items()
        if key not in {"scf_iteration", "episode_id"}
    }
    power["join_key"] = power_join_key
    compare["join_key"] = compare_join_key
    power["power_window"].update(
        {
            "start_event": args.measurement_start_event,
            "stop_event": args.measurement_stop_event,
            "warmup_policy": args.warmup_policy,
        }
    )
    compare["compare_inputs"].update(
        {
            "gold_baseline_path": args.gold_baseline_path,
            "candidate_report_path": args.candidate_report_path,
            "simulator_projection_source": args.simulator_projection_source,
        }
    )
    rewrite_manifest = instantiate_rewrite_manifest(runner, args.workload_group_id, args.fairness_policy_id)
    rewrite_manifest["manifest_id"] = args.algorithm_rewrite_manifest_id

    return {
        BOARD_OUTPUT_FILES["manifest"]: manifest,
        BOARD_OUTPUT_FILES["metrics"]: metrics,
        BOARD_OUTPUT_FILES["power"]: power,
        BOARD_OUTPUT_FILES["compare"]: compare,
        REWRITE_OUTPUT_FILE: rewrite_manifest,
    }


def scaffold_cpu_gpu(args: Any) -> list[Path]:
    out_dir = Path(first_attr(args, "output_dir", "out_dir", default="."))
    out_dir.mkdir(parents=True, exist_ok=True)
    namespace = argparse.Namespace(
        workload_id=first_attr(args, "case_id", "workload_id"),
        gpu_mode=getattr(args, "gpu_mode", "strict_fp64"),
        run_tag=getattr(args, "run_tag", "YYYYMMDD-HHMMSS"),
        host_id=getattr(args, "host_id", "fill-me"),
        gpu_id=getattr(args, "gpu_id", "fill-me"),
        qe_rev=getattr(args, "qe_rev", "fill-me"),
        workload_group_id=getattr(args, "workload_group_id"),
        fairness_policy_id=getattr(args, "fairness_policy_id"),
        algorithm_rewrite_manifest_id=getattr(args, "algorithm_rewrite_manifest_id"),
        qe_tolerance_schema_id=getattr(args, "qe_tolerance_schema_id", QE_TOLERANCE_SCHEMA_ID),
        accounting_boundary_id=getattr(args, "accounting_boundary_id", ACCOUNTING_BOUNDARY_ID),
        power_boundary_id=getattr(args, "power_boundary_id"),
        command=getattr(args, "command", "fill-me"),
        cuda_visible_devices=getattr(args, "cuda_visible_devices", "fill-me"),
        host_normalization_note=getattr(args, "host_normalization_note", "fill-me"),
        rewrite_mode=getattr(args, "rewrite_mode", "none"),
    )
    runner = load_runner_module()
    bundle = instantiate_baseline_bundle(namespace, runner)
    write_json(out_dir / BASELINE_OUTPUT_FILE, bundle[BASELINE_OUTPUT_FILE], overwrite=True)
    return [out_dir / BASELINE_OUTPUT_FILE]


def scaffold_fpga_board(args: Any) -> list[Path]:
    out_dir = Path(first_attr(args, "output_dir", "out_dir", default="."))
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = load_runner_module()
    family = first_attr(args, "family", "architecture_family")
    family_profile = load_family_profile(runner, family)
    namespace = argparse.Namespace(
        workload_id=first_attr(args, "case_id", "workload_id"),
        workload_group_id=getattr(args, "workload_group_id"),
        architecture_family=family,
        assumption_set_id=getattr(args, "assumption_set_id", "fill-me"),
        diag_policy=getattr(args, "diag_policy", family_profile["canonical_diag_policy"]),
        offload_scope=getattr(args, "offload_scope", family_profile["canonical_offload_scope"]),
        resident_policy=getattr(args, "resident_policy", family_profile["canonical_resident_policy"]),
        qe_tolerance_schema_id=getattr(args, "qe_tolerance_schema_id", QE_TOLERANCE_SCHEMA_ID),
        accounting_boundary_id=getattr(args, "accounting_boundary_id", ACCOUNTING_BOUNDARY_ID),
        fairness_policy_id=getattr(args, "fairness_policy_id"),
        power_boundary_id=getattr(args, "power_boundary_id"),
        observability_contract_id=getattr(args, "observability_contract_id"),
        algorithm_rewrite_manifest_id=getattr(args, "algorithm_rewrite_manifest_id"),
        algorithm_contract_deviation=(getattr(args, "algorithm_contract_deviation", "none") not in {False, "none", None}),
        request_id=getattr(args, "request_id", "fill-me"),
        scf_iteration=getattr(args, "scf_iteration", None),
        episode_id=getattr(args, "episode_id", None),
        board_run_id=getattr(args, "board_run_id", "fill-me"),
        generated_at_utc=getattr(args, "generated_at_utc", utc_now()),
        claim_ids_supported=getattr(args, "claim_ids_supported", ["CL1", "CL2", "CL3", "CL4", "CL5", "CL6"]),
        host_id=getattr(args, "host_id", "fill-me"),
        fpga_board_id=first_attr(args, "fpga_board_id", "board_id", default="fill-me"),
        fpga_image_id=getattr(args, "fpga_image_id", "fill-me"),
        driver_rev=getattr(args, "driver_rev", "fill-me"),
        runtime_rev=getattr(args, "runtime_rev", "fill-me"),
        qe_rev=getattr(args, "qe_rev", "fill-me"),
        ref_clock_hz=getattr(args, "ref_clock_hz", 250000000),
        ref_cycle_note=getattr(args, "ref_cycle_note", "Fill in how board counters are normalized to the simulator ref-cycle domain."),
        measurement_start_event=getattr(args, "measurement_start_event", "qe_wrapper_launch"),
        measurement_stop_event=getattr(args, "measurement_stop_event", "qe_wrapper_exit"),
        measurement_boundary_note=getattr(args, "measurement_boundary_note", "Must match OBS-01 and whole-node power accounting for the same QE shell run."),
        run_tag=getattr(args, "run_tag", "YYYYMMDD-HHMMSS"),
        warmup_policy=getattr(args, "warmup_policy", WARMUP_POLICY),
        gold_baseline_path=getattr(args, "gold_baseline_path", "fill-me"),
        candidate_report_path=getattr(args, "candidate_report_path", "fill-me"),
        simulator_projection_source=getattr(args, "simulator_projection_source", "fill-me"),
    )
    bundle = instantiate_board_bundle(namespace, runner)
    for name, payload in bundle.items():
        if name == REWRITE_OUTPUT_FILE:
            continue
        write_json(out_dir / name, payload, overwrite=True)
    return [out_dir / BOARD_OUTPUT_FILES["manifest"], out_dir / BOARD_OUTPUT_FILES["metrics"], out_dir / BOARD_OUTPUT_FILES["power"], out_dir / BOARD_OUTPUT_FILES["compare"]]


def add_common_contract_args(parser: argparse.ArgumentParser, runner: Any) -> None:
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory where initialized JSON files are written")
    parser.add_argument("--workload-id", required=True, help="QE workload/case id")
    parser.add_argument("--workload-group-id", default=runner.PHASE1_WORKLOAD_GROUP_ID, help="Workload-group contract id")
    parser.add_argument("--fairness-policy-id", default=runner.PHASE1_FAIRNESS_POLICY_ID, help="Fairness/power contract id")
    parser.add_argument("--power-boundary-id", default=runner.PHASE1_POWER_BOUNDARY_ID, help="Power boundary id")
    parser.add_argument("--algorithm-rewrite-manifest-id", default=runner.PHASE1_REWRITE_MANIFEST_ID, help="Algorithm rewrite manifest id")
    parser.add_argument("--qe-tolerance-schema-id", default=QE_TOLERANCE_SCHEMA_ID, help="QE tolerance schema id")
    parser.add_argument("--accounting-boundary-id", default=ACCOUNTING_BOUNDARY_ID, help="Accounting boundary id")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing output files")


def parse_args(argv: list[str], runner: Any) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize phase-1 QE CPU+GPU baseline or CPU+FPGA board artifact bundles.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    baseline = subparsers.add_parser("baseline", help="Initialize a CPU+GPU baseline collection bundle")
    add_common_contract_args(baseline, runner)
    baseline.add_argument("--gpu-mode", choices=["strict_fp64", "practical"], default="strict_fp64")
    baseline.add_argument("--run-tag", default="YYYYMMDD-HHMMSS")
    baseline.add_argument("--host-id", default="fill-me")
    baseline.add_argument("--gpu-id", default="fill-me")
    baseline.add_argument("--qe-rev", default="fill-me")
    baseline.add_argument("--command", default="fill-me")
    baseline.add_argument("--cuda-visible-devices", default="fill-me")
    baseline.add_argument("--host-normalization-note", default="fill-me")
    baseline.add_argument("--rewrite-mode", default="none")

    board = subparsers.add_parser("board", help="Initialize a CPU+FPGA board artifact bundle")
    add_common_contract_args(board, runner)
    board.add_argument("--architecture-family", choices=sorted(runner.FAMILY_PROFILES), required=True)
    board.add_argument("--observability-contract-id", default=runner.PHASE1_OBSERVABILITY_CONTRACT_ID, help="Simulator↔board observability contract id")
    board.add_argument("--board-run-id", default="fill-me")
    board.add_argument("--run-tag", default="YYYYMMDD-HHMMSS")
    board.add_argument("--assumption-set-id", default="fill-me")
    board.add_argument("--request-id", default="fill-me")
    board.add_argument("--diag-policy", default=None)
    board.add_argument("--offload-scope", default=None)
    board.add_argument("--resident-policy", default=None)
    board.add_argument("--algorithm-contract-deviation", action="store_true")
    board.add_argument("--scf-iteration", type=int, default=None)
    board.add_argument("--episode-id", default=None)
    board.add_argument("--generated-at-utc", default=utc_now())
    board.add_argument("--claim-id", dest="claim_ids_supported", action="append")
    board.add_argument("--host-id", default="fill-me")
    board.add_argument("--fpga-board-id", default="fill-me")
    board.add_argument("--fpga-image-id", default="fill-me")
    board.add_argument("--driver-rev", default="fill-me")
    board.add_argument("--runtime-rev", default="fill-me")
    board.add_argument("--qe-rev", default="fill-me")
    board.add_argument("--ref-clock-hz", type=int, default=250000000)
    board.add_argument("--ref-cycle-note", default="Fill in how board counters are normalized to the simulator ref-cycle domain.")
    board.add_argument("--measurement-start-event", default="qe_wrapper_launch")
    board.add_argument("--measurement-stop-event", default="qe_wrapper_exit")
    board.add_argument("--measurement-boundary-note", default="Must match OBS-01 and whole-node power accounting for the same QE shell run.")
    board.add_argument("--warmup-policy", default=WARMUP_POLICY)
    board.add_argument("--gold-baseline-path", default="fill-me")
    board.add_argument("--candidate-report-path", default="fill-me")
    board.add_argument("--simulator-projection-source", default="fill-me")

    args = parser.parse_args(argv)
    if args.mode == "board":
        family_profile = load_family_profile(runner, args.architecture_family)
        if args.diag_policy is None:
            args.diag_policy = family_profile["canonical_diag_policy"]
        if args.offload_scope is None:
            args.offload_scope = family_profile["canonical_offload_scope"]
        if args.resident_policy is None:
            args.resident_policy = family_profile["canonical_resident_policy"]
        if args.claim_ids_supported is None:
            args.claim_ids_supported = ["CL1", "CL2", "CL3", "CL4", "CL5", "CL6"]
    return args


def ensure_output_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)


def emit_bundle(bundle: dict[str, Any], out_dir: Path, overwrite: bool) -> None:
    for relative_name, payload in bundle.items():
        write_json(out_dir / relative_name, payload, overwrite)


def main(argv: list[str] | None = None) -> int:
    runner = load_runner_module()
    args = parse_args(argv or sys.argv[1:], runner)
    ensure_output_dir(args.out_dir)
    if args.mode == "baseline":
        bundle = instantiate_baseline_bundle(args, runner)
    else:
        bundle = instantiate_board_bundle(args, runner)
    emit_bundle(bundle, args.out_dir, args.overwrite)
    print(f"[PASS] initialized {args.mode} artifact bundle: {args.out_dir}")
    for name in sorted(bundle):
        print(f"[WRITE] {args.out_dir / name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InitError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
