# 广义 Hermitian 子空间微对角化行为级验证

## 1. 目的

这份验证对应当前新增的行为级 testbench：

- [`tb_generalized_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/ozaki_subspace_model/src/tb_generalized_subspace.cpp)

它验证的不是 `CIM` 阵列本身，而是我们在系统设计里定义的 `NML` 侧 generalized Hermitian 微对角化闭环：

1. `H_sub / S_sub` 显式 Hermitian 化
2. 对 `S_sub` 做 Cholesky
3. 将 `H_sub c = lambda S_sub c` 变换成标准 Hermitian 问题
4. 对标准问题求本征对
5. 回代恢复 generalized 本征向量

这里的目标是先回答两个问题：

- 这条 `NML` 数学主链是否和直接 `zhegv` 一致
- 在真实 `QE` 导出的 `H_sub / S_sub` 上，数值误差和残差能否稳定保持在 `FP64` 水平

## 2. 输入样本

当前 testbench 默认直接读取真实 `QE` 采样 dump：

- [`tmp_qe_si_medium_dump`](/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump)
- [`tmp_qe_si_large_dump`](/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump)

也就是说，这一版不是随机玩具矩阵，而是直接对以下路径里真正送入对角化器的小矩阵做验证：

- `QE` `cdiaghg`
- complex generalized Hermitian subspace matrices

## 3. 数值后端

行为级求解器使用 macOS `Accelerate` 提供的 LAPACK/BLAS 作为 reference-grade 数值后端：

- `zhegv`
- `zheev`
- `zpotrf`
- `ztrsm`

这意味着：

- 它非常适合验证 `NML` 算法链的正确性
- 但它还不是 cycle-accurate 的硬件微架构模型

## 4. 构建与运行

构建：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
make -C model/ozaki_subspace_model bin/generalized_subspace_eval
```

运行：

```bash
./model/ozaki_subspace_model/bin/generalized_subspace_eval
```

可选环境变量：

- `GEN_SUBSPACE_DIRS`
  - 逗号分隔的 dump 目录列表
- `GEN_SUBSPACE_MAX_CASES`
  - 限制处理的样本数

默认会处理两组 `Si` dump 中的全部 `32` 个 `H/S` pair。

## 5. 评测指标

对每个样本，testbench 会比较：

- `eig_max_rel`
  - 与直接 `zhegv` 相比的最大相对特征值误差
- `eig_rms_rel`
  - 相对特征值误差均方根
- `res_max`
  - generalized 残差 `||H v - lambda S v||`
- `res_rms`
  - generalized 残差均方根
- `Sorth`
  - `V^H S V - I` 的缺陷

## 6. 当前结果

本次在 `32` 个真实 `QE` 样本上的运行结果是：

- `ok_cases = 32 / 32`
- `avg eig_max_rel = 5.461946e-15`
- `max eig_max_rel = 2.652706e-14`
- `avg residual_max = 2.239396e-16`
- `max residual_max = 4.617593e-16`
- `avg S-orth defect = 3.793651e-15`
- `max S-orth defect = 7.650607e-15`

也就是说，在当前 `FP64` 行为级条件下：

- 这条 `Hermitianize -> Cholesky -> standardize -> eig -> back-transform` 闭环可以稳定复现 `zhegv`
- 在真实 `QE` 子空间样本上，误差维持在 `1e-14 ~ 1e-16` 量级

## 7. 对系统设计的意义

这组结果让我们可以更有把握地把 `NML` 微对角化器写成系统主路径的一部分：

- generalized Hermitian 是真实主路径，不是边角情况
- `N = 16 / 32` 是当前 `QE` 样本里最重要的优先尺寸
- 行为级算法闭环已经成立，后面可以继续往：
  - `Ozaki-II` 复数 `FP64 GEMM`
  - `Q^H H Q / Q^H S Q`
  - 更明确的 `NML/CIM` 边界
  这些方向推进

## 8. 当前边界

这份验证还没有覆盖：

- cycle-accurate 的 `NML` datapath 时序
- 将 `Ozaki-II / CRT complex GEMM` 与微对角化器放入同一个统一 executable
- 部分谱求解器调度，例如更接近 `QE diaghg` 的 `m < n` selective path

所以这份 testbench 的定位应理解为：

- 已经回答“这条 generalized Hermitian 微对角化数学链能不能在真实 `QE` 样本上稳定工作”
- 还没有回答“具体硬件流水如何切拍、如何计面积和吞吐”
