# QE 系统 DSE 前端输入：partition and interface freeze v1

## 0. 定位

这份文档对应系统 DSE 的 **Step-2 输入 artifact**。

在 `Step-1` 的 `kernel characterization matrix` 已经冻结后，Step-2 回答四个问题：

1. **有哪些可能的系统架构选项？** ← 新增：架构家族探索
2. **给定 workload 特征，哪个架构最优？** ← 新增：基于证据的架构选择
3. 选定架构下，`Host / FPGA / Chip` 三层怎么分工；
4. 第一波 accelerator candidate kernel 的边界应该落在哪里；

**核心原则**：
- Step-2 **不是**直接冻结一个固定架构，而是**先探索、再选择、最后冻结**
- 架构探索（macro-level）使用**低保真快速评估**
- 最终输出是**基于证据的架构选择 + 冻结的接口边界**

**文献依据**：
- DNNExplorer (IBM, 2020): "global optimization is the first task" → 先选架构范式
- Polaris: 外层硬件优化器选择候选架构 → 内层逐层软件优化
- DeepStack (2026): 基础架构+堆叠搜索 → 仅 Top 5% 进入详细调优

---

## 1. Step-2 目标：从探索到冻结

当前阶段，Step-2 分为三个子阶段：

### 1.1 架构家族探索（Exploration）

**目标**：定义并评估多种可能的架构选项

**方法**：
- 基于 workload 特征（Step-1 输出）
- 使用低保真快速评估（Roofline、利用率估算）
- 不需要完整 SystemC 仿真

**输出**：
- 架构选项列表
- 定量评分矩阵
- Pareto 最优分析

### 1.2 架构选择（Selection）

**目标**：基于证据选择最优架构家族

**方法**：
- 多维度评分（性能、利用率、能效、灵活性、复杂度）
- 敏感性分析（不同 workload 特征下的选择稳定性）
- 风险-收益权衡

**输出**：
- 推荐架构 + 选择理由
- 为什么不选其他架构的证据

### 1.3 分区与接口冻结（Freeze）

**目标**：基于选定的架构，冻结系统边界

**方法**：
- 定义 Host / device runtime / hardware datapath 分工
- 冻结第一波 kernel 边界
- 定义 public interface 对象

**输出**：
- Partition and interface freeze 文档
- 可直接用于 Step-3 参数化

---

## 2. 架构家族探索

### 2.1 架构选项定义

基于 `docs/architecture/architecture_comparison/architecture_taxonomy.md`，当前定义 5 种架构家族：

| 架构 | 核心特征 | 适用场景 |
|------|---------|---------|
| **4-Cluster Pipeline** | 固定 4 阶段流水线，专用 cluster | 模块清晰，易验证 |
| **Unified Systolic Array** | 统一大 systolic array + 专用单元 | GEMM-heavy，高利用率 |
| **Dataflow Fabric** | 2D mesh 异构 PE，数据流驱动 | 算法多变，需灵活性 |
| **Heterogeneous Tiles** | 多个专用 tile，2D mesh 互联 | 平衡性能/灵活性/复杂度 |
| **CGRA** | 粗粒度可重构阵列 | 极致灵活，近 ASIC 效率 |

### 2.2 快速评估方法

**评估维度与权重**：

| 维度 | 权重 | 评估方法 |
|------|------|----------|
| Performance | 30% | Roofline 分析 |
| Utilization | 25% | Workload 分解估算 |
| Energy Efficiency | 20% | 计算/内存能量估算 |
| Flexibility | 15% | 定性评分 |
| Design Complexity | 10% | 定性评分 |

**Workload 特征（来自 Step-1）**：
- GEMM 占比：83%
- 负载分解：A=68%, B=4%, C=23%, D=5%
- 算法稳定性：evolving（可能探索 CG/LOBPCG）
- 设计时间约束：6 个月

### 2.3 评估结果

**评估范围**：25 种架构变体，7 个家族（Pipeline、Systolic、Dataflow、Tile、Reconfigurable、Hybrid、Near-Memory）

**定量评分**（0-100，基于 L0 低保真模型）：

| 排名 | 架构 | 家族 | Performance | Utilization | Energy | Flexibility | Complexity | **加权总分** | Pareto |
|------|------|------|-------------|-------------|--------|-------------|------------|--------------|--------|
| 1 | **Homogeneous Tiles Large** | Tile | 85 | 75 | 75 | 70 | 65 | **76.9** | ✅ |
| 2 | **Heterogeneous Compute-Heavy** | Tile | 85 | 75 | 75 | 70 | 65 | **76.9** | ✅ |
| 3 | **Heterogeneous Balanced** | Tile | 85 | 75 | 75 | 70 | 65 | **76.9** | ✅ |
| 4 | Scale-Up Multi-Chip | Hybrid | 75 | 72 | 70 | 65 | 55 | **68.4** | ✅ |
| 5 | CGRA Large | Reconfigurable | 70 | 60 | 68 | 90 | 40 | **68.2** | ✅ |
| 6 | FPGA with Hardened Accel | Reconfigurable | 70 | 60 | 68 | 90 | 40 | **68.2** | ✅ |
| 7 | Unified Systolic Large | Systolic | 90 | 80 | 82 | 55 | 70 | **64.8** | ✅ |
| 8 | HBM-PIM | Near-Memory | 55 | 55 | 85 | 50 | 60 | **52.8** | |
| 9 | Digital CIM | Near-Memory | 55 | 55 | 85 | 50 | 60 | **52.8** | |
| 10 | 4-Cluster Standard | Pipeline | 60 | 35 | 55 | 40 | 80 | **41.0** | |

