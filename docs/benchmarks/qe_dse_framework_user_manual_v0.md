# QE/DFT DSE 框架辅助工具用户手册 v0

## 0. 本手册的作用

本手册说明当前仓库中的 **QE/DFT DSE 辅助框架** 如何被使用、验证、解释、归档和交付。它面向接手该仓库的研究者、agent、advisor-facing 报告编写者，以及需要复现实验结果的评审者。

本手册描述的是工具框架本身，而不是后续开发计划。它回答以下问题：

1. DSE 框架由哪些文档、脚本、模型和 contract 组成？
2. 输入 artifact 是什么？
3. 如何运行 Stage-A sweep、next-stage phase、release bundle validation 和 adjudicator？
4. 每个输出 artifact 应该按什么顺序阅读？
5. 如何判断一个结果是 `reject`、`explain-only` 还是 `promotion-eligible`？
6. 如何区分 candidate identity、runtime projection 和 evidence fidelity？
7. 哪些结论可以说，哪些必须 guarded，哪些当前不能说？

本手册不承担以下角色：

- 不定义新的 RTL / FPGA / ASIC 实施路线；
- 不把当前模型结果升级为 board-measured 或 thesis-grade 结论；
- 不替代 `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`；
- 不把 Stage-A 或 next-stage runner 的 recommendation-like 字段当作最终决策；
- 不声称 `F4`、`F5`、`custom` 已有 native executor；
- 不声称 gem5/SystemC co-sim 已经有可执行结果。

核心原则：

```text
DSE organizes evidence.
Adjudicator controls claims.
```

---

## 1. 权威边界和阅读规则

当前文档链的最高层规则来自：

- `docs/README.md`
- `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`
- `docs/benchmarks/qe_complete_architecture_family_dse_framework_v0.md`
- `docs/benchmarks/qe_unified_dse_framework_v0.md`
- `model/qe_band_solver_model/README.md`

统一阅读规则如下：

1. `run_systemc_architecture_family_dse_sweep.py` 只产生 DSE evidence。
2. `run_unified_dse_v0.py` 是 additive bounded v0 CLI wrapper，只组织 Stage-A evidence-only、adjudicator-ready 结果，不替代当前 family sweep runner。
3. `run_qe_next_stage_dse_phase.py` 只组织 fast-layer、accurate-layer、coverage 和 release-facing evidence。
4. `qe_next_stage_stage_main_recommendation.*` 是 pre-adjudication evidence package，不是最终 public authority。
5. `model/qe_band_solver_model/README.md` 描述 runnable model truth，但它不是第二套 authority surface。
6. 只有 adjudicator memo 可以把 evidence 合成为 public family decision、release posture 和 claim-permission decision。

因此，阅读任何 DSE 输出时，必须先问：

```text
这个 artifact 是 evidence、package、validator output，还是 adjudicator authority?
```

如果它不是 adjudicator output，就不能单独用于最终 claim。

---

### 1.1 Unified DSE staged contract bundle

Unified DSE staged documentation/contract lane 由以下文件固定：

- `docs/benchmarks/qe_dse_systemc_feedback_contract_v0.md`：SystemC feedback dry-run 默认为 `planned_not_executed` / `not_executed` / `timed_functional_proxy_contract_only`，不隐式运行 SystemC。
- `docs/benchmarks/qe_dse_gem5_systemc_handoff_contract_v0.md`：gem5/SystemC handoff 默认为 Stage B planning record，`execution_status = not_executed`，`platform_status = requires_linux_x86_validation`。
- `docs/benchmarks/qe_unified_dse_stage_a_readiness_checklist_v0.md`：固定 QE anchor status、pre-adjudication ranking 语义，以及 `final_public_family_winner = null` 的 Stage A 边界。
- `docs/benchmarks/qe_dse_qe_correctness_report_contract_v0.md`：固定 Stage C external QE-equivalent correctness report 的 schema 和 claim gate。
- `docs/benchmarks/qe_dse_fpga_asic_implementation_evidence_contract_v0.md`：固定 Stage D FPGA/ASIC implementation evidence 的 schema、target/evidence-kind matrix 和 overclaim 拒绝规则。

这些合同只允许 evidence-only / screening-only 读法：CLI 不生成 RTL/HLS/board、cycle accuracy、CIM-only identity、实际 gem5-controlled SCF 或最终 public winner claim；QE-equivalent SCF 只能来自 validated external correctness report。老师汇报语言继续引用 `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` 和 `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md`，不要另造 recommendation 口径。

---

## 2. 框架总览

当前 DSE 工具链可以理解为五层：

```text
Layer A: Workload characterization / pruning
Layer B: Fast-layer system-simulator DSE search
Layer C: Correctness-capable accurate layer
Layer D: Nonblocking generalization coverage
Layer E: Release / closure / adjudicator authority
```

