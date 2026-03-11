# Si 代表体系下 `h_psi` 局域势作用的数据流分析

## 1. 目标

这里分析的是 QE 中 `h_psi` 里的局域势作用：

`hpsi <- hpsi + V_loc * psi`

重点不是 benchmark，而是把这段流程拆到足够细，便于后面做硬件映射、数据流设计和模块划分。

本分析聚焦于最常见、也最适合先做硬件映射的路径：

- `gamma-only`
- 非 `task group`
- 非 `real_space`
- 非非共线

对应代码路径是：

1. `h_psi_`
2. `vloc_psi_gamma_acc`
3. `wave_g2r`
4. 实空间逐点乘局域势
5. `wave_r2g`
6. 回写到 `hpsi`

## 2. 代表体系选择

这里用 QE 自带的一个小尺寸 Si 体系作为代表：

- 输入文件：`soft/qe-7.5/benchmark/test_si8_gamma.in`
- 体系：8 原子 Si，Gamma-only
- 参数：`ecutwfc = 15 Ry`，`nbnd = 16`

从输出文件 `soft/qe-7.5/benchmark/test_si8_gamma.out` 可以读到这组关键尺寸：

- `number of Kohn-Sham states = 16`
- `PW = 1021`
- `Dense/Smooth G-vectors = 8385`
- `FFT dimensions = 25 x 25 x 25`

因此对这条局域势路径，最有代表性的几个规模量是：

- 波函数 G 空间系数长度：`n = 1021`
- band 数：`m = 16`
- FFT 实空间网格点数：`nnr = 25 * 25 * 25 = 15625`
- 局域势数组长度：`v(r)` 长度也是 `15625`

这组量级比较合适做第一版硬件数据流分析，因为：

1. `n` 还在千级以内，容易看清楚 packing 和 tiling
2. `nnr` 已经明显大于 `n`，说明这段流程是典型的 “小 G 空间系数 -> 大实空间网格 -> 小 G 空间系数” 的往返流
3. `m = 16` 足够看到 band batching 的规律

## 3. 代码路径

### 3.1 `h_psi_` 顶层逻辑

`h_psi_` 先做动能项，然后进入局域势项：

- 先计算：`hpsi = (k+G)^2 * psi`
- 然后进入局域势项：`hpsi += V_loc * psi`

对当前分析的 Si 代表体系，由于它是 `gamma_only` 且通常不走 `real_space` 和 `task_groups`，局域势调用会落到：

`vloc_psi_gamma_acc(lda, n, m, psi, vrs(1,current_spin), hpsi)`

这里 `vrs(:, current_spin)` 就是实空间 smooth grid 上的局域势。

### 3.2 `vloc_psi_gamma_acc` 的本质

这个子程序本身的注释已经把算法写清楚了：

1. `psi` 从 G 空间变到实空间
2. 在实空间逐点乘局域势 `v(r)`
3. 再从实空间变回 G 空间
4. 把结果累加到 `hpsi`

所以这一段可以看成一个非常规整的流水：

`G-space coeffs -> packing -> inverse FFT -> pointwise multiply -> forward FFT -> unpack/scatter -> hpsi`

## 4. 参与的数据对象

### 4.1 输入输出数组

`vloc_psi_gamma_acc` 的主要数组如下：

- `psi(lda, m)`：输入波函数，G 空间复数系数
- `hpsi(lda, m)`：输出，累加后的哈密顿量作用结果
- `v(nnr)`：实空间局域势，实数数组
- `psi1(n, incr)`：当前 batch 的 band 缓冲
- `psic(nnr * incr)`：FFT 工作缓冲区

这里：

- `n` 是当前波函数的有效 G 系数数
- `m` 是 band 数
- `incr = 2 * many_fft`

对 Si 代表体系，如果 `many_fft = 1`，那每次处理 2 条 band；
如果 `many_fft = 2`，那每次处理 4 条 band，以此类推。

### 4.2 这几个数组在数据流中的角色

- `psi` / `hpsi`：长期存储在 G 空间，属于求解器主状态
- `psi1`：band 级本地 staging buffer
- `psic`：FFT 入口和出口共用的大缓冲
- `v`：只读、可重复使用的常驻局域势向量

如果从硬件角度看，这 4 类数据的性质完全不同：

1. `psi/hpsi` 是外部主存中的 band 数据
2. `psi1` 是小缓存，适合放片上 SRAM
3. `psic` 是大流式中间结果，最适合和 FFT 引擎邻接
4. `v` 是只读高复用数据，最值得驻留

## 5. Gamma-only 下的真实计算过程

Gamma-only 不是简单地 “一条 band 做一次复数 FFT”。  
QE 在这里用了一个很关键的技巧：把两条实波函数打包成一次复数 FFT。

这意味着自然的硬件最小处理粒度不是 1 条 band，而是 2 条 band。

### 5.1 band 分组

在 `vloc_psi_gamma_acc` 里：

- `incr = 2 * many_fft`
- 外层循环：`DO ibnd = 1, m, incr`

也就是按 band batch 处理。

例如：

