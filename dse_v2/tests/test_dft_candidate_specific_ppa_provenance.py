#!/usr/bin/env python3
"""Candidate-specific PPA provenance audit tests."""

from __future__ import annotations

import json
from pathlib import Path

from dse_v2.reference_workloads.dft_candidate_specific_ppa_provenance import (
    DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA,
    build_dft_hardware_tie_breaker_execution_queue,
    build_dft_candidate_specific_ppa_provenance_audit,
    validate_dft_candidate_specific_ppa_provenance_audit,
    validate_dft_hardware_tie_breaker_execution_queue,
    write_dft_candidate_specific_ppa_provenance_audit,
)
from dse_v2.reference_workloads.dft_hardware_ppa_ranking import REQUIRED_STAGE_IDS


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _command_templates() -> list[dict]:
    return [
        {
            "template_id": f"template_{stage_id}",
            "stage_ids": [stage_id],
            "tool": "vivado" if "vivado" in stage_id else "dc_shell" if stage_id.startswith("dc_") else "python3",
            "command": f"run {stage_id} {{candidate_bundle_json}} {{kernel_id}} {{unit_evidence_dir}}",
            "required_outputs": [f"{{unit_dir}}/{stage_id}.out"],
        }
        for stage_id in REQUIRED_STAGE_IDS
    ]


def _seed_run(run_dir: Path, *, fresh: bool) -> None:
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-prov-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "expected_kernel_ids": [kernel_id],
            "hardware_completion_eligible": True,
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
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "fpga_ranking": [{"candidate_id": candidate_id, "rank": 1}],
            "asic_ranking": [{"candidate_id": candidate_id, "rank": 1}],
        },
    )
    unit_dir = run_dir / "candidate_specific_evidence" / candidate_id / kernel_id
    source_flow_dir = run_dir / "source_flows" / candidate_id / kernel_id
    if not fresh:
        _write_json(
            source_flow_dir / "manifest.json",
            {
                "schema_version": "dse.dft_scf.fft_ifft_ffft_rtl_flow.v1",
                "status": "passed_smoke_flow",
                "claim_boundary": "DFT-scoped RTL smoke flow; not full-SCF/all-kernel closure.",
            },
        )
    _write_json(
        unit_dir / "source_bundle_manifest.json",
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "candidate_specific_closure": True,
            "shared_microkernel_smoke_only": False,
            "raw_evidence_scope": "candidate_specific_closure",
            **(
                {
                    "candidate_parameter_manifest": "candidate_parameter_manifest.json",
                    "candidate_parametric_source_hash": "candidate-parametric-hash",
                    "rtl_parameter_values": {"rtl_kernel_variant": 1},
                }
                if fresh
                else {}
            ),
        },
    )
    _write_json(
        unit_dir / "tool_versions.json",
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "tool_versions_recorded": fresh,
            "tool_rows": [{"tool": "vivado", "version": "2019.1"}] if fresh else [],
        },
    )
    _write_json(
        unit_dir / "command_manifest.json",
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "commands_executed": fresh,
            "command_templates": _command_templates(),
            "executed_commands": [{"stage_id": "all", "command": "fresh run"}] if fresh else [],
        },
    )
    _write_json(
        unit_dir / "raw_transcript_index.json",
        {"candidate_id": candidate_id, "kernel_id": kernel_id, "raw_transcript_refs": []},
    )
    _write_json(
        unit_dir / "candidate_input_manifest.json",
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            **(
                {
                    "source_flow_dir": str(source_flow_dir),
                    "input_source": "source_flow_golden_correctness",
                    "claim_boundary": "raw-stage materialization copies or wraps existing source-flow outputs",
                }
                if not fresh
                else {"input_source": "fresh_candidate_specific_tool_execution"}
            ),
        },
    )
    for stage_id in REQUIRED_STAGE_IDS:
        _write_json(
            run_dir / "parsed_hard_gate_results" / candidate_id / kernel_id / f"{stage_id}_parsed_result.json",
            {
                "schema_version": "dse.dft.hardware_parsed_stage_result.v1",
                "candidate_id": candidate_id,
                "kernel_id": kernel_id,
                "stage_id": stage_id,
                "verdict": "passed",
                "raw_evidence_refs": [{"path": f"candidate_specific_evidence/{candidate_id}/{kernel_id}/{stage_id}.out"}],
            },
        )


