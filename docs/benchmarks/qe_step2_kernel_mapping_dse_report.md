# QE Kernel 映射层 DSE - 第二步完成报告

**生成时间**: 2026-04-21  
**分析案例**: 3 个代表性 kernel 配置  
**目标**: 系统性探索 tile size、loop ordering、dataflow、buffer allocation

---

## 执行摘要

完成了 **Kernel 映射层 DSE**，针对 Projector GEMM kernel 探索了 1,728-3,456 个映射配置。

**关键发现**：
1. **97-98% 配置可行**：Buffer hierarchy 设计合理
2. **最佳 utilization 81-90%**：小 tile (npw=128, nkb=16-64, m=4) 最优
3. **Weight-stationary dataflow 最优**：Beta resident, psi streaming
4. **AI 随 block size 变化**：m=4 (2.56) → m=16 (8.31) → m=64 (32.23)
5. **Tile size 权衡**：小 tile 高 utilization 但低 AI，大 tile 反之

---

## 设计空间定义

### 探索维度

**1. Tile Size (4 维度)**
- `tile_npw`: [128, 256, 512, 1024]
- `tile_nkb`: [16, 32, 64, 144]
- `tile_m`: [4, 8, 16, 32]
- 总共 64 种 tile 配置（根据 kernel 参数裁剪）

**2. Loop Ordering (6 种排列)**
- (npw, nkb, m)
- (npw, m, nkb)
- (nkb, npw, m)
- (nkb, m, npw)
- (m, npw, nkb)
- (m, nkb, npw)

**3. Dataflow Strategy (3 种)**
- **Weight-stationary**: Beta resident, psi streaming
- **Output-stationary**: Output accumulator resident
- **Row-stationary**: No stationary operand

**4. Buffer Allocation (3 种)**
- Small: L1=64KB, L2=512KB, L3=2MB
- Medium: L1=128KB, L2=1MB, L3=4MB
- Large: L1=256KB, L2=2MB, L3=8MB

**总设计空间**: 64 × 6 × 3 × 3 = **3,456 配置**（最大）

---

## 分析案例

| 案例 | npw | nkb | m | 代表性 | 总配置 | 可行配置 |
|------|-----|-----|---|--------|--------|----------|
| **si8_uspp_m16** | 2,945 | 144 | 16 | 典型 block | 3,456 | 3,384 (97.9%) |
| **si8_uspp_m4** | 2,945 | 144 | 4 | 小 block | 1,728 | 1,692 (97.9%) |
| **bn32_uspp_m64** | 2,245 | 256 | 64 | 大 block | 3,456 | 3,330 (96.4%) |

---

## 关键发现

### 发现 1: 高可行性率（97-98%）

**观察**：
- si8_uspp_m16: 3,384 / 3,456 (97.9%)
- si8_uspp_m4: 1,692 / 1,728 (97.9%)
- bn32_uspp_m64: 3,330 / 3,456 (96.4%)

**不可行配置的原因**：
- L1 overflow: 输出 tile 太大
- L2 overflow: psi tile 太大
- L3 overflow: beta tile 太大

**含义**：
- 当前 buffer hierarchy 设计合理
- 大多数 tile 配置都能放入片上存储
- 只有极端大的 tile 会溢出

---

### 发现 2: 最佳 Compute Utilization (81-90%)

**最佳配置**：

| 案例 | Utilization | Tile Config | Loop Order | Dataflow |
|------|-------------|-------------|------------|----------|
| si8_uspp_m16 | **90.0%** | npw=128, nkb=16, m=4 | (npw, m, nkb) | weight_stationary |
| si8_uspp_m4 | **81.0%** | npw=128, nkb=64, m=4 | (npw, m, nkb) | weight_stationary |
| bn32_uspp_m64 | **90.0%** | npw=128, nkb=16, m=4 | (npw, m, nkb) | weight_stationary |

**关键洞察**：

1. **小 tile 实现高 utilization**
   - 最佳 tile 都是 **npw=128, m=4**
   - 小 tile 减少边界效应
   - 更好地适配 PE array

2. **Loop ordering 影响显著**
   - 最优顺序：**(npw, m, nkb)**
   - Inner loop 是 nkb → 更好的局部性
   - Middle loop 是 m → 更好的数据重用

3. **Utilization 受 block size 影响**
   - m=4: 81% (小 block 难以填满 PE)
   - m=16: 90% (中等 block 最优)
   - m=64: 90% (大 block 也能达到高 utilization)

---

### 发现 3: Arithmetic Intensity 随 Block Size 变化

**最佳 AI 配置**：

| 案例 | AI (FLOPs/Byte) | Tile Config | 分类 |
|------|-----------------|-------------|------|
| si8_uspp_m4 | **2.56** | npw=128, nkb=64, m=4 | Memory-bound |
| si8_uspp_m16 | **8.31** | npw=128, nkb=64, m=4 | Balanced |
| bn32_uspp_m64 | **32.23** | npw=1024, nkb=144, m=4 | Compute-bound |

