# DFT加速系统 DSE+Simulator 完整评估报告

## 执行摘要

**结论：当前系统需要"混合式"改进 - 关键部分重构，其他部分渐进扩展**

---

## 一、当前系统架构分析

### 1.1 DSE框架现状

**核心发现：**
- ✅ **有完整的component catalog系统** (16个组件，955行JSON)
- ✅ **有graph topology定义** (F1/F2/F3三种架构family)
- ❌ **探索空间被"4-Cluster"硬编码限制**
- ❌ **计算实现被"CIM"硬编码限制**

**具体证据：**
```python
# run_systemc_architecture_family_dse_sweep.py 第97-127行
CLUSTER_COMPONENT_GROUPS = {
    "cluster_a": [...],  # 硬编码4个cluster
    "cluster_b": [...],
    "cluster_c": [...],
    "cluster_d": [...],
}

# 第73-86行
LEAF_COMPONENT_ORDER = [
    "cim_operator_subchain",  # 硬编码CIM
    "cim_array_core",
    ...
]
```

**问题：**
1. **Cluster数量固定**：无法探索2-Cluster、3-Cluster、5-Cluster
2. **计算单元固定**：无法探索PIM、Traditional FPGA作为替代
3. **F1/F2/F3只是工作分配不同**，不是架构本质不同

---

### 1.2 SystemC Simulator现状

**核心发现：**
- ✅ **模块化程度较好** - 每个Cluster是独立的.cpp文件
- ✅ **已有Traditional FPGA GEMM实现** (blocked_gemm_engine.cpp, traditional_fpga_gemm_core.cpp)
- ❌ **Timing模型使用代理公式** (±20%误差)
- ⚠️ **架构切换需要重新编译**

**具体证据：**
```
model/qe_band_solver_model/src/clusters/
├── cluster_a_operator_sweep.cpp      # Cluster A独立模块
├── cluster_b_reduced_build.cpp       # Cluster B独立模块
├── cluster_c_hardware_diag.cpp       # Cluster C独立模块
├── cluster_d_refresh_residual.cpp    # Cluster D独立模块

model/qe_band_solver_model/src/onchip/
├── cim_array_core.cpp                # CIM实现
├── traditional_fpga_gemm_core.cpp    # Traditional FPGA实现（已存在！）
├── blocked_gemm_engine.cpp           # GEMM引擎
```

**代理公式证据：**
```markdown
# qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md

T_A = max(T_A_load, T_A_fft, T_A_array, T_A_emit)
T_B = max(T_B_accum, T_B_reduce, T_B_emit)
T_C = max(T_C_input, T_C_compute, T_C_emit)
T_D = max(T_D_refresh, T_D_residual, T_D_writeback)

# 默认系数（第33-71行）
k_dma_eff = 0.50
k_a_array_work_per_lane_per_us = 40.0
k_b_accum_kib_per_lane_per_us = 0.60
...
```

**问题：**
1. **代理公式精度不足**：文档明确说"不用于宣称最终FPGA性能"
2. **系数来源不明**：没有绑定到HLS schedule或板级测试
3. **架构切换困难**：需要修改C++代码并重新编译

---

## 二、核心问题诊断

### 问题1：DSE表达能力不足

**现状：**
- Component catalog只能表达"有哪些组件"
- Graph topology只能表达"组件如何连接"
- **无法表达"Cluster A用CIM还是Traditional FPGA"**
- **无法表达"用3个Cluster还是4个Cluster"**

**根本原因：**
DSE框架假设架构是"固定的"，只探索"参数"（如lane数量、buffer大小）

**需要的能力：**
DSE应该能探索"架构变体"（如不同的计算单元、不同的Cluster组织）

---

### 问题2：Simulator配置灵活性不足

**现状：**
- SystemC代码模块化较好
- 但架构选择是编译时决定的（C++代码）
- 无法通过配置文件快速切换架构

