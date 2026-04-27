# QE F1 vs alternative risk comparison v0

## 0. 定位

这份文档是 `F1 recommendation hardening / runtime-risk reduction phase` 的继续执行结果。

它的目标不是重新做 family-level architecture screening，而是：

1. 把当前 working recommendation `F1` 与 screening 中可见的 alternative lane 做并排比较；
2. 判断当前 `F1` 的高风险到底是“仍然优于 alternative 的可接受代价”，还是说明当前 recommendation 不稳；
3. 给出下一轮 focused local refinement proposal。

当前比较对象只使用已经存在的本地 artifacts，不重新跑全空间：

- `tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json`
- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json`
- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`
- `tmp/qe_next_stage_release/fast_layer/fast_layer_bundle.json`

---

## 1. 比较对象

### 1.1 当前 working recommendation

#### F1 lane

- `family = F1`
- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

### 1.2 当前可见 alternative lane

#### F2 lane

- `family = F2`
- `diag_policy = device_first_fallback`
- `offload_scope = balanced`
- `resident_policy = fit_first`
- `partition_strategy = operator__build__diag__refresh`

注意：

- 当前 `F2` 不是 validated alternative；
- 它在现有 phase outputs 里更多是 `explain-only` / 非主推荐 lane；
- 但它足够成为当前 `F1` 的局部风险对照对象。

---

## 2. `si4_pbe_uspp_small` 对比

| 维度 | F1 | F2 | 观察 |
| --- | --- | --- | --- |
| `time_to_convergence_s` | `0.53` | `1.354143222506394` | F1 明显更快 |
| `energy_to_convergence_j` | `13.751082693947145` | `35.450809889173065` | F1 明显更低 |
| `bytes_moved_to_convergence` | `782465.6` | `2507144.0` | F2 搬运量约为 F1 的 3.2× |
| `fallback_ratio` | `1.0` | `0.5714285714285714` | F2 fallback 比例较低，但并未避免 fallback 问题 |
| `spill_ratio` | `0.0` | `0.5714285714285714` | F2 明显引入 spill |
| `host_cpu_fallback_count` | `3` | `4` | F2 host fallback 更严重 |
| `runtime_risk_score` | `5` | `8` | F2 风险更高 |
| `runtime_risk_level` | `high` | `high` | 两者都高，但 F2 更差 |
| `runtime_risk_reasons` | `host_cpu_fallback`, `fallback_observed`, `inner_steps_at_cap` | 同上 + `spill_active`, `large_bucket` | F2 的风险来源更多 |
| `graph seed` | `f1_single_hotpath_graph_v0` | `f2_balanced_graph_v0` | F2 拓扑更复杂 |
| `dataflow_bottleneck_summary` | `host_to_fpga single-hotpath DMA handoff dominates` | `operator-build-diag-refresh handoff dominates reduced-space dataflow` | F2 的主瓶颈从 single DMA handoff 转成多阶段 reduced-space handoff |

### 小结

在 `si4_pbe_uspp_small` 上：

- `F1` 虽然高风险，但仍然比 `F2` 更快、更省能、更少数据搬运；
- `F2` 的主要问题不是“更稳但更慢”，而是“更慢且引入了明显 spill / more complex handoff risk”。

---

## 3. `graphene_pbe_uspp` 对比

| 维度 | F1 | F2 | 观察 |
| --- | --- | --- | --- |
| `time_to_convergence_s` | `0.54` | `1.0863697705802968`（from phase summary fast-layer lane) | F1 仍明显更快 |
| `energy_to_convergence_j` | `14.010537084398978` | `28.896247038581856`（same source) | F1 更低 |
| `bytes_moved_to_convergence` | `782465.6` | `2001680.0` | F2 搬运量约为 F1 的 2.6× |
| `fallback_ratio` | `1.0` | `0.5` | F2 fallback 比例较低，但仍不低 |
| `spill_ratio` | `0.0` | `0.5` | F2 同样引入 spill |
| `runtime_risk_score` | `5` | `8` | F2 风险仍更高 |
| `runtime_risk_level` | `high` | `high` | 两者都高，但 F2 更差 |

