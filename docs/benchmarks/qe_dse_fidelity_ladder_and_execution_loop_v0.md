# QE 系统 DSE 前端输入：fidelity ladder and execution loop v0

## 0. 定位

这份文档对应系统 DSE 的 **Step-4 输入 artifact**。

在 Step-1/2/3 已经分别冻结：

- workload characterization
- partition / interface boundary
- parameter stack

之后，这里把后续探索应采用的 **低成本 → 中成本 → 高保真** 评估链，明确成一条可执行的 fidelity ladder。

它的目标不是重新描述所有脚本，而是回答三个问题：

1. 现在 repo 里到底有哪些 fidelity 层；
2. 每一层该回答什么问题，不该回答什么问题；
3. 这些层如何串成一条 stepwise DSE execution loop。

---

## 1. 当前总原则

当前这条系统 DSE 主线不以 RTL / implementation 为第一目标，而以：

- `QE-only`
- simulator / DSE mainline
- rule-based + contract-driven narrowing
- correctness-capable validation

为当前阶段主线。

因此当前 fidelity ladder 的核心原则是：

> **低保真广筛，中保真主搜，高保真做 correctness / closure / release gate，而不是一上来就跑重 implementation。**

---

## 2. Layer A — 低成本 characterization / pruning 层

### 2.1 这一层的工具

#### 软件路径与 trace characterization
- `tools/benchmarks/run_qe_workload_matrix.py`
- `tools/benchmarks/summarize_qe_subspace_trace.py`
- `tools/benchmarks/analyze_qe_scf_operator_load.py`
- `tools/benchmarks/analyze_qe_workload_revalidation.py`
- `tools/benchmarks/extract_qe_shell_cpu_baseline.py`

#### computational-pattern / kernel-mapping 分析
- `docs/benchmarks/qe_step1_computational_pattern_analysis_report.md`
- `docs/benchmarks/qe_multi_case_analysis_report.md`
- `docs/benchmarks/qe_step2_kernel_mapping_dse_report.md`
- `tools/benchmarks/qe_kernel_mapping_dse_step2.py`

### 2.2 这一层应该回答的问题

这一层只负责回答：

1. 热点在哪里：`c_bands`、`h_psi/s_psi`、`build H_sub/S_sub`、`cdiaghg`、`refresh`
2. 这些 kernel 的尺寸、工作集、AI、复用模式是什么
3. 哪些 kernel 是第一波 accelerator 候选
4. 哪些 kernel mapping 参数最值得进入后续探索
5. 哪些 design points 明显 infeasible / 不值得进入中成本层

### 2.3 这一层不应承担的任务

它不应直接给出：

- 最终 `family` 决策
- release-facing recommendation
- board-grounded / thesis-grade 结论
- 最终 RTL 可实现性结论

### 2.4 当前输出形式

当前 Step-1/3 已经把 Layer A 的结论收口成：

- `qe_kernel_characterization_matrix_for_system_dse_v0.md`
- `qe_partition_and_interface_for_system_dse_v0.md`
- `qe_dse_parameter_stack_for_system_dse_v0.md`

---

## 3. Layer B — 中成本 system-simulator / DSE 主搜索层

### 3.1 这一层的工具

- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- `tools/benchmarks/run_qe_next_stage_dse_phase.py`
- `model/qe_band_solver_model/build/qe_band_solver_model`

### 3.2 这一层当前的角色

根据 `qe_next_stage_dse_simulator_execution_checklist_v0.md`，这层是双层框架的主工作层：

#### 快层 fast layer
必须输出：

- `time_to_convergence_s`
- `energy_to_convergence_j`
- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

职责：

- 大规模 sweep / ranking
- state-machine 分类：
  - `reject`
  - `explain-only`
  - `promotion-eligible`
- 形成 shortlist：
  - `primary_candidate`
  - `fallback_candidate`
  - `extra_promoted_candidates`（若满足 tie-band）

#### 当前 mainline cases
- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

