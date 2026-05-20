#!/usr/bin/env python3
"""Build source_flow_map.json from latest ready real-source-flow run dirs.

This helper is a thin discovery wrapper around
``write_dft_hardware_closure_source_flow_map``.  It scans repeatable run roots
for wave36 real-source-flow run manifests, includes only fail-closed ready
``*_all8_*`` runs, and records inclusion/exclusion provenance without upgrading
hardware completion claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.evidence_ledger import write_json  # noqa: E402
from dse_v2.reference_workloads.dft_hardware_closure_source_flow_map import (  # noqa: E402
    write_dft_hardware_closure_source_flow_map,
)

DISCOVERY_STATUS_SCHEMA = (
    "dse.dft.hardware_closure_latest_source_flow_map_discovery_status.v1"
)
_READY_RUN_STATUS = "source_flows_ready_pending_step5"
_DISCOVERY_GLOB = (
    "wave36_real_source_flow_run_*_all8_*/"
    "dft_hardware_closure_real_source_flow_run.json"
)
_CLAIM_BOUNDARY = (
    "Latest DFT hardware closure source-flow map discovery selects only existing "
    "real-source-flow run source_flows roots whose run manifests are already "
    "ready-pending-Step5 for all eight units. It does not run tools, adjudicate "
    "hard gates, certify PPA, or upgrade hardware/deliverable completion."
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _split_csv(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            stripped = item.strip()
            if stripped:
                items.append(stripped)
    return items


def _run_candidate_ids(payload: Mapping[str, Any]) -> list[str]:
    candidate_ids: set[str] = set()
    units = payload.get("units", [])
    if isinstance(units, list):
        for unit in units:
            if isinstance(unit, Mapping) and unit.get("candidate_id"):
                candidate_ids.add(str(unit["candidate_id"]))
    flows = payload.get("flows", [])
    if isinstance(flows, list):
        for flow in flows:
            if isinstance(flow, Mapping) and flow.get("candidate_id"):
                candidate_ids.add(str(flow["candidate_id"]))
    return sorted(candidate_ids)


def _int_field(payload: Mapping[str, Any], field: str, default: int = -1) -> int:
    value = payload.get(field, default)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_filter_blocker(
    payload: Mapping[str, Any], candidate_filter: set[str]
) -> str | None:
    if not candidate_filter:
        return None
    candidate_ids = set(_run_candidate_ids(payload))
    if candidate_ids and candidate_ids.isdisjoint(candidate_filter):
        return "candidate_id_filter_mismatch"
    if not candidate_ids:
        return "candidate_id_filter_unverifiable"
    return None


def _ready_run_blockers(
    manifest_path: Path,
    payload: Mapping[str, Any],
    *,
    candidate_filter: set[str],
) -> list[str]:
    blockers: list[str] = []
    if payload.get("status") != _READY_RUN_STATUS:
        blockers.append("run_status_not_source_flows_ready_pending_step5")
    if _int_field(payload, "source_flow_ready_count") != 8:
        blockers.append("source_flow_ready_count_not_8")
    if _int_field(payload, "blocked_unit_count") != 0:
        blockers.append("blocked_unit_count_not_0")
    filter_blocker = _candidate_filter_blocker(payload, candidate_filter)
    if filter_blocker:
        blockers.append(filter_blocker)
    if not (manifest_path.parent / "source_flows").is_dir():
        blockers.append("source_flows_root_missing")
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            blockers.append(f"claim_upgrade_{field}")
    return blockers


def discover_latest_source_flow_roots(
    *,
    run_roots: Sequence[Path],
    candidate_ids: Sequence[str] = (),
) -> tuple[list[Path], dict[str, Any]]:
    """Discover ready real-source-flow run ``source_flows`` roots."""

    candidate_filter = set(candidate_ids)
    seen_manifests: set[Path] = set()
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    source_flow_roots: list[Path] = []

    for run_root in run_roots:
        root = Path(run_root)
        for manifest_path in sorted(root.glob(_DISCOVERY_GLOB)):
            resolved = manifest_path.resolve()
            if resolved in seen_manifests:
                continue
            seen_manifests.add(resolved)
            payload = _load_json(manifest_path)
            source_flow_root = manifest_path.parent / "source_flows"
            candidate_id_values = _run_candidate_ids(payload)
            blockers = _ready_run_blockers(
                manifest_path, payload, candidate_filter=candidate_filter
            )
            row = {
                "run_dir": str(manifest_path.parent),
                "manifest": str(manifest_path),
                "source_flow_root": str(source_flow_root),
                "candidate_ids": candidate_id_values,
                "run_status": payload.get("status"),
                "source_flow_ready_count": _int_field(
                    payload, "source_flow_ready_count", default=0
                ),
                "blocked_unit_count": _int_field(
                    payload, "blocked_unit_count", default=0
                ),
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
            if blockers:
                excluded.append(
                    {
                        **row,
                        "status": "excluded",
                        "blocker_ids": blockers,
                    }
                )
                continue
            included.append({**row, "status": "included", "blocker_ids": []})
            source_flow_roots.append(source_flow_root)

    discovery_status = {
        "schema_version": DISCOVERY_STATUS_SCHEMA,
        "status": (
            "ready_source_flow_roots_discovered"
            if included
            else "blocked_no_ready_source_flow_runs_discovered"
        ),
        "run_roots": [str(Path(root)) for root in run_roots],
        "discovery_glob": _DISCOVERY_GLOB,
        "candidate_ids": sorted(candidate_filter),
        "included_run_count": len(included),
        "excluded_run_count": len(excluded),
        "source_flow_root_count": len(source_flow_roots),
        "source_flow_roots": [str(root) for root in source_flow_roots],
        "included_runs": included,
        "excluded_runs": excluded,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return source_flow_roots, discovery_status


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--closure-packet-index", type=Path, required=True)
    parser.add_argument(
        "--run-root",
        type=Path,
        action="append",
        default=[],
        help="Run root to scan; repeatable. Defaults to runs/dse when omitted.",
    )
    parser.add_argument(
        "--candidate-id",
        action="append",
        default=[],
        help="Candidate filter; repeatable or comma-separated.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_roots = args.run_root if args.run_root else [Path("runs/dse")]
    source_flow_roots, discovery_status = discover_latest_source_flow_roots(
        run_roots=run_roots,
        candidate_ids=_split_csv(args.candidate_id),
    )
    status = write_dft_hardware_closure_source_flow_map(
        args.out,
        closure_packet_index_path=args.closure_packet_index,
        source_flow_roots=source_flow_roots,
    )
    write_json(Path(args.out) / "discovery_status.json", discovery_status)
    if not args.quiet:
        print(
            json.dumps(
                {
                    "source_flow_map_status": status,
                    "discovery_status": discovery_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
