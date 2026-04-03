# QE shell clustered FPGA v1 Cluster C hardware `cdiaghg` module规范（2026-04-02）

## 1. 目的与上下文
Cluster C 是 v1 clustered FPGA 架构中唯一负责 `cdiaghg` 的集群，它必须直接承接 Cluster B 输出的 reduced generalized Hermitian problem，并在 FPGA 主路径上完成 generalized → standard → solve → output 整条流水。本文档描述 Cluster C 的 front-end contract、具体计算桶（buckets）、buffer 组织、fallback 触发条件、指标采集点以及五类典型 QE case（small-Si / Si8 / graphene / Au slab / SiC32）对应的兼容性要求。它立足于现有 freeze spec（`B_to_C_reduced_fifo` barrier、生存期对象、buffer contract）和 architecture model（`T_C` 拆分、`n_active` 约束、crossover margin）提供可落表的 implementation-facing 规范。

这里必须明确区分两个包络：

- **当前 trace-backed 实现包络**：直接由当前 ready workload matrix 驱动，当前明确覆盖 `graphene≈8`、`small-Si≈16`、`Si8≈32`。
- **reserve-large 预留包络**：用于 `Au slab`、`SiC32` 一类大 case 的 headroom / fallback / crossover 研究；在拿到与当前 ready cases 同等粒度的 per-episode subspace summary 之前，它们不能冒充当前基线 capacity 的数值来源。

## 2. Front-end contract
### 2.1 Reduced descriptor ingestion
- 接口：`B_to_C_reduced_fifo` 交付 `reduced_matrices_descriptor`；每个 descriptor 包含：`n_active`、`H_sub` base address、`S_sub` base address、stride/width metadata、case id、boundary flags。
- 读取策略：Cluster C 发现 descriptor 后在 `diag_input_buffer` 内申请 `n_active^2 * 2`（对角/非对角） data window，并将 `H_sub`/`S_sub` 拉入片上 cache；输入阶段只负责装载、header 校验与 capacity check，不包含 factorization / transform / solver 计算。输入阶段需要核准 `n_active <= c_reduced_dim_cap`，否则立即通知 controller 走 fallback。
- Barrier：C 从 B 接收 descriptor 必须等待 `B_to_C_reduced_fifo` 产生完整 descriptor，N/A `stale` descriptor 会被丢弃；该 barrier 与 freeze spec 中 `B→C` barrier 对齐，确保 `H_sub/S_sub` 完整可见前 C 不开始。

### 2.2 Control handshake
- Controller 提供 `cdiaghg_mode` 信号：`hardware`／`fallback`，默认当 `resident_fit == yes` 且 buffer budget足够时设为 `hardware`；否则 `fallback`。
- 当 `hardware` 被选择且 C 能够完成 transform/solve 时，C 将在 `diag_solution_fifo` 设定 `diag_solution_descriptor`，包含 eigenpairs、norm estimates、residual proxy；当 `fallback` 触发，C 将把 descriptor 投递给 controller 以切换到 companion path 并置位 `cdiaghg_mode_selected=fallback_companion`。

## 3. Generalized→Standard 转换
### 3.1 S_sub factorization bucket
- 执行 `S_sub = L * L^H` 或 `S_sub = U^H * U` 的 Cholesky factorization（可复用 `c_solver_parallelism` 个通道并行）。
- Factorization bucket 输出 `L`/`U`，并更新 `diag_input_buffer` 中的 factorized header，供下游 transform bucket 读取。
- 同步点：作为 `T_C_compute` 的第一个子阶段完成，并在本地 compute pipeline 内产生 `S_factor_ready` 标记。

### 3.2 Transform bucket
- 使用 `L^{-1}`/`U^{-H}` 将 `H_sub` 变换为标准 Hermitian：`H_std = L^{-1} H_sub L^{-H}`。该步骤可分为“前向替换 + GEMM + 后向替换”三个 sub-bucket。
- 变换后立即写回 `diag_input_buffer` 中的 transform workspace，以供 solver bucket 直接拾取；无须落 Host。
- 如果 transform bucket 未在 `c_input_buffer_kib` 预算内完成，controller 需要触发 fallback (buffer saturation)。

