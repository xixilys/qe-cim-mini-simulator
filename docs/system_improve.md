你说得对，我上一轮把“系统设计文档”过度按“论文叙事”来审了。现在我按**系统工程本身**来审：这个系统未来要长期演进、能接不同 workload、能跑 DSE、能复现实验、能把低保真/高保真结果分层、能支撑 DFT→FPGA 主证明场景，但不要求所有东西都进文章。

我的总体判断是：

> **系统的大方向是对的：domain-neutral core + profile/importer + architecture catalog + mapping search + L1/L2/L3/L4 多保真 + evidence-backed claim。真正需要改的不是推倒重来，而是把“线性流程文档”重构成“可执行、可验证、可扩展的 DSE 控制平面”。**

也就是说，不建议放弃现有 Step1/Step2/Step3/Reporting 分层；建议在这个分层上方增加更严格的 **campaign / trial / artifact / evidence / policy / calibration** 控制体系。

---

## 1. 最重要的系统级问题：现在像“流程规范”，还不完全像“DSE 操作系统”

你现在的设计已经明确了系统目标：接收不同领域 workload，经统一 IR、架构候选、映射搜索和高保真仿真，输出带证据链的设计结论；全局文档还强调 domain-neutral、evidence-backed、replayable 三个约束。
详细规范也已经把闭环写成：

```text
workload ingestion
→ architecture catalog / design point generation
→ mapping search with screening
→ SystemC or gem5+SystemC simulation
→ simulation feedback updates search
→ trusted final analysis report
```

并明确 L1/L2 只能初筛，SystemC/gem5+SystemC 才能支撑最终可信结论。

但系统层面还缺一个更硬的抽象：**DSE campaign / trial state machine**。

现在文档里有 Step1、Step2、Step3、Reporting，但没有把一次完整 DSE 运行定义成一个稳定的、可恢复的、可查询的 campaign ledger。也就是说，系统知道有哪些 artifacts，但还没有一个足够强的“运行账本”来回答：

* 这个 campaign 的目标函数是什么？
* 预算是什么？
* 每个 candidate 为什么生成？
* 为什么被筛掉？
* 为什么被 promotion？
* 哪个 simulator 评估过？
* 低保真和高保真结果如何校准？
* 哪些结果进入 frontier？
* 哪些结果被 claim gate 拦截？
* 如果中断，如何从 ledger 精确恢复？

参考 AiiDA、FireWorks、custodian 这类科学工作流系统，成熟系统的核心不是“流程能跑通”，而是 automation、data、environment、sharing / provenance / error recovery 一整套账本能力；AiiDA 明确以有向图记录数据和计算 provenance，FireWorks 面向大规模高通量工作流，custodian 处理长任务的错误检查、管理和自动恢复。([arXiv][1])

### 修改方向

增加一个一等公民：

```yaml
Campaign:
  campaign_id
  workload_set
  architecture_catalog_version
  objectives
  constraints
  fidelity_budget
  search_policy
  promotion_policy
  calibration_policy
  stopping_policy
  created_at
  git_revision
  environment_ref
  status

Trial:
  trial_id
  campaign_id
  candidate_id
  lifecycle_state
  parent_candidate_ids
  generation_reason
  screening_refs
  promotion_decision_ref
  simulation_refs
  evidence_refs
  feedback_update_refs
  verdict_ref
  timestamps
  failure_reason
```

然后把现在的 candidate lifecycle：

```text
generated → screened → promoted → scheduled-for-sim → simulated → finalist/rejected/blocked → selected
```

升级成**强制状态机**。状态变化必须只能由 policy engine 写入，不允许脚本随便改 JSON 文件。

这一步是系统级关键改造。否则系统会越来越像一组脚本和 artifacts，而不是一个可以长期复现实验的 DSE 平台。

---

## 2. Step3 和 Reporting 的职责现在仍然混在一起，需要拆开

全局设计里写得很清楚：Step3 是 Simulation Evidence Layer，Reporting and Claim Layer 负责 final report、claim validation 和 adjudicator inputs。
但详细规范里 Step3 output contract 又把 `final_report.json / final_report.md` 放进 Step3 输出，同时 Step3 还产生 `claim_validation.json`。

这不是论文叙事问题，而是**系统边界问题**。如果 Step3 既运行仿真、又写 evidence、又写 final report、又做 claim validation，那么后面会出现三个麻烦：

