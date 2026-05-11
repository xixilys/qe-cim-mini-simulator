# 2026-04-13 Advisor-Facing Report Template — SystemC System-Level DSE v0

## 1. 使用说明

这份模板用于第一版 system-level DSE 的老师汇报包。目标不是给出 RTL 定版结论，而是用统一口径汇报：

- 当前是否已经形成 family recommendation；
- 如果已经形成，推荐哪个 family、证据边界是什么；
- 如果还没有形成，阻塞 recommendation 的关键缺口是什么；
- 是否值得进入下一阶段 FPGA / RTL 原型化。

所有 projection 都必须按 **SCF-shell convergence scope** 汇报，而不是 kernel 峰值吞吐。

## 1.1 填写前应准备的上游输入

默认已经拿到以下上游产物：

- family comparator / shortlist 输出：覆盖 `F1 / F2 / F3` 的统一 ranking；
- QE gold correctness report：包含最终 `total energy`、`residual threshold`、收敛状态的对齐结论；
- stage artifact bundle manifest：release-facing 顶层入口，用于统一定位 phase summary / projection review / stage-main recommendation package；
- sweep / phase summary 输出：包含 phase gate、public recommendation、confidence 与 assumption set；
- projection review package：收集所有 accurate-layer-passing shortlisted candidates；
- stage-main recommendation package：收集最终 recommended family 的 primary candidates 与 validated alternatives；
- confidence / claims rubric；
- advisor pack manifest / docs index。

如果这些输入里缺任意一项，首页摘要仍要完整，但必须**同时**降级成：
- `recommended_family = none-yet`
- `recommendation_type = evidence-incomplete`
- `correctness_status = partial`
- `confidence = exploratory`（证据未闭合时的默认对外写法）

---

## 2. 报告首页摘要（必填）

| 字段 | 填写规则 |
|---|---|
| `Report ID` | 建议格式：`qe-dse-report-[YYYYMMDD]-[run_id_or_phase_id]` |
| `Date` | 报告导出日期，格式 `YYYY-MM-DD` |
| `Recommended family` | 填 `F1 / F2 / F3 / none-yet` |
| `Recommendation type` | 填 `evidence-incomplete / ranking-grade / projection-grade` |
| `correctness_status` | 只能填 rubric-backed 值：`gold_pass / gold_fail / portability_only / partial`。证据未闭合时默认 `partial` |
| `confidence` | 只能填 `high / medium / exploratory`。证据未闭合时默认 `exploratory` |
| `speedup_to_convergence_range` | 只在 `recommendation_type = projection-grade` 时填写；否则留空，并在 `One-line recommendation` 或 `Main limiting factor` 中解释为什么当前不展示 range |
| `energy_to_convergence_range` | 同上 |
| `assumption_set_id` | 只在 `recommendation_type = projection-grade` 时填写；否则留空即可，不要自造状态字符串 |
| `algorithm_contract_deviation` | 填 `no / yes`，来自 comparison contract |
| `One-line recommendation` | 若有 promoted family，写“推荐谁以及为什么”；若无，写“当前不提升任何 family 的单一主阻塞” |

---

## 3. 一页执行结论

### 3.1 Recommendation
- **Recommended family**：直接写 `F1 / F2 / F3 / none-yet`
- **Why this family wins / why no family is promoted yet**：
  - recommendation-grade：一句话概括 ranking + correctness + system-design 依据；若要展示 range，本段 recommendation_type 必须是 `projection-grade`；
  - evidence-incomplete：一句话概括当前主阻塞，例如 `fast-layer shortlist still insufficient_evidence`。
- **Why the others are not preferred now**：
  - 对每个非推荐 family 给一句 why-not；
  - 若 `none-yet`，则改写为“为什么当前不提升任何 family”。
- **Should we continue to FPGA / RTL prototyping?**：填 `yes / no / only after deeper validation`。

### 3.2 Projection summary
- **Release-facing top-level entrypoint**：`qe_next_stage_artifact_bundle_manifest.json / .md`
- **Projection schema**：`docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- **Projection sweep source**：`tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- **Next-stage phase runner**：`tools/benchmarks/run_qe_next_stage_dse_phase.py`
- **Projection review package**：`qe_next_stage_projection_review.json / .md`
- **Stage-main recommendation package**：`qe_next_stage_stage_main_recommendation.json / .md`
- **speedup_to_convergence_range**：只在 `recommendation_type = projection-grade` 时引用 machine-readable bundle；否则留空，并在 narrative 里解释为什么当前还不能展示 range
- **energy_to_convergence_range**：同上
- **Schema note**：machine-readable schema 使用 `energy_to_convergence_range_j`；advisor-facing 文本可省略 `_j`，但必须保留 Joule 单位
- **time_to_convergence trend**：一句话描述排序逻辑或当前阻塞，例如“time-first ranking 已冻结，但 mainline fast-layer metrics 尚未闭合”
- **Main limiting factor**：从 `DMA / fallback / low resident reuse / correctness risk / missing fast-layer evidence / other` 里选一个最关键项

