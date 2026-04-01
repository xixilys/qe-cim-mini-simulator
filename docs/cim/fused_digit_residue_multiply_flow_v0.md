# Fused Digit-Residue Multiply Flow v0

## 1. 文档目的

这份文档只细化**第一个创新点**的乘法计算流程。

这里不再重复“这个创新点值不值得做”或“它是不是最终论文主线”，而是只回答下面几个更落地的问题：

1. 在这个创新点里，一次乘法到底按什么数值 contract 进入硬件
2. 单个 real / complex 乘法在 residue 宏里是怎么一步步完成的
3. project kernel 中，`digit stage`、`row loop`、`modulus group promotion` 的先后关系是什么
4. 现有原型里的 [`Complex_Row_Bank`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:61)、[`Row_Residue_Buffer`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:74)、[`Mod_Encode_Unit`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:92)、[`Residue_3M_MAC`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:97) 在这个流程里分别扮演什么角色

## 2. 先固定这条创新点的正确边界

这个创新点的正确 claim 不是：

- “两个 `FP64` 相乘时，可以神奇地少很多模数”
- “整个过程中永远只保留一个固定 `54bit + 8bit` 窗口”

这个创新点真正做的是：

- 把 `streaming operand` 的 `radix -> residue` 转换吞进主计算
- 让 active modulus planes 随 digit stage 渐进打开
- 用 deterministic stage schedule 决定何时 promotion

因此，它是一条**乘法/乘加流程创新**，而不是“动态范围奇迹”。

## 3. v0 数值 contract

## 3.1 输入形式

先只看一个 complex project kernel 的基本项：

```text
z_k = sum_r conj(B_{r,k}) * x_r
```

或者它的非共轭版本：

```text
y_r = sum_k B_{r,k} * c_k
```

其中：

- `B` 是 resident projector / basis
- `x` 或 `c` 是 streaming operand

## 3.2 缩放 contract

为了把这个流程变成可实现硬件，先固定一个最保守的 v0 contract：

1. resident 侧和 streaming 侧都先做 power-of-two scaling
2. scaling 之后的 real / imag mantissa 都转成有符号整数
3. 整数化后满足：

```text
|q| < 2^p,  p = 53
```

也就是：

```text
B = 2^{-s_B} * q_B
x = 2^{-s_x} * q_x
```

其中：

- `s_B`
  - resident row / resident block 的移位量
- `s_x`
  - streaming block 的移位量
- `q_B`, `q_x`
  - 进入 residue 主通路之前的有符号整数

这和当前原型里的 `power-of-two scaling + truncation` 是一致的，现有 [`Mod_Encode_Unit::encode()`](/Volumes/remote/phd/year_2/project/dft加速/model/src/iterative_subspace_engine.cpp:454) 已经在做这类行为级整数化。

## 3.3 resident 与 streaming 的职责分离

这条创新点最关键的不是“两个输入都 digit 化”，而是：

- resident operand 保持在 residue 域长期常驻
- streaming operand 只保留在 radix/digit 域，按 stage 逐步注入

也就是：

```text
resident:  q_B -> pre-encoded residues
streaming: q_x -> digit stream d_0, d_1, ..., d_{T-1}
```

## 4. digit 化定义

令 digit 宽度为 `w`，总 stage 数为：

```text
T = ceil(p / w)
```

对 `p = 53`、`w = 8`，有：

```text
T = 7
```

把 streaming operand 的有符号整数写成 MSB-first digit：

```text
q_x = sum_{t=0}^{T-1} d_t * 2^{w(T-1-t)}
```

其中：

- `d_0`
  - 最高位 digit
- `d_{T-1}`
  - 最低位 digit

这个 MSB-first 表示很重要，因为整个 fused recurrence 走的是 Horner 型展开。

## 5. 单个 real 乘法的 residue 流程

先只看一个最小单元：`a * b`。

假设：

