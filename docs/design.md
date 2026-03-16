# 面向 QE / PySCF 的 DFT 科学计算加速系统设计

## 1. 系统目标

这份文档必须被理解为一份**系统设计文档**，而不是单个乘法器、单个算子或单条数值公式的说明书。

本项目的最高目标是：

- 面向 `Quantum ESPRESSO (QE)`、`PySCF` 等 DFT 科学计算软件
- 设计一套能够真正提升科学计算吞吐、能效和可扩展性的专用加速系统
- 让系统既能服务当前论文切入点，也能支撑后续更大范围的 DFT 工作负载

因此，系统层面要回答的核心问题不是“如何实现一个复数矩阵乘法器”，而是：

- 真实 DFT 软件的热点算子到底是什么
- 哪些热点值得提取成硬件主路径
- `Host / runtime / NML / CIM / micro-solver` 应该如何分工
- 当前论文先切哪一块，才能形成一篇对 `VLSI` 这类 IC 顶会有说服力的系统故事

## 2. 论文定位与边界

### 2.1 长期目标

长期目标是构建一个**面向 DFT 软件栈的复数高精度科学计算加速系统**，重点支持：

- `QE` 的平面波 DFT 主路径
- `PySCF` 的高精度电子结构计算路径
- 复数 `FP64` 密集矩阵乘法
- Hermitian / generalized Hermitian 子空间本征问题

### 2.2 当前论文切入点

如果直接宣称“完整加速整个 DFT 软件”，论文边界会过大，也很难在一篇 `VLSI` 论文里把系统、算法和硬件都讲清楚。  
因此当前论文采用的是**系统目标不变、工作负载先切一块**的策略：

- 从真实 DFT 软件中做算子提取
- 当前已经提取到 `QE Davidson` 子空间中的 Hermitian / generalized Hermitian 对角化问题
- 同时确认这一子问题内部天然包含高频复数矩阵乘法需求

所以当前论文的正确定位应该是：

- **系统目标**：加速 `QE / PySCF` 这类 DFT 科学计算软件
- **当前切口**：`QE Davidson` 子空间里的 Hermitian / generalized Hermitian 对角化
- **当前关键能力**：原生支持该子问题内部用到的复数 `FP64` 矩阵乘法

### 2.3 为什么这个切口成立

这个切口对系统论文是成立的，因为它同时满足 4 个条件：

- 来自真实软件，而不是人造 benchmark
- 数值结构清晰，便于形成可验证的硬件数据流
- 同时覆盖“矩阵乘法”和“对角化”两类核心科学计算算子
- 可以自然扩展到 `PySCF` 等其他电子结构软件

因此，我们当前并不是在写一篇“单个复数乘法器设计”，而是在写一篇：

- 以 `QE` 为工作负载来源
- 以 Davidson 子空间对角化为论文切口
- 以复数 `FP64` GEMM 为关键硬件能力
- 面向 `QE / PySCF` 长期落地的 DFT 加速系统设计

## 3. 系统级创新点

从 `VLSI` 论文叙事出发，当前系统最关键的创新点应当强调为以下几项，而不是只强调 `Ozaki-II` 本身。

### 3.1 创新点一：面向真实 DFT 软件的算子级系统提取

创新不只是“做了一个快的矩阵乘法器”，而是：

- 从 `QE / PySCF` 真实软件栈出发
- 定位出对性能与能效最敏感的科学计算热点
- 把这些热点抽象成可落硬件的数据流和算子接口

这使论文不是孤立的电路设计，而是**面向 DFT 软件的系统级协同设计**。

### 3.2 创新点二：复数 GEMM 与子空间对角化的一体化系统闭环

对 DFT 软件而言，只加速 `GEMM` 还不够。  
当前设计强调的是：

- 一方面系统能原生计算复数 `FP64` 矩阵乘法
- 另一方面系统能支撑当前提取出来的 Hermitian / generalized Hermitian 子空间对角化

这意味着系统不是单算子 IP，而是：

- 复数高精度 GEMM 引擎
- NML 侧对角化与投影子系统
- 上层软件接口与调度逻辑

三者共同组成的科学计算加速系统。

### 3.3 创新点三：面向复数 `FP64` 的 Ozaki-II / CRT 主路径

