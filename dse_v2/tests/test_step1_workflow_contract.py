#!/usr/bin/env python3
"""Step1 persisted workload-ingestion workflow contract regressions."""

from __future__ import annotations

import json

import pytest

from dse_v2.core.workload import (
    STEP1_INGESTION_REQUEST_SCHEMA,
    WORKLOAD_CHARACTERIZATION_SCHEMA,
    Step1HandoffError,
    create_dynamic_custom_graph,
    create_tensor_chain_graph,
    default_importer_registry,
    default_profile_registry,
    load_step1_handoff,
    run_step1_ingestion_request_workflow,
    run_step1_workload_ingestion_workflow,
    verify_step1_artifact_validation,
)
from dse_v2.mapping.step2_workflow import run_step2_architecture_mapping_workflow_from_step1
from dse_v2.reference_workloads.dft_qe import qe_scf_reference_profile, register_qe_reference_importer


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


def test_step1_complete_workflow_persists_replayable_handoff_and_step2_loads_from_disk(tmp_path):
    step1_dir = tmp_path / "step1"
    result = run_step1_workload_ingestion_workflow(
        create_tensor_chain_graph("step1_tensor_graph"),
        profile_id="ml_tensor",
        importer_id="generic_json",
        source_kind="hand_authored",
        output_dir=step1_dir,
        source_path="fixtures/tensor_chain.json",
        timestamp="2026-05-12T00:00:00Z",
        environment_summary={"test": True},
    )

    assert result.status == "complete"
    expected = {
        "ingestion_request.json",
        "step1_status.json",
        "workload_package.json",
        "workload_graph.json",
        "workload_characterization.json",
        "graph_lowering_report.json",
        "executable_graph.json",
        "profile_manifest.json",
        "importer_manifest.json",
        "step1_artifact_validation.json",
    }
    assert expected <= {path.name for path in step1_dir.iterdir() if path.is_file()}

    status = _load_json(step1_dir / "step1_status.json")
    request = _load_json(step1_dir / "ingestion_request.json")
    package = _load_json(step1_dir / "workload_package.json")
    characterization = _load_json(step1_dir / "workload_characterization.json")
    lowering = _load_json(step1_dir / "graph_lowering_report.json")
    validation = _load_json(step1_dir / "step1_artifact_validation.json")

    assert request["schema_version"] == STEP1_INGESTION_REQUEST_SCHEMA
    assert request["profile"]["profile_id"] == "ml_tensor"
    assert request["importer"]["importer_id"] == "generic_json"
    assert status["schema_version"] == "dse.step1.status.v1"
    assert status["status"] == "complete"
    assert status["full_workload_eligible"] is True
    assert status["provenance"]["profile_id"] == "ml_tensor"
    assert status["provenance"]["importer_id"] == "generic_json"
    assert status["provenance"]["source_path"] == "fixtures/tensor_chain.json"
    assert package["schema_version"] == "dse.step1.workload_package.v1"
    assert package["workload_family"] == "ml_tensor"
    assert characterization["schema_version"] == WORKLOAD_CHARACTERIZATION_SCHEMA
    assert characterization["analysis_scope"] == "architecture_independent"
    assert characterization["lowering_status"] == "lowered"
    assert characterization["full_workload_eligible"] is True
    assert characterization["op_mix_summary"]["node_count"] == 3
    assert characterization["edge_traffic_summary"]["edge_count"] == 2
    assert characterization["fusion_candidate_hints"]
    assert "selected_fusion" not in set(_all_keys(characterization))
    assert {"selected_mapping", "selected_placement", "selected_schedule", "selected_runtime_policy"}.isdisjoint(
        set(_all_keys(characterization))
    )
    assert lowering["status"] == "lowered"
    assert validation["valid"] is True
    assert validation["artifacts"]["ingestion_request"]["schema_version"] == STEP1_INGESTION_REQUEST_SCHEMA
    assert validation["artifacts"]["workload_characterization"]["schema_version"] == WORKLOAD_CHARACTERIZATION_SCHEMA
    assert validation["artifacts"]["workload_package"]["sha256"]
    assert verify_step1_artifact_validation(step1_dir)["valid"] is True

    handoff = load_step1_handoff(step1_dir)
    assert handoff["workload_package"].workload_id == "step1_tensor_graph"
    assert handoff["executable_graph"].metadata["source_graph_id"] == "step1_tensor_graph"
    assert handoff["workload_characterization"]["source_graph_id"] == "step1_tensor_graph"

    step2 = run_step2_architecture_mapping_workflow_from_step1(step1_dir, output_dir=tmp_path / "step2")
    assert step2.workload_package.workload_id == "step1_tensor_graph"
    assert (tmp_path / "step2" / "workload_package.json").exists()


