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
11. Optional DFT-profile sections — `dft_evidence_ledger`,
    `dft_trial_state_ledger`, and `dft_full_scf_evaluated_hybrid`, when their
    artifacts are indexed; these are audit/reporting citations and never
    self-upgrade trusted claims.
12. `limitations` — gem5+SystemC blockers, missing metrics, and single-run
    scope limits.
13. `replay_instructions` — Python and simulator commands from the manifest.

## Claim validation rules

`claim_validation.json` is the Step4-owned gate artifact generated from the same
report payload and enforces:

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

Step5 must read the source Step4 `claim_validation.json` before writing
`final_report.json`.  If that source artifact has `passed=false` or omits a
positive pass flag, Step5 records
`run_metadata.source_step4_claim_validation_passed=false` and forces
`final_report.json.claim_validation.passed=false`; it may still present blocked
claims for audit, but it cannot regenerate a report-local `passed=true` claim
validation over an unpassed Step4 gate.

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
- Step5 can cite the DFT full-SCF evaluated-hybrid artifact bundle
  (`full_scf_accelerator_descriptor.json`, `full_scf_runtime_schedule.json`,
  `full_scf_data_residency_plan.json`, `full_scf_correctness_report.json`,
  `full_scf_ppa_summary.json`) under
  `dft_full_scf_evaluated_hybrid`; the bundle can be found directly in the
  Step5 run directory or indirectly through DFT ledger
  `full_scf_hybrid_bundle.artifact_refs`; this is schedule/cost accounting
  evidence only and keeps completion, numerical-correctness, and PPA
  eligibility fail-closed until independent gates pass;
- Wave 1.5 traces are explicitly progress-only and cannot be used as MVP,
  vertical-slice completion, or final closure claims.

Generate a replayable Wave 1.5 trace/runbook bundle:

```bash
python3 dse_v2/scripts/dse/build_dft_wave15_trace.py \
  --out runs/dse/<wave15_trace_run>
```

The generated `wave15_trace.json` reaches the Step5 reporting shape while
keeping `completion_claim=false` and `mvp_claim=false`; the default tool
evidence intentionally contains a Vivado blocker so downstream reports cannot
mistake the fixture for FPGA/ASIC closure.

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

Build the DFT full-SCF evaluated-hybrid accounting bundle from explicit cost
files before Step5 citation:

```bash
python3 dse_v2/scripts/dse/build_dft_full_scf_hybrid_bundle.py \
  --out runs/dse/<full_scf_hybrid_bundle> \
  --candidate-id <candidate_id> \
  --campaign-id <campaign_id> \
  --workload-run-id <workload_run_id> \
  --trial-id <trial_id> \
  --accelerated-kernel-costs-json <accelerated_kernel_costs.json> \
  --host-bound-costs-json <host_bound_costs.json> \
  --overhead-costs-json <overhead_costs.json>
```

Attach the bundle to the DFT candidate ledger without upgrading release
completion:

```bash
python3 dse_v2/scripts/dse/build_dft_candidate_evidence_ledger.py \
  --release-artifact-dir <release_domain_dir> \
  --full-scf-hybrid-artifact-dir runs/dse/<full_scf_hybrid_bundle> \
  --out runs/dse/<ledger_run>
```

If a Step5 run indexes the ledger artifacts but not the bundle files directly,
`final_report.json` still resolves readable ledger refs, marks
`dft_full_scf_evaluated_hybrid.source` as
`dft_evidence_ledger.full_scf_hybrid_bundle`, and uses the referenced
  `full_scf_accelerator_descriptor.json` cost model.  Missing or unreadable refs
stay report-visible but do not satisfy required bundle presence.

Build the DFT candidate binding map before the trial ledger when Step2
hierarchical IDs differ from the frozen seven-axis release IDs used by
candidate evidence rows:

```bash
python3 dse_v2/scripts/dse/build_dft_candidate_binding_map.py \
  --out runs/dse/<binding_run> \
  --hierarchical-search-report runs/dse/<step5_run>/release_domain/hierarchical_funnel_search_report.json \
  --candidate-universe-manifest runs/dse/<step5_run>/release_domain/candidate_universe_manifest.json \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json
```

