# QE algorithm rewrite manifest contract（v0，2026-04-14）

## 0. 目的与来源

本文对应 `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md` 里的：

- `WS0 / M0.6`：冻结 `CPU + GPU` baseline policy，包括 shared algorithmic rewrites；
- `WS3 / M3.1`：在 family / policy / rewrite knob sweep 中，明确哪些 rewrite 可以进入 decisive 候选；
- `WS4 / M4.3`：要求对每一条 algorithmic rewrite 记录 GPU applicability；
- `WS6 / M6.3`：要求在终局结果中把 algorithmic rewrite benefit 与 runtime/orchestration benefit、mapping benefit 区分开。

本文不是新算法 proposal，也不是性能结果报告；它的作用是把 **phase-1 QE-only CPU+FPGA thesis** 下，什么叫“可计入比较的 rewrite”、它如何影响 `CPU + GPU` baseline 资格、以及它如何进入最终 decisive shell comparison，全部提前冻结。

本文直接基于：

- `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_shell_level_comparison_metrics_contract_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
- `docs/architecture/qe_system_optimized_delta_20260413.md`
- `model/qe_band_solver_model/README.md`

与本文配套的 machine-readable template：

- `docs/benchmarks/qe_algorithm_rewrite_manifest_template_v0.json`

与本文直接相关的 validator / 执行入口：

- `docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json`：baseline row 需要回填 `algorithm_rewrite_manifest_id`；
- `docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`：DSE/bootstrap bundle 会携带 `algorithm_rewrite_manifest_id` 与 contract id；
- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`：结果 bundle 的 machine-readable schema。

---

## 1. phase-1 rewrite fairness 总原则

phase 1 的终局 thesis 仍然是：

> 在固定 workload group 上，`CPU + FPGA` 相对 `CPU + GPU`，在相同 correctness / tolerance contract 下，实现 **>2x end-to-end time-to-solution**，且 **whole-node power 更低**。

因此 rewrite policy 必须满足两条总原则：

1. **不能把共享算法收益只记在 FPGA 头上。**  
   如果某个 rewrite 在数学语义和工程实现上也可用于 `CPU + GPU`，则 `CPU + GPU` baseline 必须有权采用。

2. **不能把 FPGA-only architectural trick 伪装成共享算法改写。**  
   依赖 resident on-chip objects、device-private schedule、FPGA-only dataflow contract 的收益，必须从共享 rewrite 收益中拆出来。

因此：

> phase-1 的 decisive `CPU + GPU` baseline，必须在同一 correctness/tolerance contract 下，拿到 **它有资格拿到的全部 shared rewrites**；而 `CPU + FPGA` 的额外优势，只能来自确实需要 FPGA architectural state 的部分。

---

## 2. rewrite manifest 的作用范围

每一个可能影响 end-to-end shell 时间、功耗、convergence comparability、或 GPU baseline 资格的 rewrite，都必须进入统一 manifest。

manifest 覆盖三类对象：

- algorithm-level rewrites
- runtime / data-layout / batching / scheduling rewrites
- FPGA-only architecture-coupled rewrites

以下改动**必须入表**：

- 改写 `QE` 中 band / subspace / projector 相关计算路径的算法组织；
- 更改数据布局、batching、resident policy、host/device task slicing；
- 引入新的 fallback policy、reorder policy、orchestration rule；
- 影响 `CPU + GPU` 是否可用同一数学/工程路径的任何修改。

以下改动**可不入表**，但需在 PR / note 中说明：

- 纯注释或文档文字修订；
- 不影响 shell accounting、correctness、fairness 或 workload admission 的日志格式微调；
- 完全离线、且不影响被测 runtime path 的开发辅助脚本。

---

## 3. rewrite 分类与处理规则

manifest 的一级分类固定为下表三类：

