"""Tests for converting admitted six-SCF QE references into baseline rows."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES
from dse_v2.scripts.dse.build_qe_baseline_comparisons_from_six_class_bundle import (
    build_baseline_comparisons_from_six_class_bundle,
    materialize_qe_baseline_triplet_from_index,
)


SCRIPT = Path("dse_v2/scripts/dse/build_qe_baseline_comparisons_from_six_class_bundle.py")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_qe_output(class_id: str) -> str:
    return f"""
     Program PWSCF v.7.5 starts
!    total energy              =     -10.00000000 Ry
     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000
     Total force =     0.000123     Total SCF correction =     0.000000
          total   stress  (Ry/bohr**3)                   (kbar)     P=       27.34
     convergence has been achieved in   4 iterations
=------------------------------------------------------------------------------=
   JOB DONE.
=------------------------------------------------------------------------------=
     {class_id}
"""


def _write_fake_bundle(
    bundle: Path,
    *,
    break_first_hash: bool = False,
    strip_first_completion_markers: bool = False,
) -> None:
    cases = []
    for index, class_id in enumerate(STRICT_DFT_QE_WORKLOAD_CLASSES):
        output_rel = Path("reference_outputs") / f"{class_id}.out"
        output_path = bundle / output_rel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_text = _fake_qe_output(class_id)
        if strip_first_completion_markers and index == 0:
            output_text = output_text.replace(
                "     convergence has been achieved in   4 iterations\n",
                "",
            ).replace("   JOB DONE.\n", "")
        output_path.write_text(output_text, encoding="utf-8")
        sha = _sha256(output_path)
        if break_first_hash and index == 0:
            sha = "0" * 64
        cases.append(
            {
                "case_id": f"{class_id}_case",
                "class_id": class_id,
                "reference_output": {
                    "path": output_rel.as_posix(),
                    "sha256": sha,
                    "hash_algorithm": "sha256",
                    "status": "local_pw_x_reference_output_hash_from_converged_scf_run",
                    "hash_final": True,
                    "job_done": True,
                    "scf_converged": True,
                    "returncode": 0,
                    "command": ["/qe/bin/pw.x", "-in", f"qe_inputs/{class_id}.in"],
                },
            }
        )
    _write_json(
        bundle / "dft_scf_six_class_bundle_manifest.json",
        {
            "schema_version": "dse.dft_scf.six_class_bundle_manifest.v1",
            "cases": cases,
        },
    )


def test_builds_passed_baseline_comparisons_from_admitted_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle)

    index = build_baseline_comparisons_from_six_class_bundle(bundle, out_dir)

    assert index["status"] == "passed"
    assert index["passed_case_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    first_case = STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    baseline = json.loads((out_dir / f"{first_case}_case" / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert baseline["pure_software_qe_baseline"] is True
    assert baseline["baseline_status"] == "real_qe_baseline"
    assert baseline["performance_metrics"]["terminal_step_metrics"]["total_energy_ry"] == -10.0
    assert baseline["performance_metrics"]["terminal_step_metrics"]["pressure_kbar"] == 27.34


def test_emits_pure_software_baseline_materialization_triplet_for_six_passed_classes(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle)

    index = build_baseline_comparisons_from_six_class_bundle(bundle, out_dir)

    materialization_path = out_dir / "dft_scf_six_class_qe_baseline_materialization.json"
    validation_path = out_dir / "dft_scf_six_class_qe_baseline_materialization_validation.json"
    status_path = out_dir / "dft_scf_six_class_qe_baseline_materialization_status.json"
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))

    assert index["status"] == "passed"
    assert materialization["status"] == "passed"
    assert materialization["case_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert materialization["passed_case_count"] == len(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert materialization["blocked_case_count"] == 0
    assert materialization["strict_scf_class_ids"] == list(STRICT_DFT_QE_WORKLOAD_CLASSES)
    assert materialization["evidence_classification"] == "pure_software_qe_baseline_value_evidence"
    assert materialization["pure_software_qe_baseline"] is True
    assert materialization["pure_software_qe_baseline_only"] is True
    assert materialization["source_index_sha256"] == _sha256(out_dir / "qe_baseline_comparison_index.json")
    for flag in (
        "hardware_acceleration",
        "hardware_acceleration_evidence",
        "fpga_ppa",
        "fpga_ppa_evidence",
        "asic_ppa",
        "asic_ppa_evidence",
        "l4_value",
        "l4_value_evidence",
        "trusted_final_claim",
        "hardware_completion",
        "hardware_completion_eligible",
        "release_completion",
        "release_completion_eligible",
        "deliverable_complete",
    ):
        assert materialization[flag] is False
        assert validation["claim_flags"][flag] is False
        assert status["claim_flags"][flag] is False
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert status["status"] == "passed"
    assert status["materialization_artifact"] == str(materialization_path)
    assert status["validation_artifact"] == str(validation_path)


def test_materialization_triplet_fails_closed_for_mismatched_existing_index(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "baselines"
    records = []
    for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES[:-1]:
        records.append(
            {
                "case_id": f"{class_id}_case",
                "class_id": class_id,
                "status": "passed",
                "pure_software_qe_baseline": True,
                "baseline_comparison": str(out_dir / f"{class_id}_case" / "baseline_comparison.json"),
                "blockers": [],
            }
        )
    records.append(dict(records[0]))
    index_path = out_dir / "qe_baseline_comparison_index.json"
    _write_json(
        index_path,
        {
            "schema_version": "dse.qe_pure_software_baseline_from_six_class_bundle_index.v1",
            "status": "passed",
            "passed": True,
            "case_count": len(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "passed_case_count": len(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "strict_scf_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "missing_strict_scf_class_ids": [],
            "records": records,
            "blockers": [],
        },
    )

    materialization = materialize_qe_baseline_triplet_from_index(index_path)

    validation = json.loads(
        (out_dir / "dft_scf_six_class_qe_baseline_materialization_validation.json").read_text(
            encoding="utf-8"
        )
    )
    status = json.loads(
        (out_dir / "dft_scf_six_class_qe_baseline_materialization_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert materialization["status"] == "blocked"
    assert materialization["pure_software_qe_baseline"] is False
    assert materialization["pure_software_qe_baseline_only"] is False
    assert materialization["deliverable_complete"] is False
    assert validation["valid"] is False
    assert "missing_strict_scf_class_id:projector_orthogonalization_heavy_scf" in validation["errors"]
    assert "duplicate_strict_scf_class_id:small_multi_k_scf" in validation["errors"]
    assert status["status"] == "blocked"
    assert status["deliverable_complete"] is False


def test_blocks_hash_mismatch_fail_closed(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle, break_first_hash=True)

    index = build_baseline_comparisons_from_six_class_bundle(bundle, out_dir)

    assert index["status"] == "blocked"
    assert "reference_output_sha256_mismatch" in index["blockers"]
    first_case = STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    baseline = json.loads((out_dir / f"{first_case}_case" / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert baseline["pure_software_qe_baseline"] is False
    assert baseline["baseline_status"] == "qe_reference_bundle_baseline_not_admitted"


def test_blocks_manifest_flags_without_qe_completion_markers(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle, strip_first_completion_markers=True)

    index = build_baseline_comparisons_from_six_class_bundle(bundle, out_dir)

    assert index["status"] == "blocked"
    assert "reference_output_job_done_marker_missing" in index["blockers"]
    assert "reference_output_scf_converged_marker_missing" in index["blockers"]
    first_case = STRICT_DFT_QE_WORKLOAD_CLASSES[0]
    baseline = json.loads((out_dir / f"{first_case}_case" / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert baseline["pure_software_qe_baseline"] is False
    assert baseline["baseline_status"] == "qe_reference_bundle_baseline_not_admitted"


def test_cli_writes_index(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bundle-dir",
            str(bundle),
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
    index = json.loads((out_dir / "qe_baseline_comparison_index.json").read_text(encoding="utf-8"))
    assert index["passed"] is True


def test_cli_materializes_existing_index(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    out_dir = tmp_path / "baselines"
    _write_fake_bundle(bundle)
    build_baseline_comparisons_from_six_class_bundle(bundle, out_dir)

    for name in (
        "dft_scf_six_class_qe_baseline_materialization.json",
        "dft_scf_six_class_qe_baseline_materialization_validation.json",
        "dft_scf_six_class_qe_baseline_materialization_status.json",
    ):
        (out_dir / name).unlink()

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--index-path",
            str(out_dir / "qe_baseline_comparison_index.json"),
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    materialization = json.loads(
        (out_dir / "dft_scf_six_class_qe_baseline_materialization.json").read_text(
            encoding="utf-8"
        )
    )
    assert materialization["status"] == "passed"
    assert materialization["pure_software_qe_baseline_only"] is True
    assert materialization["hardware_acceleration_evidence"] is False


def test_materialization_triplet_requires_referenced_row_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "baselines"
    records = [
        {
            "case_id": f"{class_id}_case",
            "class_id": class_id,
            "status": "passed",
            "pure_software_qe_baseline": True,
            "baseline_comparison": str(out_dir / f"{class_id}_case" / "baseline_comparison.json"),
            "blockers": [],
        }
        for class_id in STRICT_DFT_QE_WORKLOAD_CLASSES
    ]
    index_path = out_dir / "qe_baseline_comparison_index.json"
    _write_json(
        index_path,
        {
            "schema_version": "dse.qe_pure_software_baseline_from_six_class_bundle_index.v1",
            "status": "passed",
            "passed": True,
            "case_count": len(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "passed_case_count": len(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "strict_scf_class_ids": list(STRICT_DFT_QE_WORKLOAD_CLASSES),
            "missing_strict_scf_class_ids": [],
            "records": records,
            "blockers": [],
        },
    )

    materialization = materialize_qe_baseline_triplet_from_index(index_path)
    validation = json.loads(
        (out_dir / "dft_scf_six_class_qe_baseline_materialization_validation.json").read_text(
            encoding="utf-8"
        )
    )

    assert materialization["status"] == "blocked"
    assert materialization["pure_software_qe_baseline_only"] is False
    assert validation["valid"] is False
    assert any(
        error.startswith("baseline_comparison_missing:")
        for error in validation["errors"]
    )