Build the DFT trial state ledger that ties Step2 search candidates, bound
release candidate IDs, DFT evidence rows, Step5 report refs, and goal-audit refs
to Campaign / WorkloadRun / Trial state without upgrading claims:

```bash
python3 dse_v2/scripts/dse/build_dft_trial_state_ledger.py \
  --out runs/dse/<trial_ledger_run> \
  --hierarchical-search-report runs/dse/<step5_run>/release_domain/hierarchical_funnel_search_report.json \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json \
  --eda-all-candidate-evidence runs/dse/<step5_run>/dft_ledger/eda_all_candidate_evidence.json \
  --candidate-binding-map runs/dse/<binding_run>/dft_candidate_binding_map.json \
  --final-report runs/dse/<step5_run>/final_report.json \
  --goal-audit runs/dse/<step5_run>/dft_scf_hardware_goal_completion_audit.json
```

Build the hardware completion workplan to make the remaining per-candidate
kernel closure explicit and parallelizable:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_completion_workplan.py \
  --out runs/dse/<workplan_run> \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json \
  --dft-hardware-evidence-matrix runs/dse/<kernel_matrix_run>/dft_hardware_evidence_matrix.json \
  --ic-eda-tool-availability runs/dse/<ic_eda_probe_run>/ic_eda_tool_availability.json \
  --candidate-binding-map runs/dse/<binding_run>/dft_candidate_binding_map.json
```

IC/EDA availability can be refreshed independently and reattached to the DFT
ledger/Step5 report.  Step5 surfaces the availability payload status, raw
attempt count, and `completion_claim=availability_only_not_kernel_ppa`; it must
not mark the availability artifact as kernel PPA, timing, area, Vivado
implementation, DC synthesis, hardware completion, or deliverable completion.
Missing probes, zero raw attempts, unavailable tools, `command not found`
output, or mislabeled availability payloads remain blockers in the goal audit.
Wave35 source-flow reports must keep the same boundary: `ic_eda_tool_availability.json`
and `ic_eda_tool_attempts.json` may justify scheduling real Vivado/DC/VCS/HLS
runs, but they are not `source_flow_map.json` entries, not source-flow
`manifest.json` evidence, and not substitute PPA for any candidate/kernel row.

Shard that workplan for parallel execution assignment:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_shards.py \
  --out runs/dse/<closure_shards_run> \
  --hardware-completion-workplan runs/dse/<workplan_run>/dft_hardware_completion_workplan.json \
  --max-units-per-shard 16
```

Packet each shard into a candidate-specific execution runbook before assigning
Vivado/DC/VCS/HLS closure work:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_packets.py \
  --out runs/dse/<closure_packets_run> \
  --hardware-closure-shards runs/dse/<closure_shards_run>/dft_hardware_closure_shards.json
```

Materialize packet-referenced candidate bundle templates without creating raw
evidence or claim upgrades:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_candidate_bundles.py \
  --out runs/dse/<closure_packets_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

Step5 surfaces `dft_hardware_closure_candidate_bundles` separately from
evidence intake.  The bundle index is valid only if every referenced
`candidate_bundle.json` stays template-only (`raw_evidence_file_count=0`,
`raw_evidence_present=false`, no expected evidence row marked present, no
hardware/deliverable completion flags) and every bundle path remains inside the
evidence root.

Stage candidate/kernel-scoped provenance metadata without creating raw evidence:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_unit_provenance.py \
  --out runs/dse/<unit_provenance_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

Step5 surfaces `dft_hardware_closure_unit_provenance` separately from both
candidate bundles and evidence intake.  The section reports
`staged_unit_count`, `global_provenance_file_count`,
`raw_stage_evidence_file_count=0`, validation status, and fail-closed
`hardware_completion_eligible=false` / `deliverable_complete=false` flags.
The four per-unit files (`tool_versions.json`, `command_manifest.json`,
`raw_transcript_index.json`, and `source_bundle_manifest.json`) are
orchestration/audit provenance only; an empty staged transcript index is not a
raw transcript and cannot satisfy any hard claim gate.

Plan candidate/kernel source-flow bindings before broad materialization:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_source_flow_plan.py \
  --out runs/dse/<source_flow_plan_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --source-flow-map runs/dse/<source_flow_map_run>/source_flow_map.json
```

