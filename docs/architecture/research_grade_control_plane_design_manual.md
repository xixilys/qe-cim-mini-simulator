# Research-Grade DSE Control Plane Design Manual

**Status:** active execution contract  
**Source plan:** `.omx/plans/ralplan-system-restructure-research-grade-closure-20260518T175509Z.md`  
**Primary proof path:** DFT profile/importer -> FPGA/gem5 evidence  
**Core rule:** domain-neutral control-plane contracts first; DFT stays in profile/adapter/schema.

This manual is the implementation-facing companion to the system restructure plan.  It freezes the contracts that must remain stable while the codebase is refactored.  If code, schemas, artifact names, state transitions, evidence gates, or claim semantics change, update this file and the relevant runbook in the same iteration.

## 1. Completion semantics

The system has three top-level delivery statuses:

| Status | Meaning | May satisfy the user goal? |
|---|---|---|
| `deliverable_complete` | All required artifacts, real hard-gate evidence, docs, and prompt-to-artifact checklist are present and verified. | Yes |
| `partial_blocked_not_complete` | Some work exists, but at least one hard gate, artifact, real-tool proof, or semantic requirement is missing/blocked/weakly verified. | No |
| `failed` | Execution reached a non-recoverable failure for the current attempt. | No |

A run may not convert `partial_blocked_not_complete` into final success by citing tests, mocked artifacts, missing tools, or a blocker report.  Failed gates trigger diagnosis and another implementation iteration unless the user explicitly changes the gate.

## 2. Control-plane entity model

The canonical control plane is:

```text
Campaign
  ├─ WorkloadRun / IngestionRun
  │    └─ Step1 workload artifacts
  └─ Trial / DesignPoint
       ├─ Step2 architecture + mapping + promotion artifacts
       ├─ Step3 simulation execution artifacts
       ├─ Step4 adjudication/calibration/feedback artifacts
       └─ Step5 reporting/claim-presentation artifacts
```

### 2.1 Entities

| Entity | Required role | Required IDs |
|---|---|---|
| `Campaign` | Top-level DSE campaign, owns objective, workload family, policy, ledger, and terminal status. | `campaign_id` |
| `WorkloadRun` / `IngestionRun` | Step1 ingestion/lowering attempt for a workload/profile input. | `campaign_id`, `workload_run_id` |
| `Trial` / `DesignPoint` | Step2+ candidate/design-point lifecycle unit. | `campaign_id`, `workload_run_id`, `trial_id`, `design_point_id` when applicable |
| `ArtifactRef` | Hashable reference to an artifact with producer, schema, path, and consumers. | `artifact_id`, `producer_step`, `schema_id`, `path`, `sha256` when materialized |
| `Activity` | Provenance activity such as ingestion, candidate generation, simulation, adjudication, report generation. | `activity_id`, `activity_type`, `inputs`, `outputs`, `agent` |
| `FailurePolicy` | Retry/no-retry/diagnostic/fail-fast behavior for tools and gates. | `policy_id`, `retry_class`, `max_attempts`, `terminal_on_failure` |

### 2.2 ID propagation rules

- `campaign_id` appears on every canonical artifact and every run directory manifest.
- `workload_run_id` appears on Step1 artifacts and every downstream artifact derived from that workload.
- `trial_id` appears on every Step2+ candidate, design point, simulation request/result, adjudication result, and report artifact.
- Domain-specific IDs, including DFT case IDs, are profile metadata and must not become required fields in domain-neutral schemas.

## 3. Step ownership split

| Stage | Owns | Must not own |
|---|---|---|
| Step1 | Workload ingestion, profile import, graph lowering facts, workload hints. | Architecture selection, final claims. |
| Step2 | Architecture family/search-space, candidate generation, mapping/co-design records, promotion/blocker reasons. | Simulation measurement, trusted final claims. |
| Step3 | Simulation execution only: backend request, raw backend outputs, simulation result, simulator consistency/timing calibration inputs. | `claim_validation.json`, `final_report.json`, `final_report.md`, final trust adjudication. |
| Step4 | Evidence adjudication, verdict, claim validation, calibration records, feedback update, canonical L4 metrics. | Human-facing final report presentation. |
| Step5 | Final report and claim presentation from Step4 evidence. | Raw backend measurement or trust adjudication. |

The phrase “Step3 final report” is stale.  Step3 may provide evidence consumed by later stages, but Step5 owns final report artifacts.

## 4. Canonical artifact ownership

