# QE DSE Workflow Data Flow Specification v0

## 0. 定位

本文档定义 **Step 1 (Workload Characterization) → Step 2 (Architecture Exploration)** 之间的数据流接口。

**核心原则**：
- Step 1 输出**抽象的工作负载描述**，不是原始软件细节
- Step 2 只消费抽象描述，不依赖具体软件实现
- 数据流通过**标准化的 IR (Intermediate Representation)** 传递

**文献依据**：
- Flint (2026): compiler IR → Chakra graph → cost models
- DFModel: workload dataflow graph + system spec → inter/intra-chip optimization
- A-Graph: unified graph over application/software/architecture/circuit
- DeepStack: hardware model + workload + scheduling → metrics → hierarchical search

---

## 1. 数据流架构

### 1.1 总体流程

```
Step 1: Workload Characterization
    ├── Raw QE Traces (stdout, subspace_trace, hpsi_trace)
    ├── Trace Analysis (timing, call counts, dimensions)
    └── Workload IR (标准化抽象描述)
            ↓
            【数据流接口】
            ↓
Step 2: Architecture Exploration
    ├── Load Workload IR
    ├── Architecture Family Evaluation (25 variants)
    ├── Quantitative Scoring (metric vector)
    ├── Pareto Analysis
    └── Selected Architecture + Frozen Interface
            ↓
Step 3: Parameter Stack (在选定架构下调参)
```

### 1.2 关键洞察

**用户的观点完全正确**：
- Step 1 之后，具体软件（QE 的 Fortran 代码）不再重要
- 重要的是**工作负载的计算特征**（compute pattern, data movement, parallelism）
- Step 2+ 应该基于这些特征进行架构探索，而不是软件细节

---

## 2. Step 1 输出：Workload IR

### 2.1 Workload IR Schema

```json
{
  "schema_version": "v0",
  "workload_id": "qe_dft_si8_uspp",
  "source": {
    "software": "Quantum ESPRESSO",
    "version": "7.5",
    "case": "si8_pbe_uspp",
    "trace_date": "2026-05-07"
  },
  
  "compute_graph": {
    "nodes": [
      {
        "id": "h_psi",
        "type": "GEMM",
        "dominance": 0.68,
        "flops_per_call": 1.2e12,
        "precision": "FP64",
        "dimensions": {
          "M": "nbnd",
          "N": "npw",
          "K": "nkb"
        },
        "typical_sizes": {
          "M_range": [4, 64],
          "N_range": [2000, 3000],
          "K_range": [100, 300]
        }
      },
      {
        "id": "s_psi",
        "type": "GEMM",
        "dominance": 0.05,
        "flops_per_call": 8.0e11,
        "precision": "FP64"
      },
      {
        "id": "build_H_sub",
        "type": "REDUCTION",
        "dominance": 0.04,
        "flops_per_call": 2.0e11
      },
      {
        "id": "cdiaghg",
        "type": "EIGEN",
        "dominance": 0.23,
        "matrix_size": "nbnd × nbnd",
        "typical_size": [16, 64]
      },
      {
        "id": "refresh",
        "type": "VECTOR",
        "dominance": 0.05
      }
    ],
    
    "edges": [
      {"from": "h_psi", "to": "build_H_sub", "data_type": "wavefunction", "volume_mb": 50},
      {"from": "s_psi", "to": "build_H_sub", "data_type": "overlap", "volume_mb": 50},
      {"from": "build_H_sub", "to": "cdiaghg", "data_type": "reduced_matrix", "volume_mb": 0.1},
      {"from": "cdiaghg", "to": "refresh", "data_type": "eigenvectors", "volume_mb": 1}
    ]
  },
  
  "execution_profile": {
    "total_iterations": 15,
    "convergence_pattern": "oscillating_decay",
    "dominant_solver": "Davidson",
    "solver_fallbacks": ["CG", "LOBPCG"],
    "parallelism": {
      "kpoints": 8,
      "bands": "nbnd",
      "gvectors": "npw"
    }
  },
  
  "memory_profile": {
    "working_set_mb": 2000,
    "resident_set_mb": 500,
    "memory_access_pattern": "streaming_with_reuse",
    "reuse_distance": "short"
  },
  
  "data_movement": {
    "host_to_device_mb_per_iter": 100,
    "device_to_host_mb_per_iter": 10,
    "device_internal_mb_per_iter": 500,
    "dominant_traffic": "projector_beta_reuse"
  }
}
```

