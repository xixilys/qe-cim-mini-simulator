# 2026-03-28 QE / CP2K replay-body catalog v0

## 1. 目标

这份文档的作用，是把前面已经拿到的两类证据真正收口成一套可复用的控制骨架：

- `QE` 侧的真实执行证据
- `CP2K` 侧的源码/benchmark 主流程恢复

目标不是证明两套软件完全同构，而是回答更关键的问题：

> 如果 chip 顶层要继续坚持 `LCW + replay body`，那么哪些 replay body 是可以跨软件共用的，哪些只是 `QE` 或 `CP2K` 的专用压力项？

本文是后续全流程 `SystemC` 扩展与模块实现冻结之间的桥梁文档。

## 2. 当前证据边界

### 2.1 已执行证据

当前只有 `QE` 拿到了本地真实运行证据：

- `docs/benchmarks/results/qe_autonomous_h2_tiny/`
- `docs/benchmarks/results/qe_autonomous_si8_uspp/`

其中 `si8_pbe_uspp` 已足够代表一个比极小 demo 更真实的 `c_bands` episode。

### 2.2 非执行重构证据

`CP2K` 当前仍然是：

- 源码可读
- benchmark 输入可读
- 主机上暂不直接执行

因此本文对 `CP2K` 的所有判断，都是：

- `Quickstep + SCF + DIAGONALIZATION / OT + DBCSR + Poisson/grid`

这一层的结构恢复，而不是本地运行 trace。

## 3. replay-body 设计原则

为了让 replay catalog 真的能用于 chip 顶层，而不是停留在流程图命名上，这里先固定三条原则。

### 3.1 replay body 是 episode 内可重复下发的局部模板

每个 replay body 必须满足：

- 可以由 `Host / FPGA/runtime` 通过少量 patch 参数复用
- 可以由 `Command Scheduler` 在 chip 内部多次 replay
- 输入/输出对象边界清晰，能绑定 `object handle`

### 3.2 replay body 不等于单一算子

对于当前工作负载，真正可复用的最小对象，通常不是：

- 一次矩阵乘
- 一次 FFT
- 一次对角化

而是由多部件组成的局部闭环，例如：

- `operator apply + temporary resident staging + local closure`
- `refresh gate + basis compact + object rebinding`

### 3.3 replay body 要同时表达共性与分叉

如果 catalog 只保留共性，它会太空泛；
如果 catalog 只保留 `QE` 细节，它就无法承接 `CP2K`。

因此本文采用三层表示：

- `Common body`：跨软件都成立的骨架
- `QE specialization`：从真实执行中可直接钉住的路径
- `CP2K pressure`：当前必须为未来兼容预留的扩展点

## 4. 第一版公共 replay-body 集

### 4.1 `outer_scf_control_body`

#### 作用

负责一轮电子结构外层迭代中的：

- phase 切换
- 依赖检查
- episode 启停
- 全局收敛门控

#### 当前软件映射

`QE`：

- `electrons`
- `c_bands`
- `sum_band`
- `v_of_rho`
- `newd`
- `mix_rho`

`CP2K`：

- `scf`
- `scf_env_do_scf`
- mixing / DIIS / OT / diagonalization 外层调度

#### 芯片职责

- 不是纯 chip 内自治完成，而是 `Host + FPGA/runtime + Chip` 的分层控制接口
- chip 侧主要接收“本轮要执行哪个局部 episode”
- `Host / FPGA/runtime` 侧维护更高层 SCF 历史、阈值、软件态对象

#### 当前结论

这一 body 不应全塞进 chip；
它更像是混合系统的顶层协议骨架。

### 4.2 `basis_seed_and_bind_body`

#### 作用

负责为一个局部求解 episode 建立起点对象：

- 初始 band / orbital block
- 初始 resident buffer tag
- 需要保留的历史方向或辅助对象

#### 当前软件映射

`QE`：

- `init_basis`

`CP2K`：

- 对角化路线中的初始 MO / overlap 环境绑定
- `OT` 路线中的 `ot_scf_init`

