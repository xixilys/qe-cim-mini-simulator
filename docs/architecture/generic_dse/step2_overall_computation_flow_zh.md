# Step2 整体计算流程说明（中文）

状态：说明文档
适用范围：`dse_v2` 当前 Step2 架构/映射/低保真筛选流程
核心入口：`dse_v2/mapping/step2_workflow.py`

## 0. 一句话总览

当前 Step2 做的是：

> 从 Step1 给出的通用 workload/graph 出发，选择一个候选架构，生成合法 mapping 候选，用启发式搜索选出一个候选 mapping，再分别用 L1 analytical evaluator 和 L2 Python formula estimator 做低保真筛选，最后决定这个候选是否可以进入 Step3/SystemC/gem5 等更高保真度验证队列。

重要边界：

- Step2 **不是最终性能验证**。
- L1/L2 当前只是 **candidate-generation / screening**。
- Step2 输出可以告诉你“这个候选值得不值得进入 Step3”，但不能告诉你“这个候选就是最终最好设计”。
- 当前 L1/L2 里很多数值是 heuristic，不能当作 validated model 结果。

---

## 1. 主要代码位置

| 功能 | 文件 / 函数 |
|---|---|
| Step2 总入口 | `dse_v2/mapping/step2_workflow.py::run_step2_architecture_mapping_workflow` |
| 从 Step1 目录加载 | `dse_v2/mapping/step2_workflow.py::run_step2_architecture_mapping_workflow_from_step1` |
| Mapping 合法性/搜索 | `dse_v2/mapping/search.py` |
| L1 analytical evaluator | `dse_v2/dse/analytical_evaluator.py::EnhancedAnalyticalEvaluator` |
| L2 wrapper | `dse_v2/dse/tlm_evaluator.py::TLMEvaluator` |
| L2 formula model | `dse_v2/models/mid/python_tlm.py::PythonTLM` |
| Promotion gate | `dse_v2/promotion/promotion_engine.py::PromotionEngine` |
| Promotion thresholds | `dse_v2/promotion/thresholds.py` |
| Generic domain policy seam | `dse_v2/mapping/domain_policy.py` |
| DFT reference policy | `dse_v2/reference_workloads/dft_step2_policy.py` |

---

## 2. Step1 丢给 Step2 什么

Step2 不直接解析 QE 输入，也不直接做 workload importer。Step2 消费的是 Step1 已经生成的通用 artifact。

从磁盘边界看，入口是：

```python
run_step2_architecture_mapping_workflow_from_step1(step1_dir, **kwargs)
```

它会调用：

```python
handoff = load_step1_handoff(step1_dir)
```

Step1 handoff 通常包含：

1. `workload_package`
   - 通用 workload 包。
   - 包含 workload id、family、claim boundary、graph、metadata 等。

2. `workload_graph`
   - Step1 生成的 source `ComputeGraph`。
   - 节点代表计算操作，例如 `gemm`、`fft`、`reduction`、`eigen` 等。
   - 边代表数据依赖和 tensor movement。

3. `executable_graph`
   - 降低后的、Step2 可执行/可映射图。
   - 如果 Step1 已经给了，Step2 直接使用。
   - 如果没有，Step2 可能调用 `lower_compute_graph` 重新生成。

4. `graph_lowering_report`
   - 描述 lowering 是否成功。
   - 包含 unsupported constructs、approximations、required coverage、full workload eligibility 等。

5. `workload_characterization`
   - workload 级别的摘要。
   - 如果是 DFT/QE frontdoor，可包含 `domain_phase_summary` 等领域摘要，但 generic core 不强制依赖。

6. `step1_handoff_summary`
   - Step1 artifact 验证、加载状态、输入来源等摘要。

所以 Step2 的基本输入可以抽象为：

```text
WorkloadPackage
  └── ComputeGraph / executable_graph
        ├── nodes: op_type, estimated_flops, estimated_memory_bytes, tensor specs
        └── edges: source_node, target_node, tensor_spec

GraphLoweringReport
WorkloadCharacterization
Optional Domain Metadata / DFT Phase Summary
```

---

## 3. Step2 总流程

主函数：

```python
run_step2_architecture_mapping_workflow(...)
```

整体流程如下：

