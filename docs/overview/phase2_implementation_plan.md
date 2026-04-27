# Phase 2 Implementation Plan: Simulator Configuration-Driven Architecture

**Goal**: 让SystemC模型能够根据架构模板动态切换架构

**Duration**: 1-2周  
**Status**: 🚀 Starting

---

## Overview

Phase 2将实现配置驱动的SystemC模拟器，使其能够：
1. 读取架构模板JSON配置
2. 根据配置动态实例化不同的计算单元（CIM/Traditional FPGA/PIM）
3. 支持不同数量的cluster（2/3/4/5个）
4. 保持timing模型的准确性

---

## Task Breakdown

### Phase 2.1: 分析SystemC配置机制 (2-3小时)
**目标**: 理解现有SystemC如何读取和使用配置

**子任务**:
- [ ] 2.1.1: 查找SystemC的配置入口点
- [ ] 2.1.2: 分析现有的硬编码架构参数
- [ ] 2.1.3: 识别需要参数化的模块
- [ ] 2.1.4: 理解cluster实例化流程

**交付物**:
- SystemC配置机制分析文档
- 硬编码参数清单
- 参数化改造点列表

---

### Phase 2.2: 设计配置投影层 (3-4小时)
**目标**: 设计模板JSON到SystemC配置的映射

**子任务**:
- [ ] 2.2.1: 设计SystemC配置格式
- [ ] 2.2.2: 实现模板到SystemC配置的投影函数
- [ ] 2.2.3: 处理cluster数量变化的逻辑
- [ ] 2.2.4: 处理计算单元类型切换的逻辑

**交付物**:
- SystemC配置格式定义
- 配置投影器实现 (`template_to_systemc_config.py`)
- 单元测试

---

### Phase 2.3: 实现动态架构切换 (1-2天)
**目标**: 修改SystemC模块支持配置驱动

**子任务**:
- [ ] 2.3.1: 参数化cluster数量
- [ ] 2.3.2: 实现计算单元工厂模式
- [ ] 2.3.3: 修改cluster实例化逻辑
- [ ] 2.3.4: 更新timing模型以支持不同计算单元

**交付物**:
- 修改后的SystemC模块
- 计算单元工厂类
- 配置驱动的cluster实例化

---

### Phase 2.4: 验证配置驱动 (1天)
**目标**: 测试不同模板能否正确运行

**子任务**:
- [ ] 2.4.1: 测试4-Cluster CIM baseline
- [ ] 2.4.2: 测试4-Cluster Traditional FPGA
- [ ] 2.4.3: 测试3-Cluster融合架构
- [ ] 2.4.4: 验证性能数据的正确性

**交付物**:
- 测试报告
- 性能对比数据
- Bug修复记录

---

## Technical Approach

### 1. 配置投影策略

```python
# 模板JSON → SystemC配置
template = {
    "template_id": "4cluster_traditional_fpga_v1",
    "clusters": [
        {"cluster_id": "cluster_a", "compute_unit": "traditional_fpga_dsp", ...},
        {"cluster_id": "cluster_b", "compute_unit": "traditional_fpga_dsp", ...},
        ...
    ]
}

# 投影为SystemC配置
systemc_config = {
    "num_clusters": 4,
    "cluster_configs": [
        {"id": "cluster_a", "type": "traditional_fpga_dsp", "params": {...}},
        ...
    ]
}
```

### 2. 计算单元工厂模式

```cpp
// SystemC中的工厂模式
class ComputeUnitFactory {
public:
    static ComputeUnit* create(const std::string& type, const Config& config) {
        if (type == "cim_array") {
            return new CIMArrayCore(config);
        } else if (type == "traditional_fpga_dsp") {
            return new TraditionalFPGAGEMMCore(config);
        } else if (type == "pim_array") {
            return new PIMArrayCore(config);
        }
        // ...
    }
};
```

### 3. 动态Cluster实例化

```cpp
// 根据配置动态创建cluster
for (const auto& cluster_config : systemc_config.cluster_configs) {
    auto compute_unit = ComputeUnitFactory::create(
        cluster_config.type, 
        cluster_config.params
    );
    clusters.push_back(new Cluster(cluster_config.id, compute_unit));
}
```

---

## Success Criteria

Phase 2成功的标准：

1. ✅ **配置加载**: SystemC能够读取模板JSON并解析
2. ✅ **动态实例化**: 能够根据配置创建不同数量和类型的cluster
3. ✅ **正确性验证**: 不同配置下的数值结果正确（与golden baseline对比）
4. ✅ **性能数据**: Timing模型输出合理的性能数据
5. ✅ **向后兼容**: 原有的4-Cluster CIM baseline仍能正常运行

---

## Risk Assessment

### 高风险项
1. **SystemC重构复杂度**: 现有代码可能有大量硬编码，重构工作量大
   - **缓解**: 先做小范围试点，验证可行性后再全面推进

2. **Timing模型准确性**: 不同计算单元的timing模型可能不一致
   - **缓解**: 保留代理公式作为fallback，逐步提升精度

### 中风险项
3. **配置格式兼容性**: 模板JSON可能无法完全映射到SystemC配置
   - **缓解**: 设计灵活的投影层，支持扩展字段

4. **测试覆盖度**: 3个模板可能无法覆盖所有边界情况
   - **缓解**: 先验证核心场景，后续迭代增加测试用例

---

## Dependencies

### 前置条件
- ✅ Phase 1完成（架构模板系统）
- ✅ SystemC模型可编译运行
- ✅ 现有的4-Cluster CIM baseline能正常工作

### 外部依赖
- SystemC 2.3.3+
- C++17编译器
- Python 3.7+ (配置投影器)

---

## Timeline

```
Week 1:
  Day 1-2: Phase 2.1 分析SystemC配置机制
  Day 3-4: Phase 2.2 设计配置投影层
  Day 5:   Phase 2.3 开始实现动态架构切换

Week 2:
  Day 1-3: Phase 2.3 完成动态架构切换
  Day 4-5: Phase 2.4 验证配置驱动
```

**预计完成时间**: 2周后

---

## Next Immediate Action

开始Phase 2.1.1 - 查找SystemC的配置入口点

**具体步骤**:
1. 查找`sc_main`函数
2. 查找配置文件读取代码
3. 查找cluster实例化代码
4. 识别硬编码的架构参数
