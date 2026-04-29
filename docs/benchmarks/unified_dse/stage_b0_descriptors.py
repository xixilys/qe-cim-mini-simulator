from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import constraints, domain_contracts


DESCRIPTOR_MANIFEST_NAME = "stage_b0_descriptor_manifest_v0.json"
SYSTEMC_CONFIG_SCHEMA_VERSION = "qe_dse_systemc_candidate_config_stage_b0_v0"
ARCHITECTURE_CONFIG_SCHEMA_VERSION = "systemc_architecture_config_v1"
GEM5_HANDOFF_DESCRIPTOR_SCHEMA_VERSION = "qe_dse_gem5_systemc_handoff_descriptor_stage_b0_v0"
EMISSION_ALL_VALID_EXECUTABLE = "all_valid_executable"
EMISSION_SCHEDULER_SELECTED_ONLY = "scheduler_selected_only"
EMISSION_MODES = (EMISSION_ALL_VALID_EXECUTABLE, EMISSION_SCHEDULER_SELECTED_ONLY)


def _require_mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"row missing Stage B0 mapping: {key}")
    return value


def _candidate_id(row: Mapping[str, Any]) -> str:
    systemc_feedback = _require_mapping(row, "systemc_feedback_contract")
    candidate_id = systemc_feedback.get("candidate_id")
    if not candidate_id:
        raise ValueError("row missing systemc_feedback_contract.candidate_id")
    return str(candidate_id)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workload_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    workload = _require_mapping(row, "workload")
    identity = dict(row.get("workload_identity", {}) if isinstance(row.get("workload_identity"), Mapping) else {})
    if not identity:
        identity = domain_contracts.workload_identity(workload)
    if domain_contracts.is_qe_workload(workload):
        qe_anchor_refs = _require_mapping(row, "qe_anchor_refs")
        identity.update(
            {
                "case_id": qe_anchor_refs.get("case_id"),
                "signature_id": workload.get("signature_id"),
                "pseudopotential_family": workload.get("pseudopotential_family"),
                "qe_tolerance_schema_id": workload.get("qe_tolerance_schema_id"),
            }
        )
    return {
        **identity,
        "workload_group_id": workload.get("workload_group_id"),
        "accounting_boundary_id": workload.get("accounting_boundary_id"),
        "observability_contract_id": workload.get("observability_contract_id"),
    }


def _candidate_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    design_point = _require_mapping(row, "design_point")
    systemc_feedback = _require_mapping(row, "systemc_feedback_contract")
    backend_neutral_schema = _require_mapping(row, "backend_neutral_schema")
    design_validation = row.get("design_validation", {})
    if not isinstance(design_validation, Mapping):
        design_validation = {}
    projection = row.get("projection", {})
    if not isinstance(projection, Mapping):
        projection = {}
    return {
        "candidate_id": systemc_feedback.get("candidate_id"),
        "candidate_family": systemc_feedback.get("candidate_family"),
        "architecture_template_id": systemc_feedback.get("architecture_template_id"),
        "implementation_target_class": systemc_feedback.get("implementation_target_class"),
        "backend_profile_id": systemc_feedback.get("backend_profile_id"),
        "runtime_projection_family": projection.get("runtime_projection_family"),
        "implementation_backend": backend_neutral_schema.get("implementation_backend"),
        "source_kind": backend_neutral_schema.get("source_kind"),
        "validity_class": design_validation.get("validity_class"),
        "design_axes": dict(design_point),
    }


def _sidecar_refs(row: Mapping[str, Any]) -> dict[str, str]:
    workload = _require_mapping(row, "workload")
    design_point = _require_mapping(row, "design_point")
    identity = _candidate_identity(row)
    architecture_template_id = str(identity.get("architecture_template_id") or "unknown_template")
    candidate_id = str(identity.get("candidate_id") or _candidate_id(row))
    return {
        "application_graph_ref": domain_contracts.application_graph_ref(workload),
        "architecture_template_ref": domain_contracts.architecture_template_ref(architecture_template_id),
        "mapping_ref": domain_contracts.mapping_sidecar_ref(design_point),
        "candidate_descriptor_ref": domain_contracts.candidate_descriptor_ref(candidate_id),
    }


