# 伴随感知型投影原语实现方案 v0

## 1. 结论先行

如果把近几年 `CIM` 宏和 accelerator 的电路结构都放在一起看，我认为这个原语**不应该**实现成：

- 一个通用 `GEMM-CIM` 宏外加一点 `transpose` 支持
- 一个纯模拟 crossbar
- 一个“所有阶段都同一种数据通路”的对称结构

更合适的实现形态应当是：

## `Projector-Stationary Asymmetric Bra/Ket Macro Cluster`

中文可以叫：

- `投影矩阵常驻的非对称 Bra/Ket 宏簇`

它的核心思想只有一句：

- **用同一份常驻 `P`，分别以“长归约 bra 路径”和“短归约 ket 路径”去实现 `P^H X` 和 `P T`，中间的小矩阵 `M` 与 reduced accumulation 留在本地 FP64 微引擎里完成。**

这不是简单拼凑，原因是整套结构都服务于同一个数学分解：

```text
Y = P M P^H X
G = X^H P M P^H X = C^H M C
```

也就是：

```text
bra 投影 -> 中心小矩阵 -> ket 回投 -> reduced 输出
```

## 2. 为什么必须这样做，而不是照搬 AI 的 GEMM-CIM

## 2.1 我们的目标不是普通 AI 推理，而是 QE 里的 FP64 复数科学计算

这件事非常关键。  
对 `QE / VASP / PySCF` 来说，约束和主流 AI-edge / LLM CIM 完全不同：

1. 目标不是 `W8A8` 或 `BF16` 推理最优能效，而是**维持 `FP64 contract`**
2. 数据流里天然存在：
   - `P`
   - `P^H`
   - conjugation
   - Hermitian / reduced matrix
3. 真实热路径常常是：
   - `project -> small transform -> back-project`
4. 很多情况下：
   - 真正重要的是 `G`
   - 而不是完整 `Y`

所以如果直接照搬 AI 里的“通用矩阵乘 + transpose/non-transpose”，会出现两个问题：

- 对我们的工作负载来说太浅
- 对 `FP64` 科学计算来说精度与搬运都不够对路

## 2.2 我们的计算形状是强非对称的

对这个原语来说：

```text
C = P^H X
T = M C
Y = P T
```

其中：

- `P ∈ C^(N×K)`，通常 `N` 很大，`K` 相对小
- `X ∈ C^(N×B)`，`B` 是 block size

于是：

- `P^H X` 是沿着大维度 `N` 的**长归约**
- `P T` 是沿着小维度 `K` 的**短归约**

这就直接决定了：

- bra 路径和 ket 路径**不应该用完全对称的电路**

这是整个实现方案里最核心的判断。

## 3. 近几年论文里真正值得借的结构

这里不是简单列 paper，而是只抽取那些真的对我们有用的结构思想。

## 3.1 Hsu et al., VLSI 2025：`Concurrent-Transpose/Non-Transpose` + layer-fused flow

用户给的这篇 paper：

- [`Hsu et al. 2025 PDF`](/Volumes/remote/Zotero/storage/VDIJEW27/Hsu 等 - 2025 - A 22nm 41.8TFLOPSW AI-Edge TransformerCNN Nonvolatile-Processor Using QKV-Softmax-Layer-Fused Hybr.pdf)

官方出处：

- [VLSI 2025 Advance Program](https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf)

这篇 paper 的关键结构不是“新原语”，而是：

1. `Concurrent-Transpose/Non-Transpose SRAM-CIM`
2. `QKV-Softmax Layer-Fused flow`
3. row-by-row pipeline
4. 尽量减少中间结果存取

我们真正该借的是：

- **同一份 resident 数据支持两种视图**
- **把原本分立的阶段融合成一条数据流**

但我们不该照搬它的地方是：

- 它的目标是 attention 的 dynamic MM
- 它默认还是 `MAC/GEMM` 主语
- 它并没有面对 `FP64`、conjugation 和 reduced Hermitian 输出

换句话说，这篇 paper 给我们的是：

- `dual-view` 和 `flow fusion` 的启发

不是最终原语本体。

## 3.2 Guo et al., SCIS 2025：hybrid CIM + compressed adder tree + 可扩展 accumulation

参考：