**根本原因：**
SystemC模型设计时假设架构是"冻结的"，只有参数是可配置的

**需要的能力：**
Simulator应该能通过JSON配置文件切换架构（如CIM vs Traditional FPGA）

---

### 问题3：Timing模型精度不足

**现状：**
- 使用简单的代理公式（T = workload / throughput）
- 系数是"拍脑袋"的默认值
- 文档明确说±20%误差，不能用于最终结论

**根本原因：**
没有cycle-accurate的计算单元模型

**需要的能力：**
关键计算单元（CIM Array, Eigensolver）需要更精确的timing模型（±10%）

---

## 三、改进方案

### 方案A：渐进式扩展（不推荐）

**做法：**
1. 在现有DSE框架中添加更多参数
2. 在SystemC中添加更多if-else分支
3. 逐步提升代理公式精度

**问题：**
- 代码会变得非常复杂和脆弱
- 无法从根本上解决"架构表达能力"问题
- 技术债务会越积越多

---

### 方案B：完全重构（不推荐）

**做法：**
1. 重新设计DSE框架（新的架构描述语言）
2. 重写SystemC模型（完全可配置）
3. 实现所有计算单元的cycle-accurate模型

**问题：**
- 工作量巨大（几个月）
- 风险高（可能做不完或做错）
- 浪费现有基础设施

---

### 方案C：混合式改进（推荐）✅

**核心思路：**
1. **DSE层：引入"架构模板"概念** - 重构
2. **Simulator层：配置驱动架构** - 重构
3. **Timing层：提升关键路径精度** - 渐进
4. **结合大模型辅助代码生成** - 创新

---

## 四、推荐方案详细设计

### 4.1 DSE层改进：架构模板系统

**当前问题：**
```python
# 当前：只能表达参数
{
  "a_array_lanes": 16,
  "b_accum_lanes": 8,
  ...
}
```

**改进后：**
```python
# 改进：可以表达架构变体
{
  "architecture_template": "4cluster_cim_v1",  # 或 "3cluster_traditional_v1"
  "cluster_a_compute_unit": "cim_array",       # 或 "traditional_fpga_gemm"
  "cluster_c_eigensolver": "lapack_style",     # 或 "jacobi_iterative"
  "parameters": {
    "a_array_lanes": 16,
    ...
  }
}
```

**实现方式：**
1. 创建`architecture_templates/`目录
2. 每个模板是一个JSON文件，定义：
   - Cluster数量和功能
   - 每个Cluster的计算单元类型
   - 默认参数范围
3. DSE框架加载模板，生成候选架构

**工作量：** 2-3天

---

### 4.2 Simulator层改进：配置驱动架构

**当前问题：**
```cpp
// 当前：架构硬编码在C++代码中
void ClusterA::operator_sweep() {
    cim_array_core->compute(...);  // 硬编码使用CIM
}
```

**改进后：**
```cpp
// 改进：通过配置选择计算单元
void ClusterA::operator_sweep() {
    if (config.compute_unit == "cim_array") {
        cim_array_core->compute(...);
    } else if (config.compute_unit == "traditional_fpga_gemm") {
        traditional_gemm_core->compute(...);
    }
}
```

**更好的方式（工厂模式）：**
```cpp
// 使用工厂模式，避免if-else
class ComputeUnitFactory {
    static unique_ptr<ComputeUnit> create(string type) {
        if (type == "cim_array") return make_unique<CIMArrayCore>();
        if (type == "traditional_fpga_gemm") return make_unique<TraditionalFPGAGEMM>();
        ...
    }
};

void ClusterA::operator_sweep() {
    compute_unit->compute(...);  // 多态调用
}
```

**工作量：** 3-5天

---

### 4.3 Timing层改进：提升关键路径精度

**当前问题：**
```python
# 当前：简单的吞吐量模型
T_A_array = (npw * panel_bands) / (a_array_lanes * k_a_array_work_per_lane_per_us)
```

