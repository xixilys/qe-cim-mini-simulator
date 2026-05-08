#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import gmtime, strftime
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "qe_candidate_evidence_manifest_v0"
SURVEY_CATALOG_TIER = "survey-catalog"
PROJECTION_SCREENED_TIER = "projection-screened"
SYSTEMC_CYCLE_ACCOUNTED_TIER = "systemc-cycle-accounted"
FINAL_BEST_ELIGIBLE_TIER = "final-best-eligible"
EVIDENCE_TIER_LABELS = {
    SURVEY_CATALOG_TIER,
    PROJECTION_SCREENED_TIER,
    SYSTEMC_CYCLE_ACCOUNTED_TIER,
    FINAL_BEST_ELIGIBLE_TIER,
}


class CandidateManifestError(ValueError):
    pass


def load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CandidateManifestError(f"expected JSON object: {path}")
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


def _resolve(ref: Any, base: Path) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    path = Path(ref)
    if path.is_absolute():
        return path.resolve(strict=False)
    return (base / path).resolve(strict=False)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows_by_candidate(matrix: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(matrix, Mapping):
        return {}
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping) and row.get("candidate_id") is not None:
            result[str(row["candidate_id"])] = row
    return result


def _tier_counts(candidates: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in sorted(EVIDENCE_TIER_LABELS)}
    for candidate in candidates:
        label = str(candidate.get("evidence_tier") or SURVEY_CATALOG_TIER)
        if label not in counts:
            counts[label] = 0
        counts[label] += 1
    return counts


def _artifact(path: Path | None) -> dict[str, Any]:
    return {
        "ref": str(path) if path is not None else None,
        "sha256": sha256_file(path),
    }


def _request_context(request_path: Path | None) -> dict[str, Any]:
    if request_path is None or not request_path.exists():
        return {}
    payload = load_json(request_path)
    candidate_identity = _mapping(payload.get("candidate_identity"))
    design_axes = _mapping(candidate_identity.get("design_axes"))
    workload_identity = _mapping(payload.get("workload_identity"))
    domain_extension = _mapping(payload.get("domain_extension"))
    qe_extension = _mapping(domain_extension.get("qe"))
    candidate_id = payload.get("candidate_id") or candidate_identity.get("candidate_id") or request_path.stem
    workload_id = workload_identity.get("workload_id") or qe_extension.get("workload_id") or qe_extension.get("case_id")
    case_id = qe_extension.get("case_id") or workload_id
    family = design_axes.get("family") or candidate_identity.get("architecture_template_id")
    return {
        "candidate_id": str(candidate_id) if candidate_id is not None else None,
        "family": str(family) if family is not None else None,
        "workload_id": str(workload_id) if workload_id is not None else None,
        "case_id": str(case_id) if case_id is not None else None,
        "design_axes": dict(design_axes),
        "candidate_identity": dict(candidate_identity),
    }


