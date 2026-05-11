# QE post-architecture-rescreen workflow v0

## 0. 定位

这份文档服务于这样一个时间点：

> 系统架构已经重新筛选过一轮，当前不再需要回到“哪个 family 可能值得看”的开放式讨论，
> 而要把后续工作收口成一条可执行的、由 shortlist 向 recommendation / closure 推进的工作流。

它的作用是明确：

1. **系统架构重新筛选之后**应该立刻做什么；
2. 哪些步骤属于 recommendation-grade narrowing；
3. 哪些步骤属于 closure / authority / release-facing 阶段；
4. 哪些更细的 refinement 应该推迟到主推荐链稳定之后再做。

这份文档不是新的 strategy 文档，而是把当前 repo 里已经存在的：

- `qe_next_stage_dse_strategy_v0.md`
- `qe_next_stage_dse_simulator_execution_checklist_v0.md`
- `qe_next_stage_release_delivery_spec_v0.md`
- `qe_stepwise_system_dse_workflow_index_v0.md`
- `qe_dse_fidelity_ladder_and_execution_loop_v0.md`

按“post-screening”语境重新整理成一份后续执行清单。

---

## 1. 适用前提

这份 workflow 默认以下条件已经满足：

1. Step-1 workload characterization 已完成；
2. Step-2 partition / interface boundary 已冻结；
3. Step-3 parameter stack 已冻结；
4. 系统架构已经经历过一轮 re-screening，已经不再是全空间开放探索，而是有一组待收口的 system candidates；
5. 当前仍遵守 repo 的 frozen rule：
   - low-cost broad screening
   - medium-cost main search
   - higher-fidelity correctness / closure
   - adjudicator 仍是唯一 top-level authority。

---

## 2. Post-screening 主线（推荐顺序）

当前推荐按下面顺序推进：

1. **冻结 shortlist**
2. **对 shortlist 做 accurate-layer correctness validation**
3. **补 canonical coverage**
4. **补 nonblocking generalization coverage**
5. **生成 recommendation packages**
6. **跑 release validators**
7. **推进 GPU / board closure**
8. **进入 adjudicator / authority readout**
9. **最后才做更细一层 refinement / heuristic search**

---

## 3. Step A — 冻结 shortlist

### 3.1 目标

把 re-screening 的结果从“口头上保留了几个方向”变成 machine-readable / doc-backed 的 candidate roster。

### 3.2 至少要固定的字段

- `family`
- `offload_scope`
- `resident_policy`
- `partition_strategy`
- `diag_policy`

并明确每个候选在当前阶段的角色：

- `primary candidate`
- `fallback candidate`
- `validated alternative`
- `reject`
- `explain-only`

### 3.3 为什么这是 post-screening 的第一步

因为后续 expensive 的部分——accurate-layer、closure、advisor pack——都不应对“全空间”运行，而应只对 surviving candidates 运行。

### 3.4 当前 repo 对齐对象

后续语言要与这些 artifact 保持一致：

- `primary_candidate`
- `fallback_candidate`
- `extra_promoted_candidates`
- `recommended_primary_candidates`
- `validated_alternative_candidates`

---

## 4. Step B — accurate-layer correctness validation

### 4.1 目标

确认 shortlist 中的候选不是只在 fast-layer 排序上好看，而是满足当前 frozen correctness / convergence gate。

### 4.2 当前固定的 validation 对象

#### Anchor
- `si8_pbe_nc`

#### Canonical coverage case
- `si8_pbe_uspp`

#### Candidate validation scope
- 每个 mainline shortlisted candidate

### 4.3 至少要检查的字段

- `gold_pass`
- `convergence_comparable_pass`
- `final_total_energy_ry`
- `final_converged`
- `final_residual_threshold_reached`

### 4.4 当前主脚本

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
```

---

## 5. Step C — canonical coverage

### 5.1 目标

确认推荐链不只是依赖单一 anchor，而是在第二个 canonical QE gold case 上也闭环成立。

### 5.2 当前固定 case

- `si8_pbe_uspp`

### 5.3 作用

把你从：

> 这套架构在一个 anchor 上没坏

推进到：

> 这套架构在 canonical QE gold path 上也成立

### 5.4 对下游的影响

只有 canonical coverage ready，当前 release-ready recommendation 才成立。

---

## 6. Step D — nonblocking generalization coverage

### 6.1 目标

明确当前推荐对 broader workload family 的适用边界，而不是直接用它去推翻主推荐链。

### 6.2 当前 generalization cases

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`
- `graphene_pbe_paw`
- `h2_tiny`

### 6.3 当前 frozen 规则

这一层是 **nonblocking** 的：

- mismatch 可以存在；
- 但必须进入 summary / manifest / release delivery spec；
- 用于 broader confidence / generalization discussion，而不是直接打断主推荐链。

