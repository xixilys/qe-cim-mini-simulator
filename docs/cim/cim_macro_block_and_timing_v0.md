# SRAM 数字 CIM 宏结构与计算/存储流程规范 v0

## 1. 文档定位

这份文件不是再讨论“`CIM` 大方向可不可做”，而是把当前系统里最关键的一块继续收口成**硬件实现口径**：

- 我们到底要做哪一种 `SRAM` 数字 `CIM`；
- 它在真实混合系统里承担哪些功能，不承担哪些功能；
- 阵列结构、外围计算结构、计算流程、存储流程怎么描述才和论文界常用写法一致；
- `projector` 常驻、输入流式、`PROJECT/BACKPROJECT` 双模式到底怎样落成可实现的宏结构。

本文默认服务的系统对象仍然是：

- `Host + software driver`
- `FPGA / runtime orchestrator`
- `Chip`

而本文只冻结 `Chip` 内的 `CIM / Projector-Apply Engine`。

当前如果要继续冻结 `resident_context`、`row_block` 与 `Near-SRAM` 协同接口，应继续阅读：

- `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`

## 2. v0 冻结结论

当前建议冻结的 `CIM` 方向不是：

- 模拟 `RRAM CIM`；
- 泛化的“整条 `H/S` 算子都在阵列里做完”；
- 面向任意矩阵常驻的通用 `FP64` 浮点阵列。

当前建议冻结的方向是：

> 一个 **6T SRAM 为主存储基底、投影列常驻、双模式、数字域、数位流输入、剩余域复数乘加** 的专用 `CIM` 宏。

它的核心口径固定为：

1. **常驻对象不是一般权重矩阵，而是 `projector / beta / projection basis` 列组**；
2. **宏的两个算术原语是 `PROJECT` 和 `BACKPROJECT`**；
3. `H/S/nonlocal` 相关 projector-family apply 不再描述成“一个宽泛 `CIM` opcode”，而是由：
   - `PROJECT`
   - 近存域小矩阵/系数变换
   - `BACKPROJECT`
   组合而成；
4. **浮点格式处理不放进阵列内部闭环**，而是由输入边界和输出重构逻辑承担；
5. **阵列内主计算域是 residue-domain complex `3M` MAC，而不是传统 bit-parallel `FP64` FMA 阵列**。

## 3. 设计输入与证据来源

### 3.1 项目内部设计输入

当前宏结构直接继承自 `ppt/20260319.tex` 的两条内部结论：

- `融合数位-剩余乘法`：常驻矩阵留在模域，流式输入留在数位域，数位到剩余的转换被吸收到主计算循环；
- `投影列常驻双模式计算宏`：同一份常驻投影基同时支持 `PROJECT` 与 `BACKPROJECT`，并采用 `G0/G1/G2` 渐进开启的活跃模组调度。

这两条决定了本文不能照搬常规 AI-CIM 的“整数 bit-serial MAC + adder tree”描述，而必须保持：

- `projector-column-resident`
- `digit-stream ingress`
- `residue-domain complex 3M`
- `mode-dependent reduction network`

### 3.2 本地论文库主证据

本轮实际检索了本地 `paper_db`、`Zotero` 附件层和 `extend_2/research_data` 中的全文资料。最直接影响当前结论的论文有：

1. `Jedhe et al., A 12nm 137 TOPS/W Digital Compute-In-Memory using Foundry 8T SRAM Bitcell supporting 16 Kernel Weight Sets for AI Edge Applications`, DOI `10.23919/VLSITechnologyandCir57934.2023.10185253`
   - 贡献给本文的不是 bitcell 本身，而是：**多组常驻权重上下文**和**写/算并行时的组织方式**；
2. `Chih et al., An 89TOPS/W and 16.3TOPS/mm2 All-Digital SRAM-Based Full-Precision Compute-In-Memory Macro in 22nm`, DOI `10.1109/ISSCC42613.2021.9365766`
   - 贡献给本文的是：**6T SRAM + bit-serial 输入 + 并行 adder tree + 精确数字累加**这一条数字 `SRAM CIM` 主线；
