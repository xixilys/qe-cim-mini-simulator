# 2026-03-28 VASP flow and workload recovery v0

## 1. 目标

这份笔记的目标，是把 `VASP` 的流程分析尽量补到接近当前 `QE` / `CP2K` 的完整度。

由于当前 workspace 中：

- 没有 `VASP` 本地源码树
- 没有 `VASP` 本地可执行程序

因此本文只能做到：

- **非执行型主流程恢复**
- **基于官方一手公开文档的 workload 与控制路径抽象**

也就是说，本文不声称已经得到 `VASP` 本地 trace，但会尽量把其主循环、核心负载和芯片顶层压力恢复完整。

## 2. 证据边界

### 2.1 当前没有的证据

当前没有：

- `VASP` 本地源码级证据
- `VASP` 本地 trace
- `VASP` 本地 benchmark 运行证据

### 2.2 当前采用的证据类型

本文主要依赖 `VASP` 官方公开资料：

- `Self-consistency cycle - VASP Wiki`
- `ALGO - VASP Wiki`
- `IALGO - VASP Wiki`
- `NSIM - VASP Wiki`
- `IMIX - VASP Wiki`
- `Projector-augmented-wave formalism - VASP Wiki`
- `NGXF - VASP Wiki`
- `ADDGRID - VASP Wiki`
- `VASP workshop` 公开讲义（electronic convergence / basics / accuracy）
- `VASP About` 页面

因此这是一份：

- **官方文档驱动的主流程恢复**
- **不是本地源码恢复，更不是本地执行恢复**

## 3. `VASP` 的稳定方法学对象

从官方说明可以稳定确认：

- `VASP` 的中心对象是 `plane-wave Kohn-Sham DFT`
- 轨道、密度、局域势等中心量使用平面波/FFT 网格表达
- 电子-离子相互作用使用 `PAW`、USPP 或 norm-conserving 路线

更具体地说，`VASP` 官方介绍明确指出：

- 电子基态通过迭代矩阵对角化技术求解
- 核心电子结构变量在平面波基组中表达
- 电子-离子相互作用可通过 `PAW` 描述

这意味着，从芯片视角看，`VASP` 和 `QE` 的共性非常强：

- 都是 plane-wave KS DFT
- 都有 projector / augmentation 路线
- 都高度依赖 FFT / real-space grid
- 都存在电子自洽外层与轨道优化内层

## 4. 从官方 SCC 文档恢复的主流程

`VASP` 官方 `Self-consistency cycle` 页面已经给出一个非常明确的电子自洽循环。

### 4.1 初始化阶段

起点是：

- 初始电荷密度
- 初始轨道

从零开始时，`VASP` 使用：

- 重叠原子电荷密度作为初始密度近似
- 随机初始化轨道

如果有重启文件，则可从已有轨道或密度继续。

### 4.2 电子内层迭代

随后进入标准 SCC：

1. 当前密度定义 Hamiltonian
2. 通过迭代矩阵对角化求得 `NBANDS` 个最低本征态
3. 基于本征值和轨道计算占据数
4. 计算自由能
5. 用轨道和占据构造新密度
6. 对新旧密度做 mixing
7. 用混合后的密度定义下一轮 Hamiltonian

这个过程反复迭代，直到能量变化低于 `EDIFF`。

### 4.3 `VASP` 电子主循环的最稳抽象

因此从系统对象看，`VASP` 最稳的电子结构主循环可以抽成：

- `rho_in -> H[rho] -> orbital optimization / band update -> occupancies -> rho_out -> mixing -> rho_next`

这和当前已经跑出来的 `QE electrons -> c_bands -> sum_band -> v_of_rho -> newd -> mix_rho` 非常接近。

也就是说：

- `QE` 的软件阶段名更显式
- `VASP` 的官方文档则更强调 SCC 步骤
- 但二者在系统级控制骨架上高度同构

## 5. `VASP` 的主要电子优化路径

### 5.1 Blocked-Davidson 路线

官方 `ALGO` / `IALGO` 页面确认：

- `ALGO = Normal` 对应 `IALGO = 38`
- 这是 `blocked-Davidson` 路线

官方说明进一步指出：

- 该算法一次同时优化一部分 band
- `NSIM` 控制同时优化的 band 数
- 被优化的 band 保持与其它 band 正交

这对硬件很重要，因为它说明 `VASP` 不是纯单 band 串行优化，而是：

- 存在显式的 batched band update
- 存在局部 search space
- 存在正交化与子空间旋转压力

### 5.2 RMM-DIIS 路线

官方 `ALGO` / `IALGO` 页面还确认：

- `ALGO = VeryFast` 对应 `IALGO = 48`
- 这是 `RMM-DIIS` 路线

