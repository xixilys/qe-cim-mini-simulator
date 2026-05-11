# QE IC adjudicator authority contract v0

## 1. Purpose

This contract freezes the authority boundary for the high-fidelity adjudicator layer in the current QE IC benchmark stack.

It defines four things:

1. the adjudicator is the single public decision authority for this stack;
2. the insertion seam is fixed against the current repo pipeline;
3. existing DSE, projection, GPU, and phase recommendation-like outputs are demoted to evidence inputs only;
4. the adjudicator outputs are the only surfaces allowed to carry a public family decision, release decision, or claim-permission decision.

This document is intentionally about authority and handoff first, plus the frozen policy layer that stops present-day proxy evidence from being overstated. It does not define adjudicator scoring or ranking math.

The frozen intake-manifest semantics now live alongside this contract in:

- `docs/benchmarks/qe_ic_adjudicator_input_manifest_contract_v0.md`
- `docs/benchmarks/qe_ic_adjudicator_input_manifest_schema_v0.json`

## 2. Normative authority rule

### 2.1 Single public decision authority

The adjudicator becomes the single public decision authority for the QE IC DSE and phase-closure stack.

After this contract, no upstream producer may present its own result as the stack's public recommendation, public best family, release-ready family, or final claim-bearing decision.

Upstream layers may still rank, shortlist, summarize, aggregate, or explain. Those outputs remain useful, but they are evidence for the adjudicator, not public authority.

### 2.2 What this contract does not claim

This contract does not upgrade current model fidelity.

The runnable model truth in this repository remains timed-functional to roughly L1.5 to L2. Frontdoor graph projection, proxy energy, calibrated narrowing artifacts, and partial closure summaries can support evidence-tier reasoning, but they do not by themselves become board-grounded or thesis-grade authority.

## 3. Frozen insertion seam in the current pipeline

### 3.1 Actual pipeline seam

The adjudicator insertion point is frozen at the current seam that already exists in `tools/benchmarks/run_qe_next_stage_dse_phase.py`:

1. the DSE runner produces result bundles in `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`;
2. the phase runner imports those bundles and materializes `bundle["family_summary"]`;
3. the phase runner then builds additional evidence surfaces such as GPU annex summaries, accurate-layer validation summaries, projection review packages, and phase-1 closure summaries;
4. the adjudicator must run after the DSE bundle and its evidence-input bundle are available, and before or alongside final phase and evidence closure aggregation that would otherwise expose a release-facing recommendation.

In short, the seam is:

`post-DSE bundle generation -> adjudicator intake -> phase/evidence closure aggregation with adjudicator authority attached`

### 3.2 Practical reading of the seam

For this repo version, "post-DSE bundle generation" means the adjudicator consumes the normalized outputs that exist after the family sweep and phase runner have assembled machine-readable evidence surfaces.

For this repo version, "before or alongside phase/evidence closure aggregation" means the adjudicator must be the layer that decides what final family decision, release posture, and claim permission may be shown once `phase1_evidence_closure` and related closure packages are in view.

The adjudicator must not be inserted before the DSE bundle exists, and it must not be left after a separate stage-main or public recommendation surface has already become the outward decision authority.

## 4. Evidence-input surfaces only, not authority surfaces

The following existing outputs are frozen as evidence inputs only.

They may inform the adjudicator. They may not act as the stack's public decision authority.

### 4.1 DSE sweep evidence inputs

From `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`:

- `family_summary`
- row-level `projection`
- row-level `projection.confidence`
- row-level `projection.ranking_grade_ready`
- row-level `projection.projection_grade_ready`

These fields remain DSE evidence and projection evidence. They do not authorize a public family decision on their own.

### 4.2 GPU evidence inputs

From `tools/benchmarks/run_qe_next_stage_dse_phase.py`:

- `gpu_annex_summary`

This surface remains a GPU evidence annex only. It may constrain claim permission and fairness posture, but it does not independently decide the final public recommendation.

### 4.3 Phase closure evidence inputs

From `tools/benchmarks/run_qe_next_stage_dse_phase.py`:

- `phase1_evidence_closure`
- `phase1_evidence_closure_summary`

These remain closure evidence and lane-status evidence. They may block, narrow, or qualify adjudicator outputs, but they are not themselves the public decision surface.

### 4.4 Existing recommendation-like phase outputs, demoted to evidence only

The following fields and packages remain visible as internal or explain-only evidence, but are no longer authoritative:

- `stage_main_recommendation_status`
- `public_recommended_family`
- `public_recommendation_type`
- `projection_review`
- `stage_main_recommendation_json`
- `stage_main_recommendation_md`
- `qe_next_stage_stage_main_recommendation_v0`
- `qe_next_stage_projection_review_v0`
- `qe_next_stage_artifact_bundle_manifest_v0`
- `qe_next_stage_advisor_pack_summary_v0`

If these surfaces still use recommendation language for backward compatibility, that wording must be interpreted as pre-adjudication evidence packaging, not final authority.

## 5. Authoritative adjudicator outputs

Only adjudicator outputs may carry the following authority roles:

### 5.1 Public family decision

The adjudicator alone may name the public family decision for the current stack view, including:

- whether a family is selected;
- whether no family may yet be selected;
- whether trusted-family and performance-family divergence forces a no-decision or conditional decision state.

### 5.2 Release posture decision

The adjudicator alone may decide whether the current evidence posture is:

- not ready for a public recommendation;
- ready for a bounded projection-grade public memo;
- blocked from stronger claims because GPU, board, fairness, or closure evidence remains incomplete.

### 5.3 Claim permission decision

The adjudicator alone may decide which claim tier is unlocked by the current evidence bundle.

This includes deciding whether the stack is limited to projection-grade reasoning, whether it may describe only evidence-tier tradeoffs, or whether a stronger claim remains disallowed because current closure is still below board-validated or thesis-grade confidence.

## 6. Intake contract for the adjudicator

### 6.1 Required evidence intake

At minimum, the adjudicator intake bundle must treat the following as upstream evidence inputs:

- DSE result rows and `family_summary`
- row-level `projection`
- `gpu_annex_summary`
- `phase1_evidence_closure`
- stage-main recommendation-like packages, only as evidence of what the current phase runner would have said before adjudicator authority was frozen

The exact intake-manifest shape, normalized identity tuple, authority-driving cohort, and hard-block semantics for missing/drifted join keys are frozen by:

- `docs/benchmarks/qe_ic_adjudicator_input_manifest_contract_v0.md`
- `docs/benchmarks/qe_ic_adjudicator_input_manifest_schema_v0.json`

Later runner work may add more evidence metadata, but it may not infer the adjudicator identity or authority cohort from partial fields.

### 6.2 Evidence discipline

The adjudicator must preserve the distinction between:

- evidence tier,
- confidence or maturity,
- claim permission,
- final public decision.

Those may correlate, but they must not collapse into one score or one status field by default.

The canonical machine-readable claim-permission surface is the per-claim matrix, not any convenience summary list.

If top-level `allowed` / `guarded` / `forbidden` projections are emitted for readability, they must be derived from the same per-claim permission records rather than authored independently.

For v0, those terms are frozen as follows:

- **`evidence_tier`** — the strongest admissible evidence surface presently supporting or limiting a claim.
- **`confidence`** — how closed, stable, and contradiction-resolved the current evidence bundle is after workload admissibility, gate state, and precedence are applied.
- **`claim_permission`** — whether a claim is `allowed`, `guarded`, or `forbidden` for public use after stage activation, evidence ceilings, blockers, confidence, and contradiction precedence are applied.
- **final public decision** — the outward adjudicator recommendation and release posture after all claim-permission rules are projected into one memo-level decision.

These axes are intentionally separate.

A stronger `evidence_tier` does not automatically imply higher `confidence`, and neither one automatically unlocks stronger `claim_permission`.

Row-level `source_kind` remains provenance only. It must never, by itself, act as final adjudication authority.

### 6.3 Honest fidelity boundary

The adjudicator must preserve current wave boundaries honestly:

- structural and projection evidence can support architecture reasoning;
- calibrated runtime and accurate-layer gates can support stronger narrowing;
- reference-only GPU evidence remains reference-only;
- incomplete phase-1 closure still limits release-facing confidence;
- no frontdoor or proxy surface alone may be promoted into board-grounded causality.

### 6.4 Deterministic contradiction precedence

When evidence surfaces disagree, the adjudicator must resolve or report them using the following precedence ladder, from highest authority to lowest authority:

1. **identity and contract integrity**
   - examples: `join_key_missing`, `join_key_drift`, workload-group inadmissibility, or a fairness / power / observability contract mismatch that makes the comparison non-comparable;
2. **correctness and convergence integrity**
   - examples: `correctness_mismatch`, `convergence_not_comparable`, or any higher-level closure failure that breaks same-correctness or same-boundary comparison;
3. **measured board and whole-node evidence**
   - measured FPGA board evidence, board-validated observability, and measured whole-node power/energy surfaces;