师兄的参考工作主要是实数 `Ozaki-II` 路线。  
当前系统把这个方向推进到：

- 复数 `FP64` 矩阵乘法
- 面向科学计算软件可直接使用的 `ZGEMM` 级接口
- 通过 `Ozaki-II + CRT + Karatsuba 3M` 在实数阵列上完成高精度复数 GEMM

这里要强调的是：这条主路径不是系统的全部，但它是系统里的**关键创新子系统**。

### 3.4 创新点四：固定矩阵负载的近存迭代对角化闭环

当前论文不能只写“GEMM 能算”，还必须回答“对角化如何完成”。  
本设计里的答案是：

- `H_sub / S_sub` 作为本地固定矩阵驻留在 near-memory tile
- tile 反复执行 `H_sub X`、`S_sub X` 这类块向量乘法
- `NML` 负责 reduced-space 构造、正交化、微型广义本征求解与固定步长控制

也就是说，对角化不是外挂在系统外部的一段软件，而是整个架构中的**原生子系统**；同时，`CIM` 不再只是 trailing update 的配角，而是直接进入迭代微对角化主回路。

### 3.5 创新点五：对 QE / PySCF 兼容的软件接口设计

系统不应只在 toy benchmark 上成立，而应具备明确的软件接入方式：

- 对 `QE`，通过 `BLAS/GEMM` 拦截和算子语义调度接入
- 对 `PySCF`，通过相同的复数 BLAS 接口或更高层 kernel 包装接入
- 对无法获益的情形保留 CPU fallback

这样论文中的硬件设计才有清晰的系统落地路径。

## 4. 工作负载画像与问题规模

### 4.1 大目标工作负载

面向 DFT 软件，典型热点包括：

- 复数 `GEMM/GEMV`
- 子空间投影与子空间矩阵构造
- Hermitian / generalized Hermitian 本征问题
- FFT 及与波函数相关的数据搬运

### 4.2 当前已提取工作负载

当前已提取并准备形成论文主线的工作负载是：

- `QE Davidson` 子空间里的 Hermitian / generalized Hermitian 对角化

其数学对象可写为：

- 标准问题：`H_sub c = lambda c`
- 广义问题：`H_sub c = lambda S_sub c`

其中：

- `H_sub` 在一般 `k` 点路径下是复数 Hermitian
- `S_sub` 在 `USPP / PAW` 路径下是复数 Hermitian 正定

围绕这个子问题，系统需要支持：

- `H_sub X`
- `S_sub X`
- `Q^H H Q`
- `Q^H S Q`
- 小规模 Hermitian / generalized Hermitian 对角化

### 4.3 规模特征

在 `QE Davidson` 中，当前子空间矩阵维度通常与 `nbnd` 同量级，并常落在：

- `N_sub ~= nbnd`
- 扩展子空间后 `N_sub ~= 2 * nbnd`

因此当前论文应重点覆盖的代表性规模是：

- `32 x 32`
- `64 x 64`
- `128 x 128`
- `256 x 256`

这几个规模足以覆盖“当前 paper cut”的主要工程区间，也更适合作为 `VLSI` 论文的实验点。

## 5. 总体系统架构

当前系统应当被描述为一个五层结构，而不是单个算子模块。

### 5.1 软件层

软件层对应：

- `QE`
- `PySCF`
- 上层 DFT 工作流

这一层负责产生真实的科学计算负载，并通过 runtime / bridge 把关键算子送入加速系统。

### 5.2 Runtime / Bridge 层

这一层负责：

- 拦截复数 `GEMM`
- 识别当前 kernel 是否属于已提取的 DFT 热点
- 决定是走硬件主路径还是 CPU fallback
- 在 `QE / PySCF` 与加速器之间做协议转换

从当前原型看，这一层已经可以对应到现有桥接路径：

- `qe_cim_bridge.c`
- socket 协议
- SystemC server

因此，这一层既是软件兼容性的入口，也是系统论文里很重要的“落地路径”。

### 5.3 NML / Controller 层

`NML` 是系统的大脑，负责：

- 任务编排
- 缩放向量生成
- residue 调度
- CRT 重构
- 子空间投影
- 正交化
- 对角化控制
- 微型本征求解

