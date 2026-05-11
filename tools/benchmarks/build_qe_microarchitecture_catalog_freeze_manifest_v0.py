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
ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import microarchitecture_catalog_loader_v0 as catalog_loader


SCHEMA_VERSION = "qe_microarchitecture_catalog_freeze_manifest_v0"
DEFAULT_MANIFEST_PATH = ROOT / "docs/benchmarks/qe_microarchitecture_catalog_freeze_manifest_v0.json"
DEFAULT_POLICY_ID = "qe_fpga_final_best_policy_systemc_b4_minimum_v0"

PARTITION_COMPETITIVE = "competitive_evaluable"
PARTITION_COVERAGE_ONLY = "coverage_only"
PARTITION_EXCLUDED = "excluded_from_best_universe"
PARTITIONS = (PARTITION_COMPETITIVE, PARTITION_COVERAGE_ONLY, PARTITION_EXCLUDED)

FREEZE_GATE_IDS = (
    "research_coverage_proof",
    "ppt_family_coverage",
    "auditable_parameter_space",
    "exclusion_rationale",
    "evidence_path_per_competitive_candidate",
    "reproducible_topk_closure_refs",
)

REQUIRED_COVERAGE_TAGS = (
    "host_fpga_chip",
    "operator_sweep",
    "reduced_build",
    "diagonalization",
    "refresh_residual",
    "memory_residency",
    "interconnect",
    "cim_or_hybrid",
    "data_movement",
)


class CatalogFreezeError(ValueError):
    pass


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _parameter_space_hash(entry: catalog_loader.MicroarchitectureCatalogEntry) -> str:
    return _sha256_payload(entry.parameter_ranges)


def _ref_exists_or_external(ref: str, *, repo_root: Path) -> bool:
    if not ref:
        return False
    if "://" in ref or ref.startswith("architecture literature pattern:"):
        return True
    path = Path(ref)
    if path.is_absolute():
        return path.exists()
    return (repo_root / path).exists()


def _entry_ref_list(entry: catalog_loader.MicroarchitectureCatalogEntry) -> list[str]:
    refs: list[str] = []
    for source in entry.provenance:
        ref = source.get("ref")
        if isinstance(ref, str) and ref:
            refs.append(ref)
    return refs


def _coverage_tags_for_entry(entry: catalog_loader.MicroarchitectureCatalogEntry) -> list[str]:
    text = " ".join(
        [
            entry.microarchitecture_id,
            entry.name,
            entry.target_stage,
            entry.architecture_family,
            entry.summary,
            " ".join(_entry_ref_list(entry)),
        ]
    ).lower()
    tags: set[str] = set()
    if entry.target_stage in {
        "operator_sweep",
        "reduced_build",
        "diagonalization",
        "refresh_residual",
        "memory_residency",
        "interconnect",
        "multi_stage",
    }:
        tags.add(entry.target_stage)
    if entry.target_stage == "multi_stage":
        tags.add("host_fpga_chip")
    keyword_tags = {
        "host_fpga_chip": ("host", "fpga", "chip", "full-system", "full_system", "4-cluster", "four-cluster"),
        "operator_sweep": ("operator", "h_psi", "s_psi", "sweep"),
        "reduced_build": ("reduced", "build", "cluster_ab"),
        "diagonalization": ("diag", "diagonalization", "cdiaghg"),
        "refresh_residual": ("refresh", "residual", "cluster_d"),
        "memory_residency": ("resident", "residency", "memory", "pim", "sram"),
        "interconnect": ("interconnect", "noc", "chiplet", "hbm"),
        "cim_or_hybrid": ("cim", "hybrid", "dsp"),
        "data_movement": ("dma", "stream", "streaming", "movement", "hbm", "resident"),
    }
    for tag, needles in keyword_tags.items():
        if any(needle in text for needle in needles):
            tags.add(tag)
    if entry.support_status in {"systemc_configurable", "current_executor_supported"}:
        tags.add("systemc_configurable_candidate")
    return sorted(tags)


def _partition_entry(entry: catalog_loader.MicroarchitectureCatalogEntry) -> tuple[str, str]:
    tiers = set(entry.supported_evidence_tiers)
    if (
        entry.support_status in {"systemc_configurable", "current_executor_supported"}
        and "systemc-cycle-accounted" in tiers
    ):
        return (
            PARTITION_COMPETITIVE,
            "current backend can carry this entry to same-candidate SystemC cycle evidence; Stage C and strict B4 remain required before any final-best claim",
        )
    if entry.support_status == "unsupported":
        return (
            PARTITION_EXCLUDED,
            "not executable in the current SystemC/B4 evidence loop; retained for search coverage only and excluded before final-best ranking",
        )
    return (
        PARTITION_COVERAGE_ONLY,
        "projection/catalog coverage entry without same-candidate SystemC+B4 executable path; cannot block or win the closed-catalog-best decision",
    )


