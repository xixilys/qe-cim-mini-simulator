# 2026-03-27 Long Control Word ISA v0

## 1. 文档目标

这份文档的目标不是继续定义一套传统意义上的处理器 ISA，而是给当前 chip 顶层定义一套 **Long Control Word (LCW) ISA**：

> 一条控制字同时指定多个计算部件的工作模式、数据输入输出来源、模块间数据流向，以及必要的同步/提交语义。

这份 LCW ISA 的设计动机来自当前项目的两个事实：

1. 如果系统只服务 `QE c_bands`，做成固定深流水最直接；
2. 但如果未来还想兼容 `VASP` 乃至 `CP2K`，chip 顶层就不能被写成只对应单一路径的 rigid pipeline。

因此，我们需要一个中间层：

- 不退回纯软件 runtime 调度；
- 不走完整通用 CPU；
- 也不只是“发一个 descriptor 给一个引擎”；
- 而是用一条 **长控制字** 去同时 orchestrate 多个引擎及其数据流。

本轮整理后，原 descriptor 展开件、template/replay 展开件与独立对象术语说明的稳定内容已经并入本文；从现在开始，`LCW`、descriptor 分层、template/replay 边界，以及 `object handle / resident buffer / version` 的控制术语统一以这份文档为主。

## 2. LCW ISA 的基本立场

### 2.1 这不是普通 VLIW，也不是普通 descriptor ISA

它和普通 `VLIW` 的相似点在于：

- 一条指令中有多个 slot；
- 多个 slot 可以在同一阶段同时控制多个功能部件。

但它和普通 `VLIW` 的差异更关键：

- 这里的重点不是多个 ALU/FPU 的并行发射；
- 而是 **多引擎之间的数据流编排**；
- 指令真正表达的是：
  - 哪些模块在这一阶段激活；
  - 它们的输入从哪里来；
  - 输出要流向哪里；
  - 哪些路径需要 join / fence / barrier。

因此，它更适合被称为：

- `Long Control Word`
- `Multi-Engine Dataflow Instruction`
- `Spatial Orchestration Word`

本文统一使用 `LCW`。

### 2.2 LCW 所处的层级

当前建议把整个控制栈明确分成四层：

1. **Episode / Subgraph Descriptor 层**
   - 对 `Host / FPGA / runtime` 可见；
   - 表示较粗粒度的软件任务对象；
   - 例如 `QE c_bands episode`、`VASP band-update subgraph`、`CP2K SCF kernel bundle`。

2. **LCW Template 层**
   - 对 `Host / FPGA / runtime` 与 chip 顶层 `Command Scheduler` 同时相关；
   - 表示某类 episode 在 chip 内通常拆成哪些 phase、哪些 word 骨架、哪些 patch 点与 replay body。

3. **Replay Contract 层**
   - 主要由 chip 内 `Command Scheduler` 执行；
   - 决定模板主体如何在片内局部闭环中重复推进、哪些字段自动轮换、何时退出。

4. **Concrete LCW Word 层**
   - 表示具体每条 `LCW` word 的 slot、route 与 commit 语义；
   - 真正决定模块怎么连、数据怎么走。

本文主要定义第 `2~4` 层，同时给出第 `1` 层 descriptor taxonomy 的最小稳定口径。

## 3. 这套 LCW 为什么能跨 `QE / VASP / CP2K`

根据前面的负载分析，三类软件虽然实现细节不同，但在 chip 顶层其实共享了一类更抽象的结构：

- 都存在多引擎协作，而不是单 kernel；
- 都涉及 `FFT / grid transform`、apply/projector-like 路径、局部线代、状态更新；
- 都需要 tile/panel/band/block 级的数据搬运和局部闭环；
- 差别主要不在“是否有模块”，而在：
  - 模块是否激活；
  - 激活顺序；
  - 数据流向；
  - solver mode / branch mode / batch mode。

因此，一个合理的共性 ISA 不是“所有软件共享同一条固定流水”，而是：

> 所有软件共享一套 **LCW 语法**，但在不同软件/不同阶段下使用不同的 slot 组合、route 组合和 phase 序列。

## 4. 顶层模块模型