| `rewrite_class` | 含义 | GPU 处理规则 | 对最终比较的默认要求 |
| --- | --- | --- | --- |
| `shared_semantic` | 改写算法/数据流语义，但不依赖 FPGA-only architectural state | `CPU + GPU` baseline **必须允许**采用，只要仍满足 correctness/tolerance contract | 若 GPU 未采用，case 不能进入 decisive final table |
| `shared_engineering` | 工程性重排：layout、batching、runtime scheduling、launch grouping、buffering 等 | `CPU + GPU` baseline **必须允许**采用，只要工程上可实现且不会引入额外语义改变 | 若 GPU 未采用或未评估 applicability，case 不能进入 decisive final table |
| `fpga_specific_arch` | 依赖 FPGA-only resident objects、private schedule、board-local memory/dataflow、device contract 的改写 | GPU baseline 可标记为 not applicable，但必须说明原因 | 可作为 FPGA 独有收益计入，但必须在最终结果中做 ablation 或 delta 说明 |

### 3.1 `shared_semantic`

这类 rewrite 的典型例子包括：

- 不改变最终物理收敛标准，但改变 band/subspace 求解顺序或重用策略；
- 可在 GPU 上同样实现的分块、投影、reduction 组织；
- 对数值容差合同无破坏的算法级重排。

规则：

- 若 `gpu_applicable = yes`，则 GPU baseline **必须**尝试采用；
- 若 GPU 未采用，必须给出工程不可实现或 correctness 失配的证据；
- 否则，该 rewrite 带来的收益不能独占记给 FPGA。

### 3.2 `shared_engineering`

这类 rewrite 的典型例子包括：

- host/device launch grouping；
- batch sizing；
- layout transform 下沉；
- runtime queueing / overlap policy；
- 不依赖 FPGA-only state 的 buffering / prefetch / reorder。

规则：

- 默认视为 GPU 可竞争采用；
- 只有在 board/device contract 真正要求 FPGA-private state 时，才能转入 `fpga_specific_arch`；
- “实现起来麻烦”不是拒绝 GPU applicability 的充分理由。

### 3.3 `fpga_specific_arch`

这类 rewrite 的典型例子包括：

- 依赖 FPGA resident projector / resident descriptor objects；
- 依赖 board-local memory topology 的 schedule；
- 依赖 FPGA-private pipeline / streaming / control object 的 execution contract；
- 依赖 phase-1 public contract 中 `CPU + FPGA` 独有 control/dataflow wiring 的改写。

规则：

- 允许 `gpu_applicable = no`；
- 但必须明确到底是哪一个 architectural feature 使其 GPU 不适用；
- 必须在最终结果或中间 candidate review 中提供 ablation、delta，或“without this rewrite”对照。

---

## 4. 每条 rewrite 的必填字段

每一条 rewrite 至少要记录下列字段：

| 字段 | 含义 |
| --- | --- |
| `rewrite_id` | 稳定 ID，建议 `RW-<family>-<nnn>` |
| `title` | 简短标题 |
| `rewrite_class` | `shared_semantic` / `shared_engineering` / `fpga_specific_arch` |
| `scope` | 影响的 QE shell stage / subsystem / file / runtime object |
| `description` | 改写内容摘要 |
| `motivation` | 为什么需要这条 rewrite |
| `changes_algorithm_semantics` | `yes/no/qualified` |
| `correctness_contract_impact` | `none / bounded / requires-review / incompatible` |
| `tolerance_contract_note` | 对 tolerance schema、gold contract、convergence comparability 的说明 |
| `gpu_applicable` | `yes / no / unclear` |
| `gpu_applicability_basis` | 为什么可/不可/暂不明确 |
| `gpu_enabled_in_baseline` | `yes / no / deferred` |
| `gpu_enablement_note` | GPU baseline 是否已经采用、为何未采用 |
| `fpga_required_arch_feature` | 若为 FPGA-only，依赖的 resident/schedule/memory/control feature |
| `expected_benefit_axis` | `time / power / size / convergence-stability / mixed` |
| `expected_benefit_note` | 预期收益来自哪里 |
| `ablation_required` | `yes/no` |
| `admission_risk` | `none / medium / high`，表示它对 decisive baseline eligibility 的风险 |
| `evidence_note` | 当前证据：spec、simulator、board、analysis、or none |
| `review_status` | `draft / accepted / conditionally-accepted / rejected` |
| `owner_note` | 谁负责维护这条 rewrite 的说明与验证 |

### 4.1 推荐附加字段

若 rewrite 将进入 thesis-counted workload，建议额外记录：

