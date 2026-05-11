#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import sys
from collections import Counter
from pathlib import Path


FLOAT_FIELDS = [
    "h_frob",
    "h_max_abs",
    "h_min_nz_abs",
    "h_diag_min",
    "h_diag_max",
    "h_diag_imag_max",
    "h_herm_rel",
    "s_frob",
    "s_max_abs",
    "s_min_nz_abs",
    "s_diag_min",
    "s_diag_max",
    "s_diag_imag_max",
    "s_herm_rel",
    "s_identity_rel",
]


def parse_bool(text: str) -> bool:
    return text.strip().lower() in {"t", "true", "1", "y", "yes"}


def parse_csv(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            parsed: dict[str, object] = {
                "call_id": int(row["call_id"]),
                "solver": row["solver"],
                "n": int(row["n"]),
                "m": int(row["m"]),
                "all_eigenvalues": parse_bool(row["all_eigenvalues"]),
            }
            for field in FLOAT_FIELDS:
                parsed[field] = float(row[field])
            rows.append(parsed)
    return rows


def fmt_float(value: float) -> str:
    if math.isnan(value):
        return "nan"
    return f"{value:.3e}"


def print_counter(title: str, counter: Counter[object], limit: int = 10) -> None:
    print(title)
    for key, count in counter.most_common(limit):
        print(f"  {key}: {count}")
    print()


def summarize(rows: list[dict[str, object]]) -> None:
    if not rows:
        print("No rows found.")
        return

    n_counter = Counter(int(row["n"]) for row in rows)
    nm_counter = Counter((int(row["n"]), int(row["m"])) for row in rows)
    solver_counter = Counter(str(row["solver"]) for row in rows)

    generalized = sum(float(row["s_identity_rel"]) > 1e-10 for row in rows)
    standard_like = len(rows) - generalized

    print(f"Total calls: {len(rows)}")
    print(f"Generalized-like calls (s_identity_rel > 1e-10): {generalized}")
    print(f"Standard-like calls   (s_identity_rel <= 1e-10): {standard_like}")
    print()

    print_counter("Solver counts", solver_counter)
    print_counter("Top n sizes", n_counter)
    print_counter("Top (n, m) pairs", nm_counter)

    fields_to_report = [
        "h_max_abs",
        "h_min_nz_abs",
        "h_herm_rel",
        "s_max_abs",
        "s_min_nz_abs",
        "s_herm_rel",
        "s_identity_rel",
    ]

    print("Global ranges")
    for field in fields_to_report:
        values = [float(row[field]) for row in rows]
        print(f"  {field}: min={fmt_float(min(values))} max={fmt_float(max(values))}")
    print()

    worst_herm = sorted(rows, key=lambda r: float(r["h_herm_rel"]), reverse=True)[:5]
    print("Top 5 h_herm_rel calls")
    for row in worst_herm:
        print(
            "  call={call_id} solver={solver} n={n} m={m} h_herm_rel={herm} s_identity_rel={sid}".format(
                call_id=row["call_id"],
                solver=row["solver"],
                n=row["n"],
                m=row["m"],
                herm=fmt_float(float(row["h_herm_rel"])),
                sid=fmt_float(float(row["s_identity_rel"])),
            )
        )
    print()

    worst_overlap = sorted(rows, key=lambda r: float(r["s_identity_rel"]), reverse=True)[:5]
    print("Top 5 generalized-like calls by s_identity_rel")
    for row in worst_overlap:
        print(
            "  call={call_id} solver={solver} n={n} m={m} s_identity_rel={sid} s_herm_rel={sherm}".format(
                call_id=row["call_id"],
                solver=row["solver"],
                n=row["n"],
                m=row["m"],
                sid=fmt_float(float(row["s_identity_rel"])),
                sherm=fmt_float(float(row["s_herm_rel"])),
            )
        )


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} /abs/path/qe_subspace_trace.csv", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Trace file not found: {path}", file=sys.stderr)
        return 1

    summarize(parse_csv(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
