# QE 工程级实测手册（v0，2026-04-18）

## 0. 这份手册要解决什么问题

现在仓库里的：

- `time_to_convergence_s`
- `energy_to_convergence_j`
- `avg_system_power_proxy_w`

已经足够做 **DSE / 架构排序 / 瓶颈分析**，但其中功耗与能耗仍然是 **proxy**。

如果你想把它提升成：

- 可复核的 **工程级系统测试**
- 可进入 thesis / report 的 **实测 power-performance evidence**
- 可和真实 `CPU + GPU` / `CPU + FPGA` 做 end-to-end 对比的结果

那么你必须补的不是“更多解释”，而是**同一 accounting boundary 下的真实测量 artifact**。

这份手册直接告诉你：

1. **必须实际测哪些数据**
2. **这些数据该落到哪些文件**
3. **怎样验证它们已经不再只是 proxy**

本手册与以下现有合同直接对齐：

- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
- `tools/benchmarks/check_qe_phase1_artifact_contracts.py`
- `tools/benchmarks/init_qe_phase1_artifact_bundle.py`
- `tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py`
- `tools/benchmarks/assess_qe_phase1_evidence_closure.py`
- 若你还需要理解当前 proxy 指标是**怎么从模型输出一路算出来的**，请同时阅读：
  - `docs/benchmarks/qe_proxy_estimation_flow_and_worked_example_v0.md`
- 若你需要一页可以直接放进 PPT/周报的摘要，请同时阅读：
  - `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_proxy_estimation_onepage_summary_v0.md`

---

## 1. 从 proxy 到工程级，缺的到底是什么

### 1.1 当前 proxy 已经有什么

当前 SystemC/DSE 链已经能给你：

- 端到端估计时间：`time_to_convergence_s`
- 端到端估计能耗：`energy_to_convergence_j`
- 平均系统功耗 proxy：`avg_system_power_proxy_w`
- 分解账本：
  - `E_host_j`
  - `E_device_runtime_j`
  - `E_dma_j`
  - `E_hardware_datapath_j`
  - `E_idle_static_j`

### 1.2 它为什么还只是 proxy

因为这些量现在来自：

- simulator ref-cycle
- fast-layer power assumption set
- host/device/dma/static 的假设功率参数

而不是来自同一真实 run window 内的：

- **真实 wall-clock**
- **真实 whole-node power**
- **真实 device / DMA / fallback / spill counter**

### 1.3 一句话标准

> **只有当时间、功耗、正确性、数据搬运、fallback 行为都来自同一真实测量窗口，并按现有 artifact contract 落盘后，它才不再只是 proxy。**

---

## 2. 你必须实际测的最小数据面

下面这张表是最核心的内容。

| 类别 | 现在的 proxy 字段 | 工程级实测要补的真实量 | 最终落盘位置 |
| --- | --- | --- | --- |
| 端到端时间 | `time_to_convergence_s` | 同一 QE shell run 的真实 `start -> stop` wall time | `*.timing.json` / `board_metrics.json` |
| 正确性 | `gold_pass` / `convergence_comparable_pass` | 与同一 gold baseline 对比后的真实 compare 结果 | `*.correctness.json` / `board_compare.json` |
| 迭代收敛 | `scf_iterations_to_convergence` | 真实 QE stdout / wrapper 记录的 SCF 次数 | `*.convergence.json` / `board_metrics.json` |
| 数据搬运 | `bytes_moved_to_convergence` | 真实 DMA read/write bytes 与 closure | `board_metrics.json` 或 GPU row 对应统计文件 |
| fallback / spill | `fallback_count_to_convergence` / `fallback_ratio` / `spill_ratio` | 真实 host fallback 次数、spill 次数/比例 | `board_metrics.json` |
| 周期占比 | `device_busy_ref_cycles` / `dma_ref_cycles` / `host_assist_ref_cycles` | 真实 device / DMA / host-assist 计数器 | `board_metrics.json` |
| 总能耗 | `energy_to_convergence_j` | 同一测量窗口下的真实 whole-node energy integral | `*.power.json` / `board_power.json` |
| 平均功耗 | `avg_system_power_proxy_w` | 真实 `avg_whole_node_power_w` | `*.power.json` / `board_power.json` |
| 峰值功耗 | 无 | 真实 `peak_power_w` | `board_power.json` / GPU power artifact |
| 环境可比性 | assumption-set + notes | host / device / image / driver / runtime / qe rev | manifest files |

---

## 3. 如果你只测一部分，会发生什么

### 3.1 只测真实时间，不测真实功耗

那么：

- `time_to_convergence_s` 可以升级为真实测量
- 但 `energy_to_convergence_j` / `avg_system_power_proxy_w` 仍然只能算 proxy

### 3.2 只测 device power，不测 whole-node power

那么：

- 你可以做 device-level profiling
- 但 **不能**做 phase-1 fairness contract 要求的 engineering-grade 功耗结论

因为当前合同冻结的是：

- `power_boundary_id = whole_node_steady_state_single_cpu_single_accelerator_v0`

