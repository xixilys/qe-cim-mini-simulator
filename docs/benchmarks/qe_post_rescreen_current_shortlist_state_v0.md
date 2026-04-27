# QE post-rescreen current shortlist state v0

## 0. 定位

这份文档不是新的 DSE strategy，也不是新的 release artifact。

它的作用是把当前 repo 在 **post-architecture-rescreen** 阶段的“当前状态”固定下来，回答：

1. 当前 shortlist 到底是什么；
2. 它已经在哪些层级上通过；
3. 哪些后续步骤还没做；
4. 下一步应该沿着哪条 post-screening 主线继续推进。

这份文档直接锚定当前已经生成的本地结果：

- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json`
- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json`
- `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json`

---

## 1. 当前状态的读法

当前这份状态文档只按 frozen rule 解释已有 artifacts：

- 这是 **projection-grade / release-facing evidence state**；
- 不是 measured-board-grounded final authority；
- adjudicator memo 仍然是唯一 top-level decision authority。

因此这里的“当前推荐”“当前 shortlist”应理解为：

> 当前 system-level re-screening + accurate-layer + canonical coverage 已经收口后的 **working recommendation state**。

---

## 2. 当前 shortlist 状态

### 2.1 当前主推荐 family

来自 `qe_next_stage_stage_main_recommendation.json`：

- `recommended_family = F1`
- `stage_main_recommendation_status = projection_eligible`
- `recommendation_status = ready`
- `recommendation_type = projection-grade`

### 2.2 当前 supported source workloads

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

这说明当前 mainline shortlist 已经不再是“只在一个 anchor 上成立”的状态，而是已经回到当前 repo 固定的两个主结果 case 上。

---

## 3. 当前推荐主候选

### 3.1 Candidate 1

#### `si4_pbe_uspp_small`

- `selection_role = primary_candidate`
- `family = F1`
- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

关键指标：

- `time_to_convergence_s = 0.53`
- `energy_to_convergence_j = 13.751082693947145`
- `runtime_risk_level = high`

关键运行特征：

- `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`
- `spill_active_count = 0`
- `graph seed = f1_single_hotpath_graph_v0`

### 3.2 Candidate 2

#### `graphene_pbe_uspp`

- `selection_role = primary_candidate`
- `family = F1`
- `diag_policy = cpu_only`
- `offload_scope = single_hotpath`
- `resident_policy = fit_first`
- `partition_strategy = single_hotpath_partition`

关键指标：

- `time_to_convergence_s = 0.54`
- `energy_to_convergence_j = 14.010537084398978`
- `runtime_risk_level = high`

关键运行特征：

- `host_cpu_fallback_count = 3`
- `last_diag_path = host_cpu_fallback`
- `spill_active_count = 0`
- `graph seed = f1_single_hotpath_graph_v0`

---

## 4. 当前 shortlist 的结构性解释

### 4.1 当前 shortlist 实际上说明了什么

当前主推荐链指向的是：

- `F1`
- `single_hotpath`
- `fit_first`
- `cpu_only` diag

也就是说：

> 当前最可信的 post-screening recommendation 不是更激进的全内环 device-heavy 方案，而是 **host-heavy / single-hotpath / diag 保守落在 CPU companion 的主线**。

### 4.2 当前 shortlist 没说明什么

它**没有**说明：

- `F1` 已经 board-grounded 优于 GPU；
- `cpu_only` diag 是最终 frozen hardware choice；
- `F2` / `F3` 在未来 closure 补齐后不可能回来；
- 当前 `host_cpu_fallback_count = 3` 的高风险状态可以直接对外解释成最终最优系统行为。

---

## 5. 当前 review / manifest 状态

### 5.1 projection review

来自 `qe_next_stage_projection_review.json`：

- `review_readiness = ready`
- `promoted_candidate_count = 2`
- 两个 promoted candidates 都来自 `F1`
- `projection_reporting_allowed = true`

### 5.2 stage-main recommendation

来自 `qe_next_stage_stage_main_recommendation.json`：

- `recommended_primary_candidate_count = 2`
- `validated_alternative_candidate_count = 0`
- `best_trusted_point = F1`
- `best_performance_candidate = F1`（当前与 trusted point 重合）

