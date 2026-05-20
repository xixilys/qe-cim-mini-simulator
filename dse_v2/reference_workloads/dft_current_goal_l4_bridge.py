#!/usr/bin/env python3
"""Fail-closed bridge from DFT Step5 current-goal artifacts to an L4 root.

The bridge only materializes identity and scheduling/provenance artifacts for a
regenerated current-goal L4 run.  It intentionally does not invent gem5, QE, or
FPGA/ASIC PPA evidence: optional L4 rows are emitted as pending/blocked until a
real L4 runner replaces them with trusted evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.l4_closure import build_coverage_claim_report, build_l4_evidence_matrix
from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.reference_workloads.dft_hardware_closure_release_gate import (
    DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA,
)
from dse_v2.reference_workloads.dft_scf_six_class_suite import (
    DFT_SCF_SIX_CLASS_SUITE_SCHEMA,
    REQUIRED_DFT_SCF_CLASS_IDS,
)

DFT_CURRENT_GOAL_L4_BRIDGE_SCHEMA = "dse.dft.current_goal_l4_bridge.v1"
DFT_CURRENT_GOAL_RELEASE_SUBSET_SCHEMA = "dse.dft.current_goal_l4.release_subset_manifest.v1"
DFT_CURRENT_GOAL_SIX_SCF_WORKLOAD_SUITE_SCHEMA = "dse.dft.current_goal_l4.six_scf_workload_suite.v1"
DFT_CURRENT_GOAL_L4_CROSSWALK_SCHEMA = "dse.dft.current_goal_l4.structured_crosswalk.v1"
DFT_CURRENT_GOAL_L4_PENDING_ROOT_SCHEMA = "dse.dft.current_goal_l4.pending_root_manifest.v1"
DFT_CURRENT_GOAL_L4_STATUS_SCHEMA = "dse.dft.current_goal_l4_bridge_status.v1"

EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT = 36
EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT = 6
LEGACY_INSUFFICIENT_CANDIDATE_COUNT = 9
LEGACY_INSUFFICIENT_WORKLOAD_COUNT = 4

CLAIM_BOUNDARY = (
    "The DFT current-goal L4 bridge emits identity manifests and exact crosswalks "
    "for a regenerated 36-candidate x six-SCF L4 root. It does not run gem5 or "
    "QE, does not fabricate PPA or correctness evidence, does not validate old "
    "9x4 L4 crosswalks, and cannot mark deliverable_complete."
)


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _stable_hash_without(payload: Mapping[str, Any], *excluded: str) -> str:
    return stable_json_hash({key: value for key, value in payload.items() if key not in set(excluded)})


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _candidate_ids_from_release_gate(release_gate: Mapping[str, Any]) -> list[str]:
    rows = _as_list(release_gate.get("candidate_rows"))
    ids = [
        str(row.get("candidate_id"))
        for row in rows
        if isinstance(row, Mapping) and row.get("candidate_id")
    ]
    if ids:
        return sorted(dict.fromkeys(ids))
    units = _as_list(release_gate.get("unit_rows"))
    return sorted(dict.fromkeys(
        str(row.get("candidate_id"))
        for row in units
        if isinstance(row, Mapping) and row.get("candidate_id")
    ))


def _workload_cases_from_six_scf_manifest(manifest: Mapping[str, Any]) -> list[Dict[str, Any]]:
    cases: list[Dict[str, Any]] = []
    for raw_case in _as_list(manifest.get("cases")):
        if not isinstance(raw_case, Mapping):
            continue
        class_id = str(raw_case.get("class_id") or raw_case.get("workload_class") or "")
        case_id = str(raw_case.get("case_id") or raw_case.get("workload_case_id") or "")
        if class_id or case_id:
            cases.append({
                "class_id": class_id,
                "workload_class": str(raw_case.get("workload_class") or class_id),
                "case_id": case_id,
                "workload_case_id": case_id,
                "descriptor": raw_case.get("descriptor"),
                "proof_class": raw_case.get("proof_class"),
                "reference_output_hash": raw_case.get("reference_output_hash"),
                "final_real_qe_evidence": bool(raw_case.get("final_real_qe_evidence", False)),
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": CLAIM_BOUNDARY,
            })
    order = {class_id: index for index, class_id in enumerate(REQUIRED_DFT_SCF_CLASS_IDS)}
    return sorted(cases, key=lambda row: order.get(row["class_id"], 999))


def _bridge_blockers(
    *,
    release_gate: Mapping[str, Any],
    candidate_ids: Sequence[str],
    six_scf_manifest: Mapping[str, Any],
    workload_cases: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    if release_gate.get("schema_version") != DFT_HARDWARE_CLOSURE_RELEASE_GATE_SCHEMA:
        blockers.append({"blocker_id": "release_gate_schema_mismatch", "reason": "Step5 release gate schema is not recognized"})
    if len(candidate_ids) != EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT:
        blockers.append({
            "blocker_id": "current_goal_candidate_count_not_36",
            "reason": "current-goal L4 bridge requires exactly 36 Step5 candidate identities",
            "expected_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
            "actual_candidate_count": len(candidate_ids),
        })
    non_cand_ids = [candidate_id for candidate_id in candidate_ids if not candidate_id.startswith("cand_")]
    if non_cand_ids:
        blockers.append({
            "blocker_id": "current_goal_candidate_ids_not_cand_prefixed",
            "reason": "all current-goal candidate identities must use cand_* ids from Step5",
            "candidate_ids": non_cand_ids,
        })
    if len(set(candidate_ids)) != len(candidate_ids):
        blockers.append({"blocker_id": "duplicate_current_goal_candidate_ids", "reason": "candidate ids must be unique"})
    if six_scf_manifest.get("schema_version") != DFT_SCF_SIX_CLASS_SUITE_SCHEMA:
        blockers.append({"blocker_id": "six_scf_manifest_schema_mismatch", "reason": "six-SCF bundle manifest schema is not recognized"})
    if six_scf_manifest.get("strict") is not True:
        blockers.append({"blocker_id": "six_scf_manifest_not_strict", "reason": "six-SCF workload suite must declare strict=true"})
    class_ids = [str(row.get("class_id")) for row in workload_cases]
    case_ids = [str(row.get("case_id")) for row in workload_cases]
    required = set(REQUIRED_DFT_SCF_CLASS_IDS)
    if set(class_ids) != required or len(workload_cases) != EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT:
        blockers.append({
            "blocker_id": "six_scf_workload_suite_not_exact",
            "reason": "workload suite must contain exactly the six strict SCF class ids",
            "expected_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "actual_class_ids": class_ids,
        })
    if len(set(case_ids)) != len(case_ids) or any(not case_id for case_id in case_ids):
        blockers.append({"blocker_id": "six_scf_workload_case_ids_missing_or_duplicate", "reason": "strict six-SCF workload case ids must be present and unique"})
    if six_scf_manifest.get("deliverable_complete") is True or six_scf_manifest.get("hardware_completion_eligible") is True:
        blockers.append({"blocker_id": "six_scf_manifest_overclaims_completion", "reason": "workload input bundle cannot be hardware/deliverable-complete evidence"})
    return blockers


def build_current_goal_release_subset_manifest(
    release_gate: Mapping[str, Any],
    *,
    release_gate_path: Path | None = None,
) -> Dict[str, Any]:
    """Build the current-goal 36-candidate release subset identity manifest."""

    candidate_ids = _candidate_ids_from_release_gate(release_gate)
    candidates: list[Dict[str, Any]] = []
    source_by_candidate = {
        str(row.get("candidate_id")): row
        for row in _as_list(release_gate.get("candidate_rows"))
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    for index, candidate_id in enumerate(candidate_ids):
        source = _as_mapping(source_by_candidate.get(candidate_id))
        candidates.append({
            "candidate_id": candidate_id,
            "candidate_index": index,
            "legal": True,
            "identity": {
                "identity_source": "step5_dft_hardware_closure_release_gate_candidate_id",
                "stable_id": candidate_id,
                "identity_scope": "current_goal_dft_hardware_candidate",
            },
            "step5_hardware_gate_status": source.get("status"),
            "step5_candidate_hardware_gate_passed": bool(source.get("candidate_hardware_gate_passed", False)),
            "step5_kernel_count": source.get("distinct_kernel_count") or source.get("unit_count"),
            "gem5_l4_evidence_present": False,
            "qe_reference_evidence_present": False,
            "ppa_evidence_fabricated": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": CLAIM_BOUNDARY,
        })
    payload: Dict[str, Any] = {
        "schema_version": DFT_CURRENT_GOAL_RELEASE_SUBSET_SCHEMA,
        "status": "identity_manifest_only_pending_l4_regeneration",
        "release_id": release_gate.get("release_id") or "dft_current_goal_l4",
        "tier": "current_goal_release_subset",
        "finite": True,
        "predeclared": True,
        "candidate_count": len(candidates),
        "legal_candidate_count": len(candidates),
        "expected_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
        "legal_candidate_ids": candidate_ids,
        "candidates": candidates,
        "source_artifacts": {"dft_hardware_closure_release_gate": _source_ref(release_gate_path) if release_gate_path else None},
        "generation_provenance": {
            "source": "dft_current_goal_l4_bridge",
            "candidate_id_rule": "preserve Step5 cand_* candidate_id exactly; no remapping or many-to-one binding",
            "candidate_order": candidate_ids,
        },
        "legacy_9x4_crosswalk_assessment": {
            "status": "insufficient_for_current_goal",
            "blocker_id": "old_9x4_crosswalk_insufficient_for_36x6_current_goal",
            "old_candidate_count": LEGACY_INSUFFICIENT_CANDIDATE_COUNT,
            "old_workload_count": LEGACY_INSUFFICIENT_WORKLOAD_COUNT,
            "required_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
            "required_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
            "reason": "historical 9x4 L4 identity crosswalk cannot prove the current 36-candidate x six-SCF matrix",
        },
        "gem5_l4_evidence_present": False,
        "qe_reference_evidence_present": False,
        "ppa_evidence_fabricated": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["release_subset_hash"] = _stable_hash_without(payload, "release_subset_hash")
    return payload


def build_current_goal_workload_suite_manifest(
    six_scf_manifest: Mapping[str, Any],
    *,
    six_scf_manifest_path: Path | None = None,
) -> Dict[str, Any]:
    """Build a strict six-SCF workload suite manifest suitable for L4 matrix input."""

    cases = _workload_cases_from_six_scf_manifest(six_scf_manifest)
    workload_case_ids = [str(row["case_id"]) for row in cases]
    payload: Dict[str, Any] = {
        "schema_version": DFT_CURRENT_GOAL_SIX_SCF_WORKLOAD_SUITE_SCHEMA,
        "status": "strict_six_scf_identity_manifest_only_pending_l4_regeneration",
        "suite_id": six_scf_manifest.get("suite_id") or "dft_current_goal_six_scf_l4_suite",
        "source_bundle_id": six_scf_manifest.get("bundle_id"),
        "strict": True,
        "descriptor_plus_runnable_bundle": bool(six_scf_manifest.get("descriptor_plus_runnable_bundle", False)),
        "expected_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        "workload_case_count": len(workload_case_ids),
        "case_count": len(cases),
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "workload_classes": [str(row["class_id"]) for row in cases],
        "workload_case_ids": workload_case_ids,
        "cases": cases,
        "source_artifacts": {"dft_scf_six_class_bundle_manifest": _source_ref(six_scf_manifest_path) if six_scf_manifest_path else None},
        "legacy_9x4_crosswalk_assessment": {
            "status": "insufficient_for_current_goal",
            "blocker_id": "old_9x4_crosswalk_insufficient_for_36x6_current_goal",
            "old_candidate_count": LEGACY_INSUFFICIENT_CANDIDATE_COUNT,
            "old_workload_count": LEGACY_INSUFFICIENT_WORKLOAD_COUNT,
            "required_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
            "required_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        },
        "final_real_qe_evidence": False,
        "gem5_l4_evidence_present": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["suite_hash"] = _stable_hash_without(payload, "suite_hash")
    return payload


def build_current_goal_l4_crosswalk(
    release_subset: Mapping[str, Any],
    workload_suite: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build exact structured crosswalks for a regenerated current-goal L4 root."""

    candidate_ids = [str(item) for item in _as_list(release_subset.get("legal_candidate_ids"))]
    cases = [row for row in _as_list(workload_suite.get("cases")) if isinstance(row, Mapping)]
    candidate_crosswalk = {
        candidate_id: {
            "current_goal_candidate_id": candidate_id,
            "l4_candidate_id": candidate_id,
            "equivalence_scope": "same_identity_regenerated_l4",
            "confidence": 1.0,
            "match_basis": "regenerated L4 root preserves current-goal Step5 candidate identity exactly",
            "many_to_one_allowed": False,
        }
        for candidate_id in candidate_ids
    }
    workload_crosswalk = {
        str(case.get("class_id")): {
            "current_goal_workload_class_id": str(case.get("class_id")),
            "current_goal_workload_case_id": str(case.get("case_id")),
            "l4_workload_case_ids": [str(case.get("case_id"))],
            "equivalence_scope": "same_strict_scf_workload",
            "confidence": 1.0,
            "match_basis": "regenerated L4 root uses the strict six-SCF case id from the bundle manifest",
        }
        for case in cases
    }
    payload: Dict[str, Any] = {
        "schema_version": DFT_CURRENT_GOAL_L4_CROSSWALK_SCHEMA,
        "status": "exact_structured_crosswalk_for_regenerated_current_goal_l4_root",
        "candidate_crosswalk": candidate_crosswalk,
        "workload_crosswalk": workload_crosswalk,
        "candidate_crosswalk_count": len(candidate_crosswalk),
        "workload_crosswalk_count": len(workload_crosswalk),
        "expected_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
        "expected_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        "regenerated_l4_root_expected_row_count": len(candidate_ids) * len(workload_crosswalk),
        "legacy_9x4_crosswalk_assessment": {
            "status": "insufficient_for_current_goal",
            "blocker_id": "old_9x4_crosswalk_insufficient_for_36x6_current_goal",
            "old_candidate_count": LEGACY_INSUFFICIENT_CANDIDATE_COUNT,
            "old_workload_count": LEGACY_INSUFFICIENT_WORKLOAD_COUNT,
            "required_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
            "required_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
            "required_row_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT * EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        },
        "gem5_l4_evidence_present": False,
        "qe_reference_evidence_present": False,
        "ppa_evidence_fabricated": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["crosswalk_hash"] = _stable_hash_without(payload, "crosswalk_hash")
    return payload


def build_pending_current_goal_l4_root(
    out_dir: Path,
    release_subset: Mapping[str, Any],
    workload_suite: Mapping[str, Any],
) -> Dict[str, Any]:
    """Write a blocked/pending 36x6 L4 root with no fabricated evidence rows."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = build_l4_evidence_matrix(release_subset, workload_suite, evidence_rows=[])
    report = build_coverage_claim_report(matrix)
    complete_report = {
        "schema_version": "dse.codesign.complete_dse_full_l4_report.v1",
        "status": "blocked_or_partial",
        "release_subset_path": str(out_dir / "release_subset_manifest.json"),
        "workload_suite_path": str(out_dir / "workload_suite_manifest.json"),
        "gem5_preflight_path": str(out_dir / "gem5_preflight.json"),
        "evidence_rows_path": str(out_dir / "evidence_rows.json"),
        "l4_evidence_matrix_path": str(out_dir / "l4_evidence_matrix.json"),
        "coverage_claim_report_path": str(out_dir / "coverage_claim_report.json"),
        "expected_row_count": matrix["expected_row_count"],
        "row_count": 0,
        "matrix_row_count": matrix["row_count"],
        "blocked_row_count": matrix["blocked_row_count"],
        "claims": {
            "foundation_artifacts_emitted": True,
            "mvp_partial": False,
            "deliverable_complete": False,
        },
        "blocker_counts": {
            "current_goal_l4_not_run": matrix["expected_row_count"],
            "missing_l4_evidence_row": matrix["expected_row_count"],
        },
        "claim_boundaries": {
            "foundation": "Current-goal L4 identity/matrix artifacts exist for 36x6 regeneration planning only.",
            "mvp_partial": "No real gem5 rows have been run in this pending root.",
            "deliverable_complete": "False until every current-goal row has real gem5, QE baseline/correctness, and calibration evidence.",
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    evidence_rows = {
        "schema_version": "dse.dft.current_goal_l4.pending_evidence_rows.v1",
        "status": "pending_no_real_gem5_qe_or_ppa_evidence",
        "rows": [],
        "row_count": 0,
        "expected_row_count": matrix["expected_row_count"],
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    preflight = {
        "schema_version": "dse.dft.current_goal_l4.pending_gem5_preflight.v1",
        "status": "blocked_pending_regenerated_l4_execution",
        "blockers": ["current_goal_l4_not_run", "no_gem5_l4_proof_files_present"],
        "gem5_binary_exists": None,
        "driver_binary_exists": None,
        "gem5_config_exists": None,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(out_dir / "l4_evidence_matrix.json", matrix)
    write_json(out_dir / "coverage_claim_report.json", report)
    write_json(out_dir / "complete_dse_full_l4_evidence_report.json", complete_report)
    write_json(out_dir / "evidence_rows.json", evidence_rows)
    write_json(out_dir / "gem5_preflight.json", preflight)
    manifest: Dict[str, Any] = {
        "schema_version": DFT_CURRENT_GOAL_L4_PENDING_ROOT_SCHEMA,
        "status": "blocked_pending_current_goal_l4_execution",
        "l4_root": str(out_dir),
        "artifacts": {
            "l4_evidence_matrix.json": _source_ref(out_dir / "l4_evidence_matrix.json"),
            "coverage_claim_report.json": _source_ref(out_dir / "coverage_claim_report.json"),
            "complete_dse_full_l4_evidence_report.json": _source_ref(out_dir / "complete_dse_full_l4_evidence_report.json"),
            "evidence_rows.json": _source_ref(out_dir / "evidence_rows.json"),
            "gem5_preflight.json": _source_ref(out_dir / "gem5_preflight.json"),
        },
        "candidate_count": len(matrix["legal_candidate_ids"]),
        "workload_case_count": len(matrix["workload_case_ids"]),
        "expected_row_count": matrix["expected_row_count"],
        "row_count": matrix["row_count"],
        "blocked_row_count": matrix["blocked_row_count"],
        "coverage_status": matrix["coverage_status"],
        "deliverable_complete_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(out_dir / "current_goal_l4_pending_root_manifest.json", manifest)
    return manifest


def build_dft_current_goal_l4_bridge(
    *,
    release_gate_path: Path,
    six_scf_manifest_path: Path,
    pending_l4_root: Path | None = None,
) -> Dict[str, Any]:
    release_gate = _load_json(Path(release_gate_path))
    six_scf_manifest = _load_json(Path(six_scf_manifest_path))
    candidate_ids = _candidate_ids_from_release_gate(release_gate)
    workload_cases = _workload_cases_from_six_scf_manifest(six_scf_manifest)
    blockers = _bridge_blockers(
        release_gate=release_gate,
        candidate_ids=candidate_ids,
        six_scf_manifest=six_scf_manifest,
        workload_cases=workload_cases,
    )
    release_subset = build_current_goal_release_subset_manifest(release_gate, release_gate_path=release_gate_path)
    workload_suite = build_current_goal_workload_suite_manifest(six_scf_manifest, six_scf_manifest_path=six_scf_manifest_path)
    crosswalk = build_current_goal_l4_crosswalk(release_subset, workload_suite)
    pending_manifest = None
    if pending_l4_root is not None:
        pending_manifest = build_pending_current_goal_l4_root(pending_l4_root, release_subset, workload_suite)
    bridge_ready = not blockers
    payload: Dict[str, Any] = {
        "schema_version": DFT_CURRENT_GOAL_L4_BRIDGE_SCHEMA,
        "status": "passed_identity_bridge_ready_for_regenerated_l4" if bridge_ready else "blocked_identity_bridge_inputs_invalid",
        "source_artifacts": {
            "dft_hardware_closure_release_gate": _source_ref(release_gate_path),
            "dft_scf_six_class_bundle_manifest": _source_ref(six_scf_manifest_path),
        },
        "expected_candidate_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT,
        "actual_candidate_count": len(candidate_ids),
        "expected_workload_count": EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        "actual_workload_count": len(workload_cases),
        "expected_l4_row_count": EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT * EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT,
        "actual_l4_row_count": len(candidate_ids) * len(workload_cases),
        "candidate_ids": candidate_ids,
        "workload_case_ids": [str(row.get("case_id")) for row in workload_cases],
        "blocker_count": len(blockers),
        "blockers": blockers,
        "legacy_9x4_crosswalk_assessment": crosswalk["legacy_9x4_crosswalk_assessment"],
        "release_subset_manifest": release_subset,
        "workload_suite_manifest": workload_suite,
        "structured_crosswalk": crosswalk,
        "pending_l4_root_manifest": pending_manifest,
        "gem5_l4_evidence_present": False,
        "qe_reference_evidence_present": False,
        "ppa_evidence_fabricated": False,
        "hardware_completion_eligible": False,
        "final_closure_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["bridge_hash"] = _stable_hash_without(payload, "bridge_hash")
    return payload


def write_dft_current_goal_l4_bridge(
    out_dir: Path,
    *,
    release_gate_path: Path,
    six_scf_manifest_path: Path,
    emit_pending_l4_root: bool = True,
    pending_l4_root: Path | None = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pending_root = pending_l4_root if pending_l4_root is not None else (out_dir / "current_goal_l4_root" if emit_pending_l4_root else None)
    bridge = build_dft_current_goal_l4_bridge(
        release_gate_path=Path(release_gate_path),
        six_scf_manifest_path=Path(six_scf_manifest_path),
        pending_l4_root=pending_root,
    )
    write_json(out_dir / "release_subset_manifest.json", bridge["release_subset_manifest"])
    write_json(out_dir / "workload_suite_manifest.json", bridge["workload_suite_manifest"])
    write_json(out_dir / "current_goal_l4_crosswalk.json", bridge["structured_crosswalk"])
    write_json(out_dir / "dft_current_goal_l4_bridge.json", bridge)
    status = {
        "schema_version": DFT_CURRENT_GOAL_L4_STATUS_SCHEMA,
        "status": "passed" if bridge["status"].startswith("passed_") else "blocked",
        "bridge_status": bridge["status"],
        "candidate_count": bridge["actual_candidate_count"],
        "workload_case_count": bridge["actual_workload_count"],
        "expected_l4_row_count": bridge["expected_l4_row_count"],
        "actual_l4_row_count": bridge["actual_l4_row_count"],
        "blocker_count": bridge["blocker_count"],
        "release_subset_manifest": "release_subset_manifest.json",
        "workload_suite_manifest": "workload_suite_manifest.json",
        "current_goal_l4_crosswalk": "current_goal_l4_crosswalk.json",
        "pending_l4_root": str(pending_root) if pending_root is not None else None,
        "legacy_9x4_crosswalk_status": bridge["legacy_9x4_crosswalk_assessment"]["status"],
        "final_closure_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_current_goal_l4_bridge_status.json", status)
    return status


__all__ = [
    "CLAIM_BOUNDARY",
    "DFT_CURRENT_GOAL_L4_BRIDGE_SCHEMA",
    "DFT_CURRENT_GOAL_L4_CROSSWALK_SCHEMA",
    "DFT_CURRENT_GOAL_RELEASE_SUBSET_SCHEMA",
    "DFT_CURRENT_GOAL_SIX_SCF_WORKLOAD_SUITE_SCHEMA",
    "EXPECTED_CURRENT_GOAL_CANDIDATE_COUNT",
    "EXPECTED_CURRENT_GOAL_WORKLOAD_COUNT",
    "build_current_goal_l4_crosswalk",
    "build_current_goal_release_subset_manifest",
    "build_current_goal_workload_suite_manifest",
    "build_dft_current_goal_l4_bridge",
    "build_pending_current_goal_l4_root",
    "write_dft_current_goal_l4_bridge",
]