### 3.3 Correctness summary
- **correctness_status**：来自 QE gold gate / accurate layer
- **QE gold gate result**：若 gate summary 已产出，则直接抄 `pass / mismatch / baseline_missing / baseline_normalization_error / candidate_missing / model_error / compare_error`；若 artifact 尚未产出，则保持 `correctness_status = partial` 并在 `Key note` 解释缺失原因
- **QE baseline ID**：来自 comparison contract；若上游 bundle 还未给出，就留空并在 `Key note` 里说明 baseline artifact 尚未闭合
- **QE numerical tolerance schema ID**：默认 `qe_gold_numerical_tolerance_schema_v0`
- **Key note**：一句话说明当前 correctness 结论是否足够支撑 ranking-grade / projection-grade claim

---

## 4. 比较范围与固定合同

### 4.1 Compared families
- `F1` — Host-heavy / Single-hotpath
- `F2` — Balanced hybrid / Multi-operator pipeline
- `F3` — Device-heavy / Full inner-loop offload

### 4.2 Fixed comparison contract
本报告默认所有 family 共享：

- 相同 input case
- 相同 pseudopotential
- 相同 convergence threshold
- 相同 outer SCF accounting boundary
- 相同 QE gold correctness gate

### 4.3 Allowed family differences
- CPU / device 分工
- offload scope
- `diag` policy
- runtime scheduling path
- resident / spill policy

---

## 5. Family ranking summary（必填）

| Family | CPU/device split summary | correctness_status | confidence | speedup_to_convergence_range | energy_to_convergence_range | Main reason |
|---|---|---|---|---|---|---|
| `F1` | host-heavy / single-hotpath / or measured split summary | 当前 bundle 若含 `F1` row 则据实填写；否则留空 | 当前 bundle 若含 `F1` row 则据实填写；否则留空 | 仅 projection-grade 时填写 | 仅 projection-grade 时填写 | 写 artifact-backed reason；若未闭合则写 `planned comparison lane` 或 why-not |
| `F2` | balanced hybrid / multi-operator pipeline / or measured split summary | 当前 bundle 若含 `F2` row 则据实填写；否则留空 | 当前 bundle 若含 `F2` row 则据实填写；否则留空 | 仅 projection-grade 时填写 | 仅 projection-grade 时填写 | 写 artifact-backed reason；若无证据则写 `planned comparison lane` 或 why-not |
| `F3` | device-heavy / full inner-loop offload / or measured split summary | 只有当前 bundle 实际包含 `F3` row 时才填写；否则留空并标注 `optional/withheld` | 同左 | 只有当前 bundle 实际包含 `F3` row 且 recommendation 为 projection-grade 时才填写 | 同左 | 无 `F3` artifact 时写 `optional/withheld` 或 why-not |

### 填写规则
- 如果当前还没有 promoted family，这张表仍要完整；
- `Main reason` 一栏必须写 artifact-backed why-not 或 role 说明；
- 不允许预设 `F1/F2/F3` 的 winner / baseline / stretch 身份；这些标签只有在上游 ranking/summary 明确支持时才可写入；
- 对 `F3`，若没有当前 artifact，就必须写成 `optional/withheld`。

---

## 6. QE gold correctness gate（必填）

