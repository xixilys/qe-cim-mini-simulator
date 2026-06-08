#!/usr/bin/env python3
"""Build a file-backed representative QE workflow corpus fixture.

The generated corpus is intentionally a fixture for repeatable DSE pipeline
experiments.  It is not a measured QE benchmark suite and must not be reported
as hardware or application-performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


SCF_INPUT_TEMPLATE = """
&CONTROL
  calculation = '{calculation}',
  prefix = '{prefix}',
  outdir = './tmp',
  pseudo_dir = './pseudo',
/
&SYSTEM
  nat = {nat},
  ntyp = {ntyp},
  ecutwfc = {ecutwfc},
  nbnd = {nbnd},
  occupations = '{occupations}',
/
&ELECTRONS
  electron_maxstep = {electron_maxstep},
  mixing_beta = {mixing_beta},
/
K_POINTS automatic
{k1} {k2} {k3} 0 0 0
"""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(list(argv))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _pw_input(
    *,
    calculation: str,
    prefix: str,
    nat: int,
    ntyp: int,
    ecutwfc: float,
    nbnd: int,
    occupations: str,
    electron_maxstep: int,
    mixing_beta: float,
    k_grid: Sequence[int],
) -> str:
    k1, k2, k3 = k_grid
    return SCF_INPUT_TEMPLATE.format(
        calculation=calculation,
        prefix=prefix,
        nat=nat,
        ntyp=ntyp,
        ecutwfc=ecutwfc,
        nbnd=nbnd,
        occupations=occupations,
        electron_maxstep=electron_maxstep,
        mixing_beta=mixing_beta,
        k1=k1,
        k2=k2,
        k3=k3,
    )


def _pw_log(
    *,
    kpoints: int,
    nbnd: int,
    npw: int,
    fft: Sequence[int],
    iterations: int,
    hpsi_wall: float,
    fft_wall: float,
    diag_wall: float,
    extra_lines: Sequence[str] = (),
) -> str:
    fft_x, fft_y, fft_z = fft
    iteration_lines = "\n".join(f"     iteration # {index}" for index in range(1, iterations + 1))
    return f"""
     Program PWSCF v.7.5 starts on  1Jun2026
     number of MPI processes:                 8
     number of OpenMP threads:                2
     number of k points=     {kpoints}
     number of Kohn-Sham states= {nbnd}
     number of plane waves= {npw}
     dense FFT grid: ( {fft_x}, {fft_y}, {fft_z})
{iteration_lines}
     h_psi        :      0.20s CPU      {hpsi_wall:.2f}s WALL
     c_bands      :      0.10s CPU      {diag_wall:.2f}s WALL
     FFT          :      0.05s CPU      {fft_wall:.2f}s WALL
     mix_rho      :      0.02s CPU      0.40s WALL
     total energy              =      -7.25000000 Ry
     estimated scf accuracy    <       9.0E-11 Ry
{"".join(line + chr(10) for line in extra_lines)}
     convergence has been achieved in {iterations} iterations
