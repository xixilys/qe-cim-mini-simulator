# Si8 SCF 子循环算子负载实验方案与实例化结果

## 1. 实验目标

这份实验说明把 `8` 原子 `Si` 的一次 SCF 内循环拆成可规划的数据流模块，目标是回答三个问题：

1. 每一步的核心算子到底处理多大的张量；
2. 输入到该步和输出到下一步的数据量分别是多少；
3. 哪些块值得放到 chip / CIM / FPGA 路径上，哪些块继续留在 host 更合理。

这里选用 `si8_pbe_uspp` 作为主案例，而不是 `si8_pbe_nc`，因为它同时保留了：

- generalized overlap (`s_psi`)；
- ultrasoft nonlocal projector (`nkb = 144`)；
- Davidson + reduced generalized eigensolver 这一条当前主线。

## 2. 数据来源与复现实验

- 输入文件：`/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp/metadata.json` 记录的 `docs/qe_inputs/si8_pbe_uspp.in`
- 运行产物目录：`/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp`
- 关键 trace：`/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp/hpsi_trace.csv`、`/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp/bandsolver_trace.csv`、`/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp/subspace_trace.csv`

复现命令：

```bash
python3 tools/benchmarks/analyze_qe_scf_operator_load.py \
  /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation/si8_pbe_uspp \
  --markdown-out docs/benchmarks/si8_scf_operator_load_experiment_plan.md
```

## 3. 基础维度

| 量 | 数值 | 说明 |
| --- | ---: | --- |
| `nat` | 8 | Si 原子数 |
| `nbnd` | 16 | Kohn-Sham 态数 |
| `kpoints` | 1 | 本例只有 `Γ` 网格上的 `1` 个 `k` 点，但 QE 仍走复数路径 |
| `npw` | 2,945 | 波函数平面波系数个数 |
| `dense G` | 23,583 | 电荷/势场 G 向量个数 |
| `FFT grid` | `36 × 36 × 36` = 46,656 | 实空间网格点数 |
| `beta l list` | `[0, 0, 1, 1, 2, 2]` | 从当前 UPF 直接解析 |
| `beta channels / atom` | 18 | `sum(2l+1)` |
| `nkb` | 144 | `8 × 18 = 144`，是当前真实 pseudo 的值 |

提醒：仓库里的旧 note `soft/qe-7.5/CIM_data_residency_analysis.md` 使用的是更早的一组 Si 参数，其中写的是 `nkb = 12`。那份 note 适合作为思路参考，但不应该再拿来做当前 `si8_pbe_uspp` 的定量规划。

存储约定：

- 复数 `FP64`：`16 B / element`
- 实数 `FP64`：`8 B / element`

因此本 case 中几个最关键的对象大小为：

| 对象 | 维度 | 数据量 |
| --- | --- | ---: |
| `psi(G)` for `m = 16` | `2945 × 16` complex | 736.25 KiB |
| `psi(r)` on FFT grid | `46656 × 16` complex | 11.39 MiB |
| `Veff(r)` | `46656` real | 364.50 KiB |
| `beta(G)` | `2945 × 144` complex | 6.47 MiB |
| `D` or `Q` coeff | `144 × 144` real | 162.00 KiB |
| `H_sub` or `S_sub` worst case | `32 × 32` complex | 16.00 KiB |

## 4. Trace 观察到的 SCF 结构

从 `stdout.out` 和 `bandsolver_trace.csv` 可以看到：

- `c_bands`: 0.47 s / 8 calls (58.75 ms/call)
- `cegterg`: 0.41 s / 8 calls (51.25 ms/call)
- `h_psi`: 0.28 s / 53 calls (5.28 ms/call)
- `s_psi`: 0.06 s / 53 calls (1.13 ms/call)
- `cdiaghg`: 0.01 s / 52 calls (0.19 ms/call)
- `v_of_rho`: 0.06 s / 9 calls (6.67 ms/call)
- `newd`: 0.18 s / 9 calls (20.00 ms/call)
- `mix_rho`: 0.01 s / 8 calls (1.25 ms/call)

这说明：

- band solver 仍是单个 SCF 步的主块；
- `h_psi/s_psi` 的 operator application 远重于 reduced diagonalization；
- `newd` 在 USPP 路径下也不轻，但它更像 host/FPGA companion path，而不是第一优先的 chip primitive。

## 5. 单个算子的接口、维度与计算量

下面优先给出最值得建数据流的 operator 级接口。`m = 16` 对应初始 block / full-band block，是这条路径的设计基准。

### 5.1 `rho -> Veff` 势场构造

这一张表按数据依赖顺序展开 `rho -> Veff`，让 density 从实空间一路变成下一轮 `h_psi` 要消费的 `Veff(r)`。

这里的记号变化规则是：

