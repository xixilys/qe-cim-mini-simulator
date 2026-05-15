#!/usr/bin/env python3
"""Run the DFT-first QE DSE flow from source facts through L4 evidence.

This runner is intentionally QE-focused.  It uses the optional DFT/QE importer
for Step1 source-fact reconstruction, the reference DFT Step2 policy for
candidate-only FPGA/GPU/host hints, standalone generic_sim for Step3 timing
screening over a small architecture set, and the real gem5 GenericAccel path for
Step4.  It never converts Step1/Step2 estimates into final trusted claims; the
best architecture is selected only from measured Step3/Step4 timing artifacts
within the requested test scope.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.backends.gem5_systemc_adapter import Gem5SystemCClosureAdapter
from dse_v2.core.workload import (
    default_importer_registry,
    default_profile_registry,
    run_step1_workload_ingestion_workflow,
)
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.evidence.full_flow import (
    build_numerical_validation,
    build_phase_results,
    write_full_flow_evidence,
)
from dse_v2.mapping.step2_workflow import run_step2_architecture_mapping_workflow_from_step1
from dse_v2.reference_workloads.dft_qe import dft_qe_pw_profile, register_dft_qe_importer
from dse_v2.reference_workloads.dft_step2_policy import dft_step2_policy_registry
from dse_v2.scripts.dse.audit_dft_first_end_to_end_run import audit_run


DEFAULT_ARCHITECTURE_IDS = [
    "dft-cpu-baseline-v0",
    "dft-fpga-hbm-streaming-v0",
    "dft-fpga-fft-grid-v0",
    "dft-fpga-systolic-gemm-v0",
    "dft-fpga-gpu-diag-hybrid-v0",
    "dft-memory-rich-hbm-v0",
    "dft-low-power-fpga-v0",
]


_PATH_CONTENT_KEYS = {
    "input_path": "input",
    "pw_input_path": "pw_input",
    "log_path": "log",
    "pw_log_path": "pw_log",
    "profile_path": "profile",
}


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_completion_audit(run_dir: Path) -> Dict[str, Any]:
    audit = audit_run(run_dir)
    _write_json(run_dir / "dft_end_to_end_audit.json", audit)
    return audit


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json_or_text(path: Path) -> Any:
    text = _read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _path_from_payload(base_dir: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base_dir / path)


def _materialize_stage_paths(stage: Mapping[str, Any], *, base_dir: Path) -> Dict[str, Any]:
    """Load stage *_path references while preserving source paths for provenance."""

    materialized = dict(stage)
    for path_key, content_key in _PATH_CONTENT_KEYS.items():
        if path_key not in materialized or content_key in materialized:
            continue
        path = _path_from_payload(base_dir, materialized[path_key])
        materialized[content_key] = _read_json_or_text(path) if content_key == "profile" else _read_text(path)
        materialized[path_key] = str(path)
    return materialized


def _load_qe_source(args: argparse.Namespace) -> Tuple[Any, str, Dict[str, Any]]:
    """Load a QE source bundle for the DFT-first importer."""

    if args.workflow_json:
        workflow_path = Path(args.workflow_json).resolve()
        payload = json.loads(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("--workflow-json must contain a JSON object")
        stages = [
            _materialize_stage_paths(stage, base_dir=workflow_path.parent)
            if isinstance(stage, Mapping)
            else {"input": stage}
            for stage in payload.get("stages", []) or []
        ]
        source = dict(payload)
        source["stages"] = stages
        metadata = {
            "source_kind": "qe_workflow_bundle",
            "workflow_json": str(workflow_path),
            "stage_count": len(stages),
        }
        return source, "qe_workflow_bundle", metadata

    source: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {"source_kind": "qe_pw_bundle", "files": {}}
    if args.qe_input:
        path = Path(args.qe_input).resolve()
        source["input"] = _read_text(path)
        source["input_path"] = str(path)
        metadata["files"]["input"] = str(path)
    if args.qe_log:
        path = Path(args.qe_log).resolve()
        source["log"] = _read_text(path)
        source["log_path"] = str(path)
        metadata["files"]["log"] = str(path)
    if args.qe_profile:
        path = Path(args.qe_profile).resolve()
        source["profile"] = _read_json_or_text(path)
        source["profile_path"] = str(path)
        metadata["files"]["profile"] = str(path)
    if not source:
        raise ValueError("Provide --workflow-json or at least one of --qe-input/--qe-log/--qe-profile")
    return source, "qe_pw_bundle", metadata


def _process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _step3_timing_verified(
    *,
    simulator_returncode: int,
    sim_request: Mapping[str, Any],
    sim_result: Mapping[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    phase_results = build_phase_results(sim_result, sim_request)
    missing = [phase for phase, result in phase_results.items() if result.get("status") != "available"]
    numerical = build_numerical_validation(sim_request, sim_result)
    verified = bool(
        simulator_returncode == 0
        and sim_result.get("status") == "passed"
        and not missing
        and numerical.get("passed", False)
    )
    return verified, {
        "phase_results": phase_results,
        "missing_required_coverage": missing,
        "numerical_validation": {
            "status": numerical.get("status"),
            "passed": bool(numerical.get("passed", False)),
            "scope": numerical.get("scope"),
            "summary": numerical.get("summary", {}),
        },
    }


def _run_step1(
    *,
    source: Any,
    source_kind: str,
    args: argparse.Namespace,
    run_dir: Path,
):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)
    step1_dir = run_dir / "step1"
    parameters = {
        "case_id": args.case_id,
        "graph_id": args.graph_id or f"{args.case_id}_graph",
        "source_kind": source_kind,
        "static_dominance_margin": args.static_dominance_margin,
    }
    if args.user_confirmed_dominance:
        parameters["user_confirmed_dominance"] = [
            item.strip() for item in args.user_confirmed_dominance.split(",") if item.strip()
        ]
    step1 = run_step1_workload_ingestion_workflow(
        source,
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind=source_kind,
        parameters=parameters,
        output_dir=step1_dir,
        profile_registry=profiles,
        importer_registry=importers,
        source_path=str(args.workflow_json or args.qe_input or args.qe_log or args.qe_profile or ""),
    )
    return step1_dir, step1


def _run_step2_and_step3(
    *,
    step1_dir: Path,
    run_dir: Path,
    architecture_ids: Sequence[str],
    args: argparse.Namespace,
    cli_argv: Sequence[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    best: Dict[str, Any] = {}
    verified_candidates: List[Dict[str, Any]] = []
    backend = GenericSystemCBackend(executable_path=str(args.simulator), mode="standalone_systemc")
    policy_registry = dft_step2_policy_registry()

    for architecture_id in architecture_ids:
        arch_root = run_dir / "architectures" / architecture_id
        step2_dir = arch_root / "step2"
        record: Dict[str, Any] = {
            "architecture_id": architecture_id,
            "step2_dir": str(step2_dir),
            "step3_dir": str(arch_root / "step3_systemc"),
            "estimate_vs_measured_boundary": {
                "step2": "L1/L2 estimates and domain-policy hints are candidate-generation only",
                "step3": "standalone generic_sim timing run is measured tool output for this test scope",
            },
        }
        try:
            step2 = run_step2_architecture_mapping_workflow_from_step1(
                step1_dir,
                architecture_id=architecture_id,
                backend="systemc",
                evidence_mode=args.evidence_mode,
                output_dir=step2_dir,
                enable_domain_policies=True,
                domain_policy_registry=policy_registry,
                require_l4_proof=True,
                l4_reason="DFT-first QE timing candidate requires real gem5 GenericAccel L4 closure before final Step4 claim",
                beam_width=args.beam_width,
            )
        except Exception as exc:  # keep per-architecture failures isolated and reported as blockers
            record.update({
                "step2_status": "failed_exception",
                "timing_verified": False,
                "blockers": [{"id": "step2_exception", "detail": str(exc)}],
            })
            records.append(record)
            continue

        promotion = step2.artifacts.get("promotion_decision", {}) if isinstance(step2.artifacts.get("promotion_decision"), Mapping) else {}
        low_summary = step2.artifacts.get("low_fidelity_summary", {}) if isinstance(step2.artifacts.get("low_fidelity_summary"), Mapping) else {}
        architecture_artifact = step2.artifacts.get("architecture", {}) if isinstance(step2.artifacts.get("architecture"), Mapping) else {}
        record.update({
            "step2_status": step2.status,
            "promoted_for_simulation": bool(promotion.get("promoted_for_simulation", False)),
            "step3_searchable": bool(architecture_artifact.get("step3_searchable", False)),
            "step3_search_blockers": list(architecture_artifact.get("step3_search_blockers", []) or []),
            "candidate_only_reasons": list(architecture_artifact.get("candidate_only_reasons", []) or []),
            "step4_eligible": bool(
                architecture_artifact.get("step3_searchable", False)
                and "gem5_systemc" in (
                    architecture_artifact.get("architecture_instance", {}).get("simulation_bindings", {})
                    if isinstance(architecture_artifact.get("architecture_instance", {}), Mapping)
                    else {}
                )
            ),
            "review_status": promotion.get("review_status"),
            "review_required": bool(promotion.get("review_required", False)),
            "review_flags": list(promotion.get("review_flags", []) or []),
            "step2_estimated_screening": {
                "passed": bool(low_summary.get("passed", False)),
                "trusted_final_claim": False,
                "l1_artifact": str(step2_dir / "l1_evaluation_result.json"),
                "l2_artifact": str(step2_dir / "l2_evaluation_result.json"),
            },
        })
        if step2.design_point is None or step2.executable_graph is None:
            record.update({
                "timing_verified": False,
                "blockers": [{"id": "no_step2_design_point", "detail": "Step2 did not produce a replayable design point"}],
            })
            records.append(record)
            continue

        step3_dir = arch_root / "step3_systemc"
        try:
            run = backend.run_simulation(
                step2.design_point,
                step2.executable_graph,
                workload_package=step2.workload_package,
                output_dir=step3_dir,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            run = {
                "returncode": 124,
                "stdout": _process_text(exc.stdout),
                "stderr": _process_text(exc.stderr) + f"\nSimulation timed out after {args.timeout}s\n",
                "request": backend._build_request(
                    step2.design_point,
                    step2.executable_graph,
                    workload_package=step2.workload_package,
                    output_dir=step3_dir,
                ),
                "result": {"schema_version": "gsim.result.v1", "run_id": step2.design_point.design_point_id, "status": "timeout"},
                "cmd": [str(args.simulator), "--request", str(step3_dir / "simulation_request.json"), "--result", str(step3_dir / "simulation_result.raw.json")],
            }

        request_value = run.get("request")
        sim_request: Mapping[str, Any] = request_value if isinstance(request_value, Mapping) else backend._build_request(
            step2.design_point,
            step2.executable_graph,
            workload_package=step2.workload_package,
            output_dir=step3_dir,
        )
        result_value = run.get("result")
        sim_result: Mapping[str, Any] = result_value if isinstance(result_value, Mapping) else {}
        timing_verified, verification = _step3_timing_verified(
            simulator_returncode=int(run.get("returncode", 1)),
            sim_request=sim_request,
            sim_result=sim_result,
        )
        evidence = write_full_flow_evidence(
            run_dir=step3_dir,
            backend="systemc",
            evidence_mode=args.evidence_mode,
            design_point=step2.design_point,
            compute_graph=step2.executable_graph,
            simulation_request=sim_request,
            simulation_result=sim_result,
            simulator_cmd=[str(x) for x in run.get("cmd", [])],
            simulator_returncode=int(run.get("returncode", 1)),
            systemc_stdout=_process_text(run.get("stdout")),
            systemc_stderr=_process_text(run.get("stderr")),
            cli_command=["python3", "dse_v2/scripts/dse/run_dft_first_end_to_end_dse.py", *cli_argv],
            gem5_attempted=False,
            workload_package=step2.workload_package,
            codesign_candidate=step2.artifacts.get("codesign_candidate") if isinstance(step2.artifacts.get("codesign_candidate"), Mapping) else None,
        )
        metrics = sim_result.get("metrics", {}) if isinstance(sim_result.get("metrics", {}), Mapping) else {}
        latency_ms = _float_or_none(metrics.get("latency_ms"))
        record.update({
            "timing_verified": timing_verified,
            "simulator_returncode": int(run.get("returncode", 1)),
            "step3_measured_timing": {
                "latency_ms": latency_ms,
                "power_w": metrics.get("power_w"),
                "energy_j": metrics.get("energy_j"),
                "result_status": sim_result.get("status"),
                "evidence_dir": str(step3_dir),
                "simulation_result": str(step3_dir / "simulation_result.json"),
                "numerical_validation": str(step3_dir / "numerical_validation.json"),
                "verdict": str(step3_dir / "verdict.json"),
                "full_flow_trusted_final_ranking": bool(evidence.get("trusted_for_final_ranking", False)),
                "trusted_final_boundary_note": "DFT numerical/scientific correctness is not claimed by this timing-only flow",
            },
            "step3_verification": verification,
            "design_point_id": step2.design_point.design_point_id,
            "workload_package_id": step2.workload_package.workload_id,
            "_step2_result": step2,
        })
        if timing_verified and latency_ms is not None:
            verified_candidate = {
                "architecture_id": architecture_id,
                "latency_ms": latency_ms,
                "record_index": len(records),
                "step2_result": step2,
                "step3_dir": step3_dir,
            }
            verified_candidates.append(verified_candidate)
            if not best or latency_ms < best.get("latency_ms", float("inf")):
                best = dict(verified_candidate)
        records.append(record)

    if best:
        best["ranked_candidates"] = sorted(
            verified_candidates,
            key=lambda item: (float(item.get("latency_ms", float("inf"))), str(item.get("architecture_id", ""))),
        )

    # Remove live Python objects before serialization; keep a private copy in best.
    for record in records:
        record.pop("_step2_result", None)
    return records, best


def _run_step4_gem5(
    *,
    best: Mapping[str, Any],
    run_dir: Path,
    args: argparse.Namespace,
    cli_argv: Sequence[str],
) -> Dict[str, Any]:
    ranked_candidates = [
        candidate for candidate in best.get("ranked_candidates", [best])
        if isinstance(candidate, Mapping)
    ] if isinstance(best, Mapping) else []
    if not ranked_candidates or ranked_candidates[0].get("step2_result") is None:
        return {
            "attempted": False,
            "status": "blocked_no_step3_verified_candidate",
            "trusted_step4_timing": False,
            "blockers": [{"id": "no_step3_verified_candidate", "detail": "No measured Step3 candidate was available for L4 sampling"}],
        }
    if args.skip_gem5_l4:
        return {
            "attempted": False,
            "status": "skipped_by_explicit_cli_flag",
            "trusted_step4_timing": False,
            "blockers": [{"id": "skip_gem5_l4", "detail": "--skip-gem5-l4 was supplied; this is not a completion path"}],
        }

    adapter = Gem5SystemCClosureAdapter(GenericSystemCBackend(executable_path=str(args.simulator), mode="gem5_systemc"))
    attempts: List[Dict[str, Any]] = []
    selected_attempt: Optional[Dict[str, Any]] = None
    trusted_attempts: List[Dict[str, Any]] = []
    for rank, candidate in enumerate(ranked_candidates, start=1):
        step2 = candidate.get("step2_result")
        architecture_id = str(candidate.get("architecture_id", f"rank_{rank}"))
        step4_dir = run_dir / "step4_gem5" / architecture_id
        if step2 is None:
            attempts.append({
                "architecture_id": architecture_id,
                "rank": rank,
                "status": "blocked_no_step2_result",
                "trusted_step4_timing": False,
                "blockers": [{"id": "missing_step2_result", "detail": "Step3-ranked candidate lacks a live Step2 result"}],
            })
            continue
        run = adapter.run_verified_l4(
            design_point=step2.design_point,
            compute_graph=step2.executable_graph,
            workload_package=step2.workload_package,
            output_dir=step4_dir,
            gem5_binary=args.gem5_binary,
            gem5_config=args.gem5_config,
            driver_binary=args.gem5_driver,
            simulator_binary=args.simulator,
            max_ticks=args.gem5_max_ticks,
            cpu_type=args.gem5_cpu_type,
            timeout=args.timeout,
            allow_local_transport_fallback=False,
        )
        evidence = write_full_flow_evidence(
            run_dir=step4_dir,
            backend="gem5_systemc",
            evidence_mode=args.evidence_mode,
            design_point=step2.design_point,
            compute_graph=step2.executable_graph,
            simulation_request=run.get("request") if isinstance(run.get("request"), Mapping) else {},
            simulation_result=run.get("result") if isinstance(run.get("result"), Mapping) else {},
            simulator_cmd=[str(x) for x in run.get("cmd", [])],
            simulator_returncode=int(run.get("returncode", 2)),
            systemc_stdout=_process_text(run.get("stdout")),
            systemc_stderr=_process_text(run.get("stderr")),
            cli_command=["python3", "dse_v2/scripts/dse/run_dft_first_end_to_end_dse.py", *cli_argv],
            gem5_attempted=True,
            gem5_log=run.get("gem5_log") if isinstance(run.get("gem5_log"), str) else None,
            gem5_source_artifacts=(run.get("gem5_l4_transport_proof") or {}).get("source_artifacts") if isinstance(run.get("gem5_l4_transport_proof"), Mapping) else None,
            workload_package=step2.workload_package,
            codesign_candidate=step2.artifacts.get("codesign_candidate") if isinstance(step2.artifacts.get("codesign_candidate"), Mapping) else None,
        )
        proof = json.loads((step4_dir / "gem5_l4_proof.json").read_text(encoding="utf-8")) if (step4_dir / "gem5_l4_proof.json").exists() else {}
        activity = json.loads((step4_dir / "gem5_activity_summary.json").read_text(encoding="utf-8")) if (step4_dir / "gem5_activity_summary.json").exists() else {}
        blockers_path = step4_dir / "gem5_systemc_blockers.json"
        blockers = []
        if blockers_path.exists():
            blockers_payload = json.loads(blockers_path.read_text(encoding="utf-8"))
            blockers = list(blockers_payload.get("blockers", []) or []) if isinstance(blockers_payload, Mapping) else []
        checks = proof.get("checks", {}) if isinstance(proof.get("checks"), Mapping) else {}
        non_smoke = bool(
            proof.get("passed", False)
            and checks.get("stats_txt_present", False)
            and checks.get("config_present", False)
            and checks.get("nonzero_accelerator_activity", False)
            and proof.get("fallback_from_gem5") is False
        )
        attempt = {
            "architecture_id": architecture_id,
            "rank": rank,
            "step3_latency_ms": candidate.get("latency_ms"),
            "step3_dir": str(candidate.get("step3_dir")) if candidate.get("step3_dir") else None,
            "attempted": True,
            "status": "passed" if non_smoke else "blocked_or_failed",
            "trusted_step4_timing": non_smoke,
            "run_dir": str(step4_dir),
            "gem5_returncode": run.get("gem5_returncode"),
            "adapter_returncode": run.get("returncode"),
            "evidence_trusted_final_ranking": bool(evidence.get("trusted_for_final_ranking", False)),
            "proof_artifact": str(step4_dir / "gem5_l4_proof.json"),
            "stats_artifact": str(step4_dir / "stats.txt"),
            "config_artifacts": [str(path) for path in [step4_dir / "config.ini", step4_dir / "config.json"] if path.exists()],
            "command_artifact": str(step4_dir / "manifest.json"),
            "completion_artifact": str(step4_dir / "gem5_completion_descriptor.json"),
            "activity_artifact": str(step4_dir / "gem5_activity_summary.json"),
            "proof_checks": checks,
            "missing_evidence": proof.get("missing_evidence", []),
            "blockers": blockers,
            "activity_summary": activity,
        }
        attempts.append(attempt)
        if non_smoke:
            trusted_attempts.append(attempt)
            if selected_attempt is None:
                selected_attempt = attempt

    if selected_attempt is not None:
        return {
            **selected_attempt,
            "attempted": True,
            "attempts": attempts,
            "trusted_step4_candidate_count": len(trusted_attempts),
            "trusted_step4_candidates": [
                {
                    "architecture_id": attempt.get("architecture_id"),
                    "rank": attempt.get("rank"),
                    "step3_latency_ms": attempt.get("step3_latency_ms"),
                    "run_dir": attempt.get("run_dir"),
                    "trusted_step4_timing": attempt.get("trusted_step4_timing"),
                }
                for attempt in trusted_attempts
            ],
            "selection_policy": "lowest Step3-latency-ranked candidate among all requested candidates that pass real gem5 GenericAccel non-smoke proof",
        }

    return {
        "attempted": True,
        "status": "blocked_or_failed",
        "trusted_step4_timing": False,
        "attempts": attempts,
        "blockers": [
            {
                "id": "no_step4_candidate_passed",
                "detail": "No Step3-verified architecture candidate passed real gem5 GenericAccel non-smoke proof",
            }
        ],
    }


def _public_best_architecture(best: Mapping[str, Any], step4: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the public best-architecture summary with Step4 closure status."""

    if not best:
        return None
    if step4.get("trusted_step4_timing") and step4.get("architecture_id"):
        return {
            "architecture_id": step4.get("architecture_id"),
            "selected_by": "minimum measured Step3 latency among candidates that passed real gem5 GenericAccel non-smoke proof",
            "latency_ms": step4.get("step3_latency_ms", best.get("latency_ms")),
            "step3_dir": step4.get("step3_dir") or (str(best.get("step3_dir")) if best.get("step3_dir") else None),
            "step4_dir": step4.get("run_dir"),
            "estimate_vs_measured_boundary": "Step2 estimates are screening-only; final selection requires measured Step3 timing and passing Step4 real gem5 proof.",
        }
    return {
        "architecture_id": best.get("architecture_id"),
        "selected_by": "minimum measured Step3 generic_sim latency within requested architecture_ids",
        "latency_ms": best.get("latency_ms"),
        "step3_dir": str(best.get("step3_dir")) if best.get("step3_dir") else None,
        "estimate_vs_measured_boundary": "Step2 estimates are screening-only; this selection uses measured Step3 timing artifacts and is only finalized when Step4 real gem5 proof passes.",
    }


