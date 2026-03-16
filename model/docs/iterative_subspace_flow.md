# 固定矩阵负载迭代微对角化流程说明

## 1. 文档目的

这份文档描述当前新增的 fixed-matrix iterative diagonalization 行为级模块如何组织。

它不负责冻结最终算法选择，而是先把当前代码中的模块划分、输入输出、数据流和 build 组织写清楚，避免后续继续把实现、架构和测试混在一起。

当前对应的主要代码为：

- `model/include/iterative_subspace_engine.h`
- `model/src/iterative_subspace_engine.cpp`
- `model/src/tb_iterative_subspace.cpp`
- `model/src/tb_iterative_qe_regression.cpp`

## 2. 当前模块划分

### 2.1 Matrix_Resident_Tile

这个类负责建模“本地固定矩阵负载”这一硬件侧角色。

这一步之后，它已经不再是单一黑盒矩阵乘抽象，而是被拆成更接近目标架构的几个子角色：

- `Complex_Row_Bank`
  - 分别保存固定矩阵的 `real bank` / `imag bank`
  - 以行读出方式向后级提供一整行复数数据
- `Row_Residue_Buffer`
  - 建模 tile 内的行级热数据缓存
  - 当前是行为级的多行常驻缓存，用 `matrix_tag + row + shift` 识别命中
  - `H` 与 `S` 的已编码行在一次 `bind()` 之后可跨多轮 `HX / SX / HQ / SQ` 复用
  - 早期 `row_hits = 0` 的直接原因是缓存只有单行，顺序扫完整个矩阵后下一次访问又从第 0 行开始，前一轮留下的最后一行无法形成有效复用
- `Mod_Encode_Unit`
  - 建模按行读出后的局部 encode 边界
  - 当前已实现 power-of-two scaling + truncation 的行为级整数化
  - 当前实现使用 `L = 16` 的 `< 8-bit` 互素模数组把一行复数数据映射到 residue 域
- `Residue_3M_MAC`
  - 建模复数 `3M` 路径的行乘加
  - 当前在每个模数上执行 `p0 / p1 / p2`，再做 CRT reconstruction 回到输出边界

`Matrix_Resident_Tile` 现在负责把这些子块串起来，完成：

- 绑定固定的 `H_sub`
- 绑定固定的 `S_sub`
- 对每个输出行执行：bank read -> row buffer lookup/fill -> local encode -> `3M` accumulate
- 对 `compute_hx()` / `compute_sx()` 做 cycle 记账
- 输出 row-buffer / residue encode / CRT reconstruct 统计

当前这些子模块仍然是行为级模型，还没有引入：

- 多行或多路 residue buffer 组织
- `L = 13/17` 那样的可配置模数组策略
- 更真实的 encode / reconstruct 位宽与 overflow guard
- tile 内并行 lane 与冲突调度

当前这版已经把 `compute_hx()` / `compute_sx()` 的数值 contract 收敛到更接近 `complex FP64 GEMM` 主线的形式：

- 矩阵侧按行做 power-of-two scaling
- 输入 block 向量按列做 power-of-two scaling
- `16` 个 `< 8-bit` 模数上的 `3M`
- 输出边界做 `CRT` 有符号重构

### 2.2 Reduced_Generalized_MicroSolver

这个类负责建模 `NML` 里的 reduced-space 微求解部分。

它当前由更细的行为级子块组成：

- `Reduced_Projection_Unit`
  - 负责构造 `Q^H H Q` 与 `Q^H S Q`
  - 单独记 `reduced_build_ops`
- `Reduced_Cholesky_Unit`
  - 负责对 reduced `B = Q^H S Q` 做微型复数 Cholesky
  - 单独记 `reduced_cholesky_ops`
- `Reduced_Standardize_Unit`
  - 负责把 `A z = lambda B z` 变换成标准 Hermitian 问题
  - 当前实现是 `L^{-1} A L^{-H}`
  - 单独记 `reduced_standardize_ops`
- `Hermitian_Jacobi_Unit`
  - 负责对标准化后的小矩阵做固定上界 sweep 的 Hermitian Jacobi
  - 单独记 `reduced_jacobi_ops`
