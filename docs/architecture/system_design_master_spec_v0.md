# 2026-03-28 DFT 混合加速系统主设计规范 v0

## 1. 文档定位

### 1.1 作用

这份文件是当前仓库的**主系统设计文档**。

它的职责不是替代所有专题文档，而是把现在已经形成的系统级结论统一收口成一份更接近硬件开发习惯的总规范，明确回答下面几件事：

- 系统对象到底是什么；
- 顶层控制、数据流、对象流转到底怎么定义；
- chip 内每个主要模块到底负责什么；
- 当前哪些内容已经稳定，哪些仍然只是过渡性设计；
- 现有 `SystemC` 原型究竟验证到了哪一层。

经过本轮整理后，本文还吸收并替代了三类原先重复承担系统级角色的文档中的稳定部分：

- 问题定义与故事对齐文档中的赛道边界、目标指标与 baseline 取向；
- 模块实现展开件中的模块树、最小功能合同与 `SystemC` 结构化要求；
- 审阅导航包中的系统审核入口与主文档导航结论。

因此，从当前版本开始，**整个仓库只有这一份系统级主规范**；其余文档只作为接口、控制、`CIM` 与建模支撑件保留。

### 1.2 系统对象

本文的系统对象不是单个 `CIM` 阵列，也不是孤立的 band solver IP，而是一个完整的混合系统：

- `Host + software driver`
- `FPGA / runtime orchestrator`
- `Chip`

本文后续统一把这个对象称为：

> `DFT Hybrid Accelerator System`

### 1.3 读者对象

本文默认服务以下几类读者：

- 系统架构设计者：看系统边界、分层、冻结点；
- 芯片顶层/数字实现设计者：看模块分工、控制合同、接口责任；
- SystemC 建模者：看行为模型应该保持哪些事务边界；
- 运行时/编译映射设计者：看 descriptor、replay、LCW 三层关系；
- 后续论文/汇报整理者：看当前系统主叙事是否一致。

### 1.4 文档状态

本文是 `v0` 主规范。

当前状态定义如下：

- **已稳定**：系统对象、六域划分、`QE` 主线切口、`LCW` 的角色、对象语义主术语，以及 system-visible body catalog（`BODY_00-05`、`BODY_04A/B/C`、`BODY_10A/B/C`）；
- **部分稳定**：`Phase A-E/Bx` 的系统级流程、`QE/VASP -> replay` 的下降关系、`BODY_04/10` 之下更深的 lowering / mode / object 细节；
- **未冻结**：精确编码、时钟/复位/功耗架构、buffer 容量、QoS 仲裁、最终 KPI 栈、`VASP` support-grid / mode-switch 的最终字段、`CP2K OT` 更深层 sparse-object catalog。

### 1.5 文档组织依据

本文的组织方式有两个明确参考来源：

- `ISO/IEC/IEEE 42010` 风格的架构描述思路：先定义系统对象、相关干系人/关注点，再组织视图和设计理由；
- `OpenTitan` 公开硬件文档的实践结构：总览、功能、工作原理、硬件接口、时钟/复位、实现状态、检查清单。

因此，本文不是单纯的“研究笔记汇总”，而是有意朝更标准的硬件总设计文档格式收口。

## 2. 范围与非目标

### 2.1 本文覆盖范围

本文覆盖的是当前项目在系统级已经收口出的内容：

- 面向 `QE / VASP / CP2K` 的一类 DFT 主路径混合加速系统；
- 以 `QE` 为当前可执行主线；
- 以 `VASP / CP2K` 作为顶层控制合同与模块边界的扩展压力检查；
- 以 `descriptor -> replay body -> LCW` 三层控制合同组织 `Host / FPGA / Chip`；
- 以 `object handle + resident buffer tag + version` 组织对象生命周期；
- 以 `SystemC` 行为级模型承载当前系统验证入口。

### 2.2 本文不覆盖的内容

本文**不**等价于以下对象：

- 完整通用处理器 ISA 规格；
- 单个 block 的 RTL 微架构说明书；
- 带精确位宽/寄存器图/时序图的实现冻结文档；
- 数值上完全 faithful 的 `QE / VASP / CP2K` 全软件复刻；
- 已经冻结的最终 benchmark 与投稿 KPI 方案。

### 2.3 v0 非目标

当前 `v0` 明确不以以下目标作为完成标准：

- 不要求把 `Chip` 写成 rigid 的固定深流水；
- 不要求一步推成完整 CPU / CGRA / fully programmable array；
- 不要求当前就把 `CP2K` 的 sparse/block 路线完整落成硬件；
- 不要求当前就把 outer `SCF` 所有 phase 全部下沉成 chip-visible replay body。

## 3. 设计驱动与主要关注点

### 3.1 设计驱动

当前系统设计由以下事实驱动：

1. 真实 DFT workload 不是孤立 kernel，而是 `SCF` 驱动的多阶段闭环；
2. 当前第一可执行主线来自 `QE`，且最清晰的内层系统对象是 `c_bands` family；
3. 如果未来希望兼容 `VASP` 乃至 `CP2K`，顶层就不能冻结成只适配单一路径的 rigid pipeline；
4. 主价值不只来自峰值算力，更来自主链对象在片上/近存域的连续流动与数据搬运压缩；
5. 数值约束是 `complex + FP64 + Hermitian/generalized Hermitian`，不能照搬典型 AI-CIM 的近似假设。

### 3.2 干系人与关注点

| 干系人 | 主要关注点 | 本文对应部分 |
| --- | --- | --- |
| 系统架构设计者 | 系统对象、边界、冻结项 | 第 4、5、12、13 节 |
| 顶层设计/前端设计者 | 模块划分、接口责任、控制层次 | 第 5、6、8、9 节 |
| 建模者 | 哪些行为必须保留、哪些还可抽象 | 第 10、11 节 |
| 运行时/映射设计者 | descriptor、replay、LCW 的分层与 patch 点 | 第 5、6、7 节 |
| 研究叙事整理者 | 为什么是这个系统对象，而不是更宽泛的 DQC-wide cut | 第 2、3、4、12 节 |

### 3.3 当前最重要的系统级关注点

当前最值得优先维护的关注点不是“模块名够不够炫”，而是以下五条：

- **软件挂接位置是否真实**：必须能说明自己在真实 `DFT` 主路径中的位置；
- **控制层次是否清楚**：descriptor、replay、LCW 不能混写；
- **对象生命周期是否闭合**：对象身份、驻留位置、版本轮换要能说清；
- **模块责任是否可实现**：每个模块必须有明确边界，而不是抽象口号；
- **当前实现状态是否诚实**：已经建模到哪、尚未下沉到哪，必须明确区分。

### 3.4 当前赛道、目标指标与文章边界

当前最稳的系统级口径已经收口为：

- **赛道**：`domain-specific accelerator / digital processing`，服务 `QE / CP2K / VASP` 这类 `DFT` 主路径，而不是通用 `AI-CIM` 或孤立数值 `IP`；
- **第一版对象**：先围绕真实 `QE-connected band-solver subsystem` 做可运行混合系统，再向完整 `SCF` system model 扩张；
- **第一版目标**：优先保证“真实软件挂接 + 端到端闭环 + 模块责任清楚 + 可继续下沉”，而不是一开始就追求最大范围的硬化；
- **主指标方向**：优先看 `c_bands / SCF episode` 的端到端时间、能耗与数据搬运，其次才是 area efficiency 与局部算子性能；纯峰值 `TOPS/W` 不能作为主指标；
- **baseline 原则**：至少同时保留软件真实路径 baseline，以及 primitive 相对 `GEMM baseline` / `transpose-aware macro baseline` 的局部比较；
- **明确边界**：当前不把 cache coherence、多 chip/多核扩展、完整透明编译栈、cycle-accurate 数值 faithful 模型，作为本文必须先冻结的内容。

这组结论原先分散在问题定义、模块规格和审阅导航文档里；本次整理后，统一以本文为唯一系统级入口。

## 4. 顶层系统架构

### 4.1 系统分层

当前系统的顶层分层固定为三层：

1. **Host / software driver**
   - 负责高层 `SCF` 任务组织、软件态控制、外层收敛逻辑、与原始软件栈的挂接；
2. **FPGA / runtime orchestrator**
   - 负责 episode 级计划组织、对象搬运、bundle patch、模式切换、fallback 与 replay 调度；
3. **Chip**
   - 负责最值得固化在片上的主算子链和近存连续数据流。

### 4.2 顶层结构图（文字版）

```text
Host / software driver
    |
    | episode / subgraph request
    v
FPGA / runtime orchestrator
    |
    | replay body bundle + patched parameters
    v
ChipTop
    |
    +-- Command Scheduler
    +-- CIM / Projector-Apply Engine
    +-- FFT Engine
    +-- Near-SRAM Support Domain
    +-- Reduction / Closure / Solve Engine
    +-- SIMD / Vector Companion
```

### 4.3 为什么系统对象必须是三层混合系统

当前最关键的判断是：

- 真实软件对象不是“把一个矩阵乘法喂给一块芯片”；
- 真实系统也不是“Host 直接逐条细粒度发指令给每个执行单元”；
- 更自然的结构是：
  - `Host` 保留软件语义和外层闭环；
  - `FPGA/runtime` 承担任务组织、patch、重放与适配；
  - `Chip` 保留有限但强的数据流编排能力与领域专用执行域。

因此，本文后续所有接口与模块定义都以这个三层对象为前提。

## 5. 控制架构

### 5.1 三层控制合同

当前系统的控制合同分为三层：

1. **Episode / Subgraph Descriptor 层**
   - `Host` 与 `FPGA/runtime` 可见；
   - 定义“要完成什么软件阶段”；
   - 例子：`QE c_bands episode`、`VASP band-update subgraph`、`CP2K SCF kernel bundle`。

2. **Replay Body 层**
   - `FPGA/runtime` 与 `ChipTop` 的中间层；
   - 定义“这一组 phase/body 在 chip 内如何按模板重放”；
   - 这是当前系统从抽象工作流走向真实硬件控制的关键中层。

