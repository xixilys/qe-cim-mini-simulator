# QE IC component/graph input template v1

## 1. 目标

这份文档冻结 architecture-exploration / performance-estimation 平台的 **v1 输入模板**。

它回答四个问题：

1. `component_catalog` 的固定模板应该长什么样；
2. `CPU` 侧和 system-level seed component 在 v1 中如何收口；
3. `graph_spec` 的最小模板应该长什么样；
4. 这些模板如何与当前 brownfield DSE / simulator / artifact chain 对齐。

本文件是对以下合同的上层收口，而不是替代它们：

- `docs/architecture/qe_ic_component_library_contract_v0.md`
- `docs/architecture/qe_ic_graph_schema_guide_v0.md`
- `docs/architecture/qe_ic_graph_export_contract_v0.md`
- `docs/benchmarks/qe_ic_architecture_evaluator_contract_v0.md`

---

## 2. 定位与边界

### 2.1 当前定位

`component_catalog + graph_spec` 是 **统一系统描述层**。

它的职责是：

- 描述 system-level component、连接、流程、placement 和约束；
- 同时喂给快层 DSE evaluator 和 runnable simulator；
- 为 `graph_evidence`、phase summary、review package 提供结构化输入。

### 2.2 非目标

当前 v1 不追求：

- 直接取代现有 release-facing 主 authority；
- 直接支持任意自由拓扑搜索；
- 一开始就覆盖全部细粒度硬件参数；
- 让 component 定义直接等价于 RTL/IP 接口规范。

### 2.3 authority 规则

在 `adapter/exporter` 稳定前，当前 claim-bearing 主身份仍然是：

- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`
- 所有现有 shared join keys / fairness / observability contract IDs

因此：

> `component_catalog + graph_spec` 是统一描述层，
> 但当前阶段仍然必须 round-trip 回现有 `design_point` 主身份。

---

## 3. v1 设计原则

1. 先支持 system-level component，再考虑 leaf/IP 级细化。
2. 先围绕当前 `QE` 主线与 brownfield simulator 收口，而不是追求全通用平台。
3. 每个 component 必须同时回答三件事：
   - 它对应哪个 `QE` 阶段职责；
   - 它如何进入 DSE；
   - 它如何绑定到 simulator。
4. 每个 component 都必须有 `brownfield_anchor` 或 `future_placeholder`。
5. 无法 lossless export 的 graph-only / evaluator-only 信息，只能进入 `graph_evidence` sidecar。

---

## 4. v1 seed components

### 4.1 CPU-side seed components

当前 v1 先把 CPU 侧收口为 5 个一级 component：

1. `HostSCFController`
   - outer `SCF` loop owner
   - request issuance / completion consumption
   - next-iteration decision

2. `PolicyPlanner`
   - `ResidentSetDesc`
   - `BandBatchDesc`
   - `DiagPolicy`
   - workload-signature to runtime-policy mapping

3. `OuterStateUpdateEngine`
   - `rho -> Veff`
   - `psi -> rho_out`
   - `mix_rho`
   - convergence gate

4. `HostDiagAssist`
   - reduced matrices 接收
   - host-side diagonalization fallback / assist
   - diag solution 回传

5. `HostMemoryWindow`
   - `rho`
   - `Veff`
   - mixing history
   - global convergence state
   - host fallback solver inputs / outputs

### 4.2 Device / shared seed components

当前 v1 推荐的 system-level seed components：

1. `DeviceRuntime`
2. `TransferFabric`
3. `HardwareDatapathContainer`
4. `EpisodeScheduleController`
5. `ResidencyNearMemorySubsystem`
6. `OperatorApplyEngine`
7. `FFTSupportUnit`
8. `ReducedBuildClosureUnit`
9. `DiagFallbackUnit`
10. `RefreshResidualUnit`
11. `GraphFlowOverlay`

### 4.3 不直接作为主 component 的对象

以下对象更像 leaf / glue / archived compatibility，不应直接作为 v1 主 component 名称：

- `CIMArrayCore`
- `Residue3MCore`
- `CoefficientAccumulator`
- `RowMergeTree`
- `ContextLoader`
- `DigitSerialInputBoundary`
- `ConjugateSignSelector`
- `NearSRAMCoeffBuffer`
- `NearSRAMRowBuffer`
- `ReplayBundleExecutor`
- `Body04FamilyController`
- `Body10FamilyController`

`Cluster A/B/C/D` 也不应直接作为对外主 component 名称；它们应作为：

- `OperatorApplyEngine`
- `ReducedBuildClosureUnit`
- `DiagFallbackUnit`
- `RefreshResidualUnit`

的 brownfield execution anchors。

---

## 5. 固定 component template

### 5.1 统一模板

所有 component definition 统一采用以下模板。

```yaml
component_id: ""
component_type: ""
role: ""
description: ""

