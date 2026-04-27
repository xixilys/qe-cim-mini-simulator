# Architecture Template System Design (Draft v0.1)

## 目标

设计一个架构模板系统，让DSE能够探索不同的系统架构，而不仅仅是参数。

## 核心概念

### 当前问题
- DSE只能探索"参数"（lane数量、buffer大小）
- 无法探索"架构"（Cluster数量、计算单元类型）

### 解决方案
引入"架构模板"概念：
- 每个模板定义一种架构变体
- DSE加载模板，生成候选架构
- SystemC根据架构描述运行仿真

## 架构模板JSON Schema (初步设计)

```json
{
  "template_id": "4cluster_cim_v1",
  "template_version": "v1.0",
  "description": "4-Cluster pipeline with CIM Array in Cluster A",
  
  "architecture": {
    "cluster_count": 4,
    "clusters": [
      {
        "cluster_id": "cluster_a",
        "function": "operator_sweep",
        "compute_units": [
          {
            "type": "cim_array",
            "role": "primary",
            "parameters": {
              "array_lanes": {"min": 8, "max": 32, "default": 16},
              "fft_lanes": {"min": 0, "max": 16, "default": 4}
            }
          }
        ],
        "memory": {
          "coeff_buffer_kb": {"min": 64, "max": 512, "default": 256},
          "row_buffer_kb": {"min": 32, "max": 256, "default": 128}
        }
      },
      {
        "cluster_id": "cluster_b",
        "function": "reduced_build",
        "compute_units": [
          {
            "type": "reduction_tree",
            "role": "primary",
            "parameters": {
              "accum_lanes": {"min": 4, "max": 16, "default": 8}
            }
          }
        ]
      },
      {
        "cluster_id": "cluster_c",
        "function": "hardware_diag",
        "compute_units": [
          {
            "type": "lapack_eigensolver",
            "role": "primary",
            "parameters": {
              "solver_parallelism": {"min": 1, "max": 8, "default": 4}
            }
          }
        ]
      },
      {
        "cluster_id": "cluster_d",
        "function": "refresh_residual",
        "compute_units": [
          {
            "type": "vector_engine",
            "role": "primary",
            "parameters": {
              "refresh_lanes": {"min": 4, "max": 16, "default": 8}
            }
          }
        ]
      }
    ],
    
    "interconnect": {
      "a_to_b_bandwidth_gbps": {"min": 10, "max": 100, "default": 50},
      "b_to_c_bandwidth_gbps": {"min": 5, "max": 50, "default": 25},
      "c_to_d_bandwidth_gbps": {"min": 5, "max": 50, "default": 25}
    }
  },
  
  "timing_model": {
    "cluster_a": "ozaki_cycle_accurate",
    "cluster_b": "proxy_formula",
    "cluster_c": "lapack_operation_count",
    "cluster_d": "proxy_formula"
  },
  
  "constraints": {
    "max_total_lut": 500000,
    "max_total_bram": 2000,
    "max_power_w": 75
  }
}
```

## 设计要点

### 1. 模板可以表达的架构变体

**Cluster数量：**
- 2-Cluster: 合并A+B, 合并C+D
- 3-Cluster: 合并B+C, 或合并C+D
- 4-Cluster: 当前baseline
- 5-Cluster: 拆分A为operator+FFT

**计算单元类型：**
- Cluster A: `cim_array` | `traditional_fpga_gemm` | `pim` | `hybrid`
- Cluster C: `lapack_eigensolver` | `jacobi_iterative` | `divide_conquer`

**Pipeline组织：**
- Sequential: A → B → C → D
- Parallel: (A || B) → C → D
- Fused: A+B → C+D

### 2. 参数探索空间

每个参数定义为：
```json
{
  "min": <最小值>,
  "max": <最大值>,
  "default": <默认值>,
  "step": <可选，步长>
}
```

DSE可以：
- 使用default值快速验证
- 在[min, max]范围内sweep
- 使用step控制探索粒度

### 3. Timing模型选择

每个Cluster可以指定timing模型：
- `ozaki_cycle_accurate`: 使用Ozaki模型（±10%精度）
- `lapack_operation_count`: 基于LAPACK操作数（±10%精度）
- `proxy_formula`: 使用代理公式（±20%精度）
- `board_measurement_required`: 标记需要板卡实测

### 4. 约束条件

模板可以定义资源约束：
- LUT/FF/BRAM/DSP数量
- 功耗预算
- 时钟频率要求

## 使用流程

### Step 1: 创建架构模板

```bash
docs/architecture/architecture_templates/
├── 4cluster_cim_v1.json              # 当前baseline
├── 4cluster_traditional_v1.json      # Traditional FPGA替代
├── 3cluster_traditional_v1.json      # 3-Cluster变体
├── 5cluster_hybrid_v1.json           # 5-Cluster变体
└── 2cluster_fused_v1.json            # 2-Cluster算子融合
```

### Step 2: DSE加载模板

```python
# 在run_systemc_architecture_family_dse_sweep.py中
templates = load_architecture_templates("docs/architecture/architecture_templates/")

for template in templates:
    # 生成候选架构
    candidates = generate_candidates(template, strategy="grid_search")
    
    for candidate in candidates:
        # 生成SystemC配置
        systemc_config = template_to_systemc_config(candidate)
        
        # 运行仿真
        result = run_systemc_simulation(systemc_config)
        
        # 记录结果
        record_result(candidate, result)
```

### Step 3: SystemC读取配置

```cpp
// 在architecture_template.cpp中
void ArchitectureTemplate::load_from_json(const json& config) {
    cluster_count = config["architecture"]["cluster_count"];
    
    for (auto& cluster_config : config["architecture"]["clusters"]) {
        string cluster_id = cluster_config["cluster_id"];
        string compute_type = cluster_config["compute_units"][0]["type"];
        
        // 根据类型创建计算单元
        if (compute_type == "cim_array") {
            clusters[cluster_id] = make_unique<CIMArrayCore>(...);
        } else if (compute_type == "traditional_fpga_gemm") {
            clusters[cluster_id] = make_unique<TraditionalFPGAGEMM>(...);
        }
        ...
    }
}
```

## 待探索任务完成后确定

以下内容需要等待探索任务完成后确定：

1. **SystemC配置格式** - 当前实际使用的JSON schema
2. **F1/F2/F3的具体区别** - 是否只是参数不同，还是架构不同
3. **DSE投影机制** - component catalog如何映射到SystemC配置
4. **现有计算单元接口** - CIM vs Traditional FPGA的接口是否统一

## 下一步

1. 等待3个探索任务完成
2. 根据探索结果完善schema设计
3. 实现模板加载和候选生成代码
4. 创建3-5个初始模板
5. 验证：DSE能否加载模板并生成有效配置

---

**状态：** 等待探索任务完成...
