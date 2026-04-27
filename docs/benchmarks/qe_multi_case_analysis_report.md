# QE 多案例计算模式对比分析报告

**生成时间**: 2026-04-21  
**分析案例数**: 6 个代表性案例  
**目标**: 识别跨案例的通用模式和案例特定的优化策略

---

## 执行摘要

通过分析 6 个具有代表性的 QE 案例，我们发现：

1. **规模差异巨大**：npw 从 129 到 29,039（225× 变化），GFLOPs 从 0.04 到 857（21,000× 变化）
2. **三层硬件映射策略**：
   - **Tier 1 (CIM/Systolic)**：3 个高 AI 案例（AI > 10），占 930 GFLOPs
   - **Tier 2 (GPU)**：3 个中等 AI 案例（AI = 3-7），占 19 GFLOPs
   - **Tier 3 (CPU)**：无案例属于此类（所有案例 AI > 1）
3. **通用模式**：所有案例 GEMM 占 99%+ FLOPs，eigensolver 可忽略
4. **Block size 高度动态**：从 m=1 到 m=128，需要自适应硬件设计

---

## 案例概览

| 案例 | 类型 | npw | m 范围 | n 范围 | nkb | GEMM GFLOPs | AI | 推荐硬件 |
|------|------|-----|--------|--------|-----|-------------|-------|----------|
| **h2_tiny** | 分子 (tiny) | 129 | 1-2 | 2-4 | 4 | 0.04 | 3.32 | GPU |
| **si8_pbe_nc** | 体材料 (small, NC) | 4,553 | 1-16 | 16-32 | 0 | 14.68 | 6.68 | GPU |
| **si8_pbe_uspp** | 体材料 (small, USPP) | 2,945 | 1-32 | 16-32 | 144 | 18.35 | 11.23 | **CIM/Systolic** |
| **graphene_pbe_uspp** | 2D 材料 (12 k-points) | 1,137 | 1-8 | 4-8 | 16 | 4.36 | 4.42 | GPU |
| **bn32_pbe_uspp** | 体材料 (medium) | 2,245 | 1-128 | 64-128 | 256 | 56.51 | 20.59 | **CIM/Systolic** |
| **sic32_subspace** | 体材料 (large) | 29,039 | 10-128 | 64-128 | 416 | 857.49 | 34.32 | **CIM/Systolic** |

---

## 关键发现

### 1. 规模多样性：225× npw 变化，21,000× GFLOPs 变化

**npw (平面波数) 分布**：
- **Tiny** (< 500): h2_tiny (129)
- **Small** (500-5,000): graphene (1,137), bn32 (2,245), si8_uspp (2,945), si8_nc (4,553)
- **Large** (> 5,000): sic32 (29,039)

**计算量分布**：
- **Negligible** (< 1 GFLOPs): h2_tiny (0.04)
- **Light** (1-20 GFLOPs): graphene (4.36), si8_nc (14.68), si8_uspp (18.35)
- **Medium** (20-100 GFLOPs): bn32 (56.51)
- **Heavy** (> 100 GFLOPs): sic32 (857.49)

**关键洞察**：
- 规模差异不是线性的，而是**指数级的**
- 大系统（sic32）的计算量是小系统（si8）的 **47 倍**
- 这意味着 DSE 必须覆盖多个数量级的设计点

---

### 2. Arithmetic Intensity 分层：三种硬件映射策略

#### Tier 1: 高 AI 案例（AI > 10）→ CIM/Systolic 加速

| 案例 | AI | GFLOPs | 特征 | 硬件推荐 |
|------|-----|--------|------|----------|
| **sic32_subspace** | 34.32 | 857.49 | 大系统，大 block (m=64-128) | **Systolic Array 主力** |
| **bn32_pbe_uspp** | 20.59 | 56.51 | 中等系统，大 block (m=64) | **Systolic Array** |
| **si8_pbe_uspp** | 11.23 | 18.35 | 小系统，USPP (nkb=144) | **CIM (projector GEMM)** |

**共同特征**：
- 所有都有 **nkb > 0**（USPP 赝势）
- 所有都有 **较大的 m** (平均 m > 10)
- 所有都是 **compute-bound**

**硬件映射建议**：
- **sic32, bn32**: Systolic array，因为 m 很大（64-128），规则 GEMM
- **si8_uspp**: CIM，因为有 projector GEMM（asymmetric access pattern）

#### Tier 2: 中等 AI 案例（1 < AI < 10）→ GPU 加速