- `many_fft = 1` 时，每批最多处理 2 条 band
- `many_fft = 2` 时，每批最多处理 4 条 band
- `many_fft = 4` 时，每批最多处理 8 条 band

对 Si 体系 `m = 16`，如果 `many_fft = 1`，就有 8 个 batch。

### 5.2 Step A: 从 `psi` 搬到 `psi1`

每个 batch 先做一次显式拷贝：

- 从 `psi(j, ibnd + idx - 1)` 读
- 写入 `psi1(j, idx)`

这一步本质上是：

- 从求解器总波函数矩阵里抽取当前要处理的几条 band
- 整形成一个连续的小块，供后续 FFT 打包使用

数据量近似是：

- 读：`n * group_size` 个复数
- 写：`n * group_size` 个复数

对 Si 代表体系，如果 `group_size = 2`：

- 每个 batch 搬运 `1021 * 2` 个复数

### 5.3 Step B: `wave_g2r`，把 G 空间波函数变到实空间

这一步内部又分两层。

#### B1. Gamma packing

在 `fftx_c2psi_gamma` 中，两条 band 的 G 空间系数会被打包成一个复数 FFT 输入：

- 第 1 条 band 放实部
- 第 2 条 band 放虚部

具体形式是：

- `psi_pack(nl(ig)) = c1(ig) + i * c2(ig)`
- `psi_pack(nlm(ig)) = conj(c1(ig) - i * c2(ig))`

这里：

- `nl(ig)` / `nlm(ig)` 是正负 G 点在 FFT 缓冲中的位置
- 这样构造后，一个复数 FFT 可以同时承载两条实波函数

如果当前 batch 是奇数条 band，最后剩下的 1 条 band 会单独占一个 slot。

这一层不是 FFT 本身，而是一个稀疏散写过程：

- 输入是长度 `n` 的 G 系数
- 输出是长度 `nnr` 的 FFT 输入缓冲

对 Si 代表体系：

- 每 2 条 band 最终会写满一个长度 `15625` 的复数 FFT buffer

#### B2. 逆 FFT

完成 packing 后，调用 `invfft('Wave', ...)`：

- 输入：长度 `nnr` 的复数频域数组
- 输出：长度 `nnr` 的复数实空间数组

注意这里的 “实空间数组” 在程序里仍然用复数存储。  
原因不是数据本身一定是一般复数，而是 Gamma 双 band 打包后，一个复数数组里同时携带了两条实波函数的信息。

所以 `wave_g2r` 的输出 `psic` 可以理解为：

- 每个 FFT slot 对应一对 band
- 每个 slot 长度是 `nnr`

### 5.4 Step C: 在实空间逐点乘局域势

这是整段流程里最规整、最适合硬件流化的一步：

`psic(r) = psic(r) * v(r)`

特征非常明确：

- `v(r)` 是实数
- `psic(r)` 是复数
- 没有跨点依赖
- 完全逐点独立

对每个网格点的计算可以写成：

- `Re(psic') = Re(psic) * v`
- `Im(psic') = Im(psic) * v`

如果当前 batch 有 `howmany` 个 FFT slot，那么这一步的数据量是：

- 读 `psic`：`nnr * howmany` 个复数
- 读 `v`：`nnr` 个实数，可广播复用
- 写 `psic`：`nnr * howmany` 个复数

对 Si 代表体系，若一次处理 2 条 band：

- `howmany = 1`
- 就是长度 `15625` 的复数向量乘一个长度 `15625` 的实向量

这一步算力要求不高，瓶颈通常是带宽和数据驻留。

## 6. 回到 G 空间

### 6.1 Step D: `wave_r2g`

乘完局域势后，调用 `wave_r2g` 回到 G 空间。

内部顺序是：

1. `fwfft('Wave', ...)`
2. `fftx_psi2c_gamma` 做 gamma-only 的解包

也就是先对 `psic` 做正向 FFT，再从 FFT 结果中把两条 band 的 G 系数拆出来。

### 6.2 Step E: Gamma unpacking

在 `fftx_psi2c_gamma` 里，会从打包后的 FFT 输出恢复出两条 band：

- `fp = (vin(nl) + vin(nlm)) / 2`
- `fm = (vin(nl) - vin(nlm)) / 2`

然后恢复：

- band 1 来自 `fp` 的实部和 `fm` 的虚部组合
- band 2 来自 `fp` 的虚部和 `fm` 的实部组合

这一层本质上是：

- 从长度 `nnr` 的 FFT 结果中
- 按 `nl/nlm` 索引
- 提取并重构回长度 `n` 的两条 G 空间系数向量

这又是一次 gather 型数据流，而不是密集矩阵运算。

### 6.3 Step F: 累加到 `hpsi`

最后做：

- `hpsi(:, band) += psi1(:, local_idx)`

这一层是 G 空间上的逐元素累加。

对 Si 代表体系，每 2 条 band 的 batch，对应：

- 读 `hpsi`：`1021 * 2` 个复数
- 读回变换结果：`1021 * 2` 个复数
- 写 `hpsi`：`1021 * 2` 个复数

## 7. 完整循环层次

如果把这一段放回整个 SCF 过程，循环关系可以写成：

