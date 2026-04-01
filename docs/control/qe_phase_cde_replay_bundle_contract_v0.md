# 2026-03-29 QE `Phase C/D/E` Replay Body Catalog 合同 v0

## 1. 文档目标

这份文档的目标，是把当前已经存在于：

- `model/qe_band_solver_model/` 的行为级 `Phase C/D/E`
- `docs/architecture/qe_full_dft_systemc_extension_outline_v0.md`
- `docs/architecture/system_design_master_spec_v0.md`

中的 outer-update 路径，正式收口成一套**已经冻结到 system-visible body 编号层**的合同。

本轮要解决的问题，不再是“要不要继续把 `Phase C/D/E` 当成一个过渡 family”，而是明确：

- `BODY_04` 继续保留为 family alias；
- 但 system-visible catalog 正式冻结为 `BODY_04A/B/C`；
- 更深的 leaf-block / kernel lowering / route id 仍然留在 body 之下，不再继续拿 body 编号承载。

## 2. 当前状态与核心决策

### 2.1 当前已实现状态

当前 `model/qe_band_solver_model` 已经具备：

- `DensityAccumulationStage` 对应 `Phase C / sum_band`
- `PotentialRefreshStage` 对应 `Phase D / v_of_rho + newd`
- `MixingConvergenceStage` 对应 `Phase E / mix_rho + convergence gate`
- `Body04StageRequest` / `Body04StageSummary` 作为 stage 级合同对象
- `Body04BundleRequest` / `Body04BundleSummary` 作为 family 级合同对象
- `Body04LoweringPlan` / `Body04StageDescriptor` 作为 lowering 对象
- `Body04FamilyController` / `OuterUpdateRuntimeDomain` 作为显式运行时域

并且每个 stage 已经导出：

- `reference-cycle`
- `critical_unit`
- `unit occupancy`
- leaf-block `accept/busy/complete`
- ingress / egress owner
- `backpressure` 摘要

因此，`BODY_04` 已经不再是“只有 bundle 名字的 host 后处理”，而是一个带结构化统计和叶块代理的 timed-functional 运行时域。

### 2.2 本轮冻结决策

本轮正式冻结下面三条：

1. `BODY_04` 保留为 outer-update family alias；
2. system-visible sub-body catalog 冻结为 `BODY_04A/B/C`；
3. `BODY_04` 之下更深的 `density / potential / mixing` kernel 细节继续放在 descriptor / mode / lowering / leaf-block 层，而不是继续发散成更多 body 编号。

因此，从本文件开始：

> `BODY_04` 不再是“尚未决定是否拆分”的过渡项，而是“family alias + frozen sub-body catalog”的正式写法。

## 3. 为什么现在必须冻结 `BODY_04A/B/C`

如果 `Phase C/D/E` 继续长期停留在“过渡 family，之后再说”的状态，会同时带来三个问题：

1. 系统级 body catalog 在 `Phase B` 之后出现明显断层；
2. `QE / VASP / CP2K` 的 outer-update 兼容讨论无法落到明确 body 边界；
3. `SystemC` 模型里已经显式存在的三段对象交接、leaf-block 时序和 lowering 对象，无法进入正式主规范。

而当前证据已经足够支持下面这个层次划分：

- body 层：冻结 `BODY_04A/B/C`
- lowering 层：继续描述 route / assist engine / residency action
- leaf-block 层：继续描述 `accept/busy/complete` 与参考周期

这正是当前最像硬件开发文档的收口方式。

## 4. `BODY_04 family` 的外部合同

### 4.1 对外身份

对主规范与 runtime 而言，`BODY_04` 继续统一表示：

- `density accumulation`
- `potential / nonlocal refresh`
- `mixing / convergence gate`

组成的一个 outer-update family。

但从 body 编号层看，`BODY_04_FAMILY` 必须按固定顺序 lower 成：

```text
BODY_04A_DENSITY_ACCUM
  -> BODY_04B_POTENTIAL_REFRESH
  -> BODY_04C_MIX_CONVERGE
```

### 4.2 对外输入对象

当前建议固定以下主要输入：

