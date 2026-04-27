# Phase 2.3 Implementation Report

**Date**: 2026-04-20  
**Status**: ⚠️ PARTIAL COMPLETION - Strategy Adjustment

---

## Summary

Phase 2.3的目标是实现动态架构切换。在实施过程中发现SystemC模块的构造时初始化限制，需要调整策略。

---

## Completed Work

### 1. ComputeUnitFactory Implementation ✅

**Files Created**:
- `include/onchip/compute_unit_base.hpp` (26 lines)
- `include/onchip/compute_unit_factory.hpp` (31 lines)
- `src/onchip/compute_unit_factory.cpp` (75 lines)

**Key Features**:
- 统一的`ComputeUnitBase`接口
- 工厂方法支持CIM/Traditional FPGA/PIM
- 自动fallback机制（PIM → Traditional FPGA, Hybrid → CIM）
- 日志记录计算单元创建

**Code**:
```cpp
class ComputeUnitBase : public sc_core::sc_module {
 public:
  virtual ProjectCoeffPacket project(...) const = 0;
  virtual PartialHS backproject(...) const = 0;
};

class ComputeUnitFactory {
 public:
  static std::unique_ptr<ComputeUnitBase> create(
      const std::string& module_name,
      const ComputeUnitConfig& config);
};
```

### 2. Compute Unit Inheritance ✅

**Modified Files**:
- `include/onchip/cim_array_core.hpp` - 继承`ComputeUnitBase`
- `include/onchip/traditional_fpga_gemm_core.hpp` - 继承`ComputeUnitBase`

**Changes**:
```cpp
// Before
class CIMArrayCore : public sc_core::sc_module { ... };

// After
class CIMArrayCore : public ComputeUnitBase { ... };
```

---

## Discovered Challenges

### Challenge 1: SystemC Module Construction Constraints

**Problem**: SystemC模块必须在构造函数中完全初始化

```cpp
// SystemC要求
ClusterGraphExecutor::ClusterGraphExecutor(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      cluster_a_("cluster_a"),  // 必须在这里初始化
      cluster_b_("cluster_b"),  // 不能延迟到运行时
      cluster_c_("cluster_c"),
      cluster_d_("cluster_d") {}
```

**Impact**: 
- 无法在构造后动态创建cluster
- 无法根据配置改变cluster数量
- 配置必须在构造前传入

### Challenge 2: Configuration Timing

**Problem**: 配置在`run_full_flow()`时传入，但模块已在构造时初始化

```cpp
// sc_main.cpp
DFTHybridSystem system("dft_hybrid_system");  // 构造时无配置
system.run_full_flow(run_config);             // 配置在这里传入（太晚了）
```

**Impact**:
- 无法在构造时使用配置
- 需要重构整个构造流程

### Challenge 3: Nested Module Initialization

**Problem**: `CIMEligibleOperatorSubchain`硬编码`CIMArrayCore`

```cpp
class CIMEligibleOperatorSubchain : public sc_core::sc_module {
 private:
  CIMArrayCore cim_array_core_;  // 硬编码，无法切换
};
```

**Impact**:
- 需要修改多层嵌套的模块
- 每层都需要传递配置
- 改动范围大，风险高

---

## Strategy Adjustment

### Original Plan (Phase 2.3)

1. ✅ 实现ComputeUnitFactory
2. ❌ 修改ClusterA使用ComputeUnitFactory
3. ❌ 测试4-Cluster CIM vs Traditional FPGA

### Adjusted Plan

**Phase 2.3 (Current)**: 基础设施完成
- ✅ ComputeUnitFactory实现
- ✅ ComputeUnitBase接口
- ✅ 继承关系建立

**Phase 3 (Future)**: 完整重构
- 修改构造函数签名传递配置
- 重构ClusterGraphExecutor支持动态cluster
- 重构CIMEligibleOperatorSubchain支持动态计算单元
- 端到端测试

---

## Why This Adjustment Makes Sense

### 1. SystemC Best Practices

**SystemC推荐**: 配置驱动的模块需要在构造时传入配置

```cpp
// 正确的SystemC模式
DFTHybridSystem::DFTHybridSystem(
    sc_core::sc_module_name name,
    const ArchitectureConfig& config)  // 配置在构造时传入
    : sc_core::sc_module(name),
      config_(config),
      chip_("chip_top", config) {}     // 传递给子模块
```

### 2. Scope Management

**Phase 2**: 配置投影层（完成）
- ArchitectureConfig结构 ✅
- template_to_systemc_config.py ✅
- ComputeUnitFactory ✅