3. `Tu et al., A 28nm 29.2TFLOPS/W BF16 and 36.5TOPS/W INT8 Reconfigurable Digital CIM Processor with Unified FP/INT Pipeline and Bitwise In-Memory Booth Multiplication`, DOI `10.1109/ISSCC42614.2022.9731762`
   - 贡献给本文的是：**浮点/整数职责拆分**、**阵列内 mantissa/定点主乘加**、**边界做格式与对齐处理**；
4. `Wu et al., A 22nm 832Kb Hybrid-Domain Floating-Point SRAM In-Memory-Compute Macro with 16.2-70.2TFLOPS/W for High-Accuracy AI-Edge Devices`, DOI `10.1109/ISSCC42615.2023.10067527`
   - 贡献给本文的是：**浮点指数路径和 mantissa 路径拆开处理**、**流水分阶段组织**；
5. `Guo et al., A 28-nm 64-kb 31.6-TFLOPS/W Digital-Domain Floating-Point-Computing-Unit and Double-Bit 6T-SRAM Computing-in-Memory Macro for Floating-Point CNNs`, DOI `10.1109/JSSC.2024.3375359`
   - 贡献给本文的是：**global-floating/local-fixed** 思路、**双 bitcell + 局部浮点外围**、**weight-wise/feature-wise/channel-wise 可重构加法网络**；
6. `Mori et al., A 3nm 125 Tops/W-29 TFLOPS/W, 90 TOPS/mm2-17 TFLOPS/mm2 SRAM-Based INT8 and FP16 Digital-CIM Compiler with Multi-Weight Update/Cycle`, DOI `10.23919/VLSITechnologyandCir65189.2025.11074897`
   - 贡献给本文的是：**可参数化行数/输出通道组织**、**多权重更新/周期**、**编译器视角的宏尺寸与上下文切换问题**；
7. `Liu et al., CIM-BLAS: Computing-in-Memory Accelerator for BLAS`, DOI `10.1109/DAC63849.2025.11133288`
   - 贡献给本文的不是阵列电路，而是：**BLAS/科学计算型 dataflow 需要 H-tree / reduction / 可配置数据流，而不是只考虑 CNN 卷积数据流**。

### 3.3 网络补证

除本地全文外，本轮还补做了联网检索，用于确认近两年的公开口径与论文元数据：

- `VLSI 2025 advance program` 中的 `Mori 2025` 公开条目；
- `IEEE Xplore / DOI` 元数据页中的 `Tu 2022`、`Wu 2023`、`Guo 2024`；
- `DAC 2025` / `DOI` 元数据中的 `CIM-BLAS`。

因此，当前结论不是单靠仓库内部推演，也不是单靠本地 PDF 片段，而是：

> `内部设计约束 + 本地全文库 + 网络元数据确认` 三条证据一起支撑。

## 4. 为什么 v0 选择 6T SRAM 数字宏，而不是别的路线

### 4.1 不选模拟 / RRAM 路线

模拟 `RRAM/PCM` 的 fully weight-stationary 叙事在“权重常驻”上很诱人，但它不适合当前主线：

- 我们要处理的是 `complex + FP64 + strict numerical closure`；
- `projector` 路径后面还要接近存变换、reduction、closure；
- 外围需要明确的 `Host -> FPGA/runtime -> Chip` 合同和可回放控制。

在这种前提下，把主计算压到模拟电流域和 `ADC` 上，会把可验证性、数值闭环和系统接口都变得更难冻结。

### 4.2 不把 8T 多 kernel 选择结构直接当成模板

`Jedhe 2023` 的 8T 结构很好地说明了：

- 同一输入通道下保存多组权重上下文是可行且有价值的；
- 片上要认真设计写/算并行与上下文切换。

但它更适合 `CNN kernel-set` 选择，不是我们最自然的 projector 列常驻实现模板。当前 `DFT` 场景里真正需要的是：

- 行方向顺序扫描；
- 列组长期常驻；
- `PROJECT` 的列内归约；
- `BACKPROJECT` 的跨列组行归并。

因此，v0 不把 `8T + kernel selector` 当成主阵列原型，而只吸收它的**多上下文常驻思想**。

