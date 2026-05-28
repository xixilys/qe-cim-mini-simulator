#!/usr/bin/env python3
"""Run a bounded end-to-end DSE search-effectiveness loop pilot.

This orchestrates the real control-plane path rather than treating a single
Step3/Step4 evidence sample as search completion:

1. run_full_flow_pilot.py builds the initial Step1/Step2/Step3/Step4 artifacts
   with explicit Top-K widening enabled, producing Campaign Step2
   materialization requests and a campaign_materialization_summary.json;
2. run_materialized_handoff_sweep.py executes those materialized Step2 handoffs
   as explicit child full-flow runs, feeds Step4 observations back into
   SearchPolicy, audits replay safety, and optionally materializes the next
   Campaign requests;
3. this script records a compact loop summary with the latest
   search_effectiveness_audit.json status.

The output is a control-plane/search-effectiveness pilot only.  It does not
claim convergence, a final winner, release completion, or broad DFT/EDA closure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_PILOT = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_full_flow_pilot.py"
DEFAULT_SWEEP = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_materialized_handoff_sweep.py"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_command(command: Sequence[str], *, cwd: Path, timeout: int, log_dir: Path, label: str) -> Dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    (log_dir / f"{label}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (log_dir / f"{label}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    return {
        "label": label,
        "command": list(command),
        "returncode": completed.returncode,
        "stdout_log": str(log_dir / f"{label}.stdout.log"),
        "stderr_log": str(log_dir / f"{label}.stderr.log"),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Loop pilot output directory")
    parser.add_argument("--source-run-dir", type=Path, default=None, help="Reuse an existing initial full-flow run instead of creating one")
    parser.add_argument("--rounds", type=int, default=1, help="Number of materialized handoff sweep rounds to execute")
    parser.add_argument("--limit", type=int, default=1, help="Maximum materialized handoffs executed per sweep round")
    parser.add_argument("--top-k-admission-budget", type=int, default=None, help="Initial extra Search candidates materialized by the source pilot")
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--sweep", type=Path, default=DEFAULT_SWEEP)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--subprocess-timeout", type=int, default=120)
    parser.add_argument("--workload", default=None)
    parser.add_argument("--profile", default="ml_tensor")
    parser.add_argument("--importer", default="generic_json")
    parser.add_argument("--source-kind", default="generated")
    parser.add_argument(
        "--generator",
        default="tensor_chain",
        choices=["tensor_chain", "sparse_spmv", "stencil_streaming", "graph_analytics", "vector_search", "dynamic_custom", "qe_scf_reference"],
    )
    parser.add_argument("--backend", default="systemc", choices=["systemc", "gem5_systemc"])
    parser.add_argument("--evidence-mode", default="debug", choices=["summary", "debug", "forensic"])
    parser.add_argument("--npw", type=int, default=128)
    parser.add_argument("--nkb", type=int, default=16)
    parser.add_argument("--m", type=int, default=8)
    parser.add_argument("--nfft", type=int, default=1024)
    parser.add_argument("--simulator", type=Path, default=None)
    parser.add_argument(
        "--dft-template-search",
        action="store_true",
        help=(
            "After the source Step2 context exists, replace the initial widening "
            "queue with a DFT hierarchical-template SearchPolicy checkpoint, bind "
            "template rows to real generic Step2 selectors, and materialize only "
            "those bound requests before entering the sweep loop."
        ),
    )
    parser.add_argument(
        "--dft-template-budget",
        type=int,
        default=36,
        help=(
            "DFT hierarchical-template candidate budget used with --dft-template-search; "
            "default covers the current strict 36-candidate release-admission universe"
        ),
    )
    parser.add_argument(
        "--dft-template-proposal-budget",
        type=int,
        default=None,
        help="DFT template proposal budget; defaults to the explicit admission budget/limit",
    )
    return parser.parse_args(list(argv))


def _initial_pilot_command(args: argparse.Namespace, source_run_dir: Path) -> List[str]:
    budget = int(args.top_k_admission_budget if args.top_k_admission_budget is not None else max(1, args.limit))
    command: List[str] = [
        str(args.python),
        str(args.pilot),
        "--backend",
        str(args.backend),
        "--evidence-mode",
        str(args.evidence_mode),
        "--out",
        str(source_run_dir),
        "--npw",
        str(args.npw),
        "--nkb",
        str(args.nkb),
        "--m",
        str(args.m),
        "--nfft",
        str(args.nfft),
        "--top-k-widening-allowed",
        "--top-k-admission-budget",
        str(budget),
    ]
    if args.workload:
        command.extend(["--workload", str(args.workload)])
    else:
        command.extend([
            "--profile",
            str(args.profile),
            "--importer",
            str(args.importer),
            "--source-kind",
            str(args.source_kind),
            "--generator",
            str(args.generator),
        ])
    if args.simulator is not None:
        command.extend(["--simulator", str(args.simulator)])
    return command


def _sweep_command(args: argparse.Namespace, *, source_run_dir: Path, sweep_dir: Path) -> List[str]:
    command: List[str] = [
        str(args.python),
        str(args.sweep),
        "--source-run-dir",
        str(source_run_dir),
        "--out",
        str(sweep_dir),
        "--limit",
        str(max(0, int(args.limit))),
        "--backend",
        str(args.backend),
        "--evidence-mode",
        str(args.evidence_mode),
        "--npw",
        str(args.npw),
        "--nkb",
        str(args.nkb),
        "--m",
        str(args.m),
        "--nfft",
        str(args.nfft),
        "--subprocess-timeout",
        str(args.subprocess_timeout),
        "--materialize-next-requests",
    ]
    if args.workload:
        command.extend(["--workload", str(args.workload)])
    elif args.profile or args.importer or args.source_kind or args.generator:
        command.extend([
            "--profile",
            str(args.profile),
            "--importer",
            str(args.importer),
            "--source-kind",
            str(args.source_kind),
            "--generator",
            str(args.generator),
        ])
    if args.simulator is not None:
        command.extend(["--simulator", str(args.simulator)])
    return command


def _bootstrap_dft_template_source_materialization(
    *,
    source_run_dir: Path,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Seed the source run with a DFT template SearchPolicy handoff.

    Normal ``run_full_flow_pilot.py`` output uses the generic mapping search
    checkpoint.  For the DFT full-SCF hardware-search lane we also need to prove
    that profile/template candidates cannot reach Campaign until a DFT adapter
    binds them to persisted generic Step2 selectors.  This opt-in bootstrap
    keeps that bridge outside generic Campaign code, writes the binding report,
    and materializes the bound requests without launching Step3 evidence.
    """

    from dse_v2.architecture.catalog import seed_generic_dse_architecture_catalog
    from dse_v2.contracts import SCHEMA_REGISTRY, validate_instance
    from dse_v2.dse.campaign_manager import build_campaign_search_admission_plan
    from dse_v2.evidence.full_flow import _write_campaign_materialization_summary
    from dse_v2.mapping.search_policy import build_search_iteration_plan
    from dse_v2.reference_workloads.dft_step2_policy import (
        bind_dft_template_search_iteration_plan_to_step2_selectors,
        build_dft_hierarchical_funnel_search_report,
    )

    source_dir = source_run_dir.resolve()
    step2_dir = source_dir / "step2"
    if not step2_dir.exists():
        raise FileNotFoundError(f"missing source Step2 directory for DFT template bootstrap: {step2_dir}")

    generic_checkpoint_path = step2_dir / "search_checkpoint.json"
    generic_checkpoint_backup = step2_dir / "generic_search_checkpoint_before_dft_template.json"
    if generic_checkpoint_path.exists() and not generic_checkpoint_backup.exists():
        generic_checkpoint_backup.write_text(generic_checkpoint_path.read_text(encoding="utf-8"), encoding="utf-8")

    campaign_evaluation_plan = _load_json(source_dir / "campaign_evaluation_plan.json")
    campaign_id = str(campaign_evaluation_plan.get("campaign_id") or "campaign::dft-template-search-loop")
    workload_run_id = str(campaign_evaluation_plan.get("workload_run_id") or "dft_scf_six_class_suite_v1")
    trial_id = str(campaign_evaluation_plan.get("trial_id") or "trial::dft-template-search-loop")
    proposal_budget = int(
        args.dft_template_proposal_budget
        if args.dft_template_proposal_budget is not None
        else args.top_k_admission_budget
        if args.top_k_admission_budget is not None
        else max(1, int(args.limit))
    )
    proposal_budget = max(1, proposal_budget)

    dft_search_report = build_dft_hierarchical_funnel_search_report(
        workload_suite_id=workload_run_id,
        budget=max(1, int(args.dft_template_budget)),
    )
    dft_search_report.update({
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "source_generic_step2_search_checkpoint_ref": (
            "step2/generic_search_checkpoint_before_dft_template.json"
            if generic_checkpoint_backup.exists()
            else None
        ),
    })
    dft_report_ref = "step2/hierarchical_funnel_search_report.json"
    _write_json(source_dir / dft_report_ref, dft_search_report)
    # Make this the replay checkpoint for the following sweep round.  Persisted
    # generic mapping artifacts remain in step2/ and are the only binding source.
    _write_json(generic_checkpoint_path, dft_search_report)

    initial_feedback_update = {
        "schema_version": "dse.contract.feedback_update.v1",
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "updates": [],
        "source_artifact_hashes": {},
        "claim_boundary": (
            "Initial DFT template bootstrap feedback contains no Step3 observations; "
            "it only asks SearchPolicy to emit replayable template candidates."
        ),
    }
    _write_json(source_dir / "dft_template_initial_feedback_update.json", initial_feedback_update)

    iteration_plan = build_search_iteration_plan(
        search_checkpoint=dft_search_report,
        feedback_update=initial_feedback_update,
        proposal_budget=proposal_budget,
        refs={
            "search_checkpoint": dft_report_ref,
            "feedback_update": "dft_template_initial_feedback_update.json",
        },
    )
    bound_plan = bind_dft_template_search_iteration_plan_to_step2_selectors(
        iteration_plan,
        step2_dir=step2_dir,
        catalog=seed_generic_dse_architecture_catalog(),
    )
    if isinstance(bound_plan.get("dft_template_binding_report"), Mapping):
        bound_plan["dft_template_binding_report_ref"] = "dft_template_binding_report.json"
        _write_json(source_dir / "dft_template_binding_report.json", bound_plan["dft_template_binding_report"])
    validate_instance(bound_plan, SCHEMA_REGISTRY["dse.contract.search_iteration_plan.v1"])
    _write_json(source_dir / "search_iteration_plan.json", bound_plan)

    campaign_plan = build_campaign_search_admission_plan(
        search_iteration_plan=bound_plan,
        campaign_evaluation_plan=campaign_evaluation_plan,
        step3_simulation_queue=_load_json(step2_dir / "step3_simulation_queue.json"),
        budget_policy={
            "top_k_widening_allowed": True,
            "top_k_admission_budget": proposal_budget,
        },
        refs={
            "campaign_evaluation_plan": "campaign_evaluation_plan.json",
            "search_iteration_plan": "search_iteration_plan.json",
            "step3_simulation_queue": "step2/step3_simulation_queue.json",
        },
    )
    validate_instance(campaign_plan, SCHEMA_REGISTRY["dse.contract.campaign_search_admission_plan.v1"])
    _write_json(source_dir / "campaign_search_admission_plan.json", campaign_plan)

    materialization_written, artifact_paths = _write_campaign_materialization_summary(
        run_dir=source_dir,
        campaign_search_admission_plan=campaign_plan,
        backend=str(args.backend),
        evidence_mode=str(args.evidence_mode),
    )
    binding_report = _load_json(source_dir / "dft_template_binding_report.json")
    materialization_summary = _load_json(source_dir / "campaign_materialization_summary.json")
    return {
        "schema_version": "dse.dft.search_effectiveness_loop_source_bootstrap.v1",
        "status": (
            "materialized_bound_dft_template_requests"
            if materialization_written and int(materialization_summary.get("materialized_count", 0) or 0) > 0
            else "blocked_no_dft_template_materialization"
        ),
        "source_run_dir": str(source_dir),
        "dft_search_report_ref": dft_report_ref,
        "generic_checkpoint_backup_ref": (
            "step2/generic_search_checkpoint_before_dft_template.json"
            if generic_checkpoint_backup.exists()
            else None
        ),
        "dft_template_binding_report_ref": "dft_template_binding_report.json" if binding_report else None,
        "dft_template_binding_status": binding_report.get("status") if binding_report else None,
        "dft_template_bound_candidate_count": int(binding_report.get("bound_candidate_count", 0) or 0),
        "dft_template_blocked_candidate_count": int(binding_report.get("blocked_candidate_count", 0) or 0),
        "campaign_search_admission_plan_ref": "campaign_search_admission_plan.json",
        "step2_iteration_request_count": int(campaign_plan.get("step2_iteration_request_count", 0) or 0),
        "campaign_materialization_summary_written": materialization_written,
        "campaign_materialization_summary_ref": (
            "campaign_materialization_summary.json" if materialization_written else None
        ),
        "campaign_materialized_count": int(materialization_summary.get("materialized_count", 0) or 0),
        "campaign_materialization_coverage_closed": bool(materialization_summary.get("coverage_closed", False)),
        "artifact_paths": list(dict.fromkeys(artifact_paths)),
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "This source bootstrap binds DFT template SearchPolicy rows to persisted generic "
            "Step2 selectors and materializes Step2 handoffs only. It does not execute "
            "Step3 evidence or claim hardware/search completion."
        ),
    }


