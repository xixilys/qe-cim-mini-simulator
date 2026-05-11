# DFT 加速项目：可配置 DSE + Simulator 系统总结

## 项目现状 (2026-04-20)

你的项目**已经拥有完整的可配置 DSE + Simulator 框架**，可以立即开始使用。

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│ 配置层 (JSON)                                                 │
│ ├─ Component Catalog (16 个 system-level components)         │
│ └─ Graph Spec (定义拓扑和连接)                                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ DSE 引擎 (Python)                                             │
│ ├─ 5 维参数空间: family × diag_policy × offload_scope ×     │
│ │                 resident_policy × partition_strategy        │
│ ├─ 10+ workloads: Si, graphene, Au slab, SiC32, VASP, CP2K  │
│ └─ 输出: JSON + CSV + graph evidence                         │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Simulator (SystemC)                                           │
│ ├─ ozaki_subspace_model/ (独立验证器)                        │
│ └─ qe_band_solver_model/ (完整系统模型)                       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 分析和决策                                                     │
│ ├─ Phase closure pipeline                                    │
│ ├─ Adjudicator (决策权威)                                     │
│ └─ Baseline 对比 (CPU/GPU/FPGA)                              │
└──────────────────────────────────────────────────────────────┘
```

## 核心能力

### ✅ 已实现

| 能力 | 工具 | 状态 |
|------|------|------|
| Component 定义 | `qe_ic_component_catalog_system_level_v1.json` | ✅ 16 个 components |
| Graph 配置 | `qe_ic_graph_seed_system_level_v1.json` | ✅ F2 balanced 模板 |
| DSE 扫描 | `run_systemc_architecture_family_dse_sweep.py` | ✅ 5 维参数空间 |
| Graph 验证 | `check_qe_ic_component_graph_v1.py` | ✅ 带 regression tests |
| Graph 投影 | `qe_ic_graph_projection_utils.py` | ✅ Graph → design_point |
| Simulator | `model/qe_band_solver_model/` | ✅ SystemC 可执行 |
| 结果分析 | `run_qe_phase1_closure_pipeline.py` | ✅ 完整 closure 报告 |
| Workloads | 10+ cases | ✅ QE/VASP/CP2K |

### 🎯 支持的配置维度

```python
families = ["F1", "F2", "F3"]
diag_policies = ["cpu_only", "device_first_fallback", "aggressive_device"]
offload_scopes = ["single_hotpath", "balanced", "device_heavy"]
resident_policies = ["fit_first", "spill_tolerant"]
partition_strategies = [
    "single_hotpath_partition",
    "operator_build_fused__diag__refresh",
    "operator__build__diag__refresh"
]
```

## 快速开始

### 1. 运行预置测试

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
./quick_start_dse.sh
```

### 2. 自定义 DSE 扫描

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_uspp graphene_pbe_uspp \
  --families F1 F2 F3 \
  --max-design-points 50 \
  --output-dir results/my_sweep
```

### 3. 运行 Simulator

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j

python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_nc \
  --families F2 \
  --execute-model \
  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \
  --output-dir results/simulator_run
```

## 典型工作流程

### 迭代 1: 快速探索 (Stub 模式)

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si4_pbe_uspp_small \
  --families F1 F2 F3 \
  --max-design-points 100 \
  --output-dir results/iter1_fast
```

**输出**: 100 个 design points 的性能估计，筛选出 top candidates。

### 迭代 2: 精确验证 (Simulator 模式)

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F2 \
  --execute-model \
  --model-bin model/qe_band_solver_model/build/qe_band_solver_model \
  --gold-baseline-root results/gold_baselines \
  --output-dir results/iter2_accurate
```

**输出**: 真实的 time/energy/correctness 数据。

### 迭代 3: 泛化测试

```bash
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --workloads graphene_pbe_paw au_slab_subspace sic32_subspace \
  --families F2 \
  --execute-model \
  --output-dir results/iter3_generalization
```

**输出**: 不同 workloads 上的表现。

### 迭代 4: 生成决策报告

```bash
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --baseline-root results/gold_baselines \
  --board-root results/iter2_accurate \
  --output-dir results/closure

cat results/closure/qe_phase1_evidence_closure_report.md
```

**输出**: Phase closure 报告，包含推荐的架构配置。

## 自定义和扩展

### 添加新 Component

编辑 `docs/architecture/qe_ic_component_catalog_system_level_v1.json`：