第一，仿真后端会被迫理解 report 语义。
第二，报告层无法独立复用多次仿真结果。
第三，多候选、多 campaign 汇总时会出现 Step3-run report 和 campaign-level report 冲突。

### 修改方向

把系统拆成五层，而不是四层：

```text
Step1: Workload ingestion / lowering
Step2: Architecture + mapping + candidate generation
Step3: Simulation execution only
Step4: Evidence adjudication + feedback update
Step5: Reporting + claim presentation
```

对应 artifacts：

```text
Step3 emits:
  simulation_request.json
  simulation_result.json
  backend_logs
  raw_trace_files
  step3_status.json

Step4 emits:
  manifest.json
  artifact_manifest.json
  verdict.json
  evidence_requirements.json
  claim_validation.json
  feedback_update.json

Step5 emits:
  final_report.json
  final_report.md
  campaign_summary.json
  trusted_ranking.json
  pareto_frontier.json
```

这样 Step3 是“测量”，Step4 是“裁决”，Step5 是“表达”。这比现在 Step3 大包大揽更干净。

---

## 3. `trusted`、`full-flow`、`numerical_validation` 三个词需要重新定义

系统总览明确说当前 `generic_sim_backend` 是**纯 timing estimator**，不执行 GEMM/FFT/Eigen 数值计算，不产生输出 tensor，因此不能验证计算正确性，也不能作为 RTL UVM reference model。

但详细规范里仍然有 `numerical_validation.json`，并且它既被描述为 generic simulator/reference checks，又在别处和未来 numerical execution / golden model / UVM reference model 方向发生语义重叠。

这会导致系统后期非常危险：用户或论文作者可能误把 timing-level consistency 当成 numerical correctness。

### 修改方向

把验证类型拆成四层：

```text
simulator_consistency_check.json
  检查 simulation_result 字段、单位、事件覆盖、metric consistency。
  不涉及数值计算正确性。

timing_model_calibration.json
  检查 SystemC/generic backend 的 timing/resource 模型与 reference/microbenchmark/RTL/HLS report 的误差。

kernel_numerical_validation.json
  只有真正执行 GEMM/FFT/Eigen/reduction 并与 golden output 对比时才生成。

domain_physics_validation.json
  只有验证 DFT residual、density、eigenvalue、energy、force、stress 等领域物理量时才生成。
```

然后把 claim level 固定成：

| Claim level                 | 允许支持的结论                                |
| --------------------------- | -------------------------------------- |
| `predicted`                 | L1/L2 初筛，不进最终排名                        |
| `timing_evidence`           | L3 timing/resource/data movement       |
| `software_visible_evidence` | L4 descriptor/request/completion proof |
| `kernel_numerical_evidence` | kernel 数值正确性                           |
| `domain_physics_evidence`   | DFT/ML/sparse/database 领域正确性           |

这样以后你加 numerical layer 或 UVM reference model 时不会破坏旧 artifacts。

---

## 4. Artifact 命名和 schema 版本需要冻结，否则系统会越来越不可维护

现在文档里同类 artifact 有多套名字。例如：

* `mapping_candidates.jsonl` / `mapping_candidate_records.json`
* `promotion_decisions.jsonl` / `promotion_decision.json` / `mapping_promotion_decision.json`
* `manifest.json` / `artifact_manifest.json`
* `mapping.json` / `mapping_selected_record.json`
* `final_analysis.md/json` / `final_report.md/json`

这些在早期开发中可以接受，但系统长期演进会变成灾难。全局文档强调 replayable，后续步骤不得依赖隐藏 Python 状态；详细规范也要求 Step1/Step2/Step3 artifacts 落盘并可审计。 
如果 artifact 名称不稳定，replayable 会失效。

JSON Schema 官方规范把 schema 拆成 Core 和 Validation，并且当前版本是 2020-12；对你这种以 JSON artifacts 作为阶段合同的系统，应当把每个 artifact 的 schema 固化，而不是只在 Markdown 中写 YAML 伪结构。([json-schema.org][2])

### 修改方向

建立：

```text
schemas/
  workload_package.schema.json
  compute_graph.schema.json
  executable_graph.schema.json
  architecture_catalog.schema.json
  architecture_instance.schema.json
  design_point.schema.json
  mapping_candidate.schema.json
  promotion_decision.schema.json
  simulation_request.schema.json
  simulation_result.schema.json
  verdict.schema.json
  claim_validation.schema.json
  campaign.schema.json
  trial.schema.json
```

