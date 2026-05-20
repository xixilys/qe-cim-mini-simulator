# DFT-first QE end-to-end DSE flow

Status: implementation/runbook note
Scope: QE `pw.x` source-fact workloads only; not a VASP/all-DFT promise.

## Source anchors checked

- Quantum ESPRESSO's official repository is `gitlab.com/QEF/q-e`; the repo layout includes `PW`, `PHonon`, `FFTXlib`, `LAXlib`, and `KS_Solvers`, which matches this adapter's focus on `pw.x` stages plus FFT/dense/eigensolver-style hotspots: <https://gitlab.com/QEF/q-e>.
- The official PWscf user guide documents `pw.x` SCF and band-structure workflows and is the parser/runbook anchor for Step1 QE source facts: <https://www.quantum-espresso.org/Doc/pw_user_guide/>.
- QE's GPU/exascale work identifies heterogeneous accelerator porting for `PW scf`, `PHonon`, and related codes as active work, and reinforces the FFT/linear-algebra hotspot split used only as Step2 candidate hints here: <https://arxiv.org/abs/2104.10502> and <https://pubs.acs.org/doi/abs/10.1021/acs.jctc.3c00249>.
- Recent FPGA electronic-structure literature explores hardware-native streaming Hamiltonian/eigensolver pipelines for semi-empirical methods such as EHT/DFTB0; this is only a future FPGA dataflow/eigensolver reference and is not used as QE plane-wave DFT proof or final ranking evidence: <https://arxiv.org/abs/2602.11702>.
- gem5's official build/run documentation defines the real `gem5.opt` simulation-script invocation shape; this flow treats gem5 as mandatory for Step4 non-smoke evidence, not as a smoke/demo substitute: <https://www.gem5.org/documentation/general_docs/building>.

## Implemented runner

Entry point:

```bash
python3 dse_v2/scripts/dse/run_dft_first_end_to_end_dse.py \
  --qe-input path/to/pw.in \
  --qe-log path/to/pw.out \
  --case-id qe_case \
  --out runs/dse/qe_case_dft_first
```

For multi-stage workflows, pass a JSON bundle:

```json
{
  "stages": [
    {"program": "pw.x", "stage_type": "scf", "input_path": "scf.in", "log_path": "scf.out"},
    {"program": "pw.x", "stage_type": "nscf", "input_path": "nscf.in"},
    {"program": "bands.x", "profile_path": "bands_profile.json"}
  ]
}
```

and run:

```bash
python3 dse_v2/scripts/dse/run_dft_first_end_to_end_dse.py \
  --workflow-json workflow.json \
  --case-id qe_workflow \
  --gem5-binary /path/to/real/gem5.opt \
  --out runs/dse/qe_workflow_dft_first
```

The runner materializes relative `input_path`, `log_path`, and `profile_path`
entries before Step1 import.  Multi-stage workflow packages preserve both
per-stage `source_facts` and a flattened `domain_metadata.dft.source_facts`
list, so the strict completion audit can verify that QE provenance survived
before Step2/Step3/Step4 decisions.

## Stage boundaries

1. **Step1 QE source parsing**
   - Uses `dse_v2/reference_workloads/dft_qe.py::DftQePwImporter`.
   - Emits `workload_package.json`, `workload_graph.json`, and `workload_characterization.json` under `step1/`.
   - Characterization may include `domain_phase_summary`, `domain_workflow_summary`, and `domain_claim_summary`.
   - Step1 remains facts-only: no mapping, placement, schedule, runtime policy, descriptor choice, simulator verdict, or architecture selection.

2. **Step2 architecture/mapping candidate generation**
   - Runs per catalog architecture ID under `architectures/<architecture_id>/step2/`.
   - Enables the explicit DFT reference policy in `dse_v2/reference_workloads/dft_step2_policy.py`.
   - Policy output is candidate-only: DFT phase hints may bias FPGA/GPU/host seeds, but Step2/L1/L2 estimates are never final ranking evidence.

3. **Step3 timing pre-screen**
   - Runs `model/generic_sim_backend/build/generic_sim` for each promoted Step2 design point.
   - Writes full evidence under `architectures/<architecture_id>/step3_systemc/`.
   - `dft_end_to_end_summary.json` selects `best_architecture` by minimum measured Step3 latency among verified candidates.
   - The summary keeps Step2 estimates and Step3 measured tool output in separate fields.

4. **Step4 real gem5 GenericAccel validation**
   - Runs Step3-verified candidates through `dse_v2.backends.gem5_systemc_adapter.Gem5SystemCClosureAdapter` in measured-latency order.
   - If the fastest Step3 candidate fails real gem5 closure, the runner records that attempt and continues to the next verified candidate rather than downgrading to smoke/demo evidence.
   - Local transport fallback is disabled.
   - Trusted Step4 timing requires all of:
     - `gem5.log` descriptor/read/decode/microarchitecture/complete markers;
     - `stats.txt` copied from gem5 `m5out`, with positive `simTicks`,
       `finalTick`, `simInsts`, `simOps`, and `system.cpu.numCycles` counters
       parsed by the auditor;
     - `config.ini` or `config.json` copied from gem5 `m5out`;
     - replay command in `manifest.json`;
     - `artifact_manifest.json` hashes for raw gem5/config/proof/activity
       artifacts;
     - completion evidence in `gem5_completion_descriptor.json`;
     - non-zero GenericAccel activity in `gem5_activity_summary.json`.