- `a`
  - resident，已经存在模 `m_i` 下的 residue：`a_i = a mod m_i`
- `b`
  - streaming，被 digit-slice 成 `d_0 ... d_{T-1}`

定义：

```text
c_i = 2^w mod m_i
```

对每个 active modulus plane `m_i`，维护一个 stage accumulator：

```text
U_i^{(0)} = 0
U_i^{(t+1)} = (c_i * U_i^{(t)} + a_i * d_t) mod m_i
```

处理完全部 `T` 个 stage 后：

```text
U_i^{(T)} = a * b mod m_i
```

这就是第一个创新点里最基础的 real multiply recurrence。

## 5.1 它和“先编码再乘”有什么区别

传统流程是：

```text
b -> residue encode on all moduli
then
a_i * b_i on every modulus plane
```

这里则是：

```text
b -> digit stream
then
U_i <- c_i * U_i + a_i * d_t
```

区别不在最后数学结果，而在过程：

- `b` 不需要一开始就在所有模平面上完整展开
- 前几个 stage 只需要打开较少的模平面
- radix-to-residue conversion 被吞进乘法主循环

## 6. 单个 complex 乘法的 3M 流程

对 complex 乘法：

```text
(a_r + j a_i) * (b_r + j b_i)
```

采用 Karatsuba `3M`：

```text
p0 = a_r * b_r
p1 = a_i * b_i
p2 = (a_r + a_i) * (b_r + b_i)

Re = p0 - p1
Im = p2 - p0 - p1
```

## 6.1 resident 侧需要什么

resident 侧不建议存三份副本。

更合适的是：

- 常驻 `a_r mod m_i`
- 常驻 `a_i mod m_i`
- `a_sum mod m_i = (a_r + a_i) mod m_i`
  - 在 plane-local pre-adder 里现算

这样可以避免再存一份 `a_r + a_i` 的长期副本。

## 6.2 streaming 侧需要什么

streaming 侧要显式生成三路 digit stream：

- `d_t(b_r)`
- `d_t(b_i)`
- `d_t(b_sum)`，其中 `b_sum = b_r + b_i`

这里有一个必须说明白的实现点：

- `b_sum` 不能偷懒地用 `d_t(b_r) + d_t(b_i)` 替代

原因是 digit 边界之间会有 carry/borrow，尤其在 MSB-first 流程里，这会直接影响 `p2` 的正确性。

因此 v0 版本应当规定：

- `b_sum`
  - 在 ingress 里先以有符号整数求和
- 然后对 `b_sum` 本身再做 digit-slice

## 6.3 per-plane 3M recurrence

对每个 active modulus plane `m_i`，并行维护三条 recurrence：

```text
U0_i^{(0)} = 0
U1_i^{(0)} = 0
U2_i^{(0)} = 0

U0_i^{(t+1)} = (c_i * U0_i^{(t)} + a_{r,i}   * d_t(b_r))   mod m_i
U1_i^{(t+1)} = (c_i * U1_i^{(t)} + a_{i,i}   * d_t(b_i))   mod m_i
U2_i^{(t+1)} = (c_i * U2_i^{(t)} + a_{sum,i} * d_t(b_sum)) mod m_i
```

stage 结束后先不做 full CRT，而是在模域内重组：

```text
Re_i = (U0_i - U1_i) mod m_i
Im_i = (U2_i - U0_i - U1_i) mod m_i
```

这样每个 modulus plane 最终都会得到：

- `Re_i`
- `Im_i`

这一步正好对应当前原型 [`Residue_3M_MAC::accumulate_row_block()`](/Volumes/remote/phd/year_2/project/dft加速/model/src/iterative_subspace_engine.cpp:460) 里对 `p0 / p1 / p2` 的模域重组。

## 7. 从单乘扩展到 project kernel

单个乘法只是最小单元。真正重要的是：

