# Generic DSE Architecture Catalog P2 Contract

## Purpose

This note documents the implemented P2 architecture-catalog surface for the
generic DSE framework. It is intentionally limited to architecture schema,
seed families, binding metadata, validation, and the minimum DesignPoint payload.
Mapping search, final reporting, and evidence generation are owned by later
lanes and are not implemented here.

## Source modules

- `dse_v2/architecture/catalog.py` — dataclass schema, seed catalog, validation,
  status labels, simulation-binding metadata, and minimum DesignPoint payload
  export.
- `dse_v2/architecture/__init__.py` — public import surface.

## Schema objects

The catalog separates these concepts:

| Object | Role |
|---|---|
| `ArchitectureCatalog` | Top-level container for families, component types, simulation bindings, and concrete instances. |
| `ArchitectureFamily` | Reusable architecture family with parameters, component-template roles, extension rules, and binding requirements. |
| `ArchitectureParameter` | Typed family knob with allowed-values/range validation. |
| `ComponentType` | Reusable component class such as host CPU, FPGA fabric, GPU SM, CIM array, ASIC block, HBM, NoC, or legacy cluster. |
| `ComponentInstance` | Concrete component inside an architecture instance, including status, supported ops, memory, bandwidth, power, area, and connectivity. |
| `ArchitectureInstance` | Concrete candidate emitted by the catalog, with components, memory hierarchy, interconnect, constraints, bindings, and status. |
| `ConstraintSet` | Power/area/memory/route/operator checks applied before an instance can be trusted. |
| `SimulationBinding` | SystemC or gem5+SystemC adapter metadata used to gate trusted-final eligibility. |

## Status labels and eligibility

Canonical status labels are:

- `implemented`
- `unverified`
- `prototype`
- `stub`
- `planned`
- `unsupported`
- `candidate-only`
- `trusted-final-eligible`

An architecture instance is trusted-final eligible only when all of these are
true:

1. It is not a legacy/reference instance.
2. Its status is `implemented` or `trusted-final-eligible`.
3. It has at least one SystemC or gem5+SystemC binding whose binding status is
   `implemented` or `trusted-final-eligible`.
4. Catalog validation passes for duplicate ids, binding backend consistency,
   non-negative units, required routes, required operators, memory/power/area
   limits, and trusted binding supported-operator coverage.

A passing catalog only means an architecture may enter downstream trusted-final
consideration. Final claims still require run-specific SystemC/gem5+SystemC
evidence and claim gating.

## Seed family list

`seed_generic_dse_architecture_catalog()` currently seeds 11 families:

1. `cpu-only-baseline`
2. `host-fpga-minimal`
3. `host-fpga-cim`
4. `diag-heavy`
5. `streaming-heavy`
6. `memory-rich`
7. `low-power`
8. `balanced`
9. `debug`
10. `future-custom`
11. `legacy-four-cluster-reference`

The historical four-cluster design is represented only as
`legacy-four-cluster-reference-v0` with `candidate-only` status and
`legacy_reference=true`; it is not the default or only architecture family.

## Seed instances and bindings

The seed catalog includes:

- `balanced-generic-systemc-v0` — heterogeneous host+FPGA+GPU+CIM+HBM instance
  with standalone SystemC binding eligibility and gem5+SystemC stub metadata.
- `host-fpga-minimal-v0` — Host+FPGA prototype instance available for screening
  and SystemC bring-up, but not trusted-final eligible until promoted by status.
- `future-custom-candidate-v0` — empty candidate-only extension hook.
- `legacy-four-cluster-reference-v0` — candidate-only legacy/reference instance.

Bindings are separated from instances:

- `standalone_generic_systemc_v1` — implemented SystemC timing backend metadata.
- `gem5_systemc_descriptor_path_v1` — stub/blocked gem5+SystemC metadata with an
  unavailable reason for descriptor/completion closure.

## Minimum DesignPoint payload

`ArchitectureInstance.minimum_design_point_payload()` emits the required P2.3
payload without hidden Python state:

- `design_point_id`
- `workload_id`
- `architecture_instance`
- `component_parameters`
- `memory_hierarchy`
- `interconnect_topology`
- `mapping`
- `data_placement`
- `scheduling_policy`
- `precision_policy`
- `fallback_policy`
- `simulation_config`
- `output_config`
- `constraints`

Downstream mapping and simulation lanes may fill mapping/data-placement choices,
but the catalog owns the architecture-side replay payload.

## Smoke check

```bash
python3 - <<'PY'
from dse_v2.architecture import catalog_summary, seed_generic_dse_architecture_catalog
catalog = seed_generic_dse_architecture_catalog()
summary = catalog_summary(catalog)
assert summary["family_count"] >= 10
assert "legacy-four-cluster-reference-v0" in summary["candidate_only_instances"]
assert "balanced-generic-systemc-v0" in summary["trusted_final_eligible_instances"]
assert summary["validation"] == []
PY
```
