#!/usr/bin/env python3
"""Complete-DSE Step2 binding contracts."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.codesign.complete_dse_search_space import build_release_subset_manifest
from dse_v2.codesign.complete_dse_step2_binding import (
    QUEUE_MODE,
    build_complete_dse_step2_binding_bundle,
    validate_complete_dse_step2_queue,
)
from dse_v2.codesign.release_domain import stable_json_hash


def test_complete_dse_step2_binding_admits_all_generated_release_candidates():
    release_subset = build_release_subset_manifest()
    bundle = build_complete_dse_step2_binding_bundle(release_subset)

    binding = bundle["complete_dse_step2_binding.json"]
    queue = bundle["step3_simulation_queue.json"]
    ledger = bundle["trial_state_ledger.json"]
    effectiveness = bundle["complete_dse_search_effectiveness_report.json"]
    validation = bundle["complete_dse_step2_binding_validation.json"]

    assert binding["candidate_count"] == release_subset["legal_candidate_count"]
    assert queue["queue_mode"] == QUEUE_MODE
    assert queue["entry_count"] == binding["candidate_count"]
    assert queue["candidate_ids"] == release_subset["legal_candidate_ids"]
    assert queue["release_subset_hash"] == release_subset["release_subset_hash"]
    assert ledger["candidate_count"] == binding["candidate_count"]
    assert ledger["queued_entry_count"] == queue["entry_count"]
    assert ledger["trusted_final_claim"] is False
    assert ledger["release_completion_eligible"] is False
    assert effectiveness["status"] == "passed"
    assert effectiveness["queue_preservation"]["status"] == "passed"
    assert effectiveness["can_name_best_fpga_or_asic"] is False
    assert validation["valid"] is True
    assert all(
        row["complete_dse_candidate_id"].startswith("cdse_")
        for row in binding["candidate_bindings"]
    )
    assert all(
        row["candidate_identity_policy"]
        == "complete_dse_seven_layer_design_identity"
        for row in ledger["candidates"]
    )
    assert {
        row["target_platform_id"] for row in binding["candidate_bindings"]
    } == {"fpga_vivado_release_v1", "asic_synopsys_dc_release_v1"}
    assert {
        entry["target_platform_id"] for entry in queue["entries"]
    } == {"fpga_vivado_release_v1", "asic_synopsys_dc_release_v1"}


def test_complete_dse_step2_binding_preserves_release_matrix_provenance_hashes():
    release_subset = build_release_subset_manifest()
    bundle = build_complete_dse_step2_binding_bundle(release_subset)

    binding = bundle["complete_dse_step2_binding.json"]
    queue = bundle["step3_simulation_queue.json"]
    ledger = bundle["trial_state_ledger.json"]
    contract = release_subset["candidate_workflow_deployment_target_matrix_contract"]
    expected = {
        "schema_version": "dse.codesign.complete_dse.release_matrix_provenance.v1",
        "release_id": release_subset["release_id"],
        "matrix_contract_hash": contract["contract_hash"],
        "matrix_rows_hash": release_subset[
            "candidate_workflow_deployment_target_matrix_rows_hash"
        ],
        "matrix_validation_hash": release_subset["generation_provenance"][
            "candidate_workflow_deployment_target_matrix_validation_hash"
        ],
        "target_axis_complete": True,
        "target_kind_axis_complete": True,
        "required_target_platform_ids": [
            "fpga_vivado_release_v1",
            "asic_synopsys_dc_release_v1",
        ],
        "required_target_platform_kinds": ["fpga", "asic"],
        "source_artifact": "release_subset_manifest.json",
    }

    assert (
        binding["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
    )
    assert (
        queue["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
    )
    assert (
        ledger["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
    )
    assert all(
        row["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
        for row in binding["candidate_bindings"]
    )
    assert all(
        entry["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
        for entry in queue["entries"]
    )
    assert all(
        row["candidate_workflow_deployment_target_matrix_provenance"]
        == expected
        for row in ledger["candidates"]
    )


def test_complete_dse_step2_queue_validation_rejects_candidate_order_or_hash_mismatch():
    release_subset = build_release_subset_manifest()
    queue = build_complete_dse_step2_binding_bundle(release_subset)[
        "step3_simulation_queue.json"
    ]

    wrong_order = dict(queue)
    wrong_order["entries"] = list(reversed(queue["entries"]))
    wrong_order["candidate_ids"] = [
        entry["candidate_id"] for entry in wrong_order["entries"]
    ]
    order_validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=wrong_order,
    )
    assert order_validation["valid"] is False
    assert any(
        blocker["id"] == "step3_queue_candidate_order_mismatch"
        for blocker in order_validation["blockers"]
    )

    wrong_hash = dict(queue)
    wrong_hash["release_subset_hash"] = "not-the-release-subset-hash"
    hash_validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=wrong_hash,
    )
    assert hash_validation["valid"] is False
    assert any(
        blocker["id"] == "release_subset_hash_mismatch"
        for blocker in hash_validation["blockers"]
    )

    wrong_declared_ids = dict(queue)
    wrong_declared_ids["candidate_ids"] = list(reversed(queue["candidate_ids"]))
    declared_validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=wrong_declared_ids,
    )
    assert declared_validation["valid"] is False
    assert any(
        blocker["id"] == "step3_queue_declared_candidate_ids_mismatch"
        for blocker in declared_validation["blockers"]
    )


def test_complete_dse_step2_queue_validation_rejects_matrix_provenance_tampering():
    release_subset = build_release_subset_manifest()
    queue = build_complete_dse_step2_binding_bundle(release_subset)[
        "step3_simulation_queue.json"
    ]
    tampered = copy.deepcopy(queue)
    tampered["candidate_workflow_deployment_target_matrix_provenance"][
        "matrix_rows_hash"
    ] = "sha256:manual-top-k-subset"
    tampered["entries"][0]["candidate_workflow_deployment_target_matrix_provenance"][
        "target_kind_axis_complete"
    ] = False
    tampered["queue_hash"] = stable_json_hash(
        {
            key: value
            for key, value in tampered.items()
            if key != "queue_hash"
        }
    )

    validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=tampered,
    )

    assert validation["valid"] is False
    blocker_ids = {blocker["id"] for blocker in validation["blockers"]}
    assert "step3_queue_hash_mismatch" not in blocker_ids
    assert "step3_queue_matrix_provenance_mismatch" in blocker_ids
    assert "step3_queue_entry_identity_invariant_mismatch" in blocker_ids


def test_complete_dse_step2_queue_validation_rejects_entry_identity_tampering():
    release_subset = build_release_subset_manifest()
    queue = build_complete_dse_step2_binding_bundle(release_subset)[
        "step3_simulation_queue.json"
    ]

    tampered = copy.deepcopy(queue)
    tampered["entries"][0]["complete_dse_candidate_id"] = "cdse_wrong_identity"
    tampered["entries"][1]["queue_entry_id"] = "complete-dse-step2::cdse_wrong_entry"
    tampered["entries"][2]["design_point_id"] = "cdse_wrong::__workload_case_bound_at_step3"
    tampered["entries"][3]["mapping_id"] = "wrong_mapping"
    tampered["entries"][4]["target_platform_id"] = "wrong_target"
    validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=tampered,
    )

    assert validation["valid"] is False
    blocker_ids = {blocker["id"] for blocker in validation["blockers"]}
    assert "step3_queue_hash_mismatch" in blocker_ids
    assert "step3_queue_entry_identity_invariant_mismatch" in blocker_ids
    invariant_blocker = next(
        blocker
        for blocker in validation["blockers"]
        if blocker["id"] == "step3_queue_entry_identity_invariant_mismatch"
    )
    mismatched_fields = {
        mismatch["field"]
        for entry in invariant_blocker["entries"]
        for mismatch in entry["mismatches"]
    }
    assert {
        "complete_dse_candidate_id",
        "queue_entry_id",
        "design_point_id",
        "mapping_id",
        "target_platform_id",
    }.issubset(mismatched_fields)

    rehashed_tampered = copy.deepcopy(tampered)
    rehashed_tampered["queue_hash"] = stable_json_hash(
        {
            key: value
            for key, value in rehashed_tampered.items()
            if key != "queue_hash"
        }
    )
    rehashed_validation = validate_complete_dse_step2_queue(
        release_subset=release_subset,
        step3_queue=rehashed_tampered,
    )
    rehashed_blocker_ids = {
        blocker["id"] for blocker in rehashed_validation["blockers"]
    }
    assert rehashed_validation["valid"] is False
    assert "step3_queue_hash_mismatch" not in rehashed_blocker_ids
    assert "step3_queue_entry_identity_invariant_mismatch" in rehashed_blocker_ids


def test_complete_dse_step2_binding_cli_writes_replayable_artifacts(tmp_path: Path):
    out_dir = tmp_path / "step2-binding"
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_complete_dse_step2_binding.py",
            "--out",
            str(out_dir),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["valid"] is True
    assert status["candidate_count"] == build_release_subset_manifest()[
        "legal_candidate_count"
    ]
    assert (out_dir / "release_subset_manifest.json").exists()
    assert (out_dir / "complete_dse_step2_binding.json").exists()
    assert (out_dir / "step3_simulation_queue.json").exists()
    assert (out_dir / "trial_state_ledger.json").exists()
    assert (out_dir / "complete_dse_search_effectiveness_report.json").exists()
    copied_subset = json.loads(
        (out_dir / "release_subset_manifest.json").read_text(encoding="utf-8")
    )
    assert copied_subset["release_subset_hash"] == build_release_subset_manifest()[
        "release_subset_hash"
    ]
    assert status["artifacts"]["release_subset_manifest"].endswith(
        "release_subset_manifest.json"
    )
    assert status["artifacts"]["complete_dse_search_effectiveness_report"].endswith(
        "complete_dse_search_effectiveness_report.json"
    )
    assert json.loads(
        (out_dir / "complete_dse_step2_binding_validation.json").read_text(
            encoding="utf-8"
        )
    )["valid"] is True
