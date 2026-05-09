## Why

现有 `docs/architecture/generic_dse_framework_design_spec_v1.md` 已经覆盖通用 DSE 框架的主要构想，但更像实现笔记与修复记录的合集，缺少面向冻结、评审、实现验收的能力边界、接口契约、需求场景、验证矩阵和状态分层。更重要的是，现有表述还没有把 `gem5+SystemC/SystemC 仿真反馈闭环` 定义为最终可信 DSE 结论的必要条件。该变更将其提升为 OpenSpec 驱动的专业系统规范，使后续实现、代码审查、DSE 论文/报告取证和跨后端验证可以围绕明确契约推进。

## What Changes

- 将通用 DSE 复杂系统拆分为可验收的能力规范：IR/工作负载契约、加速器/系统描述、多保真 DSE 评估、通用仿真后端、DFT/QE 特化适配。
- 为每个能力定义可测试的 MUST/SHALL 级需求、典型场景、失败/降级语义和可复现验证入口。
- 明确 L1/L2/L3/L4 保真度边界、晋升策略、指标一致性、校准证据和不确定性报告要求。
- 明确 Generic SystemC JSON IPC、C++ 后端、Python bridge 与 gem5 GenericAccel 的状态边界，避免把 stub/prototype 描述成完成态。
- 将 DFT/QE 用例限定为通用框架上的参考 workload，而非硬编码主路径；保留当前 Host+FPGA/CIM 研究主线所需的算子、数据流和验证要求。
- 增加端到端 DSE workflow 契约：从 workload、architecture catalog、mapping search、gem5+SystemC simulation、evidence export 到 final analysis report 必须完整跑通。
- 增加闭环选择最佳架构要求：低保真模型只负责初筛候选，SystemC/gem5+SystemC 仿真结果必须反哺搜索并决定最终可信 architecture/mapping。
- 不引入新的运行时依赖；本变更先产出规范与实施任务，不直接修改核心代码。

## Capabilities

### New Capabilities
- `generic-dse-ir-contract`: 通用 DSE 的 ComputeGraph、TaskGraph、Architecture、Execution 四级 IR、序列化和状态转移契约。
- `accelerator-system-description`: CPU/GPU/FPGA/ASIC/CIM/分布式系统的自描述能力模型、拓扑、资源、功耗、面积和通信语义。
- `multi-fidelity-dse-evaluation`: 搜索空间、设计点、评估结果、多目标排序、L1/L2/L3/L4 保真度晋升和验证闭环。
- `generic-simulation-backend`: Python bridge、JSON IPC、Generic SystemC backend、算子模型注册、trace/resource 输出和 gem5 GenericAccel 集成边界。
- `dft-qe-workload-adapter`: QE/DFT SCF 参考工作负载到通用 IR 的降维/映射/指标校准和回归验证契约。
- `end-to-end-dse-workflow`: 端到端 DSE 流水线、run artifact、claim evidence、最终分析报告和可复现执行契约。

### Modified Capabilities

- None; OpenSpec 当前没有既有能力规格，本变更创建首批规范基线。

## Impact

- Affected documentation: `docs/architecture/generic_dse_framework_design_spec_v1.md`, future architecture/spec handoff notes.
- Affected implementation areas for later tasks: `dse_v2/core/ir/`, `dse_v2/core/architecture/`, `dse_v2/dse/`, `dse_v2/backends/generic_systemc_bridge.py`, `model/generic_sim_backend/`, `gem5_integration/src/dev/generic_accel/`.
- Affected validation: `dse_v2/tests/`, Generic SystemC backend build/regression, gem5+SystemC full QE-flow pilot, DFT/QE workload regression and architecture-difference probes.
- No breaking API change is proposed at the specification stage; implementation may later require explicit migration tasks if existing return types or schema fields diverge from the new contracts.
