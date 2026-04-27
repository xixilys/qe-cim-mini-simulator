# 芯片系统级建模与性能评估方法参考（2026-04-02）

## 0. 摘要

这份文档的目的不是给出某一个固定架构的最终性能结论，而是把后续系统级建模常用的**方法层次、可计算对象、常用工具、适用边界和推荐工作流**统一收口成一份参考件，供本项目后续做 `QE / DFT` 混合加速系统建模时直接复用。

先给结论：

- 系统级建模最常见的问题，不是“不会算”，而是把**不同层次的模型混在一起算**。
- 一个成熟的建模流程，通常不是一步得到“精确吞吐 + 精确功耗 + 精确频率”，而是分成：
  1. workload / object accounting；
  2. analytical upper/lower bound；
  3. cycle-approximate architecture model；
  4. full-system interaction model；
  5. energy / area / thermal estimation；
  6. 少量 RTL / FPGA / implementation 校准。
- 对当前项目，最值得优先冻结的不是具体 `PE` 微结构，而是：
  - `SCF iteration shell` 的阶段划分；
  - `Host / FPGA / Chip` 三层分工；
  - resident object；
  - 每个 body 的输入输出、流量、调用频次和重叠关系。
- 在系统对象和对象流转没有冻结之前，不应强行给出“最终频率”“最终面积”“精确功耗”“最终 QoS”这类结论。

本文把后续常用建模方法归纳成一个统一口径：

> 先做 **可验证的工作负载与边界建模**，再做 **体系结构级时间模型**，最后再做 **能耗/面积与实现校准**。

## 1. 文档定位

### 1.1 作用

本文是本仓库后续做系统级 exploration 时的**建模方法参考件**。

它回答的不是“最终系统长什么样”，而是下面这些更基础的问题：

- 系统级建模一般分几层；
- 每一层通常算什么，不算什么；
- 常用的 analytical / simulator / estimator 工具各自适合什么问题；
- 对当前 `QE / DFT` 项目，应该按什么顺序建模，才能避免一开始就掉进“什么都想精确算”的陷阱；
- 哪些量现在就可以算，哪些量应该明确延后。

### 1.2 与主系统规范的关系

本文不替代 `docs/architecture/system_design_master_spec_v0.md`。

两者关系如下：

- `system_design_master_spec_v0.md` 回答“系统对象、分层、模块责任、对象语义是什么”；
- 本文回答“这些对象和边界在后续研究里**应该用什么方法建模**”。

因此，本文是方法参考，不是冻结规范。

### 1.3 当前适用范围

本文优先面向以下任务：

- `QE` 主线 `SCF iteration shell` 的系统级建模；
- `Host / FPGA / Chip` 分工分析；
- `h_psi / s_psi / build H_sub / S_sub / cdiaghg / refresh` 这类阶段的时间、流量、驻留与接口分析；
- 后续需要对接 `SystemC` 行为模型、runtime orchestration 和 paper narrative 的建模工作。

本文不试图直接给出：

- 最终 RTL 微架构；
- 最终布局布线频率；
- 最终签核级功耗；
- 全量软件生态兼容性结论。

## 2. 为什么系统级建模常常会“越算越乱”

系统级建模最常见的混乱源头，通常来自下面五种混淆：

1. **把 workload 描述和 hardware 设计混在一起**
   - 例如还没把 `SCF shell` 的对象流转说清楚，就急着给阵列规模或频率。

2. **把上界分析和实现估计混在一起**
   - `roofline` 算的是瓶颈上界，不是实现后一定能达到的性能。

3. **把 architecture-level 周期模型和 full-system 开销混在一起**
   - 单 kernel 周期快，不代表端到端 wall time 一定快。

4. **把能耗估算和精确电路功耗混在一起**
   - `Accelergy / McPAT / CACTI` 一类给的是 architecture-level estimate，不是 signoff power。

5. **把当前可冻结量和未来才可冻结量混在一起**
   - resident object 和边界流量通常比 buffer 最终大小、QoS、时钟树更早冻结。

因此，系统级建模首先要做的不是“套工具”，而是先把建模问题分层。

## 3. 一个常用且稳健的建模分层

下面给出一个在架构研究里非常常见、也最适合本项目的六层分法。

### 3.1 `L0`：工作负载与对象层

这一层的任务是把真实软件路径压成**可枚举的对象、阶段和流量**。

典型问题包括：

- 有哪些阶段；
- 每个阶段调用多少次；
- 输入输出对象是什么；
- 每个对象的 shape、dtype、layout、版本轮换是什么；
- 哪些对象适合驻留，哪些对象必须跨边界搬运；
- 一个 `SCF iteration` 的 dependence graph 是什么。

