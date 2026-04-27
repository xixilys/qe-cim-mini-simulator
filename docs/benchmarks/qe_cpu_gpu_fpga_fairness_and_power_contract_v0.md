# QE-only `CPU + GPU` / `CPU + FPGA` fairness and power contract（v0，2026-04-13）

## 0. 目的与来源

本文对应 `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md` 里的：

- `M0.5`：冻结 whole-node power boundary 与 exact end-to-end accounting boundary；
- `M0.6`：冻结 `CPU + GPU` baseline policy，包括 shared algorithmic rewrites 与 measurement path；
- `WS2 / WS3`：为 pre-board GPU-competitive plausibility kill gate 提供可执行输入。

它不是新的结果报告，也不是新的比较计划；它的作用是把 **phase-1 QE-only thesis** 下，什么叫“可用于结论的 `CPU + GPU` baseline”、什么叫“lower whole-node power”、什么又只能算 deferred/proxy，全部提前钉死。

本文直接基于：

- `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_shell_comparison_plan_v0.md`
- `docs/benchmarks/qe_shell_level_comparison_metrics_contract_v0.md`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
- `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`
- `docs/architecture/qe_system_optimized_delta_20260413.md`
- `model/qe_band_solver_model/README.md`

---

## 1. phase-1 thesis 与 baseline 总边界

### 1.1 phase-1 thesis

phase 1 只讨论：

- `QE-only`
- `single CPU + single accelerator`
- 用户可见的 **end-to-end QE shell closure**
- 相同 correctness / tolerance contract
- workload-group 聚合评估

当前被批准的 hard thesis target 是：

> 在固定 workload group 上，`CPU + FPGA` 相对 `CPU + GPU`，实现 **>2x end-to-end time-to-solution**，且 **whole-node power 更低**。

这仍然是 **planning target**，不是当前仓库已经证成的事实。

### 1.2 当前状态约束

根据 `qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`：

- `CPU only` 已有真实 shell aggregate；
- `CPU + FPGA` 目前已有 runnable shell-contract proxy，但 `cdiaghg` 仍是 companion/proxy 计账；
- `CPU + GPU` 仍是 **deferred baseline**，当前机器与当前结果集里没有可直接纳入最终 shell-level 表格的 GPU 实测结果；
- 本机可见的 `Apple M4` GPU **不能**当成 `QE shell` GPU baseline 的替代值。

因此：

> **没有 real QE-facing `CPU + GPU` shell baseline，就不能宣称 phase-1 thesis 成立。**

---

## 2. phase-1 里什么叫 `CPU + GPU`

### 2.1 baseline 定义

phase 1 的 `CPU + GPU` 指：

- 同一类 `QE` 软件语义；
- 同一 workload-group；
- 同一 correctness / tolerance contract；
- 单机、单 host CPU、单 GPU accelerator；
- 由 host CPU 负责外层 SCF control / orchestration，GPU 负责可下沉的 kernels / stages / rewritten paths；
- 所有 host↔GPU launch / sync / transfer / layout-transform / fallback cost 全部计入。

它**不是**：

- 理论 GPU peak FLOPS；
- 某个孤立 GEMM/FFT micro-benchmark；
- 与 `QE shell` 无直接对应关系的通用 GPU capability；
- 只统计 device kernel time、不统计 host/runtime cost 的 vendor benchmark。

### 2.2 phase-1 的可接受 GPU baseline 形态

每一条 `CPU + GPU` baseline 结果都必须明确标注 `gpu_mode`：

1. **`strict_fp64`**
   - 尽量保持 `FP64` / 接近 software reference 的数学路径；
   - 优先服务“同精度公平比较”。

2. **`practical`**
   - 允许现实工程里会采用的 vendor-library / batching / mixed-precision-friendly route；
   - 前提是最终仍满足冻结后的 correctness / tolerance contract。

### 2.3 phase-1 的 decisive GPU baseline 规则

为避免“拿弱 GPU baseline 给 FPGA 让路”，phase 1 的 decisive `CPU + GPU` baseline 规则冻结为：

