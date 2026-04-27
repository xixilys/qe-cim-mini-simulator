# QE IC component/graph projection v1

## 1. 目标

这份文档定义 `v1 component_catalog + graph_spec` 如何投影到当前仓库的两类主对象：

1. 当前 DSE / phase / release 主链中的 `design_point + shared join keys`
2. 当前 runnable model 中的 `SystemRunConfig` / `ScfIterationRequest` graph-frontdoor fields

它的作用是把统一描述层真正接到：

- `run_systemc_architecture_family_dse_sweep.py`
- `run_qe_next_stage_dse_phase.py`
- `model/qe_band_solver_model`

当前它仍然是 **projection / adapter 规格**，不是新一套主 authority。

当前 wave 1 已把可复用的 benchmark-layer projection/helper 逻辑收束到
`docs/benchmarks/qe_ic_graph_projection_utils.py`，并由
`docs/benchmarks/test_qe_ic_graph_projection_utils.py` 提供 regression coverage。
这里描述的是 helper 与 consumer 共同遵守的投影边界，不代表 release-facing
authority 已迁到 helper，也不代表 `v0` / `v1` 已完成统一。

---

## 2. 输入对象

当前 projection 的输入是：

- `component_catalog`
- `graph_spec`

其中：

- `component_catalog` 提供 component definition、anchor 与 binding 元信息
- `graph_spec` 提供当前 graph instance 的 modules / links / flows / placement / constraints / join keys

当前 canonical 输入参考文件：

- `docs/architecture/qe_ic_component_catalog_system_level_v1.json`
- `docs/architecture/qe_ic_graph_seed_system_level_v1.json`

---

## 3. 输出面 A：projected design_point

### 3.1 主输出字段

当前 `graph_spec` 必须稳定投影到以下 `design_point` 主身份字段：

- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`

这些字段来自：

- `graph_spec.join_keys`

### 3.2 shared join keys

当前还必须保留：

- `workload_id`
- `workload_group_id`
- `qe_tolerance_schema_id`
- `fairness_policy_id`
- `observability_contract_id`

如果未来 phase/release 还依赖更多 join keys，应继续扩到 `graph_spec.join_keys`，但不得重命名现有 claim-bearing key。

### 3.3 当前最小 projection 结果

```json
{
  "projected_design_point": {
    "family": "F2",
    "diag_policy": "device_first_fallback",
    "offload_scope": "balanced",
    "resident_policy": "fit_first",
    "partition_strategy": "operator__build__diag__refresh"
  },
  "shared_join_keys": {
    "workload_id": "si4_pbe_uspp_small",
    "workload_group_id": "qe_next_stage_mainline",
    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
    "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_v0",
    "observability_contract_id": "qe_simulator_board_observability_v0"
  }
}
```

### 3.4 authority 约束

这一步只是 **导出**，不是重写 authority。

当前 wave 1 的 authority boundary 保持不变，release-facing 仍只认：

- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`

`docs/benchmarks/qe_ic_graph_projection_utils.py` 只是把这些字段以及共享 graph
semantic helpers 以 benchmark-layer 可复用形式集中起来，供 checker 和
frontdoor 复用，不接管 release authority，也不改写现有 payload assembly。

因此：

- 若 graph 字段不能 lossless export 到当前 `design_point` 槽位，就不能进入 `projected_design_point`
- 只能进入 `graph_evidence` sidecar

---

## 4. 输出面 B：SystemRunConfig projection

### 4.1 直接映射字段

当前 `graph_spec + projected_design_point` 必须至少能投影到 `SystemRunConfig` 的以下字段：

| `SystemRunConfig` 字段 | 来源 |
| --- | --- |
| `software_family` | `graph_spec.workload_class.software_family` |
| `flow_family` | `graph_spec.workload_class.flow_family` |
| `case_id` | `graph_spec.workload_class.workload_id` 或上层 lane 指定 case id |
| `architecture_family` | `projected_design_point.family` |
| `signature_id` | `graph_spec.workload_class.signature_id` 或上层 workload/signature resolver |
| `projector_pressure` | `graph_spec.workload_class.signature_hints.projector_pressure` |
| `generalized_ratio_bucket` | `graph_spec.workload_class.signature_hints.generalized_ratio_bucket` |
| `diag_dominance` | `graph_spec.workload_class.signature_hints.diag_dominance` |
| `fft_grid_pressure` | `graph_spec.workload_class.signature_hints.fft_grid_pressure` |
| `offload_scope_override` | `projected_design_point.offload_scope` |
| `resident_policy_override` | `projected_design_point.resident_policy` |

