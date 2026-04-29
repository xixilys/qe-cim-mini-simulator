# QE FPGA DSE E2E v0 Runbook

This runbook drives the contract-only frontend/backend loop for a small QE-like
workload. It is a proxy/smoke evidence path, not a final FPGA performance or QE
correctness claim.

## Command

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_e2e_v0 \
  --include-gem5-smoke
```

## What it does

1. Runs Unified DSE v0 frontend screening and emits Stage-B0 descriptors.
2. Selects the first executable Stage-B0 backend request.
3. Runs backend `systemc_timed_functional` with `--allow-execute`.
4. Ingests the backend report back into frontend EvidenceIR.
5. Adds B3 `gem5_systemc_smoke` evidence by converting the legacy smoke report by default.
6. Writes:
   - `qe_fpga_dse_e2e_manifest_v0.json`
   - `qe_fpga_dse_performance_summary_v0.json`

## Claim boundary

Allowed claims are limited to:

- `systemc_timed_functional_proxy_only` for the SystemC proxy report.
- `gem5_systemc_smoke_only` for the gem5 smoke report.

Forbidden claims remain out of scope:

- QE numerical equivalence / scientific correctness.
- Cycle accuracy.
- RTL, HLS, board, ASIC, or physical FPGA measurement.
- End-to-end acceleration on real FPGA hardware.

Use `--require-real-gem5-smoke` only when local gem5/QE smoke prerequisites are
available; otherwise the default legacy B3 conversion keeps the run reproducible
without elevating the claim ceiling.
