#!/usr/bin/env python3
"""QE workflow bundle to FPGA-DSE workload abstraction regressions."""

from __future__ import annotations

from pathlib import Path

from dse_v2.reference_workloads.qe_workflow_fpga_abstraction import (
    build_qe_workflow_fpga_abstraction,
    load_qe_workflow_bundle,
)


SCF_INPUT = """
&CONTROL
  calculation = 'scf',
  prefix = 'si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 16,
/
&ELECTRONS
  conv_thr = 1.0d-8,
  mixing_beta = 0.6,
  electron_maxstep = 60,
/
K_POINTS automatic
4 4 2 0 0 0
"""


NSCF_INPUT = """
&CONTROL
  calculation = 'nscf',
  prefix = 'si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 30.0,
  nbnd = 32,
/
K_POINTS automatic
6 6 4 0 0 0
"""


SCF_LOG = """
     number of k points=     12
     number of Kohn-Sham states= 16
     number of plane waves= 2048
     dense FFT grid: ( 40, 40, 32)
     iteration # 1
     iteration # 2
     h_psi        :      0.10s CPU      7.50s WALL
     FFT          :      0.03s CPU      2.10s WALL
     v_of_rho     :      0.02s CPU      0.85s WALL
     mix_rho      :      0.01s CPU      0.45s WALL
     convergence has been achieved in 2 iterations
"""


NSCF_LOG = """
     number of k points=     24
     number of Kohn-Sham states= 32
     number of plane waves= 4096
     dense FFT grid: ( 48, 48, 40)
     h_psi        :      0.20s CPU      11.00s WALL
     c_bands      :      0.05s CPU      1.70s WALL
"""


