# 2026-04-13 Advisor-Facing Report Template — SystemC System-Level DSE v0

## 1. 使用说明

这份模板用于第一版 system-level DSE 的老师汇报包。目标不是给出 RTL 定版结论，而是用统一口径汇报：

- 推荐的系统架构 family
- 该 family 的 correctness status
- 该 family 的 confidence
- `speedup_to_convergence_range`
- `energy_to_convergence_range`
- 是否值得进入下一阶段 FPGA / RTL 原型化

所有 projection 都必须按 **SCF-shell convergence scope** 汇报，而不是 kernel 峰值吞吐。

## 1.1 填写前应准备的上游输入

在填写这份模板前，默认已经拿到以下上游产物：

- family comparator 输出：至少覆盖 `F1 / F2 / F3` 的统一 ranking 结果；
- QE gold correctness report：包含最终 `total energy`、`residual threshold`、收敛状态的对齐结论；
- sweep / summary 输出：包含 `speedup_to_convergence_range`、`energy_to_convergence_range`、confidence 与 assumption set。

如果这三类输入里缺任意一项，首页摘要中的 projection-grade 结论应降级为 `partial` 或暂不填写。

## 2. 报告首页摘要（必填）

| 字段 | 填写内容 |
|---|---|
| Report ID | `TODO` |
| Date | `TODO` |
| Recommended family | `F1 / F2 / F3` |
| Recommendation type | `ranking-grade / projection-grade` |
| correctness_status | `gold_pass / gold_fail / portability_only` |
| confidence | `high / medium / exploratory` |
| speedup_to_convergence_range | `TODO` |
| energy_to_convergence_range | `TODO` |
| assumption_set_id | `TODO` |
| algorithm_contract_deviation | `no / yes` |
| One-line recommendation | `TODO` |

## 3. 一页执行结论

### 3.1 Recommendation
- **Recommended family**: `TODO`
- **Why this family wins**: `TODO`
- **Why the others are not preferred now**: `TODO`
- **Should we continue to FPGA / RTL prototyping?**: `yes / no / only after deeper validation`

### 3.2 Projection summary
- **Projection schema**: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- **Projection sweep source**: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- **speedup_to_convergence_range**: `TODO`
- **energy_to_convergence_range**: `TODO`
- **Schema note**: machine-readable schema currently uses `energy_to_convergence_range_j`; advisor-facing text may omit `_j` but must preserve Joule units in tables/figures.
- **time_to_convergence trend**: `TODO`
- **Main limiting factor**: `DMA / fallback / low resident reuse / correctness risk / other`

### 3.3 Correctness summary
- **correctness_status**: `TODO`
- **QE gold gate result**: `pass / fail / partial`
- **QE baseline ID**: `TODO`
- **QE numerical tolerance schema ID**: `TODO`
- **Key note**: `TODO`

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

## 5. Family ranking summary（必填）

| Family | CPU/device split summary | correctness_status | confidence | speedup_to_convergence_range | energy_to_convergence_range | Main reason |
|---|---|---|---|---|---|---|
| `F1` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |
| `F2` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |
| `F3` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |

## 6. QE gold correctness gate（必填）

### 6.1 Gold reference
- **Reference lane**: QE CPU-only baseline
- **Correctness contract**: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_correctness_contract_v0.md`
- **Tolerance schema**: `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- **Cases**:
  - `QE USPP-heavy`
  - `QE NC-light` including `si8_pbe_nc`

### 6.2 Pass/fail table

| QE case | final total energy match | residual threshold state match | converged/not-converged state match | tolerance schema ID | pass/fail | Note |
|---|---|---|---|---|---|---|
| `QE USPP-heavy` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |
| `QE NC-light / si8_pbe_nc` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` | `TODO` |

### 6.3 Correctness interpretation
- If either QE gold case fails, projection-grade claims must be downgraded or withheld.
- If `algorithm_contract_deviation = yes`, explain the deviation and reduce confidence explicitly.

## 7. Portability evidence（建议填写）

| Case | Workload trait | Observed winner | correctness_status | confidence | Note |
|---|---|---|---|---|---|
| `VASP PAW-heavy` | `PAW-heavy` | `TODO` | `portability_only` | `TODO` | `TODO` |
| `CP2K OT-like small batch` | `NC-light / OT-like` | `TODO` | `portability_only` | `TODO` | `TODO` |

## 8. Evidence classification（必填）

### 8.1 Ranking-grade conclusions
可用于：
- family ranking
- 推荐 CPU/device 分工
- 推荐主路径算子集
- 推荐 offload policy

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
- `ranking_grade_ready` / `projection_grade_ready`（若直接引用 machine-readable schema 时）

## 9. 风险、假设与局限（必填）

### 9.1 Assumptions
- `TODO`

### 9.2 Risks
- `TODO`

### 9.3 Limitations
- v1 是 system-level 架构筛选器，不是 RTL 参数冻结器。
- 不应用这份报告直接宣称最终 board-level power。
- 不应用这份报告直接冻结 DMA / buffer / BRAM / URAM / HBM 参数。

## 10. 建议下一步（必填）

### 10.1 If recommendation is accepted
- `TODO`

### 10.2 What should be refined next
- `DMA / buffer engineering`
- `faithfulness upgrade`
- `FPGA prototype`
- `other: TODO`

## 11. 附录：建议的口头汇报句式

> 在统一 QE gold correctness gate 下，我们比较了 `F1 / F2 / F3` 三类软硬件协同系统架构。  
> 当前推荐 `TODO` 作为下一阶段主线，因为它在 `correctness_status = TODO`、`confidence = TODO` 的前提下，给出了 `speedup_to_convergence_range = TODO` 与 `energy_to_convergence_range = TODO`。  
> 这说明该架构族在 system-level 上具备继续工程化验证的价值，但当前结论仍受 `TODO` 约束，尚不能直接外推为 RTL 定版或板级功耗结论。
