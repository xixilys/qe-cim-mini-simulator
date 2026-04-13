# 2026-04-13 Advisor-Facing DSE Docs Index — SystemC System-Level DSE v0

## 1. 文档定位

这份 index 用于 team 执行后期快速导航当前已经补齐的 advisor-facing 文档集。目标是让任何接手汇总的人都能快速知道：

- 现在哪些文档已经准备好了；
- 每份文档解决什么问题；
- 应该按什么顺序阅读 / 组装；
- 哪些文档是对外汇报产物，哪些更偏内部对齐与 verifier 使用。

## 2. 建议阅读顺序

如果你是第一次接手 advisor pack，建议按这个顺序看：

1. **Family responsibility matrix**
2. **Advisor report template**
3. **Confidence and claims rubric**
4. **Executive summary one-pager template**
5. **Advisor cover memo template**
6. **Bootstrap-complete handoff note**
7. **Advisor pack assembly checklist**
8. **Advisor pack manifest / handoff map**
9. **Advisor figures/tables layout guide**
10. **Why-not-other-families note template**
11. **Advisor Q&A cheatsheet**

## 3. 文档导航表

| 文档 | 路径 | 主要用途 | 建议使用阶段 | 对外 / 对内 |
|---|---|---|---|---|
| Family responsibility matrix | `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` | 固定 `F1/F2/F3` 的 CPU/device/datapath 分工与默认 `diag` 路径 | architecture -> report 对齐 | 对内为主 |
| Advisor report template | `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md` | 主报告模板，要求填写 correctness/confidence/speedup/energy range | report 主体编写 | 对外 |
| Confidence and claims rubric | `docs/architecture/systemc_system_level_dse_confidence_and_claims_rubric_v0_20260413.md` | 冻结 `correctness_status` / `confidence` / claim discipline | verifier + report 收口 | 对内为主 |
| Executive summary one-pager | `docs/architecture/systemc_system_level_dse_executive_summary_onepager_template_v0_20260413.md` | 一页讲清推荐 family 与主指标 | 对外摘要 | 对外 |
| Advisor cover memo | `docs/architecture/systemc_system_level_dse_advisor_cover_memo_template_v0_20260413.md` | 老师先读版 memo | 最终发包前 | 对外 |
| Bootstrap-complete handoff note | `docs/architecture/systemc_system_level_dse_bootstrap_complete_handoff_note_v0_20260413.md` | 说明当前 bootstrap 已完成什么、下一阶段还缺什么 | team 过渡 / 维护态交接 | 对内 |
| Advisor pack checklist | `docs/architecture/systemc_system_level_dse_advisor_pack_assembly_checklist_v0_20260413.md` | 汇总前放行检查 | final verifier | 对内 |
| Advisor pack manifest | `docs/architecture/systemc_system_level_dse_advisor_pack_manifest_v0_20260413.md` | 字段来源、owner lane、handoff map | team final integration | 对内 |
| Figures/tables layout guide | `docs/architecture/systemc_system_level_dse_advisor_figures_tables_layout_guide_v0_20260413.md` | 图表顺序、表格字段、range figure 建议 | report 视觉收口 | 对内 |
| Why-not-other-families note | `docs/architecture/systemc_system_level_dse_why_not_other_families_note_template_v0_20260413.md` | 统一解释“为什么不是另两个 family” | report / advisor Q&A | 对内为主 |
| Advisor Q&A cheatsheet | `docs/architecture/systemc_system_level_dse_advisor_qa_cheatsheet_v0_20260413.md` | 汇报时口头答辩统一口径 | final presentation prep | 对内 |

## 3.1 当前已落地的 family-template 代码锚点

除 advisor-facing 文档外，当前 repo 中已经有可直接引用的 family-template 实现锚点：

- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/architecture_template.hpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/architecture_template.cpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/types.hpp` 中的 `ArchitectureTemplateConfig` / `SystemRunConfig`

这组文件可以帮助 report / verifier lane 追溯：当前 `F1 / F2 / F3` 的默认 template label、offload scope、resident policy、diag policy 到底是如何在 brownfield 模型里落下来的。

## 3.2 当前已落地的 benchmark-side 上游输入

除本 index 列出的 advisor-facing 文档外，当前仓库里已经可以直接配套引用：

- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_correctness_contract_v0.md`
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/compare_qe_gold_correctness.py`

这三项分别对应：
- correctness gate 的文字合同
- machine-readable 容差 schema
- baseline/candidate 对比 helper

## 3.3 当前已落地的 sweep-side 上游输入

当前仓库里已经可以直接配套引用：

- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`

这两项分别对应：
- projection / ranking 结果的 machine-readable schema（含 `energy_to_convergence_range_j`、`ranking_grade_ready`、`projection_grade_ready` 等字段）
- family-level batch sweep 的 runner 落点

## 4. 最小对外交付集合

如果只准备一个最小可汇报包，建议至少包含：

1. cover memo
2. executive summary one-pager
3. main report
4. QE gold correctness gate table

其余文档可以作为内部配套或附录支持。

## 5. 最小内部放行集合

如果只做 final sanity check，至少需要同时对照：

1. confidence and claims rubric
2. advisor pack checklist
3. advisor pack manifest
4. QE gold correctness report
5. sweep / summary ranking output

## 6. 推荐组装顺序

### Step 1 — 先定系统叙事
- 用 family responsibility matrix 固定 Host / Device / Datapath 分工

### Step 2 — 冻结正确性与 claim discipline
- 用 QE gold correctness report 冻结 `correctness_status`
- 用 confidence rubric 冻结 `confidence`

### Step 3 — 填 projection 与 ranking
- 用 advisor report template + executive summary one-pager 填主结果

### Step 4 — 做整包收口
- 用 cover memo 做对外摘要
- 用 checklist + manifest 做 final release check
- 用 Q&A cheatsheet 做汇报前 rehearsal

## 7. 当前文档集能解决的问题

这套文档集已经能支持：

- family-level 系统叙事统一
- correctness / confidence / projection 的口径统一
- 老师汇报页、主报告页、一页摘要页的模板化生成
- final verifier 对 advisor pack 的放行检查

## 7.1 当前还在等待的结果型上游产物

截至当前，文档集已经和 correctness/schema/runner/code-anchors 对齐，但仍在等待：

- canonical baseline-normalized output
- candidate-result canonicalized payload
- final ranking/projection result output

当前检查时，`docs/benchmarks/results/` 下尚未出现 `systemc_architecture_family_dse_*` 类生成结果文件。

在这些结果真正出现前，advisor-facing 页面应继续保持模板/占位状态，而不是提前填入未经上游支撑的具体数值。

## 8. 当前文档集还不替代什么

这套文档集不能替代：

- QE gold correctness report 本身
- sweep / summary ranking output 本身
- 真正的图表数据生成脚本
- 代码实现与数值验证工作

也就是说，它负责的是 **“怎么把结论讲清楚、讲对、讲得不过度”**，不负责替代上游实验结果。
