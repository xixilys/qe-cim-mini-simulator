# 通用 DSE 与仿真证据闭环系统手册 v1

> **文档版本：** v1.0  
> **日期：** 2026-05-11  
> **状态：** 操作手册与证据审查指南；全局设计入口见 `docs/architecture/generic_dse_global_system_design_v0.md`  
> **旧手册：** 应用专用历史材料已从 active tree 移除；如需单个 artifact，应从历史中定点恢复  
> **核心原则：** DSE 组织候选与证据；可信结论由 evidence、claim gate 和 adjudicator 共同约束。

---

## 0. 阅读规则与证据边界

本手册说明当前仓库中的通用 Design Space Exploration（DSE）与仿真证据闭环系统如何被运行、扩展和审查。全局架构以 `docs/architecture/generic_dse_global_system_design_v0.md` 为准；本文只保留执行规则、artifact 规则和 claim 边界。它面向 4 类读者：

1. 后续开发者：需要继续实现 workload profile/importer、architecture family、backend 或 optimizer。
2. 实验执行者：需要跑通 Step1、Step2、Step3 和反馈闭环。
3. 报告编写者：需要把 artifacts 组织成 advisor-facing 或论文阶段材料。
4. 审查者：需要判断某个结果是否能支撑可信 claim。

本手册的主身份是通用 DSE / 仿真证据闭环操作手册：

```text
generic workload package
  -> architecture and mapping search
  -> SystemC / gem5+SystemC simulation evidence
  -> feedback and convergence
  -> final report with claim validation
```

### 0.1 一句话规则

```text
Low-fidelity search proposes candidates.
High-fidelity simulation produces evidence.
Claim validation controls what can be said.
Adjudicator controls public decision authority.
```

### 0.2 不允许的读法

以下表述在当前仓库状态下不允许：

| 表述 | 原因 |
| --- | --- |
| “BO 找到了最终最佳架构” | BO / surrogate 只能是 candidate proposal layer。 |
| “Step2 输出了可信 winner” | Step2 只能输出 simulation-ready candidates。 |
| “SystemC 进程退出 0，所以结论可信” | 还必须检查 `verdict.json`、`claim_validation.json`、coverage 和 evidence ids。 |
| “单个 pilot 证明全局 Pareto frontier” | 单个 full-flow pilot 只能是 feasibility / timing evidence。 |
| “gem5+SystemC 已自动可信” | 必须有通过的 `gem5_l4_proof.json`。 |
| “应用专用字段是核心 IR 必需字段” | 应用/领域字段只能属于 profile/importer metadata，不是 core schema。 |
| “projection-only row 是 native executor result” | `projection_only` 只能用于解释、筛选或提名。 |

---

## 1. 系统总览

### 1.1 主流程

当前通用 DSE 主线应按下面的闭环理解：