### 3.3 这一层当前 objective / constraint

#### 主目标
1. `time_to_convergence_s`
2. `energy_to_convergence_j`

#### 显式约束 / 解释指标
- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

### 3.4 这一层当前的排序逻辑

当前 fast layer 的排序逻辑已经冻结为：

1. 先按 `time_to_convergence_s`
2. 再用 `energy_to_convergence_j` 打破相近候选的 tie
3. 若核心指标缺失或 `ranking_grade_ready != true`，只能 `explain-only`
4. 只有 `promotion-eligible` 的点能进入准层 shortlist

### 3.5 这一层的作用边界

这一层是**主搜索层**，但不是最终 authority。

它负责：

- 大量 design-point 搜索
- family/policy/partition 比较
- ranking 与 shortlist

它不负责：

- 最终 thesis-grade 结论
- measured board-grounded closure
- 单独对外发布 authoritative decision

---

## 4. Layer C — correctness-capable 准层

### 4.1 这一层的工具

仍由：

- `run_qe_next_stage_dse_phase.py`
- `compare_qe_gold_correctness.py`
- `qe_gold_numerical_tolerance_schema_v0.json`
- `normalize_qe_gold_baseline.py`

驱动。

### 4.2 当前覆盖对象

#### accurate-layer anchor
- `si8_pbe_nc`

#### canonical coverage case
- `si8_pbe_uspp`

#### shortlisted candidates
- 对每个 mainline workload 的 `primary` / `fallback` / allowed promoted candidates

### 4.3 这一层至少回答的字段

- `gold_pass`
- `convergence_comparable_pass`
- `final_total_energy_ry`
- `final_converged`
- `final_residual_threshold_reached`

### 4.4 这一层的作用

这层的任务不是覆盖所有点，而是：

- 给 mainline shortlist 做 correctness backstop
- 保证 release-facing recommendation 不是单纯 proxy 排序
- 让 current recommendation 至少达到 **projection-grade**

---

## 5. Layer D — nonblocking generalization 层

