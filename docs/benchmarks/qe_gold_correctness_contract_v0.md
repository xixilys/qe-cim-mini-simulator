# QE gold correctness contract（v0，2026-04-13）

## 0. 目的

这份文档冻结 QE gold correctness lane 的**数值字段**、**容差**和**pass/fail 规则**，服务于系统级 DSE 的第一版执行阶段。

它回答的是：

- SystemC / timed-functional candidate 的最终结果，能不能和 **QE CPU-only baseline** 在关键数值上对齐；
- 在给老师汇报系统架构选择和加速比区间前，哪些结果能被标记为 `gold_pass = yes`。

对应的 machine-readable schema 在：

- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`

配套关系上，它和 `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/extract_qe_shell_cpu_baseline.py` 是互补的：前者抽 shell-level timing aggregate，这一套文件冻结的是 QE gold numerical gate。

## 0.1 Canonical gold matrix（v0）

这一版 formal gate 明确冻结一个**版本化 canonical QE gold matrix**：

- `canonical_gold_matrix_id = qe_canonical_gold_matrix_v0`
- `canonical_gold_matrix_version = 2026-04-13`

当前 gate-required workload 只包含两项：

| workload_id | 角色 |
| --- | --- |
| `si8_pbe_nc` | **first-priority convergence case** |
| `si8_pbe_uspp` | canonical coverage case |

其中：

- `si8_pbe_nc` 被明确标记为当前第一优先收敛对象；
- 第一条固定 convergence family 是 `F1`，原因记录在 gate artifacts 里：`host_cpu_fallback` 与 QE CPU-side 行为耦合最少，适合作为第一条缩窄路径；
- 这份 matrix 只声明 gate coverage / priority，不改变 compare helper 的字段语义、容差或 pass 阈值。

## 0.2 Gate 输出状态分类（additive only）

formal gate 在 summary / bundle / compare artifact 上统一使用下面这组状态：

| 状态 | 含义 |
| --- | --- |
| `pass` | 所有强制字段通过 frozen QE gold contract |
| `mismatch` | compare helper 正常执行，但至少一个强制字段失败 |
| `baseline_missing` | baseline 元数据 / stdout 缺失 |
| `baseline_normalization_error` | baseline 归一化失败 |
| `candidate_missing` | runnable model 未产出 candidate JSON |
| `model_error` | runnable model 返回非零 |
| `compare_error` | compare helper 自身执行失败 |

注意：这些分类只是**报告层 / artifact 层**的 formalization，不改变 baseline normalization semantics、compare-field semantics 或 tolerance。

## 1. v0 的强制字段

v0 故意只冻结最小但必须的 gold gate：

| 字段 | 含义 | 规则 | 是否强制 |
| --- | --- | --- | --- |
| `final_total_energy_ry` | 最终总能量 | 数值容差比较 | 必须 |
| `final_converged` | 最终 SCF 是否收敛 | 精确匹配 | 必须 |
| `final_residual_threshold_reached` | 最终 residual / SCF-accuracy 阈值是否达到 | 精确匹配 | 必须 |
| `scf_iterations` | 最终 SCF 轮数 | 仅报告，不参与 v0 gold pass | 可选 |

## 2. 容差定义

### 2.1 `final_total_energy_ry`

v0 采用：

- `abs_tol = 1e-8 Ry`
- `rel_tol = 1e-10`
- `scale_floor = 1.0`

比较规则：

```text
pass if |candidate - baseline| <= max(abs_tol, rel_tol * max(|baseline|, scale_floor))
```

这样做的目的，是把 v0 的数值门槛固定在一个保守的 DFT 量级上，同时避免对接近 0 的值产生不稳定的纯相对误差判断。

### 2.2 布尔字段

- `final_converged`
- `final_residual_threshold_reached`

都要求**精确匹配**。

## 3. Pass / fail 规则

整体 `gold_pass` 规则非常直接：

```text
overall_pass = every required field passes
```

也就是说：

- 只要任何一个强制字段失败，整体就是 `gold_pass = no`
- `scf_iterations` 只作为解释性字段，不会单独导致 fail

## 4. Bootstrap 约定

为了让这套 gate 在当前 brownfield 阶段就能启动，v0 允许一个**临时推断**：

- 如果 JSON 里没有显式的 `final_residual_threshold_reached`
- helper 可以把它**临时**从 `final_converged` 推断出来
- 报告中会标成 `bootstrap_from_final_converged`

这只是第一版引导措施，不是最终长期合同。后续如果 runnable model 显式导出 residual-threshold 状态，应该优先使用显式字段。

## 5. JSON 输入约定

helper 支持两类输入：

### 5.1 Canonical JSON

推荐格式：

```json
{
  "case_id": "si8_pbe_nc",
  "final": {
    "total_energy_ry": -62.28748772,
    "residual_threshold_reached": true,
    "converged": true,
    "scf_iterations": 8
  }
}
```

### 5.2 QE metadata JSON + stdout fallback

如果 JSON 本身不含 canonical 字段，但包含 `stdout_file`，helper 会尝试从 QE stdout 抽取：

- 最终 total energy
- convergence achieved / not achieved
- SCF iteration 数

这对当前 `docs/benchmarks/results/qe_workload_revalidation/*/metadata.json` 很有用。

## 6. 辅助脚本

baseline 归一化脚本在：

- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/normalize_qe_gold_baseline.py`

比较脚本在：

- `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/compare_qe_gold_correctness.py`

示例：

```bash
python3 docs/benchmarks/normalize_qe_gold_baseline.py \
  --metadata docs/benchmarks/results/qe_workload_revalidation/si8_pbe_nc/metadata.json \
  --output /tmp/si8_pbe_nc.gold.json

python3 docs/benchmarks/compare_qe_gold_correctness.py \
  --baseline /tmp/si8_pbe_nc.gold.json \
  --candidate /path/to/candidate_result.json \
  --output /tmp/qe_gold_compare.json
```

如果 baseline / candidate 是 summary list，也可以加：

```bash
  --case-id si8_pbe_nc
```

如果要把 QE gold lane 作为一条真正可执行的批量 gate 往前推，可以直接用 architecture-family sweep runner 的 canonical gold 命令：

```bash
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --gold-required-only \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F1 F2 F3 \
  --canonical-only \
  --execute-model \
  --auto-match-baseline-iters \
  --fail-on-gold-mismatch \
  --output-dir tmp/qe_gold_lane
```

这条命令会做四件事：

1. 先把 QE baseline 归一化成 canonical gold JSON  
2. 再运行 runnable model 导出 candidate JSON  
3. 然后自动调用 compare helper  
4. 最后输出 bundle/CSV/summary/compare artifacts，并在任一 gold-required case 失败时返回非零退出码

### 6.1 Exit code 约定

- 返回 `0`：所有 selected gold-required rows 都是 `pass`
- 返回非零：出现任意 `mismatch` 或 infrastructure status（如 `baseline_missing` / `model_error` / `compare_error`）

### 6.2 Artifact layout

假设 `--output-dir tmp/qe_gold_lane`，当前 formal gate 会固定产出：

| 路径 | 作用 |
| --- | --- |
| `tmp/qe_gold_lane/systemc_architecture_family_dse_bootstrap_v0.json` | 原始 machine-readable bundle |
| `tmp/qe_gold_lane/systemc_architecture_family_dse_bootstrap_v0.csv` | 行级 CSV 导出 |
| `tmp/qe_gold_lane/qe_gold_gate_summary_v0.json` | **machine-readable gate summary**（按 workload / family 汇总） |
| `tmp/qe_gold_lane/qe_gold_gate_summary_v0.md` | **human-readable gate summary** |
| `tmp/qe_gold_lane/artifacts/baseline/*.gold.json` | canonical baseline JSON |
| `tmp/qe_gold_lane/artifacts/candidate/*.json` | candidate result JSON |
| `tmp/qe_gold_lane/artifacts/compare/*.compare.json` | compare helper report |
| `tmp/qe_gold_lane/artifacts/stdout/*.log` | runnable model stdout |

### 6.3 Interpretation rules

- `qe_gold_gate_summary_v0.json` / `.md` 都会给出：
  - 每个 `workload × family` 的 gate status；
  - 哪些强制字段失败（`final_total_energy_ry` / `final_converged` / `final_residual_threshold_reached`）；
  - `scf_iterations` 的 baseline / candidate 对照，作为解释性上下文；
  - `si8_pbe_nc` 是否是 first-priority convergence case。
- `compare/*.compare.json` 继续保留逐字段原始细节；summary 只是把这些信息正式汇总出来，并没有改变 helper 的比较逻辑。

## 7. 这份合同解决什么，不解决什么

### 解决
- 冻结 QE gold lane 的最小可执行数值 gate
- 让 system-level DSE 的 `gold_pass` 有统一口径
- 给后面的 ranking/projection 输出提供一条不漂移的正确性底线

### 不解决
- 不给出完整 QE faithful 数值模拟承诺
- 不覆盖 portability lane 的 VASP / CP2K strict correctness
- 不冻结最终 FPGA/RTL 级数值误差预算

一句话：这份合同是**第一版系统级 DSE 的 QE gold correctness 门槛**，不是最终全系统数值签核规范。
