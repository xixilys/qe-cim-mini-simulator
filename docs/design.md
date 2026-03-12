# 面向 QE 子空间问题的复数 CIM 系统设计

## 1. 设计背景

本项目的目标不是替换 Quantum ESPRESSO `pw.x` 中完整的平面波哈密顿量求解流程，而是面向其内部反复出现的**小规模复数稠密子空间算子**进行加速。典型目标包括：

- `Y_H = H_sub X`
- `Y_S = S_sub X`
- `H_sub = V^H H V`
- `S_sub = V^H S V`

其中：

- `H_sub` 在一般 `k` 点路径下是复数 Hermitian 矩阵
- `S_sub` 在 USPP / PAW 路径下是复数 Hermitian 正定矩阵
- `X`、`V` 是当前子空间中的 block vector

因此，当前系统面对的核心问题不是“大矩阵一次性全谱对角化”，而是**复数 Hermitian / generalized Hermitian 小矩阵上的反复矩阵-块向量乘与子空间构造**。

师兄的参考设计 [`Ozaki_CIM_20260312014000.pdf`](/Volumes/remote/phd/year_2/project/dft加速/docs/Ozaki_CIM_20260312014000.pdf) 给出的重点是：

- 以实数乘法器为基础单元
- 将高精度实数乘法映射到 INT8/CIM 友好的路径
- 在阵列外完成取模、重构、归一化等控制和恢复操作

这与我们当前的系统目标是兼容的：**我们不重新发明复数乘法器，而是在实数乘法 primitive 之上构造复数块乘路径。**

## 2. 参考设计对当前系统的启发

Ozaki Scheme II 对我们的启发不在于“直接照搬实数 FP64 精确重构的全部流程”，而在于它给出了一个清晰的分层原则：

1. **阵列内只做高吞吐、规则的实数乘加**
2. **阵列外承担前处理、重构、归一化、控制流**
3. **尽量把复杂数值问题分解成多个可复用的实数子问题**

这三个原则直接决定了当前复数子空间系统的设计方向：

- 复数运算不在 CIM 阵列内原生实现
- 复数矩阵乘由多个实数 GEMM / GEMV 组成
- 近存逻辑负责复数组装、Hermitian 约束维护、误差监控和调度

## 3. 当前系统的目标边界

### 3.1 加速对象

第一阶段加速对象限定为 QE 子空间求解中最规则、最稳定的两类操作：

- 复数矩阵-块向量乘：`Y = A X`
- 复数小矩阵构造：`A_sub = X^H Y`

这里的 `A` 可以是：

- `H_sub`
- `S_sub`
- `V^H H`
- `V^H S`

### 3.2 不作为第一阶段目标的内容

第一阶段不试图完成以下任务：

- 完整替换 QE 现有 `diaghg` 密集小矩阵求解器
- 直接改写 `h_psi` 的 FFT 主路径
- 构造一个通用复数 LAPACK 加速器

这意味着第一版验证重点是：

- **复数乘法的映射正确性**
- **复数子空间构造误差是否可控**
- **`S_sub` 的正定性在低精度路径下是否仍能维持**

### 3.3 主设计路线

当前系统的**主设计路线**就是复数 Ozaki-II / CRT 方案：

- `FP64 complex input`
- `缩放/截断 -> CRT residue -> Karatsuba 模乘 -> CRT 重构 -> 反缩放`

目标是实现 `ZGEMM` 级别的 `FP64` 复数矩阵乘法。

当前仓库里保留的 4M/3M 子空间验证，只是为了：

- 做 block MVM 数据流探索
- 研究低精度实现下的误差传播
- 给子空间求解器接口做前期原型

它不是主设计，也不是最终的复数 `FP64` 乘法方案。

## 4. 探索性复数矩阵块乘路径

### 4.1 四实乘法（4M）基线

对复数乘法：

`(A_r + i A_i)(X_r + i X_i)`

最直接的映射是四次实数乘法：

- `T1 = A_r X_r`
- `T2 = A_i X_i`
- `T3 = A_r X_i`
- `T4 = A_i X_r`

然后在近存逻辑中重组：

- `Y_r = T1 - T2`
- `Y_i = T3 + T4`

优点：

- 数学形式最直接
- 误差传播最好分析
- 最适合作为第一版硬件和行为模型的“保守基线”

缺点：

