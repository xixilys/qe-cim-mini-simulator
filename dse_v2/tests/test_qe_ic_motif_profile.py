#!/usr/bin/env python3
"""QE-IC Layer-2 motif-profile contract regressions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.profiling import qe_ic
from dse_v2.profiling.qe_ic.artifacts import QeIcMotifProfileArtifactError
from dse_v2.profiling.qe_ic.motif_mapping import map_profile_event_to_motif
from dse_v2.workloads.qe_ic import build_default_qe_ic_workload_suite


FIXTURE_PATH = Path("dse_v2/testdata/qe_ic_profiles/qe_ic_profile_sources_fixture.json")


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _build_profile() -> dict:
    suite = build_default_qe_ic_workload_suite()
    fixture = _load_fixture()
    return qe_ic.build_qe_ic_motif_profile(suite, fixture["profile_sources"])


def test_public_api_exports_expected_functions():
    assert qe_ic.build_qe_ic_motif_profile
    assert qe_ic.validate_qe_ic_motif_profile
    assert qe_ic.write_qe_ic_motif_profile_artifacts
    assert qe_ic.load_qe_ic_motif_profile


def test_profile_fixture_schema_loads():
    fixture = _load_fixture()

    assert fixture["schema_version"] == "dse.qe_ic.profile_sources.v1"
    assert isinstance(fixture["profile_sources"], list)
    assert len(fixture["profile_sources"]) == 5


def test_profile_sources_have_required_fields():
    fixture = _load_fixture()
    required = {
        "source_id",
        "workload_family_id",
        "program",
        "target",
        "input_case",
        "profile_source_type",
        "raw_artifact_path",
        "raw_artifact_hash",
        "trusted_for_layer2",
        "events",
        "gpu_baseline",
    }

    for source in fixture["profile_sources"]:
        assert required.issubset(source)
        assert source["target"] == "gpu_only"
        assert source["trusted_for_layer2"] is True
        assert source["raw_artifact_path"]
        assert source["raw_artifact_hash"]
        assert source["events"]


def test_event_mapping_uses_mapping_hint_first():
    suite = build_default_qe_ic_workload_suite()
    event = {
        "event_name": "allreduce that would otherwise match reduction",
        "mapping_hint": "fft_transpose",
        "time_ms": 1.0,
    }

    mapped = map_profile_event_to_motif(event, suite)

    assert mapped == {
        "event_name": "allreduce that would otherwise match reduction",
        "motif_id": "fft_transpose",
        "mapping_status": "mapped",
        "mapping_confidence": "high",
        "mapping_reason": "mapping_hint",
    }


def test_event_mapping_rule_fallback():
    suite = build_default_qe_ic_workload_suite()
    event = {"event_name": "cdiagh_gpu_kernel", "time_ms": 1.0}

    mapped = map_profile_event_to_motif(event, suite)

    assert mapped["motif_id"] == "diagonalization"
    assert mapped["mapping_status"] == "mapped"
    assert mapped["mapping_confidence"] == "medium"
    assert mapped["mapping_reason"] == "event_name_rule:cdiagh"


def test_unmapped_events_are_preserved():
    profile = _build_profile()

    unmapped = [
        event
        for group in profile["family_target_profiles"]
        for event in group["mapped_events"]
        if event["motif_id"] == "unmapped"
    ]

    assert unmapped
    assert unmapped[0]["mapping_status"] == "unmapped"
    assert unmapped[0]["mapping_reason"] == "no registered motif mapping"


def test_aggregation_builds_family_target_profiles():
    profile = _build_profile()

    assert profile["schema_version"] == "dse.qe_ic.motif_profile.v1"
    assert profile["suite_id"] == "qe_ic_device_suite_v1"
    assert profile["profile_source_count"] == 5
    assert len(profile["family_target_profiles"]) == 5
    keys = {
        (group["workload_family_id"], group["target"])
        for group in profile["family_target_profiles"]
    }
    assert keys == {
        ("ground_state_band_structure", "gpu_only"),
        ("phonon_dfpt", "gpu_only"),
        ("electron_phonon_mobility", "gpu_only"),
        ("strain_doping_field_sweep", "gpu_only"),
        ("interface_band_offset_defect", "gpu_only"),
    }


def test_runtime_ratios_sum_to_one():
    profile = _build_profile()

    for group in profile["family_target_profiles"]:
        ratio_sum = sum(
            motif["runtime_ratio"] for motif in group["motif_profiles"]
        ) + group["unmapped_time_ratio"]
        assert ratio_sum == pytest.approx(1.0)


def test_gpu_baseline_required_and_present():
    profile = _build_profile()

    for group in profile["family_target_profiles"]:
        baseline = group["gpu_baseline"]
        assert baseline["required"] is True
        assert baseline["available"] is True
        assert baseline["speedup_vs_cpu"] > 0.0
        assert baseline["gpu_utilization"] > 0.0


def test_unmapped_time_ratio_threshold_enforced():
    suite = build_default_qe_ic_workload_suite()
    fixture = _load_fixture()
    source = copy.deepcopy(fixture["profile_sources"][0])
    source["events"].append(
        {
            "event_name": "unknown_large_timer",
            "time_ms": 1000.0,
            "memory_movement_bytes": 0,
            "communication_bytes": 0,
            "parallel_axes": [],
        }
    )
    profile = qe_ic.build_qe_ic_motif_profile(suite, [source])

    validation = qe_ic.validate_qe_ic_motif_profile(profile)

    assert validation["status"] == "failed"
    assert any(
        error["field"].endswith("unmapped_time_ratio")
        for error in validation["errors"]
    )


def test_manual_profile_table_is_explicitly_marked():
    fixture = _load_fixture()

    assert all(
        source["profile_source_type"] == "manual_profile_table"
        for source in fixture["profile_sources"]
    )


def test_validation_passes_default_fixture():
    profile = _build_profile()
    validation = qe_ic.validate_qe_ic_motif_profile(profile)

    assert validation == {
        "schema_version": "dse.qe_ic.motif_profile_validation.v1",
        "status": "passed",
        "errors": [],
        "warnings": [],
        "family_profile_count": 5,
        "profile_source_count": 5,
        "unmapped_time_ratio_max": pytest.approx(0.05),
        "gpu_baseline_coverage_closed": True,
    }


def test_validation_fails_missing_gpu_baseline():
    profile = _build_profile()
    profile["family_target_profiles"][0]["gpu_baseline"]["available"] = False

    validation = qe_ic.validate_qe_ic_motif_profile(profile)

    assert validation["status"] == "failed"
    assert any(
        "gpu_baseline.available" in error["field"]
        for error in validation["errors"]
    )
    assert validation["gpu_baseline_coverage_closed"] is False


def test_validation_fails_unknown_motif():
    profile = _build_profile()
    profile["family_target_profiles"][0]["motif_profiles"][0]["motif_id"] = "missing_motif"

    validation = qe_ic.validate_qe_ic_motif_profile(profile)

    assert validation["status"] == "failed"
    assert any("unknown motif" in error["message"] for error in validation["errors"])


def test_validation_fails_unknown_mapped_event_motif():
    profile = _build_profile()
    mapped_event = next(
        event
        for event in profile["family_target_profiles"][0]["mapped_events"]
        if event["mapping_status"] == "mapped"
    )
    mapped_event["motif_id"] = "missing_motif"

    validation = qe_ic.validate_qe_ic_motif_profile(profile)

    assert validation["status"] == "failed"
    assert any(
        "mapped event references unknown motif" in error["message"]
        for error in validation["errors"]
    )


def test_writer_emits_required_artifacts(tmp_path: Path):
    suite_path = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")

    result = qe_ic.write_qe_ic_motif_profile_artifacts(
        tmp_path,
        suite_path,
        FIXTURE_PATH,
    )

    assert result["status"] == "passed"
    assert result["artifacts"] == [
        "qe_ic_motif_profile.json",
        "qe_ic_motif_profile_validation.json",
        "qe_ic_motif_profile_manifest.json",
        "qe_ic_motif_profile_readme.md",
    ]
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_writer_fail_closed_only_writes_validation_for_invalid_profile(tmp_path: Path):
    suite_path = tmp_path / "suite.json"
    sources_path = tmp_path / "sources.json"
    suite = build_default_qe_ic_workload_suite()
    fixture = _load_fixture()
    fixture["profile_sources"][0]["gpu_baseline"]["available"] = False
    suite_path.write_text(json.dumps(suite))
    sources_path.write_text(json.dumps(fixture))

    result = qe_ic.write_qe_ic_motif_profile_artifacts(
        tmp_path,
        suite_path,
        sources_path,
    )

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_motif_profile_validation.json"]
    assert (tmp_path / "qe_ic_motif_profile_validation.json").exists()
    assert not (tmp_path / "qe_ic_motif_profile.json").exists()
    assert not (tmp_path / "qe_ic_motif_profile_manifest.json").exists()
    assert not (tmp_path / "qe_ic_motif_profile_readme.md").exists()
    with pytest.raises(QeIcMotifProfileArtifactError):
        qe_ic.load_qe_ic_motif_profile(tmp_path / "qe_ic_motif_profile.json")


def test_manifest_declares_layer3_downstream(tmp_path: Path):
    suite_path = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")
    qe_ic.write_qe_ic_motif_profile_artifacts(tmp_path, suite_path, FIXTURE_PATH)

    manifest = json.loads((tmp_path / "qe_ic_motif_profile_manifest.json").read_text())

    assert manifest["artifact_role"] == "dse_layer2_motif_profile"
    assert manifest["producer"] == "dse_v2.profiling.qe_ic"
    assert manifest["layer"] == "layer2_motif_profiling"
    assert manifest["source_layer1_suite_artifact"] == "qe_ic_workload_suite.json"
    assert manifest["downstream_consumers"] == [
        "layer3_target_viability_test",
        "promotion_policy",
    ]


def test_cli_emits_passed_status(tmp_path: Path):
    script = Path("dse_v2/scripts/dse/build_qe_ic_motif_profile.py")
    suite_path = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--suite",
            str(suite_path),
            "--profile-sources",
            str(FIXTURE_PATH),
            "--out",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["status"] == "passed"
    assert result["out_dir"] == str(tmp_path)
    assert "qe_ic_motif_profile.json" in result["artifacts"]


def test_core_logic_not_in_cli():
    script = Path("dse_v2/scripts/dse/build_qe_ic_motif_profile.py")
    source = script.read_text()

    assert "from dse_v2.profiling.qe_ic" in source
    assert "EVENT_NAME_TO_MOTIF_RULES" not in source
    assert "map_profile_event_to_motif" not in source
    assert "manual_profile_table" not in source


def test_claim_boundary_blocks_architecture_viability_promotion():
    profile = _build_profile()
    boundary = profile["claim_boundary"].lower()

    for term in (
        "profiling",
        "architecture candidates",
        "target viability",
        "promotion decisions",
        "final performance claims",
    ):
        assert term in boundary
    assert "does not contain" in boundary
    assert "architecture_candidates" not in profile
    assert "target_viability" not in profile
    assert "promotion_decisions" not in profile
