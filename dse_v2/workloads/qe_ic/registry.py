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
) -> dict[str, Any]:
    return {
        "motif_name": name,
        "category": category,
        "description": description,
        "provisional": provisional,
    }


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
    external_programs: list[str] | None = None,
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
        "profiling_contract": _profiling_contract(),
    }
    if external_programs:
        family["external_programs"] = external_programs
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
    ),
    "electron_phonon_mobility": _family(
        family_id="electron_phonon_mobility",
        family_name="Electron-phonon mobility and transport",
        priority="primary",
        representative_programs=["epw.x", "perturbo"],
        external_programs=["perturbo"],
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
