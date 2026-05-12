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
DEFAULT_CASE_DIR = ROOT / "docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp"
DEFAULT_OUT = ROOT / "docs/benchmarks/si8_scf_operator_load_experiment_plan.md"

COMPLEX_FP64_BYTES = 16
REAL_FP64_BYTES = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a SCF operator-load report from QE traces.")
    parser.add_argument(
        "case_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_CASE_DIR,
        help="Case directory that contains metadata.json, stdout.out, hpsi_trace.csv, bandsolver_trace.csv.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=DEFAULT_OUT,
        help="Where to write the Markdown report.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def parse_input_value(text: str, key: str) -> str | None:
    pattern = re.compile(rf"\b{re.escape(key)}\s*=\s*([^,\n]+)", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return value


def parse_input_file(path: Path) -> dict[str, int | float | str]:
    text = path.read_text(encoding="utf-8")
    return {
        "nat": int(float(parse_input_value(text, "nat") or "0")),
        "nbnd": int(float(parse_input_value(text, "nbnd") or "0")),
        "ecutwfc": float(parse_input_value(text, "ecutwfc") or "0"),
        "ecutrho": float(parse_input_value(text, "ecutrho") or "0"),
        "prefix": parse_input_value(text, "prefix") or path.stem,
    }


def parse_stdout(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    data: dict[str, object] = {
        "kpoints": 0,
        "npw": 0,
        "dense_g": 0,
        "fft": (0, 0, 0),
        "beta_l": [],
        "timings": {},
    }

    k_match = re.search(r"number of k points=\s*(\d+)", text)
    if k_match:
        data["kpoints"] = int(k_match.group(1))

    g_match = re.search(
        r"Dense\s+grid:\s*(\d+) G-vectors\s+FFT dimensions:\s*\(\s*(\d+),\s*(\d+),\s*(\d+)\)",
        text,
    )
    if g_match:
        data["dense_g"] = int(g_match.group(1))
        data["fft"] = (int(g_match.group(2)), int(g_match.group(3)), int(g_match.group(4)))

    pw_match = re.search(r"Sum\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)", text)
    if pw_match:
        data["npw"] = int(pw_match.group(1))

    beta_l = [int(match.group(1)) for match in re.finditer(r"l\(\d+\)\s*=\s*(\d+)", text)]
    data["beta_l"] = beta_l

    timing_re = re.compile(
        r"^\s*(?P<name>[A-Za-z0-9_*:+-]+)\s*:\s*"
        r"(?P<cpu>[0-9.]+)s CPU\s*"
        r"(?P<wall>[0-9.]+)s WALL\s*\(\s*(?P<calls>\d+) calls\)",
        re.MULTILINE,
    )
    timings: dict[str, dict[str, float | int]] = {}
    for match in timing_re.finditer(text):
        timings[match.group("name")] = {
            "cpu": float(match.group("cpu")),
            "wall": float(match.group("wall")),
            "calls": int(match.group("calls")),
        }
    data["timings"] = timings
    return data


def binary_size(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    amount = float(value)
    idx = 0
    while amount >= 1024.0 and idx < len(units) - 1:
        amount /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(amount)} {units[idx]}"
    return f"{amount:.2f} {units[idx]}"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_float(value: float) -> str:
    if value >= 1e9:
        return f"{value / 1e9:.3f} G"
    if value >= 1e6:
        return f"{value / 1e6:.3f} M"
    if value >= 1e3:
        return f"{value / 1e3:.3f} K"
    return f"{value:.0f}"


def complex_bytes(rows: int, cols: int) -> int:
    return rows * cols * COMPLEX_FP64_BYTES


def real_bytes(rows: int, cols: int = 1) -> int:
    return rows * cols * REAL_FP64_BYTES


def fft_flops(nfft: int) -> float:
    return 5.0 * nfft * math.log2(max(2, nfft))


def hpsi_metrics(npw: int, nkb: int, nfft: int, m: int) -> dict[str, int | float]:
    return {
        "psi_g_bytes": complex_bytes(npw, m),
        "psi_r_bytes": complex_bytes(nfft, m),
        "bec_bytes": complex_bytes(nkb, m),
        "out_bytes": complex_bytes(npw, m),
        "kinetic_ops": npw * m,
        "local_fft_count": 2 * m,
        "local_pointwise_ops": nfft * m,
        "proj_macs": npw * nkb * m,
        "coeff_ops": nkb * nkb * m,
        "reconstruct_macs": npw * nkb * m,
        "real_flops": (
            2 * npw * m
            + 2 * m * fft_flops(nfft)
            + 2 * nfft * m
            + 8 * npw * nkb * m
            + 4 * nkb * nkb * m
            + 8 * npw * nkb * m
            + 4 * npw * m
        ),
    }


def spsi_metrics(npw: int, nkb: int, m: int) -> dict[str, int | float]:
    return {
        "psi_g_bytes": complex_bytes(npw, m),
        "bec_bytes": complex_bytes(nkb, m),
        "out_bytes": complex_bytes(npw, m),
        "proj_macs": npw * nkb * m,
        "coeff_ops": nkb * nkb * m,
        "reconstruct_macs": npw * nkb * m,
        "real_flops": 8 * npw * nkb * m + 4 * nkb * nkb * m + 8 * npw * nkb * m + 4 * npw * m,
    }


def expand_metrics(npw: int, n: int, p: int) -> dict[str, int | float]:
    n_prev = n - p
    complex_macs = 2 * npw * (n_prev * p + p * p)
    return {
        "n_prev": n_prev,
        "complex_macs": complex_macs,
        "real_flops": 8 * complex_macs,
        "subspace_bytes": 2 * complex_bytes(n, n),
    }


def diag_metrics(n: int, m: int) -> dict[str, int | float]:
    return {
        "matrix_bytes": 2 * complex_bytes(n, n),
        "output_bytes": complex_bytes(n, m) + real_bytes(m),
        "real_flops_est": 15.0 * (n ** 3),
    }


def refresh_metrics(npw: int, n: int, m: int) -> dict[str, int | float]:
    return {
        "basis_bytes_in": 3 * complex_bytes(npw, n) + complex_bytes(n, m),
        "basis_bytes_out": 3 * complex_bytes(npw, m),
        "real_flops": 3 * 8 * npw * n * m,
    }


def rho_metrics(npw: int, nbnd: int, nfft: int) -> dict[str, int | float]:
    return {
        "psi_g_bytes": complex_bytes(npw, nbnd),
        "psi_r_bytes": complex_bytes(nfft, nbnd),
        "rho_bytes": real_bytes(nfft),
        "real_flops": nbnd * fft_flops(nfft) + 3 * nfft * nbnd + nfft * nbnd + nfft * (nbnd - 1),
    }


def mix_metrics(nfft: int) -> dict[str, int | float]:
    return {
        "grid_bytes_in": 2 * real_bytes(nfft),
        "grid_bytes_out": real_bytes(nfft),
        "real_flops": 3 * nfft,
    }


def veff_metrics(dense_g: int, nfft: int) -> dict[str, int | float]:
    return {
        "rho_bytes_in": real_bytes(nfft),
        "rho_g_bytes": complex_bytes(dense_g, 1),
        "veff_bytes_out": real_bytes(nfft),
        "real_flops_est": 2 * fft_flops(nfft) + 2 * dense_g + 6 * nfft,
    }


def build_iteration_sequences(hpsi_rows: list[dict[str, str]], bandsolver_rows: list[dict[str, str]]) -> dict[int, dict[str, object]]:
    data: dict[int, dict[str, object]] = defaultdict(lambda: {"hpsi_m": [], "expand": [], "diag": [], "refresh": []})
    for row in hpsi_rows:
        scf_iter = int(row["scf_iter"])
        if row["case_id"] == "unknown" or scf_iter <= 0 or row["op"] != "h_psi":
            continue
        data[scf_iter]["hpsi_m"].append(int(row["nbnd_or_m"]))
    for row in bandsolver_rows:
        scf_iter = int(row["scf_iter"])
        if scf_iter <= 0:
            continue
        op = row["op"]
        n = int(row["nbase"])
        notcnv = int(row["notcnv"])
        if op == "expand_basis":
            data[scf_iter]["expand"].append({"n": n, "p": notcnv, "n_prev": n - notcnv})
        elif op == "post_diag":
            data[scf_iter]["diag"].append({"n": n, "m": int(row["subspace_m"])})
        elif op == "refresh_basis":
            data[scf_iter]["refresh"].append({"n": n, "m": int(row["subspace_m"])})
    return dict(sorted(data.items()))


def build_iteration_timeline(bandsolver_rows: list[dict[str, str]]) -> dict[int, list[dict[str, int | str]]]:
    timeline: dict[int, list[dict[str, int | str]]] = defaultdict(list)
    for row in bandsolver_rows:
        scf_iter = int(row["scf_iter"])
        if scf_iter <= 0:
            continue
        timeline[scf_iter].append(
            {
                "call_id": int(row["call_id"]),
                "op": row["op"],
                "solver_iter": int(row["solver_iter"]),
                "n": int(row["nbase"]),
                "m": int(row["subspace_m"]),
                "notcnv": int(row["notcnv"]),
            }
        )
    for key in timeline:
        timeline[key].sort(key=lambda item: int(item["call_id"]))
    return dict(sorted(timeline.items()))


def summarize_iterations(sequences: dict[int, dict[str, object]], npw: int, nkb: int, nfft: int, nbnd: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scf_iter, item in sequences.items():
        h_total = sum(hpsi_metrics(npw, nkb, nfft, m)["real_flops"] for m in item["hpsi_m"])
        s_total = sum(spsi_metrics(npw, nkb, m)["real_flops"] for m in item["hpsi_m"])
        expand_total = sum(expand_metrics(npw, op["n"], op["p"])["real_flops"] for op in item["expand"])
        diag_total = sum(diag_metrics(op["n"], op["m"])["real_flops_est"] for op in item["diag"])
        refresh_total = sum(refresh_metrics(npw, op["n"], op["m"])["real_flops"] for op in item["refresh"])
        rows.append(
            {
                "scf_iter": scf_iter,
                "hpsi_calls": len(item["hpsi_m"]),
                "hpsi_m_sum": sum(item["hpsi_m"]),
                "hpsi_sequence": item["hpsi_m"],
                "max_subspace_n": max((op["n"] for op in item["diag"]), default=nbnd),
                "diag_calls": len(item["diag"]),
                "refresh_calls": len(item["refresh"]),
                "estimated_real_flops": h_total + s_total + expand_total + diag_total + refresh_total,
                "estimated_breakdown": {
                    "h_psi": h_total,
                    "s_psi": s_total,
                    "subspace_build": expand_total,
                    "reduced_diag": diag_total,
                    "basis_refresh": refresh_total,
                },
            }
        )
    return rows


def choose_nominal(rows: list[dict[str, object]]) -> dict[str, object]:
    target = statistics_median([int(row["hpsi_m_sum"]) for row in rows])
    return min(rows, key=lambda row: (abs(int(row["hpsi_m_sum"]) - target), int(row["scf_iter"])))


def statistics_median(values: list[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count % 2 == 1:
        return float(ordered[count // 2])
    mid = count // 2
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def sequence_text(values: list[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"


def timing_line(name: str, timings: dict[str, dict[str, float | int]]) -> str:
    if name not in timings:
        return "n/a"
    item = timings[name]
    wall = float(item["wall"])
    calls = int(item["calls"])
    avg_ms = 1000.0 * wall / max(1, calls)
    return f"{wall:.2f} s / {calls} calls ({avg_ms:.2f} ms/call)"


def markdown_report(
    case_dir: Path,
    input_meta: dict[str, int | float | str],
    stdout_meta: dict[str, object],
    iteration_rows: list[dict[str, object]],
    timelines: dict[int, list[dict[str, int | str]]],
) -> str:
    timings = stdout_meta["timings"]
    npw = int(stdout_meta["npw"])
    dense_g = int(stdout_meta["dense_g"])
    fft1, fft2, fft3 = stdout_meta["fft"]
    nfft = fft1 * fft2 * fft3
    nbnd = int(input_meta["nbnd"])
    nat = int(input_meta["nat"])
    kpoints = int(stdout_meta["kpoints"])
    beta_l = list(stdout_meta["beta_l"])
    beta_channels_per_atom = sum(2 * value + 1 for value in beta_l)
    nkb = nat * beta_channels_per_atom

    nominal = choose_nominal(iteration_rows)
    peak = max(iteration_rows, key=lambda row: int(row["hpsi_m_sum"]))

    h16 = hpsi_metrics(npw, nkb, nfft, nbnd)
    s16 = spsi_metrics(npw, nkb, nbnd)
    rho16 = rho_metrics(npw, nbnd, nfft)
    mix = mix_metrics(nfft)
    veff = veff_metrics(dense_g, nfft)

    lines: list[str] = []
    lines.append("# Si8 SCF 子循环算子负载实验方案与实例化结果")
    lines.append("")
    lines.append("## 1. 实验目标")
    lines.append("")
    lines.append("这份实验说明把 `8` 原子 `Si` 的一次 SCF 内循环拆成可规划的数据流模块，目标是回答三个问题：")
    lines.append("")
    lines.append("1. 每一步的核心算子到底处理多大的张量；")
    lines.append("2. 输入到该步和输出到下一步的数据量分别是多少；")
    lines.append("3. 哪些块值得放到 chip / CIM / FPGA 路径上，哪些块继续留在 host 更合理。")
    lines.append("")
    lines.append("这里选用 `si8_pbe_uspp` 作为主案例，而不是 `si8_pbe_nc`，因为它同时保留了：")
    lines.append("")
    lines.append("- generalized overlap (`s_psi`)；")
    lines.append("- ultrasoft nonlocal projector (`nkb = 144`)；")
    lines.append("- Davidson + reduced generalized eigensolver 这一条当前主线。")
    lines.append("")
    lines.append("## 2. 数据来源与复现实验")
    lines.append("")
    lines.append(f"- 输入文件：`{Path(case_dir, 'metadata.json').resolve()}` 记录的 `docs/qe_inputs/si8_pbe_uspp.in`")
    lines.append(f"- 运行产物目录：`{case_dir}`")
    lines.append(f"- 关键 trace：`{case_dir / 'hpsi_trace.csv'}`、`{case_dir / 'bandsolver_trace.csv'}`、`{case_dir / 'subspace_trace.csv'}`")
    lines.append("")
    lines.append("复现命令：")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 tools/benchmarks/analyze_qe_scf_operator_load.py \\")
    lines.append(f"  {case_dir} \\")
    lines.append("  --markdown-out docs/benchmarks/si8_scf_operator_load_experiment_plan.md")
    lines.append("```")
    lines.append("")
    lines.append("## 3. 基础维度")
    lines.append("")
    lines.append("| 量 | 数值 | 说明 |")
    lines.append("| --- | ---: | --- |")
    lines.append(f"| `nat` | {nat} | Si 原子数 |")
    lines.append(f"| `nbnd` | {nbnd} | Kohn-Sham 态数 |")
    lines.append(f"| `kpoints` | {kpoints} | 本例只有 `Γ` 网格上的 `1` 个 `k` 点，但 QE 仍走复数路径 |")
    lines.append(f"| `npw` | {fmt_int(npw)} | 波函数平面波系数个数 |")
    lines.append(f"| `dense G` | {fmt_int(dense_g)} | 电荷/势场 G 向量个数 |")
    lines.append(f"| `FFT grid` | `{fft1} × {fft2} × {fft3}` = {fmt_int(nfft)} | 实空间网格点数 |")
    lines.append(f"| `beta l list` | `{beta_l}` | 从当前 UPF 直接解析 |")
    lines.append(f"| `beta channels / atom` | {beta_channels_per_atom} | `sum(2l+1)` |")
    lines.append(f"| `nkb` | {fmt_int(nkb)} | `8 × 18 = 144`，是当前真实 pseudo 的值 |")
    lines.append("")
    lines.append("提醒：仓库里的旧 note `soft/qe-7.5/CIM_data_residency_analysis.md` 使用的是更早的一组 Si 参数，其中写的是 `nkb = 12`。那份 note 适合作为思路参考，但不应该再拿来做当前 `si8_pbe_uspp` 的定量规划。")
    lines.append("")
    lines.append("存储约定：")
    lines.append("")
    lines.append("- 复数 `FP64`：`16 B / element`")
    lines.append("- 实数 `FP64`：`8 B / element`")
    lines.append("")
    lines.append("因此本 case 中几个最关键的对象大小为：")
    lines.append("")
    lines.append("| 对象 | 维度 | 数据量 |")
    lines.append("| --- | --- | ---: |")
    lines.append(f"| `psi(G)` for `m = 16` | `{npw} × 16` complex | {binary_size(complex_bytes(npw, 16))} |")
    lines.append(f"| `psi(r)` on FFT grid | `{nfft} × 16` complex | {binary_size(complex_bytes(nfft, 16))} |")
    lines.append(f"| `Veff(r)` | `{nfft}` real | {binary_size(real_bytes(nfft))} |")
    lines.append(f"| `beta(G)` | `{npw} × {nkb}` complex | {binary_size(complex_bytes(npw, nkb))} |")
    lines.append(f"| `D` or `Q` coeff | `{nkb} × {nkb}` real | {binary_size(real_bytes(nkb, nkb))} |")
    lines.append(f"| `H_sub` or `S_sub` worst case | `32 × 32` complex | {binary_size(complex_bytes(32, 32))} |")
    lines.append("")
    lines.append("## 4. Trace 观察到的 SCF 结构")
    lines.append("")
    lines.append("从 `stdout.out` 和 `bandsolver_trace.csv` 可以看到：")
    lines.append("")
    lines.append(f"- `c_bands`: {timing_line('c_bands', timings)}")
    lines.append(f"- `cegterg`: {timing_line('cegterg', timings)}")
    lines.append(f"- `h_psi`: {timing_line('h_psi', timings)}")
    lines.append(f"- `s_psi`: {timing_line('s_psi', timings)}")
    lines.append(f"- `cdiaghg`: {timing_line('cdiaghg', timings)}")
    lines.append(f"- `v_of_rho`: {timing_line('v_of_rho', timings)}")
    lines.append(f"- `newd`: {timing_line('newd', timings)}")
    lines.append(f"- `mix_rho`: {timing_line('mix_rho', timings)}")
    lines.append("")
    lines.append("这说明：")
    lines.append("")
    lines.append("- band solver 仍是单个 SCF 步的主块；")
    lines.append("- `h_psi/s_psi` 的 operator application 远重于 reduced diagonalization；")
    lines.append("- `newd` 在 USPP 路径下也不轻，但它更像 host/FPGA companion path，而不是第一优先的 chip primitive。")
    lines.append("")
    lines.append("## 5. 单个算子的接口、维度与计算量")
    lines.append("")
    lines.append("下面优先给出最值得建数据流的 operator 级接口。`m = 16` 对应初始 block / full-band block，是这条路径的设计基准。")
    lines.append("")
    lines.append("### 5.1 `rho -> Veff` 势场构造")
    lines.append("")
    lines.append("这一张表按数据依赖顺序展开 `rho -> Veff`，让 density 从实空间一路变成下一轮 `h_psi` 要消费的 `Veff(r)`。")
    lines.append("")
    lines.append("这里的记号变化规则是：")
    lines.append("")
    lines.append("- `rho(r)` 与 `rho(G)` 是同一个电荷密度对象，只是从实空间网格切到倒空间。")
    lines.append("- `V_H` 表示 Hartree 势，它由 `rho` 经过 Coulomb kernel 后得到，所以从 `rho -> V_H` 时变量名改变。")
    lines.append("- `V_xc` 表示交换关联局域势；`Veff` 则是在 `V_ion + V_H + V_xc` 合并后的总有效势。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `rho(G) = F rho(r)` | `rho(r)` `{nfft}` real = {binary_size(real_bytes(nfft))} | `rho(G)` `{dense_g}` complex = {binary_size(complex_bytes(dense_g, 1))} | 同一个 density，只是从 `(r)` 变到 `(G)` | `1` 次 3D FFT |")
    lines.append(f"| 2 | `V_H(G) = K_H(G) rho(G)` | `rho(G)` `{dense_g}` complex | `V_H(G)` `{dense_g}` complex = {binary_size(complex_bytes(dense_g, 1))} | 乘上 Coulomb kernel 后，物理量从 density 变成 Hartree potential，所以 `rho -> V_H` | `{fmt_int(2 * dense_g)}` real ops |")
    lines.append(f"| 3 | `V_H(r) = F^{{-1}} V_H(G)` | `V_H(G)` `{dense_g}` complex | `V_H(r)` `{nfft}` real = {binary_size(real_bytes(nfft))} | 同一个 Hartree 势，只是从 `(G)` 变回 `(r)` | `1` 次 3D iFFT |")
    lines.append(f"| 4 | `V_xc(r) = V_xc[rho(r)]` | `rho(r)` `{nfft}` real | `V_xc(r)` `{nfft}` real = {binary_size(real_bytes(nfft))} | 这里从 density 经过 local functional evaluation 变成交换关联势，所以 `rho -> V_xc` | `{fmt_int(nfft)}` local evaluations |")
    lines.append(f"| 5 | `Veff(r) = V_ion(r) + V_H(r) + V_xc(r)` | `V_ion(r)` + `V_H(r)` + `V_xc(r)` | `Veff(r)` `{nfft}` real = {binary_size(veff['veff_bytes_out'])} | 三个势项合并后改记为最终有效势 `Veff(r)` | `{fmt_int(2 * nfft)}` real adds |")
    lines.append("")
    lines.append(f"汇总：这一块的接口非常规整，输入/输出都只是一个 `{nfft}` 点实数网格，输出 `Veff(r)` 约 {binary_size(veff['veff_bytes_out'])}。")
    lines.append("")
    lines.append("### 5.2 `h_psi`：`H psi = y_T + y_eff + y_NL`")
    lines.append("")
    lines.append("这一张表按 **数据依赖 / 数学逻辑顺序** 展开 `h_psi`，不是按底层 kernel 是否能并行重叠来排序。")
    lines.append("这样写的目的，是让每一个中间量都能显式接到下一步，方便你直接拿去做 dataflow 和 buffer 规划。")
    lines.append("")
    lines.append("先说明这里的记号为什么会变化：")
    lines.append("")
    lines.append("- `psi(G)` 表示波函数在平面波系数域；`(G)` 是 reciprocal-space / plane-wave 域。")
    lines.append("- `psi(r)` 表示同一批波函数经过 iFFT 后落在实空间网格；对象还是同一批波函数，所以保留 `psi`，只把域从 `(G)` 改成 `(r)`。")
    lines.append("- `y_T / y_eff / y_NL` 表示哈密顿量三项贡献；一旦某个量不再是“原始波函数”，就从 `psi` 改记为 `y_*`。")
    lines.append("- `bec`、`d` 是 projector coefficient 域里的中间量；它们已经不是 `npw × m` 的波函数块，所以单独改名。")
    lines.append("")
    lines.append("还要注意：同一份 `psi(G)` 会分叉到三条支路——kinetic、local-potential、nonlocal-projector——最后再在 `G` 域汇合成 `Hpsi(G)`。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `m = 16` 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `y_T(G) = T psi(G)` | `psi(G)` `{npw} × 16` = {binary_size(h16['psi_g_bytes'])} | `y_T(G)` `{npw} × 16` = {binary_size(h16['out_bytes'])} | 还在 `G` 域，但内容已经从“波函数”变成“动能项贡献”，所以 `psi -> y_T` | `{fmt_int(int(h16['kinetic_ops']))}` complex-scale |")
    lines.append(f"| 2 | `psi(r) = F^{{-1}} psi(G)` | `psi(G)` `{npw} × 16` | `psi(r)` `{nfft} × 16` = {binary_size(h16['psi_r_bytes'])} | 对象还是同一批波函数，所以保留 `psi`；只是在括号里把域从 `(G)` 改成 `(r)` | `{int(h16['local_fft_count']) // 2}` 次 3D iFFT |")
    lines.append(f"| 3 | `y_eff(r) = Veff(r) ⊙ psi(r)` | `psi(r)` + `Veff(r)` | `y_eff(r)` `{nfft} × 16` = {binary_size(h16['psi_r_bytes'])} | 乘上局域势后，它不再是原始 `psi`，而是局域势贡献，所以改记为 `y_eff(r)` | `{fmt_int(int(h16['local_pointwise_ops']))}` pointwise |")
    lines.append(f"| 4 | `y_eff(G) = F y_eff(r)` | `y_eff(r)` `{nfft} × 16` | `y_eff(G)` `{npw} × 16` = {binary_size(h16['out_bytes'])} | 这里只改域，不改物理含义；`y_eff` 从实空间贡献返回 `G` 域贡献 | `{int(h16['local_fft_count']) // 2}` 次 3D FFT |")
    lines.append(f"| 5 | `bec = beta^H psi(G)` | `beta(G)` `{npw} × {nkb}` + `psi(G)` | `bec` `{nkb} × 16` = {binary_size(h16['bec_bytes'])} | 输出已不是波函数网格，而是 projector coefficient block，所以改名为 `bec` | `{fmt_int(int(h16['proj_macs']))}` complex MAC |")
    lines.append(f"| 6 | `d = D bec` | `bec` `{nkb} × 16` | `d` `{nkb} × 16` = {binary_size(h16['bec_bytes'])} | 这里施加的是非局域系数矩阵 `D`；输出变成另一组非局域权重，所以 `bec -> d` | `{fmt_int(int(h16['coeff_ops']))}` coeff ops |")
    lines.append(f"| 7 | `y_NL(G) = beta d` | `beta(G)` `{npw} × {nkb}` + `d` `{nkb} × 16` | `y_NL(G)` `{npw} × 16` = {binary_size(h16['out_bytes'])} | 从 projector coefficient 重新展回 `G` 域的非局域贡献，所以改记为 `y_NL(G)` | `{fmt_int(int(h16['reconstruct_macs']))}` complex MAC |")
    lines.append(f"| 8 | `Hpsi(G) = y_T(G) + y_eff(G) + y_NL(G)` | 三个 `{npw} × 16` block | `Hpsi(G)` `{npw} × 16` = {binary_size(h16['out_bytes'])} | 三条支路都回到 `G` 域后求和，得到最终的哈密顿量作用结果 `Hpsi(G)` | `{fmt_int(4 * npw * 16)}` real ops 级别 |")
    lines.append("")
    lines.append(f"按上面 `1 -> 8` 的逻辑链路累计，`m = 16` 的一次 `h_psi` 总量约为 `{fmt_float(float(h16['real_flops']))}` real-flop 量级（含 FFT 估算）。")
    lines.append(f"这一步最需要注意的数据膨胀发生在 step `2`：`psi(G)` 从 {binary_size(h16['psi_g_bytes'])} 经过 FFT 网格展开后，会暂时变成 `psi(r)` {binary_size(h16['psi_r_bytes'])}。")
    lines.append("如果后面要映射到硬件流水线，可以把 step `1`、`2-4`、`5-7` 看成三条可部分重叠的支路；但为了保证语义清楚，这里仍按依赖顺序写。")
    lines.append("")
    lines.append("### 5.3 `s_psi`：广义重叠算子")
    lines.append("")
    lines.append("这一张表把 `s_psi` 也完全按依赖顺序展开。它和 `h_psi` 的 nonlocal 路径很像，只是这里用的是 overlap projector，而不是 Hamiltonian 非局域系数。")
    lines.append("")
    lines.append("记号变化规则：")
    lines.append("")
    lines.append("- `bec` 仍表示 `beta^H psi` 形成的 projector coefficient。")
    lines.append("- `d_S` 表示 overlap 矩阵 `Q` 作用后的系数；为了和 `h_psi` 里的 `d = D bec` 区分，这里显式写成 `d_S`。")
    lines.append("- `Spsi_corr(G)` 表示 overlap correction 项；加回原始 `psi(G)` 后才得到最终 `Spsi(G)`。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `m = 16` 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `bec = beta^H psi(G)` | `beta(G)` `{npw} × {nkb}` + `psi(G)` `{npw} × 16` = {binary_size(s16['psi_g_bytes'])} | `bec` `{nkb} × 16` = {binary_size(s16['bec_bytes'])} | 输出从波函数块变成 projector coefficient block，所以改名为 `bec` | `{fmt_int(int(s16['proj_macs']))}` complex MAC |")
    lines.append(f"| 2 | `d_S = Q bec` | `bec` `{nkb} × 16` | `d_S` `{nkb} × 16` = {binary_size(s16['bec_bytes'])} | 经过 overlap 系数矩阵 `Q` 后，得到另一组 correction coefficient，所以 `bec -> d_S` | `{fmt_int(int(s16['coeff_ops']))}` coeff ops |")
    lines.append(f"| 3 | `Spsi_corr(G) = beta d_S` | `beta(G)` `{npw} × {nkb}` + `d_S` `{nkb} × 16` | `Spsi_corr(G)` `{npw} × 16` = {binary_size(s16['out_bytes'])} | 从 coefficient 域重新展回 `G` 域的重叠修正项，所以改名为 `Spsi_corr(G)` | `{fmt_int(int(s16['reconstruct_macs']))}` complex MAC |")
    lines.append(f"| 4 | `Spsi(G) = psi(G) + Spsi_corr(G)` | `psi(G)` + `Spsi_corr(G)` | `Spsi(G)` `{npw} × 16` = {binary_size(s16['out_bytes'])} | correction 加回原始波函数后，得到最终 overlap 作用结果 `Spsi(G)` | `{fmt_int(4 * npw * 16)}` real ops 级别 |")
    lines.append("")
    lines.append(f"按上面 `1 -> 4` 的链路累计，`m = 16` 的一次 `s_psi` 总量约为 `{fmt_float(float(s16['real_flops']))}` real-flop 量级。")
    lines.append("`s_psi` 的优点是没有 FFT；它更像典型的 projector-dense kernel。")
    lines.append("")
    lines.append("### 5.4 basis expansion: 构建 `H_sub / S_sub`")
    lines.append("")
    lines.append("设当前保留 basis 为 `n_prev`，新增修正向量数为 `p`，则扩展后 `n = n_prev + p`。下面把一次 `expand_basis` call 展开成显式 reduced-matrix 组装步骤。")
    lines.append("")
    lines.append("这里的符号变化规则是：")
    lines.append("")
    lines.append("- `Psi[npw, n_prev]` 是旧 basis；`P[npw, p]` 是这一轮新加进来的修正向量块。")
    lines.append("- `HP` / `SP` 表示这些新向量已经分别经过 `H` 和 `S` 作用。")
    lines.append("- `G_H`、`B_H` 是 reduced Hamiltonian 的两个新块；`G_S`、`B_S` 则是 reduced overlap 的两个新块。")
    lines.append("- `H_sub`、`S_sub` 是最终拼装好的 `n × n` 子空间矩阵。")
    lines.append("")
    lines.append("下面以第一次 expand 为例：`n_prev = 16`，`p = 16`，扩展后 `n = 32`。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `G_H = Psi^H HP` | `Psi` `{npw} × 16` + `HP` `{npw} × 16` | `G_H` `16 × 16` = {binary_size(complex_bytes(16, 16))} | 从 full-space block 投影到 reduced coupling block，所以改为 `G_H` | `{fmt_int(npw * 16 * 16)}` complex MAC |")
    lines.append(f"| 2 | `B_H = P^H HP` | `P` `{npw} × 16` + `HP` `{npw} × 16` | `B_H` `16 × 16` = {binary_size(complex_bytes(16, 16))} | 这是新增块在 Hamiltonian 下的自耦合，所以写成底部块 `B_H` | `{fmt_int(npw * 16 * 16)}` complex MAC |")
    lines.append(f"| 3 | `H_sub = [[H_old, G_H], [G_H^H, B_H]]` | `H_old` `16 × 16` + `G_H` + `B_H` | `H_sub` `32 × 32` = {binary_size(complex_bytes(32, 32))} | 多个 reduced block 拼成最终 Hamiltonian 子空间矩阵，所以统一记为 `H_sub` | `{fmt_int(32 * 32)}` element assembly |")
    lines.append(f"| 4 | `G_S = Psi^H SP` | `Psi` `{npw} × 16` + `SP` `{npw} × 16` | `G_S` `16 × 16` = {binary_size(complex_bytes(16, 16))} | 与 step 1 同理，但这是 overlap coupling block，所以写成 `G_S` | `{fmt_int(npw * 16 * 16)}` complex MAC |")
    lines.append(f"| 5 | `B_S = P^H SP` | `P` `{npw} × 16` + `SP` `{npw} × 16` | `B_S` `16 × 16` = {binary_size(complex_bytes(16, 16))} | 与 step 2 同理，但对应 overlap 自耦合块 | `{fmt_int(npw * 16 * 16)}` complex MAC |")
    lines.append(f"| 6 | `S_sub = [[S_old, G_S], [G_S^H, B_S]]` | `S_old` `16 × 16` + `G_S` + `B_S` | `S_sub` `32 × 32` = {binary_size(complex_bytes(32, 32))} | 多个 reduced block 拼成最终 overlap 子空间矩阵，所以统一记为 `S_sub` | `{fmt_int(32 * 32)}` element assembly |")
    lines.append("")
    lines.append("在 `Si8` 的第一次 expand (`n_prev = 16`, `p = 16`, `n = 32`) 上：")
    lines.append("")
    first_expand = expand_metrics(npw, 32, 16)
    lines.append(f"- 输出两个小矩阵 `H_sub + S_sub` 总共只有 {binary_size(int(first_expand['subspace_bytes']))}")
    lines.append(f"- 但乘加量已经是 `{fmt_int(int(first_expand['complex_macs']))}` complex MAC")
    lines.append("")
    lines.append("### 5.5 reduced generalized diagonalization `cdiaghg`")
    lines.append("")
    lines.append("trace 只能直接看到顶层 `cdiaghg` 调用；下面这张表给的是**用于架构分析的数学展开**，把 generalized eigensolver 内部逻辑显式写出来。")
    lines.append("")
    lines.append("这里的符号变化规则是：")
    lines.append("")
    lines.append("- `L` 是 `S_sub` 的 Cholesky factor；它不再是原始 overlap 矩阵，所以从 `S_sub -> L`。")
    lines.append("- `A_std` 是把 generalized 问题标准化后的 Hermitian 小矩阵。")
    lines.append("- `Y` 是标准问题的本征向量；`C` 是回代后的 generalized 系数矩阵。")
    lines.append("")
    lines.append("下面以峰值 `n = 32`、`m = 16` 为例展开。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `S_sub = L L^H` | `S_sub` `32 × 32` = {binary_size(complex_bytes(32, 32))} | `L` `32 × 32` = {binary_size(complex_bytes(32, 32))} | 对 overlap 小矩阵做分解后，得到 factor `L`，所以 `S_sub -> L` | `O(32^3)` |")
    lines.append(f"| 2 | `A_std = L^{{-1}} H_sub L^{{-H}}` | `H_sub` `32 × 32` + `L` `32 × 32` | `A_std` `32 × 32` = {binary_size(complex_bytes(32, 32))} | generalized 问题被标准化后，得到新的标准 Hermitian 矩阵 `A_std` | `O(32^3)` |")
    lines.append(f"| 3 | `A_std Y = Y Lambda` | `A_std` `32 × 32` | `Y` `32 × 16` = {binary_size(complex_bytes(32, 16))} + `Lambda` `16` = {binary_size(real_bytes(16))} | 在标准问题里输出的是标准坐标系本征向量 `Y` 和本征值 `Lambda` | `O(32^3)` |")
    lines.append(f"| 4 | `C_raw = L^{{-H}} Y` | `L` `32 × 32` + `Y` `32 × 16` | `C_raw` `32 × 16` = {binary_size(complex_bytes(32, 16))} | 把标准问题本征向量回代到 generalized 坐标，所以 `Y -> C_raw` | `O(32^2 * 16)` |")
    lines.append(f"| 5 | `C = normalize_S(C_raw)` | `C_raw` `32 × 16` + `S_sub` `32 × 32` | `C` `32 × 16` = {binary_size(complex_bytes(32, 16))} + `Lambda` `16` = {binary_size(real_bytes(16))} | 最终做 `S`-度量归一化后，得到可以直接回到 full space 的 reduced coefficient `C` | `O(32^2 * 16)` |")
    lines.append("")
    lines.append(f"峰值 `n = 32` 时，输入矩阵总共只有 {binary_size(diag_metrics(32, 16)['matrix_bytes'])}，输出 `C + Lambda` 也只有 {binary_size(diag_metrics(32, 16)['output_bytes'])}。")
    lines.append("")
    lines.append("### 5.6 basis refresh / residual update")
    lines.append("")
    lines.append("在 generalized Davidson 路径里，reduced solve 之后不会立刻结束；还要把 reduced coefficient 回到 full space，再形成 residual 并产生下一批修正向量。")
    lines.append("")
    lines.append("这里的符号变化规则是：")
    lines.append("")
    lines.append("- `X` 表示刷新后的 Ritz vector block；`HX`、`SX` 则是它们在 `H` / `S` 作用下的 companion block。")
    lines.append("- `R` 是 residual block；`P_raw` 是预条件后的候选修正向量；`P` 是正交化后的最终扩展块。")
    lines.append("")
    lines.append("下面用峰值型 `n = 32`、`m = 16` 展开。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `X = Psi C` | `Psi` `{npw} × 32` = {binary_size(complex_bytes(npw, 32))} + `C` `32 × 16` = {binary_size(complex_bytes(32, 16))} | `X` `{npw} × 16` = {binary_size(complex_bytes(npw, 16))} | reduced coefficient 回到 full space 后，得到新的 Ritz vectors `X` | `{fmt_float(8.0 * npw * 32 * 16)}` real-flop 级别 |")
    lines.append(f"| 2 | `HX = HPsi C`, `SX = SPsi C` | `HPsi/SPsi` `{npw} × 32` + `C` `32 × 16` | `HX/SX` 各 `{npw} × 16` = {binary_size(complex_bytes(npw, 16))} | 与 `X` 对应的两个 companion block 单独命名为 `HX`、`SX` | `{fmt_float(2.0 * 8.0 * npw * 32 * 16)}` real-flop 级别 |")
    lines.append(f"| 3 | `R = HX - SX Lambda` | `HX` `{npw} × 16` + `SX` `{npw} × 16` + `Lambda` `16` | `R` `{npw} × 16` = {binary_size(complex_bytes(npw, 16))} | 构造残差后，变量从 operator result 变成 residual，所以改记为 `R` | `{fmt_int(12 * npw * 16)}` real ops 级别 |")
    lines.append(f"| 4 | `P_raw = M^{{-1}} R` | `R` `{npw} × 16` | `P_raw` `{npw} × 16` = {binary_size(complex_bytes(npw, 16))} | 经过预条件器后，残差变成候选修正向量，所以 `R -> P_raw` | `O(npw * m)` |")
    lines.append(f"| 5 | `P = ortho_S(P_raw; X)` | `P_raw` `{npw} × 16` + `X/SX` `{npw} × 16` | `P` `{npw} × p`，其中 `p <= 16` | 经过 `S`-正交化后，得到真正能拿去扩展 basis 的块 `P` | `O(npw * m * p)` |")
    lines.append("")
    lines.append("这部分的张量尺寸仍然是 `npw × n` 级别，所以它们更像 `chip/FPGA` 边界上的 companion GEMM，而不是新的小矩阵主热点。")
    lines.append("")
    lines.append("### 5.7 `psi -> rho_out` 电荷组装")
    lines.append("")
    lines.append("这里也按依赖顺序把电荷组装完全展开。当前 case 只有 `1` 个 `k` 点，所以 `k` 权重不会引入额外分支。")
    lines.append("")
    lines.append("记号变化规则：")
    lines.append("")
    lines.append("- `psi(G)` 与 `psi(r)` 仍然是同一批波函数，只是域不同。")
    lines.append("- `q_n(r)` 表示每个 band 的电子密度贡献；`u_n(r)` 表示再乘上占据数后的加权贡献。")
    lines.append("- 最后对 band 维求和后，得到总电荷密度 `rho_out(r)`。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `nbnd = 16` 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `psi(r) = F^{{-1}} psi(G)` | `psi(G)` `{npw} × 16` = {binary_size(rho16['psi_g_bytes'])} | `psi(r)` `{nfft} × 16` = {binary_size(rho16['psi_r_bytes'])} | 同一批波函数，只是从 `(G)` 变到 `(r)` | `16` 次 3D iFFT |")
    lines.append(f"| 2 | `q_n(r) = |psi_n(r)|^2` | `psi(r)` `{nfft} × 16` | `q_n(r)` `{nfft} × 16` real = {binary_size(real_bytes(nfft, nbnd))} | 从复振幅变成每个 band 的实数密度贡献，所以 `psi -> q_n` | `{fmt_int(3 * nfft * nbnd)}` real ops |")
    lines.append(f"| 3 | `u_n(r) = f_n q_n(r)` | `q_n(r)` `{nfft} × 16` + `f_n` `16` | `u_n(r)` `{nfft} × 16` real = {binary_size(real_bytes(nfft, nbnd))} | 乘上占据数后，band-density contribution 变成 weighted contribution，所以 `q_n -> u_n` | `{fmt_int(nfft * nbnd)}` real ops |")
    lines.append(f"| 4 | `rho_out(r) = sum_n u_n(r)` | `u_n(r)` `{nfft} × 16` | `rho_out(r)` `{nfft}` real = {binary_size(rho16['rho_bytes'])} | 对 band 维求和后，得到总输出密度，所以 `u_n -> rho_out` | `{fmt_int(nfft * (nbnd - 1))}` real ops |")
    lines.append("")
    lines.append("### 5.8 `mix_rho`")
    lines.append("")
    lines.append("这个 case 的输入文件使用的是 `mixing_mode = plain`，所以这里可以把混合路径写得很直接。")
    lines.append("")
    lines.append("记号变化规则：")
    lines.append("")
    lines.append("- `rho_in(r)` 表示本轮进入 mixing 的旧密度。")
    lines.append("- `delta_rho(r)` 是新旧密度差；`rho_new(r)` 是线性混合后的下一轮输入密度。")
    lines.append("")
    lines.append("| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |")
    lines.append("| --- | --- | --- | --- | --- | ---: |")
    lines.append(f"| 1 | `delta_rho(r) = rho_out(r) - rho_in(r)` | `rho_out(r)` + `rho_in(r)` = {binary_size(mix['grid_bytes_in'])} | `delta_rho(r)` `{nfft}` real = {binary_size(real_bytes(nfft))} | 新旧密度做差后，变量从 density 变成 density residual，所以改记为 `delta_rho` | `{fmt_int(nfft)}` real subs |")
    lines.append(f"| 2 | `beta_delta(r) = beta delta_rho(r)` | `delta_rho(r)` `{nfft}` real | `beta_delta(r)` `{nfft}` real = {binary_size(real_bytes(nfft))} | 经过 mixing 系数 `beta` 缩放后，残差变成可加回的 mixed increment | `{fmt_int(nfft)}` real muls |")
    lines.append(f"| 3 | `rho_new(r) = rho_in(r) + beta_delta(r)` | `rho_in(r)` + `beta_delta(r)` | `rho_new(r)` `{nfft}` real = {binary_size(mix['grid_bytes_out'])} | 把混合增量加回旧密度后，得到下一轮 SCF 输入密度 `rho_new(r)` | `{fmt_int(nfft)}` real adds |")
    lines.append("")
    lines.append("## 6. 一整个 SCF 步的 trace 实例")
    lines.append("")
    lines.append("为了给 throughput / buffering 设计留出上界，下面同时给出一个 nominal step 和一个 peak step：")
    lines.append("")
    lines.append(f"- nominal step: SCF iter `{nominal['scf_iter']}`，`h_psi` block 序列为 `{sequence_text(nominal['hpsi_sequence'])}`")
    lines.append(f"- peak step: SCF iter `{peak['scf_iter']}`，`h_psi` block 序列为 `{sequence_text(peak['hpsi_sequence'])}`")
    lines.append("")
    lines.append("| SCF iter | `h_psi` calls | `sum(m)` | `diag` calls | max `n` | 估算总计算量 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in iteration_rows:
        lines.append(
            f"| {row['scf_iter']} | {row['hpsi_calls']} | {row['hpsi_m_sum']} | {row['diag_calls']} | {row['max_subspace_n']} | {fmt_float(float(row['estimated_real_flops']))} real-flop 级别 |"
        )
    lines.append("")
    lines.append("其中最值得拿来做峰值带宽设计的是 SCF iter `6`：")
    lines.append("")
    lines.append(f"- `h_psi/s_psi` 的 block 序列：`{sequence_text(peak['hpsi_sequence'])}`")
    lines.append(f"- 这一轮的 `h_psi + s_psi` 估算已经达到 `{fmt_float(float(peak['estimated_breakdown']['h_psi'] + peak['estimated_breakdown']['s_psi']))}` real-flop 量级")
    lines.append(f"- 同一轮的 reduced diagonalization 仍只有 `{fmt_float(float(peak['estimated_breakdown']['reduced_diag']))}` 量级")
    lines.append("")
    lines.append("结论很直接：峰值设计应以 repeated operator application 为准，而不是以 `32 × 32` 小矩阵对角化为准。")
    lines.append("")
    lines.append("### 6.1 nominal SCF step 的显式数据流版")
    lines.append("")
    lines.append(
        f"下面把 nominal step（SCF iter `{nominal['scf_iter']}`）按 **trace runtime order + 数学依赖** 展开。"
        "`init_basis / expand_basis / post_diag / refresh_basis / converged_exit` 是 trace 直接可见的控制事件；"
        "而 `X / R / P` 这一类中间对象是为了 dataflow 规划而显式补出来的。"
    )
    lines.append("")
    lines.append("这里的记号变化规则是：")
    lines.append("")
    lines.append("- `Psi_keep^{(i)}` 表示第 `i` 次 refresh 之后保留下来的 resident basis。")
    lines.append("- `P^{(i)}` 表示第 `i` 轮新增 correction block；`HP^{(i)}`、`SP^{(i)}` 是它的 companion operator blocks。")
    lines.append("- `H_sub^{(i)}`、`S_sub^{(i)}` 是第 `i` 轮 expanded subspace 矩阵。")
    lines.append("- `C^{(i)}`、`Lambda^{(i)}` 是 reduced solve 输出；回到 full space 后得到 `X^{(i)}`、`HX^{(i)}`、`SX^{(i)}`。")
    lines.append("")
    lines.append("| 阶段 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 下一步 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    nominal_timeline = timelines[int(nominal["scf_iter"])]
    nominal_blocks = list(nominal["hpsi_sequence"])
    nominal_init_block = nominal_blocks[0]
    lines.append(
        f"| init-1 | `Psi_keep^{{(0)}} = psi_init(G)` | `psi_init(G)` `{npw} × {nominal_init_block}` = {binary_size(complex_bytes(npw, nominal_init_block))} | `Psi_keep^{{(0)}}` `{npw} × {nominal_init_block}` | 原始输入 block 进入 band solver 后，变成初始 resident basis，所以改记为 `Psi_keep^{(0)}` | `init-2` |"
    )
    lines.append(
        f"| init-2 | `HPsi_keep^{{(0)}} = H Psi_keep^{{(0)}}`, `SPsi_keep^{{(0)}} = S Psi_keep^{{(0)}}` | `Psi_keep^{{(0)}}` `{npw} × {nominal_init_block}` | `HPsi_keep^{{(0)}}/SPsi_keep^{{(0)}}` 各 `{npw} × {nominal_init_block}` = {binary_size(complex_bytes(npw, nominal_init_block))} | 伴随 operator 作用后的 resident companion blocks 单独记为 `HPsi_keep` / `SPsi_keep` | `solver iter 1 / expand_basis` |"
    )
    block_index = 1
    for item in nominal_timeline:
        if item["op"] != "expand_basis":
            continue
        solver_iter = int(item["solver_iter"])
        block_m = nominal_blocks[block_index]
        block_index += 1
        n = int(item["n"])
        p = int(item["notcnv"])
        n_prev = n - p
        diag_item = next(
            entry
            for entry in nominal_timeline
            if entry["op"] == "post_diag" and entry["solver_iter"] == item["solver_iter"]
        )
        refresh_item = next(
            (entry for entry in nominal_timeline if entry["op"] == "refresh_basis" and entry["solver_iter"] == item["solver_iter"]),
            None,
        )
        next_block = nominal_blocks[block_index] if block_index < len(nominal_blocks) else None
        lines.append(
            f"| iter {solver_iter}-1 | `P^{{({solver_iter})}} -> [P^{{({solver_iter})}}, HP^{{({solver_iter})}}, SP^{{({solver_iter})}}]` | 前一轮 residual / precondition 路径输出，trace 可见 block size `m = {block_m}` | 三个 `{npw} × {block_m}` block，各 {binary_size(complex_bytes(npw, block_m))} | 新增 correction block 不再属于 retained basis，所以单独改记为 `P^{{(i)}}` | `iter {solver_iter}-2 / expand_basis` |"
        )
        lines.append(
            f"| iter {solver_iter}-2 | `build([Psi_keep^{{({solver_iter - 1})}}, P^{{({solver_iter})}}]) -> H_sub^{{({solver_iter})}}, S_sub^{{({solver_iter})}}` | retained basis `{npw} × {n_prev}` + new block `{npw} × {p}` | `H_sub^{{({solver_iter})}}/S_sub^{{({solver_iter})}}` 各 `{n} × {n}` = {binary_size(complex_bytes(n, n))} | full-space vectors 被投影到 reduced subspace，所以统一改记为 `H_sub` / `S_sub` | `iter {solver_iter}-3 / post_diag` |"
        )
        lines.append(
            f"| iter {solver_iter}-3 | `(H_sub^{{({solver_iter})}}, S_sub^{{({solver_iter})}}) -> (C^{{({solver_iter})}}, Lambda^{{({solver_iter})}})` | `H_sub^{{({solver_iter})}}/S_sub^{{({solver_iter})}}` `{n} × {n}` | `C^{{({solver_iter})}}` `{n} × 16` = {binary_size(complex_bytes(n, 16))} + `Lambda^{{({solver_iter})}}` `16` = {binary_size(real_bytes(16))}; `notcnv = {int(diag_item['notcnv'])}` | reduced eigensolver 输出不再是 basis block，而是 reduced coefficient + eigenvalue，所以改记为 `C/Lambda` | {'`iter ' + str(solver_iter) + '-4 / refresh_basis`' if refresh_item is not None else '`iter ' + str(solver_iter) + '-4 / converged_exit`'} |"
        )
        if refresh_item is not None:
            next_text = f"再经 residual / precondition / ortho 生成 `P^{{({solver_iter + 1})}}`，其 trace block size 为 `m = {next_block}`" if next_block is not None else "进入下一轮 residual 路径"
            lines.append(
                f"| iter {solver_iter}-4 | `C^{{({solver_iter})}} -> [X^{{({solver_iter})}}, HX^{{({solver_iter})}}, SX^{{({solver_iter})}}] -> [Psi_keep^{{({solver_iter})}}, HPsi_keep^{{({solver_iter})}}, SPsi_keep^{{({solver_iter})}}]` | expanded basis/operator blocks `{npw} × {n}` + `C^{{({solver_iter})}}` `{n} × 16` | refreshed resident state 三个 `{npw} × {int(refresh_item['n'])}` block，各 {binary_size(complex_bytes(npw, int(refresh_item['n'])))} | reduced coefficient 回到 full space 先形成 Ritz block `X/HX/SX`，再压回 retained basis resident state，所以 `C -> X -> Psi_keep` | {next_text} |"
            )
        else:
            lines.append(
                f"| iter {solver_iter}-4 | `C^{{({solver_iter})}} -> [X_conv^{{({solver_iter})}}, HX_conv^{{({solver_iter})}}, SX_conv^{{({solver_iter})}}]` | expanded basis/operator blocks `{npw} × {n}` + `C^{{({solver_iter})}}` `{n} × 16` | final converged blocks 三个 `{npw} × 16`，各 {binary_size(complex_bytes(npw, 16))} | 最后一轮不再 refresh，而是直接输出收敛 Ritz block，所以改记为 `X_conv/HX_conv/SX_conv` | `converged_exit / SCF step done` |"
            )
    lines.append("")
    lines.append("### 6.2 peak SCF step 的显式重复模式")
    lines.append("")
    lines.append(
        f"peak step（SCF iter `{peak['scf_iter']}`）内部一共跑了 `{peak['diag_calls']}` 次 reduced solve。"
        "它和 nominal step 走的是同一个数据流模板，只是 `notcnv` 下降更慢，所以 `expand -> diag -> refresh -> residual` 这组动作被重复了更多次。"
    )
    lines.append("")
    lines.append("peak step 的单轮模板仍然是：")
    lines.append("")
    lines.append("1. `P^{(i)}` 进入，并形成 `HP^{(i)}` / `SP^{(i)}`")
    lines.append("2. `[Psi_keep^{(i-1)}, P^{(i)}] -> H_sub^{(i)}, S_sub^{(i)}`")
    lines.append("3. `(H_sub^{(i)}, S_sub^{(i)}) -> (C^{(i)}, Lambda^{(i)})`")
    lines.append("4. `C^{(i)} -> X^{(i)}/HX^{(i)}/SX^{(i)} -> refresh or converged_exit`")
    lines.append("")
    lines.append("下面把 peak step 每一轮的尺寸变化显式列出，便于你做最坏情况 buffer / scheduler 规划。")
    lines.append("")
    lines.append("| solver iter | 新增 block `p` | expanded `n_prev + p -> n` | `diag` 后 `notcnv` | refresh? | 下一轮 block |")
    lines.append("| --- | ---: | --- | ---: | --- | ---: |")
    peak_timeline = timelines[int(peak["scf_iter"])]
    peak_blocks = list(peak["hpsi_sequence"])
    peak_index = 1
    for item in peak_timeline:
        if item["op"] != "expand_basis":
            continue
        solver_iter = int(item["solver_iter"])
        block_m = peak_blocks[peak_index]
        peak_index += 1
        n = int(item["n"])
        p = int(item["notcnv"])
        n_prev = n - p
        diag_item = next(
            entry
            for entry in peak_timeline
            if entry["op"] == "post_diag" and entry["solver_iter"] == item["solver_iter"]
        )
        refresh_item = next(
            (entry for entry in peak_timeline if entry["op"] == "refresh_basis" and entry["solver_iter"] == item["solver_iter"]),
            None,
        )
        next_block = peak_blocks[peak_index] if peak_index < len(peak_blocks) else 0
        diag_notcnv = int(diag_item["notcnv"])
        if refresh_item is not None:
            refresh_text = f"yes, back to n = {int(refresh_item['n'])}"
            next_block_text = str(next_block)
        elif diag_notcnv == 0:
            refresh_text = "no, converged_exit"
            next_block_text = "0"
        else:
            refresh_text = f"no, keep expanded n = {n}"
            next_block_text = str(next_block)
        lines.append(
            f"| {solver_iter} | {block_m} | `{n_prev} + {p} -> {n}` | {diag_notcnv} | {refresh_text} | {next_block_text} |"
        )
    lines.append("")
    lines.append("## 7. 面向数据流规划的建议")
    lines.append("")
    lines.append("### 7.1 第一优先：`h_psi / s_psi` 主数据通路")
    lines.append("")
    lines.append("建议把这条路拆成两个可以流水的域：")
    lines.append("")
    lines.append("1. `FFT + local potential` 域：处理 `psi(G) <-> psi(r)` 和 `Veff(r)` 点乘")
    lines.append("2. `projector` 域：处理 `beta^H psi -> coeff mix -> beta d`")
    lines.append("")
    lines.append("原因：")
    lines.append("")
    lines.append(f"- `beta(G)` 常量尺寸已经达到 {binary_size(complex_bytes(npw, nkb))}，足够值得做强复用；")
    lines.append(f"- `Veff(r)` 只有 {binary_size(real_bytes(nfft))}，更适合按 SCF step 级别装载并在多个 `h_psi` 调用间复用；")
    lines.append("- `h_psi` 同时含 FFT-heavy 和 projector-heavy 两类算子，带宽/访存模式并不一样，拆域比强行做一个单核更自然。")
    lines.append("")
    lines.append("### 7.2 第二优先：`Psi/HPsi/SPsi` 与 `C` 的 companion GEMM")
    lines.append("")
    lines.append("`refresh_basis` 和 `subspace_build` 的输入虽然都不大，但它们直接连着 solver 控制流，适合作为 chip 的 companion dense kernel。")
    lines.append("")
    lines.append("### 7.3 第三优先：`rho_out` 组装")
    lines.append("")
    lines.append("如果后续要把 SCF loop 拉成更完整的端到端 demo，可以把 charge assembly 加进去；这条路的关键仍然是 batched FFT 和 grid reduction。")
    lines.append("")
    lines.append("### 7.4 暂缓：`cdiaghg` 与 `mix_rho`")
    lines.append("")
    lines.append("- `cdiaghg` 的数据量只有几十 KiB，控制复杂度大于算力价值；")
    lines.append("- `mix_rho` 的输入输出都是单个 density grid，算术强度很低；")
    lines.append("- `newd` 虽然在 USPP 下有时间占比，但它更适合后续作为 host/FPGA companion path 单独分析。")
    lines.append("")
    lines.append("## 8. 这次实验应该怎么继续扩展")
    lines.append("")
    lines.append("如果你下一步要把这个实验变成 chip/FPGA 设计输入，我建议按下面的顺序继续：")
    lines.append("")
    lines.append("1. 先以本报告的 nominal / peak `h_psi` block 序列，定义 on-chip buffer 容量与块调度；")
    lines.append("2. 再把 `beta(G)`、`Veff(r)`、`Psi/HPsi/SPsi` 区分为 `SCF-step resident` 和 `call-streamed` 两类对象；")
    lines.append("3. 最后单独给 `newd` 做 companion-path 分析，决定它留在 CPU 还是下沉到 FPGA。")
    lines.append("")
    lines.append("如果只问“绝对什么部分真的要跑加速”，当前证据最强的答案是：")
    lines.append("")
    lines.append("- 必加速：`h_psi` 的 FFT + projector 主路，以及 `s_psi` projector 主路")
    lines.append("- 可以顺带做：basis refresh / subspace build companion GEMM")
    lines.append("- 不必抢先做：`cdiaghg`、`mix_rho`，以及尚未细化建模的 `newd`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.resolve()
    metadata = read_json(case_dir / "metadata.json")
    input_meta = parse_input_file(Path(metadata["input_file"]))
    stdout_meta = parse_stdout(Path(metadata["stdout_file"]))
    hpsi_rows = parse_csv(case_dir / "hpsi_trace.csv")
    bandsolver_rows = parse_csv(case_dir / "bandsolver_trace.csv")

    sequences = build_iteration_sequences(hpsi_rows, bandsolver_rows)
    timelines = build_iteration_timeline(bandsolver_rows)
    npw = int(stdout_meta["npw"])
    fft = stdout_meta["fft"]
    nfft = int(fft[0]) * int(fft[1]) * int(fft[2])
    beta_channels_per_atom = sum(2 * value + 1 for value in stdout_meta["beta_l"])
    nkb = int(input_meta["nat"]) * beta_channels_per_atom
    iteration_rows = summarize_iterations(sequences, npw, nkb, nfft, int(input_meta["nbnd"]))

    report = markdown_report(case_dir, input_meta, stdout_meta, iteration_rows, timelines)
    args.markdown_out.write_text(report, encoding="utf-8")
    print(f"Wrote {args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
