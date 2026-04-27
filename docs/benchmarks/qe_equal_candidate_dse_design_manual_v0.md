# QE Equal-Candidate DSE Design Manual v0

## Purpose

This manual defines the equal-candidate DSE model for the QE band-solver architecture exploration flow. It separates architecture identity from evaluator support so every architecture family (`F1`, `F2`, `F3`, `F4`, `F5`, `custom`) can participate as a first-class candidate without being demoted because a particular simulator backend is incomplete.

The manual is Stage-A scoped. It explains evidence generation and readiness accounting; it does not authorize final architecture decisions, CPU/GPU/FPGA performance claims, board-grounded power claims, or thesis-grade conclusions.

## Core rule

Architecture identity is not evaluator support.

An `F4` candidate remains an `F4` candidate even if the current SystemC runner can only evaluate it through an `F2`-compatible projection backend. The runtime projection is evidence metadata, not a replacement identity.

## Terminology

| Term | Meaning | Mutability |
| --- | --- | --- |
| `candidate_family` | The architecture family being explored: `F1`, `F2`, `F3`, `F4`, `F5`, or `custom`. | Immutable candidate identity. |
| `architecture_template_id` | Template source for a candidate row. | Immutable artifact identity. |
| `template_family` | Legacy/current template family field. | Preserved for compatibility. |
| `design_point.family` | Legacy runtime-family axis used by existing runner paths. | Compatibility field; not authoritative candidate identity after migration. |
| `runtime_projection_family` | Runtime/profile family used by an evaluator backend. | Evaluator metadata. |
| `evaluator_backend` | Backend that produced or would produce evidence, e.g. `systemc_timed_functional`, `analytical_stub`, or `gem5_systemc_cosim_stub`. | Evidence metadata. |
| `fidelity_class` | Evidence tier such as `stub`, `projection_only`, `timed_functional_proxy`, `trace_calibrated_proxy`, `correctness_capable`, or `measured`. | Evidence metadata. |
| `support_status` | Whether the backend is native, projected, projection-only, reserved, or unsupported. | Evidence metadata. |
| `executor_claim_allowed` | Whether this row may claim that a supported executor/proxy path was used. | Narrow executor-path metadata; never public/final claim permission. |

## Current support matrix

| Candidate family | Candidate status | Current evaluator support | Claim boundary |
| --- | --- | --- | --- |
| `F1` | Equal candidate | Runtime/profile-backed by current runner paths where metrics exist. | Stage-A evidence only. |
| `F2` | Equal candidate | Canonical balanced 4-cluster runtime/profile-backed path. | Stage-A evidence only. |
| `F3` | Equal candidate | Device-heavy runtime/profile-backed path where current runner supports it. | Stage-A evidence only. |
| `F4` | Equal candidate | Projection/scaffold unless future fused/hybrid executor evidence exists. | No native executor claim. |
| `F5` | Equal candidate | Projection/scaffold unless future unified fabric/CGRA executor evidence exists. | No native executor claim. |
| `custom` | Equal candidate | Projection/scaffold unless future PIM/resident/NoC executor evidence exists. | No native executor claim. |
| `gem5_systemc_cosim` | Evaluator backend, not family | Reserved/stub in this phase. | No cosim result claim. |

`F1`, `F2`, and `F3` being runtime-backed families does not itself prove that every row has native support. Native support must be tied to an executable run artifact or another explicit evidence path.

## Candidate identity model

A candidate row should preserve:

```json
{
  "candidate_family": "F4",
  "architecture_template_id": "f4_cim_dsp_hbm_hybrid_v1",
  "candidate_id": "0007__f4_cim_dsp_hbm_hybrid_v1__si4_pbe_uspp_small",
  "design_axes": {
    "diag_policy": "device_first_fallback",
    "offload_scope": "device_heavy",
    "resident_policy": "spill_tolerant",
    "partition_strategy": "operator__build__diag__refresh"
  }
}
```

This identity stays stable across evaluator backends. If a backend needs to map the candidate into a supported runtime family, that mapping appears only in evaluator metadata.

## Evaluator metadata model

An evaluator record should add:

```json
{
  "runtime_projection_family": "F2",
  "evaluator_backend": "systemc_timed_functional",
  "fidelity_class": "projection_only",
  "support_status": "projection_only",
  "support_evidence": {
    "executor_claim_allowed": false,
    "native_runtime_evidence_path": null,
    "projection_reason": "F4 hybrid semantics projected through the current F2-compatible SystemC path.",
    "future_backend_note": "Native F4 fused/hybrid executor is future work.",
    "claim_boundary": "Stage-A evidence only; not a completed executor claim."
  }
}
```

