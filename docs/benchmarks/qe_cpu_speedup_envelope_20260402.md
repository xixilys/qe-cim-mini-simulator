# QE `CPU only` 基线下的 speedup envelope（2026-04-02）

## 1. 作用

这份说明只回答一个问题：

> 如果未来的 `CPU + FPGA` 主要加速 `c_bands` 路径，或者更保守地只显著加速其中的 `h_psi` 主核，那么相对当前 `CPU only`，整个 `SCF iteration` 最多还能快多少？

这里所有数字都来自：

- `docs/benchmarks/archive/results/qe_cpu_shell_aggregate_extract_20260402.json`
- `docs/benchmarks/archive/results/qe_cpu_speedup_envelope_20260402.json`

它们的证据等级是：

- **基础 timing**：真实 QE `stdout` aggregate
- **speedup envelope**：由真实 CPU-only timing 通过 `Amdahl` 公式导出的上界或区间

因此这些数字**不是**：

- FPGA 实测
- clustered-FPGA latency model 的直接输出
- `CPU + FPGA` 已实现 speedup

## 2. 计算口径

对每个 case，先用真实 `CPU only` timing 求：

- `f_cbands = T_cbands / T_electrons`
- `f_hpsi = T_hpsi / T_electrons`

然后用：

- `S_total(accel) = 1 / ((1 - f) + f / accel)`

得到：

1. 当 `c_bands` 被加速 `2x / 4x / 8x / 16x` 时，整轮 `SCF iteration` 的理论 speedup；
2. 当只有 `h_psi` 被加速 `2x / 4x / 8x / 16x` 时，整轮 `SCF iteration` 的理论 speedup；
3. 当 `c_bands` 或 `h_psi` 变成“无限快”时，对应的 `Amdahl` 上界。

## 3. 结果摘要

| case | `c_bands / electrons` | `h_psi / electrons` | SCF upper bound if `c_bands -> inf` | SCF upper bound if `h_psi -> inf` |
| --- | ---: | ---: | ---: | ---: |
| `si4_pbe_uspp_small` | `0.486` | `0.286` | `1.94x` | `1.40x` |
| `si8_pbe_uspp` | `0.516` | `0.308` | `2.07x` | `1.44x` |
| `graphene_pbe_uspp` | `0.659` | `0.366` | `2.93x` | `1.58x` |
| `au_slab_subspace` | `0.640` | `0.454` | `2.78x` | `1.83x` |
| `sic32_subspace` | `0.675` | `0.510` | `3.08x` | `2.04x` |

## 4. 如果 `c_bands` 不是无限快，而只是有限加速

### 4.1 当 `c_bands` 加速 `4x`

| case | whole-SCF speedup |
| --- | ---: |
| `si4_pbe_uspp_small` | `1.57x` |
| `si8_pbe_uspp` | `1.63x` |
| `graphene_pbe_uspp` | `1.98x` |
| `au_slab_subspace` | `1.92x` |
| `sic32_subspace` | `2.03x` |

### 4.2 当 `c_bands` 加速 `8x`

| case | whole-SCF speedup |
| --- | ---: |
| `si4_pbe_uspp_small` | `1.74x` |
| `si8_pbe_uspp` | `1.82x` |
| `graphene_pbe_uspp` | `2.36x` |
| `au_slab_subspace` | `2.27x` |
| `sic32_subspace` | `2.44x` |

## 5. 对当前项目的直接含义

### 5.1 能不能只看 `h_psi`

不能只看。

从 `CPU only` 的真实 timing 看，`h_psi` 虽然是大头，但若未来硬件只把 `h_psi` 做到极致，而 `c_bands` 的其他部分仍然留在 CPU 路径里，那么整轮 `SCF iteration` 的理论上界只有：

- `1.40x`（`small-Si`）
- `1.44x`（`Si`）
- `1.58x`（`graphene`）
- `1.83x`（`Au slab`）
- `2.04x`（`SiC32`）

这说明如果想把系统 speedup 做到 `2x+`，只优化 `h_psi` 往往不够，`build H_sub/S_sub`、`cdiaghg`、`refresh/residual -> P_next` 继续进入硬件主路径是有系统价值的。

### 5.2 为什么 `Au slab` 和 `SiC32` 更值得优先看

这两个 case 的 `c_bands / electrons` 占比已经到：

- `0.640`
- `0.675`

因此只要 `c_bands` 这条内环真的被有效压缩，它们对整个 `SCF iteration` 的系统收益会比 `Si` 更敏感。

这也意味着：

- `Au slab`
- `SiC32`

应继续保留为后续 `CPU + FPGA` 首轮 win-region 判断的主 case。

## 6. 当前不能说什么

基于这份 envelope，还**不能**说：

- `CPU + FPGA` 已经实现了 `2x` 或 `3x`
- 你的 clustered hardware `cdiaghg` 方案一定能达到这里的上限
- 相比 `CPU + GPU` 一定有优势

这份 envelope 只能说：

1. 纯看 `CPU only` 实测，`c_bands` 确实已经足够大，值得做；
2. 如果硬件真的把 `c_bands` 主路径压下去，整轮 `SCF iteration` 的收益上限在当前五个 case 上大约是 `1.94x ~ 3.08x`；
3. 如果硬件只显著加速 `h_psi`，那系统收益上限明显更低。

## 7. 一句话结论

基于当前五个 case 的真实 `CPU only` timing，**你的硬件切口是值得的**；但现在能给出的，是：

- 一个对纯 CPU 的**实测驱动 speedup envelope**

而不是：

- 一个已经被验证的 `CPU + FPGA` 实现 speedup。