如果没有 `NML`，这个系统就只是一个“会做乘法的阵列”，无法形成完整闭环。

### 5.4 CIM / 实数阵列层

这一层是算力核心，负责：

- 实数 `INT8` 或模域 `GEMM`
- `Karatsuba 3M` 所需的实数子乘法
- 支撑 `Ozaki-II / CRT` 的高吞吐 residue 运算
- 支撑对角化过程中 trailing update 所需的密集矩阵运算

对外暴露的是“复数高精度矩阵运算能力”，但底层实现依然是：

- 实数阵列
- 模域 residue 运算
- 高吞吐矩阵乘加

### 5.5 片上存储与互连层

这一层负责：

- residue block 缓冲
- 多模结果收集
- `Host / NML / CIM` 间搬运
- 为 `CRT` 重构与对角化提供带宽

这部分在 `VLSI` 论文里不能被省略，因为它直接决定系统可实现性。

## 6. 从 QE / PySCF 到加速器的映射

### 6.1 QE 的当前切入点

对 `QE` 而言，当前论文关注的调用链可以抽象为：

`electrons -> c_bands -> cegterg -> reduced matrix -> diaghg`

也就是说，当前 paper cut 不是整个 `H|psi>` 大路径，而是：

- Davidson 已经形成 reduced subspace
- 接下来要对 `H_sub / S_sub` 做 Hermitian / generalized Hermitian 对角化

这正是当前系统切入的最合适位置。

### 6.2 QE 侧的系统映射

对应到系统实现上，`QE` 侧的映射应描述为：

1. `QE` 运行到 Davidson 子空间阶段
2. runtime 识别当前已进入已提取的 Hermitian / generalized Hermitian kernel
3. 将 `H_sub`、`S_sub` 与相关 block vector 发给加速器
4. 加速器完成：
   - `H_sub X`
   - `S_sub X`
   - `Q^H H Q`
   - `Q^H S Q`
   - 子空间对角化
5. 本征对回送给 `QE`
6. `QE` 继续其外层 Davidson / SCF 流程

### 6.3 PySCF 的扩展路径

对 `PySCF`，当前文档不需要过度承诺具体函数名，但应明确两点：

- 系统的第一层接口可以复用 `BLAS/LAPACK` 兼容路径
- 当前复数 `FP64` GEMM 能力和小规模 Hermitian 求解能力可以自然扩展到 `PySCF` 中的密集线性代数热点

这使 `PySCF` 不是“另一个独立系统”，而是同一加速架构的第二个软件落点。

## 7. 复数 `FP64` GEMM 主路径：Ozaki-II / CRT

这是当前系统设计里最重要的一个创新点，但它只是系统中的**一个关键子系统**，不是整篇设计文档的全部。

### 7.1 目标

给定：

- `A = A_R + i A_I`
- `B = B_R + i B_I`

系统要输出：

- `C = C_R + i C_I = A B`

并达到 `ZGEMM` 级别精度。

### 7.2 三步算法主线

完整复数 `Ozaki-II` 路线包含：

1. **缩放与截断**
   - 为 `A` 的每一行和 `B` 的每一列生成 `mu`、`nu`
   - 转换得到整数矩阵 `A'_R`、`A'_I`、`B'_R`、`B'_I`

2. **基于 CRT 的模域复数矩阵乘法**
   - 选择一组互素模数 `p_l <= 256`
   - 构造 residue matrices
   - 在每个模上执行复数矩阵乘法
   - 默认采用 `Karatsuba 3M + n-blocking`

3. **CRT 重构与反缩放**
   - 将每个模上的结果重构为 `C'_R`、`C'_I`
   - 再除以 `mu_i * nu_j`
   - 得到最终 `FP64 complex` 输出

### 7.3 为什么主路径选择 Karatsuba 3M

在主设计里，`3M` 不是“近似路线”，而是：

- 复数乘法的一种标准分解
- 在模域整数矩阵上精确执行
- 用于减少底层实数 `GEMM` 次数

因此，在 `Ozaki-II / CRT` 路线里：

- `Karatsuba 3M` 与 `4M` 在数学上完全等价
- 论文和当前系统都把它视为默认的复数模乘方法

