# 2026-03-27 论文精读：Liu et al. 2023 heterogeneous PIM for quantum chemistry

## 1. 基本信息

- 标题：`A heterogeneous processing-in-memory approach to accelerate quantum chemistry simulation`
- 作者：`Zeshi Liu`, `Zhen Xie`, `Wenqian Dong`, `Mengting Yuan`, `Haihang You`, `Dong Li`
- 期刊：`Parallel Computing 116 (2023) 103017`
- DOI：`10.1016/j.parco.2023.103017`
- 本地 PDF：`/Volumes/remote/Zotero/storage/PD99BZQX/Liu 等 - 2023 - A heterogeneous processing-in-memory approach to accelerate quantum chemistry simulation.pdf`
- Zotero key：`YHZGZQ44`

## 2. 一句话总结

这篇文章不是在讲某个孤立 kernel，而是在讲一个 **`CPU + heterogeneous PIM` 混合系统** 如何围绕 `Quantum ESPRESSO` 的两类重热点——`FFT` 和 `time-consuming loops`——做硬件/运行时协同加速；它的核心价值在于证明：**科学计算软件完全可以用“真实软件 + 混合系统 + runtime + memory-centric accelerator”这条路径来组织故事**。

## 3. 论文在解决什么问题

作者的核心问题不是“如何让某个算子更快”，而是：

- `DFT / ab initio quantum chemistry` 计算有非常大的内存 footprint；
- `GPU` 虽然能提供高吞吐，但仍然受 host-device 数据移动、显存容量和不规则计算模式限制；
- 在 `Quantum ESPRESSO` 这类软件里，`FFT` 和大量 loop-based 计算占用了大部分时间，而且两者都和 memory wall 强相关；
- 因此，作者希望通过 **heterogeneous PIM**，把“靠近数据的 fixed-function compute”和“更灵活的 programmable compute”结合起来，并辅以 runtime 调度，来改善性能、能耗和硬件利用率。

换句话说，这篇文章的系统对象从一开始就是：

> 真实科学计算软件 + CPU 主机 + 内存近旁异构加速单元 + runtime/offload 机制

而不是单独一块 PIM macro。

## 4. 真实系统对象与边界怎么切

### 4.1 它的真实系统对象

这篇文章的真实系统对象是：

- `CPU host`
- `3D-stacked memory` 上的 heterogeneous PIM
  - `fixed-function PIMs`
  - `programmable PIMs`
- 被加速的软件是 `Quantum ESPRESSO`
- 被重点承接的软件热区是 `FFT` 和 `loop-based phases`

所以它本质上是一个 **host + accelerator + runtime + real application** 的混合系统对象。

### 4.2 它的 chip/local object

它的 chip-local object 不是完整 QE，也不是完整 SCF 外环，而是：

- memory-stack logic layer 中的 heterogeneous PIM
- 重点承接 `FFT` 和 loop 里的 fixed/flexible 计算
- programmable PIM 负责协调 local fixed-function PIM

### 4.3 它切边界的层级

它的切法比“单 kernel accelerator”更大，但又没有大到“完整软件全上片”：

- **不是** 只讲 `BLAS` / `FFT` IP；
- **也不是** 整个 DFT workflow 全系统重写；
- 它更接近：
  - 真实软件 `QE`
  - 抓住占主导时间的阶段
  - 把这些阶段映射成 `CPU + PIM + runtime` 的异构执行对象

如果用我们自己的语言描述，它更像：

> 一个围绕真实 QE 热点阶段的混合系统级切口

而不是 primitive 级切口。

## 5. 方法与架构

### 5.1 硬件

他们提出的是 heterogeneous PIM：

- `fixed-function PIM`
- `programmable PIM`
- 两者组合成 fixed-programmable model
- 在 24-bank memory stack 上布置 `24 programmable PIMs` 和 `288 fixed-function PIMs`
- fixed-function pattern 从经典形式扩展到更适合其应用的表达，例如 `'(a+b)*x+c'`

这说明他们不是单纯在堆更多固定单元，而是在找：

- 并行度
- 灵活性
- 同步开销
- 面积/热约束

之间的折中。

### 5.2 软件与 runtime

软件侧有三件事非常关键：

1. **data locality-aware mapping**
2. **hybrid execution method**
3. **基于 OpenMP target 的 offload 改造**

他们不是完全重写 `QE`，而是：

- 用扩展的 OpenMP/program constructs 标记可 offload 区域；
- runtime 根据 locality 和 PIM busy status 形成 task queue；
- programmable PIM 负责协调 fixed-function PIM；
- 再用 prefetching 减少硬件 idle。

### 5.3 对原软件改动有多大

这是非常值得注意的一点：

- 论文声称应用层主要是 directive 级修改；
- 对 DQC/QE 的 mirror modification 大约 `200 lines of code`；
- 但 OpenMP runtime 也需要改；
- 所以它并不是“零侵入”，而是 **应用层小改 + runtime 层实质性改造**。

## 6. 它怎么证明自己“真的解决了问题”

### 6.1 先做热点归因

作者不是上来就报 speedup，而是先做 profile：

- 在选定的 QE case 上，`FFT + loops` 占总执行时间约 `78% ~ 79%`；
- FFT 有非常高的调用次数和 cache miss；
- loop 部分同时包含 fixed pattern 和 flexible pattern；
- 分布式系统上 collective communication 代价也很高。

这一步很重要，因为它证明了：

> 他们抓的不是任意阶段，而是对整体时间真正有统治性的部分。

### 6.2 baseline 怎么立

它的 baseline 不是单一的：

- bare CPU
- CPU + GPU
- CPU + fixed-function PIM only
- CPU + programmable PIM only
- heterogeneous PIM (their design)
- prior heterogeneous PIM design

