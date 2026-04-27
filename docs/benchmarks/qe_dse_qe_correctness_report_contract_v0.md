# QE DSE QE-equivalent correctness report contract v0

## Purpose

This contract defines the external Stage C artifact accepted by
`docs/benchmarks/run_unified_dse_v0.py --qe-correctness-report`.
The Unified DSE CLI validates and references this artifact; it does not run QE,
SystemC, gem5, or the compare helper itself.

## Schema identity

- `schema_version`: `qe_dse_qe_equivalent_correctness_report_v0`
- `qe_tolerance_schema_id`: `qe_gold_numerical_tolerance_schema_v0`
- Strict claim ceiling for a passing QE-equivalent correctness claim:
  `qe_equivalent_scf_correctness_only`

## Required fields

```json
{
  "schema_version": "qe_dse_qe_equivalent_correctness_report_v0",
  "execution_status": "executed",
  "claim_ceiling": "qe_equivalent_scf_correctness_only",
  "report_id": "stage_c_correctness_run_id",
  "candidate_id": "candidate join key from Unified DSE",
  "workload_id": "si4_pbe_uspp_small",
  "case_id": "si4_pbe_uspp_small",
  "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
  "correctness_status": "pass",
  "qe_equivalent_scf_claim": true,
  "compare_report": {
    "schema_name": "qe_gold_numerical_tolerance_schema_v0",
    "schema_version": "2026-04-13",
    "overall_pass": true,
    "summary": {
      "status": "pass",
      "failed_required_fields": []
    }
  },
  "evidence_refs": {
    "baseline": "artifacts/baseline/<case>.gold.json",
    "candidate": "artifacts/candidate/<case>.candidate.json",
    "compare_report": "artifacts/compare/<case>.compare.json"
  }
}
```

## Accepted correctness statuses

- `pass`
- `mismatch`
- `baseline_missing`
- `baseline_normalization_error`
- `candidate_missing`
- `model_error`
- `compare_error`

A report can set `qe_equivalent_scf_claim = true` only when:

1. `execution_status = executed`;
2. `correctness_status = pass`;
3. `claim_ceiling = qe_equivalent_scf_correctness_only`;
4. `compare_report.overall_pass = true`;
5. the tolerance schema is the frozen QE gold schema.

Mismatch/failure reports may still be referenced, but they do not prove Stage C.

## Non-claims

This artifact does not claim performance, energy, HLS/RTL/OpenROAD/board
readiness, ASIC tapeout readiness, or a final public architecture winner.