| 输入对象 | 含义 | 来源 |
| --- | --- | --- |
| `WAVE_OUT_HANDLE` | `Phase B` 后更新后的波函数/轨道对象 | `BODY_03` 导出 |
| `DENSITY_OLD_HANDLE` | 上一轮密度对象 | `Phase A/E` 持续对象 |
| `POTENTIAL_OLD_HANDLE` | 上一轮势对象 | `Phase A/E` 持续对象 |
| `PROJECTOR_STATE_HANDLE` | 当前 projector/nonlocal 状态 | `Phase D` 持续对象 |
| `SCF_HISTORY_HANDLE` | mixing 历史对象 | `Phase E` 持续对象 |

### 4.3 对外输出对象

| 输出对象 | 含义 | 供谁消费 |
| --- | --- | --- |
| `DENSITY_NEW_HANDLE` | 新密度对象 | `BODY_04B/C` |
| `POTENTIAL_NEW_HANDLE` | 新势对象 | 下一轮 `BODY_01-03` 与 `BODY_04C` |
| `PROJECTOR_STATE_NEXT_HANDLE` | 更新后的 projector/nonlocal 辅助状态 | 下一轮 `BODY_01-03` |
| `DENSITY_MIXED_HANDLE` | 混合后的密度对象 | 下一轮 `SCF` |
| `SCF_HISTORY_NEXT_HANDLE` | 更新后的历史对象 | 下一轮 `BODY_04C` / outer control |
| `SCF_DECISION_HANDLE` | convergence / continue 判定摘要 | `BODY_05` |

## 5. 正式 `BODY_04` sub-body catalog

### 5.1 catalog 总表

| body id | 软件对应 | 主要功能 | 当前执行类 | 当前状态 |
| --- | --- | --- | --- | --- |
| `BODY_04A_DENSITY_ACCUM` | `sum_band` | 从波函数/轨道对象形成新密度对象 | runtime-managed timed-functional body | 冻结 |
| `BODY_04B_POTENTIAL_REFRESH` | `v_of_rho + newd` | 刷新势场与 projector/nonlocal 辅助状态 | runtime-managed timed-functional body | 冻结 |
| `BODY_04C_MIX_CONVERGE` | `mix_rho + convergence gate` | 混合新旧状态并形成继续/停止决策 | runtime-managed timed-functional body | 冻结 |

### 5.2 family 顺序与跳过规则

当前 `v0` 固定下面三条规则：

1. `BODY_04_FAMILY` 的顺序固定为 `04A -> 04B -> 04C`；
2. `04A/04B/04C` 在 `QE` 主线下都属于 mandatory body，不允许 runtime 任意跳过；
3. 可选 `FFT` assist、support-grid、nonlocal refresh 细分、mixing mode 差异，都继续放在 body 内 descriptor / mode / lowering 层，而不是通过删改 body 编号表达。

这意味着当前不会再引入：

- `BODY_04D`
- `BODY_04E`
- 针对某个辅助 kernel 单独新增的一串 outer-update body 编号

## 6. `BODY_04A` 合同：density accumulation

### 6.1 软件对应

- `sum_band`

### 6.2 主要功能

- 消费 `Phase B` 导出的更新波函数/轨道对象；
- 形成新的 `DensityObject`；
- 产生供 `BODY_04B` 消费的密度句柄与摘要。

### 6.3 当前推荐执行域

当前 `v0` 把它定义成：

- `FPGA/runtime` 主导；
- `Vector Companion + Near-SRAM Support Domain` 提供局部数据组织/后处理支持；
- 不要求它完全压入 `CIM` 主路径。

### 6.4 主要输入输出

| 输入 | 输出 |
| --- | --- |
| `WAVE_OUT_HANDLE` | `DENSITY_NEW_HANDLE` |
| `ACTIVE_BAND_MASK_HANDLE` | `DENSITY_ACCUM_SUMMARY_HANDLE` |
| `SCF_ITER_CONTEXT_HANDLE` |  |

### 6.5 completion / join 规则

- `completion_mode = SYNC`
- `join_mode = HARD_BARRIER`

