# QE 系统 DSE 前端输入：parameter stack v0

## 0. 定位

这份文档对应系统 DSE 的 **Step-3 输入 artifact**。

在 `Step-1` 已冻结 workload characterization，`Step-2` 已冻结 `Host / thin device runtime / hardware datapath` 分工之后，
这里把后续 DSE 的“可调旋钮”显式整理为一套分层 parameter stack：

1. 哪些参数属于 system-level；
2. 哪些参数属于 kernel-mapping；
3. 哪些参数属于 proxy / closure / evaluation control；
4. 当前 objective / constraint 应如何与这些参数对齐。

这份文档不重新创造新的参数族，而是把仓库里已经存在的：

- `qe_ic_system_level_dse_axes_v0.md`
- `qe_next_stage_dse_strategy_v0.md`
- `systemc_architecture_family_dse_result_schema_v0.json`
- `qe_fast_layer_proxy_assumption_set_v0.json`
- `docs/benchmarks/archive/reports/qe_step2_kernel_mapping_dse_report.md`
- `qe_kernel_mapping_dse_step2.py`
- `run_systemc_architecture_family_dse_sweep.py`
- `run_qe_next_stage_dse_phase.py`

统一读成一套可以直接驱动后续 system exploration 的 parameter hierarchy。

---

## 1. Step-3 冻结目标

当前阶段，不应把所有硬件细节都同时打开。

当前参数化的原则固定为：

> **先系统级，后细粒度硬件维度；先解释系统对象和数据边界，再解释更底层 lane / banking / clock 细节。**

因此 Step-3 的目标不是“列出所有可能参数”，而是：

- 给 Step-4/5 的低成本和中成本 DSE 指定**优先参数族**；
- 让后续 sweep / phase runner / kernel mapping DSE 使用同一套词汇；
- 避免把当前 still-proxy 的 runnable model误读成已经能支撑完整 RTL/P&R 参数搜索。

---

## 2. Parameter stack 总览

当前参数栈分 4 层：

1. **Workload / signature layer**
2. **System partition layer**
3. **Kernel mapping layer**
4. **Evaluation / evidence-control layer**

其中：

- Layer 1 和 Layer 2 决定“系统对象和边界怎么切”；
- Layer 3 决定“主热点 kernel 如何落到具体数据流 / tile / buffer”；
- Layer 4 决定“这些结果用哪种 fidelity、哪套假设、哪种证据等级输出”。

---

## 3. Layer 1 — Workload / signature layer

这一层不是做数值优化，而是决定设计空间评估时到底在对哪种 workload 说话。

### 3.1 当前冻结 workload roles

来自 `qe_next_stage_dse_strategy_v0.md` 与 `qe_device_oriented_workload_matrix_v0.md`：

- mainline cases:
  - `si4_pbe_uspp_small`
  - `graphene_pbe_uspp`
- accurate-layer anchor:
  - `si8_pbe_nc`
- canonical coverage:
  - `si8_pbe_uspp`
- nonblocking generalization:
  - `si4_pbe_uspp_small`
  - `graphene_pbe_uspp`
  - `graphene_pbe_paw`
  - `h2_tiny`

### 3.2 当前重要 workload descriptors

这一层后续应被显式保留的 workload descriptors 包括：

- `workload_id`
- `signature_id`
- `property_target`
- `pseudopotential_family`
- `solver_path_class`
- `workload_topology`
- `projector_pressure`
- `nonlocal_pressure`
- `generalized_ratio_bucket`
- `diag_dominance`
- `fft_grid_pressure`

### 3.3 Step-3 中它们的作用

这些不是“旁白元数据”，而是后续剪枝的第一层上下文。

例如：

- `solver_path_class = generalized_overlap` → 强制保留 `s_psi` / overlap-aware path
- `projector_pressure = high` → projector-bank / resident-policy 成为主轴
- `diag_dominance = low` → 不应把 `cdiaghg` 作为第一优先 accelerator 主核

---

## 4. Layer 2 — System partition layer

这一层是当前 system DSE 的最高优先级参数层。

