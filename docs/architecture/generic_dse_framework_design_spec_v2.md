# 通用 DSE 框架专业设计规范 v2：以 gem5+SystemC 为可信核心的闭环架构探索系统

> **文档版本**: v2.0  
> **日期**: 2026-05-09  
> **状态**: OpenSpec 设计定稿候选  
> **对应 OpenSpec change**: `enhance-generic-dse-framework-spec`  
> **替代/上游文档**: `docs/architecture/generic_dse_framework_design_spec_v1.md`  
> **核心变化**: v1 的“多保真 DSE 框架”升级为“SystemC/gem5+SystemC evidence-backed 闭环优化 DSE 系统”。

---

## 0. 执行摘要

本规范定义一个用于复杂异构加速系统的端到端 Design Space Exploration（DSE）框架。最终目标不是只生成候选设计或 analytical Pareto 图，而是完整跑通：

```text
workload ingestion
    ↓
architecture catalog / design point generation
    ↓
mapping search with screening
    ↓
SystemC or gem5+SystemC simulation
    ↓
simulation feedback updates search
    ↓
trusted final analysis report with claim-to-evidence links
```

核心原则：

1. **SystemC/gem5+SystemC 是可信核心**：L1/L2 analytical/TLM 只能用于初筛、排序建议和不确定性估计，不能作为最终可信结论。
2. **闭环优化**：初筛模型提出候选 architecture/mapping，SystemC/gem5+SystemC 仿真反馈更新 ranking、surrogate、pruning 和下一轮候选生成。
3. **Architecture catalog 可扩展**：本地 architecture 当前不完整，因此 schema 必须支持未来新增 Host/FPGA/Chip/CIM/GPU/ASIC/custom 架构族和 SystemC binding。
4. **Mapping 是算法问题**：系统必须搜索 workload node、tensor、memory、schedule、fallback 到硬件资源的映射，而不是只手写固定 mapping。
5. **Evidence-backed final report**：最终报告里的每条可信 claim 都必须指向 evidence id、输出文件、run manifest 和 replay metadata。

---

## 1. 顶层完成定义

### 1.1 系统完成态

系统 SHALL 在给定 workload family 和 architecture catalog 后完成以下闭环：

1. 读取 workload / trace / synthetic graph。
2. 生成合法 architecture instances 和完整 DesignPoints。
3. 构造 mapping search space。
4. 用 L1/L2/surrogate 初筛候选。
5. 将候选提交到 SystemC 或 gem5+SystemC。
6. 收集 evidence artifacts。
7. 用高保真结果反馈更新搜索。
8. 达到收敛或预算耗尽。
9. 输出最终分析报告。

### 1.2 不完整状态

以下状态 MUST NOT 被称为完整 DSE 结果：

| 状态 | 允许表述 | 禁止表述 |
|---|---|---|
| 只有 L1/L2 预测 | candidate / predicted-only | final best architecture |
| SystemC backend fixed stub | bring-up diagnostic only | measured architecture result |
| gem5 only MMIO fixed timing | L4 stub | full-system co-simulation |
| architecture 无 binding | candidate-only | trusted final design |
| final report 无 evidence id | draft summary | auditable DSE conclusion |

---

## 2. 系统上下文

### 2.1 研究对象

本 DSE 系统服务于 DFT 加速系统探索，当前主线是 QE SCF/subspace diagonalization shell：

```text
rho -> Veff
while bands not converged:
    h_psi
    s_psi
    build H_sub / S_sub
    cdiaghg / generalized Hermitian eigensolver
    refresh / residual -> P_next
psi -> rho_out
mix rho / update Veff
```

长期系统对象是：

```text
Host + FPGA + Chip/CIM + optional CPU/GPU/ASIC baselines
```

### 2.2 当前设计约束

- generalized Hermitian eigensolver 是主路径，`S_sub` 不能被忽略。
- complex FP64 GEMM 是关键算力底座。
- 当前本地 architecture catalog 不完整，必须支持后续补充。
- 不得把 `/Users/xixilys/project/qe-7.5` 作为修改目标。
- 新 QE trace 生成不是本设计定稿的目标；优先使用现有 evidence。

---

