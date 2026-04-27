# 2026-03-28 DFT 混合加速系统接口与 Route 合同 v0

## 1. 文档目标

这份文档是 `docs/architecture/system_design_master_spec_v0.md` 的接口配套文件。

它的目标不是重新定义整个系统，而是把当前已经在多份文档里零散出现的：

- `Host <-> FPGA/runtime` 接口字段
- `FPGA/runtime <-> Chip` replay / template / `LCW` 接口字段
- chip 内端点命名
- `LCW` 合法 route 集
- 对象状态在各接口层的可见性

整理成一份更接近硬件开发习惯的**正式接口合同草案**。

## 2. 文档范围

本文只覆盖当前 `v0` 已经比较稳的接口层内容：

1. `Host <-> FPGA/runtime` 的 episode / subgraph 级事务接口；
2. `FPGA/runtime <-> Chip` 的 replay body / patched template / `LCW` stream 接口；
3. chip 内端点与 v0 合法 route 集；
4. 对象句柄在接口层的最小状态可见性。

本文不覆盖：

- 精确位宽与编码；
- ready/valid 级握手时序；
- 异常恢复与 timeout 完整协议；
- power/clock/reset 真实实现；
- block-level RTL 寄存器图。

## 3. 接口分层总览

当前接口层固定分成三层：

| 层级 | 生产者 | 消费者 | 主对象 |
| --- | --- | --- | --- |
| L2 | `Host / software driver` | `FPGA / runtime orchestrator` | episode / subgraph request-response |
| L1 | `FPGA / runtime orchestrator` | `ChipTop / Command Scheduler` | replay bundle / replay body / patched template |
| L0 | `Command Scheduler` | chip 内执行域 | `LCW`、slot、route、commit |

推荐理解方式：

- `L2` 回答“这一轮软件子任务是什么”；
- `L1` 回答“这一组 body 怎么在 chip 上重放”；
- `L0` 回答“这一小阶段哪些模块激活、数据怎么流动”。

## 4. `Host <-> FPGA/runtime` 接口合同

### 4.1 v0 请求类型

当前 `v0` 先固定三类高层请求：

| 请求类型 | 作用 | 当前状态 |
| --- | --- | --- |
| `EPISODE_BEGIN` | 启动一个 `QE/VASP/CP2K` 风格 episode / subgraph | 稳定 |
| `EPISODE_QUERY` | 查询执行状态与摘要 | 稳定 |
| `EPISODE_ABORT` | 提前终止当前 episode | 预留 |

当前主线实际最稳定的是 `EPISODE_BEGIN` 与完成后的状态摘要。

### 4.2 `EpisodeRequest` 正式字段表

`EpisodeRequest` 继承 `docs/architecture/qe_band_solver_transaction_semantics_20260326.md` 中的最小语义，并在这里给出字段分类。

| 字段 | 类别 | 方向 | 必需性 | 说明 |
| --- | --- | --- | --- | --- |
| `episode_id` | 标识 | `Host -> FPGA` | 必需 | 本次 episode 唯一 id |
| `scf_iter_id` | 上下文 | `Host -> FPGA` | 必需 | 所属外层 `SCF` 轮次 |
| `software_family` | 模式 | `Host -> FPGA` | 必需 | `QE / VASP / CP2K` |
| `episode_kind` | 模式 | `Host -> FPGA` | 必需 | `CBANDS / BAND_UPDATE / OT_STEP / SCF_BUNDLE` 等 |
| `kpoint_id` | 上下文 | `Host -> FPGA` | 可选 | `k` 点编号 |
| `spin_id` | 上下文 | `Host -> FPGA` | 可选 | 自旋通道 |
| `nbnd` | 形状 | `Host -> FPGA` | 必需 | band 数摘要 |
| `npw` | 形状 | `Host -> FPGA` | 必需 | `G-space` 尺寸摘要 |
| `panel_cols` | 形状 | `Host -> FPGA` | 必需 | 当前 panel / tile 列宽 |
| `max_local_iters` | 策略 | `Host -> FPGA` | 必需 | 本地闭环最大迭代数 |
| `generalized_overlap` | 模式 | `Host -> FPGA` | 必需 | 是否启用 `Spsi` / generalized 路径 |
| `need_fft` | 模式 | `Host -> FPGA` | 必需 | 是否启用 `FFT_PREP` |
| `projector_set_id` | resident 上下文 | `Host -> FPGA` | 可选 | projector/beta 常驻集 id |
| `vloc_slice_id` | resident 上下文 | `Host -> FPGA` | 可选 | local potential slice id |
| `x_init_handle` | 对象 | `Host -> FPGA` | 必需 | 初始 `X/psi panel` 句柄 |
| `potential_epoch` | 版本 | `Host -> FPGA` | 可选 | 势场版本号 |
| `completion_policy` | 策略 | `Host -> FPGA` | 可选 | `BLOCKING / ASYNC / QUERYABLE` |

