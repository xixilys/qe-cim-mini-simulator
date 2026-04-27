# 2026-03-28 QE phase-to-unit mapping v0

## 1. 目标

这份笔记把已经真实执行的 `QE` case 从“能跑”推进到“可映射”：

- 用真实 `si8_pbe_uspp` 运行结果恢复更有代表性的 `SCF -> c_bands -> davidson` 循环体
- 把软件可见 phase 映射到芯片顶层硬件单元
- 把 phase 进一步收敛成后续 `LCW replay body` 候选
- 明确哪些结论来自真实执行，哪些仍然只是保守推断

## 2. 本次执行对象

### 可执行程序

- `soft/qe-7.5/build_subspace_trace/bin/pw.x`

### 输入文件

- `docs/qe_inputs/si8_pbe_uspp.in`

### 输出目录

- `docs/benchmarks/results/qe_autonomous_si8_uspp/`

### 本次环境变量

- `OMP_NUM_THREADS=1`
- `QE_HPSI_TRACE_FILE=docs/benchmarks/results/qe_autonomous_si8_uspp/hpsi_trace.csv`
- `QE_BANDSOLVER_TRACE_FILE=docs/benchmarks/results/qe_autonomous_si8_uspp/bandsolver_trace.csv`
- `QE_SUBSPACE_TRACE_FILE=docs/benchmarks/results/qe_autonomous_si8_uspp/subspace_trace.csv`
- `QE_SUBSPACE_MIN_N=0`

## 3. 真实执行摘要

本次 `si8_pbe_uspp` 已成功完成 `8` 次 SCF 迭代并输出 trace。

从 `stdout.out` 可直接确认：

- `electrons : 0.81s WALL`
- `c_bands : 0.41s WALL (8 calls)`
- `h_psi : 0.26s WALL (53 calls)`
- `s_psi : 0.05s WALL (53 calls)`
- `g_psi : 0.00s WALL (44 calls)`
- `h_psi:calbec : 0.06s WALL (53 calls)`
- `vloc_psi : 0.14s WALL (53 calls)`
- `add_vuspsi : 0.05s WALL (53 calls)`
- `calbec : 0.07s WALL (61 calls)`
- `fft : 0.03s WALL (100 calls)`
- `ffts : 0.00s WALL (8 calls)`
- `fftw : 0.14s WALL (1192 calls)`

这说明在这个比 `h2_tiny` 更有代表性的 case 里，`c_bands episode` 已经清楚表现为：

- 不是单一 dense eigensolve
- 而是 `operator apply + overlap apply + subspace closure + basis refresh + FFT support + projector/nonlocal support` 组合循环体

## 4. 从 trace 恢复的软件循环结构

### 4.1 顶层

真实 `stdout` 仍然给出：

- `init_run`
- `electrons`

### 4.2 `electrons` 的核心子阶段

- `c_bands`
- `sum_band`
- `v_of_rho`
- `newd`
- `mix_rho`

所以当前系统级对象仍然应理解为：

- `SCF outer loop` 驱动主流程
- `c_bands` 是波函数/子空间求解主循环
- 其余阶段负责电荷累积、势场更新、nonlocal 参数更新与混合闭环

### 4.3 `c_bands` 内部可见循环体

`bandsolver_trace.csv` 给出的显式阶段为：

- `init_basis` × 8
- `expand_basis` × 44
- `post_diag` × 44
- `refresh_gate` × 29
- `refresh_basis` × 21
- `converged_exit` × 8

并且可以直接看到：

- `npw = 2945`
- `nbnd = 16`
- `nkb = 144`
- `subspace_n / nbase` 在 `16 -> 32` 之间伸缩
- `notcnv` 在不同阶段从 `16` 逐步下降到 `0`

这说明 `davidson` 在真实 case 中就是一个**变宽子空间 + 对角化后裁剪/刷新 + 未收敛状态重放**的循环体。

