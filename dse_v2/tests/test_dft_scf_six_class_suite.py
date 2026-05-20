#!/usr/bin/env python3
"""Strict six-SCF descriptor-plus-runnable bundle tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_scf_six_class_suite import (
    DFT_SCF_SIX_CLASS_MANIFEST_NAME,
    DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME,
    DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME,
    DFT_SCF_SIX_CLASS_SUITE_SCHEMA,
    REQUIRED_DFT_SCF_CLASS_IDS,
    build_dft_scf_six_class_bundle_manifest,
    discover_local_qe_pseudopotentials,
    qe_input_text,
    required_scf_class_specs,
    validate_dft_scf_six_class_bundle_manifest,
    write_dft_scf_six_class_bundle,
)


REQUIRED_TEST_ELEMENTS = ("Si", "Al", "C", "Ti", "O")
OPTIONAL_PREFERRED_TEST_ELEMENTS = ("W", "Se")


def _write_local_test_pseudos(pseudo_dir: Path) -> dict[str, str]:
    pseudo_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for element in (*REQUIRED_TEST_ELEMENTS, *OPTIONAL_PREFERRED_TEST_ELEMENTS):
        name = f"{element}.local-test.UPF"
        (pseudo_dir / name).write_text(
            f"<UPF version=\"2.0.1\"><PP_INFO>local test pseudo for {element}</PP_INFO></UPF>\n",
            encoding="utf-8",
        )
        files[element] = name
    return files


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_fake_converged_pw(path: Path) -> Path:
    return _write_fake_converged_pw_with_label(path, "local pw.x smoke output")


def _write_fake_converged_pw_with_label(path: Path, label: str) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "input=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -in) input=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        f"printf '{label} for %s\\n' \"$input\"\n"
        "printf '     convergence has been achieved in   1 iterations\\n'\n"
        "printf '   JOB DONE.\\n'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_admitted_reference_bundle(tmp_path: Path) -> Path:
    _write_local_test_pseudos(tmp_path / "local_pseudos")
    bundle_dir = tmp_path / "bundle"
    status = write_dft_scf_six_class_bundle(
        bundle_dir,
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
        run_local_qe=True,
        local_pw_x=_write_fake_converged_pw(tmp_path / "pw.x"),
        qe_run_timeout_seconds=5,
    )
    assert status["status"] == "passed"
    return bundle_dir


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_required_six_scf_class_ids_are_canonical_and_exact():
    assert REQUIRED_DFT_SCF_CLASS_IDS == (
        "small_multi_k_scf",
        "metal_smearing_scf",
        "insulator_scf",
        "slab_vacuum_large_fft_scf",
        "gamma_only_supercell_scf",
        "projector_orthogonalization_heavy_scf",
    )
    assert tuple(spec.class_id for spec in required_scf_class_specs()) == REQUIRED_DFT_SCF_CLASS_IDS


def test_qe_inputs_for_ibrav_zero_use_cell_parameters_without_celldm_and_plausible_masses():
    saw_ibrav_zero = False
    for spec in required_scf_class_specs():
        deck = qe_input_text(spec)
        if spec.ibrav == 0:
            saw_ibrav_zero = True
            assert "  celldm(1)" not in deck
            assert "CELL_PARAMETERS angstrom" in deck
        species_lines = deck.split("ATOMIC_SPECIES\n", 1)[1].split("\nATOMIC_POSITIONS", 1)[0].splitlines()
        for line in species_lines:
            fields = line.split()
            assert len(fields) == 3
            assert float(fields[1]) > 10.0
            assert fields[1] != "1.0"
    assert saw_ibrav_zero is True


def test_preferred_local_qe_pseudos_are_selected_when_present(tmp_path):
    preferred_names = {
        "Si": "Si.pz-vbc.UPF",
        "Al": "Al.pz-vbc.UPF",
        "C": "C.pz-rrkjus.UPF",
        "Ti": "Ti.pz-sp-van_ak.UPF",
        "O": "O.pz-rrkjus.UPF",
        "W": "W_pbe_v1.2.uspp.F.UPF",
        "Se": "Se_pbe_v1.uspp.F.UPF",
    }
    pseudo_dir = tmp_path / "local_pseudos"
    pseudo_dir.mkdir()
    for element, preferred_name in preferred_names.items():
        (pseudo_dir / f"{element}.aaa-fallback.UPF").write_text(
            f"<UPF version=\"2.0.1\"><PP_INFO>fallback pseudo for {element}</PP_INFO></UPF>\n",
            encoding="utf-8",
        )
        (pseudo_dir / preferred_name).write_text(
            f"<UPF version=\"2.0.1\"><PP_INFO>preferred pseudo for {element}</PP_INFO></UPF>\n",
            encoding="utf-8",
        )

    discovery = discover_local_qe_pseudopotentials(pseudo_dir, required_elements=tuple(preferred_names))

    assert discovery["complete"] is True
    assert {
        element: pseudo["file_name"]
        for element, pseudo in discovery["pseudopotentials"].items()
    } == preferred_names

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=pseudo_dir,
    )

    assert status["status"] == "blocked_missing_real_reference_output_hashes"
    assert status["final_real_qe_evidence"] is False
    manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    used_names = {pseudo["file_name"] for case in manifest["cases"] for pseudo in case["pseudo_refs"]}
    active_preferred_names = {preferred_names[element] for element in REQUIRED_TEST_ELEMENTS}
    assert used_names == active_preferred_names
    for preferred_name in active_preferred_names:
        assert preferred_name in "\n".join(case["qe_input"]["text"] for case in manifest["cases"])
    assert manifest["final_real_qe_evidence"] is False


def test_builder_materializes_descriptor_plus_runnable_fields_and_fails_closed_without_real_reference_hashes(tmp_path):
    status = write_dft_scf_six_class_bundle(tmp_path)

    assert status["status"] == "blocked_missing_real_reference_output_hashes"
    assert status["admitted"] is False
    assert status["case_count"] == 6
    assert status["blocker_count"] == 6
    assert status["blocker_ids"] == ["missing_real_reference_output_hash"]
    assert status["final_real_qe_evidence"] is False
    assert status["hardware_completion_eligible"] is False
    assert status["deliverable_complete"] is False

    manifest_path = tmp_path / DFT_SCF_SIX_CLASS_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == DFT_SCF_SIX_CLASS_SUITE_SCHEMA
    assert manifest["descriptor_plus_runnable_bundle"] is True
    assert manifest["workload_analysis_model"]["profile_schema_version"] == "dse.dft.workload_profile.layered.v1"
    assert manifest["workload_analysis_model"]["reference_suite_role"] == "reference_suite_v1_regression_search_calibration_seed"
    assert "not architecture candidate identity" in manifest["workload_analysis_model"]["claim_boundary"]
    assert (tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME).is_file()
    assert (tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME).is_file()
    assert manifest["reference_output_hash_manifest"]["path"] == DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME
    assert manifest["reference_admission_ledger"]["path"] == DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME
    hash_manifest = json.loads((tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME).read_text(encoding="utf-8"))
    admission_ledger = json.loads((tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME).read_text(encoding="utf-8"))
    assert hash_manifest["complete"] is False
    assert all(entry["sha256"] is None for entry in hash_manifest["entries"])
    assert admission_ledger["final_admission_complete"] is False
    assert admission_ledger["entry_count"] == 6
    assert admission_ledger["admitted_class_ids"] == []
    assert all(entry["admitted"] is False for entry in admission_ledger["entries"])
    assert all(entry["fail_closed"] is True for entry in admission_ledger["entries"])
    assert manifest["required_class_ids"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert [case["class_id"] for case in manifest["cases"]] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    manifest_audit = manifest["coverage_derivation_audit"]
    assert manifest_audit["all_required_gates_have_non_tag_derivation"] is True
    assert manifest_audit["stress_tags_used_for_gate_authority"] is False
    assert manifest_audit["audited_case_count"] == 6
    assert manifest_audit["case_ids"] == sorted(REQUIRED_DFT_SCF_CLASS_IDS)

    for case in manifest["cases"]:
        assert case["qe_input"]["text"].startswith("&CONTROL")
        assert case["qe_input"]["generated"] is True
        assert (tmp_path / case["qe_input"]["path"]).is_file()
        assert case["qe_input"]["sha256"]
        assert case["pseudo_refs"]
        assert case["pseudo_refs"][0]["sha256"]
        assert case["pseudo_refs"][0]["source"] == "generated_synthetic_placeholder"
        assert case["pseudo_refs"][0]["physical_validity"] == "not_a_real_qe_pseudopotential"
        assert case["run_command"] == ["bash", f"run_scripts/run_{case['class_id']}.sh"]
        assert (tmp_path / case["run_command"][1]).is_file()
        assert case["reference_output"]["sha256"] is None
        assert case["reference_output"]["hash_final"] is False
        assert case["reference_output"]["status"] == "missing_real_qe_reference_output_hash_fail_closed"
        assert case["workload_profile"]["schema_version"] == "dse.dft.workload_profile.layered.v1"
        assert case["workload_profile"]["profile_hash"]
        profile_path = tmp_path / case["workload_profile"]["path"]
        assert profile_path.is_file()
        assert case["workload_profile"]["sha256"] == hashlib.sha256(profile_path.read_bytes()).hexdigest()
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile["schema_version"] == "dse.dft.workload_profile.layered.v1"
        assert profile["layer_order"] == [
            "source_bundle",
            "raw_input_facts",
            "resolved_run_facts",
            "derived_scale_features",
            "coverage_vector",
            "kernel_workload_graph",
            "reference_suite_case",
        ]
        assert case["dft_workload_analysis"]["layer_order"] == profile["layer_order"]
        assert case["dft_workload_analysis"]["raw_input_facts"]["structure"]["nat"] >= 1
        assert case["dft_workload_analysis"]["raw_input_facts"]["structure"]["ntyp"] >= 1
        assert case["dft_workload_analysis"]["raw_input_facts"]["system"]["ecutwfc"]["source"] == "qe_input"
        assert case["dft_workload_analysis"]["raw_input_facts"]["kpoints"]["mode"] == "automatic"
        assert case["dft_workload_analysis"]["coverage_vector"]["required_kernel_gates"]
        assert "hpsi_local_potential" in case["dft_workload_analysis"]["coverage_vector"]["required_kernel_gates"]
        coverage = case["dft_workload_analysis"]["coverage_vector"]
        assert coverage["stress_tag_gate_policy"] == "display_only_not_authoritative"
        assert coverage["suite_intent_tags"] == sorted(case["stress_tags"])
        assert set(coverage["gate_derivation_reasons"]) == set(coverage["required_kernel_gates"])
        coverage_audit = case["coverage_derivation_audit"]
        assert coverage_audit == case["dft_workload_analysis"]["coverage_derivation_audit"]
        assert coverage_audit == coverage["coverage_derivation_audit"]
        assert coverage_audit == profile["coverage_derivation_audit"]
        assert coverage_audit["all_required_gates_have_non_tag_derivation"] is True
        assert coverage_audit["stress_tags_used_for_gate_authority"] is False
        assert case["dft_workload_analysis"]["kernel_workload_graph"]["nodes"]
        gate_contracts = case["dft_workload_analysis"]["kernel_workload_graph"]["kernel_gate_contracts"]
        assert gate_contracts
        assert {
            contract["gate_id"] for contract in gate_contracts
        } == set(case["dft_workload_analysis"]["coverage_vector"]["required_kernel_gates"])
        for contract in gate_contracts:
            assert contract["schema_version"] == "dse.dft.kernel_gate_contract.v1"
            assert contract["triggered_by"]["required_kernel_gate"] is True
            assert contract["candidate_requirements"]["precision_policy"] == "fp64_strict_required_for_release_claim"
            assert contract["evidence_required"]["golden_correctness"] == "required_for_any_accelerated_claim"
            assert contract["evidence_required"]["vivado_fpga_synth_or_impl"] == "required_for_fpga_claim"
            assert contract["evidence_required"]["dc_asic_synth_timing_area"] == "required_for_asic_claim"
            assert "no_cross_kernel_evidence_reuse" in contract["pass_fail"]
        assert case["dft_workload_analysis"]["reference_summary"]["normalized_reference_summary_hash"]
        assert case["dft_workload_analysis"]["reference_summary"]["raw_output_sha256"] is None
        assert case["provenance"]
        assert case["license"]
        assert case["parser_version"]
        assert case["parser_tool_version"]
        assert case["proof_class"] == "synthetic_descriptor_runnable_fixture_not_final_qe_evidence"
        assert case["final_real_qe_evidence"] is False

    validation = validate_dft_scf_six_class_bundle_manifest(manifest_path)
    assert validation["status"] == "blocked_missing_real_reference_output_hashes"
    assert validation["blocker_count"] == 6
    assert validation["blocker_ids"] == ["missing_real_reference_output_hash"]


def test_manifest_validation_rejects_stress_tag_only_gate_derivation_reason(tmp_path):
    manifest = build_dft_scf_six_class_bundle_manifest(out_dir=tmp_path)
    case = manifest["cases"][0]
    coverage = case["dft_workload_analysis"]["coverage_vector"]
    gate_id = coverage["required_kernel_gates"][0]
    coverage["gate_derivation_reasons"][gate_id] = [
        {
            "source": "stress_tags",
            "fact": "stress_tags.large_fft",
            "value": "large_fft",
            "rule": "invalid hand-edited tag-only authority",
        }
    ]

    validation = validate_dft_scf_six_class_bundle_manifest(manifest, base_dir=tmp_path)

    assert validation["status"] == "blocked"
    assert "stress_tag_only_gate_derivation_reason" in validation["blocker_ids"]
    assert "coverage_derivation_audit_mismatch" in validation["blocker_ids"]


def test_manifest_validation_rejects_tampered_coverage_derivation_audit_booleans(tmp_path):
    manifest = build_dft_scf_six_class_bundle_manifest(out_dir=tmp_path)
    manifest["coverage_derivation_audit"] = dict(manifest["coverage_derivation_audit"])
    manifest["coverage_derivation_audit"]["all_required_gates_have_non_tag_derivation"] = False
    manifest["cases"][0]["coverage_derivation_audit"] = dict(manifest["cases"][0]["coverage_derivation_audit"])
    manifest["cases"][0]["coverage_derivation_audit"]["stress_tags_used_for_gate_authority"] = True

    validation = validate_dft_scf_six_class_bundle_manifest(manifest, base_dir=tmp_path)

    mismatch_blockers = [
        blocker
        for blocker in validation["blockers"]
        if blocker["id"] == "coverage_derivation_audit_mismatch"
    ]
    assert validation["status"] == "blocked"
    assert {blocker["field"] for blocker in mismatch_blockers} >= {
        "coverage_derivation_audit",
        "cases[0].coverage_derivation_audit",
    }


def test_manifest_validation_rejects_missing_required_class_and_extra_class(tmp_path):
    manifest = build_dft_scf_six_class_bundle_manifest(out_dir=tmp_path)
    manifest["cases"] = [case for case in manifest["cases"] if case["class_id"] != "insulator_scf"]
    extra_case = dict(manifest["cases"][0])
    extra_case["class_id"] = "not_a_required_scf_class"
    extra_case["workload_class"] = "not_a_required_scf_class"
    manifest["cases"].append(extra_case)

    validation = validate_dft_scf_six_class_bundle_manifest(manifest, base_dir=tmp_path)

    assert validation["status"] == "blocked"
    assert "missing_required_class_ids" in validation["blocker_ids"]
    assert "unexpected_class_id" in validation["blocker_ids"]
    assert validation["missing_class_ids"] == ["insulator_scf"]


def test_caller_supplied_reference_hashes_are_provenance_not_final_qe_admission(tmp_path):
    reference_hashes = {
        class_id: {"path": f"reference_outputs/{class_id}.out", "sha256": _sha256_text(f"real output for {class_id}\n")}
        for class_id in REQUIRED_DFT_SCF_CLASS_IDS
    }

    status = write_dft_scf_six_class_bundle(tmp_path, reference_output_hashes=reference_hashes)

    assert status["status"] == "blocked"
    assert status["admitted"] is False
    assert status["final_real_qe_evidence"] is False
    assert "reference_output_hash_not_final" in status["blocker_ids"]
    assert "reference_output_path_not_local_bundle_file" in status["blocker_ids"]
    assert "reference_output_not_local_converged_qe_source" in status["blocker_ids"]
    manifest = json.loads((tmp_path / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    hash_manifest = json.loads((tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "blocked"
    assert manifest["validation"]["final_real_qe_evidence"] is False
    assert hash_manifest["complete"] is True
    assert hash_manifest["final_admission_complete"] is False
    assert [entry["sha256"] for entry in hash_manifest["entries"]] == [
        reference_hashes[class_id]["sha256"] for class_id in REQUIRED_DFT_SCF_CLASS_IDS
    ]
    assert all(entry["hash_final"] is False for entry in hash_manifest["entries"])
    assert all(entry["provenance_hash_only"] is True for entry in hash_manifest["entries"])
    assert all(case["reference_output"]["hash_final"] is False for case in manifest["cases"])
    assert all(case["reference_output"]["sha256"] for case in manifest["cases"])
    assert all(case["reference_output"]["provenance_hash_only"] is True for case in manifest["cases"])
    assert all(case["final_real_qe_evidence"] is False for case in manifest["cases"])
    assert all(case["proof_class"] == "descriptor_runnable_fixture_with_caller_reference_hash_provenance_not_final_qe_evidence" for case in manifest["cases"])
    assert manifest["deliverable_complete"] is False
    assert manifest["final_real_qe_evidence"] is False
    assert "not final real QE numerical evidence" in manifest["claim_boundary"]


def test_local_pseudo_discovery_and_bundle_use_real_local_refs_without_hash_admission(tmp_path):
    pseudo_names = _write_local_test_pseudos(tmp_path / "local_pseudos")

    discovery = discover_local_qe_pseudopotentials(tmp_path / "local_pseudos")
    assert discovery["complete"] is True
    assert discovery["found_elements"] == sorted(REQUIRED_TEST_ELEMENTS)

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
    )

    assert status["status"] == "blocked_missing_real_reference_output_hashes"
    assert status["local_qe_pseudo_discovery_complete"] is True
    manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["local_qe_asset_discovery"]["complete"] is True
    assert manifest["local_qe_reference_run"]["attempted"] is False
    for case in manifest["cases"]:
        assert all(pseudo["source"] == "local_qe_pseudopotential" for pseudo in case["pseudo_refs"])
        assert all(pseudo["physical_validity"] == "local_qe_pseudopotential_unverified_by_builder" for pseudo in case["pseudo_refs"])
        assert case["reference_output"]["sha256"] is None
        for pseudo in case["pseudo_refs"]:
            assert (tmp_path / "bundle" / pseudo["path"]).read_text(encoding="utf-8").startswith("<UPF")
    slab = next(case for case in manifest["cases"] if case["class_id"] == "slab_vacuum_large_fft_scf")
    assert {pseudo["file_name"] for pseudo in slab["pseudo_refs"]} == {pseudo_names["Ti"], pseudo_names["O"]}
    assert pseudo_names["Ti"] in slab["qe_input"]["text"]
    assert pseudo_names["O"] in slab["qe_input"]["text"]


def test_local_qe_runner_hash_manifest_records_actual_output_hashes_without_long_qe(tmp_path):
    _write_local_test_pseudos(tmp_path / "local_pseudos")
    fake_pw = tmp_path / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "input=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -in) input=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "printf 'local pw.x smoke output for %s\\n' \"$input\"\n"
        "printf '     convergence has been achieved in   1 iterations\\n'\n"
        "printf '   JOB DONE.\\n'\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
        run_local_qe=True,
        local_pw_x=fake_pw,
        qe_run_timeout_seconds=5,
    )

    assert status["status"] == "passed"
    assert status["local_qe_reference_run_complete"] is True
    assert status["final_real_qe_evidence"] is True
    manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    hash_manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME).read_text(encoding="utf-8"))
    admission_ledger = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME).read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "passed"
    assert manifest["validation"]["final_real_qe_evidence"] is True
    assert manifest["final_real_qe_evidence"] is True
    assert manifest["local_qe_reference_run"]["attempted"] is True
    assert hash_manifest["complete"] is True
    assert hash_manifest["final_admission_complete"] is True
    assert admission_ledger["final_admission_complete"] is True
    assert admission_ledger["admitted_class_ids"] == list(REQUIRED_DFT_SCF_CLASS_IDS)
    assert all(entry["admitted"] is True for entry in admission_ledger["entries"])
    assert all(entry["fail_closed"] is False for entry in admission_ledger["entries"])
    for entry in hash_manifest["entries"]:
        output_path = tmp_path / "bundle" / entry["path"]
        assert output_path.is_file()
        assert entry["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    for case in manifest["cases"]:
        assert case["reference_output"]["status"] == "local_pw_x_reference_output_hash_from_converged_scf_run"
        assert case["reference_output"]["job_done"] is True
        assert case["reference_output"]["scf_converged"] is True
        assert case["reference_output"]["sha256"] == hashlib.sha256(
            (tmp_path / "bundle" / case["reference_output"]["path"]).read_bytes()
        ).hexdigest()
        assert case["dft_workload_analysis"]["resolved_run_facts"]["job_done"] is True
        assert case["dft_workload_analysis"]["resolved_run_facts"]["scf_converged"] is True
        assert case["dft_workload_analysis"]["reference_summary"]["convergence_verified"] is True
        assert case["dft_workload_analysis"]["reference_summary"]["raw_output_sha256"] == case["reference_output"]["sha256"]
        assert case["dft_workload_analysis"]["reference_summary"]["normalized_reference_summary_hash"]
        assert case["proof_class"] == "descriptor_runnable_fixture_with_local_converged_qe_reference_output"
        assert case["final_real_qe_evidence"] is True


def test_missing_reference_admission_ledger_fails_closed_after_otherwise_admitted_bundle(tmp_path):
    bundle_dir = _write_admitted_reference_bundle(tmp_path)
    (bundle_dir / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME).unlink()

    validation = validate_dft_scf_six_class_bundle_manifest(bundle_dir / DFT_SCF_SIX_CLASS_MANIFEST_NAME)

    assert validation["status"] == "blocked"
    assert validation["admitted"] is False
    assert validation["final_real_qe_evidence"] is False
    assert "missing_reference_admission_ledger" in validation["blocker_ids"]


def test_tampered_reference_admission_ledger_hash_fails_closed(tmp_path):
    bundle_dir = _write_admitted_reference_bundle(tmp_path)
    ledger_path = bundle_dir / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["claim_boundary"] = "tampered ledger text"
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")

    validation = validate_dft_scf_six_class_bundle_manifest(bundle_dir / DFT_SCF_SIX_CLASS_MANIFEST_NAME)

    assert validation["status"] == "blocked"
    assert validation["admitted"] is False
    assert "reference_admission_ledger_hash_mismatch" in validation["blocker_ids"]


def test_stale_reference_admission_ledger_entry_fails_closed_even_when_ledger_hash_ref_is_current(tmp_path):
    bundle_dir = _write_admitted_reference_bundle(tmp_path)
    manifest = json.loads((bundle_dir / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    ledger_path = bundle_dir / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    stale_entry = ledger["entries"][0]
    stale_entry["reference_output_sha256"] = "0" * 64
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    manifest["reference_admission_ledger"]["sha256"] = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

    validation = validate_dft_scf_six_class_bundle_manifest(manifest, base_dir=bundle_dir)

    assert validation["status"] == "blocked"
    assert validation["admitted"] is False
    assert "reference_admission_ledger_entry_mismatch" in validation["blocker_ids"]
    mismatch = next(
        blocker
        for blocker in validation["blockers"]
        if blocker["id"] == "reference_admission_ledger_entry_mismatch"
    )
    assert mismatch["class_id"] == stale_entry["class_id"]
    assert "reference_output_sha256" in mismatch["mismatches"]


def test_local_qe_runner_can_reuse_existing_converged_outputs_without_rerun(tmp_path):
    _write_local_test_pseudos(tmp_path / "local_pseudos")
    first_pw = tmp_path / "first-pw.x"
    first_pw.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "input=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -in) input=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "printf 'converged output for %s\\n' \"$input\"\n"
        "printf '     convergence has been achieved in   1 iterations\\n'\n"
        "printf '   JOB DONE.\\n'\n",
        encoding="utf-8",
    )
    first_pw.chmod(0o755)

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
        run_local_qe=True,
        local_pw_x=first_pw,
        qe_run_timeout_seconds=5,
    )
    assert status["status"] == "passed"

    second_pw = tmp_path / "second-pw.x"
    second_pw.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'this pw.x should not be called when reuse is safe' >&2\n"
        "exit 77\n",
        encoding="utf-8",
    )
    second_pw.chmod(0o755)

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
        run_local_qe=True,
        local_pw_x=second_pw,
        qe_run_timeout_seconds=5,
        reuse_existing_qe_outputs=True,
    )

    assert status["status"] == "passed"
    assert status["final_real_qe_evidence"] is True
    manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["local_qe_reference_run"]["reuse_existing_outputs"] is True
    assert manifest["final_real_qe_evidence"] is True
    for case in manifest["cases"]:
        assert case["reference_output"]["status"] == (
            "local_pw_x_reference_output_hash_from_existing_converged_scf_output"
        )
        assert case["reference_output"]["reused_existing_output"] is True
        assert case["final_real_qe_evidence"] is True


def test_local_qe_runner_rejects_zero_returncode_without_scf_convergence(tmp_path):
    _write_local_test_pseudos(tmp_path / "local_pseudos")
    fake_pw = tmp_path / "pw.x"
    fake_pw.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'local pw.x non-converged output\\n'\n"
        "printf '   JOB DONE.\\n'\n",
        encoding="utf-8",
    )
    fake_pw.chmod(0o755)

    status = write_dft_scf_six_class_bundle(
        tmp_path / "bundle",
        use_local_pseudos=True,
        local_pseudo_dir=tmp_path / "local_pseudos",
        run_local_qe=True,
        local_pw_x=fake_pw,
        qe_run_timeout_seconds=5,
    )

    assert status["status"] == "blocked_missing_real_reference_output_hashes"
    assert status["local_qe_reference_run_complete"] is False
    manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    hash_manifest = json.loads((tmp_path / "bundle" / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert hash_manifest["complete"] is False
    for entry in hash_manifest["entries"]:
        assert entry["sha256"] is None
        assert entry["status"] == "local_pw_x_run_completed_without_verified_scf_convergence_fail_closed"
    for case in manifest["cases"]:
        assert case["reference_output"]["sha256"] is None
        assert case["reference_output"]["hash_final"] is False
        assert case["reference_output"]["job_done"] is True
        assert case["reference_output"]["scf_converged"] is False
        assert "qe_scf_convergence_marker_missing" in case["reference_output"]["missing_markers"]


def test_six_class_bundle_cli_writes_fail_closed_artifacts_by_default(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_scf_six_class_bundle.py",
            "--out",
            str(tmp_path),
            "--campaign-id",
            "campaign-six-scf",
            "--workload-run-id",
            "workload-six-scf",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    status = json.loads(completed.stdout)
    assert status["status"] == "blocked_missing_real_reference_output_hashes"
    assert status["blocker_count"] == 6
    assert status["reference_admission_ledger"] == DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME
    assert (tmp_path / DFT_SCF_SIX_CLASS_MANIFEST_NAME).exists()
    assert (tmp_path / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME).exists()
    manifest = json.loads((tmp_path / DFT_SCF_SIX_CLASS_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert len(manifest["cases"]) == 6