- `rho(r)` 与 `rho(G)` 是同一个电荷密度对象，只是从实空间网格切到倒空间。
- `V_H` 表示 Hartree 势，它由 `rho` 经过 Coulomb kernel 后得到，所以从 `rho -> V_H` 时变量名改变。
- `V_xc` 表示交换关联局域势；`Veff` 则是在 `V_ion + V_H + V_xc` 合并后的总有效势。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `rho(G) = F rho(r)` | `rho(r)` `46656` real = 364.50 KiB | `rho(G)` `23583` complex = 368.48 KiB | 同一个 density，只是从 `(r)` 变到 `(G)` | `1` 次 3D FFT |
| 2 | `V_H(G) = K_H(G) rho(G)` | `rho(G)` `23583` complex | `V_H(G)` `23583` complex = 368.48 KiB | 乘上 Coulomb kernel 后，物理量从 density 变成 Hartree potential，所以 `rho -> V_H` | `47,166` real ops |
| 3 | `V_H(r) = F^{-1} V_H(G)` | `V_H(G)` `23583` complex | `V_H(r)` `46656` real = 364.50 KiB | 同一个 Hartree 势，只是从 `(G)` 变回 `(r)` | `1` 次 3D iFFT |
| 4 | `V_xc(r) = V_xc[rho(r)]` | `rho(r)` `46656` real | `V_xc(r)` `46656` real = 364.50 KiB | 这里从 density 经过 local functional evaluation 变成交换关联势，所以 `rho -> V_xc` | `46,656` local evaluations |
| 5 | `Veff(r) = V_ion(r) + V_H(r) + V_xc(r)` | `V_ion(r)` + `V_H(r)` + `V_xc(r)` | `Veff(r)` `46656` real = 364.50 KiB | 三个势项合并后改记为最终有效势 `Veff(r)` | `93,312` real adds |

汇总：这一块的接口非常规整，输入/输出都只是一个 `46656` 点实数网格，输出 `Veff(r)` 约 364.50 KiB。

### 5.2 `h_psi`：`H psi = y_T + y_eff + y_NL`

这一张表按 **数据依赖 / 数学逻辑顺序** 展开 `h_psi`，不是按底层 kernel 是否能并行重叠来排序。
这样写的目的，是让每一个中间量都能显式接到下一步，方便你直接拿去做 dataflow 和 buffer 规划。

先说明这里的记号为什么会变化：

- `psi(G)` 表示波函数在平面波系数域；`(G)` 是 reciprocal-space / plane-wave 域。
- `psi(r)` 表示同一批波函数经过 iFFT 后落在实空间网格；对象还是同一批波函数，所以保留 `psi`，只把域从 `(G)` 改成 `(r)`。
- `y_T / y_eff / y_NL` 表示哈密顿量三项贡献；一旦某个量不再是“原始波函数”，就从 `psi` 改记为 `y_*`。
- `bec`、`d` 是 projector coefficient 域里的中间量；它们已经不是 `npw × m` 的波函数块，所以单独改名。

还要注意：同一份 `psi(G)` 会分叉到三条支路——kinetic、local-potential、nonlocal-projector——最后再在 `G` 域汇合成 `Hpsi(G)`。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `m = 16` 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `y_T(G) = T psi(G)` | `psi(G)` `2945 × 16` = 736.25 KiB | `y_T(G)` `2945 × 16` = 736.25 KiB | 还在 `G` 域，但内容已经从“波函数”变成“动能项贡献”，所以 `psi -> y_T` | `47,120` complex-scale |
| 2 | `psi(r) = F^{-1} psi(G)` | `psi(G)` `2945 × 16` | `psi(r)` `46656 × 16` = 11.39 MiB | 对象还是同一批波函数，所以保留 `psi`；只是在括号里把域从 `(G)` 改成 `(r)` | `16` 次 3D iFFT |
| 3 | `y_eff(r) = Veff(r) ⊙ psi(r)` | `psi(r)` + `Veff(r)` | `y_eff(r)` `46656 × 16` = 11.39 MiB | 乘上局域势后，它不再是原始 `psi`，而是局域势贡献，所以改记为 `y_eff(r)` | `746,496` pointwise |
| 4 | `y_eff(G) = F y_eff(r)` | `y_eff(r)` `46656 × 16` | `y_eff(G)` `2945 × 16` = 736.25 KiB | 这里只改域，不改物理含义；`y_eff` 从实空间贡献返回 `G` 域贡献 | `16` 次 3D FFT |
| 5 | `bec = beta^H psi(G)` | `beta(G)` `2945 × 144` + `psi(G)` | `bec` `144 × 16` = 36.00 KiB | 输出已不是波函数网格，而是 projector coefficient block，所以改名为 `bec` | `6,785,280` complex MAC |
| 6 | `d = D bec` | `bec` `144 × 16` | `d` `144 × 16` = 36.00 KiB | 这里施加的是非局域系数矩阵 `D`；输出变成另一组非局域权重，所以 `bec -> d` | `331,776` coeff ops |
| 7 | `y_NL(G) = beta d` | `beta(G)` `2945 × 144` + `d` `144 × 16` | `y_NL(G)` `2945 × 16` = 736.25 KiB | 从 projector coefficient 重新展回 `G` 域的非局域贡献，所以改记为 `y_NL(G)` | `6,785,280` complex MAC |
| 8 | `Hpsi(G) = y_T(G) + y_eff(G) + y_NL(G)` | 三个 `2945 × 16` block | `Hpsi(G)` `2945 × 16` = 736.25 KiB | 三条支路都回到 `G` 域后求和，得到最终的哈密顿量作用结果 `Hpsi(G)` | `188,480` real ops 级别 |

