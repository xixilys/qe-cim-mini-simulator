# Phase 2.2.1 Completion Report: ArchitectureConfig Structure Design

**Date**: 2026-04-20  
**Status**: ✅ COMPLETED

---

## Summary

成功设计并实现了`ArchitectureConfig`结构，这是连接Phase 1 JSON模板和SystemC模型的核心数据结构。

---

## Deliverables

### 1. Header File: `include/architecture_config.hpp` (181 lines)

**核心结构**:
- `ComputeUnitType` enum - 计算单元类型（CIM/Traditional FPGA/PIM/Hybrid）
- `ComputeUnitConfig` struct - 计算单元配置参数
- `ClusterType` enum - Cluster功能类型（A/B/C/D/Fused/Custom）
- `ClusterConfig` struct - 单个cluster的完整配置
- `ArchitectureConfig` struct - 完整架构配置（主结构）

**关键特性**:
- 支持1-N个cluster的任意组合
- 支持多种计算单元类型切换
- 包含资源约束验证（DSP/BRAM/URAM/LUT/FF）
- 包含互连和时序配置
- 提供F1/F2/F3预设模板工厂方法
- 支持从JSON文件加载（待实现）

### 2. Implementation File: `src/architecture_config.cpp` (301 lines)

**实现功能**:
- `brief()` 方法 - 所有结构的简洁字符串表示
- `validate()` 方法 - 配置有效性验证
- `estimate_resources()` 方法 - FPGA资源使用估算
- `from_f1_template()` - F1预设模板工厂
- `from_f2_template()` - F2预设模板工厂
- `from_f3_template()` - F3预设模板工厂
- `from_json_file()` - JSON加载（占位符，Phase 2.2.2实现）
- 字符串转换辅助函数

---

## Design Decisions

### 1. 分层配置结构

```
ArchitectureConfig
├── Metadata (template_id, label, family)
├── Clusters[] (vector of ClusterConfig)
│   ├── ClusterConfig
│   │   ├── cluster_id, type
│   │   ├── ComputeUnitConfig
│   │   │   ├── type (CIM/Traditional/PIM)
│   │   │   ├── CIM-specific params
│   │   │   ├── FPGA-specific params
│   │   │   └── PIM-specific params
│   │   ├── Buffer/DMA config
│   │   └── Execution policy
├── Global Policies (offload_scope, diag_policy, etc.)
├── Resource Limits (VU9P constraints)
├── Interconnect Config (AXI, PCIe, DDR)
└── Timing Config (clock, proxy formulas)
```

**优点**:
- 清晰的层次结构
- 易于扩展新的cluster类型
- 易于扩展新的计算单元类型
- 配置验证逻辑集中

### 2. 枚举类型 vs 字符串

**选择**: 使用强类型枚举（`enum class`）+ 字符串转换函数

**理由**:
- 编译时类型检查
- IDE自动补全支持
- 避免拼写错误
- 性能更好（switch vs string比较）

**实现**:
```cpp
enum class ComputeUnitType {
  CIM_ARRAY,
  TRADITIONAL_FPGA,
  PIM,
  HYBRID
};

std::string to_string(ComputeUnitType type);
ComputeUnitType compute_unit_type_from_string(const std::string& str);
```

### 3. 资源估算策略

**当前实现**: 简化的线性估算

```cpp
ResourceUsage estimate_resources() const {
  ResourceUsage usage;
  for (const auto& cluster : clusters) {
    if (cu.type == ComputeUnitType::CIM_ARRAY) {
      usage.dsp_used += 50;
      usage.bram_18k_used += 80;
      // ...
    } else if (cu.type == ComputeUnitType::TRADITIONAL_FPGA) {
      usage.dsp_used += cu.fpga_dsp_count;
      usage.bram_18k_used += 60;
      // ...
    }
  }
  return usage;
}
```

**未来改进**:
- 基于实际综合报告的精确估算
- 考虑布线资源
- 考虑时钟域交叉
- 考虑互连开销

### 4. 工厂方法模式

**提供三种预设模板**:

```cpp
ArchitectureConfig::from_f1_template()  // Host-heavy, single hotpath
ArchitectureConfig::from_f2_template()  // Balanced hybrid (default)
ArchitectureConfig::from_f3_template()  // Device-heavy, full inner loop
```