同时冻结 canonical artifact 名称：

```text
workload_package.json
workload_graph.json
graph_lowering_report.json
executable_graph.json

architecture_catalog.json
architecture.json
design_point.json

mapping_legality_matrix.json
mapping_seed_set.json
mapping_candidates.jsonl
screening_results.jsonl
promotion_decisions.jsonl

simulation_request.json
simulation_result.json
step3_status.json

manifest.json
artifact_manifest.json
verdict.json
claim_validation.json
feedback_update.json

trusted_ranking.json
pareto_frontier.json
final_report.json
final_report.md
```

其他历史命名可以保留 compatibility reader，但不要再作为新写入格式。

---

## 5. Evidence store 现在是“文件集合”，还不是“provenance graph”

你的设计非常重视 evidence id、manifest、artifact hash、replay metadata，这是正确的。问题是现在 evidence 还是 run directory 中的一组文件，没有明确采用 provenance graph 模型。

W3C PROV-DM 把 provenance 建模为 entities、activities、agents 及其关系，这很适合你这个系统：workload、design point、simulator result、verdict 都是 entity；Step1/Step2/Step3/feedback 都是 activity；importer、optimizer、simulator、user、CI 都是 agent。([W3C][3])
AiiDA 也正是通过 DAG 跟踪数据和计算 provenance 来保证保存、搜索和可复现。([arXiv][1])

### 修改方向

增加一个 `provenance.json` 或 ledger 表：

```yaml
Entity:
  id
  type
  content_hash
  schema_version
  path
  created_by_activity

Activity:
  id
  type
  input_entities
  output_entities
  started_at
  finished_at
  command
  environment
  status

Agent:
  id
  type: user | importer | optimizer | simulator | ci
  version
```

然后每个 claim 不直接指向文件路径，而是指向 entity id：

```yaml
Claim:
  claim_id
  trust_level
  evidence_entity_ids
  produced_by_activity_ids
```

这样你后面做 archive、artifact review、CI regression、跨机器 replay 都会简单很多。

---

## 6. ComputeGraph 需要从“开放 op_type 图”升级成“可 lowering 的多层 IR”

当前 ComputeGraph 设计已经很不错：支持 open `op_type`、typed nodes、typed edges、hierarchical subgraphs、loop/feedback/streaming constructs，不把 QE/DFT 写死进 core。
但系统长期看，仅靠 open `op_type` + opaque metadata 会遇到两个问题：

第一，mapping/search 不知道某个 op 是否可交换、可融合、可切分、可近似。
第二，simulator/backend 不知道某个 op 的语义、数据访问模式、side effect 和 lowering 合法性。

MLIR 的经验是：可扩展系统不等于所有东西都是 opaque string，而是通过 dialect / operation / attribute / pass / lowering 机制在不同抽象层级之间保持可验证语义；MLIR 的目标就是降低领域专用编译器建设成本，并连接不同抽象层级、硬件目标和执行环境。([arXiv][4])
TVM/Ansor/Halide 的经验也类似：高性能系统通常要把“算法/计算定义”和“调度/映射策略”分开，Ansor 使用层次化搜索空间和 learned cost model，Halide 明确把 algorithm 和 schedule 分离。([arXiv][5])

### 修改方向

不要把 ComputeGraph 做成 MLIR 的完整替代，但要引入**最小语义注册表**：

```yaml
OpSemantics:
  op_type
  input_contract
  output_contract
  shape_function
  dtype_rules
  side_effects
  commutativity
  associativity
  fusibility
  split_policy
  data_access_pattern
  numerical_mode_support
  cost_model_binding
  backend_lowering_rules
```

然后 graph lowering 不只是“把图变成 executable view”，而是明确输出：

```yaml
LoweringDecision:
  source_node_id
  executable_node_ids
  transformation:
    identity | fuse | split | summarize_loop | backend_native | unsupported
  semantic_preservation:
    exact | approximate | timing_summary_only | diagnostic_only
  reason
```

这会让 DFT、ML、stencil、sparse 等 profile 都能共享一套 lowering 审计机制。

---

## 7. Workload profile/importer 的方向对，但 DFT profile 需要尽快冻结

