# Generic DSE 全局系统设计 v0

> **状态：** 当前 Generic DSE 与 SystemC/gem5+SystemC 证据闭环的全局设计入口。  
> **范围：** 文档定义系统边界、模块职责、数据流、证据边界和扩展点。详细字段和实现细节见子系统设计与代码。  
> **非目标：** 本文不替代 OpenSpec change、不替代运行手册、不声明任何实验结果。

## 1. 系统目标

本系统的目标是构建一个面向异构计算系统的 evidence-backed Design Space Exploration（DSE）框架。它接收不同领域的 workload，经由统一 IR、架构候选、映射搜索和高保真仿真，输出带证据链的设计结论。

系统必须同时满足 3 个约束：

- **Domain-neutral + vertical proof：** core schema 不依赖 DFT/QE 或任何单一应用字段；当前用 DFT→FPGA 作为主证明 reference profile/importer，其他 workload 通过同一合同扩展。
- **Evidence-backed：** candidate、prediction、simulation、claim 必须分层，不能把低保真预测写成最终结论。
- **Replayable：** Step1、Step2、Step3 的关键 artifacts 必须落盘，后续步骤不得依赖隐藏 Python 进程状态。

## 2. 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                      Generic DSE System                      │
├─────────────────────────────────────────────────────────────┤
│ Step1: Workload Layer                                        │
│   profiles/importers -> WorkloadPackage -> ComputeGraph -> lowering │
├─────────────────────────────────────────────────────────────┤
│ Step2: Architecture and Mapping Layer                        │
│   architecture catalog -> DesignPoint -> mapping candidates   │
├─────────────────────────────────────────────────────────────┤
│ Step3: Simulation Evidence Layer                             │
│   SystemC / gem5+SystemC -> verdict -> evidence bundle        │
├─────────────────────────────────────────────────────────────┤
│ Reporting and Claim Layer                                    │
│   final report -> claim validation -> adjudicator inputs      │
└─────────────────────────────────────────────────────────────┘
```

未来的 HW/SW co-debug 和系统测试能力应作为侧车层接入：

```text
Debug/System Test Layer
    -> consumes run artifacts
    -> captures event timeline and traces
    -> emits diagnostic evidence
    -> may be promoted only through claim validation