**优点**:
- 向后兼容现有F1/F2/F3
- 提供合理的默认配置
- 易于测试和验证

---

## Configuration Parameters

### ComputeUnitConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | enum | CIM_ARRAY | 计算单元类型 |
| `cim_moduli_count` | int | 16 | Ozaki-II模数数量 |
| `cim_array_rows` | int | 256 | CIM阵列行数 |
| `cim_array_cols` | int | 256 | CIM阵列列数 |
| `cim_frequency_mhz` | double | 150.0 | CIM时钟频率 |
| `fpga_tile_size` | int | 32 | Blocked GEMM tile大小 |
| `fpga_dsp_count` | int | 128 | DSP slice数量 |
| `fpga_frequency_mhz` | double | 300.0 | FPGA时钟频率 |
| `parallelism` | int | 4 | 并行计算通道 |
| `enable_karatsuba` | bool | true | 使用Karatsuba 3M |

### ClusterConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cluster_id` | string | - | Cluster标识符 |
| `type` | enum | OPERATOR_SWEEP | Cluster功能类型 |
| `compute_unit` | struct | - | 计算单元配置 |
| `on_chip_buffer_kb` | int | 512 | On-chip缓冲区大小 |
| `dma_bandwidth_gbps` | int | 100 | DMA带宽 |
| `enable_pipelining` | bool | true | 启用流水线 |
| `pipeline_depth` | int | 4 | 流水线深度 |
| `resident_policy` | string | fit_first | 常驻对象策略 |
| `resident_budget_scale` | double | 1.0 | 常驻预算缩放 |

### ArchitectureConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `template_id` | string | - | 模板标识符 |
| `template_label` | string | - | 人类可读标签 |
| `architecture_family` | string | - | F1/F2/F3或custom |
| `clusters` | vector | - | Cluster配置列表 |
| `offload_scope` | string | balanced | Offload范围 |
| `diag_policy` | string | device_first_fallback | Eigensolver策略 |
| `enable_device_fft` | bool | true | 启用FPGA FFT |
| `force_host_diag` | bool | false | 强制CPU eigensolver |
| `allow_cpu_diag_fallback` | bool | true | 允许CPU fallback |

---

## Resource Limits (Xilinx VU9P)

```cpp
struct ResourceLimits {
  int max_dsp = 6840;
  int max_bram_18k = 4320;
  int max_uram = 960;
  int max_lut = 1182240;
  int max_ff = 2364480;
};
```

**来源**: Xilinx Virtex UltraScale+ VU9P FPGA规格

---

## Example Usage

### Creating F2 Template

```cpp
#include "architecture_config.hpp"

auto config = qebs::ArchitectureConfig::from_f2_template();

std::cout << config.brief() << std::endl;
// Output: template=F2, label=BalancedHybrid, family=F2, clusters=4, 
//         offload=balanced, diag=device_first_fallback, fft=device

for (const auto& cluster : config.clusters) {
  std::cout << cluster.brief() << std::endl;
}
```

### Custom Configuration

```cpp
qebs::ArchitectureConfig config;
config.template_id = "custom_3cluster";
config.template_label = "3-Cluster Fused B+C";
config.architecture_family = "custom";

qebs::ClusterConfig cluster_a;
cluster_a.cluster_id = "cluster_a";
cluster_a.type = qebs::ClusterType::OPERATOR_SWEEP;
cluster_a.compute_unit.type = qebs::ComputeUnitType::TRADITIONAL_FPGA;
cluster_a.compute_unit.fpga_frequency_mhz = 350.0;

qebs::ClusterConfig cluster_bc;
cluster_bc.cluster_id = "cluster_bc_fused";
cluster_bc.type = qebs::ClusterType::FUSED_BUILD_DIAG;
cluster_bc.compute_unit.type = qebs::ComputeUnitType::CIM_ARRAY;

qebs::ClusterConfig cluster_d;
cluster_d.cluster_id = "cluster_d";
cluster_d.type = qebs::ClusterType::REFRESH_RESIDUAL;

config.clusters = {cluster_a, cluster_bc, cluster_d};

if (config.is_valid()) {
  auto resources = config.estimate_resources();
  std::cout << "Resource usage: " << resources.brief() << std::endl;
}
```

### Validation