def test_qe_workflow_bundle_builds_fpga_dse_graph_and_features() -> None:
    bundle = {
        "workflow_id": "si_realistic_bundle",
        "stages": [
            {
                "stage_id": "scf_ground_state",
                "program": "pw.x",
                "input": SCF_INPUT,
                "stdout": SCF_LOG,
            },
            {
                "stage_id": "nscf_dense_kmesh",
                "program": "pw.x",
                "input": NSCF_INPUT,
                "stdout": NSCF_LOG,
            },
            {
                "stage_id": "bands_post",
                "program": "bands.x",
                "profile": {"phases": {"band_path_projection": 0.80, "write_bands": 0.20}},
            },
        ],
    }

    report = build_qe_workflow_fpga_abstraction(bundle, workload_id="si_realistic_bundle")

    assert report["schema_version"] == "dse.qe_workflow_fpga_abstraction.v1"
    assert report["workload_id"] == "si_realistic_bundle"
    assert report["source"]["stage_count"] == 3
    assert report["graph"]["node_count"] >= 9
    assert report["graph"]["edge_count"] >= 8
    assert report["graph_summary"]["node_count"] == report["graph"]["node_count"]
    assert report["graph_summary"]["edge_count"] == report["graph"]["edge_count"]
    assert report["graph_summary"]["host_node_count"] > 0
    assert report["graph_summary"]["accelerator_node_count"] > 0
    assert report["graph_summary"]["graph_density"] > 0.0
    assert {node["stage_type"] for node in report["graph"]["nodes"]}.issuperset({"scf", "nscf", "bands"})
    assert report["features"]["workflow_classes"] == ["nscf", "post_processing", "scf"]
    assert report["features"]["max_dimensions"]["nbnd"] == 32
    assert report["features"]["max_dimensions"]["npw"] == 4096
    assert report["features"]["max_dimensions"]["nfft"] == 48 * 48 * 40
    assert report["features"]["scf_iteration_count_observed"] == 2
    assert report["features"]["estimated_wavefunction_bytes"] > 0
    assert report["features"]["estimated_charge_density_bytes"] > 0
    assert report["features"]["estimated_total_data_movement_bytes"] > report["features"]["estimated_wavefunction_bytes"]
    assert report["features"]["kernel_weights"]["h_psi"] > report["features"]["kernel_weights"]["fft"]
    assert report["features"]["host_control_intensity"] > 0.0
    assert report["features"]["stage_repetition"]["scf_ground_state"]["observed_iterations"] == 2
    assert report["features"]["stage_repetition"]["scf_ground_state"]["repetition_kind"] == "scf_iteration_loop"
    assert report["features"]["host_control_events"]["scf_convergence_check_count"] == 2
    assert report["features"]["host_control_events"]["post_processing_stage_count"] == 1
    assert report["features"]["correctness_observables"]["workflow"] == [
        "total_energy",
        "charge_density_residual",
        "eigenvalue_spectrum",
        "band_structure",
    ]
    assert set(report["data_objects"]).issuperset({"psi", "rho", "v_of_rho", "eigenvalues", "qe_save_dir"})
    psi = report["data_objects"]["psi"]
    rho = report["data_objects"]["rho"]
    assert psi["bytes"] == report["features"]["estimated_wavefunction_bytes"]
    assert psi["preferred_residency_hint"] == "fpga_hbm_or_host_pinned_reuse"
    assert "scf_ground_state" in psi["producer_stages"]
    assert "nscf_dense_kmesh" in psi["consumer_stages"]
    assert rho["preferred_residency_hint"] == "host_visible_checkpoint_with_optional_fpga_cache"
    assert any(edge["edge_kind"] == "data_object_lifetime" and edge["tensor_name"] == "psi" for edge in report["graph"]["edges"])
    assert "charge_density" in report["host_retained_stage_hints"]
    assert report["claim_boundary"] == "workload_abstraction_only_not_fpga_performance_evidence"

    contract = report["workflow_feature_contract"]
    assert contract["schema_version"] == "dse.workflow_feature_contract.v1"
    assert contract["domain_neutral"] is True
    assert contract["source_adapter"] == "qe_workflow_fpga_abstraction"
    assert contract["workload_family"] == "qe"
    assert contract["workflow_id"] == "si_realistic_bundle"
    assert contract["claim_boundary"] == "workflow_features_only_not_evidence_not_candidate_identity"

    dag = contract["workflow_dag"]
    assert dag["stage_count"] == 3
    assert {stage["stage_type"] for stage in dag["stages"]}.issuperset({"scf", "nscf", "bands"})
    assert any(stage["repetition"]["kind"] == "scf_iteration_loop" for stage in dag["stages"])
    assert any(edge["edge_kind"] == "stage_order" for edge in dag["edges"])

    stage_table = {row["stage_id"]: row for row in contract["stage_feature_table"]}
    assert stage_table["scf_ground_state"]["host_control_barrier"] is True
    assert stage_table["scf_ground_state"]["expected_repetition"] == 2
    assert stage_table["bands_post"]["stage_class"] == "post_processing"
    assert stage_table["bands_post"]["include_in_performance_model"] is True

    data_table = {row["object_id"]: row for row in contract["data_object_table"]}
    assert {"psi", "rho", "qe_save_dir"}.issubset(data_table)
    assert data_table["psi"]["bytes"] == report["features"]["estimated_wavefunction_bytes"]
    assert "nscf_dense_kmesh" in data_table["psi"]["consumer_stages"]
    assert data_table["qe_save_dir"]["residency_constraint"] == "host_filesystem_checkpoint_not_accelerator_resident"

    compute_table = {row["compute_id"]: row for row in contract["compute_feature_table"]}
    assert compute_table["h_psi"]["weight_seconds"] > compute_table["fft"]["weight_seconds"]
    assert compute_table["h_psi"]["source_confidence"] in {"observed", "estimated"}
    assert compute_table["h_psi"]["uncertainty"]["kind"] == "relative_weight_interval"

    correctness = contract["correctness_observable_table"]
    assert "total_energy" in correctness["workflow"]
    assert "band_structure" in correctness["workflow"]

    assert contract["search_objectives"] == [
        "latency",
        "energy",
        "edp",
        "resource_pressure",
        "data_movement",
        "feasibility_risk",
    ]


def test_qe_workflow_abstraction_preserves_source_fact_provenance() -> None:
    report = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "single_scf",
            "stages": [{"stage_id": "scf", "program": "pw.x", "input": SCF_INPUT, "stdout": SCF_LOG}],
        },
        workload_id="single_scf",
    )

    facts = report["source_facts"]
    fields = {fact["field"] for fact in facts}
    assert "parameter.ecutwfc" in fields
    assert "dimension.kpoint_grid" in fields
    assert "dimension.npw" in fields
    assert "dimension.fft_grid" in fields
    assert "phase_timing.h_psi.wall_seconds" in fields
    assert all(fact["stage_id"] == "scf" for fact in facts)
    assert any(fact["evidence_level"] == "observed_timing" for fact in facts)