### 4.2 graph-frontdoor fields

当前 `SystemRunConfig` 已经预留了一组 graph-frontdoor 字段，`graph_spec` 应当优先投影到这些字段：

| `SystemRunConfig` 字段 | 来源 |
| --- | --- |
| `graph_frontdoor_mode` | 固定为 `system_level_graph_v1` |
| `graph_id` | `graph_spec.graph_id` |
| `graph_topology_style` | `graph_spec.placement.style` |
| `graph_module_count` | `len(graph_spec.modules)` |
| `graph_flow_count` | `len(graph_spec.flows)` |
| `graph_leaf_component_count` | 当前统计 `leaf-like` modules 数；v1 canonical seed 可为 `0` |
| `graph_has_fft_unit` | 是否存在 `fft_support_unit` module |
| `graph_has_reduction_unit` | 是否存在 `reduced_build_closure_unit` module |
| `graph_has_diag_unit` | 是否存在 `diag_fallback_unit` module |
| `graph_has_vector_diag_companion` | 当前 v1 canonical seed 设为 `false` |
| `graph_has_refresh_unit` | 是否存在 `refresh_residual_unit` module |
| `graph_has_leaf_hotpath_flow` | 当前 v1 canonical seed 一般为 `false` |
| `graph_prefers_diag_before_reduction` | 从 `flows` / `constraints` 推导 |
| `graph_prefers_refresh_before_diag` | 从 `flows` / `constraints` 推导 |
| `graph_requested_cluster_sequence` | `flows` / `constraints` 请求顺序 |
| `graph_resolved_cluster_sequence` | 当前投影到的 brownfield 顺序 |
| `graph_sequence_constraints` | `constraints` 中的顺序约束摘要 |

### 4.3 当前 canonical F2 seed 的建议投影

当前 `qe_ic_graph_seed_system_level_v1.json` 建议至少投影成：

```json
{
  "software_family": "QE",
  "flow_family": "CBANDS_DIAG",
  "case_id": "si4_pbe_uspp_small",
  "architecture_family": "F2",
  "projector_pressure": "medium",
  "generalized_ratio_bucket": "medium",
  "diag_dominance": "medium",
  "fft_grid_pressure": "medium",
  "offload_scope_override": "balanced",
  "resident_policy_override": "fit_first",
  "graph_frontdoor_mode": "system_level_graph_v1",
  "graph_id": "qe_f2_balanced_system_level_seed_v1",
  "graph_topology_style": "balanced_hybrid",
  "graph_module_count": 16,
  "graph_flow_count": 5,
  "graph_leaf_component_count": 0,
  "graph_has_fft_unit": true,
  "graph_has_reduction_unit": true,
  "graph_has_diag_unit": true,
  "graph_has_vector_diag_companion": false,
  "graph_has_refresh_unit": true,
  "graph_has_leaf_hotpath_flow": false,
  "graph_prefers_diag_before_reduction": false,
  "graph_prefers_refresh_before_diag": false,
  "graph_requested_cluster_sequence": "operator_apply,reduced_build,diag,refresh_residual",
  "graph_resolved_cluster_sequence": "A,B,C,D",
  "graph_sequence_constraints": "host_keeps_outer_scf;device_runtime_owns_resident_dma_launch;chip_keeps_operator_reduced_refresh;diag_must_allow_host_fallback;diag_dim_gt_device_limit -> host_diag_assist;resident_spill_can_force_host_diag"
}
```

### 4.4 与 `ArchitectureTemplateConfig` 的关系

当前 `graph_spec` 不是直接替代 `ArchitectureTemplateConfig`。

而是：

1. 先投影出 `family / diag_policy / offload_scope / resident_policy`
2. 由现有 family scaffold / template config 提供默认策略
3. 再由 graph-frontdoor 字段补充结构信息

也就是说：

- `family scaffold` 仍是当前默认策略源
- `graph_spec` 是结构化补充和 override source

---

## 5. 输出面 C：ScfIterationRequest projection

当前 `SystemRunConfig` 只是 run-level 输入对象，真正落到 runtime 的仍然是 `ScfIterationRequest`。

因此 projection 的最终下游还应体现在：