> 在同一 correctness / tolerance contract、同一 shared-rewrite policy 下，**所有已测且可接受的 GPU baseline 中最快的那一条**，才是 phase-1 的 decisive `CPU + GPU` baseline。

因此：

- 如果 `strict_fp64` 和 `practical` 都可测，主文必须同时报告两者，且 **kill gate / 终局 thesis** 以**更快**的那条为对手；
- 如果当前只能测到其中一种，必须显式标注另一种为 `deferred`，不能假装“GPU 就是一条抽象行”；
- 任何“只因为 GPU baseline 还没补齐，所以先拿较弱 GPU 模式当最终对手”的做法，均不允许。

### 2.4 host 平台约束

phase 1 的首选比较对象是：

- 同一类单机形态；
- 同级别 host CPU；
- 单 accelerator card / device；
- 相同 shell boundary 与 workload group。

如果由于设备可得性导致 host 平台不同，结果必须同时给出：

- `host_normalization_note`
- 关键 host 配置差异
- 为什么这条结果仍可进入“候选比较”而不是“decisive thesis comparison”

默认规则是：

> **host platform 不可比时，可以做参考，不可直接作为 decisive pass/fail 结果。**

---

## 3. shared algorithmic rewrite policy

这部分是本合同最关键的 fairness 条款。

### 3.1 总原则

如果某个 algorithmic rewrite：

- 不改变被冻结的 correctness / tolerance contract；
- 在数学语义上也适用于 `CPU + GPU`；
- 在工程上可以在 `CPU + GPU` baseline 上实现；

那么：

> **`CPU + GPU` baseline 有权使用它。**

换句话说，不能把“本来 GPU 也能享受的算法收益”只记到 `CPU + FPGA` 头上。

### 3.2 rewrite 分类

所有 rewrite 必须进入统一 manifest，并至少分为三类：

| class | 含义 | 对 GPU 的处理规则 |
| --- | --- | --- |
| `shared_semantic` | 改写了算法/数据流，但不依赖 FPGA-only architectural state | GPU baseline **必须允许**采用 |
| `shared_engineering` | 纯工程性重排、layout、batching、runtime scheduling | GPU baseline **必须允许**采用，只要能实现 |
| `fpga_specific_arch` | 依赖 resident on-chip object、device-private schedule、FPGA-only dataflow contract 的改写 | 可保留为 FPGA-only，但必须披露并做 ablation |

### 3.3 每个 rewrite 必报字段

每个 rewrite 至少记录：

- `rewrite_id`
- `rewrite_class`
- `description`
- `changes_algorithm_semantics`（yes/no）
- `gpu_applicable`（yes/no/unclear）
- `gpu_enabled_in_baseline`（yes/no）
- `fpga_required_arch_feature`
- `correctness_contract_impact`
- `evidence_note`

### 3.4 不允许的做法

以下做法一律视为 fairness 违规：

1. 明知 rewrite 可帮助 GPU，但故意不让 GPU baseline 使用；
2. 把 GPU 无法实现的 FPGA-only resident/dataflow trick，和共享算法收益混写成一个“大改写”；
3. 不记录 rewrite applicability，就直接宣称 `CPU + FPGA` 赢过 `CPU + GPU`。

---

## 4. whole-node power boundary

### 4.1 统计对象

phase 1 的 power boundary 冻结为 **whole-node steady-state boundary**。对每个 baseline，至少应覆盖：

- host CPU package power
- host DRAM / system memory power（若可测）
- accelerator device / board power
  - GPU board + HBM/GDDR
  - FPGA board + board DDR/HBM / companion-side memory
- 为 accelerator path 专用且可归属的 link/interface power
- 测量窗口内的 wait / sync / idle power

### 4.2 推荐测量路径

优先级如下：

1. **同一类外部 node-level power meter / wall-socket measurement**
2. 同步采集的 host + device sensor sum
3. 明确披露缺口的 power proxy

若使用第 2 或第 3 类路径，必须额外给出：

- `power_boundary_gap_note`
- 哪些项缺测
- 缺测项是否可能系统性偏向某一 baseline

### 4.3 计入与不计入

**必须计入：**

