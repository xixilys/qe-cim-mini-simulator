#!/usr/bin/env python3
"""Complete-DSE candidate identity tests."""

from __future__ import annotations

import copy

import pytest

from dse_v2.codesign.complete_dse_search_space import (
    IDENTITY_LAYER_KEYS,
    NON_IDENTITY_FIELDS,
    build_candidate_record,
    build_release_subset_manifest,
    canonical_candidate_identity,
    complete_dse_candidate_id,
)
from dse_v2.reference_workloads.dft_codesign_domain import (
    DFT_APPLICABILITY_AXIS_IDS,
    DFT_DESIGN_AXIS_IDS,
    DFT_EVALUATION_POLICY_AXIS_IDS,
    dft_candidate_universe,
)


def _first_identity_layers():
    manifest = build_release_subset_manifest()
    return copy.deepcopy(
        manifest["candidates"][0]["identity"]["identity_layers"]
    )


def test_candidate_identity_contains_exactly_five_design_only_layers():
    layers = _first_identity_layers()
    identity = canonical_candidate_identity(layers)

    assert tuple(identity["identity_layers"]) == IDENTITY_LAYER_KEYS
    assert identity["excluded_fields"] == list(NON_IDENTITY_FIELDS)
    assert identity["candidate_id_rule"].startswith("cdse_ + sha256")
    assert complete_dse_candidate_id(layers).startswith("cdse_")


def test_candidate_id_is_deterministic_and_order_insensitive_inside_layers():
    layers = _first_identity_layers()
    reversed_layer_keys = {
        layer: {
            key: layers[layer][key]
            for key in reversed(list(layers[layer].keys()))
        }
        for layer in reversed(list(layers.keys()))
    }

    assert complete_dse_candidate_id(layers) == complete_dse_candidate_id(
        reversed_layer_keys
    )
    assert (
        canonical_candidate_identity(reversed_layer_keys)["identity_layers"]
        == canonical_candidate_identity(layers)["identity_layers"]
    )


def test_compile_and_runtime_schedule_changes_affect_candidate_id():
    layers = _first_identity_layers()
    compile_changed = copy.deepcopy(layers)
    compile_changed["compile_time_schedule_parameters"][
        "tiling"
    ] = "different_tile"
    runtime_changed = copy.deepcopy(layers)
    runtime_changed["runtime_scheduling_parameters"][
        "queue_policy"
    ] = "different_queue"

    assert complete_dse_candidate_id(
        compile_changed
    ) != complete_dse_candidate_id(layers)
    assert complete_dse_candidate_id(
        runtime_changed
    ) != complete_dse_candidate_id(layers)


def test_evaluation_context_does_not_affect_candidate_id():
    layers = _first_identity_layers()
    baseline = build_candidate_record(
        layers,
        evaluation_context={
            "workload_case_id": "qe_scf_small",
            "evidence_tier": "L3",
            "promotion_policy": "top_k_for_execution_order_only",
            "tool_status": "available",
            "blocker_status": "none",
            "retry_count": 0,
        },
    )
    changed = build_candidate_record(
        layers,
        evaluation_context={
            "workload_case_id": "qe_nscf_small",
            "evidence_tier": "L4",
            "promotion_policy": "all_legal_candidates",
            "tool_status": "missing_gem5",
            "blocker_status": "blocked",
            "retry_count": 9,
        },
    )

    assert baseline["candidate_id"] == changed["candidate_id"]
    assert baseline["identity_hash"] == changed["identity_hash"]
    assert baseline["record_hash"] != changed["record_hash"]
    provenance = baseline["candidate_id_provenance"]
    assert provenance["workload_affects_identity"] is False
    assert provenance["evidence_fidelity_affects_identity"] is False
    assert provenance["promotion_policy_affects_identity"] is False
    assert provenance["tool_status_affects_identity"] is False


def test_dft_applicability_and_evaluation_partitions_do_not_affect_design_candidate_id():
    _, manifest, _ = dft_candidate_universe()

    assert "dft_phase_hotspot_selection" not in DFT_DESIGN_AXIS_IDS
    assert "evidence_fidelity_promotion_policy" not in DFT_DESIGN_AXIS_IDS
    assert manifest["applicability_axis_ids"] == list(DFT_APPLICABILITY_AXIS_IDS)
    assert manifest["evaluation_policy_axis_ids"] == list(DFT_EVALUATION_POLICY_AXIS_IDS)

    by_identity: dict[str, list[dict]] = {}
    for candidate in manifest["candidates"]:
        key = str(sorted(candidate["identity_assignments"].items()))
        by_identity.setdefault(key, []).append(candidate)

    rows = next(group for group in by_identity.values() if len(group) == 4)
    assert len({row["design_candidate_id"] for row in rows}) == 1
    assert len({row["applicability_scope_id"] for row in rows}) == 2
    assert len({row["evaluation_policy_id"] for row in rows}) == 2
    assert all("dft_phase_hotspot_selection" not in row["identity_assignments"] for row in rows)
    assert all("evidence_fidelity_promotion_policy" not in row["identity_assignments"] for row in rows)


def test_missing_or_contaminated_identity_layers_block_stable_id_emission():
    layers = _first_identity_layers()
    missing = copy.deepcopy(layers)
    missing.pop("runtime_scheduling_parameters")
    with pytest.raises(ValueError, match="missing candidate identity layers"):
        complete_dse_candidate_id(missing)

    contaminated = copy.deepcopy(layers)
    contaminated["workload_case_id"] = {"id": "qe_scf_small"}
    with pytest.raises(ValueError, match="non-identity fields"):
        complete_dse_candidate_id(contaminated)

    nested_workload = copy.deepcopy(layers)
    nested_workload["architecture_parameters"][
        "workload_case_id"
    ] = "qe_relax_small"
    with pytest.raises(ValueError, match="architecture_parameters.workload_case_id"):
        complete_dse_candidate_id(nested_workload)

    nested_evidence = copy.deepcopy(layers)
    nested_evidence["runtime_scheduling_parameters"][
        "evidence_fidelity"
    ] = "L4"
    with pytest.raises(ValueError, match="runtime_scheduling_parameters.evidence_fidelity"):
        complete_dse_candidate_id(nested_evidence)

    unknown_axis = copy.deepcopy(layers)
    unknown_axis["manual_legality_axis"] = {"status": "force_legal"}
    with pytest.raises(ValueError, match="unknown candidate identity layers"):
        complete_dse_candidate_id(unknown_axis)