default_placement: ""
allowed_placements: []

qe_stage_ownership: []
supported_ops: []

input_objects: []
output_objects: []
state_objects: []

dataflow_traits:
  traffic_pattern: ""
  statefulness: ""
  residency_sensitivity: ""
  fallback_sensitivity: ""
  overlap_potential: ""

latency_model_ref: ""
power_model_ref: ""

observability_keys: []
capacity_or_limit: {}

fallback_behavior:
  mode: ""
  triggers: []
  fallback_target: ""
  notes: ""

brownfield_anchor:
  code_paths: []
  doc_paths: []
  runtime_objects: []
  placeholder_status: "anchored"

dse_surface:
  exposed_knobs: []
  ranking_metrics: []
  risk_metrics: []
  exportable_join_keys: []

sim_binding:
  instantiation_class: ""
  config_projection: []
  runtime_counters: []
  result_fields: []

extensions: {}
```

### 5.2 必填字段说明

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `component_id` | component 定义 id | 稳定 id，不随 graph instance 改变 |
| `component_type` | component 类别 | 见 5.3 |
| `role` | system-level 职责标签 | 如 `outer_scf_control`、`operator_apply` |
| `default_placement` | 缺省放置位置 | `host` / `fpga` / `shared` / `hybrid` |
| `qe_stage_ownership` | 对应 QE 阶段职责 | 允许多阶段 |
| `supported_ops` | 支持的主操作 | system-level 语义，不要求 IP 细粒度 |
| `latency_model_ref` | 延迟/吞吐模型引用 | 可是 proxy/calibrated/measured 路径 |
| `power_model_ref` | 功耗/能耗模型引用 | 同上 |
| `observability_keys` | 必须可观测的键 | 用于对齐 runtime / board / artifact |
| `capacity_or_limit` | 容量或约束 | 可留空，但字段必须存在 |
| `fallback_behavior` | fallback 合同 | hybrid component 必须填写 |
| `brownfield_anchor` | 映回当前仓库对象 | 必须有 anchor 或 placeholder 标记 |
| `dse_surface` | 进入 DSE 的接口面 | 规定 knobs / metrics / join keys |
| `sim_binding` | 进入 simulator 的绑定面 | 规定 config projection / counters / outputs |

### 5.3 component_type 枚举

当前 v1 固定以下类型：

- `host_control`
- `compute_engine`
- `memory_residency`
- `transfer_fabric`
- `hybrid_boundary`
- `flow_orchestration`
- `system_container`
- `graph_overlay`

### 5.4 类型扩展字段

#### `host_control`

```yaml
extensions:
  host_control:
    owns_global_convergence: false
    owns_policy_generation: false
    owns_host_diag_decision: false
```

#### `compute_engine`

```yaml
extensions:
  compute_engine:
    arithmetic_domain: ""
    primary_data_granularity: ""
    requires_resident_context: false
```

#### `memory_residency`

```yaml
extensions:
  memory_residency:
    resident_objects: []
    retention_policy: ""
    spill_policy: ""
```

#### `transfer_fabric`

```yaml
extensions:
  transfer_fabric:
    channel_kinds: []
    payload_classes: []
    serialization_unit: ""
```

#### `hybrid_boundary`

```yaml
extensions:
  hybrid_boundary:
    decision_owner: ""
    export_objects: []
    import_objects: []
```

#### `flow_orchestration`

```yaml
extensions:
  flow_orchestration:
    ordered_stage_set: []
    barrier_policy: ""
    overlap_policy: ""
```

### 5.5 definition 与 instance 的区别

`component_catalog` 存的是 **definition**，不是 graph 里的具体实例。

例如：

- `HostSCFController` 是 definition
- `host_ctrl_main` 是某个 `graph_spec` 里的 module instance

因此：

- definition 负责声明能力、边界、模型与 anchor
- instance 负责声明当前 graph 中的 placement、连接、约束与具体配置

---

## 6. CPU component 示例

```yaml
component_id: "host_scf_controller"
component_type: "host_control"
role: "outer_scf_control"
description: "Owns outer SCF loop, request issuance, completion handling, and next-iteration decisions."