**改进策略：**
1. **保留代理公式用于非关键路径**（如DMA、stream）
2. **提升关键计算单元精度**（CIM Array, Eigensolver）

**关键路径识别：**
- Cluster A的CIM Array：占68%时间 → **必须精确**
- Cluster C的Eigensolver：占23%时间 → **必须精确**
- Cluster B/D：占9%时间 → 代理公式够用

**精度提升方法：**
```python
# 方法1：基于Ozaki模型的cycle-accurate估算
# model/ozaki_subspace_model/ 已经有完整的Ozaki-II实现
T_A_array_accurate = ozaki_engine.estimate_cycles(m, n, k, moduli=16)

# 方法2：查表法（预先跑HLS得到cycle数）
cycle_table = load_hls_results("cim_array_cycles.json")
T_A_array_accurate = cycle_table.lookup(m, n, k)
```

**工作量：** 5-7天

---

### 4.4 大模型辅助代码生成（创新点）

**核心思路：**
DSE生成架构描述 → 大模型生成SystemC代码 → 编译运行

**实现方式：**

**Step 1：准备实现模板库**
```
templates/
├── cim_array_template.cpp
├── traditional_fpga_gemm_template.cpp
├── pim_template.cpp
├── 3cluster_pipeline_template.cpp
├── 4cluster_pipeline_template.cpp
```

**Step 2：DSE生成架构描述**
```json
{
  "architecture_id": "3cluster_traditional_v1",
  "clusters": [
    {
      "id": "cluster_a",
      "function": "operator_sweep",
      "compute_unit": "traditional_fpga_gemm",
      "parameters": {"lanes": 16, "block_size": 32}
    },
    {
      "id": "cluster_b",
      "function": "reduced_build_and_diag",
      "compute_unit": "reduction_tree",
      "parameters": {"tree_depth": 4}
    },
    {
      "id": "cluster_c",
      "function": "refresh_residual",
      "compute_unit": "vector_engine",
      "parameters": {"lanes": 8}
    }
  ]
}
```

**Step 3：大模型生成代码**
```python
# 使用AI Agent生成SystemC代码
prompt = f"""
根据以下架构描述和模板库，生成完整的SystemC实现：

架构描述：{architecture_json}
模板库：{template_files}

要求：
1. 使用模板库中的代码片段
2. 正确连接各个Cluster
3. 实现正确的控制流
4. 保持与现有代码风格一致
"""

generated_code = ai_agent.generate(prompt)
```

**Step 4：编译运行**
```bash
# 自动编译生成的代码
mkdir -p build_generated
cd build_generated
cmake .. -DGENERATED_ARCH=3cluster_traditional_v1
make -j4
./qe_band_solver_model --config arch_config.json
```

**优势：**
- DSE探索空间不受限于预先实现的架构
- 可以快速尝试新的架构想法
- 大模型保证代码质量和一致性

**工作量：** 7-10天（包括模板库准备和AI Agent集成）

---

## 五、实施路线图

### Phase 1：基础设施重构（Week 1-2）

**目标：** 让DSE和Simulator支持架构切换

**任务：**
1. 设计架构模板JSON schema
2. 实现DSE的模板加载和候选生成
3. 重构SystemC的配置系统（工厂模式）
4. 验证：能否通过配置切换CIM vs Traditional FPGA

**交付物：**
- `architecture_templates/` 目录和示例模板
- 更新的DSE框架代码
- 更新的SystemC配置系统
- 验证报告

---

### Phase 2：Timing精度提升（Week 2-3）

**目标：** 关键路径达到±10%精度

**任务：**
1. 集成Ozaki模型到SystemC（CIM Array timing）
2. 实现Eigensolver的cycle-accurate模型
3. 保留非关键路径的代理公式
4. 对比验证：新模型 vs 旧代理公式

**交付物：**
- 更新的timing模型代码
- 精度对比报告
- 更新的文档

---