对应操作流：

```text
workload characterization
  -> partition/interface freeze
  -> parameter stack freeze
  -> fidelity ladder selection
  -> Stage-A / next-stage DSE execution
  -> release artifact bundle
  -> adjudicator memo
```

这个顺序来自 `docs/benchmarks/qe_stepwise_system_dse_workflow_index_v0.md`。它的关键思想是：

```text
低成本广筛，中成本主搜，高保真做 correctness / closure / release gate。
```

---

## 3. 核心文档地图

### 3.1 顶层索引与权威合同

| 文件 | 作用 |
| --- | --- |
| `docs/README.md` | 仓库文档索引，冻结 adjudicator-first 阅读规则。 |
| `docs/benchmarks/AGENTS.md` | benchmark 目录入口，列出 DSE、baseline、closure、contract validation 的主要脚本。 |
| `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` | 冻结唯一 public decision authority；上游 DSE、projection、GPU annex、phase recommendation 均为 evidence input。 |
| `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` | CPU/GPU/FPGA 比较、公平性、whole-node power 边界。 |
| `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md` | workload-group admission 与 same-correctness / same-tolerance 规则。 |
| `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md` | algorithm rewrite 分类与 baseline eligibility。 |
| `docs/benchmarks/qe_simulator_board_observability_contract_v0.md` | simulator/DSE 与 FPGA board observability / calibration 的连接规则。 |

### 3.2 DSE 主线文档

| 文件 | 作用 |
| --- | --- |
| `docs/benchmarks/qe_stepwise_system_dse_workflow_index_v0.md` | Step-1 到 Step-6 的主线索引。 |
| `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md` | Step-1 workload characterization 输出。 |
| `docs/benchmarks/qe_partition_and_interface_for_system_dse_v0.md` | Step-2 Host / device runtime / hardware datapath 边界。 |
| `docs/benchmarks/qe_dse_parameter_stack_for_system_dse_v0.md` | Step-3 knobs / parameter stack vocabulary。 |
| `docs/benchmarks/qe_dse_fidelity_ladder_and_execution_loop_v0.md` | Step-4 fidelity ladder 与 execution loop。 |
| `docs/benchmarks/qe_complete_architecture_family_dse_framework_v0.md` | 完整 architecture-family DSE framework 说明。 |
| `docs/benchmarks/qe_unified_dse_framework_v0.md` | Unified DSE Framework v0 的 bounded architecture / plan；说明 additive stdlib package、薄 CLI、Stage-A evidence-only 边界、opt-in `SystemC` 执行和 stub/reserved/projection-only implementation backend。 |
| `docs/benchmarks/qe_equal_candidate_dse_design_manual_v0.md` | equal-candidate semantics，区分 architecture identity 与 evaluator support。 |
| `docs/benchmarks/qe_next_stage_dse_strategy_v0.md` | next-stage 五层策略，说明 rule-based / contract-driven DSE 与 future heuristic / AI DSE 的关系。 |
| `docs/benchmarks/qe_next_stage_release_delivery_spec_v0.md` | release-facing artifact chain 的读取顺序、ready 条件和交付方式。 |

### 3.3 主执行脚本与 schema

| 文件 | 作用 |
| --- | --- |
| `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` | Stage-A architecture-family sweep 入口。 |
| `tools/benchmarks/run_unified_dse_v0.py` | Unified DSE v0 薄 CLI；用于 dry-run / bounded evidence package，不声明 winner，不替代现有 Stage-A runner 或 adjudicator。 |
| `tools/benchmarks/run_qe_next_stage_dse_phase.py` | next-stage fast/accurate/generalization/release phase runner。 |
| `tools/benchmarks/run_qe_system_design_adjudicator.py` | adjudicator memo generator。 |
| `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json` | DSE result bundle schema。 |
| `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` | next-stage phase config，包含 cases、objectives、promotion states 和 tie-band。 |
| `docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json` | fast-layer proxy assumption set。 |
| `docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json` | QE gold correctness tolerance schema。 |

### 3.4 Validators

| 文件 | 作用 |
| --- | --- |
| `tools/benchmarks/check_qe_ic_component_graph_v1.py` | 检查 component catalog 与 graph seed。 |
| `tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py` | 检查 phase config、execution checklist、schema、runner 是否漂移。 |
| `tools/benchmarks/check_qe_next_stage_release_bundle.py` | 检查 release bundle manifest、summary、coverage 与下游 artifact 是否自洽。 |
| `tools/benchmarks/check_qe_gold_contract_regression.py` | gold correctness contract regression。 |

### 3.5 Runnable model

