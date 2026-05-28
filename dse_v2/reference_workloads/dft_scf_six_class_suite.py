#!/usr/bin/env python3
"""Strict six-class DFT/QE SCF descriptor-plus-runnable bundle fixtures.

The artifacts generated here make the required six-SCF workload bundle concrete:
QE input decks, pseudo references with hashes, run commands, descriptors, and a
manifest.  They are intentionally fail-closed for final QE evidence by default:
the generated pseudo files are synthetic fixtures and no real QE reference-output
hash is invented.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.release_domain import stable_json_hash
from dse_v2.codesign.dft_scf_workstreams import STRICT_DFT_QE_WORKLOAD_CLASSES
from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.reference_workloads.dft_workload_profile import (
    build_coverage_derivation_audit,
    build_layered_workload_profile,
    write_layered_workload_profile,
)

DFT_SCF_SIX_CLASS_SUITE_SCHEMA = "dse.dft_scf.six_class_descriptor_runnable_bundle.v1"
DFT_SCF_SIX_CLASS_SUITE_VALIDATION_SCHEMA = "dse.dft_scf.six_class_descriptor_runnable_bundle_validation.v1"
DFT_SCF_COVERAGE_DERIVATION_AUDIT_SCHEMA = "dse.dft_scf.coverage_derivation_audit.v1"
DFT_SCF_SIX_CLASS_SUITE_ID = "dft_scf_six_class_suite_v1"
DFT_SCF_SIX_CLASS_MANIFEST_NAME = "dft_scf_six_class_bundle_manifest.json"
DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME = "reference_output_hash_manifest.json"
DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_SCHEMA = "dse.dft_scf.reference_admission_ledger.v1"
DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME = "reference_admission_ledger.json"
DFT_SCF_SIX_CLASS_PARSER_VERSION = "dft_scf_six_class_suite.py:v1"
DEFAULT_LOCAL_PW_X = Path("/usr/bin/pw.x")
DEFAULT_LOCAL_QE_PSEUDO_DIR = Path("/usr/share/espresso/pseudo")

REQUIRED_DFT_SCF_CLASS_IDS: tuple[str, ...] = tuple(STRICT_DFT_QE_WORKLOAD_CLASSES)

SYNTHETIC_FIXTURE_PROOF_CLASS = "synthetic_descriptor_runnable_fixture_not_final_qe_evidence"
CALLER_HASH_PROVENANCE_PROOF_CLASS = "descriptor_runnable_fixture_with_caller_reference_hash_provenance_not_final_qe_evidence"
LOCAL_CONVERGED_QE_PROOF_CLASS = "descriptor_runnable_fixture_with_local_converged_qe_reference_output"
REAL_HASH_PROOF_CLASS = CALLER_HASH_PROVENANCE_PROOF_CLASS

_CLAIM_BOUNDARY = (
    "Six-SCF descriptor-plus-runnable bundle artifacts are Step1 workload input "
    "fixtures only. Generated QE input decks and synthetic pseudo placeholders "
    "make replay contracts concrete but are not final real QE numerical evidence, "
    "hardware acceleration evidence, FPGA/ASIC PPA evidence, trusted Pareto "
    "evidence, or deliverable-complete proof. Final claims require real QE "
    "reference outputs/hashes and the independent hardware evidence gates."
)

ATOMIC_MASSES_AMU: dict[str, float] = {
    "Al": 26.9815385,
    "C": 12.0107,
    "O": 15.999,
    "Se": 78.971,
    "Si": 28.0855,
    "Ti": 47.867,
    "W": 183.84,
}

PREFERRED_LOCAL_QE_PSEUDOS_BY_ELEMENT: dict[str, tuple[str, ...]] = {
    "Si": ("Si.pz-vbc.UPF",),
    "Al": ("Al.pz-vbc.UPF",),
    "C": ("C.pz-rrkjus.UPF",),
    "Ti": ("Ti.pz-sp-van_ak.UPF",),
    "O": ("O.pz-rrkjus.UPF",),
    "W": ("W_pbe_v1.2.uspp.F.UPF",),
    "Se": ("Se_pbe_v1.uspp.F.UPF",),
}


@dataclass(frozen=True)
class DftScfClassSpec:
    class_id: str
    label: str
    nat: int
    ntyp: int
    ibrav: int
    ecutwfc: int
    k_points: tuple[int, int, int]
    occupations: str
    smearing: str | None
    degauss: float | None
    nbnd: int | None
    pseudo_file: str
    conv_thr: str
    mixing_beta: float
    electron_maxstep: int | None
    stress_tags: tuple[str, ...]
    notes: str


_CLASS_SPECS: tuple[DftScfClassSpec, ...] = (
    DftScfClassSpec(
        class_id="small_multi_k_scf",
        label="Small multi-k silicon-style SCF",
        nat=2,
        ntyp=1,
        ibrav=2,
        ecutwfc=35,
        k_points=(4, 4, 4),
        occupations="fixed",
        smearing=None,
        degauss=None,
        nbnd=8,
        pseudo_file="Si.synthetic.UPF",
        conv_thr="1.0d-8",
        mixing_beta=0.7,
        electron_maxstep=None,
        stress_tags=("multi_k", "fft", "hpsi"),
        notes="Small multi-k baseline for scheduler and FFT/Hψ replay contracts.",
    ),
    DftScfClassSpec(
        class_id="metal_smearing_scf",
        label="Metallic smearing SCF",
        nat=1,
        ntyp=1,
        ibrav=3,
        ecutwfc=45,
        k_points=(8, 8, 8),
        occupations="smearing",
        smearing="marzari-vanderbilt",
        degauss=0.02,
        nbnd=12,
        pseudo_file="Al.synthetic.UPF",
        conv_thr="1.0d-8",
        mixing_beta=0.7,
        electron_maxstep=None,
        stress_tags=("smearing", "multi_k", "reductions"),
        notes="Metal/smearing control path with dense k-point/reduction pressure.",
    ),
    DftScfClassSpec(
        class_id="insulator_scf",
        label="Insulating SCF baseline",
        nat=2,
        ntyp=1,
        ibrav=4,
        ecutwfc=50,
        k_points=(6, 6, 4),
        occupations="fixed",
        smearing=None,
        degauss=None,
        nbnd=10,
        pseudo_file="C.synthetic.UPF",
        conv_thr="1.0d-8",
        mixing_beta=0.7,
        electron_maxstep=None,
        stress_tags=("insulator", "hpsi", "diagonalization_host_cost"),
        notes="Insulating fixed-occupation baseline; host diagonalization remains costed.",
    ),
    DftScfClassSpec(
        class_id="slab_vacuum_large_fft_scf",
        label="Slab/vacuum large-FFT SCF",
        nat=4,
        ntyp=2,
        ibrav=0,
        ecutwfc=30,
        k_points=(1, 1, 1),
        occupations="smearing",
        smearing="gaussian",
        degauss=0.03,
        nbnd=28,
        pseudo_file="TiO.synthetic.UPF",
        conv_thr="1.0d-6",
        mixing_beta=0.2,
        electron_maxstep=80,
        stress_tags=("large_fft", "transpose", "vacuum", "dma"),
        notes="Bounded Ti/O slab-vacuum fixture stressing FFT, transpose, and DMA paths while remaining QE-reference convergent.",
    ),
    DftScfClassSpec(
        class_id="gamma_only_supercell_scf",
        label="Gamma-only supercell SCF",
        nat=8,
        ntyp=1,
        ibrav=1,
        ecutwfc=40,
        k_points=(1, 1, 1),
        occupations="fixed",
        smearing=None,
        degauss=None,
        nbnd=20,
        pseudo_file="Si.synthetic.UPF",
        conv_thr="1.0d-8",
        mixing_beta=0.5,
        electron_maxstep=100,
        stress_tags=("gamma_only", "supercell", "memory_footprint"),
        notes="Gamma-only silicon diamond supercell fixture for memory footprint and host/device transfer accounting.",
    ),
    DftScfClassSpec(
        class_id="projector_orthogonalization_heavy_scf",
        label="Projector/orthogonalization-heavy SCF",
        nat=8,
        ntyp=1,
        ibrav=1,
        ecutwfc=35,
        k_points=(2, 2, 2),
        occupations="fixed",
        smearing=None,
        degauss=None,
        nbnd=32,
        pseudo_file="Si.synthetic.UPF",
        conv_thr="1.0d-8",
        mixing_beta=0.5,
        electron_maxstep=100,
        stress_tags=("nonlocal_projector", "orthogonalization", "gemm_gemv", "reduction"),
        notes="High-band multi-k silicon fixture stressing nonlocal projector, orthogonalization, GEMM/GEMV, and dot reductions.",
    ),
)


class DftScfSixClassBundleError(ValueError):
    """Raised when six-class descriptor bundle construction is invalid."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reference_admission_entry_id(*, class_id: str, path: str | None, sha256: str | None, status: str | None) -> str:
    return "qe_ref_" + stable_json_hash({
        "class_id": class_id,
        "path": path,
        "sha256": sha256,
        "status": status,
    })[:16]


def _with_reference_admission_marker(class_id: str, entry: Mapping[str, Any], *, source: str) -> Dict[str, Any]:
    payload = dict(entry)
    if payload.get("sha256") and payload.get("hash_final") is True:
        payload["admission_source"] = source
        payload["admission_entry_id"] = _reference_admission_entry_id(
            class_id=class_id,
            path=str(payload.get("path") or ""),
            sha256=str(payload.get("sha256") or ""),
            status=str(payload.get("status") or ""),
        )
        payload["admission_marker_authority"] = "builder_generated_local_qe_reference_entry"
    return payload


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root).as_posix())