3. **LCW`（Long Control Word）层**
   - `ChipTop` 顶层调度器可见；
   - 定义“这一小阶段里哪些执行域被激活、数据从哪里进、往哪里走、何时提交”。

### 5.2 为什么这里是 `LCW` 而不是普通 ISA

当前顶层不适合直接描述成普通处理器 ISA，原因是：

- 这里的关键不是标量/向量算术 opcode；
- 也不是传统 `VLIW` 式多个算术单元并行发射；
- 真正要表达的是：
  - 多执行域是否同时激活；
  - 数据从哪个对象/驻留域进入；
  - 哪些 route 合法；
  - 哪些结果在本阶段提交、驻留、转发或 join。

因此，当前更准确的说法是：

> `LCW` 是一类多引擎数据流编排控制字，而不是普通通用 ISA。

### 5.3 当前 `LCW` 的稳定结构

当前 `LCW v0` 的稳定组成是：

- `Header`
- `Slots`
- `Routes`
- `Commit`

其中稳定概念包括：

- 采用多 slot 结构而不是单 opcode；
- slot 对应主要执行域；
- route 是 `LCW` 的核心，不只是附属字段；
- commit 语义必须显式表达对象产出和后续可见性。

### 5.4 当前 `LCW` 的五类主要 slot

当前建议保留五个 slot：

- `CIM Slot`
- `FFT Slot`
- `SRAM Slot`
- `Solve Slot`
- `Vector Slot`

注意：

- 这是 **LCW 控制视角** 下的五 slot；
- 它和 chip 内的六域划分并不矛盾；
- `Command Scheduler` 本身是顶层控制域，不作为普通算子 slot 出现。

### 5.5 当前 replay body catalog

当前主线 body catalog 收口为：

- `BODY_00`: `basis_seed_and_bind_body`
- `BODY_01`: `operator_apply_body`
- `BODY_02`: `reduced_closure_solve_body`
- `BODY_03`: `refresh_compact_rebind_body`
- `BODY_04`: outer-update family alias
- `BODY_04A`: `density_accum_body`
- `BODY_04B`: `potential_refresh_body`
- `BODY_04C`: `mix_converge_body`
- `BODY_05`: `outer_scf_control_body`
- `BODY_10`: `CP2K/QS_OT` extension family alias
- `BODY_10A`: `ot_precond_update_body`
- `BODY_10B`: `ot_ortho_rebind_body`
- `BODY_10C`: `ot_history_commit_body`

其中：

- `BODY_01-03` 已经较明确地对应 chip-visible `Phase B` 主线；
- `BODY_04` 继续保留 family alias，但 system-visible 编号层已经冻结为 `BODY_04A/B/C`；
- `BODY_05` 负责 outer `SCF` 层面的控制语义；
- `BODY_10` 继续保留 family alias，但 system-visible 编号层已经冻结为 `BODY_10A/B/C`；
- 更深的 `BODY_04/10` kernel、route、assist-engine 与 sparse-object 细节继续留在 body 之下，不再继续拿 body 编号承载。

### 5.6 当前系统级 phase 划分

当前最稳的系统级 phase 划分如下：

| Phase | 软件语义 | 当前 body 对应 | 当前实现状态 |
| --- | --- | --- | --- |
| `Phase A` | setup / seed / bind | `BODY_05 + BODY_00` | 已有行为级模型 |
| `Phase B` | `c_bands` / band-solver episode | `BODY_01-03` | 当前最接近 chip replay 的部分 |
| `Phase Bx` | OT/block-update 扩展 inner-loop | `BODY_10A-10C` | `CP2K/QS_OT` 已有行为级模型 |
| `Phase C` | `sum_band` | `BODY_04A` | 已冻结为正式 sub-body |
| `Phase D` | `v_of_rho / newd` | `BODY_04B` | 已冻结为正式 sub-body |
| `Phase E` | `mix_rho / convergence gate` | `BODY_04C + BODY_05` | 已冻结为正式 sub-body |
| `Family Alias` | outer-update / OT extension 高层入口 | `BODY_04`, `BODY_10` | 仅作为 family alias 保留 |

### 5.7 当前控制定义已经完成到什么程度

如果问题是“系统级指令、控制流、数据流是不是已经全部完成了”，当前最准确的回答是：

- **层次关系已经基本完成**：descriptor / replay / LCW 三层已经成立；
- **主线 phase 定义已经基本完成**：`Phase A-E` 已可统一表达；
- **`QE` 内层下降已经完成到 v0**：`c_bands` 已能映射到 `LCW + replay` 语言；
- **但硬件冻结远未完成**：精确编码、完整合法 route 矩阵、例外/异常语义、时序接口、性能计数、仲裁策略都未冻结。

因此，当前状态应该描述为：

> 系统控制架构已成型，但尚未进入可直接做 RTL 顶层冻结的完成态。

## 6. 对象与数据合同

### 6.1 基础术语

当前对象语义统一采用以下五个概念：

- `object`
- `object handle`
- `resident buffer tag`
- `route`
- `version`

### 6.2 为什么不用 `token`

这里不再把 `token` 作为主术语，原因是：

- 它过于像软件运行时或编译器 IR 里的抽象对象；
- 不利于区分“逻辑对象身份”和“物理/近物理驻留位置”；
- 不符合当前希望建立的硬件控制合同语境。

因此，本文统一采用：

- `object handle`：对象引用；
- `resident buffer tag`：驻留位置标识。

### 6.3 对象语义关系

推荐的对象语义关系如下：

- `object`：这个数据对象是什么；
- `object handle`：控制层如何引用它；
- `resident buffer tag`：它当前驻留在哪个缓冲/端点域；
- `route`：本阶段允许它往哪条数据通路走；
- `version`：同一对象在不同迭代/阶段的代次关系。

### 6.4 当前核心对象类型

当前系统级模型中最核心的对象类型包括：

- `WavefunctionBlockObject`
- `DensityObject`
- `PotentialObject`
- `ProjectorStateObject`
- `ReducedClosureObject`
- `SCFHistoryObject`

### 6.5 当前对象生命周期主规则

当前系统的对象生命周期规则可稳定写成：

1. `Host` 或 `FPGA/runtime` 为软件阶段绑定对象句柄；
2. `FPGA/runtime` 将其 patch 到 replay body / `LCW` 模板；
3. `Chip` 内部通过 `resident buffer tag` 完成 staged / resident / forwarded 的局部连续流动；
4. 新阶段结果以新 `version` 的 `object handle` 对外提交；
5. 旧对象根据策略继续保持、回收或退役。

### 6.6 当前对象合同已经完成到什么程度

当前对象模型已经完成了以下关键部分：

- 不再把对象身份与地址混写；
- 不再把对象身份与驻留位置混写；
- 已经引入 `version` 以表达 replay 轮换；
- 已经进入 `SystemC` 原型中的显式状态对象。

但仍未完成的部分也很明确：

- 统一对象状态机还没冻结；
- 句柄位宽/编码空间未冻结；
- resident buffer taxonomy 的容量/银行/一致性细节未冻结；
- 对象回收和跨 phase 保活策略还未形成正式实现规范。

## 7. 系统级数据流与控制流

### 7.1 v0 的主工作流

当前最稳的 v0 主工作流是以 `QE` 为主线的五阶段 `SCF` 闭环：

```text
Phase A: setup / seed / bind
    ->
Phase B: c_bands / band-solver episode
    ->
Phase C: sum_band
    ->
Phase D: v_of_rho / newd
    ->
Phase E: mix_rho / convergence gate
    -> next SCF iteration or stop
```

#### `QE` 主线的三层循环关系

上面这张 `Phase A-E` 图只表达了 `SCF` 外层阶段顺序，**不代表每个 phase 在一次 `SCF` 里都只运行一次**。

对当前最关键的 `QE` 主线，更准确的控制结构是三层嵌套：

1. **最外层：`SCF` 自洽循环**
   - `rho -> Veff -> c_bands -> rho_out -> mix_rho -> next SCF`
2. **中间层：`k` 点循环**
   - 每个 `k` 点都要各自完成一轮 band solver episode
3. **最内层：`Davidson / bands not converged` 循环**
   - 在单个 `k` 点内部反复执行 `operator apply -> subspace build -> reduced solve -> refresh/residual`

当前阶段用于系统建模的最准确伪代码应该理解成：

```text
while SCF not converged:
    rho -> Veff
    for k in k_points:
        while bands not converged:
            h_psi
            s_psi
            build H_sub / S_sub
            cdiaghg
            refresh / residual -> P_next
    psi -> rho_out
    mix_rho
