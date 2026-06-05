#!/usr/bin/env python3
"""QE-IC Layer-3 target-viability contract regressions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.profiling.qe_ic import validate_qe_ic_motif_profile
from dse_v2.viability import qe_ic
from dse_v2.viability.qe_ic.artifacts import QeIcTargetViabilityArtifactError
from dse_v2.viability.qe_ic.schema import REASON_CODE_REGISTRY
from dse_v2.workloads.qe_ic import validate_qe_ic_workload_suite


SUITE_PATH = Path("artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json")
MOTIF_PROFILE_PATH = Path("artifacts/qe_ic_motif_profile/qe_ic_motif_profile.json")
TARGET_CONFIG_PATH = Path("dse_v2/testdata/qe_ic_targets/qe_ic_target_config_fixture.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _build_report() -> dict:
    return qe_ic.build_qe_ic_target_viability(
        _load_json(SUITE_PATH),
        _load_json(MOTIF_PROFILE_PATH),
        _load_json(TARGET_CONFIG_PATH),
    )


def test_public_api_exports_expected_functions():
    assert qe_ic.build_qe_ic_target_viability
    assert qe_ic.validate_qe_ic_target_viability
    assert qe_ic.write_qe_ic_target_viability_artifacts
    assert qe_ic.load_qe_ic_target_viability


def test_target_config_fixture_loads():
    config = _load_json(TARGET_CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.target_config.v1"
    assert {target["target_type"] for target in config["targets"]} == {
        "gpu_only",
        "fpga_only",
        "gpu_fpga_hybrid",
    }
    assert config["thresholds"]["viable_score"] == 0.65


def test_layer1_and_layer2_inputs_are_validated():
    suite = _load_json(SUITE_PATH)
    motif_profile = _load_json(MOTIF_PROFILE_PATH)

    assert validate_qe_ic_workload_suite(suite)["status"] == "passed"
    assert validate_qe_ic_motif_profile(motif_profile)["status"] == "passed"


def test_build_viability_records_for_all_targets():
    motif_profile = _load_json(MOTIF_PROFILE_PATH)
    config = _load_json(TARGET_CONFIG_PATH)
    report = _build_report()
    motif_count = sum(
        len(group["motif_profiles"])
        for group in motif_profile["family_target_profiles"]
    )

    assert report["schema_version"] == "dse.qe_ic.target_viability.v1"
    assert report["layer"] == "layer3_target_viability_test"
    assert len(report["viability_records"]) == motif_count * len(config["targets"])
    assert {record["target_type"] for record in report["viability_records"]} == {
        "gpu_only",
        "fpga_only",
        "gpu_fpga_hybrid",
    }


def test_gpu_only_records_are_baseline():
    report = _build_report()

    assert all(
        record["decision"] == "baseline"
        for record in report["viability_records"]
        if record["target_type"] == "gpu_only"
    )


def test_fpga_and_hybrid_decisions_are_valid():
    report = _build_report()

    for record in report["viability_records"]:
        if record["target_type"] == "gpu_only":
            continue
        assert record["decision"] in {"reject", "maybe", "viable"}


def test_upper_bound_fields_are_present():
    report = _build_report()
    required = {
        "family_total_time_ms",
        "motif_time_ms",
        "runtime_ratio",
        "estimated_transfer_time_ms",
        "estimated_sync_time_ms",
        "estimated_removable_time_ms",
        "estimated_net_gain_ms",
        "estimated_net_gain_ratio",
    }

    for record in report["viability_records"]:
        assert required == set(record["upper_bound"])


def test_risk_fields_are_bounded():
    report = _build_report()
    required = {
        "overall_risk_score",
        "gpu_dominance_risk",
        "transfer_overhead_risk",
        "fpga_resource_risk",
        "profile_quality_risk",
    }

    for record in report["viability_records"]:
        assert required == set(record["risk"])
        assert all(0.0 <= value <= 1.0 for value in record["risk"].values())


def test_reason_codes_are_from_registry():
    report = _build_report()

    for record in report["viability_records"]:
        assert record["reason_codes"]
        assert set(record["reason_codes"]).issubset(REASON_CODE_REGISTRY)


def test_validation_passes_default_fixture():
    report = _build_report()
    validation = qe_ic.validate_qe_ic_target_viability(report)

    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["record_count"] == len(report["viability_records"])
    assert validation["target_count"] == 3


def test_validation_fails_unknown_target_id():
    report = _build_report()
    report["viability_records"][0]["target_id"] = "missing_target"

    validation = qe_ic.validate_qe_ic_target_viability(report)

    assert validation["status"] == "failed"
    assert any("unknown target_id" in error["message"] for error in validation["errors"])


def test_validation_fails_target_type_mismatch_for_target_id():
    report = _build_report()
    gpu_record = next(
        record
        for record in report["viability_records"]
        if record["target_type"] == "gpu_only"
    )
    gpu_record["target_type"] = "fpga_only"

    validation = qe_ic.validate_qe_ic_target_viability(report)

    assert validation["status"] == "failed"
    assert any("target_type does not match target config" in error["message"] for error in validation["errors"])


def test_validation_fails_unknown_motif():
    report = _build_report()
    report["viability_records"][0]["motif_id"] = "missing_motif"

    validation = qe_ic.validate_qe_ic_target_viability(report)

    assert validation["status"] == "failed"
    assert any("unknown motif" in error["message"] for error in validation["errors"])


def test_validation_fails_forbidden_architecture_fields():
    report = _build_report()
    report["architecture_candidates"] = []

    validation = qe_ic.validate_qe_ic_target_viability(report)

    assert validation["status"] == "failed"
    assert any("must not contain" in error["message"] for error in validation["errors"])


def test_writer_emits_required_artifacts(tmp_path: Path):
    result = qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_CONFIG_PATH,
    )

    assert result["status"] == "passed"
    assert result["artifacts"] == [
        "qe_ic_target_viability.json",
        "qe_ic_target_viability_validation.json",
        "qe_ic_target_viability_manifest.json",
        "qe_ic_target_viability_readme.md",
    ]
    for artifact in result["artifacts"]:
        assert (tmp_path / artifact).exists()


def test_writer_fail_closed_for_invalid_layer2_profile(tmp_path: Path):
    suite_path = tmp_path / "suite.json"
    motif_path = tmp_path / "motif_profile.json"
    suite_path.write_text(SUITE_PATH.read_text())
    motif_profile = _load_json(MOTIF_PROFILE_PATH)
    motif_profile["schema_version"] = "bad"
    motif_path.write_text(json.dumps(motif_profile))

    result = qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        suite_path,
        motif_path,
        TARGET_CONFIG_PATH,
    )

    assert result["status"] == "failed"
    assert result["artifacts"] == ["qe_ic_target_viability_validation.json"]
    assert (tmp_path / "qe_ic_target_viability_validation.json").exists()
    assert not (tmp_path / "qe_ic_target_viability.json").exists()
    assert not (tmp_path / "qe_ic_target_viability_manifest.json").exists()
    assert not (tmp_path / "qe_ic_target_viability_readme.md").exists()
    with pytest.raises(QeIcTargetViabilityArtifactError):
        qe_ic.load_qe_ic_target_viability(tmp_path / "qe_ic_target_viability.json")


def test_writer_fail_closed_removes_stale_canonical_artifacts(tmp_path: Path):
    valid_result = qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_CONFIG_PATH,
    )
    assert valid_result["status"] == "passed"

    motif_path = tmp_path / "motif_profile.json"
    motif_profile = _load_json(MOTIF_PROFILE_PATH)
    motif_profile["schema_version"] = "bad"
    motif_path.write_text(json.dumps(motif_profile))

    failed_result = qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        SUITE_PATH,
        motif_path,
        TARGET_CONFIG_PATH,
    )

    assert failed_result["status"] == "failed"
    assert (tmp_path / "qe_ic_target_viability_validation.json").exists()
    assert not (tmp_path / "qe_ic_target_viability.json").exists()
    assert not (tmp_path / "qe_ic_target_viability_manifest.json").exists()
    assert not (tmp_path / "qe_ic_target_viability_readme.md").exists()


def test_checked_in_qe_ic_target_viability_artifacts_match_builder_output(tmp_path: Path):
    checked_in = Path("artifacts/qe_ic_target_viability")

    qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_CONFIG_PATH,
    )

    for artifact in [
        "qe_ic_target_viability.json",
        "qe_ic_target_viability_validation.json",
        "qe_ic_target_viability_manifest.json",
        "qe_ic_target_viability_readme.md",
    ]:
        assert (checked_in / artifact).read_text() == (tmp_path / artifact).read_text()


def test_manifest_declares_layer4_downstream(tmp_path: Path):
    qe_ic.write_qe_ic_target_viability_artifacts(
        tmp_path,
        SUITE_PATH,
        MOTIF_PROFILE_PATH,
        TARGET_CONFIG_PATH,
    )
    manifest = json.loads((tmp_path / "qe_ic_target_viability_manifest.json").read_text())

    assert manifest["artifact_role"] == "dse_layer3_target_viability"
    assert manifest["producer"] == "dse_v2.viability.qe_ic"
    assert manifest["layer"] == "layer3_target_viability_test"
    assert manifest["downstream_consumers"] == [
        "layer4_candidate_generation",
        "promotion_policy",
    ]


def test_cli_emits_passed_status(tmp_path: Path):
    script = Path("dse_v2/scripts/dse/build_qe_ic_target_viability.py")

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--suite",
            str(SUITE_PATH),
            "--motif-profile",
            str(MOTIF_PROFILE_PATH),
            "--target-config",
            str(TARGET_CONFIG_PATH),
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
    assert "qe_ic_target_viability.json" in result["artifacts"]


def test_core_logic_not_in_cli():
    script = Path("dse_v2/scripts/dse/build_qe_ic_target_viability.py")
    source = script.read_text()

    assert "from dse_v2.viability.qe_ic" in source
    assert "CATEGORY_PRIORS" not in source
    assert "streaming_score" not in source
    assert "viability_score" not in source


def test_claim_boundary_blocks_architecture_promotion_implementation_claims():
    report = _build_report()
    boundary = report["claim_boundary"].lower()

    for term in (
        "target viability estimates",
        "architecture candidates",
        "promotion decisions",
        "implementation results",
        "final performance claims",
    ):
        assert term in boundary
    for forbidden in (
        "architecture_candidates",
        "promotion_decisions",
        "systemc_requests",
        "vivado_requests",
        "final_performance_claims",
    ):
        assert forbidden not in report
