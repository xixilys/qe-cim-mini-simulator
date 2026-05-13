#!/usr/bin/env python3
"""Extended DFT workload with complete QE SCF operations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec
from dse_v2.core.workload.importers import ImporterRegistry, WorkloadImporter
from dse_v2.core.workload.package import WorkloadPackage, package_from_graph
from dse_v2.core.workload.profiles import WorkloadProfile
from dse_v2.reference_workloads.dft import (
    SourceFact,
    canonicalize_phase_id,
    dft_phase_reference_profile,
    normalize_dft_case_from_facts,
    package_from_dft_case,
)


QE_SCF_REQUIRED_COVERAGE = [
    "h_psi",
    "s_psi",
    "build_H_sub",
    "build_S_sub",
    "diagonalize",
    "subspace_rotation",
    "refresh",
    "residual",
    "rho_out",
    "mix_rho",
    "veff",
]

QE_SCF_MAPPING_PREFERENCES = {
    "h_psi": ["gpu", "fpga", "host"],
    "s_psi": ["gpu", "fpga", "host"],
    "vnl": ["cim", "gpu", "fpga", "host"],
    "precondition": ["cim", "fpga", "gpu", "host"],
    "orthogonalize": ["fpga", "gpu", "host"],
    "build_H_sub": ["fpga", "gpu", "host"],
    "build_S_sub": ["fpga", "gpu", "host"],
    "diagonalize": ["gpu", "fpga", "host"],
    "subspace_rotation": ["gpu", "fpga", "host"],
    "refresh": ["gpu", "fpga", "host"],
    "residual": ["cim", "fpga", "gpu", "host"],
    "rho_out": ["fpga", "gpu", "host"],
    "mix_rho": ["cim", "fpga", "host"],
    "veff": ["fpga", "gpu", "host"],
}


def create_complete_qe_scf_graph(
    npw: int = 2945,
    nkb: int = 144,
    m: int = 16,
    nfft: int = 32768,
    graph_id: str = "qe_scf_complete",
) -> ComputeGraph:
    """Create a complete QE SCF iteration graph with all major operations.
    
    Operations:
    1. h_psi: Apply Hamiltonian (H = T + V_loc + V_nl)
    2. s_psi: Apply overlap operator
    3. vnl: Apply non-local potential
    4. precondition: Precondition residual
    5. orthogonalize: Gram-Schmidt orthogonalization
    6. build_H_sub: Build reduced Hamiltonian
    7. build_S_sub: Build reduced overlap matrix
    8. diagonalize: Generalized Hermitian eigensolver
    9. subspace_rotation: Rotate subspace
    10. refresh: Update wavefunctions
    11. residual: Residual/convergence vector update
    12. rho_out: Compute charge density
    13. mix_rho: Mix charge density (Broyden/Pulay)
    14. veff: Compute effective potential
    """
    graph = ComputeGraph(
        graph_id=graph_id,
        metadata={"domain": "dft_reference", "workload_family": "dft_qe_reference", "profile_id": "qe_scf_reference", "importer_id": "qe_reference_fixture", "solver": "scf", "iterations": 10},
    )
    
    nbnd = m
    
    # Node 1: h_psi - Kinetic + local potential
    h_psi_flops = 2.0 * npw * nkb * m
    h_psi_memory = (npw * nkb + npw * m + nkb * m) * 8
    graph.add_node(ComputeNode(
        node_id="h_psi",
        op_type="gemm",
        inputs=["psi", "H_loc"],
        outputs=["h_psi_out"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "H_loc": TensorSpec(shape=(npw, npw), dtype="FP64"),
        },
        output_specs={"h_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=h_psi_flops,
        estimated_memory_bytes=h_psi_memory,
        attributes={"description": "Apply local Hamiltonian"},
    ))
    
    # Node 2: s_psi - Overlap operator application
    s_psi_flops = 2.0 * npw * nkb * m
    s_psi_memory = (npw * nkb + npw * m + nkb * m) * 8
    graph.add_node(ComputeNode(
        node_id="s_psi",
        op_type="gemm",
        inputs=["psi", "S_op"],
        outputs=["s_psi_out"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "S_op": TensorSpec(shape=(npw, npw), dtype="FP64"),
        },
        output_specs={"s_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=s_psi_flops,
        estimated_memory_bytes=s_psi_memory,
        attributes={"description": "Apply overlap operator"},
    ))
    
    # Node 3: vnl - Non-local potential
    nproj = 8
    vnl_flops = 2.0 * npw * nproj * nkb * m + 2.0 * nproj * nproj * nkb * m
    vnl_memory = (npw * nproj + nproj * nproj + npw * nkb) * 8
    graph.add_node(ComputeNode(
        node_id="vnl",
        op_type="gemm",
        inputs=["h_psi_out", "beta", "D"],
        outputs=["h_psi_vnl"],
        input_specs={
            "h_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "beta": TensorSpec(shape=(npw, nproj), dtype="FP64"),
            "D": TensorSpec(shape=(nproj, nproj), dtype="FP64"),
        },
        output_specs={"h_psi_vnl": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=vnl_flops,
        estimated_memory_bytes=vnl_memory,
        attributes={"description": "Apply non-local potential"},
    ))
    
    # Node 4: precondition - Diagonal preconditioner
    precond_flops = npw * nkb * m
    precond_memory = (npw * nkb + npw * nkb) * 8
    graph.add_node(ComputeNode(
        node_id="precondition",
        op_type="elementwise",
        inputs=["h_psi_vnl", "precond_matrix"],
        outputs=["precond_out"],
        input_specs={
            "h_psi_vnl": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "precond_matrix": TensorSpec(shape=(npw,), dtype="FP64"),
        },
        output_specs={"precond_out": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=precond_flops,
        estimated_memory_bytes=precond_memory,
        attributes={"description": "Precondition residual"},
    ))
    
    # Node 5: orthogonalize - Gram-Schmidt
    ortho_flops = 2.0 * npw * m * m * nkb
    ortho_memory = (npw * nkb + m * m) * 8
    graph.add_node(ComputeNode(
        node_id="orthogonalize",
        op_type="reduction",
        inputs=["precond_out", "psi"],
        outputs=["ortho_out"],
        input_specs={
            "precond_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
        },
        output_specs={"ortho_out": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=ortho_flops,
        estimated_memory_bytes=ortho_memory,
        attributes={"description": "Gram-Schmidt orthogonalization"},
    ))
    
    # Node 6: build_H_sub - Reduced Hamiltonian
    build_H_flops = 2.0 * npw * nkb * m * m
    build_H_memory = (npw * nkb + m * m) * 8
    graph.add_node(ComputeNode(
        node_id="build_H_sub",
        op_type="reduction",
        inputs=["ortho_out", "psi"],
        outputs=["H_sub"],
        input_specs={
            "ortho_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
        },
        output_specs={"H_sub": TensorSpec(shape=(m, m), dtype="FP64")},
        estimated_flops=build_H_flops,
        estimated_memory_bytes=build_H_memory,
        attributes={"description": "Build reduced subspace Hamiltonian"},
    ))
    
    # Node 7: build_S_sub - Reduced overlap
    build_S_flops = 2.0 * npw * nkb * m * m
    build_S_memory = (npw * nkb + m * m) * 8
    graph.add_node(ComputeNode(
        node_id="build_S_sub",
        op_type="reduction",
        inputs=["psi", "s_psi_out"],
        outputs=["S_sub"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "s_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
        },
        output_specs={"S_sub": TensorSpec(shape=(m, m), dtype="FP64")},
        estimated_flops=build_S_flops,
        estimated_memory_bytes=build_S_memory,
        attributes={"description": "Build reduced overlap matrix"},
    ))
    
    # Node 8: diagonalize - Generalized eigensolver
    diag_flops = (m ** 3) * 8.0
    diag_memory = (m * m + m + m * m) * 8
    graph.add_node(ComputeNode(
        node_id="diagonalize",
        op_type="eigen",
        inputs=["H_sub", "S_sub"],
        outputs=["eigenvalues", "eigenvectors"],
        input_specs={
            "H_sub": TensorSpec(shape=(m, m), dtype="FP64"),
            "S_sub": TensorSpec(shape=(m, m), dtype="FP64"),
        },
        output_specs={
            "eigenvalues": TensorSpec(shape=(m,), dtype="FP64"),
            "eigenvectors": TensorSpec(shape=(m, m), dtype="FP64"),
        },
        estimated_flops=diag_flops,
        estimated_memory_bytes=diag_memory,
        attributes={"description": "Generalized Hermitian eigensolver"},
    ))
    
    # Node 9: subspace_rotation
    rotation_flops = 2.0 * npw * nkb * m * m
    rotation_memory = (npw * nkb + m * m + npw * nkb) * 8
    graph.add_node(ComputeNode(
        node_id="subspace_rotation",
        op_type="gemm",
        inputs=["psi", "eigenvectors"],
        outputs=["psi_rotated"],
        input_specs={
            "psi": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "eigenvectors": TensorSpec(shape=(m, m), dtype="FP64"),
        },
        output_specs={"psi_rotated": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=rotation_flops,
        estimated_memory_bytes=rotation_memory,
        attributes={"description": "Rotate subspace"},
    ))
    
    # Node 10: refresh - Update wavefunctions
    refresh_flops = 2.0 * npw * nkb * m
    refresh_memory = (npw * nkb + npw * nkb) * 8
    graph.add_node(ComputeNode(
        node_id="refresh",
        op_type="gemm",
        inputs=["psi_rotated", "eigenvectors"],
        outputs=["psi_new"],
        input_specs={
            "psi_rotated": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "eigenvectors": TensorSpec(shape=(m, m), dtype="FP64"),
        },
        output_specs={"psi_new": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        estimated_flops=refresh_flops,
        estimated_memory_bytes=refresh_memory,
        attributes={"description": "Update wavefunctions"},
    ))
    
    # Node 11: residual - Residual/convergence update
    residual_flops = 4.0 * npw * nkb * m
    residual_memory = (npw * nkb + npw * nkb + npw * nkb + m) * 8
    graph.add_node(ComputeNode(
        node_id="residual",
        op_type="elementwise",
        inputs=["psi_new", "h_psi_vnl", "s_psi_out", "eigenvalues"],
        outputs=["residual_norm"],
        input_specs={
            "psi_new": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "h_psi_vnl": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "s_psi_out": TensorSpec(shape=(npw, nkb), dtype="FP64"),
            "eigenvalues": TensorSpec(shape=(m,), dtype="FP64"),
        },
        output_specs={"residual_norm": TensorSpec(shape=(m,), dtype="FP64")},
        estimated_flops=residual_flops,
        estimated_memory_bytes=residual_memory,
        attributes={"description": "Compute residual and convergence norm"},
    ))
    
    # Node 12: rho_out - Charge density
    rho_flops = nfft * nkb * m * 2.0
    rho_memory = (nfft + npw * nkb) * 8
    graph.add_node(ComputeNode(
        node_id="rho_out",
        op_type="fft",
        inputs=["psi_new"],
        outputs=["rho"],
        input_specs={"psi_new": TensorSpec(shape=(npw, nkb), dtype="FP64")},
        output_specs={"rho": TensorSpec(shape=(nfft,), dtype="FP64")},
        estimated_flops=rho_flops,
        estimated_memory_bytes=rho_memory,
        attributes={"description": "Compute charge density"},
    ))
    
    # Node 13: mix_rho - Density mixing
    mix_flops = nfft * 2.0
    mix_memory = (nfft + nfft) * 8
    graph.add_node(ComputeNode(
        node_id="mix_rho",
        op_type="elementwise",
        inputs=["rho", "rho_old"],
        outputs=["rho_mixed"],
        input_specs={
            "rho": TensorSpec(shape=(nfft,), dtype="FP64"),
            "rho_old": TensorSpec(shape=(nfft,), dtype="FP64"),
        },
        output_specs={"rho_mixed": TensorSpec(shape=(nfft,), dtype="FP64")},
        estimated_flops=mix_flops,
        estimated_memory_bytes=mix_memory,
        attributes={"description": "Broyden/Pulay density mixing"},
    ))
    
    # Node 14: veff - Effective potential
    veff_flops = nfft * 4.0
    veff_memory = (nfft + nfft) * 8
    graph.add_node(ComputeNode(
        node_id="veff",
        op_type="fft",
        inputs=["rho_mixed", "vxc"],
        outputs=["V_eff"],
        input_specs={
            "rho_mixed": TensorSpec(shape=(nfft,), dtype="FP64"),
            "vxc": TensorSpec(shape=(nfft,), dtype="FP64"),
        },
        output_specs={"V_eff": TensorSpec(shape=(nfft,), dtype="FP64")},
        estimated_flops=veff_flops,
        estimated_memory_bytes=veff_memory,
        attributes={"description": "Compute effective potential"},
    ))
    
    # Edges with tensor specs
    edges = [
        ("h_psi", "vnl", "h_psi_out", (npw, nkb)),
        ("s_psi", "build_S_sub", "s_psi_out", (npw, nkb)),
        ("vnl", "precondition", "h_psi_vnl", (npw, nkb)),
        ("precondition", "orthogonalize", "precond_out", (npw, nkb)),
        ("orthogonalize", "build_H_sub", "ortho_out", (npw, nkb)),
        ("build_H_sub", "diagonalize", "H_sub", (m, m)),
        ("build_S_sub", "diagonalize", "S_sub", (m, m)),
        ("diagonalize", "subspace_rotation", "eigenvectors", (m, m)),
        ("subspace_rotation", "refresh", "psi_rotated", (npw, nkb)),
        ("refresh", "residual", "psi_new", (npw, nkb)),
        ("vnl", "residual", "h_psi_vnl", (npw, nkb)),
        ("s_psi", "residual", "s_psi_out", (npw, nkb)),
        ("diagonalize", "residual", "eigenvalues", (m,)),
        ("refresh", "rho_out", "psi_new", (npw, nkb)),
        ("residual", "rho_out", "residual_norm", (m,)),
        ("rho_out", "mix_rho", "rho", (nfft,)),
        ("mix_rho", "veff", "rho_mixed", (nfft,)),
    ]
    
    for src, dst, tensor_name, shape in edges:
        graph.add_edge(DataEdge(src, dst, tensor_name, TensorSpec(shape=shape, dtype="FP64")))
    
    return graph


def create_short_qe_scf_graph(graph_id: str = "dft_scf") -> ComputeGraph:
    """Create a small QE adapter graph for legacy backend regression tests."""
    graph = ComputeGraph(
        graph_id=graph_id,
        metadata={"domain": "dft_reference", "workload_family": "dft_qe_reference", "profile_id": "qe_scf_reference", "importer_id": "qe_reference_fixture", "solver": "scf", "iterations": 10},
    )
    npw, nkb, m = 2945, 144, 16
    graph.add_node(ComputeNode(
        node_id="h_psi",
        op_type="gemm",
        inputs=["psi", "H"],
        outputs=["h_psi_out"],
        estimated_flops=2.0 * npw * nkb * m,
        estimated_memory_bytes=(npw * nkb + npw * m + nkb * m) * 8,
        attributes={"adapter:dft_qe": {"description": "Apply Hamiltonian to wavefunctions"}},
    ))
    graph.add_node(ComputeNode(
        node_id="build_H_sub",
        op_type="reduction",
        inputs=["h_psi_out", "psi"],
        outputs=["H_sub"],
        estimated_flops=npw * m * m,
        estimated_memory_bytes=(npw * m + m * m) * 8,
        attributes={"adapter:dft_qe": {"description": "Build reduced subspace Hamiltonian"}},
    ))
    graph.add_node(ComputeNode(
        node_id="diagonalize",
        op_type="eigen",
        inputs=["H_sub"],
        outputs=["eigenvalues", "eigenvectors"],
        estimated_flops=(nkb ** 3) * m / 16.0,
        estimated_memory_bytes=(nkb * nkb + m + m * m) * 8,
        attributes={"adapter:dft_qe": {"description": "Generalized Hermitian eigensolver"}},
    ))
    graph.add_node(ComputeNode(
        node_id="refresh",
        op_type="gemm",
        inputs=["psi", "eigenvectors"],
        outputs=["psi_new"],
        estimated_flops=2.0 * npw * m * m,
        estimated_memory_bytes=(npw * m + m * m + npw * m) * 8,
        attributes={"adapter:dft_qe": {"description": "Update wavefunctions from eigenvectors"}},
    ))
    graph.add_edge(DataEdge("h_psi", "build_H_sub", "h_psi_out", TensorSpec(shape=(npw, nkb), dtype="FP64")))
    graph.add_edge(DataEdge("build_H_sub", "diagonalize", "H_sub", TensorSpec(shape=(nkb, nkb), dtype="FP64")))
    graph.add_edge(DataEdge("diagonalize", "refresh", "eigenvectors", TensorSpec(shape=(nkb, nkb), dtype="FP64")))
    return graph


def qe_scf_reference_profile() -> WorkloadProfile:
    """Return the optional QE SCF reference profile.

    This profile is intentionally outside the core workload registry.  It is a
    regression fixture/reference plugin for DFT/QE-style SCF graphs, not a core
    DSE default.
    """
    return WorkloadProfile(
        profile_id="qe_scf_reference",
        profile_version="v1",
        workload_family="dft_qe_reference",
        accepted_source_kinds=["generated", "trace", "dump", "hand_authored"],
        graph_pattern="scf_shell_graph",
        lowering_policy="identity_dag_or_profile_declared_scf_summary",
        default_mapping_policies=["host-baseline", "fpga-operator-sweep", "hardware-diagonalization", "all-operator-offload", "cim-heavy", "fallback-mix"],
        mapping_preferences=dict(QE_SCF_MAPPING_PREFERENCES),
        domain_validation={
            "timing_only_allowed": True,
            "correctness_artifacts": ["profile_qe_residual_density_eigen_report.json"],
            "correctness_claim_requires_profile_evidence": True,
            "unclaimed_domain_correctness": "QE FP64 residual/density/eigenvector physics correctness is not inferred from generic timing evidence.",
        },
        required_coverage=list(QE_SCF_REQUIRED_COVERAGE),
        unavailable_metric_labels=["qe_fp64_physics_correctness", "scf_convergence"],
        description="Optional Quantum ESPRESSO SCF reference profile used as a non-core regression fixture.",
        plugin_metadata={"reference_only": True, "domain": "dft_qe"},
    )


class QeReferenceImporter(WorkloadImporter):
    importer_id = "qe_reference_fixture"
    importer_version = "v1"
    supported_source_kinds = ["generated", "trace", "dump", "hand_authored"]
    compatible_profiles = ["qe_scf_reference"]

    def import_workload(
        self,
        source: Any = None,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile)
        graph = source if isinstance(source, ComputeGraph) else create_complete_qe_scf_graph(
            npw=int(parameters.get("npw", 2945)),
            nkb=int(parameters.get("nkb", 144)),
            m=int(parameters.get("m", 16)),
            nfft=int(parameters.get("nfft", 32768)),
            graph_id=str(parameters.get("graph_id", "qe_scf_reference_graph")),
        )
        graph.metadata["profile"] = profile_payload
        graph.metadata["workflow"] = profile_payload
        graph.metadata["profile_id"] = str(profile_payload.get("profile_id", "qe_scf_reference"))
        graph.metadata["importer_id"] = self.importer_id
        return package_from_graph(
            graph,
            workload_id=str(parameters.get("workload_id", graph.graph_id)),
            workload_family=str(profile_payload.get("workload_family", "dft_qe_reference")),
            profile_id=str(profile_payload.get("profile_id", "qe_scf_reference")),
            profile_version=str(profile_payload.get("profile_version", "v1")),
            importer_id=self.importer_id,
            importer_version=self.importer_version,
            claim_boundary=str(parameters.get("claim_boundary", profile_payload.get("default_claim_boundary", "full_workload"))),
            source_kind=str(parameters.get("source_kind", "generated")),
            source_path=parameters.get("source_path"),
            domain_metadata={
                "npw": int(parameters.get("npw", 2945)),
                "nkb": int(parameters.get("nkb", 144)),
                "m": int(parameters.get("m", 16)),
                "nfft": int(parameters.get("nfft", 32768)),
                "precision": str(parameters.get("precision", "complex_fp64")),
                **dict(parameters.get("domain_metadata", {}) or {}),
            },
            profile=profile_payload,
        )


# Compatibility alias for tests or manual imports.  The class lives in this
# optional reference module rather than the core workload registry.
DftQeReferenceImporter = QeReferenceImporter


def register_qe_reference_importer(registry: ImporterRegistry) -> ImporterRegistry:
    return registry.register(QeReferenceImporter())


def create_qe_reference_package(parameters: Optional[Mapping[str, Any]] = None) -> WorkloadPackage:
    return QeReferenceImporter().import_workload(None, profile=qe_scf_reference_profile(), parameters=parameters)


# ---------------------------------------------------------------------------
# DFT-first Step1 frontdoor: QE source facts -> DftCase -> generic graph.
# This path is deliberately separate from the legacy QE reference fixture above.
# ---------------------------------------------------------------------------

_QE_FLOAT = r"[-+]?\d+(?:\.\d*)?(?:[eEdD][-+]?\d+)?"
_QE_ASSIGNMENT_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>[^,!/]+)")
_QE_TIME_RE = re.compile(
    rf"^\s*(?P<label>[A-Za-z0-9_()./+-]+)\s*:\s*.*?(?P<seconds>{_QE_FLOAT})\s*s\s*WALL",
    re.IGNORECASE,
)


def _read_text_source(source: Any) -> tuple[str, Optional[str]]:
    if source is None:
        return "", None
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8"), str(source)
    if isinstance(source, str):
        path = Path(source)
        if "\n" not in source and path.exists():
            return path.read_text(encoding="utf-8"), str(path)
        return source, None
    raise TypeError(f"expected text or path source, got {type(source).__name__}")


def _strip_qe_comment(line: str) -> str:
    in_quote = False
    quote_char = ""
    for idx, char in enumerate(line):
        if char in {"'", '"'}:
            if in_quote and char == quote_char:
                in_quote = False
                quote_char = ""
            elif not in_quote:
                in_quote = True
                quote_char = char
        if char == "!" and not in_quote:
            return line[:idx]
    return line


def _parse_qe_value(raw: str) -> Any:
    value = raw.strip().rstrip(",").strip()
    if not value:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {".true.", "true", "t"}:
        return True
    if lowered in {".false.", "false", "f"}:
        return False
    normalized = value.replace("D", "E").replace("d", "e")
    try:
        if re.fullmatch(r"[-+]?\d+", normalized):
            return int(normalized)
        if re.fullmatch(_QE_FLOAT, normalized):
            return float(normalized)
    except Exception:
        pass
    return value


def _fact(
    field: str,
    value: Any,
    *,
    unit: str = "",
    source_type: str,
    source_path: Optional[str],
    evidence_level: str,
    confidence: str = "medium",
    raw_excerpt: Optional[str] = None,
    run_id: Optional[str] = None,
) -> SourceFact:
    return SourceFact(
        field=field,
        value=value,
        unit=unit,
        source_type=source_type,
        source_path=source_path,
        evidence_level=evidence_level,
        confidence=confidence,
        raw_excerpt=raw_excerpt,
        run_id=run_id,
    )


def parse_qe_pw_input(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse a small, deterministic subset of a QE ``pw.x`` input file.

    The parser emits provenance facts only.  Graph construction is intentionally
    performed later by DFT normalization so source frontends cannot smuggle in
    mapping/schedule decisions.
    """
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    facts: List[SourceFact] = []
    current_namelist: Optional[str] = None
    assignments: Dict[str, Any] = {}
    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        line = _strip_qe_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("&"):
            current_namelist = line[1:].strip().lower()
            continue
        if line.startswith("/"):
            current_namelist = None
            continue
        if current_namelist:
            for match in _QE_ASSIGNMENT_RE.finditer(line):
                key = match.group("key").lower()
                value = _parse_qe_value(match.group("value"))
                assignments[f"{current_namelist}.{key}"] = value
                field = _qe_assignment_field(current_namelist, key)
                if field:
                    unit = _qe_field_unit(field)
                    facts.append(_fact(
                        field,
                        value,
                        unit=unit,
                        source_type="input",
                        source_path=path,
                        evidence_level="declared_input",
                        confidence="medium",
                        raw_excerpt=raw_line.strip(),
                        run_id=run_id,
                    ))
            continue
        if line.upper().startswith("K_POINTS"):
            mode = line.split(maxsplit=1)[1].strip().lower() if len(line.split(maxsplit=1)) > 1 else "unknown"
            facts.append(_fact(
                "input.k_points_mode",
                mode,
                source_type="input",
                source_path=path,
                evidence_level="declared_input",
                confidence="medium",
                raw_excerpt=raw_line.strip(),
                run_id=run_id,
            ))
            if mode.startswith("automatic") and idx + 1 < len(lines):
                next_line = _strip_qe_comment(lines[idx + 1]).strip()
                parts = [int(float(part)) for part in next_line.split()[:6] if re.fullmatch(r"[-+]?\d+(?:\.0*)?", part)]
                if len(parts) >= 3:
                    facts.append(_fact(
                        "dimension.kpoint_grid",
                        parts[:3],
                        unit="grid",
                        source_type="input",
                        source_path=path,
                        evidence_level="declared_input",
                        confidence="medium",
                        raw_excerpt=next_line,
                        run_id=run_id,
                    ))
                    facts.append(_fact(
                        "dimension.kpoint_count",
                        max(1, parts[0] * parts[1] * parts[2]),
                        unit="count",
                        source_type="heuristic",
                        source_path=path,
                        evidence_level="pre_symmetry_estimate",
                        confidence="low",
                        raw_excerpt=next_line,
                        run_id=run_id,
                    ))
    if "system.ecutrho" not in assignments and "system.ecutwfc" in assignments:
        facts.append(_fact(
            "parameter.ecutrho",
            float(assignments["system.ecutwfc"]) * 4.0,
            unit="Ry",
            source_type="heuristic",
            source_path=path,
            evidence_level="qe_default_style_estimate",
            confidence="low",
            raw_excerpt="generated from ecutwfc because ecutrho was absent",
            run_id=run_id,
        ))
    return facts


