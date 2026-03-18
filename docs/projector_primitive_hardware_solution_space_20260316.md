# 面向 QE / PySCF 投影原语的硬件方案空间扫描与筛选

## 1. 文档目的

这份文档不是只找“最像我们”的一两篇文章，而是要把**真正可能成为我们实现路线的方案族**尽量铺全，然后再筛掉不适合的路线。

核心目标有三个：

1. 系统性扫描 `CIM / hybrid-CIM / near-memory / programmable accelerator` 这几条主线
2. 对每条路线抽取**结构级信息**，而不是只看标题或摘要
3. 最后给出一个**最适合 QE / PySCF 投影型负载**的硬件实现主线

这里的“适合”不是只看某个单点能效，而是同时看：

- `FP64 contract`
- 复数与共轭
- `P` 常驻而 `X` 流动
- `C = P^H X` 是长归约
- `Y = P T` 是短归约
- `M` 小而局部
- `G = C^H M C` 这类 reduced 输出很重要

## 2. 检索范围

## 2.1 本地全文级阅读范围

本轮已经按全文或至少前两页结构级阅读过的代表性资料包括：

### `transpose / dual-view / 双方向访问`

- [`Two-Way Transpose Multibit 6T SRAM Computing-in-Memory Macro for Inference-Training AI Edge Chips`](/Volumes/extend_2/research_data/jssc_full_harvest/2022/issues/vol57_issue02_is9694622/pdfs/Two-Way Transpose Multibit 6T SRAM Computing-in-Memory Macro for Inference-Training AI Edge Chips_9535152.pdf)
- [`TranCIM Full-Digital Bitline-Transpose CIM-based Sparse Transformer Accelerator With Pipeline/Parallel Reconfigurable Modes`](/Volumes/extend_2/research_data/jssc_full_harvest/2023/issues/vol58_issue06_is10136239/pdfs/TranCIM Full-Digital Bitline-Transpose CIM-based Sparse Transformer Accelerator With PipelineParallel Reconfigurable Modes_9931922.pdf)
- [`HYTEC Compact and Energy-Efficient Analog-Digital Hybrid CIM With Transpose Ternary eDRAM`](/Volumes/extend_2/research_data/jssc_full_harvest/2025/issues/vol00_issue99_is4359912/pdfs/HYTEC Compact and Energy-Efficient Analog-Digital Hybrid CIM With Transpose Ternary eDRAM_11219422.pdf)
- [`Hsu 等 - 2025 - A 22nm 41.8TFLOPS/W AI-Edge Transformer/CNN Nonvolatile-Processor Using QKV-Softmax-Layer-Fused Hybrid ReRAM-CIM and Concurrent-Transpose/Non-Transpose SRAM-CIM`](/Volumes/remote/Zotero/storage/VDIJEW27/Hsu 等 - 2025 - A 22nm 41.8TFLOPSW AI-Edge TransformerCNN Nonvolatile-Processor Using QKV-Softmax-Layer-Fused Hybr.pdf)

### `floating-point / mixed-precision / high-precision CIM`

