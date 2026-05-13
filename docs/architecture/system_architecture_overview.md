# DSE 异构加速系统设计空间探索系统架构设计总览

## 1. 文档定位与读者对象

本文件是全局系统架构入口，不替代专题文档，而是把系统级边界、控制层级、对象语义、模块分工与冻结状态统一收口。

本文件面向的系统对象是：**Generic DSE（设计空间探索）+ 多层次 TLM + SystemC/gem5 仿真迭代**框架。

| 项目 | 说明 |
| --- | --- |
| 文档作用 | 全局系统架构入口，统一收口，不承担单点实现细节冻结。 |
| 系统对象 | Generic DSE 框架：面向异构计算系统的 evidence-backed 设计空间探索。 |
| 读者对象 | 系统架构设计者、仿真后端开发者、DSE 算法研究者、论文整理者。 |
| 文档状态 | `v0`。系统合同已成型，硬件实现细节未冻结。 |

本文件遵循 `ISO/IEC/IEEE 42010` 的视角写法，也尽量保持 OpenTitan 风格的硬件文档习惯，即先定系统边界，再定模块边界，再定接口合同，最后才谈实现细节。

**重要声明**：本系统的核心仍是 domain-neutral 的 Generic DSE 框架，不把任何单一应用写死进 core schema。当前论文和工程收敛策略调整为：用 **DFT 计算（Density Functional Theory）到 FPGA 部署** 作为主证明场景和第一条完整 vertical slice，来证明框架对真实 workload、mapping、memory、runtime、gem5/software-visible evidence 的完备性；其他 workload 通过同一 profile/importer 合同继续支持和扩展。

## 2. 范围与非目标

### 2.1 覆盖范围

本文件覆盖面向异构计算系统的 evidence-backed Design Space Exploration（DSE）框架：

| 范围项 | 是否覆盖 | 说明 |
| --- | --- | --- |
| Workload ingestion | 是 | 多领域 workload profile/importer → WorkloadPackage → ComputeGraph。 |
| Architecture catalog | 是 | 可扩展的架构族、实例和 binding。 |
| Mapping search | 是 | Workload node、tensor/data、schedule 到硬件资源的映射搜索。 |
| HW/SW co-design search | 是 | 通过 gem5+SystemC/generic simulator 搜索硬件配置、软件 runtime、compiler lowering、descriptor 协议和调度策略。 |
| 多保真仿真 | 是 | L1 analytical → L2 TLM → L3 SystemC → L4 gem5+SystemC。 |
| Evidence 与 claim | 是 | 仿真证据、软硬件闭环证据、verdict、claim validation。 |
| Reporting | 是 | Final report、artifact manifest、adjudicator inputs。 |
| DFT→FPGA 主证明场景 | 是 | 作为第一条完整 reference vertical slice，用来证明通用框架完备性；不进入 core schema。 |
| 其他 workload families | 是 | 继续通过 profile/importer 支持 ml_tensor、sparse_la、stencil、graph、database/vector 等 family。 |

### 2.2 非目标

| 非目标项 | 说明 |
| --- | --- |
| DFT 软件专用加速器 | 本系统不把 QE/VASP/CP2K 或某个 DFT 软件栈写死为唯一目标；DFT 只是主证明场景。 |
| 完整通用处理器 ISA | 本系统不是通用 CPU 设计。 |
| 单个 block 的 RTL 微架构 | 本文件不冻结寄存器图、精确位宽与时序波形。 |
| 片上恢复软件栈 | 不是本文件目标。 |

### 2.3 数值能力声明（重要）

**当前状态**：`generic_sim_backend` 是**纯 timing estimator**，不执行实际数值计算。

- 它根据 `estimated_flops` 和加速器能力参数**估算执行时间**
- 它不执行实际的 GEMM/FFT/Eigen 计算
- 它不产生输出 tensor 的数值结果
- 因此**不能用于验证计算正确性**，也不能作为 RTL 的 UVM reference model

**设计目标**：本文档规划了从 timing-only 到 numerically-faithful reference model 的演进路径（见第 16 节）。

### 2.4 范围边界

本文件的边界可以概括为一句话：

> 本文件定义 Generic DSE 系统骨架、控制合同和对象合同，并规划 gem5+SystemC 软硬件协同搜索、数值计算层和 UVM reference model 的演进路径；它不定义最终电路实现。

### 2.5 通用框架与 DFT 主证明场景的关系

本项目采用“**通用核心 + 具体主场景证明**”的策略：

| 层级 | 角色 | 对 DFT 的处理方式 |
| --- | --- | --- |
| Core framework | `WorkloadPackage`、`ComputeGraph`、`DesignPoint`、evidence、promotion、reporting | 不出现 DFT 专用字段作为全局必需项。 |
| Reference adapters | profile/importer、domain validation、fixture/source parser | 可以实现 `dft_fpga_reference` / `dft_qe_reference`，但必须位于 `dse_v2/reference_workloads/` 或等价插件边界。 |
| Primary evaluation | 论文和工程主线的端到端 case study | 以 DFT config → workload graph → FPGA deployment → L3/L4 evidence 证明系统完备性。 |
| Future workload | ML tensor、sparse linear algebra、stencil、graph、database/vector search 等 | 复用同一 profile/importer + graph + mapping + evidence 合同扩展。 |

因此，“DFT 是主证明场景”不等于“系统是 DFT 专用系统”。DFT 的任务是提供足够真实、复杂且可复现实验的 workload family，帮助验证通用 DSE 框架是否覆盖 workload characterization、mapping/dataflow、memory movement、runtime schedule、host-FPGA interface 和 claim gate。

## 3. 设计驱动与关注点

### 3.1 设计驱动

当前系统设计的主要驱动是异构计算系统的设计空间探索需求：

| 设计驱动 | 含义 |
| --- | --- |
| Domain-neutral | core schema 不依赖任何单一应用领域。 |
| Evidence-backed | candidate、prediction、simulation、claim 必须分层。 |
| Replayable | Step1/Step2/Step3 的关键 artifacts 必须落盘。 |
| Generic-with-vertical-proof | core 保持多 workload 可扩展；DFT→FPGA 作为第一条完整证明链。 |
| 多保真迭代 | L1/L2 初筛 → L3/L4 高保真仿真 → 反馈更新搜索。 |
| 软硬件协同 | 同时搜索硬件参数、mapping、compiler/runtime schedule、driver/descriptor 协议和 memory/data movement。 |
| 异构支持 | Host + FPGA + Chip/CIM + optional CPU/GPU/ASIC。 |

### 3.2 干系人与关注点

| 干系人 | 关注点 | 需要从本文得到什么 |
| --- | --- | --- |
| 系统架构设计者 | 系统边界、阶段边界、演进边界 | 一张稳定的总图和冻结分层。 |
| 仿真后端开发者 | L3/L4 仿真后端架构、JSON IPC、proof gate | 后端接口和信任边界。 |
| DSE 算法研究者 | mapping search、promotion、feedback | 算法接口和证据流。 |
| 论文整理者 | 哪些内容已冻结，哪些内容仍是过渡 | 事实边界与可用证据顺序。 |

### 3.3 当前最重要的系统级关注点

1. 维持 `Step1 → Step2 → Step3 → Reporting` 四层分工，不把控制压回单层。
2. 维持 L1/L2 只用于初筛，L3/L4 才是可信证据的信任分层。
3. 把 gem5+SystemC 视为昂贵但权威的 software-visible co-design evidence oracle，而不是暴力搜索引擎。
4. 维持 domain-neutral 设计，同时把 DFT→FPGA 作为主证明场景和第一条完整 reference vertical slice。
5. 保持 evidence-backed claim，不把预测写成最终结论。
6. 保持 artifacts 落盘，后续步骤只读文件不依赖进程状态。

## 4. 顶层系统架构

### 4.1 系统分层

系统分层固定为四层：

