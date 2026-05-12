# QE-only `CPU + FPGA` thesis 工作负载组与正确性/容差合同（v0，2026-04-13）

## 0. 目的

本文为批准后的 QE-only `CPU + FPGA` thesis plan 冻结两件事：

1. **phase-1 候选 workload-group** 到底由哪些 QE case 组成；
2. **same-correctness / same-tolerance** 的准入规则到底是什么，哪些 case 可以进入最终 `CPU + GPU` vs `CPU + FPGA` 的 end-to-end `time-to-solution` 比较，哪些只能先作为 gate / supporting evidence。

对应计划：

- `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`

它继承但不重复定义已有的 QE gold artifacts：

- `docs/benchmarks/qe_gold_correctness_contract_v0.md`
- `docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`

结论是：

> `qe_gold_correctness_contract_v0.md` 冻结的是**单 case 数值 gate**；
> 本文冻结的是**哪些 case 构成 thesis workload-group，以及这些 case 在什么条件下才有资格进入最终 end-to-end 胜负表。**

## 1. Grounding sources

本文只依赖当前仓库里已经落地的计划与 benchmark 证据：

- 批准计划：`.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`
- 当前 shell-level 状态：`docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`
- 系统 workload 复核：`docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_system_workload_revalidation_report_20260321.md`
- QE gold correctness contract：`docs/benchmarks/qe_gold_correctness_contract_v0.md`
- QE tolerance schema：`docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`

## 2. 冻结结论（v0）

### 2.1 Phase-1 thesis object

phase-1 的对象固定为：

- **QE-only**
- **single CPU + single FPGA**
- 以 **完整 QE shell closure** 为比较对象
- 主胜负指标是 **end-to-end `time-to-solution`**
- 次胜负指标是 **whole-node power**

### 2.2 Workload-group 不是单个 gold case，也不是任意挑 case

phase-1 的最终 thesis 不能只靠：

- `si8_pbe_nc` 一条 convergence anchor，或
- 单个 hand-picked `Si` / `graphene` / `Au slab` case

来宣称成立。

最终工作负载必须是一个**冻结后的 workload-group**，并且所有被计入最终胜负表的 case 都必须先通过本文定义的准入 gate。

### 2.3 本文采用三层 case 状态

| 状态 | 含义 | 是否允许进入最终 `>2x` 表 |
| --- | --- | --- |
| `thesis_counted` | 数值 gate、convergence comparability、fairness contract 都闭合 | 允许 |
| `gate_only` | 可用于正确性 gate / 软件路径闭环 / 校准，但还不能做最终 end-to-end 胜负统计 | 不允许 |
| `pending` | case 本身重要，但当前缺 baseline / convergence / fairness / power 某一环 | 不允许 |

## 3. 候选 workload-group 组成（v0）

## 3.1 v0 case roster

### A. Correctness / convergence anchor lane

| case_id | 当前角色 | 为什么必须保留 | 当前状态 |
| --- | --- | --- | --- |
| `si8_pbe_nc` | **first-priority convergence anchor** | 已经是 `qe_gold_correctness_contract_v0.md` 冻结的首要收敛 case；`c_bands share = 76.7%`、`generalized ratio = 89.4%`，代表 phase-1 当前最稳的 Davidson/generalized 主线 | `gate_only` |
| `si8_pbe_uspp` | canonical coverage case | 已在 QE gold canonical matrix v0 中冻结；与 `si8_pbe_nc` 组成同一 Si family 的 pseudo 对照，也在 shell aggregate 状态文档中有真实 CPU aggregate | `gate_only` |

这两项回答的是：

- 这套 `CPU + FPGA` 路线能不能先在 QE gold lane 上收敛到一个稳定的 correctness contract；
- 同一 Si family 下，`NC` 与 `USPP` 是否会对主路径 / projector 结构 / comparability 造成不同约束。

### B. Phase-1 thesis performance candidate lane