### 4.3 `EpisodeResponse` 正式字段表

| 字段 | 类别 | 方向 | 必需性 | 说明 |
| --- | --- | --- | --- | --- |
| `episode_id` | 标识 | `FPGA -> Host` | 必需 | 对应请求 id |
| `status` | 状态 | `FPGA -> Host` | 必需 | `OK / LOCAL_MAX_ITER / ERROR / ABORTED` |
| `local_iters_done` | 摘要 | `FPGA -> Host` | 必需 | 本地闭环完成轮数 |
| `converged_bands` | 摘要 | `FPGA -> Host` | 可选 | 已收敛 band 数 |
| `final_residual_max` | 摘要 | `FPGA -> Host` | 可选 | 最终最大残差 |
| `used_fft` | 摘要 | `FPGA -> Host` | 可选 | 本轮是否实际启用 FFT 路径 |
| `et_handle` | 对象 | `FPGA -> Host` | 可选 | 特征值/能量摘要对象句柄 |
| `evc_handle` | 对象 | `FPGA -> Host` | 可选 | 更新后波函数/子空间句柄 |
| `summary_state_id` | 调试/摘要 | `FPGA -> Host` | 可选 | 指向完整摘要状态 |

### 4.4 `Host <-> FPGA` 接口设计原则

当前这一层有三条稳定规则：

1. 传的是 episode / subgraph 级对象，而不是细粒度 `LCW`；
2. 只要求 Host 看见句柄、模式、摘要，不要求它逐轮管理局部 replay 状态；
3. `FPGA/runtime` 必须成为软件语义与 chip-side replay 之间的隔离层。

## 5. `FPGA/runtime <-> Chip` 接口合同

### 5.1 v0 事务对象

当前 `v0` 先固定四类对象：

| 对象 | 作用 | 当前状态 |
| --- | --- | --- |
| `ReplayBundleHeader` | 描述本次下发的 bundle 范围和约束 | 稳定 |
| `ReplayBodyDesc` | 描述单个 body 的身份、依赖、patch 信息 | 稳定 |
| `PatchedLCWWord` | 描述一条已 patch 的 `LCW` | 稳定 |
| `ReplayCompletionSummary` | body/bundle 完成摘要 | 稳定 |

### 5.2 `ReplayBundleHeader` 字段表

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `bundle_id` | 标识 | 必需 | bundle 唯一 id |
| `episode_id` | 标识 | 必需 | 归属 episode |
| `software_family` | 模式 | 必需 | `QE / VASP / CP2K` |
| `episode_kind` | 模式 | 必需 | `CBANDS / BAND_UPDATE / OT_STEP / SCF_BUNDLE` |
| `phase_begin` | 范围 | 必需 | 起始 phase |
| `phase_end` | 范围 | 必需 | 结束 phase |
| `body_count` | 范围 | 必需 | 含多少个 body |
| `replay_policy` | 策略 | 必需 | `NO_REPLAY / LOCAL_REPLAY / CONDITIONAL_REPLAY` |
| `exit_policy` | 策略 | 必需 | `UNTIL_DONE / UNTIL_LIMIT / FORCE_STOP` |
| `priority` | 调度 | 可选 | bundle 调度优先级 |

### 5.3 `ReplayBodyDesc` 字段表

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `body_id` | 标识 | 必需 | body 唯一 id |
| `body_kind` | 模式 | 必需 | `BODY_00..05`、`BODY_04A/B/C`、`BODY_10A/B/C` |
| `template_id` | 模板 | 必需 | 对应 replay/LCW 模板 |
| `dependency_mask` | 依赖 | 必需 | 依赖前序 body / barrier |
| `patch_mask` | patch | 必需 | 指示哪些字段会在本次实例中改写 |
| `max_replay_iters` | 策略 | 可选 | 允许的最大本地 replay 轮数 |
| `resident_context_id` | resident | 可选 | 本 body 绑定的 resident context |
| `resident_generation` | resident | 可选 | 绑定到哪一代 context |
| `row_block_count_hint` | resident | 可选 | 预计会遍历的 `row_block` 数 |
| `context_lock_policy` | resident | 可选 | `LOCK_ON_ENTER / HOLD_UNTIL_DONE / RELEASE_ON_EXIT` |
| `completion_mode` | 完成 | 必需 | `SYNC / QUERYABLE / ASYNC_OK` |
| `join_mode` | 完成 | 必需 | `HARD_BARRIER / SOFT_JOIN / NONE` |
| `export_mask` | 输出 | 可选 | 哪些结果要对外提交 |

