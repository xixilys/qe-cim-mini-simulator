#!/usr/bin/env python3
"""Registries for the QE-IC Layer-1 workload-suite contract.

The registry is intentionally QE-IC scoped.  It documents workload-family facts
for the active DFT/QE proof path without adding QE-specific fields to the
domain-neutral core IR or generic DSE contracts.
"""

from __future__ import annotations

from typing import Any, Mapping

from dse_v2.workloads.qe_ic.schema import PROFILING_CONTRACT_REQUIRED_FIELDS


def _motif(
    name: str,
    *,
    category: str,
    description: str,
    provisional: bool = False,
    measurable_profile_fields: list[str] | None = None,
    possible_target_relevance: list[str] | None = None,
    known_gpu_strength: str | None = None,
    known_fpga_risk: str | None = None,
) -> dict[str, Any]:
    defaults = _motif_taxonomy_defaults(category)
    return {
        "motif_name": name,
        "category": category,
        "description": description,
        "provisional": provisional,
        "measurable_profile_fields": measurable_profile_fields or defaults["measurable_profile_fields"],
        "possible_target_relevance": possible_target_relevance or defaults["possible_target_relevance"],
        "known_gpu_strength": known_gpu_strength or defaults["known_gpu_strength"],
        "known_fpga_risk": known_fpga_risk or defaults["known_fpga_risk"],
        "layer2_readiness": "provisional" if provisional else "ready",
        "hint_status": "heuristic_prior",
        "requires_layer2_measurement": True,
    }


