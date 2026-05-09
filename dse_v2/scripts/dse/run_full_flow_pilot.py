#!/usr/bin/env python3
"""Run a full QE SCF shell timing-level pilot and emit evidence artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.architecture.accelerator import (
    InterconnectTopology,
    SystemArchitecture,
    create_cim_array,
    create_fpga_u280,
    create_gpu_a100,
)
from dse_v2.core.ir.dft_workload import create_complete_qe_scf_graph
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.evidence.full_flow import REQUIRED_QE_SCF_PHASES, write_full_flow_evidence


def _add_supported_op(accel, op_type: str, efficiency: float) -> None:
    if op_type not in accel.compute.supported_ops:
        accel.compute.supported_ops.append(op_type)
    accel.compute.op_efficiency[op_type] = efficiency


def build_pilot_architecture() -> SystemArchitecture:
    """Build a broad heterogeneous pilot architecture without hardcoding a cluster template."""
    gpu = create_gpu_a100("gpu-0")
    fpga = create_fpga_u280("fpga-0")
    cim = create_cim_array("cim-0")

    _add_supported_op(gpu, "elementwise", 0.65)
    _add_supported_op(gpu, "reduction", 0.55)
    _add_supported_op(fpga, "reduction", 0.88)
    _add_supported_op(fpga, "elementwise", 0.80)
    _add_supported_op(fpga, "eigen", 0.30)
    _add_supported_op(cim, "elementwise", 0.90)

    return SystemArchitecture(
        system_id="generic_heterogeneous_qe_scf_pilot",
        host_cpu_cores=64,
        host_memory_gb=512.0,
        accelerators=[gpu, fpga, cim],
        interconnect=InterconnectTopology("pcie_cxl_mixed", 128.0, 1.0),
        max_power_w=1000.0,
        max_area_mm2=2000.0,
    )


def build_seed_mapping(node_ids: List[str]) -> Dict[str, str]:
    """Create a reproducible domain-seeded mapping for the vertical slice."""
    mapping = {
        "h_psi": "gpu-0",
        "s_psi": "gpu-0",
        "vnl": "cim-0",
        "precondition": "cim-0",
        "orthogonalize": "fpga-0",
        "build_H_sub": "fpga-0",
        "build_S_sub": "fpga-0",
        "diagonalize": "gpu-0",
        "subspace_rotation": "gpu-0",
        "refresh": "gpu-0",
        "residual": "cim-0",
        "rho_out": "fpga-0",
        "mix_rho": "cim-0",
        "veff": "fpga-0",
    }
    for node_id in node_ids:
        mapping.setdefault(node_id, "host")
    return mapping


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", default="qe_scf_shell", choices=["qe_scf_shell"])
    parser.add_argument("--backend", default="systemc", choices=["systemc", "gem5_systemc"])
    parser.add_argument("--evidence-mode", default="debug", choices=["summary", "debug", "forensic"])
    parser.add_argument("--out", type=Path, default=None, help="Evidence run directory")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--npw", type=int, default=512)
    parser.add_argument("--nkb", type=int, default=64)
    parser.add_argument("--m", type=int, default=16)
    parser.add_argument("--nfft", type=int, default=8192)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--simulator",
        type=Path,
        default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)

    run_id = args.run_id or f"qe_scf_shell_{args.backend}"
    run_dir = args.out or (REPO_ROOT / "runs" / "dse" / run_id)
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    graph = create_complete_qe_scf_graph(
        npw=args.npw,
        nkb=args.nkb,
        m=args.m,
        nfft=args.nfft,
        graph_id="qe_scf_shell_full_timing",
    )
    missing_nodes = [phase for phase in REQUIRED_QE_SCF_PHASES if phase not in graph.nodes]
    if missing_nodes:
        print(f"ERROR: workload graph missing required phases: {missing_nodes}", file=sys.stderr)
        return 2

    architecture = build_pilot_architecture()
    mapping = build_seed_mapping(list(graph.nodes.keys()))
    design_point = DesignPoint(
        design_point_id=run_id,
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={
            "workload": args.workload,
            "backend": args.backend,
            "evidence_mode": args.evidence_mode,
            "npw": args.npw,
            "nkb": args.nkb,
            "m": args.m,
            "nfft": args.nfft,
            "status": "p0_p1_vertical_slice",
        },
    )

    if args.backend == "gem5_systemc":
        backend = GenericSystemCBackend(executable_path=str(args.simulator), mode="gem5_systemc_blocked")
        request = backend._build_request(design_point, graph, output_dir=run_dir)
        evidence = write_full_flow_evidence(
            run_dir=run_dir,
            backend=args.backend,
            evidence_mode=args.evidence_mode,
            design_point=design_point,
            compute_graph=graph,
            simulation_request=request,
            simulation_result={
                "schema_version": "gsim.result.v1",
                "run_id": run_id,
                "status": "blocked",
                "error_message": "gem5+SystemC full descriptor/completion path is not implemented in this vertical slice",
            },
            simulator_cmd=[],
            simulator_returncode=2,
            systemc_stdout="",
            systemc_stderr=(
                "gem5+SystemC full descriptor/completion path is not implemented in this vertical slice; "
                "run --backend systemc to produce trusted L3 SystemC evidence and a blocked L4 verdict.\\n"
            ),
            cli_command=["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"] + argv,
            gem5_attempted=False,
        )
        print(json.dumps({
            "run_id": evidence["run_id"],
            "run_dir": evidence["run_dir"],
            "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
            "missing_required_phases": evidence["missing_required_phases"],
            "gem5_systemc": "blocked",
        }, indent=2, sort_keys=True))
        return 2

    backend = GenericSystemCBackend(executable_path=str(args.simulator), mode="standalone_systemc")
    try:
        run = backend.run_simulation(
            design_point,
            graph,
            output_dir=run_dir,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired as exc:
        run = {
            "run_id": run_id,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nSimulation timed out after {args.timeout}s\n",
            "request": backend._build_request(design_point, graph, output_dir=run_dir),
            "result": {"schema_version": "gsim.result.v1", "run_id": run_id, "status": "timeout"},
            "cmd": [str(args.simulator), "--request", str(run_dir / "simulation_request.json"), "--result", str(run_dir / "simulation_result.raw.json")],
        }

    evidence = write_full_flow_evidence(
        run_dir=run_dir,
        backend=args.backend,
        evidence_mode=args.evidence_mode,
        design_point=design_point,
        compute_graph=graph,
        simulation_request=run["request"] or backend._build_request(design_point, graph, output_dir=run_dir),
        simulation_result=run["result"],
        simulator_cmd=[str(x) for x in run.get("cmd", [])],
        simulator_returncode=int(run.get("returncode", 1)),
        systemc_stdout=run.get("stdout", ""),
        systemc_stderr=run.get("stderr", ""),
        cli_command=["python3", "dse_v2/scripts/dse/run_full_flow_pilot.py"] + argv,
        gem5_attempted=False,
    )

    summary = {
        "run_id": evidence["run_id"],
        "run_dir": evidence["run_dir"],
        "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
        "missing_required_phases": evidence["missing_required_phases"],
        "simulator_returncode": run.get("returncode", 1),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if evidence["trusted_for_final_ranking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
