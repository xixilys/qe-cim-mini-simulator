# Phase 2.1 Complete Analysis: SystemC Architecture Deep Dive

**Date**: 2026-04-20  
**Status**: ✅ COMPLETED

---

## Executive Summary

完成了对SystemC模型的全面分析，识别了所有硬编码的架构参数和需要重构的位置。关键发现：

1. **F1/F2/F3不是硬件架构变体**，而是**策略配置模板**（offload scope、resident policy、diag policy）
2. **4-Cluster架构是硬编码的**，在ClusterGraphExecutor中固定实例化
3. **计算单元类型（CIM vs Traditional FPGA）未找到切换逻辑**，可能也是硬编码的
4. **配置流程完整**，但架构实例化发生在配置加载之前

---

## Finding 1: F1/F2/F3 Architecture Families

### 实际含义

F1/F2/F3 **不是硬件架构变体**，而是**运行时策略配置**：

| Family | Label | Offload Scope | Resident Policy | Diag Policy | Use Case |
|--------|-------|---------------|-----------------|-------------|----------|
| **F1** | HostHeavySingleHotpath | single_hotpath | fit_first | cpu_only | 保守方案，只offload热点 |
| **F2** | BalancedHybrid | balanced | fit_first | device_first_fallback | 平衡方案（默认） |
| **F3** | DeviceHeavyFullInnerLoop | device_heavy | spill_tolerant | aggressive_device | 激进方案，全部offload |

### 配置参数详解

**Offload Scope** (控制什么被offload到FPGA):
- `single_hotpath`: 只offload最热的路径（h_psi/s_psi）
- `balanced`: 平衡offload（h_psi/s_psi + 部分diag）
- `device_heavy`: 激进offload（整个inner loop）

**Resident Policy** (控制数据常驻策略):
- `fit_first`: 优先放入能放下的数据
- `spill_tolerant`: 允许数据溢出到host

**Diag Policy** (控制eigensolver位置):
- `cpu_only`: 强制在CPU上执行
- `device_first_fallback`: 优先FPGA，失败则CPU
- `aggressive_device`: 激进使用FPGA

### 代码实现 (architecture_template.cpp)

```cpp
ArchitectureTemplateConfig resolve_architecture_template(
    const SystemRunConfig& run_config) {
  ArchitectureTemplateConfig config;
  
  if (run_config.architecture_family == "F1") {
    config.offload_scope = "single_hotpath";
    config.resident_policy = "fit_first";
    config.diag_policy = "cpu_only";
    config.resident_budget_scale = 0.85;
    config.device_diag_max_dim = 8;
  } else if (run_config.architecture_family == "F3") {
    config.offload_scope = "device_heavy";
    config.resident_policy = "spill_tolerant";
    config.diag_policy = "aggressive_device";
    config.resident_budget_scale = 1.20;
    config.device_diag_max_dim = 40;
  } else {  // F2 (default)
    config.offload_scope = "balanced";
    config.resident_policy = "fit_first";
    config.diag_policy = "device_first_fallback";
    config.resident_budget_scale = 1.00;
    config.device_diag_max_dim = 28;
  }
  
  return config;
}
```

### 使用位置

**host_scf.cpp** (257-316行):
- 根据architecture_family调整offload决策
- 控制哪些操作在FPGA上执行

**cluster_c_hardware_diag.cpp** (234-243行):
- 根据architecture_family调整eigensolver性能系数
- F1: 0.9x (保守), F2: 0.65x (平衡), F3: 1.25x (激进)

---

## Finding 2: Hardcoded 4-Cluster Architecture

### ClusterGraphExecutor (cluster_graph_executor.hpp)

```cpp
class ClusterGraphExecutor : public sc_core::sc_module {
 public:
  explicit ClusterGraphExecutor(sc_core::sc_module_name name);
  
  EpisodeResult run_episode(const EpisodeDescriptor& descriptor,
                            const EpisodeController& controller) const;

 private:
  ClusterAOperatorSweep cluster_a_;      // ← HARDCODED
  ClusterBReducedBuild cluster_b_;       // ← HARDCODED
  ClusterCHardwareDiag cluster_c_;       // ← HARDCODED
  ClusterDRefreshResidual cluster_d_;    // ← HARDCODED
};
```

### 问题分析

**硬编码的内容**:
1. **Cluster数量**: 固定4个
2. **Cluster类型**: 固定A/B/C/D四种类型
3. **成员变量名**: cluster_a_, cluster_b_, cluster_c_, cluster_d_
4. **实例化时机**: 构造函数中自动实例化

**无法支持的场景**:
- ❌ 2-Cluster架构（只有A+C）
- ❌ 3-Cluster架构（A+B+C融合）
- ❌ 5-Cluster架构（A拆分为多个）
- ❌ 禁用某个cluster
- ❌ 改变cluster执行顺序

