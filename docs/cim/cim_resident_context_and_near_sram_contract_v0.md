# 2026-03-29 CIM Resident Context 与 Near-SRAM 协同合同 v0

## 1. 文档目标

这份文档的目标，是把前面已经在：

- `docs/cim/cim_macro_block_and_timing_v0.md`
- `docs/architecture/system_interface_contract_v0.md`
- `docs/control/long_control_word_isa_v0.md`

里出现、但还没有被单独冻结的一层正式写清楚：

- `resident_context` 到底是什么；
- 它和 `object handle`、`resident buffer tag`、`row_block` 的关系是什么；
- `CIM` 和 `Near-SRAM Support Domain` 在 `PROJECT/BACKPROJECT` 双模式下如何协同；
- `FPGA/runtime` 到 `Chip` 的 patch 点里，哪些字段必须显式存在。

这份文档不是新的系统构想，而是当前 `CIM` v0 路线继续下沉后的**接口与对象合同**。

## 2. 为什么现在必须单独写这份合同

到目前为止，`CIM` 路线已经收口成：

- `projector-column-resident SRAM digital CIM`
- `PROJECT`
- `BACKPROJECT`
- `PROJECT -> near-SRAM small transform -> BACKPROJECT`

但如果没有单独的 `resident_context` 合同，下面几个边界仍然会混在一起：

1. **一整个 episode 里常驻的是哪一组 projector**；
2. **当前正在处理哪个 `row_block`**；
3. **当前 `PROJECT` 产出的系数对象住在哪个近存缓冲域**；
4. **什么时候允许切换 context，什么时候只允许切换 `row_block`**。

因此，这份文件的主要作用就是把：

> `episode-scope resident set`、`row_block working set`、`transient coeff/row objects`

三层对象分清楚。

## 3. 对象层次

### 3.1 `resident_context`

`resident_context` 是 `CIM` 宏中一组可跨多个 replay / local iteration 复用的常驻对象集合。

在当前系统里，它不表示任意矩阵常驻，而专门表示：

- `projector / beta / projection basis` family
- 已按 `column_group`
- 已按 `row_block`
- 已按 `G0/G1/G2 + redundant modulus`

组织好的常驻对象布局。

它是 **episode-scope 或 body-scope 的常驻对象集合**。

### 3.2 `row_block`

`row_block` 是当前 `resident_context` 内部被激活的一段工作窗口。

它不是新的 resident context，也不是新的 object kind，而是：

- 同一个 `resident_context` 内的局部工作分块；
- `PROJECT` / `BACKPROJECT` 扫描时当前生效的行窗口；
- 由 `row_block_id` 选择。

它是 **context 内的 working-set selector**。

### 3.3 `transient coeff object`

`PROJECT` 的输出系数对象，如：

- `COEFF_PANEL`
- `PROJECT_COEFF_RESIDUE`

不应被等同于 `resident_context`。

它们是：

- 计算期产生的短命对象；
- 驻留在 `Near-SRAM` 的系数缓冲域；
- 可被 `Vector` 或 `Near-SRAM` 小变换消费；
- 再作为 `BACKPROJECT` 的输入返回 `CIM`。

### 3.4 `transient row object`

`BACKPROJECT` 的输出行对象，如：

- `ROW_PARTIAL`
- `PROJECTOR_APPLY_ROW`

也是短命对象。它们用于：

- 回投影后的 row-domain 结果暂存；
- 送往 assembler / closure / 下游近存聚合路径。

## 4. 正式字段合同

### 4.1 `ResidentContextDesc`

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `resident_context_id` | 标识 | 必需 | 当前常驻 context id |
| `resident_generation` | 版本 | 必需 | 当前 context 的装载代次 |
| `projector_family_id` | 模式 | 必需 | 对应哪一组 projector family |
| `layout_id` | 布局 | 必需 | 列组/行块/模组布局版本 |
| `modulus_profile_id` | 数值配置 | 必需 | `G0/G1/G2` 与冗余模配置 |
| `column_group_count` | 形状 | 必需 | 当前 context 的列组数 |
| `row_block_count` | 形状 | 必需 | context 内总 `row_block` 数 |
| `rows_per_block` | 形状 | 必需 | 每个 `row_block` 的行数 |
| `valid_row_block_mask` | 状态 | 可选 | 哪些 `row_block` 已经有效装载 |
| `context_state` | 状态 | 必需 | `LOADING / READY / LOCKED / DRAINING / RETIRED` |
| `lock_owner` | 控制 | 可选 | 当前由哪个 body / scheduler scope 持锁 |
| `source_tag` | 来源 | 可选 | 该 context 来自哪一份 runtime staging 对象 |

