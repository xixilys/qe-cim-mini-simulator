"""Tests for component-scoped QE h_psi kernel runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


RUNNER = Path("dse_v2/scripts/dse/run_qe_hpsi_component_kernel.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _arrays_and_targets(tmp_path: Path) -> tuple[Path, Path]:
    arrays = tmp_path / "arrays.json"
    targets = tmp_path / "targets.json"
    payload = {
        "schema_version": "dse.qe_hpsi_kernel_boundary_arrays.v1",
        "kernel_id": "h_psi",
        "dimensions": {"lda": 2, "n": 2, "m": 1},
        "npol": 1,
        "g2kin": [2.0, 3.0],
        "psi_real_imag": [[1.0, 0.0], [0.0, 1.0]],
        "hpsi_kinetic_reference_real_imag": [[2.0, 0.0], [0.0, 3.0]],
        "hpsi_after_vloc_reference_real_imag": [[3.0, 0.0], [0.0, 5.0]],
        "hpsi_after_vnl_reference_real_imag": [[4.0, 0.0], [0.0, 8.0]],
        "hpsi_reference_real_imag": [[4.0, 0.0], [0.0, 8.0]],
    }
    target_payload = {
        "schema_version": "dse.qe_hpsi_component_target_arrays.v1",
        "kernel_id": "h_psi",
        "element_count": 2,
        "component_summaries": {
            "kinetic_output_real_imag": {"element_count": 2, "l2_norm": (13.0) ** 0.5, "max_abs": 3.0},
            "vloc_delta_reference_real_imag": {"element_count": 2, "l2_norm": (5.0) ** 0.5, "max_abs": 2.0},
            "vnl_delta_reference_real_imag": {"element_count": 2, "l2_norm": (10.0) ** 0.5, "max_abs": 3.0},
        },
        "kinetic_output_real_imag": [[2.0, 0.0], [0.0, 3.0]],
        "vloc_delta_reference_real_imag": [[1.0, 0.0], [0.0, 2.0]],
        "vnl_delta_reference_real_imag": [[1.0, 0.0], [0.0, 3.0]],
    }
    _write_json(arrays, payload)
    _write_json(targets, target_payload)
    return arrays, targets


def test_component_kernel_computes_kinetic_against_targets(tmp_path: Path) -> None:
    arrays, targets = _arrays_and_targets(tmp_path)
    out = tmp_path / "kinetic_result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--component",
            "kinetic",
            "--boundary-arrays",
            str(arrays),
            "--component-targets",
            str(targets),
            "--out",
            str(out),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["computed"] is True
    assert result["absolute_error"] == 0.0
    assert result["relative_error"] == 0.0
    assert result["trusted_full_h_psi"] is False


def test_component_kernel_blocks_vloc_without_replay_downgrade(tmp_path: Path) -> None:
    arrays, targets = _arrays_and_targets(tmp_path)
    out = tmp_path / "vloc_result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--component",
            "vloc_delta",
            "--boundary-arrays",
            str(arrays),
            "--component-targets",
            str(targets),
            "--out",
            str(out),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["computed"] is False
    assert "missing_vloc_algorithm_path" in result["blockers"]
    assert result["target_summary"]["element_count"] == 2


def test_component_kernel_computes_vloc_delta_from_fft_inputs(tmp_path: Path) -> None:
    arrays, targets = _arrays_and_targets(tmp_path)
    payload = json.loads(arrays.read_text(encoding="utf-8"))
    payload.update(
        {
            "vloc_algorithm": {
                "path": "vloc_psi_k_acc",
                "gamma_only": False,
                "noncolin": False,
                "real_space": False,
                "has_task_groups": False,
                "use_gpu": False,
                "current_spin": 1,
                "current_k": 1,
                "nkb": 2,
            },
            "fft_descriptor_dffts": {
                "nr": [1, 1, 2],
                "nrx": [1, 1, 2],
                "nnr": 2,
                "ngw": 2,
                "ngm": 2,
                "lpara": False,
                "lgamma": False,
            },
            "vloc_inputs": {
                "current_spin": 1,
                "current_k": 1,
                "vrs_array_order": "dffts_local_realspace_order",
                "vrs_current_spin": [1.0, 1.0],
                "igk_current_k": [1, 2],
                "dffts_nl": [1, 2],
            },
        }
    )
    _write_json(arrays, payload)
    target_payload = json.loads(targets.read_text(encoding="utf-8"))
    target_payload["vloc_delta_reference_real_imag"] = [[1.0, 0.0], [0.0, 1.0]]
    target_payload["component_summaries"]["vloc_delta_reference_real_imag"] = {
        "element_count": 2,
        "l2_norm": 2.0 ** 0.5,
        "max_abs": 1.0,
    }
    _write_json(targets, target_payload)
    out = tmp_path / "vloc_result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--component",
            "vloc_delta",
            "--boundary-arrays",
            str(arrays),
            "--component-targets",
            str(targets),
            "--out",
            str(out),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["computed"] is True
    assert result["relative_error"] == 0.0
    assert result["input_contract"]["status"] == "passed"
    assert result["input_contract"]["algorithm_path"] == "vloc_psi_k_acc"
    assert result["input_contract"]["vrs_element_count"] == 2
    assert result["trusted_full_h_psi"] is False


def test_component_kernel_computes_vnl_delta_from_projector_inputs(tmp_path: Path) -> None:
    arrays, targets = _arrays_and_targets(tmp_path)
    payload = json.loads(arrays.read_text(encoding="utf-8"))
    payload["hpsi_after_vloc_reference_real_imag"] = [[3.0, 0.0], [0.0, 5.0]]
    payload["hpsi_after_vnl_reference_real_imag"] = [[23.0, 0.0], [0.0, 35.0]]
    payload["hpsi_reference_real_imag"] = [[23.0, 0.0], [0.0, 35.0]]
    payload["vnl_inputs"] = {
        "algorithm_path": "add_vuspsi_k",
        "supported_by_python_sidecar": True,
        "nkb": 1,
        "nhm": 1,
        "nat": 1,
        "ntyp": 1,
        "nh": [1],
        "ityp": [1],
        "ofsbeta": [0],
        "vkb_real_imag": [[2.0, 0.0], [0.0, 3.0]],
        "deeq_current_spin": [2.0],
        "becp_k_reference_real_imag": [[5.0, 0.0]],
    }
    _write_json(arrays, payload)
    target_payload = json.loads(targets.read_text(encoding="utf-8"))
    target_payload["vnl_delta_reference_real_imag"] = [[20.0, 0.0], [0.0, 30.0]]
    target_payload["component_summaries"]["vnl_delta_reference_real_imag"] = {
        "element_count": 2,
        "l2_norm": (20.0**2 + 30.0**2) ** 0.5,
        "max_abs": 30.0,
    }
    _write_json(targets, target_payload)
    out = tmp_path / "vnl_result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--component",
            "vnl_delta",
            "--boundary-arrays",
            str(arrays),
            "--component-targets",
            str(targets),
            "--out",
            str(out),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["computed"] is True
    assert result["relative_error"] == 0.0
    assert result["becp_reference_relative_error"] == 0.0
    assert result["trusted_full_h_psi"] is False
