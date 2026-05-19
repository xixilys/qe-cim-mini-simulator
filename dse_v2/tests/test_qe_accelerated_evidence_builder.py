"""Tests for audited QE accelerated numeric evidence collection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.qe_accelerated_evidence import (
    build_qe_accelerated_numeric_evidence,
    parse_qe_stdout_metrics,
    validate_kernel_numeric_evidence,
)


BUILDER = Path("dse_v2/scripts/dse/build_qe_accelerated_numeric_evidence.py")
CAMPAIGN = Path("dse_v2/scripts/dse/collect_qe_accelerated_numeric_evidence_campaign.py")


def _baseline() -> dict:
    return {
        "schema_version": "dse.qe_pure_software_baseline_result.v1",
        "case_id": "qe_case",
        "pure_software_qe_baseline": True,
        "performance_metrics": {
            "terminal_step_metrics": {
                "total_energy_ry": -10.0,
                "highest_occupied_ev": 1.0,
                "lowest_unoccupied_ev": 2.0,
            }
        },
    }


def _trusted_provenance(**overrides) -> dict:
    payload = {
        "producer": "qe-offload-test",
        "accelerated_runtime": "qe_offload_runtime",
        "offload_target": "gem5_generic_accel",
        "full_h_psi_recomputed": True,
        "qe_mainflow_integrated": True,
        "accelerated_results_consumed_by_qe": True,
        "l4_execution_proof": {
            "passed": True,
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
        },
    }
    payload.update(overrides)
    return payload


def test_parse_qe_stdout_metrics_extracts_energy_and_eigen_summary() -> None:
    metrics = parse_qe_stdout_metrics(
        """
!    total energy              =     -10.00000010 Ry
     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001
     Total force =     0.000123     Total SCF correction =     0.000000
          total   stress  (Ry/bohr**3)                   (kbar)     P=       27.34