### 7.4 这条主路径在系统中的价值

对当前系统来说，`Ozaki-II / CRT` 的意义不只是“做出一个复数乘法器”，而是：

- 让实数阵列能够原生支撑复数 `FP64` 科学计算
- 为 Davidson 子空间投影、trailing update、回代等环节提供统一的矩阵运算底座
- 把“复数高精度”从软件库层面下沉为架构能力

### 7.5 模数与代价

对 `ZGEMM` 级别精度，当前系统应按论文经验预留：

- `13` 到 `17` 个模数

这意味着一轮完整计算的主要代价来自：

- 多模 residue 运算
- residue buffer
- 多模并行度
- `CRT` 重构

因此，主设计真正要优化的是整个模域数据流，而不是把问题简化成“一个复数乘法公式选 `3M` 还是 `4M`”。

### 7.6 近存 tile 的当前组织结论

针对 `complex FP64` 科学计算，我们当前不再把 `CIM tile` 理解为“直接在主 `SRAM` 中长期存放全量 residue 矩阵”的极端存算形式，而是收敛到更现实的 near-memory 组织：

- 主 `SRAM` 仍保存原始复数矩阵数据的实部 / 虚部行块
- 每个 tile 内设置一套本地 `mod encode` 单元，将被激活的行按需转换到 residue 域
- tile 内保留小容量的 `row residue buffer`，缓存高重用热点行的 residue 结果
- 复数乘法主路径仍采用 `Karatsuba 3M`
- `3M` 的实数子乘法与 dot-product 累加在模空间内完成，最后再由 tile 侧重构单元恢复到普通数值域

这条结论的意义是：

- 对 `FP64` 而言，如果直接把主存储整体翻译成全量 residue 形式，`SRAM` 面积和 banking 开销会明显上升
- 因而更合理的主线不是“纯 residue 常驻阵列”，而是“原始数据近存 + 热点行按需取模 + 模空间完成主乘加 + 最终重构”
- 这让系统保留了模域 `3M` 的计算价值，同时避免把主 `SRAM` 容量膨胀直接固定为全量多模副本

### 7.7 当前复数 tile 数据流

当前选定的复数 `FP64` tile 数据流为：

1. `real bank` 与 `imag bank` 同时按行读出
2. 查询 tile 内 `row residue buffer`
3. 若命中，则直接复用该行的 residue 表示
4. 若未命中，则送入 tile 内 `mod encode` 单元完成取模编码，并写回 `row residue buffer`
5. residue 形式的实部 / 虚部行送入 `3M residue MAC` 单元
6. 在模空间内完成单个输出元素所需的复数乘法与 dot-product 累加
7. 当前输出元素完成后，由 tile 侧 `CRT / reconstruction` 单元恢复到普通数值域

因此，系统在这一层的正确表述应是：

- `SRAM` 负责近数据存储与高带宽行供给
- tile 侧编码、buffer 和 `3M` 单元承担模空间主计算
- 最终重构留在 tile 外围或 tile 侧重构单元完成

这比把全部语义都压成“纯存算 bitcell”更符合当前 `FP64 complex` 目标，也更适合后续面积与数据流分析。

## 8. 子空间对角化子系统

因为当前论文切入的是 `QE Davidson` 子空间对角化，所以系统必须同时给出这一层设计，而不能只停留在“外部有个 eigensolver”。

### 8.1 目标问题

当前目标不是全 DFT 全谱求解，而是：

- 小规模 Hermitian / generalized Hermitian reduced problem
- 面向 Davidson 提取出来的 `H_sub / S_sub`

这也是当前 paper cut 最适合的范围。

### 8.2 当前主候选：固定矩阵负载的迭代微对角化

当前更符合系统创新点的主候选路线，不再是“先 standardize、再完整 direct dense 解全谱”的纯数字主线，而是：

- `H_sub / S_sub` 固定驻留在 near-memory complex tile
- 反复将 block vector `X` 流过 tile，计算：
  - `H_sub X`
  - `S_sub X`
- 在 `NML` 中构造 reduced-space generalized problem
- 通过固定步长的 block iterative / Rayleigh-Ritz refinement 得到最小 `m` 个本征对

这一主候选的关键点是：

