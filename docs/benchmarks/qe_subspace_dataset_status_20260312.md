# QE 子空间矩阵数据集状态（2026-03-12）

## 1. 目标

当前我们要解决的问题不是系统加速比，而是先回答：

- `QE` 里真实送入子空间对角化器的矩阵到底长什么样
- 这些矩阵在不同体系类别下是否保持相同结构
- 当前数据集是否已经足够支撑系统设计约束

因此，数据集需要尽量覆盖不同类型工作负载，而不能只停留在单一 `Si`。

## 2. 当前已拿到的真实样本

### 2.1 半导体晶体：Si

来源：

- [`qe_si_medium_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_medium_trace.csv)
- [`qe_si_large_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_si_large_trace.csv)

结论：

- 路径：`cdiaghg`
- 结构：complex generalized Hermitian
- 主导维度：
  - `(16, 8)` / `(8, 8)`
  - `(32, 16)` / `(16, 16)`

### 2.2 金属磁性晶体：Fe

来源：

- [`qe_fe_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_fe_trace.csv)

输入：

- [`fe_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/fe_subspace_trace.in)

结论：

- 路径：`cdiaghg`
- 结构：complex generalized Hermitian
- 总调用：`788`
- generalized-like 占比：`614 / 788`
- 主导维度：
  - `(24, 12)` 出现 `249` 次
  - `(12, 12)` 出现 `174` 次
- `s_identity_rel` 最大达到 `9.337e-01`

这说明在磁性金属中：

- 子空间尺寸和 `Si` 明显不同
- overlap 路径更强，`S_sub` 更不能忽略

### 2.3 有机分子：C6H6

来源：

- [`qe_benzene_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_benzene_trace.csv)

输入：

- [`benzene_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/benzene_subspace_trace.in)

结论：

- 路径：`rdiaghg`
- 结构：real generalized Hermitian
- 当前拿到 `9` 次调用
- 主导维度：
  - `(60, 30)` 出现 `2` 次
  - `(30, 30)` 出现 `1` 次
  - 其他点包括 `(42,30)`, `(53,30)`, `(55,30)`

这组样本虽然 SCF 没跑完整，但已经足够说明一个重要事实：

- 分子 / 有机体系下，`Gamma` 实数路径同样会进入 generalized Hermitian 子空间问题
- 当 `nbnd = 30` 时，Davidson 子空间已经可以长到 `n = 60`

## 3. 当前数据集已经支持的判断

### 2.4 2D 材料：graphene

来源：

- [`qe_graphene_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_graphene_trace.csv)

输入：

- [`graphene_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/graphene_subspace_trace.in)

结论：

- 路径：`cdiaghg`
- 结构：complex generalized Hermitian
- 总调用：`148`
- generalized-like 占比：`112 / 148`
- 主导维度：
  - `(8, 4)` 出现 `74` 次
  - `(4, 4)` 出现 `36` 次

### 2.5 表面/slab 金属：Au slab

来源：

- [`qe_au_slab_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_au_slab_trace.csv)

输入：

- [`au_slab_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/au_slab_subspace_trace.in)

结论：

- 路径：`cdiaghg`
- 结构：complex generalized Hermitian
- 总调用：`261`
- generalized-like 占比：`222 / 261`
- 主导维度：
  - `(52, 26)` 出现 `71` 次
  - `(26, 26)` 出现 `39` 次

### 2.6 更大绝缘体超胞：SiC32

来源：

- [`qe_sic32_trace.csv`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_sic32_trace.csv)

输入：

- [`sic32_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/sic32_subspace_trace.in)

结论：

- 路径：`cdiaghg`
- 结构：complex generalized Hermitian
- 总调用：`17`
- generalized-like 占比：`14 / 17`
- 主导维度：
  - `(128, 64)` 出现 `8` 次
  - `(64, 64)` 出现 `3` 次

这组样本非常关键，因为它第一次把我们当前数据集直接推到了 `n = 128` 的量级。

## 3. 当前数据集已经支持的判断

基于 `Si + Fe + C6H6 + graphene + Au slab + SiC32`，我们已经可以更稳地说：

1. `QE` 子空间矩阵不是单一模式
   - 既有 `cdiaghg`
   - 也有 `rdiaghg`

2. generalized Hermitian 是主路径
   - 在三类体系里都不是边角情况

3. 子空间维度强依赖体系和 `nbnd`
   - 小 `Si`: `n = 8 ~ 32`
   - `Fe`: `n = 12 ~ 24`
   - `C6H6`: `n = 30 ~ 60`
   - `Au slab`: `n = 26 ~ 52`
   - `SiC32`: `n = 64 ~ 128`

4. 单一 `Si` 样本不够
   - 如果只看 `Si`，会低估分子/有机体系的 `m` 和 `n`
   - 也会低估某些金属体系里 `S_sub` 偏离单位阵的程度
   - 还会低估更大超胞中 `n = 128` 这类对子空间微对角化器尺寸规划非常关键的点

## 4. 下一批最值得补的样本

为了让数据集更完整，下一批建议优先补：

1. 再补一个更大的有机/分子样本
   - 当前 `C6H6` 已经有了，但只拿到第一轮 SCF 的有效 trace

2. 再补一个真正的 `Gamma-only` 晶体样本
   - 目前 `C6H6` 是 `rdiaghg`
   - 但还缺一个固体 `Gamma` 代表

3. 再补一个更大的异质晶体超胞
   - 例如 [`bn32_pbe0.scf.in`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/benchmark/bn32_pbe0.scf.in)
   - 用来和 [`sic32_subspace_trace.in`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_inputs/sic32_subspace_trace.in) 做横向对比

这样一来，数据集就能覆盖：

- 分子/有机
- 半导体晶体
- 金属磁性晶体
- 2D 材料
- 表面/slab
- 大超胞

## 5. 当前结论

所以，当前阶段最合理的方向不是去急着报加速比，而是继续把这套矩阵画像数据集补成体系化集合。  
现在我们已经从“只有 Si”走到了“Si + Fe + C6H6 + graphene + Au slab + SiC32”，而且已经覆盖了：

- 分子/有机
- 半导体晶体
- 金属磁性晶体
- 2D 材料
- 表面/slab
- 更大超胞

这套数据集已经足够支撑系统设计章节里的 workload 画像；后面再补 2 到 3 个点，主要是为了把边界补齐，而不是从零开始。