```text
Step1: Workload Ingestion Layer
  -> profiles/importers → WorkloadPackage → ComputeGraph → lowering
  -> 输出: workload_package.json, workload_graph.json,
           graph_lowering_report.json, executable_graph.json

Step2: Architecture, Mapping, and Co-design Layer
  -> architecture catalog → DesignPoint → mapping/co-design search
  -> 输出: architecture.json, design_point.json, mapping.json,
           codesign_candidate.json, runtime_schedule.json,
           descriptor_protocol.json, mapping_legality_matrix.json,
           promotion_decision.json

Step3: Simulation Evidence Layer
  -> SystemC (L3) / gem5+SystemC (L4) → verdict → evidence
  -> 输出: simulation_request.json, simulation_result.json,
           l4_execution_trace.json, codesign_verdict.json,
           verdict.json, claim_validation.json

Reporting and Claim Layer
  -> final_report.json/md, manifest.json, artifact_manifest.json
```

### 4.2 顶层结构图

| 层级 | 主要职责 | 主要对象 | 当前状态 |
| --- | --- | --- | --- |
| `Step1` | Workload ingestion、lowering | WorkloadPackage、ComputeGraph | 已稳定。 |
| `Step2` | Architecture catalog、mapping、co-design search | DesignPoint、mapping candidates、co-design candidates | 主合同稳定，co-design search 为规划扩展。 |
| `Step3` | Simulation、evidence、verdict | simulation_request、result、verdict、codesign_verdict | L1-L3 稳定，L4 co-design verdict 为规划扩展。 |
| `Reporting` | Final report、claim validation | final_report、claim_validation | 已稳定。 |

### 4.3 保真度层级

| 层级 | 名称 | 作用 | 是否可支撑最终排名 | 当前状态 |
| --- | --- | --- | --- | --- |
| L1 | Analytical | 快速估算、剪枝、候选提名 | 否 | 已实现。 |
| L2 | Python TLM | 中等保真筛选、uncertainty hint | 否 | 已实现。 |
| L3 | Standalone SystemC | 单机可重放 timing/resource evidence | 条件允许 | 已实现。 |
| L4 | gem5+SystemC | 软件可见 descriptor/request/completion proof | 条件允许 | Proof-gated。 |
| Debug | System-test trace | 诊断、定位、复现实验 | 默认否 | 未实现。 |

### 4.4 顶层责任切分

| 层级 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| `Step1` | Workload 读取、graph 构建、lowering | 架构选择和映射决策。 |
| `Step2` | Architecture catalog、mapping/co-design search、promotion | 仿真执行和证据收集。 |
| `Step3` | 仿真执行、evidence 收集、verdict | 最终报告和 claim 表述。 |
| `Reporting` | Final report、claim validation、adjudicator inputs | workload 读取和仿真执行。 |

### 4.5 主证明路径：DFT config 到 FPGA deployment

当前收敛后的主证明路径如下：

```text
DFT Config / trace / profile
  -> Step1: DFT-aware workload characterization
       - atoms, nbands, npw, nfft, kpoints, spin, solver, precision
       - FFT / GEMM / reduction / eigensolver / SCF-loop / transfer graph
       - compute intensity, memory pressure, data reuse, host-FPGA transfer hints
  -> Step2: FPGA-focused architecture + mapping + co-design search
       - FFT pipeline variant, GEMM tiling, reduction tree, BRAM/URAM/HBM budget
       - stream overlap, DMA batching, descriptor granularity, precision policy
  -> Step3: L1/L2/L3/L4 evidence
       - timing/resource/data movement estimates
       - gem5 software-visible descriptor/DMA/MMIO/completion proof for selected candidates
  -> Reporting
       - best deployment under stated DFT config set
       - evidence bundle, blocked claims, limits, and portability notes to other workload families
```

这条路径用于证明框架完备性，具体证明项包括：

1. Step1 能把领域配置转成通用 `WorkloadPackage` / `ComputeGraph`，并保留 profile-specific metadata。
2. Step2 能把 workload facts 转成 FPGA mapping/dataflow/memory/runtime 候选，而不是只调 accelerator 参数表。
3. Step3 能用 L3/L4 分层证据区分预测、仿真证据和 software-visible proof。
4. Reporting 能说明 claim 边界：哪些结论只对当前 DFT config set 成立，哪些机制可迁移到其他 workload family。

## 5. 核心数据模型

### 5.1 WorkloadPackage

| 字段 | 说明 |
| --- | --- |
| `workload_family` | 工作负载族（dft_fpga_reference、ml_tensor、sparse_la、stencil_streaming、database_vector_search 等）。 |
| `profile_id` / `importer_id` | profile 声明策略和 claim boundary；importer 负责 source parsing/provenance。 |
| `source_format` | 原始格式（onnx-like、matrix_market、query_plan、generic_json 等）。 |
| `compute_graph` | 计算图引用。 |
| `provenance` | 来源、版本、生成时间。 |
| `claim_boundary` | 声明边界（full_workload、diagnostic 等）。 |

### 5.2 ComputeGraph

| 特性 | 说明 |
| --- | --- |
| `nodes` | 计算节点（算子、kernel、task）。 |
| `edges` | 数据边（普通、streaming、feedback、state）。 |
| `regions` | 层次化区域（支持嵌套）。 |
| `tensor_specs` | Tensor 形状、dtype、layout。 |

**重要**：ComputeGraph 支持 non-DAG 语义，包括 streaming、feedback 和 state 边。

### 5.3 DesignPoint

`DesignPoint` 是可重放候选的最小合同。它不只描述硬件，也必须显式记录 operator mapping、tensor/data placement、schedule、precision、fallback 和仿真绑定，避免隐含在 Python 进程状态中。

| 字段 | 说明 |
| --- | --- |
| `design_point_id` | 唯一标识。 |
| `workload` | 关联的 workload id、graph artifact id 和 claim boundary。 |
| `architecture` | 架构实例（family、components、memory hierarchy、interconnect、binding）。 |
| `mapping` | operator/resource 映射（node/region → resource）。 |
| `data_placement` | tensor/buffer/memory level 放置策略。 |
| `scheduling_policy` | task order、pipeline、overlap、batching 和 fallback 调度。 |
| `dataflow` | loop/dataflow 配置，例如 tiling、spatial/temporal mapping、streaming/fusion。 |
| `precision_policy` | dtype、quantization、mixed precision、CIM bit slicing 等策略。 |
| `fallback_policy` | unsupported/high-risk 节点回退路径和原因。 |
| `simulation_config` | L1/L2/L3/L4 后端、binding id、预算和 evidence mode。 |
| `output_config` | artifact 目录、trace 粒度、claim 类型和报告约束。 |

### 5.4 Architecture Catalog

Architecture catalog 定义架构族、实例和 binding：

| 状态 | 说明 |
| --- | --- |
| `implemented` | 已实现，有仿真后端支持。 |
| `unverified` | 已实现，但未验证。 |
| `prototype` | 原型阶段。 |
| `stub` | 占位符。 |
| `planned` | 计划中。 |
| `unsupported` | 不支持。 |
| `candidate-only` | 仅作为候选，不可信。 |
| `trusted-final-eligible` | 可进入最终排名。 |

### 5.5 CoDesignCandidate（规划）

`CoDesignCandidate` 用于表达软硬件协同搜索的整体候选。它引用 `DesignPoint`，并补充软件栈、runtime、compiler lowering、descriptor 协议和 memory policy。

| 字段 | 说明 |
| --- | --- |
| `codesign_candidate_id` | 唯一标识。 |
| `design_point_id` | 关联的硬件/mapping 设计点。 |
| `software_stack_config` | driver、runtime、library/API、host pre/post-processing 和 fallback 软件路径。 |
| `compiler_lowering` | op fusion、tiling、layout transform、precision lowering、sparse/CIM lowering。 |
| `runtime_schedule` | batching、command queue、copy/compute overlap、polling/interrupt、host/accelerator 同步策略。 |
| `descriptor_protocol` | descriptor format、doorbell、completion、shared memory layout、zero-copy/copy policy。 |
| `memory_policy` | host/device allocation、DMA、coherency、cacheability、pinning 和 data layout。 |
| `expected_claims` | 该候选希望证明的 timing、software-visible completion、host overhead、energy 或 correctness claim。 |

