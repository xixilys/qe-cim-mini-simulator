#!/usr/bin/env python3
"""DFT plugin proposal for the seven-axis co-design release domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.release_domain import (
    AxisDomain,
    AxisValue,
    axis_value_ids,
    build_candidate_universe,
    build_domain_freeze,
    stable_json_hash,
)
from dse_v2.reference_workloads.dft_step2_policy import (
    build_dft_hierarchical_funnel_search_report,
)


DFT_CODESIGN_RELEASE_ID = "dft_first_seven_axis_release_v1"
DFT_RELEASE_PRESET_AXIS_IDS = (
    "dft_phase_hotspot_selection",
    "algorithm_variants",
    "schedule_runtime_policy",
    "mapping_data_layout",
    "hardware_microarchitecture",
    "interface_descriptor_protocol",
    "evidence_fidelity_promotion_policy",
)
DFT_SEVEN_AXIS_IDS = DFT_RELEASE_PRESET_AXIS_IDS
DFT_EVALUATION_RECORD_AXIS_IDS = DFT_RELEASE_PRESET_AXIS_IDS
DFT_APPLICABILITY_SCOPE_AXIS_IDS = ("dft_phase_hotspot_selection",)
DFT_EVIDENCE_ROUTING_AXIS_IDS = ("evidence_fidelity_promotion_policy",)
DFT_STABLE_DESIGN_IDENTITY_AXIS_IDS = tuple(
    axis_id
    for axis_id in DFT_RELEASE_PRESET_AXIS_IDS
    if axis_id not in {*DFT_APPLICABILITY_SCOPE_AXIS_IDS, *DFT_EVIDENCE_ROUTING_AXIS_IDS}
)
DFT_APPLICABILITY_AXIS_IDS = DFT_APPLICABILITY_SCOPE_AXIS_IDS
DFT_EVALUATION_POLICY_AXIS_IDS = DFT_EVIDENCE_ROUTING_AXIS_IDS
DFT_DESIGN_AXIS_IDS = DFT_STABLE_DESIGN_IDENTITY_AXIS_IDS

DFT_LEGALITY_CONSTRAINTS = (
    {
        "constraint_id": "batched_gemm_requires_band_block_layout",
        "when": {"algorithm_variants": "batched_gemm_exx"},
        "requires": {"mapping_data_layout": "band_block_systolic"},
        "reason": "batched_gemm_exx requires band_block_systolic layout",
    },
    {
        "constraint_id": "fft_grid_layout_bound_to_host_fpga",
        "when": {"mapping_data_layout": "fft_grid_hbm_tiled"},
        "requires": {"hardware_microarchitecture": "host_fpga_minimal_v0"},
        "reason": "fft_grid_hbm_tiled release value is bound to host_fpga_minimal_v0 in this frozen domain",
    },
    {
        "constraint_id": "batched_descriptor_requires_batched_gemm",
        "when": {"interface_descriptor_protocol": "batched_kernel_descriptor_v1"},
        "requires": {"algorithm_variants": "batched_gemm_exx"},
        "reason": "batched descriptor requires batched_gemm_exx algorithm",
    },
)

DFT_APPLICABILITY_COMPATIBILITY_RULES = (
    {
        "rule_id": "hybrid_exx_requires_batched_gemm",
        "when": {"dft_phase_hotspot_selection": "hybrid_exx_fft"},
        "requires": {"algorithm_variants": "batched_gemm_exx"},
        "reason": "hybrid_exx_fft applicability requires batched_gemm_exx algorithm template",
    },
)

DFT_EVALUATION_POLICY_COMPATIBILITY_RULES = (
    {
        "rule_id": "eda_formal_ladder_routes_to_genericaccel_descriptor",
        "when": {"evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder"},
        "requires": {"interface_descriptor_protocol": "genericaccel_descriptor_v1"},
        "reason": "EDA/formal ladder routes to genericaccel_descriptor_v1 promotion evidence",
    },
)

_SOURCE_LEDGER = (
    {
        "id": "S01",
        "kind": "official_docs",
        "source": "Quantum ESPRESSO pw.x input description v7.5",
        "url": "https://www.quantum-espresso.org/Doc/INPUT_PW.html",
        "supports": ["dft_phase_hotspot_selection", "algorithm_variants"],
    },
    {
        "id": "S03",
        "kind": "paper",
        "source": "Giannozzi et al., Quantum ESPRESSO toward the exascale, JCP 2020",
        "doi": "10.1063/5.0005082",
        "supports": ["algorithm_variants", "schedule_runtime_policy"],
    },
    {
        "id": "S15",
        "kind": "vendor_official",
        "source": "AMD Alveo U280 product brief",
        "supports": ["hardware_microarchitecture", "mapping_data_layout"],
    },
    {
        "id": "S19",
        "kind": "vendor_app_note",
        "source": "Alpha Data HBM FPGA memory-bandwidth app note",
        "supports": ["mapping_data_layout", "hardware_microarchitecture"],
    },
    {
        "id": "S21",
        "kind": "research_software_docs",
        "source": "AutoSA matrix multiplication with HBM example",
        "supports": ["algorithm_variants", "hardware_microarchitecture"],
    },
    {
        "id": "S22",
        "kind": "vendor_benchmark",
        "source": "Xilinx Vitis BLAS benchmark",
        "supports": ["algorithm_variants", "evidence_fidelity_promotion_policy"],
    },
    {
        "id": "GENERIC_DSE_V2",
        "kind": "repo_architecture_doc",
        "source": "docs/architecture/generic_dse_framework_design_spec_v2.md",
        "supports": [
            "schedule_runtime_policy",
            "interface_descriptor_protocol",
            "evidence_fidelity_promotion_policy",
        ],
    },
)


def dft_seven_axis_source_ledger() -> list[Dict[str, Any]]:
    return [dict(item) for item in _SOURCE_LEDGER]


def dft_legality_constraints() -> list[Dict[str, Any]]:
    """Return design-only DFT legality constraints for the generic universe builder."""
    return [
        {
            "schema_version": "dse.dft.legality_constraint.v1",
            **dict(item),
            "axis_ids": sorted({*item["when"], *item["requires"]}),
            "claim_boundary": "DFT plugin data for generic design legality evaluation; not core coupling.",
        }
        for item in DFT_LEGALITY_CONSTRAINTS
    ]


def dft_applicability_compatibility_rules() -> list[Dict[str, Any]]:
    """Return applicability/offload-scope compatibility rules, separate from design legality."""
    return [
        {
            "schema_version": "dse.dft.applicability_compatibility_rule.v1",
            **dict(item),
            "axis_ids": sorted({*item["when"], *item["requires"]}),
            "claim_boundary": (
                "Applicability compatibility can block an offload-scope pairing, "
                "but it does not change design_legality or stable design identity."
            ),
        }
        for item in DFT_APPLICABILITY_COMPATIBILITY_RULES
    ]


def dft_evaluation_policy_compatibility_rules() -> list[Dict[str, Any]]:
    """Return evaluation/promotion routing rules, separate from design legality and score."""
    return [
        {
            "schema_version": "dse.dft.evaluation_policy_compatibility_rule.v1",
            **dict(item),
            "axis_ids": sorted({*item["when"], *item["requires"]}),
            "claim_boundary": (
                "Evaluation policy compatibility schedules or blocks promotion evidence rows; "
                "it does not change design_legality, design_score, or stable design identity."
            ),
        }
        for item in DFT_EVALUATION_POLICY_COMPATIBILITY_RULES
    ]


def dft_seven_axis_domains() -> tuple[AxisDomain, ...]:
    return (
        AxisDomain(
            axis_id="dft_phase_hotspot_selection",
            label="DFT phase / hotspot selection",
            description="First-stage DFT workflow focus used to seed candidate generation and feedback grouping.",
            source_refs=("S01", "S03"),
            values=(
                AxisValue(
                    "scf_hpsi_density",
                    "SCF h_psi / density / mixing",
                    "SCF-dominant plane-wave phase bundle with h_psi, diagonalization, density, and mixing.",
                    ("S01", "S03"),
                    {"phase_groups": ["dense_linear_algebra", "fft_grid_density", "mixing_reduction"]},
                ),
                AxisValue(
                    "hybrid_exx_fft",
                    "Hybrid exact exchange / FFT",
                    "Hybrid-functional path with exact exchange, FFT/grid movement, and diagonalization pressure.",
                    ("S01", "S22"),
                    {"phase_groups": ["hybrid_exchange", "fft_grid_density", "dense_linear_algebra"]},
                ),
            ),
        ),
        AxisDomain(
            axis_id="algorithm_variants",
            label="Algorithm variants",
            description="Algorithmic kernel template used before any hardware binding.",
            source_refs=("S01", "S03", "S21", "S22"),
            values=(
                AxisValue(
                    "iterative_diag_fft",
                    "Iterative diagonalization + FFT",
                    "QE-like iterative eigensolver plus FFT/grid kernels.",
                    ("S01", "S03"),
                    {"phase_groups": ["diagonalization", "fft_grid_density"]},
                ),
                AxisValue(
                    "batched_gemm_exx",
                    "Batched GEMM exact-exchange",
                    "Exact-exchange/hybrid block expressed as batched dense kernels.",
                    ("S21", "S22"),
                    {"phase_groups": ["hybrid_exchange", "dense_linear_algebra"]},
                ),
            ),
        ),
        AxisDomain(
            axis_id="schedule_runtime_policy",
            label="Schedule / runtime policy",
            description="Runtime orchestration policy used by screening and feedback.",
            source_refs=("S03", "GENERIC_DSE_V2"),
            values=(
                AxisValue(
                    "host_orchestrated_sync",
                    "Host-orchestrated synchronous kernels",
                    "Conservative host-submitted accelerator kernels with explicit completion boundaries.",
                    ("S03", "GENERIC_DSE_V2"),
                    {"overlap": False, "feedback_feature": "host_submission_latency"},
                ),
                AxisValue(
                    "overlap_dma_compute",
                    "Overlap DMA and compute",
                    "Pipelined transfer/compute overlap candidate for streaming/HBM candidates.",
                    ("S15", "S19", "GENERIC_DSE_V2"),
                    {"overlap": True, "feedback_feature": "dma_compute_overlap"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="mapping_data_layout",
            label="Mapping / data layout",
            description="Generic layout/mapping template used by legality and screening.",
            source_refs=("S15", "S19", "S21"),
            values=(
                AxisValue(
                    "fft_grid_hbm_tiled",
                    "FFT/grid HBM tiling",
                    "Grid/FFT/data-density path using HBM-friendly tiles.",
                    ("S15", "S19"),
                    {"layout_group": "fft_grid_density"},
                ),
                AxisValue(
                    "band_block_systolic",
                    "Band-block systolic layout",
                    "Band/block layout for dense GEMM/eigensolver/exact-exchange candidates.",
                    ("S21", "S22"),
                    {"layout_group": "dense_linear_algebra"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="hardware_microarchitecture",
            label="Hardware / microarchitecture",
            description="Searchable hardware family binding; values map to repo architecture IDs when available.",
            source_refs=("S15", "S19", "S21", "GENERIC_DSE_V2"),
            values=(
                AxisValue(
                    "balanced_generic_systemc_v0",
                    "Balanced GenericAccel/SystemC candidate",
                    "Existing balanced-generic-systemc-v0 path with GenericAccel non-smoke evidence hooks.",
                    ("GENERIC_DSE_V2",),
                    {"architecture_id": "balanced-generic-systemc-v0", "family": "balanced_generic"},
                ),
                AxisValue(
                    "host_fpga_minimal_v0",
                    "Host + minimal FPGA candidate",
                    "Existing host-fpga-minimal-v0 path used as a small host/FPGA comparison point.",
                    ("GENERIC_DSE_V2", "S15"),
                    {"architecture_id": "host-fpga-minimal-v0", "family": "host_fpga_minimal"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="interface_descriptor_protocol",
            label="Interface / descriptor protocol",
            description="Host/accelerator interface contract used by promotion and L4 evidence checks.",
            source_refs=("GENERIC_DSE_V2",),
            values=(
                AxisValue(
                    "genericaccel_descriptor_v1",
                    "GenericAccel descriptor v1",
                    "Repo GenericAccel descriptor/request/completion path.",
                    ("GENERIC_DSE_V2",),
                    {"descriptor_schema": "generic_accel_descriptor.v1"},
                ),
                AxisValue(
                    "batched_kernel_descriptor_v1",
                    "Batched kernel descriptor v1",
                    "Descriptor variant for batched dense/hybrid-exchange kernels; still GenericAccel-compatible.",
                    ("GENERIC_DSE_V2", "S22"),
                    {"descriptor_schema": "generic_accel_batched_kernel_descriptor.v1"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="evidence_fidelity_promotion_policy",
            label="Evidence fidelity / promotion policy",
            description="Promotion ladder defining what evidence is required before stronger claims.",
            source_refs=("GENERIC_DSE_V2", "S22"),
            values=(
                AxisValue(
                    "systemc_then_gem5_non_smoke",
                    "SystemC then non-smoke gem5",
                    "Step3 generic_sim timing followed by non-smoke gem5 GenericAccel proof for promoted candidates.",
                    ("GENERIC_DSE_V2",),
                    {"requires_systemc": True, "requires_gem5_non_smoke": True, "requires_eda": False},
                ),
                AxisValue(
                    "systemc_gem5_eda_formal_ladder",
                    "SystemC + gem5 + EDA/formal ladder",
                    "Stronger release ladder that also schedules EDA/formal evidence rows.",
                    ("GENERIC_DSE_V2", "S22"),
                    {"requires_systemc": True, "requires_gem5_non_smoke": True, "requires_eda": True},
                ),
            ),
        ),
    )


def dft_domain_freeze() -> Dict[str, Any]:
    freeze = build_domain_freeze(
        dft_seven_axis_domains(),
        release_id=DFT_CODESIGN_RELEASE_ID,
        source_ledger=dft_seven_axis_source_ledger(),
        claim_boundary=(
            "frozen finite DFT-first release domain; candidate/evidence execution "
            "and closure are audited by downstream artifacts"
        ),
    )
    freeze["small_release_domain_policy"] = {
        "finite": True,
        "cited": True,
        "explicit_scope": "DFT-first seven-axis release v1, two values per axis",
        "complete_for_frozen_scope": True,
        "represents_infinite_dft_space": False,
        "claim_boundary": (
            "This small release domain is complete only for the frozen cited scope; "
            "it is not represented as the infinite DFT design space."
        ),
    }
    freeze["candidate_identity_policy"] = {
        "schema_version": "dse.dft.candidate_identity_policy.v1",
        "release_preset_axis_ids": list(DFT_RELEASE_PRESET_AXIS_IDS),
        "evaluation_record_axis_ids": list(DFT_EVALUATION_RECORD_AXIS_IDS),
        "design_identity_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "applicability_scope_axis_ids": list(DFT_APPLICABILITY_SCOPE_AXIS_IDS),
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "evidence_routing_axis_ids": list(DFT_EVIDENCE_ROUTING_AXIS_IDS),
        "candidate_identity_excludes": [
            "dft_phase_hotspot_selection",
            "workload_id",
            "workload_case_id",
            "evidence_fidelity_promotion_policy",
            "release_policy_metadata",
            "release_or_exploratory_lane",
            "retry_count",
            "tool_status",
            "claim_label",
        ],
        "candidate_row_id_boundary": (
            "candidate_id remains a unique all-axis evaluation-row key for artifact compatibility; "
            "design_candidate_id is the stable DFT design identity and excludes applicability/evaluation/release policy."
        ),
        "evidence_policy_affects_identity": False,
        "phase_hotspot_affects_identity": False,
        "candidate_id_kind": "evaluation_record_id",
        "candidate_id_authoritative_for_design": False,
        "legacy_candidate_id_authoritative_for_design": False,
        "stable_design_identity_key": "design_candidate_id",
        "claim_boundary": (
            "Evaluation/promotion policy can classify or schedule a design but does not create a new stable "
            "DFT design candidate identity; workload applicability/offload scope is tracked separately."
        ),
    }
    freeze["design_identity_audit"] = {
        "schema_version": "dse.dft.design_identity_audit_contract.v1",
        "status": "contract_declared",
        "stable_design_identity_key": "design_candidate_id",
        "evaluation_record_key": "evaluation_record_id",
        "legacy_candidate_key": "legacy_candidate_id",
        "candidate_id_kind": "evaluation_record_id",
        "candidate_id_authoritative_for_design": False,
        "legacy_candidate_id_authoritative_for_design": False,
        "phase_hotspot_affects_identity": False,
        "evidence_policy_affects_identity": False,
        "applicability_affects_design_score": False,
        "evaluation_policy_affects_design_score": False,
        "evaluation_policy_affects_design_legality": False,
        "claim_boundary": (
            "The freeze declares the vocabulary contract; the candidate-universe "
            "manifest recomputes per-row identity/score/legality predicates."
        ),
    }
    freeze["axis_partitions"] = {
        "schema_version": "dse.dft.axis_partition.v1",
        "all_axis_ids": list(DFT_SEVEN_AXIS_IDS),
        "release_preset_axis_ids": list(DFT_RELEASE_PRESET_AXIS_IDS),
        "evaluation_record_axis_ids": list(DFT_EVALUATION_RECORD_AXIS_IDS),
        "design_identity_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "applicability_scope_axis_ids": list(DFT_APPLICABILITY_SCOPE_AXIS_IDS),
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "evidence_routing_axis_ids": list(DFT_EVIDENCE_ROUTING_AXIS_IDS),
        "non_identity_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS),
        "claim_boundary": (
            "The seven-axis release preset remains an evaluation-row generator; "
            "stable design identity, applicability, and evaluation policy are separate partitions."
        ),
    }
    freeze["legality_constraints"] = dft_legality_constraints()
    freeze["applicability_compatibility_rules"] = dft_applicability_compatibility_rules()
    freeze["evaluation_policy_compatibility_rules"] = dft_evaluation_policy_compatibility_rules()
    freeze["domain_hash"] = stable_json_hash({
        key: value for key, value in freeze.items() if key != "domain_hash"
    })
    return freeze


def _rule_blockers(assignments: Mapping[str, str], rules: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    blockers: list[Dict[str, Any]] = []
    for rule in rules:
        when = rule["when"]
        requires = rule["requires"]
        if all(assignments.get(axis_id) == value_id for axis_id, value_id in when.items()) and any(
            assignments.get(axis_id) != value_id for axis_id, value_id in requires.items()
        ):
            blockers.append({
                "rule_id": str(rule.get("constraint_id") or rule.get("rule_id")),
                "when": dict(when),
                "requires": dict(requires),
                "reason": str(rule["reason"]),
            })
    return blockers


def _design_legality(assignments: Mapping[str, str]) -> Dict[str, Any]:
    blockers = _rule_blockers(assignments, DFT_LEGALITY_CONSTRAINTS)
    return {
        "schema_version": "dse.dft.design_legality.v1",
        "passed": not blockers,
        "design_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "ignored_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS),
        "blockers": blockers,
        "reasons": [str(blocker["reason"]) for blocker in blockers],
        "claim_boundary": (
            "Design legality consumes design axes only; applicability and evaluation policy "
            "cannot make a stable design candidate legal or illegal."
        ),
    }


def _legality(assignments: Mapping[str, str]) -> tuple[bool, Sequence[str]]:
    design_legality = _design_legality(assignments)
    return bool(design_legality["passed"]), list(design_legality["reasons"])


def _applicability_compatibility(assignments: Mapping[str, str]) -> Dict[str, Any]:
    applicability_assignments = {axis_id: assignments[axis_id] for axis_id in DFT_APPLICABILITY_AXIS_IDS}
    blockers = _rule_blockers(assignments, DFT_APPLICABILITY_COMPATIBILITY_RULES)
    return {
        "schema_version": "dse.dft.applicability_compatibility.v1",
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "design_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_assignments": applicability_assignments,
        "compatible": not blockers,
        "blockers": blockers,
        "reasons": [str(blocker["reason"]) for blocker in blockers],
        "affects_design_legality": False,
        "affects_design_score": False,
        "affects_candidate_binding_score": False,
        "affects_formal_pareto_identity": False,
        "claim_boundary": (
            "Applicability compatibility determines whether an offload scope is compatible "
            "with a design assignment; blockers are not design-legality failures."
        ),
    }


def _evaluation_policy_routing(assignments: Mapping[str, str]) -> Dict[str, Any]:
    evaluation_policy_assignments = {axis_id: assignments[axis_id] for axis_id in DFT_EVALUATION_POLICY_AXIS_IDS}
    blockers = _rule_blockers(assignments, DFT_EVALUATION_POLICY_COMPATIBILITY_RULES)
    policy = assignments["evidence_fidelity_promotion_policy"]
    promotion_requirements = {
        "systemc_then_gem5_non_smoke": ["systemc_timing", "gem5_non_smoke_genericaccel"],
        "systemc_gem5_eda_formal_ladder": [
            "systemc_timing",
            "gem5_non_smoke_genericaccel",
            "eda_synthesis_or_implementation",
            "formal_or_equivalence_evidence",
        ],
    }[policy]
    return {
        "schema_version": "dse.dft.evaluation_policy_routing.v1",
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "design_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "evaluation_policy_assignments": evaluation_policy_assignments,
        "promotion_requirements": promotion_requirements,
        "routing_compatible": not blockers,
        "routing_blockers": blockers,
        "evaluation_row_evidence_routable": not blockers,
        "claim_eligible": not blockers,
        "claim_eligibility_boundary": (
            "Routing compatibility is necessary for this evaluation row to pursue a claim; "
            "downstream evidence ledgers and release gates are still required."
        ),
        "affects_design_legality": False,
        "affects_design_score": False,
        "affects_candidate_binding_score": False,
        "affects_formal_pareto_identity": False,
        "claim_boundary": (
            "Evaluation policy routes required evidence and promotion work; routing blockers "
            "do not change design_legality or design_score."
        ),
    }


def _partition_assignments(assignments: Mapping[str, str], axis_ids: Sequence[str]) -> Dict[str, str]:
    return {axis_id: assignments[axis_id] for axis_id in axis_ids}


def _partition_id(prefix: str, assignments: Mapping[str, str]) -> str:
    return prefix + stable_json_hash({"assignments": dict(sorted(assignments.items()))})[:16]


def _build_design_identity_audit(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    identity_groups: Dict[str, list[Mapping[str, Any]]] = {}
    for candidate in manifest.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        key = stable_json_hash({"identity_assignments": candidate.get("identity_assignments", {})})
        identity_groups.setdefault(key, []).append(candidate)

    same_design_id = True
    same_design_score = True
    same_design_legality = True
    all_rows_labeled = True
    for rows in identity_groups.values():
        if len({str(row.get("design_candidate_id")) for row in rows}) != 1:
            same_design_id = False
        if len({json.dumps(row.get("design_score"), sort_keys=True) for row in rows}) != 1:
            same_design_score = False
        if len({json.dumps(row.get("design_legality"), sort_keys=True) for row in rows}) != 1:
            same_design_legality = False
        if any(
            row.get("candidate_id_kind") != "evaluation_record_id"
            or row.get("candidate_id_authoritative_for_design") is not False
            or row.get("evaluation_record_id") != row.get("candidate_id")
            or row.get("legacy_candidate_id") != row.get("candidate_id")
            for row in rows
        ):
            all_rows_labeled = False

    return {
        "schema_version": "dse.dft.design_identity_audit.v1",
        "status": "passed"
        if same_design_id and same_design_score and same_design_legality and all_rows_labeled
        else "failed",
        "stable_design_identity_key": "design_candidate_id",
        "evaluation_record_key": "evaluation_record_id",
        "legacy_candidate_key": "legacy_candidate_id",
        "identity_group_count": len(identity_groups),
        "all_same_identity_axis_rows_share_design_candidate_id": same_design_id,
        "all_same_identity_axis_rows_share_design_score": same_design_score,
        "all_same_identity_axis_rows_share_design_legality": same_design_legality,
        "all_candidate_rows_label_evaluation_record_identity": all_rows_labeled,
        "candidate_id_kind": "evaluation_record_id",
        "candidate_id_authoritative_for_design": False,
        "legacy_candidate_id_authoritative_for_design": False,
        "phase_hotspot_affects_identity": False,
        "evidence_policy_affects_identity": False,
        "applicability_affects_design_score": False,
        "evaluation_policy_affects_design_score": False,
        "evaluation_policy_affects_design_legality": False,
        "claim_boundary": (
            "Computed from generated candidates: all rows that share stable design axes "
            "must share design identity, score, and design legality despite applicability "
            "or evidence-routing differences."
        ),
    }


def _enrich_candidate_partitions(manifest: Dict[str, Any], legality: Dict[str, Any]) -> None:
    """Add DFT-specific applicability/evaluation partitions without changing generic core."""
    for candidate in manifest.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        assignments = candidate["assignments"]
        applicability_assignments = _partition_assignments(assignments, DFT_APPLICABILITY_AXIS_IDS)
        evaluation_policy_assignments = _partition_assignments(assignments, DFT_EVALUATION_POLICY_AXIS_IDS)
        design_legality = _design_legality(assignments)
        screening = dict(candidate.get("screening") or {})
        candidate.update({
            "evaluation_record_id": candidate.get("candidate_id"),
            "legacy_candidate_id": candidate.get("candidate_id"),
            "candidate_id_authoritative_for_design": False,
            "design_candidate_id_authoritative_for_design": True,
            "design_legality": design_legality,
            "design_score": screening.get("design_score", screening.get("score")),
            "applicability_assignments": applicability_assignments,
            "evaluation_policy_assignments": evaluation_policy_assignments,
            "applicability_scope_id": _partition_id("appscope_", applicability_assignments),
            "evaluation_policy_id": _partition_id("evalpol_", evaluation_policy_assignments),
            "applicability_compatibility": _applicability_compatibility(assignments),
            "evaluation_policy_routing": _evaluation_policy_routing(assignments),
        })
        candidate["promotion_requirements"] = candidate["evaluation_policy_routing"]["promotion_requirements"]
        candidate["provenance"]["applicability_axis_ids"] = list(DFT_APPLICABILITY_AXIS_IDS)
        candidate["provenance"]["evaluation_policy_axis_ids"] = list(DFT_EVALUATION_POLICY_AXIS_IDS)
        candidate["provenance"]["phase_hotspot_affects_identity"] = False
        candidate["provenance"]["candidate_id_authoritative_for_design"] = False

    for row in legality.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        assignments = row["assignments"]
        applicability_assignments = _partition_assignments(assignments, DFT_APPLICABILITY_AXIS_IDS)
        evaluation_policy_assignments = _partition_assignments(assignments, DFT_EVALUATION_POLICY_AXIS_IDS)
        row.update({
            "evaluation_record_id": row.get("candidate_id"),
            "legacy_candidate_id": row.get("candidate_id"),
            "candidate_id_authoritative_for_design": False,
            "design_candidate_id_authoritative_for_design": True,
            "design_legality": _design_legality(assignments),
            "applicability_assignments": applicability_assignments,
            "evaluation_policy_assignments": evaluation_policy_assignments,
            "applicability_scope_id": _partition_id("appscope_", applicability_assignments),
            "evaluation_policy_id": _partition_id("evalpol_", evaluation_policy_assignments),
            "applicability_compatibility": _applicability_compatibility(assignments),
            "evaluation_policy_routing": _evaluation_policy_routing(assignments),
        })
        row["promotion_requirements"] = row["evaluation_policy_routing"]["promotion_requirements"]
        row["provenance"]["applicability_axis_ids"] = list(DFT_APPLICABILITY_AXIS_IDS)
        row["provenance"]["evaluation_policy_axis_ids"] = list(DFT_EVALUATION_POLICY_AXIS_IDS)
        row["provenance"]["phase_hotspot_affects_identity"] = False
        row["provenance"]["candidate_id_authoritative_for_design"] = False

    manifest["applicability_axis_ids"] = list(DFT_APPLICABILITY_AXIS_IDS)
    manifest["evaluation_policy_axis_ids"] = list(DFT_EVALUATION_POLICY_AXIS_IDS)
    manifest["candidate_id_provenance"]["applicability_axis_ids"] = list(DFT_APPLICABILITY_AXIS_IDS)
    manifest["candidate_id_provenance"]["evaluation_policy_axis_ids"] = list(DFT_EVALUATION_POLICY_AXIS_IDS)
    manifest["candidate_id_provenance"]["phase_hotspot_affects_identity"] = False
    manifest["candidate_id_provenance"]["candidate_id_authoritative_for_design"] = False
    manifest["candidate_id_provenance"]["legacy_candidate_id_authoritative_for_design"] = False
    manifest["candidate_id_provenance"]["evaluation_record_key"] = "evaluation_record_id"
    manifest["candidate_id_provenance"]["stable_design_identity_key"] = "design_candidate_id"
    manifest["legal_evaluation_record_ids"] = list(manifest.get("legal_candidate_ids", []) or [])
    manifest["legal_candidate_ids_kind"] = "evaluation_record_id"
    manifest["legal_candidate_ids_authoritative_for_design"] = False
    manifest["design_identity_audit"] = _build_design_identity_audit(manifest)
    manifest["axis_partitions"] = {
        "release_preset_axis_ids": list(DFT_RELEASE_PRESET_AXIS_IDS),
        "evaluation_record_axis_ids": list(DFT_EVALUATION_RECORD_AXIS_IDS),
        "design_identity_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "applicability_scope_axis_ids": list(DFT_APPLICABILITY_SCOPE_AXIS_IDS),
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "evidence_routing_axis_ids": list(DFT_EVIDENCE_ROUTING_AXIS_IDS),
    }
    manifest["universe_hash"] = stable_json_hash({
        key: value for key, value in manifest.items() if key != "universe_hash"
    })
    legality["universe_hash"] = manifest["universe_hash"]
    legality["axis_partitions"] = manifest["axis_partitions"]
    legality["legality_semantics"] = {
        "legal_field": "design_legality.passed",
        "applicability_compatibility_affects_legal": False,
        "evaluation_policy_routing_affects_legal": False,
    }
    legality["legality_hash"] = stable_json_hash({
        key: value for key, value in legality.items() if key != "legality_hash"
    })


def _screen(assignments: Mapping[str, str]) -> Dict[str, Any]:
    axis_terms = {axis_id: 1.0 for axis_id in DFT_DESIGN_AXIS_IDS}
    if assignments["schedule_runtime_policy"] == "overlap_dma_compute":
        axis_terms["schedule_runtime_policy"] = 0.85
    if assignments["hardware_microarchitecture"] == "balanced_generic_systemc_v0":
        axis_terms["hardware_microarchitecture"] = 0.95
    design_score = round(sum(axis_terms.values()), 6)
    return {
        "score_model": "deterministic_design_axis_weighted_screen_v2",
        "axis_terms": axis_terms,
        "design_axis_terms": axis_terms,
        "score": design_score,
        "design_score": design_score,
        "all_axes_used": False,
        "all_design_axes_used": sorted(axis_terms) == sorted(DFT_DESIGN_AXIS_IDS),
        "ignored_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS + DFT_EVALUATION_POLICY_AXIS_IDS),
        "applicability_affects_design_score": False,
        "evaluation_policy_affects_design_score": False,
        "trusted_final_claim": False,
    }


def dft_candidate_universe() -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    freeze = dft_domain_freeze()
    manifest, legality = build_candidate_universe(
        freeze,
        legality_fn=_legality,
        score_fn=_screen,
        identity_axis_ids=DFT_DESIGN_AXIS_IDS,
    )
    _enrich_candidate_partitions(manifest, legality)
    return freeze, manifest, legality


def build_search_space_report(
    freeze: Mapping[str, Any],
    manifest: Mapping[str, Any],
    legality: Mapping[str, Any],
    *,
    timing_evidence_summary: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    axes = axis_value_ids(freeze)
    legal_candidates = [
        candidate for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True
    ]
    timing_summary = dict(timing_evidence_summary or {})
    feedback_axis_updates = {
        axis_id: {
            "status": "updated_from_non_smoke_timing_evidence" if timing_summary else "ready_for_timing_feedback",
            "value_count": len(values),
            "values": values,
        }
        for axis_id, values in axes.items()
    }
    promoted = [
        {
            "candidate_id": candidate["candidate_id"],
            "evaluation_record_id": candidate.get("evaluation_record_id", candidate["candidate_id"]),
            "legacy_candidate_id": candidate.get("legacy_candidate_id", candidate["candidate_id"]),
            "candidate_id_kind": candidate.get("candidate_id_kind"),
            "candidate_id_authoritative_for_design": False,
            "design_candidate_id": candidate.get("design_candidate_id"),
            "design_candidate_id_authoritative_for_design": True,
            "assignments": candidate["assignments"],
            "identity_assignments": candidate.get("identity_assignments"),
            "non_identity_assignments": candidate.get("non_identity_assignments"),
            "applicability_assignments": candidate.get("applicability_assignments"),
            "evaluation_policy_assignments": candidate.get("evaluation_policy_assignments"),
            "promotion_target": "non_smoke_systemc_gem5_timing",
            "promotion_reason": "legal candidate in frozen seven-axis release domain",
            "all_axes_used": sorted(candidate["assignments"]) == sorted(DFT_SEVEN_AXIS_IDS),
            "stable_design_identity_excludes_evidence_policy": (
                "evidence_fidelity_promotion_policy" not in (candidate.get("identity_assignments") or {})
            ),
            "stable_design_identity_excludes_applicability": (
                "dft_phase_hotspot_selection" not in (candidate.get("identity_assignments") or {})
            ),
            "design_legality": candidate.get("design_legality"),
            "design_score": candidate.get("design_score"),
            "applicability_scope_id": candidate.get("applicability_scope_id"),
            "evaluation_policy_id": candidate.get("evaluation_policy_id"),
            "applicability_compatibility": candidate.get("applicability_compatibility"),
            "evaluation_policy_routing": candidate.get("evaluation_policy_routing"),
            "promotion_requirements": candidate.get("promotion_requirements"),
            "timing_evidence_status": "pending_or_external_sample",
        }
        for candidate in legal_candidates
    ]
    promoted_candidate_ids = [item["candidate_id"] for item in promoted]
    report = {
        "schema_version": "dse.dft.seven_axis_search_space_report.v1",
        "status": "passed" if legal_candidates else "failed",
        "release_id": freeze.get("release_id"),
        "domain_hash": freeze.get("domain_hash"),
        "universe_hash": manifest.get("universe_hash"),
        "legality_hash": legality.get("legality_hash"),
        "axis_ids": list(DFT_SEVEN_AXIS_IDS),
        "design_identity_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "axis_partitions": dict(freeze.get("axis_partitions") or {}),
        "candidate_identity_policy": dict(freeze.get("candidate_identity_policy") or {}),
        "axis_usage": {
            axis_id: {
                "candidate_generation": True,
                "design_legality": axis_id in DFT_DESIGN_AXIS_IDS,
                "screening": axis_id in DFT_DESIGN_AXIS_IDS,
                "applicability_compatibility": axis_id in DFT_APPLICABILITY_AXIS_IDS,
                "evaluation_policy_routing": axis_id in DFT_EVALUATION_POLICY_AXIS_IDS,
                "non_smoke_timing_promotion": True,
                "feedback": True,
                "values": values,
            }
            for axis_id, values in axes.items()
        },
        "candidate_generation": {
            "cartesian_count": manifest.get("cartesian_count"),
            "legal_candidate_count": manifest.get("legal_candidate_count"),
            "unique_design_candidate_count": manifest.get("unique_design_candidate_count"),
            "legal_design_candidate_count": manifest.get("legal_design_candidate_count"),
            "all_candidates_have_all_axes": all(
                sorted(candidate.get("assignments", {})) == sorted(DFT_SEVEN_AXIS_IDS)
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
            "all_design_identities_exclude_evaluation_policy": all(
                "evidence_fidelity_promotion_policy" not in (candidate.get("identity_assignments") or {})
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
            "all_design_identities_exclude_applicability": all(
                "dft_phase_hotspot_selection" not in (candidate.get("identity_assignments") or {})
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
            "all_candidates_have_applicability_assignments": all(
                sorted(candidate.get("applicability_assignments", {})) == sorted(DFT_APPLICABILITY_AXIS_IDS)
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
            "all_candidates_have_evaluation_policy_assignments": all(
                sorted(candidate.get("evaluation_policy_assignments", {})) == sorted(DFT_EVALUATION_POLICY_AXIS_IDS)
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
        },
        "cardinality_cost_estimator": {
            "stage": "before_full_evidence_execution",
            "cartesian_candidate_count": manifest.get("cartesian_count"),
            "legal_candidate_count": manifest.get("legal_candidate_count"),
            "illegal_candidate_count": manifest.get("illegal_candidate_count"),
            "required_hard_evidence_classes": 9,
            "estimated_candidate_evidence_rows": int(manifest.get("legal_candidate_count") or 0),
            "estimated_hard_evidence_slots": int(manifest.get("legal_candidate_count") or 0) * 9,
            "claim_boundary": (
                "Cardinality/cost estimates may size and order the run before "
                "full evidence execution; they are not completion evidence."
            ),
        },
        "screening": {
            "all_legal_candidates_have_axis_terms": all(
                sorted((candidate.get("screening", {}).get("axis_terms") or {}).keys()) == sorted(DFT_DESIGN_AXIS_IDS)
                for candidate in legal_candidates
            ),
            "design_scoring_ignores_applicability_and_evaluation_policy": all(
                not set(candidate.get("screening", {}).get("axis_terms") or {}).intersection(
                    {*DFT_APPLICABILITY_AXIS_IDS, *DFT_EVALUATION_POLICY_AXIS_IDS}
                )
                for candidate in legal_candidates
            ),
            "priority_queue_policy": {
                "top_k_or_representative_subset_allowed_for_execution_order": True,
                "completion_requires_all_legal_candidates": True,
                "subset_satisfies_release_completion": False,
                "claim_boundary": (
                    "Screening scores may prioritize expensive evidence execution, "
                    "but top-K or representative-only evidence cannot replace "
                    "all-candidate evidence closure for the frozen release domain."
                ),
            },
        },
        "promotion_queue": promoted,
        "universe_backed_queue": {
            "queue_mode": "all_legal_candidates",
            "source": "candidate_universe_manifest.legal_evaluation_record_ids",
            "entry_count": len(promoted_candidate_ids),
            "candidate_ids": promoted_candidate_ids,
            "candidate_ids_kind": "evaluation_record_id",
            "candidate_ids_authoritative_for_design": False,
            "evaluation_record_ids": promoted_candidate_ids,
            "all_legal_candidates_once": promoted_candidate_ids == list(manifest.get("legal_candidate_ids", []) or [])
            and len(promoted_candidate_ids) == len(set(promoted_candidate_ids)),
            "legal_design_candidate_ids": list(manifest.get("legal_design_candidate_ids", []) or []),
            "claim_boundary": (
                "Queue covers each legal frozen-domain candidate exactly once; "
                "downstream evidence status still controls completion claims."
            ),
        },
        "feedback_trace": {
            "schema_version": "dse.dft.closed_loop_feedback_trace.v1",
            "status": "passed" if timing_summary else "ready",
            "source": "existing_non_smoke_timing_sample" if timing_summary else "domain_ready_no_timing_sample",
            "timing_evidence_summary": timing_summary,
            "axis_updates": feedback_axis_updates,
            "all_axes_updated_or_ready": sorted(feedback_axis_updates) == sorted(DFT_SEVEN_AXIS_IDS),
        },
        "claim_boundary": (
            "Seven-axis release-domain/search-space contract. This is not a claim "
            "that every legal candidate already has all downstream evidence rows closed."
        ),
    }
    report["search_space_hash"] = stable_json_hash({
        key: value for key, value in report.items() if key != "search_space_hash"
    })
    return report


def timing_summary_from_dft_run(run_dir: Path) -> Dict[str, Any]:
    summary_path = run_dir / "dft_end_to_end_summary.json"
    if not summary_path.exists():
        return {}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    step4 = summary.get("step4_gem5") if isinstance(summary, Mapping) else {}
    if not isinstance(step4, Mapping):
        step4 = {}
    best = summary.get("best_architecture") if isinstance(summary, Mapping) else {}
    if not isinstance(best, Mapping):
        best = {}
    return {
        "run_dir": str(run_dir),
        "summary": str(summary_path),
        "status": summary.get("status"),
        "best_architecture": best,
        "step4_architecture_id": step4.get("architecture_id"),
        "step4_trusted_timing": step4.get("trusted_step4_timing"),
        "step4_activity_artifact": step4.get("activity_artifact"),
        "step4_attempted": step4.get("attempted"),
    }


def write_dft_seven_axis_artifacts(out_dir: Path, *, timing_run_dir: Path | None = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    freeze, manifest, legality = dft_candidate_universe()
    timing = timing_summary_from_dft_run(timing_run_dir) if timing_run_dir else {}
    report = build_search_space_report(freeze, manifest, legality, timing_evidence_summary=timing)
    hierarchical_funnel = build_dft_hierarchical_funnel_search_report()
    artifacts = {
        "seven_axis_domain_freeze": out_dir / "seven_axis_domain_freeze.json",
        "candidate_universe_manifest": out_dir / "candidate_universe_manifest.json",
        "candidate_legality_report": out_dir / "candidate_legality_report.json",
        "seven_axis_search_space_report": out_dir / "seven_axis_search_space_report.json",
        "closed_loop_feedback_trace": out_dir / "closed_loop_feedback_trace.json",
        "hierarchical_funnel_search_report": out_dir / "hierarchical_funnel_search_report.json",
    }
    # Preserve insertion order in artifact JSON so human review sees every
    # candidate assignment in the frozen axis order.  Hashes remain stable
    # because stable_json_hash() canonicalizes separately for digesting.
    artifacts["seven_axis_domain_freeze"].write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    artifacts["candidate_universe_manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    artifacts["candidate_legality_report"].write_text(json.dumps(legality, indent=2) + "\n", encoding="utf-8")
    artifacts["seven_axis_search_space_report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    artifacts["closed_loop_feedback_trace"].write_text(json.dumps(report["feedback_trace"], indent=2) + "\n", encoding="utf-8")
    artifacts["hierarchical_funnel_search_report"].write_text(
        json.dumps(hierarchical_funnel, indent=2) + "\n",
        encoding="utf-8",
    )
    status = {
        "schema_version": "dse.dft.seven_axis_artifact_status.v1",
        "status": "passed" if report["status"] == "passed" and hierarchical_funnel["status"] == "passed" else "failed",
        "artifacts": {key: str(path) for key, path in artifacts.items()},
        "domain_hash": freeze["domain_hash"],
        "universe_hash": manifest["universe_hash"],
        "legality_hash": legality["legality_hash"],
        "search_space_hash": report["search_space_hash"],
        "hierarchical_funnel_status": hierarchical_funnel["status"],
        "axis_ids": list(DFT_SEVEN_AXIS_IDS),
        "design_identity_axis_ids": list(DFT_DESIGN_AXIS_IDS),
        "applicability_axis_ids": list(DFT_APPLICABILITY_AXIS_IDS),
        "evaluation_policy_axis_ids": list(DFT_EVALUATION_POLICY_AXIS_IDS),
        "legal_candidate_count": manifest["legal_candidate_count"],
        "legal_design_candidate_count": manifest["legal_design_candidate_count"],
        "claim_boundary": report["claim_boundary"],
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status
