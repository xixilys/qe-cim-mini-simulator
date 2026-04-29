
# 前后端结合与项目总体开发路线文档

**目标**：指导项目从当前 QE/DFT-oriented prototype，演进为一个可复用的软硬件协同 DSE 基础平台，并以 QE 负载作为第一条完整验证链路。

---

## 1. 总体定位

项目应被定位为：

> 一个面向复杂软硬件计算框架的多保真 DSE + co-simulation 平台。前端负责生成、筛选、优化和 adjudicate 候选设计；后端负责 SystemC/gem5/implementation 级别的执行与证据回传；QE/DFT 是第一垂直应用案例，而不是框架唯一目标。

这个定位解决两个问题：

1. 框架层面保持普适：可以服务 FPGA/ASIC、不同 accelerator template、不同软件 runtime、不同 workload graph。
2. 落地层面保持可信：第一条完整证据链先打通 QE/DFT，而不是一次性追求所有应用。

---

## 2. 建议的总架构

```text
                         ┌────────────────────────────┐
                         │ Workload / Application      │
                         │ QE, CP2K, VASP, Stencil...  │
                         └─────────────┬──────────────┘
                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │ Workload Adapter            │
                         │ -> ApplicationGraphIR       │
                         └─────────────┬──────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ DSE Frontend                                                       │
│  - ArchitectureTemplateIR                                          │
│  - MappingIR                                                       │
│  - DesignPointValidator                                            │
│  - FastModel / BO / Multi-fidelity Scheduler                       │
│  - Claim Ceiling / Evidence Contract                               │
│  - BackendExecutionRequest emitter                                 │
└─────────────────────────────┬────────────────────────────────────┘
                              │ descriptor / handoff
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ Backend Evaluation Service                                         │
│  - SystemC standalone                                               │
│  - SystemC timed-functional proxy                                   │
│  - gem5 SE/FS + SystemC smoke/timed proxy                           │
│  - HLS/RTL/FPGA/ASIC evidence adapters                              │
└─────────────────────────────┬────────────────────────────────────┘
                              │ feedback / evidence
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ DSE Feedback + Calibration + Adjudicator                           │
│  - Feedback schema validation                                       │
│  - Calibration residual model                                       │
│  - Promotion gate                                                   │
│  - Release bundle / design recommendation                           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 前后端边界

### 前端负责

- Workload graph 的抽象。
- 架构模板和参数空间的定义。
- design point 生成和合法性判断。
- fast/proxy model 初筛。
- 搜索策略：Cartesian、BO、active sampling。
- 生成 backend execution request。
- 验证 backend report schema。
- 校准模型和更新 ranking。
- adjudicator memo / release bundle。

### 后端负责

- 读取 backend execution request。
- 执行 SystemC/gem5/implementation 指定模式。
- 生成统一 backend execution report。
- 保证 metrics 单位、时间、字节、claim ceiling 一致。
- 保证 smoke 不越权 claim correctness。
- 保存 logs/stats/artifact refs。

### 二者唯一强耦合点

只允许通过 JSON/schema contract 强耦合：

```text
CandidateDescriptor
BackendExecutionRequest
BackendExecutionReport
CorrectnessReport
ImplementationEvidence
CalibrationFeedback
AdjudicatorMemo
```

不要让前端直接调用后端内部 C++ 类，也不要让后端依赖前端 Python 对象。

---

## 4. 核心 artifact 设计

### 4.1 CandidateDescriptor

```json
{
  "schema_version": "candidate_descriptor_v0",
  "candidate_id": "...",
  "application_graph_ref": "...",
  "architecture_template_ref": "...",
  "mapping_ref": "...",
  "target_class": "fpga",
  "validity_class": "valid_executable",
  "claim_ceiling_before_execution": "descriptor_only",
  "domain_extension": {
    "qe": {}
  }
}
```

### 4.2 BackendExecutionRequest

前端发给后端的执行请求。

```json
{
  "schema_version": "backend_execution_request_v0",
  "candidate_id": "...",
  "execution_mode": "systemc_timed_functional",
  "requested_fidelity": "B2",
  "input_refs": {
    "systemc_config": "...",
    "proxy_runtime": "..."
  },
  "expected_report_schema": "backend_execution_report_v0"
}
```

### 4.3 BackendExecutionReport

后端回传给前端。

```json
{
  "schema_version": "backend_execution_report_v0",
  "candidate_id": "...",
  "execution_status": "executed",
  "fidelity": "systemc_timed_functional",
  "claim_ceiling": "systemc_timed_functional_proxy_only",
  "metrics": {},
  "correctness_gate": {},
  "artifact_refs": {}
}
```

### 4.4 CorrectnessReport

领域正确性单独存在，不与性能 report 混用。

```json
{
  "schema_version": "correctness_report_v0",
  "domain": "dft",
  "adapter": "qe",
  "candidate_id": "...",
  "correctness_status": "pass | mismatch | baseline_missing",
  "workload_equivalent_claim": true,
  "tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
  "compare_report": {}
}
```

### 4.5 ImplementationEvidence

实现证据单独存在。

```json
{
  "schema_version": "implementation_evidence_v0",
  "candidate_id": "...",
  "target_class": "fpga | asic",
  "evidence_kind": "hls_synthesis | rtl_simulation | fpga_board | openroad_physical",
  "metrics": {
    "lut": 0,
    "dsp": 0,
    "bram": 0,
    "fmax_mhz": 0,
    "timing_met": false
  },
  "claim_ceiling": "hls_synthesis_only"
}
```

---

## 5. Claim ceiling 统一分级

建议统一成以下层级：

| Level | 名称 | 允许声明 | 禁止声明 |
|---|---|---|---|
| C0 | descriptor_only | 设计点可表达 | 已执行、有性能 |
| C1 | fast_model_screening | fast/proxy 初筛分数 | SystemC/gem5 性能 |
| C2 | systemc_standalone_proxy | SystemC standalone proxy 执行 | host 控制开销 |
| C3 | systemc_timed_functional | timed-functional datapath 指标 | QE 等价正确性、RTL 性能 |
| C4 | gem5_systemc_smoke | host 控制链路跑通 | workload-equivalent correctness |
| C5 | gem5_systemc_timed_proxy | host/runtime/cache/sync proxy 指标 | board measured speedup |
| C6 | workload_equivalent_correctness | domain correctness within tolerance | FPGA/ASIC 实测性能 |
| C7 | implementation_synthesis | HLS/RTL/ASIC synthesis evidence | board measured |
| C8 | board_or_physical_measured | 板级/物理设计证据 | production-ready unless separately proven |

当前项目大多数证据应该停在 C0-C4；QE correctness 和 implementation evidence 需要单独推进。

---

## 6. 如何兼顾“普适框架”和“QE 落地”

### 6.1 核心必须保持 domain-neutral

这些模块不应包含 QE 专有字段：

```text
DSE search engine
CandidateDescriptor
BackendExecutionRequest
BackendExecutionReport
CalibrationEngine
Adjudicator
ImplementationEvidence
```

### 6.2 QE adapter 可以很深

QE adapter 可以包含：

```text
pseudopotential_family
solver_path_class
h_psi/c_bands/sum_band/mix_rho
qe_tolerance_schema_id
gold baseline comparison
SCF convergence criteria
```

这样你的项目能同时做到：

```text
核心框架普适
QE 案例深入
```

### 6.3 第一条完整闭环建议仍然选 QE/F2

虽然框架要普适，但第一条完整闭环建议聚焦：

```text
Application: QE/DFT proxy
Architecture: F2 balanced hybrid
Mapping: operator -> build -> diag -> refresh
Backend: SystemC timed-functional + gem5 SE smoke
Claim ceiling: C4 or C5
```

不要先追 F4/F5/custom，因为它们 projection 成分太重。

---

## 7. 建议目录重构

短期可以不移动全部旧代码，但建议建立新顶层组织：

```text
project_root/
├── frontend/
│   ├── dse_core/
│   ├── adapters/
│   │   ├── qe/
│   │   └── generic_trace/
│   ├── schemas/
│   └── cli/
├── backend/
│   ├── systemc/
│   ├── gem5/
│   ├── runtime_api/
│   ├── runners/
│   └── report_writers/
├── model/
│   ├── qe_band_solver_model/
│   └── ozaki_subspace_model/
├── evidence/
│   ├── requests/
│   ├── reports/
│   ├── correctness/
│   └── implementation/
└── docs/
    ├── development/
    ├── architecture/
    └── release/