### 4.4 `hpsi_trace` 给出的 operator-apply 视角

`hpsi_trace.csv` 给出：

- `h_psi` 与 `s_psi` 成对出现
- 绝大多数都处在 `solver_family = davidson`
- `nbnd_or_m` 不只出现 `16`，还会出现 `15 / 14 / 11 / 9 / 7 / 4 / 3 / 2 / 1`

这非常重要，因为它表明：

- 真正被反复下发到 operator-apply 路径的并不是一个固定宽度向量组
- 而是一组随着 `notcnv` 缩小而动态变化的候选向量块
- 后续 LCW 不能只表达“固定一批 band 做一次算子作用”，而必须支持“收敛筛选后对子集继续 replay”

### 4.5 `subspace_trace` 给出的 reduced-space 闭环视角

`subspace_trace.csv` 记录了 `rdiaghg` 侧的矩阵闭包对象：

- `n`
- `m`
- `h_frob`
- `s_frob`
- `h_herm_rel`
- `s_herm_rel`
- `s_identity_rel`

因此在软件层面，`rdiaghg` 不是孤立的求特征值调用，而是：

- 一个可观测的 reduced-space 闭包点
- 接收当前扩展子空间上的 `H`、`S` 投影矩阵
- 产出本轮 band 更新与收敛判断所需信息

## 5. 到硬件单元的第一版映射

下面只写当前已被真实执行支撑的保守映射。

### 5.1 `Command Scheduler`

对应的软件职责：

- `SCF` 外层阶段切换
- `c_bands` episode 进入/退出
- `davidson` replay body 选择
- `refresh_gate / converged_exit` 这类分支决策

需要承担的硬件职责：

- 解释 LCW 宽控制字
- 维护 episode 级状态机
- 根据 `notcnv`、`subspace_n`、对象就绪状态发起下一轮 replay
- 驱动 chip 内多个执行部件并保持对象版本一致性

### 5.2 `CIM / Projector-Apply Engine`

优先对应的软件对象：

- `h_psi:calbec`
- `calbec`
- `add_vuspsi`
- `h_psi` 中与非局域投影相关的路径

需要承担的硬件职责：

- 对当前波函数块执行 projector overlap / projector accumulation
- 输出 projector 系数对象与 nonlocal 修正结果对象
- 尽可能保持 projector 系数、beta 相关中间量在本地驻留

这也是当前最适合保持 `resident buffer tag` 连续性的单元之一。

### 5.3 `FFT Engine`

优先对应的软件对象：

- `fft`
- `ffts`
- `fftw`
- `g_psi` 中的表示切换与频域相关路径
- `vloc_psi` 中依赖网格/变换的部分

需要承担的硬件职责：

- 处理平面波 / 实空间之间的表示切换
- 支持局域势应用前后的数据布局变化
- 与 `Near-SRAM Support Domain` 协同处理分块重排和临时驻留

从本次 trace 看，`fftw` 调用次数非常高，所以它更像一个**高频支撑部件**而不是独立 episode。

### 5.4 `Near-SRAM Support Domain`

它在软件 trace 中通常不会被显式点名，但从 `expand_basis / refresh_basis / variable-width h_psi` 已经可以反推出其必要性。

需要承担的硬件职责：

- 波函数块、projector 系数、局部投影矩阵的近存储暂存
- basis 扩展/裁剪时的数据重排
- `notcnv` 收缩后对子集 band 块的局部 gather/scatter
- 维持对象句柄与物理驻留槽之间的映射

如果没有这一域，`refresh_basis` 这一类阶段会被迫退化成昂贵的全量搬运。

### 5.5 `Reduction / Closure / Solve Engine`

优先对应的软件对象：

- `rdiaghg`
- `post_diag`
- `converged_exit`
- `refresh_gate`

需要承担的硬件职责：