这是一个比较完整的 baseline ladder，至少包含：

- 传统通用系统 baseline
- 单一 PIM 子类 baseline
- 旧的异构 PIM baseline

### 6.3 证据链是什么

它的证据链大致是：

1. `profile` 证明 FFT/loops 是主热点；
2. `hardware design` 证明 fixed + programmable 组合有必要；
3. `runtime design` 证明 task queue + prefetching 能提升 utilization；
4. `execution time`、`energy`、`hardware utilization` 共同证明设计有效。

### 6.4 最终指标

论文里最核心的结果包括：

- heterogeneous PIM 相对 bare CPU 平均 speedup 约 `3.73×`
- 相对 bare CPU 最高 speedup 达 `4.09×`
- 相对 GPU (`NVIDIA P100`) 最高 speedup 达 `2.60×`
- 相对 CPU 节能约 `71%`
- 相对 GPU 节能约 `88%`
- 组合 `task queue + prefetch` 时，PIM utilization 平均约 `93%`

## 7. 这篇文章的强项

### 7.1 它证明了“真实软件 + 混合系统”是可讲的

这点对我们最重要。

它不是做一个脱离软件语境的 memory macro，而是直接绑定真实 `QE`。这说明：

- 科学计算加速论文可以不是纯 kernel 论文；
- 也可以不是完整 application paper；
- 完全可以是 **真实软件热点 + hardware/runtime co-design** 的中间层切法。

### 7.2 它的 baseline 和证据链比较像样

它没有只和一个弱 baseline 比，而是做了多层对照。这对我们后面设计自己的 baseline ladder 很有参考价值。

### 7.3 它明确承认 runtime 是核心组成部分

这也和我们当前直觉一致：

- 真正的系统对象不是只有 chip；
- runtime / orchestration 不是配角；
- 如果没有运行时调度和 locality-aware dispatch，硬件潜力很难兑现。

## 8. 这篇文章的局限

### 8.1 它的对象比我们现在想抓的对象更“宽”

它抓的是 `DQC/QE` 里的 `FFT + loops` 这两大热点，整体上仍偏宽。

而我们现在逐渐收口的是：

- `QE-connected band-solver subsystem`
- 甚至更具体到 `c_bands episode`
- 再进一步聚焦 `projector / reduced-space / generalized eigensolver`

所以这篇论文更像一个 **更上层、更宽的系统切口对照物**，不是直接给我们 primitive/story 定位的模板。

### 8.2 数值与算法层没有碰我们最难的点

它主要解决：

- memory movement
- FFT
- loops
- runtime utilization

它没有真正进入我们现在最关心的那些难点：

- generalized Hermitian reduced problem
- `S_sub` 合同
- `Ozaki / CRT / complex FP64`
- primitive 与 macro 级收益表达

### 8.3 硬件与实验口径有其时代和假设限制

它的比较对象里 GPU 是 `P100`；
PIM 结果大量依赖建模与仿真；
应用工作负载展示也比较集中，不是很宽的 benchmark matrix。

因此它更适合作为：

- 架构和叙事对照；
- baseline 组织对照；
- mixed-system 合法性对照；

而不是直接拿来当最终性能预期模板。

## 9. 对我们当前方案的具体启发

### 9.1 支持我们的地方

这篇文章强烈支持下面几件事：

1. **真实系统对象应该是混合系统**
   - 它也是 `host + accelerator + runtime + real software`
   - 这和我们强调的 `Host/QE + FPGA/runtime + Chip` 非常一致

2. **runtime 必须被正名**
   - 他们把 runtime 直接作为主要贡献的一部分
   - 这支持我们把 `FPGA/runtime transaction scheduler` 放进真实系统对象里

3. **系统级 baseline 是必要的**
   - 只做 primitive 对比不够
   - 最后还是要回到真实软件连接的系统比较

### 9.2 和我们不同、提醒我们谨慎的地方

1. **他们是宽热点切法，我们是更窄的 subsystem 切法**
   - 他们抓 `FFT + loops`
   - 我们抓 `band-solver / c_bands episode / projector + reduced-space`
   - 这意味着我们不能简单照搬他们的 story

2. **他们讲的是 memory-intensive application 加速**
   - 我们后面要讲的是更强的 `domain-specific accelerator / digital processing`，而且更强调 subsystem contract

3. **他们没有解决我们最危险的数学合同问题**
   - 所以这篇能帮我们证明“mixed-system 是合理的”
   - 但不能替我们回答“generalized eigensolver / FP64 complex primitive 应该怎么冻结”

## 10. 对我们当前路线的结论性判断

如果把这篇文章作为第一个强种子，那么它给我们的最重要结论是：

> 你的方向里，“真实软件路径 + 混合系统对象 + runtime + accelerator” 这条大框架本身没有问题，甚至是被现有文献支持的。

但它同时也说明：

> 我们当前真正需要继续收紧的，不是“能不能讲混合系统”，而是“为什么必须切到 `QE-connected band-solver / c_bands episode` 这一层，而不是像他们一样停在更宽的 FFT+loops / DQC 热点层”。

这也是我们下一步最该回答的问题。

## 11. 对下一步工作的建议

读完这篇后，最合理的下一步不是外网大搜，而是继续在本地做一件事：

- 把这篇作为 **“更宽系统 cut” 参考物**；
- 然后对照我们自己的方案，写一个短文档：
  - `Liu 2023` 这种 `FFT + loops / DQC-wide` cut 为什么不够适合我们；
  - 我们为什么要继续收口到 `QE-connected band-solver subsystem`；
  - 这会怎样影响后面的 KPI、baseline 和系统边界。

如果这一步写清楚，后面再进入外部扩展调研会更稳。