这一层通常可以产出：

- operator / body catalog；
- object catalog；
- per-stage input/output bytes；
- per-iteration call counts；
- Host / FPGA / Chip 边界流量。

这一层最重要，因为后续所有更高层模型，几乎都把它当输入。

### 3.2 `L1`：分析上界层

这一层不追求模拟所有细节，而是用 analytical model 先判断瓶颈大致在哪里。

常见量包括：

- `Arithmetic Intensity = Ops / Bytes`
- `T_compute_lb = Ops / PeakCompute`
- `T_offchip_lb = Bytes_offchip / BW_offchip`
- `T_onchip_lb = Bytes_onchip / BW_onchip`
- `T_body_lb = max(T_compute_lb, T_offchip_lb, T_onchip_lb)`

如果某个 body 的 `Arithmetic Intensity` 很低，那么即使算子形式看起来“很数学”，实际也可能是强 memory-bound。

这一层的作用不是给出最终性能，而是：

- 快速判定该 body 更偏 compute-bound 还是 bandwidth-bound；
- 粗筛掉不可能成立的设计点；
- 给后续 architecture exploration 一个合理范围。

### 3.3 `L2`：体系结构近似层

这一层开始引入更具体的架构假设，例如：

- array 并行度；
- tile 大小；
- buffer 层级与容量；
- 双缓冲与否；
- NoC / memory port / bank 假设；
- 数据映射与 schedule。

这一层通常输出：

- cycles；
- utilization；
- stall breakdown；
- 各 memory level 的访问统计；
- mapping efficiency；
- 某一 workload 在某一架构下的 traffic 分布。

这一层最接近架构研究论文里的“主性能结果”。

### 3.4 `L3`：全系统交互层

这一层不再只盯单个 accelerator，而是把下面这些系统问题拉进来：

- Host driver 开销；
- CPU companion solver 开销；
- OS / DMA / cache / memory hierarchy 干扰；
- CPU-accelerator / accelerator-memory 的共享路径竞争；
- 真实软件调用边界对整体 wall time 的影响。

如果一个方案在 `L2` 上看很快，但每次 body 之间都需要大量 host 介入和同步，那么 `L3` 可能会显著改变结论。

### 3.5 `L4`：能耗 / 面积估计层

这一层通常接受两类输入：

- architecture description；
- action counts / access counts / cycle counts。

输出包括：

- component-level energy；
- total design energy；
- area estimate；
- 有时还包括简单的 power proxy。

常见形式是：

`Energy_total ≈ Σ_i action_count_i × energy_per_action_i`

这一层适合做相对比较与论文级 estimate，但不等价于 signoff。

### 3.6 `L5`：实现与校准层

这一层才涉及：

- RTL；
- FPGA prototype；
- synthesis / P&R；
- measured frequency；
- real board power；
- 少量 microbenchmark 校准。

这一层通常不是用来替代前面的模型，而是用来：

- 校准分析模型误差；
- 校准能耗估计误差；
- 验证关键 datapath 是否实现可行。

## 4. 常用建模方法：分别解决什么问题

### 4.1 Workload accounting

这是最基础也最重要的方法。

典型做法：

- 从 trace、dump、operator log 或软件调用路径中提取阶段；
- 统计每个阶段的输入输出对象；
- 计算 shape、dtype、bytes、calls；
- 标出是否可驻留、是否必须跨边界；
- 组织成 shell-level timeline 或 DAG。

它最适合回答：

- 哪个阶段最值得下沉；
- 哪些对象值得驻留在近存或片上；
- Host / FPGA / Chip 边界数据量大概多少。

### 4.2 Roofline / bandwidth-bound analysis

这是最常见的一阶性能分析工具。

它适合：

- 快速判断是 compute-bound 还是 memory-bound；
- 估计 bandwidth 需求是否现实；
- 给出“即使实现完美也只能到什么量级”的上界。

但它不适合：

- 精细表达 pipeline bubble；
- bank conflict；
- irregular access；
- 跨阶段同步。

### 4.3 Queueing / service-rate model

当系统是多 stage pipeline 时，可以用每个 stage 的 service rate 估算整体吞吐。

最典型的写法是：

- `Throughput_pipeline ≈ min(service_rate_stage_i)`
- `Latency_episode ≈ Σ non-overlapped stage latencies + sync overheads`

它非常适合 shell-level system exploration，因为它允许把：

- `h_psi`
- `s_psi`
- `build H_sub / S_sub`
- `cdiaghg`
- `refresh`

