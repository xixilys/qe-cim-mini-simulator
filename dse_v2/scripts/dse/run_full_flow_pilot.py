#!/usr/bin/env python3
"""Run a profile-driven full workload timing-level pilot and emit evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
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
from dse_v2.contracts.schema_registry import CONTRACT_VERSION
from dse_v2.mapping.search import run_mapping_search, select_initial_mapping
from dse_v2.mapping.step2_workflow import run_step2_architecture_mapping_workflow_from_step1
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


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, Mapping) else {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_schema_version(path: Path) -> str:
    payload = _load_json(path)
    version = payload.get("schema_version")
    return str(version) if version else "v1"


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else None


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


def _run_step2_sidecar(args: argparse.Namespace, run_dir: Path):
    """Persist canonical Step2 search/Trial-ledger artifacts for pilot runs.

    The pilot keeps its historical smoke design point for backward-compatible
    evidence tests, but the front door now also exercises the generic Step2
    search/queue/Trial-ledger contract without launching broad evidence runs.
    """

    step2_dir = run_dir / "step2"
    result = run_step2_architecture_mapping_workflow_from_step1(
        run_dir / "step1",
        backend=args.backend,
        evidence_mode=args.evidence_mode,
        output_dir=step2_dir,
        require_l4_proof=args.backend == "gem5_systemc",
    )
    if not (step2_dir / "trial_state_ledger.json").exists():
        raise RuntimeError(f"Step2 sidecar did not write {step2_dir / 'trial_state_ledger.json'}")
    return result


def _step2_extra_artifact_paths(step2_result) -> list[str]:
    if step2_result is None:
        return []
    return list(dict.fromkeys(
        str(Path("step2") / rel_path)
        for rel_path in step2_result.artifact_paths.values()
    ))


def _campaign_scope_from_step2(run_dir: Path, *, run_id: str, workload_package: WorkloadPackage) -> Dict[str, str]:
    ledger = _load_json(run_dir / "step2" / "trial_state_ledger.json")
    queue = _load_json(run_dir / "step2" / "step3_simulation_queue.json")
    entries = queue.get("entries", []) if isinstance(queue.get("entries", []), list) else []
    first_entry = entries[0] if entries and isinstance(entries[0], Mapping) else {}
    return {
        "campaign_id": str(
            ledger.get("campaign_id")
            or queue.get("campaign_id")
            or f"campaign::{workload_package.workload_id}"
        ),
        "workload_run_id": str(
            ledger.get("workload_run_id")
            or queue.get("workload_run_id")
            or first_entry.get("workload_run_id")
            or f"workload_run::{workload_package.workload_id}"
        ),
        "trial_id": str(
            ledger.get("trial_id")
            or queue.get("trial_id")
            or first_entry.get("trial_id")
            or f"trial::{run_id}"
        ),
    }


def _campaign_objective(args: argparse.Namespace, workload_package: WorkloadPackage) -> str:
    return (
        f"Run a bounded {workload_package.workload_family}/{args.backend} DSE pilot "
        "that preserves Campaign/WorkloadRun/Trial provenance across Step1, Step2, "
        "and one selected-entry Step3 evidence path without broad evidence fanout."
    )


def _campaign_budgets(args: argparse.Namespace, run_dir: Path) -> Dict[str, Any]:
    queue = _load_json(run_dir / "step2" / "step3_simulation_queue.json")
    top_k = _load_json(run_dir / "step2" / "top_k_candidate_queue.json")
    return {
        "backend": args.backend,
        "evidence_mode": args.evidence_mode,
        "timeout_seconds": args.timeout,
        "feedback_sample_budget": max(1, int(args.feedback_samples)),
        "step3_queue_entry_budget": int(queue.get("entry_count", 0) or 0),
        "top_k_provenance_entry_count": int(top_k.get("entry_count", 0) or 0),
        "broad_evidence_run": False,
        "evidence_fanout_policy": "selected_entry_only_for_pilot",
    }


def _selected_trial_refs(run_dir: Path) -> Dict[str, Any]:
    queue = _load_json(run_dir / "step2" / "step3_simulation_queue.json")
    entries = queue.get("entries", []) if isinstance(queue.get("entries", []), list) else []
    normalized_entries = [dict(entry) for entry in entries if isinstance(entry, Mapping)]
    return {
        "step3_simulation_queue": "step2/step3_simulation_queue.json",
        "queue_mode": queue.get("queue_mode"),
        "entry_count": int(queue.get("entry_count", len(normalized_entries)) or 0),
        "queue_entry_ids": [str(entry.get("queue_entry_id")) for entry in normalized_entries if entry.get("queue_entry_id")],
        "candidate_ids": [str(entry.get("candidate_id")) for entry in normalized_entries if entry.get("candidate_id")],
        "mapping_candidate_ids": [
            str(entry.get("mapping_candidate_id"))
            for entry in normalized_entries
            if entry.get("mapping_candidate_id")
        ],
        "design_point_ids": [str(entry.get("design_point_id")) for entry in normalized_entries if entry.get("design_point_id")],
        "mapping_ids": [str(entry.get("mapping_id")) for entry in normalized_entries if entry.get("mapping_id")],
        "architecture_ids": [str(entry.get("architecture_id")) for entry in normalized_entries if entry.get("architecture_id")],
    }


def _top_k_lookup(top_k_queue: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    lookup: Dict[str, Mapping[str, Any]] = {}
    entries = top_k_queue.get("entries", []) if isinstance(top_k_queue.get("entries", []), list) else []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        for key in ("mapping_candidate_id", "candidate_id", "top_k_entry_id"):
            value = entry.get(key)
            if value:
                lookup[str(value)] = entry
    return lookup


def _build_campaign_evaluation_plan(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    run_id: str,
    workload_package: WorkloadPackage,
    scope: Mapping[str, str],
    budgets: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build the budgeted Campaign Manager handoff from Step2 provenance.

    The plan deliberately admits only the canonical Step3 queue entries.  Top-K
    rows are retained as deferred provenance so a later Campaign Manager can
    widen budgets explicitly without mistaking ranking hints for Step3 work.
    """

    queue = _load_json(run_dir / "step2" / "step3_simulation_queue.json")
    top_k_queue = _load_json(run_dir / "step2" / "top_k_candidate_queue.json")
    top_k_lookup = _top_k_lookup(top_k_queue)
    queue_entries = queue.get("entries", []) if isinstance(queue.get("entries", []), list) else []
    planned_entries: list[Dict[str, Any]] = []
    planned_top_k_ids: set[str] = set()
    for index, entry in enumerate(queue_entries):
        if not isinstance(entry, Mapping):
            continue
        mapping_candidate_id = str(entry.get("mapping_candidate_id") or entry.get("candidate_id") or f"queue_entry_{index}")
        top_k_entry = top_k_lookup.get(mapping_candidate_id) or top_k_lookup.get(str(entry.get("candidate_id", ""))) or {}
        if top_k_entry:
            planned_top_k_ids.add(str(top_k_entry.get("top_k_entry_id") or mapping_candidate_id))
            planned_top_k_ids.add(str(top_k_entry.get("mapping_candidate_id") or mapping_candidate_id))
            planned_top_k_ids.add(str(top_k_entry.get("candidate_id") or mapping_candidate_id))
        planned_entries.append({
            "plan_entry_id": f"campaign-plan::{entry.get('queue_entry_id') or index}",
            "queue_entry_id": str(entry.get("queue_entry_id") or f"queue_entry_{index}"),
            "candidate_id": str(entry.get("candidate_id") or ""),
            "mapping_candidate_id": mapping_candidate_id,
            "architecture_id": str(entry.get("architecture_id") or ""),
            "design_point_id": str(entry.get("design_point_id") or ""),
            "mapping_id": str(entry.get("mapping_id") or ""),
            "top_k_rank": top_k_entry.get("top_k_rank") if isinstance(top_k_entry, Mapping) else None,
            "parameter_hash": top_k_entry.get("parameter_hash") if isinstance(top_k_entry, Mapping) else None,
            "priority_score": entry.get("priority_score", top_k_entry.get("priority_score") if isinstance(top_k_entry, Mapping) else None),
            "admission_source": "step2/step3_simulation_queue.json",
            "execution_stage": "step3",
            "execution_allowed": bool(entry.get("promoted_for_simulation", False))
            and str(entry.get("queue_state", "")).startswith("scheduled_for_simulation"),
            "queue_state": entry.get("queue_state"),
            "required_step3_artifacts": list(entry.get("required_step3_artifacts", []) or []),
            "broad_evidence_run": False,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
        })

    deferred_entries: list[Dict[str, Any]] = []
    top_k_entries = top_k_queue.get("entries", []) if isinstance(top_k_queue.get("entries", []), list) else []
    for index, entry in enumerate(top_k_entries):
        if not isinstance(entry, Mapping):
            continue
        identities = {
            str(entry.get("top_k_entry_id") or ""),
            str(entry.get("mapping_candidate_id") or ""),
            str(entry.get("candidate_id") or ""),
        }
        if identities & planned_top_k_ids:
            continue
        deferred_entries.append({
            "top_k_entry_id": str(entry.get("top_k_entry_id") or f"top_k_entry_{index}"),
            "candidate_id": str(entry.get("candidate_id") or ""),
            "mapping_candidate_id": str(entry.get("mapping_candidate_id") or ""),
            "architecture_id": str(entry.get("architecture_id") or ""),
            "top_k_rank": entry.get("top_k_rank"),
            "parameter_hash": entry.get("parameter_hash"),
            "priority_score": entry.get("priority_score"),
            "defer_reason": "not_admitted_by_selected_entry_budget",
            "admission_required_before_execution": "step2/step3_simulation_queue.json",
            "execution_allowed": False,
            "provenance_only": True,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
        })

    return {
        "schema_version": CONTRACT_VERSION,
        **dict(scope),
        "plan_id": f"campaign_evaluation_plan::{run_id}",
        "run_id": run_id,
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "status": "active",
        "plan_scope": "bounded_selected_entry_pilot",
        "budget_policy": dict(budgets),
        "step3_simulation_queue_ref": "step2/step3_simulation_queue.json",
        "top_k_candidate_queue_ref": "step2/top_k_candidate_queue.json",
        "search_checkpoint_ref": "step2/search_checkpoint.json",
        "step3_queue_mode": queue.get("queue_mode"),
        "top_k_queue_mode": top_k_queue.get("queue_mode"),
        "planned_entry_count": len(planned_entries),
        "planned_entries": planned_entries,
        "deferred_entry_count": len(deferred_entries),
        "deferred_entries": deferred_entries,
        "budget_exhausted": len(deferred_entries) > 0,
        "selected_entry_only": True,
        "broad_evidence_run": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Campaign evaluation plan is a budgeted Step3 work plan. It may execute only "
            "entries admitted by step2/step3_simulation_queue.json; Top-K rows remain "
            "deferred provenance until the campaign budget is explicitly widened."
        ),
        "resume_next_actions": [
            "execute planned_entries through Step3 before considering deferred Top-K candidates",
            "widen the campaign budget before converting deferred_entries into Step3 queue entries",
            "keep final ranking blocked until Step4 adjudicates executed evidence",
        ],
    }


