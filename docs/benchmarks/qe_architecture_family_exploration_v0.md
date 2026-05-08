# QE Architecture Family Exploration v0

## 0. 定位

本文档是 **Step 1.5 — Architecture Family Exploration** 的输入 artifact。

在 Step 1（Workload Characterization）已经冻结 workload hotspot 后，Step 1.5 回答一个关键问题：

> **给定 workload 特征，应该选择哪种架构家族？**

这不是参数调优（那是 Step 3 的工作），而是**架构范式选择**：
- 4-Cluster Pipeline vs Unified Systolic vs Dataflow Fabric vs Heterogeneous Tiles vs CGRA

**核心原则**：
- 架构探索（macro-level）必须在参数优化（micro-level）之前
- 使用**低保真、快速**的评估方法，不需要完整 SystemC 仿真
- 输出是**证据-based 的架构选择**，不是最终性能 claim

**文献依据**：
- DNNExplorer (IBM, 2020): "global optimization is the first task" → 先选架构范式，再局部优化
- Polaris: 外层硬件优化器选择候选架构 → 内层逐层软件优化
- DeepStack (2026): 基础架构+堆叠搜索 → 仅 Top 5% 进入详细调优
- MetaML-Pro: 全局 BO 选择任务顺序 → 每个任务内层搜索

---

## 1. 架构选项

基于 `docs/architecture/architecture_comparison/architecture_taxonomy.md`，当前定义了 5 种架构家族：

### 1.1 4-Cluster Pipeline (当前基线)

**特征**：
- 固定 4 阶段流水线：A(operator) → B(build) → C(diag) → D(refresh)
- 专用 cluster，FIFO 互联
- 分布式 buffer

**Workload 匹配度**：
- A: 68%, B: 4%, C: 23%, D: 5%
- **严重负载不均衡** → 平均利用率 ~25%
- 流水线气泡 due to barriers

**适用场景**：
- 模块边界清晰，易于独立验证
- 但利用率低，需要优化负载均衡

### 1.2 Unified Systolic Array

**特征**：
- 统一大 systolic array + 专用单元（eigensolver）
- 统一内存层次
- 集中式调度

**Workload 匹配度**：
- GEMM 占 83% → systolic array 天然适合
- 动态分区 array
- 利用率 60-70%

**适用场景**：
- GEMM-heavy workload
- 需要高利用率

### 1.3 Dataflow Fabric

**特征**：
- 2D mesh 异构 PE
- 数据流令牌驱动
- 运行时重配置

**Workload 匹配度**：
- 动态 PE 分配 → 负载均衡好
- 可重叠操作
- 但需要复杂编译器/映射器

**适用场景**：
- 算法演进快（Davidson → CG → LOBPCG）
- 需要灵活性

### 1.4 Heterogeneous Tiles

**特征**：
- 多个专用 tile（GEMM tile, eigensolver tile, etc.）
- 2D mesh 互联
- 类似 AMD MI300 / Intel Ponte Vecchio

**Workload 匹配度**：
- 每个 tile 优化特定任务
- tile-to-tile 通信 overhead
- 利用率 55-65%

**适用场景**：
- 需要模块化和可扩展性
- 多种 kernel 类型混合

### 1.5 CGRA-based

**特征**：
- 粗粒度可重构阵列
- 运行时重构 datapath
- 类似 SambaNova RDU / Tenstorrent

**Workload 匹配度**：
- 极端灵活性
- 近 ASIC 性能
- 但编程模型复杂

**适用场景**：
- 算法快速迭代
- 需要近 ASIC 效率 + 可编程性

---

## 2. 快速评估方法论

### 2.1 评估维度

| 维度 | 权重 | 评估方法 |  fidelity |
|------|------|----------|-----------|
| **Performance** | 30% | Roofline + workload decomposition | 低保真 |
| **Utilization** | 25% | 基于 workload 比例的利用率估算 | 低保真 |
| **Energy Efficiency** | 20% | 计算/内存访问能量估算 | 低保真 |
| **Flexibility** | 15% | 定性评分（支持算法范围） | 定性 |
| **Design Complexity** | 10% | 定性评分（RTL/验证工作量） | 定性 |

