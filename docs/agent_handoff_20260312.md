# Agent Handoff 2026-03-12

## 1. 项目目标

当前项目的长期目标是：

- 面向 [`QE`](https://www.quantum-espresso.org/) / `PySCF` 这类 DFT 科学计算软件
- 设计一套以 `NML + CIM` 为核心的科学计算加速系统
- 当前论文切口聚焦在 `QE Davidson` 子空间里的 Hermitian / generalized Hermitian 对角化
- 同时原生支持其中用到的 `complex FP64 GEMM`

当前最重要的不是整机加速比，而是：

1. 先把真实 workload 的子空间矩阵画像做出来
2. 先把 `Ozaki-II / CRT` 复数 GEMM 主算法收敛
3. 先把 `NML` 侧 generalized Hermitian 微对角化流程收敛

## 2. 硬约束

### 2.1 绝对不要碰主目录 QE

用户明确要求：

- **不要修改** `/Users/xixilys/project/qe-7.5`

之前曾误修改过一次，后来已经恢复。  
后续所有 `QE` 相关工作都必须只在工作区副本进行：

- [`soft/qe-7.5`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5)

### 2.2 当前可用的本地 QE 二进制

已经基于工作区副本成功构建：

- [`soft/qe-7.5/build_subspace_trace/bin/pw.x`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace/bin/pw.x)

这个版本包含对子空间对角化入口的采样 hook。

## 3. 已完成工作

### 3.1 数值 contract / 子系统规格

已完成并落文档：

- [`docs/complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)

已覆盖：

- 输入输出 contract
- 精度目标
- fallback 条件
- 数据布局初版
- 评测方法初版

### 3.2 QE 真实子空间矩阵采样能力

已完成：

- 在工作区副本的 [`cdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/cdiaghg.f90) / [`rdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/rdiaghg.f90) 加入采样 hook
- 采样说明文档：
  - [`docs/qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_subspace_sampling.md)
- patch 留档：
  - [`docs/patches/qe_subspace_sampling_cdiaghg.patch`](/Volumes/remote/phd/year_2/project/dft加速/docs/patches/qe_subspace_sampling_cdiaghg.patch)
  - [`docs/patches/qe_subspace_sampling_rdiaghg.patch`](/Volumes/remote/phd/year_2/project/dft加速/docs/patches/qe_subspace_sampling_rdiaghg.patch)

支持的环境变量：

- `QE_SUBSPACE_TRACE_FILE`
- `QE_SUBSPACE_DUMP_DIR`
- `QE_SUBSPACE_DUMP_LIMIT`
- `QE_SUBSPACE_MIN_N`

### 3.3 QE 真实矩阵数据集

当前已经拿到 6 类样本：

1. `Si`
2. `Fe`
3. `C6H6`
4. `graphene`
5. `Au slab`
6. `SiC32`

数据集状态汇总：

- [`docs/benchmarks/qe_subspace_dataset_status_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_dataset_status_20260312.md)
- [`docs/benchmarks/qe_subspace_profile_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_profile_20260312.md)

trace 结果：

- [`docs/benchmarks/results/qe_si_medium_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_medium_trace.csv)
- [`docs/benchmarks/results/qe_si_large_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_large_trace.csv)
- [`docs/benchmarks/results/qe_fe_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_fe_trace.csv)
- [`docs/benchmarks/results/qe_benzene_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_benzene_trace.csv)
- [`docs/benchmarks/results/qe_graphene_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_graphene_trace.csv)
- [`docs/benchmarks/results/qe_au_slab_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_au_slab_trace.csv)
- [`docs/benchmarks/results/qe_sic32_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_sic32_trace.csv)
- 早期基线：
  - [`docs/benchmarks/results/qe_subspace_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_subspace_trace.csv)
  - [`docs/benchmarks/results/qe_subspace_trace_complex.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_subspace_trace_complex.csv)

重要结论：

- generalized Hermitian 是主路径，不是边角情况
- 既命中 `cdiaghg`，也命中 `rdiaghg`
- 真实样本已经覆盖到 `n = 128`
- 单一 `Si` 样本不足以代表整体 workload

### 3.4 QE 采样输入模板

为可复现实验已经新增：

- [`docs/qe_inputs/fe_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/fe_subspace_trace.in)
- [`docs/qe_inputs/benzene_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/benzene_subspace_trace.in)
- [`docs/qe_inputs/graphene_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/graphene_subspace_trace.in)
- [`docs/qe_inputs/au_slab_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/au_slab_subspace_trace.in)
- [`docs/qe_inputs/sic32_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/sic32_subspace_trace.in)

以及早期 H2 最小样本：

- [`docs/qe_inputs/h2_tiny_gamma.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/h2_tiny_gamma.in)
- [`docs/qe_inputs/h2_small_gamma.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/h2_small_gamma.in)

### 3.5 行为级验证

#### 复数 Ozaki-II / CRT GEMM

已完成：

- 原型：
  - [`model/src/tb_complex_ozaki.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_complex_ozaki.cpp)
- 验证说明：
  - [`model/docs/complex_ozaki_fp64_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md)

状态：

- 主线已经是完整 `FP64 complex GEMM`
- 不再是早期 `INT8_EMU` 近似占位

#### generalized Hermitian 微对角化

已完成：

- 原型：
  - [`model/src/tb_generalized_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_generalized_subspace.cpp)
- 验证说明：
  - [`model/docs/generalized_subspace_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/generalized_subspace_validation.md)

状态：

- 已能在真实 `QE` dump 上验证
  - `Hermitianize`
  - `SPD check`
  - `Cholesky`
  - generalized 到 standard
  - eigensolve
  - back-transform

### 3.6 成本模型初版

已完成：

- [`docs/complex_fp64_gemm_cost_model_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)

已覆盖：

- `L` 个模数下的实数 GEMM 次数
- `3M/4M` 运算量差异
- 输入 / residue / output buffer 量级
- `CRT` 项数
- `32/64/128` tile 的代表性数字

## 4. 正在进行的工作

当前真正处于“进行中但未冻结”的不是实现，而是**算法冻结**。

### 4.1 冻结状态总览

- [`docs/algorithm_freeze_status_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/algorithm_freeze_status_v0.md)

### 4.2 Ozaki / CRT 冻结草案

- [`docs/ozaki_crt_algorithm_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/ozaki_crt_algorithm_freeze_v0.md)

未最终确认的关键点：

1. `L` 策略
   - 固定 `13`
   - 还是主配置 `13`、压力上界 `17`

2. residue 数据流
   - 全模缓存
   - 还是 streaming

3. `CRT` 组织
   - 整块重构
   - 还是 accumulation

4. scaling / integerization contract
   - 当前推荐是 power-of-two row/column scaling + truncation

5. fallback contract
   - 当前推荐是前置保守判定

### 4.3 NML generalized eigensolver 冻结草案

- [`docs/nml_generalized_eigensolver_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/nml_generalized_eigensolver_freeze_v0.md)

未最终确认的关键点：

1. 主路线
   - 当前推荐：direct dense generalized Hermitian solver
   - 不推荐：在近存里再引入 `LOBPCG`

2. tridiagonal 后端
   - 当前推荐：implicit QR

3. 谱范围
   - 当前推荐：`v0` 先做全谱
   - 还没有冻结是否直接做 selective spectrum

4. `CIM` 参与边界
   - 当前推荐：只做 trailing update / dense GEMM

## 5. 之后需要做的事

### 5.1 第一优先级：让用户确认算法冻结项

优先让用户确认这几个决定：

1. `Ozaki/CRT`
   - `L = 13` 还是 `13+17`
   - residue streaming 还是全缓存
   - accumulation CRT 还是整块重构

2. `NML eigensolver`
   - direct dense 还是引入 `LOBPCG`
   - QR 还是更复杂 tridiagonal eigensolver
   - `v0` 先全谱还是直接做部分谱

### 5.2 第二优先级：把冻结结果回写到主设计文档

确认后要同步更新：

- [`docs/design.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/design.md)
- [`docs/complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)
- [`docs/complex_fp64_gemm_cost_model_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)

### 5.3 第三优先级：做可比表/图

冻结后最值得补的是：

1. `Ozaki/CRT` 对比表
   - `3M vs 4M`
   - `L=13 vs 17`
   - streaming vs full-buffer

2. `NML eigensolver` 路线表
   - direct dense vs iterative
   - full spectrum vs partial spectrum

3. workload 到 tile 的映射表
   - 根据当前 `QE` 数据集把 `16/32/64/128` 的必要性讲清楚

### 5.4 第四优先级：继续补边界 workload

当前数据集已经够支撑设计，但还可以补边界样本：

- 更大的分子/有机体系
- 更典型的 `Gamma-only` 固体样本
- 另一个更大的异质超胞，如 `BN32`

这一步是增强，不是当前主阻塞项。

## 6. 可直接复用的命令

### 6.1 重新编译工作区 QE copy

```bash
cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4
```

### 6.2 运行 trace 摘要

```bash
python3 /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/summarize_qe_subspace_trace.py /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_fe_trace.csv
```

### 6.3 构建 generalized_subspace_eval

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
make bin/generalized_subspace_eval
```

### 6.4 运行 generalized_subspace_eval

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
./bin/generalized_subspace_eval
```

## 7. 当前工作区状态

当前存在但尚未提交的核心文件包括：

- 冻结草案文档
- 数据集状态文档
- trace CSV
- generalized eigensolver 行为级代码

用 `git status --short` 可见主要新增项：

- `docs/algorithm_freeze_status_v0.md`
- `docs/ozaki_crt_algorithm_freeze_v0.md`
- `docs/nml_generalized_eigensolver_freeze_v0.md`
- `docs/complex_fp64_gemm_cost_model_v0.md`
- `docs/benchmarks/results/qe_*.csv`
- `docs/qe_inputs/*_subspace_trace.in`
- `model/src/tb_generalized_subspace.cpp`
- `model/docs/generalized_subspace_validation.md`

## 8. 给下一位 agent 的一句话

下一位 agent 不需要重新做矩阵画像，也不需要重新搭 generalized 行为模型。  
当前最该做的是：

- 基于冻结草案，帮用户把 `Ozaki/CRT` 和 `NML` 微对角化两条主算法正式拍板
- 然后把最终结论同步回系统总文档和子系统 spec