```

这里要特别强调两点：

- `Phase B` 不是一个“一次进入、一次退出”的单次 body，而是一个在 `SCF` 迭代内部、按 `k` 点和 Davidson 内循环反复展开的 episode；
- 当前 `Si8` workload 样本里虽然 `kpoints = 1`，但这只是这个 case 的实例，不应该把系统级控制合同写死成“没有 `k` 点循环”。

#### 为什么这层循环关系对系统设计很关键

把三层循环写清楚之后，系统切分的判断也会更稳定：

- `rho -> Veff`、`psi -> rho_out`、`mix_rho` 更接近 **每个 `SCF` iteration 一次** 的对象；
- `h_psi / s_psi / build H_sub,S_sub / cdiaghg / refresh,residual` 更接近 **`SCF` 内反复滚动的小循环体**；
- 因此，硬件最值得抓住的不是某个孤立小算子，而是这个最内层反复回环的数据流壳层。

### 7.2 各 phase 的系统责任划分

| Phase | Host 责任 | FPGA/runtime 责任 | Chip 责任 |
| --- | --- | --- | --- |
| `A` | 外层迭代建立、初始对象绑定 | 初始化 replay 上下文 | 仅执行必要初始化/绑定辅助 |
| `B` | 发起 band-solver episode | 组织 `BODY_01-03` bundle | 主执行域完成 operator/reduce/solve/refresh |
| `C` | 维持 phase 级语义 | 调度 density accumulation bundle | 当前多为行为级或局部计算支撑 |
| `D` | 维持势更新语义 | 调度 potential/nonlocal refresh bundle | 当前多为行为级或局部计算支撑 |
| `E` | 外层收敛与 mixed state 更新 | 管理收敛门控与下一轮参数 | 当前以 host-visible 行为为主 |

### 7.3 为什么当前重点仍然是 `Phase B`

因为当前证据链中：

- `QE` 可执行主线最完整地落在 `c_bands` family；
- `BODY_01-03` 已经能清楚映射到 chip 内的多执行域协作；
- 这是最适合先冻结控制语言、对象合同与模块边界的部分。

但这并不代表系统对象只等于 `Phase B`。当前更准确的说法是：

> `qe_band_solver_model` 现在已经是完整 `SCF` 骨架中的 `Phase A-E` 行为级系统模型，其中 `Phase B` 是下沉最深的 chip-side body family。

### 7.4 当前数据流合同已经完成到什么程度

当前数据流合同已经完成了以下系统级表达：

- 哪些对象更偏 resident，哪些对象更偏 streaming；
- 主要 route 必须在 `LCW` 中显式写出；
- `CIM / FFT / SRAM / Solve / Vector` 五 slot 可以联动；
- `Near-SRAM Support Domain` 是主动数据流执行域，不是被动缓存。

但以下部分仍未完成冻结：

- 全量 source/sink 合法性矩阵；
- 跨 phase 对象驻留保活规则；
- route 冲突、仲裁、背压与优先级的统一规范；
- 面向实现的 buffer 深度、吞吐、bank conflict 处理方式。

## 8. Chip 内模块规范

## 8.1 `Command Scheduler`

### 模块角色

- 接收 `FPGA/runtime` 组织后的 replay body / `LCW` 控制；
- 完成解码、依赖检查、阶段派发、join/barrier/completion 管理；
- 维护 `object handle` 生命周期与 issue 顺序。

### v0 必须支持的功能

- `LCW` 解码与多 slot 派发；
- body 内依赖管理；
- 对象句柄可见性与版本轮换管理；
- completion / join / barrier 语义；
- 基本 issue policy 与队列前后关系维护。

### 当前未冻结项

- 精确命令队列组织；
- exception / timeout / retry 处理；
- QoS 优先级与公平性策略；
- performance counter 暴露方式。

## 8.2 `CIM / Projector-Apply Engine`

### 模块角色

- 承担 `projector-family` 主算子路径；
- 服务 `QE` 中最关键的 projector/nonlocal/operator apply 主链；
- 是当前系统主线中最领域专用的计算域；
- 在实现上冻结为 `projector-column-resident SRAM digital CIM`，而不是宽泛的通用 `FP64` 算子阵列。

### v0 必须支持的功能

- `PROJECT`
- `BACKPROJECT`
- `resident context` 的装载/切换/保持
- 通过 `PROJECT -> near-SRAM small transform -> BACKPROJECT` 组合支撑 `H/S/nonlocal` projector-family apply

### 当前未冻结项

- `CIM Slot` mode 的精确集合与编码；
- projector 常驻格式与 `row_block` 布局；
- 与 `FFT`、`Near-SRAM` 的接口吞吐要求；
- `G0/G1/G2` 的规模、冗余模数量与 `Row Merge Tree` 参数。

当前与 `resident_context`、`row_block`、`Near-SRAM` 协同相关的正式接口冻结，见：

- `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`

## 8.3 `FFT Engine`

### 模块角色

- 提供 reciprocal / real-space 变换与必要重排；
- 处理 `QE/VASP` 中显著存在的 FFT/grid-support 路径；
- 作为主链支撑域而不是边角工具模块。

### v0 必须支持的功能

- `G_TO_R`
- `R_TO_G`
- `REORDER`
- `AUX_FFT`

### 当前未冻结项

- transform 尺寸/批次组织；
- 片上缓冲与输入输出格式；
- `VASP` support-grid / addgrid 风格路径需要的额外模式；
- 与 `CIM` / `Vector` 的直接 route 集合。

## 8.4 `Near-SRAM Support Domain`

### 模块角色

- 负责对象 staged/resident/recycle/merge/assemble/feed 的近存连续流动；
- 维持局部数据流连续性；
- 是当前系统“不是只靠算子快，而是靠对象流动更短”的关键收益来源。

### v0 必须支持的功能

- `STAGE`
- `HOLD`
- `FORWARD`
- `RECYCLE`
- `MERGE_PARTIAL`
- `ASSEMBLE_FULL`
- `FEED_REDUCED`
- 对 replay / object handle 的近存支撑。

### 当前未冻结项

- resident buffer 分类与命名全集；
- 容量、bank、路由器和一致性策略；
- 不同对象类型的驻留优先级；
- 片上持久对象和短命对象的回收策略。

## 8.5 `Reduction / Closure / Solve Engine`

### 模块角色

- 负责 reduced build、closure、solver、检查与局部闭环；
- 承担从局部主算子结果走向 reduced-space 决策的关键闭合步骤；
- 是把“算子链”变成“可迭代求解链”的关键域。

### v0 必须支持的功能

- `REDUCE_BUILD`
- `SOLVE_STANDARD`
- `SOLVE_GENERALIZED`
- `SOLVE_APPROX`
- `OT_STEP`（保留为扩展位）
- `CLOSURE`
- `CHECK`

### 当前未冻结项

- `Solve Slot` 是否继续合并 closure/check/solve 语义；
- `OT` 路线的真实下沉边界；
- 小矩阵求解与近存聚合之间的切分方式；
- 与 `CP2K` 兼容时是否需要额外 matrix/block object 支撑。

## 8.6 `SIMD / Vector Companion`

### 模块角色

- 处理 layout、mask、gather/scatter、postproc、batch update 等数字支撑功能；
- 为不同软件路径提供模式切换和轻量补算空间；
- 避免系统被迫退化为“所有边角算术都回 Host”。

### v0 必须支持的功能

- `BATCH_UPDATE`
- `LAYOUT_XFORM`
- `MASK_OP`
- `GATHER_SCATTER`
- `POSTPROC`
- `AUX_ARITH`

### 当前未冻结项

- 它与 `LCW` 的指令粒度关系；
- 与 `Solve` 域的边界；
- `VASP NSIM` / `CP2K` task-bundle 风格压力下需要的批处理模式；
- 是否要上升成更强的向量子系统或只保留 companion 角色。

## 8.7 六域划分是否已经最终完成

当前最准确的回答是：

- **逻辑六域划分已经足够稳定，可以作为系统级规范使用；**
- **物理实现层面的宏块合并/拆分还没有冻结。**

也就是说，当前可以稳定维护的是“六类职责域”，但不能假装已经完成了最终物理 floorplan 级模块切分。

## 9. 外部接口、时钟复位与系统集成约束

### 9.1 `Host <-> FPGA/runtime` 接口

当前稳定的接口层级是 episode / subgraph 级，而不是细粒度指令级。

这一层至少需要表达：

- 请求类型；
- episode 标识；
- 输入对象句柄；
- 模式/精度/软件路径配置；
- 完成状态与摘要。

当前已整理出的 v0 正式字段表见：

- `docs/architecture/system_interface_contract_v0.md`

### 9.2 `FPGA/runtime <-> Chip` 接口

当前稳定的接口层级是 replay body / patched template / `LCW` stream。

这一层至少需要表达：

- body kind / body sequence；
- patch 后的 `object handle` 与 mode 参数；
- 依赖关系；
- completion / join / barrier 语义；
- 结果对象提交与摘要。

当前已整理出的 v0 正式字段表见：

- `docs/architecture/system_interface_contract_v0.md`

### 9.3 Chip 内部接口

当前对 chip 内部接口已经形成的稳定要求是：

- 不是共享总线式“谁都能发给谁”的完全开放网络；
- 而是由 `LCW route` 显式控制的有限合法连接图；
- route 必须和对象句柄、驻留位置、版本提交语义协同定义。

当前已整理出的 v0 端点命名与合法 route 集见：

- `docs/architecture/system_interface_contract_v0.md`

### 9.4 时钟、复位与功耗

从硬件文档标准看，这一节必须存在；但从当前项目进度看，这一节仍处于早期。

当前只能稳定写下以下约束：

- 系统一定存在 `Host/FPGA` 侧与 chip 侧的时钟/事件边界；
- chip 内部大概率需要至少控制域与主数据路径域的区分；
- `LCW` / completion 语义必须在跨域条件下保持可解释；
- 当前尚未形成可冻结的 clock tree / reset tree / power domain 方案。

因此：

- **这一节已被纳入主规范结构；**
- **但内容仍未到可实现冻结水平。**

### 9.5 可观测性与调试

当前系统必须预留以下观测对象：

- phase/body completion；
- object version 演进；
- resident buffer 命中/回收；
- route 激活统计；
- solver / closure 摘要；
- outer `SCF` 收敛门控摘要。

但具体计数器、trace 端口、调试 CSR 仍未冻结。

## 10. 当前可运行模型与验证状态

### 10.1 当前可运行模型

当前最重要的可运行系统模型位于：

- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`

它表达的是：

```text
HostSCF -> FPGAOrchestrator -> ReplayBundleExecutor ->
{ChipTop/BODY_01-03 replay, optional BODY_10A/B/C under BODY_10_FAMILY, BODY_04A/B/C under BODY_04_FAMILY} -> next SCF iteration
```

当前已经可以在这个统一骨架下运行：

- `QE / CBANDS_DIAG`
- `CP2K / QS_DIAG`
- `CP2K / QS_OT`
- `VASP / BLOCKED_DAVIDSON`
- `VASP / FAST`

### 10.2 这个模型已经证明了什么

当前模型已经证明：

- 三层系统对象不是空概念；
- `Phase A-E/Bx` 已经可以在一个统一行为模型中串起来；
- `BODY_01-03` 可以承担 chip-side `Phase B` 主线；
- `BODY_10A/B/C` 已经可以作为 `CP2K/QS_OT` 的运行时扩展 body 序列插入 `Phase B` 之后；
- `BODY_10` 现在也已经具备 `Body10StageRequest / Body10StageSummary / Body10LoweringPlan` 形式的显式 stage-level 合同；
- `VASP` 的 `BLOCKED_DAVIDSON / FAST` 两类 flow family 已经能落到统一的行为级控制骨架；
- `object handle / resident buffer tag / version` 已进入可运行模型；
- `BODY_04A/B/C` 已经从单个合并摘要收口成带 `Body04StageRequest / Body04StageSummary` 的分阶段 runtime bundle；
- `Body04LoweringPlan` 已经把 `BODY_04A/B/C` 的 stage route / residency / latency lowering 写成显式对象；
- `ReplayBundleDescriptor / ReplayBundleCompletion` 已经把 `Phase B`、`BODY_10A/B/C`（经 `BODY_10_FAMILY` alias）与 `BODY_04A/B/C`（经 `BODY_04_FAMILY` alias）收口到统一 runtime 接口；
- `ChipTop` 已经显式暴露行为级 `run_replay_bundle(...)` 入口；
- 模型现在能生成显式 `SCFIterationReport / DFTRunReport`，不再只依赖滚动日志判断全流程是否闭合；
- `QE` 主线已经从“band-solver subsystem demo”提升为“完整 SCF skeleton system model”。

### 10.3 这个模型还没有证明什么

当前模型还**没有**证明：

- 它不是数值 faithful 的 `QE electrons` 全实现；
- `Phase C/D/E` 虽然已经冻结为 `BODY_04A/B/C` body catalog，但尚未 lower 成最终冻结的 chip-visible `LCW` micro-sequence；
- `BODY_04A/B/C` 当前仍主要是 runtime-managed timed-functional body，而不是最终 silicon 接口冻结版；
- 当前 `run_replay_bundle(...)` 与 `Body04LoweringPlan` 仍然只是行为级系统入口与 lowering 合同，还不是最终 silicon 接口冻结版；
- 还没有完整时序、带宽、能耗和面积级证明链。

### 10.4 当前软件证据完整度排序

基于现有证据，当前三套软件的完整度排序仍然是：

- `QE`：本地可执行 + trace + 系统模型主线
- `CP2K`：源码/benchmark 级主流程恢复
- `VASP`：公开文档驱动的主流程恢复

因此，当前系统级规范的第一锚点仍然必须是 `QE`。

## 11. 审核结论：当前系统到底完成了多少

### 11.1 已经完成的部分

当前可以认为已经基本完成的系统级设计内容包括：

- 系统对象已经从“单 IP”升级为 `Host + FPGA/runtime + Chip` 混合系统；
- `QE` 主线的 `Phase A-E` 闭环已经形成统一系统视图；
- `descriptor -> replay body -> LCW` 三层控制合同已经成型；
- `object handle + resident buffer tag + version` 对象合同已经成型；
- 六域职责划分已经可以稳定使用；
- `Phase B` 的下降路径已经足够支撑继续做系统级建模。

### 11.2 还没有完成的部分

当前**还不能**说已经完全完成的内容包括：

- 系统级指令编码与合法 route 矩阵没有完全冻结；
- `Phase C/D/E` 还没有真正下沉为 chip-visible body/bundle；
- 六域的物理实现切分与接口细节没有冻结；
- 时钟/复位/功耗没有正式规格；
- 异常/流控合同已形成 v0，但尚未到 RTL 协议冻结；
- KPI 栈、baseline、公平比较与端到端证据链没有定稿；
- `CP2K/VASP` 虽然已经有行为级 flow-family 映射与全流程 run report，但其软件侧证据仍然主要来自源码/文档恢复，而不是本地 executed trace。

### 11.3 因此当前最准确的一句话

> 现在已经有了一套可持续推进的系统架构主规范，但它仍处于“系统合同已成型、硬件实现细节未冻结、完整闭环尚在下沉”的阶段。

### 11.4 当前建模层级判定

为了避免把“能跑的系统骨架”误说成“已经完成的硬件模型”，当前统一把系统建模层级分成下面五层：

| 层级 | 名称 | 能回答的问题 | 当前仓库状态 |
| --- | --- | --- | --- |
| `L0` | 软件流程恢复 | 软件主流程、phase/body 边界、对象语义是否正确 | `QE` 已有 executed anchor；`CP2K/VASP` 仍多依赖源码/文档恢复 |
| `L1` | 事务/对象级系统模型 | `Host/FPGA/Chip` 事务边界、descriptor/replay/object 生命周期是否闭合 | 已完成 |
| `L1.5` | 结构化 timed-functional 模型 | 主要模块树是否显式、每轮由哪些模块工作、参考周期/忙闲统计怎样分布 | `Phase B` 与 `BODY_04` 已进入这一层 |
| `L2` | 结构化硬件模型 | 模块接收条件、busy 条件、队列/credit、backpressure、资源竞争、并发重叠 | `Phase B` 与 `BODY_04` 已有 leaf-block proxy，但仍未冻结 |
| `L3` | cycle-approx 微架构模型 | 固定端口宽度、buffer 深度、仲裁策略、跨 body/跨 batch 重叠时序 | 尚未开始冻结 |
| `L4` | RTL/实现模型 | 时钟/复位/寄存器/位宽/时序约束/DFT/功耗实现 | 尚未开始 |

