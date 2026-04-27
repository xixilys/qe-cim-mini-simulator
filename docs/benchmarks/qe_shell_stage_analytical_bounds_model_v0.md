# QE shell per-stage analytical bounds model（v0，2026-04-02）

## 0. 目的

这份文档用于完成 `Task 4`：给 `QE-connected band-solver subsystem` 建立第一版 **per-stage analytical bounds model**。

这不是最终 cycle-accurate 结果，而是：

- 统一每个阶段的 `Ops / Bytes / AI` 口径；
- 给出 `T_compute_lb` 与 `T_bw_lb` 的公式；
- 为后续 `SystemC shell-level` 模型提供上界/下界与瓶颈判断依据。

当前版本采用两层输出：

1. **symbolic formulas**：可迁移到其他 case；
2. **reference proxy instantiation**：以 `si8_pbe_uspp` 的峰值型 block (`npw=2945`, `m=16`, `n_prev=16`, `p=16`, `n=32`, FFT grid `36×36×36`) 作为参考代理。

## 1. 统一记号与假设

### 1.1 数据类型假设

- complex FP64 element：`b_c = 16 bytes`
- real FP64 element：`b_r = 8 bytes`

### 1.2 lower-bound bytes 的定义

本文件中的 `Bytes` 默认指：

> **在理想 residency 假设下，阶段为完成本职功能而必须跨 accelerator-memory 边界搬运的最小 compulsory bytes**。

也就是说：

- 已明确可 resident 的对象（如 `beta/projector`, `Veff(r)`, 小 reduced matrices）在该阶段 lower bound 中默认不反复计入；
- 如果某对象在阶段之间必须重新装载，则计入 `Bytes`；
- 阶段内部临时 working set 另外用 `working-set note` 解释，而不混入 compulsory `Bytes`。

### 1.3 lower-bound 时间公式

对于任一 stage：

- `AI = Ops / Bytes`
- `T_compute_lb = Ops / P_peak`
- `T_bw_lb = Bytes / B_eff`
- `T_stage_lb = max(T_compute_lb, T_bw_lb)`

其中：

- `P_peak`：该 baseline 在该 stage 可用的有效峰值算力
- `B_eff`：该 baseline 在该 stage 的有效边界带宽

### 1.4 FFT 估算口径

对当前 `si8` 参考代理，我们采用校准过的 v0 口径：

- 单次 3D FFT / iFFT 估算为 `~ 5 * N_grid * log2(N_grid)` real-flop

这来自对本地 `h_psi` 参考量级的反推，只作为 v0 analytical model 的统一口径，不等于最终实现成本。

## 2. Stage formulas

### 2.1 `rho -> Veff`

Symbolic:

- `Ops_rho_veff ≈ 2 * 5 * N_grid * log2(N_grid) + O(N_grid)`
- `Bytes_rho_veff = 2 * N_grid * b_r`

Reference (`N_grid = 46656`):

- `Ops ≈ 7.423 M real-flop`
- `Bytes = 729.00 KiB`
- `AI ≈ 9.94 ops/byte`
- bound hint: **bandwidth-sensitive / regular grid path**
- working-set note: output `Veff(r)` is only `364.50 KiB`, so it is an attractive SCF-step resident object.

### 2.2 `h_psi`

Symbolic:

- `Ops_hpsi ≈ 2 * m * 5 * N_grid * log2(N_grid) + O(npw*m) + O(N_grid*m) + O(npw*nkb*m)`
- `Bytes_hpsi = 2 * npw * m * b_c`  (ideal residency: `Veff(r)` and `beta/D` resident)

Reference:

- `Ops ≈ 227.447 M real-flop`
- `Bytes = 1.438 MiB`
- `AI ≈ 150.84 ops/byte`
- bound hint: **compute-heavy at boundary, but on-chip memory pressure is high**
- working-set note: `psi(G) -> psi(r)` expands from `736.25 KiB` to `11.39 MiB`; `beta(G)` resident state is ~`6.47 MiB`.

### 2.3 `s_psi`

Symbolic:

- `Ops_spsi ≈ O(npw*nkb*m) + O(nkb*m)`
- `Bytes_spsi = 2 * npw * m * b_c` (ideal residency: `beta/Q` resident)

Reference:

- `Ops ≈ 110.080 M real-flop`
- `Bytes = 1.438 MiB`
- `AI ≈ 73.01 ops/byte`
- bound hint: **projector-dense / array-friendly**
- working-set note: no FFT inflation, but projector resident state dominates locality planning.

### 2.4 `build H_sub / S_sub`

Symbolic (first expand style):

- `Ops_build ≈ 4 * npw * n_prev * p * c_cmac + O(n^2)` where `c_cmac ≈ 8 real-flop/complex MAC`
- `Bytes_build = 4 * npw * p * b_c + 2 * n_prev^2 * b_c + 2 * n^2 * b_c`

Reference (`n_prev=16`, `p=16`, `n=32`):

- `Ops ≈ 24.127 M real-flop`
- `Bytes = 2.915 MiB`
- `AI ≈ 7.89 ops/byte`
- bound hint: **moderate AI; highly sensitive to basis/operator block residency**
- working-set note: output is tiny (`32.00 KiB`), but inputs are full-space blocks.

### 2.5 `cdiaghg`

Symbolic:

- `Ops_cdiaghg ≈ κ_diag * n^3 + O(n^2*m)`
- `Bytes_cdiaghg = 2 * n^2 * b_c + n*m*b_c + m*b_r`