- `CIM` / tile 直接承担对角化迭代中的主算子
- `NML` 只负责小规模、控制流强的 reduced solver 和正交化
- 算法天然匹配“本地固定矩阵 + 流式向量块”的硬件负载模型

### 8.3 固定矩阵负载算法流程

在当前版本中，这条路线可细化为：

1. **输入整形**
   - 对 `H_sub` 做 Hermitian 一致性检查与必要的对称化
   - 对 `S_sub` 做 Hermitian 检查与正定性检查

2. **矩阵驻留**
   - 将 `H_sub` 与 `S_sub` 的实部 / 虚部行块写入 tile 内 `real/imag bank`
   - 之后在若干固定步迭代中保持矩阵常驻

3. **初始块向量输入**
   - runtime / `NML` 提供初始 block vector `X`
   - 其列数对应目标低端本征空间大小 `m` 或扩展块维度

4. **tile 主算子计算**
   - tile 反复计算 `HX = H_sub X`
   - generalized 路径同时计算 `SX = S_sub X`
   - 这一层复用当前选定的 dual-bank + row residue buffer + `3M` residue MAC 主路径

5. **reduced-space 构造**
   - `NML` 构造：
     - `X^H H X`
     - `X^H S X`
   - 或在扩展子空间 `Q = [X, W]` / `Q = [X, W, P]` 上构造：
     - `Q^H H Q`
     - `Q^H S Q`

6. **微型广义本征求解**
   - `NML` 对 reduced generalized Hermitian 问题求解
   - 得到当前 Ritz 值与 Ritz 向量

7. **搜索子空间更新**
   - 形成 residual / correction block
   - 执行 `S`-正交化
   - 更新下一轮 block vector 或扩展子空间

8. **固定步长终止**
   - 按固定 `T` 步结束
   - 输出最小 `m` 个候选本征对给外层 `QE Davidson`

这条流程的本质不是让近存模块单独承担整个全局收敛，而是把它定义成：

- `QE Davidson` 外层中的一个 near-memory subspace refinement engine

### 8.4 当前 baseline：direct dense generalized solver

虽然当前主候选是固定矩阵负载迭代路线，但系统仍保留一条 direct dense baseline：

- `Hermitianize`
- `SPD check`
- `Cholesky`
- generalized 到 standard
- tridiagonalization
- implicit QR
- back-transform

这条路线的作用是：

- 作为数值 reference / golden flow
- 为后续 iterative 路线提供误差、残差与正交性对照
- 在早期验证阶段提供 fallback 与行为基线

### 8.5 软硬分工

在当前系统里：

- `CIM` 负责：
  - `H_sub X`
  - `S_sub X`
  - `Q^H H Q`
  - `Q^H S Q`
  - 在 tile 内完成实部 / 虚部分离读出、热点行 residue 复用、`3M` 模域乘加与结果重构

- `NML` 负责：
  - Hermitian 化与检查
  - 初始块向量与 fixed-step 控制
  - reduced-space generalized matrix 构造
  - `S`-正交化
  - 微型广义本征求解
  - 残差判定与结果整理

这样切分的关键在于：

- 把固定矩阵负载下最重的 `HX / SX` 主算子留给 tile
- 把 reduced-space 的小规模高依赖步骤留给 `NML`

### 8.6 为什么这层对 VLSI 论文重要

如果只写“我们能做一个很好的复数 `GEMM`”，论文会更像一个算术单元设计。  
而把它放进当前提取出来的 Davidson 子空间对角化闭环里，并且让 `CIM` 真正承担固定矩阵负载下的迭代主算子，论文才真正变成：

- 面向 DFT 软件的系统架构
- 有明确 workload
- 有明确 software-to-hardware path
- 有明确 end-to-end story

### 8.7 当前原型与完整对角化的关系

当前仓库里已经验证的是：

- `Ozaki-II / CRT` 复数 `FP64` GEMM 行为正确性
- generalized reduced problem 的 direct dense baseline 行为正确性

下一阶段需要补齐的是：

- fixed-step block iterative 路线的行为级模型
- 本地固定矩阵负载下 `HX / SX` 与 reduced-space 更新的闭环验证
- 与 `QE Davidson` reduced matrix 的迭代式闭环联调