统一看成一条有重叠关系的阶段链，而不是五个孤立 kernel。

### 4.4 Cycle-approximate architecture simulation

这类方法最适合：

- 阵列规模 exploration；
- tile / mapping 选择；
- buffer / bank / memory hierarchy 配置；
- 访问统计与 stall 分解。

它比 roofline 更细，也比 full-system 更聚焦。

论文里大量 accelerator evaluation 都是靠这一层给出主结果。

### 4.5 Full-system simulation

这类方法适合：

- 研究 host-device interaction；
- 研究 driver / runtime / memory hierarchy；
- 研究 CPU companion path 对整体 wall time 的影响。

如果研究问题是“这个 accelerator kernel 理论上多快”，full-system 往往太重；
如果研究问题是“端到端软件挂接后还能不能真的快”，full-system 才开始变重要。

### 4.6 Energy / area estimation

这类方法的核心思想通常是：

1. 给 architecture description；
2. 统计 action counts / access counts；
3. 查或生成 component action energy table；
4. 汇总 total energy / area。

它很适合研究：

- 某种驻留策略是否更省能；
- data movement 是否主导能耗；
- 不同架构方向在论文层面哪个更有 energy story。

### 4.7 Thermal / implementation-aware estimation

这类方法通常不是第一阶段必需，但在下面两种情况下会很重要：

- array 很大，局部功耗密度可能成为问题；
- 频率和面积开始进入比较真实的实现探索。

## 5. 常用工具：适用层次、输入输出与局限

下面列的是后续最可能用到的一批工具，不要求全部都上。

### 5.1 工具分层总表

| 工具 | 主要层次 | 主要输入 | 主要输出 | 更适合的问题 | 主要局限 |
| --- | --- | --- | --- | --- | --- |
| `gem5` | `L3` | system config、CPU/mem config、workload | cycles、stats、memory hierarchy interaction | full-system、host-device、软件挂接 | 慢，建模成本高 |
| `FireSim` | `L3/L5` | RTL / SoC config、FPGA deployment | cycle-exact-ish full-system behavior | 更真实的系统验证 | 成本高，准备重 |
| `Timeloop` | `L2` | architecture、mapspace、problem | mapping、performance、traffic、energy proxy | dense/tensor-style accelerator exploration | 偏映射/阵列类结构 |
| `Accelergy` | `L4` | architecture description、action counts | ERT/ART、energy estimate | architecture-level energy/area | 依赖 action counts 质量 |
| `MAESTRO` | `L1/L2` | dataflow、tensor dimensions、hardware params | latency、reuse、buffer req、bandwidth | data-centric dataflow analysis | 偏 DNN/tensor 风格 |
| `SCALE-Sim` | `L2` | array config、topology、layout | cycles、stall、bandwidth、detailed access | systolic / memory-bound exploration | 问题形式较偏阵列映射 |
| `Aladdin` | `L2/L4` | kernel、config、memory system params | power/performance/area proxy | pre-RTL accelerator exploration | 老，但方法论仍有参考价值 |
| `Sniper` | `L3` | multicore system config、workload | multicore performance stats | CPU-centric full-system-ish exploration | 对定制 accelerator 支持有限 |
| `SST` | `L3` | component graph、system params | system-level simulation stats | 组件化系统建模 | 配置复杂 |
| `McPAT` | `L4` | architecture stats、activity | power/area/timing estimate | CPU/SoC-level power/area | 需要统计与模型适配 |
| `CACTI` | `L4` | memory size / ports / banks / tech | cache/SRAM latency、area、energy | memory macro 估计 | 只覆盖 memory-like macro |
| `HotSpot` | `L4/L5` | floorplan、power trace | thermal estimate | 热分析 | 依赖功耗输入质量 |

### 5.2 `gem5`

`gem5` 是经典的 full-system / architecture research simulator。

它适合：

- 把 `CPU + cache + memory + interconnect + workload` 放在同一个系统里；
- 研究 host-device interaction；
- 研究 companion CPU / software stack 的系统影响。

它不太适合：

- 早期快速扫大量 accelerator design point；
- 在系统对象都还没冻结时就开始重度搭建。

### 5.3 `Timeloop + Accelergy`

这是一条很经典的组合：

- `Timeloop` 负责 architecture / mapping / traffic / latency；
- `Accelergy` 负责 architecture-level energy / area estimate。

这条路线特别适合：

- 有比较明确的 array / storage hierarchy；
- 想把 dataflow、tile、buffer 和 traffic 说清楚；
- 论文里需要结构化地展示 mapping、reuse 和 energy story。

### 5.4 `MAESTRO`

