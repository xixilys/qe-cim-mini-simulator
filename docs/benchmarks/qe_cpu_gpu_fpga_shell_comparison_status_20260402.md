# QE shell-level `CPU only` / `CPU + GPU` / `CPU + FPGA` 对比执行状态（2026-04-02）

## 1. 作用

这份记录不是新的比较合同，而是 `Task 6` 在当前仓库里的**第一次执行状态快照**。

它只回答三件事：

1. 当前已经跑出了什么；
2. 这些输出能支持什么，不能支持什么；
3. 下一步必须补哪些数据，Task 6 才能从 `in_progress` 进入可判定状态。

### 1.1 当前执行模式

当前 Task 6 的**本地执行模式**已经明确收口为：

- `CPU only`
- `CPU + FPGA`

`CPU + GPU` 仍保留在总合同里，但当前机器和当前结果集中并没有可直接纳入表格的 shell-level GPU 实测结果，因此它在这份状态记录中继续作为**deferred baseline**存在。

## 2. 本次实际执行的命令

### 2.1 trace-backed case 摘要

```bash
python3 docs/benchmarks/summarize_qe_subspace_trace.py docs/benchmarks/results/qe_si_medium_trace.csv
python3 docs/benchmarks/summarize_qe_subspace_trace.py docs/benchmarks/results/qe_graphene_trace.csv
```

### 2.2 shell-contract runnable model

```bash
./model/qe_band_solver_model/build/qe_band_solver_model | rg 'SCF iteration report|QE shell-stage summary|Full DFT run report'
```

### 2.3 CPU micro-benchmark 实际执行

```bash
/usr/bin/python3 docs/benchmarks/run_cpu_baseline.py --threads 1 --output docs/benchmarks/results/qe_cpu_baseline_threads1_20260402.json
```

结果：成功。这里刻意没有继续使用默认 `python3`，因为默认解释器缺少 `numpy/scipy/pyscf`；最终采用的是已经验证带依赖的 `/usr/bin/python3`。

## 3. 当前已拿到的执行输出

### 3.1 `Si` trace 摘要

- 数据源：`docs/benchmarks/results/qe_si_medium_trace.csv`
- total calls：`180`
- generalized-like calls：`140`
- standard-like calls：`40`
- dominant `(n, m)`：`(16, 8)`，出现 `67` 次
- 结论：`Si` 代理 workload 的 reduced-space 路径以 generalized Davidson 小块反复调用为主，适合继续做 shell-level case descriptor 与 reduced-solver fidelity 对齐。

### 3.2 `graphene` trace 摘要

- 数据源：`docs/benchmarks/results/qe_graphene_trace.csv`
- total calls：`148`
- generalized-like calls：`112`
- standard-like calls：`36`
- dominant `(n, m)`：`(8, 4)`，出现 `74` 次
- 结论：`graphene` 代理 workload 的 reduced-space 维度明显更小，可作为对比 `Si` 的轻量 2D-channel 代理。

### 3.2.1 关于新增 small-Si workload

用户要求再加一个更小的半导体负载，例如 `3–4` 个 `Si` 原子级别的系统。

当前已经完成的动作是：

- 新建了真实可跑输入：`docs/qe_inputs/si4_pbe_uspp_small.in`
- 将它接入了工作负载脚本：
  - `docs/benchmarks/run_qe_workload_matrix.py`
  - `docs/benchmarks/analyze_qe_workload_revalidation.py`
- 实际跑通了这个 case，并生成了 trace / stdout / metadata

这个 workload 当前的 measured descriptor 是：

- case id：`si4_pbe_uspp_small`
- solver：`davidson`
- `npw = 1473`
- `nkb = 72`
- `max_subspace_n = 16`
- `max_subspace_m = 8`
- FFT grid：`36x36x18`
- `electrons` wall：`0.35 s`
- `c_bands` wall：`0.17 s`
- derived avg `c_bands` episode：`24.29 ms`
- derived avg `SCF iteration`：`50.00 ms`
- convergence：`yes` in `7` iterations

### 3.3 当前 runnable shell model 输出

数据源：`./model/qe_band_solver_model/build/qe_band_solver_model`

提取到的关键 totals：