按上面 `1 -> 8` 的逻辑链路累计，`m = 16` 的一次 `h_psi` 总量约为 `227.447 M` real-flop 量级（含 FFT 估算）。
这一步最需要注意的数据膨胀发生在 step `2`：`psi(G)` 从 736.25 KiB 经过 FFT 网格展开后，会暂时变成 `psi(r)` 11.39 MiB。
如果后面要映射到硬件流水线，可以把 step `1`、`2-4`、`5-7` 看成三条可部分重叠的支路；但为了保证语义清楚，这里仍按依赖顺序写。

### 5.3 `s_psi`：广义重叠算子

这一张表把 `s_psi` 也完全按依赖顺序展开。它和 `h_psi` 的 nonlocal 路径很像，只是这里用的是 overlap projector，而不是 Hamiltonian 非局域系数。

记号变化规则：

- `bec` 仍表示 `beta^H psi` 形成的 projector coefficient。
- `d_S` 表示 overlap 矩阵 `Q` 作用后的系数；为了和 `h_psi` 里的 `d = D bec` 区分，这里显式写成 `d_S`。
- `Spsi_corr(G)` 表示 overlap correction 项；加回原始 `psi(G)` 后才得到最终 `Spsi(G)`。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `m = 16` 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `bec = beta^H psi(G)` | `beta(G)` `2945 × 144` + `psi(G)` `2945 × 16` = 736.25 KiB | `bec` `144 × 16` = 36.00 KiB | 输出从波函数块变成 projector coefficient block，所以改名为 `bec` | `6,785,280` complex MAC |
| 2 | `d_S = Q bec` | `bec` `144 × 16` | `d_S` `144 × 16` = 36.00 KiB | 经过 overlap 系数矩阵 `Q` 后，得到另一组 correction coefficient，所以 `bec -> d_S` | `331,776` coeff ops |
| 3 | `Spsi_corr(G) = beta d_S` | `beta(G)` `2945 × 144` + `d_S` `144 × 16` | `Spsi_corr(G)` `2945 × 16` = 736.25 KiB | 从 coefficient 域重新展回 `G` 域的重叠修正项，所以改名为 `Spsi_corr(G)` | `6,785,280` complex MAC |
| 4 | `Spsi(G) = psi(G) + Spsi_corr(G)` | `psi(G)` + `Spsi_corr(G)` | `Spsi(G)` `2945 × 16` = 736.25 KiB | correction 加回原始波函数后，得到最终 overlap 作用结果 `Spsi(G)` | `188,480` real ops 级别 |

按上面 `1 -> 4` 的链路累计，`m = 16` 的一次 `s_psi` 总量约为 `110.080 M` real-flop 量级。
`s_psi` 的优点是没有 FFT；它更像典型的 projector-dense kernel。

### 5.4 basis expansion: 构建 `H_sub / S_sub`

设当前保留 basis 为 `n_prev`，新增修正向量数为 `p`，则扩展后 `n = n_prev + p`。下面把一次 `expand_basis` call 展开成显式 reduced-matrix 组装步骤。

这里的符号变化规则是：

- `Psi[npw, n_prev]` 是旧 basis；`P[npw, p]` 是这一轮新加进来的修正向量块。
- `HP` / `SP` 表示这些新向量已经分别经过 `H` 和 `S` 作用。
- `G_H`、`B_H` 是 reduced Hamiltonian 的两个新块；`G_S`、`B_S` 则是 reduced overlap 的两个新块。
- `H_sub`、`S_sub` 是最终拼装好的 `n × n` 子空间矩阵。

