# QE 系统 DSE 前端输入：partition and interface freeze v0

## 0. 定位

这份文档对应系统 DSE 的 **Step-2 输入 artifact**。

在 `Step-1` 的 `kernel characterization matrix` 已经冻结后，这里继续回答三件事：

1. `Host / FPGA / Chip` 三层到底怎么分工；
2. 第一波 accelerator candidate kernel 的边界应该落在哪里；
3. 后续 system-level DSE 要围绕哪些 interface / residency / fallback 问题展开，而不是重新回到“整个 DFT 都搬上硬件”的叙事。

这份文档是对以下证据的收口，而不是新的 speculative 设计：

- `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md`
- `docs/architecture/host_managed_full_scf_architecture_v1_20260409.md`
- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_d_refresh_spec_20260402.md`
- `docs/overview/agent_handoff_20260312.md`

---

## 1. Step-2 冻结目标

当前阶段，partition 的目标不是直接冻结最终微结构，而是：

- 把 system object 明确成 `Host CPU -> thin device runtime -> hardware datapath`；
- 让第一波 accelerator kernels (`h_psi / s_psi`) 有稳定输入输出边界；
- 让 companion kernels (`build H_sub/S_sub`, `refresh/residual`) 与主热点形成闭环；
- 明确 `cdiaghg` 的 fallback/companion 角色，避免系统叙事漂移成“只做 reduced diag”。

也就是说，当前 Step-2 追求的是：

> **可执行、可比较、可进入 system-level DSE 的边界冻结**，
> 而不是“先把所有 cluster / lane / SRAM 都 RTL 化”。

---

## 2. 系统对象冻结

当前系统对象固定为三层：

1. `Host CPU / software runtime`
2. `Thin device runtime / firmware bridge`
3. `Hardware datapath`

对应的 shell contract 仍然是：

```text
rho -> Veff
while bands not converged {
  h_psi
  s_psi
  build H_sub / S_sub
  cdiaghg
  refresh / residual -> P_next
}
psi -> rho_out
mix_rho / convergence gate
```

但从 Step-2 开始，这条链不再被读成“所有阶段都应该进入同一硬件对象”，而是读成：

- 哪些阶段是 **host-side shell control**；
- 哪些阶段是 **device runtime orchestration and data movement**；
- 哪些阶段是 **first-wave hardware datapath hot path**。

---

## 3. 三层分工冻结

### 3.1 Host CPU

Host 固定负责：

- 外层 `SCF` 循环
- `rho -> Veff`
- `mix_rho`
- 全局 convergence 判断
- `k-point / band batch` 组织
- workload trait / policy 选择
- `DiagPolicy` 生成
- host-side diagonalization fallback

Host 当前**不直接负责**：

- 逐条 `LCW` 下发；
- cluster/FIFO 级资源管理；
- resident window 生命周期；
- `h_psi/s_psi` 的内层 projector sweep 数据通路。

### 3.2 Thin device runtime

Thin device runtime 固定负责：

- resident preload / reuse 判断
- `Host DRAM <-> Device HBM/DDR` DMA
- request 到内部 episode/cluster descriptor 的映射
- launch / completion / perf summary
- `diag` fallback 的导出、同步、回传
- spill / resident-fit / host-assist 统计

它的职责不是“重新实现 QE 控制平面”，而是：

> 把上层 shell request 变成 hardware datapath 可以稳定消费的批次、resident set、policy 和 completion surface。

### 3.3 Hardware datapath

当前第一波强制放入硬件 datapath 的功能是：

- `h_psi / s_psi`
- `build H_sub / S_sub`
- `refresh / residual -> P_next`

而 `cdiaghg` 的定位冻结为：

- hardware-first proxy / optional hardware lane
- 但**必须允许回退**到 Host CPU / soft-core companion
- 不能把“diag 完全硬化”当作 v1 system DSE 的成功标准

---

## 4. 第一波 kernel 与层级映射

| Kernel / stage | Host | Thin device runtime | Hardware datapath | 当前冻结角色 |
| --- | --- | --- | --- | --- |
| `h_psi` | 只保留高层 request 语义，不执行主体算子 | 负责 batch DMA、resident preload、launch、completion summary | **主执行路径** | 第一波主热点 |
| `s_psi` | 只保留高层 request 语义，不执行主体算子 | 同上 | **主执行路径** | 第一波主热点 |
| `build H_sub / S_sub` | 不承担主体计算 | 负责把 partial stream / reduced descriptor 接成可调度对象 | **主执行路径（companion hot path）** | 第一波 companion kernel |
| `cdiaghg / rdiaghg` | **保留 host fallback / companion solver** | 负责 reduced export / import / sync | 可有 hardware-first proxy，但非强制主闭环 | 第一波 companion / fallback |
| `refresh / residual -> P_next` | 不承担主体计算 | 负责 descriptor handoff / lifecycle tracking | **主执行路径（companion hot path）** | 第一波 companion kernel |
| `rho -> Veff` | **主执行路径** | 只负责 device-visible metadata / potential slice transport（若需要） | 非第一波主核 | host-kept shell stage |
| `psi -> rho_out` | 结果由 host-visible shell 收口 | 负责必要的 batch/result return | 非第一波主核 | host-visible reduction stage |
| `mix_rho / convergence gate` | **主执行路径** | completion summary / status return | 不进入第一波 datapath | host-kept shell stage |

---

## 5. 第一波 interface 冻结

当前可直接用于 Step-3 DSE 的 public interface 对象，延续 runnable model 的五类对象：

### 5.1 `ResidentSetDesc`

表达应预加载并尽量复用的常驻对象：

- projector/beta family
- overlap / support-grid mode
- potential slice metadata
- resident footprint / preload budget

对 Step-2 的意义：

- 它是 `h_psi / s_psi` 能否做成 resident-aware dataflow 的核心接口；
- 后续 `resident_policy` 与 `spill_ratio` 都要围绕它定义。

### 5.2 `BandBatchDesc`

表达活动 batch：

- `band_begin / band_count`
- `panel_count / panel_size`
- active wave batch 大小
- 是否双缓冲

对 Step-2 的意义：

- 它把 `m` 维动态范围转成 system-visible 调度对象；
- 是后续 block-size-aware offload 策略的入口。

### 5.3 `DiagPolicy`

表达 diagonalization 策略约束：

- device-first 还是强制 CPU
- `max_device_diag_dim`
- 条件数阈值
- 是否允许 CPU fallback

对 Step-2 的意义：

- 把 `cdiaghg` 从“必须硬化”改成“受 policy 约束的 companion lane”；
- 后续 `diag_policy` 会是重要 system-level knob。

### 5.4 `ScfIterationRequest`

统一打包：

- resident set
- band batch
- diag policy
- density / potential / history object
- completion policy

对 Step-2 的意义：

- 它就是 `Host -> thin device runtime` 的主边界；
- 让 system DSE 不用直接修改上层软件语义。

### 5.5 `CompletionSummary`

统一返回：

- 执行状态
- `diag_path`
- resident reuse / spill
- DMA read/write
- host assist / device busy 计数
- exported wave handle / `EpisodeResult`

对 Step-2 的意义：

- 为后续 objective / constraint (`fallback_ratio`, `spill_ratio`, `bytes_moved_to_convergence`) 提供同一出口；
- 保证 DSE 比较不只看时间，还能看到系统代价。

---

## 6. 第一波数据所有权与搬运边界

### 6.1 Host DRAM 保留对象

- 全局 `rho`
- 全局 `Veff`
- mixing history
- 全局 convergence state
- host fallback diag 的输入输出

### 6.2 Device HBM / DDR 保留对象

- resident projector set
- support-grid metadata
- potential slice
- active wave batch
- reduced matrices
- temporary refresh/update objects

### 6.3 On-chip SRAM / BRAM / URAM 保留对象

- tile
- FIFO
- double buffer
- row-block window
- partial HS packets
- temporary reduction packets
- `P_next` 局部 slots

### 6.4 当前不建议长期片上保存的对象

- 全局 `rho`
- 全局 `Veff`
- 全局 SCF history

这一步的核心设计判断是：

> 第一波系统对象要把片上常驻资源优先留给 **projector/beta, panel tiles, partial HS, P_next companion state**，
> 而不是试图把完整 shell-level density/history 也搬进 chip。

---

## 7. Cluster 级角色与 Step-2 边界解释

当前 runnable model 和 cluster spec 已经给了足够清楚的角色分配：

- `Cluster A`: `h_psi / s_psi` operator sweep，时间主占比约 `68%`
- `Cluster B`: reduced build，约 `4%`
- `Cluster C`: hardware-first diag proxy，约 `23%`
- `Cluster D`: refresh / residual，约 `5%`

但 Step-2 不把这些 cluster 直接等价成 public API，而是做如下解释：

### 7.1 A/B/D 是第一波硬件主闭环

原因：

- A 承接主热点；
- B 让 operator path 真正闭合到 reduced-space；
- D 决定 inner-loop 是否继续，以及 `P_next` 是否回到 resident context。

### 7.2 C 是 policy-sensitive companion lane

原因：

- 原始软件侧 `cdiaghg` 不是主时间瓶颈；
- small-Si / Si8 / graphene 的 current trace-backed envelope 已经说明它可以是 hardware-first proxy，但不必作为第一波成功标准；
- 条件数 / `n_active` / buffer budget / crossover margin 都可能使它 fallback。

因此，Step-2 冻结口径是：

> 先把 A/B/D 做成可靠主闭环，把 C 作为受 `DiagPolicy` 约束的可切换 companion lane。

---

## 8. Step-2 对 Step-3 参数化的直接输入

完成 partition 冻结后，后续参数化应优先围绕这些边界展开：

### 8.1 system-level knobs

1. `offload_scope`
2. `resident_policy`
3. `partition_strategy`
4. `diag_policy`
5. `FFTUnit / ReductionUnit / DiagUnit` 是否独立

### 8.2 interface-sensitive knobs

1. `panel_bands`
2. `row_block_size`
3. `psi_panel_kib`
4. `projector_bank_kib`
5. `a_partial_fifo_kib`
6. `b_accum_buffer_kib`
7. `d_refresh_buffer_kib`
8. `d_pnext_slots_kib`
9. `fifo_ab_kib / fifo_bc_kib / fifo_cd_kib`

### 8.3 fallback-sensitive knobs

1. `max_device_diag_dim`
2. `allow_cpu_diag_fallback`
3. condition-estimate threshold
4. resident-fit threshold

---

## 9. 当前 Step-2 artifact 的作用边界

这份 partition 文档的作用是：

- 给 Step-3 parameterization 提供稳定的对象边界；
- 让 Step-4/5 的 system-level DSE 真正围绕 **接口 / resident / fallback / traffic** 展开；
- 避免系统探索退化成“只看 cluster label”或“只看某个孤立 kernel”。

它**不直接宣称**：

- 当前三层分工就是最终 RTL/ASIC 微结构；
- `Cluster C` 最终一定保留或一定硬化；
- 当前 proxy-level runnable model 已经足以形成 board-grounded 结论。

---

## 10. 一句话收口

当前 Step-2 的正式输入可以收成一句话：

> 这个系统的第一波 DSE 应以 **Host 负责 shell control、thin device runtime 负责 resident/DMA/fallback、hardware datapath 负责 `h_psi/s_psi + reduced build + refresh/residual` 主闭环，而 `cdiaghg` 保持 policy-sensitive companion lane** 的三层分工为基础，再围绕 interface、resident、spill、fallback 和 batch 尺度展开 system-level 探索。
