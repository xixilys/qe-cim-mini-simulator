# QE clustered v1 面向实现的模块级方案草案（2026-04-02）

## 1. 作用

这份文档用于回应一个非常具体的审核问题：

> 当前方案已经完成 `profile + partition + architecture model`，但还没有细化到可落板的模块级实现层。

因此，这里不再讨论“body 切法对不对”，而是直接把已经冻结的 clustered v1 架构继续下推一层，形成：

- **模块级功能划分**
- **模块间接口**
- **每个模块的大体实现方法**
- **兼容不同 workload 的具体机制**

这份文档的目标不是直接给出 RTL，而是形成一个 **L2/L3-ready implementation outline**：

- 每个 cluster 里面至少有哪些硬件模块；
- 每个模块更像 `streaming pipeline / SIMD / systolic / reduction tree / controller` 中的哪一种；
- 哪些参数必须做成可配置，才能兼容不同 `QE` workload。

## 2. 先纠正一个关键边界

当前 v1 的设计对象是：

> `c_bands` 主路径

更准确地说，是：

- `h_psi`
- `s_psi`
- `build H_sub / S_sub`
- `cdiaghg`
- `refresh / residual -> P_next`

而不是整个 `electrons()` 或整个 `SCF shell` 的 fully hardened path。

这意味着：

- `CPU only` 是对照组；
- `CPU + FPGA` 的设计对象首先是 `c_bands` 主路径；
- `sum_band / v_of_rho / newd / mix_rho` 可以作为 **phase-2 shell-support acceleration candidates**，但不应在当前 v1 抢走主线。

## 3. 兼容性到底要兼容什么

“兼容不同负载”不能只停留在一句空话。对当前项目，至少有四种兼容性要同时考虑：

### 3.1 规模兼容

不同 case 的：

- `npw`
- `nkb`
- `subspace_n`
- `subspace_m`
- FFT grid

差异很大。

因此不能把 datapath 写死成只适合 `si8_pbe_uspp` 一种形状。

### 3.2 物理路径兼容

不同 case 会触发不同的：

- `NC`
- `USPP`
- `PAW`

相关路径，尤其会影响：

- projector / overlap 负载
- `newd`
- `PAW_potential`

因此 v1 主路径至少要区分：

- `NC-light`
- `USPP/PAW-heavy`

两类执行模式。

### 3.3 算法路径兼容

当前主线冻结在 Davidson 风格 `c_bands` 路径，但不同 case 可能出现：

- 子空间扩张深度不同；
- `cdiaghg` reduced dimension 不同；
- refresh 中 residual / orthogonalization 压力不同。

因此 Cluster C 和 D 不能只为单一 `n_active` 写死。

### 3.4 系统集成兼容

未来还要兼容：

- 更小的 `small-Si`
- `Si8`
- `graphene`
- `Au slab`
- `SiC32`

以及可能的：

- `bn32` stress

这要求顶层要以 **descriptor + parameterized execution** 工作，而不是一个 rigid fixed pipeline。

## 4. 顶层实现方案：不是一个大流水线，而是“控制壳 + 四个主 cluster + 统一内存层”

### 4.1 顶层组成

建议顶层固定为 6 个实现域：

1. **Episode Control Domain**
2. **Memory / DMA Domain**
3. **Cluster A: Fused Operator Sweep**
4. **Cluster B: Reduced-Matrix Build**
5. **Cluster C: Hardware cdiaghg**
6. **Cluster D: Refresh / Residual**

外加 3 个 shell-support 连接口：

- `rho -> Veff`
- `psi -> rho_out`
- `mix_rho`

### 4.2 为什么不是单一深流水

因为当前 workload 的结构不是一个完全同构的 feed-forward kernel 链：

- A 更像 streaming + local array；
- B 更像 accumulation + reduction；
- C 更像 reduced dense solver；
- D 更像 update / orthogonalize / writeback。

把它们强拉成一根单流水，通常会在：

- buffer
- backpressure
- variable-sized reduced solve
- exception / fallback

这些地方把设计搞僵。

## 5. 模块级实现：Cluster A

### 5.1 Cluster A 的职责

Cluster A 负责：

- `h_psi`
- `s_psi`

并且必须一次 sweep 共享：

- `Psi`
- projector
- overlap

### 5.2 Cluster A 模块拆分

建议拆成 5 个模块：