`MAESTRO` 的价值不只是“一个 DNN tool”，更重要的是它代表了一种**data-centric cost model** 思路：

- 先看数据复用和映射；
- 再看 latency、buffer requirement 和 bandwidth。

即使不直接拿来跑本项目，它的建模思路仍然很值得借鉴。

### 5.5 `SCALE-Sim`

`SCALE-Sim` 更偏阵列级、周期级和 memory-level 分析。

它适合：

- 估算阵列利用率；
- 看 SRAM / DRAM bandwidth；
- 看 stall cycles；
- 看不同 layout / memory system 假设的影响。

如果后续本项目出现比较明确的 tiled dense engine 或 projector engine，`SCALE-Sim` 风格的方法会很有参考价值。

### 5.6 `McPAT / CACTI / HotSpot`

这几个工具分别代表：

- `McPAT`：架构级 power / area / timing estimate；
- `CACTI`：memory macro 级 latency / area / energy estimate；
- `HotSpot`：温度估计。

它们更适合在：

- 架构参数已经初步冻结；
- 访问统计已经相对可信；
- 需要开始讲 energy/area/thermal story

时使用。

## 6. 对当前 `QE / DFT` 项目最推荐的建模顺序

### 6.1 第一步：先冻结系统对象，不先冻结电路细节

当前项目最需要冻结的是：

- `SCF iteration shell` 的阶段边界；
- `Host / FPGA / Chip` 的职责切分；
- resident object；
- 每个阶段的对象流转和边界流量。

换句话说，现在先回答：

- 哪些对象留在 host；
- 哪些对象驻留在 FPGA runtime；
- 哪些对象值得变成 chip-visible resident object；
- 哪些阶段可以互相重叠；
- 哪些阶段必须同步。

### 6.2 第二步：做 shell-level workload accounting

建议把每个阶段都整理成统一表格，至少包含：

| 字段 | 说明 |
| --- | --- |
| `Stage / Body` | 阶段名或 body 编号 |
| `Call Site` | 在 `SCF` 里的调用位置 |
| `Inputs` | 输入对象与 shape |
| `Outputs` | 输出对象与 shape |
| `Calls / Iter` | 每轮调用次数 |
| `Ops` | 算术量 |
| `Bytes In/Out` | 跨边界流量 |
| `Resident Candidates` | 哪些对象适合驻留 |
| `Can Overlap?` | 是否可和其他阶段重叠 |
| `Current Model Status` | 已建模 / 仅估算 / 未建模 |

### 6.3 第三步：对每个阶段做一阶上下界分析

每个阶段至少算下面几项：

- `Ops`
- `Bytes_offchip`
- `Bytes_onchip`
- `Arithmetic Intensity`
- `T_compute_lb`
- `T_offchip_lb`
- `T_onchip_lb`
- `B_required(target_time) = Bytes / target_time`

这样至少可以先判断：

- 哪些阶段主要受片外带宽限制；
- 哪些阶段值得通过驻留和对象复用来降低流量；
- 哪些阶段真正值得做更复杂的专用 datapath。

### 6.4 第四步：再做 architecture-level 近似时间模型

这一阶段建议只对少量候选设计点做：

- 并行度；
- buffer 大小；
- tile 大小；
- port / bank 假设；
- 双缓冲与否；
- pipeline overlap。

对每个 body 的 latency，可以先写成：

`T_body ≈ max(T_compute, T_data_move, T_memory_service) + T_sync + T_launch`

对一个 shell episode，可以写成：

`T_episode ≈ Σ non-overlapped bodies + Σ sync terms - Σ overlapped portions`

这比直接上全系统模拟更稳，也更符合当前阶段。

### 6.5 第五步：把 `cdiaghg` 明确当作 companion path 看待

当前阶段完全可以把 `cdiaghg` 视为：

- 暂时保留在 `CPU / soft-core companion solver`；
- 单独建模其输入输出字节数、调用频率和 wall time；
- 在 shell-level latency 里占一个阶段，而不强行下沉为第一版 chip 主路径。

这会让系统边界更清楚，也更符合当前 handoff 文档给出的优先级。

### 6.6 第六步：最后才引入能耗 / 面积估计

当下面这些已经相对稳定之后，再做 `L4`：

- resident object；
- body 边界；
- 主要 buffer 层级；
- 主要 traffic 统计；
- 大致 array / datapath 假设。

在此之前硬算 `energy/mm²` 或最终 `TOPS/W`，很容易让讨论失焦。

## 7. 现在就能算什么，先不要算什么

### 7.1 现在就能算

