# Adjoint-Aware Projector Primitive 规格说明 v0

## 1. 文档目的

这份文档用来定义我们下一阶段要重点探索的硬件原语。

它**不是**：

- 一个通用 `GEMM` 替代品
- 一个完整的特征值求解器
- 一个只讲精度格式的故事
- 一篇论文标题的最终版本

它**是**：

- 一个面向 `projector / basis / subspace` 类负载的 workload-native 原语
- 一个位于普通 `GEMM` 与完整迭代求解器之间的硬件契约
- 一个面向 `QE / VASP / PySCF` 类负载的候选电路创新点

这份文档要固定的核心思想是：

```text
投影 -> 小矩阵变换 -> 回投
```

也就是不再把整条数据流拆成若干个互相脱节的 `GEMM`、`transpose` 或软件 glue，而是把它视为一个完整的硬件原语。

## 2. 原语名称

当前工作名：

- `Adjoint-Aware Projector Primitive`

中文可表述为：

- `伴随感知型投影原语`
- `Bra-Ket 融合型投影原语`

简称可以使用：

- `AAP primitive`
- `Bra-Ket fused primitive`

这个名字强调的是硬件必须同时支持：

- 常驻的投影矩阵 / 基矩阵 `P`
- `P` 与 `P^H` 两种视图
- 可选的局部 reduced accumulation
- 一个局部的小中心矩阵 `M`

这个名字**故意不强调**：

- `FP64`
- `transpose`
- `Davidson`
- `QE`

因为这些要么是实现细节，要么是上层算法场景，不应该取代原语本体。

## 3. 核心数学语义

## 3.1 主算子

这个原语的中心语义是：

```text
Y = P M P^H X
```

其中：

- `P ∈ C^(N×K)`
  - 常驻的 projector / basis / ACE 向量 / beta projector / 子空间基
- `X ∈ C^(N×B)`
  - 流式输入的 block
- `M ∈ C^(K×K)`
  - 片上就地存放的小中心矩阵
- `Y ∈ C^(N×B)`
  - 输出 block

这个算子可以拆成三步：

```text
C = P^H X      （前向投影）
T = M C        （小矩阵中心变换）
Y = P T        （回投 / 合成）
```

这三步合起来，就是这个原语的最基本契约。

## 3.2 可选的 reduced 输出

很多工作负载不只需要 `Y`，还需要一个 reduced matrix。  
因此这个原语还应支持：

```text
G = X^H Y = X^H P M P^H X
```

因为已经有：

```text
C = P^H X
```

所以：

```text
G = C^H M C
```

这点非常重要，因为它意味着很多情况下：

- 并不需要把完整的 `Y` 先写回片外
- 再重新读回来做 reduced accumulation

而是可以直接在原语内部把 `G` 做出来。

## 3.3 实数与复数情况

实数情形下：

```text
P^H = P^T
```

复数情形下：

```text
P^H = conj(P)^T
```

这说明这个原语真正需要的是：

- `adjoint-aware`

而不是简单的：

- `transpose-aware`

所以“支持转置”只是这个原语里的一项硬件机制，不是这个原语的最终语义。

## 4. 操作数角色

## 4.1 常驻操作数：`P`

`P` 是最关键的常驻操作数。

典型含义包括：

- `QE` 的非局域 projector bank `vkb`
- `QE` 的 ACE projector `xi`
- 子空间基 `Q`
- 一组局域化 basis block
- 压缩后的低秩 basis 或辅助 basis

这个原语是否成立，首先取决于：

- `P` 能不能在一段时间内稳定常驻
- 它对多个 `X` 是否具有足够高的复用率

如果 `P` 自己也是高频变化的大矩阵，那这个原语很可能会退化回普通 `GEMM`。

## 4.2 流式操作数：`X`

`X` 是移动的输入操作数。

典型含义包括：

- 一批波函数 `psi`
- 一批 trial vectors
- 一批 residual / update block
- 一批 orbitals
- 一批 pair-density / orbital-pair block

这个原语默认的硬件假设是：

- `X` 的变化频率显著高于 `P`