def _build_architecture_pareto_frontier(
    records: Sequence[Mapping[str, Any]],
    step4: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build a run-level architecture Pareto frontier from measured candidates.

    This is a reporting artifact over measured Step3 metrics and Step4 proof
    status.  It does not feed back into Step1 and does not imply that Step2
    estimates are trusted final claims.
    """

    trusted_step4_by_arch = {
        str(attempt.get("architecture_id")): bool(attempt.get("trusted_step4_timing"))
        for attempt in step4.get("attempts", []) or []
        if isinstance(attempt, Mapping)
    }
    candidates: List[Dict[str, Any]] = []
    for record in records:
        metrics = record.get("step3_measured_timing", {})
        if not isinstance(metrics, Mapping):
            continue
        architecture_id = str(record.get("architecture_id", ""))
        latency = _float_or_none(metrics.get("latency_ms"))
        energy = _float_or_none(metrics.get("energy_j"))
        power = _float_or_none(metrics.get("power_w"))
        if latency is None or energy is None or power is None:
            continue
        candidates.append({
            "architecture_id": architecture_id,
            "latency_ms": latency,
            "energy_j": energy,
            "power_w": power,
            "timing_verified": bool(record.get("timing_verified", False)),
            "trusted_step4_timing": trusted_step4_by_arch.get(architecture_id, False),
            "step3_dir": metrics.get("evidence_dir"),
            "objective_directions": {
                "latency_ms": "minimize",
                "energy_j": "minimize",
                "power_w": "minimize",
            },
        })

    def dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        keys = ["latency_ms", "energy_j", "power_w"]
        return all(float(left[key]) <= float(right[key]) for key in keys) and any(
            float(left[key]) < float(right[key]) for key in keys
        )

    frontier = [
        candidate for candidate in candidates
        if not any(
            other is not candidate
            and bool(other.get("timing_verified"))
            and dominates(other, candidate)
            for other in candidates
        )
    ]
    frontier.sort(key=lambda item: (
        not bool(item.get("trusted_step4_timing")),
        float(item.get("latency_ms", float("inf"))),
        float(item.get("energy_j", float("inf"))),
        str(item.get("architecture_id", "")),
    ))
    return {
        "schema_version": "dse.architecture_pareto_frontier.v1",
        "analysis_scope": "measured_step3_with_step4_trust_labels",
        "claim_boundary": "Pareto frontier is scoped to requested architecture candidates and measured run artifacts; it is not a universal architecture ranking.",
        "objective_directions": {
            "latency_ms": "minimize",
            "energy_j": "minimize",
            "power_w": "minimize",
        },
        "candidate_count": len(candidates),
        "frontier_count": len(frontier),
        "candidates": candidates,
        "frontier": frontier,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-json", type=Path, default=None, help="QE workflow bundle JSON; stage *_path keys are loaded")
    parser.add_argument("--qe-input", type=Path, default=None, help="Single-stage QE pw.x input file")
    parser.add_argument("--qe-log", type=Path, default=None, help="Single-stage QE stdout/log file")
    parser.add_argument("--qe-profile", type=Path, default=None, help="Single-stage QE timing profile JSON or text")
    parser.add_argument("--case-id", default="qe_dft_first_case")
    parser.add_argument("--graph-id", default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--architecture-ids", default=",".join(DEFAULT_ARCHITECTURE_IDS), help="Comma-separated catalog architecture IDs for Step2/Step3 screening")
    parser.add_argument("--evidence-mode", default="debug", choices=["summary", "debug", "forensic"])
    parser.add_argument("--beam-width", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--static-dominance-margin", type=float, default=4.0)
    parser.add_argument("--user-confirmed-dominance", default="", help="Comma-separated phase IDs confirmed by a domain reviewer")
    parser.add_argument("--simulator", type=Path, default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim")
    parser.add_argument("--gem5-binary", type=Path, default=REPO_ROOT / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt")
    parser.add_argument("--gem5-config", type=Path, default=REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py")
    parser.add_argument("--gem5-driver", type=Path, default=REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver")
    parser.add_argument("--gem5-cpu-type", default="atomic", choices=["atomic", "timing"])
    parser.add_argument("--gem5-max-ticks", type=int, default=10_000_000_000)
    parser.add_argument("--skip-gem5-l4", action="store_true", help="Development-only: stop after Step3 and mark Step4 untrusted/skipped")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    cli_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(cli_argv)
    run_dir = (args.out or (REPO_ROOT / "runs" / "dse" / f"dft_first_qe_{_now_tag()}")).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        source, source_kind, source_metadata = _load_qe_source(args)
    except Exception as exc:
        summary = {
            "schema_version": "dse.dft_end_to_end_summary.v1",
            "status": "blocked_source_load",
            "run_dir": str(run_dir),
            "source": {
                "source_kind": "unavailable",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            "scope": {
                "workload_focus": "QE pw.x/source-fact DFT-first flow only",
                "domain_neutral_core": True,
                "dft_logic_location": "dse_v2/reference_workloads",
                "trusted_final_dft_correctness_claimed": False,
                "claim_boundary": "source loading failed before any DSE timing or DFT correctness claim",
            },
            "completion": {
                "end_to_end_timing_complete": False,
                "requires_real_gem5_non_smoke": True,
                "trusted_final_dft_correctness_claimed": False,
            },
        }
        _write_json(run_dir / "dft_end_to_end_summary.json", summary)
        audit = _write_completion_audit(run_dir)
        print(json.dumps({
            "run_dir": str(run_dir),
            "status": summary["status"],
            "source": summary["source"],
            "audit": {
                "status": audit.get("status"),
                "check_count": audit.get("check_count"),
                "failed_count": audit.get("failed_count"),
                "artifact": str(run_dir / "dft_end_to_end_audit.json"),
            },
        }, indent=2, sort_keys=True))
        return 2

    step1_dir, step1 = _run_step1(source=source, source_kind=source_kind, args=args, run_dir=run_dir)
    if step1.status != "complete":
        summary = {
            "schema_version": "dse.dft_end_to_end_summary.v1",
            "status": "blocked_step1",
            "source": source_metadata,
            "step1": {"status": step1.status, "run_dir": str(step1_dir)},
            "completion": {"end_to_end_timing_complete": False, "trusted_final_dft_correctness_claimed": False},
        }
        _write_json(run_dir / "dft_end_to_end_summary.json", summary)
        _write_completion_audit(run_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 2

    architecture_ids = [item.strip() for item in args.architecture_ids.split(",") if item.strip()]
    records, best = _run_step2_and_step3(
        step1_dir=step1_dir,
        run_dir=run_dir,
        architecture_ids=architecture_ids,
        args=args,
        cli_argv=cli_argv,
    )
    step4 = _run_step4_gem5(best=best, run_dir=run_dir, args=args, cli_argv=cli_argv)
    pareto_frontier = _build_architecture_pareto_frontier(records, step4)
    _write_json(run_dir / "architecture_pareto_frontier.json", pareto_frontier)
    best_public = _public_best_architecture(best, step4)
    step3_best_public = {
        "architecture_id": best.get("architecture_id"),
        "selected_by": "minimum measured Step3 generic_sim latency within requested architecture_ids",
        "latency_ms": best.get("latency_ms"),
        "step3_dir": str(best.get("step3_dir")) if best.get("step3_dir") else None,
        "estimate_vs_measured_boundary": "Step2 estimates are screening-only; Step3 ranking still requires Step4 real gem5 closure for final trust.",
    } if best else None
    summary = {
        "schema_version": "dse.dft_end_to_end_summary.v1",
        "status": "complete" if step4.get("trusted_step4_timing") else "blocked_or_untrusted_step4",
        "run_dir": str(run_dir),
        "source": source_metadata,
        "scope": {
            "workload_focus": "QE pw.x/source-fact DFT-first flow only",
            "domain_neutral_core": True,
            "dft_logic_location": "dse_v2/reference_workloads",
            "trusted_final_dft_correctness_claimed": False,
            "claim_boundary": "timing/evidence only; no DFT numerical/scientific correctness claim",
        },
        "step1": {"status": step1.status, "run_dir": str(step1_dir), "facts_only": True},
        "step2_step3_records": records,
        "step3_best_architecture": step3_best_public,
        "architecture_pareto_frontier": {
            "artifact": str(run_dir / "architecture_pareto_frontier.json"),
            "frontier_count": pareto_frontier.get("frontier_count"),
            "candidate_count": pareto_frontier.get("candidate_count"),
            "claim_boundary": pareto_frontier.get("claim_boundary"),
        },
        "best_architecture": best_public,
        "step4_gem5": step4,
        "completion": {
            "end_to_end_timing_complete": bool(step4.get("trusted_step4_timing", False)),
            "requires_real_gem5_non_smoke": True,
            "stats_config_command_completion_activity_required": True,
            "trusted_final_dft_correctness_claimed": False,
        },
    }
    _write_json(run_dir / "dft_end_to_end_summary.json", summary)
    audit = _write_completion_audit(run_dir)
    print(json.dumps({
        "run_dir": str(run_dir),
        "status": summary["status"],
        "best_architecture": best_public,
        "audit": {
            "status": audit.get("status"),
            "check_count": audit.get("check_count"),
            "failed_count": audit.get("failed_count"),
            "artifact": str(run_dir / "dft_end_to_end_audit.json"),
        },
        "step4_gem5": {k: v for k, v in step4.items() if k not in {"activity_summary", "proof_checks"}},
    }, indent=2, sort_keys=True))
    if args.skip_gem5_l4:
        return 2
    return 0 if step4.get("trusted_step4_timing") and audit.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