1. **A0 Panel DMA / Panel Loader**
2. **A1 Psi Reformatter / Tile Organizer**
3. **A2 Projector-Apply Engine**
4. **A3 Optional FFT / Potential Side Engine**
5. **A4 Partial HS Emitter**

### 5.3 每个模块的大体实现方法

**A0 Panel DMA / Panel Loader**
- 类型：streaming DMA + double buffer controller
- 职责：把 `Psi_panel` 从 off-chip 拉到片上
- 实现重点：双缓冲、burst 对齐、面向 `panel_bands` 的预取

**A1 Psi Reformatter / Tile Organizer**
- 类型：layout engine
- 职责：把输入数据整理成 A2/A3 喜欢的 tile / row-block 形状
- 实现重点：兼容不同 `npw` 尺寸下的尾块处理

**A2 Projector-Apply Engine**
- 类型：主计算模块
- 候选实现：SIMD lane array 或小型 systolic-like MAC array
- 职责：完成 projector / overlap 主计算
- 实现重点：对 `nkb`、`row_block_size` 可配置

**A3 Optional FFT / Potential Side Engine**
- 类型：side companion
- 职责：处理 `h_psi` 中需要的 FFT / potential path
- 实现重点：作为 side path，不把 A2 绑死到 FFT 时序

**A4 Partial HS Emitter**
- 类型：local reduction + packetizer
- 职责：把 A 的输出打包成 `partial_HS_packets`
- 实现重点：支持 `h/s` fused emit，避免二次搬运

### 5.4 Cluster A 的兼容性机制

Cluster A 不能靠“换代码”兼容 workload，而要靠 **参数化**：

- `panel_bands`
- `row_block_size`
- `a_array_lanes`
- `projector_mode` = `NC | USPP | PAW`
- `fft_mode` = `off | on`

也就是说，A 要做成：

> 同一套模块，不同 descriptor 配置，不同 lane 使用率

而不是：

> 每种 case 一套不同硬件。

## 6. 模块级实现：Cluster B

### 6.1 Cluster B 的职责

- 接收 `partial_HS_packets`
- 聚合成 `H_sub / S_sub`

### 6.2 Cluster B 模块拆分

建议拆成 4 个模块：

1. **B0 Partial FIFO Ingress**
2. **B1 Tile Accumulator Bank**
3. **B2 Hermitian Closure / Symmetry Enforcer**
4. **B3 Reduced-Matrix Packager**

### 6.3 实现方法

**B0**
- 类型：FIFO ingress + flow control
- 作用：吸收 A 的 bursty partial 输出

**B1**
- 类型：banked accumulation SRAM + reduction logic
- 作用：完成局部 `H/S` 累加
- 重点：避免 spill；要有 bank conflict 规则

**B2**
- 类型：small dense post-processing
- 作用：保证 reduced matrices 的 Hermitian / generalized consistency

**B3**
- 类型：descriptor builder
- 作用：输出 `reduced_matrices_descriptor` 给 C

### 6.4 Cluster B 的兼容性机制

B 的兼容性主要来自：

- `subspace_n`
- `subspace_m`
- reduced tile size

因此 B 要支持：

- 小矩阵快路径
- 大矩阵分块聚合路径

这比“只有一个固定 32x32 reduced buffer”更合理。

## 7. 模块级实现：Cluster C

### 7.1 Cluster C 是当前最关键的审核缺口

审核意见里最核心的一点是对的：

> 当前 C 还只是“硬件优先”的口号，还没有细到实现方法。

### 7.2 C 不能只有一个抽象 solver

建议 Cluster C 再拆成 4 个子模块：

1. **C0 Reduced Ingress / Conditioning Check**
2. **C1 Generalized-to-Standard Transform**
3. **C2 Standard Hermitian Solver Core**
4. **C3 Back-Transform / Solution Packager**

### 7.3 每个模块的意义

**C0**
- 类型：front-end controller
- 作用：检查 reduced size、condition、path selection
- 重点：决定硬件 fast path 还是 fallback companion

**C1**
- 类型：small dense factorization block
- 候选方法：Cholesky / LDLᵀ / overlap whitening
- 作用：把 generalized problem 转成标准 Hermitian problem

**C2**
- 类型：真正 solver core
- 候选方法：
  - 小维度 Jacobi-like / QR-like iterative engine
  - 或 block dense systolic / semi-systolic eigensolver core
