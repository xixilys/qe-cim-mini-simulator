# FP64 混合精度存算宏讨论简报（2026-03-17）

## 1. 文档目的

这份文件给研讨小组使用，目标不是讲完整论文故事，而是把当前**本地已有数据**和**这轮讨论已经收敛出的判断**压成一份可以直接开会的讨论材料。

本文只回答四个问题：

1. 本地已经拿到了哪些 workload / 原型 / 验证数据
2. 这些数据对硬件方向提出了什么硬约束
3. 现在最值得保留的 `FP64 mixed-precision CIM macro` 结构候选有哪些
4. 研讨小组下一步需要拍板哪些问题

## 2. 一句话结论

当前最稳的主线仍然是：

- **基于 `Ozaki-II / RNS / CRT` 的 modulus-sliced `FP64` 存算宏**

但这条线现在更像“高精度算术映射”，还缺一个更强的**宏级创新点**。  
本轮讨论后，最有希望补上这一点的方向是：

- **把宏做成双模式**
- 主模式做 `residue-MAC`
- 次模式做 `risk-aware select / correct`

也就是说，别再把问题讲成“一个会做 FP64 的通用 GEMM-CIM”，而要讲成：

- **一个满足 `FP64 contract`、内部采用 mixed precision 分解、并具备数值风险驱动选择/修正能力的存算宏**

## 3. 当前本地已有数据与实现

## 3.1 QE 真实子空间矩阵数据集已经形成

相关文件：

- [`qe_subspace_dataset_status_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_dataset_status_20260312.md)
- [`qe_subspace_profile_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_profile_20260312.md)

当前已经有 6 类真实 `QE` 样本：

1. `Si`
2. `Fe`
3. `C6H6`
4. `graphene`
5. `Au slab`
6. `SiC32`

已经确认的关键事实：

- `QE` 的子空间问题不是单一路径
  - 同时覆盖 `cdiaghg` 和 `rdiaghg`
- generalized Hermitian 不是边角情况，而是主路径
- 子空间维度依体系明显变化
  - 小 `Si`: `n = 8 ~ 32`
  - `Fe`: `n = 12 ~ 24`
  - `C6H6`: `n = 30 ~ 60`
  - `Au slab`: `n = 26 ~ 52`
  - `SiC32`: `n = 64 ~ 128`

对硬件的直接含义：

- 不能只按 `Si` 这种小 case 规划阵列和 buffer
- `S_sub` 不能被当成“接近单位阵、可以忽略”的对象
- 对角化侧最需要面对的是**小到中等规模的 dense generalized Hermitian**

## 3.2 `QE` 源码分析已经确认 projector/basis 类负载非常关键

相关文件：

- [`CIM_data_residency_analysis.md`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/CIM_data_residency_analysis.md)
- [`circuit_innovation_candidates_20260316.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/circuit_innovation_candidates_20260316.md)
- [`dual_operator_projection_cim_positioning_20260314.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/dual_operator_projection_cim_positioning_20260314.md)

已经确认的负载模式包括：

1. `QE` 非局域项：
   - `becp = <vkb|psi>`
   - `ps = D * becp`
   - `hpsi += vkb * ps`

2. `QE` ACE / EXX：
   - `<xi|phi>`
   - `xi * coeff`

3. `QE` / `PySCF` generalized Davidson 接口：
   - `HX`
   - `SX`
   - `X^H H X`
   - `X^H S X`

其中最关键的 residency 证据来自 `xi`：

- `xi` 写入次数极低
- 单示例中写读比可到 `1 : 1680`

对硬件的直接含义：

- 常驻对象不是“任意矩阵”，而是 `vkb / xi / Q` 这类 projector/basis
- 这类负载天然不是一次普通 `GEMM`，而是：
  - `project`
  - `small transform`
  - `back-project`

## 3.3 `FP64 complex GEMM` 行为级主线已经闭环

相关文件：

- [`complex_ozaki_fp64_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md)
- [`complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)
- [`complex_fp64_gemm_cost_model_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)
- [`ozaki_crt_algorithm_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/ozaki_crt_algorithm_freeze_v0.md)

已经打通的主链是：

1. scaling / truncation
2. residue 编码
3. 模域 `Karatsuba 3M`
4. `CRT` 重构
5. 反缩放回 `FP64 complex`

行为级验证结果已经证明：

- 在默认与宽指数范围压力测试下，整体相对误差稳定在 `1e-14` 量级