`CoDesignCandidate` 的核心作用是把“软件如何喂给硬件、硬件如何暴露给软件、二者如何共同调度”显式化，而不是只搜索 accelerator 参数表。

## 6. 控制架构

### 6.1 Step 流程

#### Step1：Workload ingestion

Step1 把领域输入转换为可审计 artifacts：

1. 读取 workload source（trace、graph、外部 IR）。
2. 通过 importer + profile 转换为 WorkloadPackage。
3. 构建 ComputeGraph。
4. 执行 graph lowering（如果需要）。
5. 输出 artifacts 到磁盘。

**核心验收标准**：后续流程可以只读这些 artifacts，而不依赖 importer 进程内状态。

#### Step2：Architecture and mapping

Step2 读取 Step1 artifacts 和 architecture catalog：

1. 选择 architecture family 和 instance。
2. 构建 DesignPoint。
3. 执行 mapping search。
4. 生成 mapping candidates。
5. 生成可选的 co-design candidates：software/runtime config、compiler lowering、descriptor protocol、memory policy。
6. 执行 promotion decision（是否值得进入仿真，是否需要 L4 software-visible proof）。
7. 输出 artifacts 和 Step3 handoff directory。

**核心约束**：Step2 只决定候选是否值得进入仿真，不产生最终可信结论；软硬件协同候选必须在 L4 证据链闭合后才能形成 software-visible claim。

#### Step3：Simulation evidence

Step3 读取 Step2 handoff artifacts：

1. 验证 Step2 artifacts 完整性和 promotion 状态。
2. 构造 simulation request（JSON）。
3. 运行 L3 SystemC 或 L4 gem5+SystemC 仿真。
4. 收集 evidence artifacts。
5. 生成 verdict 和 claim validation。

**核心约束**：如果候选缺少 binding、coverage、proof 或 required artifacts，Step3 必须阻止其进入 trusted ranking。

### 6.2 Promotion 决策

| 层级 | 决策 | 条件 |
| --- | --- | --- |
| L1 → L2 | promote | L1 结果满足 threshold，uncertainty 可接受。 |
| L2 → L3 | promote | L2 结果满足 threshold，需要更高保真证据。 |
| L3 → L4 | promote | L3 结果可信，需要软件可见 proof。 |
| 任意 → blocked | blocked | 缺少 artifacts、diagnostic only、或 proof gate 失败。 |

### 6.3 可信 Claim 条件

可信 claim 必须同时满足：

1. artifacts 存在且可解析；
2. `verdict.json` 允许对应 claim；
3. `claim_validation.json` 中 evidence id 可回溯；
4. 对 L4 claim，`gem5_l4_proof.json` 通过；
5. adjudicator 或等价规则允许对外表述。

## 7. 仿真后端架构

### 7.1 L3：Standalone SystemC Backend

**位置**：`model/generic_sim_backend/`

**架构**：

```text
Python DSE Framework
    |
    | JSON Request
    v
GenericSystemCBackend (Python)
    |
    | subprocess.run()
    v
generic_sim (C++ executable)
    |
    |-- SimTop
        |-- Host Model
        |-- Interconnect Model
        |-- Memory System
        |-- Accelerator Devices
        |   |-- GPUAccelerator
        |   |-- FPGAAccelerator
        |   |-- CIMAccelerator
        |   |-- GenericAccelerator
        |-- Graph Executor
        |-- Trace Recorder
    |
    | JSON Result
    v
Python DSE Framework
```

**支持的操作**：gemm、fft、eigen、reduction、elementwise、transfer、generic_op

**支持的加速器类型**：gpu、fpga、cim、asic、cpu

**Schema**：`simulation_request_v1.json`、`simulation_result_v1.json`

### 7.2 L4：gem5+SystemC Backend

**位置**：`gem5_integration/`

**组件**：

| 组件 | 文件 | 状态 |
| --- | --- | --- |
| GenericAccel 设备 | `src/dev/generic_accel/generic_accel.cc` | 已实现原型。 |
| L4 测试配置 | `configs/generic_accel_l4_test.py` | 已实现。 |
| Guest driver | `test_programs/generic_accel/generic_accel_l4_driver.c` | 已实现。 |
| L4 微架构 evidence adapter | `dse_v2/backends/gem5_systemc_adapter.py` + `gem5_integration/src/dev/generic_accel/` | Proof-gated，最小可信路径已实现。 |

**L4 Trust Boundary**：

L4 结果被 proof-gated。可信 L4 结果需要证据链：

1. gem5 软件写入 GSIM command descriptor；
2. GenericAccel 摄入 descriptor 和 request payload；
3. GenericAccel 在 gem5 内 decode request 并执行微架构 micro-op schedule；
4. completion/result 数据写回 guest-visible memory。

只有 `gem5.log` 同时证明 `descriptor_read`、`uarch_request_decode`、`microarchitecture_execute`、`completion_writeback`，且 guest driver 观察到 completion status 0 时，L4 才能 emit trusted verdict；否则必须 emit `blocked` verdict。

**Co-design Search Role**：

gem5+SystemC 不只是最终验证器，而是昂贵但权威的 software-visible co-design evidence oracle。它用于抽样验证并校准以下对象的组合：

- workload graph / executable graph；
- architecture instance 和 hardware knobs；
- operator mapping、tensor placement 和 schedule；
- compiler lowering、data layout、precision policy；
- driver/runtime policy、descriptor protocol、DMA/MMIO/completion 行为。

因此 L4 的 trusted claim 不是“硬件模型跑过”，而是“软件真实提交 descriptor，GenericAccel 消费 request，在 gem5 内执行微架构 schedule，completion 对 guest software 可见”。

### 7.3 后端连接

```text
dse_v2/
  |
  | GenericSystemCBackend.evaluate()
  |   -> builds JSON request
  |   -> subprocess.run(generic_sim)
  |   -> parses JSON result
  v
model/generic_sim_backend/
  |
  | generic_sim (C++ executable)
  |   -> validates request
  |   -> schedules graph
  |   -> estimates transfer/compute
  |   -> emits metrics/events/utilization
  v
JSON result
  |
  | Gem5SystemCClosureAdapter (optional L4 path)
  |   -> proof-gated
  |   -> blocked if no L4 evidence
  v
verdict.json + claim_validation.json
```

## 8. 模块级实现规范

### 8.1 dse_v2/ 模块树

```text
dse_v2/
├─ core/
│  ├─ workload/
│  │  ├─ profiles.py          # WorkloadProfile registry
│  │  ├─ importers.py         # WorkloadImporter registry
│  │  ├─ adapters.py          # Generic graph fixture builders
│  │  ├─ package.py           # WorkloadPackage
│  │  └─ lowering.py          # Graph lowering
│  ├─ ir/
│  │  ├─ compute_graph.py     # ComputeGraph IR
│  │  ├─ execution.py         # Execution timeline
│  │  └─ task_graph.py        # Task graph
│  └─ architecture/
│     └─ accelerator.py       # Accelerator abstractions
├─ architecture/
│  └─ catalog.py              # Architecture catalog
├─ mapping/
│  ├─ step2_workflow.py       # Step2 orchestration
│  └─ search.py               # Mapping search
├─ backends/
│  ├─ generic_systemc_bridge.py  # L3 Python bridge
│  ├─ systemc_backend.py      # Unified backend (generic/legacy)
│  └─ gem5_systemc_adapter.py # L4 proof-gated microarchitecture evidence
├─ dse/
│  ├─ orchestrator.py         # DSE orchestrator
│  ├─ analytical_evaluator.py # L1 evaluator
│  ├─ systemc_evaluator.py    # L3 evaluator
│  ├─ tlm_evaluator.py        # L2 evaluator
│  └─ multi_fidelity.py       # Multi-fidelity support
├─ evidence/
│  ├─ step3_workflow.py       # Step3 orchestration
│  └─ full_flow.py            # Full-flow evidence writer
├─ reporting/
│  └─ final_report.py         # Final report + claim validation
├─ registry/
│  └─ experiment_registry.py  # Campaign/trial ledger
├─ models/
│  ├─ fast/
│  │  └─ performance_model.py # L1 analytical model
│  └─ mid/
│     └─ python_tlm.py        # L2 Python TLM
├─ promotion/
│  ├─ promotion_engine.py     # Promotion decisions
│  └─ thresholds.py           # Thresholds
└─ scripts/
   └─ dse/
      ├─ run_full_flow_pilot.py  # Main entry point
      └─ run_end_to_end_dse.py   # Wrapper
```

