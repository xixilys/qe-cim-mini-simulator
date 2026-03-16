# 双算子投影型 CIM 宏：论文定位与赛道判断（2026-03-14）

## 1. 这份 memo 要回答什么

这份 memo 不再重复“近几年顶会里有多少篇 CIM 论文”这种背景信息。  
它只回答更直接的四个问题：

1. `面向非正交电子结构的双算子投影型 CIM 宏` 能不能作为一篇芯片论文的主创新点
2. 如果能，它应该被包装成什么类型的创新，而不只是一个 `QE/PySCF` 专用加速器
3. 它更适合先打 `VLSI / ISSCC / JSSC` 里的哪条赛道
4. 如果要让这个点有“可比较意义”，论文里最低限度要给哪些 baseline、图表和硬件机制

本 memo 建立在：

- [`docs/conference_track_fit_20260314.md`](conference_track_fit_20260314.md)
- [`docs/benchmarks/qe_subspace_profile_20260312.md`](benchmarks/qe_subspace_profile_20260312.md)
- [`docs/benchmarks/qe_subspace_dataset_status_20260312.md`](benchmarks/qe_subspace_dataset_status_20260312.md)

之上。

## 2. 一句话结论

这个点**可以**成长为一篇顶级芯片论文的主创新点，但前提不是“我们拿 CIM 跑了 `QE Davidson`”，而是：

- 我们把 `CIM` 的基本原语从单算子 `Y = AX`
- 提升成面向 generalized-eigen / non-orthogonal 工作负载的
- `dual-operator projection primitive`

也就是在**算子常驻**条件下，对输入 block `X`，原生支持：

- `HX`
- `SX`
- `X^H H X`
- `X^H S X`

如果最后实现退化成：

- 存两份矩阵
- 做两次普通 `MVM`
- 投影矩阵在外部再算

那它不够成为“大创新点”，最多只是一个领域化加速器。

## 3. 为什么这个点有机会成为“大点”

## 3.1 真正有价值的不是“服务 QE”，而是抬高了 CIM 原语

主流 `CIM` 论文的标准原语通常还是：

- `Y = AX`
- 或其卷积 / GEMM 变体

而我们面对的真实工作负载并不是“只要一次矩阵乘”。

从当前 `QE` 画像可以看出，主路径更接近于：

- 常驻 `H_sub` 与 `S_sub`
- 重复流入 block `X`
- 反复形成：
  - `H_sub X`
  - `S_sub X`
  - `X^H H_sub X`
  - `X^H S_sub X`

如果硬件能把这一整组操作提升为**一个 primitive**，那创新层级就从：

- “把科学计算映射到现成 CIM”

变成：

- “为 generalized-eigen / bilinear projection 类负载定义新的 CIM 计算原语”

这个层级差异很大。前者是应用映射，后者才是芯片论文能打的主创新。

## 3.2 这个点不是红海，但也不是“没人做所以新”

从近几年 `ISSCC` / `VLSI` 的官方 program 看，`CIM` 已经是稳定赛道，但主要拥挤在：

- `AI / ML / Transformer / LLM`
- 精度扩展
- 可重构模式
- 新存储器件
- 编译器和系统协同

因此我们这条线的正确价值，不是：

- “别人没做过电子结构，所以我们新”

而应该是：

- “别人多数停留在单算子原语，而我们提出了一个对 generalized-eigen 更原生的 CIM primitive”

电子结构只是最真实、最有强度的落地应用，不应该是唯一的创新支点。

## 4. 哪种版本算真正够格，哪种版本不够格

## 4.1 够格做主创新点的版本

下面这个版本，才有可能被评审认成一个大的芯片创新：

### 主 claim

`A dual-operator projection CIM macro for generalized-eigen workloads`

### 必须满足的硬件含义

1. `H` 与 `S` 成对常驻
   - 不是软件层面“先算 `HX` 再算 `SX`”
   - 而是硬件里把 `(H, S)` 当成一对相关算子管理

2. 单次输入编码尽量复用到双算子
   - block `X` 注入一次，尽量同时服务 `HX` 与 `SX`
   - 核心收益应该落在编码、激活、读出和外围流量上

3. 支持 projection-native 数据流
   - 不是只吐出 `HX / SX`
   - 而是能低代价形成 `X^H H X / X^H S X`
   - 至少要减少一次显式回写再读回的大搬运

4. 收益来自电路 / 阵列 / 感测 / 累加路径本身
   - 而不是只来自一个更聪明的调度脚本

### 论文里应该呈现出的价值

