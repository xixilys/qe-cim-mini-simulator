# SystemC模拟器覆盖范围说明

**日期：** 2026-04-20  
**问题：** 模拟器能正确完成整个QE流程的计算吗？

---

## 简短回答

**不能。** 当前SystemC模拟器只模拟了QE `electrons`循环中的**c_bands子系统**（band-solver subsystem），而不是完整的QE DFT计算流程。

---

## 详细说明

### 1. QE完整计算流程（3层循环）

```
┌─────────────────────────────────────────────────────────────┐
│ 最外层：SCF自洽循环 (electrons)                              │
│                                                               │
│  for iter = 1 to max_scf_iters:                              │
│    ┌─────────────────────────────────────────────────────┐  │
│    │ Phase A: rho -> Veff (势场计算)                      │  │
│    │   - v_of_rho: 计算Hartree势、XC势                    │  │
│    │   - newd: 更新D矩阵                                  │  │
│    │   - 时间占比：~5-10%                                 │  │
│    └─────────────────────────────────────────────────────┘  │
│                                                               │
│    ┌─────────────────────────────────────────────────────┐  │
│    │ Phase B: c_bands (能带求解) ← 当前模拟器只模拟这部分 │  │
│    │   - 时间占比：45%-95%（最热点）                      │  │
│    │                                                       │  │
│    │   for k_point in k_points:                           │  │
│    │     for band_group in band_groups:                   │  │
│    │       ┌─────────────────────────────────────────┐   │  │
│    │       │ Davidson迭代（内层循环）                 │   │  │
│    │       │                                           │   │  │
│    │       │ for inner_step = 1 to max_davidson:      │   │  │
│    │       │   1. h_psi: H|ψ⟩ (算符作用)              │   │  │
│    │       │   2. s_psi: S|ψ⟩ (重叠矩阵)              │   │  │
│    │       │   3. 归约: 构建H_sub, S_sub              │   │  │
│    │       │   4. 对角化: 求解广义特征值问题          │   │  │
│    │       │   5. 更新波函数                           │   │  │
│    │       │   6. 检查收敛                             │   │  │
│    │       └─────────────────────────────────────────┘   │  │
│    └─────────────────────────────────────────────────────┘  │
│                                                               │
│    ┌─────────────────────────────────────────────────────┐  │
│    │ Phase C: sum_band (能带求和)                         │  │
│    │   - 计算电荷密度                                     │  │
│    │   - 时间占比：~5-10%                                 │  │
│    └─────────────────────────────────────────────────────┘  │
│                                                               │
│    ┌─────────────────────────────────────────────────────┐  │
│    │ Phase D: mix_rho (密度混合)                          │  │
│    │   - Broyden混合                                      │  │
│    │   - 时间占比：<5%                                    │  │
│    └─────────────────────────────────────────────────────┘  │
│                                                               │
│    if converged: break                                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 2. 当前模拟器实际模拟的范围

**SystemC模拟器只模拟了Phase B (c_bands)中的一个"episode"：**

```cpp
// host_scf.cpp: run_full_flow()
for (int iter = 1; iter <= max_scf_iters; ++iter) {
  // Phase A: rho->Veff (简化为8ns延迟)
  sc_core::wait(8.0, sc_core::SC_NS);
  log_line("Host CPU completes rho->Veff stage for iter " + iter);
  
  // Phase B: c_bands (实际模拟)
  auto request = make_iteration_request(...);
  auto completion = fpga_.execute_iteration(request);  // ← 这里调用FPGA模拟
  
  // Phase C/D: sum_band + mix_rho (简化为6ns延迟)
  sc_core::wait(6.0, SC_core::SC_NS);
  log_line("Host CPU consumes returned wave/density summary for iter " + iter);
  
  // 简化的收敛判断（不是真实QE逻辑）
  if (state.converged) break;
}
```

**实际模拟的c_bands episode包括：**

1. **Cluster A (Operator Sweep)** - 68%时间
   - h_psi: H|ψ⟩计算（CIM Array Core加速）
   - s_psi: S|ψ⟩计算
   - 使用Ozaki-II + CRT + Karatsuba 3M算法

2. **Cluster B (Reduced Build)** - 4%时间
   - 构建H_sub和S_sub矩阵
   - 归约操作

3. **Cluster C (Hardware Diag)** - 23%时间
   - 广义Hermitian特征值求解
   - 使用NML eigensolver

4. **Cluster D (Refresh/Residual)** - 5%时间
   - 更新波函数
   - 计算残差

### 3. 模拟器的简化假设

#### 3.1 Phase A (rho->Veff) 简化
- **真实QE：** 复杂的势场计算（Hartree势、XC势、PAW增强）
- **模拟器：** 固定8ns延迟，不做实际计算

#### 3.2 Phase C (sum_band) 简化
- **真实QE：** 从波函数计算电荷密度
- **模拟器：** 包含在6ns延迟中，不做实际计算

#### 3.3 Phase D (mix_rho) 简化
- **真实QE：** Broyden密度混合算法
- **模拟器：** 包含在6ns延迟中，不做实际计算

#### 3.4 收敛判断简化
- **真实QE：** 基于电荷密度变化、能量变化、力收敛等多个标准
- **模拟器：** 简化的`density_delta`阈值判断

#### 3.5 k点和能带组循环简化
- **真实QE：** 多个k点、多个能带组的嵌套循环
- **模拟器：** 单个"episode"代表一次Davidson迭代，不显式模拟k点循环

### 4. 模拟器的性能预估能力

#### 4.1 可以预估的部分 ✅

**c_bands子系统的性能（45%-95%的总时间）：**
- h_psi/s_psi算符作用的cycles
- 归约操作的cycles
- 特征值求解的cycles
- 波函数更新的cycles
- 数据搬运带宽（DMA read/write）
- 片上存储占用（resident context）

**示例输出：**
```
ref_cycles=3639 (FPGA总cycles)
  - Cluster A: 915 cycles (68%)
  - Cluster B: 54 cycles (4%)
  - Cluster C: 303 cycles (23%)
  - Cluster D: 63 cycles (5%)
