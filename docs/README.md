# Docs Index

当前文档链已经收束为：**一份系统级主规范 + 少量支撑合同 + 模型/调研证据**。

## 0. Review Shortcut

如果只是做设计审核，优先看：

- `docs/architecture/system_design_master_spec_v0.md`
- `docs/architecture/qe_system_optimized_delta_20260413.md`
- `docs/architecture/system_interface_contract_v0.md`
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
- `docs/control/long_control_word_isa_v0.md`
- `docs/cim/cim_macro_block_and_timing_v0.md`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`
- `docs/benchmarks/qe_dse_framework_user_manual_v0.md`
- `docs/benchmarks/qe_unified_dse_framework_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`
- `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`
- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`
- 根目录 `README.md` 里的 `Key Design Files` 小节

其中如果问题涉及“当前到底谁有资格下最终结论”，请先读 `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`。

当前 frozen 读法是：

- adjudicator memo 是唯一 decision authority
- DSE、projection、GPU annex、phase closure、stage-main recommendation 都只是 evidence inputs
- Stage A 可用，但只能做 bounded / guarded / projection-grade 结论，不能当 thesis-grade final authority
- Stage B 只有在 GPU baseline、phase closure、board closure、ranking stability、workload-group admissibility 这些 closure 真正闭合后，才允许更强 public claims
- `model/qe_band_solver_model/README.md` 记录的是当前 runnable model truth，不是第二套 authority surface

## 1. Canonical Path