1. SCF 外层循环
2. 本征求解器内层迭代
3. 每次需要 `H|psi>` 时调用 `h_psi`
4. `h_psi` 进入局域势分支
5. `vloc_psi_gamma_acc` 按 band batch 循环
6. 每个 batch 执行
   - G 空间抽取
   - Gamma packing
   - 逆 FFT
   - 实空间逐点乘 `v(r)`
   - 正 FFT
   - Gamma unpacking
   - 回写 `hpsi`

因此这段之所以值得做硬件映射，不是单次算子特别复杂，而是：

- 被 `h_psi` 高频调用
- 结构规整
- 可批处理
- FFT 和点乘之间的数据复用明确

## 8. 对硬件映射最关键的 4 个模块

### 8.1 模块 A: G 空间 pack/unpack 引擎

职责：

- `psi -> psi1`
- `psi1 -> FFT buffer`
- `FFT buffer -> psi1`
- `psi1 -> hpsi`

这一块的本质是索引重排、共轭镜像填充、band pair 打包和结果散回。

难点不在乘加，而在：

- 地址生成
- `nl/nlm` 非连续索引
- 两条 band 的复用式打包

### 8.2 模块 B: FFT 引擎

职责：

- `wave_g2r`
- `wave_r2g`

在当前路径里，FFT 是整个数据流的骨架。  
如果没有高效 FFT，单独优化点乘意义有限。

### 8.3 模块 C: 实空间局域势点乘引擎

职责：

- `psic(r) *= v(r)`

这一块最适合流式实现：

- `v(r)` 常驻
- `psic(r)` 连续流过
- 每拍做复数乘实数

如果要优先做最小可落地原型，这一块是最容易先实现的。

### 8.4 模块 D: 局域势驻留与调度

`v(r)` 对同一个 SCF 步、同一个自旋通道来说，在一整批 band 上是复用的。

所以很自然的策略是：

- 把 `v(r)` 作为常驻向量放片上或近存
- 多个 band batch 重复使用

如果 `v(r)` 每个 batch 都重新搬运，收益会被带宽吃掉。

## 9. 这一段真正的瓶颈是什么

对这条局域势路径，不能把它理解成 GEMM 型计算。  
它更准确的描述是：

- FFT 主导
- 中间穿插一个带高复用只读向量的逐点乘
- 前后各有一次复杂索引重排

所以主瓶颈通常不是 MAC 数，而是：

1. FFT 吞吐
2. `G <-> FFT buffer` 的 packing/unpacking 开销
3. `psic` 大缓冲的搬运
4. `v(r)` 是否能常驻

## 10. 以 Si 代表体系估算一次 batch 的数据流

下面按 `many_fft = 1`，即每批处理 2 条 band 粗略估算。

### 10.1 G 空间侧

- 输入 band 数：2
- 每条 band G 系数数：`1021`
- 输入 `psi` 数据量：`1021 * 2` 个复数
- 输出回 `hpsi` 数据量：`1021 * 2` 个复数

### 10.2 FFT / 实空间侧

- 每对 band 需要 1 个复数 FFT slot
- slot 长度：`nnr = 15625`
- `psic` 大小：`15625` 个复数
- `v(r)` 大小：`15625` 个实数

所以单看数据长度，实空间侧明显比 G 空间侧大很多。  
这说明这条路径更像 “大中间缓冲主导” 的流，而不是 “输入输出矩阵主导” 的流。

## 11. 对后续硬件方案的直接启发

### 11.1 最自然的切分单位

最自然的计算 tile 不是单条 band，而是：

- `2` 条 band 一个 gamma pair

如果做更大批处理，则是：

- `2 * many_fft` 条 band 一个上层 batch
- `many_fft` 个复数 FFT slot

### 11.2 最值得优先优化的不是乘法器，而是数据组织

因为这一段里最“纯乘法”的部分只有：

- `psic(r) *= v(r)`

这一步本身很简单。  
真正复杂的是：

- G 系数到 FFT buffer 的映射
- FFT 前后的数据驻留
- band batching
- `nl/nlm` 地址生成

所以如果要做架构探索，优先顺序更合理的是：

1. 先定 band batching 粒度
2. 再定 FFT 与局域势乘法之间是否零回写直连
3. 再定 `v(r)` 驻留策略
4. 最后才是点乘单元本身的精度和吞吐

### 11.3 局域势路径很适合做系统工程原型

因为它具有几个很好的特征：

1. 数据流清晰
2. 输入输出边界明确
3. 有固定只读向量 `v(r)`
4. FFT 前后可以插入专用硬件模块
5. 对 `h_psi` 高频调用，优化后能在整体流程中被放大

## 12. 可以继续细化的下一层

如果下一步继续往硬件落，我建议沿下面 3 条线继续细化：

1. 对 `Si` 体系把一次 `vloc_psi_gamma_acc` 的每一步读写量精确算成字节数
2. 把 `many_fft = 1/2/4` 三种 batching 方式分别画成数据流图
3. 单独把 `fftx_c2psi_gamma / fftx_psi2c_gamma` 的索引网络抽出来，分析它是否值得做专用 pack/unpack 单元

