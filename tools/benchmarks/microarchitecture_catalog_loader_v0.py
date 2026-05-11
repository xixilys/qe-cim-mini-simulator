#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]

CATALOG_SCHEMA_VERSION = "qe_microarchitecture_catalog_v0"
CATALOG_SCHEMA_ID = "qe_microarchitecture_catalog_schema_v0"
DEFAULT_CATALOG_PATH = ROOT / "docs/benchmarks/qe_microarchitecture_catalog_v0.json"
DEFAULT_SCHEMA_PATH = ROOT / "docs/benchmarks/qe_microarchitecture_catalog_schema_v0.json"

EXACT_EVIDENCE_TIERS = (
    "survey-catalog",
    "projection-screened",
    "systemc-cycle-accounted",
    "final-best-eligible",
)
CATALOG_ENTRY_EVIDENCE_TIERS = {
    "survey-catalog",
    "projection-screened",
    "systemc-cycle-accounted",
}
CATALOG_ONLY_EVIDENCE_TIERS = {"survey-catalog", "projection-screened"}
SUPPORT_STATUSES = {
    "unsupported",
    "projection_only",
    "systemc_configurable",
    "current_executor_supported",
}
MODEL_SUPPORT_STATUSES = {
    "not_supported",
    "projection_only",
    "configurable_systemc_model",
    "existing_executor_path",
}
TARGET_STAGES = {
    "operator_sweep",
    "reduced_build",
    "diagonalization",
    "refresh_residual",
    "memory_residency",
    "interconnect",
    "multi_stage",
}
PROVENANCE_SOURCE_TYPES = {
    "local_design_template",
    "local_contract",
    "literature_pattern",
    "workload_analysis",
}
PARAMETER_KINDS = {"range", "enum", "unknown"}
EFFECT_DIRECTIONS = {"increase", "decrease", "mixed", "unknown"}
INITIAL_TIER_BY_SUPPORT_STATUS = {
    "unsupported": "survey-catalog",
    "projection_only": "projection-screened",
    "systemc_configurable": "projection-screened",
    "current_executor_supported": "projection-screened",
}


class CatalogValidationError(ValueError):
    """Raised when the microarchitecture catalog violates the v0 contract."""


@dataclass(frozen=True)
class MicroarchitectureCatalogEntry:
    microarchitecture_id: str
    name: str
    target_stage: str
    architecture_family: str
    summary: str
    support_status: str
    model_support_status: Mapping[str, Any]
    supported_evidence_tiers: tuple[str, ...]
    provenance: tuple[Mapping[str, Any], ...]
    assumptions: tuple[str, ...]
    parameter_ranges: Mapping[str, Mapping[str, Any]]
    expected_effects: tuple[Mapping[str, str], ...]
    non_claims: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MicroarchitectureCatalogEntry":
        return cls(
            microarchitecture_id=str(payload["microarchitecture_id"]),
            name=str(payload["name"]),
            target_stage=str(payload["target_stage"]),
            architecture_family=str(payload["architecture_family"]),
            summary=str(payload["summary"]),
            support_status=str(payload["support_status"]),
            model_support_status=dict(payload["model_support_status"]),
            supported_evidence_tiers=tuple(str(item) for item in payload["supported_evidence_tiers"]),
            provenance=tuple(dict(item) for item in payload["provenance"]),
            assumptions=tuple(str(item) for item in payload["assumptions"]),
            parameter_ranges=dict(payload["parameter_ranges"]),
            expected_effects=tuple(dict(item) for item in payload["expected_effects"]),
            non_claims=tuple(str(item) for item in payload["non_claims"]),
        )

    @property
    def initial_evidence_tier(self) -> str:
        """Claim-safe Level-1 row tier derived from catalog support status."""
        return INITIAL_TIER_BY_SUPPORT_STATUS[self.support_status]

    def as_search_row(self) -> dict[str, Any]:
        """Expose support/evidence metadata for broad search without overclaiming."""
        return {
            "microarchitecture_id": self.microarchitecture_id,
            "name": self.name,
            "target_stage": self.target_stage,
            "architecture_family": self.architecture_family,
            "support_status": self.support_status,
            "model_support_status": dict(self.model_support_status),
            "dse_evidence_tier": self.initial_evidence_tier,
            "supported_evidence_tiers": list(self.supported_evidence_tiers),
            "final_best_eligible": False,
            "claim_boundary": "catalog_search_space_only",
            "non_claims": list(self.non_claims),
        }