def _competitive_evidence_requirements(entry: catalog_loader.MicroarchitectureCatalogEntry) -> dict[str, Any]:
    return {
        "candidate_id": entry.microarchitecture_id,
        "required_policy_id": DEFAULT_POLICY_ID,
        "required_refs": {
            "stage_c_qe_correctness_report": "required_same_candidate_artifact",
            "strict_b4_gem5_systemc_event_tick_report": "required_same_candidate_artifact",
            "systemc_cycle_accounted_evidence": "required_same_candidate_artifact",
            "claim_ceiling_status_matrix_row": "required_same_candidate_join",
            "topk_closure_row": "required_same_candidate_join",
            "final_best_decision_row": "required_same_candidate_join",
        },
        "optional_precision_upgrades": [
            "stage_d_hls_or_stronger_implementation_evidence",
            "fpga_board_measurement",
            "asic_or_physical_timing_evidence",
        ],
    }


def _gate(gate_id: str, passed: bool, details: Mapping[str, Any]) -> dict[str, Any]:
    if gate_id not in FREEZE_GATE_IDS:
        raise CatalogFreezeError(f"unknown freeze gate: {gate_id}")
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "blocked",
        "details": dict(details),
    }


def build_freeze_manifest(
    *,
    catalog_path: Path = catalog_loader.DEFAULT_CATALOG_PATH,
    schema_path: Path = catalog_loader.DEFAULT_SCHEMA_PATH,
    output_ref: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo = repo_root or SCRIPT_DIR.parents[1]
    catalog = catalog_loader.load_catalog(catalog_path, schema_path)

    entries: list[dict[str, Any]] = []
    partitions = {partition: [] for partition in PARTITIONS}
    source_types: set[str] = set()
    missing_refs: list[str] = []
    missing_parameter_hashes: list[str] = []
    missing_exclusion_rationale: list[str] = []
    coverage_tags: set[str] = set()
    competitive_requirements: dict[str, Any] = {}

    for entry in catalog.entries:
        partition, reason = _partition_entry(entry)
        tags = _coverage_tags_for_entry(entry)
        coverage_tags.update(tags)
        refs = _entry_ref_list(entry)
        for source in entry.provenance:
            source_type = source.get("source_type")
            if isinstance(source_type, str) and source_type:
                source_types.add(source_type)
        for ref in refs:
            if not _ref_exists_or_external(ref, repo_root=repo):
                missing_refs.append(f"{entry.microarchitecture_id}:{ref}")
        parameter_hash = _parameter_space_hash(entry)
        if not parameter_hash:
            missing_parameter_hashes.append(entry.microarchitecture_id)
        if partition != PARTITION_COMPETITIVE and not reason:
            missing_exclusion_rationale.append(entry.microarchitecture_id)
        partitions[partition].append(entry.microarchitecture_id)
        if partition == PARTITION_COMPETITIVE:
            competitive_requirements[entry.microarchitecture_id] = _competitive_evidence_requirements(entry)
        entries.append(
            {
                "microarchitecture_id": entry.microarchitecture_id,
                "name": entry.name,
                "target_stage": entry.target_stage,
                "architecture_family": entry.architecture_family,
                "support_status": entry.support_status,
                "model_support_status": dict(entry.model_support_status),
                "supported_evidence_tiers": list(entry.supported_evidence_tiers),
                "freeze_partition": partition,
                "partition_reason": reason,
                "coverage_tags": tags,
                "provenance_refs": refs,
                "parameter_space_hash": parameter_hash,
                "non_claims": list(entry.non_claims),
            }
        )

    missing_coverage = [tag for tag in REQUIRED_COVERAGE_TAGS if tag not in coverage_tags]
    gates = [
        _gate(
            "research_coverage_proof",
            not missing_refs and {"local_design_template", "local_contract", "workload_analysis", "literature_pattern"}.issubset(source_types),
            {
                "source_types_present": sorted(source_types),
                "missing_or_unresolved_refs": missing_refs,
                "entry_count": len(entries),
            },
        ),
        _gate(
            "ppt_family_coverage",
            not missing_coverage,
            {
                "required_coverage_tags": list(REQUIRED_COVERAGE_TAGS),
                "covered_tags": sorted(coverage_tags),
                "missing_coverage_tags": missing_coverage,
            },
        ),
        _gate(
            "auditable_parameter_space",
            not missing_parameter_hashes,
            {
                "parameter_space_hashes_present_for": [entry["microarchitecture_id"] for entry in entries if entry["parameter_space_hash"]],
                "missing_parameter_space_hashes": missing_parameter_hashes,
            },
        ),
        _gate(
            "exclusion_rationale",
            not missing_exclusion_rationale and bool(partitions[PARTITION_COVERAGE_ONLY] or partitions[PARTITION_EXCLUDED]),
            {
                "coverage_only_ids": partitions[PARTITION_COVERAGE_ONLY],
                "excluded_from_best_universe_ids": partitions[PARTITION_EXCLUDED],
                "missing_exclusion_rationale": missing_exclusion_rationale,
            },
        ),
        _gate(
            "evidence_path_per_competitive_candidate",
            bool(partitions[PARTITION_COMPETITIVE])
            and set(partitions[PARTITION_COMPETITIVE]) == set(competitive_requirements),
            {
                "competitive_candidate_ids": partitions[PARTITION_COMPETITIVE],
                "evidence_path_requirements": competitive_requirements,
            },
        ),
        _gate(
            "reproducible_topk_closure_refs",
            bool(partitions[PARTITION_COMPETITIVE]),
            {
                "topk_closure_required_fields": [
                    "catalog_hash",
                    "policy_id",
                    "screening_rank",
                    "ranking_metric_inputs",
                    "tie_break_inputs",
                    "dominance_status",
                    "evidence_refs",
                    "evidence_hashes",
                ],
                "dominance_rule": "a lower-ranked competitive candidate cannot win until every higher-ranked competitive candidate is resolved worse or excluded by this freeze manifest",
            },
        ),
    ]
    freeze_status = "passed" if all(gate["status"] == "passed" for gate in gates) else "blocked"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": "qe_microarchitecture_catalog_freeze_manifest_v0",
        "generated_at_utc": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "freeze_status": freeze_status,
        "policy_id": DEFAULT_POLICY_ID,
        "catalog_ref": str(catalog_path),
        "catalog_id": catalog.catalog_id,
        "catalog_sha256": _sha256_file(catalog_path),
        "catalog_schema_ref": str(schema_path),
        "catalog_schema_sha256": _sha256_file(schema_path),
        "partitions": partitions,
        "entries": entries,
        "freeze_gates": gates,
        "coverage_summary": {
            "required_coverage_tags": list(REQUIRED_COVERAGE_TAGS),
            "covered_tags": sorted(coverage_tags),
            "missing_coverage_tags": missing_coverage,
        },
        "topk_closure_contract": {
            "ranking_universe": PARTITION_COMPETITIVE,
            "policy_id": DEFAULT_POLICY_ID,
            "requires_reproducible_topk_hash": True,
            "requires_dominance_closure_hash": True,
            "requires_no_unresolved_higher_ranked_competitive_candidate": True,
        },
        "non_claims": [
            "catalog_freeze_is_not_a_final_best_claim",
            "closed_catalog_best_is_not_global_best",
            "coverage_only_and_excluded_entries_cannot_win_or_block_final_best",
            "systemc_b4_minimum_does_not_claim_rtl_or_physical_timing_accuracy",
            "missing_hls_fpga_asic_or_board_measurement_remains_residual_risk_not_a_first_pass_blocker",
        ],
    }
    payload["manifest_sha256"] = _sha256_payload(payload)
    if output_ref is not None:
        payload["manifest_ref"] = str(output_ref)
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the QE microarchitecture catalog freeze manifest v0.")
    parser.add_argument("--catalog", type=Path, default=catalog_loader.DEFAULT_CATALOG_PATH)
    parser.add_argument("--schema", type=Path, default=catalog_loader.DEFAULT_SCHEMA_PATH)
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parents[1])
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_freeze_manifest(
        catalog_path=args.catalog,
        schema_path=args.schema,
        output_ref=args.output,
        repo_root=args.repo_root,
    )
    write_json(args.output, payload)
    print(f"[{payload['freeze_status'].upper()}] wrote catalog freeze manifest to {args.output}")
    return 0 if payload["freeze_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
