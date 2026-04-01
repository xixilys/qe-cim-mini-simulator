# Docs Index

当前文档链已经收束为：**一份系统级主规范 + 少量支撑合同 + 模型/调研证据**。

## 0. Review Shortcut

如果只是做设计审核，优先看：

- `docs/architecture/system_design_master_spec_v0.md`
- `docs/architecture/system_interface_contract_v0.md`
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
- `docs/control/long_control_word_isa_v0.md`
- `docs/cim/cim_macro_block_and_timing_v0.md`
- `model/qe_band_solver_model/README.md`
- `model/docs/qe_band_solver_smoke_run_20260326.md`
- 根目录 `README.md` 里的 `Key Design Files` 小节

## 1. Canonical Path

- `docs/overview/project_development_timeline.md`：完整开发时间线与阶段结论
- `docs/overview/agent_handoff_20260312.md`：仓库级 handoff / 工作约束
- `docs/overview/qe_subspace_sampling.md`：`QE` 采样与真实样本背景
- `docs/architecture/system_design_master_spec_v0.md`：当前唯一系统级主规范
- `docs/architecture/system_interface_contract_v0.md`：系统接口与 route 合同
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`：异常、流控与恢复合同
- `docs/cim/cim_macro_block_and_timing_v0.md`：`CIM` 宏结构、计算/存储流程主文档
- `model/qe_band_solver_model/README.md`：可运行系统模型入口

## 2. Support Contracts

- `docs/control/`：以 `docs/control/long_control_word_isa_v0.md` 为主的控制侧合同；其中 `LCW`、descriptor/template/replay 边界，以及 `object handle / resident buffer / version` 术语都以该文件为主，再配 `QE` lowering / `BODY_04` / `BODY_10` 等软件相关支撑合同
- `docs/cim/`：`CIM` 可实现性、驻留上下文、近存协同、数字乘法流程等支撑文档
- `docs/architecture/qe_band_solver_systemc_overview_20260325.md`：当前 `SystemC` 骨架说明
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`：当前事务语义
- `docs/architecture/qe_full_dft_systemc_extension_outline_v0.md`：从 band-solver 扩到 full-SCF 的行为级路线
- `model/docs/qe_band_solver_smoke_run_20260326.md`：当前 smoke run 结果

## 3. Evidence

- `docs/survey/`：外部路线与软件/行业调研
- `docs/benchmarks/`：工作负载、trace、baseline 与实验脚本
- `docs/qe_inputs/`：`QE` 输入样例
- `docs/patches/`：`QE` 采样 patch

## 4. Removed Duplicates

原先重复承担系统级角色的“问题定义文档、模块实现展开件、审阅导航包”，以及二级重复的 `LCW` 模块拆解说明、object-handle/resident-buffer 术语说明、`CIM` 可实现性说明、descriptor/template-replay 控制展开文档，其稳定内容已经分别并入 `docs/architecture/system_design_master_spec_v0.md`、`docs/cim/cim_macro_block_and_timing_v0.md` 与 `docs/control/long_control_word_isa_v0.md`。
