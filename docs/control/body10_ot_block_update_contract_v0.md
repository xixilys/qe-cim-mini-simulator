# 2026-03-29 `BODY_10` OT block-update Body Catalog 合同 v0

## 1. 文档定位

本文是当前系统设计里针对 `CP2K/QS_OT` 路径的正式支撑文档。

它的目标不再只是保留一个“以后再细化”的 `BODY_10 family` 入口，而是把已经进入 `SystemC` 行为级模型的那段扩展路径，正式收口成：

- 一个保留 family alias 的扩展 body 组；
- 一套冻结到 system-visible 编号层的 `BODY_10A/B/C` catalog；
- 一条明确的边界：更深的 block-sparse / AO / DBCSR 细节属于 body 之下的 descriptor / mode / object 合同，而不是继续膨胀成新的 body 号。

## 2. 当前定位与本轮冻结决策

当前 `BODY_10` 的角色固定为：

- `CP2K/QS_OT` 专属扩展 body family；
- 位于 `Phase B` 与 `BODY_04` 之间；
- 用来承接 `OT` 在 `Phase B` 之后需要补的一段对象更新路径。

本轮正式冻结下面三条：

1. `BODY_10` 保留为 family alias；
2. system-visible sub-body catalog 冻结为 `BODY_10A/B/C`；
3. deeper `block-sparse / AO / DBCSR` 细节继续放在 `BODY_10A/B/C` 之下，不通过新增 `BODY_11+` 编号表达。

因此，从本文件开始：

> `BODY_10` 不再只是“第一层入口”，而是“family alias + frozen sub-body catalog”的正式 OT 扩展写法。

## 3. 当前触发条件

`BODY_10` 当前只在下面条件下进入运行路径：

- `software_family = CP2K`
- `flow_family = QS_OT`

因此，它在顶层流程中的位置是：

```text
BODY_05 / BODY_00
  -> BODY_01-03
  -> BODY_10_FAMILY   (only for CP2K/QS_OT)
  -> BODY_04_FAMILY
  -> next SCF iteration / stop
```

## 4. 正式 `BODY_10` sub-body catalog

### 4.1 catalog 总表

| body id | 主要功能 | 当前执行类 | 当前状态 |
| --- | --- | --- | --- |
| `BODY_10A_PRECOND_UPDATE` | preconditioned block update | runtime-managed extension body | 冻结 |
| `BODY_10B_ORTHO_REBIND` | orthogonalize / rebind / projector-object refresh | runtime-managed extension body | 冻结 |
| `BODY_10C_HISTORY_COMMIT` | search-history / iteration-summary commit | runtime-managed extension body | 冻结 |

### 4.2 family 顺序与跳过规则

当前 `v0` 固定下面三条规则：

1. `BODY_10_FAMILY` 的顺序固定为 `10A -> 10B -> 10C`；
2. 对 `CP2K/QS_OT` 主线，三段都属于 mandatory sub-body；
3. block-sparse tile 选择、AO/object layout、preconditioner 形态、orthogonalize mode 等差异继续放在 sub-body 之下的 descriptor / mode / object 层。

因此，当前不建议再把下面这些内容写成新的 body 编号：

- 某个特定 `DBCSR` tile update
- 某个特定 AO block gather / scatter
- 某个特定 orthogonalize kernel 变种

这些都应属于 `BODY_10A/B/C` 内部的 lowering 选择，而不是 catalog 膨胀。

## 5. 输入/输出对象合同

### 5.1 family 级输入

当前 `Body10BundleRequest` 至少包含：

- `bundle_id`
- `software_family`
- `flow_family`
- `incoming_state`
- `phase_b_summary`

其中：

- `incoming_state` 提供上一轮 `SCFState` 与对象句柄；
- `phase_b_summary` 提供 `BODY_01-03` 结束后的 residual / reduced / context 摘要。

### 5.2 family 级输出

当前 `Body10BundleSummary` 至少输出：

- `updated_wave_object`
- `updated_projector_object`
- `search_history_object`
- `block_update_norm`
- `orthogonality_score`
- `data_movement_kib`
- `active_blocks`
- `accepted`

### 5.3 sub-body 交接关系

| sub-body | 主要输入 | 主要输出 |
| --- | --- | --- |
| `BODY_10A_PRECOND_UPDATE` | `phase_b_summary`, incoming wave / residual / precondition context | updated wave candidate |
| `BODY_10B_ORTHO_REBIND` | updated wave candidate, projector / metric context | rebound wave object, updated projector object |
| `BODY_10C_HISTORY_COMMIT` | rebound wave object, orthogonality / norm summary, prior history object | `search_history_object`, `accepted`, OT extension summary |

## 6. 控制语义合同

当前 `BODY_10` 的控制语义应理解为：

- `Host` 决定本轮是否需要该扩展 family；
- `FPGA/runtime` 负责 dispatch `BODY_10_FAMILY`；
- `Body10FamilyController` 负责按 `10A -> 10B -> 10C` 推进；
- `Chip` 当前不需要把它误写成新的固定深流水 phase。