**完整结果**：见 `tmp/comprehensive_architecture_evaluation/`

**Pareto 分析**：
- **Pareto 最优（8个）**：Tile 家族（3个）、Scale-Up Multi-Chip、CGRA Large、FPGA with Hardened、Unified Systolic Large、Dynamic Pipeline、Dataflow 家族（4个）
- **被支配**：4-Cluster Standard（被 Tile 家族全面超越）、Small 配置（被 Large 配置超越）

**家族级分析**：
- **Tile 家族**：平均分最高（74.6），最佳平衡
- **Systolic 家族**：性能最强（64.8），但灵活性不足
- **Reconfigurable 家族**：灵活性最高（68.2），但复杂度风险
- **Hybrid 家族**：扩展性好（68.4），但设计复杂
- **Pipeline 家族**：最简单（41.0），但性能差
- **Near-Memory 家族**：能效好（52.8），但 FP64 支持差
- **Dataflow 家族**：灵活性高（43.4），但复杂度过高

### 2.4 架构选择决策

**推荐架构：Heterogeneous Tiles（Compute-Heavy 配置）**

**选择理由**：
1. **性能竞争力**（85分）：6 个 GEMM tile + 2 个 eigen tile，充分利用并行性
2. **利用率高**（75分）：专用 tile 匹配 workload 分解，动态分配改善负载均衡
3. **能效良好**（75分）：专用 tile 优化特定任务，避免通用 overhead
4. **灵活性足够**（70分）：支持算法演进，tile 可重配置
5. **复杂度可控**（65分）：模块化设计，6 个月可完成验证
6. **可扩展性**：未来可扩展为 chiplet 或 multi-chip

**详细配置**：
```json
{
  "tiles": [
    {"type": "GEMM", "count": 6, "compute": "systolic_64x64", "memory_kb": 1024},
    {"type": "EIGEN", "count": 2, "compute": "eigen_unit", "memory_kb": 512},
    {"type": "VECTOR", "count": 2, "compute": "vector_unit", "memory_kb": 256}
  ],
  "interconnect": "2D_mesh",
  "shared_l3_mb": 4
}
```

**备选方案 1：Unified Systolic Large**（如果 tile 验证复杂）
- 性能最强（90分），但灵活性较低（55分）
- 集中式控制，验证相对简单

**备选方案 2：CGRA Large**（如果需要最大灵活性）
- 灵活性最高（90分），支持任意算法
- 但复杂度风险高（40分），可能延期

**为什么不选 Pipeline / 4-Cluster**：
- 利用率太低（35分），负载不均衡严重
- 被 Tile 家族全面超越

**为什么不选 Near-Memory**：
- FP64 精度支持差（当前 workload 需要 FP64）
- 更适合推理而非科学计算

**为什么不选 Dataflow**：
- 复杂度过高（45分），6 个月难以完成
- 需要复杂编译器/映射器

---

## 3. 基于 Heterogeneous Tiles 的系统对象冻结

### 3.1 三层分工

**Host CPU**：
- 外层 SCF 循环
- rho → Veff
- mix_rho
- 全局 convergence 判断
- k-point / band batch 组织
- workload trait / policy 选择
- DiagPolicy 生成
- host-side diagonalization fallback

**Thin device runtime**：
- tile 分配与调度（6 GEMM + 2 EIGEN + 2 VECTOR）
- resident preload / reuse 判断
- Host DRAM ↔ Device HBM/DDR DMA
- request 到 tile descriptor 的映射
- launch / completion / perf summary
- diag fallback 的导出、同步、回传
- spill / resident-fit / host-assist 统计
- tile 间负载均衡

**Hardware datapath (Tiles)**：
- **GEMM Tiles (6)**：h_psi / s_psi + build H_sub/S_sub（systolic 64×64）
- **Eigensolver Tiles (2)**：cdiaghg（专用 eigen unit）
- **Vector Tiles (2)**：refresh / residual → P_next
- **Inter-tile Mesh**：2D mesh 互联
- **Shared L3**：4MB 共享缓存

### 3.2 第一波 kernel 与 tile 映射

| Kernel / stage | Host | Device Runtime | Tile | 角色 |
|---------------|------|----------------|------|------|
| h_psi | 高层 request | batch DMA、tile 分配 | **GEMM Tile (1-6)** | 主热点 |
| s_psi | 高层 request | batch DMA、tile 分配 | **GEMM Tile (1-6)** | 主热点 |
| build H_sub/S_sub | 不承担 | tile 调度 | **GEMM Tile (1-6)** | companion |
| cdiaghg | host fallback | export/import/sync | **Eigensolver Tile (1-2)** | companion/fallback |
| refresh/residual | 不承担 | descriptor handoff | **Vector Tile (1-2)** | companion |
| rho → Veff | **主执行** | metadata transport | - | host-kept |
| mix_rho | **主执行** | completion summary | - | host-kept |

