#!/usr/bin/env python3
"""Three-lane coordination summary for DFT deployment decisions.

This artifact joins the framework/search-control-plane lane with the FPGA and
ASIC evidence lanes.  It does not invent evidence or upgrade completion claims:
the summary is only "fully coordinated" when search-loop evidence is closed and
the already-generated FPGA/ASIC deployment summaries are valid.  Release/full
SCF completion remains owned by the separate goal-completion audit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.complete_dse_search_space import (
    DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
    build_release_cardinality_budget,
)
from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA = "dse.dft.deployment_coordination_summary.v1"
DFT_DEPLOYMENT_COORDINATION_VALIDATION_SCHEMA = (
    "dse.dft.deployment_coordination_summary_validation.v1"
)
DFT_DEPLOYMENT_COORDINATION_STATUS_SCHEMA = "dse.dft.deployment_coordination_summary_status.v1"

_CLAIM_BOUNDARY = (
    "Coordination summary combines search-control-plane closure with current "
    "FPGA/ASIC deployment winners and work ownership. It is a handoff and "
    "decision-support artifact only; it does not create new PPA, gem5/L4, QE, "
    "or full-SCF completion evidence."
)

_CANDIDATE_ADMISSION_CLAIM_BOUNDARY = (
    "Candidate admission audit checks whether the current deployment winners "
    "are visible in the DFT search-to-release binding map. It is framework "
    "provenance only; it does not create new hardware evidence, make heuristic "
    "bindings authoritative for design, or prove release completion."
)

_COMPLETE_DSE_LEDGER_SCHEMA = "dse.codesign.complete_dse.release_candidate_trial_ledger.v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return {}
    path = Path(path)
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path | None, *, required: bool = True) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "required": required,
            "exists": False,
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _first_existing_path(paths: tuple[Path, ...]) -> Path:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return paths[0]


def _nonclaiming_hash_bound_ref(
    path: Path | None,
    *,
    artifact_role: str,
    required: bool = True,
) -> Dict[str, Any]:
    ref = _source_ref(path, required=required)
    ref["artifact_role"] = artifact_role
    ref["claim_upgrade_allowed"] = False
    return ref


def _payload_claim_upgrade_blockers(
    *,
    artifact_name: str,
    payload: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if payload.get("deliverable_complete") is True:
        blockers.append({
            "blocker_id": "artifact_claims_deliverable_complete",
            "artifact": artifact_name,
        })
    if payload.get("trusted_final_claim") is True:
        blockers.append({
            "blocker_id": "artifact_claims_trusted_final_result",
            "artifact": artifact_name,
        })
    if payload.get("release_completion_eligible") is True:
        blockers.append({
            "blocker_id": "artifact_claims_release_completion",
            "artifact": artifact_name,
        })
    if payload.get("execution_allowed") is True:
        blockers.append({
            "blocker_id": "artifact_allows_execution",
            "artifact": artifact_name,
        })
    return blockers


def _release_universe_materialization_refs(run_dir: Path) -> Dict[str, Any]:
    """Expose concrete release/materialization refs without upgrading claims."""

    release_universe_manifest_path = _first_existing_path((
        run_dir / "release_universe_manifest.json",
        run_dir / "search_space" / "release_subset_manifest.json",
    ))
    matrix_path = _first_existing_path((
        run_dir / "candidate_workflow_deployment_target_matrix.json",
        run_dir / "search_space" / "candidate_workflow_deployment_target_matrix.json",
    ))
    materialization_coverage_path = _first_existing_path((
        run_dir / "materialization_coverage_audit.json",
        run_dir / "campaign_materialization_coverage_audit.json",
    ))
    refs = {
        "release_universe_manifest": _nonclaiming_hash_bound_ref(
            release_universe_manifest_path,
            artifact_role="release_universe_manifest",
        ),
        "candidate_workflow_deployment_target_matrix": _nonclaiming_hash_bound_ref(
            matrix_path,
            artifact_role="candidate_workflow_deployment_target_matrix",
        ),
        "materialization_coverage_audit": _nonclaiming_hash_bound_ref(
            materialization_coverage_path,
            artifact_role="materialization_coverage_audit",
        ),
    }
    payloads = {
        name: _load_json(Path(ref["path"])) if ref.get("exists") is True and ref.get("path") else {}
        for name, ref in refs.items()
    }
    blockers: list[Dict[str, Any]] = []
    for name, ref in refs.items():
        if ref.get("exists") is not True:
            blockers.append({
                "blocker_id": "hash_bound_ref_missing",
                "artifact": name,
                "path": ref.get("path"),
            })
        if not ref.get("sha256"):
            blockers.append({
                "blocker_id": "hash_bound_ref_missing_sha256",
                "artifact": name,
                "path": ref.get("path"),
            })
        blockers.extend(_payload_claim_upgrade_blockers(artifact_name=name, payload=payloads[name]))
    refs_ready = not blockers
    return {
        "schema_version": "dse.dft.release_universe_materialization_refs.v1",
        "status": "hash_bound_refs_ready" if refs_ready else "partial_blocked_not_complete",
        "release_universe_manifest": refs["release_universe_manifest"],
        "candidate_workflow_deployment_target_matrix": refs[
            "candidate_workflow_deployment_target_matrix"
        ],
        "materialization_coverage_audit": refs["materialization_coverage_audit"],
        "hash_bound_ref_count": sum(1 for ref in refs.values() if ref.get("sha256")),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_upgrade_allowed": False,
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Release-universe/materialization refs are replay provenance only. "
            "They may replace blocked placeholders when present and hash-bound, "
            "but they do not create QE, FPGA, ASIC, or global completion evidence."
        ),
    }


def _source_freshness_errors(
    source_artifacts: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[str]:
    """Return validation errors when recorded upstream hashes are stale."""

    errors: list[str] = []
    for key in keys:
        ref = source_artifacts.get(key)
        if not isinstance(ref, Mapping):
            continue
        path_text = str(ref.get("path") or "")
        if ref.get("exists") is not True or not path_text:
            continue
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            errors.append(f"source_artifact_current_path_missing:{key}")
            continue
        expected_sha = str(ref.get("sha256") or "")
        actual_sha = sha256_file(path)
        if not expected_sha:
            errors.append(f"source_artifact_missing_recorded_sha256:{key}")
        elif actual_sha != expected_sha:
            errors.append(f"stale_source_artifact:{key}")
    return errors


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _deployment_recommendation(
    deployment: str,
    summary: Mapping[str, Any],
    *,
    target_feasibility: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    item = _as_mapping(summary.get(deployment))
    metrics = _as_mapping(item.get("metrics"))
    device_summary = _as_mapping(item.get("device_summary"))
    target_evidence = _as_mapping(device_summary.get("kernel_row_target_evidence"))
    target_feasibility = _as_mapping(target_feasibility)
    fpga_feasibility = _as_mapping(target_feasibility.get("fpga_target_feasibility"))
    asic_binding = _as_mapping(target_feasibility.get("asic_target_binding"))
    blockers: list[Dict[str, Any]] = []
    if item.get("resolved") is not True:
        blockers.append({"blocker_id": f"{deployment}_winner_not_resolved"})
    device_status = str(item.get("device_selection_status") or "")
    selected_device = device_summary.get("selected_device")
    target_feasibility_status = None
    if deployment == "fpga" and fpga_feasibility:
        # Raw package feasibility is diagnostic only.  It can show that a
        # published part has enough nominal capacity for the current winner, but
        # it is not per-kernel Vivado target/part consensus and must not bind the
        # deployment target or clear the physical-target blocker.
        target_feasibility_status = fpga_feasibility.get("status")
        if fpga_feasibility.get("deployment_target_claim_eligible") is True:
            blockers.append({
                "blocker_id": "fpga_raw_target_feasibility_overclaimed_deployment_target",
                "target_selection_class": fpga_feasibility.get("target_selection_class"),
            })
        if fpga_feasibility.get("can_clear_physical_target_blocker") is True:
            blockers.append({
                "blocker_id": "fpga_raw_target_feasibility_attempted_to_clear_physical_target_blocker",
                "target_selection_class": fpga_feasibility.get("target_selection_class"),
            })
    elif deployment == "asic" and asic_binding.get("target_binding_claim_eligible") is True:
        selected_device = asic_binding.get("selected_target_library")
        target_feasibility_status = asic_binding.get("status")
    if device_status in {"", "not_explicitly_proven"}:
        blockers.append(
            {
                "blocker_id": f"{deployment}_physical_target_not_explicitly_proven",
                "device_selection_status": device_status or "missing",
            }
        )
    elif device_status.startswith("blocked"):
        blockers.append(
            {
                "blocker_id": f"{deployment}_physical_target_blocked",
                "device_selection_status": device_status,
            }
        )
    return {
        "deployment": deployment,
        "status": "recommended_with_bound_target" if not blockers else "recommended_with_open_target_blockers",
        "winner_resolved": item.get("resolved") is True,
        "best_candidate_id": item.get("best_candidate_id"),
        "best_design_candidate_id": item.get("best_design_candidate_id"),
        "equivalent_top_candidate_ids": list(item.get("equivalent_top_candidate_ids", []) or []),
        "device_selection_status": device_status or "missing",
        "selected_device": selected_device,
        "target_feasibility_status": target_feasibility_status,
        "fpga_target_selection_class": (
            fpga_feasibility.get("target_selection_class") if deployment == "fpga" else None
        ),
        "fpga_selected_part": fpga_feasibility.get("selected_part") if deployment == "fpga" else None,
        "fpga_selected_package": fpga_feasibility.get("selected_package") if deployment == "fpga" else None,
        "fpga_resource_fit": bool(fpga_feasibility.get("resource_fit", False)) if deployment == "fpga" else None,
        "fpga_deployment_target_claim_eligible": (
            bool(fpga_feasibility.get("deployment_target_claim_eligible", False))
            if deployment == "fpga"
            else None
        ),
        "fpga_can_clear_physical_target_blocker": (
            bool(fpga_feasibility.get("can_clear_physical_target_blocker", False))
            if deployment == "fpga"
            else None
        ),
        "fpga_claim_aware_next_gate": (
            fpga_feasibility.get("claim_aware_next_gate") if deployment == "fpga" else None
        ),
        "asic_target_binding_claim_eligible": (
            bool(asic_binding.get("target_binding_claim_eligible", False))
            if deployment == "asic"
            else None
        ),
        "metrics": metrics,
        "target_evidence_status": target_evidence.get("status"),
        "targeted_kernel_count": target_evidence.get("targeted_kernel_count"),
        "expected_kernel_count": target_evidence.get("expected_kernel_count"),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": item.get("claim_boundary") or _CLAIM_BOUNDARY,
    }


def _search_lane(search_loop_summary: Mapping[str, Any]) -> Dict[str, Any]:
    closed = search_loop_summary.get("control_plane_search_effectiveness_closed") is True
    latest_gate = search_loop_summary.get("latest_effectiveness_gate_passed") is True
    dft_template_binding_seen = search_loop_summary.get("dft_template_binding_report_seen") is True
    dft_template_binding_gate = search_loop_summary.get("latest_dft_template_binding_gate_passed")
    dft_template_binding_status = search_loop_summary.get("latest_dft_template_binding_status")
    blockers = list(search_loop_summary.get("latest_effectiveness_blockers", []) or [])
    if not closed:
        blockers.append({"blocker_id": "control_plane_search_effectiveness_not_closed"})
    if not latest_gate:
        blockers.append({"blocker_id": "latest_search_effectiveness_gate_not_passed"})
    if not dft_template_binding_seen:
        blockers.append({
            "blocker_id": "dft_template_binding_report_missing_for_dft_primary_proof",
            "claim_boundary": (
                "The DFT primary proof path requires the framework/search lane "
                "to show a passed DFT-template binding report before current "
                "FPGA/ASIC evidence can be coordinated as search-admitted work."
            ),
        })
    if dft_template_binding_seen and dft_template_binding_gate is not True:
        blockers.append({
            "blocker_id": "dft_template_binding_gate_not_passed",
            "dft_template_binding_status": dft_template_binding_status,
        })
    return {
        "lane_id": "dse_framework_search_control_plane",
        "owner_process": "codex_process_framework",
        "status": (
            "closed_for_current_coordination"
            if closed and latest_gate and dft_template_binding_seen and dft_template_binding_gate is True
            else "incomplete"
        ),
        "control_plane_search_effectiveness_closed": closed,
        "latest_effectiveness_gate_passed": latest_gate,
        "dft_template_binding_report_seen": dft_template_binding_seen,
        "latest_dft_template_binding_gate_passed": dft_template_binding_gate,
        "latest_dft_template_binding_status": dft_template_binding_status,
        "latest_dft_template_binding_report_ref": search_loop_summary.get(
            "latest_dft_template_binding_report_ref"
        ),
        "latest_dft_template_bound_candidate_count": search_loop_summary.get(
            "latest_dft_template_bound_candidate_count"
        ),
        "latest_dft_template_blocked_candidate_count": search_loop_summary.get(
            "latest_dft_template_blocked_candidate_count"
        ),
        "completed_rounds": search_loop_summary.get("completed_rounds"),
        "total_executed_count": search_loop_summary.get("total_executed_count"),
        "latest_search_effectiveness_audit_ref": search_loop_summary.get(
            "latest_search_effectiveness_audit_ref"
        ),
        "responsibilities": [
            "own Campaign/SearchPolicy/Trial-ledger contracts",
            "prove candidate identity progression and replay safety before evidence fanout",
            "bind profile/template search rows to real Step2 selectors before Campaign materialization",
            "consume FPGA/ASIC evidence as feedback without manufacturing evidence",
        ],
        "blocker_count": len(blockers),
        "blockers": blockers,
    }


def _process_lanes(
    *,
    search_lane: Mapping[str, Any],
    fpga: Mapping[str, Any],
    asic: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    fpga_blockers = list(fpga.get("blockers", []) or [])
    asic_blockers = list(asic.get("blockers", []) or [])
    return [
        dict(search_lane),
        {
            "lane_id": "fpga_evidence_and_deployment",
            "owner_process": "codex_process_fpga_evidence",
            "status": "open_target_binding" if fpga_blockers else "evidence_bound",
            "responsibilities": [
                "keep Vivado FPGA claims separate from ASIC/DC claims",
                "bind the selected FPGA architecture to a concrete part only from per-kernel tool evidence",
                "produce any missing FPGA target/device consensus evidence for all major kernels",
                "return candidate-specific PPA rows to the framework lane",
            ],
            "current_best_candidate_id": fpga.get("best_candidate_id"),
            "current_best_design_candidate_id": fpga.get("best_design_candidate_id"),
            "device_selection_status": fpga.get("device_selection_status"),
            "blocker_count": len(fpga_blockers),
            "blockers": fpga_blockers,
        },
        {
            "lane_id": "asic_evidence_and_release_accounting",
            "owner_process": "codex_process_asic_evidence",
            "status": "evidence_bound" if not asic_blockers else "open_target_binding",
            "responsibilities": [
                "keep DC/ASIC target-library evidence separate from FPGA/Vivado claims",
                "maintain per-kernel DC timing/area target-library consensus",
                "feed ASIC winner and blocker status into final report and goal audit",
                "coordinate with QE/full-SCF accounting before any release-complete claim",
            ],
            "current_best_candidate_id": asic.get("best_candidate_id"),
            "current_best_design_candidate_id": asic.get("best_design_candidate_id"),
            "device_selection_status": asic.get("device_selection_status"),
            "blocker_count": len(asic_blockers),
            "blockers": asic_blockers,
        },
    ]


def _binding_row_identity_set(row: Mapping[str, Any]) -> set[str]:
    identities: set[str] = set()
    for key in (
        "release_candidate_id",
        "evaluation_record_id",
        "legacy_candidate_id",
        "candidate_id",
        "design_candidate_id",
        "search_candidate_id",
    ):
        value = str(row.get(key) or "")
        if value:
            identities.add(value)
    return identities


def _deployment_winner_identity_set(item: Mapping[str, Any]) -> set[str]:
    identities: set[str] = set()
    for key in ("best_candidate_id", "best_design_candidate_id", "selected_device"):
        value = str(item.get(key) or "")
        if value:
            identities.add(value)
    for value in item.get("equivalent_top_candidate_ids", []) or []:
        value = str(value or "")
        if value:
            identities.add(value)
    return identities


def _candidate_binding_row_index(candidate_binding_map: Mapping[str, Any]) -> dict[str, list[Dict[str, Any]]]:
    index: dict[str, list[Dict[str, Any]]] = {}
    for row in candidate_binding_map.get("binding_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        row_payload = dict(row)
        for identity in _binding_row_identity_set(row_payload):
            index.setdefault(identity, []).append(row_payload)
    return index


def _candidate_binding_release_admission_state(
    candidate_binding_map: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return fail-closed release-universe admission state from the binding map."""

    reconciliation = _as_mapping(candidate_binding_map.get("candidate_universe_reconciliation"))
    closure = reconciliation.get("release_admission_closure")
    if closure is None:
        closure = candidate_binding_map.get("release_admission_closure")
    claim_eligible = reconciliation.get("release_admission_claim_eligible")
    if claim_eligible is None:
        claim_eligible = candidate_binding_map.get("release_admission_claim_eligible")
    status = (
        reconciliation.get("candidate_admission_status")
        or candidate_binding_map.get("candidate_admission_status")
        or candidate_binding_map.get("candidate_admission_status")
    )
    release_only_ids = (
        reconciliation.get("release_only_admission_candidate_ids")
        if isinstance(reconciliation.get("release_only_admission_candidate_ids"), list)
        else candidate_binding_map.get("release_only_admission_candidate_ids", [])
    )
    return {
        "candidate_admission_status": status,
        "release_admission_closure": closure is True,
        "release_admission_closure_present": closure is not None,
        "release_admission_claim_eligible": claim_eligible is True,
        "release_admission_claim_eligible_present": claim_eligible is not None,
        "release_only_admission_candidate_count": (
            reconciliation.get("release_only_admission_candidate_count")
            if reconciliation.get("release_only_admission_candidate_count") is not None
            else candidate_binding_map.get("release_only_admission_candidate_count")
        ),
        "release_only_admission_candidate_ids": [
            str(item)
            for item in (release_only_ids or [])
            if str(item)
        ],
        "search_covers_full_release_universe": (
            reconciliation.get("search_covers_full_release_universe")
            if reconciliation.get("search_covers_full_release_universe") is not None
            else candidate_binding_map.get("search_covers_full_release_universe")
        ),
        "candidate_set_scope": (
            reconciliation.get("candidate_set_scope")
            or candidate_binding_map.get("candidate_set_scope")
        ),
    }