官方文档说明它通过减少正交化步骤来提高速度，但也明确提醒：

- 它比 `blocked-Davidson` 更快
- 但并非在所有系统上都同样稳健
- 初始轨道与前若干非自洽步对收敛很关键

所以从系统设计看，`VASP` 不只是一条固定 solver path，而是：

- 至少有 `blocked-Davidson`
- `RMM-DIIS`
- 以及 `Fast` 这种前期 Davidson、后期切换 RMM-DIIS 的混合路径

### 5.3 `Fast` 混合路径

官方 `ALGO = Fast` 页面明确写到：

- 初始阶段使用 `blocked-Davidson`
- 随后切换到 `RMM-DIIS`
- 对每个离子步还会再做一次 `IALGO=38` sweep

这条信息对我们很关键，因为它意味着：

- `VASP` 顶层不是“固定某一个 solver”，而是允许 episode 内 solver mode 切换
- 如果未来要兼容 `VASP`，chip-top control 至少要能表达：
  - initial robust mode
  - fast refinement mode
  - periodic fallback sweep

这就是为什么当前系统不适合写成 rigid single pipeline，而更适合 `LCW + replay body + mode switch`。

## 6. `NSIM` 暴露出来的负载与 batching 特征

官方 `NSIM` 页面给出非常直接的硬件线索：

- `NSIM` 设置同时优化的 band 数
- `RMM-DIIS` 以 blocked mode 工作
- 同时优化 `NSIM` 条 band 能把某些步骤从 matrix-vector 变成 matrix-matrix
- 其中点名受益的就是 nonlocal projection operators in real space

这意味着：

- `VASP` 的真实高价值并行维度之一就是 band batch
- 当前我们的 `QE` 路线里已经存在 `nbnd` 子集、动态筛选、panel 组织
- `VASP NSIM` 正好从另一侧证明，这类 batched band/update 视角是对的

这也直接支持：

- `SIMD / Vector Companion`
- `Near-SRAM Support Domain`
- `projector/apply engine`

在 `VASP` 兼容视角下都不是附属部件，而是关键部件。

## 7. `PAW` 路线带来的 projector / augmentation 压力

`Projector-augmented-wave formalism` 官方页面明确指出：

- 真正轨道由 pseudo orbitals 加上 projector/partial-wave 修正恢复
- 伪轨道是变分对象，并在平面波基组中展开
- `PAW` 的 augmentation 把平面波网格上的部分和球区附近的部分联动起来

这说明 `VASP` 的 projector 路线不是边缘功能，而是中心结构之一。

从硬件抽象看，这意味着：

- `VASP` 和 `QE` 一样，都不是“纯 FFT + dense solve”
- `projector / augmentation / local correction` 路线同样重要
- 我们当前围绕 `projector-apply`、adjoint-aware primitive 的收口并没有被 `VASP` 否定

## 8. `FFT`、双网格和 augmentation 负载

`VASP` 的 FFT / grid 相关负载可以从官方 wiki 和 workshop 资料恢复得比较具体。

### 8.1 粗细双网格

官方 `NGXF` 页面说明：

- `NGXF / NGYF / NGZF` 控制 fine FFT grid
- `PAW` / `USPP` 的 localized augmentation charges 在 fine FFT grid 上表示
- 在 USPP 情况下，局域势也会在 fine grid 上计算

这已经说明 `VASP` 不是单一 FFT grid，而是：

- coarse plane-wave grid
- fine augmentation / density / potential grid

### 8.2 support grid

官方 `ADDGRID` 页面进一步说明：

- 可以再启用一个额外 support grid
- 这个 support grid 点数是 fine grid 的 8 倍
- augmentation charge 会先在该 support grid 上评估，再 FFT 回 reciprocal space，然后再加回 fine grid

这条信息对系统设计很关键，因为它意味着：

- `VASP` 的 PAW/augmentation 路线不仅需要 FFT
- 还需要显式 support grid / temporary grid / local-to-global accumulation

这与我们当前的：

- `Near-SRAM Support Domain`
- `FFT Engine`
- `CIM / Projector-Apply Engine`

的三者联动非常一致。

### 8.3 非局域 projector 的计算路径

官方 accuracy 讲义还进一步指出：

- 非局域项 `Hψ` 中存在 projector 相关表达
- 这部分可在 real space 或 reciprocal space 求值
- reciprocal-space 路径对 plane waves、ions、projectors 有耦合
- real-space 路径因为 projector 的局域性，对离子数的扩展更友好

因此，`VASP` 的非局域 projector 路线本身就是一个重要的 workload 分流点：

- 一边连接 plane-wave / reciprocal objects
- 一边连接 localized projector / augmentation objects
- 需要在 real-space / reciprocal-space 之间来回组织数据