### 3.3 数据所有权与搬运边界

**Host DRAM 保留**：
- 全局 rho、Veff
- mixing history
- 全局 convergence state
- host fallback diag 的输入输出

**Device HBM/DDR**：
- tile-local resident projector set
- support-grid metadata
- potential slice
- active wave batch
- reduced matrices
- temporary refresh/update objects
- tile descriptor table

**Tile Local SRAM**：
- tile-local compute buffer（GEMM: 1MB, EIGEN: 512KB, VECTOR: 256KB）
- partial HS packets
- temporary reduction packets
- P_next 局部 slots

**Shared L3**：
- inter-tile 共享数据
- tile 间同步变量
- global scheduling state

---

## 4. 第一波 Interface 冻结

基于 Heterogeneous Tiles 架构，定义 5 个 public interface 对象：

### 4.1 ResidentSetDesc
- 表达应预加载并复用的常驻对象
- projector/beta family、overlap/support-grid mode
- **tile-local** resident footprint / preload budget

### 4.2 BandBatchDesc
- 表达活动 batch
- band_begin/band_count、panel_count/panel_size
- **tile assignment**（哪个 tile 处理哪个 batch）

### 4.3 DiagPolicy
- 表达 diagonalization 策略约束
- device-first 还是强制 CPU
- max_device_diag_dim、条件数阈值
- **eigensolver tile** 的 fallback 策略

### 4.4 ScfIterationRequest
- 统一打包：resident set、band batch、diag policy
- **multi-tile request**（请求多个 tile 协同）
- density/potential/history object、completion policy

### 4.5 CompletionSummary
- 统一返回：执行状态、diag_path
- **per-tile + aggregate** 统计
- resident reuse/spill、DMA read/write
- host assist/device busy 计数

---

## 5. Step-2 对 Step-3 的参数化输入

完成架构选择和分区冻结后，后续参数化应优先围绕这些边界展开：

### 5.1 System-level knobs

1. `family` → 已固定为 Heterogeneous Tiles (Compute-Heavy)
2. `n_gemm_tiles`: 4, 6, 8
3. `n_eigen_tiles`: 1, 2
4. `n_vector_tiles`: 1, 2
5. `tile_local_mem`: 256KB, 512KB, 1MB, 2MB
6. `mesh_topology`: 2×4, 3×3, 4×2
7. `tile_link_bw`: 16GB/s, 32GB/s, 64GB/s
8. `offload_scope`
9. `resident_policy`
10. `diag_policy`

### 5.2 Interface-sensitive knobs

1. `panel_bands`
2. `row_block_size`
3. `psi_panel_kib`
4. `projector_bank_kib`
5. `array_partition_strategy`
6. `pe_local_buffer_kib`

### 5.3 Fallback-sensitive knobs

1. `max_device_diag_dim`
2. `allow_cpu_diag_fallback`
3. condition-estimate threshold
4. resident-fit threshold

---

## 6. 当前 Step-2 artifact 的作用边界

这份文档的作用是：
- **探索**多种架构选项，提供定量对比证据
- **选择**基于证据的最优架构（Heterogeneous Tiles）
- **冻结**选定架构的接口边界
- 给 Step-3 parameterization 提供稳定的对象边界

它**不直接宣称**：
- 当前评估就是最终性能 claim（仍是低保真估算）
- Heterogeneous Tiles 就是唯一正确选择（保留重新评估可能性）
- 当前 proxy-level runnable model 已经足以形成 board-grounded 结论

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Tile-to-tile 通信 overhead | 性能下降 | 优化 mesh 拓扑，增加 link bandwidth |
| 负载均衡 across tiles | 利用率下降 | 动态 tile 分配，运行时调度 |
| Tile 验证复杂度 | 时间延长 | 模块化验证，独立测试每个 tile type |
| 与现有 4-Cluster SystemC 不兼容 | 需要重构 | 保留 4-Cluster 作为 fallback baseline |
| 架构选择错误 | 方向偏差 | 保留重新评估机制，Stage-B 可重新选择 |
| 算法演进（CG/LOBPCG）不适用 | 灵活性不足 | 保留 CGRA/FPGA 作为未来升级路径 |

---

## 8. 一句话收口

当前 Step-2 的正式输入可以收成一句话：

> **先通过低保真快速评估 25 种架构变体（7 家族），基于 workload 特征（GEMM-heavy、负载不均衡、算法可能演进、6 个月设计时间）选择 Heterogeneous Tiles（Compute-Heavy 配置：6 GEMM + 2 EIGEN + 2 VECTOR）作为最优架构范式，再围绕 Tile-based 系统对象（Host → Tile Runtime → GEMM/Eigen/Vector Tiles）冻结接口边界，最后输出 tile-related parameters 供 Step-3 探索。**