当前更准确的判定应是：

- `Host + FPGA/runtime` 主体仍以 `L1` 为主；
- `ChipTop Phase B` 现在处在 `L1.5 + L2 proxy` 之间：
  - 有显式模块树；
  - 有 `module occupancy`；
  - 有 `reference-cycle` 级 busy 统计；
  - 能指出当前 critical domain；
  - projector 主链与 closure 主链都已经下沉到 leaf-block `accept/busy/complete`；
  - 已经显式导出 provisional ingress queue depth、ingress/egress owner、arbitration domain、credit limit 与 dominant backpressure route；
- 但它**还不能**被称为完成版 `L2` 硬件模型，因为还缺：
  - 最终冻结的 ingress/egress queue 深度与 credit 数值；
  - 明确的跨 route 资源争用与仲裁矩阵；
  - 多 episode / 多 batch 并发重叠；

- `Body10FamilyController / BODY_10A/B/C` 现在也处在 `L1.5 + L2 proxy` 之间：
  - `preconditioned update / orthogonalize-rebind / history commit` 三段都已有显式 stage summary；
  - 已经能导出 `BODY_10` stage 级与 bundle 级 `reference-cycle` / `backpressure` 摘要；
  - 叶块层也已有 `accept/busy/complete`、ingress/egress owner、arbitration domain 的代理合同；
- 但它同样**还不能**被称为完成版 `L2` 硬件模型，因为还缺：
  - OT deeper sparse/object lowering 的固定 datapath 边界；
  - block-sparse / AO mixed object 的真实容量与仲裁矩阵；
  - 和 `Phase B` / `BODY_04` 的跨 bundle 并发重叠规则；

- `OuterUpdateRuntimeDomain / BODY_04A/B/C` 现在也处在 `L1.5 + L2 proxy` 之间：
  - `Density / Potential / Mixing` 三段都已有显式 stage summary；
  - 六个支撑 block 都有 leaf-block `accept/busy/complete`、ingress/egress owner、arbitration domain；
  - 已经能导出 `BODY_04` stage 级与 bundle 级 `reference-cycle` / `backpressure` 摘要；
- 但它同样**还不能**被称为完成版 `L2` 硬件模型，因为还缺：
  - outer-update family 的真实 kernel lowering；
  - 与 `Phase B` / `BODY_10` 的跨 bundle 重叠执行规则；
  - 更细的 runtime-memory / host-visible 仲裁与异常恢复协议；
  - 独立时钟/复位/功耗域；
  - 真实 kernel lowering 对应的固定 datapath 时序。

因此，如果按硬件开发口径来命名，当前仓库里的 `qe_band_solver_model` 更准确的表述应当是：

> 一套以硬件模块树为骨架、带参考周期与模块忙闲统计的 `QE-connected full-SCF` 结构化 timed-functional 系统模型，而不是最终硬件微架构模型。

## 12. 冻结项、过渡项与缺口

### 12.1 当前建议视为已冻结的内容

- 真实系统对象是 `Host + FPGA/runtime + Chip`；
- 当前第一主线是 `QE`，不是更宽泛但更空泛的 `DQC-wide` 切口；
- 顶层控制要走 `descriptor -> replay -> LCW`，不是回退成纯软件 runtime，也不是直接上通用 CPU ISA；
- `LCW` 是多引擎数据流控制字，不是普通通用 ISA；
- `object handle + resident buffer tag + version` 是主术语；
- 六域职责划分是当前系统级主划分。

### 12.2 当前建议明确标为过渡项的内容

- `BODY_04A/B/C` 内部更深的 route / assist-engine / capacity 参数；
- `BODY_04A/B/C` 当前是 runtime-managed body，还是哪些部分还要继续下沉为更强 chip-autonomous body；
- `Solve` 域与 `Vector` 域的更精细切分；
- `OT_STEP` 进入 v1 还是更后续；
- `VASP` support-grid / solver-mode 切换对 `LCW` 的字段扩展；
- `CP2K` matrix/block object 如何进入 replay body catalog。

### 12.3 当前最关键的规范缺口

如果按硬件开发文档标准来审，当前最明显的缺口是：

1. **单一主规范文件** 已经补齐为 `docs/architecture/system_design_master_spec_v0.md`，但仍需持续维护而不是重新分散；
2. **v0 稳定接口表** 已补到 `docs/architecture/system_interface_contract_v0.md`，但异常/流控/编码仍未冻结；
3. **缺少时钟/复位/功耗章节的实质内容** —— 章节必须有，但内容尚未成熟；
4. **异常/流控合同 v0** 已补到 `docs/architecture/system_exception_and_flow_control_contract_v0.md`，但恢复策略与精确时序仍未冻结；
5. **`Phase C/D/E` 下沉合同** 已补到 `docs/control/qe_phase_cde_replay_bundle_contract_v0.md`，并已冻结为 `BODY_04A/B/C` catalog；
6. **缺少从系统规范到 block-level spec 的明确拆分边界。**

## 13. 下一步冻结顺序

当前最合理的推进顺序是：

1. 以本文为主设计总纲，继续把系统定义收束在主规范与少量支撑文档中；
2. 基于 `docs/architecture/system_interface_contract_v0.md` 与 `docs/architecture/system_exception_and_flow_control_contract_v0.md` 继续冻结异常、流控、计数器与恢复策略；
3. 先把 `Phase B` 从 `L1.5` 推向 `L2`：补齐 block 级 accept/busy/complete、queue depth、credit/backpressure 与资源争用；
4. 按 `docs/control/qe_phase_cde_replay_bundle_contract_v0.md` 把 `Phase C/D/E` 从 `L1` 进一步下沉到带结构统计的 replay bundle；
5. 在冻结的 `BODY_04A/B/C` 与 `BODY_10A/B/C` 之上继续细化 lowering、异常恢复与跨软件 mode 字段；
6. 再进入 block-level 微架构规格书编写与 `SystemC -> RTL` 风格细化。

## 14. 支撑文档关系图

当前本文与其他关键文档的关系如下：

- 原 `project_requirements`、`module spec` 与 `review packet` 的稳定内容已经并入本文，不再保留独立系统级主文档；
- `docs/control/long_control_word_isa_v0.md`
  - 作为统一的 `LCW` / descriptor / template / replay 控制主文档，并承载 `object handle / resident buffer / version` 的基础控制术语；
- `docs/architecture/system_interface_contract_v0.md`
  - 作为正式接口表、端点命名与 v0 route 合法集文档；
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
  - 作为异常、timeout、abort、backpressure 与错误升级合同文档；
- `docs/control/qe_phase_cde_replay_bundle_contract_v0.md`
  - 作为 `Phase C/D/E` 与 `BODY_04A/B/C` 下沉合同文档；
- `docs/control/body10_ot_block_update_contract_v0.md`
  - 作为 `CP2K/QS_OT` 的 `BODY_10` 运行时扩展合同文档；
- `docs/cim/cim_macro_block_and_timing_v0.md`
  - 作为 `CIM` 宏结构、计算流程与存储流程冻结文档；
- `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`
  - 作为 `resident_context`、`row_block` 与 `Near-SRAM` 协同接口冻结文档；
- `docs/control/qe_cbands_lcw_lowering_v0.md`
  - 作为 `QE c_bands -> replay/LCW` 的桥梁文档；
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`
  - 作为事务字段与行为合同文档；
- `docs/architecture/qe_full_dft_systemc_extension_outline_v0.md`
  - 作为 `qe_band_solver_model` 如何继续推广到完整 `SCF` skeleton 的扩展文档；
- `docs/architecture/qe_system_optimized_delta_20260413.md`
  - 作为最近一轮 optimized system-level redesign 的 delta 文档，明确 phase-1 public contract、family maturity 与哪些 claim 已更扎实；
- `model/qe_band_solver_model/README.md`
  - 作为当前可运行系统模型入口；
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
  - 作为 QE-only phase-1 thesis 的 workload-group roster 与 same-correctness / same-tolerance admission 合同；
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
  - 作为 `CPU + GPU` / `CPU + FPGA` shared-rewrite、公平比较、whole-node power 与 exact end-to-end accounting boundary 合同；
- `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md`
  - 作为 algorithm rewrite 的分类、GPU applicability、FPGA-only architectural rewrite 与 decisive baseline eligibility 合同；
- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`
  - 作为 phase-1 `CPU + GPU` baseline 的实际采集 runbook；
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
  - 作为 simulator/DSE ↔ FPGA board 的 observability / calibration 合同；
- `Survey/reports/2026-03-28-qe-vasp-cp2k-unified-flow-workload-matrix-v1.md`
  - 作为三软件统一流程/负载的外围证据。

## 15. 本文结论

当前最重要的不是再多写一批概念性碎文档，而是承认并维护以下事实：

- 我们已经拥有一套系统级架构主线；
- 这条主线的真实对象是 `Host + FPGA/runtime + Chip`；
- `QE` 已经足够支撑第一条可执行系统模型主线；
- `VASP/CP2K` 的价值主要在于约束顶层不要写偏；
- 现在最需要补的是“像硬件设计文档一样把系统写完整”，而不是再发散出更多概念层讨论。

从这个意义上说，本文之后应当被视为当前仓库的**主系统设计基线文档**。

## 16. 模块级实现规范冻结结果

从当前这一版开始，本文不再只停留在“六域分工”的抽象层，而是进一步冻结一套可直接落到 block-level 设计与 `SystemC` 行为级建模的模块树。

### 16.1 建议冻结的模块树

当前 chip 内建议冻结为：

```text
ChipTop
├─ CommandScheduler
├─ ResidentContextController
├─ NearMemoryDomain
│  └─ NearSRAMSupport
├─ FFTCompanion
├─ CIMEligibleOperatorSubchain
│  ├─ ContextLoader
│  ├─ DigitSerialInputBoundary
│  ├─ ConjugateSignSelector
│  ├─ NearSRAMCoeffBuffer
│  ├─ NearSRAMRowBuffer
│  └─ CIMArrayCore
│     ├─ Residue3MCore
│     ├─ CoefficientAccumulator
│     └─ RowMergeTree
├─ ReductionClosureEngine
└─ VectorDiagCompanion
```

这意味着：

- `CommandScheduler` 与 `ResidentContextController` 从“概念角色”提升为正式模块；
- `CIMArrayCore` 不再被视为一个无结构黑盒；
- `PROJECT -> near-SRAM coeff transform -> BACKPROJECT` 的组合关系被明确写成模块连接，而不是只写成一句叙事；
- `NearSRAMCoeffBuffer` 与 `NearSRAMRowBuffer` 被显式提升为数据流合同的一部分；
- `SystemC` 模型后续必须按这个模块树继续维护，而不是退回到单函数模拟。

### 16.2 每个模块的最小功能合同

当前最小合同建议冻结如下：