default_placement: "host"
allowed_placements: ["host"]

qe_stage_ownership:
  - "rho_to_Veff"
  - "build_iteration_request"
  - "wait_completion"
  - "mix_rho"
  - "convergence_gate"

supported_ops:
  - "outer_scf_control"
  - "iteration_orchestration"
  - "request_submission"
  - "completion_consumption"

input_objects:
  - "rho"
  - "Veff"
  - "mixing_history"
  - "CompletionSummary"
  - "workload_signature"

output_objects:
  - "ScfIterationRequest"
  - "next_iteration_decision"
  - "updated_mixing_state"

state_objects:
  - "global_convergence_state"
  - "iteration_state"
  - "policy_context"

dataflow_traits:
  traffic_pattern: "control_dominant"
  statefulness: "loop_carried"
  residency_sensitivity: "medium"
  fallback_sensitivity: "high"
  overlap_potential: "medium"

latency_model_ref: "host_scf_control_v1"
power_model_ref: "host_cpu_runtime_proxy_v1"

observability_keys:
  - "scf_iteration"
  - "host_control_time"
  - "completion_wait_time"
  - "fallback_decision_count"

capacity_or_limit:
  max_inflight_batches: 1
  max_inflight_requests: 1

fallback_behavior:
  mode: "owner_of_host_fallback_decision"
  triggers:
    - "diag_dim_exceeds_threshold"
    - "condition_estimate_exceeds_threshold"
    - "resident_spill_unacceptable"
  fallback_target: "host_diag_assist"
  notes: "Owns decision, not the numerical solve itself."

brownfield_anchor:
  code_paths:
    - "model/qe_band_solver_model/src/host_scf.cpp"
  doc_paths:
    - "docs/architecture/host_managed_full_scf_architecture_v1_20260409.md"
  runtime_objects:
    - "HostSCF"
    - "ScfIterationRequest"
    - "CompletionSummary"
  placeholder_status: "anchored"

dse_surface:
  exposed_knobs:
    - "resident_policy"
    - "diag_policy"
    - "band_batch"
    - "panel_size"
  ranking_metrics:
    - "host_control_overhead"
    - "host_wait_time"
  risk_metrics:
    - "fallback_pressure"
    - "policy_mismatch_risk"
  exportable_join_keys:
    - "family"
    - "diag_policy"
    - "resident_policy"

sim_binding:
  instantiation_class: "HostSCF"
  config_projection:
    - "signature_id"
    - "resident_policy"
    - "offload_scope"
    - "device_diag_max_dim"
  runtime_counters:
    - "host_control_cycles"
    - "host_wait_cycles"
    - "fallback_count"
  result_fields:
    - "host_time"
    - "convergence_iterations"

extensions:
  host_control:
    owns_global_convergence: true
    owns_policy_generation: true
    owns_host_diag_decision: true
```

---

## 7. 固定 graph_spec 最小模板

### 7.1 顶层模板

`graph_spec` 在 v1 中至少必须包含以下顶层字段：

```yaml
graph_schema_version: "v1"
graph_id: ""
seed_template_id: ""
workload_class: {}
join_keys: {}

modules: []
links: []
flows: []

placement: {}
estimation_profile: {}
constraints: {}
observability_requirements: {}
```

### 7.2 顶层字段说明

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `graph_schema_version` | schema 版本 | 当前固定为 `v1` |
| `graph_id` | 当前 graph id | 每个 graph instance 唯一 |
| `seed_template_id` | round-trip canonical anchor | 必填 |
| `workload_class` | workload class 描述 | 对齐 evaluator 输入 |
| `join_keys` | 当前主身份 / 合同 join keys | 必须可导出 |
| `modules` | module instances | graph 主体 |
| `links` | inter-module links | 图连接面 |
| `flows` | flow / stage / dependency | 图流程面 |
| `placement` | host/fpga/shared/hybrid 布局 | 可拆到 module，也可集中声明 |
| `estimation_profile` | 当前估计所用 profile | latency/power calibration context |
| `constraints` | family-compatible / fallback / placement 等约束 | 不得为空壳 |
| `observability_requirements` | 必须可投影的可观测性要求 | 供 simulator / artifact 对齐 |

### 7.3 module template

```yaml
modules:
  - module_id: ""
    component_ref: ""
    role: ""
    placement: ""
    ports: []
    state_binding: []
    config_projection: {}
    brownfield_binding: {}
