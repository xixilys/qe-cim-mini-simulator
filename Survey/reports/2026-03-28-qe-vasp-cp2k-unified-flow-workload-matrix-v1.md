# 2026-03-28 QE / VASP / CP2K unified flow and workload matrix v1

## 1. 目标

这份文档是对先前三方对照表的升级版。

相比 `2026-03-27-qe-vasp-cp2k-three-way-workload-matrix.md`，这里不再只做粗粒度并列，而是尽量把三者的：

- 证据边界
- 主流程骨架
- 核心内层负载
- solver / minimizer 分支
- projector / FFT / grid / sparse 路径
- 对 chip-top 的直接要求

统一写到一个更完整的矩阵里。

## 2. 证据等级先说明

### 2.1 `QE`

当前是三者里证据最强的一类：

- 本地可执行
- 已有真实 trace
- 已恢复到 phase / call / reduced-closure 粒度

### 2.2 `CP2K`

当前属于：

- 本地源码树存在
- benchmark 输入存在
- 已做到源码/benchmark 级主流程恢复
- 但没有本地执行 trace

### 2.3 `VASP`

当前属于：

- workspace 中无本地源码/可执行
- 已做到基于官方一手公开文档的主流程恢复
- 无本地执行与源码级细节

因此，三者完整度的真实排序仍然是：

- `QE` > `CP2K` > `VASP`

但现在三者至少都已经有了一版明确的主流程与负载分析。

## 3. 三者统一矩阵

| 维度 | QE | VASP | CP2K |
|---|---|---|---|
| **当前证据等级** | 本地执行 + trace | 官方文档恢复 | 本地源码/benchmark 恢复 |
| **主方法学对象** | plane-wave KS-DFT | plane-wave KS-DFT + PAW | GPW/GAPW Quickstep |
| **外层主循环** | `electrons` SCF loop | SCC / electronic minimization loop | `scf` / `scf_env_do_scf` |
| **当前最贴近的内层对象** | `c_bands` | orbital / band update | Quickstep inner loop |
| **典型内层路径** | Davidson / generalized subspace solve | blocked-Davidson / RMM-DIIS / Fast hybrid | DIAGONALIZATION / OT |
| **初始化对象** | initial density + basis/bands | initial density + orbitals | initial density / MO / SCF env |
| **Hamiltonian 更新** | `v_of_rho`, `newd`, nonlocal path | density -> Hamiltonian | `qs_ks_build_kohn_sham_matrix` |
| **主优化对象** | wavefunction bands | orbitals / bands | orbitals or density matrix |
| **显式 reduced closure** | 很强，`rdiaghg` 可见 | 强，但官方公开材料多写成 iterative diagonalization/minimization | 强，但与 OT 并存 |
| **solver / minimizer 分支** | 以 Davidson 为中心 | `IALGO=38`, `IALGO=48`, `ALGO=Fast` | `DIAGONALIZATION` vs `OT` |
| **FFT 角色** | 主链核心 | 主链核心 | grid/Poisson/support 核心 |
| **projector / augmentation** | ultrasoft / nonlocal / `calbec` | `PAW` projector + augmentation | 有，但不再是唯一中心 |
| **局域/支持网格** | FFT grid + local potential path | fine FFT grid + support grid (`ADDGRID`) | grid + Poisson + basis/grid coupling |
| **自然 batching 维度** | band subset / panel / tile | `NSIM` band batch | block matrix / sparse block / task bundle |
| **稀疏 / block-sparse** | 非主线 | 非主线 | 主线之一（`DBCSR`） |
| **mixing / convergence gate** | `mix_rho` | `IMIX` / Broyden / Pulay / Kerker | DIIS / Broyden / OT preconditioned update |
| **最像哪类 chip object** | fixed replay episode | replay episode with mode switch | multi-kernel bundle |
| **与当前 chip-top 的贴合度** | 最高 | 高 | 中等 |
| **对当前顶层的最大压力** | 完整 DFT outer phases 还未建模 | solver mode + batch width + support-grid | sparse/block + OT branch + matrix objects |

## 4. 三者共同的最小系统骨架