- 需要 4 次实数 GEMM / GEMV
- 对阵列调用次数最高

### 4.2 三实乘法（3M）高吞吐变体

为了减少一次实数乘法，可以使用 Gauss 型三乘法：

- `T1 = A_r X_r`
- `T2 = A_i X_i`
- `T3 = (A_r + A_i)(X_r + X_i)`

然后重组：

- `Y_r = T1 - T2`
- `Y_i = T3 - T1 - T2`

优点：

- 实数阵列调用从 4 次降到 3 次
- 更适合在阵列吞吐受限时提升 effective throughput

缺点：

- 额外的加法与抵消会放大量化误差
- 对低精度路径特别敏感
- 更容易破坏 Hermitian 子空间矩阵的数值对称性

因此，对于这条探索性路径，建议：

- **4M 作为默认精度优先路径**
- **3M 作为吞吐优先可选路径**
- 是否启用 3M 由误差监控和矩阵条件数评估决定

这里必须强调：

- 从**代数上**讲，本节的 `3M` 与 `4M` 完全等价
- 差异只出现在**有限精度实现**里
- 在 `BF16/FP32/INT8_EMU` 这类近似路径中，`3M` 由于额外的加减与抵消，数值鲁棒性可能弱于 `4M`

这与后文完整 FP64 Ozaki-II 路线中的 `Karatsuba` 不是同一层概念。  
在 CRT 模式里，Karatsuba 作用在**模域整数矩阵**上，每个模乘本身是精确的，因此与 `4M` 在数学上完全等价。

## 5. 面向 QE 的系统分层

### 5.1 Host / QE 侧

Host 侧负责：
- 从 QE 中截获复数 `H_sub`、`S_sub` 或对应 block 乘请求
- 识别当前是标准问题还是广义问题
- 对主路径优先调度 Ozaki-II / CRT 模式
- 只有在探索性验证时才比较 4M 与 3M
- 在超出硬件边界时回退到 CPU

### 5.2 近存控制逻辑

近存控制逻辑负责：

- 将复数矩阵拆分为实部和虚部
- 在探索性验证模式中生成 4M / 3M 所需的中间矩阵
- 调度实数 CIM macro
- 重组复数输出
- 维护 Hermitian 对称化
- 监控误差、残差和 `S_sub` 的 Cholesky 可行性

### 5.3 实数 CIM Macro

实数 CIM macro 只承担最擅长的规则操作：

- 实数矩阵-块向量乘
- 实数 GEMM/GEMV
- 固定精度或近似整数路径的高吞吐 MAC

从架构职责上看，师兄 PDF 里的实数乘法器正适合作为这里的底层 primitive。

## 6. 与 Ozaki 实数乘法器的关系

### 6.1 可以直接复用的部分

对于参考设计中的实数路径，当前系统可以直接继承其分工理念：

- 前预对齐 / 缩放
- 实数乘法核心
- 结果重组与归一化

若后续实现完整 Ozaki 路径，则每一路实数乘法可以替换为：

- 取模拆分
- INT8 CIM 乘加
- 余数结果重构
- 归一化恢复

### 6.2 需要新增的部分

为了支持 QE 复数子空间问题，必须补上以下机制：

- Ozaki-II / CRT 调度器
- 在验证模式中保留 4M / 3M 调度器
- 共轭转置数据路径 `X^H`
- Hermitian / generalized Hermitian 的数值检查
- `S_sub` 正定性检测
- 对探索性 3M 路径的误差门控

换句话说，Ozaki 实数乘法器是**底层 primitive**，而不是完整系统。

## 7. 基于 Uchino 2025 的完整 FP64 复数 GEMM 路线

Uchino 等 2025 的论文 [`Emulation of Complex Matrix Multiplication based on the Chinese Remainder Theorem.pdf`](/Volumes/remote/phd/year_2/project/dft加速/docs/Uchino%20%E7%AD%89%20-%202025%20-%20Emulation%20of%20Complex%20Matrix%20Multiplication%20based%20on%20the%20Chinese%20Remainder%20Theorem.pdf) 补齐了我们之前设计里最关键的一块：**如何基于 Ozaki-II 真实地把 `FP64` 复数矩阵乘法映射到 INT8/模域阵列，并在输出端重构回 `FP64` 复数结果。**

这条路线不再是“近似算一个差不多的复数乘法”，而是完整的高精度 emulation 链。