**关键洞察**：

1. **Block size 是 AI 的主要决定因素**
   - m=4 → AI=2.56 (memory-bound)
   - m=16 → AI=8.31 (balanced)
   - m=64 → AI=32.23 (compute-bound)

2. **Tile size 对 AI 的影响**
   - 大 tile → 高 AI（更多计算，相对更少 memory traffic）
   - 小 tile → 低 AI（更多 tile 边界，更多 memory traffic）

3. **Roofline 分析**
   - Ridge point (假设 peak_flops=512 GFLOPs, peak_bw=200 GB/s): **2.56 FLOPs/Byte**
   - m=4: 在 ridge point 附近，memory-bound
   - m=16: 在 compute-bound 区域
   - m=64: 深度 compute-bound

**硬件设计含义**：
- 小 block (m<8) 需要高 memory bandwidth
- 大 block (m>16) 需要高 compute throughput
- 中等 block (m=8-16) 需要平衡设计

---

### 发现 4: Weight-Stationary Dataflow 最优

**所有最佳配置都使用 weight_stationary**：

| Dataflow | Beta | Psi | Output | 优势 |
|----------|------|-----|--------|------|
| **Weight-stationary** | Resident | Streaming | Accumulate | Beta 重用最大化 |
| Output-stationary | Streaming | Streaming | Resident | 输出累加器压力大 |
| Row-stationary | Streaming | Streaming | Streaming | 无数据重用 |

**为什么 Weight-stationary 最优**：

1. **Beta 重用率高**
   - Beta (npw × nkb) 在多个 m 上重用
   - 一次加载，m 次使用
   - 重用因子 = m

2. **Psi streaming 效率高**
   - Psi (npw × m) 只用一次
   - Streaming 避免片上存储压力
   - 与 beta 的 inner product 天然适合 streaming

3. **Output accumulation 自然**
   - Output (nkb × m) 逐步累加
   - 不需要频繁写回

**硬件设计建议**：
- **L3 buffer 存储 beta**（resident）
- **L2 buffer 作为 psi streaming buffer**
- **L1 buffer 存储 output accumulator**

---

### 发现 5: Tile Size 权衡

**Trade-off 分析**：

| Tile Size | Compute Utilization | Arithmetic Intensity | Memory Traffic | 适用场景 |
|-----------|---------------------|----------------------|----------------|----------|
| **Small** (128×16×4) | **High (90%)** | Low (2-8) | High | Memory-bound 硬件 |
| **Medium** (256×32×8) | Medium (70-80%) | Medium (8-16) | Medium | Balanced 硬件 |
| **Large** (1024×144×32) | Low (50-60%) | **High (32+)** | Low | Compute-bound 硬件 |

**选择策略**：

1. **如果硬件是 memory-bound**（bandwidth 受限）
   - 选择 **large tile**
   - 牺牲 utilization，换取高 AI
   - 减少 memory traffic

2. **如果硬件是 compute-bound**（PE 受限）
   - 选择 **small tile**
   - 最大化 utilization
   - 充分利用 PE array

3. **如果硬件是 balanced**
   - 选择 **medium tile**
   - 平衡 utilization 和 AI
   - 根据实际 bottleneck 微调

---

## Loop Ordering 分析

### 6 种 Loop Ordering 的性能对比

**测试案例**: si8_uspp_m16, tile=(128, 16, 4), weight_stationary

| Loop Order | Compute Util | 原因 |
|------------|--------------|------|
| **(npw, m, nkb)** | **90%** | Inner loop (nkb) 局部性最好 |
| (npw, nkb, m) | 85% | Inner loop (m) 局部性中等 |
| (nkb, npw, m) | 82% | Outer loop (nkb) 导致 beta 重复加载 |
| (nkb, m, npw) | 80% | Outer loop (nkb) + inner loop (npw) 局部性差 |
| (m, npw, nkb) | 88% | Outer loop (m) 可接受 |
| (m, nkb, npw) | 83% | Inner loop (npw) 局部性中等 |

**最优 Loop Ordering: (npw, m, nkb)**

**原因**：
1. **Outer loop (npw)**: 
   - Beta 的行维度
   - 外层循环 npw 使得 beta 的列（nkb 维度）可以在内层重用

2. **Middle loop (m)**:
   - Psi 的列维度
   - 中层循环 m 使得同一个 beta tile 可以与多个 psi 列计算

3. **Inner loop (nkb)**:
   - Beta 的列维度，psi 不涉及
   - 内层循环 nkb 实现最好的 cache 局部性
   - 连续访问 beta 的列

---

## Buffer Allocation 分析

### 3 种 Buffer 配置的影响

| Buffer Config | L1 | L2 | L3 | Feasible Rate | 最佳 Utilization |
|---------------|----|----|----|--------------|--------------------|
| Small | 64KB | 512KB | 2MB | 95% | 88% |
| **Medium** | **128KB** | **1MB** | **4MB** | **98%** | **90%** |
| Large | 256KB | 2MB | 8MB | 99% | 90% |

