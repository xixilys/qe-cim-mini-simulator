#!/usr/bin/env python3
"""DFT-first Step1 frontdoor regressions."""

from __future__ import annotations

import json

from dse_v2.core.workload import (
    default_importer_registry,
    default_profile_registry,
    run_step1_workload_ingestion_workflow,
    verify_step1_artifact_validation,
)
from dse_v2.reference_workloads.dft import (
    SourceFact,
    canonicalize_phase_id,
    merge_source_facts,
    stable_unknown_phase_id,
)
from dse_v2.reference_workloads.dft_importer_coverage import (
    dft_importer_fixture_coverage_matrix,
)
from dse_v2.reference_workloads.dft_profile_schema import (
    DFT_CONFIG_PROFILE_SCHEMA,
    DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA,
    DFT_DOMAIN_VALIDATION_SCHEMA,
    dft_config_profile_schema,
    profile_contract_from_package,
    validate_dft_profile_contract,
)
from dse_v2.reference_workloads.dft_qe import (
    dft_qe_pw_profile,
    parse_qe_profile,
    parse_qe_pw_input,
    parse_qe_pw_log,
    register_dft_qe_importer,
)
from dse_v2.reference_workloads.dft_vasp import (
    dft_vasp_profile,
    parse_vasp_incar,
    parse_vasp_kpoints,
    parse_vasp_outcar,
    parse_vasp_poscar,
    parse_vasp_profile,
    register_dft_vasp_importer,
)


QE_INPUT = """
&CONTROL
  calculation = 'scf'
/
&SYSTEM
  ibrav = 2, nat = 2, ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 8,
/
&ELECTRONS
  conv_thr = 1.0d-8,
  mixing_beta = 0.7,
  diagonalization = 'david'
/
K_POINTS automatic
  2 2 1 0 0 0
"""

QE_LOG = """
     number of k points=     2
     number of Kohn-Sham states= 8
     number of plane waves= 321
     FFT dimensions: ( 16, 16, 16)
     iteration # 1
     h_psi        :      0.10s CPU      1.20s WALL
     c_bands      :      0.05s CPU      0.20s WALL
     FFT          :      0.02s CPU      0.10s WALL
"""

QE_NSCF_INPUT = """
&CONTROL
  calculation = 'nscf'
/
&SYSTEM
  ibrav = 2, nat = 2, ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 16,
/
K_POINTS automatic
  2 2 1 0 0 0
"""

VASP_INCAR = """
ENCUT = 520
NBANDS = 64
ISPIN = 2
EDIFF = 1E-6
ALGO = Fast
"""

VASP_KPOINTS = """
Automatic mesh
0
Gamma
2 2 1
0 0 0
"""

VASP_POSCAR = """
Si
1.0
0.0 2.7 2.7
2.7 0.0 2.7
2.7 2.7 0.0
Si
2
Direct
0.0 0.0 0.0
0.25 0.25 0.25
"""

VASP_OUTCAR = """
 NKPTS = 4   k-points in BZ     NBANDS= 64
 NIONS = 2 ions
 number of plane waves: 2048
 dimension x,y,z NGX = 16 NGY = 16 NGZ = 16
 Iteration 1
 DAV: 1.10
 FFT: 0.25
 CHARGE: 0.40
 MIXING: 0.10
"""


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


def test_qe_input_log_and_profile_parsers_emit_source_facts_with_provenance():
    input_facts = parse_qe_pw_input(QE_INPUT, source_path="qe.in")
    log_facts = parse_qe_pw_log(QE_LOG, source_path="qe.out")
    profile_facts = parse_qe_profile({"phases": {"h_psi": 2.0, "fft": 0.25}}, source_path="profile.json")

    by_field = {fact.field: fact for fact in input_facts + log_facts + profile_facts}
    assert by_field["parameter.ecutwfc"].value == 30.0
    assert by_field["dimension.kpoint_grid"].value == [2, 2, 1]
    assert by_field["dimension.npw"].value == 321
    assert by_field["dimension.nfft"].value == 4096
    assert by_field["phase_timing.h_psi.wall_seconds"].source_type == "profile"
    assert all(fact.fact_id.startswith("fact:") for fact in input_facts + log_facts + profile_facts)
    assert by_field["parameter.ecutwfc"].source_path == "qe.in"
    assert by_field["dimension.npw"].source_path == "qe.out"