```cpp
auto config = qebs::ArchitectureConfig::from_f2_template();

if (!config.is_valid()) {
  std::cerr << "Invalid configuration: " << config.validate() << std::endl;
  return 1;
}

auto resources = config.estimate_resources();
if (!resources.within_limits(config.resource_limits)) {
  std::cerr << "Resource usage exceeds FPGA limits!" << std::endl;
  return 1;
}
```

---

## Integration Points

### 1. Phase 1 JSON Templates → ArchitectureConfig

**Next Step (Phase 2.2.2)**: 实现`template_to_systemc_config.py`

```python
# Load Phase 1 JSON template
with open('4cluster_cim_baseline_v1.json') as f:
    template = json.load(f)

# Project to ArchitectureConfig
config = project_template_to_architecture_config(template)

# Write to C++ readable format (JSON or binary)
with open('architecture_config.json', 'w') as f:
    json.dump(config, f)
```

### 2. ArchitectureConfig → SystemC Modules

**Next Step (Phase 2.3)**: 修改SystemC构造函数

```cpp
// Old (hardcoded)
DFTHybridSystem::DFTHybridSystem(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      chip_("chip_top") {}

// New (config-driven)
DFTHybridSystem::DFTHybridSystem(
    sc_core::sc_module_name name,
    const ArchitectureConfig& arch_config)
    : sc_core::sc_module(name),
      arch_config_(arch_config),
      chip_("chip_top", arch_config) {}
```

---

## Testing Strategy

### Unit Tests (Phase 2.2.3)

1. **Factory Methods**
   - Test F1/F2/F3 templates create valid configurations
   - Verify cluster counts and types
   - Verify compute unit types

2. **Validation**
   - Test empty cluster list rejection
   - Test resource limit enforcement
   - Test invalid cluster_id rejection

3. **Resource Estimation**
   - Test CIM Array resource usage
   - Test Traditional FPGA resource usage
   - Test multi-cluster accumulation

4. **String Conversion**
   - Test enum to string conversion
   - Test string to enum conversion
   - Test round-trip conversion

### Integration Tests (Phase 2.4)

1. **JSON Loading**
   - Load Phase 1 templates
   - Verify projection correctness
   - Test error handling

2. **SystemC Integration**
   - Pass config to DFTHybridSystem
   - Verify cluster instantiation
   - Verify compute unit selection

---

## Known Limitations

### 1. Simplified Resource Estimation

**Current**: 固定常数估算  
**Future**: 基于实际综合报告的精确模型

### 2. JSON Loading Not Implemented

**Current**: `from_json_file()` 返回占位符  
**Future**: Phase 2.2.2实现完整JSON解析

### 3. No Timing Model Integration

**Current**: 只有频率参数  
**Future**: 集成cycle-accurate timing模型

### 4. No Power Estimation

**Current**: 无功耗估算  
**Future**: 添加功耗模型

---

## Next Steps

### Immediate (Phase 2.2.2)

1. ✅ 实现`template_to_systemc_config.py`
   - 读取Phase 1 JSON模板
   - 投影到ArchitectureConfig格式
   - 写入JSON文件供SystemC读取

2. ✅ 实现`ArchitectureConfig::from_json_file()`
   - 使用JSON库（nlohmann/json或RapidJSON）
   - 解析JSON到C++结构
   - 错误处理和验证

### Short-term (Phase 2.2.3)

3. ✅ 创建单元测试
   - 测试所有工厂方法
   - 测试验证逻辑
   - 测试资源估算

### Medium-term (Phase 2.3)

4. 修改SystemC模块使用ArchitectureConfig
5. 实现ComputeUnitFactory
6. 实现ClusterFactory

---

## Files Created

```
model/qe_band_solver_model/
├── include/
│   └── architecture_config.hpp          (181 lines, NEW)
└── src/
    └── architecture_config.cpp          (301 lines, NEW)
```

**Total**: 482 lines of new code

---

## Conclusion

Phase 2.2.1成功完成，创建了灵活且可扩展的`ArchitectureConfig`结构。关键成果：

1. ✅ 支持任意数量和类型的cluster
2. ✅ 支持多种计算单元类型（CIM/Traditional/PIM）
3. ✅ 包含完整的资源约束和验证
4. ✅ 提供F1/F2/F3向后兼容的预设模板
5. ✅ 为Phase 2.2.2的JSON投影做好准备

**下一步**: 进入Phase 2.2.2，实现Python配置投影脚本。