| case_id | 当前角色 | 纳入原因 | 当前直接证据 | 当前状态 |
| --- | --- | --- | --- | --- |
| `si4_pbe_uspp_small` | small-Si bring-up / sanity proxy | 已真实跑通；可作为最便宜的 full-shell bring-up case；适合先把 `CPU + FPGA` shell closure、timing accounting 与 power boundary 跑顺 | status 文档已给出 `24.29 ms` 平均 `c_bands` episode、`50.00 ms` 平均 `SCF iteration`，并在 `7` 次 SCF 后收敛 | `pending` → 优先转 `thesis_counted` |
| `si8_pbe_uspp` | canonical Si performance case | 与现有 gold matrix 重叠；是 phase-1 必须保留的 canonical Si case；比 `small-Si` 更接近真正 thesis 叙事 | status 文档已给出 `58.75 ms` 平均 `c_bands` episode、`113.75 ms` 平均 `SCF iteration` | `gate_only` |
| `graphene_pbe_uspp` | 2D / channel-style proxy | revalidation 报告显示其 `c_bands share = 64.3%`，dominant solver 仍是 Davidson/generalized；与 Si family 形成不同 `npw / nkb / block shape` 组合 | status 文档已给出 `45.00 ms` 平均 `c_bands` episode、`68.33 ms` 平均 `SCF iteration`，并在 `6` 次 SCF 后收敛 | `pending` → 优先转 `thesis_counted` |
| `au_slab_subspace` | interface / slab stress | 状态文档中的 `CPU only` envelope 显示它对 `c_bands` 主路径特别敏感；适合承接“大系统 / 接触界面”故事 | status 文档已给出 `1136.00 ms` 平均 `c_bands` episode、`2217.50 ms` 平均 `SCF iteration`；且 `c_bands -> inf` 的 SCF upper bound 为 `2.78x` | `pending` |
| `sic32_subspace` | larger system / device-relevant stress | 当前所有已抽 shell aggregate case 里，系统级 `c_bands` 敏感度最高之一；适合承接 “bigger system after faster system” 的第二叙事 | status 文档已给出 `2335.00 ms` 平均 `c_bands` episode、`3457.50 ms` 平均 `SCF iteration`；且 `c_bands -> inf` 的 SCF upper bound 为 `3.08x` | `pending` |

## 3.2 为什么 v0 先不把所有 rerun case 都算进 thesis group

以下 case 暂不进入 phase-1 thesis-counted group：

| case / family | 暂不纳入原因 |
| --- | --- |
| `bn32_pbe_uspp` | 系统 workload 复核表明它很有价值，尤其适合作 projector-heavy stress；但当前 shell comparison 状态文档还没有把它纳入同一批真实 shell aggregate / speedup envelope 抽取 |
| `si8_pbe0_uspp`、`bn32_pbe0_uspp` | 这些 case 说明 functional 可能把主路径切到 `CG`，对长期 full-stack 很重要；但 phase-1 当前的稳定对象仍然是 Davidson/generalized 主线上的 decision-grade proof，不宜把 CG 扩展和主 thesis-counted group 同时冻结 |
| `benzene` / `Fe` | 当前更适合作 auxiliary stress / historical compatibility case；其中 `benzene` 在 rerun 中还出现 `exit=82`，不适合进入第一版 decisive workload-group |

因此，v0 的冻结策略是：

- **先把 QE-only phase-1 thesis group 锁在 Davidson/generalized 主线更稳的 case 上；**
- **再把 `CG` / PBE0 / projector-heavy 扩展作为后续 admission item，而不是当前 decisive group 的一部分。**

## 4. Same-correctness / same-tolerance 合同

## 4.1 所有 baseline 都继承同一个 QE gold schema

对于任何进入 `CPU + GPU` vs `CPU + FPGA` 最终表的 case，必须继承：

- `qe_tolerance_schema_id = qe_gold_numerical_tolerance_schema_v0`
- `qe_baseline_id = <case_id>_qe_gold`（或等价的冻结 baseline ID）

并通过已有 helper 路径归一化和比较：