def _write_ir_sidecars(root: Path, row: Mapping[str, Any]) -> dict[str, str]:
    refs = _sidecar_refs(row)
    workload = _require_mapping(row, "workload")
    design_point = _require_mapping(row, "design_point")
    identity = _candidate_identity(row)
    architecture_template_id = str(identity.get("architecture_template_id") or "unknown_template")
    target_class = str(identity.get("implementation_target_class") or "unknown")
    candidate_descriptor = dict(_require_mapping(row, "candidate_descriptor"))
    candidate_descriptor.update(
        {
            "application_graph_ref": refs["application_graph_ref"],
            "architecture_template_ref": refs["architecture_template_ref"],
            "mapping_ref": refs["mapping_ref"],
        }
    )
    _write_json(root / refs["application_graph_ref"], domain_contracts.build_application_graph_ir(workload))
    _write_json(
        root / refs["architecture_template_ref"],
        domain_contracts.build_architecture_template_ir(
            architecture_template_id,
            design_point,
            target_class,
        ),
    )
    _write_json(root / refs["mapping_ref"], domain_contracts.build_mapping_ir(design_point, workload))
    _write_json(root / refs["candidate_descriptor_ref"], candidate_descriptor)
    return refs


def _systemc_config(row: Mapping[str, Any], sidecar_refs: Mapping[str, str], architecture_config_ref: str) -> dict[str, Any]:
    return {
        "schema_version": SYSTEMC_CONFIG_SCHEMA_VERSION,
        "execution_status": "not_executed",
        "claim_ceiling": "systemc_config_descriptor_only",
        "candidate_identity": _candidate_identity(row),
        "workload_identity": _workload_identity(row),
        "design_point": dict(_require_mapping(row, "design_point")),
        "ir_refs": dict(sidecar_refs),
        "architecture_config_ref": architecture_config_ref,
        "backend_neutral_schema": dict(_require_mapping(row, "backend_neutral_schema")),
        "systemc_feedback_contract": dict(_require_mapping(row, "systemc_feedback_contract")),
        "candidate_descriptor": dict(_require_mapping(row, "candidate_descriptor")),
        "backend_execution_request": dict(_require_mapping(row, "backend_execution_request")),
        "workload_anchor_refs": dict(_require_mapping(row, "workload_anchor_refs")),
        "domain_extension": dict(row.get("domain_extension", {}))
        if isinstance(row.get("domain_extension", {}), Mapping)
        else {},
        "design_validation": dict(_require_mapping(row, "design_validation")),
        "qe_anchor_refs": dict(_require_mapping(row, "qe_anchor_refs")),
        "non_claims": [
            "not_systemc_executed",
            "not_gem5_executed",
            "not_qe_equivalent_scf",
            "not_rtl_hls_board_evidence",
        ],
    }



def _architecture_family(identity: Mapping[str, Any], design_point: Mapping[str, Any]) -> str:
    for value in (
        identity.get("candidate_family"),
        identity.get("architecture_template_id"),
        design_point.get("family"),
        design_point.get("architecture_family"),
    ):
        if isinstance(value, str) and value.strip():
            token = value.strip().upper()
            if token.startswith("F1"):
                return "F1"
            if token.startswith("F3"):
                return "F3"
            if token.startswith("F2"):
                return "F2"
    return "F2"