因此，它更准确地说是：

- **运行时层的结构化扩展 body 组**

而不是：

- **已经冻结了所有 sparse / AO 微路径的完整 OT 微架构**

## 7. 更深层 block-sparse / AO catalog 的边界

当前必须明确一个边界：

- `BODY_10A/B/C` 冻结的是 system-visible replay body catalog；
- 不是 `CP2K OT` 全部内部对象的最终 catalog。

更深的内容，例如：

- block-sparse tile 组装
- AO block layout 变体
- preconditioner 细分模式
- orthogonalization 内核选择
- `DBCSR` / AO mixed object 的中间对象层

继续属于：

- descriptor family
- body-local mode 字段
- resident-context / object-handle 合同
- leaf-block / lowering 合同

也就是说，当前解决这个问题的正确方式不是继续加 body 编号，而是：

> 在 `BODY_10A/B/C` 之下冻结对象字段和 lowering 边界。

## 8. 与 `LCW` / descriptor 的关系

当前 `BODY_10` 已经不再只是 descriptor / runtime bundle 层的模糊入口，而是：

- body 编号层：`BODY_10A/B/C` 已冻结；
- family 层：`BODY_10_FAMILY` 继续保留作高层 alias；
- deeper lowering 层：是否继续下沉到正式 `LCW` micro-sequence 仍未冻结。

因此，后续若要继续下沉，最自然的顺序应是：

1. 维持 `BODY_10A/B/C` 不再变化；
2. 在每个 sub-body 内继续冻结对象字段、mode 与 lowering 规则；
3. 最后才决定哪些部分值得进入独立 `LCW` 模板。

## 9. 与 `VASP` 的边界

当前 `VASP` 不直接复用 `BODY_10`。

`VASP` 给系统带来的主要压力仍更适合写成：

- `solver_mode`
- `band_batch`
- `support_grid_mode`

这些顶层字段，而不是引入 `BODY_10` 风格的 OT 扩展 body。

因此：

- `BODY_10` 主要是 `CP2K/QS_OT` 的对象扩展入口；
- `VASP` 主要是 descriptor / mode 扩展入口。

## 10. 当前实现状态

当前仓库中已经有：

- `model/qe_band_solver_model/legacy/include/body10_family_controller.hpp`
- `model/qe_band_solver_model/legacy/src/body10_family_controller.cpp`
- `Body10StageRequest / Body10StageSummary / Body10LoweringPlan`
- `Body10BundleRequest / Body10BundleSummary`
- archived replay/body compatibility path for `BODY_10`

并且当前行为级实现已经显式覆盖：

- `BODY_10A` 对应 preconditioned block update
- `BODY_10B` 对应 orthogonalize / rebind
- `BODY_10C` 对应 search-history / summary commit

这意味着：

- `BODY_10` 已经进入可运行行为级模型；
- `BODY_10A/B/C` 已经足以作为正式 body-level 合同收口；
- 行为级模型现在也已经能导出 `BODY_10A/B/C` 各自的 stage request、stage summary、lowering plan、reference-cycle 与 leaf-block flow-control 摘要；
- 但它还不是最终的 `OT` 硬件规格书。

## 11. 当前最稳的结论

当前最稳的结论是：

- `CP2K/QS_OT` 确实需要一个独立于 `BODY_01-03` 与 `BODY_04` 的中间扩展层；
- 这个扩展层现在应正式写成 `BODY_10_FAMILY = 10A -> 10B -> 10C`；
- 更深的 sparse / AO object catalog 不应再继续用 body 编号承载，而应下沉到 `BODY_10A/B/C` 之下的对象和 lowering 合同。


## 12. `ReplayBodyDesc` 与 template 对齐

### 12.1 `BODY_10_FAMILY` bundle 级约束

当前 `BODY_10_FAMILY` 在 `L1` 层应固定为：

- `body_count = 3`
- `replay_policy = NO_REPLAY`
- `exit_policy = UNTIL_DONE`
- `phase_begin = BODY_10A`
- `phase_end = BODY_10C`

也就是说，`BODY_10_FAMILY` 负责把 `CP2K/QS_OT` 的 OT extension 保持成一个结构化三段 body 组，而不是继续保留成一个模糊扩展入口。

### 12.2 sub-body 到 `ReplayBodyDesc` 的推荐映射

| sub-body | `body_kind` | `template_id` | descriptor family | `completion_mode` | `join_mode` | `replay_policy` | `context_lock_policy` | `export_mask` | `patch_mask` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `BODY_10A` | `BODY_10A` | `TPL_BODY_10A_PRECOND_UPDATE_V0` | `VECTOR_AUX` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `LOCK_ON_ENTER` | `UPDATED_WAVE_CANDIDATE` | `src_handle_0`, `residual_handle`, `precond_mode`, `active_block_mask`, `episode_id` |
| `BODY_10B` | `BODY_10B` | `TPL_BODY_10B_ORTHO_REBIND_V0` | `VECTOR_AUX + BARRIER_JOIN` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `HOLD_UNTIL_DONE` | `UPDATED_WAVE_OBJECT`, `UPDATED_PROJECTOR_OBJECT` | `src_handle_0`, `src_handle_1`, `orthogonalize_mode`, `resident_context_id`, `metric_handle` |
| `BODY_10C` | `BODY_10C` | `TPL_BODY_10C_HISTORY_COMMIT_V0` | `VECTOR_AUX + BARRIER_JOIN` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `RELEASE_ON_EXIT` | `SEARCH_HISTORY_OBJECT`, `OT_DECISION_SUMMARY` | `src_handle_0`, `src_handle_1`, `history_depth`, `summary_epoch`, `stop_policy` |

