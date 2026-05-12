# CPU+FPGA协同模拟设计方案 (v0)

**日期：** 2026-04-20  
**目标：** 完整模拟QE计算全流程，包括CPU执行的Phase A/C/D和FPGA加速的Phase B (c_bands)

---

## 1. 需求分析

### 1.1 当前问题

**现状：** SystemC模拟器只模拟FPGA部分（c_bands子系统），CPU部分被简化为固定延迟：
```cpp
// host_scf.cpp: 当前简化实现
for (int iter = 1; iter <= max_scf_iters; ++iter) {
  sc_core::wait(8.0, SC_NS);  // Phase A: rho->Veff (简化)
  auto completion = fpga_.execute_iteration(request);  // Phase B: c_bands (完整模拟)
  sc_core::wait(6.0, SC_NS);  // Phase C/D: sum_band + mix_rho (简化)
}
```

**问题：**
- 无法预估CPU部分的真实性能
- 无法评估CPU-FPGA数据传输开销
- 无法分析CPU-FPGA负载均衡
- 无法验证异构系统的端到端正确性

### 1.2 目标

**完整的异构系统模拟器：**
```
┌─────────────────────────────────────────────────────────────┐
│                    QE Full-Flow Simulator                    │
├─────────────────────────────────────────────────────────────┤
│  CPU Simulator (gem5 or Functional Model)                   │
│    - Phase A: rho->Veff (v_of_rho, newd)                    │
│    - Phase C: sum_band (电荷密度计算)                        │
│    - Phase D: mix_rho (Broyden混合)                         │
│    - SCF收敛判断                                             │
├─────────────────────────────────────────────────────────────┤
│  FPGA Simulator (SystemC - 已完成)                          │
│    - Phase B: c_bands (h_psi, s_psi, diag, refresh)        │
│    - 4-Cluster流水线                                         │
│    - CIM Array Core                                          │
├─────────────────────────────────────────────────────────────┤
│  Co-simulation Interface                                     │
│    - PCIe/DMA模型                                            │
│    - 数据传输timing                                          │
│    - 同步机制                                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 架构方案对比

### 2.1 方案A：gem5 + SystemC协同模拟（高精度）

**架构：**
```
┌──────────────────────┐         ┌──────────────────────┐
│   gem5 (CPU侧)       │         │  SystemC (FPGA侧)    │
│                      │         │                      │
│  - QE代码执行        │◄───────►│  - 4-Cluster流水线   │
│  - v_of_rho          │  TLM    │  - CIM Array Core    │
│  - sum_band          │  2.0    │  - Timing Model      │
│  - mix_rho           │         │                      │
│  - Cache/Memory模型  │         │  - DMA Controller    │
└──────────────────────┘         └──────────────────────┘
         ▲                                  ▲
         │                                  │
         └──────────────┬───────────────────┘
                        │
                ┌───────▼────────┐
                │  PCIe/DMA模型  │
                │  - 带宽模型    │
                │  - 延迟模型    │
                │  - 队列模型    │
                └────────────────┘
