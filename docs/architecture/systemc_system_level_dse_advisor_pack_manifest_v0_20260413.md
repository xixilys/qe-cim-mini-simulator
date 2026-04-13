# 2026-04-13 Advisor Pack Manifest and Handoff Map — SystemC System-Level DSE v0

## 1. 文档定位

这份 manifest 用于 team execution 后期的最终集成。它不定义新的技术结论，而是把 advisor pack 需要的文档、字段来源、推荐 owner lane、以及放行条件整理成一个统一交付清单，避免最后成包时出现：

- 字段重复但口径不一致
- 上游输入缺失却提前生成首页结论
- ranking-grade / projection-grade 混写
- correctness / confidence / assumption set 无法追溯来源

## 2. 最终 advisor pack 建议目录

建议最终成包逻辑如下：

1. **Cover memo**
2. **Executive summary one-pager**
3. **Main report**
4. **Correctness appendix**
5. **Projection appendix**
6. **Q&A cheatsheet**（内部使用，不一定对外发）

## 2.1 当前已发现的 concrete upstream artifacts

当前仓库里已经存在、可直接被 advisor pack 引用的上游文件包括：

- QE correctness contract: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_correctness_contract_v0.md`
- QE numerical tolerance schema: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- QE correctness compare helper: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/compare_qe_gold_correctness.py`

这些文件意味着：`correctness_status` 与 `tolerance schema ID` 已经有具体落点，不再只是抽象占位。

## 2.2 当前已发现的 architecture-template 上游实现

当前 family comparator 的 brownfield 代码锚点包括：

- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/architecture_template.hpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/architecture_template.cpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/types.hpp` 中的 `ArchitectureTemplateConfig` / `SystemRunConfig`

这意味着 `recommended_family`、`offload_scope`、`resident_policy`、`diag_policy` 已经有具体代码入口，不再只是汇报层抽象名词。

## 2.3 当前已发现的 sweep / result-schema 上游实现

当前用于 projection 与 ranking 输出的上游文件包括：

- DSE result schema: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- DSE sweep runner: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`

这意味着 `speedup_to_convergence_range`、`energy_to_convergence_range`、`confidence`、`assumption_set_id` 这些字段也已经有 concrete schema / runner 落点。

同时需要注意：当前 bootstrap sweep runner 中 `qe_baseline_id` 默认写成 `qe_cpu_only_gold_v0`，`qe_tolerance_schema_id` 默认仍是 `pending_qe_numerical_tolerance_schema_v0`。在 final advisor pack 进入 release 前，这两个字段应被 canonical baseline / correctness lane 的真实值覆盖，而不是直接沿用 bootstrap placeholder。

## 3. Artifact map

| Artifact | 路径 / 形态 | 主要用途 | 主要 owner lane | 是否必须 |
|---|---|---|---|---|
| Cover memo | `advisor_cover_memo` | 给老师的先读版推荐摘要 | report lane | 是 |
| Executive summary one-pager | `onepager` | 一页讲清推荐 family 与 projection | report lane | 是 |
| Main report | `main_report` | 完整 family ranking + correctness + limitations | report lane | 是 |
| Family responsibility matrix | `family_matrix` | 统一 CPU/device/datapath 分工叙事 | architecture lane + report lane | 是 |
| QE gold correctness report | `qe_gold_report` | 冻结 `gold_pass / gold_fail` | correctness lane | 是 |
| Sweep / summary ranking output | `sweep_summary` | family ranking、projection range、assumption set | sweep lane | 是 |
| Confidence and claims rubric | `claims_rubric` | 冻结 `confidence` 与 claim discipline | report lane + verifier lane | 是 |
| Bootstrap-complete handoff note | `bootstrap_handoff_note` | 记录 bootstrap 已落地骨架与下一阶段缺口，供 team 过渡期对齐 | docs lane / team coordination | 否 |
| Advisor pack checklist | `assembly_checklist` | 最终成包放行检查 | verifier lane | 是 |
| Advisor Q&A cheatsheet | `qa_cheatsheet` | 汇报/答辩时统一口径 | report lane | 否 |