### 4.2 `RowBlockWindowDesc`

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `resident_context_id` | 绑定 | 必需 | 所属 context |
| `resident_generation` | 绑定 | 必需 | 绑定到哪一代 context |
| `row_block_id` | 标识 | 必需 | 当前工作窗口编号 |
| `first_row` | 形状 | 可选 | 对应原始行起点 |
| `row_count` | 形状 | 必需 | 当前块实际行数 |
| `column_group_mask` | 形状 | 可选 | 本块可见的列组子集 |
| `active_mod_group_mask` | 数值配置 | 必需 | 当前激活的 `G0/G1/G2` 组合 |

### 4.3 `CIMContextStatusSummary`

| 字段 | 类别 | 必需性 | 说明 |
| --- | --- | --- | --- |
| `resident_context_id` | 标识 | 必需 | 当前 context id |
| `resident_generation` | 版本 | 必需 | 当前代次 |
| `context_state` | 状态 | 必需 | 当前状态 |
| `loaded_row_blocks` | 摘要 | 可选 | 已完成装载的块数 |
| `active_row_block_id` | 摘要 | 可选 | 当前活动块 |
| `coeff_buf_tag` | 驻留 | 可选 | 当前系数缓冲位置 |
| `row_buf_tag` | 驻留 | 可选 | 当前行结果缓冲位置 |

## 5. `resident_context` 状态机约束

### 5.1 最小状态集合

| 状态 | 含义 |
| --- | --- |
| `LOADING` | 正在从 `Near-SRAM` staging 向 `CIM` 常驻 bank 装载 |
| `READY` | 已完成装载，可被 body 绑定 |
| `LOCKED` | 当前正在被一个 replay body 使用，不允许覆写 |
| `DRAINING` | 正在清空系数/行结果临时对象，准备切换 |
| `RETIRED` | 已退出当前 episode 或被新 generation 取代 |

### 5.2 主规则

- `LOADING -> READY` 之前，不允许 `PROJECT/BACKPROJECT` 消费该 context；
- `LOCKED` 状态下，只允许切换 `row_block_id`，不允许换 `resident_context_id`；
- generation 变化必须伴随 `READY -> LOCKED` 之前的显式确认；
- context 切换必须和 replay body / barrier 边界对齐。

## 6. `Near-SRAM` 协同对象

### 6.1 建议保留的专用缓冲域

| 缓冲域 | 所属域 | 作用 |
| --- | --- | --- |
| `SRAM_CTX_LOAD_BUF` | `Near-SRAM` | 临时存放待写入 `CIM` 的 context 载荷 |
| `SRAM_STAGE_BUF` | `Near-SRAM` | 保持 `X/psi panel` 等主输入对象 |
| `SRAM_COEFF_BUF` | `Near-SRAM` | 保持 `PROJECT` 输出系数与中间系数对象 |
| `SRAM_ROW_BUF` | `Near-SRAM` | 保持 `BACKPROJECT` 输出行对象 |
| `SRAM_META_BUF` | `Near-SRAM` | mask、layout、小控制对象 |

### 6.2 为什么 `coeff` 和 `row` 要单独成缓冲域

原因有三点：

1. `PROJECT` 和 `BACKPROJECT` 的方向完全不同；
2. `coeff object` 需要先经过小矩阵/向量变换再回投影；
3. `row object` 更接近下游 assembler / closure 路径，不应和系数对象混用同一个生命周期。

## 7. `FPGA/runtime -> Chip` patch 点

### 7.1 `ReplayBodyDesc` 至少应显式带出的字段

除当前已有字段外，建议在 body 级上显式保留：

| 字段 | 作用 |
| --- | --- |
| `resident_generation` | 指定本 body 绑定的是哪一代 context |
| `row_block_count_hint` | 给出本 body 预计会遍历多少个 `row_block` |
| `context_lock_policy` | `LOCK_ON_ENTER / HOLD_UNTIL_DONE / RELEASE_ON_EXIT` |

