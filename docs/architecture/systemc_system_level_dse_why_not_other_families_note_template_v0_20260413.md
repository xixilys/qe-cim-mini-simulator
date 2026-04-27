# 2026-04-13 Why-Not-Other-Families Note Template — SystemC System-Level DSE v0

## 1. 文档定位

这份 note 用于 report lane 或 advisor pack 汇总时，统一解释：

- 为什么当前推荐 `F?` 而不是另外两个 family；
- 或者为什么当前**还不推荐任何 family**；
- 避免只给“推荐谁”，却不解释“为什么不是另外两个”或“为什么现在还不能推荐”。

它应与以下文档配套使用：

- family responsibility matrix
- advisor report template
- confidence and claims rubric
- QE gold correctness report
- sweep / phase summary / shortlist output
- stage artifact bundle manifest（release-facing 顶层入口）
- projection review package（用于引用所有 accurate-layer-passing shortlisted candidates）
- stage-main recommendation package（用于区分最终主推荐与 validated alternatives）

## 2. 使用规则

每条 why-not 说明至少同时引用：

- 一个 system-level ranking 依据；
- 一个 correctness / confidence 依据；
- 一个工程推进层面的理由。

如果当前没有 promoted family，也不允许写成“还没想好”；必须明确指出：
- 当前不提升任何 family 的主阻塞是什么；
- 该阻塞是 fast-layer、accurate-layer、还是 board/observability closure 问题。

## 3. 当前推荐状态写法

### 3.1 若已有推荐 family
- `recommended_family`：填 `F1 / F2 / F3`
- `correctness_status`：来自 QE gold gate / accurate layer
- `confidence`：来自 result bundle
- 若 `recommendation_type = projection-grade`，才补 `speedup_to_convergence_range` 与 `energy_to_convergence_range`

### 3.2 若当前没有 promoted family（evidence-incomplete 示例）
- `recommended_family = none-yet`
- `recommendation_type = evidence-incomplete`
- `correctness_status = partial`（若 accurate-layer 尚未闭合）或当前真实状态
- `confidence = exploratory`（证据未闭合时的默认对外写法）
- `speedup_to_convergence_range` / `energy_to_convergence_range`：留空；在正文里说明“range 尚未报告，因为 fast-layer evidence 仍未闭合”
- `main_blocker = fast-layer shortlist still insufficient_evidence`

### 3.3 若当前已经形成 stage-main recommendation package
- `stage_artifact_bundle_manifest`：作为顶层 release-facing artifact index，先用它定位 summary / projection review / stage-main recommendation package
- `recommended_family`：优先从 `qe_next_stage_stage_main_recommendation.json / .md` 读取
- `recommended_primary_candidates`：作为“为什么推荐当前主线”的直接依据
- `validated_alternative_candidates`：作为 why-not-other-families 与 risk discussion 的直接依据
- `projection review package`：用于补充说明所有 accurate-layer-passing shortlisted candidates，而不把它们都误写成主推荐

## 4. Why not `F1`

### 4.1 一句话版本
- 若当前推荐的不是 `F1`：
  > 当前不优先选择 `F1`，因为它在当前 artifact-backed 排名、correctness/confidence 条件和系统推进代价下，还不足以成为最值得继续投入的主线。
- 若当前没有 promoted family：
  > 当前不把 `F1` 升成主线，并不是因为 `F1` 没价值，而是因为 mainline evidence 还没有闭合到足以做 decisive recommendation。

### 4.2 结构化说明
- **ranking reason**：说明 `F1` 在当前排序里为何没有成为推荐 family，或说明排序本身尚未闭合；
- **correctness / confidence reason**：说明 `F1` 的 gold gate / confidence 是否支撑 decisive recommendation；
- **system-design reason**：说明 `F1` 的 CPU/device/datapath 分工为何当前还不是最优主路线；
- **什么时候 F1 会重新变得有吸引力**：写明触发条件，例如“若更深 offload family 在 accurate-layer 下持续失败，则回退到 `F1` 重新评估”。

## 5. Why not `F2`

### 5.1 一句话版本
- 若当前推荐的不是 `F2`：
  > 当前不优先选择 `F2`，因为它在当前 artifact-backed 排名、correctness/confidence 条件和系统推进代价下，还不足以成为最值得继续投入的主线。
