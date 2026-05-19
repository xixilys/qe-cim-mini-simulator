"""Tests for reusable QE accelerated requirements remap/admissibility helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dse_v2.reference_workloads.qe_accelerated_requirements import (
    DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT,
    assert_no_forbidden_v1_writable_paths,
    build_qe_admissibility_ledger,
    remap_qe_accelerated_numeric_requirements,
    validate_qe_admissibility_ledger,
    validate_qe_producer_counts,
    write_qe_admissibility_ledger,
    write_remapped_qe_accelerated_numeric_requirements,
)


OLD_ROOT = DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT


def _row(candidate_id: str, workload_case_id: str) -> dict:
    row_root = f"{OLD_ROOT}/accelerated_numeric_inputs/{candidate_id}/{workload_case_id}"
    baseline = f"{OLD_ROOT}/qe_baselines/{workload_case_id}/baseline_comparison.json"
    return {
        "row_id": f"{candidate_id}::{workload_case_id}",
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "baseline_comparison": baseline,
        "evidence_output": f"{row_root}/qe_accelerated_numeric_evidence.json",
        "required_outputs": {
            "accelerated_stdout": f"{row_root}/accelerated_qe.stdout.log",
            "kernel_evidence_json": f"{row_root}/kernel_evidence.json",
            "offload_provenance_json": f"{row_root}/offload_provenance.json",
            "density_residual": "numeric CLI value or provenance-derived scalar",
        },
        "builder_command_template": [
            "/usr/bin/python3",
            "dse_v2/scripts/dse/build_qe_accelerated_numeric_evidence.py",
            "--baseline-comparison",
            baseline,
            "--accelerated-stdout",
            f"{row_root}/accelerated_qe.stdout.log",
            "--out",
            f"{row_root}/qe_accelerated_numeric_evidence.json",
        ],
        "hpsi_sidecar_bridge_command_template": [
            "--out-dir",
            row_root,
            "--baseline-comparison",
            baseline,
        ],
        "producer_command_template": [
            "/usr/bin/python3",
            "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py",
            "--requirements",
            f"{OLD_ROOT}/qe_accelerated_numeric_evidence_requirements.json",
            "--candidate-id",
            candidate_id,
            "--workload-case-id",
            workload_case_id,
        ],
    }


def _requirements() -> dict:
    source = f"{OLD_ROOT}/qe_accelerated_numeric_evidence_requirements.json"
    return {
        "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
        "status": "required_for_deliverable_complete",
        "row_count": 2,
        "campaign_producer_command_template": [
            "/usr/bin/python3",
            "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py",
            "--requirements",
            source,
            "--fail-on-blocked",
        ],
        "campaign_collector_command_template": [
            "--requirements",
            source,
            "--out-dir",
            f"{OLD_ROOT}/qe_accelerated_numeric_campaign",
        ],
        "hpsi_sidecar_bridge_campaign_command_template": [
            "--requirements",
            source,
            "--out-dir",
            f"{OLD_ROOT}/qe_accelerated_numeric_campaign/bridge",
        ],
        "rows": [
            _row("cand_a", "qe_si_scf_small_v1"),
            _row("cand_b", "qe_si_bands_small_v1"),
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def test_remap_one_row_rewrites_writable_paths_and_preserves_read_only_refs(tmp_path: Path) -> None:
    source = f"{OLD_ROOT}/qe_accelerated_numeric_evidence_requirements.json"
    output = "runs/dse/qe_l4_one_row_trusted_20260518T000000Z/qe_accelerated_numeric_evidence_requirements.v2.json"
    root = "runs/dse/qe_l4_one_row_trusted_20260518T000000Z"

    remapped = remap_qe_accelerated_numeric_requirements(
        _requirements(),
        source_requirements_path=source,
        output_requirements_path=output,
        output_root=root,
        candidate_id="cand_a",
        workload_case_id="qe_si_scf_small_v1",
        expected_row_count=1,
    )

    assert remapped["row_count"] == 1
    assert remapped["source_requirements"] == source
    assert remapped["writable_output_root"] == root
    assert remapped["schema_version"].endswith("+remapped_v2")
    row = remapped["rows"][0]
    assert row["baseline_comparison"] == f"{OLD_ROOT}/qe_baselines/qe_si_scf_small_v1/baseline_comparison.json"
    assert row["required_outputs"]["density_residual"] == "numeric CLI value or provenance-derived scalar"
    assert row["evidence_output"] == (
        f"{root}/accelerated_numeric_inputs/cand_a/qe_si_scf_small_v1/"
        "qe_accelerated_numeric_evidence.json"
    )
    assert row["required_outputs"]["kernel_evidence_json"] == (
        f"{root}/accelerated_numeric_inputs/cand_a/qe_si_scf_small_v1/kernel_evidence.json"
    )
    assert output in row["producer_command_template"]
    assert f"{root}/qe_accelerated_numeric_campaign" in remapped["campaign_collector_command_template"]
    assert_no_forbidden_v1_writable_paths(remapped)


def test_write_full_remap_preserves_row_count_and_rejects_forbidden_writable_v1_paths(tmp_path: Path) -> None:
    source_path = tmp_path / "source_requirements.json"
    output_path = tmp_path / "trusted_run" / "qe_accelerated_numeric_evidence_requirements.v2.json"
    output_root = tmp_path / "trusted_run"
    _write_json(source_path, _requirements())

    remapped = write_remapped_qe_accelerated_numeric_requirements(
        source_requirements_path=source_path,
        output_requirements_path=output_path,
        output_root=output_root,
    )

    assert output_path.exists()
    assert remapped["row_count"] == 2
    assert len(remapped["rows"]) == 2
    assert all(str(output_root) in row["evidence_output"] for row in remapped["rows"])
    assert_no_forbidden_v1_writable_paths(remapped)

    broken = json.loads(json.dumps(remapped))
    broken["rows"][0]["required_outputs"]["accelerated_stdout"] = (
        f"{OLD_ROOT}/accelerated_numeric_inputs/cand_a/qe_si_scf_small_v1/accelerated_qe.stdout.log"
    )
    with pytest.raises(ValueError, match="forbidden writable v1 paths remain"):
        assert_no_forbidden_v1_writable_paths(broken)


def test_validate_producer_counts_accepts_exact_passed_bundle_and_rejects_blockers() -> None:
    requirements = remap_qe_accelerated_numeric_requirements(
        _requirements(),
        source_requirements_path=f"{OLD_ROOT}/qe_accelerated_numeric_evidence_requirements.json",
        output_requirements_path="runs/dse/qe_l4_full_trusted/qe_accelerated_numeric_evidence_requirements.v2.json",
        output_root="runs/dse/qe_l4_full_trusted",
    )
    bundle_rows = [
        {
            "candidate_id": row["candidate_id"],
            "workload_case_id": row["workload_case_id"],
            "trusted_accelerated_numeric_source": True,
        }
        for row in requirements["rows"]
    ]
    index = {
        "selected_row_count": 2,
        "passed_row_count": 2,
        "blocked_row_count": 0,
        "evidence_bundle_row_count": 2,
        "evidence_bundle_blockers": [],
    }
    bundle = {"row_count": 2, "rows": bundle_rows, "blockers": []}

    checks = validate_qe_producer_counts(
        requirements=requirements,
        producer_index=index,
        evidence_bundle=bundle,
    )
    assert checks["expected_row_count"] == 2

    blocked_index = dict(index, passed_row_count=1, blocked_row_count=1)
    with pytest.raises(ValueError, match="did not pass every"):
        validate_qe_producer_counts(
            requirements=requirements,
            producer_index=blocked_index,
            evidence_bundle=bundle,
        )
    blocked_bundle = dict(bundle, blockers=["missing_l4_proof"])
    with pytest.raises(ValueError, match="still contains blockers"):
        validate_qe_producer_counts(
            requirements=requirements,
            producer_index=index,
            evidence_bundle=blocked_bundle,
        )



def test_validate_producer_counts_rejects_missing_native_hpsi_sidecar_counters() -> None:
    requirements = remap_qe_accelerated_numeric_requirements(
        _requirements(),
        source_requirements_path=f"{OLD_ROOT}/qe_accelerated_numeric_evidence_requirements.json",
        output_requirements_path="runs/dse/qe_l4_full_trusted/qe_accelerated_numeric_evidence_requirements.v2.json",
        output_root="runs/dse/qe_l4_full_trusted",
    )
    row = requirements["rows"][0]
    bundle_row = {
        "candidate_id": row["candidate_id"],
        "workload_case_id": row["workload_case_id"],
        "trusted_accelerated_numeric_source": True,
        "offload_provenance": {
            "producer": "gem5_generic_accel_qe_hpsi_systemc_native_payload",
            "kernel_id": "h_psi",
            "trusted_payload_kind": "systemc_generic_accel_model_l4_offload_kernel_numerical",
        },
        "kernel_evidence": [
            {
                "kernel_id": "h_psi",
                "source": "gem5_generic_accel_qe_hpsi_systemc_native_payload",
            }
        ],
    }
    index = {
        "selected_row_count": 1,
        "passed_row_count": 1,
        "blocked_row_count": 0,
        "evidence_bundle_row_count": 1,
        "evidence_bundle_blockers": [],
    }
    bundle = {"row_count": 1, "rows": [bundle_row], "blockers": []}
    single_req = dict(requirements, row_count=1, rows=[row])

    with pytest.raises(ValueError, match="h_psi sidecar consumption counters invalid"):
        validate_qe_producer_counts(
            requirements=single_req,
            producer_index=index,
            evidence_bundle=bundle,
        )

    counters = {
        "sidecar_observed_hpsi_calls": 2,
        "sidecar_attempted_hpsi_calls": 2,
        "sidecar_consumed_hpsi_calls": 2,
        "sidecar_failed_hpsi_calls": 0,
        "all_observed_hpsi_calls_sidecar_consumed": True,
        "single_hpsi_call_smoke_only": False,
    }
    bundle_row["offload_provenance"].update(counters)
    bundle_row["kernel_evidence"][0].update(counters)
    checks = validate_qe_producer_counts(
        requirements=single_req,
        producer_index=index,
        evidence_bundle=bundle,
    )
    assert checks["passed_row_count"] == 1

def test_build_and_validate_admissibility_ledger_hash_record(tmp_path: Path) -> None:
    source_requirements_path = tmp_path / "v1" / "qe_accelerated_numeric_evidence_requirements.json"
    requirements_path = tmp_path / "trusted" / "qe_accelerated_numeric_evidence_requirements.v2.json"
    index_path = tmp_path / "trusted" / "qe_accelerated_numeric_producer_index.json"
    bundle_path = tmp_path / "trusted" / "qe_accelerated_numeric_producer_evidence_bundle.json"
    _write_json(source_requirements_path, _requirements())
    remapped = write_remapped_qe_accelerated_numeric_requirements(
        source_requirements_path=source_requirements_path,
        output_requirements_path=requirements_path,
        output_root=tmp_path / "trusted",
    )
    _write_json(index_path, {"selected_row_count": remapped["row_count"]})
    _write_json(bundle_path, {"row_count": remapped["row_count"], "rows": remapped["rows"], "blockers": []})

    ledger = build_qe_admissibility_ledger(
        run_dir=tmp_path / "trusted",
        bundle_path=bundle_path,
        producer_index_path=index_path,
        requirements_path=requirements_path,
        source_requirements_path=source_requirements_path,
        writable_output_root=tmp_path / "trusted",
        producer_command=["python3", "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py"],
        campaign_id="system-restructure-full-closure",
        environment={"python": "test", "cwd": str(tmp_path)},
        git_revision="testrev",
    )

    assert ledger["status"] == "final_admissible"
    assert ledger["trial_row_count"] == 2
    assert ledger["workload_case_count"] == 2
    validate_qe_admissibility_ledger(
        ledger,
        bundle_path=bundle_path,
        producer_index_path=index_path,
        requirements_path=requirements_path,
        source_requirements_path=source_requirements_path,
    )

    tampered = dict(ledger, bundle_sha256="0" * 64)
    with pytest.raises(ValueError, match="bundle_sha256"):
        validate_qe_admissibility_ledger(
            tampered,
            bundle_path=bundle_path,
            producer_index_path=index_path,
            requirements_path=requirements_path,
            source_requirements_path=source_requirements_path,
        )


def test_write_and_validate_admissibility_ledger_hash_binds_extra_artifacts(tmp_path: Path) -> None:
    source_requirements_path = tmp_path / "v1" / "qe_accelerated_numeric_evidence_requirements.json"
    requirements_path = tmp_path / "trusted" / "qe_accelerated_numeric_evidence_requirements.v2.json"
    index_path = tmp_path / "trusted" / "qe_accelerated_numeric_producer_index.json"
    bundle_path = tmp_path / "trusted" / "qe_accelerated_numeric_producer_evidence_bundle.json"
    ledger_path = tmp_path / "trusted" / "admissibility_ledger.json"
    _write_json(source_requirements_path, _requirements())
    remapped = write_remapped_qe_accelerated_numeric_requirements(
        source_requirements_path=source_requirements_path,
        output_requirements_path=requirements_path,
        output_root=tmp_path / "trusted",
    )
    _write_json(index_path, {"selected_row_count": remapped["row_count"]})
    _write_json(bundle_path, {"row_count": remapped["row_count"], "rows": remapped["rows"], "blockers": []})

    native_payload_executable = tmp_path / "native" / "hpsi_payload"
    native_payload_source = tmp_path / "native" / "hpsi_payload.c"
    native_wrapper_script = tmp_path / "native" / "run_native_hpsi.sh"
    gem5_config = tmp_path / "gem5" / "generic_accel.py"
    gem5_driver = tmp_path / "gem5" / "generic_accel_driver.c"
    sidecar_simulator = tmp_path / "sidecar" / "native_hpsi_sidecar.py"
    accelerated_qe_binary_manifest = tmp_path / "qe" / "accelerated_qe_binary_manifest.json"
    _write_text(native_payload_executable, "ELF payload bytes\n")
    _write_text(native_payload_source, "int main(void) { return 0; }\n")
    _write_text(native_wrapper_script, "#!/usr/bin/env bash\nexec ./hpsi_payload \"$@\"\n")
    _write_text(gem5_config, "GenericAccel config\n")
    _write_text(gem5_driver, "GenericAccel driver\n")
    _write_text(sidecar_simulator, "native sidecar simulator\n")
    _write_json(
        accelerated_qe_binary_manifest,
        {
            "qe_binary": "pw.x",
            "qe_binary_sha256": "1" * 64,
            "plugin_binary_sha256": "2" * 64,
        },
    )
    extra_artifact_paths = {
        "native_payload_executable": native_payload_executable,
        "native_payload_source": native_payload_source,
        "native_wrapper_script": native_wrapper_script,
        "gem5_config": gem5_config,
        "gem5_driver": gem5_driver,
        "sidecar_simulator": sidecar_simulator,
        "accelerated_qe_binary_manifest": accelerated_qe_binary_manifest,
    }

    ledger = write_qe_admissibility_ledger(
        ledger_path,
        run_dir=tmp_path / "trusted",
        bundle_path=bundle_path,
        producer_index_path=index_path,
        requirements_path=requirements_path,
        source_requirements_path=source_requirements_path,
        writable_output_root=tmp_path / "trusted",
        producer_command=["python3", "dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py"],
        campaign_id="system-restructure-full-closure",
        environment={"python": "test", "cwd": str(tmp_path)},
        git_revision="testrev",
        extra_artifact_paths=extra_artifact_paths,
    )

    assert ledger_path.exists()
    assert set(ledger["extra_artifacts"]) == set(extra_artifact_paths)
    for label in extra_artifact_paths:
        assert ledger["extra_artifacts"][label]["path"] == extra_artifact_paths[label].as_posix()
        assert len(ledger["extra_artifacts"][label]["sha256"]) == 64
        assert ledger[f"{label}_path"] == ledger["extra_artifacts"][label]["path"]
        assert ledger[f"{label}_sha256"] == ledger["extra_artifacts"][label]["sha256"]
    validated_hashes = validate_qe_admissibility_ledger(
        ledger,
        bundle_path=bundle_path,
        producer_index_path=index_path,
        requirements_path=requirements_path,
        source_requirements_path=source_requirements_path,
        extra_artifact_paths=extra_artifact_paths,
    )
    assert validated_hashes["native_payload_executable_sha256"] == ledger["native_payload_executable_sha256"]
    assert (
        validated_hashes["accelerated_qe_binary_manifest_sha256"]
        == ledger["accelerated_qe_binary_manifest_sha256"]
    )

    _write_text(native_wrapper_script, "#!/usr/bin/env bash\nexit 42\n")
    with pytest.raises(ValueError, match="native_wrapper_script_sha256"):
        validate_qe_admissibility_ledger(
            ledger,
            bundle_path=bundle_path,
            producer_index_path=index_path,
            requirements_path=requirements_path,
            source_requirements_path=source_requirements_path,
            extra_artifact_paths=extra_artifact_paths,
        )
