# 2026-03-28 DFT 混合加速系统异常与流控合同 v0

## 1. 文档目标

这份文档是：

- `docs/architecture/system_design_master_spec_v0.md`
- `docs/architecture/system_interface_contract_v0.md`

的异常与流控补充件。

它的目标是把当前系统里最容易一直被写成“以后再说”的部分先收成一份 `v0` 合同草案，明确回答：

- 哪些异常属于 `Host`、`FPGA/runtime`、`Chip` 各自负责；
- backpressure、join、barrier、timeout、abort 在三层接口里应该怎么表达；
- 当前哪些错误能被本地消化，哪些必须向上升级；
- 现阶段最小需要暴露哪些可观测状态。

本文仍然不是 RTL 级协议书，但它应当足够成为下一版 block-level 规格书的系统约束输入。

## 2. 文档范围

本文覆盖：

- `Host <-> FPGA/runtime` 的异常状态码与 abort 语义；
- `FPGA/runtime <-> Chip` 的 replay limit、retry、timeout、completion 行为；
- chip 内 `LCW` / route / object 生命周期相关的局部错误分类；
- 最小 backpressure / credit / queue 协议约束；
- 需要暴露给调试与建模层的状态摘要。

本文不覆盖：

- 精确 ready/valid 波形；
- 逐周期 credit 数值；
- ECC / parity / RAS 真实实现；
- DFT scan、BIST、片上 debug fabric；
- 最终的系统恢复软件栈。

## 3. 异常与流控分层

当前系统继续按三层理解：

| 层级 | 主对象 | 主要异常类型 | 主要流控对象 |
| --- | --- | --- | --- |
| L2 | `Host <-> FPGA/runtime` | request 非法、episode abort、summary error | episode queue / completion |
| L1 | `FPGA/runtime <-> Chip` | patch 非法、bundle timeout、replay limit | body queue / bundle issue / completion |
| L0 | chip 内 `LCW` 执行域 | route 非法、object 状态非法、局部执行失败 | slot busy / route backpressure / buffer saturation |

最关键的原则是：

- 不要把所有错误都抬升到 `Host`；
- 也不要假装 chip 内所有错误都能完全吞掉；
- 必须明确“局部可恢复”和“需要升级”之间的边界。

## 4. v0 异常分类

### 4.1 顶层异常大类

当前建议固定六大类：

| 异常类 | 说明 | 当前典型来源 |
| --- | --- | --- |
| `CONFIG_ERROR` | 请求或 patch 参数不合法 | 非法 mode、shape、family 组合 |
| `RESOURCE_STALL` | 资源暂不可用但未损坏 | queue 满、slot busy、buffer 占满 |
| `DATA_STATE_ERROR` | 对象状态或版本关系不合法 | handle 未 ready、resident context 丢失 |
| `EXECUTION_LIMIT` | 达到预设上限但不是硬失败 | local iter 达上限、timeout 软超限 |
| `EXECUTION_FAULT` | 执行域内部失败 | solve 失败、route 无法建立、内部 assert |
| `ABORT_EVENT` | 上层主动终止 | host cancel、runtime stop |

### 4.2 当前建议保留的状态码集合

为避免每层各写一套完全不同的状态码，当前 v0 推荐统一保留下面这组状态码，再按接口层裁剪使用：

- `OK`
- `QUEUED`
- `RUNNING`
- `SOFT_STALL`
- `LOCAL_MAX_ITER`
- `TIMEOUT_SOFT`
- `RETRYABLE_ERROR`
- `PATCH_ERROR`
- `OBJECT_STATE_ERROR`
- `ROUTE_ERROR`
- `ENGINE_ERROR`
- `ABORTED`
- `FATAL_ERROR`

这里有两个重要判断：

1. `LOCAL_MAX_ITER` 与 `TIMEOUT_SOFT` 不应直接等同于硬错误；
2. `PATCH_ERROR / OBJECT_STATE_ERROR / ROUTE_ERROR` 应和笼统的 `ERROR` 分开，否则调试价值太低。

## 5. `Host <-> FPGA/runtime` 异常与流控合同

### 5.1 `Host -> FPGA/runtime` 请求接收结果