def test_qe_workflow_abstraction_uses_explicit_stage_dag_and_stage_local_compute() -> None:
    bundle = {
        "workflow_id": "branched_qe_workflow",
        "stages": [
            {
                "stage_id": "scf_ground_state",
                "program": "pw.x",
                "input": SCF_INPUT,
                "stdout": SCF_LOG,
            },
            {
                "stage_id": "nscf_dense_kmesh",
                "program": "pw.x",
                "input": NSCF_INPUT,
                "stdout": NSCF_LOG,
                "depends_on": ["scf_ground_state"],
            },
            {
                "stage_id": "bands_post",
                "program": "bands.x",
                "profile": {"phases": {"band_path_projection": 0.80, "write_bands": 0.20}},
                "depends_on": ["nscf_dense_kmesh"],
            },
            {
                "stage_id": "dos_post",
                "program": "dos.x",
                "profile": {"phases": {"reduction": 0.70, "io": 0.30}},
                "depends_on": ["nscf_dense_kmesh"],
            },
        ],
    }

    report = build_qe_workflow_fpga_abstraction(bundle, workload_id="branched_qe_workflow")

    contract = report["workflow_feature_contract"]
    dag_edges = {
        (edge["source_stage"], edge["target_stage"], edge["edge_kind"])
        for edge in contract["workflow_dag"]["edges"]
    }
    assert ("scf_ground_state", "nscf_dense_kmesh", "stage_artifact_dependency") in dag_edges
    assert ("nscf_dense_kmesh", "bands_post", "stage_artifact_dependency") in dag_edges
    assert ("nscf_dense_kmesh", "dos_post", "stage_artifact_dependency") in dag_edges
    assert ("bands_post", "dos_post", "stage_order") not in dag_edges

    stage_by_id = {stage["stage_id"]: stage for stage in contract["workflow_dag"]["stages"]}
    assert stage_by_id["scf_ground_state"]["repetition"]["kind"] == "scf_iteration_loop"
    assert stage_by_id["nscf_dense_kmesh"]["repetition"]["kind"] == "single_electronic_spectrum_pass"
    assert stage_by_id["bands_post"]["repetition"]["kind"] == "single_post_processing_pass"

    features_by_id = {stage["stage_id"]: stage for stage in contract["stage_feature_table"]}
    assert "h_psi" in features_by_id["scf_ground_state"]["compute_ids"]
    assert "h_psi" in features_by_id["nscf_dense_kmesh"]["compute_ids"]
    assert "band_path_projection" in features_by_id["bands_post"]["compute_ids"] or "write_bands" in features_by_id["bands_post"]["compute_ids"]
    assert "reduction" in features_by_id["dos_post"]["compute_ids"]
    assert features_by_id["scf_ground_state"]["compute_ids"] != features_by_id["nscf_dense_kmesh"]["compute_ids"]

    compute_by_stage = {
        stage_id: {row["compute_id"] for row in rows}
        for stage_id, rows in contract["stage_compute_feature_table"].items()
    }
    assert compute_by_stage["scf_ground_state"].issuperset({"h_psi", "fft"})
    assert "h_psi" in compute_by_stage["nscf_dense_kmesh"]
    assert "band_path_projection" in compute_by_stage["bands_post"] or "write_bands" in compute_by_stage["bands_post"]
    assert compute_by_stage["dos_post"] == {"io", "reduction"}


