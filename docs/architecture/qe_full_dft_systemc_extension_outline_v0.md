# 2026-03-28 QE full DFT SystemC extension outline v0

## 1. 文档目标

这份文档的目标，是把当前已有的：

- `model/qe_band_solver_model/` 可运行原型
- `LCW / replay body` 架构语言
- `QE` 真实执行证据

连接成一个**与当前实现状态一致**的系统级扩展说明。

当前要回答的问题，不再只是：

> 如何把只覆盖 `c_bands episode` 的原型扩成完整 `QE SCF` 主流程？

而是更具体地回答：

1. 现在已经补到了哪一步；
2. 哪些地方已经从“设计意图”变成了“可运行行为级骨架”；
3. 下一步还缺哪些真正关键的下沉工作。

这里说的“完整”仍然是系统级/行为级完整，不是要求马上把每个数值 kernel 都做成精确硬件模型。

## 2. 当前原型的实际覆盖边界

从 `model/qe_band_solver_model/README.md` 和 `model/docs/qe_band_solver_smoke_run_20260326.md` 可确认，当前原型已经不再是旧版本那种：

- `HostSCF(mock) -> FPGAOrchestrator -> ChipTop -> episode complete`
- episode 返回后只做极简 `rho update / convergence check`

当前已经实现的行为级路径是：

- `HostSCF -> FPGAOrchestrator -> ChipTop -> c_bands episode -> sum_band -> v_of_rho/newd -> mix_rho -> next SCF iteration`

默认 smoke run 已经可以：

- 走完 `Phase A -> Phase B -> Phase C -> Phase D -> Phase E`
- 在默认第 `3` 轮 `SCF` iteration 后收敛退出

因此，当前原型已经明确具备的价值包括：

- `Host / FPGA / Chip` 三层系统对象边界
- chip 内部六域风格模块划分
- `BODY_00~05` 的主线日志语义
- `object handle / version / resident buffer tag` 的显式对象生命周期
- 从单次 `c_bands` episode 提升到 outer `SCF` 行为级闭环

但当前还没有真正补齐的地方同样很明确：

- `Phase C/D/E` 仍然是行为级阶段模块，还没有 lowered 成真正的 FPGA 管理 replay bundle
- `BODY_04` 当前仍是一个合并的 `density/potential/mixing` family，而不是完全冻结的细分 body catalog
- `ChipTop` 还没有统一的 `run_replay_body(...) / run_replay_bundle(...)` 接口
- 当前仍不是数值 faithful 的 `QE electrons` 全实现

## 3. 真实系统对象与当前实现名称

建议把完整系统对象固定理解为三层：

- `Host + software driver`
- `FPGA / runtime orchestrator`
- `ChipTop`

当前代码里的对应名称分别是：

- `HostSCF`
- `FPGAOrchestrator`
- `ChipTop`

也就是说，当前代码名还偏原型化，但系统角色已经比较清楚：

- `HostSCF` 实际承担的是 `HostDFTDriver` 的早期角色
- `FPGAOrchestrator` 实际承担的是 `FPGARuntimeOrchestrator` 的早期角色
- `ChipTop` 已经是较稳定的 chip-side system facade

这一点很重要，因为后续有些文档讨论的是：

- **真实系统对象是什么**

而另一些文档讨论的是：

- **当前代码里已经实现到哪一步**

这两层如果不分开，就会出现“设计上已经升级、文档里却还在按旧 demo 说话”的错位。

## 4. 建议的 QE 全流程 phase 划分

根据当前真实执行证据和当前原型状态，系统级 phase 可以稳定写成下面五段。

### 4.1 `Phase A: SCF setup / seed`

对应：

- 初始波函数/密度对象建立
- 本轮迭代对象绑定

主要 body：

- `BODY_05 outer_scf_control_body`
- `BODY_00 basis_seed_and_bind_body`

### 4.2 `Phase B: band-solver episode`

对应：

- `c_bands`
- `davidson` 内循环

主要 body：

- `BODY_01 operator_apply_body`
- `BODY_02 reduced_closure_solve_body`
- `BODY_03 refresh_compact_rebind_body`

这是当前已有 `ChipTop` 实现最接近、也最稳定的部分。

### 4.3 `Phase C: density accumulation`

对应：

- `sum_band`

主要职责：

- 用更新后的波函数对象形成新的密度相关对象
- 产生供后续势场更新的输入

当前实现状态：

- 已有 `DensityAccumulationStage`
- 但仍是 host-side 行为级模块，不是独立 chip replay body

### 4.4 `Phase D: potential / nonlocal refresh`

对应：

- `v_of_rho`
- `newd`

主要职责：

- 更新局域势/相关网格对象
- 更新 nonlocal / projector 相关辅助对象
- 为下一次 `c_bands` episode 生成新版本输入句柄

当前实现状态：

- 已有 `PotentialRefreshStage`
- 但仍是行为级阶段，不是已经冻结的硬件 lowering

### 4.5 `Phase E: mixing / convergence gate`