```

**优点：**
- ✅ 最高精度：cycle-accurate CPU + cycle-accurate FPGA
- ✅ 真实QE代码执行：直接运行QE二进制
- ✅ Cache/Memory层次建模：准确预估内存瓶颈
- ✅ 多核并行建模：评估CPU并行效率

**缺点：**
- ❌ 实现复杂度极高：gem5-SystemC接口需要大量工程
- ❌ 仿真速度极慢：gem5本身就很慢（~1 MIPS），加上SystemC更慢
- ❌ 调试困难：两个模拟器的时间同步、状态一致性
- ❌ 工程量巨大：预计需要3-6个月

**适用场景：**
- 需要发表顶级系统会议论文（ISCA, MICRO, HPCA）
- 需要精确评估Cache miss、TLB miss、分支预测等微架构细节
- 有充足的时间和人力资源

### 2.2 方案B：Functional CPU Model + SystemC（中等精度，推荐）

**架构：**
```
┌──────────────────────────────────────────────────────────┐
│         Unified SystemC Simulator                         │
├──────────────────────────────────────────────────────────┤
│  HostCPU Module (Functional + Timing Annotation)         │
│    - QE Phase A/C/D的功能模型                            │
│    - 基于真实trace的timing标注                           │
│    - 简化的内存访问模型                                  │
├──────────────────────────────────────────────────────────┤
│  FPGA Module (已有的SystemC模型)                         │
│    - 4-Cluster流水线                                     │
│    - CIM Array Core                                      │
│    - Cycle-accurate timing                               │
├──────────────────────────────────────────────────────────┤
│  Interconnect Module                                      │
│    - PCIe/DMA timing model                               │
│    - 带宽/延迟/队列模型                                  │
└──────────────────────────────────────────────────────────┘
```

**优点：**
- ✅ 实现复杂度适中：在现有SystemC框架内扩展
- ✅ 仿真速度快：比gem5快100-1000倍
- ✅ 调试友好：统一的SystemC时间模型
- ✅ 工程量可控：预计2-4周完成

**缺点：**
- ⚠️ CPU精度有限：不建模Cache/TLB/分支预测等微架构
- ⚠️ 依赖真实trace：需要真实QE trace来标注timing
- ⚠️ 不适合CPU优化：无法评估CPU侧的优化效果

**适用场景：**
- 当前项目（DFT加速系统原型验证）
- 需要快速迭代架构设计
- 主要关注FPGA加速效果，CPU是baseline

### 2.3 方案C：Trace-Driven Replay（低精度，最快）

**架构：**
```
┌──────────────────────────────────────────────────────────┐
│         Trace-Driven Simulator                            │
├──────────────────────────────────────────────────────────┤
│  Trace Player                                             │
│    - 读取真实QE trace                                     │
│    - 重放Phase A/C/D的timing                             │
│    - 注入Phase B的FPGA模拟结果                           │
├──────────────────────────────────────────────────────────┤
│  FPGA Module (已有的SystemC模型)                         │
│    - 4-Cluster流水线                                     │
│    - CIM Array Core                                      │
└──────────────────────────────────────────────────────────┘
```

**优点：**
- ✅ 实现最简单：只需要trace读取和注入逻辑
- ✅ 仿真速度最快：直接重放trace
- ✅ 工程量最小：1-2周完成

**缺点：**
- ❌ 精度最低：完全依赖trace，无法探索新配置
- ❌ 不支持架构探索：trace固定了CPU行为
- ❌ 无法评估CPU-FPGA交互：trace中没有FPGA

**适用场景：**
- 快速验证概念
- 生成初步的性能数据
- 不需要架构探索

---

## 3. 推荐方案：Functional CPU Model + SystemC

### 3.1 设计原则

1. **在现有SystemC框架内扩展** - 避免引入gem5的复杂性
2. **基于真实trace标注timing** - 保证CPU部分的timing准确性
3. **保持模块化** - CPU/FPGA/Interconnect独立建模
4. **支持架构探索** - 可以调整CPU-FPGA分工、DMA策略等

### 3.2 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                  DFTHybridSystem (顶层)                      │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐  ┌────────────────┐  ┌──────────────┐
│  HostCPU      │  │  Interconnect  │  │  FPGAChip    │
│  (新增)       │  │  (新增)        │  │  (已有)      │
└───────────────┘  └────────────────┘  └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐  ┌────────────────┐  ┌──────────────┐
│ Phase A/C/D   │  │ PCIe/DMA Model │  │ ChipTop      │
│ Functional    │  │ - Bandwidth    │  │ - 4-Cluster  │
│ Model         │  │ - Latency      │  │ - CIM Core   │
│               │  │ - Queue        │  │              │
└───────────────┘  └────────────────┘  └──────────────┘
```

### 3.3 模块设计

#### 3.3.1 HostCPU模块（新增）

**职责：**
- 执行Phase A (rho->Veff)
- 执行Phase C (sum_band)
- 执行Phase D (mix_rho)
- SCF收敛判断

