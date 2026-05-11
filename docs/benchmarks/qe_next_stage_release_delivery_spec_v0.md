# QE next-stage release / delivery spec v0

## 1. 文档定位

这份文档把当前已经跑通的 next-stage QE-only 双层仿真结果，整理成一份**release-facing delivery spec**。

它不替代：

- `qe_next_stage_dse_phase_summary.json / .md`
- `qe_next_stage_projection_review.json / .md`
- `qe_next_stage_stage_main_recommendation.json / .md`
- `qe_next_stage_artifact_bundle_manifest.json / .md`

若要理解“为什么当前先用 rule-based / contract-driven DSE，而不是直接上 heuristic / AI search”，应配合阅读：

- `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`

而是回答一个更实际的问题：

> 当下一位人类或 agent 接手时，应该先看哪个 artifact、当前这条链已经到什么状态、哪些结论允许对外说、以及怎样复现。

---

## 2. 当前 release-facing artifact chain

当前推荐的读取顺序固定为：

1. **顶层入口**
   - `qe_next_stage_artifact_bundle_manifest.json / .md`
2. **阶段总览**
   - `qe_next_stage_dse_phase_summary.json / .md`
3. **所有通过 accurate-layer 的 shortlisted candidates**
   - `qe_next_stage_projection_review.json / .md`
4. **最终主推荐**
   - `qe_next_stage_stage_main_recommendation.json / .md`
5. **第二个 canonical QE gold coverage case**
   - `accurate_coverage/accurate_coverage_bundle.json / .csv`
6. **更广的 nonblocking generalization coverage**
   - `generalization_coverage/generalization_coverage_bundle.json / .csv`

读取原则：

- **先看 manifest，再看其下游 artifact**；
- 不要直接跳过 manifest 去看 recommendation package，否则很容易漏掉 coverage / readiness 的上游条件；
- advisor-facing 文本（cover memo / report / onepager）应把 manifest 作为 release-facing 顶层入口。

---

## 3. 当前 release-ready 准入条件

当前 `release_ready_recommendation = true` 的最低条件是：

1. `stage_main_recommendation_status == projection_eligible`
2. `projection_review.review_readiness == ready`
3. `stage_main_recommendation_package.recommendation_status == ready`
4. 若存在 `accurate_coverage`，则 `accurate_coverage_summary.coverage_ready == true`

也就是说，当前 release-facing 推荐并不只依赖：

- 主推荐 family 有没有通过

还依赖：

- canonical coverage case 有没有通过

当前 `generalization_coverage` 默认仍是 **nonblocking**：

- 它不会直接推翻当前已经 ready 的主推荐链；
- 但它会被写入 phase summary 和顶层 bundle manifest，用于 broader confidence / generalization 讨论。

---

## 4. 当前已闭环的 canonical QE gold cases

### 4.1 Accurate-layer anchor
- `si8_pbe_nc`

### 4.2 Canonical coverage case
- `si8_pbe_uspp`

当前这两个 case 都已经在现有 simulator / accurate-layer 路径下闭环通过，因此：

- `F1`、`F2` 在这两个 canonical QE gold case 上都满足
  - `gold_pass = true`
  - `convergence_comparable_pass = true`

这为当前 release-facing recommendation 提供了比“单一 anchor 通过”更强的支撑。

---

## 5. 当前 recommendation 的正确解读

当前 release-facing recommendation 不是：

- “FPGA 一定优于 GPU”
- “RTL 已冻结”
- “板级功耗已经定稿”

当前它真正支持的是：

1. next-stage simulator/DSE 主线已经达到 **projection-grade**
2. 在统一 QE gold correctness gate 下，**`F1` 是当前推荐 family**
3. `F2` 在通过 accurate-layer 且进入 package 时，可作为 **validated alternative** 保留；当前最新生成 bundle 中它未进入主推荐包
4. canonical coverage 已不再只停留在 `si8_pbe_nc`，还包括 `si8_pbe_uspp`
5. 若 `stage_main_recommendation_package` 同时给出 `best_performance_candidate`，它应被理解为：
   - 当前已验证候选里的最强性能观察点
   - **不自动等于**当前最可信的对外主推荐

---

## 6. 当前 artifact 各自负责什么

### 6.1 `qe_next_stage_dse_phase_summary`
作用：
- 完整描述 fast layer / accurate layer / public recommendation / stage gate

适合回答：
- 现在 phase 到哪一步了？
- `projection_eligible` 是怎么来的？
- fast-layer shortlist 和 accurate-layer gate 分别是什么状态？

