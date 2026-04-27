#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "docs/architecture/qe_fpga_clustered_v1_architecture_model_template_v0.csv"


DEFAULT_COEFFICIENTS = {
    "k_dma_eff": 0.50,
    "k_ab_stream_eff": 0.75,
    "k_bc_stream_eff": 0.75,
    "k_cd_stream_eff": 0.75,
    "k_controller_setup_mul": 8.0,
    "k_a_fft_us_per_kib": 0.10,
    "k_a_array_work_per_lane_per_us": 40.0,
    "k_b_accum_kib_per_lane_per_us": 0.60,
    "k_b_reduce_kib_per_lane_per_us": 1.00,
    "k_c_pipeline_factor": 2.0,
    "k_d_refresh_kib_per_lane_per_us": 0.75,
    "k_d_residual_lane_eff": 1.50,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute clustered-FPGA cycle-approx proxy latency columns from the architecture-model CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Input architecture-model CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path. If omitted with --in-place, rewrites the input file.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the input CSV in place.",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print a short latency summary for each row.",
    )
    return parser.parse_args()


def as_float(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value is None or value == "":
        return 0.0
    return float(value)


def projector_pressure(row: dict[str, str]) -> float:
    return max(1.0, as_float(row, "nkb") / 64.0)


def subspace_pressure(row: dict[str, str]) -> float:
    return max(1.0, as_float(row, "n_active") / 32.0)


def compute_t_a(row: dict[str, str]) -> float:
    proj = projector_pressure(row)
    t_a_load = as_float(row, "psi_panel_kib") / (
        max(1e-9, as_float(row, "offchip_bw_kib_per_us")) * DEFAULT_COEFFICIENTS["k_dma_eff"]
    )

    a_fft_lanes = as_float(row, "a_fft_lanes")
    if a_fft_lanes <= 0.0:
        t_a_fft = 0.0
    else:
        t_a_fft = (
            as_float(row, "psi_panel_kib")
            * DEFAULT_COEFFICIENTS["k_a_fft_us_per_kib"]
            / a_fft_lanes
        )

    t_a_array = (
        as_float(row, "npw")
        * as_float(row, "panel_bands")
        * proj
        / max(1e-9, as_float(row, "a_array_lanes") * DEFAULT_COEFFICIENTS["k_a_array_work_per_lane_per_us"])
    )
    t_a_emit = (
        as_float(row, "a_partial_fifo_kib")
        * proj
        / max(1e-9, as_float(row, "a_stream_lanes") * DEFAULT_COEFFICIENTS["k_ab_stream_eff"])
    )
    return max(t_a_load, t_a_fft, t_a_array, t_a_emit)


def compute_t_b(row: dict[str, str]) -> float:
    proj = projector_pressure(row)
    sub = subspace_pressure(row)
    b_lanes = max(1e-9, as_float(row, "b_accum_lanes"))

    t_b_accum = (
        as_float(row, "b_accum_buffer_kib")
        * proj
        / (b_lanes * DEFAULT_COEFFICIENTS["k_b_accum_kib_per_lane_per_us"])
    )
    t_b_reduce = (
        as_float(row, "b_reduced_stage_kib")
        * sub
        / (b_lanes * DEFAULT_COEFFICIENTS["k_b_reduce_kib_per_lane_per_us"])
    )
    t_b_emit = as_float(row, "b_reduced_stage_kib") / (
        max(1e-9, as_float(row, "b_reduced_emit_bw_kib_per_us")) * DEFAULT_COEFFICIENTS["k_bc_stream_eff"]
    )
    return max(t_b_accum, t_b_reduce, t_b_emit)


def compute_t_c(row: dict[str, str]) -> float:
    t_c_input = as_float(row, "c_input_buffer_kib") / (
        max(1e-9, as_float(row, "b_reduced_emit_bw_kib_per_us")) * DEFAULT_COEFFICIENTS["k_bc_stream_eff"]
    )
    t_c_compute = (
        DEFAULT_COEFFICIENTS["k_c_pipeline_factor"]
        * as_float(row, "c_compute_us_per_n3")
        * (as_float(row, "n_active") ** 3)
        / max(1e-9, as_float(row, "c_solver_parallelism"))
    )
    t_c_emit = (
        as_float(row, "c_eigvec_buffer_kib") + as_float(row, "c_eigval_buffer_kib")
    ) / (max(1e-9, as_float(row, "c_emit_bw_kib_per_us")) * DEFAULT_COEFFICIENTS["k_cd_stream_eff"])
    return max(t_c_input, t_c_compute, t_c_emit)


def compute_t_d(row: dict[str, str]) -> float:
    sub = subspace_pressure(row)
    d_lanes = max(1e-9, as_float(row, "d_refresh_lanes"))

    t_d_refresh = (
        as_float(row, "d_pnext_slots_kib")
        * sub
        / (d_lanes * DEFAULT_COEFFICIENTS["k_d_refresh_kib_per_lane_per_us"])
    )
    t_d_residual = (
        as_float(row, "d_refresh_buffer_kib") + as_float(row, "n_active") / 4.0
    ) / (d_lanes * DEFAULT_COEFFICIENTS["k_d_residual_lane_eff"])
    t_d_writeback = as_float(row, "d_pnext_slots_kib") / (
        max(1e-9, as_float(row, "d_writeback_bw_kib_per_us")) * DEFAULT_COEFFICIENTS["k_cd_stream_eff"]
    )
    return max(t_d_refresh, t_d_residual, t_d_writeback)


def compute_episode(row: dict[str, str], t_a: float, t_b: float, t_c: float, t_d: float) -> float:
    t_controller_setup = max(
        1.0,
        DEFAULT_COEFFICIENTS["k_controller_setup_mul"] * as_float(row, "controller_sync_us"),
    )
    t_spill_penalty = as_float(row, "bytes_spill_kib") * as_float(row, "spill_penalty_us_per_kib")
    return (
        t_controller_setup
        + as_float(row, "inner_steps") * (max(t_a, t_b) + t_c + t_d + as_float(row, "controller_sync_us"))
        + t_spill_penalty
    )


def format_us(value: float) -> str:
    text = f"{value:.2f}".rstrip("0")
    if text.endswith("."):
        return text + "0"
    return text


def main() -> int:
    args = parse_args()
    input_path = args.input
    output_path = args.output
    if args.in_place:
        output_path = input_path
    elif output_path is None:
        raise SystemExit("Specify --output or use --in-place.")

    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for row in rows:
        t_a = compute_t_a(row)
        t_b = compute_t_b(row)
        t_c = compute_t_c(row)
        t_d = compute_t_d(row)
        t_episode = compute_episode(row, t_a, t_b, t_c, t_d)
        row["t_a_us"] = format_us(t_a)
        row["t_b_us"] = format_us(t_b)
        row["t_c_us"] = format_us(t_c)
        row["t_d_us"] = format_us(t_d)
        row["t_episode_cluster_lb_us"] = format_us(t_episode)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    if args.print_summary:
        for row in rows:
            print(
                row["case_id"],
                row["t_a_us"],
                row["t_b_us"],
                row["t_c_us"],
                row["t_d_us"],
                row["t_episode_cluster_lb_us"],
                row["cdiaghg_mode_selected"],
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
