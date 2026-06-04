# QE-IC Layer-1 Workload Suite

## Scope

`dse_v2.workloads.qe_ic` implements `QE-IC-Device-Suite-v1`, a Layer-1
workload-suite registry for IC-device-oriented DFT design-space exploration.
It defines workload-family scope, family dependencies, expected motifs,
scenario weights, excluded workflows, and the downstream motif-profiling
contract.

This is a scoped QE/IC workload adapter. It does not add QE-specific fields to
the generic control-plane IR, mapping contracts, simulator requests, or
evidence gates.

## Public API

```python
from dse_v2.workloads.qe_ic import (
    build_default_qe_ic_workload_suite,
    load_qe_ic_workload_suite,
    validate_qe_ic_workload_suite,
    write_qe_ic_workload_suite_artifacts,
)

suite = build_default_qe_ic_workload_suite()
validation = validate_qe_ic_workload_suite(suite)
```

## Artifacts

The CLI writes four artifacts:

```bash
python3 dse_v2/scripts/dse/build_qe_ic_workload_suite.py \
  --out artifacts/qe_ic_workload_suite
```

Expected files:

- `qe_ic_workload_suite.json`
- `qe_ic_workload_suite_validation.json`
- `qe_ic_workload_suite_manifest.json`
- `qe_ic_workload_suite_readme.md`

The loader validates persisted suite artifacts fail-closed. Invalid schema
versions, missing required workload families, invalid dependencies, unregistered
motifs, broken scenario weights, missing excluded-workflow reasons, or weak
claim boundaries cause load-time failure.

## Workload Families

The first-version registry contains:

- `ground_state_band_structure`
- `phonon_dfpt`
- `electron_phonon_mobility`
- `strain_doping_field_sweep`
- `interface_band_offset_defect`

`electron_phonon_mobility` lists `epw.x` under `representative_programs`.
Perturbo is listed only under `external_reference_programs` because it is a
reference transport program, not a core QE executable. EPW remains the
QE-family transport program in the first-version suite.

Each family also carries compact `source_basis` tags. These are stable
provenance tags for downstream documentation and review, not long citations.
Current tags cover QE PWscf ground-state workflows, QE PHonon/DFPT, QE
post-processing, EPW transport/Wannier interpolation, Perturbo as an external
transport reference, and IC-device analysis motives such as mobility, effective
mass, band offsets, and defect traps.

## Scenario Weights

Weights belong to scenarios, not workload families. The default primary
scenario is `mobility_centered_ic_device`; `interface_centered_ic_device`
rebalances importance toward interface, band-offset, and defect workloads.
Every scenario must assign weights to every registered first-version family and
the weights must sum to `1.0`.

## Downstream Contract

Each workload family includes a `profiling_contract` for Layer-2 motif
profiling. Required fields are:

- `runtime_breakdown`
- `op_mix`
- `memory_movement`
- `communication_pattern`
- `parallel_axes`
- `reuse_opportunities`
- `gpu_baseline_required`

GPU baseline tracking is required at Layer-2 because QE/EPW-style workflows and
electron-phonon transport workflows have meaningful heterogeneous-computing
baselines. Layer-1 only records that requirement; it does not measure or compare
targets.

The motif registry also carries Layer-2 taxonomy hints:

- `measurable_profile_fields`
- `possible_target_relevance`
- `known_gpu_strength`
- `known_fpga_risk`
- `layer2_readiness`

These fields keep motif profiling from becoming plain text matching. They are
still Layer-1 hints; Layer-2 must replace them with measured or justified
profile evidence.

## Checked-In Fixture Strategy

`artifacts/qe_ic_workload_suite/` is a canonical release fixture for Layer-1.
It is intentionally committed so reviewers and downstream layers have a stable
example artifact bundle. The regression test
`test_checked_in_qe_ic_artifacts_match_builder_output` regenerates the artifacts
in a temporary directory and byte-compares them against the checked-in fixture to
prevent registry/schema drift.

If the registry changes, regenerate the fixture with:

```bash
python3 dse_v2/scripts/dse/build_qe_ic_workload_suite.py \
  --out artifacts/qe_ic_workload_suite
```

`write_qe_ic_workload_suite_artifacts()` is fail-closed for invalid suites: it
only writes `qe_ic_workload_suite_validation.json` when validation fails. It
does not write a canonical suite, manifest, or README for invalid input.

## Claim Boundary

Layer-1 does not contain profiling results, architecture candidates,
performance estimates, target viability results, promotion decisions, hardware
evidence, or final claim adjudication. Those belong to later layers.

## Validation

Run the focused regression suite:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_workload_suite.py
```

When Python imports changed, also run:

```bash
python3 -m compileall dse_v2
```

The full repository suite had one known unrelated failure during the Layer-1
push audit. It is recorded in
`docs/architecture/qe_ic_layer1_known_failures.json` with test name, observed
state, reason, owner, and `layer1_regression=false`.
