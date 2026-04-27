# QE F1 runtime-risk reduction plan v0

## 0. 定位

这份文档是当前 `post-rescreen execution plan` 选定的第一条执行 lane：

> **F1 recommendation hardening / runtime-risk reduction phase**

它不是重新做 architecture search，也不是立即进入 GPU / board closure。

它的作用是把当前 `F1` working recommendation 的高风险信号拆开，回答：

1. 当前 `F1` 的主要 runtime risk 到底是什么；
2. 这些风险最可能对应哪类 system-level knob；
3. 后续应该做哪种局部 refinement，而不是重新打开全空间。

---

## 1. 当前输入证据

本计划只锚定当前已经存在的 artifacts：

- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`
- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json`
- `tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json`
- `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json`

以及当前已冻结的前端输入：

- `qe_kernel_characterization_matrix_for_system_dse_v0.md`
- `qe_partition_and_interface_for_system_dse_v0.md`
- `qe_dse_parameter_stack_for_system_dse_v0.md`
- `qe_post_rescreen_execution_plan_v0.md`

---

## 2. 当前 F1 working recommendation

当前 working recommendation 的共同配置是：

- `family = F1`
- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

它当前在两个 mainline workloads 上都被保留为：

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

并且在 recommendation package 中是：

- `recommended_primary_candidates`
- `best_trusted_point`
- `best_performance_candidate`

---

## 3. 当前风险证据抽取

### 3.1 `si4_pbe_uspp_small`

从 `qe_next_stage_stage_main_recommendation.json` / `qe_next_stage_projection_review.json` 读取到：

- `time_to_convergence_s = 0.53`
- `energy_to_convergence_j = 13.751082693947145`
- `bytes_moved_to_convergence = 782465.6`
- `fallback_ratio = 1.0`
- `spill_ratio = 0.0`
- `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`
- `runtime_risk_score = 5`
- `runtime_risk_level = high`
- `runtime_risk_reasons = [host_cpu_fallback, fallback_observed, inner_steps_at_cap]`

### 3.2 `graphene_pbe_uspp`

同样读取到：

- `time_to_convergence_s = 0.54`
- `energy_to_convergence_j = 14.010537084398978`
- `bytes_moved_to_convergence = 782465.6`
- `fallback_ratio = 1.0`
- `spill_ratio = 0.0`
- `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`
- `runtime_risk_score = 5`
- `runtime_risk_level = high`
- `runtime_risk_reasons = [host_cpu_fallback, fallback_observed, inner_steps_at_cap]`

### 3.3 总体 runtime risk summary

当前 `F1` 主推荐链的整体 runtime 风险呈现出三个稳定信号：

1. **host_cpu_fallback**
2. **fallback_observed**
3. **inner_steps_at_cap**

同时，当前主推荐链上：

- `spill_ratio = 0.0`
- `spill_active_count = 0`

这说明当前主问题不是 resident spill，而是：

> 当前 `F1` 主推荐链在 diag / iteration policy 上明显依赖 host companion 路径，并且 inner-step budget 贴着上限运行。

---

## 4. 当前风险的结构性解释

### 4.1 这不是“F1 完全失效”

当前 package 已经表明：

- `F1` 仍然是当前最可信推荐；
- canonical coverage ready；
- release-ready recommendation 为真。

所以当前问题不是：

> `F1` 不能用。

而是：

> `F1` 当前是 **ready but high-risk**。

### 4.2 风险更像 policy / path 问题，而不是 memory overflow 问题

因为：

- `spill_ratio = 0.0`
- `spill_active_count = 0`
- 但 `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`

这说明当前短板更像：

- `diag_policy` 偏保守；
- `single_hotpath` 下，diag 没有真正进入 device-stable path；
- inner-step scheduling 贴着上限，导致当前 recommendation 更像“保守能跑通”，而不是“稳态低风险”。

### 4.3 数据搬运仍是解释项，但不是唯一主矛盾

当前 graph-level summary 反复出现：

- `host_to_fpga single-hotpath DMA handoff dominates`

这意味着：

- `bytes_moved_to_convergence` 需要保留在解释层；
- 但在当前主推荐链上，最直接的红色信号仍然是 fallback / iteration-cap，而不是 spill。

---

## 5. 当前最可能有效的局部 refinement 方向

当前不建议回到全空间重筛，而只建议围绕下面 3 组 knobs 做局部 refinement：

### 5.1 `diag_policy`

当前值：

- `cpu_only`

它最直接对应当前风险：

- `host_cpu_fallback`
- `last_diag_path = host_cpu_fallback`

当前最值得测试的问题是：