```text
┌──────────────────────────────────────────────────────────────┐
│                        Generic DSE Loop                       │
├──────────────────────────────────────────────────────────────┤
│ Step1                                                        │
│   Workload source / trace / graph / importer input            │
│        ↓                                                      │
│   WorkloadPackage + ComputeGraph + graph lowering             │
│        ↓                                                      │
│ Step2                                                        │
│   Architecture catalog + DesignPoint + mapping search          │
│        ↓                                                      │
│   Promotion decision + replayable Step2 handoff artifacts      │
│        ↓                                                      │
│ Step3                                                        │
│   SystemC or gem5+SystemC simulation/evidence                  │
│        ↓                                                      │
│   verdict + final report + claim validation                    │
│        ↓                                                      │
│ Feedback                                                     │
│   ranking / Pareto / surrogate calibration / convergence       │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 分层模型

| 层级 | 作用 | 当前可信边界 |
| --- | --- | --- |
| Workload layer | 接入 domain source，生成 `WorkloadPackage` / `ComputeGraph` | 领域专用内容只能作为 profile/importer；DFT→FPGA 是当前主证明场景但不进入 core schema。 |
| Design-space layer | 定义 architecture family、component、binding 和 constraints | 无 binding 的 family 是 candidate-only。 |
| Mapping/search layer | 生成 legal mappings、候选和 promotion decision | 不能输出 trusted final claim。 |
| Simulation layer | 运行 L3 SystemC 或 L4 gem5+SystemC | L4 需要 `gem5_l4_proof.json` 通过。 |
| Evidence layer | 写出 manifest、verdict、report、claim validation | simulator success 不等于 claim success。 |
| Adjudication layer | 合成 public decision | 只有 adjudicator memo 能升级 public claim。 |

### 1.3 外部 DSE 系统给出的结构启发

| 外部系统 | 借鉴点 | 本项目中的落点 | 不复制的地方 |
| --- | --- | --- | --- |
| Timeloop / Accelergy | 分离 problem、architecture、mapping、energy model | `WorkloadPackage`、architecture catalog、mapping artifacts、calibration | 不把 mapper 输出直接当最终结论。 |
| MAESTRO | 显式表达 dataflow、reuse、occupancy | mapping legality、screening result、resource summary | 不把 DNN-only 术语变成 core schema。 |
| gem5 / SystemC / gem5-Aladdin | 系统级时序、软件可见 completion、proof artifacts | `gem5_l4_proof.json`、GenericAccel L4 proof gate | 不把 MMIO bring-up 写成 trusted co-sim。 |
| TVM / MetaSchedule | 统一 manual schedule、template search、自动搜索 | optimizer plugin 和 search-state artifact | 不复制 template/API fragmentation。 |
| OpenTuner / Optuna / HyperMapper | trial ledger、sampler/pruner、multi-objective search | experiment registry、candidate queue、Pareto archive | 不让 optimizer 代替 evidence gate。 |
| Ax / BoTorch | orchestration layer 与 BO engine 分离 | search engine 是 proposal layer，BoTorch 类能力可做插件 | 不把 BO 设计成唯一入口。 |

---

## 2. 当前能力矩阵

本章是防止 overclaim 的入口。写报告或继续开发前，先确认当前路径属于哪个状态。

| 子系统 | 状态 | 当前真实能力 | 必须保留的状态词 |
| --- | --- | --- | --- |
| `dse_v2` Step1/Step2/Step3 | implemented + partial | 已有 persisted workflow、generic IR、mapping handoff、Step3 evidence flow。 | `trusted_final_eligible`、`blocked_before_simulation`、`trusted_full_flow_evidence_emitted` |
| `tools/benchmarks/unified_dse` | planned / bounded scaffold | Stage-A evidence-only wrapper 和合同表面，不是最终 authority。 | `Stage-A evidence-only`、`stub`、`reserved`、`projection_only` |
| `model/generic_sim_backend` | implemented L3 backend | 支持 `standalone_systemc`、heterogeneous accelerators、graph execution、timing/resource metrics。 | `standalone_systemc`、`passed`、`failed`、`blocked` |
| `gem5_integration` generic accel | partial / blocked for L4 trust | 控制路径和 L4 proof harness 存在，但可信 L4 必须由 proof artifacts 支撑。 | `MMIO Timed Stub / L4 Blocked Prototype`、`gem5_l4_proof.json` |
| BO / Ax / BoTorch scripts | proposal / experimental | 可生成候选或 Pareto-like rows，但不能直接声明 trusted winner。 | `candidate proposal layer`、`predicted-only` |
| DFT/reference profiles | reference profile/importer / vertical proof lane | DFT→FPGA 可作为主证明场景进入 generic flow；其他历史材料仍需隔离。 | `reference importer`、`vertical proof lane`、`legacy lane` |

### 2.1 状态等级

| 等级 | 含义 | 是否可用于 trusted final ranking |
| --- | --- | --- |
| `implemented` | 有代码、artifact、测试或可运行路径 | 仍需 evidence gate。 |
| `partial` | 有部分实现，但缺 closure 或覆盖 | 否，除非当前 run 明确补齐缺口。 |
| `prototype` | 可演示机制或接口 | 否。 |
| `planned` | 文档或 OpenSpec 规划 | 否。 |
| `reserved` | 预留字段、预留 backend 或未来接口 | 否。 |
| `blocked` | 明确缺少依赖或 proof | 否。 |

---

## 3. 核心概念与术语

### 3.1 WorkloadPackage

`WorkloadPackage` 是进入通用 DSE 的 workload contract。它携带 workload id、family、source provenance、profile/importer id/version、claim boundary、domain metadata 和 graph payload。

核心规则：

- Core DSE 只能依赖 generic fields。
- Domain-specific metadata 归 profile/importer 所有。
- 应用/领域专用参数和节点名不能成为 core schema 必需字段。
- reduced、synthetic、trace-only、diagnostic-only workload 不能通过 full-workload trusted claim gate。

### 3.2 ComputeGraph

`ComputeGraph` 表示通用计算图。它应该支持：

- open `op_type`；
- nodes、edges、tensor/resource metadata；
- loops / streaming / dynamic constructs 的 bounds 或 summary；
- profile/importer-owned opaque metadata；
- source-to-executable graph lowering audit。

### 3.3 DesignPoint

`DesignPoint` 绑定 workload、architecture、mapping、scheduling policy、precision policy、fallback policy 和 objective directions。它必须能写入磁盘并被 Step3 重载，不能依赖隐藏 Python 进程状态。

### 3.4 Candidate identity 与 runtime projection

旧手册中最重要的防误读规则必须保留：

```text
candidate quality != evidence quality
```

| 字段 | 含义 |
| --- | --- |
| `candidate_family` | immutable architecture identity。 |
| `architecture_template_id` | candidate 的模板身份。 |
| `candidate_id` | row / design point 的唯一身份。 |
| `runtime_projection_family` | evaluator metadata，不是 architecture identity。 |
| `support_status` | 当前 evidence support 级别。 |
| `executor_claim_allowed` | 是否允许声称使用某个 executor/proxy path，不是 public claim permission。 |

`projection_only` row 可以用于筛选、解释或 nomination，但不能写成 native executor、board measurement 或 final performance claim。

---

## 4. Step1：workload ingestion 与 graph lowering

### 4.1 Step1 目标

Step1 的职责是把 domain source 归一化为可审计的 workload artifacts：

```text
domain input
  -> profile registry + importer registry
  -> WorkloadPackage
  -> ComputeGraph
  -> graph lowering report
  -> required coverage