| 状态 | 含义 | 处理建议 |
| --- | --- | --- |
| `OK` | request 被接受并进入执行路径 | Host 等待完成或查询 |
| `QUEUED` | request 已入队但未开始 | Host 可查询，不应重复发同 episode |
| `PATCH_ERROR` | 参数组合在 runtime 层即非法 | 直接返回 Host |
| `SOFT_STALL` | 暂无资源接收新 episode | Host 可等待后重试 |
| `ABORTED` | request 在入队前已被上层撤销 | Host 结束该请求 |

### 5.2 `EpisodeResponse` 允许返回的异常状态

| 状态 | 含义 | 责任归属 |
| --- | --- | --- |
| `OK` | 正常完成 | `FPGA/runtime + Chip` |
| `LOCAL_MAX_ITER` | 局部闭环达到上限退出 | `Chip` 本地策略，`FPGA/runtime` 汇总 |
| `TIMEOUT_SOFT` | 达到软超时，已受控退出 | `FPGA/runtime` 或 `Chip` |
| `RETRYABLE_ERROR` | 可重下发/可重放 | `FPGA/runtime` |
| `PATCH_ERROR` | bundle 未能合法实例化 | `FPGA/runtime` |
| `OBJECT_STATE_ERROR` | 输入对象或版本关系不满足 | `FPGA/runtime` / `Chip` |
| `ENGINE_ERROR` | 内部执行域报告失败 | `Chip` |
| `ABORTED` | Host 或 runtime 主动停止 | `Host` 或 `FPGA/runtime` |
| `FATAL_ERROR` | 无法继续当前 episode | `FPGA/runtime` 汇总上报 |

### 5.3 `Host <-> FPGA` 流控原则

- `Host` 不对 `LCW` 级事件背压；
- `Host` 只面向 episode queue 看到 `QUEUED / RUNNING / DONE` 级摘要；
- `FPGA/runtime` 必须吸收 chip 内局部短时背压，不应把这类细粒度抖动直接上推给 `Host`；
- `Host` 可发 `EPISODE_QUERY`，但不参与本地 replay 逐轮推进。

## 6. `FPGA/runtime <-> Chip` 异常与流控合同

### 6.1 bundle 接收阶段的错误

| 状态 | 触发条件 | 是否允许重试 |
| --- | --- | --- |
| `PATCH_ERROR` | template 与 patch 点组合非法 | 否，需修正请求 |
| `OBJECT_STATE_ERROR` | 输入 handle 不在允许状态 | 条件允许时可重试 |
| `SOFT_STALL` | issue queue / resident context 资源暂满 | 是 |
| `ABORTED` | bundle 在发射前被撤销 | 否 |

### 6.2 replay 执行阶段的错误

| 状态 | 触发条件 | 当前建议处理 |
| --- | --- | --- |
| `LOCAL_MAX_ITER` | 达到 `max_replay_iters` | 受控退出并上报摘要 |
| `TIMEOUT_SOFT` | 达到 body / bundle 软超时 | 受控退出并上报 |
| `ROUTE_ERROR` | 当前 `route_mask` 与 slot/mode 不一致 | 直接停止当前 body |
| `OBJECT_STATE_ERROR` | handle 未 ready、版本错配、resident 丢失 | 停止当前 body，是否重试由 runtime 决定 |
| `ENGINE_ERROR` | 执行域本地失败 | 停止当前 body，升级到 bundle summary |
| `RETRYABLE_ERROR` | 资源型失败，可经 runtime 重放恢复 | 允许重试 |
| `FATAL_ERROR` | 不可恢复失败 | bundle 终止 |

### 6.3 `FPGA/runtime <-> Chip` 流控原则

当前建议固定四条：

1. `FPGA/runtime` 只对 bundle/body 级完成做显式等待，不逐条 `LCW` 轮询；
2. chip 内短时背压通过 queue / scoreboard / local stall 吸收；
3. 只有当本地无法在策略上消化背压时，才升级成 `SOFT_STALL` 或 `RETRYABLE_ERROR`；
4. bundle 不应因为单条 `LCW` 的一拍延迟就上报错误，错误必须对应稳定失配或超限。

## 7. Chip 内局部错误合同

### 7.1 `Command Scheduler` 负责识别的错误

- 非法 `route_mask` 与 slot 组合；
- `dependency_mask` 未满足却试图发射；
- `src_handle` / `dst_handle` 与当前 phase/body 不一致；
- barrier / join 条件未满足却提前提交；
- 同一 object version 被重复消费或重复导出。

