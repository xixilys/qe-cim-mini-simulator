# 2026-04-13 Bootstrap-Complete Handoff Note — SystemC System-Level DSE v0

## 1. 文档定位

这份 note 服务于 team 当前从 `execution` 进入 `bootstrap-complete` 之后的过渡阶段。它不是新的规划文档，而是把目前已经落地的 bootstrap 产物、它们对 advisor pack 的含义、以及下一阶段还缺什么，收成一份可交接的状态说明。

## 2. 当前 team 状态

根据当前 `.omx` team state：

- phase: `bootstrap-complete`
- completed bootstrap:
  - `qe-gold-tolerance-schema`
  - `qe-gold-compare-helper`
  - `architecture-family-config-layer`
  - `dse-result-schema`
  - `dse-sweep-runner`
- next focus:
  - `family-behavior-deepening`
  - `canonical-baseline-normalization`
  - `candidate-result-canonicalization`

## 3. 已落地的 concrete upstream artifacts

### 3.1 Correctness lane
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_correctness_contract_v0.md`
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- `/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/compare_qe_gold_correctness.py`

这些文件已经足以固定：
- QE gold correctness gate 的必需字段
- tolerance schema ID 的实际来源
- `gold_pass / gold_fail` 的比较 helper 路径

### 3.2 Architecture lane
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/architecture_template.hpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/architecture_template.cpp`
- `/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/types.hpp`

这些文件已经足以固定：
- `F1 / F2 / F3` 的默认 template label
- canonical offload / resident / diag policy 的代码锚点
- `assumption_set_id` / `confidence_label` / `algorithm_contract_deviation` 的字段落点

### 3.3 Sweep lane
- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- `/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`

这些文件已经足以固定：
- projection/ranking 输出的 machine-readable schema
- `speedup_to_convergence_range`
- `energy_to_convergence_range_j`
- `confidence`
- `assumption_set_id`
- `canonical_profile_match`
- `qe_baseline_id`

但当前 bootstrap runner 仍保留一个需要后续收口的临时点：
- `qe_baseline_id` 在 runner 中先写为 `qe_cpu_only_gold_v0`
- `qe_tolerance_schema_id` 默认仍是 `pending_qe_numerical_tolerance_schema_v0`

因此 canonical baseline normalization 阶段不仅要产出 baseline 结果，还要把这些 placeholder 字段替换成最终可追溯的 release 值。

## 4. 对 advisor pack 的直接影响

当前 advisor-facing 文档集已经不再是纯抽象模板，而是能直接追溯到上游具体文件：

- correctness 字段可追溯到 QE gold contract / tolerance schema
- family 叙事可追溯到 architecture-template implementation
- projection 字段可追溯到 sweep runner / result schema

因此，当前 docs lane 的主要职责已经从“补模板”转成：

- 维护这些追溯关系不漂移
- 等待下一阶段的 canonical baseline / candidate result 产物
- 在真正的 ranking/projection 结果出现后，帮助 report lane 做 final pack 收口

## 4.1 当前尚未发现的 concrete canonical outputs

截至当前检查，workspace 里已经有 correctness contract / tolerance schema / compare helper / family-template layer / sweep schema/runner，
但**还没有发现**可以直接作为 final advisor pack 输入的以下 concrete 结果文件：

- canonical baseline-normalized output artifact
- candidate-result canonicalized payload artifact
- final family ranking / projection result JSON

并且在该轮检查时，还**没有发现**可直接作为 final advisor pack 输入的 `systemc_architecture_family_dse_*` 类生成结果；后续历史生成证据归档在 `docs/benchmarks/archive/results/`。

这意味着 docs lane 现在不应提前生成带具体数值的 advisor 首页，而应继续等待这些结果型上游产物真正落地。

## 4.2 2026-04-16 状态更新：next-stage package 已落地

相对于本 note 初稿阶段，当前 repo 已经不再停留在“只有骨架、没有 recommendation-grade package”的状态。

当前 next-stage phase runner 已经能够直接生成：

- `qe_next_stage_dse_phase_summary.json / .md`
- `qe_next_stage_projection_review.json / .md`
- `qe_next_stage_stage_main_recommendation.json / .md`

这意味着：

- projection review package 已能汇总所有 accurate-layer-passing shortlisted candidates；
- stage-main recommendation package 已能收口最终 `recommended_family`、`recommended_primary_candidates`、以及 `validated_alternative_candidates`；
- advisor-facing cover memo / report / one-pager / pack manifest / checklist / docs index / figures-layout guide / why-not template / QA cheatsheet 都已经知道并引用这两类 package。

因此，当前 docs lane 的主要职责已经进一步转成：

1. 维护 package 字段与 advisor-facing narrative 的一致性；
2. 确保 `projection_review` 与 `stage_main_recommendation_package` 不发生语义漂移；
3. 只在 package contract 再次升级时补同步，而不是继续扩写更多抽象模板。

## 5. 进入下一阶段前还缺什么（在 package 已落地之后）

### 5.1 family-behavior-deepening
还需要更清楚地回答：
- `F1 / F2 / F3` 在真实 case 上的行为差异是否稳定
- 何时触发 fallback / spill / resident mismatch
- 哪些行为会影响 `confidence`

### 5.2 canonical-baseline-normalization
还需要一条更明确的 baseline 归一化产物，让 report/verifier 能稳定引用：
- baseline case ID
- canonical payload shape
- baseline accounting boundary
- QE baseline ID 到报告字段的直接映射

### 5.3 candidate-result-canonicalization
还需要把 candidate 运行结果规范成稳定 payload，方便：
- compare helper 消费
- report template 自动填表
- verifier 检查 `correctness_status` / `assumption_set_id` / `algorithm_contract_deviation`

## 6. docs lane 当前建议动作

在 team 进入 terminal phase 之前，docs lane 建议维持“维护态”而不是继续扩写新模板：

1. 跟踪新落地的 baseline/candidate canonical artifacts
2. 只做必要的字段来源对齐修补
3. 不提前生成未经上游结果支撑的 advisor 首页结论

## 7. 最终 release 前的最低条件

在 advisor pack 真正进入“可对老师汇报”状态前，至少还应确认：

- 有可追溯的 QE gold correctness result
- 有可追溯的 canonical baseline ID
- 有可追溯的 candidate canonical result payload
- 有来自 sweep runner 的 family ranking / projection outputs
- 若 stage 已到 `projection_eligible`，`projection_review` 与 `stage_main_recommendation_package` 已生成并彼此一致
- `confidence` 已由 verifier 结合上游证据冻结

## 8. 一句话状态总结

现在 bootstrap 已完成，系统已经具备：**family template + QE gold gate + sweep schema/runner** 三个关键骨架；接下来真正决定 advisor pack 能否落地的，不再是模板够不够，而是 baseline / candidate / family behavior 这三类结果能否被 canonical 化并稳定接入。
