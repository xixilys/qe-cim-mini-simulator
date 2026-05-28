#!/usr/bin/env python3
"""Fail-closed FPGA/ASIC winner-resolution gate for DFT/QE hardware DSE.

This layer consumes the candidate-stamped hardware PPA ranking and decides
whether the current evidence is strong enough to name a best FPGA deployment and
best ASIC deployment.  It intentionally rejects deterministic candidate-id tie
ordering as proof: a winner exists only when the deployment-specific PPA ranking
has exactly one rank-1 design identity backed by non-conflicting hard-gate
metrics.  Multiple rank-1 evaluation rows may collapse only when they share the
same authoritative ``design_candidate_id``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_candidate_specific_ppa_provenance import (
    validate_dft_candidate_specific_ppa_provenance_audit,
)
from dse_v2.reference_workloads.dft_hardware_ppa_ranking import (
    validate_dft_hardware_ppa_ranking,
)


DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA = "dse.dft.architecture_winner_resolution.v1"
DFT_ARCHITECTURE_WINNER_RESOLUTION_VALIDATION_SCHEMA = (
    "dse.dft.architecture_winner_resolution_validation.v1"
)
DFT_ARCHITECTURE_WINNER_RESOLUTION_STATUS_SCHEMA = (
    "dse.dft.architecture_winner_resolution_status.v1"
)

_CLAIM_BOUNDARY = (
    "Architecture winner resolution may identify deployment-specific FPGA/ASIC "
    "hardware-PPA winners only when candidate-stamped hard-gate metrics break "
    "ties across distinct design identities.  Duplicate top-rank evaluation "
    "rows may collapse only when they share one design_candidate_id and have "
    "non-conflicting deployment metrics; tied distinct designs or conflicting "
    "duplicate-design metrics remain blockers.  This artifact does not mark "
    "full-SCF deliverable completion; the separate goal/release claim gate "
    "still owns final completion."
)

_DEPLOYMENTS = ("fpga", "asic")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _as_rows(value: Any) -> list[Dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _rank_one_rows(rows: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [dict(row) for row in rows if row.get("rank") == 1]


def _design_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the architecture identity used for winner resolution.

    ``candidate_id`` rows may be evaluation records rather than unique designs.
    The winner-resolution layer therefore collapses duplicate top-rank
    evaluation rows by authoritative ``design_candidate_id`` when available, and
    falls back to ``candidate_id`` only when the upstream ranking has no design
    identity to preserve legacy fixtures.
    """

    design_candidate_id = row.get("design_candidate_id")
    if design_candidate_id not in (None, ""):
        return str(design_candidate_id), "design_candidate_id"
    candidate_id = row.get("candidate_id")
    if candidate_id not in (None, ""):
        return str(candidate_id), "candidate_id_fallback"
    return "", "missing_design_identity"