尽管底层实现差异很大，但三者都可以收口到下面这个系统骨架：

1. 初始密度/轨道/对象绑定
2. 当前状态定义 Hamiltonian 或等价闭包对象
3. 轨道/波函数更新
4. 占据/能量/摘要更新
5. 新密度或等价状态重构
6. mixing / convergence gate
7. 进入下一轮 SCF

这就是为什么当前 `replay body` 方向是成立的：

- 三者共享 SCF-driven outer loop
- 共享某种 orbit/band update inner loop
- 共享 density/state reconstruction
- 共享 mixing / convergence decision

## 5. 三者最核心的差异在哪里

### 5.1 `QE`

`QE` 的最大特点是：

- 当前我们已经能真实看到 `c_bands` 内部阶段
- `projector/nonlocal + FFT + reduced solve + refresh` 这一组合是可执行证据支撑的
- 因此它最适合拿来做第一 SystemC/architecture 主线

### 5.2 `VASP`

`VASP` 的最大特点是：

- 和 `QE` 非常像，但 `PAW` augmentation、双网格/support-grid 更显式
- `blocked-Davidson`、`RMM-DIIS`、`Fast` 混合路径要求顶层支持 solver mode 切换
- `NSIM` 明确暴露出 batched band update 的硬件意义

### 5.3 `CP2K`

`CP2K` 的最大特点是：

- `Quickstep` 不是纯 plane-wave 叙事，而是 GPW/GAPW 混合对象
- 除对角化路径外，`OT` 是必须考虑的主分支
- `DBCSR` 说明 block-sparse / matrix-object 支撑不能缺席

## 6. 对 chip-top 最稳的共同要求

基于当前三者分析，最稳的共同 chip-top 要求是：

- 顶层不能写成 rigid single pipeline
- 但也没必要上升成完整 CPU/CGRA
- 更合理的是：
  - `Host + FPGA/runtime + Chip`
  - chip 内部保持固定引擎
  - 顶层通过 `LCW + replay body + mode/batch/route fields` 调度

## 7. 当前六域划分的适配性

### 7.1 当前六域

- `Command Scheduler`
- `CIM / Projector-Apply Engine`
- `FFT Engine`
- `Near-SRAM Support Domain`
- `Reduction / Closure / Solve Engine`
- `SIMD / Vector Companion`

### 7.2 三者适配情况

`QE`：

- 几乎完全对齐当前六域划分

`VASP`：

- 同样高度对齐，但更强调：
  - support-grid
  - solver-mode switching
  - batched band width

`CP2K`：

- 前五域依然成立
- 但未来可能需要：
  - 更强 matrix/block object 支撑
  - OT 相关 body
  - 可能的 sparse/block specialization

## 8. 当前最合理的系统推进顺序

基于三者完整度和系统风险，当前最合理的推进顺序仍然是：

1. 继续以 `QE` 为可执行主线
2. 把当前 `c_bands` 子系统推广成完整 `QE DFT flow` SystemC 模型
3. 用 `VASP` 验证 replay family、batch、support-grid、projector 路线没有写偏
4. 用 `CP2K` 验证顶层没有被锁死在 plane-wave-only / diagonalization-only 路线上

## 9. 当前最稳的结论

现在已经可以比较有把握地说：

- `QE`、`VASP`、`CP2K` 的实现差异很大，但其系统级主循环足够相似，能共享一套 higher-level replay skeleton
- 当前最该泛化的，是顶层 replay-contract，而不是立即把每个底层执行单元都做成通用可编程核
- 因此现阶段最合理的工程路径仍然是：
  - 用 `QE` 推进完整 system model
  - 用 `VASP / CP2K` 做 contract 检查和扩展压力测试

## 10. 对应文件

- QE executed flow: `Survey/reports/2026-03-28-qe-phase-to-unit-mapping-v0.md`
- VASP official-doc recovery: `Survey/reports/2026-03-28-vasp-flow-and-workload-recovery-v0.md`
- CP2K source recovery: `Survey/reports/2026-03-28-cp2k-source-flow-recovery-v0.md`