### 小结

在 `graphene_pbe_uspp` 上：

- `F1` 的“高风险”并没有被 `F2` 替代掉；
- `F2` 仍表现为更高成本、更高复杂度、且仍然高风险的 lane；
- 所以当前没有证据支持把 `F2` 升为更强的 alternative hedge。

---

## 4. 当前比较的核心结论

### 4.1 `F1` 的问题是真问题，但不是被 `F2` 明确支配的问题

当前对照表明：

- `F1` 的确存在高 runtime risk；
- 但当前可见 `F2` lane 并不是一个“风险更低但稍慢”的保守替代；
- 相反，`F2` 同时呈现：
  - 更慢
  - 更高能耗
  - 更多数据搬运
  - 更高 spill
  - 更高综合 runtime risk

### 4.2 当前 recommendation 仍应保持在 `F1`

因此当前最合理的判断是：

> 当前 `F1` 不是因为“没有 alternative 才被保留”，而是因为当前可见 `F2` alternative 并没有比它更好地解决 runtime risk，反而引入了更多系统代价。

---

## 5. 当前风险更像哪类问题

从对照结果看，当前 `F1` 的问题更像：

### 5.1 `diag_policy` 问题

- `F1` 当前固定 `cpu_only`
- 当前高风险信号与 `host_cpu_fallback` 强绑定

这说明：

- 当前最值得做的局部 refinement 是先检查 `diag_policy`，而不是先改 resident 或 family。

### 5.2 `partition_strategy` 问题，但要谨慎

当前对照表明：

- 从 `single_hotpath_partition` 直接跳到更 balanced 的 `operator__build__diag__refresh`，并没有自然降低风险；
- 反而导致：
  - reduced-space handoff 变复杂
  - 搬运量变大
  - spill 增加

这意味着：

- `partition_strategy` 是值得调的；
- 但下一步不应直接假定“更 balanced 就更稳”。

### 5.3 `resident_policy` 目前不是第一优先

原因：

- `F1` 目前 `spill_ratio = 0.0`
- 当前 primary pain point 并不是 resident-fit 失败

所以：

- `resident_policy` 应该保留为次一级 refinement knob；
- 不应把它当成当前第一优先修复项。

---

## 6. focused refinement proposal

### Proposal 1 — 先围绕 `diag_policy` 做局部对照

目标：

- 判断是否能在保持 `F1` family + current hotpath assumption 的前提下，降低 `host_cpu_fallback` 与 `inner_steps_at_cap`。

当前最值得测试的问题：

> 是否存在一种比 `cpu_only` 更合理、但又不至于把当前 `F1` recommendation 推向更复杂 balanced pipeline 的 `diag_policy` 选择？

### Proposal 2 — `partition_strategy` 只做局部、受控比较

不是重开全空间，而是：

- 在 `F1` 语义下，验证当前 `single_hotpath_partition` 是否真的是最稳结构；
- 对更复杂 handoff 方案保持保守态度，因为当前 `F2` 证据已经说明“更 balanced”不自动带来更低风险。

### Proposal 3 — `resident_policy` 暂列第二优先级

除非后续证据表明：

- spill 开始成为 `F1` 问题；

否则当前不建议先用它作为第一优先 refinement 动作。

---

## 7. 当前对 post-screening 主线的影响

这份对照文档把 post-screening 主线进一步收窄成：

1. **不重开 family-level search**
2. **保持 `F1` 为 working baseline**
3. **优先做 `diag_policy` 层面的 focused hardening**
4. **`partition_strategy` 做局部、保守 refinement**
5. **只有当 recommendation 的风险解释更清楚后，才推进 closure-first**

---

## 8. 一句话收口

当前 `F1` vs alternative 的对照结果说明：

> `F1` 虽然高风险，但当前可见的 `F2` lane 并不是一个更稳妥的替代方案——它更慢、搬运更多、spill 更高、综合风险更高——因此当前最合理的继续推进方向不是重开架构筛选，而是保留 `F1` 作为 working baseline，优先围绕 `diag_policy` 和受控的 `partition_strategy` 做 focused hardening。