| 文件 | 作用 |
| --- | --- |
| `model/qe_band_solver_model/README.md` | 当前 runnable model truth：host-managed timed-functional proxy model。 |
| `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md` | 历史 smoke record；可作背景，不应覆盖当前 README truth。 |
| `model/qe_band_solver_model/sc_main.cpp` | executable entry 与 `QEBS_*` runtime fields。 |

---

## 4. 核心概念

### 4.1 Candidate identity

候选身份由以下字段表达：

```text
candidate_family
architecture_template_id
candidate_id
design_axes
```

其中 `candidate_family` 是 immutable architecture identity。它不应因为当前 evaluator 只能用某个兼容 runtime 近似执行而改变。

例子：

```json
{
  "candidate_family": "F4",
  "architecture_template_id": "f4_cim_dsp_hbm_hybrid_v1",
  "runtime_projection_family": "F2"
}
```

正确解读：

```text
这是一个 F4 candidate，目前通过 F2-compatible runtime projection 产生 evidence。
```

错误解读：

```text
这个 candidate 已经变成 F2。
```

### 4.2 Runtime projection

`runtime_projection_family` 是 evaluator metadata。它说明当前执行/投影路径使用哪个 runtime/profile 近似 candidate，不代表 candidate identity。

常见情形：

- `F1/F2/F3`：在已有 runtime/profile-backed path 上可能有 executable proxy evidence；
- `F4/F5/custom`：当前多为 projection/scaffold，除非未来有明确 native executor evidence；
- `gem5_systemc_cosim`：当前是 reserved/stub evaluator backend，不是 candidate family。

### 4.3 Evidence fidelity

与证据质量相关的字段包括：

```text
evaluator_backend
fidelity_class
support_status
support_evidence
executor_claim_allowed
```

常见 fidelity / support 状态包括：

```text
stub
reserved
projection_only
trace_calibrated_proxy
correctness_capable
measured
```

重要规则：

```text
candidate quality != evidence quality
```

一个 candidate 可以是 equal candidate，但它的当前 evidence 仍然可能只是 projection-only。projection-only 可以用于 screening、explanation、nomination，但不能用于 native executor claim、board power claim 或 final public performance claim。

### 4.4 `executor_claim_allowed`

`executor_claim_allowed` 只说明 row 是否可以声称使用了某个 supported executor/proxy path。它不是 public/final claim permission。

因此：

```text
executor_claim_allowed = true
```

不等于：

```text
CPU + FPGA beats CPU + GPU
该 family 是最终最佳架构
板级功耗已经闭合
```

### 4.5 Same-fidelity ranking

DSE ranking 只应在 comparable workload、constraint、evaluator 和 fidelity group 内解释。跨 fidelity 的比较可以用于 nomination / promotion，但不能直接给 winner claim。

---

## 5. 输入 artifacts

### 5.1 Workload / case 输入

常用输入：

```text
docs/benchmarks/qe_ic_case_signature_matrix_v0.json
docs/benchmarks/archive/results/qe_ic_case_pack_v0.json
docs/overview/qe_subspace_sampling.md
docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md
```

这些 artifact 描述：

- workload identity；
- workload group；
- case signature；
- solver path；
- property target；
- hotspot / companion path。

当前主线 workload pressure 来自 `c_bands`，重点路径包括：

```text
h_psi / s_psi
build H_sub / S_sub
cdiaghg
refresh / residual -> P_next
```

### 5.2 Architecture / graph / template 输入

常用输入：

```text
docs/architecture/qe_ic_component_catalog_system_level_v1.json
docs/architecture/qe_ic_graph_seed_system_level_v1.json
docs/architecture/architecture_templates/
docs/benchmarks/qe_architecture_family_design_space_spec_v0.json
```

这些 artifact 定义：

- component catalog；
- graph seed；
- architecture template；
- design-point axes；
- candidate family scaffold。

当前关键 design-point keys：

```text
family
diag_policy
offload_scope
resident_policy
partition_strategy
```

### 5.3 Assumption / tolerance / phase config 输入

常用输入：

```text
docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json
docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json
docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json
```

当前 canonical metadata：

```text
assumption_set_id = qe_next_stage_phase_v0
qe_tolerance_schema_id = qe_gold_numerical_tolerance_schema_v0
```

`pending_calibration_v0` 只能作为 legacy alias，不应作为新的默认输出身份。

### 5.4 Contract 输入

结果解释必须服从以下 contract：

```text
docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md
docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md
docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md
docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md
docs/benchmarks/qe_simulator_board_observability_contract_v0.md
```

这些文件决定：

- workload 是否 admissible；
- baseline 是否 fair；
- rewrite 是否 comparable；
- power / board / observability claim 是否被允许；
- adjudicator 是否可以 unlock 某类 public claim。