当前 v0 先固定下面五个 LCW 可控对象：

- `CIM Slot`
- `FFT Slot`
- `SRAM Slot`
- `Solve Slot`
- `Vector Slot`

并由一个统一的：

- `Command Scheduler`

负责解码 LCW、检查依赖、发射到各模块。

### 4.1 五个 slot 的含义

#### `CIM Slot`
负责：
- `project`
- `apply`
- `backproject`
- resident-state dependent compute

#### `FFT Slot`
负责：
- `G <-> R` transform
- reorder
- selected grid support transform

#### `SRAM Slot`
负责：
- stage / hold / forward / recycle
- partial merge
- reduced-build feeder
- object-handle handoff / local continuity

#### `Solve Slot`
负责：
- `reduce-build`
- reduced solve
- closure / update
- convergence-side local operations

#### `Vector Slot`
负责：
- batched loop assist
- layout transform
- mask / gather / scatter
- postproc / aux arithmetic

### 4.2 为什么要把 `SRAM` 单独做成 slot

这是和传统 VLIW 最大不同之一。

在这里，`Near-SRAM Support Domain` 不是被动存储，而是数据流组织的关键节点。对当前系统来说：

- 很多收益不只来自算得更快；
- 也来自 partials、panels、reduced-build 输入在本地连续流动；
- 因而 `SRAM` 本身必须在 LCW 中占有显式控制位。

## 5. LCW v0 的总体格式

v0 中，一条 LCW 统一由四部分构成：

```text
LCW {
  Header
  Slots
  Routes
  Commit
}
```

### 5.1 `Header`

```text
LCWHeader {
  word_id
  epoch_id
  phase_id
  dependency_mask
  issue_policy
  priority
}
```

字段含义：

- `word_id`：当前控制字 id
- `epoch_id`：所属 episode / subgraph
- `phase_id`：所在的小阶段
- `dependency_mask`：依赖哪些前序 word / barrier
- `issue_policy`：normal / speculative-disabled / single-step / replay
- `priority`：调度优先级

### 5.2 `Slots`

```text
LCWSlots {
  cim_slot
  fft_slot
  sram_slot
  solve_slot
  vector_slot
}
```

每个 slot 的值不是任意程序，而是一个受限的 mode 集。

### 5.3 `Routes`

```text
LCWRoutes {
  route_0
  route_1
  route_2
  route_3
}
```

每条 `route` 表示一次合法源/宿连接，例如：

- `X_HANDLE -> CIM_IN`
- `CIM_OUT -> SRAM_PARTIAL_BUF`
- `SRAM_FULL_BUF -> SOLVE_IN`
- `FFT_OUT -> SRAM_STAGE_BUF`
- `VECTOR_OUT -> SRAM_META_BUF`

### 5.4 `Commit`

```text
LCWCommit {
  src_handle_0
  src_handle_1
  dst_handle_0
  dst_handle_1
  join_mode
  completion_mode
}
```

用于显式规定：

- 本条 LCW 消费哪些 object handle
- 产生哪些 object handle
- 是否需要 barrier / fence / join
- 是否允许异步完成

## 6. v0 的 slot 模式集合

关键原则：

> slot 必须是有限状态集合，而不是自由编程空间。

只有这样，LCW 才保持“硬件可控的长控制字”，而不会膨胀成隐式微程序机。

### 6.1 `CIM Slot` modes

```text
CIMMode = {
  IDLE,
  PROJECT,
  PROJECTOR_APPLY_CHAIN,
  BACKPROJECT
}
```

### 6.2 `FFT Slot` modes

```text
FFTMode = {
  IDLE,
  G_TO_R,
  R_TO_G,
  REORDER,
  AUX_FFT
}
```

### 6.3 `SRAM Slot` modes

```text
SRAMMode = {
  IDLE,
  STAGE,
  HOLD,
  FORWARD,
  RECYCLE,
  MERGE_PARTIAL,
  ASSEMBLE_FULL,
  FEED_REDUCED
}
```

### 6.4 `Solve Slot` modes