下面以第一次 expand 为例：`n_prev = 16`，`p = 16`，扩展后 `n = 32`。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `G_H = Psi^H HP` | `Psi` `2945 × 16` + `HP` `2945 × 16` | `G_H` `16 × 16` = 4.00 KiB | 从 full-space block 投影到 reduced coupling block，所以改为 `G_H` | `753,920` complex MAC |
| 2 | `B_H = P^H HP` | `P` `2945 × 16` + `HP` `2945 × 16` | `B_H` `16 × 16` = 4.00 KiB | 这是新增块在 Hamiltonian 下的自耦合，所以写成底部块 `B_H` | `753,920` complex MAC |
| 3 | `H_sub = [[H_old, G_H], [G_H^H, B_H]]` | `H_old` `16 × 16` + `G_H` + `B_H` | `H_sub` `32 × 32` = 16.00 KiB | 多个 reduced block 拼成最终 Hamiltonian 子空间矩阵，所以统一记为 `H_sub` | `1,024` element assembly |
| 4 | `G_S = Psi^H SP` | `Psi` `2945 × 16` + `SP` `2945 × 16` | `G_S` `16 × 16` = 4.00 KiB | 与 step 1 同理，但这是 overlap coupling block，所以写成 `G_S` | `753,920` complex MAC |
| 5 | `B_S = P^H SP` | `P` `2945 × 16` + `SP` `2945 × 16` | `B_S` `16 × 16` = 4.00 KiB | 与 step 2 同理，但对应 overlap 自耦合块 | `753,920` complex MAC |
| 6 | `S_sub = [[S_old, G_S], [G_S^H, B_S]]` | `S_old` `16 × 16` + `G_S` + `B_S` | `S_sub` `32 × 32` = 16.00 KiB | 多个 reduced block 拼成最终 overlap 子空间矩阵，所以统一记为 `S_sub` | `1,024` element assembly |

在 `Si8` 的第一次 expand (`n_prev = 16`, `p = 16`, `n = 32`) 上：

- 输出两个小矩阵 `H_sub + S_sub` 总共只有 32.00 KiB
- 但乘加量已经是 `3,015,680` complex MAC

### 5.5 reduced generalized diagonalization `cdiaghg`

trace 只能直接看到顶层 `cdiaghg` 调用；下面这张表给的是**用于架构分析的数学展开**，把 generalized eigensolver 内部逻辑显式写出来。

这里的符号变化规则是：

- `L` 是 `S_sub` 的 Cholesky factor；它不再是原始 overlap 矩阵，所以从 `S_sub -> L`。
- `A_std` 是把 generalized 问题标准化后的 Hermitian 小矩阵。
- `Y` 是标准问题的本征向量；`C` 是回代后的 generalized 系数矩阵。

下面以峰值 `n = 32`、`m = 16` 为例展开。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `S_sub = L L^H` | `S_sub` `32 × 32` = 16.00 KiB | `L` `32 × 32` = 16.00 KiB | 对 overlap 小矩阵做分解后，得到 factor `L`，所以 `S_sub -> L` | `O(32^3)` |
| 2 | `A_std = L^{-1} H_sub L^{-H}` | `H_sub` `32 × 32` + `L` `32 × 32` | `A_std` `32 × 32` = 16.00 KiB | generalized 问题被标准化后，得到新的标准 Hermitian 矩阵 `A_std` | `O(32^3)` |
| 3 | `A_std Y = Y Lambda` | `A_std` `32 × 32` | `Y` `32 × 16` = 8.00 KiB + `Lambda` `16` = 128 B | 在标准问题里输出的是标准坐标系本征向量 `Y` 和本征值 `Lambda` | `O(32^3)` |
| 4 | `C_raw = L^{-H} Y` | `L` `32 × 32` + `Y` `32 × 16` | `C_raw` `32 × 16` = 8.00 KiB | 把标准问题本征向量回代到 generalized 坐标，所以 `Y -> C_raw` | `O(32^2 * 16)` |
| 5 | `C = normalize_S(C_raw)` | `C_raw` `32 × 16` + `S_sub` `32 × 32` | `C` `32 × 16` = 8.00 KiB + `Lambda` `16` = 128 B | 最终做 `S`-度量归一化后，得到可以直接回到 full space 的 reduced coefficient `C` | `O(32^2 * 16)` |

峰值 `n = 32` 时，输入矩阵总共只有 32.00 KiB，输出 `C + Lambda` 也只有 8.12 KiB。

### 5.6 basis refresh / residual update

在 generalized Davidson 路径里，reduced solve 之后不会立刻结束；还要把 reduced coefficient 回到 full space，再形成 residual 并产生下一批修正向量。

这里的符号变化规则是：

- `X` 表示刷新后的 Ritz vector block；`HX`、`SX` 则是它们在 `H` / `S` 作用下的 companion block。
- `R` 是 residual block；`P_raw` 是预条件后的候选修正向量；`P` 是正交化后的最终扩展块。