def run_loop(args: argparse.Namespace) -> Dict[str, Any]:
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    command_results: List[Dict[str, Any]] = []
    round_summaries: List[Dict[str, Any]] = []

    if args.source_run_dir is None:
        source_run_dir = out_dir / "source"
        source_command = _initial_pilot_command(args, source_run_dir)
        source_result = _run_command(
            source_command,
            cwd=REPO_ROOT,
            timeout=args.subprocess_timeout,
            log_dir=out_dir / "logs",
            label="source_pilot",
        )
        command_results.append(source_result)
        if source_result["returncode"] != 0:
            raise SystemExit(json.dumps(source_result, indent=2))
    else:
        source_run_dir = args.source_run_dir.resolve()

    dft_template_source_bootstrap: Dict[str, Any] = {}
    if args.dft_template_search:
        dft_template_source_bootstrap = _bootstrap_dft_template_source_materialization(
            source_run_dir=source_run_dir,
            args=args,
        )
        _write_json(out_dir / "dft_template_source_bootstrap.json", dft_template_source_bootstrap)

    if not (source_run_dir / "campaign_materialization_summary.json").exists():
        raise SystemExit(
            f"source run lacks campaign_materialization_summary.json: {source_run_dir}. "
            "Run with --top-k-widening-allowed/--top-k-admission-budget or pass a materialized source run."
        )

    current_source_dir = source_run_dir
    latest_effectiveness: Dict[str, Any] = {}
    latest_sweep_summary: Dict[str, Any] = {}
    for round_index in range(1, max(0, int(args.rounds)) + 1):
        sweep_dir = out_dir / f"sweep_round_{round_index:02d}"
        sweep_command = _sweep_command(args, source_run_dir=current_source_dir, sweep_dir=sweep_dir)
        sweep_result = _run_command(
            sweep_command,
            cwd=REPO_ROOT,
            timeout=max(args.subprocess_timeout, args.subprocess_timeout * max(1, int(args.limit)) + 30),
            log_dir=out_dir / "logs",
            label=f"sweep_round_{round_index:02d}",
        )
        command_results.append(sweep_result)
        if sweep_result["returncode"] != 0:
            raise SystemExit(json.dumps(sweep_result, indent=2))
        latest_sweep_summary = _load_json(sweep_dir / "materialized_handoff_sweep_summary.json")
        latest_effectiveness = _load_json(sweep_dir / "search_effectiveness_audit.json")
        dft_binding_status = latest_sweep_summary.get("dft_template_binding_status")
        dft_binding_report_written = bool(latest_sweep_summary.get("dft_template_binding_report_written", False))
        dft_binding_blocked_count = int(latest_sweep_summary.get("dft_template_blocked_candidate_count", 0) or 0)
        round_summaries.append({
            "round_index": round_index,
            "source_run_dir": str(current_source_dir),
            "sweep_dir": str(sweep_dir),
            "executed_count": int(latest_sweep_summary.get("executed_count", 0) or 0),
            "passed_count": int(latest_sweep_summary.get("passed_count", 0) or 0),
            "failed_count": int(latest_sweep_summary.get("failed_count", 0) or 0),
            "search_loop_audit_summary_written": bool(latest_sweep_summary.get("search_loop_audit_summary_written", False)),
            "search_effectiveness_audit_written": bool(latest_sweep_summary.get("search_effectiveness_audit_written", False)),
            "next_campaign_materialization_summary_written": bool(latest_sweep_summary.get("next_campaign_materialization_summary_written", False)),
            "dft_template_binding_report_written": dft_binding_report_written,
            "dft_template_binding_report_ref": (
                str(sweep_dir / str(latest_sweep_summary.get("dft_template_binding_report_ref")))
                if dft_binding_report_written and latest_sweep_summary.get("dft_template_binding_report_ref")
                else None
            ),
            "dft_template_binding_status": dft_binding_status,
            "dft_template_bound_candidate_count": int(latest_sweep_summary.get("dft_template_bound_candidate_count", 0) or 0),
            "dft_template_blocked_candidate_count": dft_binding_blocked_count,
            "dft_template_binding_gate_passed": (
                (not dft_binding_report_written)
                or (str(dft_binding_status or "") == "passed" and dft_binding_blocked_count == 0)
            ),
            "effectiveness_gate_passed": bool(latest_effectiveness.get("effectiveness_gate_passed", False)),
            "effectiveness_status": latest_effectiveness.get("status"),
            "effectiveness_blockers": [
                blocker.get("reason_id")
                for blocker in latest_effectiveness.get("blockers", []) or []
                if isinstance(blocker, Mapping)
            ],
        })
        if latest_sweep_summary.get("next_campaign_materialization_summary_written"):
            current_source_dir = sweep_dir
        else:
            break

    latest_gate_passed = bool(latest_effectiveness.get("effectiveness_gate_passed", False))
    latest_round = round_summaries[-1] if round_summaries else {}
    dft_binding_seen = any(bool(row.get("dft_template_binding_report_written")) for row in round_summaries)
    latest_dft_binding_gate_passed = bool(latest_round.get("dft_template_binding_gate_passed", True))
    latest_dft_binding_status = latest_round.get("dft_template_binding_status")
    latest_dft_binding_blocked_count = int(latest_round.get("dft_template_blocked_candidate_count", 0) or 0)
    control_plane_closed = bool(latest_gate_passed and latest_dft_binding_gate_passed)
    summary = {
        "schema_version": "dse.search_effectiveness_loop_pilot.v1",
        "out_dir": str(out_dir),
        "source_run_dir": str(source_run_dir),
        "final_source_run_dir": str(current_source_dir),
        "requested_rounds": int(args.rounds),
        "completed_rounds": len(round_summaries),
        "total_executed_count": sum(int(row.get("executed_count", 0) or 0) for row in round_summaries),
        "dft_template_source_bootstrap": dft_template_source_bootstrap or None,
        "dft_template_source_bootstrap_ref": (
            "dft_template_source_bootstrap.json" if dft_template_source_bootstrap else None
        ),
        "latest_search_effectiveness_audit_ref": (
            str(Path(round_summaries[-1]["sweep_dir"]) / "search_effectiveness_audit.json") if round_summaries else None
        ),
        "latest_effectiveness_status": latest_effectiveness.get("status") if latest_effectiveness else None,
        "latest_effectiveness_gate_passed": latest_gate_passed,
        "latest_effectiveness_blockers": [
            blocker.get("reason_id")
            for blocker in latest_effectiveness.get("blockers", []) or []
            if isinstance(blocker, Mapping)
        ] if latest_effectiveness else [],
        "dft_template_binding_report_seen": dft_binding_seen,
        "latest_dft_template_binding_report_ref": latest_round.get("dft_template_binding_report_ref"),
        "latest_dft_template_binding_status": latest_dft_binding_status,
        "latest_dft_template_bound_candidate_count": int(latest_round.get("dft_template_bound_candidate_count", 0) or 0),
        "latest_dft_template_blocked_candidate_count": latest_dft_binding_blocked_count,
        "latest_dft_template_binding_gate_passed": latest_dft_binding_gate_passed,
        "control_plane_search_effectiveness_closed": control_plane_closed,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "claim_boundary": (
            "This loop pilot proves only bounded control-plane search/candidate flow when the latest "
            "search_effectiveness_audit gate passes and any DFT template rows were bound to real Step2 "
            "selectors with no binding blockers. It does not prove convergence, final winner quality, "
            "DFT hardware completion, or release completion."
        ),
        "rounds": round_summaries,
        "commands": command_results,
        "resume_next_actions": [
            "increase rounds or budget only through explicit Campaign/Search widening",
            "use the latest sweep directory as the next source-run-dir for another bounded loop",
            "for DFT template runs, require a passed dft_template_binding_report before Campaign materialization is treated as search-safe",
            "send admitted/materialized candidates to the separate DFT/PPA/gem5/EDA evidence lane only after search gates close",
        ],
    }
    _write_json(out_dir / "search_effectiveness_loop_pilot_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = run_loop(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
