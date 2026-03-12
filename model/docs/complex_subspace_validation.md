# 复数子空间行为级验证结果

## 1. 验证目的

这份文档对应的是**探索性支线验证**，不是当前系统的主设计路线。当前主设计已经明确为完整的 Ozaki-II / CRT `FP64` 复数 GEMM，见 [model/docs/complex_ozaki_fp64_validation.md](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md)。

本验证针对 [`docs/design.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/design.md) 中提出的复数子空间数据通路，检查以下问题：

- 以实数 CIM primitive 组合出的复数 4M / 3M 路径是否正确
- 在低精度实数 primitive 下，`H X` / `S X` 的误差有多大
- 由 `X^H (H X)`、`X^H (S X)` 构造出的子空间矩阵误差是否可控
- 低精度下 `S_sub` 的正定性是否还能维持

## 2. 验证模型

验证程序为：

- [`tb_complex_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_complex_subspace.cpp)

构建命令：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
make bin/complex_subspace_eval
```

运行命令：

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
./bin/complex_subspace_eval
```

默认配置：

- `N = 24`
- `m = 8`
- `trials = 12`
- `seed = 20260312`

矩阵生成方式：

- `H`：随机复数 Hermitian
- `S`：随机复数 Hermitian 正定
- `X`：随机复数 block vector，并做列正交化

验证路径：

1. 参考路径：CPU `FP64` 直接复数 GEMM
2. 加速路径：通过 `CIM_Macro` 的实数 primitive 组合成复数 4M / 3M
3. 输出指标：
   - `HX_rel`：`H X` 相对 Frobenius 误差
   - `SX_rel`：`S X` 相对 Frobenius 误差
   - `Hsub_rel`：`X^H (H X)` 相对 Frobenius 误差
   - `Ssub_rel`：`X^H (S X)` 相对 Frobenius 误差
   - `Hherm` / `Sherm`：Hermitian 缺陷
   - `rawSPD`：原始 `S_sub` 是否通过 Cholesky
   - `symSPD`：Hermitian 化后的 `S_sub` 是否通过 Cholesky

## 3. 实测结果

| 模式 | HX_rel | SX_rel | Hsub_rel | Ssub_rel | Hherm | Sherm | Hsub_max | Ssub_max | rawSPD | symSPD |
|------|-------:|-------:|---------:|---------:|------:|------:|---------:|---------:|-------:|-------:|
| FP64-4M | 2.58966e-16 | 2.56169e-16 | 2.85237e-16 | 2.45061e-16 | 2.85648e-16 | 2.00028e-16 | 3.19119e-16 | 3.22171e-16 | 12/12 | 12/12 |
| FP32-4M | 4.76485e-08 | 5.12108e-08 | 5.85114e-08 | 4.56912e-08 | 6.23409e-08 | 4.18421e-08 | 6.81972e-08 | 6.00822e-08 | 0/12 | 12/12 |
| FP32-3M | 6.91858e-08 | 6.74499e-08 | 8.33792e-08 | 6.46756e-08 | 1.22576e-07 | 8.73210e-08 | 9.47035e-08 | 7.36937e-08 | 0/12 | 12/12 |
| BF16-4M | 1.10507e-02 | 1.16156e-02 | 2.03601e-02 | 2.14862e-02 | 4.26246e-03 | 2.92914e-03 | 2.13861e-02 | 2.29353e-02 | 0/12 | 12/12 |
| BF16-3M | 1.14330e-02 | 1.19467e-02 | 2.05002e-02 | 2.13878e-02 | 7.71546e-03 | 6.28273e-03 | 2.12616e-02 | 2.27725e-02 | 0/12 | 12/12 |
| INT8_EMU-4M | 9.50177e-03 | 1.27339e-02 | 1.01968e-02 | 8.81079e-03 | 7.92959e-03 | 4.69968e-03 | 1.18272e-02 | 9.46795e-03 | 0/12 | 12/12 |
| INT8_EMU-3M | 1.37311e-02 | 1.80416e-02 | 1.51467e-02 | 1.27724e-02 | 2.15190e-02 | 1.76596e-02 | 2.00231e-02 | 1.41611e-02 | 0/12 | 12/12 |

## 4. 结果解读

### 4.1 路径正确性

- `FP64-4M` 与参考基本一致，说明这套复数拆分测试路径在行为级上是通的。
- `FP32/BF16/INT8_EMU` 的结果说明，在当前这份探索性 testbench 里，不同底层精度实现会得到不同的数值表现。

这里需要特别说明：

- 本文档记录的是**这一份探索性 testbench 的观测结果**
- 不应把这些结果泛化成“3M 算法本身会带来额外误差”的结论
- 从算法上讲，`3M` 与 `4M` 是等价的；差异来自具体实现与所选底层数值格式

### 4.2 `S_sub` 必须显式做 Hermitian 化

低精度路径下 `rawSPD` 全部失败，而 `symSPD` 全部恢复为 `12/12`。这说明：

- 数值误差首先破坏的是严格 Hermitian 结构
- 不做对称化时，Cholesky 很容易因为微小的反 Hermitian 噪声失败
- 一次显式的 `0.5 * (S_sub + S_sub^H)` 是必要的系统步骤

这条结论对后续广义本征值路径非常关键。

## 5. 当前结论

基于这组行为级结果，当前能确认的是：

- 这套探索性复数 block MVM 数据流是可运行的
- `S_sub` 在低精度实现下需要显式 Hermitian 化
- 不同底层数值格式会影响观测到的误差水平

这组结论只服务于探索性支线，也就是：

- `H_sub X / S_sub X` 的数据流研究
- 低精度 block MVM 的数值行为观察

它不应被误读为当前主设计的复数 `FP64` 乘法方案。

## 6. 后续工作

当前验证程序使用的是 `INT8_EMU` 行为模型，还不是完整的 Ozaki 模取/重构实现。下一步建议是：

1. 将 `INT8_EMU` 替换为更接近师兄设计的 Ozaki 实数 primitive
2. 在 NML 侧补上 direct dense 微求解器或 `3m x 3m` 微型广义本征求解器模型
3. 把当前 4M / 3M 复数调度器接到更真实的阵列延迟与带宽模型
4. 将 `S_sub` 的 Hermitian 化与 Cholesky 检查并入统一近存控制逻辑

当前结果需要特别说明的一点是：

- 本文档验证的是**乘法与子空间矩阵构造路径**
- 还没有把 LOBPCG / Rayleigh-Ritz / `diaghg` 风格微对角化器并入同一个行为级闭环

也就是说，这一版已经回答了“复数阵列怎么给对子空间求解器喂 `H X` 和 `S X`”，但还没有回答“近存逻辑里的微型 eigensolver 具体怎么建模”。这一部分已经在新版设计手册中单独展开。
