# 复数 Ozaki-II FP64 GEMM 行为级验证

## 1. 目的

本文档对应仓库中新加入的完整 `FP64` 复数矩阵乘法 emulation 原型：

- [`tb_complex_ozaki.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/ozaki_subspace_model/src/tb_complex_ozaki.cpp)

它的目标不是近似求一个“差不多”的复数 GEMM，而是基于 Uchino 等 2025 的复数 Ozaki-II 思路，行为级打通这条完整链：

1. 缩放与截断
2. 多模 residue 生成
3. 模域 Karatsuba 3M
4. CRT 重构
5. 反缩放回 `FP64 complex`

## 2. 当前实现边界

这份原型重点验证的是**算法完整性与数值结果**，而不是最终硬件时序最优实现。

当前实现包含：

- 16 个互素模数的 `ZGEMM` 风格配置
- 对复数实部/虚部分别缩放
- 模域下的 Karatsuba 三乘法
- `n` 方向 block 化接口
- CRT 重构与反缩放

另外，这个 evaluator 现在还包含一条单独的乘法流程验证模式：

- `fused digit-residue scalar` 模式
  - 用 `8` 个常驻 `8-bit` 模存储输入尾数
  - 采用 `8 -> 11 -> 14` 的两次 promotion schedule
  - promotion 边界采用 `mixed-radix / Garner` 形式的 pure base extension
  - 用冗余模只做 signed range 判定，不再回到大整数 snapshot
  - 也就是说，当前验证版已经是“模域表示 -> 模域扩展 -> 新模 residue”的 datapath

当前还没有做的部分：

- 论文中完整的性能优化版 fast/accurate mode 硬件时序模型
- `s1 + s2` 型高精度重构流水的片上资源拆分
- residue buffer / NoC / multi-array 并发建模

也就是说，这一版已经可以回答“这条算法链能不能把 `FP64 complex GEMM` 算出来”，但还没有回答“芯片上怎么做到最优吞吐”。

## 3. 构建与运行

构建：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
make -C model/ozaki_subspace_model bin/complex_ozaki_eval
```

默认运行：

```bash
./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

运行 fused digit-residue 单乘验证：

```bash
OZAKI_MODE=fused_scalar ./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

更宽指数范围压力测试：

```bash
OZAKI_EXP_SPAN=64 OZAKI_TRIALS=4 ./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

更宽指数范围下运行 fused digit-residue 单乘验证：

```bash
OZAKI_MODE=fused_scalar OZAKI_EXP_SPAN=64 OZAKI_TRIALS=256 ./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

## 4. fused digit-residue 单乘验证

验证目标不是整块 `GEMM`，而是我们最近冻结下来的那条单乘流程：

1. `FP64` 标量先按 `53-bit mantissa` 量化成整数
2. resident operand 只常驻 `8` 个 base moduli
3. streaming operand 以 `8-bit` digit、`7-stage`、`MSB-first` 注入
4. `stage1` 结束后做一次 promotion，`8 -> 11`
5. `stage4` 结束后再做一次 promotion，`11 -> 14`
6. 末端用 `14` 个 active moduli 重构结果

默认压力参数：

- `trials = 512`
- `exp_span = 24`

实测输出：

- `exact_integer_match = 512 / 512`
- `direct_rns_match = 512 / 512`
- `avg_rel_vs_double = 0`
- `max_rel_vs_double = 0`
- `max_abs_vs_double = 0`

更宽指数范围压力参数：

- `trials = 256`
- `exp_span = 64`

实测输出：

- `exact_integer_match = 256 / 256`
- `direct_rns_match = 256 / 256`
- `avg_rel_vs_double = 0`
- `max_rel_vs_double = 0`
- `max_abs_vs_double = 0`

这里的两个 match 指标分别表示：

- `exact_integer_match`
  - fused-digit 路径的整数结果是否与直接 `53b x 53b` 乘法完全一致
- `direct_rns_match`
  - fused-digit 路径的整数结果是否与“先完整分解到 `14` 个 active 模、再直接做纯 RNS 乘法”的结果完全一致

这说明至少对“单次 mantissa 乘法 + 两次 promotion”这一层，当前 pure base extension 流程已经在行为级上完全打通。

### 2026-03-19 精度跟踪记录

本次记录对应的算法版本是：

- `resident = 8 x 8bit` base moduli
- `streaming = 7-stage, 8-bit, MSB-first digit`
- `promotion schedule = 8 -> 11 -> 14`
- `promotion datapath = pure base extension`
- `signed range handling = redundant modulus`

其中 promotion 已经不再使用“大整数 snapshot 重建 -> 再取新模”的过渡实现，而是：

1. 先由 base residues 生成 mixed-radix digits
2. 再直接在目标模上求值
3. 用冗余模判断当前值位于 `x_unsigned` 还是 `x_unsigned - M`

本次实际运行命令为：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
make -C model/ozaki_subspace_model bin/complex_ozaki_eval
OZAKI_MODE=fused_scalar OZAKI_TRIALS=512 ./model/ozaki_subspace_model/bin/complex_ozaki_eval
OZAKI_MODE=fused_scalar OZAKI_EXP_SPAN=64 OZAKI_TRIALS=256 ./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

本次记录结果为：

- 常规指数范围
  - `exact_integer_match = 512 / 512`
  - `direct_rns_match = 512 / 512`
  - `avg_rel_vs_double = 0`
  - `max_rel_vs_double = 0`
  - `max_abs_vs_double = 0`
- 宽指数范围
  - `exact_integer_match = 256 / 256`
  - `direct_rns_match = 256 / 256`
  - `avg_rel_vs_double = 0`
  - `max_rel_vs_double = 0`
  - `max_abs_vs_double = 0`

这条记录说明：

- 单次 mantissa 乘法在当前 `8 -> 11 -> 14` schedule 下是正确的
- pure base extension promotion 没有引入额外数值错误
- 这条链已经可以作为后续接入更大 `GEMM / projector` 行为级路径的精度基线

## 5. 默认配置结果

默认参数：

- `m = 16`
- `n = 16`
- `k = 32`
- `trials = 6`
- `exp_span = 24`
- `moduli = 16`

实测输出：

| Trial | rel_frob | rms_abs | max_abs |
|------:|---------:|--------:|--------:|
| 1 | 2.040217e-16 | 1.598145e-02 | 7.370298e-02 |
| 2 | 2.609567e-16 | 1.523844e-02 | 1.252439e-01 |
| 3 | 1.874256e-16 | 1.226561e-02 | 9.504316e-02 |
| 4 | 1.560375e-16 | 8.351241e-03 | 6.250191e-02 |
| 5 | 1.974924e-16 | 9.263872e-03 | 6.250031e-02 |
| 6 | 2.113235e-16 | 9.123116e-03 | 9.407496e-02 |

汇总：

- `avg_rel_frob = 2.028762e-16`
- `avg_rms_abs = 1.170395e-02`
- `max_rel_frob = 2.609567e-16`
- `max_abs = 1.252439e-01`

这里 `rms_abs` 和 `max_abs` 已经明显收敛，从 `rel_frob` 看，当前 `16` 模配置下整体相对误差稳定在 `1e-16` 量级。

## 6. 更宽指数范围结果

压力参数：

- `exp_span = 64`
- `trials = 4`

实测输出：

| Trial | rel_frob | rms_abs | max_abs |
|------:|---------:|--------:|--------:|
| 1 | 1.274929e-16 | 2.414268e+21 | 1.889004e+22 |
| 2 | 1.111733e-16 | 1.908062e+21 | 1.889181e+22 |
| 3 | 1.224126e-16 | 2.891451e+21 | 3.777934e+22 |
| 4 | 5.700725e-17 | 1.017364e+21 | 9.518234e+21 |

汇总：

- `avg_rel_frob = 1.045215e-16`
- `avg_rms_abs = 2.057786e+21`
- `max_rel_frob = 1.274929e-16`
- `max_abs = 3.777934e+22`

这说明在更宽的指数范围下，算法仍然保持了 `1e-16` 量级的相对误差。

## 7. 结果解读

这组结果说明了三件事：

1. **完整链路已经闭环**
   - 这不再是 `INT8_EMU` 式近似，而是真正打通了 `CRT + Karatsuba + 反缩放` 的复数 `FP64` 路径。

2. **相对精度已经达到可接受的 `ZGEMM` 级别**
   - 在两组测试下，`rel_frob` 都稳定在 `1e-16` 左右。

3. **Karatsuba 在这里是安全的**
   - 因为它运行在模域整数上，属于 Ozaki-II / CRT 主设计中的精确复数乘法分解。

## 8. 对系统设计的直接影响

有了这条行为级原型之后，系统设计的主路线已经可以明确收敛为：

- **完整 FP64 complex GEMM emulation 模式**
  - 服务于需要 `FP64` 复数输出的高精度路径
  - 强调缩放、模数管理、Karatsuba 模乘和 CRT 重构

仓库中仍保留一条探索性支线：

- **近似子空间验证模式**
  - 服务于 `H_sub X / S_sub X` 的数据流研究
  - 强调 block MVM、误差门控、Hermitian 化

也就是说，当前主设计已经不是“两条并列路线”，而是：

- 主线：Ozaki-II / CRT
- 支线：近似子空间验证
