# 2026-03-27 `QE c_bands episode` 到 LCW 的 lowering v0

## 1. 文档目标

这份文档的目标不是重新解释 `QE` 算法，而是回答一个更具体的问题：

> 如果 chip 顶层真的采用 `Long Control Word (LCW)`，那么一个最小 `QE c_bands episode` 到底会被展开成怎样的一串控制字？

这份文档的作用有三层：

1. 验证当前五个 slot：`CIM / FFT / SRAM / Solve / Vector` 是否足以闭环；
2. 验证前一份“模块完整功能清单”里的每个模块职责是不是落得下来；
3. 提前暴露当前 LCW v0 里可能仍然分错或缺失的地方。

这里仍然坚持当前已经收口的系统对象：

- 真实系统对象是 `Host + FPGA/runtime + Chip` 的混合系统；
- chip 内部对象先锁定在 `QE-connected band-solver subsystem`；
- 具体执行口径先锁定在一个最小 `c_bands episode`。

## 2. lowering 所依据的最小 episode 合同

这里沿用 `docs/architecture/qe_band_solver_transaction_semantics_20260326.md` 里的最小事务口径。

一个 v0 `c_bands episode` 至少包含下面这些对象：

- 输入大对象：`X_PANEL`
- resident 对象：`PROJECTOR_SET`, `VLOC_SLICE`, `POTENTIAL_EPOCH`
- 中间对象：`HPSI_PARTIAL`, `SPSI_PARTIAL`, `FULL_H`, `FULL_S`, `REDUCED_FEED`
- reduced 对象：`H_SUB`, `S_SUB`, `RITZ`, `ET`
- 闭环对象：`RESIDUAL`, `NEXT_X_PANEL`

并且先只考虑最常见的一类 generalized path：

- 有 `Hpsi`
- 有 `Spsi`
- 有 reduced build
- 有 reduced solve
- 有 residual / next-`X` closure
- 若未收敛，则进入下一轮 local loop

## 3. lowering 的基本原则

### 3.1 LCW 不直接表达完整数学式，而表达阶段化数据流

在 lowering 之后，一条 LCW 不试图描述完整的：

- `H X`
- `S X`
- `X^H H X`
- `X^H S X`
- residual 公式

它只表达：

- 哪些引擎此阶段启动；
- 输入 object handle 从哪里来；
- 输出 object handle 流向哪里；
- 这一阶段何时可视为“完成并可被下阶段消费”。

### 3.2 一个 `c_bands` local iteration 先拆成六个 phase

为了让 v0 足够清晰，先把一个 local iteration 拆成下面六段：

1. `LOAD_AND_STAGE`
2. `FFT_PREP`（可选）
3. `PROJECTOR_APPLY_CHAIN`
4. `ASSEMBLE_AND_REDUCE`
5. `SOLVE_AND_CLOSE`
6. `LOOP_DECIDE`

这六段不一定是一一对应六条 LCW，但至少能帮助我们检查模块边界。

### 3.3 v0 先按“最保守可验证” lowering

也就是说：

- 不追求把所有动作压缩成最少 LCW 条数；
- 优先让 phase 边界清楚；
- 优先暴露 route / object handle / join 是否足够表达；
- 允许后续 v1 再做融合与压缩。

## 4. 一个最小 generalized `c_bands` local iteration 的 LCW 序列

下面给出一个最小 local iteration 的参考 lowering。它不是唯一实现，但足够检验 v0 架构。

---

## 5. LCW #0：`LOAD_AND_STAGE`

### 5.1 目标

把 host/runtime 送来的 `X_PANEL`、本轮要用的 meta state，以及必要的 resident-context 绑定到 chip-local 执行环境。

### 5.2 激活的 slot

- `CIM Slot`：`IDLE`
- `FFT Slot`：`IDLE`
- `SRAM Slot`：`STAGE`
- `Solve Slot`：`IDLE`
- `Vector Slot`：`META_PREP`

### 5.3 典型 route

- `HANDLE_IN_X -> SRAM_STAGE_BUF`
- `HANDLE_IN_META -> VECTOR_META_BUF`

### 5.4 commit 语义

- `dst_handle_0 = STAGED_X_PANEL_HANDLE`
- `dst_handle_1 = READY_META_HANDLE`
- `join_mode = HARD_BARRIER`

### 5.5 它检验了哪些模块功能

