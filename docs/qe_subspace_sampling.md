# QE Davidson 子空间矩阵采样说明

## 1. 目的

这份说明对应当前仓库里对 `QE` 子空间对角化入口新增的采样插桩。  
它的目标是把我们后续论文最关键的一组实验输入先固定下来：

- `QE` 真实路径中的 representative `H_sub / S_sub`
- 它们的规模、动态范围、Hermitian 结构与 overlap 特征
- 可离线复用的真实矩阵样本

当前插桩位置选择在：

- [`cdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/cdiaghg.f90)
- [`rdiaghg.f90`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/LAXlib/rdiaghg.f90)
- 对应的可提交 patch 归档在：
  - [`qe_subspace_sampling_cdiaghg.patch`](/Volumes/remote/phd/year_2/project/dft加速/docs/patches/qe_subspace_sampling_cdiaghg.patch)
  - [`qe_subspace_sampling_rdiaghg.patch`](/Volumes/remote/phd/year_2/project/dft加速/docs/patches/qe_subspace_sampling_rdiaghg.patch)

也就是说，采到的是**真正送进子空间对角化器的 reduced matrix**，而不是更早期的中间临时块。

## 2. 当前覆盖范围

当前采样覆盖的是 `LAXlib` CPU LAPACK 路径：

- `laxlib_cdiaghg`
- `laxlib_rdiaghg`

这对当前 paper cut 已经够用，因为我们关心的正是：

- Davidson 子空间对角化前的 `H_sub`
- generalized 情形下的 `S_sub`

需要注意：

- 如果后续采用 GPU eigensolver 路径，当前这套插桩不会自动命中 GPU 版本
- 做画像采样时，建议先用 CPU diagonalization 路径拿样本

## 3. 环境变量

### 3.1 统计 trace

设置：

```bash
export QE_SUBSPACE_TRACE_FILE=/abs/path/qe_subspace_trace.csv
```

效果：

- 在每次进入 `cdiaghg/rdiaghg` 时，向 CSV 追加一行统计信息

### 3.2 导出完整矩阵

设置：

```bash
mkdir -p /abs/path/qe_subspace_dump
export QE_SUBSPACE_DUMP_DIR=/abs/path/qe_subspace_dump
export QE_SUBSPACE_DUMP_LIMIT=16
```

效果：

- 额外导出前若干次调用的完整 `H/S` 矩阵
- 每个矩阵一个 CSV 文件

### 3.3 过滤小矩阵

设置：

```bash
export QE_SUBSPACE_MIN_N=32
```

效果：

- 只采样 `n >= 32` 的调用

## 4. 输出字段

`QE_SUBSPACE_TRACE_FILE` 会生成一个 CSV，字段如下：

- `call_id`
- `solver`
- `n`
- `m`
- `all_eigenvalues`
- `h_frob`
- `h_max_abs`
- `h_min_nz_abs`
- `h_diag_min`
- `h_diag_max`
- `h_diag_imag_max`
- `h_herm_rel`
- `s_frob`
- `s_max_abs`
- `s_min_nz_abs`
- `s_diag_min`
- `s_diag_max`
- `s_diag_imag_max`
- `s_herm_rel`
- `s_identity_rel`

字段含义：

- `h_herm_rel` / `s_herm_rel`
  - 衡量矩阵偏离 Hermitian / symmetric 的相对量
- `s_identity_rel`
  - 衡量 `S_sub` 偏离单位阵的程度
  - 用于区分“近似标准问题”与“明显 generalized 问题”

## 5. 完整矩阵导出格式

当 `QE_SUBSPACE_DUMP_DIR` 打开时，会生成如下文件：

- `cdiaghg_H_call000001_n64_m32.csv`
- `cdiaghg_S_call000001_n64_m32.csv`
- `rdiaghg_H_call000002_n48_m24.csv`

格式统一为：

```text
row,col,real,imag
1,1,...
1,2,...
```

这样后续不管是 Python、MATLAB 还是 Julia，都可以很直接地离线重建矩阵。

## 6. 建议的采样组织方式

为了对齐我们已经定义好的实验包，建议按下面 4 类组织采样。

### 6.1 数学对照集

来源：

- 当前 `SystemC` / CPU 参考模型中的随机矩阵

用途：

- 纯 `GEMM` 精度验证

### 6.2 结构化科学计算集

来源：

- 人工构造的 Hermitian / generalized Hermitian 矩阵
- `Q^H H Q / Q^H S Q` 型结构化块

用途：

- 证明系统不是只会做随机矩阵

### 6.3 QE 真实样本

来源：

- 本文档说明的 `QE` trace + dump

用途：

- 形成最重要的一组 representative matrices
- 回答“和真实 DFT workload 的关系是什么”

### 6.4 压力测试集

来源：

- 从导出的真实样本中挑选坏案例
- 或根据真实样本统计规律构造更极端样本

用途：

- 评估缩放、模数需求、fallback 边界

## 7. 推荐运行方式

一个最小可用的采样流程可以是：

```bash
mkdir -p /abs/path/qe_subspace_dump
export QE_SUBSPACE_TRACE_FILE=/abs/path/qe_subspace_trace.csv
export QE_SUBSPACE_DUMP_DIR=/abs/path/qe_subspace_dump
export QE_SUBSPACE_DUMP_LIMIT=12
export QE_SUBSPACE_MIN_N=32
```

然后运行代表性的 `QE` 输入，例如：

- [`h2_tiny_gamma.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/h2_tiny_gamma.in)
- [`h2_small_gamma.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/h2_small_gamma.in)

之后再用：

- [`summarize_qe_subspace_trace.py`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/summarize_qe_subspace_trace.py)

对 CSV 做初步汇总。

## 8. 下一步最该采的字段

为了后面做系统论文里的 workload 画像，建议先回答这几件事：

1. 维度分布
   - `n` 和 `m` 主要落在哪些点
2. overlap 结构
   - `S_sub` 距离单位阵有多远
3. 动态范围
   - `h_max_abs / h_min_nz_abs`
   - `s_max_abs / s_min_nz_abs`
4. 结构稳定性
   - `h_herm_rel`
   - `s_herm_rel`
5. representative dumps
   - 至少保存每个主要维度点的一组 `H/S` 样本

只要这一步先做好，后面的 `Ozaki-II` 模数选择、buffer 设计、坏案例压力测试，都会更有依据。

## 9. 当前已拿到的真实样本

截至 `2026-03-12`，已经在工作区副本 `soft/qe-7.5` 上完成了两组 `Si` SCF 样本的采样：

- [`qe_si_medium_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_medium_trace.csv)
- [`qe_si_large_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_large_trace.csv)

对应的阶段性整理已经并入：

- [`project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/project_development_timeline.md)

当前这两组样本已经足够支持几个重要判断：

- 非 `Gamma` `Si` SCF 路径全部命中 `cdiaghg`
- 主路径是复数 generalized Hermitian，而不是标准实对称问题
- Davidson 子空间的主导维度点符合 `n ≈ m` 到 `n ≈ 2m`
- `S_sub` 经常明显偏离单位阵，因此 generalized 路径必须作为主系统路径设计
