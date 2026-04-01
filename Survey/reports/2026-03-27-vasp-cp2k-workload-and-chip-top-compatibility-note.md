# 2026-03-27 VASP / CP2K 负载与计算流程分析，以及对 chip 顶层兼容性的含义

## 1. 这份笔记要回答什么

导师提出的新约束很重要：系统未来不应只服务 `QE`，还需要尽量保留向 `VASP`，甚至 `CP2K` 兼容的可能性。这个约束会直接影响 chip 顶层组织方式。

如果目标只盯住当前 `QE c_bands` 主链，那么把系统写成一条很深、很固定的 episode pipeline 是自然的；但如果希望后续还能兼容 `VASP` 与 `CP2K`，那么 chip 顶层大概率不能是一条只为单一路径冻结的“完整流水线”，而更像：

- 一组固定功能引擎；
- 上面有一个较薄但明确的调度/命令层；
- 必要时再配一个较轻量的 `SIMD / vector / programmable` companion，去承接不同软件之间不完全一致的局部控制、批处理和轻算术逻辑。

所以这份笔记分两步：

1. 先看 `VASP` 和 `CP2K` 的主负载、SCF/solver 流程和主要算子组织；
2. 再判断哪些 chip 顶层调度方式更适合同时兼容 `QE / VASP / CP2K`。

## 2. VASP：主负载与计算流程的含义

### 2.1 VASP 的系统对象更接近我们当前 `QE` 路线

从方法上看，`VASP` 与当前 `QE` 路线最接近：

- 都是以 `plane-wave` 为主的 Kohn-Sham DFT 主流实现；
- 都依赖 `FFT` 在实空间 / 倒空间之间来回切换；
- 都需要反复应用 Hamiltonian、处理非局域 projector / augmentation 相关项；
- 都有显著的 band-wise / k-point-wise 并行结构；
- 都在 SCF 中重复进行“波函数更新 -> 子空间/本征问题处理 -> 密度更新”的闭环。

因此，如果只是问“哪个软件和当前 `QE-connected band-solver subsystem` 最接近”，答案通常先是 `VASP`，而不是 `CP2K`。

### 2.2 VASP 的 SCF / electronic minimization 主线

官方 `VASP Wiki` 给出的 self-consistency cycle 说明了其内层电子自洽迭代是围绕电子密度、势、Kohn-Sham 轨道更新展开的。`ALGO` 页面进一步说明，`VASP` 的电子优化路径常见包括：

- `IALGO=38` / `Blocked-Davidson`；
- `IALGO=48` / `RMM-DIIS`；
- 以及更稳健或更保守的 Davidson / all-band / exact 等变体。

这对架构含义很直接：

- `VASP` 不是单一固定 solver；
- 即便同一软件内，也存在多种电子最小化/特征求解主路径；
- 因而如果 chip 顶层过于死板，只适配单一子路径，后续兼容代价会偏高。

### 2.3 VASP 的关键负载形态

对硬件更关键的是它的“算子形状”：

1. **FFT 很重要**
   - plane-wave 表示天然要求频繁做 reciprocal/real-space 变换；
   - 这和我们当前保留 `explicit FFT Companion` 的做法是一致的。

2. **非局域 projector / PAW 相关路径重要**
   - 这与我们当前强调 `Adjoint-Aware Projector Primitive` 并不冲突，反而说明 projector 类路径不只是 `QE` 特例。

3. **band 批处理很重要**
   - `VASP` 文档中的 `NSIM` 明确表示多个 bands 可以被同时优化；
   - 这说明“跨 band 的批处理 / strip-mining / vector-like 发射”是软件层已有的自然结构。

4. **dense linear algebra 依然存在**
   - 子空间更新、正交化、Rayleigh-Ritz 或近似本征处理仍需要大量 BLAS/LAPACK/ScaLAPACK 类支撑。

因此，如果只从 `VASP` 看，顶层硬件既不能只有 `FFT`，也不能只有一个孤立的 eigensolver；更合理的是能把：

- `FFT`
- projector/apply
- reduced-space dense kernels
- band 批处理控制

放在同一个调度框架里。

### 2.4 VASP 对 chip 顶层的含义