def _candidate_admission_audit(
    *,
    fpga: Mapping[str, Any],
    asic: Mapping[str, Any],
    candidate_binding_map: Mapping[str, Any],
    candidate_binding_validation: Mapping[str, Any],
    candidate_binding_map_path: Path,
    candidate_binding_validation_path: Path,
) -> Dict[str, Any]:
    """Audit whether current deployment winners are search/release bound."""

    source_present = bool(candidate_binding_map)
    validation_present = bool(candidate_binding_validation)
    validation_valid = candidate_binding_validation.get("valid") is True if validation_present else False
    row_index = _candidate_binding_row_index(candidate_binding_map)
    release_admission_state = (
        _candidate_binding_release_admission_state(candidate_binding_map)
        if source_present
        else {
            "candidate_admission_status": "missing",
            "release_admission_closure": False,
            "release_admission_closure_present": False,
            "release_admission_claim_eligible": False,
            "release_admission_claim_eligible_present": False,
            "release_only_admission_candidate_count": None,
            "release_only_admission_candidate_ids": [],
            "search_covers_full_release_universe": None,
            "candidate_set_scope": None,
        }
    )
    deployments: Dict[str, Any] = {}
    blockers: list[Dict[str, Any]] = []

    for deployment, item in (("fpga", fpga), ("asic", asic)):
        identities = _deployment_winner_identity_set(item)
        matching_rows: list[Dict[str, Any]] = []
        seen_row_keys: set[tuple[str, str, str]] = set()
        for identity in identities:
            for row in row_index.get(identity, []):
                row_key = (
                    str(row.get("search_candidate_id") or ""),
                    str(row.get("release_candidate_id") or ""),
                    str(row.get("design_candidate_id") or ""),
                )
                if row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
                matching_rows.append({
                    "search_candidate_id": row.get("search_candidate_id"),
                    "release_candidate_id": row.get("release_candidate_id"),
                    "evaluation_record_id": row.get("evaluation_record_id"),
                    "legacy_candidate_id": row.get("legacy_candidate_id"),
                    "design_candidate_id": row.get("design_candidate_id"),
                    "binding_status": row.get("binding_status"),
                    "template_family": row.get("template_family"),
                    "confidence": row.get("confidence"),
                    "candidate_id_authoritative_for_design": row.get(
                        "candidate_id_authoritative_for_design"
                    ),
                })
        deployment_blockers: list[Dict[str, Any]] = []
        if not source_present:
            deployment_blockers.append({
                "blocker_id": "candidate_binding_map_missing_for_winner_search_admission",
                "deployment": deployment,
            })
        elif not validation_valid:
            deployment_blockers.append({
                "blocker_id": "candidate_binding_map_validation_not_valid",
                "deployment": deployment,
                "validation_present": validation_present,
            })
        elif not matching_rows:
            deployment_blockers.append({
                "blocker_id": "deployment_winner_not_bound_to_search_candidate",
                "deployment": deployment,
                "winner_identities": sorted(identities),
                "detail": (
                    "The current deployment winner does not appear in the "
                    "candidate binding map by release/evaluation/legacy/design "
                    "candidate identity."
                ),
            })
        deployments[deployment] = {
            "deployment": deployment,
            "best_candidate_id": item.get("best_candidate_id"),
            "best_design_candidate_id": item.get("best_design_candidate_id"),
            "equivalent_top_candidate_ids": list(item.get("equivalent_top_candidate_ids", []) or []),
            "winner_identities": sorted(identities),
            "binding_status": "winner_bound_to_search_candidate" if matching_rows and not deployment_blockers else "blocked",
            "matched_binding_row_count": len(matching_rows),
            "matched_binding_rows": matching_rows,
            "blocker_count": len(deployment_blockers),
            "blockers": deployment_blockers,
        }
        blockers.extend(deployment_blockers)

    if source_present and validation_valid and release_admission_state["release_admission_closure"] is not True:
        blockers.append({
            "blocker_id": "candidate_binding_release_admission_not_closed",
            "candidate_admission_status": release_admission_state.get("candidate_admission_status"),
            "candidate_set_scope": release_admission_state.get("candidate_set_scope"),
            "search_covers_full_release_universe": release_admission_state.get(
                "search_covers_full_release_universe"
            ),
            "release_admission_closure_present": release_admission_state.get(
                "release_admission_closure_present"
            ),
            "release_only_admission_candidate_count": release_admission_state.get(
                "release_only_admission_candidate_count"
            ),
            "release_only_admission_candidate_ids": release_admission_state.get(
                "release_only_admission_candidate_ids"
            ),
            "detail": (
                "The binding map has not closed the full release-admission "
                "universe. Current winners may be visible in search rows, but "
                "deployment claims remain blocked until the SearchPolicy set, "
                "release universe, and admission rows reconcile."
            ),
        })
    if source_present and validation_valid and release_admission_state["release_admission_claim_eligible"] is not True:
        blockers.append({
            "blocker_id": "candidate_binding_release_admission_claim_not_eligible",
            "candidate_admission_status": release_admission_state.get("candidate_admission_status"),
            "release_admission_claim_eligible_present": release_admission_state.get(
                "release_admission_claim_eligible_present"
            ),
            "release_only_admission_candidate_count": release_admission_state.get(
                "release_only_admission_candidate_count"
            ),
            "detail": (
                "The binding map does not authorize release-admission claims. "
                "Deployment coordination must stay fail-closed even when the "
                "current FPGA/ASIC winners have matching binding rows."
            ),
        })

    status = "passed" if source_present and validation_valid and not blockers else "blocked"
    return {
        "schema_version": "dse.dft.deployment_candidate_admission_audit.v1",
        "status": status,
        "required_for_dft_primary_proof": True,
        "candidate_binding_map_ref": _source_ref(candidate_binding_map_path, required=True),
        "candidate_binding_map_validation_ref": _source_ref(candidate_binding_validation_path, required=True),
        "candidate_binding_map_status": candidate_binding_map.get("status") if source_present else "missing",
        "candidate_binding_map_validation_valid": validation_valid,
        "search_candidate_count": candidate_binding_map.get("search_candidate_count") if source_present else None,
        "legal_release_candidate_count": (
            candidate_binding_map.get("legal_release_candidate_count") if source_present else None
        ),
        "bound_candidate_count": candidate_binding_map.get("bound_candidate_count") if source_present else None,
        "unique_release_candidate_count": (
            candidate_binding_map.get("unique_release_candidate_count") if source_present else None
        ),
        "release_admission_candidate_count": (
            candidate_binding_map.get("release_admission_candidate_count") if source_present else None
        ),
        "release_only_admission_candidate_count": (
            candidate_binding_map.get("release_only_admission_candidate_count") if source_present else None
        ),
        "candidate_admission_status": release_admission_state.get("candidate_admission_status"),
        "candidate_set_scope": release_admission_state.get("candidate_set_scope"),
        "search_covers_full_release_universe": release_admission_state.get(
            "search_covers_full_release_universe"
        ),
        "release_admission_closure": release_admission_state.get("release_admission_closure"),
        "release_admission_closure_present": release_admission_state.get(
            "release_admission_closure_present"
        ),
        "release_admission_claim_eligible": release_admission_state.get(
            "release_admission_claim_eligible"
        ),
        "release_admission_claim_eligible_present": release_admission_state.get(
            "release_admission_claim_eligible_present"
        ),
        "release_only_admission_candidate_ids": release_admission_state.get(
            "release_only_admission_candidate_ids"
        ),
        "duplicate_release_candidate_ids": list(
            candidate_binding_map.get("duplicate_release_candidate_ids", []) or []
        ) if source_present else [],
        "completion_eligible": candidate_binding_map.get("completion_eligible") if source_present else False,
        "deployments": deployments,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": _CANDIDATE_ADMISSION_CLAIM_BOUNDARY,
    }


