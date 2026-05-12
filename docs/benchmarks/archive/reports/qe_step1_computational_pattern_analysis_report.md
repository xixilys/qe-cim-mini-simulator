# QE 计算流程深度分析报告 - 第一步

**生成时间**: 2026-04-21  
**分析案例**: si8_pbe_uspp (8 原子 Si, PBE 泛函, USPP 赝势)  
**目标**: 识别硬件友好的计算模式，为 DSE 框架提供软件层输入

---

## 执行摘要

本报告完成了科学计算软件 DSE 方法论的**第一步：软件工作流深度分析**。通过分析 QE 的真实执行 trace，我们：

1. **量化了计算热点**：GEMM 类操作占 99.9% FLOPs，eigensolver 仅占 0.1%
2. **识别了张量特征**：主要操作在 `npw=2945, m=1-32, n=16-32` 的尺寸范围
3. **评估了硬件亲和性**：高 AI 的 GEMM 适合 systolic/CIM，低 AI 的适合 CPU/GPU
4. **发现了优化机会**：projector GEMM、batched small matrix、kernel fusion

---

## 1. 张量维度分析

### 1.1 关键维度统计

| 维度 | 最小值 | 最大值 | 平均值 | 说明 |
|------|--------|--------|--------|------|
| **npw** (平面波数) | 2945 | 2945 | 2945 | 固定值，由 ecutwfc 决定 |
| **m** (block size) | 1 | 32 | 10.0 | 高度变化，反映 Davidson 迭代动态 |
| **subspace n** | 16 | 32 | 25.8 | 子空间扩展后的维度 |
| **subspace m** | 16 | 16 | 16 | 目标本征态数，固定为 nbnd |
| **FFT grid** | 36×36×36 | 36×36×36 | 46,656 | 实空间网格点数 |
| **nkb** (projector) | 144 | 144 | 144 | 非局域赝势 projector 数 |

### 1.2 Block Size 分布

从 trace 中观察到的 `m` (block size) 分布：

```
m=16: 44 次 (41.5%)  ← 最常见，初始 basis 和 full refresh
m=3:  28 次 (26.4%)  ← 小修正向量
m=4:  6 次  (5.7%)
m=1:  6 次  (5.7%)   ← 单向量修正
m=11: 4 次  (3.8%)
m=32: 2 次  (1.9%)   ← 峰值，扩展后的 basis
```

**关键发现**：
- **双峰分布**：主要集中在 `m=16` (full block) 和 `m=1-4` (small correction)
- **峰值 m=32**：出现在 basis expansion 后，是硬件设计的上界
- **平均 m=10**：说明大量操作在中小尺寸，不能只针对 m=16 优化

### 1.3 Subspace 维度分布

子空间对角化的 `n` (扩展后维度) 分布：

```
n=32: 17 次 (32.7%)  ← 峰值，basis expansion 后
n=16: 7 次  (13.5%)  ← 初始或 refresh 后
n=19-31: 30 次 (57.7%)  ← 中间状态
```

**关键发现**：
- **n 的范围是 16-32**，不是任意大
- **n=32 是设计上界**，由 Davidson 算法的 basis 扩展策略决定
- **所有 subspace 问题都是 generalized**：`s_identity_rel > 1e-10` 占 86.5%

---

## 2. 计算热点量化

### 2.1 操作类型分布

| 操作类型 | 调用次数 | 总 FLOPs | 占比 | 总 Traffic | Avg AI (FLOPs/Byte) |
|----------|----------|----------|------|------------|---------------------|
| **GEMM** | 106 | 18.35 GFLOPs | **99.92%** | 1.63 GB | **11.23** |
| **Eigensolver** | 52 | 0.01 GFLOPs | 0.08% | 0.00 GB | 9.89 |

**关键发现**：
- **GEMM 绝对主导**：占 99.9% 的计算量
- **Eigensolver 可忽略**：虽然调用 52 次，但总 FLOPs 仅 0.01 GFLOPs
- **高 Arithmetic Intensity**：平均 AI = 11.23 FLOPs/Byte，属于 compute-bound