- 每个 `SCF iteration` 中各阶段的调用次数；
- 每个阶段的输入输出对象大小；
- resident object 候选；
- Host / FPGA / Chip 边界流量；
- 各阶段 `Ops`、`Bytes`、`Arithmetic Intensity`；
- 一阶 `compute-bound / bandwidth-bound` 判断；
- shell-level 是否值得重叠执行；
- 不同分工方案下的 episode-level latency proxy。

### 7.2 暂时不要硬算

- 最终频率；
- 最终面积；
- signoff 功耗；
- 完整 QoS；
- 精确 cache coherence 行为；
- 还未冻结的深层 microarchitecture 细节；
- 还没有稳定 resident object 之前的 buffer 最终尺寸。

## 8. 一个适合本项目的最小可行建模工作流

下面给出一个最小但完整的工作流，建议按这个顺序推进。

### Phase A：对象与阶段表

产出：

- `SCF shell` 阶段列表；
- object catalog；
- per-stage input/output/calls。

### Phase B：边界流量与驻留表

产出：

- Host / FPGA / Chip 边界流量表；
- resident object proposal；
- 版本轮换语义。

### Phase C：一阶上下界表

产出：

- 每个阶段的 `Ops / Bytes / AI / lower bound latency`；
- bandwidth requirement；
- compute-bound / memory-bound 标签。

### Phase D：shell-level latency model

产出：

- episode-level 时间分解；
- overlap 候选；
- CPU companion path 的占比。

### Phase E：candidate architecture exploration

产出：

- 小量 design point 的 latency / traffic / utilization 比较；
- 哪些 body 需要 array-like engine；
- 哪些 body 更适合 runtime / host 侧处理。

### Phase F：energy / area estimate

产出：

- component-level energy estimate；
- total energy per episode；
- data movement vs compute energy breakdown。

### Phase G：targeted validation

产出：

- 少量 microbenchmark；
- SystemC / FPGA / software baseline 对齐；
- 模型误差来源说明。

## 9. 对后续工具选型的建议

如果只从“当前项目阶段”出发，最建议的优先顺序是：

1. **先做本地表格化 workload accounting 与 shell-level latency model**
   - 这是当前最缺、也最值钱的部分。

2. **必要时借鉴 `Timeloop / MAESTRO / SCALE-Sim` 的方法论**
   - 不一定马上深度集成工具，但它们的建模口径值得借。

3. **当需要谈 host-device 真实挂接时，再考虑 `gem5` / full-system 路线**
   - 这一步不要太早。

4. **当架构参数初步稳定时，再引入 `Accelergy / McPAT / CACTI`**
   - 把 energy / area story 做起来。

## 10. 给本项目后续建模者的一句话

如果后续只记住一条原则，那么最值得记住的是：

> 先把 `SCF shell` 当作系统对象，把对象流转、边界流量和 resident object 说清楚；然后再让每一种工具只回答它真正擅长回答的问题。

这样做，系统级建模就不会变成“什么都想精确算，最后什么都不可信”。

## 参考资料

1. Roofline model: [Roofline: an insightful visual performance model for multicore architectures](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-134.pdf)
2. gem5 project site: [gem5](https://www.gem5.org/)
3. gem5 paper: Binkert et al., [The gem5 simulator](https://people.csail.mit.edu/tushar/papers/pdfs/gem5_can2011.pdf)
4. FireSim docs: [FireSim Documentation](https://docs.fires.im/en/latest/)
5. Timeloop site: [Timeloop](https://timeloop.csail.mit.edu/)
6. Timeloop repository: [NVlabs/timeloop](https://github.com/NVlabs/timeloop)
7. Accelergy site: [Accelergy](http://accelergy.mit.edu)
8. Accelergy repository: [Accelergy-Project/accelergy](https://github.com/Accelergy-Project/accelergy)
9. MAESTRO docs/tutorial: [MAESTRO Tutorial](https://maestro.ece.gatech.edu/docs/build/html/tutorials/micro2020.html)
10. SCALE-Sim repository: [scalesim-project/scale-sim-v2](https://github.com/scalesim-project/scale-sim-v2)
11. Aladdin repository: [harvard-acc/ALADDIN](https://github.com/harvard-acc/ALADDIN)
12. McPAT paper mirror: [McPAT: an integrated power, area, and timing modeling framework](https://perso.ens-lyon.fr/christophe.alias/evalM2/micro09b.pdf)
13. CACTI overview: [CACTI](https://www.hpl.hp.com/research/cacti/)
14. HotSpot site: [HotSpot Thermal Modeling](https://lava.cs.virginia.edu/HotSpot/)