#### 芯片职责

- 为对象分配近存储槽位
- 绑定本轮要用的输入句柄
- 记录是否存在历史方向对象、正交化对象或预条件对象

#### 当前结论

这是一个明显可跨软件共用的 body，只是 `QE` 和 `CP2K` 的输入对象类型不同。

### 4.3 `operator_apply_body`

#### 作用

对当前候选向量/轨道对象执行主算子作用，并把中间对象留在本地可复用状态。

#### 当前软件映射

`QE`：

- `h_psi`
- `s_psi`
- `h_psi:calbec`
- `calbec`
- `add_vuspsi`
- `vloc_psi`
- `fft / fftw / ffts`
- `g_psi` 中与表示变换相关的路径

`CP2K`：

- `qs_ks_build_kohn_sham_matrix` 相关局部 apply 压力
- `OT` 路线中的矩阵-轨道更新子步
- `DBCSR` 主导的块矩阵乘/旋转/正交化前置算子
- `pw_poisson_solve` / grid transform 相关支撑域

#### 芯片职责

它不是一个单模块 body，而是由多个 slot 协同完成：

- `CIM / Projector-Apply Engine`
- `FFT Engine`
- `Near-SRAM Support Domain`
- `SIMD / Vector Companion`

#### 当前结论

这是 replay catalog 里最核心的 body。
它已经被 `QE` 真实执行明确支持，而且对 `CP2K` 仍然成立，只是：

- `QE` 更偏 plane-wave + projector/nonlocal
- `CP2K` 更偏 AO / DBCSR / GPW 混合对象

### 4.4 `reduced_closure_solve_body`

#### 作用

把本轮构造好的局部子空间或闭包对象送入 reduced solve / closure domain，产出本轮更新方向与收敛摘要。

#### 当前软件映射

`QE`：

- `post_diag`
- `rdiaghg`

`CP2K`：

- `&DIAGONALIZATION`
- `CHOLESKY INVERSE_DBCSR`
- `ELPA / ScaLAPACK` 后端压力
- 以及与 overlap/orthogonality 相关的闭包求解路径

#### 芯片职责

- 形成 reduced `H / S` 或等价闭包对象
- 进行求解、规范化或回写
- 形成对下一轮有效的收敛摘要

#### 当前结论

这一 body 也是强共性 body。
但它的实现自由度很大：

- `QE` 目前更像 reduced generalized eigensolve
- `CP2K` 可能需要更一般的 closure / factorization / diagonalization 接口

### 4.5 `refresh_compact_rebind_body`

#### 作用

根据本轮求解结果进行：

- 未收敛对象筛选
- basis 紧缩/裁剪
- 历史方向维护
- object handle 重绑定

#### 当前软件映射

`QE`：

- `refresh_gate`
- `refresh_basis`
- `converged_exit`

`CP2K`：

- 外层 mixing 之前的密度/轨道刷新
- `OT` 路线中的方向重用、旋转对象更新
- DIIS / Broyden 缓冲区更新压力

#### 芯片职责

- 在近存储内完成 gather/scatter/compact
- 只保留下一轮所需对象
- 维护对象版本、驻留状态和部分历史

#### 当前结论

这是过去最容易被忽略、但对 chip 数据移动最关键的 body。
`QE` 的真实 trace 已经证明它不是边角步骤，而是显式阶段。

### 4.6 `density_potential_mix_body`

#### 作用

在 band/orbital 更新之后，完成外层 SCF 所需的密度、电势与混合闭环。

#### 当前软件映射

`QE`：

- `sum_band`
- `v_of_rho`
- `newd`
- `mix_rho`

`CP2K`：

- `Kohn-Sham matrix / density` 更新
- Poisson / grid 支撑
- mixing / DIIS / Broyden

#### 芯片职责

这部分是否要大规模下沉到 chip 仍未冻结，但至少要在系统模型中明确：

- 它是完整 DFT flow 不可或缺的 replay family
- 不能永远只把它当成 host 侧黑箱

#### 当前结论