```

### 4.2 Profile/importer registry

内建 profile/importer 可以包括：

| Entry | 角色 |
| --- | --- |
| `generic_json` importer | 通用 JSON / generated / hand-authored graph 输入。 |
| DFT/reference importers | DFT→FPGA 主证明 importer 或其他 reference/profile importer；不属于 core schema。 |
| future importers | ONNX-like ML、MatrixMarket sparse、stencil DSL、graph dataset、query plan 等。 |

新增 importer/profile 不应修改 core IR classes、generic simulator schema、report validator 或 mapping-search core。

### 4.3 Step1 artifact

| Artifact | 作用 |
| --- | --- |
| `workload_package.json` | workload id、family、profile/importer、source、claim boundary。 |
| `workload_graph.json` | source graph 的 nodes、edges、metadata。 |
| `graph_lowering_report.json` | lowering 状态、unsupported constructs、full-workload eligibility。 |
| `executable_graph.json` | 如果 lowering 成功，供 Step2/Step3 使用的可执行图。 |

### 4.4 Step1 gate

Step1 通过不等于可最终声明。它只说明 workload 能进入后续 DSE。若出现以下状态，后续只能写成 blocked 或 diagnostic：

- graph lowering 未成功；
- workload 是 smoke / reduced / trace-only；
- required coverage 无法映射到 executable graph；
- profile/importer 没有 domain validation，但报告试图声明 domain correctness。

---

## 5. Step2：architecture、mapping 与 promotion

### 5.1 Step2 目标

Step2 是 workload lowering 与 simulation evidence 之间的 handoff boundary。它消费磁盘上的 generic artifacts，选择 architecture instance，构造 replayable `DesignPoint`，运行 mapping search，并写出下游可重放 artifacts。

Step2 不能输出 trusted final claim。

### 5.2 Architecture catalog

Architecture catalog 描述可探索的架构空间：

- architecture family；
- components；
- constraints；
- simulation bindings；
- trusted-final eligibility；
- candidate-only reasons。

如果 architecture 缺少 trusted simulation binding，它可以继续作为 candidate 参与分析，但不能进入 trusted final ranking。

### 5.3 Mapping search

第一阶段推荐的 mapping search 不是纯 BO，而是：

```text
domain seed generation
  -> legality filtering
  -> beam search over mapping and architecture mutations
  -> L1/L2/surrogate screening
  -> promotion to SystemC/gem5+SystemC
