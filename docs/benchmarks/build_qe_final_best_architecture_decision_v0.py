#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import gmtime, strftime
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import final_best_policy_v0 as final_policy
import dse_evidence_tier_classifier_v0 as evidence_tiers
from unified_dse import stage_c_qe_correctness, stage_d_implementation_evidence

SCHEMA_VERSION = "qe_fpga_final_best_architecture_decision_v0"
DEFAULT_OUTPUT_NAME = "qe_fpga_final_best_architecture_decision_v0.json"


class FinalBestDecisionError(ValueError):
    pass


def load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalBestDecisionError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def resolve_ref(ref: Any, *, base_dir: Path, repo_root: Path | None = None) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    raw = Path(ref)
    candidates = [raw] if raw.is_absolute() else [base_dir / raw]
    if repo_root is not None and not raw.is_absolute():
        candidates.append(repo_root / raw)
    candidates.append(raw.resolve(strict=False) if raw.is_absolute() else raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve(strict=False)
    first = candidates[0]
    return first.resolve(strict=False)


def _rows_by_candidate(matrix: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    rows = matrix.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and row.get("candidate_id"):
                result[str(row["candidate_id"])] = row
    return result


def _manifest_candidate_runs(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    runs = manifest.get("candidate_runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, Mapping)]
    selected = manifest.get("selected_backend_requests")
    if isinstance(selected, list):
        return [
            {"candidate_id": Path(str(path)).stem, "stage_b0_request": str(path)}
            for path in selected
        ]
    return []


def _catalog_freeze_manifest_ref(manifest: Mapping[str, Any]) -> str | None:
    for key in ("catalog_freeze_manifest", "catalog_freeze_manifest_ref", "microarchitecture_catalog_freeze_manifest"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    refs = manifest.get("source_refs")
    if isinstance(refs, Mapping):
        for key in ("catalog_freeze_manifest", "microarchitecture_catalog_freeze_manifest"):
            value = refs.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _catalog_entry_id(candidate_id: str, run: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    for value in (
        row.get("microarchitecture_id"),
        row.get("catalog_entry_id"),
        row.get("microarchitecture_catalog_id"),
        run.get("microarchitecture_id"),
        run.get("catalog_entry_id"),
    ):
        if isinstance(value, str) and value:
            return value
    level1 = run.get("level1_search")
    if isinstance(level1, Mapping):
        for key in ("microarchitecture_id", "catalog_entry_id", "microarchitecture_catalog_id"):
            value = level1.get(key)
            if isinstance(value, str) and value:
                return value
    return candidate_id


def _freeze_partition_for_catalog_id(freeze_manifest: Mapping[str, Any] | None, catalog_entry_id: str) -> str | None:
    if not isinstance(freeze_manifest, Mapping):
        return None
    partitions = freeze_manifest.get("partitions")
    if not isinstance(partitions, Mapping):
        return None
    for partition, values in partitions.items():
        if catalog_entry_id in _list_of_strings(values):
            return str(partition)
    return None


def _competitive_catalog_ids(freeze_manifest: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(freeze_manifest, Mapping):
        return set()
    partitions = freeze_manifest.get("partitions")
    if not isinstance(partitions, Mapping):
        return set()
    return set(_list_of_strings(partitions.get("competitive_evaluable")))


def _is_unresolved_dominance_reason(reason: Any) -> bool:
    text = str(reason)
    return text.startswith(
        (
            "missing_",
            "candidate_evidence_alignment_mismatch",
            "systemc_cycle_evidence_load_failed",
            "systemc_cycle_evidence_sha256_mismatch",
            "catalog_freeze_manifest_not_passed",
            "candidate_missing_from_catalog_freeze_manifest",
        )
    )


def _is_unresolved_for_dominance(row: Mapping[str, Any]) -> bool:
    reasons = row.get("ineligible_reasons")
    if not isinstance(reasons, list):
        return False
    return any(_is_unresolved_dominance_reason(reason) for reason in reasons)


def _candidate_id_from_run(run: Mapping[str, Any]) -> str | None:
    value = run.get("candidate_id")
    return str(value) if value is not None and str(value) else None


def _metric(report: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(report, Mapping):
        return None
    metrics = report.get("metrics")
    if isinstance(metrics, Mapping):
        return metrics.get(key)
    return None


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _systemc_cycle_ref_from(
    candidate_id: str,
    run: Mapping[str, Any],
    row: Mapping[str, Any],
    backend_collection: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    row_refs = _mapping(row.get("evidence_refs"))
    row_hashes = _mapping(row.get("evidence_hashes"))
    run_refs = _mapping(run.get("evidence_refs"))
    run_hashes = _mapping(run.get("evidence_hashes"))

    backend_ref = None
    backend_sha = None
    if isinstance(backend_collection, Mapping):
        candidate_reports = backend_collection.get("candidate_reports")
        candidate_entry = _mapping(candidate_reports).get(candidate_id) if isinstance(candidate_reports, Mapping) else None
        if isinstance(candidate_entry, Mapping):
            for key in (
                "systemc_cycle_evidence",
                "systemc_cycle_accounted_evidence",
                "SystemC-cycle-accounted",
                "systemc-cycle-accounted",
                "B2_cycle_accounted",
            ):
                entry = candidate_entry.get(key)
                if isinstance(entry, Mapping):
                    backend_ref = _first_string(
                        entry.get("report_ref"),
                        entry.get("artifact_ref"),
                        entry.get("systemc_cycle_evidence_ref"),
                    )
                    backend_sha = _first_string(
                        entry.get("sha256"),
                        entry.get("artifact_sha256"),
                        entry.get("systemc_cycle_evidence_sha256"),
                    )
                    if backend_ref or backend_sha:
                        break

    ref = _first_string(
        row.get("systemc_cycle_evidence_ref"),
        row.get("systemc_cycle_accounted_evidence_ref"),
        row_refs.get("systemc_cycle_evidence"),
        row_refs.get("systemc_cycle_accounted_evidence"),
        run.get("systemc_cycle_evidence_ref"),
        run.get("systemc_cycle_accounted_evidence_ref"),
        run_refs.get("systemc_cycle_evidence"),
        run_refs.get("systemc_cycle_accounted_evidence"),
        backend_ref,
    )
    sha = _first_string(
        row.get("systemc_cycle_evidence_sha256"),
        row.get("systemc_cycle_accounted_evidence_sha256"),
        row_hashes.get("systemc_cycle_evidence_sha256"),
        row_hashes.get("systemc_cycle_accounted_evidence_sha256"),
        run.get("systemc_cycle_evidence_sha256"),
        run.get("systemc_cycle_accounted_evidence_sha256"),
        run_hashes.get("systemc_cycle_evidence_sha256"),
        run_hashes.get("systemc_cycle_accounted_evidence_sha256"),
        backend_sha,
    )
    return ref, sha


def _load_systemc_cycle_evidence(
    candidate_id: str,
    run: Mapping[str, Any],
    row: Mapping[str, Any],
    backend_collection: Mapping[str, Any] | None,
    *,
    manifest_dir: Path,
    repo_root: Path | None,
) -> tuple[Path | None, Mapping[str, Any] | None, str | None, list[str]]:
    ref, declared_sha = _systemc_cycle_ref_from(candidate_id, run, row, backend_collection)
    reasons: list[str] = []
    if not ref:
        return None, None, None, ["missing_systemc_cycle_evidence", "missing_systemc_cycle_evidence_ref"]

    path = resolve_ref(ref, base_dir=manifest_dir, repo_root=repo_root)
    computed_sha = sha256_file(path)
    evidence_sha = computed_sha or declared_sha
    payload: Mapping[str, Any] | None = None

    if path is None or not path.exists() or not path.is_file():
        reasons.append("missing_systemc_cycle_evidence_artifact")
    else:
        try:
            payload = load_json(path)
        except Exception as exc:
            reasons.append(f"systemc_cycle_evidence_load_failed:{exc}")

    if declared_sha and computed_sha and declared_sha != computed_sha:
        reasons.append("systemc_cycle_evidence_sha256_mismatch")
    if not evidence_sha:
        reasons.append("missing_systemc_cycle_evidence_sha256")
    if isinstance(payload, Mapping):
        payload_candidate = payload.get("candidate_id")
        if payload_candidate is None:
            reasons.append("systemc_cycle_evidence_candidate_id_missing")
        elif str(payload_candidate) != candidate_id:
            reasons.append("systemc_cycle_evidence_candidate_id_mismatch")
    return path, payload, evidence_sha, reasons


def _load_b4_report(
    candidate_id: str,
    run: Mapping[str, Any],
    backend_collection: Mapping[str, Any] | None,
    *,
    manifest_dir: Path,
    repo_root: Path | None,
) -> tuple[Path | None, Mapping[str, Any] | None, list[str]]:
    reasons: list[str] = []
    report_ref: Any = run.get("gem5_b4_report")
    if not report_ref and isinstance(backend_collection, Mapping):
        candidate_reports = backend_collection.get("candidate_reports")
        if isinstance(candidate_reports, Mapping):
            by_stage = candidate_reports.get(candidate_id)
            if isinstance(by_stage, Mapping):
                b4 = by_stage.get("B4")
                if isinstance(b4, Mapping):
                    report_ref = b4.get("report_ref")
    if not report_ref:
        return None, None, ["missing_b4_report"]
    path = resolve_ref(report_ref, base_dir=manifest_dir, repo_root=repo_root)
    if path is None or not path.exists():
        return path, None, ["missing_b4_report"]
    try:
        payload = load_json(path)
    except Exception as exc:
        return path, None, [f"b4_report_load_failed:{exc}"]
    payload_candidate = payload.get("candidate_id")
    if payload_candidate is not None and str(payload_candidate) != candidate_id:
        reasons.append("b4_candidate_id_mismatch")
    return path, payload, reasons


def _strict_b4_reasons(b4_report: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> list[str]:
    if not isinstance(b4_report, Mapping):
        return ["missing_b4_report"]
    metrics = b4_report.get("metrics")
    if not isinstance(metrics, Mapping):
        return ["missing_b4_metrics"]
    reasons: list[str] = []
    required_source = str(policy.get("required_b4_cycle_source"))
    if metrics.get("cycle_source") != required_source:
        reasons.append("b4_cycle_source_not_gem5_event_timed_device_observed")
    if metrics.get("event_timed_device_activity_observed") is not True:
        reasons.append("b4_event_timed_device_activity_not_observed")
    delta = metrics.get("candidate_device_event_delta_ticks")
    if not isinstance(delta, (int, float)) or delta <= 0:
        reasons.append("b4_candidate_event_delta_ticks_missing_or_nonpositive")
    reads = metrics.get("host_control_mmio_read_count")
    writes = metrics.get("host_control_mmio_write_count")
    if not ((isinstance(reads, int) and reads > 0) or (isinstance(writes, int) and writes > 0)):
        reasons.append("b4_mmio_activity_missing")
    return reasons


def _load_stage_c(path_ref: Any, *, base_dir: Path, repo_root: Path | None, candidate_id: str) -> tuple[Path | None, Mapping[str, Any] | None, list[str]]:
    if not path_ref:
        return None, None, ["missing_stage_c_qe_correctness_report"]
    path = resolve_ref(path_ref, base_dir=base_dir, repo_root=repo_root)
    if path is None or not path.exists():
        return path, None, ["missing_stage_c_qe_correctness_report"]
    try:
        payload = stage_c_qe_correctness.load_and_validate_qe_correctness_report(path)
    except Exception as exc:
        return path, None, [f"stage_c_report_invalid:{exc}"]
    reasons: list[str] = []
    if str(payload.get("candidate_id")) != candidate_id:
        reasons.append("stage_c_candidate_id_mismatch")
    if payload.get("qe_equivalent_scf_claim") is not True:
        reasons.append("stage_c_qe_equivalent_scf_not_proven")
    return path, payload, reasons


def _load_stage_d(path_ref: Any, *, base_dir: Path, repo_root: Path | None, candidate_id: str, policy: Mapping[str, Any]) -> tuple[Path | None, Mapping[str, Any] | None, list[str]]:
    if not path_ref:
        if not final_policy.stage_d_required_for_final_best(policy):
            return None, None, []
        return None, None, ["missing_stage_d_implementation_evidence"]
    path = resolve_ref(path_ref, base_dir=base_dir, repo_root=repo_root)
    if path is None or not path.exists():
        if not final_policy.stage_d_required_for_final_best(policy):
            return path, None, []
        return path, None, ["missing_stage_d_implementation_evidence"]
    try:
        payload = stage_d_implementation_evidence.load_and_validate_implementation_evidence(path)
    except Exception as exc:
        return path, None, [f"stage_d_evidence_invalid:{exc}"]
    reasons: list[str] = []
    if str(payload.get("candidate_id")) != candidate_id:
        reasons.append("stage_d_candidate_id_mismatch")
    ok, policy_reasons = final_policy.stage_d_satisfies_policy(payload, policy)
    if not ok:
        reasons.extend(policy_reasons)
    return path, payload, reasons


def _score_candidate(item: Mapping[str, Any]) -> tuple[float, float, int, str]:
    event_ticks = item.get("strict_b4_event_delta_ticks")
    if not isinstance(event_ticks, (int, float)):
        event_ticks = float("inf")
    dma_bytes = item.get("successful_dma_transfer_bytes")
    if not isinstance(dma_bytes, (int, float)):
        dma_bytes = float("inf")
    screening_rank = item.get("screening_rank")
    if not isinstance(screening_rank, int):
        screening_rank = 10**9
    return (float(event_ticks), float(dma_bytes), screening_rank, str(item.get("candidate_id") or ""))


def _release_gate_fields(
    *,
    policy: Mapping[str, Any],
    evidence_refs: Mapping[str, Any],
    evidence_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    """Flatten same-candidate evidence refs for release-boundary validators.

    The decision payload already carries a structured ``evidence_refs`` object.
    The release claim-boundary checker intentionally scans arbitrary JSON
    objects without schema-specific joins, so final-best rows also need direct
    fields whose names spell out Stage C / strict B4 / SystemC-cycle evidence.
    """

    return {
        "policy_id": policy.get("policy_id"),
        "stage_d_required_for_final_best": final_policy.stage_d_required_for_final_best(policy),
        "stage_c_report_ref": evidence_refs.get("stage_c_report"),
        "stage_c_report_sha256": evidence_hashes.get("stage_c_report_sha256"),
        "strict_b4_report_ref": evidence_refs.get("b4_report"),
        "strict_b4_report_sha256": evidence_hashes.get("b4_report_sha256"),
        "stage_d_report_ref": evidence_refs.get("stage_d_report"),
        "stage_d_report_sha256": evidence_hashes.get("stage_d_report_sha256"),
        "systemc_cycle_evidence_ref": evidence_refs.get("systemc_cycle_evidence"),
        "systemc_cycle_evidence_sha256": evidence_hashes.get("systemc_cycle_evidence_sha256"),
    }


def build_decision(
    *,
    manifest_path: Path,
    claim_matrix_path: Path | None = None,
    backend_report_collection_path: Path | None = None,
    policy_path: Path | None = None,
    output_ref: Path | None = None,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    manifest_dir = manifest_path.resolve().parent
    repo_root_value = manifest.get("repo_root")
    repo_root = Path(str(repo_root_value)).resolve(strict=False) if repo_root_value else None
    policy = final_policy.load_policy(policy_path)

    matrix_ref = claim_matrix_path or resolve_ref(
        manifest.get("claim_ceiling_status_matrix"),
        base_dir=manifest_dir,
        repo_root=repo_root,
    )
    if matrix_ref is None:
        raise FinalBestDecisionError("claim matrix path is required or must be present in manifest")
    matrix_path = Path(matrix_ref)
    matrix = load_json(matrix_path)
    rows_by_candidate = _rows_by_candidate(matrix)

    backend_ref = backend_report_collection_path or resolve_ref(
        manifest.get("backend_report_collection"),
        base_dir=manifest_dir,
        repo_root=repo_root,
    )
    backend_collection = load_json(backend_ref) if backend_ref is not None and Path(backend_ref).exists() else None
    freeze_manifest_path = resolve_ref(
        _catalog_freeze_manifest_ref(manifest),
        base_dir=manifest_dir,
        repo_root=repo_root,
    )
    freeze_manifest = (
        load_json(freeze_manifest_path)
        if freeze_manifest_path is not None and Path(freeze_manifest_path).exists()
        else None
    )
    require_catalog_freeze = policy.get("require_catalog_freeze_membership") is True
    require_dominance = policy.get("require_dominance_closure") is True

    eligible: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    ranking_table: list[dict[str, Any]] = []

    for run in _manifest_candidate_runs(manifest):
        candidate_id = _candidate_id_from_run(run)
        if candidate_id is None:
            continue
        reasons: list[str] = []
        row = rows_by_candidate.get(candidate_id)
        if row is None:
            reasons.append("missing_claim_matrix_row")
            row = {}
        catalog_entry_id = _catalog_entry_id(candidate_id, run, row)
        freeze_partition = _freeze_partition_for_catalog_id(freeze_manifest, catalog_entry_id)
        if require_catalog_freeze:
            if not isinstance(freeze_manifest, Mapping):
                reasons.append("missing_catalog_freeze_manifest")
            elif freeze_manifest.get("freeze_status") != "passed":
                reasons.append("catalog_freeze_manifest_not_passed")
            elif freeze_partition != "competitive_evaluable":
                if freeze_partition in {"coverage_only", "excluded_from_best_universe"}:
                    reasons.append(f"candidate_not_in_competitive_catalog_partition:{freeze_partition}")
                else:
                    reasons.append("candidate_missing_from_catalog_freeze_manifest")
        blockers = row.get("blockers")
        if isinstance(blockers, list):
            reasons.extend(final_policy.filter_policy_blockers([str(item) for item in blockers if item], policy))
        if row.get("same_candidate_evidence_only") is False:
            reasons.append("candidate_evidence_alignment_mismatch")

        stage_c_path, stage_c_payload, stage_c_reasons = _load_stage_c(
            row.get("stage_c_report_ref"),
            base_dir=manifest_dir,
            repo_root=repo_root,
            candidate_id=candidate_id,
        )
        reasons.extend(stage_c_reasons)
        stage_d_path, stage_d_payload, stage_d_reasons = _load_stage_d(
            row.get("stage_d_report_ref"),
            base_dir=manifest_dir,
            repo_root=repo_root,
            candidate_id=candidate_id,
            policy=policy,
        )
        policy_stage_d_reasons = final_policy.filter_policy_blockers(stage_d_reasons, policy)
        reasons.extend(policy_stage_d_reasons)
        optional_precision_upgrade_risks = final_policy.optional_precision_upgrade_risks(stage_d_payload, policy)
        b4_path, b4_payload, b4_load_reasons = _load_b4_report(
            candidate_id,
            run,
            backend_collection,
            manifest_dir=manifest_dir,
            repo_root=repo_root,
        )
        reasons.extend(b4_load_reasons)
        strict_b4_reasons = _strict_b4_reasons(b4_payload, policy)
        reasons.extend(strict_b4_reasons)
        systemc_cycle_path, systemc_cycle_payload, systemc_cycle_sha, systemc_cycle_reasons = _load_systemc_cycle_evidence(
            candidate_id,
            run,
            row,
            backend_collection,
            manifest_dir=manifest_dir,
            repo_root=repo_root,
        )
        reasons.extend(systemc_cycle_reasons)

        evidence_tier, classifier_reasons = evidence_tiers.classify_candidate_evidence(
            same_candidate_evidence_only=row.get("same_candidate_evidence_only") is not False,
            stage_c_correct=not stage_c_reasons,
            strict_b4_evidence=not b4_load_reasons and not strict_b4_reasons,
            stage_d_policy_satisfied=not policy_stage_d_reasons,
            systemc_cycle_evidence=not systemc_cycle_reasons,
            projection_screened=(
                row.get("screening_rank") is not None
                or row.get("final_observed_conclusion_ceiling") not in (None, "", "no_evidence")
                or b4_payload is not None
            ),
            catalog_provenance=bool(row.get("catalog_entry_id") or row.get("microarchitecture_catalog_id")),
            existing_blockers=reasons,
        )
        reasons.extend(classifier_reasons)

        unique_reasons = []
        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(reason)

        evidence_refs = {
            "stage_b0_request": run.get("stage_b0_request"),
            "stage_c_report": str(stage_c_path) if stage_c_path else row.get("stage_c_report_ref"),
            "stage_d_report": str(stage_d_path) if stage_d_path else row.get("stage_d_report_ref"),
            "b4_report": str(b4_path) if b4_path else run.get("gem5_b4_report"),
            "systemc_cycle_evidence": (
                str(systemc_cycle_path)
                if systemc_cycle_path
                else _systemc_cycle_ref_from(candidate_id, run, row, backend_collection)[0]
            ),
        }
        evidence_hashes = {
            "stage_c_report_sha256": sha256_file(stage_c_path),
            "stage_d_report_sha256": sha256_file(stage_d_path),
            "b4_report_sha256": sha256_file(b4_path),
            "systemc_cycle_evidence_sha256": systemc_cycle_sha,
        }
        rank_row = {
            "candidate_id": candidate_id,
            "catalog_entry_id": catalog_entry_id,
            "catalog_freeze_partition": freeze_partition,
            "family": row.get("family"),
            "workload_id": row.get("workload_id"),
            "case_id": row.get("case_id"),
            "screening_rank": row.get("screening_rank"),
            "evidence_tier": evidence_tier,
            "strict_b4_event_delta_ticks": _metric(b4_payload, "candidate_device_event_delta_ticks"),
            "successful_dma_transfer_bytes": _metric(b4_payload, "successful_dma_transfer_bytes"),
            "stage_d_tier": final_policy.stage_d_tier_from_evidence(stage_d_payload),
            "stage_d_claim_ceiling": stage_d_payload.get("claim_ceiling") if isinstance(stage_d_payload, Mapping) else None,
            "optional_precision_upgrade_risks": optional_precision_upgrade_risks,
            "systemc_cycle_evidence_ref": evidence_refs["systemc_cycle_evidence"],
            "systemc_cycle_evidence_sha256": systemc_cycle_sha,
            "final_observed_conclusion_ceiling": row.get("final_observed_conclusion_ceiling"),
            "eligible": evidence_tier == evidence_tiers.FINAL_BEST_ELIGIBLE and not unique_reasons,
            "ineligible_reasons": unique_reasons,
            "evidence_refs": evidence_refs,
            "evidence_hashes": evidence_hashes,
            **_release_gate_fields(
                policy=policy,
                evidence_refs=evidence_refs,
                evidence_hashes=evidence_hashes,
            ),
        }
        ranking_table.append(rank_row)
        if unique_reasons:
            ineligible.append(rank_row)
        else:
            eligible.append(rank_row)

    eligible_sorted = sorted(eligible, key=_score_candidate)
    ranking_table_sorted = sorted(ranking_table, key=lambda item: (0 if item.get("eligible") else 1, _score_candidate(item)))
    winner_row = eligible_sorted[0] if eligible_sorted else None
    dominance_closure: dict[str, Any] = {
        "required": require_dominance,
        "status": "not_required" if not require_dominance else "not_evaluated",
        "blocking_higher_ranked_competitive_candidates": [],
        "resolved_higher_ranked_competitive_candidates": [],
        "competitive_catalog_ids": sorted(_competitive_catalog_ids(freeze_manifest)),
    }
    if winner_row is not None and require_dominance:
        winner_rank = winner_row.get("screening_rank")
        blockers: list[dict[str, Any]] = []
        resolved_higher: list[dict[str, Any]] = []
        if not isinstance(winner_rank, int):
            blockers.append(
                {
                    "candidate_id": winner_row.get("candidate_id"),
                    "blocker": "winner_missing_screening_rank_for_dominance_closure",
                }
            )
        else:
            eligible_ids = {str(item.get("candidate_id")) for item in eligible}
            for item in ranking_table:
                item_rank = item.get("screening_rank")
                if not isinstance(item_rank, int) or item_rank >= winner_rank:
                    continue
                if item.get("catalog_freeze_partition") != "competitive_evaluable":
                    continue
                if str(item.get("candidate_id")) in eligible_ids:
                    continue
                if not _is_unresolved_for_dominance(item):
                    resolved_higher.append(
                        {
                            "candidate_id": item.get("candidate_id"),
                            "catalog_entry_id": item.get("catalog_entry_id"),
                            "screening_rank": item_rank,
                            "resolution": "resolved_nonpass_or_evidence_reranked_below_winner",
                            "ineligible_reasons": item.get("ineligible_reasons", []),
                        }
                    )
                    continue
                blockers.append(
                    {
                        "candidate_id": item.get("candidate_id"),
                        "catalog_entry_id": item.get("catalog_entry_id"),
                        "screening_rank": item_rank,
                        "blocker": f"unresolved_higher_ranked_competitive_candidate:{item.get('candidate_id')}",
                        "ineligible_reasons": item.get("ineligible_reasons", []),
                    }
                )
        dominance_closure["blocking_higher_ranked_competitive_candidates"] = blockers
        dominance_closure["resolved_higher_ranked_competitive_candidates"] = resolved_higher
        dominance_closure["status"] = "passed" if not blockers else "blocked"
        if blockers:
            winner_row = None
    winner = None
    if winner_row is not None:
        winner = {
            "candidate_id": winner_row["candidate_id"],
            "catalog_entry_id": winner_row.get("catalog_entry_id"),
            "catalog_freeze_partition": winner_row.get("catalog_freeze_partition"),
            "family": winner_row.get("family"),
            "workload_id": winner_row.get("workload_id"),
            "case_id": winner_row.get("case_id"),
            "decision_rank": 1,
            "claim_label": final_policy.claim_label_for_policy(winner_row, policy),
            "evidence_tier": winner_row.get("evidence_tier"),
            "strict_b4_event_delta_ticks": winner_row.get("strict_b4_event_delta_ticks"),
            "stage_d_tier": winner_row.get("stage_d_tier"),
            "optional_precision_upgrade_risks": winner_row.get("optional_precision_upgrade_risks"),
            "systemc_cycle_evidence_ref": winner_row.get("systemc_cycle_evidence_ref"),
            "systemc_cycle_evidence_sha256": winner_row.get("systemc_cycle_evidence_sha256"),
            "evidence_refs": winner_row.get("evidence_refs"),
            "evidence_hashes": winner_row.get("evidence_hashes"),
            **_release_gate_fields(
                policy=policy,
                evidence_refs=_mapping(winner_row.get("evidence_refs")),
                evidence_hashes=_mapping(winner_row.get("evidence_hashes")),
            ),
        }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "decision_status": "winner_selected" if winner is not None else "blocked_no_eligible_candidates",
        "winner": winner,
        "decision_scope": policy.get("decision_scope"),
        "policy_ref": str(policy_path) if policy_path is not None else "default:hls_synthesis_minimum",
        "policy": policy,
        "source_refs": {
            "manifest": str(manifest_path),
            "claim_ceiling_status_matrix": str(matrix_path),
            "backend_report_collection": str(backend_ref) if backend_ref is not None else None,
            "catalog_freeze_manifest": str(freeze_manifest_path) if freeze_manifest_path is not None else None,
        },
        "source_hashes": {
            "manifest_sha256": sha256_file(manifest_path),
            "claim_ceiling_status_matrix_sha256": sha256_file(matrix_path),
            "backend_report_collection_sha256": sha256_file(Path(backend_ref)) if backend_ref is not None else None,
            "catalog_freeze_manifest_sha256": sha256_file(Path(freeze_manifest_path)) if freeze_manifest_path is not None else None,
        },
        "dominance_closure": dominance_closure,
        "eligible_candidates": eligible_sorted,
        "ineligible_candidates": sorted(ineligible, key=_score_candidate),
        "ranking_table": ranking_table_sorted,
        "claim_ceiling": (
            "final_best_under_systemc_b4_minimum_policy"
            if winner is not None and not final_policy.stage_d_required_for_final_best(policy)
            else (
                f"final_best_under_{policy.get('minimum_stage_d_tier')}_policy"
                if winner is not None
                else "bounded_proxy_leader_only_no_final_best"
            )
        ),
        "non_claims": list(policy.get("non_claims", [])) + [
            "bounded_proxy_rerank_is_not_final_best_architecture",
            (
                "no_final_best_without_same_candidate_stage_c_strict_b4_systemc_cycle_catalog_freeze_and_dominance_evidence"
                if not final_policy.stage_d_required_for_final_best(policy)
                else "no_final_best_without_same_candidate_stage_c_stage_d_strict_b4_and_systemc_cycle_evidence"
            ),
            "no_hardware_cycle_accuracy_claim_from_gem5_event_ticks",
            "systemc_cycle_accounted_is_not_rtl_cycle_accurate_timing",
        ],
    }
    if output_ref is not None:
        payload["decision_ref"] = str(output_ref)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build QE FPGA final-best architecture decision v0.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--claim-matrix", type=Path)
    parser.add_argument("--backend-report-collection", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    decision = build_decision(
        manifest_path=args.manifest,
        claim_matrix_path=args.claim_matrix,
        backend_report_collection_path=args.backend_report_collection,
        policy_path=args.policy,
        output_ref=args.output,
    )
    write_json(args.output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