当前主线冻结结论基本是：

- 主算法：`Ozaki-II + CRT + Karatsuba 3M`
- 主配置：`L = 13`
- 压力上界：`L = 17`
- residue 数据流：streaming 优先
- `CRT` 组织：accumulation 优先

对硬件的直接含义：

- 这条线数值上是成立的
- 现在真正需要解决的不是“算法能不能算对”，而是：
  - bank 怎么切
  - `L` 怎么落到面积
  - `CRT` 和 residue buffer 怎么不把代价吃死

## 3.4 迭代微对角化行为级原型已经有拆分后的数据通路

相关文件：

- [`iterative_subspace_flow.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/iterative_subspace_flow.md)
- [`generalized_subspace_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/generalized_subspace_validation.md)
- [`nml_generalized_eigensolver_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/nml_generalized_eigensolver_freeze_v0.md)

当前 `iterative_subspace_engine` 已经拆成：

- `Matrix_Resident_Tile`
  - `Complex_Row_Bank`
  - `Row_Residue_Buffer`
  - `Mod_Encode_Unit`
  - `Residue_3M_MAC`
- `Reduced_Generalized_MicroSolver`
  - `Cholesky`
  - `standardize`
  - `Jacobi`
  - `back-transform`

`2026-03-13` 的快照说明：

- `mode=1` 可作为激进 fast path
- `mode=2` 更像系统默认自动模式
- 对更大的 `n`，当前先暴露出来的瓶颈是外层 fixed-step 轮数，而不是 reduced solver 本身

对硬件的直接含义：

- 近存微求解器应优先走 **direct dense generalized Hermitian solver**
- 不建议在近存里再引入一层新的 Davidson / LOBPCG 作为主线

## 3.5 当前本地代码里 residue 路径已经接进 tile 主通路

相关代码：

- [`iterative_subspace_engine.h`](/Volumes/remote/phd/year_2/project/dft加速/model/include/iterative_subspace_engine.h)
- [`iterative_subspace_engine.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/iterative_subspace_engine.cpp)
- [`tb_iterative_subspace.cpp`](/Volumes/remote/phd/year_2/project/dft加速/model/src/tb_iterative_subspace.cpp)

当前已经具备的行为级模块包括：

- `Mod_Encode_Unit`
- 固定互素模数组 residue 编码
- 每模数显式 `Residue_3M_MAC`
- `CRT` 有符号重构

并且 testbench 已经接了：

- `row_hits`
- `row_misses`
- `residue_encodes`
- `crt_reconstructs`

这意味着：

- residue 域通路已经不是占位逻辑
- 但当前 bank/cache/modulus 组织仍然只是 `v0` 行为模型

## 4. 本轮讨论已经收敛出的技术判断

## 4.1 现在不要继续讲“系统拼装型 primitive”主故事

前面我们尝试过把故事放在：

- `projector-stationary asymmetric bra/ket primitive`

这条线有价值，但当前的问题是：

- 它更像系统/原语叙事
- 还不像一个真正站得住的 `FP64 mixed-precision CIM macro` 本体

因此本轮之后建议：

- **暂时把 projector primitive 作为 workload 解释背景**
- **把主讨论重心收回到 `FP64 mixed-precision 存算宏本体`**

## 4.2 需要面对的硬约束

从 workload 和本地原型看，当前硬约束有 6 条：

1. 必须满足 `FP64 contract`
2. 必须支持复数
3. 必须能承受长累加与 cancellation
4. 不适合依赖大规模高精度 ADC
5. 主路径最好仍然是数字 `CIM`
6. 局部 mixed precision 可以有，但不能把主结果数值 contract 搞脏

## 4.3 直接把 `bit-serial` 当 `FP64` 主路径不合适

这轮讨论已经明确：

- `bit-serial` 不是完全没价值
- 但**不适合作为 `FP64` 主路径本体**

原因是：

1. `53` 位有效尾数导致串行周期太长
2. `FP64` 最难的是对齐、长累加和规格化，而不是单次尾数乘法
3. 复数路径会把 `bit-serial` 的时延和控制复杂度进一步放大
4. 对科学计算来说，单次 kernel latency 太长会伤到整条迭代链

`bit-serial` 最合适的位置是：

- residue / modulus plane 内部的小位宽乘加
- `Hi/Lo` 结构里的 `lo` 修正路径
- 非主路径的 screening / correction 单元

## 4.4 CELLA 给出的最重要启发：宏不该只有一种语义