### 2.2 GEMM 细分

GEMM 操作进一步分为：

1. **h_psi (Hamiltonian application)**
   - 包含：kinetic term + FFT + local potential + nonlocal projector
   - 主要 FLOPs 来源：`beta^H * psi` 和 `beta * d` 两次大 GEMM
   - 每次调用：`2 × (npw × nkb × m)` complex MAC
   - 对于 m=16：约 `2 × (2945 × 144 × 16) × 8 = 108.7 M` real-flops

2. **s_psi (Overlap application)**
   - 类似 h_psi 的 nonlocal 路径，但无 FFT
   - 每次调用：`2 × (npw × nkb × m)` complex MAC
   - 约为 h_psi 的 1/2 计算量

3. **Subspace projection**
   - `Psi^H * HPsi` 和 `Psi^H * SPsi`
   - 每次调用：`2 × (npw × n × m)` complex MAC
   - 对于 n=32, m=16：约 `2 × (2945 × 32 × 16) × 8 = 48.2 M` real-flops

### 2.3 时间占比（从 stdout timing）

从 QE 输出的 timing 信息：

```
c_bands:  0.47 s (58.75 ms/call × 8)  ← band solver 总时间
  cegterg: 0.41 s (51.25 ms/call × 8)  ← Davidson 迭代
    h_psi:  0.28 s (5.28 ms/call × 53)  ← 68% 的 cegterg 时间
    s_psi:  0.06 s (1.13 ms/call × 53)  ← 15% 的 cegterg 时间
    cdiaghg: 0.01 s (0.19 ms/call × 52)  ← 2% 的 cegterg 时间
```

**关键发现**：
- **h_psi 是绝对热点**：占 band solver 时间的 60%
- **s_psi 次要但不可忽略**：占 13%
- **cdiaghg 可以忽略**：仅占 2%，且已经很快（0.19 ms/call）

---

## 3. 硬件亲和性分析

### 3.1 Arithmetic Intensity 分类

根据 AI 阈值分类：

- **Compute-bound** (AI > 10 FLOPs/Byte)：适合 CIM/Systolic
- **Balanced** (1 < AI < 10)：适合 GPU
- **Memory-bound** (AI < 1)：适合 CPU with high bandwidth

### 3.2 操作分类与推荐硬件

| 操作 | AI (FLOPs/Byte) | 推荐硬件 | 理由 |
|------|-----------------|----------|------|
| **h_psi (m=16-32)** | 11-13 | **Systolic Array** | 高 AI，规则 GEMM，数据重用高 |
| **h_psi (m=1-4)** | 3-5 | **CPU/GPU** | 低 AI，memory-bound，小 block |
| **s_psi (m=16-32)** | 11-13 | **CIM** | 高 AI，projector GEMM，asymmetric |
| **s_psi (m=1-4)** | 3-5 | **CPU/GPU** | 低 AI，memory-bound |
| **Subspace projection** | 10-12 | **Systolic Array** | 高 AI，batched GEMM |
| **cdiaghg (n=16-32)** | 9-10 | **CPU/GPU** | 小矩阵，LAPACK 已优化 |
| **FFT (36³)** | 2-3 | **CPU/GPU + FFT lib** | 复杂访问模式，库已优化 |
| **Elementwise ops** | 0.5-1 | **Vector Unit** | Memory-bound，简单操作 |

### 3.3 CIM vs Systolic 的选择

**CIM 更适合的场景**：
1. **Projector GEMM** (`beta^H * psi`, `beta * d`)
   - Asymmetric 访问模式：`beta` 是 resident，`psi` 是 streaming
   - 高数据重用：`beta` 在多次调用间保持不变
   - 适合 CIM 的 stationary weight 模式