下面用峰值型 `n = 32`、`m = 16` 展开。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `X = Psi C` | `Psi` `2945 × 32` = 1.44 MiB + `C` `32 × 16` = 8.00 KiB | `X` `2945 × 16` = 736.25 KiB | reduced coefficient 回到 full space 后，得到新的 Ritz vectors `X` | `12.063 M` real-flop 级别 |
| 2 | `HX = HPsi C`, `SX = SPsi C` | `HPsi/SPsi` `2945 × 32` + `C` `32 × 16` | `HX/SX` 各 `2945 × 16` = 736.25 KiB | 与 `X` 对应的两个 companion block 单独命名为 `HX`、`SX` | `24.125 M` real-flop 级别 |
| 3 | `R = HX - SX Lambda` | `HX` `2945 × 16` + `SX` `2945 × 16` + `Lambda` `16` | `R` `2945 × 16` = 736.25 KiB | 构造残差后，变量从 operator result 变成 residual，所以改记为 `R` | `565,440` real ops 级别 |
| 4 | `P_raw = M^{-1} R` | `R` `2945 × 16` | `P_raw` `2945 × 16` = 736.25 KiB | 经过预条件器后，残差变成候选修正向量，所以 `R -> P_raw` | `O(npw * m)` |
| 5 | `P = ortho_S(P_raw; X)` | `P_raw` `2945 × 16` + `X/SX` `2945 × 16` | `P` `2945 × p`，其中 `p <= 16` | 经过 `S`-正交化后，得到真正能拿去扩展 basis 的块 `P` | `O(npw * m * p)` |

这部分的张量尺寸仍然是 `npw × n` 级别，所以它们更像 `chip/FPGA` 边界上的 companion GEMM，而不是新的小矩阵主热点。

### 5.7 `psi -> rho_out` 电荷组装

这里也按依赖顺序把电荷组装完全展开。当前 case 只有 `1` 个 `k` 点，所以 `k` 权重不会引入额外分支。

记号变化规则：

- `psi(G)` 与 `psi(r)` 仍然是同一批波函数，只是域不同。
- `q_n(r)` 表示每个 band 的电子密度贡献；`u_n(r)` 表示再乘上占据数后的加权贡献。
- 最后对 band 维求和后，得到总电荷密度 `rho_out(r)`。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | `nbnd = 16` 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `psi(r) = F^{-1} psi(G)` | `psi(G)` `2945 × 16` = 736.25 KiB | `psi(r)` `46656 × 16` = 11.39 MiB | 同一批波函数，只是从 `(G)` 变到 `(r)` | `16` 次 3D iFFT |
| 2 | `q_n(r) = |psi_n(r)|^2` | `psi(r)` `46656 × 16` | `q_n(r)` `46656 × 16` real = 5.70 MiB | 从复振幅变成每个 band 的实数密度贡献，所以 `psi -> q_n` | `2,239,488` real ops |
| 3 | `u_n(r) = f_n q_n(r)` | `q_n(r)` `46656 × 16` + `f_n` `16` | `u_n(r)` `46656 × 16` real = 5.70 MiB | 乘上占据数后，band-density contribution 变成 weighted contribution，所以 `q_n -> u_n` | `746,496` real ops |
| 4 | `rho_out(r) = sum_n u_n(r)` | `u_n(r)` `46656 × 16` | `rho_out(r)` `46656` real = 364.50 KiB | 对 band 维求和后，得到总输出密度，所以 `u_n -> rho_out` | `699,840` real ops |

### 5.8 `mix_rho`

这个 case 的输入文件使用的是 `mixing_mode = plain`，所以这里可以把混合路径写得很直接。

记号变化规则：

- `rho_in(r)` 表示本轮进入 mixing 的旧密度。
- `delta_rho(r)` 是新旧密度差；`rho_new(r)` 是线性混合后的下一轮输入密度。

| 步骤 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 量级 |
| --- | --- | --- | --- | --- | ---: |
| 1 | `delta_rho(r) = rho_out(r) - rho_in(r)` | `rho_out(r)` + `rho_in(r)` = 729.00 KiB | `delta_rho(r)` `46656` real = 364.50 KiB | 新旧密度做差后，变量从 density 变成 density residual，所以改记为 `delta_rho` | `46,656` real subs |
| 2 | `beta_delta(r) = beta delta_rho(r)` | `delta_rho(r)` `46656` real | `beta_delta(r)` `46656` real = 364.50 KiB | 经过 mixing 系数 `beta` 缩放后，残差变成可加回的 mixed increment | `46,656` real muls |
| 3 | `rho_new(r) = rho_in(r) + beta_delta(r)` | `rho_in(r)` + `beta_delta(r)` | `rho_new(r)` `46656` real = 364.50 KiB | 把混合增量加回旧密度后，得到下一轮 SCF 输入密度 `rho_new(r)` | `46,656` real adds |

## 6. 一整个 SCF 步的 trace 实例

为了给 throughput / buffering 设计留出上界，下面同时给出一个 nominal step 和一个 peak step：

- nominal step: SCF iter `3`，`h_psi` block 序列为 `[16, 16, 16, 3]`
- peak step: SCF iter `6`，`h_psi` block 序列为 `[16, 16, 16, 16, 14, 11, 9, 7, 7, 4, 3, 3, 3, 3, 3, 3, 3, 2, 1, 1]`

