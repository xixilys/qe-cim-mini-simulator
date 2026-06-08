# Real Hybrid HLS Evidence Campaign Summary

- Preliminary label: `fpga_hybrid_weaker`
- Confidence: `medium`
- Final hardware claim allowed: `False`
- Best architecture: `hybrid_combined_vcs_sidecar_v1`
- Best optimistic trace-replay speedup vs GPU: `1.5511x`
- Best Vivado-implemented architecture: `hybrid_integrated_streaming_pipeline_sidecar_v3`
- Best Vivado-implemented trace-replay speedup vs GPU: `1.55089x`
- Resource-infeasible architectures filtered: `hybrid_fft_twiddle_stream_v1`
- Claim closure audit: `artifacts/qe_ic_real_hybrid_hls/real_hybrid_claim_closure.json`
- Integrated Vivado implementation: `hybrid_integrated_streaming_pipeline_sidecar_v3` passed `True`, WNS `0.962` ns, implemented clock `12.0` ns, LUT `848`, FF `736`, BRAM tile `0`, DSP `8`

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
  - VCS RTL sim: `True`, latency `64` cycles, samples `64`
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
  - VCS RTL sim: `True`, latency `128` cycles, samples `128`
  - Performance latency source: `vivado_hls_cosim`, latency `5068` cycles
  - Resource feasible on target: `True`; BRAM18K `16`, DSP `25`, FF `4652`, LUT `6465`, URAM `0`
  - HLS blockers: `hls_latency_summary_missing`
- `hybrid_hpsi_local_potential_v1`
  - Coverage: `qe_routine_equivalent_miniapp`; mapped timers: `h_psi`
  - C-sim golden: `True`
  - C-synth parsed: `parsed`, latency `326` cycles, estimated clock `8.75` ns
  - Verilog C/RTL cosim: `True`, latency `664` cycles
  - VCS RTL sim: `True`, latency `96` cycles, samples `96`
  - Performance latency source: `vivado_hls_cosim`, latency `664` cycles
  - Resource feasible on target: `True`; BRAM18K `34`, DSP `28`, FF `6561`, LUT `8762`, URAM `0`

## Workflow accounting result

Trace replay used measured QE full-SCF timer logs from `artifacts/qe_ic_7day_prelim/runs/<case>/gpu_only_baseline/run_*.stdout.log` plus real HLS C/RTL cosim latency; rows with handwritten RTL evidence also include a VCS RTL latency-sensitivity channel. Rows marked `partial_sidecar_motif` or `qe_routine_equivalent_miniapp` are not final full-QE integration evidence.