### 4.1 当前开放 system-level axes

来自 `qe_ic_system_level_dse_axes_v0.md` 与 `systemc_architecture_family_dse_result_schema_v0.json`：

#### 4.1.1 Family
- `F1`
- `F2`
- `F3`

角色：
- `F1`: host-heavy / single-hotpath
- `F2`: balanced hybrid / multi-operator pipeline
- `F3`: device-heavy / full inner-loop offload

#### 4.1.2 `diag_policy`
- `cpu_only`
- `device_first_fallback`
- `aggressive_device`

#### 4.1.3 `offload_scope`
- `single_hotpath`
- `balanced`
- `device_heavy`

#### 4.1.4 `resident_policy`
- `fit_first`
- `spill_tolerant`

#### 4.1.5 `partition_strategy`
- `single_hotpath_partition`
- `operator_build_fused__diag__refresh`
- `operator__build__diag__refresh`
- `operator__build_diag_fused__refresh`
- `operator_build_fused__diag_refresh_fused`

### 4.2 当前推荐优先级

Step-3 明确建议先扫的 system-level knobs 顺序是：

1. `offload_scope`
2. `resident_policy`
3. `partition_strategy`
4. `diag_policy`
5. `family`

理由：

- 当前最强不确定性首先来自 **边界怎么切**，不是 PE 个数；
- `h_psi / s_psi` 与 `build / refresh` 是否耦合，会先改变系统最优结构；
- `cdiaghg` 是否硬化目前仍然是 policy-sensitive，而不是无条件主轴。

### 4.3 当前暂不打开的 system knobs

仍属于下一阶段：

- cluster 数量
- on-chip buffer 容量上界的全空间搜索
- DMA 通道数 / 档位
- module replication factor
- local scheduling micro-policy

---

## 5. Layer 3 — Kernel mapping layer

这一层当前主要服务 `h_psi / s_psi` 的 projector/GEMM 主链。

### 5.1 当前已存在的 kernel-mapping knobs

来自 `qe_kernel_mapping_dse_step2.py`：

#### Tile sizes
- `tile_npw`
- `tile_nkb`
- `tile_m`

当前候选生成逻辑默认扫描：
- `tile_npw`: `[128, 256, 512, min(1024, npw)]`
- `tile_nkb`: `[16, 32, 64, min(144, nkb)]`
- `tile_m`: `[4, 8, 16, min(32, m)]`

#### Loop ordering
6 种排列：
- `(npw, nkb, m)`
- `(npw, m, nkb)`
- `(nkb, npw, m)`
- `(nkb, m, npw)`
- `(m, npw, nkb)`
- `(m, nkb, npw)`

#### Dataflow
- `weight_stationary`
- `output_stationary`
- `row_stationary`

#### Buffer hierarchy
- `L1`
- `L2`
- `L3`

当前内建 buffer 候选为：
- small: `64KB / 512KB / 2MB`
- medium: `128KB / 1MB / 4MB`
- large: `256KB / 2MB / 8MB`

### 5.2 当前已有的 kernel-level先验

来自 `docs/benchmarks/archive/reports/qe_step2_kernel_mapping_dse_report.md`：

- `weight_stationary` 最优
- `beta resident, psi streaming` 最优
- 最优 loop 常落在 `(npw, m, nkb)`
- 小 tile 更高 utilization
- 大 tile 更高 arithmetic intensity

### 5.3 当前推荐的映射层优先级

对 `h_psi / s_psi`，推荐先扫：

1. `tile_m`
2. `tile_nkb`
3. `dataflow`
4. `loop_order`
5. `tile_npw`
6. `buffer hierarchy`

理由：

- `m` 直接决定是否值得 offload；
- `nkb` 影响 projector pressure；
- `dataflow` 决定 resident reuse 是否成立；
- `tile_npw` 更多决定规模伸缩，而不是首先决定边界语义。

### 5.4 block-size-aware 初始剪枝规则

当前可先冻结一条启发式规则：

- `m < 8`：默认不作为 accelerator 主收益区间
- `8 <= m <= 16`：作为第一波主探索区间
- `m > 16`：作为 compute-throughput 主区间

