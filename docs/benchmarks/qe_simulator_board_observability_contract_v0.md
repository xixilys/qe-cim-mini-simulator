# QE simulator ↔ board observability contract v0

## 1. Purpose

This document freezes the **simulator-to-board observability contract** required by the approved QE-only CPU+FPGA thesis plan in:

- `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`
- `model/qe_band_solver_model/README.md`
- `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`

The goal is not to restate the whole thesis. The goal is to define **which simulator outputs must line up with which board-measurable sources** before FPGA evidence can be used to support:

1. simulator/DSE ranking trust;
2. architecture-family candidate selection (`F1/F2` first, `F3` conditional);
3. end-to-end QE `CPU+FPGA` performance claims;
4. whole-node power claims; and
5. same-correctness/tolerance claims.

## 2. Scope and phase-1 assumptions

This contract is scoped to **phase 1** only:

- `QE` only;
- single `CPU + FPGA` node;
- public control contract frozen at the README-visible objects:
  - `ResidentSetDesc`
  - `BandBatchDesc`
  - `ScfIterationRequest`
  - `DiagPolicy`
  - `CompletionSummary`
- internal `descriptor -> replay/body -> LCW` lowering remains internal.

Current repo reality that affects the contract:

- the promoted runnable model is **host-managed** and **QE shell-first**;
- `cdiaghg` still may appear as **CPU/companion fallback/proxy** in early milestones;
- `CPU+GPU` shell-level baseline is still deferred in the current status note, so this contract does **not** replace the required later fairness/baseline freeze;
- `F1/F2` are decision-grade first-pass families, while `F3` remains conditional until the heavier device path is better grounded.

## 2.1 Machine-readable surfaces

本文不仅对应 prose contract，也直接对应以下 machine-readable / validator surfaces：

- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- `docs/benchmarks/qe_algorithm_rewrite_manifest_template_v0.json`
- `docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json`
- `docs/benchmarks/qe_fpga_board_manifest_template_v0.json`
- `docs/benchmarks/qe_fpga_board_metrics_template_v0.json`
- `docs/benchmarks/qe_fpga_board_power_template_v0.json`
- `docs/benchmarks/qe_fpga_board_compare_template_v0.json`
- `tools/benchmarks/init_qe_phase1_artifact_bundle.py`
- `tools/benchmarks/check_qe_phase1_artifact_contracts.py`
- `tools/benchmarks/compare_qe_gold_correctness.py`

phase-1 的执行要求是：进入 board calibration / ranking review 的 simulator row、board run、baseline manifest，必须都能落到这些 schema/template/validator 所使用的字段命名上，而不是只在 Markdown 里口头对齐。

## 3. Required join-key contract

Every simulator row, DSE row, and board run used for comparison must carry the same identity tuple:

- `workload_id`
- `workload_group_id`
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
- `algorithm_contract_deviation`
- run-local iteration identifiers:
  - `request_id`
  - `scf_iteration`
  - `episode_id` when applicable

If the join-key tuple does not match exactly, the sample is **not comparison-eligible**.

## 4. Formula shorthand

To keep the main table compact, use:

- `rel_err(sim, board) = |sim - board| / max(|board|, 1e-12)`
- `abs_gap(sim, board) = |sim - board|`
- `ratio_gap(sim, board) = |sim_ratio - board_ratio|`
- `exact_match = identical value / string / boolean`

## 5. Thesis-claim IDs

- `CL1` — simulator/DSE ranking is decision-grade enough to choose a board candidate
- `CL2` — selected `F1/F2` board candidate is architecturally realizable
- `CL3` — `CPU+FPGA` beats `CPU+GPU` on end-to-end QE time-to-solution
- `CL4` — `CPU+FPGA` uses lower whole-node energy / power than `CPU+GPU`
- `CL5` — resident/offload/fallback policy effects remain attributable rather than anecdotal
- `CL6` — board run preserves the same correctness/tolerance contract as QE gold

