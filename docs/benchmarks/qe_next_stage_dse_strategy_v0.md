# QE next-stage DSE strategy v0

## 1. 文档定位

这份文档把当前 next-stage QE-only DSE 的实际策略收口成一个稳定说明。

它主要回答四个问题：

1. 当前 DSE 到底是怎么排序、怎么升格、怎么发布的？
2. 为什么现在先用 rule-based / contract-driven 策略，而不是直接上 heuristic / AI search？
3. 当前 recommendation 到什么证据等级？
4. 未来如果要上 heuristic / AI DSE，应该在什么条件下接入？

---

## 2. 当前 DSE 的五层策略

### 2.1 快层：system-simulator 筛选

快层负责大规模 design-point 搜索，不直接承担最终 correctness 结论。

当前主结果 case：

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

当前 objective stack：

1. `time_to_convergence_s`
2. `energy_to_convergence_j`

当前显式约束 / 解释指标：

- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

每个 design point 的状态机固定为：

- `reject`
- `explain-only`
- `promotion-eligible`

然后形成 shortlist：

- `primary_candidate`
- `fallback_candidate`
- 必要时 `extra_promoted_candidates`

---

### 2.2 准层：correctness-capable accurate layer

准层不覆盖所有点，只覆盖：

- 主 anchor
- canonical coverage case
- shortlisted candidates

当前 accurate-layer anchor：

- `si8_pbe_nc`

当前 canonical coverage case：

- `si8_pbe_uspp`

准层至少检查：

- `gold_pass`
- `convergence_comparable_pass`
- `final_total_energy_ry`
- `final_converged`
- `final_residual_threshold_reached`

---

### 2.3 nonblocking generalization coverage

在 anchor + canonical coverage 之外，还维护一条非阻塞 generalization lane。

当前 generalization cases：

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`
- `graphene_pbe_paw`
- `h2_tiny`

这条 lane 的职责是：

- 给更广的 workload 外推提供证据；
- 不直接推翻当前 release-facing recommendation；
- 但必须被写入 phase summary / artifact bundle / delivery spec。

---

### 2.4 recommendation packages

当前 release-facing recommendation 不是单一 summary，而是分三层：

1. `projection_review`
   - 所有 accurate-layer-passing shortlisted candidates
2. `stage_main_recommendation_package`
   - `recommended_family`
   - `recommended_primary_candidates`
   - `validated_alternative_candidates`
   - `best_trusted_point`
   - `best_performance_candidate`
3. `stage_artifact_bundle_manifest`
   - 最顶层 release-facing 入口
   - 统一索引 phase summary / projection review / stage-main recommendation / coverage 状态

---

### 2.5 release gate

当前 `release_ready_recommendation = true` 的最低条件是：

1. `stage_main_recommendation_status == projection_eligible`
2. `projection_review.review_readiness == ready`
3. `stage_main_recommendation_package.recommendation_status == ready`
4. 若存在 `accurate_coverage`，则 `accurate_coverage_summary.coverage_ready == true`

这意味着：

- 当前 release-facing 推荐不是“单一 anchor 过了就算好”
- 而是“主链 + canonical coverage 一起过了”才算 ready

---

## 3. 当前策略为什么不是 heuristic / AI DSE

当前阶段不直接用 heuristic / AI search，不是因为它们没有潜力，而是因为：

1. **当前最大风险仍是 simulator fidelity，而不是搜索效率**
2. **当前 recommendation 必须和 gold/correctness gate 绑死**
3. **当前结论需要能直接解释给老师/报告，而不是只给黑箱最优点**

换句话说：

> 如果底层 simulator / accurate-layer 还不够稳，AI search 很容易学到 simulator 的伪规律，而不是可迁移的真实规律。

因此当前优先顺序是：

- 先把 rule-based + accurate-layer + coverage-ready 体系做稳
- 再往 heuristic / surrogate / Bayesian optimization 演进

---

## 4. 当前状态（2026-04-16）

当前这条链已经达到：

### Accurate-layer 主链
- `si8_pbe_nc`：pass
- `si8_pbe_uspp`：pass

### Generalization coverage
- `si4_pbe_uspp_small`：pass
- `graphene_pbe_uspp`：pass
- `graphene_pbe_paw`：mismatch（nonblocking）
- `h2_tiny`：pass

### Release-facing recommendation
- `recommended_family = F1`
- `projection_review`：ready
- `stage_main_recommendation_package`：ready
- `stage_artifact_bundle_manifest`：ready
- `release_ready_recommendation = true`

因此，当前系统已经不是“只有 sweep 结果”，而是：

> 一个分层、带 gold gate、带 canonical coverage、带 generalization coverage、并且可作为 release-facing artifact chain 对外发布的 DSE 策略。

---

## 5. 当前推荐应该如何解读

当前推荐并不意味着：

- “FPGA 一定优于 GPU”
- “RTL 已冻结”
- “板级功耗已经定稿”

当前它真正支持的是：

1. next-stage QE-only simulator/DSE 主线已经达到 **projection-grade**
2. 在统一 QE gold correctness gate 下，**`F1` 是当前推荐 family**
3. `F2` 在通过 accurate-layer 且进入 stage-main package 时，可作为 **validated alternative** 被保留；当前最新生成 bundle 中未出现 validated alternative
4. broader generalization 已被纳入 release-facing artifact chain，但当前最新生成 bundle 中仍存在 nonblocking mismatch，因此 `generalization_ready = false`
5. 如果 package 同时给出 `best_performance_candidate`，那表示“当前最强性能候选点”，而不是自动推翻 `best_trusted_point`

---

## 6. 未来 heuristic / AI DSE 的接入条件

只有在以下条件满足后，才建议正式引入 heuristic / AI-assisted DSE：

1. accurate-layer anchor 稳定
2. canonical coverage case 稳定
3. 至少一组 generalization cases 稳定
4. release-facing artifact chain 已可复现
5. 当前 rule-based shortlist 已不再是主要瓶颈

一旦进入下一阶段，可考虑：

- heuristic pruning
- surrogate model
- Bayesian optimization
- learned candidate proposal

但它们应当是：

- **叠加在当前 artifact chain 上**
- 而不是替换掉当前 correctness / coverage / release gate

---

## 7. 推荐的演进路线

### 当前阶段
- rule-based + contract-driven DSE
- accurate-layer / coverage / generalization / release chain 全开

### 下一阶段
- 在保持现有 gates 不变的前提下，加 heuristic pruning

### 再下一阶段
- 用已有结果训练 surrogate / Bayesian optimizer

### 最后阶段
- 才考虑更激进的 AI-driven search / proposal generation

---

## 8. 一句话总结

当前这套 DSE 策略不是“单层 sweep”，而是：

> **快层筛选 + 准层校验 + canonical coverage + generalization coverage + release-facing artifact chain**

这也是为什么当前阶段先把 rule-based 策略做扎实，比直接跳到黑箱 heuristic / AI DSE 更安全。