你文档反复强调 DFT 是主证明场景，但 DFT 字段不得进入 core schema。这个边界是正确的。
问题是：DFT profile 现在还没有冻结到足以驱动系统实现。总览里也承认 DFT→FPGA 主证明 spec 是关键规范缺口，需要冻结 DFT config schema、DFT mini-graph coverage、FPGA deployment knobs、domain validation 和 case-set 边界。

### 修改方向

新增独立文档和 schema：

```text
dft_reference_profile_spec.md
schemas/dft_config.schema.json
schemas/dft_profile_metadata.schema.json
schemas/dft_domain_validation.schema.json
```

建议最小 DFT profile：

```yaml
DftConfig:
  code_family: qe | vasp | synthetic_plane_wave
  calculation_kind: scf | relax | nscf | bands | phonon | synthetic_scf
  precision_mode: fp64 | mixed_timing_only
  natoms
  species
  valence_electrons
  spin_channels
  kpoints
  nbands
  npw
  nfft
  scf_iterations
  solver_family
  kernels:
    fft3d_count
    gemm_shapes
    reduction_count
    eigensolver_shell_steps
  data_objects:
    wavefunction_bytes
    density_bytes
    potential_bytes
  host_device:
    transfer_policy
    transfer_bytes
  claim_boundary:
    timing_only | kernel_numerical | dft_residual | full_physics
```

注意：这里不是把 DFT 写进 core，而是把 DFT profile 做完整。否则系统会出现“core 很通用，但主证明 profile 不够硬”的问题。

---

## 8. Architecture catalog 需要 capability model，而不是只靠 family/status

当前 Architecture catalog 已经有 family、component types、bindings、constraints、binding status 等字段。
但从系统实现角度看，还需要更强的 capability model。否则 mapping legality matrix 会变成一堆手写 if/else。

Timeloop/Accelergy 的启发是：架构描述、映射、能耗/性能模型需要分离但可组合；Timeloop 通过架构和 mapper 支持大设计空间评估，Accelergy/Timeloop 这类基础设施强调 action counts、architecture/action energy 等可复用成本模型。([Accelergy][6])
MAESTRO 则强调从 dataflow 描述、硬件配置推导 throughput、execution time、energy 等指标；这对你系统里的 mapping/dataflow/cost model 分层很有参考价值。([arXiv][7])

### 修改方向

给每个 ComponentType 增加机器可读 capability：

```yaml
ComponentCapability:
  supported_ops:
    - op_type
    - semantic_tags
  supported_dtypes
  vector_width
  peak_ops
  memory_ports
  local_memory_bytes
  bandwidth
  latency_model_id
  energy_model_id
  action_counter_model_id
  routing_endpoints
  supported_schedules:
    - streaming
    - batched
    - tiled
    - fused
  numerical_modes:
    - timing_only
    - numerical_reference
  binding:
    systemc_model
    gem5_model
    rtl_model
    status
```

Legality matrix 不应该直接问“这个 resource 是否支持 op_type 字符串”，而应该调用：

```python
capability.supports(op_semantics, dtype, schedule, data_placement, precision_policy)
```

---

## 9. Mapping search 当前方向合理，但系统不该把 beam search 写死成主路径

详细规范说第一实现建议：

```text
domain seed generation
→ legality filtering
→ beam search over mapping + architecture mutations
→ L1/L2/surrogate screening
→ promotion to SystemC/gem5+SystemC
→ feedback update
```

并且认为纯 BO 不适合第一实现，因为 mapping 空间离散、强约束、依赖 domain seed。这个判断是合理的。

但从系统设计角度，不应把“beam search”写成系统事实。更好的做法是定义统一的 `SearchPolicy` 插件接口。原因是不同 workload 的搜索形态完全不同：

* HLS pragma/FPGA DSE 里，Prospector 用 Bayesian optimization 优化 synthesis directives，以减少 latency/resource；AutoDSE 用 bottleneck-guided coordinate optimizer，每步检测瓶颈并优先调整高影响参数。([ACM Digital Library][8])
* HGBO-DSE 把 HLS DSE 做成 Hierarchical GNN predictor、tree-structured design space modeler 和 multi-objective BO 的组合，用 tree model 删除无效配置。([ResearchGate][9])
* BOHB 结合 Bayesian optimization 和 Hyperband，利用低保真预算做 strong anytime performance 和 fast convergence。([arXiv][10])
* OpenTuner 的系统思想是支持可定制 configuration representation、domain-specific heuristics 和多种搜索技术 ensemble。([Commit][11])
* RankTuner 这类近期 EDA 工作直接学习 Pareto dominance / preference，而不是回归绝对 QoR，这对有噪声的 DSE 很有价值。([香港中文大学计算机科学与工程系][12])

