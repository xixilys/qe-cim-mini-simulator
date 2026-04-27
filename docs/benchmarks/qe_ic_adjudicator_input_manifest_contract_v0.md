# QE IC adjudicator input manifest contract v0

## 1. Purpose

This contract freezes the **adjudicator intake manifest** for the QE IC high-fidelity adjudicator before runner logic or memo-schema logic is implemented.

It defines four things:

1. the exact upstream evidence surfaces that must exist before adjudication;
2. the normalized adjudicator identity tuple, in explicit field order;
3. the comparison cohorts the adjudicator must evaluate, and which one actually drives recommendation authority;
4. the hard-block semantics for missing or drifted join-key tuples.

This document is intentionally about intake identity, cohort authority, and comparison eligibility. It does not define the later scoring formula, memo rendering, or claim text.

## 2. Relationship to existing contracts

This contract tightens and extends the intake wording already frozen in:

- `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
- `docs/benchmarks/qe_ic_simulator_calibration_contract_v0.md`
- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`

The adjudicator input manifest is a **group × family × policy × contract identity surface**, not a per-execution trace identity.

That scope choice is deliberate because the adjudicator is the single authority surface for workload-group decisions, not a replacement for workload-local or run-local provenance.

## 3. Frozen adjudicator inputs

### 3.1 Required manifest surfaces

Every adjudicator input manifest must point to all of the following surfaces:

1. one exact-match **DSE subject row** from `results[]` in `systemc_architecture_family_dse_result_schema_v0.json`;
2. the matching **`family_summary` context** for the same normalized `family`;
3. **`gpu_annex_summary`** as GPU evidence input;
4. **`phase1_evidence_closure`** as closure-gate input;
5. the current **stage-main recommendation-like package(s)** as pre-adjudication evidence only.

No later runner may treat any one of these surfaces as optional by default.

### 3.2 Surface roles

The surfaces above are frozen with the following roles:

- **DSE subject row** — the exact design-point row being adjudicated.
- **`family_summary` context** — canonical family-profile context only; not recommendation authority.
- **`gpu_annex_summary`** — GPU evidence annex and fairness/claim-limit context.
- **`phase1_evidence_closure`** — closure-gate and admissibility context.
- **stage-main recommendation-like packages** — explain-only evidence of what the current phase stack would have said before adjudicator authority was frozen.

### 3.3 Secondary provenance is required but non-authoritative

The following fields remain important provenance, but they are **not part of the adjudicator identity tuple** in v0:

- `workload_id`
- `request_id`
- `scf_iteration`
- `episode_id`
- `algorithm_contract_deviation`

They may still appear in upstream artifacts and later memo appendices. The adjudicator must not use them to replace, weaken, or partially reconstruct the frozen identity tuple below.

## 4. Normalized adjudicator identity tuple

### 4.1 Exact field order

The adjudicator input identity tuple is frozen in this exact order:

1. `workload_group_id`
2. `family`
3. `diag_policy`
4. `offload_scope`
5. `resident_policy`
6. `partition_strategy`
7. `assumption_set_id`
8. `qe_tolerance_schema_id`
9. `accounting_boundary_id`
10. `fairness_policy_id`
11. `power_boundary_id`
12. `observability_contract_id`
13. `algorithm_rewrite_manifest_id`

This tuple is the **only** adjudicator input key allowed to determine comparison eligibility across DSE rows and closure artifacts in v0.

### 4.2 Scope rule

The tuple above is a **normalized adjudicator identity**, not a unique run identifier.

This means:

- it freezes the group/family/policy/contract identity of the adjudicated subject;
- it intentionally does not distinguish per-case or per-iteration provenance;
- it must never be inferred from a partial subset of fields.

### 4.3 Family alias normalization rule

The normalized field name is `family`.

If an upstream surface uses `architecture_family`, the adjudicator may only consume it after a lossless normalization step:

- `architecture_family -> family`

If that alias is absent when needed, the status is `join_key_missing`.

If the alias is present but resolves to a different normalized `family` than the DSE subject row, the status is `join_key_drift`.

### 4.4 Exact-match rule

For the DSE subject row and every required closure artifact, all 13 identity fields above must match **exactly** after normalization.

The adjudicator must not:

- infer `partition_strategy` from family defaults;
- infer `assumption_set_id` from projection prose;
- infer fairness/power/observability ids from document names alone;
- accept a family-level match while policy-level or contract-level fields drift.