这再次说明我们当前把 projector/apply 路线作为主 primitive 是有依据的。

## 9. 密度 mixing 与收敛压力

`VASP` 官方 `IMIX` 和 density-mixing 文档给出的信息也很完整。

可以稳定恢复出：

- `VASP` 电子循环的核心固定点问题本质上是 `rho_in -> rho_out`
- 默认 mixing 采用 Broyden / Pulay 路线
- 对金属体系尤其容易出现 charge sloshing
- Kerker、Broyden、Pulay、Tchebycheff 都是可选手段

从芯片设计角度，最稳的结论不是“要把所有 mixing 算法都做进 chip”，而是：

- `mixing / convergence gate` 必须在完整 DFT flow 中被显式建模
- 不能永远停留在 band-solver 返回后的一个 mock 语句

也就是说，`QE` 里要补的 `mix_rho`，在 `VASP` 这里也有非常清晰的对应物。

## 10. `VASP` 的系统级对象总结

如果把上面的官方证据收口成系统语言，那么 `VASP` 最稳的对象可以这样写。

### 10.1 外层对象

- `electronic SCC loop`
- `ionic loop`（如果是结构优化或 MD）

### 10.2 内层主负载

- Hamiltonian build from density
- blocked band/orbital update
- `blocked-Davidson` / `RMM-DIIS` / hybrid switching
- occupancies + free energy
- density reconstruction
- density mixing

### 10.3 关键负载族

- plane-wave basis update
- FFT / dual-grid / support-grid movement
- PAW projector / augmentation evaluation
- subspace diagonalization / orthogonalization / rotation
- batched band update (`NSIM`)
- density mixing and convergence control

## 11. 对当前 chip-top 的直接含义

### 11.1 `VASP` 与 `QE` 的共性足够强

这意味着当前 chip-top 主资产仍然成立：

- `FFT Engine`
- `CIM / Projector-Apply Engine`
- `Near-SRAM Support Domain`
- `Reduction / Closure / Solve Engine`
- `SIMD / Vector Companion`

### 11.2 `VASP` 比 `QE` 更强调 mode switch 和 batched band update

`VASP` 带来的额外要求主要是：

- solver path 不能写死
- band batch / `NSIM` 要被顶层控制明确支持
- augmentation / support grid 要被视为一等对象，而不是边角实现细节

### 11.3 当前最稳的顶层合同

因此，如果要让系统对 `VASP` 友好，最该冻结的不是某个固定 solver 硬流水，而是：

- `LCW body type`
- `solver mode`
- `batch width`
- `projector/FFT/support-grid route`
- `refresh / mix / convergence gate`

这样的 replay-contract 语言。

## 12. 当前最稳的结论

在没有本地源码和执行证据的约束下，基于官方一手资料，当前已经可以比较有把握地说：

- `VASP` 的电子结构主循环与 `QE` 在系统骨架上高度接近
- 它同样是 `plane-wave + projector/augmentation + FFT + iterative eigensolver/minimizer + density mixing` 组合体
- 与 `QE` 最大的差异不在于是否需要这些模块，而在于：
  - `PAW` augmentation / support-grid 更强
  - solver mode 切换更显式
  - `NSIM` 暴露出更明确的 batched band update 维度

因此，`VASP` 并没有推翻我们现在的系统对象；
它更像是在要求：

- 顶层控制语言更一般化
- replay body 更能表达 mode switch、batch width、support-grid 路由

## 13. 本文证据来源

- VASP Self-consistency cycle: https://www.vasp.at/wiki/index.php/Self-consistency_cycle
- VASP ALGO: https://www.vasp.at/wiki/ALGO
- VASP IALGO: https://www.vasp.at/wiki/index.php/IALGO
- VASP NSIM: https://www.vasp.at/wiki/index.php/NSIM
- VASP IMIX: https://www.vasp.at/wiki/IMIX
- VASP About: https://www.vasp.at/info/about/
- VASP PAW formalism: https://www.vasp.at/wiki/index.php/Projector-augmented-wave_formalism
- VASP PAW category: https://www.vasp.at/wiki/index.php/Category%3AProjector-augmented-wave_method
- VASP NGXF: https://www.vasp.at/wiki/NGXF
- VASP ADDGRID: https://vasp.at/wiki/ADDGRID
- VASP workshop basics: https://www.vasp.at/wiki/images/5/5d/VASP_lecture_Basics.pdf
- VASP workshop electronic convergence: https://www.vasp.at/wiki/images/b/b6/VASP_lecture_Basics2.pdf
- VASP workshop accuracy: https://www.vasp.at/vasp-workshop/accuracy.pdf
- VASP HPC lecture: https://www.vasp.at/wiki/images/4/46/VASP_lecture_HPC.pdf