#### `Near-SRAM Support Domain`
必须已经能做：
- `STAGE`
- `HOLD`
- `X_PANEL` 这类对象登记
- object handle 到 resident buffer tag 的映射记录

#### `SIMD / Vector Companion`
必须已经能做：
- meta unpack
- band/panel shape 检查
- mask / active-band state 初始化

#### `Command Scheduler`
必须已经能做：
- episode 上下文装填
- object-handle 生命周期起点登记
- resident set 合法性检查

### 5.6 暴露出的设计判断

这一步说明 `Vector Slot` 不是可有可无的。

如果没有 `Vector Slot`，那么：
- shape / band-mask / loop metadata 只能塞回 scheduler；
- scheduler 会变成又做控制又做轻量数据处理的混合体；
- 这会让 `CP2K/VASP` 扩展时的控制平面变脏。

所以 `Vector Slot` 在 v0 就应该保留。

---

## 6. LCW #1：`FFT_PREP`（可选）

### 6.1 目标

如果本轮需要显式 `G <-> R` 变换或 transform-side reorder，这一条负责把 `X_PANEL` 变成后续 `APPLY` 更适合消费的表示。

### 6.2 激活的 slot

- `CIM Slot`：`IDLE`
- `FFT Slot`：`G_TO_R` 或 `REORDER`
- `SRAM Slot`：`FORWARD`
- `Solve Slot`：`IDLE`
- `Vector Slot`：`PACK`（可选）

### 6.3 典型 route

- `SRAM_STAGE_BUF -> FFT_IN`
- `FFT_OUT -> SRAM_STAGE_BUF`
- `VECTOR_OUT -> SRAM_META_BUF`（可选）

### 6.4 commit 语义

- `dst_handle_0 = FFT_READY_X_HANDLE`
- `completion_mode = ASYNC_OK`
- `join_mode = SOFT_JOIN`

### 6.5 它检验了哪些模块功能

#### `FFT Engine`
必须已经能做：
- `G_TO_R`
- `R_TO_G`
- `REORDER`
- shape-aware transform mode 选择

#### `Near-SRAM Support Domain`
必须已经能做：
- staged object 原地替换或版本化登记
- transform 前后 object-handle continuity 维护

### 6.6 暴露出的设计判断

这一步说明：

- `FFT Slot` 仍然是显式独立 slot；
- 但它不必每轮都激活；
- 因此固定流水不如 LCW 更自然。

这正好解释为什么未来兼容 `VASP/CP2K` 时，chip top 不该是一条 rigid pipe。

---

## 7. LCW #2：`PROJECTOR_APPLY_CHAIN`

### 7.1 目标

对同一个 `X_PANEL` 在同一阶段完成主 operator family 的核心计算：

- `PROJECT`
- `near-SRAM coefficient transform`
- `BACKPROJECT`

这里 v0 不要求所有子动作物理同拍完成，但 LCW 必须能够把它们当作一个受控阶段发起。

### 7.2 激活的 slot

- `CIM Slot`：`PROJECTOR_APPLY_CHAIN`
- `FFT Slot`：`IDLE`
- `SRAM Slot`：`MERGE_PARTIAL_PREP`
- `Solve Slot`：`IDLE`
- `Vector Slot`：`MASK`

### 7.3 典型 route

- `SRAM_STAGE_BUF -> CIM_IN_X`
- `CIM_OUT_COEFF -> SRAM_COEFF_BUF`
- `SRAM_COEFF_BUF -> CIM_IN_COEFF`
- `CIM_OUT_ROW -> SRAM_ROW_BUF`

### 7.4 commit 语义

- `dst_handle_0 = PROJECTOR_PARTIAL_HANDLE`
- `dst_handle_1 = PROJECTOR_META_HANDLE`
- `join_mode = HARD_BARRIER`

### 7.5 它检验了哪些模块功能

#### `CIM / Projector-Apply Engine`
必须已经能做：
- resident projector / nonlocal context 绑定
- `PROJECT`
- `near-SRAM coefficient transform`
- `BACKPROJECT`
- partial 输出带 tag

#### `Near-SRAM Support Domain`
必须已经能做：
- 接收 coeff/row partial
- 记录 projector-chain 阶段类型
- 同 panel / same-iteration partial 对齐

#### `SIMD / Vector Companion`
必须已经能做：
- active band mask
- select / compact / skip already-converged bands

