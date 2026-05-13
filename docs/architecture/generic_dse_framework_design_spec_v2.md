# 通用 DSE 框架子系统设计规范 v2

> **文档版本**: v2.0  
> **日期**: 2026-05-09  
> **状态**: 子系统详细设计参考  
> **全局入口**: `docs/architecture/generic_dse_global_system_design_v0.md`  
> **OpenSpec 关系**: 本文不是 active change；OpenSpec 只记录有边界的增量变更。  
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
6. **完整仿真硬门槛**：最终检查必须看到完整 SystemC 或 gem5+SystemC full-flow 仿真证据；smoke 只能用于 bring-up 诊断，不能被包装、重命名或混入为完成证据。
7. **通用核心 + DFT 主证明场景**：core schema 保持多 workload 可扩展；当前用 DFT→FPGA reference vertical slice 证明 workload characterization、FPGA mapping/dataflow、memory/runtime、gem5 software-visible evidence 和 claim/reporting 的完整闭环。

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

其中第 5 步必须是真正的 full-flow simulation：standalone SystemC 至少要跑所选 `WorkloadPackage` 声明的完整工作负载或经声明的等价端到端工作流；gem5 L4 必须通过真实 descriptor/request/decode/microarchitecture execution/completion proof。DFT→FPGA 可以作为当前主证明 reference profile/importer，但只有在其 DFT config、graph coverage、FPGA deployment、runtime/interface 和 evidence artifacts 完整时，才满足完整仿真定义。任何 smoke-only、fixed-timing、MMIO bring-up、driver hello、legacy B3 smoke 或等价诊断路径都不满足“完整仿真”定义。

### 1.2 不完整状态

以下状态 MUST NOT 被称为完整 DSE 结果：

| 状态 | 允许表述 | 禁止表述 |
|---|---|---|
| 只有 L1/L2 预测 | candidate / predicted-only | final best architecture |
| smoke-only / bring-up-only | diagnostic / health check | completed simulation / trusted evidence |
| SystemC backend diagnostic replay path | bring-up diagnostic only | measured architecture result |
| gem5 only MMIO fixed timing | MMIO bring-up only | full-system co-simulation |
| architecture 无 binding | candidate-only | trusted final design |
| final report 无 evidence id | draft summary | auditable DSE conclusion |

---

## 2. 系统上下文

### 2.1 研究对象

本 DSE 系统的研究对象是**任意可表达为计算图的工作负载在异构系统上的设计空间探索**，不是 QE-only 工作流。当前工程和论文主线以 DFT→FPGA 作为第一条完整证明场景，但顶层输入仍 SHALL 是 domain-neutral 的 `WorkloadPackage` / `ComputeGraph`，可由不同 workload profile/importer 生成或导入：

```text
source workload
  ├── ML / tensor graph
  ├── DFT / QE SCF graph
  ├── stencil / FFT / signal-processing graph
  ├── graph analytics / sparse linear algebra graph
  ├── database / vector-search pipeline
  └── user-defined scientific computation graph
        ↓ profile / importer
WorkloadPackage + ComputeGraph + provenance
```

长期系统对象是：

```text
Host + FPGA + Chip/CIM + optional CPU/GPU/ASIC/distributed baselines
```

DFT/QE SCF/subspace diagonalization shell 是当前主证明 reference profile/importer 和回归 fixture，用于证明 generic DSE pipeline、SystemC/gem5+SystemC evidence、claim gate 与反馈闭环可以在真实科学计算配置上跑通。DFT/QE 节点名或参数（如 `h_psi`、`diagonalize`、`npw`、`nbands`、`nfft`）不得成为 core IR、generic mapping search 或 final-report schema 的必需字段。

### 2.2 当前设计约束

- Core workload IR 必须保持 domain-neutral：任意 workload 只要能提供 nodes、edges、tensor/resource metadata、cost hints 或 cost-model binding，就能进入 DSE。
- Workload profile/importer 可以提供专用 metadata、calibration、mapping policy 和 report metric，但这些能力必须通过 profile/importer 注册，不能写死在 core pipeline。
- DFT reference profile/importer 的领域约束只适用于 reference lane；不得传播为 core 默认规则。
- 当前本地 architecture catalog 不完整，必须支持后续补充。
- 不得把 `/Users/xixilys/project/qe-7.5` 作为修改目标。
- 新 vendor-specific DFT trace 生成不是本设计定稿的硬门槛；优先使用可复现 DFT config / synthetic reference fixture / 现有 evidence 闭合主证明链。

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

### 3.0 Closed-loop flow diagram

```text
┌───────────────┐
│ Workload      │
│ package       │
└───────┬───────┘
        │ workload graph + provenance
        ▼
┌───────────────┐      architecture parameters      ┌────────────────┐
│ Architecture  │──────────────────────────────────▶│ DesignPoint    │
│ catalog       │                                   │ assembly       │
└───────┬───────┘                                   └───────┬────────┘
        │ family/instance/binding status                    │ replayable candidate
        ▼                                                   ▼
┌───────────────┐      legal mappings + seeds        ┌────────────────┐
│ Catalog       │──────────────────────────────────▶│ Mapping search │
│ validation    │                                   │ + screening    │
└───────────────┘                                   └───────┬────────┘
                                                            │ promoted candidates
                                                            ▼
                                                    ┌────────────────┐
                                                    │ SystemC or     │
                                                    │ gem5+SystemC   │
                                                    │ simulation     │
                                                    └───────┬────────┘
                                                            │ high-fidelity samples
                                                            ▼
                                                    ┌────────────────┐
                                                    │ Feedback update│
                                                    │ + convergence  │
                                                    └───────┬────────┘
                                                            │ trusted evidence index
                                                            ▼
                                                    ┌────────────────┐
                                                    │ Final report   │
                                                    │ + claim gate   │
                                                    └────────────────┘
```

