# 分阶段实施计划：SystemC + SCF + GPU Baseline

## 原则：不使用Mock，真实实现

---

## 阶段1: SystemC真实接入（最高优先级）

### 目标
替换 `_project_l3()` 的projection，改为真实调用SystemC可执行文件

### 实现步骤
1. **解析SystemC文本输出**
   - SystemC输出文本日志（非JSON）
   - 需要正则表达式提取关键metrics
   - 关键字段：
     - `ref_cycles=963` - 参考周期
     - `device_busy_ref_cycles=963` - 设备忙碌周期
     - `invocations=3` - 调用次数
     - `move_kib=215.7422` - 数据移动量
     - `convergence=max_scf_iters_reached` - 收敛状态

2. **实现SystemCBackend.run_episode()**
   - 使用subprocess调用 `qe_band_solver_model`
   - 传递环境变量：QEBS_ARCH_FAMILY, QEBS_MAX_SCF_ITERS等
   - 捕获stdout并解析metrics
   - 转换为Layer 3的EvaluationResult格式

3. **修改Orchestrator**
   - `l3_mode='systemc_execution'` 时调用真实SystemC
   - 保持 `projection_only` 作为fallback

4. **验证**
   - 运行每个family (F1-F7) 的SystemC仿真
   - 验证输出metrics合理
   - 测试完整SCF循环 (QEBS_MAX_SCF_ITERS > 1)

### 工作量：中等（1-2天）

---

## 阶段2: 完整SCF循环支持

### 目标
确保SystemC能运行完整的SCF迭代（多次迭代）

### 实现步骤
1. **验证SCF循环参数**
   - QEBS_MAX_SCF_ITERS 控制迭代次数
   - 每次迭代包含：rho->Veff, h_psi, cdiaghg, refresh

2. **提取每次迭代的metrics**
   - SystemC输出包含每次迭代的详细报告
   - 需要聚合多次迭代的结果

3. **收敛检测**
   - 检查convergence状态（converged=yes/no）
   - 提取residual和energy

### 工作量：小（与阶段1一起完成）

---

## 阶段3: GPU Baseline真实测量

### 目标
获取真实的GPU性能数据，不是mock或deferred

### 实现方案选择

**方案A: PyCUDA/CuPy直接实现（推荐）**
- 使用CuPy实现h_psi (GEMM) 和 cdiaghg (对角化)
- 直接测量wall time和GFLOPS
- 优点：简单、直接、可控
- 缺点：需要CUDA代码

**方案B: QE的GPU支持**
- 检查soft/qe-7.5是否支持CUDA
- 编译QE with CUDA support
- 运行真实QE并测量c_bands时间
- 优点：最真实
- 缺点：编译复杂、可能需要大量内存

**方案C: 使用NVIDIA性能工具**
- 使用nsys/nvprof测量
- 优点：专业工具
- 缺点：需要额外安装

### 推荐：方案A（PyCUDA/CuPy）

实现步骤：
1. 安装CuPy: `pip install cupy-cuda12x`
2. 实现 `gpu_kernels.py`:
   - `h_psi_gpu(npw, nkb, m)` - 使用cupy.matmul
   - `cdiaghg_gpu(nkb, m)` - 使用cupy.linalg.eigh
3. 测量latency和throughput
4. 生成真实的GPU baseline manifest

### 工作量：中等（1-2天）

---

## 阶段4: 集成验证

### 目标
验证完整流程：L1→L2→SystemC→GPU对比

### 验证步骤
1. 运行每个family的完整3层评估
2. 对比L2 projection vs L3 SystemC结果
3. 计算MAPE（Mean Absolute Percentage Error）
4. 验证GPU baseline数据
5. 生成confidence report

### 成功标准
- SystemC成功运行所有7个family
- GPU baseline有真实测量数据
- L2 vs L3的MAPE < 20%
- 整体confidence > 95%

---

## 依赖关系

```
阶段1 (SystemC接入)
    ↓
阶段2 (SCF循环) [依赖阶段1]
    ↓
阶段4 (集成验证) [依赖阶段1,2,3]
    ↑
阶段3 (GPU Baseline) [可并行]
```

**关键路径**: 阶段1 → 阶段2 → 阶段4
**可并行**: 阶段3与阶段1/2并行

---

## 风险评估

1. **SystemC解析复杂度**：文本输出解析可能脆弱
   - 缓解：使用多个正则模式，添加fallback

2. **GPU内存不足**：RTX 3070 8GB可能不够大case
   - 缓解：先从小case开始，逐步扩展

3. **SystemC运行时间**：每次执行可能需要数秒到数分钟
   - 缓解：使用小参数测试（npw=1000, nkb=16）

4. **CuPy兼容性**：需要CUDA 12.x
   - 缓解：检查nvidia-smi输出确认CUDA版本

---

## 下一步行动

1. **立即开始阶段1**：实现SystemCBackend.run_episode()
2. **并行准备阶段3**：检查CuPy安装和GPU可用性
3. **阶段1完成后**：验证所有family的SystemC执行
4. **最后阶段4**：完整集成验证