def _release_gate_candidate_admission_audit(
    *,
    release_gate: Mapping[str, Any],
    release_gate_path: Path,
) -> Dict[str, Any]:
    """Summarize release-gate candidate admission for deployment coordination.

    The candidate-binding audit above proves only that the current deployment
    winners are visible in the search-to-release binding map.  The release gate
    has the stronger universe-level authority: every hardware evidence
    candidate in the release matrix must exactly match the binding map and the
    trial-state ledger.  Deployment coordination must consume that stronger
    gate so an evidence matrix cannot widen the candidate universe behind
    Search/Campaign/Trial.
    """

    present = bool(release_gate)
    nested = _as_mapping(release_gate.get("candidate_admission_gate")) if present else {}
    gate_passed = (
        release_gate.get("candidate_admission_gate_passed") is True
        or nested.get("candidate_admission_gate_passed") is True
    )
    blockers = list(nested.get("blockers", []) or release_gate.get("candidate_admission_blockers", []) or [])
    binding_release_admission_closure = nested.get("candidate_binding_map_release_admission_closure")
    binding_release_only_count = nested.get("candidate_binding_map_release_only_admission_candidate_count")
    trial_release_only_count = nested.get("trial_state_ledger_release_only_admission_candidate_count")
    if not present:
        blockers.append({
            "blocker_id": "hardware_release_gate_missing_for_candidate_admission",
            "reason": (
                "Deployment coordination requires the hardware release gate so "
                "the evidence candidate universe can be checked against the "
                "Search/Campaign/Trial binding map and trial ledger."
            ),
        })
    elif not gate_passed and not blockers:
        blockers.append({
            "blocker_id": "hardware_release_gate_candidate_admission_not_passed",
            "reason": "Release gate candidate admission did not pass but did not publish blocker details.",
        })
    elif (
        binding_release_admission_closure is False
        or (isinstance(binding_release_only_count, int) and binding_release_only_count > 0)
        or (isinstance(trial_release_only_count, int) and trial_release_only_count > 0)
    ):
        blockers.append({
            "blocker_id": "release_gate_candidate_binding_release_admission_not_closed",
            "candidate_binding_map_candidate_admission_status": nested.get(
                "candidate_binding_map_candidate_admission_status"
            ),
            "candidate_binding_map_release_admission_closure": binding_release_admission_closure,
            "candidate_binding_map_release_only_admission_candidate_count": binding_release_only_count,
            "trial_state_ledger_release_only_admission_candidate_count": trial_release_only_count,
            "reason": (
                "The hardware release gate cannot pass candidate admission while "
                "the binding map or trial ledger still reports release-only "
                "admission candidates outside the SearchPolicy proposal set."
            ),
        })

    return {
        "schema_version": "dse.dft.deployment_release_gate_candidate_admission.v1",
        "status": "passed" if present and gate_passed and not blockers else "blocked",
        "required_for_dft_primary_proof": True,
        "release_gate_ref": _source_ref(release_gate_path, required=True),
        "release_gate_status": release_gate.get("status") if present else "missing",
        "release_gate_result": release_gate.get("release_gate_result") if present else "missing",
        "release_gate_hardware_completion_eligible": (
            release_gate.get("hardware_completion_eligible") is True if present else False
        ),
        "candidate_admission_gate_passed": gate_passed,
        "release_gate_candidate_count": (
            nested.get("release_gate_candidate_count")
            if nested
            else release_gate.get("candidate_count") if present else None
        ),
        "candidate_binding_map_bound_candidate_count": nested.get(
            "candidate_binding_map_bound_candidate_count"
        ),
        "candidate_binding_map_unique_release_candidate_count": nested.get(
            "candidate_binding_map_unique_release_candidate_count"
        ),
        "candidate_binding_map_release_admission_candidate_count": nested.get(
            "candidate_binding_map_release_admission_candidate_count"
        ),
        "candidate_binding_map_release_only_admission_candidate_count": nested.get(
            "candidate_binding_map_release_only_admission_candidate_count"
        ),
        "candidate_binding_map_candidate_admission_status": nested.get(
            "candidate_binding_map_candidate_admission_status"
        ),
        "candidate_binding_map_release_admission_closure": binding_release_admission_closure,
        "trial_state_ledger_candidate_count": nested.get("trial_state_ledger_candidate_count"),
        "trial_state_ledger_release_admission_candidate_count": nested.get(
            "trial_state_ledger_release_admission_candidate_count"
        ),
        "trial_state_ledger_release_only_admission_candidate_count": nested.get(
            "trial_state_ledger_release_only_admission_candidate_count"
        ),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": (
            "Release-gate candidate admission is a universe-level framework gate. "
            "Current deployment winners may remain decision-support, but no "
            "deployment or release claim is eligible unless release-gate "
            "candidate rows exactly match the current binding map and trial ledger."
        ),
    }