### 7.2 执行域负责识别的错误

#### `CIM / Projector-Apply`
- resident context 缺失；
- 不支持的 mode 组合；
- partial 输出端点不可达。

#### `FFT`
- shape/mode 不支持；
- transform 输入对象状态不合法；
- output 无合法接收端。

#### `Near-SRAM`
- stage/full/partial buffer 空间不足；
- assembler 输入集合不完整；
- resident reuse 与 recycle 策略冲突。

#### `Reduction / Closure / Solve`
- reduced-build 输入不完整；
- diag/closure mode 不匹配；
- 内部求解失败或无法给出有效摘要。

#### `SIMD / Vector`
- mask/meta 缺失；
- next-`X` / residual 目标端点不可写；
- postproc 模式与输入对象类型不匹配。

### 7.3 错误升级原则

- 能在本域局部消化的，不升级；
- 会破坏当前 body 语义的，升级到 body 级；
- 会破坏当前 bundle 完整性的，升级到 bundle 级；
- 会使 episode 语义失效的，升级到 `Host` 可见状态。

## 8. Backpressure / credit / queue 合同

### 8.1 v0 最小 queue 语义

当前文档层只先冻结 queue 语义，不冻结精确深度：

| 队列 / 资源 | 作用 | 最小语义 |
| --- | --- | --- |
| `EpisodeQueue` | 接收 Host 请求 | 可返回 `QUEUED / SOFT_STALL` |
| `BundleIssueQueue` | runtime 向 chip 发 bundle | 可返回 `SOFT_STALL` |
| `BodyQueue` | chip 内 body 发射 | 支持等待依赖满足 |
| `LCWIssueWindow` | scheduler 局部发射窗口 | 支持短时 hold，不直接升级错误 |
| `ResidentContextPool` | resident context 占用资源 | 用尽时返回 `SOFT_STALL` 或 `RETRYABLE_ERROR` |

### 8.1.1 当前 `Phase B` 原型里已经落地的 provisional queue depth

为了让 `SystemC` 原型不再只停留在“概念上有 backpressure”，当前 `Phase B` 已经先落地一组**原型级** queue depth：

- `NearSRAMSupport.stage_panel` ingress queue = `2`
- `FFTCompanion.Transform` ingress queue = `1`
- `ContextLoader` ingress queue = `2`
- `DigitSerialInputBoundary` ingress queue = `2`
- `ProjectConjugateSignSelector` ingress queue = `2`
- `Residue3MCore.PROJECT` ingress queue = `1`
- `CoefficientAccumulator` ingress queue = `1`
- `NearSRAMCoeffBuffer` ingress queue = `2`
- `BackprojectConjugateSignSelector` ingress queue = `2`
- `Residue3MCore.BACKPROJECT` ingress queue = `1`
- `RowMergeTree` ingress queue = `1`
- `NearSRAMRowBuffer` ingress queue = `1`
- `NearSRAMSupport.aggregate` ingress queue = `1`
- `ReductionClosureEngine.InputAssembler` ingress queue = `1`
- `ReductionClosureEngine.HermitianClosureBuilder` ingress queue = `1`
- `ReductionClosureEngine.SmallSolveFrontEnd` ingress queue = `1`
- `VectorDiagCompanion.RitzUpdate` ingress queue = `1`

同时当前 `Phase B` 原型已经对每个 leaf block 额外导出：

- `accept_condition`
- `busy_condition`
- `complete_condition`
- `ingress_owner`
- `egress_owner`
- `arbitration_domain`

这些数值和字符串当前都只表示 `L2 proxy` 流控建模旋钮，不等于最终硬件冻结值。


### 8.1.2 当前尚未全部导出为 `flow stage` 行的 block

虽然当前 `ContextLoader` 之后的大部分 `Phase B` 叶块都已经能在日志里打印出完整的 `qdepth / accept / busy / complete / ingress_owner / egress_owner / arbitration_domain`，但下面这几个块目前仍然主要通过 `module occupancy` 或事件日志可见：