因为 `BODY_04B` 不允许消费一个不完整的 density 对象。

### 6.6 当前叶块映射

```text
BODY_04A_DENSITY_ACCUM
  -> DensityAccumulatorUnit.Reduce
  -> DensityCommitUnit.Commit
```

## 7. `BODY_04B` 合同：potential / nonlocal refresh

### 7.1 软件对应

- `v_of_rho`
- `newd`

### 7.2 主要功能

- 消费 `DENSITY_NEW_HANDLE`；
- 形成新一轮 `PotentialObject`；
- 更新 projector/nonlocal 相关辅助状态；
- 产出下一轮 `BODY_01-03` 可直接绑定的势场与 projector 状态句柄。

### 7.3 当前推荐执行域

当前 `v0` 把它定义成：

- `FPGA/runtime` 主导；
- `FFT Engine`、`Vector Companion`、`Near-SRAM` 提供选择性支持；
- 先不把它误写成完全 chip-autonomous 的深流水。

### 7.4 主要输入输出

| 输入 | 输出 |
| --- | --- |
| `DENSITY_NEW_HANDLE` | `POTENTIAL_NEW_HANDLE` |
| `POTENTIAL_OLD_HANDLE` | `PROJECTOR_STATE_NEXT_HANDLE` |
| `PROJECTOR_STATE_HANDLE` | `POTENTIAL_REFRESH_SUMMARY_HANDLE` |

### 7.5 completion / join 规则

- `completion_mode = SYNC`
- `join_mode = HARD_BARRIER`

因为 `BODY_04C` 与下一轮 `Phase B` 都依赖它形成的稳定对象。

### 7.6 当前叶块映射

```text
BODY_04B_POTENTIAL_REFRESH
  -> PotentialFieldUnit.Build
  -> ProjectorStateUpdater.Update
```

## 8. `BODY_04C` 合同：mixing / convergence gate

### 8.1 软件对应

- `mix_rho`
- convergence decision

### 8.2 主要功能

- 混合 `DENSITY_OLD_HANDLE` 与 `DENSITY_NEW_HANDLE`；
- 更新 `SCFHistoryObject`；
- 形成 `DENSITY_MIXED_HANDLE`、`SCF_HISTORY_NEXT_HANDLE` 与 `SCF_DECISION_HANDLE`；
- 告诉 `BODY_05` 是否继续下一轮 outer `SCF`。

### 8.3 当前推荐执行域

当前 `v0` 把它定义成：

- `FPGA/runtime` 主导、`Host` 语义可见；
- `Vector Companion` 提供数值后处理/摘要支持；
- 不要求其完全下沉成当前阶段的纯 chip-autonomous body。

### 8.4 主要输入输出

| 输入 | 输出 |
| --- | --- |
| `DENSITY_OLD_HANDLE` | `DENSITY_MIXED_HANDLE` |
| `DENSITY_NEW_HANDLE` | `SCF_HISTORY_NEXT_HANDLE` |
| `SCF_HISTORY_HANDLE` | `SCF_DECISION_HANDLE` |
| `POTENTIAL_NEW_HANDLE` | `OUTER_SCF_SUMMARY_HANDLE` |

### 8.5 completion / join 规则

- `completion_mode = QUERYABLE`
- `join_mode = SOFT_JOIN`

因为最终是否继续，仍然是对 `Host / BODY_05` 可见的 outer decision 点。

### 8.6 当前叶块映射

```text
BODY_04C_MIX_CONVERGE
  -> DensityMixerUnit.Mix
  -> ConvergenceTracker.Decide
```

## 9. `BODY_04 family` 的 bundle 结构

### 9.1 推荐 bundle 名称

当前建议内部使用：

- `QE_SCF_OUTER_UPDATE_BUNDLE_V0`

### 9.2 推荐 bundle header 字段

| 字段 | 说明 |
| --- | --- |
| `bundle_id` | 本次 outer-update bundle id |
| `episode_id` | 所属 outer `SCF` episode |
| `phase_family` | 固定为 `BODY_04_FAMILY` |
| `sub_body_mask` | 当前 `v0` 固定为 `04A|04B|04C` |
| `completion_policy` | `SYNC_TO_04C / QUERYABLE_AT_04C` |