---

## 6. Runnable model 的定位

`model/qe_band_solver_model/` 当前是：

```text
host-managed timed-functional system model
```

它的行为链为：

```text
DFTHybridSystem
  -> HostSCF
  -> FPGAOrchestrator
  -> ChipTop
  -> EpisodeController
  -> ClusterGraphExecutor
  -> Cluster A/B/C/D
  -> next SCF iteration
```

Cluster 含义：

| Cluster | 作用 |
| --- | --- |
| A | fused `h_psi + s_psi` operator sweep |
| B | reduced `H_sub / S_sub` build |
| C | hardware-first diagonalization proxy |
| D | refresh / residual -> `P_next` |

它不是：

- numerically faithful full DFT implementation；
- frozen RTL-level chip model；
- board-measured implementation；
- final decision authority。

构建命令：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

默认运行：

```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

可选 real SystemC 构建：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build-systemc \
  -DQE_BAND_SOLVER_USE_SYSTEMC=ON \
  -DSYSTEMC_HOME=<your-systemc-prefix>
cmake --build model/qe_band_solver_model/build-systemc -j4
```

---

## 7. 标准运行流程

### 7.1 Smoke：快速检查工具链

入口：

```bash
./quick_start_dse.sh
```

用途：

- 检查 component/graph validation；
- 构建 runnable model；
- 运行 bounded stub sweep；
- 快速发现环境或路径问题。

Smoke 不是 final run，也不产生 thesis-grade claim。

### 7.2 Stage-A architecture-family sweep

典型 bounded template-driven smoke：

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --template-driven \
  --architecture-template-dir docs/architecture/architecture_templates \
  --emit-projected-configs \
  --source-kind stub \
  --output-dir tmp/stage_a_template_dse_smoke
```

更完整的 graph/catalog 入口：

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_sweep_results
```

如果需要执行 runnable model，需要先构建模型，并显式使用 execution path，例如相关文档中的 `--execute-model` flow。未执行模型的 `--source-kind stub` run 只能证明 schema、template、projection、coverage 和 evidence packaging 能跑通。

### 7.2.1 Unified DSE v0 bounded wrapper

Unified DSE v0 的架构和实施计划见 `docs/benchmarks/qe_unified_dse_framework_v0.md`。它是 additive stdlib package + thin CLI wrapper，用来把 workload、design-space、proxy metrics、projection 状态和 adjudicator intake sidecar 组织成 bounded v0 evidence package。

典型 dry-run 入口：

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload tmp/workload_descriptor.json \
  --output-dir tmp/unified_dse_results \
  --dry-run
```

读取规则：

- 这是 Stage-A evidence-only、adjudicator-ready wrapper，不是 public decision authority；
- 当前 canonical Stage-A family sweep orchestrator 仍是 `run_systemc_architecture_family_dse_sweep.py`；
- `SystemC` execution 必须显式 opt-in，默认 dry-run / proposal-only 不隐式运行模型；
- implementation backend 在 v0 中只允许 stub / reserved / projection-only，不表示 HLS、RTL、OpenROAD、FPGA board 或 whole-node power capability 已完成。

Stage B0 descriptor-only handoff 可以在不执行仿真的情况下显式生成：

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload tmp/workload_descriptor.json \
  --output-dir tmp/unified_dse_results \
  --dry-run \
  --emit-stage-b0-descriptors
```

该模式会额外写出 `systemc_configs/`、`gem5_systemc_handoff/` 和
`stage_b0_descriptor_manifest_v0.json`。这些文件只是下一阶段 SystemC/gem5 adapter 的输入合同；
`execution_status` 仍为 `not_executed`，不能读成 gem5 已经控制 SystemC 或 QE-equivalent SCF 已经完成。

如果已有外部 SystemC feedback artifact，可以用 `--systemc-feedback` 回流指标：

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload tmp/workload_descriptor.json \
  --systemc-feedback tmp/systemc_feedback.json \
  --output-dir tmp/unified_dse_results \
  --dry-run
