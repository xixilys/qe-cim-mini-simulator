# 软硬件协同加速的一般套路，以及对当前 `QE SCF shell` 项目的启发（2026-04-02）

## 0. 这份笔记回答什么

这份笔记不回答“我们最后的 `FPGA / chip` 一定长什么样”，而是回答一个更基础的问题：

- 一般来说，软硬件协同加速项目是怎么推进的；
- 软件和硬件各自通常要做哪些定制化修改；
- 系统级建模通常怎么分层、怎么和原型验证配合；
- 对当前 `QE SCF shell` 项目，最应该借鉴哪一套方法，而不是只借表面术语。

这份笔记综合了三类本地证据：

- 本仓库已有的系统级建模参考与 `QE` 工作负载文档；
- 当前 `SystemC` / `Host-FPGA-Chip` 事务语义文档；
- 本地可检索到的一些 `FPGA` / dataflow / systolic 方向材料。

## 1. 一般的软硬件协同加速，通常不是“把代码搬到硬件”

真正成熟的软硬件协同加速，通常都不是把一段软件直接翻译成 `RTL` 或 `HLS` 内核，而是把原始软件路径拆成三层对象：

1. **软件侧保留层**
   - 复杂控制流；
   - 稀疏或不规则路径；
   - 异常处理与回退路径；
   - 系统集成、调度、API 与运行时管理。

2. **加速器主数据流层**
   - 长时间重复；
   - 输入输出对象清楚；
   - 有明显数据复用；
   - 适合分块、流水、阵列或 streaming 的主路径。

3. **系统边界协调层**
   - CPU / host 和 accelerator 的命令/完成语义；
   - 大对象如何进出、哪些对象驻留、哪些对象版本化；
   - 什么时候同步、什么时候异步；
   - 性能瓶颈究竟在算力还是在搬运。

所以一个项目如果真的要落地，第一件事往往不是“选阵列”，而是先回答：

- 哪些对象必须留在软件；
- 哪些对象必须在硬件侧长期驻留；
- 哪些对象只是流经硬件；
- 哪些步骤值得在硬件局部闭环；
- 哪些步骤只应该做 companion/fallback。

## 2. 一般项目里，软件侧通常要改什么

软硬件协同加速几乎总是要求软件侧做定制化修改，常见有下面几类。

### 2.1 调用边界会被重写

原始软件调用往往会被改造成：

- panel / tile / block 粒度调用；
- episode / task / bundle 粒度调用；
- 异步下发 + 完成通知；
- handle/object id 语义，而不是直接传完整大数组。

这类修改的目的，是让软件不再把 accelerator 当成一个“同步函数库”，而是当成一个有局部状态、可驻留对象、可重放任务的执行域。

### 2.2 数据布局会被重写

常见改动包括：

- AoS/SoA 改写；
- dense/sparse/compressed format 重排；
- 面向 burst 的对齐和 padding；
- 把原来的 loop order 改成 tile-friendly order；
- 把“每次都重新装载”的对象变成 resident object。

### 2.3 算法会做“硬件友好型重构”

常见思路包括：

- fusion / split；
- precompute / cache；
- 把难以硬件化的步骤先留在 host 或 companion；
- 把大问题改成重复的 block / panel 子问题；
- 用近似、低精度、裁剪、压缩等方式换带宽/缓存压力。

这也是为什么很多系统最后看起来不像“原软件一比一硬化”，而更像“软件和硬件共同定义了一套新的执行合同”。

## 3. 一般项目里，硬件侧通常怎么干

### 3.1 最常见的不是单一大流水线，而是分层 dataflow

在真实系统里，最稳健的顶层做法通常不是：

- 一根覆盖全部阶段的超长流水线；
- 或者一个试图吃掉所有类型算子的统一阵列。

更常见的是：

- 一个 **persistent controller / scheduler**；
- 若干个 **specialized engines**；
- engine 之间用 **FIFO / queue / double buffer** 解耦；
- 规则算子内部使用 **deep pipeline**；
- 局部 dense kernel 使用 **PE array / systolic-like structure**；
- 不规则部分留给 software / companion / runtime。

这是因为实际 workload 很少全都同构：

- 有的阶段 compute-heavy；
- 有的阶段 bandwidth-heavy；
- 有的阶段有 data expansion/compression；
- 有的阶段天然适合阵列；
- 有的阶段更像控制或 closure。

