#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
VALIDATOR_PATH = TOOLS_BENCHMARKS_DIR / "check_qe_phase1_artifact_contracts.py"

REQUIRED_ARTIFACT_KEYS = ["stdout", "stderr", "timing", "correctness", "convergence", "power", "summary"]


class ReadinessError(RuntimeError):
    pass


def load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location("qe_phase1_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ReadinessError(f"cannot import validator module from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def maybe_load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


def artifact_path_map(baseline_dir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    paths = {}
    for key, rel in manifest["artifact_paths"].items():
        paths[key] = baseline_dir / rel
    return paths


def classify_row(baseline_dir: Path, validator: Any, runner: Any) -> dict[str, Any]:
    manifest_path = baseline_dir / "cpu_gpu_baseline_manifest.json"
    if not manifest_path.exists():
        return {
            "baseline_dir": str(baseline_dir),
            "status": "deferred",
            "reason": "missing_cpu_gpu_baseline_manifest",
        }

    manifest = load_json(manifest_path)
    validator.validate_baseline_manifest_template(manifest, runner, manifest_path)
    rewrite_manifest_path = baseline_dir / "algorithm_rewrite_manifest.json"
    if not rewrite_manifest_path.exists():
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "missing_algorithm_rewrite_manifest",
            "manifest_path": str(manifest_path),
        }
    rewrite_manifest = load_json(rewrite_manifest_path)
    validator.validate_algorithm_rewrite_manifest_template(
        rewrite_manifest, runner, rewrite_manifest_path
    )

    artifacts = artifact_path_map(baseline_dir, manifest)
    missing = [key for key in REQUIRED_ARTIFACT_KEYS if not artifacts[key].exists()]
    if missing:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "deferred",
            "reason": "missing_artifacts:" + ",".join(missing),
            "manifest_path": str(manifest_path),
        }

    correctness = maybe_load_json(artifacts["correctness"]) or {}
    convergence = maybe_load_json(artifacts["convergence"]) or {}
    timing = maybe_load_json(artifacts["timing"]) or {}
    power = maybe_load_json(artifacts["power"]) or {}

    gold_pass = correctness.get("gold_pass")
    convergence_pass = (
        correctness.get("convergence_comparable_pass")
        if "convergence_comparable_pass" in correctness
        else convergence.get("convergence_comparable_pass")
    )
    time_to_convergence = timing.get("time_to_convergence_s")
    avg_power = power.get("avg_whole_node_power_w")
    energy = power.get("energy_to_solution_j")

    if gold_pass is not True or convergence_pass is not True:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "correctness_or_convergence_not_closed",
            "gold_pass": gold_pass,
            "convergence_comparable_pass": convergence_pass,
            "manifest_path": str(manifest_path),
        }

    if time_to_convergence is None or avg_power is None or energy is None:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "missing_decisive_metrics",
            "manifest_path": str(manifest_path),
        }

    if manifest.get("shared_rewrite_closed") is not True:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "shared_rewrite_not_closed",
            "manifest_path": str(manifest_path),
        }

    relevant_entries = [
        entry
        for entry in rewrite_manifest.get("entries", [])
        if manifest["case_id"] in entry.get("affected_workload_ids", [])
    ]
    unresolved_rewrite = any(
        entry.get("review_status") != "accepted"
        or entry.get("gpu_applicable") == "unclear"
        or (
            entry.get("gpu_applicable") == "yes"
            and entry.get("gpu_enabled_in_baseline") != "yes"
        )
        for entry in relevant_entries
    )
    if unresolved_rewrite:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "rewrite_manifest_not_closed",
            "manifest_path": str(manifest_path),
        }

    if manifest.get("host_platform_comparable") is not True:
        return {
            "baseline_dir": str(baseline_dir),
            "case_id": manifest["case_id"],
            "gpu_mode": manifest["gpu_mode"],
            "status": "reference_only",
            "reason": "host_platform_not_comparable",
            "manifest_path": str(manifest_path),
        }

    return {
        "baseline_dir": str(baseline_dir),
        "case_id": manifest["case_id"],
        "gpu_mode": manifest["gpu_mode"],
        "status": "thesis_eligible",
        "reason": "all_phase1_gates_closed",
        "time_to_convergence_s": time_to_convergence,
        "avg_whole_node_power_w": avg_power,
        "energy_to_solution_j": energy,
        "manifest_path": str(manifest_path),
    }


def choose_decisive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_id = row.get("case_id")
        if not case_id:
            continue
        grouped.setdefault(case_id, []).append(row)

    for case_id, case_rows in grouped.items():
        eligible = [row for row in case_rows if row["status"] == "thesis_eligible"]
        if not eligible:
            continue
        attempts = set()
        exemption_present = False
        for row in case_rows:
            manifest_path = row.get("manifest_path")
            if manifest_path:
                manifest = load_json(Path(manifest_path))
                attempts.update(manifest.get("gpu_mode_attempts", []))
                exemption_present = exemption_present or bool(
                    manifest.get("mode_attempt_exemption_note", "").strip()
                )
        case_ready = ({"strict_fp64", "practical"} <= attempts) or exemption_present
        best = min(eligible, key=lambda row: row["time_to_convergence_s"])
        for row in case_rows:
            row["baseline_state"] = row["status"]
            row["decisive_for_case"] = bool(case_ready and row is best)
            row["case_ready"] = case_ready
    return rows


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "schema_version": "qe_cpu_gpu_baseline_readiness_report_v0",
        "rows": rows,
        "counts": {
            "thesis_eligible": sum(1 for row in rows if row["status"] == "thesis_eligible"),
            "reference_only": sum(1 for row in rows if row["status"] == "reference_only"),
            "deferred": sum(1 for row in rows if row["status"] == "deferred"),
            "decisive": sum(1 for row in rows if row.get("decisive_for_case")),
        },
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess phase-1 CPU+GPU baseline artifact directories against the frozen readiness contracts."
    )
    parser.add_argument("--baseline-dir", action="append", required=True, help="Directory containing cpu_gpu_baseline_manifest.json and referenced artifacts. May be repeated.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validator = load_validator_module()
    runner = validator.load_runner_module()
    rows = [classify_row(Path(path), validator, runner) for path in args.baseline_dir]
    rows = choose_decisive(rows)
    summary = build_summary(rows)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