```text
Step1 artifacts
    ↓
validate WorkloadPackage
    ↓
load/recompute executable graph
    ↓
optional domain policy hints, e.g. DFT phase-aware hints
    ↓
select architecture from catalog
    ↓
convert ArchitectureInstance → SystemArchitecture
    ↓
build architecture artifact
    ↓
run mapping search
    ↓
build DesignPoint
    ↓
run L1 analytical screening
    ↓
run L2 formula/TLM-like screening
    ↓
run promotion gates
    ↓
build architecture_candidate_set + step3_simulation_queue
    ↓
write Step2 artifacts
```

---

## 4. 架构如何进入计算

Step2 从 architecture catalog 中取一个 `ArchitectureInstance`，然后调用：

```python
architecture_instance_to_system_architecture(instance)
```

它会生成一个 `SystemArchitecture`，里面有：

- host CPU 信息；
- accelerator 列表；
- accelerator 类型：`fpga`、`gpu`、`cim`、`asic`、`custom`；
- 每个 accelerator 的：
  - peak FLOPs；
  - supported ops；
  - op efficiency；
  - local memory capacity；
  - bandwidth；
  - host link / peer link；
  - static power；
- interconnect；
- max power / area constraint。

当前部分 peak FLOPs 和 op efficiency 是代码内置表。例如：

```python
_component_peak_flops(component_type_id, precision)
_op_efficiency(component_type_id, op_type)
```

这些是用于候选生成的默认参数，不是板卡实测数据。

---

## 5. Mapping search 如何计算

实现文件：

```text
dse_v2/mapping/search.py
```

### 5.1 target 列表

Step2 首先定义可映射目标：

```python
target_ids = ["host"] + accelerator_ids
```

也就是说每个 graph node 都可以尝试映射到：

- host；
- 某个 FPGA accelerator；
- 某个 GPU accelerator；
- 某个 CIM accelerator；
- 其他 catalog 中定义的 accelerator。

### 5.2 合法性矩阵

函数：

```python
build_legality_matrix(graph, architecture)
```

对每个 node 和每个 target 检查：

1. target 是否支持该 `op_type`；
2. target 是否支持该 precision；
3. node working set 是否超过 local memory；
4. 是否有 host link 或 interconnect route；
5. host fallback 是否可用。

输出 artifact：

```text
mapping_legality_matrix.json
```

它会记录：

```json
{
  "node_id": "...",
  "op_type": "gemm",
  "legal_targets": ["host", "accel-0"],
  "cells": [
    {"target": "host", "legal": true, "reasons": [...]},
    {"target": "accel-0", "legal": true, "reasons": [...]}
  ]
}
```

### 5.3 seed mappings

函数：

```python
generate_seed_mappings(...)
```

当前会生成几类 seed：

1. `host_baseline`
   - 所有 node 放 host。

2. `all_<accel_type>_<accel_id>`
   - 尽量把所有合法 node 放到某个 accelerator。

3. `<workload_family>_workflow_balanced`
   - 根据 workload family 的偏好映射。

4. `streaming_memory_locality`
   - 对 `reduction`、`fft`、`elementwise` 等更偏向 FPGA/CIM/GPU。

5. policy hints seeds
   - 如果启用 DFT policy，可能生成：
     - `phase_aware_balanced`
     - `dominant_phase_offload`
     - `host_visible_review_safe`

输出 artifact：

```text
mapping_seed_set.json
```

### 5.4 mapping screening 公式

函数：

```python
screen_mapping(seed, graph, architecture, candidate_index)
```

对每个 node，当前估算：

```python
throughput, power = _target_cost(target, node.op_type, architecture)
compute_ms = node.estimated_flops / throughput * 1000.0
memory_ms = node.estimated_memory_bytes * 8.0 / 1.0e11 * 1000.0
node_ms = max(compute_ms, memory_ms)
```

解释：

- `throughput` 来自 target 的 peak FLOPs × op efficiency。
- `compute_ms` 是计算时间。
- `memory_ms` 是一个固定带宽假设下的内存访问时间。
- `node_ms = max(compute_ms, memory_ms)`，相当于一个简化 roofline-like bound。

然后累加所有 node：

```python
predicted_latency_ms += node_ms
predicted_energy_j += power * node_ms / 1000.0
```

跨 target 的 edge 会产生 data movement：

```python
movement = _data_movement_mb(graph, mapping)
predicted_latency_ms += movement * 0.002
```