- 在 reduced-space 上做 `H/S` 闭包后的求解
- 收敛统计、残差/阈值相关控制支持
- 产出下一轮 band 子集、子空间宽度和刷新决策

这一单元不一定全部落在 CIM；它更像混合系统里需要兼容 dense closure 的专门求解域。

### 5.6 `SIMD / Vector Companion`

优先承担：

- 小规模向量更新
- 归一化、比例更新、残差整形
- `refresh_gate` 周围的轻量数值处理
- metadata 和对象头部维护辅助

它的意义不是取代主算子，而是避免每个小更新都回 Host 或强行塞进主矩阵部件。

## 6. 对 `LCW replay body` 的直接约束

这次真实执行已经足够把 replay body 从抽象词收紧成几个比较明确的类别。

### 6.1 `basis_init_body`

软件对应：

- `init_basis`

应完成：

- 为本轮 `c_bands` episode 建立初始 band 对象
- 绑定初始 `object handle`
- 建立起始 `resident buffer tag`

### 6.2 `expand_apply_body`

软件对应：

- `expand_basis`
- 同轮中的 `h_psi / s_psi / g_psi`
- projector + FFT + local potential 复合路径

应完成：

- 读取当前 band 子集对象
- 在多个执行部件上并发完成 `H`、`S` 相关作用
- 产出扩展子空间所需的新向量对象和中间对象

### 6.3 `closure_diag_body`

软件对应：

- `post_diag`
- `rdiaghg`

应完成：

- 触发 reduced-space `H/S` 闭包
- 求解并回写更新后的 band 信息
- 产出 `notcnv`、有效子空间宽度等控制结果

### 6.4 `refresh_body`

软件对应：

- `refresh_gate`
- `refresh_basis`

应完成：

- 根据收敛状态对子空间进行裁剪或压缩
- 重绑定新的 band 对象句柄与驻留槽
- 保留下一轮 replay 所需对象局部性

### 6.5 `converged_exit_body`

软件对应：

- `converged_exit`

应完成：

- 本轮 `c_bands` episode 收尾
- 向外层 `electrons` 提交收敛对象和必要摘要
- 释放或降级不再需要的驻留对象

## 7. 当前已解决与未解决的问题边界

### 7.1 已经被真实执行确认的部分

- `QE` 当前可稳定执行并抽取 trace
- `c_bands` 确实是多阶段 replay 式循环，而不是单次 dense solve
- `projector/nonlocal`、`FFT`、`reduced-space diagonalization` 三类对象在真实运行中共同出现
- band 子集宽度会随收敛过程动态变化
- `subspace_n` 和 `nbase` 会在有限窗口内扩展与回收，而不是单调增长

### 7.2 还没有完全冻结的部分

- `sum_band / v_of_rho / newd / mix_rho` 如何纳入更完整的全流程 LCW 目录
- `g_psi` 内部哪些部分值得独立成硬件功能，而不是归入 `FFT Engine`
- `rdiaghg` 最终更适合放在何种实现域：纯数字 dense solve、Host 辅助、还是近存储闭包域
- 对象驻留策略如何从 `QE` 推广到 `VASP / CP2K`

## 8. 当前最稳的结论

基于当前已跑通的 `QE` 证据，最稳的收口是：

- 顶层应继续坚持 **Host + FPGA/runtime + Chip** 的混合系统对象
- 芯片内控制核心应继续坚持 **LCW 宽控制字 + replay body**，而不是传统细粒度普通 ISA
- 但 replay body 现在不能只按静态模块定义，而必须反映 `QE davidson` 中真实存在的：
  - 子空间变宽
  - 未收敛 band 子集收缩
  - projector / FFT / closure 的复合联动

这也意味着下一步进入 `CP2K` 时，重点不是寻找表面上的同名函数，而是看它是否也存在：

- `outer SCF loop`
- `operator apply`
- `basis / density / overlap closure`
- `refresh / mixing / convergence gate`

这样的可复用 replay 骨架。