| 观测对象 | move | ref_cycles | bp_ref_cycles | 备注 |
| --- | ---: | ---: | ---: | --- |
| iteration 1 shell summary | `486.0812 KiB` | `801` | `54` | `cdiaghg_on_companion=yes` |
| iteration 2 shell summary | `801.2812 KiB` | `1026` | `105` | `cdiaghg_on_companion=yes` |
| iteration 3 shell summary | `954.8812 KiB` | `1026` | `105` | `cdiaghg_on_companion=yes` |
| full run shell total | `2242.2437 KiB` | `2853` | `264` | 3 次 SCF iteration 后收敛 |

run-level 输出还确认：

- 当前模型级别：`STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_BODY10_BODY04_LEAF_FLOW_CONTROL_PROXY`
- 当前 shell-stage 视图已经能显式报告 `rho -> Veff -> ... -> mix_rho`
- 但 `cdiaghg` 仍由 `COMPANION_CDIAGHG_PROXY` 计账，而不是硬件 cluster

### 3.4 当前真实 `CPU only` micro-benchmark 输出

数据源：`docs/benchmarks/results/qe_cpu_baseline_threads1_20260402.json`

这是当前仓库里已经真实执行得到的 `CPU only` 基线数据，不是 analytical 回填值。

关键结果如下：

| kernel family | shape / size | metric | value |
| --- | --- | --- | ---: |
| GEMM | `3072x256x64` | median throughput | `171.60 GFLOP/s` |
| GEMM | `2048x512x256` | median throughput | `259.18 GFLOP/s` |
| FFT | `64^3` | median points/s | `79.91 Mpoints/s` |
| FFT | `96^3` | median points/s | `97.03 Mpoints/s` |
| FFT | `128^3` | median points/s | `83.86 Mpoints/s` |
| generalized eigensolve | `scipy_gvd_256` | median latency | `5.55 ms` |
| generalized eigensolve | `scipy_gvd_512` | median latency | `31.38 ms` |
| generalized eigensolve | `scipy_gvd_768` | median latency | `94.10 ms` |
| generalized eigensolve | `pyscf_safe_eigh_256` | median latency | `14.40 ms` |
| generalized eigensolve | `pyscf_safe_eigh_512` | median latency | `65.53 ms` |
| generalized eigensolve | `pyscf_safe_eigh_768` | median latency | `174.98 ms` |

这些数据当前只支持：

- 建立 `CPU only` 的真实 operator-level reference points；
- 校验 analytical model 的数量级；
- 为后续 case-bound shell totals 提供下界与 sanity check。

这些数据**还不等于** case-bound `c_bands episode latency` 或 `SCF iteration latency`。

### 3.5 当前真实 `CPU only` shell aggregate 抽取

第一轮数据源：

- `docs/benchmarks/results/qe_workload_revalidation/si4_pbe_uspp_small/stdout.out`
- `docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp/stdout.out`
- `docs/benchmarks/results/qe_workload_revalidation/graphene_pbe_uspp/stdout.out`

扩展后数据源：

- `docs/benchmarks/results/qe_workload_revalidation/au_slab_subspace/stdout.out`
- `docs/benchmarks/results/qe_workload_revalidation/sic32_subspace/stdout.out`
- `docs/benchmarks/results/qe_cpu_shell_aggregate_extract_20260402.json`

抽取命令：

```bash
python3 docs/benchmarks/extract_qe_shell_cpu_baseline.py \
  --cases si4_pbe_uspp_small si8_pbe_uspp graphene_pbe_uspp au_slab_subspace sic32_subspace \
  --output docs/benchmarks/results/qe_cpu_shell_aggregate_extract_20260402.json
```

这里的口径分两层：

- `electrons_wall_s` / `c_bands_wall_s` / `h_psi_wall_s` / `pwscf_wall_s`：直接来自 QE stdout timing section 的**真实 aggregate**
- `avg_c_bands_episode_wall_ms` / `avg_scf_iteration_wall_ms_from_electrons`：由真实 aggregate 再除以 call count 或 iteration count 得到的**导出平均值**

关键结果如下：

