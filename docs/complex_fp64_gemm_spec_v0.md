# CIM Complex FP64 GEMM Subsystem Spec v0

## 1. 文档目的

这份文档是系统总设计文档之外的一份**内部子系统规格说明**。  
它的目标不是重复介绍 `Ozaki-II` 原理，而是先把下面几件事锁住：

- 这个复数 `FP64 GEMM` 子系统在整个 DFT 加速系统里扮演什么角色
- 输入输出和数值目标到底是什么
- 数学主链如何映射到 `NML + CIM + reconstruction` 数据流
- 实验和验证该如何组织，避免后期再拼

这份 `v0` 文档优先解决的是 **problem contract** 和 **evaluation contract**。  
后续更细的 datapath、SRAM banking、NoC 时序，都应该建立在这里的约束之上。

## 2. 目标工作负载与系统角色

### 2.1 系统角色

本子系统服务于更大的目标：

- 加速 `QE / PySCF` 这类 DFT 科学计算软件

它在系统中的角色不是一个孤立的复数乘法 IP，而是：

- `QE Davidson` 子空间对角化中的矩阵运算底座
- 后续 `PySCF` 密集复数线性代数热点的统一加速底座
- `NML` 对角化、投影、回代过程中需要反复调用的高精度复数 GEMM 引擎

### 2.2 当前 paper cut

当前论文并不声称“完整加速所有 DFT 热点”，而是先切入：

- `QE Davidson` 子空间中的 Hermitian / generalized Hermitian 对角化

在这个切口下，复数 `FP64 GEMM` 子系统的直接任务包括：

- `H_sub X`
- `S_sub X`
- `Q^H H Q`
- `Q^H S Q`
- blocked tridiagonalization 中的 trailing update
- eigenvector back-transform 中的块矩阵更新

因此，这个子系统是当前系统论文里的**核心算力主路径**。

## 3. Problem Contract

### 3.1 算子定义

`v0` 版本以复数密集矩阵乘法为主，定义为：

- `C = op(A) * op(B)`
- 可选扩展形式：`C = alpha * op(A) * op(B) + beta * C`

其中：

- `A, B, C` 为 `complex FP64`
- `op(.)` 在 `v0` 中优先支持 `{N, C}`
- `T` 模式不作为硬件主路径承诺，必要时由 runtime 转换或 fallback

### 3.2 输入输出契约

输入：

- `A`, `B`：列主序复数 `FP64` 矩阵
- `M, N, K`
- `op(A), op(B)`
- `alpha`, `beta`
- layout / leading dimension 元信息

输出：

- `C_out`：列主序复数 `FP64` 结果矩阵
- 可选统计信息：
  - 使用模数个数
  - fallback 原因
  - scaling 溢出/保护标志

### 3.3 精度目标

`v0` 的精度目标不是“近似可用”，而是以 `ZGEMM` 为黄金参考，达到高精度科学计算可接受水平：

- 主指标：相对 Frobenius 误差 `<= 1e-13` 量级目标
- 观察指标：
  - `max_abs`
  - `max_rel`
  - `rms_abs`
  - 在 representative `QE` 样本上的能量/残差敏感性

当前行为级原型已经在随机测试上达到了 `~1e-14` 量级的相对误差，这为该 contract 提供了初步支撑。

### 3.4 支持维度

`v0` 先锁定为**tile-native, large-matrix composable** 的契约：

- 原生关注的代表性 tile 尺寸：`16, 32, 64, 128, 256`
- 更大的矩阵由 runtime 在 tile 级进行拼接
- `QE Davidson` 当前论文主线优先覆盖：
  - `32 x 32`
  - `64 x 64`
  - `128 x 128`
  - `256 x 256`

这一定义避免了一开始就把芯片目标写成“无限大矩阵通吃”，也保证 contract 与当前 workload 一致。

### 3.5 支持算子模式

`v0` 明确支持以下模式：

- `op(A), op(B) ∈ {N, C}`
- `beta = 0` 作为优先快路径
- `beta != 0` 作为 NML/output formatter 支持项
- dense complex matrix only

当前不作为主路径承诺的内容：

- 稀疏格式
- batched GEMM 的专门调度
- 非复数 `FP64` 之外的通用 BLAS 全家桶

### 3.6 Fallback 条件

以下条件出现时，runtime 应允许回退到 CPU / BLAS 参考路径：

- `op(A)` 或 `op(B)` 不在 `{N, C}` 内
- tile 尺寸超出当前片上 buffer 和 modulus schedule 能力
- scaling 分析要求的模数个数超过配置上限
- reconstruction guard 检测到潜在溢出或非法值
- 输入维度太小，低于硬件 crossover point
- 调试或验证模式要求强制软件参考

这部分必须写死，因为 fallback 不是失败，而是系统契约的一部分。