### 7.6 暴露出的设计判断

这里出现了第一个真正关键的问题：

> `CIM Slot` 里是否应该直接存在一个 `PROJECTOR_APPLY_CHAIN` 复合模式，而不是只暴露最原子的 `PROJECT/BACKPROJECT`？

当前判断是：

- LCW 层应该允许复合模式存在；
- 但复合模式的内部微序仍然由引擎本地控制；
- 否则 scheduler 需要拆太多 word，控制字数量会膨胀。

也就是说，LCW v0 更像“阶段级控制”，不是每个微操作一条 word。

---

## 8. LCW #3：`ASSEMBLE_AND_REDUCE`

### 8.1 目标

把 `Hpsi/Spsi` partial、当前 `X_PANEL` 与必要的 local state 组装成 reduced-build 所需输入，并形成 `H_SUB/S_SUB`。

### 8.2 激活的 slot

- `CIM Slot`：`IDLE`
- `FFT Slot`：`IDLE`
- `SRAM Slot`：`ASSEMBLE_FULL + FEED_REDUCED`
- `Solve Slot`：`REDUCE_BUILD`
- `Vector Slot`：`LAYOUT`

### 8.3 典型 route

- `SRAM_PARTIAL_BUF_H -> SRAM_ASSEMBLER`
- `SRAM_PARTIAL_BUF_S -> SRAM_ASSEMBLER`
- `SRAM_STAGE_BUF -> SRAM_ASSEMBLER`
- `SRAM_REDUCED_FEED -> SOLVE_IN`
- `SOLVE_OUT_REDUCED -> SRAM_META_BUF`

### 8.4 commit 语义

- `dst_handle_0 = H_SUB_HANDLE`
- `dst_handle_1 = S_SUB_HANDLE`
- `join_mode = HARD_BARRIER`

### 8.5 它检验了哪些模块功能

#### `Near-SRAM Support Domain`
必须已经能做：
- `MERGE_PARTIAL`
- `ASSEMBLE_FULL`
- `FEED_REDUCED`
- 将大对象和 reduced-build 输入在本地连续组织

#### `Reduction / Closure / Solve Engine`
必须已经能做：
- `REDUCE_BUILD`
- 支持 generalized 路径
- reduced object 输出对象句柄化

#### `SIMD / Vector Companion`
必须已经能做：
- reduced 输入前的 layout 整理
- index / stride / compact metadata 处理

### 8.6 暴露出的设计判断

这一步说明 `SRAM Slot` 独立存在是合理的，因为：

- reduced build 之前最关键的不是新算子，而是对象装配与连续性；
- 如果把这些动作强塞到 `Solve Slot`，会模糊“算法求解”和“近存数据组织”的边界；
- 这样也会掩盖本项目真正的重要系统收益：chip-local continuity。

---

## 9. LCW #4：`SOLVE_AND_CLOSE`

### 9.1 目标

在 reduced 空间内完成本轮局部闭环：

- 求解 reduced 问题
- 计算 Ritz / eigvals
- 形成 residual
- 生成 next-`X` 或更新后的 band-state

### 9.2 激活的 slot

- `CIM Slot`：`IDLE`
- `FFT Slot`：`IDLE`
- `SRAM Slot`：`FORWARD`
- `Solve Slot`：`SOLVE + CLOSURE`
- `Vector Slot`：`POSTPROC`

### 9.3 典型 route

- `SRAM_META_BUF -> SOLVE_IN`
- `SOLVE_OUT_RITZ -> VECTOR_IN`
- `VECTOR_OUT_RESIDUAL -> SRAM_STAGE_BUF`
- `VECTOR_OUT_NEXT_X -> SRAM_STAGE_BUF`

### 9.4 commit 语义

- `dst_handle_0 = RESIDUAL_HANDLE`
- `dst_handle_1 = NEXT_X_HANDLE`
- `completion_mode = ASYNC_OK`
- `join_mode = SOFT_JOIN`

### 9.5 它检验了哪些模块功能

#### `Reduction / Closure / Solve Engine`
必须已经能做：
- `SOLVE`
- generalized / standard mode 选择
- `CLOSURE`
- residual-side small dense operations 的承接

#### `SIMD / Vector Companion`
必须已经能做：
- Ritz 后处理
- residual norm / band mask 更新
- correction / next-`X` 形成中的辅助向量计算

