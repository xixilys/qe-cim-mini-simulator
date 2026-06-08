#!/usr/bin/env python3
"""Run a small QE workflow and capture it as a measured workflow corpus."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.build_qe_measured_workflow_bundle import build_bundle_and_corpus  # noqa: E402
from dse_v2.scripts.dse.run_qe_fpga_deployment_dse import build_qe_fpga_workflow_corpus_report  # noqa: E402


SCF_INPUT = """&CONTROL
  calculation = 'scf',
  prefix = 'si_measured',
  outdir = './tmp',
  pseudo_dir = './pseudo',
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.2,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 8
/
&ELECTRONS
  conv_thr = 1.0d-6,
  electron_maxstep = 20,
  mixing_beta = 0.7
/
ATOMIC_SPECIES
 Si 28.0855 {pseudo_name}
ATOMIC_POSITIONS alat
 Si 0.00 0.00 0.00
 Si 0.25 0.25 0.25
K_POINTS automatic
 2 2 2 1 1 1
"""


NSCF_INPUT = """&CONTROL
  calculation = 'nscf',
  prefix = 'si_measured',
  outdir = './tmp',
  pseudo_dir = './pseudo',
/
&SYSTEM
  ibrav = 2,
  celldm(1) = 10.2,
  nat = 2,
  ntyp = 1,
  ecutwfc = 12.0,
  nbnd = 8
/
&ELECTRONS
  conv_thr = 1.0d-6,
  electron_maxstep = 20,
  mixing_beta = 0.7
/
ATOMIC_SPECIES
 Si 28.0855 {pseudo_name}
ATOMIC_POSITIONS alat
 Si 0.00 0.00 0.00
 Si 0.25 0.25 0.25
K_POINTS automatic
 3 3 3 0 0 0