这是下一阶段全流程 `SystemC` 扩展的关键 body；
目前证据足够确认它存在，但还不足以冻结其 chip / host 分工。

## 5. `QE` 与 `CP2K` 的 replay 共性矩阵

### 5.1 强共性 body

下面这些 body 当前已经足够作为共性 catalog 冻结为 v0：

- `outer_scf_control_body`
- `basis_seed_and_bind_body`
- `operator_apply_body`
- `reduced_closure_solve_body`
- `refresh_compact_rebind_body`

### 5.2 中等共性 body

- `density_potential_mix_body`

之所以只算中等共性，不是因为它不存在，而是因为：

- `QE` 路径我们已经知道它显式存在
- `CP2K` 路径也肯定存在相应闭环
- 但还没把它压缩成统一的对象接口与 LCW 参数表

### 5.3 `CP2K` 专属压力项

当前需要在 catalog 中保留“尚未吸收进公共 body”的压力项：

- `DBCSR block-sparse object support`
- `OT-specific orbital update body`
- `AO / GPW / grid hybrid object conversion`
- 更可切换的 diagonalization backend contract

这些不是独立否定现有 LCW 路线，而是提示：

- v0 catalog 主要捕获了共性骨架
- v1 需要开始引入 `CP2K` 扩展参数或分支 body

## 6. 对顶层 LCW 的直接影响

### 6.1 LCW 不该只发单模块模式位

从 replay catalog 来看，LCW 至少要表达：

- body 类型
- 输入对象句柄
- 输出对象句柄
- 哪些 slot 激活
- slot 间 route 组合
- 完成后是否 compact / commit / rebind

否则就无法区分：

- `QE expand_apply`
- `QE refresh_basis`
- `CP2K OT update`
- `CP2K density/mixing`

这些结构上不同的局部闭环。

### 6.2 最稳的 v0 body 编号建议

建议后续 LCW 文档先固定如下 body family 编号：

- `BODY_00`：`basis_seed_and_bind_body`
- `BODY_01`：`operator_apply_body`
- `BODY_02`：`reduced_closure_solve_body`
- `BODY_03`：`refresh_compact_rebind_body`
- `BODY_04`：`density_potential_mix_body`
- `BODY_05`：`outer_scf_control_body`
- `BODY_10+`：软件专属扩展 body，例如 `CP2K OT`、未来 `VASP` 压力项

这样能让 catalog 先稳住共性，再给未来分支保留编码空间。

## 7. 与当前 SystemC 原型的关系

当前 `model/qe_band_solver_model/` 已经实现的，其实主要覆盖了：

- `basis_seed_and_bind_body` 的一小部分
- `operator_apply_body`
- `reduced_closure_solve_body`
- `refresh_compact_rebind_body` 的一小部分

而明显还没有覆盖完整的：

- `outer_scf_control_body`
- `density_potential_mix_body`
- `CP2K OT / DBCSR` 压力项

因此，下一步全流程 `SystemC` 扩展最自然的做法，不是推翻当前 `c_bands` demo，而是：

- 把它重解释为 replay catalog 中的 `BODY_01 + BODY_02 + BODY_03` 子系统
- 再往上补 `BODY_05` 与 `BODY_04`
- 再为未来 `CP2K` 加接口挂点

## 8. 当前最稳的结论

基于当前 `QE` 执行证据和 `CP2K` 源码恢复，最稳的收口是：

- `LCW + replay body` 方向不但没有被削弱，反而被强化了
- 但 replay body 不应只围绕 `QE c_bands` 细节命名，而应提升到跨软件共性骨架
- 当前最适合作为 v0 冻结对象的，是 `6` 类 replay family，其中 `5` 类已经足够明确，`1` 类需要在全流程 SystemC 中进一步压实

这意味着接下来最合理的推进方式是：

1. 用这份 catalog 作为语言层，把现有 `QE c_bands` demo 重新编号归类
2. 写一份完整 DFT flow 的 `SystemC` 扩展纲要
3. 再决定哪些 body 真正下沉到 chip，哪些继续保留在 `Host / FPGA/runtime` 层
