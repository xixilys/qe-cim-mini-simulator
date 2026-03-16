# 顶会赛道与创新点匹配评估（2026-03-14）

## 1. 目的

这份文档不讨论“这个想法听起来新不新”，而是只回答两个更实际的问题：

1. `面向非正交电子结构的双算子投影型 CIM 宏` 能不能作为一篇芯片论文的大创新点
2. 如果能，应该优先往哪个主流赛道包装，避免落到“没人做也没人关心”的尴尬位置

这里主要参考：

- `ISSCC 2023 / 2024 / 2025` 官方 advance program
- `VLSI 2025` 官方 advance program 与 `VLSI 2026` 官方 CFP
- `JSSC` 官方 aims/scope 与 `2025` 官方数字/ML 类投稿标准说明
- `QE` 官方输入说明
- `PySCF` 官方 API 文档与本机源码接口

## 2. 先说结论

### 2.1 当前这个点“有潜力成为大创新点”，但前提非常明确

`双算子投影型 CIM 宏` 只有在下面这个版本下，才像一个足够大的电路创新点：

- 不是单纯“把 `H` 和 `S` 两个矩阵都存进来”
- 而是提出一个新的 `CIM primitive`
- 这个 primitive 原生支持：
  - `HX`
  - `SX`
  - `X^H H X`
  - `X^H S X`
- 并且这个 primitive 通过新的电路/数据流组织，显著减少：
  - 输入编码次数
  - 阵列读出次数
  - 输出重构次数
  - 外围 buffer / ADC / CRT 代价

如果只是：

- “我们用 CIM 算 `HX` 和 `SX`”
- “然后外面软件再算投影”

那它还不够大，最多是一个领域化应用。

### 2.2 这个方向不是完全没人做，但直接对口竞争不多

当前主流 `ISSCC / VLSI` 的 `CIM` 论文，明显主战场还是：

- `AI / CNN / Transformer / LLM`
- 模式切换
- 精度扩展
- 新存储器件
- compiler / system co-optimization

我没有看到很多直接对口的：

- `non-orthogonal electronic structure`
- `generalized Davidson`
- `dual-operator projection primitive`

所以它不是“拥挤红海”，但也不能只靠“没人做过”来成立。

真正能成立的原因应该是：

- 它把 `CIM` 从单算子 MVM 推进成了一个更通用的 `bilinear / generalized-eigen` primitive
- 而电子结构只是最强、最真实的应用入口

### 2.3 最适合的主赛道：`VLSI > ISSCC > JSSC`

按当前状态排序：

1. `VLSI Symposium`
   - 最适合作为首发主赛道
   - 对 `new compute`、`CIM`、`technology/circuit/system co-design` 的包容度更高
   - 比 `ISSCC` 更容易接受“不是 AI、但有强 primitive 创新”的故事

2. `ISSCC`
   - 可以冲，但门槛更高
   - 必须非常像一个“主流 CIM 宏”而不是“科学计算专用单点加速器”
   - 需要更强的 measured silicon、标准化指标、和更清晰的头对头比较

3. `JSSC`
   - 不是首发会场，而是后续扩展稿
   - 需要更完整的低层电路、版图、时钟、电源、测试、封装与测量细节

## 3. 各会场最近几年的偏好

## 3.1 ISSCC：更偏“硬核电路宏 + 主流赛道 + 强测量”

从官方 advance program 看，`ISSCC` 近三年里 `CIM` 不是偶发主题，而是稳定主线：

- `ISSCC 2023`
  - `Session 7: SRAM Compute-In-Memory`
  - `Session 16: Efficient Compute-In-Memory Based Processors for ML`
- `ISSCC 2024`
  - `Session 34: Compute-In-Memory`
  - `Session 20: Machine Learning Accelerators`
  - Short course 里还专门讲了 `ML hardware` 和 `CIM architectures`
- `ISSCC 2025`
  - `Session 14: Compute-In-Memory`
  - Forum 明确把 `data-centric architecture design`, `in-memory computing`, `memory wall` 放在一起讨论