| 模块 | 最小稳定功能 | 最小输入对象 | 最小输出对象 |
| --- | --- | --- | --- |
| `CommandScheduler` | 发出 row-block 级 `LCW` 序列 | `EpisodeConfig`, `ResidentContextDesc` | `LCWCommand[]` |
| `ResidentContextController` | 绑定/释放常驻上下文与行窗 | `EpisodeConfig` | `ResidentContextDesc`, `RowBlockWindowDesc` |
| `NearSRAMSupport` | panel staging 与 partial 聚合 | panel 请求、`PartialHS[]` | `WavePanel`, `FullHS` |
| `ContextLoader` | row-block gather | `WavePanel`, `RowBlockWindowDesc` | row-window `WavePanel` |
| `DigitSerialInputBoundary` | digit-stream pack | row-window `WavePanel` | `DigitStreamSlice` |
| `ConjugateSignSelector` | 共轭/符号策略切换 | `DigitStreamSlice` / `ProjectCoeffPacket` | 调整后对象 |
| `Residue3MCore` | residue-domain complex MAC | `DigitStreamSlice` / coeff packet | `ProjectCoeffPacket` / `BackprojectRowPacket` |
| `CoefficientAccumulator` | 系数聚合与整形 | `ProjectCoeffPacket` | refined coeff packet |
| `RowMergeTree` | 行向量合并 | `BackprojectRowPacket` | `PartialHS` |
| `NearSRAMCoeffBuffer` | 系数暂存与小变换承接 | `ProjectCoeffPacket` | transformed coeff packet |
| `NearSRAMRowBuffer` | 行结果暂存与提交 | `PartialHS` | committed `PartialHS` |
| `ReductionClosureEngine` | `FullHS -> ReducedMatrices` | `FullHS` | `ReducedMatrices` |
| `VectorDiagCompanion` | `ReducedMatrices -> Ritz/Residual` | `ReducedMatrices` | `RitzResult`, `ResidualPacket` |
| `FFTCompanion` | `G<->R/reorder` 支撑 | `WavePanel` | transformed `WavePanel` |

### 16.3 当前对 CIM 模块的正式收口

当前对 `CIM` 的正式收口仍然是：

- 阵列方向：`projector-column-resident SRAM digital CIM`
- 阵列主原语：
  - `PROJECT`
  - `BACKPROJECT`
- 系统级 projector-family apply 形式：
  - `PROJECT -> near-SRAM coeff transform -> BACKPROJECT`

这一定义的意义在于：

1. 不再把完整 `H/S/nonlocal` 伪装成单个黑盒阵列模式；
2. 把近存缓冲与小变换路径正式纳入功能合同；
3. 为 `QE` 与 `CP2K` 的复用讨论留下结构化接口，而不是把相容性问题压给一个“万能阵列”。

### 16.4 对当前 `SystemC` 结构化模型的直接要求

从本节开始，当前仓库里的 `model/qe_band_solver_model/` 至少应满足：

- `EpisodeSummary` 显式追踪：
  - `resident_context_id`
  - `resident_generation`
  - `lcw_words_issued`
  - `row_blocks_processed`
  - `structural.model_level`
  - `structural.total_ref_cycles`
  - `structural.critical_domain`
  - `flow_control.total_backpressure_ref_cycles`
  - `flow_control.dominant_backpressure_route`
- `Phase B` 必须能够导出 `module occupancy`，至少覆盖：
  - `CommandScheduler`
  - `ResidentContextController`
  - `ContextLoader`
  - `DigitSerialInputBoundary`
  - `ConjugateSignSelector`
  - `Residue3MCore`
  - `CoefficientAccumulator`
  - `NearSRAMCoeffBuffer`
  - `RowMergeTree`
  - `NearSRAMRowBuffer`
  - `NearSRAMSupport`

### 16.5 模块间共性合同与分代冻结建议

在删去独立的 `LCW` 模块拆解文档之后，模块间必须共同满足的稳定结论统一并入这里：

#### 16.5.1 六域模块的共性系统合同

无论具体软件来自 `QE`、`CP2K` 还是后续 `VASP`，当前六域模块都必须共同满足以下系统级合同：

- **object handle 一致性**：同一 `object handle` 在任一时刻只能绑定一个有效拥有者；跨 `PROJECT/BACKPROJECT/solve/update` 传递时，版本号与驻留标签必须同步前进；
- **phase 一致性**：`Phase A-E/Bx` 的进入、完成和回写边界必须由 `CommandScheduler` 与运行时共同显式维护，不能退回到“默认按函数顺序完成”；
- **route 合法性**：`LCW` 允许的 route 只能落在已登记的端点组合上，模块不能隐式旁路未声明的数据路径；
- **异步 / join 语义**：允许局部异步，但必须保留 `soft join / hard barrier / fence` 三类最小完成语义；
- **局部 replay 能力**：`BODY_04`、`BODY_10` 以及后续扩展 family，都应先以 bundle 级 replay 进入系统，而不是把新软件压力直接压成新的硬编码时序。

#### 16.5.2 各模块的扩展压力判断

当前最稳的扩展判断如下：

- `CommandScheduler`：最直接承受跨软件 replay family 扩张、依赖管理与 mode-switch 压力；
- `CIM / Projector-Apply Engine`：承受 `projector-family apply` 的数值模式扩展，但不应被要求吞下完整外层 `H/S/nonlocal` 语义；
- `FFT Engine`：主要承受不同软件下 `G<->R/reorder` 模式差异，而不是承担主控制；
- `Near-SRAM Support Domain`：承受对象驻留、行窗切换、局部变换和结果冻结的一致性压力；
- `Reduction / Closure / Solve Engine`：承受 reduced problem 形态差异与 companion/fallback 策略压力；
- `SIMD / Vector Companion`：承受额外向量后处理、预条件、残差更新和软件兼容策略压力。

#### 16.5.3 `v0 / v1 / v2` 冻结建议

- **`v0` 必须冻结**：六域模块树、最小功能合同、`object handle` 一致性、合法 route 集、`soft join / hard barrier / fence` 语义、`QE` 主线下的 `PROJECT -> near-SRAM coeff transform -> BACKPROJECT` 主链；
- **`v1` 建议补强**：更细的 queue depth / credit / backpressure 统计，冻结 catalog 下各 sub-body 的 lowering / object 字段，`CP2K/VASP` 模式切换字段，更多 `leaf-block accept/busy/complete` 暴露；
- **`v2` 才考虑冻结**：更激进的跨软件统一 body catalog、更深的自动 lowering、以及面向最终 RTL 的精确资源仲裁与 QoS 策略。

### 16.5.4 当前 `Phase B` leaf-block implementation contract

为了把 `Phase B` 从“有模块名和忙闲统计”进一步推进到更像硬件包的正式设计对象，当前把已经进入行为级模型的 leaf-block 合同收口如下：

| leaf block | 当前主链位置 | 当前模块职责 | 输入对象 / 状态 | 输出对象 / 状态 | 局部完成点 | 参考 busy 周期 |
| --- | --- | --- | --- | --- | --- | --- |
| `NearSRAMSupport.stage_panel` | panel ingress | 把 panel 对象装入近存 stage 域 | panel request valid | staged `WavePanel` ready | `FFTCompanion.ingress` 或 `ContextLoader.panel_ingress` | `6` |
| `FFTCompanion.Transform` | optional panel transform | 执行 `G<->R/reorder` 相关预处理 | staged `WavePanel` ready | transformed `WavePanel` ready | `ContextLoader.panel_ingress` | `5` |
| `ContextLoader` | row-window gather | 从 panel + row-block 生成 row-window | `WavePanel = READY`, `RowBlockWindowDesc = READY` | row-window ready | `DigitSerialInputBoundary.digit_pack_fifo` | `2` |
| `DigitSerialInputBoundary` | input packing | 把 row-window 打成 digit stream | row-window ready | `DigitStreamSlice` ready | `ProjectConjugateSignSelector.project_policy_slot` | `2` |
| `ProjectConjugateSignSelector` | project policy select | 应用 `PROJECT` 共轭/符号策略 | `DigitStreamSlice` ready | project slice ready | `Residue3MCore.PROJECT.ingress_lane` | `1` |
| `Residue3MCore.PROJECT` | project MAC | 完成 residue-domain `PROJECT` 乘累加 | project slice ready | `ProjectCoeffPacket` ready | `CoefficientAccumulator.coeff_hold_reg` | `6` |
| `CoefficientAccumulator` | coeff refinement | 系数聚合与整形 | `ProjectCoeffPacket` ready | refined coeff ready | `NearSRAMCoeffBuffer.coeff_fifo` | `3` |
| `NearSRAMCoeffBuffer` | coeff near-SRAM path | 系数暂存与小变换承接 | refined coeff ready | transformed coeff ready | `BackprojectConjugateSignSelector.backproject_policy_slot` | `4` |
| `BackprojectConjugateSignSelector` | backproject policy select | 应用 `BACKPROJECT` 共轭/符号策略 | transformed coeff ready | backproject coeff ready | `Residue3MCore.BACKPROJECT.ingress_lane` | `1` |
| `Residue3MCore.BACKPROJECT` | backproject MAC | 完成 residue-domain `BACKPROJECT` 乘累加 | backproject coeff ready | `BackprojectRowPacket` ready | `RowMergeTree.partial_row_fifo` | `6` |
| `RowMergeTree` | row reduction | 把行级 partial 合并成 `PartialHS` | `BackprojectRowPacket` ready | `PartialHS` ready | `NearSRAMRowBuffer.row_fifo` | `3` |
| `NearSRAMRowBuffer` | partial commit | 提交 `PartialHS` 到近存聚合边界 | `PartialHS` ready | committed `PartialHS` ready | `NearSRAMSupport.aggregate.partial_ingress` | `3` |
| `NearSRAMSupport.aggregate` | body-02 ingress | 聚合 `PartialHS[]` 形成 `FullHS` | committed `PartialHS[]` ready | `FullHS` ready | `ReductionClosureEngine.input_fifo` | `8` |
| `ReductionClosureEngine.InputAssembler` | closure input | 组装 reduced closure 输入描述 | `FullHS` ready | closure matrix tiles ready | `ReductionClosureEngine.closure_fifo` | `4` |
| `ReductionClosureEngine.HermitianClosureBuilder` | closure build | 构建 Hermitian/generalized reduced matrices | closure matrix tiles ready | reduced matrices ready | `ReductionClosureEngine.solve_frontend_fifo` | `4` |
| `ReductionClosureEngine.SmallSolveFrontEnd` | solve frontend | small solve 前端准备与描述导出 | reduced matrices ready | solve descriptor ready | `VectorDiagCompanion.solve_ingress` | `2` |
| `VectorDiagCompanion.RitzUpdate` | body-03 ingress | 形成 `RitzResult` / `ResidualPacket` 与刷新对象 | solve descriptor ready | residual refresh packet ready | `BODY_03.commit_boundary` | `7` |

这张表当前冻结的是：

- `Phase B` 已经具备正式的 leaf-block 边界，而不只是一个巨大的 `BODY_01-03` 黑盒；
- 每个 leaf block 的输入条件、输出落点、局部完成边界和当前 proxy 周期已经明确；
- 后续 `RTL` 细化应该继续保持这些模块边界，而不是把 `PROJECT/BACKPROJECT/solve/update` 重新揉回单一过程函数。

### 16.5.5 当前 `Phase B` block-level port / local-state / flow-control contract

在 `16.5.4` 的 leaf-block implementation contract 之上，当前再冻结一层更接近硬件规格书的 block package 合同。

这里的 `ingress_owner / egress_owner` 有两层意义：

- 一方面它们对应当前行为级模型已经在日志里暴露、或应继续保持的 block 边界名字；
- 另一方面它们也是后续 `RTL` / `SystemC` 子模块继续细化时最不应该漂移的端口边界。

