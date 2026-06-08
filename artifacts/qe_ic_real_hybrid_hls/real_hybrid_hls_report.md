# Real Hybrid HLS Evidence Campaign Summary

- Preliminary label: `fpga_hybrid_weaker`
- Confidence: `medium`
- Final hardware claim allowed: `False`
- Best architecture: `hybrid_streaming_reduction_accumulator_v1`
- Best optimistic trace-replay speedup vs GPU: `1.15046x`

## Direct answer

The current non-stub hybrid FPGA/HLS candidates should be reported as **FPGA/hybrid weaker / not superior to the GPU baseline** for claim purposes. The real HLS microkernels pass Vivado-HLS C-sim, C-synth, and Verilog C/RTL co-simulation, but they are still partial sidecar motifs rather than full QE kernel-equivalent replacements.

## Evidence gates passed

- `hybrid_streaming_reduction_accumulator_v1`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `351` cycles, estimated clock `9.376` ns
  - Verilog C/RTL cosim: `True`, latency `431` cycles
  - Resource: BRAM18K `22`, DSP `25`, FF `5371`, LUT `6916`, URAM `0`
- `hybrid_tiled_complex_axpy_v1`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `82` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `175` cycles
  - Resource: BRAM18K `28`, DSP `56`, FF `7858`, LUT `12337`, URAM `0`
- `hybrid_fft_twiddle_stream_v1`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `119` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `288` cycles
  - Resource: BRAM18K `48`, DSP `237`, FF `18387`, LUT `23350`, URAM `0`

## Workflow accounting result

Trace replay used measured QE full-SCF timer logs from `artifacts/qe_ic_7day_prelim/runs/<case>/gpu_only_baseline/run_*.stdout.log` plus real HLS C/RTL cosim latency. The accounting is intentionally labelled `trace_replay_optimistic` and `partial_sidecar_motif`.

| Architecture | Case | Mapped QE timers | Optimistic speedup | Coverage |
| --- | --- | --- | ---: | --- |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `sum_band` | 1.1505x | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `sum_band` | 1.0486x | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `sum_band` | 1.0226x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.1359x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_al_interconnect_4atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.0917x | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_si_bulk_2atom_scf_v0` | `mix_rho, h_psi:calbec, calbec` | 1.1164x | `partial_sidecar_motif` |
| `hybrid_fft_twiddle_stream_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `fft, ffts, fftw` | 0.9902x | `partial_sidecar_motif` |
| `hybrid_fft_twiddle_stream_v1` | `ic_al_interconnect_4atom_scf_v0` | `fft, ffts, fftw` | 0.9890x | `partial_sidecar_motif` |
| `hybrid_fft_twiddle_stream_v1` | `ic_si_bulk_2atom_scf_v0` | `fft, ffts, fftw` | 0.9843x | `partial_sidecar_motif` |

## Claim boundary

Real HLS C/RTL cosim passed, and optimistic trace replay shows sidecar microkernel potential, but the implemented kernels are partial motifs rather than full QE kernel-equivalent replacements; report current implementation as weaker/not superior.

Blockers:
- `full_qe_kernel_equivalent_missing`
- `full_qe_kernel_integration_missing`
- `physical_fpga_board_measurement_missing`

Therefore this artifact improves the evidence chain beyond generated stubs/proxies, but it still does not allow a final hardware superiority or fundamental no-opportunity claim.