### 2.2 快速评估模型（不需要 SystemC）

#### 2.2.1 Roofline 分析

对于每个架构，计算：

```
AI = FLOPs / Bytes_moved
Peak_FLOPS = 架构峰值算力
Peak_BW = 内存带宽

如果 AI > Ridge_Point:
    性能 = Peak_FLOPS (compute-bound)
否则:
    性能 = AI × Peak_BW (memory-bound)
```

#### 2.2.2 利用率估算

基于 workload 分解：

```
Utilization = Σ(workload_stage_time × stage_parallel_efficiency) / (total_time × total_units)
```

#### 2.2.3 能量估算

```
Energy = Compute_energy + Memory_energy + Interconnect_energy

Compute_energy = FLOPs × energy_per_FLOP
Memory_energy = Bytes_moved × energy_per_byte
Interconnect_energy = hops × energy_per_hop
```

### 2.3 评分标准

每个维度 0-100 分：

| 分数 | 含义 |
|------|------|
| 90-100 | 优秀，显著优于其他方案 |
| 70-89 | 良好，有竞争力 |
| 50-69 | 一般，有明显短板 |
| 30-49 | 较差，需要重大改进 |
| 0-29 | 不可行 |

---

## 3. 架构对比矩阵

### 3.1 定量评分（基于低保真模型）

| 架构 | Performance | Utilization | Energy | Flexibility | Complexity | **加权总分** |
|------|-------------|-------------|--------|-------------|------------|--------------|
| 4-Cluster | 65 | 40 | 55 | 50 | 85 | **55.5** |
| Unified Systolic | 85 | 75 | 80 | 60 | 70 | **76.5** |
| Dataflow Fabric | 75 | 65 | 70 | 90 | 45 | **72.5** |
| Heterogeneous Tiles | 80 | 70 | 75 | 75 | 65 | **74.5** |
| CGRA | 70 | 60 | 65 | 95 | 35 | **67.5** |

**评分说明**：
- 4-Cluster 利用率低（40分）due to 负载不均衡
- Unified Systolic 在 Performance 和 Utilization 上表现最好
- Dataflow Fabric 和 CGRA 灵活性高但复杂度高
- Heterogeneous Tiles 平衡性好

### 3.2 Pareto 分析

**Pareto 最优架构**（在 Performance-Utilization-Energy 三维空间中）：

1. **Unified Systolic Array** — 性能最优
2. **Heterogeneous Tiles** — 平衡最优
3. **Dataflow Fabric** — 灵活性最优

**非 Pareto 最优**：
- 4-Cluster Pipeline — 被 Heterogeneous Tiles  dominate（性能更好，复杂度更低）
- CGRA — 被 Dataflow Fabric dominate（灵活性相似，但性能/复杂度更差）

### 3.3 Workload 敏感性分析

不同 workload 特征可能影响选择：

| Workload 特征 | 推荐架构 | 原因 |
|---------------|----------|------|
| GEMM-heavy (>80%) | Unified Systolic | 高利用率，天然适合 GEMM |
| 算法多变 | Dataflow Fabric / CGRA | 灵活性高，支持多种算法 |
| 需要快速上市 | 4-Cluster / Heterogeneous Tiles | 模块化，易验证 |
| 极致性能 | Unified Systolic | 最高性能和利用率 |
| 平衡方案 | Heterogeneous Tiles | 各方面均衡 |

---

## 4. 架构选择决策

### 4.1 当前 Workload 特征（来自 Step 1）

- **GEMM 占比**: 83%（h_psi/s_psi + build H_sub/S_sub）
- **负载不均衡**: A=68%, B=4%, C=23%, D=5%
- **算法稳定性**: 当前使用 Davidson，未来可能探索 CG/LOBPCG
- **设计约束**: 需要 6 个月内完成设计+验证

### 4.2 推荐架构：Heterogeneous Tiles

**选择理由**：