@dataclass(frozen=True)
class MicroarchitectureCatalog:
    schema_version: str
    catalog_id: str
    entries: tuple[MicroarchitectureCatalogEntry, ...]
    evidence_tier_labels: tuple[str, ...]
    support_status_values: tuple[str, ...]
    non_claims: tuple[str, ...]
    description: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MicroarchitectureCatalog":
        return cls(
            schema_version=str(payload["schema_version"]),
            catalog_id=str(payload["catalog_id"]),
            description=str(payload.get("description", "")),
            evidence_tier_labels=tuple(str(item) for item in payload["evidence_tier_labels"]),
            support_status_values=tuple(str(item) for item in payload["support_status_values"]),
            non_claims=tuple(str(item) for item in payload["non_claims"]),
            entries=tuple(MicroarchitectureCatalogEntry.from_mapping(item) for item in payload["entries"]),
        )

    def as_search_rows(self) -> list[dict[str, Any]]:
        return [entry.as_search_row() for entry in self.entries]

    def support_summary(self) -> dict[str, int]:
        summary = {status: 0 for status in sorted(SUPPORT_STATUSES)}
        for entry in self.entries:
            summary[entry.support_status] += 1
        return summary


@dataclass
class _Validator:
    errors: list[str]

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(f"{path}: invalid JSON: {exc}") from exc


def _as_mapping(value: Any, path: str, validator: _Validator) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    validator.require(False, f"{path} must be an object")
    return {}


def _as_list(value: Any, path: str, validator: _Validator) -> list[Any]:
    if isinstance(value, list):
        return value
    validator.require(False, f"{path} must be a list")
    return []


def _require_non_empty_string(value: Any, path: str, validator: _Validator) -> str:
    if isinstance(value, str) and value.strip():
        return value
    validator.require(False, f"{path} must be a non-empty string")
    return ""


def _require_non_empty_string_list(value: Any, path: str, validator: _Validator) -> list[str]:
    raw_items = _as_list(value, path, validator)
    validator.require(bool(raw_items), f"{path} must not be empty")
    items: list[str] = []
    for idx, item in enumerate(raw_items):
        items.append(_require_non_empty_string(item, f"{path}[{idx}]", validator))
    return items


def _validate_schema(schema: Any, validator: _Validator) -> None:
    schema_map = _as_mapping(schema, "schema", validator)
    validator.require(schema_map.get("$id") == CATALOG_SCHEMA_ID, f"schema $id must be {CATALOG_SCHEMA_ID}")
    validator.require("entries" in str(schema_map), "schema must describe entries")


def _validate_provenance(value: Any, path: str, validator: _Validator) -> None:
    rows = _as_list(value, path, validator)
    validator.require(bool(rows), f"{path} must contain at least one source")
    for idx, row in enumerate(rows):
        row_path = f"{path}[{idx}]"
        row_map = _as_mapping(row, row_path, validator)
        for key in ("source_id", "source_type", "title", "ref"):
            _require_non_empty_string(row_map.get(key), f"{row_path}.{key}", validator)
        source_type = row_map.get("source_type")
        validator.require(source_type in PROVENANCE_SOURCE_TYPES, f"{row_path}.source_type is not supported: {source_type!r}")


