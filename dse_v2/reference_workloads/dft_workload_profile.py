#!/usr/bin/env python3
"""Layered DFT workload profile helpers for the reference DFT/QE adapter.

The generic DSE core stays domain-neutral.  This module is deliberately scoped
under ``reference_workloads`` and converts QE-flavoured bundle material into a
canonical, fail-closed DFT workload profile:

source/provenance -> raw input facts -> resolved run facts -> derived scale
features -> coverage vector -> kernel workload graph.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.codesign.release_domain import stable_json_hash

DFT_WORKLOAD_PROFILE_SCHEMA = "dse.dft.workload_profile.layered.v1"
DFT_REFERENCE_SUMMARY_SCHEMA = "dse.dft.reference_summary.v1"
DFT_COVERAGE_VECTOR_SCHEMA = "dse.dft.coverage_vector.v1"
DFT_KERNEL_WORKLOAD_GRAPH_SCHEMA = "dse.dft.kernel_workload_graph.v1"
DFT_KERNEL_GATE_CONTRACT_SCHEMA = "dse.dft.kernel_gate_contract.v1"
DFT_PROFILE_BUILDER_VERSION = "dft_workload_profile.py:v1"

SEMANTIC_KERNEL_GATE_ALIASES: Mapping[str, str] = {
    "fft3d_forward_inverse_batch": "fft_ifft_ffft",
    "transpose_layout_conversion": "transpose_layout_conversion",
    "hpsi_local_potential": "hpsi_local_potential",
    "kinetic_energy_apply": "kinetic_add",
    "nonlocal_projector_apply": "nonlocal_projector",
    "complex_gemm_tile": "complex_gemm_gemv_tile",
    "complex_gemv_tile": "complex_gemm_gemv_tile",
    "reduction_dot_tree": "reduction_dot_tree",
    "dma_hbm_movement_engine": "dma_hbm_movement_engine",
}

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_value(raw: str) -> Any:
    text = raw.strip().rstrip(",").strip()
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        return text[1:-1]
    lower = text.lower()
    if lower in {".true.", "true"}:
        return True
    if lower in {".false.", "false"}:
        return False
    try:
        if any(marker in lower for marker in ("d", "e", ".")):
            return float(lower.replace("d", "e"))
        return int(text)
    except ValueError:
        return text


def _parse_namelists(qe_input_text: str) -> Dict[str, Dict[str, Any]]:
    namelists: Dict[str, Dict[str, Any]] = {}
    current: str | None = None
    for raw_line in qe_input_text.splitlines():
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("&"):
            current = line[1:].strip().lower()
            namelists[current] = {}
            continue
        if line == "/":
            current = None
            continue
        if current and "=" in line:
            key, value = line.split("=", 1)
            namelists[current][key.strip().lower()] = _strip_value(value)
    return namelists


def _block_after(qe_input_text: str, header: str) -> list[str]:
    lines = qe_input_text.splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.strip().lower().startswith(header.lower()):
            block: list[str] = []
            for child in lines[index + 1 :]:
                stripped = child.strip()
                if not stripped:
                    break
                first = stripped.split()[0].upper()
                if first in {"ATOMIC_POSITIONS", "K_POINTS", "CELL_PARAMETERS", "ATOMIC_SPECIES"}:
                    break
                block.append(stripped)
            return block
    return []


def _cell_parameters(qe_input_text: str) -> list[list[float]] | None:
    block = _block_after(qe_input_text, "CELL_PARAMETERS")
    if len(block) < 3:
        return None
    rows: list[list[float]] = []
    for line in block[:3]:
        fields = line.split()
        if len(fields) < 3:
            return None
        rows.append([float(fields[0]), float(fields[1]), float(fields[2])])
    return rows


def _atomic_species(qe_input_text: str) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for line in _block_after(qe_input_text, "ATOMIC_SPECIES"):
        fields = line.split()
        if len(fields) >= 3:
            rows.append({"species": fields[0], "mass_amu": float(fields[1]), "pseudo_file": fields[2]})
    return rows


def _atomic_positions(qe_input_text: str) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for line in _block_after(qe_input_text, "ATOMIC_POSITIONS"):
        fields = line.split()
        if len(fields) >= 4:
            rows.append({"species": fields[0], "position": [float(fields[1]), float(fields[2]), float(fields[3])]})
    return rows


def _kpoints(qe_input_text: str) -> Dict[str, Any]:
    lines = qe_input_text.splitlines()
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.upper().startswith("K_POINTS"):
            mode = stripped.split(maxsplit=1)[1].lower() if len(stripped.split(maxsplit=1)) == 2 else "unknown"
            if mode == "automatic" and index + 1 < len(lines):
                fields = lines[index + 1].split()
                if len(fields) >= 6:
                    grid = [int(fields[0]), int(fields[1]), int(fields[2])]
                    shift = [int(fields[3]), int(fields[4]), int(fields[5])]
                    return {
                        "mode": mode,
                        "grid": grid,
                        "shift": shift,
                        "full_count_estimate": grid[0] * grid[1] * grid[2],
                    }
            return {"mode": mode}
    return {"mode": "missing"}


def build_source_bundle_layer(
    *,
    class_id: str,
    qe_input_path: str,
    qe_input_sha256: str | None,
    pseudo_refs: Sequence[Mapping[str, Any]],
    run_command: Sequence[str] | None,
    reference_output: Mapping[str, Any] | None,
    parser_version: str,
    proof_class: str,
) -> Dict[str, Any]:
    return {
        "schema_version": "dse.dft.source_bundle_layer.v1",
        "class_id": class_id,
        "source_kind": "qe_input_output" if reference_output and reference_output.get("path") else "qe_input_bundle",
        "qe_input": {"path": qe_input_path, "sha256": qe_input_sha256, "hash_algorithm": "sha256"},
        "pseudopotentials": [dict(item) for item in pseudo_refs],
        "run_command": list(run_command or []),
        "reference_output": dict(reference_output or {}),
        "parser_tool_version": parser_version,
        "proof_class": proof_class,
        "claim_boundary": "Source/provenance layer only; not architecture, mapping, evidence promotion, or completion proof.",
    }


def parse_qe_raw_input_facts(qe_input_text: str, *, class_id: str | None = None) -> Dict[str, Any]:
    namelists = _parse_namelists(qe_input_text)
    control = namelists.get("control", {})
    system = namelists.get("system", {})
    electrons = namelists.get("electrons", {})
    nbnd_value = system.get("nbnd")
    ecutwfc = system.get("ecutwfc")
    ecutrho = system.get("ecutrho")
    return {
        "schema_version": "dse.dft.raw_input_facts.v1",
        "class_id": class_id,
        "calculation": control.get("calculation", "unknown"),
        "structure": {
            "nat": system.get("nat"),
            "ntyp": system.get("ntyp"),
            "ibrav": system.get("ibrav"),
            "celldm1_bohr": system.get("celldm(1)"),
            "celldm3": system.get("celldm(3)"),
            "cell_parameters_angstrom": _cell_parameters(qe_input_text),
            "atomic_species": _atomic_species(qe_input_text),
            "atomic_positions": _atomic_positions(qe_input_text),
        },
        "system": {
            "ecutwfc": {"value": ecutwfc, "unit": "Ry", "source": "qe_input" if ecutwfc is not None else "missing"},
            "ecutrho": {"value": ecutrho, "unit": "Ry", "source": "qe_input" if ecutrho is not None else "missing"},
            "occupations": system.get("occupations"),
            "smearing": system.get("smearing"),
            "degauss": {"value": system.get("degauss"), "unit": "Ry" if system.get("degauss") is not None else None},
            "nbnd": {"explicit": nbnd_value is not None, "input_value": nbnd_value},
            "nspin": system.get("nspin", 1),
            "noncolin": bool(system.get("noncolin", False)),
            "lspinorb": bool(system.get("lspinorb", False)),
        },
        "electrons": {
            "conv_thr": electrons.get("conv_thr"),
            "mixing_beta": electrons.get("mixing_beta"),
            "electron_maxstep": electrons.get("electron_maxstep"),
            "diagonalization": electrons.get("diagonalization"),
        },
        "kpoints": _kpoints(qe_input_text),
        "claim_boundary": "Raw input facts are parsed workload facts only; resolved sizes and claims require later layers.",
    }


def _regex_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _regex_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def resolved_run_facts_from_output(
    output_text: str | None,
    *,
    raw_input_facts: Mapping[str, Any],
) -> Dict[str, Any]:
    text = output_text or ""
    raw_system = raw_input_facts.get("system", {}) if isinstance(raw_input_facts.get("system"), Mapping) else {}
    raw_kpoints = raw_input_facts.get("kpoints", {}) if isinstance(raw_input_facts.get("kpoints"), Mapping) else {}
    nbnd_input = raw_system.get("nbnd", {}) if isinstance(raw_system.get("nbnd"), Mapping) else {}
    fft_match = re.search(r"FFT dimensions:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text)
    fft_grid = [int(fft_match.group(i)) for i in range(1, 4)] if fft_match else None
    pw_counts = [int(item) for item in re.findall(r"\(\s*(\d+)\s+PWs\)", text)]
    beta_functions = [int(item) for item in re.findall(r"Using radial grid of\s+\d+\s+points,\s+(\d+)\s+beta functions", text)]
    kpoint_count = _regex_int(r"number of k points=\s*(\d+)", text)
    nbnd_resolved = _regex_int(r"number of Kohn-Sham states=\s*(\d+)", text)
    scf_iterations = _regex_int(r"convergence has been achieved in\s*(\d+)\s+iterations", text)
    resolved_ecutrho = _regex_float(r"charge density cutoff\s*=\s*([0-9.]+)\s*Ry", text)
    return {
        "schema_version": "dse.dft.resolved_run_facts.v1",
        "source": "qe_output" if text else "input_estimator",
        "resolved_nbnd": nbnd_resolved if nbnd_resolved is not None else nbnd_input.get("input_value"),
        "resolved_kpoints_full": kpoint_count if kpoint_count is not None else raw_kpoints.get("full_count_estimate"),
        "resolved_kpoints_irreducible": kpoint_count,
        "resolved_npw": {
            "min": min(pw_counts) if pw_counts else None,
            "max": max(pw_counts) if pw_counts else None,
            "mean": round(sum(pw_counts) / len(pw_counts), 6) if pw_counts else None,
            "per_kpoint_sample": pw_counts[:32],
            "source": "qe_output" if pw_counts else "missing",
        },
        "resolved_nfft": {"grid": fft_grid, "source": "qe_output" if fft_grid else "missing"},
        "resolved_ecutrho": resolved_ecutrho,
        "valence_electrons": _regex_float(r"number of electrons\s*=\s*([0-9.]+)", text),
        "projector_count": sum(beta_functions) if beta_functions else None,
        "scf_iterations": scf_iterations,
        "job_done": "JOB DONE" in text,
        "scf_converged": "convergence has been achieved" in text,
        "warnings": [line.strip() for line in text.splitlines() if "warning" in line.lower()][:16],
        "confidence": {
            "npw": "exact" if pw_counts else "missing",
            "nfft": "exact" if fft_grid else "missing",
            "nbnd": "exact" if nbnd_resolved is not None else "input_explicit" if nbnd_input.get("input_value") else "missing",
            "kpoints": "exact" if kpoint_count is not None else "input_grid_estimate" if raw_kpoints.get("full_count_estimate") else "missing",
        },
        "claim_boundary": "Resolved facts describe QE initialization/output facts only; they are not hardware evidence or claim gates.",
    }


def build_derived_scale_features(
    raw_input_facts: Mapping[str, Any],
    resolved_run_facts: Mapping[str, Any],
) -> Dict[str, Any]:
    raw_system = raw_input_facts.get("system", {}) if isinstance(raw_input_facts.get("system"), Mapping) else {}
    raw_structure = raw_input_facts.get("structure", {}) if isinstance(raw_input_facts.get("structure"), Mapping) else {}
    nfft_grid = None
    resolved_nfft = resolved_run_facts.get("resolved_nfft")
    if isinstance(resolved_nfft, Mapping):
        nfft_grid = resolved_nfft.get("grid")
    nfft_total = None
    if isinstance(nfft_grid, Sequence) and len(nfft_grid) == 3 and all(isinstance(v, int) for v in nfft_grid):
        nfft_total = int(nfft_grid[0]) * int(nfft_grid[1]) * int(nfft_grid[2])
    nbnd = resolved_run_facts.get("resolved_nbnd")
    kpoints = resolved_run_facts.get("resolved_kpoints_full")
    npw = resolved_run_facts.get("resolved_npw", {}) if isinstance(resolved_run_facts.get("resolved_npw"), Mapping) else {}
    npw_effective = npw.get("mean") or npw.get("max")
    nat = raw_structure.get("nat")
    projector_count = resolved_run_facts.get("projector_count")
    fft_transforms = int((nbnd or 0) * (kpoints or 0) * 2) if nbnd and kpoints else None
    return {
        "schema_version": "dse.dft.derived_scale_features.v1",
        "fft": {
            "nfft": nfft_grid,
            "nfft_total": nfft_total,
            "transforms_per_scf_estimate": fft_transforms,
            "estimated_fft_points_per_scf": nfft_total * fft_transforms if nfft_total and fft_transforms else None,
            "source": "resolved_qe_output" if nfft_total else "missing_or_estimated",
        },
        "hpsi": {
            "npw_effective": npw_effective,
            "nbnd": nbnd,
            "kpoints": kpoints,
            "estimated_complex_points": int(npw_effective * nbnd * kpoints) if npw_effective and nbnd and kpoints else None,
        },
        "nonlocal_projector": {
            "projector_count": projector_count,
            "estimated_projector_work": int(projector_count * (nbnd or 0) * (kpoints or 0)) if projector_count and nbnd and kpoints else None,
        },
        "dense_linear_algebra": {
            "nbnd": nbnd,
            "gemm_shape_estimates": [[nbnd, nbnd, max(int(npw_effective), 1)]] if nbnd and npw_effective else [],
            "orthogonalization_shape": [nbnd, nbnd] if nbnd else None,
        },
        "reductions": {
            "dot_products_per_scf_estimate": int((nbnd or 0) * (nbnd or 0) * (kpoints or 0)) if nbnd and kpoints else None,
        },
        "host_device": {
            "transfer_bytes_per_scf_estimate": int((nfft_total or 0) * 16 * max(kpoints or 1, 1)) if nfft_total else None,
            "persistent_tensor_candidates": ["wavefunction", "density", "potential", "projector_coefficients"],
        },
        "input_parameters": {
            "ecutwfc": raw_system.get("ecutwfc"),
            "occupations": raw_system.get("occupations"),
            "smearing": raw_system.get("smearing"),
            "nat": nat,
        },
        "claim_boundary": "Derived features estimate computational pressure; they are not candidate identity or measured hardware evidence.",
    }


def _intensity(value: int | float | None, *, medium: float, high: float) -> str:
    if value is None:
        return "unknown"
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def build_coverage_vector(
    *,
    class_id: str,
    stress_tags: Iterable[str],
    raw_input_facts: Mapping[str, Any],
    derived_features: Mapping[str, Any],
    resolved_run_facts: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build feature-derived workload coverage gates.

    ``stress_tags`` are retained only as suite intent/display labels.  They do
    not add gates: required kernel gates must be reproducible from parsed input
    facts, resolved QE facts, or deterministic derived scale features.
    """

    tags = sorted({str(tag) for tag in stress_tags})
    gates: set[str] = set()
    gate_derivation_reasons: dict[str, list[Dict[str, Any]]] = {}

    def add_gate(gate_id: str, *, source: str, fact: str, value: Any, rule: str) -> None:
        gates.add(gate_id)
        gate_derivation_reasons.setdefault(gate_id, []).append(
            {
                "source": source,
                "fact": fact,
                "value": value,
                "rule": rule,
            }
        )

    fft = derived_features.get("fft", {}) if isinstance(derived_features.get("fft"), Mapping) else {}
    hpsi = derived_features.get("hpsi", {}) if isinstance(derived_features.get("hpsi"), Mapping) else {}
    projector = derived_features.get("nonlocal_projector", {}) if isinstance(derived_features.get("nonlocal_projector"), Mapping) else {}
    dense = derived_features.get("dense_linear_algebra", {}) if isinstance(derived_features.get("dense_linear_algebra"), Mapping) else {}
    reductions = derived_features.get("reductions", {}) if isinstance(derived_features.get("reductions"), Mapping) else {}
    host_device = derived_features.get("host_device", {}) if isinstance(derived_features.get("host_device"), Mapping) else {}
    resolved = resolved_run_facts or {}
    raw_system = raw_input_facts.get("system", {}) if isinstance(raw_input_facts.get("system"), Mapping) else {}
    raw_structure = raw_input_facts.get("structure", {}) if isinstance(raw_input_facts.get("structure"), Mapping) else {}
    raw_nbnd = raw_system.get("nbnd", {}) if isinstance(raw_system.get("nbnd"), Mapping) else {}
    calculation = str(raw_input_facts.get("calculation") or "").lower()
    kpoints = hpsi.get("kpoints")
    nfft_total = fft.get("nfft_total")
    nfft_grid = fft.get("nfft")
    projector_count = projector.get("projector_count")
    estimated_projector_work = projector.get("estimated_projector_work")
    nbnd = hpsi.get("nbnd") or dense.get("nbnd") or raw_nbnd.get("input_value")
    dot_products = reductions.get("dot_products_per_scf_estimate")
    transfer_bytes = host_device.get("transfer_bytes_per_scf_estimate")

    if calculation == "scf":
        for gate_id in ("fft3d_forward_inverse_batch", "hpsi_local_potential", "kinetic_energy_apply"):
            add_gate(
                gate_id,
                source="raw_input_facts",
                fact="calculation",
                value=calculation,
                rule="QE scf calculation requires FFT/Hψ/kinetic workload coverage",
            )
        add_gate(
            "reduction_dot_tree",
            source="raw_input_facts",
            fact="calculation",
            value=calculation,
            rule="QE scf convergence and band operations require reduction coverage",
        )
        add_gate(
            "dma_hbm_movement_engine",
            source="raw_input_facts",
            fact="calculation",
            value=calculation,
            rule="QE scf evaluated-hybrid model must account host/device transfer coverage",
        )

    if nfft_total is not None:
        add_gate(
            "fft3d_forward_inverse_batch",
            source="derived_scale_features",
            fact="fft.nfft_total",
            value=nfft_total,
            rule="resolved FFT grid supplies FFT coverage shape",
        )
        if nfft_total >= 32768:
            add_gate(
                "transpose_layout_conversion",
                source="derived_scale_features",
                fact="fft.nfft_total",
                value=nfft_total,
                rule="nfft_total >= 32768 triggers layout/transpose pressure coverage",
            )
    if isinstance(nfft_grid, Sequence) and not isinstance(nfft_grid, (str, bytes, bytearray)) and len(nfft_grid) == 3:
        dims = [int(value) for value in nfft_grid if isinstance(value, int)]
        if len(dims) == 3 and min(dims) > 0 and max(dims) / min(dims) >= 4:
            add_gate(
                "transpose_layout_conversion",
                source="derived_scale_features",
                fact="fft.nfft",
                value=list(nfft_grid),
                rule="anisotropic resolved_nfft aspect ratio >= 4 triggers transpose coverage",
            )

    if nbnd:
        add_gate(
            "hpsi_local_potential",
            source="derived_scale_features",
            fact="hpsi.nbnd",
            value=nbnd,
            rule="nbnd present defines Hψ/band workload coverage",
        )
        add_gate(
            "kinetic_energy_apply",
            source="derived_scale_features",
            fact="hpsi.nbnd",
            value=nbnd,
            rule="nbnd present defines kinetic apply workload coverage",
        )
        if nbnd >= 16:
            add_gate(
                "complex_gemm_tile",
                source="derived_scale_features",
                fact="dense_linear_algebra.nbnd",
                value=nbnd,
                rule="nbnd >= 16 triggers orthogonalization/dense GEMM coverage",
            )
        if nbnd >= 32:
            add_gate(
                "complex_gemv_tile",
                source="derived_scale_features",
                fact="dense_linear_algebra.nbnd",
                value=nbnd,
                rule="nbnd >= 32 triggers GEMV/projector tile coverage",
            )

    if projector_count:
        add_gate(
            "nonlocal_projector_apply",
            source="derived_scale_features",
            fact="nonlocal_projector.projector_count",
            value=projector_count,
            rule="projector_count > 0 triggers nonlocal projector coverage",
        )
        add_gate(
            "complex_gemv_tile",
            source="derived_scale_features",
            fact="nonlocal_projector.projector_count",
            value=projector_count,
            rule="projector_count > 0 triggers GEMV tile coverage for projector application",
        )
    if estimated_projector_work:
        add_gate(
            "nonlocal_projector_apply",
            source="derived_scale_features",
            fact="nonlocal_projector.estimated_projector_work",
            value=estimated_projector_work,
            rule="estimated_projector_work > 0 confirms nonlocal projector workload coverage",
        )

    if dot_products:
        add_gate(
            "reduction_dot_tree",
            source="derived_scale_features",
            fact="reductions.dot_products_per_scf_estimate",
            value=dot_products,
            rule="dot_products_per_scf_estimate > 0 triggers reduction coverage",
        )
    if transfer_bytes:
        add_gate(
            "dma_hbm_movement_engine",
            source="derived_scale_features",
            fact="host_device.transfer_bytes_per_scf_estimate",
            value=transfer_bytes,
            rule="transfer_bytes_per_scf_estimate > 0 triggers DMA/movement coverage",
        )
    resolved_nfft = resolved.get("resolved_nfft") if isinstance(resolved, Mapping) else None
    if isinstance(resolved_nfft, Mapping) and resolved_nfft.get("grid") and "fft3d_forward_inverse_batch" in gates:
        add_gate(
            "fft3d_forward_inverse_batch",
            source="resolved_run_facts",
            fact="resolved_nfft.grid",
            value=resolved_nfft.get("grid"),
            rule="resolved QE FFT dimensions corroborate FFT gate shape",
        )

    axes = {
        "system_size": _intensity(raw_structure.get("nat"), medium=4, high=8),
        "kpoint_pressure": _intensity(kpoints, medium=4, high=16),
        "fft_pressure": _intensity(nfft_total, medium=32768, high=250000),
        "projector_pressure": _intensity(projector_count, medium=4, high=12),
        "band_pressure": _intensity(nbnd, medium=16, high=32),
        "reduction_pressure": _intensity(dot_products, medium=1024, high=16384),
        "dma_pressure": _intensity(transfer_bytes, medium=1_000_000, high=16_000_000),
        "metallicity": "metal" if raw_system.get("occupations") == "smearing" else "insulator_or_fixed",
        "geometry": "slab" if "slab" in class_id else "supercell" if "supercell" in class_id else "bulk_or_fixture",
    }
    return {
        "schema_version": DFT_COVERAGE_VECTOR_SCHEMA,
        "class_id": class_id,
        "display_stress_tags": tags,
        "suite_intent_tags": tags,
        "stress_tag_gate_policy": "display_only_not_authoritative",
        "axes": axes,
        "required_kernel_gates": sorted(gates),
        "gate_derivation_reasons": {gate: gate_derivation_reasons[gate] for gate in sorted(gates)},
        "legacy_kernel_gate_aliases": {gate: SEMANTIC_KERNEL_GATE_ALIASES[gate] for gate in sorted(gates) if gate in SEMANTIC_KERNEL_GATE_ALIASES},
        "claim_boundary": "Coverage vector is a workload-analysis product. It may drive Step2 legality, but it is not architecture identity or evidence policy.",
    }