### 3.3 Precondition & residual proxy bucket
- 在标准问题解出前，提前计算 `S_sub` 相关的 residual scaling（例如 `tr(S_sub)`, `diag(S_sub)`）为 D cluster 提供 `residual_status`；该数据流通过 `diag_solution_fifo` 携带到 D。

## 4. Solver core buckets
Cluster C 内部的 compute work 被划分为以下四个 buckets，分别服务不同阶段。

### 4.1 Factorization bucket
- 负责 `S_sub` 的 Cholesky 或 LDL^H factorization。
- 资源：`c_solver_parallelism` 条 factor pipeline、`c_input_buffer_kib` 中的 factor tile cache。
- 输出：factorized `L`/`U`，供 Transform bucket 和 residual proxy bucket 使用。

### 4.2 Transform bucket
- 在线执行 `H_std = L^{-1} H_sub L^{-H}`，包括三段替换/矩阵乘（forward/backward/GEMM）。
- 需要 `c_eigvec_buffer_kib` 的 scratch window 保存中间 `H_std`。
- 向 solver bucket 汇报 transform latency以便 `T_C_compute` 计数。

### 4.3 Standard eigensolver bucket
- 在 `H_std` 上执行 Hermitian eigensolve（例如 divide-and-conquer 或 QR）；`c_solver_parallelism` 控制并发 tile 数，`c_emit_bw_kib_per_us` 用于控制 `diagonalizer → diag_solution_fifo` 传输。
- 输出 `Lambda` 与 `C_std`（标准问题的 eigenvector），并从 `H_std` 中扫描 residual indicator（如 Rayleigh residual）。

### 4.4 Back-transform & emit bucket
- 将 `C_std` 回转为 generalized eigenvectors：`C = L^{-H} C_std`；结果写入 `eigvec_buffer`，`eigval_buffer` 用于存放 `Lambda`。
- 与 D 的 `diag_solution_descriptor` 聚合：`C`、`Lambda`、`residual_status`、`continuation_flag` 通过 `diag_solution_fifo` 送达。

## 5. Buffers 与 data staging
- `diag_input_buffer`：`c_input_buffer_kib` budget，分区为 `H_sub`, `S_sub`, `transform_workspace`，支持 `double-buffered` descriptor pipelining。
- `eigvec_buffer`：`c_eigvec_buffer_kib` 规格，必须支持最坏 `n_active * n_active` 大小，分配 `ping/pong` 两份供 solver bucket 与 D 交替访问。
- `eigval_buffer`：`c_eigval_buffer_kib`，用于存 eigenvalues，与 `diag_solution_fifo` 共同构成 `diag_solution_descriptor`。
- `diag_solution_fifo`：参照 freeze spec 的 FIFO contract，C 输出 `diag_solution_descriptor`，内含 `C_addr`, `Lambda_addr`, `residual_status`, `norm_estimate`, `continue_flag`，直接喂 D 而非 Host。
- Buffer guard：任何时刻 `c_input_buffer_kib + c_eigvec_buffer_kib + c_eigval_buffer_kib <= available_diag_budget`，否则 controller 置 `cdiaghg_mode_selected=fallback_companion`。

## 6. Fallback triggers & controller interface
- `n_active > c_reduced_dim_cap` 或 `resident_fit == no` → 由 controller 强制 `fallback`，C 立即将 `diag_solution_descriptor` 标记 `mode=fallback` 并向 `companion` 送 `reduced_matrices_descriptor`。
- `T_C_compute + T_C_emit` 超过 `T_companion`（包括 `added_diag_buffer_penalty`）时设置 `crossover_margin <= 0` → C 通过 controller 记录 `cdiaghg_mode_selected=fallback_companion` 并切至 fallback path。
- Buffer overflow（`diag_input_buffer` / `eigvec_buffer`）在 runtime 发生时，C 触发 `buffer_abort` 信号提供 `companion_trigger_reason` 给 controller。
- `C_to_D_solution_fifo` 仍保留 barrier 信号：C 必须在 `diag_solution_descriptor` 准备就绪后向 controller 递交 `C_complete` 以解除 `C→D` barrier。

