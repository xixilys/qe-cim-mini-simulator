# QE post-rescreen execution plan v0

## 0. 定位

这份文档不是重新做系统 DSE strategy，也不是重新打开全空间搜索。

它服务于当前这个非常具体的状态：

- Step-1~Step-4 的前端 DSE artifacts 已经冻结；
- `tmp/qe_next_stage_release/` 已经生成了 projection-grade 的主推荐链；
- 当前主推荐是 `F1`，但运行风险仍然偏高；
- GPU / board closure 尚未闭合。

因此，这份文档的目标是：

1. 给出一个**完整但聚焦**的 post-rescreen 执行计划；
2. 明确当前不应该做什么；
3. 直接指定“下一步要执行哪条 lane”。

---

## 1. 当前状态复述（作为计划输入）

当前 repo 已经形成的事实状态如下：

### 1.1 当前 recommendation

来自 `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`：

- `recommended_family = F1`
- `recommendation_status = ready`
- `recommendation_type = projection-grade`
- supported source workloads:
  - `si4_pbe_uspp_small`
  - `graphene_pbe_uspp`

### 1.2 当前 release-facing bundle

来自 `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json`：

- `bundle_readiness = ready`
- `release_ready_recommendation = true`
- canonical coverage ready
- generalization 仍有 mismatch（nonblocking）
- GPU annex deferred
- phase1 decisive lane not closed

### 1.3 当前主问题

当前最重要的问题不是“没有 recommendation”，而是：

- recommendation 已存在；
- 但 shortlist 主候选的 runtime risk 偏高；
- 当前最突出的 signals 是：
  - `host_cpu_fallback`
  - `fallback_observed`
  - `inner_steps_at_cap`

---

## 2. 这一步不该做什么

当前不应该做以下事情：

### 2.1 不重新回到 workload characterization

原因：

- Step-1 artifact 已经存在；
- repo handoff 也明确反对重新铺陈 workload 画像；
- 当前瓶颈已经不在“热点是谁”，而在“当前推荐链还能不能更稳”。

### 2.2 不重新打开全空间 system DSE

原因：

- 当前 recommendation package 已 ready；
- 当前 bundle 不是“没有结果”，而是“结果已形成但尚未充分固化”；
- 在这个节点重新全空间搜索只会稀释 post-screening 的执行重心。

### 2.3 不把 GPU / board closure 当作唯一当前主线

原因：

- closure 很重要；
- 但当前 closure 缺口有外部依赖；
- 如果不先把当前 `F1` recommendation 的风险解释清楚，closure 只是在往后推一个 still-high-risk 的推荐链。

---

## 3. 当前完整计划（按优先级）

### 路线 A：closure-first

#### 要做的事
- 配置 GPU baseline / reference dirs
- 配置 board artifact bundle
- 跑 phase1 closure pipeline
- 推进 adjudicator-ready stronger evidence

#### 优点
- 能尽快把结果推向更强证据等级
- 直接面向 CPU/GPU/FPGA / board-facing closure

#### 风险
- 当前 closure 依赖部分外部 artifact
- 在 shortlist 主候选风险仍高时，closure-first 容易把“ready but risky”的推荐链继续放大

---

### 路线 B：shortlist-risk-reduction-first

#### 要做的事
- 正式抽取当前 `F1` shortlist 的 runtime-risk 证据
- 分解风险来源：
  - `host_cpu_fallback`
  - `inner_steps_at_cap`
  - 与 `diag_policy / resident_policy / partition_strategy` 的关系
- 在不推翻当前 Step-1~Step-4 输入的前提下，形成一轮 **局部 refinement plan**

#### 优点
- 直接作用于当前 recommendation 最薄弱的地方
- 能把当前结果从“ready”推进到“ready and better explained / lower-risk”
- 对后续 closure 更有帮助，因为它先解释清楚为什么当前推荐值得继续推进

#### 风险
- 不会立即提高 closure 等级
- 需要额外定义一轮 focused downstream artifact，而不是继续复用现有 package 就结束

---

## 4. 计划选择：当前默认主线

当前默认选择：

> **路线 B：shortlist-risk-reduction-first**

理由：

