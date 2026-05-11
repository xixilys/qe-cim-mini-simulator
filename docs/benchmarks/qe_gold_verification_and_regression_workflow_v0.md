# QE Gold Verification + Frozen-Contract Regression Workflow（v0，2026-04-13）

## 0. 目的

这份文档补上 **worker-3 / verification lane** 的固定动作：

1. 验证 QE gold lane 仍然可执行；
2. 给冻结的 QE gold contract 增加一个可重复运行的 regression guard；
3. 明确哪些变化属于 **allowed additive diagnostics**，哪些变化会触碰冻结合同。

它不替代 `qe_gold_correctness_contract_v0.md`；它的角色是 **验证手册 + contract-regression checklist**。

---

## 1. Frozen contract guard

新增脚本：

- `/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/check_qe_gold_contract_regression.py`

执行：

```bash
python3 tools/benchmarks/check_qe_gold_contract_regression.py
```

这个 guard 固定检查下面几类回归：

### 1.1 Schema freeze

确认 schema 没有被无意放松：

- required field 仍然只包括：
  - `final_total_energy_ry`
  - `final_converged`
  - `final_residual_threshold_reached`
- `final_total_energy_ry` 容差仍然是：
  - `abs_tol = 1e-8 Ry`
  - `rel_tol = 1e-10`
  - `scale_floor = 1.0`
- `scf_iterations` 仍然是 `report_only`
- residual-threshold bootstrap 仍然只能从 `final_converged` 推断，并显式标成 `bootstrap_from_final_converged`

### 1.2 Runner freeze

确认 architecture-family sweep runner 的 QE gold 入口没有漂移：

- gold-required workload 仍然只包括 `si8_pbe_nc` 和 `si8_pbe_uspp`
- `si8_pbe_nc` 仍然在 `qe_gold` lane
- family roster 仍然固定在 `F1/F2/F3`

### 1.3 Helper semantics freeze

guard 直接跑 compare helper，验证下面语义没有变：

- 能量扰动在容差内时仍然 `PASS`
- 能量扰动超容差时仍然 `FAIL`
- `scf_iterations` 不一致时仍然只作为诊断字段，不会单独让 `gold_pass` 失败
- candidate 缺少 `final_residual_threshold_reached` 时，bootstrap fallback 仍然有效且带显式来源标记

---

## 2. Verification ladder

当 QE gold lane 的 contract / compare helper / sweep runner 被修改时，建议按下面顺序验证。

### Step 1 — Python syntax sanity

```bash
python3 -m py_compile tools/benchmarks/*.py
```

### Step 2 — Frozen contract regression guard

```bash
python3 tools/benchmarks/check_qe_gold_contract_regression.py
```

### Step 3 — Canonical QE gold gate run

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --gold-required-only \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F1 F2 F3 \
  --canonical-only \
  --execute-model \
  --auto-match-baseline-iters \
  --fail-on-gold-mismatch \
  --output-dir tmp/qe_gold_lane
```

解释规则：

- 退出码 `0`：所有 gold-required rows 都通过冻结合同
- 非零：出现 mismatch，或者 baseline / candidate / compare / model 基础设施错误

### Step 4 — Build evidence

```bash
cmake --build model/qe_band_solver_model/build -j4
```

如果 Step 3 失败，不能直接改 contract 来“修复”失败；必须先判断失败属于哪一类：

- 真实 mismatch
- baseline 缺失 / baseline normalization error
- candidate missing
- model error
- compare error

---

## 3. Allowed vs forbidden changes

### Allowed（本阶段允许）

- 新增 summary/report artifact
- 新增 machine-readable verification note
- 新增 human-readable failure taxonomy 说明
- 新增回归测试/guard 脚本

### Forbidden（会触碰 frozen contract）

- 放宽 `final_total_energy_ry` 容差
- 把 `final_converged` 或 `final_residual_threshold_reached` 从 required 改成 optional
- 让 `scf_iterations` 参与 overall `gold_pass`
- 改写 baseline normalization 语义，让同一个 QE baseline 变成不同 canonical 值
- 把 compare helper 的 pass/fail 阈值改成比 contract 更宽松

如果确实要改这些内容，必须把它当成 **显式 contract revision**，而不是普通实现细节。

---

## 4. Worker-3 lane deliverable

verification / regression lane 的最小交付不是“又跑一遍命令”，而是：

1. 有固定 guard 可以挡住 contract 漂移；
2. 有固定命令可以重复验证；
3. 有清晰文档说明什么叫 additive-only，什么叫 contract change。

一句话：**formal gate 可以继续演进，但 frozen QE gold semantics 不能偷偷漂移。**

---

## 5. Latest observed verification snapshot（2026-04-13）

本轮 worker-3 验证跑到的结果：

- `python3 tools/benchmarks/check_qe_gold_contract_regression.py`：`PASS`
- `cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build && cmake --build model/qe_band_solver_model/build -j4`：`PASS`
- canonical QE gold gate：

  ```bash
  python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
    --gold-required-only \
    --workloads si8_pbe_nc si8_pbe_uspp \
    --families F1 F2 F3 \
    --canonical-only \
    --execute-model \
    --auto-match-baseline-iters \
    --fail-on-gold-mismatch \
    --output-dir tmp/qe_gold_lane_worker3
  ```

  返回：

  - `rows=6`
  - `passed=0`
  - `failed=6`
  - `errors=0`

按当前 artifact 读数：

- `si8_pbe_nc` 的 `F1/F2/F3` 都是 **energy mismatch**，但 `final_converged` 和 `final_residual_threshold_reached` 已经匹配；
- `si8_pbe_uspp` 的 `F1/F2/F3` 同时存在 **energy mismatch + converged/residual mismatch**。

这个 snapshot 的意义不是“宣布 gate 已完成”，而是给 convergence lane 一个冻结合同下的当前基线：  
`si8_pbe_nc/F1` 目前最集中的 blocker 已经收敛到 **energy gap**，不是布尔状态漂移。