def _qe_assignment_field(namelist: str, key: str) -> Optional[str]:
    mapping = {
        ("control", "calculation"): "input.calculation",
        ("system", "nat"): "dimension.nat",
        ("system", "ntyp"): "dimension.ntyp",
        ("system", "nbnd"): "dimension.nbnd",
        ("system", "nspin"): "dimension.nspin",
        ("system", "ecutwfc"): "parameter.ecutwfc",
        ("system", "ecutrho"): "parameter.ecutrho",
        ("system", "occupations"): "parameter.occupations",
        ("system", "input_dft"): "parameter.input_dft",
        ("electrons", "conv_thr"): "parameter.conv_thr",
        ("electrons", "mixing_beta"): "parameter.mixing_beta",
        ("electrons", "diagonalization"): "parameter.diagonalization",
        ("electrons", "electron_maxstep"): "iteration.scf.maxstep",
    }
    return mapping.get((namelist, key))


def _qe_field_unit(field: str) -> str:
    if field in {"parameter.ecutwfc", "parameter.ecutrho"}:
        return "Ry"
    if field in {"parameter.conv_thr"}:
        return "Ry"
    if field.startswith("dimension.") or field.startswith("iteration."):
        return "count"
    return ""


def parse_qe_pw_log(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse selected observed dimensions/timing facts from QE stdout."""
    text, detected_path = _read_text_source(source)
    path = source_path or detected_path
    facts: List[SourceFact] = []
    iteration_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        match = re.search(r"number of k points\s*=\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.kpoint_count", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"number of kohn-sham states\s*=\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.nbnd", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"number of plane waves\s*=\s*(\d+)", lower)
        if match:
            facts.append(_fact("dimension.npw", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"(?:fft|dense|smooth).*?(?:grid|dimensions).*?\(?\s*(\d+)\s*[,x ]+\s*(\d+)\s*[,x ]+\s*(\d+)\s*\)?", lower)
        if match:
            grid = [int(match.group(1)), int(match.group(2)), int(match.group(3))]
            facts.append(_fact("dimension.fft_grid", grid, unit="grid", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="medium", raw_excerpt=line, run_id=run_id))
            facts.append(_fact("dimension.nfft", grid[0] * grid[1] * grid[2], unit="count", source_type="log", source_path=path, evidence_level="observed_preprocessed", confidence="medium", raw_excerpt=line, run_id=run_id))
            continue
        match = re.search(r"convergence has been achieved in\s+(\d+)\s+iterations", lower)
        if match:
            facts.append(_fact("iteration.scf.count", int(match.group(1)), unit="count", source_type="log", source_path=path, evidence_level="observed_runtime", confidence="high", raw_excerpt=line, run_id=run_id))
            continue
        if re.search(r"iteration\s*#\s*\d+", lower):
            iteration_count += 1
        timing = _QE_TIME_RE.match(line)
        if timing:
            label = timing.group("label")
            phase_id = canonicalize_phase_id(label, extension_namespace="qe")
            seconds = float(timing.group("seconds").replace("D", "E").replace("d", "e"))
            facts.append(_fact(
                f"phase_timing.{phase_id}.wall_seconds",
                seconds,
                unit="s",
                source_type="log",
                source_path=path,
                evidence_level="observed_timing",
                confidence="medium",
                raw_excerpt=line,
                run_id=run_id,
            ))
    if iteration_count:
        facts.append(_fact("iteration.scf.count", iteration_count, unit="count", source_type="log", source_path=path, evidence_level="observed_runtime", confidence="medium", raw_excerpt="counted iteration # lines", run_id=run_id))
    return facts


def parse_qe_profile(source: Any, *, source_path: Optional[str] = None, run_id: Optional[str] = None) -> List[SourceFact]:
    """Parse QE timing/profile summaries from JSON, mappings, or simple text."""
    path = source_path
    payload: Any = source
    if isinstance(source, (str, Path)):
        text, detected_path = _read_text_source(source)
        path = path or detected_path
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            payload = json.loads(stripped)
        else:
            return _parse_qe_profile_text(text, source_path=path, run_id=run_id)
    facts: List[SourceFact] = []
    if isinstance(payload, Mapping):
        items = payload.get("phases", payload.get("phase_timings", payload))
        if isinstance(items, Mapping):
            iterable = items.items()
        elif isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            iterable = []
            for item in items:
                if isinstance(item, Mapping):
                    label = item.get("phase_id", item.get("phase", item.get("label", item.get("name", "unknown"))))
                    seconds = item.get("wall_seconds", item.get("seconds", item.get("time_seconds")))
                    iterable.append((label, seconds))
        else:
            iterable = []
        for label, seconds in iterable:
            if seconds is None:
                continue
            try:
                value = float(seconds)
            except Exception:
                continue
            phase_id = canonicalize_phase_id(str(label), extension_namespace="qe")
            facts.append(_fact(
                f"phase_timing.{phase_id}.wall_seconds",
                value,
                unit="s",
                source_type="profile",
                source_path=path,
                evidence_level="observed_timing",
                confidence="high",
                raw_excerpt=f"{label}: {seconds}",
                run_id=run_id,
            ))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for item in payload:
            if isinstance(item, Mapping):
                facts.extend(parse_qe_profile({"phases": [item]}, source_path=path, run_id=run_id))
    return facts


def _parse_qe_profile_text(text: str, *, source_path: Optional[str], run_id: Optional[str]) -> List[SourceFact]:
    facts: List[SourceFact] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        timing = _QE_TIME_RE.match(line)
        if timing:
            label = timing.group("label")
            seconds = float(timing.group("seconds").replace("D", "E").replace("d", "e"))
        else:
            parts = re.split(r"[,\s]+", line)
            if len(parts) < 2:
                continue
            label = parts[0]
            try:
                seconds = float(parts[1])
            except Exception:
                continue
        phase_id = canonicalize_phase_id(label, extension_namespace="qe")
        facts.append(_fact(
            f"phase_timing.{phase_id}.wall_seconds",
            seconds,
            unit="s",
            source_type="profile",
            source_path=source_path,
            evidence_level="observed_timing",
            confidence="high",
            raw_excerpt=line,
            run_id=run_id,
        ))
    return facts


def normalize_qe_dft_case(
    facts: Sequence[SourceFact | Mapping[str, Any]],
    *,
    case_id: str = "qe_pw_static_case",
    profile_id: str = "dft_qe_pw_static",
    importer_id: str = "dft_qe_pw",
    claim_boundary: str = "diagnostic",
    parameters: Optional[Mapping[str, Any]] = None,
):
    return normalize_dft_case_from_facts(
        facts,
        case_id=case_id,
        source_program="qe_pw",
        workload_family="dft",
        profile_id=profile_id,
        importer_id=importer_id,
        claim_boundary=claim_boundary,
        parameters=parameters,
    )


class DftQePwImporter(WorkloadImporter):
    """QE pw.x source importer for the DFT-first Step1 frontdoor."""

    importer_id = "dft_qe_pw"
    importer_version = "v1"
    supported_source_kinds = ["qe_pw_bundle", "qe_pw_input", "qe_pw_log", "qe_pw_profile", "dft_config", "generated"]
    compatible_profiles = ["dft_qe_pw_static", "dft"]

    def import_workload(
        self,
        source: Any = None,
        *,
        profile: WorkloadProfile | Mapping[str, Any],
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> WorkloadPackage:
        parameters = dict(parameters or {})
        profile_payload = profile.to_dict() if isinstance(profile, WorkloadProfile) else dict(profile)
        profile_id = str(profile_payload.get("profile_id", "dft_qe_pw_static"))
        claim_boundary = str(parameters.get("claim_boundary", profile_payload.get("default_claim_boundary", "diagnostic")))
        case_id = str(parameters.get("case_id", parameters.get("workload_id", parameters.get("graph_id", "qe_pw_static_case"))))
        source_kind = str(parameters.get("source_kind", "qe_pw_bundle"))
        run_id = str(parameters.get("run_id")) if parameters.get("run_id") is not None else None

        if hasattr(source, "to_dict") and getattr(source, "schema_version", "") == "dse.dft.case.v1":
            case = source
        else:
            facts = self._collect_facts(source, parameters, source_kind=source_kind, run_id=run_id)
            case = normalize_qe_dft_case(
                facts,
                case_id=case_id,
                profile_id=profile_id,
                importer_id=self.importer_id,
                claim_boundary=claim_boundary,
                parameters=parameters,
            )
        package = package_from_dft_case(
            case,
            profile=profile_payload,
            graph_id=str(parameters.get("graph_id", f"{case_id}_graph")),
            source_kind=source_kind,
            source_path=parameters.get("source_path"),
        )
        package.importer["importer_version"] = self.importer_version
        return package

    def _collect_facts(
        self,
        source: Any,
        parameters: Mapping[str, Any],
        *,
        source_kind: str,
        run_id: Optional[str],
    ) -> List[SourceFact]:
        facts: List[SourceFact] = []
        if isinstance(source, Mapping):
            if "facts" in source:
                for item in source.get("facts", []) or []:
                    facts.append(item if isinstance(item, SourceFact) else SourceFact.from_dict(item))
            input_source = _first_present(source, "pw_input", "input", "input_text")
            log_source = _first_present(source, "pw_log", "log", "log_text", "stdout")
            profile_source = _first_present(source, "profile", "profile_text", "profile_json", "timing")
            if input_source is not None:
                facts.extend(parse_qe_pw_input(input_source, source_path=_source_path_hint(source, "input_path", "pw_input_path"), run_id=run_id))
            if log_source is not None:
                facts.extend(parse_qe_pw_log(log_source, source_path=_source_path_hint(source, "log_path", "pw_log_path"), run_id=run_id))
            if profile_source is not None:
                facts.extend(parse_qe_profile(profile_source, source_path=_source_path_hint(source, "profile_path"), run_id=run_id))
        elif source is not None:
            if source_kind == "qe_pw_input":
                facts.extend(parse_qe_pw_input(source, source_path=parameters.get("source_path"), run_id=run_id))
            elif source_kind == "qe_pw_log":
                facts.extend(parse_qe_pw_log(source, source_path=parameters.get("source_path"), run_id=run_id))
            elif source_kind == "qe_pw_profile":
                facts.extend(parse_qe_profile(source, source_path=parameters.get("source_path"), run_id=run_id))
        for key, parser in [
            ("input_path", parse_qe_pw_input),
            ("pw_input_path", parse_qe_pw_input),
            ("log_path", parse_qe_pw_log),
            ("pw_log_path", parse_qe_pw_log),
            ("profile_path", parse_qe_profile),
        ]:
            if parameters.get(key):
                facts.extend(parser(str(parameters[key]), source_path=str(parameters[key]), run_id=run_id))
        for key in ["npw", "nfft", "nbnd", "kpoint_count", "nat", "ntyp"]:
            if key in parameters:
                field = "dimension.kpoint_count" if key == "kpoint_count" else f"dimension.{key}"
                facts.append(_fact(
                    field,
                    int(parameters[key]),
                    unit="count",
                    source_type="generated",
                    source_path=parameters.get("source_path"),
                    evidence_level="caller_parameter",
                    confidence="medium",
                    raw_excerpt=f"parameter.{key}",
                    run_id=run_id,
                ))
        return facts


DftQePwStaticImporter = DftQePwImporter


def register_dft_qe_importer(registry: ImporterRegistry) -> ImporterRegistry:
    return registry.register(DftQePwImporter())


def dft_qe_pw_profile() -> WorkloadProfile:
    return dft_phase_reference_profile()


def create_dft_qe_package(source: Any = None, parameters: Optional[Mapping[str, Any]] = None) -> WorkloadPackage:
    return DftQePwImporter().import_workload(source, profile=dft_phase_reference_profile(), parameters=parameters)


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _source_path_hint(mapping: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if mapping.get(key):
            return str(mapping[key])
    return None