### 9.3 当前已实现的 stage-level 合同

从当前版本开始，bundle 内部已经显式生成：

- `Body04StageRequest`
- `Body04StageSummary`
- `Body04BundleSummary`

它们至少表达：

- `stage_kind`
- `input_handle / output_handle`
- `completion_mode / join_mode`
- `data_movement_kib`
- `reference-cycle`
- `critical_unit`
- `backpressure_ref_cycles`

### 9.4 为什么 family alias 仍然要保留

因为当前自然的调度粒度仍然是“一次完整 outer update”，而不是让 `Host` 或顶层软件每次都显式发三条完全独立的高层命令。

因此，最合理的写法不是删掉 `BODY_04`，而是：

- 对外保留 `BODY_04_FAMILY`
- 对内冻结 `BODY_04A/B/C`
- deeper lowering 继续留在 body 之下

## 10. 与 chip 内模块的当前映射

| sub-body | `Host` | `FPGA/runtime` | `Chip` |
| --- | --- | --- | --- |
| `BODY_04A` | 语义可见 | 主调度 | `Vector + Near-SRAM` 支撑 |
| `BODY_04B` | 语义可见 | 主调度 | `FFT + Vector + Near-SRAM` 支撑 |
| `BODY_04C` | 决策可见 | 主调度 | `Vector` 摘要支撑 |

这里最重要的是：

- `BODY_04A/B/C` 已经是正式 body 编号；
- 但它们当前仍属于 runtime-managed timed-functional body；
- 不应被误解成“已经冻结了完整的 chip-autonomous 微序列”。

## 11. 与异常/流控合同的关系

当前 `BODY_04` 需要遵守以下规则：

- `BODY_04A` 与 `BODY_04B` 默认不允许使用 `SOFT_JOIN` 越过未完成对象；
- `BODY_04C` 可以保持 `QUERYABLE` 风格完成；
- `density / potential / history` 对象的状态错配应归类为 `OBJECT_STATE_ERROR`；
- `BODY_04B` 若使用到辅助 `FFT` 路径，其 timeout 不应单独上抬为 `Host` 级错误，而应先在 family 内汇总。

对应异常与流控文档见：

- `docs/architecture/system_exception_and_flow_control_contract_v0.md`

## 12. 当前已冻结与未冻结部分

### 12.1 已冻结到足以继续推进的内容

- `BODY_04` 的 body-level catalog 已正式冻结为 `04A/B/C`；
- `BODY_04_FAMILY = 04A -> 04B -> 04C` 的顺序已冻结；
- 每个 sub-body 的输入/输出对象边界已冻结；
- 每个 sub-body 当前对应的 leaf-block 骨架已冻结到可继续细化的程度；
- `BODY_04` 之下的 deeper 语义统一转入 descriptor / mode / lowering / leaf-block 层。

### 12.2 仍未冻结的内容

- `BODY_04A/B/C` 各自最终是否下沉成更强的 chip-autonomous 执行域；
- `BODY_04B` 内部更细的 route id、assist-engine 组合与容量参数；
- `VASP/CP2K` 进入后，outer-update 内部 mode-switch 的更正式字段；
- queue depth、credit、backpressure 的真实数值。

## 13. 与其他文档的关系

- `docs/architecture/system_design_master_spec_v0.md`
  - 主系统设计总规范；
- `docs/architecture/qe_full_dft_systemc_extension_outline_v0.md`
  - 当前原型已实现到 `Phase A-E` 的主要来源；
- `docs/architecture/system_interface_contract_v0.md`
  - bundle / body / route 接口合同；
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
  - timeout、abort、soft stall 与错误升级边界；
- `docs/control/long_control_word_isa_v0.md`
  - descriptor / template / replay / `LCW` 控制栈主文档；
- `model/qe_band_solver_model/README.md`
  - 当前行为级原型入口。

## 14. 当前一句话结论

> `BODY_04` 现在不再是“尚未决定是否拆分”的过渡项，而是一个保留 family alias、但已经冻结为 `BODY_04A/B/C` 的正式 replay body catalog。