```

旧目录映射：

```text
dse_v2/                         -> frontend/dse_core/search + models + adapters/qe
_docs/benchmarks/unified_dse/    -> frontend/dse_core/contracts + adjudication
gem5_integration/                -> backend/gem5 + backend/systemc_bridge
model/qe_band_solver_model/      -> backend/systemc/models/qe_band_solver or model/
```

---

## 8. 端到端开发流程

### Stage A：前端生成候选

```bash
qedse frontend optimize \
  --workload-adapter qe \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --architecture-space docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --search bo_or_cartesian \
  --output evidence/requests/stage_a
```

输出：

```text
CandidateDescriptor
Stage-A ranking
BackendExecutionRequest
claim ceiling = C1
```

### Stage B1/B2：SystemC backend 执行

```bash
qedse backend run-systemc \
  --request evidence/requests/stage_a/candidate.json \
  --output evidence/reports/systemc/candidate.json
```

输出：

```text
BackendExecutionReport
claim ceiling = C2/C3
```

### Stage B3/B4：gem5 + SystemC 执行

```bash
qedse backend run-gem5-systemc \
  --request evidence/requests/stage_a/candidate.json \
  --mode se_smoke \
  --output evidence/reports/gem5/candidate.json
```

输出：

```text
BackendExecutionReport
claim ceiling = C4/C5
```

### Stage C：correctness

```bash
qedse frontend check-correctness \
  --candidate candidate.json \
  --gold-baseline gold/qe_case.json \
  --candidate-output backend_output.json