- 重点：先冻结支持的维度桶，而不是假装“一核通吃”

**C3**
- 类型：post-process block
- 作用：生成 `C / Lambda / residual-visible` 结果并打包给 D

### 7.4 C 的兼容性策略

这里建议不要追求“完全通用求解器”，而是：

- **bucketed compatibility**

例如：

- `n_active <= 32`：fast path A
- `32 < n_active <= 64`：fast path B
- `64 < n_active <= 128`：slow hardware path
- 超出上限：fallback companion

这样做的好处是：

- 设计可收敛
- buffer 能算清楚
- 时钟更容易守住

而不是一开始就设计一个“理论上什么都能解”的硬件黑洞。

## 8. 模块级实现：Cluster D

### 8.1 Cluster D 的职责

- residual
- precondition
- basis refresh
- `P_next` writeback

### 8.2 Cluster D 模块拆分

建议拆成 5 个模块：

1. **D0 Solution Ingress**
2. **D1 Residual Engine**
3. **D2 Precondition / Scaling Engine**
4. **D3 Ortho / Basis Update Engine**
5. **D4 Pnext Commit / Context Writer**

### 8.3 实现方法

**D1**
- 类型：vector/tile streaming compute
- 作用：生成 residual

**D2**
- 类型：elementwise / small-vector transform
- 作用：预条件、缩放、阈值处理

**D3**
- 类型：local orthogonalization / update
- 重点：它决定 refresh 的数值稳定性

**D4**
- 类型：commit engine
- 作用：把 `P_next` 写回 resident context

### 8.4 D 的兼容性机制

D 的兼容性不是靠不同算法路径，而是靠：

- lane 数可调
- slot 数可调
- residual mode 可调

也就是说，它应该是一个：

> update fabric

而不是一条写死的 residual pipeline。

## 9. 公共支撑模块：这部分必须单独设计

如果没有这部分，所谓“兼容性”最后会变成空话。

### 9.1 Episode Descriptor Decoder

必须显式解析：

- `npw`
- `nkb`
- `subspace_n`
- `subspace_m`
- FFT grid
- pseudo mode
- solver mode
- precision mode

### 9.2 Resident Context Manager

必须维护：

- `Psi`
- projector / overlap state
- reduced buffers
- `P_next`
- version / ownership

### 9.3 Memory Scheduler

必须负责：

- off-chip burst
- bank mapping
- A/B/C/D 的共享访存仲裁

### 9.4 Inter-Cluster Flow Control

至少包含：

- FIFO credit
- backpressure propagation
- barrier control
- fallback switch

## 10. 真正的“兼容不同负载”应该怎么做

这里给一个明确判断：

### 10.1 不要做“每种 workload 一套硬件”

这会马上失控。

### 10.2 也不要做“完全通用单核”

这会马上做成一个低效软核。

### 10.3 正确做法：三层兼容

**第一层：统一 descriptor**
- 所有 case 共享一套 episode descriptor

**第二层：bucketed datapath**
- 按 `small / medium / large` reduced size
- 按 `NC-light / USPP-PAW-heavy`
- 按 `FFT on/off`

做成有限几个硬件执行桶

**第三层：fallback path**
- 超出硬件甜点区间时，不崩溃，走 companion

这才是一个工程上能收敛的“兼容性”方案。

## 11. 你现在真正缺的不是 system model，而是这三类文档

如果按工程完成度往前推，下一步不该继续泛泛谈 partition，而是要补三类文件：

1. **Module realization spec**
   - 每个 cluster 内部模块树
   - 输入输出接口
   - 主要参数
   - 候选实现方法

2. **Resource/buffer budget sheet**
   - BRAM/URAM/HBM
   - FIFO 深度
   - resident footprint
   - spill 条件

3. **Timing/compatibility sheet**
   - 每个 workload bucket 对应哪条执行路径
   - 哪些边界 barrier
   - 哪些配置导致 fallback

## 12. 一句话结论

你的审核判断是对的：

> 当前方案的方法论是对的，但工程层级还停在 cluster 级，不是模块级实现级。

要把它推进到 implementation-ready FPGA design，下一步必须从：

- “Cluster A/B/C/D 是什么”

继续下推到：

- “Cluster A/B/C/D 里面有哪些模块，各自怎么实现，哪些参数决定兼容性”

这才是能进入后续 RTL 细化的起点。
