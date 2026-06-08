# Real Hybrid HLS Evidence Campaign Summary

- Preliminary label: `fpga_hybrid_weaker`
- Confidence: `medium`
- Final hardware claim allowed: `False`
- Best architecture: `hybrid_streaming_reduction_accumulator_v1`
- Best optimistic trace-replay speedup vs GPU: `1.15046x`
- Resource-infeasible architectures filtered: `hybrid_fft_twiddle_stream_v1`

## Direct answer

The current non-stub hybrid FPGA/HLS evidence supports **FPGA/hybrid weaker / not superior to the GPU baseline** for claim purposes unless all hard gates pass. The evidence includes real HLS kernels and Vivado-HLS C/RTL co-simulation, but miniapps and sidecar motifs are not final full-QE integration evidence.

## Evidence gates

- `hybrid_streaming_reduction_accumulator_v1`
  - Coverage: `partial_sidecar_motif`; mapped timers: `sum_band`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `351` cycles, estimated clock `9.376` ns
  - Verilog C/RTL cosim: `True`, latency `431` cycles
  - Performance latency source: `vivado_hls_cosim`, latency `431` cycles
  - Resource feasible on target: `True`; BRAM18K `22`, DSP `25`, FF `5371`, LUT `6916`, URAM `0`
- `hybrid_tiled_complex_axpy_v1`
  - Coverage: `partial_sidecar_motif`; mapped timers: `mix_rho, h_psi:calbec, calbec`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `82` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `175` cycles
  - Performance latency source: `vivado_hls_cosim`, latency `175` cycles
  - Resource feasible on target: `True`; BRAM18K `28`, DSP `56`, FF `7858`, LUT `12337`, URAM `0`
- `hybrid_fft_twiddle_stream_v1`
  - Coverage: `partial_sidecar_motif`; mapped timers: `fft, ffts, fftw`
  - C-sim golden: `True`
  - C-synth parsed: `partial`, latency `119` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `288` cycles
  - Performance latency source: `vivado_hls_cosim`, latency `288` cycles
  - Resource feasible on target: `False`; BRAM18K `48`, DSP `237`, FF `18387`, LUT `23350`, URAM `0`
  - HLS blockers: `hls_resource_infeasible`
- `hybrid_sum_band_density_accumulator_v1`
  - Coverage: `qe_routine_equivalent_miniapp`; mapped timers: `sum_band`
  - C-sim golden: `True`
  - C-synth parsed: `partial`, latency `None` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `5068` cycles
  - Performance latency source: `vivado_hls_cosim`, latency `5068` cycles
  - Resource feasible on target: `True`; BRAM18K `16`, DSP `25`, FF `4652`, LUT `6465`, URAM `0`
  - HLS blockers: `hls_latency_summary_missing`

## Workflow accounting result

Trace replay used measured QE full-SCF timer logs from `artifacts/qe_ic_7day_prelim/runs/<case>/gpu_only_baseline/run_*.stdout.log` plus real HLS C/RTL cosim latency. Rows marked `partial_sidecar_motif` or `qe_routine_equivalent_miniapp` are not final full-QE integration evidence.

| Architecture | Case | Mapped QE timers | Optimistic speedup | Coverage |
| --- | --- | --- | ---: | --- |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `sum_band` | 1.1505x | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `sum_band` | 1.0486x | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `sum_band` | 1.0226x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.1359x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_al_interconnect_4atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.0917x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_si_bulk_2atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.1164x | `partial_sidecar_motif` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `sum_band` | 1.1496x | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `sum_band` | 1.0482x | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `sum_band` | 1.0222x | `qe_routine_equivalent_miniapp` |

## Claim boundary

Real HLS C/RTL cosim passed, and optimistic trace replay shows sidecar microkernel potential, but the implemented kernels are partial motifs rather than full QE kernel-equivalent replacements; report current implementation as weaker/not superior.

Blockers:
- `full_qe_kernel_equivalent_missing`
- `full_qe_kernel_integration_missing`
- `hls_resource_infeasible_architectures_filtered`
- `physical_fpga_board_measurement_missing`

Therefore this artifact improves the evidence chain beyond generated stubs/proxies and includes a QE-routine miniapp when present, but it still does not allow final hardware superiority or fundamental no-opportunity wording without full QE integration and board/implementation closure.