### 8.2 每个模块的最小功能合同

| 模块 | 最小稳定功能 | 最小输入 | 最小输出 |
| --- | --- | --- | --- |
| `profiles.py` | 注册 profile policy/coverage/claim boundary。 | profile id | `WorkloadProfile` |
| `importers.py` | 注册和调用 workload importer。 | source + profile | `WorkloadPackage` |
| `adapters.py` | 生成通用 fixture graphs。 | generator params | `ComputeGraph` |
| `package.py` | 构建和验证 WorkloadPackage。 | source data | `WorkloadPackage` |
| `workflows.py` | compatibility view of profile metadata。 | family name | profile metadata |
| `lowering.py` | 将 ComputeGraph lower 为 executable view。 | `ComputeGraph` | `GraphLoweringResult` |
| `compute_graph.py` | 构建和遍历计算图。 | nodes、edges | `ComputeGraph` |
| `accelerator.py` | 定义加速器抽象。 | accelerator type | `Accelerator` |
| `catalog.py` | 管理 architecture catalog。 | family、constraints | `ArchitectureInstance` |
| `step2_workflow.py` | 执行 Step2 handoff。 | Step1 artifacts | Step2 artifacts |
| `search.py` | 执行 mapping search。 | executable graph、architecture | mapping candidates |
| `generic_systemc_bridge.py` | 构建 JSON request 并调用 generic_sim。 | `DesignPoint`、`ComputeGraph` | simulation result |
| `gem5_systemc_adapter.py` | Proof-gated L4 microarchitecture evidence。 | descriptor/request/decode/execute/completion evidence、co-design candidate | L4/co-design verdict or blocked |
| `step3_workflow.py` | 执行 Step3 evidence flow。 | Step2 artifacts | Step3 artifacts |
| `full_flow.py` | 写入 full-flow evidence bundle。 | simulation result | evidence artifacts |
| `final_report.py` | 生成 final report 和 claim validation。 | evidence artifacts | `final_report.json/md` |
| `experiment_registry.py` | 记录 campaign 和 trial。 | run metadata | ledger entries |
| `promotion_engine.py` | 执行 promotion 决策。 | evaluation result | `PromotionDecision` |
| `performance_model.py` | L1 analytical evaluation。 | `DesignPoint`、workload | L1 metrics |
| `python_tlm.py` | L2 Python TLM evaluation。 | `DesignPoint`、workload | L2 metrics |

## 9. 外部接口与系统集成约束

### 9.1 Python → C++ JSON IPC

| 接口方向 | 格式 | 说明 |
| --- | --- | --- |
| Python → C++ | `simulation_request_v1.json` | 包含 design point、workload、accelerator config。 |
| C++ → Python | `simulation_result_v1.json` | 包含 metrics、events、utilization、status。 |

### 9.2 JSON Request 结构

```json
{
  "schema_version": "gsim.request.v1",
  "mode": "generic",
  "design_point": {
    "architecture": { ... },
    "mapping": { ... }
  },
  "workload": {
    "graph": { ... },
    "tensors": [ ... ]
  },
  "accelerators": [
    {"type": "gpu", "name": "gpu-0", ...},
    {"type": "fpga", "name": "fpga-0", ...}
  ]
}
```

### 9.3 JSON Result 结构

```json
{
  "schema_version": "gsim.result.v1",
  "status": "ok",
  "metrics": {
    "latency_ms": 123.4,
    "throughput_gops": 56.7,
    "power_w": 12.3
  },
  "events": [ ... ],
  "utilization": { ... }
}
```

### 9.4 时钟 / 复位 / 功耗

这一章节存在，但内容未冻结。

| 项目 | 当前状态 |
| --- | --- |
| 时钟 | 章节存在，实质内容未冻结。 |
| 复位 | 章节存在，实质内容未冻结。 |
| 功耗 | 章节存在，实质内容未冻结。 |
| Design-for-Test / BIST / 片上 debug fabric | 不在本文件覆盖范围；这里的 Design-for-Test 不等同于本文主证明场景中的 Density Functional Theory。 |

## 10. 当前可运行模型与验证状态

### 10.1 可运行模型位置与能力

| 位置 | 能力 | 当前状态 |
| --- | --- | --- |
| `dse_v2/scripts/dse/run_full_flow_pilot.py` | Full-flow pilot：Step1 → Step2 → Step3 → Reporting。 | 可运行。 |
| `model/generic_sim_backend/build/generic_sim` | L3 standalone SystemC 仿真后端。 | 可运行。 |
| `dse_v2/tests/*.py` | 20+ 回归测试文件。 | 可运行。 |

### 10.2 模型已经证明的内容

| 已证明内容 | 证据类型 | 说明 |
| --- | --- | --- |
| Generic DSE 四层流程成立 | 代码实现 | Step1 → Step2 → Step3 → Reporting 可运行。 |
| L1/L2 初筛模型 | 代码实现 | FastPerformanceModel、PythonTLM 已实现。 |
| L3 SystemC 后端 | 代码实现 | generic_sim 可执行，JSON IPC 工作。 |
| Evidence 与 claim 体系 | 代码实现 | verdict、claim_validation、final_report 完整。 |
| Multi-fidelity promotion | 代码实现 | L1→L2→L3 promotion 决策完整。 |

### 10.3 模型还没有证明的内容

| 未证明内容 | 说明 |
| --- | --- |
| 生产级 L4 覆盖 | 最小 GenericAccel descriptor/request/decode/microarchitecture/completion 证据链已可 trusted；尚需扩展 FS/cache/coherency、host overhead、更多 workloads 和更丰富 trace metrics。 |
| Debug/System Test Layer | 未实现。 |
| Distributed runtime | 只有数据模型和兼容字段。 |
| HW/SW co-design search loop | 已定义方向；尚未把 co-design candidate、gem5 sampling、feedback calibration 接入完整搜索闭环。 |
| DFT→FPGA 主证明闭环 | 需要把 DFT config characterization、FPGA deployment knobs、L3/L4 evidence 和 final report 串成稳定端到端 case study。 |
| WorkloadProfile / WorkloadImporter | 已实现基础；DFT reference importer 作为主证明入口优先补强，其他生产级 importer 后续扩展。 |
| 多 workload 生产导入器 | sparse/tensor/stencil/graph/vector/custom fixture path 已可运行；真实外部格式 importer 仍需扩展。 |

### 10.4 软件证据完整度排序

| Workload Family | 证据完整度 | 说明 |
| --- | --- | --- |
| `dft_fpga_reference` / `dft_qe_reference` | 主证明场景 | 作为第一条完整 vertical slice：DFT config/profile → workload graph → FPGA deployment/co-design → L3/L4 evidence；不得把 DFT 字段提升为 core 必需字段。 |
| `sparse_la` | 中 | generic_json + generated sparse fixture 已可跑 L3 pilot；生产 MatrixMarket importer 待扩展。 |
| `ml_tensor` | 中 | generated tensor fixture 可跑；生产 ONNX-like importer 待扩展。 |
| `stencil_streaming` | 中 | generated stencil fixture 可跑；生产 DSL importer 待扩展。 |
| `graph_analytics` | 中 | generated graph fixture 可跑；生产 graph dataset importer 待扩展。 |
| `database_vector_search` | 中 | generated vector-search fixture 可跑；生产 query-plan/index importer 待扩展。 |

## 11. 建模层级判定

### 11.1 L1-L4 四级定义

| 层级 | 名称 | 能回答的问题 | 当前状态 |
| --- | --- | --- | --- |
| L1 | Analytical | 快速估算、剪枝、候选提名。 | 已完成。 |
| L2 | Python TLM | 中等保真筛选、uncertainty hint。 | 已完成。 |
| L3 | Standalone SystemC | 单机可重放 timing/resource evidence。 | 已完成。 |
| L4 | gem5 GenericAccel microarchitecture | 软件可见 descriptor/request/decode/execute/completion proof。 | Proof-gated，最小可信路径已解锁。 |

