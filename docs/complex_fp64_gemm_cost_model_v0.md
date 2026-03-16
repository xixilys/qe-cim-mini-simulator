# CIM Complex FP64 GEMM Cost Model v0

## 1. 目的

这份文档对应第 6 件冻结事项：**做代价拆账**。  
它服务于当前已经锁定的主路线：

- `Ozaki-II`
- `CRT`
- `Karatsuba 3M`

目标不是给出最终版芯片面积，而是先把系统设计里最关键的账目拆清楚：

- 需要多少个模数
- 一次 complex GEMM 需要多少次实数 GEMM
- 输入、residue、输出缓冲分别是什么量级
- `CRT` 重构和反缩放相对于主 GEMM 有多重

## 2. 记号

对一个 tile 级 complex GEMM：

- `C = A * B`
- `A`: `Tm x Tk`
- `B`: `Tk x Tn`
- `C`: `Tm x Tn`

定义：

- `L`
  - 模数个数
- `b_fp`
  - `FP64` 实数存储字节数，当前为 `8`
- `b_res`
  - residue 存储字节数，当前默认按 `p_l <= 256` 取 `1`
- `b_acc`
  - 模域输出临时累加/缓存字节数，保持参数化
- `b_crt`
  - `CRT` 部分和累加器字节数，保持参数化

当前主线默认：

- `L = 13`
  - 见行为模型默认模数组合
- `3M`
  - 作为主设计
- `4M`
  - 只作为对照

## 3. 运算量拆账

### 3.1 每个模数的复数乘法代价

对单个模数 `p_l`：

- `3M`：需要 `3` 次实数 GEMM
- `4M`：需要 `4` 次实数 GEMM

因此：

- `N_real_gemm_per_tile(3M) = 3L`
- `N_real_gemm_per_tile(4M) = 4L`

`3M` 相对于 `4M` 的主算力节省是固定的：

- 节省比例 `= 1 - 3/4 = 25%`

### 3.2 tile 级实数 MAC 数

对一个 `Tm x Tk` 乘 `Tk x Tn` 的 tile：

- `MAC_real_per_gemm = Tm * Tk * Tn`

因此：

- `MAC_complex_per_tile(3M) = 3L * Tm * Tk * Tn`
- `MAC_complex_per_tile(4M) = 4L * Tm * Tk * Tn`

### 3.3 整个矩阵的 GEMM 次数

若外层 runtime 将大矩阵切成：

- `Nt_m = ceil(M / Tm)`
- `Nt_n = ceil(N / Tn)`
- `Nt_k = ceil(K / Tk)`

则总实数 GEMM 次数为：

- `N_real_gemm_total(3M) = 3L * Nt_m * Nt_n * Nt_k`
- `N_real_gemm_total(4M) = 4L * Nt_m * Nt_n * Nt_k`

## 4. Buffer 拆账

### 4.1 输入 staging buffer

复数 `FP64` 输入按实部/虚部分离后，需要暂存：

- `A_R`, `A_I`
- `B_R`, `B_I`

因此输入 staging 最少需要：

- `B_in_fp64 = 2 * b_fp * (Tm * Tk + Tk * Tn)`

当前 `b_fp = 8`，所以：

- `B_in_fp64 = 16 * (Tm * Tk + Tk * Tn)` bytes

### 4.2 整数化后输入缓冲

若 `NML` 显式保存整数化结果：

- `A'_R`, `A'_I`
- `B'_R`, `B'_I`

并按 64-bit 整数保存，则：

- `B_in_int64 = 16 * (Tm * Tk + Tk * Tn)` bytes

这和 `FP64` staging 同量级。

### 4.3 Residue buffer

若一次性缓存全部模数的 residue tiles，则需要：

- `B_res_full = 4 * L * b_res * (Tm * Tk + Tk * Tn)`

当前按 `b_res = 1` 字节估算时：

- `B_res_full = 4L * (Tm * Tk + Tk * Tn)` bytes

若采用**按模时分 streaming**，则最小 residue 缓冲可降为：

- `B_res_stream = 4 * b_res * (Tm * Tk + Tk * Tn)`

也就是把 `L` 从 buffer 中拿掉，代价是调度时序更紧。

### 4.4 3M 中间结果缓冲

若 `D/E/F` 三路结果都显式保留到同一拍后再组合：

- `B_3m_scratch = 3 * b_acc * Tm * Tn`