```

原因是 mapping space 高度离散、受 legality 约束、强依赖 workload / profile seed。BO、NSGA-II、HyperMapper 或 Ax/BoTorch 类搜索应作为 plugin 接入，而不是绕过 legality 和 evidence gate。

### 5.4 Step2 artifacts

| Artifact | 作用 | Claim 边界 |
| --- | --- | --- |
| `step2_status.json` | Step2 状态、selected ids、reasons | 不是 final evidence。 |
| `architecture_catalog.json` | catalog snapshot | 审计架构空间。 |
| `architecture.json` | selected architecture instance | 缺 binding 时是 candidate-only。 |
| `design_point.json` | replayable DesignPoint | Step3 输入。 |
| `mapping_legality_matrix.json` | node/resource legality | 解释 rejection。 |
| `mapping_seed_set.json` | generic / profile-owned seed mappings | 复现搜索。 |
| `mapping_candidate_records.json` | generated candidates | candidate audit。 |
| `mapping_selected_record.json` | selected mapping | final report 需引用。 |
| `mapping_promotion_decision.json` | 是否进入 Step3 | 不能声明 trusted final。 |
| `mapping_simulation_samples.json` | promoted samples / placeholders | 反馈桥。 |
| `mapping_feedback_state.json` | ranking / calibration state | 下一轮搜索输入。 |
| `convergence_status.json` | stop/continue reason | budget exhaustion 是 limitation。 |

### 5.5 Step2 acceptance gate

Step2 进入 Step3 前必须满足：

- workload package valid；
- graph lowering `full_workload_eligible = true`；
- architecture catalog validation 无 fatal error；
- selected backend binding trusted-eligible；
- selected mapping 无 legality violations；
- promotion decision 显式允许 simulation；
- Step2 artifacts 不声明 trusted final winner。

---

## 6. Step3：simulation evidence 与 claim gate

### 6.1 Step3 目标

Step3 是 high-fidelity evidence boundary。它必须从磁盘 reload Step2 artifacts，拒绝未 promotion、diagnostic、illegal 或缺 artifact 的 handoff，然后运行 selected backend，并写出 evidence bundle。

### 6.2 Backend taxonomy

| Backend | 当前角色 | Claim 边界 |
| --- | --- | --- |
| L1 analytical | 快速估算、筛选 | predicted-only。 |
| L2 TLM / Python TLM | 中等保真估计 | 不能 final winner。 |
| L3 `standalone_systemc` | generic timing-level SystemC backend | 可进入 trusted timing evidence，但仍需 coverage / validation。 |
| L4 `gem5_systemc` | gem5 + SystemC co-simulation | 只有 `gem5_l4_proof.json` 通过才可信。 |
| implementation / board | 未来 HLS / RTL / board evidence | 当前不得隐式声称存在。 |

### 6.3 Step3 artifacts

| Artifact | 作用 |
| --- | --- |
| `simulation_request.json` | backend 消费的 workload / architecture / mapping request。 |
| `simulation_result.json` | public simulation result。 |
| `simulation_result.raw.json` | optional raw backend output。 |
| `numerical_validation.json` | generic timing-level numeric reference check。 |
| `verdict.json` | trust gate 的主要机器可读 verdict。 |
| `evidence_requirements.json` | required / optional evidence files。 |
| `claim_validation.json` | claim validation 结果。 |
| `final_report.json` | machine-readable final report。 |
| `final_report.md` | human-readable final report。 |
| `artifact_manifest.json` | run-local evidence index。 |
| `manifest.json` | run id、command、backend、status、artifact paths。 |
| `gem5_l4_proof.json` | L4 gem5+SystemC proof，仅 L4 trusted claim 必需。 |

### 6.4 Trusted ranking gate

候选进入 trusted final ranking 至少需要：

1. architecture instance 有 valid simulation binding；
2. selected mapping legal；
3. complete SystemC 或 gem5+SystemC full-flow simulation 完成；
4. `verdict.json` 标记 `trusted_for_final_ranking = true`；
5. required evidence files 存在，或 unavailable reasons 明确；
6. trusted claim 引用 run-local evidence ids；
7. `claim_validation.json` 通过；
8. L4 claim 还必须有通过的 `gem5_l4_proof.json`。

### 6.5 Step3 blocked / untrusted 状态

手册和报告必须使用明确状态，而不是模糊描述：

| 状态 | 含义 |
| --- | --- |
| `blocked_before_simulation` | Step2 handoff 或 claim boundary 不允许进入 simulation。 |
| `blocked_simulator_unavailable` | backend executable 或 L4 harness 不可用。 |
| `simulation_completed_untrusted` | simulation 运行了，但 evidence / coverage / proof / claim validation 不完整。 |
| `trusted_full_flow_evidence_emitted` | full-flow evidence、verdict 和 claim validation 均通过。 |

---

## 7. Feedback loop 与 convergence

### 7.1 Feedback 更新内容

每个 trusted high-fidelity sample 应反馈到：

1. trusted ranking；
2. Pareto frontier；
3. low-fidelity calibration samples；
4. surrogate model 或 ranking correction；
5. pruning thresholds；
6. promotion policy；
7. next-candidate generation。

### 7.2 Sample class

| Sample class | Search effect | Reporting effect |
| --- | --- | --- |
| `trusted-systemc` | 更新 ranking、calibration、pruning、promotion | 可进入 trusted timing ranking。 |
| `trusted-gem5-systemc` | 同上，并有 L4 software-visible completion proof | 可支撑 L4 trusted claim。 |
| `untrusted-gem5-systemc` | 记录 missing proof，可能重定向预算到 L3 | 不可 trusted。 |
| `diagnostic-only` | 只验证命令或 wiring | 诊断附录。 |
| `predicted-only` | 指导探索 | candidate appendix。 |

### 7.3 Convergence criteria

闭环可以因以下条件停止：

- trusted frontier stability；
- top-K stability；
- improvement threshold；
- uncertainty reduction；
- family coverage；
- budget exhaustion；
- hard blocker。

`budget exhaustion` 必须报告为 limitation，而不是完整 convergence。

---

## 8. Final report 与 claim validation

### 8.1 Final report 应包含的章节

1. Executive summary。
2. Workload and dataset provenance。
3. Architecture catalog scope。
4. Search configuration and budget。
5. Candidate lifecycle summary。
6. Trusted SystemC/gem5+SystemC ranking。
7. Predicted-only candidates appendix。
8. Pareto alternatives。
9. Selected architecture and mapping。
10. Phase breakdown。
11. Data movement and resource utilization。
12. Evidence index。
13. Claim table。
14. Limitations and blocked paths。
15. Replay instructions。

### 8.2 Claim schema

每条 claim 至少应包含：

```yaml
claim_id: string
claim_type: best_architecture | mapping_comparison | bottleneck | feasibility | pareto | convergence | debug | numerical_correctness | limitation
statement: string
trust_level: trusted | predicted | untrusted | blocked
evidence_ids: list[string]
required_files: list[string]
metric_values: map[string, any]
limitations: list[string]
```

### 8.3 Claim evidence table

| Claim type | Required evidence |
| --- | --- |
| Best architecture | selected run result、mapping、architecture、verdict、trusted ranking table。 |
| Mapping comparison | 同一 workload/config 下两个 mapping 的 SystemC/gem5+SystemC results。 |
| Bottleneck diagnosis | resource summary + debug trace。 |
| Feasibility | verdict、violation list、no-deadlock/no-overflow 或等价 evidence。 |
| Pareto frontier | trusted result set、objective directions、dominance computation artifact。 |
| Convergence | search-state snapshots、feedback iterations、budget 和 stopping reason。 |
| Numerical correctness | generic timing-level check；domain correctness 需要 profile/importer reference evidence。 |
| Smoke / diagnostic limitation | 显式 diagnostic-only status，不能进入 trusted ranking。 |

### 8.4 Claim wording cookbook

| 证据状态 | 允许写法 | 禁止写法 |
| --- | --- | --- |
| L1/L2 predicted | “候选点在低保真模型下表现较好” | “该架构最快” |
| Step2 promoted | “该 design point 具备进入 Step3 的条件” | “该 design point 已经胜出” |
| L3 trusted SystemC | “该 run 支撑 timing/resource 层面的可信排序” | “该 run 证明 domain correctness” |
| L4 proof passed | “该 run 有 gem5 software-visible completion proof” | “所有 L4 路径都已闭合” |
| single pilot | “该 pilot 是 feasibility evidence” | “该 pilot 给出全局 Pareto frontier” |
| projection_only | “该 row 是 projection/scaffold evidence” | “该 row 是 native executor result” |

---

## 9. 开发者扩展指南

### 9.1 新增 workload profile/importer

新增 profile/importer 的最小要求：

- 注册 profile id/version 和 importer id/version；
- 输出 valid `WorkloadPackage`；
- 保留 source provenance；
- 声明 claim boundary；
- 声明 required coverage；
- 提供 graph lowering 规则或 unsupported diagnostics；
- 若要声明 domain correctness，必须提供 profile/importer-domain validation evidence。

不得把 profile/importer-specific metadata 写成 core IR requirement。

### 9.2 新增 architecture family

新增 architecture family 的最小要求：

- family id 和参数 schema；
- component templates；
- resource constraints；
- supported operators；
- simulation binding metadata；
- candidate-only reason；
- trusted-final eligibility 判断。

没有 simulation binding 的 family 只能是 candidate-only。

### 9.3 新增 backend

新增 backend 必须定义：

- request schema；
- result schema；
- status labels；
- evidence artifacts；
- trust gate；
- replay instructions；
- blocked / unavailable behavior。

后端不可静默生成 synthetic evidence。缺 proof 时必须输出 blocked 或 untrusted。

### 9.4 新增 optimizer

Optimizer 只负责 candidate proposal，不拥有 claim authority。建议接口：

```text
candidate queue
  -> legality filter
  -> screening model
  -> promotion policy
  -> simulation samples
  -> feedback update