```

输出：

```text
CorrectnessReport
claim ceiling = C6
```

### Stage D：implementation evidence

```bash
qedse frontend ingest-implementation \
  --candidate candidate.json \
  --report hls_report.json
```

输出：

```text
ImplementationEvidence
claim ceiling = C7/C8
```

### Stage E：adjudication

```bash
qedse frontend adjudicate \
  --bundle evidence/release_bundle \
  --output docs/release/adjudicator_memo.md
```

---

## 9. 八周路线图

### Week 1：schema 和接口冻结

- 冻结 CandidateDescriptor。
- 冻结 BackendExecutionRequest/Report。
- 冻结 claim ceiling enum。
- 把 QE-specific fields 移入 adapter extension。
- 给现有 unified DSE 输出 compatibility schema。

### Week 2：前端融合

- unified DSE 调用 DSE v2 fast model。
- BO search plugin 接入 unified pipeline。
- design point legality checker。
- Stage-A 输出 executable/projection/invalid 三类。

### Week 3：SystemC report 化

- `qe_band_solver_model` 输出 BackendExecutionReport。
- report 包含 cluster、DMA、fallback、resident reuse。
- 前端 feedback adapter 能吸收 report。

### Week 4：gem5 SE smoke 闭环

- gem5 SE proxy runtime 跑通。
- MMIO/TLM/control/completion report 输出。
- claim ceiling = gem5_systemc_smoke_only。
- 前端 stage_b3 validator 接受。

### Week 5：真实 bridge 和 timed path

- 替换/隔离 FPGATLMStub。
- TLM target 调用统一 backend dispatcher。
- 修正 address map。
- timed path 不再 immediate complete。

### Week 6：calibration

- fast vs SystemC residual model。
- calibrated ranking。
- multi-fidelity selection。
- 对 QE/F2 做闭环迭代。

### Week 7：correctness gate

- QE proxy correctness report。
- minimal one-iteration/operator-level correctness。
- diagonalization proxy residual check。
- fallback path equivalence。

### Week 8：release bundle 和泛化测试

- QE 完整案例 release bundle。
- generic trace workload smoke。
- 文档、CI、adjudicator memo。
- 准备论文/报告中的系统图和 ablation。

---

## 10. 对当前项目最关键的三条建议

### 建议 1：把 `unified_dse` 作为可信核心

因为它已经有 claim ceiling、stage gate、handoff、correctness、implementation evidence 的雏形。不要丢掉这条线。

### 建议 2：把 `dse_v2` 作为优化器和 fast model 插件

因为它已经有 BO、多 workload、host-fpga design space 和 fast model。不要让它和 evidence-only pipeline 分裂。

### 建议 3：把后端从“QE demo”变成“backend service”

所有后端执行都通过 request/report schema，QE 只是一个 model/runtime adapter。这样未来才能接入更多复杂软硬件计算框架。

---

## 11. 最小可交付版本定义

一个合格的 v1 MVP 应该具备：

1. 前端能生成 100+ design points，并给出 legality / claim ceiling。
2. 前端能用 BO 或 Cartesian 选 top-N。
3. 后端能对 top-N 中至少 3 个点执行 SystemC timed-functional。
4. 后端能对至少 1 个点执行 gem5-SystemC smoke。
5. 前端能吸收 SystemC/gem5 report 并更新 ranking。
6. 所有结论都带 claim ceiling。
7. QE/F2 路线有一份完整 release bundle。
8. 一个 generic synthetic workload 可以通过同一 core 跑到 Stage A/B1，证明框架不是 QE-only。

---

## 12. 最终目标形态

最终这个项目应该能对用户说：

> 给我一个 workload adapter、一个 architecture template set、一个 backend capability set，我可以先用 fast model 做大规模 DSE，再把少数高价值候选交给 SystemC/gem5/implementation backend 验证，最后给出带证据等级和 claim ceiling 的软硬件划分、控制策略、硬件参数和瓶颈分析。

对 QE 的具体输出则应该是：

```text
推荐哪些 SCF/inner-loop 阶段 offload；
推荐 resident object policy；
推荐 host/device control policy；
推荐 FPGA/ASIC accelerator 参数；
说明 diagonalization 是 CPU-only、device-first fallback 还是 aggressive device；
说明性能收益来自哪里，风险在哪里，证据等级到哪里。
```

这就是“普适框架 + QE 深度落地”的平衡点。