### 4.3 选择 6T SRAM + 局部数字计算切片

当前更自然的宏原型是：

- **6T SRAM bank** 负责存储常驻 `projector` 列组的剩余值；
- **输入边界** 负责 `FP64` 拆包、缩放、数位切分和共轭相关的前处理；
- **局部 `Residue_3M` 计算切片** 负责模平面内复数乘加；
- **列内/列间加法网络** 负责 `PROJECT` 与 `BACKPROJECT` 两类不同的归约方向；
- **扩模/重构单元** 只在必要阶段打开，不把所有模平面长期拉高活跃度。

这样做和 `Chih 2021`、`Tu 2022`、`Guo 2024` 的共同经验一致：

> 阵列负责最值得常驻和最密集的局部主乘加，复杂格式和更宽的闭环交给外围数字域。

## 5. v0 宏承担的功能边界

### 5.1 宏内部必须支持的功能

#### A. `PROJECT`

输入：

- 行块流式输入 `x_r`
- 当前 `resident_context_id`
- 当前 `row_block_id`

输出：

- 每个列组一个系数结果 `c_k` 的剩余表示

数据流本质：

- **同一行输入广播到所有列组**；
- **每个列组内部独立归约**。

#### B. `BACKPROJECT`

输入：

- 列组系数输入 `c_k`
- 当前 `resident_context_id`
- 当前 `row_block_id`

输出：

- 行结果 `y_r` 的剩余表示

数据流本质：

- **每个列组独立产生当前行的部分积**；
- **跨列组对同一行做归并**。

#### C. `resident context` 装载 / 切换 / 保持

这部分不是算术模式，但它是宏可用的前提。必须支持：

- `resident_context_id` 选择；
- `resident_generation` 或版本号；
- `row_block_id` 选择；
- `context_lock`，避免同一 episode 中途被覆盖；
- `context_valid` / `context_dirty` / `context_reload_needed` 状态。

### 5.2 宏不直接承担的功能

以下功能不应写成 `CIM` 宏内闭合责任：

- 完整 `FFT` 与 `reorder`；
- 全 `H psi` / `S psi` 的所有组成部分；
- `H_sub/S_sub` 完整 reduced build；
- generalized reduced solve；
- outer `SCF` mixing；
- 最终 `FP64` 完整结果重构与收敛控制。

### 5.3 `H/S/nonlocal` projector-family apply 如何表达

当前应统一写成：

```text
PROJECT
  -> near-SRAM small transform / coefficient update
  -> BACKPROJECT
```

也就是说：

- `CIM` 提供的是 projector-family 原语；
- `H/S/nonlocal` 是系统级组合，不是单一大而化之的阵列模式名。

## 6. v0 宏的阵列结构

### 6.1 顶层分块

当前建议的宏顶层结构如下：

```text
FP64 Input Boundary / Mode Controller
    |
    +-- Digit/Sum Generator
    +-- Conjugate Sign Selector
    |
    v
Column-Group SRAM Banks (resident projector columns)
    |
    +-- Local Residue_3M Slice per column group
    +-- Per-column Coefficient Accumulator
    |
    +-- Cross-column Row Merge Tree
    |
    v
Coeff FIFO / Row Residue Buffer / Promotion Unit
```

### 6.2 列组存储体组织

每个 `column group` 对应一个常驻 projector 列或小列束，物理组织建议如下：

- 维度一：`row_block`
- 维度二：`row index inside block`
- 维度三：`real / imag`
- 维度四：`G0 / G1 / G2 / redundant modulus`
- 维度五：`modulus-lane word`

换句话说，阵列存的是：

- `P_r[:,k]` 的实部/虚部剩余值；
- 已经按 `G0/G1/G2` 和冗余模分开；
- 不再在阵列里保存完整 `FP64` 指数/尾数格式。

### 6.3 为什么每列组只存一份 `P`

同一份常驻 `P` 同时服务 `PROJECT` 和 `BACKPROJECT`。

- `PROJECT` 里的共轭由输入边界或符号选择逻辑承担；
- `BACKPROJECT` 不需要再存一份 `P^H`。

因此：

