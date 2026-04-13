#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
SCHEMA_PATH = BENCHMARKS_DIR / "qe_gold_numerical_tolerance_schema_v0.json"
COMPARE_HELPER = BENCHMARKS_DIR / "compare_qe_gold_correctness.py"
NORMALIZE_HELPER = BENCHMARKS_DIR / "normalize_qe_gold_baseline.py"
SWEEP_RUNNER = BENCHMARKS_DIR / "run_systemc_architecture_family_dse_sweep.py"
QE_BASELINE_ROOT = BENCHMARKS_DIR / "results/qe_workload_revalidation"
FIRST_PRIORITY_CASE = "si8_pbe_nc"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"[PASS] {message}")


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def field_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field["name"]: field for field in schema["fields"]}


def run_command(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_compare(
    temp_dir: Path,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline_path = temp_dir / "baseline.json"
    candidate_path = temp_dir / "candidate.json"
    report_path = temp_dir / "report.json"
    write_json(baseline_path, baseline_payload)
    write_json(candidate_path, candidate_payload)

    proc = run_command(
        [
            sys.executable,
            str(COMPARE_HELPER),
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--output",
            str(report_path),
        ]
    )
    check(
        proc.returncode in (0, 1),
        "compare helper returns only PASS/FAIL exit codes during regression scenarios",
    )
    check(report_path.exists(), "compare helper emits a machine-readable report")
    return load_json(report_path)


def check_schema_contract(schema: dict[str, Any]) -> None:
    expected_required_fields = [
        "final_total_energy_ry",
        "final_converged",
        "final_residual_threshold_reached",
    ]
    check(
        schema["pass_rule"]["required_fields"] == expected_required_fields,
        "schema required-field gate stays frozen to energy + converged + residual-threshold",
    )

    fields = field_map(schema)
    expected_field_names = {
        "case_id",
        "final_total_energy_ry",
        "final_converged",
        "final_residual_threshold_reached",
        "scf_iterations",
    }
    check(set(fields) == expected_field_names, "schema field roster stays frozen")

    energy = fields["final_total_energy_ry"]
    check(energy["required"] is True, "final_total_energy_ry remains required")
    check(energy["comparison"] == "abs_or_rel", "energy comparison mode remains abs_or_rel")
    check(float(energy["abs_tol"]) == 1e-8, "energy abs_tol remains 1e-8 Ry")
    check(float(energy["rel_tol"]) == 1e-10, "energy rel_tol remains 1e-10")
    check(float(energy["scale_floor"]) == 1.0, "energy scale_floor remains 1.0")

    converged = fields["final_converged"]
    check(converged["required"] is True, "final_converged remains required")
    check(converged["comparison"] == "exact", "final_converged remains exact-match")

    residual = fields["final_residual_threshold_reached"]
    check(
        residual["required"] is True,
        "final_residual_threshold_reached remains required",
    )
    check(
        residual["comparison"] == "exact",
        "final_residual_threshold_reached remains exact-match",
    )
    check(
        residual.get("fallback_from_field") == "final_converged",
        "residual-threshold bootstrap fallback still derives only from final_converged",
    )
    check(
        residual.get("fallback_label") == "bootstrap_from_final_converged",
        "residual-threshold bootstrap label stays explicit",
    )

    iterations = fields["scf_iterations"]
    check(iterations["required"] is False, "scf_iterations remains non-required")
    check(iterations.get("report_only") is True, "scf_iterations remains report-only")


def check_runner_contract() -> None:
    runner = load_module(SWEEP_RUNNER, "qe_gold_runner_contract")
    gold_required = {
        workload_id
        for workload_id, config in runner.DEFAULT_WORKLOADS.items()
        if config.get("gold_required")
    }
    check(
        gold_required == {"si8_pbe_nc", "si8_pbe_uspp"},
        "sweep runner gold-required workload set stays frozen to si8_pbe_nc + si8_pbe_uspp",
    )
    check(
        runner.DEFAULT_WORKLOADS[FIRST_PRIORITY_CASE]["lane"] == "qe_gold",
        "si8_pbe_nc remains anchored in the QE gold lane",
    )
    check(
        runner.DEFAULT_WORKLOADS[FIRST_PRIORITY_CASE]["gold_required"] is True,
        "si8_pbe_nc remains a required QE gold case",
    )
    check(
        set(runner.FAMILY_PROFILES) == {"F1", "F2", "F3"},
        "architecture-family roster remains F1/F2/F3 during this gate phase",
    )


def build_normalized_baseline(temp_dir: Path) -> dict[str, Any]:
    baseline_case_dir = QE_BASELINE_ROOT / FIRST_PRIORITY_CASE
    baseline_out = temp_dir / f"{FIRST_PRIORITY_CASE}.gold.json"
    proc = run_command(
        [
            sys.executable,
            str(NORMALIZE_HELPER),
            "--metadata",
            str(baseline_case_dir / "metadata.json"),
            "--stdout",
            str(baseline_case_dir / "stdout.out"),
            "--case-id",
            FIRST_PRIORITY_CASE,
            "--output",
            str(baseline_out),
        ]
    )
    check(proc.returncode == 0, "baseline normalizer succeeds for si8_pbe_nc")
    check(baseline_out.exists(), "baseline normalizer writes canonical QE gold JSON")
    baseline = load_json(baseline_out)
    final = baseline["final"]
    check(
        {"total_energy_ry", "converged", "residual_threshold_reached"} <= set(final),
        "normalized si8_pbe_nc baseline exposes all required canonical final fields",
    )
    return baseline


def check_compare_semantics(baseline: dict[str, Any]) -> None:
    base_energy = float(baseline["final"]["total_energy_ry"])
    base_iters = int(baseline["final"].get("scf_iterations", 1))
    base_converged = bool(baseline["final"]["converged"])
    base_residual = bool(baseline["final"]["residual_threshold_reached"])

    with tempfile.TemporaryDirectory(prefix="qe-gold-contract-") as tmp:
        temp_dir = Path(tmp)

        within_tol_candidate = {
            "case_id": baseline["case_id"],
            "final": {
                "total_energy_ry": base_energy + 5e-9,
                "converged": base_converged,
                "residual_threshold_reached": base_residual,
                "scf_iterations": base_iters,
            },
        }
        report = run_compare(temp_dir, baseline, within_tol_candidate)
        check(report["overall_pass"] is True, "within-tolerance energy perturbation still passes")

        outside_tol_candidate = {
            "case_id": baseline["case_id"],
            "final": {
                "total_energy_ry": base_energy + 5e-7,
                "converged": base_converged,
                "residual_threshold_reached": base_residual,
                "scf_iterations": base_iters,
            },
        }
        report = run_compare(temp_dir, baseline, outside_tol_candidate)
        energy_field = next(
            item for item in report["field_results"] if item["name"] == "final_total_energy_ry"
        )
        check(report["overall_pass"] is False, "outside-tolerance energy perturbation still fails")
        check(energy_field["status"] == "fail", "energy mismatch is still surfaced as a field fail")

        report_only_candidate = {
            "case_id": baseline["case_id"],
            "final": {
                "total_energy_ry": base_energy,
                "converged": base_converged,
                "residual_threshold_reached": base_residual,
                "scf_iterations": base_iters + 1,
            },
        }
        report = run_compare(temp_dir, baseline, report_only_candidate)
        iteration_field = next(item for item in report["field_results"] if item["name"] == "scf_iterations")
        check(
            report["overall_pass"] is True,
            "scf_iterations mismatch stays diagnostic-only and does not break overall gold_pass",
        )
        check(
            iteration_field["status"] == "fail",
            "scf_iterations mismatch remains visible in field-level diagnostics",
        )

        fallback_candidate = {
            "case_id": baseline["case_id"],
            "final": {
                "total_energy_ry": base_energy,
                "converged": base_converged,
                "scf_iterations": base_iters,
            },
        }
        report = run_compare(temp_dir, baseline, fallback_candidate)
        residual_field = next(
            item
            for item in report["field_results"]
            if item["name"] == "final_residual_threshold_reached"
        )
        check(
            report["overall_pass"] is True,
            "residual-threshold bootstrap from final_converged still preserves the frozen contract",
        )
        check(
            residual_field["candidate"]["source"] == "field_fallback",
            "residual-threshold bootstrap remains explicitly labeled as field_fallback",
        )
        check(
            residual_field["candidate"]["note"] == "bootstrap_from_final_converged",
            "residual-threshold bootstrap note remains explicit in reports",
        )


def main() -> int:
    schema = load_json(SCHEMA_PATH)
    check_schema_contract(schema)
    check_runner_contract()
    with tempfile.TemporaryDirectory(prefix="qe-gold-baseline-") as tmp:
        baseline = build_normalized_baseline(Path(tmp))
    check_compare_semantics(baseline)
    print("[PASS] QE gold frozen-contract regression guard completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
