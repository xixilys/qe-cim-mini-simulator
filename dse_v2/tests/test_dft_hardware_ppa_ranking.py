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


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _vivado_utilization_report(luts: int = 100, dsps: int = 2) -> str:
    return f"""
+-------------------------+------+-------+-----------+-------+
|        Site Type        | Used | Fixed | Available | Util% |
+-------------------------+------+-------+-----------+-------+
| Slice LUTs*             | {luts:4d} |     0 |     20800 |  0.48 |
| Slice Registers         |   10 |     0 |     41600 |  0.02 |
| Block RAM Tile          |    1 |     0 |        50 |  2.00 |
| DSPs                    | {dsps:4d} |     0 |        90 |  2.22 |
| Bonded IOB              |   12 |     0 |       210 |  5.71 |
+-------------------------+------+-------+-----------+-------+
"""


def _vivado_timing_report() -> str:
    return """
| Design Timing Summary
| ---------------------
------------------------------------------------------------------------------------------------
    WNS(ns)      TNS(ns)
    -------      -------
       1.23         0.00
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


def _write_source_bundle(run_dir: Path, candidate_id: str, kernel_id: str, rtl_sha: str = "same-rtl") -> None:
    source_path = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / f"{kernel_id}.v"
    _write_text(source_path, f"// {rtl_sha}\nmodule {kernel_id.replace('-', '_')}(); endmodule\n")
    _write_json(
        run_dir / "candidate_specific_evidence" / candidate_id / kernel_id / "source_bundle_manifest.json",
        {
            "schema_version": "dse.dft.hardware_closure.source_bundle_manifest.v1",
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "source_refs": [
                {
                    "path": str(source_path.relative_to(run_dir)),
                    "exists": True,
                    "sha256": rtl_sha,
                    "hash_algorithm": "sha256",
                }
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
    assert {row["rank"] for row in ranking["fpga_ranking"]} == {1}
    assert {row["rank"] for row in ranking["asic_ranking"]} == {1}
    assert ranking["ranking_policy"]["non_identity_axes_excluded_from_score"] is True
    assert ranking["ranking_policy"]["candidate_metadata_sidecar_only"] is True
    assert ranking["candidate_rows"][0]["candidate_metadata"]["assignments"]
    assert ranking["candidate_rows"][0]["applicability_assignments"]
    assert ranking["candidate_rows"][0]["evaluation_policy_assignments"]
    assert validation["valid"] is True
    assert pareto["pareto_candidate_count"] == 2


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


def test_hardware_ppa_ranking_blocks_identical_static_rtl_source_bundles(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    kernel_id = "fft_ifft_ffft"
    _seed_run(run_dir, kernel_id=kernel_id)
    for candidate_id in ("cand-a", "cand-b"):
        _write_source_bundle(run_dir, candidate_id, kernel_id, rtl_sha="identical-rtl")

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["winner_selection_status"] == "blocked_no_hardware_ppa_winner"
    assert ranking["ranking_eligible_candidate_count"] == 0
    assert not ranking["fpga_ranking"]
    assert all(
        any(blocker["blocker_id"] == "candidate_parametric_source_not_distinguished" for blocker in row["blockers"])
        for row in ranking["candidate_rows"]
    )
    assert validation["valid"] is True


def test_hardware_ppa_ranking_blocks_fpga_claim_without_vivado_route(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, candidates=("cand-a",), route_completed=False)

    ranking = build_dft_hardware_ppa_ranking(run_dir)
    validation = validate_dft_hardware_ppa_ranking(ranking)

    assert ranking["status"] == "blocked_hardware_ppa_ranking"
    assert ranking["ranking_eligible_candidate_count"] == 0
    assert any(
        blocker["blocker_id"] == "vivado_route_not_completed"
        for row in ranking["candidate_rows"]
        for blocker in row["blockers"]
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
    assert {blocker["blocker_id"] for blocker in candidate_row["blockers"]} == {"missing_parsed_stage_result"}
    assert ranking["hardware_completion_eligible"] is True
    assert ranking["deliverable_complete"] is False
    assert validation["valid"] is True