def _deployment_metrics(deployment: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    if deployment == "fpga":
        return {
            "fpga_total_slice_luts": row.get("fpga_total_slice_luts"),
            "fpga_total_dsps": row.get("fpga_total_dsps"),
            "fpga_total_block_ram_tiles": row.get("fpga_total_block_ram_tiles"),
            "fpga_total_bonded_iob": row.get("fpga_total_bonded_iob"),
            "vivado_route_completed_kernel_count": row.get("vivado_route_completed_kernel_count"),
            "kernel_count": row.get("kernel_count"),
        }
    return {
        "asic_total_cell_area": row.get("asic_total_cell_area"),
        "asic_min_slack_ns": row.get("asic_min_slack_ns"),
        "asic_slack_deficit_ns": row.get("asic_slack_deficit_ns"),
        "dc_real_target_library_kernel_count": row.get("dc_real_target_library_kernel_count"),
        "kernel_count": row.get("kernel_count"),
    }


def _metric_signature(deployment: str, row: Mapping[str, Any]) -> str:
    return json.dumps(_deployment_metrics(deployment, row), sort_keys=True)


def _top_rank_design_groups(
    deployment: str,
    top_rows: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for row in top_rows:
        row_dict = dict(row)
        design_identity, identity_kind = _design_identity(row_dict)
        if not design_identity:
            design_identity = f"<missing>:{row_dict.get('candidate_id') or len(groups)}"
        group = groups.setdefault(
            design_identity,
            {
                "design_identity": design_identity,
                "identity_kind": identity_kind,
                "design_candidate_id": row_dict.get("design_candidate_id"),
                "top_rank_candidate_ids": [],
                "top_rank_rows": [],
                "metric_signatures": set(),
            },
        )
        group["top_rank_candidate_ids"].append(str(row_dict.get("candidate_id")))
        group["top_rank_rows"].append(row_dict)
        group["metric_signatures"].add(_metric_signature(deployment, row_dict))

    normalized: list[Dict[str, Any]] = []
    for group in groups.values():
        rows = sorted(
            group["top_rank_rows"],
            key=lambda item: (
                str(item.get("design_candidate_id") or ""),
                str(item.get("candidate_id") or ""),
            ),
        )
        normalized.append(
            {
                "design_identity": group["design_identity"],
                "identity_kind": group["identity_kind"],
                "design_candidate_id": group.get("design_candidate_id"),
                "representative_row": rows[0],
                "top_rank_candidate_ids": sorted(set(group["top_rank_candidate_ids"])),
                "top_rank_evaluation_record_count": len(rows),
                "metric_signature_count": len(group["metric_signatures"]),
                "metric_signatures": sorted(group["metric_signatures"]),
                "collapsed_duplicate_evaluation_rows": len(rows) > 1,
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            str(item.get("design_candidate_id") or item.get("design_identity") or ""),
            str(item.get("top_rank_candidate_ids", [""])[0]),
        ),
    )


def _winner_summary(
    deployment: str,
    row: Mapping[str, Any],
    *,
    design_group: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    design_group = design_group if isinstance(design_group, Mapping) else {}
    return {
        "deployment": deployment,
        "candidate_id": row.get("candidate_id"),
        "representative_candidate_id": row.get("candidate_id"),
        "design_candidate_id": row.get("design_candidate_id"),
        "design_identity": design_group.get("design_identity") or _design_identity(row)[0],
        "design_identity_kind": design_group.get("identity_kind") or _design_identity(row)[1],
        "top_rank_candidate_ids": list(design_group.get("top_rank_candidate_ids", []))
        if design_group
        else [str(row.get("candidate_id"))],
        "top_rank_evaluation_record_count": design_group.get("top_rank_evaluation_record_count", 1),
        "collapsed_duplicate_evaluation_rows": bool(
            design_group.get("collapsed_duplicate_evaluation_rows", False)
        ),
        "identity_assignments": dict(row.get("identity_assignments", {}) if isinstance(row.get("identity_assignments", {}), Mapping) else {}),
        "non_identity_assignments": dict(row.get("non_identity_assignments", {}) if isinstance(row.get("non_identity_assignments", {}), Mapping) else {}),
        "rank": row.get("rank"),
        "tie_key": row.get("tie_key"),
        "metrics": _deployment_metrics(deployment, row),
        "evidence_ids": [
            "dft_hardware_ppa_ranking.json",
            "dft_hardware_ppa_ranking_validation.json",
            "dft_hardware_closure_release_gate.json",
            "dft_hardware_closure_gate_adjudication.json",
            "dft_hardware_closure_parser_run.json",
        ],
        "claim_boundary": (
            "Deployment-specific hardware-PPA winner candidate only; not a "
            "full-SCF deliverable-complete winner by itself."
        ),
    }


def _required_next_evidence(
    *,
    deployment: str,
    top_rows: Sequence[Mapping[str, Any]],
    reason: str,
) -> list[Dict[str, Any]]:
    candidate_ids = [str(row.get("candidate_id")) for row in top_rows if row.get("candidate_id")]
    if not candidate_ids:
        candidate_ids = ["<all_release_candidates>"]
    deployment_specific_artifacts = (
        [
            "candidate-specific Vivado utilization/timing/power reports after synth/implementation/route",
            "Vivado command transcript and tool-version record for each candidate/kernel row",
        ]
        if deployment == "fpga"
        else [
            "candidate-specific DC area/timing/slack reports using a real target library",
            "DC command transcript, target-library discovery record, and tool-version record for each candidate/kernel row",
        ]
    )
    return [
        {
            "task_id": f"{deployment}_candidate_specific_ppa_tie_breaker",
            "deployment": deployment,
            "candidate_ids": candidate_ids,
            "reason": reason,
            "required_artifacts": [
                "candidate-specific golden correctness for every claimed major kernel",
                "candidate-specific HLS C-sim or RTL sim transcript/result",
                "candidate-specific HLS C-synth or RTL synth report",
                *deployment_specific_artifacts,
                "full-SCF evaluated-hybrid cost/schedule row using these candidate-specific kernel metrics",
            ],
            "required_artifact_paths": [
                "dft_hardware_closure_gate_adjudication.json",
                "dft_hardware_ppa_ranking.json",
                "dft_hardware_ppa_pareto_frontier.json",
                "dft_candidate_specific_ppa_provenance_audit.json",
                "dft_candidate_specific_ppa_provenance_audit_validation.json",
                "dft_hardware_tie_breaker_execution_queue.json",
                "dft_candidate_specific_ppa_execution.json",
                "dft_architecture_winner_resolution.json",
            ],
            "acceptance_checks": [
                "all major-kernel golden/sim/synth hard gates pass for every tied candidate",
                "every PPA row is parsed from candidate-specific fresh command outputs",
                "candidate_specific_ppa_provenance.winner_provenance_eligible is true",
                f"{deployment} ranking has exactly one rank-1 candidate",
                "rank-1 metric signature is not shared by another candidate",
                "full-SCF evaluated-hybrid accounting exists for the winning candidate and keeps host-bound costs included",
            ],
            "forbidden_shortcuts": [
                "candidate-id deterministic tie order",
                "shared route_probe/source-flow evidence reused as candidate winner proof",
                "Step2 design_score or low-fidelity score as final PPA tie-breaker",
                "single-candidate full-SCF accounting bundle used as cross-candidate winner proof",
            ],
        }
    ]


def _validation_summary(
    *,
    schema_version: str,
    companion_validation: Mapping[str, Any],
    recomputed_validation: Mapping[str, Any],
    claim_boundary: str,
) -> Dict[str, Any]:
    companion_errors = companion_validation.get("errors", [])
    recomputed_errors = recomputed_validation.get("errors", [])
    return {
        "schema_version": schema_version,
        "companion_valid": companion_validation.get("valid") is True,
        "recomputed_valid": recomputed_validation.get("valid") is True,
        "valid": companion_validation.get("valid") is True
        and recomputed_validation.get("valid") is True,
        "companion_errors": list(companion_errors) if isinstance(companion_errors, list) else [],
        "recomputed_errors": list(recomputed_errors) if isinstance(recomputed_errors, list) else [],
        "claim_boundary": claim_boundary,
    }


def _deployment_resolution(
    deployment: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    ppa: Mapping[str, Any],
    winner_source_eligible: bool,
    source_blocker_ids: Sequence[str] = (),
) -> Dict[str, Any]:
    rows = [dict(row) for row in rows]
    top_rows = _rank_one_rows(rows)
    top_candidate_ids = [str(row.get("candidate_id")) for row in top_rows if row.get("candidate_id")]
    top_design_groups = _top_rank_design_groups(deployment, top_rows)
    top_design_count = len(top_design_groups)
    top_design_ids = [
        str(group.get("design_candidate_id") or group.get("design_identity"))
        for group in top_design_groups
        if group.get("design_identity")
    ]
    duplicate_top_rank_evaluation_rows_collapsed = bool(
        top_rows and len(top_rows) > top_design_count and top_design_count == 1
    )
    blockers: list[Dict[str, Any]] = []
    winner: Dict[str, Any] | None = None

    if ppa.get("hardware_completion_eligible") is not True:
        blockers.append({"blocker_id": "ppa_ranking_not_hardware_completion_eligible"})
    if not rows:
        blockers.append({"blocker_id": "no_deployment_ranking_rows"})
    if not top_rows:
        blockers.append({"blocker_id": "no_rank_one_candidate"})
    if any(int(group.get("metric_signature_count", 0) or 0) > 1 for group in top_design_groups):
        blockers.append(
            {
                "blocker_id": "duplicate_design_top_rank_metric_conflict",
                "top_rank_design_ids": top_design_ids,
            }
        )
    if top_design_count > 1:
        blockers.append(
            {
                "blocker_id": "deployment_top_rank_tied",
                "top_rank_candidate_count": len(top_rows),
                "top_rank_candidate_ids": top_candidate_ids,
                "top_rank_design_count": top_design_count,
                "top_rank_design_ids": top_design_ids,
            }
        )
    if ppa.get("all_candidates_metric_tied") is True and not duplicate_top_rank_evaluation_rows_collapsed:
        blockers.append(
            {
                "blocker_id": "all_candidates_metric_tied",
                "metric_signature_count": ppa.get("metric_signature_count"),
                "top_rank_design_count": top_design_count,
            }
        )
    if (
        str(ppa.get("winner_selection_status", "")).startswith("tied_")
        and not duplicate_top_rank_evaluation_rows_collapsed
    ):
        blockers.append(
            {
                "blocker_id": "ppa_winner_selection_status_tied",
                "winner_selection_status": ppa.get("winner_selection_status"),
                "top_rank_design_count": top_design_count,
            }
        )
    if winner_source_eligible is not True:
        blockers.append(
            {
                "blocker_id": "winner_source_evidence_not_trusted",
                "source_blocker_ids": list(source_blocker_ids),
            }
        )

    if not blockers and top_design_count == 1:
        group = top_design_groups[0]
        winner = _winner_summary(
            deployment,
            group["representative_row"],
            design_group=group,
        )

    status = "resolved_unique_hardware_ppa_winner" if winner else "blocked_no_unique_hardware_ppa_winner"
    reason = blockers[0]["blocker_id"] if blockers else "resolved"
    return {
        "schema_version": "dse.dft.architecture_winner_resolution.deployment.v1",
        "deployment": deployment,
        "status": status,
        "resolved": winner is not None,
        "winner": winner,
        "top_rank_candidate_count": len(top_rows),
        "top_rank_candidate_ids": top_candidate_ids,
        "top_rank_design_count": top_design_count,
        "top_rank_design_ids": top_design_ids,
        "top_rank_design_groups": [
            {
                key: value
                for key, value in group.items()
                if key not in {"representative_row", "metric_signatures"}
            }
            for group in top_design_groups
        ],
        "duplicate_top_rank_evaluation_rows_collapsed": duplicate_top_rank_evaluation_rows_collapsed,
        "winner_resolution_basis": (
            "design_candidate_id_duplicate_evaluation_rows_collapsed"
            if duplicate_top_rank_evaluation_rows_collapsed
            else "single_top_rank_design_candidate"
            if winner
            else "blocked"
        ),
        "ranking_row_count": len(rows),
        "ranking_design_count": len(
            {
                _design_identity(row)[0]
                for row in rows
                if _design_identity(row)[0]
            }
        ),
        "blockers": blockers,
        "required_next_evidence": []
        if winner is not None
        else _required_next_evidence(deployment=deployment, top_rows=top_rows, reason=reason),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _full_scf_tie_breaker_record(run_dir: Path) -> Dict[str, Any]:
    bundle_dir = run_dir / "full_scf_hybrid_bundle"
    descriptor = _load_json(bundle_dir / "full_scf_accelerator_descriptor.json")
    ppa_summary = _load_json(bundle_dir / "full_scf_ppa_summary.json")
    refs = {
        name: _source_ref(bundle_dir / name, required=False)
        for name in (
            "full_scf_accelerator_descriptor.json",
            "full_scf_runtime_schedule.json",
            "full_scf_data_residency_plan.json",
            "full_scf_correctness_report.json",
            "full_scf_ppa_summary.json",
        )
    }
    present = any(ref.get("exists") for ref in refs.values())
    comparable_candidate_count = 1 if descriptor.get("candidate_id") else 0
    return {
        "present": present,
        "candidate_id": descriptor.get("candidate_id"),
        "prototype_boundary": descriptor.get("prototype_boundary"),
        "device_residency": descriptor.get("device_residency"),
        "baseline_scf_time_s": ppa_summary.get("baseline_scf_time_s"),
        "accelerated_scf_time_s": ppa_summary.get("accelerated_scf_time_s"),
        "comparable_candidate_count": comparable_candidate_count,
        "can_break_cross_candidate_ties": False,
        "status": (
            "single_candidate_accounting_not_comparative_tie_breaker"
            if present
            else "not_present"
        ),
        "artifact_refs": refs,
        "claim_boundary": (
            "The current full-SCF evaluated-hybrid bundle is useful accounting "
            "evidence for its candidate, but it is not a cross-candidate "
            "tie-breaker unless equivalent bundles exist for every tied candidate."
        ),
    }


def build_dft_architecture_winner_resolution(run_dir: Path) -> Dict[str, Any]:
    """Build the fail-closed FPGA/ASIC winner-resolution payload."""

    run_dir = Path(run_dir)
    ppa_path = run_dir / "dft_hardware_ppa_ranking.json"
    ppa_validation_path = run_dir / "dft_hardware_ppa_ranking_validation.json"
    ppa_status_path = run_dir / "dft_hardware_ppa_ranking_status.json"
    provenance_path = run_dir / "dft_candidate_specific_ppa_provenance_audit.json"
    provenance_validation_path = run_dir / "dft_candidate_specific_ppa_provenance_audit_validation.json"
    tie_breaker_queue_path = run_dir / "dft_hardware_tie_breaker_execution_queue.json"
    ppa = _load_json(ppa_path)
    ppa_validation = _load_json(ppa_validation_path)
    ppa_recomputed_validation = validate_dft_hardware_ppa_ranking(ppa)
    ppa_validation_summary = _validation_summary(
        schema_version="dse.dft.architecture_winner_resolution.ppa_validation_summary.v1",
        companion_validation=ppa_validation,
        recomputed_validation=ppa_recomputed_validation,
        claim_boundary=(
            "Winner resolution requires both the sidecar validation and a fresh "
            "in-process validation of dft_hardware_ppa_ranking.json before "
            "naming deployment winners."
        ),
    )
    provenance = _load_json(provenance_path)
    provenance_validation = _load_json(provenance_validation_path)
    provenance_recomputed_validation = validate_dft_candidate_specific_ppa_provenance_audit(
        provenance
    )
    provenance_validation_summary = _validation_summary(
        schema_version=(
            "dse.dft.architecture_winner_resolution."
            "candidate_specific_provenance_validation_summary.v1"
        ),
        companion_validation=provenance_validation,
        recomputed_validation=provenance_recomputed_validation,
        claim_boundary=(
            "Winner resolution requires both the sidecar validation and a fresh "
            "in-process validation of dft_candidate_specific_ppa_provenance_audit.json "
            "before trusting candidate-specific PPA provenance."
        ),
    )
    tie_breaker_queue = _load_json(tie_breaker_queue_path)
    source_artifacts = {
        "dft_hardware_ppa_ranking": _source_ref(ppa_path),
        "dft_hardware_ppa_ranking_validation": _source_ref(ppa_validation_path),
        "dft_hardware_ppa_ranking_status": _source_ref(ppa_status_path, required=False),
        "dft_candidate_specific_ppa_provenance_audit": _source_ref(provenance_path),
        "dft_candidate_specific_ppa_provenance_audit_validation": _source_ref(provenance_validation_path),
        "dft_hardware_tie_breaker_execution_queue": _source_ref(tie_breaker_queue_path, required=False),
    }
    blockers: list[Dict[str, Any]] = []
    if not ppa:
        blockers.append({"blocker_id": "missing_dft_hardware_ppa_ranking"})
    if ppa_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "dft_hardware_ppa_ranking_validation_not_valid",
                "valid": ppa_validation.get("valid"),
            }
        )
    if ppa_recomputed_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "dft_hardware_ppa_ranking_recomputed_validation_not_valid",
                "valid": ppa_recomputed_validation.get("valid"),
                "errors": ppa_recomputed_validation.get("errors", []),
            }
        )
    if not provenance:
        blockers.append({"blocker_id": "missing_candidate_specific_ppa_provenance_audit"})
    if provenance_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "candidate_specific_ppa_provenance_validation_not_valid",
                "valid": provenance_validation.get("valid"),
            }
        )
    if provenance_recomputed_validation.get("valid") is not True:
        blockers.append(
            {
                "blocker_id": "candidate_specific_ppa_provenance_recomputed_validation_not_valid",
                "valid": provenance_recomputed_validation.get("valid"),
                "errors": provenance_recomputed_validation.get("errors", []),
            }
        )
    if provenance and provenance.get("winner_provenance_eligible") is not True:
        blockers.append(
            {
                "blocker_id": "candidate_specific_ppa_provenance_not_trusted",
                "provenance_status": provenance.get("status"),
                "blocked_unit_count": provenance.get("blocked_unit_count"),
                "blocker_count": provenance.get("blocker_count"),
            }
        )

    source_blocker_ids = [
        str(blocker.get("blocker_id"))
        for blocker in blockers
    ]
    winner_source_eligible = not source_blocker_ids
    deployments = {
        "fpga": _deployment_resolution(
            "fpga",
            _as_rows(ppa.get("fpga_ranking", [])),
            ppa=ppa,
            winner_source_eligible=winner_source_eligible,
            source_blocker_ids=source_blocker_ids,
        ),
        "asic": _deployment_resolution(
            "asic",
            _as_rows(ppa.get("asic_ranking", [])),
            ppa=ppa,
            winner_source_eligible=winner_source_eligible,
            source_blocker_ids=source_blocker_ids,
        ),
    }
    duplicate_metric_tie_collapsed_to_unique_design = bool(
        ppa.get("all_candidates_metric_tied") is True
        and all(
            item.get("duplicate_top_rank_evaluation_rows_collapsed") is True
            for item in deployments.values()
        )
    )
    deployment_duplicate_top_rank_evaluation_rows_collapsed = {
        deployment: bool(item.get("duplicate_top_rank_evaluation_rows_collapsed"))
        for deployment, item in deployments.items()
    }
    for deployment, resolution in deployments.items():
        if resolution.get("resolved") is not True:
            blockers.append(
                {
                    "blocker_id": f"{deployment}_winner_not_resolved",
                    "deployment_status": resolution.get("status"),
                    "top_rank_candidate_count": resolution.get("top_rank_candidate_count"),
                }
            )

    hardware_winner_resolution_eligible = not blockers and all(
        item.get("resolved") is True for item in deployments.values()
    )
    status = (
        "resolved_hardware_ppa_deployment_winners"
        if hardware_winner_resolution_eligible
        else "blocked_no_unique_hardware_ppa_winners"
    )
    return {
        "schema_version": DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": source_artifacts,
        "release_id": ppa.get("release_id"),
        "candidate_count": ppa.get("candidate_count"),
        "ranking_eligible_candidate_count": ppa.get("ranking_eligible_candidate_count"),
        "ranking_eligible_design_candidate_count": max(
            int(deployments["fpga"].get("ranking_design_count", 0) or 0),
            int(deployments["asic"].get("ranking_design_count", 0) or 0),
        ),
        "hardware_completion_eligible": bool(ppa.get("hardware_completion_eligible", False)),
        "candidate_specific_ppa_provenance": {
            "present": bool(provenance),
            "status": provenance.get("status"),
            "validation_valid": provenance_validation_summary.get("valid"),
            "winner_provenance_eligible": bool(provenance.get("winner_provenance_eligible", False)),
            "unit_count": provenance.get("unit_count"),
            "blocked_unit_count": provenance.get("blocked_unit_count"),
            "blocker_count": provenance.get("blocker_count"),
            "blocker_id_counts": provenance.get("blocker_id_counts", {}),
            "tie_breaker_work_item_count": tie_breaker_queue.get("work_item_count"),
        },
        "candidate_specific_ppa_provenance_validation": provenance_validation_summary,
        "dft_hardware_ppa_ranking_validation": ppa_validation_summary,
        "ppa_winner_selection_status": ppa.get("winner_selection_status"),
        "all_candidates_metric_tied": bool(ppa.get("all_candidates_metric_tied", False)),
        "duplicate_metric_tie_collapsed_to_unique_design": duplicate_metric_tie_collapsed_to_unique_design,
        "top_rank_duplicate_evaluation_rows_collapsed": any(
            deployment_duplicate_top_rank_evaluation_rows_collapsed.values()
        ),
        "deployment_duplicate_top_rank_evaluation_rows_collapsed": (
            deployment_duplicate_top_rank_evaluation_rows_collapsed
        ),
        "metric_signature_count": ppa.get("metric_signature_count"),
        "deployments": deployments,
        "fpga_best_architecture": deployments["fpga"].get("winner")
        if hardware_winner_resolution_eligible
        else None,
        "asic_best_architecture": deployments["asic"].get("winner")
        if hardware_winner_resolution_eligible
        else None,
        "full_scf_tie_breaker": _full_scf_tie_breaker_record(run_dir),
        "blockers": blockers,
        "blocker_count": len(blockers),
        "hardware_winner_resolution_eligible": hardware_winner_resolution_eligible,
        "trusted_best_architecture_claim_eligible": False,
        "deliverable_complete": False,
        "completion_claim": "blocked" if blockers else "hardware_winners_resolved_pending_release_claim_gate",
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_architecture_winner_resolution(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate winner-resolution consistency without promoting claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("winner_resolution_must_not_mark_deliverable_complete")
    deployments = payload.get("deployments", {})
    if not isinstance(deployments, Mapping):
        errors.append("deployments_missing_or_not_mapping")
        deployments = {}
    for deployment in _DEPLOYMENTS:
        item = deployments.get(deployment, {}) if isinstance(deployments, Mapping) else {}
        if not isinstance(item, Mapping):
            errors.append(f"{deployment}_resolution_not_mapping")
            continue
        resolved = item.get("resolved") is True
        winner = item.get("winner")
        top_count = int(item.get("top_rank_candidate_count", 0) or 0)
        top_design_count = int(item.get("top_rank_design_count", top_count) or 0)
        if resolved and top_design_count != 1:
            errors.append(f"{deployment}_resolved_without_single_top_design")
        if (
            resolved
            and top_count != 1
            and item.get("duplicate_top_rank_evaluation_rows_collapsed") is not True
        ):
            errors.append(f"{deployment}_resolved_without_single_top_candidate_or_design_collapse")
        if resolved and not isinstance(winner, Mapping):
            errors.append(f"{deployment}_resolved_without_winner")
        if not resolved and not item.get("required_next_evidence"):
            errors.append(f"{deployment}_blocked_without_required_next_evidence")
        if item.get("status") == "resolved_unique_hardware_ppa_winner" and not resolved:
            errors.append(f"{deployment}_resolved_status_without_resolved_true")
    eligible = payload.get("hardware_winner_resolution_eligible") is True
    status = str(payload.get("status") or "")
    blockers = payload.get("blockers", [])
    if not isinstance(blockers, list):
        errors.append("blockers_not_list")
        blockers = []
    blocker_count = int(payload.get("blocker_count", 0) or 0)
    if blocker_count != len(blockers):
        errors.append("blocker_count_mismatch")
    if status == "resolved_hardware_ppa_deployment_winners" and not eligible:
        errors.append("resolved_status_without_hardware_winner_resolution_eligible")
    if eligible and status != "resolved_hardware_ppa_deployment_winners":
        errors.append("eligible_without_resolved_status")
    if eligible and blockers:
        errors.append("eligible_with_blockers")
    if eligible and any(
        not isinstance(deployments.get(deployment, {}), Mapping)
        or deployments.get(deployment, {}).get("resolved") is not True
        for deployment in _DEPLOYMENTS
    ):
        errors.append("eligible_without_both_deployments_resolved")
    if (
        payload.get("all_candidates_metric_tied") is True
        and eligible
        and payload.get("duplicate_metric_tie_collapsed_to_unique_design") is not True
    ):
        errors.append("eligible_while_all_candidates_metric_tied")
    if payload.get("trusted_best_architecture_claim_eligible") is True:
        errors.append("trusted_best_architecture_claim_must_remain_false_in_resolution_layer")
    return {
        "schema_version": DFT_ARCHITECTURE_WINNER_RESOLUTION_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_architecture_winner_resolution(run_dir: Path) -> Dict[str, Any]:
    """Write winner-resolution, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    resolution = build_dft_architecture_winner_resolution(run_dir)
    validation = validate_dft_architecture_winner_resolution(resolution)
    write_json(run_dir / "dft_architecture_winner_resolution.json", resolution)
    write_json(run_dir / "dft_architecture_winner_resolution_validation.json", validation)
    status = {
        "schema_version": DFT_ARCHITECTURE_WINNER_RESOLUTION_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "winner_resolution_status": resolution.get("status"),
        "fpga_status": resolution.get("deployments", {}).get("fpga", {}).get("status"),
        "asic_status": resolution.get("deployments", {}).get("asic", {}).get("status"),
        "fpga_top_rank_candidate_count": resolution.get("deployments", {}).get("fpga", {}).get("top_rank_candidate_count"),
        "asic_top_rank_candidate_count": resolution.get("deployments", {}).get("asic", {}).get("top_rank_candidate_count"),
        "fpga_top_rank_design_count": resolution.get("deployments", {}).get("fpga", {}).get("top_rank_design_count"),
        "asic_top_rank_design_count": resolution.get("deployments", {}).get("asic", {}).get("top_rank_design_count"),
        "duplicate_metric_tie_collapsed_to_unique_design": resolution.get(
            "duplicate_metric_tie_collapsed_to_unique_design"
        ),
        "top_rank_duplicate_evaluation_rows_collapsed": resolution.get(
            "top_rank_duplicate_evaluation_rows_collapsed"
        ),
        "hardware_winner_resolution_eligible": resolution.get("hardware_winner_resolution_eligible"),
        "trusted_best_architecture_claim_eligible": resolution.get("trusted_best_architecture_claim_eligible"),
        "deliverable_complete": False,
        "blocker_count": resolution.get("blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_architecture_winner_resolution_status.json", status)
    return {
        "schema_version": "dse.dft.architecture_winner_resolution_artifact_status.v1",
        "status": status["status"],
        "winner_resolution": str(run_dir / "dft_architecture_winner_resolution.json"),
        "winner_resolution_validation": str(run_dir / "dft_architecture_winner_resolution_validation.json"),
        "winner_resolution_status": str(run_dir / "dft_architecture_winner_resolution_status.json"),
        "hardware_winner_resolution_eligible": resolution.get("hardware_winner_resolution_eligible"),
        "blocker_count": resolution.get("blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_ARCHITECTURE_WINNER_RESOLUTION_SCHEMA",
    "DFT_ARCHITECTURE_WINNER_RESOLUTION_STATUS_SCHEMA",
    "DFT_ARCHITECTURE_WINNER_RESOLUTION_VALIDATION_SCHEMA",
    "build_dft_architecture_winner_resolution",
    "validate_dft_architecture_winner_resolution",
    "write_dft_architecture_winner_resolution",
]