def _architecture_config(row: Mapping[str, Any], sidecar_refs: Mapping[str, str]) -> dict[str, Any]:
    identity = _candidate_identity(row)
    design_point = _require_mapping(row, "design_point")
    family = _architecture_family(identity, design_point)
    cluster_specs = (
        ("cluster_a", "operator_sweep", 448),
        ("cluster_b", "reduced_build", 128),
        ("cluster_c", "hardware_diag", 256),
        ("cluster_d", "refresh_residual", 128),
    )
    if family == "F3":
        cluster_specs = (
            ("cluster_a", "operator_sweep", 512),
            ("cluster_b", "reduced_build", 192),
            ("cluster_c", "hardware_diag", 384),
            ("cluster_d", "refresh_residual", 192),
        )
    elif family == "F1":
        cluster_specs = (
            ("cluster_a", "operator_sweep", 448),
            ("cluster_b", "reduced_build", 128),
            ("cluster_c", "hardware_diag", 256),
            ("cluster_d", "refresh_residual", 128),
        )
    compute_unit_type = "traditional_fpga" if "traditional" in str(identity.get("architecture_template_id", "")).lower() else "cim_array"
    clusters = []
    for cluster_id, cluster_type, buffer_kb in cluster_specs:
        clusters.append(
            {
                "cluster_id": cluster_id,
                "type": cluster_type,
                "enabled": True,
                # The current SystemC JSON parser is intentionally lightweight and
                # resolves the first `"type"` token inside each cluster object. Keep
                # compute_unit as a string here so the cluster-level `type` remains
                # unambiguous and the B2 run is metric-bearing rather than a
                # 0-cluster/0-cycle descriptor parse.
                "compute_unit": compute_unit_type,
                "on_chip_buffer_kb": int(design_point.get("on_chip_buffer_kb", buffer_kb) or buffer_kb),
                "dma_bandwidth_gbps": int(design_point.get("dma_bandwidth_gbps", 100) or 100),
                "enable_pipelining": True,
                "pipeline_depth": int(design_point.get("pipeline_depth", 4) or 4),
                "resident_policy": str(design_point.get("resident_policy", "fit_first")),
                "resident_budget_scale": float(design_point.get("resident_budget_scale", 1.0) or 1.0),
                "enable_backpressure": True,
                "max_concurrent_ops": int(design_point.get("max_concurrent_ops", 8) or 8),
            }
        )
    return {
        "schema_version": ARCHITECTURE_CONFIG_SCHEMA_VERSION,
        "execution_status": "not_executed",
        "claim_ceiling": "architecture_config_descriptor_only",
        "candidate_identity": identity,
        "workload_identity": _workload_identity(row),
        "design_point": dict(design_point),
        "ir_refs": dict(sidecar_refs),
        "template_id": str(identity.get("architecture_template_id") or family),
        "template_label": str(identity.get("architecture_template_id") or family),
        "architecture_family": family,
        "clusters": clusters,
        "global_policies": {
            "offload_scope": str(design_point.get("offload_scope", "balanced")),
            "diag_policy": str(design_point.get("diag_policy", "device_first_fallback")),
            "enable_device_fft": family != "F1",
            "force_host_diag": family == "F1",
            "allow_cpu_diag_fallback": True,
        },
        "resource_limits": {
            "max_dsp": 6840,
            "max_bram_18k": 4320,
            "max_uram": 960,
            "max_lut": 1182240,
            "max_ff": 2364480,
        },
        "interconnect": {
            "axi_data_width": 512,
            "axi_burst_length": 256,
            "pcie_bandwidth_gbps": 32.0,
            "ddr_bandwidth_gbps": 76.8,
        },
        "timing": {
            "system_clock_mhz": float(design_point.get("system_clock_mhz", 250.0) or 250.0),
            "use_proxy_formulas": True,
            "proxy_uncertainty": 0.20,
        },
        "descriptor_provenance": {
            "source": "stage_b0_architecture_config_projection",
            "systemc_config_separated": True,
            "claim_ceiling": "architecture_config_descriptor_only",
        },
        "non_claims": [
            "not_systemc_executed",
            "not_gem5_executed",
            "not_qe_equivalent_scf",
            "not_rtl_hls_board_evidence",
        ],
    }

