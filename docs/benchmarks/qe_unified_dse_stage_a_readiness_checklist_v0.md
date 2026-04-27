# QE Unified DSE Stage A readiness checklist v0

## 1. Purpose

This checklist is the documentation/readiness surface for the QE FPGA/ASIC co-design DSE Stage A lane.

It verifies that the Unified DSE artifacts are framed as backend-neutral, evidence-only, advisor-facing screening records. It does not validate RTL/HLS/board execution, cycle accuracy, gem5-controlled SCF, or QE-equivalent SCF.

## 2. Required companion contracts

Stage A readiness should be read with:

- `docs/benchmarks/qe_dse_systemc_feedback_contract_v0.md`
- `docs/benchmarks/qe_dse_gem5_systemc_handoff_contract_v0.md`
- `docs/benchmarks/qe_unified_dse_framework_v0.md`
- `docs/benchmarks/qe_dse_framework_user_manual_v0.md`
- `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md`
- `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md`

The advisor-facing architecture docs remain the reporting vocabulary. This checklist does not create a parallel recommendation language.

## 3. Stage split

| Stage | Allowed in this checklist | Not allowed in this checklist |
| --- | --- | --- |
| Stage A | Backend-neutral schema, dry-run DSE rows, SystemC feedback contract, gem5 handoff contract, QE anchor references, pre-adjudication ranking semantics. | Final winner, board evidence, cycle-accurate evidence, actual gem5-controlled SCF, QE-equivalent SCF. |
| Stage B | Planned handoff only. | Treating the planned handoff as executed co-simulation. |
| Stage C | Roadmap only. | Claiming QE-equivalent SCF closure. |

## 4. Claim-boundary checklist

Before marking Stage A docs/readiness complete, confirm:

- [ ] No document claims RTL, HLS, OpenROAD, FPGA-board, or board-measured evidence.
- [ ] No document claims cycle-accurate or physical-timing closure.
- [ ] No document treats CIM as the only backend identity; CIM is one possible backend/implementation style.
- [ ] No document claims actual gem5-controlled SystemC SCF execution.
- [ ] No document claims QE-equivalent SCF implementation or numerical closure.
- [ ] No document declares a final public family winner.
- [ ] Public recommendation authority remains with the adjudicator memo.

## 5. Backend-neutral identity checklist

Result rows and docs should preserve these distinctions:

- [ ] `candidate_family` is immutable architecture identity.
- [ ] `runtime_projection_family` is evaluator/projection metadata and may differ from `candidate_family`.
- [ ] `implementation_target_class` does not imply executor support.
- [ ] `backend_profile_id` describes the planned evaluator/backend path, not a public claim tier.
- [ ] F4/F5/custom candidates remain projection/scaffold unless explicit executor evidence is present.

## 6. SystemC feedback dry-run defaults

Dry-run Stage A rows should use:

| Field | Default |
| --- | --- |
| `systemc_feedback_contract.status` | `planned_not_executed` |
| `systemc_feedback_contract.execution_status` | `not_executed` |
| `systemc_feedback_contract.backend_class` | `systemc_timed_functional_proxy` |
| `systemc_feedback_contract.metrics_ref` | `null` unless an explicit opt-in run writes metrics |
| `systemc_feedback_contract.calibration_status` | `not_applicable_for_dry_run` or `missing` |
| `systemc_feedback_contract.claim_ceiling` | `timed_functional_proxy_contract_only` |
| `systemc_feedback_contract.subprocess_invoked` | `false` |

Readiness condition:

- [ ] Dry-run output can serialize the SystemC feedback object without running SystemC.
- [ ] Any future opt-in SystemC run remains labeled timed-functional/proxy, not board-measured or cycle-accurate.

## 7. gem5/SystemC Stage B handoff defaults

Dry-run Stage A rows should use:

| Field | Default |
| --- | --- |
| `gem5_handoff_contract.status` | `planned_for_stage_b` |
| `gem5_handoff_contract.handoff_status` | `planned` |
| `gem5_handoff_contract.execution_status` | `not_executed` |
| `gem5_handoff_contract.platform_status` | `requires_linux_x86_validation` |
| `gem5_handoff_contract.input_descriptor_ref` | planned descriptor path, not proof of execution |
| `gem5_handoff_contract.expected_report_ref` | planned report path, not proof of execution |
| `gem5_handoff_contract.claim_ceiling` | `stage_b_handoff_contract_only` |

Readiness condition:

- [ ] Stage A describes how to hand off to Stage B without claiming the Stage B path has run.

## 8. QE anchor status defaults

Stage A rows should carry `qe_anchor_refs` as references, not QE-equivalent closure proof.

Default object:

```json
{
  "schema_version": "qe_anchor_refs_v0",
  "status": "trace_or_correctness_anchor_only",
  "workload_id": "{workload_id}",
  "case_id": "{case_id}",
  "trace_ref": null,
  "dump_ref": null,
  "correctness_anchor_ref": null,
  "anchor_evidence_kind": "missing_or_trace_only",
  "qe_equivalent_scf_claim": false,
  "claim_ceiling": "anchor_reference_only"
}
```

Allowed `anchor_evidence_kind` values for Stage A documentation are:

```text
missing_or_trace_only
trace_only
correctness_capable_anchor
measured_reference
```

Interpretation:

- [ ] `trace_ref` and `dump_ref` identify inputs/evidence surfaces; they do not prove QE-equivalent SCF.
- [ ] `correctness_anchor_ref` may point to a gold/correctness artifact when available; it does not by itself create a final winner.
- [ ] `qe_equivalent_scf_claim` remains `false` for Stage A.

## 9. Pre-adjudication ranking semantics

Stage A may rank or shortlist rows for screening, but ranking is not a public recommendation.

| Field | Stage A default/allowed meaning |
| --- | --- |
| `screening_rank` | `null` or deterministic ordinal within the emitted dry-run candidate list only. |
| `pareto_membership` | `not_evaluated` unless all required comparable metrics are present. |
| `shortlist_reason` | `insufficient_metrics_for_shortlist`, `dry_run_contract_fixture`, or an artifact-backed screening note. |
| `ranking_claim_ceiling` | `stage_a_screening_only`; never `public_recommendation`. |
| `final_public_family_winner` | Always `null` in Stage A outputs. |
| `authority_scope` | `supporting_evidence_only`. |

Readiness condition:

- [ ] Any field that looks recommendation-like is labeled pre-adjudication evidence.
- [ ] Advisor-facing output uses `Recommended family = none-yet` unless an adjudicator memo authorizes stronger wording.

## 10. Advisor-facing alignment checklist

The family responsibility matrix requires a fixed comparison contract:

- [ ] same input case;
- [ ] same pseudopotential;
- [ ] same convergence threshold;
- [ ] same outer SCF accounting boundary;
- [ ] same QE gold correctness gate;
- [ ] algorithm-contract deviations explicitly marked and confidence downgraded.

The advisor report template requires these fields to remain aligned with evidence state:

- [ ] `Recommended family` is `F1`, `F2`, `F3`, or `none-yet`, with `none-yet` as the Stage A safe default.
- [ ] `Recommendation type` is `evidence-incomplete`, `ranking-grade`, or `projection-grade`, with no stronger Stage A wording.
- [ ] `correctness_status` is rubric-backed and defaults to `partial` when incomplete.
- [ ] `confidence` defaults to `exploratory` when evidence is incomplete.
- [ ] `speedup_to_convergence_range` and `energy_to_convergence_range` are shown only when projection-grade evidence is actually available.
- [ ] `algorithm_contract_deviation` is explicit.

## 11. Suggested Stage A dry-run commands

Focused dry-run command, when the CLI lane is available:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir /tmp/unified_dse_stage_a_smoke \
  --dry-run \
  --max-design-points 4