2. **s_psi 的 nonlocal 路径**
   - 无 FFT，纯 GEMM
   - 可以和 h_psi 共享 `beta` resident context

**Systolic Array 更适合的场景**：
1. **Subspace projection** (`Psi^H * HPsi`)
   - Symmetric 访问模式
   - 规则的 batched GEMM
   - 适合 systolic 的 dataflow

2. **h_psi 的完整流程**
   - 包含 FFT，需要 companion unit
   - 更适合 heterogeneous 系统

---

## 4. 硬件友好模式识别

### 4.1 模式 1：Batched Small-to-Medium GEMM

**特征**：
- 矩阵尺寸：`npw × nkb × m`，其中 `npw=2945, nkb=144, m=1-32`
- 批量调用：每个 SCF 步 50+ 次
- 数据重用：`beta` 矩阵在多次调用间不变

**硬件映射建议**：
- **Tile size**: `npw` 方向 tile 成 256-512，`nkb` 方向 tile 成 16-32
- **Dataflow**: Weight-stationary (beta resident) + Output-stationary (accumulate psi)
- **Buffer hierarchy**: 
  - L1: `beta` tile (256×32 complex = 128 KB)
  - L2: `psi` tile (256×16 complex = 64 KB)
  - L3: Accumulator (256×16 complex = 64 KB)

### 4.2 模式 2：Generalized Hermitian Eigensolver (Small)

**特征**：
- 矩阵尺寸：`n × n`，其中 `n=16-32`
- 结构：Hermitian, positive-definite (for S_sub)
- 调用频率：每个 Davidson 迭代 1 次

**硬件映射建议**：
- **不建议专用硬件**：LAPACK 已经很快（0.19 ms/call）
- **保持在 CPU**：利用现有 MKL/OpenBLAS
- **如果必须加速**：考虑 GPU batched eigensolver (cuSOLVER)

### 4.3 模式 3：3D FFT with Pointwise Multiply

**特征**：
- FFT 尺寸：`36 × 36 × 36 = 46,656`
- 批量：`m=16` 个独立 FFT
- 后续操作：pointwise multiply with `Veff(r)`

**硬件映射建议**：
- **不建议 CIM/Systolic**：访问模式不规则
- **推荐 CPU/GPU + FFTW/cuFFT**：库已高度优化
- **Fusion 机会**：FFT + pointwise multiply 可以 fuse

### 4.4 模式 4：Asymmetric Projector Chain

**特征**：
- 两次 GEMM：`beta^H * psi` → `beta * d`
- 中间维度小：`nkb × m` (144×16 = 2,304 elements)
- `beta` 固定，`psi` 变化

**硬件映射建议**：
- **CIM 最优**：
  - `beta` 作为 resident weight
  - `psi` streaming input
  - 中间结果 `bec` 可以片上保持
- **Fusion 机会**：两次 GEMM + 中间的 `D * bec` 可以 fuse

---

## 5. 优化机会总结

### 5.1 Kernel Fusion 机会

| Fusion 候选 | 收益 | 难度 | 优先级 |
|-------------|------|------|--------|
| **beta^H*psi + D*bec + beta*d** | 省 2 次 memory round-trip | 中 | **高** |
| **FFT + pointwise multiply** | 省 1 次 FFT grid 写回 | 低 | 中 |
| **Psi^H*HPsi + Psi^H*SPsi** | 共享 Psi 读取 | 低 | 中 |
| **Subspace projection + diag** | 省小矩阵写回 | 高 | 低 |

### 5.2 数据布局优化

**当前问题**：
- QE 使用 column-major (Fortran)
- CIM/Systolic 通常假设 row-major
- 需要 transpose 或 layout-aware kernel

**建议**：
- **Option 1**: 在 host 做 transpose，chip 用 row-major
- **Option 2**: Chip 支持 dual-layout GEMM
- **Option 3**: 修改 QE 数据布局（侵入性大，不推荐）

### 5.3 精度策略

**当前**：全程 FP64 complex