4. **decisive measured GPU baseline evidence**
   - the fastest measured GPU baseline that remains admissible under the frozen fairness and correctness contracts;
5. **calibrated proxy / closure-bound evidence**
   - calibrated simulator outputs, accurate-layer narrowing, and closure-bound evidence that remains below board validation;
6. **structural / frontdoor projection evidence only**
   - graph projection, frontdoor structural projections, and explain-only projection surfaces.

The rule is strict:

- lower-precedence evidence may explain a higher-precedence result;
- lower-precedence evidence may not overturn, hide, or soften a higher-precedence blocker or contradiction;
- if a higher-precedence blocker or contradiction remains active, the affected claim must remain `guarded` or `forbidden` even if lower-precedence evidence looks optimistic.

### 6.5 Trusted-family vs performance-family divergence rule

The adjudicator must surface two different family identities whenever they differ:

- **trusted family** — the family selected by the authority cohort `trusted_point_per_family`;
- **performance family** — the family containing the raw best-performance point.

If those families align, no special divergence rule is needed.

If they diverge, the adjudicator must do all of the following:

1. record the divergence explicitly in `comparison_scope` and in `contradiction_ledger`;
2. keep recommendation authority bound to `trusted_point_per_family`, not to the raw best-performance row;
3. keep the faster performance-family visible as non-authoritative context, not hidden prose;
4. refuse to let either side silently override the other.

The decision consequence is also frozen:

- **Stage A** — trusted/performance divergence forces **no public family recommendation**; the memo may report tradeoffs, but it must not name a public winner;
- **Stage B** — the trusted family may be selected only if measured board or whole-node evidence resolves the divergence in favor of the trusted family and no higher-precedence blocker remains active; otherwise the memo stays conditional or blocked.

### 6.6 Stage A / Stage B activation on one memo surface

Stage A and Stage B must use the **same memo schema, same claim registry, and same contradiction/blocker vocabulary**.

They differ only by activation gates, confidence ceilings, and claim permissions.

The adjudicator memo remains the only decision authority in both stages.

Stage activation changes what the memo is allowed to claim. It does not create a second recommendation surface, and it does not let upstream DSE, GPU, phase, or runnable-model artifacts become public authorities.

#### Stage A

Stage A is the projection-grade / pre-board activation state.

It may see calibrated proxy evidence, closure-bound evidence, and decisive measured GPU baseline evidence, but it remains constrained by the current repo truth: the runnable model is still timed-functional / L1.5-L2 and is not board-grounded.

Therefore Stage A is frozen to these guardrails:

- release posture may be only `blocked`, `no_public_recommendation`, or `bounded_projection_grade_public_memo`;
- public family selection is forbidden;
- final thesis-grade comparative claims are forbidden;
- present-day proxy or calibrated evidence may support tradeoff narration or guarded predictiveness language only.

Stage A is therefore usable for internal narrowing, tradeoff review, and bounded projection-grade public memos, but it is not thesis-grade final authority. The current runnable model truth remains proxy-level and timed-functional, so Stage A may speak about what the present evidence bundle suggests, not about what has been fully closed on measured board or whole-node evidence.

The following claims are explicitly forbidden in Stage A:

- `family_recommendation`
- `cpu_fpga_vs_cpu_only`
- `cpu_fpga_vs_cpu_gpu`
- `lower_whole_node_power`
- `same_correctness_tolerance`
- `resident_offload_fallback_attribution`

At most, `simulator_dse_ranking_predictiveness` may remain as a guarded, projection-grade statement.

#### Stage B

Stage B is the closure-bound / final-adjudication activation state on the same memo surface.

Stage B may unlock stronger claims only when the higher-precedence measured surfaces and hard gates justify them. It does **not** bypass the same blocker classes, contradiction precedence, or divergence reporting rules defined above.

In particular, Stage B does not inherit final-thesis authority merely by being “later”; it must still earn that authority through measured board / whole-node evidence and closed correctness, convergence, fairness, and power boundaries.

That also means Stage B comparative claims against GPU must be anchored to the decisive measured GPU baseline defined by the fairness contract, not merely to the presence of a generic GPU annex. If the decisive measured GPU baseline or shared-rewrite fairness closure remains missing or deferred, those comparative claims must remain `guarded` or `forbidden`.

For this repo, Stage B activation is understood as the point where the memo can prove that the stronger closure gates have actually passed on the current comparison cohort. The minimum closure set is:

1. decisive measured GPU baseline closure under the frozen fairness contract;
2. phase closure, including same-correctness and convergence comparability;
3. board / whole-node closure under the observability contract;
4. ranking-stability closure on the admissible workload group;
5. workload-group admissibility closure for the public comparison scope.