最后得到：

```python
confidence = 0.72 if legal else 0.35
promotion_priority = 1.0 / predicted_latency_ms * confidence
```

这里要注意：

- 这是启发式 screening，不是 calibrated performance model。
- `confidence=0.72` / `0.35` 是经验值。
- `movement * 0.002` 也是经验 penalty。

### 5.5 选出候选

函数：

```python
run_mapping_search(...)
```

逻辑是：

1. 生成 legality matrix。
2. 生成 seed mappings。
3. 对每个 seed 调 `screen_mapping`。
4. 过滤非法 mapping。
5. 按以下 key 排序：

```python
(-promotion_priority, predicted_latency_ms, candidate_id)
```

6. 取 beam width 内的候选。
7. 选出 selected mapping。
8. 输出：

```text
mapping_candidate_records.json
mapping_selected_record.json
mapping_feedback_state.json
convergence_status.json
```

如果没有 Step3 simulation sample，则 convergence 仍是：

```text
awaiting_simulation
```

也就是说 Step2 不声称收敛。

---

## 6. DesignPoint 如何构造

Step2 选出 mapping 后，会构造：

```python
DesignPoint(
    design_point_id=run_id,
    system_architecture=system_arch,
    task_mapping=selected_mapping,
    scheduling_policy=scheduling_policy,
    config=design_config,
)
```

`design_config` 由：

```python
_design_point_config(...)
```

生成。

里面包含：

- workload id；
- graph id；
- architecture id；
- selected candidate id；
- data placement；
- scheduling policy；
- precision policy；
- fallback policy；
- low fidelity policy；
- simulation config；
- replay metadata；
- optional domain policy metadata。

输出 artifact：

```text
design_point.json
```

---

## 7. L1 整体计算

实现：

```text
dse_v2/dse/analytical_evaluator.py
```

入口：

```python
EnhancedAnalyticalEvaluator().evaluate(design_point, compute_graph)
```

### 7.1 L1 输入

L1 输入是：

```text
DesignPoint
  ├── SystemArchitecture
  └── task_mapping

ComputeGraph / executable_graph
```

### 7.2 构建 bandwidth matrix

函数：

```python
_build_bandwidth_matrix(sys_arch)
```

它从 architecture 中读取：

- peer links；
- host links；
- CPU-to-CPU 默认带宽。

形成：

```python
bandwidths[(source_accel, target_accel)] = bandwidth_gbps
```

### 7.3 ComputeGraph → TaskGraph

L1 调用：

```python
map_compute_to_tasks(compute_graph, design_point.task_mapping, accel_bandwidths)
```

它把 graph node 转成 task，并根据 mapping 给每个 task placement。

### 7.4 Roofline 分析

函数：

```python
_roofline_analysis(task, sys_arch)
```

核心变量：

```python
bytes_accessed = task.required_memory_bytes
arithmetic_intensity = task.required_compute_flops / bytes_accessed
peak_compute = accel.compute.get_peak_flops("FP64") / 1e9
peak_memory_bw = accel.memory.levels[0].bandwidth_gbps
efficiency = op_efficiency or default 0.8
```

核心公式：

```python
compute_bound = peak_compute * efficiency
memory_bound = peak_memory_bw * arithmetic_intensity
actual = min(compute_bound, memory_bound)
```

如果：

```python
compute_bound <= memory_bound
```

则 bottleneck 是 compute，否则是 memory。

单 task latency：

```python
latency_ms = flops / (actual_gflops * 1e9) * 1000.0
```

这部分是当前 L1 最接近标准 Roofline 的地方。

### 7.5 L1 调度

函数：

```python
_schedule_tasks_parallel(task_graph, roofline_results, design_point)
```

它做：

1. 拓扑排序。
2. 记录每个 accelerator 什么时候空闲：

```python
accel_available_at[accel_id]
```

3. 记录每个 task 完成时间：

```python
task_completion[task_id]
```

4. 对每个 task：

```python
compute_latency_ms = roofline.latency_ms(task.required_compute_flops)
```

5. 对输入依赖的数据移动，计算最晚可用时间：

```python
movement_latency_ms = max(dep_completion + transfer_time)
```

6. task 最早开始时间：

```python
earliest_start = max(accel_available_at[accel_id], movement_latency_ms)
```