def build_manifest(e2e_manifest_path: Path, *, output_ref: Path | None = None) -> dict[str, Any]:
    e2e_manifest = load_json(e2e_manifest_path)
    base = e2e_manifest_path.resolve().parent
    runs = e2e_manifest.get("candidate_runs")
    if not isinstance(runs, list):
        raise CandidateManifestError("E2E manifest must contain candidate_runs list")
    claim_matrix_path = _resolve(e2e_manifest.get("claim_ceiling_status_matrix"), base)
    claim_matrix = load_json(claim_matrix_path) if claim_matrix_path is not None and claim_matrix_path.exists() else None
    rows_by_candidate = _rows_by_candidate(claim_matrix)
    catalog_freeze_manifest = _resolve(e2e_manifest.get("catalog_freeze_manifest"), base)
    candidates: list[dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping):
            raise CandidateManifestError(f"candidate_runs[{index}] must be an object")
        request_path = _resolve(run.get("stage_b0_request"), base)
        context = _request_context(request_path)
        candidate_id = str(run.get("candidate_id") or context.get("candidate_id") or (request_path.stem if request_path else f"candidate_{index}"))
        row = rows_by_candidate.get(candidate_id, {})
        level1_search = _mapping(run.get("level1_search"))
        catalog_entry_id = (
            row.get("catalog_entry_id")
            or row.get("microarchitecture_id")
            or level1_search.get("catalog_entry_id")
            or level1_search.get("microarchitecture_id")
            or candidate_id
        )
        systemc_report = _resolve(run.get("systemc_backend_report"), base)
        systemc_cycle_report = _resolve(
            run.get("systemc_cycle_accounted_evidence")
            or row.get("systemc_cycle_accounted_evidence_ref"),
            base,
        )
        b4_report = _resolve(run.get("gem5_b4_report"), base)
        b4_manifest = _resolve(run.get("gem5_b4_materialization_manifest"), base)
        stage_c_report = _resolve(row.get("stage_c_report_ref"), base)
        stage_d_report = _resolve(row.get("stage_d_report_ref"), base)
        blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else run.get("blockers", [])
        candidates.append(
            {
                "candidate_id": candidate_id,
                "catalog_entry_id": str(catalog_entry_id) if catalog_entry_id is not None else None,
                "catalog_freeze_partition": row.get("catalog_freeze_partition"),
                "family": context.get("family"),
                "workload_id": context.get("workload_id"),
                "case_id": context.get("case_id"),
                "evidence_tier": row.get("evidence_tier") or run.get("evidence_tier") or PROJECTION_SCREENED_TIER,
                "same_candidate_evidence_only": row.get(
                    "same_candidate_evidence_only",
                    run.get("same_candidate_evidence_only"),
                ),
                "blockers": blockers if isinstance(blockers, list) else [],
                "implementation_target_class": "fpga",
                "stage_b0_request": str(request_path) if request_path is not None else run.get("stage_b0_request"),
                "systemc_backend_report": str(systemc_report) if systemc_report is not None else run.get("systemc_backend_report"),
                "systemc_cycle_accounted_evidence": (
                    str(systemc_cycle_report)
                    if systemc_cycle_report is not None
                    else row.get("systemc_cycle_accounted_evidence_ref")
                ),
                "gem5_b4_report": str(b4_report) if b4_report is not None else run.get("gem5_b4_report"),
                "gem5_b4_materialization_manifest": (
                    str(b4_manifest) if b4_manifest is not None else run.get("gem5_b4_materialization_manifest")
                ),
                "stage_c_report": str(stage_c_report) if stage_c_report is not None else row.get("stage_c_report_ref"),
                "stage_d_report": str(stage_d_report) if stage_d_report is not None else row.get("stage_d_report_ref"),
                "artifact_refs": {
                    "catalog_freeze_manifest": _artifact(catalog_freeze_manifest),
                    "stage_b0_request": _artifact(request_path),
                    "systemc_backend_report": _artifact(systemc_report),
                    "systemc_cycle_accounted_evidence": _artifact(systemc_cycle_report),
                    "gem5_b4_report": _artifact(b4_report),
                    "gem5_b4_materialization_manifest": _artifact(b4_manifest),
                    "stage_c_report": _artifact(stage_c_report),
                    "stage_d_report": _artifact(stage_d_report),
                },
                "design_axes": context.get("design_axes", {}),
                "candidate_identity": context.get("candidate_identity", {}),
                "candidate_alignment": row.get("candidate_alignment"),
            }
        )
    top_k_closure = e2e_manifest.get("top_k_closure")
    if not isinstance(top_k_closure, Mapping):
        top_k_closure = {
            "schema_version": "qe_top_k_evidence_closure_status_v0",
            "queue_count": len(candidates),
            "queue": [
                {
                    "queue_rank": index + 1,
                    "candidate_id": candidate["candidate_id"],
                    "evidence_tier": candidate["evidence_tier"],
                    "same_candidate_evidence_only": candidate["same_candidate_evidence_only"],
                    "blockers": candidate["blockers"],
                }
                for index, candidate in enumerate(candidates)
            ],
            "evidence_tier_counts": _tier_counts(candidates),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "source_e2e_manifest": str(e2e_manifest_path),
        "manifest_ref": str(output_ref) if output_ref is not None else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "claim_ceiling_status_matrix": str(claim_matrix_path) if claim_matrix_path is not None else None,
        "catalog_freeze_manifest": str(catalog_freeze_manifest) if catalog_freeze_manifest is not None else None,
        "top_k_closure": dict(top_k_closure),
        "evidence_tier_counts": _tier_counts(candidates),
        "non_claims": [
            "candidate_manifest_is_join_key_only",
            "no_qe_correctness_claim",
            "no_implementation_evidence_claim",
            "no_final_best_architecture_claim",
            "systemc_cycle_accounted_is_not_rtl_cycle_accurate",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build candidate evidence manifest for QE FPGA final-best evidence producers.")
    parser.add_argument("--e2e-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_manifest(args.e2e_manifest, output_ref=args.output)
    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
