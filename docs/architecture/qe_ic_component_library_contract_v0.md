# QE IC component library contract v0

## 1. 目标

这份合同定义 graph-DSE v0 所使用的 **组件库抽象层**。

当前目标不是把所有模块都变成 RTL-ready IP catalog，而是先形成一个：
- 可复用
- 可组合
- 可被 graph schema 引用
- 可被 evaluator 估计
- 可映射回 brownfield simulator

的系统级组件库。

---

## 2. 组件类别

### 2.1 Compute
- `CIMArray`
- `FFTUnit`
- `DiagUnit`
- `ReductionUnit`
- `MixingUnit`

### 2.2 Memory / Residency
- `ResidentBuffer`
- `NearMemoryBuffer`
- `HBMInterface`
- `HostMemoryWindow`

### 2.3 Transfer / Interconnect
- `DMAChannel`
- `InterconnectLink`
- `ControlLink`

### 2.4 Control / Orchestration
- `SystemContainer`
- `HostController`
- `EpisodeController`
- `Scheduler`
- `FallbackManager`

### 2.5 Flow / Glue
- `GraphExecutor`
- `DataTransform`
- `FormatAdapter`
- `GraphBarrier`

---

## 3. 每个组件最小 metadata

每个组件定义至少需要包含：
- `component_id`
- `component_type`
- `role`
- `default_placement` (`host`, `fpga`, `shared`)
- `supported_ops`
- `latency_model_ref`
- `power_model_ref`
- `observability_keys`
- `capacity_or_limit`
- `fallback_behavior`
- `brownfield_anchor`

---

## 4. 与 brownfield 的映射原则

当前 brownfield 模块要优先被映射为组件库 seed：
- `DFTHybridSystem` -> `SystemContainer`
- `HostSCF` -> `HostController`
- `FPGAOrchestrator` -> `FallbackManager` / device orchestration anchor
- `Interconnect` -> `InterconnectLink` / `DMAChannel` / `ControlLink`
- `ChipTop` -> graph execution container / top-level flow owner
- `ClusterGraphExecutor` -> `GraphExecutor`
- `ClusterAOperatorSweep` -> `CIMArray` + operator sweep compute anchor
- `ClusterBReducedBuild` -> `ReductionUnit`
- `ClusterCHardwareDiag` / `VectorDiagCompanion` -> `DiagUnit`
- `CommandScheduler` -> `Scheduler`
- `FFTCompanion` -> `FFTUnit`
- `NearSRAM* / NearMemoryDomain / ResidentContextController` -> memory/residency family
- `ContextLoader` / `DigitSerialInputBoundary` / `ConjugateSignSelector` -> `DataTransform` / `FormatAdapter`
- `CIMEligibleOperatorSubchain` -> `GraphExecutor`
- `CIMArrayCore` / `Residue3MCore` -> leaf `CIMArray`
- `CoefficientAccumulator` / `RowMergeTree` / `ReductionClosureEngine` -> reduction / transform leaf family

当前 active build 中的 on-chip leaf 链也可以作为 seed component 纳入 catalog，
即便它们暂时还没有全部进入 graph seed template 的默认拓扑。

---

## 5. v0 约束

当前 v0 组件库：
- 允许系统级组合；
- 允许 placement / capability / bottleneck reasoning；
- 不要求每个组件都已有精确数值模型；
- 但每个组件必须有明确的 `brownfield_anchor` 或 `future_placeholder` 标记。

---

## 6. 非目标

当前 v0 不要求：
- IP 级接口冻结
- RTL 级端口/时序规范
- 板级资源闭合
- 组件之间的 cycle-accurate protocol 定稿