### 5.3 manifest

来自 `qe_next_stage_artifact_bundle_manifest.json`：

- `bundle_readiness = ready`
- `release_ready_recommendation = true`
- `accurate_coverage_summary.coverage_ready = true`
- `generalization_ready = false`
- `gpu_annex_summary.status = deferred`
- `phase1_evidence_closure_summary.decisive_lane_closed = false`
- `next_blocker_class = external_measurement_artifacts`

---

## 6. 当前 post-screening 工作已经完成到哪一步

把当前状态映射到 `qe_post_architecture_rescreen_workflow_v0.md` 的步骤，可以得到：

### 已完成

1. shortlist 已经形成
2. accurate-layer 已经跑过
3. canonical coverage 已经 ready
4. generalization coverage 已经存在
5. recommendation package 已经形成
6. release bundle validation 已经能通过

### 仍未完成 / 仍未闭合

7. GPU closure 仍未进入 decisive state
8. board closure 未闭合
9. adjudicator 作为 final authority 的更强读法还不能升级成 thesis-grade
10. 当前 shortlist 的高风险项（`host_cpu_fallback`, `inner_steps_at_cap`）仍需进一步解释或缓解

---

## 7. 当前最重要的风险，不是“没有推荐”，而是“推荐太保守且仍带高 runtime risk”

当前 artifact chain 已经足以表明：

- **主推荐链已经存在**；
- **不是“没有 shortlist”**；
- 但当前主推荐仍然有明显的高 runtime risk signals：
  - `host_cpu_fallback`
  - `fallback_observed`
  - `inner_steps_at_cap`

这说明 post-screening 后的下一步，不应该再回去做“有没有 recommendation”的工作，而应该做：

1. 继续 closure
2. 或者继续解释/压低当前 shortlist 的 runtime risk

---

## 8. 当前最自然的下一步

基于现有状态，后续最合理的两条主线是：

### 路线 A — closure-first

优先推进：

- GPU annex
- board bundle
- phase1 closure pipeline
- adjudicator-ready evidence strengthening

适合目标：

- 想把当前 projection-grade 结果进一步推向更强证据等级；
- 想回答“能不能更接近 CPU/GPU/FPGA / board-grounded 比较”。

### 路线 B — shortlist-risk-reduction-first

优先推进：

- 解释或降低 `host_cpu_fallback_count`
- 解释或缓解 `inner_steps_at_cap`
- 看 `diag_policy / resident_policy / partition_strategy` 的局部 refinement 是否能保留 `F1` 同时降低 risk

适合目标：

- 想先把 current recommendation 变得更稳、更可解释；
- 想让 post-screening 结果不只是“ready”，而是“ready 且更可信”。

---

## 9. 当前推荐

如果现在必须在两条路里选一条，我建议：

> **先走路线 B：先围绕当前 F1 shortlist 的 runtime risk 做解释和局部收口，再进入 closure。**

理由是：

- 当前 recommendation 已经存在；
- 当前最大的短板不是“没有 package”，而是 package 里主候选风险较高；
- 在这个状态下直接推进 closure，可能只是把一个 still-high-risk recommendation 推到更后面的证据层，而没有先把推荐本身解释清楚。

### 当前这条建议已经继续收口成的 artifact

这条建议当前已经被进一步具体化为：

- `qe_f1_runtime_risk_reduction_plan_v0.md`
- `qe_f1_vs_alternative_risk_comparison_v0.md`
- `qe_f1_local_refinement_proposal_v0.md`

因此，当前状态不再只是“建议走路线 B”，而是已经进入：

> **路线 B 的具体执行阶段**。

---

## 10. 一句话收口

当前 post-rescreen 的系统状态可以收成一句话：

> 当前 repo 已经把 **`F1 / cpu_only / single_hotpath / fit_first / single_hotpath_partition`** 收成 projection-grade 的主推荐链，并且在 `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 上都进入了 ready 状态；但当前 generalization 仍未完全 ready，GPU/board closure 尚未闭合，而且 shortlist 自身仍带有明显的 `host_cpu_fallback` 与 `inner_steps_at_cap` 风险，因此下一步更适合先做 shortlist-risk-reduction 或更强 closure，而不是回到全空间重筛。