### 6.1 Gold reference
- **Reference lane**：QE CPU-only baseline
- **Correctness contract**：`docs/benchmarks/qe_gold_correctness_contract_v0.md`
- **Tolerance schema**：`docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- **Cases**（v0 canonical gold matrix）:
  - `si8_pbe_nc`
  - `si8_pbe_uspp`
- 若 gold contract revision 改了 case set，本节必须同步改成 contract 中的真实 case ID，而不是保留泛化标签。

### 6.2 Pass/fail table

| QE case | final total energy match | residual threshold state match | converged/not-converged state match | tolerance schema ID | pass/fail | Note |
|---|---|---|---|---|---|---|
| `si8_pbe_nc` | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | `qe_gold_numerical_tolerance_schema_v0` | copy gate summary status (`pass / mismatch / baseline_missing / baseline_normalization_error / candidate_missing / model_error / compare_error`) | 简述主要 blocker 或 note |
| `si8_pbe_uspp` | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | copy compare-helper field outcome (`pass` or `fail`) | `qe_gold_numerical_tolerance_schema_v0` | copy gate summary status (`pass / mismatch / baseline_missing / baseline_normalization_error / candidate_missing / model_error / compare_error`) | 简述主要 blocker 或 note |

### 6.3 Correctness interpretation
- 如果任一 QE gold case 进入 `mismatch` 或其他 blocking gate status，projection-grade claims 必须降级或撤回；
- 如果 `algorithm_contract_deviation = yes`，必须显式解释并降级 confidence；
- 如果准层还没闭合，不允许把首页 recommendation 写成 projection-grade。

---

## 7. Portability evidence（建议填写）

| Case | Workload trait | Observed winner | correctness_status | confidence | Note |
|---|---|---|---|---|---|
| `VASP PAW-heavy` | `PAW-heavy` | `artifact-backed observed trend` 或留空 | `portability_only / partial` | `high / medium / exploratory` | 说明该证据是否只做 portability support |
| `CP2K OT-like small batch` | `NC-light / OT-like` | `artifact-backed observed trend` 或留空 | `portability_only / partial` | `high / medium / exploratory` | 说明该证据是否只做 portability support |

---

## 8. Evidence classification（必填）

### 8.1 Ranking-grade conclusions
可用于：
- family ranking
- 推荐 CPU/device 分工
- 推荐主路径算子集
- 推荐 offload policy

**不应在 ranking-grade 首页摘要中直接展示：**
- `speedup_to_convergence_range`
- `energy_to_convergence_range`

### 8.2 Projection-grade conclusions
可用于：
- `speedup_to_convergence_range`
- `energy_to_convergence_range`
- “是否值得进入下一阶段原型化”

Projection-grade 输出必须带：
- `correctness_status`
- `confidence`
- `assumption_set_id`
- `algorithm_contract_deviation`
- `ranking_grade_ready / projection_grade_ready`

### 8.3 Evidence-incomplete conclusions
当以下任一条件成立时，报告必须显式降级为 `evidence-incomplete`：
- mainline fast-layer 仍是 `insufficient_evidence`
- accurate-layer / QE gold gate 未闭合
- recommendation card 中的 range 仍为空白（说明当前还不具备 projection-grade 展示条件）

---

## 9. 风险、假设与局限（必填）

### 9.1 Assumptions
至少覆盖：
- 当前 workload set 与 objective hierarchy 是否冻结；
- 当前 assumption set 是否可能改变 ranking；
- 当前 energy/power 结论是否仍处于 simulator-only 或 board-deferred 状态。

### 9.2 Risks
至少覆盖：
- fast-layer metrics 不足导致 shortlist 不稳定；
- accurate-layer / gold gate 未闭合；
- board observability / whole-node power 尚未到位；
- `F3` 在证据不足时被误用为 decisive recommendation。

### 9.3 Limitations
- v1 是 system-level 架构筛选器，不是 RTL 参数冻结器；
- 不应用本报告直接宣称最终 board-level power；
- 不应用本报告直接冻结 DMA / buffer / BRAM / URAM / HBM 参数；
- 若当前 recommendation 仍为 `none-yet`，这不是否定研究方向，而是说明证据闭合还未完成。

---

## 10. 建议下一步（必填）

### 10.1 If recommendation is accepted
- recommendation-grade：列出该 family 的下一阶段工程化动作；
- evidence-incomplete：写“当前不进入 decisive prototype choice，先补 fast-layer metric population 和 shortlist closure”。

### 10.2 What should be refined next
可从以下中选择并排序：
- `fast-layer metric population`
- `accurate-layer / QE gold closure`
- `DMA / buffer engineering`
- `faithfulness upgrade`
- `FPGA prototype`
- `board observability / power closure`

---

## 11. 附录：建议的口头汇报句式

### recommendation-grade 版本
> 在统一 QE gold correctness gate 下，我们比较了 `F1 / F2 / F3` 三类软硬件协同系统架构。当前推荐 `F?` 作为下一阶段主线，因为它在 `correctness_status=[status]`、`confidence=[level]` 的前提下，给出了最适合继续工程化验证的 CPU/device/datapath 分工。只有当本轮结论已经达到 `projection-grade` 时，才额外在首页展示 `speedup_to_convergence_range` 与 `energy_to_convergence_range`。

### evidence-incomplete 版本（示例）
> 在统一 QE gold correctness gate 下，我们已经把 QE-only 的双层仿真框架与 shortlist policy 收口完成，但当前还没有把任何 family 升成 projection-grade recommendation。最关键的阻塞不是 thesis story，而是 fast-layer ranking metrics 仍未闭合；下一步必须先补齐 `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 的 shortlist evidence，再由 `si8_pbe_nc` 的准层继续兜底 correctness。