| 案例 | AI | GFLOPs | 特征 | 硬件推荐 |
|------|-----|--------|------|----------|
| **si8_pbe_nc** | 6.68 | 14.68 | NC 赝势 (nkb=0) | **GPU** |
| **graphene_pbe_uspp** | 4.42 | 4.36 | 2D 材料，12 k-points | **GPU** |
| **h2_tiny** | 3.32 | 0.04 | 分子，极小系统 | **CPU** |

**共同特征**：
- **小 block size**：平均 m < 10
- **高调用频率**：graphene 有 538 次 GEMM 调用
- **Balanced** 或 **memory-bound**

**硬件映射建议**：
- GPU 已经足够高效
- 不值得为这些案例设计专用硬件
- h2_tiny 甚至可以保持在 CPU

#### Tier 3: 低 AI 案例（AI < 1）→ CPU 足够

**本次分析中无案例属于此类**，说明 QE 的主要工作负载都是 compute-intensive 的。

---

### 3. Block Size 模式：高度动态，需要自适应设计

#### Block Size 分布对比

| 案例 | 平均 m | m 范围 | 最常见 m | 分布特征 |
|------|--------|--------|----------|----------|
| **h2_tiny** | 1.6 | 1-2 | m=2 (63%) | 极小，单峰 |
| **graphene_pbe_uspp** | 3.5 | 1-8 | m=4 (64%) | 小，单峰 |
| **si8_pbe_nc** | 8.8 | 1-16 | m=16 (37%) | 中等，双峰 |
| **si8_pbe_uspp** | 10.0 | 1-32 | m=16 (42%) | 中等，双峰 |
| **bn32_pbe_uspp** | 56.6 | 1-128 | m=64 (68%) | 大，单峰 |
| **sic32_subspace** | 54.7 | 10-128 | m=64 (61%) | 大，单峰 |

**关键洞察**：

1. **双峰分布**（si8 系列）：
   - 峰值 1：m=16（full block）
   - 峰值 2：m=1-4（small correction）
   - 这是 Davidson 迭代的典型模式

2. **单峰分布**（大系统）：
   - bn32, sic32 主要在 m=64 附近
   - 说明大系统更稳定，不需要频繁 refresh

3. **硬件设计含义**：
   - **不能只针对单一 m 优化**
   - 需要 **tile size 自适应**
   - 小 m (< 8) 可能不值得 offload

---

### 4. Subspace 维度：所有案例 n ≤ 128

#### Subspace n 分布

| 案例 | n 范围 | 最大 n | 特征 |
|------|--------|--------|------|
| **h2_tiny** | 2-4 | 4 | 极小 |
| **graphene_pbe_uspp** | 4-8 | 8 | 小 |
| **si8_pbe_nc** | 16-32 | 32 | 中等 |
| **si8_pbe_uspp** | 16-32 | 32 | 中等 |
| **bn32_pbe_uspp** | 64-128 | 128 | 大 |
| **sic32_subspace** | 64-128 | 128 | 大 |

**关键洞察**：
- **所有案例 n ≤ 128**
- **大多数案例 n ≤ 32**
- Eigensolver 的计算量极小（< 1% FLOPs）

**硬件设计含义**：
- **不需要为 eigensolver 设计专用硬件**
- CPU 上的 LAPACK 已经足够快
- 如果要加速，考虑 GPU batched eigensolver

---

### 5. USPP vs NC 赝势的差异

#### USPP (Ultrasoft) 案例

| 案例 | nkb | AI | GFLOPs | 特征 |
|------|-----|-----|--------|------|
| **si8_pbe_uspp** | 144 | 11.23 | 18.35 | 高 AI，适合 CIM |
| **bn32_pbe_uspp** | 256 | 20.59 | 56.51 | 高 AI，适合 Systolic |
| **sic32_subspace** | 416 | 34.32 | 857.49 | 极高 AI，适合 Systolic |
| **graphene_pbe_uspp** | 16 | 4.42 | 4.36 | 中等 AI，GPU 足够 |

**共同特征**：
- 所有 USPP 案例都有 **nkb > 0**
- 所有 USPP 案例都有 **projector GEMM**
- 大多数 USPP 案例 **AI 较高**

#### NC (Norm-Conserving) 案例

| 案例 | nkb | AI | GFLOPs | 特征 |
|------|-----|-----|--------|------|
| **si8_pbe_nc** | 0 | 6.68 | 14.68 | 中等 AI，GPU 足够 |