### 3.3 只测 kernel 时间，不测完整 QE shell 时间

那么：

- 你只能做 micro-benchmark / kernel study
- 不能替代 `time_to_convergence_s`

因为当前比较边界冻结的是：

- `accounting_boundary_id = scf_shell_convergence_scope_v1`

---

## 4. GPU 基线：必须实际测什么

## 4.1 每条 GPU row 最少要有 8 类 artifact

对于每个 `case_id × gpu_mode`，你至少要真实生成：

1. `stdout.txt`
2. `stderr.txt`
3. `timing.json`
4. `correctness.json`
5. `convergence.json`
6. `power.json`
7. `summary.md`
8. `cpu_gpu_baseline_manifest.json`

并保留：

- `algorithm_rewrite_manifest.json`

### 4.2 GPU row 最少必须实测的字段

#### A. `timing.json`

至少要真实写入：

- `time_to_convergence_s`
- 推荐附加：
  - `pwscf_wall_s`
  - `electrons_wall_s`
  - 分阶段 timing entries

#### B. `correctness.json`

至少要真实写入：

- `gold_pass`
- `convergence_comparable_pass`

推荐同时写：

- `final_total_energy_match`
- `residual_threshold_state_match`
- `converged_state_match`
- `final_total_energy_abs_err_ev`
- `final_total_energy_rel_err`
- `baseline_scf_iterations`
- `candidate_scf_iterations`

#### C. `convergence.json`

至少要真实写入：

- `convergence_comparable_pass`
- `scf_iterations_to_convergence`

#### D. `power.json`

这是把它从 proxy 升级成 engineering-grade 的关键。

至少要真实写入：

- `avg_whole_node_power_w`
- `energy_to_solution_j`

推荐附加：

- `peak_power_w`
- `sampling_period_ms`
- `window_start_utc`
- `window_stop_utc`
- `host_energy_j`
- `device_energy_j`
- `power_boundary_gap_note`

### 4.3 GPU row 最少必须冻结的 manifest 字段

`cpu_gpu_baseline_manifest.json` 里至少要冻结：

- `case_id`
- `gpu_mode`
- `host_id`
- `gpu_id`
- `qe_rev`
- `workload_group_id`
- `fairness_policy_id`
- `algorithm_rewrite_manifest_id`
- `qe_tolerance_schema_id`
- `accounting_boundary_id`
- `power_boundary_id`
- `gpu_mode_attempts`
- `shared_rewrite_closed`
- `host_platform_comparable`
- `rewrite_mode`
- `artifact_paths`
- `baseline_state`

### 4.4 GPU row 的工程级通过标准

某条 GPU row 只有在下列条件同时满足时，才能不再只是参考数据：

1. `gold_pass = true`
2. `convergence_comparable_pass = true`
3. `time_to_convergence_s` 来自完整 QE shell run
4. `avg_whole_node_power_w` / `energy_to_solution_j` 来自同一真实窗口
5. `shared_rewrite_closed = true`
6. `host_platform_comparable = true`，或者有清楚的 normalization note

---

## 5. FPGA / 板级路径：必须实际测什么

如果你要让 `CPU + FPGA` 也从 simulator proxy 走向工程级测试，那么 board bundle 至少要真实补四个 JSON：

- `board_manifest.json`
- `board_metrics.json`
- `board_power.json`
- `board_compare.json`

### 5.1 `board_manifest.json`

你必须真实填写：

- 板卡 identity：
  - `fpga_board_id`
  - `fpga_image_id`
  - `driver_rev`
  - `runtime_rev`
  - `qe_rev`
- 运行 join-key：
  - `workload_id`
  - `architecture_family`
  - `assumption_set_id`
  - `diag_policy`
  - `offload_scope`
  - `resident_policy`
  - `qe_tolerance_schema_id`
  - `accounting_boundary_id`
  - `fairness_policy_id`
  - `power_boundary_id`
  - `observability_contract_id`
  - `algorithm_rewrite_manifest_id`
- 计量边界：
  - `start_event`
  - `stop_event`
  - `ref_clock_hz`
  - `normalization_note`

### 5.2 `board_metrics.json`

这里是真正替换 runtime proxy 的核心文件。

至少要真实测：

- `timing.wall_time_s`
- `timing.scf_iterations_to_convergence`
- `data_movement.total_data_movement_kib`
- `data_movement.dma_read_kib`
- `data_movement.dma_write_kib`
- `cycles.device_busy_ref_cycles`
- `cycles.dma_ref_cycles`
- `cycles.host_assist_ref_cycles`
- `cycles.accounted_ref_cycles`
- `cycles.accounted_backpressure_ref_cycles`
- `policy_counters.cpu_fallbacks`
- `policy_counters.fallback_ratio`
- `policy_counters.resident_reuse_hits`
- `policy_counters.resident_reuse_ratio`
- `policy_counters.spill_events`
- `policy_counters.spill_ratio`

### 5.3 `board_power.json`

这是 board 工程级功耗闭环的关键文件。

至少要真实测：