## 4. Arithmetic Mapping

这一节定义从 `complex FP64` 到阵列计算的**主数学链**。

### 4.1 复数 FP64 到缩放

输入复数矩阵先按行/列生成缩放向量：

- `mu`：对应 `A` 的行
- `nu`：对应 `B` 的列

目标是把复数实部和虚部都压缩到后续整数化和模域计算可接受的范围内。

### 4.2 整数化

对缩放后的实部与虚部分别执行整数化，得到：

- `A'_R`, `A'_I`
- `B'_R`, `B'_I`

这一层的 contract 是：

- 尽可能保持信息不丢失
- 保证后续 `CRT` 路径可以唯一重构

### 4.3 Residue 展开

选择一组互素模数 `p_l <= 256`，将上述整数矩阵映射到 residue 域：

- `A'_(R,l), A'_(I,l)`
- `B'_(R,l), B'_(I,l)`

`v0` 预留的代表性模数数量范围为：

- `13` 到 `17`

### 4.4 模域复数乘法

在每个模数 `p_l` 上，默认采用 `Karatsuba 3M`：

- `D_l = A_(R,l) * B_(R,l)`
- `E_l = A_(I,l) * B_(I,l)`
- `F_l = (A_(R,l) + A_(I,l)) * (B_(R,l) + B_(I,l))`

重组得到：

- `C_(R,l) = D_l - E_l`
- `C_(I,l) = F_l - D_l - E_l`

这里要再次写清楚：

- 在 `Ozaki-II / CRT` 主路径里，`Karatsuba 3M` 与 `4M` 在数学上完全等价
- `3M` 在这里不是近似技巧，而是默认的精确复数模乘映射

### 4.5 CRT 重构

将各模上的结果送入重构单元，得到：

- `C'_R`
- `C'_I`

这一步需要：

- modulus product 管理
- modular inverse 常量
- residue accumulation

### 4.6 反缩放

最终对 `C'_R`、`C'_I` 施加 `mu_i * nu_j` 反缩放，恢复到：

- `C_R`
- `C_I`

得到最终 `complex FP64` 输出。

## 5. Microarchitecture

### 5.1 NML Preprocessing

`NML` 预处理阶段负责：

- 输入矩阵扫描
- 动态范围估计
- scaling 向量生成
- integerization 控制
- fallback 判定前置检查

### 5.2 Residue Generator

该模块负责：

- 按模数集合并行或时分生成 residue matrix
- 将实部与虚部分别格式化为阵列可消费的数据块
- 输出给 modulus scheduler

### 5.3 Modulus Scheduler

该模块负责：

- 决定每个模数是并行执行还是时分复用
- 调度 `3M` 所需的三次实数 `GEMM`
- 管理 tile 次序、阵列占用和结果回收顺序

### 5.4 CIM Tile Array

`CIM` 阵列只做它最擅长的事：

- 实数 / 模域 dense GEMM
- 高吞吐 tile 乘加

它不负责：

- scaling 判定
- `CRT` 重构
- 结果格式化

这保证了阵列职责足够纯粹，避免 datapath 被控制流污染。

### 5.5 Residue Accumulator

该模块负责：

- 汇总不同模数、不同 tile 的部分和
- 为 `CRT` 重构提供统一接口
- 维护实部和虚部的结果域分离

### 5.6 CRT / Reconstruction Engine

该模块负责：

- 每个输出元素的 residue 合并
- `CRT` 唯一重构
- 溢出和异常值检查

### 5.7 Output Formatter

该模块负责：

- 反缩放
- `alpha / beta` 合成
- 列主序输出格式恢复
- 向 runtime 返回结果与状态标志

## 6. Dataflow and Memory System

### 6.1 Tile 流程

`v0` 规定的主 tile 流如下：

1. runtime 切 tile
2. `NML` 预处理与缩放
3. residue generator 生成各模输入块
4. modulus scheduler 发起 `3M` 模域 `GEMM`
5. residue accumulator 回收中间结果
6. `CRT` engine 重构
7. output formatter 反缩放并写回

### 6.2 Buffer 分层

至少要明确三层缓冲：

- `Input staging buffer`
  - 存 `A/B` 当前 tile 的实部和虚部
- `Residue buffer`
  - 存各模数下的 residue tiles
- `Output / reconstruction buffer`
  - 存重构前的 residue accumulation 和重构后的 `C`

### 6.3 实虚部布局

`v0` 先锁定为**实部 / 虚部分离布局**：

- `A_R`, `A_I` 分开存
- `B_R`, `B_I` 分开存
- residue 域也保持实部、虚部分离

原因很直接：

- 更符合 `3M` 调度
- 便于 tile 级重用
- 便于独立检查实部与虚部的数值范围

### 6.4 多模并行 vs 时分