这些 session 里能看到的强信号很一致：

- 主题高度集中在 `AI/ML`
- 论文标题里频繁出现：
  - `TOPS/W`
  - `TOPS/mm2`
  - `FP16 / floating-point / multi-mode`
  - `Transformer / LLM / training / inference`
  - `compiler`
  - `digital / analog / hybrid domain`

这说明 `ISSCC` 喜欢的不是抽象算法，而是：

- 一个**非常硬的 macro**
- 有非常清楚的电路创新
- 有完整测量
- 有当前主流应用牵引

对我们这个方向的启示是：

- 如果只说“电子结构很重要”，不够
- 必须把它讲成一个**新的计算原语**
- 而且要像主流 `CIM` 论文一样，给出：
  - 面积/能效/吞吐
  - 精度与稳定性
  - 数据流和外围成本
  - 与已有 `single-operator CIM` 的直接比较

## 3.2 VLSI：更欢迎“new compute + benchmark methodology + cross-layer story”

`VLSI 2025` 的信号比 `ISSCC` 更适合我们当前这个点。

从官方 advance program 可以看到：

- `Circuits Session 1: CIM and Quantum-inspired Computing`
- `Workshop 5: Architectural Benchmarking of Compute-in-Memory Systems`
- `Joint Focus Session 3: AI and ML Hardware`

同时，`VLSI 2026` 官方 CFP 也把下面这些并列写进 scope：

- `Computing/Processing in Memory`
- `Devices and Accelerators for ML/DL and New Compute`
- `Memory technologies, devices, circuits, and architectures`
- `Beyond CMOS devices ... optical and quantum computing`

这说明 `VLSI` 对下面这类故事更友好：

- 新计算范式
- memory/compute co-design
- device-to-system co-optimization
- benchmarking methodology
- 不一定完全贴着主流 AI，但要能放进 `new compute`

这对我们非常关键，因为：

- `双算子投影型 CIM 宏` 本质上更像 `new compute primitive`
- 它和 `quantum-inspired / scientific computing / generalized eigen` 的相邻关系，比和纯 `edge AI` 更自然
- `VLSI` 当前已经公开承认 `benchmarking of CIM systems` 是一个重要主题，这正适合我们做 workload-driven 论证

## 3.3 JSSC：接受创新，但要求必须落到 IC 细节

`JSSC` 官方 scope 很明确：

- 重点是 `transistor-level design of integrated circuits`
- `Experimental verification is strongly encouraged`

更关键的是，`2025` 官方文件《Criteria for Good JSSC Submissions on Digital Circuits and Systems》说得非常直白：

- 仅有高层算法和体系结构不够
- 必须有 substantial content on:
  - low-level microarchitecture or gate-level design
  - VLSI implementation details
  - voltage/clock generation and distribution
  - silicon measurements that are difficult to infer pre-silicon

所以 `JSSC` 对我们这个点的态度会是：

- 创新点可以很新
- 但必须已经是**成熟芯片论文**
- 不能只是一个应用故事或系统原型

## 4. QE / PySCF 负载对这个创新点的支撑

## 4.1 QE 给出的最强证据

当前仓库里的 `QE` trace 已经说明：

- `generalized Hermitian` 不是边角情况
- 子空间维度稳定落在 `m -> 2m` 的 block 扩张
- `H_sub` 和 `S_sub` 都是真实主路径

具体地：

- `Si` 样本里 generalized-like 占比达到 `77.8%` 和 `85.2%`
- `Fe / Au slab / SiC32` 这些样本进一步证明：
  - `S_sub` 经常明显偏离单位阵
  - `n` 可扩到 `128`

这说明我们不是在为“一个矩阵乘”做硬件，而是在为：

- `H_sub X`
- `S_sub X`
- `Q^H H Q`
- `Q^H S Q`

这一整套非正交子空间 primitive 做硬件。

## 4.2 PySCF 给出的最强证据

`PySCF` 也不是和这个故事无关。

官方接口中：