这里的 `replay_policy` 同样只指 **system-visible sub-body replay**。
当前 `BODY_10A/B/C` 全部冻结为 `NO_REPLAY`：

- `OT` deeper block-sparse / AO 变化仍允许写成 body-local lowering；
- 但不允许在 `BODY_10A/B/C` 之上继续膨胀新的 system-visible replay 环；
- 受控重试由 `runtime` 在 body / family 边界决定，而不是由 scheduler 自行生成新循环。

### 12.3 sub-body 到 `LCW` slot skeleton 的推荐映射

| sub-body | `CIM` | `FFT` | `SRAM` | `Solve` | `Vector` | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `BODY_10A` | `IDLE` | `IDLE` | `FORWARD / HOLD` | `IDLE` | `POSTPROC` | preconditioned update 主要保持在 `Vector + stage` 路径 |
| `BODY_10B` | `IDLE` | `IDLE` | `STAGE / HOLD` | `IDLE` | `POSTPROC` | 正交化 / rebind 消费 stage 中的 wave candidate 与辅助对象 |
| `BODY_10C` | `IDLE` | `IDLE` | `HOLD` | `IDLE` | `POSTPROC` | history commit 与接受/拒绝摘要继续保持控制可见 |

## 13. route 与对象状态对齐

### 13.1 sub-body route skeleton

| sub-body | canonical route chain | 主要 route id | 输入对象要求 | 输出对象落点 |
| --- | --- | --- | --- | --- |
| `BODY_10A` | `HANDLE_IN_0 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_STAGE_BUF` | `R29`, `R36` | phase-B 输出 wave / residual 对象必须 `READY` | updated wave candidate 进入 `STAGED` |
| `BODY_10B` | `SRAM_STAGE_BUF + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_0/1` | `R35`, `R30`, `R31`, `R32`, `R33` | staged wave candidate 必须有效，projector / metric 上下文必须 `READY/RESIDENT` | rebound wave / projector 对象最终 `EXPORTED` |
| `BODY_10C` | `HANDLE_IN_0 + HANDLE_IN_1 -> VECTOR_IN -> VECTOR_OUT_MISC -> SRAM_META_BUF -> HANDLE_OUT_1` | `R29`, `R30`, `R31`, `R33` | rebound wave 与 prior history 对象必须 `READY` 或至少摘要可查询 | `search_history_object` 与 decision 摘要最终 `EXPORTED` |

### 13.2 对象状态主规则

- `BODY_10A` 只接受 `READY` 的 phase-B 输出对象，不接受已经 `RETIRED` 的 residual / wave handle；
- `BODY_10B` 进入前，`BODY_10A` 必须已经把 wave candidate 放入 `SRAM_STAGE_BUF`；
- `BODY_10C` 进入前，`updated_wave_object`、`updated_projector_object` 至少应处于 `READY` 或摘要可见；
- `BODY_10C` 导出的 `search_history_object` 不要求数值路径完全片内化，但必须具备明确 `producer_body` 与 `validity_scope`。

## 14. 异常、恢复与流控对齐

| sub-body | 主风险 | 局部处理 | 升级状态码 | 恢复/退出责任 |
| --- | --- | --- | --- | --- |
| `BODY_10A` | precondition context 缺失、active block 形状非法 | 局部参数检查失败即停止 | `PATCH_ERROR`, `OBJECT_STATE_ERROR` | `runtime` 终止当前 OT extension |
| `BODY_10B` | orthogonalize 输入未就绪、rebind 目标端点冲突 | 先 local hold；无法提交则失败 | `SOFT_STALL`, `OBJECT_STATE_ERROR`, `ENGINE_ERROR` | `runtime` 决定是否重发 `BODY_10_FAMILY` |
| `BODY_10C` | history 对象代次错配、summary commit 超时 | 允许短时等待 | `TIMEOUT_SOFT`, `OBJECT_STATE_ERROR` | `runtime` 汇总为 `accepted / rejected / retryable` 摘要 |

当前推荐的最小原则是：

- `BODY_10A/B` 默认按 `HARD_BARRIER` 处理，避免 OT update 中间对象提前外露；
- `BODY_10C` 可以用 `SOFT_JOIN` 风格对上层暴露 queryable summary；
- 更深的 sparse / AO 错误先在 `BODY_10A/B/C` 之下分类，不直接要求新增 body 编号。