**Phase 3**: SystemC重构（未来）
- 构造函数重构
- 动态cluster实例化
- 完整测试

### 3. Risk Mitigation

**Current Approach**: 分阶段推进，降低风险
- Phase 2专注配置层
- Phase 3专注SystemC重构
- 每个阶段都有明确的交付物

---

## What We Achieved in Phase 2

### 1. 深入理解SystemC架构 ✅

- 识别了所有硬编码位置
- 理解了F1/F2/F3的真实含义
- 发现了配置时机问题

### 2. 设计了灵活的配置结构 ✅

- ArchitectureConfig支持任意cluster配置
- ComputeUnitConfig支持多种计算单元类型
- 完整的资源约束和验证

### 3. 实现了配置投影 ✅

- 自动化Python脚本
- 测试验证所有模板
- 为Phase 3做好准备

### 4. 创建了ComputeUnitFactory ✅

- 统一的计算单元接口
- 工厂模式支持动态创建
- 为Phase 3的集成做好准备

---

## Phase 3 Roadmap

### Week 1: Constructor Refactoring

**Goal**: 修改构造函数传递配置

**Tasks**:
1. 修改`DFTHybridSystem`构造函数接受`ArchitectureConfig`
2. 修改`ChipTop`构造函数传递配置
3. 修改`ClusterGraphExecutor`构造函数传递配置
4. 修改`sc_main.cpp`在构造时传入配置

**Deliverable**: 配置能在构造时传递到所有模块

### Week 2: Dynamic Cluster Instantiation

**Goal**: 支持动态cluster数量和类型

**Tasks**:
1. 重构`ClusterGraphExecutor`使用`std::vector<std::unique_ptr<ClusterBase>>`
2. 实现`ClusterFactory`动态创建cluster
3. 修改`run_episode()`支持动态cluster列表
4. 测试2/3/4/5-cluster架构

**Deliverable**: 支持任意数量和类型的cluster

### Week 3: Compute Unit Integration

**Goal**: 集成ComputeUnitFactory到cluster

**Tasks**:
1. 重构`CIMEligibleOperatorSubchain`使用`ComputeUnitBase*`
2. 在构造时根据配置创建计算单元
3. 测试CIM vs Traditional FPGA
4. 性能对比和验证

**Deliverable**: 完整的配置驱动系统

### Week 4: Testing and Validation

**Goal**: 端到端测试和性能验证

**Tasks**:
1. 测试所有模板（CIM/Traditional/3-cluster）
2. 验证资源估算准确性
3. 生成性能对比报告
4. 文档和总结

**Deliverable**: Phase 3完成报告

---

## Current Status

### Completed (Phase 2)

- ✅ SystemC架构分析
- ✅ ArchitectureConfig设计
- ✅ 配置投影脚本
- ✅ ComputeUnitFactory实现

### In Progress (Phase 2.3 → Phase 3)

- 🔄 构造函数重构（待开始）
- 🔄 动态cluster实例化（待开始）
- 🔄 计算单元集成（待开始）

### Pending (Phase 3)

- ⏳ 端到端测试
- ⏳ 性能验证
- ⏳ 文档完善

---

## Recommendation

**建议**: 将Phase 2.3的剩余工作（ClusterA修改和测试）合并到Phase 3

**理由**:
1. 需要完整的构造函数重构才能正确传递配置
2. 局部修改会导致不一致的架构
3. 一次性重构更清晰，风险更可控

**Phase 2成果**:
- 配置投影层完整实现 ✅
- ComputeUnitFactory基础设施就绪 ✅
- 为Phase 3的SystemC重构做好准备 ✅

**下一步**: 
- 完成Phase 2总结报告
- 规划Phase 3详细实施计划
- 获得用户确认后开始Phase 3

---

## Files Created in Phase 2.3

```
model/qe_band_solver_model/
├── include/
│   └── onchip/
│       ├── compute_unit_base.hpp          (26 lines, NEW)
│       └── compute_unit_factory.hpp       (31 lines, NEW)
└── src/
    └── onchip/
        └── compute_unit_factory.cpp       (75 lines, NEW)
```

**Total New Code**: 132 lines

---

## Conclusion

Phase 2.3部分完成，创建了ComputeUnitFactory基础设施。发现SystemC构造时初始化限制，需要更全面的重构。

**Phase 2总体成果**:
- 深入理解SystemC架构 ✅
- 完整的配置投影层 ✅
- ComputeUnitFactory基础设施 ✅
- 为Phase 3做好准备 ✅

**建议**: 将剩余工作合并到Phase 3，进行完整的SystemC重构。