"""


def _materialize_save_dir(path: Path, *, wave_bytes: int, density_bytes: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "charge-density.dat").write_bytes(b"r" * density_bytes)
    (path / "wfc1.dat").write_bytes(b"w" * wave_bytes)
    _write_text(path / "data-file-schema.xml", "<root><fixture>true</fixture></root>")


def _materialize_workload(root: Path, spec: Mapping[str, Any]) -> Dict[str, Any]:
    workload_dir = root / str(spec["workload_id"])
    pseudo_dir = workload_dir / "pseudo"
    pseudo_dir.mkdir(parents=True, exist_ok=True)
    _write_text(pseudo_dir / f"{spec['pseudo']}.UPF", f"pseudo fixture for {spec['material']}")
    save_dir = workload_dir / "tmp" / f"{spec['prefix']}.save"
    _materialize_save_dir(save_dir, wave_bytes=int(spec["wave_bytes"]), density_bytes=int(spec["density_bytes"]))

    stages: List[Dict[str, Any]] = []
    scf_input = _pw_input(
        calculation="scf",
        prefix=str(spec["prefix"]),
        nat=int(spec["nat"]),
        ntyp=int(spec["ntyp"]),
        ecutwfc=float(spec["ecutwfc"]),
        nbnd=int(spec["nbnd"]),
        occupations=str(spec["occupations"]),
        electron_maxstep=int(spec["electron_maxstep"]),
        mixing_beta=float(spec["mixing_beta"]),
        k_grid=spec["k_grid"],
    )
    scf_log = _pw_log(
        kpoints=int(spec["kpoints"]),
        nbnd=int(spec["nbnd"]),
        npw=int(spec["npw"]),
        fft=spec["fft_grid"],
        iterations=int(spec["iterations"]),
        hpsi_wall=float(spec["hpsi_wall"]),
        fft_wall=float(spec["fft_wall"]),
        diag_wall=float(spec["diag_wall"]),
    )
    _write_text(workload_dir / "scf.in", scf_input)
    _write_text(workload_dir / "scf.out", scf_log)
    _write_json(workload_dir / "scf_profile.json", {"phases": dict(spec["profile_phases"])})
    stages.append({
        "stage_id": f"{spec['prefix']}_scf",
        "program": "pw.x",
        "input_path": "scf.in",
        "log_path": "scf.out",
        "profile_path": "scf_profile.json",
        "save_dir": f"tmp/{spec['prefix']}.save",
        "pseudopotential_paths": [f"pseudo/{spec['pseudo']}.UPF"],
    })

    for stage in spec.get("extra_stages", []) or []:
        stage_type = str(stage["stage_type"])
        if stage_type == "nscf":
            nscf_input = _pw_input(
                calculation="nscf",
                prefix=str(spec["prefix"]),
                nat=int(spec["nat"]),
                ntyp=int(spec["ntyp"]),
                ecutwfc=float(spec["ecutwfc"]),
                nbnd=int(stage.get("nbnd", spec["nbnd"])),
                occupations=str(spec["occupations"]),
                electron_maxstep=int(spec["electron_maxstep"]),
                mixing_beta=float(spec["mixing_beta"]),
                k_grid=stage.get("k_grid", spec["k_grid"]),
            )
            nscf_log = _pw_log(
                kpoints=int(stage.get("kpoints", spec["kpoints"])),
                nbnd=int(stage.get("nbnd", spec["nbnd"])),
                npw=int(stage.get("npw", spec["npw"])),
                fft=stage.get("fft_grid", spec["fft_grid"]),
                iterations=1,
                hpsi_wall=float(stage.get("hpsi_wall", spec["hpsi_wall"])),
                fft_wall=float(stage.get("fft_wall", spec["fft_wall"])),
                diag_wall=float(stage.get("diag_wall", spec["diag_wall"])),
            )
            _write_text(workload_dir / "nscf.in", nscf_input)
            _write_text(workload_dir / "nscf.out", nscf_log)
            stages.append({
                "stage_id": f"{spec['prefix']}_nscf",
                "program": "pw.x",
                "input_path": "nscf.in",
                "log_path": "nscf.out",
                "depends_on": [f"{spec['prefix']}_scf"],
            })
        else:
            stages.append({
                "stage_id": f"{spec['prefix']}_{stage_type}",
                "program": str(stage.get("program", f"{stage_type}.x")),
                "depends_on": [f"{spec['prefix']}_scf"],
                "profile": {"phases": dict(stage.get("phases", {}))},
            })

    bundle = {
        "workflow_id": str(spec["workload_id"]),
        "stages": stages,
        "fixture_boundary": "representative_QE_workflow_fixture_not_measured_QE_benchmark",
    }
    _write_json(workload_dir / "workflow_bundle.json", bundle)
    return {
        "workload_id": str(spec["workload_id"]),
        "bundle_path": f"{spec['workload_id']}/workflow_bundle.json",
        "material": str(spec["material"]),
        "size_class": str(spec["size_class"]),
        "workflow_roles": list(spec["workflow_roles"]),
        "artifact_hashes": {
            "workflow_bundle": _sha256(workload_dir / "workflow_bundle.json"),
            "scf_input": _sha256(workload_dir / "scf.in"),
            "scf_log": _sha256(workload_dir / "scf.out"),
        },
    }


def _workload_specs() -> List[Dict[str, Any]]:
    return [
        {
            "workload_id": "si_scf_nscf_bands_small",
            "material": "Si",
            "size_class": "small",
            "prefix": "si",
            "pseudo": "Si",
            "nat": 2,
            "ntyp": 1,
            "ecutwfc": 24.0,
            "nbnd": 24,
            "occupations": "fixed",
            "electron_maxstep": 50,
            "mixing_beta": 0.7,
            "k_grid": [4, 4, 4],
            "kpoints": 16,
            "npw": 2048,
            "fft_grid": [40, 40, 40],
            "iterations": 6,
            "hpsi_wall": 8.2,
            "fft_wall": 2.1,
            "diag_wall": 1.6,
            "wave_bytes": 4096,
            "density_bytes": 2048,
            "profile_phases": {"h_psi": 8.2, "fft": 2.1, "diagonalization": 1.6, "mix_rho": 0.4},
            "workflow_roles": ["scf", "nscf", "bands"],
            "extra_stages": [
                {"stage_type": "nscf", "nbnd": 48, "k_grid": [6, 6, 6], "kpoints": 36, "npw": 4096, "hpsi_wall": 11.0, "fft_wall": 3.2, "diag_wall": 2.4},
                {"stage_type": "bands", "program": "bands.x", "phases": {"band_path_projection": 0.8, "io": 0.3}},
            ],
        },
        {
            "workload_id": "al_metal_scf_dos_medium",
            "material": "Al",
            "size_class": "medium",
            "prefix": "al",
            "pseudo": "Al",
            "nat": 4,
            "ntyp": 1,
            "ecutwfc": 48.0,
            "nbnd": 64,
            "occupations": "smearing",
            "electron_maxstep": 80,
            "mixing_beta": 0.35,
            "k_grid": [8, 8, 8],
            "kpoints": 64,
            "npw": 8192,
            "fft_grid": [72, 72, 72],
            "iterations": 10,
            "hpsi_wall": 24.0,
            "fft_wall": 7.5,
            "diag_wall": 9.0,
            "wave_bytes": 8192,
            "density_bytes": 4096,
            "profile_phases": {"h_psi": 24.0, "fft": 7.5, "diagonalization": 9.0, "mix_rho": 1.0},
            "workflow_roles": ["scf", "dos"],
            "extra_stages": [
                {"stage_type": "dos", "program": "dos.x", "phases": {"reduction": 2.5, "io": 1.4}},
            ],
        },
        {
            "workload_id": "oxide_relax_projector_heavy",
            "material": "TiO2",
            "size_class": "medium",
            "prefix": "tio2",
            "pseudo": "TiO2",
            "nat": 6,
            "ntyp": 2,
            "ecutwfc": 64.0,
            "nbnd": 96,
            "occupations": "fixed",
            "electron_maxstep": 90,
            "mixing_beta": 0.45,
            "k_grid": [3, 3, 3],
            "kpoints": 14,
            "npw": 12288,
            "fft_grid": [96, 96, 96],
            "iterations": 12,
            "hpsi_wall": 35.0,
            "fft_wall": 11.0,
            "diag_wall": 14.5,
            "wave_bytes": 12288,
            "density_bytes": 6144,
            "profile_phases": {"h_psi": 35.0, "projector": 12.0, "fft": 11.0, "diagonalization": 14.5, "forces": 2.4},
            "workflow_roles": ["scf", "relax", "projwfc"],
            "extra_stages": [
                {"stage_type": "relax", "program": "pw.x", "phases": {"forces": 2.4, "stress": 0.8, "h_psi": 20.0}},
                {"stage_type": "projwfc", "program": "projwfc.x", "phases": {"projector": 5.2, "reduction": 1.7, "io": 1.1}},
            ],
        },
        {
            "workload_id": "slab_gamma_fft_io_heavy",
            "material": "Si_slab",
            "size_class": "large_fft_fixture",
            "prefix": "slab",
            "pseudo": "Si",
            "nat": 12,
            "ntyp": 1,
            "ecutwfc": 36.0,
            "nbnd": 80,
            "occupations": "fixed",
            "electron_maxstep": 70,
            "mixing_beta": 0.5,
            "k_grid": [1, 1, 1],
            "kpoints": 1,
            "npw": 16384,
            "fft_grid": [64, 64, 192],
            "iterations": 8,
            "hpsi_wall": 18.0,
            "fft_wall": 18.5,
            "diag_wall": 7.0,
            "wave_bytes": 16384,
            "density_bytes": 8192,
            "profile_phases": {"h_psi": 18.0, "fft": 18.5, "transpose": 8.0, "diagonalization": 7.0, "io": 4.0},
            "workflow_roles": ["scf"],
            "extra_stages": [],
        },
    ]


def build_corpus(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    workload_rows = [_materialize_workload(out_dir, spec) for spec in _workload_specs()]
    corpus = {
        "schema_version": "dse.qe_fpga_workflow_corpus.v1",
        "corpus_id": "qe_fpga_representative_fixture_corpus_v1",
        "primary_workload_id": workload_rows[0]["workload_id"],
        "workloads": workload_rows,
        "representativeness_boundary": "fixture_corpus_for_pipeline_experiments_not_measured_QE_benchmark_suite",
    }
    _write_json(out_dir / "workflow_corpus.json", corpus)
    classes = sorted({role for row in workload_rows for role in row["workflow_roles"]})
    summary = {
        "schema_version": "dse.qe_fpga_representative_corpus_summary.v1",
        "corpus_id": corpus["corpus_id"],
        "workload_count": len(workload_rows),
        "workflow_class_coverage": classes,
        "materials": [row["material"] for row in workload_rows],
        "size_classes": [row["size_class"] for row in workload_rows],
        "workload_table_rows": [
            {
                "workload_id": row["workload_id"],
                "material": row["material"],
                "size_class": row["size_class"],
                "workflow_roles": row["workflow_roles"],
                "bundle_path": row["bundle_path"],
            }
            for row in workload_rows
        ],
        "representativeness_boundary": "fixture_corpus_for_pipeline_experiments_not_measured_QE_benchmark_suite",
        "limitations": [
            "stdout_logs_are_fixture_timing_records_not_raw_QE_measurements",
            "save_dirs_and_pseudopotentials_are_file_backed_fixtures",
            "requires_replacement_with_curated_measured_QE_corpus_for_DAC_results",
        ],
    }
    _write_json(out_dir / "representative_corpus_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = build_corpus(args.out)
    print(json.dumps({
        "status": "built",
        "out": str(args.out),
        "corpus_id": summary["corpus_id"],
        "workload_count": summary["workload_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
