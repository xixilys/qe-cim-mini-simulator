# QE IC component/graph brownfield binding v1

## 1. 目标

这份文档说明 `v1 component_catalog + graph_spec` 如何映回当前 brownfield simulator / artifact chain。

它回答三个问题：

1. 新的 system-level component 如何绑定到当前 runnable model；
2. canonical `graph seed` 如何导出到当前 `design_point + join_keys`；
3. 哪些信息当前只能进入 `graph_evidence` sidecar。

---

## 2. 当前 binding 原则

### 2.1 当前不是 greenfield instantiation

当前 `v1` graph 不是直接生成一套全新的 simulator，而是：

- 用 graph/module/flow 表达 system-level component 关系；
- 再通过 `brownfield_anchor + sim_binding` 投影回当前 runnable model。

也就是说：

> 当前阶段是 **graph-guided binding to brownfield runtime**，
> 不是 **graph-native simulator generation**。

### 2.2 当前 binding 的三层面

1. `component definition -> brownfield anchor`
2. `module instance -> runtime object binding`
3. `graph seed -> design_point + shared join keys`

---

## 3. component 到 brownfield 的绑定表

| v1 component | 当前 brownfield anchor | 主要 runtime object | 绑定说明 |
| --- | --- | --- | --- |
| `system_container` | `src/dft_hybrid_system.cpp` | `DFTHybridSystem` | 顶层系统容器，承接 full-flow 组合语义 |
| `host_scf_controller` | `src/host_scf.cpp` | `HostSCF` | outer `SCF` control / request / completion / next-iteration owner |
| `policy_planner` | `src/host_scf.cpp` + `include/types.hpp` | `HostSCF` + request descriptor objects | 当前还是 `HostSCF` 的子职责，通过 descriptor types 投影 |
| `outer_state_update_engine` | `src/host_scf.cpp` | `HostSCF` | `rho -> Veff`、`mix_rho`、convergence gate 仍由 host 侧对象承接 |
| `host_diag_assist` | `src/host_scf.cpp` + `src/fpga_orchestrator.cpp` | `HostSCF` + `FPGAOrchestrator` | 是当前 `diag` fallback 的 host 半边，不是独立 simulator class |
| `host_memory_window` | `include/types.hpp` + `src/host_scf.cpp` | host-side object/state ownership | 当前是 host-side object ownership surface，不是独立 class |
| `device_runtime` | `src/fpga_orchestrator.cpp` | `FPGAOrchestrator` | resident preload / DMA / fallback bridge / completion owner |
| `transfer_fabric` | `src/interconnect.cpp` | `Interconnect` | control descriptor、DMA、completion 三类事务通道 |
| `hardware_datapath_container` | `src/chip_top.cpp` | `ChipTop` | device execution container |
| `episode_schedule_controller` | `src/clusters/episode_controller.cpp` + `src/clusters/cluster_graph_executor.cpp` | `EpisodeController` + `ClusterGraphExecutor` | local inner-loop owner |
| `residency_near_memory_subsystem` | `src/onchip/resident_context_controller.cpp` + `src/onchip/near_memory_domain.cpp` + `src/onchip/near_sram_support.cpp` | residency / near-memory state | resident/stage/hold/forward/spill 语义绑定面 |
| `operator_apply_engine` | `src/clusters/cluster_a_operator_sweep.cpp` | `ClusterAOperatorSweep` | `h_psi / s_psi` + projector apply 主路径 |
| `fft_support_unit` | `src/onchip/fft_companion.cpp` | `FFTCompanion` | support-grid / FFT 条件性路径 |
| `reduced_build_closure_unit` | `src/clusters/cluster_b_reduced_build.cpp` | `ClusterBReducedBuild` | `H_sub / S_sub` reduced build |
| `diag_fallback_unit` | `src/clusters/cluster_c_hardware_diag.cpp` + `src/fpga_orchestrator.cpp` + `src/host_scf.cpp` | `ClusterCHardwareDiag` + `DiagPolicy` | 当前最关键的 hybrid boundary |
| `refresh_residual_unit` | `src/clusters/cluster_d_refresh_residual.cpp` | `ClusterDRefreshResidual` | `refresh / residual / P_next` |