```json
{
  "component_id": "my_new_component",
  "component_type": "custom_type",
  "role": "specialized_function",
  "supported_ops": ["op1", "op2"],
  "latency_model_ref": "my_latency_model",
  "power_model_ref": "my_power_model",
  "dse_surface": {
    "exposed_knobs": ["param1", "param2"],
    "ranking_metrics": ["metric1", "metric2"]
  }
}
```

### 创建自定义 Graph

```json
{
  "graph_schema_version": "qe_ic_graph_schema_system_level_v1",
  "graph_id": "my_custom_topology",
  "join_keys": {
    "family": "F2",
    "diag_policy": "device_first_fallback",
    "offload_scope": "device_heavy"
  },
  "modules": [
    {
      "module_id": "custom0",
      "component_ref": "my_new_component",
      "placement": "device"
    }
  ]
}
```

### 验证配置

```bash
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-seed my_custom_graph.json \
  --print-projection
```

## 关键文件索引

### 配置文件
- `docs/architecture/qe_ic_component_catalog_system_level_v1.json` - Component 库
- `docs/architecture/qe_ic_graph_seed_system_level_v1.json` - Graph 模板

### 工具脚本
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` - DSE 主引擎
- `tools/benchmarks/check_qe_ic_component_graph_v1.py` - Graph 验证器
- `tools/benchmarks/qe_ic_graph_projection_utils.py` - 投影工具
- `tools/benchmarks/run_qe_phase1_closure_pipeline.py` - Closure 分析

### 文档
- `docs/architecture/qe_ic_component_graph_input_template_v1.md` - Component/Graph 规范
- `docs/benchmarks/qe_next_stage_dse_strategy_v0.md` - DSE 策略
- `docs/architecture/system_design_master_spec_v0.md` - 系统设计主规范
- `docs/examples/custom_dse_workflow.md` - 自定义工作流示例

### 模型代码
- `model/ozaki_subspace_model/` - Ozaki/CRT 验证器
- `model/qe_band_solver_model/` - QE band-solver 系统模型

## 下一步建议

### 立即可做 (今天)
1. ✅ 运行 `./quick_start_dse.sh` 验证系统
2. ✅ 查看生成的 CSV/JSON 结果
3. ✅ 构建并运行 SystemC model

### 短期目标 (1-2 周)
1. 扩展到完整 workload 矩阵 (10+ cases)
2. 对比 F1/F2/F3 三个 family
3. 生成 phase closure 报告
4. 校准性能模型参数

### 中期目标 (1-2 月)
1. 自定义 component 和 graph
2. 集成 AI/heuristic DSE
3. 开始 RTL 实现
4. 完整的 CPU/GPU baseline 对比

### 长期目标 (3-6 月)
1. 完整的 FPGA 实现
2. 硅后验证
3. 论文撰写和发表

## 常见问题

### Q: 如何修改 DSE 参数空间？
A: 使用命令行参数指定：
```bash
--families F1 F2 F3
--diag-policies device_first_fallback cpu_only
--offload-scopes balanced device_heavy
```

### Q: 如何添加新的 workload？
A: 
1. 准备 QE 输入文件
2. 运行 QE 生成 gold baseline
3. 在 DSE 脚本中添加 workload 定义

### Q: Simulator 运行太慢怎么办？
A:
1. 使用 `--model-max-scf-iters` 限制迭代
2. 先用 stub 模式筛选
3. 使用 fast-layer proxy

### Q: 如何对比不同配置的性能？
A: 查看生成的 CSV 文件，或使用 pandas 分析 JSON：
```python
import json
import pandas as pd

with open('results/sweep.json') as f:
    data = json.load(f)
    
df = pd.DataFrame(data['results'])
print(df[['family', 'workload_id', 'time_to_convergence_s', 'speedup_to_convergence']])
```

## 总结

你的项目已经具备：
- ✅ 完整的可配置架构描述系统
- ✅ 自动化的 DSE 参数空间扫描
- ✅ 可执行的 SystemC simulator
- ✅ 完整的验证和分析工具链
- ✅ 10+ 真实 workloads

**可以立即开始迭代优化性能/功耗/延时！**

下一步只需要：
1. 运行 DSE 获得初步结果
2. 用 Simulator 验证关键 design points
3. 根据结果调整配置
4. 重复迭代直到满意

祝开发顺利！🚀