需要明确的是：

- 下面的表不是最终 `ready/valid` 波形规范；
- 但它已经冻结了每个 block 应该保留的输入边界、输出边界、局部状态与 `accept / busy / complete` 切分位置；
- 后续任何实现细化，都不应把这些边界重新揉回一个模糊的大过程函数。

#### 16.5.5.1 控制与 resident-context block package

| block | ingress owner -> egress owner | 必留局部状态 | `accept / busy / complete` 合同 | 当前模型可见性 |
| --- | --- | --- | --- | --- |
| `CommandScheduler` | `BODY_01.issue_boundary + ResidentContextController.ready_boundary -> LCW_ISSUE_WINDOW` | `resident_context_id`, `resident_generation`, `inner_step`, `row_block_cursor`, `active_mod_group_mask`, `fft_mode` | `accept` = resident context 已 `READY` 且 issue window 仍有 credit；`busy` = 正在逐 row-block 发射 `LCWCommand` 或被 issue hold；`complete` = 当前 inner-step 所有 `row_block_id` 已发射完成 | 当前已有 `CommandScheduler issued N LCW words` 事件日志与 `module occupancy`，尚未单独导出 `flow stage` 行 |
| `ResidentContextController` | `BODY_01.context_request -> ResidentContextDesc.ready_boundary / RowBlockWindowDesc.issue_boundary / context_release_ack` | `resident_context_id`, `generation`, `row_block_count`, `column_group_count`, `resident_words`, `lifecycle_state`, `row_begin`, `row_count`, `conjugate_policy`, `fft_preconditioned` | `accept` = bind 时 context slot 可用，open 时当前 context 已 `READY` 且 row-block cursor 合法，release 时所有 row-block 已退休；`busy` = bind/open/release 任一事务进行中；`complete` = `ResidentContextDesc` 或 `RowBlockWindowDesc` 已稳定导出，或 context 已释放 | 当前已有 `bind/open/release` 事件日志与 `module occupancy`，尚未单独导出 `flow stage` 行 |

#### 16.5.5.2 panel ingress / projector-apply / near-SRAM row path block package

| block | ingress owner -> egress owner | 必留局部状态 | `accept / busy / complete` 合同 | 仲裁域 / 当前边界 |
| --- | --- | --- | --- | --- |
| `NearSRAMSupport.stage_panel` | `LCW_ISSUE_WINDOW -> FFTCompanion.Transform` 或 `ContextLoader.panel_ingress` | `panel_id`, `resident_slot`, `panel_size`, `amplitude_norm`, `support_grid_mode` | `accept` = panel request valid 且 stage slot 可装入；`busy` = panel fill / stage commit 进行中；`complete` = staged `WavePanel` 已提交到 `FFT` 或 `ContextLoader` ingress | `PANEL_STAGE_DOMAIN`；当前有 `module occupancy` 与 backpressure route，但尚未单独导出 `flow stage` 行 |
| `FFTCompanion.Transform` | `FFTCompanion.ingress -> ContextLoader.panel_ingress` | `fft_mode`, `panel_id`, `spectral_view_valid`, `reorder_phase` | `accept` = staged panel ready；`busy` = `G<->R/reorder` 变换进行中；`complete` = transformed `WavePanel` ready | `FFT_SHARED_DOMAIN`；当前有 `module occupancy` 与 backpressure route，但尚未单独导出 `flow stage` 行 |
| `ContextLoader` | `ContextLoader.row_window_fifo -> DigitSerialInputBoundary.digit_pack_fifo` | `panel_id`, `resident_slot`, `row_begin`, `row_count`, `mod_group_mask` | `accept_cond=row_window_fifo_not_full`；`busy_cond=context_loader_busy_or_output_hold`；`complete_cond=row_window_ready_for_digit_pack` | `ROW_WINDOW_DOMAIN` / `ROW_WINDOW_LOAD` |
| `DigitSerialInputBoundary` | `DigitSerialInputBoundary.digit_pack_fifo -> ProjectConjugateSignSelector.project_policy_slot` | `panel_id`, `row_block_id`, `digit_count`, `magnitude_checksum` | `accept_cond=digit_pack_fifo_not_full`；`busy_cond=digit_serial_pack_busy_or_output_hold`；`complete_cond=digit_stream_slice_ready` | `DIGIT_STREAM_DOMAIN` / `DIGIT_STREAM_PACK` |
| `ProjectConjugateSignSelector` | `ProjectConjugateSignSelector.project_policy_slot -> Residue3MCore.PROJECT.ingress_lane` | `conjugate_policy`, `digit_checksum`, `project_mode` | `accept_cond=project_policy_slot_free`；`busy_cond=project_policy_logic_busy_or_output_hold`；`complete_cond=project_conjugate_policy_applied` | `PROJECT_SELECTOR_DOMAIN` / `PROJECT_POLICY_SELECT` |
| `Residue3MCore.PROJECT` | `Residue3MCore.PROJECT.ingress_lane -> CoefficientAccumulator.coeff_hold_reg` | `resident_context_id`, `resident_generation`, `row_block_id`, `column_group_count`, `coeff_energy`, `coeff_condition` | `accept_cond=project_mac_lane_available`；`busy_cond=project_residue_mac_busy_or_output_hold`；`complete_cond=project_coeff_packet_ready` | `PROJECT_ARRAY_DOMAIN` / `PROJECT_RESIDUE_MAC` |
| `CoefficientAccumulator` | `CoefficientAccumulator.coeff_hold_reg -> NearSRAMCoeffBuffer.coeff_fifo` | `coeff_energy`, `coeff_condition`, `row_count`, `scf_iteration` | `accept_cond=coeff_accum_slot_free`；`busy_cond=coeff_accum_busy_or_output_hold`；`complete_cond=coeff_accumulation_complete` | `COEFF_ACCUM_DOMAIN` / `COEFF_ACCUMULATE` |
| `NearSRAMCoeffBuffer` | `NearSRAMCoeffBuffer.coeff_fifo -> BackprojectConjugateSignSelector.backproject_policy_slot` | `coeff_energy`, `coeff_condition`, `resident_generation`, `band_count`, `transform_mode` | `accept_cond=coeff_buffer_slot_free`；`busy_cond=coeff_buffer_transform_busy_or_output_hold`；`complete_cond=coeff_transform_complete` | `COEFF_BUFFER_DOMAIN` / `COEFF_RESHAPE` |
| `BackprojectConjugateSignSelector` | `BackprojectConjugateSignSelector.backproject_policy_slot -> Residue3MCore.BACKPROJECT.ingress_lane` | `conjugate_policy`, `coeff_condition`, `backproject_mode` | `accept_cond=backproject_policy_slot_free`；`busy_cond=backproject_policy_logic_busy_or_output_hold`；`complete_cond=backproject_policy_applied` | `BACKPROJECT_SELECTOR_DOMAIN` / `BACKPROJECT_POLICY_SELECT` |
| `Residue3MCore.BACKPROJECT` | `Residue3MCore.BACKPROJECT.ingress_lane -> RowMergeTree.partial_row_fifo` | `resident_context_id`, `resident_generation`, `row_block_id`, `row_energy`, `overlap_energy` | `accept_cond=backproject_mac_lane_available`；`busy_cond=backproject_residue_mac_busy_or_output_hold`；`complete_cond=backproject_row_packet_ready` | `BACKPROJECT_ARRAY_DOMAIN` / `BACKPROJECT_RESIDUE_MAC` |
| `RowMergeTree` | `RowMergeTree.partial_row_fifo -> NearSRAMRowBuffer.row_fifo` | `panel_id`, `h_contrib`, `s_contrib`, `local_condition` | `accept_cond=row_merge_slot_free`；`busy_cond=row_merge_busy_or_output_hold`；`complete_cond=partial_hs_ready` | `ROW_MERGE_DOMAIN` / `ROW_REDUCE` |
| `NearSRAMRowBuffer` | `NearSRAMRowBuffer.row_fifo -> NearSRAMSupport.aggregate.partial_ingress` | `h_partial`, `s_partial`, `resident_generation`, `commit_epoch` | `accept_cond=row_buffer_slot_free`；`busy_cond=row_buffer_commit_busy_or_output_hold`；`complete_cond=partial_commit_complete` | `ROW_BUFFER_DOMAIN` / `PARTIAL_COMMIT` |

#### 16.5.5.3 closure / solve / writeback block package

| block | ingress owner -> egress owner | 必留局部状态 | `accept / busy / complete` 合同 | 仲裁域 / 当前边界 |
| --- | --- | --- | --- | --- |
| `NearSRAMSupport.aggregate` | `NearSRAMSupport.aggregate.partial_ingress -> ReductionClosureEngine.input_fifo` | `partial_count`, `h_total`, `s_total`, `locality_score`, `episode_id` | `accept` = partial row committed 且 aggregate slot 可继续收集；`busy` = `PartialHS[] -> FullHS` 聚合进行中；`complete` = `FullHS` ready | `CLOSURE_INPUT_DOMAIN`；当前有 `module occupancy` 与 backpressure route，但尚未单独导出 `flow stage` 行 |
| `ReductionClosureEngine.InputAssembler` | `ReductionClosureEngine.input_fifo -> ReductionClosureEngine.closure_fifo` | `full_hs_snapshot`, `reduced_dim`, `matrix_tile_cursor` | `accept_cond=closure_input_fifo_not_full`；`busy_cond=closure_input_assemble_busy_or_output_hold`；`complete_cond=closure_matrix_tiles_ready` | `CLOSURE_ENGINE_DOMAIN` / `CLOSURE_INPUT_ASSEMBLE` |
| `ReductionClosureEngine.HermitianClosureBuilder` | `ReductionClosureEngine.closure_fifo -> ReductionClosureEngine.solve_frontend_fifo` | `h_small`, `s_small`, `closure_score`, `generalized_mode` | `accept_cond=closure_builder_slot_free`；`busy_cond=closure_builder_busy_or_output_hold`；`complete_cond=hermitian_reduced_matrices_ready` | `CLOSURE_ENGINE_DOMAIN` / `HERMITIAN_CLOSURE_BUILD` |
| `ReductionClosureEngine.SmallSolveFrontEnd` | `ReductionClosureEngine.solve_frontend_fifo -> VectorDiagCompanion.solve_ingress` | `reduced_dim`, `solve_mode`, `descriptor_valid` | `accept_cond=solve_frontend_slot_free`；`busy_cond=small_solve_frontend_busy_or_output_hold`；`complete_cond=reduced_matrix_descriptor_ready` | `SMALL_SOLVE_DOMAIN` / `SMALL_SOLVE_PREP` |
| `VectorDiagCompanion.RitzUpdate` | `VectorDiagCompanion.solve_ingress -> BODY_03.commit_boundary` | `eigenpair_count`, `et`, `evc_norm`, `residual_norm`, `updates_applied`, `episode_done` | `accept_cond=vector_diag_slot_free`；`busy_cond=vector_diag_busy_or_output_hold`；`complete_cond=residual_refresh_packet_ready` | `VECTOR_DIAG_DOMAIN` / `RITZ_UPDATE` |

#### 16.5.5.4 当前 block-level 合同真正冻结了什么

本小节真正冻结的是：