### 2.2 从 Step 1 报告提取的关键字段

基于代码库中的 `summary.json` 和 `qe_kernel_characterization_matrix`：

| Step 1 输出字段 | Workload IR 映射 | 用途 |
|----------------|-----------------|------|
| `dominant_solver` | `execution_profile.dominant_solver` | 算法选择 |
| `hpsi_call_count` | `compute_graph.nodes[].call_count` | 调用频率 |
| `max_subspace_n` | `compute_graph.nodes[].typical_sizes` | 矩阵维度 |
| `max_subspace_m` | `compute_graph.nodes[].typical_sizes` | 块大小 |
| `generalized_ratio` | `execution_profile.generalized_path_ratio` | 路径选择 |
| `top_level_shares` | `compute_graph.nodes[].dominance` | 热点分布 |
| `npw_samples` | `compute_graph.nodes[].dimensions.N` | 工作负载大小 |
| `nkb_values` | `compute_graph.nodes[].dimensions.K` | 投影器数量 |
| `functional` | `source.functional` | 精度要求 |
| `pseudo_type` | `source.pseudo_type` | 计算类型 |

---

## 3. 数据流接口定义

### 3.1 接口契约

```python
class WorkloadIR:
    """Step 1 输出，Step 2 输入"""
    workload_id: str
    compute_graph: ComputeGraph      # 计算图（节点=kernel，边=data flow）
    execution_profile: ExecutionProfile  # 执行特征
    memory_profile: MemoryProfile    # 内存特征
    data_movement: DataMovement      # 数据移动特征

class ArchitectureDescriptor:
    """架构描述（Step 2 内部使用）"""
    family_id: str
    variant_id: str
    compute_units: List[ComputeUnit]
    memory_hierarchy: MemoryHierarchy
    interconnect: Interconnect
    control_model: ControlModel

class EvaluationResult:
    """评估结果（Step 2 输出）"""
    variant_id: str
    metric_vector: MetricVector      # 多维指标向量
    weighted_score: float            # 加权总分
    is_pareto: bool                  # Pareto 最优
    rationale: str                   # 选择理由
```

### 3.2 数据流图

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Workload Characterization                            │
│                                                              │
│  Raw Traces → Trace Analysis → Workload IR                  │
│                                   ↓                          │
└──────────────────────────────────┼──────────────────────────┘
                                   │
                    【接口: WorkloadIR Schema】
                                   │
┌──────────────────────────────────┼──────────────────────────┐
│ Step 2: Architecture Exploration │                          │
│                                  ↓                          │
│  Load Workload IR → Evaluate Architectures                  │
│                       ↓                                     │
│  ┌──────────────────────────────────────────────┐          │
│  │ Quantitative Evaluation Engine                │          │
│  │                                               │          │
│  │  Input: WorkloadIR + ArchitectureDescriptor   │          │
│  │  Process:                                     │          │
│  │    1. Roofline Analysis                       │          │
│  │    2. Utilization Estimation                  │          │
│  │    3. Energy Modeling                         │          │
│  │    4. Complexity Scoring                      │          │
│  │  Output: MetricVector                         │          │
│  └──────────────────────────────────────────────┘          │
│                       ↓                                     │
│  Pareto Analysis → Architecture Selection                   │
│                       ↓                                     │
│  Frozen Interface + Selected Architecture                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Step 2 量化评估方法论

### 4.1 评估框架

基于文献最佳实践（DeepStack, A-Graph, SIS）：

**核心原则**：
- 使用**指标向量**（metric vector），不是单一分数
- 支持**Pareto 分析**和**加权评分**两种模式
- 包含**不确定性量化**

### 4.2 指标向量定义

