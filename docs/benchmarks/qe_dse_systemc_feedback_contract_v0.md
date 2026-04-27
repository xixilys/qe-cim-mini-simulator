# QE DSE SystemC feedback contract v0

## 1. Purpose

This contract freezes the Stage A handoff shape between the Unified DSE layer and the existing SystemC timed-functional/proxy model.

It defines what a DSE row may say about a planned or executed SystemC feedback path, which keys must be serializable in result JSON/CSV/manifest artifacts, and which claims remain forbidden at Stage A.

Stage A uses this contract to prove that a candidate can carry SystemC feedback metadata without requiring SystemC execution. It does **not** upgrade the evidence tier.

## 2. Stage A claim boundary

The contract is intentionally bounded:

- no RTL, HLS, OpenROAD, FPGA-board, or board-measured claim;
- no cycle-accurate or physical-timing claim;
- no CIM lock-in: CIM is one possible backend/implementation style, not the schema identity;
- no actual gem5-controlled SystemC SCF claim;
- no QE-equivalent SCF numerical-closure claim;
- no final public family winner or public recommendation.

The allowed Stage A wording is:

```text
SystemC feedback is represented as a timed-functional/proxy contract record.
Dry-run rows are planned-not-executed evidence scaffolds.
Any public family decision remains adjudicator-controlled.
```

## 3. Required row-level object

A Stage A result row should carry a `systemc_feedback_contract` object. The object is row-local and must not overwrite backend-neutral identity keys.

Required top-level keys:

| Key | Required Stage A meaning |
| --- | --- |
| `schema_version` | `qe_dse_systemc_feedback_contract_v0` |
| `status` | Planning/availability status for the feedback path. Dry-run default: `planned_not_executed`. |
| `execution_status` | Whether a SystemC subprocess/model was run. Dry-run default: `not_executed`. |
| `backend_class` | `systemc_timed_functional_proxy`; never `rtl`, `hls`, `board`, or `cycle_accurate`. |
| `candidate_config_ref` | Path or planned path to the candidate SystemC config sidecar. |
| `metrics_ref` | Path to metrics emitted by a real opt-in run, or `null` for dry-run. |
| `metrics_expected_keys` | Stable list of metric names expected if a future opt-in run occurs. |
| `calibration_join_keys` | Keys used to join the feedback record with workload/QE/calibration evidence. |
| `calibration_status` | Dry-run default: `not_applicable_for_dry_run` or `missing`. |
| `claim_ceiling` | Dry-run default: `timed_functional_proxy_contract_only`. |
| `subprocess_invoked` | Boolean; dry-run default: `false`. |

## 4. Candidate input keys

The SystemC feedback sidecar should be generated from backend-neutral identity plus workload identity. It must not assume that every candidate is CIM-backed.

Minimum candidate identity keys:

```text
candidate_id
candidate_family
architecture_template_id
implementation_target_class
backend_profile_id
runtime_projection_family
design_axes
```

Minimum workload/QE anchor keys:

```text
workload_id
case_id
workload_group_id
pseudopotential_family
qe_tolerance_schema_id
accounting_boundary_id
trace_ref
dump_ref
correctness_anchor_ref
```

Interpretation rules:

- `candidate_family` is architecture identity.
- `runtime_projection_family` is evaluator/projection metadata.
- `implementation_target_class` may be `fpga_style`, `asic_style`, `cim_style`, `non_cim_style`, `mixed`, `custom`, or `unknown`; it does not by itself imply executor support.
- `backend_profile_id` identifies the planned SystemC profile, not a public claim tier.

## 5. Dry-run defaults

For Stage A dry-run rows, the default object is:

```json
{
  "schema_version": "qe_dse_systemc_feedback_contract_v0",
  "status": "planned_not_executed",
  "execution_status": "not_executed",
  "backend_class": "systemc_timed_functional_proxy",
  "candidate_config_ref": "systemc_configs/{candidate_id}.json",
  "metrics_ref": null,
  "metrics_expected_keys": [
    "time_proxy_s",
    "energy_proxy_j",
    "cycle_proxy",
    "resident_reuse_ratio",
    "spill_count",
    "fallback_count",
    "diag_policy",
    "offload_scope"
  ],
  "calibration_join_keys": [
    "workload_id",
    "case_id",
    "candidate_id",
    "candidate_family",
    "architecture_template_id",
    "assumption_set_id"
  ],
  "calibration_status": "not_applicable_for_dry_run",
  "claim_ceiling": "timed_functional_proxy_contract_only",
  "subprocess_invoked": false
}
```

Allowed dry-run aliases are deliberately narrow:

- `calibration_status: missing` may be used when a row records an intended calibration join but no calibration artifact exists yet.
- `metrics_ref: null` is required unless an explicit opt-in SystemC run writes a metrics artifact.
- `claim_ceiling` must not exceed `timed_functional_proxy_contract_only` in Stage A.

## 6. Metrics output keys for future opt-in runs

If a future task enables explicit SystemC execution, the metrics artifact referenced by `metrics_ref` should use stable keys so DSE rows can be compared without changing schema names:

| Key | Meaning | Stage A interpretation |
| --- | --- | --- |
| `time_proxy_s` | Timed-functional/proxy time estimate. | Proxy evidence only. |
| `energy_proxy_j` | Proxy energy estimate when available. | Proxy evidence only; not board-measured. |
| `cycle_proxy` | Simulator/proxy cycle-like count when available. | Not cycle-accurate unless a later contract upgrades it. |
| `resident_reuse_ratio` | Reuse proxy for resident context behavior. | Screening signal only. |
| `spill_count` | Proxy spill/fallback pressure count. | Screening signal only. |
| `fallback_count` | Count or estimate of fallback events. | Screening signal only. |
| `diag_policy` | Diagonalization path used by the candidate/profile. | Identity/explanation field. |
| `offload_scope` | Offload scope used by the candidate/profile. | Identity/explanation field. |

## 7. Calibration join semantics

`calibration_join_keys` exists to stop accidental cross-case or cross-family comparison drift. A feedback record is not comparable unless the consuming row can match the relevant workload and candidate identity keys.

Required join discipline:

1. If `workload_id`, `case_id`, `candidate_id`, or `candidate_family` is missing, the row remains explain-only.
2. If `runtime_projection_family` differs from `candidate_family`, the row must preserve both fields.
3. If `assumption_set_id` is missing, the row may still be serialized, but confidence cannot be upgraded by this contract alone.
4. Calibration metadata can lower confidence; it cannot promote a Stage A row into final public authority.

## 8. Advisor-facing alignment

This contract feeds advisor-facing docs rather than replacing them:

- `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` fixes the family comparison contract: same input case, pseudopotential, convergence threshold, outer SCF accounting boundary, and QE gold correctness gate.
- `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md` fixes report fields such as `Recommended family`, `Recommendation type`, `correctness_status`, `confidence`, `speedup_to_convergence_range`, `energy_to_convergence_range`, and `algorithm_contract_deviation`.

A SystemC feedback row may support those report fields only as pre-adjudication evidence. It must not independently fill a public winner.

## 9. Non-claim wording for reports

Use wording like:

```text
SystemC feedback is planned or proxy-grade. The row is suitable for Stage A screening and adjudicator intake, not for a final public family recommendation.
```

Do not use wording like:

```text
The SystemC run proves cycle-accurate speedup.
The candidate is board-ready.
The CIM backend wins.
```

## 10. Readiness checks

A Stage A documentation or manifest review should confirm:

- `systemc_feedback_contract.status = planned_not_executed` for dry-run rows;
- `execution_status = not_executed` and `subprocess_invoked = false` for dry-run rows;
- `claim_ceiling = timed_functional_proxy_contract_only`;
- candidate identity remains backend-neutral and does not encode CIM-only assumptions;
- `final_public_family_winner` remains `null` in Stage A bundles.
