# 文档阅读入口

本目录只保留阅读导航职责。全局设计、子系统设计、运行手册、历史记录和变更提案必须分层阅读，不能互相替代。

## 1. 推荐阅读顺序

| 顺序 | 文档 | 角色 |
| --- | --- | --- |
| 1 | `docs/architecture/generic_dse_global_system_design_v0.md` | Generic DSE 与 SystemC/gem5+SystemC 证据闭环的全局设计入口。 |
| 2 | `docs/architecture/generic_dse_framework_design_spec_v2.md` | Generic DSE 子系统详细设计，补充数据模型、Step1/Step2/Step3 和信任边界。 |
| 3 | `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md` | 操作手册，说明如何运行、审查 artifacts 和避免 overclaim。 |
| 4 | `dse_v2/README.md` | 当前实现入口，说明代码目录、主要命令和测试。 |
| 5 | `openspec/HANDBOOK.md` | OpenSpec 治理规则，说明 active change、spec 和 archive 的职责。 |

## 2. 文档分层

| 层级 | 用途 | 代表文件 |
| --- | --- | --- |
| 全局设计 | 定义系统目标、范围、模块边界和证据流。 | `docs/architecture/generic_dse_global_system_design_v0.md` |
| 子系统设计 | 展开某个子系统的数据模型、接口和状态机。 | `docs/architecture/generic_dse_framework_design_spec_v2.md` |
| 操作手册 | 给执行者说明命令、artifacts、验证方法和常见误读。 | `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md` |
| 实现入口 | 给开发者说明代码目录和最小运行命令。 | `dse_v2/README.md` |
| 变更提案 | 记录有边界的设计变更、任务和归档历史。 | `openspec/changes/*` |
| 历史证据 | 保留旧阶段、旧假设和实验记录。 | `docs/overview/*`、`docs/benchmarks/results/*` |

## 3. Authority 规则

- 全局设计文档定义架构边界，但不替代运行结果。
- DSE、projection、optimizer、pilot run 只能产生 evidence 或 candidate。
- `claim_validation.json` 和 adjudicator 规则决定哪些结论可以对外声明。
- OpenSpec change 只描述一个有边界的增量，不能充当全局设计文档。
- 已完成的 OpenSpec change 应进入 `openspec/changes/archive/`，不要长期留在 active 列表。

## 4. 旧 QE 系统文档

以下文档仍然有效，但它们是 DFT/QE 研究原型的系统级资料，不再作为 Generic DSE 的唯一入口：

- `docs/architecture/system_design_master_spec_v0.md`
- `docs/architecture/system_interface_contract_v0.md`
- `docs/architecture/system_exception_and_flow_control_contract_v0.md`
- `docs/control/long_control_word_isa_v0.md`
- `docs/cim/cim_macro_block_and_timing_v0.md`
- `model/qe_band_solver_model/README.md`

需要审查 QE/FPGA/CIM 旧主线时，从这些文档开始；需要审查通用 DSE 与仿真证据闭环时，从第 1 节开始。