也就是说：

- `P` 更像权重/基
- `X` 更像激活/流入 block

## 4.3 局部中心操作数：`M`

`M` 是刻意设计成“小而局部”的中心矩阵。

典型含义包括：

- 非局域赝势系数块 `D`
- reduced rotation matrix `U`
- reduced basis transform
- 小的对角 / 分块对角权重
- 压缩后的 screened kernel block

这里必须强调：

- `M` 不是那个大而重的常驻矩阵
- `M` 的价值在于它小，可以近原语就地计算

如果 `M` 本身也变成一个大而动态的矩阵，这个原语就会显著失去意义。

## 5. 原语模式族

完整的融合模式是：

```text
Y = P M P^H X
```

但为了让硬件复用同一套 resident organization，这个原语应该暴露一组模式，而不是只有一个模式。

## 5.1 `FWD_PROJ`

```text
C = P^H X
```

语义：

- 前向投影
- bra-side contraction
- 系数提取

典型用途：

- `<vkb|psi>`
- `<xi|phi>`
- `Q^H Z`

## 5.2 `CENTER_APPLY`

```text
T = M C
```

语义：

- 在投影后的小空间中做一次局部 dense 变换

典型用途：

- `D * becp`
- reduced coefficient update
- 在不离开近原语区域的情况下应用小矩阵

## 5.3 `BACK_PROJ`

```text
Y = P T
```

语义：

- ket-side synthesis
- 从小空间回投到大空间

典型用途：

- `vkb * ps`
- `xi * coeff`
- `X <- QY`

## 5.4 `FUSED_APPLY`

```text
Y = P M P^H X
```

语义：

- 完整的 projector sandwich

这是最重要的融合模式，因为它避免把中间大张量 `C`、`T` 暴露到片外或更高层 buffer。

## 5.5 `FUSED_REDUCE`

```text
G = X^H P M P^H X = C^H M C
```

语义：

- reduced matrix 构造
- Gram / overlap / projection result 生成

这对 subspace 类工作负载尤其关键，因为它可以直接省掉一次：

- 完整写回
- 再完整读回

的往返搬运。

## 6. 硬件边界

## 6.1 这个原语负责什么

这个原语负责：

- `P` 的常驻存储
- 以 forward / adjoint 两种视图读出 `P`
- 必要时对复数路径做 on-the-fly conjugation
- 消费流式输入 `X`
- 本地形成 `C = P^H X`
- 本地执行 `T = M C`
- 本地形成 `Y = P T`
- 可选地本地形成 reduced result `G`

## 6.2 这个原语不负责什么

这个原语不负责：

- 外层收敛判断
- residual 生成策略
- 正交化策略
- 完整 eigensolver 控制流
- host runtime 决策
- 整个应用级全局调度

这些职责属于原语上层的 engine / controller。

## 7. 抽象接口

一个中性的抽象接口可以写成：

```text
bind_projector(tag_P, N, K, layout, datatype)
load_projector(tag_P, P)

bind_center(tag_M, K, datatype)
load_center(tag_M, M)

run_aap(
    mode,
    tag_P,
    tag_M,
    X_desc,
    output_mask,
    flags
)
```

其中：

- `mode`
  - `FWD_PROJ`
  - `CENTER_APPLY`
  - `BACK_PROJ`
  - `FUSED_APPLY`
  - `FUSED_REDUCE`
- `output_mask`
  - 是否输出 `C`
  - 是否输出 `Y`
  - 是否输出 `G`
- `flags`
  - real / complex
  - conjugate enable
  - triangular compression enable
  - reduced-only writeback

这个接口刻意保持抽象，不预设：

- 模拟 CIM
- 数字 CIM
- SRAM / ReRAM / mixed

这样后续可以独立探索实现。

## 8. 最小微架构

## 8.1 常驻 projector banks

最基本需要：

- 用于存放 `P` 的常驻 bank
- 稳定的行/列 tile 索引方式
- 能同时服务 projection 和 back-projection 两个阶段

这里可以有两种实现思路：

- 只存一份 `P`，但提供 dual-view read
- 显式存多个 layout 变体