| case | measured `PWSCF` wall | measured `electrons` wall | measured `c_bands` wall | `c_bands` calls | derived avg episode | iterations | derived avg SCF iter |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `si4_pbe_uspp_small` | `0.53 s` | `0.35 s` | `0.17 s` | `7` | `24.29 ms` | `7` | `50.00 ms` |
| `si8_pbe_uspp` | `1.14 s` | `0.91 s` | `0.47 s` | `8` | `58.75 ms` | `8` | `113.75 ms` |
| `graphene_pbe_uspp` | `0.54 s` | `0.41 s` | `0.27 s` | `6` | `45.00 ms` | `6` | `68.33 ms` |
| `au_slab_subspace` | `10.25 s` | `8.87 s` | `5.68 s` | `5` | `1136.00 ms` | `4` | `2217.50 ms` |
| `sic32_subspace` | `16.29 s` | `13.83 s` | `9.34 s` | `4` | `2335.00 ms` | `4` | `3457.50 ms` |

这一步已经把 `CPU only` 从纯 operator-level reference points，推进到了**五个 case 的真实 QE shell aggregate** 层。

### 3.6 当前相对 `CPU only` 的 speedup envelope

数据源：

- `docs/benchmarks/results/qe_cpu_shell_aggregate_extract_20260402.json`
- `docs/benchmarks/results/qe_cpu_speedup_envelope_20260402.json`
- `docs/benchmarks/qe_cpu_speedup_envelope_20260402.md`

这一层不是 FPGA 实测，也不是 cluster latency model 的直接输出，而是：

- 用真实 `CPU only` 的 `electrons / c_bands / h_psi` timing；
- 通过 `Amdahl` 公式，推导“如果未来硬件主要加速 `c_bands` 或只加速 `h_psi`，整个 SCF 最多能快多少”。

当前最重要的结果是：

| case | SCF upper bound if `c_bands -> inf` | SCF upper bound if `h_psi -> inf` |
| --- | ---: | ---: |
| `si4_pbe_uspp_small` | `1.94x` | `1.40x` |
| `si8_pbe_uspp` | `2.07x` | `1.44x` |
| `graphene_pbe_uspp` | `2.93x` | `1.58x` |
| `au_slab_subspace` | `2.78x` | `1.83x` |
| `sic32_subspace` | `3.08x` | `2.04x` |

这组结果说明：

- 只看 `h_psi` 不够；
- 如果你的 clustered v1 真能把整个 `c_bands` 主路径压下去，那么相对 `CPU only` 的系统收益空间是明确存在的；
- `Au slab` 与 `SiC32` 对整轮 SCF speedup 更敏感，应继续保留为主 case。

## 4. 当前输出能支持什么

当前输出已经足够支持：

1. 冻结 `Si / graphene` 的第一批 trace-backed case descriptor；
2. 把 shell-level 比较边界固定在同一个 `QE` 软件语义上；
3. 从 runnable model 中提取统一的 shell traffic / ref-cycle / stall proxy；
4. 获得真实执行的 `CPU only` operator-level baseline；
5. 获得 `si4_pbe_uspp_small`、`si8_pbe_uspp`、`graphene_pbe_uspp`、`au_slab_subspace`、`sic32_subspace` 的真实 `CPU only` shell aggregate；
6. 获得相对 `CPU only` 的实测驱动 speedup envelope；
7. 明确区分“contract-layer shell totals”和“implementation-facing clustered-FPGA totals”。

## 5. 当前输出不能支持什么

当前输出**还不能**支持：

1. 宣称 `CPU + FPGA` 已经打赢 `CPU only`；
2. 宣称 `CPU + FPGA` 已经打赢 `CPU + GPU`；
3. 宣称 “hardware `cdiaghg` clustered v1” 已经由 runnable model 直接验证；
4. 宣称 `CPU + FPGA` 的 `FP64` fidelity 已经优于 GPU。

原因分别是：

- `CPU only` 目前已经覆盖 `small-Si / Si / graphene / Au slab / SiC32` 五个 case，但 episode / iteration 还是 aggregate-based derived average，不是 direct per-episode timer；
- `CPU + GPU` 还没有严格区分 `Strict-FP64` 与 `Practical` 两类 baseline 的结果；
- 当前 runnable model 仍是 companion-`cdiaghg` contract layer；
- 任何 fidelity 结论都还没有 residual / density / eigenspectrum / iteration-count 对照结果。
- 本机虽然可见 `Apple M4` GPU，但当前仓库没有与 `QE` shell 直接对齐的 `Metal/MPS` GPU baseline 路径，因此不会把本机通用 GPU 能力当成 `CPU + GPU` shell 结果的替代物。

