
# 前端 DSE 开发推进文档

**适用范围**：本文件面向项目的 DSE 前端，即负责 workload 接入、设计空间表达、候选架构生成、fast/proxy 评估、搜索、证据分级、handoff descriptor 生成和反馈吸收的 Python/contract 管线。

**目标定位**：把当前项目从“QE 专用 DSE 脚本集合”推进为一个**通用软硬件协同设计空间探索前端**，同时保留 QE/DFT 作为第一垂直落地 adapter。

---

## 1. 当前前端状态判断

当前前端实际上有两条并行路线。

第一条是 `dse_v2/`：它偏向传统 DSE/优化器路线，已经有 Host+FPGA 设计空间、workload matrix、fast roofline model、Bayesian Optimization、multi-workload DSE 和可视化结果。它的优势是：

- 有明确的优化器入口，例如 `run_bayesian_dse.py` 和 `run_multi_workload_dse.py`。
- 有大规模参数空间，例如 `host_fpga_design_space_v2.json` 中的 offload strategy、dataflow、resident strategy、pipeline depth、parallel units、DMA channels 等。
- 有 fast model，可快速返回 time、energy、area/resource 估计。
- 已经初步形成“多 workload 平均性能 / robustness”的分析风格。

它的主要问题是：

- 设计点语义仍偏 QE/Host+FPGA，没有形成通用 `ApplicationGraphIR / ArchitectureIR / MappingIR / EvidenceIR`。
- fast model 里很多公式仍是 hand-tuned proxy，缺少统一的 calibration metadata、assumption set、validity domain 和 confidence level。
- 搜索结果容易看起来像“真实性能结论”，但还没有和 SystemC/gem5/implementation evidence 形成严格闭环。
- BO 结果和 `unified_dse` 的 claim ceiling / adjudicator 体系尚未合并。

第二条是 `tools/benchmarks/unified_dse/`：它偏向 evidence-only pipeline 和 stage gate。它的优势是：

- 有明确的 design point identity：`family / diag_policy / offload_scope / resident_policy / partition_strategy`。
- 有 `stage_a_contracts.py`，能生成 backend-neutral schema、SystemC feedback contract、gem5 handoff contract、QE anchor refs。
- 有 `stage_b0_descriptors.py`，能生成 SystemC config 和 gem5 handoff descriptor。
- 有 `stage_b3_gem5_smoke.py`、`stage_c_qe_correctness.py`、`stage_d_implementation_evidence.py`，能做证据分级和 claim ceiling 限制。
- 有 `result_analysis.py`，把 promotion state 限制在 `reject / explain-only / promotion-eligible`，这对可信 DSE 很重要。

它的主要问题是：

- 当前 `FastModelBackend` 基本是 stub，只返回 `stub_metrics_present`。
- `run_unified_dse_v0.py` 明确限制 `--source-kind stub`，并不会真正执行 SystemC，也不会调用 BO。
- 搜索目前主要是 bounded Cartesian product，不是主动多保真搜索。
- schema 中大量字段直接以 QE 命名，例如 `qe_anchor_refs`、`qe_equivalent_scf_claim`，这会限制普适性。

**结论**：前端不应该继续分裂成两套体系。建议以 `unified_dse` 作为“证据/contract/claim 核心”，把 `dse_v2` 的 BO、fast model、多 workload 优化迁移成 core 插件。

---

## 2. 前端总体目标

前端应该服务于一个更通用的问题：

> 给定一个软件 workload 或 workload graph、一个候选异构系统架构空间、若干 fast/mid/high fidelity backend，自动生成候选设计点，筛掉非法点，选择值得高保真验证的点，吸收反馈，更新模型，最后输出带证据等级的推荐。

这个目标可以拆成六个能力。

| 能力 | 当前状态 | 下一步目标 |
|---|---|---|
| Workload 表达 | QE descriptor + workload matrix | 通用 `ApplicationGraphIR` + QE adapter |
| 架构空间表达 | `family` 五轴 + Host/FPGA v2 参数 | 通用 `ArchitectureTemplateIR` + target-specific realization |
| 搜索 | Cartesian + BO 分散存在 | 统一 `SearchEngine` 插件体系 |
| fast model | DSE v2 有 roofline，unified 是 stub | 可校准 fast model + confidence metadata |
| 证据体系 | unified DSE 做得较好 | 从 QE-specific 推广成 domain-neutral evidence levels |
| handoff/feedback | B0 descriptor 初步存在 | 后端 runner 可执行、可回灌、可校准 |

---

## 3. 建议的前端核心抽象

### 3.1 ApplicationGraphIR

用于表示任何复杂软件 workload，不限于 QE。

```yaml
application_graph:
  schema_version: app_graph_ir_v0
  app_id: qe_pwscf_si8
  domain: dft
  nodes:
    - node_id: h_psi
      op_type: operator_apply
      math_tags: [fft, projector, complex_vector]
      data_objects: [psi, beta_projectors, veff]
      control_role: hotpath
      candidate_mappings: [software, fpga, asic, systemc_proxy]
      precision_contract: fp64_required
      correctness_contract: qe_operator_equivalence_v0
  edges:
    - from: h_psi
      to: reduced_build
      edge_type: data_dependency
      objects: [partial_h, partial_s]
```

