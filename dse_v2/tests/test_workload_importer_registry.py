#!/usr/bin/env python3
"""Regression coverage for workload importer/profile registry isolation."""

from __future__ import annotations

import json

from dse_v2.core.workload import (
    GenericJsonImporter,
    create_dynamic_custom_graph,
    create_graph_analytics_graph,
    create_sparse_spmv_graph,
    create_stencil_streaming_graph,
    create_tensor_chain_graph,
    create_vector_search_graph,
    default_importer_registry,
    default_profile_registry,
)
from dse_v2.reference_workloads.dft_qe import (
    QE_SCF_REQUIRED_COVERAGE,
    create_qe_reference_package,
)


NON_QE_BUILDERS = {
    "ml_tensor": create_tensor_chain_graph,
    "sparse_la": create_sparse_spmv_graph,
    "stencil_streaming": create_stencil_streaming_graph,
    "graph_analytics": create_graph_analytics_graph,
    "database_vector_search": create_vector_search_graph,
    "dynamic_custom": lambda graph_id: create_dynamic_custom_graph(graph_id, supported=True),
}

QE_ONLY_TOKENS = {"npw", "nkb", "h_psi", "s_psi", "diagonalize", "mix_rho", "veff"}


def test_generic_importer_emits_non_qe_package_without_qe_fields():
    registry = default_importer_registry()
    profile = default_profile_registry().get("ml_tensor")
    graph = create_tensor_chain_graph("tensor_chain")
    package = registry.import_workload(
        "generic_json",
        graph,
        profile=profile,
        parameters={"workload_family": "ml_tensor", "workload_id": "tensor_chain_pkg"},
    )

    payload = package.to_dict()
    assert package.validate()["valid"] is True
    assert payload["importer"]["importer_id"] == "generic_json"
    assert payload["workload_family"] == "ml_tensor"
    assert "npw" not in payload["domain_metadata"]
    assert set(payload["graph"]["nodes"]) == {"input", "linear", "activation"}
    assert "h_psi" not in payload["graph"]["nodes"]


def test_generic_importer_accepts_representative_broad_workload_families_without_qe_leakage():
    registry = default_importer_registry()
    profiles = default_profile_registry()

    for family, build_graph in NON_QE_BUILDERS.items():
        graph = build_graph(f"{family}_importer_pkg")
        package = registry.import_workload(
            "generic_json",
            graph,
            profile=profiles.get(family),
            parameters={"workload_family": family, "workload_id": f"{family}_pkg"},
        )
        payload = package.to_dict()
        payload_text = json.dumps(payload)

        assert package.validate()["valid"] is True, family
        assert package.importer_id == "generic_json", family
        assert package.workload_family == family, family
        assert payload["workflow"]["workload_family"] == family, family
        assert payload["workflow"]["domain_validation"]["correctness_claim_requires_profile_evidence"] is True, family
        assert payload["profile"].get("required_coverage", []) == [], family
        assert QE_ONLY_TOKENS.isdisjoint(set(package.required_coverage()["required_coverage"])), family
        assert all(token not in payload_text for token in QE_ONLY_TOKENS), family


def test_qe_reference_importer_keeps_qe_metadata_profile_owned():
    package = create_qe_reference_package({"npw": 128, "nkb": 16, "m": 8, "nfft": 1024})
    validation = package.validate()
    payload = package.to_dict()

    assert validation["valid"] is True
    assert payload["profile"]["profile_id"] == "qe_scf_reference"
    assert payload["importer"]["importer_id"] == "qe_reference_fixture"
    assert payload["workload_family"] == "dft_qe_reference"
    assert payload["domain_metadata"]["npw"] == 128
    assert "npw" not in payload["graph"]
    assert payload["profile"]["required_coverage"] == QE_SCF_REQUIRED_COVERAGE
    assert "diagonalize" in payload["graph"]["nodes"]


def test_registry_can_add_new_importer_without_core_schema_changes():
    class ToySparseImporter(GenericJsonImporter):
        importer_id = "toy_sparse"
        importer_version = "v1"

    registry = default_importer_registry().register(ToySparseImporter())
    profile = default_profile_registry().get("sparse_la")
    graph = create_tensor_chain_graph("sparse_like")
    graph.nodes["linear"].op_type = "spmv"
    package = registry.import_workload(
        "toy_sparse",
        graph,
        profile=profile,
        parameters={"workload_family": "sparse_la", "claim_boundary": "full_workload"},
    )

    assert package.importer_id == "toy_sparse"
    assert package.workload_family == "sparse_la"
    assert package.validate()["valid"] is True
    assert registry.to_dict()["importers"][-1]["importer_id"] == "toy_sparse"