### 5.3.1 `BODY_04A/B/C` 与 `BODY_10A/B/C` 的固定 `ReplayBodyDesc` 姿态

当前 `ReplayBodyDesc` 在 body 级不再允许把完成与 join 混写成一个模糊策略字段，而是固定拆成：

- `completion_mode`
- `join_mode`
- `replay_policy`

其中已经冻结到 system-visible body 级的主约束如下：

| sub-body | `completion_mode` | `join_mode` | `replay_policy` | `context_lock_policy` | `export_mask` 主集合 |
| --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `DENSITY_NEW_HANDLE` |
| `BODY_04B` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `HOLD_UNTIL_DONE` | `POTENTIAL_NEW_HANDLE`, `PROJECTOR_STATE_NEXT_HANDLE` |
| `BODY_04C` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `DENSITY_MIXED_HANDLE`, `SCF_HISTORY_NEXT_HANDLE`, `SCF_DECISION_HANDLE` |
| `BODY_10A` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `LOCK_ON_ENTER` | `UPDATED_WAVE_CANDIDATE` |
| `BODY_10B` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `HOLD_UNTIL_DONE` | `UPDATED_WAVE_OBJECT`, `UPDATED_PROJECTOR_OBJECT` |
| `BODY_10C` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `SEARCH_HISTORY_OBJECT`, `OT_DECISION_SUMMARY` |

这里最关键的接口判断是：

- `BODY_04A/B` 与 `BODY_10A/B` 继续保持严格提交边界；
- `BODY_04C` 与 `BODY_10C` 才允许作为 queryable summary 的可见点；
- `NO_REPLAY` 只限制 system-visible body 级自发扩环，不禁止 local hold 或 runtime 在 body/family 边界受控重发。

### 5.4 `PatchedLCWWord` 字段表

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `word_id` | 标识 | 必需 | 当前 `LCW` id |
| `phase_id` | 上下文 | 必需 | 所属 phase |
| `resident_context_id` | resident | 可选 | 当前 `LCW` 绑定的 context |
| `resident_generation` | resident | 可选 | 当前 generation |
| `row_block_id` | resident | 可选 | 当前活动工作块 |
| `active_mod_group_mask` | resident | 可选 | 当前激活 `G0/G1/G2` 组合 |
| `cim_operand_role` | resident | 可选 | `X_PANEL / COEFF_PANEL` |
| `cim_mode` | slot mode | 必需 | `IDLE / PROJECT / PROJECTOR_APPLY_CHAIN / BACKPROJECT` 等 |
| `fft_mode` | slot mode | 必需 | `IDLE / G_TO_R / R_TO_G / REORDER` |
| `sram_mode` | slot mode | 必需 | `STAGE / HOLD / FORWARD / MERGE_PARTIAL / ASSEMBLE_FULL / FEED_REDUCED` |
| `solve_mode` | slot mode | 必需 | `IDLE / REDUCE_BUILD / SOLVE / CLOSURE / CHECK` |
| `vector_mode` | slot mode | 必需 | `IDLE / PACK / MASK / LAYOUT / POSTPROC` |
| `route_mask` | route | 必需 | 本条 `LCW` 允许的 route 集 |
| `src_handle_0` | 对象 | 可选 | 输入句柄 0 |
| `src_handle_1` | 对象 | 可选 | 输入句柄 1 |
| `dst_handle_0` | 对象 | 可选 | 输出句柄 0 |
| `dst_handle_1` | 对象 | 可选 | 输出句柄 1 |
| `join_mode` | 完成 | 必需 | `HARD_BARRIER / SOFT_JOIN / NONE` |
| `completion_mode` | 完成 | 必需 | `SYNC / ASYNC_OK` |

### 5.5 `ReplayCompletionSummary` 字段表

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `bundle_id` | 标识 | 必需 | 对应 bundle |
| `body_id` | 标识 | 可选 | 对应 body；bundle 级可为空 |
| `status` | 状态 | 必需 | `OK / LIMIT / ERROR / ABORTED` |
| `replay_iters_done` | 摘要 | 可选 | 已完成 replay 轮数 |
| `export_handle_0` | 对象 | 可选 | 输出句柄 0 |
| `export_handle_1` | 对象 | 可选 | 输出句柄 1 |
| `residual_handle` | 对象 | 可选 | residual 对象 |
| `next_x_handle` | 对象 | 可选 | 下一轮 `X` 句柄 |
| `trace_state_id` | 调试/摘要 | 可选 | 指向内部 trace/summary |