### 6.2 `qe_next_stage_projection_review`
作用：
- 汇总所有 accurate-layer-passing shortlisted candidates

适合回答：
- 哪些 shortlisted candidates 已经具备 recommendation-grade 资格？

### 6.3 `qe_next_stage_stage_main_recommendation`
作用：
- 收口最终 recommended family
- 给出 `recommended_primary_candidates`
- 给出 `validated_alternative_candidates`
- 给出 `best_trusted_point`
- 给出 `best_performance_candidate`

适合回答：
- 对外主推荐应该怎么说？
- 为什么是 `F1`？
- 为什么 `F2` 不是主推荐但仍被保留？
- 当前最可信的推荐点和当前观测到的最强性能点是不是同一个？

### 6.4 `qe_next_stage_artifact_bundle_manifest`
作用：
- 作为统一 release-facing 顶层索引
- 汇总 readiness / artifact paths / coverage summary / generalization summary

适合回答：
- 当前这套结果能不能直接拿去做 release-facing 汇报？
- 下游 artifact 分别在哪里？
- canonical coverage 有没有一起通过？
- broader generalization 现在是什么状态？

---

## 7. 推荐的对外交付顺序

若当前要做 advisor-facing 交付，建议按下面顺序出包：

1. `qe_next_stage_artifact_bundle_manifest`
2. `qe_next_stage_stage_main_recommendation`
3. `qe_next_stage_projection_review`
4. `qe_next_stage_dse_phase_summary`
5. advisor-facing:
   - cover memo
   - report
   - executive summary one-pager

原因：

- 先用 manifest 判断 bundle 是否 ready；
- 再用 stage-main package 决定首页 recommendation；
- 然后用 projection review 和 phase summary 做展开解释。

### 7.1 `best_trusted_point` 与 `best_performance_candidate` 的读取规则

从当前版本起，`qe_next_stage_stage_main_recommendation` 至少允许同时表达两类对象：

1. **`best_trusted_point`**
   - 对外主推荐的可信入口
   - 当前通常仍与 `recommended_family` 同步
2. **`best_performance_candidate`**
   - 当前已验证候选中性能最强的点
   - 必须带 machine-readable `signature_id`
   - 以及 `family / diag_policy / offload_scope / resident_policy / partition_strategy`

默认读取规则是：

- 对外第一页默认先看 `best_trusted_point`
- 如果要讨论“更激进、但仍未必是主推荐”的性能峰值，再看 `best_performance_candidate`

---

## 8. 默认本地复现命令

### 8.1 默认构建

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

### 8.2 默认 execute-model phase run

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir /tmp/qe_next_stage_release \
  --execute-model
```

运行成功后，应至少看到：

- `qe_next_stage_dse_phase_summary.json / .md`
- `qe_next_stage_projection_review.json / .md`
- `qe_next_stage_stage_main_recommendation.json / .md`
- `qe_next_stage_artifact_bundle_manifest.json / .md`

若当前 release-facing 链保持闭环，则 manifest 里应看到：

- `bundle_readiness = ready`
- `release_ready_recommendation = true`

---

## 9. 当前交付状态（2026-04-16）

当前这条链已经达到：

- `si8_pbe_nc` accurate-layer pass
- `si8_pbe_uspp` accurate coverage pass
- `si4_pbe_uspp_small` generalization pass
- `graphene_pbe_uspp` generalization pass
- `graphene_pbe_paw` generalization mismatch（nonblocking）
- `h2_tiny` generalization pass
- `projection_review` ready
- `stage_main_recommendation_package` ready
- `stage_artifact_bundle_manifest` ready
- `release_ready_recommendation = true`
- 当前 `recommended_family = F1`

并且当前 `generalization_coverage` 已经达到：

- `generalization_workload_count = 4`
- `generalization_pass_count = 3`
- `generalization_mismatch_count = 1`
- `generalization_ready = false`

因此，这份 delivery spec 的当前作用不是“声明工作已彻底结束”，而是：

- 把现在已经能交付的结果收口成一个**稳定、可读、可复现**的 release-facing 读取规范；
- 给后续继续扩 case / 扩 search / 接 board-facing artifact 留出稳定入口。

---

## 10. 后续扩展方向

如果继续扩而不是停在当前版本，优先级建议为：

1. 再扩一个新的 coverage / generalization case
2. 再把 board-facing / GPU baseline artifact 接入同一 release-facing 入口
3. 最后才考虑 heuristic / AI-assisted DSE 升级

原因：

- 当前 rule-based + accurate-layer + coverage-ready 链已经很稳；
- 在这个基础上扩 coverage，比直接跳到黑箱搜索更安全。
