#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_qe_microarchitecture_catalog_freeze_manifest_v0 as freeze_builder


class CatalogFreezeCheckError(RuntimeError):
    pass


def _load_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogFreezeCheckError(f"expected JSON object: {path}")
    return payload


def _require(condition: bool, message: str, issues: list[str]) -> None:
    if not condition:
        issues.append(message)


def validate_freeze_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
    allow_blocked: bool = False,
) -> list[str]:
    issues: list[str] = []
    _require(
        manifest.get("schema_version") == freeze_builder.SCHEMA_VERSION,
        f"schema_version must be {freeze_builder.SCHEMA_VERSION}",
        issues,
    )
    if not allow_blocked:
        _require(manifest.get("freeze_status") == "passed", "freeze_status must be passed", issues)
    partitions = manifest.get("partitions")
    _require(isinstance(partitions, Mapping), "partitions must be an object", issues)
    if isinstance(partitions, Mapping):
        for partition in freeze_builder.PARTITIONS:
            _require(isinstance(partitions.get(partition), list), f"partitions.{partition} must be a list", issues)
        competitive = partitions.get(freeze_builder.PARTITION_COMPETITIVE)
        _require(bool(competitive), "at least one competitive_evaluable candidate is required", issues)

    entries = manifest.get("entries")
    _require(isinstance(entries, list) and bool(entries), "entries must be a non-empty list", issues)
    entry_ids: set[str] = set()
    if isinstance(entries, list):
        for index, raw_entry in enumerate(entries):
            if not isinstance(raw_entry, Mapping):
                issues.append(f"entries[{index}] must be an object")
                continue
            entry_id = raw_entry.get("microarchitecture_id")
            _require(isinstance(entry_id, str) and bool(entry_id), f"entries[{index}].microarchitecture_id missing", issues)
            if isinstance(entry_id, str):
                _require(entry_id not in entry_ids, f"duplicate entry id: {entry_id}", issues)
                entry_ids.add(entry_id)
            partition = raw_entry.get("freeze_partition")
            _require(partition in freeze_builder.PARTITIONS, f"{entry_id}: invalid freeze_partition {partition!r}", issues)
            _require(bool(raw_entry.get("parameter_space_hash")), f"{entry_id}: missing parameter_space_hash", issues)
            if partition != freeze_builder.PARTITION_COMPETITIVE:
                _require(bool(raw_entry.get("partition_reason")), f"{entry_id}: missing exclusion/coverage rationale", issues)

    gates = manifest.get("freeze_gates")
    _require(isinstance(gates, list), "freeze_gates must be a list", issues)
    if isinstance(gates, list):
        gates_by_id = {}
        for index, raw_gate in enumerate(gates):
            if not isinstance(raw_gate, Mapping):
                issues.append(f"freeze_gates[{index}] must be an object")
                continue
            gate_id = raw_gate.get("gate_id")
            gates_by_id[gate_id] = raw_gate
            _require(gate_id in freeze_builder.FREEZE_GATE_IDS, f"unknown freeze gate {gate_id!r}", issues)
            if not allow_blocked:
                _require(raw_gate.get("status") == "passed", f"freeze gate {gate_id!r} is not passed", issues)
        for gate_id in freeze_builder.FREEZE_GATE_IDS:
            _require(gate_id in gates_by_id, f"missing freeze gate {gate_id!r}", issues)

    coverage = manifest.get("coverage_summary")
    _require(isinstance(coverage, Mapping), "coverage_summary must be an object", issues)
    if isinstance(coverage, Mapping) and not allow_blocked:
        missing = coverage.get("missing_coverage_tags")
        _require(missing == [], f"coverage_summary has missing coverage tags: {missing!r}", issues)

    topk = manifest.get("topk_closure_contract")
    _require(isinstance(topk, Mapping), "topk_closure_contract must be an object", issues)
    if isinstance(topk, Mapping):
        for key in (
            "requires_reproducible_topk_hash",
            "requires_dominance_closure_hash",
            "requires_no_unresolved_higher_ranked_competitive_candidate",
        ):
            _require(topk.get(key) is True, f"topk_closure_contract.{key} must be true", issues)

    catalog_ref = manifest.get("catalog_ref")
    declared_sha = manifest.get("catalog_sha256")
    if isinstance(catalog_ref, str) and declared_sha and manifest_path is not None:
        path = Path(catalog_ref)
        if not path.is_absolute():
            candidates = [manifest_path.parent / path, SCRIPT_DIR.parents[1] / path, path]
        else:
            candidates = [path]
        existing = next((candidate for candidate in candidates if candidate.exists()), None)
        if existing is not None:
            actual_sha = freeze_builder._sha256_file(existing)
            _require(actual_sha == declared_sha, f"catalog_sha256 mismatch for {existing}", issues)

    return issues


def validate_manifest_path(path: Path, *, allow_blocked: bool = False) -> None:
    payload = _load_json(path)
    issues = validate_freeze_manifest(payload, manifest_path=path, allow_blocked=allow_blocked)
    if issues:
        raise CatalogFreezeCheckError("\n".join(issues))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate QE microarchitecture catalog freeze manifest v0.")
    parser.add_argument("--manifest", type=Path, default=freeze_builder.DEFAULT_MANIFEST_PATH)
    parser.add_argument("--allow-blocked", action="store_true", help="Validate structure without requiring passed gates.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_manifest_path(args.manifest, allow_blocked=args.allow_blocked)
    except CatalogFreezeCheckError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] catalog freeze manifest is valid: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
