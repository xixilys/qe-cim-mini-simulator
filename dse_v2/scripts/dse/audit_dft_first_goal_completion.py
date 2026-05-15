#!/usr/bin/env python3
"""Audit the active DFT-first goal against concrete artifacts.

This is a prompt-to-artifact audit, not another proxy test.  It recomputes the
DFT end-to-end run audits, reads the guard/monitor evidence, and reports whether
the goal is complete, still in progress, or failed.  The midnight horizon is a
first-class requirement: before the horizon this script must report
``in_progress`` even when all technical DSE evidence is green.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.audit_dft_first_end_to_end_run import audit_run


GOAL_AUDIT_SCHEMA = "dse.dft_first.goal_completion_audit.v1"
DEFAULT_HORIZON_LOCAL = "2026-05-15 00:00:00"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

REQUIRED_COMMON_CHECKS = {
    "summary_status_complete",
    "scope_qe_and_domain_neutral",
    "no_dft_correctness_claim",
    "step1_qe_source_facts_preserved",
    "step1_facts_only",
    "step1_no_decision_fields",
    "step1_domain_summaries_present",
    "step2_candidate_records_present",
    "best_architecture_from_measured_step3",
    "step4_attempted_real_gem5",
    "step4_selected_attempt_bound_to_best_architecture",
    "step4_non_smoke_artifacts_present",
    "step4_gem5_stats_semantics_present",
    "step4_manifest_replays_real_gem5",
    "step4_gem5_proof_checks_pass",
    "step4_no_smoke_demo_or_fallback_tokens",
    "step4_nonzero_accelerator_activity",
    "step4_activity_matches_raw_result",
}

REQUIRED_PREFIX_CHECKS = {
    "step2_artifacts_present:",
    "step2_dft_fpga_policy_hints:",
    "step2_estimate_boundary:",
    "step3_timing_verified:",
    "step3_raw_timing_artifacts_consistent:",
    "step3_artifact_manifest_hashes:",
    "step3_raw_result_replay_bound:",
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _status_item(requirement: str, status: str, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "requirement": requirement,
        "status": status,
        "evidence": dict(evidence),
    }


def _audit_ids(audit: Mapping[str, Any]) -> set[str]:
    return {str(check.get("check_id")) for check in audit.get("checks", []) or [] if isinstance(check, Mapping)}


def _has_prefixed_check(check_ids: Iterable[str], prefix: str) -> bool:
    return any(check_id.startswith(prefix) for check_id in check_ids)


def _audit_covers_required_checks(audit: Mapping[str, Any]) -> tuple[bool, Dict[str, Any]]:
    check_ids = _audit_ids(audit)
    missing_common = sorted(REQUIRED_COMMON_CHECKS - check_ids)
    missing_prefixes = sorted(prefix for prefix in REQUIRED_PREFIX_CHECKS if not _has_prefixed_check(check_ids, prefix))
    return (
        audit.get("status") == "passed"
        and audit.get("failed_count") == 0
        and not missing_common
        and not missing_prefixes,
        {
            "audit_status": audit.get("status"),
            "check_count": audit.get("check_count"),
            "failed_count": audit.get("failed_count"),
            "missing_common_checks": missing_common,
            "missing_prefix_checks": missing_prefixes,
        },
    )


def _pid_alive(pid_file: Path) -> tuple[bool, Optional[str]]:
    if not pid_file.exists():
        return False, None
    pid = pid_file.read_text(encoding="utf-8").strip()
    if not pid:
        return False, pid
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False, pid
    return True, pid


def _shell_sleep_command_hits(script_path: Path) -> List[Dict[str, Any]]:
    if not script_path.exists():
        return [{"path": str(script_path), "line": None, "text": "missing_monitor_script"}]
    hits: List[Dict[str, Any]] = []
    for lineno, line in enumerate(script_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        command_part = line.split("#", 1)[0].strip()
        if not command_part:
            continue
        tokens = command_part.replace(";", " ; ").replace("&&", " && ").replace("||", " || ").split()
        for index, token in enumerate(tokens):
            if token == "sleep" and (index == 0 or tokens[index - 1] in {";", "&&", "||", "do", "then"}):
                hits.append({"path": str(script_path), "line": lineno, "text": line.strip()})
                break
    return hits


def _date_text() -> str:
    return subprocess.check_output(["date", "+%Y-%m-%d %H:%M:%S %Z (%z)"], text=True).strip()


def _parse_local_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=LOCAL_TZ)


def _monitor_requirement_status(monitor_dir: Path, *, horizon_reached: bool) -> tuple[str, Dict[str, Any]]:
    status_path = monitor_dir / "monitor_status.json"
    status = _load_json(status_path)
    alive, pid = _pid_alive(monitor_dir / "monitor.pid")
    failure_file = monitor_dir / "monitor_failures.jsonl"
    failure_events = []
    if failure_file.exists():
        for line in failure_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"raw": line}
            if isinstance(event, dict):
                failure_events.append(event)
    failure_iterations = [
        int(event["iteration"]) for event in failure_events
        if isinstance(event.get("iteration"), int)
    ]
    latest_failure_iteration = max(failure_iterations) if failure_iterations else None
    completed_horizon = status.get("last_status") == "completed_horizon"
    sleep_hits = _shell_sleep_command_hits(monitor_dir / "monitor_no_sleep.sh")
    no_sleep_verified = status.get("no_sleep_command_used") is True and not sleep_hits
    if status.get("last_failure") or not no_sleep_verified:
        requirement_status = "failed"
    elif horizon_reached:
        requirement_status = "passed" if completed_horizon or alive else "failed"
    else:
        requirement_status = "in_progress" if alive else "failed"
    return requirement_status, {
        "monitor_dir": str(monitor_dir),
        "monitor_pid": pid,
        "monitor_alive": alive,
        "monitor_status": status,
        "failure_file_exists": failure_file.exists(),
        "failure_event_count": len(failure_events),
        "latest_failure_iteration": latest_failure_iteration,
        "horizon_reached": horizon_reached,
        "no_sleep_status_flag": status.get("no_sleep_command_used"),
        "sleep_command_hits": sleep_hits,
    }


def _snapshot_freshness(snapshot: Mapping[str, Any], monitor_evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """Return freshness evidence for a monitor validation snapshot.

    A full-suite snapshot is only useful as completion evidence if it is close
    to the live monitor's current iteration.  Older snapshots can still be
    valuable history, but they must not be accepted as the final "recent full
    validation" proof after many additional monitor iterations have run.

    Historical fixtures may omit iteration fields; in that case this check is
    intentionally non-blocking and records that freshness could not be measured.
    """
    monitor_status = monitor_evidence.get("monitor_status")
    if not isinstance(monitor_status, Mapping):
        monitor_status = {}
    monitor_iteration = monitor_status.get("iteration")
    latest_full_iteration = snapshot.get("latest_full_validation_iteration")
    full_suite_every = monitor_status.get("full_suite_every_iterations")
    snapshot_status = snapshot.get("monitor_status")
    if not isinstance(snapshot_status, Mapping):
        snapshot_status = {}
    if not isinstance(full_suite_every, int):
        full_suite_every = snapshot_status.get("full_suite_every_iterations")
    if not isinstance(full_suite_every, int) or full_suite_every <= 0:
        full_suite_every = 20

    measurable = isinstance(monitor_iteration, int) and isinstance(latest_full_iteration, int)
    allowed_iteration_lag = full_suite_every + 5
    iteration_lag = (
        monitor_iteration - latest_full_iteration
        if measurable else None
    )
    fresh_enough = (
        True if not measurable
        else 0 <= int(iteration_lag) <= allowed_iteration_lag
    )
    return {
        "monitor_iteration": monitor_iteration,
        "full_suite_every_iterations": full_suite_every,
        "latest_full_validation_iteration": latest_full_iteration,
        "snapshot_iteration_lag": iteration_lag,
        "allowed_iteration_lag": allowed_iteration_lag,
        "snapshot_freshness_measurable": measurable,
        "snapshot_fresh_enough": fresh_enough,
    }


def build_goal_completion_audit(
    *,
    main_run: Path,
    official_run: Path,
    no_smoke_scan: Path,
    domain_boundary_scan: Path,
    external_reference_scan: Path,
    tamper_probe: Path,
    monitor_dir: Path,
    monitor_snapshot: Optional[Path],
    horizon_local: str = DEFAULT_HORIZON_LOCAL,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or datetime.now(LOCAL_TZ)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=LOCAL_TZ)
    horizon_dt = _parse_local_datetime(horizon_local)
    horizon_reached = now_dt >= horizon_dt

    main_audit = audit_run(main_run)
    official_audit = audit_run(official_run)
    main_ok, main_evidence = _audit_covers_required_checks(main_audit)
    official_ok, official_evidence = _audit_covers_required_checks(official_audit)

    no_smoke = _load_json(no_smoke_scan)
    domain = _load_json(domain_boundary_scan)
    external = _load_json(external_reference_scan)
    tamper = _load_json(tamper_probe)
    snapshot = _load_json(monitor_snapshot) if monitor_snapshot else {}
    monitor_status, monitor_evidence = _monitor_requirement_status(monitor_dir, horizon_reached=horizon_reached)
    latest_failure_iteration = monitor_evidence.get("latest_failure_iteration")
    latest_full_iteration = snapshot.get("latest_full_validation_iteration")
    snapshot_after_latest_failure = (
        latest_failure_iteration is None
        or (
            isinstance(latest_full_iteration, int)
            and latest_full_iteration > int(latest_failure_iteration)
        )
    )
    snapshot_freshness = _snapshot_freshness(snapshot, monitor_evidence)

    checklist: List[Dict[str, Any]] = [
        _status_item(
            "Use date and keep validation running until 2026-05-15 00:00 CST without a sleep-based idle loop",
            "passed" if horizon_reached and monitor_status == "passed" else monitor_status,
            {
                "checked_at_local": _date_text(),
                "now_iso": now_dt.isoformat(),
                "horizon_local": horizon_dt.isoformat(),
                **monitor_evidence,
            },
        ),
        _status_item(
            "QE source parsing, Step1 facts-only characterization, Step2 FPGA candidates, Step3 measured timing, and Step4 real gem5 evidence are all covered by the main hardened run audit",
            "passed" if main_ok else "failed",
            {"run": str(main_run), **main_evidence},
        ),
        _status_item(
            "Official QE multi-stage source reproduction covers the same end-to-end gates",
            "passed" if official_ok else "failed",
            {"run": str(official_run), **official_evidence},
        ),
        _status_item(
            "No smoke/demo/skip/fallback evidence is accepted",
            "passed" if no_smoke.get("status") == "passed" and all(item.get("passed_guard") is True for item in no_smoke.get("items", []) or []) else "failed",
            {
                "scan": str(no_smoke_scan),
                "scan_status": no_smoke.get("status"),
                "item_count": len(no_smoke.get("items", []) or []),
            },
        ),
        _status_item(
            "Core/mapping remain domain-neutral while DFT/QE logic stays in reference_workloads",
            "passed" if domain.get("status") == "passed" and domain.get("blocked_hit_count") == 0 else "failed",
            {
                "scan": str(domain_boundary_scan),
                "scan_status": domain.get("status"),
                "blocked_hit_count": domain.get("blocked_hit_count"),
            },
        ),
        _status_item(
            "Raw artifact tampering is detected, including copied-run source_artifact rebasing",
            "passed" if tamper.get("probe_status") == "passed" and all(case.get("passed_probe") is True for case in tamper.get("cases", []) or []) else "failed",
            {
                "probe": str(tamper_probe),
                "probe_status": tamper.get("probe_status"),
                "case_count": len(tamper.get("cases", []) or []),
            },
        ),
        _status_item(
            "Public/open-source project and paper anchors are recorded without letting external models decide the final architecture",
            "passed" if external.get("status") == "passed" and external.get("integration_decision", {}).get("no_final_claim_from_external_models") is True else "failed",
            {
                "scan": str(external_reference_scan),
                "scan_status": external.get("status"),
                "source_count": len(external.get("sources", []) or []),
                "no_final_claim_from_external_models": external.get("integration_decision", {}).get("no_final_claim_from_external_models"),
            },
        ),
        _status_item(
            "Continuous monitor has a recent full-suite validation snapshot with preserved logs",
            "passed" if snapshot.get("latest_full_validation_passed") is True and snapshot.get("all_full_logs_preserved") is True and snapshot_after_latest_failure and snapshot_freshness["snapshot_fresh_enough"] is True else "failed",
            {
                "snapshot": str(monitor_snapshot) if monitor_snapshot else None,
                "schema_version": snapshot.get("schema_version"),
                "latest_full_validation_iteration": snapshot.get("latest_full_validation_iteration"),
                "latest_full_validation_passed": snapshot.get("latest_full_validation_passed"),
                "all_full_logs_preserved": snapshot.get("all_full_logs_preserved"),
                "failure_file_exists": snapshot.get("failure_file_exists"),
                "latest_failure_iteration": latest_failure_iteration,
                "snapshot_after_latest_failure": snapshot_after_latest_failure,
                **snapshot_freshness,
            },
        ),
    ]

    failed = [item for item in checklist if item["status"] == "failed"]
    in_progress = [item for item in checklist if item["status"] == "in_progress"]
    status = "failed" if failed else "in_progress" if in_progress else "complete"
    return {
        "schema_version": GOAL_AUDIT_SCHEMA,
        "checked_at_local": _date_text(),
        "status": status,
        "completion_decision": (
            "ready_to_mark_complete" if status == "complete" else
            "do_not_mark_complete_before_midnight_horizon" if in_progress else
            "do_not_mark_complete_failed_requirements"
        ),
        "horizon_reached": horizon_reached,
        "prompt_to_artifact_checklist": checklist,
        "failed_requirements": failed,
        "in_progress_requirements": in_progress,
        "main_audit": main_audit,
        "official_audit": official_audit,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-run", type=Path, required=True)
    parser.add_argument("--official-run", type=Path, required=True)
    parser.add_argument("--no-smoke-scan", type=Path, required=True)
    parser.add_argument("--domain-boundary-scan", type=Path, required=True)
    parser.add_argument("--external-reference-scan", type=Path, required=True)
    parser.add_argument("--tamper-probe", type=Path, required=True)
    parser.add_argument("--monitor-dir", type=Path, required=True)
    parser.add_argument("--monitor-snapshot", type=Path, default=None)
    parser.add_argument("--horizon-local", default=DEFAULT_HORIZON_LOCAL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--allow-in-progress", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    audit = build_goal_completion_audit(
        main_run=args.main_run,
        official_run=args.official_run,
        no_smoke_scan=args.no_smoke_scan,
        domain_boundary_scan=args.domain_boundary_scan,
        external_reference_scan=args.external_reference_scan,
        tamper_probe=args.tamper_probe,
        monitor_dir=args.monitor_dir,
        monitor_snapshot=args.monitor_snapshot,
        horizon_local=args.horizon_local,
    )
    if args.out:
        _write_json(args.out, audit)
    if not args.quiet:
        print(json.dumps(audit, indent=2, sort_keys=True))
    if audit["status"] == "complete":
        return 0
    if audit["status"] == "in_progress" and args.allow_in_progress:
        return 0
    return 3 if audit["status"] == "in_progress" else 2


if __name__ == "__main__":
    raise SystemExit(main())