| block | 当前可见性 | 当前应冻结的最小 `accept / busy / complete` 语义 | 为什么现在就要写进合同 |
| --- | --- | --- | --- |
| `CommandScheduler` | `issued N LCW words` 事件日志 + `module occupancy` | `accept` = resident context 已 `READY` 且 issue window 尚有 credit；`busy` = `LCWCommand` 正在逐 row-block 发射或被 issue hold；`complete` = 当前 inner-step 全部 row-block 的 `LCW` 已发射 | 否则 `LCW` 发射边界会被错误地揉回 `BODY_01` 大过程 |
| `ResidentContextController` | `bind/open/release` 事件日志 + `module occupancy` | `accept` = bind/open/release 请求满足 context 生命周期条件；`busy` = bind/open/release 任一事务进行中；`complete` = `ResidentContextDesc` / `RowBlockWindowDesc` / release ack 已稳定导出 | 否则 resident context 生命周期会继续停留在叙事层 |
| `NearSRAMSupport.stage_panel` | stage-panel 日志 + `module occupancy` + backpressure route | `accept` = panel request valid 且 stage slot 可装入；`busy` = stage fill / local buffer commit 进行中；`complete` = staged `WavePanel` 已进入 `FFTCompanion` 或 `ContextLoader` 的 ingress | 这是 `Phase B` 的第一个真实近存入口，不应再是黑盒 |
| `FFTCompanion.Transform` | FFT 日志 + `module occupancy` + backpressure route | `accept` = staged panel ready；`busy` = `G<->R/reorder` 或谱视图刷新进行中；`complete` = transformed `WavePanel` ready | 否则 support-grid / spectral preprocessing 的停顿位置无从归属 |
| `NearSRAMSupport.aggregate` | aggregate 日志 + `module occupancy` + backpressure route | `accept` = committed `PartialHS` 可继续并入；`busy` = `PartialHS[] -> FullHS` 聚合进行中；`complete` = `FullHS` 已稳定进入 `ReductionClosureEngine.input_fifo` | 这是 `BODY_01` 与 `BODY_02` 之间最关键的聚合边界 |

当前对这五个块的要求是：

- 文档层已经冻结其 `accept / busy / complete` 语义；
- 行为级模型下一步应把它们也补成和中间链路一致的 `flow stage` 统计对象；
- 在这一步完成之前，不能把它们误报成“尚未定义”。

### 8.1.3 当前 `Phase B` block-level 流控可见性分层

为了避免后续汇报时继续把“已经有 block-level 合同”和“已经打印出 block-level flow-stage 行”混为一谈，当前明确分成三层：

1. **事件级可见**
   - `CommandScheduler`
   - `ResidentContextController`
2. **occupancy + backpressure route 可见**
   - `NearSRAMSupport.stage_panel`
   - `FFTCompanion.Transform`
   - `NearSRAMSupport.aggregate`
3. **完整 flow-stage 可见**
   - `ContextLoader`
   - `DigitSerialInputBoundary`
   - `ProjectConjugateSignSelector`
   - `Residue3MCore.PROJECT`
   - `CoefficientAccumulator`
   - `NearSRAMCoeffBuffer`
   - `BackprojectConjugateSignSelector`
   - `Residue3MCore.BACKPROJECT`
   - `RowMergeTree`
   - `NearSRAMRowBuffer`
   - `ReductionClosureEngine.InputAssembler`
   - `ReductionClosureEngine.HermitianClosureBuilder`
   - `ReductionClosureEngine.SmallSolveFrontEnd`
   - `VectorDiagCompanion.RitzUpdate`

这三层分法当前非常重要，因为它直接决定：

- 哪些块还需要继续补日志与统计对象；
- 哪些块已经足够进入 block-level 设计评审；
- 哪些块还不能被误写成“已经具备 RTL 级流控观测”。

### 8.2 backpressure 传播原则

当前推荐的 backpressure 传播顺序是：

```text
slot/local buffer busy
  -> scheduler local hold
  -> body-level soft stall
  -> bundle-level soft stall / retryable
  -> episode-level visible delay
```

也就是说：

- 优先在局部消化；
- 不要直接从某个 slot busy 跳成 `Host` 可见错误；
- 只有在跨 body / 跨 bundle 持续存在时，才向上升级。

### 8.3 credit 语义

当前 `v0` 只冻结概念，不冻结数值：

