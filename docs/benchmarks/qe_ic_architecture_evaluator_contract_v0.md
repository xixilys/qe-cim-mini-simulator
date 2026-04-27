# QE IC architecture evaluator contract v0

## 1. 目标

这份合同定义 graph-DSE v0 的 **architecture evaluator** 应该输出什么、不能输出什么、以及它如何与当前 brownfield 证据链对接。

Evaluator 的职责是：
- 对 graph / component library 描述做系统级估计；
- 产出性能、能耗、延迟、瓶颈与风险解释；
- 为 adapter/export 层提供结构化输入。

Evaluator **不是** release writer，也不是新的主结果 authority。

---

## 2. 输入

最小输入对象：
- `graph_spec`
- `component_catalog`
- `workload_class_descriptor`
- `estimation_profile`
- `shared_join_keys`
- 可选 calibration inputs

---

## 3. 必须输出的结果面

### 3.1 性能
- `total_time`
- `stage_time_breakdown`
- `overlap_or_stall_summary`
- `critical_path_summary`

### 3.2 功耗 / 能耗
- `component_energy_breakdown`
- `transfer_energy_breakdown`
- `idle_static_energy`
- `total_energy`

### 3.3 瓶颈
- `dataflow_bottleneck_summary`
- `memory_bottleneck_summary`
- `transfer_bottleneck_summary`
- `fallback_induced_bottleneck_summary`

### 3.4 风险
- `mapping_risk_summary`
- `runtime_risk_proxy`
- `unsupported_topology_notes`
- `calibration_gap_notes`

---

## 4. evaluator 输出边界

Evaluator 输出分两类：

### A. 可进入 adapter/export 的结构化估计
可被 adapter 层映射到：
- `graph_evidence` sidecar
- explain-only phase/review note
- 部分可 lossless export 的 aggregated metadata

### B. 不可直接进入 claim-bearing 主表的内部解释
例如：
- 中间估计矩阵
- 局部调度推导
- 尚未校准的模块级数值
- 无法稳定投影到现有 result schema 的 graph-only 属性

---

## 5. 与 runtime 证据链的关系

Evaluator 不得直接替代：
- `runtime_observability`
- `runtime_risk_summary`

它只能：
1. 给出 graph-level 解释；
2. 给出可映射到 runtime 风险的补充原因；
3. 作为 phase/review narrative 的增强证据。

---

## 6. Claim-bearing 规则

以下规则必须满足：
- 若一个 evaluator 字段不能 **lossless export** 到现有 schema slot，就只能进入 `graph_evidence` sidecar；
- 若一个 evaluator 字段尚未校准，就只能是 explain-only；
- 任何 release-facing claim 仍需经过当前 phase/release gate。

---

## 7. 最小验证要求

1. evaluator 至少能对一个 canonical seed graph 输出完整估计包；
2. 估计包必须包含性能 / 能耗 / 瓶颈 / 风险四大类字段；
3. adapter 必须能把其中一部分映射到 phase summary 或 sidecar；
4. 当前 execute-model 主链不能因为 evaluator 接入而失效。