因此，当前论文文档应当明确：

- **系统设计已经包含以 fixed-matrix iterative 为主候选、以 direct dense 为 baseline 的双路线对角化方案**
- **当前原型处于“GEMM 主路径已验证，iterative diagonalization 闭环继续实现”的阶段**

## 9. 当前论文主线的数据流

对于当前论文提取的 `QE Davidson` 子空间问题，系统级数据流可以描述为：

1. `QE` 运行到 Davidson 子空间对角化阶段
2. runtime 识别出当前 kernel 属于已提取的 Hermitian / generalized Hermitian 子问题
3. 将 `H_sub`、`S_sub` 及相关 block vector 发送到加速器
4. near-memory tile 主路径负责：
   - `H_sub X`
   - `S_sub X`
   - reduced-space 构造所需的主矩阵乘法
5. `NML` 负责：
   - Hermitian 化
   - fixed-step 调度
   - `S`-正交化
   - reduced generalized eigensolve
   - 候选本征对整理
6. 得到的本征对回送给 `QE`
7. `QE` 继续其外层 Davidson / SCF 流程

这个数据流非常重要，因为它说明：

- 当前论文虽然只切入了一个算子簇
- 但它已经嵌在真实 DFT 软件的运行闭环里

## 10. 面向 VLSI 论文的实验组织

如果目标是 `VLSI` 这类 IC 顶会，实验组织不能只给算子误差或只给电路面积，而应同时覆盖以下层次。

### 10.1 系统价值

- 面向 `QE / PySCF` 的真实工作负载
- 当前提取出的 Davidson 子空间对角化热点
- 对上层软件运行时间与能耗的潜在影响

### 10.2 架构价值

- `Ozaki-II / CRT` 主路径的吞吐、面积、能效
- residue buffer / `NML` / `CRT` 重构代价
- 对角化子系统的控制与存储开销

### 10.3 数值价值

- `ZGEMM` 级精度
- Hermitian / generalized Hermitian 子空间数据流正确性
- 本征值和本征向量误差
- 广义本征问题下的稳定性

### 10.4 软件协同价值

- `QE` 接口映射
- `PySCF` 接口映射
- fallback 策略与兼容性
- 从桥接层到加速器的数据流完整性

## 11. 当前原型与文档的关系

当前仓库里的原型分成两类。

### 11.1 主线原型

- [`model/src/tb_complex_ozaki.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_complex_ozaki.cpp)
- [`model/docs/complex_ozaki_fp64_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md)
- [`docs/complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)

它们服务于：

- 复数 `FP64` GEMM 主路径
- `Ozaki-II / CRT` 系统能力验证

### 11.2 支撑原型

- [`model/src/tb_generalized_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_generalized_subspace.cpp)
- [`model/docs/generalized_subspace_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/generalized_subspace_validation.md)
- [`model/src/tb_iterative_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_iterative_subspace.cpp)
- [`model/src/tb_iterative_tile_gemm.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_iterative_tile_gemm.cpp)
- [`model/docs/iterative_subspace_flow.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/iterative_subspace_flow.md)

它们服务于：

- generalized Hermitian 微对角化验证
- 固定矩阵负载的 iterative 子空间流程验证
- residue / CRT 复数 GEMM 在迭代引擎里的接入验证

这些原型不是系统设计本身，但它们为当前论文的系统故事提供了可验证支撑。

## 12. 当前设计结论

当前设计文档的核心结论应当明确为：

- **最大的目标是加速 `QE / PySCF` 这类 DFT 科学计算软件**
- **当前论文切入点是从 `QE` 中提取出的 Davidson 子空间 Hermitian / generalized Hermitian 对角化**
- **`Ozaki-II / CRT` 复数 `FP64` 矩阵乘法是系统里的关键创新点之一，但不是系统设计的全部**
- **系统最终要同时覆盖软件接口、复数高精度 GEMM、子空间对角化、以及 `NML / CIM` 协同**

用一句话概括当前论文的正确定位：

**我们不是在写一篇“复数矩阵乘法器设计”，而是在写一套面向 DFT 软件、以 Davidson 子空间对角化为当前切入点、并原生支持复数 `FP64` GEMM 的科学计算加速系统。**