7. task 结束时间：

```python
end_time = earliest_start + compute_latency_ms
```

8. 记录 execution events 和 data transfers。

### 7.6 L1 汇总指标

函数：

```python
_calculate_metrics(timeline, design_point, compute_graph)
```

主要计算：

```python
total_flops = compute_graph.total_flops()
total_latency_ms = timeline.total_duration_ms
throughput_gops = total_flops / max(total_latency_ms, 1.0) / 1e6
```

power 当前是：

```python
total_power_w = sum(accel.power.static_power_w)
```

然后对每个 task start event 加一个 compute power heuristic。

energy：

```python
energy_j = total_power_w * total_latency_ms / 1000.0
```

compute efficiency：

```python
compute_efficiency = achieved_flops_per_second / peak_flops
```

memory efficiency 当前是固定值：

```python
memory_efficiency = 0.5
```

所以 L1 的可信度边界是：

- Roofline bound 有文献基础。
- 调度是自定义 list scheduling。
- power/energy 是 heuristic。
- memory_efficiency 当前是硬编码。

---

## 8. L1 normalization 和 promotion score

L1 evaluator 原始输出会被 Step2 包装成标准 artifact。

函数：

```python
_normalize_l1_result(...)
```

核心逻辑：

```python
screening_confidence = selected_record.screening.confidence or 0.60
compute_efficiency = result.compute_efficiency
memory_efficiency = result.memory_efficiency
```

confidence 公式：

```python
confidence = clamp(
    max(
        screening_confidence,
        0.55
        + 0.25 * min(memory_efficiency, 1.0)
        + 0.10 * min(compute_efficiency * 10.0, 1.0)
    ),
    0.0,
    0.92
)
```

promotion score：

```python
promotion_score = clamp(0.55 + 0.40 * confidence, 0.0, 1.0)
```

输出 artifact：

```text
l1_evaluation_result.json
l1_promotion_decision.json
```

注意：这里的 confidence / promotion_score 是 heuristic，不是实测置信度。

---

## 9. L2 整体计算

L2 由两层组成：

1. `TLMEvaluator`：wrapper，把 generic DSE 输入转成 PythonTLM 输入。
2. `PythonTLM`：真正公式模型。

### 9.1 L2 wrapper

文件：

```text
dse_v2/dse/tlm_evaluator.py
```

入口：

```python
TLMEvaluator().evaluate(design_point, compute_graph)
```

它做：

1. `_convert_design_point(design_point)`
2. `_extract_workload(compute_graph)`
3. `PythonTLM.run_episode(tlm_design_point, workload)`
4. `_convert_result(...)`

### 9.2 design point 转换

当前 wrapper 默认生成：

```python
architecture = {
    "family": "F1",
    "clock_mhz": 250,
    "parallel_units": 4,
    "gemm_tiles": 4,
    "eigen_tiles": 1,
    "local_mem_kb": 512,
    "max_power_w": 75,
    "pcie_bw_gbps": 64,
    "dram_bw_gbps": 128,
}
```

如果 accelerator 是：

- gpu → family `F3`，parallel units 16；
- fpga → family `F1`；
- cim → family `F4`。

这里是很粗的架构抽象。

### 9.3 workload 参数提取

函数：

```python
_extract_workload(compute_graph)
```

优先读 metadata：

```python
problem_size
feature_size
batch_size
iterations
```

如果没有，就用 graph 估算：

```python
total_flops = sum(node.estimated_flops)
total_bytes = sum(node.estimated_memory_bytes)
problem_size = int((total_flops / total_bytes) * 1024)
feature_size = int(node_count * 64)
batch_size = int(node_count)
```

这也是 heuristic。

---

## 10. PythonTLM 公式模型

文件：

```text
dse_v2/models/mid/python_tlm.py
```

入口：

```python
PythonTLM.run_episode(design_point, workload)
```

### 10.1 输入参数

从 design point / workload 里取：

```python
problem_size
feature_size
batch_size
iterations

gemm_tiles
eigen_tiles
local_mem_kb
family
max_power_w
pcie_bw_gbps
dram_bw_gbps
```

### 10.2 FLOPs 估算

dense compute：

```python
dense_compute_flops = 2.0 * problem_size * feature_size * batch_size * iterations
```

solver：