## 15. 当前 `SystemC` 映射状态

从当前版本开始，`BODY_04` 已经有明确的行为级实现映射：

- `FPGAOrchestrator`
  - dispatch `BODY_04_FAMILY`
- `Body04FamilyController`
  - execute `BODY_04A/B/C`
- `OuterUpdateRuntimeDomain`
  - 维护 stage request / summary / lowering plan
- `DensityAccumulationStage`
- `PotentialRefreshStage`
- `MixingConvergenceStage`

这意味着模型层已经完成了下面这一步：

> `Phase C/D/E` 已经从 outer-update family，正式收口成带 frozen sub-body catalog 的 runtime-managed body sequence。

## 16. 当前 lowering 合同对象的角色

从当前版本开始，`Body04LoweringPlan` / `Body04StageDescriptor` 的角色也更清楚了：

- 它们不再负责替代 body 编号；
- 它们负责描述 `BODY_04A/B/C` 各自的 route、assist engine、residency action 和参考周期摘要；
- 后续如果要继续下沉到更强的 chip-visible lowering，应继承这些对象，而不是重新回到“未拆分 family”叙事。


## 17. `ReplayBodyDesc` 与 template 对齐

### 17.1 `BODY_04_FAMILY` bundle 级约束

当前 `BODY_04_FAMILY` 在 `L1` 层应固定为：

- `body_count = 3`
- `replay_policy = NO_REPLAY`
- `exit_policy = UNTIL_DONE`
- `phase_begin = BODY_04A`
- `phase_end = BODY_04C`

也就是说，`BODY_04_FAMILY` 的职责是把三段 outer-update sub-body 作为一组受控 body 序列交给 runtime / scheduler，而不是把它重新变回一个未拆分大黑盒。

### 17.2 sub-body 到 `ReplayBodyDesc` 的推荐映射

| sub-body | `body_kind` | `template_id` | descriptor family | `completion_mode` | `join_mode` | `replay_policy` | `context_lock_policy` | `export_mask` | `patch_mask` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `BODY_04A` | `TPL_BODY_04A_DENSITY_ACCUM_V0` | `VECTOR_AUX` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `DENSITY_NEW_HANDLE` | `src_handle_0`, `src_handle_1`, `episode_id`, `scf_iter_id`, `active_band_mask_handle` |
| `BODY_04B` | `BODY_04B` | `TPL_BODY_04B_POTENTIAL_REFRESH_V0` | `FFT_OP + VECTOR_AUX` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `HOLD_UNTIL_DONE` | `POTENTIAL_NEW_HANDLE`, `PROJECTOR_STATE_NEXT_HANDLE` | `src_handle_0`, `src_handle_1`, `support_grid_mode`, `potential_epoch`, `resident_context_id` |
| `BODY_04C` | `BODY_04C` | `TPL_BODY_04C_MIX_CONVERGE_V0` | `VECTOR_AUX + BARRIER_JOIN` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `DENSITY_MIXED_HANDLE`, `SCF_HISTORY_NEXT_HANDLE`, `SCF_DECISION_HANDLE` | `src_handle_0`, `src_handle_1`, `history_depth`, `mixing_mode`, `stop_policy` |

这里的 `replay_policy` 指 **system-visible sub-body** 是否允许由 chip-side scheduler 自行展开局部 replay。
当前 `BODY_04A/B/C` 全部冻结为 `NO_REPLAY`：

- 允许 local hold / queue absorb；
- 允许 `runtime` 在 body 边界做受控重发；
- 不允许 scheduler 在 body 内凭空扩成新的未编号 replay 环。

### 17.3 sub-body 到 `LCW` slot skeleton 的推荐映射