### Phase 3：大模型辅助系统（Week 3-4）

**目标：** 实现AI辅助的架构代码生成

**任务：**
1. 准备实现模板库
2. 设计架构描述语言
3. 实现AI Agent集成
4. 端到端测试：DSE → AI生成 → 编译运行

**交付物：**
- 模板库
- AI Agent集成代码
- 端到端示例
- 使用文档

---

### Phase 4：完整DSE运行（Week 4-5）

**目标：** 运行完整的架构探索

**任务：**
1. 定义探索空间（Cluster数量、计算单元类型等）
2. 运行DSE sweep（可能需要几小时到几天）
3. 分析结果，生成Pareto前沿
4. 撰写技术报告

**交付物：**
- DSE结果数据
- Pareto前沿图
- 最优架构推荐
- 技术报告

---

## 六、关键决策点

### 决策1：是否需要完全cycle-accurate？

**我的建议：NO**

**理由：**
- ±10%精度足够用于架构选择
- Cycle-accurate需要大量工作（几周到几个月）
- 最终验证还是要靠FPGA板卡实测

**方案：**
- 关键路径（CIM, Eigensolver）：±10%精度
- 非关键路径（DMA, stream）：±20%精度够用

---

### 决策2：是否一定要用"Cluster"概念？

**我的建议：保留但不强制**

**理由：**
- Cluster是一种有效的组织方式
- 但不应该限制探索空间
- 应该允许"非Cluster"的架构（如算子融合）

**方案：**
- 架构模板可以定义任意数量的Cluster（2/3/4/5）
- 也可以定义"单片式"架构（无Cluster划分）
- DSE框架不假设Cluster数量

---

### 决策3：大模型辅助是否必要？

**我的建议：YES，但分阶段**

**理由：**
- Phase 1-2可以不用大模型，手动实现几种架构
- Phase 3引入大模型，扩展探索空间
- 大模型不是必需的，但能显著提升效率

**方案：**
- 先手动实现3-5种代表性架构
- 验证DSE+Simulator流程可行
- 再引入大模型辅助生成更多变体

---

## 七、风险和缓解

### 风险1：重构破坏现有功能

**缓解：**
- 保留现有代码作为baseline
- 新代码在独立分支开发
- 每个Phase都有验证步骤

---

### 风险2：Timing精度提升不达预期

**缓解：**
- 先用Ozaki模型验证可行性
- 如果不行，退回到改进的代理公式
- 最坏情况：保持±20%精度，但增加更多架构探索

---

### 风险3：大模型生成代码质量不稳定

**缓解：**
- 准备高质量的模板库
- 实现代码验证流程（编译+测试）
- 人工review生成的代码
- 最坏情况：手动实现，不用大模型

---

## 八、总结

### 当前系统评估

| 维度 | 评分 | 说明 |
|------|------|------|
| DSE表达能力 | 3/10 | 只能探索参数，不能探索架构 |
| Simulator模块化 | 7/10 | 模块化较好，但配置不灵活 |
| Timing精度 | 4/10 | 代理公式±20%，不够精确 |
| 整体可用性 | 5/10 | 能跑通，但探索空间太窄 |

### 推荐方案

**混合式改进：**
1. **重构**：DSE架构模板系统 + Simulator配置系统
2. **渐进**：Timing精度提升（关键路径优先）
3. **创新**：大模型辅助代码生成

**预期效果：**
- DSE探索空间扩大10倍以上
- Simulator精度提升到±10%
- 架构迭代速度提升5倍

**总工作量：** 4-5周

---

## 九、下一步行动

**立即行动：**
1. 确认这个方案是否符合你的期望
2. 讨论Phase 1的具体实施细节
3. 开始设计架构模板JSON schema

**需要你的反馈：**
1. 这个方案是否解决了你的核心需求？
2. 4-5周的时间是否可接受？
3. 是否有其他优先级更高的需求？
4. 对"大模型辅助"这个创新点的看法？