对应：

- `mix_rho`
- `SCF` convergence check

主要职责：

- 混合新旧密度/势对象
- 更新外层历史
- 决定是否继续下一轮 `SCF`

当前实现状态：

- 已有 `MixingConvergenceStage`
- 当前默认 smoke run 的收敛退出就由这一阶段触发

## 5. 当前 body family 的正确理解

当前最容易写错的地方，是把 `BODY_04` 说得过于精确。

现在更稳的写法应当是：

- `BODY_00`：`basis_seed_and_bind_body`
- `BODY_01`：`operator_apply_body`
- `BODY_02`：`reduced_closure_solve_body`
- `BODY_03`：`refresh_compact_rebind_body`
- `BODY_04`：当前是一个**合并的 host-visible density/potential/mixing family**
- `BODY_05`：`outer_scf_control_body`

也就是说：

- `BODY_01~03` 现在已经较明确地对应 chip-side `Phase B`
- `BODY_04` 现在只是把 `Phase C/D/E` 串起来的过渡性 family
- 将来是否把 `BODY_04` 再细分成多个 replay body，还没有最终冻结

这个澄清很关键，因为它直接影响：

- 后续 `LCW` 文档怎么写
- `QE / VASP / CP2K` 兼容时 body catalog 怎样扩展
- 当前 SystemC 日志语义应该如何解释

## 6. 当前对象模型

为了让全流程模型不退回“普通函数串联”，当前建议显式保留下面这些对象类。

### 6.1 核心对象类型

- `WavefunctionBlockObject`
- `DensityObject`
- `PotentialObject`
- `ProjectorStateObject`
- `ReducedClosureObject`
- `SCFHistoryObject`

### 6.2 对象元数据

每个对象至少带：

- `object handle`
- `version`
- `resident buffer tag`
- `producer body id`
- `validity scope`

当前 `qe_band_solver_model` 已经在行为级状态对象中开始显式维护这些概念，这说明对象语义不再只是抽象说法，而是已经进入原型代码。

## 7. 下一步最合理的实现顺序

### 7.1 第一步：冻结 `BODY_04` 语义

当前最需要先收住的，不是再去细抠 `Phase B`，而是明确：

- `BODY_04` 继续保持合并 family
- 还是拆成 `density / potential / mixing` 的更细 body

这决定后续：

- `LCW` catalog 是否要扩张
- `FPGA` 侧 bundle 组织怎样设计
- `CP2K / VASP` 兼容时哪些 patch 点会落在哪

### 7.2 第二步：把 `Phase C/D/E` 从 host 行为模块下沉到 FPGA 管理 bundle

也就是说，把当前：

- `HostSCF -> DensityAccumulationStage -> PotentialRefreshStage -> MixingConvergenceStage`

进一步推进成：

- `HostSCF/HostDFTDriver` 下发高层计划
- `FPGAOrchestrator` 组织 `BODY_04` 或其细分 bundle
- `ChipTop` 接受更完整的 replay body 族

### 7.3 第三步：补 `ChipTop` 的统一 replay 接口

建议后续新增：

- `run_replay_body(...)`
- `run_replay_bundle(...)`

这样才算真正把：

- `LCW`
- `template`
- `replay body`
- `SystemC` 原型

说成同一套语言。

### 7.4 第四步：把 `QE` 骨架扩展成更稳定的跨软件控制合同

这里不是马上去写一个“兼容一切”的大模型，而是：

- 先用 `QE` 把全流程控制骨架压实
- 再检查 `VASP` 哪些 pressure 主要落在 `BODY_01~04`
- 再检查 `CP2K` 哪些 pressure 需要额外 `BODY_10+` 扩展

## 8. 与后续 `CP2K / VASP` 兼容的关系

这份 `QE` 全流程扩展纲要并不是把架构重新收窄回 `QE-only`。
相反，它的意义是：

- 先用 `QE` 真实执行证据把完整 DFT flow 的系统骨架搭起来
- 再在这个骨架上考察哪些 body family 对 `CP2K` 或 `VASP` 仍成立
- 最后只在 body specialization 上扩展，而不是推翻整个系统模型

这比直接从一开始做一个“声称兼容一切软件”的大而空模型更稳。

## 9. 当前最稳的结论

当前最合理的推进路径已经比较明确：

- 现有 `model/qe_band_solver_model/` 不需要推倒重来
- 它已经不再只是 `Phase B` 单点 demo，而是一个以 `Phase B / BODY_01-03` 为核心的完整 `QE SCF` 行为级骨架
- 当前真正缺的不是再把 `c_bands` 写得更细，而是把 `Phase C/D/E` 从 host-visible behavior modules 继续下沉成更稳定的 replay-control contract

这样做的结果是：

- `QE` 侧会从“band-solver subsystem demo”稳定升级成“完整 DFT flow system model”
- `CP2K / VASP` 兼容讨论会从抽象口号，变成“哪些 replay body 能复用、哪些需要扩展”的可执行问题
