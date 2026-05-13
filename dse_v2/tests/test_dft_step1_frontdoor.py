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
from dse_v2.reference_workloads.dft_qe import (
    dft_qe_pw_profile,
    parse_qe_profile,
    parse_qe_pw_input,
    parse_qe_pw_log,
    register_dft_qe_importer,
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
    assert characterization["domain_phase_summary"]["dominance_summary"]["dominant_phase_ids"] == ["h_psi"]
    assert characterization["full_workload_eligible"] is False
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
