from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


SYSTEMC_FEEDBACK_CONTRACT_VERSION = "qe_dse_systemc_feedback_contract_v0"
GEM5_SYSTEMC_HANDOFF_CONTRACT_VERSION = "qe_dse_gem5_systemc_handoff_contract_v0"
QE_ANCHOR_REFS_VERSION = "qe_anchor_refs_v0"
BACKEND_NEUTRAL_SCHEMA_VERSION = "unified_dse_backend_neutral_schema_stage_a_v0"

SYSTEMC_METRICS_EXPECTED_KEYS = [
    "time_proxy_s",
    "energy_proxy_j",
    "cycle_proxy",
    "resident_reuse_ratio",
    "spill_count",
    "fallback_count",
    "diag_policy",
    "offload_scope",
]

SYSTEMC_CALIBRATION_JOIN_KEYS = [
    "workload_id",
    "case_id",
    "candidate_id",
    "candidate_family",
    "architecture_template_id",
    "assumption_set_id",
]

GEM5_OUTPUT_REPORT_EXPECTED_KEYS = [
    "run_id",
    "environment",
    "workload_identity",
    "candidate_identity",
    "scf_control_loop_status",
    "systemc_bridge_status",
    "qe_equivalence_status",
    "metrics",
    "correctness_gate",
    "claim_ceiling",
]


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {}


def _clean_token(value: Any) -> str:
    token = str(value) if value not in (None, "") else "unknown"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in token)


def _candidate_id(workload: Mapping[str, Any], design_point: Mapping[str, Any]) -> str:
    keys = (
        workload.get("workload_id"),
        design_point.get("family"),
        design_point.get("diag_policy"),
        design_point.get("offload_scope"),
        design_point.get("resident_policy"),
        design_point.get("partition_strategy"),
    )
    return "__".join(_clean_token(value) for value in keys)


def _merge_contract_defaults(defaults: Mapping[str, Any], existing: Any) -> dict[str, Any]:
    merged = dict(defaults)
    if isinstance(existing, Mapping):
        merged.update(deepcopy(dict(existing)))
    return merged


def default_contract_fields(
    workload: Any,
    design_point: Any,
    backend: str,
    source_kind: str,
) -> dict[str, Any]:
    workload_payload = _payload(workload)
    design_point_payload = _payload(design_point)
    candidate_id = _candidate_id(workload_payload, design_point_payload)
    case_id = workload_payload.get("case_id") or workload_payload.get("workload_id")
    architecture_template_id = (
        workload_payload.get("architecture_template_id")
        or f"template_{_clean_token(design_point_payload.get('family'))}_stage_a"
    )
    assumption_set_id = workload_payload.get("assumption_set_id") or "stage_a_dry_run_assumption_set"
    implementation_target_class = workload_payload.get("implementation_target_class") or "unknown"
    backend_profile_id = (
        workload_payload.get("backend_profile_id") or "stage_a_systemc_timed_functional_proxy"
    )
    return {
        "backend_neutral_schema": {
            "schema_version": BACKEND_NEUTRAL_SCHEMA_VERSION,
            "architecture_family": design_point_payload.get("family"),
            "implementation_backend": backend,
            "source_kind": source_kind,
            "supported_target_classes": ["fpga", "asic"],
            "cim_lockin": False,
            "claim_ceiling": "backend_identity_and_stage_a_contract_only",
        },
        "systemc_feedback_contract": {
            "schema_version": SYSTEMC_FEEDBACK_CONTRACT_VERSION,
            "status": "planned_not_executed",
            "execution_status": "not_executed",
            "backend_class": "systemc_timed_functional_proxy",
            "candidate_config_ref": f"systemc_configs/{candidate_id}.json",
            "metrics_ref": None,
            "metrics_expected_keys": list(SYSTEMC_METRICS_EXPECTED_KEYS),
            "calibration_join_keys": list(SYSTEMC_CALIBRATION_JOIN_KEYS),
            "subprocess_invoked": False,
            "calibration_status": "not_applicable_for_dry_run",
            "claim_ceiling": "timed_functional_proxy_contract_only",
            "adapter_status": "future_explicit_adapter",
            "candidate_id": candidate_id,
            "candidate_family": design_point_payload.get("family"),
            "architecture_template_id": architecture_template_id,
            "implementation_target_class": implementation_target_class,
            "backend_profile_id": backend_profile_id,
            "design_axes": deepcopy(design_point_payload),
            "assumption_set_id": assumption_set_id,
        },
        "gem5_handoff_contract": {
            "schema_version": GEM5_SYSTEMC_HANDOFF_CONTRACT_VERSION,
            "status": "planned_for_stage_b",
            "handoff_status": "planned",
            "execution_status": "not_executed",
            "platform_status": "requires_linux_x86_validation",
            "input_descriptor_ref": f"gem5_systemc_handoff/{candidate_id}.json",
            "expected_command": (
                "stage_b_gem5_systemc_scf_driver "
                f"--descriptor gem5_systemc_handoff/{candidate_id}.json "
                f"--output gem5_systemc_reports/{candidate_id}.json"
            ),
            "expected_report_ref": f"gem5_systemc_reports/{candidate_id}.json",
            "output_report_expected_keys": list(GEM5_OUTPUT_REPORT_EXPECTED_KEYS),
            "handoff_goal": "gem5_controls_systemc_fpgamodule_for_complete_scf_loop",
            "stage_b_execution_claim": False,
            "claim_ceiling": "stage_b_handoff_contract_only",
        },
        "qe_anchor_refs": {
            "schema_version": QE_ANCHOR_REFS_VERSION,
            "status": "trace_or_correctness_anchor_only",
            "qe_equivalent_scf_claim": False,
            "claim_ceiling": "anchor_reference_only",
            "workload_id": workload_payload.get("workload_id"),
            "case_id": case_id,
            "workload_group_id": workload_payload.get("workload_group_id"),
            "signature_id": workload_payload.get("signature_id"),
            "qe_tolerance_schema_id": workload_payload.get("qe_tolerance_schema_id"),
            "trace_ref": workload_payload.get("trace_ref"),
            "dump_ref": workload_payload.get("dump_ref"),
            "correctness_anchor_ref": workload_payload.get("correctness_anchor_ref"),
            "anchor_evidence_kind": workload_payload.get("anchor_evidence_kind")
            or "missing_or_trace_only",
        },
    }


def attach_stage_a_contracts(row: Mapping[str, Any], refresh: bool = False) -> dict[str, Any]:
    copied = deepcopy(dict(row))
    defaults = default_contract_fields(
        workload=copied.get("workload", {}),
        design_point=copied.get("design_point", {}),
        backend=str(copied.get("backend", "")),
        source_kind=str(copied.get("source_kind", "")),
    )
    for key, value in defaults.items():
        if refresh or key not in copied:
            copied[key] = value
        else:
            copied[key] = _merge_contract_defaults(value, copied.get(key))
    projection = copied.get("projection", {})
    if isinstance(projection, Mapping):
        copied["systemc_feedback_contract"]["runtime_projection_family"] = projection.get(
            "runtime_projection_family"
        )
        copied["backend_neutral_schema"]["runtime_projection_family"] = projection.get(
            "runtime_projection_family"
        )
    return copied