```

这个模式只读取 artifact；CLI 不启动 SystemC。若 artifact 含完整 proxy metrics，DSE row 可以进入
`promotion-eligible`，但仍是 timed-functional/proxy feedback，不是最终 public winner。

如果需要一眼查看所有阶段状态，可加：

```bash
--emit-full-stage-status
```

输出 `unified_dse_full_stage_status_v0.json`。没有真实外部报告的后续阶段会显示为
`blocked_waiting_*`，例如 gem5/SystemC smoke、QE-equivalent correctness、FPGA/ASIC implementation evidence。

Stage B3 的 gem5/SystemC smoke 报告可以通过 `--gem5-smoke-report` 引用，但必须是外部已经产生的
`qe_dse_gem5_systemc_smoke_report_v0` artifact。该报告只能证明 smoke-level bridge/control evidence；
`claim_ceiling` 必须是 `gem5_systemc_smoke_only`，且
`correctness_gate.qe_equivalent_scf_claim` 必须保持 `false`。

Stage C 的 QE-equivalent correctness 报告可以通过 `--qe-correctness-report` 引用。该报告必须使用
`qe_dse_qe_equivalent_correctness_report_v0` schema，并且只有在
`correctness_status = pass`、`compare_report.overall_pass = true`、容差 schema 为
`qe_gold_numerical_tolerance_schema_v0` 时，才允许设置
`qe_equivalent_scf_claim = true`。这只证明 correctness gate 通过，不证明硬件实现、性能优势或最终架构赢家。

Stage D 的 FPGA/ASIC implementation evidence 可以通过 `--implementation-evidence` 引用。该 artifact
必须使用 `qe_dse_fpga_asic_implementation_evidence_v0` schema，并明确写出
`implementation_target_class`、`evidence_kind`、窄 claim ceiling（例如
`hls_synthesis_only`、`rtl_simulation_only`、`fpga_board_measurement_only`、
`asic_ppa_estimate_only`）。CLI 只做 schema / claim-boundary validation，不运行 HLS、RTL、OpenROAD、
board 或 ASIC flow，也拒绝 `final_public_family_winner` / production release ready 这类越权字段。

Stage-A 允许：

```text
screen
rank
explain
nominate
account missing metrics
package evidence
```

Stage-A 不允许：

```text
final public best-family selection
CPU + FPGA beats CPU + GPU claim
board-grounded power claim
native executor claim for projection-only family
thesis-grade architecture decision
```

### 7.3 Canonical QE gold gate

Runnable model README 中给出的 canonical QE gold gate：

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --gold-required-only \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F1 F2 F3 \
  --canonical-only \
  --execute-model \
  --auto-match-baseline-iters \
  --fail-on-gold-mismatch \
  --output-dir tmp/qe_gold_lane
```

典型输出：

```text
systemc_architecture_family_dse_bootstrap_v0.json
systemc_architecture_family_dse_bootstrap_v0.csv
qe_gold_gate_summary_v0.json
qe_gold_gate_summary_v0.md
artifacts/baseline/*.gold.json
artifacts/candidate/*.json
artifacts/compare/*.compare.json
artifacts/stdout/*.log
```

退出码规则：

- `0`：selected gold-required rows 均通过；
- 非零：存在 mismatch 或 infrastructure status，例如 `baseline_missing`、`candidate_missing`、`model_error`、`compare_error`。

### 7.4 Next-stage DSE phase

构建模型：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

运行 next-stage phase：

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
```

如果只需要 stub/source-kind flow，可使用 runner 支持的 non-execute mode，例如：

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --include-conditional-families \
  --source-kind stub
```

next-stage phase 负责：

- fast-layer ranking；
- accurate-layer shortlist validation；
- canonical coverage；
- generalization coverage；
- projection review；
- stage-main recommendation-like package；
- artifact bundle manifest；
- release evidence。

---

## 8. 输出 artifacts 与阅读顺序

### 8.1 Stage-A sweep 输出

典型输出：

```text
systemc_architecture_family_dse_bootstrap_v0.json
systemc_architecture_family_dse_bootstrap_v0.csv
stage_a_coverage_manifest_v0.json
qe_system_design_adjudicator_reference.json
adjudicator/decision_memo.json
unified_dse_results_v0.json, if generated by run_unified_dse_v0.py
unified_dse_results_v0.csv, if generated by run_unified_dse_v0.py
unified_dse_manifest_v0.json, if generated by run_unified_dse_v0.py
```

读取方式：

1. 先读 JSON bundle，不要只看 CSV；
2. 用 CSV 做快速排序和表格检查；
3. 用 coverage manifest 看 family/support/missing-metric coverage；
4. 若使用 Unified DSE v0，先读 `unified_dse_manifest_v0.json` 确认 `authority_scope`、`claim_posture` 和 promotion-state counts；
5. 用 adjudicator reference / memo 看 claim permission，而不是直接从 ranking 得出结论。

### 8.2 Next-stage release 输出

典型输出：

```text
fast_layer/fast_layer_bundle.json
accurate_layer/accurate_layer_bundle.json
accurate_coverage/accurate_coverage_bundle.json
generalization_coverage/generalization_coverage_bundle.json
qe_next_stage_dse_phase_summary.json
qe_next_stage_projection_review.json
qe_next_stage_stage_main_recommendation.json
qe_next_stage_artifact_bundle_manifest.json
qe_next_stage_release_evidence.json
```