For Wave35, build `runs/dse/<source_flow_map_run>/source_flow_map.json` as the
36 × 8 source-flow-map input before invoking this step.  Use the explicit
`flows[]` form so the report can audit exact provenance:

```json
{
  "flows": [
    {
      "candidate_id": "<release_candidate_id>",
      "kernel_id": "<major_kernel_id>",
      "source_flow_dir": "runs/dse/<candidate_kernel_source_flow_run>"
    }
  ]
}
```

The complete release target has 288 intended rows.  Each row's
`source_flow_dir` must contain a `manifest.json` with matching `candidate_id`
and `kernel_id`; old kernel-only manifests are expected to surface as
`source_flow_candidate_id_missing`.

Step5 surfaces `dft_hardware_closure_source_flow_plan` before
`dft_hardware_closure_raw_stage_materialization`.  The section reports
`planned_unit_count` / `unit_count` (288 for the current 36 × 8 release target),
`source_flow_present_count`, `source_flow_missing_count`,
`blocked_unit_count`, wrong-candidate/wrong-kernel/reused-source-flow blocker
counts, provenance mismatch counts, validation status,
`adjudication_result=not_adjudicated_by_source_flow_plan`,
`passed_stage_count=0`, and fail-closed completion flags.  A valid plan makes
exact rows eligible for later raw-stage materialization only; any missing or
mismatched source-flow row keeps the release blocked and cannot satisfy golden,
simulation, synthesis, Vivado, DC, PPA, Pareto, hardware-completion, or
deliverable gates.

When producing new DFT kernel source-flow directories with the RTL/HLS smoke
runners, pass `--candidate-id <release_candidate_id>` so `manifest.json`
contains the same release candidate ID that appears in the source-flow map.
Legacy flow directories whose manifests only name `kernel_id` are reported as
`source_flow_candidate_id_missing` blockers by the plan.

To execute selected candidate/kernel source-flow shards from the packet index,
use the Wave36 real source-flow runner:

```bash
python3 dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py \
  --out runs/dse/<real_source_flow_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --candidate-id <release_candidate_id> \
  --jobs <parallel_jobs>
```

The runner dispatches the per-kernel RTL/HLS flow scripts with `--candidate-id`,
candidate/run/kernel-scoped `--remote-dir`, and `--ssh-target ic-eda` by
default; use `--skip-remote` only for local candidate-stamped source-flow
generation without remote EDA.  It writes
`dft_hardware_closure_real_source_flow_run.json`,
`dft_hardware_closure_real_source_flow_run_validation.json`,
`dft_hardware_closure_real_source_flow_run_status.json`,
`source_flow_map.json`, and
`source_flows/<candidate>/<kernel>/...`.  Reports must keep the runner
fail-closed:
`adjudication_result=not_adjudicated_by_real_source_flow_run`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Its `source_flow_map.json` is an input to the
source-flow plan; the runner output is not a parser verdict, hard-gate pass,
PPA proof, or release-completion claim.

To summarize many completed all-eight candidate runs, insert the rolling latest
source-flow map discovery step before source-flow planning:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_latest_source_flow_map.py \
  --out runs/dse/<latest_source_flow_map_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --run-root runs/dse