```text
SolveMode = {
  IDLE,
  REDUCE_BUILD,
  SOLVE_STANDARD,
  SOLVE_GENERALIZED,
  SOLVE_APPROX,
  OT_STEP,
  CLOSURE,
  CHECK
}
```

这里把 `OT_STEP` 提前纳入 mode 集，是为了给未来 `CP2K` 保留入口。

### 6.5 `Vector Slot` modes

```text
VectorMode = {
  IDLE,
  BATCH_UPDATE,
  LAYOUT_XFORM,
  MASK_OP,
  GATHER_SCATTER,
  POSTPROC,
  AUX_ARITH
}
```

## 7. Route 语义：LCW 的核心不只是 slot，而是数据流

如果说 `slot` 决定“模块做什么”，那么 `route` 决定的就是：

> 这些模块之间的数据到底怎么流。

v0 不应该允许任意全互连 route，而应限制为一组 **合法 route 集**。

### 7.1 建议的合法 source 集

```text
Source = {
  HOST_IN,
  SRAM_STAGE_BUF,
  SRAM_FULL_BUF,
  SRAM_META_BUF,
  FFT_OUT,
  CIM_OUT,
  SOLVE_OUT,
  VECTOR_OUT,
  HANDLE_IN_0,
  HANDLE_IN_1
}
```

### 7.2 建议的合法 sink 集

```text
Sink = {
  SRAM_STAGE_BUF,
  SRAM_PARTIAL_BUF,
  SRAM_FULL_BUF,
  SRAM_META_BUF,
  FFT_IN,
  CIM_IN,
  SOLVE_IN,
  VECTOR_IN,
  HANDLE_OUT_0,
  HANDLE_OUT_1
}
```

### 7.3 v0 中典型的合法 route 示例

```text
HANDLE_IN_0     -> FFT_IN
HANDLE_IN_0     -> CIM_IN
FFT_OUT         -> SRAM_STAGE_BUF
CIM_OUT         -> SRAM_PARTIAL_BUF
SRAM_PARTIAL_BUF-> SRAM_FULL_BUF
SRAM_FULL_BUF   -> SOLVE_IN
SOLVE_OUT       -> HANDLE_OUT_0
VECTOR_OUT      -> SRAM_META_BUF
SRAM_META_BUF   -> SOLVE_IN
```

### 7.4 为什么 route 必须受限

如果 route 完全自由：

- 硬件 crossbar / scheduling 成本会失控；
- 编程模型会过于松散；
- 很难保证 timing 与正确性。

因此 LCW v0 要表达“数据流”，但必须是：

- **有限合法边集合**
- 而不是任意图重连。

## 8. 对象句柄、驻留缓冲与代次语义

从当前版本开始，原独立的 object-handle 术语合同已经并入本文件。

原因很简单：

- `LCW` 不只是 slot 和 route；
- 它还必须明确“谁被消费、谁被产生、谁在近存域复用”；
- 如果这些对象语义仍散在单独小文档里，control 主线就还不够收口。

因此，后续 control 文档默认都应复用本节。

### 8.1 为什么不用 `token`

`token` 更像软件 runtime / 编译器数据流里的通用对象名。

对当前项目，这个词会同时带来两个问题：

1. 它会把对象流转写得更像软件消息传递，而不是 `Host + FPGA/runtime + Chip` 混合系统里的硬件控制合同；
2. 它容易把“逻辑对象身份”和“物理驻留位置”混成一个词。

因此，当前主线统一使用：

- `object handle`
- `resident buffer tag`
- `resident context`
- `version`

### 8.2 六个基础概念

| 概念 | 回答的问题 | 典型例子 |
| --- | --- | --- |
| `object` | 这是什么数据对象 | `X_PANEL`, `FULL_H`, `RITZ`, `RESIDUAL` |
| `object handle` | 控制层如何引用这个对象 | `X_PANEL_HANDLE`, `FULL_H_HANDLE` |
| `resident buffer tag` | 对象当前住在哪个片上域 | `SRAM_STAGE_BUF`, `SRAM_META_BUF`, `CIM_IN_X` |
| `route` | 本阶段允许对象往哪条边流动 | `HANDLE_IN_0 -> FFT_IN`, `SOLVE_OUT -> HANDLE_OUT_0` |
| `version` | 同类对象当前是第几代 | `X_PANEL@v0`, `NEXT_X_PANEL@v1` |
| `resident context` | 哪一组常驻对象跨 body 继续复用 | `projector_set`, `row_block`, `resident_generation` |

