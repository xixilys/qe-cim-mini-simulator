#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive CPU-only speedup envelopes from measured QE shell aggregate timings."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Measured CPU shell aggregate JSON from extract_qe_shell_cpu_baseline.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the derived speedup-envelope JSON.",
    )
    return parser.parse_args()


def amdahl_speedup(parallel_fraction: float, accel: float) -> float:
    if accel <= 0.0:
        raise ValueError("accel must be positive")
    return 1.0 / ((1.0 - parallel_fraction) + parallel_fraction / accel)


def main() -> int:
    args = parse_args()
    measured = json.loads(args.input.read_text(encoding="utf-8"))
    accel_points = [2.0, 4.0, 8.0, 16.0]

    out = []
    for row in measured:
        electrons = row.get("electrons_wall_s")
        cbands = row.get("c_bands_wall_s")
        hpsi = row.get("h_psi_wall_s")
        if not electrons or not cbands or not hpsi:
            continue

        f_cbands = cbands / electrons
        f_hpsi = hpsi / electrons
        cbands_curve = {str(int(point)): amdahl_speedup(f_cbands, point) for point in accel_points}
        hpsi_curve = {str(int(point)): amdahl_speedup(f_hpsi, point) for point in accel_points}

        out.append(
            {
                "case_id": row["case_id"],
                "source_type": "derived_from_measured_cpu_shell_aggregate",
                "measured_source_file": str(args.input),
                "electrons_wall_s": electrons,
                "c_bands_wall_s": cbands,
                "h_psi_wall_s": hpsi,
                "fractions": {
                    "c_bands_of_electrons": f_cbands,
                    "h_psi_of_electrons": f_hpsi,
                    "h_psi_of_c_bands": hpsi / cbands,
                },
                "upper_bounds": {
                    "if_c_bands_were_infinitely_fast": 1.0 / (1.0 - f_cbands),
                    "if_h_psi_were_infinitely_fast": 1.0 / (1.0 - f_hpsi),
                },
                "speedup_curves": {
                    "whole_scf_if_only_c_bands_is_accelerated": cbands_curve,
                    "whole_scf_if_only_h_psi_is_accelerated": hpsi_curve,
                },
                "note": (
                    "This is an Amdahl-style envelope derived from measured CPU-only QE timing sections. "
                    "It is not an FPGA measurement, not a cluster-model latency prediction, and not a claim "
                    "that the proposed FPGA design already achieves these speedups."
                ),
            }
        )

    args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
