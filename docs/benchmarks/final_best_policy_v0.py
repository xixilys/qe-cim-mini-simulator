from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dse_evidence_tier_classifier_v0 as evidence_tiers

POLICY_SCHEMA_VERSION = "qe_fpga_final_best_policy_v0"
DEFAULT_POLICY_ID = "qe_fpga_final_best_policy_hls_v0"
SYSTEMC_B4_MINIMUM_POLICY_ID = "qe_fpga_final_best_policy_systemc_b4_minimum_v0"

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
    "stage_d_required_for_final_best": True,
    "minimum_stage_d_tier": "hls_synthesis",
    "allow_implementation_projection": False,
    "ranking_metric": "strict_b4_event_delta_ticks_lower_is_better",
    "tie_breakers": [
        "successful_dma_transfer_bytes_lower_is_better",
        "screening_rank_lower_is_better",
    ],
    "required_b4_cycle_source": "gem5_event_timed_device_observed",
    "required_final_best_evidence_tier": evidence_tiers.FINAL_BEST_ELIGIBLE,
    "require_systemc_cycle_accounted_evidence": True,
    "required_case_set": [],
    "non_claims": [
        "final_best_is_under_this_explicit_policy_only",
        "gem5_event_ticks_are_not_hardware_cycle_accuracy",
        "systemc_cycle_accounted_is_not_rtl_cycle_accurate_timing",
        "no_board_measurement_claim_without_fpga_board_evidence",
        "no_asic_physical_claim_without_openroad_or_asic_ppa_evidence",
        "no_final_best_without_same_candidate_stage_c_stage_d_strict_b4_and_systemc_cycle_evidence",
    ],
}

SYSTEMC_B4_MINIMUM_POLICY: dict[str, Any] = {
    "schema_version": POLICY_SCHEMA_VERSION,
    "policy_id": SYSTEMC_B4_MINIMUM_POLICY_ID,
    "decision_scope": "closed_catalog_competitive_partition",
    "stage_d_required_for_final_best": False,
    "minimum_stage_d_tier": None,
    "allow_implementation_projection": False,
    "ranking_metric": "strict_b4_event_delta_ticks_lower_is_better",
    "tie_breakers": [
        "successful_dma_transfer_bytes_lower_is_better",
        "screening_rank_lower_is_better",
    ],
    "required_b4_cycle_source": "gem5_event_timed_device_observed",
    "required_final_best_evidence_tier": evidence_tiers.FINAL_BEST_ELIGIBLE,
    "require_systemc_cycle_accounted_evidence": True,
    "require_catalog_freeze_membership": True,
    "require_dominance_closure": True,
    "required_case_set": [],
    "optional_precision_upgrades": [
        "stage_d_hls_or_stronger_implementation_evidence",
        "fpga_board_measurement",
        "asic_or_physical_timing_evidence",
    ],
    "non_claims": [
        "final_best_is_under_this_explicit_policy_only",
        "closed_catalog_best_is_not_global_best",
        "gem5_event_ticks_are_not_hardware_cycle_accuracy",
        "systemc_cycle_accounted_is_not_rtl_cycle_accurate_timing",
        "no_board_measurement_claim_without_fpga_board_evidence",
        "no_asic_physical_claim_without_openroad_or_asic_ppa_evidence",
        "no_final_best_without_same_candidate_stage_c_strict_b4_systemc_cycle_catalog_freeze_and_dominance_evidence",
        "missing_stage_d_hls_fpga_asic_or_board_measurement_is_residual_risk_under_systemc_b4_minimum",
    ],
}


class PolicyError(ValueError):
    pass


def default_policy() -> dict[str, Any]:
    return dict(DEFAULT_POLICY)


def systemc_b4_minimum_policy() -> dict[str, Any]:
    return dict(SYSTEMC_B4_MINIMUM_POLICY)