- `total_energy.energy_to_convergence_j`
- `total_energy.avg_power_w`
- 推荐再测：
  - `total_energy.peak_power_w`

如果条件允许，最好再补 energy ledger：

- `E_host_j`
- `E_device_runtime_j`
- `E_dma_j`
- `E_hardware_datapath_j`
- `E_idle_static_j`
- `ledger_total_j`
- `ledger_closure_rel_err`

### 5.4 `board_compare.json`

这里必须真实写：

- `correctness.status`
- `correctness.gold_pass`
- `correctness.convergence_comparable_pass`
- `correctness.final_total_energy_abs_err_ev`
- `correctness.final_total_energy_rel_err`

如果你还要检验“projection 和 board 是否一致”，则再真实补：

- `projection_cross_check.realized_speedup_to_convergence`
- `projection_cross_check.realized_energy_to_convergence_j`
- `projection_cross_check.projection_consistency_status`

---

## 6. 建议的真实采样方式

下面不是冻结合同，而是 **工程级建议默认值**。

### 6.1 时间窗口

同一条 run 的时间窗口建议统一成：

- `start_event = qe_wrapper_launch`
- `stop_event = qe_wrapper_exit`

也就是完整 QE shell，不是单 kernel。

### 6.2 功耗采样

建议：

- `sampling_period_ms = 50 ~ 100 ms`
- 保留原始采样序列或至少保留积分结果与采样周期

优先级建议：

1. 外部 wall-socket / whole-node power meter
2. 同步 host + accelerator telemetry 求和
3. 仅 device telemetry + 明确 gap note（只能降级，不建议作为最终结论）

### 6.3 环境稳定性

每次正式 run 前至少要固定：

- host 频率策略
- accelerator 功耗/频率策略
- 散热状态
- warmup policy
- runtime / driver / image 版本

否则 engineering-grade 结果会漂。

---

## 7. 现场实际操作顺序

### Step 1：先生成 scaffold

#### GPU baseline

```bash
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  baseline \
  --out-dir "$GPU_RUN_DIR" \
  --workload-id si4_pbe_uspp_small \
  --gpu-mode practical \
  --run-tag 20260418-120000
```

#### FPGA board

```bash
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  board \
  --out-dir "$BOARD_RUN_DIR" \
  --workload-id si4_pbe_uspp_small \
  --architecture-family F1 \
  --assumption-set-id phase1_calibrated_v0 \
  --request-id REQ-001 \
  --scf-iteration 6 \
  --episode-id 2
```

### Step 2：实际跑机器并回填真实数据

你要回填的不是“结论”，而是前面列出的：

- timing
- correctness
- convergence
- power
- counters
- environment

### Step 3：先做结构检查

```bash
python3 tools/benchmarks/check_qe_phase1_artifact_contracts.py \
  --board-dir "$BOARD_RUN_DIR"
```

### Step 4：做 GPU readiness 判断

```bash
python3 tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py \
  --baseline-dir "$GPU_RUN_DIR"
```

你希望看到：

- `status = thesis_eligible`
或至少知道为什么还是：
- `reference_only`
- `deferred`

### Step 5：做 phase-1 closure 判断

```bash
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --gpu-baseline-dir "$GPU_RUN_DIR" \
  --board-dir "$BOARD_RUN_DIR" \
  --output-prefix "$OUT_DIR/closure_report"
```

你最终希望看到：

- `decisive_lane_closed = true`

---

## 8. 什么数据一到位，就可以说“不是 proxy 了”

## 8.1 对 GPU baseline

只要同一条 row 同时具备：

1. 真实 `time_to_convergence_s`
2. 真实 `avg_whole_node_power_w`
3. 真实 `energy_to_solution_j`
4. 真实 `gold_pass / convergence_comparable_pass`
5. 完整 manifest + rewrite policy + accounting boundary

那么这条 GPU row 就不再只是 proxy。

## 8.2 对 FPGA board

只要 board bundle 同时具备：

1. 真实 `board_metrics.json`
2. 真实 `board_power.json`
3. 真实 `board_compare.json`
4. 和 simulator / DSE 完整对齐的 join-key

那么这条 board run 就不再只是 simulator-side explain-only evidence。

## 8.3 对系统级结论

只有当：

- GPU row 不是 proxy
- board row 不是 proxy
- `assess_qe_phase1_evidence_closure.py` 显示 lane 已闭合

你才能把当前系统从：

> “proxy-based DSE / architecture exploration”

升级成：

> “engineering-grade measured system test”

---

## 9. 最小实测清单：你现场只看这一页也够

如果你只想记最短版本，就记下面这 12 项：

1. 完整 QE shell `start/stop` wall time
2. SCF iterations
3. gold correctness compare
4. convergence comparable pass
5. total DMA read bytes
6. total DMA write bytes
7. device busy cycles
8. host assist cycles / time
9. fallback count
10. spill count / spill ratio
11. whole-node average power
12. whole-node total energy

再加上：

13. host / device / image / driver / qe revision manifest

这套东西一旦齐了，当前系统就可以从 proxy 进入工程级测试。