```

The discovery report must be cited separately from the source-flow map/plan:
`discovery_status.json.included_run_count`, `excluded_run_count`,
`source_flow_root_count`, and `included_runs[].candidate_ids` describe ready
source-flow roots; `source_flow_mapped_count`, `source_flow_present_count`, and
`source_flow_missing_count` describe packet-index coverage.  Reports must keep
"ready source-flow candidates" distinct from "Step5 gated candidates" and from
"full-SCF/release-complete candidates".

Wave35 generated 288 candidate-stamped local source-flow directories for the
36 × 8 matrix, but those directories are source-flow presence only.  The
verified Wave36 run
`runs/dse/wave36_real_source_flow_run_cand_0715923dc14b29cd_all8_20260520T033600Z`
ran `cand_0715923dc14b29cd` for all eight kernels on `ic-eda` with
`skip_remote=false` and produced `source_flow_ready_count=8`,
`blocked_unit_count=0`, `passed_stage_count=0`,
`hardware_completion_eligible=false`, and `deliverable_complete=false`.
The filtered Step5 follow-up
`runs/dse/wave36_step5_real_source_flow_cand_0715923dc14b29cd_all8_20260520T034024Z`
reported `parsed_result_written_count=40`,
`stage_gate_passed_count=40`, `unit_gate_passed_count=8`,
`candidate_gate_passed_count=1`, filtered
`hardware_completion_eligible=true`, and `deliverable_complete=false`.
The current Wave36 run
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z` now reports
36 candidates × 8 kernels = 288 gated units:
`stage_gate_passed_count=1440`, `unit_gate_passed_count=288`, and
`candidate_gate_passed_count=36`; the latest source-flow map
`runs/dse/wave36_latest_source_flow_map_auto_ready_20260520T061756Z` reports
`source_flow_present_count=288` and `source_flow_missing_count=0`.
This is not full deliverable closure: `hardware_completion_eligible=true` is
scoped to the candidate×kernel hard-gate matrix, while
`deliverable_complete=false` and the goal audit remains blocked on DFT
ledger/provenance, current-goal L4 binding, full-SCF evaluated-hybrid
accounting, and release-claim gates.  Newer status should be read from the
latest `discovery_status.json`, source-flow map status, Step5 release gate, and
goal-audit artifacts.

The fail-closed Step5 sequence is:

1. candidate-id-stamped source-flow generation/staging;
2. optional latest source-flow map auto-discovery (`discovery_status.json`);
3. `source_flow_map.json`;
4. `dft_hardware_closure_source_flow_plan.json`;
5. `dft_hardware_closure_source_flow_plan_validation.json`;
6. `dft_hardware_closure_source_flow_plan_status.json`;
7. `dft_hardware_closure_raw_stage_materialization.json` for materialization
   eligible rows only;
8. `dft_hardware_closure_raw_transcript_registration.json`;
9. `dft_hardware_closure_evidence_intake.json`;
10. `dft_hardware_closure_parser_run.json`;
11. refreshed `dft_hardware_closure_parsed_evidence_manifest.json`;
12. `dft_hardware_closure_gate_adjudication.json`;
13. `dft_hardware_closure_release_gate.json`;
14. `dft_trial_state_ledger.json`, `final_report.json`, and
    `dft_scf_hardware_goal_completion_audit.json`.

`run_dft_hardware_closure_step5_sequence.py --source-flow-map
runs/dse/<source_flow_map_run>/source_flow_map.json` follows this ordering for
the indexed Step5 path.  Reports must treat
`blocked_no_valid_source_flows`, `blocked_partial_source_flow_plan`,
`blocked_reused_source_flow_count`,
`blocked_wrong_candidate_reuse_count`, `blocked_wrong_kernel_reuse_count`,
`blocked_invalid_manifest_count`, and `provenance_mismatch_count` as blockers
against raw materialization for the affected rows.  A latest discovery run with
`included_run_count > 0` is still partial when `source_flow_missing_count > 0`;
that condition must be reported as blocked/partial and cannot be promoted to a
release-complete, full-SCF, FPGA, ASIC, Pareto, or deliverable-complete claim.

Materialize existing candidate/kernel source-flow outputs into packet-expected
raw evidence filenames before transcript registration:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_raw_stage_materialization.py \
  --out runs/dse/<closure_run> \
  --closure-packet-index runs/dse/<closure_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_run> \
  --source-flow-dir runs/dse/<kernel_rtl_or_hls_flow> \
  --candidate-id <release_candidate_id> \
  --kernel-id <major_kernel_id>
