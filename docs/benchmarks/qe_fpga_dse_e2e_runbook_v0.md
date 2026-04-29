# QE FPGA DSE E2E v0 Runbook

This runbook drives the contract-only frontend/backend loop for a small QE-like
workload. It is a proxy/smoke evidence path, not a final FPGA performance or QE
correctness claim.

## Command

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_e2e_v0 \
  --include-gem5-smoke \
  --include-gem5-b4
```

## What it does

1. Runs Unified DSE v0 frontend screening and emits Stage-B0 descriptors.
2. Selects the preferred Stage-B0 backend request family (`F2` by default,
   configurable with `--preferred-family`) so the reproducible baseline gate
   targets the QE/F2 path rather than accidentally consuming the first emitted
   descriptor.
3. Runs backend `systemc_timed_functional` with `--allow-execute`.
4. Ingests the backend report back into frontend EvidenceIR.
5. Adds B3 `gem5_systemc_smoke` evidence by converting the legacy smoke report by default.
6. Optionally runs B4 `gem5_systemc_timed_proxy` through the real gem5 binary and
   the guarded `simple_fpga_test.py` config. This requires an explicit
   `systemc_bridge_library` artifact and preserves that bridge path in both
   `environment.systemc_bridge` and `artifact_refs.systemc_bridge`.
7. Writes:
   - `qe_fpga_dse_e2e_manifest_v0.json`
   - `qe_fpga_dse_performance_summary_v0.json`

## Claim boundary

Allowed claims are limited to:

- `systemc_timed_functional_proxy_only` for the SystemC proxy report.
- `gem5_systemc_smoke_only` for the gem5 smoke report.
- `gem5_systemc_timed_proxy_only` for the optional B4 timed-proxy report.

Forbidden claims remain out of scope:

- QE numerical equivalence / scientific correctness.
- Cycle accuracy.
- RTL, HLS, board, ASIC, or physical FPGA measurement.
- End-to-end acceleration on real FPGA hardware.

Use `--require-real-gem5-smoke` only when local gem5/QE smoke prerequisites are
available; otherwise the default legacy B3 conversion keeps the run reproducible
without elevating the claim ceiling.

Use `--require-real-gem5-b4` only after `gem5_integration/gem5/build/X86/gem5.opt`
has been rebuilt with the `FPGAAccelerator` B4 parameters and
`gem5_integration/systemc_model/build/libgem5_systemc_bridge.a` exists. The
hard gate rejects refusal reports, smoke fallbacks, missing bridge provenance,
and reports without the B4 control/metric fields.