### 11.2 当前最准确的一句话

> Generic DSE 框架的四层流程（Step1→Step2→Step3→Reporting）和 L1-L4 最小可信证据路径已经可以运行；下一步是用 DFT→FPGA 主证明场景闭合 workload characterization、mapping/dataflow、memory/runtime 和 gem5 software-visible co-design evidence，同时保留多 workload 扩展合同。

## 12. 冻结项、过渡项与缺口

### 12.1 已冻结内容清单

| 已冻结项 | 说明 |
| --- | --- |
| Generic DSE 四层流程 | Step1 → Step2 → Step3 → Reporting。 |
| L1/L2/L3 保真度体系 | Analytical → TLM → SystemC。 |
| Domain-neutral core schema | WorkloadPackage、ComputeGraph、DesignPoint。 |
| Evidence-backed claim 体系 | verdict、claim_validation、final_report。 |
| JSON IPC 接口 | simulation_request_v1.json、simulation_result_v1.json。 |
| L4 proof gate | 缺少 descriptor/request/decode/microarchitecture execution/completion 或 software-visible proof 时返回 blocked verdict。 |
| 通用核心 / 领域适配边界 | DFT 可以作为主证明 adapter，但 core schema 不吸收 DFT 专用字段。 |

### 12.2 过渡项清单

| 过渡项 | 说明 |
| --- | --- |
| L4 gem5 microarchitecture | 最小 SE-mode descriptor/request/decode/execute/completion 证据链已实现；仍需扩展 FS 启动、cache/coherency、host overhead 和 co-design sampling 深度。 |
| WorkloadProfile / WorkloadImporter | 已替换 core adapter 语义；需要补生产级 source importers。 |
| DFT reference vertical slice | 作为主证明场景优先实现；仍必须保持在 `reference_workloads/` 或插件边界，不得回到 core schema。 |
| 更多 workload family | 需要实现 ONNX/MatrixMarket/DSL/query-plan 等真实 importer，用来证明框架可迁移。 |
| Debug/System Test Layer | 需要实现侧车层。 |
| HW/SW co-design search | 需要冻结 CoDesignCandidate、runtime schedule、descriptor protocol、L4 evidence artifacts 和反馈校准合同。 |

### 12.3 关键规范缺口

| 缺口 | 说明 |
| --- | --- |
| L4 可信证据链扩展 | 最小 SE-mode proof 已实现；需要 gem5 FS/cache/coherency、host overhead、DMA/MMIO 细粒度指标和更多 workload 覆盖。 |
| DFT→FPGA 主证明 spec | 需要冻结 DFT config schema、DFT mini-graph coverage、FPGA deployment knobs、domain validation 和 case-set 边界。 |
| 生产级多 workload 导入 | 需要真实外部格式 importer 和测试；优先级低于 DFT 主证明闭环，但接口必须保持可扩展。 |
| Distributed runtime | 只有数据模型，无实际运行时。 |
| 软硬件协同搜索 | 缺少 co-design candidate schema、gem5 trace metrics、surrogate calibration 和 promotion policy。 |
| 时钟/复位/功耗 | 章节存在，内容未冻结。 |

## 13. 支撑文档关系图

### 13.1 本文与其他关键文档的关系

| 文档 | 角色 | 与本文关系 |
| --- | --- | --- |
| `docs/architecture/generic_dse_global_system_design_v0.md` | 全局设计入口 | 本文的上位来源和事实基线。 |
| `docs/architecture/generic_dse_framework_design_spec_v2.md` | 子系统详细设计 | 补充数据模型、Step1/2/3 和信任边界。 |
| `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md` | 操作手册 | 说明如何运行、审查 artifacts 和避免 overclaim。 |
| `dse_v2/README.md` | 实现入口 | 说明代码目录、主要命令和测试。 |
| `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md` | 报告 schema | full-flow report schema 和 claim-validation 规则。 |
| `openspec/HANDBOOK.md` | OpenSpec 治理 | active change、spec 和 archive 的职责。 |

### 13.2 推荐阅读顺序

| 顺序 | 文档 | 理由 |
| --- | --- | --- |
| 1 | `docs/architecture/generic_dse_global_system_design_v0.md` | 先看系统级事实基线。 |
| 2 | `docs/architecture/generic_dse_framework_design_spec_v2.md` | 再看子系统详细设计。 |
| 3 | `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md` | 再看操作手册。 |
| 4 | `dse_v2/README.md` | 再看实现入口。 |
| 5 | `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md` | 最后看报告规则。 |

## 14. 结论与下一步冻结顺序

### 14.1 当前最准确的一句话总结

> 这是一个面向异构计算系统的 evidence-backed Generic DSE 框架；核心保持多 workload 可扩展，当前主线用 DFT→FPGA vertical slice 证明框架完备性，下一步重点是闭合 DFT workload characterization、FPGA mapping/co-design search、L3/L4 gem5 software-visible evidence 和 claim/reporting。

### 14.2 下一步冻结顺序建议

1. **冻结“通用核心 + DFT 主证明场景”边界**：
   - core schema 保持 domain-neutral；
   - DFT 字段只出现在 reference workload/profile/importer、case config 或 artifact metadata 中；
   - final report 必须区分“对 DFT case 成立的结论”和“框架机制可迁移的结论”。
2. **巩固 profile/importer 主线**：
   - 保持 WorkloadProfile / WorkloadImporter 为唯一 active ingestion 入口；
   - DFT reference workload 只保留在 `reference_workloads/` 或插件边界；
   - 持续禁止 reference workload 常量回到 core；
   - 用 generic profile/importer CLI 作为默认入口。
3. **优先冻结 DFT→FPGA 主证明合同**：
   - 定义 `DftConfig`、DFT mini graph coverage、case-set 边界和 domain validation；
   - 定义 FPGA deployment knobs：FFT pipeline、GEMM tile、reduction tree、BRAM/URAM/HBM、DMA batching、stream overlap、precision policy；
   - 明确 DFT case 如何落到通用 `WorkloadPackage`、`ComputeGraph`、`DesignPoint`、`CoDesignCandidate`。
4. **冻结软硬件协同搜索合同**：
   - 定义 `CoDesignCandidate`、`software_stack_config`、`runtime_schedule`、`compiler_lowering`、`descriptor_protocol`、`memory_policy`；
   - 明确 gem5 trace metrics、L4 sampling 策略和反馈校准 artifact。
5. **深化 L4 gem5 微架构路径**：
   - 在已完成的 SE-mode descriptor → request → uarch execute → completion 证据链基础上，扩展 gem5 FS/cache/coherency；
   - 增强 DMA/MMIO、host overhead、queue stall 和 accelerator utilization trace；
   - 先把 DFT→FPGA top-K / uncertainty-high candidates 纳入 L4 抽样校准，再推广到其他 workload。
6. **扩展 workload family**：
   - 保留并回归 ml_tensor、sparse_la、stencil、graph、database/vector 的 generic path；
   - 在 DFT 主证明闭合后，实现更多真实 source importers。
7. **强化证据与 claim 体系**：
   - 完善自动化 claim validation；
   - 增加 CI 流程。

### 14.3 最后结论

当前最稳妥的判断不是"系统已经完成"，而是：

> Generic DSE 框架的核心流程和 L1-L3 保真度体系已经稳定；当前不再追求一开始覆盖所有 workload，而是用 DFT→FPGA 主证明场景把 Step1/Step2/Step3/Reporting 和 L4 co-design evidence 做实，再把同一合同迁移到其他 workload family。

本文只负责把总览收口，不负责替代各专题文档。

## 15. gem5 + SystemC 软硬件协同 DSE 设计（规划）

### 15.1 设计定位

本系统将 gem5 GenericAccel L4 + SystemC/generic simulator 定义为 **software-visible co-design evidence oracle**：

