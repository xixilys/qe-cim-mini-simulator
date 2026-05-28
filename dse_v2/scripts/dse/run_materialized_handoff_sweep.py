#!/usr/bin/env python3
"""Explicitly execute Step2-materialized candidates as independent full-flow runs.

This is the opt-in bridge from Campaign/Search materialization to comparative
Step3/Step4 feedback.  It never treats `campaign_materialization_summary.json`
or Top-K provenance as Step3 authority by itself; every executed row is staged
through `run_full_flow_pilot.py --step2-handoff-dir ...`, where the materialized
candidate's own `step3_simulation_queue.json` becomes the canonical authority
for exactly that run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PILOT = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_full_flow_pilot.py"
MATERIALIZATION_REQUEST_FILENAME = "campaign_materialization_request.json"

from dse_v2.contracts import CONTRACT_VERSION, SCHEMA_REGISTRY, validate_instance
from dse_v2.dse.campaign_manager import build_campaign_search_admission_plan
from dse_v2.dse.materialization_coverage import build_materialization_coverage_audit
from dse_v2.mapping.search_policy import build_search_iteration_plan, search_checkpoint_from_iteration_plan
from dse_v2.scripts.dse.audit_search_feedback_loop import (
    build_search_effectiveness_audit,
    build_search_loop_audit_summary,
)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _validate_registered_schema(payload: Mapping[str, Any], schema_id: str) -> None:
    if schema_id in SCHEMA_REGISTRY:
        validate_instance(payload, SCHEMA_REGISTRY[schema_id])


def _run_step2_campaign_materialization_request(*args: Any, **kwargs: Any) -> Any:
    """Load the optional Step2 writer only when materialization is requested.

    Importing this sweep module must remain cheap and fail-closed for auditors
    that only need helper functions.  If the writer surface is unavailable at
    runtime, the caller's per-request exception handler records the blocker
    instead of turning Top-K provenance into implicit execution authority.
    """

    from dse_v2.mapping.step2_workflow import run_step2_campaign_materialization_request

    return run_step2_campaign_materialization_request(*args, **kwargs)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _has_dft_template_candidates(search_iteration_plan: Mapping[str, Any]) -> bool:
    """Return true when a SearchPolicy plan contains DFT template-level rows.

    Generic Campaign admission is intentionally fail-closed for abstract/profile
    templates.  The handoff sweep is the point where Step4 feedback creates the
    next SearchPolicy plan, so it is also the last safe point to run the
    DFT-scoped adapter that binds profile templates to real generic Step2
    selectors before Campaign admission.  Non-DFT plans must remain untouched.
    """

    for candidate in search_iteration_plan.get("next_candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        parameters = _as_mapping(candidate.get("parameters"))
        if parameters.get("template_family"):
            return True
    problem = _as_mapping(search_iteration_plan.get("search_policy_problem"))
    problem_id = str(search_iteration_plan.get("problem_id") or problem.get("problem_id") or "")
    return problem_id.endswith(":dft_hardware_hierarchical_funnel")


def _maybe_bind_dft_template_search_iteration_plan(
    search_iteration_plan: Mapping[str, Any],
    *,
    step2_dir: Path,
) -> Dict[str, Any]:
    """Bind DFT template rows to concrete Step2 selectors when needed.

    This keeps the generic Campaign code domain-neutral: Campaign still only
    accepts rows that carry generic architecture/mapping selectors, while the
    DFT reference adapter owns the profile/template-specific bridge.  If no DFT
    template rows are present, the plan is returned unchanged.
    """

    plan = dict(search_iteration_plan)
    if not _has_dft_template_candidates(plan):
        return plan

    from dse_v2.architecture.catalog import seed_generic_dse_architecture_catalog
    from dse_v2.reference_workloads.dft_step2_policy import (
        bind_dft_template_search_iteration_plan_to_step2_selectors,
    )

    bound_plan = bind_dft_template_search_iteration_plan_to_step2_selectors(
        plan,
        step2_dir=step2_dir,
        catalog=seed_generic_dse_architecture_catalog(),
    )
    if isinstance(bound_plan.get("dft_template_binding_report"), Mapping):
        bound_plan["dft_template_binding_report_ref"] = "dft_template_binding_report.json"
    bound_plan["execution_allowed"] = False
    bound_plan["hidden_evidence_fanout_allowed"] = False
    bound_plan["trusted_final_claim"] = False
    bound_plan["release_completion_eligible"] = False
    return bound_plan


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_if_exists(path: Path) -> str | None:
    return _file_sha256(path) if path.exists() and path.is_file() else None


def _materialization_request_paths_for_row(
    row: Mapping[str, Any],
    *,
    source_run_dir: Path,
) -> List[Path]:
    """Return canonical request locations allowed to define a sweep row.

    The explicit sweep must not search through multiple possible request files
    when building feedback.  The row records one authoritative path/hash at
    planning time; this helper only provides the canonical path set used to
    validate that the recorded authority still points at the materialized
    handoff the row was launched from.
    """

    paths: List[Path] = []
    handoff_dir_raw = str(row.get("handoff_dir") or "")
    if handoff_dir_raw:
        paths.append((Path(handoff_dir_raw).resolve() / MATERIALIZATION_REQUEST_FILENAME).resolve())
    source_materialized_dir = str(row.get("source_materialized_dir") or "")
    if source_materialized_dir:
        paths.append((source_run_dir / source_materialized_dir / MATERIALIZATION_REQUEST_FILENAME).resolve())

    deduped: List[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _authoritative_materialization_request(
    row: Mapping[str, Any],
    *,
    source_run_dir: Path,
) -> tuple[Path, str]:
    """Validate and return the single request file allowed for feedback.

    A feedback update is only valid if the sweep row still matches the exact
    materialization request path/hash recorded before the child run.  This keeps
    the feedback loop fail-closed if a copied child artifact, sibling handoff,
    or source materialized directory diverges.
    """

    canonical_paths = _materialization_request_paths_for_row(row, source_run_dir=source_run_dir)
    if not canonical_paths:
        raise ValueError("missing_canonical_materialization_request_path")

    declared_raw = str(row.get("authoritative_request_path") or "")
    if not declared_raw:
        raise ValueError("missing_authoritative_materialization_request_path")
    declared_path = Path(declared_raw).resolve()
    if declared_path not in canonical_paths:
        expected = ", ".join(str(path) for path in canonical_paths)
        raise ValueError(
            "authoritative_materialization_request_path_mismatch: "
            f"{declared_path} not in [{expected}]"
        )

    declared_hash = str(row.get("authoritative_request_sha256") or "")
    if not declared_hash:
        raise ValueError("missing_authoritative_materialization_request_sha256")
    actual_hash = _hash_if_exists(declared_path)
    if not actual_hash:
        raise FileNotFoundError(f"missing_authoritative_materialization_request: {declared_path}")
    if actual_hash != declared_hash:
        raise ValueError(
            "authoritative_materialization_request_hash_mismatch: "
            f"{declared_path} expected {declared_hash} got {actual_hash}"
        )
    return declared_path, actual_hash


def _rel_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _safe_path_segment(value: Any, *, fallback: str = "candidate") -> str:
    raw = str(value or fallback)
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in raw)
    safe = safe.strip("-_.") or fallback
    if len(safe) <= 80:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{safe[:64].rstrip('-_.')}-{digest}"


def _generator_for_profile(profile_id: str) -> str:
    return {
        "ml_tensor": "tensor_chain",
        "sparse_la": "sparse_spmv",
        "stencil_streaming": "stencil_streaming",
        "graph_analytics": "graph_analytics",
        "database_vector_search": "vector_search",
        "dynamic_custom": "dynamic_custom",
        "qe_scf_reference": "qe_scf_reference",
    }.get(profile_id, "tensor_chain")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", type=Path, required=True, help="Run directory containing campaign_materialization_summary.json")
    parser.add_argument("--out", type=Path, required=True, help="Directory for sweep runs and materialized_handoff_sweep_summary.json")
    parser.add_argument("--limit", type=int, default=None, help="Maximum materialized candidates to execute")
    parser.add_argument("--plan-only", action="store_true", help="Write the sweep plan without launching Step3/Step4 runs")
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT, help="run_full_flow_pilot.py path")
    parser.add_argument("--python", default=sys.executable, help="Python executable used for child full-flow runs")
    parser.add_argument("--subprocess-timeout", type=int, default=120, help="Timeout in seconds for each child pilot run")
    parser.add_argument(
        "--materialize-next-requests",
        action="store_true",
        help=(
            "After applying sweep feedback, replay the next Campaign step2_iteration_requests "
            "through the Step2 writer into this sweep output directory. This prepares a next "
            "source-run directory but still does not execute Step3."
        ),
    )

    parser.add_argument("--workload", default=None, help="Optional workload alias forwarded to run_full_flow_pilot.py")
    parser.add_argument("--profile", default=None, help="Optional profile id forwarded to run_full_flow_pilot.py")
    parser.add_argument("--importer", default=None, help="Optional importer id forwarded to run_full_flow_pilot.py")
    parser.add_argument("--source-kind", default=None, help="Optional source kind forwarded to run_full_flow_pilot.py")
    parser.add_argument("--generator", default=None, help="Optional generated fixture forwarded to run_full_flow_pilot.py")
    parser.add_argument("--backend", default=None, choices=["systemc", "gem5_systemc"], help="Backend forwarded to run_full_flow_pilot.py")
    parser.add_argument("--evidence-mode", default=None, choices=["summary", "debug", "forensic"], help="Evidence mode forwarded to run_full_flow_pilot.py")
    parser.add_argument("--npw", type=int, default=None)
    parser.add_argument("--nkb", type=int, default=None)
    parser.add_argument("--m", type=int, default=None)
    parser.add_argument("--nfft", type=int, default=None)
    parser.add_argument("--simulator", type=Path, default=None)
    return parser.parse_args(list(argv))


def _source_defaults(source_run_dir: Path) -> Dict[str, Any]:
    step1_status = _load_json(source_run_dir / "step1" / "step1_status.json")
    ingestion_request = _load_json(source_run_dir / "step1" / "ingestion_request.json")
    campaign = _load_json(source_run_dir / "campaign.json")
    parameters = ingestion_request.get("parameters", {}) if isinstance(ingestion_request.get("parameters", {}), Mapping) else {}
    budgets = campaign.get("budgets", {}) if isinstance(campaign.get("budgets", {}), Mapping) else {}
    profile_id = str(step1_status.get("profile_id") or parameters.get("profile_id") or "ml_tensor")
    importer_id = str(step1_status.get("importer_id") or parameters.get("importer_id") or "generic_json")
    source_kind = str(step1_status.get("source_kind") or parameters.get("source_kind") or "generated")
    return {
        "profile": profile_id,
        "importer": importer_id,
        "source_kind": source_kind,
        "generator": _generator_for_profile(profile_id),
        "backend": str(budgets.get("backend") or "systemc"),
        "evidence_mode": str(budgets.get("evidence_mode") or "debug"),
        "npw": parameters.get("npw"),
        "nkb": parameters.get("nkb"),
        "m": parameters.get("m"),
        "nfft": parameters.get("nfft"),
    }


def _pilot_base_args(args: argparse.Namespace, source_run_dir: Path) -> List[str]:
    defaults = _source_defaults(source_run_dir)
    command: List[str] = [str(args.python), str(args.pilot)]
    if args.workload:
        command.extend(["--workload", str(args.workload)])
    else:
        command.extend([
            "--profile",
            str(args.profile or defaults["profile"]),
            "--importer",
            str(args.importer or defaults["importer"]),
            "--source-kind",
            str(args.source_kind or defaults["source_kind"]),
            "--generator",
            str(args.generator or defaults["generator"]),
        ])

    command.extend([
        "--backend",
        str(args.backend or defaults["backend"]),
        "--evidence-mode",
        str(args.evidence_mode or defaults["evidence_mode"]),
    ])
    for field in ("npw", "nkb", "m", "nfft"):
        value = getattr(args, field)
        if value is None:
            value = defaults.get(field)
        if value not in (None, ""):
            command.extend([f"--{field}", str(int(value))])
    if args.simulator is not None:
        command.extend(["--simulator", str(args.simulator)])
    return command


def _materialization_rows(source_run_dir: Path, *, limit: int | None) -> List[Dict[str, Any]]:
    summary_path = source_run_dir / "campaign_materialization_summary.json"
    summary = _load_json(summary_path)
    if not summary:
        raise FileNotFoundError(f"missing campaign_materialization_summary.json in {source_run_dir}")
    rows: List[Dict[str, Any]] = []
    for materialization in summary.get("materializations", []) or []:
        if not isinstance(materialization, Mapping):
            continue
        if materialization.get("materialization_status") != "materialized_by_step2_writer":
            continue
        if not bool(materialization.get("canonical_step3_queue_written", False)):
            continue
        materialized_dir = str(materialization.get("materialized_dir") or "")
        if not materialized_dir:
            continue
        handoff_dir = (source_run_dir / materialized_dir).resolve()
        rows.append({
            "source_materialization": dict(materialization),
            "handoff_dir": handoff_dir,
            "source_materialized_dir": materialized_dir,
        })
        if limit is not None and len(rows) >= max(0, int(limit)):
            break
    return rows


def _row_metrics(run_dir: Path) -> Dict[str, Any]:
    simulation_result = _load_json(run_dir / "simulation_result.json")
    simulation_request = _load_json(run_dir / "simulation_request.json")
    verdict = _load_json(run_dir / "verdict.json")
    handoff_source = _load_json(run_dir / "explicit_step2_handoff_source.json")
    metrics = simulation_result.get("metrics", {}) if isinstance(simulation_result.get("metrics", {}), Mapping) else {}
    translation = simulation_request.get("candidate_translation", {}) if isinstance(simulation_request.get("candidate_translation", {}), Mapping) else {}
    return {
        "simulation_status": simulation_result.get("status"),
        "simulator_returncode": simulation_result.get("simulator_returncode"),
        "metrics": {
            "latency_ms": metrics.get("latency_ms"),
            "energy_j": metrics.get("energy_j"),
            "power_w": metrics.get("power_w"),
            "total_data_movement_mb": metrics.get("total_data_movement_mb"),
        },
        "candidate_translation": {
            "candidate_id": translation.get("candidate_id"),
            "mapping_id": translation.get("mapping_id"),
            "architecture_id": translation.get("architecture_id"),
            "step2_handoff_present": translation.get("step2_handoff_present"),
        },
        "trusted_for_final_ranking": verdict.get("trusted_for_final_ranking"),
        "handoff_source_binding_status": handoff_source.get("source_binding_status"),
    }


def _materialization_coverage_audit(
    *,
    out_dir: Path,
    requests: Sequence[Mapping[str, Any]],
    materialized_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Check that requested candidates were materialized into authorized Step3 queues."""

    return build_materialization_coverage_audit(
        out_dir=out_dir,
        requests=requests,
        materialized_records=materialized_records,
    )