```

字段约束：

- `component_ref` 必须引用 `component_catalog` 中已有 definition
- `role` 必须是当前流程中的 system-level 角色，而不是随意命名
- `placement` 必须落在当前允许值集合中
- `brownfield_binding` 允许为空，但若为空则必须显式说明是 future placeholder

### 7.4 link template

```yaml
links:
  - link_id: ""
    src_module: ""
    src_port: ""
    dst_module: ""
    dst_port: ""
    payload_kind: ""
    direction: ""
    bandwidth_class: ""
    latency_class: ""
    runtime_channel: ""
```

推荐 `payload_kind`：

- `control_descriptor`
- `resident_object`
- `active_wave_batch`
- `reduced_matrices`
- `diag_solution`
- `completion_summary`

### 7.5 flow template

```yaml
flows:
  - flow_id: ""
    stage_id: ""
    role: ""
    ordered_modules: []
    control_dependencies: []
    data_dependencies: []
    barrier_semantics: ""
    overlap_policy: ""
    runtime_owner: ""
```

当前 v1 推荐至少覆盖以下 flow roles：

- `rho_to_Veff`
- `resident_preload`
- `batch_dma`
- `operator_apply`
- `reduced_build`
- `diag`
- `refresh_residual`
- `completion_return`
- `mix_rho_and_convergence`

### 7.6 join_keys 模板

```yaml
join_keys:
  family: ""
  diag_policy: ""
  offload_scope: ""
  resident_policy: ""
  partition_strategy: ""
  workload_id: ""
  workload_group_id: ""
  qe_tolerance_schema_id: ""
  fairness_policy_id: ""
  observability_contract_id: ""
```

要求：

- `join_keys` 必须能 lossless export 到当前 phase/release schema
- 不允许在 graph 层重命名已有 claim-bearing key

### 7.7 constraints 模板

```yaml
constraints:
  family_compatibility: []
  host_fpga_split_rules: []
  fallback_rules: []
  placement_rules: []
  resource_limits: {}
  export_limits: {}
```

当前 v1 至少要能表达：

- `HostSCF` 必须保持 outer-shell owner
- `DiagFallbackUnit` 必须允许 host fallback
- `graph` 必须能导出当前 `design_point` 主身份
- 无法 export 的 graph-only 信息只能留在 sidecar

### 7.8 observability_requirements 模板

```yaml
observability_requirements:
  runtime_keys: []
  bottleneck_keys: []
  energy_keys: []
  risk_keys: []
  board_alignment_keys: []
```

至少应能覆盖：

- `device_busy`
- `dma_read/write_bytes`
- `host_assist_time`
- `fallback_ratio`
- `spill_ratio`
- `resident_reuse`
- `critical_path_summary`

---

## 8. graph_spec 示例骨架

```yaml
graph_schema_version: "v1"
graph_id: "qe_f2_balanced_seed_a"
seed_template_id: "f2_balanced_seed"

workload_class:
  workload_id: "si4_pbe_uspp_small"
  software_family: "QE"
  flow_family: "CBANDS_DIAG"

join_keys:
  family: "F2"
  diag_policy: "device_first_fallback"
  offload_scope: "balanced"
  resident_policy: "fit_first"
  partition_strategy: "clustered_v1"
  workload_id: "si4_pbe_uspp_small"
  workload_group_id: "qe_mainline"
  qe_tolerance_schema_id: "qe_gold_numerical_tolerance_schema_v0"
  fairness_policy_id: "qe_cpu_gpu_fpga_fairness_v0"
  observability_contract_id: "qe_simulator_board_observability_v0"

modules:
  - module_id: "host_ctrl"
    component_ref: "host_scf_controller"
    role: "outer_scf_control"
    placement: "host"
    ports: ["request_out", "completion_in"]
    state_binding: ["global_convergence_state", "mixing_history"]
    config_projection: {}
    brownfield_binding:
      runtime_object: "HostSCF"

  - module_id: "device_runtime"
    component_ref: "device_runtime"
    role: "request_bridge"
    placement: "fpga"
    ports: ["request_in", "launch_out", "completion_out"]
    state_binding: ["resident_context"]
    config_projection: {}
    brownfield_binding:
      runtime_object: "FPGAOrchestrator"

