"""Tests for QE h_psi component sidecar transport through GenericAccel."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GSIM_SIDECAR = Path("dse_v2/scripts/dse/run_qe_hpsi_component_gsim_sidecar.py")
GEM5_WRAPPER = Path("dse_v2/scripts/dse/run_qe_hpsi_gem5_component_sidecar.py")
NATIVE_KERNEL_CPP = Path("tools/qe_hpsi_l4_kernel/qe_hpsi_native_kernel.cpp")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_minimal_full_hpsi_arrays(path: Path) -> None:
    _write_json(
        path,
        {
            "schema_version": "dse.qe_hpsi_kernel_boundary_arrays.v1",
            "kernel_id": "h_psi",
            "dimensions": {"lda": 1, "n": 1, "m": 1},
            "npol": 1,
            "array_order": "fortran_column_major_band_then_row",
            "vloc_algorithm": {
                "path": "vloc_psi_k_acc",
                "gamma_only": False,
                "noncolin": False,
                "real_space": False,
                "has_task_groups": False,
            },
            "fft_descriptor_dffts": {
                "nr": [1, 1, 1],
                "nrx": [1, 1, 1],
                "nnr": 1,
                "ngw": 1,
                "ngm": 1,
                "lgamma": False,
                "lpara": False,
            },
            "vloc_inputs": {"vrs_current_spin": [0.0], "igk_current_k": [1], "dffts_nl": [1]},
            "vnl_inputs": {
                "algorithm_path": "add_vuspsi_k",
                "supported_by_python_sidecar": True,
                "nkb": 1,
                "nhm": 1,
                "nat": 1,
                "ntyp": 1,
                "nh": [1],
                "ityp": [1],
                "ofsbeta": [0],
                "vkb_real_imag": [[0.0, 0.0]],
                "deeq_current_spin": [0.0],
                "becp_k_reference_real_imag": [[0.0, 0.0]],
            },
            "g2kin": [2.0],
            "psi_real_imag": [[1.0, 0.0]],
            "hpsi_kinetic_reference_real_imag": [[2.0, 0.0]],
            "hpsi_after_vloc_reference_real_imag": [[2.0, 0.0]],
            "hpsi_after_vnl_reference_real_imag": [[2.0, 0.0]],
            "hpsi_reference_real_imag": [[2.0, 0.0]],
        },
    )


def _compile_native_kernel(tmp_path: Path) -> Path:
    binary = tmp_path / "qe_hpsi_native_kernel"
    completed = subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            str(REPO_ROOT / NATIVE_KERNEL_CPP),
            "-o",
            str(binary),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return binary


def test_gsim_sidecar_writes_qe_consumable_payload_but_stays_untrusted(tmp_path: Path) -> None:
    arrays = tmp_path / "kernel_boundary_arrays.json"
    result_txt = tmp_path / "hpsi_result.txt"
    summary_json = tmp_path / "component_summary.json"
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    _write_minimal_full_hpsi_arrays(arrays)
    _write_json(
        request,
        {
            "schema_version": "gsim.request.v1",
            "run_id": "cand__qe_case__hpsi_component",
            "extension_payload": {
                "qe_hpsi_component_sidecar": {
                    "boundary_arrays_json": str(arrays),
                    "result_txt": str(result_txt),
                    "summary_json": str(summary_json),
                }
            },
        },
    )

    completed = subprocess.run(
        [sys.executable, str(GSIM_SIDECAR), "--request", str(request), "--result", str(result), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["software_component_model_not_l4"] is True
    assert payload["trusted_full_claim"] is False
    assert summary["status"] == "passed_component_model"
    assert result_txt.read_text(encoding="utf-8").strip() == "2.00000000000000000e+00 0.00000000000000000e+00"


def test_gsim_sidecar_dispatches_native_l4_payload_without_component_model_marker(tmp_path: Path) -> None:
    native_kernel = _compile_native_kernel(tmp_path)
    arrays = tmp_path / "kernel_boundary_arrays.json"
    result_txt = tmp_path / "hpsi_result.txt"
    summary_json = tmp_path / "native_summary.json"
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    _write_minimal_full_hpsi_arrays(arrays)
    _write_json(
        request,
        {
            "schema_version": "gsim.request.v1",
            "run_id": "cand__qe_case__hpsi_native",
            "extension_payload": {
                "qe_hpsi_component_sidecar": {
                    "payload_mode": "native_l4",
                    "native_payload_executable": str(native_kernel),
                    "boundary_arrays_json": str(arrays),
                    "result_txt": str(result_txt),
                    "summary_json": str(summary_json),
                }
            },
        },
    )

    completed = subprocess.run(
        [sys.executable, str(GSIM_SIDECAR), "--request", str(request), "--result", str(result), "--quiet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["payload_mode"] == "native_l4"
    assert payload["software_component_model_not_l4"] is False
    assert payload["trusted_full_claim"] is True
    assert summary["status"] == "passed_native_l4_payload"
    assert summary["full_kernel_recomputed"] is True
    assert summary["software_component_model_not_l4"] is False
    assert summary["trusted_payload_kind"] == "systemc_generic_accel_model_l4_offload_kernel_numerical"
    assert "not silicon or RTL proof" in summary["claim_boundary"]
    assert result_txt.read_text(encoding="utf-8").strip() == "2.00000000000000000e+00 0.00000000000000000e+00"


def test_gem5_wrapper_accepts_fake_generic_accel_transport_and_preserves_claim_boundary(tmp_path: Path) -> None:
    arrays = tmp_path / "kernel_boundary_arrays.json"
    result_txt = tmp_path / "hpsi_result.txt"
    summary_json = tmp_path / "component_summary.json"
    work_dir = tmp_path / "gem5_work"
    fake_gem5 = tmp_path / "fake_gem5.py"
    fake_config = tmp_path / "generic_accel_l4_test.py"
    fake_driver = tmp_path / "generic_accel_l4_driver"
    _write_minimal_full_hpsi_arrays(arrays)
    fake_config.write_text("# fake config\n", encoding="utf-8")
    fake_driver.write_text("# fake driver\n", encoding="utf-8")
    fake_gem5.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, subprocess, sys\n"
        "outdir = pathlib.Path(next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--outdir=')))\n"
        "request = sys.argv[sys.argv.index('--request') + 1]\n"
        "simulator = sys.argv[sys.argv.index('--simulator') + 1]\n"
        "outdir.mkdir(parents=True, exist_ok=True)\n"
        "sidecar_result = outdir / 'systemc_sidecar.result.json'\n"
        "rc = subprocess.run([sys.executable, simulator, '--request', request, '--result', str(sidecar_result), '--quiet'])\n"
        "log = '\\n'.join([\n"
        " 'descriptor_read verified=true',\n"
        " 'uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 result_path=/tmp/uarch.result.json',\n"
        " f'systemc_submit verified=true executable={simulator} request_path={request} result_path={sidecar_result} return_code={rc.returncode} result_bytes={sidecar_result.stat().st_size if sidecar_result.exists() else 0}',\n"
        " 'microarchitecture_execute verified=true engine=gem5_generic_accel_microarchitecture_v1',\n"
        " 'completion_writeback verified=true',\n"
        "])\n"
        "(outdir / 'gem5.log').write_text(log + '\\n', encoding='utf-8')\n"
        "print('generic_accel_l4_status=1 error_code=0')\n"
        "sys.exit(rc.returncode)\n",
        encoding="utf-8",
    )
    fake_gem5.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(GEM5_WRAPPER),
            "--boundary-arrays",
            str(arrays),
            "--result-txt",
            str(result_txt),
            "--summary-json",
            str(summary_json),
            "--work-dir",
            str(work_dir),
            "--gem5-bin",
            str(fake_gem5),
            "--gem5-config",
            str(fake_config),
            "--gem5-driver",
            str(fake_driver),
            "--sidecar-simulator",
            str(REPO_ROOT / GSIM_SIDECAR),
            "--fail-on-blocked",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed_gem5_transport_component_model"
    assert summary["gem5_l4_transport_proof"]["passed"] is True
    assert summary["software_component_model_not_l4"] is True
    assert summary["trusted_full_claim"] is False
    assert "blocked for trusted non-software L4 correctness" in summary["claim_boundary"]
    assert result_txt.exists()


def test_gem5_wrapper_accepts_fake_transport_with_native_l4_payload(tmp_path: Path) -> None:
    native_kernel = _compile_native_kernel(tmp_path)
    arrays = tmp_path / "kernel_boundary_arrays.json"
    result_txt = tmp_path / "hpsi_result.txt"
    summary_json = tmp_path / "native_summary.json"
    work_dir = tmp_path / "gem5_work"
    fake_gem5 = tmp_path / "fake_gem5.py"
    fake_config = tmp_path / "generic_accel_l4_test.py"
    fake_driver = tmp_path / "generic_accel_l4_driver"
    _write_minimal_full_hpsi_arrays(arrays)
    fake_config.write_text("# fake config\n", encoding="utf-8")
    fake_driver.write_text("# fake driver\n", encoding="utf-8")
    fake_gem5.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, subprocess, sys\n"
        "outdir = pathlib.Path(next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--outdir=')))\n"
        "request = sys.argv[sys.argv.index('--request') + 1]\n"
        "simulator = sys.argv[sys.argv.index('--simulator') + 1]\n"
        "outdir.mkdir(parents=True, exist_ok=True)\n"
        "sidecar_result = outdir / 'systemc_sidecar.result.json'\n"
        "rc = subprocess.run([sys.executable, simulator, '--request', request, '--result', str(sidecar_result), '--quiet'])\n"
        "log = '\\n'.join([\n"
        " 'descriptor_read verified=true',\n"
        " 'uarch_request_decode verified=true engine=gem5_generic_accel_microarchitecture_v1 result_path=/tmp/uarch.result.json',\n"
        " f'systemc_submit verified=true executable={simulator} request_path={request} result_path={sidecar_result} return_code={rc.returncode} result_bytes={sidecar_result.stat().st_size if sidecar_result.exists() else 0}',\n"
        " 'microarchitecture_execute verified=true engine=gem5_generic_accel_microarchitecture_v1',\n"
        " 'completion_writeback verified=true',\n"
        "])\n"
        "(outdir / 'gem5.log').write_text(log + '\\n', encoding='utf-8')\n"
        "print('generic_accel_l4_status=1 error_code=0')\n"
        "sys.exit(rc.returncode)\n",
        encoding="utf-8",
    )
    fake_gem5.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(GEM5_WRAPPER),
            "--boundary-arrays",
            str(arrays),
            "--result-txt",
            str(result_txt),
            "--summary-json",
            str(summary_json),
            "--work-dir",
            str(work_dir),
            "--gem5-bin",
            str(fake_gem5),
            "--gem5-config",
            str(fake_config),
            "--gem5-driver",
            str(fake_driver),
            "--sidecar-simulator",
            str(REPO_ROOT / GSIM_SIDECAR),
            "--payload-mode",
            "native_l4",
            "--native-payload-bin",
            str(native_kernel),
            "--fail-on-blocked",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "passed_gem5_transport_native_l4_payload"
    assert summary["gem5_l4_transport_proof"]["passed"] is True
    assert summary["payload_mode"] == "native_l4"
    assert summary["software_component_model_not_l4"] is False
    assert summary["trusted_full_claim"] is True
    assert summary["full_kernel_recomputed"] is True
    assert "not silicon/RTL proof" in summary["claim_boundary"]
    assert result_txt.exists()
