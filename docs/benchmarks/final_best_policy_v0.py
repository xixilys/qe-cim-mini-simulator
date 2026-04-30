from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = "qe_fpga_final_best_policy_v0"
DEFAULT_POLICY_ID = "qe_fpga_final_best_policy_hls_v0"

STAGE_D_TIER_ORDER = {
    "implementation_projection": 0,
    "hls_synthesis": 10,
    "rtl_simulation": 20,
    "openroad_physical": 30,
    "asic_ppa": 40,
    "fpga_board": 50,
}

CLAIM_CEILING_TO_STAGE_D_TIER = {
    "implementation_evidence_only": "implementation_projection",
    "hls_synthesis_only": "hls_synthesis",
    "rtl_simulation_only": "rtl_simulation",
    "openroad_physical_estimate_only": "openroad_physical",
    "asic_ppa_estimate_only": "asic_ppa",
    "fpga_board_measurement_only": "fpga_board",
}

DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": POLICY_SCHEMA_VERSION,
    "policy_id": DEFAULT_POLICY_ID,
    "decision_scope": "explored_top_k_only",
    "minimum_stage_d_tier": "hls_synthesis",
    "allow_implementation_projection": False,
    "ranking_metric": "strict_b4_event_delta_ticks_lower_is_better",
    "tie_breakers": [
        "successful_dma_transfer_bytes_lower_is_better",
        "screening_rank_lower_is_better",
    ],
    "required_b4_cycle_source": "gem5_event_timed_device_observed",
    "required_case_set": [],
    "non_claims": [
        "final_best_is_under_this_explicit_policy_only",
        "gem5_event_ticks_are_not_hardware_cycle_accuracy",
        "no_board_measurement_claim_without_fpga_board_evidence",
        "no_asic_physical_claim_without_openroad_or_asic_ppa_evidence",
    ],
}


class PolicyError(ValueError):
    pass


def default_policy() -> dict[str, Any]:
    return dict(DEFAULT_POLICY)


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise PolicyError(f"policy schema_version must be {POLICY_SCHEMA_VERSION}")
    minimum_tier = str(policy.get("minimum_stage_d_tier") or "")
    if minimum_tier not in STAGE_D_TIER_ORDER:
        raise PolicyError(f"unknown minimum_stage_d_tier: {minimum_tier}")
    if not isinstance(policy.get("allow_implementation_projection"), bool):
        raise PolicyError("allow_implementation_projection must be boolean")
    if str(policy.get("ranking_metric")) != "strict_b4_event_delta_ticks_lower_is_better":
        raise PolicyError("only strict_b4_event_delta_ticks_lower_is_better is supported in v0")
    if str(policy.get("required_b4_cycle_source")) != "gem5_event_timed_device_observed":
        raise PolicyError("v0 final-best policy requires gem5_event_timed_device_observed B4 source")


def load_policy(path_or_default: Path | str | None = None) -> dict[str, Any]:
    if path_or_default is None:
        policy = default_policy()
    else:
        payload = json.loads(Path(path_or_default).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PolicyError(f"policy must be a JSON object: {path_or_default}")
        policy = dict(payload)
    validate_policy(policy)
    return policy


def write_policy(path: Path, policy: Mapping[str, Any] | None = None) -> None:
    payload = dict(policy or default_policy())
    validate_policy(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stage_d_tier_from_evidence(evidence: Mapping[str, Any] | None) -> str | None:
    if not isinstance(evidence, Mapping):
        return None
    evidence_kind = evidence.get("evidence_kind")
    if isinstance(evidence_kind, str) and evidence_kind in STAGE_D_TIER_ORDER:
        return evidence_kind
    claim_ceiling = evidence.get("claim_ceiling")
    if isinstance(claim_ceiling, str):
        return CLAIM_CEILING_TO_STAGE_D_TIER.get(claim_ceiling)
    return None


def stage_d_tier_satisfies(actual_tier: str | None, policy: Mapping[str, Any]) -> bool:
    if actual_tier is None:
        return False
    if actual_tier == "implementation_projection" and policy.get("allow_implementation_projection") is not True:
        return False
    minimum_tier = str(policy.get("minimum_stage_d_tier"))
    return STAGE_D_TIER_ORDER.get(actual_tier, -1) >= STAGE_D_TIER_ORDER[minimum_tier]


def stage_d_satisfies_policy(evidence: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    validate_policy(policy)
    reasons: list[str] = []
    if not isinstance(evidence, Mapping):
        return False, ["missing_stage_d_implementation_evidence"]
    if evidence.get("evidence_status") != "available":
        reasons.append("stage_d_evidence_status_not_available")
    actual_tier = stage_d_tier_from_evidence(evidence)
    if actual_tier is None:
        reasons.append("stage_d_tier_unknown")
    elif actual_tier == "implementation_projection" and policy.get("allow_implementation_projection") is not True:
        reasons.append("implementation_projection_not_allowed_for_final_best")
    elif not stage_d_tier_satisfies(actual_tier, policy):
        reasons.append(
            "stage_d_tier_below_policy_minimum:{}<{}".format(
                actual_tier,
                policy.get("minimum_stage_d_tier"),
            )
        )
    correctness_dependency = evidence.get("correctness_dependency")
    if isinstance(correctness_dependency, Mapping):
        if correctness_dependency.get("qe_equivalent_scf_claim") is not True:
            reasons.append("stage_d_correctness_dependency_not_met")
    return not reasons, reasons


def claim_label_for_policy(row: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> str:
    validate_policy(policy)
    minimum_tier = str(policy.get("minimum_stage_d_tier"))
    if not isinstance(row, Mapping):
        return "no_final_best_candidate"
    candidate_id = row.get("candidate_id") or "candidate"
    return f"final_best_under_{minimum_tier}_policy::{candidate_id}"