| Architecture | Case | Latency source | Mapped QE timers | Speedup | Status | Coverage |
| --- | --- | --- | --- | ---: | --- | --- |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.1505x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.0486x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_streaming_reduction_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.0226x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vivado_hls_cosim` | `mix_rho, h_psi:calbec, calbec` | 1.1359x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vcs_rtl` | `mix_rho, h_psi:calbec, calbec` | 1.1362x | `trace_replay_vcs_rtl_sensitivity` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_al_interconnect_4atom_scf_v0` | `vivado_hls_cosim` | `mix_rho, h_psi:calbec, calbec` | 1.0917x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_al_interconnect_4atom_scf_v0` | `vcs_rtl` | `mix_rho, h_psi:calbec, calbec` | 1.0919x | `trace_replay_vcs_rtl_sensitivity` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_si_bulk_2atom_scf_v0` | `vivado_hls_cosim` | `mix_rho, h_psi:calbec, calbec` | 1.1164x | `trace_replay_optimistic` | `partial_sidecar_motif` |
| `hybrid_tiled_complex_axpy_v1` | `ic_si_bulk_2atom_scf_v0` | `vcs_rtl` | `mix_rho, h_psi:calbec, calbec` | 1.1166x | `trace_replay_vcs_rtl_sensitivity` | `partial_sidecar_motif` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.1496x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vcs_rtl` | `sum_band` | 1.1505x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.0482x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_al_interconnect_4atom_scf_v0` | `vcs_rtl` | `sum_band` | 1.0486x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `vivado_hls_cosim` | `sum_band` | 1.0222x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_sum_band_density_accumulator_v1` | `ic_si_bulk_2atom_scf_v0` | `vcs_rtl` | `sum_band` | 1.0226x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vivado_hls_cosim` | `h_psi` | 1.1163x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `vcs_rtl` | `h_psi` | 1.1168x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_al_interconnect_4atom_scf_v0` | `vivado_hls_cosim` | `h_psi` | 1.1856x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_al_interconnect_4atom_scf_v0` | `vcs_rtl` | `h_psi` | 1.1863x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_si_bulk_2atom_scf_v0` | `vivado_hls_cosim` | `h_psi` | 1.1250x | `trace_replay_optimistic` | `qe_routine_equivalent_miniapp` |
| `hybrid_hpsi_local_potential_v1` | `ic_si_bulk_2atom_scf_v0` | `vcs_rtl` | `h_psi` | 1.1255x | `trace_replay_vcs_rtl_sensitivity` | `qe_routine_equivalent_miniapp` |
| `hybrid_combined_vcs_sidecar_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `combined_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.5511x | `trace_replay_combined_vcs_sidecar_sensitivity` | `combined_partial_sidecar_motif` |
| `hybrid_combined_vcs_sidecar_v1` | `ic_al_interconnect_4atom_scf_v0` | `combined_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.4036x | `trace_replay_combined_vcs_sidecar_sensitivity` | `combined_partial_sidecar_motif` |
| `hybrid_combined_vcs_sidecar_v1` | `ic_si_bulk_2atom_scf_v0` | `combined_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.3124x | `trace_replay_combined_vcs_sidecar_sensitivity` | `combined_partial_sidecar_motif` |
| `hybrid_integrated_combined_sidecar_v1` | `ic_sio2_dielectric_6atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.5505x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_partial_sidecar_motif` |
| `hybrid_integrated_combined_sidecar_v1` | `ic_al_interconnect_4atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.4031x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_partial_sidecar_motif` |
| `hybrid_integrated_combined_sidecar_v1` | `ic_si_bulk_2atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.3120x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_partial_sidecar_motif` |
| `hybrid_integrated_pipelined_sidecar_v2` | `ic_sio2_dielectric_6atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.5489x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_pipelined_sidecar_motif` |
| `hybrid_integrated_pipelined_sidecar_v2` | `ic_al_interconnect_4atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.4018x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_pipelined_sidecar_motif` |
| `hybrid_integrated_pipelined_sidecar_v2` | `ic_si_bulk_2atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.3111x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_pipelined_sidecar_motif` |
| `hybrid_integrated_streaming_pipeline_sidecar_v3` | `ic_sio2_dielectric_6atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.5509x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_streaming_pipeline_sidecar_motif` |
| `hybrid_integrated_streaming_pipeline_sidecar_v3` | `ic_al_interconnect_4atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.4034x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_streaming_pipeline_sidecar_motif` |
| `hybrid_integrated_streaming_pipeline_sidecar_v3` | `ic_si_bulk_2atom_scf_v0` | `integrated_vcs_rtl` | `calbec, h_psi, h_psi:calbec, mix_rho, sum_band` | 1.3122x | `trace_replay_integrated_vcs_sidecar_sensitivity` | `integrated_streaming_pipeline_sidecar_motif` |

## Integrated Vivado implementation evidence

This is post-synthesis/place/route FPGA implementation evidence for the single integrated RTL sidecar. It improves hardware feasibility evidence, but it is still not physical board measurement and not full QE kernel integration.

- Passed: `True`
- Timing met: `True`; WNS `0.962` ns; TNS `0.0` ns
- Resource feasible: `True`; LUT `848`, FF `736`, BRAM tile `0`, DSP `8`
- Evidence JSON: `artifacts/qe_ic_real_hybrid_hls/runs/hybrid_integrated_streaming_pipeline_sidecar_v3/vivado_impl/real_hybrid_integrated_streaming_vivado_impl_evidence.json`

## Claim boundary

Integrated VCS RTL sidecar trace replay improves hardware-integration evidence, but it remains a compact sidecar miniapp rather than full QE kernel integration; report current implementation as weaker/not superior.

Blockers:
- `full_qe_kernel_equivalent_missing`
- `full_qe_kernel_integration_missing`
- `hls_resource_infeasible_architectures_filtered`
- `physical_fpga_board_measurement_missing`
- `vivado_impl_setup_timing_not_met`

Therefore this artifact improves the evidence chain beyond generated stubs/proxies and includes a QE-routine miniapp when present, but it still does not allow final hardware superiority or fundamental no-opportunity wording without full QE integration and board/implementation closure.
