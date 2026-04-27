# 2026-04-13 Advisor Figures and Tables Layout Guide — SystemC System-Level DSE v0

## 1. 文档定位

这份 guide 用于统一 advisor pack 的图表布局建议。目标不是强制视觉设计，而是确保老师在最短时间内看到：

- 当前是否已经形成 recommendation；
- recommendation 的 correctness_status / confidence 是什么；
- `speedup_to_convergence_range` / `energy_to_convergence_range` 落在哪个证据等级；
- 为什么这个结论可信、但又不过度承诺。

如果当前还没有 promoted family，图表也必须完整，但首页要明确写出：
- `recommended_family = none-yet`
- `recommendation_type = evidence-incomplete`

如果当前 next-stage phase 已经进入 `projection_eligible`，图表取数应优先锚定：

- `qe_next_stage_artifact_bundle_manifest.json / .md`
- `qe_next_stage_projection_review.json / .md`
- `qe_next_stage_stage_main_recommendation.json / .md`

## 2. 最推荐的图表顺序

如果时间很紧，优先保留下面 4 个元素：

1. **One-row recommendation table**
2. **Family ranking summary table**
3. **QE gold correctness gate table**
4. **Projection range / evidence-status figure**

如果篇幅允许，再补：

5. CPU/device/datapath responsibility figure
6. assumptions / limitations box

## 3. 图表 1：One-row recommendation table（首页必需）

### 目的
用一行就让老师知道“当前推荐什么，以及可以信到什么程度”。

### 建议字段与填写规则
| 字段 | 填写规则 |
|---|---|
| `recommended_family` | 填 `F1 / F2 / F3 / none-yet`。 |
| `recommendation_type` | 填 `evidence-incomplete / ranking-grade / projection-grade`。 |
| `correctness_status` | 只能填 `gold_pass / gold_fail / portability_only / partial`。证据未闭合时填 `partial`。 |
| `confidence` | 只能填 `high / medium / exploratory`。 |
| `speedup_to_convergence_range` | 只在 `recommendation_type = projection-grade` 时填写；否则留空，并把原因写到 `main_caveat`。 |
| `energy_to_convergence_range` | 同上。 |
| `main_reason` | 对 promoted family 写推荐理由；对 `none-yet` 写主阻塞。 |
| `main_caveat` | 只写一个最关键 caveat。 |

若当前已经形成 stage-main recommendation package，还应在表下注明：
- `stage_artifact_bundle_manifest` 是顶层 release-facing 入口
- `recommended_primary_candidates` 来自 stage-main package
- `validated_alternative_candidates` 来自 stage-main package / projection review package

### 注意
- `speedup` / `energy` 必须是 range；
- 如果 `correctness_status != gold_pass`，这一行要显式降级；
- 如果当前没有 promoted family，不要用空白格或省略，直接写 `none-yet / evidence-incomplete`。

## 4. 图表 2：Family ranking summary table（首页或主报告第一页）

### 目的
把 `F1 / F2 / F3` 的相对关系快速讲清楚。

### 建议字段
| Family | CPU/device split | correctness_status | confidence | speedup_to_convergence_range | energy_to_convergence_range | role |
|---|---|---|---|---|---|---|
| `F1` | host-heavy / single-hotpath | 当前 bundle 若含 `F1` row 则据实填写；否则留空 | 当前 bundle 若含 `F1` row 则据实填写；否则留空 | 仅 projection-grade 时填写 | 仅 projection-grade 时填写 | 填 artifact-backed role；若未闭合则写 `planned comparison lane` |
| `F2` | balanced hybrid / multi-operator pipeline | 当前 bundle 若含 `F2` row 则据实填写；否则留空 | 当前 bundle 若含 `F2` row 则据实填写；否则留空 | 仅 projection-grade 时填写 | 仅 projection-grade 时填写 | 填 artifact-backed role；若无证据则写 `planned comparison lane` |
| `F3` | device-heavy / full inner-loop offload | 只有当前 bundle 实际包含 `F3` row 时才填写；否则留空并标注 `optional/withheld` | 同左 | 只有当前 bundle 实际包含 `F3` row 且 recommendation 为 projection-grade 时才填写 | 同左 | 若无 `F3` artifact，则写 `optional/withheld` |

### 注意
- 角色描述必须由 artifact-backed ranking/summary 决定；若证据未闭合，只写 `planned comparison lane` 或 `optional/withheld`，不要预填 winner/baseline/stretch；
- 若当前已进入 `projection_eligible`，推荐 family 的 role 应以 `stage_main_recommendation_package` 为准；其他通过 accurate-layer 的 candidate 可作为 validated alternatives 进入 why-not 说明；
- 避免只写 cluster 名称，不写 CPU/device 分工；
- 若当前无 promoted family，也应保留这张表，用于说明“比较仍在进行，但 promotion 尚未发生”。

## 5. 图表 3：QE gold correctness gate table（主报告必需）

### 目的
证明这不是“只会讲 story”的 projection，而是有 numerical gate 的。

