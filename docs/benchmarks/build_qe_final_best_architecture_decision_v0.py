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
        return None, None, ["missing_stage_d_implementation_evidence"]
    path = resolve_ref(path_ref, base_dir=base_dir, repo_root=repo_root)
    if path is None or not path.exists():
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
        blockers = row.get("blockers")
        if isinstance(blockers, list):
            reasons.extend(str(item) for item in blockers if item)
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
        reasons.extend(stage_d_reasons)
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
            stage_d_policy_satisfied=not stage_d_reasons,
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
            "family": row.get("family"),
            "workload_id": row.get("workload_id"),
            "case_id": row.get("case_id"),
            "screening_rank": row.get("screening_rank"),
            "evidence_tier": evidence_tier,
            "strict_b4_event_delta_ticks": _metric(b4_payload, "candidate_device_event_delta_ticks"),
            "successful_dma_transfer_bytes": _metric(b4_payload, "successful_dma_transfer_bytes"),
            "stage_d_tier": final_policy.stage_d_tier_from_evidence(stage_d_payload),
            "stage_d_claim_ceiling": stage_d_payload.get("claim_ceiling") if isinstance(stage_d_payload, Mapping) else None,
            "systemc_cycle_evidence_ref": evidence_refs["systemc_cycle_evidence"],
            "systemc_cycle_evidence_sha256": systemc_cycle_sha,
            "final_observed_conclusion_ceiling": row.get("final_observed_conclusion_ceiling"),
            "eligible": evidence_tier == evidence_tiers.FINAL_BEST_ELIGIBLE and not unique_reasons,
            "ineligible_reasons": unique_reasons,
            "evidence_refs": evidence_refs,
            "evidence_hashes": evidence_hashes,
        }
        ranking_table.append(rank_row)
        if unique_reasons:
            ineligible.append(rank_row)
        else:
            eligible.append(rank_row)

    eligible_sorted = sorted(eligible, key=_score_candidate)
    ranking_table_sorted = sorted(ranking_table, key=lambda item: (0 if item.get("eligible") else 1, _score_candidate(item)))
    winner_row = eligible_sorted[0] if eligible_sorted else None
    winner = None
    if winner_row is not None:
        winner = {
            "candidate_id": winner_row["candidate_id"],
            "family": winner_row.get("family"),
            "workload_id": winner_row.get("workload_id"),
            "case_id": winner_row.get("case_id"),
            "decision_rank": 1,
            "claim_label": final_policy.claim_label_for_policy(winner_row, policy),
            "evidence_tier": winner_row.get("evidence_tier"),
            "strict_b4_event_delta_ticks": winner_row.get("strict_b4_event_delta_ticks"),
            "stage_d_tier": winner_row.get("stage_d_tier"),
            "systemc_cycle_evidence_ref": winner_row.get("systemc_cycle_evidence_ref"),
            "systemc_cycle_evidence_sha256": winner_row.get("systemc_cycle_evidence_sha256"),
            "evidence_refs": winner_row.get("evidence_refs"),
            "evidence_hashes": winner_row.get("evidence_hashes"),
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
        },
        "source_hashes": {
            "manifest_sha256": sha256_file(manifest_path),
            "claim_ceiling_status_matrix_sha256": sha256_file(matrix_path),
            "backend_report_collection_sha256": sha256_file(Path(backend_ref)) if backend_ref is not None else None,
        },
        "eligible_candidates": eligible_sorted,
        "ineligible_candidates": sorted(ineligible, key=_score_candidate),
        "ranking_table": ranking_table_sorted,
        "claim_ceiling": (
            f"final_best_under_{policy.get('minimum_stage_d_tier')}_policy"
            if winner is not None
            else "bounded_proxy_leader_only_no_final_best"
        ),
        "non_claims": list(policy.get("non_claims", [])) + [
            "bounded_proxy_rerank_is_not_final_best_architecture",
            "no_final_best_without_same_candidate_stage_c_stage_d_strict_b4_and_systemc_cycle_evidence",
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
