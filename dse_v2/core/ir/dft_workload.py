#!/usr/bin/env python3
"""Extended DFT workload with complete QE SCF operations."""

from __future__ import annotations

from dse_v2.core.ir.compute_graph import ComputeGraph, ComputeNode, DataEdge, TensorSpec


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
        metadata={"domain": "dft", "solver": "scf", "iterations": 10},
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