- `affected_workload_ids`
- `affected_family_ids`（`F1/F2/F3`）
- `simulator_hook_ids`
- `board_observability_rows`
- `fallback_behavior`
- `shared_rewrite_dependency_ids`
- `claim_dependency_ids`

---

## 5. review 与升级规则

### 5.1 录入时机

以下任一情况发生时，rewrite 必须先入 manifest，才能进入 decisive candidate 讨论：

- 被 DSE 当作一个 design knob；
- 被 claim 为 end-to-end shell speedup 来源；
- 会改变 `CPU + GPU` baseline eligibility；
- 会影响 correctness/tolerance/comparability gate；
- 会改变 whole-node power accounting path；
- 会改变 simulator↔board observability 对齐方式。

### 5.2 review 层级

每条 rewrite 至少经历以下检查：

1. **contract review**  
   检查字段是否齐全，分类是否正确，GPU applicability 是否有依据。

2. **fairness review**  
   检查是否把共享收益错误归到 FPGA-only；检查 GPU baseline 是否被不当地限制。

3. **correctness/comparability review**  
   检查是否仍满足 `qe_fpga_workload_group_and_correctness_contract_v0.md` 中的 same-correctness / same-tolerance / convergence-comparable gate。

4. **observability review**  
   若 rewrite 影响 shell time、DMA、fallback、power、orchestration 或 board-visible行为，必须同步补 observability mapping。

### 5.3 状态流转

推荐状态流转：

- `draft`
- `accepted`
- `conditionally-accepted`
- `rejected`

规则：

- `conditionally-accepted` 只能用于“方向允许，但 GPU applicability / correctness / observability 仍缺证据”的情况；
- 凡是 `gpu_applicable = unclear` 且 `review_status != rejected` 的 rewrite，默认不能支撑 decisive final comparison；
- `rejected` rewrite 不能进入 thesis-counted aggregate table。

---

## 6. GPU applicability handling

### 6.1 基本处理逻辑

GPU applicability 不是一个叙事字段，而是一个 **baseline eligibility gate**。

决策顺序固定如下：

1. 这条 rewrite 是否改变 correctness/tolerance contract？
2. 若不改变，它在数学语义上是否也适用于 GPU？
3. 若适用，它在 phase-1 single-node GPU baseline 上是否工程可实现？
4. 若可实现，GPU baseline 是否已经启用？
5. 若未启用，是否有书面证据说明这条 GPU path 不满足 correctness、observability、或 measurement boundary？

### 6.2 `gpu_applicable = yes`

必须满足：

- `gpu_enabled_in_baseline = yes`，或
- `gpu_enabled_in_baseline = deferred` 但该 case 只能算 `candidate-only`，不能进 decisive thesis table。

### 6.3 `gpu_applicable = no`

必须写明：

- 具体依赖的 `fpga_required_arch_feature`；
- 为什么它不是“共享工程优化的另一种写法”；
- 为什么 GPU 无法在相同 shell boundary 与 correctness contract 下获得同类收益。

### 6.4 `gpu_applicable = unclear`

处理规则最严格：

- 默认视为 fairness unresolved；
- 不得进入 decisive final comparison；
- 只能用于 exploratory note、conditional family ranking、或未完成的 design-space branch。

---

## 7. manifest 如何影响 decisive CPU+GPU baseline eligibility

### 7.1 case 进入最终比较表的前提

一个 workload case 要进入最终 `CPU + GPU` vs `CPU + FPGA` decisive table，除 correctness/tolerance/convergence-comparable gate 外，还必须满足：

1. 该 case 的全部 `shared_semantic` rewrites 均已有 GPU applicability verdict；
2. 其中 `gpu_applicable = yes` 的 rewrite，GPU baseline 已启用，或已被明确标注为该 case 仍不具 decisive 资格；
3. 所有 `shared_engineering` rewrites 都已给出 GPU applicability verdict；
4. 所有 `fpga_specific_arch` rewrites 都已写明 `fpga_required_arch_feature`，并在最终结果中提供 ablation/delta 说明路径；
5. 不存在 `review_status = draft` 且同时会显著影响 shell-level end-to-end time 的关键 rewrite。

### 7.2 decisive baseline 资格判定