对我们最重要的不是“VASP 和 QE 一模一样”，而是：

> `VASP` 支持继续保留一个以 `FFT + projector/apply + reduced-space solve` 为核心的对象，但它提醒我们：顶层不应是一条写死的全流程流水，而要支持 solver path 切换与 batched-band 调度。

换句话说，兼容 `VASP` 不一定要求完全推翻当前 `QE` 主线；但它确实要求：

- 顶层要更像 `commanded subsystem`；
- 而不是一条“只能执行单一 `QE c_bands episode` 形态”的 rigid pipeline。

## 3. CP2K：主负载与计算流程的含义

### 3.1 CP2K 与 `QE/VASP` 的根本差异

`CP2K` 尤其是 `Quickstep` 路线，方法学中心不是标准 `plane-wave KS solver`，而是 `Gaussian and Plane Waves (GPW)` / `GAPW` 一类混合表示。

这意味着：

- 它仍然会用到网格与 `FFT`；
- 但它不只是 plane-wave band solver；
- 它更强地依赖 Gaussian basis、积分、矩阵块运算，以及不同稀疏度 / 不同表示之间的数据搬运与变换。

因此，`CP2K` 对我们是一个非常重要的“压力测试对象”：

- 如果一个 chip 顶层只适合 plane-wave band solver，它可能能兼容 `QE/VASP`，但未必能自然兼容 `CP2K`；
- 如果一个 chip 顶层能兼容 `CP2K` 的主负载，那么它往往必须具备更强的命令驱动与多引擎编排能力。

### 3.2 CP2K Quickstep 的计算主线

官方 `CP2K` 文档中，`GPW` 页面明确强调：

- Kohn-Sham orbitals 用 Gaussian basis 展开；
- Hartree potential 在 plane-wave/FFT 栅格上求解；
- 因而其核心数据流天然是“Gaussian basis world”与“grid / FFT world”之间来回耦合。

这和 `QE/VASP` 最大不同在于：

- `QE/VASP` 更像在 plane-wave / projector / FFT / reduced eigensolver 之间反复闭环；
- `CP2K` 则更像在 Gaussian basis、矩阵块、栅格/FFT、稀疏/块稠密操作之间交替推进。

### 3.3 CP2K 的 SCF / 求解器路径

`CP2K` 官方输入参考说明，在 `SCF` 中可以选择：

- `DIAGONALIZATION` 路线；
- `OT`（Orbital Transformation）路线。

这件事对架构影响极大。因为它说明：

- 即便在同一个 `CP2K` 里，“求解 Kohn-Sham 轨道”的主路径也未必是经典的显式对角化；
- 某些情况下，`OT` 这种直接最小化/轨道变换路线比反复显式子空间对角化更重要；
- 因而如果芯片顶层只为“reduced eigensolver”做非常深的硬编码，面对 `CP2K` 时适配空间会明显变窄。

### 3.4 CP2K 的关键负载形态

从官方文档与 `DBCSR` 项目页面看，`CP2K` 一个极关键的性能基础设施是 `DBCSR`：

- 它面向分布式块压缩稀疏矩阵乘；
- 支持 CPU 与 accelerator；
- 是 `CP2K` 这类代码的重要高性能底座之一。

这带来两个和 `QE/VASP` 明显不同的点：

1. **稀疏/块稀疏矩阵路径更重要**
   - 这与纯 plane-wave dense-kernel 中心的对象不同；
   - 顶层必须能描述不同数据稀疏度与不同引擎选择。

2. **显式命令驱动比深流水更重要**
   - 因为 `CP2K` 的主要算子族更杂：grid/FFT、积分、稀疏块乘、正交化、OT/DIAG 分支；
   - 所以更像“任务编排 + 专用内核”的系统，而不是一条高度单路化的管线。

### 3.5 CP2K 对 chip 顶层的含义

如果以后真要兼容 `CP2K`，那我们应该提前接受一个现实：

> 顶层设计不能只是一条围绕 `QE c_bands` 写死的深流水，它必须是一种能在多类 kernel / 多类数据表示 / 多类求解路径之间切换的命令式架构。