```text
z_k = sum_{r=1}^{K} conj(B_{r,k}) * x_r
```

对某个输出系数 `z_k`、模 `m_i`、stage `t`，定义 accumulator：

```text
P_{k,i}^{(0)} = 0
P_{k,i}^{(t+1)} = (c_i * P_{k,i}^{(t)} + sum_{r=1}^{K} conj(B_{r,k,i}) * d_t(x_r)) mod m_i
```

这表示：

- 每进入一个新 digit stage，旧 partial sum 先乘 `2^w`
- 再把本 stage 所有 row 的 digit 贡献加进去

这条式子比“逐 row 做完整乘法”更接近真实硬件调度。

## 7.1 stage 内的正确顺序

在实现上，stage `t` 内的顺序建议固定成：

1. `StageScale`
   - 所有 active plane accumulator 先乘 `c_i = 2^w mod m_i`
2. `RowSweep`
   - 逐 row 读 resident residue
   - 取当前 row 的 digit
   - 做 plane-local multiply-add
3. `StageClose`
   - 完成这个 stage 的所有 row 累加
4. `PromotionCheck`
   - 若达到阈值，则触发扩模

不要把“乘 `c_i`”放到逐 row 内部去做，否则会把本来是 stage 级的 Horner recurrence 搞乱。

## 7.2 project 模式下每拍硬件在做什么

对一个 `(stage t, row r)` 时刻：

1. `Digit_Slicer`
   - 输出 `d_t(x_r)`，以及 complex 情况下的 `d_t(x_r_real)`、`d_t(x_r_imag)`、`d_t(x_r_sum)`
2. `Complex_Row_Bank`
   - 读出 resident `B_{r,k}` 的 `real/imag` 行数据
3. `Row_Residue_Buffer`
   - 若该行 residue 已经命中，则直接供给后级
   - 否则先由 encode 边界补齐
4. `Plane-local Residue_3M`
   - 在每个 active modulus plane 上做 `residue × digit + accumulator`
5. `Project_Accumulator`
   - 写回该 `k` 对应的模域 partial sum

stage 末尾再由 `Stage_Scheduler` 决定是否 promotion。

## 8. active modulus groups 与 promotion

## 8.1 为什么要按组分 plane

如果所有模平面从 stage1 就全开，那这个创新点只剩下“把 encode 吞进去”这一个收益，能耗与外围宽度收益就会显著下降。

因此要把模平面分组，比如：

- `G0`
  - base planes，高占空比
- `G1`
  - extension planes，中占空比
- `G2`
  - extension planes，低占空比

这里再补一个现在已经明确下来的**实现硬约束**：

- resident 数据格式最多只存 `8 x 8bit` residue
- 也就是每个常驻数据项只能带 `8` 个模值
- 后续新开的模，只能存在于：
  - stage accumulator scratch
  - promotion island 的临时寄存器
  - extension bank

不能把这些 extension planes 再回写成新的“常驻标准格式”，否则冗余会直接破坏后面的多精度切分。

## 8.2 单次 53-bit 尾数乘法的范围需求

这一版先只讨论**单次 real multiply**：

```text
u = a * b
```

不把 `project` 里的行累加 `sum_r` 也一起算进去。

对 `|a| < 2^53`、`|b| < 2^53`、`w = 8`、`T = 7`，
在第 `t` 个 stage 结束后，已经注入的 `b` 前缀最多只有 `min(8(t+1), 53)` bit，因此单乘需要覆盖的动态范围可以直接写成：

```text
R_mul(t) = 53 + min(8(t+1), 53)
```

于是各 stage 的最低需求是：

- `stage1`
  - `61 bit`
- `stage2`
  - `69 bit`
- `stage3`
  - `77 bit`
- `stage4`
  - `85 bit`
- `stage5`
  - `93 bit`
- `stage6`
  - `101 bit`
- `stage7`
  - `106 bit`

