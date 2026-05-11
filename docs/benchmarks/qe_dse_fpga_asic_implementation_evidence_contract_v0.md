# QE DSE FPGA/ASIC implementation evidence contract v0

## Purpose

This contract defines the external Stage D artifact accepted by
`tools/benchmarks/run_unified_dse_v0.py --implementation-evidence`.
The Unified DSE CLI validates and references the artifact; it does not run HLS,
RTL simulation, OpenROAD, FPGA board measurement, ASIC implementation, SystemC,
or gem5.

## Schema identity

- `schema_version`: `qe_dse_fpga_asic_implementation_evidence_v0`
- `execution_status`: `external_evidence_referenced`

## Required fields

```json
{
  "schema_version": "qe_dse_fpga_asic_implementation_evidence_v0",
  "execution_status": "external_evidence_referenced",
  "evidence_id": "stage_d_evidence_run_id",
  "candidate_id": "candidate join key from Unified DSE",
  "implementation_target_class": "fpga",
  "evidence_kind": "hls_synthesis",
  "evidence_status": "available",
  "claim_ceiling": "hls_synthesis_only",
  "artifact_refs": {
    "hls_report": "artifacts/implementation/<candidate>.hls.json"
  },
  "metrics": {
    "estimated_lut": 1000,
    "estimated_bram": 8
  },
  "correctness_dependency": {
    "qe_equivalent_scf_claim": false,
    "qe_correctness_report_ref": null
  },
  "final_public_family_winner": null,
  "production_release_ready": false
}
```

## Target/evidence-kind matrix

| `implementation_target_class` | accepted `evidence_kind` values |
| --- | --- |
| `fpga` | `hls_synthesis`, `rtl_simulation`, `fpga_board`, `implementation_projection` |
| `asic` | `rtl_simulation`, `openroad_physical`, `asic_ppa`, `implementation_projection` |

## Claim ceilings

| `evidence_kind` | required `claim_ceiling` |
| --- | --- |
| `hls_synthesis` | `hls_synthesis_only` |
| `rtl_simulation` | `rtl_simulation_only` |
| `fpga_board` | `fpga_board_measurement_only` |
| `openroad_physical` | `openroad_physical_estimate_only` |
| `asic_ppa` | `asic_ppa_estimate_only` |
| `implementation_projection` | `implementation_evidence_only` |

## Rejected overclaims

The artifact is rejected if it declares any of the following:

- `final_public_family_winner` is non-null;
- `public_winner_claim = true`;
- `production_release_ready = true`.

Implementation evidence can improve the Stage D status surface, but final public
architecture decisions still require an adjudicator/release authority path.
