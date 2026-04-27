# 2026-03-28 CP2K source-flow recovery v0

## 1. 目标

这份笔记不尝试在当前 macOS 环境下直接跑 `CP2K`，而是先完成源码级主流程恢复，回答三个问题：

- `CP2K` 当前在本仓库里最主要的 DFT 路线对象是什么
- 它的主执行链如何从程序入口走到 `SCF` 与核心数值路径
- 它给未来兼容型芯片顶层带来的结构压力是什么

这里所有结论都明确标记为：

- **源码/benchmark 恢复证据**
- 不是当前 workspace 中的真实已执行证据

## 2. 当前可确认的执行边界

根据本仓库现状：

- `soft/cp2k/` 源码树完整存在
- benchmark 与测试输入丰富
- 当前主机环境下不适合作为第一执行入口
- 因而本阶段只做**源码恢复 + benchmark 输入恢复**

这与 `QE` 当前已实际执行的状态不同。

## 3. 从入口到 Quickstep 的主执行链

### 3.1 程序入口

源码入口在：

- `soft/cp2k/src/start/cp2k.F`

这里的 `PROGRAM cp2k` 负责：

- 初始化运行环境
- 解析输入/输出参数
- 调用运行调度层

### 3.2 运行调度层

更关键的调度层在：

- `soft/cp2k/src/start/cp2k_runs.F`

从这里可以看出 `CP2K` 的真实对象不是单一 DFT 求解器，而是一个支持多种 run type 的通用运行框架。对我们最关键的是其中的：

- `create_force_env`
- `force_env_calc_energy_force`
- 与 `do_qs` / `METHOD QS` 相关的 Quickstep 路线

因此对芯片兼容视角来说，`CP2K` 的宿主对象更明显是：

- 一个大而泛化的软件运行框架
- 其中 `Quickstep` 只是其 DFT 电子结构主线之一

### 3.3 Quickstep 作为主要 DFT 工作负载对象

benchmark 文档直接说明：

- `benchmarks/QS/README.md`
- `benchmarks/QS_single_node/README.md`

都把 `Quickstep` 视为主要 DFT benchmark 路线。

这说明后续如果我们要谈 `CP2K` 兼容，实际上应该优先面向：

- `Quickstep GPW/GAPW` 风格工作负载
- 而不是泛泛地说“兼容 CP2K 的一切功能”

## 4. 从 Quickstep 到 SCF 的主求解链

### 4.1 SCF 顶层入口

`SCF` 相关主入口位于：

- `soft/cp2k/src/qs_scf.F`

关键子程序：

- `scf`
- `scf_env_do_scf`

从 `scf` 可以直接看出：

- 先构造/初始化 `qs_scf_env`
- 再进入 `scf_env_do_scf`
- 若不是特殊 `CDFT` 分支，则标准 Quickstep 电子结构优化都在这条链内完成

这与 `QE` 的 `electrons -> c_bands` 很像，区别是：

- `QE` 直接暴露 band-solver episode
- `CP2K` 更先暴露 `SCF environment`

### 4.2 `scf_env_do_scf` 的意义

`scf_env_do_scf` 是当前最关键的源码恢复锚点。

从源码命名、状态变量和相邻调用可以恢复出它承担的职责：

- 维护 `QS_SCF` 迭代层级
- 驱动每轮电子结构更新
- 连接 mixing、DIIS、OT、对角化、矩阵与密度更新
- 在迭代结束后决定是否收敛并回写结果

所以若用我们当前的芯片顶层语言表达，它更像：

- `Quickstep SCF episode dispatcher`

而不是单一数值 kernel。

## 5. 当前能恢复出的两条主要数值路线

### 5.1 对角化路线

benchmark 输入里可以直接看到标准对角化风格：

- `benchmarks/QS_single_node/diag_cu72_broy.inp`
- `benchmarks/QS_diag/nm211_elpa_bench.inp`

它们显式包含：

- `&SCF`
- `&DIAGONALIZATION`
- `PREFERRED_DIAG_LIBRARY ELPA`
- `CHOLESKY INVERSE_DBCSR`
- `&MIXING METHOD BROYDEN_MIXING`

因此可以恢复出一条很明确的 `CP2K` 路线：

- 构建 Kohn-Sham 闭包
- 做 overlap / Cholesky / diagonalization
- 借助 ELPA / ScaLAPACK 一类对角化后端
- 通过 mixing 驱动外层 SCF 收敛

这条路线对我们最有价值，因为它与 `QE` 当前抓住的 `subspace closure + solve + refresh` 有明显可对应结构。

### 5.2 OT 路线

另一些 benchmark，例如：

- `benchmarks/QS_single_node/H2O-gga.inp`

则显式启用：

- `&OT ON`

并且源码里对应：

- `soft/cp2k/src/qs_ot_scf.F`
- `ot_scf_read_input`
- `ot_scf_init`
- `ot_scf_mini`

从源码能直接看出，OT 路线大量依赖：

- `DBCSR` 矩阵操作
- 稀疏/块稀疏矩阵乘法
- 正交化、旋转、约束最小化相关更新

这说明如果未来真要兼容 `CP2K`，芯片顶层不能只围绕“QE 式子空间对角化 episode”设计；它还需要为：