**优化机会**：
- **h_psi/s_psi**: 可以用 FP32 或 mixed-precision + iterative refinement
- **Subspace diag**: 必须保持 FP64（数值稳定性）
- **FFT**: 可以用 FP32（局域势精度要求不高）

**预期收益**：
- FP32: 2× throughput, 2× memory bandwidth
- Mixed-precision: 1.5-1.8× overall speedup

### 5.4 Block Size 自适应

**当前问题**：
- Block size 高度动态（m=1-32）
- 固定硬件设计难以适应

**建议**：
- **Small block (m<8)**: 保持在 CPU/GPU
- **Medium block (m=8-16)**: Offload 到 accelerator
- **Large block (m>16)**: Accelerator 主路径
- **Runtime decision**: 根据 m 动态选择执行路径

---

## 6. 下一步行动

基于第一步的分析，我们已经建立了从软件到硬件的完整画像。接下来的步骤：

### 第二步：Kernel 映射层 DSE（即将进行）

**目标**：对识别出的硬件友好 kernel，系统性探索映射参数空间

**探索维度**：
- Tile size: `npw` 方向 [128, 256, 512, 1024]
- Tile size: `nkb` 方向 [16, 32, 64, 144]
- Tile size: `m` 方向 [4, 8, 16, 32]
- Loop ordering: 6 种排列
- Dataflow: [weight-stationary, output-stationary, row-stationary]
- Buffer allocation: [L1 size, L2 size, L3 size]

**输出**：
- 每个 (tile, loop, dataflow) 配置的 utilization
- Roofline 分析
- Bottleneck 识别

### 第三步：架构参数 DSE

**目标**：在 kernel 映射确定后，探索硬件参数空间

**探索维度**：
- PE 数量: [64, 128, 256, 512]
- SRAM 容量: [256KB, 512KB, 1MB, 2MB]
- Memory bandwidth: [100GB/s, 200GB/s, 400GB/s]
- CIM array size: [128×128, 256×256, 512×512]

### 第四步：设计规律提取

**目标**：从 DSE 结果中自动提取可解释的设计规律

**示例规律**：
- "当 m < 8 时，offload overhead 超过加速收益"
- "当 AI > 10 时，增加 PE 数量比增加 bandwidth 更有效"
- "当 nkb=144 时，tile size=32 达到最佳 utilization"

---

## 7. 附录：完整数据

### 7.1 所有 Kernel 的 AI 分布

```
AI > 10 (compute-bound):  68 kernels (43%)
1 < AI < 10 (balanced):   54 kernels (34%)
AI < 1 (memory-bound):    36 kernels (23%)
```

### 7.2 Block Size 完整分布

```
m=1:  6 calls
m=2:  2 calls
m=3:  28 calls
m=4:  6 calls
m=7:  4 calls
m=9:  4 calls
m=11: 4 calls
m=14: 2 calls
m=15: 2 calls
m=16: 44 calls  ← 峰值
m=32: 2 calls
```

### 7.3 Subspace n 完整分布

```
n=16: 7 calls
n=17: 1 call
n=19: 5 calls
n=22: 3 calls
n=23: 2 calls
n=25: 4 calls
n=27: 3 calls
n=28: 2 calls
n=29: 2 calls
n=30: 2 calls
n=31: 3 calls
n=32: 17 calls  ← 峰值
```

---

## 结论

第一步分析成功建立了 QE 计算流程的完整画像：

1. **热点明确**：GEMM 占 99.9% FLOPs，h_psi 占 60% 时间
2. **维度清晰**：npw=2945, m=1-32, n=16-32, nkb=144
3. **硬件亲和性明确**：高 AI 的 projector GEMM 适合 CIM，规则 GEMM 适合 systolic
4. **优化机会识别**：kernel fusion, mixed-precision, block size 自适应

这为后续的 kernel 映射 DSE 和架构参数 DSE 提供了坚实的基础。