- 更少的 input encoding 次数
- 更少的 row/column activation 次数
- 更少的 sense / ADC / reconstruction 次数
- 更少的 output traffic
- 更低的 dual-operator generalized-eigen step energy
- 对真实 `QE / PySCF` block 负载更高的端到端有效吞吐

## 4.2 不够格做主创新点的版本

下面这些版本大概率不够：

1. 两个普通 `CIM MVM` 宏并排放
   - `HX` 和 `SX` 还是两次独立调用

2. 只强调“我们支持复数浮点矩阵乘”
   - 这更像底层算术支持，不是新 primitive

3. 微型 eigensolver 本身作为主创新
   - 这更像 `NML` 辅助模块，不像整个芯片的主角

4. 全部创新写成 `QE` 算法映射
   - 会显得像 workload-specific accelerator

## 5. 赛道判断：先投哪里最合理

## 5.1 第一优先：VLSI

当前最适合的主赛道仍然是：

- `VLSI Symposium`

原因不是它“水”，而是它更匹配我们这个点的结构：

1. 更接受 `new compute`
2. 更接受 `memory/compute co-design`
3. 更接受 workload-driven benchmark 方法学
4. 不要求故事必须长得像纯 `AI CIM`

这和我们的最佳包装非常一致：

- 一个新的 `CIM primitive`
- 用 `QE / PySCF` 证明它不是玩具
- 再用更通用的 dual-operator/projection 基准证明它有比较意义

如果首发目标是 `VLSI`，论文叙事会比较顺：

- `new primitive`
- `macro mechanism`
- `paired-operator dataflow`
- `projection-aware benchmark`
- `scientific workload case study`

## 5.2 第二优先：ISSCC

`ISSCC` 不是不能做，但要求会更硬。

它要求这个故事像一个真正的主流 `CIM macro`：

1. 有非常清楚的阵列级或感测级新机制
2. 有完整芯片测量
3. 有标准化的能效 / 密度 / 吞吐指标
4. 有足够强的头对头 baseline

所以如果要冲 `ISSCC`，题目不能长成：

- `A QE subspace accelerator`

而要更接近：

- `A dual-operator projection CIM macro enabling fused bilinear kernels`

然后把 `QE / PySCF` 作为一组强应用 benchmark，而不是唯一 benchmark。

## 5.3 第三优先：JSSC

`JSSC` 更适合作为后续扩展稿，而不是第一落点。

原因很直接：

- 它对低层实现细节、VLSI 细节和测量完备度要求更高
- 只靠一个有趣的 primitive 概念和行为级验证不够

所以合理顺序应该是：

1. 先把 primitive 和 measured macro 讲清楚
2. 先用 `VLSI` 或强 `ISSCC` 版本打首发
3. 再把完整芯片细节、实现 tradeoff、版图和更系统化测量扩成 `JSSC`

## 6. 这篇论文到底应该 claim 什么

最稳的做法不是四处撒创新点，而是把主创新点收敛成一个中心 claim，再配两个 backup formulation。

## 6.1 主创新点

`双算子投影型 CIM 原语`

论文主句式建议收敛到：

- `We elevate CIM from single-operator MVM to fused dual-operator projection for generalized-eigen workloads.`

它的关键词应该是：

- `dual-operator`
- `projection`
- `metric-aware`
- `fused`
- `generalized-eigen`

而不是：

- `Davidson`
- `QE`
- `eigensolver accelerator`

因为前一组词更像硬件 primitive，后一组更像应用映射。

## 6.2 Backup formulation A

`面向非正交工作负载的 metric-aware CIM macro`

这个版本适合在需要强调 `S != I` 的地方使用。  
它比“电子结构专用”更宽，但依然能保留 generalized 问题的本质。

## 6.3 Backup formulation B

`支持 paired-operator bilinear kernels 的 CIM 宏`

这个版本适合在需要弱化领域标签、强调计算形态时使用。  
它更有利于和已有 `single-operator CIM` 做横向比较。

## 7. 一定要补上的 baseline，不然会很悬

如果不想落入“没人做，所以也没人能比较”的陷阱，baseline 必须提前设计好。

最低限度建议有四档：

1. `Baseline-1: single-operator CIM, dual pass`
   - `H` 和 `S` 分别跑两次普通 `MVM`

2. `Baseline-2: dual-resident, non-fused`
   - `H` 与 `S` 同时常驻，但依然分开读出 / 分开外围

3. `Baseline-3: fused HX/SX only`
   - 只证明双算子 `MVM` 融合
   - 但 `X^H H X / X^H S X` 仍在外部形成

4. `Ours: fused dual-operator projection`
   - `HX`
   - `SX`
   - `X^H H X`
   - `X^H S X`
   - 在一个统一数据流中尽量共享输入、激活、读出和累加