`v0` 不把这件事写死成单一实现，而是明确成一个设计空间：

- 小规模原型可采用时分多模
- 吞吐优化版本可采用部分模数并行

但必须记录的 contract 是：

- 无论并行还是时分，运行时都必须能报告：
  - 模数个数
  - 每模调用次数
  - tile 次数

这样后续论文里的 cost breakdown 才有依据。

### 6.5 中间量落点

这一点必须在 `v0` 文档里提前写清楚：

- scaling 向量留在 `NML`
- residue tiles 落在 `residue buffer`
- `3M` 三路中间结果落在 `residue accumulator`
- `CRT` 之前不恢复到 `FP64`
- `alpha / beta` 合成放在 output formatter

## 7. Evaluation Methodology

### 7.1 对照对象

`v0` 评测统一以两层 reference 为准：

- 黄金数学模型：
  - `std::complex<double>` / CPU `ZGEMM`
- 硬件行为模型：
  - 当前 SystemC `Ozaki-II / CRT` 原型

这样可以同时回答：

- 数学上算得对不对
- 行为级硬件模型和黄金参考差多少

### 7.2 数值指标

统一报告以下指标：

- `rel_frob`
- `max_rel`
- `rms_abs`
- `max_abs`
- 异常样本计数
- fallback 率

对结构化和 `QE` 样本，还要补充：

- Hermitian 性破坏量
- 若进入 generalized path，则 `S_sub` 正定性检查结果

### 7.3 系统指标

系统侧至少记录：

- 每次调用所需模数个数
- 每次调用的实数 `GEMM` 总次数
- tile 次数
- `NML` 前后处理调用次数
- `CRT` 重构代价
- CPU fallback 次数

### 7.4 与 QE 工作负载的结合方式

对 `QE` 路径，评测不应只停留在随机矩阵，而应区分两层：

- kernel-level：
  - 直接比较提取出的 `H_sub / S_sub / Q^H H Q / Q^H S Q`
- workload-level：
  - 统计这些 kernel 在 `QE Davidson` 中的出现频率、规模分布和动态范围

## 8. 实验包 v0

这部分建议从现在就开始准备，因为它会反过来约束架构。

### 8.1 数学对照集

用途：纯 `GEMM` 精度验证。

样本类型：

- 随机 complex matrix
- 不同动态范围
- 不同 condition number
- 不同 amplitude pattern

最少输出：

- 每类样本的误差统计
- 所需模数数量分布
- 是否触发 fallback

### 8.2 结构化科学计算集

用途：证明系统不是只会做随机矩阵。

样本类型：

- Hermitian block
- generalized Hermitian 的 `H_sub / S_sub`
- `Q^H H Q`
- `Q^H S Q`

最少输出：

- 对结构保持性的影响
- Hermitian 破坏量
- generalized 情形下的稳定性

### 8.3 QE 提取真实样本

这是最重要的一组。

样本来源：

- 从实际 `QE` 路径截取 representative matrices
- 具体采样入口与字段定义见 [`qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_subspace_sampling.md)

至少要记录：

- 维度分布
- 数值范围
- 实虚部比例
- Hermitian / generalized Hermitian 类型
- reuse 特征

这是后续系统论文中“不是玩具 workload”的关键证据。

### 8.4 压力测试集

用途：验证坏情况下的稳健性。

样本类型：

- 幅值跨度很大
- 接近 cancellation
- 虚实部比例极端
- 接近病态

最少输出：

- 误差随动态范围和条件数的变化
- 模数需求是否激增
- fallback 是否增加

## 9. 立即冻结的 6 件事

`v0` 版本现在就应冻结以下 6 件事，避免后面反复回滚：

1. 数值 contract
   - 输入输出、精度目标、fallback 条件写死
2. `QE` 真实矩阵画像的采样字段
   - 规模、动态范围、结构、reuse
3. 主算法锁定
   - `Ozaki-II + CRT + 3M`
   - `4M` 只作为对照
4. 数据布局
   - 实虚部分离
   - residue buffer 独立
5. 双层 reference
   - 黄金数学模型
   - 硬件行为模型
6. 代价拆账
   - 模数数目
   - 实数 `GEMM` 次数
   - buffer 需求
   - `CRT` 重构开销

## 10. 当前文档的作用

这份 `spec v0` 的作用不是把芯片所有细节一次性定死，而是先为后续工作提供一个稳定的“主线”。

后续我们围绕它继续推进时，优先顺序应保持为：

1. 先采 `QE` 真实矩阵画像
2. 再把行为级模型按这份 contract 补齐
3. 再做模数选择、buffer 组织、`NML/CIM` 分工细化
4. 最后才下探更细的 datapath 和物理实现细节

如果这份文档没有先立住，后面的微架构图和 datapath 很容易越画越细、越画越偏。