def _write_campaign_control_artifacts(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    run_id: str,
    workload_package: WorkloadPackage,
) -> Dict[str, Any]:
    """Write campaign-level control-plane artifacts without widening evidence runs."""

    scope = _campaign_scope_from_step2(run_dir, run_id=run_id, workload_package=workload_package)
    objective = _campaign_objective(args, workload_package)
    budgets = _campaign_budgets(args, run_dir)
    selected_refs = _selected_trial_refs(run_dir)
    evaluation_plan = _build_campaign_evaluation_plan(
        args=args,
        run_dir=run_dir,
        run_id=run_id,
        workload_package=workload_package,
        scope=scope,
        budgets=budgets,
    )
    policies = {
        "claim_boundary": (
            "Pilot campaign links Step1/Step2/selected-entry Step3 evidence only; "
            "it does not prove broad DSE, all-candidate RTL/PPA closure, or release completion."
        ),
        "step2_trial_ledger": "step2/trial_state_ledger.json",
        "step3_admission_queue": "step2/step3_simulation_queue.json",
        "top_k_queue_role": "provenance_only_not_step3_admission",
        "promotion_policy": "Step2 may promote only selected-entry queue rows to Step3.",
        "registry_campaign_name": args.registry_campaign if args.registry_db is not None else None,
    }
    campaign = {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": scope["campaign_id"],
        "objective": objective,
        "status": "active",
        "budgets": budgets,
        "policies": policies,
        "environment_ref": "provenance.json",
        "git_revision": _git_revision(),
        "global_stop_criteria": [
            "step1_workload_ingestion_complete",
            "step2_search_checkpoint_and_trial_ledger_written",
            "step3_selected_entry_evidence_attempted",
            "no_broad_evidence_or_release_claim_from_pilot",
        ],
        "final_completion_status": None,
    }
    ledger = {
        "schema_version": CONTRACT_VERSION,
        **scope,
        "run_id": run_id,
        "workload_id": workload_package.workload_id,
        "workload_family": workload_package.workload_family,
        "profile_id": workload_package.profile_id,
        "importer_id": workload_package.importer_id,
        "objective": objective,
        "status": "active",
        "budgets": budgets,
        "policies": policies,
        "control_plane_refs": {
            "campaign": "campaign.json",
            "campaign_ledger": "campaign_ledger.json",
            "campaign_evaluation_plan": "campaign_evaluation_plan.json",
        },
        "broad_evidence_run": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": policies["claim_boundary"],
        "workload_run_ref": {
            "step1_status": "step1/step1_status.json",
            "workload_package": "step1/workload_package.json",
            "workload_graph": "step1/workload_graph.json",
            "graph_lowering_report": "step1/graph_lowering_report.json",
            "executable_graph": "step1/executable_graph.json",
        },
        "step2_refs": {
            "architecture_search_space": "step2/architecture_search_space.json",
            "search_checkpoint": "step2/search_checkpoint.json",
            "top_k_candidate_queue": "step2/top_k_candidate_queue.json",
            "trial_state_ledger": "step2/trial_state_ledger.json",
            "step3_simulation_queue": "step2/step3_simulation_queue.json",
            "step2_artifact_validation": "step2/step2_artifact_validation.json",
        },
        "campaign_evaluation_plan_ref": "campaign_evaluation_plan.json",
        "step3_refs": {
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
            "simulation_result_raw": "simulation_result.raw.json",
            "systemc_stdout": "systemc_stdout.log",
            "systemc_stderr": "systemc_stderr.log",
        },
        "step4_refs": {
            "verdict": "verdict.json",
            "claim_validation": "claim_validation.json",
            "feedback_update": "feedback_update.json",
            "calibration_record": "calibration_record.json",
        },
        "step5_refs": {
            "final_report": "final_report.json",
            "final_report_markdown": "final_report.md",
        },
        "selected_trial_refs": selected_refs,
        "resume_next_actions": [
            "resume Step2 from step2/search_checkpoint.json if candidate ordering must be replayed",
            "use step2/step3_simulation_queue.json, not top_k_candidate_queue.json, for Step3 admission",
            "run Step3/Step4/Step5 only for selected queued entries unless campaign budgets are explicitly widened",
            "leave workload-family-specific physical evidence closure to profile-owned evidence lanes",
        ],
    }
    _write_json(run_dir / "campaign.json", campaign)
    _write_json(run_dir / "campaign_ledger.json", ledger)
    _write_json(run_dir / "campaign_evaluation_plan.json", evaluation_plan)
    return {
        "campaign": campaign,
        "campaign_ledger": ledger,
        "campaign_evaluation_plan": evaluation_plan,
        "artifact_paths": ["campaign.json", "campaign_ledger.json", "campaign_evaluation_plan.json"],
    }