```json
{
  "metric_vector": {
    "performance": {
      "speedup": {"value": 10.5, "unit": "x", "baseline": "CPU"},
      "throughput": {"value": 512, "unit": "GFLOPS"},
      "latency": {"value": 15.2, "unit": "ms"}
    },
    "efficiency": {
      "energy_per_op": {"value": 12.5, "unit": "pJ/op"},
      "power": {"value": 55, "unit": "W"},
      "area_efficiency": {"value": 8.5, "unit": "GFLOPS/mm²"},
      "edp": {"value": 0.85, "unit": "J·s"}
    },
    "utilization": {
      "compute_utilization": {"value": 0.75, "unit": "ratio"},
      "memory_bandwidth_utilization": {"value": 0.60, "unit": "ratio"},
      "load_balance": {"value": 0.80, "unit": "ratio"}
    },
    "flexibility": {
      "workload_coverage": {"value": 85, "unit": "score_0_100"},
      "reconfiguration_overhead": {"value": 100, "unit": "cycles"},
      "algorithm_support": {"value": ["Davidson", "CG", "LOBPCG"]}
    },
    "implementation": {
      "area": {"value": 90, "unit": "mm²"},
      "design_effort": {"value": 4.5, "unit": "person_months"},
      "verification_complexity": {"value": 65, "unit": "score_0_100"},
      "time_to_market": {"value": 6, "unit": "months"}
    }
  }
}
```

### 4.3 评估方法

#### 方法 1: Pareto 前沿分析

```python
def pareto_analysis(results: List[EvaluationResult]) -> List[EvaluationResult]:
    """
    找出 Pareto 最优架构
    
    定义：架构 A Pareto 优于 B，当且仅当：
    - A 在所有指标上 ≥ B
    - A 在至少一个指标上 > B
    """
    pareto = []
    for result in results:
        if not any(dominates(other, result) for other in results if other != result):
            pareto.append(result)
    return pareto
```

#### 方法 2: 加权评分（SIS 方法）

```python
def weighted_score(metric_vector: MetricVector, weights: Dict[str, float]) -> float:
    """
    基于 SIS (Sustainability Impact Score) 的加权评分
    
    Score = Σ(w_i × normalized_metric_i)
    
    其中 normalized_metric = (metric - min) / (max - min)
    """
    score = 0.0
    for category, metrics in metric_vector.items():
        weight = weights.get(category, 0.2)
        category_score = sum(metrics.values()) / len(metrics)
        score += weight * category_score
    return score
```

#### 方法 3: 多保真度评估

| 保真度 | 方法 | 时间 | 精度 | 用途 |
|--------|------|------|------|------|
| L0 | 分析模型 (Roofline) | 分钟 | ±50% | 初筛 |
| L1 | Python TLM | 小时 | ±30% | 排名 |
| L2 | SystemC TLM | 天 | ±15% | 详细对比 |
| L3 | 周期精确仿真 | 周 | ±5% | 最终验证 |
| L4 | RTL/硅片 | 月 | 实测 | 基准 |

### 4.4 不确定性量化

```python
def uncertainty_quantification(result: EvaluationResult) -> UncertaintyBounds:
    """
    评估结果的不确定性
    
    使用 MAPE (Mean Absolute Percentage Error):
    MAPE = (1/n) × Σ|y_i - ŷ_i| / y_i × 100%
    
    其中 y_i 是实测值，ŷ_i 是模型预测值
    """
    return {
        "confidence_interval": [lower, upper],
        "mape": 15.0,  # 例如 L2 保真度的典型 MAPE
        "sensitivity": {
            "parameter_x": 0.3,  # 参数 x 变化 1% 导致结果变化 0.3%
            "parameter_y": 0.1
        }
    }
```

---

## 5. Step 1 → Step 2 接口实现

### 5.1 代码实现

