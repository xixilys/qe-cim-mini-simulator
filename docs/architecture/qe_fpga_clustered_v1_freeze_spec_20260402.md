# QE shell clustered FPGA v1 架构冻结规格（2026-04-02）

## 1. 作用

这份文档是当前 experiment 阶段对 v1 FPGA 实现视角的正式冻结件。

它冻结的不是：

- RTL 细节
- 精确位宽
- 最终频率
- 最终 buffer KiB 数值

它冻结的是：

- 物理 cluster 划分
- resident object 策略
- buffer / FIFO 合同
- hardware `cdiaghg` 的首选地位
- companion fallback 的边界条件

从这一版开始，`BODY_01/02/03/04` 仍然保留在 SystemC shell model 中，但只作为：

> software contract / shell-accounting layer

而不是：

> final implementation partition

## 2. v1 冻结结论

### 2.1 顶层系统对象

v1 仍然是：

- `Host`
- `FPGA runtime / persistent episode controller`
- `FPGA compute clusters`
- optional `companion cdiaghg` fallback path

系统对象仍然是：

> `QE-connected band-solver subsystem`

### 2.2 v1 首选硬件方向

v1 首选方向冻结为：

- `h_psi`：硬件
- `s_psi`：硬件
- `build H_sub / S_sub`：硬件
- `cdiaghg`：硬件优先
- `refresh / residual -> P_next`：硬件

fallback 路线冻结为：

- companion `cdiaghg` 允许保留，但只作为 bring-up / capacity / risk fallback，
- 不是首选系统叙事。

### 2.3 外层 shell 路径

当前 v1 不强制把以下部分一起硬化到同一主内环：

- `rho -> Veff`
- `psi -> rho_out`
- `mix_rho`

它们在 v1 中作为 shell-support path 保留独立建模；是否进一步下沉由后续板级和 traffic 结果决定。

## 3. 物理 cluster 划分

### 3.1 Cluster A：Fused Operator Sweep Cluster

**职责**

- 完成 `h_psi + s_psi`
- 在一次 panel / row-block sweep 中形成 H/S 相关 partials

**冻结原因**

- `h_psi` 与 `s_psi` 的输入对象和数据复用高度重合
- 若物理拆开，将重复搬运 `psi / projector / overlap` 数据

**接口**

- 输入：`Psi_panel`, `projector_state`, `overlap_state`, optional `Veff/support_tile`
- 输出：`partial_HS_packets`

### 3.2 Cluster B：Subspace Build Cluster

**职责**

- 接收 partials
- 聚合并生成 `H_sub / S_sub`

**冻结原因**

- 这是从 full-space object 向 reduced-space object 收缩的明确边界
- 更适合做本地 accumulation + reduction tree，而不是复用 A 或 C 的控制语义

**接口**

- 输入：`partial_HS_packets`
- 输出：`reduced_matrices_descriptor`

### 3.3 Cluster C：Hardware cdiaghg Cluster

**职责**

- 对 reduced generalized Hermitian problem 做硬件求解
- 输出 `C / Lambda` 及 refresh 所需求解结果

**冻结原因**

- 当前方向已经从 “companion 优先” 改成 “hardware first”
- 如果这块长期不进硬件，整条 episode 主路径的系统叙事会被削弱

**接口**

- 输入：`reduced_matrices_descriptor`
- 输出：`diag_solution_descriptor`

### 3.4 Cluster D：Basis Refresh Cluster

**职责**

- 接收 `diag_solution_descriptor`
- 完成 `refresh / residual -> P_next`
- 写回下一轮内环所需的 refreshed basis state

**冻结原因**

- 这是 loop-carried state 的主要更新边界
- 若不把它纳入主硬件路径，episode 闭环无法体现硬件持续收益

**接口**

- 输入：`diag_solution_descriptor`
- 输出：`P_next_descriptor`, `residual_status`, `episode_continue_flag`

### 3.5 Persistent Episode Controller

**职责**

- 管理 A/B/C/D 的调度、重试、终止条件与 inter-cluster handoff
- 对 Host 暴露 coarse-grain episode 级接口

**冻结原因**

- `CPU + FPGA` 不应模仿 `CPU + GPU` 的频繁 kernel launch 模式
- v1 必须把调度重心尽量压到 device 内部

## 4. resident object 冻结

下列对象在 v1 中冻结为 **优先 resident**：

### 4.1 Episode-scope resident objects

- `projector_state`
- `overlap_state`
- `active_basis_metadata`
- `resident_context`

这些对象默认不应在 A/B/C/D 每个 cluster 间重复从 Host 重新下发。

### 4.2 Inner-loop resident / rotating objects

- `Psi_panel / Psi_tile`
- `partial_HS`
- `H_sub / S_sub` staging objects
- `diag_solution` staging objects
- `P_next / refreshed_basis_slots`