- `docs/overview/project_development_timeline.md`：完整开发时间线与阶段结论
- `docs/overview/qe_project_implementation_architecture_and_plan_v0.md`：当前项目级实现架构、workstream、phase roadmap 与 validation gate 总规划
- `docs/overview/agent_handoff_20260312.md`：仓库级 handoff / 工作约束
- `docs/overview/qe_subspace_sampling.md`：`QE` 采样与真实样本背景
- `docs/architecture/system_design_master_spec_v0.md`：当前唯一系统级主规范
- `docs/architecture/qe_system_optimized_delta_20260413.md`：最近一轮 optimized system-level redesign 相对主规范/旧读法的增量说明
- `docs/architecture/system_interface_contract_v0.md`：系统接口与 route 合同
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`：异常、流控与恢复合同
- `docs/cim/cim_macro_block_and_timing_v0.md`：`CIM` 宏结构、计算/存储流程主文档
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`：phase-1 QE-only thesis 的 workload-group 与 same-correctness / same-tolerance 准入合同
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`：`CPU + GPU` / `CPU + FPGA` 的 fairness、shared-rewrite 与 whole-node power 边界合同
- `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md`：algorithm rewrite 的分类、GPU applicability 与 decisive baseline eligibility 合同
- `docs/benchmarks/qe_algorithm_rewrite_manifest_template_v0.json`：algorithm rewrite manifest 的 machine-readable template
- `docs/benchmarks/init_qe_phase1_artifact_bundle.py`：phase-1 baseline / board bundle 的 scaffold helper
- `docs/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py`：对 incoming `CPU + GPU` baseline 目录做 `deferred / reference_only / thesis_eligible` 归类，并用 `decisive_for_case` 标记当前 case 最优 row 的 helper
- `docs/benchmarks/assess_qe_phase1_evidence_closure.py`：按 frozen phase-1 lane 评估当前 GPU/board artifact 是否已形成 thesis-count candidate
- `docs/benchmarks/render_qe_phase1_evidence_closure_md.py`：把 closure JSON 渲染成可读 Markdown 摘要
- `docs/benchmarks/run_qe_phase1_closure_pipeline.py`：一条命令生成 phase-1 closure JSON + Markdown
- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`：phase-1 `CPU + GPU` baseline 的实际采集 runbook；内含从 template 生成 baseline bundle 的最小命令示例
- `docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json`：`CPU + GPU` baseline run manifest 的 machine-readable template
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`：simulator/DSE ↔ FPGA board 的 observability / calibration 合同；内含 board bundle 模板实例化与 validator 示例
- `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`：当前 adjudicator authority freeze；明确 adjudicator memo 是唯一 decision authority，说明 Stage A / Stage B activation split，以及 allowed / guarded / forbidden claim policy
- `docs/benchmarks/check_qe_phase1_artifact_contracts.py` / `docs/benchmarks/test_qe_phase1_artifact_contracts.py` / `docs/benchmarks/test_init_qe_phase1_artifact_bundle.py` / `docs/benchmarks/test_assess_qe_cpu_gpu_baseline_readiness.py` / `docs/benchmarks/test_assess_qe_phase1_evidence_closure.py` / `docs/benchmarks/test_render_qe_phase1_evidence_closure_md.py` / `docs/benchmarks/test_run_qe_phase1_closure_pipeline.py`：phase-1 artifact contract / scaffold / readiness / closure 的 validator 与 regression tests
- `docs/benchmarks/qe_dse_framework_user_manual_v0.md`：当前 DSE 辅助框架的完整用户手册；说明输入、运行、输出、验证、claim boundary 与 adjudicator 读取规则
- `docs/benchmarks/qe_unified_dse_framework_v0.md`：Unified DSE Framework v0 的 bounded architecture / plan；它是 Stage-A evidence-only、adjudicator-ready 的组织层，不替代现有 runner 或 adjudicator
- `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`：DSE/bootstrap result bundle 的 machine-readable schema
- `docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`：当前 family sweep / bootstrap bundle 生成入口；用于把上述 contract/template id 写入结果
- `docs/benchmarks/run_unified_dse_v0.py`：Unified DSE v0 的薄 CLI wrapper；默认生成 bounded evidence package，`SystemC` 执行仍需显式 opt-in，implementation backend 仅限 stub / reserved / projection-only 口径
- `docs/benchmarks/qe_next_stage_release_delivery_spec_v0.md`：当前 next-stage release-facing artifact chain 的读取顺序、准入条件、generalization 状态与复现方式
- `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`：当前 next-stage DSE 的五层策略，以及 future heuristic / AI DSE 的接入条件与演进路线
- `model/qe_band_solver_model/README.md`：可运行系统模型入口

### 1.1 Adjudicator reading rule

对当前 benchmark / release-facing 文档链，统一按下面的 authority rule 阅读：

1. `run_systemc_architecture_family_dse_sweep.py`、`run_unified_dse_v0.py`、projection helpers、GPU annex、phase closure、stage-main recommendation 都只能提供 evidence
2. 只有 adjudicator memo 能把这些 evidence 合成为 outward decision
3. Stage A 和 Stage B 共用同一份 memo schema，不共用同一套 claim permission
4. 如果没有看到 closure-bound Stage B gate 被满足，就不要把任何当前结论读成 thesis-grade final authority
5. runnable model 的 timed-functional / proxy truth 仍然成立，所以任何“当前 family 看起来更好”的表述都必须服从 adjudicator claim policy，而不是自己升级成 final authority

## 2. Support Contracts

- `docs/control/`：以 `docs/control/long_control_word_isa_v0.md` 为主的控制侧合同；其中 `LCW`、descriptor/template/replay 边界，以及 `object handle / resident buffer / version` 术语都以该文件为主，再配 `QE` lowering / `BODY_04` / `BODY_10` 等软件相关支撑合同
- `docs/cim/`：`CIM` 可实现性、驻留上下文、近存协同、数字乘法流程等支撑文档
- `docs/architecture/qe_band_solver_systemc_overview_20260325.md`：当前 `SystemC` 骨架说明
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`：当前事务语义
- `docs/architecture/qe_full_dft_systemc_extension_outline_v0.md`：从 band-solver 扩到 full-SCF 的行为级路线
- `docs/architecture/qe_ic_component_graph_input_template_v1.md`：architecture-exploration / performance-estimation 平台的固定 `component template` 与 `graph_spec` 最小模板
- `docs/architecture/qe_ic_component_catalog_system_level_v1.json`：system-level component catalog 的最小机器可读实例
- `docs/architecture/qe_ic_graph_seed_system_level_v1.json`：canonical `F2` balanced graph seed 的最小机器可读实例
- `docs/architecture/qe_ic_component_graph_brownfield_binding_v1.md`：`v1` component/graph 对 brownfield simulator 与 artifact chain 的绑定说明
- `docs/architecture/qe_ic_component_graph_projection_v1.md`：`graph/component -> design_point + SystemRunConfig` 的 projection / adapter 规格，以及当前 wave 1 helper ownership / authority boundary 说明
- `docs/benchmarks/qe_ic_graph_projection_utils.py` / `docs/benchmarks/test_qe_ic_graph_projection_utils.py`：当前可复用 benchmark-layer projection/helper 语义与其 regression coverage；供 checker 和 frontdoor 复用，但不接管 release-facing authority
- `docs/benchmarks/check_qe_ic_component_graph_v1.py` / `docs/benchmarks/test_check_qe_ic_component_graph_v1.py`：对 `v1` component catalog 和 graph seed 做一致性检查、projection 预览，并消费 helper 已抽出的 `system_level_v1` 语义
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`：当前 smoke run 结果

## 3. Evidence

- `docs/survey/`：外部路线与软件/行业调研
- `docs/survey/system_level_modeling_methods_and_tools_reference_20260402.md`：系统级建模方法、建模层次与常用工具参考
- `docs/benchmarks/`：工作负载、trace、baseline 与实验脚本
- `docs/benchmarks/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`：当前 `CPU only / CPU + GPU / CPU + FPGA` shell-level 执行状态快照
- `docs/qe_inputs/`：`QE` 输入样例
- `docs/patches/`：`QE` 采样 patch

## 4. Removed Duplicates

原先重复承担系统级角色的“问题定义文档、模块实现展开件、审阅导航包”，以及二级重复的 `LCW` 模块拆解说明、object-handle/resident-buffer 术语说明、`CIM` 可实现性说明、descriptor/template-replay 控制展开文档，其稳定内容已经分别并入 `docs/architecture/system_design_master_spec_v0.md`、`docs/cim/cim_macro_block_and_timing_v0.md` 与 `docs/control/long_control_word_isa_v0.md`。