def _motif_taxonomy_defaults(category: str) -> dict[str, Any]:
    taxonomy = {
        "spectral_transform": {
            "measurable_profile_fields": ["fft_size", "transpose_bytes", "all_to_all_count"],
            "possible_target_relevance": ["gpu", "fpga_streaming", "near_memory"],
            "known_gpu_strength": "high_when_fft_library_and_batching_are_available",
            "known_fpga_risk": "transpose_routing_and_global_memory_pressure",
        },
        "operator_application": {
            "measurable_profile_fields": ["call_count", "flop_count", "streamed_bytes", "reuse_distance"],
            "possible_target_relevance": ["gpu", "fpga_pipeline", "asic_datapath"],
            "known_gpu_strength": "medium_to_high_for_batched_dense_or_stencil_like_regions",
            "known_fpga_risk": "irregular_projector_access_and_precision_pressure",
        },
        "linear_algebra": {
            "measurable_profile_fields": ["matrix_shape", "flop_count", "solver_iterations", "library_calls"],
            "possible_target_relevance": ["gpu", "cpu_blas", "fpga_for_fixed_shapes"],
            "known_gpu_strength": "high_for_large_dense_blas_and_solver_kernels",
            "known_fpga_risk": "shape_variability_and_solver_control_complexity",
        },
        "scf_state_update": {
            "measurable_profile_fields": ["grid_points", "mixing_iterations", "reduction_bytes"],
            "possible_target_relevance": ["cpu", "gpu", "fpga_for_streaming_updates"],
            "known_gpu_strength": "medium_for_large_grid_updates",
            "known_fpga_risk": "host_control_coupling_and_convergence_feedback",
        },
        "communication": {
            "measurable_profile_fields": ["message_count", "bytes_moved", "collective_type", "rank_count"],
            "possible_target_relevance": ["interconnect", "gpu_direct", "host_runtime"],
            "known_gpu_strength": "depends_on_gpu_aware_mpi_and_data_residency",
            "known_fpga_risk": "system_integration_and_synchronization_overhead",
        },
        "memory": {
            "measurable_profile_fields": ["working_set_bytes", "bandwidth_bytes", "access_stride", "reuse_distance"],
            "possible_target_relevance": ["gpu_hbm", "fpga_hbm", "near_memory"],
            "known_gpu_strength": "high_when_arrays_are_resident_and_coalesced",
            "known_fpga_risk": "capacity_limits_and_data_staging_overheads",
        },
        "workflow_parallelism": {
            "measurable_profile_fields": ["run_count", "dependency_edges", "reuse_artifacts", "batch_width"],
            "possible_target_relevance": ["scheduler", "gpu_cluster", "fpga_farm"],
            "known_gpu_strength": "high_for_independent_batches_with_reusable_inputs",
            "known_fpga_risk": "amortization_risk_when_individual_runs_are_small",
        },
        "response_solve": {
            "measurable_profile_fields": ["q_point_count", "rhs_count", "solve_iterations", "response_tensor_size"],
            "possible_target_relevance": ["gpu", "fpga_for_repeated_rhs", "cpu_solver"],
            "known_gpu_strength": "medium_to_high_for_many_rhs_or_q_points",
            "known_fpga_risk": "small_dense_kernels_and_solver_branching",
        },
        "transport": {
            "measurable_profile_fields": ["kq_grid_size", "matrix_element_count", "collision_terms", "staging_bytes"],
            "possible_target_relevance": ["gpu", "gpu_cluster", "fpga_for_streaming_collision_terms"],
            "known_gpu_strength": "high_for_dense_kq_grids_and_matrix_traversals",
            "known_fpga_risk": "large_memory_footprint_and_irregular_table_access",
        },
        "io_memory": {
            "measurable_profile_fields": ["file_count", "checkpoint_bytes", "staging_bytes", "reuse_count"],
            "possible_target_relevance": ["storage", "host_runtime", "memory_hierarchy"],
            "known_gpu_strength": "low_unless_io_is_hidden_by_residency_or_overlap",
            "known_fpga_risk": "host_io_dominance_and_low_compute_density",
        },
        "structure_scale": {
            "measurable_profile_fields": ["atom_count", "cell_volume", "grid_points", "band_count"],
            "possible_target_relevance": ["memory_capacity", "gpu_hbm", "distributed_cpu_gpu"],
            "known_gpu_strength": "medium_when_large_arrays_fit_device_memory",
            "known_fpga_risk": "capacity_pressure_and_low_reuse_for_large_unique_cells",
        },
        "post_processing": {
            "measurable_profile_fields": ["projection_count", "grid_points", "output_bytes", "analysis_passes"],
            "possible_target_relevance": ["cpu", "gpu", "fpga_for_streaming_analysis"],
            "known_gpu_strength": "medium_for_large_regular_projection_or_grid_passes",
            "known_fpga_risk": "low_reuse_and_workflow_integration_overhead",
        },
    }
    return taxonomy.get(
        category,
        {
            "measurable_profile_fields": ["runtime_breakdown", "memory_movement", "parallel_axes"],
            "possible_target_relevance": ["cpu", "gpu", "fpga"],
            "known_gpu_strength": "unknown_until_layer2_profiling",
            "known_fpga_risk": "unknown_until_layer2_profiling",
        },
    )


