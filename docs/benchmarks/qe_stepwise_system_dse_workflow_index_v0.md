# QE stepwise system DSE workflow index v0

## 0. 定位

这份文档是当前 repo 内 **stepwise system DSE workflow** 的执行入口。

它的作用不是替代已有的 characterization、partition、parameter、phase-runner 文档，而是把它们按 **Step-1 → Step-6** 串起来，让下一位人类或 agent 不需要再自己拼接：

- 前端输入 artifact 在哪里；
- 每一步的目标是什么；
- 每一步之后应该交给哪一层工具；
- 当前 repo 已经跑通到哪一步。

---

## 1. 当前 stepwise DSE 主线

当前建议按下面顺序推进：

1. **Step-1 — Workload characterization**
2. **Step-2 — Partition and interface freeze**
3. **Step-3 — Parameter stack**
4. **Step-4 — Fidelity ladder and execution loop**
5. **Step-5 — System-level fast/accurate DSE execution**
6. **Step-6 — Release / closure / authority readout**

这条主线遵循当前 frozen 原则：

- 先系统级，后细粒度硬件维度；
- 先解释热点、边界和参数层级，再跑系统级主搜索；
- 低成本广筛，中成本主搜，高保真做 correctness / closure；
- adjudicator 仍是唯一 top-level authority。

---

## 2. Step-1 — Workload characterization

### 2.1 目标

确认：

- 原始科学计算软件里真正的系统热点是谁；
- 第一波 accelerator candidate kernels 是谁；
- 哪些路径是 generalized / overlap 主路径；
- 哪些路径只是 companion / fallback。

### 2.2 当前输入证据

- `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_system_workload_revalidation_report_20260321.md`
- `docs/benchmarks/archive/results/qe_workload_revalidation/summary.json`
- `docs/benchmarks/archive/results/qe_workload_revalidation/summary_tables.md`
- `docs/benchmarks/si8_scf_operator_load_experiment_plan.md`
- `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_step1_computational_pattern_analysis_report.md`
- `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_multi_case_analysis_report.md`

### 2.3 当前 Step-1 artifact

- `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md`

### 2.4 当前冻结结论

- `c_bands` 是系统级主热点
- 第一波主热点是 `h_psi / s_psi`
- `build H_sub/S_sub` 与 `refresh/residual` 是必须纳入的 companion path
- `cdiaghg` 当前保持 policy-sensitive companion / fallback lane

---

## 3. Step-2 — Partition and interface freeze

### 3.1 目标

冻结：

- `Host / thin device runtime / hardware datapath` 三层对象；
- 第一波 accelerator kernel 的边界；
- resident / DMA / fallback / completion 的主接口。

### 3.2 当前输入证据

- `docs/architecture/host_managed_full_scf_architecture_v1_20260409.md`
- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`
- cluster specs under `docs/architecture/qe_fpga_clustered_v1_cluster_*.md`

### 3.3 当前 Step-2 artifact

- `docs/benchmarks/qe_partition_and_interface_for_system_dse_v0.md`

### 3.4 当前冻结结论

- Host 负责 shell control / `rho -> Veff` / `mix_rho` / convergence / host fallback
- thin device runtime 负责 resident preload / DMA / launch / fallback bridge / completion summary
- hardware datapath 第一波主闭环是 `h_psi/s_psi + build H_sub/S_sub + refresh/residual`
- `cdiaghg` 保持 companion / fallback-friendly 角色

---

## 4. Step-3 — Parameter stack

### 4.1 目标

把后续 DSE 的 knobs 显式收口成统一 vocabulary。

### 4.2 当前输入证据

- `docs/benchmarks/qe_ic_system_level_dse_axes_v0.md`
- `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`
- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- `docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json`
- `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_step2_kernel_mapping_dse_report.md`
- `tools/benchmarks/qe_kernel_mapping_dse_step2.py`

### 4.3 当前 Step-3 artifact

- `docs/benchmarks/qe_dse_parameter_stack_for_system_dse_v0.md`

### 4.4 当前参数层级

- Layer 1: workload/signature layer
- Layer 2: system partition layer
- Layer 3: kernel mapping layer
- Layer 4: evaluation/evidence-control layer

### 4.5 当前优先 knobs

#### system-level
- `offload_scope`
- `resident_policy`
- `partition_strategy`
- `diag_policy`
- `family`

#### kernel-mapping
- `tile_npw`
- `tile_nkb`
- `tile_m`
- loop ordering
- dataflow
- buffer hierarchy

---

## 5. Step-4 — Fidelity ladder and execution loop

### 5.1 目标

把 repo 中已有工具映射成低成本 → 中成本 → 高保真链路。

### 5.2 当前 Step-4 artifact

- `docs/benchmarks/qe_dse_fidelity_ladder_and_execution_loop_v0.md`

### 5.3 当前 fidelity 层

#### Layer A — characterization / pruning
- trace summary
- operator-load analysis
- kernel-mapping DSE

#### Layer B — fast-layer system simulator
- `run_systemc_architecture_family_dse_sweep.py`
- mainline ranking / shortlist

#### Layer C — accurate-layer correctness validation
- `run_qe_next_stage_dse_phase.py`
- gold compare / canonical coverage

#### Layer D — nonblocking generalization
- broader confidence lane

#### Layer E — release / closure / authority
- manifest
- release evidence
- adjudicator chain

---

## 6. Step-5 — System-level DSE execution

### 6.1 目标

在 Step-1/2/3/4 已冻结的前提下，真正运行：

- fast-layer ranking
- accurate-layer shortlist validation
- canonical coverage
- generalization coverage
- recommendation package

### 6.2 当前主执行命令

#### Build runnable model

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

#### Run next-stage phase

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
```

