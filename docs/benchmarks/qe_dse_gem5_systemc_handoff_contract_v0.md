# QE DSE gem5/SystemC handoff contract v0

## 1. Purpose

This contract freezes the Stage A -> Stage B handoff shape for a future gem5-controlled SystemC SCF experiment.

Stage A only defines the handoff record, descriptor fields, expected command shape, expected report fields, platform requirements, and non-claim wording. It does not implement or claim gem5-controlled SCF execution.

## 2. Stage A claim boundary

The handoff contract preserves these limits:

- no actual gem5-controlled SystemC SCF loop is claimed in Stage A;
- no QE-equivalent SCF implementation or numerical closure is claimed in Stage A;
- no cycle-accurate, physical-timing, RTL, HLS, OpenROAD, FPGA-board, or board-measured evidence is claimed;
- no CIM lock-in: the descriptor must carry backend-neutral identity and may describe CIM, non-CIM, mixed, FPGA-style, ASIC-style, or custom candidates;
- no final public family winner is produced by this handoff.

The allowed Stage A wording is:

```text
The gem5/SystemC path is a Stage B handoff contract. It is planned, not executed, and requires platform validation before it can become runtime evidence.
```

## 3. Required row-level object

A Stage A result row should carry a `gem5_handoff_contract` object.

Required keys:

| Key | Required Stage A meaning |
| --- | --- |
| `schema_version` | `qe_dse_gem5_systemc_handoff_contract_v0` |
| `status` | Dry-run/default: `planned_for_stage_b`. |
| `handoff_status` | Dry-run/default: `planned`; may become `blocked` or `ready_for_stage_b` only with explicit evidence. |
| `execution_status` | Dry-run/default: `not_executed`. |
| `platform_status` | Dry-run/default: `requires_linux_x86_validation` unless a later artifact proves otherwise. |
| `input_descriptor_ref` | Planned path to the Stage B descriptor consumed by the future driver. |
| `expected_command` | Human/machine-readable command template for a future Stage B run. |
| `expected_report_ref` | Planned path to the Stage B report artifact. |
| `output_report_expected_keys` | Stable list of fields expected from a future Stage B report. |
| `claim_ceiling` | Dry-run/default: `stage_b_handoff_contract_only`. |

## 4. Stage B defaults

For Stage A dry-run rows, the default object is:

```json
{
  "schema_version": "qe_dse_gem5_systemc_handoff_contract_v0",
  "status": "planned_for_stage_b",
  "handoff_status": "planned",
  "execution_status": "not_executed",
  "platform_status": "requires_linux_x86_validation",
  "input_descriptor_ref": "gem5_systemc_handoff/{candidate_id}.json",
  "expected_command": "stage_b_gem5_systemc_scf_driver --descriptor gem5_systemc_handoff/{candidate_id}.json --output gem5_systemc_reports/{candidate_id}.json",
  "expected_report_ref": "gem5_systemc_reports/{candidate_id}.json",
  "output_report_expected_keys": [
    "run_id",
    "environment",
    "workload_identity",
    "candidate_identity",
    "scf_control_loop_status",
    "systemc_bridge_status",
    "qe_equivalence_status",
    "metrics",
    "correctness_gate",
    "claim_ceiling"
  ],
  "claim_ceiling": "stage_b_handoff_contract_only"
}
```

The `expected_command` is a contract placeholder, not a claim that the command exists or passes in Stage A.

## 5. Input descriptor contract

A future Stage B descriptor should include these groups.

### 5.1 Candidate identity

```text
candidate_id
candidate_family
architecture_template_id
implementation_target_class
backend_profile_id
runtime_projection_family
design_axes
```

### 5.2 SystemC feedback linkage

```text
systemc_feedback_contract_ref
candidate_config_ref
metrics_ref
calibration_join_keys
claim_ceiling
```

### 5.3 QE/SCF anchor linkage

```text
workload_id
case_id
trace_ref
dump_ref
correctness_anchor_ref
pseudopotential_family
qe_tolerance_schema_id
convergence_threshold_ref
outer_scf_accounting_boundary_id
qe_equivalent_scf_claim
```

`qe_equivalent_scf_claim` must be `false` for Stage A handoff descriptors.

### 5.4 Platform requirements

```text
required_host_os
required_host_arch
gem5_build_ref
systemc_build_ref
compiler_toolchain_ref
known_platform_blockers
```

Default Stage A platform status is `requires_linux_x86_validation` because the handoff is not yet a verified runtime path.

## 6. Expected Stage B report fields

A future Stage B report should produce the following keys before it can become execution evidence:

| Key | Meaning |
| --- | --- |
| `run_id` | Unique Stage B run identifier. |
| `environment` | Host OS/arch, gem5 build, SystemC build, toolchain, and relevant runtime flags. |
| `workload_identity` | Echo of workload/case/QE anchor keys. |
| `candidate_identity` | Echo of candidate/backend-neutral identity keys. |
| `scf_control_loop_status` | Whether gem5 controlled the intended SCF loop. Stage A expected value: absent/not executed. |
| `systemc_bridge_status` | Whether gem5/SystemC bridge execution succeeded. Stage A expected value: absent/not executed. |
| `qe_equivalence_status` | Whether QE-equivalent SCF closure was proven. Stage A expected value: `not_claimed`. |
| `metrics` | Runtime metrics, if execution occurred in a later stage. |
| `correctness_gate` | Correctness comparison state, if a later stage implements it. |
| `claim_ceiling` | Evidence tier ceiling after the run. |

## 7. Non-claim wording

Use wording like:

```text
The gem5/SystemC record is ready as a Stage B handoff descriptor once platform prerequisites are satisfied. Stage A does not execute or validate the gem5-controlled SCF loop.
```

Do not use wording like:

```text
gem5 now controls QE-equivalent SCF.
The gem5/SystemC co-simulation is cycle accurate.
The Stage A DSE winner is final.
```

## 8. Advisor-facing alignment

This contract is downstream of the advisor-facing architecture docs:

- `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` defines the comparison contract that any Stage B report must preserve: same input case, pseudopotential, convergence threshold, outer SCF accounting boundary, and QE gold correctness gate.
- `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md` defines outward report fields. Until Stage B produces execution evidence, `Recommended family` should remain `none-yet` unless an adjudicator memo authorizes stronger wording; `Recommendation type` should remain `evidence-incomplete` or similarly bounded.

## 9. Readiness checks

A Stage A review should confirm:

- `gem5_handoff_contract.status = planned_for_stage_b`;
- `handoff_status = planned` unless explicit platform/runtime evidence supports `ready_for_stage_b`;
- `execution_status = not_executed`;
- `platform_status = requires_linux_x86_validation` by default;
- `claim_ceiling = stage_b_handoff_contract_only`;
- no row claims actual gem5-controlled SCF or QE-equivalent SCF.
