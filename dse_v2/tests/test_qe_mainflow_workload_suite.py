#!/usr/bin/env python3
"""QE mainflow workload-suite and patch-manifest regressions."""

from __future__ import annotations

import copy

from dse_v2.reference_workloads.qe_mainflow import (
    default_qe_mainflow_workload_suite,
    example_qe_patch_runtime_manifest,
    package_qe_mainflow_case,
    qe_patch_runtime_manifest_schema,
    validate_qe_mainflow_workload_suite,
    validate_qe_patch_runtime_manifest,
)


def test_default_qe_mainflow_suite_covers_release_v1_mainflow_and_boundary():
    manifest = default_qe_mainflow_workload_suite()
    report = validate_qe_mainflow_workload_suite(manifest)

    assert report["valid"] is True
    assert report["release_v1_workload_suite_accepted"] is True
    assert report["trusted_closure_ready"] is False
    assert report["case_count"] >= 4
    assert {"scf", "nscf", "post_processing", "relax"}.issubset(set(report["mainflow_classes"]))
    assert manifest["candidate_identity_policy"]["workload_case_ids_participate"] is False
    assert all(case["candidate_identity_participation"] is False for case in manifest["cases"])
    assert all(case["adapter_boundary"]["generic_core_required_qe_fields"] == [] for case in manifest["cases"])
    assert all(case["baseline_run_provenance"] for case in manifest["cases"])
    assert all(case["tolerance_reference"]["required_fields"] for case in manifest["cases"])
    assert any("fft" in case["kernel_coverage"] for case in manifest["cases"])


def test_scf_only_qe_suite_is_rejected_for_release_acceptance():
    manifest = default_qe_mainflow_workload_suite()
    manifest["cases"] = [case for case in manifest["cases"] if case["stage_type"] == "scf"]
    manifest.pop("suite_hash", None)

    report = validate_qe_mainflow_workload_suite(manifest)

    assert report["valid"] is False
    assert report["release_v1_workload_suite_accepted"] is False
    messages = "\n".join(error["message"] for error in report["errors"])
    assert "not release-v1 mainflow complete" in messages
    assert "SCF-only suite" in messages


def test_qe_suite_case_round_trips_through_reference_importer_without_core_qe_fields():
    manifest = default_qe_mainflow_workload_suite()
    for case in manifest["cases"]:
        package = package_qe_mainflow_case(case)
        payload = package.to_dict()
        validation = package.validate()

        assert validation["valid"] is True
        assert payload["workload_family"] == "dft"
        assert payload["domain_metadata"]["dft"]["source_program"] == "qe"
        assert payload["source"]["kind"] == "qe_workflow_bundle"
        graph = payload["graph"]
        assert graph["schema_version"] == "dse.compute_graph.v1"
        assert graph["nodes"]
        assert all("npw" not in node and "nbnd" not in node for node in graph["nodes"].values())
        assert all("adapter:dft" in node["attributes"] for node in graph["nodes"].values())


def test_qe_patch_runtime_manifest_blocks_trusted_status_on_missing_safety_fields():
    schema = qe_patch_runtime_manifest_schema()
    assert "fallback_path is required" in schema["trusted_status_rules"][0]

    manifest = example_qe_patch_runtime_manifest()
    assert validate_qe_patch_runtime_manifest(manifest)["trusted_status_allowed"] is True

    broken = copy.deepcopy(manifest)
    broken["rows"][0].pop("fallback_path")
    broken["rows"][0]["tolerance_impact"] = {}
    report = validate_qe_patch_runtime_manifest(broken)

    assert report["valid"] is False
    assert report["trusted_status_allowed"] is False
    blocked_fields = {block["field"].split(".")[-1] for block in report["trusted_blocks"]}
    assert {"fallback_path", "tolerance_impact"}.issubset(blocked_fields)