def _gem5_descriptor(row: Mapping[str, Any], systemc_config_ref: str, architecture_config_ref: str, sidecar_refs: Mapping[str, str]) -> dict[str, Any]:
    gem5_handoff = _require_mapping(row, "gem5_handoff_contract")
    return {
        "schema_version": GEM5_HANDOFF_DESCRIPTOR_SCHEMA_VERSION,
        "execution_status": "not_executed",
        "claim_ceiling": "stage_b0_handoff_descriptor_only",
        "candidate_identity": _candidate_identity(row),
        "workload_identity": _workload_identity(row),
        "ir_refs": dict(sidecar_refs),
        "systemc_config_ref": systemc_config_ref,
        "architecture_config_ref": architecture_config_ref,
        "backend_execution_request_ref": f"backend_execution_requests/{_candidate_id(row)}.json",
        "expected_command": gem5_handoff.get("expected_command"),
        "expected_report_ref": gem5_handoff.get("expected_report_ref"),
        "output_report_expected_keys": list(gem5_handoff.get("output_report_expected_keys", [])),
        "systemc_feedback_contract": dict(_require_mapping(row, "systemc_feedback_contract")),
        "gem5_handoff_contract": dict(gem5_handoff),
        "candidate_descriptor": dict(_require_mapping(row, "candidate_descriptor")),
        "backend_execution_request": dict(_require_mapping(row, "backend_execution_request")),
        "workload_anchor_refs": dict(_require_mapping(row, "workload_anchor_refs")),
        "domain_extension": dict(row.get("domain_extension", {}))
        if isinstance(row.get("domain_extension", {}), Mapping)
        else {},
        "design_validation": dict(_require_mapping(row, "design_validation")),
        "qe_anchor_refs": dict(_require_mapping(row, "qe_anchor_refs")),
        "non_claims": [
            "descriptor_only",
            "not_gem5_controlled_systemc_execution",
            "not_qe_equivalent_scf",
        ],
    }


def _backend_execution_request(row: Mapping[str, Any], systemc_config_ref: str, architecture_config_ref: str, sidecar_refs: Mapping[str, str]) -> dict[str, Any]:
    request = dict(_require_mapping(row, "backend_execution_request"))
    request["input_refs"] = dict(request.get("input_refs", {}))
    request["input_refs"].update(
        {
            "application_graph": sidecar_refs["application_graph_ref"],
            "architecture_template": sidecar_refs["architecture_template_ref"],
            "mapping": sidecar_refs["mapping_ref"],
            "architecture_config": architecture_config_ref,
            "systemc_config": systemc_config_ref,
            "architecture_config": architecture_config_ref,
        }
    )
    return request


def _design_validation(row: Mapping[str, Any]) -> dict[str, Any]:
    validation = row.get("design_validation")
    if isinstance(validation, Mapping):
        return dict(validation)
    return constraints.validate_design_point(
        _require_mapping(row, "design_point"),
        _require_mapping(row, "workload"),
    )


