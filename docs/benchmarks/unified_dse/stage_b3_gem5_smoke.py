from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


GEM5_SYSTEMC_SMOKE_REPORT_SCHEMA_VERSION = "qe_dse_gem5_systemc_smoke_report_v0"


def load_and_validate_gem5_smoke_report(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_gem5_smoke_report(payload)
    return payload


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"gem5 smoke report requires mapping field: {key}")
    return value


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