def test_qe_log_parser_accepts_standard_parallel_version_mpi_line():
    log_facts = parse_qe_pw_log(
        """
     Program PWSCF v.7.5 starts on  1Jun2026
     Parallel version (MPI), running on     4 processors
""",
        source_path="qe75.out",
    )

    by_field = {fact.field: fact for fact in log_facts}
    assert by_field["runtime.qe_version"].value == "7.5"
    assert by_field["runtime.mpi_processes"].value == 4
    assert by_field["runtime.mpi_processes"].raw_excerpt == "Parallel version (MPI), running on     4 processors"


def test_vasp_input_log_and_profile_parsers_emit_source_facts_with_provenance():
    incar_facts = parse_vasp_incar(VASP_INCAR, source_path="INCAR")
    kpoint_facts = parse_vasp_kpoints(VASP_KPOINTS, source_path="KPOINTS")
    poscar_facts = parse_vasp_poscar(VASP_POSCAR, source_path="POSCAR")
    outcar_facts = parse_vasp_outcar(VASP_OUTCAR, source_path="OUTCAR")
    profile_facts = parse_vasp_profile({"phases": {"DAV": 2.0, "FFT": 0.25}}, source_path="vasp_profile.json")

    by_field = {fact.field: fact for fact in incar_facts + kpoint_facts + poscar_facts + outcar_facts + profile_facts}
    assert by_field["parameter.ecutwfc"].value == 520
    assert by_field["parameter.ecutwfc"].unit == "eV"
    assert by_field["dimension.kpoint_grid"].value == [2, 2, 1]
    assert by_field["dimension.nat"].value == 2
    assert by_field["dimension.npw"].value == 2048
    assert by_field["dimension.nfft"].value == 4096
    assert by_field["phase_timing.diagonalization.wall_seconds"].source_type == "profile"
    assert by_field["phase_timing.fft.wall_seconds"].source_type == "profile"
    assert all(fact.fact_id.startswith("fact:") for fact in incar_facts + kpoint_facts + poscar_facts + outcar_facts + profile_facts)
    assert by_field["parameter.ecutwfc"].source_path == "INCAR"
    assert by_field["dimension.npw"].source_path == "OUTCAR"


def test_qe_vasp_importer_fixture_coverage_matrix_is_explicit_and_bounded():
    matrix = dft_importer_fixture_coverage_matrix()

    assert matrix["status"] == "passed"
    assert matrix["required_importer_ids"] == ["dft_qe_pw", "dft_vasp"]
    assert matrix["covered_importer_ids"] == ["dft_qe_pw", "dft_vasp"]
    assert matrix["all_required_importers_present"] is True
    rows = {row["importer_id"]: row for row in matrix["rows"]}
    assert rows["dft_qe_pw"]["fixture_inputs"] == ["input", "log", "profile", "workflow_bundle"]
    assert rows["dft_vasp"]["fixture_inputs"] == ["incar", "kpoints", "poscar", "outcar", "profile"]
    assert "QE numerical correctness is not claimed" in rows["dft_qe_pw"]["claim_boundary"]
    assert "VASP numerical correctness is not claimed" in rows["dft_vasp"]["claim_boundary"]
    assert "not release-complete evidence" in matrix["claim_boundary"]