最推荐的理解方式是：

- `object` 解决对象身份；
- `object handle` 解决控制引用；
- `resident buffer tag` 解决驻留位置；
- `route` 解决阶段连通；
- `version` 解决 replay 轮换；
- `resident context` 解决跨 body 常驻集复用。

### 8.3 三条必须冻结的主规则

#### 8.3.1 `object handle` 不等于地址

`object handle` 最终当然可以映射到 buffer index、table entry 或物理 tag，但在控制合同层它不应被退化成裸地址。

因为它还必须携带：

- `object_kind / object_id`
- `episode_id`
- `version`
- `current_location / state`

也就是说，地址只回答“住在哪”，而 `object handle` 还要回答“它是谁、属于哪一轮、现在能不能继续被消费”。

#### 8.3.2 对象身份与驻留位置必须分开

后续文档不要再用一个模糊词同时表示：

- 对象是谁；
- 对象住在哪。

当前系统追求的不只是单点算子速度，还包括：

- panel / partial / reduced / residual 在 chip-local 域连续流动；
- `SRAM` slot 显式承接 staging、merge、assemble、near-memory glue；
- `CIM` 常驻对象与流动对象被分开建模。

所以：

- `object handle` 不能取代 `resident buffer tag`；
- `resident buffer tag` 也不能反过来取代对象句柄。

#### 8.3.3 `version` 绑定在 handle 语义上

replay 中的轮换优先理解成：

- `object-handle version rotation`
- `next-X handle promotion`
- `object retire / recycle`

而不是简单“把同一块缓存覆写一遍”。

这样写，才能把 local loop、闭环退出和对象生命周期放进同一套控制语义里。

### 8.4 推荐字段命名

后续 `LCW`、template、replay 和 lowering 文档优先使用下面这组硬件口径字段名：

- `src_handle_0`, `src_handle_1`, `dst_handle_0`, `dst_handle_1`
- `HANDLE_IN_0`, `HANDLE_IN_1`, `HANDLE_OUT_0`, `HANDLE_OUT_1`
- `x_init_handle`, `in_handle`, `out_handle`, `full_h_handle`, `residual_handle`, `next_x_handle`
- `resident_buffer_tag`, `src_buffer_tag`, `dst_buffer_tag`

不再推荐把这些字段写成：

- `token_in_0`
- `token_out_0`
- `token replay`
- `token remap`

### 8.5 一个最小对象流转例子

#### 8.5.1 `LOAD_AND_STAGE`

```text
src_handle_0   = X_PANEL_HANDLE
route_0        = HANDLE_IN_0 -> SRAM_STAGE_BUF
dst_handle_0   = STAGED_X_PANEL_HANDLE
dst_buffer_tag = SRAM_STAGE_BUF
```

这里最关键的是：

- `X_PANEL` 是 object；
- `X_PANEL_HANDLE` 是 object handle；
- `SRAM_STAGE_BUF` 是 resident buffer tag；
- `HANDLE_IN_0 -> SRAM_STAGE_BUF` 是 route。

#### 8.5.2 `SOLVE_AND_CLOSE`

```text
src_handle_0 = H_SUB_HANDLE
src_handle_1 = S_SUB_HANDLE

route_0      = SRAM_META_BUF -> SOLVE_IN
route_1      = SOLVE_OUT -> HANDLE_OUT_0

dst_handle_0 = RESIDUAL_HANDLE@v1
dst_handle_1 = NEXT_X_HANDLE@v1
```

这里最关键的不是某个算式，而是：

- 新对象句柄被产生；
- 它们带有新的 `version`；
- 后续 replay 继续消费的是“新一代 handle”，而不是旧句柄的含混覆写。

## 9. 三类软件如何映射到 LCW

### 9.1 `QE`

`QE c_bands` 最适合 LCW，因为它最接近当前已知主线。

典型 phase 序列可近似为：