这和前面带 `K` 的 `project` 累加公式不是一回事。  
也正因为这里现在只看单乘，所以 `8 -> 11 -> 14` 会重新变成一个可讨论的候选 schedule。

## 8.3 两次扩模时的判定规则

如果固定只做两次 promotion，那么 active modulus group 的动态范围只要满足：

- `R(G0) >= 61`
- `R(G1) >= 85`
- `R(G2) >= 106`

对应的 stage 划分就是：

- `G0`
  - 覆盖 `stage1`
- `G1`
  - 覆盖 `stage2-stage4`
- `G2`
  - 覆盖 `stage5-stage7`

也就是说：

- 第一次 promotion 放在 `stage1` 结束后
- 第二次 promotion 放在 `stage4` 结束后

这正好对应你说的：

- 常驻只留 `8` 个模
- 输入每拍进 `8bit`
- 一共 `7` 个 stage
- 中间做 `2` 次模转换

## 8.4 具体模值建议

如果你希望**尽量复用当前代码和已有叙事**，最自然的一套是继续用现有原型里的大模数前缀：

```text
stored G0 = {251, 241, 239, 233, 229, 227, 223, 211}
promote G1 = {199, 197, 193}
promote G2 = {191, 181, 179}
mr = 173
```

这样有：

- 常驻存储
  - 固定只有 `8` 个 residue
- 第一次扩模后 active set
  - `8 -> 11`
- 第二次扩模后 active set
  - `11 -> 14`

对应累计动态范围约为：

- `8` 个 active 模
  - `62.84 bit`
- `11` 个 active 模
  - `85.69 bit`
- `14` 个 active 模
  - `108.25 bit`

它对单乘的 stage 覆盖关系是：

- `stage1`
  - 用 `G0`
- `stage2-stage4`
  - 用 `G0 + G1`
- `stage5-stage7`
  - 用 `G0 + G1 + G2`

## 8.5 如果想多留一点余量，可以用更激进的 8-bit pairwise-coprime 组合

如果目标是“在不增加常驻存储位宽的前提下，再多抠一点动态范围”，可以考虑一组允许 composite modulus 的 odd pairwise-coprime 集合：

```text
stored G0 = {253, 251, 249, 247, 245, 241, 239, 233}
promote G1 = {229, 227, 223}
promote G2 = {211, 209, 199}
mr = 197
```

对应累计动态范围约为：

- `8` 个 active 模
  - `63.48 bit`
- `11` 个 active 模
  - `86.94 bit`
- `14` 个 active 模
  - `110.01 bit`

这套的优点是：

- 仍然只存 `8 x 8bit`
- 两次 promotion 的调度不变
- 单乘末级能多出大约 `1.8 bit` 余量

代价是：

- 会偏离当前 simulator 的 prime-only 模表
- 文档和后续论文里需要额外解释“为什么允许 composite modulus”

## 8.6 这里为什么又可以接受 `8 -> 11 -> 14`

关键就在于：这里现在只看**单次乘法**，不把 `project` 里的：

- 行方向累加
- `p2` 的额外 headroom
- 后续 block accumulation

一起塞进同一个阈值里。

因此：

- 对单次 `53b x 53b` 乘法
  - `8 -> 11 -> 14` 是可行的
- 对包含 `sum_r` 的 `project` 累加
  - 这套范围就会重新变紧
  - 那时要么再开更多临时 extension planes
  - 要么把累加拆成 block boundary 局部重构 / 局部归一化

所以现在这版更准确的说法应该是：

- `8 x 8bit`
  - 适合作为**统一常驻存储格式**
- `8 -> 11 -> 14`
  - 适合作为**单乘计算态的临时 active schedule**
- 真正的 `project` kernel
  - 还要在此之上再加一层 block-level range 管理

## 9. promotion 在硬件里到底做什么

promotion 不应该等价成“做一次 full CRT 再重新编码”。