### 3.2 顶层设计的核心不是 PE，而是 memory hierarchy

在很多加速器里，真正决定成败的通常不是 ALU 数量，而是：

- 片上缓存放什么；
- 哪些对象驻留；
- 哪些对象必须 streaming；
- 双缓冲怎么做；
- off-chip memory 的 burst / bank / port 怎么喂饱；
- 各 stage 之间会不会互相阻塞。

因此，一般的硬件设计流程往往先冻结：

- working set；
- resident object；
- stage buffer；
- traffic budget；
- overlap/latency hiding 策略；

然后才去细化 PE 微结构。

### 3.3 阵列化通常是“局部策略”，不是顶层信仰

`systolic array`、`pulse array`、`SIMD lane`、`streaming pipeline` 都更像局部 kernel 的实现方法，而不是整个系统唯一正确的组织方式。

通常只有当 workload 已经高度稳定，而且主路径极其统一时，才会走向像 `TPU` 那样的“冻结 workload + 大片上存储 + 强阵列中心”的路线。

对大多数早期项目，尤其是要先走 `FPGA` 验证的项目，顶层更常见的是：

- dataflow + reusable engines；
- 局部阵列化；
- runtime-managed buffering；
- host/accelerator 的清晰分工。

## 4. 一般项目怎么做系统级建模

本地参考文档已经把系统级建模收口成一个很稳的六层方法，这个方法本身就很符合软硬件协同加速的一般套路。

### 4.1 先做 `L0`：工作负载与对象建模

先冻结：

- 阶段划分；
- 输入输出对象；
- shape / dtype / layout；
- 调用频次；
- Host / FPGA / Chip 边界流量；
- resident object。

这一步对应很多协同加速项目里的“profile + cut + object contract”。

### 4.2 再做 `L1`：上界与粗筛

常见方法是：

- arithmetic intensity；
- compute lower bound；
- bandwidth lower bound；
- 判断是 compute-bound 还是 memory-bound。

这一层的作用不是给最终结果，而是快速排除明显不合理的方案。

### 4.3 再做 `L2/L3`：体系结构时间模型 + 系统交互模型

真正和软硬件协同最相关的是：

- tile / panel / array 并行度；
- buffer 容量与双缓冲；
- stage 间 stall/occupancy；
- host-device 交互开销；
- runtime 调度和同步点。

这个层次通常能回答：

- 为什么某个“局部 kernel 很快”的方案，系统上并不快；
- 为什么某个“算力不最强”的方案，端到端反而更优。

### 4.4 最后才做 `L4/L5`：能耗/面积估计与少量校准

系统对象和接口没有冻结之前，不应过早谈：

- 最终频率；
- 最终面积；
- 最终功耗；
- 最终 QoS。

成熟做法通常是：

- 先让 `SystemC / analytical / FPGA prototype` 收敛系统边界；
- 再用 `Accelergy / McPAT / CACTI` 一类做 architecture-level estimate；
- 最后用少量 `RTL / FPGA / implementation` 数据做校准。

## 5. 把这套一般套路映射到当前 `QE SCF shell`

对当前项目，最重要的启发有五条。

### 5.1 先冻结对象与边界，不先冻结最终芯片

当前最值得冻结的不是最终 `chip` 微结构，而是：

- `SCF shell` 的阶段划分；
- `Host / FPGA / Chip` 分工；
- resident object；
- 边界流量；
- 每个 body 的输入输出、调用频次与重叠关系。

这和一般软硬件协同项目的最佳实践一致。

### 5.2 当前项目的软件定制点其实已经很清楚

对 `QE` 来说，最现实的软件定制通常是：

- 把原始 band-solver 路径整理成 episode / bundle；
- 用 object handle 或 panel handle 表示大对象；
- 把 `Host`、`FPGA runtime`、`chip local loop` 的责任分开；
- 允许 fallback / companion solver 存在，而不是追求首版全硬化。

这和当前仓库里的 `EpisodeRequest / EpisodeResponse / OperatorTxn / ReductionTxn / ClosureTxn` 语义，是同一条主线。

### 5.3 当前项目的硬件主路径也已经浮现出来

结合本地工作负载文档，可以看到：