1. `FFT / stage`
2. `PROJECT / projector-family apply chain / partial merge`
3. `ASSEMBLE_FULL / REDUCE_BUILD`
4. `SOLVE_GENERALIZED`
5. `CLOSURE / residual update`

也就是说，`QE` 主要体现为：

- route 比较稳定
- slot 组合比较稳定
- 只是 panel / batch / generalized flag 会变化

### 9.2 `VASP`

`VASP` 和 `QE` 很接近，但更强调：

- solver mode 切换
- batched bands
- `NSIM` 风格批处理
- 可能更多依赖 `Vector Slot` 做 batch-side glue

因此，`VASP` 的差异主要体现为：

- `SolveMode` 更频繁变化
- `VectorMode = BATCH_UPDATE / POSTPROC` 使用更高
- `FFT + CIM + SRAM` 主轴仍然保留

### 9.3 `CP2K`

`CP2K` 是 LCW 是否有共性价值的真正压力测试。

对 `CP2K` 而言，LCW v0 不能承诺完整覆盖，但可以提供入口：

- `FFT Slot` 仍然有用
- `Vector Slot` 重要性显著上升
- `Solve Slot` 中的 `OT_STEP` 提供未来兼容入口
- `SRAM Slot` 帮助 basis/block/grid 局部连续流动

也就是说，`CP2K` 更可能用：

- 不同的 slot 组合
- 不同的 route 组合
- 更少依赖 `CIM Slot` 的主中心性

但 LCW 语法仍可共用。

## 10. 一个最小 LCW 例子

下面给一个接近 `QE` 风格的例子：

```text
LCW #17
Header:
  epoch_id = 3
  phase_id = 2
  dependency_mask = {#16}
  issue_policy = normal

Slots:
  cim_slot    = PROJECTOR_APPLY_CHAIN
  fft_slot    = IDLE
  sram_slot   = MERGE_PARTIAL
  solve_slot  = IDLE
  vector_slot = POSTPROC

Routes:
  route_0 = HANDLE_IN_0 -> CIM_IN
  route_1 = CIM_OUT -> SRAM_PARTIAL_BUF
  route_2 = SRAM_PARTIAL_BUF -> SRAM_FULL_BUF
  route_3 = VECTOR_OUT -> SRAM_META_BUF

Commit:
  src_handle_0 = X_PANEL_HANDLE
  dst_handle_0 = HPSI_PARTIAL_HANDLE
  join_mode   = SOFT_JOIN
  completion_mode = ASYNC
```

这条 LCW 表示的不是“算一个指令”，而是：

- `CIM` 对输入 panel 启动 `PROJECTOR_APPLY_CHAIN`
- `SRAM` 同时执行 partial merge
- `Vector` 做边角后处理
- 数据按指定 route 在几个部件间流动
- 本条 word 不需要全局硬 barrier，只做 soft join

这就是我们想要的“长指令字控制多个计算部件之间数据流”的感觉。

## 11. 统一控制栈：descriptor、template 与 replay

### 11.1 descriptor 负责“任务边界是什么”

descriptor 不是普通处理器指令，也不是完整软件计划本身。它更像：

- `kernel descriptor ISA`
- `episode / subgraph command contract`
- `chip-top control envelope`

它对 `Host / FPGA / runtime` 可见，主要负责描述：

- 本次任务属于哪类 episode / subgraph；
- 输入输出对象是什么；
- resident context / shape / batch / band 范围是什么；
- completion、join、priority、resource hint 等粗粒度边界。

它不直接表达：

- 每条 `LCW` 在第几小阶段做什么；
- 哪几条 route 在片内如何连接；
- 哪些 object handle 在 local loop 中如何轮换。

### 11.2 `LCW` 负责“这一阶段几个模块怎么协同”

`LCW` 负责的仍然是当前文档最核心的部分：

- 哪些 slot 激活；
- route 怎么走；
- 哪些 object handle 被消费和产生；
- 哪一步需要 `soft join / hard barrier / fence`；
- 哪个 phase 属于 local replay body。

因此更准确的关系不是“descriptor 或 `LCW` 二选一”，而是：

> `Episode Descriptor -> LCW Template -> Replay Contract -> Concrete LCW Words`