- `tools/benchmarks/normalize_qe_gold_baseline.py`
- `tools/benchmarks/compare_qe_gold_correctness.py`

## 4.2 v0 required fields

必须沿用 `qe_gold_correctness_contract_v0.md` 的 v0 强制字段：

| 字段 | 规则 |
| --- | --- |
| `final_total_energy_ry` | `abs_tol = 1e-8 Ry`, `rel_tol = 1e-10`, `scale_floor = 1.0` |
| `final_converged` | exact match |
| `final_residual_threshold_reached` | exact match |
| `scf_iterations` | report-only；解释性字段，不单独触发 v0 gold fail |

### 4.3 v0 interpretation

这意味着：

- **same-correctness** 首先不是“看起来差不多”，而是要先通过同一个 QE gold schema；
- `final_total_energy_ry`、`final_converged`、`final_residual_threshold_reached` 是 phase-1 目前唯一冻结的强制字段；
- `scf_iterations` 必须上报，但**不会**在 v0 中单独导致 `gold_pass = no`。

## 5. 什么叫 convergence-comparable

为了支持真正的 end-to-end `time-to-solution` 论文叙事，本文在 gold pass 之上，再加一层 **convergence comparability**。

## 5.1 Gold-correctness pass

单个 case 满足下面三条时，记为 `gold_correctness_pass`：

1. baseline 和 candidate 都存在；
2. `final_total_energy_ry`、`final_converged`、`final_residual_threshold_reached` 全部通过 v0 schema；
3. 没有 `baseline_missing` / `candidate_missing` / `model_error` / `compare_error` 一类 infrastructure failure。

这一步只回答：

> candidate 有没有在冻结后的 QE numerical contract 下对齐 baseline。

它**不自动等于**这个 case 已经可以进入最终 `time-to-solution` 主表。

## 5.2 Convergence-comparable pass

单个 case 只有同时满足下面条件，才记为 `convergence_comparable_pass`：

1. 已经 `gold_correctness_pass = yes`；
2. baseline 与 candidate 使用同一个 `workload_id`、同一个 QE shell 输入语义；
3. baseline 与 candidate 使用同一个 stopping contract：
   - 同一 `SCF accuracy / residual threshold`
   - 同一 convergence 判据
   - 同一 shell accounting boundary
4. **baseline 与 candidate 最终都必须 `final_converged = true`**；
5. 如果存在 algorithmic rewrite，则必须明确记录其对 GPU baseline 是否也适用；未闭合前只能记为 `gate_only`；
6. 如果 `scf_iterations` 漂移，允许继续算 `convergence_comparable_pass`，但必须在主表中显式披露 `baseline_iterations` 与 `candidate_iterations`。

### 5.3 这条规则的直接后果

- **“两边都没收敛，但字段刚好一致”**：可以是 `gold_correctness_pass`，但不能是 `convergence_comparable_pass`；
- **“收敛了，但 candidate 偷偷放松 residual 阈值”**：直接 fail；
- **“candidate 因算法协同而迭代更少，但最终能量与 residual 状态都在冻结合同里通过”**：允许通过，但必须把 `scf_iterations` 漂移记入解释表；
- **“candidate 用了能帮助 GPU 的 rewrite，但 GPU baseline 没同步采用”**：fairness 未闭合，不能进入 thesis-counted 表。

## 6. Case admission rules

## 6.1 单 case admission checklist

单个 case 进入最终 workload-group speedup 表，必须全部满足：

- [ ] 已有 trace-backed case identity，不是 synthetic toy
- [ ] 已有 canonical QE baseline JSON 或等价的 normalized gold baseline
- [ ] 已有 CPU-only shell aggregate 或 end-to-end reference
- [ ] `gold_correctness_pass = yes`
- [ ] `convergence_comparable_pass = yes`
- [ ] algorithmic rewrite fairness 已闭合（`N/A` 或 shared-rewrite on GPU 已明确）
- [ ] whole-node power 口径可落在冻结后的同一边界内

只有这样，这个 case 才能从 `pending` / `gate_only` 升到 `thesis_counted`。