def test_dft_profile_config_and_domain_validation_contracts_are_profile_owned():
    profile = dft_qe_pw_profile()
    payload = profile.to_dict()
    validation = validate_dft_profile_contract(payload)
    schema = dft_config_profile_schema()

    assert validation["valid"] is True
    assert schema["schema_version"] == DFT_CONFIG_PROFILE_SCHEMA
    assert schema["owner"] == "dse_v2.reference_workloads"
    assert payload["domain_validation"]["schema_version"] == DFT_DOMAIN_VALIDATION_SCHEMA
    assert payload["domain_validation"]["domain_physics_validation_schema"] == DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA
    assert payload["domain_validation"]["numerical_correctness_claimed"] is False
    assert payload["plugin_metadata"]["core_must_import"] is False
    assert payload["plugin_metadata"]["core_required_fields"] == []


def test_dft_package_bridges_generic_core_payload_plus_profile_owned_metadata(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)

    run_step1_workload_ingestion_workflow(
        {"input": QE_INPUT, "log": QE_LOG, "profile": {"phases": {"h_psi": 2.0, "fft": 0.25}}},
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind="qe_pw_bundle",
        parameters={"case_id": "qe_profile_contract", "graph_id": "qe_profile_contract_graph"},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
    )

    package = _load_json(tmp_path / "workload_package.json")
    contract_view = profile_contract_from_package(package)
    dft_metadata = package["domain_metadata"]["dft"]

    assert package["schema_version"] == "dse.step1.workload_package.v1"
    assert set(contract_view["top_level_dft_keys"]) == set()
    assert contract_view["has_dft_domain_metadata"] is True
    assert contract_view["core_required_fields"] == []
    assert dft_metadata["profile_metadata"]["owner"] == "dse_v2.reference_workloads"
    assert dft_metadata["profile_metadata"]["domain_physics_validation_schema"] == DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA
    assert package["profile"]["domain_validation"]["schema_version"] == DFT_DOMAIN_VALIDATION_SCHEMA
    assert validate_dft_profile_contract(package["profile"])["valid"] is True


def test_source_fact_merge_preserves_conflicts_and_prefers_higher_evidence():
    facts = [
        SourceFact("dimension.npw", 128, unit="count", source_type="input", evidence_level="declared_input"),
        SourceFact("dimension.npw", 256, unit="count", source_type="log", evidence_level="observed_preprocessed"),
        SourceFact("dimension.nbnd", 8, unit="count", source_type="heuristic", evidence_level="fallback"),
    ]

    merged = merge_source_facts(facts)

    assert merged["fact_summaries"]["dimension.npw"]["preferred_value"] == 256
    assert merged["fact_summaries"]["dimension.npw"]["source_type"] == "log"
    assert merged["conflicts"][0]["field"] == "dimension.npw"
    assert "project_critical_conflict" in merged["conflicts"][0]["review_flags"]
    assert len(merged["fact_summaries"]["dimension.npw"]["fact_ids"]) == 2


def test_phase_id_rules_are_stable_and_extension_safe():
    assert canonicalize_phase_id("h_psi") == "h_psi"
    assert canonicalize_phase_id("c_bands") == "diagonalization"
    assert canonicalize_phase_id("two electron integrals") == "extension:quantum_chemistry:two_electron_integrals"
    assert canonicalize_phase_id("extension:mycode:phase-A") == "extension:mycode:phase_a"
    assert canonicalize_phase_id("mystery phase") == canonicalize_phase_id("mystery phase")
    assert stable_unknown_phase_id("mystery phase") == stable_unknown_phase_id("mystery phase")


