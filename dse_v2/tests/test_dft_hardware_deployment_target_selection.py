#!/usr/bin/env python3
"""DFT hardware deployment target-selection producer tests."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_deployment_recommendation_readiness import (
    build_dft_hardware_deployment_recommendation_readiness,
)
from dse_v2.reference_workloads.dft_hardware_deployment_target_selection import (
    DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA,
    build_dft_hardware_deployment_target_selection,
    validate_dft_hardware_deployment_target_selection,
    write_dft_hardware_deployment_target_selection,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fresh_source_ref(path: Path, *, source_kind: str) -> dict:
    return {
        "path": str(path),
        "source_kind": source_kind,
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "hash_algorithm": "sha256",
    }


def _fpga_catalog_payload(source_ref: dict) -> dict:
    return {
        "schema_version": "dse.dft.fpga_target_catalog.v1",
        "source_refs": [source_ref],
        "targets": [
            {
                "target_device_id": "small-fpga",
                "vendor": "xilinx",
                "part": "xcvu9p-small-test",
                "family": "virtex-ultrascale-plus",
                "capacity": {"slice_luts": 1_000_000, "dsps": 4_000, "block_ram_tiles": 1_000},
                "source_refs": [source_ref],
            },
            {
                "target_device_id": "large-fpga",
                "vendor": "xilinx",
                "part": "xcvu19p-largest-test",
                "family": "virtex-ultrascale-plus",
                "capacity": {"slice_luts": 2_000_000, "dsps": 8_000, "block_ram_tiles": 2_000},
                "source_refs": [source_ref],
            },
        ],
    }


def _asic_probe_payload(source_ref: dict) -> dict:
    return {
        "schema_version": "dse.dft.asic_target_library_probe.v1",
        "status": "passed",
        "source_refs": [source_ref],
        "target_libraries": [
            {
                "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                "process_node": "library_defined",
                "pvt_corner": "tt_1p8v_25c",
                "voltage_v": 1.8,
                "temperature_c": 25,
                "discovery_status": "real_target_library_present",
                "source_refs": [source_ref],
            }
        ],
    }


def _seed_ready_inputs(run_dir: Path) -> None:
    fpga_source_ref = _fresh_source_ref(
        _write_text(
            run_dir / "raw_sources" / "fpga_vendor_catalog_snapshot.txt",
            "captured vendor catalog rows for xcvu9p-small-test and xcvu19p-largest-test\n",
        ),
        source_kind="vendor_fpga_catalog_snapshot",
    )
    asic_source_ref = _fresh_source_ref(
        _write_text(
            run_dir / "raw_sources" / "dc_target_library_probe.log",
            "dc_shell probe found fsa0a_c_generic_core_tt1p8v25c at tt_1p8v_25c\n",
        ),
        source_kind="dc_target_library_probe_transcript",
    )
    _write_json(
        run_dir / "fpga_target_catalog.json",
        _fpga_catalog_payload(fpga_source_ref),
    )
    _write_json(
        run_dir / "asic_target_library_probe.json",
        _asic_probe_payload(asic_source_ref),
    )
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "dc_shell", "available": True},
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
            ],
        },
    )


def _seed_readiness_dependencies(run_dir: Path) -> None:
    _write_json(
        run_dir / "dft_hardware_completion_workplan.json",
        {
            "schema_version": "dse.dft.hardware_completion_workplan.v1",
            "release_id": "release-target-selection-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "work_items": [
                {
                    "work_item_id": f"cand-a:fft_ifft_ffft:{stage_id}",
                    "candidate_id": "cand-a",
                    "kernel_id": "fft_ifft_ffft",
                    "stage_id": stage_id,
                    "blocked": False,
                    "candidate_specific_evidence_present": True,
                }
                for stage_id in (
                    "golden_correctness",
                    "hls_or_rtl_sim",
                    "hls_or_rtl_synth",
                    "vivado_fpga_synth_or_impl",
                    "dc_asic_synth_timing_area",
                )
            ],
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_completion_workplan_validation.json",
        {"schema_version": "dse.dft.hardware_completion_workplan_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_tie_breaker_execution_queue.json",
        {
            "schema_version": "dse.dft.hardware_tie_breaker_execution_queue.v1",
            "status": "no_tie_breaker_work_items",
            "work_item_count": 0,
            "work_items": [],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution.json",
        {
            "schema_version": "dse.dft.architecture_winner_resolution.v1",
            "status": "resolved_hardware_ppa_deployment_winners",
            "release_id": "release-target-selection-test",
            "candidate_count": 1,
            "ranking_eligible_candidate_count": 1,
            "hardware_completion_eligible": True,
            "hardware_winner_resolution_eligible": True,
            "deliverable_complete": False,
            "deployments": {
                "fpga": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "winner": {"candidate_id": "cand-a", "rank": 1},
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [],
                },
                "asic": {
                    "status": "resolved_unique_hardware_ppa_winner",
                    "resolved": True,
                    "winner": {"candidate_id": "cand-a", "rank": 1},
                    "top_rank_candidate_count": 1,
                    "top_rank_candidate_ids": ["cand-a"],
                    "required_next_evidence": [],
                },
            },
        },
    )
    _write_json(
        run_dir / "dft_architecture_winner_resolution_validation.json",
        {"schema_version": "dse.dft.architecture_winner_resolution_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_available",
            "fpga_ranking": [
                {
                    "candidate_id": "cand-a",
                    "rank": 1,
                    "ranking_target": "fpga",
                    "target_required_stage_ids": [
                        "golden_correctness",
                        "hls_or_rtl_sim",
                        "hls_or_rtl_synth",
                        "vivado_fpga_synth_or_impl",
                    ],
                    "ranking_eligible": True,
                    "candidate_gate_passed": True,
                    "target_specific_blockers": [],
                    "candidate_identity": {
                        "candidate_id": "cand-a",
                        "deployment_boundary": {"accelerated_kernels": ["fft_ifft_ffft"]},
                        "host_device_partition": {
                            "accelerated_node_ids": ["fft_ifft_ffft"],
                            "cpu_retained_node_ids": ["scf_control"],
                        },
                        "architecture_template_parameters": {"template_id": "fpga_template"},
                        "mapping_layout": {"layout_id": "layout-a"},
                        "runtime_co_scheduling": {"policy_id": "overlap_dma_compute"},
                        "descriptor_granularity": {"granularity": "kernel_descriptor"},
                        "fallback_policy": {"policy_id": "cpu_fallback"},
                        "target_platform": {"deployment_target": "fpga"},
                    },
                }
            ],
            "asic_ranking": [
                {
                    "candidate_id": "cand-a",
                    "rank": 1,
                    "ranking_target": "asic",
                    "target_required_stage_ids": [
                        "golden_correctness",
                        "hls_or_rtl_sim",
                        "hls_or_rtl_synth",
                        "dc_asic_synth_timing_area",
                    ],
                    "ranking_eligible": True,
                    "candidate_gate_passed": True,
                    "target_specific_blockers": [],
                    "candidate_identity": {
                        "candidate_id": "cand-a",
                        "deployment_boundary": {"accelerated_kernels": ["fft_ifft_ffft"]},
                        "host_device_partition": {
                            "accelerated_node_ids": ["fft_ifft_ffft"],
                            "cpu_retained_node_ids": ["scf_control"],
                        },
                        "architecture_template_parameters": {"template_id": "asic_template"},
                        "mapping_layout": {"layout_id": "layout-a"},
                        "runtime_co_scheduling": {"policy_id": "overlap_dma_compute"},
                        "descriptor_granularity": {"granularity": "kernel_descriptor"},
                        "fallback_policy": {"policy_id": "cpu_fallback"},
                        "target_platform": {"deployment_target": "asic"},
                    },
                }
            ],
            "deliverable_complete": False,
            "trusted_final_claim": False,
        },
    )
    _write_json(
        run_dir / "dft_hardware_ppa_ranking_validation.json",
        {"schema_version": "dse.dft.hardware_ppa_ranking_validation.v1", "valid": True, "errors": []},
    )


def test_target_selection_blocks_without_catalog_or_library_probe(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["schema_version"] == DFT_HARDWARE_DEPLOYMENT_TARGET_SELECTION_SCHEMA
    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert {blocker["deployment"] for blocker in payload["blockers"]} == {"fpga", "asic"}
    assert validation["valid"] is True


def test_target_selection_rejects_placeholder_fpga_catalog_even_when_hash_backed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    source_ref = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "placeholder_fpga_catalog.txt", "placeholder fpga catalog capture\n"),
        source_kind="vendor_fpga_catalog_snapshot",
    )
    catalog = _fpga_catalog_payload(source_ref)
    catalog["targets"][1]["target_device_id"] = "fpga_unbounded_budget_placeholder"
    _write_json(run_dir / "fpga_target_catalog.json", catalog)

    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["fpga"]["blockers"][0]["blocker_id"] == "fpga_target_catalog_placeholder_input"
    assert payload["deployments"]["asic"]["selection_status"] == "selected"
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert validation["valid"] is True


def test_target_selection_rejects_placeholder_asic_probe_even_when_hash_backed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    source_ref = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "placeholder_asic_probe.log", "placeholder asic probe capture\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    probe = _asic_probe_payload(source_ref)
    probe["target_libraries"][0]["target_library_id"] = "asic_target_library_placeholder"
    probe["target_libraries"][0]["discovery_status"] = "generated_placeholder"
    _write_json(run_dir / "asic_target_library_probe.json", probe)

    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "selected"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["blockers"][0]["blocker_id"] == "asic_target_library_probe_placeholder_input"
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert validation["valid"] is True


def test_target_selection_rejects_self_hashed_inputs_without_raw_source_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw_fpga_source = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "fpga_catalog_capture.txt", "real fpga catalog capture\n"),
        source_kind="vendor_fpga_catalog_snapshot",
    )
    raw_asic_source = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "asic_probe_capture.log", "real asic library probe capture\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    catalog = _fpga_catalog_payload(raw_fpga_source)
    probe = _asic_probe_payload(raw_asic_source)
    catalog.pop("source_refs")
    probe.pop("source_refs")
    for row in catalog["targets"]:
        row.pop("source_refs")
    for row in probe["target_libraries"]:
        row.pop("source_refs")
    _write_json(run_dir / "fpga_target_catalog.json", catalog)
    _write_json(run_dir / "asic_target_library_probe.json", probe)

    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["fpga"]["blockers"][0]["blocker_id"] == (
        "fpga_target_catalog_self_hashed_without_raw_source_refs"
    )
    assert payload["deployments"]["asic"]["blockers"][0]["blocker_id"] == (
        "asic_target_library_probe_self_hashed_without_raw_source_refs"
    )
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert validation["valid"] is True


def test_target_selection_rejects_declared_but_untrusted_raw_source_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    missing_fpga_ref = {
        "path": str(run_dir / "raw_sources" / "missing_vendor_catalog_snapshot.txt"),
        "source_kind": "vendor_fpga_catalog_snapshot",
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(b"missing vendor catalog snapshot\n").hexdigest(),
        "hash_algorithm": "sha256",
    }
    stale_asic_source = _write_text(
        run_dir / "raw_sources" / "dc_target_library_probe_stale.log",
        "dc_shell probe later changed the target-library transcript\n",
    )
    stale_asic_ref = {
        "path": str(stale_asic_source),
        "source_kind": "dc_target_library_probe_transcript",
        "exists": True,
        "status": "present_hash_valid",
        "sha256": hashlib.sha256(b"old dc_shell target-library transcript\n").hexdigest(),
        "hash_algorithm": "sha256",
    }
    _write_json(run_dir / "fpga_target_catalog.json", _fpga_catalog_payload(missing_fpga_ref))
    _write_json(run_dir / "asic_target_library_probe.json", _asic_probe_payload(stale_asic_ref))
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "passed",
            "tool_rows": [
                {"tool": "dc_shell", "available": True},
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["fpga"]["blockers"][0]["blocker_id"] == (
        "fpga_target_catalog_missing_trusted_raw_source_refs"
    )
    assert payload["deployments"]["asic"]["blockers"][0]["blocker_id"] == (
        "asic_target_library_probe_missing_trusted_raw_source_refs"
    )
    assert payload["input_trust_gates"]["fpga_target_catalog"]["trusted"] is False
    assert payload["input_trust_gates"]["asic_target_library_probe"]["trusted"] is False
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["trusted_final_claim"] is False
    assert payload["hardware_completion_eligible"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True


def test_target_selection_keeps_fpga_selected_when_only_asic_probe_is_untrusted(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    raw_asic_source = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "asic_probe_capture.log", "real asic library probe capture\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    probe = _asic_probe_payload(raw_asic_source)
    probe.pop("source_refs")
    for row in probe["target_libraries"]:
        row.pop("source_refs")
    _write_json(run_dir / "asic_target_library_probe.json", probe)

    payload = build_dft_hardware_deployment_target_selection(run_dir)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "selected"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["blockers"][0]["blocker_id"] == (
        "asic_target_library_probe_self_hashed_without_raw_source_refs"
    )


def test_target_selection_keeps_asic_selected_when_only_fpga_catalog_is_untrusted(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    raw_fpga_source = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "fpga_catalog_capture.txt", "real fpga catalog capture\n"),
        source_kind="vendor_fpga_catalog_snapshot",
    )
    catalog = _fpga_catalog_payload(raw_fpga_source)
    catalog.pop("source_refs")
    for row in catalog["targets"]:
        row.pop("source_refs")
    _write_json(run_dir / "fpga_target_catalog.json", catalog)

    payload = build_dft_hardware_deployment_target_selection(run_dir)

    assert payload["status"] == "target_selection_required"
    assert payload["deployment_target_selection_ready"] is False
    assert payload["deployments"]["fpga"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["fpga"]["blockers"][0]["blocker_id"] == (
        "fpga_target_catalog_self_hashed_without_raw_source_refs"
    )
    assert payload["deployments"]["asic"]["selection_status"] == "selected"


def test_target_selection_picks_unbounded_fpga_and_real_asic_library(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)

    status = write_dft_hardware_deployment_target_selection(run_dir)
    payload = json.loads((run_dir / "dft_hardware_deployment_target_selection.json").read_text())
    validation = json.loads((run_dir / "dft_hardware_deployment_target_selection_validation.json").read_text())

    assert status["status"] == "passed"
    assert payload["status"] == "target_selection_ready"
    assert payload["deployment_target_selection_ready"] is True
    assert payload["deployments"]["fpga"]["target_device_id"] == "large-fpga"
    assert payload["deployments"]["fpga"]["part"] == "xcvu19p-largest-test"
    assert payload["deployments"]["fpga"]["budget_policy"] == "unbounded_budget_current_catalog_required"
    assert payload["deployments"]["asic"]["target_library_id"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert payload["deployments"]["asic"]["pvt_corner"] == "tt_1p8v_25c"
    assert payload["can_name_targeted_deployment_recommendation"] is False
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False
    assert validation["valid"] is True



def test_target_selection_prefers_nominal_asic_tt_corner_over_fast_slow(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    ff_ref = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "dc_target_library_probe_ff.log", "dc_shell probe ff corner\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    ss_ref = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "dc_target_library_probe_ss.log", "dc_shell probe ss corner\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    tt_ref = _fresh_source_ref(
        _write_text(run_dir / "raw_sources" / "dc_target_library_probe_tt.log", "dc_shell probe tt corner\n"),
        source_kind="dc_target_library_probe_transcript",
    )
    _write_json(
        run_dir / "asic_target_library_probe.json",
        {
            "schema_version": "dse.dft.asic_target_library_probe.v1",
            "status": "passed",
            "source_refs": [ff_ref, ss_ref, tt_ref],
            "target_libraries": [
                {
                    "target_library_id": "fsa0a_c_generic_core_ff1p98vm40c",
                    "process_node": "library_defined",
                    "pvt_corner": "ff_1p98v_m40c",
                    "voltage_v": 1.98,
                    "temperature_c": -40,
                    "discovery_status": "real_target_library_present",
                    "source_refs": [ff_ref],
                },
                {
                    "target_library_id": "fsa0a_c_generic_core_ss1p62v125c",
                    "process_node": "library_defined",
                    "pvt_corner": "ss_1p62v_125c",
                    "voltage_v": 1.62,
                    "temperature_c": 125,
                    "discovery_status": "real_target_library_present",
                    "source_refs": [ss_ref],
                },
                {
                    "target_library_id": "fsa0a_c_generic_core_tt1p8v25c",
                    "process_node": "library_defined",
                    "pvt_corner": "tt_1p8v_25c",
                    "voltage_v": 1.8,
                    "temperature_c": 25,
                    "discovery_status": "real_target_library_present",
                    "source_refs": [tt_ref],
                },
            ],
        },
    )

    payload = build_dft_hardware_deployment_target_selection(run_dir)

    assert payload["deployments"]["asic"]["target_library_id"] == "fsa0a_c_generic_core_tt1p8v25c"
    assert payload["deployments"]["asic"]["pvt_corner"] == "tt_1p8v_25c"
    assert "nominal/typical TT" in payload["deployments"]["asic"]["pvt_selection_policy"]
    assert payload["can_name_final_recommendation"] is False
    assert payload["deliverable_complete"] is False

def test_target_selection_feeds_readiness_without_final_upgrade(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    _seed_readiness_dependencies(run_dir)
    write_dft_hardware_deployment_target_selection(run_dir)

    readiness = build_dft_hardware_deployment_recommendation_readiness(run_dir)

    assert readiness["deployment_target_selection_ready"] is True
    assert readiness["can_name_hardware_ppa_winners"] is True
    assert readiness["can_name_targeted_deployment_recommendation"] is False
    assert readiness["can_name_final_recommendation"] is False
    assert readiness["deliverable_complete"] is False
    assert readiness["deployments"]["fpga"]["target_selection"]["selected_target"]["part"] == "xcvu19p-largest-test"
    assert (
        readiness["deployments"]["asic"]["target_selection"]["selected_target"]["target_library_id"]
        == "fsa0a_c_generic_core_tt1p8v25c"
    )
    assert readiness["deployments"]["fpga"]["final_recommendation_required_next_evidence"]


def test_target_selection_blocks_asic_when_dc_shell_unavailable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    _write_json(
        run_dir / "ic_eda_tool_availability.json",
        {
            "schema_version": "dse.dft_scf.ic_eda_tool_availability.v1",
            "status": "blocked",
            "tool_rows": [
                {"tool": "dc_shell", "available": False},
                {"tool": "vcs", "available": True},
                {"tool": "vivado", "available": True},
            ],
        },
    )

    payload = build_dft_hardware_deployment_target_selection(run_dir)
    validation = validate_dft_hardware_deployment_target_selection(payload)

    assert payload["status"] == "target_selection_required"
    assert payload["deployments"]["fpga"]["selection_status"] == "selected"
    assert payload["deployments"]["asic"]["selection_status"] == "blocked_target_selection_required"
    assert payload["deployments"]["asic"]["blockers"][0]["blocker_id"] == "dc_shell_unavailable_for_target_library_probe"
    assert payload["deployment_target_selection_ready"] is False
    assert validation["valid"] is True


def test_target_selection_validator_rejects_final_or_winner_upgrades(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    payload = build_dft_hardware_deployment_target_selection(run_dir)

    upgraded = json.loads(json.dumps(payload))
    upgraded["can_name_targeted_deployment_recommendation"] = True
    upgraded["can_name_final_recommendation"] = True
    upgraded["deliverable_complete"] = True
    assert validate_dft_hardware_deployment_target_selection(upgraded)["valid"] is False

    leaked = json.loads(json.dumps(payload))
    leaked["fpga_best_architecture"] = {"candidate_id": "cand-a"}
    assert validate_dft_hardware_deployment_target_selection(leaked)["valid"] is False


def test_target_selection_validator_rejects_stale_or_missing_source_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)
    payload = build_dft_hardware_deployment_target_selection(run_dir)

    stale_refs = json.loads(json.dumps(payload))
    stale_refs["deployments"]["fpga"]["source_refs"] = [
        {
            "path": "vendor_catalog_large",
            "status": "attached",
        }
    ]
    stale_refs["deployments"]["asic"]["source_refs"] = [
        {
            "path": "missing_asic_probe.json",
            "exists": False,
            "status": "missing_required",
            "sha256": "stale-hash",
            "hash_algorithm": "sha256",
        }
    ]

    validation = validate_dft_hardware_deployment_target_selection(stale_refs)

    assert validation["valid"] is False
    assert "fpga_selected_target_stale_source_refs" in validation["errors"]
    assert "asic_selected_target_stale_source_refs" in validation["errors"]


def test_build_target_selection_cli_writes_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_ready_inputs(run_dir)

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_hardware_deployment_target_selection.py",
            "--run-dir",
            str(run_dir),
            "--quiet",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert (run_dir / "dft_hardware_deployment_target_selection.json").exists()
    assert (run_dir / "dft_hardware_deployment_target_selection_status.json").exists()
    validation = json.loads((run_dir / "dft_hardware_deployment_target_selection_validation.json").read_text())
    assert validation["valid"] is True