def _read_json_mapping(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DftScfSixClassBundleError(f"{path} must contain a JSON object")
    return payload


def _pseudo_text(pseudo_file: str) -> str:
    element_hint = pseudo_file.split(".", 1)[0]
    return (
        "<UPF version=\"2.0.1\">\n"
        f"<!-- Synthetic placeholder for {element_hint}; not a physical QE pseudopotential. -->\n"
        "<PP_INFO>synthetic fixture only; not valid for numerical evidence</PP_INFO>\n"
        "</UPF>\n"
    )


def _class_elements(spec: DftScfClassSpec) -> tuple[str, ...]:
    if spec.class_id == "slab_vacuum_large_fft_scf":
        return ("Ti", "O")
    return (spec.pseudo_file.split(".", 1)[0],)


def _si_diamond_8_positions() -> list[tuple[str, float, float, float]]:
    return [
        ("Si", 0.00, 0.00, 0.00),
        ("Si", 0.25, 0.25, 0.25),
        ("Si", 0.00, 0.50, 0.50),
        ("Si", 0.25, 0.75, 0.75),
        ("Si", 0.50, 0.00, 0.50),
        ("Si", 0.75, 0.25, 0.75),
        ("Si", 0.50, 0.50, 0.00),
        ("Si", 0.75, 0.75, 0.25),
    ]


def _atomic_positions(spec: DftScfClassSpec) -> list[tuple[str, float, float, float]]:
    element = spec.pseudo_file.split(".", 1)[0]
    if spec.class_id == "slab_vacuum_large_fft_scf":
        return [
            ("Ti", 0.00, 0.00, 0.25),
            ("O", 0.50, 0.50, 0.30),
            ("Ti", 0.50, 0.00, 0.40),
            ("O", 0.00, 0.50, 0.45),
        ]
    if spec.class_id in {"gamma_only_supercell_scf", "projector_orthogonalization_heavy_scf"}:
        return _si_diamond_8_positions()
    return [(element, (index * 0.125) % 1.0, (index * 0.25) % 1.0, (index * 0.375) % 1.0) for index in range(spec.nat)]


def _atomic_species(spec: DftScfClassSpec, pseudo_by_element: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    if pseudo_by_element:
        return [(element, pseudo_by_element[element]) for element in _class_elements(spec) if element in pseudo_by_element]
    if spec.class_id == "slab_vacuum_large_fft_scf":
        return [("Ti", "TiO.synthetic.UPF"), ("O", "TiO.synthetic.UPF")]
    element = spec.pseudo_file.split(".", 1)[0]
    return [(element, spec.pseudo_file)]


def qe_input_text(spec: DftScfClassSpec, pseudo_by_element: Mapping[str, str] | None = None) -> str:
    """Return a deterministic QE pw.x input deck for ``spec``."""

    lines = [
        "&CONTROL",
        f"  calculation = 'scf',",
        f"  prefix = '{spec.class_id}',",
        "  outdir = './qe_tmp',",
        "  pseudo_dir = './pseudos',",
        "  tstress = .true.,",
        "  tprnfor = .true.,",
        "/",
        "&SYSTEM",
        f"  ibrav = {spec.ibrav},",
        f"  nat = {spec.nat},",
        f"  ntyp = {spec.ntyp},",
    ]
    if spec.ibrav != 0:
        lines.append("  celldm(1) = 10.2,")
    lines.extend([
        f"  ecutwfc = {spec.ecutwfc},",
        f"  occupations = '{spec.occupations}',",
    ])
    if spec.ibrav == 4:
        lines.append("  celldm(3) = 1.6,")
    if spec.nbnd is not None:
        lines.append(f"  nbnd = {spec.nbnd},")
    if spec.smearing is not None:
        lines.append(f"  smearing = '{spec.smearing}',")
    if spec.degauss is not None:
        lines.append(f"  degauss = {spec.degauss},")
    lines.extend([
        "/",
        "&ELECTRONS",
        f"  conv_thr = {spec.conv_thr},",
        f"  mixing_beta = {spec.mixing_beta},",
    ])
    if spec.electron_maxstep is not None:
        lines.append(f"  electron_maxstep = {spec.electron_maxstep},")
    lines.append("/")
    if spec.ibrav == 0:
        lines.extend([
            "CELL_PARAMETERS angstrom",
            "6.0 0.0 0.0",
            "0.0 6.0 0.0",
            "0.0 0.0 18.0",
        ])
    lines.append("ATOMIC_SPECIES")
    for element, pseudo in _atomic_species(spec, pseudo_by_element):
        mass = ATOMIC_MASSES_AMU.get(element, 1.0)
        lines.append(f"  {element} {mass:.6f} {pseudo}")
    lines.append("ATOMIC_POSITIONS crystal")
    for element, x, y, z in _atomic_positions(spec):
        lines.append(f"  {element} {x:.6f} {y:.6f} {z:.6f}")
    lines.extend([
        "K_POINTS automatic",
        f"  {spec.k_points[0]} {spec.k_points[1]} {spec.k_points[2]} 0 0 0",
        "",
    ])
    return "\n".join(lines)


def required_scf_class_specs() -> tuple[DftScfClassSpec, ...]:
    """Return the strict six-SCF class specs in canonical order."""

    return _CLASS_SPECS


def _required_elements() -> tuple[str, ...]:
    elements: list[str] = []
    for spec in _CLASS_SPECS:
        for element in _class_elements(spec):
            if element not in elements:
                elements.append(element)
    return tuple(elements)


def _is_candidate_pseudo_name(element: str, path: Path) -> bool:
    name = path.name
    stem_lower = name.lower()
    element_lower = element.lower()
    if not stem_lower.endswith(".upf") or not stem_lower.startswith(element_lower):
        return False
    if len(name) == len(element):
        return True
    if len(name) <= len(element):
        return False
    return name[len(element)] in {".", "_", "-"}


def _select_local_qe_pseudo(element: str, matches: Sequence[Path]) -> Path:
    matches_by_name = {path.name: path for path in matches}
    for preferred_name in PREFERRED_LOCAL_QE_PSEUDOS_BY_ELEMENT.get(element, ()):
        if preferred_name in matches_by_name:
            return matches_by_name[preferred_name]
    return sorted(matches)[0]


def discover_local_qe_pseudopotentials(
    pseudo_dir: Path = DEFAULT_LOCAL_QE_PSEUDO_DIR,
    *,
    required_elements: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Discover local QE UPF pseudopotentials by element without downloading anything.

    The discovery is intentionally conservative: a file must end in ``.UPF`` and
    start with the element symbol followed by a separator.  Missing elements are
    reported explicitly so callers can remain fail-closed instead of fabricating
    pseudos or hashes.
    """

    root = Path(pseudo_dir)
    elements = tuple(required_elements or _required_elements())
    found: dict[str, Dict[str, Any]] = {}
    candidates: list[Path] = []
    if root.is_dir():
        candidates = sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".upf")
    for element in elements:
        matches = [path for path in candidates if _is_candidate_pseudo_name(element, path)]
        if not matches:
            continue
        selected = _select_local_qe_pseudo(element, matches)
        found[element] = {
            "element": element,
            "path": str(selected),
            "file_name": selected.name,
            "sha256": sha256_file(selected),
            "hash_algorithm": "sha256",
        }
    missing = [element for element in elements if element not in found]
    return {
        "schema_version": "dse.dft_scf.local_qe_pseudopotential_discovery.v1",
        "pseudo_dir": str(root),
        "default_pseudo_dir": str(DEFAULT_LOCAL_QE_PSEUDO_DIR),
        "available": root.is_dir(),
        "required_elements": list(elements),
        "found_elements": sorted(found),
        "missing_elements": missing,
        "complete": not missing,
        "pseudopotentials": found,
    }


def _reference_output_entry(class_id: str, reference_output_hashes: Mapping[str, Any] | None) -> Dict[str, Any]:
    raw_hash = None if reference_output_hashes is None else reference_output_hashes.get(class_id)
    raw_entry = raw_hash if isinstance(raw_hash, Mapping) else {}
    if isinstance(raw_hash, Mapping):
        raw_hash = raw_hash.get("sha256") or raw_hash.get("hash")
    if raw_hash:
        hash_value = str(raw_hash)
        if hash_value.startswith("sha256:"):
            hash_value = hash_value.split(":", 1)[1]
        output_path = None
        status = "real_qe_reference_output_hash_provided_by_caller"
        if raw_entry:
            output_path = raw_entry.get("path")
            status = str(raw_entry.get("status") or status)
        has_builder_admission_marker = (
            raw_entry.get("admission_source") in {"local_qe_reference_run", "reused_existing_local_qe_output"}
            and _non_empty(raw_entry.get("admission_entry_id"))
            and raw_entry.get("admission_marker_authority") == "builder_generated_local_qe_reference_entry"
        )
        source_backed_local = status in {
            "local_pw_x_reference_output_hash_from_converged_scf_run",
            "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
        } and has_builder_admission_marker
        entry = {
            "path": output_path,
            "sha256": hash_value,
            "hash_algorithm": "sha256",
            "status": status,
            "hash_final": bool(raw_entry.get("hash_final") is True and source_backed_local),
            "required_for_final_claim": True,
            "provenance_hash_only": not source_backed_local,
            "final_admission_eligible": bool(raw_entry.get("hash_final") is True and source_backed_local),
        }
        if not source_backed_local:
            entry["claim_boundary"] = (
                "Caller-supplied or external reference-output hashes are provenance only. "
                "Final real-QE admission requires a converged local/reused output file under this bundle."
            )
        for optional_key in (
            "command",
            "returncode",
            "job_done",
            "scf_converged",
            "reused_existing_output",
            "diagnostic_output_sha256",
            "missing_markers",
            "claim_boundary",
            "admission_source",
            "admission_entry_id",
            "admission_marker_authority",
        ):
            if optional_key in raw_entry:
                entry[optional_key] = raw_entry[optional_key]
        return entry
    entry = {
        "path": raw_entry.get("path") if raw_entry else None,
        "sha256": None,
        "hash_algorithm": "sha256",
        "status": str(raw_entry.get("status") or "missing_real_qe_reference_output_hash_fail_closed") if raw_entry else "missing_real_qe_reference_output_hash_fail_closed",
        "hash_final": False,
        "required_for_final_claim": True,
        "provenance_hash_only": bool(raw_entry),
        "final_admission_eligible": False,
        "claim_boundary": "No placeholder reference-output hash is fabricated; final QE evidence remains blocked.",
    }
    for optional_key in (
        "command",
        "returncode",
        "job_done",
        "scf_converged",
        "reused_existing_output",
        "diagnostic_output_sha256",
        "missing_markers",
    ):
        if optional_key in raw_entry:
            entry[optional_key] = raw_entry[optional_key]
    return entry


def _write_reference_output_hash_manifest(
    out_root: Path,
    entries_by_class: Mapping[str, Any],
    *,
    qe_command: str,
) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []
    for class_id in REQUIRED_DFT_SCF_CLASS_IDS:
        raw_entry = entries_by_class.get(class_id, {})
        if isinstance(raw_entry, Mapping):
            entry = dict(raw_entry)
        else:
            entry = {"sha256": raw_entry} if raw_entry else {}
        if entry.get("sha256") and str(entry["sha256"]).startswith("sha256:"):
            entry["sha256"] = str(entry["sha256"]).split(":", 1)[1]
        manifest_entry = {
            "class_id": class_id,
            "path": entry.get("path"),
            "sha256": entry.get("sha256"),
            "hash_algorithm": "sha256",
            "status": entry.get(
                "status",
                "real_qe_reference_output_hash_provided_by_caller"
                if entry.get("sha256")
                else "missing_real_qe_reference_output_hash_fail_closed",
            ),
        }
        has_builder_admission_marker = (
            entry.get("admission_source") in {"local_qe_reference_run", "reused_existing_local_qe_output"}
            and _non_empty(entry.get("admission_entry_id"))
            and entry.get("admission_marker_authority") == "builder_generated_local_qe_reference_entry"
        )
        source_backed_local = manifest_entry["status"] in {
            "local_pw_x_reference_output_hash_from_converged_scf_run",
            "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
        } and has_builder_admission_marker
        manifest_entry["hash_final"] = bool(entry.get("sha256") and entry.get("hash_final") is True and source_backed_local)
        manifest_entry["provenance_hash_only"] = bool(entry.get("sha256") and not source_backed_local)
        manifest_entry["final_admission_eligible"] = bool(manifest_entry["hash_final"] and source_backed_local)
        for optional_key in (
            "command",
            "returncode",
            "job_done",
            "scf_converged",
            "reused_existing_output",
            "diagnostic_output_sha256",
            "missing_markers",
            "claim_boundary",
            "admission_source",
            "admission_entry_id",
            "admission_marker_authority",
        ):
            if optional_key in entry:
                manifest_entry[optional_key] = entry[optional_key]
        entries.append(manifest_entry)
    manifest = {
        "schema_version": "dse.dft_scf.reference_output_hash_manifest.v1",
        "suite_id": DFT_SCF_SIX_CLASS_SUITE_ID,
        "qe_command": qe_command,
        "entry_count": len(entries),
        "complete": all(entry["sha256"] for entry in entries),
        "final_admission_complete": all(entry["final_admission_eligible"] for entry in entries),
        "entries": entries,
        "claim_boundary": (
            "Hashes are recorded only for local converged outputs or caller-supplied provenance entries. "
            "Caller hash-only entries are not final real-QE evidence."
        ),
    }
    write_json(out_root / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME, manifest)
    return manifest


def _reference_admission_blocker_ids(reference_output: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not reference_output.get("sha256"):
        blockers.append("missing_real_reference_output_hash")
    elif reference_output.get("hash_final") is not True:
        blockers.append("reference_output_hash_not_final")
    if reference_output.get("status") not in {
        "local_pw_x_reference_output_hash_from_converged_scf_run",
        "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
    }:
        blockers.append("reference_output_not_local_converged_qe_source")
    if reference_output.get("job_done") is not True or reference_output.get("scf_converged") is not True:
        blockers.append("reference_output_convergence_markers_not_verified")
    if reference_output.get("admission_source") not in {"local_qe_reference_run", "reused_existing_local_qe_output"}:
        blockers.append("reference_output_missing_builder_admission_marker")
    if not _non_empty(reference_output.get("admission_entry_id")):
        blockers.append("reference_output_missing_builder_admission_marker")
    if reference_output.get("admission_marker_authority") != "builder_generated_local_qe_reference_entry":
        blockers.append("reference_output_admission_marker_not_builder_owned")
    return sorted(set(blockers))


def _reference_admission_ledger_entry_from_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    class_id = str(case.get("class_id") or case.get("workload_class") or "")
    reference_output = case.get("reference_output") if isinstance(case.get("reference_output"), Mapping) else {}
    workload_analysis = case.get("dft_workload_analysis") if isinstance(case.get("dft_workload_analysis"), Mapping) else {}
    reference_summary = (
        workload_analysis.get("reference_summary")
        if isinstance(workload_analysis.get("reference_summary"), Mapping)
        else {}
    )
    admitted = _is_local_converged_reference_entry(reference_output)
    expected_admission_entry_id = None
    if reference_output.get("sha256") and reference_output.get("hash_final") is True:
        expected_admission_entry_id = _reference_admission_entry_id(
            class_id=class_id,
            path=str(reference_output.get("path") or ""),
            sha256=str(reference_output.get("sha256") or ""),
            status=str(reference_output.get("status") or ""),
        )
    return {
        "schema_version": "dse.dft_scf.reference_admission_ledger.entry.v1",
        "class_id": class_id,
        "case_id": case.get("case_id"),
        "reference_output_path": reference_output.get("path"),
        "reference_output_sha256": reference_output.get("sha256"),
        "hash_algorithm": "sha256",
        "status": reference_output.get("status"),
        "hash_final": bool(reference_output.get("hash_final") is True),
        "job_done": bool(reference_output.get("job_done") is True),
        "scf_converged": bool(reference_output.get("scf_converged") is True),
        "admission_source": reference_output.get("admission_source"),
        "admission_entry_id": reference_output.get("admission_entry_id"),
        "expected_admission_entry_id": expected_admission_entry_id,
        "admission_marker_authority": reference_output.get("admission_marker_authority"),
        "admitted": bool(admitted),
        "fail_closed": not admitted,
        "blocker_ids": [] if admitted else _reference_admission_blocker_ids(reference_output),
        "source_case_reference_output": f"cases.{class_id}.reference_output",
        "source_workload_profile_path": (
            case.get("workload_profile", {}).get("path")
            if isinstance(case.get("workload_profile"), Mapping)
            else None
        ),
        "normalized_reference_summary_hash": (
            reference_summary.get("normalized_reference_summary_hash")
            if isinstance(reference_summary, Mapping)
            else None
        ),
        "raw_output_sha256": reference_summary.get("raw_output_sha256") if isinstance(reference_summary, Mapping) else None,
    }


def _write_reference_admission_ledger(
    out_root: Path,
    cases: Sequence[Mapping[str, Any]],
    *,
    bundle_id: str,
    qe_command: str,
    reference_hash_manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    entries = [_reference_admission_ledger_entry_from_case(case) for case in cases]
    entries_by_class = {entry["class_id"]: entry for entry in entries}
    admitted_class_ids = [
        class_id
        for class_id in REQUIRED_DFT_SCF_CLASS_IDS
        if entries_by_class.get(class_id, {}).get("admitted") is True
    ]
    ledger = {
        "schema_version": DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_SCHEMA,
        "suite_id": DFT_SCF_SIX_CLASS_SUITE_ID,
        "bundle_id": bundle_id,
        "qe_command": qe_command,
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "entry_count": len(entries),
        "admitted_class_ids": admitted_class_ids,
        "missing_class_ids": [
            class_id for class_id in REQUIRED_DFT_SCF_CLASS_IDS if class_id not in {entry["class_id"] for entry in entries}
        ],
        "reference_output_hash_manifest": {
            "path": DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME,
            "sha256": sha256_file(out_root / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME),
            "hash_algorithm": "sha256",
            "final_admission_complete": bool(reference_hash_manifest.get("final_admission_complete") is True),
        },
        "final_admission_complete": all(entry["admitted"] for entry in entries)
        and len(entries) == len(REQUIRED_DFT_SCF_CLASS_IDS),
        "entries": entries,
        "fail_closed_policy": {
            "missing_ledger_blocks_admission": True,
            "tampered_ledger_blocks_admission": True,
            "stale_ledger_blocks_admission": True,
            "external_or_caller_hashes_are_provenance_only": True,
            "requires_local_bundle_output_file": True,
            "requires_job_done_and_scf_convergence_markers": True,
            "requires_normalized_reference_summary_hash_match": True,
        },
        "claim_boundary": (
            "This ledger is the canonical admission record for final real-QE reference outputs. "
            "Admission fails closed unless each entry matches the manifest case, hash manifest, "
            "local/reused bundle output file, convergence markers, and normalized reference summary."
        ),
    }
    write_json(out_root / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME, ledger)
    return ledger


def _is_local_converged_reference_entry(reference_output: Mapping[str, Any]) -> bool:
    return bool(
        reference_output.get("sha256")
        and reference_output.get("hash_final") is True
        and reference_output.get("status")
        in {
            "local_pw_x_reference_output_hash_from_converged_scf_run",
            "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
        }
        and reference_output.get("admission_source") in {"local_qe_reference_run", "reused_existing_local_qe_output"}
        and _non_empty(reference_output.get("admission_entry_id"))
        and reference_output.get("admission_marker_authority") == "builder_generated_local_qe_reference_entry"
        and reference_output.get("job_done") is True
        and reference_output.get("scf_converged") is True
    )


def _proof_class_for_reference_output(reference_output: Mapping[str, Any]) -> str:
    if _is_local_converged_reference_entry(reference_output):
        return LOCAL_CONVERGED_QE_PROOF_CLASS
    if reference_output.get("sha256"):
        return CALLER_HASH_PROVENANCE_PROOF_CLASS
    return SYNTHETIC_FIXTURE_PROOF_CLASS


def _run_local_qe_reference(
    *,
    class_id: str,
    out_root: Path,
    input_rel: str,
    output_rel: str,
    pw_x: Path,
    timeout_seconds: int,
    reuse_existing_output: bool = False,
) -> Dict[str, Any]:
    if not pw_x.is_file() or not pw_x.exists():
        return {
            "path": output_rel,
            "sha256": None,
            "status": "local_pw_x_not_available_fail_closed",
            "hash_final": False,
            "command": [str(pw_x), "-in", input_rel],
        }
    output_path = out_root / output_rel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    (out_root / "qe_tmp").mkdir(parents=True, exist_ok=True)
    command = [str(pw_x), "-in", input_rel]
    if reuse_existing_output and output_path.is_file():
        output_text = output_path.read_text(encoding="utf-8", errors="replace")
        job_done = "JOB DONE" in output_text
        scf_converged = "convergence has been achieved" in output_text
        if job_done and scf_converged:
            return _with_reference_admission_marker(class_id, {
                "path": output_rel,
                "sha256": sha256_file(output_path),
                "hash_algorithm": "sha256",
                "status": "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
                "hash_final": True,
                "required_for_final_claim": True,
                "command": command,
                "returncode": 0,
                "job_done": True,
                "scf_converged": True,
                "reused_existing_output": True,
            }, source="reused_existing_local_qe_output")
    try:
        with output_path.open("w", encoding="utf-8") as stdout:
            completed = subprocess.run(
                command,
                cwd=out_root,
                check=False,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
            )
    except OSError as exc:
        return {
            "path": output_rel,
            "sha256": None,
            "status": "local_pw_x_run_failed_fail_closed",
            "hash_final": False,
            "command": command,
            "error": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "path": output_rel,
            "sha256": None,
            "status": "local_pw_x_run_timed_out_fail_closed",
            "hash_final": False,
            "command": command,
            "timeout_seconds": timeout_seconds,
            "diagnostic_output_sha256": sha256_file(output_path) if output_path.is_file() else None,
        }
    if completed.returncode != 0:
        return {
            "path": output_rel,
            "sha256": None,
            "status": "local_pw_x_run_failed_fail_closed",
            "hash_final": False,
            "command": command,
            "returncode": completed.returncode,
            "stderr_tail": completed.stderr[-2000:],
        }
    output_text = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    job_done = "JOB DONE" in output_text
    scf_converged = "convergence has been achieved" in output_text
    output_sha256 = sha256_file(output_path)
    if not (job_done and scf_converged):
        missing = []
        if not job_done:
            missing.append("qe_job_done_marker_missing")
        if not scf_converged:
            missing.append("qe_scf_convergence_marker_missing")
        return {
            "path": output_rel,
            "sha256": None,
            "diagnostic_output_sha256": output_sha256,
            "hash_algorithm": "sha256",
            "status": "local_pw_x_run_completed_without_verified_scf_convergence_fail_closed",
            "hash_final": False,
            "required_for_final_claim": True,
            "command": command,
            "returncode": 0,
            "job_done": job_done,
            "scf_converged": scf_converged,
            "missing_markers": missing,
            "claim_boundary": (
                "A zero QE return code is not sufficient reference evidence; "
                "SCF reference hashes are final only when JOB DONE and convergence markers are both present."
            ),
        }
    return _with_reference_admission_marker(class_id, {
        "path": output_rel,
        "sha256": output_sha256,
        "hash_algorithm": "sha256",
        "status": "local_pw_x_reference_output_hash_from_converged_scf_run",
        "hash_final": True,
        "required_for_final_claim": True,
        "command": command,
        "returncode": 0,
        "job_done": True,
        "scf_converged": True,
    }, source="local_qe_reference_run")


def build_dft_scf_six_class_bundle_manifest(
    *,
    out_dir: Path,
    bundle_id: str = "dft-scf-six-class-descriptor-runnable-bundle",
    campaign_id: str = "dft-scf-hardware-dse",
    workload_run_id: str = DFT_SCF_SIX_CLASS_SUITE_ID,
    qe_command: str = "pw.x",
    reference_output_hashes: Mapping[str, Any] | None = None,
    use_local_pseudos: bool = False,
    local_pseudo_dir: Path = DEFAULT_LOCAL_QE_PSEUDO_DIR,
    run_local_qe: bool = False,
    local_pw_x: Path = DEFAULT_LOCAL_PW_X,
    qe_run_timeout_seconds: int = 300,
    reuse_existing_qe_outputs: bool = False,
) -> Dict[str, Any]:
    """Materialize the six descriptors, QE inputs, pseudo refs, run scripts, and manifest."""

    out_root = Path(out_dir)
    local_pw_x = Path(local_pw_x).expanduser()
    if run_local_qe:
        local_pw_x = local_pw_x.resolve(strict=False)
    qe_input_dir = out_root / "qe_inputs"
    pseudo_dir = out_root / "pseudos"
    descriptor_dir = out_root / "descriptors"
    run_script_dir = out_root / "run_scripts"
    reference_output_dir = out_root / "reference_outputs"
    workload_profile_dir = out_root / "workload_profiles"
    for directory in (qe_input_dir, pseudo_dir, descriptor_dir, run_script_dir, reference_output_dir, workload_profile_dir):
        directory.mkdir(parents=True, exist_ok=True)

    local_qe_asset_discovery = discover_local_qe_pseudopotentials(local_pseudo_dir) if use_local_pseudos or run_local_qe else None
    discovered_pseudos = (
        local_qe_asset_discovery["pseudopotentials"] if isinstance(local_qe_asset_discovery, Mapping) else {}
    )
    local_qe_run_entries: dict[str, Dict[str, Any]] = {}
    pseudo_cache: dict[str, Dict[str, Any]] = {}
    cases: list[Dict[str, Any]] = []
    for spec in _CLASS_SPECS:
        required_elements = _class_elements(spec)
        discovered_for_case = {
            element: discovered_pseudos[element]["file_name"]
            for element in required_elements
            if element in discovered_pseudos
        }
        use_real_pseudos_for_case = (use_local_pseudos or run_local_qe) and set(discovered_for_case) == set(required_elements)
        pseudo_by_element = discovered_for_case if use_real_pseudos_for_case else None
        input_text = qe_input_text(spec, pseudo_by_element=pseudo_by_element)
        input_path = qe_input_dir / f"{spec.class_id}.in"
        input_path.write_text(input_text, encoding="utf-8")

        pseudo_refs: list[Dict[str, Any]] = []
        if use_real_pseudos_for_case:
            for element in required_elements:
                discovered = discovered_pseudos[element]
                pseudo_file = str(discovered["file_name"])
                pseudo_path = pseudo_dir / pseudo_file
                if pseudo_file not in pseudo_cache:
                    pseudo_path.write_bytes(Path(str(discovered["path"])).read_bytes())
                    pseudo_cache[pseudo_file] = {
                        "file_name": pseudo_file,
                        "element": element,
                        "path": _rel(pseudo_path, out_root),
                        "sha256": sha256_file(pseudo_path),
                        "hash_algorithm": "sha256",
                        "source": "local_qe_pseudopotential",
                        "source_path": str(discovered["path"]),
                        "license": "external-local-qe-installation-license-not-redistributed-upstream",
                        "physical_validity": "local_qe_pseudopotential_unverified_by_builder",
                        "final_evidence_eligible": True,
                    }
                pseudo_refs.append(dict(pseudo_cache[pseudo_file]))
        else:
            pseudo_path = pseudo_dir / spec.pseudo_file
            if spec.pseudo_file not in pseudo_cache:
                pseudo_path.write_text(_pseudo_text(spec.pseudo_file), encoding="utf-8")
                pseudo_cache[spec.pseudo_file] = {
                    "file_name": spec.pseudo_file,
                    "path": _rel(pseudo_path, out_root),
                    "sha256": sha256_file(pseudo_path),
                    "hash_algorithm": "sha256",
                    "source": "generated_synthetic_placeholder",
                    "license": "synthetic-fixture-only-no-external-pseudopotential-license",
                    "physical_validity": "not_a_real_qe_pseudopotential",
                    "final_evidence_eligible": False,
                }
            pseudo_refs.append(dict(pseudo_cache[spec.pseudo_file]))

        run_script_path = run_script_dir / f"run_{spec.class_id}.sh"
        qe_input_rel = _rel(input_path, out_root)
        output_rel = f"reference_outputs/{spec.class_id}.out"
        run_qe_command = str(local_pw_x) if run_local_qe else qe_command
        run_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "ROOT=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)\"\n"
            "cd \"$ROOT\"\n"
            "mkdir -p qe_tmp reference_outputs\n"
            f"${{QE_PW_CMD:-{shlex.quote(run_qe_command)}}} -in {shlex.quote(qe_input_rel)} > {shlex.quote(output_rel)}\n"
        )
        run_script_path.write_text(run_script, encoding="utf-8")
        run_script_path.chmod(run_script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        if run_local_qe:
            if use_real_pseudos_for_case:
                local_qe_run_entries[spec.class_id] = _run_local_qe_reference(
                    class_id=spec.class_id,
                    out_root=out_root,
                    input_rel=qe_input_rel,
                    output_rel=output_rel,
                    pw_x=Path(local_pw_x),
                    timeout_seconds=qe_run_timeout_seconds,
                    reuse_existing_output=reuse_existing_qe_outputs,
                )
            else:
                local_qe_run_entries[spec.class_id] = {
                    "path": output_rel,
                    "sha256": None,
                    "status": "local_pw_x_run_not_attempted_missing_real_pseudos_fail_closed",
                    "hash_final": False,
                    "missing_pseudo_elements": [element for element in required_elements if element not in discovered_pseudos],
                }

        active_reference_hashes = local_qe_run_entries if run_local_qe else reference_output_hashes
        reference_output = _reference_output_entry(spec.class_id, active_reference_hashes)
        proof_class = _proof_class_for_reference_output(reference_output)
        case_final_real_qe_evidence = _is_local_converged_reference_entry(reference_output)
        pseudo_hashes = {str(pseudo["file_name"]): pseudo["sha256"] for pseudo in pseudo_refs}
        run_command = ["bash", _rel(run_script_path, out_root)]
        profile = build_layered_workload_profile(
            class_id=spec.class_id,
            qe_input_text=input_text,
            qe_input_path=qe_input_rel,
            qe_input_sha256=sha256_file(input_path),
            pseudo_refs=pseudo_refs,
            run_command=run_command,
            reference_output=reference_output,
            output_path=out_root / output_rel,
            stress_tags=spec.stress_tags,
            parser_version=DFT_SCF_SIX_CLASS_PARSER_VERSION,
            proof_class=proof_class,
        )
        profile_path = workload_profile_dir / f"{spec.class_id}_workload_profile.json"
        profile_ref = write_layered_workload_profile(profile_path, profile)
        coverage_derivation_audit = build_coverage_derivation_audit(profile["coverage_vector"])
        descriptor: Dict[str, Any] = {
            "schema_version": "dse.dft_scf.six_class_case_descriptor.v1",
            "suite_id": DFT_SCF_SIX_CLASS_SUITE_ID,
            "case_id": f"{spec.class_id}_case",
            "class_id": spec.class_id,
            "workload_class": spec.class_id,
            "label": spec.label,
            "qe_input": {
                "path": qe_input_rel,
                "sha256": sha256_file(input_path),
                "hash_algorithm": "sha256",
                "generated": True,
                "text_sha256": _sha256_text(input_text),
                "text": input_text,
            },
            "pseudo_refs": [dict(pseudo) for pseudo in pseudo_refs],
            "pseudopotentials": [dict(pseudo) for pseudo in pseudo_refs],
            "pseudopotential_hashes": pseudo_hashes,
            "run_command": run_command,
            "qe_command_template": ["${QE_PW_CMD:-" + run_qe_command + "}", "-in", qe_input_rel],
            "reference_output": reference_output,
            "reference_output_hash": reference_output["sha256"],
            "workload_profile": profile_ref,
            "coverage_derivation_audit": coverage_derivation_audit,
            "dft_workload_analysis": {
                "layer_order": list(profile["layer_order"]),
                "raw_input_facts": profile["raw_input_facts"],
                "resolved_run_facts": profile["resolved_run_facts"],
                "derived_scale_features": profile["derived_scale_features"],
                "coverage_vector": profile["coverage_vector"],
                "coverage_derivation_audit": coverage_derivation_audit,
                "kernel_workload_graph": profile["kernel_workload_graph"],
                "reference_summary": profile["reference_summary"],
                "claim_boundary": profile["claim_boundary"],
            },
            "provenance": {
                "source": "generated_by_dse_v2.reference_workloads.dft_scf_six_class_suite",
                "suite_builder": DFT_SCF_SIX_CLASS_PARSER_VERSION,
                "fixture_kind": "local_qe_reference_fixture" if use_real_pseudos_for_case else "synthetic_reference_fixture",
                "notes": spec.notes,
            },
            "license": {
                "input_deck": "synthetic-fixture-only",
                "pseudo_refs": "external-local-qe-installation-license-not-redistributed-upstream"
                if use_real_pseudos_for_case
                else "synthetic-fixture-only-no-external-pseudopotential-license",
                "redistribution": "repository-test-fixture",
            },
            "parser_version": DFT_SCF_SIX_CLASS_PARSER_VERSION,
            "parser_tool_version": DFT_SCF_SIX_CLASS_PARSER_VERSION,
            "proof_class": proof_class,
            "stress_tags": list(spec.stress_tags),
            "suite_intent_tags": list(spec.stress_tags),
            "final_real_qe_evidence": case_final_real_qe_evidence,
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        descriptor_path = descriptor_dir / f"{spec.class_id}_descriptor.json"
        write_json(descriptor_path, descriptor)
        descriptor_ref = {
            "path": _rel(descriptor_path, out_root),
            "sha256": sha256_file(descriptor_path),
            "hash_algorithm": "sha256",
        }
        cases.append({**descriptor, "descriptor": descriptor_ref})

    active_reference_hashes = local_qe_run_entries if run_local_qe else reference_output_hashes or {}
    reference_hash_manifest = _write_reference_output_hash_manifest(
        out_root,
        active_reference_hashes,
        qe_command=str(local_pw_x) if run_local_qe else qe_command,
    )
    reference_hash_manifest_ref = {
        "path": DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME,
        "sha256": sha256_file(out_root / DFT_SCF_SIX_CLASS_REFERENCE_HASH_MANIFEST_NAME),
        "hash_algorithm": "sha256",
        "complete": reference_hash_manifest["complete"],
    }
    reference_admission_ledger = _write_reference_admission_ledger(
        out_root,
        cases,
        bundle_id=bundle_id,
        qe_command=str(local_pw_x) if run_local_qe else qe_command,
        reference_hash_manifest=reference_hash_manifest,
    )
    reference_admission_ledger_ref = {
        "path": DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME,
        "sha256": sha256_file(out_root / DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_NAME),
        "hash_algorithm": "sha256",
        "schema_version": reference_admission_ledger["schema_version"],
        "final_admission_complete": reference_admission_ledger["final_admission_complete"],
    }

    coverage_derivation_audit = _suite_coverage_derivation_audit(cases)

    coverage_derivation_audit = _suite_coverage_derivation_audit(cases)

    coverage_derivation_audit = _suite_coverage_derivation_audit(cases)

    coverage_derivation_audit = _suite_coverage_derivation_audit(cases)

    manifest: Dict[str, Any] = {
        "schema_version": DFT_SCF_SIX_CLASS_SUITE_SCHEMA,
        "bundle_id": bundle_id,
        "suite_id": DFT_SCF_SIX_CLASS_SUITE_ID,
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "strict": True,
        "descriptor_plus_runnable_bundle": True,
        "workload_analysis_model": {
            "schema_version": "dse.dft.six_class_workload_analysis_model.v1",
            "profile_schema_version": "dse.dft.workload_profile.layered.v1",
            "layer_order": [
                "source_bundle",
                "raw_input_facts",
                "resolved_run_facts",
                "derived_scale_features",
                "coverage_vector",
                "kernel_workload_graph",
                "reference_suite_case",
            ],
            "reference_suite_role": "reference_suite_v1_regression_search_calibration_seed",
            "claim_boundary": (
                "The six classes are a DFT reference suite selection. They are not "
                "the workload analyzer itself, not architecture candidate identity, "
                "and not evaluation/release policy."
            ),
        },
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "workload_classes": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "case_count": len(cases),
        "cases": cases,
        "coverage_derivation_audit": coverage_derivation_audit,
        "manifest_path": DFT_SCF_SIX_CLASS_MANIFEST_NAME,
        "reference_output_hash_manifest": reference_hash_manifest_ref,
        "reference_admission_ledger": reference_admission_ledger_ref,
        "local_qe_asset_discovery": local_qe_asset_discovery
        or {
            "schema_version": "dse.dft_scf.local_qe_pseudopotential_discovery.v1",
            "pseudo_dir": str(local_pseudo_dir),
            "default_pseudo_dir": str(DEFAULT_LOCAL_QE_PSEUDO_DIR),
            "available": False,
            "required_elements": list(_required_elements()),
            "found_elements": [],
            "missing_elements": list(_required_elements()),
            "complete": False,
            "pseudopotentials": {},
            "not_attempted": True,
        },
        "local_qe_reference_run": {
            "attempted": bool(run_local_qe),
            "pw_x": str(local_pw_x),
            "default_pw_x": str(DEFAULT_LOCAL_PW_X),
            "timeout_seconds": qe_run_timeout_seconds,
            "reuse_existing_outputs": bool(reuse_existing_qe_outputs),
            "complete": bool(run_local_qe and reference_hash_manifest["complete"]),
            "entries": local_qe_run_entries,
        },
        "provenance": {
            "source": "generated_by_build_dft_scf_six_class_bundle.py",
            "parser_version": DFT_SCF_SIX_CLASS_PARSER_VERSION,
            "fixture_kind": "local_qe_reference_fixture" if (use_local_pseudos or run_local_qe) else "synthetic_reference_fixture",
        },
        "license": {
            "fixture_material": "synthetic-fixture-only",
            "external_pseudopotentials": "copied_from_local_qe_installation"
            if (use_local_pseudos or run_local_qe)
            else "none_included",
        },
        "parser_version": DFT_SCF_SIX_CLASS_PARSER_VERSION,
        "proof_class": (
            LOCAL_CONVERGED_QE_PROOF_CLASS
            if run_local_qe
            and all(_is_local_converged_reference_entry(_reference_output_entry(spec.class_id, local_qe_run_entries)) for spec in _CLASS_SPECS)
            else CALLER_HASH_PROVENANCE_PROOF_CLASS
            if reference_output_hashes
            and all(_reference_output_entry(spec.class_id, reference_output_hashes)["sha256"] for spec in _CLASS_SPECS)
            else SYNTHETIC_FIXTURE_PROOF_CLASS
        ),
        "final_real_qe_evidence": False,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    validation = validate_dft_scf_six_class_bundle_manifest(manifest, base_dir=out_root)
    manifest["validation"] = validation
    manifest["status"] = validation["status"]
    manifest["admitted"] = validation["admitted"]
    manifest["blocker_count"] = len(validation["blockers"])
    manifest["final_real_qe_evidence"] = validation["final_real_qe_evidence"]
    write_json(out_root / DFT_SCF_SIX_CLASS_MANIFEST_NAME, manifest)
    return manifest


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, Mapping):
        return bool(value)
    return True


def _suite_coverage_derivation_audit(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    case_audits: dict[str, Dict[str, Any]] = {}
    missing_coverage_cases: list[str] = []
    for index, case in enumerate(cases):
        class_id = str(case.get("class_id") or case.get("workload_class") or f"case_{index}")
        workload_analysis = case.get("dft_workload_analysis") if isinstance(case.get("dft_workload_analysis"), Mapping) else {}
        coverage = workload_analysis.get("coverage_vector") if isinstance(workload_analysis, Mapping) else None
        if not isinstance(coverage, Mapping):
            missing_coverage_cases.append(class_id)
            continue
        case_audits[class_id] = build_coverage_derivation_audit(coverage)

    cases_without_non_tag_derivation = sorted(
        class_id
        for class_id, audit in case_audits.items()
        if audit.get("all_required_gates_have_non_tag_derivation") is not True
    )
    cases_with_stress_tag_authority = sorted(
        class_id
        for class_id, audit in case_audits.items()
        if audit.get("stress_tags_used_for_gate_authority") is True
    )
    return {
        "schema_version": DFT_SCF_COVERAGE_DERIVATION_AUDIT_SCHEMA,
        "all_required_gates_have_non_tag_derivation": (
            not missing_coverage_cases
            and not cases_without_non_tag_derivation
            and len(case_audits) == len(cases)
        ),
        "stress_tags_used_for_gate_authority": bool(cases_with_stress_tag_authority),
        "case_count": len(cases),
        "audited_case_count": len(case_audits),
        "case_ids": sorted(case_audits),
        "missing_coverage_cases": sorted(missing_coverage_cases),
        "cases_without_non_tag_derivation": cases_without_non_tag_derivation,
        "cases_with_stress_tag_authority": cases_with_stress_tag_authority,
        "case_audits": case_audits,
        "recomputed_from": ["cases[].dft_workload_analysis.coverage_vector"],
        "claim_boundary": (
            "Suite coverage derivation audit is recomputed from case coverage vectors. "
            "Stress tags are display-only suite intent and cannot authorize required gates."
        ),
    }


def _path_ref_valid(ref: Mapping[str, Any], *, base_dir: Path, field: str, blockers: list[Dict[str, Any]]) -> None:
    rel_path = str(ref.get("path") or "")
    if not rel_path:
        blockers.append({"id": "missing_path_ref", "field": field, "reason": "path ref is required"})
        return
    path = base_dir / rel_path
    if not path.is_file():
        blockers.append({"id": "missing_artifact_file", "field": field, "path": rel_path, "reason": "referenced file is absent"})
        return
    actual = sha256_file(path)
    expected = str(ref.get("sha256") or "")
    if expected != actual:
        blockers.append({"id": "artifact_hash_mismatch", "field": field, "path": rel_path, "expected": expected, "actual": actual})


def _bundle_relative_existing_file(path_value: Any, *, base_dir: Path) -> Path | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    candidate = Path(path_value)
    if candidate.is_absolute():
        return None
    root = base_dir.resolve()
    path = (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def _reference_hash_manifest_entries(payload: Mapping[str, Any], *, base_dir: Path) -> Dict[str, Dict[str, Any]]:
    ref = payload.get("reference_output_hash_manifest")
    if not isinstance(ref, Mapping):
        return {}
    path = _bundle_relative_existing_file(ref.get("path"), base_dir=base_dir)
    if path is None:
        return {}
    try:
        manifest = _read_json_mapping(path)
    except (OSError, json.JSONDecodeError, DftScfSixClassBundleError):
        return {}
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        return {}
    return {
        str(entry.get("class_id")): dict(entry)
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("class_id")
    }


def _reference_admission_ledger_entries(
    payload: Mapping[str, Any],
    *,
    base_dir: Path,
    blockers: list[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    ref = payload.get("reference_admission_ledger")
    if not isinstance(ref, Mapping):
        blockers.append({
            "id": "missing_reference_admission_ledger_ref",
            "field": "reference_admission_ledger",
            "reason": "final reference admission must be mediated by the canonical ledger",
        })
        return {}
    rel_path = str(ref.get("path") or "")
    if not rel_path:
        blockers.append({
            "id": "missing_reference_admission_ledger_ref",
            "field": "reference_admission_ledger.path",
            "reason": "canonical reference admission ledger path is required",
        })
        return {}
    path = _bundle_relative_existing_file(rel_path, base_dir=base_dir)
    if path is None:
        blockers.append({
            "id": "missing_reference_admission_ledger",
            "field": "reference_admission_ledger.path",
            "path": rel_path,
            "reason": "canonical reference_admission_ledger.json is absent or not bundle-relative",
        })
        return {}
    actual_hash = sha256_file(path)
    expected_hash = str(ref.get("sha256") or "")
    if actual_hash != expected_hash:
        blockers.append({
            "id": "reference_admission_ledger_hash_mismatch",
            "field": "reference_admission_ledger.sha256",
            "path": rel_path,
            "expected": expected_hash,
            "actual": actual_hash,
            "reason": "tampered admission ledger blocks final reference admission",
        })
    try:
        ledger = _read_json_mapping(path)
    except (OSError, json.JSONDecodeError, DftScfSixClassBundleError) as exc:
        blockers.append({
            "id": "reference_admission_ledger_unreadable",
            "field": "reference_admission_ledger.path",
            "path": rel_path,
            "error": str(exc),
        })
        return {}
    if ledger.get("schema_version") != DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_SCHEMA:
        blockers.append({
            "id": "unexpected_reference_admission_ledger_schema",
            "field": "reference_admission_ledger.schema_version",
            "expected": DFT_SCF_SIX_CLASS_REFERENCE_ADMISSION_LEDGER_SCHEMA,
            "actual": ledger.get("schema_version"),
        })
    if ledger.get("suite_id") != DFT_SCF_SIX_CLASS_SUITE_ID:
        blockers.append({
            "id": "reference_admission_ledger_suite_mismatch",
            "field": "reference_admission_ledger.suite_id",
            "expected": DFT_SCF_SIX_CLASS_SUITE_ID,
            "actual": ledger.get("suite_id"),
        })
    if ledger.get("bundle_id") != payload.get("bundle_id"):
        blockers.append({
            "id": "reference_admission_ledger_bundle_mismatch",
            "field": "reference_admission_ledger.bundle_id",
            "expected": payload.get("bundle_id"),
            "actual": ledger.get("bundle_id"),
        })
    entries = ledger.get("entries", [])
    if not isinstance(entries, list):
        blockers.append({
            "id": "reference_admission_ledger_entries_not_list",
            "field": "reference_admission_ledger.entries",
        })
        return {}
    entries_by_class: Dict[str, Dict[str, Any]] = {}
    duplicate_class_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            blockers.append({
                "id": "reference_admission_ledger_entry_not_object",
                "field": "reference_admission_ledger.entries",
            })
            continue
        class_id = str(entry.get("class_id") or "")
        if class_id in entries_by_class:
            duplicate_class_ids.add(class_id)
        if class_id:
            entries_by_class[class_id] = dict(entry)
    if duplicate_class_ids:
        blockers.append({
            "id": "duplicate_reference_admission_ledger_class_id",
            "class_ids": sorted(duplicate_class_ids),
        })
    missing = [class_id for class_id in REQUIRED_DFT_SCF_CLASS_IDS if class_id not in entries_by_class]
    extra = [class_id for class_id in entries_by_class if class_id not in set(REQUIRED_DFT_SCF_CLASS_IDS)]
    if missing:
        blockers.append({
            "id": "reference_admission_ledger_missing_required_class_ids",
            "missing_class_ids": missing,
        })
    if extra:
        blockers.append({
            "id": "reference_admission_ledger_unexpected_class_ids",
            "extra_class_ids": sorted(extra),
        })
    if ledger.get("entry_count") != len(entries):
        blockers.append({
            "id": "reference_admission_ledger_entry_count_mismatch",
            "expected": len(entries),
            "actual": ledger.get("entry_count"),
        })
    admitted_class_ids = [
        class_id
        for class_id in REQUIRED_DFT_SCF_CLASS_IDS
        if entries_by_class.get(class_id, {}).get("admitted") is True
    ]
    if ledger.get("admitted_class_ids") != admitted_class_ids:
        blockers.append({
            "id": "reference_admission_ledger_admitted_class_ids_mismatch",
            "expected": admitted_class_ids,
            "actual": ledger.get("admitted_class_ids"),
        })
    expected_final_complete = len(entries_by_class) == len(REQUIRED_DFT_SCF_CLASS_IDS) and all(
        entries_by_class[class_id].get("admitted") is True for class_id in REQUIRED_DFT_SCF_CLASS_IDS
    )
    if ledger.get("final_admission_complete") is not expected_final_complete:
        blockers.append({
            "id": "reference_admission_ledger_final_complete_mismatch",
            "expected": expected_final_complete,
            "actual": ledger.get("final_admission_complete"),
        })
    return entries_by_class


def _normalized_reference_summary_hash(summary: Mapping[str, Any]) -> str:
    return stable_json_hash({
        key: value
        for key, value in summary.items()
        if key != "normalized_reference_summary_hash"
    })


def validate_dft_scf_six_class_bundle_manifest(
    payload_or_path: Mapping[str, Any] | Path,
    *,
    base_dir: Path | None = None,
) -> Dict[str, Any]:
    """Validate that the six-class bundle is concrete and fail-closed."""

    if isinstance(payload_or_path, Path):
        manifest_path = Path(payload_or_path)
        payload = _read_json_mapping(manifest_path)
        root = base_dir or manifest_path.parent
    else:
        payload = dict(payload_or_path)
        root = Path(base_dir or ".")

    local_qe_reference_run = payload.get("local_qe_reference_run") if isinstance(payload.get("local_qe_reference_run"), Mapping) else {}
    local_reference_entries = (
        local_qe_reference_run.get("entries", {})
        if isinstance(local_qe_reference_run, Mapping) and isinstance(local_qe_reference_run.get("entries"), Mapping)
        else {}
    )
    reference_manifest_entries = _reference_hash_manifest_entries(payload, base_dir=root)

    blockers: list[Dict[str, Any]] = []
    reference_admission_entries = _reference_admission_ledger_entries(payload, base_dir=root, blockers=blockers)
    if payload.get("schema_version") != DFT_SCF_SIX_CLASS_SUITE_SCHEMA:
        blockers.append({"id": "unexpected_schema_version", "reason": "six-class bundle manifest schema mismatch"})
    if payload.get("strict") is not True:
        blockers.append({"id": "strict_flag_not_true", "reason": "strict six-class bundle must set strict=true"})
    if payload.get("descriptor_plus_runnable_bundle") is not True:
        blockers.append({"id": "not_descriptor_plus_runnable_bundle", "reason": "manifest must declare descriptor-plus-runnable bundle"})
    for field in ("bundle_id", "campaign_id", "workload_run_id", "parser_version", "proof_class"):
        if not _non_empty(payload.get(field)):
            blockers.append({"id": "missing_manifest_field", "field": field, "reason": "required manifest field is absent"})

    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        blockers.append({"id": "cases_not_list", "reason": "cases must be a list"})
        cases = []
    seen: set[str] = set()
    present: list[str] = []
    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, Mapping):
            blockers.append({"id": "case_not_object", "field": f"cases[{index}]", "reason": "case entry must be an object"})
            continue
        case = raw_case
        class_id = str(case.get("class_id") or case.get("workload_class") or "")
        present.append(class_id)
        if class_id in seen:
            blockers.append({"id": "duplicate_class_id", "field": f"cases[{index}].class_id", "class_id": class_id})
        seen.add(class_id)
        if class_id not in REQUIRED_DFT_SCF_CLASS_IDS:
            blockers.append({"id": "unexpected_class_id", "field": f"cases[{index}].class_id", "class_id": class_id})
        for field in ("case_id", "class_id", "workload_class", "run_command", "provenance", "license", "parser_version", "parser_tool_version", "proof_class"):
            if not _non_empty(case.get(field)):
                blockers.append({"id": "missing_case_field", "field": f"cases[{index}].{field}", "class_id": class_id})
        raw_qe_input = case.get("qe_input")
        qe_input: Mapping[str, Any] = raw_qe_input if isinstance(raw_qe_input, Mapping) else {}
        if not _non_empty(qe_input.get("text")):
            blockers.append({"id": "missing_qe_input_text", "field": f"cases[{index}].qe_input.text", "class_id": class_id})
        if qe_input:
            _path_ref_valid(qe_input, base_dir=root, field=f"cases[{index}].qe_input", blockers=blockers)
        else:
            blockers.append({"id": "missing_qe_input", "field": f"cases[{index}].qe_input", "class_id": class_id})
        raw_descriptor = case.get("descriptor")
        descriptor: Mapping[str, Any] = raw_descriptor if isinstance(raw_descriptor, Mapping) else {}
        if descriptor:
            _path_ref_valid(descriptor, base_dir=root, field=f"cases[{index}].descriptor", blockers=blockers)
        else:
            blockers.append({"id": "missing_descriptor_ref", "field": f"cases[{index}].descriptor", "class_id": class_id})
        raw_workload_profile = case.get("workload_profile")
        workload_profile: Mapping[str, Any] = raw_workload_profile if isinstance(raw_workload_profile, Mapping) else {}
        if workload_profile:
            _path_ref_valid(workload_profile, base_dir=root, field=f"cases[{index}].workload_profile", blockers=blockers)
            if workload_profile.get("schema_version") != "dse.dft.workload_profile.layered.v1":
                blockers.append({
                    "id": "unexpected_workload_profile_schema",
                    "field": f"cases[{index}].workload_profile.schema_version",
                    "class_id": class_id,
                })
            if not _non_empty(workload_profile.get("profile_hash")):
                blockers.append({
                    "id": "missing_workload_profile_hash",
                    "field": f"cases[{index}].workload_profile.profile_hash",
                    "class_id": class_id,
                })
        else:
            blockers.append({"id": "missing_workload_profile_ref", "field": f"cases[{index}].workload_profile", "class_id": class_id})
        raw_workload_analysis = case.get("dft_workload_analysis")
        workload_analysis: Mapping[str, Any] = raw_workload_analysis if isinstance(raw_workload_analysis, Mapping) else {}
        required_analysis_layers = (
            "raw_input_facts",
            "resolved_run_facts",
            "derived_scale_features",
            "coverage_vector",
            "coverage_derivation_audit",
            "kernel_workload_graph",
            "reference_summary",
        )
        if not workload_analysis:
            blockers.append({"id": "missing_dft_workload_analysis", "field": f"cases[{index}].dft_workload_analysis", "class_id": class_id})
        else:
            for layer in required_analysis_layers:
                if not isinstance(workload_analysis.get(layer), Mapping):
                    blockers.append({
                        "id": "missing_dft_workload_analysis_layer",
                        "field": f"cases[{index}].dft_workload_analysis.{layer}",
                        "class_id": class_id,
                    })
            coverage = workload_analysis.get("coverage_vector")
            if isinstance(coverage, Mapping) and not _non_empty(coverage.get("required_kernel_gates")):
                blockers.append({
                    "id": "missing_required_kernel_gates",
                    "field": f"cases[{index}].dft_workload_analysis.coverage_vector.required_kernel_gates",
                    "class_id": class_id,
                })
            if isinstance(coverage, Mapping):
                gate_reasons = coverage.get("gate_derivation_reasons")
                if not isinstance(gate_reasons, Mapping):
                    gate_reasons = {}
                for gate_id in coverage.get("required_kernel_gates") or []:
                    reasons = gate_reasons.get(gate_id)
                    if not isinstance(reasons, list) or not reasons:
                        blockers.append({
                            "id": "missing_non_tag_gate_derivation_reason",
                            "field": f"cases[{index}].dft_workload_analysis.coverage_vector.gate_derivation_reasons.{gate_id}",
                            "class_id": class_id,
                            "gate_id": gate_id,
                            "reason": "each required kernel gate must cite at least one non-stress-tag derivation fact",
                        })
                        continue
                    if not any(isinstance(reason, Mapping) and reason.get("source") != "stress_tags" for reason in reasons):
                        blockers.append({
                            "id": "stress_tag_only_gate_derivation_reason",
                            "field": f"cases[{index}].dft_workload_analysis.coverage_vector.gate_derivation_reasons.{gate_id}",
                            "class_id": class_id,
                            "gate_id": gate_id,
                            "reason": "stress_tags are display-only and cannot authorize required kernel gates",
                        })
                expected_coverage_audit = build_coverage_derivation_audit(coverage)
                if expected_coverage_audit.get("stress_tags_used_for_gate_authority") is True:
                    blockers.append({
                        "id": "stress_tag_gate_derivation_reason",
                        "field": f"cases[{index}].dft_workload_analysis.coverage_vector.gate_derivation_reasons",
                        "class_id": class_id,
                        "stress_tag_reason_gates": expected_coverage_audit.get("stress_tag_reason_gates", []),
                        "reason": "stress_tags are display-only and cannot appear as gate authority reasons",
                    })
                for audit_field, emitted_audit in (
                    (
                        f"cases[{index}].coverage_derivation_audit",
                        case.get("coverage_derivation_audit"),
                    ),
                    (
                        f"cases[{index}].dft_workload_analysis.coverage_derivation_audit",
                        workload_analysis.get("coverage_derivation_audit"),
                    ),
                    (
                        f"cases[{index}].dft_workload_analysis.coverage_vector.coverage_derivation_audit",
                        coverage.get("coverage_derivation_audit"),
                    ),
                ):
                    if not isinstance(emitted_audit, Mapping):
                        blockers.append({
                            "id": "missing_coverage_derivation_audit",
                            "field": audit_field,
                            "class_id": class_id,
                            "reason": "coverage derivation audit must be emitted but recomputed by validation",
                        })
                    elif dict(emitted_audit) != expected_coverage_audit:
                        blockers.append({
                            "id": "coverage_derivation_audit_mismatch",
                            "field": audit_field,
                            "class_id": class_id,
                            "expected": expected_coverage_audit,
                            "actual": dict(emitted_audit),
                            "reason": "emitted coverage derivation audit disagrees with recomputation from gate reasons",
                        })
            graph = workload_analysis.get("kernel_workload_graph")
            if isinstance(graph, Mapping):
                gate_contracts = graph.get("kernel_gate_contracts")
                required_gates = set(coverage.get("required_kernel_gates") or []) if isinstance(coverage, Mapping) else set()
                contract_gates: set[str] = set()
                if isinstance(gate_contracts, list):
                    contract_gates = {
                        str(contract.get("gate_id"))
                        for contract in gate_contracts
                        if isinstance(contract, Mapping)
                    }
                if required_gates and contract_gates != required_gates:
                    blockers.append({
                        "id": "kernel_gate_contracts_do_not_cover_required_gates",
                        "field": f"cases[{index}].dft_workload_analysis.kernel_workload_graph.kernel_gate_contracts",
                        "class_id": class_id,
                        "required_gates": sorted(required_gates),
                        "contract_gates": sorted(contract_gates),
                    })
            reference_summary = workload_analysis.get("reference_summary")
            if isinstance(reference_summary, Mapping) and not _non_empty(reference_summary.get("normalized_reference_summary_hash")):
                blockers.append({
                    "id": "missing_normalized_reference_summary_hash",
                    "field": f"cases[{index}].dft_workload_analysis.reference_summary.normalized_reference_summary_hash",
                    "class_id": class_id,
                })
            if isinstance(reference_summary, Mapping) and _non_empty(reference_summary.get("normalized_reference_summary_hash")):
                expected_summary_hash = _normalized_reference_summary_hash(reference_summary)
                if reference_summary.get("normalized_reference_summary_hash") != expected_summary_hash:
                    blockers.append({
                        "id": "normalized_reference_summary_hash_mismatch",
                        "field": f"cases[{index}].dft_workload_analysis.reference_summary.normalized_reference_summary_hash",
                        "class_id": class_id,
                        "expected": expected_summary_hash,
                        "actual": reference_summary.get("normalized_reference_summary_hash"),
                    })
        pseudo_refs = case.get("pseudo_refs", [])
        if not isinstance(pseudo_refs, list) or not pseudo_refs:
            blockers.append({"id": "missing_pseudo_refs", "field": f"cases[{index}].pseudo_refs", "class_id": class_id})
            pseudo_refs = []
        for pseudo_index, pseudo in enumerate(pseudo_refs):
            if not isinstance(pseudo, Mapping):
                blockers.append({"id": "pseudo_ref_not_object", "field": f"cases[{index}].pseudo_refs[{pseudo_index}]", "class_id": class_id})
                continue
            _path_ref_valid(pseudo, base_dir=root, field=f"cases[{index}].pseudo_refs[{pseudo_index}]", blockers=blockers)
            for field in ("source", "license", "physical_validity"):
                if not _non_empty(pseudo.get(field)):
                    blockers.append({"id": "missing_pseudo_ref_field", "field": f"cases[{index}].pseudo_refs[{pseudo_index}].{field}", "class_id": class_id})
        raw_reference_output = case.get("reference_output")
        reference_output: Mapping[str, Any] = raw_reference_output if isinstance(raw_reference_output, Mapping) else {}
        ref_hash = str(reference_output.get("sha256") or "") if reference_output else ""
        if not ref_hash:
            blockers.append({
                "id": "missing_real_reference_output_hash",
                "field": f"cases[{index}].reference_output.sha256",
                "class_id": class_id,
                "reason": "real QE reference-output hash is required; placeholder hashes are not fabricated",
            })
        elif reference_output.get("hash_final") is not True:
            blockers.append({
                "id": "reference_output_hash_not_final",
                "field": f"cases[{index}].reference_output.hash_final",
                "class_id": class_id,
                "reason": "hash-only/caller-supplied reference material is provenance and cannot be final real-QE evidence",
            })
        if ref_hash:
            output_path = _bundle_relative_existing_file(reference_output.get("path"), base_dir=root)
            if output_path is None:
                blockers.append({
                    "id": "reference_output_path_not_local_bundle_file",
                    "field": f"cases[{index}].reference_output.path",
                    "class_id": class_id,
                    "path": reference_output.get("path"),
                    "reason": "final real-QE admission requires an existing bundle-relative QE output file",
                })
            else:
                actual_output_hash = sha256_file(output_path)
                if actual_output_hash != ref_hash:
                    blockers.append({
                        "id": "reference_output_file_hash_mismatch",
                        "field": f"cases[{index}].reference_output.sha256",
                        "class_id": class_id,
                        "expected": ref_hash,
                        "actual": actual_output_hash,
                    })
            if reference_output.get("status") not in {
                "local_pw_x_reference_output_hash_from_converged_scf_run",
                "local_pw_x_reference_output_hash_from_existing_converged_scf_output",
            }:
                blockers.append({
                    "id": "reference_output_not_local_converged_qe_source",
                    "field": f"cases[{index}].reference_output.status",
                    "class_id": class_id,
                    "status": reference_output.get("status"),
                    "reason": "caller/external hashes are provenance; final admission requires local or reused converged QE output",
                })
            if reference_output.get("job_done") is not True or reference_output.get("scf_converged") is not True:
                blockers.append({
                    "id": "reference_output_convergence_markers_not_verified",
                    "field": f"cases[{index}].reference_output",
                    "class_id": class_id,
                    "job_done": reference_output.get("job_done"),
                    "scf_converged": reference_output.get("scf_converged"),
                })
            admission_source = reference_output.get("admission_source")
            admission_entry_id = reference_output.get("admission_entry_id")
            admission_marker_authority = reference_output.get("admission_marker_authority")
            if admission_source not in {"local_qe_reference_run", "reused_existing_local_qe_output"} or not _non_empty(admission_entry_id):
                blockers.append({
                    "id": "reference_output_missing_builder_admission_marker",
                    "field": f"cases[{index}].reference_output.admission_entry_id",
                    "class_id": class_id,
                    "admission_source": admission_source,
                    "reason": "final real-QE admission requires a builder-generated local/reuse admission marker",
                })
            elif admission_marker_authority != "builder_generated_local_qe_reference_entry":
                blockers.append({
                    "id": "reference_output_admission_marker_not_builder_owned",
                    "field": f"cases[{index}].reference_output.admission_marker_authority",
                    "class_id": class_id,
                    "actual": admission_marker_authority,
                })
            local_entry = local_reference_entries.get(class_id) if isinstance(local_reference_entries, Mapping) else None
            manifest_entry = reference_manifest_entries.get(class_id)
            for source_name, source_entry in (
                ("local_qe_reference_run.entries", local_entry),
                ("reference_output_hash_manifest.entries", manifest_entry),
            ):
                if not isinstance(source_entry, Mapping):
                    blockers.append({
                        "id": "reference_output_admission_entry_missing_from_builder_manifest",
                        "field": f"{source_name}.{class_id}",
                        "class_id": class_id,
                        "admission_entry_id": admission_entry_id,
                    })
                    continue
                mismatches = {
                    field: {"case": reference_output.get(field), "builder": source_entry.get(field)}
                    for field in ("path", "sha256", "status", "job_done", "scf_converged", "admission_source", "admission_entry_id")
                    if reference_output.get(field) != source_entry.get(field)
                }
                if mismatches:
                    blockers.append({
                        "id": "reference_output_admission_entry_mismatch",
                        "field": f"{source_name}.{class_id}",
                        "class_id": class_id,
                        "mismatches": mismatches,
                    })
            reference_summary = workload_analysis.get("reference_summary") if isinstance(workload_analysis, Mapping) else {}
            if not isinstance(reference_summary, Mapping) or reference_summary.get("raw_output_sha256") != ref_hash:
                blockers.append({
                    "id": "reference_summary_raw_hash_mismatch",
                    "field": f"cases[{index}].dft_workload_analysis.reference_summary.raw_output_sha256",
                    "class_id": class_id,
                    "expected": ref_hash,
                    "actual": reference_summary.get("raw_output_sha256") if isinstance(reference_summary, Mapping) else None,
                })
            if not isinstance(reference_summary, Mapping) or reference_summary.get("convergence_verified") is not True:
                blockers.append({
                    "id": "reference_summary_convergence_not_verified",
                    "field": f"cases[{index}].dft_workload_analysis.reference_summary.convergence_verified",
                    "class_id": class_id,
                    "actual": reference_summary.get("convergence_verified") if isinstance(reference_summary, Mapping) else None,
                })
            ledger_entry = reference_admission_entries.get(class_id)
            if not isinstance(ledger_entry, Mapping):
                blockers.append({
                    "id": "reference_admission_ledger_entry_missing",
                    "field": f"reference_admission_ledger.entries.{class_id}",
                    "class_id": class_id,
                    "reason": "final reference admission requires a canonical ledger entry matching the manifest case",
                })
            else:
                ledger_expected = {
                    "reference_output_path": reference_output.get("path"),
                    "reference_output_sha256": reference_output.get("sha256"),
                    "status": reference_output.get("status"),
                    "hash_final": bool(reference_output.get("hash_final") is True),
                    "job_done": bool(reference_output.get("job_done") is True),
                    "scf_converged": bool(reference_output.get("scf_converged") is True),
                    "admission_source": reference_output.get("admission_source"),
                    "admission_entry_id": reference_output.get("admission_entry_id"),
                    "admission_marker_authority": reference_output.get("admission_marker_authority"),
                    "admitted": bool(_is_local_converged_reference_entry(reference_output)),
                    "normalized_reference_summary_hash": (
                        reference_summary.get("normalized_reference_summary_hash")
                        if isinstance(reference_summary, Mapping)
                        else None
                    ),
                    "raw_output_sha256": (
                        reference_summary.get("raw_output_sha256")
                        if isinstance(reference_summary, Mapping)
                        else None
                    ),
                }
                ledger_mismatches = {
                    key: {"case": expected_value, "ledger": ledger_entry.get(key)}
                    for key, expected_value in ledger_expected.items()
                    if ledger_entry.get(key) != expected_value
                }
                if ledger_mismatches:
                    blockers.append({
                        "id": "reference_admission_ledger_entry_mismatch",
                        "field": f"reference_admission_ledger.entries.{class_id}",
                        "class_id": class_id,
                        "mismatches": ledger_mismatches,
                        "reason": "canonical admission ledger entry is stale or disagrees with the manifest case",
                    })

    mapping_cases = [case for case in cases if isinstance(case, Mapping)]
    expected_manifest_audit = _suite_coverage_derivation_audit(mapping_cases)
    manifest_audit = payload.get("coverage_derivation_audit")
    if not isinstance(manifest_audit, Mapping):
        blockers.append({
            "id": "missing_coverage_derivation_audit",
            "field": "coverage_derivation_audit",
            "reason": "suite manifest must emit a recomputable coverage derivation audit",
        })
    elif dict(manifest_audit) != expected_manifest_audit:
        blockers.append({
            "id": "coverage_derivation_audit_mismatch",
            "field": "coverage_derivation_audit",
            "expected": expected_manifest_audit,
            "actual": dict(manifest_audit),
            "reason": "suite manifest coverage audit disagrees with recomputation from cases",
        })

    missing = [class_id for class_id in REQUIRED_DFT_SCF_CLASS_IDS if class_id not in set(present)]
    extra = [class_id for class_id in present if class_id not in set(REQUIRED_DFT_SCF_CLASS_IDS)]
    if missing:
        blockers.append({"id": "missing_required_class_ids", "missing_class_ids": missing, "reason": "all six strict SCF class IDs are required"})
    if extra:
        blockers.append({"id": "unexpected_extra_class_ids", "extra_class_ids": extra, "reason": "strict suite must contain exactly the six required class IDs"})
    if len(cases) != len(REQUIRED_DFT_SCF_CLASS_IDS):
        blockers.append({"id": "wrong_case_count", "expected": len(REQUIRED_DFT_SCF_CLASS_IDS), "actual": len(cases)})

    missing_real_hashes = [blocker for blocker in blockers if blocker["id"] == "missing_real_reference_output_hash"]
    status = "passed" if not blockers else "blocked_missing_real_reference_output_hashes" if len(missing_real_hashes) == len(blockers) else "blocked"
    admitted = not blockers
    final_real_qe_evidence = admitted
    return {
        "schema_version": DFT_SCF_SIX_CLASS_SUITE_VALIDATION_SCHEMA,
        "bundle_id": payload.get("bundle_id"),
        "suite_id": payload.get("suite_id"),
        "status": status,
        "admitted": admitted,
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "present_class_ids": sorted(set(present)),
        "missing_class_ids": missing,
        "blocker_count": len(blockers),
        "blocker_ids": sorted({str(blocker.get("id")) for blocker in blockers}),
        "blockers": blockers,
        "final_real_qe_evidence": final_real_qe_evidence,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_scf_six_class_bundle(
    out_dir: Path,
    *,
    bundle_id: str = "dft-scf-six-class-descriptor-runnable-bundle",
    campaign_id: str = "dft-scf-hardware-dse",
    workload_run_id: str = DFT_SCF_SIX_CLASS_SUITE_ID,
    qe_command: str = "pw.x",
    reference_output_hashes: Mapping[str, Any] | Path | None = None,
    use_local_pseudos: bool = False,
    local_pseudo_dir: Path = DEFAULT_LOCAL_QE_PSEUDO_DIR,
    run_local_qe: bool = False,
    local_pw_x: Path = DEFAULT_LOCAL_PW_X,
    qe_run_timeout_seconds: int = 300,
    reuse_existing_qe_outputs: bool = False,
) -> Dict[str, Any]:
    """Write the six-class bundle and return a compact builder status."""

    hash_mapping: Mapping[str, Any] | None
    if isinstance(reference_output_hashes, Path):
        hash_mapping = _read_json_mapping(reference_output_hashes)
    else:
        hash_mapping = reference_output_hashes
    manifest = build_dft_scf_six_class_bundle_manifest(
        out_dir=Path(out_dir),
        bundle_id=bundle_id,
        campaign_id=campaign_id,
        workload_run_id=workload_run_id,
        qe_command=qe_command,
        reference_output_hashes=hash_mapping,
        use_local_pseudos=use_local_pseudos,
        local_pseudo_dir=Path(local_pseudo_dir),
        run_local_qe=run_local_qe,
        local_pw_x=Path(local_pw_x),
        qe_run_timeout_seconds=qe_run_timeout_seconds,
        reuse_existing_qe_outputs=reuse_existing_qe_outputs,
    )
    validation = manifest["validation"]
    return {
        "schema_version": "dse.dft_scf.six_class_bundle_builder_status.v1",
        "status": "passed" if validation["admitted"] else validation["status"],
        "manifest": DFT_SCF_SIX_CLASS_MANIFEST_NAME,
        "bundle_id": manifest["bundle_id"],
        "suite_id": manifest["suite_id"],
        "case_count": manifest["case_count"],
        "required_class_ids": list(REQUIRED_DFT_SCF_CLASS_IDS),
        "reference_output_hash_manifest": manifest["reference_output_hash_manifest"]["path"],
        "reference_admission_ledger": manifest["reference_admission_ledger"]["path"],
        "local_qe_pseudo_discovery_complete": manifest["local_qe_asset_discovery"]["complete"],
        "local_qe_reference_run_complete": manifest["local_qe_reference_run"]["complete"],
        "admitted": validation["admitted"],
        "blocker_count": validation["blocker_count"],
        "blocker_ids": validation["blocker_ids"],
        "final_real_qe_evidence": validation["final_real_qe_evidence"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