def test_dft_qe_step1_frontdoor_emits_generic_package_graph_and_characterization(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)

    result = run_step1_workload_ingestion_workflow(
        {"input": QE_INPUT, "log": QE_LOG, "profile": {"phases": {"h_psi": 2.0, "fft": 0.25}}},
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind="qe_pw_bundle",
        parameters={"case_id": "qe_si_static", "graph_id": "qe_si_graph"},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
        timestamp="2026-05-13T00:00:00Z",
        environment_summary={"test": True},
    )

    assert result.status == "complete"
    package = _load_json(tmp_path / "workload_package.json")
    graph = _load_json(tmp_path / "workload_graph.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")

    assert package["workload_family"] == "dft"
    assert set(package["domain_metadata"]) == {"dft", "characterization"}
    assert package["domain_metadata"]["dft"]["source_program"] == "qe_pw"
    assert package["domain_metadata"]["dft"]["conflicts"]
    assert package["domain_metadata"]["dft"]["coverage"]["claim_boundary"] == "diagnostic"
    assert graph["schema_version"] == "dse.compute_graph.v1"
    assert graph["nodes"]
    assert all("adapter:dft" in node["attributes"] for node in graph["nodes"].values())
    assert all("adapter:dft" not in node for node in graph["nodes"].values())
    assert characterization["analysis_scope"] == "architecture_independent"
    assert characterization["domain_phase_summary"]["schema_version"] == "dse.domain_phase_summary.v1"
    assert characterization["domain_workflow_summary"]["schema_version"] == "dse.domain_workflow_summary.v1"
    assert characterization["domain_claim_summary"]["schema_version"] == "dse.domain_claim_summary.v1"
    assert characterization["domain_claim_summary"]["observed_hotspots"]
    assert characterization["domain_phase_summary"]["dominance_summary"]["dominant_phase_ids"] == ["h_psi"]
    assert characterization["full_workload_eligible"] is False
    assert verify_step1_artifact_validation(tmp_path)["valid"] is True


def test_dft_vasp_step1_frontdoor_emits_generic_package_graph_and_characterization(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_vasp_profile())
    importers = default_importer_registry()
    register_dft_vasp_importer(importers)

    result = run_step1_workload_ingestion_workflow(
        {
            "incar": VASP_INCAR,
            "kpoints": VASP_KPOINTS,
            "poscar": VASP_POSCAR,
            "outcar": VASP_OUTCAR,
            "profile": {"phases": {"DAV": 2.0, "FFT": 0.25}},
        },
        profile_id="dft_vasp_static",
        importer_id="dft_vasp",
        source_kind="vasp_bundle",
        parameters={"case_id": "vasp_si_static", "graph_id": "vasp_si_graph"},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
        timestamp="2026-05-13T00:00:00Z",
        environment_summary={"test": True},
    )

    assert result.status == "complete"
    package = _load_json(tmp_path / "workload_package.json")
    graph = _load_json(tmp_path / "workload_graph.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")

    assert package["workload_family"] == "dft"
    assert package["source"]["kind"] == "vasp_bundle"
    assert package["domain_metadata"]["dft"]["source_program"] == "vasp"
    assert package["domain_metadata"]["dft"]["coverage"]["claim_boundary"] == "diagnostic"
    assert graph["schema_version"] == "dse.compute_graph.v1"
    assert graph["nodes"]
    assert all("adapter:dft" in node["attributes"] for node in graph["nodes"].values())
    assert characterization["analysis_scope"] == "architecture_independent"
    assert characterization["domain_phase_summary"]["schema_version"] == "dse.domain_phase_summary.v1"
    assert characterization["domain_claim_summary"]["observed_hotspots"]
    assert "diagonalization" in characterization["domain_phase_summary"]["dominance_summary"]["dominant_phase_ids"]
    assert characterization["full_workload_eligible"] is False
    assert verify_step1_artifact_validation(tmp_path)["valid"] is True