| Artifact family | Canonical artifact | Producer | Consumers |
|---|---|---|---|
| Campaign ledger | `campaign_ledger.json` | Control plane | All stages, final audit |
| Workload package | `workload_package.json` | Step1 | Step2, reports |
| Compute graph | `compute_graph.json` | Step1 | Step2/search |
| Executable graph | `executable_graph.json` | Step1 lowering | Step2/Step3 |
| Architecture search space | `architecture_search_space.json` | Step2 | Candidate generation, audit |
| Candidate generation report | `architecture_candidate_generation_report.json` | Step2 | Screening, audit |
| Architecture screening report | `architecture_screening_report.json` | Step2 | Promotion, audit |
| Design point | `design_point.json` | Step2 | Step3 request |
| Mapping candidate records | `mapping_candidate_records.json` | Step2 | Step3/Step4/audit |
| Promotion decision | `mapping_promotion_decision.json` | Step2 | Step3 admission |
| Simulation request | `simulation_request.json` | Step3 | Backend, Step4 provenance |
| Simulation result | `simulation_result.json` | Step3 | Step4 adjudicator |
| Simulator consistency | `simulator_consistency_check.json` | Step4 | Step5/reporting |
| Timing calibration | `timing_model_calibration.json` | Step4 | Step2/search feedback, Step5/reporting |
| Kernel numerical validation | `kernel_numerical_validation.json` | Domain/profile validator | Step4, only when real numeric kernel evidence exists |
| Domain physics validation | `domain_physics_validation.json` | Domain/profile validator | Step4, DFT/physics claims only |
| Verdict | `verdict.json` | Step4 | Step5/reporting |
| Claim validation | `claim_validation.json` | Step4 | Step5/reporting |
| Calibration record | `calibration_record.json` | Step4 | Promotion/search feedback/reporting |
| Feedback update | `feedback_update.json` | Step4 | Step2/search policy |

Implementation status note (2026-05-19): `dse_v2/mapping/step2_workflow.py`
now writes the canonical Step2 search/provenance bundle alongside legacy
compatibility handoff files: `architecture_search_space.json`,
`architecture_candidate_generation_report.json`,
`architecture_screening_report.json`, `mapping_candidates.jsonl`,
`screening_results.jsonl`, and `promotion_decisions.jsonl`.  The JSONL files
are candidate/screening/promotion records only; they do not establish final
trust without Step3/Step4 evidence.

Feedback-sample hardening note (2026-05-19): additional SystemC feedback
samples generated by `run_full_flow_pilot.py --feedback-samples N` are raw
Step3 measurements unless a per-sample Step4 verdict/claim-validation/evidence
requirements bundle is present.  The pilot CLI therefore records these
additional samples in `mapping_simulation_samples.json` as
`blocked_or_untrusted_attempt` with
`missing_step4_adjudication_for_feedback_sample`; only callers that supply
sample-local Step4 adjudication may mark non-primary feedback samples
`trusted_final_eligible=true`.

Step3 admission additionally checks that `step3_simulation_queue.json` contains
a queue entry matching the promoted `design_point_id`, `mapping_id`,
`architecture_id`, and mapping candidate.  A tampered queue cannot schedule a
different candidate into Step3, even if the promotion decision is otherwise
green.

Step5 report generation requires Step4 `verdict.json`,
`claim_validation.json`, and `evidence_requirements.json` to exist before it
writes `final_report.json` / `final_report.md`.  Step5 may present blocked
claims, but it records the source Step4 claim-validation status and cannot
upgrade a failed Step4 gate into a trusted winner.
| L4 raw proof | `gem5_l4_proof.json` plus raw logs/traces | L4 adapter | Step4 |
| L4 canonical metrics | `l4_interface_metrics.json` | Step4 | Step5/reporting, feedback |
| Final report | `final_report.json`, `final_report.md` | Step5 | Human/release review |

Legacy `numerical_validation.json` is not a trusted canonical artifact name.  Existing runs may mention it as migration history, but new trusted evidence must use the narrower artifact names above.

A complete-DSE matrix produced before schema/registry/Step3-4-5/calibration/evidence-policy changes is only provisional.  Any such matrix pointer must be rerun or explicitly revalidated after the structural changes before it can support final claims.

## 5. DFT primary proof boundary

DFT is the current research-grade proof path, not a core dependency.  DFT-specific fields belong in:

- DFT profile/config schemas;
- DFT importers and reference workload fixtures;
- DFT domain validation artifacts;
- DFT-specific run/audit scripts;
- documentation sections that explicitly describe the proof path.

Generic core schemas must stay valid for non-DFT workload families.  If a generic artifact cannot be validated without DFT-only fields, the change violates the design contract.

The DFT full-flow audit must cite the frozen profile/schema contract from `dse_v2/reference_workloads/dft_profile_schema.py`, including `DFT_PROFILE_CONTRACT_VERSION`, `DFT_PROFILE_METADATA_SCHEMA`, `DFT_DOMAIN_VALIDATION_SCHEMA`, and `DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA`.  Missing or stale profile-owned metadata is a blocker, not a documentation warning.

