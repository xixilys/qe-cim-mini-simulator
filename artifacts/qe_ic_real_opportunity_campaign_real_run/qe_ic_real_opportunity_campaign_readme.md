# QE-IC Real Opportunity Campaign

## Campaign Flow

The campaign probes the local GPU, QE, profiler, SystemC, and EDA environment; prepares the ground_state_band_structure and electron_phonon_mobility cases; attempts CPU and GPU baselines without substituting CPU timing for GPU evidence; selects Layer-4 FPGA/hybrid candidates; generates non-claimable candidate stubs for EDA syntax attempts when real designs are missing; ingests candidate high-fidelity evidence; audits implementation quality; and calls the existing real-baseline opportunity claim gate.

## Modes

`run_if_available` may execute available local measurements. `ingest_only` only accepts externally provided logs or JSON records. `run_if_available_or_ingest_only` uses local measurements when available and otherwise emits evidence_missing rather than fabricating results. In nonblocking execute-real mode, generated stubs may be sent to real EDA tools as syntax/readiness evidence, not acceleration evidence.

## Real GPU Baseline

A real GPU baseline requires at least three repeated GPU-only QE runs for the same case, program, input_deck_hash, and precision. The baseline must carry `measurements_are_real=true` and `evidence_status=measured`. CPU-only QE timing is reported separately as CPU context and must not replace GPU-only evidence.

## Generated Benchmark Boundary

Nonblocking generated QE cases use `case_origin=generated_benchmark` and `scientific_claim_scope=performance_benchmark_only`. Missing pseudopotentials are reported explicitly; QE runtime is not fabricated.

## Candidate High-Fidelity Evidence

Candidate high-fidelity evidence may be workflow-level trace replay, SystemC timing, gem5/SystemC, real QE candidate runs, or Vivado/DC resource and timing evidence with explicit tool provenance. L1 estimates and synthetic labels are not high-fidelity evidence.

## Generated EDA Stub Evidence

When selected Layer-4 candidates do not have implementation bindings, the campaign generates minimal RTL, HLS, and SystemC stubs and attempts a real EDA syntax run through local tools or `ic-eda`. Remote EDA commands force `LC_ALL=C LANG=C`. The resulting `qe_ic_candidate_eda_stub_evidence_real_run.json` artifact is non-claimable and does not replace workflow-level candidate evidence.

## Implementation-Limited vs Fundamental-No-Opportunity

`implementation_limited` means the current candidate loses but weak utilization, poor overlap, low fmax, immature implementation, missing calibration, or an idealized upper bound above 1.0 leaves opportunity open. `fundamental_no_opportunity` is only allowed when real baseline and workflow-level candidate evidence exist, implementation quality passes, resource and timing are feasible or intrinsically infeasible, the idealized upper bound is at or below 1.0, and no claim gate passes.

## Replace Templates

Replace templates by adding real input deck paths, GPU baseline run JSON, profile logs, and candidate evidence JSON to the campaign config. Missing tools or missing decks produce evidence_missing or blocked status, not fake measurements.

## Forbidden Conclusions

Do not claim FPGA-only or GPU+FPGA is faster than GPU-only unless the claim gate passes. EDA tool availability and generated-stub syntax success do not imply speedup. Fixture evidence, templates, L1 estimates, and synthetic labels are progress evidence only.

## Seven-Day Preliminary Label

The report includes `opportunity_summary.preliminary_classification` and mirrors the advisor-facing fields in `final_answer.preliminary_*`. The label is a preliminary triage result, not a final FPGA/hybrid superiority claim. Supported advisor labels are `fpga_hybrid_stronger`, `fpga_hybrid_weaker`, `gpu_dominant`, and `fundamental_no_opportunity`; when required baseline or candidate evidence is missing, the fail-closed label is `insufficient_evidence` and `advisor_labels_supported=false`.

- Preliminary label: insufficient_evidence
- Confidence: low
- Evidence tier: insufficient_evidence
- Final hardware claim allowed: False

## Current Answer

Generated proxy/stub evidence is available, but it is not final measured performance; no strong GPU-vs-FPGA superiority claim is allowed.