| SCF iter | `h_psi` calls | `sum(m)` | `diag` calls | max `n` | 估算总计算量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 3 | 43 | 2 | 32 | 964.105 M real-flop 级别 |
| 2 | 2 | 32 | 1 | 32 | 699.671 M real-flop 级别 |
| 3 | 4 | 51 | 3 | 32 | 1.164 G real-flop 级别 |
| 4 | 7 | 65 | 6 | 32 | 1.497 G real-flop 级别 |
| 5 | 4 | 51 | 3 | 32 | 1.163 G real-flop 级别 |
| 6 | 20 | 141 | 19 | 32 | 3.294 G real-flop 级别 |
| 7 | 8 | 66 | 7 | 32 | 1.518 G real-flop 级别 |
| 8 | 4 | 51 | 3 | 32 | 1.164 G real-flop 级别 |

其中最值得拿来做峰值带宽设计的是 SCF iter `6`：

- `h_psi/s_psi` 的 block 序列：`[16, 16, 16, 16, 14, 11, 9, 7, 7, 4, 3, 3, 3, 3, 3, 3, 3, 2, 1, 1]`
- 这一轮的 `h_psi + s_psi` 估算已经达到 `2.974 G` real-flop 量级
- 同一轮的 reduced diagonalization 仍只有 `5.641 M` 量级

结论很直接：峰值设计应以 repeated operator application 为准，而不是以 `32 × 32` 小矩阵对角化为准。

### 6.1 nominal SCF step 的显式数据流版

下面把 nominal step（SCF iter `3`）按 **trace runtime order + 数学依赖** 展开。`init_basis / expand_basis / post_diag / refresh_basis / converged_exit` 是 trace 直接可见的控制事件；而 `X / R / P` 这一类中间对象是为了 dataflow 规划而显式补出来的。

这里的记号变化规则是：

- `Psi_keep^{(i)}` 表示第 `i` 次 refresh 之后保留下来的 resident basis。
- `P^{(i)}` 表示第 `i` 轮新增 correction block；`HP^{(i)}`、`SP^{(i)}` 是它的 companion operator blocks。
- `H_sub^{(i)}`、`S_sub^{(i)}` 是第 `i` 轮 expanded subspace 矩阵。
- `C^{(i)}`、`Lambda^{(i)}` 是 reduced solve 输出；回到 full space 后得到 `X^{(i)}`、`HX^{(i)}`、`SX^{(i)}`。