### 11.3 v0 推荐的 descriptor family

在删去独立的 `chip-top descriptor` 文档之后，当前建议保留的 descriptor family 收口如下：

1. **`RESIDENT_LOAD`**
   - 负责把 projector set、coeff、panel 或局部 working-set 装入 `Near-SRAM Support Domain` 或相关近侧缓冲；
2. **`FFT_OP`**
   - 负责 `G<->R`、reorder 与选定 grid-support 变换；
3. **`PROJECT / APPLY / BACKPROJECT` family**
   - 包括 `PROJECT_OP`、`APPLY_OP`、`BACKPROJECT_OP` 三类具体 descriptor；
   - 共同对应 `CIM / Projector-Apply Engine` 的 projector-family apply 路线；
4. **`REDUCE / SOLVE / CLOSURE` family**
   - 包括 `REDUCE_BUILD`、`SOLVE_UPDATE`、`CLOSURE_STEP`；
   - 共同对应 `Reduction / Closure / Solve Engine`；
5. **`VECTOR_AUX`**
   - 承接 batched glue、layout transform、mask / gather / scatter 与轻量后处理；
6. **`BARRIER_JOIN`**
   - 显式承接多引擎同步、join、completion fence 与 episode done 语义。

之所以不再把 taxonomy 单独放成一份文档，是因为当前更关键的是：

- family 是否足够覆盖 `QE / VASP / CP2K`；
- descriptor 与 template / replay 的分层是否清楚；
- 而不是继续把 control 文档拆成多个平行入口。

### 11.4 为什么必须有 template，而不是只有 descriptor + LCW

如果没有 template，系统会退回两个极端：

- **极端一**：`Host/runtime` 直接发大量细粒度 `LCW`，导致 host-chip 控制开销过大、局部 loop 无法片内闭环；
- **极端二**：chip 内把整条路径硬写成固定流水，导致 `QE` 之外的软件兼容性和可选 phase 表达迅速僵化。

template 正好位于二者之间。它固定：

- 一个 episode 在 chip 内通常拆成哪些 phase；
- 默认 slot 组合与 route 拓扑骨架；
- 哪些 word 构成 replay body；
- 哪些字段允许 patch，哪些只允许在 replay 中自动轮换。

当前一个最小 template 对象应至少包含：

```text
LCWTemplate {
  template_id
  episode_kind
  phase_count
  static_words[]
  patch_points[]
  replay_policy
  exit_policy
}
```

### 11.5 静态、patch 与 replay 更新字段的边界

当前 v0 最稳的划分如下：

- **静态冻结字段**
  - `phase_id` 结构
  - 默认 `dependency_mask`
  - 默认 slot 组合框架
  - route 拓扑骨架
  - join / completion 的基本类型
  - 哪些 word 属于 replay body
- **runtime patch 字段**
  - `epoch_id`
  - 输入 object-handle id
  - resident set / panel / shape / band 范围
  - generalized / standard mode 开关
  - 可选 `FFT_PREP` 是否启用
  - local iteration 上限
  - priority / issue policy 的受限选择
- **replay 更新字段**
  - replay instance 编号
  - `src_handle` / `dst_handle` 的 version
  - `NEXT_X_PANEL -> X_PANEL` 的轮换关系
  - active-band mask handle
  - residual / loop-decision handle
  - 局部对象的 ready / retired 状态

一句话区分：

- patch：把模板接到“这次实例”上；
- replay：让模板主体在 chip 内多跑几轮。

### 11.6 一个最小 `QE c_bands` replay body 该怎么理解

当前最稳的 `QE c_bands` 最小 replay body 仍然是：

- `PROJECTOR_APPLY_CHAIN`
- `ASSEMBLE_AND_REDUCE`
- `SOLVE_AND_CLOSE`
- `LOOP_DECIDE`

这意味着：

- `LOAD_AND_STAGE` 更像实例准备；
- `FFT_PREP` 更像可选前导阶段；
- 主要 local loop 已经能够在 chip 内收口；
- scheduler 必须显式维护 object-handle/version 轮换，而不是把“下一轮输入对象”当成隐式覆盖。