只有这样，评审才能明确看见：

- 收益到底来自“双算子常驻”
- 还是来自“融合读出”
- 还是来自“projection-native 数据流”

## 8. 论文里必须出现的图表

如果我们要把这个点立成“大创新”，图表不能只放算法框图。

至少应该有：

1. `Primitive definition figure`
   - 明确对比：
     - 传统 `Y = AX`
     - 我们的 `{HX, SX, X^H H X, X^H S X}`

2. `Array/dataflow figure`
   - 画清楚 `H/S` paired residency
   - 输入 block `X` 的共享注入
   - 投影矩阵形成路径

3. `Cost decomposition`
   - input encoding
   - activation
   - sensing / ADC
   - accumulation / reconstruction
   - output traffic

4. `Comparator bar chart`
   - 对四档 baseline 比较 energy / latency / data movement

5. `Real workload mapping`
   - `QE` 与 `PySCF` 中 `HX/SX/Q^H H Q/Q^H S Q` 的出现位置和尺寸分布

6. `Accuracy / convergence impact`
   - 证明这个 primitive 的数值近似不会把整体解算流程打坏

## 9. 对真实负载的要求：哪些证据最关键

当前 `QE` 数据集已经足够支撑一个很强的前提：

- generalized Hermitian 是主路径
- `S_sub` 不是可忽略项
- `n` 和 `m` 具有稳定的 `m -> 2m` block 扩张特征

这说明：

- 我们不是为了“多做一次矩阵乘”做硬件
- 而是在为 `(H, S)` 成对算子的 block 投影流程做硬件

但若要投稿更稳，建议继续补两类证据：

1. `paired-op trace evidence`
   - 在 `QE / PySCF` 中统计：
     - `HX`
     - `SX`
     - `Q^H H Q`
     - `Q^H S Q`
   - 的相邻出现频率和尺寸相关性

2. `projection reuse evidence`
   - 证明 fused primitive 的收益不只是理论 FLOPs 减少
   - 而是确实减少了重复编码和输出搬运

## 10. 当前最需要警惕的风险

## 10.1 风险一：写成“电子结构专用芯片”

如果标题、摘要和主图都在强调：

- `QE`
- `Davidson`
- `subspace diagonalization`

评审很容易把它看成：

- 一个很窄的 scientific ASIC

更安全的写法是：

- 主标题强调 primitive
- 副标题或实验章节再放 `QE / PySCF`

## 10.2 风险二：创新落不到电路

如果收益最后主要来自：

- 软件流水化
- 更好的缓存调度
- NML 里做的小投影求解

那论文会更像 architecture / accelerator mapping，而不够像 circuit/macro 创新。

真正需要落到硬件的地方，至少要包含：

- paired-operator 阵列组织
- 共享输入编码或共享激活机制
- 投影矩阵形成的低搬运实现
- 明确的外围成本下降

## 10.3 风险三：只有应用，没有比较框架

如果 benchmark 只放：

- 一个 `QE` case
- 一个 `PySCF` case

评审会很难判断：

- 你的提升到底来自 primitive 创新
- 还是因为选了一个别人没测过的 workload

所以一定要保留“对同一 dual-operator kernel 的不同硬件实现方式”的 baseline 比较。

## 11. 最终判断

所以，当前最稳的结论不是：

- “这个点已经天然是一篇大 paper”

而是：

- “这个点有潜力成为大 paper 的主创新，但必须被收敛成一个新的 CIM primitive，并且把比较框架和电路收益做实”

更具体地说：

1. 如果我们把它做成
   - `dual-operator fused projection CIM primitive`
   - 并给出明确阵列 / 外围机制
   - 再配上 `QE / PySCF` 真实负载
   - 那它有资格去争 `VLSI` 主线，甚至作为 `ISSCC` 的备选方向

2. 如果我们只是做成
   - `QE Davidson accelerator`
   - 或 `complex GEMM + tiny eigensolver`
   - 那创新等级不够高，很难作为顶会主创新点站稳

## 12. 当前建议

后续工作不要再平均用力，而是优先围绕下面三件事推进：

1. 冻结**唯一主创新点**
   - 就是 `dual-operator projection CIM primitive`

2. 反推**必须存在的硬件机制**
   - 证明它不是两个普通 `MVM` 拼起来

3. 建立**可比较的 benchmark/baseline 套件**
   - 避免落入“很新，但没人知道该怎么比”的陷阱

做到这一步，这条线就不再只是“一个有意思的研究方向”，而开始具备真正论文化、会场化和竞争化的形状。