- **gem5** 负责软件可见路径：driver/runtime、MMIO、DMA、descriptor、completion、host overhead、cache/coherency 影响；
- **GenericAccel L4 微架构模型 / SystemC/generic simulator** 负责硬件 timing/resource/data-movement 估计；
- **DSE framework** 负责多保真搜索、候选筛选、promotion、feedback calibration 和 claim gate。

因此 L4 不只是“最后跑一次验证”，而是用于抽样证明并校准完整软硬件协同方案：

```text
workload + architecture + mapping + memory/data placement
+ compiler lowering + runtime schedule + descriptor protocol
+ gem5-visible driver/MMIO/DMA/completion behavior
```

可信结论必须来自这个整体 design point，而不是来自孤立的 accelerator timing 数字。

**第一目标场景**：co-design search 首先在 DFT→FPGA vertical slice 上落地。DFT case 覆盖 FFT、GEMM、reduction、eigensolver shell、SCF loop summary 和 host-FPGA transfer，足以暴露 compute/memory/dataflow/runtime/interface 的联合搜索问题；其他 workload 后续复用相同 `CoDesignCandidate` 合同。

### 15.2 搜索对象

软硬件协同搜索的最小对象是 `CoDesignCandidate`：

```yaml
CoDesignCandidate:
  codesign_candidate_id: string
  design_point_id: string
  workload_id: string
  architecture_id: string
  mapping_id: string
  hardware_config: object
  software_stack_config: object
  compiler_lowering: object
  runtime_schedule: object
  descriptor_protocol: object
  memory_policy: object
  simulation_binding:
    l3_systemc: optional string
    l4_gem5_systemc: optional string
  expected_claims: list[string]
  promotion_policy:
    l4_required: bool
    reason: string
```

`CoDesignCandidate` 必须可重放，并且所有影响软件/硬件交互的决策都必须落盘。

### 15.3 搜索空间

| 类别 | 典型 knobs | 说明 |
| --- | --- | --- |
| Hardware knobs | accelerator count、DMA engine count、queue depth、scratchpad/cache size、coherency mode、interconnect bandwidth、interrupt latency、CIM array config | 硬件资源和接口能力。 |
| Software knobs | batching policy、polling vs interrupt、descriptor granularity、host pre/post-processing、fallback policy、memory allocation policy | 软件如何提交、同步和回退。 |
| Compiler/runtime knobs | op fusion、kernel partition、tile size、stream overlap、prefetch distance、precision lowering、sparse format selection | 编译器和 runtime 如何组织 workload。 |
| Interface knobs | descriptor format、doorbell policy、completion path、shared memory layout、zero-copy/copy policy、cacheability | 软件/硬件边界协议。 |

这些 knobs 应被视为联合搜索空间。单独搜索 accelerator 参数但固定软件路径，不能形成完整的 co-design claim。

在 DFT→FPGA 主证明场景中，优先冻结以下子空间，避免早期复杂度失控：

| DFT/FPGA 子空间 | 典型 knobs |
| --- | --- |
| DFT config | atoms、nbands、npw、nfft、kpoints、spin_channels、scf_iterations、solver、precision。 |
| Kernel/dataflow | FFT pipeline variant、GEMM tile M/N/K、reduction tree width、eigensolver batching、SCF region scheduling。 |
| FPGA memory | BRAM/URAM/HBM budget、scratchpad partition、stream buffer depth、host-device tensor placement。 |
| Runtime/interface | DMA batch size、copy/compute overlap、descriptor granularity、polling/interrupt、fallback policy。 |

### 15.4 多保真闭环

推荐搜索路径：

```text
Step1 workload ingestion
  -> workload graph / executable graph

Step2 architecture + mapping + co-design search
  -> DesignPoint
  -> CoDesignCandidate
  -> software/runtime/interface candidates

L1 analytical screening
  -> quick pruning, rough host/device/transfer estimates

L2 Python TLM
  -> uncertainty hints, queue/overlap approximation

L3 SystemC/generic_sim
  -> timing/resource/data movement sample

L4 gem5 GenericAccel microarchitecture
  -> software-visible descriptor/MMIO/DMA/request-decode/microarchitecture/completion proof
  -> host overhead and runtime schedule evidence

Feedback
  -> calibrate L1/L2/L3 models
  -> update surrogate/ranking/pruning/promotion
  -> generate next candidates
```

由于 gem5 成本高，L4 应只跑 top-K、uncertainty 高、或者 claim-critical 的 candidates。gem5 不承担 brute-force search；它承担 expensive but authoritative sampling。

### 15.5 L4 证据 artifacts

软硬件协同 L4 路径应输出以下 artifacts：

| Artifact | 说明 |
| --- | --- |
| `codesign_candidate.json` | 完整软硬件协同候选。 |
| `software_stack_config.json` | driver/runtime/library/API 配置。 |
| `runtime_schedule.json` | batching、queue、overlap、polling/interrupt、fallback 调度。 |
| `compiler_lowering.json` | tiling、fusion、layout transform、precision/sparse/CIM lowering。 |
| `descriptor_protocol.json` | descriptor、doorbell、completion、shared memory、zero-copy/copy 策略。 |
| `gem5_config.json` | gem5 CPU/memory/cache/device/config 参数。 |
| `l4_execution_trace.json` | 软件提交、设备摄入、request decode、microarchitecture execution、completion 的端到端 trace。 |
| `dma_trace.json` | DMA bytes、burst、stall、overlap。 |
| `mmio_trace.json` | MMIO count、latency、doorbell 和 status polling。 |
| `cpu_runtime_trace.json` | host overhead、busy/wait、polling/interrupt、runtime scheduling。 |
| `accelerator_trace.json` | accelerator utilization、queue stall、compute/transfer overlap。 |
| `completion_proof.json` | guest-visible completion/result memory proof。 |
| `codesign_verdict.json` | co-design candidate 的 trusted/blocked/diagnostic verdict。 |

### 15.6 软硬件协同指标

co-design search 的目标函数应至少支持：

```yaml
Objectives:
  latency_ms
  throughput_ops_per_s
  energy_j
  host_overhead_ms
  cpu_occupancy
  dma_bytes
  dma_stall_time_ms
  mmio_count
  mmio_latency_ms
  interrupt_count
  queue_stall_time_ms
  accelerator_utilization
  memory_bandwidth_pressure
  software_visible_completion_latency_ms
```

其中 `host_overhead_ms`、`dma/mmio overhead`、`queue_stall_time_ms`、`software_visible_completion_latency_ms` 是 L4 相对 L3 的关键增量价值。

### 15.7 Promotion 与 claim gate

一个 co-design candidate 只有满足以下条件，才能进入 trusted co-design ranking：

1. `codesign_candidate.json` 和关联 DesignPoint artifacts 完整；
2. L3 SystemC/generic simulator 或 L4 GenericAccel microarchitecture 能消费同一个 workload/mapping/architecture payload；
3. L4 gem5 path 证明 descriptor/request 被 GenericAccel 摄入和 decode；
4. GenericAccel 从该设备路径执行 microarchitecture schedule，而不是绕过软件路径直接调用；
5. completion/result 对 guest-visible memory 或 driver status 可见；
6. `codesign_verdict.json` 允许对应 claim；
7. `claim_validation.json` 能回溯到 L4 execution trace 和 completion proof。

失败时必须进入 `blocked` 或 `diagnostic-only`，不能降级成 trusted performance ranking。

### 15.8 设计创新点

本系统在该方向上的创新边界是：

1. **Proof-carrying HW/SW Co-DSE**：输出候选同时输出证据链，说明为什么该软硬件协同方案可信。  
2. **Software-visible accelerator DSE**：只有软件真实提交 descriptor、触发 DMA/MMIO、收到 completion 的方案，才允许 trusted claim。  
3. **Interface-aware search**：descriptor 协议、queue、doorbell、polling/interrupt、zero-copy/copy policy 都纳入搜索空间。  
4. **Multi-fidelity co-design closure**：L1/L2/L3 用于快速筛选，L4 用于权威抽样和反馈校准。  
5. **Negative evidence / blocked verdict**：证据链闭合不了就阻止 overclaim。

### 15.9 实现路线图