QE/DFT 只是一个 adapter：它把 `HostSCF / h_psi / s_psi / reduced build / cdiaghg proxy / refresh` 映射成这个通用图。

### 3.2 ArchitectureTemplateIR

用于表示可探索的系统架构模板。

```yaml
architecture_template:
  schema_version: architecture_template_ir_v0
  template_id: balanced_fpga_pipeline
  target_classes: [fpga, asic]
  components:
    - component_id: host_runtime
      type: software_runtime
    - component_id: device_orchestrator
      type: accelerator_runtime
    - component_id: operator_engine
      type: compute_engine
    - component_id: local_memory
      type: memory
    - component_id: host_device_link
      type: interconnect
  knobs:
    parallel_units: [1, 2, 4, 8]
    pipeline_depth: [2, 3, 4, 5]
    resident_policy: [fit_first, spill_tolerant]
```

当前 `family=F1/F2/F3/F4/F5/custom` 可以保留，但应作为 architecture template 的一类，而不是整个核心 schema。

### 3.3 MappingIR

用于表示“软件节点如何映射到硬件/软件/混合执行”。

```yaml
mapping:
  mapped_nodes:
    h_psi: fpga.operator_engine
    reduced_build: fpga.reduction_engine
    diag: cpu.lapack_or_device_first_fallback
    refresh: fpga.refresh_engine
  control_policy:
    submission: async
    completion: polling_or_interrupt
    buffering: double
    fallback: host_diag_allowed
```

这样你的 DSE 可以回答“什么放硬件，什么放软件，控制流怎么组织”。

### 3.4 EvidenceIR

用于统一前端和后端的证据。

```yaml
evidence:
  schema_version: evidence_ir_v0
  candidate_id: ...
  fidelity: systemc_timed_functional
  execution_status: executed
  metrics:
    latency_s: ...
    energy_j: ...
    bytes_moved: ...
    host_wait_s: ...
    accelerator_busy_s: ...
  claim_ceiling: systemc_timed_functional_only
  non_claims:
    - not_qe_equivalent_correctness
    - not_fpga_board_measured
```

当前 `stage_b3_gem5_smoke.py`、`stage_c_qe_correctness.py`、`stage_d_implementation_evidence.py` 可以迁移到这个通用 evidence schema 下。

---

## 4. 前端需要继续深入推进的工作

### 4.1 统一 `dse_v2` 和 `unified_dse`

建议保留两者的优点：

- `unified_dse` 负责 contract、claim ceiling、stage status、handoff descriptor、feedback adapter、adjudicator 输入。
- `dse_v2` 负责 BO、multi-workload optimization、fast roofline model、visualization。

建议新目录结构：

```text
dse_frontend/
├── core/
│   ├── ir/
│   │   ├── application_graph.py
│   │   ├── architecture_template.py
│   │   ├── mapping.py
│   │   └── evidence.py
│   ├── design_space/
│   ├── constraints/
│   ├── search/
│   │   ├── bounded_cartesian.py
│   │   ├── bayesian_ax.py
│   │   ├── evolutionary.py
│   │   └── active_multifidelity.py
│   ├── models/
│   │   ├── fast_model_base.py
│   │   ├── roofline_model.py
│   │   └── calibrated_surrogate.py
│   ├── handoff/
│   ├── feedback/
│   └── adjudication/
├── adapters/
│   ├── qe/
│   ├── generic_trace/
│   └── synthetic_kernel/
└── cli/
```

短期内不需要重写所有代码，可以先做 compatibility wrapper：

```text
unified_dse.FastModelBackend
  -> 调用 dse_v2.models.fast.performance_model.FastPerformanceModel

unified_dse.search_engine
  -> 支持 bounded_cartesian / ax_bayesian 两个 backend

unified_dse.stage_b0_descriptors
  -> 输出通用 handoff + QE extension
```

### 4.2 把 QE-specific 字段移到 adapter extension

当前 unified DSE 中这些字段偏 QE：

```text
qe_anchor_refs
qe_equivalent_scf_claim
qe_tolerance_schema_id
pseudopotential_family
solver_path_class
projector_pressure
nonlocal_pressure
```

建议拆成：

```yaml
workload_identity:
  workload_id: ...
  domain: dft
  app_adapter: qe
  correctness_contract_id: qe_gold_tolerance_v0

domain_extension:
  qe:
    pseudopotential_family: USPP
    solver_path_class: generalized_overlap
    projector_pressure: high
    qe_equivalent_scf_claim: false
```

这样未来可以接入：

```text
CP2K
VASP proxy
CFD stencil
sparse linear algebra
graph workload
ML inference/training kernel
```

而不需要修改 DSE core。

### 4.3 加入 design point legality checker

现在 Cartesian product 会生成很多语义上可表达但未必合法的组合。建议增加：

