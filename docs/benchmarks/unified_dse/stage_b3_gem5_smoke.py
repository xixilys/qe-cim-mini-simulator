from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


GEM5_SYSTEMC_SMOKE_REPORT_SCHEMA_VERSION = "qe_dse_gem5_systemc_smoke_report_v0"
_EQUIVALENCE_CLAIM_KEYS = {
    "qe_equivalence_status",
    "qe_equivalent_scf_claim",
    "qe_equivalence_claim",
    "workload_equivalent_claim",
    "workload_equivalence_claim",
    "domain_equivalence_claim",
}
_FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS = (
    "qe_equivalence",
    "qe-equivalence",
    "qe equivalence",
    "qe_equivalent",
    "qe-equivalent",
    "qe equivalent",
    "workload_equivalence",
    "workload-equivalence",
    "workload equivalence",
    "workload_equivalent",
    "workload-equivalent",
    "workload equivalent",
    "domain_equivalence",
    "domain-equivalence",
    "domain equivalence",
    "domain_equivalent",
    "domain-equivalent",
    "domain equivalent",
)


def load_and_validate_gem5_smoke_report(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_gem5_smoke_report(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"gem5 smoke report requires mapping field: {key}")
    return value


def _iter_json_items(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    items = [(path, value)]
    if isinstance(value, Mapping):
        for key, child in value.items():
            items.extend(_iter_json_items(child, path + (str(key),)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            items.extend(_iter_json_items(child, path + (str(index),)))
    return items


def _is_non_claim_text(text: str) -> bool:
    normalized = text.strip().lower().replace("-", "_")
    if normalized.startswith("no_") or normalized.startswith("not_"):
        return True
    return any(
        marker in text
        for marker in (
            "not ",
            "no ",
            "without ",
            "unclaimed",
            "not_claimed",
            "non-claim",
            "non_claim",
        )
    )


def _reject_hidden_equivalence_claims(payload: Mapping[str, Any]) -> None:
    for path, value in _iter_json_items(payload):
        if not path:
            continue
        key = path[-1].lower()
        if key in _EQUIVALENCE_CLAIM_KEYS and value not in (False, "not_claimed"):
            if isinstance(value, str) and _is_non_claim_text(value.lower()):
                continue
            raise ValueError(f"{'.'.join(path)} must not claim QE-equivalent SCF")
        if isinstance(value, str):
            lowered = value.lower()
            if any(token in lowered for token in _FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS):
                if not _is_non_claim_text(lowered):
                    raise ValueError(f"{'.'.join(path)} must not claim QE-equivalent SCF")


def validate_gem5_smoke_report(payload: Mapping[str, Any]) -> None:
    required = (
        "schema_version",
        "execution_status",
        "claim_ceiling",
        "run_id",
        "candidate_id",
        "environment",
        "scf_control_loop_status",
        "systemc_bridge_status",
        "qe_equivalence_status",
        "metrics",
        "correctness_gate",
    )
    for key in required:
        if key not in payload:
            raise ValueError(f"gem5 smoke report missing field: {key}")
    if payload["schema_version"] != GEM5_SYSTEMC_SMOKE_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported gem5 smoke report schema_version")
    if payload["execution_status"] != "executed":
        raise ValueError("gem5 smoke report must represent an executed external smoke run")
    if payload["claim_ceiling"] != "gem5_systemc_smoke_only":
        raise ValueError("gem5 smoke report claim_ceiling must be gem5_systemc_smoke_only")
    if payload["scf_control_loop_status"] not in {"smoke_passed", "smoke_failed"}:
        raise ValueError("invalid gem5 smoke scf_control_loop_status")
    if payload["systemc_bridge_status"] not in {"smoke_passed", "smoke_failed"}:
        raise ValueError("invalid gem5 smoke systemc_bridge_status")
    if payload["qe_equivalence_status"] != "not_claimed":
        raise ValueError("Stage B3 smoke report must not claim QE-equivalent SCF")
    correctness_gate = _require_mapping(payload, "correctness_gate")
    if correctness_gate.get("qe_equivalent_scf_claim") is not False:
        raise ValueError("Stage B3 smoke report must keep QE-equivalent SCF claim false")
    _require_mapping(payload, "environment")
    _require_mapping(payload, "metrics")
    _reject_hidden_equivalence_claims(payload)