更合理的 v0 版本是：

- 当前 active group 之外，再保留 `1` 条 redundant modulus channel
- stage 到阈值时，对 accumulator 做 snapshot
- 送入共享的 `Promotion_Island`
- 通过 base-extension 直接生成新组模数下的 residues
- 写入 extension banks

也就是：

```text
active residues + redundant residue
-> shared base-extension engine
-> new-group residues
```

这条路径只服务于“扩模”，不服务于最终结果重构。

## 9.1 stage 末尾的 promotion 顺序

建议固定为：

1. 当前 stage 全部 row sweep 完成
2. freeze 当前 accumulator snapshot
3. 用 `redundant modulus + base extension` 生成下一组 residues
4. 把新 residues 写入 `G1 / G2 / G3`
5. 下一 stage 启动时，active mask 扩大

这样 stage 边界非常清楚，也更容易做 pipeline overlap。

## 10. 输出边界与本地数域

这里必须补一个在讨论记录里还不够清楚的点。

对第一个创新点，更合理的数域边界应当是：

1. `project` 结束后
   - 输出的是 coefficient residues，不是立刻 full CRT
2. 若中间的小矩阵 `M` 由本地 FP64 微引擎完成
   - 则在 coefficient block 边界做一次局部 reconstruct
3. `back-project` 若还回到 residue 宏
   - 则由系数块重新 digit-slice 注入

也就是说，第一个创新点真正要避免的是：

- 对每一 row、每一 stage 都做 reconstruct

而不是永远不 reconstruct。

## 11. 与现有原型模块的对齐

如果把这条细化流程和当前原型对齐，可以这样理解：

- [`Complex_Row_Bank`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:61)
  - resident row read 边界
- [`Row_Residue_Buffer`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:74)
  - 已编码 resident row 或 output row 的局部缓存
- [`Mod_Encode_Unit`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:92)
  - 当前是“完整一行编码”的行为级模块
  - 对第一创新点来说，后续需要拆成：
    - resident pre-encode
    - streaming digit-slice ingress
- [`Residue_3M_MAC`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h:97)
  - 当前是“完整 residue block -> full 3M -> CRT reconstruct”的行为级模块
  - 对第一创新点来说，后续需要拆成：
    - plane-local stage recurrence
    - stage-scale
    - promotion hook
    - final recombine / optional reconstruct

## 12. v0 版本现在就可以冻结的流程决策

如果现在就要把第一个创新点先冻结成一版可继续建模的流程，我建议直接定下面这些：

1. `scaling`
   - 继续沿用 power-of-two scaling + truncation
2. `digit order`
   - 用 MSB-first
3. `digit width`
   - `w = 8` 起步
4. `complex multiply`
   - 固定走 Karatsuba `3M`
5. `p2` 输入
   - `b_sum` 在 ingress 里单独生成后再 digit-slice
6. `stage order`
   - 先 `StageScale`，再 `RowSweep`
7. `promotion`
   - 不做动态猜测
   - 只做 deterministic stage-scheduled promotion
8. `promotion engine`
   - 不做 full CRT
   - 采用 redundant-modulus base extension
9. `output boundary`
   - project 后优先保留 coefficient residues
   - reconstruct 只放在 block 边界

## 13. 下一步最值得继续补的东西

在这份流程细化之后，下一步最值得补的是三张表：

1. `single real multiply` 的 stage-by-stage 时序表
   - 每一 stage 哪些寄存器在更新
2. `complex 3M project kernel` 的 lane 表
   - `p0 / p1 / p2` 各自读什么、加什么、何时重组
3. `promotion schedule` 表
   - 针对 `K = 8 / 16 / 32 / 64`
   - 给出 `G0/G1/G2/(G3)` 的阈值

这三张表一补齐，第一个创新点就不只是“有公式”，而是真正具备继续做宏级行为建模、RTL 切分和时序算账的条件了。