> 在保持 `F1` 作为主 family 的前提下，是否应该尝试把 `diag_policy` 从 `cpu_only` 局部推进到更强的 device-aware lane（例如更受控的 fallback policy），从而降低 runtime risk，而不必重开全空间 family search？

### 5.2 `partition_strategy`

当前值：

- `single_hotpath_partition`

它与当前风险的关系在于：

- 当前推荐链把主收益高度压在 single-hotpath 上；
- reduced / diag / refresh 更像 companion，而不是 fully balanced pipeline；
- 如果 single-hotpath 让 current runtime 更依赖 host fallback，那么下一步可能需要做**局部比较**，看看是否有更稳的 `partition_strategy` 能保留大部分收益，同时降低 risk。

### 5.3 `resident_policy`

当前值：

- `fit_first`

当前看起来 spill 不是主问题，所以：

- 它不是第一优先 refinement knob；
- 但如果后续局部 refinement 推动了更多 device-side activity，它仍可能变成关键次级旋钮。

---

## 6. 当前不建议优先打开的 refinement 方向

### 6.1 不建议优先回到 family-level 重筛

原因：

- 当前 `F1` 已是 ready recommendation；
- 当前缺的不是“没有 family 候选”，而是“当前 family 风险偏高”。

### 6.2 不建议优先推进 closure-first

原因：

- GPU / board closure 很重要；
- 但 closure-first 会把当前 still-high-risk `F1` recommendation 直接推入更后面的证据链；
- 更稳的顺序是先把当前 recommendation 的主要风险解释清楚或局部压低。

### 6.3 不建议优先进入 heuristic / Bayesian

原因：

- 当前问题还没有到“搜索效率成为主要瓶颈”的阶段；
- 主要问题仍然是 recommendation robustness 和 fidelity/closure 分层。

---

## 7. 当前 phase 的直接输出目标

这轮 `F1 runtime-risk reduction phase` 结束时，应该至少形成：

1. 一份明确的 risk decomposition（当前文档就是第一步）；
2. 一份 focused refinement proposal；
3. 一条明确决策：
   - 是继续 recommendation hardening，
   - 还是已经足够进入 closure-first。

---

## 8. 当前建议的执行顺序

### Step 1
接受当前 `F1` 作为 working baseline，不重开全空间。

### Step 2
围绕以下问题做 focused refinement proposal：

- `diag_policy`
- `partition_strategy`
- `resident_policy`（次一级）

### Step 3
判断是否需要显式保留更强的 alternative lane，作为 recommendation hedge。

### Step 4
只有当 recommendation 的风险解释已经足够清楚，才把主线推进到 closure-first。

---

## 9. 当前结论

当前最关键的判断是：

> `F1` 当前不是“错误推荐”，也不是“没有推荐”，而是一个 **projection-grade, release-ready, but runtime-risk-high** 的 working recommendation。

因此当前最合理的下一步，不是回到 architecture re-screening，也不是立刻转为 closure-only，而是：

> **围绕 `host_cpu_fallback` 与 `inner_steps_at_cap` 两个核心风险，对当前 `F1` recommendation 做 focused hardening。**

---

## 10. 下一步可直接执行的动作

为了让这份计划不是只停留在说明层，当前建议把下一步执行动作固定为下面 4 项：

### Action 1 — 固定当前 baseline artifact 路径

把下面三份结果固定为本轮风险收口的 baseline：

- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json`
- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`
- `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json`

### Action 2 — 从 phase summary / package 中提取 F1 vs alternative 的并排风险对照

重点抽取并整理：

- `host_cpu_fallback_count`
- `last_diag_path`
- `runtime_risk_score`
- `runtime_risk_level`
- `runtime_risk_reasons`
- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

目标不是再跑全空间，而是形成“当前 F1 风险画像”和“替代 lane 是否值得保留”的局部对照。

### Action 3 — 对局部 refinement 形成 focused proposal

下一轮只围绕下面 3 个 knobs 形成局部 refinement proposal：

1. `diag_policy`
2. `partition_strategy`
3. `resident_policy`

输出应明确：

- 哪个 knob 是第一优先；
- 它为什么最可能缓解 `host_cpu_fallback` 或 `inner_steps_at_cap`；
- 哪个 knob 只是次级观察项。

### Action 4 — 只有在 recommendation 风险解释充分后，才转入 closure-first

也就是说，当前的直接 runnable 主线不是：

- 先补 GPU / board

而是：

- 先把 `F1` 的 current high-risk state 做清楚
- 然后再决定是否把主线切到 closure-first

一句话说，当前最直接可执行的动作就是：

> **先做 F1 shortlist 的风险对照与局部 refinement proposal，再决定 closure 的推进时机。**
