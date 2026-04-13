# 2026-04-13 SystemC System-Level DSE Confidence and Claims Rubric v0

## 1. 文档定位

这份文档给 system-level DSE 的输出结论提供统一的 claim discipline，避免第一版模型在 proxy 条件下过度外推。它主要服务于：

- sweep / summary lane：给 family ranking 打统一 `confidence`；
- correctness lane：把 `gold_pass / gold_fail / portability_only` 的语义固定下来；
- advisor-facing report lane：决定哪些结论可以写进老师汇报首页，哪些只能作为 exploratory note。

本文件与以下文档配套使用：

- [/Volumes/remote/phd/year_2/project/dft加速/.omx/plans/prd-systemc-system-level-dse.md](/Volumes/remote/phd/year_2/project/dft加速/.omx/plans/prd-systemc-system-level-dse.md)
- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md)
- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md)

## 2. 输出结论分级

### 2.1 Ranking-grade conclusion
允许回答：

- `F1 / F2 / F3` 的相对排序
- 推荐 CPU/device 分工
- 推荐 offload scope
- 推荐主路径算子集

默认证据基础：

- 同一 fixed numerical contract 下的 family 比较
- convergence-scoped 性能/能量输出
- portability lane 的行为稳定性

### 2.2 Projection-grade conclusion
允许回答：

- `speedup_to_convergence_range`
- `energy_to_convergence_range`
- “是否值得进入下一阶段 FPGA / RTL 原型化”

额外前提：

- QE gold lane 必须有明确 `gold_pass / gold_fail` 结果
- 报告中必须写明 `assumption_set_id`
- 只能给区间，不给无边界点估计

## 3. correctness_status 语义冻结

| correctness_status | 语义 | 允许的使用方式 |
|---|---|---|
| `gold_pass` | QE gold correctness gate 通过；最终 `total energy`、`residual threshold` 状态、收敛状态与 QE CPU-only baseline 对齐 | 可用于 ranking-grade 和 projection-grade |
| `gold_fail` | QE gold correctness gate 未通过，或关键字段未满足冻结容差 | 只能用于解释失败，不应用于 projection-grade 推荐 |
| `portability_only` | 只在 VASP / CP2K portability lane 中观察到趋势，未通过 QE gold gate | 只能作为 portability evidence，不能单独支撑推荐结论 |
| `partial` | 上游输入不完整，或 gold 结论尚未封闭 | 可作临时内部草稿，不应进入正式 advisor 首页 |

## 4. confidence 语义冻结

| confidence | 最低前提 | 报告中的允许口径 |
|---|---|---|
| `high` | QE gold gate 通过；family 排序在 gold lane 与 portability lane 上都稳定；无 `algorithm_contract_deviation`；主要 projection 不依赖单一脆弱假设 | 可放入首页 recommendation 与口头主线 |
| `medium` | QE gold gate 通过；family 排序基本稳定，但 projection 对 resident/fallback/energy proxy 假设较敏感，或 portability 证据较弱 | 可进入正式报告，但要同时写局限与敏感假设 |
| `exploratory` | gold gate 未封闭，或存在 `algorithm_contract_deviation`，或 family 排序只在有限 case 上成立 | 只能作为补充观察，不应作为“推荐主线” |

## 5. 自动降级规则

出现以下任一条件时，结论必须降级：

1. `algorithm_contract_deviation = yes`
2. 任一 QE gold case 为 `gold_fail`
3. `speedup_to_convergence_range` 或 `energy_to_convergence_range` 缺少 assumption set
4. projection 只由 portability lane 支撑
5. 关键上游输入缺失，导致报告只能填 `partial`

建议降级方式：

- `high -> medium`
- `medium -> exploratory`
- 如 gold correctness 失败，则 projection-grade 结论直接 withheld

## 6. 老师汇报首页允许出现的句子类型

### 6.1 可以出现
- “在 QE gold correctness gate 通过的前提下，`F2` 是当前推荐 family。”
- “当前 `speedup_to_convergence_range` 与 `energy_to_convergence_range` 为区间估计，而非最终板级实测。”
- “该推荐的 `confidence = medium`，主要敏感项是 resident reuse 与 fallback rate 假设。”

### 6.2 不应出现
- “该系统已经证明最终 RTL 一定最优。”
- “该模型已经证明最终板级功耗就是某个精确值。”
- “仅凭 portability lane 就推荐进入原型化。”
- “在 `gold_fail` 状态下继续给出强 projection-grade 推荐。”

## 7. sweep / summary 输出最小字段要求

每条 family recommendation 至少带：

- `family`
- `correctness_status`
- `confidence`
- `assumption_set_id`
- `algorithm_contract_deviation`
- `speedup_to_convergence_range`
- `energy_to_convergence_range`
- `main_reason`

缺任一字段时，advisor-facing 模板首页应降级或留空。

## 8. 建议的最终汇总动作

在 team 进入 advisor pack 汇总前，建议做一次 claims sanity check：

1. correctness lane 确认 `gold_pass / gold_fail`
2. sweep lane 生成 family ranking + range outputs
3. report lane 按本 rubric 给每个结论打 `confidence`
4. 最终 verifier 检查首页是否存在越级 claim

这样可以保证：

- 排序结论和 projection 结论不混淆；
- `confidence` 不是主观形容词，而是有输入条件的标签；
- 老师看到的是可辩护的系统级结论，而不是过度承诺。
