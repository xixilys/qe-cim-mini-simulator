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
GPU_ASSESSOR_PATH = TOOLS_BENCHMARKS_DIR / "assess_qe_cpu_gpu_baseline_readiness.py"
VALIDATOR_PATH = TOOLS_BENCHMARKS_DIR / "check_qe_phase1_artifact_contracts.py"

PHASE1_DECISIVE_LANE = [
    "si4_pbe_uspp_small",
    "graphene_pbe_uspp",
]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess whether phase-1 thesis evidence closure is satisfied for the current QE-only CPU+FPGA plan."
    )
    parser.add_argument(
        "--gpu-baseline-dir",
        action="append",
        default=[],
        help="Directory containing a CPU+GPU baseline bundle. May be repeated.",
    )
    parser.add_argument(
        "--board-dir",
        action="append",
        default=[],
        help="Directory containing board_manifest.json, board_metrics.json, board_power.json, board_compare.json. May be repeated.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output path.")
    return parser.parse_args()


def assess_gpu_rows(dirs: list[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    assessor = load_module(GPU_ASSESSOR_PATH, "qe_cpu_gpu_readiness")
    validator = assessor.load_validator_module()
    runner = validator.load_runner_module()
    rows = [assessor.classify_row(Path(path), validator, runner) for path in dirs]
    rows = assessor.choose_decisive(rows)
    by_case: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("case_id")
        if not case_id:
            continue
        entry = by_case.setdefault(
            case_id,
            {
                "gpu_rows": [],
                "gpu_decisive_ready": False,
                "gpu_blockers": [],
            },
        )
        entry["gpu_rows"].append(row)
        if row.get("decisive_for_case"):
            entry["gpu_decisive_ready"] = True
        if row["status"] != "thesis_eligible":
            entry["gpu_blockers"].append(row["reason"])
    return rows, by_case


def assess_board_dirs(dirs: list[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    validator = load_module(VALIDATOR_PATH, "qe_phase1_validator")
    runner = validator.load_runner_module()
    rows: list[dict[str, Any]] = []
    by_case: dict[str, dict[str, Any]] = {}
    for raw in dirs:
        path = Path(raw)
        try:
            validator.validate_board_artifact_bundle(path, runner)
            manifest = json.loads((path / "board_manifest.json").read_text(encoding="utf-8"))
            case_id = manifest["workload_id"]
            row = {
                "board_dir": str(path),
                "case_id": case_id,
                "status": "board_ready",
            }
        except Exception as exc:  # pragma: no cover - defensive
            case_id = None
            manifest_path = path / "board_manifest.json"
            if manifest_path.exists():
                try:
                    case_id = json.loads(manifest_path.read_text(encoding="utf-8")).get("workload_id")
                except Exception:
                    case_id = None
            row = {
                "board_dir": str(path),
                "case_id": case_id,
                "status": "board_blocked",
                "reason": str(exc),
            }
        rows.append(row)
        if case_id is None:
            continue
        entry = by_case.setdefault(
            case_id,
            {
                "board_rows": [],
                "board_ready": False,
                "board_blockers": [],
            },
        )
        entry["board_rows"].append(row)
        if row["status"] == "board_ready":
            entry["board_ready"] = True
        else:
            entry["board_blockers"].append(row["reason"])
    return rows, by_case


def build_case_matrix(
    gpu_by_case: dict[str, dict[str, Any]],
    board_by_case: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    all_cases = sorted(set(PHASE1_DECISIVE_LANE) | set(gpu_by_case) | set(board_by_case))
    matrix = []
    for case_id in all_cases:
        gpu = gpu_by_case.get(case_id, {})
        board = board_by_case.get(case_id, {})
        matrix.append(
            {
                "case_id": case_id,
                "gpu_decisive_ready": bool(gpu.get("gpu_decisive_ready", False)),
                "board_ready": bool(board.get("board_ready", False)),
                "thesis_count_candidate_ready": bool(
                    gpu.get("gpu_decisive_ready", False) and board.get("board_ready", False)
                ),
                "gpu_blockers": gpu.get("gpu_blockers", []),
                "board_blockers": board.get("board_blockers", []),
            }
        )
    return matrix


def build_summary(gpu_rows: list[dict[str, Any]], board_rows: list[dict[str, Any]], case_matrix: list[dict[str, Any]]) -> dict[str, Any]:
    decisive_ready_cases = [row["case_id"] for row in case_matrix if row["thesis_count_candidate_ready"]]
    decisive_lane_closed = all(
        any(row["case_id"] == target and row["thesis_count_candidate_ready"] for row in case_matrix)
        for target in PHASE1_DECISIVE_LANE
    )
    return {
        "schema_version": "qe_phase1_evidence_closure_report_v0",
        "gpu_rows": gpu_rows,
        "board_rows": board_rows,
        "case_matrix": case_matrix,
        "summary": {
            "gpu_input_rows": len(gpu_rows),
            "board_input_rows": len(board_rows),
            "gpu_decisive_ready_cases": sum(1 for row in case_matrix if row["gpu_decisive_ready"]),
            "board_ready_cases": sum(1 for row in case_matrix if row["board_ready"]),
            "thesis_count_candidate_ready_cases": len(decisive_ready_cases),
            "decisive_lane_targets": PHASE1_DECISIVE_LANE,
            "decisive_lane_closed": decisive_lane_closed,
            "repo_internal_status": "complete",
            "next_blocker_class": "external_measurement_artifacts" if not decisive_lane_closed else "none",
        },
    }


def main() -> int:
    args = parse_args()
    gpu_rows, gpu_by_case = assess_gpu_rows(args.gpu_baseline_dir)
    board_rows, board_by_case = assess_board_dirs(args.board_dir)
    case_matrix = build_case_matrix(gpu_by_case, board_by_case)
    report = build_summary(gpu_rows, board_rows, case_matrix)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