- `Reduced_Backtransform_Unit`
  - 负责把标准问题本征向量回代到 generalized 系数空间
  - 当前实现是 `z = L^{-H} y`，并做 `B`-度量归一化
  - 单独记 `reduced_backtransform_ops`
- `Reduced_Generalized_MicroSolver`
  - 负责把上述微子块串起来，完成 reduced generalized problem 的小规模求解
  - 单独记 `qhqx_ops`

当前支持两个 reduced solver mode：

- `mode = 0`
  - `Cholesky -> standardize -> Hermitian Jacobi -> back-transform`
  - 更接近 generalized Hermitian 数学主链
- `mode = 1`
  - 显式 `B^{-1}A` 近似后再做 Hermitian Jacobi
  - 省掉 `Cholesky/back-transform`
  - 更便宜，但更依赖 reduced matrix 条件和外层子空间构造
- `mode = 2`
  - hybrid dispatcher
  - `X` 子空间优先走 `B^{-1}A + Jacobi`
  - 扩展 `Q` 子空间回到 `Cholesky -> standardize -> Jacobi -> back-transform`
  - 开启 `history P` 时直接整体退回稳路径

引擎里另外还新增了两个更接近硬件边界的子块：

- `Subspace_Ortho_Unit`
  - 负责 `S`-正交化
  - 单独记 `ortho_ops`
- `Basis_Update_Unit`
  - 负责 `X <- XU`、`X <- QY`
  - 单独记 `basis_update_ops`

它们当前完成：

- 在 `X` 子空间上解 reduced generalized problem
- 在 `Q = [X, W]` 扩展子空间上解 reduced generalized problem
- 对投影构造、正交化、basis update、reduced solver 分别做 cycle 记账

当前它仍是纯行为级实现，用的是小规模矩阵显式构造与求解。
不过它已经不再是单个软件黑盒求解函数，而是拆成了可单独计数的 `Cholesky -> standardize -> Jacobi -> back-transform` 微数据通路。

### 2.3 Iterative_Subspace_Engine

这个 `SystemC` 模块负责把 tile 和 microsolver 串成固定步长迭代流程。

它当前负责：

- 读取配置：`n`、`m`、`steps`
- 装载输入矩阵与初始 block vector
- 执行 fixed-step 迭代
- 输出 Ritz 值与候选本征向量
- 输出统计：
  - `total_cycles_used`
  - `hx_ops_used`
  - `sx_ops_used`
  - `qhqx_ops_used`
  - `ortho_ops_used`
  - `basis_update_ops_used`
  - `reduced_build_ops_used`
  - `reduced_cholesky_ops_used`
  - `reduced_standardize_ops_used`
  - `reduced_jacobi_ops_used`
  - `reduced_backtransform_ops_used`

## 3. 当前算法流程

当前引擎默认实现的是 `Q = [X, W]` 的 fixed-step generalized refinement 行为模型。

同时保留了一个可选的 `LOBPCG-like` 试验开关：

- 设置 `ITER_USE_HISTORY_P=1` 时，扩展子空间切换为 `Q = [X, W, P]`

其中：

- `X`：当前 block Ritz vector
- `W`：当前 residual block
- `P`：上一轮更新得到的历史方向块

由于当前行为模型仍然受 `n` 维 reduced matrix 约束，`W / P` 的实际列数会按 `n - m` 的可用空间自动裁剪，而不是无条件取满 `3m` 维。

当前试验版 `Q = [X, W, P]` 仅用于方案探索，不作为默认稳定路径。

每轮流程为：

1. tile 计算 `HX = H_sub X`
2. tile 计算 `SX = S_sub X`
3. microsolver 在 `X` 子空间上解 reduced generalized problem
4. 用 reduced-space 解更新 `X`
5. 对 `X` 做一次 `S`-正交化
6. 重新计算 `HX` 与 `SX`
7. 构造 residual block `W`
8. 构造扩展子空间
   - 默认：`Q = [X, W]`
   - 试验模式：`Q = [X, W, P]`
9. tile 计算 `HQ = H_sub Q`
10. tile 计算 `SQ = S_sub Q`
11. microsolver 在 `Q` 子空间上解 reduced generalized problem
12. 取最低 `m` 个方向更新下一轮 `X`

固定跑 `T` 步后输出。

## 3.1 当前整体框图