```python
solver_flops = feature_size * feature_size * batch_size * iterations
```

### 10.3 compute time

函数：

```python
_compute_time_ms(flops, tiles, base_gops_per_tile)
```

公式：

```python
efficiency = 0.72 + 0.03 * min(tiles, 8.0)
throughput_gops = tiles * base_gops_per_tile * efficiency * (clock_mhz / 250.0)
time_ms = flops / (throughput_gops * 1e9) * 1000.0
```

dense 用：

```python
base_gops_per_tile = 88.0
```

solver 用：

```python
base_gops_per_tile = 36.0
```

这些常数当前没有校准证明。

### 10.4 transaction time

函数：

```python
_transaction_time_ms(bytes_count, bandwidth_gbps, transaction_bytes, latency_us)
```

公式：

```python
transactions = ceil(bytes_count / transaction_bytes)
bandwidth_ms = bytes_count * 8 / (bandwidth_gbps * 1e9) * 1000
latency_ms = transactions * latency_us / 1000
return bandwidth_ms + latency_ms
```

这就是当前所谓 TLM 的核心：

```text
bandwidth time + per-transaction latency
```

但是它不是 SystemC/TLM-2.0 标准实现。

### 10.5 family timing scale

当前有：

```python
FAMILY_TIMING_SCALE = {
    'F1': 1.50,
    'F2': 1.25,
    'F3': 1.00,
    'F4': 1.00,
    'F5': 0.018,
    'F6': 1.00,
    'F7': 1.00,
}
```

然后：

```python
dense_compute_ms *= timing_scale
transfer_ms *= timing_scale
solver_compute_ms *= timing_scale
...
```

这里也是 heuristic，尤其 `F5 = 0.018` 需要特别审计/校准。

### 10.6 mapping penalty 和 dataflow speedup

mapping penalty：

```python
if phase target == cpu: +0.15
elif target == auto: +0.05
max penalty = 0.5
```

算在 latency 上：

```python
latency_ms *= (1.0 + mapping_penalty)
```

dataflow speedup：

```python
double_buffer: +0.08
overlap_dma_compute: +0.12
keep_resident: +0.05
max speedup = 0.25
```

算在 latency 上：

```python
latency_ms *= (1.0 - dataflow_speedup)
```

### 10.7 power / area / throughput

当前公式：

```python
power_w = 17.5 + 2.6 * gemm_tiles + 3.1 * eigen_tiles + 0.0018 * local_mem_kb + 0.02 * latency_ms
```

```python
area_mm2 = 18.0 + 2.2 * gemm_tiles + 3.0 * eigen_tiles + 0.0014 * local_mem_kb
```

```python
total_ops = dense_compute_flops + solver_flops
throughput_gops = total_ops / latency_ms / 1e6
```

这些是公式估计，不是综合/布局布线/实测结果。

### 10.8 confidence / accuracy / promotion score / MAPE

resource utilization：

```python
compute_percent = min(180, ...)
memory_percent = min(180, ...)
bandwidth_percent = min(180, ...)
```

resource margin：

```python
resource_margin = max(0, 1 - max(resource_utilization) / 100)
```

confidence：

```python
confidence = clamp(
    0.74
    + 0.16 * resource_margin
    + 0.05 * balance
    + 0.03 * min(1, local_mem_kb / 1024),
    0,
    0.97
)
```

accuracy proxy：

```python
accuracy_vs_reference = clamp(0.82 + 0.12 * confidence + 0.06 * resource_margin)
```

promotion score：

```python
promotion_score = clamp(
    0.48 * accuracy_vs_reference
    + 0.30 * confidence
    + 0.17 * resource_margin
    + 0.05
)
```

MAPE proxy：

```python
mape_percent = max(5.0, 22.0 * (1.0 - confidence))
```

注意：这里的 MAPE 不是和真实 reference 比较出来的 measured MAPE，只是 proxy。

---

## 11. L2 normalization

Step2 把 L2 原始结果包装成：

```python
_normalize_l2_result(...)
```

输出：

```text
l2_evaluation_result.json
l2_promotion_decision.json
```

其中包含：

- latency；
- throughput；
- power；
- energy；
- confidence；
- mape_percent；
- promotion_score；
- resource_utilization；
- provenance；
- `candidate_generation_only: true`；
- `trusted_final_claim: false`。

---

