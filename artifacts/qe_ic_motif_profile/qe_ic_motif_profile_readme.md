# QE-IC Motif Profile v1

## Artifact Role

This Layer-2 artifact consumes the Layer-1 QE-IC workload suite and profile-source fixtures or log summaries. It maps raw profile events to registered workload motifs and aggregates runtime, memory movement, communication, parallel axes, unmapped time, and GPU-baseline coverage per workload family and target.

## Family-Target Profiles

- `electron_phonon_mobility` on `gpu_only`: total_time_ms=10000.0, unmapped_time_ratio=0.000, motifs: bte_collision_integral=0.330, dense_kq_interpolation=0.420, dense_linear_algebra=0.250.
- `ground_state_band_structure` on `gpu_only`: total_time_ms=231.57894736842104, unmapped_time_ratio=0.050, motifs: fft_transpose=0.518, hpsi=0.432.
- `interface_band_offset_defect` on `gpu_only`: total_time_ms=4000.0, unmapped_time_ratio=0.000, motifs: charge_density_analysis=0.100, large_supercell=0.600, localized_state_analysis=0.300.
- `phonon_dfpt` on `gpu_only`: total_time_ms=500.0, unmapped_time_ratio=0.000, motifs: perturbation_rhs=0.360, reduction_collective=0.200, response_accumulation=0.440.
- `strain_doping_field_sweep` on `gpu_only`: total_time_ms=3000.0, unmapped_time_ratio=0.000, motifs: batch_scheduling=0.167, cross_run_reuse=0.300, workflow_parameter_sweep=0.533.

## Source Boundary

The first implementation supports `manual_profile_table` ingestion. `qe_timer_log`, `nsight_summary`, and `mpi_trace_summary` records may be registered, but parser support is intentionally reported as `parser_not_implemented_for_source_type` until implemented.

## Claim Boundary

This artifact contains observed or fixture-based workload motif profiling only. It does not contain architecture candidates, target viability decisions, promotion decisions, hardware implementation results, or final performance claims.

Layer-2 does not generate architectures, compare targets, decide viability, promote candidates, produce hardware implementation results, or make final performance claims.