The feedback edge from simulation back to mapping/search is mandatory for a
trusted DSE conclusion. A one-shot analytical ranking followed by a prose
summary is a partial result, not a complete architecture recommendation.

### 3.1 Stage contract

| Stage | Input | Output | Persistent artifact |
|---|---|---|---|
| Workload ingestion | domain source / trace / config / graph IR | `WorkloadPackage` + `ComputeGraph` | `workload_package.json`, `workload_graph.json` |
| Architecture generation | catalog + parameters | `ArchitectureInstance` | `architecture.json` |
| Catalog validation | architecture instance + binding metadata | eligibility verdict | `architecture_validation.json` |
| Graph normalization/lowering | `WorkloadPackage` + `ComputeGraph` | executable graph / lowering verdict | `graph_lowering_report.json`, optional `executable_graph.json` |
| DesignPoint assembly | workload + architecture | `DesignPoint` | `design_point.json` |
| Legality construction | executable graph + architecture | node/resource legality matrix | `mapping_legality_matrix.json` |
| Seed generation | executable graph + architecture + generic/domain mapping policy | initial mappings | `mapping_seed_set.json` |
| Mapping search | executable graph + architecture | candidate mappings | `mapping_candidates.jsonl` |
| Screening | candidate set | predictions + uncertainty | `screening_results.jsonl` |
| Promotion | screening + policy | sim queue | `promotion_decisions.jsonl` |
| Simulation | sim queue | SystemC/gem5 results | run directory |
| Feedback update | sim samples | updated ranking/calibration/search state | `mapping_feedback_state.json` |
| Convergence check | feedback state + budget | stop/continue decision | `convergence_status.json` |
| Final report | evidence store | trusted conclusions | `final_analysis.md/json` |

---

## 4. Core data model

### 4.1 WorkloadPackage

```yaml
WorkloadPackage:
  schema_version: string
  workload_id: string
  workload_family: string          # e.g. ml_tensor, stencil, sparse_la, graph_analytics, database_pipeline, custom
  source:
    kind: trace | generated | hand_authored | imported_graph | external_ir
    path: optional string
    provenance: string
    generator: optional string
  profile:
    profile_id: string             # e.g. sparse_la, ml_tensor, dynamic_custom
    profile_version: string
  importer:
    importer_id: string            # e.g. generic_json, ml_onnx, matrix_market, custom_python
    importer_version: string
    claim_boundary: string
  graph: ComputeGraph
  constraints:
    objective_hints: list[string]
    precision_policy: optional string
    memory_budget_bytes: optional int
    latency_budget_ms: optional float
  calibration:
    datasets: list[map[string, any]]
    confidence: optional string
  domain_metadata: map[string, any] # profile/importer-owned opaque metadata; never required by core DSE
```

Requirement:

- Workload metadata SHALL preserve source, units, profile/importer identity, generator/provenance, and domain attributes.
- Core DSE SHALL consume only generic fields: graph nodes, edges, tensor specs, operator strings, cost estimates or cost-model bindings, constraints, and mapping policy hooks.
- Domain-specific metadata such as QE `npw`, `nkb`, `nbands`, `nfft`, k-point/spin, ML batch shape, sparse matrix format, or database query shape SHALL remain profile/importer-owned attributes, not core IR requirements.
- Every workload profile/importer SHALL declare its claim boundary: full workload, reduced workload, synthetic regression, imported trace, or diagnostic-only. Reduced/diagnostic workloads SHALL NOT satisfy full-flow final checks.

### 4.1.1 Generic ComputeGraph model

`ComputeGraph` SHALL be a domain-neutral computation graph, not a QE-specific or DAG-only workload shell. It must support:

- open `op_type` strings and opaque profile/importer attributes rather than fixed operator enums;
- typed nodes with tensor/resource/cost-model metadata;
- typed edges for data, control, state, streaming, resource, and ordering dependencies;
- hierarchical subgraphs or regions for loop bodies, pipeline stages, fused kernels, and call-like reusable graph fragments;
- declared iteration/feedback constructs with bounds, convergence criteria, trace-derived trip counts, or importer-provided summary models;
- explicit source/sink, stateful side-effect, and external I/O annotations when those affect scheduling or correctness claims.

The core validator SHALL reject only ambiguous graph semantics, not every non-DAG
shape. Unannotated dependency cycles are invalid. Declared loop/feedback/streaming
cycles are valid at the `ComputeGraph` level only when they include enough
metadata to lower or summarize them for evaluation. Before L1/L2/L3/L4 execution,
the workflow SHALL produce a normalized executable graph or task graph whose
ordering, iteration policy, approximations, and unsupported constructs are
recorded in `graph_lowering_report.json`.

### 4.1.2 Workload profile/importer registry

The framework SHALL route workload ingestion through separate profile and importer registries rather than hardcoded workload branches. Minimum importer interface:

```yaml
WorkloadImporter:
  importer_id: string
  supported_source_kinds: list[string]
  compatible_profiles: list[string]
  import_workload(source, profile, parameters) -> WorkloadPackage
  validate_workload_package(package) -> validation_report
```

Built-in importers MAY include `generic_json` plus optional reference importers, but adding `ml_onnx`, `stencil`, `sparse_la`, or user-defined importers SHALL NOT require changing core IR classes, generic simulator request schema, report validator, or mapping-search core.

### 4.1.3 Workload-family workflow contract

