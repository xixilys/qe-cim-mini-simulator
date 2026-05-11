# Unified DSE Frontend Contract Layer v0

This note records the frontend-only contract boundary for the reusable DSE
frontend lane. The frontend enumerates candidates, validates legality, runs only
stdlib/optional fast screening models, emits handoff JSON, ingests externally
produced report JSON, normalizes evidence, calibrates proxy metrics, and packages
a release bundle. It **does not execute** SystemC, gem5, QE, HLS, RTL, or board
runs.

## Canonical JSON boundary

The only strong coupling between the frontend and any backend is JSON:

- `candidate_descriptor_v0`
- `backend_execution_request_v0`
- `backend_execution_report_v0`
- `evidence_ir_v0`
- `app_graph_ir_v0`
- `architecture_template_ir_v0`
- `mapping_ir_v0`
- `multi_fidelity_plan_v0`
- `release_bundle_v0`

Backend-specific formats are adapter inputs only. They must be normalized to
`evidence_ir_v0` before ranking, calibration, or release packaging consumes
them.

## Workload adapters and domain isolation

`unified_dse.adapters.WorkloadAdapter` defines the frontend adapter surface:

- `detect(payload)`
- `identity(payload)`
- `domain_extension(payload)`
- `workload_anchor_refs(payload)`
- `application_graph(payload)`
- `correctness_contract(payload)`
- `legacy_aliases(payload)`

Current adapters:

- `QeWorkloadAdapter` emits QE hotpath graph nodes (`h_psi`, reduced build,
  `diag`/`cdiaghg`, refresh/residual) and puts QE-only data under
  `domain_extension.qe` plus the compatibility-only `qe_anchor_refs` alias.
- `GenericTraceAdapter` emits supplied generic nodes/edges or a single-kernel
  fallback and emits no meaningful `qe_*` fields.

For generic workloads, `domain_extension == {}` and all Stage-A rows, CSVs,
Stage-B0 sidecars, descriptors, backend requests, and release bundles must remain
free of meaningful QE aliases.

## Claim ceilings

| Evidence grade | Claim ceiling |
|---|---|
| Descriptor only | `descriptor_only` |
| Fast model screening | `fast_model_screening_only` |
| Calibrated fast screening | `fast_model_calibrated_screening_only` / ranking `fast_model_calibrated_screening` |
| SystemC proxy report | `systemc_proxy_only` or adapter-specific proxy ceiling |
| gem5 smoke/timed | `gem5_smoke_only` / `gem5_timed_only` |
| Correctness-only report | `correctness_only` / QE compatibility `qe_equivalent_scf_correctness_only` |
| Implementation evidence | `implementation_evidence_only` / implementation-specific reference ceiling |
| Board/physical measurement | `board_physical_measured_only` |

No frontend output declares QE-equivalent correctness, board-measured speedup, or
a final public family winner. The decision authority remains
`adjudicator_memo_only`.

## Stage-B0 handoff sidecars

When `--emit-stage-b0-descriptors` is used, the frontend revalidates every row
and writes sidecars only for `valid_executable` candidates:

- `application_graphs/<workload>.json`
- `architecture_templates/<template>.json`
- `mappings/<mapping>.json`
- `candidate_descriptors/<candidate>.json`
- `systemc_configs/<candidate>.json`
- `gem5_systemc_handoff/<candidate>.json`
- `backend_execution_requests/<candidate>.json`

Emission modes:

- `all_valid_executable` (default/backward-compatible): emit every valid row.
- `scheduler_selected_only`: emit only candidates selected by
  `multi_fidelity_plan_v0`; record valid-but-unselected and blocked rows in the
  descriptor manifest.

Unresolved descriptor placeholders such as `cluster_graph`,
`resident_object_map`, `dma_plan`, `software_runtime.control_policy`, and the
host/device event sequence are explicitly marked
`unresolved_descriptor_only`.

## Search and fast model frontend

Search is routed through `unified_dse.search_engine.search_candidates()`:

- `bounded_cartesian` / `bounded_cartesian_prefix`
- `stratified_cartesian`
- `round_robin_by_family`
- `ax_bayesian` as an optional plugin path. If Ax is unavailable, metadata marks
  `available: false` and `unavailable_optional_dependency: ax`; no hard runtime
  dependency is introduced.

`FastModelBackend(source_kind="fast_model_screening")` produces ranking metrics,
`model_metadata`, calibration status, validity domain, confidence, and
`claim_ceiling = fast_model_screening_only`.

## EvidenceIR, calibration, and adjudication posture

`backend_execution_report_v0` requires:

- `schema_version`
- `candidate_id`
- `backend_class`
- `source_kind`
- `fidelity`
- `execution_status`
- `metrics`
- `claim_ceiling`
- `correctness_gate`
- `non_claims`
- `artifact_refs`

`unified_dse.backend_feedback_adapter` validates generic reports or dispatches
legacy SystemC artifacts, then normalizes them to `evidence_ir_v0`.
Calibration consumes EvidenceIR and uses the minimal residual model:

```text
corrected_latency = fast_latency * alpha_family * beta_workload + gamma_transfer
```