- **不复制 `P^H` 存储体**；
- **只保留一份 `P`，通过 mode + sign control 切换**。

### 6.4 6T SRAM 基底与外围逻辑边界

当前建议用标准数字 `6T SRAM` 作为主存储基底，原因是：

- 读多写少，符合 `projector` 常驻特性；
- 可以把工艺和编译器资源集中在高密度常驻存储上；
- 乘加和加法树放在局部外围，更符合当前 `Residue_3M` 需求。

因此 v0 不是把“乘法直接做在 bitcell 内”，而是更接近：

> **SRAM-resident + local digital compute slice** 的数字 `CIM`。

这和 `Guo 2024` 的 `DBcell + FCU`、`Chih 2021` 的 `SRAM + parallel adder tree` 在思想上是一致的，只是我们把数值核心替换成了更适合本文的 residue-domain complex `3M`。

## 7. 计算架构

### 7.1 输入边界

输入边界负责以下动作：

1. `FP64` 拆包；
2. 绝对值/符号提取；
3. 必要的缩放与规范化；
4. 生成当前阶段的数位流 `d_t(x)` 或 `d_t(c)`；
5. 生成 `d_t(x_r + x_i)` 或 `d_t(c_r + c_i)` 以支持复数 `3M`；
6. 生成 `conjugate_sign`；
7. 控制当前活跃模组 `G0/G1/G2`。

这里特别要保持和 `ppt/20260319.tex` 一致：

- 输入保持在**数位域**；
- resident projector 保持在**剩余域**；
- 转换不在计算前一次性全部做完，而是被吸收到阶段流水里。

### 7.2 `Residue_3M` 局部计算切片

每个列组配置一个局部计算切片，最少包含：

- `Digit Latch`
- `Conjugate Sign Selector`
- `Residue_3M Core`
- `Local Modulus Accumulator`
- `Promotion / Reload Hook`

其职责是：

- 在每个活跃模平面上读取当前行的 resident residue；
- 与本周期数位输入做复数 `3M` 乘加；
- 把结果写回列内系数累加器或送入行归并树。

### 7.3 两类不同的加法网络

这部分必须明确分开，不要再用一个笼统的“adder tree”糊过去。

#### A. `PROJECT`：列组内归约网络

特点：

- 广播的是当前行输入；
- 结果是每列一个系数；
- 主要压力在**列内累加**。

因此需要：

- 每个列组独立的 `Coefficient Accumulator`；
- 最终把 `c_k` 写入 `Coeff FIFO`。

#### B. `BACKPROJECT`：跨列组行归并网络

特点：

- 输入是每列一个系数；
- 结果是每行一个输出；
- 主要压力在**列间同一行归并**。

因此需要：

- 跨列组 `Row Merge Tree`；
- 每个活动行一个 `Row Residue Buffer`。

### 7.4 渐进活跃模组调度

当前保持 `ppt/20260319.tex` 中的三段活跃模组策略：

| 阶段 | 活跃模组 | 作用 |
| --- | --- | --- |
| `stage1` | `G0` | 最低能耗起步阶段 |
| `stage2-4` | `G0 + G1` | 第一次扩模后进入中精度阶段 |
| `stage5-7` | `G0 + G1 + G2` | 第二次扩模后进入高精度阶段 |

补充要求：

- 冗余模不应长期全开，只在扩模/范围判定时参与；
- `G0/G1/G2` 必须物理上可独立门控；
- 活跃模组掩码由输入边界和 mode controller 共同控制。

## 8. 存储流程

### 8.1 `resident_context` 组织

每个 `resident_context` 至少包含：

- `resident_context_id`
- `projector_family_id`
- `layout_id`
- `modulus_profile_id`
- `row_block_count`
- `resident_generation`
- `valid_bits`

### 8.2 预加载流程

```text
Host / runtime prepare projector set
    -> FPGA pack by column-group / row-block / G0-G2 layout
    -> Near-SRAM staging buffer
    -> background load into CIM resident SRAM banks
    -> context_valid = 1
```

这里应固定两个原则：