def test_provenance_audit_blocks_materialized_source_flow_without_fresh_commands(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, fresh=False)

    status = write_dft_candidate_specific_ppa_provenance_audit(run_dir)
    audit = json.loads((run_dir / "dft_candidate_specific_ppa_provenance_audit.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "dft_hardware_tie_breaker_execution_queue.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert audit["schema_version"] == DFT_CANDIDATE_SPECIFIC_PPA_PROVENANCE_AUDIT_SCHEMA
    assert audit["winner_provenance_eligible"] is False
    assert audit["blocked_unit_count"] == 1
    assert audit["blocker_id_counts"]["commands_not_executed"] == len(REQUIRED_STAGE_IDS)
    assert audit["blocker_id_counts"]["tool_versions_not_recorded"] == len(REQUIRED_STAGE_IDS)
    assert audit["blocker_id_counts"]["raw_evidence_materialized_from_source_flow"] == len(REQUIRED_STAGE_IDS)
    assert queue["work_item_count"] == len(REQUIRED_STAGE_IDS)
    assert queue["work_items"][0]["fresh_execution_required"] is True


def test_provenance_audit_missing_candidate_specific_files_fails_closed_and_queues_all_stages(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "cand-a"
    kernel_id = "fft_ifft_ffft"
    _write_json(
        run_dir / "dft_hardware_closure_release_gate.json",
        {
            "schema_version": "dse.dft.hardware_closure_release_gate.v1",
            "release_id": "release-missing-provenance-test",
            "candidate_count": 1,
            "major_kernel_count": 1,
            "expected_kernel_ids": [kernel_id],
            "hardware_completion_eligible": True,
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
        run_dir / "dft_hardware_ppa_ranking.json",
        {
            "schema_version": "dse.dft.hardware_ppa_ranking.v1",
            "status": "trusted_hardware_ppa_ranking_tied",
            "fpga_ranking": [{"candidate_id": candidate_id, "rank": 1}],
            "asic_ranking": [{"candidate_id": candidate_id, "rank": 1}],
            "winner_selection_status": "tied_by_identical_kernel_ppa_no_single_winner",
        },
    )

    audit = build_dft_candidate_specific_ppa_provenance_audit(run_dir)
    audit_validation = validate_dft_candidate_specific_ppa_provenance_audit(audit)
    queue = build_dft_hardware_tie_breaker_execution_queue(run_dir, provenance_audit=audit)
    queue_validation = validate_dft_hardware_tie_breaker_execution_queue(queue)

    assert audit["status"] == "blocked_candidate_specific_ppa_provenance"
    assert audit["winner_provenance_eligible"] is False
    assert audit["unit_count"] == 1
    assert audit["trusted_unit_count"] == 0
    assert audit["blocked_unit_count"] == 1
    assert audit["blocker_id_counts"]["missing_candidate_specific_evidence_dir"] == 1
    assert audit["blocker_id_counts"]["missing_source_bundle_manifest"] == 1
    assert audit["blocker_id_counts"]["missing_tool_versions_manifest"] == 1
    assert audit["hardware_completion_eligible"] is False
    assert audit["deliverable_complete"] is False
    assert queue["status"] == "fresh_candidate_specific_ppa_execution_required"
    assert queue["work_item_count"] == len(REQUIRED_STAGE_IDS)
    assert {item["stage_id"] for item in queue["work_items"]} == set(REQUIRED_STAGE_IDS)
    assert all(item["fresh_execution_required"] is True for item in queue["work_items"])
    assert all(item["no_shared_evidence_allowed"] is True for item in queue["work_items"])
    assert audit_validation["valid"] is True
    assert queue_validation["valid"] is True


def test_provenance_audit_accepts_fresh_candidate_specific_command_tool_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, fresh=True)

    status = write_dft_candidate_specific_ppa_provenance_audit(run_dir)
    audit = build_dft_candidate_specific_ppa_provenance_audit(run_dir)
    validation = validate_dft_candidate_specific_ppa_provenance_audit(audit)
    queue = json.loads((run_dir / "dft_hardware_tie_breaker_execution_queue.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert audit["status"] == "trusted_candidate_specific_ppa_provenance"
    assert audit["winner_provenance_eligible"] is True
    assert audit["trusted_unit_count"] == 1
    assert audit["blocker_count"] == 0
    assert queue["status"] == "no_tie_breaker_work_items"
    assert queue["work_item_count"] == 0
    assert validation["valid"] is True


def test_provenance_audit_requires_candidate_parametric_source_hash_for_winner_proof(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _seed_run(run_dir, fresh=True)
    source_bundle = run_dir / "candidate_specific_evidence" / "cand-a" / "fft_ifft_ffft" / "source_bundle_manifest.json"
    payload = json.loads(source_bundle.read_text(encoding="utf-8"))
    payload.pop("candidate_parameter_manifest", None)
    payload.pop("candidate_parametric_source_hash", None)
    payload.pop("rtl_parameter_values", None)
    _write_json(source_bundle, payload)

    status = write_dft_candidate_specific_ppa_provenance_audit(run_dir)
    audit = json.loads((run_dir / "dft_candidate_specific_ppa_provenance_audit.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "dft_hardware_tie_breaker_execution_queue.json").read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert audit["winner_provenance_eligible"] is False
    assert audit["blocker_id_counts"]["candidate_parametric_source_hash_missing"] == 1
    assert audit["blocker_id_counts"]["candidate_parameter_manifest_missing"] == 1
    assert audit["blocker_id_counts"]["rtl_parameter_values_missing"] == 1
    assert queue["status"] == "fresh_candidate_specific_ppa_execution_required"
    assert queue["work_item_count"] == len(REQUIRED_STAGE_IDS)