MOTIF_REGISTRY: dict[str, dict[str, Any]] = {
    "fft_transpose": _motif(
        "FFT and transpose",
        category="spectral_transform",
        description="Plane-wave FFTs and distributed transpose traffic.",
    ),
    "hpsi": _motif(
        "Hamiltonian application",
        category="operator_application",
        description="Repeated H psi application in iterative electronic solves.",
    ),
    "projector_nonlocal": _motif(
        "Nonlocal projector",
        category="operator_application",
        description="Pseudopotential projector application and accumulation.",
    ),
    "dense_linear_algebra": _motif(
        "Dense linear algebra",
        category="linear_algebra",
        description="GEMM/GEMV, orthogonalization, and dense eigensolver support.",
    ),
    "diagonalization": _motif(
        "Diagonalization",
        category="linear_algebra",
        description="Kohn-Sham subspace diagonalization and solver orchestration.",
    ),
    "density_update": _motif(
        "Density update",
        category="scf_state_update",
        description="Charge-density construction, update, and mixing inputs.",
    ),
    "reduction_collective": _motif(
        "Reduction collective",
        category="communication",
        description="Dot products, global sums, and collective reductions.",
    ),
    "wavefunction_memory": _motif(
        "Wavefunction memory",
        category="memory",
        description="Large wavefunction-array footprint, layout, and reuse pressure.",
    ),
    "q_point_sweep": _motif(
        "q-point sweep",
        category="workflow_parallelism",
        description="Independent or weakly coupled phonon q-point evaluations.",
    ),
    "perturbation_rhs": _motif(
        "Perturbation right-hand side",
        category="response_solve",
        description="DFPT perturbation-source construction and solve RHS handling.",
    ),
    "response_accumulation": _motif(
        "Response accumulation",
        category="response_solve",
        description="Accumulation of dielectric, phonon, and response tensors.",
    ),
    "dense_kq_interpolation": _motif(
        "Dense k/q interpolation",
        category="transport",
        description="Wannier or dense-grid k/q interpolation for transport studies.",
    ),
    "electron_phonon_matrix": _motif(
        "Electron-phonon matrix",
        category="transport",
        description="Electron-phonon matrix-element construction and traversal.",
    ),
    "bte_collision_integral": _motif(
        "BTE collision integral",
        category="transport",
        description="Boltzmann transport collision-integral evaluation.",
    ),
    "memory_bandwidth": _motif(
        "Memory bandwidth",
        category="memory",
        description="Bandwidth-bound sweeps over dense numerical arrays.",
    ),
    "large_data_staging": _motif(
        "Large data staging",
        category="io_memory",
        description="Movement of wavefunction, matrix-element, and checkpoint data.",
    ),
    "io_checkpoint": _motif(
        "I/O checkpoint",
        category="io_memory",
        description="Restart files, intermediate outputs, and checkpoint pressure.",
    ),
    "workflow_parameter_sweep": _motif(
        "Workflow parameter sweep",
        category="workflow_parallelism",
        description="Scenario-level repeated workflows over physical parameters.",
    ),
    "cross_run_reuse": _motif(
        "Cross-run reuse",
        category="workflow_parallelism",
        description="Reuse of electronic, phonon, or interpolation artifacts across runs.",
    ),
    "batch_scheduling": _motif(
        "Batch scheduling",
        category="workflow_parallelism",
        description="Scheduling many related calculations under a shared campaign.",
    ),
    "large_supercell": _motif(
        "Large supercell",
        category="structure_scale",
        description="Large real-space cell and gamma/sparse-k electronic solves.",
    ),
    "localized_state_analysis": _motif(
        "Localized-state analysis",
        category="post_processing",
        description="Projection and analysis of localized defect or interface states.",
    ),
    "potential_alignment": _motif(
        "Potential alignment",
        category="post_processing",
        description="Electrostatic and band-edge alignment across regions or materials.",
    ),
    "charge_density_analysis": _motif(
        "Charge-density analysis",
        category="post_processing",
        description="Charge-density, orbital, and projected-density analysis.",
    ),
    "memory_capacity": _motif(
        "Memory capacity",
        category="memory",
        description="Capacity pressure from large cells, bands, and retained arrays.",
    ),
    "small_dense_linear_algebra": _motif(
        "Small dense linear algebra",
        category="linear_algebra",
        description="Small-matrix DFPT and response tensor linear algebra.",
        provisional=True,
    ),
    "communication": _motif(
        "Communication",
        category="communication",
        description="General inter-rank data exchange beyond explicit reductions.",
        provisional=True,
    ),
    "repeated_runs": _motif(
        "Repeated runs",
        category="workflow_parallelism",
        description="Repeated program invocations in a parameter or operating-condition sweep.",
        provisional=True,
    ),
    "incremental_update": _motif(
        "Incremental update",
        category="workflow_parallelism",
        description="Reusing and incrementally updating state across neighboring sweep points.",
        provisional=True,
    ),
    "repeated_ground_state_solve": _motif(
        "Repeated ground-state solve",
        category="workflow_parallelism",
        description="Multiple related SCF solves for structures, defects, or interfaces.",
        provisional=True,
    ),
    "parameter_sweep": _motif(
        "Parameter sweep",
        category="workflow_parallelism",
        description="Generic parameter sweep where the driving physical axis is family-specific.",
        provisional=True,
    ),
}