links:
  - link_id: "request_path"
    src_module: "host_ctrl"
    src_port: "request_out"
    dst_module: "device_runtime"
    dst_port: "request_in"
    payload_kind: "control_descriptor"
    direction: "host_to_device"
    bandwidth_class: "control"
    latency_class: "short"
    runtime_channel: "control_descriptor_channel"

flows:
  - flow_id: "main_iteration"
    stage_id: "operator_apply"
    role: "device_hotpath"
    ordered_modules: ["host_ctrl", "device_runtime"]
    control_dependencies: []
    data_dependencies: []
    barrier_semantics: "request_then_execute"
    overlap_policy: "limited_overlap"
    runtime_owner: "device_runtime"

placement: {}

estimation_profile:
  latency_profile_id: "qe_proxy_latency_v1"
  power_profile_id: "qe_proxy_energy_v1"
  provenance: "proxy"

constraints:
  family_compatibility: ["F2"]
  host_fpga_split_rules:
    - "host_keeps_outer_scf"
  fallback_rules:
    - "diag_must_allow_host_fallback"
  placement_rules: []
  resource_limits: {}
  export_limits:
    sidecar_only_fields: ["graph_topology_detail"]

observability_requirements:
  runtime_keys:
    - "device_busy"
    - "dma_read_bytes"
    - "dma_write_bytes"
  bottleneck_keys:
    - "critical_path_summary"
    - "fallback_induced_bottleneck_summary"
  energy_keys:
    - "total_energy"
    - "transfer_energy_breakdown"
  risk_keys:
    - "mapping_risk_summary"
  board_alignment_keys:
    - "resident_reuse"
    - "spill_ratio"
```

---

## 9. 与 evaluator / simulator / artifact chain 的对齐

### 9.1 evaluator 输入对齐

当前 evaluator 的最小输入是：

- `graph_spec`
- `component_catalog`
- `workload_class_descriptor`
- `estimation_profile`
- `shared_join_keys`
- optional calibration inputs

因此，v1 模板必须显式保留这些对象，而不是把它们隐含在注释或自由字段里。

### 9.2 simulator 绑定对齐

当前 v1 模板要求每个主 component 都提供：

- `brownfield_anchor`
- `sim_binding.instantiation_class`
- `sim_binding.config_projection`
- `sim_binding.runtime_counters`

这样 graph 不必直接重写 simulator，而是通过 binding 映回当前 runnable model。

### 9.3 artifact chain 对齐

当前模板必须支持：

- `graph_spec -> design_point + shared join keys`
- `graph_evidence` sidecar 输出
- `phase summary / projection review / stage package` 引用 graph explainability

但不得：

- 直接替代现有 phase/release gate
- 直接重写现有 result row 的 claim-bearing 字段

---

## 10. 后续使用规则

1. 新增 component 时，先填 `component_catalog` definition，再在 `graph_spec.modules` 中实例化。
2. 新增 graph 字段时，先判断是否能 lossless export；不能则默认进入 `graph_evidence`。
3. 新增 component 若没有 brownfield anchor，必须显式标记 `future_placeholder`，不能伪装成已接上 simulator。
4. CPU-side component 与 device-side component 都必须保持一等地位，不能把 host 侧对象降格成“隐式控制逻辑”。
5. 所有推荐/结论仍需通过当前 DSE/simulator artifact chain，而不是绕过它直接从 graph 层发布。

---

## 11. 一句话总结

当前 `v1` 的正确方向不是“重新发明一套 graph-only 主语义系统”，而是：

> 用固定的 `component template + graph_spec` 模板，
> 把 `QE` 主线、CPU/device/datapath 边界、DSE evaluator、runnable simulator 和 artifact chain 收进同一套统一描述层。

---

## 12. 参考实例

当前仓库已经提供与本模板配套的机器可读参考实例：

- `docs/architecture/qe_ic_component_catalog_system_level_v1.json`
- `docs/architecture/qe_ic_graph_seed_system_level_v1.json`
- `docs/architecture/qe_ic_component_graph_brownfield_binding_v1.md`

它们的职责分别是：

- 提供 system-level component definitions 的最小 catalog；
- 提供一个 canonical `F2` balanced seed graph；
- 说明这套 `v1` 对象如何映回当前 brownfield runtime 与 artifact chain。