Reference (`n=32`, `m=16`):

- `Bytes = 40.12 KiB`
- `Ops`: keep symbolic in v0; exact constant depends on chosen generalized eigensolver implementation
- bound hint: **small-I/O companion path; lower-bound comparison alone is not decisive**
- working-set note: architecture decision here is dominated by control/companion placement, not by shell-level traffic volume.

### 2.6 `refresh / residual -> P_next`

Symbolic:

- `Ops_refresh >= O(npw*n*m)` from `X/HX/SX` rebuild, plus `O(npw*m)` residual/precondition, plus `O(npw*m*p)` orthogonalization
- `Bytes_refresh = 3*npw*n*b_c + 4*npw*m*b_c + n*m*b_c + m*b_r`

Reference (`n=32`, `m=16`, `p≈16` upper block):

- `Known Ops lower-bound ≈ 36.753 M real-flop`  (only the explicitly quantified `X/HX/SX + R` part)
- `Bytes = 7.198 MiB`
- `AI_known_lb ≈ 4.87 ops/byte`
- bound hint: **mixed / bandwidth-sensitive unless refreshed state stays resident**
- working-set note: this stage is the main reason the shell cannot be judged only by reduced-matrix costs.

### 2.7 `psi -> rho_out`

Symbolic:

- `Ops_psi_rho ≈ m * 5 * N_grid * log2(N_grid) + O(N_grid*m)`
- `Bytes_psi_rho = npw*m*b_c + N_grid*b_r`

Reference:

- `Ops ≈ 61.576 M real-flop`
- `Bytes = 1.075 MiB`
- `AI ≈ 54.63 ops/byte`
- bound hint: **FFT-dominated shell wrapper path**
- working-set note: not a v1 chip hotspot, but relevant to SCF-iteration latency accounting.

### 2.8 `mix_rho`

Symbolic:

- `Ops_mix = 3 * N_grid`
- `Bytes_mix = 3 * N_grid * b_r`

Reference:

- `Ops ≈ 0.140 M real-flop`
- `Bytes = 1093.50 KiB`
- `AI ≈ 0.125 ops/byte`
- bound hint: **strongly bandwidth-bound / host-friendly companion path**

## 3. Consolidated reference table (`si8_pbe_uspp` peak-style proxy)

| stage | Ops (real-flop est.) | Bytes (lower-bound) | AI (ops/byte) | v0 bound hint |
| --- | ---: | ---: | ---: | --- |
| `rho -> Veff` | 7.423 M | 729.00 KiB | 9.94 | bandwidth-sensitive |
| `h_psi` | 227.447 M | 1.438 MiB | 150.84 | compute-heavy at boundary |
| `s_psi` | 110.080 M | 1.438 MiB | 73.01 | projector-dense |
| `build H_sub/S_sub` | 24.127 M | 2.915 MiB | 7.89 | moderate AI |
| `cdiaghg` | symbolic `κ_diag n^3` | 40.12 KiB | implementation-dependent | companion-dominated |
| `refresh/residual -> P_next` | >= 36.753 M | 7.198 MiB | >= 4.87 | mixed / residency-sensitive |
| `psi -> rho_out` | 61.576 M | 1.075 MiB | 54.63 | FFT-dominated |
| `mix_rho` | 0.140 M | 1093.50 KiB | 0.125 | strongly bandwidth-bound |

## 4. 解析模型的直接结论

### 4.1 对 v1 硬件热点的判断

在当前口径下：

- `h_psi`：是第一主热点；
- `s_psi`：是第二主热点；
- `build H_sub/S_sub`：虽然输出小，但 full-space input 使其依然重要；
- `refresh/residual -> P_next`：是 shell-level 闭环中不能忽略的 companion-hot path；
- `cdiaghg`：I/O 很小，更像 companion placement 问题，而不是第一主流量热点；
- `mix_rho`：AI 极低，不应抢先进入 v1 chip datapath。

### 4.2 为什么不能只拿 reduced solve 讲系统性能

参考代理上：

- `build` 的输出只有小矩阵；
- `cdiaghg` 的输入输出也很小；
- 但 `h_psi / s_psi / refresh` 都仍然围绕 `npw × n` 级对象展开。

因此：

> 系统胜负主要由 repeated operator application 与 refresh path 决定，而不是由 `32 × 32` 小矩阵解本身决定。

### 4.3 这份 v0 模型的局限

- `cdiaghg` 仍只有 order-level `Ops` 口径，常数项待后续 companion implementation 校准；
- `refresh` 的正交化与预条件部分目前只纳入了 lower-bound 的已知显式项；
- `rho -> Veff` 与 `psi -> rho_out` 在当前项目中更偏 shell wrapper / host-side accounting，而不是 v1 芯片主核。

这些都不影响 v0 的主要用途：

- 快速给每个 stage 打上 compute-/bandwidth-sensitive 标签；
- 为 `SystemC` shell-level 模型提供合理的初始边界；
- 为 `CPU only / CPU + GPU / CPU + FPGA` 的公平比较提供统一 analytical 口径。

## 5. 对下一步的支持

这份文档冻结后，`Task 5` 可以直接把每个 stage 的：

- `T_compute_lb`
- `T_bw_lb`
- overlap 候选
- resident object 假设
- FIFO / double-buffer 假设

带入 `SystemC` shell-level 模型，而不需要重新定义 stage 口径。