- `Phase B` 现在不只是“有 leaf-block 名字”，而是已经有每个 block 的 ingress / egress owner；
- 每个 block 必须保留的局部状态已经明确，不允许后续细化时把状态偷偷漂移到邻接模块；
- `accept / busy / complete` 的切分位置已经固定，后续只允许细化信号，不允许重新改写语义边界；
- `CommandScheduler`、`ResidentContextController`、`NearSRAMSupport.stage_panel`、`FFTCompanion.Transform`、`NearSRAMSupport.aggregate` 虽然还未全部像中间链路那样打印 `flow stage` 行，但其 block-level 合同已经先在系统规格层冻结。

### 16.5.6 下一层 `L2` 细化目标

当前 `Phase B` 已经有 leaf-block 流控代理，但下一层 `L2` 细化目标必须明确写出且不能伪装成“已完成”：

- 冻结后的 ingress/egress queue 或 credit 资源；
- route 冲突与 backpressure 的仲裁规则；
- 多 issue-source 进入同一 leaf block 时的仲裁顺序；
- 跨 inner-step / 跨 batch 的并发重叠；
- `NearSRAMSupport / FFT / CIM / Solve / Vector` 五域之间是否允许更细粒度 overlap。

## 17. QE / CP2K 统一计算流程与 replay 映射

### 17.1 `QE` 主路径

当前 `QE` 路线已经有真实执行证据支持，主流程仍保持：

- `Phase A`：setup / seed / bind
- `Phase B`：`c_bands` episode
- `Phase C`：`sum_band`
- `Phase D`：`v_of_rho / newd`
- `Phase E`：`mix_rho / convergence gate`

其中 `Phase B` 当前冻结为：

- `BODY_01`：projector/operator apply body
- `BODY_02`：reduced closure / solve body
- `BODY_03`：refresh / compact / rebind body

### 17.2 `CP2K` 主路径

当前 `CP2K` 仍属于**源码/benchmark 驱动的非执行恢复对象**，但已经可以明确恢复出两条主要路线：

- `Quickstep DIAG` 路线
- `Quickstep OT` 路线

二者共同共享：

- `SCF` 外层驱动；
- grid / FFT / Poisson 支撑域；
- 某种 form 的 closure / solve / update；
- mixing / convergence gate。

但二者不同之处在于：

- `DIAG` 更容易映射到 `QE` 当前的 closure / solve 主线；
- `OT` 明显引入更强的 `DBCSR` / block-sparse / AO-mixed 对象压力。

### 17.3 当前建议冻结的跨软件 replay body catalog

当前建议先把跨软件 replay body catalog 收口到：

| body / family | QE | CP2K DIAG | CP2K OT | 当前状态 |
| --- | --- | --- | --- | --- |
| `BODY_00` seed/bind | 直接适用 | 直接适用 | 直接适用 | 稳定 |
| `BODY_01` projector/operator apply | 直接适用 | 部分适用 | 部分适用 | 稳定 |
| `BODY_02` reduced closure / solve | 直接适用 | 直接适用 | 仅部分适用 | 稳定 |
| `BODY_03` refresh / compact / rebind | 直接适用 | 直接适用 | 需要扩展 | 稳定 |
| `BODY_04_FAMILY` | 直接适用 | 直接适用 | 直接适用 | 稳定 alias |
| `BODY_04A` density accumulation | 直接适用 | 直接适用 | 直接适用 | 稳定 |
| `BODY_04B` potential / nonlocal refresh | 直接适用 | 直接适用 | 直接适用 | 稳定 |
| `BODY_04C` mixing / convergence gate | 直接适用 | 直接适用 | 直接适用 | 稳定 |
| `BODY_05` outer episode / SCF control | 直接适用 | 直接适用 | 直接适用 | 稳定 |
| `BODY_10_FAMILY` | 不强需求 | 候选 | 已有行为级映射 | 稳定 alias |
| `BODY_10A` OT preconditioned update | 不强需求 | 候选 | 已有行为级映射 | 稳定 |
| `BODY_10B` OT orthogonalize / rebind | 不强需求 | 候选 | 已有行为级映射 | 稳定 |
| `BODY_10C` OT history / summary commit | 不强需求 | 候选 | 已有行为级映射 | 稳定 |

因此，当前更稳妥的判断不是“我们已经完全兼容了 `CP2K`”，而是：

- 现有 `QE` 模型已经定义了可以被 `CP2K DIAG` 明显复用的一条主链；
- `CP2K OT` 已经不再只停留在 `BODY_10` family 入口，而是具备 `10A/B/C` 级别的正式 body catalog；
- 更深的 block-sparse / AO object catalog 仍然存在，但它们应属于 `BODY_10A/B/C` 之下，而不是继续膨胀成新的 system-visible body 编号；
- `VASP` 当前更像是通过 `solver_mode / band_batch / support_grid_mode` 这些 descriptor 字段进入统一骨架，而不是首先引入新的 body 编号；
- 顶层应该保持 `LCW + replay body` 风格，而不是过早收死成只服务 `QE` 的刚性流水。

### 17.4 当前最稳的跨软件结论

当前最稳的结论依然是：

- `QE` 是执行锚点；
- `CP2K` 是顶层控制与对象模型的重要约束源；
- 芯片顶层最该冻结的是：
  - `descriptor -> replay body -> LCW`
  - resident/context 合同
  - shared `FFT / reduction / solve` 支撑域
  - projector-family `PROJECT/BACKPROJECT` 子链

## 18. 当前实现状态与下一步

### 18.1 当前已经完成到哪一步

从本文当前版本开始，可以把“系统设计已经完成到哪一步”更明确地写成：

1. 真实系统对象已稳定为：`Host + FPGA/runtime + Chip`；
2. `QE Phase A-E` 主流程已经稳定；
3. `CP2K Quickstep DIAG/OT` 的源码级主流程已经恢复到可以约束顶层设计；
4. block-level 模块树已经冻结到可以直接驱动 `SystemC` 细化；
5. `CIM` 的主方向已经收口到 `projector-column-resident SRAM digital CIM`；
6. `PROJECT -> near-SRAM coeff transform -> BACKPROJECT` 已经成为正式数据流合同，而不只是概念提法。

### 18.2 当前还没有冻结的内容

仍未冻结的核心问题包括：

- `BODY_04A/B/C` 各自是否继续下沉成更强 chip-autonomous body；
- `CP2K OT` 在 `BODY_10A/B/C` 之下更深一层 sparse/block-object update 的具体合同；
- `VASP` 的 `support-grid` / `mode-switch` 字段是否继续扩成正式 bundle/body 语义；
- 阵列尺寸、bank 规模、row-merge 带宽、context switch cost 的定量冻结；
- 时钟/复位/功耗域的正式实现规格。

### 18.3 当前最合理的推进顺序

在完成本版 block-level 规格和细粒度 `SystemC` 行为级骨架后，当前推进顺序已经从“继续做更深的 catalog 冻结”切换为“先做系统级 modeling 探索”。

当前最合理的顺序是：

1. 先把 `QE` 主线里的一个完整 `SCF iteration shell` 作为系统对象显式建模：
   - `rho -> Veff`
   - `while bands not converged:`
     - `h_psi`
     - `s_psi`
     - `build H_sub / S_sub`
     - `cdiaghg`
     - `refresh / residual -> P_next`
   - `psi -> rho_out`
2. 在这个 shell 里优先探索 **Host / FPGA / Chip** 三层之间的真实对象驻留、边界数据量和 episode contract，而不是先把更深一层 `BODY_04/10` lowering 全部写死；
3. 第一版建模允许把 `cdiaghg` 暂时保留在 `CPU / soft-core companion solver` 一侧，把主精力放在 `h_psi / s_psi + subspace build + refresh/residual` 的系统闭环上；
4. 等 shell-level 数据流、resident object、buffer turnover 和边界传输关系稳定之后，再回头决定：
   - `cdiaghg` 是否继续下沉；
   - `BODY_04A/B/C` 与 `BODY_10A/B/C` 是否需要更强 chip-autonomous 化；
   - 哪些 route / assist-engine / exception path 值得继续冻结到 `RTL` 风格规格。

### 18.4 当前阶段切换说明

这一步需要明确说明：

- 当前阶段**不是**继续沿着上一阶段的思路，把更多精力先投入到更深的 body catalog 冻结；
- 当前阶段**也不是**立即进入精确 `RTL` 风格资源预算；
- 当前阶段的核心，是先把真实 `QE` 主路径里的 `SCF iteration shell` 当成一个可建模、可分区、可统计边界流量的系统对象。

换句话说，当前仓库正在进入的是：

> `modeling / system exploration phase`

这一阶段最重要的输出不是最终微架构，而是下面三类系统级结论：

1. 哪些对象应该常驻在 `Chip / FPGA` 一侧；
2. `CPU <-> FPGA <-> Chip` 边界上每一轮真正需要传的是什么；
3. `h_psi / s_psi / build / refresh` 与 `cdiaghg` 的系统切分点应该放在哪里。


## 19. 完整系统模型与 `BODY_04` 运行时下沉状态

从当前版本开始，仓库里的 `SystemC` 行为级模型已经不再只是“`Phase B` 的 band-solver 子系统 demo”，而是一个更完整的系统对象：

- `DFTHybridSystem`
  - `HostSCF`
  - `FPGAOrchestrator`
    - `ReplayBundleExecutor`
      - `Body04FamilyController`
        - `OuterUpdateRuntimeDomain`
      - `Body10FamilyController`
  - `ChipTop`

### 19.1 运行时层的新增冻结点

当前 `FPGA/runtime` 层已经不再只是“下发 `BODY_01/BODY_02/BODY_03`”。

当前更准确的实现关系是：

- `FPGAOrchestrator` 作为 Host 可见的 runtime facade；
- `ReplayBundleExecutor` 统一执行 `BODY_01_03_REPLAY`、`BODY_10_FAMILY`、`BODY_04_FAMILY`；
- `ChipTop::run_replay_bundle(...)` 承接 `Phase B` 的行为级 chip-side bundle 入口；
- `Body04FamilyController -> OuterUpdateRuntimeDomain` 承接 `BODY_04` 的运行时域下沉；
- `Phase B -> BODY_10A/B/C -> BODY_04A/B/C` 之间的对象交接已经显式化；
- `BODY_04` 内部 stage request / stage summary / lowering plan 的生成已经显式化；
- `Host` 可见的 convergence / continue 汇总与全流程 `DFTRunReport` 已经显式化。

这意味着当前系统现在可以更准确地写成：

```text
Host/BODY_05
  -> FPGAOrchestrator lowers replay bundle
  -> ReplayBundleExecutor dispatches BODY_01_03_REPLAY
  -> ChipTop executes Phase B via run_replay_bundle(...)
  -> optional ReplayBundleExecutor dispatches BODY_10_FAMILY
  -> ReplayBundleExecutor dispatches BODY_04_FAMILY
  -> Body04FamilyController forwards to OuterUpdateRuntimeDomain
  -> Host observes convergence decision and DFTRunReport
```

### 19.2 `BODY_04/10` catalog 的当前实现状态

当前 `BODY_04` 已经不再只是一个未拆分 family，而是：

- family 层保留 `BODY_04_FAMILY` alias；
- body 层正式冻结为 `BODY_04A/B/C`；
- `BODY_04A/B/C` 分别映射到 `density / potential / mixing` 三段运行时域；
- 叶块层继续由各自 stage 的 `accept/busy/complete` 与 `reference-cycle` 摘要承接。

其当前实现映射为：

- `BODY_04A`
  - `DensityAccumulationStage`
  - `DensityAccumulatorUnit`
  - `DensityCommitUnit`
- `BODY_04B`
  - `PotentialRefreshStage`
  - `PotentialFieldUnit`
  - `ProjectorStateUpdater`