### 6.3 当前已经跑通的结果

当前 repo 已经本地跑通并生成：

- `tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json/.md`
- `tmp/qe_next_stage_release/qe_next_stage_projection_review.json/.md`
- `tmp/qe_next_stage_release/qe_next_stage_stage_main_recommendation.json/.md`
- `tmp/qe_next_stage_release/qe_next_stage_artifact_bundle_manifest.json/.md`
- `tmp/qe_next_stage_release/qe_next_stage_release_evidence.json/.md`

### 6.4 当前运行结论

- `recommended_family = F1`
- `stage_main_recommendation_status = projection_eligible`
- `bundle_readiness = ready`
- `release_ready_recommendation = true`
- canonical coverage ready
- generalization 仍存在 nonblocking mismatch

---

## 7. Step-6 — Validation / closure / authority readout

### 7.1 当前 validator

#### Release bundle validator

```bash
python3 tools/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json
```

#### Strategy / contract alignment validator

```bash
python3 tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
```

### 7.2 当前状态

两者当前都可通过。

### 7.3 当前 authority 读法

即使当前 `release_ready_recommendation = true`，也仍然要按 frozen boundary 阅读：

- 这是 **projection-grade / release-facing evidence package**
- 不是 measured-board-grounded final authority
- adjudicator memo 仍是 top-level authority

---

## 8. 推荐工作顺序（给下一位执行者）

### 如果前端还没冻结

按顺序读：

1. `qe_kernel_characterization_matrix_for_system_dse_v0.md`
2. `qe_partition_and_interface_for_system_dse_v0.md`
3. `qe_dse_parameter_stack_for_system_dse_v0.md`
4. `qe_dse_fidelity_ladder_and_execution_loop_v0.md`

### 如果前端已经冻结

直接进入：

5. `run_qe_next_stage_dse_phase.py --execute-model`
6. release validators
7. GPU/board closure / adjudicator-oriented continuation

---

## 9. 当前缺口与下一步

当前已经补齐了 Step-1~Step-4 的前端 artifact，且 Step-5 主线可运行。

因此后续最自然的两个方向是：

### 方向 A — 把 Step-1~4 真正接入后续 phase-runner narrative

例如让 phase summary / recommendation package 能引用这些前端 artifact 作为“为什么是这些 knobs / boundaries”的解释层。

### 方向 B — 继续推进 closure

包括：

- GPU baseline dirs / reference dirs
- board dirs
- 更强 evidence closure

---

## 10. 一句话收口

当前 repo 的 stepwise system DSE 主线已经可以明确读成：

> **先用 characterization / partition / parameter stack / fidelity ladder 四份前端 artifact 固定系统对象与探索边界，再用 next-stage phase runner 执行双层 DSE 主搜索，最后通过 release validators 与 adjudicator boundary 完成结果收口。**
