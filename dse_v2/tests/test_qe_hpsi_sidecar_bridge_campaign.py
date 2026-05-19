"""Tests for QE h_psi sidecar bridge campaign runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


CAMPAIGN = Path("dse_v2/scripts/dse/run_qe_hpsi_sidecar_bridge_campaign.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_hpsi_sidecar_bridge_campaign_runs_available_rows_and_preserves_blockers(tmp_path: Path) -> None:
    row_dir = tmp_path / "campaign" / "cand" / "qe_case"
    snapshot = row_dir / "kernel_boundary_snapshot.json"
    arrays = row_dir / "kernel_boundary_arrays.json"
    baseline = tmp_path / "baseline_comparison.json"
    accelerated_stdout = row_dir / "accelerated_qe.stdout.log"
    simulator = tmp_path / "fake_generic_sim.py"
    requirements = tmp_path / "requirements.json"
    out_index = tmp_path / "campaign_index.json"

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
    _write_json(
        requirements,
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
            "rows": [
                {
                    "candidate_id": "cand",
                    "workload_case_id": "qe_case",
                    "baseline_comparison": str(baseline),
                    "evidence_output": str(row_dir / "qe_accelerated_numeric_evidence.json"),
                    "required_outputs": {
                        "accelerated_stdout": str(accelerated_stdout),
                        "kernel_boundary_snapshot_json": str(snapshot),
                        "kernel_boundary_arrays_json": str(arrays),
                        "kernel_evidence_json": str(row_dir / "kernel_evidence.json"),
                        "offload_provenance_json": str(row_dir / "offload_provenance.json"),
                    },
                },
                {
                    "candidate_id": "missing",
                    "workload_case_id": "qe_case",
                    "baseline_comparison": str(tmp_path / "missing_baseline.json"),
                    "evidence_output": str(tmp_path / "missing" / "qe_accelerated_numeric_evidence.json"),
                    "required_outputs": {
                        "accelerated_stdout": str(tmp_path / "missing.out"),
                        "kernel_boundary_snapshot_json": str(tmp_path / "missing_snapshot.json"),
                        "kernel_boundary_arrays_json": str(tmp_path / "missing_arrays.json"),
                    },
                },
            ],
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(CAMPAIGN),
            "--requirements",
            str(requirements),
            "--simulator",
            str(simulator),
            "--out-index",
            str(out_index),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    index = json.loads(out_index.read_text(encoding="utf-8"))
    evidence = json.loads((row_dir / "qe_accelerated_numeric_evidence.json").read_text(encoding="utf-8"))
    assert index["selected_row_count"] == 2
    assert index["passed_foundation_row_count"] == 1
    assert index["blocked_row_count"] == 1
    assert index["trusted_row_count"] == 0
    assert index["rows"][0]["status"] == "passed_foundation_blocked_for_trusted_correctness"
    assert any(str(item).startswith("missing_hpsi_sidecar_input:") for item in index["rows"][1]["blockers"])
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert "hpsi_sidecar_boundary_probe_not_full_kernel_recompute" in evidence["blockers"]