```

## 3. 模块职责

| 模块 | 输入 | 输出 | 不能做的事 |
| --- | --- | --- | --- |
| Workload profile/importer | domain source、trace、外部 IR | `WorkloadPackage`、`ComputeGraph` | 不能修改 core schema 来适配单一领域。 |
| Graph lowering | source graph、workflow metadata | executable graph 或诊断报告 | 不能伪造 full-workload coverage。 |
| Architecture catalog | family、component、binding、constraints | architecture instance | 不能把无 binding 架构写成 trusted candidate。 |
| Mapping/search | executable graph、architecture、policy | candidate、screening、promotion decision | 不能输出 final winner。 |
| Simulation backend | replayable handoff artifacts | SystemC/gem5 evidence、runtime metrics | 不能绕过 proof gate。 |
| Evidence writer | backend result、proof、artifacts | manifest、verdict、claim validation | 不能把 diagnostic success 升级为 public claim。 |
| Registry | campaign、trial、artifact refs | 可查询 ledger | 不能成为调试编排器或 decision authority。 |

## 4. Step 流程

### 4.1 Step1：Workload ingestion

Step1 把领域输入转换为可审计 artifacts：

- `workload_package.json`
- `workload_graph.json`
- `graph_lowering_report.json`
- 可选 `executable_graph.json`

Step1 的核心验收标准是：后续流程可以只读这些 artifacts，而不依赖 importer 进程内状态。

### 4.2 Step2：Architecture and mapping

Step2 读取 Step1 artifacts 和 architecture catalog，生成可重放候选：

- `architecture.json`
- `design_point.json`
- `mapping_legality_matrix.json`
- `mapping_seed_set.json`
- `mapping_candidates.jsonl`
- `promotion_decisions.jsonl`
- Step3 handoff directory

Step2 只决定候选是否值得进入仿真，不产生最终可信结论。

### 4.3 Step3：Simulation evidence

Step3 读取 Step2 handoff artifacts，构造 backend request，并运行 L3 SystemC 或 L4 gem5+SystemC 路径。

Step3 必须输出：

- `step3_status.json`
- `simulation_request.json`
- backend result artifacts
- `manifest.json`
- `verdict.json`
- `final_report.json` / `final_report.md`
- `claim_validation.json`

如果候选缺少 binding、coverage、proof 或 required artifacts，Step3 必须阻止其进入 trusted ranking。

## 5. Evidence 与 claim 边界

系统采用下面的信任分层：

| 层级 | 作用 | 是否可支撑最终排名 |
| --- | --- | --- |
| L1 analytical | 快速估算、剪枝、候选提名 | 否 |
| L2 TLM / surrogate | 中等保真筛选、uncertainty hint | 否 |
| L3 standalone SystemC | 单机可重放 timing/resource evidence | 条件允许 |
| L4 gem5+SystemC | 软件可见 descriptor/request/completion proof | 条件允许 |
| Debug/system-test trace | 诊断、定位、复现实验 | 默认否 |

可信 claim 必须同时满足：

- artifacts 存在且可解析；
- `verdict.json` 允许对应 claim；
- `claim_validation.json` 中 evidence id 可回溯；
- 对 L4 claim，`gem5_l4_proof.json` 通过；
- adjudicator 或等价规则允许对外表述。

## 6. OpenSpec 与设计文档的关系

全局设计文档描述系统全貌。OpenSpec 描述有边界的增量变更。

| 文档 | 正确用途 |
| --- | --- |
| 本文 | 全局架构、模块边界、证据边界。 |
| `generic_dse_framework_design_spec_v2.md` | Generic DSE 子系统详细设计。 |
| `generic_dse_simulation_system_handbook_v1.md` | 操作手册和 review checklist。 |
| `openspec/specs/*/spec.md` | 已接受能力的规范要求。 |
| `openspec/changes/*` | 单次变更提案、设计和任务。 |

完成的 OpenSpec change 应归档，不应长期留在 active 列表中充当说明文档。

## 7. Debug/System Test 扩展点

HW/SW co-debug 和复杂系统测试不进入 optimizer/search，也不把 Step3 改成 debugger。推荐新增侧车层：

- `DebugSession`：一次诊断会话；
- `SystemTestScenario`：声明 workload、backend、descriptor、ROI marker 和 expected invariants；
- `EventTimeline`：统一 software ROI、command descriptor、gem5 event、SystemC event；
- `CorrelationRecord`：关联软件 marker、descriptor、simulator event 和 hardware interval；
- `DebugEvidenceBundle`：记录 debug artifacts，默认 `diagnostic_only`。

Debug evidence 只有通过 repeatability、provenance、claim validation 和 adjudication 后，才能升级为 ranking evidence。

## 8. Distributed compatibility

当前仓库只有分布式拓扑和字段预留，不具备 distributed simulation runtime。现阶段只能保留兼容字段：

- `node_id`
- `clock_domain`
- `timebase`
- `trace_partition_id`
- `simulator_adapter`
- `failure_domain`

不得声称系统已支持跨节点分布式仿真、HLA/RTI federation 或 optimistic rollback。

## 9. 当前实现状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Generic workload profile/importer | 已实现部分 | 包含 `generic_json` 和 optional QE reference importer path。 |
| Step2 mapping handoff | 已实现部分 | 已有 persisted artifacts 和 promotion boundary。 |
| Step3 evidence flow | 已实现部分 | 已有 full-flow evidence writer 和 report/claim validation。 |
| L3 SystemC backend | 已实现部分 | 可生成 timing/resource evidence。 |
| L4 gem5+SystemC | proof-gated | 只有 proof artifacts 通过时才可信。 |
| Experiment registry | 已实现基础 | 存储 campaign/trial 和 artifact refs。 |
| Debug/System Test Layer | 未实现 | 仅作为设计扩展点。 |
| Distributed runtime | 未实现 | 只有数据模型和未来兼容字段。 |

## 10. 支撑文档

- `docs/architecture/generic_dse_framework_design_spec_v2.md`
- `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`
- `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md`
- `docs/overview/archive/docs/overview/archive/gem5_systemc_wsl_joint_debug_plan_20260427.md`
- `openspec/HANDBOOK.md`