**实现方式：**
```cpp
class HostCPU : public sc_core::sc_module {
 public:
  // Phase A: rho -> Veff
  PhaseAResult execute_phase_a(const SCFState& state) {
    // 1. 从trace获取timing标注
    auto timing = trace_db_.get_phase_a_timing(state.workload_id, state.iter);
    
    // 2. 功能模拟（简化）
    PhaseAResult result;
    result.veff = compute_veff_functional(state.rho);  // 简化计算
    
    // 3. Timing标注
    sc_core::wait(timing.v_of_rho_ns, sc_core::SC_NS);
    sc_core::wait(timing.newd_ns, sc_core::SC_NS);
    
    return result;
  }
  
  // Phase C: sum_band
  PhaseCResult execute_phase_c(const PhaseBResult& bands) {
    auto timing = trace_db_.get_phase_c_timing(...);
    
    PhaseCResult result;
    result.rho_out = compute_rho_from_bands(bands);  // 简化计算
    
    sc_core::wait(timing.sum_band_ns, sc_core::SC_NS);
    return result;
  }
  
  // Phase D: mix_rho
  PhaseDResult execute_phase_d(const SCFState& state, 
                                const PhaseCResult& rho_out) {
    auto timing = trace_db_.get_phase_d_timing(...);
    
    PhaseDResult result;
    result.rho_mixed = broyden_mix(state.rho, rho_out.rho_out);  // 简化
    result.converged = check_convergence(state, rho_out);
    
    sc_core::wait(timing.mix_rho_ns, sc_core::SC_NS);
    return result;
  }
  
 private:
  TraceDatabase trace_db_;  // 存储真实QE trace的timing数据
};
```

**Timing标注来源：**
```json
// trace_timing_database.json
{
  "workload": "si8_pbe_nc",
  "iterations": [
    {
      "iter": 1,
      "phase_a": {
        "v_of_rho_ns": 5000.0,
        "newd_ns": 3000.0,
        "total_ns": 8000.0
      },
      "phase_c": {
        "sum_band_ns": 4000.0
      },
      "phase_d": {
        "mix_rho_ns": 2000.0
      }
    }
  ]
}
```

#### 3.3.2 Interconnect模块（新增）

**职责：**
- 建模PCIe/DMA数据传输
- 建模传输延迟和带宽限制
- 建模队列和拥塞

**实现方式：**
```cpp
class Interconnect : public sc_core::sc_module {
 public:
  // DMA传输模型
  void dma_transfer(const DMARequest& req) {
    // 1. 队列延迟
    double queue_delay_ns = dma_queue_.get_delay(req.size_bytes);
    sc_core::wait(queue_delay_ns, sc_core::SC_NS);
    
    // 2. 传输延迟 = 固定延迟 + 带宽限制
    double transfer_ns = pcie_latency_ns_ + 
                         (req.size_bytes * 8.0) / pcie_bandwidth_gbps_;
    sc_core::wait(transfer_ns, sc_core::SC_NS);
    
    // 3. 更新统计
    stats_.total_dma_bytes += req.size_bytes;
    stats_.total_dma_transfers += 1;
  }
  
 private:
  double pcie_latency_ns_ = 500.0;      // PCIe固定延迟
  double pcie_bandwidth_gbps_ = 16.0;   // PCIe Gen3 x16
  DMAQueue dma_queue_;
  InterconnectStats stats_;
};
```

**PCIe模型参数：**
| 参数 | PCIe Gen3 x16 | PCIe Gen4 x16 | PCIe Gen5 x16 |
|------|---------------|---------------|---------------|
| 带宽 | 16 GB/s | 32 GB/s | 64 GB/s |
| 延迟 | ~500 ns | ~400 ns | ~300 ns |

#### 3.3.3 FPGAChip模块（已有，无需修改）

**当前实现：**
- ChipTop
- ClusterGraphExecutor
- 4-Cluster流水线
- CIM Array Core

**接口保持不变：**
```cpp
class FPGAChip : public sc_core::sc_module {
 public:
  PhaseBResult execute_c_bands(const PhaseBRequest& req);
};
```

### 3.4 完整执行流程