| sub-body | `CIM` | `FFT` | `SRAM` | `Solve` | `Vector` | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `IDLE` | `IDLE` | `HOLD / FORWARD` | `IDLE` | `POSTPROC` | 波函数对象进入 `Vector` 域做 density accumulation，并经近存提交 |
| `BODY_04B` | `IDLE` | `G_TO_R / REORDER / IDLE` | `HOLD / FORWARD` | `IDLE` | `POSTPROC` | support-grid 开启时显式使用 `FFT`，否则直接走 `Vector + Near-SRAM` |
| `BODY_04C` | `IDLE` | `IDLE` | `HOLD` | `IDLE` | `POSTPROC` | 混合与收敛判断保持在 `Vector + control-visible summary` 路径 |

## 18. route 与对象状态对齐

### 18.1 sub-body route skeleton

| sub-body | canonical route chain | 主要 route id | 输入对象要求 | 输出对象落点 |
| --- | --- | --- | --- | --- |
| `BODY_04A` | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0` | `R29`, `R31`, `R32` | `WAVE_OUT_HANDLE = READY`，`ACTIVE_BAND_MASK_HANDLE` 至少 `PATCHED` | `DENSITY_NEW_HANDLE` 先 `PATCHED`，再 `EXPORTED` |
| `BODY_04B` (`support_grid=ON`) | `HANDLE_IN_0 -> FFT_IN -> FFT_OUT -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | `R01/R02`, `R03`, `R34`, `R31`, `R32`, `R33` | `DENSITY_NEW_HANDLE = READY`，`PROJECTOR_STATE_HANDLE = READY/RESIDENT` | `POTENTIAL_NEW_HANDLE`、`PROJECTOR_STATE_NEXT_HANDLE` 最终 `EXPORTED` |
| `BODY_04B` (`support_grid=BYPASS`) | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | `R29`, `R31`, `R32`, `R33` | 同上 | 同上 |
| `BODY_04C` | `HANDLE_IN_0 + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | `R29`, `R30`, `R31`, `R32`, `R33` | `DENSITY_OLD/NEW_HANDLE = READY`，`SCF_HISTORY_HANDLE` 至少摘要可见 | `DENSITY_MIXED_HANDLE`、`SCF_HISTORY_NEXT_HANDLE`、`SCF_DECISION_HANDLE` 最终 `EXPORTED` |

### 18.2 对象状态主规则

- `BODY_04A` 只接受 `READY` 的 `WAVE_OUT_HANDLE`，不允许消费 `RETIRED` 波函数对象；
- `BODY_04B` 进入前，`DENSITY_NEW_HANDLE` 必须已经由 `BODY_04A` 提交完成；
- `BODY_04C` 进入前，`POTENTIAL_NEW_HANDLE` 与 `PROJECTOR_STATE_NEXT_HANDLE` 必须至少处于 `READY`；
- `BODY_04C` 导出的 `SCF_DECISION_HANDLE` 可以是 `QUERYABLE` 语义，但不能伪装成未提交对象。

## 19. 异常、恢复与流控对齐

| sub-body | 主风险 | 局部处理 | 升级状态码 | 恢复/退出责任 |
| --- | --- | --- | --- | --- |
| `BODY_04A` | 波函数对象未 ready、`Vector` ingress 拥塞 | local hold / queue absorb | `OBJECT_STATE_ERROR`, `SOFT_STALL` | `runtime` 决定是否重放当前 body |
| `BODY_04B` | support-grid 路径超时、`FFT` mode 与输入形状不匹配、projector 状态失配 | 优先局部消化；无法消化则终止当前 body | `TIMEOUT_SOFT`, `ENGINE_ERROR`, `OBJECT_STATE_ERROR` | `runtime` 汇总为 bundle 级结果 |
| `BODY_04C` | history/version 错配、决策门未能提交 | 允许 `SOFT_JOIN` 式等待；超过上限后退出 | `OBJECT_STATE_ERROR`, `TIMEOUT_SOFT`, `ENGINE_ERROR` | `BODY_05` 消费决策摘要，`runtime` 决定是否停止 SCF |

当前推荐的最小原则是：

- `BODY_04A/B` 不允许用 `SOFT_JOIN` 跨过未完成对象；
- `BODY_04C` 允许 `QUERYABLE + SOFT_JOIN` 风格完成；
- body 级失败优先在 `BODY_04_FAMILY` 内汇总，不直接上推成 `Host` 级硬错误。
