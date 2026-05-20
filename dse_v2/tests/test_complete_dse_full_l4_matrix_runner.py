"""Regression tests for exhaustive complete-DSE full L4 matrix runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


RUNNER = Path("dse_v2/scripts/dse/run_complete_dse_full_l4_matrix.py")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_scf_input(class_id: str) -> str:
    return (
        "&CONTROL\n"
        "  calculation = 'scf'\n"
        f"  prefix = '{class_id}'\n"
        "/\n"
        "&SYSTEM\n"
        "  ibrav = 2, nat = 2, ntyp = 1, ecutwfc = 12.0, nbnd = 8\n"
        "/\n"
        "&ELECTRONS\n"
        "  conv_thr = 1.0d-6\n"
        "/\n"
        "ATOMIC_SPECIES\n"
        "  Si 28.0855 Si.pz-vbc.UPF\n"
        "ATOMIC_POSITIONS alat\n"
        "  Si 0.00 0.00 0.00\n"
        "  Si 0.25 0.25 0.25\n"
        "K_POINTS automatic\n"
        "2 2 2 0 0 0\n"
    )


def _write_current_goal_six_scf_suite(tmp_path: Path, *, with_descriptors: bool = True) -> Path:
    from dse_v2.reference_workloads.dft_current_goal_l4_bridge import (
        DFT_CURRENT_GOAL_SIX_SCF_WORKLOAD_SUITE_SCHEMA,
    )
    from dse_v2.reference_workloads.dft_scf_six_class_suite import REQUIRED_DFT_SCF_CLASS_IDS

    suite_root = tmp_path / "six_scf_bundle"
    descriptor_root = suite_root / "descriptors"
    descriptor_root.mkdir(parents=True)
    cases = []
    for class_id in REQUIRED_DFT_SCF_CLASS_IDS:
        case_id = f"{class_id}_case"
        descriptor_ref = None
        if with_descriptors:
            descriptor_path = descriptor_root / f"{class_id}_descriptor.json"
            _write_json(
                descriptor_path,
                {
                    "schema_version": "dse.dft_scf.six_class_case_descriptor.v1",
                    "case_id": case_id,
                    "class_id": class_id,
                    "workload_class": class_id,
                    "qe_input": {
                        "path": f"qe_inputs/{class_id}.in",
                        "text": _minimal_scf_input(class_id),
                        "sha256": "not-used-by-runner-for-text-fixture",
                    },
                    "qe_command_template": ["${QE_PW_CMD:-pw.x}", "-in", f"qe_inputs/{class_id}.in"],
                    "proof_class": "synthetic_descriptor_runnable_fixture_not_final_qe_evidence",
                    "final_real_qe_evidence": False,
                    "hardware_completion_eligible": False,
                    "deliverable_complete": False,
                },
            )
            descriptor_ref = {
                "path": f"descriptors/{class_id}_descriptor.json",
                "sha256": _sha256_file(descriptor_path),
                "hash_algorithm": "sha256",
            }
        case = {
            "case_id": case_id,
            "workload_case_id": case_id,
            "class_id": class_id,
            "workload_class": class_id,
            "proof_class": "synthetic_descriptor_runnable_fixture_not_final_qe_evidence",
            "reference_output_hash": None,
            "final_real_qe_evidence": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        }
        if descriptor_ref is not None:
            case["descriptor"] = descriptor_ref
        cases.append(case)

    manifest_path = suite_root / "workload_suite_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": DFT_CURRENT_GOAL_SIX_SCF_WORKLOAD_SUITE_SCHEMA,
            "status": "strict_six_scf_identity_manifest_only_pending_l4_regeneration",
            "suite_id": "test_dft_current_goal_six_scf_l4_suite",
            "strict": True,
            "descriptor_plus_runnable_bundle": True,
            "expected_workload_count": len(cases),
            "workload_case_count": len(cases),
            "case_count": len(cases),
            "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "workload_classes": list(REQUIRED_DFT_SCF_CLASS_IDS),
            "workload_case_ids": [case["case_id"] for case in cases],
            "cases": cases,
            "final_real_qe_evidence": False,
            "gem5_l4_evidence_present": False,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    return manifest_path


def test_matrix_normalizer_blocks_trusted_source_without_offload_provenance():
    from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _normalize_accelerated_numeric_payload

    normalized = _normalize_accelerated_numeric_payload(
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "candidate_id": "cand",
            "workload_case_id": "qe_case",
            "source_kind": "qe_offload_runtime",
            "accelerated_output_status": "passed",
            "kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 1.0e-12,
                    "relative_error": 1.0e-10,
                }
            ],
            "physical_evidence": {
                "total_energy_error_ry": 1.0e-8,
                "density_residual": 1.0e-8,
                "eigenvalue_summary_error_ry": 1.0e-7,
            },
        },
        candidate_id="cand",
        workload_case_id="qe_case",
        row_id="cand::qe_case",
        source="unit_test",
    )

    assert normalized["trusted_accelerated_numeric_source"] is False
    assert "missing_offload_provenance_for_trusted_source" in normalized["blockers"]


def test_blocker_counts_include_matrix_closure_blockers():
    from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _blocker_counts

    counts = _blocker_counts(
        [
            {"blockers": ["payload_declares_accelerated_numeric_source_untrusted"]},
            {
                "blockers": [
                    "payload_declares_accelerated_numeric_source_untrusted",
                    "trusted_correctness_source_not_eligible",
                ]
            },
        ]
    )

    assert counts["payload_declares_accelerated_numeric_source_untrusted"] == 2
    assert counts["trusted_correctness_source_not_eligible"] == 1


def test_gpu_runtime_context_records_available_nvidia_smi(monkeypatch):
    from dse_v2.scripts.dse import run_complete_dse_full_l4_matrix as runner

    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def fake_run(command, *, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="NVIDIA GeForce RTX 3070, 596.36, 8192 MiB\n",
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    context = runner._gpu_runtime_context()

    assert context["gpu_available"] is True
    assert context["nvidia_smi_available"] is True
    assert context["gpus"] == ["NVIDIA GeForce RTX 3070, 596.36, 8192 MiB"]


def test_default_workload_suite_regenerates_stale_manifest(tmp_path):
    from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _materialize_default_workload_suite

    out_dir = tmp_path / "matrix"
    stale = out_dir / "qe_mainflow_workload_suite_manifest.json"
    _write_json(
        stale,
        {
            "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
            "suite_hash": "stale_hash",
            "cases": [
                {
                    "case_id": "qe_si_scf_small_v1",
                    "step1_source": {
                        "stages": [
                            {
                                "input": "&SYSTEM\n  ibrav = 2, nat = 2, ntyp = 1\n/\n",
                                "input_path": "fixtures/qe/si_scf.in",
                            }
                        ]
                    },
                }
            ],
        },
    )

    path = _materialize_default_workload_suite(out_dir)

    regenerated = json.loads(path.read_text(encoding="utf-8"))
    assert regenerated["suite_hash"] != "stale_hash"
    assert "celldm(1)" in regenerated["cases"][0]["step1_source"]["stages"][0]["input"]
    assert list(out_dir.glob("qe_mainflow_workload_suite_manifest.stale-*.json"))


def test_l4_result_transport_echo_cannot_be_trusted_numeric_evidence(tmp_path):
    from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _build_accelerated_numeric_evidence

    row_dir = tmp_path / "out" / "rows" / "cand_a" / "qe_case"
    row_dir.mkdir(parents=True)
    trusted_looking_echo = {
        "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
        "candidate_id": "cand_a",
        "workload_case_id": "qe_case",
        "source_kind": "qe_offload_runtime",
        "accelerated_output_status": "passed",
        "trusted_accelerated_numeric_source": True,
        "offload_provenance": {
            "producer": "echoed-by-generic-transport",
            "accelerated_runtime": "qe_offload_runtime",
            "offload_target": "gem5_generic_accel",
            "full_h_psi_recomputed": True,
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "l4_execution_proof": {
                "passed": True,
                "transport_harness": "gem5_generic_accel_microarchitecture_v1",
            },
        },
        "kernel_evidence": [
            {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "absolute_error": 0.0,
                "relative_error": 0.0,
            }
        ],
        "physical_evidence": {
            "total_energy_error_ry": 0.0,
            "density_residual": 0.0,
            "eigenvalue_summary_error_ry": 0.0,
        },
    }

    evidence = _build_accelerated_numeric_evidence(
        candidate_id="cand_a",
        workload_case_id="qe_case",
        row_id="cand_a::qe_case",
        baseline={"baseline_status": "real_qe_baseline"},
        l4_attempt={"result": {"qe_accelerated_numeric_evidence": trusted_looking_echo}},
        external_evidence=None,
        row_dir=row_dir,
    )

    assert evidence["status"] == "blocked"
    assert evidence["trusted_accelerated_numeric_source"] is False
    assert evidence["accelerated_output_status"] == "blocked"
    assert "generic_accel_transport_echo_not_numeric_evidence" in evidence["blockers"]


def test_full_l4_matrix_runner_emits_every_candidate_workload_row_without_completion_downgrade(tmp_path):
    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(
        release_subset,
        {
            "schema_version": "test.release_subset",
            "release_subset_hash": "release_hash",
            "legal_candidate_ids": ["cand_a", "cand_b"],
            "candidates": [
                {
                    "candidate_id": "cand_a",
                    "legal": True,
                    "identity": {"identity_layers": {"architecture_parameters": {"taxonomy_id": "streaming_pipeline"}}},
                },
                {
                    "candidate_id": "cand_b",
                    "legal": True,
                    "identity": {"identity_layers": {"architecture_parameters": {"taxonomy_id": "simd_vector"}}},
                },
            ],
        },
    )

    out_dir = tmp_path / "matrix"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(out_dir),
            "--release-subset",
            str(release_subset),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    status = json.loads(completed.stdout)
    rows = json.loads((out_dir / "evidence_rows.json").read_text(encoding="utf-8"))
    matrix = json.loads((out_dir / "l4_evidence_matrix.json").read_text(encoding="utf-8"))
    coverage = json.loads((out_dir / "coverage_claim_report.json").read_text(encoding="utf-8"))
    report = json.loads((out_dir / "complete_dse_full_l4_evidence_report.json").read_text(encoding="utf-8"))
    requirements = json.loads((out_dir / "qe_accelerated_numeric_evidence_requirements.json").read_text(encoding="utf-8"))

    assert status["expected_row_count"] == 8
    assert rows["row_count"] == 8
    assert matrix["expected_row_count"] == 8
    assert requirements["row_count"] == 8
    assert "qe_offload_runtime" in requirements["trusted_source_kinds"]
    assert "fixture" in requirements["blocked_source_kinds"]
    assert any("run_qe_accelerated_numeric_producer.py" in item for item in requirements["campaign_producer_command_template"])
    assert any(
        "run_qe_hpsi_sidecar_bridge_campaign.py" in item
        for item in requirements["hpsi_sidecar_bridge_campaign_command_template"]
    )
    assert all("producer_command_template" in row for row in requirements["rows"])
    assert all("hpsi_sidecar_bridge_command_template" in row for row in requirements["rows"])
    assert all(
        "run_qe_hpsi_sidecar_bridge.py" in item
        for row in requirements["rows"]
        for item in row["hpsi_sidecar_bridge_command_template"]
        if item.endswith(".py")
    )
    assert "full_h_psi_recomputed=true" in requirements["hpsi_sidecar_bridge_note"]
    assert "full_kernel_recomputed=true" in requirements["hpsi_sidecar_bridge_note"]
    assert "not h_psi-only" in requirements["selected_kernel_evidence_note"]
    assert "selected offload kernel" in requirements["selected_kernel_evidence_note"]
    assert all("target_kernel_evidence_requirements" in row for row in requirements["rows"])
    assert all(
        row["target_kernel_evidence_requirements"]["requires_full_kernel_recomputed"] is True
        for row in requirements["rows"]
    )
    assert all(
        row["target_kernel_evidence_requirements"]["requires_accelerated_results_consumed_by_qe"] is True
        for row in requirements["rows"]
    )
    assert all(
        row["target_kernel_evidence_requirements"]["hpsi_specific_completion_allowed"] is False
        for row in requirements["rows"]
    )
    assert any(
        "another selected QE offload kernel" in row["target_kernel_evidence_requirements"]["claim_boundary"]
        for row in requirements["rows"]
    )
    assert all("kernel_boundary_arrays_json" in row["required_outputs"] for row in requirements["rows"])
    assert matrix["row_count"] == 8
    assert coverage["all_rows_present"] is True
    assert coverage["claims"]["deliverable_complete"] is False
    assert coverage["claims"]["top_k_or_representative_completion_allowed"] is False
    assert report["claims"]["foundation_artifacts_emitted"] is True
    assert report["claims"]["mvp_partial"] is True
    assert report["claims"]["deliverable_complete"] is False
    assert report["qe_accelerated_numeric_evidence_requirements_path"].endswith(
        "qe_accelerated_numeric_evidence_requirements.json"
    )
    assert all(row["evidence_present"] is True for row in matrix["rows"])
    assert all(row["deliverable_complete_eligible"] is False for row in matrix["rows"])


def test_full_l4_matrix_runner_fail_on_blocked_is_explicit(tmp_path):
    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(release_subset, {"legal_candidate_ids": ["cand_a"], "candidates": [{"candidate_id": "cand_a", "legal": True}]})

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(tmp_path / "matrix"),
            "--release-subset",
            str(release_subset),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
            "--fail-on-blocked",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    status = json.loads(completed.stdout)
    assert status["expected_row_count"] == 4
    assert status["deliverable_complete"] is False


def test_full_l4_matrix_runner_resolves_qe_executables_from_qe_bin_dir(tmp_path):
    fake_bin = tmp_path / "qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "print('!    total energy              =      -1.00000000 Ry')\n"
        "print('     convergence has been achieved in   1 iterations')\n"
        "print('     PWSCF        :      0.01s CPU      0.02s WALL')\n"
        "print('   JOB DONE.')\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)
    pseudo_dir = tmp_path / "pseudo"
    pseudo_dir.mkdir()
    (pseudo_dir / "Si.pz-vbc.UPF").write_text("fake pseudo for executable-resolution test\n", encoding="utf-8")

    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(release_subset, {"legal_candidate_ids": ["cand_a"], "candidates": [{"candidate_id": "cand_a", "legal": True}]})
    workload_suite = tmp_path / "workload_suite.json"
    qe_input = "&CONTROL\n  calculation = 'scf'\n/\n&SYSTEM\n  ibrav = 0, nat = 0, ntyp = 0\n/\n&ELECTRONS\n/\n"
    _write_json(
        workload_suite,
        {
            "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
            "status": "test",
            "suite_id": "test_qe_bin_dir_resolution",
            "candidate_identity_policy": {"workload_case_ids_participate": False},
            "cases": [
                {
                    "case_id": "qe_fake_scf_v1",
                    "stage_type": "scf",
                    "workflow_class": "scf",
                    "qe_command": ["pw.x", "-in", "fake_scf.in"],
                    "input_hashes": {"fixtures/qe/fake_scf.in": "0" * 64},
                    "expected_outputs": {"total_energy_ry": {"value": -1.0}},
                    "kernel_coverage": ["h_psi"],
                    "physical_quantities": ["total_energy_ry"],
                    "baseline_run_provenance": {"status": "test"},
                    "tolerance_reference": {"required_fields": ["kernel_absolute_tolerance"]},
                    "blocker_status": {"structural_status": "ready", "trusted_closure_status": "blocked_until_test"},
                    "candidate_identity_participation": False,
                    "adapter_boundary": {"generic_core_required_qe_fields": []},
                    "step1_source": {
                        "stages": [
                            {
                                "stage_id": "stage_00_scf",
                                "program": "pw.x",
                                "stage_type": "scf",
                                "command": ["pw.x", "-in", "fake_scf.in"],
                                "input": qe_input,
                                "input_path": "fixtures/qe/fake_scf.in",
                            }
                        ]
                    },
                    "baseline_sequence": [
                        {
                            "step_id": "stage_00_scf",
                            "program": "pw.x",
                            "command": ["pw.x", "-in", "fake_scf.in"],
                            "input": qe_input,
                            "input_path": "fixtures/qe/fake_scf.in",
                        }
                    ],
                }
            ],
        },
    )
    accelerated_numeric_evidence = tmp_path / "accelerated_numeric_evidence.json"
    _write_json(
        accelerated_numeric_evidence,
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "candidate_id": "cand_a",
            "workload_case_id": "qe_fake_scf_v1",
            "source_kind": "qe_offload_runtime",
            "accelerated_output_status": "passed",
            "trusted_accelerated_numeric_source": True,
            "baseline_reference": {"path": "baseline_comparison.json"},
            "accelerated_reference": {"path": "accelerated_qe_outputs.json"},
            "offload_provenance": {
                "producer": "qe-offload-test",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "gem5_generic_accel",
                "full_h_psi_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 1.0e-12,
                    "relative_error": 1.0e-10,
                }
            ],
            "physical_evidence": {
                "total_energy_error_ry": 1.0e-8,
                "density_residual": 1.0e-8,
                "eigenvalue_summary_error_ry": 1.0e-7,
            },
        },
    )

    out_dir = tmp_path / "matrix"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(out_dir),
            "--release-subset",
            str(release_subset),
            "--workload-suite",
            str(workload_suite),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
            "--qe-bin-dir",
            str(fake_bin),
            "--qe-pseudo-dir",
            str(pseudo_dir),
            "--accelerated-numeric-evidence",
            str(accelerated_numeric_evidence),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    baseline = json.loads((out_dir / "qe_baselines" / "qe_fake_scf_v1" / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert baseline["pure_software_qe_baseline"] is True
    assert baseline["steps"][0]["resolved_executable"] == str(fake_pw)
    assert baseline["steps"][0]["resolution_provenance"] == "qe_bin_dir"
    correctness = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "qe_correctness_for_l4_closure.json"
        ).read_text(encoding="utf-8")
    )
    accelerated = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "qe_accelerated_numeric_evidence.json"
        ).read_text(encoding="utf-8")
    )
    request = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "l4_gem5"
            / "simulation_request.json"
        ).read_text(encoding="utf-8")
    )
    assert accelerated["status"] == "passed"
    assert accelerated["trusted_accelerated_numeric_source"] is True
    assert request["extension_payload"]["qe_offload"]["kernel_id"] == "h_psi"
    assert request["extension_payload"]["qe_offload"]["target_kernel"] == "h_psi"
    assert request["extension_payload"]["qe_offload"]["required_kernel_scope"] == "full_h_psi"
    assert request["extension_payload"]["qe_offload"]["requires_full_kernel_recomputed"] is True
    assert request["extension_payload"]["qe_offload"]["requires_full_h_psi_recomputed"] is True
    assert request["extension_payload"]["qe_offload"]["full_kernel_recomputed"] is True
    assert request["extension_payload"]["qe_offload"]["full_h_psi_recomputed"] is True
    assert request["extension_payload"]["qe_offload"]["hpsi_specific_completion_allowed"] is False
    assert request["extension_payload"]["qe_offload"]["claim_boundary"].startswith("Transport metadata only")
    assert request["extension_payload"]["qe_accelerated_numeric_evidence"]["source_kind"] == "qe_offload_runtime"
    assert "qe_accelerated_numeric_evidence" not in request
    assert correctness["trusted_claim_eligible"] is True
    assert correctness["kernel_gate"]["status"] == "passed"
    assert correctness["scf_physical_gate"]["status"] == "passed"
    report = json.loads((out_dir / "complete_dse_full_l4_evidence_report.json").read_text(encoding="utf-8"))
    summary = report["evidence_summary"]
    stale_counter = "full_hpsi_" + "component_model_rows"
    stale_requirement_prefix = "component-model " + "full h_psi"
    assert stale_counter not in summary
    assert summary["full_hpsi_numeric_payload_rows"] == 1
    assert summary["full_hpsi_native_payload_rows"] == 1
    assert summary["full_hpsi_legacy_component_model_rows"] == 0
    assert not any(
        item["requirement"].startswith(stale_requirement_prefix)
        for item in report["prompt_to_artifact_checklist"]
    )


def test_full_l4_matrix_surfaces_blocked_component_numeric_gates_without_trusting_row(tmp_path):
    fake_bin = tmp_path / "qe" / "bin"
    fake_bin.mkdir(parents=True)
    fake_pw = fake_bin / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env python3\n"
        "print('!    total energy              =      -1.00000000 Ry')\n"
        "print('     highest occupied, lowest unoccupied level (ev):     1.000000  2.000000')\n"
        "print('     PWSCF        :      0.01s CPU      0.02s WALL')\n"
        "print('   JOB DONE.')\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)
    pseudo_dir = tmp_path / "pseudo"
    pseudo_dir.mkdir()
    (pseudo_dir / "Si.pz-vbc.UPF").write_text("fake pseudo for blocked-component test\n", encoding="utf-8")

    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(release_subset, {"legal_candidate_ids": ["cand_a"], "candidates": [{"candidate_id": "cand_a", "legal": True}]})
    workload_suite = tmp_path / "workload_suite.json"
    qe_input = "&CONTROL\n  calculation = 'scf'\n/\n&SYSTEM\n  ibrav = 0, nat = 0, ntyp = 0\n/\n&ELECTRONS\n/\n"
    _write_json(
        workload_suite,
        {
            "schema_version": "dse.qe_mainflow_workload_suite_manifest.v1",
            "status": "test",
            "suite_id": "test_blocked_component_numeric_gates",
            "candidate_identity_policy": {"workload_case_ids_participate": False},
            "cases": [
                {
                    "case_id": "qe_fake_scf_v1",
                    "stage_type": "scf",
                    "workflow_class": "scf",
                    "qe_command": ["pw.x", "-in", "fake_scf.in"],
                    "input_hashes": {"fixtures/qe/fake_scf.in": "0" * 64},
                    "expected_outputs": {"total_energy_ry": {"value": -1.0}},
                    "kernel_coverage": ["h_psi"],
                    "physical_quantities": ["total_energy_ry"],
                    "baseline_run_provenance": {"status": "test"},
                    "tolerance_reference": {"required_fields": ["kernel_absolute_tolerance"]},
                    "blocker_status": {"structural_status": "ready", "trusted_closure_status": "blocked_until_test"},
                    "candidate_identity_participation": False,
                    "adapter_boundary": {"generic_core_required_qe_fields": []},
                    "step1_source": {
                        "stages": [
                            {
                                "stage_id": "stage_00_scf",
                                "program": "pw.x",
                                "stage_type": "scf",
                                "command": ["pw.x", "-in", "fake_scf.in"],
                                "input": qe_input,
                                "input_path": "fixtures/qe/fake_scf.in",
                            }
                        ]
                    },
                    "baseline_sequence": [
                        {
                            "step_id": "stage_00_scf",
                            "program": "pw.x",
                            "command": ["pw.x", "-in", "fake_scf.in"],
                            "input": qe_input,
                            "input_path": "fixtures/qe/fake_scf.in",
                        }
                    ],
                }
            ],
        },
    )
    blocked_component_evidence = tmp_path / "blocked_component_evidence.json"
    _write_json(
        blocked_component_evidence,
        {
            "schema_version": "dse.qe_accelerated_numeric_evidence.v1",
            "candidate_id": "cand_a",
            "workload_case_id": "qe_fake_scf_v1",
            "source_kind": "gem5_generic_accel_qe_extension",
            "accelerated_output_status": "blocked",
            "trusted_accelerated_numeric_source": False,
            "offload_provenance": {
                "producer": "sidecar-component-test",
                "accelerated_runtime": "gem5_generic_accel_qe_extension",
                "offload_target": "generic_systemc_bridge",
                "full_h_psi_recomputed": False,
                "boundary_norm_probe_only": True,
            },
            "kernel_evidence": [
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "h_psi_boundary_norm_transport_probe",
                    "full_kernel_recomputed": False,
                    "boundary_norm_probe_only": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                },
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "boundary_norm_probe_only": False,
                    "absolute_error": 1.0e-14,
                    "relative_error": 1.0e-15,
                },
            ],
            "physical_evidence": {
                "total_energy_error_ry": 0.0,
                "density_residual": 0.0,
                "eigenvalue_summary_error_ry": 0.0,
            },
            "blockers": ["component_model_not_l4_offload"],
        },
    )

    out_dir = tmp_path / "matrix"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(out_dir),
            "--release-subset",
            str(release_subset),
            "--workload-suite",
            str(workload_suite),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
            "--qe-bin-dir",
            str(fake_bin),
            "--qe-pseudo-dir",
            str(pseudo_dir),
            "--accelerated-numeric-evidence",
            str(blocked_component_evidence),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    correctness = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "qe_correctness_for_l4_closure.json"
        ).read_text(encoding="utf-8")
    )
    accelerated = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "qe_accelerated_numeric_evidence.json"
        ).read_text(encoding="utf-8")
    )
    request = json.loads(
        (
            out_dir
            / "rows"
            / "cand_a"
            / "qe_fake_scf_v1"
            / "l4_gem5"
            / "simulation_request.json"
        ).read_text(encoding="utf-8")
    )

    assert accelerated["trusted_accelerated_numeric_source"] is False
    qe_offload = request["extension_payload"]["qe_offload"]
    assert qe_offload["requires_full_h_psi_recomputed"] is True
    assert qe_offload["full_h_psi_recomputed"] is False
    assert qe_offload["trusted_accelerated_numeric_source"] is False
    assert qe_offload["claim_boundary"].startswith("Transport metadata only")
    assert correctness["kernel_gate"]["status"] == "passed"
    assert correctness["scf_physical_gate"]["status"] == "passed"
    assert correctness["trusted_claim_eligible"] is False
    assert "offload_provenance_marks_boundary_norm_probe_only" in correctness["downgrade_blocks"]
    report = json.loads((out_dir / "complete_dse_full_l4_evidence_report.json").read_text(encoding="utf-8"))
    assert report["blocker_counts"]["trusted_correctness_source_not_eligible"] == 1
    assert report["matrix_blocker_counts"]["trusted_correctness_source_not_eligible"] == 1
    summary = report["evidence_summary"]
    stale_counter = "full_hpsi_" + "component_model_rows"
    stale_requirement_prefix = "component-model " + "full h_psi"
    assert stale_counter not in summary
    assert summary["full_hpsi_numeric_payload_rows"] == 1
    assert summary["full_hpsi_native_payload_rows"] == 0
    assert summary["full_hpsi_legacy_component_model_rows"] == 1
    assert "full_hpsi_legacy_component_model_rows remains blocked" in summary["claim_boundary"]
    assert not any(
        item["requirement"].startswith(stale_requirement_prefix)
        for item in report["prompt_to_artifact_checklist"]
    )


def test_qe_offload_extension_payload_supports_non_hpsi_selected_kernel() -> None:
    from dse_v2.scripts.dse.run_complete_dse_full_l4_matrix import _qe_offload_extension_payload

    payload = _qe_offload_extension_payload(
        {
            "candidate_id": "cand_spsi",
            "workload_case_id": "qe_case_spsi",
            "source_kind": "qe_offload_runtime",
            "accelerated_output_status": "passed",
            "trusted_accelerated_numeric_source": True,
            "offload_provenance": {
                "producer": "qe-offload-test",
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": "gem5_generic_accel",
                "target_kernel": "s_psi",
                "full_h_psi_recomputed": False,
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "l4_execution_proof": {
                    "passed": True,
                    "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                },
            },
            "kernel_evidence": [
                {
                    "kernel_id": "s_psi",
                    "kernel_scope": "full_s_psi",
                    "full_kernel_recomputed": True,
                    "absolute_error": 0.0,
                    "relative_error": 0.0,
                }
            ],
        }
    )

    assert payload["kernel_id"] == "s_psi"
    assert payload["target_kernel"] == "s_psi"
    assert payload["required_kernel_scope"] == "full_s_psi"
    assert payload["requires_full_kernel_recomputed"] is True
    assert payload["requires_full_h_psi_recomputed"] is False
    assert payload["full_kernel_recomputed"] is True
    assert payload["full_h_psi_recomputed"] is False
    assert payload["hpsi_specific_completion_allowed"] is False


def test_current_goal_strict_six_scf_suite_packages_descriptor_refs_and_stays_blocked(tmp_path):
    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(
        release_subset,
        {
            "schema_version": "test.current_goal.release_subset",
            "legal_candidate_ids": ["cand_000", "cand_001"],
            "candidates": [
                {"candidate_id": "cand_000", "legal": True},
                {"candidate_id": "cand_001", "legal": True},
            ],
        },
    )
    workload_suite = _write_current_goal_six_scf_suite(tmp_path, with_descriptors=True)
    out_dir = tmp_path / "matrix"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(out_dir),
            "--release-subset",
            str(release_subset),
            "--workload-suite",
            str(workload_suite),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    status = json.loads(completed.stdout)
    rows = json.loads((out_dir / "evidence_rows.json").read_text(encoding="utf-8"))
    matrix = json.loads((out_dir / "l4_evidence_matrix.json").read_text(encoding="utf-8"))
    coverage = json.loads((out_dir / "coverage_claim_report.json").read_text(encoding="utf-8"))
    validation = json.loads((out_dir / "qe_mainflow_workload_suite_validation.json").read_text(encoding="utf-8"))

    assert status["expected_row_count"] == 12
    assert rows["expected_row_count"] == 12
    assert rows["row_count"] == 12
    assert matrix["expected_row_count"] == 12
    assert matrix["row_count"] == 12
    assert coverage["all_rows_present"] is True
    assert coverage["claims"]["deliverable_complete"] is False
    assert validation["suite_kind"] == "dft_current_goal_six_scf"
    assert validation["case_count"] == 6
    assert all(row["deliverable_complete_eligible"] is False for row in matrix["rows"])
    assert all(row["accelerated_numeric_evidence"]["status"] == "blocked" for row in rows["rows"])
    first_case = rows["rows"][0]["workload_case_id"]
    packaged_case = json.loads(
        (out_dir / "rows" / "cand_000" / first_case / "workload_case.json").read_text(encoding="utf-8")
    )
    assert packaged_case["step1_source"]["stages"][0]["input"].startswith("&CONTROL")
    assert packaged_case["baseline_sequence"][0]["command"] == ["pw.x", "-in", Path(packaged_case["baseline_sequence"][0]["input_path"]).name]


def test_current_goal_strict_six_scf_suite_resolves_repo_relative_source_bundle(tmp_path, monkeypatch):
    from dse_v2.scripts.dse import run_complete_dse_full_l4_matrix as runner

    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    source_bundle = _write_current_goal_six_scf_suite(tmp_path / "runs" / "dse" / "six_scf_source", with_descriptors=True)
    source_payload = json.loads(source_bundle.read_text(encoding="utf-8"))
    bridge_dir = tmp_path / "bridge"
    bridge_manifest = bridge_dir / "workload_suite_manifest.json"
    bridge_payload = dict(source_payload)
    bridge_payload["source_artifacts"] = {
        "dft_scf_six_class_bundle_manifest": {
            "path": "runs/dse/six_scf_source/six_scf_bundle/workload_suite_manifest.json",
            "exists": True,
        }
    }
    _write_json(bridge_manifest, bridge_payload)

    adapted, validation = runner._adapt_workload_suite_for_runner(
        bridge_payload,
        workload_suite_path=bridge_manifest,
    )

    assert validation["valid"] is True
    assert all(not blockers for blockers in validation["case_blockers"].values())
    assert any(str(path).endswith("runs/dse/six_scf_source/six_scf_bundle") for path in validation["source_roots"])
    assert adapted["cases"][0]["step1_source"]["stages"][0]["input"].startswith("&CONTROL")


def test_current_goal_strict_six_scf_suite_missing_qe_input_fails_closed_per_row(tmp_path):
    release_subset = tmp_path / "release_subset_manifest.json"
    _write_json(
        release_subset,
        {
            "schema_version": "test.current_goal.release_subset",
            "legal_candidate_ids": ["cand_000"],
            "candidates": [{"candidate_id": "cand_000", "legal": True}],
        },
    )
    workload_suite = _write_current_goal_six_scf_suite(tmp_path, with_descriptors=False)
    out_dir = tmp_path / "matrix"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out",
            str(out_dir),
            "--release-subset",
            str(release_subset),
            "--workload-suite",
            str(workload_suite),
            "--simulator",
            str(tmp_path / "missing_generic_sim"),
            "--gem5-binary",
            str(tmp_path / "missing_gem5.opt"),
            "--gem5-config",
            str(tmp_path / "missing_generic_accel_l4_test.py"),
            "--gem5-driver",
            str(tmp_path / "missing_driver"),
            "--gem5-attempt-policy",
            "preflight_only",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    status = json.loads(completed.stdout)
    rows = json.loads((out_dir / "evidence_rows.json").read_text(encoding="utf-8"))
    matrix = json.loads((out_dir / "l4_evidence_matrix.json").read_text(encoding="utf-8"))

    assert status["expected_row_count"] == 6
    assert rows["expected_row_count"] == 6
    assert rows["row_count"] == 6
    assert matrix["expected_row_count"] == 6
    assert matrix["row_count"] == 6
    assert all(row["status"] == "blocked" for row in rows["rows"])
    assert all("current_goal_missing_embedded_descriptor_or_qe_input" in row["blockers"] for row in rows["rows"])
    assert all(any(blocker.startswith("current_goal_workload_packaging_failed") for blocker in row["blockers"]) for row in rows["rows"])
    assert all(row["deliverable_complete_eligible"] is False for row in matrix["rows"])
