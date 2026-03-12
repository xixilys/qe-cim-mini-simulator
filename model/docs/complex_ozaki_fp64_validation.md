# 复数 Ozaki-II FP64 GEMM 行为级验证

## 1. 目的

本文档对应仓库中新加入的完整 `FP64` 复数矩阵乘法 emulation 原型：

- [`tb_complex_ozaki.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_complex_ozaki.cpp)

它的目标不是近似求一个“差不多”的复数 GEMM，而是基于 Uchino 等 2025 的复数 Ozaki-II 思路，行为级打通这条完整链：

1. 缩放与截断
2. 多模 residue 生成
3. 模域 Karatsuba 3M
4. CRT 重构
5. 反缩放回 `FP64 complex`

## 2. 当前实现边界

这份原型重点验证的是**算法完整性与数值结果**，而不是最终硬件时序最优实现。

当前实现包含：

- 13 个互素模数的 `ZGEMM` 风格配置
- 对复数实部/虚部分别缩放
- 模域下的 Karatsuba 三乘法
- `n` 方向 block 化接口
- CRT 重构与反缩放

当前还没有做的部分：

- 论文中完整的性能优化版 fast/accurate mode 硬件时序模型
- `s1 + s2` 型高精度重构流水的片上资源拆分
- residue buffer / NoC / multi-array 并发建模

也就是说，这一版已经可以回答“这条算法链能不能把 `FP64 complex GEMM` 算出来”，但还没有回答“芯片上怎么做到最优吞吐”。

## 3. 构建与运行

构建：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
make bin/complex_ozaki_eval
```

默认运行：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
./bin/complex_ozaki_eval
```

更宽指数范围压力测试：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
OZAKI_EXP_SPAN=64 OZAKI_TRIALS=4 ./bin/complex_ozaki_eval
```

## 4. 默认配置结果

默认参数：

- `m = 16`
- `n = 16`
- `k = 32`
- `trials = 6`
- `exp_span = 24`
- `moduli = 13`

实测输出：

| Trial | rel_frob | rms_abs | max_abs |
|------:|---------:|--------:|--------:|
| 1 | 1.870973e-14 | 1.465573e+00 | 4.440827e+00 |
| 2 | 1.908101e-14 | 1.114226e+00 | 3.761654e+00 |
| 3 | 1.514504e-14 | 9.911303e-01 | 3.690809e+00 |
| 4 | 2.389939e-14 | 1.279113e+00 | 4.133649e+00 |
| 5 | 2.241383e-14 | 1.051377e+00 | 4.824804e+00 |
| 6 | 2.426961e-14 | 1.047751e+00 | 2.963612e+00 |

汇总：

- `avg_rel_frob = 2.058644e-14`
- `avg_rms_abs = 1.158195e+00`
- `max_rel_frob = 2.426961e-14`
- `max_abs = 4.824804e+00`

这里 `rms_abs` 和 `max_abs` 看起来不是很小，是因为输入矩阵含有较大的指数跨度，输出绝对值本身也较大；从 `rel_frob` 看，整体相对误差已经稳定在 `1e-14` 量级。

## 5. 更宽指数范围结果

压力参数：

- `exp_span = 64`
- `trials = 4`

实测输出：

| Trial | rel_frob | rms_abs | max_abs |
|------:|---------:|--------:|--------:|
| 1 | 1.978542e-14 | 3.746664e+23 | 2.026734e+24 |
| 2 | 1.191998e-14 | 2.045820e+23 | 9.279334e+23 |
| 3 | 1.183744e-14 | 2.796067e+23 | 1.905695e+24 |
| 4 | 1.034586e-14 | 1.846344e+23 | 8.329646e+23 |

汇总：

- `avg_rel_frob = 1.347218e-14`
- `avg_rms_abs = 2.608724e+23`
- `max_rel_frob = 1.978542e-14`
- `max_abs = 2.026734e+24`

这说明在更宽的指数范围下，算法仍然保持了 `1e-14` 量级的相对误差。

## 6. 结果解读

这组结果说明了三件事：

1. **完整链路已经闭环**
   - 这不再是 `INT8_EMU` 式近似，而是真正打通了 `CRT + Karatsuba + 反缩放` 的复数 `FP64` 路径。

2. **相对精度已经达到可接受的 `ZGEMM` 级别**
   - 在两组测试下，`rel_frob` 都稳定在 `1e-14` 左右。

3. **Karatsuba 在这里是安全的**
   - 因为它运行在模域整数上，不是之前近似子空间模式里的低精度浮点 3M，所以不会引入那类额外量化误差放大问题。

## 7. 对系统设计的直接影响

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