### 5.6 `FPGA/runtime <-> Chip` 接口设计原则

当前这一层有四条稳定规则：

1. `FPGA/runtime` 下发的是模板实例与 body 序列，不是软件源代码级控制流；
2. `Chip` 只接收已 patch 的局部合同，不负责决定软件级 episode 边界；
3. `LCW` 字段中允许 patch 的部分要显式受限，不能无限制改写；
4. replay 导致的对象版本轮换应尽量在 chip 内闭合，不要求每轮都回报 Host。

## 6. Chip 内端点命名合同

### 6.1 顶层句柄端点

| 端点 | 类型 | 说明 |
| --- | --- | --- |
| `HANDLE_IN_0` | ingress | 主要输入对象句柄入口 |
| `HANDLE_IN_1` | ingress | 次要输入对象句柄入口 |
| `HANDLE_OUT_0` | egress | 主要输出对象句柄出口 |
| `HANDLE_OUT_1` | egress | 次要输出对象句柄出口 |

### 6.2 执行域本地端点

| 端点 | 所属域 | 说明 |
| --- | --- | --- |
| `FFT_IN` | `FFT Engine` | FFT 输入 |
| `FFT_OUT` | `FFT Engine` | FFT 输出 |
| `CIM_IN` | `CIM / Projector-Apply` | 聚合式 projector/operator 输入 |
| `CIM_OUT_H` | `CIM / Projector-Apply` | 聚合式 projector path 主结果输出 |
| `CIM_OUT_S` | `CIM / Projector-Apply` | 聚合式 projector/generalized 辅助输出 |
| `CIM_CTX_LOAD` | `CIM / Projector-Apply` | 常驻 context 装载入口 |
| `CIM_IN_X` | `CIM / Projector-Apply` | `PROJECT` 输入 |
| `CIM_IN_COEFF` | `CIM / Projector-Apply` | `BACKPROJECT` 系数输入 |
| `CIM_OUT_COEFF` | `CIM / Projector-Apply` | `PROJECT` 系数输出 |
| `CIM_OUT_ROW` | `CIM / Projector-Apply` | `BACKPROJECT` 行输出 |
| `SOLVE_IN` | `Reduction / Closure / Solve` | reduced / closure 输入 |
| `SOLVE_OUT_REDUCED` | `Reduction / Closure / Solve` | reduced build 输出 |
| `SOLVE_OUT_RITZ` | `Reduction / Closure / Solve` | Ritz / eig output |
| `VECTOR_IN` | `SIMD / Vector Companion` | vector companion 输入 |
| `VECTOR_OUT_RESIDUAL` | `SIMD / Vector Companion` | residual 输出 |
| `VECTOR_OUT_NEXT_X` | `SIMD / Vector Companion` | next-`X` 输出 |
| `VECTOR_OUT_MISC` | `SIMD / Vector Companion` | 其他后处理输出 |

### 6.3 近存端点与驻留域命名

| 端点 / tag | 所属域 | 说明 |
| --- | --- | --- |
| `SRAM_STAGE_BUF` | `Near-SRAM` | stage / forward 主缓冲 |
| `SRAM_CTX_LOAD_BUF` | `Near-SRAM` | 常驻 context 临时载荷缓冲 |
| `SRAM_COEFF_BUF` | `Near-SRAM` | `PROJECT` 系数与中间系数缓冲 |
| `SRAM_ROW_BUF` | `Near-SRAM` | `BACKPROJECT` 行结果缓冲 |
| `SRAM_PARTIAL_BUF_H` | `Near-SRAM` | 聚合式 `Hpsi` partial 缓冲 |
| `SRAM_PARTIAL_BUF_S` | `Near-SRAM` | 聚合式 `Spsi` partial 缓冲 |
| `SRAM_ASSEMBLER` | `Near-SRAM` | full/reduced 组装入口 |
| `SRAM_REDUCED_FEED` | `Near-SRAM` | reduced-build 喂入端 |
| `SRAM_META_BUF` | `Near-SRAM` | meta / reduced / mask / summary 缓冲 |

## 7. v0 合法 Route 集

### 7.1 设计原则

当前 `v0` 不允许全互连式自由 route，而只允许一组有限、可解释、可验证的合法 route。

判定一个 route 是否应进入 `v0` 合法集，必须同时满足：

- 它已被当前 `QE` 主线或 `LCW` lowering 直接需要；
- 它不会模糊模块职责边界；
- 它不会把系统偷偷推成完全开放的 crossbar。

