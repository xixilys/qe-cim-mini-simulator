# 2026 顶会 Session 地图：Processor / Accelerator / CIM 赛道重看（2026-03-14）

## 1. 为什么要补这份 memo

前一版判断把注意力过多放在了：

- `CIM`
- `new compute`
- `VLSI > ISSCC > JSSC`

这个结论本身不算错，但不够完整。  
因为从 `2026` 年官方 program / CFP 来看，`processor`、`accelerator`、`domain-specific accelerator` 这些主线并没有和 `CIM` 割裂，反而是在明显交叉。

所以这份 memo 只回答一个更实际的问题：

- **我们这个工作到底可以往哪些 2026 主流 session/category 上挂，分别需要长成什么样？**

## 2. 先说结论

你说得对，我们**完全不能把自己只锁死在 `CIM` session**。

按 `2026` 年官方会议信号看，我们至少有下面四种可能包装：

1. `CIM macro`
   - 走 `Compute-in-Memory`

2. `Domain-Specific Accelerator`
   - 走 `Technology and Circuits for Domain-Specific Accelerators`

3. `Processor / SoC`
   - 走 `Processors` 或 `Processors & SoCs`

4. `Digital processing technique / subsystem`
   - 走 `Digital Processing and Circuit Techniques`

但这四种包装对论文内容的要求完全不同。  
**当前我们最自然的是 `DSA / CIM`，不是 `processor`；但如果你想往 processor/accelerator session 挂，并不是不行，只是要把工作做得更像系统级芯片，而不是单一计算宏。**

## 3. ISSCC 2026：官方 session 已经把路铺得很宽了

`ISSCC 2026` 官方 advance program 已经公开，所以这个判断是基于**真实 session 名称**，不是猜的。  
会议日期是 **2026 年 2 月 15 日到 2 月 19 日**。

和我们最相关的 session 包括：

### 3.1 Session 2: Processors

`ISSCC 2026` 把 `Processors` 单独作为 `Session 2`。更关键的是，这个 session 里实际收的内容并不只是传统 CPU。

官方 program 里这一场包含了：

- `AMD Instinct MI350 Series GPUs`
- `A Quad-Chiplet AI SoC`
- `An End-to-End Driving Processor`
- `An Inference-Optimized Scalable AI Accelerator`
- `A Transformer-Based Diffusion Model Processor`
- `A Generative Diffusion Accelerator`
- `3D GS Processor`

这说明 `ISSCC 2026` 的 `Processors` 已经明显扩大到：

- `GPU`
- `AI SoC`
- `application processor`
- `large accelerator-class processor`
- `chiplet processor`

也就是说，如果我们的工作未来长成：

- 有明确的 control / scheduling / memory hierarchy
- 有 programmability
- 有完整 SoC / processor 叙事

那它**理论上可以往 processor 赛道靠**，并不需要被限制在 `CIM`。

## 3.2 Session 10: Digital Processing and Circuit Techniques

`ISSCC 2026` 还有 `Session 10: Digital Processing and Circuit Techniques`。

这类 session 的特点是：

- 不一定要讲一个完整 processor
- 也不一定要讲纯 `CIM`
- 但要有比较硬的 digital/circuit technique

官方这场里出现了例如：

- `3nm ... SoC with Chiplet Support for ASIL-D Automotive Cross-Domain Applications`
- `3nm-Plus Mobile CPU`
- `processor clock-power reduction`
- `workload-aware droop mitigation`
- `3D Network-on-Chip DNN processor`
- 甚至 `SAT` / `Ising` 一类非传统计算芯片

这说明它接受：

- processor 里的关键数字电路技术
- 特定 digital subsystem
- 新型计算引擎
- 更广义的高性能数字处理芯片

如果我们的创新点最终落在：

- paired-operator dataflow
- shared encoding / sensing
- projection-aware local accumulation
- 与 chiplet / memory / power delivery 强耦合的数字路径

那这类 session 也不是不可能。

## 3.3 Session 18: Technology and Circuits for Domain-Specific Accelerators

这场对我们尤其重要。  
`ISSCC 2026` 明确存在：

- `Session 18: Technology and Circuits for Domain-Specific Accelerators`

官方 paper 题目里能看到的方向包括：