```python
class DesignPointValidator:
    def validate(point, workload, backend_capability) -> ValidationResult:
        return ValidationResult(
            validity_class="valid_executable | projection_only | invalid",
            claim_ceiling="...",
            missing_evidence=[...],
            reasons=[...],
        )
```

至少要检查：

- projection-only family 是否被错误送入 executable backend。
- `diag_policy=aggressive_device` 是否需要 backend 存在 device diag engine。
- `resident_policy=fit_first` 是否满足 memory capacity。
- `offload_scope=device_heavy` 是否与 workload data movement 矛盾。
- `partition_strategy` 是否满足 cluster/data dependency。
- target 是 FPGA 还是 ASIC，资源/工艺模型是否存在。

### 4.4 把 fast model 从“返回数值”升级为“返回证据”

当前 DSE v2 的 fast model 可以估计 `h_psi` time、energy、area，但它应该返回更多 metadata：

```json
{
  "metrics": {
    "time_to_convergence_s": 1.2e-3,
    "energy_to_convergence_j": 0.4,
    "bytes_moved_to_convergence": 123456,
    "fallback_ratio": 0.0,
    "spill_ratio": 0.1,
    "host_wait_s": 2.0e-4,
    "device_busy_s": 8.0e-4
  },
  "model_metadata": {
    "model_kind": "roofline_proxy",
    "calibration_status": "uncalibrated",
    "validity_domain": "fpga_host_device_tlm_proxy",
    "confidence": "low",
    "assumption_set_id": "stage_a_v0"
  },
  "claim_ceiling": "fast_model_screening_only"
}
```

这样 ranking 不会被误读成最终真实性能。

### 4.5 引入多保真搜索调度器

建议新建 `active_multifidelity.py`，做三件事：

1. 先用 fast model 大规模筛选。
2. 选择 Pareto-front 附近、模型不确定性高、或高潜力但缺证据的点进入 SystemC/gem5。
3. 用后端反馈更新 surrogate/correction model。

选择策略可以先很简单：

```text
select = top_k_fast + top_k_uncertain + top_k_diverse_by_family + required_baselines
```

后续再上 Bayesian multi-fidelity / expected improvement。

### 4.6 强化 calibration engine

当前 calibration 更像占位。建议改成：

```text
fast_model_prediction
+ systemc_feedback
+ gem5_feedback
+ implementation_feedback
-> residual model
-> calibrated prediction
```

最小实现：

```python
corrected_latency = fast_latency * alpha_family * beta_workload + gamma_transfer
```

其中 `alpha/beta/gamma` 从 feedback artifact 学出来。输出必须带：

```text
calibration_data_count
error_before
error_after
validity_scope
```

### 4.7 前端 CLI 统一化

当前 runner 比较多。建议提供统一 CLI：

```bash
qedse frontend enumerate
qedse frontend optimize
qedse frontend emit-handoff
qedse frontend ingest-feedback
qedse frontend calibrate
qedse frontend adjudicate
qedse frontend release
```

旧脚本可以保留为 compatibility entrypoint。

---

## 5. 前端近期任务清单

### P0：两周内必须完成

1. 建立 `CandidateDescriptor` 通用 schema。
2. 把 `qe_anchor_refs` 改为 `workload_anchor_refs + qe_extension`。
3. 给每个 design point 加 `validity_class / claim_ceiling / missing_evidence / promotion_blockers`。
4. 让 `unified_dse.FastModelBackend` 可以调用 DSE v2 fast model。
5. 让 `result_analysis` 支持 `fast_model_screening_only` 和 `systemc_feedback_ranked` 两类 ranking。
6. 输出统一 Stage-B backend request JSON。

### P1：一个月内完成

1. 把 Ax/BoTorch BO 做成 search plugin。
2. 建立 multi-fidelity scheduler。
3. 加入 calibrated surrogate。
4. 建立 workload adapter API。
5. 建立一套 minimal generic trace adapter。
6. 给 QE adapter 输出 `ApplicationGraphIR`。

### P2：两到三个月完成

1. 支持多个 target class：FPGA / ASIC / CPU-only baseline / simulated accelerator。
2. 支持多应用 workload：QE + synthetic stencil/GEMM/SpMV。
3. 支持 implementation feedback 闭环。
4. 形成 reproducible release bundle。
5. 写论文/技术报告级别的 ablation：fast-only vs SystemC-feedback vs calibrated multi-fidelity。

---

## 6. 前端成功标准

前端推进成功的标志不是“能跑更多脚本”，而是：

1. 一个 design point 从生成到后端执行再到反馈吸收，有唯一 ID 和完整证据链。
2. 所有 ranking 都带 claim ceiling，不会越权声称最终性能。
3. QE 是 adapter，不是 core；换一个 workload adapter 后，DSE core 不需要改。
4. BO、Cartesian、active sampling 都通过同一 search interface 输出 candidate。
5. fast model、SystemC feedback、gem5 feedback、implementation evidence 都能进入同一个 calibration/adjudication 管线。
