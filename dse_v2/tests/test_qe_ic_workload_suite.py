#!/usr/bin/env python3
"""QE-IC Layer-1 workload-suite contract regressions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.workloads import qe_ic
from dse_v2.workloads.qe_ic.registry import (
    MOTIF_REGISTRY,
    REQUIRED_FIRST_VERSION_FAMILY_IDS,
    SCENARIO_REGISTRY,
    WORKLOAD_FAMILY_REGISTRY,
)


def _family_ids(suite: dict) -> set[str]:
    return {family["family_id"] for family in suite["workload_families"]}


def test_public_api_exports_expected_functions():
    assert qe_ic.build_default_qe_ic_workload_suite
    assert qe_ic.validate_qe_ic_workload_suite
    assert qe_ic.write_qe_ic_workload_suite_artifacts
    assert qe_ic.load_qe_ic_workload_suite


def test_registry_contains_required_families():
    assert set(REQUIRED_FIRST_VERSION_FAMILY_IDS) == {
        "ground_state_band_structure",
        "phonon_dfpt",
        "electron_phonon_mobility",
        "strain_doping_field_sweep",
        "interface_band_offset_defect",
    }
    assert set(REQUIRED_FIRST_VERSION_FAMILY_IDS).issubset(WORKLOAD_FAMILY_REGISTRY)


def test_suite_contains_required_families():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    assert set(REQUIRED_FIRST_VERSION_FAMILY_IDS).issubset(_family_ids(suite))
    assert all(
        family["first_version_required"] is True
        for family in suite["workload_families"]
        if family["family_id"] in REQUIRED_FIRST_VERSION_FAMILY_IDS
    )


def test_family_ids_are_unique():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    ids = [family["family_id"] for family in suite["workload_families"]]

    assert len(ids) == len(set(ids))


def test_family_dependencies_are_valid():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    ids = _family_ids(suite)

    for family in suite["workload_families"]:
        assert set(family["depends_on_families"]).issubset(ids)


def test_expected_motifs_are_registered():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    for family in suite["workload_families"]:
        assert family["expected_motifs"]
        for motif_id in family["expected_motifs"]:
            assert motif_id in MOTIF_REGISTRY
            assert isinstance(MOTIF_REGISTRY[motif_id]["provisional"], bool)


def test_each_family_has_device_relevance():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    assert all(family["device_relevance"] for family in suite["workload_families"])


def test_each_family_has_profiling_contract():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    required_fields = {
        "runtime_breakdown",
        "op_mix",
        "memory_movement",
        "communication_pattern",
        "parallel_axes",
        "reuse_opportunities",
        "gpu_baseline_required",
    }

    for family in suite["workload_families"]:
        contract = family["profiling_contract"]
        assert contract["required_next_layer"] == "motif_profiling"
        assert required_fields.issubset(set(contract["expected_profile_fields"]))
        assert contract["gpu_baseline_required"] is True


def test_primary_scenario_exists():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    assert suite["primary_scenario_id"] in {
        scenario["scenario_id"] for scenario in suite["scenarios"]
    }
    assert suite["primary_scenario_id"] in SCENARIO_REGISTRY


def test_scenario_weights_sum_to_one():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    for scenario in suite["scenarios"]:
        assert sum(scenario["weights"].values()) == 1.0


def test_scenario_weights_reference_known_families():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    ids = _family_ids(suite)

    for scenario in suite["scenarios"]:
        assert set(scenario["weights"]) == ids


def test_excluded_workflows_have_reasons():
    suite = qe_ic.build_default_qe_ic_workload_suite()

    assert suite["excluded_workflows"]
    assert all(row["workflow"] and row["reason"] for row in suite["excluded_workflows"])


def test_validation_passes_default_suite():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    validation = qe_ic.validate_qe_ic_workload_suite(suite)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["family_count"] == 5
    assert validation["scenario_count"] == 2
    assert validation["motif_count"] >= 25
    assert validation["excluded_workflow_count"] == 5


def test_writer_emits_required_artifacts(tmp_path: Path):
    result = qe_ic.write_qe_ic_workload_suite_artifacts(tmp_path)

    assert result["status"] == "passed"
    assert result["artifacts"] == [
        "qe_ic_workload_suite.json",
        "qe_ic_workload_suite_validation.json",
        "qe_ic_workload_suite_manifest.json",
        "qe_ic_workload_suite_readme.md",
    ]
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_manifest_declares_downstream_consumers(tmp_path: Path):
    qe_ic.write_qe_ic_workload_suite_artifacts(tmp_path)
    manifest = json.loads((tmp_path / "qe_ic_workload_suite_manifest.json").read_text())

    assert manifest["artifact_role"] == "dse_layer1_workload_suite"
    assert manifest["producer"] == "dse_v2.workloads.qe_ic"
    assert manifest["layer"] == "layer1_workload_suite_definition"
    assert manifest["downstream_consumers"] == [
        "layer2_motif_profiling",
        "layer3_target_viability_test",
        "promotion_policy",
    ]


def test_artifacts_are_consistent_with_manifest(tmp_path: Path):
    qe_ic.write_qe_ic_workload_suite_artifacts(tmp_path)
    manifest = json.loads((tmp_path / "qe_ic_workload_suite_manifest.json").read_text())
    validation = json.loads((tmp_path / manifest["validation_artifact"]).read_text())
    suite = json.loads((tmp_path / manifest["suite_artifact"]).read_text())

    assert manifest["suite_artifact"] == "qe_ic_workload_suite.json"
    assert manifest["validation_artifact"] == "qe_ic_workload_suite_validation.json"
    assert manifest["readme_artifact"] == "qe_ic_workload_suite_readme.md"
    assert suite["schema_version"] == "dse.qe_ic.workload_suite.v1"
    assert validation["schema_version"] == "dse.qe_ic.workload_suite_validation.v1"
    assert validation["status"] == "passed"


def test_suite_can_be_loaded_and_revalidated(tmp_path: Path):
    qe_ic.write_qe_ic_workload_suite_artifacts(tmp_path)

    loaded = qe_ic.load_qe_ic_workload_suite(tmp_path / "qe_ic_workload_suite.json")

    assert loaded["suite_id"] == "qe_ic_device_suite_v1"
    assert qe_ic.validate_qe_ic_workload_suite(loaded)["status"] == "passed"


def test_cli_emits_passed_status(tmp_path: Path):
    script = Path("dse_v2/scripts/dse/build_qe_ic_workload_suite.py")

    completed = subprocess.run(
        [sys.executable, str(script), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["status"] == "passed"
    assert result["out_dir"] == str(tmp_path)
    assert "qe_ic_workload_suite.json" in result["artifacts"]


def test_core_logic_not_in_cli():
    script = Path("dse_v2/scripts/dse/build_qe_ic_workload_suite.py")
    source = script.read_text()

    assert "from dse_v2.workloads.qe_ic" in source
    assert "WORKLOAD_FAMILY_REGISTRY" not in source
    assert "SCENARIO_REGISTRY" not in source
    assert "MOTIF_REGISTRY" not in source


def test_claim_boundary_blocks_profiling_architecture_performance_viability_promotion():
    suite = qe_ic.build_default_qe_ic_workload_suite()
    boundary = suite["claim_boundary"].lower()
    manifest_boundary = qe_ic.build_qe_ic_workload_suite_manifest()["claim_boundary"].lower()

    for term in ("profiling", "architecture", "performance", "viability", "promotion"):
        assert term in boundary
        assert term in manifest_boundary
    assert "does not contain" in boundary
    assert "not profiling" in manifest_boundary
