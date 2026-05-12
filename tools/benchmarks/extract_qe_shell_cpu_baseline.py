#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = ROOT / "docs/benchmarks/archive/results/qe_workload_revalidation"

TIMING_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_*:+-]+)\s*:\s*"
    r"(?P<cpu>[0-9.]+)s CPU\s*"
    r"(?P<wall>[0-9.]+)s WALL\s*\(\s*(?P<calls>\d+) calls\)"
)
SUMMARY_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_*:+-]+)\s*:\s*"
    r"(?P<cpu>[0-9.]+)s CPU\s*"
    r"(?P<wall>[0-9.]+)s WALL\s*$"
)
ITER_RE = re.compile(r"^\s*iteration #\s*(\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract measured CPU-only shell aggregates from QE workload revalidation outputs."
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        required=True,
        help="Case ids under docs/benchmarks/archive/results/qe_workload_revalidation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the extracted JSON payload.",
    )
    return parser.parse_args()


def parse_case(case_id: str) -> dict[str, object]:
    case_dir = RESULTS_ROOT / case_id
    metadata_path = case_dir / "metadata.json"
    stdout_path = case_dir / "stdout.out"

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="ignore")

    timings: dict[str, dict[str, float | int]] = {}
    iter_count = 0
    converged = False
    for line in stdout_text.splitlines():
        if ITER_RE.match(line):
            iter_count += 1
        if "convergence has been achieved" in line:
            converged = True
        match = TIMING_RE.match(line)
        if match:
            timings[match.group("name")] = {
                "cpu_s": float(match.group("cpu")),
                "wall_s": float(match.group("wall")),
                "calls": int(match.group("calls")),
            }
            continue
        summary = SUMMARY_RE.match(line)
        if summary:
            timings[summary.group("name")] = {
                "cpu_s": float(summary.group("cpu")),
                "wall_s": float(summary.group("wall")),
                "calls": None,
            }

    electrons = timings.get("electrons", {})
    c_bands = timings.get("c_bands", {})
    h_psi = timings.get("h_psi", {})

    avg_episode_ms = None
    if c_bands.get("wall_s") is not None and c_bands.get("calls"):
        avg_episode_ms = float(c_bands["wall_s"]) * 1000.0 / int(c_bands["calls"])

    avg_iter_ms = None
    if electrons.get("wall_s") is not None and iter_count > 0:
        avg_iter_ms = float(electrons["wall_s"]) * 1000.0 / iter_count

    payload = {
        "case_id": case_id,
        "source_type": "measured_qe_stdout_and_metadata",
        "metadata_file": str(metadata_path),
        "stdout_file": str(stdout_path),
        "duration_sec": metadata["duration_sec"],
        "exit_code": metadata["exit_code"],
        "omp_threads": metadata["environment"].get("OMP_NUM_THREADS"),
        "scf_iterations": iter_count,
        "converged": converged,
        "pwscf_wall_s": timings.get("PWSCF", {}).get("wall_s"),
        "electrons_wall_s": electrons.get("wall_s"),
        "electrons_calls": electrons.get("calls"),
        "c_bands_wall_s": c_bands.get("wall_s"),
        "c_bands_calls": c_bands.get("calls"),
        "h_psi_wall_s": h_psi.get("wall_s"),
        "h_psi_calls": h_psi.get("calls"),
        "derived_metrics": {
            "avg_c_bands_episode_wall_ms": avg_episode_ms,
            "avg_scf_iteration_wall_ms_from_electrons": avg_iter_ms,
        },
        "derived_metrics_note": (
            "Derived averages are computed from measured aggregate timing sections in QE stdout; "
            "they are not direct per-episode or per-iteration timer outputs."
        ),
    }
    return payload


def main() -> int:
    args = parse_args()
    rows = [parse_case(case_id) for case_id in args.cases]
    args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