因此，`object handle` 至少应当在合同层被理解为：

> `(object_kind, object_id, version, location)` 风格的受控引用对象。

### 11.7 scheduler 应有和不应有的自由度

当前最合适的理解是：scheduler 是**模板执行器 + 结构化 replay 控制器**，而不是一台自由编程微码机。

它应该拥有的自由度包括：

- 按模板推进 phase 顺序；
- 检查依赖与 join 是否满足；
- 维护 object-handle 生命周期与 version 轮换；
- 对可选 phase 做受限跳过，例如 `FFT_PREP disabled`；
- 根据 `LOOP_DECIDE` 继续或退出 replay。

它不应拥有的自由度包括：

- 凭空生成新模板；
- 重写 episode 的系统边界；
- 任意修改 route 图；
- 把 `LCW` 控制栈退化成通用可编程微码机。

### 11.8 这套控制栈如何覆盖 `QE / VASP / CP2K`

- **`QE`**：descriptor family、template 骨架、replay body 都最稳定；
- **`VASP`**：大概率仍复用接近 `QE` 的多引擎组织，但在 `Solve` / `Vector` mode 与可选 phase 组合上变化更大；
- **`CP2K`**：更可能改变 template 骨架、patch 点与 replay body，但不会首先推翻“descriptor -> template -> replay -> `LCW`”这一层级。

因此，未来软件扩展真正施压的是：

- template 语法是否足够泛化；
- replay 合同是否足够结构化；
- object-handle / version / resident-context 语义是否足够稳固。

### 11.9 `BODY_04A/B/C` 与 `BODY_10A/B/C` 的模板冻结边界

随着 `BODY_04A/B/C` 与 `BODY_10A/B/C` 已经进入正式 system-visible body catalog，`LCW` 主文档这里也要同步冻结一个关键边界：

- 这些 sub-body 不是“任意可编程微码段”；
- 它们是 **固定 template + 受限 patch_mask + 固定 route skeleton + 固定 completion/join 姿态** 的控制对象；
- deeper kernel 变化应继续落在 body-local mode / lowering / resident-object 合同里，而不是重新打开 body 编号与 replay 语义。

当前 `v0` 推荐把六个 sub-body 理解为下面这张总表：

| sub-body | `template_id` | slot skeleton | canonical route subset | `patch_mask` 主集合 | `completion/join` | `replay_policy` |
| --- | --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `TPL_BODY_04A_DENSITY_ACCUM_V0` | `Vector + SRAM_META_BUF` | `R29`, `R31`, `R32` | `src_handle_0`, `src_handle_1`, `episode_id`, `scf_iter_id`, `active_band_mask_handle` | `SYNC + HARD_BARRIER` | `NO_REPLAY` |
| `BODY_04B` | `TPL_BODY_04B_POTENTIAL_REFRESH_V0` | `FFT(optional) + Vector + SRAM_META_BUF` | `R01/R02/R03/R34` 或 `R29`，再接 `R31`, `R32`, `R33` | `src_handle_0`, `src_handle_1`, `support_grid_mode`, `potential_epoch`, `resident_context_id` | `SYNC + HARD_BARRIER` | `NO_REPLAY` |
| `BODY_04C` | `TPL_BODY_04C_MIX_CONVERGE_V0` | `Vector + SRAM_META_BUF` | `R29`, `R30`, `R31`, `R32`, `R33` | `src_handle_0`, `src_handle_1`, `history_depth`, `mixing_mode`, `stop_policy` | `QUERYABLE + SOFT_JOIN` | `NO_REPLAY` |
| `BODY_10A` | `TPL_BODY_10A_PRECOND_UPDATE_V0` | `Vector + SRAM_STAGE_BUF` | `R29`, `R36` | `src_handle_0`, `residual_handle`, `precond_mode`, `active_block_mask`, `episode_id` | `SYNC + HARD_BARRIER` | `NO_REPLAY` |
| `BODY_10B` | `TPL_BODY_10B_ORTHO_REBIND_V0` | `SRAM_STAGE_BUF + Vector + SRAM_META_BUF` | `R35`, `R30`, `R31`, `R32`, `R33` | `src_handle_0`, `src_handle_1`, `orthogonalize_mode`, `resident_context_id`, `metric_handle` | `SYNC + HARD_BARRIER` | `NO_REPLAY` |
| `BODY_10C` | `TPL_BODY_10C_HISTORY_COMMIT_V0` | `SRAM_META_BUF + Vector + SRAM_META_BUF` | `R05`, `R30`, `R31`, `R33` | `src_handle_0`, `src_handle_1`, `history_depth`, `summary_epoch`, `stop_policy` | `QUERYABLE + SOFT_JOIN` | `NO_REPLAY` |