若采用边算边组合，则该项可压缩，但控制复杂度会上升。

### 4.5 CRT / 输出缓冲

若 `CRT` 引擎对实部和虚部分别维护部分和：

- `B_crt = 2 * b_crt * Tm * Tn`

最终 `FP64` 输出缓冲为：

- `B_out_fp64 = 2 * b_fp * Tm * Tn = 16 * Tm * Tn` bytes

## 5. CRT 与后处理代价

### 5.1 CRT 重构项数

对每个输出元素：

- 实部需要合并 `L` 个 residue
- 虚部也需要合并 `L` 个 residue

因此每个 tile 的 `CRT` 核心项数是：

- `N_crt_terms = 2L * Tm * Tn`

### 5.2 反缩放代价

每个输出元素最终要做：

- 实部一次反缩放
- 虚部一次反缩放

因此：

- `N_rescale_terms = 2 * Tm * Tn`

### 5.3 相对主算力的重要性

主 GEMM 代价是：

- `O(L * Tm * Tk * Tn)`

而 `CRT + rescale` 是：

- `O(L * Tm * Tn)`

所以当 `Tk` 不是很小时，`CRT` 通常不是主瓶颈。  
它更像是：

- 小 tile 下的控制和后处理开销
- 大 tile 下的次级但不可忽略项

## 6. 代表性数字

以下都按当前主线默认：

- `L = 13`
- `3M` 主路径
- `4M` 作为对照
- `Tm = Tk = Tn = T`

### 6.1 运算量

| Tile `T` | `3M` 实数 GEMM 数 | `4M` 实数 GEMM 数 | `3M` 实数 MAC 数 | `4M` 实数 MAC 数 |
|---|---:|---:|---:|---:|
| `32`  | `39` | `52` | `1,277,952` | `1,703,936` |
| `64`  | `39` | `52` | `10,223,616` | `13,631,488` |
| `128` | `39` | `52` | `81,788,928` | `109,051,904` |

### 6.2 输入与 residue 缓冲

| Tile `T` | `B_in_fp64` | `B_res_full` (`L=13`) |
|---|---:|---:|
| `32`  | `32 KB`  | `104 KB` |
| `64`  | `128 KB` | `416 KB` |
| `128` | `512 KB` | `1.63 MB` |

这里有一个很直接的设计含义：

- `64 x 64` tile 时，完整 residue 缓冲已经到 `416 KB`
- `128 x 128` tile 时，完整 residue 缓冲已经到 `1.63 MB`

所以如果片上 SRAM 紧张，**优先考虑时分多模 + streaming residue**，而不是一次性缓存全部模数。

### 6.3 CRT 项数

| Tile `T` | `N_crt_terms = 2LT^2` |
|---|---:|
| `32`  | `26,624` |
| `64`  | `106,496` |
| `128` | `425,984` |

## 7. 和当前 QE 工作负载的关系

根据当前真实样本：

- [`qe_subspace_dataset_status_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_dataset_status_20260312.md)

我们已经看到：

- `graphene`: 主导到 `(8, 4)`
- `Si`: 主导到 `(32, 16)`
- `Fe`: 主导到 `(24, 12)`
- `C6H6`: 已到 `(60, 30)`
- `Au slab`: 已到 `(52, 26)`
- `SiC32`: 已到 `(128, 64)`

这意味着当前最有价值的 tile 不是“无限大”，而是：

- `32`
- `64`
- `128`

其中：

- `32` 适合覆盖当前大量中小 `QE` 子空间块
- `64` 适合作为主工作点
- `128` 已经被 `SiC32` 这类样本直接命中

## 8. 当前结论

对当前系统设计，最重要的几条代价结论是：

1. `3M` 相对 `4M` 的算力收益是稳定的 `25%`
2. 真正先把 SRAM 推高的往往不是 `CRT`，而是多模 residue 缓冲
3. 若片上存储紧，优先优化的是：
   - `residue` 的 streaming
   - `D/E/F` 的中间结果保留策略
4. 结合当前 `QE` 数据集，`32/64/128` 已经足够支撑第一版 cost model

这份文档的定位就是把“代价拆账”先写死。  
后面如果要继续细化，可以直接在此基础上继续补：

- 每个模数的调度拍数
- NoC/跨 tile 搬运
- `NML` 侧 `CRT` 引擎端口带宽
- 不同 `L` 取值下的 crossover point