- photonic interposer routing
- ASR accelerator with CIM/TCAM components
- sparse-MoE language processing unit with `NPU-CIM` core
- neuromorphic compute-near/in-memory processor
- visual autoregressive accelerator

这说明这一场的审稿口味是：

- 不要求你一定是“通用 processor”
- 也不要求你一定是“纯 AI training chip”
- 但你要像一个**真正的加速器方向**，有明确 workload、明确 datapath、明确电路/架构收益

对我们来说，这比“只讲 QE”要宽，也比“硬凹成通用 processor”更自然。

如果我们把论文包装成：

- `generalized-eigen / non-orthogonal workload accelerator`
- 以 `dual-operator projection primitive` 为核心
- 配上真实 `QE / PySCF` + synthetic paired-operator benchmarks

那它最像的其实就是这条线。

## 3.4 Session 30: Compute-in-Memory

`ISSCC 2026` 依然有：

- `Session 30: Compute-in-Memory`

这一场还是主流热赛道。  
官方题目继续围绕：

- `TOPS/W`
- `TOPS/mm2`
- `digital CIM`
- `ReRAM / SRAM / gain-cell`
- quantization / data format

所以如果我们最终主张的是：

- 一个新的 paired-operator CIM macro
- 收益主要来自阵列 / 感测 / 重构 / 外围共享

那这仍然是最自然的 `macro-first` 挂法。

但要注意：

- 这条线最强调 **macro innovation**
- 不太关心上层 solver 本身

也就是说，一旦挂这个 session，论文主角必须是：

- array organization
- encoding / sensing / ADC / reduction
- accuracy-energy-density

而不是 `QE`。

## 3.5 Session 31: AI Accelerators

`ISSCC 2026` 还有：

- `Session 31: AI Accelerators`

官方内容基本是：

- `LLM accelerator`
- `GenAI accelerator`
- `Vision-Language Model accelerator`
- `mobile intelligence SoC`
- `always-on vision processor`

这说明这条线在 `2026` 年仍然很强，但口味非常偏：

- mainstream AI benchmark
- token/s、TOPS/W、on-device AI
- 大模型 / 视觉 / 多模态

所以对我们来说：

- **不是完全不能碰**
- 但如果 benchmark 还是 `QE / PySCF` 为主，这条线并不自然

除非我们把故事改得非常“通用 paired-operator accelerator”，并给出更一般的 benchmark，否则不建议强挂。

## 3.6 Session 17: Highlighted Chip Releases for AI

这一场更偏：

- 大厂重磅芯片发布
- 平台级 NPU / accelerator / AI SoC

官方里面有：

- `NVIDIA GB10`
- `STM32N6`
- `Mobilint NPU SoC family`
- `Microsoft MAIA`

这说明这条线是非常工业化、平台化的 showcase。  
除非我们以后真的做成一个完成度很高的系统芯片，否则现在不应该把它当主目标。

## 4. VLSI 2026：截至 2026-03-14，正式 technical session 还没公布，但 category 已经很清楚

`VLSI 2026` 的日期是 **2026 年 6 月 14 日到 6 月 18 日**。  
截至 **2026 年 3 月 14 日**，官方网站明确写着：

- program 仍在开发
- `Summary` 页面会在 **4 月中旬**给出更多 program details
- `Program PDF` 会在 **5 月中旬**发布

所以今天这个时间点，**VLSI 2026 还没有可引用的正式 technical session 名称列表**。  
但它已经公开了官方 scope/category，这对赛道判断已经很够用了。

官方 scope 里与我们相关的项包括：

1. `Computing/Processing in Memory`
2. `Devices and Accelerators for ML/DL and New Compute`
3. `Processors and SoCs`
4. `Advanced Packaging, Chiplet and Heterogeneous Integration`
5. `Wireline and Optical Transceivers, Optical Interconnects and Processors`
6. `DTCO and Design Enablement`

这说明 `VLSI 2026` 的 gate 并不窄，它允许我们把论文做成：

- `CIM macro`
- `new compute accelerator`
- `processor/SoC`
- `chiplet/system-scale compute`

中的任何一种，只要内容真的匹配。

## 5. 2026 的会场趋势，和前几年已经不一样了

如果只看 `2023/2024/2025`，容易得到一个结论：

