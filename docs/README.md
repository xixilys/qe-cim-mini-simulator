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

## 5. 文档清理与治理

本仓库当前的文档基线是 170 个 Markdown 文件，632 个 JSON 文件。这个基线说明 docs 树里同时存在叙述性文档、机器可读契约和大量证据文件，清理时不能把它们一概视为“可移动杂项”。

### 5.1 需要稳定保留的 JSON 入口

- `docs/architecture/` 下的 contract、schema、template、catalog JSON 是活跃接口的一部分，默认必须保留在原路径。
- `docs/benchmarks/` 下的 contract、schema、template、catalog JSON 也是活跃接口的一部分，除非所有引用和工具默认值都已同步更新，否则不要挪动。
- 典型稳定路径包括 `docs/architecture/qe_ic_component_catalog_system_level_v1.json`、`docs/architecture/qe_ic_graph_seed_system_level_v1.json`、`docs/architecture/qe_ic_graph_seed_templates_v0.json`、`docs/architecture/qe_ic_graph_schema_v0.json`、`docs/architecture/architecture_template_schema_v1.json`，以及 `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json`、`docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`、`docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json`、`docs/benchmarks/qe_ic_full_flow_phase_config_v0.json`、`docs/benchmarks/qe_microarchitecture_catalog_v0.json`、`docs/benchmarks/qe_microarchitecture_catalog_freeze_manifest_v0.json`、`docs/benchmarks/gpu_case_list_v0.json`。

### 5.2 证据目录不是随机杂项

- `docs/benchmarks/results/` 是生成证据、历史结果、trace bundle 和可复现实验产物的保留区。
- `docs/benchmarks/testdata/` 是测试夹具和 adjudicator 输入，不是随手堆放的临时文件夹。
- `docs/benchmarks/results/` 下的 timestamped result 文件、QE traces 和 dumps 不能直接改写。
- 任何生成证据的迁移或删除，都需要先完成引用扫描，再获得明确的用户批准。

### 5.3 当前热点

- `docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/graph_evidence/` 是当前最集中的 JSON 热点，包含 540 个 graph JSON 证据文件。
- 这批文件默认应原地保留，除非后续有明确批准的 archive move，并且同步更新所有引用。

### 5.4 以后做移动前先查什么

1. 先确认目标目录是 evidence、fixture，还是 active contract。
2. 再用 `rg` 扫描所有引用、工具默认值和文档入口。
3. 只有在引用链已经更新完毕后，才考虑移动、重命名或归档。

### 5.5 快速验证清单

```bash
rg --files docs | rg '\.md$' | wc -l
rg --files docs | rg '\.json$' | wc -l
rg --files docs/benchmarks/results/systemc_architecture_family_dse_bootstrap | rg 'graph_evidence|adjudicator|\.json$|\.md$'
rg -n 'graph_evidence|docs/benchmarks/results/|docs/benchmarks/testdata/' docs/README.md docs/benchmarks/results/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/graph_evidence/README.md docs/architecture/architecture_comparison/results/README.md
rg --files tools/benchmarks | rg 'check_qe_ic_component_graph_v1.py|run_systemc_architecture_family_dse_sweep.py|summarize_qe_subspace_trace.py'
```