## 3. 顶层架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         DSE Orchestrator                             │
│                                                                     │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────┐   │
│  │ Workload      │   │ Architecture   │   │ Mapping Optimizer     │   │
│  │ Ingestion     │──▶│ Catalog        │──▶│ + Screening Models    │   │
│  └──────────────┘   └────────────────┘   └──────────┬───────────┘   │
│                                                       │ candidates    │
│                                                       ▼               │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────┐   │
│  │ Final Report │◀──│ Evidence Store │◀──│ Simulation Scheduler  │   │
│  │ + Claims     │   │ + Run Artifacts│   └──────────┬───────────┘   │
│  └──────────────┘   └────────────────┘              │               │
└──────────────────────────────────────────────────────┼───────────────┘
                                                       │
                     ┌─────────────────────────────────┴────────────────┐
                     │                                                  │
                     ▼                                                  ▼
       ┌─────────────────────────┐                       ┌────────────────────────┐
       │ L3 SystemC Standalone   │                       │ L4 gem5 + SystemC      │
       │ architecture simulation │                       │ HW/SW co-debug path    │
       └─────────────────────────┘                       └────────────────────────┘
```

### 3.1 Stage contract

| Stage | Input | Output | Persistent artifact |
|---|---|---|---|
| Workload ingestion | trace / config / synthetic graph | `WorkloadGraph` | `workload_graph.json` |
| Architecture generation | catalog + parameters | `ArchitectureInstance` | `architecture.json` |
| DesignPoint assembly | workload + architecture | `DesignPoint` | `design_point.json` |
| Mapping search | graph + architecture | candidate mappings | `mapping_candidates.jsonl` |
| Screening | candidate set | predictions + uncertainty | `screening_results.jsonl` |
| Promotion | screening + policy | sim queue | `promotion_decisions.jsonl` |
| Simulation | sim queue | SystemC/gem5 results | run directory |
| Feedback update | sim samples | updated search state | `search_state.json` |
| Final report | evidence store | trusted conclusions | `final_analysis.md/json` |

---

## 4. Core data model

### 4.1 WorkloadPackage

```yaml
WorkloadPackage:
  workload_id: string
  workload_family: dft_qe | synthetic | generic
  source:
    kind: trace | generated | hand_authored
    path: optional string
    provenance: string
  graph: ComputeGraph
  domain_metadata:
    qe_case: optional string
    npw: optional int
    nkb: optional int
    nbands: optional int
    nfft: optional int
    precision: string
```

Requirement:

- Workload metadata SHALL preserve source, units, and domain attributes.
- DFT/QE-specific metadata SHALL remain adapter attributes, not core IR requirements.

### 4.2 Architecture catalog

Implementation note: the concrete P2 catalog schema, seed families, validation checks, status labels, simulation binding gates, and minimum DesignPoint payload are implemented in `dse_v2/architecture/catalog.py` and documented in `docs/architecture/generic_dse_architecture_catalog_p2.md`.

```yaml
ArchitectureCatalog:
  version: string
  families:
    - ArchitectureFamily
  component_types:
    - ComponentType
  bindings:
    - SimulationBinding
```

```yaml
ArchitectureFamily:
  family_id: string
  description: string
  parameters:
    - name: string
      type: int | float | enum | bool | string
      allowed_values: optional list
      range: optional [min, max]
      default: any
  component_template:
    host: HostTemplate
    fpga: optional FPGATemplate
    chip: optional ChipTemplate
    accelerators: list[AcceleratorTemplate]
    memory: MemoryHierarchyTemplate
    interconnect: InterconnectTemplate
  constraints:
    - ConstraintRule
  binding_requirements:
    systemc: optional BindingRequirement
    gem5_systemc: optional BindingRequirement
```

```yaml
ArchitectureInstance:
  architecture_id: string
  family_id: string
  parameters: map[string, any]
  components: list[ComponentInstance]
  memory_hierarchy: MemoryHierarchy
  interconnect: InterconnectTopology
  constraints: ConstraintSet
  simulation_binding:
    systemc_binding_id: optional string
    gem5_binding_id: optional string
    binding_status: implemented | unverified | prototype | stub | planned | unsupported
  trusted_final_eligible: bool
```

### 4.3 Initial architecture families

| Family | Purpose | Trusted eligibility rule |
|---|---|---|
| `cpu-only-baseline` | software reference | trusted only with calibrated baseline/SystemC equivalent |
| `host-fpga-minimal` | minimal offload | requires SystemC binding |
| `host-fpga-cim` | CIM/GEMM acceleration | requires CIM op model binding |
| `diag-heavy` | stronger eigensolver cluster | requires eigensolver SystemC model |
| `streaming-heavy` | h_psi/s_psi/operator sweep optimized | requires streaming/buffer model |
| `memory-rich` | large SRAM/HBM/buffer exploration | requires memory contention model |
| `low-power` | energy/power constrained | requires power model confidence label |
| `balanced` | Pareto-balanced template | requires all relevant component bindings |
| `debug` | maximal observability | may be slower; used for co-debug evidence |
| `future-custom` | extension hook | candidate-only until binding exists |

### 4.4 DesignPoint

```yaml
DesignPoint:
  design_point_id: string
  workload_id: string
  architecture: ArchitectureInstance
  mapping: MappingPlan
  data_placement: DataPlacementPlan
  scheduling_policy: SchedulingPolicy
  precision_policy: PrecisionPolicy
  fallback_policy: FallbackPolicy
  simulation_config: SimulationConfig
  output_config: EvidenceConfig
  constraints: ConstraintSet