#### `Near-SRAM Support Domain`
必须已经能做：
- residual / next-`X` 的继续驻留
- 为下一轮 local iteration 提供 continuity

### 9.6 暴露出的设计判断

这一步提示：

- `Solve Slot` 目前内部仍然偏大；
- 但在 v0 阶段还不必马上拆成 `ReducedBuild / Diag / Closure` 三个 slot；
- 更合理的做法是先保留一个大 slot，再在模式集合中区分：
  - `REDUCE_BUILD`
  - `SOLVE_ONLY`
  - `SOLVE_AND_CLOSE`
  - `CLOSURE_ONLY`

也就是说，当前问题更像是 `Solve Slot` 的 mode taxonomy 还要细化，而不是立即增加新的顶层 slot。

---

## 10. LCW #5：`LOOP_DECIDE`

### 10.1 目标

根据 residual / active-band 状态，决定：

- 当前 episode 是否局部结束；
- 是否需要下一轮 local iteration；
- 下一轮是否启用相同 route 模板。

### 10.2 激活的 slot

- `CIM Slot`：`IDLE`
- `FFT Slot`：`IDLE`
- `SRAM Slot`：`HOLD` 或 `RECYCLE`
- `Solve Slot`：`IDLE`
- `Vector Slot`：`LOOP_CTRL`

### 10.3 典型 route

- `SRAM_STAGE_BUF -> VECTOR_IN`
- `VECTOR_OUT -> HANDLE_OUT_LOOP`

### 10.4 commit 语义

- `dst_handle_0 = LOOP_DECISION_HANDLE`
- `completion_mode = HARD_DONE`

### 10.5 它检验了哪些模块功能

#### `SIMD / Vector Companion`
必须已经能做：
- active-band 统计
- convergence mask 更新
- 下一轮元数据生成

#### `Command Scheduler`
必须已经能做：
- 根据 `LOOP_DECISION` 选择 replay 下一轮模板
- 保证 object handle 没有被过早释放
- 处理 episode-done 和 local-replay 的分叉

### 10.6 暴露出的设计判断

这一步再次证明 scheduler 不能自己承担 loop 数值判断。

更好的分工是：
- `Vector Slot` 生成 compact 的 loop-decision payload；
- scheduler 只负责据此切换控制流。

这样系统才保持“控制面”和“轻量数值面”的分离。

## 11. 从这组 lowering 反推：六个模块的完整功能是否够用

### 11.1 `Command Scheduler`
当前是够用的，但必须再明确三件事：
- 能否原生支持 loop-template replay；
- object-handle 生命周期是否支持同一对象跨多 phase 常驻；
- `SOFT_JOIN` 和 `HARD_BARRIER` 的语义边界要进一步写死。

### 11.2 `CIM / Projector-Apply Engine`
当前方向是对的。

但 v0 更适合把它的对外 mode 写成两层：
- 外层：`PROJECT_ONLY`, `BACKPROJECT_ONLY`, `PROJECTOR_APPLY_CHAIN`
- 内层：由引擎本地微序实现具体 `project/coeff-transform/backproject` 顺序

### 11.3 `FFT Engine`
当前功能集合够用。

真正要注意的是：
- 不要把所有 reorder 都丢给 `Vector Slot`；
- transform-伴随的数据布局修正应该主要仍由 `FFT Slot` 负责。

### 11.4 `Near-SRAM Support Domain`
这是当前系统里最关键、也最容易低估的模块。

如果没有它，当前 `c_bands` 路径仍然能“算”，但很难体现：
- partial merge 的 local continuity
- reduced feed 的组织优势
- residual / next-`X` 的局部闭环优势

所以它不只是 buffer，而是系统收益的重要载体。

### 11.5 `Reduction / Closure / Solve Engine`
当前还不能拆得太早，但已经能看出需要进一步细化 mode：
- `REDUCE_BUILD`
- `SOLVE_ONLY`
- `CLOSURE_ONLY`
- `SOLVE_AND_CLOSE`

真正要避免的是把所有小 dense 事情都塞给 `Vector Slot`，否则 `Solve Slot` 会被掏空。

### 11.6 `SIMD / Vector Companion`
当前是必须保留的。

它至少承担三类不可忽略的任务：
- meta / layout / band-mask 处理
- solve 后辅助向量计算
- loop-decision payload 形成