## 4. 首页关键字段来源追踪

| 首页字段 | 来源 artifact | 上游 owner | 说明 |
|---|---|---|---|
| `recommended_family` | `sweep_summary` + `family_matrix` | sweep lane / architecture lane | 必须和 family responsibility matrix 叙事一致 |
| `correctness_status` | `qe_gold_report` | correctness lane | 不允许 report lane 自行推断 |
| `confidence` | `claims_rubric` + `qe_gold_report` + `sweep_summary` | verifier/report lane | 必须按 rubric 打级 |
| `speedup_to_convergence_range` | `sweep_summary` | sweep lane | 只能填 range；schema 字段同名 |
| `energy_to_convergence_range` | `sweep_summary` | sweep lane | 只能填 range；machine-readable schema 字段名为 `energy_to_convergence_range_j` |
| `assumption_set_id` | `sweep_summary` | sweep lane | projection-grade 必须存在 |
| `ranking_grade_ready` / `projection_grade_ready` | `sweep_summary` | sweep lane / verifier lane | 若 machine-readable 结果存在，这两个 ready flag 应参与最终放行判断 |
| `algorithm_contract_deviation` | correctness / architecture cross-check | correctness lane / architecture lane | 若为 `yes` 必须降级 confidence |
| `main_reason` | `family_matrix` + `sweep_summary` | report lane | 不能和上游 ranking 结论冲突 |
| `main_caveat` | `claims_rubric` + `qe_gold_report` | report lane / verifier lane | 必须反映真实局限 |

## 5. 推荐的 lane 交接顺序

### 5.1 Architecture lane -> Report lane
必须交付：
- family responsibility matrix
- family-level CPU/device/datapath 分工摘要
- `diag` 路径说明

### 5.2 Correctness lane -> Report lane / Verifier lane
必须交付：
- QE gold correctness report
- tolerance schema ID
- `gold_pass / gold_fail`
- 若存在数值路径变化，显式标出 `algorithm_contract_deviation`

### 5.3 Sweep lane -> Report lane / Verifier lane
必须交付：
- family ranking
- `speedup_to_convergence_range`
- `energy_to_convergence_range`
- `assumption_set_id`
- main reason / sensitivity note

### 5.4 Verifier lane -> Final pack
必须交付：
- confidence finalization
- claim discipline check
- 首页字段完整性确认
- release / hold recommendation

## 6. 成包前必须回答的交叉一致性问题

1. `recommended_family` 是否同时被 ranking output 和 family matrix 支撑？
2. `correctness_status` 是否确实来自 QE gold report，而不是 report lane 主观判定？
3. `confidence` 是否按 rubric 规则确定，而不是口头感觉？
4. projection 字段是否都带有 `assumption_set_id`？
5. 是否任何地方把 system-level proxy 说成了最终 RTL / 板级功耗结论？

## 7. Hold 条件

出现以下任一情况时，advisor pack 应暂缓正式汇报：

- canonical baseline-normalized output 尚未落地
- candidate-result canonicalized payload 尚未落地
- final family ranking / projection result JSON 尚未落地
- QE gold correctness 结果缺失
- 首页缺少 `correctness_status` 或 `confidence`
- projection 不是 range 而是无边界点估计
- `algorithm_contract_deviation = yes` 但未解释
- family ranking 与 family matrix 叙事冲突

## 8. Release 条件

只有同时满足以下条件时，advisor pack 才应进入“可对老师汇报”状态：

- `correctness_status` 已冻结
- `confidence` 已冻结
- `speedup_to_convergence_range` 已冻结
- `energy_to_convergence_range` 已冻结
- 已存在可追溯的 DSE result bundle / ranking output 文件
- `assumption_set_id` 已可追溯
- 报告明确声明 v1 不是 RTL 参数冻结器
- 报告未越级声称 board-level final power
