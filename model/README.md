# `model/` 模型总览

这个目录里现在实际上有 **三类模型**，不是一套单一模型。

如果不先分清这三类东西，很容易把：

- 乘法/矩阵算子原型
- reduced-space 微对角化原型
- QE shell 级系统模型

混成一件事。

## 1. 先说结论

`model/` 下面当前可以按下面的结构理解：

1. **算子级 / kernel 级行为模型**
   - 重点是 `complex FP64 GEMM`、复数 residue / CRT / Ozaki-II 这条线
   - 这是你说的“像乘法器”的那一部分
2. **迭代子空间微对角化行为模型**
   - 重点是固定矩阵负载下的 `HX / SX / reduced generalized solve / basis update`
   - 它已经不是单纯乘法器，而是“tile 乘法 + 小规模广义特征值求解”的组合
3. **QE shell / system-level runnable model**
   - 重点是 `Host -> FPGA -> Chip` 级别的 shell contract、数据流和 timed-functional proxy
   - 这就是 `model/qe_band_solver_model/`

所以：

- **旧 standalone evaluator 那套现在收口在 `model/ozaki_subspace_model/`**
- **新 `model/qe_band_solver_model/` 更像系统级 runnable model**

## 2. 目录怎么读

### 2.1 老的算子 / testbench 体系

这部分由：

- `model/ozaki_subspace_model/src/*.cpp`
- `model/ozaki_subspace_model/include/iterative_subspace_engine.h`
- `model/ozaki_subspace_model/Makefile`

驱动。

它们通过 `make -C model/ozaki_subspace_model ...` 构建几个 standalone evaluator。

主要 target 有：

- `bin/complex_ozaki_eval`
- `bin/generalized_subspace_eval`
- `bin/iterative_subspace_eval`
- `bin/iterative_tile_gemm_eval`
- `bin/iterative_micro_compare_eval`
- `bin/iterative_qe_regression_eval`

这部分不是一个完整系统，而是一组：

- 行为级算子验证程序
- 微求解器验证程序
- 回归/对比 testbench

### 2.2 新的 `qe_band_solver_model`

这部分在：

- `model/qe_band_solver_model/`

它是独立的 `CMake` 工程，当前已经转成：

- `include/` 放头文件
- `src/` 放实现文件

