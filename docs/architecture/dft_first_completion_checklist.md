# DFT-first end-to-end DSE completion checklist

Status: live completion-audit checklist

This checklist maps the DFT-first objective to concrete artifacts and commands.
It is deliberately stricter than "tests pass": each requirement must have a
run artifact, an audit check, or an explicit limitation before the flow is
treated as complete.

Current evidence anchor:

```text
runs/dse/dft_first_qe_real_gem5_hardened_audit
```

Additional official-QE-source reproduction:

```text
runs/dse/dft_first_qe_official_ref_gem5_stats_semantics_20260514_102804
```

The runner writes `dft_end_to_end_audit.json` automatically.  Re-run the audit
manually with:

```bash
python3 dse_v2/scripts/dse/audit_dft_first_end_to_end_run.py \
  runs/dse/dft_first_qe_real_gem5_hardened_audit
```

The active goal-level prompt-to-artifact audit should be rebuilt from the
freshest live support artifacts, monitor snapshot, and tamper probe:

```bash
MON_DIR=$(ls -td runs/dse/dft_first_continuous_monitor_*_setsid_v6 | head -1)
SUPPORT=$(ls -td runs/dse/dft_first_goal_support_scans_* | head -1)
SNAPSHOT=$(ls -t runs/dse/dft_first_monitor_validation_snapshot_*_v6/monitor_validation_snapshot.json | head -1)
TAMPER=$(ls -t runs/dse/dft_first_real_artifact_tamper_probe_*_v3_rebased_sources/tamper_probe_result.json | head -1)

python3 dse_v2/scripts/dse/audit_dft_first_goal_completion.py \
  --main-run runs/dse/dft_first_qe_real_gem5_hardened_audit \
  --official-run runs/dse/dft_first_qe_official_ref_gem5_stats_semantics_20260514_102804 \
  --no-smoke-scan "$SUPPORT/no_smoke_guard_scan.json" \
  --domain-boundary-scan "$SUPPORT/domain_boundary_scan.json" \
  --external-reference-scan "$SUPPORT/external_reference_scan.json" \
  --tamper-probe "$TAMPER" \
  --monitor-dir "$MON_DIR" \
  --monitor-snapshot "$SNAPSHOT" \
  --allow-in-progress
```

Before the active date horizon it must report `status=in_progress` and
`completion_decision=do_not_mark_complete_before_date_horizon`. After the
horizon, re-run without `--allow-in-progress`; it is one final gate before
marking the goal complete.

Latest observed audit result:

```text
status=passed check_count=44 failed_count=0
```

Doc-pinned goal-level continuous validation refresh:

```text
date:      2026-05-14 13:20:17 CST (+0800)
monitor:   runs/dse/dft_first_continuous_monitor_20260514_112555_setsid_v6
snapshot:  runs/dse/dft_first_monitor_validation_snapshot_20260514_132017_v6/monitor_validation_snapshot.json
full iter: 600, latest_full_validation_passed=true, all_full_logs_preserved=true
audit:     runs/dse/dft_first_goal_completion_audit_20260514_132017_support_refresh_full600/goal_completion_audit.json
status:    in_progress
reason:    do_not_mark_complete_before_date_horizon
failed:    0
```

Additional durable local validation evidence:

```text
runs/dse/dft_first_additional_local_validation_20260514_130927/validation_manifest.json
status=passed
steps=cmake_configure, cmake_build, ctest_generic_sim, dft_targeted_pytest,
      compileall_dse_v2, py_compile_gem5_config, compileall_gem5_integration,
      git_diff_check
```

## Prompt-to-artifact checklist

