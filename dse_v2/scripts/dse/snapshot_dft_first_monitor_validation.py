#!/usr/bin/env python3
"""Create an auditable snapshot from a DFT-first continuous monitor directory."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


SNAPSHOT_SCHEMA = "dse.dft_first.monitor_validation_snapshot.v6"
FULL_LABELS = {
    "full_pytest",
    "compileall",
    "gem5_config_py_compile",
    "generic_accel_compileall",
    "diff_check",
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"raw": line}
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _date_text() -> str:
    return subprocess.check_output(["date", "+%Y-%m-%d %H:%M:%S %Z (%z)"], text=True).strip()


def build_monitor_validation_snapshot(monitor_dir: Path) -> Dict[str, Any]:
    events = _read_jsonl(monitor_dir / "monitor_events.jsonl")
    latest_iteration: Optional[int] = None
    latest_subset: List[Dict[str, Any]] = []
    iterations = sorted({event.get("iteration") for event in events if isinstance(event.get("iteration"), int)}, reverse=True)
    for iteration in iterations:
        subset = [
            event for event in events
            if event.get("iteration") == iteration and event.get("label") in FULL_LABELS
        ]
        passed_labels = {event.get("label") for event in subset if event.get("returncode") == 0}
        if FULL_LABELS <= passed_labels:
            latest_iteration = iteration
            latest_subset = subset
            break

    log_artifacts = {
        str(event.get("label")): {
            "path": str(event.get("log")),
            "exists": Path(str(event.get("log"))).exists(),
            "size_bytes": Path(str(event.get("log"))).stat().st_size if Path(str(event.get("log"))).exists() else 0,
        }
        for event in latest_subset
    }
    failure_events = _read_jsonl(monitor_dir / "monitor_failures.jsonl")
    failure_iterations = [
        int(event["iteration"]) for event in failure_events
        if isinstance(event.get("iteration"), int)
    ]
    latest_failure_iteration = max(failure_iterations) if failure_iterations else None
    full_after_failure = (
        latest_failure_iteration is None
        or (latest_iteration is not None and latest_iteration > latest_failure_iteration)
    )

    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "checked_at_local": _date_text(),
        "monitor_dir": str(monitor_dir),
        "monitor_status": _load_json(monitor_dir / "monitor_status.json"),
        "required_full_labels": sorted(FULL_LABELS),
        "latest_full_validation_iteration": latest_iteration,
        "latest_full_validation_passed": latest_iteration is not None,
        "latest_full_validation_events": latest_subset,
        "latest_full_log_artifacts": log_artifacts,
        "all_full_logs_preserved": bool(log_artifacts) and all(item.get("exists") for item in log_artifacts.values()),
        "failure_file_exists": (monitor_dir / "monitor_failures.jsonl").exists(),
        "failure_event_count": len(failure_events),
        "latest_failure_iteration": latest_failure_iteration,
        "full_validation_after_latest_failure": full_after_failure,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("monitor_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    snapshot = build_monitor_validation_snapshot(args.monitor_dir)
    if args.out:
        _write_json(args.out, snapshot)
    if not args.quiet:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0 if (
        snapshot["latest_full_validation_passed"]
        and snapshot["all_full_logs_preserved"]
        and snapshot["full_validation_after_latest_failure"]
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
