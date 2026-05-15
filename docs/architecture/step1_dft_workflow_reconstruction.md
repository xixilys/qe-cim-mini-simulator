# Step1 DFT Workflow Reconstruction Contract

This note documents the optional DFT adapter contract for Step1. The generic core
still consumes and emits `WorkloadPackage`, `ComputeGraph`, lowering reports, and
`workload_characterization.json`; DFT-specific reconstruction lives under
`dse_v2/reference_workloads` and is copied into characterization as optional
domain summaries.

## Scope

Step1 may reconstruct a DFT workflow as architecture-independent facts:

- source facts from QE/VASP/normalized DFT inputs;
- stage and phase skeletons for common DFT modes;
- main hotspot kernel-shape facts;
- evidence-labeled hotspot and dominance claims;
- review gates, limitations, and unsupported/experimental diagnostics.

Step1 must not choose mapping, tensor placement, execution scheduling, runtime
policy, descriptor protocol, simulator verdict, or architecture resources.

## Optional characterization summaries

DFT adapters may add these keys under
`WorkloadPackage.domain_metadata["characterization"]`; Step1 copies them into
`workload_characterization.json` when present:

- `domain_phase_summary` (`dse.domain_phase_summary.v1`)
- `domain_workflow_summary` (`dse.domain_workflow_summary.v1`)
- `domain_claim_summary` (`dse.domain_claim_summary.v1`)

No standalone workflow artifact is mandatory in v1.

## Claim labels

DFT claims use strict labels:

- `observed_*`: derived from log/profile/trace runtime evidence;
- `predicted_*`: derived from deterministic formulas, software semantics,
  source templates, or calibrated static models;
- `user_confirmed_*`: prediction or domain fact explicitly reviewed by the user
  or a domain expert.

Static dominance is never serialized as `observed_dominance`. It may appear as
`predicted_dominance` when a configured margin/order gap is met, and can become
`user_confirmed_dominance` only after review.

## Common-mode draft requiring user review

The current v1 draft targets broad recognition plus common-mode reconstruction
for:

- QE `pw.x`: `scf`, `nscf`, `relax`, `vc-relax`;
- QE post-processing: `bands.x`, `dos.x`, `projwfc.x`;
- QE `ph.x` / phonon-like stages as experimental until fixtures are reviewed;
- VASP-like workflows through normalized DFT metadata first, with parser-light
  support deferred to a later hardening pass.

The exact phase taxonomy, project-critical phases, and static dominance margins
remain user-review gates.

## Validation focus

A valid Step1 DFT workflow implementation should prove:

1. common-mode bundles emit stage/phase skeletons;
2. main hotspots carry kernel-shape facts;
3. observed, predicted, and user-confirmed claims are separated;
4. unsupported/experimental cases degrade to diagnostics;
5. Step1 outputs contain no Step2/Step3 decision fields.