## Output contract

Top-level summary:

```text
runs/dse/<run>/dft_end_to_end_summary.json
```

Completion audit:

```bash
python3 dse_v2/scripts/dse/audit_dft_first_end_to_end_run.py runs/dse/<run>
```

The runner also writes `dft_end_to_end_audit.json` automatically at the end of
each run.  The audit fails closed if any objective requirement lacks concrete
artifacts.  It verifies, among other checks, that Step1 is facts-only and uses
the expected Step1 schemas, Step2 estimates are candidate-only, Step3 summary
latency matches raw `generic_sim` request/result/numerical-validation/verdict
artifacts and a replayable `generic_sim` manifest command.  The Step3 audit
checks both the public `simulation_result.json` and the true simulator output
`simulation_result.raw.json`, and requires the manifest `--result` path to point
to that raw artifact.  It also validates `artifact_manifest.json` hashes for the
audited Step3 request/result/validation/verdict files so raw-result tampering
outside the latency field is rejected.  Step3 best selection is the minimum
measured verified latency among Step4-passing candidates, and Step4 has real
gem5 non-smoke evidence (`gem5.log`, `gem5_stdout.txt`,
`stats.txt`, config, replayable real-gem5 manifest command, command/completion
descriptors, proof `source_artifacts`, proof checks recomputed from raw
log/stdout/result artifacts, and non-zero accelerator activity cross-checked
against the raw gem5 microarchitecture result).

Important fields:

- `step1.facts_only == true`
- `step2_step3_records[*].step2_estimated_screening`
- `step2_step3_records[*].step3_measured_timing`
- `best_architecture.selected_by`
- `step3_best_architecture` for the pre-Step4 latency ranking
- `step4_gem5.trusted_step4_timing`
- `step4_gem5.attempts[*]` when multiple Step3-ranked candidates are tried before a passing real-gem5 closure
- `completion.trusted_final_dft_correctness_claimed == false`

The runner can be invoked with `--skip-gem5-l4` only for local Step1-Step3 development.  That mode marks Step4 untrusted, writes a failing audit, and exits non-zero; it is not a completion path for the full objective.

## Fresh official-QE-source reproduction

During the 2026-05-14 CST validation window, an additional non-smoke end-to-end
run used Quantum ESPRESSO's official `PW/examples/example01` Si `scf` and
`bands` reference artifacts from the upstream `QEF/q-e` repository as Step1
workflow parser inputs.  The locally measured Step3/Step4 evidence remained the
only trusted timing basis.

Upstream source artifacts used:

- `PW/examples/example01/run_example`: <https://gitlab.com/QEF/q-e/-/blob/master/PW/examples/example01/run_example>
- `PW/examples/example01/reference/si.scf.david.out`: <https://gitlab.com/QEF/q-e/-/blob/master/PW/examples/example01/reference/si.scf.david.out>
- `PW/examples/example01/reference/si.band.david.out`: <https://gitlab.com/QEF/q-e/-/blob/master/PW/examples/example01/reference/si.band.david.out>

```text
source bundle: runs/dse/dft_first_qe_official_source_20260514_044406
source provenance:
  resolved QE commit at provenance check:
  770a0b2d12928a67048e2f3da8d10d057e52179e
  provenance artifact:
  runs/dse/dft_first_qe_official_source_20260514_044406/source_provenance.json
run:           runs/dse/dft_first_qe_official_ref_gem5_refresh_20260514_044816
audit:         status=passed check_count=41 failed_count=0
best:          balanced-generic-systemc-v0
Step3 latency: 21.631 ms
Step4:         real gem5 GenericAccel, accelerator_event_count=8,
               total_cycles=814913, total_flops=400841749
```

After the Step4 `stats.txt` semantic gate was added, the same official QE
workflow was rerun with real gem5 evidence:

```text
run:           runs/dse/dft_first_qe_official_ref_gem5_stats_semantics_20260514_102804
audit:         status=passed check_count=44 failed_count=0
proof:         stats_txt_present=true, stats_semantics_present=true
stats fields:  simTicks=4168053000, finalTick=4168053000,
               simInsts=1606342, simOps=3874032,
               system.cpu.numCycles=4511236
best:          balanced-generic-systemc-v0
Step3 latency: 21.631 ms
Step4:         real gem5 GenericAccel, accelerator_event_count=8,
               total_cycles=814913, total_flops=400841749
```

This run exposed and then closed a workflow-specific evidence gap: the
multi-stage Step1 package now emits aggregate `domain_phase_summary` and
flattened workflow `source_facts` in the same audit-visible location as
single-stage QE bundles.

The current audit also contains `step4_no_smoke_demo_or_fallback_tokens`, which
scans the selected Step4 replay command and proof fields for `--skip-gem5-l4`,
unqualified smoke markers, demo markers, or `fallback_from_gem5=true`.  The
doc-pinned refreshed goal-support guard scan
`runs/dse/dft_first_goal_support_scans_20260514_131913_fpga_paper_refresh/no_smoke_guard_scan.json`
passed for both the hardened single-stage QE run and the official multi-stage QE
run.  That historical DFT-first audit was gated by an earlier
continuous-running horizon; the active DFT/QE full-SCF hardware DSE goal now
uses the `2026-06-01 12:00:00 CST` date gate and must be audited with the
current goal-level checklist before completion.