架构层真正要固定的是：

- 原语必须同时暴露 `P` 与 `P^H` 的能力

而不是提前规定：

- 一定得物理存两份

## 8.2 Adjoint / transpose access path

这就是“转置能力”真正所在的位置。

它至少需要支持：

- 为 `P T` 提供 forward-view read
- 为 `P^H X` 提供 adjoint-view read
- 在 complex mode 下进行共轭

这块是**机制**，不是我们最终要 claim 的整个创新点。

## 8.3 Projection accumulator

这块负责形成：

```text
C = P^H X
```

它需要支持：

- 沿大维度 `N` 的 block 累加
- 本地保留 `C`
- 在只需要部分系数时做压缩或裁剪

## 8.4 Small center matrix engine

这块负责：

```text
T = M C
```

要求是：

- 专门优化小 `K×K` 运算
- setup 开销低
- 能直接消费本地 `C`

它可以实现为：

- 近存逻辑里的小 dense 单元
- 一个紧凑的数字矩阵路径
- 或者一个特化的局部 datapath

这块不需要长成一个“大矩阵乘法引擎”。

## 8.5 Back-projection engine

这块负责：

```text
Y = P T
```

它复用前面的 resident `P` bank，但此时使用的是 forward view。

## 8.6 Reduced-result accumulator

这块是可选但很重要的。

它负责：

```text
G = X^H Y
```

或者在 `C` 已经存在时，直接负责：

```text
G = C^H M C
```

这块应尽量利用：

- Hermitian 对称性
- 三角压缩写出
- 局部累加
- reduced-only writeback

## 9. 数据流

## 9.1 完整融合数据流

理想的完整融合数据流是：

```text
X stream in
-> 以 adjoint 视图读取 P
-> 本地投影得到 C = P^H X
-> 本地小矩阵变换得到 T = M C
-> 以 forward 视图读取 P
-> 回投得到 Y = P T
-> 可选本地累加得到 G
-> 选择性写回 Y 和/或 G
```

## 9.2 为什么这值得做

如果按朴素方式拆成分立 kernel：

1. `C = P^H X`
2. 写回 `C`
3. `T = M C`
4. 写回 `T`
5. `Y = P T`
6. 写回 `Y`
7. 再读回 `Y`
8. 构造 `G = X^H Y`

那么会出现大量不必要的：

- 中间写回
- 中间读回
- 重复 projector 访问
- 重复编码和激活
- 不必要的全尺寸输出搬运

这个原语之所以值得定义，核心就在于它有机会减少这些代价。

## 10. 与 QE / VASP / PySCF 的关系

## 10.1 QE 非局域赝势 / PAW 类路径

`QE` 的非局域路径非常接近这个原语：

```text
becp = <vkb | psi>
ps   = D * becp
hpsi = hpsi + vkb * ps
```

它可以直接映射成：

- `P = vkb`
- `X = psi`
- `M = D`
- `Y = vkb * D * vkb^H * psi`

这是目前最干净、最标准的例子。

## 10.2 QE ACE / EXX 路径

`ACE` 类路径外形也一致：

```text
coeff = <xi | phi>
vv    = xi * coeff
```

它对应的是一个特例：

```text
Y = P I P^H X
```

这里：

- `P = xi`
- `M = I` 或一个接近单位阵的小系数变换

它给我们的硬件启发仍然是：

- `P` 复用很高
- `X` 流式输入
- 系数先在本地形成
- 再从小空间回投

## 10.3 QE / VASP 子空间旋转与 basis update

对 subspace 工作负载，这个原语不一定总是以完整 `P M P^H X` 的形式出现，但同一套模式族仍然成立。

例如：

```text
X <- QY
```

就是：

```text
BACK_PROJ with P = Q
```

而：

```text
Q^H Z
```

就是：

```text
FWD_PROJ with P = Q
```

进一步地，像下面这些 reduced build：

```text
Q^H H Q
Q^H S Q
```

可以拆成：

1. 先由别的原语形成 `Z = H Q` 或 `Z = S Q`
2. 再由这个原语做 `Q^H Z`