```

BO、NSGA-II、OpenTuner-style ensemble、Optuna sampler、Ax/BoTorch acquisition 都应接入同一套 artifact 和 evidence gate。

---

## 10. Runbook

### 10.1 构建 generic SystemC backend

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j4
```

预期输出：

```text
model/generic_sim_backend/build/generic_sim
```

可信等级：只说明 L3 backend executable 可用，不生成 DSE claim。

### 10.2 运行 generic profile full-flow pilot

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend systemc \
  --evidence-mode debug \
  --out runs/dse/sparse_la_systemc
```

预期 artifacts：

```text
manifest.json
workload_package.json
workload_graph.json
graph_lowering_report.json
simulation_request.json
simulation_result.json
numerical_validation.json
verdict.json
final_report.json
final_report.md
claim_validation.json
```

可信等级：single-run feasibility / timing evidence。不能声明 best architecture 或 Pareto frontier。

### 10.3 运行 bounded multi-candidate feedback pilot

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend systemc \
  --evidence-mode debug \
  --feedback-samples 2 \
  --out runs/dse/feedback_convergence_<timestamp>
```

预期额外 artifacts：

```text
mapping_simulation_samples.json
mapping_feedback_state.json
convergence_status.json
feedback_samples/
```

可信等级：bounded feedback evidence。若停止原因是 budget exhaustion，只能写成 limitation。

