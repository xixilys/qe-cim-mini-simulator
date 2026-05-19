#!/usr/bin/env python3
"""Build the QE bundle single-workflow L4 evidence gate report.

This is an anti-downgrade helper: an explicit bundle campaign may expand a
bundle into per-opportunity actual-compute attempts, but that is not proof that
one QE workflow offloaded multiple call sites.  The emitted report records that
boundary and rejects bundle-level value unless a future harness provides
``single_qe_workflow_proven=true``.
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

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    build_bundle_single_workflow_l4_evidence_report,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_campaign_statuses(
    *,
    campaign_roots: Sequence[Path],
    campaign_status_paths: Sequence[Path],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in campaign_roots:
        status_path = root / "status.json"
        status = dict(_load_json(status_path))
        status["status_path"] = str(status_path)
        status["campaign_root"] = str(root)
        rows.append(status)
    for status_path in campaign_status_paths:
        status = dict(_load_json(status_path))
        status["status_path"] = str(status_path)
        status.setdefault("campaign_root", str(status_path.parent))
        rows.append(status)
    return rows


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help=(
            "Directory containing offload_bundle_search_space.json. Ignored "
            "when --bundle-space is provided."
        ),
    )
    parser.add_argument("--bundle-space", type=Path, default=None)
    parser.add_argument("--campaign-root", action="append", type=Path, default=[])
    parser.add_argument("--campaign-status", action="append", type=Path, default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.bundle_space is not None:
        bundle_space_path = args.bundle_space
    elif args.artifact_root is not None:
        bundle_space_path = args.artifact_root / "offload_bundle_search_space.json"
    else:
        raise SystemExit("provide --bundle-space or --artifact-root")

    bundle_space = _load_json(bundle_space_path)
    campaign_statuses = _load_campaign_statuses(
        campaign_roots=args.campaign_root,
        campaign_status_paths=args.campaign_status,
    )
    report = build_bundle_single_workflow_l4_evidence_report(
        bundle_space,
        campaign_statuses,
    )
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "bundle_single_workflow_l4_evidence_report.json", report)
    status = {
        "schema_version": "dse.qe_bundle_single_workflow_l4_evidence_status.v1",
        "status": report.get("status"),
        "report_path": str(
            out_dir / "bundle_single_workflow_l4_evidence_report.json"
        ),
        "bundle_level_valuable_l4_count": report.get(
            "bundle_level_valuable_l4_count", 0
        ),
        "per_opportunity_expanded_campaign_bundle_count": report.get(
            "per_opportunity_expanded_campaign_bundle_count", 0
        ),
        "campaign_status_count": report.get("campaign_status_count", 0),
        "deliverable_complete": False,
        "claim_boundary": (
            "bundle single-workflow evidence gate status only; expanded "
            "per-opportunity campaigns cannot claim bundle-level value"
        ),
    }
    _write_json(out_dir / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