## 12. Promotion 计算

实现：

```text
dse_v2/promotion/promotion_engine.py
```

阈值：

```text
dse_v2/promotion/thresholds.py
```

### 12.1 L1 → L2

函数：

```python
_evaluate_l1_to_l2(result)
```

检查：

```python
status_passed = result.status == "passed"
resource_legal = resource utilization <= 100%
score_passed = promotion_score >= threshold[family].l1_to_l2
confidence_passed = confidence >= threshold[family].min_confidence_l1
pareto_passed = not dominated
budget_available = true
```

全部通过才 promote。

### 12.2 L2 → L3

函数：

```python
_evaluate_l2_to_l3(result)
```

检查：

```python
status_passed
score_passed
confidence_passed
mape_passed = mape <= 20%
pareto_passed
budget_available
```

注意：当前 `mape` 可能来自 proxy，所以这个 gate 不能解释成真实验证误差 gate。

### 12.3 默认阈值

例如 F1：

```python
l1_to_l2 = 0.70
l2_to_l3 = 0.80
min_confidence_l1 = 0.55
min_confidence_l2 = 0.75
```

不同 family 有不同阈值。

---

## 13. Final Step2 promotion decision

Step2 还有一个更上层的 mapping promotion decision：

```python
_promotion_decision(...)
```

它综合：

- selected mapping 是否 legal；
- architecture 是否 trusted final eligible；
- low fidelity screening 是否 passed；
- review flags 是否存在 hard block；
- backend/evidence mode；
- L4 proof 是否要求。

核心边界：

```text
promoted_for_simulation = true
```

只表示：

> 可以进入 Step3 simulation queue。

不是：

> 已经是最终可信设计。

输出 artifact：

```text
mapping_promotion_decision.json
```

---

## 14. DFT policy 如何影响计算

DFT policy 文件：

```text
dse_v2/reference_workloads/dft_step2_policy.py
```

它通过 generic seam 进入 Step2：

```text
dse_v2/mapping/domain_policy.py
```

### 14.1 输入来源

DFT policy 会读：

- `workload_package.domain_metadata["dft"]`
- `workload_characterization.domain_phase_summary`
- graph node attributes 里的 `adapter:dft`

### 14.2 phase group

它会把 DFT phase 粗分成：

- dense linear algebra；
- FFT/grid/density；
- diagonalization；
- mixing/reduction；
- extension or unknown；
- generic safe op。

### 14.3 mapping hints

根据 phase group 生成 target preference，例如：

- dense linear algebra → FPGA/GPU/host；
- FFT/grid/density → FPGA/GPU/host；
- diagonalization → GPU/FPGA/host；
- unknown extension → host-visible until reviewed。

这些 hints 会进入 `run_mapping_search`，影响 seed mapping。

### 14.4 review flags

DFT policy 会收集：

- `project_critical_conflict`
- `segmentation_uncertain`
- `insufficient_evidence`
- `important_input_parameter`

其中 hard flags 会阻塞 promotion。

重要边界：

- DFT policy 只加 candidate hints。
- Generic Step2 artifacts 不要求 DFT 字段。
- Generic consumer 可以忽略 DFT metadata。

---

## 15. Step2 输出什么

Step2 会写出一组 artifact。主要包括：

### 15.1 Workload / graph

```text
workload_package.json
workload_graph.json
graph_lowering_report.json
executable_graph.json
```

### 15.2 Architecture / design point

```text
architecture_catalog.json
architecture.json
design_point.json
```

### 15.3 Mapping

```text
mapping_legality_matrix.json
mapping_seed_set.json
mapping_candidate_records.json
mapping_selected_record.json
mapping.json
```

### 15.4 L1/L2

```text
l1_evaluation_result.json
l1_promotion_decision.json
l2_evaluation_result.json
l2_promotion_decision.json
low_fidelity_screening_summary.json
```

### 15.5 Promotion / Step3 queue

```text
mapping_promotion_decision.json
architecture_candidate_set.json
step3_simulation_queue.json
```

### 15.6 Feedback / convergence

```text
mapping_simulation_samples.json
mapping_feedback_state.json
convergence_status.json
```

如果没有 Step3 samples，convergence 会显示还没有可信收敛。

---

## 16. 当前计算可信度分层

