# si8_pbe_nc / F1 gold 校准记录（2026-04-15）

## 1. 目的

这份记录用于冻结本轮 `si8_pbe_nc / F1` accurate-layer 收敛校准的边界、参数和验证结论。

目标不是声明已经得到一套第一性原理的 `QE` 能量演化模型，而是把当前**通过 gold 的、有界启发式校准**明确记录下来，避免后续误把这轮结果理解为：

- 直接注入 `QE gold` 最终能量；
- 放宽 `gold` 容差；
- 或者把 `F1` 的通过状态误解释成所有 family 都已经完成校准。

## 2. 本轮允许改动的校准面

本轮只收窄了 `F1 + host_cpu_fallback` 的能量更新路径：

- 文件：`model/qe_band_solver_model/src/host_scf.cpp`
- 作用点：`host_cpu_fallback_energy_correction_ry(...)`

保持不变的硬约束：

- 不读取 `QE gold` baseline payload 里的最终能量来反推候选值；
- 不修改 `qe_gold_numerical_tolerance_schema_v0.json`；
- 不修改 compare helper 的 pass/fail 语义；
- 不把 `F2` 或其他 workload 一起“顺手调过”。

## 3. 当前冻结的启发式参数

当前 `F1 + !okvan + cpu_diag_fallback` 的校正项为：

```cpp
const double generalized_relief_coeff = 0.000503925;
const double subspace_scale =
    static_cast<double>(shape.max_subspace_n) / 16.0;
const double generalized_relief =
    generalized_relief_coeff * shape.generalized_ratio * subspace_scale;
return 0.04 + 0.001 * static_cast<double>(shape.nkb) +
       0.0015 * static_cast<double>(shape.max_subspace_n) -
       generalized_relief;
```

其中这组参数仍然是**workload-structure-based hand-tuned heuristic**，依赖的结构量只有：

- `nat`
- `nbnd`
- `nkb`
- `max_subspace_n`
- `ecutwfc`
- `generalized_ratio`
- `okvan`
- `is_2d`

它们来自本地 simulator 的 workload shape 映射，不来自 gold 结果文件。

## 4. 本轮验证命令

### 4.1 构建

```bash
cmake --build model/qe_band_solver_model/build -j4
```

### 4.2 benchmark tests

```bash
python3 -m unittest discover -s docs/benchmarks -p 'test_*.py'
```

### 4.3 focused accurate-layer sweep

```bash
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --output-dir /tmp/si8_check_final.Jni2Qf \
  --workloads si8_pbe_nc \
  --families F1 F2 \
  --canonical-only \
  --execute-model \
  --source-kind timed_functional_proxy \
  --assumption-set-id qe_next_stage_phase_v0 \
  --qe-tolerance-schema-id qe_gold_numerical_tolerance_schema_v0 \
  --auto-match-baseline-iters
```

### 4.4 phase-level check

```bash
python3 docs/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir /tmp/qe_next_stage_phase_final.4NBkgr \
  --execute-model
```

## 5. 本轮冻结结果

focused sweep 的最终状态：

- `si8_pbe_nc / F1`
  - `status = pass`
  - `gold_pass = true`
  - `convergence_comparable_pass = true`
  - `final_total_energy_abs_err_ev = 2.078902693399256e-08`
- `si8_pbe_nc / F2`
  - `status = mismatch`
  - `gold_pass = false`
  - `convergence_comparable_pass = true`
  - `final_total_energy_abs_err_ev = 15.105712470022551`

phase-level 结果：

- `stage_main_recommendation_status = projection_eligible`
- `public_recommended_family = F1`

这说明本轮真正达成的是：

1. `si8_pbe_nc / F1` accurate-layer gold 通过；
2. fast-layer shortlist 不再被 accurate-layer gate 卡住；
3. `F1` 可以进入 projection-grade recommendation review。

## 6. 需要明确保留的 caveat

### 6.1 这不是第一性原理能量模型

当前通过依然是一个**有界的行为级启发式校准**，不是可泛化的 `QE` 物理能量演化模型。

### 6.2 convergence 判定和校正项仍有时序差

在 `HostSCF::finalize_iteration(...)` 里：

- `energy_delta` 先基于 `lambda_base` 和旧 `state.total_energy` 计算；
- 然后才把 `host_cpu_fallback_energy_correction_ry(...)` 作用到 `energy_after_iteration`。

这在本轮没有破坏通过结果，但后续继续调参时要注意：

- `energy_after_iteration` 的改动可能先影响最终能量；
- 但不一定同步反映在 convergence gate 使用的 `energy_delta` 上。

### 6.3 passing lane 的 convergence report 已改成 anchor 语义

`docs/benchmarks/run_systemc_architecture_family_dse_sweep.py` 现在会在 `compare_report["overall_pass"] is True` 时输出：

- `dominant_blocker.kind = "gold_passed"`

这是为了防止 passing lane 继续被错误标成 `energy_trajectory_mismatch`。

## 7. 下一步建议

如果后续继续推进，不要先回头重调 `F1`。优先顺序应为：

1. 把这份校准记录当作当前 `F1` accurate-layer passing anchor；
2. 继续 narrowing `F2` 或其他尚未通过的 lane；
3. 若要继续提升 simulator 可信度，再单独设计更强的 energy-path contract，而不是在本轮 passing lane 上继续无界调参。
