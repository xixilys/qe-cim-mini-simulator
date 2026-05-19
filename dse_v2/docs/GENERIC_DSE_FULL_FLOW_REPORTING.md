# Generic DSE Full-Flow Reporting and Claim Validation

## Purpose

This document records the Task 3 review outcome for the generic DSE team run and
specifies the implemented final-report surface for generic WorkloadPackage /
ComputeGraph evidence runs. The current runnable pilot is profile/importer
driven; QE is only an optional reference profile/importer, not the default core
path.
It complements `omx/team-generic-dse-run-cli-manager.md` by documenting how the
current code avoids overclaiming while still producing auditable report artifacts.

## Current implementation status

- `dse_v2/scripts/dse/run_full_flow_pilot.py` resolves a workload profile and
  importer, then runs the resulting generic WorkloadPackage through the generic
  SystemC timing backend when `generic_sim` is built. Optional reference
  importers enter through the same WorkloadPackage / ComputeGraph contract.
- `dse_v2/evidence/full_flow.py` writes the core evidence contract: manifest,
  verdict, design point, architecture, mapping, workload graph, simulation
  request/result, phase/resource/data summaries, logs, and gem5+SystemC blocker
  records. The target contract also includes `workload_package.json` and
  `graph_lowering_report.json` so non-DAG, hierarchical, looping, streaming, or
  stateful workload graphs can be audited before simulation.
- `dse_v2/reporting/final_report.py` now generates the P5 report artifacts:
  - `final_report.json`
  - `final_report.md`
  - `claim_validation.json`
- The report generator treats a single pilot as **single-run feasibility
  evidence**, not as a final best-architecture or Pareto-frontier conclusion.

## Generated report schema

`final_report.json` is machine-checkable and contains these top-level sections:

1. `run_metadata` — run id, backend, evidence mode, replay commands, and trust
   flag from `verdict.json`.
2. `workload` — workload package/graph id, graph size, profile/importer id,
   graph lowering status, full-workload coverage requirements, and any missing
   coverage.
3. `architecture_catalog_scope` — architecture id/family/status and whether the
   instance is eligible for trusted final ranking.
4. `search_configuration` — mapping id, mapping policy, search status, and
   explicit single-candidate convergence/budget labels when no optimizer loop ran.
5. `trusted_ranking` — trusted SystemC/gem5+SystemC-backed entries only. For the
   current pilot this is scoped as feasibility evidence, not winner evidence.
6. `predicted_only_candidates` — candidates or placeholders that cannot be used
   as winners.
7. `selected_recommendation` — `not_selected` unless a comparative search has
   trusted evidence for the selected design.
8. `pareto_alternatives` — empty until comparable trusted candidates exist.
9. `claims` — each claim has a claim id, type, backend, fidelity, trust flags,
   evidence ids, and limitations.
10. `evidence_index` — run-local artifact availability for required evidence and
    report outputs.
11. `limitations` — gem5+SystemC blockers, missing metrics, and single-run
    scope limits.
12. `replay_instructions` — Python and simulator commands from the manifest.

## Claim validation rules

`claim_validation.json` is generated from the same report payload and enforces:

- Trusted claims must use `systemc` or `gem5_systemc` backend evidence.
- Trusted claims cannot be `predicted_only` or `blocked`.
- Trusted claims cannot use L1/L2/analytical/TLM/surrogate sources.
- Trusted claims must be backed by complete SystemC or gem5+SystemC full-flow
  simulation artifacts; smoke-only, fixed-timing bring-up, diagnostic replay, or
  legacy smoke-conversion evidence is a final-check failure.
- Trusted claims must list run-local `evidence_ids`, and every evidence id must
  resolve to an existing artifact file.
- Predicted-only candidates cannot be emitted as best architecture, selected
  recommendation, or Pareto-frontier winner claims.
- A selected recommendation, when present, must be SystemC/gem5+SystemC-backed
  and evidence-linked.

## DFT/QE full-SCF hardware-DSE workstream gates

`dse_v2/codesign/dft_scf_workstreams.py` adds the DFT/QE-specific guardrails
used by the PRD workstreams without adding QE-only fields to the generic
control-plane schemas:

- strict Step1 bundles must cover the six required DFT/QE workload classes and
  carry QE input, pseudopotential, replay command, reference hash, provenance /
  license, parser/tool version, and proof-class assets;
- Step2 formal Pareto/frontier filters admit release-tier candidates only and
  keep exploratory candidates visible as excluded rows;
- Step3/Step4 hardware claim gates treat unavailable tool logs as blockers, not
  pass evidence, and reject DC-only FPGA claims or Vivado-only ASIC claims;
- Step5 full-SCF hybrid reports separate kernel speedup from end-to-end SCF
  evaluated speedup and include host-bound compute, transfer,
  synchronization/queueing/layout, I/O, SCF control, convergence,
  diagonalization, and mixing costs;
- Wave 1.5 traces are explicitly progress-only and cannot be used as MVP,
  vertical-slice completion, or final closure claims.

## Commands

Build the generic timing backend first:

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j4
```

Run the full-flow pilot and produce report artifacts:

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend systemc \
  --evidence-mode debug \
  --out runs/dse/sparse_la_systemc
```

Regenerate report artifacts for an existing run directory:

```bash
python3 -m dse_v2.reporting.final_report runs/dse/sparse_la_systemc
```

Run targeted report validation tests:

```bash
python3 -m pytest -q dse_v2/tests/test_final_report_validation.py dse_v2/tests/test_full_flow_pilot.py
```

Run a bounded multi-candidate feedback/convergence pilot:

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend systemc \
  --evidence-mode debug \
  --feedback-samples 2 \
  --out runs/dse/feedback_convergence_<timestamp>
```

Run the real gem5 GenericAccel L4 microarchitecture/timing proof:

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend gem5_systemc \
  --gem5-real-l4 \
  --evidence-mode debug \
  --out runs/dse/l4_full_flow_real_<timestamp>
```

## Review notes and remaining blockers

- The current standalone SystemC path may be trusted for per-run timing evidence
  only when all required full-workload coverage checks for the selected profile
  are present and the simulator exits 0. Coverage checks are profile-declared
  or derived from the lowered executable graph.
- The gem5 GenericAccel descriptor/decode/microarchitecture/completion path is trusted only for runs with a
  passing `gem5_l4_proof.json`; missing-proof attempts remain blocked.
- Multi-candidate feedback runs now record `mapping_simulation_samples.json`,
  `mapping_feedback_state.json`, and `convergence_status.json`; budget
  exhaustion is reported as a limitation rather than convergence.
- Additional feedback samples emitted by the pilot CLI are raw Step3
  measurements, not final-trusted samples, until each sample has its own Step4
  verdict/claim-validation/evidence-requirements bundle.  The pilot records the
  blocker as `missing_step4_adjudication_for_feedback_sample` instead of
  inflating trusted sample counts from raw simulator success alone.
- Final best-architecture, mapping-comparison, and Pareto claims require multiple
  comparable SystemC/gem5+SystemC evidence runs and cannot be created by a single
  pilot report.
