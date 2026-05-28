#!/usr/bin/env python3
"""DFT hardware PPA ranking tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads.dft_hardware_ppa_ranking import (
    DFT_HARDWARE_PPA_RANKING_SCHEMA,
    build_dft_hardware_ppa_ranking,
    validate_dft_hardware_ppa_ranking,
    write_dft_hardware_ppa_ranking,
)


STAGES = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
    "dc_asic_synth_timing_area",
]
FPGA_STAGES = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "vivado_fpga_synth_or_impl",
]
ASIC_STAGES = [
    "golden_correctness",
    "hls_or_rtl_sim",
    "hls_or_rtl_synth",
    "dc_asic_synth_timing_area",
]


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _safe_slug(value: str) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [ch if ch.isalnum() or ch in "._-" else "_" for ch in text]
    return "".join(chars).strip("_") or "unknown"


def _vivado_utilization_report(
    luts: int = 100,
    dsps: int = 2,
    registers: int = 10,
    device: str = "7a35tcsg324-1",
) -> str:
    return f"""
| Device       : {device}
+-------------------------+------+-------+-----------+-------+
|        Site Type        | Used | Fixed | Available | Util% |
+-------------------------+------+-------+-----------+-------+
| Slice LUTs*             | {luts:4d} |     0 |     20800 |  0.48 |
| Slice Registers         | {registers:4d} |     0 |     41600 |  0.02 |
| Block RAM Tile          |    1 |     0 |        50 |  2.00 |
| DSPs                    | {dsps:4d} |     0 |        90 |  2.22 |
| Bonded IOB              |   12 |     0 |       210 |  5.71 |
+-------------------------+------+-------+-----------+-------+
"""


def _vivado_timing_report(wns: float = 1.23, device: str = "7a35t-csg324") -> str:
    return f"""
| Device       : {device}
------------------------------------------------------------------------------------------------
| Design Timing Summary
| ---------------------
------------------------------------------------------------------------------------------------
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
    -------      -------  ---------------------  -------------------
       {wns:.2f}         0.00                      0                  218

