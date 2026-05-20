#!/usr/bin/env python3
"""DFT full-SCF evaluated-hybrid descriptor/cost helper tests."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    FULL_SCF_HYBRID_ARTIFACT_NAMES,
    MAJOR_SCF_ACCELERATED_KERNEL_IDS,
    REQUIRED_HOST_BOUND_PHASE_IDS,
    REQUIRED_OVERHEAD_PHASE_IDS,
    DftFullScfHybridValidationError,
    build_full_scf_evaluated_hybrid_payload,
    validate_full_scf_evaluated_hybrid_payload,
    write_full_scf_evaluated_hybrid_artifacts,
)


def _accelerated_costs() -> dict[str, float]:
    return {kernel_id: float(index) for index, kernel_id in enumerate(MAJOR_SCF_ACCELERATED_KERNEL_IDS, start=1)}


def _host_costs() -> dict[str, float]:
    return {
        "io": 1.0,
        "scf_control": 2.0,
        "convergence": 3.0,
        "diagonalization": 4.0,
        "mixing": 5.0,
    }


def _overhead_costs() -> dict[str, float]:
    return {
        "transfer": 0.5,
        "synchronization": 0.25,
        "queueing": 0.125,
        "layout": 0.75,
    }


def _valid_payload() -> dict:
    return build_full_scf_evaluated_hybrid_payload(
        candidate_id="cand-full-scf-hybrid",
        campaign_id="campaign-dft",
        workload_run_id="workload-six-scf",
        trial_id="trial-hybrid",
        accelerated_kernel_costs_s=_accelerated_costs(),
        host_bound_costs_s=_host_costs(),
        overhead_costs_s=_overhead_costs(),
        baseline_scf_time_s=100.0,
    )


def test_missing_host_bound_phase_fails_closed_before_descriptor_is_built():
    host_costs = _host_costs()
    del host_costs["mixing"]

    with pytest.raises(DftFullScfHybridValidationError, match="host_bound_costs_s missing required cost ids: mixing"):
        build_full_scf_evaluated_hybrid_payload(
            candidate_id="cand-missing-host",
            campaign_id="campaign-dft",
            workload_run_id="workload-six-scf",
            trial_id="trial-hybrid",
            accelerated_kernel_costs_s=_accelerated_costs(),
            host_bound_costs_s=host_costs,
            overhead_costs_s=_overhead_costs(),
        )


def test_missing_accelerated_kernel_fails_closed_before_descriptor_is_built():
    accelerated_costs = _accelerated_costs()
    del accelerated_costs["kinetic_add"]

    with pytest.raises(DftFullScfHybridValidationError, match="accelerated_kernel_costs_s missing required cost ids: kinetic_add"):
        build_full_scf_evaluated_hybrid_payload(
            candidate_id="cand-missing-kernel",
            campaign_id="campaign-dft",
            workload_run_id="workload-six-scf",
            trial_id="trial-hybrid",
            accelerated_kernel_costs_s=accelerated_costs,
            host_bound_costs_s=_host_costs(),
            overhead_costs_s=_overhead_costs(),
        )


def test_host_bound_phase_cannot_be_counted_as_hardware_acceleration():
    payload = _valid_payload()
    diagonalization = next(piece for piece in payload["schedule"] if piece.get("phase_id") == "diagonalization")
    diagonalization["hardware_acceleration_claim"] = True

    validation = validate_full_scf_evaluated_hybrid_payload(payload)

    assert validation["status"] == "blocked"
    assert "host_bound_phase_counted_as_acceleration" in validation["blocker_ids"]


def test_non_major_kernel_acceleration_claim_is_rejected():
    payload = _valid_payload()
    payload["schedule"].append(
        {
            "piece_id": "accelerated.diagonalization",
            "category": "accelerated_kernel",
            "phase_id": "diagonalization",
            "kernel_id": "diagonalization",
            "execution_target": "hardware_candidate",
            "cost_s": 1.0,
            "hardware_acceleration_claim": True,
        }
    )

    validation = validate_full_scf_evaluated_hybrid_payload(payload)

    assert validation["status"] == "blocked"
    assert "unsupported_accelerated_kernel" in validation["blocker_ids"]
    assert "host_bound_phase_counted_as_acceleration" in validation["blocker_ids"]


def test_valid_descriptor_includes_accelerated_host_and_overhead_schedule_pieces():
    payload = _valid_payload()

    assert payload["prototype_boundary"] == "full_scf_evaluated_hybrid"
    assert payload["device_residency"] == "host_orchestrated_hybrid"
    assert payload["completion_claim"] is False
    assert payload["validation"]["passed"] is True

    accelerated = {piece["kernel_id"] for piece in payload["schedule"] if piece["category"] == "accelerated_kernel"}
    host = {piece["phase_id"] for piece in payload["schedule"] if piece["category"] == "host_bound_phase"}
    overhead = {piece["overhead_id"] for piece in payload["schedule"] if piece["category"] == "runtime_overhead"}

    assert accelerated == set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert host == set(REQUIRED_HOST_BOUND_PHASE_IDS)
    assert overhead == set(REQUIRED_OVERHEAD_PHASE_IDS)
    assert all(piece["hardware_acceleration_claim"] is False for piece in payload["schedule"] if piece["category"] != "accelerated_kernel")
    assert payload["cost_model"]["accelerated_kernel_cost_s"] == sum(_accelerated_costs().values())
    assert payload["cost_model"]["host_bound_cost_s"] == sum(_host_costs().values())
    assert payload["cost_model"]["runtime_overhead_cost_s"] == sum(_overhead_costs().values())
    assert payload["cost_model"]["evaluated_hybrid_scf_time_s"] == pytest.approx(52.625)
    assert payload["cost_model"]["end_to_end_scf_evaluated_speedup"] == pytest.approx(100.0 / 52.625)


def test_full_scf_hybrid_artifact_bundle_writes_descriptor_schedule_residency_correctness_and_ppa(tmp_path):
    payload = _valid_payload()

    status = write_full_scf_evaluated_hybrid_artifacts(tmp_path, payload)

    assert status["status"] == "passed"
    assert status["completion_claim"] is False
    assert set(status["artifact_paths"].values()) == set(FULL_SCF_HYBRID_ARTIFACT_NAMES)
    for rel_path in FULL_SCF_HYBRID_ARTIFACT_NAMES:
        assert (tmp_path / rel_path).exists(), rel_path

    descriptor = json.loads((tmp_path / "full_scf_accelerator_descriptor.json").read_text(encoding="utf-8"))
    schedule = json.loads((tmp_path / "full_scf_runtime_schedule.json").read_text(encoding="utf-8"))
    residency = json.loads((tmp_path / "full_scf_data_residency_plan.json").read_text(encoding="utf-8"))
    correctness = json.loads((tmp_path / "full_scf_correctness_report.json").read_text(encoding="utf-8"))
    ppa = json.loads((tmp_path / "full_scf_ppa_summary.json").read_text(encoding="utf-8"))

    assert descriptor["validation"]["passed"] is True
    assert schedule["host_orchestrated"] is True
    assert set(schedule["accelerated_kernel_ids"]) == set(MAJOR_SCF_ACCELERATED_KERNEL_IDS)
    assert set(residency["host_resident_phase_ids"]) == set(REQUIRED_HOST_BOUND_PHASE_IDS)
    assert correctness["numerical_correctness_claim_eligible"] is False
    assert ppa["ppa_claim_eligible"] is False
    assert "not FPGA/ASIC PPA closure" in ppa["claim_boundary"]


def test_full_scf_hybrid_bundle_cli_requires_explicit_cost_files(tmp_path):
    accelerated_path = tmp_path / "accelerated_costs.json"
    host_path = tmp_path / "host_costs.json"
    overhead_path = tmp_path / "overhead_costs.json"
    accelerated_path.write_text(json.dumps(_accelerated_costs()), encoding="utf-8")
    host_path.write_text(json.dumps(_host_costs()), encoding="utf-8")
    overhead_path.write_text(json.dumps(_overhead_costs()), encoding="utf-8")
    out_dir = tmp_path / "bundle_cli"

    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_full_scf_hybrid_bundle.py",
            "--out",
            str(out_dir),
            "--candidate-id",
            "cand-full-scf-hybrid-cli",
            "--campaign-id",
            "campaign-dft",
            "--workload-run-id",
            "workload-six-scf",
            "--trial-id",
            "trial-hybrid",
            "--accelerated-kernel-costs-json",
            str(accelerated_path),
            "--host-bound-costs-json",
            str(host_path),
            "--overhead-costs-json",
            str(overhead_path),
            "--baseline-scf-time-s",
            "100.0",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0
    status = json.loads(completed.stdout)
    assert status["status"] == "passed"
    assert status["completion_claim"] is False
    assert (out_dir / "full_scf_accelerator_descriptor.json").exists()
    ppa = json.loads((out_dir / "full_scf_ppa_summary.json").read_text(encoding="utf-8"))
    assert ppa["ppa_claim_eligible"] is False