推荐阅读顺序：

```text
1. qe_next_stage_artifact_bundle_manifest.json / .md
2. qe_next_stage_dse_phase_summary.json / .md
3. qe_next_stage_projection_review.json / .md
4. qe_next_stage_stage_main_recommendation.json / .md
5. accurate_coverage/accurate_coverage_bundle.json / .csv
6. generalization_coverage/generalization_coverage_bundle.json / .csv
7. adjudicator memo, if generated
```

不要直接跳到 stage-main recommendation。manifest 是 release-facing 顶层入口，因为它汇总 readiness、artifact paths、coverage summary 和 generalization status。

### 8.3 Artifact dictionary

| Artifact | 作用 | 不能做什么 |
| --- | --- | --- |
| `systemc_architecture_family_dse_bootstrap_v0.json` | Stage-A row-level evidence bundle。 | 不能单独给 final family claim。 |
| `systemc_architecture_family_dse_bootstrap_v0.csv` | flattened view，便于排序和 spreadsheet 分析。 | 不能替代 JSON schema。 |
| `stage_a_coverage_manifest_v0.json` | candidate/support/missing-metric coverage。 | 不能证明 unsupported family 已有 executor。 |
| `unified_dse_results_v0.json` | Unified DSE v0 row-level evidence bundle。 | 不能替代 current Stage-A runner、schema 或 adjudicator。 |
| `unified_dse_manifest_v0.json` | Unified DSE v0 evidence package index，记录 evidence-only authority scope。 | 不能发布 final winner、board claim 或 implementation-backed claim。 |
| `fast_layer_bundle.json` | fast-layer metrics、ranking、state machine。 | 不能直接作为 final recommendation。 |
| `accurate_layer_bundle.json` | shortlisted candidates 的 correctness-capable evidence。 | 不能覆盖所有 design space。 |
| `projection_review.json` | accurate-layer-passing shortlisted candidates 汇总。 | 不是 adjudicator authority。 |
| `stage_main_recommendation.json` | pre-adjudication recommendation package。 | 不是最终 public authority。 |
| `artifact_bundle_manifest.json` | release-facing top-level index。 | 不能跳过 adjudicator claim policy。 |
| `decision_memo.json` | adjudicator decision / claim permission。 | 只能表达其 evidence bundle 已解锁的 claim。 |

---

## 9. Ranking、promotion 与 state machine

fast-layer 至少关注这些核心 ranking metrics：

```text
time_to_convergence_s
energy_to_convergence_j
bytes_moved_to_convergence
fallback_ratio
spill_ratio
```

排序原则：

1. 优先 `time_to_convergence_s`；
2. 再用 `energy_to_convergence_j` 打破接近候选的 tie；
3. `bytes_moved_to_convergence`、`fallback_ratio`、`spill_ratio` 是显式约束/解释指标；
4. 核心指标缺失或 `ranking_grade_ready != true` 时，row 只能 `explain-only`；
5. 只有 `promotion-eligible` row 能进入 shortlist。

状态含义：

| State | 含义 |
| --- | --- |
| `reject` | candidate 缺失、baseline 缺失、model error、compare error 或其他 hard failure。 |
| `explain-only` | 有解释价值，但缺 ranking-grade metrics 或不满足 promotion gate。 |
| `promotion-eligible` | metrics 完整且通过 fast-layer gate，可进入 accurate-layer shortlist。 |

tie-band 规则由 `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` 冻结；现有文档记录相对 time tie-band 为 `0.05`。

---

## 10. Accurate-layer / correctness-capable 规则

accurate layer 不是大规模搜索层。它的作用是给 shortlisted candidates 提供 correctness backstop。

至少关注字段：

```text
gold_pass
convergence_comparable_pass
final_total_energy_ry
final_converged
final_residual_threshold_reached
```

相关工具：

```text
tools/benchmarks/normalize_qe_gold_baseline.py
tools/benchmarks/compare_qe_gold_correctness.py
docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json
```

正确解读：

```text
accurate-layer pass 支持 projection-grade / recommendation-grade evidence。
```

错误解读：

```text
accurate-layer pass 自动等于 board-measured 或 final architecture claim。
```

---

## 11. Release-ready 与 adjudicator-ready

当前 release-facing chain 中常见 readiness 条件包括：

```text
stage_main_recommendation_status == projection_eligible
projection_review.review_readiness == ready
stage_main_recommendation_package.recommendation_status == ready
accurate_coverage_summary.coverage_ready == true, if accurate coverage exists
```

但即使 release-facing bundle ready，也仍然只是：

```text
ready for bounded / projection-grade delivery
```

不是：

```text
ready for thesis-grade final authority
```

adjudicator-ready 的最低要求是 evidence bundle 能明确区分：

