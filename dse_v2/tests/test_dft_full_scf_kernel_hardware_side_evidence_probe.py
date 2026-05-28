"""Fail-closed probes for full-SCF kernel hardware side evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from dse_v2.reference_workloads.dft_full_scf_evidence_gap import (
    build_kernel_hardware_side_evidence_progress,
)


SCRIPT = Path("dse_v2/scripts/dse/probe_dft_full_scf_kernel_hardware_side_evidence.py")
KERNEL_ID = "complex_gemm_gemv_tile"
REQUIRED_STAGE_IDS = (
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_parsed_stage(
    root: Path,
    *,
    candidate_id: str,
    stage_id: str,
    kernel_id: str = KERNEL_ID,
    verdict: str = "passed",
    workload_case_id: str = "small_multi_k_scf_case",
    passed: bool | None = None,
    suffix: str = ".json",
) -> Path:
    path = (
        root
        / "parsed_hard_gate_results"
        / candidate_id
        / kernel_id
        / f"{stage_id}_parsed_result{suffix}"
    )
    payload: dict[str, Any] = {
        "schema_version": "dse.dft.hardware_parsed_stage_result.v1",
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "kernel_id": kernel_id,
        "stage_id": stage_id,
        "verdict": verdict,
        "parser_id": f"unit_{stage_id}_parser",
        "blocker_ids": [] if verdict == "passed" else [f"{stage_id}_blocked"],
        "raw_evidence_refs": [
            {
                "path": f"candidate_specific_evidence/{candidate_id}/{kernel_id}/{stage_id}.log",
                "sha256": f"{stage_id}_sha256",
                "hash_algorithm": "sha256",
            }
        ],
        "metrics": {"unit_metric": 1.0},
        "claim_boundary": "unit parsed result",
    }
    if passed is not None:
        payload["passed"] = passed
    if suffix == ".jsonl":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    else:
        _write_json(path, payload)
    return path


def test_hpsi_hardware_side_repair_guidance_points_to_hpsi_vloc_producer_surface(
    tmp_path: Path,
) -> None:
    candidate_id = "cand_hpsi_vloc"
    for kernel_id in ("h_psi", "vloc_psi_k_acc"):
        for stage_id in REQUIRED_STAGE_IDS:
            _write_parsed_stage(
                tmp_path,
                candidate_id=candidate_id,
                kernel_id=kernel_id,
                stage_id=stage_id,
            )

        progress = build_kernel_hardware_side_evidence_progress(
            candidate_id=candidate_id,
            workload_case_id="small_multi_k_scf_case",
            kernel_id=kernel_id,
            source_roots=[tmp_path],
        )

        queue_item = progress["executable_repair_queue"][0]
        guidance = queue_item["next_command_or_fix"]
        assert "h_psi/vloc_psi" in guidance
        assert "run_qe_accelerated_numeric_producer.py" in guidance
        assert "--enable-hpsi-component-sidecar" in guidance
        assert "diagonalization/s_psi" not in guidance


def test_kernel_hardware_side_probe_records_real_ppa_without_upgrading_numeric_or_runtime(
    tmp_path: Path,
) -> None:
    candidate_id = "cand_0715923dc14b29cd"
    for stage_id in REQUIRED_STAGE_IDS:
        _write_parsed_stage(tmp_path, candidate_id=candidate_id, stage_id=stage_id)

    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id=candidate_id,
        workload_case_id="small_multi_k_scf_case",
        kernel_id=KERNEL_ID,
        source_roots=[tmp_path],
    )

    assert progress["status"] == "hardware_side_evidence_found_qe_consumption_required"
    assert progress["hardware_side_evidence_found"] is True
    assert progress["hardware_stage_pass_count"] == len(REQUIRED_STAGE_IDS)
    assert progress["full_scf_seed_eligible"] is False
    assert progress["trusted_runtime_event_found"] is False
    assert progress["trusted_qe_consumed_numeric_row_found"] is False
    assert "trusted_runtime_event_missing::complex_gemm_gemv_tile" in progress["remaining_blockers"]
    assert (
        "trusted_qe_consumed_numeric_row_missing::complex_gemm_gemv_tile"
        in progress["remaining_blockers"]
    )
    assert "not trusted QE-consumed numeric evidence" in progress["claim_boundary"]
    queue_item = progress["executable_repair_queue"][0]
    assert queue_item["status"] == "producer_required_after_hardware_side_evidence_found"
    assert "diagonalization/s_psi" in queue_item["next_command_or_fix"]
    assert "QE_OFFLOAD_KERNEL_EVIDENCE_JSON" in queue_item["next_command_or_fix"]


def test_kernel_hardware_side_probe_cli_writes_fail_closed_progress(tmp_path: Path) -> None:
    candidate_id = "cand_0715923dc14b29cd"
    for stage_id in REQUIRED_STAGE_IDS:
        _write_parsed_stage(tmp_path, candidate_id=candidate_id, stage_id=stage_id)
    out_path = tmp_path / "complex_gemm_gemv_tile_hardware_side_evidence_progress.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidate-id",
            candidate_id,
            "--workload-case-id",
            "small_multi_k_scf_case",
            "--kernel-id",
            KERNEL_ID,
            "--source-root",
            str(tmp_path),
            "--out",
            str(out_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert summary["status"] == "hardware_side_evidence_found_qe_consumption_required"
    assert summary["scanned_json_file_count"] == len(REQUIRED_STAGE_IDS)
    assert payload["hardware_side_evidence_found"] is True
    assert payload["full_scf_seed_eligible"] is False
    assert payload["trusted_runtime_events_emitted"] == []


def test_kernel_hardware_side_probe_fail_closes_wrong_candidate(tmp_path: Path) -> None:
    for stage_id in REQUIRED_STAGE_IDS:
        _write_parsed_stage(tmp_path, candidate_id="cand_other", stage_id=stage_id)

    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id="cand_0715923dc14b29cd",
        workload_case_id="small_multi_k_scf_case",
        kernel_id=KERNEL_ID,
        source_roots=[tmp_path],
    )

    assert progress["status"] == "hardware_side_evidence_missing_or_incomplete"
    assert progress["hardware_side_evidence_found"] is False
    assert progress["hardware_stage_pass_count"] == 0
    assert progress["full_scf_seed_eligible"] is False
    assert all(record["status"] == "missing_or_blocked" for record in progress["stage_records"])


def test_kernel_hardware_side_probe_rejects_declared_wrong_workload_and_passed_false(
    tmp_path: Path,
) -> None:
    candidate_id = "cand_0715923dc14b29cd"
    for stage_id in REQUIRED_STAGE_IDS:
        workload_case_id = "other_case" if stage_id == "hls_or_rtl_sim" else "small_multi_k_scf_case"
        passed = False if stage_id == "dc_asic_synth_timing_area" else None
        _write_parsed_stage(
            tmp_path,
            candidate_id=candidate_id,
            stage_id=stage_id,
            workload_case_id=workload_case_id,
            passed=passed,
        )

    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id=candidate_id,
        workload_case_id="small_multi_k_scf_case",
        kernel_id=KERNEL_ID,
        source_roots=[tmp_path],
    )

    assert progress["status"] == "hardware_side_evidence_missing_or_incomplete"
    assert progress["hardware_side_evidence_found"] is False
    assert progress["hardware_stage_pass_count"] == len(REQUIRED_STAGE_IDS) - 2
    assert "hls_or_rtl_sim" in progress["missing_or_blocked_stage_ids"]
    assert "dc_asic_synth_timing_area" in progress["missing_or_blocked_stage_ids"]


def test_kernel_hardware_side_probe_scans_jsonl_in_exact_parsed_directory(tmp_path: Path) -> None:
    candidate_id = "cand_0715923dc14b29cd"
    for stage_id in REQUIRED_STAGE_IDS:
        _write_parsed_stage(tmp_path, candidate_id=candidate_id, stage_id=stage_id, suffix=".jsonl")

    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id=candidate_id,
        workload_case_id="small_multi_k_scf_case",
        kernel_id=KERNEL_ID,
        source_roots=[tmp_path],
    )

    assert progress["status"] == "hardware_side_evidence_found_qe_consumption_required"
    assert progress["hardware_side_evidence_found"] is True
    assert progress["hardware_stage_pass_count"] == len(REQUIRED_STAGE_IDS)
    assert progress["scanned_json_file_count"] == len(REQUIRED_STAGE_IDS)


def test_kernel_hardware_side_probe_preserves_blockers_from_all_failed_observations(
    tmp_path: Path,
) -> None:
    candidate_id = "cand_0715923dc14b29cd"
    blocked_stage_id = "hls_or_rtl_sim"
    for stage_id in REQUIRED_STAGE_IDS:
        if stage_id != blocked_stage_id:
            _write_parsed_stage(tmp_path, candidate_id=candidate_id, stage_id=stage_id)

    blocked_dir = tmp_path / "parsed_hard_gate_results" / candidate_id / KERNEL_ID
    for label in ("a", "b"):
        _write_json(
            blocked_dir / f"{blocked_stage_id}_{label}_parsed_result.json",
            {
                "schema_version": "dse.dft.hardware_parsed_stage_result.v1",
                "candidate_id": candidate_id,
                "workload_case_id": "small_multi_k_scf_case",
                "kernel_id": KERNEL_ID,
                "stage_id": blocked_stage_id,
                "verdict": "failed",
                "blocker_ids": [f"{blocked_stage_id}_{label}_blocked"],
                "raw_evidence_refs": [
                    {
                        "path": (
                            f"candidate_specific_evidence/{candidate_id}/{KERNEL_ID}/"
                            f"{blocked_stage_id}_{label}.log"
                        ),
                        "sha256": f"{blocked_stage_id}_{label}_sha256",
                    }
                ],
            },
        )

    progress = build_kernel_hardware_side_evidence_progress(
        candidate_id=candidate_id,
        workload_case_id="small_multi_k_scf_case",
        kernel_id=KERNEL_ID,
        source_roots=[tmp_path],
    )

    blocked_record = next(
        record for record in progress["stage_records"] if record["stage_id"] == blocked_stage_id
    )
    assert blocked_record["status"] == "missing_or_blocked"
    assert f"{blocked_stage_id}_a_blocked" in blocked_record["blockers"]
    assert f"{blocked_stage_id}_b_blocked" in blocked_record["blockers"]