```

Step5 surfaces `dft_hardware_closure_raw_stage_materialization` when present.
The section reports materialized units/files, validation status,
`adjudication_result=not_adjudicated_by_raw_stage_materialization`,
`passed_stage_count=0`, and fail-closed completion flags.  This helper does not
run tools, register raw transcript hashes, parse results, adjudicate gates, or
upgrade PPA/Pareto/completion claims.  It also reports
`missing_required_raw_stage_file_count` and `materialization_blocker_ids`; for
the DC ASIC gate, a missing `dc_synth.ddc` remains
`missing_dc_synth_ddc_design_database` even when real DC logs, reports, or a
mapped Verilog netlist exist as diagnostics.

Register already-present candidate-specific raw transcript refs before parsing:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_raw_transcript_registration.py \
  --out runs/dse/<raw_transcript_registration_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

Step5 surfaces `dft_hardware_closure_raw_transcript_registration` between unit
provenance and evidence intake.  The section reports registered units,
registered/present/missing/invalid raw-stage file counts, validation status,
`adjudication_result=not_adjudicated_by_raw_transcript_registration`,
`passed_stage_count=0`, and fail-closed completion flags.  This helper hashes
raw files that already exist and writes refs into the staged transcript index;
it never creates evidence, parses logs, adjudicates hard gates, or upgrades
PPA/Pareto/completion claims.

Check packet evidence-file presence without adjudicating the hard gates:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_evidence_intake.py \
  --out runs/dse/<closure_intake_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

Build the fail-closed stage-level adjudication ledger after intake:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_adjudication.py \
  --out runs/dse/<closure_adjudication_run> \
  --closure-evidence-intake runs/dse/<closure_intake_run>/dft_hardware_closure_evidence_intake.json
```

Run candidate-specific hard-gate parsers for any raw files already present:

```bash
python3 dse_v2/scripts/dse/run_dft_hardware_closure_parsers.py \
  --out runs/dse/<closure_parser_run> \
  --closure-evidence-intake runs/dse/<closure_intake_run>/dft_hardware_closure_evidence_intake.json \
  --evidence-root runs/dse/<closure_packets_run> \
  --parsed-root runs/dse/<closure_parser_run>
```

The parser-run artifact is still fail-closed: missing candidate bundles,
missing/stale unit provenance, invalid evidence paths, missing raw transcript
hash refs, or missing raw stage files remain blockers, parser outputs are
written only from existing candidate-specific raw files, and
`adjudication_result=not_adjudicated_by_parser_run` with
`passed_stage_count=0`.  The parser also requires unit-level provenance files
(`tool_versions.json`, `command_manifest.json`, `raw_transcript_index.json`,
and `source_bundle_manifest.json`) and blocks shared microkernel smoke manifests
that do not declare candidate-specific closure for the exact candidate/kernel.
Step5 reports parser `stage_blocker_ids`, `parser_status_counts`, discovered DC
target-library identity/status when present in parser metrics, and the verdict
count rollup.  Missing Vivado implementation-route completion is surfaced as
`vivado_implementation_route_not_completed` even when `synth_design` completed
successfully; missing `dc_synth.ddc` is surfaced as
`missing_dc_synth_ddc_design_database`; a complete raw DC file set whose logs
show missing/placeholder target libraries, gtech-only final mapping, unmapped
output, unconstrained timing, or non-physical zero cell area parses as
`verdict=blocked`, not as ASIC timing/area evidence.  Reports must not summarize
mapped Verilog/log/report presence as ASIC closure when target-library discovery
or DC parser blocker ids remain blocked.
Refresh `dft_hardware_closure_parsed_evidence_manifest.json` after parser runs
before using it for hard-gate adjudication; a pre-parser manifest is a
fail-closed readiness snapshot only.

