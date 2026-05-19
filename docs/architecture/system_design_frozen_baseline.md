# System Design Frozen Baseline

> Date: 2026-05-18  
> Status: **frozen baseline for implementation**, not final deliverable completion.

## 1. Purpose

This document consolidates the current architecture baseline so implementers do not need to infer the active design from scattered v0/v1/v2 planning documents. It freezes the **design boundary and evidence contracts** while leaving proof-gated implementation work visible.

## 2. System mission

Build a domain-neutral DSE system that can ingest workload families, generate architecture/mapping/co-design candidates, promote candidates through L1/L2/L3/L4 evidence, and emit claim-checked reports whose trusted claims resolve to concrete artifacts.

QE full-callgraph offload search is an active reference proof lane for real software-visible L4 value, not a core-schema specialization.

## 3. Frozen stage model

| Stage | Owns | Must emit | Must not claim |
|---|---|---|---|
| Step1 workload ingestion | Workload profiles/importers, `WorkloadPackage`, `ComputeGraph`, lowering facts | workload package/graph/lowering artifacts | Architecture choice, mapping value, acceleration value |
| Step2 architecture/mapping/co-design | Architecture catalog, DesignPoint, legality, mapping search, offload target identity, promotion | candidate records, mapping/codesign artifacts, promotion/blocker reasons | L3/L4 measured value |
| Step3 simulation evidence | L1/L2/L3/L4 execution, simulator/gem5 request/result/verdict | simulation/evidence artifacts, correctness/speed/blockers | Final report completion by itself |
| Reporting/claim layer | Claim validation, final report, artifact manifest, checklist | machine/human reports with claim-to-evidence links | Hidden upgrades from projection/smoke/local tests |

## 4. Frozen fidelity and trust model

| Level | Role | Claim power |
|---|---|---|
| L1 analytical | Screening/pruning and cheap ranking hint | No final value claim |
| L2 TLM/Python | Medium-fidelity screening and uncertainty hint | No final value claim |
| L3 SystemC/generic simulator | Replayable timing/resource evidence | Conditional evidence, bounded by numeric/reference limitations |
| L4 gem5 GenericAccel | Software-visible descriptor/request/execute/completion proof | Required for QE `valuable_l4` rows |
| Smoke/diagnostic | Dataflow/bring-up only | Never actual-compute or value proof |

## 5. Frozen object contracts

| Object | Baseline contract | Current files |
|---|---|---|
| Workload package / graph | Domain-neutral source/provenance/profile/graph/tensor metadata | `dse_v2/evidence/full_flow.py`, `dse_v2/reference_workloads/` |
| Architecture template/catalog | Family/instance/binding separation; reusable across workload families | `docs/architecture/architecture_template_schema_v1.json`, `docs/architecture/architecture_templates/` |
| Design point | Architecture + mapping + schedule + data placement + simulation config | `docs/architecture/generic_dse/design_point_schema.md` |
| Evaluation result | Evidence mode, metrics, verdict, claim boundary | `docs/architecture/generic_dse/evaluation_result_schema.md` |
| Offload target identity | Candidate identity changes when offload target/bundle changes | `dse_v2/codesign/qe_callgraph_offload_search.py` |
| QE L4 attempt row | Non-smoke full QE/gem5 L4, replacement, correctness, baseline, speed, blockers | `dse_v2/scripts/dse/run_qe_callgraph_offload_l4_smoke.py`, `dse_v2/scripts/dse/run_qe_bundle_single_workflow_l4_actual_compute.py` |
| QE speed diagnostic | End-to-end pure-QE vs patched-QE speed formula plus stage/timer/bridge breakdown without value-claim promotion | `dse_v2/scripts/dse/build_qe_bundle_speed_diagnostics_report.py`, `docs/architecture/qe_offload_speed_judgement.md` |

## 6. Frozen QE offload DSE lane

The QE offload lane searches which workload/stage/kernel/callsite/bundle to offload. It is not h_psi/s_psi-only. A row can be `valuable_l4` only when all value gates pass:

1. non-smoke full QE actual-compute evidence;
2. gem5 GenericAccel L4 descriptor/request/decode/execute/completion evidence;
3. QE consumes accelerated replacement output as computation output;
4. software fallback is not on the selected critical path;
5. correctness passes against pure QE baseline;
6. pure QE baseline records GPU runtime context when available;
7. end-to-end `pure_qe_elapsed / patched_qe_elapsed > 1.0`;
8. row and report keep `deliverable_complete=false` for the first pass.

The speed ratio is intentionally workflow-level. Kernel timers, bridge launch counts, and selected-stage deltas are recorded to explain the result, but they are not allowed to replace the end-to-end speed gate.

Latest folded matrix evidence is recorded in `design_completion_statement.md` and `implementation_gap_matrix.md`.

## 7. Implementation freedoms

Implementers may change module internals, add scripts, and refine report shape as long as these invariants hold:

- core stays domain-neutral;
- all generated claims remain evidence-backed;
- no projection/smoke/sidecar/local-only evidence is upgraded to value;
- all blockers remain machine-visible;
- generated run artifacts stay under `runs/` or equivalent evidence directories, not active docs.