def _kernel_gate_contract(
    gate_id: str,
    *,
    coverage_vector: Mapping[str, Any],
    derived_features: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the DFT-scoped machine-readable contract for one kernel gate.

    The contract intentionally describes trigger/shape/evidence semantics only.
    It does not assert that the current candidate or run has passed any gate.
    """

    fft = derived_features.get("fft", {}) if isinstance(derived_features.get("fft"), Mapping) else {}
    hpsi = derived_features.get("hpsi", {}) if isinstance(derived_features.get("hpsi"), Mapping) else {}
    projector = derived_features.get("nonlocal_projector", {}) if isinstance(derived_features.get("nonlocal_projector"), Mapping) else {}
    dense = derived_features.get("dense_linear_algebra", {}) if isinstance(derived_features.get("dense_linear_algebra"), Mapping) else {}
    reductions = derived_features.get("reductions", {}) if isinstance(derived_features.get("reductions"), Mapping) else {}
    host_device = derived_features.get("host_device", {}) if isinstance(derived_features.get("host_device"), Mapping) else {}
    axes = coverage_vector.get("axes", {}) if isinstance(coverage_vector.get("axes"), Mapping) else {}
    display_tags = list(coverage_vector.get("display_stress_tags") or [])

    shape_by_gate: Dict[str, Any] = {
        "fft3d_forward_inverse_batch": {
            "nfft": fft.get("nfft"),
            "nfft_total": fft.get("nfft_total"),
            "batch_transforms_per_scf_estimate": fft.get("transforms_per_scf_estimate"),
            "dtype": "complex_fp64_release_boundary",
        },
        "transpose_layout_conversion": {
            "nfft": fft.get("nfft"),
            "transpose_volume_proxy": fft.get("estimated_fft_points_per_scf"),
            "host_device_bytes_per_scf_estimate": host_device.get("transfer_bytes_per_scf_estimate"),
            "dtype": "complex_fp64_release_boundary",
        },
        "hpsi_local_potential": {
            "npw_effective": hpsi.get("npw_effective"),
            "nbnd": hpsi.get("nbnd"),
            "kpoints": hpsi.get("kpoints"),
            "estimated_complex_points": hpsi.get("estimated_complex_points"),
            "dtype": "complex_fp64_release_boundary",
        },
        "kinetic_energy_apply": {
            "npw_effective": hpsi.get("npw_effective"),
            "nbnd": hpsi.get("nbnd"),
            "kpoints": hpsi.get("kpoints"),
            "dtype": "complex_fp64_release_boundary",
        },
        "nonlocal_projector_apply": {
            "projector_count": projector.get("projector_count"),
            "estimated_projector_work": projector.get("estimated_projector_work"),
            "nbnd": hpsi.get("nbnd"),
            "kpoints": hpsi.get("kpoints"),
            "dtype": "complex_fp64_release_boundary",
        },
        "complex_gemm_tile": {
            "gemm_shape_estimates": dense.get("gemm_shape_estimates", []),
            "orthogonalization_shape": dense.get("orthogonalization_shape"),
            "dtype": "complex_fp64_release_boundary",
        },
        "complex_gemv_tile": {
            "gemv_proxy_shape": [
                hpsi.get("nbnd"),
                hpsi.get("npw_effective"),
            ],
            "dtype": "complex_fp64_release_boundary",
        },
        "reduction_dot_tree": {
            "dot_products_per_scf_estimate": reductions.get("dot_products_per_scf_estimate"),
            "nbnd": hpsi.get("nbnd"),
            "kpoints": hpsi.get("kpoints"),
            "accumulation_dtype": "fp64_release_boundary",
        },
        "dma_hbm_movement_engine": {
            "host_device_bytes_per_scf_estimate": host_device.get("transfer_bytes_per_scf_estimate"),
            "persistent_tensor_candidates": host_device.get("persistent_tensor_candidates", []),
        },
    }
    supported_op_by_gate = {
        "fft3d_forward_inverse_batch": ["fft3d_forward", "fft3d_inverse", "batched_fft"],
        "transpose_layout_conversion": ["layout_transpose", "grid_reorder"],
        "hpsi_local_potential": ["hpsi_local_potential"],
        "kinetic_energy_apply": ["kinetic_energy_apply"],
        "nonlocal_projector_apply": ["nonlocal_projector_apply"],
        "complex_gemm_tile": ["complex_gemm"],
        "complex_gemv_tile": ["complex_gemv"],
        "reduction_dot_tree": ["dot_product", "tree_reduction"],
        "dma_hbm_movement_engine": ["dma_transfer", "hbm_stream"],
    }
    return {
        "schema_version": DFT_KERNEL_GATE_CONTRACT_SCHEMA,
        "gate_id": gate_id,
        "legacy_kernel_gate_alias": SEMANTIC_KERNEL_GATE_ALIASES.get(gate_id),
        "triggered_by": {
            "coverage_axes": dict(axes),
            "display_stress_tags": display_tags,
            "required_kernel_gate": gate_id in set(coverage_vector.get("required_kernel_gates") or []),
        },
        "workload_shape": shape_by_gate.get(gate_id, {}),
        "candidate_requirements": {
            "supported_ops": supported_op_by_gate.get(gate_id, [gate_id]),
            "precision_policy": "fp64_strict_required_for_release_claim",
            "memory_capacity_bytes_lower_bound": host_device.get("transfer_bytes_per_scf_estimate"),
            "claim_scope": "candidate_kernel_specific",
        },
        "evidence_required": {
            "golden_correctness": "required_for_any_accelerated_claim",
            "hls_or_rtl_sim": "required_for_any_accelerated_claim",
            "hls_or_rtl_synth": "required_for_any_accelerated_claim",
            "vivado_fpga_synth_or_impl": "required_for_fpga_claim",
            "dc_asic_synth_timing_area": "required_for_asic_claim",
            "l3": [
                "phase_breakdown_includes_gate_or_legacy_alias",
                "data_movement_summary_if_gate_moves_tensors",
            ],
            "l4": [
                "descriptor_or_completion_region_id_matches_gate_when_offloaded",
                "software_visible_completion_proof_present",
            ],
        },
        "metrics": [
            "latency_ms",
            "energy_proxy_or_joules",
            "resource_utilization",
            "bytes_moved",
            "throughput_or_utilization",
        ],
        "pass_fail": [
            "no_missing_required_stage_for_claim_type",
            "candidate_id_and_kernel_id_match_source_manifest",
            "no_cross_kernel_evidence_reuse",
            "host_bound_rows_must_account_cost_and_cannot_claim_acceleration",
        ],
        "claim_boundary": "Kernel gate contract describes required evidence semantics only; it is not a pass verdict.",
    }


def build_kernel_workload_graph(
    *,
    class_id: str,
    coverage_vector: Mapping[str, Any],
    derived_features: Mapping[str, Any],
) -> Dict[str, Any]:
    gates = list(coverage_vector.get("required_kernel_gates") or [])
    contracts = [
        _kernel_gate_contract(gate, coverage_vector=coverage_vector, derived_features=derived_features)
        for gate in gates
    ]
    contract_by_gate = {contract["gate_id"]: contract for contract in contracts}
    nodes = []
    for gate in gates:
        nodes.append({
            "node_id": f"{class_id}:{gate}",
            "kernel_gate": gate,
            "legacy_kernel_gate_alias": SEMANTIC_KERNEL_GATE_ALIASES.get(gate),
            "shape_source": "dft_derived_scale_features",
            "gate_contract": contract_by_gate[gate],
        })
    return {
        "schema_version": DFT_KERNEL_WORKLOAD_GRAPH_SCHEMA,
        "class_id": class_id,
        "graph_kind": "dft_scf_kernel_summary_graph",
        "regions": [
            "scf_loop_summary",
            "hpsi_apply",
            "orthogonalization_or_diagonalization_shell",
            "density_accumulation",
            "mixing_host_bound",
            "convergence_reduction",
        ],
        "nodes": nodes,
        "kernel_gate_contracts": contracts,
        "derived_feature_refs": {
            "fft": derived_features.get("fft", {}),
            "hpsi": derived_features.get("hpsi", {}),
            "nonlocal_projector": derived_features.get("nonlocal_projector", {}),
            "dense_linear_algebra": derived_features.get("dense_linear_algebra", {}),
            "reductions": derived_features.get("reductions", {}),
            "host_device": derived_features.get("host_device", {}),
        },
        "semantic_preservation": "timing_summary_and_kernel_pressure_only",
        "domain_physics_correctness_claimed": False,
        "claim_boundary": "Kernel workload graph feeds architecture/search legality; it is not numerical correctness or hardware evidence.",
    }


def build_reference_summary(
    *,
    class_id: str,
    output_path: Path | None,
    raw_input_facts: Mapping[str, Any],
    resolved_run_facts: Mapping[str, Any],
) -> Dict[str, Any]:
    output_exists = bool(output_path and output_path.is_file())
    raw_output_sha256 = sha256_file(output_path) if output_exists and output_path is not None else None
    payload = {
        "schema_version": DFT_REFERENCE_SUMMARY_SCHEMA,
        "class_id": class_id,
        "output_path": str(output_path) if output_path else None,
        "raw_output_sha256": raw_output_sha256,
        "hash_algorithm": "sha256",
        "job_done": bool(resolved_run_facts.get("job_done")),
        "scf_converged": bool(resolved_run_facts.get("scf_converged")),
        "convergence_verified": bool(resolved_run_facts.get("job_done") and resolved_run_facts.get("scf_converged")),
        "normalized_facts": {
            "calculation": raw_input_facts.get("calculation"),
            "resolved_nbnd": resolved_run_facts.get("resolved_nbnd"),
            "resolved_kpoints_full": resolved_run_facts.get("resolved_kpoints_full"),
            "resolved_nfft": resolved_run_facts.get("resolved_nfft"),
            "resolved_npw": resolved_run_facts.get("resolved_npw"),
            "valence_electrons": resolved_run_facts.get("valence_electrons"),
            "projector_count": resolved_run_facts.get("projector_count"),
            "scf_iterations": resolved_run_facts.get("scf_iterations"),
            "confidence": resolved_run_facts.get("confidence"),
        },
        "claim_boundary": "Normalized reference summary is QE reference characterization only; final claims require independent correctness and hardware gates.",
    }
    payload["normalized_reference_summary_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "normalized_reference_summary_hash"})
    return payload


def build_layered_workload_profile(
    *,
    class_id: str,
    qe_input_text: str,
    qe_input_path: str,
    qe_input_sha256: str | None,
    pseudo_refs: Sequence[Mapping[str, Any]],
    run_command: Sequence[str] | None,
    reference_output: Mapping[str, Any] | None,
    output_path: Path | None,
    stress_tags: Iterable[str],
    parser_version: str,
    proof_class: str,
) -> Dict[str, Any]:
    raw = parse_qe_raw_input_facts(qe_input_text, class_id=class_id)
    output_text = output_path.read_text(encoding="utf-8", errors="replace") if output_path and output_path.is_file() else None
    resolved = resolved_run_facts_from_output(output_text, raw_input_facts=raw)
    derived = build_derived_scale_features(raw, resolved)
    coverage = build_coverage_vector(
        class_id=class_id,
        stress_tags=stress_tags,
        raw_input_facts=raw,
        derived_features=derived,
        resolved_run_facts=resolved,
    )
    graph = build_kernel_workload_graph(class_id=class_id, coverage_vector=coverage, derived_features=derived)
    reference_summary = build_reference_summary(
        class_id=class_id,
        output_path=output_path,
        raw_input_facts=raw,
        resolved_run_facts=resolved,
    )
    payload = {
        "schema_version": DFT_WORKLOAD_PROFILE_SCHEMA,
        "class_id": class_id,
        "builder_version": DFT_PROFILE_BUILDER_VERSION,
        "source_bundle": build_source_bundle_layer(
            class_id=class_id,
            qe_input_path=qe_input_path,
            qe_input_sha256=qe_input_sha256,
            pseudo_refs=pseudo_refs,
            run_command=run_command,
            reference_output=reference_output,
            parser_version=parser_version,
            proof_class=proof_class,
        ),
        "raw_input_facts": raw,
        "resolved_run_facts": resolved,
        "derived_scale_features": derived,
        "coverage_vector": coverage,
        "kernel_workload_graph": graph,
        "reference_summary": reference_summary,
        "layer_order": [
            "source_bundle",
            "raw_input_facts",
            "resolved_run_facts",
            "derived_scale_features",
            "coverage_vector",
            "kernel_workload_graph",
            "reference_suite_case",
        ],
        "claim_boundary": "DFT reference profile layer artifact; Step1 workload analysis only, not Step2 design identity or Step3/Step4/Step5 evidence policy.",
    }
    payload["profile_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "profile_hash"})
    return payload


def write_layered_workload_profile(profile_path: Path, profile: Mapping[str, Any]) -> Dict[str, Any]:
    write_json(profile_path, dict(profile))
    rel_path = (
        f"{profile_path.parent.name}/{profile_path.name}"
        if profile_path.parent.name == "workload_profiles"
        else str(profile_path.as_posix())
    )
    return {
        "path": rel_path,
        "sha256": sha256_file(profile_path),
        "hash_algorithm": "sha256",
        "schema_version": profile.get("schema_version"),
        "profile_hash": profile.get("profile_hash"),
    }