- evidence tier；
- confidence / maturity；
- claim permission；
- final public decision；
- trusted-family 与 performance-family 是否分歧。

若 trusted-family 与 performance-family 不一致，DSE 可以展示分歧，但不能自行发布 winner。该分歧必须交给 adjudicator。

---

## 12. Claim boundary

### 12.1 可以说

在证据来源、workload、fidelity 和配置都写清楚的前提下，可以说：

```text
在当前 DSE 配置和 fidelity level 下，某 candidate/family 表现较好。
```

```text
当前 evidence 支持该 candidate 进入下一层 validation。
```

```text
当前结果是 projection-grade / timed-functional-proxy evidence。
```

```text
某些 rows 由于 missing metrics 只能 explain-only。
```

### 12.2 必须 guarded 地说

以下表述必须附带 workload、source kind、fidelity、是否 execute-model、是否通过 accurate-layer、是否缺 GPU/board closure：

```text
当前模型暗示某 family 可能有系统级优势。
```

```text
当前 stage-main package 推荐某 family。
```

```text
当前 best_performance_candidate 优于 best_trusted_point。
```

### 12.3 不能说

除非有额外 closure evidence 且 adjudicator unlock 对应 claim，否则不能说：

```text
FPGA 一定优于 GPU。
CPU + FPGA beats CPU + GPU。
该架构是最终最优。
板级功耗已经验证。
F4/F5/custom 已有 native executor。
gem5/SystemC co-sim 已完成实测验证。
Stage-A ranking 等于 thesis-grade final claim。
release_ready_recommendation 等于最终 public authority。
```

---

## 13. Validators 与验证流程

### 13.1 Component / graph validation

```bash
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json
```

用途：

- 检查 component catalog；
- 检查 graph seed；
- 预览 projection；
- 防止 graph/template drift。

### 13.2 Next-stage simulator contract validation

```bash
python3 tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
```

用途：

- 检查 phase config；
- 检查 execution checklist；
- 检查 result schema；
- 检查 runner 对 cases、metrics、tie-band、promotion state 的实现是否漂移。

### 13.3 Release bundle validation

```bash
python3 tools/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json
```

用途：

- 检查 manifest 是否存在；
- 检查 projection review / stage-main recommendation 是否存在；
- 检查 artifact paths 是否指向真实文件；
- 检查 coverage / readiness 是否一致。

### 13.4 Regression tests

常用 regression tests：

```bash
python3 tools/benchmarks/test_run_systemc_architecture_family_dse_sweep.py
python3 tools/benchmarks/test_run_qe_next_stage_dse_phase.py
python3 tools/benchmarks/test_run_qe_system_design_adjudicator.py
```

这些 test 用于保证 runner/schema/adjudicator 行为没有被无意破坏。它们不是 performance benchmark。

---

## 14. Troubleshooting

### 14.1 Row 变成 `explain-only`

常见原因：

```text
missing_fast_layer_metrics
ranking_grade_ready_false
baseline_missing
candidate_missing
source_kind = stub
```

检查：

- 是否执行了模型；
- 是否生成完整 metrics；
- baseline 是否可用；
- 是否只是 projection/scaffold row；
- row 的 `support_status` 和 `fidelity_class` 是否允许 promotion。

### 14.2 `F4/F5/custom` 被误读为 supported

检查字段：

```text
candidate_family
runtime_projection_family
support_status
fidelity_class
support_evidence.executor_claim_allowed
support_evidence.projection_reason
support_evidence.native_runtime_evidence_path
```

如果：

```text
support_status = projection_only
executor_claim_allowed = false
```

则只能作为 projection evidence。

### 14.3 Candidate identity 丢失

优先使用：

```text
candidate_family
architecture_template_id
candidate_id
design_axes
```

不要用 `design_point.family` 覆盖 `candidate_family`。`design_point.family` 在迁移期可以作为 legacy/runtime field 保留，但新消费者应优先读 `candidate_family`。

### 14.4 Release bundle validator 失败

常见原因：

- phase summary 缺字段；
- manifest 指向不存在的 artifact；
- projection review 未生成；
- stage-main recommendation 未生成；
- accurate coverage 不 ready；
- output-dir 与 validator summary path 不一致。

处理方式：

1. 先读 `qe_next_stage_artifact_bundle_manifest.json`；
2. 再读 `qe_next_stage_dse_phase_summary.json`；
3. 检查每个 artifact path 是否存在；
4. 只修复由当前 run 造成的问题，不重写 unrelated historical artifacts。

### 14.5 Generalization mismatch

`generalization_coverage` 默认 nonblocking。它用于 broader confidence，不自动推翻主链，但必须记录在：