1. `projector` 的编排由 `FPGA/runtime` 预先完成，不让 chip 内部做重格式化大工程；
2. 真正写入 `CIM` 的对象已经是“适合列组常驻”的布局，而不是软件原生布局。

### 8.3 计算期保持流程

在一个 `c_bands` episode 或一个 projector-family 小段内：

- `resident_context_id` 不应频繁切换；
- 允许 `row_block_id` 在 context 内切换；
- 允许同一 context 被多个 `PROJECT/BACKPROJECT` replay 反复复用；
- context 被锁住时，不允许后台覆写。

### 8.4 context 切换流程

建议固定为：

```text
drain current coeff/row buffers
  -> hard barrier at scheduler
  -> unlock old context
  -> load next context or mark miss
  -> issue next replay body
```

也就是说：

- 不把 context 热切换藏在宏内部黑盒中；
- context 切换是 `runtime-visible` 的；
- 切换边界必须和 replay body / barrier 对齐。

## 9. 计算流程

### 9.1 `PROJECT` 计算流程

| 步骤 | 输入 | 活跃子块 | 本地缓冲 | 输出 |
| --- | --- | --- | --- | --- |
| `P0` | `resident_context_id`, `row_block_id` | mode controller | context table | 有效配置 |
| `P1` | `x_r` | input boundary | digit latch | `d_t(x_r)`, `d_t(x_i)`, `d_t(x_r+x_i)` |
| `P2` | 当前数位 | broadcast fabric | digit broadcast latch | 广播到所有列组 |
| `P3` | resident residues | column-group SRAM | row read latch | 当前行 `P_{r,k}` 的 residue |
| `P4` | residue + digit | `Residue_3M` | local accum | 每列部分和 |
| `P5` | 列部分和 | coefficient accumulator | coeff residue buffer | `c_k` residue |
| `P6` | `c_k` residue | promotion unit | coeff FIFO | 导出或下游变换 |

### 9.2 `BACKPROJECT` 计算流程

| 步骤 | 输入 | 活跃子块 | 本地缓冲 | 输出 |
| --- | --- | --- | --- | --- |
| `B0` | `resident_context_id`, `row_block_id` | mode controller | context table | 有效配置 |
| `B1` | `c_k` | coeff ingress | coeff latch | `d_t(c_k)` and sum-digit |
| `B2` | resident residues | column-group SRAM | row read latch | 当前行 `P_{r,k}` residue |
| `B3` | residue + digit | `Residue_3M` | local row partial | 每列对当前行的部分积 |
| `B4` | 行部分积 | row merge tree | row residue buffer | 当前行和 |
| `B5` | 行和 | promotion / export | row FIFO | `y_r` residue |

### 9.3 projector-family apply 的系统级流程

`H/S/nonlocal` projector-family apply 在系统级上固定为：

```text
CIM.PROJECT
  -> Near-SRAM / Vector small transform
  -> CIM.BACKPROJECT
```

其中：

- 中间的小矩阵乘或系数更新不放进 `CIM` 阵列；
- 但系数对象要尽量保持在 chip-local 域，不回到 host。

## 10. 为什么这个结构和论文口径是一致的

当前方案不是凭空造词，而是和现有论文里几条成熟表达保持一致：

1. **权重/对象常驻**
   - 对应 `Jedhe 2023` 的多 kernel weight sets、`Guo 2024` 的 array-resident weight mapping；
2. **阵列负责 local compute，外围负责格式/控制**
   - 对应 `Tu 2022`、`Wu 2023`、`Guo 2024`；
3. **全数字精确累加，而不是模拟求和**
   - 对应 `Chih 2021`、`Guo 2024`；
4. **支持科学计算 / BLAS 的 reduction-oriented dataflow**
   - 对应 `CIM-BLAS 2025` 的 H-tree / configurable dataflow 视角；
5. **可参数化上下文与行块配置**
   - 对应 `Mori 2025` 的 compiler/macro co-design 视角。

因此，当前最合适的表述不是：

> “我们做了一个泛化浮点 `CIM`。”

而是：

> “我们冻结了一种面向 projector-family 的 `SRAM` 数字 `CIM`：以常驻投影列、数位流输入、剩余域复数 `3M`、双模式归约网络为核心。”

