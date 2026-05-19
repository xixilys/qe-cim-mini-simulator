#!/usr/bin/env python3
"""Complete-DSE offload-target identity tests."""

from __future__ import annotations

import copy

import pytest

from dse_v2.codesign.qe_callgraph_offload_search import (
    OFFLOAD_IDENTITY_LAYER_KEYS,
    OFFLOAD_TARGET_LAYER,
    WORKLOAD_VARIANT_BINDING_SCHEMA,
    build_offload_candidate_record,
    canonical_offload_candidate_identity,
    complete_dse_offload_candidate_id,
    example_offload_identity_layers,
)


def _layers():
    return copy.deepcopy(example_offload_identity_layers())


def test_offload_identity_adds_sixth_design_layer():
    layers = _layers()
    identity = canonical_offload_candidate_identity(layers)

    assert tuple(identity["identity_layers"]) == OFFLOAD_IDENTITY_LAYER_KEYS
    assert identity["identity_layer_order"] == list(OFFLOAD_IDENTITY_LAYER_KEYS)
    assert OFFLOAD_TARGET_LAYER in identity["identity_layers"]
    assert identity["claim_boundary"] == "offload target identity only; not L4 value evidence"
    assert complete_dse_offload_candidate_id(layers).startswith("cdse_offload_")


def test_offload_target_changes_affect_candidate_id():
    layers = _layers()

    bundle_changed = copy.deepcopy(layers)
    bundle_changed[OFFLOAD_TARGET_LAYER]["bundle_id"] = "bundle_other"

    opportunity_changed = copy.deepcopy(layers)
    opportunity_changed[OFFLOAD_TARGET_LAYER]["opportunity_ids"] = [
        "opp_qe_si_relax_forces_v1_forces"
    ]

    assert complete_dse_offload_candidate_id(bundle_changed) != complete_dse_offload_candidate_id(layers)
    assert complete_dse_offload_candidate_id(opportunity_changed) != complete_dse_offload_candidate_id(layers)


def test_evaluation_context_does_not_affect_offload_candidate_id():
    layers = _layers()
    first = build_offload_candidate_record(
        layers,
        evaluation_context={
            "workload_case_id": "qe_si_scf_small_v1",
            "evidence_tier": "L3",
            "queue_order": 1,
            "blocker_status": "none",
        },
    )
    second = build_offload_candidate_record(
        layers,
        evaluation_context={
            "workload_case_id": "qe_si_relax_forces_v1",
            "evidence_tier": "L4",
            "queue_order": 99,
            "blocker_status": "blocked_gem5",
        },
    )

    assert first["candidate_id"] == second["candidate_id"]
    assert first["identity_hash"] == second["identity_hash"]
    assert first["record_hash"] != second["record_hash"]
    provenance = first["candidate_id_provenance"]
    assert provenance["offload_target_affects_identity"] is True
    assert provenance["formal_workload_variant_binding_affects_identity"] is True
    assert provenance["workload_affects_identity"] is False
    assert provenance["evidence_fidelity_affects_identity"] is False
    assert provenance["queue_order_affects_identity"] is False
    assert provenance["blocker_status_affects_identity"] is False


def test_missing_or_contaminated_offload_identity_is_rejected():
    layers = _layers()

    missing = copy.deepcopy(layers)
    missing.pop(OFFLOAD_TARGET_LAYER)
    with pytest.raises(ValueError, match="missing offload candidate identity layers"):
        complete_dse_offload_candidate_id(missing)

    top_level_context = copy.deepcopy(layers)
    top_level_context["workload_case_id"] = "qe_si_scf_small_v1"
    with pytest.raises(ValueError, match="non-identity fields"):
        complete_dse_offload_candidate_id(top_level_context)

    nested_context = copy.deepcopy(layers)
    nested_context[OFFLOAD_TARGET_LAYER]["workload_case_ids"] = [
        "qe_si_scf_small_v1"
    ]
    with pytest.raises(
        ValueError, match=r"offload_target_parameters\.workload_case_ids"
    ):
        complete_dse_offload_candidate_id(nested_context)

    nested_evidence = copy.deepcopy(layers)
    nested_evidence["algorithm_parameters"]["evidence_kind"] = "profile_only"
    with pytest.raises(
        ValueError, match=r"algorithm_parameters\.evidence_kind"
    ):
        complete_dse_offload_candidate_id(nested_evidence)


def test_formal_workload_variant_binding_changes_offload_candidate_id():
    layers = _layers()
    uspp_layers = copy.deepcopy(layers)
    uspp_layers[OFFLOAD_TARGET_LAYER]["workload_variant_binding"] = {
        "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
        "workload_variant_id": "qe_si_uspp_spsi_probe_v1",
        "formal_status": "formal_workload_variant_candidate",
        "pseudopotential_family": "uspp",
        "target_kernel": "s_psi",
    }

    paw_layers = copy.deepcopy(uspp_layers)
    paw_layers[OFFLOAD_TARGET_LAYER]["workload_variant_binding"] = {
        **paw_layers[OFFLOAD_TARGET_LAYER]["workload_variant_binding"],
        "workload_variant_id": "qe_si_paw_spsi_probe_v1",
        "pseudopotential_family": "paw",
    }

    assert complete_dse_offload_candidate_id(uspp_layers) != complete_dse_offload_candidate_id(layers)
    assert complete_dse_offload_candidate_id(paw_layers) != complete_dse_offload_candidate_id(uspp_layers)


def test_workload_variant_binding_rejects_non_identity_workload_case_id():
    layers = _layers()
    layers[OFFLOAD_TARGET_LAYER]["workload_variant_binding"] = {
        "schema_version": WORKLOAD_VARIANT_BINDING_SCHEMA,
        "workload_variant_id": "qe_si_uspp_spsi_probe_v1",
        "formal_status": "formal_workload_variant_candidate",
        "pseudopotential_family": "uspp",
        "target_kernel": "s_psi",
        "workload_case_id": "qe_si_scf_small_v1",
    }

    with pytest.raises(
        ValueError,
        match=r"offload_target_parameters\.workload_variant_binding\.workload_case_id",
    ):
        complete_dse_offload_candidate_id(layers)