Every workload family SHALL be reviewed through the same top-level DSE workflow:

```text
source artifact / trace / graph
  → resolve WorkloadProfile
  → WorkloadImporter.import_workload()
  → WorkloadPackage validation
  → ComputeGraph validation
  → graph lowering / executable-view generation
  → architecture catalog filtering
  → legality matrix + mapping search
  → SystemC or gem5+SystemC full-flow simulation
  → profile/importer-domain validation where available
  → evidence export + final claim validation
```

The workflow is generic, but each profile SHALL declare the family-specific
items needed by the generic stages:

```yaml
WorkloadProfile:
  profile_id: string
  profile_version: string
  workload_family: string
  accepted_sources: list[string]
  graph_pattern: dag | hierarchical | bounded_loop | streaming | dynamic_summary | custom
  required_coverage: list[node_id | region_id | phase_id]  # optional; defaults described below
  lowering_policy: identity_dag | unroll | summarize | backend_native | unsupported
  default_mapping_policies: list[policy_id]
  domain_validation:
    timing_only_allowed: bool
    correctness_artifacts: list[string]
    unavailable_metric_labels: list[string]
  final_claim_boundary: full_workload | reduced | synthetic | trace_only | diagnostic_only
```

Coverage is profile-owned, not globally DFT/QE-owned:

- `dft_fpga_reference` / `dft_qe_reference` MAY use profile-declared DFT/SCF phase coverage (`fft`, `gemm`, `reduction`, `eigensolver_shell`, `host_fpga_transfer`, or QE-like `h_psi`, `s_psi`, diagonalization/rotation/refresh/residual/density phases when present).
- Non-reference profiles SHALL use explicit `required_coverage` when provided.
- If a profile does not provide explicit coverage, the default full-workload coverage SHALL be the lowered executable graph nodes or regions.
- Missing coverage blocks trusted full-workload claims regardless of simulator exit code.

The following table is the required family workflow baseline for later Step2+
implementation. A new profile/importer may specialize these rows, but it must still emit
`WorkloadPackage`, `ComputeGraph`, `graph_lowering_report.json`, mapping artifacts,
simulation artifacts, and claim-gated final report evidence.

| Workload family | Accepted sources | Graph / lowering workflow | Mapping workflow | Simulation evidence | Domain validation / final claim boundary |
| --- | --- | --- | --- | --- | --- |
| `ml_tensor` | ONNX-like graph, framework export, hand-authored tensor graph, generic JSON | Mostly DAG tensor operators; preserve shapes, dtype/layout, batch/sequence dimensions; bounded dynamic axes require declared summaries; unsupported dynamic control is non-final | host baseline, GPU/tensor accelerator, FPGA systolic, CIM/near-memory for eligible ops, memory-placement variants | executable node events, tensor data movement, utilization, precision policy, `workload_package.json`, `graph_lowering_report.json` | Timing/resource claims are allowed from SystemC/gem5+SystemC; accuracy, numerical tolerance, or model-output equivalence requires profile/importer reference-output evidence |
| `sparse_la` | MatrixMarket/CSR/CSC/COO/block-sparse descriptors, solver trace, generic sparse JSON | SpMV, gather/scatter, reduction, preconditioner and solver loops; sparse format and nnz metadata remain importer-owned; bounded solver loops may be summarized | CPU baseline, FPGA sparse pipeline, memory-rich/HBM, near-memory/CIM for gather/reduce where legal | sparse tensor/index byte movement, node/loop coverage, memory pressure, irregular-access summaries | Residual convergence, solver correctness, and reference-vector equivalence require profile/importer residual/reference evidence |
| `stencil_streaming` | stencil DSL, structured-grid config, FFT/signal pipeline, streaming operator graph | grid/halo/tile metadata; time-step loops or streaming feedback edges require bounds, convergence, trace distribution, or summary model; lower by unroll/summary/backend-native stream | streaming-heavy, FPGA pipeline, HBM tile-buffer, overlap DMA/compute, low-power variants | per-stage events, buffer/data movement, tile/halo traffic, summarized recurrence coverage | PDE/signal numerical error, conservation, or output equivalence requires profile/importer validation; unbounded streams are diagnostic only |
| `graph_analytics` | graph format plus algorithm config, traversal trace, GNN/message-passing graph | frontier/traversal/update/reduction nodes; loops declare iteration/convergence/trace distribution; graph format metadata stays importer-owned | CPU baseline, memory-rich, graph accelerator/FPGA, near-memory frontier/reduction seeds | frontier/update/reduction event coverage, edge/vertex traffic, irregular memory summaries | Traversal/result equivalence, PageRank/SSSP/CC convergence, or GNN output quality requires profile/importer validation |
| `database_vector_search` | query plan, vector index config, relational/vector-search pipeline, synthetic benchmark config | scan/filter/join/aggregate/top-k/distance/search nodes; selectivity/cardinality/index metadata preserved as domain metadata | CPU baseline, GPU distance compute, FPGA filter/top-k, memory-rich/index-resident variants | query-stage timing, index/data movement, selectivity/cardinality assumptions, top-k stage coverage | Query-result equivalence, recall/precision, freshness, or transaction semantics require profile/importer validation; timing-only reports must say correctness unclaimed |
| `dynamic_custom` | custom JSON graph, Python/DSL export, trace-summary workload | arbitrary generic nodes/edges/regions; dynamic control, recursion, or stateful behavior must declare bounds, convergence, trace distribution, summary model, or backend-native support | generic host/capability-greedy, profile-declared seeds only if legality is expressible | executable-view events or explicit unsupported diagnostics; source-to-executable mapping required | Domain correctness is unavailable unless the profile/importer supplies validator artifacts; unsupported dynamics block trusted claims |
| `dft_fpga_reference` / `dft_qe_reference` | DFT config, generated QE-like SCF reference fixture, or declared trace summary | generic ComputeGraph with DFT metadata under profile/importer domain fields; covers FFT, GEMM, reduction, eigensolver shell, SCF-loop summary, host-FPGA transfer; reduced shells must be explicitly diagnostic | FPGA deployment search, host baseline, FFT/GEMM/reduction/eigensolver mapping seeds, dataflow/memory/runtime/interface co-design | DFT region events, tensor/data movement, host-FPGA transfer, descriptor/runtime traces, numerical reference checks where modeled | DFT FP64 residual/density/eigenvector/physics correctness requires profile reference evidence; timing/resource/co-design claims are scoped to the declared DFT config set |