```text
                +--------------------------------------------------+
                |          Iterative_Subspace_Engine               |
                |--------------------------------------------------|
start/n/m/steps | 1) load H_sub / S_sub / X0                       |
--------------->| 2) fixed-step iterative refinement               |
                +-------------------------+------------------------+
                                          |
                                          v
          +-------------------------------+-------------------------------+
          |                       Matrix_Resident_Tile                    |
          |---------------------------------------------------------------|
          |  Complex_Row_Bank(H)      Complex_Row_Bank(S)                 |
          |          |                         |                           |
          |          +---- row read ---------- +                           |
          |                     |                                         |
          |               Row_Residue_Buffer                              |
          |                     | hit/miss                                |
          |                Mod_Encode_Unit                                |
          |                     |                                         |
          |                Residue_3M_MAC                                 |
          |                     | CRT reconstruct                         |
          +---------------------+--------------------+--------------------+
                                |                    |
                                v                    v
                               HX                   SX
                                |                    |
                                +----------+---------+
                                           |
                                           v
          +----------------------------------------------------------------+
          |               Reduced_Generalized_MicroSolver                   |
          |----------------------------------------------------------------|
          | Reduced_Projection_Unit : A=Q^H H Q, B=Q^H S Q                  |
          |    mode 0 : Cholesky -> standardize -> Jacobi -> backtransform  |
          |    mode 1 : B^{-1}A approx -> Jacobi                            |
          |    mode 2 : stage hybrid dispatcher                             |
          +-------------------------------+--------------------------------+
                                          |
                                          v
          +-------------------------------+--------------------------------+
          |  Basis_Update_Unit   +   Subspace_Ortho_Unit (S-metric)        |
          +-------------------------------+--------------------------------+
                                          |
                                          v
                                   next X / Ritz pair
```

## 4. Testbench 当前行为

`tb_iterative_subspace.cpp` 当前支持两类输入：

### 4.1 优先尝试 QE dump 风格输入

它会优先尝试从 dump 目录中寻找：

- `*_H_call*_n*_m*.csv`
- 对应的 `*_S_call*_n*_m*.csv`

相关环境变量：

- `ITER_USE_QE_CASE`
- `ITER_SUBSPACE_DIRS`

### 4.2 回退到随机矩阵

如果没有找到真实 dump：

- 生成随机 Hermitian `H`
- 生成随机 HPD `S`
- 生成随机复数初始 `X`

这保证模块开发期间始终可跑。

## 5. 当前 build 组织

从这一步开始，`model` 下的编译缓存统一放到：

- `model/build/obj/`

而不是继续把 `.o` 文件写进 `model/src/`。

当前目标：

- `bin/iterative_subspace_eval`
- `bin/iterative_qe_regression_eval`

对应命令：

```bash
make -C model bin/iterative_subspace_eval
./model/bin/iterative_subspace_eval
```

微求解器模式可通过环境变量切换：

```bash
ITER_MICRO_SOLVER_MODE=0 ./model/bin/iterative_subspace_eval
ITER_MICRO_SOLVER_MODE=1 ./model/bin/iterative_subspace_eval
ITER_MICRO_SOLVER_MODE=2 ./model/bin/iterative_subspace_eval
```

单独比较 reduced solver 的命令：

```bash
make -C model bin/iterative_micro_compare_eval
./model/bin/iterative_micro_compare_eval
```

真实 `QE` dump 批量回归命令：

```bash
make -C model bin/iterative_qe_regression_eval
ITER_REG_DIRS=/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_actual_medium_dump \
ITER_REG_MAX_CASES=8 ./model/bin/iterative_qe_regression_eval
```

## 5.1 当前性能快照

以下结果来自 `2026-03-13` 的当前工作区运行。

注意：

- 当前工作区缺少 `tmp_qe_si_medium_dump` / `tmp_qe_si_large_dump`
- 因此下面的 `iterative_subspace_eval` 与 `iterative_micro_compare_eval` 都使用 `random_fallback`

### `n = 16, m = 8, steps = 6`