Setup :            0  Failing Endpoints,  Worst Slack        {wns:.2f}ns,  Total Violation        0.000ns
"""


def _seed_run(
    run_dir: Path,
    *,
    candidates: tuple[str, ...] = ("cand-a", "cand-b"),
    kernel_id: str = "fft_ifft_ffft",
    route_completed: bool = True,
) -> None:
    candidate_rows = [
        {
            "candidate_id": candidate_id,
            "candidate_hardware_gate_passed": True,
            "candidate_claim_eligible": True,
        }
        for candidate_id in candidates
    ]
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-ppa-test",
            "candidate_count": len(candidates),
            "major_kernel_count": 1,
            "expected_kernel_ids": [kernel_id],
            "stage_gate_passed_count": len(candidates) * len(STAGES),
            "unit_gate_passed_count": len(candidates),
            "candidate_gate_passed_count": len(candidates),
            "release_gate_result": "hardware_completion_eligible_pending_deliverable_claim",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "candidate_rows": candidate_rows,
        },
    )
    _write_json(
        run_dir / "dft_hardware_closure_release_gate_validation.json",
        {"schema_version": "dse.dft.hardware_closure_release_gate_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_closure_parser_run.json",
        {"schema_version": "dse.dft.hardware_closure_parser_run.v1", "status": "parsed"},
    )
    _write_json(
        run_dir / "candidate_universe_manifest.json",
        {
            "schema_version": "dse.codesign.candidate_universe_manifest.v1",
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "evaluation_record_id": candidate_id,
                    "legacy_candidate_id": candidate_id,
                    "candidate_id_kind": "evaluation_record_id",
                    "candidate_id_authoritative_for_design": False,
                    "design_candidate_id_authoritative_for_design": True,
                    "design_candidate_id": f"design-{candidate_id}",
                    "assignments": {
                        "algorithm_variants": "iterative_diag_fft",
                        "hardware_microarchitecture": "host_fpga_minimal_v0",
                        "mapping_data_layout": "fft_grid_hbm_tiled",
                        "schedule_runtime_policy": "host_orchestrated_sync",
                        "interface_descriptor_protocol": "genericaccel_descriptor_v1",
                        "dft_phase_hotspot_selection": f"hotspot-{candidate_id}",
                        "evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder",
                    },
                    "identity_assignments": {"hardware_microarchitecture": "host_fpga_minimal_v0"},
                    "non_identity_assignments": {
                        "dft_phase_hotspot_selection": f"hotspot-{candidate_id}",
                        "evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder",
                    },
                    "applicability_assignments": {"dft_phase_hotspot_selection": f"hotspot-{candidate_id}"},
                    "evaluation_policy_assignments": {
                        "evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder"
                    },
                    "design_score": 4.2,
                }
                for candidate_id in candidates
            ],
        },
    )
    for candidate_id in candidates:
        raw_root = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
        _write_text(raw_root / "vivado_utilization.rpt", _vivado_utilization_report())
        _write_text(raw_root / "vivado_timing_summary.rpt", _vivado_timing_report())
        _write_json(raw_root / "vivado_route_status.json", {"implementation_route_completed": route_completed})
        for stage_id in STAGES:
            metrics = {}
            raw_refs = []
            if stage_id == "vivado_fpga_synth_or_impl":
                metrics = {
                    "implementation_route_completed": route_completed,
                    "implementation_route_completed_source": "vivado_route_status_json",
                }
                raw_refs = [
                    {"path": str((raw_root / "vivado_utilization.rpt").relative_to(run_dir))},
                    {"path": str((raw_root / "vivado_timing_summary.rpt").relative_to(run_dir))},
                    {"path": str((raw_root / "vivado_route_status.json").relative_to(run_dir))},
                ]
            elif stage_id == "dc_asic_synth_timing_area":
                metrics = {
                    "dc_target_library_discovery": "real_target_library_present",
                    "dc_target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
                    "slack_ns": 0.5,
                    "area": 1234.0,
                }
            _write_json(
                run_dir
                / "parsed_hard_gate_results"
                / candidate_id
                / kernel_id
                / f"{stage_id}_parsed_result.json",
                {
                    "schema_version": "dse.dft.hardware_parsed_stage_result.v1",
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "stage_id": stage_id,
                    "verdict": "passed",
                    "parser_id": f"{stage_id}_parser",
                    "blocker_ids": [],
                    "raw_evidence_refs": raw_refs,
                    "metrics": metrics,
                },
            )
        _write_source_bundle(run_dir, candidate_id, kernel_id, rtl_sha=f"rtl-{candidate_id}")


def _seed_target_scoped_run(
    run_dir: Path,
    *,
    candidate_id: str,
    target: str,
    stage_ids: list[str],
    kernel_id: str = "fft_ifft_ffft",
    missing_stage_ids: set[str] | None = None,
) -> None:
    missing_stage_ids = missing_stage_ids or set()
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-target-scoped-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "expected_kernel_ids": [kernel_id],
            "stage_gate_passed_count": len(stage_ids) - len(missing_stage_ids),
            "unit_gate_passed_count": 1,
            "candidate_gate_passed_count": 1,
            "release_gate_result": "hardware_completion_eligible_pending_deliverable_claim",
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "candidate_rows": [
                {
                    "candidate_id": candidate_id,
                    "candidate_hardware_gate_passed": True,
                    "candidate_claim_eligible": True,
                    "kernel_rows": [
                        {
                            "candidate_id": candidate_id,
                            "kernel_id": kernel_id,
                            "unit_gate_passed": True,
                            "required_stage_ids": stage_ids,
                            "non_passing_stage_reasons": [],
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        run_dir / "dft_hardware_closure_release_gate_validation.json",
        {"schema_version": "dse.dft.hardware_closure_release_gate_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_closure_parser_run.json",
        {"schema_version": "dse.dft.hardware_closure_parser_run.v1", "status": "parsed"},
    )
    _write_json(
        run_dir / "dft_hardware_closure_gate_adjudication.json",
        {
            "schema_version": "dse.dft.hardware_closure_gate_adjudication.v1",
            "status": "failed_hard_gate" if missing_stage_ids else "passed_hard_gate",
            "unit_rows": [
                {
                    "candidate_id": candidate_id,
                    "kernel_id": kernel_id,
                    "stage_rows": [
                        {
                            "candidate_id": candidate_id,
                            "kernel_id": kernel_id,
                            "stage_id": stage_id,
                            "stage_gate_passed": stage_id not in missing_stage_ids,
                        }
                        for stage_id in stage_ids
                    ],
                }
            ],
        },
    )
    _write_json(
        run_dir / "candidate_universe_manifest.json",
        {
            "schema_version": "dse.codesign.candidate_universe_manifest.v1",
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "design_candidate_id": f"design-{_safe_slug(candidate_id)}",
                    "evaluation_record_id": candidate_id,
                    "assignments": {"hardware_target": target},
                    "identity_assignments": {"hardware_target": target},
                    "applicability_assignments": {"hardware_target": target},
                    "evaluation_policy_assignments": {"gate_policy": f"{target}_target_scoped"},
                }
            ],
        },
    )
    raw_root = run_dir / "candidate_specific_evidence" / _safe_slug(candidate_id) / kernel_id
    _write_text(raw_root / "vivado_utilization.rpt", _vivado_utilization_report(luts=80, dsps=1))
    _write_text(raw_root / "vivado_timing_summary.rpt", _vivado_timing_report())
    _write_json(raw_root / "vivado_route_status.json", {"implementation_route_completed": True})
    for stage_id in stage_ids:
        if stage_id in missing_stage_ids:
            continue
        metrics = {}
        raw_refs = []
        if stage_id == "vivado_fpga_synth_or_impl":
            metrics = {
                "implementation_route_completed": True,
                "implementation_route_completed_source": "vivado_route_status_json",
            }
            raw_refs = [
                {"path": str((raw_root / "vivado_utilization.rpt").relative_to(run_dir))},
                {"path": str((raw_root / "vivado_timing_summary.rpt").relative_to(run_dir))},
                {"path": str((raw_root / "vivado_route_status.json").relative_to(run_dir))},
            ]
        elif stage_id == "dc_asic_synth_timing_area":
            metrics = {
                "dc_target_library_discovery": "real_target_library_present",
                "dc_target_libraries": ["fsa0a_c_generic_core_tt1p8v25c"],
                "slack_ns": 0.4,
                "area": 900.0,
            }
        _write_json(
            run_dir
            / "parsed_hard_gate_results"
            / _safe_slug(candidate_id)
            / _safe_slug(kernel_id)
            / f"{_safe_slug(stage_id)}_parsed_result.json",
            {
                "schema_version": "dse.dft.hardware_parsed_stage_result.v1",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "stage_id": stage_id,
                "verdict": "passed",
                "parser_id": f"{stage_id}_parser",
                "blocker_ids": [],
                "raw_evidence_refs": raw_refs,
                "metrics": metrics,
            },
        )


def _write_source_bundle(run_dir: Path, candidate_id: str, kernel_id: str, rtl_sha: str = "same-rtl") -> None:
    source_path = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / f"{kernel_id}.v"
    _write_text(source_path, f"// {rtl_sha}\nmodule {kernel_id.replace('-', '_')}(); endmodule\n")
    _write_json(
        source_path.parent / "command_manifest.json",
        {
            "schema_version": "dse.dft.hardware_closure.command_manifest.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "commands_executed": True,
            "executed_commands": [{"tool": "unit-test", "command": "run fresh candidate-specific ppa"}],
        },
    )
    _write_json(
        source_path.parent / "tool_versions.json",
        {
            "schema_version": "dse.dft.hardware_closure.tool_versions.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "tool_versions_recorded": True,
            "tool_rows": [{"tool": "vivado", "available": True}, {"tool": "dc_shell", "available": True}],
        },
    )
    _write_json(
        run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / "source_bundle_manifest.json",
        {
            "schema_version": "dse.dft.hardware_closure.source_bundle_manifest.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "candidate_specific_closure": True,
            "shared_microkernel_smoke_only": False,
            "raw_evidence_scope": "candidate_specific_closure",
            "fresh_execution_work_dir": str(source_path.parent / "fresh_tool_work"),
            "fresh_command_run_id": f"fresh-{candidate_id}-{kernel_id}",
            "candidate_parameter_manifest": "candidate_parameter_manifest.json",
            "candidate_parametric_source_hash": f"param-{rtl_sha}",
            "rtl_parameter_values": {"rtl_kernel_variant": rtl_sha},
            "source_refs": [
                {
                    "path": str(source_path.relative_to(run_dir)),
                    "exists": True,
                    "sha256": rtl_sha,
                    "hash_algorithm": "sha256",
                },
                {
                    "path": str((source_path.parent / "command_manifest.json").relative_to(run_dir)),
                    "exists": True,
                    "sha256": "command",
                    "hash_algorithm": "sha256",
                },
                {
                    "path": str((source_path.parent / "tool_versions.json").relative_to(run_dir)),
                    "exists": True,
                    "sha256": "tool",
                    "hash_algorithm": "sha256",
                },
            ],
        },
    )


def test_hardware_ppa_ranking_marks_tied_candidates_without_deliverable_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir)

    status = write_dft_hardware_ppa_ranking(
        run_dir,
        candidate_universe_manifest=run_dir / "candidate_universe_manifest.json",
    )
    ranking = json.loads((run_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    validation = json.loads((run_dir / "dft_hardware_ppa_ranking_validation.json").read_text(encoding="utf-8"))
    pareto = json.loads((run_dir / "dft_hardware_ppa_pareto_frontier.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert ranking["schema_version"] == DFT_HARDWARE_PPA_RANKING_SCHEMA
    assert ranking["hardware_completion_eligible"] is True
    assert ranking["deliverable_complete"] is False
    assert ranking["winner_selection_status"] == "tied_by_identical_kernel_ppa_no_single_winner"
    assert ranking["all_candidates_physical_metric_tied"] is True
    assert ranking["candidate_parametric_sidecar_available"] is True
    assert ranking["candidate_parametric_attribution_used"] is False
    assert ranking["all_candidates_metric_tied"] is True
    assert {row["kernel_rows"][0]["fpga"]["wns_ns"] for row in ranking["candidate_rows"]} == {1.23}
    assert {row["rank"] for row in ranking["fpga_ranking"]} == {1}
    assert {row["rank"] for row in ranking["asic_ranking"]} == {1}
    assert ranking["ranking_policy"]["non_identity_axes_excluded_from_score"] is True
    assert ranking["ranking_policy"]["candidate_metadata_sidecar_only"] is True
    assert ranking["candidate_rows"][0]["candidate_metadata"]["assignments"]
    assert ranking["candidate_rows"][0]["applicability_assignments"]
    assert ranking["candidate_rows"][0]["evaluation_policy_assignments"]
    assert validation["valid"] is True
    assert pareto["pareto_candidate_count"] == 2


def test_hardware_ppa_ranking_uses_fpga_registers_and_wns_for_physical_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, candidates=("cand-a", "cand-b", "cand-c"))
    overrides = {
        "cand-a": {"registers": 10, "wns": 1.00},
        "cand-b": {"registers": 10, "wns": 0.75},
        "cand-c": {"registers": 12, "wns": 2.00},
    }
    for candidate_id, metrics in overrides.items():
        raw_root = run_dir / "candidate_specific_evidence" / candidate_id / "fft_ifft_ffft"
        _write_text(raw_root / "vivado_utilization.rpt", _vivado_utilization_report(registers=metrics["registers"]))
        _write_text(raw_root / "vivado_timing_summary.rpt", _vivado_timing_report(wns=metrics["wns"]))

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    ranks = {row["candidate_id"]: row["rank"] for row in ranking["fpga_ranking"]}
    rows = {row["candidate_id"]: row for row in ranking["fpga_ranking"]}
    assert ranks == {"cand-a": 1, "cand-b": 2, "cand-c": 3}
    assert rows["cand-a"]["fpga_min_wns_ns"] == 1.0
    assert rows["cand-b"]["fpga_min_wns_ns"] == 0.75
    assert rows["cand-c"]["fpga_total_slice_registers"] == 12
    assert ranking["ranking_policy"]["fpga_sort_order"] == [
        "min fpga_total_slice_luts",
        "min fpga_total_slice_registers",
        "min fpga_total_dsps",
        "min fpga_total_block_ram_tiles",
        "min fpga_total_bonded_iob",
        "max fpga_min_wns_ns",
        "shared rank for equal physical metrics; listing order is not winner evidence",
    ]
    assert ranking["pareto_frontier"]["objective_sense"]["fpga_total_slice_registers"] == "minimize"
    assert ranking["pareto_frontier"]["objective_sense"]["fpga_min_wns_ns"] == "maximize"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_auto_discovers_candidate_universe(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir)

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["source_artifacts"]["candidate_universe_manifest"]["exists"] is True
    assert ranking["candidate_rows"][0]["design_candidate_id"].startswith("design-")
    assert ranking["candidate_rows"][0]["candidate_metadata"]["assignments"]
    assert ranking["winner_selection_status"] == "tied_by_identical_kernel_ppa_no_single_winner"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_can_bind_external_evidence_and_parsed_roots(tmp_path: Path) -> None:
    step5_dir = tmp_path / "step5"
    evidence_root = tmp_path / "candidate_ppa_run"
    _seed_run(evidence_root)
    for artifact_name in (
        "dft_hardware_closure_release_gate.json",
        "dft_hardware_closure_release_gate_validation.json",
        "dft_hardware_closure_parser_run.json",
    ):
        _write_json(
            step5_dir / artifact_name,
            json.loads((evidence_root / artifact_name).read_text(encoding="utf-8")),
        )

    status = write_dft_hardware_ppa_ranking(
        step5_dir,
        candidate_universe_manifest=evidence_root / "candidate_universe_manifest.json",
        evidence_root=evidence_root,
        parsed_root=evidence_root,
    )
    ranking = json.loads((step5_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    validation = json.loads((step5_dir / "dft_hardware_ppa_ranking_validation.json").read_text(encoding="utf-8"))

    assert not (step5_dir / "candidate_specific_evidence").exists()
    assert not (step5_dir / "parsed_hard_gate_results").exists()
    assert status["status"] == "passed"
    assert ranking["source_artifacts"]["candidate_specific_evidence_root"]["path"] == str(evidence_root)
    assert ranking["source_artifacts"]["parsed_hard_gate_results_root"]["path"] == str(evidence_root)
    assert ranking["ranking_eligible_candidate_count"] == 2
    assert {row["kernel_rows"][0]["fpga"]["wns_ns"] for row in ranking["candidate_rows"]} == {1.23}
    assert {row["rank"] for row in ranking["fpga_ranking"]} == {1}
    assert {row["rank"] for row in ranking["asic_ranking"]} == {1}
    assert validation["valid"] is True


def test_hardware_ppa_ranking_uses_step2_deployment_metadata_when_universe_absent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-asic-scf-kernel-array-v0::map_7ae35297ebdfc771"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:asic:unit:dc",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "mapping_candidate_id": "map_7ae35297ebdfc771",
                    "target": "asic",
                    "stage_id": "dc_asic_synth_timing_area",
                    "canonical_stage_ids": ASIC_STAGES,
                    "target_execution_profile": {
                        "profile_id": "asic_dc_real_target_library_profile_v1",
                        "target": "asic",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "fsa0a_tt_model",
                            "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                            "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        },
                    },
                }
            ],
        },
    )
    _write_json(
        run_dir / "step2" / "architecture_candidate_set.json",
        {
            "schema_version": "dse.step2.architecture_candidate_set.v1",
            "candidates": [
                {
                    "candidate_id": "architecture::dft-asic-scf-kernel-array-v0",
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "architecture_family": "diag-heavy",
                    "parameter_hash": "sha256:arch",
                    "parameters": {
                        "architecture_id": "dft-asic-scf-kernel-array-v0",
                        "backend": "systemc",
                    },
                }
            ],
        },
    )
    _write_text(
        run_dir / "step2" / "mapping_candidates.jsonl",
        json.dumps(
            {
                "candidate_id": "map_7ae35297ebdfc771",
                "mapping_candidate_id": "map_7ae35297ebdfc771",
                "architecture_id": "dft-asic-scf-kernel-array-v0",
                "parameter_hash": "sha256:mapping",
                "parameters": {"backend": "systemc", "mapping_policy": "architecture_screening_v1"},
            }
        )
        + "\n",
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["source_artifacts"]["candidate_universe_manifest"]["exists"] is False
    assert ranking["candidate_metadata_context_available"] is True
    assert not any(blocker["blocker_id"] == "missing_candidate_universe_metadata" for blocker in ranking["blockers"])
    assert ranking["ranking_eligible_candidate_count"] == 1
    row = ranking["candidate_rows"][0]
    assert row["ranking_eligible"] is True
    assert row["candidate_metadata_source"] == "step2_deployment_hard_gate_metadata_fallback"
    assert row["assignments"]["architecture_id"] == "dft-asic-scf-kernel-array-v0"
    assert row["assignments"]["mapping_candidate_id"] == "map_7ae35297ebdfc771"
    assert row["assignments"]["hardware_target"] == "asic"
    assert row["candidate_metadata"]["provenance"]["metadata_not_candidate_universe"] is True
    assert validation["valid"] is True


def test_hardware_ppa_ranking_uses_external_deployment_metadata_fallback(tmp_path: Path) -> None:
    step5_dir = tmp_path / "step5"
    evidence_root = tmp_path / "candidate_ppa_run"
    candidate_id = "dft-asic-scf-kernel-array-v0::map_7ae35297ebdfc771"
    _seed_target_scoped_run(
        evidence_root,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    (evidence_root / "candidate_universe_manifest.json").unlink()
    _write_json(
        evidence_root / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:asic:unit:dc",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "mapping_candidate_id": "map_7ae35297ebdfc771",
                    "target": "asic",
                    "stage_id": "dc_asic_synth_timing_area",
                    "canonical_stage_ids": ASIC_STAGES,
                    "target_execution_profile": {
                        "profile_id": "asic_dc_real_target_library_profile_v1",
                        "target": "asic",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "fsa0a_tt_model",
                            "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                            "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        },
                    },
                }
            ],
        },
    )
    _write_json(
        evidence_root / "step2" / "architecture_candidate_set.json",
        {
            "schema_version": "dse.step2.architecture_candidate_set.v1",
            "candidates": [
                {
                    "candidate_id": "architecture::dft-asic-scf-kernel-array-v0",
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "architecture_family": "diag-heavy",
                    "parameter_hash": "sha256:arch",
                    "parameters": {
                        "architecture_id": "dft-asic-scf-kernel-array-v0",
                        "backend": "systemc",
                    },
                }
            ],
        },
    )
    _write_text(
        evidence_root / "step2" / "mapping_candidates.jsonl",
        json.dumps(
            {
                "candidate_id": "map_7ae35297ebdfc771",
                "mapping_candidate_id": "map_7ae35297ebdfc771",
                "architecture_id": "dft-asic-scf-kernel-array-v0",
                "parameter_hash": "sha256:mapping",
                "parameters": {"backend": "systemc", "mapping_policy": "architecture_screening_v1"},
            }
        )
        + "\n",
    )
    for artifact_name in (
        "dft_hardware_closure_release_gate.json",
        "dft_hardware_closure_release_gate_validation.json",
        "dft_hardware_closure_parser_run.json",
        "dft_hardware_closure_gate_adjudication.json",
    ):
        _write_json(
            step5_dir / artifact_name,
            json.loads((evidence_root / artifact_name).read_text(encoding="utf-8")),
        )

    status = write_dft_hardware_ppa_ranking(
        step5_dir,
        evidence_root=evidence_root,
        parsed_root=evidence_root,
    )
    ranking = json.loads((step5_dir / "dft_hardware_ppa_ranking.json").read_text(encoding="utf-8"))
    validation = json.loads((step5_dir / "dft_hardware_ppa_ranking_validation.json").read_text(encoding="utf-8"))

    assert not (step5_dir / "dft_deployment_hard_gate_execution_queue.json").exists()
    assert status["status"] == "passed"
    assert ranking["source_artifacts"]["candidate_universe_manifest"]["exists"] is False
    assert ranking["source_artifacts"]["external_deployment_hard_gate_execution_queue"]["exists"] is True
    assert ranking["candidate_metadata_context_available"] is True
    assert not any(blocker["blocker_id"] == "missing_candidate_universe_metadata" for blocker in ranking["blockers"])
    assert ranking["ranking_eligible_candidate_count"] == 1
    row = ranking["candidate_rows"][0]
    assert row["ranking_eligible"] is True
    assert row["candidate_metadata_source"] == "step2_deployment_hard_gate_metadata_fallback"
    assert row["assignments"]["hardware_target"] == "asic"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_asic_scope_does_not_require_vivado(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-asic::map_1"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["ranking_eligible_candidate_count"] == 1
    assert ranking["fpga_ranking"] == []
    assert len(ranking["asic_ranking"]) == 1
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["target"] == "asic"
    assert candidate_row["candidate_gate_passed"] is True
    assert candidate_row["ranking_eligible"] is True
    assert candidate_row["required_stage_ids"] == ASIC_STAGES
    assert candidate_row["vivado_route_completed_kernel_count"] == 0
    assert candidate_row["dc_real_target_library_kernel_count"] == 1
    assert "vivado_fpga_synth_or_impl" not in candidate_row["kernel_rows"][0]["stage_verdicts"]
    assert not any(
        blocker.get("stage_id") == "vivado_fpga_synth_or_impl"
        for blocker in candidate_row["blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_blocks_asic_profile_without_bound_model(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-asic-scf-kernel-array-v0::map_7ae35297ebdfc771"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:asic:unit:dc",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "mapping_candidate_id": "map_7ae35297ebdfc771",
                    "target": "asic",
                    "stage_id": "dc_asic_synth_timing_area",
                    "canonical_stage_ids": ASIC_STAGES,
                    "target_execution_profile": {
                        "profile_id": "asic_dc_real_target_library_profile_v1",
                        "target": "asic",
                        "model_binding_required": True,
                        "selected_model": None,
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["ranking_eligible_candidate_count"] == 0
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["candidate_gate_passed"] is True
    assert candidate_row["ranking_eligible"] is False
    assert candidate_row["asic_target_model_binding"]["required"] is True
    assert candidate_row["asic_target_model_binding"]["status"] == "missing_selected_model"
    assert candidate_row["asic_target_model_binding"]["observed_dc_target_libraries"] == [
        "fsa0a_c_generic_core_tt1p8v25c"
    ]
    assert any(
        blocker["blocker_id"] == "asic_target_model_binding_missing"
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_blocks_asic_profile_id_without_profile_body(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-asic::map_profile_id_only"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    manifest_path = run_dir / "candidate_universe_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["candidates"][0]["non_identity_assignments"] = {
        "target_execution_profile_ids": ["asic_dc_real_target_library_profile_v1"]
    }
    _write_json(manifest_path, manifest)

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["ranking_eligible_candidate_count"] == 0
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["candidate_gate_passed"] is True
    assert candidate_row["ranking_eligible"] is False
    assert candidate_row["asic_target_model_binding"]["required"] is True
    assert candidate_row["asic_target_model_binding"]["status"] == "missing_selected_model"
    assert any(
        blocker["blocker_id"] == "asic_target_model_binding_missing"
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_accepts_bound_asic_model_matching_dc_library(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-asic-scf-kernel-array-v0::map_7ae35297ebdfc771"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:asic:unit:dc",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "mapping_candidate_id": "map_7ae35297ebdfc771",
                    "target": "asic",
                    "stage_id": "dc_asic_synth_timing_area",
                    "canonical_stage_ids": ASIC_STAGES,
                    "target_execution_profile": {
                        "profile_id": "asic_dc_real_target_library_profile_v1",
                        "target": "asic",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "fsa0a_tt_model",
                            "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                            "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        },
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["ranking_eligible"] is True
    assert ranking["ranking_eligible_candidate_count"] == 1
    assert candidate_row["asic_target_model_binding"]["status"] == "bound_model_matches_evidence"
    assert candidate_row["asic_dc_target_libraries"] == ["fsa0a_c_generic_core_tt1p8v25c"]
    assert not any(
        blocker["blocker_id"].startswith("asic_")
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_accepts_asic_model_inferred_by_binding_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-asic-scf-kernel-array-v0::map_7ae35297ebdfc771"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:asic:unit:dc",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-asic-scf-kernel-array-v0",
                    "mapping_candidate_id": "map_7ae35297ebdfc771",
                    "target": "asic",
                    "stage_id": "dc_asic_synth_timing_area",
                    "canonical_stage_ids": ASIC_STAGES,
                    "target_execution_profile": {
                        "profile_id": "asic_dc_real_target_library_profile_v1",
                        "target": "asic",
                        "model_binding_required": True,
                        "selected_model": None,
                    },
                }
            ],
        },
    )
    _write_json(
        run_dir / "dft_deployment_target_model_binding.json",
        {
            "schema_version": "dse.dft.deployment_target_model_binding.v1",
            "status": "target_model_binding_ready",
            "blocker_ids": [],
            "target_binding_row_count": 1,
            "target_binding_rows": [
                {
                    "target": "asic",
                    "profile_id": "asic_dc_real_target_library_profile_v1",
                    "binding_status": "bound_model_inferred_from_dc_probe",
                    "candidate_ids": [candidate_id],
                    "selected_model_source": "dc_target_library_probe",
                    "selected_model": {
                        "model_id": "dc_target_library:fsa0a_c_generic_core_tt1p8v25c",
                        "library_name": "fsa0a_c_generic_core_tt1p8v25c",
                        "dc_target_library": "fsa0a_c_generic_core_tt1p8v25c",
                        "library_db_path": "/eda/lib/fsa0a_c_generic_core_tt1p8v25c.db",
                    },
                }
            ],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["ranking_eligible"] is True
    assert candidate_row["asic_target_model_binding"]["status"] == "bound_model_matches_evidence"
    profile = candidate_row["candidate_metadata"]["target_execution_profiles"][
        "asic_dc_real_target_library_profile_v1"
    ]
    assert profile["selected_model_source"] == "dc_target_library_probe"
    assert profile["model_binding_artifact"] == "dft_deployment_target_model_binding.json"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_fpga_scope_does_not_require_dc(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-fpga::map_1"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="fpga",
        stage_ids=FPGA_STAGES,
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["ranking_eligible_candidate_count"] == 1
    assert len(ranking["fpga_ranking"]) == 1
    assert ranking["asic_ranking"] == []
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["target"] == "fpga"
    assert candidate_row["candidate_gate_passed"] is True
    assert candidate_row["ranking_eligible"] is True
    assert candidate_row["required_stage_ids"] == FPGA_STAGES
    assert candidate_row["vivado_route_completed_kernel_count"] == 1
    assert candidate_row["dc_real_target_library_kernel_count"] == 0
    assert "dc_asic_synth_timing_area" not in candidate_row["kernel_rows"][0]["stage_verdicts"]
    assert not any(
        blocker.get("stage_id") == "dc_asic_synth_timing_area"
        for blocker in candidate_row["blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_blocks_hbm_fpga_profile_without_bound_model(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-fpga-hbm-streaming-v0::map_092f94724710d5d4"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="fpga",
        stage_ids=FPGA_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:fpga:unit:vivado",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "mapping_candidate_id": "map_092f94724710d5d4",
                    "target": "fpga",
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "canonical_stage_ids": FPGA_STAGES,
                    "target_execution_profile": {
                        "profile_id": "fpga_hbm_unbounded_budget_vivado_route_profile_v1",
                        "target": "fpga",
                        "model_binding_required": True,
                        "selected_model": None,
                        "recommended_model_selection": {
                            "recommended_model_id": "amd_alveo_u280_a_u280",
                            "selection_status": "recommended_for_no_budget_planning_but_local_vivado_binding_required",
                        },
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["ranking_eligible_candidate_count"] == 0
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["candidate_gate_passed"] is True
    assert candidate_row["ranking_eligible"] is False
    assert candidate_row["fpga_target_model_binding"]["required"] is True
    assert candidate_row["fpga_target_model_binding"]["status"] == "missing_selected_model"
    assert sorted(candidate_row["fpga_vivado_devices"]) == ["7a35t-csg324", "7a35tcsg324-1"]
    assert any(
        blocker["blocker_id"] == "fpga_target_model_binding_missing"
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_accepts_bound_fpga_model_matching_vivado_part(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-fpga-hbm-streaming-v0::map_092f94724710d5d4"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="fpga",
        stage_ids=FPGA_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:fpga:unit:vivado",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "mapping_candidate_id": "map_092f94724710d5d4",
                    "target": "fpga",
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "canonical_stage_ids": FPGA_STAGES,
                    "target_execution_profile": {
                        "profile_id": "fpga_hbm_unbounded_budget_vivado_route_profile_v1",
                        "target": "fpga",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "bound-artix-smoke-model",
                            "vivado_part": "7a35t-csg324",
                        },
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["ranking_eligible"] is True
    assert ranking["ranking_eligible_candidate_count"] == 1
    assert candidate_row["fpga_target_model_binding"]["status"] == "bound_model_matches_evidence"
    assert not any(
        blocker["blocker_id"].startswith("fpga_")
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_accepts_selected_xc_part_when_vivado_reports_device_without_x_prefix(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-fpga-hbm-streaming-v0::map_092f94724710d5d4"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="fpga",
        stage_ids=FPGA_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:fpga:unit:vivado",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "mapping_candidate_id": "map_092f94724710d5d4",
                    "target": "fpga",
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "canonical_stage_ids": FPGA_STAGES,
                    "target_execution_profile": {
                        "profile_id": "fpga_hbm_unbounded_budget_vivado_route_profile_v1",
                        "target": "fpga",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "artix7_xc7a35t_smoke",
                            "vivado_part": "xc7a35tcsg324-1",
                            "claim_level": "smoke_progress_only_not_hbm_alveo_deployment",
                        },
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["ranking_eligible"] is True
    assert candidate_row["fpga_target_model_binding"]["status"] == "bound_model_matches_evidence"
    assert candidate_row["fpga_target_model_binding"]["expected_vivado_parts"] == [
        "xc7a35tcsg324-1"
    ]
    assert "7a35tcsg324-1" in candidate_row["fpga_target_model_binding"]["observed_vivado_devices"]
    assert not any(
        blocker["blocker_id"] == "fpga_vivado_device_mismatch"
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_rejects_device_only_fpga_model_binding(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "dft-fpga-hbm-streaming-v0::map_092f94724710d5d4"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="fpga",
        stage_ids=FPGA_STAGES,
    )
    (run_dir / "candidate_universe_manifest.json").unlink()
    _write_json(
        run_dir / "dft_deployment_hard_gate_execution_queue.json",
        {
            "schema_version": "dse.dft.deployment_hard_gate_execution_queue.v1",
            "work_items": [
                {
                    "work_item_id": "deployment_ppa:fpga:unit:vivado",
                    "candidate_id": candidate_id,
                    "architecture_id": "dft-fpga-hbm-streaming-v0",
                    "mapping_candidate_id": "map_092f94724710d5d4",
                    "target": "fpga",
                    "stage_id": "vivado_fpga_synth_or_impl",
                    "canonical_stage_ids": FPGA_STAGES,
                    "target_execution_profile": {
                        "profile_id": "fpga_hbm_unbounded_budget_vivado_route_profile_v1",
                        "target": "fpga",
                        "model_binding_required": True,
                        "selected_model": {
                            "model_id": "legacy-device-only",
                            "device": "7a35t-csg324",
                        },
                    },
                }
            ],
        },
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["ranking_eligible_candidate_count"] == 0
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["ranking_eligible"] is False
    assert candidate_row["fpga_target_model_binding"]["status"] == "selected_model_missing_vivado_part"
    assert any(
        blocker["blocker_id"] == "fpga_selected_model_missing_vivado_part"
        for blocker in candidate_row["ranking_blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_target_scope_still_fails_closed_when_required_stage_missing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-asic::map_missing"
    _seed_target_scoped_run(
        run_dir,
        candidate_id=candidate_id,
        target="asic",
        stage_ids=ASIC_STAGES,
        missing_stage_ids={"dc_asic_synth_timing_area"},
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["ranking_eligible_candidate_count"] == 0
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["candidate_gate_passed"] is False
    assert candidate_row["ranking_eligible"] is False
    assert candidate_row["required_stage_ids"] == ASIC_STAGES
    blockers = {(blocker.get("stage_id"), blocker.get("blocker_id")) for blocker in candidate_row["blockers"]}
    assert ("dc_asic_synth_timing_area", "missing_parsed_stage_result") in blockers
    assert ("vivado_fpga_synth_or_impl", "missing_parsed_stage_result") not in blockers
    assert validation["valid"] is True


def test_hardware_ppa_ranking_fails_closed_without_candidate_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir)
    (run_dir / "candidate_universe_manifest.json").unlink()

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["ranking_eligible_candidate_count"] == 0
    assert any(blocker["blocker_id"] == "missing_candidate_universe_metadata" for blocker in ranking["blockers"])
    assert all(
        any(blocker["blocker_id"] == "missing_candidate_universe_metadata" for blocker in row["blockers"])
        for row in ranking["candidate_rows"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_keeps_static_rtl_ties_visible_but_blocks_winner_policy(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    kernel_id = "fft_ifft_ffft"
    _seed_run(run_dir, kernel_id=kernel_id)
    for candidate_id in ("cand-a", "cand-b"):
        _write_source_bundle(run_dir, candidate_id, kernel_id, rtl_sha="identical-rtl")

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "trusted_hardware_ppa_ranking_tied"
    assert ranking["winner_selection_status"] == "tied_by_identical_kernel_ppa_no_single_winner"
    assert ranking["ranking_eligible_candidate_count"] == 2
    assert {row["rank"] for row in ranking["fpga_ranking"]} == {1}
    assert ranking["winner_policy_blocker_count"] == 2
    assert all(
        any(
            blocker["blocker_id"] == "candidate_parametric_source_not_distinguished"
            and blocker["scope"] == "winner_selection_only"
            and blocker["ranking_eligible_unchanged"] is True
            for blocker in row["winner_policy_blockers"]
        )
        for row in ranking["candidate_rows"]
    )
    assert not any(
        any(blocker["blocker_id"] == "candidate_parametric_source_not_distinguished" for blocker in row["blockers"])
        for row in ranking["candidate_rows"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_blocks_fpga_claim_without_vivado_route(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, candidates=("cand-a",), route_completed=False)

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["fpga_ranking"] == []
    assert ranking["asic_ranking"]
    assert ranking["candidate_rows"][0]["target_eligibility"]["fpga"]["ranking_eligible"] is False
    assert ranking["candidate_rows"][0]["target_eligibility"]["asic"]["ranking_eligible"] is True
    assert any(
        blocker["blocker_id"] == "vivado_route_not_completed"
        for row in ranking["candidate_rows"]
        for blocker in row["target_eligibility"]["fpga"]["blockers"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_missing_parsed_stage_results_fails_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-missing-parsed-stage-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "expected_kernel_ids": [kernel_id],
            "stage_gate_passed_count": len(STAGES),
            "unit_gate_passed_count": 1,
            "candidate_gate_passed_count": 1,
            "hardware_completion_eligible": True,
            "deliverable_complete": False,
            "candidate_rows": [
                {
                    "candidate_id": candidate_id,
                    "candidate_hardware_gate_passed": True,
                    "candidate_claim_eligible": True,
                }
            ],
        },
    )
    _write_json(
        run_dir / "dft_hardware_closure_release_gate_validation.json",
        {"schema_version": "dse.dft.hardware_closure_release_gate_validation.v1", "valid": True, "errors": []},
    )
    _write_json(
        run_dir / "dft_hardware_closure_parser_run.json",
        {"schema_version": "dse.dft.hardware_closure_parser_run.v1", "status": "parsed"},
    )

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["winner_selection_status"] == "blocked_no_hardware_ppa_winner"
    assert ranking["ranking_eligible_candidate_count"] == 0
    assert ranking["blocked_candidate_count"] == 1
    assert ranking["fpga_ranking"] == []
    assert ranking["asic_ranking"] == []
    candidate_row = ranking["candidate_rows"][0]
    assert candidate_row["candidate_gate_passed"] is False
    assert candidate_row["ranking_eligible"] is False
    assert "missing_parsed_stage_result" in {blocker["blocker_id"] for blocker in candidate_row["blockers"]}
    assert ranking["hardware_completion_eligible"] is True
    assert ranking["deliverable_complete"] is False
    assert validation["valid"] is True


def test_hardware_ppa_ranking_is_target_scoped_dc_only_does_not_satisfy_fpga(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _seed_run(run_dir, candidates=(candidate_id,), kernel_id=kernel_id)
    (
        run_dir
        / "parsed_hard_gate_results"
        / candidate_id
        / kernel_id
        / "vivado_fpga_synth_or_impl_parsed_result.json"
    ).unlink()

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    row = ranking["candidate_rows"][0]
    assert ranking["fpga_ranking"] == []
    assert [item["candidate_id"] for item in ranking["asic_ranking"]] == [candidate_id]
    assert row["target_eligibility"]["fpga"]["ranking_eligible"] is False
    assert row["target_eligibility"]["asic"]["ranking_eligible"] is True
    assert any(
        blocker["stage_id"] == "vivado_fpga_synth_or_impl"
        and blocker["blocker_id"] == "missing_parsed_stage_result"
        for blocker in row["target_eligibility"]["fpga"]["blockers"]
    )
    assert not any(
        blocker["stage_id"] == "vivado_fpga_synth_or_impl"
        for blocker in row["target_eligibility"]["asic"]["blockers"]
    )
    assert ranking["asic_ranking"][0]["candidate_identity"]["target_platform"]["deployment_target"] == "asic"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_is_target_scoped_vivado_only_does_not_satisfy_asic(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _seed_run(run_dir, candidates=(candidate_id,), kernel_id=kernel_id)
    (
        run_dir
        / "parsed_hard_gate_results"
        / candidate_id
        / kernel_id
        / "dc_asic_synth_timing_area_parsed_result.json"
    ).unlink()

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    row = ranking["candidate_rows"][0]
    assert [item["candidate_id"] for item in ranking["fpga_ranking"]] == [candidate_id]
    assert ranking["asic_ranking"] == []
    assert row["target_eligibility"]["fpga"]["ranking_eligible"] is True
    assert row["target_eligibility"]["asic"]["ranking_eligible"] is False
    assert any(
        blocker["stage_id"] == "dc_asic_synth_timing_area"
        and blocker["blocker_id"] == "missing_parsed_stage_result"
        for blocker in row["target_eligibility"]["asic"]["blockers"]
    )
    assert not any(
        blocker["stage_id"] == "dc_asic_synth_timing_area"
        for blocker in row["target_eligibility"]["fpga"]["blockers"]
    )
    assert ranking["fpga_ranking"][0]["candidate_identity"]["target_platform"]["deployment_target"] == "fpga"
    assert validation["valid"] is True


def test_hardware_ppa_ranking_requires_fresh_identity_bound_source_bundle(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _seed_run(run_dir, candidates=(candidate_id,), kernel_id=kernel_id)
    source_bundle = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / "source_bundle_manifest.json"
    payload = json.loads(source_bundle.read_text(encoding="utf-8"))
    payload["candidate_id"] = "forged-candidate"
    payload["shared_microkernel_smoke_only"] = True
    payload.pop("fresh_execution_work_dir", None)
    _write_json(source_bundle, payload)

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    row = ranking["candidate_rows"][0]
    blocker_ids = {blocker["blocker_id"] for blocker in row["blockers"]}
    assert ranking["fpga_ranking"] == []
    assert ranking["asic_ranking"] == []
    assert "source_bundle_candidate_id_mismatch" in blocker_ids
    assert "source_bundle_shared_microkernel_smoke_only" in blocker_ids
    assert "source_bundle_fresh_execution_work_dir_missing" in blocker_ids
    assert row["candidate_identity"]["deployment_boundary"]
    assert row["candidate_identity"]["host_device_partition"]["accelerated_node_ids"]
    assert row["candidate_identity"]["architecture_template_parameters"]
    assert row["candidate_identity"]["mapping_layout"]
    assert row["candidate_identity"]["runtime_co_scheduling"]
    assert row["candidate_identity"]["descriptor_granularity"]
    assert row["candidate_identity"]["fallback_policy"]
    assert validation["valid"] is True