### 4.5 `family_summary` binding rule

`family_summary` is the one required input surface that is allowed to bind by normalized `family` only.

It is therefore **advisory context**, not a direct closure-artifact join source.

The canonical family profile used by the adjudicator must be resolved through the exact-match DSE row set for that same normalized `family`, not by treating `family_summary` itself as a complete join-key carrier.

## 5. Frozen comparison cohort rule

### 5.1 Compared cohorts

The adjudicator must evaluate all three of the following cohorts for each normalized `family`:

1. **`canonical_family_profile`** — the DSE row whose design point matches the `family_summary` canonical profile for that family.
2. **`trusted_point_per_family`** — the best family-local row that survives adjudicator hard blocks and remains eligible after the required closure gates are applied.
3. **`best_performance_point`** — the raw best-performance row for that family after exact-match join checks, even if it does not survive the trust/closure gates.

### 5.2 Authority cohort

The single recommendation-authority cohort is frozen as:

- **`trusted_point_per_family`**

The other two cohorts are required comparison views, but they are not allowed to issue recommendation authority.

### 5.3 Roles of the non-authoritative cohorts

- **`canonical_family_profile`** is explain-only context that shows whether the family's frozen canonical profile agrees with the final authority outcome.
- **`best_performance_point`** is an upside-probe context that shows whether a faster but less trusted point exists inside the family.

Neither cohort may silently override the authority cohort.

### 5.4 Divergence surfacing rule

If the authority cohort differs from either non-authoritative cohort, the adjudicator must surface that explicitly:

- `authority_vs_canonical_divergence`
- `authority_vs_best_performance_divergence`

The adjudicator must not collapse those disagreements into a single unlabeled score or hide them inside prose.

### 5.5 No-authority fallback rule

If no `trusted_point_per_family` survives for a given family, that family is recommendation-ineligible.

If no family has a surviving `trusted_point_per_family`, the adjudicator must return:

- no public family recommendation
- an explicit blocked/no-decision posture

## 6. Hard-block semantics

### 6.1 `join_key_missing`

`join_key_missing` is raised when any required identity field is absent from the DSE subject row or any required closure artifact after normalization rules are applied.

Examples:

- `partition_strategy` is missing from a closure artifact;
- `observability_contract_id` is absent from a GPU annex package;
- the artifact exposes only `architecture_family`, but alias normalization cannot be completed into `family`.

`join_key_missing` is a **hard block**.

### 6.2 `join_key_drift`

`join_key_drift` is raised when all required identity fields are present, but one or more normalized values differ across the DSE subject row and required closure artifacts.

Examples:

- DSE subject row says `resident_policy = fit_first`, but closure evidence says `spill_tolerant`;
- DSE subject row says `family = F1`, while normalized closure evidence says `family = F2`;
- DSE subject row and closure evidence disagree on `fairness_policy_id`, `power_boundary_id`, or `algorithm_rewrite_manifest_id`.

`join_key_drift` is a **hard block**.

### 6.3 Hard-block action

For both `join_key_missing` and `join_key_drift`, the adjudicator must do all of the following before any scoring or recommendation logic:

1. mark the affected DSE subject row / closure bundle as **comparison-ineligible**;
2. remove the affected row from `trusted_point_per_family` authority consideration;
3. refuse to upgrade the affected family into a public recommendation;
4. if the hard block removes all families from authority consideration, return no recommendation at manifest level.

There is no v0 soft-warning path for missing or drifted identity tuples.

## 7. Machine-readable schema binding

The machine-readable shape corresponding to this contract is:

- `docs/benchmarks/qe_ic_adjudicator_input_manifest_schema_v0.json`

Later runner work may extend the manifest with more evidence metadata, but it may not:

- change the normalized identity tuple without a schema revision;
- change the authority cohort without a contract revision;
- downgrade `join_key_missing` or `join_key_drift` from hard-block status.

## 8. Verification checklist

This contract is correct if a reader can answer all of the following without guessing:

1. What exact surfaces must the adjudicator intake manifest reference?
2. What exact 13-field tuple determines comparison eligibility?
3. Which cohort actually drives recommendation authority? `trusted_point_per_family`.
4. What are `canonical_family_profile` and `best_performance_point` used for? Divergence surfacing only.
5. What happens if an identity field is missing? `join_key_missing`, hard block.
6. What happens if an identity field drifts after normalization? `join_key_drift`, hard block.