| mode | history_p | cycles | max_residual | 说明 |
|---|---:|---:|---:|---|
| `0` | `0` | `17985` | `6.916019e-12` | 基准稳路径 |
| `1` | `0` | `12801` | `6.916285e-12` | 最快，当前 case 精度未退 |
| `2` | `0` | `17409` | `6.919164e-12` | hybrid，保守省拍 |
| `0` | `1` | `17985` | `6.917097e-12` | 稳定 |
| `1` | `1` | `12801` | `1.401936e+00` | 失稳 |
| `2` | `1` | `17985` | `6.917097e-12` | 自动退回稳路径 |

### `n = 32, m = 8`

| steps | mode | cycles | max_residual | 说明 |
|---:|---:|---:|---:|---|
| `6` | `0` | `21413` | `8.445698e-01` | 外层 fixed-step 未收敛 |
| `6` | `1` | `16229` | `8.445698e-01` | 残差相同，solver 不是瓶颈 |
| `6` | `2` | `20837` | `8.445698e-01` | hybrid 稍降 cycle |
| `10` | `0` | `36037` | `2.980537e-01` | 增步数后明显收敛 |
| `10` | `2` | `35077` | `2.980537e-01` | 相同残差下略降 cycle |
| `12` | `0` | `43349` | `1.702190e-01` | 继续收敛 |
| `12` | `2` | `42197` | `1.702190e-01` | 相同残差下略降 cycle |

当前可以先得出的判断是：

- `mode = 1` 适合做 `Q=[X,W]` 场景下的激进 fast path
- `mode = 2` 更适合做系统默认自动模式，因为它保住了 `history P` 的稳定性
- 对更大的 `n`，当前主瓶颈先表现为 fixed-step 外层迭代次数，而不是 reduced solver 选择

### 真实 `QE` dump 批量回归

以下结果来自：

- `2026-03-13`
- `ITER_REG_DIRS=/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_actual_medium_dump`
- `ITER_REG_MAX_CASES=8`
- `steps = 6`
- `use_history_p = 0`

覆盖的真实 case 为：

- `n = 8, m = 8` 共 `3` 个
- `n = 12, m = 8` 共 `1` 个
- `n = 16, m = 8` 共 `4` 个

批量回归汇总：

| mode | ok/runs | avg eig_max_rel | max eig_max_rel | avg res_max | max res_max | avg Sorth | avg cycles | avg hit_rate | speedup vs mode0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `chol_jacobi` | `8/8` | `1.002e-12` | `1.004e-12` | `1.607e-13` | `2.660e-13` | `7.254e-16` | `10448` | `0.934` | `1.000` |
| `binv_jacobi` | `8/8` | `1.002e-12` | `1.004e-12` | `1.607e-13` | `2.661e-13` | `9.072e-16` | `7325` | `0.934` | `1.481` |
| `hybrid` | `8/8` | `1.002e-12` | `1.004e-12` | `1.607e-13` | `2.661e-13` | `8.084e-16` | `9872` | `0.934` | `1.244` |

这批结果说明：

- 当前 residue + iterative 主通路在真实 `QE` 导出的 `H_sub / S_sub` 上已经能稳定对齐 direct generalized reference
- `row buffer` 的多行缓存修正已经真实生效，批量命中率稳定在 `0.917` 到 `0.944`
- 在 `Q=[X,W]` 默认路径下，`binv_jacobi` 目前是最省 cycle 的 reduced fast path
- `hybrid` 没有牺牲数值稳定性，但在这批真实 case 上节拍收益明显小于纯 `binv_jacobi`

## 6. 当前边界

这版代码仍然是“硬件化结构的行为模型”，还没有完成以下工作：

- 把现在的子模块继续推进到更真实的 datapath 级建模
- 把真实 `QE` 回归集从当前 `medium dump` 的 `8` 个 case 扩展到更多材料与更大 `n`
- 把 batch regression 结果继续固化成更正式的 validation note / 图表，而不只是控制台输出

## 7. 推荐的下一步

建议按下面顺序继续推进：

1. 先把 row buffer / mod encode / `3M` MAC 的位宽、缓存项和 cycle 模型补细
2. 再把 `iterative_qe_regression_eval` 扩展到更多真实 `QE` dump 目录，并固定成常用回归集
3. 再把 batch regression 的输出整理成论文可直接引用的表格 / 图

这样能保证：

- 架构建模
- 数值验证
- 真实 workload 对齐

三条线保持同步，而不是其中一条先跑太远。