### 7.1 计算目标

给定：

- `A = A_R + i A_I`
- `B = B_R + i B_I`

目标是输出：

- `C = C_R + i C_I = A B`

并保持 `ZGEMM` 级别精度。

### 7.2 三步主流程

完整复数 Ozaki-II 路线包含三步：

1. **缩放与截断**
   - 为 `A` 的每一行和 `B` 的每一列选择缩放向量 `mu`、`nu`
   - 将 `A_R`、`A_I`、`B_R`、`B_I` 转换为整数矩阵 `A'_R`、`A'_I`、`B'_R`、`B'_I`

2. **基于 CRT 的模域复数矩阵乘法**
   - 选择一组两两互素的模 `p_l <= 256`
   - 对每个模生成 residue matrix
   - 在每个模上执行复数矩阵乘法
   - 论文推荐在模域使用 **Karatsuba 3M + n-blocking**

3. **CRT 重构与反缩放**
   - 将每个模上的结果按 CRT 重构为整数矩阵 `C'_R`、`C'_I`
   - 再对每个输出元素除以对应的 `mu_i * nu_j`
   - 得到最终 `FP64` 复数输出

### 7.3 复数模乘的具体形式

论文比较了三种复杂数处理方式：

- 扩展成单次实数大 GEMM
- 另一种等价扩展形式
- Karatsuba 三乘法

最终结论是：对于足够大的问题规模，**Karatsuba + n 方向 blocking** 最稳妥，因而应作为系统默认方案。

在每个模 `p_l` 上执行：

- `D_l = A_R,l B_R,l`
- `E_l = A_I,l B_I,l`
- `F_l = (A_R,l + A_I,l)(B_R,l + B_I,l)`

然后重组：

- `C_R,l = D_l - E_l`
- `C_I,l = F_l - D_l - E_l`

由于这里的运算对象已经是模域整数矩阵，`Karatsuba 3M` 是**精确整数运算**，不是近似低精度浮点变形。

### 7.4 缩放策略

论文给出两种缩放模式：

- `fast mode`
  - 基于 Cauchy-Schwarz 上界
  - 预处理更轻
  - 往往需要更多模数

- `accurate mode`
  - 先把输入预缩放到 6-bit / 7-bit 上界矩阵
  - 通过辅助整数矩阵乘法更紧地估计输出上界
  - 通常可以减少所需模数

对我们的系统设计，建议如下：

- **硬件默认支持 accurate mode**
- fast mode 作为面积/时延受限时的回退策略

因为 accurate mode 虽然前处理稍重，但能减少模数数量，等价于减少后续的模域 GEMM 次数。

### 7.5 模数数量与系统代价

论文结果表明，对 `ZGEMM` 级别精度，典型需要：

- `13` 到 `17` 个模数

这意味着一轮完整的复数 Ozaki-II 计算，若采用 Karatsuba，则大致需要：

- `3N` 次实数 INT8 GEMM

其中 `N` 是模数数量。

因此，对我们当前的复数阵列系统来说，完整 FP64 路线的核心代价不是“一个复数 GEMM”，而是：

- 多模并行度
- residue 存储带宽
- CRT 重构带宽
- NML 侧缩放与重构时延

### 7.6 当前系统中的软硬件分工

基于该论文，完整 FP64 路线的职责划分应为：

#### Host / NML

- 选择模数集合 `p_l`
- 计算 `P/p_l` 与乘法逆元 `q_l`
- 生成缩放向量 `mu`、`nu`
- 生成 residue matrices
- 执行 CRT 重构和最终反缩放

#### CIM 阵列

- 执行每个模上的 INT8 实数 GEMM
- 支持 Karatsuba 所需的三次实数乘法路径
- 对 `n` 方向执行 block 化调度

#### 片上缓冲 / NoC

- 缓存多模 residue block
- 支撑 `3N` 次模域乘法结果的回收
- 给 CRT 重构单元提供稳定带宽

### 7.7 对 QE 的意义

引入这条完整 FP64 路线后，我们的系统不再只有“近似子空间 block MVM”这一个答案，而是具备了：

- **近似模式**：用于架构探索和容错 block MVM
- **完整模式**：用于需要 `FP64` 复数输出的 GEMM 主路径

这对 QE 特别重要，因为：