## 11. 当前仍未冻结的实现量

下面这些还需要在后续微架构阶段继续定量：

- 每个 `column group` 实际包含几列；
- `row_block` 的容量与切换成本；
- `G0/G1/G2` 每组模数数量和字宽；
- 冗余模数量；
- `Row Merge Tree` 扇入、流水深度和频率；
- `Coeff FIFO / Row Residue Buffer` 深度；
- 与 `Near-SRAM Support Domain` 的握手吞吐。

但这些未冻结项不影响本文已经固定的主判断：

- 路线是 `SRAM` 数字 `CIM`；
- 常驻对象是 `projector` 列组；
- 主原语是 `PROJECT/BACKPROJECT`；
- `H/S/nonlocal` 是由系统级组合实现，不再把完整闭环硬塞进阵列。

## 12. 可实现性、常驻与风险收口

独立的 `CIM` 可实现性审查文档已经并入本文件；当前稳定结论统一收口如下。

### 12.1 从现有 `CIM` 路线看，我们该站哪一侧

结合项目内部设计和本地论文库，目前最稳的判断不是继续追求“泛化浮点 `CIM`”，而是明确选择：

- 放弃模拟 / `RRAM` 路线在 `complex + FP64 + 严格闭环` 下的高风险路径；
- 不直接照搬面向 `AI` 的多 kernel-select `SRAM CIM` 模板；
- 固定在 **`6T SRAM` 数字 `CIM` + 局部数字伴随切片** 这条更可实现的 projector-family 路线。

### 12.2 哪些功能应当算作可实现

当前可以视为可实现并应继续冻结的，是：

- `PROJECT`：常驻投影列参与、输入流式进入、局部系数在阵列外围或近存侧冻结；
- `BACKPROJECT`：共用同一份常驻投影列，不额外存一份 `P^H`，通过模式切换与共轭/符号路径实现反向展开；
- `projector-family apply`：以 `PROJECT -> near-SRAM coeff transform -> BACKPROJECT` 的系统级组合表达 `H/S/nonlocal`，而不是要求阵列单独理解完整物理语义；
- `APPLY_H / APPLY_S`：只应理解为系统级 operator family 的组合调用，不应表述成“阵列里直接有一个完整 `H` 或 `S` 指令”。

### 12.3 哪些功能不应强塞进 `CIM`

以下内容当前不应压进阵列主职责：

- 完整外层 `SCF` 更新、收敛判断与软件态控制；
- 完整 FFT / reduce / solve 闭环；
- 把浮点格式恢复、全精度归一化、全局异常处理都塞进阵列；
- 用一个“万能 `CIM` 模式”掩盖 `projector apply`、近存小变换和 companion 计算之间的边界。

### 12.4 权重常驻的正式口径

当前关于“权重大部分时间常驻”的最稳收口是两级常驻：

- **一级常驻**：`episode-scope resident projector set`，即与当前 `k-point / band block / projector family` 对应的列组在一个 episode 内尽量不换；
- **二级常驻**：`active tile / row-block working set`，只在活跃行窗、局部模组和小范围系数缓存上发生快速轮换。

这意味着：

- 物理上只存一份 `P`，不额外复制 `P^H`；
- `G0/G1/G2` 这样的模组分层应当是可控的物理常驻层，而不是纯叙事概念；
- 输入对象保持流式，权重尽量保持常驻，结果先局部冻结再交给 `Near-SRAM Support Domain`。

### 12.5 当前最大的三个实现风险

当前最需要持续压住的风险是：

- **把 `CIM` 说得过宽**：导致系统边界失真，后续无法落 RTL；
- **把浮点格式问题直接压给阵列**：忽略了数位流、剩余域和外围补偿路径的职责划分；
- **常驻范围与活跃范围不分**：导致“常驻”沦为一句口号，而不是可量化的物理组织策略。

因此，当前最合适的一句话仍然是：

> 我们冻结的是一种面向 projector-family 的 `SRAM` 数字 `CIM`：以常驻投影列、数位流输入、剩余域复数 `3M`、双模式归约网络为核心，而不是一个泛化浮点 `CIM`。
