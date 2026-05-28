#!/usr/bin/env python3
"""Replayable FPGA/ASIC deployment comparator for DFT/QE hardware DSE.

This artifact is intentionally separate from the fail-closed architecture
winner-resolution gate.  It can report a best physical *set* for a deployment
target (for example a tied FPGA top rank) and a unique ASIC physical winner
without weakening the rule that tied physical metrics are not a unique winner
claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_DEPLOYMENT_COMPARATOR_SCHEMA = "dse.dft.deployment_comparator.v1"
DFT_DEPLOYMENT_COMPARATOR_VALIDATION_SCHEMA = "dse.dft.deployment_comparator_validation.v1"
DFT_DEPLOYMENT_COMPARATOR_STATUS_SCHEMA = "dse.dft.deployment_comparator_status.v1"

_CLAIM_BOUNDARY = (
    "Deployment comparator reports target-scoped hardware-PPA recommendation "
    "sets from candidate-stamped hard-gate evidence.  It does not choose a "
    "unique FPGA winner when physical metrics tie, does not choose a single "
    "cross-target FPGA-vs-ASIC winner without an explicit objective/cost model, "
    "and does not mark full-SCF deliverable completion."
)

_FORBIDDEN_TIE_BREAKERS = [
    "candidate_id_order",
    "step2_design_score",
    "architecture_family_label",
    "candidate_metadata_sidecar",
    "single_candidate_full_scf_bundle",
]


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


def _source_ref_from_optional(path: Path | None, *, required: bool = True) -> Dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "required": required,
            "exists": False,
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    return _source_ref(path, required=required)


def _as_rows(value: Any) -> list[Dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _rank_one_rows(rows: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [dict(row) for row in rows if row.get("rank") == 1]


def _deployment_metrics(target: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    if target == "fpga":
        return {
            "fpga_total_slice_luts": row.get("fpga_total_slice_luts"),
            "fpga_total_slice_registers": row.get("fpga_total_slice_registers"),
            "fpga_total_dsps": row.get("fpga_total_dsps"),
            "fpga_total_block_ram_tiles": row.get("fpga_total_block_ram_tiles"),
            "fpga_total_bonded_iob": row.get("fpga_total_bonded_iob"),
            "fpga_min_wns_ns": row.get("fpga_min_wns_ns"),
            "vivado_route_completed_kernel_count": row.get("vivado_route_completed_kernel_count"),
            "kernel_count": row.get("kernel_count"),
        }
    return {
        "asic_total_cell_area": row.get("asic_total_cell_area"),
        "asic_total_area_um2": row.get("asic_total_area_um2", row.get("asic_total_cell_area")),
        "asic_min_slack_ns": row.get("asic_min_slack_ns"),
        "asic_slack_deficit_ns": row.get("asic_slack_deficit_ns"),
        "dc_real_target_library_kernel_count": row.get("dc_real_target_library_kernel_count"),
        "kernel_count": row.get("kernel_count"),
    }


def _candidate_summary(target: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    release_provenance = row.get("release_universe_provenance", {})
    release_provenance = release_provenance if isinstance(release_provenance, Mapping) else {}
    return {
        "candidate_id": row.get("candidate_id"),
        "design_candidate_id": row.get("design_candidate_id"),
        "target": target,
        "rank": row.get("rank"),
        "tie_key": row.get("tie_key"),
        "identity_assignments": dict(
            row.get("identity_assignments", {})
            if isinstance(row.get("identity_assignments", {}), Mapping)
            else {}
        ),
        "metrics": _deployment_metrics(target, row),
        "required_stage_ids": list(row.get("required_stage_ids", []) or [])
        if isinstance(row.get("required_stage_ids", []), list)
        else [],
        "release_universe_provenance": dict(release_provenance),
        "claim_boundary": (
            "Target-scoped hardware-PPA recommendation candidate only; "
            "not a full-SCF deliverable-complete claim."
        ),
    }


def _candidate_target_kind(candidate: Mapping[str, Any]) -> str:
    identity = candidate.get("identity", {})
    if isinstance(identity, Mapping):
        layers = identity.get("identity_layers", {})
        if isinstance(layers, Mapping):
            target = layers.get("target_platform_parameters", {})
            if isinstance(target, Mapping):
                kind = str(target.get("platform_kind") or "").lower()
                if kind in {"fpga", "asic"}:
                    return kind
    for source_key in ("identity_assignments", "assignments"):
        source = candidate.get(source_key, {})
        if isinstance(source, Mapping):
            for key in ("hardware_target", "target", "platform_kind", "deployment"):
                kind = str(source.get(key) or "").lower()
                if kind in {"fpga", "asic"}:
                    return kind
    return ""


def _candidate_release_provenance(
    candidate: Mapping[str, Any],
    *,
    release_subset: Mapping[str, Any],
    manifest_path: Path | None,
) -> Dict[str, Any]:
    identity = candidate.get("identity", {})
    layers = identity.get("identity_layers", {}) if isinstance(identity, Mapping) else {}
    layers = layers if isinstance(layers, Mapping) else {}
    deployment = layers.get("deployment_boundary_parameters", {})
    target = layers.get("target_platform_parameters", {})
    generation_provenance = release_subset.get("generation_provenance", {})
    generation_provenance = generation_provenance if isinstance(generation_provenance, Mapping) else {}
    return {
        "source_artifact": str(manifest_path) if manifest_path else None,
        "release_id": release_subset.get("release_id"),
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "generation_source": generation_provenance.get("source"),
        "search_policy_provenance": {
            "generation_source": generation_provenance.get("source"),
            "generation_mode": generation_provenance.get("generation_mode"),
            "pruning_rationale_hash": generation_provenance.get("pruning_rationale_hash"),
            "legality_constraints_hash": generation_provenance.get("legality_constraints_hash"),
            "matrix_contract_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_contract_hash"
            ),
            "matrix_rows_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_rows_hash"
            ),
            "matrix_validation_hash": generation_provenance.get(
                "candidate_workflow_deployment_target_matrix_validation_hash"
            ),
            "candidate_order": list(generation_provenance.get("candidate_order", []) or []),
            "parameter_profile_ids": list(generation_provenance.get("parameter_profile_ids", []) or []),
            "claim_boundary": (
                "Release-generation provenance is search-control metadata only; "
                "it is not PPA evidence."
            ),
        },
        "candidate_id": candidate.get("candidate_id"),
        "identity_hash": candidate.get("identity_hash"),
        "record_hash": candidate.get("record_hash"),
        "legal": candidate.get("legal", True) is True,
        "illegal_reasons": list(candidate.get("illegal_reasons", []) or []),
        "deployment_boundary_id": deployment.get("deployment_boundary_id")
        if isinstance(deployment, Mapping)
        else None,
        "target_platform_id": target.get("target_platform_id")
        if isinstance(target, Mapping)
        else None,
        "target_platform_kind": target.get("platform_kind")
        if isinstance(target, Mapping)
        else _candidate_target_kind(candidate),
        "claim_boundary": (
            "Release-universe provenance identifies the legal frozen candidate "
            "row that supplied this recommendation input; it is not PPA evidence."
        ),
    }


def _discover_release_universe_manifest(run_dir: Path, ranking: Mapping[str, Any]) -> Path | None:
    source_artifacts = ranking.get("source_artifacts", {})
    if isinstance(source_artifacts, Mapping):
        for key in ("release_subset_manifest", "candidate_universe_manifest"):
            ref = source_artifacts.get(key, {})
            if isinstance(ref, Mapping) and ref.get("path"):
                candidate = Path(str(ref["path"]))
                if candidate.exists() and candidate.is_file():
                    return candidate
    for candidate in (
        run_dir / "release_subset_manifest.json",
        run_dir / "search_space" / "release_subset_manifest.json",
        run_dir / "candidate_universe_manifest.json",
        run_dir / "release_domain" / "candidate_universe_manifest.json",
        run_dir / "release_domain_current36" / "candidate_universe_manifest.json",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _release_universe_binding(
    run_dir: Path,
    ranking: Mapping[str, Any],
    *,
    fpga_rows: Sequence[Mapping[str, Any]],
    asic_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    manifest_path = _discover_release_universe_manifest(run_dir, ranking)
    release_subset = _load_json(manifest_path) if manifest_path is not None else {}
    blockers: list[Dict[str, Any]] = []
    if not release_subset:
        blockers.append({"blocker_id": "missing_release_universe_manifest"})
    raw_legal_ids = release_subset.get("legal_candidate_ids", [])
    legal_candidate_ids = [
        str(candidate_id) for candidate_id in raw_legal_ids if str(candidate_id)
    ] if isinstance(raw_legal_ids, list) else []
    legal_id_set = set(legal_candidate_ids)
    candidates = [
        dict(candidate)
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ] if isinstance(release_subset.get("candidates", []), list) else []
    legal_candidates_by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidates
        if str(candidate.get("candidate_id") or "") in legal_id_set
        and candidate.get("legal", True) is True
    }
    if release_subset and not legal_candidate_ids:
        blockers.append({"blocker_id": "release_universe_has_no_legal_candidate_ids"})
    if release_subset and not legal_candidates_by_id:
        blockers.append({"blocker_id": "release_universe_has_no_legal_candidate_records"})

    rows_by_target = {"fpga": list(fpga_rows), "asic": list(asic_rows)}
    target_coverage: Dict[str, Any] = {}
    for target, rows in rows_by_target.items():
        required_ids = [
            candidate_id
            for candidate_id in legal_candidate_ids
            if _candidate_target_kind(legal_candidates_by_id.get(candidate_id, {})) == target
        ]
        present_ids = [
            str(row.get("candidate_id") or "")
            for row in rows
            if row.get("candidate_id")
        ]
        missing_ids = [
            candidate_id for candidate_id in required_ids if candidate_id not in set(present_ids)
        ]
        unexpected_ids = [
            candidate_id for candidate_id in present_ids if candidate_id not in legal_id_set
        ]
        wrong_target_ids = [
            candidate_id
            for candidate_id in present_ids
            if candidate_id in legal_candidates_by_id
            and _candidate_target_kind(legal_candidates_by_id[candidate_id]) not in {"", target}
        ]
        if release_subset and not required_ids:
            blockers.append({"blocker_id": f"{target}_release_universe_target_axis_missing"})
        if unexpected_ids:
            blockers.append(
                {
                    "blocker_id": f"{target}_ranking_row_candidate_not_in_release_universe",
                    "candidate_ids": sorted(set(unexpected_ids)),
                }
            )
        if wrong_target_ids:
            blockers.append(
                {
                    "blocker_id": f"{target}_ranking_row_candidate_wrong_target_axis",
                    "candidate_ids": sorted(set(wrong_target_ids)),
                }
            )
        if missing_ids:
            blockers.append(
                {
                    "blocker_id": f"{target}_missing_release_universe_target_ranking_rows",
                    "missing_candidate_count": len(missing_ids),
                    "missing_candidate_ids": missing_ids[:20],
                }
            )
        target_coverage[target] = {
            "required_candidate_count": len(required_ids),
            "present_ranking_row_count": len(rows),
            "present_candidate_ids": present_ids,
            "missing_candidate_count": len(missing_ids),
            "unexpected_candidate_count": len(unexpected_ids),
            "wrong_target_candidate_count": len(wrong_target_ids),
            "coverage_complete": (
                bool(required_ids)
                and not missing_ids
                and not unexpected_ids
                and not wrong_target_ids
            ),
        }
    return {
        "schema_version": "dse.dft.deployment_comparator.release_universe_binding.v1",
        "valid": not blockers,
        "status": "release_universe_bound" if not blockers else "blocked_release_universe_binding",
        "source_artifact": _source_ref_from_optional(manifest_path),
        "release_id": release_subset.get("release_id"),
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "legal_candidate_count": len(legal_candidate_ids),
        "legal_candidate_ids": legal_candidate_ids,
        "target_coverage": target_coverage,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "claim_boundary": (
            "Best/Pareto deployment recommendation inputs must be drawn from "
            "the frozen release universe, with every legal target-specific "
            "candidate row present before recommendation claims are allowed."
        ),
    }


def _attach_release_universe_provenance(
    rows: Sequence[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    manifest_path_text = binding.get("source_artifact", {}).get("path") if isinstance(binding.get("source_artifact", {}), Mapping) else None
    manifest_path = Path(str(manifest_path_text)) if manifest_path_text else None
    release_subset = _load_json(manifest_path) if manifest_path is not None else {}
    candidates = [
        dict(candidate)
        for candidate in release_subset.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ] if isinstance(release_subset.get("candidates", []), list) else []
    by_id = {str(candidate.get("candidate_id")): candidate for candidate in candidates}
    enriched: list[Dict[str, Any]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        item = dict(row)
        if candidate_id in by_id:
            item["release_universe_provenance"] = _candidate_release_provenance(
                by_id[candidate_id],
                release_subset=release_subset,
                manifest_path=manifest_path,
            )
        enriched.append(item)
    return enriched


def _release_universe_target_blockers(
    binding: Mapping[str, Any],
    target: str,
) -> list[Dict[str, Any]]:
    blockers = [
        dict(blocker)
        for blocker in binding.get("blockers", []) or []
        if isinstance(blocker, Mapping)
    ]
    target_prefixes = ("fpga_", "asic_")
    target_blockers: list[Dict[str, Any]] = []
    for blocker in blockers:
        blocker_id = str(blocker.get("blocker_id") or "")
        if blocker_id.startswith(f"{target}_") or not blocker_id.startswith(target_prefixes):
            target_blockers.append(blocker)
    coverage = binding.get("target_coverage", {})
    coverage = coverage if isinstance(coverage, Mapping) else {}
    target_coverage = coverage.get(target, {})
    if isinstance(target_coverage, Mapping) and target_coverage.get("coverage_complete") is not True:
        target_blockers.append(
            {
                "blocker_id": f"{target}_release_universe_target_coverage_incomplete",
                "missing_candidate_count": target_coverage.get("missing_candidate_count"),
                "unexpected_candidate_count": target_coverage.get("unexpected_candidate_count"),
                "wrong_target_candidate_count": target_coverage.get("wrong_target_candidate_count"),
            }
        )
    return target_blockers


def _recommendation_for_target(
    target: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    ranking_valid: bool,
    hardware_completion_eligible: bool,
    provenance_eligible: bool,
    release_universe_binding: Mapping[str, Any],
) -> Dict[str, Any]:
    rows = [dict(row) for row in rows]
    top_rows = _rank_one_rows(rows)
    top_candidates = [_candidate_summary(target, row) for row in top_rows]
    top_candidate_ids = [
        str(item.get("candidate_id"))
        for item in top_candidates
        if item.get("candidate_id")
    ]
    blockers: list[Dict[str, Any]] = []
    if not ranking_valid:
        blockers.append({"blocker_id": "ppa_ranking_validation_not_valid"})
    if not hardware_completion_eligible:
        blockers.append({"blocker_id": "ppa_ranking_not_hardware_completion_eligible"})
    if not provenance_eligible:
        blockers.append({"blocker_id": "candidate_specific_ppa_provenance_not_trusted"})
    release_target_blockers = _release_universe_target_blockers(
        release_universe_binding,
        target,
    )
    if release_target_blockers:
        blockers.append(
            {
                "blocker_id": f"{target}_release_universe_binding_not_valid",
                "blockers": release_target_blockers,
            }
        )
    if not rows:
        blockers.append({"blocker_id": "no_target_ranking_rows"})
    if not top_rows:
        blockers.append({"blocker_id": "no_rank_one_candidate"})

    if len(top_rows) == 1 and not blockers:
        status = "unique_physical_winner"
        recommendation_kind = "unique_candidate"
        unique_winner = top_candidates[0]
    elif len(top_rows) > 1 and not blockers:
        status = f"physical_tie_no_single_{target}_winner"
        recommendation_kind = "best_physical_tie_set"
        unique_winner = None
    else:
        status = f"blocked_no_{target}_recommendation"
        recommendation_kind = "blocked"
        unique_winner = None

    return {
        "schema_version": "dse.dft.deployment_comparator.target_recommendation.v1",
        "target": target,
        "status": status,
        "recommendation_kind": recommendation_kind,
        "unique_winner": unique_winner,
        "top_candidate_count": len(top_rows),
        "top_candidate_ids": top_candidate_ids,
        "top_candidates": top_candidates,
        "ranking_row_count": len(rows),
        "blockers": blockers,
        "non_physical_tie_breakers_used": False,
        "forbidden_tie_breakers": list(_FORBIDDEN_TIE_BREAKERS),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_deployment_comparator(run_dir: Path) -> Dict[str, Any]:
    """Build a fail-safe FPGA/ASIC deployment comparator payload."""

    run_dir = Path(run_dir)
    ranking_path = run_dir / "dft_hardware_ppa_ranking.json"
    ranking_validation_path = run_dir / "dft_hardware_ppa_ranking_validation.json"
    pareto_path = run_dir / "dft_hardware_ppa_pareto_frontier.json"
    winner_path = run_dir / "dft_architecture_winner_resolution.json"
    provenance_path = run_dir / "dft_candidate_specific_ppa_provenance_audit.json"
    tie_breaker_queue_path = run_dir / "dft_hardware_tie_breaker_execution_queue.json"
    release_gate_path = run_dir / "dft_hardware_closure_release_gate.json"
    gate_adjudication_path = run_dir / "dft_hardware_closure_gate_adjudication.json"
    parser_run_path = run_dir / "dft_hardware_closure_parser_run.json"
    ranking = _load_json(ranking_path)
    ranking_validation = _load_json(ranking_validation_path)
    winner_resolution = _load_json(winner_path)
    provenance = _load_json(provenance_path)
    ranking_valid = ranking_validation.get("valid") is True
    hardware_completion_eligible = ranking.get("hardware_completion_eligible") is True
    provenance_eligible = provenance.get("winner_provenance_eligible") is True
    fpga_rows = _as_rows(ranking.get("fpga_ranking", []))
    asic_rows = _as_rows(ranking.get("asic_ranking", []))
    release_universe_binding = _release_universe_binding(
        run_dir,
        ranking,
        fpga_rows=fpga_rows,
        asic_rows=asic_rows,
    )
    fpga_rows = _attach_release_universe_provenance(
        fpga_rows,
        binding=release_universe_binding,
    )
    asic_rows = _attach_release_universe_provenance(
        asic_rows,
        binding=release_universe_binding,
    )
    fpga = _recommendation_for_target(
        "fpga",
        fpga_rows,
        ranking_valid=ranking_valid,
        hardware_completion_eligible=hardware_completion_eligible,
        provenance_eligible=provenance_eligible,
        release_universe_binding=release_universe_binding,
    )
    asic = _recommendation_for_target(
        "asic",
        asic_rows,
        ranking_valid=ranking_valid,
        hardware_completion_eligible=hardware_completion_eligible,
        provenance_eligible=provenance_eligible,
        release_universe_binding=release_universe_binding,
    )
    available = [
        item for item in (fpga, asic)
        if item.get("recommendation_kind") in {"unique_candidate", "best_physical_tie_set"}
    ]
    target_recommendation_available_count = len(available)
    cross_target_comparison_eligible = target_recommendation_available_count == 2
    if not ranking:
        status = "blocked_missing_hardware_ppa_ranking"
    elif len(available) == 2 and any(item.get("recommendation_kind") == "best_physical_tie_set" for item in available):
        status = "partial_recommendation_available"
    elif len(available) == 2:
        status = "target_recommendations_available"
    elif available:
        status = "partial_recommendation_available"
    else:
        status = "blocked_no_deployment_recommendations"

    return {
        "schema_version": DFT_DEPLOYMENT_COMPARATOR_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "deployment_comparison_status": status,
        "source_artifacts": {
            "dft_hardware_ppa_ranking": _source_ref(ranking_path),
            "dft_hardware_ppa_ranking_validation": _source_ref(ranking_validation_path),
            "dft_hardware_ppa_pareto_frontier": _source_ref(pareto_path, required=False),
            "dft_architecture_winner_resolution": _source_ref(winner_path, required=False),
            "dft_candidate_specific_ppa_provenance_audit": _source_ref(provenance_path, required=False),
            "dft_hardware_tie_breaker_execution_queue": _source_ref(tie_breaker_queue_path, required=False),
            "dft_hardware_closure_release_gate": _source_ref(release_gate_path, required=False),
            "dft_hardware_closure_gate_adjudication": _source_ref(gate_adjudication_path, required=False),
            "dft_hardware_closure_parser_run": _source_ref(parser_run_path, required=False),
            "release_universe_manifest": release_universe_binding["source_artifact"],
        },
        "release_id": ranking.get("release_id"),
        "release_subset_hash": release_universe_binding.get("release_subset_hash"),
        "candidate_count": ranking.get("candidate_count"),
        "ranking_eligible_candidate_count": ranking.get("ranking_eligible_candidate_count"),
        "hardware_completion_eligible": hardware_completion_eligible,
        "candidate_specific_ppa_provenance_eligible": provenance_eligible,
        "release_universe_binding": release_universe_binding,
        "winner_resolution_status": winner_resolution.get("status"),
        "fpga_recommendation": fpga,
        "asic_recommendation": asic,
        "target_recommendations": {"fpga": fpga, "asic": asic},
        "target_recommendation_available_count": target_recommendation_available_count,
        "cross_target_comparison_eligible": cross_target_comparison_eligible,
        "cross_target_recommendation": {
            "status": "no_single_cross_target_winner_without_user_objective",
            "single_cross_target_winner": None,
            "objective_required": True,
            "acceptable_objective_examples": [
                "minimize FPGA resources under a board budget",
                "minimize ASIC cell area at non-negative slack",
                "minimize end-to-end SCF time/energy with normalized cost weights",
            ],
            "claim_boundary": (
                "FPGA resource/timing and ASIC area/timing are not normalized "
                "into one scalar without an explicit user objective/cost model."
            ),
        },
        "non_physical_tie_breakers_used": False,
        "forbidden_tie_breakers": list(_FORBIDDEN_TIE_BREAKERS),
        "hardware_completion_eligible_for_deployment_comparison": cross_target_comparison_eligible,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_comparator(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate deployment-comparator consistency without upgrading claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_COMPARATOR_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("deployment_comparator_must_not_mark_deliverable_complete")
    if payload.get("trusted_final_claim") is True:
        errors.append("deployment_comparator_must_not_mark_trusted_final_claim")
    if payload.get("non_physical_tie_breakers_used") is True:
        errors.append("non_physical_tie_breakers_forbidden")
    release_binding = payload.get("release_universe_binding", {})
    if not isinstance(release_binding, Mapping):
        errors.append("release_universe_binding_missing_or_not_mapping")
        release_binding = {}
    else:
        binding_valid = release_binding.get("valid") is True
        blockers = release_binding.get("blockers", [])
        blocker_count = int(release_binding.get("blocker_count", 0) or 0)
        if binding_valid and blocker_count:
            errors.append("release_universe_binding_valid_with_blockers")
        if not binding_valid and blocker_count == 0:
            errors.append("release_universe_binding_invalid_without_blockers")
        if blockers and blocker_count != len(blockers):
            errors.append("release_universe_binding_blocker_count_mismatch")
    cross = payload.get("cross_target_recommendation", {})
    if not isinstance(cross, Mapping):
        errors.append("cross_target_recommendation_missing_or_not_mapping")
    elif cross.get("single_cross_target_winner") is not None:
        errors.append("single_cross_target_winner_forbidden_without_objective")
    available_target_count = 0
    for target in ("fpga", "asic"):
        item = payload.get(f"{target}_recommendation", {})
        if not isinstance(item, Mapping):
            errors.append(f"{target}_recommendation_missing_or_not_mapping")
            continue
        status = str(item.get("status") or "")
        kind = str(item.get("recommendation_kind") or "")
        top_count = int(item.get("top_candidate_count", 0) or 0)
        if item.get("non_physical_tie_breakers_used") is True:
            errors.append(f"{target}_non_physical_tie_breakers_forbidden")
        if kind == "unique_candidate" and (top_count != 1 or not isinstance(item.get("unique_winner"), Mapping)):
            errors.append(f"{target}_unique_recommendation_without_single_winner")
        if kind == "best_physical_tie_set" and top_count < 2:
            errors.append(f"{target}_tie_set_without_multiple_top_candidates")
        if "physical_tie_no_single" in status and item.get("unique_winner") is not None:
            errors.append(f"{target}_physical_tie_must_not_have_unique_winner")
        if kind in {"unique_candidate", "best_physical_tie_set"}:
            available_target_count += 1
    reported_available_count = payload.get("target_recommendation_available_count")
    if reported_available_count is not None:
        try:
            reported_available_count_int = int(reported_available_count or 0)
        except (TypeError, ValueError):
            errors.append("target_recommendation_available_count_not_integer")
            reported_available_count_int = available_target_count
        if reported_available_count_int != available_target_count:
            errors.append("target_recommendation_available_count_mismatch")
    expected_cross_eligible = available_target_count == 2
    if (
        "cross_target_comparison_eligible" in payload
        and bool(payload.get("cross_target_comparison_eligible")) != expected_cross_eligible
    ):
        errors.append("cross_target_comparison_eligible_mismatch")
    if (
        "hardware_completion_eligible_for_deployment_comparison" in payload
        and bool(payload.get("hardware_completion_eligible_for_deployment_comparison")) != expected_cross_eligible
    ):
        errors.append("deployment_comparison_hardware_completion_eligibility_mismatch")
    return {
        "schema_version": DFT_DEPLOYMENT_COMPARATOR_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_comparator(run_dir: Path) -> Dict[str, Any]:
    """Write deployment-comparator, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    comparator = build_dft_deployment_comparator(run_dir)
    validation = validate_dft_deployment_comparator(comparator)
    write_json(run_dir / "dft_deployment_comparator.json", comparator)
    write_json(run_dir / "dft_deployment_comparator_validation.json", validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_COMPARATOR_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "deployment_comparison_status": comparator.get("deployment_comparison_status"),
        "fpga_recommendation_status": comparator.get("fpga_recommendation", {}).get("status"),
        "asic_recommendation_status": comparator.get("asic_recommendation", {}).get("status"),
        "cross_target_recommendation_status": comparator.get("cross_target_recommendation", {}).get("status"),
        "target_recommendation_available_count": comparator.get("target_recommendation_available_count"),
        "cross_target_comparison_eligible": comparator.get("cross_target_comparison_eligible"),
        "hardware_completion_eligible_for_deployment_comparison": comparator.get(
            "hardware_completion_eligible_for_deployment_comparison"
        ),
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_deployment_comparator_status.json", status)
    return {
        "schema_version": "dse.dft.deployment_comparator_artifact_status.v1",
        "status": status["status"],
        "deployment_comparator": str(run_dir / "dft_deployment_comparator.json"),
        "deployment_comparator_validation": str(run_dir / "dft_deployment_comparator_validation.json"),
        "deployment_comparator_status": str(run_dir / "dft_deployment_comparator_status.json"),
        "deployment_comparison_status": comparator.get("deployment_comparison_status"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_DEPLOYMENT_COMPARATOR_SCHEMA",
    "DFT_DEPLOYMENT_COMPARATOR_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_COMPARATOR_VALIDATION_SCHEMA",
    "build_dft_deployment_comparator",
    "validate_dft_deployment_comparator",
    "write_dft_deployment_comparator",
]