- 某些子空间步骤可以容忍近似
- 但某些复数 GEMM 主路径、参考验证路径和精度敏感路径需要完整 `FP64` 输出

## 8. 第一版行为级模型的验证对象

第一版行为级模型不直接验证完整 Ozaki 模运算链，而是验证更靠近系统架构决策的问题：

1. 复数乘法拆分为 4M / 3M 后是否数学正确
2. 在低精度实数 primitive 下，`H X` / `S X` 的误差有多大
3. 由 `X^H (H X)` 和 `X^H (S X)` 构造的子空间矩阵误差有多大
4. `S_sub` 在误差存在时是否仍然能够通过 Cholesky 检查

当前行为模型中的实数 primitive 使用三类模式：

- `FP64`：参考路径
- `BF16` / `FP32`：低精度浮点近似路径
- `INT8_EMU`：Ozaki 风格整数阵列的第一版近似替身

需要强调：`INT8_EMU` 只是在行为级上模拟“实数阵列量化 + 累加”的效果，还不是完整的 Ozaki Scheme II 精确重构实现。

## 9. 推荐的数据流

### 8.1 计算 `Y = H_sub X`

1. Host 给出复数 `H_sub` 与 `X`
2. 近存逻辑拆分为 `H_r`、`H_i`、`X_r`、`X_i`
3. 按 4M 或 3M 生成实数乘法任务
4. 实数 CIM macro 完成各路 GEMM
5. 近存逻辑重组 `Y_r`、`Y_i`
6. 若需要，执行数值对称化或残差监控

### 8.2 构造 `H_sub = X^H (H X)`

1. 先执行 `Y = H X`
2. 生成 `X^H`
3. 对 `X^H` 与 `Y` 继续执行 4M / 3M 复数块乘
4. 对得到的 `H_sub` 做 Hermitian 化：
   - `H_sub <- 0.5 * (H_sub + H_sub^H)`

### 8.3 构造 `S_sub = X^H (S X)`

与 `H_sub` 路径类似，但在输出端增加：

- 对角实部检查
- Cholesky 可行性检查

若 `S_sub` 不能通过正定性检查，则强制回退到高精度 4M 或 CPU。

## 10. 主设计的硬件/算法协同策略

### 9.1 默认策略

- 复数 `FP64` 主路径：优先 Ozaki-II / CRT + Karatsuba 模乘
- `Gamma-only` 且实对称：可退化为实数 Ozaki-II
- 只有在探索性验证时，才比较 4M 与 3M 的近似 block MVM

### 9.2 策略切换规则

对主设计，建议用以下指标作为切换依据：

- CRT 唯一性条件是否满足
- 所需模数数量是否在硬件支持范围内
- 缩放向量与 residue buffer 是否超出片上资源预算
- 外层 Davidson / RMM 迭代残差

当任一指标超阈值时：

- accurate mode 优先于 fast mode
- 模数数量不足时回退到更高资源配置或 CPU
- 只有在探索性验证模式中才存在 `3M -> 4M`
- CIM -> CPU fallback

## 11. 子空间对角化设计

前面的章节解决的是“复数子空间矩阵如何高效做块乘与构造”。但对 QE 来说，系统还需要回答另一个关键问题：**这些小矩阵最后怎么完成本征求解或对角化？**

这里不能只写“送回 CPU 调 `diaghg`”，否则整套 CIM 方案就只覆盖了乘法通路，没有形成完整闭环。

### 10.1 为什么要单独讨论对角化

在 QE 的主路径里，当前 reduced problem 的维度记为 `N`，实际想要的最低本征对数记为 `m`。

- `N`：当前 reduced basis 维度
- `m`：当前需要保留的最低本征对个数

对标准问题：

- `H_sub c = lambda c`

对广义问题：

- `H_sub c = lambda S_sub c`

如果只从数学上看，最直接的办法当然是对 `N x N` 的小矩阵直接做 dense generalized Hermitian eigensolve；但如果我们已经有一块复数 CIM 阵列，并且它最擅长做的是 `H_sub X` / `S_sub X`，那么就可以进一步考虑把“求最低 `m` 个本征对”改写成一个**基于 block MVM 的迭代求解器**。

### 10.2 两条候选路线

当前系统建议保留两条路线，而不是只押注一种：

#### 路线 A：NML 直接 dense 对角化

这条路线对应传统 `diaghg` 风格：