- `h_psi` 有明显 data expansion/compression；
- `s_psi` 是 projector-dense hot path；
- `build H_sub/S_sub` 输入是 full-space blocks，输出是小矩阵；
- `cdiaghg` 小而规整，但对首版系统价值未必是第一优先级；
- `refresh/residual -> P_next` 又回到 full-space loop。

这意味着当前项目最适合的顶层方式，确实更像：

- `FPGA-resident loop controller`
- `FFT companion`
- `projector apply/backproject engine`
- `reduced-build engine`
- `refresh/residual/update engine`
- `CPU / soft-core companion cdiaghg`

而不是一根端到端大流水线。

### 5.4 当前项目最该看的性能指标，不只是 FLOPs

一般软硬件协同项目的评价重点往往是：

- stage stall ratio；
- host-device traffic；
- off-chip-memory traffic；
- resident hit / spill；
- pipeline occupancy；
- buffer pressure；
- 实际 wall-time，而不是单 kernel 峰值吞吐。

对当前项目尤其如此，因为 `h_psi` / `refresh` 这类路径里，大对象反复进入循环，communication/computation balance 比单点峰值算力更关键。

### 5.5 `FPGA-first` 是符合一般规律的

一般软硬件协同项目也通常遵循：

- 先 `FPGA` 或 emulator 验证分工、吞吐、边界流量；
- 再在系统对象稳定后讨论 `ASIC / DSA / chip`；
- 最后才谈更激进的定制（例如更强阵列、更深近存、更复杂 memory system）。

所以对当前项目，“先不管 chip，先把 `FPGA-first` 的系统分工和局部闭环做实”，并不是退一步，而是更符合一般方法论。

## 6. 一个可以直接复用的通用 playbook

如果把一般的软硬件协同加速流程压成一条可以直接执行的 checklist，我建议写成下面这样：

1. **Profile workload**
   - 找真正热、真正重复、真正规则的路径；
   - 不只看 FLOPs，也看 bytes 和 working set。

2. **Freeze system object**
   - 明确 `Host / runtime / accelerator` 分工；
   - 明确 object contract 和 resident object。

3. **Reshape software interface**
   - 把软件调用改成 panel / task / episode / handle 语义；
   - 保留 fallback 与异常路径。

4. **Choose accelerator style**
   - 顶层优先考虑 hierarchical dataflow；
   - 深流水只放进稳定 kernel；
   - 阵列化只放进真正 dense 的局部主核。

5. **Design memory hierarchy first**
   - 先定什么驻留、什么 streaming、什么双缓冲；
   - 再定 PE 数量和具体 datapath。

6. **Model before hardening**
   - `L0/L1/L2/L3` 先跑通；
   - 先把 bottleneck 说清，再讨论 `L4/L5`。

7. **Validate with FPGA**
   - 验证 wall-time、traffic、stall、spill；
   - 验证 software-visible loop 是否闭环。

8. **Harden only after convergence**
   - 当 workload、接口、working set、runtime 行为都稳定后，再进入 chip/ASIC 路线。

## 7. 对当前项目的直接建议

如果把上面的结论只压成一句话：

> 对当前 `QE SCF shell` 项目，最合理的软硬件协同路线是：**先把软件路径改造成 episode/object-handle 友好的系统接口，再在 FPGA 上实现一个以 dataflow 为顶层、以局部复用为中心、以 memory hierarchy 为先的 band-solver accelerator；不要一开始就追求单一超深流水线或全系统单体阵列化。**

进一步说：

- **软件上**：改接口、改对象、改调度，不急着把所有路径都变硬件；
- **硬件上**：先做 `FPGA` 版 `persistent controller + reusable engines + resident buffers`；
- **建模上**：先做对象/流量/时间模型，再做面积功耗估计；
- **系统上**：真正要优化的是循环中的复用、流量和阻塞，而不是单一 kernel 的理论峰值。

## 8. 这份笔记之后最自然的下一步

基于这份 playbook，后续最值得立即产出的不是更细的 `PE` 结构，而是下面三份表：

1. `Host / FPGA / memory` 分工表；
2. resident-object / stream-object / spill-object 表；
3. per-stage cache/buffer budget 与 traffic budget 表。

只有这三份表先出来，后面谈 `FPGA` 顶层、性能指标、甚至 `chip` 路线，才不会漂。