## 6. Observability table

| Obs ID | Simulator field(s) / origin | Expected board-measurable source | Comparison formula | Provisional acceptable error-band placeholder | Claim dependency | Notes |
|---|---|---|---|---|---|---|
| `OBS-00` | DSE row identity fields: `workload_id`, `family`, `diag_policy`, `offload_scope`, `resident_policy`, `assumption_set_id`, `algorithm_contract_deviation`, `qe_tolerance_schema_id`, `accounting_boundary_id` | Board run manifest + command log + env snapshot + board metrics header | `exact_match` | `OBS_EXACT` | `CL1` `CL2` `CL3` `CL4` `CL5` `CL6` | No claim is admissible if the board run drifts from the frozen fairness/control contract. |
| `OBS-01` | `timing.wall_time_s` from `QEBS_RESULT_JSON`; DSE `primary_metrics.time_to_convergence_s` | Host-side board wrapper timestamps around the complete QE run; QE stdout `PWSCF` / `electrons` totals as sanity anchors | `rel_err(sim_wall, board_wall)` | `OBS_TBD_E2E_TIME_REL` | `CL1` `CL3` | Authoritative boundary is the **same whole QE run**, not a kernel-only slice. |
| `OBS-02` | `SCFRunReport.iterations.size()`; DSE `primary_metrics.scf_iterations_to_convergence`; correctness `candidate_scf_iterations` | QE stdout convergence log from the board run; board summary JSON | `abs_gap(sim_iters, board_iters)` | `OBS_TBD_SCF_ITER_ABS` | `CL3` `CL6` | Default expectation should be `0`, unless the frozen correctness contract explicitly allows different iteration counts. |
| `OBS-03` | DSE correctness fields: `gold_pass`, `final_total_energy_match`, `residual_threshold_state_match`, `converged_state_match`, `final_total_energy_abs_err_ev`, `final_total_energy_rel_err` | Board candidate JSON rechecked with `compare_qe_gold_correctness.py` against the same QE gold baseline | booleans: `exact_match`; energy-gap fields: `abs_gap` / `rel_err` | `OBS_EXACT` for booleans; `OBS_TBD_GOLD_ENERGY_ABS_EV`; `OBS_TBD_GOLD_ENERGY_REL` | `CL3` `CL6` | This row guards the thesis phrase “same correctness/tolerance contract.” |
| `OBS-04` | `metrics.total_data_movement_kib`, `metrics.dma_read_kib`, `metrics.dma_write_kib`; DSE `primary_metrics.bytes_moved_to_convergence` | FPGA DMA-engine byte counters; host driver/accounting bytes; optional interconnect trace | `rel_err(sim_bytes, board_bytes)` and ledger consistency `abs_gap(board_total, board_read + board_write)` | `OBS_TBD_DMA_BYTES_REL`; `OBS_TBD_DMA_LEDGER_ABS_KIB` | `CL1` `CL4` `CL5` | Must be measured at the same accounting boundary used for the power comparison. |
| `OBS-05` | `metrics.device_busy_ref_cycles`; per-iteration `device_busy_ref_cycles`; DSE `secondary_metrics.device_busy_ref_cycles` | FPGA cycle counter gated by device-active / datapath-active signal | `rel_err(sim_busy_cycles, board_busy_cycles)` after frozen ref-cycle normalization | `OBS_TBD_DEVICE_BUSY_REL` | `CL1` `CL2` `CL5` | Needed to show the selected family is realizable for the expected duty cycle, not only functionally runnable. |
| `OBS-06` | `metrics.dma_ref_cycles`; DSE `secondary_metrics.dma_ref_cycles` | DMA-engine cycle counter or timestamp delta from first DMA submit to last DMA completion | `rel_err(sim_dma_cycles, board_dma_cycles)` | `OBS_TBD_DMA_CYCLE_REL` | `CL1` `CL2` `CL5` | This row is especially important because the plan explicitly lets simulator/DSE trade off transport delay against compute delay. |
| `OBS-07` | `metrics.host_assist_ref_cycles`; per-iteration `host_assist_ref_cycles`; DSE `secondary_metrics.host_assist_ref_cycles` | Host instrumentation around diag assist / fallback service on the board path, converted to the same ref-cycle unit | `rel_err(sim_host_assist, board_host_assist)` | `OBS_TBD_HOST_ASSIST_REL` | `CL1` `CL3` `CL5` | Particularly important while `cdiaghg` may still remain CPU/companion-backed in early milestones. |
| `OBS-08` | `metrics.cpu_fallbacks`; per-iteration `cpu_diag_fallback`; DSE `primary_metrics.fallback_count_to_convergence` and `secondary_metrics.fallback_ratio` | Board runtime fallback CSR/log counter; host diag service invocation count | count: `abs_gap`; ratio: `ratio_gap` | `OBS_TBD_FALLBACK_COUNT_ABS`; `OBS_TBD_FALLBACK_RATIO_ABS` | `CL1` `CL2` `CL5` | A required attribution row for `F1/F2`; if fallback dominates, the board result cannot be reported as device-heavy success. |
| `OBS-09` | `metrics.resident_reuse_hits`; per-iteration `resident_reused`; DSE `secondary_metrics.resident_reuse_hits` | FPGA runtime resident-cache hit counter keyed by `resident_set_id` / generation | hits: `abs_gap`; ratio form when aggregated: `ratio_gap` | `OBS_TBD_RESIDENT_HITS_ABS`; `OBS_TBD_RESIDENT_RATIO_ABS` | `CL1` `CL2` `CL5` | This row is the direct observability hook for the repo’s resident-policy story. |
| `OBS-10` | per-iteration `spill_active`; DSE `secondary_metrics.spill_ratio` | Board spill / eviction event counter + spill-byte log | `ratio_gap(sim_spill_ratio, board_spill_ratio)` | `OBS_TBD_SPILL_RATIO_ABS` | `CL1` `CL2` `CL5` | Important when comparing `fit_first` vs `spill_tolerant` policies and when judging whether `F3` is still only exploratory. |
| `OBS-11` | `ShellIterationSummary.accounted_ref_cycles`, `accounted_backpressure_ref_cycles`; `SCFRunReport.total_ref_cycles`, `total_backpressure_ref_cycles` | Board-side iteration timeline plus stall/backpressure counters in the device runtime / queues | `rel_err` on totals; `ratio_gap` on backpressure fraction | `OBS_TBD_SHELL_CYCLE_REL`; `OBS_TBD_BACKPRESSURE_RATIO_ABS` | `CL1` `CL2` `CL5` | The current shell-status doc already reports shell `ref_cycles` / `bp_ref_cycles`; board evidence must preserve that same accounting vocabulary. |
| `OBS-12` | DSE `primary_metrics.energy_to_convergence_j` | Whole-node energy integral over the board run: host package telemetry + FPGA board telemetry + frozen idle accounting policy | `rel_err(sim_total_energy, board_total_energy)` | `OBS_TBD_TOTAL_ENERGY_REL` | `CL1` `CL4` | This is the blocking row for any “lower power / lower energy” thesis claim. |
| `OBS-13` | DSE `energy_ledger.E_host_j`, `E_device_runtime_j`, `E_dma_j`, `E_hardware_datapath_j`, `E_idle_static_j` | Board energy bundle: host energy counter, board rails grouped by runtime/datapath when available, plus explicit idle/static estimate | component-wise `rel_err` where measurable; always require ledger closure `rel_err(sum(ledger), board_total_energy)` | `OBS_TBD_LEDGER_COMPONENT_REL`; `OBS_TBD_LEDGER_CLOSURE_REL` | `CL1` `CL4` `CL5` | If component rails are not separable on the board, ledger closure still must hold and the unresolved split must be reported as a confidence downgrade. |
| `OBS-14` | DSE `projection.speedup_to_convergence_range`, `projection.energy_to_convergence_range_j`, `projection.confidence`, `projection.ranking_grade_ready` | Board-measured realized speedup/energy under the same workload group and contract | realized point must lie inside or explainably near the projected range: `board ∈ [lower - δ, upper + δ]` | `OBS_TBD_RANGE_MARGIN`; `OBS_TBD_CONFIDENCE_POLICY` | `CL1` `CL3` `CL4` | This row prevents simulator/DSE from being used only as storytelling after candidate selection. |