构建方式是：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j
```

它和老的 `Makefile` 体系是并列关系，不共享同一个 build 入口。

## 3. 各套模型分别干什么

### 3.1 `tb_complex_ozaki.cpp`

对应：

- `model/ozaki_subspace_model/src/tb_complex_ozaki.cpp`
- 文档：`model/ozaki_subspace_model/docs/complex_ozaki_fp64_validation.md`

这是当前最像“乘法器模型”的一套。

它的核心目标是验证：

- 复数 `FP64` 矩阵乘法
- `Ozaki-II`
- residue / CRT / Karatsuba 3M

也就是说它本质上是：

> 复数高精度矩阵乘法 / 乘加 datapath 的行为级验证器

如果你只问“`model/` 下面是不是主要有一套乘法器模型”，那最像的就是它。

### 3.2 `tb_generalized_subspace.cpp`

对应：

- `model/ozaki_subspace_model/src/tb_generalized_subspace.cpp`
- 文档：`model/ozaki_subspace_model/docs/generalized_subspace_validation.md`

这套不是乘法器，而是：

> reduced generalized Hermitian eigensolver 的行为级 reference/validation

它关心的是：

- `H_sub / S_sub`
- Cholesky
- standardize
- eigensolve
- back-transform

所以它是：

- 数学闭环验证
- reference-grade 小矩阵求解链

而不是硬件阵列本身。

### 3.3 `iterative_subspace_engine.*` 这一套

对应：

- `model/ozaki_subspace_model/include/iterative_subspace_engine.h`
- `model/ozaki_subspace_model/src/iterative_subspace_engine.cpp`
- 文档：`model/ozaki_subspace_model/docs/iterative_subspace_flow.md`

这套是一个中间层。

它把两类东西串起来：

1. **tile 级矩阵算子**
   - `Matrix_Resident_Tile`
   - `Complex_Row_Bank`
   - `Row_Residue_Buffer`
   - `Mod_Encode_Unit`
   - `Residue_3M_MAC`
2. **reduced-space 微求解器**
   - `Reduced_Generalized_MicroSolver`
   - `Reduced_Projection_Unit`
   - `Reduced_Cholesky_Unit`
   - `Reduced_Standardize_Unit`
   - `Hermitian_Jacobi_Unit`
   - `Reduced_Backtransform_Unit`

所以它不是单纯乘法器，也不是完整系统。

更准确地说，它是：

> 固定矩阵负载下的“tile 乘法 + reduced generalized solve + basis update”行为级引擎

### 3.4 与 `iterative_subspace_engine` 配套的 testbench

#### `tb_iterative_tile_gemm.cpp`

这套主要验证：

- `Matrix_Resident_Tile`
- `HX / SX`
- row buffer / residue encode / CRT reconstruct

它更偏：

> tile 级矩阵乘法通路验证

所以这部分也很像“乘法器 / GEMM datapath 验证”。

#### `tb_iterative_subspace.cpp`

这套跑的是：

- fixed-step iterative refinement
- `HX / SX`
- `X` 子空间 solve
- `Q = [X, W]` 或 `Q = [X, W, P]`
- basis update

它更像：

> 一个固定步数的 iterative generalized subspace 行为模型

#### `tb_iterative_micro_compare.cpp`

这套做的是：

- reduced solver mode 间对比
- 和 reference eigensolver 对比
- 看误差、残差、`B`-orth defect、cycle 统计

它更偏：

> 微求解器对比实验台

#### `tb_iterative_qe_regression.cpp`

这套做的是：

- 用真实 QE dump case 做 regression
- 比较 mode 0/1/2
- 统计 hit-rate、cycles、误差

它更偏：

> 面向 QE dump 的回归验证器

### 3.5 `qe_band_solver_model/`

这套现在是新主线。

它不是旧的：

- 乘法器验证器
- reduced micro-solver 验证器

而是：

> `QE` shell contract / system-level / timed-functional runnable model

当前它已经进一步改成 cluster-first 主路径：

- `HostSCF`
- `FPGAOrchestrator`
- `ChipTop`
- `EpisodeController`
- `ClusterGraphExecutor`
- `Cluster A/B/C/D`

但它本质上仍然是：

- runnable model
- timed-functional proxy
- system integration skeleton

不是数值 faithful 的 full DFT solver，也不是 RTL。

## 4. 所以现在 `model/` 下面最合理的分类方式

可以直接按下面这张表记：

| 类别 | 主要文件 | 作用 | 更像什么 |
| --- | --- | --- | --- |
| 复数 GEMM / residue 原型 | `tb_complex_ozaki.cpp` | 验证 Ozaki-II / residue / CRT 复数乘法链 | 乘法器 / GEMM datapath |
| generalized subspace reference | `tb_generalized_subspace.cpp` | 验证 reduced generalized Hermitian 数学闭环 | 小规模 eigensolver reference |
| iterative subspace engine | `iterative_subspace_engine.*` + iterative tbs | 把 tile 乘法和微求解器串起来 | kernel-composition 行为模型 |
| QE shell runnable model | `qe_band_solver_model/` | 建模 `Host/FPGA/Chip` + cluster-first episode | 系统级 timed-functional proxy |

## 5. 如果你现在只想盯“乘法器那套”

那优先看这几处：

- `model/ozaki_subspace_model/src/tb_complex_ozaki.cpp`
- `model/ozaki_subspace_model/src/tb_iterative_tile_gemm.cpp`
- `model/ozaki_subspace_model/include/iterative_subspace_engine.h`
- `model/ozaki_subspace_model/src/iterative_subspace_engine.cpp`
- `model/ozaki_subspace_model/docs/complex_ozaki_fp64_validation.md`
- `model/ozaki_subspace_model/docs/iterative_subspace_flow.md`

其中：

- `complex_ozaki` 更像纯乘法链验证
- `iterative_tile_gemm` 更像 tile/resident-row-buffer 乘法通路验证

## 6. 如果你现在想盯“新系统主线”

那就看：

- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/include/`
- `model/qe_band_solver_model/src/`

它现在已经和老的 `Makefile` evaluator 体系分开了。

## 7. 一句话版

`model/` 下面现在不是“一套乘法器模型”，而是：

- **一套乘法 / GEMM / residue 原型**
- **一套 iterative subspace 微对角化原型**
- **一套 QE shell 系统级 runnable model**

如果只说“最像乘法器的是哪套”，答案是：

> `tb_complex_ozaki.cpp` 和 `iterative_tile_gemm` 这一支。