### 7.2 `PatchedLCWWord` 至少应显式带出的字段

除当前已有字段外，建议在单条 `LCW` 上显式保留：

| 字段 | 作用 |
| --- | --- |
| `resident_context_id` | 当前作用的 context |
| `resident_generation` | 当前 generation |
| `row_block_id` | 当前活动工作块 |
| `active_mod_group_mask` | 当前活跃模组，典型为 `G0 / G0+G1 / G0+G1+G2` |
| `cim_operand_role` | `X_PANEL / COEFF_PANEL` |
| `conjugate_policy` | `NONE / PROJECT_CONJ / BACKPROJECT_DIRECT` |

## 8. 详细 route 子集

本节是对 `docs/architecture/system_interface_contract_v0.md` 中聚合式 `CIM` route 的细化。

### 8.1 context 装载 route

| Route ID | Source | Sink | 作用 | 状态 |
| --- | --- | --- | --- | --- |
| `R20` | `HANDLE_IN_1` | `SRAM_CTX_LOAD_BUF` | runtime 下发 context 载荷对象 | 预留 |
| `R21` | `SRAM_CTX_LOAD_BUF` | `CIM_CTX_LOAD` | 把 context 数据写入 `CIM` 常驻 bank | 稳定 |

### 8.2 `PROJECT` 路线

| Route ID | Source | Sink | 作用 | 状态 |
| --- | --- | --- | --- | --- |
| `R22` | `SRAM_STAGE_BUF` | `CIM_IN_X` | 当前 `X/psi panel` 送入 `PROJECT` | 稳定 |
| `R23` | `CIM_OUT_COEFF` | `SRAM_COEFF_BUF` | `PROJECT` 系数结果回写近存 | 稳定 |

### 8.3 小变换与 `BACKPROJECT` 路线

| Route ID | Source | Sink | 作用 | 状态 |
| --- | --- | --- | --- | --- |
| `R24` | `SRAM_COEFF_BUF` | `VECTOR_IN` | 系数对象送入向量/小矩阵变换 | 稳定 |
| `R25` | `VECTOR_OUT_MISC` | `SRAM_COEFF_BUF` | 变换后系数回写系数缓冲 | 稳定 |
| `R26` | `SRAM_COEFF_BUF` | `CIM_IN_COEFF` | 系数对象送入 `BACKPROJECT` | 稳定 |
| `R27` | `CIM_OUT_ROW` | `SRAM_ROW_BUF` | 回投影行结果回写近存 | 稳定 |
| `R28` | `SRAM_ROW_BUF` | `SRAM_ASSEMBLER` | 行结果送往近存聚合/组装路径 | 稳定 |

## 9. 一条最小的执行序列

最小 projector-family apply 序列建议固定理解为：

```text
1. preload resident_context into CIM
2. lock resident_context on body enter
3. iterate row_block_id for PROJECT
4. write coeff objects into SRAM_COEFF_BUF
5. transform coeff objects in Near-SRAM / Vector domain
6. feed transformed coeff objects back for BACKPROJECT
7. write row objects into SRAM_ROW_BUF
8. drain SRAM_ROW_BUF to assembler / next closure stage
9. release or keep context according to context_lock_policy
```

这条序列最关键的意义是：

- 常驻的是 `resident_context`；
- 切换频繁的是 `row_block`；
- 流动的是 `coeff/row transient objects`。

## 10. 与其他文档的关系

- `docs/cim/cim_macro_block_and_timing_v0.md`
  - 给出 `CIM` 的阵列结构、计算流程与存储流程；
- `docs/architecture/system_interface_contract_v0.md`
  - 给出三层接口和聚合 route 合同；
- `docs/control/long_control_word_isa_v0.md`
  - 给出 `object handle`、`resident buffer tag`、`version` 等基础控制术语；
- `docs/architecture/system_design_master_spec_v0.md`
  - 给出主系统设计总规范。

## 11. 当前一句话结论

> `resident_context` 是 episode/body-scope 的常驻 projector 集，`row_block` 是 context 内 working-set selector，`coeff/row` 是近存域的短命对象；`CIM` 与 `Near-SRAM` 的接口应围绕这三层对象分别冻结，而不能继续混写成一个笼统的 `apply` 路径。