| 阶段 | 显式表达式 | 输入 | 输出 | 为什么符号变化 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| init-1 | `Psi_keep^{(0)} = psi_init(G)` | `psi_init(G)` `2945 × 16` = 736.25 KiB | `Psi_keep^{(0)}` `2945 × 16` | 原始输入 block 进入 band solver 后，变成初始 resident basis，所以改记为 `Psi_keep^0` | `init-2` |
| init-2 | `HPsi_keep^{(0)} = H Psi_keep^{(0)}`, `SPsi_keep^{(0)} = S Psi_keep^{(0)}` | `Psi_keep^{(0)}` `2945 × 16` | `HPsi_keep^{(0)}/SPsi_keep^{(0)}` 各 `2945 × 16` = 736.25 KiB | 伴随 operator 作用后的 resident companion blocks 单独记为 `HPsi_keep` / `SPsi_keep` | `solver iter 1 / expand_basis` |
| iter 1-1 | `P^{(1)} -> [P^{(1)}, HP^{(1)}, SP^{(1)}]` | 前一轮 residual / precondition 路径输出，trace 可见 block size `m = 16` | 三个 `2945 × 16` block，各 736.25 KiB | 新增 correction block 不再属于 retained basis，所以单独改记为 `P^{(i)}` | `iter 1-2 / expand_basis` |
| iter 1-2 | `build([Psi_keep^{(0)}, P^{(1)}]) -> H_sub^{(1)}, S_sub^{(1)}` | retained basis `2945 × 16` + new block `2945 × 16` | `H_sub^{(1)}/S_sub^{(1)}` 各 `32 × 32` = 16.00 KiB | full-space vectors 被投影到 reduced subspace，所以统一改记为 `H_sub` / `S_sub` | `iter 1-3 / post_diag` |
| iter 1-3 | `(H_sub^{(1)}, S_sub^{(1)}) -> (C^{(1)}, Lambda^{(1)})` | `H_sub^{(1)}/S_sub^{(1)}` `32 × 32` | `C^{(1)}` `32 × 16` = 8.00 KiB + `Lambda^{(1)}` `16` = 128 B; `notcnv = 16` | reduced eigensolver 输出不再是 basis block，而是 reduced coefficient + eigenvalue，所以改记为 `C/Lambda` | `iter 1-4 / refresh_basis` |
| iter 1-4 | `C^{(1)} -> [X^{(1)}, HX^{(1)}, SX^{(1)}] -> [Psi_keep^{(1)}, HPsi_keep^{(1)}, SPsi_keep^{(1)}]` | expanded basis/operator blocks `2945 × 32` + `C^{(1)}` `32 × 16` | refreshed resident state 三个 `2945 × 16` block，各 736.25 KiB | reduced coefficient 回到 full space 先形成 Ritz block `X/HX/SX`，再压回 retained basis resident state，所以 `C -> X -> Psi_keep` | 再经 residual / precondition / ortho 生成 `P^{(2)}`，其 trace block size 为 `m = 16` |
| iter 2-1 | `P^{(2)} -> [P^{(2)}, HP^{(2)}, SP^{(2)}]` | 前一轮 residual / precondition 路径输出，trace 可见 block size `m = 16` | 三个 `2945 × 16` block，各 736.25 KiB | 新增 correction block 不再属于 retained basis，所以单独改记为 `P^{(i)}` | `iter 2-2 / expand_basis` |
| iter 2-2 | `build([Psi_keep^{(1)}, P^{(2)}]) -> H_sub^{(2)}, S_sub^{(2)}` | retained basis `2945 × 16` + new block `2945 × 16` | `H_sub^{(2)}/S_sub^{(2)}` 各 `32 × 32` = 16.00 KiB | full-space vectors 被投影到 reduced subspace，所以统一改记为 `H_sub` / `S_sub` | `iter 2-3 / post_diag` |
| iter 2-3 | `(H_sub^{(2)}, S_sub^{(2)}) -> (C^{(2)}, Lambda^{(2)})` | `H_sub^{(2)}/S_sub^{(2)}` `32 × 32` | `C^{(2)}` `32 × 16` = 8.00 KiB + `Lambda^{(2)}` `16` = 128 B; `notcnv = 3` | reduced eigensolver 输出不再是 basis block，而是 reduced coefficient + eigenvalue，所以改记为 `C/Lambda` | `iter 2-4 / refresh_basis` |
| iter 2-4 | `C^{(2)} -> [X^{(2)}, HX^{(2)}, SX^{(2)}] -> [Psi_keep^{(2)}, HPsi_keep^{(2)}, SPsi_keep^{(2)}]` | expanded basis/operator blocks `2945 × 32` + `C^{(2)}` `32 × 16` | refreshed resident state 三个 `2945 × 16` block，各 736.25 KiB | reduced coefficient 回到 full space 先形成 Ritz block `X/HX/SX`，再压回 retained basis resident state，所以 `C -> X -> Psi_keep` | 再经 residual / precondition / ortho 生成 `P^{(3)}`，其 trace block size 为 `m = 3` |
| iter 3-1 | `P^{(3)} -> [P^{(3)}, HP^{(3)}, SP^{(3)}]` | 前一轮 residual / precondition 路径输出，trace 可见 block size `m = 3` | 三个 `2945 × 3` block，各 138.05 KiB | 新增 correction block 不再属于 retained basis，所以单独改记为 `P^{(i)}` | `iter 3-2 / expand_basis` |
| iter 3-2 | `build([Psi_keep^{(2)}, P^{(3)}]) -> H_sub^{(3)}, S_sub^{(3)}` | retained basis `2945 × 16` + new block `2945 × 3` | `H_sub^{(3)}/S_sub^{(3)}` 各 `19 × 19` = 5.64 KiB | full-space vectors 被投影到 reduced subspace，所以统一改记为 `H_sub` / `S_sub` | `iter 3-3 / post_diag` |
| iter 3-3 | `(H_sub^{(3)}, S_sub^{(3)}) -> (C^{(3)}, Lambda^{(3)})` | `H_sub^{(3)}/S_sub^{(3)}` `19 × 19` | `C^{(3)}` `19 × 16` = 4.75 KiB + `Lambda^{(3)}` `16` = 128 B; `notcnv = 0` | reduced eigensolver 输出不再是 basis block，而是 reduced coefficient + eigenvalue，所以改记为 `C/Lambda` | `iter 3-4 / converged_exit` |
| iter 3-4 | `C^{(3)} -> [X_conv^{(3)}, HX_conv^{(3)}, SX_conv^{(3)}]` | expanded basis/operator blocks `2945 × 19` + `C^{(3)}` `19 × 16` | final converged blocks 三个 `2945 × 16`，各 736.25 KiB | 最后一轮不再 refresh，而是直接输出收敛 Ritz block，所以改记为 `X_conv/HX_conv/SX_conv` | `converged_exit / SCF step done` |

### 6.2 peak SCF step 的显式重复模式

peak step（SCF iter `6`）内部一共跑了 `19` 次 reduced solve。它和 nominal step 走的是同一个数据流模板，只是 `notcnv` 下降更慢，所以 `expand -> diag -> refresh -> residual` 这组动作被重复了更多次。

peak step 的单轮模板仍然是：

1. `P^{(i)}` 进入，并形成 `HP^{(i)}` / `SP^{(i)}`
2. `[Psi_keep^{(i-1)}, P^{(i)}] -> H_sub^{(i)}, S_sub^{(i)}`
3. `(H_sub^{(i)}, S_sub^{(i)}) -> (C^{(i)}, Lambda^{(i)})`
4. `C^{(i)} -> X^{(i)}/HX^{(i)}/SX^{(i)} -> refresh or converged_exit`

