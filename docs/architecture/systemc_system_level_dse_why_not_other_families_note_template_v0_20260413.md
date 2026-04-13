# 2026-04-13 Why-Not-Other-Families Note Template — SystemC System-Level DSE v0

## 1. 文档定位

这份模板用于 report lane 或 advisor pack 汇总时，统一解释：

- 为什么当前推荐 `F2` 而不是 `F1` / `F3`；
- 或者为什么当前推荐 `F1` / `F3`，而另外两个 family 暂时不作为主线；
- 避免只给“推荐谁”，却不清楚说明“为什么不是另外两个”。

它应与以下文档配套使用：

- family responsibility matrix
- advisor report template
- confidence and claims rubric
- QE gold correctness report
- sweep / summary ranking output

## 2. 使用规则

这份 note 只能基于已冻结的上游结论填写，不允许凭主观偏好写“为什么不是另外两个”。

每条 why-not 说明至少同时引用：

- 一个 system-level ranking 依据
- 一个 correctness / confidence 依据
- 一个工程推进层面的理由

## 3. 推荐结构

### 当前推荐 family
- `recommended_family`: `TODO`
- `correctness_status`: `TODO`
- `confidence`: `TODO`
- `speedup_to_convergence_range`: `TODO`
- `energy_to_convergence_range`: `TODO`

## 4. Why not `F1`

### 4.1 一句话版本
> 当前不优先选择 `F1`，因为它虽然是更保守的 host-heavy 基线，但在 `TODO correctness/confidence condition` 下，无法像 `TODO recommended family` 一样提供足够有吸引力的 convergence-scoped projection 或系统分工收益。

### 4.2 结构化说明
- **ranking reason**: `TODO`
- **correctness / confidence reason**: `TODO`
- **system-design reason**: `TODO`
- **什么时候 F1 会重新变得有吸引力**: `TODO`

### 4.3 可用的常见表述
- `F1` 更适合作为 conservative baseline，而不是当前主推荐。
- `F1` 的价值在于提供保守下界，而不是最大化系统级收益。
- 如果更深 offload 带来的复杂度风险无法被 correctness gate 和 projection 结果支撑，再回退到 `F1` 才有意义。

## 5. Why not `F3`

### 5.1 一句话版本
> 当前不优先选择 `F3`，因为它虽然代表更激进的 device-heavy 方向，但在 `TODO correctness/confidence condition` 下，其 projection 收益还不足以抵消 fallback、resident/spill、或 system complexity 带来的风险。

### 5.2 结构化说明
- **ranking reason**: `TODO`
- **correctness / confidence reason**: `TODO`
- **system-design reason**: `TODO`
- **什么时候 F3 会重新变得有吸引力**: `TODO`

### 5.3 可用的常见表述
- `F3` 是 stretch candidate，不应在证据不足时直接升级为主线。
- 如果 `F3` 只能在更激进假设下才优于推荐 family，则当前应保持 exploratory 定位。
- 只有当 QE gold correctness、confidence 和 projection 都显著优于推荐 family 时，`F3` 才值得进入主线。

## 6. 如果推荐 family 不是 `F2`

### 若推荐 `F1`
建议把 why-not 写成：
- 为什么更深 offload 没带来稳定收益
- 为什么 simplicity / correctness margin 更重要
- 为什么当前阶段不值得承担 `F2/F3` 的复杂度

### 若推荐 `F3`
建议把 why-not 写成：
- 为什么更激进 device-heavy 在 gold correctness 下仍成立
- 为什么 `F1/F2` 的系统收益不足
- 为什么当前值得承担更深工程化成本

## 7. 不推荐的写法

避免以下说法：

- “我感觉 `F2` 更合理。”
- “`F3` 太复杂，所以不用它。”
- “`F1` 看起来没那么先进。”
- “虽然 gold gate 没过，但我还是更喜欢这个 family。”

这些写法的问题是：
- 没有 ranking 依据
- 没有 correctness / confidence 依据
- 容易在老师追问时站不住

## 8. 建议的结尾句式

> 因此，当前不把 `TODO family` 作为主线，并不是说它没有价值，而是说在统一 QE gold correctness gate、当前 confidence、以及 convergence-scoped projection 的约束下，它还不是最值得继续投入的系统架构方向。