"""
    )
    assert metrics["total_energy_ry"] == -10.00000010
    assert metrics["highest_occupied_ev"] == 1.000001
    assert metrics["lowest_unoccupied_ev"] == 2.000001
    assert metrics["total_force_ry_bohr"] == 0.000123
    assert metrics["pressure_kbar"] == 27.34


def test_builder_fills_multistage_baseline_metrics_and_relax_force_stress_from_stdout() -> None:
    baseline = {
        "schema_version": "dse.qe_pure_software_baseline_result.v1",
        "case_id": "qe_multistage",
        "pure_software_qe_baseline": True,
        "performance_metrics": {"terminal_step_metrics": {"job_done": True}},
        "steps": [
            {
                "step_id": "stage_00_scf",
                "metrics": {
                    "total_energy_ry": -10.0,
                    "highest_occupied_ev": 1.0,
                    "lowest_unoccupied_ev": 2.0,
                    "total_force_ry_bohr": 0.001,
                    "pressure_kbar": 27.34,
                },
            },
            {"step_id": "stage_01_bands", "metrics": {"job_done": True}},
        ],
    }
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_multistage",
        baseline_comparison=baseline,
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
            "     Total force =     0.001000     Total SCF correction =     0.000000\n"
            "          total   stress  (Ry/bohr**3)                   (kbar)     P=       27.34\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "absolute_error": 1.0e-12,
                "relative_error": 1.0e-10,
            }
        ],
        provenance=_trusted_provenance(),
        density_residual=0.0,
    )

    assert evidence["physical_evidence"]["total_energy_error_ry"] == 0.0
    assert evidence["physical_evidence"]["eigenvalue_summary_error_ry"] == 0.0
    assert evidence["physical_evidence"]["force_error_ry_bohr"] == 0.0
    assert evidence["physical_evidence"]["stress_error_kbar"] == 0.0


def test_builder_blocks_trusted_source_without_offload_provenance() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout="!    total energy              =     -10.00000000 Ry\n",
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "absolute_error": 1.0e-12,
                "relative_error": 1.0e-10,
            }
        ],
        density_residual=1.0e-8,
    )
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert evidence["accelerated_output_status"] == "blocked"
    assert "missing_offload_provenance_for_trusted_source" in evidence["blockers"]


def test_builder_blocks_full_hpsi_replay_without_qe_mainflow_integration() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000010 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "absolute_error": 1.0e-12,
                "relative_error": 1.0e-10,
            }
        ],
        provenance={
            "producer": "component-replay-only",
            "accelerated_runtime": "qe_offload_runtime",
            "offload_target": "gem5_generic_accel",
            "full_h_psi_recomputed": True,
        },
        density_residual=1.0e-8,
    )

    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "offload_provenance_missing_qe_mainflow_integrated_true" in evidence["blockers"]
    assert "offload_provenance_missing_accelerated_results_consumed_by_qe_true" in evidence["blockers"]
    assert "offload_provenance_missing_l4_execution_proof" in evidence["blockers"]


def test_builder_blocks_failed_or_incomplete_l4_execution_proof() -> None:
    for provenance, expected_blocker in [
        (
            _trusted_provenance(l4_execution_proof={"passed": False, "transport_harness": "gem5_generic_accel_microarchitecture_v1"}),
            "offload_provenance_l4_execution_proof_not_passed",
        ),
        (
            _trusted_provenance(l4_execution_proof={"passed": True, "transport_harness": ""}),
            "offload_provenance_l4_execution_proof_missing_transport_harness",
        ),
    ]:
        evidence = build_qe_accelerated_numeric_evidence(
            candidate_id="cand",
            workload_case_id="qe_case",
            baseline_comparison=_baseline(),
            accelerated_stdout=(
                "!    total energy              =     -10.00000010 Ry\n"
                "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n"
            ),
            source_kind="qe_offload_runtime",
            kernel_evidence=[
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 1.0e-12,
                    "relative_error": 1.0e-10,
                }
            ],
            provenance=provenance,
            density_residual=1.0e-8,
        )

        assert evidence["trusted_accelerated_numeric_source"] is False
        assert expected_blocker in evidence["blockers"]


def test_builder_blocks_reference_assisted_mainflow_consumption_smoke() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": False,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "host_stage_reference_assisted": True,
                "component_model_reference_replay_only": True,
                "source": "qe_mainflow_hpsi_component_sidecar_reference_assisted",
            }
        ],
        provenance={
            "producer": "qe_hpsi_mainflow_component_sidecar_patch",
            "accelerated_runtime": "qe_offload_runtime",
            "offload_target": "python_component_sidecar_reference_assisted",
            "full_h_psi_recomputed": False,
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "host_stage_reference_assisted": True,
            "component_model_reference_replay_only": True,
            "l4_execution_proof": {
                "passed": False,
                "transport_harness": "python_component_sidecar_not_l4",
            },
        },
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "offload_provenance_missing_qe_mainflow_integrated_true" not in evidence["blockers"]
    assert "offload_provenance_missing_accelerated_results_consumed_by_qe_true" not in evidence["blockers"]
    assert "offload_provenance_marks_host_stage_reference_assisted" in evidence["blockers"]
    assert "offload_provenance_marks_component_model_reference_replay_only" in evidence["blockers"]
    assert "kernel_evidence_marks_host_stage_reference_assisted:0" in evidence["blockers"]
    assert "kernel_evidence_marks_component_model_reference_replay_only:0" in evidence["blockers"]
    assert "offload_provenance_l4_execution_proof_not_passed" in evidence["blockers"]
    assert "missing_required_full_h_psi_kernel_evidence" in evidence["blockers"]


def test_builder_blocks_software_component_model_without_l4_even_when_full_hpsi_consumed() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "software_component_model_not_l4": True,
                "single_hpsi_call_smoke_only": True,
                "source": "python_qe_hpsi_component_model",
            }
        ],
        provenance={
            "producer": "qe_hpsi_mainflow_component_sidecar_patch",
            "accelerated_runtime": "qe_offload_runtime",
            "offload_target": "python_component_sidecar",
            "full_h_psi_recomputed": True,
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "software_component_model_not_l4": True,
            "single_hpsi_call_smoke_only": True,
            "l4_execution_proof": {
                "passed": False,
                "transport_harness": "python_component_sidecar_not_l4",
            },
        },
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "offload_provenance_missing_full_h_psi_recomputed_true" not in evidence["blockers"]
    assert "missing_required_full_h_psi_kernel_evidence" not in evidence["blockers"]
    assert "offload_provenance_marks_software_component_model_not_l4" in evidence["blockers"]
    assert "kernel_evidence_marks_software_component_model_not_l4:0" in evidence["blockers"]
    assert "offload_provenance_marks_single_hpsi_call_smoke_only" in evidence["blockers"]
    assert "kernel_evidence_marks_single_hpsi_call_smoke_only:0" in evidence["blockers"]
    assert "offload_provenance_l4_execution_proof_not_passed" in evidence["blockers"]



def test_builder_blocks_native_hpsi_sidecar_when_consumption_counters_are_missing() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "full_h_psi_recomputed": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "gem5_generic_accel_qe_hpsi_systemc_native_payload",
                "software_component_model_not_l4": False,
                "single_hpsi_call_smoke_only": False,
            }
        ],
        provenance=_trusted_provenance(
            producer="gem5_generic_accel_qe_hpsi_systemc_native_payload",
            offload_target="gem5_generic_accel_qe_hpsi_systemc_native_payload",
            trusted_payload_kind="systemc_generic_accel_model_l4_offload_kernel_numerical",
            software_component_model_not_l4=False,
            single_hpsi_call_smoke_only=False,
        ),
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "offload_provenance_missing_sidecar_observed_hpsi_calls" in evidence["blockers"]
    assert "offload_provenance_missing_all_observed_hpsi_calls_sidecar_consumed_true" in evidence["blockers"]
    assert "kernel_evidence:0_missing_sidecar_observed_hpsi_calls" in evidence["blockers"]
    assert "kernel_evidence:0_missing_all_observed_hpsi_calls_sidecar_consumed_true" in evidence["blockers"]


def test_builder_trusts_native_hpsi_sidecar_only_with_consumption_counters() -> None:
    counters = {
        "sidecar_observed_hpsi_calls": 2,
        "sidecar_attempted_hpsi_calls": 2,
        "sidecar_consumed_hpsi_calls": 2,
        "sidecar_failed_hpsi_calls": 0,
        "all_observed_hpsi_calls_sidecar_consumed": True,
        "single_hpsi_call_smoke_only": False,
    }
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "full_h_psi_recomputed": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "gem5_generic_accel_qe_hpsi_systemc_native_payload",
                "software_component_model_not_l4": False,
                **counters,
            }
        ],
        provenance=_trusted_provenance(
            producer="gem5_generic_accel_qe_hpsi_systemc_native_payload",
            offload_target="gem5_generic_accel_qe_hpsi_systemc_native_payload",
            trusted_payload_kind="systemc_generic_accel_model_l4_offload_kernel_numerical",
            software_component_model_not_l4=False,
            **counters,
        ),
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is True
    assert evidence["blockers"] == []

def test_builder_emits_trusted_evidence_only_with_provenance_and_required_deltas(tmp_path: Path) -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000010 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "absolute_error": 1.0e-12,
                "relative_error": 1.0e-10,
            }
        ],
        provenance=_trusted_provenance(),
        density_residual=1.0e-8,
    )
    assert evidence["trusted_accelerated_numeric_source"] is True
    assert evidence["accelerated_output_status"] == "passed"
    assert evidence["blockers"] == []
    assert evidence["physical_evidence"]["total_energy_error_ry"] < 1.1e-7
    assert evidence["physical_evidence"]["eigenvalue_summary_error_ry"] < 1.0e-6

    baseline_path = tmp_path / "baseline.json"
    accelerated_stdout = tmp_path / "accelerated.out"
    kernel_path = tmp_path / "kernel.json"
    provenance_path = tmp_path / "provenance.json"
    out_path = tmp_path / "evidence.json"
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    accelerated_stdout.write_text(
        "!    total energy              =     -10.00000010 Ry\n"
        "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n",
        encoding="utf-8",
    )
    kernel_path.write_text(
        json.dumps(
            [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 1.0e-12,
                    "relative_error": 1.0e-10,
                }
            ]
        ),
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps(
            _trusted_provenance()
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--candidate-id",
            "cand",
            "--workload-case-id",
            "qe_case",
            "--baseline-comparison",
            str(baseline_path),
            "--accelerated-stdout",
            str(accelerated_stdout),
            "--source-kind",
            "qe_offload_runtime",
            "--kernel-evidence",
            str(kernel_path),
            "--offload-provenance",
            str(provenance_path),
            "--density-residual",
            "1e-8",
            "--out",
            str(out_path),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["trusted_accelerated_numeric_source"] is True


def test_non_hpsi_full_kernel_evidence_is_not_forced_through_hpsi_gate() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000000 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n"
        ),
        source_kind="qe_offload_runtime",
        kernel_evidence=[
            {
                "kernel_id": "s_psi",
                "kernel_scope": "full_s_psi",
                "full_kernel_recomputed": True,
                "accelerated_results_consumed_by_qe": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "qe_offload_runtime",
            }
        ],
        provenance=_trusted_provenance(
            target_kernel="s_psi",
            full_h_psi_recomputed=False,
            full_kernel_recomputed=True,
        ),
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is True
    assert "missing_required_full_h_psi_kernel_evidence" not in evidence["blockers"]
    assert "offload_provenance_missing_full_h_psi_recomputed_true" not in evidence["blockers"]
    assert "missing_required_full_kernel_evidence" not in evidence["blockers"]


def test_kernel_evidence_allows_auxiliary_boundary_row_when_full_hpsi_row_exists() -> None:
    blockers = validate_kernel_numeric_evidence(
        [
            {
                "kernel_id": "h_psi",
                "kernel_scope": "h_psi_boundary_norm_transport_probe",
                "full_kernel_recomputed": False,
                "boundary_norm_probe_only": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "gem5_generic_accel_qe_extension",
            },
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "boundary_norm_probe_only": False,
                "absolute_error": 1.0e-14,
                "relative_error": 1.0e-15,
                "source": "qe_offload_runtime",
            },
        ]
    )

    assert blockers == []


def test_campaign_collector_builds_rows_from_requirements_manifest(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    accel_stdout = tmp_path / "campaign" / "cand" / "qe_case" / "accelerated_qe.stdout.log"
    kernel_path = tmp_path / "campaign" / "cand" / "qe_case" / "kernel_evidence.json"
    provenance_path = tmp_path / "campaign" / "cand" / "qe_case" / "offload_provenance.json"
    requirements_path = tmp_path / "requirements.json"
    out_dir = tmp_path / "evidence"
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    accel_stdout.parent.mkdir(parents=True)
    accel_stdout.write_text(
        "!    total energy              =     -10.00000010 Ry\n"
        "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n",
        encoding="utf-8",
    )
    kernel_path.write_text(
        json.dumps(
            [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 1.0e-12,
                    "relative_error": 1.0e-10,
                }
            ]
        ),
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps(
            _trusted_provenance(physical_evidence={"density_residual": 1.0e-8})
        ),
        encoding="utf-8",
    )
    requirements_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
                "rows": [
                    {
                        "candidate_id": "cand",
                        "workload_case_id": "qe_case",
                        "baseline_comparison": str(baseline_path),
                        "required_outputs": {
                            "accelerated_stdout": str(accel_stdout),
                            "kernel_evidence_json": str(kernel_path),
                            "offload_provenance_json": str(provenance_path),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(CAMPAIGN),
            "--requirements",
            str(requirements_path),
            "--out-dir",
            str(out_dir),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    index = json.loads((out_dir / "qe_accelerated_numeric_evidence_campaign_index.json").read_text(encoding="utf-8"))
    evidence = json.loads((out_dir / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(encoding="utf-8"))
    assert index["trusted_row_count"] == 1
    assert index["blocked_row_count"] == 0
    assert evidence["trusted_accelerated_numeric_source"] is True


def test_builder_blocks_boundary_probe_without_full_hpsi_recompute() -> None:
    evidence = build_qe_accelerated_numeric_evidence(
        candidate_id="cand",
        workload_case_id="qe_case",
        baseline_comparison=_baseline(),
        accelerated_stdout=(
            "!    total energy              =     -10.00000010 Ry\n"
            "     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001\n"
        ),
        source_kind="gem5_generic_accel_qe_extension",
        kernel_evidence=[
            {
                "kernel_id": "h_psi",
                "kernel_scope": "h_psi_boundary_norm_transport_probe",
                "full_kernel_recomputed": False,
                "boundary_norm_probe_only": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "gem5_generic_accel_qe_extension",
            }
        ],
        provenance={
            "producer": "sidecar-test",
            "accelerated_runtime": "gem5_generic_accel_qe_extension",
            "offload_target": "generic_systemc_bridge",
            "full_h_psi_recomputed": False,
            "boundary_norm_probe_only": True,
        },
        density_residual=0.0,
    )

    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "kernel_evidence_boundary_norm_probe_only:0" in evidence["blockers"]
    assert "missing_required_full_h_psi_kernel_evidence" in evidence["blockers"]
    assert "offload_provenance_missing_full_h_psi_recomputed_true" in evidence["blockers"]


def test_campaign_collector_preserves_missing_inputs_as_blocked_rows(tmp_path: Path) -> None:
    requirements_path = tmp_path / "requirements.json"
    out_dir = tmp_path / "evidence"
    requirements_path.write_text(
        json.dumps(
            {
                "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
                "rows": [
                    {
                        "candidate_id": "cand",
                        "workload_case_id": "qe_case",
                        "baseline_comparison": str(tmp_path / "missing_baseline.json"),
                        "required_outputs": {
                            "accelerated_stdout": str(tmp_path / "missing.out"),
                            "kernel_evidence_json": str(tmp_path / "missing_kernel.json"),
                            "offload_provenance_json": str(tmp_path / "missing_provenance.json"),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(CAMPAIGN), "--requirements", str(requirements_path), "--out-dir", str(out_dir)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads((out_dir / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(encoding="utf-8"))
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert any(str(item).startswith("missing_required_campaign_input:") for item in evidence["blockers"])