### 6.4 当前要回答的问题

- 当前推荐对哪些 workload family 稳定？
- 哪些 mismatch 是当前阶段可接受的？
- 哪些 mismatch 未来可能升级为 blocking issue？

---

## 7. Step E — recommendation package 收口

### 7.1 目标

把 `shortlist + accurate-layer + coverage` 收成 recommendation-grade artifacts，而不是保留 raw ranking 表。

### 7.2 当前三层 package

#### `projection_review`
回答：
- 哪些 shortlisted candidates 已经具备 recommendation-grade 资格？

#### `stage_main_recommendation_package`
回答：
- 当前推荐 family 是谁？
- `recommended_primary_candidates`
- `validated_alternative_candidates`
- `best_trusted_point`
- `best_performance_candidate`

#### `stage_artifact_bundle_manifest`
回答：
- 当前 bundle 是否 ready？
- 下游 artifact 在哪里？
- canonical coverage 是否 ready？
- broader generalization 当前状态是什么？

### 7.3 这一步的意义

从“筛选结果”进入“可解释的 recommendation”。

---

## 8. Step F — release / bundle validation

### 8.1 目标

确认 recommendation package 已满足当前 repo 的 frozen contract，而不是直接把它视为最终可公开结论。

### 8.2 当前 validator

#### Release bundle validator

```bash
python3 tools/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json
```

#### Strategy / contract validator

```bash
python3 tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
```

### 8.3 当前检查的核心条件

- `stage_main_recommendation_status == projection_eligible`
- `projection_review.review_readiness == ready`
- `stage_main_recommendation_package.recommendation_status == ready`
- canonical coverage `coverage_ready == true`

---

## 9. Step G — GPU / board closure

### 9.1 目标

把当前 proxy-level / simulator-level recommendation 推向更强证据，而不是停留在当前 release-facing narrowing。

### 9.2 GPU closure

#### 当前相关入口
- `--gpu-baseline-dir`
- `--gpu-reference-dir`

#### 当前要回答的问题
- 当前推荐在 CPU/GPU/FPGA 的更完整边界下位置如何？
- 当前 GPU baseline 是 `deferred`、`reference_only` 还是已足够进入 decisive discussion？

### 9.3 Board closure

#### 当前相关工具
- `init_qe_phase1_artifact_bundle.py`
- `check_qe_phase1_artifact_contracts.py`
- `run_qe_phase1_closure_pipeline.py`

#### 当前要回答的问题
- 当前结果能否与 board observability contract 对齐？
- current proxy/result 是否能继续往 measured board evidence 推进？

---

## 10. Step H — adjudicator / authority readout

### 10.1 目标

把已经形成的 evidence surfaces 转成当前 repo 允许的 claim level，而不是直接把 DSE 排名当最终 authority。

### 10.2 当前 frozen rule

- adjudicator memo 是唯一 top-level decision authority
- DSE bundle / phase summary / recommendation package 都只是 evidence inputs

### 10.3 这一层要回答的问题

- 当前 recommendation 只允许 projection-grade 表述吗？
- 哪些 outward claims 仍然不允许？
- 缺的 closure 是 GPU、board，还是 ranking stability？

---

## 11. Step I — 最后才做更细一层 refinement

### 11.1 什么时候进入这一层

只有当：

- shortlist 已稳定
- accurate-layer 已跑通
- recommendation package 已形成
- release/closure 规则已明确

之后，才建议继续做更细一层 refinement。

### 11.2 可继续细化的方向

#### kernel mapping refinement
- `tile_npw`
- `tile_nkb`
- `tile_m`
- loop ordering
- dataflow
- buffer hierarchy

#### system knobs refinement
- cluster 数量
- DMA 通道数
- module replication
- local scheduling micro-policy
- 更细 memory architecture

#### heuristic / surrogate / Bayesian
当前 repo 也明确要求：

- 先把 rule-based + accurate-layer + coverage + release chain 做稳；
- 再考虑 heuristic pruning / surrogate / Bayesian optimization。

---

## 12. 推荐的最简 post-screening 执行链

如果要把上面所有内容压缩成最核心的版本，当前推荐这样走：

1. **冻结 shortlist**
2. **accurate-layer 复核 shortlist**
3. **补 canonical coverage**
4. **补 generalization coverage**
5. **形成 recommendation package**
6. **跑 release validators**
7. **推进 GPU / board closure**
8. **进入 adjudicator / authority readout**

---

## 13. 一句话收口

当前系统架构重新筛选之后，后面的步骤不应直接跳到实现，而应先沿着：

> **shortlist → accurate-layer → coverage → recommendation package → release validation → GPU/board closure → adjudicator authority → finer refinement**

这条 post-screening 主线推进，把当前系统推荐从“筛选结果”逐步变成“有边界、有证据等级、有 closure 状态的 recommendation”。