1. NML 接收 `H_sub`、`S_sub`
2. 若是广义问题，先做 `S_sub = L L^H`
3. 化为标准 Hermitian 问题
4. 对 `N x N` 小矩阵直接做 dense eigensolve

这条路线的优点是：

- 算法最成熟
- 控制流简单
- 当 `N` 很小或者 `m` 接近 `N` 时最直接

这条路线的缺点是：

- 需要 NML 具备完整的小型 complex Hermitian generalized eigensolver
- 会弱化 CIM 阵列的价值，因为主要算力落在 NML 上

#### 路线 B：CIM + NML 协同的 block LOBPCG

这条路线对应 Gemini 提到的架构思路。它不是让 CIM 去做所有事情，而是严格切分：

- **CIM**：负责 `H X`、`S X`、`H W`、`S W`、`H P`、`S P`
- **NML**：负责投影、正交化、微型广义本征问题和块更新

这条路线的关键不是“CIM 会不会对角化”，而是：

- CIM 提供高吞吐复数 block MVM
- NML 在一个很小的投影子空间里完成真正的 Ritz / Rayleigh-Ritz 步

### 10.3 block LOBPCG 在当前架构中的具体映射

设：

- `X`：当前近似特征向量块，维度 `N x m`
- `W`：当前预条件残差块，维度 `N x m`
- `P`：上一轮共轭方向块，维度 `N x m`

对广义问题可写作：

- `R = H_sub X - S_sub X Lambda`
- `W = T^{-1} R`

其中 `T^{-1}` 是预条件器。

当前一轮迭代的数据流如下：

1. 将 `H_sub`、`S_sub` 写入 CIM 阵列并在本轮求解期间驻留  
   注意：这里的“驻留”只在**当前 reduced problem 求解阶段**成立。外层 Davidson 子空间扩展或下一轮 SCF 之后，矩阵仍可能需要重写。

2. NML 把 `X`、`W`、`P` 作为 activation 送入 CIM  
   若采用 block 调度，可一次送入 `Q = [X, W, P]`

3. CIM 计算：
   - `H Q`
   - `S Q`

4. NML 计算投影矩阵：
   - `A_Q = Q^H H Q`
   - `B_Q = Q^H S Q`

5. NML 在 `3m x 3m` 小问题上做 generalized Hermitian eigensolve：
   - `A_Q C = B_Q C Theta`

6. NML 利用系数矩阵 `C` 更新：
   - `X_new = Q C_x`
   - `P_new = Q C_p`

7. 若残差未收敛，继续下一轮

这里真正“对角化”的地方不是 CIM 阵列本身，而是 NML 中的 **`3m x 3m` 微型广义本征问题**。

### 10.4 这条路线为什么适合 CIM

Gemini 给出的核心判断是成立的，原因主要有三点：

1. `H_sub`、`S_sub` 可以在一轮迭代求解中保持 weight stationary  
   对 CIM 来说，静态矩阵 + 流式输入块向量正是最舒服的数据流。

2. LOBPCG 的主耗时确实集中在 block MVM  
   对 `Q = [X, W, P]` 来说，最重的部分是 `H Q` 与 `S Q`，这正好映射到复数阵列。

3. 正交化和 Rayleigh-Ritz 都被限制在小窗口里  
   NML 不需要处理长历史向量链条，这比把大量全局正交化强塞给 CIM 要现实得多。

### 10.5 但这条路线也有一个必须写清楚的边界

Gemini 那套叙述隐含了一个非常重要的前提：

- `m` 要明显小于 `N`

例如：

- `N = 100`
- `m = 4`
- 则 `3m = 12`

这时 `3m x 3m` 的小问题确实非常小，LOBPCG 很漂亮。

但在 QE 的常见 Davidson 子空间里，情况经常是：

- `N = nbase`
- `m = nbnd`
- 而 `nbase` 典型上只比 `nbnd` 大一倍左右

也就是说很多时候：

- `N ~ 2m`

这时 `3m` 已经不再是“极小常数”，甚至会接近或超过 `N`。  
在这种 regime 下，LOBPCG 的 Rayleigh-Ritz 小问题不一定比直接对 `N x N` 的 reduced matrix 做 dense solve 更划算。

所以这部分必须写进设计手册：

- **LOBPCG 不是对所有 QE 子空间都天然优于 direct dense solve**
- 它更适合 `m << N`、只求少量最低本征对、并且矩阵在一个 solve 窗口内能稳定驻留的场景

