#!/usr/bin/env python3
"""Current-goal Done-when 4-6 audit for the DFT/QE release lane.

This module is intentionally DFT/current-goal scoped.  It observes the generic
Complete-DSE release subset and the DFT/QE six-SCF obligations, but it does not
add workload facts to stable core candidate identity.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.complete_dse_search_space import (
    DEFAULT_FROZEN_WORKLOAD_CASE_COUNT,
    IDENTITY_LAYER_KEYS,
    NON_IDENTITY_FIELDS,
    build_release_subset_manifest,
    validate_candidate_workflow_deployment_target_matrix,
    write_complete_dse_search_space_artifacts,
)
from dse_v2.codesign.dft_scf_workstreams import (
    STRICT_BUNDLE_REQUIRED_ASSETS,
    STRICT_DFT_QE_WORKLOAD_CLASSES,
)
from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.reference_workloads.dft_scf_six_class_suite import (
    validate_dft_scf_six_class_bundle_manifest,
)


COMPLETE_DSE_DONE_WHEN_4_6_AUDIT_SCHEMA = (
    "dse.dft.current_goal.complete_dse_done_when_4_6_audit.v1"
)
COMPLETE_DSE_DONE_WHEN_4_6_STATUS_SCHEMA = (
    "dse.dft.current_goal.complete_dse_done_when_4_6_audit_status.v1"
)
COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_SCHEMA = (
    "dse.dft.current_goal.complete_dse_release_artifact_package.v1"
)
COMPLETE_DSE_RELEASE_ARTIFACT_HASH_MANIFEST_SCHEMA = (
    "dse.dft.current_goal.complete_dse_release_artifact_hash_manifest.v1"
)
COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_STATUS_SCHEMA = (
    "dse.dft.current_goal.complete_dse_release_artifact_package_status.v1"
)
COMPLETE_DSE_RELEASE_CHECKLIST_TRACEABILITY_SCHEMA = (
    "dse.dft.current_goal.complete_dse_release_checklist_traceability.v1"
)

REPORT_NAME = "complete_dse_done_when_4_6_audit.json"
STATUS_NAME = "status.json"
RELEASE_ARTIFACT_PACKAGE_NAME = "complete_dse_release_artifact_package.json"
RELEASE_ARTIFACT_HASH_MANIFEST_NAME = "complete_dse_release_artifact_hash_manifest.json"

STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES = (
    "search_space/release_subset_manifest.json",
    "candidate_workflow_deployment_target_matrix.json",
    "audit/complete_dse_done_when_4_6_audit.json",
    "audit/status.json",
    "search_space/candidate_generation_report.json",
    "search_space/freeze_gate_verdict.json",
    "search_space/status.json",
)
CURRENT_GOAL_CHECKLIST_TRACEABILITY_ALIASES = (
    (
        "complete_dse_done_when_4_6_audit.json",
        "audit/complete_dse_done_when_4_6_audit.json",
        "done_when_4_6_audit",
    ),
    ("status.json", "audit/status.json", "done_when_4_6_audit_status"),
    (
        "release_universe_manifest.json",
        "search_space/release_subset_manifest.json",
        "release_universe_manifest",
    ),
    (
        "candidate_generation_report.json",
        "search_space/candidate_generation_report.json",
        "candidate_generation_report",
    ),
    (
        "candidate_workflow_deployment_target_matrix.json",
        "candidate_workflow_deployment_target_matrix.json",
        "candidate_workflow_deployment_target_matrix",
    ),
)

_BARRIER_NAME = "three-run-barrier-integration-20260526T021120+0800.md"
_PREFLIGHT_NAME = "three-run-dispatch-preflight-20260526T021512+0800.md"

_CLAIM_BOUNDARY = (
    "Done-when 4-6 audit only. This report records spec, workload-input, "
    "and release-universe blockers; it cannot claim hardware winners, trusted "
    "speedup, FPGA/ASIC closure, or deliverable completion."
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_ref(label: str, path: Path | None, *, required: bool = True) -> Dict[str, Any]:
    if path is None:
        return {
            "label": label,
            "path": None,
            "required": required,
            "exists": False,
            "sha256": None,
            "hash_algorithm": "sha256",
        }
    path = Path(path)
    exists = path.is_file()
    return {
        "label": label,
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": _sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_mapping(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _package_artifact_ref(
    package_root: Path,
    canonical_name: str,
    *,
    artifact_role: str,
    required: bool = True,
) -> Dict[str, Any]:
    path = package_root / canonical_name
    exists = path.is_file()
    return {
        "canonical_name": canonical_name,
        "artifact_role": artifact_role,
        "path": str(path),
        "required": required,
        "exists": exists,
        "status": "present_hash_valid" if exists else "missing_required" if required else "not_attached",
        "sha256": _sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _artifact_status_metadata(payload: Mapping[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for key in (
        "status",
        "evidence_status",
        "complete",
        "completion_complete",
        "deliverable_complete",
        "valid",
        "validation_valid",
        "projection_only",
        "smoke_only",
        "stale",
        "forged",
        "exists",
    ):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def _status_is_nonclaimable(status: Any) -> bool:
    status_text = str(status or "").lower()
    if status_text in {"", "passed", "proven", "present_hash_valid"}:
        return False
    return (
        status_text in {"partial", "incomplete", "blocked", "failed", "missing_required"}
        or "projection_only" in status_text
        or "tool_unavailable" in status_text
        or "smoke_only" in status_text
        or "forged" in status_text
        or "invalid" in status_text
        or "stale" in status_text
    )


def _current_goal_checklist_traceability(
    *,
    stable_artifacts: list[Mapping[str, Any]],
    audit_payload: Mapping[str, Any],
    audit_status: Mapping[str, Any],
    release_subset: Mapping[str, Any],
    generation_report: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> Dict[str, Any]:
    stable_by_name = {
        str(artifact.get("canonical_name") or ""): dict(artifact)
        for artifact in stable_artifacts
        if artifact.get("canonical_name")
    }
    payload_by_alias: Dict[str, Mapping[str, Any]] = {
        "complete_dse_done_when_4_6_audit.json": audit_payload,
        "status.json": audit_status,
        "release_universe_manifest.json": release_subset,
        "candidate_generation_report.json": generation_report,
        "candidate_workflow_deployment_target_matrix.json": matrix,
    }
    artifact_refs: Dict[str, Dict[str, Any]] = {}
    artifact_hashes: Dict[str, str] = {}
    hash_binding_blockers: list[str] = []
    source_status_blockers: list[str] = []
    for alias, canonical_name, artifact_role in CURRENT_GOAL_CHECKLIST_TRACEABILITY_ALIASES:
        source = stable_by_name.get(canonical_name, {})
        payload = payload_by_alias.get(alias, {})
        ref_blockers: list[str] = []
        if source.get("exists") is not True:
            ref_blockers.append("missing_hash_bound_source_artifact")
        digest = source.get("sha256")
        if not digest:
            ref_blockers.append("missing_source_sha256")
        source_status = payload.get("status") or source.get("status")
        if _status_is_nonclaimable(source_status):
            source_status_blockers.append(f"{alias}:source_status:{source_status}")
        ref = {
            "path": canonical_name,
            "source_canonical_name": canonical_name,
            "package_artifact_path": source.get("path"),
            "artifact_role": artifact_role,
            "required": True,
            "exists": bool(source.get("exists") is True),
            "sha256": str(digest) if digest else None,
            "hash_algorithm": str(source.get("hash_algorithm") or "sha256"),
            "status": str(source_status or source.get("status") or "missing_required"),
            "source_status": str(source_status or ""),
            "package_artifact_status": source.get("status"),
            "hash_binding_blockers": ref_blockers,
        }
        ref.update(_artifact_status_metadata(payload))
        artifact_refs[alias] = ref
        if digest:
            artifact_hashes[alias] = str(digest)
        hash_binding_blockers.extend(f"{alias}:{blocker}" for blocker in ref_blockers)

    hash_binding_status = "blocked" if hash_binding_blockers else "passed"
    status = (
        "blocked"
        if hash_binding_blockers
        else "partial"
        if source_status_blockers
        else "passed"
    )
    return {
        "schema_version": COMPLETE_DSE_RELEASE_CHECKLIST_TRACEABILITY_SCHEMA,
        "status": status,
        "hash_binding_status": hash_binding_status,
        "artifact_alias_count": len(CURRENT_GOAL_CHECKLIST_TRACEABILITY_ALIASES),
        "artifact_refs": artifact_refs,
        "artifact_hashes": artifact_hashes,
        "hash_binding_blockers": sorted(set(hash_binding_blockers)),
        "source_status_blockers": sorted(set(source_status_blockers)),
        "source": "complete_dse_release_artifact_package_stable_artifacts",
        "deliverable_complete": False,
        "claim_boundary": (
            "Checklist traceability binds current-goal artifact aliases to "
            "package-local sha256 refs. It preserves source statuses, so partial, "
            "blocked, projection-only, invalid, or missing artifacts remain "
            "non-claimable for the final checklist."
        ),
    }


def _strict_six_class_bundle_linkage(
    manifest_path: Path | None,
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    artifact = _source_ref(
        "strict_qe_release_bundle_manifest",
        manifest_path,
        required=False,
    )
    linkage: Dict[str, Any] = {
        "supplied": manifest_path is not None,
        "artifact": artifact,
        "required_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "present_class_ids": [],
        "case_count": 0,
        "admitted": False,
        "final_real_qe_evidence": False,
        "validation_status": None,
        "schema_version": None,
        "claim_boundary": (
            "Strict six-class bundle linkage records descriptor/runnable input "
            "coverage only. It remains non-final unless the bundle carries "
            "real QE reference-output admission."
        ),
    }
    blockers: list[Dict[str, Any]] = []
    if manifest_path is None:
        blockers.append(
            {
                "id": "strict_qe_release_lane_bundle_not_supplied_to_audit",
                "reason": "no strict six-class QE bundle manifest is linked into the release package",
            }
        )
        return linkage, blockers

    if artifact["exists"] is not True:
        blockers.append(
            {
                "id": "strict_qe_release_bundle_manifest_missing",
                "path": str(manifest_path),
                "reason": "supplied strict six-class bundle manifest does not exist",
            }
        )
        return linkage, blockers

    manifest = _load_json_mapping(Path(manifest_path))
    validation = validate_dft_scf_six_class_bundle_manifest(
        Path(manifest_path),
        base_dir=Path(manifest_path).parent,
    )
    final_real_qe_evidence = bool(
        manifest.get("final_real_qe_evidence") is True
        and validation.get("admitted") is True
    )
    linkage.update(
        {
            "schema_version": manifest.get("schema_version"),
            "case_count": manifest.get("case_count", 0),
            "present_class_ids": list(manifest.get("workload_classes") or []),
            "validation_status": validation.get("status"),
            "admitted": bool(validation.get("admitted") is True),
            "final_real_qe_evidence": final_real_qe_evidence,
        }
    )
    if validation.get("status") != "passed" or not final_real_qe_evidence:
        blockers.append(
            {
                "id": "strict_qe_release_bundle_not_final_real_qe_evidence",
                "reason": (
                    "the linked strict six-class bundle is present, but it is "
                    "not final admitted real-QE evidence for release completion"
                ),
                "validation_status": validation.get("status"),
                "final_real_qe_evidence": manifest.get("final_real_qe_evidence"),
            }
        )
    return linkage, blockers


def _release_candidate_identity_provenance(
    *,
    deployment_search_candidate_id_audit: Mapping[str, Any],
    decision_summary_inputs: Mapping[str, Any],
    strict_six_class_bundle_linkage: Mapping[str, Any],
    strict_six_class_bundle_blockers: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    decision_summary_binding_status = str(
        decision_summary_inputs.get("binding_status") or decision_summary_inputs.get("status") or "unbound"
    )
    decision_summary_bound = bool(
        decision_summary_inputs.get("status") == "bound"
        and decision_summary_binding_status == "bound_to_supplied_artifact"
    )
    bundle_supplied = bool(strict_six_class_bundle_linkage.get("supplied") is True)
    bundle_admitted = bool(strict_six_class_bundle_linkage.get("admitted") is True)
    bundle_final_real_qe_evidence = bool(
        strict_six_class_bundle_linkage.get("final_real_qe_evidence") is True
    )
    bundle_binding_status = (
        "bound_final_real_qe_evidence"
        if bundle_supplied and bundle_admitted and bundle_final_real_qe_evidence
        else "unbound_no_strict_qe_release_bundle_manifest"
        if not bundle_supplied
        else "blocked_strict_qe_release_bundle_not_final_real_qe_evidence"
    )
    blocker_ids = sorted(
        {
            *(
                str(blocker_id)
                for blocker_id in deployment_search_candidate_id_audit.get("blocker_ids", []) or []
                if blocker_id
            ),
            *(
                str(blocker_id)
                for blocker_id in decision_summary_inputs.get("blocker_ids", []) or []
                if blocker_id
            ),
            *(
                str(blocker.get("id") or "")
                for blocker in strict_six_class_bundle_blockers
                if blocker.get("id")
            ),
        }
    )
    canonical_bundle_bound = (
        bundle_supplied and bundle_admitted and bundle_final_real_qe_evidence
    )
    status = "passed" if decision_summary_bound and canonical_bundle_bound else "blocked"
    trusted_for_release_package_candidate_identity = (
        status == "passed"
        and bool(deployment_search_candidate_id_audit.get("status") == "passed")
    )
    payload: Dict[str, Any] = {
        "schema_version": "dse.dft.current_goal.release_candidate_identity_provenance.v1",
        "status": status,
        "candidate_source": "deployment_decision_summary",
        "deployment_search_candidate_id_audit_status": deployment_search_candidate_id_audit.get("status"),
        "deployment_decision_summary_binding_status": decision_summary_binding_status,
        "deployment_decision_summary_blocker_ids": list(
            decision_summary_inputs.get("blocker_ids", []) or []
        ),
        "strict_qe_release_bundle_binding_status": bundle_binding_status,
        "strict_qe_release_bundle_blocker_ids": [
            str(blocker.get("id") or "")
            for blocker in strict_six_class_bundle_blockers
            if blocker.get("id")
        ],
        "canonical_bundle_bound": canonical_bundle_bound,
        "trusted_for_release_package_candidate_identity": trusted_for_release_package_candidate_identity,
        "blocker_ids": blocker_ids,
        "claim_boundary": (
            "Release-package candidate identity provenance is a fail-closed "
            "binding audit. It only reports whether the canonical deployment "
            "decision summary and strict release-lane bundle are bound; it "
            "is not FPGA/ASIC PPA evidence and does not imply deliverable "
            "completion."
        ),
    }
    payload["provenance_hash"] = stable_json_hash(
        {key: value for key, value in payload.items() if key != "provenance_hash"}
    )
    return payload


def _missing_required_artifacts(artifacts: list[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [
        {
            "id": "missing_required_artifact",
            "label": str(artifact.get("label") or ""),
            "path": artifact.get("path"),
            "reason": "required audit source artifact is missing",
        }
        for artifact in artifacts
        if artifact.get("required") is True and artifact.get("exists") is not True
    ]


def _repo_file(repo_root: Path, label: str, relative_path: str, *, required: bool = True) -> Dict[str, Any]:
    return _source_ref(label, repo_root / relative_path, required=required)


def _default_control_root(repo_root: Path) -> Path:
    repo_root = Path(repo_root).resolve()
    if _has_default_control_artifacts(repo_root):
        return repo_root
    parent = repo_root.parent
    if parent.name.endswith(".omx-worktrees"):
        sibling = parent.with_name(parent.name.removesuffix(".omx-worktrees"))
        if sibling.is_dir() and _has_default_control_artifacts(sibling):
            return sibling
    if (repo_root / ".omx" / "context").is_dir():
        return repo_root
    return repo_root


def _has_default_control_artifacts(root: Path) -> bool:
    return (
        (root / "docs" / "goal.md").is_file()
        and (root / ".omx" / "context" / _BARRIER_NAME).is_file()
        and (root / ".omx" / "context" / _PREFLIGHT_NAME).is_file()
    )


def _latest_match(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def _status_from(blockers: list[Mapping[str, Any]], *, partial: bool = False) -> str:
    if blockers:
        return "blocked"
    if partial:
        return "partial"
    return "proven"


def _release_package_replay_cli(
    *,
    out_dir: Path,
    repo_root: Path,
    control_root: Path,
    goal_path: Path | None = None,
    barrier_path: Path | None = None,
    preflight_path: Path | None = None,
    north_star_path: Path | None = None,
    deployment_decision_summary_path: Path | None = None,
    strict_qe_release_bundle_manifest_path: Path | None = None,
    target_evidence_ledger_path: Path | None = None,
    target_evidence_ledger_validation_path: Path | None = None,
    target_evidence_ledger_status_path: Path | None = None,
) -> Dict[str, Any]:
    entrypoint = "dse_v2/scripts/dse/build_complete_dse_release_artifact_package.py"
    argv = [
        "python3",
        entrypoint,
        "--out",
        str(out_dir),
        "--repo-root",
        str(repo_root),
        "--control-root",
        str(control_root),
    ]
    optional_paths = (
        ("--goal-path", goal_path),
        ("--barrier-path", barrier_path),
        ("--preflight-path", preflight_path),
        ("--north-star-path", north_star_path),
        ("--deployment-decision-summary-path", deployment_decision_summary_path),
        (
            "--strict-qe-release-bundle-manifest-path",
            strict_qe_release_bundle_manifest_path,
        ),
        ("--target-evidence-ledger-path", target_evidence_ledger_path),
        (
            "--target-evidence-ledger-validation-path",
            target_evidence_ledger_validation_path,
        ),
        ("--target-evidence-ledger-status-path", target_evidence_ledger_status_path),
    )
    for flag, path in optional_paths:
        if path is not None:
            argv.extend([flag, str(path)])
    payload = {
        "entrypoint": entrypoint,
        "cwd": str(repo_root),
        "argv": argv,
        "command": " ".join(shlex.quote(part) for part in argv),
        "claim_boundary": (
            "Replay CLI regenerates the release package and hash manifest from "
            "the same package/control roots. It is provenance only, not FPGA, "
            "ASIC, QE, or deliverable-complete evidence."
        ),
    }
    payload["argv_hash"] = stable_json_hash(
        {"cwd": payload["cwd"], "argv": payload["argv"]}
    )
    return payload


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value is not None and str(value)]


def _deployment_search_candidate_id_audit(
    *,
    release_subset: Mapping[str, Any],
    generation_report: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> Dict[str, Any]:
    release_candidate_ids = _string_list(release_subset.get("legal_candidate_ids"))
    legal_candidate_set = set(release_candidate_ids)
    candidates = [
        row
        for row in release_subset.get("candidates", []) or []
        if isinstance(row, Mapping)
    ]
    recomputed_candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if candidate.get("legal", True) is True and candidate.get("candidate_id")
    ]
    matrix_id_set = {
        str(row.get("candidate_id") or "")
        for row in matrix.get("rows", []) or []
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    matrix_candidate_ids = [
        candidate_id for candidate_id in release_candidate_ids if candidate_id in matrix_id_set
    ]
    contract = generation_report.get("recommendation_candidate_input_contract", {})
    contract = contract if isinstance(contract, Mapping) else {}
    contract_candidate_ids = _string_list(contract.get("candidate_ids"))

    manual_candidate_id_blockers: list[Dict[str, Any]] = []
    if contract.get("candidate_source") != "release_subset_manifest.legal_candidate_ids":
        manual_candidate_id_blockers.append(
            {
                "id": "recommendation_candidate_source_not_release_subset",
                "candidate_source": contract.get("candidate_source"),
            }
        )
    if contract.get("fixed_or_manual_top_k_seed_source_allowed") is not False:
        manual_candidate_id_blockers.append(
            {
                "id": "fixed_or_manual_top_k_seed_source_not_fail_closed",
                "fixed_or_manual_top_k_seed_source_allowed": contract.get(
                    "fixed_or_manual_top_k_seed_source_allowed"
                ),
            }
        )
    if release_candidate_ids != recomputed_candidate_ids:
        manual_candidate_id_blockers.append(
            {
                "id": "legal_candidate_ids_not_recomputed_from_release_universe",
                "declared_count": len(release_candidate_ids),
                "recomputed_count": len(recomputed_candidate_ids),
            }
        )
    missing_matrix_candidate_ids = [
        candidate_id
        for candidate_id in release_candidate_ids
        if candidate_id not in matrix_id_set
    ]
    extra_matrix_candidate_ids = sorted(matrix_id_set - legal_candidate_set)
    if missing_matrix_candidate_ids or extra_matrix_candidate_ids:
        manual_candidate_id_blockers.append(
            {
                "id": "matrix_candidate_ids_not_bound_to_release_subset",
                "missing_count": len(missing_matrix_candidate_ids),
                "extra_count": len(extra_matrix_candidate_ids),
                "missing_candidate_ids": missing_matrix_candidate_ids[:20],
                "extra_candidate_ids": extra_matrix_candidate_ids[:20],
            }
        )
    if contract_candidate_ids and contract_candidate_ids != release_candidate_ids:
        manual_candidate_id_blockers.append(
            {
                "id": "recommendation_contract_candidate_ids_not_release_subset",
                "contract_candidate_count": len(contract_candidate_ids),
                "release_candidate_count": len(release_candidate_ids),
            }
        )

    payload = {
        "schema_version": "dse.dft.current_goal.deployment_search_candidate_id_audit.v1",
        "status": "passed" if not manual_candidate_id_blockers else "blocked",
        "candidate_source": "release_subset_manifest.legal_candidate_ids",
        "candidate_ids": release_candidate_ids,
        "candidate_count": len(release_candidate_ids),
        "matrix_candidate_ids": matrix_candidate_ids,
        "matrix_candidate_count": len(matrix_candidate_ids),
        "extra_matrix_candidate_ids": extra_matrix_candidate_ids,
        "missing_matrix_candidate_ids": missing_matrix_candidate_ids,
        "contract_candidate_ids": contract_candidate_ids,
        "candidate_ids_recomputed_from_release_universe": (
            release_candidate_ids == recomputed_candidate_ids
        ),
        "recommendation_candidate_input_contract_source": contract.get(
            "candidate_source"
        ),
        "fixed_or_manual_candidate_completion_claim_allowed": False,
        "top_k_or_representative_completion_allowed": False,
        "manual_candidate_id_blockers": manual_candidate_id_blockers,
        "claim_boundary": (
            "This audit binds deployment/search recommendation inputs to the "
            "reproducible release subset. It detects manual, Top-K, or mismatched "
            "candidate-ID sources but does not provide hardware PPA evidence."
        ),
    }
    payload["audit_hash"] = stable_json_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    return payload


def _unique_nonempty_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _is_candidate_id_key(key: str) -> bool:
    return (
        key == "candidate_id"
        or key.endswith("_candidate_id")
        or key == "candidate_ids"
        or key.endswith("_candidate_ids")
    )


def _decision_summary_candidate_id_refs(
    payload: Any,
    *,
    path: str = "$",
) -> list[Dict[str, str]]:
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
                                _decision_summary_candidate_id_refs(
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
            refs.extend(_decision_summary_candidate_id_refs(value, path=child_path))
        return refs
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            refs.extend(_decision_summary_candidate_id_refs(item, path=f"{path}[{index}]"))
    return refs


def _decision_summary_candidate_ids(
    payload: Mapping[str, Any],
) -> tuple[list[str], list[Dict[str, str]]]:
    refs = _decision_summary_candidate_id_refs(payload)
    candidate_ids = _unique_nonempty_strings([ref.get("candidate_id") for ref in refs])
    return candidate_ids, refs


def _decision_summary_candidate_id_audit(
    *,
    decision_summary: Mapping[str, Any],
    release_subset: Mapping[str, Any],
) -> Dict[str, Any]:
    release_candidate_ids = _string_list(release_subset.get("legal_candidate_ids"))
    release_candidate_set = set(release_candidate_ids)
    candidate_ids, candidate_id_refs = _decision_summary_candidate_ids(decision_summary)
    extra_candidate_ids = [
        candidate_id for candidate_id in candidate_ids if candidate_id not in release_candidate_set
    ]
    blocker_ids = (
        ["decision_summary_candidate_ids_not_in_release_subset"]
        if extra_candidate_ids
        else []
    )
    payload = {
        "schema_version": "dse.dft.current_goal.decision_summary_candidate_id_audit.v1",
        "status": "blocked" if blocker_ids else "passed",
        "candidate_source": "deployment_decision_summary",
        "release_candidate_source": "release_subset_manifest.legal_candidate_ids",
        "candidate_ids": candidate_ids,
        "candidate_id_refs": candidate_id_refs,
        "candidate_count": len(candidate_ids),
        "release_candidate_count": len(release_candidate_ids),
        "candidate_ids_bound_to_release_universe": not extra_candidate_ids,
        "extra_candidate_ids": extra_candidate_ids,
        "missing_candidate_ids": [],
        "blocker_ids": blocker_ids,
        "claim_boundary": (
            "Decision-summary candidate IDs are accepted only when they are "
            "members of the frozen release universe. This audit is identity "
            "provenance only; it is not FPGA/ASIC PPA evidence."
        ),
    }
    payload["audit_hash"] = stable_json_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    return payload


def _decision_summary_inputs(
    deployment_decision_summary_path: Path | None,
    *,
    release_subset: Mapping[str, Any],
) -> Dict[str, Any]:
    ref = _source_ref(
        "deployment_decision_summary",
        deployment_decision_summary_path,
        required=False,
    )
    payload = (
        _load_json_mapping(Path(deployment_decision_summary_path))
        if ref.get("exists") is True and deployment_decision_summary_path is not None
        else {}
    )
    ref.update(_artifact_status_metadata(payload))
    if deployment_decision_summary_path is None:
        ref["status"] = "unbound"
        blocker_ids = ["deployment_decision_summary_not_bound"]
        candidate_audit = {
            "schema_version": "dse.dft.current_goal.decision_summary_candidate_id_audit.v1",
            "status": "unbound",
            "candidate_source": "deployment_decision_summary",
            "release_candidate_source": "release_subset_manifest.legal_candidate_ids",
            "candidate_ids": [],
            "candidate_id_refs": [],
            "candidate_count": 0,
            "release_candidate_count": len(_string_list(release_subset.get("legal_candidate_ids"))),
            "candidate_ids_bound_to_release_universe": False,
            "extra_candidate_ids": [],
            "missing_candidate_ids": [],
            "blocker_ids": blocker_ids,
            "claim_boundary": (
                "No deployment decision-summary artifact is bound, so no "
                "summary candidate IDs can be trusted for release-package claims."
            ),
        }
        candidate_audit["audit_hash"] = stable_json_hash(
            {key: value for key, value in candidate_audit.items() if key != "audit_hash"}
        )
        return {
            "schema_version": "dse.dft.current_goal.decision_summary_inputs.v1",
            "status": "unbound",
            "binding_status": "unbound_no_deployment_decision_summary_artifact",
            "deployment_decision_summary": ref,
            "deployment_decision_summary_candidate_id_audit": candidate_audit,
            "supplied_input_count": 0,
            "blocker_ids": blocker_ids,
            "claim_boundary": (
                "Decision-summary inputs are hash-bound package references only. "
                "They do not upgrade target recommendations, Vivado/DC hard gates, "
                "or deliverable completion."
            ),
        }
    if ref.get("exists") is not True:
        ref["status"] = "missing_supplied_artifact"
        blocker_ids = ["deployment_decision_summary_supplied_path_missing"]
        candidate_audit = {
            "schema_version": "dse.dft.current_goal.decision_summary_candidate_id_audit.v1",
            "status": "blocked",
            "candidate_source": "deployment_decision_summary",
            "release_candidate_source": "release_subset_manifest.legal_candidate_ids",
            "candidate_ids": [],
            "candidate_id_refs": [],
            "candidate_count": 0,
            "release_candidate_count": len(_string_list(release_subset.get("legal_candidate_ids"))),
            "candidate_ids_bound_to_release_universe": False,
            "extra_candidate_ids": [],
            "missing_candidate_ids": [],
            "blocker_ids": blocker_ids,
            "claim_boundary": (
                "The supplied deployment decision-summary path is missing, so "
                "the release package cannot bind recommendation candidate IDs."
            ),
        }
        candidate_audit["audit_hash"] = stable_json_hash(
            {key: value for key, value in candidate_audit.items() if key != "audit_hash"}
        )
        return {
            "schema_version": "dse.dft.current_goal.decision_summary_inputs.v1",
            "status": "blocked",
            "binding_status": "blocked_supplied_artifact_missing",
            "deployment_decision_summary": ref,
            "deployment_decision_summary_candidate_id_audit": candidate_audit,
            "supplied_input_count": 0,
            "blocker_ids": blocker_ids,
            "claim_boundary": (
                "Decision-summary inputs are hash-bound package references only. "
                "They do not upgrade target recommendations, Vivado/DC hard gates, "
                "or deliverable completion."
            ),
        }
    candidate_audit = _decision_summary_candidate_id_audit(
        decision_summary=payload,
        release_subset=release_subset,
    )
    summary_status = str(payload.get("status") or "").strip()
    summary_status_blocker_ids: list[str] = []
    if summary_status != "deployment_decision_summary_available":
        summary_status_blocker_ids.append("deployment_decision_summary_not_release_usable")
        candidate_audit = dict(candidate_audit)
        candidate_audit["status"] = "blocked"
        candidate_audit["candidate_ids_bound_to_release_universe"] = False
        candidate_audit["deployment_decision_summary_status"] = summary_status or "missing"
        candidate_audit["deployment_decision_summary_status_acceptable"] = False
        candidate_audit["blocker_ids"] = sorted(
            dict.fromkeys(
                [
                    *[str(item) for item in candidate_audit.get("blocker_ids", []) or [] if item],
                    *summary_status_blocker_ids,
                ]
            )
        )
        candidate_audit["audit_hash"] = stable_json_hash(
            {key: value for key, value in candidate_audit.items() if key != "audit_hash"}
        )
    blocker_ids = list(candidate_audit.get("blocker_ids", []) or [])
    return {
        "schema_version": "dse.dft.current_goal.decision_summary_inputs.v1",
        "status": "blocked" if blocker_ids else "bound",
        "binding_status": (
            "blocked_supplied_summary_fail_closed"
            if summary_status_blocker_ids
            else "bound_to_supplied_artifact"
        ),
        "deployment_decision_summary": ref,
        "deployment_decision_summary_candidate_id_audit": candidate_audit,
        "supplied_input_count": 1 if ref.get("exists") is True else 0,
        "blocker_ids": blocker_ids,
        "claim_boundary": (
            "Decision-summary inputs are hash-bound package references only. "
            "They do not upgrade target recommendations, Vivado/DC hard gates, "
            "or deliverable completion."
        ),
    }


def _target_evidence_gate_ledger_linkage(
    *,
    target_evidence_ledger_path: Path | None,
    target_evidence_ledger_validation_path: Path | None,
    target_evidence_ledger_status_path: Path | None,
) -> Dict[str, Any]:
    artifact_refs = {
        "target_evidence_gate_ledger": _source_ref(
            "target_evidence_gate_ledger",
            target_evidence_ledger_path,
            required=False,
        ),
        "target_evidence_gate_ledger_validation": _source_ref(
            "target_evidence_gate_ledger_validation",
            target_evidence_ledger_validation_path,
            required=False,
        ),
        "target_evidence_gate_ledger_status": _source_ref(
            "target_evidence_gate_ledger_status",
            target_evidence_ledger_status_path,
            required=False,
        ),
    }
    supplied_paths = [
        path
        for path in (
            target_evidence_ledger_path,
            target_evidence_ledger_validation_path,
            target_evidence_ledger_status_path,
        )
        if path is not None
    ]
    if not supplied_paths:
        payload = {
            "schema_version": "dse.dft.current_goal.target_evidence_gate_ledger_linkage.v1",
            "status": "unbound",
            "binding_status": "unbound_no_target_evidence_gate_ledger",
            "artifact_refs": artifact_refs,
            "source_matrix_ref": {},
            "source_matrix_evidence_gate_ids": [],
            "source_matrix_to_target_gate_rows": [],
            "source_matrix_to_target_gate_row_count": 0,
            "ledger_row_count": 0,
            "validation_valid": False,
            "supplied_input_count": 0,
            "blocker_ids": [],
            "deliverable_complete": False,
            "claim_boundary": (
                "Target evidence-gate ledger linkage is optional package "
                "provenance. When unbound it cannot upgrade release, FPGA, "
                "ASIC, PPA, or deliverable-complete claims."
            ),
        }
        payload["linkage_hash"] = stable_json_hash(
            {key: value for key, value in payload.items() if key != "linkage_hash"}
        )
        return payload

    blocker_ids: list[str] = []
    for key, ref in artifact_refs.items():
        if ref.get("exists") is not True:
            blocker_ids.append(f"{key}_missing")

    ledger = (
        _load_json_mapping(Path(target_evidence_ledger_path))
        if artifact_refs["target_evidence_gate_ledger"].get("exists") is True
        and target_evidence_ledger_path is not None
        else {}
    )
    validation = (
        _load_json_mapping(Path(target_evidence_ledger_validation_path))
        if artifact_refs["target_evidence_gate_ledger_validation"].get("exists") is True
        and target_evidence_ledger_validation_path is not None
        else {}
    )
    ledger_status = (
        _load_json_mapping(Path(target_evidence_ledger_status_path))
        if artifact_refs["target_evidence_gate_ledger_status"].get("exists") is True
        and target_evidence_ledger_status_path is not None
        else {}
    )

    if validation and validation.get("valid") is not True:
        blocker_ids.append("target_evidence_gate_ledger_validation_not_valid")

    rows: list[Dict[str, Any]] = []
    for row in ledger.get("rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        row_provenance = (
            dict(row.get("row_provenance"))
            if isinstance(row.get("row_provenance"), Mapping)
            else {}
        )
        source_gate_id = str(
            row.get("source_matrix_evidence_gate_id")
            or row_provenance.get("source_matrix_evidence_gate_id")
            or ""
        )
        if not source_gate_id:
            continue
        rows.append(
            {
                "candidate_id": str(row.get("candidate_id") or ""),
                "kernel_id": str(row.get("kernel_id") or ""),
                "workflow_case_id": str(row.get("workflow_case_id") or ""),
                "deployment_boundary_id": str(row.get("deployment_boundary_id") or ""),
                "target_platform_id": str(row.get("target_platform_id") or ""),
                "target_platform_kind": str(row.get("target_platform_kind") or ""),
                "source_matrix_evidence_gate_id": source_gate_id,
                "target_evidence_gate_id": str(row.get("evidence_gate_id") or ""),
                "source_matrix_row_id": str(row.get("source_matrix_row_id") or ""),
                "source_matrix_row_hash": str(
                    row_provenance.get("source_matrix_row_hash") or ""
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["target_platform_kind"],
            row["candidate_id"],
            row["kernel_id"],
            row["source_matrix_evidence_gate_id"],
            row["target_evidence_gate_id"],
        )
    )
    if artifact_refs["target_evidence_gate_ledger"].get("exists") is True and not rows:
        blocker_ids.append("target_evidence_gate_ledger_missing_source_matrix_gate_ids")

    source_artifacts = (
        dict(ledger.get("source_artifacts"))
        if isinstance(ledger.get("source_artifacts"), Mapping)
        else {}
    )
    source_matrix_ref = (
        dict(source_artifacts.get("candidate_workflow_deployment_target_matrix"))
        if isinstance(
            source_artifacts.get("candidate_workflow_deployment_target_matrix"),
            Mapping,
        )
        else {}
    )
    status = "blocked" if blocker_ids else "bound"
    payload = {
        "schema_version": "dse.dft.current_goal.target_evidence_gate_ledger_linkage.v1",
        "status": status,
        "binding_status": (
            "bound_to_supplied_target_evidence_gate_ledger"
            if status == "bound"
            else "blocked_supplied_target_evidence_gate_ledger"
        ),
        "artifact_refs": artifact_refs,
        "source_matrix_ref": source_matrix_ref,
        "source_matrix_evidence_gate_ids": sorted(
            {row["source_matrix_evidence_gate_id"] for row in rows}
        ),
        "source_matrix_to_target_gate_rows": rows,
        "source_matrix_to_target_gate_row_count": len(rows),
        "ledger_row_count": int(ledger_status.get("row_count", ledger.get("row_count", 0)) or 0),
        "validation_valid": validation.get("valid") is True,
        "supplied_input_count": sum(
            1 for ref in artifact_refs.values() if ref.get("exists") is True
        ),
        "blocker_ids": sorted(set(blocker_ids)),
        "deliverable_complete": False,
        "claim_boundary": (
            "Target evidence-gate ledger linkage hash-binds producer artifacts "
            "and source-matrix gate IDs only. It is not final FPGA/ASIC PPA "
            "evidence and cannot upgrade hardware or deliverable-complete claims."
        ),
    }
    payload["linkage_hash"] = stable_json_hash(
        {key: value for key, value in payload.items() if key != "linkage_hash"}
    )
    return payload


def _done_when_item(
    *,
    done_when_id: int,
    title: str,
    status: str,
    source_artifacts: list[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    blockers: list[Mapping[str, Any]],
    claim_boundary: str,
) -> Dict[str, Any]:
    payload = {
        "done_when_id": done_when_id,
        "title": title,
        "status": status,
        "source_artifacts": [dict(item) for item in source_artifacts],
        "artifact_paths": [item.get("path") for item in source_artifacts],
        "evidence": dict(evidence),
        "blocker_count": len(blockers),
        "blockers": [dict(item) for item in blockers],
        "claim_boundary": claim_boundary,
    }
    payload["check_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "check_hash"})
    return payload


def build_complete_dse_done_when_4_6_audit(
    *,
    repo_root: Path | None = None,
    control_root: Path | None = None,
    goal_path: Path | None = None,
    barrier_path: Path | None = None,
    preflight_path: Path | None = None,
    north_star_path: Path | None = None,
    strict_qe_release_bundle_manifest_path: Path | None = None,
    release_subset: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a fail-closed Done-when 4-6 audit payload.

    The default release subset is intentionally the current generic Complete-DSE
    subset.  The audit therefore reports the present 4-vs-6 blocker instead of
    silently substituting a DFT-specific workflow axis.
    """

    repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    control_root = Path(control_root).resolve() if control_root is not None else _default_control_root(repo_root)
    goal_path = Path(goal_path) if goal_path is not None else control_root / "docs" / "goal.md"
    barrier_path = (
        Path(barrier_path)
        if barrier_path is not None
        else control_root / ".omx" / "context" / _BARRIER_NAME
    )
    preflight_path = (
        Path(preflight_path)
        if preflight_path is not None
        else control_root / ".omx" / "context" / _PREFLIGHT_NAME
    )
    north_star_path = (
        Path(north_star_path)
        if north_star_path is not None
        else _latest_match(control_root, ".omx/context/master-qe-fpga-asic-dse-north-star-*.md")
    )
    strict_qe_release_bundle_manifest_path = (
        Path(strict_qe_release_bundle_manifest_path)
        if strict_qe_release_bundle_manifest_path is not None
        else None
    )

    subset = dict(release_subset or build_release_subset_manifest())
    matrix = (
        dict(subset.get("candidate_workflow_deployment_target_matrix") or {})
        if isinstance(subset.get("candidate_workflow_deployment_target_matrix"), Mapping)
        else {}
    )
    matrix_validation = validate_candidate_workflow_deployment_target_matrix(subset, matrix)
    required_workflow_case_count = int(DEFAULT_FROZEN_WORKLOAD_CASE_COUNT)
    actual_workflow_case_count = int(matrix.get("workflow_case_count") or 0)
    workflow_axis_blockers: list[Dict[str, Any]] = []
    if actual_workflow_case_count != required_workflow_case_count:
        workflow_axis_blockers.append(
            {
                "id": "release_workflow_axis_case_count_mismatch",
                "reason": (
                    "current default matrix workflow axis does not satisfy the "
                    "six strict SCF release obligation"
                ),
                "actual_workflow_case_count": actual_workflow_case_count,
                "expected_workflow_case_count": required_workflow_case_count,
                "actual_workflow_case_ids": list(matrix.get("workflow_case_ids") or []),
                "expected_workload_classes": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
            }
        )
    if matrix_validation.get("valid") is not True:
        workflow_axis_blockers.append(
            {
                "id": "candidate_workflow_deployment_target_matrix_invalid",
                "reason": "release-universe matrix validation failed",
                "validation_blockers": matrix_validation.get("blockers", []),
            }
        )
    if subset.get("generation_provenance", {}).get("source") == "predeclared_release_v1_seed_rows":
        workflow_axis_blockers.append(
            {
                "id": "predeclared_seed_rows_not_real_search_generation_claim",
                "reason": (
                    "canonical release subset is reproducible seed-row enumeration; "
                    "it is not by itself a real search-generation completion claim"
                ),
                "source": "predeclared_release_v1_seed_rows",
            }
        )

    done4_artifacts = [
        _source_ref("controlling_goal", goal_path),
        _source_ref("three_run_barrier", barrier_path),
        _source_ref("three_run_preflight", preflight_path),
        _source_ref("north_star_checkpoint", north_star_path, required=False),
        _repo_file(
            repo_root,
            "dft_design_manual",
            "docs/architecture/dft_scf_hardware_dse_design_manual.md",
        ),
    ]
    done4_blockers = _missing_required_artifacts(done4_artifacts)
    done4 = _done_when_item(
        done_when_id=4,
        title="Current north-star/spec contract",
        status=_status_from(done4_blockers),
        source_artifacts=done4_artifacts,
        evidence={
            "goal_path": str(goal_path),
            "barrier_path": str(barrier_path),
            "preflight_path": str(preflight_path),
            "north_star_path": str(north_star_path) if north_star_path else None,
            "deliverable_complete": False,
        },
        blockers=done4_blockers,
        claim_boundary=(
            "Spec and process evidence only; this does not prove QE/gem5/L4, "
            "Vivado, DC, or final hardware recommendation closure."
        ),
    )

    done5_artifacts = [
        _repo_file(repo_root, "dft_scf_workstreams", "dse_v2/codesign/dft_scf_workstreams.py"),
        _repo_file(repo_root, "dft_workflow_contract", "dse_v2/reference_workloads/dft_workflow.py"),
        _repo_file(repo_root, "dft_qe_importer", "dse_v2/reference_workloads/dft_qe.py"),
        _repo_file(
            repo_root,
            "step1_workflow_contract_tests",
            "dse_v2/tests/test_step1_workflow_contract.py",
        ),
        _repo_file(repo_root, "workload_workflow_tests", "dse_v2/tests/test_workload_workflows.py"),
        _repo_file(
            repo_root,
            "dft_scf_six_class_tests",
            "dse_v2/tests/test_dft_scf_six_class_suite.py",
        ),
        _repo_file(
            repo_root,
            "qe_offload_oracle_contract",
            "dse_v2/codesign/qe_callgraph_offload_search.py",
        ),
        _source_ref(
            "strict_qe_release_bundle_manifest",
            strict_qe_release_bundle_manifest_path,
            required=False,
        ),
    ]
    done5_blockers = _missing_required_artifacts(done5_artifacts)
    strict_qe_release_bundle_evidence: Dict[str, Any] = {
        "supplied": strict_qe_release_bundle_manifest_path is not None,
        "path": str(strict_qe_release_bundle_manifest_path) if strict_qe_release_bundle_manifest_path is not None else None,
        "required_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
        "present_class_ids": [],
        "case_count": 0,
        "admitted": False,
        "final_real_qe_evidence": False,
        "validation_status": None,
        "schema_version": None,
    }
    if strict_qe_release_bundle_manifest_path is not None:
        validation = validate_dft_scf_six_class_bundle_manifest(
            strict_qe_release_bundle_manifest_path,
            base_dir=strict_qe_release_bundle_manifest_path.parent,
        )
        manifest = {}
        try:
            manifest = json.loads(strict_qe_release_bundle_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        strict_qe_release_bundle_evidence.update(
            {
                "schema_version": manifest.get("schema_version"),
                "case_count": manifest.get("case_count", 0),
                "present_class_ids": list(manifest.get("workload_classes") or []),
                "validation_status": validation.get("status"),
                "admitted": bool(validation.get("admitted") is True),
                "final_real_qe_evidence": bool(manifest.get("final_real_qe_evidence") is True and validation.get("admitted") is True),
            }
        )
        if validation.get("status") != "passed" or manifest.get("final_real_qe_evidence") is not True:
            done5_blockers.append(
                {
                    "id": "strict_qe_release_bundle_not_final_real_qe_evidence",
                    "reason": (
                        "the supplied strict six-class bundle is present, but it "
                        "does not yet carry final real-QE reference-output evidence"
                    ),
                    "validation_status": validation.get("status"),
                    "manifest_schema_version": manifest.get("schema_version"),
                    "final_real_qe_evidence": manifest.get("final_real_qe_evidence"),
                }
            )
    done5_partial_blockers = [
        {
            "id": "strict_qe_release_lane_bundle_not_supplied_to_audit",
            "reason": (
                "the audit can identify the six-class contract sources, but no "
                "current generated strict QE bundle manifest is supplied as "
                "final release evidence"
            ),
        }
    ]
    if strict_qe_release_bundle_manifest_path is not None:
        done5_partial_blockers = []
    done5 = _done_when_item(
        done_when_id=5,
        title="QE workflow/input representation contract",
        status=_status_from(done5_blockers, partial=not done5_blockers),
        source_artifacts=done5_artifacts,
        evidence={
            "required_strict_scf_class_count": len(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "required_strict_scf_classes": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "required_bundle_assets": list(STRICT_BUNDLE_REQUIRED_ASSETS),
            "stable_core_identity_contains_dft_workload_class": False,
            "deliverable_complete": False,
            "strict_qe_release_bundle": strict_qe_release_bundle_evidence,
        },
        blockers=done5_blockers + done5_partial_blockers,
        claim_boundary=(
            "DFT/QE workflow-input contract evidence only. It remains partial "
            "until a current strict six-SCF bundle plus real QE baseline/oracle "
            "evidence is bound into the release lane."
        ),
    )

    done6_artifacts = [
        _repo_file(
            repo_root,
            "complete_dse_search_space",
            "dse_v2/codesign/complete_dse_search_space.py",
        ),
        _repo_file(
            repo_root,
            "release_matrix_tests",
            "dse_v2/tests/test_complete_dse_release_matrix.py",
        ),
        _repo_file(
            repo_root,
            "search_space_contract_tests",
            "dse_v2/tests/test_complete_dse_search_space_contracts.py",
        ),
        _repo_file(
            repo_root,
            "release_taxonomy_tests",
            "dse_v2/tests/test_complete_dse_release_taxonomy.py",
        ),
        _repo_file(
            repo_root,
            "current_goal_l4_bridge",
            "dse_v2/reference_workloads/dft_current_goal_l4_bridge.py",
        ),
    ]
    done6_blockers = _missing_required_artifacts(done6_artifacts) + workflow_axis_blockers
    done6 = _done_when_item(
        done_when_id=6,
        title="Finite reproducible release universe",
        status=_status_from(done6_blockers),
        source_artifacts=done6_artifacts,
        evidence={
            "release_id": subset.get("release_id"),
            "candidate_count": subset.get("candidate_count"),
            "legal_candidate_count": subset.get("legal_candidate_count"),
            "release_subset_hash": subset.get("release_subset_hash"),
            "generation_mode": subset.get("generation_provenance", {}).get("generation_mode"),
            "generation_source": subset.get("generation_provenance", {}).get("source"),
            "matrix_hash": matrix.get("matrix_hash"),
            "matrix_validation_hash": matrix_validation.get("validation_hash"),
            "default_matrix_workflow_case_count": actual_workflow_case_count,
            "current_goal_required_workflow_case_count": required_workflow_case_count,
            "workflow_case_ids": list(matrix.get("workflow_case_ids") or []),
            "evidence_gate_count": matrix.get("evidence_gate_count"),
            "row_count": matrix.get("row_count"),
            "expected_row_count": matrix.get("expected_row_count"),
            "deliverable_complete": False,
        },
        blockers=done6_blockers,
        claim_boundary=(
            "Release-universe audit only. The generic candidate IDs remain "
            "domain-neutral; the current six-SCF workflow axis must be supplied "
            "as a release matrix axis outside candidate identity."
        ),
    )

    checklist = [done4, done5, done6]
    blocker_ids = sorted(
        {
            str(blocker.get("id") or blocker.get("blocker_id") or "")
            for item in checklist
            for blocker in item.get("blockers", [])
            if blocker.get("id") or blocker.get("blocker_id")
        }
    )
    status = "blocked" if any(item["status"] == "blocked" for item in checklist) else "partial"
    payload: Dict[str, Any] = {
        "schema_version": COMPLETE_DSE_DONE_WHEN_4_6_AUDIT_SCHEMA,
        "status": status,
        "deliverable_complete": False,
        "repo_root": str(repo_root),
        "control_root": str(control_root),
        "checklist": checklist,
        "blocker_ids": blocker_ids,
        "release_universe_audit": {
            "release_id": subset.get("release_id"),
            "release_subset_hash": subset.get("release_subset_hash"),
            "candidate_count": subset.get("candidate_count"),
            "legal_candidate_count": subset.get("legal_candidate_count"),
            "default_matrix_workflow_case_count": actual_workflow_case_count,
            "current_goal_required_workflow_case_count": required_workflow_case_count,
            "workflow_axis_blocked": actual_workflow_case_count != required_workflow_case_count,
            "matrix_hash": matrix.get("matrix_hash"),
            "matrix_validation_valid": matrix_validation.get("valid"),
            "deliverable_complete": False,
        },
        "candidate_identity_contract": {
            "domain_neutral_core": True,
            "identity_layers": list(IDENTITY_LAYER_KEYS),
            "non_identity_fields": list(NON_IDENTITY_FIELDS),
            "workload_facts_enter_stable_candidate_id": False,
            "dft_qe_facts_location": "reference_workloads/adapters/scripts/tests only",
            "identity_contract_hash": stable_json_hash(
                {
                    "identity_layers": list(IDENTITY_LAYER_KEYS),
                    "non_identity_fields": list(NON_IDENTITY_FIELDS),
                }
            ),
        },
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    payload["audit_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "audit_hash"})
    return payload


def write_complete_dse_done_when_4_6_audit(
    out_dir: Path,
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / REPORT_NAME
    status_path = out_dir / STATUS_NAME
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status_payload = {
        "schema_version": COMPLETE_DSE_DONE_WHEN_4_6_STATUS_SCHEMA,
        "status": payload.get("status"),
        "artifact": str(report_path),
        "status_path": str(status_path),
        "audit_hash": payload.get("audit_hash"),
        "deliverable_complete": False,
        "blocker_ids": list(payload.get("blocker_ids", []) or []),
        "claim_boundary": payload.get("claim_boundary"),
    }
    status_payload["status_hash"] = stable_json_hash(
        {k: v for k, v in status_payload.items() if k != "status_hash"}
    )
    status_path.write_text(json.dumps(status_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status_payload


def build_complete_dse_release_artifact_package(
    *,
    package_root: Path,
    repo_root: Path,
    control_root: Path,
    search_space_status: Mapping[str, Any],
    audit_status: Mapping[str, Any],
    release_subset: Mapping[str, Any],
    audit_payload: Mapping[str, Any],
    stable_artifacts: list[Mapping[str, Any]],
    deployment_decision_summary_path: Path | None = None,
    strict_qe_release_bundle_manifest_path: Path | None = None,
    target_evidence_ledger_path: Path | None = None,
    target_evidence_ledger_validation_path: Path | None = None,
    target_evidence_ledger_status_path: Path | None = None,
    replay_cli: Mapping[str, Any] | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the materialized release package and hash manifest payloads.

    The package binds existing release-universe and Done-when 4-6 audit
    artifacts into one replayable surface.  It does not make final QE,
    FPGA/ASIC, or global completion claims.
    """

    package_root = Path(package_root)
    matrix = (
        dict(release_subset.get("candidate_workflow_deployment_target_matrix") or {})
        if isinstance(release_subset.get("candidate_workflow_deployment_target_matrix"), Mapping)
        else {}
    )
    generation_report_path = package_root / "search_space" / "candidate_generation_report.json"
    generation_report = _load_json_mapping(generation_report_path)
    freeze_path = package_root / "search_space" / "freeze_gate_verdict.json"
    freeze_gate = _load_json_mapping(freeze_path)
    linkage, linkage_blockers = _strict_six_class_bundle_linkage(
        strict_qe_release_bundle_manifest_path
    )
    missing_artifact_blockers = [
        {
            "id": "release_package_artifact_missing",
            "canonical_name": str(artifact.get("canonical_name") or ""),
            "path": artifact.get("path"),
            "reason": "stable release package artifact is missing",
        }
        for artifact in stable_artifacts
        if artifact.get("required") is True and artifact.get("exists") is not True
    ]
    audit_blockers = [
        str(blocker_id)
        for blocker_id in audit_payload.get("blocker_ids", []) or []
        if blocker_id
    ]
    blocker_ids = sorted(
        {
            *(blocker["id"] for blocker in linkage_blockers),
            *(blocker["id"] for blocker in missing_artifact_blockers),
            *audit_blockers,
        }
    )
    status = "blocked" if missing_artifact_blockers else "partial"
    current_goal_checklist_traceability = _current_goal_checklist_traceability(
        stable_artifacts=stable_artifacts,
        audit_payload=audit_payload,
        audit_status=audit_status,
        release_subset=release_subset,
        generation_report=generation_report,
        matrix=matrix,
    )
    replay_cli_payload = dict(
        replay_cli
        or _release_package_replay_cli(
            out_dir=package_root,
            repo_root=repo_root,
            control_root=control_root,
            strict_qe_release_bundle_manifest_path=strict_qe_release_bundle_manifest_path,
            target_evidence_ledger_path=target_evidence_ledger_path,
            target_evidence_ledger_validation_path=target_evidence_ledger_validation_path,
            target_evidence_ledger_status_path=target_evidence_ledger_status_path,
        )
    )
    deployment_search_candidate_id_audit = _deployment_search_candidate_id_audit(
        release_subset=release_subset,
        generation_report=generation_report,
        matrix=matrix,
    )
    decision_summary_inputs = _decision_summary_inputs(
        deployment_decision_summary_path,
        release_subset=release_subset,
    )
    decision_summary_blocker_ids = [
        str(blocker_id)
        for blocker_id in decision_summary_inputs.get("blocker_ids", []) or []
        if blocker_id
    ]
    if decision_summary_blocker_ids:
        blocker_ids = sorted(set([*blocker_ids, *decision_summary_blocker_ids]))
    release_candidate_identity_provenance = _release_candidate_identity_provenance(
        deployment_search_candidate_id_audit=deployment_search_candidate_id_audit,
        decision_summary_inputs=decision_summary_inputs,
        strict_six_class_bundle_linkage=linkage,
        strict_six_class_bundle_blockers=linkage_blockers,
    )
    target_evidence_gate_ledger_linkage = _target_evidence_gate_ledger_linkage(
        target_evidence_ledger_path=target_evidence_ledger_path,
        target_evidence_ledger_validation_path=target_evidence_ledger_validation_path,
        target_evidence_ledger_status_path=target_evidence_ledger_status_path,
    )
    if target_evidence_gate_ledger_linkage["status"] == "blocked":
        blocker_ids.extend(
            [
                str(blocker_id)
                for blocker_id in target_evidence_gate_ledger_linkage.get("blocker_ids", [])
                if blocker_id
            ]
        )
        blocker_ids = sorted(set(blocker_ids))
        status = "blocked"
    hash_manifest = {
        "schema_version": COMPLETE_DSE_RELEASE_ARTIFACT_HASH_MANIFEST_SCHEMA,
        "status": "passed" if status != "blocked" else "failed",
        "release_id": release_subset.get("release_id"),
        "stable_artifact_names": list(STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES),
        "artifact_count": len(stable_artifacts),
        "artifacts": [dict(artifact) for artifact in stable_artifacts],
        "replay_cli": replay_cli_payload,
        "deployment_search_candidate_id_audit": dict(
            deployment_search_candidate_id_audit
        ),
        "decision_summary_inputs": dict(decision_summary_inputs),
        "release_candidate_identity_provenance": dict(release_candidate_identity_provenance),
        "target_evidence_gate_ledger_linkage": dict(target_evidence_gate_ledger_linkage),
        "current_goal_checklist_traceability": dict(current_goal_checklist_traceability),
        "source_status": {
            "search_space_status": dict(search_space_status),
            "audit_status": dict(audit_status),
        },
        "strict_six_class_bundle_linkage": dict(linkage),
        "deliverable_complete": False,
        "manifest_scope": (
            "Hashes the stable release/audit package artifacts. The hash "
            "manifest records replay provenance and fail-closed linkage only; "
            "it is not final QE or hardware evidence."
        ),
    }
    hash_manifest["manifest_hash"] = stable_json_hash(
        {key: value for key, value in hash_manifest.items() if key != "manifest_hash"}
    )
    package = {
        "schema_version": COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_SCHEMA,
        "status": status,
        "release_id": release_subset.get("release_id"),
        "repo_root": str(repo_root),
        "control_root": str(control_root),
        "stable_artifact_names": list(STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES),
        "artifacts": [dict(artifact) for artifact in stable_artifacts],
        "artifact_hash_manifest": {
            "canonical_name": RELEASE_ARTIFACT_HASH_MANIFEST_NAME,
            "schema_version": COMPLETE_DSE_RELEASE_ARTIFACT_HASH_MANIFEST_SCHEMA,
            "manifest_hash": hash_manifest["manifest_hash"],
        },
        "replay_cli": replay_cli_payload,
        "deployment_search_candidate_id_audit": dict(
            deployment_search_candidate_id_audit
        ),
        "decision_summary_inputs": dict(decision_summary_inputs),
        "release_candidate_identity_provenance": dict(release_candidate_identity_provenance),
        "target_evidence_gate_ledger_linkage": dict(target_evidence_gate_ledger_linkage),
        "current_goal_checklist_traceability": dict(current_goal_checklist_traceability),
        "release_universe": {
            "release_id": release_subset.get("release_id"),
            "candidate_count": release_subset.get("candidate_count"),
            "legal_candidate_count": release_subset.get("legal_candidate_count"),
            "release_subset_hash": release_subset.get("release_subset_hash"),
            "workflow_case_count": matrix.get("workflow_case_count"),
            "workflow_case_ids": list(matrix.get("workflow_case_ids") or []),
            "target_platform_ids": list(matrix.get("target_platform_ids") or []),
            "target_platform_kinds": list(matrix.get("target_platform_kinds") or []),
            "evidence_gate_ids": list(matrix.get("evidence_gate_ids") or []),
            "row_count": matrix.get("row_count"),
            "expected_row_count": matrix.get("expected_row_count"),
            "matrix_hash": matrix.get("matrix_hash"),
            "matrix_validation_hash": (
                release_subset.get("generation_provenance", {}).get(
                    "candidate_workflow_deployment_target_matrix_validation_hash"
                )
                if isinstance(release_subset.get("generation_provenance"), Mapping)
                else None
            ),
        },
        "generated_search_provenance": {
            "source": (
                release_subset.get("generation_provenance", {}).get("source")
                if isinstance(release_subset.get("generation_provenance"), Mapping)
                else None
            ),
            "generation_mode": (
                release_subset.get("generation_provenance", {}).get("generation_mode")
                if isinstance(release_subset.get("generation_provenance"), Mapping)
                else None
            ),
            "parameter_profile_ids": (
                list(release_subset.get("generation_provenance", {}).get("parameter_profile_ids") or [])
                if isinstance(release_subset.get("generation_provenance"), Mapping)
                else []
            ),
            "candidate_generation_report_hash": generation_report.get("report_hash"),
            "search_generation_status": generation_report.get("search_generation_status"),
            "real_search_generation_eligible": bool(
                generation_report.get("real_search_generation_eligible") is True
            ),
            "freeze_gate_status": freeze_gate.get("status"),
            "final_release_universe_eligible": bool(
                freeze_gate.get("final_release_universe_eligible") is True
            ),
            "claim_boundary": (
                "Generated-search provenance proves bounded deterministic "
                "candidate generation only; it is not QE, gem5, Vivado, or DC evidence."
            ),
        },
        "strict_six_class_bundle_linkage": dict(linkage),
        "candidate_identity_contract": dict(audit_payload.get("candidate_identity_contract") or {}),
        "fixed_or_manual_seed_completion_claim_allowed": False,
        "top_k_or_representative_completion_allowed": False,
        "blocker_ids": blocker_ids,
        "blockers": linkage_blockers + missing_artifact_blockers,
        "search_space_status": dict(search_space_status),
        "audit_status": dict(audit_status),
        "deliverable_complete": False,
        "claim_boundary": (
            "Materialized release artifact package for Done-when 4-6 and the "
            "six-case release universe. It is replay/package evidence only and "
            "cannot claim hardware winners, trusted speedup, FPGA/ASIC closure, "
            "or global deliverable completion."
        ),
    }
    package["package_hash"] = stable_json_hash(
        {key: value for key, value in package.items() if key != "package_hash"}
    )
    return package, hash_manifest


def write_complete_dse_release_artifact_package(
    out_dir: Path,
    *,
    repo_root: Path | None = None,
    control_root: Path | None = None,
    goal_path: Path | None = None,
    barrier_path: Path | None = None,
    preflight_path: Path | None = None,
    north_star_path: Path | None = None,
    deployment_decision_summary_path: Path | None = None,
    strict_qe_release_bundle_manifest_path: Path | None = None,
    target_evidence_ledger_path: Path | None = None,
    target_evidence_ledger_validation_path: Path | None = None,
    target_evidence_ledger_status_path: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    control_root = Path(control_root).resolve() if control_root is not None else _default_control_root(repo_root)

    search_space_dir = out_dir / "search_space"
    audit_dir = out_dir / "audit"
    search_space_status = write_complete_dse_search_space_artifacts(search_space_dir)
    release_subset_path = search_space_dir / "release_subset_manifest.json"
    release_subset = _load_json_mapping(release_subset_path)
    matrix = dict(release_subset.get("candidate_workflow_deployment_target_matrix") or {})
    _write_json(out_dir / "candidate_workflow_deployment_target_matrix.json", matrix)

    audit_payload = build_complete_dse_done_when_4_6_audit(
        repo_root=repo_root,
        control_root=control_root,
        goal_path=goal_path,
        barrier_path=barrier_path,
        preflight_path=preflight_path,
        north_star_path=north_star_path,
        strict_qe_release_bundle_manifest_path=strict_qe_release_bundle_manifest_path,
        release_subset=release_subset,
    )
    audit_status = write_complete_dse_done_when_4_6_audit(audit_dir, audit_payload)
    artifact_roles = {
        "search_space/release_subset_manifest.json": "release_subset_manifest",
        "candidate_workflow_deployment_target_matrix.json": "candidate_workflow_deployment_target_matrix",
        "audit/complete_dse_done_when_4_6_audit.json": "done_when_4_6_audit",
        "audit/status.json": "done_when_4_6_audit_status",
        "search_space/candidate_generation_report.json": "candidate_generation_report",
        "search_space/freeze_gate_verdict.json": "freeze_gate_verdict",
        "search_space/status.json": "search_space_status",
    }
    stable_artifacts = [
        _package_artifact_ref(
            out_dir,
            canonical_name,
            artifact_role=artifact_roles[canonical_name],
        )
        for canonical_name in STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES
    ]
    replay_cli = _release_package_replay_cli(
        out_dir=out_dir,
        repo_root=repo_root,
        control_root=control_root,
        goal_path=goal_path,
        barrier_path=barrier_path,
        preflight_path=preflight_path,
        north_star_path=north_star_path,
        deployment_decision_summary_path=deployment_decision_summary_path,
        strict_qe_release_bundle_manifest_path=strict_qe_release_bundle_manifest_path,
        target_evidence_ledger_path=target_evidence_ledger_path,
        target_evidence_ledger_validation_path=target_evidence_ledger_validation_path,
        target_evidence_ledger_status_path=target_evidence_ledger_status_path,
    )
    package, hash_manifest = build_complete_dse_release_artifact_package(
        package_root=out_dir,
        repo_root=repo_root,
        control_root=control_root,
        search_space_status=search_space_status,
        audit_status=audit_status,
        release_subset=release_subset,
        audit_payload=audit_payload,
        stable_artifacts=stable_artifacts,
        deployment_decision_summary_path=deployment_decision_summary_path,
        strict_qe_release_bundle_manifest_path=strict_qe_release_bundle_manifest_path,
        target_evidence_ledger_path=target_evidence_ledger_path,
        target_evidence_ledger_validation_path=target_evidence_ledger_validation_path,
        target_evidence_ledger_status_path=target_evidence_ledger_status_path,
        replay_cli=replay_cli,
    )
    decision_summary_candidate_id_audit = dict(
        package["decision_summary_inputs"].get(
            "deployment_decision_summary_candidate_id_audit",
            {},
        )
    )
    package_path = out_dir / RELEASE_ARTIFACT_PACKAGE_NAME
    hash_manifest_path = out_dir / RELEASE_ARTIFACT_HASH_MANIFEST_NAME
    _write_json(package_path, package)
    _write_json(hash_manifest_path, hash_manifest)
    status_payload = {
        "schema_version": COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_STATUS_SCHEMA,
        "status": package["status"],
        "artifact_package": str(package_path),
        "hash_manifest": str(hash_manifest_path),
        "package_hash": package["package_hash"],
        "hash_manifest_hash": hash_manifest["manifest_hash"],
        "replay_cli": dict(package["replay_cli"]),
        "deployment_search_candidate_id_audit_status": package[
            "deployment_search_candidate_id_audit"
        ]["status"],
        "deployment_search_candidate_id_audit_hash": package[
            "deployment_search_candidate_id_audit"
        ]["audit_hash"],
        "decision_summary_input_count": package["decision_summary_inputs"][
            "supplied_input_count"
        ],
        "decision_summary_input_status": package["decision_summary_inputs"]["status"],
        "decision_summary_binding_status": package["decision_summary_inputs"].get(
            "binding_status"
        ),
        "decision_summary_input_blocker_ids": list(
            package["decision_summary_inputs"].get("blocker_ids", []) or []
        ),
        "decision_summary_candidate_id_audit_status": decision_summary_candidate_id_audit.get(
            "status"
        ),
        "decision_summary_candidate_id_audit_hash": decision_summary_candidate_id_audit.get(
            "audit_hash"
        ),
        "decision_summary_candidate_id_audit_blocker_ids": list(
            decision_summary_candidate_id_audit.get("blocker_ids", []) or []
        ),
        "decision_summary_candidate_ids_bound_to_release_universe": decision_summary_candidate_id_audit.get(
            "candidate_ids_bound_to_release_universe"
        ),
        "decision_summary_candidate_id_count": decision_summary_candidate_id_audit.get(
            "candidate_count"
        ),
        "decision_summary_extra_candidate_ids": list(
            decision_summary_candidate_id_audit.get("extra_candidate_ids", []) or []
        ),
        "release_candidate_identity_provenance_status": package[
            "release_candidate_identity_provenance"
        ]["status"],
        "release_candidate_identity_provenance_blocker_ids": list(
            package["release_candidate_identity_provenance"].get("blocker_ids", []) or []
        ),
        "target_evidence_gate_ledger_linkage_status": package[
            "target_evidence_gate_ledger_linkage"
        ]["status"],
        "target_evidence_gate_ledger_linkage_hash": package[
            "target_evidence_gate_ledger_linkage"
        ]["linkage_hash"],
        "target_evidence_gate_ledger_source_matrix_gate_id_count": len(
            package["target_evidence_gate_ledger_linkage"].get(
                "source_matrix_evidence_gate_ids",
                [],
            )
            or []
        ),
        "stable_artifact_count": len(stable_artifacts),
        "current_goal_checklist_traceability_status": package[
            "current_goal_checklist_traceability"
        ]["status"],
        "current_goal_checklist_artifact_ref_count": package[
            "current_goal_checklist_traceability"
        ]["artifact_alias_count"],
        "blocker_ids": list(package.get("blocker_ids", []) or []),
        "strict_six_class_bundle_supplied": package["strict_six_class_bundle_linkage"]["supplied"],
        "release_subset_hash": release_subset.get("release_subset_hash"),
        "matrix_hash": matrix.get("matrix_hash"),
        "deliverable_complete": False,
        "claim_boundary": package["claim_boundary"],
    }
    status_payload["status_hash"] = stable_json_hash(
        {key: value for key, value in status_payload.items() if key != "status_hash"}
    )
    _write_json(out_dir / STATUS_NAME, status_payload)
    return status_payload


__all__ = [
    "COMPLETE_DSE_DONE_WHEN_4_6_AUDIT_SCHEMA",
    "COMPLETE_DSE_DONE_WHEN_4_6_STATUS_SCHEMA",
    "COMPLETE_DSE_RELEASE_ARTIFACT_HASH_MANIFEST_SCHEMA",
    "COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_SCHEMA",
    "COMPLETE_DSE_RELEASE_ARTIFACT_PACKAGE_STATUS_SCHEMA",
    "COMPLETE_DSE_RELEASE_CHECKLIST_TRACEABILITY_SCHEMA",
    "CURRENT_GOAL_CHECKLIST_TRACEABILITY_ALIASES",
    "REPORT_NAME",
    "RELEASE_ARTIFACT_HASH_MANIFEST_NAME",
    "RELEASE_ARTIFACT_PACKAGE_NAME",
    "STABLE_RELEASE_PACKAGE_ARTIFACT_NAMES",
    "STATUS_NAME",
    "build_complete_dse_done_when_4_6_audit",
    "build_complete_dse_release_artifact_package",
    "write_complete_dse_done_when_4_6_audit",
    "write_complete_dse_release_artifact_package",
]