- 完整 measured interval 内的 host/device/link power
- runtime wait / synchronization / fallback 期间的功耗
- 必要的数据搬运与 layout transform 期间的功耗

**不计入：**

- FPGA bitstream generation
- synthesis / P&R
- offline trace preprocessing
- one-time software build / library compile
- 与被测节点无关的开发机功耗

### 4.4 power claim 的表达规则

phase 1 既然把“lower power”写成 thesis 条件，就必须同时报：

- `avg_whole_node_power_w`
- `energy_to_solution_j`

其中：

- **主合同字段**仍然是 `avg_whole_node_power_w`；
- `energy_to_solution_j` 作为强制辅助字段，用来解释“更快但平均功耗更高”或“平均功耗更低但时间更长”的情况。

如果只报 energy 不报 power，或只报 device power 不报 whole-node power，都不能支持主 thesis。

---

## 5. exact end-to-end accounting boundary

### 5.1 主 timing boundary

phase 1 的 decisive end-to-end timing boundary 冻结为：

> 从目标 workload 进入**第一轮被计入的 SCF shell iteration** 的 `rho -> Veff` 开始，
> 到最终收敛 iteration 完成、`CompletionSummary` 返回 host 并结束本次 measured QE shell closure 为止。

这条边界必须覆盖：

- `rho -> Veff`
- `while bands not converged { h_psi, s_psi, build H_sub / S_sub, cdiaghg, refresh / residual -> P_next }`
- `psi -> rho_out`
- `mix_rho / convergence gate`
- shell-visible host/runtime/orchestrator/device completion overhead

### 5.2 必须计入的时间项

- host orchestration
- host↔accelerator transfer
- device launch / dispatch
- synchronization / completion wait
- layout transform / reformat
- spill / fallback / companion-solver path
- runtime-managed resident preload if it occurs inside the measured run

### 5.3 不计入的时间项

- offline trace capture / preprocessing
- compilation / bitstream generation
- one-time environment setup not belonging to a normal QE run

如果使用 warm-up run，必须满足两条：

1. 对所有 baseline 对称执行；
2. 正式表格里显式写明 `warmup_policy`。

### 5.4 不可接受的替代值

以下都**不能**当成 decisive end-to-end result：

- 只统计 kernel elapsed time
- 只统计 `c_bands`、不统计 shell closure
- analytical lower bound
- contract-layer ref-cycles / proxy cycles
- operator micro-bench 推导值

这些都只能作为解释性或前置 plausibility 数据。

---

## 6. measured vs deferred baseline status（phase 1 当前冻结）

### 6.1 measured / deferred 的定义

- **measured**：真实 `QE`-facing shell-level run，在冻结 boundary 内拿到的时间/功耗结果；
- **proxy**：可支持 contract alignment / traffic / stall / plausibility，但不能直接当 thesis result；
- **deferred**：总合同里必须存在，但当前尚未产生真实可判定结果。

### 6.2 当前状态表

| baseline item | 当前状态 | 能支持什么 | 不能支持什么 |
| --- | --- | --- | --- |
| `CPU only` QE shell aggregate（5 个 case） | `measured` | 真实 CPU shell reference、Amdahl envelope、sanity check | 不能替代 GPU baseline |
| runnable `CPU + FPGA` shell totals（companion `cdiaghg` proxy） | `proxy` | shell contract / traffic / stall / accounting 对齐 | 不能当成硬件 `CPU + FPGA` decisive result |
| real `CPU + GPU` QE shell baseline | `deferred` | 当前不能支持任何 pass/fail 结论 | 缺失即阻塞 CPU+GPU 胜负宣称 |
| real `CPU + GPU` whole-node power | `deferred` | 当前不能支持 lower-power 结论 | 缺失即阻塞 power claim |
| board-validated `CPU + FPGA` shell time | `deferred` | 当前不能支持 decisive win | 缺失即阻塞 thesis closure |
| board-validated `CPU + FPGA` whole-node power | `deferred` | 当前不能支持 lower-power 结论 | 缺失即阻塞 power claim |

### 6.3 明确禁止的 substitute

以下对象一律不能替代 `CPU + GPU` shell baseline：

