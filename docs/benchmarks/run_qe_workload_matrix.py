#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PW_BIN = ROOT / "soft/qe-7.5/build_subspace_trace/bin/pw.x"
RESULTS_ROOT = ROOT / "docs/benchmarks/results/qe_workload_revalidation"

CASE_INPUTS = {
    "h2_tiny": "docs/qe_inputs/h2_tiny_gamma.in",
    "si8_pbe_uspp": "docs/qe_inputs/si8_pbe_uspp.in",
    "si8_pbe_nc": "docs/qe_inputs/si8_pbe_nc.in",
    "si8_pbe0_uspp": "docs/qe_inputs/si8_pbe0_uspp_cg.in",
    "benzene": "docs/qe_inputs/benzene_workload_small.in",
    "graphene_pbe_paw": "docs/qe_inputs/graphene_pbe_paw_scf.in",
    "graphene_pbe_uspp": "docs/qe_inputs/graphene_pbe_uspp_scf.in",
    "bn32_pbe_uspp": "docs/qe_inputs/bn32_pbe_uspp.in",
    "bn32_pbe0_uspp": "docs/qe_inputs/bn32_pbe0_uspp_cg.in",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the QE workload revalidation matrix with runtime traces enabled."
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=list(CASE_INPUTS),
        help="Case ids to run. Defaults to the full matrix.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rerun cases even if a successful metadata.json already exists.",
    )
    parser.add_argument(
        "--subspace-min-n",
        type=int,
        default=0,
        help="Forwarded to QE_SUBSPACE_MIN_N.",
    )
    parser.add_argument(
        "--pw-bin",
        type=Path,
        default=PW_BIN,
        help="Path to the traced pw.x binary.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available case ids and exit.",
    )
    return parser.parse_args()


def shell_command(env: dict[str, str], argv: list[str], cwd: Path, stdout_path: Path) -> str:
    env_bits = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    cmd_bits = [shlex.quote(part) for part in argv]
    return " ".join(env_bits + cmd_bits) + f" > {shlex.quote(str(stdout_path))} 2>&1"


def case_paths(case_id: str) -> dict[str, Path]:
    result_dir = RESULTS_ROOT / case_id
    return {
        "result_dir": result_dir,
        "stdout": result_dir / "stdout.out",
        "hpsi_trace": result_dir / "hpsi_trace.csv",
        "bandsolver_trace": result_dir / "bandsolver_trace.csv",
        "subspace_trace": result_dir / "subspace_trace.csv",
        "metadata": result_dir / "metadata.json",
        "command": result_dir / "command.sh",
    }


def parse_outdir(input_path: Path) -> Path | None:
    for raw_line in input_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("outdir"):
            continue
        if "=" not in line:
            continue
        value = line.split("=", 1)[1].strip().rstrip(",")
        if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            outdir = Path(value[1:-1])
            return outdir if outdir.is_absolute() else (ROOT / outdir)
    return None


def should_skip(metadata_path: Path) -> bool:
    if not metadata_path.is_file():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return int(payload.get("exit_code", 1)) == 0


def run_case(case_id: str, input_rel: str, args: argparse.Namespace) -> int:
    input_path = ROOT / input_rel
    if not input_path.is_file():
        print(f"[missing-input] {case_id}: {input_path}", file=sys.stderr)
        return 1

    if not args.pw_bin.is_file():
        print(f"[missing-pw] {args.pw_bin}", file=sys.stderr)
        return 1

    paths = case_paths(case_id)
    paths["result_dir"].mkdir(parents=True, exist_ok=True)

    if not args.force and should_skip(paths["metadata"]):
        print(f"[skip] {case_id}")
        return 0

    outdir = parse_outdir(input_path)
    if outdir is not None:
        outdir.mkdir(parents=True, exist_ok=True)

    for artifact_name in ("stdout", "hpsi_trace", "bandsolver_trace", "subspace_trace"):
        paths[artifact_name].unlink(missing_ok=True)

    env = {
        "OMP_NUM_THREADS": "1",
        "QE_HPSI_TRACE_FILE": str(paths["hpsi_trace"]),
        "QE_BANDSOLVER_TRACE_FILE": str(paths["bandsolver_trace"]),
        "QE_SUBSPACE_TRACE_FILE": str(paths["subspace_trace"]),
        "QE_SUBSPACE_MIN_N": str(args.subspace_min_n),
    }
    argv = [str(args.pw_bin), "-in", str(input_path)]

    started = time.time()
    with paths["stdout"].open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            argv,
            cwd=ROOT,
            env={**os.environ, **env},
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    finished = time.time()

    payload = {
        "case_id": case_id,
        "input_file": str(input_path),
        "pw_bin": str(args.pw_bin),
        "cwd": str(ROOT),
        "exit_code": proc.returncode,
        "duration_sec": finished - started,
        "started_epoch_sec": started,
        "finished_epoch_sec": finished,
        "stdout_file": str(paths["stdout"]),
        "hpsi_trace_file": str(paths["hpsi_trace"]),
        "bandsolver_trace_file": str(paths["bandsolver_trace"]),
        "subspace_trace_file": str(paths["subspace_trace"]),
        "environment": env,
        "argv": argv,
    }
    paths["metadata"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    command_text = "#!/bin/sh\nset -eu\ncd {}\n{}\n".format(
        shlex.quote(str(ROOT)),
        shell_command(env, argv, ROOT, paths["stdout"]),
    )
    paths["command"].write_text(command_text, encoding="utf-8")

    status = "ok" if proc.returncode == 0 else f"exit={proc.returncode}"
    print(f"[{status}] {case_id} ({finished - started:.1f}s)")
    return 0 if proc.returncode == 0 else proc.returncode


def main() -> int:
    args = parse_args()
    if args.list:
        for case_id in CASE_INPUTS:
            print(case_id)
        return 0

    bad = [case_id for case_id in args.cases if case_id not in CASE_INPUTS]
    if bad:
        print("Unknown cases: " + ", ".join(bad), file=sys.stderr)
        return 2

    rc = 0
    for case_id in args.cases:
        rc = max(rc, run_case(case_id, CASE_INPUTS[case_id], args))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