- “热门就是 AI accelerator 和 CIM”

但看 `2026` 官方信息，趋势其实更具体了，不只是“AI 很热”这么简单。

## 5.1 趋势一：AI 话题在 2026 已经上升到“系统级基础设施”

`VLSI 2026` 的总主题就是：

- `Advancing the AI Frontier through VLSI Innovation`

而官方 plenary 的标题直接把重点写成：

- `Building the Engine of AI: From Foundational VLSI Technologies to System-Scale Impact`
- `Advanced Package for Next-Generation AI System Scaling`
- `Intelligence Accelerated: Memory Innovations to Power the AI Era`

`ISSCC 2026` 的 forum 也有：

- `Powering the Future of AI, HPC, and Chiplet Architectures: From Dies to Package and Rack`

这说明 `2026` 顶会讲 AI，已经不再只是：

- “又一个更快的矩阵乘 accelerator”

而是在强调：

- memory
- chiplet
- package
- interconnect
- power delivery
- datacenter-scale system constraints

这对我们是个提醒：

- 如果我们只是讲一个小 kernel，会显得小
- 如果我们能把 paired-operator primitive 和 memory movement / dual-pass overhead / chiplet-local projection 联系起来，故事会更像 2026 的主流语言

## 5.2 趋势二：非传统计算是允许的，但必须看起来“有主赛道意义”

`ISSCC 2026` 里不仅有 AI，还出现了：

- `SAT` accelerator
- `Ising` chip
- photonic routing/interposer
- neuromorphic processor

这说明：

- 顶会不是只收 `CNN/LLM`
- 但非传统工作必须能被讲成：
  - 新计算原语
  - 新电路机制
  - 或新系统约束下的合理解

所以我们的工作可以不装成 `LLM chip`。  
但必须让评审看见：

- 这不是冷门应用特化
- 而是一个对 `dual-operator / bilinear / metric-aware` 计算普遍有意义的硬件原语

## 5.3 趋势三：processor session 本身已经吸收了大量 accelerator/SoC 内容

`ISSCC 2026 Session 2: Processors` 里已经不是纯 CPU 天下了。  
它收了：

- GPU
- quad-chiplet AI SoC
- end-to-end driving processor
- diffusion processor
- inference accelerator

这意味着：

- `processor` 和 `accelerator` 的边界正在变模糊
- 关键不是你自称什么
- 而是你的工作是否具备：
  - control plane
  - memory hierarchy
  - software/runtime story
  - task orchestration

因此，如果我们未来真想投 processor/SoC 赛道，方向不是改标题，而是补系统层实体。

## 5.4 趋势四：JSSC 对 processor/accelerator 依然欢迎，但更讨厌“只有架构没有电路”

`JSSC` 本身没有 conference-style session。  
但从其官方 `2025 年 10 月发布、2026 年仍在沿用` 的数字电路投稿标准来看，它对数字系统论文的态度非常明确：

- 接受 processor / accelerator / digital system
- 但不接受“只有算法和高层架构”
- 必须有：
  - low-level microarchitecture or gate-level detail
  - VLSI implementation detail
  - clock / voltage / floorplan / macro placement 等实现信息
  - 难以由 pre-silicon 推断的 silicon measurement

这意味着：

- `JSSC` 当然可以是后续目标
- 但它不会因为我们是 processor/accelerator 就自动放宽要求

## 6. 我们这个方向分别怎么挂这些赛道

## 6.1 如果挂 `CIM` 赛道

最像：

- `ISSCC Session 30`
- `VLSI: Computing/Processing in Memory`

这时论文主语应该是：

- `dual-operator projection CIM macro`

重点放在：

- paired residency of `(H,S)`
- shared input encoding
- shared sensing / reconstruction / local accumulation
- dual-pass overhead reduction

这条线要求最像：

- `macro paper`

## 6.2 如果挂 `Domain-Specific Accelerator`

最像：

- `ISSCC Session 18`
- `VLSI: Devices and Accelerators for ML/DL and New Compute`

这时论文主语应该是：

- `generalized-eigen / non-orthogonal subspace accelerator`

重点放在：

- workload-native primitive
- end-to-end block dataflow
- controller / local solver / paired operators
- `QE / PySCF` 和 synthetic paired-op benchmark