```text
phase summary
artifact bundle manifest
release delivery spec / memo
```

如果 mismatch 数量升高，应降低外推语气，而不是修改 mainline evidence。

### 14.6 SystemC / build 问题

默认 fallback build：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

real SystemC build 需要：

```bash
-DQE_BAND_SOLVER_USE_SYSTEMC=ON
-DSYSTEMC_HOME=<your-systemc-prefix>
```

如果环境没有 real SystemC，可使用 fallback compatibility layer。fallback run 仍是 timed-functional/proxy evidence，不是 RTL validation。

---

## 15. 当前限制

当前工具链仍有以下限制：

```text
Stage-A outputs are evidence only.
F4/F5/custom remain mostly projection/scaffold unless future native executor evidence exists.
gem5/SystemC co-sim remains reserved/stub metadata in the current repo state.
Runnable model remains timed-functional/proxy-level, not numerically faithful full DFT and not RTL.
Board/whole-node measured closure is not automatically unlocked by DSE outputs.
GPU/FPGA decisive comparison requires fairness, correctness, power, and adjudicator gates.
```

这些限制不妨碍 DSE 框架作为辅助工具使用。它们只限制 claim strength。

---

## 16. `dse_v2` / future heuristic search 的位置

若使用 Bayesian optimization、surrogate search、AI-assisted proposal 等未来机制，它们只能作为：

```text
candidate proposal layer
```

它们不能替代：

- result schema；
- phase config；
- fidelity ladder；
- accurate-layer correctness；
- contract validators；
- adjudicator authority。

任何 heuristic / BO 产生的 point，必须重新投影回同一 schema，经过同一 DSE/fidelity/validation/adjudicator 链，才可以成为 claim-relevant evidence。

---

## 17. 新接手者推荐路径

如果从零接手该 DSE 工具，推荐按下面顺序：

1. 阅读 `docs/README.md` 的 adjudicator reading rule。
2. 阅读 `docs/benchmarks/qe_stepwise_system_dse_workflow_index_v0.md`。
3. 阅读 `docs/benchmarks/qe_dse_fidelity_ladder_and_execution_loop_v0.md`。
4. 阅读 `docs/benchmarks/qe_equal_candidate_dse_design_manual_v0.md`。
5. 阅读 `docs/benchmarks/qe_next_stage_release_delivery_spec_v0.md`。
6. 阅读 `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`。
7. 阅读 `model/qe_band_solver_model/README.md`。
8. 运行 `./quick_start_dse.sh`。
9. 运行必要的 validator。
10. 只在 evidence/claim boundary 清楚后再写报告或继续开发。

---

## 18. 最小可复现 runbook

### 18.1 Smoke

```bash
./quick_start_dse.sh
```

### 18.2 Build model

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

### 18.3 Run Stage-A sweep

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_sweep_results
```

### 18.4 Run next-stage phase

```bash
python3 tools/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
```

### 18.5 Validate contracts

```bash
python3 tools/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
```

### 18.6 Validate release bundle

```bash
python3 tools/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json
```

### 18.7 Generate adjudicator memo

```bash
python3 tools/benchmarks/run_qe_system_design_adjudicator.py \
  --help
```

Use the script-specific help and the adjudicator input manifest contract to wire concrete evidence inputs. Do not infer final authority from upstream runner outputs.

---

## 19. Manual-level acceptance checklist

在使用本手册指导交付或继续工作前，检查：

- [ ] 是否明确当前 output 是 evidence、release bundle 还是 adjudicator authority？
- [ ] 是否保留 `candidate_family` 与 `runtime_projection_family` 的区别？
- [ ] 是否没有把 projection-only row 写成 native executor？
- [ ] 是否没有把 `executor_claim_allowed` 写成 public claim permission？
- [ ] 是否记录了 workload、source kind、fidelity、run command 和 output directory？
- [ ] 是否运行了相关 validators？
- [ ] 是否区分 `best_trusted_point` 与 `best_performance_candidate`？
- [ ] 是否没有越过 fairness、correctness、rewrite、observability contracts？
- [ ] 是否由 adjudicator memo 决定最终 claim language？

---

## 20. 一句话总结

这套 DSE 框架不是自动宣布最优架构的工具，而是一个：

```text
用统一 workload、统一 candidate identity、统一 fidelity ladder、统一 artifact chain、统一 contract boundary，
来辅助架构候选筛选、解释、验证和交付的 evidence management 工具。
```

其核心产物不是单个排名，而是：

```text
candidate set
+ metrics
+ correctness evidence
+ coverage state
+ projection/readiness explanation
+ release artifact bundle
+ adjudicator-compatible evidence
```

最终原则保持不变：

```text
DSE 负责组织证据；adjudicator 负责解释权限。
```