Build the parsed-evidence manifest consumed by later adjudicators:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_parsed_evidence_manifest.py \
  --out runs/dse/<closure_parsed_manifest_run> \
  --closure-adjudication runs/dse/<closure_adjudication_run>/dft_hardware_closure_adjudication.json \
  --parsed-root runs/dse/<closure_parser_run>
```

Build the fail-closed hard-gate adjudication layer from parsed evidence:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_gate_adjudication.py \
  --out runs/dse/<closure_gate_adjudication_run> \
  --parsed-evidence-manifest runs/dse/<closure_parsed_manifest_run>/dft_hardware_closure_parsed_evidence_manifest.json
```

The gate-adjudication artifact may record per-stage gate passes from valid
parsed `verdict=passed` rows, but it keeps candidate/release completion,
trusted Pareto, FPGA PPA, and ASIC PPA claims fail-closed.

Roll hard-gate adjudication up to candidate/release scope:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_release_gate.py \
  --out runs/dse/<closure_release_gate_run> \
  --gate-adjudication runs/dse/<closure_gate_adjudication_run>/dft_hardware_closure_gate_adjudication.json
```

The release-gate artifact may set `hardware_completion_eligible=true` only
after every required candidate × kernel unit gate has passed.  Any missing,
blocked, failed, or not-adjudicated unit keeps `hardware_completion_eligible=false`
and the release blocked; for ASIC units this includes missing `dc_synth.ddc` or
blocked DC target-library discovery.  Even an all-unit pass still keeps
`deliverable_complete=false`; final completion remains a separate goal/release
claim decision.

When indexed in a Step5 run, `final_report.json` includes
`dft_candidate_binding_map`, `dft_hardware_completion_workplan`,
`dft_hardware_closure_shards`, `dft_hardware_closure_packets`,
`dft_hardware_closure_candidate_bundles`,
`dft_hardware_closure_unit_provenance`,
`dft_hardware_closure_source_flow_plan`,
`dft_hardware_closure_raw_stage_materialization`,
`dft_hardware_closure_raw_transcript_registration`,
`dft_hardware_closure_evidence_intake`,
`dft_hardware_closure_adjudication`,
`dft_hardware_closure_parsed_evidence`,
`dft_hardware_closure_parser_run`,
`dft_hardware_closure_gate_adjudication`,
`dft_hardware_closure_release_gate`, and `dft_trial_state_ledger`.  The
binding section reports search/bound/unmatched counts, duplicate release-ID
reuse, validation, and fail-closed completion flags.  The workplan section
reports release-candidate count,
major-kernel count, candidate × kernel × hard-gate work-item counts, shared
smoke coverage, and fail-closed hardware completion flags.  The shard section
reports unit/shard counts, blocked work-item counts, and missing
candidate-specific bundle/evidence counts.  The packet section reports
shard/packet/unit counts, expected candidate-specific evidence filename counts,
command-template coverage, packet/runbook refs, and the same fail-closed
bundle/evidence flags.  The unit-provenance section reports staged units,
metadata-file counts, `raw_stage_evidence_file_count=0`, validation, and
fail-closed completion flags as orchestration/audit provenance only.  The
source-flow-plan section reports 288-unit planning coverage, source-flow
present/missing/blocker counts, manifest identity validation, and fail-closed
completion flags before any raw files are copied.  The
raw-stage-materialization section reports existing source-flow outputs copied or
wrapped into candidate-specific packet filenames without adjudication.  The
raw-transcript-registration section reports candidate-specific SHA-256 refs for
already-present raw files and keeps parser/adjudication/completion separate.  The
intake section reports candidate-specific bundle and evidence-file
presence/missing counts while keeping
`adjudication_status=not_adjudicated_by_intake`.  The adjudication section
reports unit/stage counts, passed/blocked hard-gate counts, file presence
counts, and `adjudication_result=not_adjudicated`.  The parsed-evidence section
reports expected/present/missing parser outputs, schema-valid/invalid counts,
parsed verdict counts, and
`adjudication_result=not_adjudicated_by_parsed_manifest`.  The parser-run
section reports parser stage counts, parsed outputs written, blocked stage
counts, parser verdict counts, and
`adjudication_result=not_adjudicated_by_parser_run`.  The gate-adjudication
section reports stage gates passed/blocked/failed, unit gates passed/blocked
or failed, and the fail-closed release-claim boundary.  The release-gate
section reports candidate/release rollup counts and whether hardware completion
is eligible before final deliverable completion.  The trial section reports
Campaign / WorkloadRun / Trial IDs, candidate counts,
blocked/rejected/selected trial counts, `completion_eligible`, and
`deliverable_complete`.  These sections are orchestration/audit evidence only:
they prove ID provenance, closure-work enumeration, parallel queue/packet
assignment, file-presence intake, fail-closed stage accounting, parser-readiness
accounting, parser-run materialization, per-stage gate adjudication, and legal
transition continuity, not final release-level numerical correctness, trusted
Pareto, or FPGA/ASIC PPA closure.

Run the DFT/QE full-SCF hardware goal audit before any completion decision:

```bash
python3 dse_v2/scripts/dse/audit_dft_scf_hardware_dse_goal_completion.py \
  --run-dir runs/dse/<step5_run> \
  --out runs/dse/<step5_run>/dft_scf_hardware_goal_completion_audit.json \
  --allow-in-progress