### 修改方向

系统层面定义：

```yaml
SearchProblem:
  workload_view
  architecture_space
  mapping_space
  legal_actions
  objectives
  constraints
  fidelity_budget
  prior_samples
  campaign_state

SearchPolicy:
  policy_id
  propose(problem, state, k) -> candidate_set
  observe(samples, state) -> updated_state
  checkpoint(state) -> artifact
```

内置策略：

```text
seeded_beam
bottleneck_guided_coordinate
random_baseline
evolutionary_nsga2
bohb
tpe
preference_bo
mcts_importance
ensemble_opentuner_style
```

第一版仍然可以默认 `seeded_beam + bottleneck_guided`，但系统不要绑定死。

---

## 10. Feedback loop 需要从“更新 ranking”升级成“校准模型”

现在 feedback update 包含 trusted ranking、Pareto frontier、surrogate calibration samples、ranking correction、promotion policy 等，这是对的。
但系统还缺少一个正式的 `CalibrationRecord`。如果没有校准记录，L1/L2/L3/L4 之间的关系会变成经验性的。

gem5-Aladdin 的动机正是 accelerator 不能孤立优化，SoC/memory/software-visible interactions 会改变最优设计；其公开说明提到它用于 accelerator-system co-design，并对真实硬件做过验证。([vlsiarch.eecs.harvard.edu][13])
这直接支持你把 L4 作为昂贵但权威的 software-visible evidence oracle 的设计。但要让 L4 反哺 DSE，必须把 L4 与 L3/L2/L1 的误差记录下来。

### 修改方向

增加：

```yaml
CalibrationRecord:
  calibration_id
  source_fidelity: L1 | L2 | L3
  target_fidelity: L3 | L4 | rtl | measured
  candidate_ids
  metrics:
    latency_ms:
      mape
      spearman_rank_corr
      kendall_tau
      bias
      variance
    dma_bytes:
      error
    host_overhead_ms:
      error
  valid_region:
    workload_family
    architecture_family
    op_types
    size_range
  update_action:
    adjust_model_params | retrain_surrogate | downgrade_confidence | block_claim
```

然后 promotion policy 使用 calibration confidence，而不是只看 `uncertainty` 一个字段。

---

## 11. L4 gem5+SystemC 的方向非常好，但要变成“接口可观测性模型”

你文档对 L4 的边界写得很清楚：可信 L4 必须证明 descriptor/request ingestion、backend invocation、payload consumption、completion visible to software side 等。
系统总览也进一步明确：L4 证明链包括软件写入 descriptor、GenericAccel 摄入 descriptor/request payload、decode、micro-op schedule、completion/result 写回 guest-visible memory。

这是系统亮点。需要改的是：L4 不应只是“通过/不通过 proof gate”，还应该输出可用于 DSE 的 interface metrics。

SystemC/TLM 的标准定位是 architecture analysis、software development、performance analysis 和 hardware verification 的 virtual prototyping/model exchange 框架。([systemc.org][14])
gem5 则是用于系统架构、微架构、系统软件和运行时优化研究的模块化平台。([GitHub][15])
所以你的 L4 层应该系统化地记录软件/接口开销，而不是只证明路径存在。

### 修改方向

把 L4 artifact 固化成：

```text
descriptor_trace.jsonl
mmio_trace.jsonl
dma_trace.jsonl
queue_trace.jsonl
completion_trace.jsonl
host_runtime_trace.jsonl
accelerator_uarch_trace.jsonl
l4_proof.json
l4_interface_metrics.json
```

最小 `l4_interface_metrics.json`：

```yaml
host_submit_latency_ms
descriptor_decode_latency_ms
mmio_count
mmio_total_latency_ms
dma_submit_count
dma_bytes
dma_stall_ms
queue_wait_ms
accelerator_busy_ms
accelerator_idle_due_to_host_ms
completion_latency_ms
polling_overhead_ms
interrupt_overhead_ms
software_visible_latency_ms
```

