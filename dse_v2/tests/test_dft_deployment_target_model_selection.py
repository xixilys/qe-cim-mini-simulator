#!/usr/bin/env python3
"""DFT deployment target-model selection tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_deployment_target_model_selection import (
    build_dft_deployment_target_model_selection,
    validate_dft_deployment_target_model_selection,
    write_dft_deployment_target_model_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "build_dft_deployment_target_model_selection.py"


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _deployment_plan(profile: dict, *, target: str = "fpga", candidate_id: str = "cand-fpga") -> dict:
    return {
        "schema_version": "dse.step4.queue_deployment_recommendation_plan.v1",
        "status": "proposal_only_hard_gates_required",
        "hard_gate_work_items": [
            {
                "work_item_id": f"deployment-hard-gate::{target}::{candidate_id}",
                "target": target,
                "candidate_id": candidate_id,
                "architecture_id": f"arch-{candidate_id}",
                "canonical_stage_ids": ["vivado_fpga_synth_or_impl"]
                if target == "fpga"
                else ["dc_asic_synth_timing_area"],
                "target_execution_profile": profile,
                "trusted_deployment_claim": False,
                "release_completion_eligible": False,
            }
        ],
        "trusted_final_claim": False,
        "release_completion_eligible": False,
    }


def _u280_profile() -> dict:
    return {
        "profile_id": "fpga_hbm_unbounded_budget_vivado_route_profile_v1",
        "target": "fpga",
        "model_binding_required": True,
        "selected_model": None,
        "required_model_fields": [
            "vendor",
            "board_or_device_model",
            "part_number",
            "memory_capacity_bytes",
            "memory_bandwidth_gbps",
            "vivado_part",
            "vivado_board_part",
        ],
        "recommended_model_selection": {
            "recommended_model_id": "amd_alveo_u280_a_u280",
        },
        "recommended_model_candidates": [
            {
                "rank": 1,
                "model_id": "amd_alveo_u280_a_u280",
                "vendor": "AMD",
                "board_or_device_model": "AMD Alveo U280 Data Center Accelerator Card",
                "part_number": "A-U280",
                "memory_capacity_bytes": 8 * 1024**3,
                "memory_bandwidth_gbps": 460,
                "vivado_part": "xcu280-fsvh2892-2L-e",
                "vivado_board_part": None,
            }
        ],
    }


def test_target_model_selection_picks_recommended_u280_without_board_part_requirement(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(_u280_profile()),
    )

    selection = build_dft_deployment_target_model_selection(run_dir)
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    assert selection["status"] == "target_model_selection_available"
    row = selection["selection_rows"][0]
    assert row["target"] == "fpga"
    assert row["candidate_id"] == "cand-fpga"
    assert row["selected_model_source"] == "deployment_plan_recommended_model_candidates"
    assert row["selected_model"]["model_id"] == "amd_alveo_u280_a_u280"
    assert row["selected_model"]["vivado_part"] == "xcu280-fsvh2892-2L-e"
    assert "vivado_board_part" not in row["required_model_fields"]
    assert row["missing_required_model_fields"] == []
    assert selection["hardware_completion_eligible"] is False
    assert selection["deliverable_complete"] is False


def test_target_model_selection_can_override_stale_plan_with_builtin_u280_catalog(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    stale_profile = _u280_profile()
    stale_profile["recommended_model_selection"] = {
        "recommended_model_id": "amd_alveo_v80_a_v80_p64g_pq_g",
    }
    stale_profile["recommended_model_candidates"] = []
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(stale_profile),
    )

    selection = build_dft_deployment_target_model_selection(
        run_dir,
        selected_model_ids={"fpga": "amd_alveo_u280_a_u280"},
    )
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    row = selection["selection_rows"][0]
    assert row["selected_model_source"] == "builtin_dft_model_catalog"
    assert row["selected_model"]["model_id"] == "amd_alveo_u280_a_u280"
    assert row["missing_required_model_fields"] == []


def test_target_model_selection_can_prefer_local_vivado_supported_smoke_model(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(_u280_profile()),
    )

    selection = build_dft_deployment_target_model_selection(
        run_dir,
        fpga_vivado_supported_parts=["xc7a35tcsg324-1"],
        prefer_fpga_model_with_supported_vivado_part=True,
    )
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    assert selection["status"] == "target_model_selection_available"
    assert selection["selection_policy"]["prefer_fpga_model_with_supported_vivado_part"] is True
    assert selection["selection_policy"]["fpga_vivado_supported_parts"] == ["xc7a35tcsg324-1"]
    row = selection["selection_rows"][0]
    assert row["target"] == "fpga"
    assert row["selected_model_source"] == "builtin_dft_model_catalog_vivado_supported_part"
    assert row["selection_status"] == "selected_local_vivado_supported_model_pending_binding"
    assert row["selected_model"]["model_id"] == "artix7_xc7a35t_smoke"
    assert row["selected_model"]["vivado_part"] == "xc7a35tcsg324-1"
    assert row["selected_model"]["claim_level"] == "smoke_progress_only_not_hbm_alveo_deployment"
    assert row["missing_required_model_fields"] == []
    assert selection["hardware_completion_eligible"] is False
    assert selection["deliverable_complete"] is False


def test_target_model_selection_explicit_fpga_override_beats_local_vivado_preference(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(_u280_profile()),
    )

    selection = build_dft_deployment_target_model_selection(
        run_dir,
        selected_model_ids={"fpga": "amd_alveo_u280_a_u280"},
        fpga_vivado_supported_parts=["xc7a35tcsg324-1"],
        prefer_fpga_model_with_supported_vivado_part=True,
    )
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    row = selection["selection_rows"][0]
    assert row["selected_model_source"] == "deployment_plan_recommended_model_candidates"
    assert row["selected_model"]["model_id"] == "amd_alveo_u280_a_u280"
    assert row["selected_model"]["vivado_part"] == "xcu280-fsvh2892-2L-e"


def test_target_model_selection_rejects_fpga_device_only_legacy_model(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    legacy_profile = {
        "profile_id": "fpga_legacy_device_only_profile",
        "target": "fpga",
        "model_binding_required": True,
        "selected_model": None,
        "required_model_fields": ["device"],
        "recommended_model_candidates": [
            {
                "rank": 1,
                "model_id": "legacy-device-only",
                "device": "xc7a35tcsg324-1",
            }
        ],
    }
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(legacy_profile),
    )

    selection = build_dft_deployment_target_model_selection(run_dir)
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    assert selection["status"] == "partial_target_model_selection_available"
    row = selection["selection_rows"][0]
    assert "device" not in row["required_model_fields"]
    assert "vivado_part" in row["required_model_fields"]
    assert "vivado_part" in row["missing_required_model_fields"]
    assert selection["blockers"][0]["blocker_id"] == "selected_model_missing_required_fields"


def test_target_model_selection_can_emit_asic_probe_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    profile = {
        "profile_id": "asic_dc_real_target_library_profile_v1",
        "target": "asic",
        "model_binding_required": True,
        "selected_model": None,
        "required_model_fields": [
            "library_name",
            "library_db_path",
            "process_node",
            "voltage_corner",
            "temperature_corner",
            "dc_target_library",
        ],
    }
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(profile, target="asic", candidate_id="cand-asic"),
    )

    status = write_dft_deployment_target_model_selection(
        run_dir,
        dc_library_db_paths=["/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db"],
        allow_asic_model_inference_from_dc_probe=True,
    )
    selection = json.loads((run_dir / "dft_deployment_target_model_selection.json").read_text())
    validation = json.loads((run_dir / "dft_deployment_target_model_selection_validation.json").read_text())

    assert status["status"] == "target_model_selection_available"
    assert status["validation_status"] == "passed"
    assert validation["valid"] is True
    row = selection["selection_rows"][0]
    assert row["target"] == "asic"
    assert row["selected_model_source"] == "dc_target_library_probe"
    assert row["selected_model"]["dc_target_library"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert row["missing_required_model_fields"] == []


def test_target_model_selection_supports_asic_selected_model_id_override(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    profile = {
        "profile_id": "asic_dc_real_target_library_profile_v1",
        "target": "asic",
        "model_binding_required": True,
        "selected_model": None,
        "required_model_fields": [
            "library_name",
            "library_db_path",
            "process_node",
            "voltage_corner",
            "temperature_corner",
            "dc_target_library",
        ],
    }
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(profile, target="asic", candidate_id="cand-asic"),
    )

    selection = build_dft_deployment_target_model_selection(
        run_dir,
        selected_model_ids={"asic": "fsa0a_c_generic_core_tt1p8v25c"},
        dc_library_db_paths=["/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db"],
    )
    validation = validate_dft_deployment_target_model_selection(selection)

    assert validation["valid"] is True
    assert selection["status"] == "target_model_selection_available"
    row = selection["selection_rows"][0]
    assert row["selected_model_source"] == "selected_model_id_override"
    assert row["selection_status"] == "selected_model_from_override_pending_binding"
    assert row["selected_model"]["model_source"] == "selected_model_id_override"
    assert row["selected_model"]["dc_target_library"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert row["selected_model"]["library_db_path"] == "/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db"
    assert row["missing_required_model_fields"] == []


def test_target_model_selection_cli_writes_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(_u280_profile()),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--run-dir",
            str(run_dir),
            "--selected-model-id",
            "fpga=amd_alveo_u280_a_u280",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(result.stdout)
    assert status["status"] == "target_model_selection_available"
    assert (run_dir / "dft_deployment_target_model_selection.json").exists()
    assert (run_dir / "dft_deployment_target_model_selection_status.json").exists()


def test_target_model_selection_cli_accepts_local_vivado_supported_preference(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(_u280_profile()),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--run-dir",
            str(run_dir),
            "--vivado-supported-part",
            "xc7a35tcsg324-1",
            "--prefer-fpga-model-with-supported-vivado-part",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    selection = json.loads((run_dir / "dft_deployment_target_model_selection.json").read_text())
    assert selection["selection_policy"]["prefer_fpga_model_with_supported_vivado_part"] is True
    row = selection["selection_rows"][0]
    assert row["selected_model"]["model_id"] == "artix7_xc7a35t_smoke"
    assert row["selected_model"]["claim_level"] == "smoke_progress_only_not_hbm_alveo_deployment"


def test_target_model_selection_cli_accepts_asic_selected_model_override(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    profile = {
        "profile_id": "asic_dc_real_target_library_profile_v1",
        "target": "asic",
        "model_binding_required": True,
        "selected_model": None,
        "required_model_fields": [
            "library_name",
            "library_db_path",
            "process_node",
            "voltage_corner",
            "temperature_corner",
            "dc_target_library",
        ],
    }
    _write_json(
        run_dir / "step3_queue" / "deployment_recommendation_plan.json",
        _deployment_plan(profile, target="asic", candidate_id="cand-asic"),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--run-dir",
            str(run_dir),
            "--selected-model-id",
            "asic=fsa0a_c_generic_core_tt1p8v25c",
            "--dc-library-db-path",
            "/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    selection = json.loads((run_dir / "dft_deployment_target_model_selection.json").read_text())
    row = selection["selection_rows"][0]
    assert row["selected_model_source"] == "selected_model_id_override"
    assert row["selected_model"]["dc_target_library"] == "fsa0a_c_generic_core_tt1p8v25c"