## 6.2 当前 v0 admission judgment

按当前仓库证据，建议这样解释当前状态：

| case_id | 当前判断 | 备注 |
| --- | --- | --- |
| `si8_pbe_nc` | `gate_only` | correctness/convergence anchor；还需要把 shell aggregate / power / GPU baseline 一起并到最终主表口径 |
| `si8_pbe_uspp` | `gate_only` | 已在 canonical gold matrix 中，但当前 CPU shell aggregate 仍未形成 final thesis-ready convergence row |
| `si4_pbe_uspp_small` | `pending`（优先 admission） | 已有收敛 CPU aggregate，最适合先闭合 `CPU + FPGA` shell closure 与 comparability contract |
| `graphene_pbe_uspp` | `pending`（优先 admission） | 已有收敛 CPU aggregate，且能提供不同于 Si family 的 generalized block pattern |
| `au_slab_subspace` | `pending` | 故事价值高，但当前更适合作 scale-sensitive stress；还不能直接算进最终 time-to-solution group |
| `sic32_subspace` | `pending` | 同上，优先保留为大系统候选；需要补 convergence closure 与 fairness closure |

## 6.3 第一批 `thesis_counted` 候选的冻结晋级路径

根据批准计划的 phase-1 范围和当前 shell comparison status，v0 明确规定：

- 第一批要从 `pending` 晋级成 `thesis_counted` 的 case，固定为：
  - `si4_pbe_uspp_small`
  - `graphene_pbe_uspp`
- 在这两个 case 还没有闭合前，`au_slab_subspace`、`sic32_subspace` 只能继续作为 scale / future-story lane，不能替代它们提前进入 decisive group。

### 6.3.1 晋级检查表