## Multi-fidelity DSE loop

## Valid evidence tuples

The schema must be interpreted as cross-field tuples. Independent enum validation is not enough.

| Condition | Required tuple | Interpretation |
| --- | --- | --- |
| gem5/SystemC reserved backend | `evaluator_backend = gem5_systemc_cosim_stub`, `fidelity_class = reserved`, `support_status = stub_reserved`, `executor_claim_allowed = false` | Future backend placeholder only. |
| Projection-only candidate | `support_status = projection_only`, `fidelity_class = projection_only`, `executor_claim_allowed = false`, non-empty `projection_reason` | Candidate is equal, but no executor/proxy claim is allowed. |
| Projected runtime support | `support_status = projected_runtime_supported`, concrete `runtime_projection_family`, `executor_claim_allowed = true`, non-empty projection/compatibility reason | An executable proxy path exists, but candidate semantics are mapped. |
| Native runtime support | `support_status = native_runtime_supported`, non-empty `native_runtime_evidence_path` or current-run artifact reference | A supported native path was used for this row. |
| Measured evidence | `fidelity_class = measured`, concrete measured artifact path | Not emitted in this phase unless real measurement evidence exists. |

`executor_claim_allowed` means only that the row may claim use of a supported executor or proxy path. It does not authorize final architecture selection, public performance statements, CPU/GPU/FPGA comparisons, or board-power claims.

`projected_runtime_supported` and `projection_only` are intentionally conservative but distinct. Use `projected_runtime_supported` only when an executable proxy path actually ran. Use `projection_only` when evidence is scaffold, analytical, or non-executed projection metadata.

## Multi-fidelity DSE loop

The intended search loop is:

1. Generate equal architecture candidates.
2. Apply workload, resource, power, correctness, and policy constraints.
3. Run cheap proxy or projection evaluator.
4. Store metrics, failures, uncertainty, and artifacts.
5. Promote promising or uncertain candidates to higher fidelity where support exists.
6. Run SystemC, gem5, gem5/SystemC co-sim, or measured backends only when explicitly available.
7. Rank only within comparable workload, constraint, evaluator, and fidelity groups. Cross-fidelity comparisons may nominate follow-up runs, but must not produce winner claims.
8. Send evidence bundles to adjudicator; do not self-authorize final claims.

## gem5/SystemC feedback boundary

SystemC should model accelerator datapath, cluster scheduling, buffering, DMA-side effects, and device timing proxies.

gem5 should model host/runtime control, CPU/memory hierarchy, checkpointing, host-device interaction, and system-level statistics.

gem5/SystemC co-simulation is a future evaluator backend in this repository state. Until executable evidence exists, it must be represented as `evaluator_backend = gem5_systemc_cosim_stub`, `fidelity_class = reserved`, and `support_status = stub_reserved`.

## Ranking rules

Allowed:

- candidate coverage
- support coverage
- projection-only accounting
- missing metric accounting
- same-fidelity ranking
- promotion nominations
- adjudicator evidence packaging

Forbidden in Stage A:

- public best-family selection
- native executor claims for `F4`, `F5`, or `custom` without evidence
- `CPU + FPGA beats CPU + GPU` claims
- board-grounded power claims
- treating reserved gem5/SystemC co-sim metadata as measured evidence
- treating `executor_claim_allowed = true` as final claim permission
- aggregating unlike `custom` templates into a single comparable result without preserving template/candidate/design-axis identity

## Backward compatibility

During migration, legacy fields remain:

- `design_point.family`
- `template_family`
- `architecture_template_id`
- `candidate_id`
- `source_kind`

New consumers should prefer:

- `candidate_family` for architecture identity
- `runtime_projection_family` for evaluator/runtime mapping
- `evaluator_backend`, `fidelity_class`, and `support_status` for evidence quality

CSV and other flattened outputs must expose the evidence boundary directly. At minimum, flattened rows should include `executor_claim_allowed`, `native_runtime_evidence_path`, `projection_reason`, `future_backend_note`, and `claim_boundary`.

## Acceptance criteria

The framework is correct when:

1. All six family identities can appear in candidate coverage.
2. Projection-only support never mutates `candidate_family`.
3. Runtime projection is reported separately.
4. Existing legacy result consumers remain compatible.
5. Invalid evidence tuples are rejected or explicitly flagged before adjudication.
6. Stage-A claim limits remain enforced.
7. Tests demonstrate that `F4`, `F5`, and `custom` can be equal candidates without native runtime claims.
8. `custom` summaries preserve template, candidate, and design-axis identity.