### 10.4 运行 real gem5+SystemC L4 proof

```bash
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --profile sparse_la \
  --importer generic_json \
  --generator sparse_spmv \
  --backend gem5_systemc \
  --gem5-real-l4 \
  --evidence-mode debug \
  --out runs/dse/l4_full_flow_real_<timestamp>
```

必须检查：

```text
gem5_l4_proof.json
gem5_command_descriptor.json
gem5_completion_descriptor.json
gem5.log
claim_validation.json
```

可信等级：只有 `gem5_l4_proof.json` passed 且 `claim_validation.json` passed 时，才能写成 L4 trusted evidence。

### 10.5 运行 focused regression

```bash
python3 -m pytest -q \
  dse_v2/tests/test_workload_importer_registry.py \
  dse_v2/tests/test_workload_workflows.py \
  dse_v2/tests/test_step2_architecture_mapping_workflow.py \
  dse_v2/tests/test_step3_cross_step_workflow.py \
  dse_v2/tests/test_final_report_validation.py \
  dse_v2/tests/test_full_flow_pilot.py
```

可信等级：验证 DSE workflow 和 report gate 的回归行为。若环境缺少依赖，应记录为 validation blocker。

---

## 11. Removed legacy/reference lane

旧应用材料不再保留在 active tree。若后续需要引用，它的定位应是：

