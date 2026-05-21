#!/usr/bin/env python3
"""DFT hardware completion workplan tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_completion_workplan import (
    DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA,
    build_dft_hardware_completion_workplan,
    validate_dft_hardware_completion_workplan,
    write_dft_hardware_completion_workplan,
)
from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNELS


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixtures(tmp_path: Path) -> dict[str, Path]:
    ledger = {
        "schema_version": "dse.codesign.per_candidate_evidence_ledger.v1",
        "release_id": "release-test",
        "rows": [{"candidate_id": "cand-a"}, {"candidate_id": "cand-b"}],
    }
    matrix = {
        "schema_version": "dse.dft_scf.hardware_evidence_matrix.v1",
        "status": "passed",
        "trusted": True,
        "kernel_rows": [
            {
                "kernel_id": kernel["kernel_id"],
                "claim_allowed": True,
                "trusted": True,
                "hardware_claim_gate": {
                    "stage_results": [
                        {"stage_id": "golden_correctness", "passed": True},
                        {"stage_id": "hls_or_rtl_sim", "passed": True},
                        {"stage_id": "hls_or_rtl_synth", "passed": True},
                        {"stage_id": "vivado_fpga_synth_or_impl", "passed": True},
                    ]
                },
            }
            for kernel in MAJOR_SCF_KERNELS
        ],
    }
    tools = {
        "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
        "status": "passed",
        "tool_rows": [
            {"tool": "vcs", "available": True},
            {"tool": "vivado", "available": True},
            {"tool": "dc_shell", "available": True},
        ],
    }
    return {
        "ledger": _write_json(tmp_path / "per_candidate_evidence_ledger.json", ledger),
        "matrix": _write_json(tmp_path / "dft_hardware_evidence_matrix.json", matrix),
        "tools": _write_json(tmp_path / "ic_eda_tool_availability.json", tools),
    }


def test_hardware_completion_workplan_expands_candidate_kernel_stage_items_fail_closed(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)

    status = write_dft_hardware_completion_workplan(
        tmp_path / "workplan",
        per_candidate_evidence_ledger_path=paths["ledger"],
        dft_hardware_evidence_matrix_path=paths["matrix"],
        ic_eda_tool_availability_path=paths["tools"],
    )

    assert status["status"] == "passed"
    payload = json.loads((tmp_path / "workplan" / "dft_hardware_completion_workplan.json").read_text())
    validation = json.loads((tmp_path / "workplan" / "dft_hardware_completion_workplan_validation.json").read_text())
    assert payload["schema_version"] == DFT_HARDWARE_COMPLETION_WORKPLAN_SCHEMA
    assert payload["candidate_count"] == 2
    assert payload["major_kernel_count"] == len(MAJOR_SCF_KERNELS)
    assert payload["required_work_item_count"] == 2 * len(MAJOR_SCF_KERNELS) * 5
    assert payload["blocked_work_item_count"] == payload["required_work_item_count"]
    assert payload["shared_microkernel_smoke_stage_present_count"] == 2 * len(MAJOR_SCF_KERNELS) * 4
    assert payload["hardware_completion_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_hardware_completion_workplan_auto_attaches_candidate_universe_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    paths = _fixtures(run_dir / "dft_ledger")
    _write_json(
        run_dir / "release_domain_current36" / "candidate_universe_manifest.json",
        {
            "schema_version": "dse.codesign.candidate_universe_manifest.v1",
            "candidates": [
                {
                    "candidate_id": "cand-a",
                    "design_candidate_id": "design-a",
                    "assignments": {
                        "hardware_microarchitecture": "host_fpga_minimal_v0",
                        "mapping_data_layout": "fft_grid_hbm_tiled",
                    },
                    "identity_assignments": {
                        "hardware_microarchitecture": "host_fpga_minimal_v0",
                        "mapping_data_layout": "fft_grid_hbm_tiled",
                    },
                    "non_identity_assignments": {"dft_phase_hotspot_selection": "scf_hpsi_density"},
                }
            ],
        },
    )

    payload = build_dft_hardware_completion_workplan(
        per_candidate_evidence_ledger_path=paths["ledger"],
        dft_hardware_evidence_matrix_path=paths["matrix"],
        ic_eda_tool_availability_path=paths["tools"],
    )

    cand_a_rows = [row for row in payload["work_items"] if row["candidate_id"] == "cand-a"]
    assert cand_a_rows
    assert cand_a_rows[0]["design_candidate_id"] == "design-a"
    assert cand_a_rows[0]["assignments"]["hardware_microarchitecture"] == "host_fpga_minimal_v0"
    assert payload["source_artifacts"]["candidate_universe_manifest"]["exists"] is True


def test_hardware_completion_workplan_validator_rejects_claim_upgrade_and_fabricated_evidence(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)
    payload = build_dft_hardware_completion_workplan(
        per_candidate_evidence_ledger_path=paths["ledger"],
        dft_hardware_evidence_matrix_path=paths["matrix"],
        ic_eda_tool_availability_path=paths["tools"],
    )

    fabricated = json.loads(json.dumps(payload))
    fabricated["work_items"][0]["candidate_specific_evidence_present"] = True
    assert validate_dft_hardware_completion_workplan(fabricated)["valid"] is False

    upgraded = json.loads(json.dumps(payload))
    upgraded["hardware_completion_eligible"] = True
    upgraded["deliverable_complete"] = True
    assert validate_dft_hardware_completion_workplan(upgraded)["valid"] is False

    duplicate = json.loads(json.dumps(payload))
    duplicate["work_items"][1]["work_item_id"] = duplicate["work_items"][0]["work_item_id"]
    assert validate_dft_hardware_completion_workplan(duplicate)["valid"] is False


def test_build_hardware_completion_workplan_cli_writes_artifacts(tmp_path: Path) -> None:
    paths = _fixtures(tmp_path)
    out_dir = tmp_path / "cli_workplan"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_completion_workplan.py",
            "--out",
            str(out_dir),
            "--per-candidate-evidence-ledger",
            str(paths["ledger"]),
            "--dft-hardware-evidence-matrix",
            str(paths["matrix"]),
            "--ic-eda-tool-availability",
            str(paths["tools"]),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "dft_hardware_completion_workplan.json").exists()
    assert json.loads((out_dir / "dft_hardware_completion_workplan_validation.json").read_text())["valid"] is True