```

A DesignPoint SHALL be complete enough to replay without hidden Python process state.

---

## 5. Mapping search design

### 5.1 Formal problem

Given:

```text
G = workload DAG with nodes V and edges E
R = architecture resources / components
T = tensors / data objects
C = constraints
O = objectives
```

Find:

```text
m_v: V -> R                     # operator/resource mapping
m_t: T -> memory/buffer levels   # data placement
s: task schedule / pipeline plan
f: fallback policy
```

Optimize:

```text
latency, energy, data movement, utilization balance, power/area feasibility
```

Subject to:

```text
operator support, precision support, memory capacity, bandwidth, dependency order,
communication route, buffer pressure, gem5/SystemC binding availability
```

### 5.2 Legality matrix

The optimizer SHALL first build:

```text
L[node_id][resource_id] -> {legal: bool, reasons: list[string]}
```

Reasons include:

- unsupported operator
- unsupported precision
- insufficient local memory
- missing communication route
- missing simulation binding
- power/area budget violation
- architecture-specific forbidden placement

### 5.3 Seed mappings

Initial seed mappings SHALL include domain and baseline policies:

| Seed | Description |
|---|---|
| `host-baseline` | all nodes on CPU/host baseline |
| `operator-sweep-fpga` | h_psi/s_psi on FPGA streaming/operator cluster |
| `hardware-diag` | diagonalize/cdiaghg on eigensolver cluster |
| `all-offload` | all supported nodes offloaded |
| `cim-heavy` | GEMM/projector-heavy nodes on CIM/GEMM arrays |
| `streaming` | prioritize pipeline and dataflow continuity |
| `batch` | prioritize batch kernels and lower control overhead |
| `fallback-mixed` | unsupported/high-risk ops fallback to host |
| `debug-observable` | maximize probes and traceability |

### 5.4 Search operators

| Operator | Meaning |
|---|---|
| `move(node, resource)` | move one op to another legal resource |
| `swap(node_a, node_b)` | exchange resources |
| `fuse(nodes)` | fuse adjacent nodes into pipeline task |
| `split(task)` | split fused task |
| `stage_shift(task, stage)` | move task across pipeline stage |
| `data_place(tensor, memory)` | change tensor placement |
| `schedule_shift(task, slot)` | change schedule ordering |
| `fallback_change(node, policy)` | switch fallback path |
| `arch_tweak(parameter)` | mutate architecture parameter within family bounds |

### 5.5 First algorithm

The first implementation SHOULD use:

```text
domain seed generation
    ↓
legality filtering
    ↓
beam search over mapping + architecture mutations
    ↓
L1/L2/surrogate screening
    ↓
promotion to SystemC/gem5+SystemC
    ↓
feedback update
    ↓
repeat until convergence/budget
```

Pure Bayesian optimization is not the first recommended implementation because the mapping space is highly discrete, legality-constrained, and domain-seed-sensitive. BO/NSGA-II SHALL be added as plug-ins later.

---

## 6. Screening and feedback loop

### 6.1 Screening output

Each screened candidate SHALL produce:

```yaml
ScreeningResult:
  candidate_id: string
  predicted_latency_ms: float
  predicted_energy_j: optional float
  predicted_power_w: optional float
  predicted_data_movement_bytes: float
  predicted_utilization: map[string, float]
  uncertainty: float
  confidence: low | medium | high
  selection_reason: list[string]
  promotion_priority: float
  model_versions: map[string, string]
```

### 6.2 Candidate lifecycle

```text
generated
  → screened
  → promoted
  → scheduled-for-sim
  → simulated
  → finalist | rejected | blocked
  → selected