1. 当前 recommendation 已经存在，不需要再证明“有没有 recommendation”；
2. 当前 bundle 已 ready，说明后端主线不是坏的；
3. 当前最大短板是 recommendation 本身的 runtime risk，而不是 artifact 缺失；
4. 在这个状态下，先解释/降低风险，比直接推进 closure 更稳。

---

## 5. 当前执行目标（直接可执行的下一个 phase）

### 5.1 phase 名称

建议把下一步正式命名为：

**`F1 recommendation hardening / runtime-risk reduction phase`**

### 5.2 phase 目标

这一 phase 只回答下面 4 个问题：

1. 当前 `F1` 的风险到底来自哪里？
2. 这些风险是 current policy choice 的自然结果，还是局部可调的 artifact？
3. 当前是否需要保留一个更明确的 validated alternative 作为风险对冲？
4. 在不重开全空间 DSE 的前提下，下一轮最值得尝试的局部 refinement 是什么？

### 5.3 success criteria

这一 phase 结束时，至少应形成：

- 一份 `F1` runtime-risk decomposition 文档；
- 一份针对当前 shortlist 的局部 refinement 建议；
- 明确说明是否要进入 closure-first，还是还需继续 recommendation hardening。

---

## 6. 直接执行顺序（本轮）

当前推荐按下面顺序直接执行：

### Step 1 — 固定当前 working baseline

把以下 artifacts 作为当前 baseline，不再重跑全空间：

- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json`
- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`
- `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json`

### Step 2 — 抽取 F1 runtime-risk 证据

重点抽取：

- `host_cpu_fallback_count`
- `last_diag_path`
- `runtime_risk_score`
- `runtime_risk_level`
- `runtime_risk_reasons`
- `inner_steps_at_cap`
- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

### Step 3 — 解释风险与当前 policy 的关系

重点看：

- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

与当前风险的关系。

### Step 4 — 定义局部 refinement 方向

当前只允许局部 refinement，不回到全空间搜索。

优先考虑：

1. `diag_policy`
2. `resident_policy`
3. `partition_strategy`

### Step 5 — 输出 recommendation hardening artifact

形成一份 downstream artifact，明确：

- current F1 的主要风险来源
- 当前是否需要为 `F2` 保留更强 alternative lane
- 下一轮 focused execution 应改哪几个 knobs

---

## 7. 当前 plan 的执行边界

这份 plan 明确要求：

- 不重启全空间 DSE
- 不重新做 characterization
- 不把 current bundle 读成 thesis-grade authority
- 不把 closure-first 当作唯一主线

它允许：

- 基于现有 artifact 做 focused downstream analysis
- 在现有 shortlist 上做 policy-sensitive refinement
- 为后续 closure 做更稳的 recommendation baseline

---

## 8. 后续衔接

如果这轮 `F1 recommendation hardening / runtime-risk reduction phase` 结束后：

### 情况 A：风险被解释清楚或显著降低

下一步进入：

- GPU / board closure
- phase1 closure pipeline
- stronger adjudicator-ready evidence

### 情况 B：风险依旧高且不可解释

下一步进入：

- 保留 `F1` 但强化 alternative lane
- 或在局部范围内重新比较 `F1` vs `F2`

### 当前已落地的下游 artifact

这条 execution lane 当前已经继续收口成：

- `qe_post_rescreen_current_shortlist_state_v0.md`
- `qe_f1_runtime_risk_reduction_plan_v0.md`
- `qe_f1_vs_alternative_risk_comparison_v0.md`
- `qe_f1_local_refinement_proposal_v0.md`

也就是说，这份 execution plan 之后的主线已经不再停留在“该做什么”，而已经开始形成：

1. 当前 shortlist state
2. F1 risk decomposition
3. F1 vs alternative 对照
4. focused local refinement proposal

---

## 9. 一句话收口

当前最正确的执行计划不是“重新做一遍 DSE”，而是：

> **把已经形成的 `F1` 主推荐链当作 current working baseline，直接进入 `F1 recommendation hardening / runtime-risk reduction phase`，先把当前 shortlist 的高风险问题解释清楚或局部压低，再继续往 closure 和 authority 层推进。**