- `lib.davidson(aop, ...)` 是标准 `aop(x)` 型接口
- `lib.dgeev(abop, ...)` 明确是 generalized Davidson 形式，`abop(x)` 返回 `(Ax, Bx)`
- `lib.safe_eigh(h, s)` 直接对应 generalized eigenvalue problem

这说明从软件抽象上，`PySCF` 和 `QE` 一样都支持下面这种负载模型：

- 固定算子常驻
- block/vector 重复流过
- 目标是 generalized / metric-aware eigensolve

所以这个创新点不是 `QE-only hack`，而是：

- `non-orthogonal electronic-structure primitive`

## 5. 这个方向目前最大的风险

## 5.1 风险一：太像“领域专用加速器”，不够像“新的 CIM primitive”

如果论文标题和内容主要强调：

- `for QE`
- `for PySCF`
- `for electronic structure`

评审可能会觉得：

- 应用很专
- 比较对象太少
- 缺少通用意义

所以主创新点不能写成：

- “A CIM accelerator for QE Davidson”

更好的写法是：

- `A metric-aware dual-operator projection CIM primitive for generalized-eigen and non-orthogonal scientific workloads`

然后再把 `QE / PySCF` 作为最强落地应用。

## 5.2 风险二：只做算法映射，没有新的电路机制

如果最终实现只是：

- 双 bank 存 `H` 和 `S`
- 重复做两次普通 MVM

那还不够。

要像顶会创新点，至少要有 1 到 2 个**真正的 circuit/dataflow 机制**，例如：

- 单次输入编码，同时驱动 `H` 和 `S`
- 输出端直接累计投影，不必总是完整重构 `HX/SX`
- 对 `X^H H X / X^H S X` 做融合式边界读出
- 对 dual-operator workload 做共享 `ADC / CRT / residue` 通路
- 针对 generalized path 的动态精度/模数/读出 gating

## 5.3 风险三：缺少主流 comparator

当前 `ISSCC / VLSI` 的 `CIM` 比较对象多数是：

- AI 宏
- LLM / transformer
- memory-centric accelerator

如果我们只有：

- `QE residual`
- `PySCF timing`

而没有和主流 `CIM primitive` 的横向比较，评审会很难量化这个点的价值。

因此必须补的比较对象包括：

1. `single-operator CIM` baseline
2. `dual-pass HX + SX` baseline
3. `fused dual-operator projection` ours

比较维度至少包括：

- 输入编码次数
- 阵列访问次数
- 输出重构次数
- SRAM/buffer 容量
- ADC/CRT 能耗估计
- system-level latency

## 6. 这个点到底适合哪个赛道

## 6.1 最推荐赛道：VLSI Circuits

最推荐的投稿叙事是：

- `new compute`
- `CIM`
- `memory-compute co-optimized primitive`
- `generalized eigen / scientific computing workload`

它最适合投 `VLSI Circuits` 的原因是：

- 会场对 `new compute` 更开放
- 已经公开强调 `CIM benchmarking`
- 不需要像 `ISSCC` 那样几乎默认你得贴最主流 AI 红海

推荐包装方式：

- 主标题突出 `dual-operator projection CIM macro`
- 副标题再落到 `non-orthogonal electronic structure`

## 6.2 可以冲的赛道：ISSCC Compute-In-Memory

如果后续有下面这些东西，可以冲 `ISSCC`：

- 硬核 silicon macro
- 很强的 measured energy/area/throughput
- 明确优于 `single-operator CIM + outer projection`
- 精度/稳定性论证完备

但在 `ISSCC` 里，单靠电子结构应用本身不太够。

要提升成功率，必须把它讲成：

- 一种对 generalized bilinear-form workload 更高效的 `CIM macro`
- 电子结构只是第一应用

## 6.3 后续扩展赛道：JSSC

一旦有了会议版和更完整 silicon 细节，`JSSC` 很合适做扩展稿。

但前提是稿子里要补足：

- floorplan
- timing / clocking
- power domain
- memory macro placement
- measurement setup
- external interfaces

## 7. 对当前项目的建议