下面把 peak step 每一轮的尺寸变化显式列出，便于你做最坏情况 buffer / scheduler 规划。

| solver iter | 新增 block `p` | expanded `n_prev + p -> n` | `diag` 后 `notcnv` | refresh? | 下一轮 block |
| --- | ---: | --- | ---: | --- | ---: |
| 1 | 16 | `16 + 16 -> 32` | 16 | yes, back to n = 16 | 16 |
| 2 | 16 | `16 + 16 -> 32` | 16 | yes, back to n = 16 | 16 |
| 3 | 16 | `16 + 16 -> 32` | 14 | yes, back to n = 16 | 14 |
| 4 | 14 | `16 + 14 -> 30` | 11 | yes, back to n = 16 | 11 |
| 5 | 11 | `16 + 11 -> 27` | 9 | yes, back to n = 16 | 9 |
| 6 | 9 | `16 + 9 -> 25` | 7 | no, keep expanded n = 25 | 7 |
| 7 | 7 | `25 + 7 -> 32` | 7 | yes, back to n = 16 | 7 |
| 8 | 7 | `16 + 7 -> 23` | 4 | no, keep expanded n = 23 | 4 |
| 9 | 4 | `23 + 4 -> 27` | 3 | no, keep expanded n = 27 | 3 |
| 10 | 3 | `27 + 3 -> 30` | 3 | yes, back to n = 16 | 3 |
| 11 | 3 | `16 + 3 -> 19` | 3 | no, keep expanded n = 19 | 3 |
| 12 | 3 | `19 + 3 -> 22` | 3 | no, keep expanded n = 22 | 3 |
| 13 | 3 | `22 + 3 -> 25` | 3 | no, keep expanded n = 25 | 3 |
| 14 | 3 | `25 + 3 -> 28` | 3 | no, keep expanded n = 28 | 3 |
| 15 | 3 | `28 + 3 -> 31` | 3 | yes, back to n = 16 | 3 |
| 16 | 3 | `16 + 3 -> 19` | 2 | no, keep expanded n = 19 | 2 |
| 17 | 2 | `19 + 2 -> 21` | 1 | no, keep expanded n = 21 | 1 |
| 18 | 1 | `21 + 1 -> 22` | 1 | no, keep expanded n = 22 | 1 |
| 19 | 1 | `22 + 1 -> 23` | 0 | no, converged_exit | 0 |

## 7. 面向数据流规划的建议

### 7.1 第一优先：`h_psi / s_psi` 主数据通路

建议把这条路拆成两个可以流水的域：

1. `FFT + local potential` 域：处理 `psi(G) <-> psi(r)` 和 `Veff(r)` 点乘
2. `projector` 域：处理 `beta^H psi -> coeff mix -> beta d`

原因：

- `beta(G)` 常量尺寸已经达到 6.47 MiB，足够值得做强复用；
- `Veff(r)` 只有 364.50 KiB，更适合按 SCF step 级别装载并在多个 `h_psi` 调用间复用；
- `h_psi` 同时含 FFT-heavy 和 projector-heavy 两类算子，带宽/访存模式并不一样，拆域比强行做一个单核更自然。

### 7.2 第二优先：`Psi/HPsi/SPsi` 与 `C` 的 companion GEMM

`refresh_basis` 和 `subspace_build` 的输入虽然都不大，但它们直接连着 solver 控制流，适合作为 chip 的 companion dense kernel。

### 7.3 第三优先：`rho_out` 组装

如果后续要把 SCF loop 拉成更完整的端到端 demo，可以把 charge assembly 加进去；这条路的关键仍然是 batched FFT 和 grid reduction。

### 7.4 暂缓：`cdiaghg` 与 `mix_rho`

- `cdiaghg` 的数据量只有几十 KiB，控制复杂度大于算力价值；
- `mix_rho` 的输入输出都是单个 density grid，算术强度很低；
- `newd` 虽然在 USPP 下有时间占比，但它更适合后续作为 host/FPGA companion path 单独分析。

## 8. 这次实验应该怎么继续扩展

如果你下一步要把这个实验变成 chip/FPGA 设计输入，我建议按下面的顺序继续：

1. 先以本报告的 nominal / peak `h_psi` block 序列，定义 on-chip buffer 容量与块调度；
2. 再把 `beta(G)`、`Veff(r)`、`Psi/HPsi/SPsi` 区分为 `SCF-step resident` 和 `call-streamed` 两类对象；
3. 最后单独给 `newd` 做 companion-path 分析，决定它留在 CPU 还是下沉到 FPGA。

如果只问“绝对什么部分真的要跑加速”，当前证据最强的答案是：

- 必加速：`h_psi` 的 FFT + projector 主路，以及 `s_psi` projector 主路
- 可以顺带做：basis refresh / subspace build companion GEMM
- 不必抢先做：`cdiaghg`、`mix_rho`，以及尚未细化建模的 `newd`