def _search_loop_audit_run_dirs(*, source_run_dir: Path, out_dir: Path) -> List[Path]:
    """Return ordered sweep dirs that should define the current loop summary."""

    ordered: List[Path] = []
    source_summary = _load_json(source_run_dir / "materialized_handoff_sweep_summary.json")
    for raw in source_summary.get("search_loop_audit_run_dirs", []) or []:
        if not raw:
            continue
        ordered.append(Path(str(raw)).resolve())
    if (
        (source_run_dir / "search_feedback_closure_audit.json").exists()
        or (source_run_dir / "search_replay_safety_audit.json").exists()
    ):
        ordered.append(source_run_dir.resolve())
    ordered.append(out_dir.resolve())

    deduped: List[Path] = []
    seen: set[Path] = set()
    for run_dir in ordered:
        if run_dir in seen:
            continue
        seen.add(run_dir)
        deduped.append(run_dir)
    return deduped


def _copy_step2_replay_context(*, source_run_dir: Path, out_dir: Path) -> List[str]:
    """Carry source Step2 context so the sweep output can seed the next round.

    The fresh search checkpoint is written from feedback later in the sweep, so
    this deliberately does not copy the source `search_checkpoint.json`.
    """

    source_step2_dir = source_run_dir / "step2"
    target_step2_dir = out_dir / "step2"
    copied: List[str] = []
    if not source_step2_dir.exists():
        return copied
    target_step2_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_step2_dir.iterdir()):
        if not source_path.is_file():
            continue
        if source_path.name == "search_checkpoint.json":
            continue
        target_path = target_step2_dir / source_path.name
        if target_path.exists():
            continue
        shutil.copy2(source_path, target_path)
        copied.append(_rel_to(target_path, out_dir))
    return copied