## 6. L4/gem5 evidence boundary

The L4 adapter emits raw software-visible proof:

- descriptor writes/reads;
- request ingestion;
- decode/micro-op scheduling evidence;
- payload consumption;
- completion/result writeback visible to software;
- raw gem5 logs/traces/proof JSON.

Step4, not the adapter, canonicalizes interface metrics into `l4_interface_metrics.json`, including queue latency, MMIO/DMA counts, host-visible completion latency, and confidence/coverage metadata when available.

## 7. Hard gates for final closure

A `deliverable_complete` claim requires fresh evidence for the gates named in the test spec:

```bash
python3 -m pytest -q dse_v2/tests
python3 -m compileall dse_v2
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
ctest --test-dir model/generic_sim_backend/build --output-on-failure
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
python3 dse_v2/scripts/dse/run_dft_first_end_to_end_dse.py \
  --qe-input runs/dse/dft_first_fixture_restructure/qe.in \
  --qe-log runs/dse/dft_first_fixture_restructure/qe.out \
  --qe-profile runs/dse/dft_first_fixture_restructure/profile.json \
  --case-id qe_dft_full_restructure_final \
  --out runs/dse/dft_first_qe_full \
  --timeout 120 \
  --evidence-mode forensic
python3 dse_v2/scripts/dse/audit_dft_first_end_to_end_run.py runs/dse/dft_first_qe_full
```