### 4.1.4 Workload workflow acceptance gates

A workload family is accepted for later DSE stages only if all of the following are true:

1. `WorkloadPackage.validate()` passes and includes profile/importer id/version, source provenance, claim boundary, and graph payload.
2. `ComputeGraph.validate()` passes, including structured errors for missing nodes, invalid tensors, and unannotated cycles.
3. `graph_lowering_report.json` is `lowered` and records unsupported constructs, approximations, and source-to-executable mapping.
4. Required coverage resolves to source or executable graph entities.
5. Mapping search can construct a legality matrix over generic node ids/op types and architecture capabilities.
6. SystemC or gem5+SystemC evidence includes every required coverage item for full-workload claims.
7. The final report separates generic timing/resource validation from profile/importer-domain correctness validation.
8. Reduced, sampled, trace-only, synthetic, smoke, or diagnostic workloads remain visible but cannot satisfy trusted final completion or winner claims.


### 4.1.5 Step2 architecture/mapping audit contract

Step2 is the architecture-catalog and mapping-search boundary between Step1
workload lowering and Step3+ simulation/evidence. Step2 begins only after the
Step1 acceptance gates in §4.1.4 pass. It does not parse domain source files and
it does not prove final performance. Its responsibility is to convert the
validated workload handoff into replayable architecture/mapping candidates that
later SystemC or gem5+SystemC runs can consume without hidden state.

#### Step2 input contract

Step2 SHALL consume the following artifacts and fields from Step1:

| Step1 artifact / field | Required Step2 use |
|---|---|
| `workload_package.json` | workload id, workload family, profile/importer id/version, source provenance, claim boundary, domain metadata boundary |
| `workload_graph.json` | source graph ids, generic nodes, edges, tensors, regions, cost hints, opaque profile/importer metadata |
| `graph_lowering_report.json` | lowering status, full-workload eligibility, required coverage, unsupported constructs, approximations, source-to-executable map |
| `executable_graph.json` or executable view in lowering report | legal mapping target graph for architecture resources and backend requests |
| workflow metadata | default mapping policies, required coverage, domain-validation boundary, unavailable domain metrics |
| required coverage | coverage ids later required in SystemC/gem5+SystemC evidence |

Step2 SHALL NOT require DFT/QE fields such as `npw`, `nkb`, `nbands`, `nfft`, `h_psi`, `diagonalize`,
or any other domain-specific term unless the selected workload profile/importer explicitly
emits those terms as generic graph node ids or workflow metadata.

#### Step2 output contract

A Step2 reviewable run SHALL persist these artifacts before Step3+ simulation is
allowed to claim a trusted sample:

| Step2 artifact | Contents | Final-claim role |
|---|---|---|
| `architecture_catalog.json` | catalog version, families, component types, bindings, validation summary | Defines design-space scope; not a result by itself |
| `architecture.json` | selected/resolved architecture instance, components, constraints, binding status | Candidate can be trusted only if binding and constraints pass |
| `design_point.json` | workload id, architecture id, mapping id, scheduling/precision/fallback/simulation/output config | Replayable candidate contract |
| `step2_status.json` | Step2 status, selected ids, required coverage, blocked/candidate-only reasons | Handoff gate; not final evidence |
| `mapping_legality_matrix.json` | node/resource legality and rejection reasons | Blocks illegal mappings before simulation |
| `mapping_seed_set.json` | generic and workflow-owned seeds with ownership labels | Explains starting points and bias |
| `mapping_candidate_records.json` | generated/screened/promoted/rejected/selected mapping candidates | Audit history for search decisions |
| `mapping_selected_record.json` | selected mapping, legality, promotion reason, limitations | Direct input to simulation request |
| `mapping_promotion_decision.json` | backend/evidence-mode promotion decision, required coverage, budget impact, structured downgrade reasons | Schedules Step3 candidates; cannot be a trusted winner |
| `step2_artifact_validation.json` | reference checks for selected node/resource ids, legality, and no Step2 trusted-final claim | Mechanical audit before Step3 |
| `mapping_simulation_samples.json` | promoted sample placeholders or completed high-fidelity attempts | Feedback bridge; trusted only after evidence passes |
| `mapping_feedback_state.json` | ranking update, sample counts, pruning/promotion effects | Search state for next iteration |
| `convergence_status.json` | stop/continue reason, budget, top-K/frontier criteria | Report limitation or convergence evidence |

If the first implementation slice has not yet split data placement, schedule
placement, or precision placement into separate files, it SHALL record explicit
policies inside `design_point.json` and `mapping_selected_record.json`. Hidden
defaults are not acceptable for trusted handoff.

#### Step2 acceptance gates

Step2 is accepted for later simulation only if all of the following are true:

1. Step1 artifacts are present, valid, and use a full-workload eligible claim boundary.
2. The architecture catalog version and selected architecture instance are recorded.
3. Architecture validation checks duplicate ids, unit consistency, required component fields, operator/precision support, memory capacity, communication routes, power/area/cost budgets, fallback compatibility, and simulation-binding coverage.
4. Each selected mapping references only executable graph nodes or declared summarized regions and legal architecture targets or explicit host fallback.
5. The legality matrix contains rejection reasons for every illegal node/resource pair considered by the search.
6. Mapping seeds are labeled as core-generic or profile/workflow-owned; DFT reference seeds are not global defaults for non-DFT workflows.
7. Candidate lifecycle states and transition reasons are persisted for generated, screened, promoted, blocked, rejected, simulated, finalist, or selected candidates.
8. Low-fidelity screening results are marked candidate-generation evidence only.
9. Promotion decisions include backend target, evidence mode, required coverage, budget impact, and reason.
10. Candidate-only, prototype, stub, planned, missing-binding, smoke-only, diagnostic-only, predicted-only, and unsupported paths are blocked from trusted final ranking.

#### Step2 audit workflow

Reviewers should audit Step2 in this order:

1. Confirm Step1 handoff artifacts resolve and do not contain hidden workload-specific assumptions.
2. Inspect catalog families and binding labels; verify legacy/reference families are not the only candidates.
3. Check architecture validation status and structured rejection reasons.
4. Check mapping legality matrix before reviewing selected mappings.
5. Check seed ownership and ensure workflow-specific seeds remain profile scoped.
6. Check candidate lifecycle records for disappearing or silently rewritten candidates.
7. Check promotion budget and required coverage before any SystemC/gem5+SystemC run.
8. Confirm final reports keep Step2 predicted/candidate outputs separate from Step3+ trusted simulation evidence.

Step2 completion therefore means “simulation-ready candidates with complete audit
artifacts,” not “final architecture recommendation.” A final recommendation still
requires Step3+ high-fidelity evidence and report claim validation.

### 4.1.6 Step3 simulation/evidence audit contract

Step3 is the high-fidelity simulation and evidence boundary after Step2
promotion. It SHALL reload the persisted Step2 run directory, validate that the
candidate is eligible for full-workload SystemC or gem5+SystemC evidence, build
the backend request from disk artifacts, and emit the evidence bundle consumed by
feedback, convergence, and final report validation. Step3 is not allowed to
recover missing Step2 state from live Python objects.

#### Step3 input contract

Step3 SHALL treat the following Step2 artifacts as the reviewable handoff:

| Step2 input artifact | Required Step3 use |
|---|---|
| `step2_status.json` | Confirms Step2 lifecycle state and selected ids |
| `step2_artifact_validation.json` | Records prior reference/legality checks; Step3 reruns equivalent checks before simulation |
| `workload_package.json` | Reconstructs profile/importer identity, workload family, claim boundary, and required coverage |
| `workload_graph.json` | Preserves source graph and domain-neutral audit view |
| `graph_lowering_report.json` | Confirms lowering status, full-workload eligibility, unsupported constructs, and source-to-executable mapping |
| `executable_graph.json` | Supplies the backend-executable graph used for mapping and simulation |
| `architecture_catalog.json` | Defines catalog scope and binding context |
| `architecture.json` | Defines the selected architecture instance and simulation binding status |
| `design_point.json` | Reconstructs architecture id, mapping id, scheduling, precision, fallback, output, and replay metadata |
| `mapping.json` | Supplies legacy or compact selected mapping when present |
| `mapping_promotion_decision.json` | Confirms backend/evidence-mode promotion and records why simulation is allowed or blocked |
| `mapping_legality_matrix.json` | Preserves legal/illegal node-resource decisions |
| `mapping_seed_set.json` | Preserves generic and profile/workflow seed ownership |
| `mapping_candidate_records.json` | Preserves search lifecycle and rejection/promote reasons |
| `mapping_selected_record.json` | Supplies the selected mapping and any legality violations |
| `mapping_simulation_samples.json` | Supplies sample queue/history for feedback linkage |
| `mapping_feedback_state.json` | Supplies feedback counts and ranking/calibration state |
| `convergence_status.json` | Supplies budget/convergence status for report limitations |

Step3 SHALL copy available Step2 inputs into `step2_input/` under the Step3 run
directory. This copy is part of the final audit bundle so a reviewer can rebuild
`simulation_request.json` without access to transient process state.

#### Step3 pre-simulation gates

Step3 SHALL block before simulation if any of the following is true:

1. required Step2 artifacts are missing;
2. Step2 did not explicitly promote the candidate for SystemC or gem5+SystemC simulation;
3. Step2 artifacts attempt to claim a trusted final winner before Step3 evidence exists;
4. graph lowering is unsupported, reduced, not full-workload eligible, or lacks an executable view;
5. selected mapping contains legality violations or references missing executable nodes/resources;
6. architecture binding is missing, prototype-only, stub, planned, diagnostic, or candidate-only;
7. workload claim boundary is smoke, diagnostic-only, trace-only, synthetic-only, or reduced;
8. dynamic Step2 artifact validation fails immediately before simulation.

A blocked Step3 attempt SHALL still write `step3_status.json` with
`full_flow_simulation_attempted: false`, structured reason ids, backend target,
evidence mode, and copied Step2 input paths. It SHALL NOT synthesize
`simulation_result.json` or claim a successful full-flow sample.

#### Step3 output contract

A completed Step3 run SHALL emit the following artifacts or explicit unavailable
reasons:

