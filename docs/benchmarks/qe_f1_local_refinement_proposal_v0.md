# QE F1 local refinement proposal v0

## 0. 定位

这份文档对应当前 post-screening 主线的下一执行 phase：

> **在不重开全空间 architecture screening 的前提下，对当前 `F1` working recommendation 做 focused local refinement proposal。**

它建立在以下已冻结事实之上：

- `F1` 是当前 projection-grade、release-ready 的 working recommendation；
- 当前可见 `F2` lane 并没有形成更稳的替代；
- 当前主问题是 recommendation 自身的 runtime risk，而不是 artifact 缺失；
- 当前最强风险信号是：
  - `host_cpu_fallback`
  - `fallback_observed`
  - `inner_steps_at_cap`

因此本 proposal 的目标不是再比较“谁赢”，而是定义：

1. 当前下一轮应该只动哪些 knobs；
2. 每个 knob 的预期作用是什么；
3. 哪些 refinement 现在不要动。

---

## 1. 当前 working baseline

当前 working baseline 固定为：

- `family = F1`
- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

当前主 workloads：

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

当前 recommendation 状态：

- `recommended_family = F1`
- `recommendation_status = ready`
- `bundle_readiness = ready`
- `release_ready_recommendation = true`

但当前 runtime risk 仍是：

- `runtime_risk_level = high`
- 核心信号为：
  - `host_cpu_fallback`
  - `fallback_observed`
  - `inner_steps_at_cap`

---

## 2. Refinement 原则

当前 refinement 必须遵守 4 条原则：

### 2.1 不重开全空间

当前 refinement 只允许在 **F1 working baseline** 周围做局部调整。

### 2.2 不把 closure 当作当前唯一主线

GPU / board closure 仍然重要，但当前更合理的顺序是先把 recommendation 自身的风险解释清楚或局部压低。

### 2.3 不让 refinement 破坏当前主收益来源

当前 `F1` 主线成立的核心是：

- single-hotpath
- 搬运量更低
- spill 为零
- 相比 `F2`，速度和能耗都明显更优

因此 refinement 不能为了“看起来更 balanced”而直接牺牲这些优势。

### 2.4 先动 policy-sensitive knobs，再动 structure-sensitive knobs

当前最优顺序应该是：

1. `diag_policy`
2. `partition_strategy`
3. `resident_policy`

---

## 3. 第一优先 refinement：`diag_policy`

### 3.1 为什么它是第一优先

当前最直接的风险信号是：

- `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`

而这两个信号都直接说明：

> 当前 `diag` 的运行路径是 recommendation 风险的核心来源之一。

### 3.2 这一步想回答的问题

不是问：

- “要不要把 diag 全部硬化？”

而是问：

> 在保持 `F1` 主结构不变的前提下，是否存在比 `cpu_only` 更合理的 diag policy，使得 host fallback 依赖降低，但又不把系统推入更复杂的 full balanced datapath？

### 3.3 当前 proposal

下一轮 focused refinement 应优先围绕：

- `cpu_only`
- `device_first_fallback`

做 controlled comparison，但 comparison 范围应限制在：

- `family = F1`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

也就是：

> 先只改 `diag_policy`，不要同时动 family / partition / resident。

### 3.4 预期收益

希望观察到：

- `host_cpu_fallback_count` 下降
- `fallback_ratio` 下降
- `runtime_risk_score` 下降

同时不应明显恶化：

- `bytes_moved_to_convergence`
- `energy_to_convergence_j`
- `spill_ratio`

---

## 4. 第二优先 refinement：`partition_strategy`

### 4.1 为什么它不是第一优先

当前 `F2` 的对照已经说明：

- 更 balanced 的 `operator__build__diag__refresh` 并没有自动让系统更稳；
- 反而带来：
  - 更高搬运量
  - 更高 spill
  - 更高综合 risk

所以当前不应一上来就把“single_hotpath 不稳”解释成“必须更 balanced”。

### 4.2 这一步该怎么做

`partition_strategy` 的 refinement 只能做 **局部、保守** 的比较。

也就是说，后续只适合问：

> 在不明显增加 reduced-space handoff 和 dataflow complexity 的前提下，是否存在比 `single_hotpath_partition` 更稳的 F1 内部策略？

而不适合问：

> 要不要把整个推荐链推成 F2 风格的 balanced graph？

### 4.3 当前 proposal

这一层暂时只作为 **第二优先观察项**，前提是：

- `diag_policy` refinement 没有显著降低 risk；
- 或者 `diag_policy` 降低 risk 的同时暴露出新的 handoff 问题。

---

## 5. 第三优先 refinement：`resident_policy`

### 5.1 为什么当前优先级较低

因为当前 baseline 上：

- `spill_ratio = 0.0`
- `spill_active_count = 0`

这说明：

- 当前 `F1` 主问题不是 resident-fit 失败；
- 也不是 on-chip budget 立刻不够；
- 所以不应先把 refinement 资源用在 resident policy 上。

### 5.2 它什么时候会上升为第一优先

如果后续发生以下任一情况：

- `diag_policy` refinement 引入更高 device-side驻留压力；
- `partition_strategy` 局部调整导致 spill 出现；
- broader workloads 上开始出现 resident instability；

那么 `resident_policy` 就会上升为主要 refinement knob。

---

## 6. 当前明确不建议做的 refinement

### 6.1 不建议重开 family-level 筛选

因为当前 `F2` 对照已经足够说明：

- 当前 alternative lane 并不更稳；
- 当前问题是 `F1` hardening，而不是“family 选错了”。

### 6.2 不建议立即做 closure-first

因为当前 closure-first 会把 still-high-risk 的 recommendation 往更后面的证据层继续推进，而没有先解释清楚为什么当前 recommendation 仍值得保留。

### 6.3 不建议立即打开更细粒度硬件参数

比如：

- cluster count
- DMA channels
- replication factor
- local scheduling micro-policy

这些都属于再下一层 refinement，而不是当前 recommendation hardening 的第一动作。

---

## 7. 当前建议的执行顺序

### Phase 1 — `diag_policy` focused check

固定：

- `family = F1`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

只改：

- `diag_policy`

目标：

- 看 runtime risk 是否明显下降
- 看 fallback / host assist 是否减少

### Phase 2 — 若仍高风险，再看 `partition_strategy`

但只做局部、保守比较，不直接跳到 `F2` 风格的 balanced pipeline。

### Phase 3 — 只有在 recommendation 风险解释充分后，再切 closure-first

也就是说：

- 当前 refinement phase 的出口不是“换 family”，
- 而是“确认当前 recommendation 是否已经 sufficiently hardened，可以交给 closure 链”。

---

## 8. 这轮 refinement 的成功标准

这轮 focused local refinement 的成功，不要求立刻得到更强 closure；

它只要求达到下面任一结果：

### 成功路径 A

证明：

- `F1` 当前的高风险主要来自 `diag_policy` 保守选择；
- 通过局部 refinement，有机会降低 runtime risk；
- recommendation 值得继续保留并进入后续 closure。

### 成功路径 B

证明：

- 即使局部 refinement 后，`F1` 仍然高风险；
- 但 alternative lane 依然不更优；
- 因此当前最合理的下一步是 closure-first，而不是 family-level rescreen。

---

## 9. 一句话收口

当前最合理的局部 refinement proposal 是：

> **先保持 `F1 / single_hotpath / fit_first / single_hotpath_partition` 不变，只围绕 `diag_policy` 做第一轮 focused refinement；若风险仍高，再把 `partition_strategy` 作为第二优先局部比较对象，而不是重新打开 family-level search。**