def _registry_provenance(reason: str) -> Dict[str, object]:
    return {"actor": "run_full_flow_pilot", "reason": reason}


def _register_registry_artifact(
    registry: ExperimentRegistry,
    *,
    campaign_row_id: int,
    run_dir: Path,
    rel_path: str,
    schema_id: str,
    scope: str,
    workload_row_id: int | None = None,
    trial_row_id: int | None = None,
    producing_activity_id: int | None = None,
    metadata: Mapping[str, object] | None = None,
) -> None:
    path = run_dir / rel_path
    if not path.exists() or not path.is_file():
        return
    registry.register_artifact_ref(
        campaign_id=campaign_row_id,
        workload_run_id=workload_row_id if scope in {"workload_run", "trial"} else None,
        trial_id=trial_row_id if scope == "trial" else None,
        scope=scope,
        path=rel_path,
        schema_id=schema_id,
        schema_version=_payload_schema_version(path),
        content_hash=_file_sha256(path),
        content_hash_alg="sha256",
        producing_activity_id=producing_activity_id,
        metadata=dict(metadata or {}),
    )


def _record_registry_lifecycle(
    *,
    registry_db: Path | None,
    campaign_name: str,
    args: argparse.Namespace,
    workload_package: WorkloadPackage,
    evidence: Mapping[str, Any],
    run_dir: Path,
    simulator_returncode: int,
    campaign_artifacts: Mapping[str, Any],
) -> None:
    if registry_db is None:
        return

    with ExperimentRegistry(registry_db) as registry:
        campaign = next((item for item in registry.list_campaigns() if item.name == campaign_name), None)
        campaign_payload = dict(campaign_artifacts.get("campaign", {}) or {})
        ledger_payload = dict(campaign_artifacts.get("campaign_ledger", {}) or {})
        if campaign is None:
            campaign = registry.create_campaign(campaign_name, metadata={
                "runner": "run_full_flow_pilot",
                "workload": args.workload or args.profile,
                "profile": args.profile,
                "importer": args.importer,
                "objective": campaign_payload.get("objective"),
                "budgets": campaign_payload.get("budgets", {}),
                "policies": campaign_payload.get("policies", {}),
                "logical_campaign_id": campaign_payload.get("campaign_id"),
            })
        if campaign.status == "created":
            campaign = registry.transition_campaign(
                campaign.campaign_id,
                "running",
                provenance=_registry_provenance("start bounded full-flow pilot campaign"),
            )

        workload_run = registry.create_workload_run(
            campaign.campaign_id,
            {
                "logical_workload_run_id": ledger_payload.get("workload_run_id"),
                "workload_id": workload_package.workload_id,
                "workload_family": workload_package.workload_family,
                "profile": args.profile,
                "importer": args.importer,
                "step1_status": "step1/step1_status.json",
                "workload_package": "step1/workload_package.json",
            },
            provenance=_registry_provenance("create workload run from Step1 pilot artifacts"),
            resume={
                "resume_from": "step1/workload_package.json",
                "next_step": "step2_architecture_mapping",
            },
        )
        for status, reason in [
            ("ingesting", "record Step1 ingestion start"),
            ("lowered", "Step1 workload graph lowered"),
            ("validated", "Step1 artifacts validated"),
            ("ready_for_step2", "Step1 handoff is ready for Step2 search"),
        ]:
            workload_run = registry.transition_workload_run(
                workload_run.workload_run_id,
                status,
                provenance=_registry_provenance(reason),
            )

        trusted = bool(evidence.get("trusted_for_final_ranking", False))
        missing_required_coverage = list(
            evidence.get("missing_required_coverage", []) or []
        )
        fidelity = "L4" if args.backend == "gem5_systemc" else "L3"
        selected_refs = dict(ledger_payload.get("selected_trial_refs", {}) or {})
        trial = registry.create_trial(
            workload_run.workload_run_id,
            params={
                "logical_trial_id": ledger_payload.get("trial_id"),
                "workload": args.workload,
                "profile": args.profile,
                "importer": args.importer,
                "source_kind": args.source_kind,
                "generator": args.generator,
                "backend": args.backend,
                "evidence_mode": args.evidence_mode,
                "run_id": evidence.get("run_id"),
                "candidate_ids": list(selected_refs.get("candidate_ids", []) or []),
                "mapping_candidate_ids": list(selected_refs.get("mapping_candidate_ids", []) or []),
                "design_point_ids": list(selected_refs.get("design_point_ids", []) or []),
                "npw": args.npw,
                "nkb": args.nkb,
                "m": args.m,
                "nfft": args.nfft,
                "feedback_samples": args.feedback_samples,
            },
            fidelity=fidelity,
            generation_reasons=["selected_entry_from_step2_simulation_queue"],
            provenance=_registry_provenance("create selected pilot trial from Step2 queue"),
            metrics={
                "trusted_for_final_ranking": trusted,
                "missing_required_coverage_count": len(missing_required_coverage),
                # Deprecated compatibility metric for older registry readers.
                "missing_required_phase_count": len(missing_required_coverage),
                "simulator_returncode": simulator_returncode,
            },
            artifacts={
                "run_dir": str(run_dir),
                "campaign": str(run_dir / "campaign.json"),
                "campaign_ledger": str(run_dir / "campaign_ledger.json"),
                "campaign_evaluation_plan": str(run_dir / "campaign_evaluation_plan.json"),
                "step1_workload_package": str(run_dir / "step1" / "workload_package.json"),
                "step2_trial_state_ledger": str(run_dir / "step2" / "trial_state_ledger.json"),
                "step3_simulation_queue": str(run_dir / "step2" / "step3_simulation_queue.json"),
                "manifest": str(run_dir / "manifest.json"),
                "verdict": str(run_dir / "verdict.json"),
                "simulation_result": str(run_dir / "simulation_result.json"),
                "final_report": str(run_dir / "final_report.json"),
            },
        )
        trial_artifacts = dict(trial.artifacts)
        trial_metrics = dict(trial.metrics)
        for status, reason in [
            ("screened", "Step2 screening produced selected queue candidate"),
            ("promoted", "Step2 promotion decision admitted selected candidate"),
            ("scheduled_for_sim", "Step3 selected-entry simulation queue scheduled trial"),
            ("simulated", "Step3 simulator attempt completed for selected trial"),
        ]:
            trial = registry.transition_trial(
                trial.trial_id,
                status,
                provenance=_registry_provenance(reason),
                metrics=trial_metrics if status == "simulated" else None,
                artifacts=trial_artifacts if status == "simulated" else None,
                resume={
                    "resume_from": "simulation_result.json",
                    "next_step": "step4_adjudication",
                    "broad_evidence_run": False,
                } if status == "simulated" else None,
            )

        campaign_activity = registry.create_activity(
            campaign.campaign_id,
            "campaign_ledger_write",
            status="succeeded",
            command={"script": "dse_v2/scripts/dse/run_full_flow_pilot.py"},
            outputs={
                "campaign": "campaign.json",
                "campaign_ledger": "campaign_ledger.json",
                "campaign_evaluation_plan": "campaign_evaluation_plan.json",
            },
            provenance=_registry_provenance("write campaign control-plane artifacts"),
        )
        step1_activity = registry.create_activity(
            campaign.campaign_id,
            "step1_workload_ingestion",
            workload_run_id=workload_run.workload_run_id,
            status="succeeded",
            command={"profile": args.profile, "importer": args.importer},
            outputs={"workload_package": "step1/workload_package.json"},
            provenance=_registry_provenance("register Step1 workload artifacts"),
        )
        step2_activity = registry.create_activity(
            campaign.campaign_id,
            "step2_search_and_promotion",
            workload_run_id=workload_run.workload_run_id,
            trial_id=trial.trial_id,
            status="succeeded",
            inputs={"workload_package": "step1/workload_package.json"},
            outputs={"trial_state_ledger": "step2/trial_state_ledger.json"},
            provenance=_registry_provenance("register Step2 search artifacts"),
        )
        step3_activity = registry.create_activity(
            campaign.campaign_id,
            "step3_selected_simulation",
            workload_run_id=workload_run.workload_run_id,
            trial_id=trial.trial_id,
            status="succeeded",
            inputs={
                "campaign_evaluation_plan": "campaign_evaluation_plan.json",
                "step3_simulation_queue": "step2/step3_simulation_queue.json",
            },
            outputs={"simulation_result": "simulation_result.json"},
            provenance=_registry_provenance("register Step3 simulation artifacts"),
        )
        step4_activity = registry.create_activity(
            campaign.campaign_id,
            "step4_evidence_adjudication",
            workload_run_id=workload_run.workload_run_id,
            trial_id=trial.trial_id,
            status="succeeded",
            inputs={"simulation_result": "simulation_result.json"},
            outputs={"verdict": "verdict.json", "claim_validation": "claim_validation.json"},
            provenance=_registry_provenance("register Step4 adjudication artifacts"),
        )
        step5_activity = registry.create_activity(
            campaign.campaign_id,
            "step5_report_generation",
            workload_run_id=workload_run.workload_run_id,
            trial_id=trial.trial_id,
            status="succeeded",
            inputs={"claim_validation": "claim_validation.json"},
            outputs={"final_report": "final_report.json"},
            provenance=_registry_provenance("register Step5 report artifacts"),
        )
        for rel_path, schema_id in [
            ("campaign.json", "dse.contract.campaign.v1"),
            ("campaign_ledger.json", "dse.contract.campaign_ledger.v1"),
            ("campaign_evaluation_plan.json", "dse.contract.campaign_evaluation_plan.v1"),
        ]:
            _register_registry_artifact(
                registry,
                campaign_row_id=campaign.campaign_id,
                workload_row_id=workload_run.workload_run_id if rel_path == "campaign_evaluation_plan.json" else None,
                trial_row_id=trial.trial_id if rel_path == "campaign_evaluation_plan.json" else None,
                run_dir=run_dir,
                rel_path=rel_path,
                schema_id=schema_id,
                scope="trial" if rel_path == "campaign_evaluation_plan.json" else "campaign",
                producing_activity_id=campaign_activity.activity_id,
                metadata={"artifact_role": rel_path, "logical_campaign_id": campaign_payload.get("campaign_id")},
            )
        for rel_path, schema_id in [
            ("step1/step1_status.json", "dse.step1.status.v1"),
            ("step1/workload_package.json", "dse.contract.workload_package.v1"),
            ("step1/workload_graph.json", "dse.contract.compute_graph.v1"),
            ("step1/graph_lowering_report.json", "dse.step1.graph_lowering_report.v1"),
            ("step1/executable_graph.json", "dse.contract.executable_graph.v1"),
        ]:
            _register_registry_artifact(
                registry,
                campaign_row_id=campaign.campaign_id,
                workload_row_id=workload_run.workload_run_id,
                run_dir=run_dir,
                rel_path=rel_path,
                schema_id=schema_id,
                scope="workload_run",
                producing_activity_id=step1_activity.activity_id,
                metadata={"artifact_role": rel_path, "logical_workload_run_id": ledger_payload.get("workload_run_id")},
            )
        for rel_path, schema_id, activity_id in [
            ("step2/search_checkpoint.json", "dse.step2.search_checkpoint_summary.v1", step2_activity.activity_id),
            ("step2/top_k_candidate_queue.json", "dse.step2.top_k_candidate_queue.v1", step2_activity.activity_id),
            ("step2/trial_state_ledger.json", "dse.step2.trial_state_ledger.v1", step2_activity.activity_id),
            ("step2/step3_simulation_queue.json", "dse.step3.simulation_queue.v1", step2_activity.activity_id),
            ("simulation_request.json", "gsim.request.v1", step3_activity.activity_id),
            ("simulation_result.json", "gsim.result.v1", step3_activity.activity_id),
            ("verdict.json", "dse.contract.verdict.v1", step4_activity.activity_id),
            ("claim_validation.json", "dse.contract.claim_validation.v1", step4_activity.activity_id),
            ("feedback_update.json", "dse.contract.feedback_update.v1", step4_activity.activity_id),
            ("calibration_record.json", "dse.contract.calibration_record.v1", step4_activity.activity_id),
            ("final_report.json", "dse.contract.final_report.v1", step5_activity.activity_id),
        ]:
            _register_registry_artifact(
                registry,
                campaign_row_id=campaign.campaign_id,
                workload_row_id=workload_run.workload_run_id,
                trial_row_id=trial.trial_id,
                run_dir=run_dir,
                rel_path=rel_path,
                schema_id=schema_id,
                scope="trial",
                producing_activity_id=activity_id,
                metadata={
                    "artifact_role": rel_path,
                    "logical_trial_id": ledger_payload.get("trial_id"),
                    "broad_evidence_run": False,
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
    try:
        step2_sidecar = _run_step2_sidecar(args, run_dir)
    except Exception as exc:
        print(f"ERROR: Step2 search/Trial-ledger sidecar failed: {exc}", file=sys.stderr)
        return 2
    step2_artifact_paths = _step2_extra_artifact_paths(step2_sidecar)
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
    campaign_artifacts = _write_campaign_control_artifacts(
        args=args,
        run_dir=run_dir,
        run_id=run_id,
        workload_package=workload_package,
    )
    campaign_artifact_paths = list(campaign_artifacts.get("artifact_paths", []) or [])

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
            extra_artifact_paths=campaign_artifact_paths + step1_artifact_paths + step2_artifact_paths,
            workload_package=workload_package,
        )
        _record_registry_lifecycle(
            registry_db=args.registry_db,
            campaign_name=args.registry_campaign,
            args=args,
            workload_package=workload_package,
            evidence=evidence,
            run_dir=run_dir,
            simulator_returncode=int(run.get("returncode", 2)),
            campaign_artifacts=campaign_artifacts,
        )
        print(json.dumps({
            "run_id": evidence["run_id"],
            "run_dir": evidence["run_dir"],
            "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
            "missing_required_coverage": evidence["missing_required_coverage"],
            "campaign": str(run_dir / "campaign.json"),
            "campaign_ledger": str(run_dir / "campaign_ledger.json"),
            "step2_trial_state_ledger": str(run_dir / "step2" / "trial_state_ledger.json"),
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
        extra_artifact_paths=campaign_artifact_paths + step1_artifact_paths + step2_artifact_paths + extra_artifact_paths,
        feedback_sample_budget=max(1, args.feedback_samples),
        workload_package=workload_package,
    )
    _record_registry_lifecycle(
        registry_db=args.registry_db,
        campaign_name=args.registry_campaign,
        args=args,
        workload_package=workload_package,
        evidence=evidence,
        run_dir=run_dir,
        simulator_returncode=int(run.get("returncode", 1)),
        campaign_artifacts=campaign_artifacts,
    )

    summary = {
        "run_id": evidence["run_id"],
        "run_dir": evidence["run_dir"],
        "trusted_for_final_ranking": evidence["trusted_for_final_ranking"],
        "missing_required_coverage": evidence["missing_required_coverage"],
        "simulator_returncode": run.get("returncode", 1),
        "campaign": str(run_dir / "campaign.json"),
        "campaign_ledger": str(run_dir / "campaign_ledger.json"),
        "step2_trial_state_ledger": str(run_dir / "step2" / "trial_state_ledger.json"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if evidence["trusted_for_final_ranking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