```

Focused artifact-key inspection, when such output exists:

```bash
python3 - <<'PYSMOKE'
import json
from pathlib import Path
root = Path('/tmp/unified_dse_stage_a_smoke')
bundle = json.loads((root / 'unified_dse_results_v0.json').read_text())
manifest = json.loads((root / 'unified_dse_manifest_v0.json').read_text())
assert bundle['authority']['claim_posture'] == 'evidence_only'
assert bundle['authority']['final_public_family_winner'] is None
assert manifest['winner_declared'] is False
row = bundle['results'][0]
for key in ['systemc_feedback_contract', 'gem5_handoff_contract', 'qe_anchor_refs', 'ranking_claim_ceiling']:
    assert key in row, key
print('stage-a contract keys ok')
PYSMOKE
```

Descriptor-only Stage B0 handoff command:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir /tmp/unified_dse_stage_b0_descriptors \
  --dry-run \
  --max-design-points 4 \
  --emit-stage-b0-descriptors
```

This optional flag writes descriptor-only sidecars:

```text
systemc_configs/{candidate_id}.json
gem5_systemc_handoff/{candidate_id}.json
stage_b0_descriptor_manifest_v0.json
```

The descriptor sidecars must remain `execution_status = not_executed` and
`claim_ceiling = descriptor_generation_only` or descriptor-only equivalents.
They are inputs for later Stage B adapters, not evidence that SystemC or gem5
executed.

SystemC feedback ingest, when an external artifact exists:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --systemc-feedback tmp/systemc_feedback.json \
  --output-dir /tmp/unified_dse_stage_b1_b2 \
  --dry-run
```

Full-stage status surface:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir /tmp/unified_dse_full_stage_status \
  --dry-run \
  --emit-stage-b0-descriptors \
  --emit-full-stage-status
```

`unified_dse_full_stage_status_v0.json` must show blocked statuses for any later
stage without real evidence. This is expected for gem5/SystemC smoke,
QE-equivalent SCF, and FPGA/ASIC implementation unless a later task supplies
external artifacts.

Stage B3 smoke intake, when a real external report exists:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --gem5-smoke-report tmp/gem5_smoke_report.json \
  --output-dir /tmp/unified_dse_stage_b3 \
  --dry-run \
  --emit-full-stage-status
```

The smoke report may move Stage B3 to `external_smoke_report_referenced`, but it
must not set `qe_equivalent_scf_claim = true` or use a claim ceiling above
`gem5_systemc_smoke_only`.

Stage C correctness intake, when a real compare-backed report exists:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --qe-correctness-report tmp/qe_correctness_report.json \
  --output-dir /tmp/unified_dse_stage_c \
  --dry-run \
  --emit-full-stage-status
```

The correctness report may move Stage C to
`external_qe_equivalent_correctness_pass_referenced` only when the report uses
the frozen QE gold tolerance schema and its compare payload passes. Otherwise it
is merely a referenced-not-proven artifact.

Stage D implementation-evidence intake, when real HLS/RTL/OpenROAD/board/ASIC
evidence exists:

```bash
python3 docs/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --implementation-evidence tmp/implementation_evidence.json \
  --output-dir /tmp/unified_dse_stage_d \
  --dry-run \
  --emit-full-stage-status
```

This can only reference narrowly scoped implementation evidence. It must not
declare a public family winner or production-ready implementation.

Documentation-only reviews may use `grep`/`sed` instead of running Python tests when code/test edits are outside scope.

## 12. Not-tested boundaries to report honestly

Unless a later task explicitly runs them, report these as not tested:

- gem5 controlling SystemC through a complete SCF loop;
- QE-equivalent SCF numerical closure;
- RTL/HLS/OpenROAD/FPGA board evidence;
- cycle-accurate or physical-timing closure;
- CPU+FPGA vs CPU+GPU final public winner claim.

## 13. Readiness outcome language

Use:

```text
Stage A documentation and contract surfaces are ready for evidence-only dry-run review and Stage B handoff planning.
```

Do not use:

```text
Stage A proves the accelerator implementation is complete or identifies a final public winner.
```
