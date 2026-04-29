# Frontend DSE Contracts Review Report

Date: 2026-04-28
Package: `/mnt/data/dft_accelerate_frontend_dse_contracts_review_package_20260428T0858Z.zip`

## Verdict

The frontend package is functional for its stated v0 review scope: evidence-only Stage-A enumeration, Stage-B0 descriptor/request emission, fast-model screening, and explicit SystemC execution guard.

It is **not yet fully normal for a general-purpose soft/hardware DSE frontend**. The main blockers are contract hardening issues around generic workload handling, axis validation, backend feedback validation, shortlist diversity, and Stage-B0 validation consistency.

## Tests executed

### Official review script

Command:

```bash
cd /mnt/data/frontend_review_run/dft_accelerate_frontend_dse_contracts_review_package
./RUN_FRONTEND_DSE_REVIEW.sh /mnt/data/frontend_review_script_run
```

Observed:

```text
Ran 37 tests in 0.273s
OK
compileall=ok
stub_results=3
stub_stage_b0_descriptors=3
stub_backend_request_schema=backend_execution_request_v0
fast_results=4
fast_shortlisted=2
fast_claim_ceiling=fast_model_screening_only
execute_systemc_guard=ok
review_status=PASS
```

### Full 540-point Stage-A/Stage-B0 run

Command used the canonical design-space, minimal workload, dry-run, `--max-design-points 540`, `--emit-stage-b0-descriptors`, and `--emit-full-stage-status`.

Observed:

```text
result_count=540
promotion={'explain-only': 540, 'promotion-eligible': 0, 'reject': 0}
validity={'projection_only': 270, 'valid_executable': 180, 'invalid': 90}
descriptor_count=180
blocked_descriptor_count=360
stage_a_dse_core=complete
stage_b0_descriptor_handoff=generated_not_executed
stage_b1_b2_systemc_feedback=blocked_waiting_systemc_feedback_artifact
stage_b3_gem5_systemc_smoke=blocked_waiting_gem5_systemc_smoke_report
stage_c_qe_equivalent_scf=blocked_waiting_qe_equivalent_correctness_report
stage_d_fpga_asic_implementation=blocked_waiting_fpga_asic_implementation_evidence
```

Interpretation: the 540-point bounded enumeration works; only F1/F2/F3 non-aggressive designs emit descriptors, while projection-only F4/F5/custom and aggressive-device points without diag-engine capability are blocked.

### Full 540-point fast-model screening run

Observed:

```text
result_count=540
promotion={'explain-only': 360, 'promotion-eligible': 180, 'reject': 0}
ranking_claim_ceiling={'fast_model_screening_only': 540}
shortlisted=10
validity={'projection_only': 270, 'valid_executable': 180, 'invalid': 90}
descriptor_count=180
```

Interpretation: fast screening and claim ceiling behavior are working, but the shortlist policy does not actually diversify across families under the current implementation.

## Strengths

1. Evidence-only posture is consistently represented in outputs.
2. `--execute-systemc` is correctly rejected by the frontend CLI.
3. Stage-B0 descriptor, gem5 handoff, and backend execution request sidecars are emitted without execution claims.
4. Projection-only families F4/F5/custom are blocked from backend descriptor emission.
5. Stage status artifact correctly marks downstream stages as blocked when external evidence is absent.
6. Tests cover the basic CLI, interfaces, fast model, SystemC dry-run guard, implementation stub, ranking semantics, and contract fields.

## Issues found

### P0-1: Generic workloads are incorrectly given QE domain extension

A generic workload such as:

```json
{
  "schema_version": "generic_trace_workload_v0",
  "workload_id": "generic_spmv_small",
  "domain": "sparse_linear_algebra",
  "app_adapter": "generic_trace",
  "dimension_n": 64,
  "dimension_m": 4
}
```

runs successfully, but its row contains:

```json
"domain_extension": {
  "qe": {
    "case_id": "generic_spmv_small",
    "qe_tolerance_schema_id": "not_applicable",
    "pseudopotential_family": "not_applicable",
    "solver_path_class": "not_applicable",
    "projector_pressure": "not_applicable",
    "nonlocal_pressure": "not_applicable",
    "qe_equivalent_scf_claim": false
  }
}
```

Cause: `WorkloadDescriptor.from_dict()` injects QE-like fields with `not_applicable` defaults, then `domain_contracts._is_qe_payload()` detects the *presence* of these keys rather than meaningful QE identity.

Impact: this directly conflicts with the goal of a more universal DSE frontend.

Recommended fix:

- Add explicit `domain` and `app_adapter` to the core workload descriptor.
- Treat QE fields as a `domain_extension.qe`, not as universal core fields.
- Change `_is_qe_payload()` to require `app_adapter == "qe"`, `domain in {"dft", "qe"}`, or non-`not_applicable` QE identifiers.
- Add CLI-level tests proving generic workloads do not emit `domain_extension.qe` or `qe_anchor_refs` unless explicitly requested as compatibility aliases.

### P0-2: Non-family design axes are not validated

`architecture_space.make_design_point()` only validates `family`; `constraints.DesignPointValidator` also only validates family plus one aggressive-device rule.