- `Apple M4` 或其他本机 GPU 的通用 capability
- non-QE GPU micro-benchmark
- theoretical GPU peak
- 来自不同 correctness/tolerance contract 的旧数据
- 未声明 `gpu_mode` 的抽象“GPU”一行

### 6.4 CPU + GPU baseline acquisition checklist

从本版开始，`CPU + GPU` baseline 不是“以后补一行结果”，而是一个必须被显式执行并留痕的 acquisition path。

#### 6.4.1 acquisition 顺序

1. **case freeze**
   - 只允许使用 `qe_fpga_workload_group_and_correctness_contract_v0.md` 中已冻结的 roster；
2. **contract freeze**
   - 同一个 `qe_tolerance_schema_id`
   - 同一个 `accounting_boundary_id`
   - 同一个 `power_boundary_id`
   - 同一个 `fairness_policy_id`
3. **strict-fp64 baseline run**
   - 先尝试生成 `strict_fp64` GPU row；
4. **practical baseline run**
   - 再尝试生成 `practical` GPU row；
5. **decisive baseline selection**
   - 两条都存在时，选更快者作为 decisive `CPU + GPU` baseline；
6. **whole-node power run**
   - 对 decisive baseline 获取 matching 的 whole-node power / energy；
7. **artifact freeze**
   - 没有完整 artifact bundle 的 GPU row 只能算 `reference`，不能算 decisive。

#### 6.4.2 每条 GPU baseline 必须产出的 artifact

至少应存在：

- `gpu_run_manifest.json`
- `gpu_metrics.json`
- `gpu_power.json`
- `gpu_stdout.out`
- `gpu_correctness_compare.json`

并且这些 artifact 必须显式记录：

- `gpu_mode`
- `workload_group_id`
- `algorithm_rewrite_manifest_id`
- `fairness_policy_id`
- `qe_tolerance_schema_id`
- `accounting_boundary_id`
- `power_boundary_id`

#### 6.4.3 decisive readiness checklist

GPU baseline 只有同时满足下面条件，才可进入 decisive thesis table：

- [ ] 已完成 `strict_fp64` 尝试
- [ ] 已完成 `practical` 尝试，或说明为什么 phase 1 不适用
- [ ] correctness / tolerance compare 通过
- [ ] shell boundary 与 power boundary 都已冻结
- [ ] whole-node power 已测
- [ ] shared algorithmic rewrite policy 已闭合
- [ ] artifact bundle 齐全

若上述任一项不满足：

> GPU baseline 只能标记为 `deferred` 或 `reference-only`，不能参与 phase-1 decisive pass/fail。

---

## 7. pre-board kill-gate 所需输入（GPU-competitive plausibility）

在进入 deep FPGA bring-up 之前，必须先收齐下面这些输入；否则只能继续做方法学/debug，不得继续宣称“有望 decisively beat CPU+GPU”。

### 7.1 required inputs

| input | 最低要求 | 主要来源 |
| --- | --- | --- |
| `workload_group_id` | 冻结的 QE workload group，含 case list 与权重/聚合规则 | `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md` |
| `qe_tolerance_schema_id` | 冻结 correctness / tolerance contract | `qe_gold_*` contract/schema |
| `accounting_boundary_id` | 冻结的 shell timing boundary | 本文档 + shell metrics contract |
| `power_boundary_id` | 冻结的 whole-node power boundary | 本文档 |
| `algorithm_rewrite_manifest_id` | 每个 rewrite 的 shared/fpga-specific 分类与 GPU applicability | rewrite manifest |
| `optimized_delta_id` | 当前 fairness / baseline 讨论绑定的是哪一版 system-level optimized delta | `docs/architecture/qe_system_optimized_delta_20260413.md` |
| `cpu_gpu_baseline_mode_set` | 已测 `strict_fp64` / `practical` 中哪些可用 | GPU baseline run log |
| `cpu_gpu_shell_time_measured` | workload-group 上的真实 `CPU + GPU` shell time | GPU shell run |
| `cpu_gpu_whole_node_power_measured` | workload-group 上的真实 `CPU + GPU` average power / energy | GPU power run |
| `candidate_family_id` | 只允许 `F1` / `F2` 进入 primary decision-grade kill gate；`F3` 仅可作条件候选 | DSE result |
| `candidate_assumption_set_id` | 选定 design point 的 assumption set | DSE result |
| `cpu_fpga_shell_time_predicted` | 同一 boundary、同一 rewrite policy 下的 predicted `CPU + FPGA` shell time | simulator / DSE |
| `cpu_fpga_whole_node_power_predicted` | 同一 boundary 下的 predicted `CPU + FPGA` power/energy | simulator / DSE |
| `observability_map_id` | simulator field ↔ board measurable source mapping 已冻结 | `docs/benchmarks/qe_simulator_board_observability_contract_v0.md` |
| `ranking_stability_status` | `F1/F2` ranking 是否稳定 | WS2 ranking pass |
| `fairness_policy_id` | 冻结 shared-rewrite / baseline 公平性合同版本 | DSE / baseline metadata |