def _validate_parameter_ranges(value: Any, path: str, validator: _Validator) -> None:
    ranges = _as_mapping(value, path, validator)
    validator.require(bool(ranges), f"{path} must contain at least one parameter")
    for key, raw_spec in ranges.items():
        param_path = f"{path}.{key}"
        spec = _as_mapping(raw_spec, param_path, validator)
        kind = spec.get("kind")
        validator.require(kind in PARAMETER_KINDS, f"{param_path}.kind is not supported: {kind!r}")
        _require_non_empty_string(spec.get("description"), f"{param_path}.description", validator)
        if kind == "range":
            validator.require(isinstance(spec.get("min"), (int, float)), f"{param_path}.min must be numeric")
            validator.require(isinstance(spec.get("max"), (int, float)), f"{param_path}.max must be numeric")
            if isinstance(spec.get("min"), (int, float)) and isinstance(spec.get("max"), (int, float)):
                validator.require(float(spec["max"]) >= float(spec["min"]), f"{param_path}.max must be >= min")
            _require_non_empty_string(spec.get("unit"), f"{param_path}.unit", validator)
        elif kind == "enum":
            values = _as_list(spec.get("values"), f"{param_path}.values", validator)
            validator.require(bool(values), f"{param_path}.values must not be empty")
        elif kind == "unknown":
            _require_non_empty_string(spec.get("unknown_reason"), f"{param_path}.unknown_reason", validator)


def _validate_expected_effects(value: Any, path: str, validator: _Validator) -> None:
    effects = _as_list(value, path, validator)
    validator.require(bool(effects), f"{path} must contain at least one expected effect")
    for idx, raw_effect in enumerate(effects):
        effect_path = f"{path}[{idx}]"
        effect = _as_mapping(raw_effect, effect_path, validator)
        _require_non_empty_string(effect.get("metric"), f"{effect_path}.metric", validator)
        direction = effect.get("direction")
        validator.require(direction in EFFECT_DIRECTIONS, f"{effect_path}.direction is not supported: {direction!r}")
        _require_non_empty_string(effect.get("rationale"), f"{effect_path}.rationale", validator)


def _validate_model_support(value: Any, support_status: str, path: str, validator: _Validator) -> None:
    model_support = _as_mapping(value, path, validator)
    status = model_support.get("status")
    validator.require(status in MODEL_SUPPORT_STATUSES, f"{path}.status is not supported: {status!r}")
    _require_non_empty_string(model_support.get("notes"), f"{path}.notes", validator)
    allowed_by_support = {
        "unsupported": {"not_supported"},
        "projection_only": {"projection_only"},
        "systemc_configurable": {"configurable_systemc_model", "existing_executor_path"},
        "current_executor_supported": {"existing_executor_path"},
    }
    if support_status in allowed_by_support:
        validator.require(
            status in allowed_by_support[support_status],
            f"{path}.status={status!r} is inconsistent with support_status={support_status!r}",
        )
    refs = model_support.get("supporting_artifact_refs", [])
    if refs is not None:
        _require_non_empty_string_list(refs, f"{path}.supporting_artifact_refs", validator)


def _validate_entry(raw_entry: Any, path: str, validator: _Validator) -> str:
    entry = _as_mapping(raw_entry, path, validator)
    entry_id = _require_non_empty_string(entry.get("microarchitecture_id"), f"{path}.microarchitecture_id", validator)
    _require_non_empty_string(entry.get("name"), f"{path}.name", validator)
    target_stage = entry.get("target_stage")
    validator.require(target_stage in TARGET_STAGES, f"{path}.target_stage is not supported: {target_stage!r}")
    _require_non_empty_string(entry.get("architecture_family"), f"{path}.architecture_family", validator)
    _require_non_empty_string(entry.get("summary"), f"{path}.summary", validator)
    _validate_provenance(entry.get("provenance"), f"{path}.provenance", validator)
    _require_non_empty_string_list(entry.get("assumptions"), f"{path}.assumptions", validator)
    _validate_parameter_ranges(entry.get("parameter_ranges"), f"{path}.parameter_ranges", validator)
    _validate_expected_effects(entry.get("expected_effects"), f"{path}.expected_effects", validator)

    support_status = entry.get("support_status")
    validator.require(support_status in SUPPORT_STATUSES, f"{path}.support_status is not supported: {support_status!r}")
    _validate_model_support(entry.get("model_support_status"), str(support_status), f"{path}.model_support_status", validator)

    evidence_tiers = _require_non_empty_string_list(
        entry.get("supported_evidence_tiers"),
        f"{path}.supported_evidence_tiers",
        validator,
    )
    evidence_tier_set = set(evidence_tiers)
    unsupported_tiers = sorted(evidence_tier_set - CATALOG_ENTRY_EVIDENCE_TIERS)
    validator.require(not unsupported_tiers, f"{path}.supported_evidence_tiers contains forbidden tiers: {unsupported_tiers}")
    validator.require("survey-catalog" in evidence_tier_set, f"{path}.supported_evidence_tiers must include survey-catalog")
    if support_status == "unsupported":
        forbidden = sorted(evidence_tier_set - CATALOG_ONLY_EVIDENCE_TIERS)
        validator.require(
            not forbidden,
            f"{path}: unsupported entries may only use survey-catalog/projection-screened tiers; got {forbidden}",
        )
    if support_status in {"projection_only", "unsupported"}:
        validator.require(
            "systemc-cycle-accounted" not in evidence_tier_set,
            f"{path}: {support_status} entries cannot advertise systemc-cycle-accounted support",
        )
    _require_non_empty_string_list(entry.get("non_claims"), f"{path}.non_claims", validator)
    return entry_id