这样 L4 的价值才能被 feedback loop 使用。

---

## 12. CoDesignCandidate 不能长期停留在“规划”，需要尽快接入 Step2

系统总览已经提出 `CoDesignCandidate`，用来表达 software stack、compiler lowering、runtime schedule、descriptor protocol、memory policy。
这非常关键，因为你做的是异构系统 DSE，不只是 accelerator 参数搜索。

问题是详细规范的 Step2 contract 仍然主要围绕 `DesignPoint / MappingPlan / DataPlacement / SchedulingPolicy`，而 `CoDesignCandidate` 还没有完全成为 Step2 的一等输出。

### 修改方向

把 Step2 输出升级为：

```text
design_point.json
codesign_candidate.json
runtime_schedule.json
descriptor_protocol.json
memory_policy.json
compiler_lowering.json
```

其中 `DesignPoint` 负责硬件和 mapping，`CoDesignCandidate` 负责软件/接口/运行时组合。

建议边界：

```text
DesignPoint:
  workload + architecture + mapping + data placement + schedule + precision

CoDesignCandidate:
  design_point + software stack + compiler lowering + runtime policy
  + descriptor protocol + DMA/MMIO/completion + host/device memory policy
```

这样 L3 可以消费 `DesignPoint`，L4 可以消费 `CoDesignCandidate`，二者不会混乱。

---

## 13. Debug/System Test 侧车设计正确，但需要防止和 Evidence 混淆

全局文档把 Debug/System Test Layer 设计为侧车层，默认 diagnostic evidence，只有通过 repeatability、provenance、claim validation 和 adjudication 后才可能升级。
这个方向对。

需要补的是 debug evidence 的结构化语义。否则 debug trace 会慢慢混入 trusted evidence。

### 修改方向

新增：

```yaml
DebugEvidenceBundle:
  debug_session_id
  linked_trial_id
  diagnostic_only: true
  captured_artifacts
  invariants_checked
  reproducibility_status
  promotion_request:
    requested_claim_type
    required_additional_evidence
```

默认规则：

```text
debug evidence cannot update trusted ranking
debug evidence can create bug reports
debug evidence can request re-simulation
debug evidence can become claim evidence only through adjudicator
```

---

## 14. Distributed compatibility 保留字段可以，但不要让它污染当前 runtime

全局文档已经明确：当前只有分布式拓扑和字段预留，不具备 distributed simulation runtime，不得声称支持 HLA/RTI federation 或 optimistic rollback。
这是正确的。

系统修改建议是把 distributed 字段放到 optional namespace，避免每个 artifact 都携带半实现语义：

```yaml
experimental_distributed:
  node_id
  clock_domain
  timebase
  trace_partition_id
  simulator_adapter
  failure_domain
```

并在 schema 中标记：

```yaml
status: reserved_not_executable
```

---

## 15. Failure recovery / timeout / resume 需要成为系统核心能力

DSE 系统一定会遇到：

* simulation timeout；
* backend crash；
* invalid candidate；
* memory overflow；
* artifact missing；
* partial result；
* cluster preemption；
* long-running campaign interruption。

AutoDSE 文档中也提醒，HLS tool assessment 会出现大量 timeout，需要保存 explored design points 并支持 resume。([UCLA VAST][16])
custodian 的系统定位就是对长任务进行错误检查、作业管理和恢复。([materialsproject.github.io][17])

### 修改方向

新增 `FailurePolicy`：

```yaml
FailurePolicy:
  timeout_s
  retry_count
  retry_on:
    - simulator_crash
    - transient_io
    - queue_preempted
  no_retry_on:
    - schema_invalid
    - legality_violation
    - missing_binding
  recovery_action:
    - resubmit_same
    - downgrade_candidate
    - request_lower_fidelity
    - block_family
    - increase_timeout
```

并且每个 Trial 都必须能从 immutable artifacts 恢复，而不是从 Python 对象恢复。

---

## 16. Power / energy / area 现在不应只是 optional metric，需要 model confidence

你的系统目标里有 latency、energy、data movement、utilization、power/area feasibility。
但系统总览也承认时钟、复位、功耗章节存在但内容未冻结。

系统修改方向不是马上做精确功耗，而是给每个 metric 加 confidence 和 model source：