def test_qe_workflow_abstraction_uses_qe_native_file_bundle_and_artifacts(tmp_path: Path) -> None:
    input_path = tmp_path / "si.scf.in"
    stdout_path = tmp_path / "si.scf.out"
    profile_path = tmp_path / "si.profile.json"
    save_dir = tmp_path / "si.save"
    pseudo_path = tmp_path / "Si.pbe-n-kjpaw_psl.1.0.0.UPF"
    charge_density = save_dir / "charge-density.dat"
    wavefunction = save_dir / "wfc1.dat"
    data_file = save_dir / "data-file-schema.xml"
    save_dir.mkdir()
    pseudo_path.write_text("pseudo", encoding="utf-8")
    charge_density.write_bytes(b"r" * 4096)
    wavefunction.write_bytes(b"w" * 8192)
    data_file.write_text("<root/>", encoding="utf-8")
    input_path.write_text(
        """
&CONTROL
  calculation = 'scf',
  prefix = 'si',
  outdir = './tmp',
  pseudo_dir = './pseudo',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  ecutwfc = 35.0,
  ecutrho = 280.0,
  nbnd = 18,
  occupations = 'smearing',
/
&ELECTRONS
  conv_thr = 1.0d-9,
  diagonalization = 'david',
/
ATOMIC_SPECIES
 Si 28.0855 Si.pbe-n-kjpaw_psl.1.0.0.UPF
K_POINTS automatic
4 4 4 0 0 0
""",
        encoding="utf-8",
    )
    stdout_path.write_text(
        """
     Program PWSCF v.7.5 starts on  1Jun2026
     number of MPI processes:                 8
     number of OpenMP threads:                2
     number of k points=     10
     number of Kohn-Sham states= 18
     number of plane waves= 3072
     dense FFT grid: ( 45, 45, 36)
     iteration # 1
     iteration # 2
     iteration # 3
     total energy              =     -15.43210000 Ry
     estimated scf accuracy    <       1.2E-10 Ry
     the Fermi energy is    6.2040 ev
     convergence has been achieved in   3 iterations
     h_psi        :      0.10s CPU      6.00s WALL
     FFT          :      0.03s CPU      1.50s WALL
     c_bands      :      0.02s CPU      0.90s WALL
""",
        encoding="utf-8",
    )
    profile_path.write_text(
        '{"phases": {"h_psi": 6.0, "fft": 1.5, "diagonalization": 0.9}}',
        encoding="utf-8",
    )

    report = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "si_native_bundle",
            "stages": [
                {
                    "stage_id": "scf_native",
                    "program": "pw.x",
                    "input_path": str(input_path),
                    "log_path": str(stdout_path),
                    "profile_path": str(profile_path),
                    "save_dir": str(save_dir),
                    "pseudopotential_paths": [str(pseudo_path)],
                },
                {
                    "stage_id": "dos_native",
                    "program": "dos.x",
                    "depends_on": ["scf_native"],
                    "profile": {"phases": {"reduction": 0.4, "io": 0.1}},
                },
            ],
        },
        workload_id="si_native_bundle",
    )

    assert report["source"]["input_model"] == "qe_native_workflow_bundle"
    assert report["source"]["observed_runtime"] is True
    assert report["source"]["qe_programs"] == ["dos.x", "pw.x"]
    assert report["source"]["artifact_dependency_count"] >= 1
    assert report["features"]["max_dimensions"]["npw"] == 3072
    assert report["features"]["scf_iteration_count_observed"] == 3
    assert report["features"]["runtime_environment"]["qe_version"] == "7.5"
    assert report["features"]["runtime_environment"]["mpi_processes"] == 8
    assert report["features"]["runtime_environment"]["openmp_threads"] == 2
    assert report["features"]["correctness_observables"]["observed_values"]["final_total_energy_ry"] == -15.4321
    assert report["features"]["correctness_observables"]["observed_values"]["scf_accuracy_ry"] == 1.2e-10
    assert report["features"]["correctness_observables"]["observed_values"]["fermi_energy_ev"] == 6.204
    assert report["features"]["pseudopotentials"][0]["path"] == str(pseudo_path)
    assert report["features"]["pseudopotentials"][0]["sha256"].startswith("sha256:")

    save_object = report["data_objects"]["qe_save_dir"]
    assert save_object["observed_path"] == str(save_dir)
    assert save_object["observed_file_count"] == 3
    assert save_object["bytes"] >= 4096 + 8192
    assert any("charge-density.dat" in artifact["path"] for artifact in save_object["artifacts"])
    assert any(
        edge["edge_kind"] == "stage_artifact_dependency" and edge["tensor_name"] == "qe_save_dir"
        for edge in report["graph"]["edges"]
    )
    assert report["graph_summary"]["inter_stage_edge_count"] >= 1
    assert report["graph_summary"]["edge_kind_counts"]["control"] >= 1
    assert report["graph_summary"]["placement_hint_counts"]["host"] >= 1

    fields = {fact["field"] for fact in report["source_facts"]}
    assert {
        "input.prefix",
        "input.outdir",
        "input.pseudo_dir",
        "runtime.qe_version",
        "runtime.mpi_processes",
        "runtime.openmp_threads",
        "observable.final_total_energy_ry",
        "observable.scf_accuracy_ry",
        "observable.fermi_energy_ev",
        "artifact.qe_save_dir.bytes",
        "artifact.pseudopotential.sha256",
    }.issubset(fields)


