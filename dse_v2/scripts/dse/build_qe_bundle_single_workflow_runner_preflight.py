#!/usr/bin/env python3
"""Preflight a true QE single-workflow multi-callsite bundle runner.

This artifact is deliberately not value evidence.  It prepares the runtime
manifest/slot plan for one QE process to exercise multiple offloaded callsites,
then reports the remaining blockers before any bundle-level value claim is
allowed.
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

from dse_v2.scripts.dse.run_qe_callgraph_offload_l4_smoke import (  # noqa: E402
    _install_bundle_runtime_env,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_path_component(value: Any) -> str:
    return "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
        for ch in str(value)
    ).strip("_") or "target"


def _bundle_by_id(bundle_space: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("bundle_id")): dict(row)
        for row in bundle_space.get("bundles", []) or []
        if isinstance(row, Mapping) and row.get("bundle_id")
    }


def _opportunity_by_id(opportunity_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("opportunity_id")): dict(row)
        for row in opportunity_manifest.get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }


def build_bundle_single_workflow_runner_preflight(
    *,
    bundle_space: Mapping[str, Any],
    opportunity_manifest: Mapping[str, Any],
    bundle_id: str,
    out_dir: Path,
) -> dict[str, Any]:
    bundles = _bundle_by_id(bundle_space)
    opportunities = _opportunity_by_id(opportunity_manifest)
    bundle = bundles.get(str(bundle_id))
    blockers: list[str] = []
    missing_opportunities: list[str] = []
    manifest_payload: dict[str, Any] | None = None
    env: dict[str, str] = {}
    target_inputs: list[dict[str, Any]] = []

    if bundle is None:
        blockers.append(f"unknown_bundle_id:{bundle_id}")
        opportunity_ids: list[str] = []
    else:
        opportunity_ids = [str(item) for item in bundle.get("opportunity_ids") or []]
        if bundle.get("granularity") != "bundle":
            blockers.append("not_larger_granularity_bundle")
        if len(opportunity_ids) <= 1:
            blockers.append("single_opportunity_bundle_not_multi_callsite")
        if bundle.get("runnable_as_single_qe_workflow") is not True:
            blockers.append("bundle_not_marked_runnable_as_single_qe_workflow")
        for opportunity_id in opportunity_ids:
            opportunity = opportunities.get(opportunity_id)
            if opportunity is None:
                missing_opportunities.append(opportunity_id)
                continue
            slot_dir = out_dir / "bundle_runtime_slots" / _safe_path_component(opportunity_id)
            bridge_script = slot_dir / "bridge_command.sh"
            bridge_script.parent.mkdir(parents=True, exist_ok=True)
            bridge_script.write_text(
                "#!/bin/sh\n"
                "echo 'bundle preflight placeholder: not executed' >&2\n"
                "exit 97\n",
                encoding="utf-8",
            )
            bridge_script.chmod(0o755)
            target_inputs.append(
                {
                    "opportunity": opportunity,
                    "bridge_script": bridge_script,
                    "runtime_kernel_evidence_path": slot_dir / "kernel_evidence.json",
                    "runtime_offload_provenance_path": slot_dir / "provenance.json",
                    "accelerated_output_json_path": slot_dir / "accelerated_output.json",
                    "accelerated_input_json_path": slot_dir / "accelerated_input.json",
                    "accelerated_input_data_path": slot_dir / "accelerated_input.dat",
                    "accelerated_output_data_path": slot_dir / "accelerated_output.dat",
                }
            )
    if missing_opportunities:
        blockers.extend(
            f"bundle_unknown_opportunity_id:{item}" for item in missing_opportunities
        )
    if target_inputs:
        manifest_payload = _install_bundle_runtime_env(
            env,
            bridge_dir=out_dir,
            bundle_id=str(bundle_id),
            targets=target_inputs,
            runtime_mode="planned_single_qe_workflow_bundle_preflight",
        )
    else:
        blockers.append("bundle_runtime_manifest_not_built")

    # The manifest/env plan is necessary but intentionally insufficient.  These
    # blockers stay until a real QE run proves multiple callsites consumed their
    # accelerated outputs in one QE process.
    blockers.extend(
        [
            "fortran_per_kernel_env_alias_consumption_not_verified",
            "multi_target_bridge_scripts_are_preflight_placeholders",
            "single_qe_workflow_runtime_execution_not_run",
            "non_smoke_bundle_actual_compute_not_run",
            "bundle_level_value_requires_real_qe_gem5_evidence",
        ]
    )
    blockers = list(dict.fromkeys(blockers))
    planned_multi_target = bool(
        manifest_payload
        and manifest_payload.get("manifest", {}).get(
            "planned_single_qe_workflow_multi_callsite_bundle"
        )
        is True
    )
    report = {
        "schema_version": "dse.qe_bundle_single_workflow_runner_preflight.v1",
        "status": "blocked_preflight_only",
        "bundle_id": str(bundle_id),
        "bundle_known": bundle is not None,
        "opportunity_ids": opportunity_ids,
        "target_count": len(target_inputs),
        "planned_single_qe_workflow_multi_callsite_bundle": planned_multi_target,
        "single_qe_workflow_proven": False,
        "single_qe_workflow_bundle_attempt_executed": False,
        "bundle_level_valuable_l4": False,
        "bundle_value_allowed": False,
        "non_smoke_actual_compute": False,
        "runtime_env_keys": sorted(env),
        "runtime_manifest_path": manifest_payload.get("manifest_path") if manifest_payload else None,
        "runtime_manifest": manifest_payload.get("manifest") if manifest_payload else None,
        "blockers": blockers,
        "deliverable_complete": False,
        "claim_boundary": (
            "preflight prepares multi-target runtime slots only; bundle-level "
            "value requires a real non-smoke QE/gem5 single-workflow run with "
            "per-target accelerated replacement consumption"
        ),
    }
    _write_json(out_dir / "bundle_single_workflow_runner_preflight_report.json", report)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--bundle-id", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_space = _load_json(args.artifact_root / "offload_bundle_search_space.json")
    opportunity_manifest = _load_json(args.artifact_root / "offload_opportunity_manifest.json")
    args.out.mkdir(parents=True, exist_ok=True)
    report = build_bundle_single_workflow_runner_preflight(
        bundle_space=bundle_space,
        opportunity_manifest=opportunity_manifest,
        bundle_id=args.bundle_id,
        out_dir=args.out,
    )
    status = {
        "schema_version": "dse.qe_bundle_single_workflow_runner_preflight_status.v1",
        "status": report.get("status"),
        "report_path": str(args.out / "bundle_single_workflow_runner_preflight_report.json"),
        "bundle_id": args.bundle_id,
        "target_count": report.get("target_count", 0),
        "planned_single_qe_workflow_multi_callsite_bundle": report.get(
            "planned_single_qe_workflow_multi_callsite_bundle", False
        ),
        "single_qe_workflow_proven": False,
        "bundle_level_valuable_l4": False,
        "bundle_value_allowed": False,
        "deliverable_complete": False,
        "blockers": report.get("blockers", []),
        "claim_boundary": report.get("claim_boundary"),
    }
    _write_json(args.out / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