- [PKU Institutional Repository entry](https://repository.pku.edu.cn/handle/20.500.11897/781339)

这篇工作的重要点在于：

1. 用 hybrid analog/digital 结构处理不同 accumulation length
2. 用 `4:2 compressor-based adder tree`
3. 用 `analog-storage quantizers`
4. 目标是让 accumulation length 扩展更平滑

这对我们尤其重要，因为：

- `P^H X` 的 bra 路径正是**长归约**
- 这条路最怕 adder tree 爆掉或输出带宽过大

我们真正该借的是：

- **bra 路径不应傻做纯数字大归约**
- 而应当考虑“局部压缩 + 层级累加 + 受控量化/保持”的长归约结构

## 3.3 Yue et al., ISSCC 2023：intensive-CIM + sparse-digital side architecture

参考：

- [CAS official news](https://english.cas.cn/newsroom/research_news/infotech/202302/t20230222_328328.shtml)

这篇工作强调的是：

1. 把高利用率、规则的那部分送进 `intensive-CIM`
2. 把长尾、稀疏、边角、异常部分送到 digital side

对我们来说，这个想法非常适合：

- `edge tiles`
- `small-K tails`
- fallback
- 极端动态范围
- 某些复杂 conjugation / correction path

这意味着我们的原语不应该把所有 case 强行塞进主宏，而是要有：

- `digital sidecar`

它不是补丁，而是正式设计的一部分。

## 3.4 CELLA, VLSI 2025：按阶段切换模式的 compute-memory co-optimization

参考：

- [VLSI 2025 Advance Program](https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf)

`CELLA` 的关键不是它具体做 LLM，而是：

1. 针对不同阶段做 mode split
2. `prefill` 和 `decoding` 不用同一条最优数据通路
3. 把 memory 和 compute 一起协同设计

这给我们的启发是：

- **bra / ket / reduce 三个阶段也不该共享完全同一种 mode**

所以我们应该让这个原语天然支持：

- `bra mode`
- `ket mode`
- `reduce mode`
- `full fused mode`

## 3.5 2026 年 dual-directional nvSRAM：同一阵列支持两方向计算与 SCW

参考：

- [Nature 2026 dual-directional nvSRAM article](https://www.nature.com/articles/s41586-025-09054-2)

这篇工作的关键点在于：

1. 同一阵列支持 row-wise / column-wise operation
2. 支持 `simultaneous compute-and-write (SCW)`
3. 说明“同一份 resident 权重支持双方向访问”在电路上不是空想

对我们来说，这一条非常重要，因为我们最核心的 resident 数据就是：

- `P`

而我们想做的正是：

- 同一份 `P`
- 同时服务 `P^H X` 和 `P T`

## 4. 我建议的实现总结构

## 4.1 总体块图

我建议的总结构是一个 5 块式宏簇：

1. `Dual-View Resident Projector Banks`
2. `Bra Projection Front-End`
3. `Local Coefficient SRAM + FP64 Center Engine`
4. `Ket Back-Projection Engine`
5. `Hermitian Reduced Accumulator + Digital Sidecar`

可以概括成：

```text
resident P
-> bra projection (long reduction)
-> local C SRAM
-> local FP64 center M engine
-> ket back projection (short reduction)
-> optional reduced output G
```

## 4.2 为什么这不是拼凑

因为这 5 块并不是五个独立想法，而是分别对应同一个算子的不同因子：

- `P^H X`
- `M C`
- `P T`
- `C^H M C`

也就是说，它们不是“拿五篇 paper 各抽一块”，而是：

- 每一块都直接服务 `P M P^H X`

这是它和简单拼装最大的区别。

## 5. 块 1：Dual-View Resident Projector Banks

## 5.1 设计目标

这一块的任务是：

- 常驻存放 `P`
- 允许以 `P` 和 `P^H` 两种视图读取
- complex 模式下支持 conjugation

## 5.2 不建议做的事情

我不建议一开始就做：

- 两份完整物理副本 `P` 和 `P^H`

因为这会把面积直接翻倍，而且创新性不足。

## 5.3 建议的做法

建议用：

- **双方向读出 + 地址重映射 + 局部共轭选择**

具体来说：

1. `P_R` 和 `P_I` 分开存
2. bra 模式下：
   - 走 `adjoint view`
   - 对虚部引入 sign flip 实现 conjugation
3. ket 模式下：
   - 走 `forward view`
   - 不做 conjugation

这样：

- `transpose` 只是路径切换
- `conjugation` 只是局部符号控制
- 原语本体仍然是 `P M P^H X`

## 5.4 这块真正的创新点

真正可以 claim 的不是“支持 transpose”，而是：

- **同一份常驻 projector bank，针对 bra 和 ket 两种物理语义做双视图访问**

也就是把：

- `transpose/non-transpose`

从 attention 里的数据访问优化，抬升成：

- `P^H` 和 `P` 的语义级支持

## 6. 块 2：Bra Projection Front-End

## 6.1 这是长归约路径

这一块负责：

```text
C = P^H X
```

它的特点是：

- `N` 大
- dot-product 很长
- 输出 `C` 很小

所以它不是普通 `GEMM` 最擅长的形状，而是一个：

- **大输入归约到小系数块**

的形状。

## 6.2 建议的实现

我建议 bra 路径采用：

- `projector-stationary`
- `long-reduction hybrid accumulation`

更具体地说：

1. 子阵列内部先做局部 partial accumulation
2. 用压缩加法树或受控量化保持去减轻长归约压力
3. 每个 bank 只把压缩后的 partial coefficient 推到局部系数 SRAM

这正是从 Guo 那类 `hybrid CIM + compressor tree + scalable accumulation` 工作里借来的思想。

## 6.3 为什么 bra 路径不适合纯模拟大一统

因为我们的约束不是 AI 推理那种：

- 可以接受较松的误差预算

而是：

- 最终要维持 `QE` 的 `FP64 contract`

所以 bra 路径可以引入：

- 局部 hybrid / compressed accumulation

但不应该把最终结果完全留在不可控的模拟域里。

更合理的是：

- **在子阵列内压缩**
- **在局部系数边界重回可控数字 / residue / 高精度域**

## 7. 块 3：Local Coefficient SRAM + FP64 Center Engine

## 7.1 这是整个原语的“数学心脏”

这一块负责：

```text
T = M C
```

同时还承担：

- `C` 本地保留
- reduced accumulation
- precision control

## 7.2 为什么这里必须是 FP64 优先

如果说这个原语有哪一块必须优先保证精度，那就是这里。

原因有两个：

1. `K×K` 很小，做 FP64 的代价可控
2. 真正最敏感的数值操作常常发生在：
   - `M C`
   - `C^H M C`

所以我的建议非常明确：

- **center engine 不要做近似 CIM**
- **直接做一个本地 complex FP64 数字微引擎**

它可以复用我们当前已有的：

- `Ozaki-II + CRT + 3M`
- 或直接一个小型 FP64 dense engine

但无论如何，这一块不应牺牲精度。

## 7.3 这块和原语创新的关系

这块不是“另一个小 solver”。  
它的作用是把整个原语从：

- “只是支持 `P^H` 和 `P`”

变成：

- “真正支持 `P M P^H`”

也就是说，没有它，这个原语就退化成纯 projector 引擎，而不是 projector sandwich primitive。

## 8. 块 4：Ket Back-Projection Engine

## 8.1 这是短归约路径

这一块负责：

```text
Y = P T
```

和 bra 不同，它的特点是：

- reduction 维度 `K` 小
- 输出维度 `N` 大

所以它不需要为长归约专门设计很重的 accumulation 路径。

## 8.2 建议的实现

这一块建议：

- 复用同一份 resident `P`
- 用 forward view
- 采用更偏数字化、更偏精确的短归约路径

这块不需要像 bra 一样强调压缩加法树或 analog-storage quantizer，因为：

- 它的难点不在长归约
- 而在高吞吐回投和输出组织

## 8.3 为什么 bra/ket 要非对称

这正是这个原语实现里最有“味道”的地方：

- AI 里的 transpose/non-transpose 宏通常在电路上尽量做对称
- 但我们的 workload 本质不对称

所以我们不应该机械追求“两个方向完全等价”，而应当明确做：

- **bra 优化长归约**
- **ket 优化短归约与输出**

这会比照搬 attention 宏更像一个新的原语实现。

## 9. 块 5：Hermitian Reduced Accumulator + Digital Sidecar

## 9.1 Reduced-first 是必须保留的设计原则

很多时候真正需要的不是完整 `Y`，而是：

```text
G = C^H M C
```

或者：

```text
G = X^H Y
```

因此这块应该提供：

- Hermitian-aware accumulation
- triangular writeout
- reduced-only writeback

这会直接决定这个原语能不能比 `GEMM + transpose support` 真正省流量。

## 9.2 Digital sidecar 为什么不是补丁

我建议保留一个正式的 `digital sidecar`，处理：

- tail tiles
- edge shapes
- 极端动态范围
- fallback
- correction
- 复杂共轭 / 边界模式

这个思路直接对应到 `intensive-CIM + sparse-digital` 那类工作：

- 规则高利用率主路径放在宏里
- 不规则和低利用率长尾放到数字侧

这不是妥协，而是让系统真正可落地。

## 10. 面向 QE 的 FP64 与 mixed precision 该怎么放

## 10.1 精度不是创新点，但它是硬约束

这点必须讲清楚：

- `FP64 contract` 是系统要求
- 不是这篇电路论文的主创新点

换句话说：

- 精度是底座
- 原语是创新

不能反过来。

## 10.2 我建议的精度分层

建议做成三层：

### 第 1 层：resident projector 主算力路径

这里用：

- `Ozaki-II + CRT + 3M`
- 或兼容它的 residue-domain path

来承接真正重的 `P^H X` 和 `P T`。

理由：

- 这是我们当前已有的 `FP64` 主线
- 也是最贴近仓库已有实现积累的路径

### 第 2 层：center / reduced engine

这里直接保持：

- `complex FP64`

理由：

- 规模小
- 对精度最敏感
- 没必要为省一点点面积把数值 contract 搞脏

### 第 3 层：可选 mixed precision 模式

这层不是主路径，而是可选增强：

- 对数值较不敏感的阶段、tile 或预筛选路径
- 可以使用：
  - `FP32`
  - `BF16`
  - 或更低位宽的 screening mode

但这层一定要满足：

- 不能破坏最终 `FP64` contract
- 必须有 error monitor 或 conservative fallback

所以 mixed precision 的正确姿势不是：

- 全原语都改成低精度

而是：

- **主路径保证 FP64**
- **局部阶段允许 mixed precision 提速/省能**

## 10.3 这和近年论文的关系

近几年很多宏都支持：

- `W8A8`
- `FP16`
- `BF16`
- 模式切换

这说明：

- `mode-aware precision scaling`

在顶会里是可接受的。

但我们的区别是：

- mixed precision 只是辅助模式
- 不是主工作模式

这点必须和 AI 宏拉开。

## 11. 这个方案真正“让人眼前一亮”的地方在哪

如果最后只是说：

- 我们做了一个支持 `P` 和 `P^H` 的宏

那还不够。

真正值得打的创新点，我认为是这三个：

## 11.1 创新点一：Projector-Stationary 的双视图原语化

不是 generic matrix multiply 的 transpose 支持，而是：

- **同一份常驻 `P` 被原语化地同时服务 `P^H X` 与 `P T`**

这个“语义提升”比单纯 CTNT 更深。

## 11.2 创新点二：Bra/Ket 非对称电路实现

这是最像电路创新的地方。

不是为了形式对称，而是根据负载本身：

- bra 是长归约
- ket 是短归约

于是电路故意做成：

- bra：hybrid / compressed / long-reduction optimized
- ket：digital / exact / short-reduction optimized

这是一个很自然、也很容易让评审记住的点。

## 11.3 创新点三：Reduced-first 输出边界

大部分 `CIM` 宏默认都想把完整输出吐出来。  
但我们的 primitive 里很多时候更值钱的是：

- `G = C^H M C`

所以如果硬件能原生支持：

- `reduced-only writeback`
- `Hermitian triangular output`

它就不再只是一个“矩阵乘法宏”，而是一个真正知道 workload 语义的原语。

## 12. 不该做成什么样

为了避免走歪，我觉得下面几种实现都不应该选：

1. `纯模拟 crossbar 一把梭`
   - 对 `FP64`、complex conjugation、reduced output 都不友好

2. `完全对称的 transpose/non-transpose 通用宏`
   - 太像 attention 结构，不够像 projector primitive

3. `只做一个大 GEMM-CIM，再把 M 和 reduced 放到软件`
   - 这样原语就塌了

4. `把 mixed precision 当主创新`
   - 这会把真正的原语创新冲淡

## 13. 当前推荐的 v0 实现落点

如果只给一个最现实、最有论文味的版本，我建议是：

### `数字 SRAM-CIM 为主、局部长归约 hybrid 化、center/reduce 保持 FP64 的 projector 宏簇`

更具体一点：

1. `P` 常驻在 dual-view digital SRAM-CIM bank
2. bra 路径做长归约优化
3. `C/T` 保存在本地 coefficient SRAM
4. `M C` 与 `C^H M C` 在本地 complex FP64 微引擎里完成
5. ket 路径复用同一份 `P` 做短归约回投
6. sidecar 处理边角 / fallback / correction

这套结构既：

- 有顶会论文可借鉴的结构基础
- 又有足够清晰、不是拼装的原语创新点
- 同时还能接上我们已有的 `FP64 Ozaki/CRT` 主线

### 补充说明：广覆盖方案筛选结果

本文件到这里为止，给的是我当前最认可的实现落点。  
如果要看“为什么不是别的路线”，例如：

- 为什么不是 `GEMM-CIM + transpose buffer`
- 为什么不是双副本 `P / P^H`
- 为什么不是通用 `FP/NMC` 加速器
- 为什么 `bank` 更适合优先按 `K` 切，而不是按 `N` 主切

请直接看：

- [`projector_primitive_hardware_solution_space_20260316.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/projector_primitive_hardware_solution_space_20260316.md)

那份文档不是只找最相关论文，而是把：

- `transpose / dual-view`
- `floating-point CIM`
- `sparsity / irregular dataflow`
- `near-memory / programmable accelerator`

几条主线一起做了全文级方案扫描，最后筛出来的主推荐仍然是：

- **单份 row-stationary 常驻 `P`**
- **按 `K` 切 bank**
- **bra / ket 非对称**
- **local FP64 center / reduced**

## 14. 下一步最该做什么

如果要把这个点从概念推进到 paper-ready，我建议按这个顺序做：

1. 先把 bra / ket / center / reduce 四条路径的 cycle/energy model 拆出来
2. 在 `QE` 上对：
   - `vkb`
   - `xi`
   - `Q`
   做真实尺寸和复用率画像
3. 做三组 baseline：
   - `GEMM + transpose`
   - `symmetric CTNT macro`
   - `ours: asymmetric projector primitive`
4. 再决定 bra 路径内部究竟采用：
   - 纯数字压缩树
   - 还是 hybrid accumulation

## 15. 一句话总结

我当前最认可的实现路线是：

```text
不要把它做成“支持转置的通用 GEMM-CIM”，
而要做成“投影矩阵常驻、bra/ket 非对称、center/reduce 本地 FP64”的 projector primitive 宏簇。
```

这条线既和近几年顶会里真正成功的结构有血缘关系，又保留了足够强、足够新的原语级创新空间。

## 16. 参考来源

### 论文 / 官方会议信息

- Hsu et al., `A 22nm 41.8TFLOPS/W AI-Edge Transformer/CNN Nonvolatile-Processor Using QKV-Softmax-Layer-Fused Hybrid ReRAM-CIM and Concurrent-Transpose/Non-Transpose SRAM-CIM`
  - 本地 PDF：
    - [`Hsu 等 2025 PDF`](/Volumes/remote/Zotero/storage/VDIJEW27/Hsu 等 - 2025 - A 22nm 41.8TFLOPSW AI-Edge TransformerCNN Nonvolatile-Processor Using QKV-Softmax-Layer-Fused Hybr.pdf)
  - 官方 program：
    - [VLSI 2025 Advance Program](https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf)

- Guo et al., `A 64kb Lightning-Like Hybrid Computing-In-Memory Macro ...`
  - [PKU Institutional Repository](https://repository.pku.edu.cn/handle/20.500.11897/781339)

- Yue et al., `An Intensive-CIM Sparse-Digital Based Processor`
  - [CAS official news](https://english.cas.cn/newsroom/research_news/infotech/202302/t20230222_328328.shtml)

- `CELLA: A 64MB Fully On-Chip W8A8 LLM-CIM Accelerator ...`
  - [VLSI 2025 Advance Program](https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf)

- Wang et al., `A 2T4R 4kb nvSRAM Array with Row-/Column-Wise...`
  - [Nature article](https://www.nature.com/articles/s41586-025-09054-2)

### 仓库内已有基础

- [`adjoint_projector_primitive_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/adjoint_projector_primitive_spec_v0.md)
- [`ozaki_crt_algorithm_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/ozaki_crt_algorithm_freeze_v0.md)
- [`complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)
- [`complex_fp64_gemm_cost_model_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)