- `FPGA/runtime` 对 chip bundle issue 至少需要有“可否再发 body/bundle”的 credit 概念；
- `Command Scheduler` 对 `Near-SRAM`、`Solve`、`Vector` 至少需要有局部 accept / busy 概念；
- precise credit counter 数值留到 block-level spec 冻结。

## 9. timeout 与 abort 合同

### 9.1 timeout 分层

当前建议把 timeout 分成三层：

| timeout | 作用对象 | 当前处理 |
| --- | --- | --- |
| `word_timeout` | 单条 `LCW` | 仅作为内部 debug 计数，不直接上抬 |
| `body_timeout` | 单个 body | 返回 `TIMEOUT_SOFT` 或 `ENGINE_ERROR` |
| `bundle_timeout` | 一组 replay body | runtime 终止 bundle 并汇总上报 |

当前判断是：

- `word_timeout` 不宜成为主要软件可见接口；
- 对系统有意义的是 `body_timeout` 和 `bundle_timeout`。

### 9.2 abort 来源

当前允许三类 abort：

- `HOST_ABORT`：Host 主动终止 episode；
- `RUNTIME_ABORT`：runtime 依据策略主动止损；
- `CHIP_ABORT_REQUEST`：chip 检测到不可恢复问题，请求上层中止。

### 9.3 abort 后的最小保证

当前建议保持以下最小保证：

- 不再发射新的 body / `LCW`；
- 当前已提交导出的 `HANDLE_OUT_x` 仍保持有效；
- 未提交对象不得伪装成有效结果；
- resident 对象是否保活由 runtime 策略决定，但必须有显式摘要。

## 10. completion / join / barrier 合同

### 10.1 三类 completion 语义

| 语义 | 说明 | 典型使用 |
| --- | --- | --- |
| `SYNC` | 当前 word/body 完成后才能继续 | 关键 assemble / reduce / solve 边界 |
| `ASYNC_OK` | 可以局部异步推进 | FFT prepare、部分 postproc |
| `QUERYABLE` | 对 Host 只暴露可查询状态 | episode 外层 |

### 10.2 三类 join 语义

| 语义 | 说明 | 典型使用 |
| --- | --- | --- |
| `HARD_BARRIER` | 所有依赖结果必须 ready | `PROJECTOR_APPLY_CHAIN`, `ASSEMBLE_AND_REDUCE` |
| `SOFT_JOIN` | 可容许局部后处理延迟 | `SOLVE_AND_CLOSE`, `LOOP_DECIDE` |
| `NONE` | 无需 join | 纯 local staging |

### 10.3 barrier 失败如何处理

- 如果只是短时未 ready，应 local hold；
- 如果达到 body timeout，应升级为 `TIMEOUT_SOFT`；
- 如果依赖对象已被 retire 或 version 冲突，应升级为 `OBJECT_STATE_ERROR`。

### 10.4 `BODY_04A/B/C` 与 `BODY_10A/B/C` 的固定 completion/join 姿态

当前 `v0` 已经不再把 `BODY_04`、`BODY_10` 仅仅当成模糊 family 名称使用，而是把六个 sub-body 的异常/流控姿态冻结到可审查的程度：

| sub-body | `completion_mode` | `join_mode` | `replay_policy` | 超时/错误上抬 | 受控重试责任 |
| --- | --- | --- | --- | --- | --- |
| `BODY_04A` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `OBJECT_STATE_ERROR` / `SOFT_STALL` / `TIMEOUT_SOFT` | `runtime` 只可在 body 边界重发 `BODY_04A` |
| `BODY_04B` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `OBJECT_STATE_ERROR` / `ENGINE_ERROR` / `TIMEOUT_SOFT` | `runtime` 决定重发 `BODY_04B` 或终止 `BODY_04_FAMILY` |
| `BODY_04C` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `OBJECT_STATE_ERROR` / `TIMEOUT_SOFT` / `ENGINE_ERROR` | `runtime + BODY_05` 依据 queryable summary 决定 stop / continue / retry |
| `BODY_10A` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `PATCH_ERROR` / `OBJECT_STATE_ERROR` | `runtime` 对当前 OT extension fail-fast |
| `BODY_10B` | `SYNC` | `HARD_BARRIER` | `NO_REPLAY` | `SOFT_STALL` / `OBJECT_STATE_ERROR` / `ENGINE_ERROR` | `runtime` 决定重发当前 body 或终止 `BODY_10_FAMILY` |
| `BODY_10C` | `QUERYABLE` | `SOFT_JOIN` | `NO_REPLAY` | `TIMEOUT_SOFT` / `OBJECT_STATE_ERROR` | `runtime` 把结果收口成 `accepted / rejected / retryable` 摘要 |