这不一定意味着必须做通用 CPU；但很可能意味着：

- 有一层 `kernel descriptor / command ISA`；
- 有一层负责 band/basis/tile/block 维度批处理的调度器；
- 有少量可编程 `SIMD / vector` 伴随引擎，去处理不同应用之间变化较大的轻控制与中等粒度算术路径。

## 4. `QE / VASP / CP2K` 三者对我们真正共同提出了什么要求

如果把三者放在一起看，能看到两类结论。

### 4.1 共同点

三者都不是“单一 GEMM 软件”。它们都需要某种组合：

- `FFT / grid transform`
- operator apply / projector-like 路径
- dense reduced-space 或局部线代
- batched state update
- SCF 内环反复调用

这说明我们当前坚持“不能只讲孤立 GEMM”是对的。

### 4.2 差异点

但三者也并不共享一条完全相同的内层路径：

- `QE`：当前最清楚的是 `c_bands` 及其 band-solver episode；
- `VASP`：与 `QE` 相近，但 solver path、band batching 和 PAW/projector 组织会有差别；
- `CP2K`：表示法与 kernel mix 差异最大，尤其是 `Gaussian + grid + sparse/dense block + OT/DIAG` 的组合。

这说明如果顶层写成“一条完整固定 episode pipeline”，它的可迁移性会偏低。

## 5. 搜索后更可行的 chip 顶层思路

基于上面三类软件的负载结构，以及已经存在的相关架构经验，当前更可行的方向不是“完整固定流水”，而是下面几种。

### 5.1 最推荐：`command processor + fixed engines + lightweight vector/SIMD companion`

这是我目前最推荐的方向。

它的基本形态是：

- 下层保留固定功能引擎：
  - `CIM/projector apply engine`
  - `FFT companion`
  - `reduction / closure / reduced solve engine`
  - 未来可扩的 sparse/block engine
- 顶层增加一个 **command processor**：
  - 接受 `kernel descriptor` / `episode descriptor` / `task packet`
  - 负责选择引擎、安排数据驻留、控制 join/sync
- 再配一个轻量 **vector/SIMD companion**：
  - 处理 band-wise / basis-wise 的 batched loops
  - 处理轻量更新、mask、归约前后整理、格式转换
  - 弥补不同软件之间在局部调度上的不一致

为什么这个方向最合适：

- 它保留了当前 `QE` 主线中最重要的固定功能资产；
- 又不会把顶层锁死成只适用于 `QE c_bands`；
- 对 `VASP` 的兼容主要通过 descriptor + batched-band 调度解决；
- 对 `CP2K` 的兼容则依赖 descriptor 层和未来可扩 kernel family，而不是要求所有路径都走同一条硬流水。

### 5.2 值得认真考虑：`vector/SIMD-fronted domain-specific accelerator`

如果想更进一步兼容 `VASP/CP2K`，一个可以认真考虑的方向是：

- 用一层较窄但明确的 vector/SIMD front-end 管 band/basis/tile/block 维度；
- 把 `FFT`、projector、dense/sparse microkernels 作为后端功能单元；
- 用类似 strip-mined 向量任务的方式发射。

这个方向的依据之一，是 `VASP` 官方 `NSIM` 体现出的跨-band 批处理天然性；另一类依据是现代 vector 架构本来就擅长“长度可变、批处理、规则循环主体 + 少量不规则边界”的数值代码。

但它的问题是：

- 如果 vector front-end 做得太重，会把项目推向另一类更通用的处理器设计；
- 对当前以 `CIM Array Core` 为中心的叙事，会形成一定稀释。

因此它适合做 **top-level companion**，不太适合作为完全替代当前对象的唯一中心。

### 5.3 可以参考但不应立刻重押：`CGRA / full programmable array`

从兼容性角度，`CGRA` 或更强的可重构阵列当然有吸引力，因为它能在不同软件/不同 kernel 间重映射。

但以我们当前阶段看，它的问题也很明显：

- 设计和编程模型复杂度太高；
- 容易稀释当前已经逐渐清晰的 `projector primitive + QE-connected subsystem` 主线；
- 短期内反而可能降低问题定义清晰度。