- `request.offload_scope`
- `request.resident_policy`
- `request.graph_frontdoor_mode`
- `request.graph_id`
- `request.graph_topology_style`
- `request.graph_module_count`
- `request.graph_flow_count`
- `request.graph_has_fft_unit`
- `request.graph_has_reduction_unit`
- `request.graph_has_diag_unit`
- `request.graph_has_refresh_unit`
- `request.graph_requested_cluster_sequence`
- `request.graph_resolved_cluster_sequence`
- `request.graph_sequence_constraints`

当前阶段这意味着：

> `graph_spec` 并不是只停留在 docs/benchmarks 层，
> 它已经能够通过当前 graph-frontdoor 字段进入 runtime object。

---

## 6. 从 graph 到 runtime 的当前推导规则

### 6.1 module presence -> boolean frontdoor flags

根据 module 的 `component_ref` 推导：

- 有 `fft_support_unit` -> `graph_has_fft_unit = true`
- 有 `reduced_build_closure_unit` -> `graph_has_reduction_unit = true`
- 有 `diag_fallback_unit` -> `graph_has_diag_unit = true`
- 有 `refresh_residual_unit` -> `graph_has_refresh_unit = true`

### 6.2 flow order -> cluster sequence hints

当前 system-level flow role 到 brownfield cluster 顺序的最小映射：

- `operator_apply` -> `A`
- `reduced_build` -> `B`
- `diag` -> `C`
- `refresh_residual` -> `D`

因此若 canonical flow 顺序为：

- `operator_apply -> reduced_build -> diag -> refresh_residual`

则当前建议：

- `graph_requested_cluster_sequence = "operator_apply,reduced_build,diag,refresh_residual"`
- `graph_resolved_cluster_sequence = "A,B,C,D"`

### 6.3 placement.style -> graph_topology_style

当前最小规则：

- `placement.style = balanced_hybrid` -> `graph_topology_style = balanced_hybrid`
- `placement.style = host_heavy` -> `graph_topology_style = host_heavy`
- `placement.style = device_heavy` -> `graph_topology_style = device_heavy`

### 6.4 constraints -> sequence / split hints

当前建议把 `constraints` 里的关键规则压缩成字符串摘要，写入：

- `graph_sequence_constraints`

例如：

- `host_keeps_outer_scf`
- `diag_must_allow_host_fallback`
- `operator_before_reduced_build`

---

## 7. sidecar-only 输出

以下信息当前不能直接进 `design_point` 或 `SystemRunConfig` 主字段，只能保留在 `graph_evidence`：

- module 内部 leaf topology
- per-link local schedule notes
- graph-only placement 细节
- component-level未校准中间数值
- evaluator 中间推导矩阵

这类字段可以进入：

- `module_instance_count`
- `link_count`
- `flow_count`
- `critical_path_summary`
- `dataflow_bottleneck_summary`
- `mapping_risk_summary`
- `estimator_provenance`

但不应污染当前 claim-bearing 主字段。

---

## 8. 当前最小 adapter 接口建议

当前最小 adapter 不需要直接改动主线 runner，即可先定义成一个纯检查/投影接口：

当前实现上，这个纯检查/投影 helper 已落在
`docs/benchmarks/qe_ic_graph_projection_utils.py`。wave 1 只覆盖 helper 抽取，以及
checker / frontdoor 对 helper 的采用，不包含 evaluator 迁移、C++ runtime 迁移，
也不包含 full `v0` / `v1` schema unification。

```text
load component_catalog
load graph_spec
validate consistency
project -> projected_design_point
project -> shared_join_keys
project -> system_run_config_patch
project -> graph_evidence_summary
```

其中：

- `projected_design_point` 供 DSE/phase 主链使用
- `system_run_config_patch` 供 runnable model frontdoor 使用
- `graph_evidence_summary` 供 sidecar / review package 使用
- helper 的 regression coverage 在
  `docs/benchmarks/test_qe_ic_graph_projection_utils.py`

---

## 9. 一句话总结

当前 `projection v1` 的核心不是让 graph 直接替代现有主线，而是：

> 让 `graph/component` 能稳定导出到当前 `design_point + join_keys`，
> 同时把 system-level 结构信息注入到 `SystemRunConfig` / `ScfIterationRequest` 的 graph-frontdoor 字段，
> 以此把统一描述层真正接到 DSE 和 simulator 两条现有主链上。