Calibration metadata includes `calibration_data_count`, `error_before`,
`error_after`, `validity_scope`, and `confidence`.

## CLI surfaces

Backward-compatible entry point:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir tmp/unified_dse_results \
  --source-kind fast_model_screening \
  --search-backend stratified_cartesian \
  --shortlist-policy top_fast_uncertain_diverse \
  --shortlist-size 3 \
  --emit-multi-fidelity-plan \
  --emit-stage-b0-descriptors \
  --emit-release-bundle \
  --dry-run
```

Thin wrapper:

```bash
python3 tools/benchmarks/qedse_frontend.py frontend enumerate --help
python3 tools/benchmarks/qedse_frontend.py frontend optimize --help
python3 tools/benchmarks/qedse_frontend.py frontend emit-handoff --help
python3 tools/benchmarks/qedse_frontend.py frontend ingest-feedback --help
python3 tools/benchmarks/qedse_frontend.py frontend calibrate --help
python3 tools/benchmarks/qedse_frontend.py frontend adjudicate --help
python3 tools/benchmarks/qedse_frontend.py frontend release --help
```

`--execute-systemc` remains a hard error in the frontend CLI.

## Release bundle

`frontend_release_bundle_v0.json` links the result bundle, candidate descriptors,
backend requests, IR sidecars, multi-fidelity plan, evidence refs, calibration
metadata, stage status, non-touch guard, claim posture, and non-claims. The
bundle deliberately keeps `final_public_family_winner: null`.

## Migration map

The implementation remains in `tools/benchmarks/unified_dse` for compatibility.
Once the frozen schemas above stabilize, the package can move to a future
`frontend/dse_core` tree with these mechanical mappings:

| Current path | Future path |
|---|---|
| `tools/benchmarks/unified_dse/domain_contracts.py` | `frontend/dse_core/contracts.py` |
| `tools/benchmarks/unified_dse/adapters.py` | `frontend/dse_core/workloads/adapters.py` |
| `tools/benchmarks/unified_dse/search_engine.py` | `frontend/dse_core/search.py` |
| `tools/benchmarks/unified_dse/active_multifidelity.py` | `frontend/dse_core/scheduler.py` |
| `tools/benchmarks/unified_dse/backend_feedback_adapter.py` | `frontend/dse_core/evidence.py` |
| `tools/benchmarks/unified_dse/release_bundle.py` | `frontend/dse_core/release.py` |
| `tools/benchmarks/qedse_frontend.py` | `frontend/qedse_frontend.py` |

The migration should be import-compatible and should not change backend JSON.

## Pro-frontend completion additions

The pro-manual frontend surface is now exposed through `frontend/dse_core` while
`tools/benchmarks/unified_dse` remains import-compatible for existing scripts.
The new package is a stable domain-neutral facade over the same JSON contracts:

- `frontend.dse_core.ir` — versioned IR builders and validators.
- `frontend.dse_core.workloads` — QE, generic trace, and synthetic GEMM/stencil/SpMV adapters.
- `frontend.dse_core.search` — bounded, stratified, round-robin, categorical Latin-hypercube, and optional Ax proposal paths.
- `frontend.dse_core.scheduler` — multi-fidelity selection with rank, uncertainty, diversity, baseline, and calibration-gap rationale.
- `frontend.dse_core.feedback` — backend-specific report adapters normalized to `evidence_ir_v0`.
- `frontend.dse_core.calibration` — `calibration_metadata_v0` plus
  `calibration_model_v0` residual correction artifacts.
- `frontend.dse_core.adjudication` — evidence-grade recommendation summaries with no public winner.
- `frontend.dse_core.release` — release bundle and SHA256 manifest helpers.

### Workload and architecture completion posture

QE is an adapter, not the core schema. QE-specific compatibility aliases remain
only for legacy Stage-A rows and are empty for generic/synthetic workloads. The
core workload adapter surface also accepts synthetic GEMM, stencil, and SpMV
workloads as minimal non-QE application families.

`architecture_template_ir_v0` and `mapping_ir_v0` now include descriptor-level
components, target classes, control policy, buffering/fallback semantics, and
host/device event sequence fields. Fields that still require backend realization
remain descriptor-only and do not imply SystemC/gem5/QE execution.

### Search, calibration, and adjudication posture

All candidate generation flows return one search metadata shape. Ax/BoTorch is
optional: if unavailable, the frontend reports a clean unavailable state; if
available, it uses AxClient proposal generation while still treating the output
as candidate generation only. Calibration consumes EvidenceIR and emits both
legacy `calibration_metadata_v0` and `calibration_model_v0`. Adjudication emits
`adjudication_summary_v0` and keeps `final_public_family_winner: null`.

### Release reproducibility

`release_bundle_v0` links result bundles, manifests, sidecars, backend requests,
evidence refs, calibration metadata/model artifacts, adjudication artifacts,
non-touch guard status, and a `frontend_release_sha256_manifest_v0.json` hash
manifest. The frontend remains strictly frontend-only: it never invokes SystemC,
gem5, QE, HLS, RTL, or board runs.