所以现阶段我不建议把“为了兼容 `CP2K`”直接转成“做一个更通用的 CGRA 风格顶层”。

### 5.4 有明确先例支持的组合式思路

搜索中最值得注意的一个支持点，是 `Liu et al. 2023` 这类异构 PIM/accelerator 方案的共同思路：

- 不是只靠 fixed-function；
- 也不是全交给 fully programmable core；
- 而是 **fixed-function engines + programmable companion + runtime scheduling** 的组合。

这和我们现在面对 `QE / VASP / CP2K` 三者兼容性时需要的东西很吻合。

## 6. 对我们当前架构最直接的改写建议

基于这轮分析，我认为当前架构不该直接改写成“完整一套固定流水”，而应该朝下面这个方向改口：

### 6.1 真实系统对象

仍然保留：

- `Host software`
- `FPGA/runtime`
- `Chip`

这一层没有必要推翻。

### 6.2 chip-local 对象

chip 内建议从“固定 `QE episode pipeline`”改成：

- `Domain-Specific Execution Cluster`
  - `CIM Array Core`
  - `FFT Companion`
  - `Reduction / Closure / Solve engines`
  - future `sparse/block engine` hook
- `Near-SRAM Support Domain`
- `Command / Descriptor Scheduler`
- lightweight `SIMD / Vector Companion`

### 6.3 执行合同

对外不再只暴露一个很强的 `QE c_bands episode` 专用合同，而是分两层：

1. **软件级 episode contract**
   - 仍可以对 `QE` 暴露 `c_bands episode`；
   - 对 `VASP/CP2K` 后续可以暴露不同 episode/subgraph。

2. **chip 级 kernel-descriptor contract**
   - `FFT`
   - `project/apply/backproject`
   - `reduced build`
   - `closure/update`
   - `sparse/block op`
   - `vector post/pre processing`

这样当前 `QE` 版本仍然可落地，但不会把未来兼容性锁死。

## 7. 当前最合理的判断

如果只给一句结论，我会这样收口：

> 在导师提出“未来要兼容 `VASP` 乃至 `CP2K`”之后，我们更不应该把 chip 顶层写成一条完整固定流水；更合理的方向是保留当前 `CIM-centered` 主体，同时在 chip 顶层加入 `descriptor-driven scheduling`，并配置一个轻量 `SIMD/vector` companion，使系统从“单一路径流水”转向“多引擎、命令驱动、可批处理”的 domain-specific accelerator。

## 8. 我建议的下一步

在真正搜索更细的架构候选之前，我建议下一步继续做两件非常具体的事：

1. **做一份 `QE / VASP / CP2K` 三列对照表**
   - basis / representation
   - SCF inner loop
   - solver path
   - FFT role
   - projector / nonlocal role
   - dense vs sparse importance
   - top-level contract implication

2. **写一个 chip 顶层 `descriptor ISA v0` 草案**
   - 先不要写完整指令集；
   - 只定义 8~12 类 kernel descriptor；
   - 看看能不能同时覆盖当前 `QE` 主线与未来 `VASP/CP2K` 的主要差异。

如果这两步能写顺，后面再去挑到底是偏 `SIMD`、偏 microcode，还是偏 command-queue，会更稳。

## 参考来源

- VASP Wiki, Self-consistency cycle: https://www.vasp.at/wiki/index.php/Self-consistency_cycle
- VASP Wiki, ALGO: https://www.vasp.at/wiki/ALGO
- VASP Wiki, OpenACC GPU port of VASP: https://www.vasp.at/wiki/index.php/OpenACC_GPU_port_of_VASP
- CP2K, GPW method overview: https://www.cp2k.org/gpw
- CP2K input reference, SCF / OT: https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/SCF/OT.html
- CP2K input reference, SCF / DIAGONALIZATION: https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/SCF/DIAGONALIZATION.html
- CP2K / DBCSR project page: https://www.cp2k.org/dbcsr
- Ara vector unit documentation: https://pulp-platform.github.io/ara/introduction.html
- Liu et al. 2023 structured read in this repo: `Survey/reports/2026-03-27-liu-2023-heterogeneous-pim-structured-read.md`