```

Additional states:

- `predicted-only`: no SystemC/gem5+SystemC evidence.
- `candidate-only`: architecture lacks binding.
- `stub-only`: result uses fixed stub path.

### 6.3 Feedback update

After every high-fidelity sample, the optimizer SHALL update:

1. trusted ranking;
2. Pareto frontier;
3. low-fidelity calibration samples;
4. surrogate model or ranking correction;
5. pruning thresholds;
6. promotion policy;
7. next-candidate generation.

### 6.4 Convergence criteria

The feedback loop may stop when one or more holds:

| Criterion | Example |
|---|---|
| trusted frontier stability | no significant hypervolume improvement for N iterations |
| top-K stability | top-K designs unchanged after M feedback rounds |
| improvement threshold | best trusted latency/energy improvement < epsilon |
| uncertainty reduction | promoted candidate uncertainty below threshold |
| family coverage | required architecture families have at least one simulated sample |
| budget exhaustion | SystemC/gem5+SystemC budget consumed |
| hard blocker | simulator cannot run or binding missing for required family |

Budget exhaustion SHALL be reported as a limitation, not as full convergence.

---

## 7. gem5 + SystemC role

### 7.1 Minimal trusted co-simulation path

```text
software driver / workload launcher
    ↓
command descriptor or request pointer
    ↓
gem5 GenericAccel MMIO/DMA path
    ↓
SystemC binding / generic backend
    ↓
execution metrics + traces
    ↓
completion + result visibility
```

### 7.2 Required semantics

The trusted L4 path SHALL demonstrate:

- command submission;
- descriptor/request ingestion;
- backend invocation;
- workload/mapping/architecture payload consumption;
- completion visible to gem5 software side;
- result/evidence file generation;
- failure diagnostics.

### 7.3 Stub boundary

If GenericAccel only provides MMIO register access and fixed timing completion, its results SHALL be labeled:

```text
stub-only / bring-up-only / not trusted for final performance ranking
```

---

## 8. SystemC evidence contract

### 8.1 Evidence modes

| Mode | Required for | Purpose |
|---|---|---|
| Summary | every trusted final candidate | ranking and metrics verification |
| Debug | finalists, failures, anomalies | bottleneck and co-debug diagnosis |
| Forensic | publication/user-selected audit | replay, waveform/full-trace audit |

### 8.2 Run directory layout

```text
runs/dse/<run_id>/
├── manifest.json
├── artifact_manifest.json
├── verdict.json
├── design_point.json
├── architecture.json
├── mapping.json
├── workload_graph.json
├── simulation_request.json
├── simulation_result.json
├── screening_result.json             # required after P3/P4 search is enabled
├── promotion_decision.json           # required after P3/P4 search is enabled
├── search_state_snapshot.json        # required after P3/P4 search is enabled
├── phase_breakdown.csv
├── resource_summary.csv
├── data_movement_summary.csv
├── systemc_stdout.log
├── systemc_stderr.log
├── gem5.log                         # required for gem5+SystemC runs
├── debug/                           # debug mode
│   ├── event_trace.csv
│   ├── task_timeline.csv
│   ├── buffer_occupancy.csv
│   ├── dma_trace.csv
│   ├── interconnect_trace.csv
│   ├── scheduler_decisions.csv
│   └── assertion_report.json
└── forensic/                        # forensic mode
    ├── replay_command.sh
    ├── environment.json
    ├── git_snapshot.txt
    ├── full_event_trace.csv
    ├── full_resource_trace.csv
    └── waveform.vcd                 # optional if supported
```

For the P0/P1 vertical slice, the minimum trusted SystemC evidence set is:
`manifest.json`, `artifact_manifest.json`, `verdict.json`, `design_point.json`,
`architecture.json`, `mapping.json`, `workload_graph.json`,
`simulation_request.json`, `simulation_result.json`, `phase_breakdown.csv`,
`resource_summary.csv`, `data_movement_summary.csv`, `systemc_stdout.log`, and
`systemc_stderr.log`. Search artifacts become required once mapping search and
feedback optimization are implemented; gem5 logs are required only for a
gem5+SystemC run and MUST be replaced by explicit blocker evidence otherwise.

### 8.3 Manifest schema

```yaml
manifest:
  run_id: string
  run_type: systemc | gem5_systemc
  workload_id: string
  design_point_id: string
  architecture_id: string
  mapping_id: string
  simulator_versions: map[string, string]
  command_line: string
  random_seed: optional int
  started_at: string
  completed_at: string
  status: pass | fail | partial | timeout | blocked
  evidence_mode: summary | debug | forensic
  artifact_paths: map[string, string]
  limitations: list[string]