我们讨论过的 [`CELLA PDF`](/Volumes/remote/Zotero/storage/KV5GC4KD/Wu%20%E7%AD%89%20-%202025%20-%20CELLA%20A%2028nm%20Compute-Memory%20Co-Optimized%20Real-Time%20Digital%20CIM-Based%20Edge%20LLM%20Accelerator%20with%201.78.pdf) 最值得借的点不是：

- `KV hash`
- `CAM` 本身

而是：

- **同一块宏在不同瓶颈下切换不同语义模式**

对应到我们这里，真正有价值的启发是：

- 宏不应只是 `MAC`
- 它还应支持一个服务于数值控制的第二模式

对我们最自然的第二模式不是 `CAM`，而是：

- `risk-aware select / correct`

也就是：

- 判断哪些行/项/tile 只需要主路径
- 哪些需要激活 correction
- 哪些需要扩模、回退、或送 sidecar

## 5. 现在最值得保留的 4 个 `FP64 mixed-precision CIM macro` 候选

## 5.1 方案 A：`RNS / CRT` modulus-sliced 宏

### 核心思想

- `FP64` 经 scaling 后转成有界整数
- 按 `L` 个小模数切成 residue 平面
- 每个平面在数字 `CIM` 中做乘加
- 输出边界 `CRT` 重构回 `FP64`

### 优点

- 与当前本地主线完全一致
- 没有高精度 ADC 依赖
- 复数 `3M` 路径很自然
- 对 cancellation 和长累加最稳

### 问题

- `L` 个平面会推高 bank 数和控制复杂度
- `CRT` / scaling / overflow guard 边界很重

### 当前判断

- **这是当前最稳的主线**

## 5.2 方案 B：`Hi/Lo mantissa correction` 宏

### 核心思想

- 把一个 `FP64` 数拆成 `hi + lo`
- 主路径只算 `hi * hi`
- 修正路径再算：
  - `hi * lo`
  - `lo * hi`
  - 必要时 `lo * lo`
- 在本地 `FP64` 累加器里合并

### 优点

- 比 `RNS/CRT` 更直观
- 更像“真正 mixed precision”
- bank 组织可能更简单

### 问题

- 想把 `QE` 数值误差压下去，修正层数可能迅速变多
- 一旦修正路径变重，复杂度会接近 `RNS`
- 对复数和长累加未必比 `RNS` 更干净

### 当前判断

- **这是最值得和当前本地法并行比较的第二主线**

## 5.3 方案 C：`limb-sliced integer + superaccumulator` 宏

### 核心思想

- 整数化后不拆模数，而是拆成多个 `8/10/12` bit limbs
- 宏里做 limb 乘法
- 结果进超宽 `carry-save / superaccumulator`
- 最后统一归一化

### 优点

- 不需要 `CRT`
- 数学链条更直接

### 问题

- limb 交叉乘的项数很多
- 宽累加器会非常重
- 不太像一个高密度、易 banking 的 `CIM` 宏

### 当前判断

- **值得做理论对照**
- **不看好作为最终主线**

## 5.4 方案 D：`shared-exponent / block-floating` 宏

### 核心思想

- 一行或一块共享 exponent
- mantissa 在阵列里算
- 边界再恢复高精度

### 优点

- 控制更简单
- bank 数少

### 问题

- 对 `QE` 这种动态范围和 cancellation 很强的负载风险太高
- 更适合 screening / 辅助模式，而不是主结果路径

### 当前判断

- **不建议作为主线**
- **只适合作为辅助模式**

## 6. 当前最推荐的小组讨论对象

如果要控制讨论面，我建议研讨组只保留下面 3 个对象：

### 方案 1：纯 `RNS/CRT` 主宏

- 优点：数值最稳，和当前本地实现最一致
- 缺点：主创新点容易被看成“算法映射”

### 方案 2：`RNS-MAC + risk-aware select/correct` 双模式宏

- 优点：最有希望在不丢掉当前主线的前提下，补出一个真正的宏级创新点
- 缺点：第二模式的硬件定义还没冻结

### 方案 3：`Hi/Lo correction + selective correction` 双模式宏

- 优点：mixed precision 叙事更直接
- 缺点：是否真能扛住 `QE` 数值稳定性还没证据

## 7. 这轮讨论后建议淘汰或降级的方向

以下方向目前建议不要作为主叙事继续展开：