def test_qe_workflow_bundle_emits_multi_stage_workflow_and_claim_summaries(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)

    run_step1_workload_ingestion_workflow(
        {
            "stages": [
                {"program": "pw.x", "input": QE_INPUT, "log": QE_LOG, "profile": {"phases": {"h_psi": 2.0, "fft": 0.25}}},
                {"program": "pw.x", "input": QE_NSCF_INPUT, "parameters": {"static_dominance_margin": 2.0}},
                {"program": "bands.x", "profile": {"phases": {"diagonalization": 0.5}}},
            ]
        },
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind="qe_workflow_bundle",
        parameters={"case_id": "qe_multi_stage", "graph_id": "qe_multi_stage_graph", "nbnd": 512},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
    )

    package = _load_json(tmp_path / "workload_package.json")
    graph = _load_json(tmp_path / "workload_graph.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")
    workflow = characterization["domain_workflow_summary"]
    claims = characterization["domain_claim_summary"]
    phase_summary = characterization["domain_phase_summary"]
    source_facts = package["domain_metadata"]["dft"]["source_facts"]

    assert phase_summary["schema_version"] == "dse.domain_phase_summary.v1"
    assert phase_summary["stage_count"] == 3
    assert phase_summary["phase_summaries"]
    assert "h_psi" in phase_summary["dominance_summary"]["dominant_phase_ids"]
    assert workflow["schema_version"] == "dse.domain_workflow_summary.v1"
    assert workflow["stage_count"] == 3
    assert workflow["by_stage_type"]["scf"] == 1
    assert workflow["by_stage_type"]["nscf"] == 1
    assert workflow["by_stage_type"]["bands"] == 1
    assert workflow["dependency_count"] == 2
    assert claims["observed_hotspots"]
    assert claims["predicted_hotspots"]
    assert all(item["evidence_label"] != "observed" for item in claims["predicted_hotspots"])
    assert "observed_dominance" in claims
    assert any(node["op_type"] == "dft_workflow_stage" for node in graph["nodes"].values())
    assert any("hotspot" in node_id for node_id in graph["nodes"])
    assert package["domain_metadata"]["dft"]["workflow"]["schema_version"] == "dse.dft.workflow_spec.v1"
    assert source_facts
    assert any(fact["field"] == "input.calculation" for fact in source_facts)
    assert any(fact["field"].startswith("phase_timing.") for fact in source_facts)
    assert package["domain_metadata"]["dft"]["workflow"]["stages"][0]["source_facts"]
    assert verify_step1_artifact_validation(tmp_path)["valid"] is True


def test_input_only_dft_case_marks_insufficient_evidence_and_no_dominant_phase(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)

    run_step1_workload_ingestion_workflow(
        QE_INPUT,
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind="qe_pw_input",
        parameters={"case_id": "input_only", "graph_id": "input_only_graph"},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
    )

    package = _load_json(tmp_path / "workload_package.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")
    dft = package["domain_metadata"]["dft"]
    assert "insufficient_evidence" in dft["review_flags"]
    assert dft["coverage"]["full_workload_reconstruction"] is False
    assert all(phase["dominance"] == "candidate" for phase in dft["phases"])
    assert characterization["domain_phase_summary"]["dominance_summary"]["dominant_phase_ids"] == []
    assert characterization["domain_claim_summary"]["predicted_hotspots"]
    assert characterization["domain_claim_summary"]["observed_hotspots"] == []


def test_dft_frontdoor_outputs_do_not_use_step2_decision_field_names(tmp_path):
    profiles = default_profile_registry()
    profiles.register(dft_qe_pw_profile())
    importers = default_importer_registry()
    register_dft_qe_importer(importers)

    run_step1_workload_ingestion_workflow(
        {"input": QE_INPUT, "log": QE_LOG},
        profile_id="dft_qe_pw_static",
        importer_id="dft_qe_pw",
        source_kind="qe_pw_bundle",
        parameters={"case_id": "no_leak", "graph_id": "no_leak_graph"},
        output_dir=tmp_path,
        profile_registry=profiles,
        importer_registry=importers,
    )

    package = _load_json(tmp_path / "workload_package.json")
    characterization = _load_json(tmp_path / "workload_characterization.json")
    guarded_payload = {
        "domain_metadata": package["domain_metadata"],
        "workload_characterization": characterization,
    }
    keys = set(_all_keys(guarded_payload))
    forbidden_exact = {
        "selected_mapping",
        "selected_placement",
        "selected_schedule",
        "selected_runtime_policy",
        "descriptor_protocol_selection",
        "selected_fusion",
        "placement",
        "schedule",
        "runtime_policy",
        "simulator_verdict",
        "accelerator_config",
        "promotion_decision",
        "l2_evidence",
        "l3_evidence",
        "l4_evidence",
    }
    assert forbidden_exact.isdisjoint(keys)