若某 case 存在以下任一情况，则它只能是 `candidate-only` 或 `gate-only`，**不能**进入 decisive final table：

- `shared_semantic` rewrite 可用于 GPU，但 GPU baseline 未启用；
- `shared_engineering` rewrite 的 GPU applicability 未定；
- 某条关键 rewrite 的 `review_status = conditionally-accepted` 且 unresolved 原因与 fairness/correctness/observability 直接相关；
- rewrite 改变了 correctness/tolerance/comparability，但未完成重新 admission；
- rewrite 的收益无法通过 simulator/board observability rows 拆解与对账。

### 7.3 与 fastest-GPU rule 的关系

本 manifest 合同与 fairness/power contract 的 decisive GPU baseline 规则联动：

> 在同一 correctness/tolerance contract、同一 shared-rewrite policy 下，**所有已测且可接受的 GPU baseline 中最快的那一条**，才是 decisive `CPU + GPU` baseline。

因此 manifest 的作用是先冻结“GPU 允许用哪些 rewrite”，再去比较 GPU 模式；而不是先测到一条弱 GPU，再倒推 rewrite policy。

---

## 8. 与 F1 / F2 / F3 family ladder 的关系

### 8.1 F1 / F2

phase 1 中，`F1/F2` 是 primary decision-grade families。

因此：

- 对 `F1/F2` 生效的 rewrite，必须优先完成 manifest 录入与 review；
- 影响 `F1/F2` 排名的 shared rewrites，必须优先完成 GPU applicability 判定；
- 若 `F1/F2` 的 top candidate 依赖 unresolved rewrite，则 `ranking_stability_status` 不能记为 `pass`。

### 8.2 F3

`F3` 仍然是 conditional / exploratory。

因此：

- `F3` 相关 rewrite 可暂时以 exploratory manifest entry 存在；
- 但不能用 `F3` unresolved rewrite 的结果去支撑 phase-1 decisive thesis；
- 如果 `F3` 进入主候选，必须先完成与 `F1/F2` 同等级别的 fairness/correctness/observability 审核。

---

## 9. 建议的 manifest 表头模板

建议至少维护一张 markdown / csv / json 可互转的清单，表头如下：

| rewrite_id | title | rewrite_class | scope | changes_algorithm_semantics | correctness_contract_impact | gpu_applicable | gpu_enabled_in_baseline | fpga_required_arch_feature | ablation_required | review_status | admission_risk | evidence_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

若进入 thesis-counted candidate，建议追加：

| affected_workload_ids | affected_family_ids | board_observability_rows | claim_dependency_ids | owner_note |
| --- | --- | --- | --- | --- |

---

## 10. phase-1 明确禁止的做法

以下做法一律视为合同违规：

1. 明知某 rewrite 可帮助 GPU，却故意不让 GPU baseline 使用；
2. 把 `shared_semantic` 与 `fpga_specific_arch` 混写成一个不可拆分“大优化”；
3. 不记录 GPU applicability，就直接把某条 rewrite 的收益算进 FPGA decisive win；
4. 用 unresolved rewrite 支撑 thesis-counted workload 的 decisive final table；
5. 在未补 observability mapping 的情况下，把 rewrite 当作 shell-level speedup 的主证据；
6. 因为 GPU 路径尚未实现完毕，就把 `deferred` 当成“GPU 不适用”；
7. 让 rewrite 绕开 same-correctness / same-tolerance / convergence-comparable contract。

---

## 11. phase-1 最低执行要求

在 phase-1 里，若要声称某组结果具备 decisive CPU+GPU vs CPU+FPGA 资格，则至少要满足：

- 有一份最新的 algorithm rewrite manifest；
- 每一条 thesis-relevant rewrite 都有稳定 `rewrite_id`；
- 全部 `shared_semantic` / `shared_engineering` rewrites 的 GPU applicability 已判定；
- GPU baseline 已采用所有应采用的 shared rewrites，或明确因此失去 decisive 资格；
- FPGA-only rewrites 已写清 architectural dependency，并在最终报告中有 ablation/delta 路径；
- manifest 与 workload-group correctness contract、fairness/power contract、observability contract 三者一致。

只有在以上条件都满足时，相关 case / workload group 才能进入最终 thesis-counted end-to-end comparison。