这张表在控制意义上冻结了三件事：

1. `BODY_04A/B` 与 `BODY_10A/B` 都保持 `SYNC + HARD_BARRIER`，不允许跨过未完成对象；
2. `BODY_04C` 与 `BODY_10C` 是 outer decision / history summary 的控制可见点，因此保留 `QUERYABLE + SOFT_JOIN`；
3. 六个 sub-body 全部保持 `NO_REPLAY`，也就是：
   - 允许 local hold / queue absorb；
   - 允许 `runtime` 在 body 边界做受控重发；
   - 不允许 chip-side scheduler 在 sub-body 内自由扩出新的 replay 环。

这也解释了为什么当前这套东西更像混合系统里的 `LCW`：

- `LCW` 负责把 **固定模块协作骨架** 具体发出来；
- template / patch 负责把这次实例绑到正确的对象句柄、版本和常驻上下文上；
- `runtime` 仍然保留 family 边界上的恢复、重发和软件兼容裁决权；
- 它不是把 chip 退化成普通通用 ISA 核。

## 12. v0 的冻结点与未冻结项

当前最应该冻结的，不再只是 `LCW` packet 比特位，而是下面六条：

1. **五 slot 架构与合法 route 集是否成立**
   - `CIM / FFT / SRAM / Solve / Vector`
2. **descriptor -> template -> replay -> `LCW` 的控制栈是否成立**
3. **patch / replay 的职责边界是否成立**
4. **descriptor family taxonomy 是否足以覆盖当前 `QE / VASP / CP2K` 主压力**
5. **object-handle/version 语义是否被正式承认**
6. **`QE c_bands` 的最小 replay body 是否自然**
7. **`BODY_04A/B/C` 与 `BODY_10A/B/C` 的 template/patch/replay 边界是否固定**

当前仍未完全冻结的主要问题则继续集中在：

- `CIM Slot` 与 `Solve Slot` 的更细 mode taxonomy；
- template 的具体编码形式与下载方式；
- family 级 rollback / 局部恢复的更细策略；
- `VASP / CP2K` 进入 `v1` 后更细的 mode-switch / body-family 字段。

## 13. 当前最合理的下一步

沿着当前已经压缩后的 control 文档链，下一步最合理的不是再拆新文档，而是继续冻结三件事：

1. 在 `docs/architecture/system_interface_contract_v0.md` 中继续收紧 route、端点和对象态字段；
2. 在 `docs/control/qe_cbands_lcw_lowering_v0.md` 中继续用最小 `QE` lowering 反推 slot/mode/route 是否还缺口；
3. 在 `docs/control/qe_phase_cde_replay_bundle_contract_v0.md` 与 `docs/control/body10_ot_block_update_contract_v0.md` 已完成 catalog 对齐的基础上，继续冻结 route subset、异常升级和 family 边界重发规则。

也就是说，control 文档下一阶段不再优先“横向增文档”，而是优先让：

- `LCW` 主文档
- 接口合同
- `QE` lowering
- `BODY_04/BODY_10` family 合同

这几份形成稳定闭环。

## 14. 参考来源

- `Survey/reports/2026-03-27-qe-vasp-cp2k-three-way-workload-matrix.md`
- `Survey/reports/2026-03-27-vasp-cp2k-workload-and-chip-top-compatibility-note.md`
- `docs/control/qe_cbands_lcw_lowering_v0.md`
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`
- `/Volumes/remote/app/drclaw-home/projects/dft-3d3b0be1/workspace/output/2026-03-26-v1-cim-array-centered-system-design-for-ppt-unified.md`