| 层级 | 当前实现 | 可信度 |
|---|---|---|
| Mapping legality | op/precision/memory/route 检查 | 软件规则可信，但不是性能模型 |
| Mapping screening | FLOPs/bandwidth heuristic + beam | candidate-generation heuristic |
| L1 roofline | roofline-style bound | adapted model，但未完整校准 |
| L1 scheduling | 自定义拓扑调度 | custom heuristic |
| L1 power/energy | 静态功耗 + compute heuristic | unsupported/custom |
| L2 transaction formula | bandwidth + latency formula | conceptual TLM-like heuristic |
| L2 confidence/MAPE | 公式生成 proxy | unsupported/custom，不是 measured |
| Promotion threshold | hard-coded family thresholds | policy gate，不是验证结论 |
| Step3 queue | candidate handoff | 合法的下一阶段入口 |

---

## 17. 当前不能怎么解释

不能说：

- “L2 是 SystemC/TLM-2.0 模型。”
- “当前 MAPE 是真实误差。”
- “当前 confidence 是统计校准置信度。”
- “L1/L2 已经验证了 DFT-FPGA 性能。”
- “Step2 选出的就是最终最优架构。”

可以说：

- “L1 是 roofline-style analytical screening。”
- “L2 是 Python formula-based mid-fidelity estimator。”
- “Step2 用 L1/L2 做 candidate-generation gate。”
- “最终可信结论需要 Step3/SystemC 或 Step4/gem5+SystemC evidence。”

---

## 18. 后续如果要变成严谨科研级模型，需要补什么

### 18.1 L1

需要：

- 明确 roofline 方程单位；
- 每个 op 的 peak/efficiency 来源；
- memory bandwidth 来源；
- data movement route 模型；
- scheduler 假设；
- energy model 来源；
- golden tests；
- 与 Step3 reference 的误差校准。

### 18.2 L2

需要：

- transaction graph，而不是隐藏公式；
- compute/memory/DMA/sync transaction 类型；
- 每个 transaction 的 timing terms；
- overlap/contention 模型；
- calibration metadata；
- measured MAPE 只能来自 Step3+ reference comparison。

### 18.3 Promotion

需要：

- 区分 heuristic confidence 和 measured confidence；
- hard review flags 必须阻塞；
- soft review flags 必须触发人工 review；
- uncalibrated model 不能给 validated claim；
- Step2 永远只进入 Step3 queue，不直接最终排名。

---

## 19. 最小读代码顺序

如果你要从代码角度理解整个计算，建议按这个顺序读：

1. `dse_v2/mapping/step2_workflow.py::run_step2_architecture_mapping_workflow_from_step1`
2. `dse_v2/mapping/step2_workflow.py::run_step2_architecture_mapping_workflow`
3. `dse_v2/mapping/search.py::run_mapping_search`
4. `dse_v2/mapping/search.py::screen_mapping`
5. `dse_v2/dse/analytical_evaluator.py::EnhancedAnalyticalEvaluator.evaluate`
6. `dse_v2/dse/analytical_evaluator.py::_roofline_analysis`
7. `dse_v2/dse/analytical_evaluator.py::_schedule_tasks_parallel`
8. `dse_v2/dse/tlm_evaluator.py::TLMEvaluator.evaluate`
9. `dse_v2/models/mid/python_tlm.py::PythonTLM.run_episode`
10. `dse_v2/promotion/promotion_engine.py::PromotionEngine.evaluate`
11. `dse_v2/reference_workloads/dft_step2_policy.py::DftStep2ReferencePolicy`

---

## 20. 总结

当前 Step2 的整体计算可以理解成三层：

```text
第一层：结构合法性和候选生成
  - architecture catalog
  - legality matrix
  - mapping seeds
  - beam screening

第二层：低保真性能筛选
  - L1 roofline-style analytical evaluator
  - L2 Python formula estimator
  - confidence / MAPE / score proxy

第三层：promotion 和证据边界
  - L1 → L2 gate
  - L2 → L3 gate
  - review flags
  - Step3 simulation queue
  - no trusted final claim
```

它现在是一个可审计的 DSE prototype，但还不是最终科研级 validated performance model。要达到科研级，需要把 L1/L2 的每个公式、常数、confidence、MAPE、promotion score 都变成 component-level evidence，并用 Step3/Step4 reference 做校准和 holdout 验证。