| Phase | 目标 | 最小完成标准 |
| --- | --- | --- |
| Phase A | 冻结 co-design schema | `CoDesignCandidate`、runtime schedule、descriptor protocol、memory policy schema 落盘。 |
| Phase B | L4 trace instrumentation | gem5 path 输出 MMIO/DMA/descriptor/completion/host-overhead trace。 |
| Phase C | Co-design promotion policy | Step2 能标记哪些候选必须进入 L4，Step3 能生成 `codesign_verdict.json`。 |
| Phase D | Feedback calibration | L4 sample 校准 L1/L2/L3 host overhead、queue stall、DMA/MMIO 估计。 |
| Phase E | Trusted co-design report | Final report 支持 software-visible co-design ranking 和 blocked/diagnostic limitations。 |

## 16. 数值计算层与 UVM Reference Model 设计（规划）

### 16.1 设计动机

当前 `generic_sim_backend` 是**纯 timing estimator**，不执行实际数值计算。这导致：

1. **无法验证计算正确性**：只能估算时间，不能验证 GEMM/FFT/Eigen 结果是否正确
2. **无法作为 RTL UVM Reference Model**：缺少数值输出，无法与 RTL 进行 bit-exact 或 tolerance-based 对比
3. **DSE 结果可信度受限**：只能优化 timing/power，不能验证功能正确性

本节设计从 timing-only 到 **numerically-faithful reference model** 的演进路径。

### 16.2 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│                 Numerical Execution Layer                    │
├─────────────────────────────────────────────────────────────┤
│ 1. Tensor Store                                              │
│    - Input tensors (from workload graph)                     │
│    - Intermediate tensors (node outputs)                     │
│    - Output tensors (final results)                          │
├─────────────────────────────────────────────────────────────┤
│ 2. Numerical Op Kernels                                      │
│    - GemmKernel: actual matrix multiplication                │
│    - FftKernel: actual FFT/IFFT                              │
│    - EigenKernel: actual eigensolver                         │
│    - ReductionKernel: actual reduction ops                   │
│    - ElementwiseKernel: actual elementwise ops               │
├─────────────────────────────────────────────────────────────┤
│ 3. Reference Model Interface                                 │
│    - Golden model execution (FP64/FP32 on host)              │
│    - Result comparison (absolute/relative tolerance)         │
│    - Scoreboard (transaction-level checking)                 │
├─────────────────────────────────────────────────────────────┤
│ 4. UVM TLM2.0 Bridge (Optional)                              │
│    - TLM2.0 initiator/target sockets                         │
│    - Transaction payload with numerical data                 │
│    - DPI-C interface for SystemVerilog integration           │
└─────────────────────────────────────────────────────────────┘
```

### 16.3 核心设计决策

#### 16.3.1 数值执行模式

| 模式 | 说明 | 用途 |
| --- | --- | --- |
| `timing_only` | 当前模式：只估算时间 | DSE 快速探索 |
| `numerical_reference` | 执行实际计算，与 golden model 对比 | 功能验证、UVM reference |
| `numerical_dse` | 执行实际计算 + timing 估算 | 功能+性能联合优化 |

#### 16.3.2 Tensor 存储设计

```cpp
// simulation_types.hpp 扩展
struct Tensor {
    std::string tensor_id;
    std::vector<int> shape;
    std::string dtype;  // "FP64", "FP32", "FP16", "INT32", etc.
    std::vector<uint8_t> data;  // Raw byte data
    
    // Type-safe accessors
    template<typename T>
    T* data_ptr() { return reinterpret_cast<T*>(data.data()); }
    
    size_t num_elements() const;
    size_t element_size() const;
    void allocate();
    void fill_random(uint32_t seed);
    void fill_pattern(double value);
};

struct TensorStore {
    std::map<std::string, Tensor> tensors;
    
    Tensor* get(const std::string& tensor_id);
    void allocate(const std::string& tensor_id, const std::vector<int>& shape, const std::string& dtype);
    void copy_from_host(const std::string& tensor_id, const void* host_data);
    void copy_to_host(const std::string& tensor_id, void* host_data);
};
```

#### 16.3.3 Numerical Op Kernel 接口

```cpp
// op_model_registry.hpp 扩展
class NumericalOpKernel {
public:
    virtual ~NumericalOpKernel() = default;
    virtual bool supports(const std::string& op_type) const = 0;
    
    // Execute the operation numerically
    virtual void execute(
        const ComputeNode& node,
        TensorStore& tensor_store,
        const AcceleratorDesc* accel
    ) = 0;
    
    // Validate numerical correctness against reference
    virtual bool validate(
        const ComputeNode& node,
        TensorStore& tensor_store,
        const TensorStore& reference_store,
        double abs_tolerance,
        double rel_tolerance,
        std::string& error_msg
    ) = 0;
};

// Concrete kernels
class GemmNumericalKernel : public NumericalOpKernel {
public:
    bool supports(const std::string& op_type) const override;
    void execute(const ComputeNode& node, TensorStore& store, const AcceleratorDesc* accel) override;
    bool validate(const ComputeNode& node, TensorStore& store, const TensorStore& ref, 
                  double abs_tol, double rel_tol, std::string& err) override;
};

class FftNumericalKernel : public NumericalOpKernel {
    // Similar interface
};

class EigenNumericalKernel : public NumericalOpKernel {
    // Similar interface
};
```

#### 16.3.4 Golden Model 框架

```cpp
// golden_model.hpp
class GoldenModel {
public:
    // Execute on host CPU with high precision (FP64)
    void execute_graph(
        const ComputeGraph& graph,
        TensorStore& input_store,
        TensorStore& output_store
    );
    
    // Compare results
    static bool compare_tensors(
        const Tensor& actual,
        const Tensor& expected,
        double abs_tolerance,
        double rel_tolerance,
        std::string& error_msg
    );
    
    // Generate statistics
    static void compute_error_metrics(
        const Tensor& actual,
        const Tensor& expected,
        double& max_abs_error,
        double& max_rel_error,
        double& rmse
    );
};
```

#### 16.3.5 Scoreboard 设计

```cpp
// scoreboard.hpp
class Scoreboard {
public:
    void register_transaction(const Transaction& txn);
    void register_expected(const Transaction& expected);
    void check_all();
    
    struct CheckResult {
        bool passed;
        std::string transaction_id;
        std::string error_msg;
        double max_abs_error;
        double max_rel_error;
    };
    
    std::vector<CheckResult> results;
};
```

### 16.4 JSON Schema 扩展

#### 16.4.1 Request Schema 扩展 (v2)

```json
{
  "schema_version": "gsim.request.v2",
  "mode": "numerical_reference",
  "numerical_config": {
    "enable_numerical_execution": true,
    "enable_golden_model": true,
    "abs_tolerance": 1e-6,
    "rel_tolerance": 1e-5,
    "tensor_init": {
      "method": "random",  // "random", "pattern", "from_file"
      "seed": 42,
      "pattern_value": 1.0
    }
  },
  "workload": {
    "nodes": {
      "node_0": {
        "op_type": "gemm",
        "inputs": ["A", "B"],
        "outputs": ["C"],
        "attributes": {
          "M": 1024,
          "N": 1024,
          "K": 1024,
          "transA": false,
          "transB": false
        }
      }
    }
  }
}
```

#### 16.4.2 Result Schema 扩展 (v2)

```json
{
  "schema_version": "gsim.result.v2",
  "status": "passed",
  "numerical_validation": {
    "enabled": true,
    "golden_model_executed": true,
    "all_tensors_passed": true,
    "tensors": [
      {
        "tensor_id": "C",
        "shape": [1024, 1024],
        "dtype": "FP64",
        "max_abs_error": 1.2e-15,
        "max_rel_error": 3.4e-16,
        "rmse": 8.9e-16,
        "passed": true
      }
    ]
  },
  "metrics": { ... }
}
```

### 16.5 UVM TLM2.0 集成设计

#### 16.5.1 TLM2.0 Transaction Types

```cpp
// tlm_transaction.hpp
#include <tlm.h>

struct NumericalTransaction : public tlm::tlm_generic_payload {
    // Transaction types
    enum Command {
        GEMM,
        FFT,
        EIGEN,
        REDUCTION,
        TRANSFER
    };
    