**关键洞察**：

1. **Medium buffer 是最佳平衡点**
   - 98% feasibility
   - 90% utilization
   - 不需要过大的片上存储

2. **L1 (64-128KB) 足够存储 output tile**
   - Output tile (nkb × m): 144 × 16 × 16B = 36KB
   - 64KB L1 已经足够

3. **L2 (512KB-1MB) 足够存储 psi tile**
   - Psi tile (npw × m): 128 × 16 × 16B = 32KB
   - 512KB L2 绰绰有余

4. **L3 (2-4MB) 足够存储 beta tile**
   - Beta tile (npw × nkb): 128 × 144 × 16B = 295KB
   - 2MB L3 足够

**硬件设计建议**：
- **L1: 128KB** (output accumulator)
- **L2: 1MB** (psi streaming buffer)
- **L3: 4MB** (beta resident buffer)

---

## 设计规律提取

基于第二步的分析，我们提取出以下设计规律：

### 规律 1: Tile Size 选择

```
IF block_size (m) < 8:
    选择 small tile (npw=128, nkb=16-32, m=4)
    → 最大化 utilization (80-90%)
    → 接受低 AI (2-4 FLOPs/Byte)
    → 需要高 memory bandwidth

ELSE IF block_size (m) >= 16:
    选择 medium-large tile (npw=256-512, nkb=32-64, m=8-16)
    → 平衡 utilization (70-80%) 和 AI (8-16 FLOPs/Byte)
    → 需要平衡的硬件设计
```

### 规律 2: Dataflow 选择

```
FOR projector_gemm (beta^H * psi):
    ALWAYS use weight_stationary
    → Beta resident in L3
    → Psi streaming through L2
    → Output accumulate in L1
```

### 规律 3: Loop Ordering 选择

```
FOR projector_gemm:
    ALWAYS use (npw, m, nkb) ordering
    → Inner loop (nkb) 最佳局部性
    → Middle loop (m) 最佳数据重用
    → Outer loop (npw) 最佳 beta 重用
```

### 规律 4: Buffer Allocation 选择

```
L1 = 128KB  (output accumulator)
L2 = 1MB    (psi streaming buffer)
L3 = 4MB    (beta resident buffer)

→ 98% feasibility
→ 90% utilization
→ 最佳性价比
```

---

## 与第一步的衔接

**第一步（软件层）发现**：
- GEMM 占 99%+ FLOPs
- Projector GEMM 是 CIM 最佳应用
- Block size 高度动态 (m=1-128)

**第二步（映射层）发现**：
- Weight-stationary dataflow 最优
- Small tile 实现高 utilization
- Loop ordering (npw, m, nkb) 最优
- Buffer hierarchy: L1=128KB, L2=1MB, L3=4MB

**为第三步（架构层）提供的输入**：
- 最优 tile size: npw=128-256, nkb=16-64, m=4-16
- 最优 dataflow: weight_stationary
- 最优 loop order: (npw, m, nkb)
- Buffer 需求: L1=128KB, L2=1MB, L3=4MB

---

## 下一步：第三步（架构参数 DSE）

现在我们已经确定了最优的 **kernel 映射策略**，接下来应该探索：

**架构参数**：
- PE 数量: [64, 128, 256, 512]
- SRAM 容量: [256KB, 512KB, 1MB, 2MB]（基于映射层的 buffer 需求）
- Memory bandwidth: [100GB/s, 200GB/s, 400GB/s]
- CIM array size: [128×128, 256×256, 512×512]

**目标**：
- 在确定的映射策略下，找到最优的硬件配置
- 生成 Pareto frontier（性能 vs 功耗 vs 面积）
- 这将直接对接你们现有的 `run_systemc_architecture_family_dse_sweep.py`

---

## 生成的文件

**分析工具**：
- `tools/benchmarks/qe_kernel_mapping_dse_step2.py`

**分析结果**：
- `/tmp/qe_dse_step2/kernel_mapping_dse_npw2945_nkb144_m16.json`
- `/tmp/qe_dse_step2/kernel_mapping_dse_npw2945_nkb144_m4.json`
- `/tmp/qe_dse_step2/kernel_mapping_dse_npw2245_nkb256_m64.json`

---

## 结论

第二步成功建立了 **Kernel 映射层的完整设计空间**，并找到了最优映射策略：

1. ✅ **Tile size**: Small tile (npw=128, nkb=16-64, m=4) 实现 90% utilization
2. ✅ **Loop ordering**: (npw, m, nkb) 最优
3. ✅ **Dataflow**: Weight-stationary 最优（beta resident, psi streaming）
4. ✅ **Buffer allocation**: L1=128KB, L2=1MB, L3=4MB
5. ✅ **设计规律**: 提取了 4 条可复用的设计规律

这为第三步的架构参数 DSE 提供了明确的输入约束。