### 7.2 合法 route 总表

| Route ID | Source | Sink | 主要 phase/body | 作用 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `R00` | `HANDLE_IN_0` | `SRAM_STAGE_BUF` | `BODY_00`, `LOAD_AND_STAGE` | 输入大对象先进入 stage 域 | 稳定 |
| `R01` | `HANDLE_IN_0` | `FFT_IN` | `FFT_PREP` | 直接把输入对象送入 FFT | 预留 |
| `R02` | `SRAM_STAGE_BUF` | `FFT_IN` | `FFT_PREP` | 由 stage 域送入 FFT | 稳定 |
| `R03` | `FFT_OUT` | `SRAM_STAGE_BUF` | `FFT_PREP` | FFT 输出回写 stage 域 | 稳定 |
| `R04` | `SRAM_STAGE_BUF` | `CIM_IN` | `PROJECTOR_FAMILY` | 聚合式 projector path 输入占位 route | 稳定 |
| `R05` | `SRAM_META_BUF` | `VECTOR_IN` | `PROJECTOR_FAMILY`, `LOOP_DECIDE` | mask / compact 元数据送入 vector 域 | 稳定 |
| `R06` | `CIM_OUT_H` | `SRAM_PARTIAL_BUF_H` | `PROJECTOR_FAMILY` | 聚合式 projector path 结果写入近存 | 稳定 |
| `R07` | `CIM_OUT_S` | `SRAM_PARTIAL_BUF_S` | `PROJECTOR_FAMILY` | generalized/projector 辅助结果写入近存 | 稳定 |
| `R08` | `SRAM_PARTIAL_BUF_H` | `SRAM_ASSEMBLER` | `ASSEMBLE_AND_REDUCE` | `H` partial 进入组装路径 | 稳定 |
| `R09` | `SRAM_PARTIAL_BUF_S` | `SRAM_ASSEMBLER` | `ASSEMBLE_AND_REDUCE` | `S` partial 进入组装路径 | 稳定 |
| `R10` | `SRAM_STAGE_BUF` | `SRAM_ASSEMBLER` | `ASSEMBLE_AND_REDUCE` | 当前 `X` 与 partial 在近存域汇合 | 稳定 |
| `R11` | `SRAM_REDUCED_FEED` | `SOLVE_IN` | `ASSEMBLE_AND_REDUCE` | reduced-build 输入送往 solve 域 | 稳定 |
| `R12` | `SOLVE_OUT_REDUCED` | `SRAM_META_BUF` | `ASSEMBLE_AND_REDUCE` | reduced object 回写 meta 域 | 稳定 |
| `R13` | `SRAM_META_BUF` | `SOLVE_IN` | `SOLVE_AND_CLOSE` | reduced / closure 输入送往 solve 域 | 稳定 |
| `R14` | `SOLVE_OUT_RITZ` | `VECTOR_IN` | `SOLVE_AND_CLOSE` | Ritz/eig 输出送往 vector 后处理 | 稳定 |
| `R15` | `VECTOR_OUT_RESIDUAL` | `SRAM_STAGE_BUF` | `SOLVE_AND_CLOSE` | residual 回写 stage 域 | 稳定 |
| `R16` | `VECTOR_OUT_NEXT_X` | `SRAM_STAGE_BUF` | `SOLVE_AND_CLOSE` | next-`X` 回写 stage 域 | 稳定 |
| `R17` | `SOLVE_OUT_RITZ` | `HANDLE_OUT_0` | episode egress | 导出 reduced/ritz 结果 | 预留 |
| `R18` | `VECTOR_OUT_NEXT_X` | `HANDLE_OUT_0` | episode egress | 导出下一阶段 `X` 对象 | 稳定 |
| `R19` | `VECTOR_OUT_MISC` | `HANDLE_OUT_1` | episode egress | 导出摘要/辅助对象 | 预留 |

### 7.3 当前明确不建议进入 `v0` 的 route

| 非法 / 不建议 route | 原因 |
| --- | --- |
| `HANDLE_IN_0 -> SOLVE_IN` | 跳过 stage/assemble 语义，会破坏系统分层 |
| `HANDLE_IN_0 -> HANDLE_OUT_0` | 没有经过任何受控执行域，不应成为 `LCW` 主路径 |
| `CIM_OUT_ROW -> SOLVE_IN` | 会把近存聚合与 reduced-build 责任偷塞进 solve 域 |
| `FFT_OUT -> HANDLE_OUT_0` | 直接出片会使 FFT 从系统主链支撑域退化成孤立工具核 |
| `VECTOR_OUT_NEXT_X -> CIM_IN_X` | 应通过 `SRAM_STAGE_BUF` 维护对象版本与驻留语义 |