---

## 4. canonical graph seed 的当前含义

当前新增的 canonical graph seed：

- `docs/architecture/qe_ic_graph_seed_system_level_v1.json`

它不是任意自由拓扑实例，而是：

- 一个 `F2 / balanced / QE / CBANDS_DIAG` 的 system-level canonical seed；
- 用来验证新的 `component_catalog + graph_spec` 是否能描述当前 promoted mainline；
- 同时保留 host/device/datapath 边界，而不退化成 leaf-only 拓扑图。

它对应的主路径是：

1. host outer-shell prepare
2. request + preload
3. device hotpath (`operator_apply -> reduced_build`)
4. hybrid diag boundary
5. refresh / completion / outer-state update

---

## 5. graph seed 到当前 design_point 的导出

当前 canonical seed 必须稳定导出以下主身份：

- `family = F2`
- `diag_policy = device_first_fallback`
- `offload_scope = balanced`
- `resident_policy = fit_first`
- `partition_strategy = operator__build__diag__refresh`

同时保留 shared join keys：

- `workload_id`
- `workload_group_id`
- `qe_tolerance_schema_id`
- `fairness_policy_id`
- `observability_contract_id`

这意味着：

> 当前 graph seed 的主要职责是 **结构化表达和 round-trip export**，
> 而不是发明新的 release-facing 主身份。

---

## 6. 当前哪些信息只能进 sidecar

以下信息当前只能进入 `graph_evidence` / explain-only sidecar：

- module 内部更细的 leaf topology
- port-local scheduling notes
- graph-only link realization 细节
- evaluator 中间推导矩阵
- 尚未校准的局部数值模型

它们不能直接替代：

- `runtime_observability`
- `runtime_risk_summary`
- 现有 phase/release result row 的 claim-bearing 字段

---

## 7. 当前与旧 v0 seeds 的关系

旧文件：

- `docs/architecture/qe_ic_component_catalog_seed_v0.json`
- `docs/architecture/qe_ic_graph_seed_templates_v0.json`

它们当前更偏：

- leaf-oriented
- projector chain / CIM subchain 展开
- graph-DSE v0 的早期 overlay 试验表达

新增的 `v1` 文件更偏：

- system-level component
- host/device/datapath 边界
- 与 current runnable model 的直接绑定
- architecture-exploration / performance-estimation 平台的统一输入层

因此这两套文件当前不是互相覆盖关系，而是：

- `v0`：更细的 graph-DSE / leaf-oriented seed evidence
- `v1`：更高层的平台输入对象与 canonical binding example

---

## 8. 下一步 extension 规则

1. 如果新增的是 system-level component，优先进入 `qe_ic_component_catalog_system_level_v1.json`。
2. 如果新增的是 leaf/IP 级对象，优先作为现有主 component 的内部解释，不直接升格为一级主 component。
3. 如果新增 graph 字段无法 lossless export，就先进入 `graph_evidence` sidecar，而不是污染主 schema。
4. 如果某个 component 还没有独立 brownfield anchor，可以暂时使用 `derived_from_shared_anchor`，但不能伪装成已独立实例化的 simulator class。

---

## 9. 一句话总结

当前 `v1` 的正确 binding 方式是：

> 先用 system-level `component_catalog + graph_spec` 描述系统，
> 再通过 `brownfield_anchor + sim_binding` 映回当前 `HostSCF -> FPGAOrchestrator -> ChipTop -> EpisodeController/ClusterGraphExecutor -> A/B/C/D` 主路径，
> 并把 graph-only 新信息保持在 `graph_evidence` sidecar 中。