这说明它不是“可选小助手”，而是 generalized compatibility 的关键缓冲层。

## 12. 当前 LCW v0 仍然暴露出的四个缺口

### 12.1 缺口一：`CIM Slot` 的 mode 还太原子或太模糊

需要在“原子模式过多”和“全部糊成一个 APPLY”之间找平衡。

当前更合理的收口是：
- 保留少量复合 mode；
- 让 mode 对应一个稳定的 operator family；
- 不让 scheduler 看到过多引擎内部细节。

### 12.2 缺口二：`Solve Slot` 需要 mode 细化，但未必需要 slot 拆分

这件事最容易做过头。

当前更合理的判断是：
- 先细化 `Solve Slot` 模式集合；
- 暂不新增 `Diag Slot` 或 `Closure Slot`；
- 等真有 `VASP/CP2K` lowering 例子顶不住时再拆。

### 12.3 缺口三：route 语义还缺少“版本化对象”表达

例如：
- `X_PANEL@iter0`
- `X_PANEL@iter1`
- `RESIDUAL@iter1`

如果没有这层语义，scheduler 和 SRAM 域在 replay 时容易混淆“同名但新版本”的 object handle。

所以 LCW v1 最好加一层轻量 object-version tag。

### 12.4 缺口四：还缺一个“模板化 lowering”视角

当前文档还是人工写出的单串 LCW。

后面需要进一步定义：
- 哪些 LCW 是每个 episode 固定模板；
- 哪些字段由 runtime 在下发时 patch；
- 哪些字段由 chip 内 scheduler 在 local replay 时自动回填。

这件事对 future `VASP/CP2K` 兼容非常关键。

补充一点：这件事现在已经不再只是 `QE Phase B` 自己的抽象需求。

当前正式控制栈里，`BODY_04A/B/C` 与 `BODY_10A/B/C` 都已经冻结了各自的：
- `template_id`
- `patch_mask`
- `completion_mode / join_mode`
- `replay_policy`

因此这份 `QE c_bands` lowering 文档现在应被理解为：

> 一份针对 `Phase B` body-local `LCW` 模板的 worked example，
> 它和 `BODY_04A/B/C`、`BODY_10A/B/C` 一起，共同组成 `descriptor -> template -> runtime-managed body -> bundle` 的统一控制栈。

## 13. 对“每个模块完整功能”这件事的当前结论

如果只看静态模块清单，上一份文档已经基本够用。

但经过这次 `QE c_bands -> LCW` lowering 之后，可以把“完整功能”更准确地理解成：

- `Command Scheduler`：必须能管模板 replay、依赖、object-handle 生命周期；
- `CIM Engine`：必须能对外提供稳定的 projector/apply family 模式；
- `FFT Engine`：必须承担 transform + transform-side reorder；
- `Near-SRAM Domain`：必须承担 stage / merge / assemble / reduced-feed / continuity；
- `Solve Engine`：必须承担 reduce-build + solve + closure 主闭环；
- `Vector Companion`：必须承担 meta/layout/postproc/loop-decision 辅助面。

所以从系统完整性看，当前六模块划分是成立的，问题主要已经从：

- “模块是否该存在”

转成了：

- “每个模块的 mode taxonomy 怎么冻结”
- “LCW 模板如何 patch / replay”
- “object-handle/version 语义如何明确”

## 14. 建议的下一步

沿当前路线，最合理的下一步不是再拆新的 control 文档，而是在现有几份主文件里继续冻结：

1. 在 `docs/control/long_control_word_isa_v0.md` 中继续收紧 slot mode taxonomy、descriptor family 与 template/replay 边界；
2. 在 `docs/architecture/system_interface_contract_v0.md` 中继续补 route、端点与对象态字段；
3. 在 `docs/control/qe_phase_cde_replay_bundle_contract_v0.md` 与 `docs/control/body10_ot_block_update_contract_v0.md` 已经冻结 `BODY_04A/B/C`、`BODY_10A/B/C` 的基础上，继续把 `Phase B` lowering 和这套统一控制栈对齐。

如果只选一个优先级更高的，我建议先做第 `2` 个，因为这更直接关系到：

- route 语义是否足够稳定；
- object-handle/version 是否真的能在接口层闭合；
- `QE` lowering 暴露出的缺口能否被正式字段吸收。