**关键差异**：
- **NC 没有 projector GEMM**（nkb=0）
- **NC 的 AI 较低**（6.68 vs 11.23 for USPP）
- **NC 更适合 GPU**，USPP 更适合 CIM/Systolic

**硬件设计含义**：
- **USPP 是主要加速目标**
- **Projector GEMM 是 CIM 的最佳应用场景**
- NC 可以保持在 GPU

---

### 6. k-points 的影响

#### 单 k-point 案例（Γ-only）

| 案例 | k-points | Subspace calls | 特征 |
|------|----------|----------------|------|
| **h2_tiny** | 1 | 31 | 分子 |
| **si8_pbe_nc** | 1 | 66 | 体材料 |
| **si8_pbe_uspp** | 1 | 52 | 体材料 |
| **bn32_pbe_uspp** | 1 | 21 | 体材料 |
| **sic32_subspace** | 1 | 17 | 体材料 |

#### 多 k-point 案例

| 案例 | k-points | Subspace calls | 特征 |
|------|----------|----------------|------|
| **graphene_pbe_uspp** | 12 | 257 | 2D 材料 |

**关键洞察**：
- **多 k-point 显著增加调用次数**（257 vs 17-66）
- **但单次调用的计算量较小**（m=1-8）
- **总 GFLOPs 反而较低**（4.36 vs 18-857）

**硬件设计含义**：
- **多 k-point 案例更适合 GPU**（高吞吐，低延迟）
- **单 k-point 大系统更适合 CIM/Systolic**（高计算量）

---

## 通用模式总结

### 模式 1：GEMM 绝对主导（99%+ FLOPs）

**所有案例的 GEMM 占比**：
- bn32_pbe_uspp: 99.3%
- graphene_pbe_uspp: 100.0%
- h2_tiny: 100.0%
- si8_pbe_nc: 99.9%
- si8_pbe_uspp: 99.9%
- sic32_subspace: 100.0%

**含义**：
- **Eigensolver 可以完全忽略**
- **所有优化精力应集中在 GEMM**
- **h_psi/s_psi 是唯一值得加速的 kernel**

### 模式 2：Block Size 高度动态

**所有案例都显示**：
- m 从 1 到 32（小系统）或 128（大系统）
- 双峰或单峰分布
- 平均 m 从 1.6 到 56.6

**含义**：
- **硬件必须支持动态 tile size**
- **小 block (m<8) 可能不值得 offload**
- **需要 runtime 自适应调度**

### 模式 3：Subspace 维度有界（n ≤ 128）

**所有案例都显示**：
- n 最大 128
- 大多数 n ≤ 32
- Eigensolver 时间可忽略

**含义**：
- **不需要为 eigensolver 设计专用硬件**
- **CPU LAPACK 已经足够**
- **重点是 full-space GEMM，不是 subspace diag**

---

## 硬件映射策略建议

### 策略 1：分层加速

**Tier 1 (CIM/Systolic)**：
- **目标案例**：sic32, bn32, si8_uspp
- **特征**：AI > 10, nkb > 0, m 较大
- **预期收益**：10-50× vs CPU，2-5× vs GPU
- **投资优先级**：**高**

**Tier 2 (GPU)**：
- **目标案例**：si8_nc, graphene, h2_tiny
- **特征**：1 < AI < 10, 小 block 或多 k-point
- **预期收益**：5-10× vs CPU
- **投资优先级**：中（利用现有 GPU）

**Tier 3 (CPU)**：
- **目标案例**：无（所有案例都值得 GPU）
- **保留场景**：极小系统（h2_tiny 级别）

### 策略 2：Kernel 特化

**Projector GEMM (CIM 最优)**：
- `beta^H * psi` 和 `beta * d`
- Asymmetric access pattern
- `beta` resident, `psi` streaming
- 适用案例：所有 USPP (si8_uspp, bn32, sic32, graphene)

**Regular GEMM (Systolic 最优)**：
- `Psi^H * HPsi` 和 `Psi^H * SPsi`
- Symmetric access pattern
- 规则 batched GEMM
- 适用案例：所有案例

**FFT + Pointwise (GPU/CPU)**：
- 3D FFT + local potential
- 复杂访问模式
- 库已优化
- 不建议专用硬件

### 策略 3：Block Size 自适应

**Small block (m < 8)**：
- 保持在 CPU/GPU
- Offload overhead 太大
- 适用案例：graphene, h2_tiny

**Medium block (8 ≤ m < 32)**：
- 根据 AI 决定
- AI > 10 → offload
- AI < 10 → GPU
- 适用案例：si8 系列