`si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 只有在下面项目全部闭合后，才允许从 `pending` 升到 `thesis_counted`：

- [ ] 生成各自的 canonical / normalized QE gold baseline artifact，并能被 `compare_qe_gold_correctness.py` 直接消费
- [ ] 生成 `CPU + FPGA` 侧同一 shell accounting boundary 的 end-to-end run artifact
- [ ] 生成 `CPU + GPU` 侧同一 shell accounting boundary 的 end-to-end run artifact；若当前仍是 deferred，则不得提前晋级
- [ ] `gold_correctness_pass = yes`
- [ ] `convergence_comparable_pass = yes`
- [ ] whole-node power boundary 已闭合到同一 node-level ledger
- [ ] algorithmic rewrite policy 已写明 `algorithm_rewrite_manifest_id`，并明确该 rewrite 是否已同步允许在 GPU baseline 上使用
- [ ] observability contract 所要求的 join key 已齐全，能回链到 simulator / board / shell aggregate 三侧

### 6.3.2 phase-1 晋级顺序

本文把 phase-1 的 decisive lane 固定为以下顺序：

1. `si4_pbe_uspp_small` —— 先闭合最便宜的 QE full-shell bring-up 与 fairness loop；
2. `graphene_pbe_uspp` —— 再闭合与 Si family 明显不同的 2D/generalized block 形状；
3. `si8_pbe_uspp` —— 作为 canonical Si case 补进第三个 decisive row；
4. `au_slab_subspace`、`sic32_subspace` —— 只在前三者至少形成一个稳定 thesis-counted 子组后，再讨论是否升级。

这条顺序回答的是：

> phase-1 不是“谁先跑出大 speedup 就先算谁”，而是先把 **small-Si + graphene** 这两个最能闭合 bring-up / fairness / shape-diversity 的 case 变成第一批 decisive rows。

## 6.4 最终 decisive table 的最小元数据

为了让后续 `CPU + GPU` vs `CPU + FPGA` 主表不再回头补口径，本文对每个进入 decisive table 的 case 追加最小 metadata 要求：

| 字段 | 作用 |
| --- | --- |
| `case_id` | workload 唯一标识 |
| `workload_group_id` | 当前 phase-1 group 归属，例如 `qe_fpga_phase1_workload_group_v0` |
| `case_state` | `thesis_counted` / `gate_only` / `pending` |
| `case_role` | `anchor` / `decisive` / `scale_support` |
| `admission_batch_id` | 标记它属于第几批被允许进入 decisive table 的 case |
| `qe_tolerance_schema_id` | 对应的数值容差 schema |
| `fairness_policy_id` | 对应 shared-rewrite / baseline 公平性合同版本 |
| `power_boundary_id` | 对应 whole-node power 统计边界版本 |
| `observability_contract_id` | 对应 simulator↔board observability 合同版本 |
| `algorithm_rewrite_manifest_id` | 本 case 采用的算法协同/重写政策标识；无则填 `none` |
| `gpu_rewrite_status` | `n/a` / `shared_enabled` / `not_closed` |
| `baseline_accounting_boundary_id` | 说明 CPU+GPU / CPU+FPGA 是否落在同一 shell ledger |
| `aggregation_admission` | `eligible` / `blocked`；只有 `eligible` 才允许进入 group statistic |
| `block_reason` | 若被挡下，记录缺的是 `gold` / `gpu_baseline` / `power` / `fairness` / `observability` 中哪一项 |

这些字段是 phase-1 decisive tables 的最小要求，不等于最终 paper table 要全部展开，但后端 artifact 必须齐全。

## 7. Group-level claim discipline

## 7.1 不允许 cherry-pick

一旦 v0 workload roster 被 leader 确认，后续不得在看过 `CPU + FPGA` vs `CPU + GPU` 结果之后，再删 case 或换 case 来抬高平均 speedup。

## 7.2 冻结后的 phase-1 aggregation rule

本文不再把 group-level aggregation statistic 留作 open item，而是直接冻结 phase-1 decisive table 的口径：

- **主统计量**：只对 `aggregation_admission = eligible` 的 `thesis_counted` cases 计算 **end-to-end speedup 的 geometric mean**；
- **guardrail 1**：同一主表中必须至少包含 **2 个** `thesis_counted` cases，且第一批必须来自 `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 这条 decisive lane；
- **guardrail 2**：若任一已计入 case 的 speedup `< 1.0x`，则禁止在主句里写“整个 workload-group 稳定优于 CPU+GPU”，只能写成“group geomean > 1 但存在 fail case”；
- **guardrail 3**：最终 `>2x` thesis 只在两条同时满足时成立：
  - decisive group geometric mean `>= 2.0x`；
  - 所有已计入 case 都满足 `speedup >= 1.2x`。

这里故意采用：

- geometric mean 作为主统计量；
- `min-case >= 1.2x` 作为最小 guardrail；

原因是批准计划要求的是 **workload-group 级别的 end-to-end decisive win**，而不是允许一个极大 speedup case 把其余 marginal / failing cases 掩盖掉。

## 7.3 case-count 与表述纪律

在 phase-1 中，group-level 结论必须按下面三档表述：

| decisive cases 数量 | 允许表述 |
| --- | --- |
| `0` | 只允许说 roster / contract 已冻结，不允许写任何 group speedup 结论 |
| `1` | 只允许说 single-case result 或 bring-up result，不允许写 workload-group result |
| `>=2` | 允许写 workload-group result，但必须同时报告 geomean、min-case speedup、以及未入组 case 的 block 状态 |

这意味着：

- `si4_pbe_uspp_small` 一条先跑出来，只能算 decisive lane 的第一张票；
- 必须再把 `graphene_pbe_uspp` 也闭合，phase-1 才第一次具备 workload-group 级别的表述资格。

## 8. 当前 open items

下面这些点还没有闭合，因此本文明确把它们列成 v0 open items：

1. **CPU + GPU shell baseline 仍缺失**  
   `docs/benchmarks/archive/reports/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md` 已经明确说明 GPU shell-level baseline 还是 deferred；在它补齐前，只能冻结 roster 和 correctness contract，不能宣称最终 thesis 已验证。