```

### 8.4 Verdict schema

```yaml
verdict:
  run_id: string
  trusted_for_final_ranking: bool
  status_label: implemented | unverified | prototype | stub | planned | unsupported
  feasibility: feasible | infeasible | unknown
  violations: list[string]
  metrics_available: list[string]
  metrics_unavailable: list[string]
  evidence_gaps: list[string]
```

---

## 9. Final analysis report

### 9.1 Report sections

Final report SHALL contain:

1. Executive summary.
2. Workload and dataset provenance.
3. Architecture catalog scope.
4. Search configuration and budget.
5. Candidate lifecycle summary.
6. Trusted SystemC/gem5+SystemC ranking.
7. Predicted-only candidates appendix.
8. Pareto alternatives.
9. Selected architecture and mapping.
10. Phase breakdown.
11. Data movement and resource utilization.
12. Evidence index.
13. Claim table.
14. Limitations and blocked paths.
15. Replay instructions.

### 9.2 Claim schema

```yaml
Claim:
  claim_id: string
  claim_type: best_architecture | mapping_comparison | bottleneck | feasibility | pareto | convergence | debug | numerical_correctness | limitation
  statement: string
  trust_level: trusted | predicted | untrusted | blocked
  evidence_ids: list[string]
  required_files: list[string]
  metric_values: map[string, any]
  limitations: list[string]
```

### 9.3 Claim evidence table

| Claim type | Required evidence |
|---|---|
| Best architecture | selected design run result, mapping, architecture, verdict, trusted ranking table |
| Mapping comparison | SystemC/gem5 results for both mappings under same workload/config |
| Bottleneck diagnosis | resource summary plus debug trace for memory/DMA/interconnect/compute claim |
| Feasibility | verdict, assertion report or equivalent, violation list, no-deadlock/no-overflow evidence |
| Pareto frontier | trusted result set, objective directions, dominance computation artifact |
| Convergence | search-state snapshots, feedback iterations, budget and stopping reason |
| Debug/replay | manifest, replay command, logs, relevant traces |
| Numerical correctness | output hash/reference comparison/residual error where modeled |
| Stub/unsupported limitation | status boundary and missing binding/feature evidence |

### 9.4 Trusted ranking gate

A candidate SHALL enter trusted final ranking only if:

1. architecture instance has valid simulation binding;
2. mapping is legal;
3. SystemC or gem5+SystemC run completed;
4. verdict marks it trusted for final ranking;
5. evidence files exist or unavailable reasons are explicit;
6. it is not dominated by another trusted candidate under configured objectives unless retained as a trade-off alternative.

---

## 10. Requirement traceability to OpenSpec

| OpenSpec capability | This document sections |
|---|---|
| `generic-dse-ir-contract` | §4 WorkloadPackage / DesignPoint and stage artifact contracts |
| `accelerator-system-description` | §4.2–§4.4 Architecture catalog, families, DesignPoint |
| `multi-fidelity-dse-evaluation` | §6 Screening and feedback loop, §6.4 convergence |
| `generic-simulation-backend` | §7 gem5+SystemC role, §8 evidence contract |
| `dft-qe-workload-adapter` | §2 system context, §9 phase/domain reporting |
| `end-to-end-dse-workflow` | §1, §3, §5, §8, §9 |

---

## 11. Implementation phasing

| Phase | Goal |
|---|---|
| P0 | gem5+SystemC minimum closed loop |
| P1 | evidence artifacts and claim gating |
| P2 | architecture catalog and DesignPoint completeness |
| P3 | mapping search algorithm |
| P4 | screening, simulation feedback, and convergence |
| P5 | final analysis report |
| P6 | validation, documentation, archive readiness |

This phasing matches `openspec/changes/enhance-generic-dse-framework-spec/tasks.md` and should be used to split future implementation `/goal` commands.

---

## 12. Open discussion items

1. Which broad architecture families should be implemented first across Host/FPGA/Chip/CIM/GPU/ASIC/custom options, without privileging any single legacy topology?
2. What is the first gem5+SystemC full-flow QE pilot configuration that covers the SCF loop at timing level?
3. What evidence mode should be default for top-K finalists: debug or forensic?
4. What SystemC/gem5 simulation budget is acceptable per DSE iteration?
5. What convergence threshold should define “best architecture found”: top-K stability, hypervolume, or absolute improvement?
6. Which DFT/QE domain metrics must appear in the first final report?

---

## 13. Document control

| Version | Date | Change |
|---|---|---|
| v2.0 | 2026-05-09 | Reframed generic DSE as SystemC/gem5+SystemC evidence-backed feedback optimization system. |