## 7. Phase-1 provisional numeric thresholds

下面这些阈值从本版开始不再保留占位符，而是冻结成 **phase-1 provisional thresholds**。

这些值的含义是：

- 它们已经足够支持 phase-1 的 DSE / board calibration / pre-board kill gate；
- 它们**不是**最终 ASIC 级或论文 camera-ready 必然不变的数值；
- 如果后续真实 board 数据证明这些阈值过松或过紧，应通过文档 revision 升级，而不是在表格里临时解释。

| placeholder | phase-1 provisional threshold | 解释 |
| --- | --- | --- |
| `OBS_EXACT` | `exact_match` | 身份字段、布尔 gate 和 contract id 必须完全一致。 |
| `OBS_TBD_E2E_TIME_REL` | `<= 0.15` | end-to-end shell total time 的 simulator↔board 相对误差上限。 |
| `OBS_TBD_SCF_ITER_ABS` | `= 0` | 默认要求 `scf_iterations_to_convergence` 与 board 完全一致。 |
| `OBS_TBD_GOLD_ENERGY_ABS_EV` | `<= 1.3606e-7 eV` | 直接继承 `1e-8 Ry` 的现有 QE gold 绝对容差。 |
| `OBS_TBD_GOLD_ENERGY_REL` | `<= 1e-10` | 直接继承现有 QE gold 相对容差。 |
| `OBS_TBD_DMA_BYTES_REL` | `<= 0.10` | 总 DMA / transfer bytes 相对误差。 |
| `OBS_TBD_DMA_LEDGER_ABS_KIB` | `<= 4.0 KiB` | board 侧 total vs read+write ledger closure 误差。 |
| `OBS_TBD_DEVICE_BUSY_REL` | `<= 0.20` | 设备活跃 ref-cycle 相对误差。 |
| `OBS_TBD_DMA_CYCLE_REL` | `<= 0.20` | DMA ref-cycle 相对误差。 |
| `OBS_TBD_HOST_ASSIST_REL` | `<= 0.15` | host assist / companion service 相对误差。 |
| `OBS_TBD_FALLBACK_COUNT_ABS` | `= 0` | fallback 次数必须精确一致。 |
| `OBS_TBD_FALLBACK_RATIO_ABS` | `<= 0.02` | fallback ratio 允许极小差异，但不能改变 family judgement。 |
| `OBS_TBD_RESIDENT_HITS_ABS` | `<= 1` | resident reuse hit 次数最多允许 1 次绝对偏差。 |
| `OBS_TBD_RESIDENT_RATIO_ABS` | `<= 0.05` | resident reuse ratio 误差上限。 |
| `OBS_TBD_SPILL_RATIO_ABS` | `<= 0.02` | spill ratio 误差上限。 |
| `OBS_TBD_SHELL_CYCLE_REL` | `<= 0.20` | shell `ref_cycles` 总量相对误差。 |
| `OBS_TBD_BACKPRESSURE_RATIO_ABS` | `<= 0.10` | backpressure fraction 绝对误差上限。 |
| `OBS_TBD_TOTAL_ENERGY_REL` | `<= 0.15` | whole-node total energy 相对误差。 |
| `OBS_TBD_LEDGER_COMPONENT_REL` | `<= 0.25` | 单个 energy ledger 分量误差上限。 |
| `OBS_TBD_LEDGER_CLOSURE_REL` | `<= 0.10` | energy ledger 求和与 total energy 的闭合误差。 |
| `OBS_TBD_RANGE_MARGIN` | `<= 0.10` | board 实测值允许落在 projection range 外的相对 margin。 |
| `OBS_TBD_CONFIDENCE_POLICY` | `ranking_grade_ready = true` 且 `projection_grade_ready = true` | 若未满足，projection 只能用于内部筛选，不能用于对外 claim。 |