### 7.4 route 与 slot 的一致性规则

- `FFT` 相关 route 只有在 `fft_mode != IDLE` 时才合法；
- `CIM` 相关 route 只有在 `cim_mode != IDLE` 时才合法；
- `SOLVE` 相关 route 只有在 `solve_mode != IDLE` 时才合法；
- `VECTOR` 相关 route 只有在 `vector_mode != IDLE` 时才合法；
- `SRAM` 相关 route 需要同时满足 `sram_mode` 与对象驻留状态一致。

### 7.5 `CIM` projector-family 细化 route 子集

当前 `R04-R07` 仍然可以作为聚合式 `CIM` route 入口理解，但如果进入 `resident_context + row_block` 级接口冻结，应进一步细化为：

| Route ID | Source | Sink | 主要 body/phase | 作用 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `R20` | `HANDLE_IN_1` | `SRAM_CTX_LOAD_BUF` | `BODY_00`, preload | runtime 下发 context 载荷对象 | 预留 |
| `R21` | `SRAM_CTX_LOAD_BUF` | `CIM_CTX_LOAD` | `BODY_00`, preload | 常驻 context 写入 `CIM` bank | 稳定 |
| `R22` | `SRAM_STAGE_BUF` | `CIM_IN_X` | `PROJECT`, `PROJECTOR_APPLY_CHAIN` | `X/psi panel` 送入 `PROJECT` | 稳定 |
| `R23` | `CIM_OUT_COEFF` | `SRAM_COEFF_BUF` | `PROJECT`, `PROJECTOR_APPLY_CHAIN` | 系数对象回写近存 | 稳定 |
| `R24` | `SRAM_COEFF_BUF` | `VECTOR_IN` | `PROJECTOR_APPLY_CHAIN` | 系数对象送入小变换 | 稳定 |
| `R25` | `VECTOR_OUT_MISC` | `SRAM_COEFF_BUF` | `PROJECTOR_APPLY_CHAIN` | 变换后系数回写近存 | 稳定 |
| `R26` | `SRAM_COEFF_BUF` | `CIM_IN_COEFF` | `BACKPROJECT`, `PROJECTOR_APPLY_CHAIN` | 系数对象送入 `BACKPROJECT` | 稳定 |
| `R27` | `CIM_OUT_ROW` | `SRAM_ROW_BUF` | `BACKPROJECT`, `PROJECTOR_APPLY_CHAIN` | 回投影行结果回写近存 | 稳定 |
| `R28` | `SRAM_ROW_BUF` | `SRAM_ASSEMBLER` | `PROJECTOR_APPLY_CHAIN` | 行结果送往聚合路径 | 稳定 |

这组 route 的详细对象语义，见：

- `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`

### 7.6 `BODY_04/10` runtime-managed body route 子集

当前 `BODY_04A/B/C` 与 `BODY_10A/B/C` 主要复用 `Vector`、`FFT`、`SRAM_META_BUF`、`SRAM_STAGE_BUF` 这条 runtime-managed body 路线。

为避免 outer-update / OT extension 一直停留在“只有 body 名，没有接口骨架”的状态，当前额外冻结下面这组 route：

| Route ID | Source | Sink | 主要 body | 作用 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `R29` | `HANDLE_IN_0` | `VECTOR_IN` | `BODY_04A/B/C`, `BODY_10A/C` | 主输入对象直接送入 `Vector` 域 | 稳定 |
| `R30` | `HANDLE_IN_1` | `VECTOR_IN` | `BODY_04B/C`, `BODY_10B/C` | 次输入 / history / projector / metric 对象送入 `Vector` 域 | 稳定 |
| `R31` | `VECTOR_OUT_MISC` | `SRAM_META_BUF` | `BODY_04A/B/C`, `BODY_10B/C` | runtime-managed body 中间结果与 meta 摘要回写近存 | 稳定 |
| `R32` | `SRAM_META_BUF` | `HANDLE_OUT_0` | `BODY_04A/B/C`, `BODY_10B` | 主结果对象从 meta 域导出 | 稳定 |
| `R33` | `SRAM_META_BUF` | `HANDLE_OUT_1` | `BODY_04B/C`, `BODY_10B/C` | 辅结果 / history / decision 对象从 meta 域导出 | 稳定 |
| `R34` | `FFT_OUT` | `VECTOR_IN` | `BODY_04B` | support-grid 刷新后结果送入 `Vector` 后处理 | 稳定 |
| `R35` | `SRAM_STAGE_BUF` | `VECTOR_IN` | `BODY_10B` | 已暂存的 OT wave candidate 送入正交化 / rebind 路径 | 稳定 |
| `R36` | `VECTOR_OUT_MISC` | `SRAM_STAGE_BUF` | `BODY_10A/B` | OT update / rebind 候选对象回写 stage 域供下一 sub-body 使用 | 稳定 |

