# QE IC graph export contract v0

## 1. 文档定位

这份合同定义 **graph-DSE v0** 如何接入现有 brownfield DSE / phase / release 主链。

它回答四个问题：
1. 当前什么是 source of truth；
2. graph 层什么能直接写回现有结果主表；
3. 什么只能作为 sidecar evidence；
4. 什么叫 round-trip success。

---

## 2. SSOT 规则

在 `adapter/exporter` 稳定前，以下对象保持 **source of truth** 身份：

- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`
- 所有现有 shared join keys / fairness / observability contract IDs

也就是说：

> graph-DSE v0 是 **overlay / sidecar evidence**，不是第二套 release-facing 主语义系统。

---

## 3. No-parallel-universe invariant

graph-DSE v0 必须满足：

1. 不得绕开当前 `run_systemc_architecture_family_dse_sweep.py` / `run_qe_next_stage_dse_phase.py` 的主结果链直接对外发布 recommendation。
2. 不得发明与现有 `design_point` 平行但不可映射的新主身份字段集合。
3. 不得让 `graph` 语义和现有 `family/policy/partition` 语义同时都声称自己是 release-facing authority。
4. 无法 lossless export 的 graph 信息，必须进入 `graph_evidence` sidecar，而不是污染主 result row。

---

## 4. 字段级 authority / export 表

| Surface / field group | 当前 authority | claim-bearing? | v0 export rule |
| --- | --- | --- | --- |
| `design_point.family / diag_policy / offload_scope / resident_policy / partition_strategy` | 现有 family scaffold | 是 | graph 只能 **lossless export** 到这些字段，不能重新定义它们 |
| `workload_id / workload_group_id / qe_tolerance_schema_id / fairness_policy_id / observability_contract_id` | 现有 workload/contract surfaces | 是 | graph 只能引用或传递，不能重命名 |
| `runtime_observability` | execute-model / runner output | 是 | graph 只能补充解释，不能替代 |
| `runtime_risk_summary` | phase/release aggregation | 是 | graph 风险只能成为 explainability input |
| graph 拓扑细节、模块实例、端口、连接、局部资源属性 | graph layer | 否（直接） | 放入 `graph_evidence` sidecar |
| evaluator 内部瓶颈推导、中间估计、mapping notes | evaluator | 否（直接） | 放入 `graph_evidence` sidecar |

---

## 5. graph_evidence sidecar 规则

`graph_evidence` 是 graph-DSE v0 的主要新输出承载面。

推荐最小字段：
- `graph_id`
- `graph_schema_version`
- `seed_template_id`
- `module_instance_count`
- `link_count`
- `flow_count`
- `critical_path_summary`
- `dataflow_bottleneck_summary`
- `mapping_risk_summary`
- `estimator_provenance`

当前阶段：
- 它可以被 phase summary / review package 引用；
- 但不能直接替代当前 result row 的 claim-bearing 主字段。

---

## 6. round-trip 规则

一个 seed graph 至少必须支持：

### Forward export
`graph_spec -> design_point + shared join keys`

必须稳定导出：
- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`
- 当前 phase/release 所需 shared join keys

### Reverse reconstruction
`design_point + shared join keys -> canonical seed graph identity`

要求至少能稳定恢复：
- `seed_template_id`
- `family-compatible topology class`
- `graph-level compatibility metadata`

---

## 7. round-trip success predicate

只有以下三项同时满足，才算 round-trip 成功：

1. 导出的 `design_point` 与 shared join keys 与当前 schema 完全一致；
2. phase summary / release bundle 的 join 行为不发生 drift；
3. 逆向重建后的 `seed_template_id` 与原 graph 的 canonical seed identity 一致。

---

## 8. v0 rollout gate

graph-DSE v0 进入下一阶段前，必须通过：

1. 至少一个 `F1` seed graph export example
2. 至少一个 `F2` seed graph export example
3. 至少一个 `F3` seed graph export example
4. round-trip predicate 写入并固定
5. graph sidecar 与现有 phase/release 输出能共存

---

## 9. 非目标

当前 v0 不追求：
- 让 graph 直接成为 release-facing 唯一 authority
- 取代现有 `runtime_observability` / `runtime_risk_summary`
- 立即支持任意自由拓扑搜索
- 一开始就覆盖全部细粒度硬件参数
