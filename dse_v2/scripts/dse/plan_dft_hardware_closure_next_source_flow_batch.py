#!/usr/bin/env python3
"""Plan the next fail-closed Wave36 real source-flow candidate batch.

This helper is intentionally non-executing: it reads the closure packet index,
existing real-source-flow run manifests, and obvious in-flight run markers, then
writes a small JSON recommendation plus an optional shell launcher.  The shell
launcher uses nohup/background commands only when a human runs it later; this
script never starts EDA tools or mutates run artifacts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.evidence_ledger import write_json  # noqa: E402
from dse_v2.scripts.dse.build_dft_hardware_closure_latest_source_flow_map import (  # noqa: E402
    discover_latest_source_flow_roots,
)

PLAN_SCHEMA = "dse.dft.hardware_closure_next_source_flow_batch_plan.v1"
_CLAIM_BOUNDARY = (
    "Wave36 next real source-flow batch planning is a fail-closed queue helper. "
    "It only recommends candidate-level invocations for existing packet-index "
    "candidates that do not already have ready all-eight source-flow runs and "
    "are not obviously in flight. It does not execute EDA tools, create source "
    "flows, adjudicate hard gates, certify PPA, or upgrade hardware/deliverable "
    "completion."
)
_READY_RUN_STATUS = "source_flows_ready_pending_step5"
_RUNNER = "dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py"
_RUNNING_DIR_GLOB = "wave36_real_source_flow_run_*"
_RUN_DIR_CANDIDATE_RE = re.compile(
    r"wave36_real_source_flow_run_(?P<candidate_id>.+?)_all8(?:_|$)"
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _bool_arg(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _append_unique(rows: list[str], value: Any) -> None:
    candidate_id = str(value or "").strip()
    if candidate_id and candidate_id not in rows:
        rows.append(candidate_id)


def _int_field(payload: Mapping[str, Any], field: str, default: int = -1) -> int:
    value = payload.get(field, default)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_order_from_packet_index(path: Path) -> tuple[list[str], list[str]]:
    payload = _load_json(path)
    errors: list[str] = []
    if not payload:
        return [], ["closure_packet_index_unreadable_or_invalid_json"]

    candidate_ids: list[str] = []
    for candidate_id in payload.get("candidate_ids", []) or []:
        _append_unique(candidate_ids, candidate_id)

    packets = payload.get("packets", [])
    if isinstance(packets, list):
        for packet in packets:
            if not isinstance(packet, Mapping):
                continue
            for candidate_id in packet.get("candidate_ids", []) or []:
                _append_unique(candidate_ids, candidate_id)

            packet_ref = packet.get("packet_json", {})
            packet_path_value = None
            if isinstance(packet_ref, Mapping):
                packet_path_value = packet_ref.get("path")
            if not packet_path_value:
                continue
            packet_path = Path(str(packet_path_value))
            if not packet_path.is_absolute():
                packet_path = path.parent / packet_path
            packet_payload = _load_json(packet_path)
            for candidate_id in packet_payload.get("candidate_ids", []) or []:
                _append_unique(candidate_ids, candidate_id)
            units = packet_payload.get("units", [])
            if isinstance(units, list):
                for unit in units:
                    if isinstance(unit, Mapping):
                        _append_unique(candidate_ids, unit.get("candidate_id"))
    else:
        errors.append("closure_packet_index_packets_not_list")

    if not candidate_ids:
        errors.append("closure_packet_index_candidate_order_empty")
    return candidate_ids, errors


def _ready_candidate_ids(run_roots: Sequence[Path]) -> list[str]:
    _, discovery_status = discover_latest_source_flow_roots(run_roots=run_roots)
    ready: list[str] = []
    for row in discovery_status.get("included_runs", []) or []:
        if not isinstance(row, Mapping):
            continue
        for candidate_id in row.get("candidate_ids", []) or []:
            _append_unique(ready, candidate_id)
    return ready


def _manifest_is_ready(payload: Mapping[str, Any], run_dir: Path) -> bool:
    return (
        payload.get("status") == _READY_RUN_STATUS
        and _int_field(payload, "source_flow_ready_count") == 8
        and _int_field(payload, "blocked_unit_count") == 0
        and (run_dir / "source_flows").is_dir()
        and payload.get("hardware_completion_eligible") is not True
        and payload.get("deliverable_complete") is not True
    )


def _running_dirs_by_candidate(
    run_roots: Sequence[Path], candidates: Sequence[str]
) -> dict[str, list[str]]:
    candidate_set = set(candidates)
    matches: dict[str, list[str]] = {candidate: [] for candidate in candidates}
    for run_root in run_roots:
        root = Path(run_root)
        if not root.exists() or not root.is_dir():
            continue
        for run_dir in sorted(root.glob(_RUNNING_DIR_GLOB)):
            if not run_dir.is_dir():
                continue
            match = _RUN_DIR_CANDIDATE_RE.search(run_dir.name)
            if not match:
                continue
            candidate_id = match.group("candidate_id")
            if candidate_id not in candidate_set:
                continue
            manifest = run_dir / "dft_hardware_closure_real_source_flow_run.json"
            if manifest.exists() and _manifest_is_ready(_load_json(manifest), run_dir):
                continue
            matches[candidate_id].append(str(run_dir))
    return {candidate: paths for candidate, paths in matches.items() if paths}


def _process_lines() -> list[str]:
    try:
        result = subprocess.run(
            [
                "pgrep",
                "-af",
                (
                    "run_dft_hardware_closure_real_source_flows.py"
                    "|wave36_real_source_flow_run_"
                ),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return []
    if result.returncode not in {0, 1}:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _running_processes_by_candidate(candidates: Sequence[str]) -> dict[str, list[str]]:
    lines = _process_lines()
    candidate_set = set(candidates)
    matches: dict[str, list[str]] = {candidate: [] for candidate in candidates}
    for line in lines:
        matched_candidate_ids: set[str] = set()
        for run_match in _RUN_DIR_CANDIDATE_RE.finditer(line):
            candidate_id = run_match.group("candidate_id")
            if candidate_id in candidate_set:
                matched_candidate_ids.add(candidate_id)
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()
        for index, token in enumerate(tokens):
            candidate_id = ""
            if token == "--candidate-id" and index + 1 < len(tokens):
                candidate_id = tokens[index + 1]
            elif token.startswith("--candidate-id="):
                candidate_id = token.split("=", 1)[1]
            if candidate_id in candidate_set:
                matched_candidate_ids.add(candidate_id)
        for candidate_id in sorted(matched_candidate_ids):
            if line not in matches[candidate_id]:
                matches[candidate_id].append(line)
    return {candidate: rows for candidate, rows in matches.items() if rows}


def _detect_running_candidate_ids(
    *, run_roots: Sequence[Path], candidates: Sequence[str], include_process_scan: bool
) -> tuple[list[str], dict[str, Any]]:
    dir_matches = _running_dirs_by_candidate(run_roots, candidates)
    process_matches = (
        _running_processes_by_candidate(candidates) if include_process_scan else {}
    )
    running = [
        candidate_id
        for candidate_id in candidates
        if candidate_id in dir_matches or candidate_id in process_matches
    ]
    return running, {
        "directory_matches": dir_matches,
        "process_scan_enabled": include_process_scan,
        "process_matches": process_matches,
    }


def _command_for_candidate(
    *,
    candidate_id: str,
    closure_packet_index: Path,
    run_root: Path,
    ssh_target: str,
    timeout_s: int,
    run_tag: str,
) -> list[str]:
    out_dir = run_root / f"wave36_real_source_flow_run_{candidate_id}_all8_{run_tag}"
    return [
        sys.executable,
        _RUNNER,
        "--out",
        str(out_dir),
        "--closure-packet-index",
        str(closure_packet_index),
        "--candidate-id",
        candidate_id,
        "--jobs",
        "1",
        "--ssh-target",
        ssh_target,
        "--timeout-s",
        str(timeout_s),
        "--quiet",
    ]


def _shell_text(commands: Sequence[Sequence[str]]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated fail-closed Wave36 source-flow queue helper.",
        "# Review before running. This file is generated only; the planner does not execute it.",
    ]
    if not commands:
        lines.extend(["", "echo 'No recommended candidates to launch.'"])
    for index, command in enumerate(commands, start=1):
        out_dir = "source_flow_batch_" + str(index)
        if "--out" in command:
            out_dir = command[command.index("--out") + 1]
        log_path = f"{out_dir}.nohup.log"
        lines.extend(
            [
                "",
                f"mkdir -p {shlex.quote(str(Path(out_dir).parent))}",
                "nohup "
                + " ".join(shlex.quote(str(part)) for part in command)
                + f" > {shlex.quote(log_path)} 2>&1 &",
                "echo $! " + f"> {shlex.quote(str(out_dir))}.pid",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_plan(
    *,
    closure_packet_index: Path,
    run_roots: Sequence[Path],
    max_new_candidates: int,
    exclude_running: bool,
    ssh_target: str,
    timeout_s: int,
    run_tag: str | None = None,
) -> dict[str, Any]:
    candidate_order, errors = _candidate_order_from_packet_index(closure_packet_index)
    ready_set = set(_ready_candidate_ids(run_roots))
    ready = [candidate for candidate in candidate_order if candidate in ready_set]
    pending = [candidate for candidate in candidate_order if candidate not in set(ready)]
    limit = max(0, int(max_new_candidates))
    if errors:
        running: list[str] = []
        running_evidence: dict[str, Any] = {
            "directory_matches": {},
            "process_scan_enabled": False,
            "process_matches": {},
            "skipped_due_to_packet_index_errors": True,
        }
        recommended: list[str] = []
    else:
        running, running_evidence = _detect_running_candidate_ids(
            run_roots=run_roots,
            candidates=pending,
            include_process_scan=exclude_running,
        )
        running_set = set(running)
        selectable = [
            candidate
            for candidate in pending
            if not (exclude_running and candidate in running_set)
        ]
        recommended = selectable[:limit]
    recommended_set = set(recommended)
    blocked_or_pending = [
        candidate for candidate in pending if candidate not in recommended_set
    ]
    primary_run_root = Path(run_roots[0]) if run_roots else Path("runs/dse")
    resolved_run_tag = run_tag or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commands = [
        _command_for_candidate(
            candidate_id=candidate_id,
            closure_packet_index=closure_packet_index,
            run_root=primary_run_root,
            ssh_target=ssh_target,
            timeout_s=timeout_s,
            run_tag=resolved_run_tag,
        )
        for candidate_id in recommended
    ]

    if errors:
        status = "blocked_invalid_or_empty_closure_packet_index"
    elif recommended:
        status = "planned_next_source_flow_batch"
    elif candidate_order and len(ready) == len(candidate_order):
        status = "blocked_no_new_candidates_all_ready"
    else:
        status = "blocked_no_recommended_candidates"

    return {
        "schema_version": PLAN_SCHEMA,
        "status": status,
        "source_artifacts": {
            "closure_packet_index": str(closure_packet_index),
            "run_roots": [str(Path(root)) for root in run_roots],
        },
        "candidate_order": candidate_order,
        "ready_candidate_ids": ready,
        "running_candidate_ids": running,
        "blocked_or_pending_candidate_ids": blocked_or_pending,
        "recommended_candidate_ids": recommended,
        "commands": commands,
        "max_new_candidates": limit,
        "exclude_running": exclude_running,
        "ssh_target": ssh_target,
        "timeout_s": timeout_s,
        "run_tag": resolved_run_tag,
        "running_detection": running_evidence,
        "error_count": len(errors),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
        "deliverable_complete": False,
        "hardware_completion_eligible": False,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure-packet-index", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, action="append", default=[])
    parser.add_argument("--max-new-candidates", type=int, default=2)
    parser.add_argument("--exclude-running", type=_bool_arg, default=True)
    parser.add_argument("--ssh-target", default="ic-eda")
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument(
        "--run-tag",
        default=None,
        help="Optional unique run suffix for generated --out directories. Defaults to current UTC timestamp.",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--emit-shell", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_roots = args.run_root if args.run_root else [Path("runs/dse")]
    plan = build_plan(
        closure_packet_index=args.closure_packet_index,
        run_roots=run_roots,
        max_new_candidates=args.max_new_candidates,
        exclude_running=args.exclude_running,
        ssh_target=args.ssh_target,
        timeout_s=args.timeout_s,
        run_tag=args.run_tag,
    )
    write_json(args.out, plan)
    if args.emit_shell:
        shell_path = args.out.parent / "next_source_flow_batch.sh"
        shell_path.parent.mkdir(parents=True, exist_ok=True)
        shell_path.write_text(_shell_text(plan["commands"]), encoding="utf-8")
        shell_path.chmod(0o755)
        plan["shell_script"] = str(shell_path)
        write_json(args.out, plan)
    if not args.quiet:
        print(json.dumps(plan, indent=2, sort_keys=True))
    return 0 if plan["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