```yaml
Metric:
  name
  value
  unit
  source:
    analytical | tlm | systemc | gem5 | synthesis_report | rtl | measured
  confidence:
    low | medium | high
  calibration_ref
  valid_for_claim_types
```

例如：

```yaml
energy_j:
  value: 0.23
  source: analytical_action_count
  confidence: low
  calibration_ref: null
  valid_for_claim_types: ["predicted", "tradeoff_hint"]
```

这样 report 不会误把未校准 energy 当作 trusted energy。

---

## 17. 我建议的系统级重构目标图

保留你的 Step1/2/3/Reporting，但上层控制面改成这样：

```text
                         ┌────────────────────┐
                         │ Campaign Manager   │
                         │ objectives/budget  │
                         └─────────┬──────────┘
                                   │
                                   ▼
┌──────────────┐       ┌────────────────────┐       ┌───────────────────┐
│ Profile /    │──────▶│ Workload IR +      │──────▶│ Architecture       │
│ Importer     │       │ Lowering Registry  │       │ Capability Catalog │
└──────────────┘       └────────────────────┘       └─────────┬─────────┘
                                                               │
                                                               ▼
                                                     ┌───────────────────┐
                                                     │ Search Policy     │
                                                     │ plugins           │
                                                     └─────────┬─────────┘
                                                               │ candidates
                                                               ▼
                                                     ┌───────────────────┐
                                                     │ Trial State       │
                                                     │ Machine / Ledger  │
                                                     └─────────┬─────────┘
                                                               │ promoted
                          ┌────────────────────────────────────┴────────────────────────────┐
                          ▼                                                                 ▼
              ┌────────────────────┐                                           ┌────────────────────┐
              │ L3 SystemC Adapter │                                           │ L4 gem5 Adapter    │
              │ timing/resource    │                                           │ software-visible   │
              └─────────┬──────────┘                                           └─────────┬──────────┘
                        │ evidence                                                       │ evidence
                        └──────────────────────────┬──────────────────────────────────────┘
                                                   ▼
                                      ┌────────────────────────┐
                                      │ Evidence Adjudicator   │
                                      │ verdict/claim gate     │
                                      └───────────┬────────────┘
                                                  ▼
                                      ┌────────────────────────┐
                                      │ Calibration + Feedback │
                                      │ ranking/frontier/model │
                                      └───────────┬────────────┘
                                                  ▼
                                      ┌────────────────────────┐
                                      │ Reporting Layer        │
                                      │ trusted/predicted/etc. │
                                      └────────────────────────┘
```

这不是推倒重来，而是把你现有模块从“阶段脚本”提升成“状态机 + 插件 + ledger + adjudicator”。

---

## 18. 建议优先级

### P0：立刻改，避免系统债务扩大

1. **拆 Step3 / Evidence adjudication / Reporting。**
   Step3 不再直接生成 final report；Step3 只仿真，Evidence 层裁决，Reporting 层表达。

2. **冻结 artifact canonical names 和 JSON Schema。**
   Markdown schema 不够，必须有机器可校验 schema。

3. **引入 Campaign / Trial 状态机。**
   所有 candidate lifecycle 状态变化必须落 ledger。

4. **重命名 `numerical_validation.json`。**
   当前 timing estimator 阶段改为 `simulator_consistency_check.json`，避免误导。

5. **冻结 DFT reference profile schema。**
   DFT 字段不进 core，但 DFT profile 必须足够完整。

### P1：中期改，提升系统研究/工程质量

6. **SearchPolicy 插件化。**
   默认 seeded beam，但保留 BOHB、TPE、preference BO、bottleneck-guided、random baseline、NSGA-II 等插件接口。

7. **Capability-based Architecture catalog。**
   用 machine-readable capability 支撑 legality，而不是手写规则。

8. **CalibrationRecord。**
   把 L1/L2/L3/L4 之间误差、rank correlation、valid region 写成 artifact。

9. **L4 interface metrics。**
   L4 不只是 proof gate，还要输出 host overhead、DMA、MMIO、queue stall、completion latency。

10. **FailurePolicy / resume。**
    DSE 运行必须可恢复、可重试、可审计。

### P2：长期扩展

11. **Numerical execution layer。**
    只在 final candidates 或验证模式启用，不要污染 timing-only DSE 主路径。

12. **Debug/SystemTest sidecar。**
    保持 diagnostic-only 默认，不直接进入 ranking。