### 7.1 使用规则

1. `OBS-00`、`OBS-03`、`OBS-12` 这类 thesis-critical rows 不能用更松的临时阈值替代；
2. 任何 row 若因 board 可观测性不足无法满足上表，应标记为 `confidence downgrade`，而不是默认通过；
3. 若 board 数据反复稳定优于上述阈值，可在下一版收紧；若长期无法满足，则必须降级相关 thesis claim。

## 8. Ranking-stability pass/fail rule

本节把 phase-1 必需的 `ranking_stability_status` 从口头要求冻结成可执行规则。

### 8.1 适用范围

- 只对 **decision-grade families** 生效：当前即 `F1` 与 `F2`；
- `F3` 在 phase-1 仍然是 `conditional / exploratory`，因此不会阻塞 `ranking_stability_status = pass`，但也不能据此获得 decisive 推荐。

### 8.2 判定输入

对同一个：

- `workload_group_id`
- `assumption_set_id`
- `fairness_policy_id`
- `power_boundary_id`
- `accounting_boundary_id`

收集 simulator / DSE 与 board 的下列值：

- `time_to_convergence_s`
- `energy_to_convergence_j`
- `fallback_ratio`
- `spill_ratio`

### 8.3 `ranking_stability_status = pass`

只有当下面条件同时成立时，才记为 `pass`：

