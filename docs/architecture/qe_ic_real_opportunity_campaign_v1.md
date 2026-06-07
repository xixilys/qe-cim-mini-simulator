# QE-IC Real Opportunity Campaign v1

## Purpose

This campaign answers one bounded question: under a real GPU-only baseline, do
FPGA-only or GPU+FPGA hybrid candidates have an opportunity for selected QE-IC
cases?

The campaign is an orchestration layer. It does not define a new DSE objective
and does not replace the existing real-baseline opportunity claim gate. It
connects environment discovery, case preparation, Layer-4 candidate selection,
real/ingested evidence, implementation quality audit, and final interpretation.

## Flow

1. Probe local GPU, QE, profiler, SystemC, and EDA availability.
2. Prepare `ground_state_band_structure` and `electron_phonon_mobility` case
   descriptors. Missing input decks are marked `input_deck_missing`.
3. Build a GPU-only baseline from at least three real QE runs, or ingest a
   validated GPU-baseline artifact.
4. Select up to three candidates from the existing Layer-4 candidate plan only:
   FPGA FFT/streaming, hybrid reduction sidecar, and hybrid DMA/memory staging.
5. Ingest workflow-level trace replay, SystemC, gem5/SystemC, real QE, or
   Vivado/DC-backed candidate evidence with explicit provenance.
6. Call the existing real GPU-baseline opportunity analysis package.
7. Audit whether losses are implementation-limited, fundamentally unattractive,
   invalid, evidence-missing, or inconclusive.
8. Emit a plain final answer with missing evidence and next actions.

## Evidence Boundary

Missing tools or missing inputs are valid campaign outcomes. They produce
`evidence_missing` or blocked status, not fabricated measurements. Templates,
L1 estimates, and synthetic feedback labels are search/progress evidence only.

The campaign may report `opportunity_found` only when the existing claim gate
returns a claim-allowed FPGA or hybrid opportunity record.

## Allowed Conclusions

- `opportunity_found`
- `implementation_limited`
- `fundamental_no_opportunity`
- `gpu_dominant_no_fpga_or_hybrid_opportunity`
- `evidence_missing`
- `inconclusive`

## Forbidden Conclusions

The campaign must not claim FPGA-only or GPU+FPGA superiority from EDA tool
availability, templates, fixed candidates, L1 estimates, synthetic labels,
kernel-only evidence, or fixture records.