## 7. KPIs 与 instrumentation点
- `T_C_input`: 从 descriptor 接收到 `H_sub/S_sub` 完成装载、header 校验和容量检查的时间；不包含 factorization / transform / solver。
- `T_C_compute`: 纯 hardware `cdiaghg` 计算时间，定义为 `T_C_factorize + T_C_transform + T_C_solver + T_C_backtransform`。
- `T_C_emit`: `diag_solution_descriptor` 打包并从 fifo 写出到 D 的时间；`c_emit_bw_kib_per_us` 控制吞吐。
- `cdiaghg_mode_selected`: `hardware` / `fallback_companion` flag（记录在 architecture model 里）。
- `crossover_margin`: `T_companion - (T_hw_diag + buffer_penalty)`，正值代表硬件模式获胜。
- `Bytes_spill`, `resident_fit`: 与 system model共享 `onchip_resident_budget_kib` 判据。
- `n_active`, `c_reduced_dim_cap`, `c_solver_parallelism`, `c_input_buffer_kib`, `c_eigvec_buffer_kib`, `c_eigval_buffer_kib`: 这些参数必须能被 trace/runner 拆出，用于填充 architecture table。

## 8. 兼容性指南：当前实现包络 vs reserve-large 包络

### 8.1 当前 trace-backed 实现包络
- **Small-Si**：当前 ready trace-backed 包络为 `n_active≈16`。默认 hardware path 应稳定覆盖这一档，并保留适度 margin，但不应把未来更大的预留值写成当前基线要求。
- **Si8 (`USPP` / `NC`)**：当前 ready trace-backed 包络为 `n_active≈32`。这是当前 `Cluster C` baseline capacity 的上限参考；只有在 `resident_fit == yes` 且 `crossover_margin > 0` 时保留 hardware path。
- **Graphene**：当前 ready trace-backed 包络为 `n_active≈8`。其重点不是大维度 capacity，而是短 episode 下的高频 `C→D` 交接和 controller 同步。

### 8.2 Reserve-large / future extension 包络
- **Au slab**：作为 reserve-large contact/interface case 参与 `Cluster C/D` 压力与 fallback 研究。它可以驱动 headroom 讨论和 `added_diag_buffer_penalty` 评估，但在取得与当前 ready cases 同等粒度的 subspace summary 前，不应被写成当前 trace-backed `c_reduced_dim_cap` 的硬约束。
- **SiC32**：作为 reserve-large wide-bandgap case 参与 large-case fallback 与 crossover 研究。当前应把它视为“条件性 large case”而不是当前 baseline-capacity 的直接数值来源。

因此，`Cluster C` 的默认冻结口径是：

- 基线 hardware capacity 先闭合当前 ready trace-backed envelope（`8 / 16 / 32`）
- reserve-large case 只用于 headroom / crossover / fallback 研究，直到其 per-episode `n_active` 摘要被冻结

## 9. 实施注意事项
- Cluster C 不直接输出 Host-visible 结果，所有 eigenpair 通过 `C_to_D_solution_fifo` 送 D；因此 D 必须等待 `diag_solution_descriptor` 且 `C→D` barrier 仍然存在。
- `diag_solution_descriptor` 中应携带 `residual_status/residual_norm` 以支持 D 的 refresh loop（与 freeze spec 中 D contract 对齐）。
- 若 controller 触发 fallback，C 仍保留 `diag_solution_fifo` 中的最后 descriptor 供 D 读取，避免 D 丢失 `P_next` 状态。
- 本 spec 是实现向导；任何 buffer size 变化需同步到 architecture model parameter list（Section 4.4 of model doc）。