def test_qe_workflow_abstraction_ingests_qe_save_xml_metadata(tmp_path: Path) -> None:
    input_path = tmp_path / "si.scf.in"
    stdout_path = tmp_path / "si.scf.out"
    save_dir = tmp_path / "si.save"
    xml_path = save_dir / "data-file-schema.xml"
    save_dir.mkdir()
    input_path.write_text(
        """
&CONTROL
  calculation = 'scf',
  prefix = 'si',
/
&SYSTEM
  nat = 2,
  ntyp = 1,
  nbnd = 8,
  ecutwfc = 30.0,
/
K_POINTS automatic
2 2 2 0 0 0
""",
        encoding="utf-8",
    )
    stdout_path.write_text(
        """
     Program PWSCF v.7.5 starts on  1Jun2026
     number of Kohn-Sham states= 8
     h_psi        :      0.01s CPU      1.00s WALL
""",
        encoding="utf-8",
    )
    xml_path.write_text(
        """
<qes:espresso xmlns:qes="http://www.quantum-espresso.org/ns/qes/qes-1.0">
  <output>
    <atomic_structure nat="2">
      <cell>
        <a1>5.43 0.0 0.0</a1>
        <a2>0.0 5.43 0.0</a2>
        <a3>0.0 0.0 5.43</a3>
      </cell>
    </atomic_structure>
    <basis_set>
      <ecutwfc>30.0</ecutwfc>
      <ecutrho>240.0</ecutrho>
      <fft_grid nr1="36" nr2="36" nr3="36"/>
      <smooth_fft_grid nr1="24" nr2="24" nr3="24"/>
      <npw>1536</npw>
    </basis_set>
    <band_structure>
      <nbnd>12</nbnd>
      <nks>8</nks>
      <fermi_energy units="eV">5.621</fermi_energy>
      <ks_energies>
        <eigenvalues units="eV">-5.0 -1.0 0.5 1.0</eigenvalues>
        <occupations>2.0 2.0 0.0 0.0</occupations>
      </ks_energies>
      <ks_energies>
        <eigenvalues units="eV">-4.8 -0.9 0.6 1.2</eigenvalues>
        <occupations>2.0 2.0 0.0 0.0</occupations>
      </ks_energies>
    </band_structure>
  </output>
</qes:espresso>
""",
        encoding="utf-8",
    )

    report = build_qe_workflow_fpga_abstraction(
        {
            "workflow_id": "si_xml_bundle",
            "stages": [
                {
                    "stage_id": "scf_xml",
                    "program": "pw.x",
                    "input_path": str(input_path),
                    "log_path": str(stdout_path),
                    "save_dir": str(save_dir),
                }
            ],
        },
        workload_id="si_xml_bundle",
    )

    fields = {fact["field"] for fact in report["source_facts"]}
    assert {
        "dimension.fft_grid",
        "dimension.smooth_fft_grid",
        "dimension.nfft",
        "dimension.npw",
        "dimension.nbnd",
        "dimension.kpoint_count",
        "observable.fermi_energy_ev",
        "observable.eigenvalue_count",
        "observable.occupation_count",
        "observable.eigenvalue_min_ev",
        "observable.eigenvalue_max_ev",
        "artifact.qe_metadata_xml.sha256",
    }.issubset(fields)
    assert report["features"]["max_dimensions"]["nbnd"] == 12
    assert report["features"]["max_dimensions"]["npw"] == 1536
    assert report["features"]["max_dimensions"]["nfft"] == 36 * 36 * 36
    assert report["features"]["correctness_observables"]["observed_values"]["fermi_energy_ev"] == 5.621
    assert report["features"]["correctness_observables"]["observed_values"]["eigenvalue_count"] == 8
    assert report["features"]["correctness_observables"]["observed_values"]["occupation_count"] == 8
    assert report["features"]["correctness_observables"]["observed_values"]["eigenvalue_min_ev"] == -5.0
    assert report["features"]["correctness_observables"]["observed_values"]["eigenvalue_max_ev"] == 1.2
    assert report["data_objects"]["qe_save_dir"]["metadata_xml_count"] == 1
    assert any(
        artifact["artifact_kind"] == "qe_metadata_xml" and artifact["sha256"].startswith("sha256:")
        for artifact in report["data_objects"]["qe_save_dir"]["artifacts"]
    )