| Step3 artifact | Contents | Final-claim role |
|---|---|---|
| `step3_status.json` | Step3 status, trust flag, backend/evidence mode, copied Step2 input paths, blocker/evidence-gap reasons | Top-level Step3 gate |
| `step2_input/*.json` | Run-local copies of Step2 handoff artifacts | Replay/audit source |
| `simulation_request.json` | Backend request reconstructed from persisted Step2 and Step1 artifacts | Replayable simulator input |
| `simulation_result.json` | SystemC or gem5+SystemC result status, metrics, events, utilization, and errors | High-fidelity sample data |
| `numerical_validation.json` | Generic simulator/reference checks and explicit numerical-scope boundary | Timing-model validation, not domain physics by default |
| `verdict.json` | Trusted-for-final-ranking flag, coverage, evidence gaps, feasibility, unavailable metrics | Main evidence trust gate |
| `evidence_requirements.json` | Required and optional evidence files for the selected mode | Completeness checklist |
| `claim_validation.json` | Machine-checkable claim validation result and rejection reasons | Final report gate |
| `final_report.json` / `final_report.md` | Human/machine report with evidence ids, limitations, and replay instructions | Review surface |
| `artifact_manifest.json` / `manifest.json` | Hashes/paths/replay metadata for run artifacts | Artifact integrity and lookup |

`trusted_full_flow_evidence_emitted` is valid only when the full-flow simulator
attempt completed and evidence, verdict, and claim-validation gates pass.
`simulation_completed_untrusted` is the required status when the simulator exits
successfully but evidence, coverage, proof, or claim validation is incomplete.
`blocked_simulator_unavailable` is the required status when the selected backend
executable or L4 harness is unavailable.

#### Step3 audit workflow

Reviewers should audit Step3 in this order:

1. Confirm `step2_input/` contains the Step2 handoff artifacts used to rebuild the request.
2. Inspect `step3_status.json` before trusting any simulator output.
3. Verify `simulation_request.json` uses the executable graph, selected mapping, architecture binding, and workflow coverage from Step2 artifacts.
4. For non-DFT workloads, confirm the request/report do not require DFT/QE-only fields or phases.
5. For the DFT reference profile, confirm DFT coverage and seeds remain profile/workflow metadata and are not global defaults.
6. Inspect `simulation_result.json`, `numerical_validation.json`, `verdict.json`, and `claim_validation.json` together; simulator success alone is insufficient.
7. Confirm smoke, diagnostic, prototype, fixed-timing, predicted-only, candidate-only, and missing-binding paths are blocked or downgraded before any trusted claim.
8. Confirm a single trusted Step3 pilot is reported as feasibility evidence only, not as a globally converged best architecture unless comparable trusted samples and convergence evidence exist.


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

Required catalog object roles:

| Object | Purpose | Required design-time fields |
|---|---|---|
| `ArchitectureFamily` | Reusable parameterized design family | id, description, parameter schema, component template, constraints, supported operators, binding requirements |
| `ArchitectureParameter` | Tunable knob for DSE generation | name, type, default, bounds or enum values, units where numeric |
| `ComponentType` | Catalog-level reusable hardware role | type id, compute/memory/communication capabilities, precision support, power/area model status |
| `ComponentInstance` | Concrete component in an architecture instance | instance id, type id, capacity/performance parameters, status label, ports/routes |
| `ArchitectureInstance` | Concrete design generated from a family | family id, resolved parameters, components, memory, interconnect, constraints, simulation binding |
| `ConstraintSet` | Validation and feasibility gates | memory, bandwidth, power, area, operator support, communication route, binding eligibility |
| `SimulationBinding` | Link from architecture instance to executable backend | backend kind, binding id, executable/config path, status, supported evidence modes |

Catalog validation SHALL reject or downgrade designs with duplicate ids, invalid
units, missing routes, missing operator support, infeasible memory/power/area
limits, or absent simulation binding. An architecture without executable binding
may be screened, but remains `candidate-only` for final reporting.

### 4.3 Initial architecture families

| Family | Purpose | Trusted eligibility rule |
|---|---|---|
| `cpu-only-baseline` | software reference | trusted only with calibrated baseline/SystemC equivalent |
| `host-fpga-minimal` | minimal offload | requires SystemC binding |
| `host-fpga-cim` | CIM/GEMM acceleration | requires CIM op model binding |
| `diag-heavy` | stronger eigensolver cluster | requires eigensolver SystemC model |
| `streaming-heavy` | producer-consumer, stencil, signal, or operator-chain streaming optimized | requires streaming/buffer model |
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

Minimum DesignPoint completeness:

- workload id and graph artifact id;
- architecture instance and validation verdict;
- component/resource parameters used by the run;
- memory hierarchy and interconnect topology;
- operator mapping, tensor placement, schedule, and fallback policy;
- precision policy and numerical status assumptions;
- simulation backend configuration and binding id;
- output/evidence mode and run directory policy;
- random seed, budget, and objective directions when search is active.

---

## 5. Mapping search design

### 5.1 Formal problem

Given:

```text
G = normalized workload computation graph with nodes V, typed edges E, and optional regions
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

If the source `ComputeGraph` contains loops, feedback edges, dynamic control,
hierarchical regions, or streaming state, mapping search operates on the
normalized executable view emitted by graph lowering while preserving links back
to the original graph ids and profile/importer claim boundary.

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

Initial seed mappings SHALL include generic baseline policies plus optional profile/importer-provided policies:

| Seed | Description | Owner |
|---|---|---|
| `host-baseline` | all nodes on CPU/host baseline | core |
| `capability-greedy` | map each node to the fastest legal resource for its `op_type`/cost model | core |
| `memory-locality` | minimize cross-resource tensor movement and local-memory overflow risk | core |
| `communication-aware` | prioritize placements that reduce high-volume DataEdge transfers | core |
| `all-offload` | offload all legal nodes, with unsupported nodes falling back explicitly | core |
| `streaming` | prioritize pipeline/dataflow continuity for producer-consumer chains | core |
| `batch` | prioritize high-throughput batch kernels and lower control overhead | core |
| `fallback-mixed` | unsupported/high-risk ops fallback to host with recorded reasons | core |
| `debug-observable` | maximize probes and traceability | core |
| profile/importer-specific seeds | e.g. QE reference diagonalization, ML convolution-heavy, sparse SpMV-heavy | workload profile/importer |

Profile/importer-specific seeds SHALL be labeled with `profile_id`, `importer_id`, `policy_id`, and claim boundary. The generic mapping core SHALL treat them as policy suggestions over generic node ids/op types; it SHALL NOT contain hardcoded QE node names such as `h_psi`, `s_psi`, or `diagonalize`.

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

The first algorithm SHALL persist at least the following search artifacts:

| Artifact | Contents | Used by |
|---|---|---|
| `mapping_legality_matrix.json` | node/resource legality and rejection reasons | mapper, report limitations |
| `mapping_seed_set.json` | baseline/domain/debug seed mappings | reproducibility and coverage review |
| `mapping_candidate_records.json` | generated candidates, parentage, objective estimates | audit and feedback |
| `mapping_simulation_samples.json` | promoted candidates with SystemC/gem5+SystemC outcomes | feedback calibration |
| `mapping_feedback_state.json` | ranking corrections, pruning/promotion updates, convergence data | next iteration and final report |
| `mapping_selected_record.json` | selected mapping, evidence id, limitation list | final report claim gate |

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
- `diagnostic-only`: result uses a bring-up or non-trusted diagnostic path.

### 6.3 Feedback update

After every high-fidelity sample, the optimizer SHALL update:

1. trusted ranking;
2. Pareto frontier;
3. low-fidelity calibration samples;
4. surrogate model or ranking correction;
5. pruning thresholds;
6. promotion policy;
7. next-candidate generation.

Feedback update SHALL distinguish these sample classes:

| Sample class | Search effect | Reporting effect |
|---|---|---|
| `trusted-systemc` | updates ranking, surrogate calibration, pruning, and promotion policy | eligible for trusted ranking if other gates pass |
| `trusted-gem5-systemc` | same as trusted SystemC plus L4 software-visible completion evidence | eligible for L4 trusted claims |
| `untrusted-gem5-systemc` | records missing proof and may redirect budget to L3 SystemC | reported as untrusted, never as trusted L4 |
| `diagnostic-only` | may validate command wiring only | diagnostic appendix only |
| `predicted-only` | may guide exploration | candidate appendix only |

The optimizer SHALL NOT convert a low-fidelity prediction into a winner without
a trusted high-fidelity sample for the selected architecture/mapping.

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

### 7.3 Diagnostic/untrusted boundary

If GenericAccel lacks real descriptor/request ingestion, SystemC submission,
completion/result writeback, and guest-visible success proof, its results SHALL
be labeled:

```text
diagnostic-only / untrusted / not trusted for final performance ranking
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
├── architecture_catalog.json
├── mapping.json
├── mapping_legality_matrix.json
├── mapping_seed_set.json
├── mapping_candidate_records.json
├── mapping_selected_record.json
├── mapping_simulation_samples.json
├── mapping_feedback_state.json
├── workload_package.json
├── workload_graph.json
├── graph_lowering_report.json
├── executable_graph.json              # optional if distinct from workload_graph
├── simulation_request.json
├── simulation_result.json
├── numerical_validation.json
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

For any full-flow workload run, the minimum trusted SystemC evidence set is:
`manifest.json`, `artifact_manifest.json`, `verdict.json`, `design_point.json`,
`architecture.json`, `architecture_catalog.json`, `mapping.json`,
`mapping_legality_matrix.json`, `mapping_seed_set.json`,
`mapping_candidate_records.json`, `mapping_selected_record.json`,
`mapping_simulation_samples.json`, `mapping_feedback_state.json`,
`workload_package.json`, `workload_graph.json`, `graph_lowering_report.json`,
`simulation_request.json`, `simulation_result.json`,
`numerical_validation.json`, `phase_breakdown.csv`, `resource_summary.csv`,
`data_movement_summary.csv`, `systemc_stdout.log`, and `systemc_stderr.log`.
`numerical_validation.json` is a scoped timing-level numeric reference check for
the generic simulator outputs; it does not by itself claim domain-specific
correctness such as QE FP64 physics, ML model accuracy, sparse solver residuals,
or database query equivalence unless the corresponding workload profile/importer supplies
separate validation evidence. gem5 logs are required only for a gem5+SystemC run
and MUST be replaced by explicit blocker evidence otherwise.

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
| Numerical correctness | `numerical_validation.json` for generic simulator timing outputs; output hash/reference comparison/residual error for QE/DFT physical correctness where modeled |
| Smoke/diagnostic limitation | explicit diagnostic-only status, no trusted ranking eligibility, and no selected-winner claim |
| Stub/unsupported limitation | status boundary and missing binding/feature evidence |

### 9.4 Trusted ranking gate

A candidate SHALL enter trusted final ranking only if:

1. architecture instance has valid simulation binding;
2. mapping is legal;
3. complete SystemC or gem5+SystemC full-flow simulation completed;
4. verdict marks it trusted for final ranking;
5. evidence files exist or unavailable reasons are explicit;
6. it is not dominated by another trusted candidate under configured objectives unless retained as a trade-off alternative.

