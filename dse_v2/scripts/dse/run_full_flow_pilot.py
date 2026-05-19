#!/usr/bin/env python3
"""Run a profile-driven full workload timing-level pilot and emit evidence artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.backends.gem5_systemc_adapter import Gem5SystemCClosureAdapter
from dse_v2.core.architecture.accelerator import (
    InterconnectTopology,
    SystemArchitecture,
    create_cim_array,
    create_fpga_u280,
    create_gpu_a100,
)
from dse_v2.core.workload import (
    create_dynamic_custom_graph,
    create_graph_analytics_graph,
    create_sparse_spmv_graph,
    create_stencil_streaming_graph,
    create_tensor_chain_graph,
    create_vector_search_graph,
    default_importer_registry,
    default_profile_registry,
    load_step1_workload_package,
    run_step1_workload_ingestion_workflow,
)
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.dse.orchestrator import DesignPoint
from dse_v2.evidence.full_flow import (
    build_numerical_validation,
    build_phase_results,
    write_full_flow_evidence,
)
from dse_v2.mapping.search import run_mapping_search, select_initial_mapping
from dse_v2.registry import ExperimentRegistry


def _add_supported_op(accel, op_type: str, efficiency: float) -> None:
    if op_type not in accel.compute.supported_ops:
        accel.compute.supported_ops.append(op_type)
    accel.compute.op_efficiency[op_type] = efficiency


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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
        system_id="generic_heterogeneous_profile_pilot",
        host_cpu_cores=64,
        host_memory_gb=512.0,
        accelerators=[gpu, fpga, cim],
        interconnect=InterconnectTopology("pcie_cxl_mixed", 128.0, 1.0),
        max_power_w=1000.0,
        max_area_mm2=2000.0,
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", default=None, help="Compatibility alias. Use --profile/--importer for new runs; qe_scf_shell delegates to the QE reference importer.")
    parser.add_argument("--profile", default="ml_tensor", help="Workload profile id")
    parser.add_argument("--importer", default="generic_json", help="Workload importer id")
    parser.add_argument("--source-kind", default="generated", help="Source kind handed to the importer")
    parser.add_argument(
        "--generator",
        default="tensor_chain",
        choices=["tensor_chain", "sparse_spmv", "stencil_streaming", "graph_analytics", "vector_search", "dynamic_custom", "qe_scf_reference"],
        help="Built-in generated fixture for the selected importer/profile",
    )
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
    parser.add_argument("--gem5-real-l4", action="store_true", help="Run the real gem5 GenericAccel L4 harness required for trusted gem5_systemc evidence")
    parser.set_defaults(gem5_real_l4=_env_flag("GSIM_GEM5_REAL_L4", False))
    parser.add_argument(
        "--gem5-binary",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt",
    )
    parser.add_argument(
        "--gem5-config",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py",
    )
    parser.add_argument(
        "--gem5-driver",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver",
    )
    parser.add_argument("--gem5-cpu-type", default="atomic", choices=["atomic", "timing"])
    parser.add_argument("--gem5-max-ticks", type=int, default=10_000_000_000)
    parser.add_argument(
        "--feedback-samples",
        type=int,
        default=1,
        help="Number of promoted SystemC candidates to sample for feedback/convergence evidence in standalone SystemC mode",
    )
    parser.add_argument("--registry-db", type=Path, default=None, help="Optional SQLite experiment registry path")
    parser.add_argument("--registry-campaign", default="full_flow_pilot", help="Campaign name used when --registry-db is set")
    return parser.parse_args(argv)


def _apply_workload_aliases(args: argparse.Namespace) -> None:
    if args.workload == "qe_scf_shell":
        args.profile = "qe_scf_reference"
        args.importer = "qe_reference_fixture"
        args.generator = "qe_scf_reference"
        args.source_kind = "generated"


def _generated_generic_graph(generator: str):
    builders = {
        "tensor_chain": create_tensor_chain_graph,
        "sparse_spmv": create_sparse_spmv_graph,
        "stencil_streaming": create_stencil_streaming_graph,
        "graph_analytics": create_graph_analytics_graph,
        "vector_search": create_vector_search_graph,
        "dynamic_custom": create_dynamic_custom_graph,
    }
    if generator not in builders:
        raise KeyError(f"unknown generic generator: {generator}")
    return builders[generator](graph_id=f"{generator}_full_timing")


def build_workload_package(args: argparse.Namespace) -> WorkloadPackage:
    """Resolve profile/importer and return a generic workload package."""
    if args.importer == "qe_reference_fixture" or args.profile == "qe_scf_reference" or args.generator == "qe_scf_reference":
        from dse_v2.reference_workloads.dft_qe import QeReferenceImporter, qe_scf_reference_profile

        profile = qe_scf_reference_profile()
        importer = QeReferenceImporter()
        return importer.import_workload(
            None,
            profile=profile,
            parameters={
                "npw": args.npw,
                "nkb": args.nkb,
                "m": args.m,
                "nfft": args.nfft,
                "source_kind": args.source_kind,
                "graph_id": "qe_scf_reference_full_timing",
            },
        )

    profile = default_profile_registry().get(args.profile)
    importer = default_importer_registry().get(args.importer)
    graph = _generated_generic_graph(args.generator)
    return importer.import_workload(
        graph,
        profile=profile,
        parameters={
            "source_kind": args.source_kind,
            "workload_family": profile.workload_family,
            "profile_id": profile.profile_id,
        },
    )


def _step1_registries(args: argparse.Namespace):
    """Return profile/importer registries for the Step1 boundary."""
    profile_registry = default_profile_registry()
    importer_registry = default_importer_registry()
    if args.importer == "qe_reference_fixture" or args.profile == "qe_scf_reference" or args.generator == "qe_scf_reference":
        from dse_v2.reference_workloads.dft_qe import qe_scf_reference_profile, register_qe_reference_importer

        profile_registry.register(qe_scf_reference_profile())
        register_qe_reference_importer(importer_registry)
    return profile_registry, importer_registry


def _step1_source_and_parameters(args: argparse.Namespace):
    """Build the source payload and importer parameters for Step1."""
    if args.importer == "qe_reference_fixture" or args.profile == "qe_scf_reference" or args.generator == "qe_scf_reference":
        return None, {
            "npw": args.npw,
            "nkb": args.nkb,
            "m": args.m,
            "nfft": args.nfft,
            "source_kind": args.source_kind,
            "graph_id": "qe_scf_reference_full_timing",
        }

    profile = default_profile_registry().get(args.profile)
    graph = _generated_generic_graph(args.generator)
    return graph, {
        "source_kind": args.source_kind,
        "workload_family": profile.workload_family,
        "profile_id": profile.profile_id,
    }


def _run_step1_boundary(args: argparse.Namespace, run_dir: Path):
    """Persist Step1 artifacts and reload the WorkloadPackage from disk."""
    source, parameters = _step1_source_and_parameters(args)
    profile_registry, importer_registry = _step1_registries(args)
    step1_dir = run_dir / "step1"
    step1 = run_step1_workload_ingestion_workflow(
        source,
        profile_id=args.profile,
        importer_id=args.importer,
        source_kind=args.source_kind,
        parameters=parameters,
        output_dir=step1_dir,
        profile_registry=profile_registry,
        importer_registry=importer_registry,
        source_path=str(parameters.get("source_path")) if parameters.get("source_path") else None,
    )
    if step1.status != "complete":
        status_path = step1_dir / "step1_status.json"
        print(
            f"ERROR: Step1 workload ingestion failed with status={step1.status}; "
            f"see {status_path}",
            file=sys.stderr,
        )
        return step1, None
    return step1, load_step1_workload_package(step1_dir)


def _step1_extra_artifact_paths(step1_result) -> list[str]:
    if step1_result is None:
        return []
    return list(dict.fromkeys(
        str(Path("step1") / rel_path)
        for rel_path in step1_result.artifact_paths.values()
    ))


def _record_registry_trial(
    *,
    registry_db: Path | None,
    campaign_name: str,
    args: argparse.Namespace,
    evidence: Mapping[str, Any],
    run_dir: Path,
    simulator_returncode: int,
) -> None:
    if registry_db is None:
        return

    with ExperimentRegistry(registry_db) as registry:
        campaign = next((item for item in registry.list_campaigns() if item.name == campaign_name), None)
        if campaign is None:
            campaign = registry.create_campaign(campaign_name, metadata={
                "runner": "run_full_flow_pilot",
                "workload": args.workload or args.profile,
                "profile": args.profile,
                "importer": args.importer,
            })

        trusted = bool(evidence.get("trusted_for_final_ranking", False))
        missing_required_coverage = list(
            evidence.get("missing_required_coverage", []) or []
        )
        fidelity = "L4" if args.backend == "gem5_systemc" else "L3"
        status = "completed" if trusted else "completed_untrusted"
        registry.add_trial(
            campaign.campaign_id,
            params={
                "workload": args.workload,
                "profile": args.profile,
                "importer": args.importer,
                "source_kind": args.source_kind,
                "generator": args.generator,
                "backend": args.backend,
                "evidence_mode": args.evidence_mode,
                "run_id": evidence.get("run_id"),
                "npw": args.npw,
                "nkb": args.nkb,
                "m": args.m,
                "nfft": args.nfft,
                "feedback_samples": args.feedback_samples,
            },
            fidelity=fidelity,
            status=status,
            metrics={
                "trusted_for_final_ranking": trusted,
                "missing_required_coverage_count": len(missing_required_coverage),
                # Deprecated compatibility metric for older registry readers.
                "missing_required_phase_count": len(missing_required_coverage),
                "simulator_returncode": simulator_returncode,
            },
            artifacts={
                "run_dir": str(run_dir),
                "manifest": str(run_dir / "manifest.json"),
                "verdict": str(run_dir / "verdict.json"),
                "simulation_result": str(run_dir / "simulation_result.json"),
                "final_report": str(run_dir / "final_report.json"),
            },
        )


def _additional_systemc_feedback_samples(
    *,
    backend: GenericSystemCBackend,
    run_dir: Path,
    run_id: str,
    graph,
    architecture: SystemArchitecture,
    selected_mapping,
    sample_budget: int,
    timeout: int,
) -> tuple[list[Dict[str, Any]], list[str]]:
    """Run additional promoted SystemC candidates into per-candidate evidence subdirectories."""
    if sample_budget <= 1:
        return [], []

    search = run_mapping_search(
        graph,
        architecture,
        selected_mapping=selected_mapping,
        beam_width=sample_budget,
    )
    selected_key = tuple(sorted(selected_mapping.items()))
    candidates = []
    for record in search["candidate_records"]["candidates"]:
        if record.get("state") not in {"promoted", "predicted-only"}:
            continue
        if record.get("violations"):
            continue
        mapping = dict(record.get("mapping", {}))
        if tuple(sorted(mapping.items())) == selected_key:
            continue
        candidates.append(record)
        if len(candidates) >= sample_budget - 1:
            break

    samples: list[Dict[str, Any]] = []
    artifact_paths: list[str] = []
    for record in candidates:
        candidate_id = str(record["candidate_id"])
        sample_rel = Path("feedback_samples") / candidate_id
        sample_dir = run_dir / sample_rel
        sample_design = DesignPoint(
            design_point_id=f"{run_id}_{candidate_id}",
            system_architecture=architecture,
            task_mapping=dict(record["mapping"]),
            scheduling_policy="static_timing_level",
            config={
                "workload": graph.graph_id,
                "backend": "systemc",
                "feedback_candidate_id": candidate_id,
                "status": "p4_p5_feedback_sample",
            },
        )
        try:
            sample_run: Dict[str, Any] = backend.run_simulation(
                sample_design,
                graph,
                output_dir=sample_dir,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            sample_run = {
                "returncode": 124,
                "stdout": _process_text(exc.stdout),
                "stderr": _process_text(exc.stderr) + f"\nSimulation timed out after {timeout}s\n",
                "request": backend._build_request(sample_design, graph, output_dir=sample_dir),
                "result": {"schema_version": "gsim.result.v1", "run_id": sample_design.design_point_id, "status": "timeout"},
                "cmd": [str(backend.executable_path), "--request", str(sample_dir / "simulation_request.json"), "--result", str(sample_dir / "simulation_result.raw.json")],
            }

        request_value = sample_run.get("request")
        request: Mapping[str, Any] = request_value if isinstance(request_value, Mapping) else backend._build_request(sample_design, graph, output_dir=sample_dir)
        result_value = sample_run.get("result")
        raw_result: Dict[str, Any] = dict(result_value) if isinstance(result_value, Mapping) else {}
        phase_results = build_phase_results(raw_result, request)
        missing_phases = [phase for phase, result in phase_results.items() if result.get("status") != "available"]
        numerical = build_numerical_validation(request, raw_result)
        raw_sample_passed = (
            int(sample_run.get("returncode", 1)) == 0
            and raw_result.get("status") == "passed"
            and not missing_phases
            and bool(numerical.get("passed", False))
        )
        # Additional feedback samples are raw Step3 measurements in this CLI.
        # They deliberately do not pass through sample-local Step4 adjudication
        # (verdict/claim-validation/evidence-requirements), so treating them as
        # final-trusted would violate the Step3/Step4/Step5 ownership boundary.
        # Future callers may still pass adjudicated trusted samples directly to
        # run_mapping_search(); this helper must keep its own raw samples
        # blocked/untrusted until that per-sample Step4 path exists.
        sample_step4_adjudicated = False
        trusted = raw_sample_passed and sample_step4_adjudicated
        public_result = dict(raw_result)
        public_result.update({
            "backend": "systemc",
            "timing_level": True,
            "required_coverage": list(phase_results.keys()),
            "required_workload_phases": list(phase_results.keys()),
            "phase_results": phase_results,
            "missing_required_coverage": missing_phases,
            "numerical_validation": {
                "artifact": str(sample_rel / "numerical_validation.json"),
                "status": numerical.get("status"),
                "passed": bool(numerical.get("passed", False)),
                "scope": numerical.get("scope"),
                "summary": numerical.get("summary", {}),
            },
            "simulator_returncode": int(sample_run.get("returncode", 1)),
        })

        _write_json(sample_dir / "simulation_request.json", request)
        _write_json(sample_dir / "simulation_result.json", public_result)
        _write_json(sample_dir / "numerical_validation.json", numerical)
        _write_text(sample_dir / "systemc_stdout.log", _process_text(sample_run.get("stdout")))
        _write_text(sample_dir / "systemc_stderr.log", _process_text(sample_run.get("stderr")))
        for rel_name in [
            "simulation_request.json",
            "simulation_result.json",
            "simulation_result.raw.json",
            "numerical_validation.json",
            "systemc_stdout.log",
            "systemc_stderr.log",
        ]:
            if (sample_dir / rel_name).exists():
                artifact_paths.append(str(sample_rel / rel_name))

        metrics = public_result.get("metrics", {}) or {}
        evidence_ids = [
            str(sample_rel / "simulation_result.json"),
            str(sample_rel / "numerical_validation.json"),
            str(sample_rel / "simulation_request.json"),
        ]
        samples.append({
            "candidate_id": candidate_id,
            "backend": "systemc",
            "fidelity": "L3",
            "status": public_result.get("status", "unknown"),
            "sample_role": "trusted_feedback" if trusted else "blocked_or_untrusted_attempt",
            "trusted_final_eligible": trusted,
            "evidence_quality": "trusted_high_fidelity" if trusted else "blocked_or_untrusted",
            "metrics": {
                "latency_ms": metrics.get("latency_ms"),
                "power_w": metrics.get("power_w"),
                "energy_j": metrics.get("energy_j"),
                "total_data_movement_mb": metrics.get("total_data_movement_mb"),
            },
            "evidence_ids": evidence_ids,
            "blockers": [] if trusted else [
                {
                    "id": "missing_step4_adjudication_for_feedback_sample",
                    "detail": "Additional feedback samples are raw Step3 measurements and are not final-trusted until per-sample Step4 verdict/claim validation artifacts exist.",
                    "raw_sample_passed": raw_sample_passed,
                    "required_artifacts": ["verdict.json", "claim_validation.json", "evidence_requirements.json"],
                },
                {
                    "id": "systemc_feedback_sample_untrusted",
                    "detail": "Additional feedback sample failed returncode, phase coverage, status, numerical validation gate, or Step4 adjudication gate.",
                    "missing_required_coverage": missing_phases,
                },
            ],
        })

    return samples, artifact_paths


def main(argv: List[str] | None = None, *, cli_script: str = "dse_v2/scripts/dse/run_full_flow_pilot.py") -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    _apply_workload_aliases(args)

    run_id = args.run_id or f"{args.profile}_{args.backend}"
    run_dir = args.out or (REPO_ROOT / "runs" / "dse" / run_id)
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    step1_result, workload_package = _run_step1_boundary(args, run_dir)
    if workload_package is None:
        return 2
    step1_artifact_paths = _step1_extra_artifact_paths(step1_result)
    graph = workload_package.graph
    required_coverage = workload_package.required_coverage()["required_coverage"]
    missing_nodes = [phase for phase in required_coverage if phase not in graph.nodes and phase not in graph.regions]
    if missing_nodes:
        print(f"ERROR: workload graph missing required coverage: {missing_nodes}", file=sys.stderr)
        return 2

    architecture = build_pilot_architecture()
    mapping = select_initial_mapping(graph, architecture)
    design_point = DesignPoint(
        design_point_id=run_id,
        system_architecture=architecture,
        task_mapping=mapping,
        scheduling_policy="static_timing_level",
        config={
            "workload": workload_package.workload_id,
            "profile": workload_package.profile_id,
            "importer": workload_package.importer_id,
            "source_kind": args.source_kind,
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
        backend = GenericSystemCBackend(
            executable_path=str(args.simulator),
            mode="gem5_systemc",
        )
        if not args.gem5_real_l4:
            print(
                "ERROR: --backend gem5_systemc requires --gem5-real-l4; "
                "synthetic gem5 evidence generation has been removed.",
                file=sys.stderr,
            )
            return 2
        adapter = Gem5SystemCClosureAdapter(backend)
        run = adapter.run_verified_l4(
            design_point=design_point,
            compute_graph=graph,
            workload_package=workload_package,
            output_dir=run_dir,
            gem5_binary=args.gem5_binary,
            gem5_config=args.gem5_config,
            driver_binary=args.gem5_driver,
            simulator_binary=args.simulator,
            max_ticks=args.gem5_max_ticks,
            cpu_type=args.gem5_cpu_type,
            timeout=args.timeout,
        )
        gem5_log_path = run_dir / "gem5.log"
        evidence = write_full_flow_evidence(
            run_dir=run_dir,
            backend=args.backend,
            evidence_mode=args.evidence_mode,
            design_point=design_point,
            compute_graph=graph,
            simulation_request=run["request"] or backend._build_request(design_point, graph, workload_package=workload_package, output_dir=run_dir),
            simulation_result=run["result"],
            simulator_cmd=[str(x) for x in run.get("cmd", [])],
            simulator_returncode=int(run.get("returncode", 2)),
            systemc_stdout=run.get("stdout", ""),
            systemc_stderr=run.get("stderr", ""),
            cli_command=["python3", cli_script] + argv,
            gem5_attempted=True,
            gem5_log=run.get("gem5_log") or (gem5_log_path.read_text(encoding="utf-8") if gem5_log_path.exists() else None),
            gem5_source_artifacts=(run.get("gem5_l4_transport_proof") or {}).get("source_artifacts"),
            extra_artifact_paths=step1_artifact_paths,
            workload_package=workload_package,
        )
        _record_registry_trial(
            registry_db=args.registry_db,
            campaign_name=args.registry_campaign,
            args=args,
            evidence=evidence,
            run_dir=run_dir,
            simulator_returncode=int(run.get("returncode", 2)),
        )
        print(json.dumps({
            "run_id": evidence["run_id"],
            "run_dir": evidence["run_dir"],
            "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
            "missing_required_coverage": evidence["missing_required_coverage"],
            "gem5_systemc": "verified" if evidence["trusted_for_final_ranking"] else "blocked",
        }, indent=2, sort_keys=True))
        return 0 if evidence["trusted_for_final_ranking"] else 2

    backend = GenericSystemCBackend(executable_path=str(args.simulator), mode="standalone_systemc")
    try:
        run = backend.run_simulation(
            design_point,
            graph,
            workload_package=workload_package,
            output_dir=run_dir,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired as exc:
        run: Dict[str, Any] = {
            "run_id": run_id,
            "returncode": 124,
            "stdout": _process_text(exc.stdout),
            "stderr": _process_text(exc.stderr) + f"\nSimulation timed out after {args.timeout}s\n",
            "request": backend._build_request(design_point, graph, workload_package=workload_package, output_dir=run_dir),
            "result": {"schema_version": "gsim.result.v1", "run_id": run_id, "status": "timeout"},
            "cmd": [str(args.simulator), "--request", str(run_dir / "simulation_request.json"), "--result", str(run_dir / "simulation_result.raw.json")],
        }
    else:
        run = dict(run)

    additional_samples, extra_artifact_paths = _additional_systemc_feedback_samples(
        backend=backend,
        run_dir=run_dir,
        run_id=run_id,
        graph=graph,
        architecture=architecture,
        selected_mapping=mapping,
        sample_budget=max(1, args.feedback_samples),
        timeout=args.timeout,
    )

    evidence = write_full_flow_evidence(
        run_dir=run_dir,
        backend=args.backend,
        evidence_mode=args.evidence_mode,
        design_point=design_point,
        compute_graph=graph,
        simulation_request=run["request"] if isinstance(run.get("request"), Mapping) else backend._build_request(design_point, graph, workload_package=workload_package, output_dir=run_dir),
        simulation_result=run["result"] if isinstance(run.get("result"), Mapping) else {},
        simulator_cmd=[str(x) for x in run.get("cmd", [])],
        simulator_returncode=int(run.get("returncode", 1)),
        systemc_stdout=_process_text(run.get("stdout")),
        systemc_stderr=_process_text(run.get("stderr")),
        cli_command=["python3", cli_script] + argv,
        gem5_attempted=False,
        additional_feedback_samples=additional_samples,
        extra_artifact_paths=step1_artifact_paths + extra_artifact_paths,
        feedback_sample_budget=max(1, args.feedback_samples),
        workload_package=workload_package,
    )
    _record_registry_trial(
        registry_db=args.registry_db,
        campaign_name=args.registry_campaign,
        args=args,
        evidence=evidence,
        run_dir=run_dir,
        simulator_returncode=int(run.get("returncode", 1)),
    )

    summary = {
        "run_id": evidence["run_id"],
        "run_dir": evidence["run_dir"],
        "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
        "missing_required_coverage": evidence["missing_required_coverage"],
        "simulator_returncode": run.get("returncode", 1),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if evidence["trusted_for_final_ranking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