13. **多 workload 真实 importer。**
    DFT 主证明闭合后，再扩 ONNX、MatrixMarket、stencil DSL、query plan 等。

14. **Distributed runtime。**
    当前只保留 reserved namespace，不要提前承诺执行能力。

---

## 19. 最终判断

系统不需要整体推翻。你的核心方向是对的，尤其是这三点很强：

1. **domain-neutral core + profile/importer 边界**；
2. **L1/L2/L3/L4 多保真分层**；
3. **evidence-backed claim gate，防止 predicted-only / smoke-only 变成最终结论**。

但系统现在最需要补的是：

> **把“文档定义的流程”升级为“可执行的 DSE 控制平面”：Campaign/Trial 状态机、schema 固化、artifact/provenance ledger、search policy 插件、calibration record、evidence adjudicator、failure recovery。**

如果只做一个重构，我建议先做：

```text
Campaign + Trial Ledger
        +
Canonical Artifact Schema
        +
Evidence Adjudicator
        +
Calibration/Feedback Records
```

这四个改完后，你的系统会从“能跑 full-flow pilot 的框架”变成“可以长期扩展、复现、比较、审计的 DSE 平台”。

[1]: https://arxiv.org/abs/1504.01163?utm_source=chatgpt.com "AiiDA: Automated Interactive Infrastructure and Database for Computational Science"
[2]: https://json-schema.org/specification?utm_source=chatgpt.com "JSON Schema - Specification [#section]"
[3]: https://www.w3.org/TR/prov-dm/?utm_source=chatgpt.com "PROV-DM: The PROV Data Model - World Wide Web Consortium (W3C)"
[4]: https://arxiv.org/abs/2002.11054?utm_source=chatgpt.com "MLIR: A Compiler Infrastructure for the End of Moore's Law"
[5]: https://arxiv.org/abs/2006.06762?utm_source=chatgpt.com "[2006.06762] Ansor: Generating High-Performance Tensor Programs for ..."
[6]: https://accelergy.mit.edu/timeloop.pdf?utm_source=chatgpt.com "Timeloop: A Systematic Approach to DNN Accelerator Evaluation"
[7]: https://arxiv.org/pdf/1805.02566v3?utm_source=chatgpt.com "A Data-Centric Approach for Modeling and Estimating Efﬁciency of ..."
[8]: https://dl.acm.org/doi/fullHtml/10.1145/3427377?utm_source=chatgpt.com "Bayesian Optimization for Efficient Accelerator Synthesis"
[9]: https://www.researchgate.net/profile/Huizhen-Kuang/publication/377911596_HGBO-DSE_Hierarchical_GNN_and_Bayesian_Optimization_based_HLS_Design_Space_Exploration/links/66487550bc86444c72e872db/HGBO-DSE-Hierarchical-GNN-and-Bayesian-Optimization-based-HLS-Design-Space-Exploration.pdf?utm_source=chatgpt.com "HGBO-DSE: Hierarchical GNN and Bayesian Optimization based HLS Design ..."
[10]: https://arxiv.org/abs/1807.01774?utm_source=chatgpt.com "BOHB: Robust and Efficient Hyperparameter Optimization at Scale"
[11]: https://commit.csail.mit.edu/papers/2014/ansel-pact14-opentuner.pdf?utm_source=chatgpt.com "OpenTuner: An Extensible Framework for Program Autotuning"
[12]: https://www.cse.cuhk.edu.hk/~byu/papers/C238-ICCAD2024-RankTuner.pdf?utm_source=chatgpt.com "RankTuner: When Design Tool Parameter Tuning Meets Preference Bayesian ..."
[13]: https://vlsiarch.eecs.harvard.edu/software/aladdin?utm_source=chatgpt.com "Aladdin | Harvard Architecture, Circuits and Compilers"
[14]: https://systemc.org/overview/systemc-tlm/?utm_source=chatgpt.com "SystemC Transaction Level Modeling (TLM)"
[15]: https://github.com/gem5/gem5?utm_source=chatgpt.com "GitHub - gem5/gem5: The official repository for the gem5 computer ..."
[16]: https://ucla-vast.github.io/AutoDSE/?utm_source=chatgpt.com "AutoDSE Tutorial | AutoDSE"
[17]: https://materialsproject.github.io/custodian/?utm_source=chatgpt.com "Home | custodian"