---

## 6. Layer 4 — Evaluation / evidence-control layer

这一层控制“同一个 design point 用什么方式被评估和发布”。

### 6.1 source kind

来自 result schema：

- `stub`
- `timed_functional_proxy`
- `trace_calibrated_proxy`
- `measured`
- `mixed`

### 6.2 assumption set

来自 `qe_fast_layer_proxy_assumption_set_v0.json`：

- `qe_next_stage_phase_v0`
- `pending_calibration_v0`（legacy alias；不作为当前默认值）

当前 active mainline 已经默认使用：
- `assumption_set_id = qe_next_stage_phase_v0`

### 6.3 correctness / tolerance controls

- `qe_tolerance_schema_id = qe_gold_numerical_tolerance_schema_v0`
- accurate-layer required checks:
  - `gold_pass`
  - `convergence_comparable_pass`
  - `final_total_energy_ry`
  - `final_converged`
  - `final_residual_threshold_reached`

### 6.4 fast-layer state machine

当前 phase strategy 冻结为：

- `reject`
- `explain-only`
- `promotion-eligible`

---

## 7. Objectives 与 constraints

### 7.1 当前 system-level 主目标

来自 `qe_next_stage_dse_strategy_v0.md`：

1. `time_to_convergence_s`
2. `energy_to_convergence_j`

### 7.2 当前显式约束 / 解释指标

- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

### 7.3 这些目标与参数层的对应关系

| 指标 | 最敏感的参数层 | 当前解释 |
| --- | --- | --- |
| `time_to_convergence_s` | system partition + kernel mapping | 端到端主排序目标 |
| `energy_to_convergence_j` | system partition + assumption set | 当前由 proxy assumption set 驱动 |
| `bytes_moved_to_convergence` | system partition + runtime interface | 判断是否被数据搬运拖垮 |
| `fallback_ratio` | `diag_policy` + `resident_policy` + workload traits | 判断硬件路径是否经常被 companion/host 接管 |
| `spill_ratio` | `resident_policy` + interface buffers | 判断 resident object 是否经常溢出 |

---

## 8. Parameter stack 的执行顺序建议

当前 Step-3 之后，建议按下面顺序推进 DSE：

### 8.1 先扫 Layer 2（系统级）

先比较：

- `offload_scope`
- `resident_policy`
- `partition_strategy`
- `diag_policy`

目的：

- 先确认系统对象与边界是否成立；
- 先找到哪类 family/policy 能把 `fallback_ratio / spill_ratio / bytes_moved` 压住。

### 8.2 再扫 Layer 3（kernel mapping）

在已经成立的 partition 上，再细化：

- `tile_npw`
- `tile_nkb`
- `tile_m`
- loop ordering
- dataflow
- buffer hierarchy

### 8.3 最后再打开 Layer 4 的更强证据控制

包括：

- from `timed_functional_proxy` 到更强 closure
- GPU annex / board closure
- adjudicator / release gates

---

## 9. 当前 Step-3 artifact 的作用边界

这份 parameter stack 的作用是：

- 把 repo 中已经存在的 knobs 收口成统一 vocabulary；
- 让 Step-4（evaluation tiers）和 Step-5（guided search）有共同输入；
- 避免不同脚本里使用不同的参数命名与优先级。

它**不直接宣称**：

- 当前所有枚举轴都必须全量搜索；
- kernel mapping 层和 system-level 层必须在同一次搜索里笛卡尔积展开；
- 现阶段就应该把所有低层 memory banking / clock / replication 因子都同时打开。

---

## 10. 一句话收口

当前 Step-3 的正式输入可以收成一句话：

> 这个系统的当前参数栈应先以 **workload/signature → system partition → kernel mapping → evidence-control** 的四层结构展开，并优先围绕 `offload_scope / resident_policy / partition_strategy / diag_policy` 与 `tile_npw / tile_nkb / tile_m / dataflow / buffer hierarchy` 两组参数族做分阶段探索，而不是一开始就把所有细粒度硬件参数全量打开。