For L4 and FPGA/EDA evidence, the agent must attempt real paths rather than placeholders:

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend gem5_systemc --gem5-real-l4 --out runs/dse/generic_l4_pilot
ic
source ~/.bashrc
which dc_shell || true; dc_shell -version || true
which vcs || true; vcs -ID || true
which vivado || true; LC_ALL=C LANG=C vivado -version || true
```

If `ic` is unavailable, use the verified SSH route described in `AGENTS.md` before concluding the local tool path is unavailable.  As of the 2026-05-19 key-auth probe, `ssh -o BatchMode=yes ic-eda` reaches host `IC_EDA` as `ICer` without a password prompt and exposes `dc_shell` O-2018.06-SP1, `vcs` O-2018.09, and Vivado 2019.1 after `source ~/.bashrc`.  The private key remains local at `~/.ssh/ic_eda_ed25519`; passwords must not be stored in repo files, scripts, logs, or SSH config.

### 7.1 Complete-DSE L4 matrix closure

Standalone proof gates are necessary but not sufficient:

- DFT full-flow/audit passing proves the DFT reference profile path is runnable.
- Standalone `gem5_systemc --gem5-real-l4` passing proves the GenericAccel
  L4 software-visible path can execute.
- Neither gate proves the complete-DSE matrix has trusted accelerated/offloaded
  QE numerical and domain/SCF correctness.

The complete-DSE L4 matrix is deliverable-complete only when every legal
release-candidate × frozen QE-mainflow row is present and unblocked.  A matrix
run that reports `blocked_or_partial` remains non-final even if all rows are
present.  Historical diagnostic evidence remains intentionally non-final:

- `runs/dse/complete_dse_full_l4_evidence_v2_20260518T202709Z_diagnostic/coverage_claim_report.json`
  reports 36 rows and 36 blocked rows and must remain classified as diagnostic.
- The matching command transcript is
  `.omx/context/complete-dse-full-l4-matrix-v2-diagnostic-20260518T202709Z.log`
  with `--fail-on-blocked` exit code 2.

Fresh post-native-bundle evidence now closes the matrix technical gate for the
current code snapshot:

- `runs/dse/complete_dse_full_l4_evidence_final_20260519T040705Z/complete_dse_full_l4_evidence_report.json`
  reports `status=deliverable_complete`, `row_count=36`,
  `expected_row_count=36`, and `blocked_row_count=0`.
- The run consumed `.omx/context/final-admissible-qe-l4-bundle.path`, which
  points to
  `runs/dse/qe_l4_full_gem5_native_hpsi_abs_current_20260519T014428Z/qe_accelerated_numeric_producer_evidence_bundle.json`.

Future candidate matrix runs must use immutable timestamped output directories
such as `runs/dse/complete_dse_full_l4_evidence_final_<UTC>`.  Do not overwrite
older diagnostic or final-candidate evidence directories.

### 7.2 Accelerated QE evidence admissibility

Accelerated/offloaded QE evidence consumed by final ranking must be bound by an
admissibility ledger.  At minimum, the ledger records:

- bundle, producer-index, remapped-requirements, and source-requirements paths;
- SHA-256 hashes for all of those files;
- producing command and environment;
- campaign/run identity and selected trial-row count;
- `writable_output_root`, which must be under the v2/timestamped run directory;
- status `final_admissible` only after producer counts and blocker checks pass.

When remapping frozen v1 requirements into a v2 evidence attempt, preserve
read-only QE baseline references and explicit `source_requirements` provenance,
but rewrite every writable `accelerated_numeric_inputs`, `evidence_output`,
row-template, and campaign-template path under the v2 root.  A recursive
old-root scan must fail if any writable
`runs/dse/complete_dse_full_l4_evidence_v1` path remains.

One-row trusted L4 proof is the required scale-up milestone before a full
36-row attempt.  The default representative row from the frozen requirements is
`cdse_a84a144ad07b71133cf1::qe_si_scf_small_v1`.  It may be changed only with
a recorded reason; pure-software, timing-only, or software-component-model
evidence remains diagnostic and cannot become `final_admissible`.


#### Current one-row gem5 h_psi sidecar status

There are now two distinct one-row h_psi sidecar classes:

1. Legacy component-model diagnostic
   `runs/dse/qe_l4_one_row_gem5_sidecar_abs_20260518T213029Z` proves only that QE
   invoked the sidecar and gem5 GenericAccel/SystemC transport passed.  It remains
   blocked because the payload is a Python/software component model and carries
   `software_component_model_not_l4=true`.
2. Native model-level L4 payload proof
   `runs/dse/qe_l4_one_row_gem5_native_hpsi_abs_20260518T230010Z` passed the
   producer under `--fail-on-blocked` with one selected row, one passed row, and
   zero blocked rows.  The trusted row records `full_h_psi_recomputed=true`,
   `software_component_model_not_l4=false`, `l4_execution_proof.passed=true`,
   `sidecar_observed_hpsi_calls=42`, `sidecar_consumed_hpsi_calls=42`,
   `sidecar_failed_hpsi_calls=0`, and `all_observed_hpsi_calls_sidecar_consumed=true`.

The native row is a **vertical slice**: SystemC/GenericAccel model L4 offload plus
kernel numerical evidence, not silicon/RTL proof and not deliverable-complete by
itself.  It only unlocks the 36-row final-admissible bundle attempt and the
complete-DSE matrix gate.

Runtime-sizing note (2026-05-19): the built-in `qe_si_bands_path_v1` proof
fixture uses a compact high-symmetry path with 13 k-points.  This is still a
real QE `bands` workflow stage, but avoids the previous 41-kpoint fixture
timing out under the campaign's per-stage timeout on the available workstation.
Timeout evidence from the older 41-kpoint attempt remains blocked evidence and
does not count toward final admissibility.



#### Current 36-row native h_psi bundle status

The current serial final-admissible bundle is
`runs/dse/qe_l4_full_gem5_native_hpsi_abs_current_20260519T014428Z`.  Its
producer index reports 36 selected rows, 36 passed rows, and zero blocked rows.
The wrapper log records `validate_qe_producer_counts(...)` success, and
`admissibility_ledger.json` has `status=final_admissible` and
`trial_row_count=36`.  The authoritative pointer for downstream matrix runs is
`.omx/context/final-admissible-qe-l4-bundle.path`.

This bundle closes the native h_psi technical evidence gate for the current
code snapshot.  It still supports only the documented model-level claim:
SystemC/GenericAccel L4 offload plus native h_psi kernel numerical evidence and
DFT/QE domain evidence, not RTL/silicon proof.  Any later code, schema, fixture,
or evidence-policy change can require a fresh bundle or explicit revalidation.

Producer-concurrency note (2026-05-19): the native h_psi QE evidence producer is
treated as a serial measurement path for final admissibility.  A diagnostic
per-candidate parallel attempt contaminated the QE runtime and produced
`cdiaghg` / `S matrix not positive definite` returncode-1 rows, while the same
candidate/workload passed when rerun alone.  Therefore parallel producer output
must be classified as diagnostic/invalidated unless a future isolation mechanism
proves per-row QE/gem5/h_psi sidecar processes do not interfere.  Parallel
implementation lanes may prepare code, docs, or independent verification, but
the final 36-row native h_psi bundle must be generated by a trusted serial or
otherwise isolation-proven producer.

## 8. Manual update discipline

Every implementation phase must update this manual or the benchmark runbook when it changes:

- schema families or artifact names;
- control-plane state transitions;
- Step ownership;
- DFT profile contracts;
- L4 evidence contracts;
- completion taxonomy;
- hard-gate command shape.

Documentation consistency is not a code feature.  It is an execution obligation for each modifying agent.