## 7.1 不要把主创新点写成“DFT 专用”

不推荐：

- `A CIM accelerator for QE/PySCF`

推荐：

- `A dual-operator projection CIM primitive for generalized-eigen workloads`

再在摘要和实验中强调：

- `QE`
- `PySCF`
- non-orthogonal electronic structure

## 7.2 不要把主创新点写成“一个算法”

不推荐：

- `A hardware Davidson solver`
- `A hardware generalized eigensolver`

推荐：

- `A new CIM primitive + fused dataflow`

然后把 Davidson / subspace iteration 当成最自然的上层使用场景。

## 7.3 必须补出来的硬比较

如果真想往顶会冲，下面这些比较必须补：

1. `single-operator CIM`
   - 分别做 `HX`、`SX`
   - 投影在外部完成

2. `dual-operator but non-fused`
   - `H/S` 双 bank
   - 但输入编码、输出重构不共享

3. `ours: fused dual-operator projection CIM`
   - 共享输入广播
   - 共享读出 / 重构 / 局部累加
   - 原生支持 `{HX,SX,X^HHX,X^HSX}`

## 7.4 当前最现实的节奏

最现实的推进顺序应该是：

1. 先把这个点抽象成 `generalized bilinear-form CIM primitive`
2. 再补 `QE + PySCF` trace，证明这不是单软件特例
3. 再做 circuit-level datapath 与 buffer/ADC/CRT 拆账
4. 最后再决定优先冲 `VLSI` 还是 `ISSCC`

## 8. 最终判断

最终判断是：

- `双算子投影型 CIM 宏` 有机会成为一个**足够大的创新点**
- 但前提是它必须表现为一个**新的 CIM 原语**
- 不能只是“用 CIM 加速 QE”

如果这个 primitive 成立，它不是没有比较意义的冷门芯片，原因是：

- 它直接落在当前最热的 `CIM / new compute / memory wall` 主赛道上
- 只是应用牵引从 `AI` 换成了 `non-orthogonal scientific computing`
- 而这个应用又确实来自真实 `QE / PySCF` 负载

因此，当前最合适的目标不是“证明它完全没人做”，而是：

- 证明它是 `CIM` 主赛道里一个**新的、足够一般、足够硬**的 primitive
- 然后用 `QE / PySCF` 证明它不是空想

## 9. 参考来源

### 官方会议/期刊来源

- ISSCC 2025 Advance Program  
  `https://www.isscc.org/s/ISSCC2025AdvanceProgram.pdf`
- ISSCC 2024 Advance Program  
  `https://www.isscc.org/s/ISSCC2024AdvanceProgram-Final.pdf`
- ISSCC 2023 Advance Program  
  `https://www.isscc.org/s/ISSCC2023AdvanceProgram.pdf`
- ISSCC Trends  
  `https://www.isscc.org/trends`
- VLSI 2025 Advance Program  
  `https://archive.vlsisymposium.org/25web/wp-content/uploads/VLSI2025_Advanceprogram0611.pdf`
- VLSI 2026 CFP Overview  
  `https://www.vlsisymposium.org/overview-cfp/`
- IEEE JSSC Aims and Scope  
  `https://sscs.ieee.org/publications/ieee-journal-of-solid-state-circuits-jssc/`
- Criteria for Good JSSC Submissions on Digital Circuits and Systems  
  `https://sscs.ieee.org/wp-content/uploads/Criteria-for-Good-JSSC-Submissions-on-Digital-Circuits-and-Systems.pdf`

### 软件/工作负载来源

- QE `pw.x` input description  
  `https://www.quantum-espresso.org/Doc/INPUT_PW.html`
- PySCF API docs  
  `https://pyscf.org/pyscf_api_docs/pyscf.lib.html`

### 仓库内已有证据

- [qe_subspace_profile_20260312.md](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_profile_20260312.md)
- [qe_subspace_dataset_status_20260312.md](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_dataset_status_20260312.md)
- [complex_fp64_gemm_cost_model_v0.md](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)