```python
# workload_ir.py
from dataclasses import dataclass
from typing import List, Dict, Tuple
import json

@dataclass
class ComputeNode:
    id: str
    type: str  # GEMM, EIGEN, VECTOR, REDUCTION
    dominance: float  # 0-1, workload share
    flops_per_call: float
    precision: str
    dimensions: Dict[str, str]
    typical_sizes: Dict[str, Tuple[int, int]]

@dataclass
class ComputeGraph:
    nodes: List[ComputeNode]
    edges: List[Dict]  # data flow between nodes

@dataclass
class WorkloadIR:
    workload_id: str
    compute_graph: ComputeGraph
    execution_profile: Dict
    memory_profile: Dict
    data_movement: Dict
    
    @classmethod
    def from_step1_json(cls, step1_json_path: str) -> 'WorkloadIR':
        """从 Step 1 的 summary.json 加载"""
        with open(step1_json_path) as f:
            data = json.load(f)
        
        # 提取 compute graph
        nodes = []
        for kernel_id, kernel_data in data['kernels'].items():
            nodes.append(ComputeNode(
                id=kernel_id,
                type=kernel_data['type'],
                dominance=kernel_data['dominance'],
                flops_per_call=kernel_data['flops'],
                precision=kernel_data.get('precision', 'FP64'),
                dimensions=kernel_data['dimensions'],
                typical_sizes=kernel_data['typical_sizes']
            ))
        
        return cls(
            workload_id=data['case_id'],
            compute_graph=ComputeGraph(nodes=nodes, edges=data['data_flow']),
            execution_profile=data['execution'],
            memory_profile=data['memory'],
            data_movement=data['data_movement']
        )
    
    def to_architecture_evaluator_input(self) -> Dict:
        """转换为架构评估器的输入格式"""
        return {
            'gemm_ratio': sum(n.dominance for n in self.compute_graph.nodes 
                            if n.type == 'GEMM'),
            'operator_sweep_ratio': self._get_node_dominance('h_psi'),
            'reduced_build_ratio': self._get_node_dominance('build_H_sub'),
            'diag_ratio': self._get_node_dominance('cdiaghg'),
            'refresh_ratio': self._get_node_dominance('refresh'),
            'algorithm_stability': self.execution_profile.get('stability', 'stable'),
            'target_design_time_months': 6,
            'precision_requirement': self._get_dominant_precision(),
            'memory_footprint_mb': self.memory_profile['working_set_mb'],
            'bandwidth_requirement_gbps': self.data_movement['device_internal_mb_per_iter'] / 1000
        }
```

### 5.2 使用示例

```python
# step1_to_step2_flow.py
from workload_ir import WorkloadIR
from qe_architecture_family_comprehensive_evaluator import evaluate_architectures

def step1_to_step2_pipeline(step1_json_path: str, design_space_path: str):
    """Step 1 → Step 2 完整流程"""
    
    # Step 1: 加载 Workload IR
    workload_ir = WorkloadIR.from_step1_json(step1_json_path)
    
    # 转换为评估器输入
    workload_profile = workload_ir.to_architecture_evaluator_input()
    
    # Step 2: 架构评估
    results = evaluate_architectures(
        workload=workload_profile,
        design_space_path=design_space_path,
        fidelity='L0'
    )
    
    # Pareto 分析
    pareto_results = pareto_analysis(results)
    
    # 选择最优架构
    best = max(pareto_results, key=lambda x: x.weighted_total)
    
    return {
        'workload_ir': workload_ir,
        'evaluation_results': results,
        'pareto_frontier': pareto_results,
        'selected_architecture': best,
        'frozen_interface': generate_frozen_interface(best)
    }
```

---

## 6. 与现有代码库的整合

### 6.1 现有 Step 1 输出

当前代码库中的 Step 1 输出：
- `docs/benchmarks/results/qe_workload_revalidation/summary.json`
- `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md`

### 6.2 整合方案

**新增文件**：
1. `docs/benchmarks/workload_ir.py` — Workload IR 定义和转换
2. `docs/benchmarks/workload_ir_schema_v0.json` — JSON Schema
3. `docs/benchmarks/step1_to_step2_pipeline.py` — 数据流管道

**修改文件**：
1. `qe_architecture_family_comprehensive_evaluator.py` — 接受 WorkloadIR 输入
2. `qe_partition_and_interface_for_system_dse_v1.md` — 更新数据流描述

### 6.3 验证方法

```bash
# 1. 生成 Workload IR
python3 docs/benchmarks/workload_ir.py \
    --step1-summary docs/benchmarks/results/qe_workload_revalidation/summary.json \
    --output workload_ir_si8.json

# 2. 运行架构评估
python3 docs/benchmarks/qe_architecture_family_comprehensive_evaluator.py \
    --workload-ir workload_ir_si8.json \
    --output-dir tmp/architecture_eval_si8

# 3. 验证数据流
python3 docs/benchmarks/step1_to_step2_pipeline.py \
    --step1-summary docs/benchmarks/results/qe_workload_revalidation/summary.json \
    --design-space docs/architecture/architecture_comparison/architecture_design_space_v1.json \
    --output step2_output_si8.json
```

---

## 7. 一句话收口

> **Step 1 输出标准化的 Workload IR（计算图、执行特征、内存特征、数据移动），Step 2 只消费这个抽象描述，通过多保真度量化评估（指标向量 + Pareto/加权评分）选择最优架构，最终冻结接口。软件细节在 Step 1 之后不再进入后续流程。**