```cpp
// dft_hybrid_system.cpp: 完整SCF循环
SCFRunReport DFTHybridSystem::run_full_scf() {
  SCFState state = initialize_state();
  
  for (int iter = 1; iter <= max_iters; ++iter) {
    // Phase A: CPU执行 rho->Veff
    auto phase_a_result = host_cpu_.execute_phase_a(state);
    
    // 准备FPGA输入数据
    PhaseBRequest fpga_req = prepare_fpga_request(state, phase_a_result);
    
    // DMA: CPU -> FPGA
    interconnect_.dma_transfer({
      .direction = HOST_TO_DEVICE,
      .size_bytes = fpga_req.data_size_bytes
    });
    
    // Phase B: FPGA执行 c_bands
    auto phase_b_result = fpga_chip_.execute_c_bands(fpga_req);
    
    // DMA: FPGA -> CPU
    interconnect_.dma_transfer({
      .direction = DEVICE_TO_HOST,
      .size_bytes = phase_b_result.data_size_bytes
    });
    
    // Phase C: CPU执行 sum_band
    auto phase_c_result = host_cpu_.execute_phase_c(phase_b_result);
    
    // Phase D: CPU执行 mix_rho
    auto phase_d_result = host_cpu_.execute_phase_d(state, phase_c_result);
    
    // 更新状态
    state.rho = phase_d_result.rho_mixed;
    state.converged = phase_d_result.converged;
    
    if (state.converged) break;
  }
  
  return generate_report(state);
}
```

---

## 4. 实施计划

### 4.1 Phase 1: Trace Database构建（Week 1）

**目标：** 从真实QE trace提取timing数据

**任务：**
1. 分析现有QE trace文件（`docs/benchmarks/archive/results/qe_*_trace.csv`）
2. 提取Phase A/C/D的timing数据
3. 构建TraceDatabase类和JSON格式
4. 验证timing数据的完整性

**输出：**
- `trace_timing_database.json` - 5个workloads的timing数据
- `trace_database.hpp/cpp` - TraceDatabase类实现

### 4.2 Phase 2: HostCPU模块实现（Week 2）

**目标：** 实现CPU侧的功能模型和timing标注

**任务：**
1. 创建HostCPU模块框架
2. 实现Phase A/C/D的功能模型（简化版）
3. 集成TraceDatabase进行timing标注
4. 单元测试：验证timing准确性

**输出：**
- `host_cpu.hpp/cpp` - HostCPU模块
- `test_host_cpu.cpp` - 单元测试

### 4.3 Phase 3: Interconnect模块实现（Week 2）

**目标：** 实现PCIe/DMA模型

**任务：**
1. 创建Interconnect模块框架
2. 实现DMA传输timing模型
3. 实现队列和拥塞模型
4. 参数化配置（PCIe Gen3/4/5）

**输出：**
- `interconnect.hpp/cpp` - Interconnect模块
- `pcie_config.json` - PCIe配置参数

### 4.4 Phase 4: 系统集成（Week 3）

**目标：** 集成CPU/FPGA/Interconnect模块

**任务：**
1. 修改DFTHybridSystem顶层
2. 实现完整的SCF循环
3. 端到端测试：运行5个workloads
4. 验证timing一致性

**输出：**
- 修改后的`dft_hybrid_system.cpp`
- 端到端测试报告

### 4.5 Phase 5: 验证和优化（Week 4）

**目标：** 验证模拟器准确性，优化性能

**任务：**
1. 对比模拟器结果 vs 真实QE trace
2. 分析误差来源
3. 优化仿真速度
4. 生成性能报告

**输出：**
- 验证报告：模拟器 vs 真实QE
- 性能优化报告
- 用户文档

---

## 5. 预期成果

### 5.1 功能成果

**完整的异构系统模拟器：**
- ✅ CPU侧：Phase A/C/D功能模型 + timing标注
- ✅ FPGA侧：4-Cluster流水线 + CIM Core（已有）
- ✅ Interconnect：PCIe/DMA模型
- ✅ 端到端：完整SCF循环模拟

### 5.2 性能预估能力

**可以回答的问题：**
1. CPU+FPGA端到端性能是多少？
2. PCIe带宽是否成为瓶颈？
3. CPU-FPGA负载均衡如何？
4. 不同PCIe配置（Gen3/4/5）的影响？
5. DMA传输策略的优化空间？

**示例输出：**
```
=== Full-System Performance Report ===
Workload: si8_pbe_nc
Total SCF Time: 18.43 seconds

Phase Breakdown:
  Phase A (rho->Veff):  2.50s (13.6%)  [CPU]
  Phase B (c_bands):    3.43s (18.6%)  [FPGA]
  Phase C (sum_band):   1.20s (6.5%)   [CPU]
  Phase D (mix_rho):    0.80s (4.3%)   [CPU]
  DMA Overhead:         0.50s (2.7%)   [PCIe]
  Other:                10.0s (54.3%)  [CPU]

Speedup Analysis:
  CPU-only baseline:    100.0s
  CPU+FPGA:             18.43s
  End-to-end speedup:   5.43x

Bottleneck Analysis:
  - c_bands已加速24.75x，不再是瓶颈
  - Phase A (rho->Veff)成为新瓶颈（13.6%）
  - PCIe带宽充足，DMA开销仅2.7%
```