- [`ReDCIM Reconfigurable Digital Computing-In-Memory Processor With Unified FP/INT Pipeline for Cloud AI Acceleration`](/Volumes/extend_2/research_data/jssc_full_harvest/2023/issues/vol58_issue01_is9999561/pdfs/ReDCIM Reconfigurable Digital Computing- In -Memory Processor With Unified FPINT Pipeline for Cloud AI Acceleration_9968289.pdf)
- [`A Floating-Point 6T SRAM In-Memory-Compute Macro Using Hybrid-Domain Structure for Advanced AI Edge Chips`](/Volumes/extend_2/research_data/jssc_full_harvest/2024/issues/vol59_issue01_is10375801/pdfs/A Floating-Point 6T SRAM In-Memory-Compute Macro Using Hybrid-Domain Structure for Advanced AI Edge Chips_10265269.pdf)
- [`AFP-CIM All-Inclusive Floating-Point With Segmented Compute-in-Memory Macro`](/Volumes/extend_2/research_data/jssc_full_harvest/2025/issues/vol00_issue99_is4359912/pdfs/AFP-CIM All-Inclusive Floating-Point With Segmented Compute-in-Memory Macro_11231367.pdf)
- [`A 22-nm 109.3-to-249.5-TFLOPS/W Outlier-Aware Floating-Point SRAM Compute-in-Memory Macro for Large Language Models`](/Volumes/extend_2/research_data/jssc_full_harvest/2026/issues/vol61_issue02_is11368630/pdfs/A 22-nm 109.3-to-249.5-TFLOPSW Outlier-Aware Floating-Point SRAM Compute-in-Memory Macro for Large Language Models_11016687.pdf)
- [`A 28-nm Hybrid-Domain Outer Product-Based Floating-Point SRAM Computing-in-Memory Macro With Logarithm Bit-Width Residual ADC for Edge AI`](/Volumes/extend_2/research_data/jssc_full_harvest/2026/issues/vol00_issue99_is4359912/pdfs/A 28-nm Hybrid-Domain Outer Product-Based Floating-Point SRAM Computing-in-Memory Macro With Logarithm Bit-Width Residual ADC for Edge AI_11418916.pdf)
- [`LLM-CIM A 28nm 126.7TOPS/W Input-LUT-Based Digital CIM Macro with Reconfigurable Matrix Multiplication and Nonlinear Operation Modes for LLMs`](/Volumes/extend_2/research_data/vlsi_paper/2025/Digital_Systems/LLM-CIM A 28nm 126.7TOPSW Input-LUT-Based Digital CIM Macro with Reconfigurable Matrix Multiplication and Nonlinear Operation Modes for LLMs_11074939.pdf)

### `sparsity / irregular dataflow / inter-macro scheduling`

- [`MulTCIM Digital Computing-in-Memory-Based Multimodal Transformer Accelerator With Attention-Token-Bit Hybrid Sparsity`](/Volumes/extend_2/research_data/jssc_full_harvest/2024/issues/vol59_issue01_is10375801/pdfs/MulTCIM Digital Computing-in-Memory-Based Multimodal Transformer Accelerator With Attention-Token-Bit Hybrid Sparsity_10226612.pdf)
- [`Onyx A 12-nm Programmable Accelerator for Dense and Sparse Applications`](/Volumes/extend_2/research_data/jssc_full_harvest/2025/issues/vol00_issue99_is4359912/pdfs/Onyx A 12-nm Programmable Accelerator for Dense and Sparse Applications_11150697.pdf)
- [`Occamy A 432-Core 28.1 DP-GFLOP/s/W 83% FPU Utilization Dual-Chiplet, Dual-HBM2E RISC-V-Based Accelerator for Stencil and Sparse Linear Algebra Computations with 8-to-64-bit Floating-Point Support in 12nm FinFET`](/Volumes/extend_2/research_data/vlsi_paper/2024/Digital_Systems/Occamy A 432-Core 28.1 DP-GFLOPsW 83% FPU Utilization Dual-Chiplet, Dual-HBM2E RISC-V-Based Accelerator for Stencil and Sparse Linear Algebra Computations with 8-to-64-bit Floating_10631529.pdf)
- [`A 28-nm 8-bit Floating-Point Tensor Core-Based Programmable CNN Training Processor With Dynamic Structured Sparsity`](/Volumes/extend_2/research_data/jssc_full_harvest/2023/issues/vol58_issue07_is10164681/pdfs/A 28-nm 8-bit Floating-Point Tensor Core-Based Programmable CNN Training Processor With Dynamic Structured Sparsity_10124223.pdf)
- [`ASAP A 28nm Transformer Training Accelerator with Alternating Sparsity and Asymmetrical Microscaling Floating-Point Precision`](/Volumes/extend_2/research_data/vlsi_paper/2025/Digital_Systems/ASAP A 28nm Transformer Training Accelerator with Alternating Sparsity and Asymmetrical Microscaling Floating-Point Precision_11075114.pdf)

