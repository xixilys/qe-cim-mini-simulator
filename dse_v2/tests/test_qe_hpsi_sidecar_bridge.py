"""Tests for QE h_psi GenericAccel/SystemC sidecar bridge evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SIDECAR = Path("dse_v2/scripts/dse/run_qe_hpsi_sidecar_bridge.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_hpsi_sidecar_detects_full_component_model_without_trusting_l4() -> None:
    from dse_v2.scripts.dse.run_qe_hpsi_sidecar_bridge import _has_full_hpsi_component_model

    assert _has_full_hpsi_component_model(
        {
            "kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "h_psi_boundary_norm_transport_probe",
                    "full_kernel_recomputed": False,
                    "boundary_norm_probe_only": True,
                    "source": "gem5_generic_accel_qe_extension",
                },
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "boundary_norm_probe_only": False,
                    "source": "python_qe_hpsi_component_model",
                },
            ]
        }
    )
    assert not _has_full_hpsi_component_model(
        {
            "kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "boundary_norm_probe_only": False,
                    "source": "qe_host_stage_reference_capture",
                }
            ]
        }
    )


def test_hpsi_sidecar_bridge_emits_foundation_evidence_but_not_trusted(tmp_path: Path) -> None:
    snapshot = tmp_path / "kernel_boundary_snapshot.json"
    arrays = tmp_path / "kernel_boundary_arrays.json"
    baseline = tmp_path / "baseline_comparison.json"
    accelerated_stdout = tmp_path / "accelerated_qe.stdout.log"
    simulator = tmp_path / "fake_generic_sim.py"
    out_dir = tmp_path / "sidecar"

    _write_json(
        snapshot,
        {
            "schema_version": "dse.qe_hpsi_kernel_boundary_snapshot.v1",
            "kernel_id": "h_psi",
            "dimensions": {"lda": 4, "n": 4, "m": 1},
            "psi_l2_norm": 1.0,
            "hpsi_l2_norm": 2.0,
            "hpsi_abs_sum": 4.0,
        },
    )
    _write_json(
        arrays,
        {
            "schema_version": "dse.qe_hpsi_kernel_boundary_arrays.v1",
            "kernel_id": "h_psi",
            "dimensions": {"lda": 4, "n": 4, "m": 1},
            "npol": 1,
            "array_order": "fortran_column_major_band_then_row",
            "g2kin": [2.0, 3.0, 4.0, 5.0],
            "psi_real_imag": [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 0.0]],
            "hpsi_kinetic_reference_real_imag": [[2.0, 0.0], [0.0, 3.0], [4.0, 4.0], [10.0, 0.0]],
            "hpsi_after_vloc_reference_real_imag": [[2.0, 0.0], [0.0, 3.0], [4.0, 4.0], [10.0, 0.0]],
            "hpsi_after_vnl_reference_real_imag": [[2.0, 0.0], [0.0, 3.0], [4.0, 4.0], [10.0, 0.0]],
            "hpsi_reference_real_imag": [[2.0, 0.0], [0.0, 3.0], [4.0, 4.0], [10.0, 0.0]],
        },
    )
    _write_json(
        baseline,
        {
            "schema_version": "dse.qe_pure_software_baseline_result.v1",
            "case_id": "qe_case",
            "performance_metrics": {
                "terminal_step_metrics": {
                    "total_energy_ry": -10.0,
                    "highest_occupied_ev": 1.0,
                    "lowest_unoccupied_ev": 2.0,
                }
            },
        },
    )
    accelerated_stdout.write_text(
        "!    total energy              =     -10.00000000 Ry\n"
        "     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000\n",
        encoding="utf-8",
    )
    simulator.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "request = sys.argv[sys.argv.index('--request') + 1]\n"
        "result = sys.argv[sys.argv.index('--result') + 1]\n"
        "payload = json.load(open(request, encoding='utf-8'))\n"
        "json.dump({'schema_version':'gsim.result.v1','run_id':payload['run_id'],'status':'passed','metrics':{'latency_ms':0.001},'events':[{'node_id':'hpsi_boundary_norm_probe','device':'generic_accel_0','op_type':'reduction'}]}, open(result, 'w', encoding='utf-8'))\n",
        encoding="utf-8",
    )
    simulator.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(SIDECAR),
            "--candidate-id",
            "cand",
            "--workload-case-id",
            "qe_case",
            "--snapshot",
            str(snapshot),
            "--boundary-arrays",
            str(arrays),
            "--baseline-comparison",
            str(baseline),
            "--accelerated-stdout",
            str(accelerated_stdout),
            "--out-dir",
            str(out_dir),
            "--simulator",
            str(simulator),
            "--fail-on-trusted",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    index = json.loads((out_dir / "hpsi_sidecar_bridge_index.json").read_text(encoding="utf-8"))
    evidence = json.loads((out_dir / "qe_accelerated_numeric_evidence.json").read_text(encoding="utf-8"))
    request = json.loads((out_dir / "simulation_request.json").read_text(encoding="utf-8"))
    kinetic = json.loads((out_dir / "hpsi_kinetic_component_result.json").read_text(encoding="utf-8"))
    vloc = json.loads((out_dir / "hpsi_vloc_component_result.json").read_text(encoding="utf-8"))
    vnl = json.loads((out_dir / "hpsi_vnl_component_result.json").read_text(encoding="utf-8"))
    stages = json.loads((out_dir / "hpsi_stage_decomposition.json").read_text(encoding="utf-8"))
    closure = json.loads((out_dir / "hpsi_component_closure_report.json").read_text(encoding="utf-8"))
    targets = json.loads((out_dir / "hpsi_component_target_arrays.json").read_text(encoding="utf-8"))

    assert index["status"] == "passed_foundation_blocked_for_trusted_correctness"
    assert request["mapping"]["hpsi_boundary_norm_probe"] == "generic_accel_0"
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "hpsi_sidecar_boundary_probe_not_full_kernel_recompute" in evidence["blockers"]
    assert "missing_required_full_h_psi_kernel_evidence" in evidence["blockers"]
    assert evidence["hpsi_sidecar_result"]["boundary_norm_probe_only"] is True
    assert kinetic["status"] == "passed"
    assert kinetic["kernel_scope"] == "partial_h_psi_kinetic_component"
    assert kinetic["qe_kinetic_reference_available"] is True
    assert kinetic["qe_kinetic_reference_max_abs_error"] == 0.0
    assert vloc["status"] == "blocked"
    assert vloc["kernel_scope"] == "partial_h_psi_vloc_delta_component"
    assert vnl["status"] == "blocked"
    assert vnl["kernel_scope"] == "partial_h_psi_vnl_delta_component"
    assert stages["status"] == "passed"
    assert closure["status"] == "blocked_until_all_components_computed"
    assert closure["missing_compute_components"] == [
        "local_potential_vloc_delta",
        "nonlocal_potential_vnl_delta",
    ]
    assert targets["status"] == "passed"
    assert targets["component_summaries"]["vloc_delta_reference_real_imag"]["element_count"] == 4
    assert targets["component_summaries"]["vnl_delta_reference_real_imag"]["element_count"] == 4
    assert len(evidence["kernel_evidence"]) == 5
    assert evidence["kernel_evidence"][1]["kernel_id"] == "h_psi_kinetic_component"
    assert evidence["kernel_evidence"][1]["error_metric"] == "qe_kinetic_stage_reference"
    assert evidence["kernel_evidence"][2]["kernel_id"] == "h_psi_stage_decomposition"
    assert evidence["kernel_evidence"][3]["kernel_id"] == "h_psi_vloc_delta_component"
    assert evidence["kernel_evidence"][4]["kernel_id"] == "h_psi_vnl_delta_component"
    assert evidence["accelerated_reference"]["hpsi_kinetic_component_result_json"].endswith(
        "hpsi_kinetic_component_result.json"
    )
    assert evidence["accelerated_reference"]["hpsi_vloc_component_result_json"].endswith(
        "hpsi_vloc_component_result.json"
    )
    assert evidence["accelerated_reference"]["hpsi_vnl_component_result_json"].endswith(
        "hpsi_vnl_component_result.json"
    )
    assert evidence["accelerated_reference"]["hpsi_stage_decomposition_json"].endswith(
        "hpsi_stage_decomposition.json"
    )
    assert evidence["accelerated_reference"]["hpsi_component_closure_report_json"].endswith(
        "hpsi_component_closure_report.json"
    )
    assert evidence["accelerated_reference"]["hpsi_component_target_arrays_json"].endswith(
        "hpsi_component_target_arrays.json"
    )