def validate_catalog_payload(payload: Any, schema: Any | None = None) -> None:
    validator = _Validator(errors=[])
    if schema is not None:
        _validate_schema(schema, validator)
    catalog = _as_mapping(payload, "catalog", validator)
    validator.require(catalog.get("schema_version") == CATALOG_SCHEMA_VERSION, f"schema_version must be {CATALOG_SCHEMA_VERSION}")
    _require_non_empty_string(catalog.get("catalog_id"), "catalog.catalog_id", validator)
    tiers = _require_non_empty_string_list(catalog.get("evidence_tier_labels"), "catalog.evidence_tier_labels", validator)
    validator.require(tuple(tiers) == EXACT_EVIDENCE_TIERS, "catalog.evidence_tier_labels must match the exact four-tier contract")
    support_values = set(_require_non_empty_string_list(catalog.get("support_status_values"), "catalog.support_status_values", validator))
    validator.require(support_values == SUPPORT_STATUSES, "catalog.support_status_values must match the support status contract")
    _require_non_empty_string_list(catalog.get("non_claims"), "catalog.non_claims", validator)

    entries = _as_list(catalog.get("entries"), "catalog.entries", validator)
    validator.require(bool(entries), "catalog.entries must not be empty")
    seen_ids: set[str] = set()
    for idx, raw_entry in enumerate(entries):
        entry_id = _validate_entry(raw_entry, f"catalog.entries[{idx}]", validator)
        if entry_id:
            validator.require(entry_id not in seen_ids, f"duplicate microarchitecture_id: {entry_id}")
            seen_ids.add(entry_id)

    if validator.errors:
        raise CatalogValidationError("\n".join(validator.errors))


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> Mapping[str, Any]:
    schema = _load_json(path)
    validator = _Validator(errors=[])
    _validate_schema(schema, validator)
    if validator.errors:
        raise CatalogValidationError("\n".join(validator.errors))
    return _as_mapping(schema, "schema", validator)


def load_catalog(path: Path = DEFAULT_CATALOG_PATH, schema_path: Path = DEFAULT_SCHEMA_PATH) -> MicroarchitectureCatalog:
    payload = _load_json(path)
    schema = load_schema(schema_path)
    validate_catalog_payload(payload, schema)
    return MicroarchitectureCatalog.from_mapping(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and inspect the QE microarchitecture catalog v0.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--emit-search-rows", type=Path, help="Optional JSON output path for claim-safe Level-1 search rows.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog(args.catalog, args.schema)
    print(f"[PASS] loaded {len(catalog.entries)} microarchitecture catalog entries from {args.catalog}")
    print(json.dumps({"support_summary": catalog.support_summary()}, indent=2, sort_keys=True))
    if args.emit_search_rows is not None:
        args.emit_search_rows.parent.mkdir(parents=True, exist_ok=True)
        args.emit_search_rows.write_text(json.dumps(catalog.as_search_rows(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[PASS] wrote search rows to {args.emit_search_rows}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CatalogValidationError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
