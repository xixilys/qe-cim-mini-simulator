# Custom DSE Workflow 示例

## 概述

本文档展示如何使用现有的可配置 DSE + Simulator 框架进行自定义实验。

## 工作流程图

```
配置文件 (JSON)
    ↓
DSE 参数扫描
    ↓
Simulator 执行
    ↓
结果分析
    ↓
迭代优化
```

## 快速开始

### 1. 运行预置的快速测试

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
./quick_start_dse.sh
```

这会：
- 验证 component catalog 和 graph
- 构建 SystemC model
- 运行一个小规模 DSE sweep (stub 模式)
- 输出结果到 `results/quick_start/`

### 2. 查看结果

```bash
cat results/quick_start/stub_sweep/sweep_stub.csv
python3 -m json.tool results/quick_start/stub_sweep/sweep_stub.json | less
```

## 自定义实验

### 场景 1: 修改 DSE 参数空间

探索不同的架构配置组合：

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_uspp graphene_pbe_uspp \
  --families F1 F2 F3 \
  --diag-policies device_first_fallback cpu_only aggressive_device \
  --offload-scopes single_hotpath balanced device_heavy \
  --resident-policies fit_first spill_tolerant \
  --partition-strategies operator__build__diag__refresh \
  --max-design-points 50 \
  --output-dir results/custom_sweep_001
```

### 场景 2: 运行真实 Simulator

对选定的 design points 运行 SystemC model：

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_nc \
  --families F2 \
  --execute-model \
  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \
  --model-max-scf-iters 20 \
  --output-dir results/simulator_run_001
```

### 场景 3: 对比 CPU/GPU Baseline

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_uspp \
  --families F2 \
  --execute-model \
  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \
  --gold-baseline-root results/gold_baselines \
  --cpu-shell-aggregate-path results/cpu_baseline/aggregate.json \
  --fail-on-gold-mismatch \
  --output-dir results/baseline_comparison
```

### 场景 4: 生成 Phase Closure 报告

```bash
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --baseline-root results/gold_baselines \
  --board-root results/simulator_run_001 \
  --output-dir results/closure_report

cat results/closure_report/qe_phase1_evidence_closure_report.md
```

## 自定义 Component 和 Graph

### 添加新的 Component

编辑 `docs/architecture/qe_ic_component_catalog_system_level_v1.json`：

```json
{
  "component_id": "my_custom_accelerator",
  "component_type": "custom_compute",
  "role": "specialized_kernel",
  "description": "Custom accelerator for specific operation",
  "default_placement": "device",
  "allowed_placements": ["device"],
  "supported_ops": ["custom_op_1", "custom_op_2"],
  "latency_model_ref": "custom_latency_model_v1",
  "power_model_ref": "custom_power_model_v1",
  "dse_surface": {
    "exposed_knobs": ["parallelism", "buffer_size"],
    "ranking_metrics": ["throughput", "energy_efficiency"]
  }
}
```

### 创建自定义 Graph

创建新的 graph seed JSON：

```json
{
  "graph_schema_version": "qe_ic_graph_schema_system_level_v1",
  "graph_id": "my_custom_topology_v1",
  "workload_class": {
    "workload_id": "si8_pbe_uspp",
    "software_family": "QE",
    "flow_family": "CBANDS_DIAG"
  },
  "join_keys": {
    "family": "F2",
    "diag_policy": "device_first_fallback",
    "offload_scope": "device_heavy",
    "resident_policy": "spill_tolerant",
    "partition_strategy": "operator__build__diag__refresh"
  },
  "modules": [
    {
      "module_id": "custom_accel0",
      "component_ref": "my_custom_accelerator",
      "placement": "device"
    }
  ]
}
```

### 验证自定义配置

```bash
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-seed my_custom_graph.json \
  --print-projection
```

## 迭代优化流程

### 第 1 轮：快速探索

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si4_pbe_uspp_small \
  --families F1 F2 F3 \
  --max-design-points 100 \
  --output-dir results/iteration_1
```

分析结果，选出 top 5 candidates。

### 第 2 轮：精确验证

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F2 \
  --execute-model \
  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \
  --output-dir results/iteration_2
```

验证 correctness 和真实性能。

### 第 3 轮：泛化测试

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads graphene_pbe_uspp au_slab_subspace sic32_subspace \
  --families F2 \
  --execute-model \
  --output-dir results/iteration_3
```

确认在不同 workloads 上的表现。

### 第 4 轮：参数微调

根据前三轮结果，调整 component 参数或 graph 拓扑，重新运行。

## 结果分析

### 查看性能指标

```bash
python3 << 'EOF'
import json
import pandas as pd

with open('results/iteration_2/sweep.json') as f:
    data = json.load(f)

results = []
for r in data.get('results', []):
    results.append({
        'family': r['family'],
        'workload': r['workload_id'],
        'time_s': r.get('time_to_convergence_s', 'N/A'),
        'energy_j': r.get('energy_to_convergence_j', 'N/A'),
        'speedup': r.get('speedup_to_convergence', 'N/A')
    })

df = pd.DataFrame(results)
print(df.to_string(index=False))
EOF
```

### 生成对比图表

```bash
python3 tools/benchmarks/visualize_dse_results.py \
  --input results/iteration_2/sweep.json \
  --output results/iteration_2/plots/
```

## 常见问题

### Q: 如何添加新的 workload？

A: 在 DSE sweep 脚本中，workload 列表是硬编码的。要添加新 workload：

1. 准备 QE 输入文件
2. 运行 QE 生成 gold baseline
3. 在 `run_systemc_architecture_family_dse_sweep.py` 中添加 workload 定义

### Q: 如何修改性能模型？

A: 编辑 `docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json`，调整：
- 延迟假设
- 功耗假设
- 带宽假设

### Q: Simulator 运行太慢怎么办？

A: 可以：
1. 使用 `--model-max-scf-iters` 限制迭代次数
2. 先用 stub 模式筛选，再对 shortlist 运行 simulator
3. 使用 fast-layer proxy 代替完整 simulator

## 参考文档

- Component/Graph 规范: `docs/architecture/qe_ic_component_graph_input_template_v1.md`
- DSE 策略: `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`
- Simulator 绑定: `docs/architecture/qe_ic_component_graph_brownfield_binding_v1.md`
- 系统设计主规范: `docs/architecture/system_design_master_spec_v0.md`