```

This audit is intentionally stricter than a green Step5 report: it keeps status
`in_progress` before `2026-06-01 12:00:00` local time and while DFT ledger,
full-SCF, major-kernel, or FPGA/ASIC hard-evidence gates are blocked.

Scan for stale objective/date/eligibility terminology during report/manual
updates:

```bash
python3 dse_v2/scripts/dse/scan_dft_scf_stale_terms.py \
  --out runs/dse/<audit_run>/dft_scf_stale_term_scan.json
```

`must_fix_count` must be zero before treating a documentation or reporting
checkpoint as aligned with the active DFT/QE full-SCF hardware DSE objective.

Run targeted report validation tests:

```bash
python3 -m pytest -q dse_v2/tests/test_final_report_validation.py dse_v2/tests/test_full_flow_pilot.py
python3 -m pytest -q dse_v2/tests/test_dft_full_scf_hybrid_descriptor.py dse_v2/tests/test_dft_scf_hardware_dse_prd.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_real_source_flow_run.py
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

To cite an already-produced complete-DSE L4 matrix inside a DFT hardware Step5
run without overclaiming candidate equivalence, build the fail-closed binding:

```bash
python3 dse_v2/scripts/dse/build_dft_l4_goal_binding.py \
  --out runs/dse/<step5_run> \
  --l4-root runs/dse/complete_dse_full_l4_evidence_final_20260519T040705Z \
  --step5-run runs/dse/<step5_run> \
  --quiet
python3 - <<'PY'
from pathlib import Path
from dse_v2.reporting.final_report import write_step5_report_artifacts
write_step5_report_artifacts(Path("runs/dse/<step5_run>"), claims=[])
PY
```

Step5 then surfaces `dft_l4_goal_binding`.  A binding can report
`l4_software_visible_proof_present=true` while still keeping
`current_goal_l4_bound=false` when candidate IDs (`cdse_*` versus `cand_*`) or
workload scopes (legacy QE mainflows versus strict six-SCF/full-SCF classes)
are not explicitly crosswalked.  The goal audit treats artifact visibility and
current-goal identity binding as separate checks; neither is FPGA/ASIC PPA or
deliverable completion evidence.

For full-SCF evaluated-hybrid reports, `full_scf_evaluated_hybrid_costs` must
surface both kernel-scope and end-to-end accounting.  If a run has descriptor
costs but no direct `kernel_speedup` metric, Step5 derives
`kernel_speedup=(baseline_scf_time_s - host_bound_cost_s) /
accelerated_kernel_cost_s` and records
`kernel_speedup_source=derived_from_baseline_scf_minus_host_bound_cost`.  This
derived metric is an accounting field only; it cannot create a trusted Pareto,
FPGA, ASIC, or deliverable-complete claim.

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