这些对象允许在 cluster 间流动，但默认应先经过片上 buffer / FIFO，而不是直接落回 Host。

### 4.3 Shell-support objects

- `rho`
- `Veff`
- `mixed_rho`

这些对象在 v1 中不要求全部 resident 在同一硬件主环中，但其边界流量必须被显式计数。

## 5. buffer / FIFO 合同冻结

### 5.1 Cluster A buffer contract

至少包含：

- `Psi_panel_ping`
- `Psi_panel_pong`
- `projector_state_bank`
- `partial_HS_fifo`

冻结规则：

- `Psi` 面板采用双缓冲
- projector / overlap state 采用 episode-scope resident bank
- partial 输出不应直接落 Host

### 5.2 Cluster B buffer contract

至少包含：

- `partial_HS_accum_buffer`
- `H_sub_stage_buffer`
- `S_sub_stage_buffer`
- `reduced_matrices_fifo`

冻结规则：

- `H_sub/S_sub` 至少要有独立 staging buffers
- B 到 C 的交接默认走 reduced descriptor FIFO

### 5.3 Cluster C buffer contract

至少包含：

- `diag_input_buffer`
- `eigvec_buffer`
- `eigval_buffer`
- `diag_solution_fifo`

冻结规则：

- `cdiaghg` 输入输出默认不经 Host 回写
- C 的输出必须能直接喂 D

### 5.4 Cluster D buffer contract

至少包含：

- `refresh_scratch_buffer`
- `residual_buffer`
- `P_next_slots`
- `episode_status_register`

冻结规则：

- D 负责生成下一轮可见的 `P_next`
- D 负责向 controller 报告 `continue / stop`

### 5.5 Inter-cluster FIFO contract

冻结为以下三条主 FIFO：

- `A_to_B_partial_fifo`
- `B_to_C_reduced_fifo`
- `C_to_D_solution_fifo`

这是 v1 的物理主干路径。

## 6. overlap / barrier 规则冻结

### 6.1 允许 overlap

- A 内部 panel / tile 加载与前一批计算重叠
- B 的局部 accumulation 与 A 的后续 partial 产生可局部重叠
- D 的局部 refresh 写回与 controller 下一轮准备可局部重叠

### 6.2 必须 barrier

以下边界当前冻结为必须 barrier：

- `B -> C`：`H_sub / S_sub` 完整可见后，`cdiaghg` 才开始
- `C -> D`：`diag_solution_descriptor` 完整可见后，refresh 才开始
- `D -> next inner-step`：`P_next_descriptor` 提交后，下轮 A 才可读取更新 basis state

这三处 barrier 是当前 v1 最小正确性边界。

## 7. hardware `cdiaghg` 与 fallback companion 的关系

### 7.1 首选路径

冻结为：

- hardware `cdiaghg` 是 v1 主路径
- baseline comparison 和 architecture exploration 都要以此为首选设计点

### 7.2 fallback 条件

仅在下列情况下允许切到 companion：

- reduced dimension 超出当前硬件 diagonalizer capacity
- area / timing closure 风险导致 v1 bring-up 无法完成
- first board bring-up 需要临时保底路径验证其他 clusters

### 7.3 fallback 合同

即使切换到 companion，也必须保持：

- `B_to_C_reduced_fifo` 改为 `B_to_companion_descriptor`
- `companion_to_D_solution_descriptor` 返回 D
- Host 看到的 shell contract 不变

也就是说：

- fallback 允许改变实现域
- 不允许改变 shell 语义与比较口径

## 8. 当前不冻结的内容

以下内容明确不在这次 freeze 中冻结：

- Cluster A 内部是否采用 CIM、SIMD、或小 systolic array 的最终微结构
- Cluster C 的具体 generalized eigensolver 算法实现细节
- 精确 BRAM/URAM/HBM KiB 数值
- 频率、功耗、面积的最终数值
- `rho -> Veff` / `psi -> rho_out` 是否在 v1 进一步合并进主硬件环

这些属于 Task 12 的 architecture model 和后续 FPGA bring-up 范围。

## 9. 对后续任务的直接要求

完成这次 freeze 后，后续任务必须按以下顺序推进：

1. 用当前 freeze spec 建 cluster-level architecture model
2. 明确 resident object 和 spill 条件
3. 建 hardware `cdiaghg` 与 fallback companion 的 crossover 模型
4. 再进入 `CPU only / CPU + GPU / CPU + FPGA` 的最终对比

## 10. 当前冻结结论

当前 v1 FPGA 架构正式冻结为：

- `persistent episode controller`
- `Cluster A = fused h_psi + s_psi`
- `Cluster B = build H_sub / S_sub`
- `Cluster C = hardware cdiaghg`
- `Cluster D = refresh / residual -> P_next`
- `companion cdiaghg = fallback only`
- `BODY_01/02/03/04 = shell contract layer only`
