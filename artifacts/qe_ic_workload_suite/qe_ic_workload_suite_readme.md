# QE-IC Device Workload Suite v1

## Suite Goal

This Layer-1 artifact defines the workload scope for an IC-device-oriented DFT design-space exploration proof path. It gives later layers a stable registry of workload families, dependencies, expected motifs, scenario weights, excluded workflows, and the next-layer profiling contract.

## Why IC Device Workloads

The suite targets electronic-structure, phonon, transport, operating-condition, interface, and defect calculations that shape semiconductor and device co-design questions. These workloads are broad enough to exercise the generic DSE control plane while remaining scoped to a concrete QE-centered research proof path.

## Why Mobility Is The Primary Scenario

Carrier mobility and electron-phonon transport connect ground-state, DFPT, interpolation, scattering, and sweep workflows. That dependency chain makes mobility a demanding first scenario for multi-fidelity DSE. It also forces later layers to keep GPU baselines visible because QE/EPW and related transport workflows already have heterogeneous-computing baselines.

## Workload Families

- `ground_state_band_structure`: Ground-state and band-structure (required); dependencies: none; motifs: fft_transpose, hpsi, projector_nonlocal, dense_linear_algebra, diagonalization, density_update, reduction_collective, wavefunction_memory.
- `phonon_dfpt`: Phonon and DFPT (required); dependencies: ground_state_band_structure; motifs: q_point_sweep, perturbation_rhs, response_accumulation, fft_transpose, hpsi, small_dense_linear_algebra, reduction_collective, communication.
- `electron_phonon_mobility`: Electron-phonon mobility and transport (primary); dependencies: ground_state_band_structure, phonon_dfpt; motifs: dense_kq_interpolation, electron_phonon_matrix, bte_collision_integral, dense_linear_algebra, memory_bandwidth, large_data_staging, io_checkpoint.
- `strain_doping_field_sweep`: Strain, doping, field, and operating-condition sweep (required); dependencies: ground_state_band_structure, phonon_dfpt, electron_phonon_mobility; motifs: workflow_parameter_sweep, repeated_runs, cross_run_reuse, batch_scheduling, incremental_update.
- `interface_band_offset_defect`: Interface, band-offset, and defect (required); dependencies: ground_state_band_structure; motifs: large_supercell, repeated_ground_state_solve, localized_state_analysis, potential_alignment, charge_density_analysis, memory_capacity, parameter_sweep.

## Scenario Weights

Scenario weights describe how important each workload family is in a system-level IC design scenario. They are scenario facts, not intrinsic properties of the workload families.

- `mobility_centered_ic_device`: IC device workload distribution centered on carrier mobility and electron-phonon transport. Weights: ground_state_band_structure=0.20, phonon_dfpt=0.20, electron_phonon_mobility=0.35, strain_doping_field_sweep=0.15, interface_band_offset_defect=0.10.
- `interface_centered_ic_device`: IC device workload distribution centered on interfaces, band offsets, and defects. Weights: ground_state_band_structure=0.20, phonon_dfpt=0.10, electron_phonon_mobility=0.20, strain_doping_field_sweep=0.15, interface_band_offset_defect=0.35.

## Excluded Workflows

- `NEB`: deferred; image-level scheduling is a separate system-level problem.
- `CP_MD`: deferred; time-step stability and trajectory validation increase scope.
- `GW_BSE`: deferred; many-body and optical workflows are outside mobility-centered v1.
- `TDDFT`: deferred; time-propagation motifs require separate modeling.
- `NEGF`: deferred; device-level quantum transport may require a non-QE software stack.

## Interface To Layer-2 Motif Profiling

Every workload family carries a `profiling_contract` requiring runtime breakdown, operation mix, memory movement, communication pattern, parallel axes, reuse opportunities, and an explicit GPU baseline field. Layer-2 must measure or otherwise justify those fields before target viability or promotion policy consumes this suite.

## Performance And Claim Boundary

This artifact defines workload scope only. It does not contain profiling results, architecture candidates, performance estimates, target viability results, or promotion decisions.

This artifact does not rank GPU, FPGA, GPU+FPGA, CPU, or ASIC targets. It does not contain profiling results, architecture candidates, performance estimates, target viability results, promotion decisions, or hardware claim evidence.

## External Program Boundary

`perturbo` is included only as a reference external transport program for `electron_phonon_mobility`; it is not treated as a core QE executable.
