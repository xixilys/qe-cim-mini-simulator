## 1. OpenSpec Step2 Contract

- [x] 1.1 Add `step2-architecture-mapping-workflow` requirements for Step1 input consumption, architecture candidate artifacts, DesignPoint completeness, legality matrix, seed mappings, candidate lifecycle, and non-final boundaries.
- [x] 1.2 Add OpenSpec deltas for architecture description, multi-fidelity evaluation, end-to-end workflow, and generic IR Step2 handoff requirements.

## 2. Handbook and Traceability Update

- [x] 2.1 Update the architecture handbook with a Step2 audit section that defines inputs, outputs, artifact checklist, acceptance gates, and review workflow.
- [x] 2.2 Update the OpenSpec traceability matrix so the Step2 change maps to handbook sections and later implementation goals.

## 3. Validation and Handoff

- [x] 3.1 Run OpenSpec strict validation for the Step2 change and all specs.
- [x] 3.2 Record the Step2 reviewed artifacts and remaining implementation handoff notes for later Step2 implementation goals.

## 4. Step2 Implementation Follow-up

- [x] 4.1 Implement the Step2 architecture/mapping workflow entry point that consumes `WorkloadPackage`, source graph, lowering report, executable graph, workflow metadata, required coverage, and source-to-executable mapping.
- [x] 4.2 Persist reviewable Step2 artifacts: architecture catalog/instance, complete DesignPoint, mapping legality matrix, seed set, candidate records, selected record, promotion decision, simulation-sample handoff, feedback state, convergence status, and artifact validation.
- [x] 4.3 Add Step3 replay support so `GenericSystemCBackend` can build a request from persisted Step2 DesignPoint/mapping/workload artifacts without hidden Python state.
- [x] 4.4 Add targeted tests for representative non-QE workloads, DFT/QE seed scoping, unsupported lowering, missing binding, diagnostic/smoke claim boundary, illegal mapping validation, and predicted-only final-claim blocking.
- [x] 4.5 Run implementation validation: Python compile, targeted Step2 tests, full `dse_v2/tests`, and OpenSpec strict validation.
- [x] 4.6 Add multi-architecture Step2 screening orchestration that preserves per-architecture Step3 handoff directories and writes `architecture_screening_records.json` without making final trusted claims.