A design point with `diag_policy="nonsense"` is accepted as `valid_executable`.

Impact: external candidates, future BO candidates, or hand-edited descriptors can bypass the declared design-space contract.

Recommended fix:

- Pass `DesignSpaceSpec` or allowed axis values into `DesignPointValidator`.
- Validate all identity axes: `family`, `diag_policy`, `offload_scope`, `resident_policy`, `partition_strategy`.
- Add tests for invalid values on every axis.

### P0-3: SystemC feedback artifact validation is too weak

`load_systemc_feedback_artifact()` only validates `schema_version` and that `rows` is a list. A malformed feedback artifact with `source_kind="board_measured_overclaim"` was accepted; the row was updated to that source kind and `result_status="executed"` while the manifest still passed Stage-A gates.

Impact: external backend feedback can smuggle misleading source kinds or claim semantics into frontend outputs.

Recommended fix:

- Validate top-level fields: `execution_status`, `source_kind`, `claim_ceiling`, `backend_class`, `report_schema_version`.
- Restrict feedback `source_kind` to a closed set such as `timed_functional_proxy` or `trace_calibrated_proxy`.
- Require each row to contain `candidate_id`, `metrics`, `claim_ceiling`, and maybe `correctness_gate`.
- Reject feedback that exceeds the frontend-ingest claim ceiling.
- Add a negative test for overclaiming feedback.

### P1-1: `top_fast_uncertain_diverse` shortlist policy is not diverse

In a 540-point fast screening run with shortlist size 10, all 10 shortlisted candidates were F3. The code currently selects every ranked candidate until the limit because the condition is:

```python
if family not in selected_families or len(selected_indexes) < shortlist_size:
```

The second clause is true until the list is full, so family diversity is not enforced.

Recommended fix:

- Implement two-pass selection: first one per family, then fill remaining by rank.
- Add tests with multiple families where top-ranked rows are dominated by one family.

### P1-2: Stage-B0 descriptor validation is inconsistent with Stage-A row validation

Stage-A evaluation uses `backend_capability={"target_resource_model": True}`. Stage-B0 descriptor emission recomputes validation without this capability, which adds `target_resource_model` to `missing_evidence` inside emitted descriptor configs.

Observed: the same candidate row had `missing_evidence=['resident_capacity_evidence']`, while its Stage-B0 config had `['resident_capacity_evidence', 'target_resource_model']`.

Impact: downstream backend/adjudicator may see different validation for the same candidate.

Recommended fix:

- Reuse row-level `design_validation` when emitting Stage-B0, or carry explicit backend capabilities into `emit_stage_b0_descriptors()`.
- Add a test asserting row validation and descriptor validation are identical unless intentionally revalidated with a recorded capability profile.

### P1-3: Stage-B0 descriptors are structurally valid but semantically thin

`backend_execution_request.systemc_config.cluster_graph`, `resident_object_map`, and `dma_plan` are currently empty placeholders. That is acceptable for v0 descriptor smoke, but not sufficient for a real backend service.

Recommended fix:

- Make empty fields explicit as `unresolved` or `not_populated_in_stage_a_v0`.
- For the next milestone, populate at least a minimal cluster graph, object residency map, DMA plan, and host control event sequence.

### P2-1: Prefix-biased bounded Cartesian enumeration

With a small `--max-design-points`, `bounded_cartesian_product()` returns a prefix of the Cartesian product, not a representative subset. This is okay for smoke tests but risky for DSE screening defaults.

Recommended fix:

- Rename current backend to `bounded_cartesian_prefix`, or
- Add `stratified_cartesian` / `latin_hypercube` / `round_robin_by_family` backend for smoke-scale but less biased sampling.

### P2-2: CLI source-kind choices are broader than accepted execution path

The parser lists `timed_functional_proxy`, `trace_calibrated_proxy`, and `mixed`, but `main()` rejects anything except `stub` or `fast_model_screening`.

Recommended fix:

- Either remove those choices from the frontend-only CLI, or
- Split CLI modes clearly: `frontend-screen` vs `feedback-ingest`.

## Recommended next tasks

### Immediate hardening

1. Fix generic workload domain detection.
2. Validate all design axes.
3. Harden SystemC feedback schema validation.
4. Fix shortlist diversity semantics.
5. Keep Stage-A and Stage-B0 validation consistent.

### Next development milestone

1. Define a backend-neutral `ApplicationGraphIR` and `ArchitectureTemplateIR` path that is not QE-specific.
2. Convert QE fields into a QE adapter/domain extension.
3. Populate Stage-B0 `cluster_graph`, `resident_object_map`, `dma_plan`, and `software_runtime.control_policy` from the candidate descriptor.
4. Add a golden end-to-end generic workload test and a QE workload test.
5. Add negative tests for claim overreach and malformed feedback.

## Final assessment

The frontend package passes its own review flow and works for QE-oriented v0 evidence-only exploration. It is ready to be merged as a **Stage-A/B0 contract prototype** if the claim boundary stays exactly as documented.

It should not yet be treated as fully normal for a general DSE frontend. The P0 issues above should be fixed before using it as the foundation for broader, non-QE soft/hardware co-design workloads.