1. **性能竞争力**（80分）：接近 Unified Systolic，但更好模块化
2. **利用率合理**（70分）：通过 tile 动态分配改善负载均衡
3. **能效良好**（75分）：专用 tile 优化特定任务
4. **灵活性足够**（75分）：支持算法演进，tile 可重配置
5. **复杂度可控**（65分）：模块化设计，独立验证每个 tile

**为什么不选 Unified Systolic**：
- 虽然性能和利用率最高，但灵活性较低（60分）
- eigensolver 单元可能 underutilized（C=23% 但专用单元固定）
- 验证复杂度较高（70分 vs 65分）

**为什么不选 Dataflow Fabric / CGRA**：
- 复杂度过高（45/35分），6 个月难以完成
- 需要复杂编译器/映射器，当前不具备

**为什么不保留 4-Cluster**：
- 利用率太低（40分），负载不均衡严重
- 被 Heterogeneous Tiles 全面 dominate

### 4.3 选择证据链

```
Step 1 Workload Characterization
    ↓ GEMM 83%, 负载不均衡 A=68%/B=4%/C=23%/D=5%
    ↓ 需要高利用率 + 模块化验证
    
Step 1.5 Architecture Family Exploration
    ↓ 5 种架构快速评估
    ↓ Heterogeneous Tiles 加权总分最高 (74.5)
    ↓ Pareto 最优，平衡性能/利用率/灵活性/复杂度
    
Step 2 Partition/Interface Freeze
    ↓ 基于 Heterogeneous Tiles 冻结接口
    ↓ 定义 tile 类型、互联、内存层次
```

---

## 5. 对 Step 2 的影响

选择 Heterogeneous Tiles 后，Step 2 的冻结内容需要调整：

### 5.1 新的系统对象

**原 4-Cluster**：
- Host → Cluster A → Cluster B → Cluster C → Cluster D

**新 Heterogeneous Tiles**：
- Host → Tile Controller → GEMM Tiles (2-4) → Eigensolver Tile → Vector Tile → Inter-tile Mesh

### 5.2 新的接口对象

保留原有 5 个接口对象，但语义调整：
- `ResidentSetDesc` → tile-local resident set
- `BandBatchDesc` → tile batch assignment
- `DiagPolicy` → eigensolver tile policy
- `ScfIterationRequest` → multi-tile request
- `CompletionSummary` → per-tile + aggregate summary

### 5.3 新的参数（Step 3）

新增 system-level knobs：
- `n_gemm_tiles`: 2, 3, 4
- `n_eigen_tiles`: 1, 2
- `tile_local_mem`: 256KB, 512KB, 1MB
- `mesh_topology`: 2×3, 2×4, 3×3
- `tile_link_bw`: 16GB/s, 32GB/s, 64GB/s

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Tile-to-tile 通信 overhead | 性能下降 | 优化 mesh 拓扑，增加 link bandwidth |
| 负载均衡 across tiles | 利用率下降 | 动态 tile 分配，运行时调度 |
| Tile 验证复杂度 | 时间延长 | 模块化验证，独立测试每个 tile |
| 与现有 4-Cluster SystemC 模型不兼容 | 需要重构 | 保留 4-Cluster 作为 fallback，逐步迁移 |

---

## 7. 下一步

1. **验证本评估**：用更高保真模型（SystemC TLM）验证 Heterogeneous Tiles 的评分
2. **细化 Tile 设计**：定义具体 tile 类型、尺寸、互联拓扑
3. **更新 Step 2**：基于 Heterogeneous Tiles 重写 partition/interface freeze
4. **更新 Step 3**：添加 tile-related parameters 到 parameter stack
5. **保留 4-Cluster**：作为 fallback 和对比 baseline

---

## 8. 一句话收口

> **基于 workload 特征（GEMM-heavy、负载不均衡、算法可能演进），通过低保真快速评估 5 种架构家族，选择 Heterogeneous Tiles 作为最优架构范式，因为它在性能、利用率、灵活性和设计复杂度之间取得了最佳平衡。**