def test_step1_unknown_profile_or_importer_is_blocked_with_manifests(tmp_path):
    result = run_step1_workload_ingestion_workflow(
        create_tensor_chain_graph("unknown_profile_graph"),
        profile_id="missing_profile",
        importer_id="generic_json",
        output_dir=tmp_path,
    )

    assert result.status == "blocked_unknown_importer_or_profile"
    status = _load_json(tmp_path / "step1_status.json")
    assert status["status"] == "blocked_unknown_importer_or_profile"
    assert status["reasons"][0]["reason_id"] == "unknown_importer_or_profile"
    assert "ml_tensor" in status["reasons"][0]["available_profiles"]
    assert (tmp_path / "profile_manifest.json").exists()
    assert (tmp_path / "importer_manifest.json").exists()
    assert not (tmp_path / "workload_package.json").exists()
    assert not (tmp_path / "workload_characterization.json").exists()

    with pytest.raises(Step1HandoffError):
        load_step1_handoff(tmp_path)


def test_step1_unsupported_graph_is_blocked_before_step2_handoff(tmp_path):
    result = run_step1_workload_ingestion_workflow(
        create_dynamic_custom_graph("unsupported_dynamic", supported=False),
        profile_id="dynamic_custom",
        importer_id="generic_json",
        source_kind="hand_authored",
        output_dir=tmp_path,
    )

    assert result.status == "blocked_unsupported_graph"
    status = _load_json(tmp_path / "step1_status.json")
    lowering = _load_json(tmp_path / "graph_lowering_report.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")
    assert status["status"] == "blocked_unsupported_graph"
    assert status["full_workload_eligible"] is False
    assert status["reasons"][0]["reason_id"] == "unsupported_graph"
    assert lowering["status"] == "unsupported"
    assert lowering["unsupported_constructs"]
    assert characterization["lowering_status"] == "unsupported"
    assert characterization["full_workload_eligible"] is False
    assert characterization["analysis_scope"] == "architecture_independent"
    assert characterization["region_summary"]["unsupported_region_hints"]
    assert not (tmp_path / "executable_graph.json").exists()
    assert verify_step1_artifact_validation(tmp_path)["valid"] is True

    with pytest.raises(Step1HandoffError):
        load_step1_handoff(tmp_path)


def test_step1_artifact_validation_detects_checksum_mismatch(tmp_path):
    run_step1_workload_ingestion_workflow(
        create_tensor_chain_graph("checksum_graph"),
        profile_id="ml_tensor",
        importer_id="generic_json",
        source_kind="hand_authored",
        output_dir=tmp_path,
    )
    package_path = tmp_path / "workload_package.json"
    package = _load_json(package_path)
    package["workload_id"] = "tampered"
    package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_step1_artifact_validation(tmp_path)
    assert verification["valid"] is False
    assert any(error["artifact"] == "workload_package" and "checksum" in error["message"] for error in verification["errors"])


def test_step1_ingestion_request_supports_dft_reference_without_core_dft_requirement(tmp_path):
    profile_registry = default_profile_registry()
    profile_registry.register(qe_scf_reference_profile())
    importer_registry = default_importer_registry()
    register_qe_reference_importer(importer_registry)

    result = run_step1_ingestion_request_workflow(
        {
            "schema_version": STEP1_INGESTION_REQUEST_SCHEMA,
            "source": {"source_kind": "generated"},
            "profile": {"profile_id": "qe_scf_reference", "profile_version": "v1"},
            "importer": {"importer_id": "qe_reference_fixture", "importer_version": "v1"},
            "parameters": {
                "npw": 128,
                "nkb": 16,
                "m": 8,
                "nfft": 1024,
                "precision": "complex_fp64",
                "graph_id": "dft_request_graph",
            },
        },
        output_dir=tmp_path,
        profile_registry=profile_registry,
        importer_registry=importer_registry,
        timestamp="2026-05-13T00:00:00Z",
        environment_summary={"test": True},
    )

    assert result.status == "complete"
    request = _load_json(tmp_path / "ingestion_request.json")
    package = _load_json(tmp_path / "workload_package.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")

    assert request["profile"]["profile_id"] == "qe_scf_reference"
    assert request["parameters"]["npw"] == 128
    assert package["workload_family"] == "dft_qe_reference"
    assert package["domain_metadata"]["npw"] == 128
    assert "npw" not in package["graph"]
    assert characterization["workload_family"] == "dft_qe_reference"
    assert characterization["op_mix_summary"]["by_op_type"]["gemm"]["node_count"] >= 1
    assert characterization["op_mix_summary"]["by_op_type"]["fft"]["node_count"] >= 1
    assert characterization["op_mix_summary"]["by_op_type"]["eigen"]["node_count"] >= 1
    assert characterization["edge_traffic_summary"]["total_edge_tensor_bytes"] > 0
    assert verify_step1_artifact_validation(tmp_path)["valid"] is True