"""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pw-command", default="pw.x")
    parser.add_argument("--pseudopotential", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--material", default="Si")
    parser.add_argument("--size-class", default="small")
    parser.add_argument("--selection-policy", required=True)
    parser.add_argument("--timeout-s", type=int, default=120)
    return parser.parse_args(list(argv))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_qe(command: str, input_name: str, *, run_dir: Path, timeout_s: int) -> Dict[str, Any]:
    completed = subprocess.run(
        [command, "-in", input_name],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=int(timeout_s),
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1")},
    )
    stdout_path = run_dir / input_name.replace(".in", ".out")
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path = run_dir / input_name.replace(".in", ".err")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return {
        "cmd": [command, "-in", input_name],
        "returncode": completed.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _write_inputs(run_dir: Path, pseudo_path: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tmp").mkdir(exist_ok=True)
    pseudo_dir = run_dir / "pseudo"
    pseudo_dir.mkdir(exist_ok=True)
    copied_pseudo = pseudo_dir / pseudo_path.name
    shutil.copy2(pseudo_path, copied_pseudo)
    (run_dir / "scf.in").write_text(SCF_INPUT.format(pseudo_name=pseudo_path.name), encoding="utf-8")
    (run_dir / "nscf.in").write_text(NSCF_INPUT.format(pseudo_name=pseudo_path.name), encoding="utf-8")
    return copied_pseudo


def _blocked_report(
    *,
    out_dir: Path,
    run_dir: Path,
    blocker: str,
    commands: Mapping[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    report = {
        "schema_version": "dse.qe_measured_workflow_capture_attempt.v1",
        "status": "blocked",
        "blocker": blocker,
        "run_dir": str(run_dir),
        "commands": dict(commands),
        "workflow_id": str(args.workflow_id),
        "workload_id": str(args.workload_id),
        "claim_boundary": "qe_measured_workflow_capture_attempt_only_not_ready_measured_corpus",
    }
    _write_json(out_dir / "qe_measured_workflow_capture_attempt.json", report)
    return report


def _preflight_corpus(corpus_path: Path, out_dir: Path) -> tuple[int, Dict[str, Any]]:
    report = build_qe_fpga_workflow_corpus_report(corpus_path)
    readiness = report.get("measured_qe_corpus_readiness", {})
    status = {
        "schema_version": "dse.qe_fpga.workflow_corpus_preflight_status.v1",
        "status": str(readiness.get("status", "blocked")),
        "workflow_corpus": str(corpus_path),
        "report": str(out_dir / "qe_fpga_workload_corpus_preflight.json"),
        "workload_count": int(report.get("workload_count", 0)),
        "measured_ready_workload_count": int(readiness.get("measured_ready_workload_count", 0)),
        "blockers": list(readiness.get("blockers", []) or []),
        "allowed_use": str(readiness.get("allowed_use", "")),
        "forbidden_use": list(readiness.get("forbidden_use", []) or []),
        "claim_boundary": "workflow_corpus_preflight_only_not_search_hardware_or_qe_correctness_evidence",
    }
    _write_json(out_dir / "qe_fpga_workload_corpus_preflight.json", report)
    _write_json(out_dir / "qe_fpga_workload_corpus_preflight_status.json", status)
    return (0 if status["status"] == "ready_for_model_level_experiments" else 1), status


def _build_and_preflight(args: argparse.Namespace, *, run_dir: Path, out_dir: Path, pseudo: Path, commands: Dict[str, Any]) -> Dict[str, Any]:
    bundle_dir = out_dir / "bundle"
    bundle_args = argparse.Namespace(
        source_dir=run_dir,
        out=bundle_dir,
        workflow_id=args.workflow_id,
        workload_id=args.workload_id,
        material=args.material,
        size_class=args.size_class,
        selection_policy=args.selection_policy,
        scf_input="scf.in",
        scf_log="scf.out",
        nscf_input="nscf.in",
        nscf_log="nscf.out",
        save_dir="tmp/si_measured.save",
        pseudopotential=[pseudo],
        profile=[],
    )
    bundle_status = build_bundle_and_corpus(bundle_args)
    preflight_dir = out_dir / "preflight"
    preflight_rc, preflight_status = _preflight_corpus(bundle_dir / "workflow_corpus.json", preflight_dir)
    status = str(preflight_status.get("status", "blocked"))
    attempt = {
        "schema_version": "dse.qe_measured_workflow_capture_attempt.v1",
        "status": status,
        "run_dir": str(run_dir),
        "commands": commands,
        "bundle_status": bundle_status,
        "preflight_status": preflight_status,
        "workflow_corpus": str(bundle_dir / "workflow_corpus.json"),
        "claim_boundary": "qe_measured_workflow_capture_attempt_only_not_hardware_or_accelerated_correctness_evidence",
    }
    _write_json(out_dir / "qe_measured_workflow_capture_attempt.json", attempt)
    return {
        "status": status,
        "workflow_corpus": str(bundle_dir / "workflow_corpus.json"),
        "preflight_status": preflight_status,
        "attempt_report": str(out_dir / "qe_measured_workflow_capture_attempt.json"),
        "claim_boundary": attempt["claim_boundary"],
        "preflight_returncode": preflight_rc,
    }


def run_capture(args: argparse.Namespace) -> Dict[str, Any]:
    out_dir = args.out
    run_dir = out_dir / "qe_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    pseudo = _write_inputs(run_dir, args.pseudopotential)
    commands: Dict[str, Any] = {}
    commands["scf"] = _run_qe(args.pw_command, "scf.in", run_dir=run_dir, timeout_s=int(args.timeout_s))
    if commands["scf"]["returncode"] != 0:
        return _blocked_report(out_dir=out_dir, run_dir=run_dir, blocker="qe_scf_run_failed", commands=commands, args=args)
    commands["nscf"] = _run_qe(args.pw_command, "nscf.in", run_dir=run_dir, timeout_s=int(args.timeout_s))
    if commands["nscf"]["returncode"] != 0:
        return _blocked_report(out_dir=out_dir, run_dir=run_dir, blocker="qe_nscf_run_failed", commands=commands, args=args)
    return _build_and_preflight(args, run_dir=run_dir, out_dir=out_dir, pseudo=pseudo, commands=commands)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    status = run_capture(args)
    print(json.dumps(status, sort_keys=True))
    return 0 if status.get("status") == "ready_for_model_level_experiments" else 1


if __name__ == "__main__":
    raise SystemExit(main())