def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _matrix_or_report_count(payload: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _as_int(payload.get(key))
        if value is not None:
            return value
    return None


def _complete_dse_release_obligation_audit(
    *,
    release_candidate_trial_ledger: Mapping[str, Any],
    l4_evidence_matrix: Mapping[str, Any],
    coverage_claim_report: Mapping[str, Any],
    complete_l4_report: Mapping[str, Any],
    candidate_binding_map: Mapping[str, Any],
    release_gate: Mapping[str, Any],
    release_candidate_trial_ledger_path: Path,
    l4_evidence_matrix_path: Path,
    coverage_claim_report_path: Path,
    complete_l4_report_path: Path,
) -> Dict[str, Any]:
    """Audit current complete-DSE ledger and 84×6-style L4 row obligation.

    This is deliberately stricter than the local winner-admission audit: the
    latter proves the current FPGA/ASIC winners are visible in search rows, while
    this audit proves those winners are being coordinated against the same finite
    complete-DSE release universe and frozen six-SCF L4 matrix obligation.
    """

    budget = build_release_cardinality_budget()
    target_min = int(budget.get("legal_release_candidates_target_min") or 0)
    workload_count_required = int(DEFAULT_FROZEN_WORKLOAD_CASE_COUNT)
    ledger_present = bool(release_candidate_trial_ledger)
    matrix_present = bool(l4_evidence_matrix)
    coverage_present = bool(coverage_claim_report)
    complete_report_present = bool(complete_l4_report)
    ledger_legal_count = _as_int(release_candidate_trial_ledger.get("legal_candidate_count"))
    ledger_candidate_count = _as_int(release_candidate_trial_ledger.get("candidate_count"))
    ledger_workload_count = _as_int(release_candidate_trial_ledger.get("frozen_workload_case_count"))
    ledger_required_rows = _as_int(
        release_candidate_trial_ledger.get("required_l4_evidence_row_count")
    )
    computed_required_rows = (
        ledger_legal_count * ledger_workload_count
        if ledger_legal_count is not None and ledger_workload_count is not None
        else None
    )
    matrix_expected_rows = _matrix_or_report_count(l4_evidence_matrix, "expected_row_count")
    matrix_row_count = _matrix_or_report_count(l4_evidence_matrix, "row_count")
    coverage_expected_rows = _matrix_or_report_count(coverage_claim_report, "expected_row_count")
    coverage_row_count = _matrix_or_report_count(coverage_claim_report, "row_count")
    report_expected_rows = _matrix_or_report_count(complete_l4_report, "expected_row_count")
    report_row_count = _matrix_or_report_count(complete_l4_report, "row_count")
    release_gate_nested = _as_mapping(release_gate.get("candidate_admission_gate"))
    release_gate_candidate_count = _as_int(
        release_gate_nested.get("release_gate_candidate_count")
        if release_gate_nested
        else release_gate.get("candidate_count")
    )
    binding_unique_count = _as_int(candidate_binding_map.get("unique_release_candidate_count"))
    binding_legal_count = _as_int(candidate_binding_map.get("legal_release_candidate_count"))
    binding_admission_count = _as_int(candidate_binding_map.get("release_admission_candidate_count"))

    blockers: list[Dict[str, Any]] = []
    if not ledger_present:
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_missing",
            "path": str(release_candidate_trial_ledger_path),
        })
    elif release_candidate_trial_ledger.get("schema_version") != _COMPLETE_DSE_LEDGER_SCHEMA:
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_wrong_schema",
            "schema_version": release_candidate_trial_ledger.get("schema_version"),
        })
    if ledger_present and release_candidate_trial_ledger.get("status") != "passed":
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_not_passed",
            "status": release_candidate_trial_ledger.get("status"),
            "ledger_blockers": release_candidate_trial_ledger.get("blockers", []),
        })
    if ledger_legal_count is None or ledger_legal_count < target_min:
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_below_release_target_min",
            "ledger_legal_candidate_count": ledger_legal_count,
            "target_min": target_min,
        })
    if ledger_candidate_count is not None and ledger_legal_count is not None:
        if ledger_candidate_count != ledger_legal_count:
            blockers.append({
                "blocker_id": "release_candidate_trial_ledger_contains_nonlegal_or_missing_candidate_rows",
                "candidate_count": ledger_candidate_count,
                "legal_candidate_count": ledger_legal_count,
            })
    if ledger_workload_count != workload_count_required:
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_workload_count_not_strict_six_scf",
            "ledger_frozen_workload_case_count": ledger_workload_count,
            "required_frozen_workload_case_count": workload_count_required,
        })
    if ledger_required_rows is None or computed_required_rows is None or ledger_required_rows != computed_required_rows:
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_required_row_count_inconsistent",
            "ledger_required_l4_evidence_row_count": ledger_required_rows,
            "computed_required_l4_evidence_row_count": computed_required_rows,
        })
    if ledger_present and (
        release_candidate_trial_ledger.get("trusted_final_claim") is True
        or release_candidate_trial_ledger.get("release_completion_eligible") is True
    ):
        blockers.append({
            "blocker_id": "release_candidate_trial_ledger_overclaims_completion",
            "trusted_final_claim": release_candidate_trial_ledger.get("trusted_final_claim"),
            "release_completion_eligible": release_candidate_trial_ledger.get("release_completion_eligible"),
        })
    if not matrix_present:
        blockers.append({
            "blocker_id": "l4_evidence_matrix_missing_for_complete_dse_obligation",
            "path": str(l4_evidence_matrix_path),
        })
    if not coverage_present:
        blockers.append({
            "blocker_id": "coverage_claim_report_missing_for_complete_dse_obligation",
            "path": str(coverage_claim_report_path),
        })
    for label, expected, row_count in (
        ("l4_evidence_matrix", matrix_expected_rows, matrix_row_count),
        ("coverage_claim_report", coverage_expected_rows, coverage_row_count),
        ("complete_dse_full_l4_evidence_report", report_expected_rows, report_row_count),
    ):
        if label == "complete_dse_full_l4_evidence_report" and not complete_report_present:
            continue
        if ledger_required_rows is not None and expected != ledger_required_rows:
            blockers.append({
                "blocker_id": f"{label}_expected_row_count_mismatch",
                "expected_row_count": expected,
                "ledger_required_l4_evidence_row_count": ledger_required_rows,
            })
        if ledger_required_rows is not None and row_count != ledger_required_rows:
            blockers.append({
                "blocker_id": f"{label}_row_count_mismatch",
                "row_count": row_count,
                "ledger_required_l4_evidence_row_count": ledger_required_rows,
            })
    if coverage_present and coverage_claim_report.get("all_rows_present") is not True:
        blockers.append({
            "blocker_id": "coverage_claim_report_not_all_rows_present",
            "all_rows_present": coverage_claim_report.get("all_rows_present"),
        })
    if ledger_legal_count is not None:
        for label, value in (
            ("candidate_binding_map_unique_release_candidate_count", binding_unique_count),
            ("candidate_binding_map_legal_release_candidate_count", binding_legal_count),
            ("candidate_binding_map_release_admission_candidate_count", binding_admission_count),
            ("hardware_release_gate_candidate_count", release_gate_candidate_count),
        ):
            if value is not None and value != ledger_legal_count:
                blockers.append({
                    "blocker_id": f"{label}_does_not_match_release_candidate_trial_ledger",
                    "reported_count": value,
                    "ledger_legal_candidate_count": ledger_legal_count,
                })

    return {
        "schema_version": "dse.dft.deployment_complete_dse_release_obligation_audit.v1",
        "status": "passed" if not blockers else "blocked",
        "required_for_dft_primary_proof": True,
        "release_candidate_trial_ledger_ref": _source_ref(
            release_candidate_trial_ledger_path,
            required=True,
        ),
        "l4_evidence_matrix_ref": _source_ref(l4_evidence_matrix_path, required=True),
        "coverage_claim_report_ref": _source_ref(coverage_claim_report_path, required=True),
        "complete_dse_full_l4_evidence_report_ref": _source_ref(
            complete_l4_report_path,
            required=False,
        ),
        "target_min_legal_candidate_count": target_min,
        "ledger_candidate_count": ledger_candidate_count,
        "ledger_legal_candidate_count": ledger_legal_count,
        "ledger_frozen_workload_case_count": ledger_workload_count,
        "ledger_required_l4_evidence_row_count": ledger_required_rows,
        "computed_required_l4_evidence_row_count": computed_required_rows,
        "matrix_expected_row_count": matrix_expected_rows,
        "matrix_row_count": matrix_row_count,
        "coverage_expected_row_count": coverage_expected_rows,
        "coverage_row_count": coverage_row_count,
        "coverage_all_rows_present": coverage_claim_report.get("all_rows_present") if coverage_present else False,
        "coverage_blocked_row_count": coverage_claim_report.get("blocked_row_count") if coverage_present else None,
        "complete_l4_report_expected_row_count": report_expected_rows,
        "complete_l4_report_row_count": report_row_count,
        "candidate_binding_map_unique_release_candidate_count": binding_unique_count,
        "candidate_binding_map_legal_release_candidate_count": binding_legal_count,
        "candidate_binding_map_release_admission_candidate_count": binding_admission_count,
        "hardware_release_gate_candidate_count": release_gate_candidate_count,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": (
            "Complete-DSE release obligation audit only proves that deployment "
            "coordination is using the current finite release candidate universe "
            "and strict six-SCF L4 row ledger. Rows may still be blocked; this "
            "audit does not prove speedup, correctness, or final completion."
        ),
    }