2. **只有 `si8_pbe_nc` / `si8_pbe_uspp` 已进入 canonical gold matrix v0**  
   `si4_pbe_uspp_small`、`graphene_pbe_uspp`、`au_slab_subspace`、`sic32_subspace` 还需要补各自的 normalized gold baseline / compare artifacts。

3. **Residual / density / eigenspectrum fidelity 还没有进入 v0 required fields**  
   状态文档已经明确，这些 fidelity 结果目前仍缺；phase-1 现在只冻结最终能量、收敛状态、residual-threshold 状态。后续如要把“strict-fidelity”讲成加分项，需要另开 schema revision。

4. **`scf_iterations` 仍是 report-only**  
   当前允许 algorithmic co-design 导致 iteration drift，只要最终 stopping contract 不变且数值 gate 通过；但后续如果 drift 成为核心科学风险，可能需要把它升级成 stronger gate。

5. **`au_slab_subspace` / `sic32_subspace` 还没有 thesis-ready convergence closure**  
   它们现在的重要性主要来自系统故事和 speedup envelope 敏感度，不代表它们已经准备好进入 phase-1 的最终 decisive workload-group。

6. **PBE0 / CG 路线还没有进入 v0 thesis-counted set**  
   rerun 证明它们对长期 full-stack 很重要，但当前 phase-1 的 first paper 不把它们和 Davidson/generalized 主线一起强行冻结。

7. **`si4_pbe_uspp_small` / `graphene_pbe_uspp` 的 GPU baseline 与 power artifact 仍待闭合**  
   当前 status 文档已经给出它们的 CPU shell aggregate，但 `CPU + GPU` 仍是 deferred baseline；在 GPU / power / fairness ledger 补齐前，这两个 case 还不能真正升级为 `thesis_counted`。

## 9. v0 执行建议

按当前证据，workload-group 与 correctness/tolerance contract 的近期执行顺序建议是：

1. 先把 `si8_pbe_nc` correctness/convergence anchor 跑成稳定 gold lane；
2. 并行把 `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 的 gold / GPU baseline / FPGA shell artifact / power ledger 补齐成第一批 `thesis_counted` 候选；
3. 以本文冻结的 geomean + min-case guardrail 口径，先形成一个由这两个 decisive case 构成的最小 phase-1 workload-group；
4. 再把 `si8_pbe_uspp`、`au_slab_subspace`、`sic32_subspace` 逐个补成可判定的 convergence-comparable row，并决定它们是进入 decisive table 还是继续留在 scale-support lane。

对于进入 decisive lane 的实际 artifact 目录，推荐在每次新增 GPU / board row 后运行：

```bash
python3 tools/benchmarks/assess_qe_phase1_evidence_closure.py \
  --gpu-baseline-dir <gpu_dir_1> \
  --gpu-baseline-dir <gpu_dir_2> \
  --board-dir <board_dir_1>
```

如果需要同时产出人可读摘要，再使用：

```bash
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --gpu-baseline-dir <gpu_dir_1> \
  --gpu-baseline-dir <gpu_dir_2> \
  --board-dir <board_dir_1> \
  --output-prefix <report_prefix>
```

若后续只想把已有 closure JSON 重新渲染成 Markdown，也可直接运行：

```bash
python3 tools/benchmarks/render_qe_phase1_evidence_closure_md.py \
  --input <report_prefix>.json \
  --output <report_prefix>.md
```

## 10. 一句话冻结

phase-1 的 QE-only `CPU + FPGA` thesis 现在可以这样表述：

> 我们已经冻结了一个 **QE-only、non-cherry-picked 的 phase-1 candidate workload roster**，并进一步冻结：只有同时通过 **QE gold correctness gate**、**convergence comparability gate**、**algorithmic fairness closure**、以及 **same-boundary GPU/power artifact closure** 的 `thesis_counted` cases，才允许进入最终 `CPU + GPU` vs `CPU + FPGA` 的 `time-to-solution` workload-group 主表；phase-1 的 decisive statistic 固定为 **eligible cases 的 geometric mean**，并受 **所有已计入 case 均需 `>= 1.2x`** 的最小 guardrail 约束。