If any part of that closure set is still open, deferred, reference-only, or contradicted by a higher-precedence blocker, the memo must remain Stage A or keep the affected Stage B claims guarded or forbidden.

### 6.7 Allowed, guarded, and forbidden claim reading rule

The same memo schema is used in both stages, but readers must interpret claim states through the claim matrix, not through prose summaries alone.

The policy is frozen as follows:

| Claim surface | Stage A | Stage B when closure is complete |
| --- | --- | --- |
| Public family recommendation | Forbidden | Allowed only when trusted-family authority survives all higher-precedence blockers and measured closure resolves any divergence |
| Simulator / DSE ranking predictiveness | Guarded at most | Allowed or guarded, depending on remaining contradiction and stability state |
| CPU + FPGA vs CPU only | Forbidden as final thesis-grade claim | Allowed only when same-correctness, fairness, and closure contracts are closed |
| CPU + FPGA vs CPU + GPU | Forbidden | Allowed only with decisive measured GPU baseline and closed shared-rewrite fairness boundary |
| Lower whole-node power | Forbidden | Allowed only with measured whole-node power closure |
| Same-correctness / same-tolerance | Forbidden as outward final authority | Allowed only after correctness and convergence closure is explicitly closed |
| Resident / offload / fallback attribution | Forbidden as microarchitectural-causality claim | Allowed only when higher-precedence measured evidence actually supports the attribution |

`allowed` means the adjudicator memo may carry the claim publicly.

`guarded` means the memo may mention the claim only with explicit evidence-tier and blocker context.

`forbidden` means the memo must not present the claim as an outward decision or comparative conclusion.

### 6.8 Relationship to current runnable-model truth

The current runnable model, documented in `model/qe_band_solver_model/README.md`, remains a host-managed timed-functional / proxy-level system model.

That truth constrains the adjudicator in two ways:

1. the runnable model may supply useful proxy, narrowing, and structure-preserving evidence to the adjudicator;
2. the runnable model may not, by itself, promote the memo into board-equivalent, whole-node-equivalent, or thesis-grade authority.

Saying that a family looks favorable in the current runnable model is therefore not the same thing as authorizing a final public claim. Only the adjudicator memo may make that decision, and only within the Stage A or Stage B permissions defined here.

## 7. Reading rule for current repo surfaces

Until later implementation tasks rename or refactor runner outputs, the repo must be read using the following rule:

1. existing DSE and phase runner recommendation-like outputs are provisional evidence packages;
2. the adjudicator is the only layer allowed to convert that evidence into a public decision;
3. any outward-facing summary that bypasses the adjudicator is non-authoritative by definition.

This rule exists to prevent multiple public recommendation surfaces from remaining active at once.

## 8. Minimal implementation consequence for follow-on tasks

Later schema and runner work must preserve this contract:

- upstream runners may continue to emit evidence packages;
- those packages should be renamed or relabeled over time to reduce authority ambiguity;
- the adjudicator memo or equivalent adjudicator output becomes the only release-facing decision surface.

No later task may reintroduce parallel public authorities for DSE ranking, projection review, GPU annex, or phase closure.

## 9. Verification checklist

This contract is correct for the current repo if a reader can answer all of the following without guessing:

1. Who is the only public decision authority? The adjudicator.
2. When does it run? After DSE bundle generation, before or alongside final phase and evidence closure aggregation.
3. What are `family_summary`, `projection`, `gpu_annex_summary`, `phase1_evidence_closure`, and stage-main recommendation surfaces now? Evidence inputs only.
4. What becomes authoritative? Only adjudicator outputs that issue the public family decision, release posture, and claim permission.
5. Which cohort drives recommendation authority once intake is normalized? `trusted_point_per_family`, not canonical profile or raw best-performance rows.
6. What blocks comparison before scoring starts? `join_key_missing` and `join_key_drift` on the frozen adjudicator identity tuple.
7. What is the precedence ladder when evidence disagrees? Identity/contract integrity > correctness/convergence integrity > measured board/whole-node evidence > decisive measured GPU baseline > calibrated proxy / closure-bound evidence > structural/frontdoor projection.
8. What happens when trusted-family and performance-family diverge in Stage A? No public family recommendation.
9. What keeps Stage A honest against current model truth? Stage A can issue only blocked / no-recommendation / bounded projection-grade posture, and six final thesis-grade claim IDs are explicitly forbidden.
10. What changes between Stage A and Stage B? Activation gates, confidence ceilings, and claim permissions only; not the memo shape.