1. simulator 选中的 `F1/F2` 最优 candidate，与 board 实测下的 `F1/F2` 最优 candidate 一致；
2. 对 `F1` 与 `F2`，board 侧 `time_to_convergence_s` 的顺序与 simulator 一致；
3. 若 `F1` 与 `F2` 的 board 侧时间差小于 `5%`，则只能记为 `tie`，不能记为 `pass`；
4. `fallback_ratio` 与 `spill_ratio` 没有跨过 family judgement 边界：
   - 若 simulator 预测 `resident_fit / low fallback`，board 不得变成 `fallback-dominant` 或 `spill-dominant`；
5. 所有用于排序的关键观测 row（`OBS-01`, `OBS-08`, `OBS-10`, `OBS-12`）都必须先 individually pass。

### 8.4 `ranking_stability_status = fail`

只要出现以下任一情况即记为 `fail`：

1. simulator 推荐 `F1`，board 推荐 `F2`，或反之；
2. board 侧 `F1/F2` 时间顺序颠倒；
3. board 侧关键时间差进入 `<= 5%` tie 区，但 simulator 仍给出 decisive 推荐；
4. fallback / spill 现象改变了 family 的定性解释；
5. 关键观测 row 未通过，因此 family 排序建立在不可信的 observability 上。

## 9. Minimum required board artifact bundle

To make the table executable rather than aspirational, the first board harness should emit at least:

1. `board_manifest.json`
   - frozen join-key tuple
   - board clock / ref-cycle normalization rule
   - measurement start/stop boundary
2. `board_metrics.json`
   - mirrors the simulator candidate JSON fields needed by `OBS-01` through `OBS-11`
3. `board_power.json`
   - whole-node total energy
   - host energy
   - board/device energy
   - idle/static accounting note
4. `board_stdout.out`
   - QE-facing stdout for convergence/timing sanity checks
5. `board_compare.json`
   - board-side correctness report against the same QE gold baseline

Reusing the simulator/DSE naming (`stdout_path`, `metrics_path`, `compare_report_path`) is preferred so later automation does not need two incompatible schemas.

