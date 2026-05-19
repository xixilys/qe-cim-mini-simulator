"""Tests for the explicit QE accelerated numeric producer runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PRODUCER = Path("dse_v2/scripts/dse/run_qe_accelerated_numeric_producer.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _baseline(baseline_dir: Path) -> Path:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "fake_scf.in").write_text("&CONTROL\n/\n", encoding="utf-8")
    (baseline_dir / "pseudo").mkdir(parents=True)
    (baseline_dir / "pseudo" / "Si.pz-vbc.UPF").write_text("fake pseudo\n", encoding="utf-8")
    baseline_path = baseline_dir / "baseline_comparison.json"
    _write_json(
        baseline_path,
        {
            "schema_version": "dse.qe_pure_software_baseline_result.v1",
            "case_id": "qe_case",
            "pure_software_qe_baseline": True,
            "qe_command": ["pw.x", "-in", "fake_scf.in"],
            "baseline_sequence": [
                {
                    "step_id": "stage_00_scf",
                    "program": "pw.x",
                    "command": ["pw.x", "-in", "fake_scf.in"],
                    "input_path": "fixtures/qe/fake_scf.in",
                }
            ],
            "performance_metrics": {
                "terminal_step_metrics": {
                    "total_energy_ry": -10.0,
                    "highest_occupied_ev": 1.0,
                    "lowest_unoccupied_ev": 2.0,
                }
            },
        },
    )
    return baseline_path


def _requirements(tmp_path: Path, baseline_path: Path) -> Path:
    row_dir = tmp_path / "campaign" / "cand" / "qe_case"
    requirements = tmp_path / "requirements.json"
    _write_json(
        requirements,
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence_requirements.v1",
            "rows": [
                {
                    "candidate_id": "cand",
                    "workload_case_id": "qe_case",
                    "baseline_comparison": str(baseline_path),
                    "required_outputs": {
                        "accelerated_stdout": str(row_dir / "accelerated_qe.stdout.log"),
                        "kernel_evidence_json": str(row_dir / "kernel_evidence.json"),
                        "offload_provenance_json": str(row_dir / "offload_provenance.json"),
                        "kernel_boundary_snapshot_json": str(row_dir / "kernel_boundary_snapshot.json"),
                        "kernel_boundary_arrays_json": str(row_dir / "kernel_boundary_arrays.json"),
                    },
                    "evidence_output": str(row_dir / "qe_accelerated_numeric_evidence.json"),
                }
            ],
        },
    )
    return requirements


def test_producer_runs_modified_qe_and_builds_trusted_evidence(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline")
    requirements = _requirements(tmp_path, baseline_path)
    fake_bin = tmp_path / "fake_accel_qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "print('!    total energy              =     -10.00000010 Ry')\n"
        "print('     highest occupied, lowest unoccupied level (ev):     1.000001  2.000001')\n"
        "print('JOB DONE.')\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_EVIDENCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump([{'kernel_id':'h_psi','kernel_scope':'full_h_psi','full_kernel_recomputed':True,'absolute_error':1e-12,'relative_error':1e-10,'source':'qe_offload_runtime'}], f)\n"
        "with open(os.environ['QE_OFFLOAD_PROVENANCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'producer':'fake_modified_qe','accelerated_runtime':'qe_offload_runtime','offload_target':'gem5_generic_accel','full_h_psi_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':True,'l4_execution_proof':{'passed':True,'transport_harness':'gem5_generic_accel_microarchitecture_v1'},'physical_evidence':{'density_residual':1e-8}}, f)\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_snapshot.v1','kernel_id':'h_psi','dimensions':{'lda':4,'n':4,'m':1},'psi_l2_norm':1.0,'hpsi_l2_norm':2.0}, f)\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_arrays.v1','kernel_id':'h_psi','dimensions':{'lda':4,'n':4,'m':1},'array_order':'fortran_column_major_band_then_row','psi_real_imag':[[1.0,0.0]],'hpsi_real_imag':[[2.0,0.0]],'g2kin':[2.0]}, f)\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--requirements",
            str(requirements),
            "--accelerated-qe-bin-dir",
            str(fake_bin),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(
        (tmp_path / "campaign" / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["trusted_accelerated_numeric_source"] is True
    assert evidence["offload_provenance"]["offload_target"] == "gem5_generic_accel"
    assert evidence["kernel_boundary_snapshot"]["kernel_id"] == "h_psi"
    assert evidence["accelerated_reference"]["kernel_boundary_snapshot_json"].endswith("kernel_boundary_snapshot.json")
    assert evidence["accelerated_reference"]["kernel_boundary_arrays_json"].endswith("kernel_boundary_arrays.json")
    assert evidence["accelerated_reference"]["kernel_boundary_arrays_embedded"] is False


def test_producer_blocks_when_runtime_does_not_emit_offload_artifacts(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline")
    requirements = _requirements(tmp_path, baseline_path)
    fake_bin = tmp_path / "fake_plain_qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "print('!    total energy              =     -10.00000010 Ry')\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--requirements",
            str(requirements),
            "--accelerated-qe-bin-dir",
            str(fake_bin),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(
        (tmp_path / "campaign" / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert any("accelerated_runtime_did_not_emit_kernel_evidence" in item for item in evidence["blockers"])
    assert any("accelerated_runtime_did_not_emit_offload_provenance" in item for item in evidence["blockers"])


def test_producer_component_sidecar_smoke_proves_qe_consumption_but_stays_blocked(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline")
    requirements = _requirements(tmp_path, baseline_path)
    fake_bin = tmp_path / "fake_sidecar_qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess\n"
        "arrays = {\n"
        "  'schema_version':'dse.qe_hpsi_kernel_boundary_arrays.v1',\n"
        "  'kernel_id':'h_psi',\n"
        "  'dimensions':{'lda':1,'n':1,'m':1},\n"
        "  'npol':1,\n"
        "  'array_order':'fortran_column_major_band_then_row',\n"
        "  'vloc_algorithm':{'path':'vloc_psi_k_acc','gamma_only':False,'noncolin':False,'real_space':False,'has_task_groups':False},\n"
        "  'fft_descriptor_dffts':{'nr':[1,1,1],'nrx':[1,1,1],'nnr':1,'ngw':1,'ngm':1,'lgamma':False,'lpara':False},\n"
        "  'vloc_inputs':{'vrs_current_spin':[0.0],'igk_current_k':[1],'dffts_nl':[1]},\n"
        "  'vnl_inputs':{'algorithm_path':'add_vuspsi_k','supported_by_python_sidecar':True,'nkb':1,'nhm':1,'nat':1,'ntyp':1,'nh':[1],'ityp':[1],'ofsbeta':[0],'vkb_real_imag':[[0.0,0.0]],'deeq_current_spin':[0.0],'becp_k_reference_real_imag':[[0.0,0.0]]},\n"
        "  'g2kin':[2.0],\n"
        "  'psi_real_imag':[[1.0,0.0]],\n"
        "  'hpsi_kinetic_reference_real_imag':[[2.0,0.0]],\n"
        "  'hpsi_after_vloc_reference_real_imag':[[2.0,0.0]],\n"
        "  'hpsi_after_vnl_reference_real_imag':[[2.0,0.0]],\n"
        "  'hpsi_reference_real_imag':[[2.0,0.0]],\n"
        "}\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump(arrays, f)\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_snapshot.v1','kernel_id':'h_psi','dimensions':{'lda':1,'n':1,'m':1},'psi_l2_norm':1.0,'hpsi_l2_norm':2.0}, f)\n"
        "subprocess.run(os.environ['QE_OFFLOAD_HPSI_SIDECAR_CMD'], shell=True, check=True)\n"
        "consumed = os.path.exists(os.environ['QE_OFFLOAD_HPSI_RESULT_TXT'])\n"
        "print('!    total energy              =     -10.00000000 Ry')\n"
        "print('     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000')\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_EVIDENCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump([{'kernel_id':'h_psi','kernel_scope':'full_h_psi','full_kernel_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'absolute_error':0.0,'relative_error':0.0,'software_component_model_not_l4':True,'single_hpsi_call_smoke_only':True,'source':'python_qe_hpsi_component_model'}], f)\n"
        "with open(os.environ['QE_OFFLOAD_PROVENANCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'producer':'fake_sidecar_qe','accelerated_runtime':'qe_offload_runtime','offload_target':'python_component_sidecar','full_h_psi_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'software_component_model_not_l4':True,'single_hpsi_call_smoke_only':True,'l4_execution_proof':{'passed':False,'transport_harness':'python_component_sidecar_not_l4'},'physical_evidence':{'density_residual':0.0}}, f)\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--requirements",
            str(requirements),
            "--accelerated-qe-bin-dir",
            str(fake_bin),
            "--enable-hpsi-component-sidecar",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(
        (tmp_path / "campaign" / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert evidence["offload_provenance"]["qe_mainflow_integrated"] is True
    assert evidence["offload_provenance"]["accelerated_results_consumed_by_qe"] is True
    assert "offload_provenance_missing_qe_mainflow_integrated_true" not in evidence["blockers"]
    assert "offload_provenance_missing_accelerated_results_consumed_by_qe_true" not in evidence["blockers"]
    assert "offload_provenance_marks_software_component_model_not_l4" in evidence["blockers"]
    assert "kernel_evidence_marks_software_component_model_not_l4:0" in evidence["blockers"]
    assert "offload_provenance_marks_single_hpsi_call_smoke_only" in evidence["blockers"]
    assert "kernel_evidence_marks_single_hpsi_call_smoke_only:0" in evidence["blockers"]
    assert evidence["accelerated_reference"]["hpsi_component_sidecar_summary_embedded"] is True
    assert evidence["hpsi_component_sidecar_summary"]["status"] == "passed_component_model"


def test_producer_preserves_gem5_sidecar_transport_proof_without_trusting_component_model(
    tmp_path: Path,
) -> None:
    baseline_path = _baseline(tmp_path / "baseline")
    requirements = _requirements(tmp_path, baseline_path)
    fake_bin = tmp_path / "fake_gem5_sidecar_qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_sidecar = tmp_path / "fake_gem5_sidecar.py"
    fake_sidecar.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, json\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--boundary-arrays')\n"
        "p.add_argument('--result-txt')\n"
        "p.add_argument('--summary-json')\n"
        "args = p.parse_args()\n"
        "open(args.result_txt, 'w', encoding='utf-8').write('2.0 0.0\\n')\n"
        "with open(args.summary_json, 'w', encoding='utf-8') as f:\n"
        "    json.dump({\n"
        "      'schema_version':'dse.qe_hpsi_gem5_component_sidecar_summary.v1',\n"
        "      'status':'passed_gem5_transport_component_model',\n"
        "      'software_component_model_not_l4': True,\n"
        "      'trusted_full_claim': False,\n"
        "      'gem5_l4_transport_proof': {\n"
        "        'passed': True,\n"
        "        'transport_harness': 'gem5_generic_accel_systemc_sidecar',\n"
        "        'checks': {'gem5_returncode_zero': True},\n"
        "        'missing_evidence': []\n"
        "      }\n"
        "    }, f)\n",
        encoding="utf-8",
    )
    fake_sidecar.chmod(0o755)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_arrays.v1','kernel_id':'h_psi','dimensions':{'lda':1,'n':1,'m':1},'array_order':'fortran_column_major_band_then_row','psi_real_imag':[[1.0,0.0]],'hpsi_reference_real_imag':[[2.0,0.0]],'g2kin':[2.0]}, f)\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_snapshot.v1','kernel_id':'h_psi','dimensions':{'lda':1,'n':1,'m':1},'psi_l2_norm':1.0,'hpsi_l2_norm':2.0}, f)\n"
        "subprocess.run(os.environ['QE_OFFLOAD_HPSI_SIDECAR_CMD'], shell=True, check=True)\n"
        "consumed = os.path.exists(os.environ['QE_OFFLOAD_HPSI_RESULT_TXT'])\n"
        "print('!    total energy              =     -10.00000000 Ry')\n"
        "print('     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000')\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_EVIDENCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump([{'kernel_id':'h_psi','kernel_scope':'full_h_psi','full_kernel_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'absolute_error':0.0,'relative_error':0.0,'software_component_model_not_l4':True,'source':'python_qe_hpsi_component_model'}], f)\n"
        "with open(os.environ['QE_OFFLOAD_PROVENANCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'producer':'fake_gem5_sidecar_qe','accelerated_runtime':'qe_offload_runtime','offload_target':'python_component_sidecar_reference_assisted','full_h_psi_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'software_component_model_not_l4':True,'sidecar_observed_hpsi_calls':2,'sidecar_attempted_hpsi_calls':2,'sidecar_consumed_hpsi_calls':2,'sidecar_failed_hpsi_calls':0,'all_observed_hpsi_calls_sidecar_consumed':True,'single_hpsi_call_smoke_only':False,'l4_execution_proof':{'passed':False,'transport_harness':'python_component_sidecar_not_l4'},'physical_evidence':{'density_residual':0.0}}, f)\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--requirements",
            str(requirements),
            "--accelerated-qe-bin-dir",
            str(fake_bin),
            "--enable-hpsi-component-sidecar",
            "--hpsi-sidecar-command-template",
            f"{sys.executable} {fake_sidecar} --boundary-arrays {{boundary_arrays}} --result-txt {{result_txt}} --summary-json {{summary_json}}",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(
        (tmp_path / "campaign" / "cand" / "qe_case" / "qe_accelerated_numeric_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert evidence["offload_provenance"]["l4_execution_proof"]["passed"] is True
    assert (
        evidence["offload_provenance"]["l4_execution_proof"]["transport_harness"]
        == "gem5_generic_accel_systemc_sidecar"
    )
    assert (
        evidence["offload_provenance"]["offload_target"]
        == "gem5_generic_accel_systemc_sidecar_component_model"
    )
    assert "offload_provenance_l4_execution_proof_not_passed" not in evidence["blockers"]
    assert "offload_provenance_marks_software_component_model_not_l4" in evidence["blockers"]
    assert "kernel_evidence_marks_software_component_model_not_l4:0" in evidence["blockers"]


def test_producer_accepts_native_sidecar_payload_only_when_summary_is_trusted(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline")
    requirements = _requirements(tmp_path, baseline_path)
    fake_bin = tmp_path / "fake_native_sidecar_qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_sidecar = tmp_path / "fake_native_gem5_sidecar.py"
    fake_sidecar.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, json\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--boundary-arrays')\n"
        "p.add_argument('--result-txt')\n"
        "p.add_argument('--summary-json')\n"
        "args = p.parse_args()\n"
        "open(args.result_txt, 'w', encoding='utf-8').write('2.0 0.0\\n')\n"
        "with open(args.summary_json, 'w', encoding='utf-8') as f:\n"
        "    json.dump({\n"
        "      'schema_version':'dse.qe_hpsi_gem5_component_sidecar_summary.v1',\n"
        "      'status':'passed_gem5_transport_native_l4_payload',\n"
        "      'kernel_id':'h_psi',\n"
        "      'kernel_scope':'full_h_psi',\n"
        "      'full_kernel_recomputed': True,\n"
        "      'full_h_psi_recomputed': True,\n"
        "      'absolute_error': 0.0,\n"
        "      'relative_error': 0.0,\n"
        "      'source':'gem5_generic_accel_qe_hpsi_systemc_native_payload',\n"
        "      'trusted_payload_kind':'systemc_generic_accel_model_l4_offload_kernel_numerical',\n"
        "      'software_component_model_not_l4': False,\n"
        "      'trusted_full_claim': True,\n"
        "      'gem5_l4_transport_proof': {\n"
        "        'passed': True,\n"
        "        'transport_harness': 'gem5_generic_accel_systemc_sidecar',\n"
        "        'checks': {'gem5_returncode_zero': True},\n"
        "        'missing_evidence': []\n"
        "      }\n"
        "    }, f)\n",
        encoding="utf-8",
    )
    fake_sidecar.chmod(0o755)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, subprocess\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_arrays.v1','kernel_id':'h_psi','dimensions':{'lda':1,'n':1,'m':1},'array_order':'fortran_column_major_band_then_row','psi_real_imag':[[1.0,0.0]],'hpsi_reference_real_imag':[[2.0,0.0]],'g2kin':[2.0]}, f)\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'schema_version':'dse.qe_hpsi_kernel_boundary_snapshot.v1','kernel_id':'h_psi','dimensions':{'lda':1,'n':1,'m':1},'psi_l2_norm':1.0,'hpsi_l2_norm':2.0}, f)\n"
        "subprocess.run(os.environ['QE_OFFLOAD_HPSI_SIDECAR_CMD'], shell=True, check=True)\n"
        "consumed = os.path.exists(os.environ['QE_OFFLOAD_HPSI_RESULT_TXT'])\n"
        "print('!    total energy              =     -10.00000000 Ry')\n"
        "print('     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000')\n"
        "# Simulate the old conservative QE hook markers; producer may override only because the sidecar summary is trusted native payload evidence.\n"
        "with open(os.environ['QE_OFFLOAD_KERNEL_EVIDENCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump([{'kernel_id':'h_psi','kernel_scope':'full_h_psi','full_kernel_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'absolute_error':0.0,'relative_error':0.0,'software_component_model_not_l4':True,'source':'python_qe_hpsi_component_model'}], f)\n"
        "with open(os.environ['QE_OFFLOAD_PROVENANCE_JSON'], 'w', encoding='utf-8') as f:\n"
        "    json.dump({'producer':'fake_native_sidecar_qe','accelerated_runtime':'qe_offload_runtime','offload_target':'python_component_sidecar_reference_assisted','full_h_psi_recomputed':True,'qe_mainflow_integrated':True,'accelerated_results_consumed_by_qe':consumed,'software_component_model_not_l4':True,'sidecar_observed_hpsi_calls':2,'sidecar_attempted_hpsi_calls':2,'sidecar_consumed_hpsi_calls':2,'sidecar_failed_hpsi_calls':0,'all_observed_hpsi_calls_sidecar_consumed':True,'single_hpsi_call_smoke_only':False,'l4_execution_proof':{'passed':False,'transport_harness':'python_component_sidecar_not_l4'},'physical_evidence':{'density_residual':0.0}}, f)\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--requirements",
            str(requirements),
            "--accelerated-qe-bin-dir",
            str(fake_bin),
            "--enable-hpsi-component-sidecar",
            "--hpsi-sidecar-command-template",
            f"{sys.executable} {fake_sidecar} --boundary-arrays {{boundary_arrays}} --result-txt {{result_txt}} --summary-json {{summary_json}}",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    row_dir = tmp_path / "campaign" / "cand" / "qe_case"
    evidence = json.loads((row_dir / "qe_accelerated_numeric_evidence.json").read_text(encoding="utf-8"))
    kernel_rows = json.loads((row_dir / "kernel_evidence.json").read_text(encoding="utf-8"))
    provenance = json.loads((row_dir / "offload_provenance.json").read_text(encoding="utf-8"))
    assert evidence["trusted_accelerated_numeric_source"] is True
    assert evidence["accelerated_output_status"] == "passed"
    assert evidence["blockers"] == []
    assert kernel_rows[0]["source"] == "gem5_generic_accel_qe_hpsi_systemc_native_payload"
    assert kernel_rows[0]["software_component_model_not_l4"] is False
    assert provenance["software_component_model_not_l4"] is False
    assert provenance["offload_target"] == "gem5_generic_accel_qe_hpsi_systemc_native_payload"
    assert provenance["l4_execution_proof"]["passed"] is True
    assert provenance["sidecar_observed_hpsi_calls"] == 2
    assert provenance["sidecar_attempted_hpsi_calls"] == 2
    assert provenance["sidecar_consumed_hpsi_calls"] == 2
    assert provenance["sidecar_failed_hpsi_calls"] == 0
    assert provenance["all_observed_hpsi_calls_sidecar_consumed"] is True
    assert provenance["single_hpsi_call_smoke_only"] is False
    assert kernel_rows[0]["sidecar_consumed_hpsi_calls"] == 2
    assert "not silicon/RTL proof" in provenance["claim_boundary"]
