# QE Offload Speed Judgement

> Date: 2026-05-18  
> Status: normative speed-claim guide for the active QE full-callgraph offload DSE lane.

## 1. Speed metric

QE offload speed is judged with an end-to-end pure-QE baseline comparison:

```text
speedup_vs_pure_qe = pure_qe_baseline_elapsed_seconds / patched_qe_elapsed_seconds
```

A positive speed signal requires:

```text
speedup_vs_pure_qe > 1.0
```

Equivalently, the patched QE workflow must finish strictly faster than the pure QE baseline for the same frozen workload case.

## 2. What elapsed time includes

For a workflow such as SCF prerequisite + NSCF target stage, the elapsed comparison includes every `include_in_performance` QE step that is part of the frozen workflow. The selected offload stage is also broken out for diagnosis, but the value gate remains end-to-end.

Kernel timers, bridge invocation counts, and SCF/NSCF stage splits are diagnostics only. They can explain why speed is positive or non-positive, but they do not replace the end-to-end ratio.

## 3. Required context before speed can contribute to value

A positive speed signal is necessary but not sufficient for `valuable_l4`. The row or bundle must also prove:

1. non-smoke full QE actual-compute execution;
2. gem5 GenericAccel L4 descriptor/request/decode/execute/completion provenance;
3. QE consumed accelerated replacement output;
4. software fallback was not on the selected critical path;
5. numerical/correctness gates passed against the pure QE baseline;
6. GPU runtime context was recorded for the pure QE baseline when GPU support is available;
7. first-pass reports keep `deliverable_complete=false`.

## 4. Current bundle diagnostic snapshot

Latest bundle diagnostic report:

`runs/dse/qe_bundle_single_workflow_actual_compute_20260518T124150Z_runtime_supported_nscf_stress_fast_driver_repeat3_prelaunch_all_repeat2/bundle_speed_diagnostics_report.json`

Key fields:

- `status=speed_positive`
- `bundle_id=bundle_runtime_supported_workload_stage_qe_si_nscf_bandgrid_v1_nscf_a7733ff1`
- `target_kernels=["fft", "subspace_rotation"]`
- `single_qe_workflow_proven=true`
- `single_qe_workflow_covers_full_bundle=true`
- `bundle_level_valuable_l4=true`
- `baseline_elapsed_seconds=92.70430073299212`
- `patched_qe_elapsed_seconds=91.03916892899724`
- `speedup_vs_pure_qe=1.0182902790478408`
- `patched_minus_baseline_seconds=-1.665131803994882`
- `seconds_to_reach_parity=0.0`

Stage breakdown:

| Stage | Baseline s | Patched s | Delta s | Bridge active |
|---|---:|---:|---:|---|
| `stage_00_scf_prerequisite` | 2.7285624499927508 | 2.720517175999703 | -0.008045273993047886 | false |
| `stage_01_nscf` | 89.97573828299937 | 88.30382044900034 | -1.6719178339990322 | true |

Bridge invocation counts:

| Kernel | Invocations | Launches | Returncode |
|---|---:|---:|---:|
| `fft` | 4 | 1 | 0 |
| `subspace_rotation` | 2 | 1 | 0 |

Interpretation: the selected bundle has real single-QE-workflow coverage, correctness evidence, and one positive end-to-end speed row after the stress/fast-driver/repeat3 branch. The folded bundle gate can now say `bundle_value_proven` for this single run. It still must not be described as stable or deliverable-complete: a nearby same-family repeat with the same repeat3 policy was slightly non-positive (`speedup_vs_pure_qe=0.9989713564404107`), so stability remains proof-gated.

## 5. Forbidden speed shortcuts

Do not use any of the following as acceleration value:

- smoke or dataflow-only runs;
- kernel-local microbench speed alone;
- gem5 descriptor/completion proof without full QE consumption;
- projection, analytical estimate, or L1/L2 ranking;
- member-level value folded into bundle-level value;
- positive speed without correctness/replacement/baseline gates.
