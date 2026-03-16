# QE Davidson 子空间矩阵画像（2026-03-12）

## 1. 采样目的

这份小结记录了当前在工作区副本 `soft/qe-7.5` 上完成的两组真实 `QE` 子空间采样结果。  
它的作用不是替代原始 trace，而是把后续系统设计最需要的几个事实先固定下来：

- `QE Davidson` 在真实 `Si` SCF 中到底送入了什么类型的小矩阵
- 子空间维度 `n` 与目标本征对数 `m` 的真实分布是什么
- generalized 路径是否是常态
- 这些结果对 `NML + CIM` 系统尺寸意味着什么

原始 trace 文件：

- [`qe_si_medium_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_medium_trace.csv)
- [`qe_si_large_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_large_trace.csv)

原始矩阵 dump：

- [`tmp_qe_si_medium_dump`](/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump)
- [`tmp_qe_si_large_dump`](/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump)

## 2. 采样设置

### 2.1 运行环境

- 仅使用当前工作区副本 [`soft/qe-7.5`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5)
- 本地构建目录：
  - [`build_subspace_trace`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace)
- 实际运行二进制：
  - [`pw.x`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace/bin/pw.x)

### 2.2 输入样本

- [`si.scf.medium.in`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/test_si/si.scf.medium.in)
  - `nbnd = 8`
  - `4x4x4` k-point
  - `ecutwfc = 18 Ry`
- [`si.scf.large.in`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/test_si/si.scf.large.in)
  - `nbnd = 16`
  - `4x4x4` k-point
  - `ecutwfc = 24 Ry`

### 2.3 采样入口

采样插桩位于：

- [`cdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/cdiaghg.f90)
- [`rdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/rdiaghg.f90)

本次 `Si` 样本命中的只有 `cdiaghg`，因此画像对应的是：

- 非 `Gamma` 的复数路径
- 复数 generalized Hermitian 子空间对角化

## 3. 结果摘要

### 3.1 `si.scf.medium`

- 总调用次数：`180`
- 求解器：全部是 `cdiaghg`
- generalized-like 调用：`140 / 180`
- standard-like 调用：`40 / 180`
- 主导维度点：
  - `(n, m) = (16, 8)` 出现 `67` 次
  - `(n, m) = (8, 8)` 出现 `48` 次
  - `(n, m) = (12, 8)` 出现 `16` 次
  - `(n, m) = (10, 8)` 出现 `15` 次
- Hermitian 误差：
  - `h_herm_rel <= 2.275e-15`
  - `s_herm_rel <= 6.151e-16`
- overlap 偏离单位阵程度：
  - `s_identity_rel` 最大到 `7.803e-01`

### 3.2 `si.scf.large`

- 总调用次数：`216`
- 求解器：全部是 `cdiaghg`
- generalized-like 调用：`184 / 216`
- standard-like 调用：`32 / 216`
- 主导维度点：
  - `(n, m) = (32, 16)` 出现 `57` 次
  - `(n, m) = (16, 16)` 出现 `40` 次
  - `(n, m) = (24, 16)` 出现 `17` 次
  - `(n, m) = (20, 16)` 出现 `17` 次
- Hermitian 误差：
  - `h_herm_rel <= 2.640e-15`
  - `s_herm_rel <= 8.038e-16`
- overlap 偏离单位阵程度：
  - `s_identity_rel` 最大到 `8.657e-01`

## 4. 可以直接锁定的系统事实

### 4.1 当前主路径是复数 generalized Hermitian，而不是实数标准问题

这组 `Si` 样本完全命中 `cdiaghg`，没有进入 `rdiaghg`。  
同时 generalized-like 调用占比很高：

- `medium`: `77.8%`
- `large`: `85.2%`

这意味着当前系统论文如果只强调“标准 Hermitian 小矩阵”，口径是不够准确的。  
`S_sub` 必须进入主设计，而不是只当作偶发扩展。

### 4.2 Davidson 子空间维度确实沿着 `m -> 2m` 扩张

这次 trace 的主导维度非常稳定：

- `nbnd = 8` 时，主要落在 `n = 8` 和 `n = 16`
- `nbnd = 16` 时，主要落在 `n = 16` 和 `n = 32`

这和 `QE` 默认 Davidson 子空间上限 `nbndx ≈ 2 * nbnd` 的行为一致。  
对于当前 paper cut，可以先把代表性 `N` 窗口锁在：

- `N = 16`
- `N = 32`

再把 `64 / 128 / 256` 作为可组合 tile 的架构目标，而不是说当前 `QE` trace 已经直接证明了这些尺寸都会频繁出现。

### 4.3 `H_sub` 与 `S_sub` 的结构很稳定

两组样本里：

- `H_sub` 一直保持到 `1e-15` 量级的 Hermitian 相对误差
- `S_sub` 也保持到 `1e-15 ~ 1e-16` 量级

这说明：

- “Hermitian / generalized Hermitian 微求解器”这个系统切口是成立的
- 我们后续在 `NML` 侧假设只需要处理 Hermitian 结构，是被真实 `QE` 工作负载支持的

### 4.4 `S_sub` 明显经常不是单位阵

`s_identity_rel` 的最大值达到：

- `0.7803` (`medium`)
- `0.8657` (`large`)

这已经不是“接近单位阵，可忽略 overlap”的量级。  
也就是说：

- generalized 路径不是边角情况
- `Q^H S Q`
- `H_sub c = lambda S_sub c`
- `S` 的 Hermitian / 正定处理

都应当作为主系统路径去设计

## 5. 对系统设计的直接约束

### 5.1 对 `CIM complex GEMM` 子系统

至少要原生覆盖：

- `Q^H H Q`
- `Q^H S Q`
- `H_sub X`
- `S_sub X`

也就是说，复数 `FP64 GEMM` 不是“顺手支持一下”，而是 generalized 子空间路径的直接计算底座。

### 5.2 对 `NML` 微对角化器

当前最先值得做的不是大而全的通用矩阵引擎，而是：

- `N = 16 / 32` 优先优化
- generalized Hermitian 直接支持
- 先把 `Cholesky -> standard Hermitian -> tridiagonal -> eigen solve -> back-transform` 这条闭环打通

这是因为真实 trace 已经说明，这两个规模点在当前 `QE` 样本里占比最高。

### 5.3 对评测方法

随机矩阵仍然需要，但已经不能作为主证据。  
后续论文评测至少要区分：

- 随机 / 数学基准
- 结构化 Hermitian / generalized Hermitian
- `QE` 真实子空间样本

而且 `QE` 样本里要显式报告：

- `n`
- `m`
- generalized 占比
- `s_identity_rel`

## 6. 下一步建议

在这组画像基础上，最自然的下一步是：

1. 把 `N = 16 / 32` 的 generalized Hermitian 微对角化闭环加入行为模型
2. 把 `Q^H H Q / Q^H S Q` 的 complex `FP64 GEMM` 调用次数和尺寸继续采到更多体系
3. 再补一组 `Gamma` 与更大体系样本，验证 `rdiaghg` 和更高 `nbnd` 的分布是否改变结论

到这一步，系统设计、真实工作负载画像和行为级验证三件事就能首尾闭环了。