### 5.1 当前对象

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`
- `graphene_pbe_paw`
- `h2_tiny`

### 5.2 当前作用

这一层只负责：

- broader confidence / generalization evidence
- 说明当前 recommendation 对更广 workload family 的外推边界

它默认**不阻塞**当前主推荐链，但必须写入：

- phase summary
- artifact bundle manifest
- release delivery spec

### 5.3 当前判断

当前 repo 已跑出来的 next-stage mainline里：

- generalization 允许 mismatch 存在
- 只要主链与 canonical coverage ready，仍可形成 `release_ready_recommendation = true`

---

## 6. Layer E — release / closure / authority 层

### 6.1 当前 artifacts

当前 release-facing artifact chain 已固定为：

1. `qe_next_stage_artifact_bundle_manifest`
2. `qe_next_stage_dse_phase_summary`
3. `qe_next_stage_projection_review`
4. `qe_next_stage_stage_main_recommendation`
5. `accurate_coverage`
6. `generalization_coverage`

### 6.2 release-ready 最低条件

当前 `release_ready_recommendation = true` 的最低条件为：

1. `stage_main_recommendation_status == projection_eligible`
2. `projection_review.review_readiness == ready`
3. `stage_main_recommendation_package.recommendation_status == ready`
4. 若存在 `accurate_coverage`，则 `coverage_ready == true`

### 6.3 当前 authority boundary

这一层也不是最终 public authority 本身。

当前 frozen rule 仍然是：

- adjudicator memo 才是唯一 top-level decision authority
- runnable model / DSE bundle / phase runner artifacts 都是 evidence surfaces

### 6.4 当前 residual risks

即使当前 mainline bundle 已经 ready，也仍可能保留：

- `gpu_annex_deferred`
- `phase1_evidence_external_measurement_artifacts`
- board closure 未闭合

这意味着：

- current result 可用于 projection-grade narrowing
- 不等于 board-grounded final claim

---

## 7. 当前 repo 的 fidelity ladder 映射

| Fidelity layer | 当前 repo 主工具 | 主要问题 | 当前输出 |
| --- | --- | --- | --- |
| Layer A: characterization / pruning | trace + operator-load + kernel-mapping scripts | 热点是谁、哪些参数值得开、哪些明显不值得进主搜 | characterization matrix / partition / parameter stack |
| Layer B: fast-layer system simulator | `run_systemc_architecture_family_dse_sweep.py` | 大量 design point 排序、短名单形成 | ranking rows, shortlist, family summary |
| Layer C: accurate-layer validation | `run_qe_next_stage_dse_phase.py` + gold compare | shortlist 是否满足 frozen correctness / convergence gate | accurate-layer bundle, coverage bundle |
| Layer D: generalization coverage | same phase runner | recommendation 的外推边界是什么 | generalization bundle |
| Layer E: release / closure / authority | release bundle + adjudicator chain | 当前结果是否达到 release-facing / projection-grade ready | manifest / release evidence / adjudicator reference |

---

## 8. 推荐执行循环

当前推荐的 DSE execution loop 固定为：

### Step A — characterization

输入：
- QE traces
- workload reports
- operator-load analysis

输出：
- Step-1/2/3 artifacts

### Step B — coarse prune

用 Layer A 的 characterization 对 design points 做第一层剪枝：

- block-size-aware policy
- resident-sensitivity judgement
- obvious infeasible kernel mappings

### Step C — fast-layer sweep

用 `run_systemc_architecture_family_dse_sweep.py` 或 phase runner的 fast lane：

- 扫 mainline cases
- 形成 `reject / explain-only / promotion-eligible`
- 产出 shortlist

### Step D — accurate-layer validate shortlist

只对 anchor / canonical coverage / shortlisted candidates 做 correctness-capable 校验。

### Step E — attach generalization lane

对 broader cases 形成 nonblocking evidence。

### Step F — produce release-facing evidence surface

产出：

- phase summary
- projection review
- stage-main recommendation
- manifest

### Step G — authority / closure readout

把这些结果作为 evidence 输入给：

- GPU annex / board closure / phase1 evidence closure
- adjudicator authority chain

---

## 9. 默认命令链（当前 repo 可执行版本）

### 9.1 characterization / operator-load

```bash
python3 tools/benchmarks/analyze_qe_workload_revalidation.py
python3 tools/benchmarks/analyze_qe_scf_operator_load.py \
  docs/benchmarks/results/qe_workload_revalidation/si8_pbe_uspp
```

### 9.2 kernel mapping sweep

```bash
python3 tools/benchmarks/qe_kernel_mapping_dse_step2.py \
  --npw 2945 --nkb 144 --m 16 --output-dir /tmp/qe_dse_step2
```

### 9.3 system-level mainline

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4

python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
```

### 9.4 release validation

```bash
python3 tools/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json

python3 tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
```

---

## 10. 当前 Step-4 artifact 的作用边界

这份文档的作用是：

- 把 repo 内已有工具映射成统一的 fidelity ladder；
- 告诉后续 DSE 不同阶段该用哪类工具、回答哪类问题；
- 避免把 fast-layer 排序、accurate-layer 校验、release-facing artifacts 混成一层。

它不直接宣称：

- 当前已经进入 RTL-to-bitstream / RTL-to-GDS fidelity；
- 当前 proxy-level结果已经足以替代 measured board closure；
- heuristic / AI search 当前就应取代 rule-based + accurate-layer chain。

---

## 11. 一句话收口

当前 Step-4 的正式输入可以收成一句话：

> 这个系统的当前 DSE 执行链应固定为 **trace/characterization 粗筛 → system-simulator fast-layer 主搜 → correctness-capable accurate-layer 校验 → nonblocking generalization 覆盖 → release/closure/adjudicator 收口**，并始终遵守“低成本广筛、中成本主搜、高保真做 correctness/closure，而不是直接以 RTL/implementation 为主线”的 fidelity ladder。