### 5.3 架构探索能力

**可以探索的设计空间：**
1. CPU-FPGA分工：哪些操作放CPU，哪些放FPGA？
2. PCIe配置：Gen3 vs Gen4 vs Gen5？
3. DMA策略：批量传输 vs 流式传输？
4. 数据布局：如何减少DMA次数？
5. 流水线优化：CPU-FPGA并行执行？

---

## 6. 与现有工作的关系

### 6.1 复用现有成果

**Phase 1-3已完成的工作：**
- ✅ SystemC FPGA模拟器（4-Cluster + CIM）
- ✅ 架构模板系统（JSON配置驱动）
- ✅ 真实QE trace数据（5个workloads）
- ✅ DSE框架（架构探索工具链）

**本方案的增量工作：**
- 新增HostCPU模块（~500行）
- 新增Interconnect模块（~300行）
- 修改DFTHybridSystem顶层（~200行）
- TraceDatabase工具（~400行）
- **总计：~1400行新增代码**

### 6.2 与DSE框架集成

**当前DSE流程：**
```
架构模板 → SystemC配置 → 运行FPGA模拟器 → 收集性能数据
```

**扩展后的DSE流程：**
```
架构模板 → SystemC配置 → 运行完整系统模拟器 → 收集端到端性能数据
                              ↓
                    CPU模型 + FPGA模型 + Interconnect模型
```

**无需修改：**
- Phase 1的架构模板系统
- Phase 1的候选生成器
- Phase 1的DSE sweep脚本

**需要修改：**
- `template_to_systemc_config.py`：添加CPU和Interconnect配置
- `run_systemc_architecture_family_dse_sweep.py`：调用新的模拟器入口

---

## 7. 风险和缓解

### 7.1 风险1：Trace数据不完整

**风险：** 现有QE trace可能缺少Phase A/C/D的详细timing

**缓解：**
1. 重新运行QE并采集更详细的trace
2. 使用粗粒度timing（每个phase一个总时间）
3. 从QE源码分析估算timing

### 7.2 风险2：功能模型不准确

**风险：** 简化的功能模型可能导致数值误差

**缓解：**
1. 只关注timing，不关注数值精度
2. 用真实QE结果验证关键数值（能量、收敛性）
3. 标注"功能模型"的精度限制

### 7.3 风险3：仿真速度慢

**风险：** 完整系统模拟可能比当前慢

**缓解：**
1. CPU部分使用功能模型，不做cycle-accurate
2. 优化SystemC事件调度
3. 支持快速模式（跳过详细logging）

---

## 8. 总结

### 8.1 推荐方案

**Functional CPU Model + SystemC（方案B）**

**理由：**
1. 实现复杂度适中（2-4周）
2. 仿真速度快（比gem5快100-1000倍）
3. 在现有SystemC框架内扩展（无需引入gem5）
4. 满足当前项目需求（端到端性能预估）

### 8.2 不推荐gem5方案的原因

1. **工程量过大：** 3-6个月，超出当前项目时间预算
2. **仿真速度慢：** gem5本身就很慢，不适合DSE
3. **收益有限：** 当前项目不需要CPU微架构细节
4. **维护成本高：** gem5-SystemC接口复杂，难以维护

### 8.3 下一步行动

**如果同意方案B，下一步：**
1. 分析现有QE trace，确认timing数据完整性
2. 创建TraceDatabase原型
3. 实现HostCPU模块原型
4. 端到端测试一个workload

**预计时间：** 2-4周完成完整实现

---

## 参考文档

- `docs/architecture/qe_ic_full_flow_simulator_contract_v0.md` - 模拟器契约
- `docs/architecture/system_design_master_spec_v0.md` - 系统设计规范
- `docs/benchmarks/qe_cpu_speedup_envelope_20260402.md` - 加速比计算
- `docs/overview/archive/docs/overview/archive/phase3_complete_summary.md` - Phase 3完成总结