```text
scoped reference profile/importer / DFT vertical proof evidence / historical evidence restored only on demand
```

### 11.1 保留内容

- `DSE organizes evidence. Adjudicator controls claims.`
- `candidate_family` 与 `runtime_projection_family` 的区别。
- `executor_claim_allowed` 不是 public claim permission。
- same-fidelity ranking。
- allowed / guarded / forbidden claim wording。
- projection-only troubleshooting。

### 11.2 降级内容

| 旧内容 | 新位置 |
| --- | --- |
| Stage-A architecture-family sweep | Historical/reference runbook, restored only when needed。 |
| next-stage release package | Release-facing appendix。 |
| F4/F5/custom projection-only 细节 | Troubleshooting。 |
| Reference workload phases | 对应 reference profile/importer section。 |

### 11.3 迁移规则

当旧应用 artifact 进入新手册语境时，必须补齐：

- workload package identity；
- profile/importer id/version；
- claim boundary；
- evidence mode；
- support status；
- trusted gate；
- forbidden claim list。

---

## 12. Troubleshooting

### 12.1 `blocked_before_simulation`

检查：

- `step2_status.json`；
- `mapping_promotion_decision.json`；
- `graph_lowering_report.json`；
- `mapping_selected_record.json`；
- `step2_artifact_validation.json`。

常见原因：missing artifacts、diagnostic claim boundary、unsupported lowering、illegal selected mapping、Step2 未 promotion。

### 12.2 `simulation_completed_untrusted`

检查：

- simulator return code；
- `simulation_result.json` status；
- required coverage；
- `numerical_validation.json`；
- `verdict.json`；
- `claim_validation.json`。

### 12.3 `projection_only` 被误读为 executor result

检查：

```text
candidate_family
runtime_projection_family
support_status
fidelity_class
executor_claim_allowed
native_runtime_evidence_path
```

如果 `support_status = projection_only`，则只能写成 projection/scaffold evidence。

### 12.4 L4 proof 失败

检查：

```text
gem5_l4_proof.json
gem5_command_descriptor.json
gem5_completion_descriptor.json
gem5_stdout.txt
gem5_stderr.txt
gem5.log
```