- `BODY_04C`
  - `MixingConvergenceStage`
  - `DensityMixerUnit`
  - `ConvergenceTracker`

并统一挂到：

- `Body04FamilyController`
- `OuterUpdateRuntimeDomain`
- `ReplayBundleExecutor`

同时，`BODY_10` 也已经从单一扩展入口收口成：

- family 层保留 `BODY_10_FAMILY` alias；
- body 层正式冻结为 `BODY_10A/B/C`；
- `Body10FamilyController` 负责推进 `preconditioned update -> orthogonalize/rebind -> history commit`；
- `BODY_10A`
  - `PreconditionedUpdateVector`
  - `WaveCandidateCommit`
- `BODY_10B`
  - `OrthogonalizeUnit`
  - `RebindCommit`
- `BODY_10C`
  - `HistoryIntegrator`
  - `OTSummaryCommit`

因此，当前更准确的表述应当是：

- 文档层：`BODY_04A/B/C` 与 `BODY_10A/B/C` 都已冻结为正式 body catalog；
- 模型层：它们仍主要处在 runtime-managed、timed-functional、带叶块流控代理的层次；
- 未冻结层：更深的 route、assist-engine、sparse-object 与 `LCW` micro-sequence 细节仍在 body 之下。

### 19.2.1 当前已冻结的 `BODY_04A/B/C` 与 `BODY_10A/B/C` 控制姿态

为了避免主规格书里继续把这两组 body 写成“只有 family 名”的过渡对象，当前把最关键的控制姿态直接并到总规范：

| sub-body | `template_id` | `completion_mode` | `join_mode` | `replay_policy` | 当前主 route skeleton |
| --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `TPL_BODY_04A_DENSITY_ACCUM_V0` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `R29 -> R31 -> R32` |
| `BODY_04B` | `TPL_BODY_04B_POTENTIAL_REFRESH_V0` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `R01/R02/R03/R34` 或 `R29`，再接 `R31/R32/R33` |
| `BODY_04C` | `TPL_BODY_04C_MIX_CONVERGE_V0` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `R29/R30 -> R31 -> R32/R33` |
| `BODY_10A` | `TPL_BODY_10A_PRECOND_UPDATE_V0` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `R29 -> R36` |
| `BODY_10B` | `TPL_BODY_10B_ORTHO_REBIND_V0` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `R35/R30 -> R31 -> R32/R33` |
| `BODY_10C` | `TPL_BODY_10C_HISTORY_COMMIT_V0` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `R29/R30 -> R31 -> R33` |

这张表表达的不是最终 `RTL` 编码，而是已经冻结的系统可见控制边界：

- `BODY_04A/B` 与 `BODY_10A/B` 仍然是严格的对象提交边界；
- `BODY_04C` 与 `BODY_10C` 是 outer decision / history summary 的查询边界；
- 六个 sub-body 都不允许在 chip 内自行膨胀出新的未编号 replay 环；
- deeper sparse / assist-engine / kernel lowering 继续留在 body-local 合同里。

### 19.2.2 当前 canonical stage-to-unit / object-flow

为了让这两组 body 更像硬件系统文档里的正式执行对象，而不是停留在“名字 + 口头语义”，当前把 stage-route、对象交接和叶块职责并表如下：

| sub-body | stage route / residency | 输入对象 -> 输出对象 | 叶块执行链 | 当前可观测摘要 |
| --- | --- | --- | --- | --- |
| `BODY_04A` | `SIMD|NEAR_SRAM_ACCUM`, `WAVE_STREAM_IN->DENSITY_BUFFER_COMMIT` | `wave_object + density_context -> density_object` | `DensityAccumulatorUnit.Reduce -> DensityCommitUnit.Commit` | `density_stage.ref_cycles`、`bp_ref_cycles`、critical unit |
| `BODY_04B` | `FFT|SIMD|NEAR_SRAM` 或 `SIMD|NEAR_SRAM`, `DENSITY_READ->GRID_REFRESH->PROJECTOR_STATE_COMMIT` / `DENSITY_READ->PROJECTOR_STATE_COMMIT` | `density_object + projector_state -> potential_object + projector_state_next` | `PotentialFieldUnit.Build -> ProjectorStateUpdater.Update` | `potential_stage.ref_cycles`、grid-mode 相关 latency、critical unit |
| `BODY_04C` | `SIMD|SCF_CONTROL`, `DENSITY_MIX->HISTORY_COMMIT` | `density_object + potential/history -> mixed_density + scf_decision/history_next` | `DensityMixerUnit.Mix -> ConvergenceTracker.Decide` | `mixing_stage.ref_cycles`、queryable decision、dominant backpressure |
| `BODY_10A` | `SIMD|SRAM_STAGE`, `PHASE_B_WAVE_IN->WAVE_CANDIDATE_STAGE` | `phase-B wave + residual -> wave_candidate_object(STAGED)` | `PreconditionedUpdateVector.Apply -> WaveCandidateCommit.Commit` | `precond_stage.ref_cycles`、update_norm、critical unit |
| `BODY_10B` | `SIMD|SRAM_STAGE|SRAM_META`, `WAVE_CANDIDATE_READ->REBOUND_WAVE_COMMIT->PROJECTOR_STATE_COMMIT` | `wave_candidate + projector/metric -> updated_wave + updated_projector` | `OrthogonalizeUnit.Project -> RebindCommit.Commit` | `ortho_stage.ref_cycles`、orthogonality_score、critical unit |
| `BODY_10C` | `SIMD|SRAM_META|SCF_CONTROL`, `HISTORY_READ->SUMMARY_COMMIT` | `updated_wave + history_object -> search_history + decision_summary` | `HistoryIntegrator.Commit -> OTSummaryCommit.Export` | `history_stage.ref_cycles`、accepted/rejected summary、query boundary |

这张表当前冻结了三层含义：

- body 级输入输出对象已经和 stage 级执行链对齐，避免“一个 body 内到底谁生产谁消费”继续含糊；
- `BODY_04A/B/C` 与 `BODY_10A/B/C` 的 stage 责任已经落到具体 leaf block，后续可以直接往 block-level spec 和 `SystemC` 子模块推进；
- 当前可观测量已经不只是 bundle 完成与否，还包括 stage 级 `reference-cycle`、`backpressure`、critical unit 和 query boundary。

### 19.2.3 当前 `BODY_04/10` leaf-block implementation contract

为了继续把系统对象往 block-level spec 收口，当前至少把已经进入行为级模型的叶块实现要求冻结到下面这个粒度：

| leaf block | 所属 sub-body | 当前模块职责 | 输入对象 / 状态 | 输出对象 / 状态 | 局部完成点 | 参考 busy 周期 |
| --- | --- | --- | --- | --- | --- | --- |
| `DensityAccumulatorUnit.Reduce` | `BODY_04A` | 从 phase-B wave 对象形成 density partial | `wave_object = READY` | density partial ready | `DensityCommitUnit.commit_fifo` | `8` |
| `DensityCommitUnit.Commit` | `BODY_04A` | 提交 `density_new_handle` | density partial ready | `density_object = EXPORTED` | `BODY_04A.stage_boundary` | `4` |
| `PotentialFieldUnit.Build` | `BODY_04B` | 从新密度构造势场 / support-grid 刷新结果 | `density_new_handle = READY` | potential field ready | `ProjectorStateUpdater.update_fifo` | `9` 或 `13` |
| `ProjectorStateUpdater.Update` | `BODY_04B` | 刷新 projector/state 对象并联合提交 | potential field ready, projector context=`READY/RESIDENT` | `potential_new_handle`、`projector_state_next_handle = EXPORTED` | `BODY_04B.stage_boundary` | `5` |
| `DensityMixerUnit.Mix` | `BODY_04C` | 混合 old/new density | density / potential inputs=`READY` | mixed-density candidate ready | `ConvergenceTracker.decision_fifo` | `6` |
| `ConvergenceTracker.Decide` | `BODY_04C` | 形成 history / convergence summary | mixed-density candidate ready | `scf_decision_handle = QUERYABLE + EXPORTED` | `BODY_05.query_boundary` | `4` |
| `PreconditionedUpdateVector.Apply` | `BODY_10A` | 对 phase-B wave/residual 执行 preconditioned update | wave=`READY`, residual=`READY` | wave-candidate ready | `WaveCandidateCommit.commit_fifo` | `5` |
| `WaveCandidateCommit.Commit` | `BODY_10A` | 提交 `wave_candidate_object` 到 stage 域 | wave-candidate ready | `wave_candidate_object = STAGED` | `BODY_10A.stage_boundary` | `3` |
| `OrthogonalizeUnit.Project` | `BODY_10B` | 对 staged wave candidate 做正交化 / 投影 | wave candidate=`STAGED`, projector/metric=`READY/RESIDENT` | rebound-wave ready | `RebindCommit.commit_fifo` | `4` |
| `RebindCommit.Commit` | `BODY_10B` | 提交 rebound wave 与 projector refresh | rebound-wave ready | `updated_wave_object`、`updated_projector_object = EXPORTED` | `BODY_10B.stage_boundary` | `3` |
| `HistoryIntegrator.Commit` | `BODY_10C` | 积分 search history / accept-reject 中间态 | updated wave=`READY`, history=`READY` | history ready for summary export | `OTSummaryCommit.summary_fifo` | `2` |
| `OTSummaryCommit.Export` | `BODY_10C` | 导出 history 与 decision summary | history ready for summary export | `search_history_object`、`ot_decision_summary = QUERYABLE + EXPORTED` | `BODY_10C.query_boundary` | `1` |

这张表当前冻结的是：

- 每个 leaf block 的**对象输入条件**、**对象输出落点**和**局部完成点**；
- 当前行为级模型已经采用的 `accept / busy / complete` 切分位置；
- 后续继续细化 `RTL` 时应保留的模块边界，而不是再把这些叶块重新揉回一个模糊大模块。

当前还没有冻结的是：

- 每个 leaf block 的精确数据通路位宽、寄存器图、FIFO 深度和仲裁优先级；
- `BODY_04/10` 与 `Phase B` 之间是否允许更激进的跨 body overlap；
- `CIM / near-SRAM / Vector` 之间最终会不会继续下沉出更细的 chip-visible lowering 边界。

### 19.3 当前“完整系统模型”已经覆盖到哪

当前模型已经覆盖：

1. `Phase A-E/Bx` 的完整系统级闭环；
2. chip 内 `PROJECT -> near-SRAM coeff transform -> BACKPROJECT` 主链；
3. `BODY_10A/B/C` 与 `BODY_04A/B/C` 的运行时 bundle 化；
4. `QE`、`CP2K`、`VASP` 三类 flow family 的共用系统骨架；
5. `resident_context`、`row_block`、`LCW`、对象句柄和 bundle 摘要的显式追踪；
6. `ReplayBundleDescriptor / ReplayBundleCompletion` 形式的统一 runtime bundle 对象；
7. `Body04LoweringPlan` 形式的 outer-update lowering 对象；
8. `SCFIterationReport / DFTRunReport` 形式的完整运行结果对象。

### 19.4 当前仍未冻结的剩余问题

当前剩下的未冻结问题继续集中在：

- `BODY_04A/B/C` 与 `BODY_10A/B/C` 各自更深的 lowering、route 与 assist-engine 规则；
- `CP2K OT` 在 `BODY_10A/B/C` 之下的 sparse/object 细节如何继续冻结；
- `VASP` 的 `descriptor / replay / body` 字段是否继续下沉到更正式的 mode-switch 合同；
- `CIM` 阵列与近存容量、带宽、切换成本的定量参数。