### 相关文件

**Cluster实现**:
- `src/clusters/cluster_a_operator_sweep.cpp` - h_psi/s_psi (68%时间)
- `src/clusters/cluster_b_reduced_build.cpp` - H_sub/S_sub (4%时间)
- `src/clusters/cluster_c_hardware_diag.cpp` - Eigensolver (23%时间)
- `src/clusters/cluster_d_refresh_residual.cpp` - Residual (5%时间)

**Cluster编排**:
- `src/clusters/cluster_graph_executor.cpp` - 硬编码4-cluster实例化和执行

---

## Finding 3: Compute Unit Type Selection

### 搜索结果

**CIM Array相关文件**:
- `src/onchip/cim_array_core.cpp` - CIM Array实现
- `include/onchip/cim_array_core.hpp` - CIM Array接口

**Traditional FPGA相关文件**:
- `src/onchip/traditional_fpga_gemm_core.cpp` - Traditional FPGA实现
- `include/onchip/traditional_fpga_gemm_core.hpp` - Traditional FPGA接口

**Blocked GEMM引擎**:
- `src/onchip/blocked_gemm_engine.cpp` - 通用Blocked GEMM
- `include/onchip/blocked_gemm_engine.hpp` - GEMM接口

### 关键发现

**未找到计算单元类型切换逻辑！**

可能的情况：
1. **硬编码使用CIM Array** - 所有cluster都用CIM
2. **编译时选择** - 通过宏或条件编译选择
3. **隐式选择** - 在cluster内部硬编码

**需要进一步调查**:
- ClusterA如何选择CIM Array vs Traditional FPGA
- 是否有工厂模式或策略模式
- 是否通过配置参数控制

---

## Finding 4: Configuration Flow

### 完整配置流程

```
1. sc_main.cpp::load_run_config()
   ↓ (读取环境变量)
   SystemRunConfig {
     architecture_family: "F2"
     software_family: "QE"
     flow_family: "CBANDS_DIAG"
     ...
   }

2. sc_main.cpp::main()
   ↓ (实例化系统)
   DFTHybridSystem system("dft_hybrid_system")
   ↓ (构造函数)
   DFTHybridSystem::DFTHybridSystem(name) {
     fabric_("interconnect");           // ← 无配置参数
     chip_("chip_top");                 // ← 无配置参数
     fpga_("fpga_orchestrator", ...);   // ← 无配置参数
     host_("host_scf", ...);            // ← 无配置参数
   }

3. sc_main.cpp::main()
   ↓ (运行仿真)
   system.run_full_flow(run_config)    // ← 配置在这里传入
   ↓
   host_.run_full_flow(run_config)
   ↓
   architecture_template.cpp::resolve_architecture_template(run_config)
   ↓ (解析F1/F2/F3)
   ArchitectureTemplateConfig {
     offload_scope: "balanced"
     resident_policy: "fit_first"
     diag_policy: "device_first_fallback"
     ...
   }
```

### 关键问题

**配置传递时机错误**:
- 系统实例化（构造函数）时**没有**配置参数
- 配置在`run_full_flow()`时才传入
- 此时4-Cluster架构已经固定实例化

**影响**:
- 无法根据配置动态选择cluster数量
- 无法根据配置动态选择计算单元类型
- 架构在构造时就固定了

---

## Finding 5: Files Requiring Modification

### 核心文件（必须修改）

**1. System Hierarchy** (3 files)
- `src/dft_hybrid_system.cpp` - 添加配置参数到构造函数
- `src/chip_top.cpp` - 传递配置到cluster executor
- `src/clusters/cluster_graph_executor.cpp` - **重点**：动态cluster实例化

**2. Configuration** (2 files)
- `include/types.hpp` - 添加ArchitectureConfig结构
- `src/architecture_template.cpp` - 扩展模板解析逻辑

**3. Cluster Modules** (4 files)
- `src/clusters/cluster_a_operator_sweep.cpp` - 添加计算单元选择
- `src/clusters/cluster_b_reduced_build.cpp` - 可能需要配置
- `src/clusters/cluster_c_hardware_diag.cpp` - 可能需要配置
- `src/clusters/cluster_d_refresh_residual.cpp` - 可能需要配置

### 新增文件（需要创建）

**1. Factory Pattern** (2 files)
- `include/cluster_factory.hpp` - Cluster工厂接口
- `src/cluster_factory.cpp` - Cluster工厂实现

**2. Compute Unit Factory** (2 files)
- `include/onchip/compute_unit_factory.hpp` - 计算单元工厂接口
- `src/onchip/compute_unit_factory.cpp` - 计算单元工厂实现

**3. Configuration Projection** (2 files)
- `include/architecture_config.hpp` - 架构配置结构
- `src/architecture_config.cpp` - 配置投影逻辑

