#!/usr/bin/env python3
"""DFT per-candidate evidence ledger closure tests."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.codesign.evidence_ledger import (
    CLAIM_STATUS_POLICY,
    REQUIRED_EVIDENCE_REFS,
    REQUIRED_ROW_FIELDS,
    validate_candidate_evidence_ledger,
)
from dse_v2.codesign.dft_hardware_evidence import (
    MAJOR_SCF_KERNEL_IDS,
    build_ic_eda_tool_availability_report,
    build_major_kernel_evidence_matrix,
    build_major_kernel_evidence_matrix_from_release_gate,
)
from dse_v2.reference_workloads.dft_codesign_domain import write_dft_seven_axis_artifacts
from dse_v2.reference_workloads.dft_evidence_ledger import (
    DFT_EVIDENCE_ARTIFACT_CLASSES,
    DFT_UNSUPPORTED_GAP_LABELS,
    write_dft_candidate_evidence_artifacts,
)
from dse_v2.reference_workloads.dft_full_scf_hybrid import (
    build_full_scf_evaluated_hybrid_payload,
    write_full_scf_evaluated_hybrid_artifacts,
)


def test_dft_candidate_evidence_ledger_has_closed_hash_valid_row_for_every_legal_candidate(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    out_dir = tmp_path / "ledger"

    status = write_dft_candidate_evidence_artifacts(out_dir, release_artifact_dir=release_dir)

    assert status["status"] == "passed"
    assert status["all_rows_closed"] is True
    ledger = json.loads((out_dir / "per_candidate_evidence_ledger.json").read_text())
    release_manifest = json.loads((release_dir / "candidate_universe_manifest.json").read_text())
    validation = validate_candidate_evidence_ledger(out_dir / "per_candidate_evidence_ledger.json")
    assert validation["valid"] is True
    expected_legal_candidate_ids = set(release_manifest["legal_candidate_ids"])
    assert ledger["row_count"] == ledger["legal_candidate_count"] == release_manifest["legal_candidate_count"]
    assert set(ledger["legal_candidate_ids"]) == expected_legal_candidate_ids
    assert set(ledger["evidence_artifact_classes"]) == set(DFT_EVIDENCE_ARTIFACT_CLASSES)
    assert tuple(ledger["claim_status_policy"]) == CLAIM_STATUS_POLICY
    assert CLAIM_STATUS_POLICY == (
        "vertical_slice",
        "partial_mvp",
        "pilot_only",
        "blocked_temporary",
        "unsupported",
        "not_attempted",
        "deliverable_complete",
    )
    assert ledger["coverage_policy"] == {
        "all_candidate_evidence_required": True,
        "top_k_or_representative_subset_allowed_for_execution_order": True,
        "subset_satisfies_release_completion": False,
        "claim_boundary": (
            "Top-K or representative subsets may choose execution order, "
            "but every legal candidate id must have a closed row before "
            "release completion can be considered."
        ),
    }
    assert ledger["release_claim_gate"]["full_universe_closed"] is True
    assert ledger["release_claim_gate"]["all_9_evidence_classes_present"] is True
    assert ledger["release_claim_gate"]["evidence_class_count"] == 9
    assert ledger["release_claim_gate"]["missing_evidence_classes"] == []
    assert ledger["release_claim_gate"]["missing_hard_requirement_rows"] == []
    assert ledger["release_claim_gate"]["all_candidate_claims_eligible"] is False
    assert ledger["release_claim_gate"]["deliverable_complete"] is False
    assert set(ledger["release_claim_gate"]["blocked_candidate_ids"]) == set(ledger["legal_candidate_ids"])
    assert ledger["unsupported_gap_labels"] == [dict(item) for item in DFT_UNSUPPORTED_GAP_LABELS]
    assert {item["label"] for item in ledger["unsupported_gap_labels"]} == {
        "blocked_temporary",
        "unsupported",
        "not_attempted",
        "diagnostic_only",
        "legacy_pilot_only",
    }
    assert all(item["completion_eligible"] is False for item in ledger["unsupported_gap_labels"])
    assert ledger["tool_unavailability_failure_policy"]["accepted_non_completion_statuses"] == [
        "blocked_temporary",
        "unsupported",
    ]
    assert ledger["tool_unavailability_failure_policy"]["completion_eligible"] is False
    assert "never completion evidence" in ledger["tool_unavailability_failure_policy"]["claim_boundary"]
    assert {item["attempt_id"] for item in ledger["tool_attempt_evidence"]} == {
        "local_ic_entrypoint",
        "ic_ssh_fallback",
    }
    for attempt in ledger["tool_attempt_evidence"]:
        assert attempt["status"] in {"blocked_temporary", "unsupported"}
        assert attempt["command"]
        assert attempt["environment"]
        assert attempt["failure_evidence"]
        assert attempt["completion_eligible"] is False

    candidate_ids = [row["candidate_id"] for row in ledger["rows"]]
    assert len(candidate_ids) == len(set(candidate_ids)) == len(expected_legal_candidate_ids)
    assert set(candidate_ids) == expected_legal_candidate_ids
    assert {row["legality"]["status"] for row in ledger["rows"]} == {"legal"}
    routing_summary = ledger["evaluation_policy_routing_summary"]
    assert routing_summary["candidate_count"] == ledger["legal_candidate_count"]
    assert routing_summary["routing_recorded_candidate_count"] == ledger["legal_candidate_count"]
    assert routing_summary["routing_blocked_candidate_count"] > 0
    assert routing_summary["affects_design_legality"] is False
    assert ledger["release_claim_gate"]["routing_blocker_count"] == routing_summary["routing_blocker_count"]
    routing_blocked_rows = [
        row for row in ledger["rows"]
        if row["evaluation_policy_routing"]["routing_compatible"] is not True
    ]
    assert {row["candidate_id"] for row in routing_blocked_rows} == set(
        routing_summary["routing_blocked_candidate_ids"]
    )
    assert {row["legality"]["status"] for row in routing_blocked_rows} == {"legal"}
    assert all(row["legality"]["routing_affects_design_legality"] is False for row in ledger["rows"])
    assert all(row["claim_eligibility"]["routing_affects_design_legality"] is False for row in ledger["rows"])
    for row in routing_blocked_rows:
        assert "evaluation_policy_routing" in row["blocker_status"]["blocked_fields"]
        assert row["blocker_status"]["routing_blocked_fields"] == ["evaluation_policy_routing"]
        assert row["claim_eligibility"]["routing_compatible"] is False
        assert row["claim_eligibility"]["routing_blockers"]
        assert row["claim_eligibility"]["deliverable_complete"] is False
        assert row["evaluation_policy_routing"]["claim_eligibility_blocker"] is True
        assert row["evaluation_policy_routing"]["affects_design_legality"] is False
    legal_id_set = set(ledger["legal_candidate_ids"])
    requirement_matrix = json.loads((out_dir / "requirement_evidence_matrix.json").read_text())
    assert requirement_matrix["status"] == "passed"
    assert requirement_matrix["missing_hard_requirement_rows"] == []
    assert set(requirement_matrix["required_artifact_classes"]) == set(DFT_EVIDENCE_ARTIFACT_CLASSES)
    assert requirement_matrix["missing_artifact_classes"] == []
    matrix_coverage = {
        row["evidence_class"]: row for row in requirement_matrix["artifact_class_coverage"]
    }

    assert set(matrix_coverage) == set(DFT_EVIDENCE_ARTIFACT_CLASSES)
    assert matrix_coverage["requirement_evidence_matrix"]["coverage_status"] == "present_self_describing"
    assert matrix_coverage["requirement_evidence_matrix"]["artifact"]["hash_recorded_in"] == (
        "artifact_hash_manifest.json"
    )
    assert all(row["hard_requirement"] is True for row in requirement_matrix["artifact_class_coverage"])
    assert all(
        row["coverage_status"] == "present_hash_valid"
        for evidence_class, row in matrix_coverage.items()
        if evidence_class != "requirement_evidence_matrix"
    )
    release_report = json.loads((out_dir / "release_report.json").read_text())
    assert release_report["schema_version"] == "dse.dft.release_report.v1"
    assert release_report["status"] == "blocked_temporary"
    assert release_report["deliverable_complete"] is False
    assert release_report["current_claim_status"] == "partial_mvp_blocked_for_deliverable"
    assert set(release_report["evidence_artifact_classes"]) == set(DFT_EVIDENCE_ARTIFACT_CLASSES)
    assert "must not be read as deliverable_complete" in release_report["claim_boundary"]
    claim_report = json.loads((out_dir / "claim_validation_report.json").read_text())
    assert claim_report["schema_version"] == "dse.dft.claim_validation_report.v1"
    assert claim_report["status"] == "passed"
    claim_rows = {row["claim"]: row for row in claim_report["validated_claims"]}
    assert claim_rows["closed_audit_ledger"]["allowed"] is True
    assert claim_rows["all_9_evidence_classes_present"]["allowed"] is True
    assert claim_rows["deliverable_complete"]["allowed"] is False
    assert claim_rows["full_dse_complete"]["allowed"] is False
    assert claim_report["rejected_false_completion_claims"] == [
        "deliverable_complete",
        "full_dse_complete",
    ]
    blocker_report = json.loads((out_dir / "blocker_report.json").read_text())
    assert blocker_report["schema_version"] == "dse.dft.blocker_report.v1"
    assert blocker_report["status"] == "blocked_temporary"
    assert blocker_report["blocked_candidate_count"] == ledger["legal_candidate_count"]
    assert set(blocker_report["blocked_fields"]) == {
        "systemc_status",
        "gem5_status",
        "eda_status",
        "formal_status",
        "numerical_status",
        "runtime_compiler_status",
    }
    assert all(row["completion_eligible"] is False for row in blocker_report["blocker_rows"])
    checklist = json.loads((out_dir / "prompt_to_artifact_checklist.json").read_text())
    assert checklist["schema_version"] == "dse.dft.prompt_to_artifact_checklist.v1"
    checklist_requirements = {row["requirement"] for row in checklist["checklist"]}
    assert {f"evidence_class::{item}" for item in DFT_EVIDENCE_ARTIFACT_CLASSES} <= checklist_requirements
    assert {
        "all_legal_candidate_rows_closed",
        "no_top_k_downgrade",
        "tool_unavailable_is_not_completion",
    } <= checklist_requirements
    signoff = json.loads((out_dir / "verifier_critic_signoff.json").read_text())
    assert signoff["schema_version"] == "dse.dft.verifier_critic_signoff.v1"
    assert signoff["status"] == "passed"
    assert signoff["verifier"]["status"] == "clear_for_structural_audit"
    assert signoff["verifier"]["deliverable_complete_signoff"] is False
    assert signoff["critic"]["status"] == "clear_no_false_completion_claim"
    assert signoff["critic"]["deliverable_complete_signoff"] is False
    assert "top_k_or_representative_subset" in signoff["critic"]["downgrade_loopholes_checked"]
    assert "withholds deliverable_complete signoff" in signoff["claim_boundary"]
    risk_register = json.loads((out_dir / "risk_register.json").read_text())
    assert risk_register["schema_version"] == "dse.dft.risk_register.v1"
    risk_rows = {row["risk_id"]: row for row in risk_register["risks"]}
    assert set(risk_rows) == {
        "candidate_universe_explosion",
        "no_top_k_downgrade",
        "dft_leaks_into_generic_core",
        "evidence_false_closure",
    }
    assert risk_rows["candidate_universe_explosion"]["status"] == "mitigated_for_frozen_release_scope"
    assert "small_but_complete_frozen_release_domain" in risk_rows["candidate_universe_explosion"]["mitigations"]
    assert "deterministic_queue_sharding_metadata" in risk_rows["candidate_universe_explosion"]["mitigations"]
    assert "ultragoal_ledger_resume_retry_checkpointing" in risk_rows["candidate_universe_explosion"]["mitigations"]
    assert risk_rows["candidate_universe_explosion"]["execution_controls"]["sharding"]["deterministic_shard_key"] == "candidate_id"
    assert risk_rows["candidate_universe_explosion"]["execution_controls"]["resume_retry"]["retry_command"] == (
        "omx ultragoal complete-goals --retry-failed"
    )
    assert "coverage_policy_requires_all_candidate_evidence" in risk_rows["no_top_k_downgrade"]["mitigations"]
    assert risk_rows["dft_leaks_into_generic_core"]["status"] == "mitigated_by_plugin_core_boundary"
    assert risk_rows["evidence_false_closure"]["status"] == "mitigated_by_claim_gate"
    assert "unresolved hard-evidence blockers" in risk_register["claim_boundary"]
    lane_report = json.loads((out_dir / "lane_signoff_report.json").read_text())
    assert lane_report["schema_version"] == "dse.dft.lane_signoff_report.v1"
    lane_rows = {row["lane_id"]: row for row in lane_report["lanes"]}
    assert {
        "executor_implementation",
        "test_engineer_tests_and_audit_fixtures",
        "verifier_requirement_evidence_closure",
        "architect_plugin_core_controller_boundary",
        "critic_downgrade_loophole_review",
        "dft_plugin_lane",
        "generic_universe_domain_freeze_lane",
        "global_controller_queue_lane",
        "evidence_ledger_reporting_lane",
        "test_audit_lane",
        "verifier_architect_critic_lane",
    } <= set(lane_rows)
    assert lane_rows["executor_implementation"]["status"] == "complete"
    assert lane_rows["test_engineer_tests_and_audit_fixtures"]["status"] == "complete"
    assert lane_rows["verifier_requirement_evidence_closure"]["status"] == "complete_for_structural_audit"
    assert "hard-evidence blockers" in lane_report["claim_boundary"]
    hash_manifest = json.loads((out_dir / "artifact_hash_manifest.json").read_text())
    assert set(hash_manifest["artifacts"]) == set(DFT_EVIDENCE_ARTIFACT_CLASSES)
    assert set(hash_manifest["report_artifacts"]) == {
        "release_report",
        "claim_validation_report",
        "blocker_report",
        "prompt_to_artifact_checklist",
        "verifier_critic_signoff",
        "risk_register",
        "lane_signoff_report",
    }
    for artifact_name, evidence_class in [
        ("systemc_candidate_evidence.json", "systemc_candidate_evidence"),
        ("gem5_candidate_evidence.json", "gem5_candidate_evidence"),
        ("non_smoke_systemc_gem5_evidence.json", "non_smoke_systemc_gem5_evidence"),
    ]:
        artifact = json.loads((out_dir / artifact_name).read_text())
        assert artifact["evidence_class"] == evidence_class
        assert artifact["status"] == "blocked_temporary"
        assert artifact["candidate_count"] == ledger["legal_candidate_count"]
        assert {record["candidate_id"] for record in artifact["candidate_records"]} == legal_id_set
        assert {record["status"] for record in artifact["candidate_records"]} == {"blocked_temporary"}
        assert "not completion evidence" in artifact["candidate_records"][0]["claim_boundary"]
        assert "deliverable_complete false" in artifact["claim_boundary"]
    non_smoke = json.loads((out_dir / "non_smoke_systemc_gem5_evidence.json").read_text())
    assert non_smoke["non_smoke_classifier"] == "required_for_deliverable_complete"
    assert non_smoke["systemc_evidence"]["path"] == "systemc_candidate_evidence.json"
    assert non_smoke["gem5_evidence"]["path"] == "gem5_candidate_evidence.json"
    eda = json.loads((out_dir / "eda_all_candidate_evidence.json").read_text())
    assert eda["real_toolchain_policy"]["required_when_available"] is True
    assert eda["real_toolchain_policy"]["required_tools"] == ["dc_shell", "vcs", "vivado"]
    assert eda["real_toolchain_policy"]["completion_eligible_without_real_tool_artifacts"] is False
    assert eda["tool_unavailability_failure_policy"] == ledger["tool_unavailability_failure_policy"]
    assert eda["tool_attempt_evidence"] == ledger["tool_attempt_evidence"]
    assert {record["candidate_id"] for record in eda["candidate_records"]} == legal_id_set
    assert {record["eda_job_id"] for record in eda["candidate_records"]} == {
        f"eda::{candidate_id}" for candidate_id in legal_id_set
    }
    assert {tuple(record["toolchain_status"]["required_tools"]) for record in eda["candidate_records"]} == {
        ("dc_shell", "vcs", "vivado")
    }
    assert {record["toolchain_status"]["status"] for record in eda["candidate_records"]} == {"blocked_temporary"}
    assert all("not synthesis" in record["claim_boundary"] for record in eda["candidate_records"])
    formal = json.loads((out_dir / "formal_proof_evidence.json").read_text())
    formal_property_ids = {item["property_id"] for item in formal["formal_property_set"]}
    assert formal_property_ids == {
        "genericaccel_descriptor_magic_version",
        "request_result_completion_memory_bounds",
        "completion_writeback_eventual",
        "candidate_id_binding_stable",
        "no_descriptor_only_completion_claim",
    }
    assert {row["candidate_id"] for row in formal["applicability_matrix"]} == legal_id_set
    assert {row["proof_status"] for row in formal["applicability_matrix"]} == {"blocked_temporary"}
    assert {row["completion_eligible"] for row in formal["applicability_matrix"]} == {False}
    assert all(set(row["applicable_property_ids"]) == formal_property_ids for row in formal["applicability_matrix"])
    assert {record["formal_job_id"] for record in formal["candidate_records"]} == {
        f"formal::{candidate_id}" for candidate_id in legal_id_set
    }
    assert all(record["proof_status"]["proof_artifacts"] == [] for record in formal["candidate_records"])
    assert "specified but unproved" in formal["candidate_records"][0]["claim_boundary"]
    numerical = json.loads((out_dir / "numerical_correctness_evidence.json").read_text())
    numerical_source_ids = {item["reference_source_id"] for item in numerical["numerical_reference_sources"]}
    numerical_metric_ids = {item["metric_id"] for item in numerical["correctness_metrics"]}
    assert numerical_source_ids == {
        "qe_pw_reference",
        "vasp_reference",
        "trusted_microkernel_reference",
    }
    assert numerical_metric_ids == {
        "total_energy_delta",
        "band_eigenvalue_delta",
        "force_component_delta",
        "stress_tensor_delta",
        "charge_density_l2_relative",
    }
    assert numerical["requires_real_or_trusted_reference_outputs"] is True
    assert numerical["importer_fixture_coverage_matrix"]["required_importer_ids"] == [
        "dft_qe_pw",
        "dft_vasp",
    ]
    assert {row["candidate_id"] for row in numerical["applicability_matrix"]} == legal_id_set
    assert {row["completion_eligible"] for row in numerical["applicability_matrix"]} == {False}
    assert all(
        set(row["reference_source_ids"]) == numerical_source_ids
        for row in numerical["applicability_matrix"]
    )
    assert all(set(row["metric_ids"]) == numerical_metric_ids for row in numerical["applicability_matrix"])
    assert {record["numerical_job_id"] for record in numerical["candidate_records"]} == {
        f"numerical::{candidate_id}" for candidate_id in legal_id_set
    }
    assert {record["comparison_status"]["status"] for record in numerical["candidate_records"]} == {
        "blocked_temporary"
    }
    assert all(record["comparison_status"]["reference_outputs"] == [] for record in numerical["candidate_records"])
    assert "not correctness" in numerical["candidate_records"][0]["claim_boundary"]
    runtime = json.loads((out_dir / "production_runtime_compiler_evidence.json").read_text())
    runtime_path_ids = {item["path_id"] for item in runtime["runtime_compiler_paths"]}
    assert runtime["production_runtime_compiler_contract"]["one_off_script_only"] is False
    assert runtime["production_runtime_compiler_contract"]["path_type"] == "repo_native_runtime_compiler_path"
    assert runtime_path_ids == {
        "runtime_command_descriptor_abi",
        "runtime_submit_api",
        "runtime_submit_implementation",
        "genericaccel_l4_driver",
        "genericaccel_l4_config",
        "crosscompile_container",
    }
    assert {row["candidate_id"] for row in runtime["applicability_matrix"]} == legal_id_set
    assert {row["completion_eligible"] for row in runtime["applicability_matrix"]} == {False}
    assert all(set(row["runtime_compiler_path_ids"]) == runtime_path_ids for row in runtime["applicability_matrix"])
    assert {record["runtime_compiler_job_id"] for record in runtime["candidate_records"]} == {
        f"runtime_compiler::{candidate_id}" for candidate_id in legal_id_set
    }
    assert {record["one_off_script_only"] for record in runtime["candidate_records"]} == {False}
    assert {record["build_status"]["status"] for record in runtime["candidate_records"]} == {
        "blocked_temporary"
    }
    assert all(record["build_status"]["build_artifacts"] == [] for record in runtime["candidate_records"])
    assert "not a production build" in runtime["candidate_records"][0]["claim_boundary"]
    for row in ledger["rows"]:
        for field in REQUIRED_ROW_FIELDS:
            assert field in row
        assert row["row_status"] == "closed"
        assert row["legality"]["status"] == "legal"
        assert row["claim_eligibility"]["deliverable_complete"] is False
        assert row["blocker_status"]["status"] == "blocked_temporary"
        assert set(row["release_domain_hashes"]) == {
            "seven_axis_domain_freeze",
            "candidate_universe_manifest",
            "candidate_legality_report",
        }
        for field in REQUIRED_EVIDENCE_REFS:
            ref = row[field]
            assert ref["path"]
            assert ref["hash"]
            assert (out_dir / ref["path"]).exists()


def test_release_gate_backed_major_kernel_matrix_trusts_only_complete_hard_gates():
    required_stage_ids = [
        "golden_correctness",
        "hls_or_rtl_sim",
        "hls_or_rtl_synth",
        "vivado_fpga_synth_or_impl",
        "dc_asic_synth_timing_area",
    ]
    candidate_ids = ["cand-a", "cand-b"]
    unit_rows = [
        {
            "candidate_id": candidate_id,
            "kernel_id": kernel_id,
            "unit_gate_passed": True,
            "observed_stage_ids": list(required_stage_ids),
            "status": "unit_gate_passed",
        }
        for candidate_id in candidate_ids
        for kernel_id in MAJOR_SCF_KERNEL_IDS
    ]
    release_gate = {
        "schema_version": "dse.dft.hardware_closure_release_gate.v1",
        "release_id": "release-test",
        "expected_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "candidate_count": len(candidate_ids),
        "unit_count": len(unit_rows),
        "stage_count": len(unit_rows) * len(required_stage_ids),
        "stage_gate_passed_count": len(unit_rows) * len(required_stage_ids),
        "unit_gate_passed_count": len(unit_rows),
        "candidate_gate_passed_count": len(candidate_ids),
        "blocked_stage_count": 0,
        "failed_stage_count": 0,
        "blocked_unit_count": 0,
        "failed_unit_count": 0,
        "blocked_candidate_count": 0,
        "failed_candidate_count": 0,
        "hardware_completion_eligible": True,
        "deliverable_complete": False,
        "candidate_rows": [{"candidate_id": candidate_id} for candidate_id in candidate_ids],
        "unit_rows": unit_rows,
    }

    matrix = build_major_kernel_evidence_matrix_from_release_gate(
        release_gate,
        source_ref={"path": "dft_hardware_closure_release_gate.json", "exists": True},
    )

    assert matrix["status"] == "passed"
    assert matrix["trusted"] is True
    assert matrix["hardware_completion_eligible"] is True
    assert matrix["deliverable_complete"] is False
    assert matrix["candidate_count"] == 2
    assert matrix["unit_count"] == 16
    assert {row["kernel_id"] for row in matrix["kernel_rows"]} == set(MAJOR_SCF_KERNEL_IDS)
    assert all(row["trusted"] is True for row in matrix["kernel_rows"])

    broken = dict(release_gate)
    broken["unit_rows"] = [dict(row) for row in unit_rows]
    broken["unit_rows"][0]["observed_stage_ids"] = required_stage_ids[:-1]
    blocked = build_major_kernel_evidence_matrix_from_release_gate(broken)
    assert blocked["status"] == "blocked"
    assert "release_gate_unit_missing_required_stages" in blocked["blocker_ids"]


def test_dft_candidate_evidence_ledger_attaches_ic_eda_and_major_kernel_matrix_without_false_completion(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    manifest = json.loads((release_dir / "candidate_universe_manifest.json").read_text(encoding="utf-8"))
    matrix_candidate_id = next(
        str(candidate["candidate_id"])
        for candidate in manifest["candidates"]
        if candidate.get("legal") is True
    )
    hardware_dir = tmp_path / "hardware"
    hardware_dir.mkdir()
    tool_report = build_ic_eda_tool_availability_report(
        [
            {
                "tool": "dc_shell",
                "returncode": 1,
                "stdout": "dc_shell version O-2018.06-SP1",
                "stderr": "",
                "command": "ssh ic-eda dc_shell -version",
            },
            {
                "tool": "vcs",
                "returncode": 0,
                "stdout": "VCS version O-2018.09",
                "stderr": "",
                "command": "ssh ic-eda vcs -ID",
            },
            {
                "tool": "vivado",
                "returncode": 0,
                "stdout": "Vivado v2019.1",
                "stderr": "",
                "command": "ssh ic-eda vivado -version",
            },
        ],
        environment="ssh ic-eda",
    )
    matrix = build_major_kernel_evidence_matrix(
        [
            {
                "kernel_id": kernel_id,
                "disposition": "host_bound",
                "host_cost_accounted": True,
            }
            for kernel_id in MAJOR_SCF_KERNEL_IDS
        ],
        candidate_id=matrix_candidate_id,
    )
    tool_path = hardware_dir / "ic_eda_tool_availability.json"
    matrix_path = hardware_dir / "dft_hardware_evidence_matrix.json"
    tool_path.write_text(json.dumps(tool_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_dir = tmp_path / "ledger"

    status = write_dft_candidate_evidence_artifacts(
        out_dir,
        release_artifact_dir=release_dir,
        ic_eda_tool_availability_path=tool_path,
        dft_hardware_evidence_matrix_path=matrix_path,
    )

    assert status["status"] == "passed"
    eda = json.loads((out_dir / "eda_all_candidate_evidence.json").read_text())
    assert eda["status"] == "blocked_temporary"
    assert eda["tool_availability_status"] == "passed"
    assert eda["major_kernel_matrix_status"] == "passed"
    assert eda["major_kernel_matrix_trusted"] is True
    assert eda["attached_hardware_evidence_structurally_ready"] is True
    assert eda["hardware_completion_eligible"] is False
    assert eda["ic_eda_tool_availability"]["path"] == str(tool_path)
    assert tool_report["completion_claim"] == "availability_only_not_kernel_ppa"
    assert tool_report["kernel_ppa_evidence"] is False
    assert tool_report["hardware_completion_eligible"] is False
    assert eda["dft_hardware_evidence_matrix"]["path"] == str(matrix_path)
    assert {source["path"] for source in eda["source_artifacts"]} >= {
        str(tool_path),
        str(matrix_path),
    }
    assert eda["hardware_evidence_attachment_policy"]["availability_only_not_ppa"] is True
    assert eda["hardware_evidence_attachment_policy"]["matrix_coverage_only_not_full_scf_completion"] is True
    assert "remains blocked_temporary" in eda["hardware_evidence_attachment_policy"]["claim_boundary"]
    candidate_records = {record["candidate_id"]: record for record in eda["candidate_records"]}
    matching_summary = candidate_records[matrix_candidate_id]["candidate_hardware_gate_summary"]
    assert matching_summary["attached"] is True
    assert matching_summary["candidate_id_match"] is True
    assert matching_summary["kernel_gate_audit_ready"] is True
    assert matching_summary["matrix_trusted"] is True
    assert matching_summary["hardware_gate_claim_eligible"] is False
    assert matching_summary["completion_eligible"] is False
    assert set(matching_summary["host_bound_kernel_ids"]) == set(MAJOR_SCF_KERNEL_IDS)
    nonmatching_summary = next(
        record["candidate_hardware_gate_summary"]
        for candidate_id, record in candidate_records.items()
        if candidate_id != matrix_candidate_id
    )
    assert nonmatching_summary["attached"] is True
    assert nonmatching_summary["candidate_id_match"] is False
    assert nonmatching_summary["kernel_gate_audit_ready"] is False
    assert nonmatching_summary["hardware_gate_claim_eligible"] is False
    checklist = json.loads((out_dir / "prompt_to_artifact_checklist.json").read_text())
    checklist_rows = {row["requirement"]: row for row in checklist["checklist"]}
    assert checklist_rows["ic_eda_tool_availability_recorded"]["status"] == "present_hash_valid"
    assert checklist_rows["ic_eda_tool_availability_recorded"]["completion_claim"] == (
        "availability_only_not_kernel_ppa"
    )
    assert checklist_rows["major_kernel_evidence_matrix_recorded"]["status"] == "present_hash_valid"
    assert checklist_rows["major_kernel_evidence_matrix_recorded"]["completion_claim"] == (
        "matrix_coverage_only_not_full_scf_completion"
    )
    release_report = json.loads((out_dir / "release_report.json").read_text())
    assert release_report["deliverable_complete"] is False
    ledger = json.loads((out_dir / "per_candidate_evidence_ledger.json").read_text())
    assert ledger["release_claim_gate"]["deliverable_complete"] is False


def test_dft_candidate_evidence_ledger_attaches_full_scf_hybrid_bundle_without_false_completion(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    manifest = json.loads((release_dir / "candidate_universe_manifest.json").read_text(encoding="utf-8"))
    candidate_id = next(
        str(candidate["candidate_id"])
        for candidate in manifest["candidates"]
        if candidate.get("legal") is True
    )
    bundle_dir = tmp_path / "full_scf_hybrid_bundle"
    payload = build_full_scf_evaluated_hybrid_payload(
        candidate_id=candidate_id,
        campaign_id="campaign-ledger-full-scf",
        workload_run_id="workload-ledger-full-scf",
        trial_id="trial-ledger-full-scf",
        accelerated_kernel_costs_s={kernel_id: 1.0 for kernel_id in MAJOR_SCF_KERNEL_IDS},
        host_bound_costs_s={
            "io": 1.0,
            "scf_control": 2.0,
            "convergence": 3.0,
            "diagonalization": 4.0,
            "mixing": 5.0,
        },
        overhead_costs_s={
            "transfer": 0.5,
            "synchronization": 0.25,
            "queueing": 0.125,
            "layout": 0.75,
        },
        baseline_scf_time_s=100.0,
    )
    write_full_scf_evaluated_hybrid_artifacts(bundle_dir, payload)
    out_dir = tmp_path / "ledger"

    write_dft_candidate_evidence_artifacts(
        out_dir,
        release_artifact_dir=release_dir,
        full_scf_hybrid_artifact_dir=bundle_dir,
    )

    ledger = json.loads((out_dir / "per_candidate_evidence_ledger.json").read_text(encoding="utf-8"))
    release_report = json.loads((out_dir / "release_report.json").read_text(encoding="utf-8"))
    checklist = json.loads((out_dir / "prompt_to_artifact_checklist.json").read_text(encoding="utf-8"))
    hash_manifest = json.loads((out_dir / "artifact_hash_manifest.json").read_text(encoding="utf-8"))
    bundle = ledger["full_scf_hybrid_bundle"]
    assert bundle["status"] == "present_hash_valid"
    assert bundle["required_artifacts_present"] is True
    assert bundle["candidate_id"] == candidate_id
    assert bundle["completion_claim"] is False
    assert bundle["numerical_correctness_claim_eligible"] is False
    assert bundle["ppa_claim_eligible"] is False
    assert set(bundle["artifact_refs"]) == {
        "full_scf_accelerator_descriptor.json",
        "full_scf_runtime_schedule.json",
        "full_scf_data_residency_plan.json",
        "full_scf_correctness_report.json",
        "full_scf_ppa_summary.json",
    }
    assert release_report["full_scf_hybrid_bundle"]["completion_claim"] is False
    assert ledger["release_claim_gate"]["deliverable_complete"] is False
    checklist_rows = {row["requirement"]: row for row in checklist["checklist"]}
    assert checklist_rows["full_scf_hybrid_bundle_recorded"]["status"] == "present_hash_valid"
    assert checklist_rows["full_scf_hybrid_bundle_recorded"]["completion_claim"] == (
        "descriptor_accounting_only_not_full_scf_completion"
    )
    assert len(hash_manifest["source_full_scf_hybrid_artifacts"]) == 5


def test_dft_candidate_evidence_ledger_rejects_missing_row_and_hash_tamper(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    out_dir = tmp_path / "ledger"
    write_dft_candidate_evidence_artifacts(out_dir, release_artifact_dir=release_dir)

    ledger_path = out_dir / "per_candidate_evidence_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    removed = ledger["legal_candidate_ids"][0]
    ledger["rows"] = [row for row in ledger["rows"] if row["candidate_id"] != removed]
    missing_validation = validate_candidate_evidence_ledger(
        ledger,
        base_dir=out_dir,
        expected_legal_candidate_ids=ledger["legal_candidate_ids"],
    )
    assert missing_validation["valid"] is False
    assert missing_validation["errors"][0]["missing_candidate_ids"] == [removed]

    (out_dir / "systemc_candidate_evidence.json").write_text("{}\n")
    tamper_validation = validate_candidate_evidence_ledger(ledger_path)
    assert tamper_validation["valid"] is False
    assert any(error["message"] == "artifact hash mismatch" for error in tamper_validation["errors"])


def test_dft_candidate_evidence_ledger_cli_emits_required_artifacts(tmp_path):
    release_dir = tmp_path / "release"
    write_dft_seven_axis_artifacts(release_dir)
    out_dir = tmp_path / "cli_ledger"

    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_candidate_evidence_ledger.py",
            "--out",
            str(out_dir),
            "--release-artifact-dir",
            str(release_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    status = json.loads(result.stdout)
    assert status["status"] == "passed"
    for name in [
        "per_candidate_evidence_ledger.json",
        "per_candidate_evidence_ledger_validation.json",
        "requirement_evidence_matrix.json",
        "dft_workload_suite_artifacts.json",
        "seven_axis_search_space_reports.json",
        "closed_loop_feedback_traces.json",
        "non_smoke_systemc_gem5_evidence.json",
        "eda_all_candidate_evidence.json",
        "numerical_correctness_evidence.json",
        "production_runtime_compiler_evidence.json",
        "formal_proof_evidence.json",
        "release_report.json",
        "claim_validation_report.json",
        "blocker_report.json",
        "prompt_to_artifact_checklist.json",
        "verifier_critic_signoff.json",
        "risk_register.json",
        "lane_signoff_report.json",
        "artifact_hash_manifest.json",
        "status.json",
    ]:
        assert (out_dir / name).exists()