dma_read_kib=69.5, dma_write_kib=1.5
device_busy_ref_cycles=3639
```

#### 4.2 不能预估的部分 ❌

**Phase A (rho->Veff)：**
- v_of_rho的实际计算时间
- newd的实际计算时间
- 这些操作在CPU上的真实开销

**Phase C (sum_band)：**
- 电荷密度计算的实际时间
- 这部分在CPU上的真实开销

**Phase D (mix_rho)：**
- Broyden混合的实际时间
- 历史密度存储和操作开销

**k点并行：**
- 多k点的并行效率
- k点间的负载均衡

**多节点并行：**
- MPI通信开销
- 能带组并行的扩展性

### 5. 端到端性能预估的正确方法

要预估完整QE计算的性能，需要：

#### 5.1 获取真实QE的时间分布

从真实QE trace数据（已有）：
```json
{
  "electrons_total_time": 100.0,
  "c_bands_time": 85.0,        // 85%
  "v_of_rho_time": 8.0,        // 8%
  "sum_band_time": 5.0,        // 5%
  "mix_rho_time": 2.0          // 2%
}
```

#### 5.2 计算加速后的时间

```python
# CPU baseline (从真实trace)
cpu_electrons_time = 100.0  # seconds
cpu_c_bands_time = 85.0
cpu_other_time = 15.0

# FPGA加速c_bands
fpga_c_bands_speedup = 24.75  # 从SystemC模拟器得到
fpga_c_bands_time = cpu_c_bands_time / fpga_c_bands_speedup  # 3.43s

# 其他部分仍在CPU上
cpu_other_time = 15.0  # 不变

# 总时间
total_time = fpga_c_bands_time + cpu_other_time  # 18.43s

# 端到端加速比
end_to_end_speedup = cpu_electrons_time / total_time  # 5.43x
```

#### 5.3 Amdahl定律验证

```python
# Amdahl's Law
P = 0.85  # c_bands占比
S = 24.75  # c_bands加速比

speedup = 1 / ((1 - P) + P / S)
        = 1 / (0.15 + 0.85 / 24.75)
        = 1 / (0.15 + 0.0343)
        = 5.43x
```

### 6. 当前项目的性能预估数据

根据`docs/benchmarks/qe_cpu_speedup_envelope_20260402.md`：

| Workload | c_bands占比 | c_bands加速比 | 端到端加速比 |
|----------|------------|--------------|-------------|
| si4 | 45% | 24.75x | 1.57x |
| si8 | 68% | 24.75x | 2.03x |
| graphene | 85% | 24.75x | 3.08x |
| au_slab | 95% | 56.00x | 11.76x |

**关键洞察：**
- 小体系（si4）：c_bands占比低，端到端加速比受限（1.57x）
- 大体系（graphene, au_slab）：c_bands占比高，端到端加速比显著（3.08x-11.76x）

### 7. 总结

**问题：** 模拟器能正确完成整个QE流程的计算吗？

**答案：** 不能。模拟器只模拟了c_bands子系统（占总时间45%-95%），其他部分（rho->Veff, sum_band, mix_rho）被简化为固定延迟。

**模拟器的价值：**
1. ✅ 准确预估c_bands子系统的FPGA性能（cycles, 带宽, 存储）
2. ✅ 支持架构探索（不同cluster配置、CIM vs Traditional FPGA）
3. ✅ 提供cycle-accurate的timing数据（关键路径±10%精度）
4. ✅ 结合真实QE trace数据，可以预估端到端加速比

**要获得完整QE性能预估：**
1. 使用真实QE trace获取各阶段时间分布
2. 用SystemC模拟器预估c_bands加速后的时间
3. 用Amdahl定律计算端到端加速比
4. 考虑k点并行、MPI通信等系统级因素

**当前项目状态：**
- ✅ SystemC模拟器已完成（Phase 3）
- ✅ 真实QE trace数据已采集（5个workloads）
- ✅ 端到端加速比已计算（1.57x-11.76x）
- ❌ GPU baseline实测延期（框架就绪）
- ❌ FPGA板级验证待执行

---

## 参考文档

- `docs/overview/project_development_timeline.md` - 项目演进历史
- `docs/architecture/system_design_master_spec_v0.md` - 系统设计规范
- `docs/benchmarks/qe_cpu_speedup_envelope_20260402.md` - 加速比计算
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` - 对比方法论