### 10.6 当前推荐的混合方案

因此，设计上建议采用**双路径对角化架构**：

#### 模式 A：直接 dense 微求解器

适用条件：

- `N` 很小
- `m` 与 `N` 同量级
- 或 NML 已经可以容纳一个小型 `diaghg` 风格单元

执行方式：

- NML 直接解 `N x N` 标准/广义 Hermitian 本征问题
- CIM 主要用于矩阵构造与前序 block 乘

#### 模式 B：LOBPCG 协同求解器

适用条件：

- `m << N`
- 只求少量最低本征对
- `H_sub`、`S_sub` 在一个求解窗口内可驻留
- NML 面积预算只够做 `3m x 3m` 微型 eigensolve

执行方式：

- CIM 做 `H Q` / `S Q`
- NML 做投影、正交化、`3m x 3m` 微型广义本征求解与块更新

### 10.7 NML 需要具备的最低能力

如果走 LOBPCG 路线，NML 至少要能完成：

- 复数向量内积与 block Gram 矩阵计算
- 小规模 QR / 正交化
- `3m x 3m` complex Hermitian generalized eigensolve
- 必要时对 `B_Q` 做 Cholesky
- 残差评估与收敛控制

如果这些能力塞不进 NML，那么系统就不该强行走 LOBPCG，而应该回退到 direct dense 微求解器或 CPU。

## 12. 当前实现建议

结合仓库现状，建议按“主线 + 支线”的方式推进：

### 第一步：以完整 FP64 Ozaki-II 路线为主线

- 完善 `FP64 complex GEMM emulation`
- 明确 residue buffer、CRT 重构、Karatsuba 3M 的时延模型
- 让 Host/NML/CIM 的职责围绕这条主链闭环

### 第二步：把对子空间求解器的接口接到这条主线

- 在需要高精度复数乘法的 QE 路径上优先使用 Ozaki-II / CRT
- 对 `H_sub` / `S_sub` 相关 kernel 明确是否采用完整模式还是 CPU fallback

### 第三步：保留当前 block MVM 验证作为支线

这一阶段已经完成的内容是：

- 复数 4M / 3M 路径
- `H X` / `S X`
- `X^H (H X)` / `X^H (S X)` 构造
- `S_sub` 的 Hermitian 化与 Cholesky 检查

### 第四步：补一个 NML 侧微对角化原型

- 对 direct dense 路线：
  - 先实现一个小规模标准/广义 Hermitian 微求解器模型
- 对 LOBPCG 路线：
  - 先实现 `Q=[X,W,P]` 的投影与 `3m x 3m` 小问题求解

### 第五步：再继续细化底层 primitive

在前两步完成后，再把 `CIM_Macro` 的实数计算核心逐步替换为：

- 更接近 Ozaki 的实数取模/重构模型
- 或者更精细的 INT8 多切片行为模型

这样可以把：

- 完整 FP64 复数 Ozaki-II 链
- 子空间对角化/NML 闭环
- 复数系统架构正确性
- 实数乘法器细节实现

这三件事拆开验证，降低联调复杂度。

## 13. 结论

基于师兄的实数 Ozaki 乘法器设计和 Uchino 2025 的复数扩展，当前系统的主路线应当明确为：

- 以实数乘法器为底层 primitive
- 基于 Ozaki-II / CRT 实现完整的 `FP64 complex GEMM emulation`
- 在模域默认采用 Karatsuba 3M
- 面向 QE 的 `H_sub` / `S_sub` 与 block-vector 乘建立专用数据流
- 在对角化层保留“direct dense 微求解器”和“LOBPCG 协同求解器”两条路线
- 用行为级模型验证 CRT 重构精度，并将 4M/3M 近似路径保留为探索性支线

在这个框架下：

- **Karatsuba 3M 是完整 FP64 CRT 模式下的默认模乘路径**
- **Ozaki 实数阵列不再只是“可替换部件”，而是完整 FP64 复数 GEMM 模式的计算核心**
- **LOBPCG 是特定维度比例下的高吞吐方案，不是所有 QE 子空间都优于 direct solve 的通用答案**

这条路线与 QE 的实际问题结构、与参考 PDF 的硬件分层思想、以及当前仓库已有的 SystemC 原型三者是一致的。