这条线是当前最容易和我们现有工作闭环的。

## 6.3 如果挂 `Processor / SoC`

最像：

- `ISSCC Session 2`
- `VLSI: Processors and SoCs`

但这条线对我们当前版本要求明显更高。  
仅有一个强 macro 不够，还需要至少补到：

1. 明确的 programming model
2. instruction / command interface
3. task scheduling / sequencing
4. memory hierarchy
5. host interaction model
6. 更像系统芯片的 benchmark

换句话说，如果要投 processor，不是改标题，而是要把它做成：

- `subspace processing engine`
- 或 `scientific domain processor`

## 6.4 如果挂 `Digital Processing and Circuit Techniques`

最像：

- `ISSCC Session 10`

这时需要把主角收缩成某个更明确的数字电路创新，比如：

- projection-aware reduction fabric
- shared dual-operator sensing datapath
- low-overhead block-projection scheduler

这条线适合“一个非常尖的数字处理技巧”，但不适合塞太多系统愿景。

## 7. 当前最现实的判断

截至 **2026 年 3 月 14 日**，如果只看我们当前手里的工作形态，我会把优先级重排成：

1. `VLSI / ISSCC 的 DSA 线`
2. `VLSI / ISSCC 的 CIM 线`
3. `ISSCC 的 Digital Processing` 线
4. `Processor / SoC` 线

原因不是 processor 不高级，而是：

- 我们现在已经有 workload、primitive 和数据流雏形
- 但还没有真正 processor/SoC 需要的系统层实体

也就是说：

- **processor 赛道是可以争取的升级方向**
- **不是当前版本最自然的落点**

## 8. 对我们接下来的策略建议

如果你希望保留往 `processor / accelerator / DSA / CIM` 多条线切换的余地，最合理的策略不是现在定死会场，而是把工作组织成三层：

1. `Primitive 层`
   - `dual-operator projection primitive`

2. `Engine 层`
   - `paired-operator subspace engine`

3. `System 层`
   - `subspace processor / scientific accelerator`

这样做的好处是：

- 往 `CIM` 投：强调 `Primitive + Macro`
- 往 `DSA` 投：强调 `Primitive + Engine`
- 往 `Processor` 投：强调 `Engine + System`

这比一开始把自己锁死在“CIM 论文”里灵活得多。

## 9. 最后一句判断

所以这次结论应该修正成：

- 我们当然可以瞄准 `processor / accelerator / domain-specific accelerator` 这些更大的 session
- `2026` 年官方 session 也确实给了这些入口
- 但**不同赛道不是换标题，而是换论文主语和所需硬件成熟度**

对当前版本而言，最强落点还是：

- `domain-specific accelerator`
- 或 `paired-operator CIM`

如果你希望冲得更大，下一步不是继续争论“像不像 processor”，而是直接把：

- control plane
- memory hierarchy
- programmability
- host/runtime interface

这些 processor/SoC 必需件补出来。

## 10. 参考来源

### ISSCC 2026 官方

- ISSCC 2026 Advance Program  
  `https://submissions.mirasmart.com/ISSCC2026/PDF/ISSCC2026AdvanceProgram.pdf`

### VLSI 2026 官方

- VLSI 2026 Home  
  `https://www.vlsisymposium.org/`
- VLSI 2026 CFP Overview  
  `https://www.vlsisymposium.org/overview-cfp/`
- VLSI 2026 Schedule-at-a-Glance  
  `https://www.vlsisymposium.org/schedule-at-a-glance/`
- VLSI 2026 Plenary Sessions  
  `https://www.vlsisymposium.org/plenary-sessions/`
- VLSI 2026 Short Courses  
  `https://www.vlsisymposium.org/short-courses/`
- VLSI 2026 Evening Panel  
  `https://www.vlsisymposium.org/evening-panel/`

### JSSC 官方

- IEEE JSSC Aims and Scope  
  `https://sscs.ieee.org/publications/ieee-journal-of-solid-state-circuits-jssc/`
- Criteria for Good JSSC Submissions on Digital Circuits and Systems  
  `https://sscs.ieee.org/wp-content/uploads/Criteria-for-Good-JSSC-Submissions-on-Digital-Circuits-and-Systems.pdf`