Smoke is an explicit final-check failure condition. If the evidence path is
smoke-only, fixed-timing bring-up, legacy smoke conversion, diagnostic replay, or
otherwise lacks full-flow simulation artifacts, the validator SHALL reject it as
a trusted ranking entry even if the smoke command exits successfully.

Report validation SHALL run before a final report is accepted. The validator
checks:

- each trusted entry completed a full-flow SystemC or gem5+SystemC simulation and is not smoke-only;
- selected winner is not `predicted-only`, `candidate-only`, `diagnostic-only`, blocked, or untrusted;
- selected winner and trusted Pareto entries do not cite smoke as completion evidence;
- every trusted claim lists at least one evidence id;
- every evidence id resolves to existing artifacts or explicit unavailable reasons;
- claim type requirements from §9.3 are satisfied;
- trusted and predicted-only sections are separate;
- blocked or untrusted limitations are preserved in the final report;
- replay instructions point to the manifest/config bundle used for the run.

---

## 10. Requirement traceability to OpenSpec

Detailed matrix: `docs/architecture/generic_dse_openspec_traceability_matrix_v2.md`.

| OpenSpec capability | This document sections |
|---|---|
| `generic-dse-ir-contract` | §4 WorkloadPackage / DesignPoint and stage artifact contracts |
| `accelerator-system-description` | §4.2–§4.4 Architecture catalog, families, DesignPoint |
| `multi-fidelity-dse-evaluation` | §6 Screening and feedback loop, §6.4 convergence |
| `generic-simulation-backend` | §7 gem5+SystemC role, §8 evidence contract |
| `dft-qe-workload-adapter` | Historical capability name; current contract treats DFT/QE as the primary reference vertical slice while keeping it profile/importer-scoped, §4.1.2 profile/importer registry, §9 domain reporting |
| `end-to-end-dse-workflow` | §1, §3, §5, §8, §9 |
| `step3-simulation-evidence-workflow` | §4.1.6 Step3 simulation/evidence audit contract, §8 evidence contract, §9 final report gates |

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

Implementation evidence update (2026-05-09):

- P0/P1 L4 evidence is implemented for the GenericAccel descriptor/request/decode/microarchitecture/completion path, with a trusted post-feedback run at `runs/dse/l4_full_flow_real_post_feedback_20260509_164657`.
- P4/P5 feedback/reporting is implemented for bounded multi-candidate SystemC feedback runs, with convergence/budget evidence at `runs/dse/feedback_convergence_20260509_164625`.
- Both evidence lanes keep the same claim boundary: generic timing-level numerical validation passes, but domain-specific correctness such as DFT/QE FP64 residual/density/eigenvector physics correctness is not claimed without profile/importer evidence.

---

## 12. Open discussion items

These items must be decided by the user/reviewer before the next implementation
goal claims a complete architecture recommendation:

| Topic | Decision needed | Default if undecided |
|---|---|---|
| Architecture family priorities | Which families should be simulated first beyond `balanced-generic-systemc-v0`: CPU-only, Host+FPGA minimal, Host+FPGA+CIM, diag-heavy, streaming-heavy, memory-rich, low-power, debug, or custom | Cover at least one baseline, one balanced, and one stress family; do not reintroduce historical fixed-pipeline templates as the default |
| First gem5+SystemC pilot | Resolved for the current generic descriptor/request/decode/microarchitecture/completion path using the DFT/QE reference profile/importer pilot at `runs/dse/l4_full_flow_real_post_feedback_20260509_164657`; future discussion is how many DFT→FPGA finalists require L4 and how to sample other workload families | Treat L4 as trusted only when `gem5_l4_proof.json` passes; otherwise retain untrusted labels for that sample |
| Evidence verbosity defaults | Whether top-K finalists should default to `debug` or `forensic` evidence mode | Use `debug` for finalists; reserve `forensic` for publication/user-selected audit runs |
| Mapping-search budget | Number of promoted candidates per feedback round, total SystemC/gem5+SystemC samples, and top-K stability threshold | Current bounded pilot uses two trusted SystemC samples and reports budget exhaustion as a limitation, not convergence |
| Convergence definition | Whether trusted frontier stability, top-K stability, hypervolume improvement, absolute improvement, uncertainty reduction, or family coverage gates stop the run | Record explicit stop reason in `convergence_status.json` |
| Required domain metrics | Which profile/importer-specific metrics are mandatory per workload family: DFT reference phase timings / transfer metrics / residual-related correctness evidence where modeled, ML accuracy/throughput, sparse residuals, graph traversal quality, database query correctness, unavailable labels | Include generic latency/energy/data movement plus profile-declared unavailable-metric labels at minimum |

## 13. Future `/goal` split

Future implementation should be split into separate bounded goals:

1. **P0/P1 full-flow evidence goal**: extend or explicitly block the L4 gem5 GenericAccel descriptor/decode/microarchitecture/completion path; harden summary/debug/forensic evidence artifacts and claim gating.
2. **P2/P3 catalog and mapping goal**: extend architecture catalog families, validation, DesignPoint generation, legality matrix, seeded beam/local mapping search, and persisted mapping artifacts.
3. **P4/P5 feedback and report goal**: implement multi-candidate feedback updates, convergence/budget reporting, final report generation, and machine-checkable claim validation.
4. **Validation/archive goal**: run build/tests/OpenSpec validation, verify protected-path compliance, record remaining limitations, and archive only after evidence matches every OpenSpec scenario.

---

## 14. Document control

| Version | Date | Change |
|---|---|---|
| v2.0 | 2026-05-09 | Reframed generic DSE as SystemC/gem5+SystemC evidence-backed feedback optimization system. |
