#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = ROOT / "docs/benchmarks/results/qe_workload_revalidation"

CASE_ORDER = [
    "h2_tiny",
    "au_slab_subspace",
    "si4_pbe_uspp_small",
    "si8_pbe_uspp",
    "si8_pbe_nc",
    "si8_pbe0_uspp",
    "sic32_subspace",
    "graphene_pbe_paw",
    "graphene_pbe_uspp",
    "benzene",
    "bn32_pbe_uspp",
    "bn32_pbe0_uspp",
]

SOLVER_PHRASES = {
    "Davidson diagonalization with overlap": "davidson",
    "CG style diagonalization": "cg",
    "RMM-DIIS diagonalization": "rmm-diis",
    "ParO style diagonalization": "paro",
}

TIMING_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_*:+-]+)\s*:\s*"
    r"(?P<cpu>[0-9.]+)s CPU\s*"
    r"(?P<wall>[0-9.]+)s WALL\s*\(\s*(?P<calls>\d+) calls\)"
)
ITER_RE = re.compile(r"^\s*iteration #\s*(\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize rerun QE workload evidence.")
    parser.add_argument(
        "--results-root",
        type=Path,
        default=RESULTS_ROOT,
        help="Root directory that contains per-case rerun artifacts.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=RESULTS_ROOT / "summary.json",
        help="Where to write the machine-readable summary.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=RESULTS_ROOT / "summary_tables.md",
        help="Where to write a compact Markdown summary.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_bool(text: str) -> bool:
    return text.strip().lower() in {"t", "true", "1", "y", "yes"}


def find_assignment(text: str, key: str) -> str | None:
    pattern = re.compile(rf"\b{re.escape(key)}\s*=\s*([^,\n]+)", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return value


def parse_atomic_species(lines: list[str]) -> list[dict[str, str]]:
    species: list[dict[str, str]] = []
    capture = False
    for raw_line in lines:
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("ATOMIC_SPECIES"):
            capture = True
            continue
        if not capture:
            continue
        if not line:
            continue
        if upper.startswith("ATOMIC_POSITIONS") or upper.startswith("K_POINTS"):
            break
        parts = line.split()
        if len(parts) >= 3:
            species.append({"element": parts[0], "mass": parts[1], "pseudo": parts[2]})
    return species


def parse_input_metadata(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    return {
        "path": str(path),
        "prefix": find_assignment(text, "prefix") or path.stem,
        "calculation": find_assignment(text, "calculation") or "unknown",
        "functional": (find_assignment(text, "input_dft") or "pbe").lower(),
        "diagonalization_input": (find_assignment(text, "diagonalization") or "default").lower(),
        "nat": int(float(find_assignment(text, "nat") or "0")),
        "ntyp": int(float(find_assignment(text, "ntyp") or "0")),
        "nbnd": int(float(find_assignment(text, "nbnd") or "0")) if find_assignment(text, "nbnd") else None,
        "ecutwfc": float(find_assignment(text, "ecutwfc") or "nan"),
        "ecutrho": float(find_assignment(text, "ecutrho") or "nan"),
        "electron_maxstep": int(float(find_assignment(text, "electron_maxstep") or "0"))
        if find_assignment(text, "electron_maxstep")
        else None,
        "outdir": find_assignment(text, "outdir") or "",
        "pseudo_dir": find_assignment(text, "pseudo_dir") or "",
        "species": parse_atomic_species(lines),
    }


def parse_pseudo_type(path: Path) -> str:
    if not path.is_file():
        return "missing"
    text = path.read_text(encoding="utf-8", errors="ignore")
    lowered = text.lower()
    name = path.name.lower()
    match = re.search(r'pseudo_type="([^"]+)"', text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    if 'is_paw="true"' in lowered or "pseudo is paw" in lowered:
        return "PAW"
    if "ultrasoft" in lowered or "rrkjus" in lowered:
        return "USPP"
    if (
        "norm-conserving" in lowered
        or "oncv" in lowered
        or "pseudo is norm-conserving" in lowered
        or "vbc" in name
    ):
        return "NC"
    return "unknown"


def attach_pseudo_types(input_meta: dict[str, object]) -> list[dict[str, str]]:
    pseudo_dir = Path(str(input_meta["pseudo_dir"]))
    species: list[dict[str, str]] = []
    for item in input_meta["species"]:
        pseudo_name = item["pseudo"]
        pseudo_path = pseudo_dir / pseudo_name
        species.append(
            {
                "element": item["element"],
                "pseudo": pseudo_name,
                "pseudo_type": parse_pseudo_type(pseudo_path),
                "path": str(pseudo_path),
            }
        )
    return species


def parse_timing_sections(text: str) -> dict[str, dict[str, dict[str, float | int]]]:
    sections: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip() == "General routines":
            current_section = "General routines"
            continue
        if line.strip() == "Parallel routines":
            current_section = None
            continue
        if line.strip().startswith("Called by ") and line.strip().endswith(":"):
            current_section = line.strip()[10:-1]
            continue
        if current_section is None:
            continue
        match = TIMING_RE.match(line)
        if not match:
            continue
        sections[current_section][match.group("name")] = {
            "cpu_s": float(match.group("cpu")),
            "wall_s": float(match.group("wall")),
            "calls": int(match.group("calls")),
        }
    return sections


def parse_solver_path(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    pending_iter: int | None = None
    countdown = 0
    for raw_line in text.splitlines():
        match = ITER_RE.match(raw_line)
        if match:
            pending_iter = int(match.group(1))
            countdown = 4
            continue
        if pending_iter is None:
            continue
        stripped = raw_line.strip()
        if not stripped:
            countdown = max(countdown - 1, 0)
            if countdown == 0:
                pending_iter = None
            continue
        solver = None
        for phrase, family in SOLVER_PHRASES.items():
            if phrase in stripped:
                solver = family
                break
        if solver is not None:
            rows.append({"scf_iter": pending_iter, "solver_family": solver})
            pending_iter = None
            countdown = 0
            continue
        countdown = max(countdown - 1, 0)
        if countdown == 0:
            pending_iter = None
    return rows


def parse_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def parse_trace_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in parse_csv_rows(path):
        cooked: dict[str, object] = {}
        for key, value in raw.items():
            if value is None:
                cooked[key] = value
            elif key in {"case_id", "solver_family", "op"}:
                cooked[key] = value
            elif key in {"gamma_only", "okvan", "all_eigenvalues"}:
                cooked[key] = parse_bool(value)
            elif key in {"solver"}:
                cooked[key] = value
            elif key.startswith("h_") or key.startswith("s_"):
                cooked[key] = float(value)
            else:
                try:
                    cooked[key] = int(value)
                except ValueError:
                    try:
                        cooked[key] = float(value)
                    except ValueError:
                        cooked[key] = value
        rows.append(cooked)
    return rows


def share_map(entries: dict[str, dict[str, float | int]], selected: list[str]) -> dict[str, float]:
    total = sum(float(item["wall_s"]) for item in entries.values())
    if total <= 0.0:
        return {name: 0.0 for name in selected + ["other"]}
    payload = {}
    picked = 0.0
    for name in selected:
        wall = float(entries.get(name, {}).get("wall_s", 0.0))
        payload[name] = wall / total
        picked += wall
    payload["other"] = max(0.0, 1.0 - picked / total)
    return payload


def sum_group(entries: dict[str, dict[str, float | int]], names: list[str]) -> float:
    return sum(float(entries.get(name, {}).get("wall_s", 0.0)) for name in names)


def top_pairs(rows: list[dict[str, object]], limit: int = 3) -> list[dict[str, object]]:
    counter = Counter((int(row["n"]), int(row["m"])) for row in rows if "n" in row and "m" in row)
    return [
        {"n": n, "m": m, "count": count}
        for (n, m), count in counter.most_common(limit)
    ]


def max_or_zero(values: list[int]) -> int:
    return max(values) if values else 0


def unique_join(values: list[str]) -> str:
    uniq = [value for value in dict.fromkeys(values) if value]
    return ", ".join(uniq) if uniq else "-"


def summarize_case(case_id: str, metadata_path: Path) -> dict[str, object]:
    metadata = read_json(metadata_path)
    input_meta = parse_input_metadata(Path(metadata["input_file"]))
    pseudo_info = attach_pseudo_types(input_meta)
    stdout_text = Path(metadata["stdout_file"]).read_text(encoding="utf-8", errors="ignore")
    timings = parse_timing_sections(stdout_text)
    solver_path = parse_solver_path(stdout_text)
    subspace_rows = parse_trace_rows(Path(metadata["subspace_trace_file"]))
    hpsi_rows = parse_trace_rows(Path(metadata["hpsi_trace_file"]))
    bandsolver_rows = parse_trace_rows(Path(metadata["bandsolver_trace_file"]))

    prefix = str(input_meta["prefix"])
    hpsi_rows = [row for row in hpsi_rows if row.get("case_id") == prefix]
    bandsolver_rows = [row for row in bandsolver_rows if row.get("case_id") == prefix]

    electrons = timings.get("electrons", {})
    cbands = timings.get("c_bands", {})
    egterg = timings.get("*egterg", {})
    cgdiag = timings.get("*cgdiagg", {})
    hpsi_clock = timings.get("h_psi", {})
    general = timings.get("General routines", {})

    top_level_shares = share_map(electrons, ["c_bands", "sum_band", "v_of_rho", "mix_rho"])

    cbands_total = sum(float(item["wall_s"]) for item in cbands.values())
    if cbands_total > 0.0:
        cbands_breakdown = {
            "egterg_share": (
                sum_group(cbands, ["cegterg", "regterg"]) / cbands_total
            ),
            "cg_share": (
                sum_group(cbands, ["ccgdiagg", "rcgdiagg"]) / cbands_total
            ),
            "paro_share": (
                sum_group(cbands, ["paro_k", "paro_gamma", "paro_k_new", "paro_gamma_new"]) / cbands_total
            ),
            "rmm_share": (
                sum_group(cbands, ["crmmdiagg", "rrmmdiagg"]) / cbands_total
            ),
        }
    else:
        cbands_breakdown = {"egterg_share": 0.0, "cg_share": 0.0, "paro_share": 0.0, "rmm_share": 0.0}

    egterg_total = sum(float(item["wall_s"]) for item in egterg.values())
    if egterg_total > 0.0:
        egterg_breakdown = {
            "h_psi_share": float(egterg.get("h_psi", {}).get("wall_s", 0.0)) / egterg_total,
            "s_psi_share": float(egterg.get("s_psi", {}).get("wall_s", 0.0)) / egterg_total,
            "g_psi_share": float(egterg.get("g_psi", {}).get("wall_s", 0.0)) / egterg_total,
            "diag_share": (
                sum_group(egterg, ["cdiaghg", "rdiaghg"]) / egterg_total
            ),
        }
    else:
        egterg_breakdown = {"h_psi_share": 0.0, "s_psi_share": 0.0, "g_psi_share": 0.0, "diag_share": 0.0}

    hpsi_breakdown = {
        "vloc_psi_wall_s": float(hpsi_clock.get("vloc_psi", {}).get("wall_s", 0.0)),
        "calbec_wall_s": float(hpsi_clock.get("h_psi:calbec", {}).get("wall_s", 0.0)),
        "add_vuspsi_wall_s": float(hpsi_clock.get("add_vuspsi", {}).get("wall_s", 0.0)),
        "fft_wall_s": (
            float(general.get("fft", {}).get("wall_s", 0.0))
            + float(general.get("ffts", {}).get("wall_s", 0.0))
            + float(general.get("fftw", {}).get("wall_s", 0.0))
        ),
    }

    generalized_calls = [
        row for row in subspace_rows if float(row.get("s_identity_rel", 0.0)) > 1.0e-10
    ]
    generalized_ratio = (
        len(generalized_calls) / len(subspace_rows) if subspace_rows else 0.0
    )

    hpsi_ops = Counter(str(row["op"]) for row in hpsi_rows)
    bandsolver_ops = Counter(str(row["op"]) for row in bandsolver_rows)
    solver_counter = Counter(str(row["solver_family"]) for row in solver_path)
    if not solver_counter:
        solver_counter = Counter(str(row["solver_family"]) for row in bandsolver_rows)

    dominant_solver = solver_counter.most_common(1)[0][0] if solver_counter else "unknown"
    npw_samples = sorted({int(row["npw"]) for row in hpsi_rows + bandsolver_rows if "npw" in row})
    fft_dims = sorted(
        {
            (int(row["fft_nr1"]), int(row["fft_nr2"]), int(row["fft_nr3"]))
            for row in hpsi_rows + bandsolver_rows
            if "fft_nr1" in row
        }
    )
    nkb_values = sorted({int(row["nkb"]) for row in hpsi_rows + bandsolver_rows if "nkb" in row})
    okvan_values = sorted({bool(row["okvan"]) for row in hpsi_rows + bandsolver_rows if "okvan" in row})

    return {
        "case_id": case_id,
        "exit_code": int(metadata["exit_code"]),
        "input": input_meta,
        "pseudo_info": pseudo_info,
        "dominant_solver": dominant_solver,
        "solver_path_by_iter": solver_path,
        "solver_families_seen": list(solver_counter.keys()),
        "timings": timings,
        "top_level_shares": top_level_shares,
        "cbands_breakdown": cbands_breakdown,
        "egterg_breakdown": egterg_breakdown,
        "hpsi_breakdown": hpsi_breakdown,
        "cgdiag_present": bool(cgdiag),
        "subspace_calls": len(subspace_rows),
        "generalized_calls": len(generalized_calls),
        "generalized_ratio": generalized_ratio,
        "subspace_top_pairs": top_pairs(subspace_rows),
        "max_subspace_n": max_or_zero([int(row["n"]) for row in subspace_rows if "n" in row]),
        "max_subspace_m": max_or_zero([int(row["m"]) for row in subspace_rows if "m" in row]),
        "hpsi_call_count": int(hpsi_ops.get("h_psi", 0)),
        "spsi_call_count": int(hpsi_ops.get("s_psi", 0)),
        "bandsolver_trace_counts": dict(bandsolver_ops),
        "max_nbase": max_or_zero([int(row["nbase"]) for row in bandsolver_rows if "nbase" in row]),
        "max_notcnv": max_or_zero([int(row["notcnv"]) for row in bandsolver_rows if "notcnv" in row]),
        "npw_samples": npw_samples,
        "fft_dims": fft_dims,
        "nkb_values": nkb_values,
        "okvan_values": okvan_values,
        "paths": {
            "metadata": str(metadata_path),
            "input": str(input_meta["path"]),
            "stdout": str(metadata["stdout_file"]),
            "command": str(metadata_path.parent / "command.sh"),
            "subspace_trace": str(metadata["subspace_trace_file"]),
            "hpsi_trace": str(metadata["hpsi_trace_file"]),
            "bandsolver_trace": str(metadata["bandsolver_trace_file"]),
        },
    }


def parser_validation() -> dict[str, object]:
    references = {
        "graphene_relax_old": ROOT / "soft/qe-7.5/benchmark/graphene.relax.out",
        "fe_scf_old": ROOT / "soft/qe-7.5/benchmark/fe.scf.out",
        "h2_rerun": RESULTS_ROOT / "h2_tiny" / "stdout.out",
    }
    payload: dict[str, object] = {}
    for name, path in references.items():
        text = path.read_text(encoding="utf-8", errors="ignore")
        sections = parse_timing_sections(text)
        payload[name] = {
            "path": str(path),
            "has_electrons_section": "electrons" in sections,
            "has_cbands_section": "c_bands" in sections,
            "has_egterg_section": "*egterg" in sections,
            "has_hpsi_section": "h_psi" in sections,
            "solver_path_rows": len(parse_solver_path(text)),
        }
    return payload


def pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def fmt_pairs(pairs: list[dict[str, object]]) -> str:
    if not pairs:
        return "-"
    return ", ".join(f"({item['n']},{item['m']})x{item['count']}" for item in pairs)


def md_link(label: str, path: str) -> str:
    return f"[{label}]({path})"


def render_markdown(case_summaries: list[dict[str, object]], validation: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# QE Workload 复核数据摘要")
    lines.append("")
    lines.append("## 1. Case Matrix")
    lines.append("")
    lines.append("| case | atoms | functional | pseudo types | input diag | exit | dominant solver | generalized ratio | top (n,m) |")
    lines.append("| --- | ---: | --- | --- | --- | ---: | --- | ---: | --- |")
    for item in case_summaries:
        pseudo_types = unique_join([entry["pseudo_type"] for entry in item["pseudo_info"]])
        lines.append(
            "| {case_id} | {nat} | {functional} | {pseudo_types} | {diag} | {exit_code} | {solver} | {ratio} | {pairs} |".format(
                case_id=item["case_id"],
                nat=item["input"]["nat"],
                functional=item["input"]["functional"],
                pseudo_types=pseudo_types,
                diag=item["input"]["diagonalization_input"],
                exit_code=item["exit_code"],
                solver=item["dominant_solver"],
                ratio=pct(item["generalized_ratio"]),
                pairs=fmt_pairs(item["subspace_top_pairs"]),
            )
        )
    lines.append("")
    lines.append("## 2. Top-Level Timing Shares")
    lines.append("")
    lines.append("| case | c_bands | sum_band | v_of_rho | mix_rho | other |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for item in case_summaries:
        shares = item["top_level_shares"]
        lines.append(
            "| {case_id} | {c_bands} | {sum_band} | {v_of_rho} | {mix_rho} | {other} |".format(
                case_id=item["case_id"],
                c_bands=pct(shares["c_bands"]),
                sum_band=pct(shares["sum_band"]),
                v_of_rho=pct(shares["v_of_rho"]),
                mix_rho=pct(shares["mix_rho"]),
                other=pct(shares["other"]),
            )
        )
    lines.append("")
    lines.append("## 3. Solver / *egterg Breakdown")
    lines.append("")
    lines.append("| case | c_bands->*egterg | c_bands->cg | *egterg->h_psi | *egterg->diag | h_psi calls | s_psi calls | max nbase |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for item in case_summaries:
        cbands = item["cbands_breakdown"]
        egterg = item["egterg_breakdown"]
        lines.append(
            "| {case_id} | {egterg_share} | {cg_share} | {hpsi_share} | {diag_share} | {hpsi_calls} | {spsi_calls} | {max_nbase} |".format(
                case_id=item["case_id"],
                egterg_share=pct(cbands["egterg_share"]),
                cg_share=pct(cbands["cg_share"]),
                hpsi_share=pct(egterg["h_psi_share"]),
                diag_share=pct(egterg["diag_share"]),
                hpsi_calls=item["hpsi_call_count"],
                spsi_calls=item["spsi_call_count"],
                max_nbase=item["max_nbase"],
            )
        )
    lines.append("")
    lines.append("## 4. Traceability")
    lines.append("")
    for item in case_summaries:
        lines.append(f"### {item['case_id']}")
        lines.append(
            "input: {input}  command: {command}  stdout: {stdout}  subspace: {subspace}  hpsi: {hpsi}  bandsolver: {bandsolver}".format(
                input=md_link("input", item["paths"]["input"]),
                command=md_link("command", item["paths"]["command"]),
                stdout=md_link("stdout", item["paths"]["stdout"]),
                subspace=md_link("subspace", item["paths"]["subspace_trace"]),
                hpsi=md_link("hpsi", item["paths"]["hpsi_trace"]),
                bandsolver=md_link("bandsolver", item["paths"]["bandsolver_trace"]),
            )
        )
        lines.append("")
    lines.append("## 5. Parser Validation")
    lines.append("")
    lines.append("| reference | electrons | c_bands | *egterg | h_psi | solver rows |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    for name, item in validation.items():
        lines.append(
            "| {name} | {electrons} | {cbands} | {egterg} | {hpsi} | {solver_rows} |".format(
                name=name,
                electrons="yes" if item["has_electrons_section"] else "no",
                cbands="yes" if item["has_cbands_section"] else "no",
                egterg="yes" if item["has_egterg_section"] else "no",
                hpsi="yes" if item["has_hpsi_section"] else "no",
                solver_rows=item["solver_path_rows"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    case_summaries: list[dict[str, object]] = []
    for case_id in CASE_ORDER:
        metadata_path = args.results_root / case_id / "metadata.json"
        if not metadata_path.is_file():
            continue
        case_summaries.append(summarize_case(case_id, metadata_path))

    validation = parser_validation()
    payload = {"cases": case_summaries, "parser_validation": validation}
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    args.markdown_out.write_text(render_markdown(case_summaries, validation), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