def _materialize_next_campaign_requests(
    *,
    source_run_dir: Path,
    out_dir: Path,
    campaign_search_admission_plan: Mapping[str, Any],
    backend: str,
    evidence_mode: str,
) -> Dict[str, Any]:
    """Replay the next Campaign step2 requests into a fresh source directory.

    This keeps the search loop re-playable: the output directory gains a
    canonical ``campaign_materialization_summary.json`` plus the new search
    checkpoint after feedback so a later sweep can continue from the updated
    frontier.  It still stops before any Step3 execution.
    """

    requests = [
        request
        for request in campaign_search_admission_plan.get("step2_iteration_requests", []) or []
        if isinstance(request, Mapping)
    ]
    materialization_root = out_dir / "step2" / "materialized_candidates"
    materialization_root.mkdir(parents=True, exist_ok=True)
    materialized_records: List[Dict[str, Any]] = []
    artifact_paths: List[str] = ["campaign_materialization_summary.json"]
    artifact_paths.extend(_copy_step2_replay_context(source_run_dir=source_run_dir, out_dir=out_dir))

    for index, request in enumerate(requests, start=1):
        request_id = str(request.get("request_id") or f"request-{index}")
        materialized_dir = materialization_root / _safe_path_segment(request_id, fallback=f"request-{index}")
        record: Dict[str, Any] = {
            "request_id": request_id,
            "requested_action": str(request.get("requested_action") or ""),
            "materialized_dir": _rel_to(materialized_dir, out_dir),
            "canonical_step3_admission_authority": "step3_simulation_queue.json",
            "execution_allowed": False,
            "hidden_evidence_fanout_allowed": False,
            "release_completion_eligible": False,
            "trusted_final_claim": False,
        }
        try:
            result = _run_step2_campaign_materialization_request(
                source_run_dir / "step2",
                request,
                output_dir=materialized_dir,
                campaign_search_admission_plan=campaign_search_admission_plan,
                backend=backend,
                evidence_mode=evidence_mode,
            )
            report = (
                result.artifacts.get("campaign_materialization_report", {})
                if isinstance(result.artifacts.get("campaign_materialization_report", {}), Mapping)
                else {}
            )
            record.update({
                "status": result.status,
                "materialization_status": report.get("materialization_status"),
                "canonical_step3_queue_written": bool(report.get("canonical_step3_queue_written", False)),
                "selected_candidate_id": report.get("selected_candidate_id"),
                "materialized_artifacts": list(report.get("materialized_artifacts", []) or []),
                "campaign_materialization_request_ref": _rel_to(materialized_dir / "campaign_materialization_request.json", out_dir),
                "campaign_materialization_report_ref": _rel_to(materialized_dir / "campaign_materialization_report.json", out_dir),
                "step3_simulation_queue_ref": _rel_to(materialized_dir / "step3_simulation_queue.json", out_dir),
            })
            for rel_path in result.artifact_paths.values():
                if rel_path:
                    artifact_paths.append(_rel_to(materialized_dir / str(rel_path), out_dir))
        except Exception as exc:  # pragma: no cover - integration failures only
            record.update({
                "status": "blocked_materialization_exception",
                "materialization_status": "blocked_by_step2_writer_exception",
                "canonical_step3_queue_written": False,
                "error": str(exc),
            })
        materialized_records.append(record)

    materialization_coverage = _materialization_coverage_audit(
        out_dir=out_dir,
        requests=requests,
        materialized_records=materialized_records,
    )
    summary = {
        "schema_version": "dse.campaign.materialization_summary.v1",
        "plan_id": str(campaign_search_admission_plan.get("plan_id") or ""),
        "campaign_id": str(campaign_search_admission_plan.get("campaign_id") or ""),
        "workload_run_id": str(campaign_search_admission_plan.get("workload_run_id") or ""),
        "trial_id": str(campaign_search_admission_plan.get("trial_id") or ""),
        "request_count": len(requests),
        "materialized_count": sum(
            1
            for record in materialized_records
            if record.get("materialization_status") == "materialized_by_step2_writer"
        ),
        "blocked_count": sum(
            1
            for record in materialized_records
            if record.get("materialization_status") != "materialized_by_step2_writer"
        ),
        "materialized_root": _rel_to(materialization_root, out_dir),
        "canonical_step3_admission_authority": "step2/step3_simulation_queue.json",
        "materialization_coverage": materialization_coverage,
        "coverage_closed": bool(materialization_coverage["coverage_closed"]),
        "authorized_step3_queue_entry_count": int(materialization_coverage["authorized_step3_queue_entry_count"]),
        "materialization_coverage_blocker_count": int(materialization_coverage["blocker_count"]),
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "broad_evidence_run": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "materializations": materialized_records,
        "resume_next_actions": [
            "inspect materialized_candidates/*/step3_simulation_queue.json before admitting any new Step3 work",
            "merge or select canonical Step2 queue entries explicitly before running Step3",
            "do not treat this materialization summary as simulation evidence",
        ],
        "claim_boundary": (
            "Campaign materialization replays requested candidates through the Step2 writer only; "
            "it writes replayable Step2 handoff artifacts but does not execute Step3 evidence."
        ),
    }
    _write_json(out_dir / "campaign_materialization_summary.json", summary)
    artifact_paths.append("campaign_materialization_summary.json")

    search_checkpoint_after_feedback = search_checkpoint_from_iteration_plan(
        search_iteration_plan=_load_json(out_dir / "search_iteration_plan.json"),
        campaign_id=str(campaign_search_admission_plan.get("campaign_id") or ""),
        workload_run_id=str(campaign_search_admission_plan.get("workload_run_id") or ""),
        trial_id=str(campaign_search_admission_plan.get("trial_id") or ""),
        refs={
            "search_iteration_plan": "search_iteration_plan.json",
            "feedback_update": "feedback_update.json",
            "calibration_record": "calibration_record.json",
            "campaign_materialization_summary": "campaign_materialization_summary.json",
        },
    )
    _write_json(out_dir / "step2" / "search_checkpoint.json", search_checkpoint_after_feedback)
    artifact_paths.append("step2/search_checkpoint.json")
    if (source_run_dir / "campaign_evaluation_plan.json").exists():
        _write_json(out_dir / "campaign_evaluation_plan.json", _load_json(source_run_dir / "campaign_evaluation_plan.json"))
        artifact_paths.append("campaign_evaluation_plan.json")
    if (source_run_dir / "calibration_record.json").exists():
        _write_json(out_dir / "calibration_record.json", _load_json(source_run_dir / "calibration_record.json"))
        artifact_paths.append("calibration_record.json")
    return {
        "written": True,
        "summary_ref": "campaign_materialization_summary.json",
        "search_checkpoint_ref": "step2/search_checkpoint.json",
        "request_count": len(requests),
        "materialized_count": summary["materialized_count"],
        "blocked_count": summary["blocked_count"],
        "coverage_closed": bool(materialization_coverage["coverage_closed"]),
        "authorized_step3_queue_entry_count": int(materialization_coverage["authorized_step3_queue_entry_count"]),
        "coverage_blocker_count": int(materialization_coverage["blocker_count"]),
        "artifact_paths": list(dict.fromkeys(artifact_paths)),
    }