## 5.1 替代方法披露

当前阶段所有结果按下面三类严格区分：

### A. 真实执行结果

- `Si / graphene` trace 摘要
- `docs/benchmarks/results/qe_cpu_baseline_threads1_20260402.json` 中的 `CPU only` micro-benchmark
- `docs/benchmarks/results/qe_cpu_shell_aggregate_extract_20260402.json` 中的五个 measured shell aggregates
- `docs/benchmarks/results/qe_cpu_speedup_envelope_20260402.json` 中的 Amdahl-style speedup envelope

### B. contract-layer proxy

- `model/qe_band_solver_model` 输出的 shell totals

这部分的用途是 shell contract 对齐与 traffic/stall/accounting，不是最终 clustered hardware `cdiaghg` 结果。

### C. 尚未产生的真实结果

- case-bound `CPU only` shell totals
- `CPU + GPU` shell totals
- hardware-`cdiaghg` clustered `CPU + FPGA` shell totals
- residual / density / eigenspectrum / iteration-count fidelity 对照

注意：

- `qe_cpu_speedup_envelope_20260402.*` 属于 **derived-from-measured**，不是 FPGA 实测。

## 6. 对 Task 6 状态的直接判断

因此，`Task 6` 当前应保持：

- 状态：`in_progress`
- 结论级别：**只允许报告 contract freeze 和 execution status，不允许报告 win region**

## 7. 下一步必须补齐的三项

### 7.1 跑通 `CPU only`

当前 operator-level `CPU only` 和 `si4_pbe_uspp_small / Si / graphene / Au slab / SiC32` 的 shell aggregate 都已经跑通；下一步不是重复 micro-benchmark，而是补更多主矩阵 case，并尽量拿到更细粒度 shell timing。

推荐继续使用已验证环境：

```bash
/usr/bin/python3 docs/benchmarks/run_cpu_baseline.py --threads 1 --output <cpu-baseline.json>
```

目标：

- 保持 `CPU only` 的真实 operator-level reference points；
- 继续扩展 `CPU only` shell aggregate 到剩余主矩阵或辅助 stress case；
- 在不引入代理填表的前提下，把 aggregate timing 与 case descriptor 闭合。

### 7.1.1 当前表格状态

`docs/benchmarks/qe_shell_comparison_table_template_v0.csv` 已经写入五个 `CPU only` 实测行：

- `si4_pbe_uspp_small`
- `si8_pbe_uspp`
- `graphene_pbe_uspp`
- `au_slab_subspace`
- `sic32_subspace`

这些行中的 `c_bands_episode_latency_ms` 与 `scf_iteration_latency_ms` 仍明确标记为 **derived from measured aggregate**，没有伪装成 direct per-episode timer。

同时，表里已经新增：

- `small_si_pending_proxy`

但它当前只是 pending 槽位，还没有任何实测数字。

### 7.2 补 `CPU + GPU` 报告模板或实测

至少先冻结每个 GPU 结果行的：

- precision mode：`Strict-FP64` 或 `Practical`
- offloaded stages
- launch/sync 粒度
- Host-GPU traffic accounting
- reproducibility class

### 7.3 把 clustered hardware-`cdiaghg` 行补成真正的 `CPU + FPGA`

不能只用当前 runnable model。

必须把：

- `model/qe_band_solver_model` 的 shell-contract totals
- `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md` 的 cluster-level design-point

合并成同一张 `CPU + FPGA` 结果行，并显式说明：

- 当前 design point 是否启用 hardware `cdiaghg`
- 若不启用，fallback 触发条件是什么
- resident / spill / FIFO 假设如何影响 win region

## 8. 当前最合理的推进顺序

推荐顺序固定为：

1. 先完成 `Si` 与 `graphene` 的 case-row 冻结；
2. 再补 `CPU only`；
3. 再补 `CPU + GPU` precision-mode rows；
4. 最后把 clustered `CPU + FPGA` 行补齐；
5. 只有这四步完成后，才进入 `Task 7` 质量门检查。