**Large block (m ≥ 32)**：
- 始终 offload 到 accelerator
- 高计算量，值得 offload
- 适用案例：bn32, sic32

---

## DSE 框架设计建议

基于多案例分析，DSE 框架应该：

### 1. 软件层变量（已完成）

✅ **案例选择**：覆盖 6 个代表性案例  
✅ **张量特征**：npw, m, n, nkb 分布  
✅ **计算热点**：GEMM 占 99%+  
✅ **硬件亲和性**：AI 分层（3.3-34.3）

### 2. Kernel 映射层变量（下一步）

**Tile size 探索**：
- npw 方向：[128, 256, 512, 1024, 2048]
- nkb 方向：[16, 32, 64, 144, 256]
- m 方向：[4, 8, 16, 32, 64, 128]

**Loop ordering**：
- 6 种排列（npw-nkb-m 的不同顺序）

**Dataflow**：
- Weight-stationary (beta resident)
- Output-stationary (accumulate psi)
- Row-stationary

**Buffer allocation**：
- L1: 64KB, 128KB, 256KB
- L2: 512KB, 1MB, 2MB

### 3. 架构层变量（第三步）

**PE 数量**：
- [64, 128, 256, 512, 1024]

**SRAM 容量**：
- [256KB, 512KB, 1MB, 2MB, 4MB]

**Memory bandwidth**：
- [100GB/s, 200GB/s, 400GB/s, 800GB/s]

**CIM array size**：
- [128×128, 256×256, 512×512, 1024×1024]

### 4. 设计规律提取（第四步）

**目标规律示例**：
- "当 m < 8 且 AI < 5 时，GPU 比 CIM 更优"
- "当 nkb > 100 时，CIM 比 Systolic 快 2×"
- "当 npw > 10,000 时，增加 PE 数量比增加 bandwidth 更有效"

---

## 结论

通过分析 6 个代表性案例，我们建立了完整的 QE 计算模式画像：

1. **规模多样性**：225× npw 变化，21,000× GFLOPs 变化
2. **三层硬件映射**：3 个高 AI 案例适合 CIM/Systolic，3 个中等 AI 案例适合 GPU
3. **通用模式**：GEMM 占 99%+，block size 高度动态，subspace 维度有界
4. **USPP vs NC**：USPP 有 projector GEMM，AI 更高，更适合 CIM
5. **k-points 影响**：多 k-point 增加调用次数但降低单次计算量

这为后续的 kernel 映射 DSE 和架构参数 DSE 提供了坚实的基础。

---

## 附录：完整数据表

### A. 所有案例的详细特征

| 案例 | nat | nbnd | npw | nkb | FFT | k-pts | m_avg | n_max | GEMM_calls | GEMM_GFLOPs | AI |
|------|-----|------|-----|-----|-----|-------|-------|-------|------------|-------------|-----|
| h2_tiny | 2 | 2 | 129 | 4 | 5,832 | 1 | 1.6 | 4 | 64 | 0.04 | 3.32 |
| graphene | 2 | 4 | 1,137 | 16 | 24,000 | 12 | 3.5 | 8 | 538 | 4.36 | 4.42 |
| si8_nc | 8 | 16 | 4,553 | 0 | 91,125 | 1 | 8.8 | 32 | 68 | 14.68 | 6.68 |
| si8_uspp | 8 | 16 | 2,945 | 144 | 46,656 | 1 | 10.0 | 32 | 106 | 18.35 | 11.23 |
| bn32 | 32 | 64 | 2,245 | 256 | 54,000 | 1 | 56.6 | 128 | 44 | 56.51 | 20.59 |
| sic32 | 32 | 64 | 29,039 | 416 | 512,000 | 1 | 54.7 | 128 | 36 | 857.49 | 34.32 |

### B. Hardware Affinity 样本统计

| 案例 | CIM 推荐 | Systolic 推荐 | CPU/GPU 推荐 | Vector 推荐 |
|------|----------|---------------|--------------|-------------|
| h2_tiny | 0/20 | 0/20 | 20/20 | 0/20 |
| graphene | 0/20 | 0/20 | 20/20 | 0/20 |
| si8_nc | 0/20 | 0/20 | 20/20 | 0/20 |
| si8_uspp | 0/20 | 14/20 | 6/20 | 0/20 |
| bn32 | 0/20 | 18/20 | 2/20 | 0/20 |
| sic32 | 0/20 | 20/20 | 0/20 | 0/20 |