也就是说，即便完整 sandwich 被拆开，这个原语仍然是主路径的一部分。

## 10.4 PySCF FFTDF / pair-density 类路径

`PySCF` 不一定总是精确符合完整的 `P M P^H X` 形式，但它反复出现同样的骨架：

- 先形成 projected / paired coefficient
- 再作用一个结构化 kernel
- 再走 conjugate-related inverse / reconstruction
- 最后做 reduced accumulation

因此，这个原语族仍然 relevant，特别是在下面几个点上：

- adjoint-aware resident data
- local center transform
- reduced-only writeback

## 11. 为什么它不是“支持转置”

如果最后的 claim 只是：

- “这个宏支持 transpose”

那这个故事太浅了。

我们真正想定义的是：

- 一个 fused projector sandwich 原语
- 常驻的是 `P`
- 共用的是 forward / adjoint 两条数据通路
- 本地保留的是中间系数
- 可选本地输出 reduced result

在这个故事里：

- transpose / adjoint access path 是必要机制
- 但它只是一部分，不是原语本体

## 12. 为什么它不是“普通 GEMM”

当然，普通 `GEMM` 在功能上可以分步实现这件事。

但这个原语仍然与 `GEMM` 不同，因为它明确假设并利用了：

- 大操作数 `P` 是常驻且高复用的
- 中心矩阵 `M` 很小
- 中间系数 `C` 与 `T` 最好留在本地
- 很多时候 reduced result `G` 比完整 `Y` 更值钱
- Hermitian / conjugate / triangular 结构可以直接被利用

当这些假设成立时：

- `GEMM` 在功能上足够
- 但在语义和流量上未必高效

## 13. 成本优势必须来自哪里

如果这个原语最终要成立，它的优势必须至少来自下面几项中的一部分：

1. 比分解实现更少的 projector 读出次数
2. 更少的中间 SRAM / DRAM 写回
3. 更少的中间 SRAM / DRAM 读回
4. 共享 forward / adjoint 数据流带来的激活成本下降
5. 在只需要 `G` 时显著减少输出搬运
6. 单位有效 reduced result 的能耗更低

如果这些优势都拿不出来，那这个方向就不该继续坚持，而应退回：

- `GEMM + transpose/adjoint support`

## 14. 必须比较的基线

后续如果要写论文，至少需要和下面三类基线对比：

1. `GEMM baseline`
   - 显式拆成 `P^H X`、`M C`、`P T`

2. `GEMM + transpose-aware macro`
   - 仍然显式拆分
   - 但阵列提供更好的 transpose / adjoint 支持

3. `Fused AAP primitive`
   - 本地保留 `C/T`
   - 本地 reduced accumulation
   - selective writeback

这样才能把收益来源区分清楚：

- 到底是来自更好的 transpose 能力
- 还是来自 primitive 级别的融合

## 15. v0 非目标

为了不把边界拉爆，v0 阶段**不打算**解决：

- 完整 FFT-integrated flow
- 全局 sparse/dense 混合调度
- 完整 host runtime / compiler stack
- 一次覆盖所有 DFT kernel
- 一次覆盖所有 projector family

v0 的任务只是：

- 把原语定义得足够精确
- 让它可以被建模、比较、验证

## 16. v0 需要回答的研究问题

下一步最具体的问题应该是：

1. `QE` 里哪些路径最干净地符合 `P M P^H X`？
2. `vkb`、`xi`、`Q` 在真实 trace 上的复用率到底有多高？
3. 同时支持 `P` 与 `P^H` 的最佳 resident layout 是什么？
4. 本地 reduced accumulation 相比完整 `Y` 写回到底更值多少？
5. 一旦把真实 buffer / control 开销加进去，这个原语还划算吗？

## 17. 一句话定义

这条原语当前最简洁的一句话定义是：

```text
一个伴随感知型的常驻投影原语：对流式输入块 X 执行
Y = P M P^H X，并可选地输出 reduced result
G = X^H P M P^H X，同时在原语内部保留投影系数。
```

这句话就是我们当前应该采用的工作定义。