def _profiling_contract() -> dict[str, Any]:
    return {
        "required_next_layer": "motif_profiling",
        "expected_profile_fields": list(PROFILING_CONTRACT_REQUIRED_FIELDS),
        "gpu_baseline_required": True,
    }


def _family(
    *,
    family_id: str,
    family_name: str,
    priority: str,
    representative_programs: list[str],
    depends_on_families: list[str],
    device_relevance: list[str],
    expected_motifs: list[str],
    first_version_required: bool,
    source_basis: list[str],
    external_reference_programs: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    family: dict[str, Any] = {
        "family_id": family_id,
        "family_name": family_name,
        "priority": priority,
        "representative_programs": representative_programs,
        "depends_on_families": depends_on_families,
        "device_relevance": device_relevance,
        "expected_motifs": expected_motifs,
        "first_version_required": first_version_required,
        "source_basis": source_basis,
        "profiling_contract": _profiling_contract(),
    }
    if external_reference_programs:
        family["external_reference_programs"] = external_reference_programs
    if notes:
        family["notes"] = notes
    return family


WORKLOAD_FAMILY_REGISTRY: dict[str, dict[str, Any]] = {
    "ground_state_band_structure": _family(
        family_id="ground_state_band_structure",
        family_name="Ground-state and band-structure",
        priority="required",
        representative_programs=["pw.x", "bands.x", "dos.x"],
        depends_on_families=[],
        device_relevance=[
            "band_structure",
            "effective_mass",
            "wavefunction_generation",
            "density_generation",
            "input_to_phonon_and_transport",
        ],
        expected_motifs=[
            "fft_transpose",
            "hpsi",
            "projector_nonlocal",
            "dense_linear_algebra",
            "diagonalization",
            "density_update",
            "reduction_collective",
            "wavefunction_memory",
        ],
        first_version_required=True,
        source_basis=[
            "qe_pwscf_ground_state",
            "qe_postproc_bands_dos",
            "ic_effective_mass_band_structure",
        ],
    ),
    "phonon_dfpt": _family(
        family_id="phonon_dfpt",
        family_name="Phonon and DFPT",
        priority="required",
        representative_programs=["ph.x"],
        depends_on_families=["ground_state_band_structure"],
        device_relevance=[
            "phonon_dispersion",
            "dielectric_response",
            "born_effective_charge",
            "input_to_electron_phonon_transport",
        ],
        expected_motifs=[
            "q_point_sweep",
            "perturbation_rhs",
            "response_accumulation",
            "fft_transpose",
            "hpsi",
            "small_dense_linear_algebra",
            "reduction_collective",
            "communication",
        ],
        first_version_required=True,
        source_basis=[
            "qe_phonon_dfpt",
            "qe_pwscf_ground_state_dependency",
            "ic_dielectric_phonon_response",
        ],
    ),
    "electron_phonon_mobility": _family(
        family_id="electron_phonon_mobility",
        family_name="Electron-phonon mobility and transport",
        priority="primary",
        representative_programs=["epw.x"],
        external_reference_programs=["perturbo"],
        depends_on_families=[
            "ground_state_band_structure",
            "phonon_dfpt",
        ],
        device_relevance=[
            "carrier_mobility",
            "conductivity",
            "phonon_limited_transport",
            "scattering_rate",
        ],
        expected_motifs=[
            "dense_kq_interpolation",
            "electron_phonon_matrix",
            "bte_collision_integral",
            "dense_linear_algebra",
            "memory_bandwidth",
            "large_data_staging",
            "io_checkpoint",
        ],
        first_version_required=True,
        source_basis=[
            "epw_transport",
            "epw_wannier_interpolation",
            "perturbo_external_reference",
            "ic_carrier_mobility",
        ],
        notes=[
            "Perturbo is tracked as a reference external transport program, not as a core QE executable.",
        ],
    ),
    "strain_doping_field_sweep": _family(
        family_id="strain_doping_field_sweep",
        family_name="Strain, doping, field, and operating-condition sweep",
        priority="required",
        representative_programs=["pw.x", "ph.x", "epw.x"],
        depends_on_families=[
            "ground_state_band_structure",
            "phonon_dfpt",
            "electron_phonon_mobility",
        ],
        device_relevance=[
            "strain_effect",
            "carrier_concentration_dependence",
            "electric_field_dependence",
            "temperature_dependence",
            "channel_orientation_sweep",
        ],
        expected_motifs=[
            "workflow_parameter_sweep",
            "repeated_runs",
            "cross_run_reuse",
            "batch_scheduling",
            "incremental_update",
        ],
        first_version_required=True,
        source_basis=[
            "qe_pwscf_operating_condition_sweep",
            "qe_phonon_dfpt_dependency",
            "epw_transport_dependency",
            "ic_strain_doping_field_temperature_sweep",
        ],
    ),
    "interface_band_offset_defect": _family(
        family_id="interface_band_offset_defect",
        family_name="Interface, band-offset, and defect",
        priority="required",
        representative_programs=["pw.x", "pp.x", "projwfc.x"],
        depends_on_families=["ground_state_band_structure"],
        device_relevance=[
            "semiconductor_oxide_interface",
            "high_k_interface",
            "metal_semiconductor_contact",
            "band_offset",
            "defect_trap_level",
            "formation_energy",
        ],
        expected_motifs=[
            "large_supercell",
            "repeated_ground_state_solve",
            "localized_state_analysis",
            "potential_alignment",
            "charge_density_analysis",
            "memory_capacity",
            "parameter_sweep",
        ],
        first_version_required=True,
        source_basis=[
            "qe_pwscf_interface_supercell",
            "qe_postproc_charge_density_projection",
            "ic_band_offset_defect_trap_analysis",
        ],
    ),
}

REQUIRED_FIRST_VERSION_FAMILY_IDS = tuple(WORKLOAD_FAMILY_REGISTRY.keys())

SCENARIO_REGISTRY: dict[str, dict[str, Any]] = {
    "mobility_centered_ic_device": {
        "scenario_id": "mobility_centered_ic_device",
        "description": (
            "IC device workload distribution centered on carrier mobility and "
            "electron-phonon transport."
        ),
        "weights": {
            "ground_state_band_structure": 0.20,
            "phonon_dfpt": 0.20,
            "electron_phonon_mobility": 0.35,
            "strain_doping_field_sweep": 0.15,
            "interface_band_offset_defect": 0.10,
        },
    },
    "interface_centered_ic_device": {
        "scenario_id": "interface_centered_ic_device",
        "description": (
            "IC device workload distribution centered on interfaces, band offsets, "
            "and defects."
        ),
        "weights": {
            "ground_state_band_structure": 0.20,
            "phonon_dfpt": 0.10,
            "electron_phonon_mobility": 0.20,
            "strain_doping_field_sweep": 0.15,
            "interface_band_offset_defect": 0.35,
        },
    },
}

EXCLUDED_WORKFLOW_REGISTRY: list[dict[str, str]] = [
    {
        "workflow": "NEB",
        "reason": "deferred; image-level scheduling is a separate system-level problem",
    },
    {
        "workflow": "CP_MD",
        "reason": "deferred; time-step stability and trajectory validation increase scope",
    },
    {
        "workflow": "GW_BSE",
        "reason": "deferred; many-body and optical workflows are outside mobility-centered v1",
    },
    {
        "workflow": "TDDFT",
        "reason": "deferred; time-propagation motifs require separate modeling",
    },
    {
        "workflow": "NEGF",
        "reason": "deferred; device-level quantum transport may require a non-QE software stack",
    },
]


def registry_snapshot() -> Mapping[str, Any]:
    """Return a shallow snapshot of all QE-IC registries for diagnostics."""

    return {
        "motif_ids": tuple(MOTIF_REGISTRY),
        "workload_family_ids": tuple(WORKLOAD_FAMILY_REGISTRY),
        "scenario_ids": tuple(SCENARIO_REGISTRY),
        "excluded_workflows": tuple(row["workflow"] for row in EXCLUDED_WORKFLOW_REGISTRY),
    }