- 若当前没有 promoted family：
  > 当前不把 `F2` 升成主线，并不代表 `F2` 没有潜力，而是因为 mainline evidence 还不足以把它从 planned comparison lane 提升为 decisive recommendation。

### 5.2 结构化说明
- **ranking reason**：说明 `F2` 在当前排序里为何没有成为推荐 family，或说明排序本身尚未闭合；
- **correctness / confidence reason**：说明 `F2` 的 gold gate / confidence 是否足以支撑 decisive recommendation；
- **system-design reason**：说明 `F2` 的 CPU/device 分工是否真正比其他 family 更合适；
- **什么时候 F2 会重新变得有吸引力**：写明触发条件，例如“当 shortlist closure 完成并且 accurate-layer 支撑其 projection-grade claim 时”。

## 6. Why not `F3`

### 6.1 一句话版本
- 若当前推荐的不是 `F3`：
  > 当前不优先选择 `F3`，因为它虽然代表更激进的 device-heavy 方向，但在当前 correctness/confidence、fallback/spill 风险和 system complexity 约束下，还不足以被提升为 decisive mainline。
- 若当前没有 promoted family：
  > 当前不把 `F3` 升成主线，不是因为它无研究价值，而是因为它在当前 phase 仍然属于 conditional / exploratory，且缺少把 hypothesis-grade 结论升级为 decisive recommendation 的闭合证据。

### 6.2 结构化说明
- **ranking reason**：说明 `F3` 在当前排序里处于 exploratory / conditional 的原因；
- **correctness / confidence reason**：说明 `F3` 是否已通过足够强的 correctness / confidence gate；
- **system-design reason**：说明 `F3` 的复杂度、fallback、resident/spill 风险；
- **什么时候 F3 会重新变得有吸引力**：写明触发条件，例如“只有当 accurate-layer 与 ranking-stability 都显著优于 `F1/F2` 时”。

## 7. 若推荐 family 不是 `F2`

### 若推荐 `F1`
应强调：
- 为什么更深 offload 没带来稳定收益；
- 为什么 simplicity / correctness margin 更重要；
- 为什么当前阶段不值得承担 `F2/F3` 的复杂度。

### 若推荐 `F3`
应强调：
- 为什么更激进 device-heavy 在 gold correctness 下仍成立；
- 为什么 `F1/F2` 的系统收益不足；
- 为什么当前值得承担更深工程化成本。

### 若当前没有推荐 family（**当前默认**）
应强调：
- 为什么现在不把任何 family 提升为 decisive mainline；
- 为什么这不是方向错误，而是证据仍待闭合；
- 下一步应该补哪些证据，才能真正开始 why-not/family promotion 的正式比较。

## 8. 不推荐的写法

避免以下说法：

- “我感觉 `F2` 更合理。”
- “`F3` 太复杂，所以不用它。”
- “`F1` 看起来没那么先进。”
- “虽然 gold gate 没过，但我还是更喜欢这个 family。”
- “现在先空着，之后再看。”

这些写法的问题是：
- 没有 ranking 依据；
- 没有 correctness / confidence 依据；
- 容易在老师追问时站不住；
- evidence-incomplete 时会让人误以为团队自己也不知道缺什么。

## 9. 建议的结尾句式

### 有推荐 family 时
> 因此，当前不把 `[other_family]` 作为主线，并不是说它没有价值，而是说在统一 QE gold correctness gate、当前 confidence，以及 convergence-scoped projection 的约束下，它还不是最值得继续投入的系统架构方向。

### 当前没有推荐 family 时（**当前默认**）
> 因此，当前不提升任何 family 为主线，并不是说 `F1 / F2 / F3` 都没有价值，而是说在统一 QE gold correctness gate、当前 confidence、以及 mainline fast-layer 证据仍未闭合的前提下，还不能对任何 family 做出对外 decisive recommendation。

### 当前已经形成 stage-main recommendation package 时
> 因此，当前不把 `[other_family]` 写成主线，并不是因为它完全失败，而是因为 `stage_main_recommendation_package` 已经把 `[recommended_family]` 收口成 recommended primary candidates，而 `[other_family]` 只保留为 validated alternatives / why-not 支撑项。