def test_load_qe_workflow_bundle_manifest_resolves_relative_paths_and_stage_dependencies(tmp_path: Path) -> None:
    bundle_root = tmp_path / "si_bundle"
    scf_dir = bundle_root / "01-scf"
    nscf_dir = bundle_root / "02-nscf"
    bands_dir = bundle_root / "03-bands"
    save_dir = scf_dir / "tmp" / "si.save"
    pseudo_dir = bundle_root / "pseudo"
    save_dir.mkdir(parents=True)
    pseudo_dir.mkdir(parents=True)
    nscf_dir.mkdir(parents=True)
    bands_dir.mkdir(parents=True)
    (pseudo_dir / "Si.UPF").write_text("pseudo", encoding="utf-8")
    (save_dir / "charge-density.dat").write_bytes(b"r" * 256)
    (save_dir / "wfc1.dat").write_bytes(b"w" * 512)
    (scf_dir / "scf.in").write_text(SCF_INPUT, encoding="utf-8")
    (scf_dir / "scf.out").write_text(SCF_LOG, encoding="utf-8")
    (nscf_dir / "nscf.in").write_text(NSCF_INPUT, encoding="utf-8")
    (nscf_dir / "nscf.out").write_text(NSCF_LOG, encoding="utf-8")
    (bands_dir / "bands_profile.json").write_text(
        '{"phases": {"band_path_projection": 0.7, "write_bands": 0.3}}',
        encoding="utf-8",
    )
    manifest_path = bundle_root / "qe_workflow_bundle.json"
    manifest_path.write_text(
        """
{
  "schema_version": "dse.qe.native_workflow_bundle.v1",
  "workflow_id": "si_manifest_bundle",
  "stages": [
    {
      "stage_id": "scf",
      "program": "pw.x",
      "input_path": "01-scf/scf.in",
      "log_path": "01-scf/scf.out",
      "save_dir": "01-scf/tmp/si.save",
      "pseudopotential_paths": ["pseudo/Si.UPF"]
    },
    {
      "stage_id": "nscf",
      "program": "pw.x",
      "input_path": "02-nscf/nscf.in",
      "log_path": "02-nscf/nscf.out",
      "depends_on": ["scf"]
    },
    {
      "stage_id": "bands",
      "program": "bands.x",
      "profile_path": "03-bands/bands_profile.json",
      "depends_on": ["nscf"]
    }
  ]
}
""",
        encoding="utf-8",
    )

    bundle = load_qe_workflow_bundle(manifest_path)
    report = build_qe_workflow_fpga_abstraction(bundle)

    assert report["workload_id"] == "si_manifest_bundle"
    assert report["source"]["input_model"] == "qe_native_workflow_bundle"
    assert report["source"]["bundle_manifest"]["path"] == str(manifest_path)
    assert report["source"]["bundle_manifest"]["sha256"].startswith("sha256:")
    assert report["source"]["bundle_root"] == str(bundle_root)
    assert report["source"]["stage_count"] == 3
    assert report["source"]["artifact_dependency_count"] == 2
    assert report["features"]["workflow_classes"] == ["nscf", "post_processing", "scf"]
    assert report["features"]["max_dimensions"]["nbnd"] == 32
    assert report["features"]["max_dimensions"]["npw"] == 4096
    assert report["features"]["pseudopotentials"][0]["path"] == str(pseudo_dir / "Si.UPF")
    assert report["data_objects"]["qe_save_dir"]["observed_path"] == str(save_dir)
    assert report["data_objects"]["qe_save_dir"]["bytes"] >= 768
    assert any(
        edge["edge_kind"] == "stage_artifact_dependency"
        and edge["source_node"] == "nscf:control"
        and edge["target_node"] == "bands:control"
        for edge in report["graph"]["edges"]
    )


def test_load_qe_workflow_bundle_directory_discovers_default_manifest(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle_dir"
    bundle_root.mkdir()
    (bundle_root / "workflow_bundle.json").write_text(
        """
{
  "workflow_id": "directory_bundle",
  "stages": [
    {
      "stage_id": "scf",
      "program": "pw.x",
      "input": "&CONTROL\\n calculation = 'scf',\\n/\\n&SYSTEM\\n nat=1, ntyp=1, nbnd=4,\\n/\\nK_POINTS automatic\\n1 1 1 0 0 0\\n"
    }
  ]
}
""",
        encoding="utf-8",
    )

    bundle = load_qe_workflow_bundle(bundle_root)

    assert bundle["workflow_id"] == "directory_bundle"
    assert bundle["_bundle_manifest_path"] == str(bundle_root / "workflow_bundle.json")
    assert bundle["_bundle_root"] == str(bundle_root)
