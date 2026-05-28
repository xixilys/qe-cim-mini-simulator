#!/usr/bin/env python3
"""Replayable deployment decision summary for DFT/QE hardware DSE.

This artifact is intentionally a summary/adjudication surface, not a new gate.
It gathers the target-model selection/binding, hardware-PPA ranking,
deployment comparator, and explicit-objective selector into one fail-closed
FPGA-vs-ASIC deployment recommendation record.  It must not convert missing
Vivado/DC hard gates, physical ties, or partial evidence into final claims.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA = "dse.dft.deployment_decision_summary.v1"
DFT_DEPLOYMENT_DECISION_SUMMARY_VALIDATION_SCHEMA = (
    "dse.dft.deployment_decision_summary_validation.v1"
)
DFT_DEPLOYMENT_DECISION_SUMMARY_STATUS_SCHEMA = (
    "dse.dft.deployment_decision_summary_status.v1"
)

_CLAIM_BOUNDARY = (
    "Deployment decision summary is a replayable evidence roll-up for the "
    "current FPGA-vs-ASIC deployment recommendation. It reports the best "
    "current target/candidate only under the explicit selector objective and "
    "available target-model binding/PPA evidence; it does not prove missing "
    "Vivado/DC hard gates, does not collapse physical ties, and cannot mark "
    "full-SCF deliverable completion."
)

_REQUIRED_DECISION_ARTIFACTS = {
    "dft_deployment_comparator": "dft_deployment_comparator.json",
    "dft_deployment_comparator_validation": "dft_deployment_comparator_validation.json",
    "dft_deployment_selector": "dft_deployment_selector.json",
    "dft_deployment_selector_validation": "dft_deployment_selector_validation.json",
}

_OPTIONAL_DECISION_ARTIFACTS = {
    "complete_dse_release_artifact_package": "complete_dse_release_artifact_package.json",
    "complete_dse_release_artifact_hash_manifest": "complete_dse_release_artifact_hash_manifest.json",
    "dft_deployment_target_model_selection": "dft_deployment_target_model_selection.json",
    "dft_deployment_target_model_selection_status": "dft_deployment_target_model_selection_status.json",
    "dft_deployment_target_model_binding": "dft_deployment_target_model_binding.json",
    "dft_deployment_target_model_binding_validation": "dft_deployment_target_model_binding_validation.json",
    "dft_vivado_part_support_probe": "dft_vivado_part_support_probe.json",
    "dft_deployment_hard_gate_execution_queue_status": "dft_deployment_hard_gate_execution_queue_status.json",
    "dft_hardware_ppa_ranking": "dft_hardware_ppa_ranking.json",
    "dft_hardware_ppa_ranking_status": "dft_hardware_ppa_ranking_status.json",
    "dft_deployment_comparator_status": "dft_deployment_comparator_status.json",
    "dft_deployment_selector_status": "dft_deployment_selector_status.json",
    "step5_final_report": "step3_queue/final_report.json",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool) -> Dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_rows(value: Any) -> list[Dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _is_candidate_id_key(key: str) -> bool:
    return (
        key == "candidate_id"
        or key.endswith("_candidate_id")
        or key == "candidate_ids"
        or key.endswith("_candidate_ids")
    )


def _candidate_id_refs(payload: Any, *, path: str = "$") -> list[Dict[str, str]]:
    refs: list[Dict[str, str]] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if _is_candidate_id_key(str(key)):
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        if item is None:
                            continue
                        if isinstance(item, (Mapping, list)):
                            refs.extend(
                                _candidate_id_refs(
                                    item,
                                    path=f"{child_path}[{index}]",
                                )
                            )
                            continue
                        candidate_id = str(item).strip()
                        if candidate_id:
                            refs.append(
                                {
                                    "path": f"{child_path}[{index}]",
                                    "candidate_id": candidate_id,
                                }
                            )
                    continue
                candidate_id = str(value or "").strip()
                if candidate_id:
                    refs.append({"path": child_path, "candidate_id": candidate_id})
                    continue
            refs.extend(_candidate_id_refs(value, path=child_path))
        return refs
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            refs.extend(_candidate_id_refs(item, path=f"{path}[{index}]"))
    return refs


def _unique_nonempty_strings(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _release_universe_candidate_identity_binding(
    *,
    source_payloads: Mapping[str, Mapping[str, Any]],
    package: Mapping[str, Any],
) -> Dict[str, Any]:
    frozen_release_subset = build_release_subset_manifest()
    release_candidate_ids = [
        str(candidate_id)
        for candidate_id in frozen_release_subset.get("legal_candidate_ids", []) or []
        if candidate_id
    ]
    release_candidate_set = set(release_candidate_ids)
    refs: list[Dict[str, str]] = []
    for artifact_name, payload in source_payloads.items():
        for ref in _candidate_id_refs(payload, path=f"$.{artifact_name}"):
            ref = dict(ref)
            ref["source_artifact"] = artifact_name
            refs.append(ref)
    candidate_ids = _unique_nonempty_strings([ref["candidate_id"] for ref in refs])
    extra_candidate_ids = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in release_candidate_set
    ]
    blocker_ids: list[str] = []
    if extra_candidate_ids:
        blocker_ids.append("deployment_summary_candidate_ids_not_in_frozen_release_universe")

    package_release_universe = _as_mapping(package.get("release_universe"))
    package_binding = _as_mapping(package.get("release_universe_candidate_identity_binding"))
    if package_release_universe:
        if (
            str(package_release_universe.get("release_id") or "")
            != str(frozen_release_subset.get("release_id") or "")
        ):
            blocker_ids.append("release_package_release_id_not_frozen_release_universe")
        if (
            str(package_release_universe.get("release_subset_hash") or "")
            != str(frozen_release_subset.get("release_subset_hash") or "")
        ):
            blocker_ids.append("release_package_release_subset_hash_mismatch")
    if package_binding.get("status") == "blocked":
        blocker_ids.extend(
            str(blocker_id)
            for blocker_id in package_binding.get("blocker_ids", []) or []
            if blocker_id
        )

    blocker_ids = sorted(dict.fromkeys(blocker_ids))
    return {
        "schema_version": "dse.dft.deployment_decision_summary.release_universe_candidate_identity_binding.v1",
        "status": "blocked" if blocker_ids else "passed",
        "release_id": frozen_release_subset.get("release_id"),
        "release_subset_hash": frozen_release_subset.get("release_subset_hash"),
        "candidate_source": "complete_dse_qe_release_v1.legal_candidate_ids",
        "release_candidate_count": len(release_candidate_ids),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "candidate_id_refs": refs,
        "candidate_ids_bound_to_frozen_release_universe": not blocker_ids,
        "extra_candidate_ids": extra_candidate_ids,
        "package_release_id": package_release_universe.get("release_id"),
        "package_release_subset_hash": package_release_universe.get("release_subset_hash"),
        "package_binding_status": package_binding.get("status"),
        "package_binding_blocker_ids": list(package_binding.get("blocker_ids", []) or []),
        "blocker_ids": blocker_ids,
        "claim_boundary": (
            "Candidate-ID binding only. Deployment-summary candidate IDs must "
            "be members of the frozen complete_dse_qe_release_v1 release "
            "universe; unsupported DFT/manual IDs are fail-closed rather than "
            "crosswalked to cdse_* IDs."
        ),
    }


def _block_recommendation_for_release_universe_binding(
    best: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> Dict[str, Any]:
    blocker_ids = sorted(
        dict.fromkeys(
            [
                *[str(item) for item in best.get("blocker_ids", []) or [] if item],
                *[str(item) for item in binding.get("blocker_ids", []) or [] if item],
            ]
        )
    )
    return {
        "status": "blocked_release_universe_candidate_identity_binding",
        "recommended_target": None,
        "recommended_candidate_id": None,
        "selected_candidate": None,
        "objective_id": best.get("objective_id"),
        "rationale": [
            "deployment summary candidate IDs are not fully bound to the frozen complete_dse_qe_release_v1 release universe",
            "unsupported candidate IDs remain blockers; no dft-* to cdse_* crosswalk was inferred",
        ],
        "blocker_ids": blocker_ids,
        "selected_target_blocker_ids": list(best.get("selected_target_blocker_ids", []) or []),
        "side_target_blocker_ids": list(best.get("side_target_blocker_ids", []) or []),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _source_artifacts(run_dir: Path) -> Dict[str, Any]:
    refs: Dict[str, Any] = {}
    for key, rel_path in _REQUIRED_DECISION_ARTIFACTS.items():
        refs[key] = _source_ref(run_dir / rel_path, required=True)
    for key, rel_path in _OPTIONAL_DECISION_ARTIFACTS.items():
        refs[key] = _source_ref(run_dir / rel_path, required=False)
    return refs


def _release_candidate_identity_provenance_summary(
    run_dir: Path,
    *,
    release_universe_candidate_identity_binding: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    package_path = run_dir / "complete_dse_release_artifact_package.json"
    package_ref = _source_ref(package_path, required=False)
    package = _load_json(package_path) if package_ref["exists"] is True else {}
    provenance = _as_mapping(package.get("release_candidate_identity_provenance"))
    binding = _as_mapping(release_universe_candidate_identity_binding)
    binding_blocked = binding.get("status") == "blocked"
    binding_blockers = [
        str(blocker_id) for blocker_id in binding.get("blocker_ids", []) or [] if blocker_id
    ]
    if not package_ref["exists"]:
        if binding_blocked:
            return {
                "release_candidate_identity_provenance_status": "blocked",
                "release_candidate_identity_provenance_blocker_ids": binding_blockers,
                "release_candidate_identity_provenance_package_exists": False,
                "release_candidate_identity_provenance_package_status": None,
                "release_candidate_identity_provenance_canonical_bundle_bound": False,
                "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": False,
                "release_candidate_identity_provenance_claim_boundary": (
                    "No canonical Complete-DSE release artifact package is "
                    "present, and the deployment summary contains candidate IDs "
                    "outside the frozen release universe."
                ),
            }
        return {
            "release_candidate_identity_provenance_status": "unbound",
            "release_candidate_identity_provenance_blocker_ids": [
                "release_candidate_identity_provenance_package_not_bound"
            ],
            "release_candidate_identity_provenance_package_exists": False,
            "release_candidate_identity_provenance_package_status": None,
            "release_candidate_identity_provenance_canonical_bundle_bound": False,
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": False,
            "release_candidate_identity_provenance_claim_boundary": (
                "No canonical Complete-DSE release artifact package is present "
                "beside this deployment decision summary, so release-package "
                "candidate identity provenance is unbound and cannot support "
                "FPGA/ASIC or deliverable-complete claims."
            ),
        }
    if not provenance:
        blocker_ids = ["release_candidate_identity_provenance_missing_from_release_package"]
        if binding_blocked:
            blocker_ids.extend(binding_blockers)
        return {
            "release_candidate_identity_provenance_status": "blocked",
            "release_candidate_identity_provenance_blocker_ids": sorted(dict.fromkeys(blocker_ids)),
            "release_candidate_identity_provenance_package_exists": True,
            "release_candidate_identity_provenance_package_status": package.get("status"),
            "release_candidate_identity_provenance_canonical_bundle_bound": False,
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": False,
            "release_candidate_identity_provenance_claim_boundary": (
                "The canonical Complete-DSE release artifact package is present "
                "but does not contain release_candidate_identity_provenance, so "
                "candidate identity remains fail-closed for release claims."
            ),
        }
    provenance_blockers = [
        str(blocker)
        for blocker in list(provenance.get("blocker_ids", []) or [])
        if blocker
    ]
    if binding_blocked:
        provenance_blockers.extend(binding_blockers)
    provenance_status = str(provenance.get("status") or "blocked")
    if binding_blocked:
        provenance_status = "blocked"
    return {
        "release_candidate_identity_provenance_status": provenance_status,
        "release_candidate_identity_provenance_blocker_ids": sorted(
            dict.fromkeys(provenance_blockers)
        ),
        "release_candidate_identity_provenance_package_exists": True,
        "release_candidate_identity_provenance_package_status": package.get("status"),
        "release_candidate_identity_provenance_canonical_bundle_bound": bool(
            provenance.get("canonical_bundle_bound") is True
        ),
        "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": bool(
            provenance.get("trusted_for_release_package_candidate_identity") is True
            and not binding_blocked
        ),
        "release_candidate_identity_provenance_claim_boundary": provenance.get(
            "claim_boundary"
        ),
    }


def _selection_row_by_target(selection: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for row in _as_rows(selection.get("selection_rows")):
        target = str(row.get("target") or "")
        if target and target not in rows:
            rows[target] = row
    return rows


def _binding_row_by_target(binding: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for row in _as_rows(binding.get("target_binding_rows")):
        target = str(row.get("target") or "")
        if target and target not in rows:
            rows[target] = row
    return rows


def _model_id(model: Mapping[str, Any]) -> str | None:
    value = model.get("model_id") or model.get("board_or_device_model") or model.get("library_name")
    return str(value) if value else None


def _vivado_part_probe_summary(part_probe: Mapping[str, Any]) -> Dict[str, Any]:
    if not part_probe:
        return {
            "present": False,
            "status": "not_present",
            "requested_parts": [],
            "supported_parts": [],
            "missing_requested_parts": [],
            "attempted": False,
            "claim_boundary": (
                "No canonical Vivado part-support probe artifact was present in "
                "this run. Target binding may still report manually supplied "
                "supported parts."
            ),
        }
    return {
        "present": True,
        "status": part_probe.get("status"),
        "requested_parts": list(part_probe.get("requested_parts", []) or []),
        "supported_parts": list(part_probe.get("supported_parts", []) or []),
        "missing_requested_parts": list(part_probe.get("missing_requested_parts", []) or []),
        "selected_probe_transport": part_probe.get("selected_probe_transport"),
        "selected_probe_returncode": part_probe.get("selected_probe_returncode"),
        "attempted": bool(part_probe.get("vivado_part_support_probe_attempted")),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": part_probe.get(
            "claim_boundary",
            "Vivado part-support probe only; not synthesis, implementation, timing, or PPA evidence.",
        ),
    }


def _tool_support_summary(
    target: str,
    binding_row: Mapping[str, Any],
    *,
    vivado_part_probe: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    binding_status = str(binding_row.get("binding_status") or "not_bound")
    if target == "fpga":
        blocked = binding_status.startswith("blocked")
        return {
            "tool": "vivado",
            "support_status": "blocked" if blocked else "supported_or_not_required",
            "binding_status": binding_status,
            "selected_vivado_parts": list(binding_row.get("selected_vivado_parts", []) or []),
            "vivado_supported_parts": list(binding_row.get("vivado_supported_parts", []) or []),
            "vivado_part_support_probe": _vivado_part_probe_summary(vivado_part_probe or {}),
            "blocker_ids": list(binding_row.get("blocker_ids", []) or []),
            "claim_boundary": (
                "Vivado part support is an admission check only; FPGA deployment "
                "still requires candidate-specific Vivado synthesis/implementation gates."
            ),
        }
    if target == "asic":
        blocked = binding_status.startswith("blocked")
        return {
            "tool": "dc_shell",
            "support_status": "blocked" if blocked else "supported_or_not_required",
            "binding_status": binding_status,
            "selected_dc_target_libraries": list(binding_row.get("selected_dc_target_libraries", []) or []),
            "dc_supported_target_libraries": list(binding_row.get("dc_supported_target_libraries", []) or []),
            "dc_library_db_paths": list(binding_row.get("dc_library_db_paths", []) or []),
            "blocker_ids": list(binding_row.get("blocker_ids", []) or []),
            "claim_boundary": (
                "DC target-library support is an admission check only; ASIC deployment "
                "still requires candidate-specific DC timing/area gates."
            ),
        }
    return {"tool": None, "support_status": "unknown_target"}


def _target_assessment(
    target: str,
    *,
    selection_row: Mapping[str, Any],
    binding_row: Mapping[str, Any],
    comparator_recommendation: Mapping[str, Any],
    selector: Mapping[str, Any],
    vivado_part_probe: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    selected_by_objective = selector.get("selected_deployment_target") == target
    selected_model = _as_mapping(binding_row.get("selected_model")) or _as_mapping(selection_row.get("selected_model"))
    binding_status = str(binding_row.get("binding_status") or "not_present")
    rec = dict(comparator_recommendation)
    blockers = []
    blockers.extend(str(item) for item in binding_row.get("blocker_ids", []) or [] if item)
    for blocker in _as_rows(rec.get("blockers")):
        blocker_id = blocker.get("blocker_id")
        if blocker_id:
            blockers.append(str(blocker_id))
    if selected_by_objective:
        for blocker in _as_rows(selector.get("blockers")):
            blocker_id = blocker.get("blocker_id")
            if blocker_id:
                blockers.append(str(blocker_id))
    blockers = sorted(dict.fromkeys(blockers))
    binding_ready = bool(binding_row) and not binding_status.startswith("blocked")
    rec_kind = str(rec.get("recommendation_kind") or "not_present")
    deployment_ready = bool(binding_ready and rec_kind == "unique_candidate")
    return {
        "schema_version": "dse.dft.deployment_decision_summary.target_assessment.v1",
        "target": target,
        "selected_by_explicit_objective": bool(selected_by_objective),
        "candidate_id_selected_by_objective": selector.get("selected_candidate_id") if selected_by_objective else None,
        "target_model_selection_status": selection_row.get("selection_status") or "not_present",
        "selected_model": selected_model,
        "selected_model_id": _model_id(selected_model),
        "target_model_binding_status": binding_status,
        "target_model_binding_ready": binding_ready,
        "tool_support": _tool_support_summary(target, binding_row, vivado_part_probe=vivado_part_probe),
        "comparator_recommendation_status": rec.get("status"),
        "comparator_recommendation_kind": rec_kind,
        "top_candidate_count": rec.get("top_candidate_count"),
        "top_candidate_ids": list(rec.get("top_candidate_ids", []) or []),
        "unique_winner": rec.get("unique_winner"),
        "blocker_ids": blockers,
        "deployment_ready_for_current_objective": deployment_ready and bool(selected_by_objective),
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Target assessment combines admission binding and comparator evidence; "
            "it is not by itself a final deployment or full-SCF completion claim."
        ),
    }


def _best_recommendation(
    *,
    selector: Mapping[str, Any],
    comparator: Mapping[str, Any],
    target_assessments: Mapping[str, Mapping[str, Any]],
    target_recommendation_available_count: int,
    cross_target_comparison_eligible: bool,
) -> Dict[str, Any]:
    selection_status = str(selector.get("selection_status") or selector.get("status") or "not_present")
    selected_target = selector.get("selected_deployment_target")
    selected_candidate_id = selector.get("selected_candidate_id")
    if selection_status == "unique_deployment_candidate_selected_by_explicit_objective" and selected_target:
        objective_target = str(
            _as_mapping(selector.get("objective")).get("deployment_target")
            or _as_mapping(selector.get("objective")).get("target")
            or ""
        ).strip().lower()
        if objective_target == "auto":
            objective_target = "cross_target"
        if objective_target in {"cross_target", "any"} and not cross_target_comparison_eligible:
            return {
                "status": "blocked_stale_selector_cross_target_requires_bilateral_recommendations",
                "recommended_target": None,
                "recommended_candidate_id": None,
                "selected_candidate": None,
                "objective_id": _as_mapping(selector.get("objective")).get("objective_id"),
                "rationale": [
                    "selector reported a unique cross-target deployment candidate, but comparator evidence is not bilateral",
                    (
                        "target-local recommendations are not sufficient for a FPGA-vs-ASIC "
                        "deployment comparison claim"
                    ),
                ],
                "blocker_ids": ["cross_target_requires_fpga_and_asic_recommendations"],
                "target_recommendation_available_count": target_recommendation_available_count,
                "cross_target_comparison_eligible": False,
                "trusted_final_claim": False,
                "deliverable_complete": False,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        assessment = _as_mapping(target_assessments.get(str(selected_target)))
        binding_ready = assessment.get("target_model_binding_ready") is True
        selected_target_blocker_ids = list(assessment.get("blocker_ids", []) or [])
        side_target_blocker_ids = sorted(
            dict.fromkeys(
                str(blocker)
                for target, target_assessment in target_assessments.items()
                if str(target) != str(selected_target)
                for blocker in list(_as_mapping(target_assessment).get("blocker_ids", []) or [])
                if blocker
            )
        )
        side_target_statuses = {
            str(target): {
                "target_model_binding_status": _as_mapping(target_assessment).get("target_model_binding_status"),
                "comparator_recommendation_kind": _as_mapping(target_assessment).get(
                    "comparator_recommendation_kind"
                ),
                "blocker_ids": list(_as_mapping(target_assessment).get("blocker_ids", []) or []),
            }
            for target, target_assessment in target_assessments.items()
            if str(target) != str(selected_target)
        }
        if not binding_ready:
            status = "selected_deployment_recommendation_blocked_by_target_model_binding"
        elif selected_target_blocker_ids:
            status = "selected_deployment_recommendation_blocked_by_selected_target"
        elif side_target_blocker_ids:
            status = "selected_deployment_recommendation_available_with_blocked_side_targets"
        else:
            status = "selected_deployment_recommendation_available"
        rationale = [
            "explicit objective produced a unique selected deployment candidate",
            f"selected target is {selected_target}",
        ]
        if binding_ready:
            rationale.append(f"{selected_target} target-model binding is ready for current evidence")
        if side_target_blocker_ids:
            rationale.append("non-selected deployment targets still have blockers and are not deployment claims")
        if selected_target == "asic":
            rationale.append("FPGA remains a separate claim path and must pass selected-board Vivado hard gates before FPGA deployment claims")
        elif selected_target == "fpga":
            rationale.append("ASIC remains a separate claim path and must pass DC target-library hard gates before ASIC deployment claims")
        return {
            "status": status,
            "recommended_target": selected_target,
            "recommended_candidate_id": selected_candidate_id,
            "selected_candidate": selector.get("selected_candidate"),
            "objective_id": _as_mapping(selector.get("objective")).get("objective_id"),
            "rationale": rationale,
            "blocker_ids": sorted(dict.fromkeys(selected_target_blocker_ids + side_target_blocker_ids)),
            "selected_target_blocker_ids": selected_target_blocker_ids,
            "side_target_blocker_ids": side_target_blocker_ids,
            "side_target_statuses": side_target_statuses,
            "trusted_final_claim": False,
            "deliverable_complete": False,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
    cross = _as_mapping(comparator.get("cross_target_recommendation"))
    blocker_ids = [str(item.get("blocker_id")) for item in _as_rows(selector.get("blockers")) if item.get("blocker_id")]
    if not selector:
        status = "blocked_missing_deployment_selector"
        blocker_ids.append("deployment_selector_required")
    elif selection_status == "blocked_missing_explicit_objective":
        status = "blocked_missing_explicit_objective"
    else:
        status = selection_status or cross.get("status") or "blocked_no_deployment_recommendation"
    return {
        "status": status,
        "recommended_target": None,
        "recommended_candidate_id": None,
        "selected_candidate": None,
        "objective_id": _as_mapping(selector.get("objective")).get("objective_id") if selector else None,
        "rationale": [
            "no single FPGA-vs-ASIC deployment candidate can be recommended without a valid explicit objective and unique selector result"
        ],
        "blocker_ids": sorted(dict.fromkeys(blocker_ids)),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def build_dft_deployment_decision_summary(run_dir: Path) -> Dict[str, Any]:
    """Build a fail-closed deployment decision roll-up from run-local artifacts."""

    run_dir = Path(run_dir)
    source_artifacts = _source_artifacts(run_dir)
    missing_required = sorted(
        key for key, ref in source_artifacts.items() if ref.get("required") is True and ref.get("exists") is not True
    )
    target_selection = _load_json(run_dir / "dft_deployment_target_model_selection.json")
    target_binding = _load_json(run_dir / "dft_deployment_target_model_binding.json")
    ranking = _load_json(run_dir / "dft_hardware_ppa_ranking.json")
    ranking_status = _load_json(run_dir / "dft_hardware_ppa_ranking_status.json")
    hard_gate_status = _load_json(run_dir / "dft_deployment_hard_gate_execution_queue_status.json")
    vivado_part_probe = _load_json(run_dir / "dft_vivado_part_support_probe.json")
    comparator = _load_json(run_dir / "dft_deployment_comparator.json")
    comparator_status = _load_json(run_dir / "dft_deployment_comparator_status.json")
    selector = _load_json(run_dir / "dft_deployment_selector.json")
    selector_status = _load_json(run_dir / "dft_deployment_selector_status.json")
    release_package = _load_json(run_dir / "complete_dse_release_artifact_package.json")
    release_universe_candidate_identity_binding = _release_universe_candidate_identity_binding(
        source_payloads={
            "dft_deployment_target_model_selection": target_selection,
            "dft_deployment_target_model_binding": target_binding,
            "dft_hardware_ppa_ranking": ranking,
            "dft_deployment_hard_gate_execution_queue_status": hard_gate_status,
            "dft_deployment_comparator": comparator,
            "dft_deployment_selector": selector,
        },
        package=release_package,
    )
    target_recommendation_available_count = comparator.get("target_recommendation_available_count")
    if target_recommendation_available_count is None:
        target_recommendation_available_count = comparator_status.get("target_recommendation_available_count")
    if target_recommendation_available_count is None:
        target_recommendation_available_count = sum(
            1
            for item in (
                _as_mapping(comparator.get("fpga_recommendation")),
                _as_mapping(comparator.get("asic_recommendation")),
            )
            if item.get("recommendation_kind") in {"unique_candidate", "best_physical_tie_set"}
        )
    cross_target_comparison_eligible = comparator.get("cross_target_comparison_eligible")
    if cross_target_comparison_eligible is None:
        cross_target_comparison_eligible = comparator_status.get("cross_target_comparison_eligible")
    if cross_target_comparison_eligible is None:
        cross_target_comparison_eligible = target_recommendation_available_count == 2
    deployment_completion_eligible = bool(cross_target_comparison_eligible)
    release_candidate_identity_provenance = _release_candidate_identity_provenance_summary(
        run_dir,
        release_universe_candidate_identity_binding=release_universe_candidate_identity_binding,
    )

    selection_by_target = _selection_row_by_target(target_selection)
    binding_by_target = _binding_row_by_target(target_binding)
    target_assessments = {
        target: _target_assessment(
            target,
            selection_row=selection_by_target.get(target, {}),
            binding_row=binding_by_target.get(target, {}),
            comparator_recommendation=_as_mapping(comparator.get(f"{target}_recommendation")),
            selector=selector,
            vivado_part_probe=vivado_part_probe if target == "fpga" else {},
        )
        for target in ("fpga", "asic")
    }
    best = _best_recommendation(
        selector=selector,
        comparator=comparator,
        target_assessments=target_assessments,
        target_recommendation_available_count=int(target_recommendation_available_count or 0),
        cross_target_comparison_eligible=bool(cross_target_comparison_eligible),
    )
    if (
        release_universe_candidate_identity_binding["status"] == "blocked"
        and best.get("recommended_candidate_id")
    ):
        best = _block_recommendation_for_release_universe_binding(
            best,
            release_universe_candidate_identity_binding,
        )
    if missing_required:
        status = "blocked_missing_required_deployment_artifacts"
    elif best.get("recommended_target"):
        status = "deployment_decision_summary_available"
    else:
        status = "deployment_decision_summary_fail_closed"

    return {
        "schema_version": DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA,
        "generated_at": _now_iso(),
        "status": status,
        "source_artifacts": source_artifacts,
        "missing_required_artifacts": missing_required,
        "objective_summary": _as_mapping(selector.get("objective")),
        "target_model_selection_status": target_selection.get("status"),
        "target_model_binding_status": target_binding.get("status"),
        "target_model_binding_blocker_ids": list(target_binding.get("blocker_ids", []) or []),
        "vivado_part_support_probe_status": vivado_part_probe.get("status"),
        "vivado_part_support_probe_requested_parts": list(vivado_part_probe.get("requested_parts", []) or []),
        "vivado_part_support_probe_supported_parts": list(vivado_part_probe.get("supported_parts", []) or []),
        "vivado_part_support_probe_missing_requested_parts": list(
            vivado_part_probe.get("missing_requested_parts", []) or []
        ),
        "hard_gate_queue_status": hard_gate_status.get("queue_status") or hard_gate_status.get("status"),
        "hardware_ppa_ranking_status": ranking.get("status") or ranking_status.get("ranking_status"),
        "deployment_comparator_status": comparator.get("deployment_comparison_status")
        or comparator_status.get("deployment_comparison_status"),
        "target_recommendation_available_count": target_recommendation_available_count,
        "cross_target_comparison_eligible": bool(cross_target_comparison_eligible),
        "hardware_completion_eligible_for_deployment_comparison": bool(deployment_completion_eligible),
        "deployment_selector_status": selector.get("selection_status") or selector_status.get("selection_status"),
        "selected_deployment_target": selector.get("selected_deployment_target"),
        "selected_candidate_id": selector.get("selected_candidate_id"),
        "release_universe_candidate_identity_binding": release_universe_candidate_identity_binding,
        **release_candidate_identity_provenance,
        "best_current_deployment_recommendation": best,
        "fpga_deployment_assessment": target_assessments["fpga"],
        "asic_deployment_assessment": target_assessments["asic"],
        "target_assessments": target_assessments,
        "trusted_final_claim": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_decision_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate summary consistency while preserving fail-closed claims."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("deployment_decision_summary_must_not_mark_deliverable_complete")
    if payload.get("trusted_final_claim") is True:
        errors.append("deployment_decision_summary_must_not_mark_trusted_final_claim")
    best = _as_mapping(payload.get("best_current_deployment_recommendation"))
    if best.get("deliverable_complete") is True or best.get("trusted_final_claim") is True:
        errors.append("best_recommendation_must_remain_fail_closed")
    provenance_status = str(payload.get("release_candidate_identity_provenance_status") or "")
    if provenance_status not in {"passed", "blocked", "unbound"}:
        errors.append("release_candidate_identity_provenance_status_invalid_or_missing")
    release_binding = _as_mapping(payload.get("release_universe_candidate_identity_binding"))
    release_binding_status = str(release_binding.get("status") or "")
    if release_binding_status not in {"passed", "blocked", "unbound"}:
        errors.append("release_universe_candidate_identity_binding_status_invalid_or_missing")
    if (
        release_binding_status == "blocked"
        and best.get("recommended_candidate_id")
    ):
        errors.append("blocked_release_universe_binding_must_clear_recommendation")
    if (
        payload.get(
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity"
        )
        is True
        and provenance_status != "passed"
    ):
        errors.append("trusted_release_candidate_identity_requires_passed_provenance")
    if (
        payload.get(
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity"
        )
        is True
        and release_binding_status != "passed"
    ):
        errors.append("trusted_release_candidate_identity_requires_passed_release_universe_binding")
    objective = _as_mapping(payload.get("objective_summary"))
    objective_target = str(objective.get("deployment_target") or objective.get("target") or "").strip().lower()
    if objective_target == "auto":
        objective_target = "cross_target"
    if (
        best.get("recommended_target")
        and objective_target in {"cross_target", "any"}
        and payload.get("cross_target_comparison_eligible") is not True
    ):
        errors.append("cross_target_recommendation_requires_bilateral_comparator_evidence")
    selected_target = payload.get("selected_deployment_target")
    selected_candidate = payload.get("selected_candidate_id")
    if selected_candidate and selected_target not in {"fpga", "asic"}:
        errors.append("selected_candidate_requires_fpga_or_asic_target")
    assessments = _as_mapping(payload.get("target_assessments"))
    for target in ("fpga", "asic"):
        assessment = _as_mapping(assessments.get(target))
        if not assessment:
            errors.append(f"missing_{target}_assessment")
            continue
        if assessment.get("deliverable_complete") is True:
            errors.append(f"{target}_assessment_must_not_mark_deliverable_complete")
    return {
        "schema_version": DFT_DEPLOYMENT_DECISION_SUMMARY_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_decision_summary(run_dir: Path) -> Dict[str, Any]:
    """Write deployment decision summary, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = build_dft_deployment_decision_summary(run_dir)
    validation = validate_dft_deployment_decision_summary(summary)
    write_json(run_dir / "dft_deployment_decision_summary.json", summary)
    write_json(run_dir / "dft_deployment_decision_summary_validation.json", validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_DECISION_SUMMARY_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "decision_summary_status": summary.get("status"),
        "best_recommendation_status": summary.get("best_current_deployment_recommendation", {}).get("status"),
        "recommended_target": summary.get("best_current_deployment_recommendation", {}).get("recommended_target"),
        "recommended_candidate_id": summary.get("best_current_deployment_recommendation", {}).get(
            "recommended_candidate_id"
        ),
        "selected_target_blocker_ids": list(
            summary.get("best_current_deployment_recommendation", {}).get("selected_target_blocker_ids", []) or []
        ),
        "side_target_blocker_ids": list(
            summary.get("best_current_deployment_recommendation", {}).get("side_target_blocker_ids", []) or []
        ),
        "fpga_target_model_binding_status": summary.get("fpga_deployment_assessment", {}).get(
            "target_model_binding_status"
        ),
        "asic_target_model_binding_status": summary.get("asic_deployment_assessment", {}).get(
            "target_model_binding_status"
        ),
        "target_recommendation_available_count": summary.get("target_recommendation_available_count"),
        "cross_target_comparison_eligible": summary.get("cross_target_comparison_eligible"),
        "hardware_completion_eligible_for_deployment_comparison": summary.get(
            "hardware_completion_eligible_for_deployment_comparison"
        ),
        "release_candidate_identity_provenance_status": summary.get(
            "release_candidate_identity_provenance_status"
        ),
        "release_candidate_identity_provenance_blocker_ids": list(
            summary.get("release_candidate_identity_provenance_blocker_ids", []) or []
        ),
        "release_universe_candidate_identity_binding_status": summary.get(
            "release_universe_candidate_identity_binding", {}
        ).get("status"),
        "release_universe_candidate_identity_binding_blocker_ids": list(
            summary.get("release_universe_candidate_identity_binding", {}).get(
                "blocker_ids", []
            )
            or []
        ),
        "release_universe_candidate_identity_binding_extra_candidate_ids": list(
            summary.get("release_universe_candidate_identity_binding", {}).get(
                "extra_candidate_ids", []
            )
            or []
        ),
        "release_candidate_identity_provenance_package_exists": summary.get(
            "release_candidate_identity_provenance_package_exists"
        ),
        "release_candidate_identity_provenance_package_status": summary.get(
            "release_candidate_identity_provenance_package_status"
        ),
        "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity": summary.get(
            "release_candidate_identity_provenance_trusted_for_release_package_candidate_identity"
        ),
        "release_candidate_identity_provenance_claim_boundary": summary.get(
            "release_candidate_identity_provenance_claim_boundary"
        ),
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_deployment_decision_summary_status.json", status)
    return {
        "schema_version": "dse.dft.deployment_decision_summary_artifact_status.v1",
        "status": status["status"],
        "decision_summary_status": summary.get("status"),
        "best_recommendation_status": status["best_recommendation_status"],
        "recommended_target": status["recommended_target"],
        "recommended_candidate_id": status["recommended_candidate_id"],
        "selected_target_blocker_ids": status["selected_target_blocker_ids"],
        "side_target_blocker_ids": status["side_target_blocker_ids"],
        "target_recommendation_available_count": status["target_recommendation_available_count"],
        "cross_target_comparison_eligible": status["cross_target_comparison_eligible"],
        "hardware_completion_eligible_for_deployment_comparison": status[
            "hardware_completion_eligible_for_deployment_comparison"
        ],
        "release_candidate_identity_provenance_status": status[
            "release_candidate_identity_provenance_status"
        ],
        "release_candidate_identity_provenance_blocker_ids": status[
            "release_candidate_identity_provenance_blocker_ids"
        ],
        "release_universe_candidate_identity_binding_status": status[
            "release_universe_candidate_identity_binding_status"
        ],
        "release_universe_candidate_identity_binding_blocker_ids": status[
            "release_universe_candidate_identity_binding_blocker_ids"
        ],
        "release_candidate_identity_provenance_package_exists": status[
            "release_candidate_identity_provenance_package_exists"
        ],
        "release_candidate_identity_provenance_package_status": status[
            "release_candidate_identity_provenance_package_status"
        ],
        "dft_deployment_decision_summary": str(run_dir / "dft_deployment_decision_summary.json"),
        "dft_deployment_decision_summary_validation": str(
            run_dir / "dft_deployment_decision_summary_validation.json"
        ),
        "dft_deployment_decision_summary_status": str(run_dir / "dft_deployment_decision_summary_status.json"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_DEPLOYMENT_DECISION_SUMMARY_SCHEMA",
    "DFT_DEPLOYMENT_DECISION_SUMMARY_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_DECISION_SUMMARY_VALIDATION_SCHEMA",
    "build_dft_deployment_decision_summary",
    "validate_dft_deployment_decision_summary",
    "write_dft_deployment_decision_summary",
]