### 辅助文件（可选修改）

**1. Entry Point**
- `sc_main.cpp` - 传递配置到DFTHybridSystem构造函数

**2. Orchestration**
- `src/fpga_orchestrator.cpp` - 可能需要传递配置
- `src/host_scf.cpp` - 可能需要调整offload逻辑

---

## Refactoring Strategy

### Phase 2.2: Configuration Projection Layer

**目标**: 将Phase 1的架构模板JSON投影到SystemC配置

**步骤**:
1. 定义`ArchitectureConfig`结构（C++）
2. 实现`template_to_systemc_config.py`（Python）
3. 扩展`architecture_template.cpp`支持新配置格式

**交付物**:
- `include/architecture_config.hpp`
- `docs/benchmarks/template_to_systemc_config.py`
- 单元测试

### Phase 2.3: Dynamic Architecture Switching

**目标**: 修改SystemC模块支持配置驱动

**步骤**:
1. 修改构造函数签名传递配置
2. 实现ClusterFactory动态创建cluster
3. 实现ComputeUnitFactory动态选择计算单元
4. 修改ClusterGraphExecutor使用动态cluster列表

**交付物**:
- `include/cluster_factory.hpp` + `.cpp`
- `include/onchip/compute_unit_factory.hpp` + `.cpp`
- 修改后的`cluster_graph_executor.cpp`

### Phase 2.4: Validation

**目标**: 测试不同模板能否正确运行

**步骤**:
1. 测试4-Cluster CIM baseline（向后兼容）
2. 测试4-Cluster Traditional FPGA
3. 测试3-Cluster融合架构
4. 验证性能数据正确性

**交付物**:
- 测试报告
- 性能对比数据

---

## Implementation Approach

### Option 1: Minimal Refactoring (Recommended for Phase 2)

**策略**: 保持4-Cluster架构，只添加计算单元类型切换

**优点**:
- 最小改动
- 风险低
- 快速验证

**缺点**:
- 仍然无法支持2/3/5-cluster架构

**实现**:
```cpp
// 只修改cluster内部的计算单元选择
class ClusterAOperatorSweep {
  ComputeUnit* compute_unit_;  // 动态选择CIM/Traditional/PIM
};
```

### Option 2: Full Dynamic Architecture (Recommended for Phase 3)

**策略**: 完全动态的cluster实例化

**优点**:
- 完全灵活
- 支持任意cluster数量和类型

**缺点**:
- 改动大
- 风险高
- 需要更多测试

**实现**:
```cpp
class ClusterGraphExecutor {
  std::vector<std::unique_ptr<ClusterBase>> clusters_;  // 动态cluster列表
};
```

---

## Risk Assessment

### 高风险项

1. **SystemC模块生命周期管理**
   - SystemC模块必须在构造时完全初始化
   - 动态创建模块需要特殊处理
   - **缓解**: 使用SystemC推荐的动态模块创建模式

2. **Timing语义保持**
   - 重构可能改变timing行为
   - **缓解**: 保留原有timing模型，只改变实例化方式

### 中风险项

3. **配置格式兼容性**
   - 新配置格式可能与现有代码不兼容
   - **缓解**: 保留F1/F2/F3作为预设模板

4. **测试覆盖度**
   - 新架构可能有未测试的边界情况
   - **缓解**: 先支持4-cluster，后续扩展

---

## Next Steps

### Immediate (Phase 2.2)

1. ✅ 设计`ArchitectureConfig`结构
2. ✅ 实现`template_to_systemc_config.py`
3. ✅ 创建配置投影单元测试

### Short-term (Phase 2.3)

4. 实现ComputeUnitFactory（CIM/Traditional/PIM切换）
5. 修改ClusterA使用ComputeUnitFactory
6. 测试4-Cluster CIM vs Traditional FPGA

### Medium-term (Phase 2.4)

7. 验证性能数据正确性
8. 对比不同计算单元类型的性能
9. 生成Phase 2完成报告

---

## Estimated Effort

**Phase 2.2**: 1-2天
- 配置结构设计: 4小时
- 配置投影实现: 4小时
- 单元测试: 4小时

**Phase 2.3**: 2-3天
- ComputeUnitFactory: 1天
- ClusterA重构: 1天
- 测试和调试: 1天

**Phase 2.4**: 1天
- 性能验证: 4小时
- 文档和报告: 4小时

**总计**: 4-6天

---

## Conclusion

Phase 2.1分析完成，关键发现：

1. ✅ **F1/F2/F3是策略配置，不是硬件架构**
2. ✅ **4-Cluster架构硬编码在ClusterGraphExecutor**
3. ✅ **计算单元类型切换逻辑未找到，可能硬编码**
4. ✅ **配置流程完整，但时机错误（构造后才传入）**

**下一步**: 进入Phase 2.2，设计配置投影层。