def build_dft_deployment_coordination_summary(
    *,
    run_dir: Path,
    search_loop_summary_path: Path | None = None,
) -> Dict[str, Any]:
    """Build a combined coordination summary from current authoritative artifacts."""

    run_dir = Path(run_dir)
    deployment_path = run_dir / "dft_fpga_asic_deployment_summary.json"
    deployment_validation_path = run_dir / "dft_fpga_asic_deployment_summary_validation.json"
    target_feasibility_path = run_dir / "dft_deployment_target_feasibility.json"
    target_feasibility_validation_path = run_dir / "dft_deployment_target_feasibility_validation.json"
    ppa_ranking_path = run_dir / "dft_hardware_ppa_ranking.json"
    winner_path = run_dir / "dft_architecture_winner_resolution.json"
    goal_audit_path = run_dir / "dft_scf_hardware_goal_completion_audit_current.json"
    candidate_binding_map_path = run_dir / "dft_candidate_binding_map.json"
    candidate_binding_validation_path = run_dir / "dft_candidate_binding_map_validation.json"
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    release_candidate_trial_ledger_path = _first_existing_path((
        run_dir / "release_candidate_trial_ledger.json",
        run_dir / "search_space" / "release_candidate_trial_ledger.json",
    ))
    l4_evidence_matrix_path = run_dir / "l4_evidence_matrix.json"
    coverage_claim_report_path = run_dir / "coverage_claim_report.json"
    complete_l4_report_path = run_dir / "complete_dse_full_l4_evidence_report.json"
    if search_loop_summary_path is None:
        default_search = run_dir / "search_effectiveness_loop_pilot_summary.json"
        search_loop_summary_path = default_search if default_search.exists() else None

    deployment_summary = _load_json(deployment_path)
    deployment_validation = _load_json(deployment_validation_path)
    target_feasibility = _load_json(target_feasibility_path)
    target_feasibility_validation = _load_json(target_feasibility_validation_path)
    ppa_ranking = _load_json(ppa_ranking_path)
    winner_resolution = _load_json(winner_path)
    goal_audit = _load_json(goal_audit_path)
    candidate_binding_map = _load_json(candidate_binding_map_path)
    candidate_binding_validation = _load_json(candidate_binding_validation_path)
    release_gate = _load_json(release_gate_path)
    release_candidate_trial_ledger = _load_json(release_candidate_trial_ledger_path)
    l4_evidence_matrix = _load_json(l4_evidence_matrix_path)
    coverage_claim_report = _load_json(coverage_claim_report_path)
    complete_l4_report = _load_json(complete_l4_report_path)
    search_summary = _load_json(search_loop_summary_path)

    search = _search_lane(search_summary)
    fpga = _deployment_recommendation("fpga", deployment_summary, target_feasibility=target_feasibility)
    asic = _deployment_recommendation("asic", deployment_summary, target_feasibility=target_feasibility)
    candidate_admission = _candidate_admission_audit(
        fpga=fpga,
        asic=asic,
        candidate_binding_map=candidate_binding_map,
        candidate_binding_validation=candidate_binding_validation,
        candidate_binding_map_path=candidate_binding_map_path,
        candidate_binding_validation_path=candidate_binding_validation_path,
    )
    release_gate_candidate_admission = _release_gate_candidate_admission_audit(
        release_gate=release_gate,
        release_gate_path=release_gate_path,
    )
    complete_dse_release_obligation = _complete_dse_release_obligation_audit(
        release_candidate_trial_ledger=release_candidate_trial_ledger,
        l4_evidence_matrix=l4_evidence_matrix,
        coverage_claim_report=coverage_claim_report,
        complete_l4_report=complete_l4_report,
        candidate_binding_map=candidate_binding_map,
        release_gate=release_gate,
        release_candidate_trial_ledger_path=release_candidate_trial_ledger_path,
        l4_evidence_matrix_path=l4_evidence_matrix_path,
        coverage_claim_report_path=coverage_claim_report_path,
        complete_l4_report_path=complete_l4_report_path,
    )
    release_universe_materialization_refs = _release_universe_materialization_refs(run_dir)
    lanes = _process_lanes(search_lane=search, fpga=fpga, asic=asic)

    deployment_valid = deployment_validation.get("valid") is True
    raw_best_deployment_claim_eligible = deployment_summary.get("best_deployment_claim_eligible") is True
    release_gate_candidate_admission_passed = (
        release_gate_candidate_admission.get("candidate_admission_gate_passed") is True
        and release_gate_candidate_admission.get("status") == "passed"
    )
    candidate_admission_passed = candidate_admission.get("status") == "passed"
    complete_dse_release_obligation_passed = complete_dse_release_obligation.get("status") == "passed"
    candidate_admission_claim_eligible = (
        candidate_admission_passed and release_gate_candidate_admission_passed
        and complete_dse_release_obligation_passed
    )
    best_deployment_claim_eligible = bool(
        raw_best_deployment_claim_eligible and candidate_admission_claim_eligible
    )
    current_best_available = bool(
        deployment_valid
        and raw_best_deployment_claim_eligible
        and fpga["winner_resolved"]
        and asic["winner_resolved"]
    )
    target_blockers = list(fpga.get("blockers", []) or []) + list(asic.get("blockers", []) or [])
    coordination_blockers: list[Dict[str, Any]] = []
    if search.get("status") != "closed_for_current_coordination":
        coordination_blockers.append({"blocker_id": "search_lane_not_closed"})
    if not deployment_valid:
        coordination_blockers.append({"blocker_id": "deployment_summary_validation_not_valid"})
    if not best_deployment_claim_eligible:
        coordination_blockers.append({"blocker_id": "best_deployment_claim_not_eligible"})
    coordination_blockers.extend(target_blockers)
    if not candidate_admission_passed:
        coordination_blockers.extend(
            {
                "blocker_id": blocker.get("blocker_id", "candidate_admission_blocked"),
                "deployment": blocker.get("deployment"),
                "detail": blocker.get("detail"),
                "winner_identities": blocker.get("winner_identities"),
                "candidate_admission_status": blocker.get("candidate_admission_status"),
                "candidate_set_scope": blocker.get("candidate_set_scope"),
                "search_covers_full_release_universe": blocker.get(
                    "search_covers_full_release_universe"
                ),
                "release_admission_closure_present": blocker.get(
                    "release_admission_closure_present"
                ),
                "release_only_admission_candidate_count": blocker.get(
                    "release_only_admission_candidate_count"
                ),
                "release_only_admission_candidate_ids": blocker.get(
                    "release_only_admission_candidate_ids"
                ),
                "release_admission_claim_eligible_present": blocker.get(
                    "release_admission_claim_eligible_present"
                ),
            }
            for blocker in candidate_admission.get("blockers", []) or []
            if isinstance(blocker, Mapping)
        )
    if not release_gate_candidate_admission_passed:
        coordination_blockers.append({
            "blocker_id": "release_gate_candidate_admission_not_passed",
            "release_gate_status": release_gate_candidate_admission.get("release_gate_status"),
            "release_gate_result": release_gate_candidate_admission.get("release_gate_result"),
            "release_gate_candidate_count": release_gate_candidate_admission.get(
                "release_gate_candidate_count"
            ),
            "candidate_binding_map_unique_release_candidate_count": (
                release_gate_candidate_admission.get(
                    "candidate_binding_map_unique_release_candidate_count"
                )
            ),
            "candidate_binding_map_release_admission_candidate_count": (
                release_gate_candidate_admission.get(
                    "candidate_binding_map_release_admission_candidate_count"
                )
            ),
            "candidate_binding_map_candidate_admission_status": (
                release_gate_candidate_admission.get(
                    "candidate_binding_map_candidate_admission_status"
                )
            ),
            "candidate_binding_map_release_admission_closure": (
                release_gate_candidate_admission.get(
                    "candidate_binding_map_release_admission_closure"
                )
            ),
            "candidate_binding_map_release_only_admission_candidate_count": (
                release_gate_candidate_admission.get(
                    "candidate_binding_map_release_only_admission_candidate_count"
                )
            ),
            "trial_state_ledger_candidate_count": release_gate_candidate_admission.get(
                "trial_state_ledger_candidate_count"
            ),
            "trial_state_ledger_release_admission_candidate_count": (
                release_gate_candidate_admission.get(
                    "trial_state_ledger_release_admission_candidate_count"
                )
            ),
            "trial_state_ledger_release_only_admission_candidate_count": (
                release_gate_candidate_admission.get(
                    "trial_state_ledger_release_only_admission_candidate_count"
                )
            ),
            "candidate_admission_blocker_count": release_gate_candidate_admission.get(
                "blocker_count"
            ),
            "candidate_admission_blockers": release_gate_candidate_admission.get("blockers", []),
            "claim_boundary": release_gate_candidate_admission.get("claim_boundary"),
        })
    if not complete_dse_release_obligation_passed:
        coordination_blockers.append({
            "blocker_id": "complete_dse_release_obligation_not_satisfied",
            "audit_status": complete_dse_release_obligation.get("status"),
            "ledger_legal_candidate_count": complete_dse_release_obligation.get(
                "ledger_legal_candidate_count"
            ),
            "ledger_frozen_workload_case_count": complete_dse_release_obligation.get(
                "ledger_frozen_workload_case_count"
            ),
            "ledger_required_l4_evidence_row_count": complete_dse_release_obligation.get(
                "ledger_required_l4_evidence_row_count"
            ),
            "matrix_expected_row_count": complete_dse_release_obligation.get(
                "matrix_expected_row_count"
            ),
            "matrix_row_count": complete_dse_release_obligation.get("matrix_row_count"),
            "coverage_all_rows_present": complete_dse_release_obligation.get(
                "coverage_all_rows_present"
            ),
            "blocker_count": complete_dse_release_obligation.get("blocker_count"),
            "blockers": complete_dse_release_obligation.get("blockers", []),
            "claim_boundary": complete_dse_release_obligation.get("claim_boundary"),
        })
    if str(goal_audit.get("status") or "") not in {"complete", "passed", "release_complete"}:
        coordination_blockers.append(
            {
                "blocker_id": "full_goal_audit_not_complete",
                "goal_audit_status": goal_audit.get("status") or "missing",
            }
        )

    return {
        "schema_version": DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA,
        "generated_at": _now_iso(),
        "status": (
            "coordinated_current_best_with_open_release_blockers"
            if current_best_available and search.get("status") == "closed_for_current_coordination"
            else "partial_blocked_not_complete"
        ),
        "run_dir": str(run_dir),
        "source_artifacts": {
            "search_effectiveness_loop_pilot_summary": _source_ref(search_loop_summary_path, required=True),
            "dft_fpga_asic_deployment_summary": _source_ref(deployment_path),
            "dft_fpga_asic_deployment_summary_validation": _source_ref(deployment_validation_path),
            "dft_deployment_target_feasibility": _source_ref(target_feasibility_path, required=False),
            "dft_deployment_target_feasibility_validation": _source_ref(
                target_feasibility_validation_path,
                required=False,
            ),
            "dft_hardware_ppa_ranking": _source_ref(ppa_ranking_path),
            "dft_architecture_winner_resolution": _source_ref(winner_path),
            "dft_scf_hardware_goal_completion_audit_current": _source_ref(goal_audit_path, required=False),
            "dft_candidate_binding_map": _source_ref(candidate_binding_map_path),
            "dft_candidate_binding_map_validation": _source_ref(candidate_binding_validation_path),
            "dft_hardware_closure_release_gate": _source_ref(release_gate_path),
            "release_candidate_trial_ledger": _source_ref(release_candidate_trial_ledger_path),
            "l4_evidence_matrix": _source_ref(l4_evidence_matrix_path),
            "coverage_claim_report": _source_ref(coverage_claim_report_path),
            "complete_dse_full_l4_evidence_report": _source_ref(
                complete_l4_report_path,
                required=False,
            ),
        },
        "search_lane": search,
        "candidate_admission_audit": candidate_admission,
        "release_gate_candidate_admission": release_gate_candidate_admission,
        "complete_dse_release_obligation": complete_dse_release_obligation,
        "release_universe_materialization_refs": release_universe_materialization_refs,
        "process_lanes": lanes,
        "deployment_recommendations": {
            "fpga": fpga,
            "asic": asic,
        },
        "current_best_available": current_best_available,
        "raw_best_deployment_claim_eligible": raw_best_deployment_claim_eligible,
        "best_deployment_claim_eligible": best_deployment_claim_eligible,
        "target_feasibility_ready": bool(
            target_feasibility.get("target_feasibility_ready", False)
            and target_feasibility_validation.get("valid") is True
        ),
        "candidate_admission_claim_eligible": candidate_admission_claim_eligible,
        "release_gate_candidate_admission_gate_passed": release_gate_candidate_admission_passed,
        "complete_dse_release_obligation_passed": complete_dse_release_obligation_passed,
        "release_gate_candidate_admission_blocker_count": release_gate_candidate_admission.get(
            "blocker_count"
        ),
        "release_gate_candidate_admission_blockers": release_gate_candidate_admission.get(
            "blockers",
            [],
        ),
        "hardware_completion_eligible": bool(
            ppa_ranking.get("hardware_completion_eligible") is True
            and candidate_admission_claim_eligible
        ),
        "raw_hardware_completion_eligible": ppa_ranking.get("hardware_completion_eligible") is True,
        "hardware_winner_resolution_eligible": bool(
            winner_resolution.get("hardware_winner_resolution_eligible") is True
            and candidate_admission_claim_eligible
        ),
        "raw_hardware_winner_resolution_eligible": (
            winner_resolution.get("hardware_winner_resolution_eligible") is True
        ),
        "trusted_best_architecture_claim_eligible": bool(
            winner_resolution.get("trusted_best_architecture_claim_eligible") is True
            and candidate_admission_claim_eligible
        ),
        "raw_trusted_best_architecture_claim_eligible": (
            winner_resolution.get("trusted_best_architecture_claim_eligible") is True
        ),
        "deliverable_complete": False,
        "release_completion_eligible": False,
        "goal_audit_status": goal_audit.get("status") or "missing",
        "coordination_blocker_count": len(coordination_blockers),
        "coordination_blockers": coordination_blockers,
        "recommended_next_actions": [
            "FPGA evidence process: attach per-kernel Vivado target/part consensus for the selected FPGA winner, or keep FPGA device unbound.",
            "ASIC evidence process: preserve the DC target-library consensus and feed any updated ASIC rows back through the same ranking/winner-resolution path.",
            "Evidence processes: do not claim release candidates absent from the current binding map and trial ledger; either route them through Search/Campaign admission or exclude them from the current release universe.",
            "Framework process: keep DFT template-binding reports, Campaign materialization coverage, and search replay-safety gates in front of any widened evidence fanout; regenerate this coordination summary after new evidence lands.",
            "All processes: do not mark release/full-SCF completion until goal-completion audit closes with QE/full-SCF, L4/gem5, and claim-boundary evidence.",
        ],
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_coordination_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate coordination summary without relaxing claim boundaries."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("coordination_summary_must_not_mark_deliverable_complete")
    if payload.get("release_completion_eligible") is True:
        errors.append("coordination_summary_must_not_mark_release_completion")
    source_artifacts = _as_mapping(payload.get("source_artifacts"))
    for key in (
        "search_effectiveness_loop_pilot_summary",
        "dft_fpga_asic_deployment_summary",
        "dft_fpga_asic_deployment_summary_validation",
        "dft_hardware_ppa_ranking",
        "dft_architecture_winner_resolution",
        "dft_hardware_closure_release_gate",
        "release_candidate_trial_ledger",
        "l4_evidence_matrix",
        "coverage_claim_report",
    ):
        ref = _as_mapping(source_artifacts.get(key))
        if ref.get("required", True) is True and ref.get("exists") is not True:
            errors.append(f"missing_required_source_artifact:{key}")
    errors.extend(
        _source_freshness_errors(
            source_artifacts,
            keys=(
                "search_effectiveness_loop_pilot_summary",
                "dft_fpga_asic_deployment_summary",
                "dft_fpga_asic_deployment_summary_validation",
                "dft_hardware_ppa_ranking",
                "dft_architecture_winner_resolution",
                "dft_hardware_closure_release_gate",
                "release_candidate_trial_ledger",
                "l4_evidence_matrix",
                "coverage_claim_report",
                "complete_dse_full_l4_evidence_report",
            ),
        )
    )
    release_gate_candidate_admission = _as_mapping(payload.get("release_gate_candidate_admission"))
    release_gate_candidate_admission_passed = (
        release_gate_candidate_admission.get("candidate_admission_gate_passed") is True
        and release_gate_candidate_admission.get("status") == "passed"
    )
    candidate_admission = _as_mapping(payload.get("candidate_admission_audit"))
    candidate_admission_passed = candidate_admission.get("status") == "passed"
    complete_dse_release_obligation = _as_mapping(payload.get("complete_dse_release_obligation"))
    complete_dse_release_obligation_passed = (
        complete_dse_release_obligation.get("status") == "passed"
    )
    if not release_gate_candidate_admission_passed:
        blocker_ids = {
            str(blocker.get("blocker_id") or "")
            for blocker in payload.get("coordination_blockers", []) or []
            if isinstance(blocker, Mapping)
        }
        if "release_gate_candidate_admission_not_passed" not in blocker_ids:
            errors.append("missing_release_gate_candidate_admission_blocker")
    if not candidate_admission_passed:
        blocker_ids = {
            str(blocker.get("blocker_id") or "")
            for blocker in payload.get("coordination_blockers", []) or []
            if isinstance(blocker, Mapping)
        }
        candidate_blocker_ids = {
            str(blocker.get("blocker_id") or "")
            for blocker in candidate_admission.get("blockers", []) or []
            if isinstance(blocker, Mapping)
        }
        if candidate_blocker_ids and not candidate_blocker_ids.intersection(blocker_ids):
            errors.append("missing_candidate_admission_coordination_blocker")
    if not complete_dse_release_obligation_passed:
        blocker_ids = {
            str(blocker.get("blocker_id") or "")
            for blocker in payload.get("coordination_blockers", []) or []
            if isinstance(blocker, Mapping)
        }
        if "complete_dse_release_obligation_not_satisfied" not in blocker_ids:
            errors.append("missing_complete_dse_release_obligation_coordination_blocker")
    if payload.get("best_deployment_claim_eligible") is True and not release_gate_candidate_admission_passed:
        errors.append("best_deployment_claim_must_fail_closed_without_release_gate_admission")
    if payload.get("best_deployment_claim_eligible") is True and not candidate_admission_passed:
        errors.append("best_deployment_claim_must_fail_closed_without_candidate_admission")
    if payload.get("best_deployment_claim_eligible") is True and not complete_dse_release_obligation_passed:
        errors.append("best_deployment_claim_must_fail_closed_without_complete_dse_release_obligation")
    if (
        payload.get("trusted_best_architecture_claim_eligible") is True
        and not release_gate_candidate_admission_passed
    ):
        errors.append("trusted_best_architecture_claim_must_fail_closed_without_release_gate_admission")
    if (
        payload.get("trusted_best_architecture_claim_eligible") is True
        and not candidate_admission_passed
    ):
        errors.append("trusted_best_architecture_claim_must_fail_closed_without_candidate_admission")
    if (
        payload.get("trusted_best_architecture_claim_eligible") is True
        and not complete_dse_release_obligation_passed
    ):
        errors.append("trusted_best_architecture_claim_must_fail_closed_without_complete_dse_release_obligation")
    for deployment in ("fpga", "asic"):
        item = _as_mapping(_as_mapping(payload.get("deployment_recommendations")).get(deployment))
        if item.get("winner_resolved") is not True:
            errors.append(f"{deployment}_winner_not_resolved")
        if not item.get("best_candidate_id"):
            errors.append(f"{deployment}_missing_best_candidate_id")
        if item.get("device_selection_status") in ("", None, "missing"):
            errors.append(f"{deployment}_missing_device_selection_status")
    lanes = payload.get("process_lanes")
    if not isinstance(lanes, list) or len(lanes) != 3:
        errors.append("expected_three_process_lanes")
    return {
        "schema_version": DFT_DEPLOYMENT_COORDINATION_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_coordination_summary(
    *,
    run_dir: Path,
    out_dir: Path | None = None,
    search_loop_summary_path: Path | None = None,
) -> Dict[str, Any]:
    """Write coordination summary, validation, and status artifacts."""

    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir is not None else run_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_dft_deployment_coordination_summary(
        run_dir=run_dir,
        search_loop_summary_path=search_loop_summary_path,
    )
    validation = validate_dft_deployment_coordination_summary(summary)
    summary_path = out_dir / "dft_deployment_coordination_summary.json"
    validation_path = out_dir / "dft_deployment_coordination_summary_validation.json"
    status_path = out_dir / "dft_deployment_coordination_summary_status.json"
    write_json(summary_path, summary)
    write_json(validation_path, validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_COORDINATION_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "coordination_status": summary.get("status"),
        "current_best_available": summary.get("current_best_available"),
        "coordination_blocker_count": summary.get("coordination_blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(status_path, status)
    return {
        "schema_version": "dse.dft.deployment_coordination_summary_artifact_status.v1",
        "status": status["status"],
        "coordination_summary": str(summary_path),
        "coordination_summary_validation": str(validation_path),
        "coordination_summary_status": str(status_path),
        "coordination_status": summary.get("status"),
        "current_best_available": summary.get("current_best_available"),
        "coordination_blocker_count": summary.get("coordination_blocker_count"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_DEPLOYMENT_COORDINATION_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_COORDINATION_SUMMARY_SCHEMA",
    "DFT_DEPLOYMENT_COORDINATION_VALIDATION_SCHEMA",
    "build_dft_deployment_coordination_summary",
    "validate_dft_deployment_coordination_summary",
    "write_dft_deployment_coordination_summary",
]