这里的 `NO_REPLAY` 必须按硬件控制语义理解：

- 不允许 scheduler 在 sub-body 内自由展开新的未编号 loop；
- 允许局部 queue absorb / local hold；
- 允许 `runtime` 在 body 或 family 边界做受控重发；
- 不允许把 `SOFT_JOIN` 误用成“对象还没提交也算成功”。

### 10.5 body 级重发与 family 级回退原则

当前建议固定下面四条最小规则：

1. 只要错误仍停留在 leaf-block busy / queue full / 短时对象未 ready，优先 local hold，不立刻上抬；
2. 一旦达到 `body_timeout`，必须结束当前 sub-body，并导出 `TIMEOUT_SOFT` 或更明确的对象/引擎错误；
3. 如果失败 sub-body 的输出尚未被后继 sub-body 消费，`runtime` 可以在 body 边界受控重发当前 sub-body；
4. 如果失败 sub-body 的输出已被后继路径消费，`runtime` 不应偷偷局部回滚，而应在 family 边界终止并重新建立对象一致性。

因此，`BODY_04C` / `BODY_10C` 的 `QUERYABLE + SOFT_JOIN` 只意味着：

- 上层可以先看到 queryable summary；
- 但对象提交、版本推进、history commit 仍然必须受控完成。

## 11. 最小可观测状态合同

### 11.1 运行时必须能导出的摘要

| 摘要项 | 所属层 | 作用 |
| --- | --- | --- |
| `episode_status` | `Host-FPGA` | 软件可见最终状态 |
| `bundle_status` | `FPGA-Chip` | bundle 失败定位 |
| `body_status` | `FPGA-Chip` | body 级失败定位 |
| `last_error_class` | `FPGA-Chip` | 快速分类 |
| `last_route_id` | chip 内 | route 相关错误定位 |
| `last_handle_id` | chip 内 | object state 错误定位 |
| `stall_counter` | chip 内 | 背压/资源拥塞画像 |
| `timeout_counter` | chip 内 | 超时画像 |

### 11.2 当前建议的最小计数器

- `episode_queue_stall_count`
- `bundle_soft_stall_count`
- `body_retry_count`
- `route_error_count`
- `object_state_error_count`
- `engine_error_count`
- `timeout_soft_count`
- `abort_count`

## 12. 当前已冻结与未冻结部分

### 12.1 已冻结到足以指导系统设计的内容

- 三层异常分层；
- 统一状态码主集合；
- `SOFT_STALL / RETRYABLE_ERROR / TIMEOUT_SOFT / LOCAL_MAX_ITER` 与硬失败的区分；
- backpressure 优先在局部消化的原则；
- `body_timeout / bundle_timeout` 作为主要软件可见 timeout 粒度；
- `BODY_04A/B/C` 与 `BODY_10A/B/C` 的 `completion/join/replay` 姿态已冻结到 sub-body 级。

### 12.2 仍未冻结的内容

- precise credit 数值与队列深度；
- 是否需要 `HARD_TIMEOUT` 与 `SOFT_TIMEOUT` 双级更多细分；
- resident 对象在 abort 后的保活策略；
- chip 内更多 RAS 机制；
- 计数器、trace、CSR 的真实地址和导出方式。

## 13. 与其他文档的关系

- `docs/architecture/system_design_master_spec_v0.md`
  - 主系统设计总规范；
- `docs/architecture/system_interface_contract_v0.md`
  - 主接口字段、route 集与对象状态合同；
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`
  - 事务层最早语义来源；
- `docs/control/qe_phase_cde_replay_bundle_contract_v0.md`
  - `Phase C/D/E` 下沉时需要遵守的异常与流控边界。

## 14. 当前一句话结论

> v0 的异常与流控合同已经足够把“出了问题怎么办、背压怎么吸收、谁负责升级错误”从口头讨论推进成正式系统约束，但还没有到 RTL 协议冻结阶段。