1. 通用 `GEMM-CIM + transpose support`
2. 双副本 `P / P^H` 宏
3. 纯模拟 `FP64 CIM`
4. 直接 `bit-serial FP64` 主宏
5. 把 `LLM outlier-aware` 结构直接平移到 `QE`
6. 继续把大部分篇幅放在“projector primitive 系统拼装故事”上

## 8. 研讨小组最需要讨论的 6 个问题

## 8.1 主线到底选哪一条

必须明确：

- 以当前本地 `RNS/CRT` 为主线继续推进
- 还是转向 `Hi/Lo correction`

我的建议是：

- `RNS/CRT` 继续做主线
- `Hi/Lo` 只做对照设计

## 8.2 是否引入第二语义模式

必须明确：

- 宏是否只有 `MAC mode`
- 还是要增加 `risk-aware select / correct mode`

我的建议是：

- **引入第二模式**

因为这是最有希望把“高精度算术映射”提升成“宏级创新”的地方。

## 8.3 第二模式到底筛什么

需要选定筛选对象：

1. 行级尺度/指数桶
2. correction mask
3. 扩模触发
4. fallback 触发

建议优先顺序：

1. correction mask
2. 扩模触发
3. fallback 触发

## 8.4 `RNS` 路径的 bank 怎么切

至少要讨论：

1. 按 `modulus` 切 bank
2. 按 `real/imag` 切 bank
3. 是否再按 `K / row tile` 做二级切分

当前建议：

- 一级按 `modulus plane`
- 二级按 `real/imag`
- 再按 `row tile` 做子阵列

## 8.5 correction 路径是纯数字还是局部 mixed

需要明确：

- correction 单元是否允许比主阵列更低吞吐、更高精度

当前建议：

- 主阵列保持规则、小位宽数字 `CIM`
- correction 放在本地较小的数字/半串行单元里

## 8.6 评估标准先看什么

建议研讨组先不要直接看系统加速比，而先看 5 个指标：

1. 数值稳定性
2. bank 数与面积增长
3. 主路径周期
4. correction 触发率
5. `CRT` / reconstruction 边界压力

## 9. 建议的小组讨论流程

建议一次讨论按下面顺序进行：

1. 先确认主目标是 `FP64 mixed-precision CIM macro`，不是系统 primitive
2. 过一遍本地已有 workload 证据
3. 过一遍本地 `RNS/CRT` 主线当前进度
4. 在 `方案 1 / 2 / 3` 三选一里先定主线
5. 再定第二语义模式要不要引入
6. 最后才讨论具体 bank / correction / fallback 细节

## 10. 本地支撑文件列表

如果小组成员需要继续看原始材料，优先读下面这些：

### workload / 数据集

- [`qe_subspace_dataset_status_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_dataset_status_20260312.md)
- [`qe_subspace_profile_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_subspace_profile_20260312.md)
- [`CIM_data_residency_analysis.md`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/CIM_data_residency_analysis.md)

### `FP64` 算术主线

- [`complex_fp64_gemm_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_spec_v0.md)
- [`complex_fp64_gemm_cost_model_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/complex_fp64_gemm_cost_model_v0.md)
- [`ozaki_crt_algorithm_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/ozaki_crt_algorithm_freeze_v0.md)
- [`complex_ozaki_fp64_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/complex_ozaki_fp64_validation.md)

### 对角化 / 行为级原型

- [`iterative_subspace_flow.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/iterative_subspace_flow.md)
- [`generalized_subspace_validation.md`](/Volumes/remote/phd/year_2/project/dft加速/model/docs/generalized_subspace_validation.md)
- [`nml_generalized_eigensolver_freeze_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/nml_generalized_eigensolver_freeze_v0.md)

### 方案空间 / 论文定位

- [`projector_primitive_hardware_solution_space_20260316.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/projector_primitive_hardware_solution_space_20260316.md)
- [`circuit_innovation_candidates_20260316.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/circuit_innovation_candidates_20260316.md)
- [`dual_operator_projection_cim_positioning_20260314.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/dual_operator_projection_cim_positioning_20260314.md)

## 11. 最终建议

给研讨小组的最直接建议是：

1. **确认主线继续以 `RNS/CRT` 为核心**
2. **不要再把问题讲成“通用 projector primitive”**
3. **把创新点收缩成“FP64 mixed-precision 双模式存算宏”**
4. **优先讨论第二模式是否定义为 `risk-aware select / correct`**

如果这四点能定下来，后面无论是写电路方案、补 cost model，还是做行为级对照，都能明显收敛。