def stage_d_required_for_final_best(policy: Mapping[str, Any]) -> bool:
    return policy.get("stage_d_required_for_final_best", True) is not False


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise PolicyError(f"policy schema_version must be {POLICY_SCHEMA_VERSION}")
    if not isinstance(policy.get("stage_d_required_for_final_best", True), bool):
        raise PolicyError("stage_d_required_for_final_best must be boolean when present")
    stage_d_required = stage_d_required_for_final_best(policy)
    minimum_tier_value = policy.get("minimum_stage_d_tier")
    minimum_tier = str(minimum_tier_value or "")
    if stage_d_required and minimum_tier not in STAGE_D_TIER_ORDER:
        raise PolicyError(f"unknown minimum_stage_d_tier: {minimum_tier}")
    if not stage_d_required and minimum_tier_value not in (None, "", "not_required"):
        raise PolicyError("minimum_stage_d_tier must be null/empty/not_required when Stage D is optional")
    if not isinstance(policy.get("allow_implementation_projection"), bool):
        raise PolicyError("allow_implementation_projection must be boolean")
    if str(policy.get("ranking_metric")) != "strict_b4_event_delta_ticks_lower_is_better":
        raise PolicyError("only strict_b4_event_delta_ticks_lower_is_better is supported in v0")
    if str(policy.get("required_b4_cycle_source")) != "gem5_event_timed_device_observed":
        raise PolicyError("v0 final-best policy requires gem5_event_timed_device_observed B4 source")
    required_tier = str(policy.get("required_final_best_evidence_tier", evidence_tiers.FINAL_BEST_ELIGIBLE))
    if required_tier != evidence_tiers.FINAL_BEST_ELIGIBLE:
        raise PolicyError("v0 final-best policy requires final-best-eligible evidence tier")
    if not isinstance(policy.get("require_systemc_cycle_accounted_evidence", True), bool):
        raise PolicyError("require_systemc_cycle_accounted_evidence must be boolean")
    if not isinstance(policy.get("require_catalog_freeze_membership", False), bool):
        raise PolicyError("require_catalog_freeze_membership must be boolean when present")
    if not isinstance(policy.get("require_dominance_closure", False), bool):
        raise PolicyError("require_dominance_closure must be boolean when present")


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
    if not stage_d_required_for_final_best(policy):
        return True
    if actual_tier is None:
        return False
    if actual_tier == "implementation_projection" and policy.get("allow_implementation_projection") is not True:
        return False
    minimum_tier = str(policy.get("minimum_stage_d_tier"))
    return STAGE_D_TIER_ORDER.get(actual_tier, -1) >= STAGE_D_TIER_ORDER[minimum_tier]


def stage_d_satisfies_policy(evidence: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    validate_policy(policy)
    reasons: list[str] = []
    if not stage_d_required_for_final_best(policy):
        return True, []
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
    if not stage_d_required_for_final_best(policy):
        minimum_tier = "systemc_b4_minimum"
    else:
        minimum_tier = str(policy.get("minimum_stage_d_tier"))
    if not isinstance(row, Mapping):
        return "no_final_best_candidate"
    candidate_id = row.get("candidate_id") or "candidate"
    return f"final_best_under_{minimum_tier}_policy::{candidate_id}"


def is_stage_d_blocker(reason: str) -> bool:
    return reason.startswith(
        (
            "missing_stage_d",
            "stage_d_",
            "implementation_projection_",
        )
    )


def filter_policy_blockers(reasons: Sequence[str], policy: Mapping[str, Any]) -> list[str]:
    validate_policy(policy)
    if stage_d_required_for_final_best(policy):
        return list(reasons)
    return [reason for reason in reasons if not is_stage_d_blocker(str(reason))]


def optional_precision_upgrade_risks(evidence: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> list[str]:
    validate_policy(policy)
    if stage_d_required_for_final_best(policy):
        return []
    if not isinstance(evidence, Mapping):
        return ["missing_optional_stage_d_hls_or_stronger_evidence"]
    actual_tier = stage_d_tier_from_evidence(evidence)
    if actual_tier is None:
        return ["optional_stage_d_tier_unknown"]
    if evidence.get("evidence_status") != "available":
        return [f"optional_stage_d_evidence_not_available:{evidence.get('evidence_status')}"]
    return [f"optional_stage_d_evidence_present:{actual_tier}"]
