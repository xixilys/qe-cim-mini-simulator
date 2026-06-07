# QE-IC Real Opportunity Campaign

## Campaign Flow

The campaign probes the local GPU, QE, profiler, SystemC, and EDA environment; prepares the ground_state_band_structure and electron_phonon_mobility cases; ingests or runs a real GPU baseline; selects Layer-4 FPGA/hybrid candidates; ingests candidate high-fidelity evidence; audits implementation quality; and calls the existing real-baseline opportunity claim gate.

## Modes

`run_if_available` may execute available local measurements. `ingest_only` only accepts externally provided logs or JSON records. `run_if_available_or_ingest_only` uses local measurements when available and otherwise emits evidence_missing rather than fabricating results.

## Real GPU Baseline

A real GPU baseline requires at least three repeated GPU-only QE runs for the same case, program, input_deck_hash, and precision. The baseline must carry `measurements_are_real=true` and `evidence_status=measured`.

## Candidate High-Fidelity Evidence

Candidate high-fidelity evidence may be workflow-level trace replay, SystemC timing, gem5/SystemC, real QE candidate runs, or Vivado/DC resource and timing evidence with explicit tool provenance. L1 estimates and synthetic labels are not high-fidelity evidence.

## Implementation-Limited vs Fundamental-No-Opportunity

`implementation_limited` means the current candidate loses but weak utilization, poor overlap, low fmax, immature implementation, missing calibration, or an idealized upper bound above 1.0 leaves opportunity open. `fundamental_no_opportunity` is only allowed when real baseline and workflow-level candidate evidence exist, implementation quality passes, resource and timing are feasible or intrinsically infeasible, the idealized upper bound is at or below 1.0, and no claim gate passes.

## Replace Templates

Replace templates by adding real input deck paths, GPU baseline run JSON, profile logs, and candidate evidence JSON to the campaign config. Missing tools or missing decks produce evidence_missing or blocked status, not fake measurements.

## Forbidden Conclusions

Do not claim FPGA-only or GPU+FPGA is faster than GPU-only unless the claim gate passes. EDA tool availability alone does not imply speedup. Fixture evidence, templates, L1 estimates, and synthetic labels are progress evidence only.

## Current Answer

Campaign could not answer the question because GPU/QE execution was unavailable.