### `near-memory / programmable alternative`

- [`A Multicore Programmable Variable-Precision Near-Memory Accelerator for CNN and Transformer Models`](/Volumes/extend_2/research_data/jssc_full_harvest/2025/issues/vol00_issue99_is4359912/pdfs/A Multicore Programmable Variable-Precision Near-Memory Accelerator for CNN and Transformer Models_11235947.pdf)
- [`Colonnade A Reconfigurable SRAM-Based Digital Bit-Serial Compute-In-Memory Macro for Processing Neural Networks`](/Volumes/extend_2/research_data/jssc_full_harvest/2021/issues/vol56_issue07_is9466892/pdfs/Colonnade A Reconfigurable SRAM-Based Digital Bit-Serial Compute-In-Memory Macro for Processing Neural Networks_9373949.pdf)

## 2.2 联网补充检索范围

除了本地库，本轮也补了在线检索，主要用于：

- 确认 `2025 / 2026` 的公开 session 方向
- 补充本地库之外的标题与趋势线
- 避免只被本地已有论文限制住

本轮实际用到的在线入口包括：

- [ISSCC 2025 Advance Program](https://isscc.org/advance-program/)
- [ISSCC 2026 Advance Program PDF](https://www.isscc.org/wp-content/uploads/2025/12/ISSCC-2026-Advance-Program.pdf)
- [VLSI 2025 Advance Program](https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf)
- [IEEE Xplore / publisher pages via official links and DOI landing pages](https://ieeexplore.ieee.org/)

从 `ISSCC 2026` 官方 program 中，和我们最相关的三条趋势线非常明确：

1. `Broadcast-Alignment Floating-Point CIM Macro`
2. `Accurate/Approximate Dual-Mode-Transpose Digital 6T-SRAM CIM`
3. `Mixed-Signal CIM` 继续往更高位宽和动态精度走

这说明现在顶会里已经不只是低比特 `W8A8` 了，而是开始把：

- `floating-point`
- `transpose / dual-view`
- `approximate + accurate dual-mode`

这些主题同时往前推。

## 3. 为什么不能只看“最相关”论文

如果只盯着和我们最像的 `transpose-CIM` 或 `projector` 类工作，会漏掉三类非常关键的对照路线：

1. **高精度/浮点路线**
   - 决定我们能不能把 `FP64 contract` 讲圆

2. **不规则稀疏 / sparse-linear-algebra / CGRA / NMC 路线**
   - 决定审稿人会不会问“这件事为什么一定要用 CIM，而不是 scratchpad + FPU/NMC”

3. **系统级 dataflow 协同路线**
   - 决定我们是不是只是在做一个好看的宏，而不是一条能在真实 workload 上成立的数据流

所以本轮筛选的正确方法不是：

- 只找最像我们的一篇

而是：

- 先把所有会和我们形成竞争或可借鉴关系的方案族拉齐
- 再按 workload 约束逐层筛掉

## 4. 从全文级阅读里抽出的 6 条主轴

## 4.1 视图组织轴：`P` 和 `P^H` 怎么来

这一轴有 4 种典型做法：

1. **额外 transpose buffer**
   - 典型代表：传统 `GEMM-CIM` 加 pipeline
   - `TranCIM` 明确把它当作要避免的对象

2. **物理双副本**
   - 存一份 `P`
   - 再存一份 `P^H`

3. **宏级双方向访问**
   - `Two-Way Transpose`
   - `bitline-transpose`
   - `concurrent transpose / non-transpose`

4. **单份 row-stationary + 执行模式切换**
   - 不强行做物理转置
   - bra 走 row-wise outer-product accumulation
   - ket 走 row-wise synthesis

对我们的结论是：

- `1` 太笨重
- `2` 太占面积，且创新性不足
- `3` 可以借，但如果直接照抄，会沦为“支持转置的 GEMM-CIM”
- `4` 才真正对应 `P M P^H X` 的 workload-native 语义

## 4.2 算术域轴：计算放在哪个域里

从全文级阅读看，近年的主流分成 4 类：

1. **纯数字 CIM**
   - `Colonnade`
   - `ReDCIM`
   - `TranCIM`
   - `LLM-CIM`

2. **纯模拟 / 混合信号 CIM**
   - 多见于低比特 `INT`
   - 更强调 `TOPS/W`

3. **hybrid-domain FP-CIM**
   - `FP 6T SRAM IMC`
   - `AFP-CIM`
   - `Outer-product FP SRAM CIM`

4. **near-memory FPU / NVMAC**
   - `A Multicore Programmable Variable-Precision Near-Memory Accelerator`
   - `Occamy`

对我们的结论是：

- 纯模拟路线不适合作为主线，因为我们的核心约束是 `complex FP64`
- 纯数字路线最稳，但 bra 长归约很吃累加树
- `hybrid-domain` 适合借来解决 bra 路径的局部压缩问题
- center / reduced engine 仍然应该放在本地数字 `FP64`

## 4.3 累加边界轴：累加器应该落在哪一层

全文级阅读里最常见的四种放置方式是：

1. `cell` 级小累加
2. `subarray` 级累加
3. `macro` 级累加
4. `inter-macro` 级归并

`ReDCIM`、`TranCIM`、`AFP-CIM` 都非常清楚地说明了一件事：

- 真正决定系统级代价的，不只是 MAC 单元本身
- 而是**累加器放在哪一层**

对我们最重要的结论是：

- bra 路径不能把长归约一直拖到 inter-macro 才做
- ket 路径则可以让 inter-bank reduction 出现在输出边界
- `C^H M C` 这类 reduced 结果要单独有一个 Hermitian-aware 边界

## 4.4 数据流轴：固定 `WS` 还是做可切换 dataflow

`AFP-CIM` 很值得借的一点不是它的 `AFP4/6/8/16`，而是：

- 它明确把 `WS` 和 `OS` 都放进宏边界
- 用 `WAR` 去切 `weight / activation / p-sum` 的常驻比例

这件事对我们很重要，因为我们的问题不是普通 `W * A`，而是：

- `P` 常驻
- `X` 流式
- `C` 需要本地保留
- `M` 很小但很敏感
- `Y` 有时根本不该完整写回

所以我们真正需要的 dataflow 不是传统：

- `WS only`

而是：

- `projector-stationary + coefficient-stationary + reduced-first`

## 4.5 稀疏轴：要吃哪种 sparsity

从 `MulTCIM`、`Onyx`、`ASAP`、`Occamy` 这几条线的全文级阅读里，可以得到一个很重要的判断：

- **稀疏不是白送的**

只有当：

- 稀疏是稳定的
- 索引代价可控
- 重排不会把数据流打散

它才真的换来能效。

这对我们意味着：

### 该做的稀疏

1. `M` 的块结构
   - QE 非局域 `D` 天然接近按 atom / channel 的块结构

2. `G` 的 Hermitian 上三角
   - 这是确定性的结构压缩

3. 行级 `zero / near-zero` gating
   - 对 projector 行和输入行做精确 skip 或保守 skip

4. tail / edge tile 交给 `digital sidecar`

### 不该作为主线的稀疏

1. `P` 的通用非结构化稀疏
2. 类 Transformer 的 token sparsity
3. 类 LLM 的 outlier-aware quantization 直接照搬

原因不是这些技术没用，而是：

- 它们和 `QE / PySCF` 的主负载形状并不匹配

## 4.6 可编程性轴：如果不做 CIM，会是谁来和我们竞争

如果审稿人不是做 `CIM` 的，而是做 `processor / accelerator` 的，他最可能拿来问我们的方案有两类：

1. **`near-memory + variable-precision MAC`**
   - 更灵活
   - 更好支持复杂控制流

2. **`CGRA / manycore sparse processor`**
   - 更适合 irregular sparse linear algebra

`Occamy` 和 `Onyx` 的意义就在这里：

- 它们提醒我们，**只要地址计算和不规则控制占主导，CIM 就不一定赢**

所以我们必须把自己的切口收缩到：

- `P` 真正高复用
- `X` 真正流式
- `M` 真正小
- `G` 真正值得 reduced-first

只要不满足这四条，就应该考虑回到 `NMC / CGRA / sparse processor`

## 5. 面向 QE / PySCF 的真实约束

## 5.1 不是所有矩阵都适合常驻

从 [`soft/qe-7.5/CIM_data_residency_analysis.md`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/CIM_data_residency_analysis.md) 可以直接看出：

- `vkb`
- `xi`

这类 projector 才是最像“权重”的对象。

尤其 `xi` 的写读比在一个示例里可以到：

- `1 : 1680`

这说明：

- 如果我们不把 `P` 常驻，整个原语故事就站不稳

## 5.2 不是所有“小矩阵”都一样

对 `QE` 来说，小中心矩阵 `M` 主要有两种形态：

1. **按 atom / channel 的块结构**
   - 典型是非局域 `D`

2. **真正 dense 的 reduced 旋转矩阵**
   - 典型是子空间 `U`

这意味着 center engine 最好支持：

- block-aware mode
- dense mode

而不是只做一个固定的 `K × K` dense engine

## 5.3 真正重的是 bra，不是 center

对 `C = P^H X`：

- 归约维度是大 `N`
- 输出只有小 `K × B`

对 `T = M C`：

- 规模是 `K × K × B`

所以真正需要靠 `CIM` 吃掉的是：

- bra
- ket

而不是 center。

## 6. 组合后可落地的 6 条主线

下面不是所有可能组合，而是对我们有工程意义的 6 条主线。

## 6.1 方案 A：通用 `GEMM-CIM + transpose buffer`

### 结构

- 通用 `GEMM-CIM`
- `P^H X` 依赖额外 transpose buffer
- `M` 和 `G` 放在外围数字逻辑

### 优点

- 最容易拼现有宏
- 最容易做 baseline

### 致命问题

- `P^H` 只是外部重排，不是原语语义
- 中间 `C / T / Y` 搬运重
- 对 `G = C^H M C` 没有 reduced-first 优势

### 结论

- **只能做 baseline，不能做主线**

## 6.2 方案 B：对称双副本 `P / P^H` 宏

### 结构

- 两份 projector bank
- 一份服务 `P^H X`
- 一份服务 `P T`

### 优点

- 控制简单
- 最直观

### 致命问题

- projector 面积近似翻倍
- 论文创新性偏弱
- 对动态换 `P` 的代价很高

### 结论

- **工程上能做，但不推荐作为论文主线**

## 6.3 方案 C：CTNT / dual-transpose 浮点扩展宏

### 结构

- 借 `Two-Way Transpose` / `bitline-transpose` / `CTNT`
- 把同一份 `P` 做成 forward / adjoint 可读

### 优点

- 比方案 B 面积小
- 有现成论文血缘

### 主要问题

- 很容易退化成“支持转置的 GEMM-CIM”
- 评审会问：这和 attention / training 宏有什么本质差别
- 直接扩到 `complex FP64` 风险极高

### 结论

- **可借机制，不适合作为完整方案定义**

## 6.4 方案 D：单份 row-stationary `P` + bra outer-product + ket row synthesis

### 结构

- 只存一份 `P`
- 不物理存 `P^H`
- bra：
  - 逐行读 `P[n,:]`
  - 广播 `X[n,:]`
  - 做 `conj(P[n,:]) ⊗ X[n,:]`
  - 累到小 `C`
- ket：
  - 逐行读 `P[n,:]`
  - 乘小 `T`
  - 生成 `Y[n,:]`

### 优点

- 最贴合 `P M P^H X`
- 不需要 transpose buffer
- 不需要第二份 `P`
- bra / ket 可以物理非对称

### 风险

- bra 的局部累加和 bank 组织必须设计好
- 论文里要把“为什么这不是普通 outer-product engine”讲清楚

### 结论

- **这是当前最优主线**

## 6.5 方案 E：方案 D 的 bra-hybrid / ket-digital 版本

### 结构

- 总体仍然是方案 D
- bra 局部引入 hybrid-domain 压缩
- ket 保持更数字化、更精确

### 优点

- 和 `Guo` / `FP hybrid-domain` 路线能接上
- 能专门针对长归约减轻 adder tree 压力

### 风险

- calibration 和 `FP64 contract` 更难讲
- 如果 hybrid 侵入过深，可能削弱论文本体

### 结论

- **可以作为方案 D 的增强版，但不应先于 D 成为主故事**

## 6.6 方案 F：近存 `FP64/NVMAC` 加速器，不做 CIM 原语

### 结构

- 用多端口 SRAM / scratchpad
- 近存 `FP64` MAC / NVMAC
- 用 ISA / scheduler 驯服 workload

### 优点

- 控制最灵活
- 最适合不规则情况

### 致命问题

- 和我们 `CIM` 论文切口冲突
- 常驻 projector 的 memory-compute 融合优势会弱很多

### 结论

- **必须作为系统级强 baseline**
- **但不应作为我们最终 paper 主线**

## 7. 最终筛选结果

## 7.1 主推荐

最终最适合的主线是：

### `方案 D 为主，方案 E 为增强，方案 F 为强 baseline`

也就是：

- **单份 row-stationary 常驻 `P`**
- **bra / ket 非对称**
- **center / reduced 本地 FP64**
- **必要时在 bra 局部引入 hybrid 压缩**

## 7.2 为什么不是方案 C

因为方案 C 的故事很容易变成：

- “我做了一个会 transpose 的浮点 CIM”

但我们真正想讲的是：

- “我做了一个知道 `P M P^H X` 语义、知道 bra/ket 非对称、知道 reduced-first 的 projector primitive”

## 7.3 为什么不是方案 F

因为虽然方案 F 更灵活，但它把论文重心推向了：

- `NMC / accelerator`

而不是：

- `CIM primitive`

用户已经明确希望创新点和 `CIM` 本体强相关，所以方案 F 只能是强 baseline。

## 8. 选中方案的具体落点

## 8.1 bank 划分

推荐的 bank 划分不是按 `N` 主分，而是：

- **一级按 `K` 切 bank**
- **二级在 bank 内按 `N` 切 row-subarray**

原因是：

1. bra 阶段里 `X[n,:]` 可以广播到所有 `K-bank`
2. 每个 `K-bank` 只负责自己那一片 `C[k,:]`
3. 这样 bra 不需要跨 bank 归并 `C`
4. ket 阶段虽然要跨 `K-bank` 归并 `Y`，但它是短归约，代价可控

因此推荐组织是：

```text
Projector Cluster
= B_K 个 projector bank
每个 bank 拥有一段 K_slice
bank 内再由多个 row-subarray 覆盖 N 维
```

## 8.2 resident 数据怎么存

这里不建议只给一种死板格式，而是建议冻结成两种模式：

### 模式 1：hot-projector residue-resident

适用对象：

- `vkb`
- `xi`
- 其他明显高复用 projector

存法：

- `P_R / P_I` 分开
- 每个复数元素预展开到 `L = 16` 个 `<8b` 模数平面
- 每行配一份缩放元数据

优点：

- 最像真正的 `weight-stationary CIM`
- 运行期不再做 projector 取模

代价：

- projector bank 面积上升

### 模式 2：dynamic-projector canonical-resident

适用对象：

- 变化更快的 `Q`
- 其他不一定值得做 16 模常驻的 basis

存法：

- 常驻 canonical 整数化表示或压缩后的主表示
- 背景编码单元在换 `P` 时装填到 shadow residue bank

优点：

- 面积更稳
- 适合动态 basis

代价：

- 切换 `P` 时有装填时延

结论不是二选一，而是：

- **宏支持双 residency mode**
- **论文主故事以 hot-projector residue-resident 为主**

## 8.3 bra 路径

bra 推荐做成：

```text
row scheduler
-> 读 P[n, K_slice]
-> 广播 X[n, B]
-> 做 K_slice × B 的 outer-product residue MAC
-> 累到 bank-local C SRAM
```

这里的关键硬件点有四个：

1. `X` 必须是 row-striped 流入，而不是 column-major
2. bra 局部累加器应该落在 bank 内，而不是拖到全局
3. complex 路径做显式共轭控制，不单独存 `P^H`
4. 若引入 hybrid，只放在 bra 的局部压缩边界

## 8.4 center / reduced 路径

center engine 应直接采用本地复杂度可控的 `complex FP64`：

- dense mode：处理一般 `K × K`
- block-aware mode：处理 QE 非局域 `D`

reduced 路径应该支持：

- `G = C^H M C`
- Hermitian-aware accumulation
- upper-triangle only writeback

这部分不该硬塞进主 `CIM` 阵列里，而应放在：

- local coefficient SRAM + FP64 center engine

## 8.5 ket 路径

ket 推荐做成：

```text
T[K_slice, B]
-> 回送到各 K-bank
-> bank 内读 P[n, K_slice]
-> 形成 Y_partial[n, B]
-> K-bank reduction tree
-> output-boundary CRT / reconstruct
```

也就是说：

- ket 不需要物理 `P^H`
- 也不需要 transpose buffer
- 只需要同一份 `P` 的 forward row read

## 8.6 稀疏怎么用

最终推荐只把下面四类稀疏做成正式设计点：

1. `M` 的块结构
2. `G` 的上三角结构
3. projector / activation 行级 gating
4. tail / edge / fallback 的 sidecar 分流

不推荐把下面这些做成主线：

1. `P` 的通用非结构化稀疏
2. token-level 动态稀疏
3. LLM outlier-aware 路线直接平移

## 9. 对论文叙事的影响

按这个筛选结果，论文最稳的叙事应该是：

1. `QE / PySCF` 里存在 `P M P^H X` 型真实热路径
2. 普通 `GEMM-CIM + transpose` 不能自然表达它
3. 现有 `transpose / FP / sparse / NMC` 路线各自解决了一部分问题
4. 我们最终提出：
   - `projector-stationary`
   - `single-copy row-stationary P`
   - `asymmetric bra/ket`
   - `local FP64 center/reduce`
   - `reduced-first output boundary`

这会比“我们做了一个会转置的浮点 CIM”更像真正的电路创新点。

## 10. 当前最值得继续细化的部分

基于这轮筛选，下一步最值得继续往下做的不是继续扩论文池，而是把选中方案的 5 个电路细节冻结：

1. `B_K`、`K_slice`、`row-subarray` 的参考尺寸
2. hot-projector residue-resident 与 dynamic-projector canonical-resident 的切换协议
3. bra 局部累加器到底是纯数字压缩树还是局部 hybrid 压缩
4. ket 的 inter-bank reduction 放在 residue 域还是重构后
5. `M` 的 block-aware mode 如何兼容一般 dense mode

## 11. 一句话结论

如果把所有可行路线都放在一起比较，最适合我们这条线的并不是：

- 通用 transpose GEMM-CIM
- 也不是通用 FP/NMC accelerator

而是：

### `单份 row-stationary projector bank + K-sliced banking + bra/ket 非对称 + local FP64 center/reduce`

这条路线既保住了 `CIM` 相关的大创新点，又真正贴合 `QE / PySCF` 的负载物理形状。