这些 route 与已有 `R01/R02/R03/R34`、`R35/R36` 一起，构成 `BODY_04A/B/C` 与 `BODY_10A/B/C` 的 canonical body route skeleton。

### 7.6.1 `BODY_04A/B/C` route skeleton 与对象交接

为了避免 `BODY_04` 继续只停留在 family 名称而不具备对象交接闭环，当前把 `Phase C/D/E` 三段 canonical route chain 固定如下：

| sub-body | canonical route chain | 输入对象 | 输入状态要求 | 输出对象 | 输出状态结果 |
| --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0` | phase-B wave object + active-band/density context | wave=`READY`，mask/context=`PATCHED/READY` | `density_new_handle` | 先 `PATCHED`，再 `EXPORTED`，producer=`BODY_04A` |
| `BODY_04B` (`support_grid=ON`) | `HANDLE_IN_0 -> FFT_IN -> FFT_OUT -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | new density object + projector state object | density=`READY`，projector=`READY/RESIDENT` | `potential_new_handle`, `projector_state_next_handle` | 先 `READY`，再 `EXPORTED`，producer=`BODY_04B` |
| `BODY_04B` (`support_grid=BYPASS`) | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | new density object + projector state object | density=`READY`，projector=`READY/RESIDENT` | `potential_new_handle`, `projector_state_next_handle` | 同上 |
| `BODY_04C` | `HANDLE_IN_0 + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | density old/new object + potential/history object | density=`READY`，history/summary 至少可查询 | `density_mixed_handle`, `scf_history_next_handle`, `scf_decision_handle` | mixed-density=`EXPORTED`，decision=`QUERYABLE + EXPORTED`，producer=`BODY_04C` |

这组 canonical route chain 和 `R29-R34` 的关系应理解为：

- `R29/R30` 负责把 `BODY_04` 的 body-visible 输入句柄接到 `Vector`；
- `R01/R02/R03/R34` 只在 `BODY_04B` 需要 support-grid 刷新时插入；
- `R31/R32/R33` 负责 `BODY_04A/B/C` 的 meta/result 提交；
- `BODY_04C` 的 queryable decision 仍然必须经过受控 commit，不能绕开 `SRAM_META_BUF` 直接伪装成完成。

### 7.6.2 `BODY_10A/B/C` route skeleton 与对象交接

为了避免 `BODY_10` 继续停留在“只有 route id，没有接口闭环”的状态，当前把三段 OT extension 的 canonical route chain 进一步固定如下：

| sub-body | canonical route chain | 输入对象 | 输入状态要求 | 输出对象 | 输出状态结果 |
| --- | --- | --- | --- | --- | --- |
| `BODY_10A` | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_STAGE_BUF` | phase-B wave object + residual object | `READY` | `wave_candidate_object` | `STAGED`，producer=`BODY_10A` |
| `BODY_10B` | `SRAM_STAGE_BUF + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | staged wave candidate + projector / metric object | candidate=`STAGED`，context=`READY/RESIDENT` | `updated_wave_object`, `updated_projector_object` | 先 `READY`，再 `EXPORTED`，producer=`BODY_10B` |
| `BODY_10C` | `HANDLE_IN_0 + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_1` | rebound wave object + prior history object | wave=`READY/EXPORTED`，history=`READY` 或摘要可查询 | `search_history_object`, `ot_decision_summary` | history=`EXPORTED`，decision=`QUERYABLE + EXPORTED`，producer=`BODY_10C` |

这组 canonical route chain 和 `R29-R36` 的关系应理解为：

- `R29/R30` 负责把 body-visible 输入句柄接到 `Vector`；
- `R35/R36` 负责 `BODY_10A/B` 中 wave candidate 的 stage-buffer 交接；
- `R31/R32/R33` 负责 `BODY_10B/C` 的 meta/result 提交；
- `BODY_10C` 的 queryable decision 仍然必须经过受控 commit，不能绕开 `SRAM_META_BUF` 直接伪装成完成。

## 8. 对象状态可见性合同

### 8.1 v0 最小对象状态集合

| 状态 | 定义 | `Host` 可见 | `FPGA/runtime` 可见 | `Chip` 可见 |
| --- | --- | --- | --- | --- |
| `BOUND` | 已绑定到 episode，但尚未进入 chip 本地流 | 是 | 是 | 否 |
| `PATCHED` | 已写入 body / `LCW` patch 点 | 否 | 是 | 是 |
| `STAGED` | 已进入 `SRAM_STAGE_BUF` 等近存域 | 否 | 摘要可见 | 是 |
| `RESIDENT` | 已在片上常驻域中保持可复用 | 否 | 摘要可见 | 是 |
| `READY` | 当前可被后续 route/slot 消费 | 否 | 摘要可见 | 是 |
| `EXPORTED` | 已通过 `HANDLE_OUT_x` 对外提交 | 是 | 是 | 是 |
| `RETIRED` | 本轮结束或被回收，不再可消费 | 否 | 摘要可见 | 是 |

### 8.2 对象状态主规则

- `Host` 主要看见 `BOUND` 与 `EXPORTED` 层面的对象；
- `FPGA/runtime` 主要看见 patch 和 body 完成后的对象摘要；
- `Chip` 必须完整维护 `STAGED / RESIDENT / READY / RETIRED` 的局部状态机；
- 当前 `v0` 还没有冻结异常状态，如 `ERROR`, `TIMEOUT`, `CORRUPT` 等对象态。

### 8.3 `BODY_04` 对象状态主规则

当前 `BODY_04A/B/C` 至少冻结下面四条对象状态规则：

1. `BODY_04A` 不接受已经 `RETIRED` 的 phase-B wave 对象；
2. `BODY_04B` 进入前，`density_new_handle` 必须已经由 `BODY_04A` 提交完成，并处于 `READY`；
3. `BODY_04C` 进入前，`potential_new_handle` 与 `projector_state_next_handle` 至少应处于 `READY` 或摘要可见；
4. `scf_decision_handle` 允许 `QUERYABLE`，但不能跳过 `EXPORTED` / commit 语义伪装成“未提交也可消费”。

### 8.4 `BODY_10` 对象状态主规则

当前 `BODY_10A/B/C` 至少冻结下面四条对象状态规则：

1. `BODY_10A` 不接受已经 `RETIRED` 的 phase-B wave / residual 对象；
2. `BODY_10B` 进入前，`wave_candidate_object` 必须已经位于 `SRAM_STAGE_BUF`，状态为 `STAGED`；
3. `BODY_10C` 进入前，`updated_wave_object` 与 `updated_projector_object` 至少应处于 `READY` 或已导出摘要可见；
4. `ot_decision_summary` 允许 `QUERYABLE`，但不能跳过 `EXPORTED` / commit 语义伪装成“未提交也可消费”。

## 9. 当前已冻结与未冻结部分

### 9.1 已冻结到可继续推进的内容

- 三层接口分层已经稳定；
- `EpisodeRequest / EpisodeResponse` 的核心字段已经稳定；
- `ReplayBundleHeader / ReplayBodyDesc / PatchedLCWWord / ReplayCompletionSummary` 已能支撑当前主线；
- chip 内端点命名与 `QE` 主线所需 route 集已经可以成表表达；
- `BODY_04A/B/C` 与 `BODY_10A/B/C` 的 route skeleton、对象状态前提与提交边界已经进入正式接口合同。

### 9.2 仍未冻结的内容

- 精确位宽、编码方式与压缩格式；
- body/bundle 的异常恢复语义；
- backpressure / 仲裁 / credit / timeout 规则；
- `BODY_10A/B/C` 之下更深的 sparse/AO mixed object 类型与 patch 字段；
- `Phase C/D/E` 完整下沉后新增的 route 和端点；
- `VASP / CP2K` 进入 v1 后对 route 集和对象态的扩展。

## 10. 与其他文档的关系

- `docs/architecture/system_design_master_spec_v0.md`
  - 主系统设计总规范；
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`
  - 事务字段的最早语义来源；
- `docs/control/long_control_word_isa_v0.md`
  - `LCW` slot/route 语法，以及 `object handle / resident buffer / version` 控制术语来源；
- `docs/control/qe_cbands_lcw_lowering_v0.md`
  - `QE c_bands` 主线对 route 的直接需求来源；
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
  - timeout、abort、soft stall 与错误升级边界来源；
- `docs/control/qe_phase_cde_replay_bundle_contract_v0.md`
  - `Phase C/D/E` 下沉后 bundle/route 扩展的直接接口约束来源。
- `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`
  - `resident_context / row_block / coeff-row transient object` 的细化接口合同来源。

## 11. 当前一句话结论

> 这份文档把原先散落在事务语义、LCW 和 lowering 文档里的接口约束，第一次整理成了一套可以继续向 block-level spec 细化的正式接口合同草案。