    Command cmd;
    std::string tensor_id;
    std::vector<int> shape;
    std::string dtype;
    
    // For GEMM
    int M, N, K;
    bool transA, transB;
    
    // Timing annotation
    sc_time delay;
};
```

#### 16.5.2 TLM2.0 Socket Interface

```cpp
// tlm_bridge.hpp
class GenericAccelTlmBridge : public sc_module {
public:
    // TLM2.0 sockets
    tlm::tlm_target_socket<> target_socket;
    tlm::tlm_initiator_socket<> initiator_socket;
    
    SC_HAS_PROCESS(GenericAccelTlmBridge);
    GenericAccelTlmBridge(sc_module_name name);
    
    // Target interface (from gem5)
    virtual void b_transport(tlm::tlm_generic_payload& trans, sc_time& delay);
    
    // Initiator interface (to memory)
    void read_tensor(const std::string& tensor_id, Tensor& tensor);
    void write_tensor(const std::string& tensor_id, const Tensor& tensor);
    
private:
    GraphExecutor* executor_;
    TensorStore* tensor_store_;
};
```

#### 16.5.3 DPI-C Interface (for SystemVerilog UVM)

```cpp
// dpi_interface.cpp
extern "C" {
    // Called from SystemVerilog UVM testbench
    int gsim_execute_request(const char* request_json, char* result_json, int result_size);
    
    // Get tensor data for comparison
    int gsim_get_tensor(const char* tensor_id, double* data, int max_elements);
    
    // Set tensor data as input
    int gsim_set_tensor(const char* tensor_id, const double* data, int num_elements);
    
    // Validate against golden
    int gsim_validate(const char* tensor_id, double abs_tol, double rel_tol);
}
```

### 16.6 实现路线图

#### Phase 1: Core Numerical Infrastructure

1. **Tensor Store 实现**
   - 内存分配和管理
   - 类型安全访问器
   - 序列化/反序列化（JSON/binary）

2. **Basic Numerical Kernels**
   - GemmNumericalKernel（基于 BLAS/OpenBLAS/MKL）
   - ElementwiseNumericalKernel
   - ReductionNumericalKernel

3. **Golden Model Framework**
   - Host CPU FP64 执行
   - Tensor 对比（abs/rel tolerance）
   - Error metrics 计算

#### Phase 2: Advanced Kernels & Validation

1. **Complex Kernels**
   - FftNumericalKernel（基于 FFTW）
   - EigenNumericalKernel（基于 Eigen/LAPACK）

2. **Scoreboard & Checker**
   - Transaction-level checking
   - 批量验证
   - 错误报告和诊断

3. **Numerical DSE Mode**
   - 同时执行 timing + numerical
   - 功能正确性作为 DSE 约束

#### Phase 3: UVM Integration

1. **TLM2.0 Bridge**
   - gem5 GenericAccel 扩展 TLM2.0 sockets
   - Transaction routing

2. **DPI-C Interface**
   - SystemVerilog 绑定
   - UVM agent 集成

3. **Reference Model Packaging**
   - 作为独立 UVM component
   - Configuration API
   - 与 scoreboard 集成

### 16.7 与现有架构的集成点

#### 16.7.1 OpModelRegistry 扩展

```cpp
class OpModelRegistry {
public:
    OpModelRegistry();
    
    // Existing: timing models
    void register_model(std::unique_ptr<OpModel> model);
    const OpModel* find_model(const std::string& op_type) const;
    
    // NEW: numerical kernels
    void register_numerical_kernel(std::unique_ptr<NumericalOpKernel> kernel);
    const NumericalOpKernel* find_numerical_kernel(const std::string& op_type) const;
    
    // NEW: golden model
    void set_golden_model(std::unique_ptr<GoldenModel> golden);
    GoldenModel* get_golden_model() const;
    
private:
    std::vector<std::unique_ptr<OpModel>> models_;
    std::vector<std::unique_ptr<NumericalOpKernel>> numerical_kernels_;
    std::unique_ptr<GoldenModel> golden_model_;
};
```

#### 16.7.2 GraphExecutor 扩展

```cpp
class GraphExecutor {
public:
    GraphExecutor(const SimulationRequest& req, const OpModelRegistry& registry);
    
    // Existing: timing-only execution
    SimulationResult execute();
    
    // NEW: numerical execution
    NumericalResult execute_numerical();
    
    // NEW: validate against golden
    ValidationResult validate_numerical(const NumericalResult& result);
    
private:
    // NEW: tensor store
    std::unique_ptr<TensorStore> tensor_store_;
    
    // NEW: execute single node numerically
    void execute_node_numerical(const ComputeNode& node);
    
    // NEW: initialize input tensors
    void initialize_tensors();
};
```

#### 16.7.3 Python Bridge 扩展

```python
# generic_systemc_bridge.py 扩展
class GenericSystemCBackend:
    def evaluate(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        workload_package: Optional[WorkloadPackage] = None,
        numerical_config: Optional[NumericalConfig] = None,  # NEW
    ) -> Dict[str, Any]:
        """
        Evaluate design point.
        
        Args:
            numerical_config: Optional numerical execution configuration.
                If provided, enables numerical execution and validation.
        """
        
    def validate_numerical(
        self,
        result: Dict[str, Any],
        golden_result: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate numerical correctness of simulation result."""
```

### 16.8 证据与 Claim 边界

#### 16.8.1 新的 Claim 类型

| Claim 类型 | 证据要求 | 可信度 |
| --- | --- | --- |
| `timing_estimate` | L3 simulation result | 中 |
| `numerical_correctness` | Numerical validation report + golden model execution | 高 |
| `uvm_reference` | TLM2.0 transaction log + scoreboard results | 高 |
| `rtl_equivalence` | DPI-C comparison log + UVM test report | 最高 |

#### 16.8.2 证据文件清单

新增证据文件：

- `numerical_validation.json`：数值验证结果
- `golden_model_execution.json`：Golden model 执行记录
- `tensor_comparison.csv`：Tensor 对比详细结果
- `scoreboard_report.json`：Scoreboard 检查报告
- `tlm_transaction_log.json`：TLM2.0 事务日志（UVM 模式）
- `dpi_comparison_log.json`：DPI-C 对比日志（UVM 模式）

### 16.9 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 数值执行性能低 | DSE 探索速度下降 | 提供 `timing_only` 模式；numerical 只在最终候选上运行 |
| 内存占用大 | 大 tensor 导致 OOM | 支持 tensor 分块；lazy allocation |
| 依赖外部库 | 构建复杂度增加 | BLAS/FFTW/Eigen 作为 optional 依赖；fallback 到 naive 实现 |
| UVM 集成复杂 | 需要 SystemVerilog 环境 | 分阶段实现；先 TLM2.0，再 DPI-C |
| 精度问题 | FP16/INT8 与 FP64 差异大 | 可配置 tolerance；支持 per-tensor tolerance |

### 16.10 与现有代码的关系

```text
generic_sim_backend/
├── include/
│   ├── simulation_types.hpp          # 扩展: Tensor, TensorStore
│   ├── op_model_registry.hpp         # 扩展: NumericalOpKernel
│   ├── graph_executor.hpp            # 扩展: execute_numerical()
│   ├── golden_model.hpp              # 新增
│   ├── scoreboard.hpp                # 新增
│   └── tlm_bridge.hpp                # 新增 (Phase 3)
├── src/
│   ├── graph_executor.cpp            # 扩展: numerical execution path
│   ├── op_model_registry.cpp         # 扩展: register numerical kernels
│   ├── numerical_kernels/            # 新增目录
│   │   ├── gemm_kernel.cpp
│   │   ├── fft_kernel.cpp
│   │   ├── eigen_kernel.cpp
│   │   └── elementwise_kernel.cpp
│   ├── golden_model.cpp              # 新增
│   ├── scoreboard.cpp                # 新增
│   └── tlm_bridge.cpp                # 新增 (Phase 3)
└── schemas/
    ├── simulation_request_v2.json    # 新增
    └── simulation_result_v2.json     # 新增
```