| Requirement | Concrete evidence | Audit / validation gate | Current status |
|---|---|---|---|
| Use `date` to check East-8 time while working | shell `date '+%Y-%m-%d %H:%M:%S %Z (%z)'`; live evidence must be refreshed before any final completion audit. | Manual progress evidence; not a DSE correctness signal | Active until the current goal horizon `2026-06-01 12:00:00 CST` |
| Focus on QE workloads, not all DFT/VASP | `dft_end_to_end_summary.json` `scope.workload_focus`; runner inputs `--qe-input`, `--qe-log`, `--workflow-json` | `scope_qe_and_domain_neutral` audit check | Passed |
| Bad QE/workflow source paths fail closed | malformed or missing `--workflow-json` stage paths write `dft_end_to_end_summary.json` with `status=blocked_source_load` and a failing audit instead of an uncaptured traceback or partial success | `test_dft_first_runner_writes_failed_audit_for_bad_workflow_path` | Implemented and tested |
| Copied run audits remain copy-local | If a run directory is copied, Step1/Step2/Step3/Step4 paths and proof `source_artifacts` from the original summary are rebased into the audited copy before evidence is read, so copied evidence tampering is caught even when the original absolute paths still exist | `test_dft_end_to_end_auditor_uses_copy_local_step1_and_step4_artifacts`; reusable tamper probe `dse_v2/scripts/dse/run_dft_first_real_artifact_tamper_probe.py`; real-run copy tamper probe `runs/dse/dft_first_real_artifact_tamper_probe_20260514_122000_v3_rebased_sources/tamper_probe_result.json` | Implemented and tested |
| Keep core IR/mapping domain-neutral | DFT code under `dse_v2/reference_workloads`; generic Step2 policy seam under `dse_v2/mapping/domain_policy.py`; mapping reads policy annotations generically by `domain_key`, not hard-coded DFT keys | `scope_qe_and_domain_neutral` audit check; `test_dft_reference_logic_does_not_leak_into_core_or_mapping_layers`; `rg` boundary scan over `dse_v2/core` and `dse_v2/mapping` | Passed |
| Step1 parses QE source facts | `step1/workload_package.json`, `step1/workload_graph.json`, `step1/workload_characterization.json`; `domain_metadata.dft.source_facts` preserves `input` plus observed `log`/`profile` provenance | `step1_status_complete`, `step1_required_artifacts_present`, `step1_package_schema`, `step1_characterization_schema`, `step1_qe_source_facts_preserved` | Passed |
| Step1 outputs workload characterization | `workload_characterization.json` contains `domain_phase_summary`, `domain_workflow_summary`, `domain_claim_summary` | `step1_domain_summaries_present` | Passed |
| Multi-stage QE workflow preserves per-stage provenance | Workflow Step1 packages contain both `workflow.stages[*].source_facts` and flattened `domain_metadata.dft.source_facts`; aggregate `domain_phase_summary` spans all parsed stages | official-QE-source reproduction `dft_first_qe_official_ref_gem5_stats_semantics_20260514_102804`; `test_qe_workflow_bundle_emits_multi_stage_workflow_and_claim_summaries`; `test_dft_first_runner_materializes_qe_workflow_bundle_paths_before_skip_step4` | Implemented and tested |
| Step1 does not perform mapping/schedule/runtime/gem5 verdict | Step1 characterization excludes Step2/Step3/Step4 decision keys | `step1_facts_only`, `step1_no_decision_fields` | Passed |
| Step2 generates FPGA-oriented architecture/mapping candidates | per-architecture `step2/architecture_candidate_set.json`, `mapping_seed_set.json`, `domain_policy_hints.json`; DFT policy emits `dft-fpga-reference-v1` candidates/hints with FPGA target preferences | `step2_candidate_records_present`, `step2_artifacts_present:*`, `step2_dft_fpga_policy_hints:*` | Passed |
| Tested architecture scope is explicit | Runnable DFT-first timing scope uses `balanced-generic-systemc-v0` and `host-fpga-minimal-v0`; catalog also contains `future-custom-candidate-v0`, but it is `candidate-only` with no simulation bindings and is not part of the real Step3/Step4 ranking scope | catalog inspection via `seed_generic_dse_architecture_catalog()`; top-level summaries list both tested records and rank by measured Step3 latency among Step4-passing candidates | Passed for stated test scope |
| Step2 uses DFT workflow skeletons without polluting core IR | DFT policy reads adapter-scoped workflow phase skeletons and maps exact/hybrid exchange plus projector/augmentation phases into FPGA/GPU candidate groups while leaving the top-level generic hints schema unchanged; boundary scan found zero DFT/QE-specific terms in `dse_v2/core` and `dse_v2/mapping` | `test_dft_step2_policy_uses_workflow_stage_skeleton_for_fpga_candidate_groups`; reusable support scan resolved by `$SUPPORT/domain_boundary_scan.json` in the command above | Implemented and tested |
| Step2 L1/L2 estimates are candidate-generation only | `step2_estimated_screening.trusted_final_claim == false`, L1/L2 artifacts | `step2_estimate_boundary:*` | Passed |
| Step3 runs measured timing pre-screen | per-architecture `step3_systemc/simulation_request.json`, public `simulation_result.json`, true raw `simulation_result.raw.json`, canonical `simulator_consistency_check.json` (legacy `numerical_validation.json` compatibility), `verdict.json`, `manifest.json`; public and raw latencies/status/schema must match the top-level summary record, the manifest must replay `generic_sim --result` into the audited raw artifact, and `artifact_manifest.json` hashes must match the audited request/result/validation/verdict files | `step3_timing_verified:*`, `step3_raw_timing_artifacts_consistent:*`, `step3_artifact_manifest_hashes:*`, `step3_replay_manifest_consistent:*`, `step3_raw_result_replay_bound:*` | Passed |
| Best architecture is selected from measured results | `best_architecture` and `step3_best_architecture` in the top-level summary | `best_architecture_from_measured_step3` | Passed |
| Step4 uses real gem5 GenericAccel and no local/smoke fallback | `step4_gem5/*/gem5_l4_proof.json` with `fallback_from_gem5 == false` and `transport_harness == gem5_generic_accel_microarchitecture_v1` | `step4_attempted_real_gem5`, `step4_gem5_proof_checks_pass` | Passed |
| Step4 rejects skip/smoke/demo/fallback markers explicitly | formal audit check `step4_no_smoke_demo_or_fallback_tokens`; reusable support scan resolved by `$SUPPORT/no_smoke_guard_scan.json`, covers both the hardened single-stage run and official-QE multi-stage run | `test_dft_end_to_end_auditor_rejects_step4_smoke_or_demo_markers`; `test_goal_support_scan_builder_emits_reusable_guard_artifacts`; guard scan status `passed`; main and official audits include the check and pass | Passed |
| Step4 selected attempt is bound to the final best architecture | `best_architecture`, `step4_gem5.architecture_id`, `step4_gem5.step3_latency_ms`, `step4_gem5.run_dir`, and the selected passing entry in `step4_gem5.attempts[*]` all refer to the same candidate | `step4_selected_attempt_bound_to_best_architecture` | Passed |
| Step4 preserves non-smoke raw evidence | `gem5.log`, `gem5_stdout.txt`, `stats.txt`, `config.ini` or `config.json`, `manifest.json`, `artifact_manifest.json`, `gem5_command_descriptor.json`, `gem5_completion_descriptor.json`, `gem5_activity_summary.json`, `simulation_result.raw.json`; audit reads raw log/stdout markers, non-empty stats/config, positive gem5 counters (`simTicks`, `finalTick`, `simInsts`, `simOps`, `system.cpu.numCycles`), artifact-manifest hashes, a replayable real-gem5 command, proof `source_artifacts`, and recomputes proof booleans instead of trusting proof JSON alone | `step4_non_smoke_artifacts_present`, `step4_raw_gem5_evidence_consistent`, `step4_artifact_manifest_hashes`, `step4_gem5_stats_semantics_present`, `step4_manifest_replays_real_gem5`, `step4_proof_source_artifacts_exist`, `step4_proof_recomputed_from_raw_artifacts` | Passed |
| Step4 records non-zero accelerator activity | `gem5_activity_summary.json` with expected schema/engine, `accelerator_event_count > 0`, `total_cycles > 0`, `total_flops > 0`, and accelerator device IDs; summary must match raw `simulation_result.raw.json` events and microarchitecture summary | `step4_nonzero_accelerator_activity`, `step4_activity_matches_raw_result` | Passed |
| Iterate if a Step3-fastest candidate fails Step4 | `step4_gem5.attempts[*]`; runner tries Step3-verified candidates in measured-latency order until one passes real gem5 proof | `test_run_step4_gem5_attempts_step3_latency_order_until_first_non_smoke_pass`, `test_dft_end_to_end_auditor_accepts_step4_iterated_best_when_fastest_fails`, plus summary `selection_policy` | Implemented and tested |
| Do not claim DFT numerical/scientific correctness | summary `scope.trusted_final_dft_correctness_claimed == false` and `completion.trusted_final_dft_correctness_claimed == false` | `no_dft_correctness_claim` | Passed |
| Use public/open-source project and paper anchors | QE/gem5 source anchors in `dft_first_end_to_end_dse.md`; L1/L2 replacement-source matrix in `generic_dse/step2_l1_l2_evaluator_audit.md`; reusable support scan resolved by `$SUPPORT/external_reference_scan.json`, includes QE, pw.x input docs, gem5, SystemC, Timeloop/Accelergy, MAESTRO, and ALADDIN anchors | Documentation/source-scan review; no final-performance claim depends on those sources without measured artifacts | Satisfied |
| Rebuild goal support scans reproducibly | `dse_v2/scripts/dse/build_dft_first_goal_support_scans.py` emits no-smoke, domain-boundary, and external-reference JSON plus a support manifest | `test_goal_support_scan_builder_emits_reusable_guard_artifacts`; latest support scan should be selected with `ls -td runs/dse/dft_first_goal_support_scans_* \| head -1` and its manifest must have `status=passed` | Passed |
| Rebuild real artifact tamper probes reproducibly | `dse_v2/scripts/dse/run_dft_first_real_artifact_tamper_probe.py` copies a completed run, mutates Step4 `stats.txt` and `gem5.log`, and verifies the normal end-to-end auditor fails the expected checks | `test_real_artifact_tamper_probe_rejects_mutated_copied_step4_evidence`; real output `runs/dse/dft_first_real_artifact_tamper_probe_20260514_122000_v3_rebased_sources/tamper_probe_result.json` has `probe_status=passed` | Passed |
| Keep validation running through the active date horizon | Current goal-mode horizon is `2026-06-01 12:00:00 CST (+0800)`. Historical monitor evidence remains audit history only; fresh monitor/snapshot evidence is required before final completion. | Periodic main + official DFT audits, targeted DFT runner pytest every iteration, full pytest/compileall/gem5 config py_compile/GenericAccel compileall/`git diff --check` every 20 iterations; the latest validation snapshot must pass, preserve full-suite logs, and have its latest full validation iteration after the latest failure iteration | Active until 2026-06-01 12:00 CST |
| Final completion requires a prompt-to-artifact audit, not just green tests | `snapshot_dft_first_monitor_validation.py` produces monitor snapshots from raw monitor events/logs; `audit_dft_first_goal_completion.py` recomputes main and official run audits, checks no-smoke/domain/external/tamper artifacts, checks the monitor/snapshot, scans the monitor script for actual `sleep` commands, treats the date horizon as a first-class requirement, and rejects stale full-suite snapshots when the live monitor has advanced too far beyond them | Before the horizon, the goal audit must report `completion_decision=do_not_mark_complete_before_date_horizon`; after the horizon, re-run without `--allow-in-progress` and require no failed or in-progress requirements before `update_goal` | Active until 2026-06-01 12:00 CST |

## Validation commands

Use the following commands after changing this flow:

```bash
python3 -m pytest -q dse_v2/tests
python3 -m compileall dse_v2
python3 -m py_compile gem5_integration/configs/generic_accel_l4_test.py
git diff --check
python3 dse_v2/scripts/dse/audit_dft_first_end_to_end_run.py \
  runs/dse/dft_first_qe_real_gem5_hardened_audit
```

For a fresh real-gem5 proof, run the DFT-first runner with an explicit real gem5
binary/root, not `--skip-gem5-l4`.  `--skip-gem5-l4` is development-only, marks
the run untrusted, and exits non-zero so process-exit-only automation cannot
mistake Step1-Step3 development artifacts for completion.