### 7.2 kill-gate 决策规则

pre-board GPU-competitive plausibility 只有在以下条件同时成立时才算 `pass`：

1. 上表输入全部存在，不允许拿 `deferred` / `proxy` 填 decisive 字段；
2. `CPU + GPU` baseline 已按 frozen correctness / tolerance contract、shared-rewrite policy、power boundary 实测；
3. 至少一个 `F1` 或 `F2` candidate 在 **允许 GPU 使用全部 shared rewrites 之后**，仍然显示：
   - projected end-to-end shell speedup `> 2.0x`
   - projected `avg_whole_node_power_w` 更低
4. 对应 candidate 的 `ranking_stability_status = pass`；
5. `observability_map_id` 已冻结，意味着后续 board bring-up 可真正验证这些 claims。

若上述任一条件失败，则：

> **不得把 deep FPGA bring-up 描述为“朝 decisively beat CPU+GPU 的必经步骤”；它只能作为方法学、架构可实现性或 calibration 工作继续。**

### 7.3 当前推荐的 pre-board gate 输出字段

为了避免 gate 只停留在 prose，phase-1 推荐至少导出以下字段：

- `gpu_baseline_ready = yes/no`
- `gpu_mode_set_measured = {strict_fp64, practical, ...}`
- `gpu_decisive_mode = <mode or deferred>`
- `gpu_correctness_contract_pass = yes/no`
- `gpu_power_boundary_closed = yes/no`
- `gpu_shared_rewrite_closed = yes/no`
- `gpu_competitive_plausibility = pass/fail`
- `gpu_competitive_plausibility_reason`

---

## 8. phase-1 必报 metadata 字段

为避免后续表格和 JSON 漂移，所有 `CPU + GPU` / `CPU + FPGA` 结果至少带上：

- `baseline_id`
- `case_id`
- `workload_group_id`
- `gpu_mode`（for GPU rows）
- `fairness_policy_id`
- `algorithm_rewrite_manifest_id`
- `qe_tolerance_schema_id`
- `accounting_boundary_id`
- `power_boundary_id`
- `proxy_type`（若不是 measured）
- `host_normalization_note`
- `warmup_policy`

没有这些字段的结果，可以进草稿，不可以进 decisive thesis table。

---

## 9. 冻结结论

这份合同冻结后的核心结论只有五条：

1. phase 1 的 decisive 对手不是抽象“GPU”，而是**同 correctness / tolerance、同 shared-rewrite policy、同 shell boundary 下最快的已测 `CPU + GPU` baseline**；
2. 任何对 GPU 也适用的 algorithmic rewrite，都必须允许 GPU baseline 使用；
3. power 比较必须是 **whole-node boundary**，不能只报 device power；
4. 当前 `CPU + GPU` 仍是 **deferred baseline**，所以今天还不能用仓库现有结果宣称 `CPU + FPGA` 赢过 `CPU + GPU`；
5. 在 real GPU shell baseline、real whole-node GPU power、以及与之对齐的 FPGA board evidence 产生之前，所有“GPU-competitive”表述都只能是 **plausibility / planning language**，不能写成已验证结论。