- 非纯对角化的轨道优化路径
- 更强的稀疏/块矩阵数据结构

预留可挂接的控制与执行接口。

## 6. Kohn-Sham / 密度 / Poisson 路线

### 6.1 Kohn-Sham 构建主线

`soft/cp2k/src/qs_ks_methods.F` 中的关键子程序包括：

- `qs_ks_build_kohn_sham_matrix`
- `calc_rho_tot_gspace`
- `qs_ks_update_qs_env`
- `rebuild_ks_matrix`

这说明在 `CP2K Quickstep` 中，核心循环对象不是单纯 `H*psi`，而更偏向：

- 在 AO / DBCSR / GPW 混合表示下构建并更新 Kohn-Sham 矩阵与密度对象

### 6.2 Poisson / FFT 路线

平面波相关主线可在：

- `soft/cp2k/src/pw/pw_poisson_methods.F`

中看到。

这里暴露了：

- `pw_poisson_set`
- `pw_poisson_rebuild`
- `pw_poisson_solve`

再结合 benchmark 中频繁出现的：

- `METHOD GPW`
- `MGRID`
- `EXTENDED_FFT_LENGTHS`

可以恢复出 `CP2K` 的另一类关键结构压力：

- 它也有 FFT / 网格 / Poisson 支撑域
- 但它和 `QE` 纯平面波路径不同，往往是与 Gaussian / AO / DBCSR 环境交织的

因此，若芯片顶层要兼容 `CP2K`，`FFT Engine` 不应只被定义为“QE 风格 plane-wave helper”，而应定义成：

- 一个可被 grid / Poisson / representation-conversion 共同调用的共享域

## 7. 对芯片顶层的直接压力

### 7.1 为什么不能只做一条刚性流水

从 `CP2K` 源码级恢复可以更清楚地看到：

- 同样是 `Quickstep SCF`，就已经有 `DIAGONALIZATION` 与 `OT` 两种显著不同的内部数值路径
- 并且它们都共享：
  - Kohn-Sham/密度更新
  - mixing
  - Poisson / grid / FFT 支撑
- 但在线性代数对象和数据结构上又差异很大

所以如果芯片顶层被做成“只适配一个固定 band-solver 流水”的形式，那么：

- `QE` 也许能很好适配
- 但 `CP2K` 很容易在 `OT`、DBCSR、AO/GPW 混合表示处失配

### 7.2 对当前 `LCW` 方向的支持

反过来说，这份源码恢复也支持我们已经收口的方向：

- 顶层更适合是一个 `LCW` 控制的混合系统
- 用一条宽控制字同时编排多个计算部件与数据路径
- 而不是暴露一套传统、过于细粒度的通用 ISA

因为 `CP2K` 真正需要的是：

- 调度不同 replay body
- 在不同对象表示之间切换
- 让不同执行域按 episode 级模板协同工作

而不是逐条软件式标量指令解释执行。

## 8. 目前可抽象出的 `CP2K` 兼容压力矩阵

### 8.1 和 `QE` 明显共性的部分

- `SCF` 外层收敛驱动
- FFT / grid / Poisson 支撑域
- 某种 form 的 overlap / closure / solve
- mixing / convergence gate
- 需要宿主软件保留较强调度能力

### 8.2 比 `QE` 更强的要求

- `DBCSR` / block-sparse 数据对象
- AO / Gaussian 与 plane-wave 混合表示
- `OT` 这种不依赖传统子空间对角化的求解支路
- 通过 ELPA/ScaLAPACK/Cholesky 等不同后端切换求解策略

### 8.3 对我们当前芯片分块的影响

这继续支持当前的六域划分，但要求每一域都更“可编排”而不是更“固定”：

- `Command Scheduler`：必须能选择 `QE-like diagonalization replay` 与 `CP2K-like OT / DBCSR replay`
- `CIM / Projector-Apply Engine`：不能只盯着 ultrasoft projector，也要考虑更广义的矩阵-向量/矩阵块投影与聚合
- `FFT Engine`：要覆盖 grid / Poisson / representation conversion
- `Near-SRAM Support Domain`：要考虑 block-sparse / tiled object 管理
- `Reduction / Closure / Solve Engine`：既要支持 reduced closure，也要能挂接更一般的 dense/structured solve
- `SIMD / Vector Companion`：承接小型向量更新、mixing、约束与辅助数值操作

## 9. 当前最稳的结论

基于当前 `CP2K` 源码级恢复，最稳的判断是：

- 如果目标只是把 `QE c_bands` 做到极致，可以继续收口到 band-solver subsystem
- 但如果导师要求后续兼容 `VASP` 乃至 `CP2K`，那么芯片顶层必须保留：
  - 多 replay body
  - 多对象表示
  - 多求解分支
  - 宿主 runtime 参与度较高

因此目前最合理的架构语言不是“固定流水 DFT 芯片”，而是：

- **面向 DFT/科学计算电子结构主循环的 domain-specific accelerator**
- **由 Host + FPGA/runtime + Chip 组成的混合系统**
- **芯片内部用 LCW 宽控制字编排多个数值域**

这与当前主线方向是相容的，而且比单纯“做一个更大 band-solver pipeline”更能容纳后续 `CP2K/VASP` 压力。