def _materialized_handoff_feedback_update(
    *,
    source_run_dir: Path,
    out_dir: Path,
    run_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    source_search_checkpoint = _load_json(source_run_dir / "step2" / "search_checkpoint.json")
    source_summary_path = source_run_dir / "campaign_materialization_summary.json"
    source_artifact_hashes: Dict[str, str] = {}
    source_summary_hash = _hash_if_exists(source_summary_path)
    if source_summary_hash:
        source_artifact_hashes["source/campaign_materialization_summary.json"] = source_summary_hash
    search_checkpoint_path = source_run_dir / "step2" / "search_checkpoint.json"
    search_checkpoint_hash = _hash_if_exists(search_checkpoint_path)
    if search_checkpoint_hash:
        source_artifact_hashes["source/step2/search_checkpoint.json"] = search_checkpoint_hash
    calibration_record_path = source_run_dir / "calibration_record.json"
    calibration_record_hash = _hash_if_exists(calibration_record_path)
    if calibration_record_hash:
        source_artifact_hashes["source/calibration_record.json"] = calibration_record_hash

    updates: List[Dict[str, Any]] = []
    for row in run_rows:
        if row.get("returncode") is None:
            continue
        run_dir = Path(str(row.get("run_dir") or "")).resolve()
        authoritative_request_path, authoritative_request_hash = _authoritative_materialization_request(
            row,
            source_run_dir=source_run_dir,
        )
        request = _load_json(authoritative_request_path)
        copied_request_path = run_dir / "step2" / MATERIALIZATION_REQUEST_FILENAME
        copied_request_hash = _hash_if_exists(copied_request_path)
        if copied_request_hash and copied_request_hash != authoritative_request_hash:
            raise ValueError(
                "materialized_handoff_request_copy_hash_mismatch: "
                f"{copied_request_path} expected {authoritative_request_hash} got {copied_request_hash}"
            )
        simulation_request = _load_json(run_dir / "simulation_request.json")
        candidate_translation = _as_mapping(row.get("candidate_translation"))
        verdict = _load_json(run_dir / "verdict.json")
        materialization_inputs = _as_mapping(request.get("materialization_inputs"))
        simulation_passed = row.get("returncode") == 0 and str(row.get("simulation_status") or "") == "passed"
        trusted_sample = bool(row.get("trusted_for_final_ranking")) and simulation_passed
        status = "available" if simulation_passed else ("failed" if row.get("returncode") else "blocked")
        search_policy_candidate_id = str(
            request.get("search_policy_candidate_id")
            or materialization_inputs.get("search_policy_candidate_id")
            or row.get("selected_candidate_id")
            or ""
        )
        search_policy_parameter_hash = str(
            request.get("search_policy_parameter_hash")
            or materialization_inputs.get("search_policy_parameter_hash")
            or ""
        )
        mapping_candidate_id = str(
            request.get("mapping_candidate_id")
            or materialization_inputs.get("mapping_candidate_id")
            or row.get("selected_candidate_id")
            or ""
        )
        mapping_parameter_hash = str(
            request.get("mapping_parameter_hash")
            or materialization_inputs.get("mapping_parameter_hash")
            or ""
        )
        materialized_architecture_candidate_id = str(
            request.get("materialized_architecture_candidate_id")
            or materialization_inputs.get("materialized_architecture_candidate_id")
            or ""
        )
        architecture_parameter_hash = str(
            request.get("architecture_parameter_hash")
            or materialization_inputs.get("architecture_parameter_hash")
            or ""
        )
        architecture_instance_hash = str(
            request.get("architecture_instance_hash")
            or materialization_inputs.get("architecture_instance_hash")
            or ""
        )
        parent_search_policy_candidate_id = str(
            request.get("parent_search_policy_candidate_id")
            or materialization_inputs.get("parent_search_policy_candidate_id")
            or ""
        )
        parent_search_policy_parameter_hash = str(
            request.get("parent_search_policy_parameter_hash")
            or materialization_inputs.get("parent_search_policy_parameter_hash")
            or ""
        )
        source_proposal_hash = str(
            request.get("source_proposal_hash")
            or materialization_inputs.get("source_proposal_hash")
            or ""
        )
        source_proposal_id = str(
            request.get("source_proposal_id")
            or materialization_inputs.get("source_proposal_id")
            or ""
        )
        feedback_candidate_id = (
            mapping_candidate_id
            or str(row.get("selected_candidate_id") or "")
            or search_policy_candidate_id
            or materialized_architecture_candidate_id
        )
        candidate_refs = {
            "candidate_id": feedback_candidate_id,
            "selected_candidate_id": str(row.get("selected_candidate_id") or ""),
            "search_policy_candidate_id": search_policy_candidate_id,
            "search_policy_parameter_hash": search_policy_parameter_hash,
            "parent_search_policy_candidate_id": parent_search_policy_candidate_id,
            "parent_search_policy_parameter_hash": parent_search_policy_parameter_hash,
            "mapping_candidate_id": mapping_candidate_id,
            "mapping_parameter_hash": mapping_parameter_hash,
            "mapping_id": str(candidate_translation.get("mapping_id") or request.get("mapping_id") or ""),
            "architecture_id": str(
                candidate_translation.get("architecture_id")
                or request.get("architecture_id")
                or materialization_inputs.get("architecture_id")
                or ""
            ),
            "materialized_architecture_candidate_id": materialized_architecture_candidate_id,
            "architecture_parameter_hash": architecture_parameter_hash,
            "architecture_instance_hash": architecture_instance_hash,
            "source_proposal_hash": source_proposal_hash,
            "source_proposal_id": source_proposal_id,
            "design_point_id": str(_as_mapping(simulation_request.get("design_point")).get("design_point_id") or ""),
        }
        metrics = dict(_as_mapping(row.get("metrics")))
        metrics.update({
            "trusted_sample": trusted_sample,
            "promoted": trusted_sample,
            "step4_verdict": "trusted_pass" if trusted_sample else (
                str(verdict.get("step4_verdict") or row.get("simulation_status") or status or "blocked_or_untrusted")
            ),
            "step4_quality_score": 80.0 if trusted_sample else 0.0,
            "calibrated_score_delta": 1.0 if trusted_sample else -1.0,
        })
        if not simulation_passed:
            metrics["search_feedback_failure_reason"] = (
                "sweep_child_returncode_nonzero"
                if row.get("returncode") not in (0, None)
                else "simulation_status_not_passed"
            )
        source_artifacts = [
            _rel_to(artifact, out_dir)
            for artifact in [
                run_dir / "simulation_result.json",
                run_dir / "simulation_request.json",
                run_dir / "verdict.json",
                run_dir / "calibration_record.json",
                run_dir / "explicit_step2_handoff_source.json",
                copied_request_path,
                authoritative_request_path,
                run_dir / "pilot_stdout.log",
                run_dir / "pilot_stderr.log",
            ]
            if artifact.exists()
        ]
        source_artifacts = list(dict.fromkeys(source_artifacts))
        updates.append({
            "target": "search_policy",
            "status": status,
            "observation_role": "search_policy_feedback",
            "trusted_sample": trusted_sample,
            "candidate_refs": candidate_refs,
            "metrics": metrics,
            "observe_api": "SearchPolicy.observe(candidate_id, metrics)",
            "candidate_id_resolution": [
                "search_policy_candidate_id",
                "search_policy_parameter_hash",
                "parent_search_policy_candidate_id",
                "parent_search_policy_parameter_hash",
                "mapping_candidate_id",
                "mapping_parameter_hash",
                "candidate_id",
            ],
            "feedback_source": {
                "kind": "materialized_handoff_sweep",
                "source_run_dir": str(source_run_dir),
                "sweep_run_dir": _rel_to(run_dir, out_dir),
                "source_materialized_dir": row.get("source_materialized_dir"),
                "authoritative_request_path": str(authoritative_request_path),
                "authoritative_request_sha256": authoritative_request_hash,
                "copied_request_path": _rel_to(copied_request_path, out_dir) if copied_request_hash else None,
                "copied_request_sha256": copied_request_hash,
                "copied_request_matches_authority": (
                    copied_request_hash == authoritative_request_hash
                    if copied_request_hash
                    else None
                ),
                "sweep_row_status": row.get("status"),
                "sweep_returncode": row.get("returncode"),
                "simulation_status": row.get("simulation_status"),
            },
            "source_artifacts": source_artifacts,
        })
        for artifact in [
            run_dir / "simulation_result.json",
            run_dir / "simulation_request.json",
            run_dir / "verdict.json",
            run_dir / "calibration_record.json",
            run_dir / "explicit_step2_handoff_source.json",
            copied_request_path,
            authoritative_request_path,
            run_dir / "pilot_stdout.log",
            run_dir / "pilot_stderr.log",
        ]:
            artifact_hash = _hash_if_exists(artifact)
            if artifact_hash:
                source_artifact_hashes[_rel_to(artifact, out_dir)] = artifact_hash

    feedback_update = {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": str(source_search_checkpoint.get("campaign_id") or "campaign"),
        "workload_run_id": str(source_search_checkpoint.get("workload_run_id") or source_search_checkpoint.get("problem", {}).get("workload_run_id") or "workload_run"),
        "trial_id": str(source_search_checkpoint.get("trial_id") or source_search_checkpoint.get("search_policy_checkpoint", {}).get("trial_id") or "trial"),
        "updates": updates,
        "source_artifact_hashes": source_artifact_hashes,
    }
    return feedback_update


def _candidate_ref_aliases(payload: Mapping[str, Any]) -> List[str]:
    aliases: List[str] = []

    def append(value: Any) -> None:
        alias = str(value or "")
        if alias and alias not in aliases:
            aliases.append(alias)

    for container in _identity_containers(payload):
        for key in (
            "search_policy_candidate_id",
            "parent_search_policy_candidate_id",
            "candidate_id",
            "selected_candidate_id",
            "mapping_candidate_id",
            "materialized_architecture_candidate_id",
            "architecture_id",
            "mapping_id",
            "design_point_id",
            "source_proposal_id",
            "parameter_hash",
            "search_policy_parameter_hash",
            "parent_search_policy_parameter_hash",
            "mapping_parameter_hash",
            "architecture_parameter_hash",
            "architecture_instance_hash",
            "source_proposal_hash",
        ):
            append(container.get(key))
    return aliases


def _candidate_ref_hashes(payload: Mapping[str, Any]) -> List[str]:
    hashes: List[str] = []

    def append(value: Any) -> None:
        item = str(value or "")
        if item and item not in hashes:
            hashes.append(item)

    for container in _identity_containers(payload):
        for key in (
            "architecture_parameter_hash",
            "architecture_instance_hash",
            "source_proposal_hash",
            "parameter_hash",
            "candidate_parameter_hash",
            "selected_candidate_parameter_hash",
            "selected_parameter_hash",
            "search_iteration_parameter_hash",
            "matched_search_candidate_parameter_hash",
            "request_parameter_hash",
            "search_policy_parameter_hash",
            "request_search_policy_parameter_hash",
            "mapping_parameter_hash",
            "request_mapping_parameter_hash",
        ):
            append(container.get(key))
    return hashes


def _identity_containers(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    containers: List[Mapping[str, Any]] = [payload]
    for key in ("candidate_refs", "materialization_inputs", "parameters"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            containers.append(value)
    refs = payload.get("candidate_refs")
    if isinstance(refs, Mapping):
        for key in ("materialization_inputs", "parameters"):
            value = refs.get(key)
            if isinstance(value, Mapping):
                containers.append(value)
    return containers


def _is_materialized_architecture_identity(payload: Mapping[str, Any]) -> bool:
    for container in _identity_containers(payload):
        if (
            container.get("materialized_architecture_candidate_id")
            or container.get("architecture_parameter_hash")
            or container.get("source_proposal_hash")
            or str(container.get("candidate_type") or "") == "materialized_architecture_candidate"
        ):
            return True
    return False


def _is_template_bound_identity(payload: Mapping[str, Any]) -> bool:
    """Return true when shared mapping ids are selectors, not candidate identity."""

    for container in _identity_containers(payload):
        if str(container.get("dft_template_binding_status") or "").startswith("bound_"):
            return True
        if container.get("template_family") and (
            container.get("search_policy_candidate_id") or container.get("search_policy_parameter_hash")
        ):
            return True
        for key in ("candidate_hints", "domain_policy_hints"):
            hints = container.get(key)
            if not isinstance(hints, Mapping):
                continue
            annotations = hints.get("annotations")
            if isinstance(annotations, Mapping):
                dft = annotations.get("dft")
                if isinstance(dft, Mapping) and isinstance(dft.get("template_binding"), Mapping):
                    return True
    return False


def _candidate_identity_aliases(payload: Mapping[str, Any]) -> List[str]:
    """Return replay identity aliases, excluding shared mapping anchors when needed."""

    if _is_template_bound_identity(payload):
        aliases: List[str] = []

        def append_template(value: Any) -> None:
            alias = str(value or "")
            if alias and alias not in aliases:
                aliases.append(alias)

        for container in _identity_containers(payload):
            for key in (
                "search_policy_candidate_id",
                "materialized_architecture_candidate_id",
                "source_proposal_id",
            ):
                append_template(container.get(key))
        if not aliases:
            for container in _identity_containers(payload):
                for key in ("candidate_id", "selected_candidate_id"):
                    append_template(container.get(key))
        return aliases

    non_materialized_identity_keys = (
        "search_policy_candidate_id",
        "candidate_id",
        "selected_candidate_id",
        "mapping_candidate_id",
        "materialized_architecture_candidate_id",
        "source_proposal_id",
    )

    if not _is_materialized_architecture_identity(payload):
        aliases: List[str] = []

        def append_non_materialized(value: Any) -> None:
            alias = str(value or "")
            if alias and alias not in aliases:
                aliases.append(alias)

        for container in _identity_containers(payload):
            for key in non_materialized_identity_keys:
                append_non_materialized(container.get(key))
        return aliases

    aliases: List[str] = []

    def append(value: Any) -> None:
        alias = str(value or "")
        if alias and alias not in aliases:
            aliases.append(alias)

    def append_materialized_candidate_alias(value: Any, container: Mapping[str, Any]) -> None:
        alias = str(value or "")
        if not alias:
            return
        materialized_id = str(container.get("materialized_architecture_candidate_id") or "")
        architecture_id = str(container.get("architecture_id") or "")
        if (
            alias == materialized_id
            or alias == architecture_id
            or alias.startswith("architecture::")
            or alias.startswith("materialized-")
        ):
            append(alias)

    for container in _identity_containers(payload):
        for key in (
            "materialized_architecture_candidate_id",
            "architecture_id",
            "source_proposal_id",
            "design_point_id",
        ):
            append(container.get(key))
        for key in (
            "candidate_id",
            "selected_candidate_id",
            "search_policy_candidate_id",
        ):
            append_materialized_candidate_alias(container.get(key), container)
    return aliases


def _candidate_identity_hashes(payload: Mapping[str, Any]) -> List[str]:
    if _is_template_bound_identity(payload):
        hashes: List[str] = []

        def append_template(value: Any) -> None:
            item = str(value or "")
            if item and item not in hashes:
                hashes.append(item)

        for container in _identity_containers(payload):
            for key in (
                "search_policy_parameter_hash",
                "architecture_parameter_hash",
                "architecture_instance_hash",
                "source_proposal_hash",
            ):
                append_template(container.get(key))
        if not hashes:
            for container in _identity_containers(payload):
                append_template(container.get("parameter_hash"))
        return hashes

    if not _is_materialized_architecture_identity(payload):
        return _candidate_ref_hashes(payload)

    hashes: List[str] = []

    def append(value: Any) -> None:
        item = str(value or "")
        if item and item not in hashes:
            hashes.append(item)

    for container in _identity_containers(payload):
        for key in (
            "architecture_parameter_hash",
            "architecture_instance_hash",
            "source_proposal_hash",
            "parameter_hash",
            "search_policy_parameter_hash",
        ):
            append(container.get(key))
    return hashes


def _first_hash(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = str(payload.get(key) or "")
        if value:
            return value
    refs = payload.get("candidate_refs")
    if isinstance(refs, Mapping):
        for key in keys:
            value = str(refs.get(key) or "")
            if value:
                return value
    return ""


def _build_search_feedback_closure_audit(
    *,
    source_run_dir: Path,
    out_dir: Path,
    run_rows: Sequence[Mapping[str, Any]],
    feedback_update: Mapping[str, Any],
    search_iteration_plan: Mapping[str, Any],
    campaign_search_admission_plan: Mapping[str, Any],
) -> Dict[str, Any]:
    """Audit the explicit materialized handoff loop through next Campaign admission.

    The audit is a control-plane artifact only.  It proves that an explicit
    materialized handoff sweep produced feedback rows and that the next
    SearchPolicy/Campaign artifacts consumed those rows without turning either
    Top-K provenance or the materialization summary into Step3 authority.
    """

    search_updates = [
        update
        for update in feedback_update.get("updates", []) or []
        if isinstance(update, Mapping) and update.get("target") == "search_policy"
    ]
    feedback_by_source_dir = {
        str(_as_mapping(update.get("feedback_source")).get("source_materialized_dir") or ""): update
        for update in search_updates
    }
    feedback_by_alias: Dict[str, Mapping[str, Any]] = {}
    for update in search_updates:
        for alias in _candidate_ref_aliases(update):
            feedback_by_alias.setdefault(alias, update)

    next_candidates = [
        candidate
        for candidate in search_iteration_plan.get("next_candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    next_by_alias: Dict[str, Mapping[str, Any]] = {}
    for candidate in next_candidates:
        for alias in _candidate_ref_aliases(candidate):
            next_by_alias.setdefault(alias, candidate)

    deferred_by_alias: Dict[str, Mapping[str, Any]] = {}
    for deferred in campaign_search_admission_plan.get("deferred_candidates", []) or []:
        if not isinstance(deferred, Mapping):
            continue
        for alias in _candidate_ref_aliases(deferred):
            deferred_by_alias.setdefault(alias, deferred)
    requests_by_alias: Dict[str, Mapping[str, Any]] = {}
    for request in campaign_search_admission_plan.get("step2_iteration_requests", []) or []:
        if not isinstance(request, Mapping):
            continue
        for alias in _candidate_ref_aliases(request):
            requests_by_alias.setdefault(alias, request)

    executed_rows = [row for row in run_rows if row.get("returncode") is not None]
    lineage: List[Dict[str, Any]] = []
    blockers: List[Dict[str, str]] = []
    for row in run_rows:
        source_materialized_dir = str(row.get("source_materialized_dir") or "")
        feedback = feedback_by_source_dir.get(source_materialized_dir)
        if not feedback:
            for alias in _candidate_ref_aliases(row):
                feedback = feedback_by_alias.get(alias)
                if feedback:
                    break
        feedback_aliases = _candidate_ref_aliases(feedback or {})
        next_candidate: Mapping[str, Any] = {}
        for alias in feedback_aliases:
            next_candidate = next_by_alias.get(alias, {})
            if next_candidate:
                break
        deferred: Mapping[str, Any] = {}
        request: Mapping[str, Any] = {}
        for alias in feedback_aliases:
            deferred = deferred_by_alias.get(alias, {})
            request = requests_by_alias.get(alias, {})
            if deferred or request:
                break
        observed_metrics = _as_mapping(next_candidate.get("observed_metrics")) if next_candidate else {}
        request_inputs = _as_mapping(request.get("materialization_inputs")) if request else {}
        request_hash = _first_hash(
            request or {},
            (
                "architecture_parameter_hash",
                "mapping_parameter_hash",
                "search_policy_parameter_hash",
                "parameter_hash",
            ),
        )
        request_search_policy_hash = _first_hash(
            request or {},
            (
                "search_policy_parameter_hash",
                "parent_search_policy_parameter_hash",
                "parameter_hash",
            ),
        )
        acceptable_request_search_policy_hashes = [
            value
            for value in (
                _first_hash(request or {}, ("search_policy_parameter_hash",)),
                str(request_inputs.get("search_policy_parameter_hash") or ""),
                _first_hash(request or {}, ("parent_search_policy_parameter_hash",)),
                str(request_inputs.get("parent_search_policy_parameter_hash") or ""),
                _first_hash(request or {}, ("parameter_hash",)),
            )
            if value
        ]
        request_mapping_hash = _first_hash(
            request or {},
            (
                "mapping_parameter_hash",
                "parameter_hash",
            ),
        )
        feedback_refs = _as_mapping(feedback.get("candidate_refs")) if feedback else {}
        materialized_identity = str(
            feedback_refs.get("materialized_architecture_candidate_id")
            or request_inputs.get("materialized_architecture_candidate_id")
            or ""
        )
        architecture_parameter_hash = str(
            feedback_refs.get("architecture_parameter_hash")
            or request_inputs.get("architecture_parameter_hash")
            or ""
        )
        source_proposal_hash = str(
            feedback_refs.get("source_proposal_hash")
            or request_inputs.get("source_proposal_hash")
            or ""
        )
        lineage_selected_candidate_id = (
            materialized_identity
            or str(feedback_refs.get("candidate_id") or "")
            or str(row.get("selected_candidate_id") or "")
        )
        template_bound_identity = bool(
            _is_template_bound_identity(request or {})
            or _is_template_bound_identity(feedback_refs)
            or _is_template_bound_identity(next_candidate)
        )
        search_policy_candidate_id = str(
            feedback_refs.get("search_policy_candidate_id")
            or request.get("search_policy_candidate_id")
            or request_inputs.get("search_policy_candidate_id")
            or ""
        )
        search_policy_parameter_hash = str(
            feedback_refs.get("search_policy_parameter_hash")
            or request.get("search_policy_parameter_hash")
            or request_inputs.get("search_policy_parameter_hash")
            or ""
        )
        if template_bound_identity and search_policy_candidate_id:
            lineage_selected_candidate_id = search_policy_candidate_id
        selected_parameter_hash = _first_hash(
            feedback_refs or feedback or {},
            (
                "search_policy_parameter_hash" if template_bound_identity else "architecture_parameter_hash",
                "architecture_parameter_hash",
                "mapping_parameter_hash",
                "parameter_hash",
                "candidate_parameter_hash",
                "search_policy_parameter_hash",
            ),
        ) or request_hash
        if template_bound_identity and search_policy_parameter_hash:
            selected_parameter_hash = search_policy_parameter_hash
        search_iteration_parameter_hash = _first_hash(
            next_candidate,
            (
                "parameter_hash",
                "search_policy_parameter_hash",
                "mapping_parameter_hash",
            ),
        )
        row_blockers: List[str] = []
        if row.get("returncode") is not None and not feedback:
            row_blockers.append("missing_feedback_update_for_executed_row")
        if feedback and not observed_metrics:
            row_blockers.append("feedback_not_applied_to_next_search_candidate")
        if feedback and not deferred and not request:
            row_blockers.append("campaign_admission_did_not_classify_feedback_candidate")
        if row.get("returncode") is not None and not selected_parameter_hash:
            row_blockers.append("missing_selected_candidate_parameter_hash")
        if feedback and not search_iteration_parameter_hash:
            row_blockers.append("missing_search_iteration_candidate_parameter_hash")
        if (
            acceptable_request_search_policy_hashes
            and search_iteration_parameter_hash
            and search_iteration_parameter_hash not in acceptable_request_search_policy_hashes
        ):
            row_blockers.append("search_policy_parameter_hash_lineage_mismatch")
        if row.get("hidden_evidence_fanout_allowed") not in (None, False):
            row_blockers.append("row_hidden_evidence_fanout_allowed")
        for reason_id in row_blockers:
            blockers.append({
                "reason_id": reason_id,
                "source_materialized_dir": source_materialized_dir,
            })
        lineage.append({
            "request_id": str(row.get("request_id") or ""),
            "selected_candidate_id": lineage_selected_candidate_id,
            "executed_mapping_candidate_id": str(row.get("selected_candidate_id") or ""),
            "materialized_architecture_candidate_id": materialized_identity,
            "architecture_id": str(feedback_refs.get("architecture_id") or request_inputs.get("architecture_id") or ""),
            "architecture_parameter_hash": architecture_parameter_hash,
            "source_proposal_hash": source_proposal_hash,
            "source_proposal_id": str(feedback_refs.get("source_proposal_id") or request_inputs.get("source_proposal_id") or ""),
            "selected_candidate_parameter_hash": selected_parameter_hash,
            "mapping_parameter_hash": request_mapping_hash,
            "search_policy_parameter_hash": request_search_policy_hash,
            "source_materialized_dir": source_materialized_dir,
            "run_dir": str(row.get("run_dir") or ""),
            "returncode": row.get("returncode"),
            "sweep_row_status": str(row.get("status") or ""),
            "simulation_status": str(row.get("simulation_status") or ""),
            "feedback_update_status": str(feedback.get("status") or "missing") if feedback else "missing",
            "feedback_trusted_sample": bool(feedback.get("trusted_sample") is True) if feedback else False,
            "feedback_step4_verdict": str(_as_mapping(feedback.get("metrics")).get("step4_verdict") or "") if feedback else "",
            "search_iteration_observed": bool(observed_metrics),
            "search_iteration_candidate_id": str(next_candidate.get("candidate_id") or "") if next_candidate else "",
            "search_iteration_parameter_hash": search_iteration_parameter_hash,
            "search_iteration_rejected": bool(
                observed_metrics.get("promoted") is False
                or "feedback_rejected" in {
                    str(reason or "")
                    for reason in (next_candidate.get("blocker_reasons", []) or [])
                }
            ) if next_candidate else False,
            "campaign_deferred_status": str(deferred.get("status") or "") if deferred else "",
            "campaign_request_id": str(request.get("request_id") or "") if request else "",
            "request_parameter_hash": request_hash,
            "request_search_policy_parameter_hash": request_search_policy_hash,
            "request_mapping_parameter_hash": request_mapping_hash,
            "blockers": row_blockers,
        })

    global_checks = {
        "executed_rows_have_feedback": len(executed_rows) == len(search_updates),
        "feedback_applied_to_search_iteration": all(
            row.get("returncode") is None or item["search_iteration_observed"]
            for row, item in zip(run_rows, lineage)
        ),
        "observed_feedback_classified_by_campaign": all(
            item["feedback_update_status"] == "missing"
            or item["campaign_deferred_status"]
            or item["campaign_request_id"]
            for item in lineage
        ),
        "hidden_evidence_fanout_allowed": False,
        "search_plan_safe_to_execute_step3": False,
        "campaign_plan_safe_to_execute_step3": bool(campaign_search_admission_plan.get("execution_allowed") is True),
        "trusted_final_claim": False,
        "release_completion_eligible": False,
    }
    if global_checks["campaign_plan_safe_to_execute_step3"]:
        blockers.append({"reason_id": "campaign_plan_execution_allowed"})
    if search_iteration_plan.get("hidden_evidence_fanout_allowed") not in (None, False):
        blockers.append({"reason_id": "search_iteration_plan_hidden_evidence_fanout_allowed"})
    if campaign_search_admission_plan.get("hidden_evidence_fanout_allowed") not in (None, False):
        blockers.append({"reason_id": "campaign_plan_hidden_evidence_fanout_allowed"})
    if len(executed_rows) != len(search_updates):
        blockers.append({"reason_id": "executed_feedback_update_count_mismatch"})

    status = "closed_for_next_iteration" if not blockers and executed_rows else "partial_blocked_not_complete"
    return {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": str(feedback_update.get("campaign_id") or campaign_search_admission_plan.get("campaign_id") or "campaign"),
        "workload_run_id": str(
            feedback_update.get("workload_run_id")
            or campaign_search_admission_plan.get("workload_run_id")
            or "workload_run"
        ),
        "trial_id": str(feedback_update.get("trial_id") or campaign_search_admission_plan.get("trial_id") or "trial"),
        "status": status,
        "source_run_dir": str(source_run_dir),
        "out_dir": str(out_dir),
        "loop_artifacts": {
            "source_campaign_materialization_summary": str(source_run_dir / "campaign_materialization_summary.json"),
            "feedback_update": "feedback_update.json",
            "search_iteration_plan": "search_iteration_plan.json",
            "campaign_search_admission_plan": "campaign_search_admission_plan.json",
        },
        "planned_candidate_count": len(run_rows),
        "executed_candidate_count": len(executed_rows),
        "feedback_update_count": len(search_updates),
        "search_iteration_applied_feedback_count": int(search_iteration_plan.get("applied_feedback_count", 0) or 0),
        "campaign_step2_iteration_request_count": int(campaign_search_admission_plan.get("step2_iteration_request_count", 0) or 0),
        "campaign_deferred_candidate_count": int(campaign_search_admission_plan.get("deferred_candidate_count", 0) or 0),
        "global_checks": global_checks,
        "lineage": lineage,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Search feedback closure audits prove control-plane lineage across explicit "
            "materialized handoff sweeps only. They cannot execute Step3, claim convergence, "
            "or establish release completion."
        ),
    }


def _build_search_replay_safety_audit(
    *,
    source_run_dir: Path,
    out_dir: Path,
    feedback_update: Mapping[str, Any],
    search_iteration_plan: Mapping[str, Any],
    campaign_search_admission_plan: Mapping[str, Any],
) -> Dict[str, Any]:
    """Audit that the next Campaign step spends search budget only on safe new work."""

    search_updates = [
        update
        for update in feedback_update.get("updates", []) or []
        if isinstance(update, Mapping) and update.get("target") == "search_policy"
    ]
    observed_aliases: Dict[str, Mapping[str, Any]] = {}
    rejected_aliases: Dict[str, Mapping[str, Any]] = {}
    for update in search_updates:
        metrics = _as_mapping(update.get("metrics"))
        rejected = (
            str(update.get("status") or "").lower() in {"failed", "blocked"}
            or str(metrics.get("step4_verdict") or "").lower() in {"failed", "blocked"}
            or metrics.get("promoted") is False
        )
        for alias in _candidate_identity_aliases(update):
            observed_aliases.setdefault(alias, update)
            if rejected:
                rejected_aliases.setdefault(alias, update)

    next_candidates = [
        candidate
        for candidate in search_iteration_plan.get("next_candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    next_by_alias: Dict[str, Mapping[str, Any]] = {}
    for candidate in next_candidates:
        for alias in _candidate_identity_aliases(candidate):
            next_by_alias.setdefault(alias, candidate)

    def candidate_for(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        for alias in _candidate_identity_aliases(payload):
            candidate = next_by_alias.get(alias)
            if candidate:
                return candidate
        return {}

    deferred_aliases: Dict[str, Mapping[str, Any]] = {}
    for deferred in campaign_search_admission_plan.get("deferred_candidates", []) or []:
        if not isinstance(deferred, Mapping):
            continue
        for alias in _candidate_identity_aliases(deferred):
            deferred_aliases.setdefault(alias, deferred)

    request_rows = [
        row
        for row in campaign_search_admission_plan.get("step2_iteration_requests", []) or []
        if isinstance(row, Mapping)
    ]
    materialized_rows = [
        row
        for row in campaign_search_admission_plan.get("materialized_step3_queue_entries", []) or []
        if isinstance(row, Mapping)
    ]
    blockers: List[Dict[str, str]] = []
    request_lineage: List[Dict[str, Any]] = []

    def request_blockers(row: Mapping[str, Any], *, row_kind: str) -> List[str]:
        row_blockers: List[str] = []
        aliases = _candidate_identity_aliases(row)
        request_hashes = _candidate_identity_hashes(row)
        matched_candidate = candidate_for(row)
        matched_hashes = _candidate_identity_hashes(matched_candidate) if matched_candidate else []
        matched_observed = sorted(alias for alias in aliases if alias in observed_aliases)
        matched_rejected = sorted(alias for alias in aliases if alias in rejected_aliases)
        if matched_observed:
            row_blockers.append("observed_candidate_re_requested")
        if matched_rejected:
            row_blockers.append("rejected_candidate_re_requested")
        if not request_hashes:
            row_blockers.append("request_missing_parameter_hash")
        if matched_candidate and matched_hashes and request_hashes and not (set(request_hashes) & set(matched_hashes)):
            row_blockers.append("request_matched_candidate_parameter_hash_mismatch")
        observed_metrics = _as_mapping(matched_candidate.get("observed_metrics")) if matched_candidate else {}
        if observed_metrics:
            row_blockers.append("request_targets_observed_search_candidate")
        if row.get("execution_allowed") not in (None, False):
            row_blockers.append(f"{row_kind}_execution_allowed")
        if row.get("hidden_evidence_fanout_allowed") not in (None, False):
            row_blockers.append(f"{row_kind}_hidden_evidence_fanout_allowed")
        if row.get("trusted_final_claim") not in (None, False):
            row_blockers.append(f"{row_kind}_trusted_final_claim")
        if row.get("release_completion_eligible") not in (None, False):
            row_blockers.append(f"{row_kind}_release_completion_eligible")
        if row_kind == "step2_request":
            if row.get("not_a_step3_queue_entry") is not True:
                row_blockers.append("step2_request_not_marked_non_queue_entry")
            if str(row.get("canonical_step3_admission_authority") or "") != "step2/step3_simulation_queue.json":
                row_blockers.append("step2_request_invalid_canonical_step3_authority")
        if matched_candidate:
            for key in ("execution_allowed", "hidden_evidence_fanout_allowed", "trusted_final_claim", "release_completion_eligible"):
                if matched_candidate.get(key) not in (None, False):
                    row_blockers.append(f"matched_candidate_{key}")
            if matched_candidate.get("not_a_step3_queue_entry") is False:
                row_blockers.append("matched_candidate_claims_step3_queue_entry")
        else:
            row_blockers.append("request_missing_matching_search_candidate")
        return row_blockers

    for row_kind, rows in (("step2_request", request_rows), ("materialized_step3_entry", materialized_rows)):
        for row in rows:
            blockers_for_row = request_blockers(row, row_kind=row_kind)
            for reason_id in blockers_for_row:
                blockers.append({
                    "reason_id": reason_id,
                    "row_kind": row_kind,
                    "candidate_id": str(row.get("search_policy_candidate_id") or row.get("candidate_id") or ""),
                })
            matched_candidate = candidate_for(row)
            materialization_inputs = _as_mapping(row.get("materialization_inputs"))
            request_lineage.append({
                "row_kind": row_kind,
                "candidate_id": str(row.get("search_policy_candidate_id") or row.get("candidate_id") or ""),
                "request_parameter_hash": _first_hash(
                    row,
                    (
                        "architecture_parameter_hash",
                        "mapping_parameter_hash",
                        "search_policy_parameter_hash",
                        "parameter_hash",
                    ),
                ),
                "request_search_policy_parameter_hash": str(row.get("search_policy_parameter_hash") or ""),
                "request_mapping_parameter_hash": str(row.get("mapping_parameter_hash") or ""),
                "materialized_architecture_candidate_id": str(
                    row.get("materialized_architecture_candidate_id")
                    or materialization_inputs.get("materialized_architecture_candidate_id")
                    or ""
                ),
                "architecture_id": str(row.get("architecture_id") or materialization_inputs.get("architecture_id") or ""),
                "architecture_parameter_hash": str(
                    row.get("architecture_parameter_hash")
                    or materialization_inputs.get("architecture_parameter_hash")
                    or ""
                ),
                "source_proposal_hash": str(
                    row.get("source_proposal_hash")
                    or materialization_inputs.get("source_proposal_hash")
                    or ""
                ),
                "source_proposal_id": str(
                    row.get("source_proposal_id")
                    or materialization_inputs.get("source_proposal_id")
                    or ""
                ),
                "request_id": str(row.get("request_id") or row.get("queue_entry_id") or ""),
                "matched_search_candidate_id": str(matched_candidate.get("candidate_id") or "") if matched_candidate else "",
                "matched_search_candidate_parameter_hash": _first_hash(
                    matched_candidate,
                    (
                        "architecture_parameter_hash",
                        "parameter_hash",
                        "search_policy_parameter_hash",
                        "mapping_parameter_hash",
                    ),
                ) if matched_candidate else "",
                "matched_search_candidate_observed": bool(_as_mapping(matched_candidate.get("observed_metrics"))) if matched_candidate else False,
                "blockers": blockers_for_row,
            })

    requested_aliases = {
        alias
        for row in [*request_rows, *materialized_rows]
        for alias in _candidate_identity_aliases(row)
    }
    observed_classification: List[Dict[str, Any]] = []
    seen_update_keys: set[tuple[str, str, str]] = set()
    for update in search_updates:
        candidate_refs = _as_mapping(update.get("candidate_refs"))
        aliases = _candidate_identity_aliases(update)
        update_key = (
            str(candidate_refs.get("search_policy_candidate_id") or ""),
            str(candidate_refs.get("candidate_id") or ""),
            str(candidate_refs.get("mapping_candidate_id") or ""),
        )
        if update_key in seen_update_keys:
            continue
        seen_update_keys.add(update_key)
        deferred_alias = next((alias for alias in aliases if alias in deferred_aliases), "")
        deferred = deferred_aliases.get(deferred_alias, {})
        requested = any(alias in requested_aliases for alias in aliases)
        rejected = any(alias in rejected_aliases for alias in aliases)
        observed_blockers: List[str] = []
        if requested:
            observed_blockers.append("observed_feedback_alias_re_requested")
        if rejected and not deferred:
            observed_blockers.append("rejected_feedback_alias_not_deferred")
        for reason_id in observed_blockers:
            blockers.append({
                "reason_id": reason_id,
                "alias": aliases[0] if aliases else "",
                "candidate_id": str(candidate_refs.get("candidate_id") or ""),
            })
        observed_classification.append({
            "alias": aliases[0] if aliases else "",
            "aliases": aliases,
            "parameter_hashes": _candidate_identity_hashes(update),
            "search_policy_parameter_hash": str(candidate_refs.get("search_policy_parameter_hash") or ""),
            "mapping_parameter_hash": str(candidate_refs.get("mapping_parameter_hash") or ""),
            "materialized_architecture_candidate_id": str(
                candidate_refs.get("materialized_architecture_candidate_id") or ""
            ),
            "architecture_id": str(candidate_refs.get("architecture_id") or ""),
            "architecture_parameter_hash": str(candidate_refs.get("architecture_parameter_hash") or ""),
            "source_proposal_hash": str(candidate_refs.get("source_proposal_hash") or ""),
            "feedback_status": str(update.get("status") or ""),
            "rejected_feedback": rejected,
            "campaign_deferred_status": str(deferred.get("status") or "") if deferred else "",
            "re_requested_by_campaign": requested,
            "blockers": observed_blockers,
        })

    source_plan_safety = _as_mapping(campaign_search_admission_plan.get("source_search_iteration_plan_safety"))
    if source_plan_safety and source_plan_safety.get("status") not in (None, "safe"):
        blockers.append({"reason_id": "campaign_source_search_iteration_plan_not_safe"})
    if campaign_search_admission_plan.get("hidden_evidence_fanout_allowed") not in (None, False):
        blockers.append({"reason_id": "campaign_plan_hidden_evidence_fanout_allowed"})
    if campaign_search_admission_plan.get("execution_allowed") not in (None, False):
        blockers.append({"reason_id": "campaign_plan_execution_allowed"})

    global_checks = {
        "observed_feedback_not_re_requested": not any(row["re_requested_by_campaign"] for row in observed_classification),
        "rejected_feedback_not_re_requested": not any(
            row["rejected_feedback"] and row["re_requested_by_campaign"]
            for row in observed_classification
        ),
        "rejected_feedback_deferred": all(
            (not row["rejected_feedback"]) or bool(row["campaign_deferred_status"])
            for row in observed_classification
        ),
        "all_campaign_requests_target_unobserved_candidates": all(
            not row["matched_search_candidate_observed"] for row in request_lineage
        ),
        "all_campaign_requests_safe": all(not row["blockers"] for row in request_lineage),
        "campaign_source_search_iteration_plan_safe": source_plan_safety.get("status", "safe") == "safe",
        "hidden_evidence_fanout_allowed": False,
        "execution_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
    }
    status = "closed_for_next_iteration" if not blockers and search_updates else "partial_blocked_not_complete"
    return {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": str(feedback_update.get("campaign_id") or campaign_search_admission_plan.get("campaign_id") or "campaign"),
        "workload_run_id": str(
            feedback_update.get("workload_run_id")
            or campaign_search_admission_plan.get("workload_run_id")
            or "workload_run"
        ),
        "trial_id": str(feedback_update.get("trial_id") or campaign_search_admission_plan.get("trial_id") or "trial"),
        "status": status,
        "source_run_dir": str(source_run_dir),
        "out_dir": str(out_dir),
        "loop_artifacts": {
            "feedback_update": "feedback_update.json",
            "search_iteration_plan": "search_iteration_plan.json",
            "campaign_search_admission_plan": "campaign_search_admission_plan.json",
        },
        "observed_feedback_alias_count": len(observed_aliases),
        "rejected_feedback_alias_count": len(rejected_aliases),
        "campaign_step2_iteration_request_count": len(request_rows),
        "campaign_materialized_step3_entry_count": len(materialized_rows),
        "observed_feedback_classification": observed_classification,
        "campaign_request_lineage": request_lineage,
        "source_search_iteration_plan_safety": source_plan_safety,
        "global_checks": global_checks,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "Search replay safety audits prove next-round scheduling discipline only: "
            "observed or rejected feedback candidates are not re-requested, and "
            "Campaign requests target safe unobserved candidates. They cannot execute "
            "Step3, claim convergence, or establish final ranking."
        ),
    }


def run_sweep(args: argparse.Namespace) -> Dict[str, Any]:
    source_run_dir = args.source_run_dir.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = source_run_dir / "campaign_materialization_summary.json"
    rows = _materialization_rows(source_run_dir, limit=args.limit)
    base_command = _pilot_base_args(args, source_run_dir)
    run_rows: List[Dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        materialization = row["source_materialization"]
        selected_candidate_id = str(materialization.get("selected_candidate_id") or materialization.get("request_id") or f"candidate-{index}")
        run_dir = out_dir / f"candidate_{index:03d}_{_safe_path_segment(selected_candidate_id)}"
        authoritative_request_path = (
            Path(row["handoff_dir"]).resolve() / MATERIALIZATION_REQUEST_FILENAME
        ).resolve()
        authoritative_request_hash = _hash_if_exists(authoritative_request_path)
        command = [
            *base_command,
            "--out",
            str(run_dir),
            "--step2-handoff-dir",
            str(row["handoff_dir"]),
        ]
        row_payload: Dict[str, Any] = {
            "sequence_index": index,
            "request_id": materialization.get("request_id"),
            "selected_candidate_id": selected_candidate_id,
            "source_materialized_dir": row["source_materialized_dir"],
            "handoff_dir": str(row["handoff_dir"]),
            "run_dir": str(run_dir),
            "authoritative_request_path": str(authoritative_request_path),
            "authoritative_request_sha256": authoritative_request_hash,
            "command": command,
            "explicit_execution_allowed": True,
            "hidden_evidence_fanout_allowed": False,
            "canonical_step3_admission_authority": "step2/step3_simulation_queue.json",
            "trusted_final_claim": False,
            "release_completion_eligible": False,
        }
        if args.plan_only:
            row_payload["status"] = "planned_not_executed"
            row_payload["returncode"] = None
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=args.subprocess_timeout,
            )
            (run_dir / "pilot_stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / "pilot_stderr.log").write_text(completed.stderr, encoding="utf-8")
            row_payload["returncode"] = completed.returncode
            row_payload["status"] = "completed" if completed.returncode == 0 else "failed"
            row_payload.update(_row_metrics(run_dir))
        run_rows.append(row_payload)

    executed_rows = [row for row in run_rows if row.get("returncode") is not None]
    passed_rows = [row for row in executed_rows if row.get("returncode") == 0 and row.get("simulation_status") == "passed"]
    failed_rows = [row for row in executed_rows if row not in passed_rows]

    feedback_update_written = False
    search_iteration_plan_written = False
    closure_audit_written = False
    feedback_update: Dict[str, Any] = {}
    search_iteration_plan: Dict[str, Any] = {}
    dft_template_binding_report: Dict[str, Any] = {}
    dft_template_binding_report_written = False
    campaign_search_admission_plan: Dict[str, Any] = {}
    replay_safety_audit_written = False
    search_loop_audit_summary_written = False
    search_effectiveness_audit_written = False
    search_checkpoint_after_feedback_written = False
    search_loop_audit_run_dirs: List[Path] = []
    next_materialization_summary: Dict[str, Any] = {
        "written": False,
        "summary_ref": None,
        "search_checkpoint_ref": None,
        "request_count": 0,
        "materialized_count": 0,
        "blocked_count": 0,
        "artifact_paths": [],
    }
    if executed_rows:
        feedback_update = _materialized_handoff_feedback_update(
            source_run_dir=source_run_dir,
            out_dir=out_dir,
            run_rows=executed_rows,
        )
        feedback_update_path = out_dir / "feedback_update.json"
        _write_json(feedback_update_path, feedback_update)
        feedback_update_written = True

        source_search_checkpoint_path = source_run_dir / "step2" / "search_checkpoint.json"
        source_calibration_record_path = source_run_dir / "calibration_record.json"
        refs = {
            "search_checkpoint": str(source_search_checkpoint_path),
            "feedback_update": "feedback_update.json",
            "calibration_record": str(source_calibration_record_path),
        }
        search_iteration_plan = build_search_iteration_plan(
            search_checkpoint=_load_json(source_search_checkpoint_path),
            feedback_update=feedback_update,
            calibration_record=_load_json(source_calibration_record_path),
            refs=refs,
        )
        search_iteration_plan = _maybe_bind_dft_template_search_iteration_plan(
            search_iteration_plan,
            step2_dir=source_run_dir / "step2",
        )
        dft_template_binding_report = _as_mapping(search_iteration_plan.get("dft_template_binding_report"))
        if dft_template_binding_report:
            _write_json(out_dir / "dft_template_binding_report.json", dft_template_binding_report)
            dft_template_binding_report_written = True
        _validate_registered_schema(search_iteration_plan, "dse.contract.search_iteration_plan.v1")
        search_iteration_plan_path = out_dir / "search_iteration_plan.json"
        _write_json(search_iteration_plan_path, search_iteration_plan)
        search_iteration_plan_written = True
        search_checkpoint_after_feedback = search_checkpoint_from_iteration_plan(
            search_iteration_plan,
            campaign_id=str(search_iteration_plan.get("campaign_id") or ""),
            workload_run_id=str(search_iteration_plan.get("workload_run_id") or ""),
            trial_id=str(search_iteration_plan.get("trial_id") or ""),
            refs={
                "source_search_checkpoint": str(source_search_checkpoint_path),
                "search_iteration_plan": "search_iteration_plan.json",
                "feedback_update": "feedback_update.json",
                "calibration_record": str(source_calibration_record_path),
            },
        )
        _write_json(out_dir / "search_checkpoint_after_feedback.json", search_checkpoint_after_feedback)
        search_checkpoint_after_feedback_written = True

        source_campaign_evaluation_plan = _load_json(source_run_dir / "campaign_evaluation_plan.json")
        source_step3_simulation_queue = _load_json(source_run_dir / "step2" / "step3_simulation_queue.json")
        campaign_search_admission_plan = build_campaign_search_admission_plan(
            search_iteration_plan=search_iteration_plan,
            campaign_evaluation_plan=source_campaign_evaluation_plan,
            step3_simulation_queue=source_step3_simulation_queue,
            refs={
                "campaign_evaluation_plan": str(source_run_dir / "campaign_evaluation_plan.json"),
                "search_iteration_plan": "search_iteration_plan.json",
                "step3_simulation_queue": str(source_run_dir / "step2" / "step3_simulation_queue.json"),
            },
        )
        _write_json(out_dir / "campaign_search_admission_plan.json", campaign_search_admission_plan)
        closure_audit = _build_search_feedback_closure_audit(
            source_run_dir=source_run_dir,
            out_dir=out_dir,
            run_rows=run_rows,
            feedback_update=feedback_update,
            search_iteration_plan=search_iteration_plan,
            campaign_search_admission_plan=campaign_search_admission_plan,
        )
        _write_json(out_dir / "search_feedback_closure_audit.json", closure_audit)
        closure_audit_written = True
        replay_safety_audit = _build_search_replay_safety_audit(
            source_run_dir=source_run_dir,
            out_dir=out_dir,
            feedback_update=feedback_update,
            search_iteration_plan=search_iteration_plan,
            campaign_search_admission_plan=campaign_search_admission_plan,
        )
        _validate_registered_schema(replay_safety_audit, "dse.contract.search_replay_safety_audit.v1")
        _write_json(out_dir / "search_replay_safety_audit.json", replay_safety_audit)
        replay_safety_audit_written = True
        search_loop_audit_run_dirs = _search_loop_audit_run_dirs(source_run_dir=source_run_dir, out_dir=out_dir)
        search_loop_audit_summary = build_search_loop_audit_summary(search_loop_audit_run_dirs)
        _validate_registered_schema(search_loop_audit_summary, "dse.contract.search_loop_audit_summary.v1")
        _write_json(out_dir / "search_loop_audit_summary.json", search_loop_audit_summary)
        search_loop_audit_summary_written = True
        if args.materialize_next_requests:
            next_materialization_summary = _materialize_next_campaign_requests(
                source_run_dir=source_run_dir,
                out_dir=out_dir,
                campaign_search_admission_plan=campaign_search_admission_plan,
                backend=str(args.backend or _source_defaults(source_run_dir)["backend"]),
                evidence_mode=str(args.evidence_mode or _source_defaults(source_run_dir)["evidence_mode"]),
            )
        search_effectiveness_audit = build_search_effectiveness_audit(
            out_dir,
            search_loop_summary=search_loop_audit_summary,
        )
        _validate_registered_schema(search_effectiveness_audit, "dse.contract.search_effectiveness_audit.v1")
        _write_json(out_dir / "search_effectiveness_audit.json", search_effectiveness_audit)
        search_effectiveness_audit_written = True

    summary = {
        "schema_version": "dse.materialized_handoff_sweep.v1",
        "source_run_dir": str(source_run_dir),
        "source_materialization_summary": {
            "path": str(summary_path),
            "sha256": _file_sha256(summary_path) if summary_path.exists() else None,
        },
        "out_dir": str(out_dir),
        "plan_only": bool(args.plan_only),
        "planned_count": len(run_rows),
        "executed_count": len(executed_rows),
        "passed_count": len(passed_rows),
        "failed_count": len(failed_rows),
        "explicit_execution_requested": not bool(args.plan_only),
        "evidence_fanout_policy": "explicit_materialized_step2_handoff_sweep_only",
        "hidden_evidence_fanout_allowed": False,
        "broad_evidence_run": len(executed_rows) > 1,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "feedback_update_written": feedback_update_written,
        "search_iteration_plan_written": search_iteration_plan_written,
        "feedback_update_ref": "feedback_update.json" if feedback_update_written else None,
        "search_iteration_plan_ref": "search_iteration_plan.json" if search_iteration_plan_written else None,
        "dft_template_binding_report_written": dft_template_binding_report_written,
        "dft_template_binding_report_ref": (
            "dft_template_binding_report.json" if dft_template_binding_report_written else None
        ),
        "dft_template_binding_status": (
            dft_template_binding_report.get("status") if dft_template_binding_report_written else None
        ),
        "dft_template_bound_candidate_count": int(
            dft_template_binding_report.get("bound_candidate_count", 0) or 0
        ),
        "dft_template_blocked_candidate_count": int(
            dft_template_binding_report.get("blocked_candidate_count", 0) or 0
        ),
        "campaign_search_admission_plan_ref": "campaign_search_admission_plan.json" if search_iteration_plan_written else None,
        "search_feedback_closure_audit_written": closure_audit_written,
        "search_feedback_closure_audit_ref": "search_feedback_closure_audit.json" if closure_audit_written else None,
        "search_replay_safety_audit_written": replay_safety_audit_written,
        "search_replay_safety_audit_ref": "search_replay_safety_audit.json" if replay_safety_audit_written else None,
        "search_loop_audit_summary_written": search_loop_audit_summary_written,
        "search_loop_audit_summary_ref": "search_loop_audit_summary.json" if search_loop_audit_summary_written else None,
        "search_loop_audit_run_dirs": [str(run_dir) for run_dir in search_loop_audit_run_dirs],
        "search_loop_audit_run_count": len(search_loop_audit_run_dirs),
        "search_effectiveness_audit_written": search_effectiveness_audit_written,
        "search_effectiveness_audit_ref": "search_effectiveness_audit.json" if search_effectiveness_audit_written else None,
        "search_checkpoint_after_feedback_written": search_checkpoint_after_feedback_written,
        "search_checkpoint_after_feedback_ref": "search_checkpoint_after_feedback.json" if search_checkpoint_after_feedback_written else None,
        "next_campaign_materialization_summary_written": bool(next_materialization_summary.get("written")),
        "next_campaign_materialization_summary_ref": next_materialization_summary.get("summary_ref"),
        "next_campaign_materialization_request_count": int(next_materialization_summary.get("request_count", 0) or 0),
        "next_campaign_materialized_count": int(next_materialization_summary.get("materialized_count", 0) or 0),
        "next_campaign_materialization_blocked_count": int(next_materialization_summary.get("blocked_count", 0) or 0),
        "next_campaign_materialization_coverage_closed": bool(next_materialization_summary.get("coverage_closed", False)),
        "next_campaign_authorized_step3_queue_entry_count": int(
            next_materialization_summary.get("authorized_step3_queue_entry_count", 0) or 0
        ),
        "next_campaign_materialization_coverage_blocker_count": int(
            next_materialization_summary.get("coverage_blocker_count", 0) or 0
        ),
        "next_search_checkpoint_ref": next_materialization_summary.get("search_checkpoint_ref"),
        "candidate_runs": run_rows,
        "claim_boundary": (
            "This sweep executes only materialized Step2 handoffs selected by an explicit CLI request. "
            "It provides comparative Step3/Step4 feedback rows and replayable search feedback artifacts, not a release-complete DSE claim."
        ),
        "resume_next_actions": [
            "feed feedback_update.json back into the SearchPolicy checkpoint before declaring convergence",
            "keep Top-K and materialization summaries separate from Step3 admission authority",
            "require Step4 claim validation per candidate before trusted final ranking claims",
        ],
    }
    _write_json(out_dir / "materialized_handoff_sweep_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = run_sweep(args)
    except Exception as exc:
        print(f"ERROR: materialized handoff sweep failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "out_dir": summary["out_dir"],
        "summary": str(Path(summary["out_dir"]) / "materialized_handoff_sweep_summary.json"),
        "planned_count": summary["planned_count"],
        "executed_count": summary["executed_count"],
        "passed_count": summary["passed_count"],
        "failed_count": summary["failed_count"],
    }, indent=2, sort_keys=True))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