若 descriptor read、SystemC submit、completion writeback、driver status 或 result status 任一失败，L4 claim 必须降级为 untrusted / blocked。

---

## 13. Acceptance checklist

在把任何 DSE run 写成报告、论文材料或 release artifact 前，逐项检查：

- [ ] 是否明确当前结果是 predicted-only、diagnostic-only、candidate-only、trusted-systemc 还是 trusted-gem5-systemc？
- [ ] 是否保留 `candidate_family` 与 `runtime_projection_family` 的区别？
- [ ] 是否没有把 `projection_only` 写成 native executor？
- [ ] 是否没有把 Step2 promotion 写成 final recommendation？
- [ ] 是否检查了 `verdict.json` 和 `claim_validation.json`？
- [ ] L4 claim 是否引用并通过 `gem5_l4_proof.json`？
- [ ] single pilot 是否只写成 feasibility / timing evidence？
- [ ] BO / surrogate / optimizer 是否只写成 candidate proposal layer？
- [ ] optional/reference workload 是否只作为 profile/importer，而非 core schema？
- [ ] domain correctness 是否有 profile/importer-specific validation evidence？
- [ ] Pareto / best architecture 是否基于多个 comparable trusted samples？
- [ ] runbook 是否记录 command、output directory、artifact paths 和 trust level？
- [ ] public claim 是否仍交由 adjudicator memo 控制？

---

## 附录 A. Artifact dictionary

| Artifact | 所属阶段 | 最小作用 |
| --- | --- | --- |
| `workload_package.json` | Step1 | Workload contract。 |
| `workload_graph.json` | Step1 | Source graph。 |
| `graph_lowering_report.json` | Step1 | Lowering / eligibility audit。 |
| `architecture_catalog.json` | Step2 | Architecture space snapshot。 |
| `architecture.json` | Step2 | Selected architecture instance。 |
| `design_point.json` | Step2 | Replayable candidate。 |
| `mapping_legality_matrix.json` | Step2 | Mapping legality。 |
| `mapping_candidate_records.json` | Step2 | Candidate history。 |
| `mapping_promotion_decision.json` | Step2 | Step3 admission gate。 |
| `simulation_request.json` | Step3 | Backend request。 |
| `simulation_result.json` | Step3 | Public backend result。 |
| `numerical_validation.json` | Step3 | Generic timing numeric check。 |
| `verdict.json` | Step3 | Trust gate。 |
| `claim_validation.json` | Step3/report | Machine-checkable claim gate。 |
| `final_report.md` | Report | Human-readable review surface。 |
| `gem5_l4_proof.json` | L4 | Software-visible completion proof。 |

---

## 附录 B. 代码与文档入口

| 入口 | 路径 |
| --- | --- |
| 通用 DSE 设计规范 | `docs/architecture/generic_dse_framework_design_spec_v2.md` |
| 旧应用专用 DSE 手册 | `legacy/` |
| DSE v2 README | `dse_v2/README.md` |
| Full-flow reporting | `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md` |
| Step2 workflow | `dse_v2/mapping/step2_workflow.py` |
| Step3 workflow | `dse_v2/evidence/step3_workflow.py` |
| Full-flow pilot | `dse_v2/scripts/dse/run_full_flow_pilot.py` |
| Generic SystemC backend | `model/generic_sim_backend/README.md` |
| gem5+SystemC L4 adapter | `dse_v2/backends/gem5_systemc_adapter.py` |

---

## 附录 C. 最终原则

这套系统的目标不是快速给出“最优架构”口号，而是建立一条可复现、可审计、可扩展的证据闭环：

```text
domain-neutral workload
  + explicit design space
  + legal mapping search
  + high-fidelity simulation evidence
  + feedback state
  + claim validation
  + adjudicator-compatible report
```

如果某条结论没有 run-local artifact、evidence id、verdict 和 claim validation 支撑，它只能是候选解释或未来工作，不能是可信 DSE 结论。