### 9.1 execution-ready board bundle example

推荐直接用 helper 生成 phase-1 board bundle：

```bash
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  board \
  --out-dir "$BOARD_DIR" \
  --workload-id si4_pbe_uspp_small \
  --architecture-family F2 \
  --assumption-set-id phase1_calibrated_v0 \
  --request-id REQ-001 \
  --scf-iteration 6 \
  --episode-id 2
```

它会先生成：

- `board_manifest.json`
- `board_metrics.json`
- `board_power.json`
- `board_compare.json`
- `algorithm_rewrite_manifest.json`

然后再把真实 board measurements / compare outputs 回填进去。

若 board harness helper 还未单独封装，phase-1 可先直接实例化 4 份模板，再用 validator 做结构检查。下面示例展示 `si4_pbe_uspp_small / F1` 的最小 board bundle：

```bash
BOARD_DIR=/tmp/qe_fpga_board_bundle_example
mkdir -p "$BOARD_DIR"
cp docs/benchmarks/qe_fpga_board_manifest_template_v0.json "$BOARD_DIR/board_manifest.json"
cp docs/benchmarks/qe_fpga_board_metrics_template_v0.json "$BOARD_DIR/board_metrics.json"
cp docs/benchmarks/qe_fpga_board_power_template_v0.json "$BOARD_DIR/board_power.json"
cp docs/benchmarks/qe_fpga_board_compare_template_v0.json "$BOARD_DIR/board_compare.json"
python3 tools/benchmarks/check_qe_phase1_artifact_contracts.py \
  --board-dir "$BOARD_DIR" \
  --require-board-bundle
```

当 board run 真正接入后，至少应补齐：

- `board_manifest.json` 中的 `board_run_id`、`board_system`、`measurement_boundary`；
- `board_metrics.json` 中的 `timing / data_movement / cycles / policy_counters`；
- `board_power.json` 中的 `total_energy / energy_ledger / confidence`；
- `board_compare.json` 中的 `correctness / projection_cross_check`。

只有 validator 通过、且关键观测 row 满足本合同阈值时，该 bundle 才能进入 ranking/calibration review。

### 9.2 建议的验证路径

为了让本合同可执行而不是停留在描述层，phase-1 推荐按以下顺序验证：

1. 用 `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` 产出带 contract id 的 DSE/bootstrap bundle；
2. 用 `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json` 检查结果字段是否齐全；
3. 用 `tools/benchmarks/compare_qe_gold_correctness.py` 生成或复查 `board_compare.json`；
4. 若 correctness/tolerance contract 有变动，再用 `tools/benchmarks/check_qe_gold_contract_regression.py` 做回归检查。

## 10. Gating rules

- `OBS-00`, `OBS-01`, `OBS-03`, and `OBS-12` are **hard-gate rows** for any thesis-level board claim.
- `OBS-08`, `OBS-09`, and `OBS-10` are **hard-gate rows** for any resident/offload/fallback attribution claim.
- `OBS-14` is a **hard-gate row** for saying the simulator/DSE was predictive rather than merely descriptive.
- `ranking_stability_status = pass` is a **hard-gate requirement** before promoting any `F1/F2` candidate into deep FPGA optimization or thesis-grade board comparison.
- If `OBS-12` or `OBS-13` fails, the result may still support a performance claim, but it must not support a lower-power claim.
- If `OBS-03` fails, no speedup result is admissible as a thesis win.

## 11. Current known limitations

- This contract does **not** yet supply the missing `CPU+GPU` shell baseline; it only defines what the `CPU+FPGA` simulator↔board chain must expose before that fairness comparison is credible.
- Because the current runnable model can still use `cdiaghg` companion / CPU fallback, the host-assist and fallback rows are not optional bookkeeping; they are central observability rows.
- `F3` should remain conditional until the heavier device path can satisfy the same observability rows without hiding work inside unmeasured fallback/service time.
