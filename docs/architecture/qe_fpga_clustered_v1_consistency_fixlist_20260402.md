# QE clustered v1 consistency fixlist (2026-04-02)

## 1. Purpose

This note closes the six cross-document consistency issues raised by `docs/architecture/qe_fpga_clustered_v1_design_analysis_20260402.md`. It does not replace the freeze spec or implementation package. Its role is to state which contract was inconsistent, what was changed, and which file now carries the corrected rule.

## 2. Resolved items

| Issue | Resolution | Source-of-truth files |
| --- | --- | --- |
| `size bucket` rule conflicted with `si8_pbe_nc` mapping | Bucket assignment is now driven by a reproducible two-step rule: base bucket from `max_subspace_n`, then `npw` / `nkb` as pressure modifiers. `si8_pbe_nc` therefore remains `medium` without contradiction. | `docs/architecture/qe_fpga_clustered_v1_workload_bucket_mapping_20260402.md` |
| `Cluster C` capacity assumptions exceeded current trace-backed matrix | `Cluster C` now separates current trace-backed baseline envelope (`graphene≈8`, `small-Si≈16`, `Si8≈32`) from reserve-large extension cases (`Au slab`, `SiC32`). Reserve-large rows no longer masquerade as current baseline constraints. | `docs/architecture/qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`, `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md` |
| `T_C_input / T_C_compute / T_C_emit` were defined inconsistently | `T_C_input` is now strictly load / validate, `T_C_compute = factorize + transform + solver + back-transform`, and `T_C_emit` is descriptor pack + drain. | `docs/architecture/qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`, `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md` |
| `P_next` resident / host semantics were ambiguous | `P_next` is now default `resident_commit`; spill goes through `spill_commit`; host visibility is restricted to `host_export` on episode exit, debug/export, or fallback boundary. | `docs/architecture/qe_fpga_clustered_v1_module_interface_table_20260402.md`, `docs/architecture/qe_fpga_clustered_v1_intercluster_exchange_spec_20260402.md` |
| `128-bit lanes` looked both frozen and unfrozen | `128-bit` is now explicitly marked as the provisional default baseline width for v0 arithmetic, not the frozen board-level port contract. | `docs/architecture/qe_fpga_clustered_v1_intercluster_exchange_spec_20260402.md` |
| Cluster A KPI pointed at a B→C parameter | `partial_HS_bandwidth_utilization` is replaced by `A_to_B_emit_utilization`, which now depends on the A→B effective stream service rate instead of `b_reduced_emit_bw_kib_per_us`. | `docs/architecture/qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`, `docs/architecture/qe_fpga_clustered_v1_module_interface_table_20260402.md` |

## 3. What remains unresolved

These fixes close cross-document contract inconsistencies, but they do not by themselves make the design implementation-ready. The next unresolved layers remain:

- exact port widths and arbitration rules
- BRAM / URAM / HBM budget freeze
- clock / CDC policy
- cycle-approx parameter table population
- `Cluster C` algorithm freeze beyond the current cubic proxy

## 4. Intended use

Use this note as the first checkpoint before any HLS / RTL-facing work. If a later document changes one of the six contracts above, it should update this fixlist at the same time.