def _row_with_design_validation(
    row: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    copied = dict(row)
    copied["design_validation"] = dict(validation)
    candidate_descriptor = copied.get("candidate_descriptor")
    if isinstance(candidate_descriptor, Mapping):
        copied["candidate_descriptor"] = dict(candidate_descriptor)
        copied["candidate_descriptor"]["validity_class"] = validation.get("validity_class")
        copied["candidate_descriptor"]["design_validation"] = dict(validation)
        descriptor_candidate_identity = copied["candidate_descriptor"].get("candidate_identity")
        if isinstance(descriptor_candidate_identity, Mapping):
            copied["candidate_descriptor"]["candidate_identity"] = dict(
                descriptor_candidate_identity
            )
            copied["candidate_descriptor"]["candidate_identity"]["validity_class"] = validation.get(
                "validity_class"
            )
    backend_execution_request = copied.get("backend_execution_request")
    if isinstance(backend_execution_request, Mapping):
        copied["backend_execution_request"] = dict(backend_execution_request)
        request_candidate_identity = copied["backend_execution_request"].get("candidate_identity")
        if isinstance(request_candidate_identity, Mapping):
            copied["backend_execution_request"]["candidate_identity"] = dict(
                request_candidate_identity
            )
            copied["backend_execution_request"]["candidate_identity"]["validity_class"] = validation.get(
                "validity_class"
            )
    return copied


def _selected_candidate_ids(multi_fidelity_plan: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(multi_fidelity_plan, Mapping):
        return set()
    selected = multi_fidelity_plan.get("selected_candidates", [])
    if not isinstance(selected, list):
        return set()
    return {
        str(item.get("candidate_id"))
        for item in selected
        if isinstance(item, Mapping) and item.get("candidate_id")
    }


def emit_stage_b0_descriptors(
    output_dir: Path | str,
    rows: Sequence[Mapping[str, Any]],
    emission_mode: str = EMISSION_ALL_VALID_EXECUTABLE,
    multi_fidelity_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if emission_mode not in EMISSION_MODES:
        raise ValueError(f"unsupported Stage B0 emission mode: {emission_mode}")
    root = Path(output_dir)
    descriptors = []
    blocked_descriptors = []
    unselected_valid_candidates = []
    selected_ids = _selected_candidate_ids(multi_fidelity_plan)
    for row in rows:
        candidate_id = _candidate_id(row)
        validation = _design_validation(row)
        if validation.get("validity_class") != "valid_executable":
            blocked_descriptors.append(
                {
                    "candidate_id": candidate_id,
                    "descriptor_status": "blocked_by_validation",
                    "validity_class": validation.get("validity_class"),
                    "promotion_blockers": list(validation.get("promotion_blockers", [])),
                    "claim_ceiling": validation.get("claim_ceiling", "descriptor_only"),
                }
            )
            continue
        if emission_mode == EMISSION_SCHEDULER_SELECTED_ONLY and candidate_id not in selected_ids:
            unselected_valid_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "descriptor_status": "not_selected_by_scheduler",
                    "validity_class": "valid_executable",
                    "claim_ceiling": "descriptor_only",
                }
            )
            continue
        validated_row = _row_with_design_validation(row, validation)
        sidecar_refs = _write_ir_sidecars(root, validated_row)
        architecture_config_ref = f"architecture_configs/{candidate_id}.json"
        systemc_config_ref = f"systemc_configs/{candidate_id}.json"
        gem5_descriptor_ref = f"gem5_systemc_handoff/{candidate_id}.json"
        backend_execution_request_ref = f"backend_execution_requests/{candidate_id}.json"
        _write_json(root / architecture_config_ref, _architecture_config(validated_row, sidecar_refs))
        _write_json(root / systemc_config_ref, _systemc_config(validated_row, sidecar_refs, architecture_config_ref))
        _write_json(
            root / gem5_descriptor_ref,
            _gem5_descriptor(validated_row, systemc_config_ref, architecture_config_ref, sidecar_refs),
        )
        _write_json(
            root / backend_execution_request_ref,
            _backend_execution_request(validated_row, systemc_config_ref, architecture_config_ref, sidecar_refs),
        )
        descriptors.append(
            {
                "candidate_id": candidate_id,
                **dict(sidecar_refs),
                "architecture_config_ref": architecture_config_ref,
                "systemc_config_ref": systemc_config_ref,
                "gem5_descriptor_ref": gem5_descriptor_ref,
                "backend_execution_request_ref": backend_execution_request_ref,
                "execution_status": "not_executed",
                "claim_ceiling": "descriptor_generation_only",
            }
        )

    manifest = {
        "schema_version": DESCRIPTOR_MANIFEST_NAME.removesuffix(".json"),
        "execution_status": "not_executed",
        "claim_ceiling": "descriptor_generation_only",
        "emission_mode": emission_mode,
        "multi_fidelity_plan_ref": (
            "multi_fidelity_plan_v0.json" if multi_fidelity_plan is not None else None
        ),
        "descriptor_count": len(descriptors),
        "blocked_descriptor_count": len(blocked_descriptors),
        "unselected_valid_candidate_count": len(unselected_valid_candidates),
        "descriptors": descriptors,
        "emitted_descriptors": descriptors,
        "unselected_valid_candidates": unselected_valid_candidates,
        "blocked_descriptors": blocked_descriptors,
    }
    _write_json(root / DESCRIPTOR_MANIFEST_NAME, manifest)
    return manifest