### 建议字段
| QE case | final total energy match | residual threshold state match | converged/not-converged state match | tolerance schema ID | pass/fail |
|---|---|---|---|---|---|
| `si8_pbe_nc` | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | `qe_gold_numerical_tolerance_schema_v0` | copy gate summary status (`pass / mismatch / baseline_missing / baseline_normalization_error / candidate_missing / model_error / compare_error`) |
| `si8_pbe_uspp` | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | `qe_gold_numerical_tolerance_schema_v0` | copy gate summary status (`pass / mismatch / baseline_missing / baseline_normalization_error / candidate_missing / model_error / compare_error`) |

### 注意
- 没有这个表时，projection-grade recommendation 不应该上首页；
- case ID 应直接从当前 `qe_gold_correctness_contract_v0.md` / canonical gold matrix 抽取；若 contract revision 改了 case set，就同步替换这里；
- 如果 accurate-layer / gate artifact 还没产出，不要自造 `withheld` 或 `not-yet-run`；保持报告头部 `correctness_status = partial`，并在 note 里解释缺失的 artifact。

## 6. 图表 4：Projection range / evidence-status figure（主报告必需）

### 目的
直观展示三类 family 在 convergence-scoped projection 上的大致位置，以及当前 evidence 是否已经足够支持 promotion。

### 推荐形式
- 只有 `projection-grade` family 才画横向区间条形图：
  - `speedup_to_convergence_range`
  - `energy_to_convergence_range`
- `ranking-grade` 与 `evidence-incomplete` family **不画 numeric range bar**；改用状态标签、why-not 注释或空位占位说明“当前无 projection-grade range”
- 每个 family 一行；
- 颜色或标记同时表达：
  - `confidence`
  - `recommendation_type`

### 示例视觉编码
- `projection-grade`：实色区间条
- `ranking-grade`：状态标签 + 简短 why-not，不画区间条
- `evidence-incomplete / exploratory`：状态标签 + blocker 注释，不画区间条

### 注意
- 不要画单点柱状图来假装精确值；
- 不要给 `ranking-grade` 或 `evidence-incomplete` family 画伪区间条；
- 区间图旁边建议放 `assumption_set_id`；
- 若当前 package 已进入 release-facing 使用阶段，图注里建议优先标出 `stage_artifact_bundle_manifest`，再附 `projection_review` / `stage_main_recommendation_package`；
- 若当前 stage 已到 `projection_eligible`，图注里建议同时标出 `projection_review` 与 `stage_main_recommendation_package` 的 artifact 路径；
- 若当前仍未产生 promoted family，图标题应写成 “Current evidence status” 而不是 “Final recommendation”。

## 7. 图表 5：CPU/device/datapath responsibility figure（建议）

### 目的
帮助老师快速理解架构差异不是 cluster 名字差异，而是 system contract 差异。

### 推荐形式
三栏框图：
- Host CPU
- Device runtime
- Hardware datapath

按 `F1 / F2 / F3` 分三行，标出：
- 哪些功能留 CPU；
- 哪些功能交 runtime；
- 哪些功能进 datapath；
- `diag` 默认走哪条路径。

## 8. 图表 6：Assumptions and limitations box（建议）

### 至少包含
- v1 是 system-level 架构筛选器；
- 不是 RTL 参数冻结器；
- 不是最终 board-level power claim；
- projection 只在 QE gold correctness gate 通过时成立；
- 若当前还未完成 fast-layer shortlist closure，必须显式写出 `main_blocker = insufficient_evidence`。

## 9. 版式建议

### 如果只有 1 页
- 上半页：recommendation table + one-paragraph summary
- 下半页：family ranking summary + QE gold gate mini table

### 如果有 2 页
- 第 1 页：cover memo + recommendation table + family ranking
- 第 2 页：QE gold gate + projection/evidence-status figure + limitations box

### 如果有主报告 + 附录
- 首页：cover memo / one-row recommendation
- 第 2 页：family ranking + projection/evidence-status figure
- 第 3 页：QE gold correctness gate
- 附录：portability evidence / assumptions / extra tables

## 10. 常见图表错误

### 不推荐
- 用单个 speedup 数字当作最终结论；
- 只给 projection 不给 correctness gate；
- 图里只写 cluster，不写 CPU/device/datapath 分工；
- 在 evidence-incomplete 状态下，把图标题写成“final winner”；
- 把 portability evidence 图放在 QE gold gate 前面。

### 推荐
- 先 recommendation，再 correctness，再 projection；
- 所有结论都带 `correctness_status / confidence / recommendation_type`；
- 所有 projection 都显式为 range；
- 若当前没有 promoted family，也要把 `none-yet` 状态视觉化表达出来。

## 11. 最小可交付图表集

如果最后时间不够，至少保留：

1. one-row recommendation table
2. family ranking summary table
3. QE gold correctness gate table
4. one-paragraph limitations box

这四项已经足够支持一次稳妥的老师汇报；若当前仍是 evidence-incomplete，也足够清楚说明“框架已收口，但 recommendation 仍待证据闭合”。
