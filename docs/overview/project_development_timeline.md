# 项目开发时间线与思路演进

## 1. 文档目的

这份文档把 `docs/` 目录下已经形成的设计、采样、画像、冻结、赛道判断与硬件原语文档整理成一条**按时间推进的项目开发主线**。

它的作用不是替代原始文档，而是作为：

- 项目的统一入口文档
- 开发流程与思路演进记录
- 后续写论文、做汇报、继续探索时的背景总览

这份总文档特别关注两件事：

- 每个阶段我们当时到底在试图回答什么问题
- 某个阶段的结论是怎样推动下一阶段转向的

目前除 [`agent_handoff_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/agent_handoff_20260312.md) 与 [`qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md) 外，大部分阶段性设计文档已经并入本文件并清理删除。
因此下文提到的大多数旧文件名，主要用于记录项目演进节点，而不再对应独立文档。

后续如果还产生新的阶段性设计文档，它们也应优先作为“源记录 / 证据文档”存在，并定期折叠回本文件，避免 `docs/` 再次回到平铺堆积的状态。

`2026-03-21` 之后新增的系统级 workload 复核、`QE-connected band-solver subsystem` 建模，以及以 `CIM Array Core` 为中心的 `v1` 执行架构，其核心结论现在也继续并入本文件；相关原文保留为查证和复现实验所需的源文档，主要包括：

- [`docs/benchmarks/qe_system_workload_revalidation_report_20260321.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)
- [`docs/survey/vasp_qe_gpu_support_evolution_20260330.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/vasp_qe_gpu_support_evolution_20260330.md)
- [`docs/architecture/qe_band_solver_systemc_overview_20260325.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_systemc_overview_20260325.md)
- [`docs/architecture/qe_band_solver_transaction_semantics_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_transaction_semantics_20260326.md)
- [`model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md)

## 2. 排序规则

本时间线优先按照**文档主题对应的日期**排序，而不是严格按 Git 首次提交时间排序。

也就是说：

- 文件名或标题里带有日期的文档，优先按该日期放入时间线
- 没有显式日期的文档，按首次成文时间和上下文依赖关系放入时间线
- 像 `agent_handoff_20260312.md`、`qe_subspace_profile_20260312.md` 这类“后写成、但记录的是 2026-03-12 阶段状态”的文档，放回它们实际描述的阶段

因此，这份文档反映的是**项目思路的演进顺序**，而不只是文件进入仓库的顺序。

## 3. 项目一句话定义

这个项目的长期目标，是面向 `QE / PySCF / VASP` 这类 DFT 科学计算软件，设计一套以 `NML + CIM` 为核心、能够处理 `complex FP64` 密集线性代数与 reduced-space eigensolver 的专用加速系统。

当前最聚焦的论文切口，则经历了下面这条明显的收敛路径：

```text
从 “做一个 complex FP64 GEMM / 子空间对角化加速模块”
逐步推进到
“围绕真实 QE `c_bands` 工作流，定义一个以 projector/operator chain 为核心的 band-solver subsystem”
```

## 4. 当前主线结论（截至 2026-03-26）

- 系统长期目标没有变，仍然是服务 `QE / PySCF` 这类 DFT 软件，而不是做一个孤立的数值 IP。
- 当前 paper cut 仍然落在 `QE Davidson` 子空间路径，以及其中涉及的 `complex FP64 GEMM`、Hermitian / generalized Hermitian reduced problem。
- 真实 workload 画像已经说明：generalized Hermitian 不是边角情况，`S_sub` 不能被省略，单一 `Si` case 不能代表整体。
- 算法侧已经形成两条需要冻结的主线：
  - `Ozaki-II + CRT + Karatsuba 3M` 的 `complex FP64 GEMM`
  - `NML` 侧面向 reduced-space 的 generalized eigensolver 路线
- 电路/原语侧的中心思想已经从“通用 GEMM-CIM + transpose”转向“adjoint-aware projector primitive”。
- 当前最接近实现形态的硬件描述是：
  - `Projector-Stationary Asymmetric Bra/Ket Macro Cluster`
- 系统级对象已经进一步收敛为：
  - `QE-connected band-solver subsystem`
- `v1` 片上分工在当前文档与 demo 中已经进一步固定为：
  - `CIM Array Core + Near-SRAM Support Domain + Reduction/Closure / Vector/Diag Digital Companions + explicit FFT Companion`
- 已经存在一个可运行的 `SystemC v0` / timed-functional 演示，用于表达单个 `c_bands episode` 的 `Host -> FPGA -> Chip -> closure -> host` 闭环。
- 当前系统执行口径已经不再只是“模块框图”，而是一个明确的 `c_bands episode` contract：
  - `Host issue -> FPGA load/dispatch/join -> Chip-local operator/FFT/aggregation/closure/update -> complete`

## 5. 时间线总览

| 时间 | 阶段 | 核心问题 | 代表文档 |
| --- | --- | --- | --- |
| 2026-03-12 | 系统起步与工作负载落点 | 这个项目到底是在做系统、算子，还是论文切口？ | `design.md`, `Si体系h_psi局域势数据流分析.md`, `complex_fp64_gemm_spec_v0.md`, `qe_subspace_sampling.md` |
| 2026-03-12 | 真实 QE 数据集与状态快照 | reduced-space 矩阵到底长什么样，是否足以支撑系统约束？ | `agent_handoff_20260312.md`, `benchmarks/qe_subspace_profile_20260312.md`, `benchmarks/qe_subspace_dataset_status_20260312.md` |
| 2026-03-14 | 论文赛道与创新点重定位 | 这个工作如何包装成顶会级芯片论文，而不是领域化应用？ | `conference_session_map_20260314.md`, `conference_track_fit_20260314.md`, `dual_operator_projection_cim_positioning_20260314.md` |
| 2026-03-16 | 算法冻结与成本拆账 | 哪些算法主线已经成立，哪些细节必须冻结，代价账怎么算？ | `algorithm_freeze_status_v0.md`, `ozaki_crt_algorithm_freeze_v0.md`, `nml_generalized_eigensolver_freeze_v0.md`, `complex_fp64_gemm_cost_model_v0.md` |
| 2026-03-16 | 电路创新点转向 projector primitive | 真正值得打的创新点是什么，为什么不能只讲 transpose？ | `circuit_innovation_candidates_20260316.md`, `adjoint_projector_primitive_spec_v0.md`, `projector_primitive_hardware_solution_space_20260316.md` |
| 2026-03-17 | 研讨会材料压缩与对外表达 | 如何把当前判断压成一份能讨论、能拍板的简报？ | `seminar_fp64_cim_macro_brief_20260317.md` |
| 2026-03-18 | 实现形态收敛 | 如果真的做这个原语，最合理的宏级组织长什么样？ | `adjoint_projector_primitive_implementation_v0.md` |
| 2026-03-21 | 系统级 workload 复核 | 真实 `QE` 全流程里到底应该抓哪个系统对象？ | `benchmarks/qe_system_workload_revalidation_report_20260321.md` |
| 2026-03-22 ~ 2026-03-23 | 行业对照与软件范式梳理 | 当前主流到底在加速什么，我们的切口与 GPU 主流路线差在哪？ | `dft_acceleration_industry_survey_20260322.md`, `dft_acceleration_vasp_qe_pyscf_survey_20260323.md` |
| 2026-03-23 | 系统对象提升到 band-solver subsystem | 为什么不能只讲 `diaghg`，而应该讲 `QE-connected band-solver subsystem`？ | `system_design_master_spec_v0.md` |
| 2026-03-25 ~ 2026-03-26 | `v1` 系统架构与 SystemC v0 demo 落地 | 如何把当前 Host/FPGA/Chip 分工、chip 内部划分与 `c_bands episode` 执行机制固定成统一口径？ | `qe_band_solver_systemc_overview_20260325.md`, `qe_band_solver_transaction_semantics_20260326.md`, `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md` |
| 2026-03-30 | VASP / QE GPU 历史补充 | 主流 DFT 软件究竟何时开始把 GPU / 异构加速纳入主线工程？ | `vasp_qe_gpu_support_evolution_20260330.md` |

## 6. 2026-03-12：先把系统边界和真实工作负载钉住

### 6.1 我们最开始在解决什么问题

在这个阶段，项目最容易走偏的风险是：

- 直接从某个电路宏出发
- 把问题缩成“做一个复数矩阵乘法器”
- 或者把论文范围放大成“加速整个 DFT 软件”

因此最先做的不是某个 datapath，而是重新确认系统边界。

### 6.2 这一阶段形成的核心判断

从早期系统设计文档 `design.md` 可以看出，最早的系统判断已经很明确：

- 这是一个面向 `QE / PySCF` 的 DFT 科学计算加速系统问题
- 当前论文不能宣称“完整加速整个 DFT”
- 最合理的切口，是从真实软件里提取一个可验证、可落地、可扩展的子问题

这个阶段的重要意义在于，我们没有把自己锁死在“某个已有硬件模板”，而是先问：

- 真实热点是什么
- 哪些热点值得变成硬件主路径
- `Host / runtime / NML / CIM` 应该如何分工

### 6.3 我们当时还在尝试哪些工作负载入口

早期分析文档 `Si体系h_psi局域势数据流分析.md` 记录了另一个非常重要的动作：

- 我们没有一开始就只盯着 reduced eigensolver
- 还认真分析了 `QE` 中 `h_psi` 局域势作用的数据流

这一步的价值不在于它后来是否成为主线，而在于它帮助我们建立了一个共识：

- 必须从 `QE` 的真实代码路径和真实张量规模出发
- 先理解软件里的数据流，再谈硬件映射
- `DFT` 热点往往不是单一矩阵乘，而是带有很强结构的数据搬运与变换链路

### 6.4 当前 paper cut 在这一阶段被固定下来

`complex_fp64_gemm_spec_v0.md` 和 [`qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md) 一起，构成了这个阶段最关键的落地动作。

这里我们实际上做了两件事：

- 一方面把 `complex FP64 GEMM` 定义成系统里的关键子系统
- 另一方面在 `QE` 工作区副本里对 `cdiaghg / rdiaghg` 做插桩，直接采样真实 `H_sub / S_sub`

这说明项目在 2026-03-12 这一天已经完成了一个非常关键的转折：

- 不再凭印象假设 reduced-space 矩阵长什么样
- 开始建立“真实 QE 样本 -> 离线验证 -> 系统设计约束”的闭环

### 6.5 这一阶段的代表文档

- `design.md`
- `Si体系h_psi局域势数据流分析.md`
- `complex_fp64_gemm_spec_v0.md`
- [`qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md)

## 7. 2026-03-12：真实 QE reduced-space 数据开始接管叙事

### 7.1 这一阶段新增了什么

这一阶段最重要的，不是又多写了几篇设计文档，而是我们终于拿到了能够约束系统设计的真实样本。

阶段性总结 `benchmarks/qe_subspace_profile_20260312.md` 和 `benchmarks/qe_subspace_dataset_status_20260312.md` 把这一点固定了下来。

与此同时，[`agent_handoff_20260312.md`](agent_handoff_20260312.md) 作为状态快照，把当时已经做完的事情和后续优先级也整理清楚了。

### 7.2 这一阶段形成的关键事实

这个阶段最重要的不是“我们已经有了一些 trace”，而是以下几个判断第一次变得有证据支撑：

- `QE Davidson` 的子空间问题不是单一路径
- generalized Hermitian 是主路径，而不是边角情况
- `S_sub` 不能被简单视为单位阵附近的小扰动
- `Si` 以外的体系会显著改变 reduced matrix 的规模和统计特征
- 子空间维度会随着体系类型明显变化，不能只按最小样本定硬件尺寸

因此项目从这一阶段开始，真正变成了：

- 基于真实 workload 画像驱动的系统设计

而不再是：

- 对某种“想象中的矩阵负载”做硬件设想

### 7.3 这一阶段对后续的影响

后面很多判断，都是从这一步生长出来的：

- 为什么要把 generalized Hermitian 放在主路径，而不是只做标准 Hermitian
- 为什么 `complex FP64 GEMM` 不能只是一个孤立 IP
- 为什么后面会开始认真考虑 `HX / SX / X^H H X / X^H S X` 这类 primitive 级叙事

### 7.4 这一阶段的代表文档

- [`agent_handoff_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/agent_handoff_20260312.md)
- `benchmarks/qe_subspace_profile_20260312.md`
- `benchmarks/qe_subspace_dataset_status_20260312.md`

## 8. 2026-03-14：从“能不能做”转向“怎样成为顶会创新点”

### 8.1 这一阶段为什么重要

有了真实 workload 之后，接下来的问题就不只是“技术上能不能实现”，而是：

- 这件事到底该怎么讲成一篇顶会芯片论文
- 它更像 `CIM macro`、`DSA`、`processor` 还是某种 subsystem
- 真正有说服力的创新点到底在哪里

这就是 `conference_session_map_20260314.md`、`conference_track_fit_20260314.md`、`dual_operator_projection_cim_positioning_20260314.md` 这一组文档的背景。

### 8.2 这一阶段的核心思路变化

这组文档最重要的贡献，不是“帮我们选会议”，而是推动了一个更深的收敛：

- 不能只把工作讲成“把 `QE` 跑到一个 `CIM` 上”
- 也不能只讲“我们支持 `HX` 和 `SX`”
- 真正值得形成电路创新点的，是把 primitive 从单算子乘法提升到**投影型 / 双算子型 primitive**

也就是说，创新点的中心开始从：

- `FP64`
- `mixed precision`
- `transpose`

逐步转向：

- workload-native primitive
- dual-operator / projection-aware hardware contract

### 8.3 这一阶段留下的遗产

到这一步，项目第一次开始具备“可写成顶会故事”的雏形：

- 有真实软件来源
- 有结构化 workload 画像
- 有明确的 primitive-level 创新方向
- 也知道应该和哪些 baseline 比

### 8.4 这一阶段的代表文档

- `conference_session_map_20260314.md`
- `conference_track_fit_20260314.md`
- `dual_operator_projection_cim_positioning_20260314.md`

## 9. 2026-03-16：真正的瓶颈变成“算法冻结”，而不是“没有方向”

### 9.1 这一阶段的判断

到了这个阶段，项目的主要问题已经不再是缺方向，而是：

- 大方向很多都已经形成
- 但关键设计还没有逐条冻结

`algorithm_freeze_status_v0.md` 非常清楚地记录了这个状态。

### 9.2 `complex FP64 GEMM` 主线在这一阶段变得更清楚

`ozaki_crt_algorithm_freeze_v0.md` 和 `complex_fp64_gemm_cost_model_v0.md` 记录了 GEMM 主线的两层推进：

- 算法上，主路线开始明确收敛到 `Ozaki-II + CRT + Karatsuba 3M`
- 代价上，开始认真拆 `L`、real GEMM 次数、buffer、residue、CRT 重构的账

这一步的意义非常大，因为它把很多原本停留在“可行性”层面的讨论，往“代价可解释性”推进了一大步。

### 9.3 第一创新点的正确 claim 也在这一阶段逐渐被讲清

除了 `Ozaki-II / CRT` 的主算法冻结，后续补出的 [`docs/cim/fused_digit_residue_multiply_flow_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/cim/fused_digit_residue_multiply_flow_v0.md) 还把第一个创新点里最容易讲偏的地方重新钉清了。

这里形成的关键判断是：

- `Fused digit-residue` 不能被讲成“单次两个 `FP64` 相乘时，最终所需模数神奇地少很多”
- 更准确的说法是：
  - 把 `streaming operand` 的 `radix -> residue` 转换吞进主乘法 / project 主循环
  - 让 active modulus planes 随 digit stage 渐进打开
  - 从而改变的是 stage-by-stage 的激活模平面与 promotion 调度，而不是 worst-case 总动态范围的数学下界

这件事的重要性在于，它避免了论文叙事里最危险的一种误表述：

- 不是“动态范围奇迹”
- 而是“乘法/乘加流程创新 + project mode 下的 stage schedule 创新”

也正因为如此，这条线最适合落在：

- `project / inner-product / streaming project kernel`

而不是：

- 孤立的单次 `FP64` 乘法故事

### 9.4 `NML` 侧 eigensolver 也进入冻结阶段

`nml_generalized_eigensolver_freeze_v0.md` 记录了另一个同样重要的事实：

- 项目并不满足于“外部有一个 LAPACK baseline 就行”
- 我们在认真讨论 `NML` 侧到底该采用 direct dense generalized solver，还是更贴近固定矩阵负载模型的 near-memory 迭代微对角化

这说明系统视角仍然被保留下来了：

- `GEMM` 不是全部
- reduced eigensolver 也必须进入硬件故事

### 9.5 这一阶段的代表文档

- `algorithm_freeze_status_v0.md`
- `ozaki_crt_algorithm_freeze_v0.md`
- `nml_generalized_eigensolver_freeze_v0.md`
- `complex_fp64_gemm_cost_model_v0.md`
- [`docs/cim/fused_digit_residue_multiply_flow_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/cim/fused_digit_residue_multiply_flow_v0.md)

## 10. 2026-03-16：电路创新点从“transpose 能力”进一步抬升到“projector primitive”

### 10.1 为什么这里又发生了一次转向

到这一步，项目已经有：

- 真实 workload
- 算法主线
- 子系统成本模型

但仍然缺一件顶会论文最关键的东西：

- 一个足够强的**宏级 / 原语级创新点**

`circuit_innovation_candidates_20260316.md` 把这个问题正面提了出来。

### 10.2 这一阶段形成的核心共识

这个阶段最关键的思路变化是：

- “支持 transpose”不是最终创新点
- “做一个会跑 `FP64` 的通用 GEMM-CIM”也不够
- 真正更深的共性，是 `QE / VASP / PySCF` 里反复出现的：

```text
project -> small transform -> back-project
```

于是 `adjoint_projector_primitive_spec_v0.md` 开始把这个模式定义成一个正式的 primitive：

- `Y = P M P^H X`
- 可选 reduced 输出 `G = X^H P M P^H X`
- 强调 `P` 常驻、`X` 流动、`M` 小而局部、`P` 与 `P^H` 共享硬件视图

### 10.3 方案空间扫描也在这一阶段补齐

`projector_primitive_hardware_solution_space_20260316.md` 的作用，是把这个 primitive 放到更大的硬件实现空间里重新审视：

- `CIM`
- hybrid-CIM
- near-memory
- programmable accelerator

这一步防止了另一个很常见的问题：

- 先爱上一个实现技术
- 再倒推工作负载去适配它

相反，这里做的是：

- 先固定 primitive 语义
- 再看哪类硬件路线最适合承载它

### 10.4 这一阶段留下的最重要变化

到这里，项目的核心叙事已经明显变了：

- 之前更像 `complex FP64 GEMM + generalized eigensolver`
- 之后更像 `adjoint-aware projector primitive + local FP64 reduced engine`

前者仍然重要，但更像实现基座；后者开始成为论文级创新点候选。

### 10.5 这一阶段的代表文档

- `circuit_innovation_candidates_20260316.md`
- `adjoint_projector_primitive_spec_v0.md`
- `projector_primitive_hardware_solution_space_20260316.md`

## 11. 2026-03-17：把当前收敛判断压缩成研讨会可讨论版本

`seminar_fp64_cim_macro_brief_20260317.md` 的价值，不在于它提出了全新的技术路线，而在于它把这段时间形成的判断压成了一份能讨论、能快速决策的材料。

这份文档反映了一个很真实的中间状态：

- `Ozaki-II / RNS / CRT` 这条高精度算术主线仍然稳
- 但仅仅有“算术映射”还不足以支撑宏级创新点
- 因此需要继续补强 primitive / 模式切换 / 风险感知修正等更高层次的故事

它相当于把项目当时的“讨论温度”留了下来：

- 我们已经知道哪些东西靠谱
- 也已经知道现有故事哪里还不够强

## 12. 2026-03-18：实现形态收敛到非对称 Bra/Ket 宏簇

### 12.1 这一阶段解决的不是“要不要做 primitive”，而是“怎么做”

如果说 `adjoint_projector_primitive_spec_v0.md` 解决的是“primitive 应该长什么样”，那么 `adjoint_projector_primitive_implementation_v0.md` 解决的就是：

- 这个 primitive 不应该只是概念定义
- 它需要落到一种有明确结构特征的宏级组织上

### 12.2 这一阶段的实现判断

这份文档最重要的结论是：

- 不应照搬 AI 场景里的通用 `GEMM-CIM`
- 不应只加一点 `transpose` 支持就结束
- 不应假设 `P^H X` 和 `P T` 可以用完全对称的数据通路处理

相反，文档提出的实现方向是：

- `Projector-Stationary Asymmetric Bra/Ket Macro Cluster`

这背后的思想很清楚：

- `P^H X` 是沿大维度的长归约
- `P T` 是沿小维度的短归约
- 两者负载形状天然不对称
- 因此更合理的实现，是让同一份常驻 `P` 支持两条不对称的数据流路径

### 12.3 这一阶段意味着什么

到这里，项目第一次有了“从 workload -> primitive -> hardware organization”完整贯通的主线。

也就是说，现在项目不再只是若干并列的文档集合，而是已经能够形成：

```text
真实 QE / PySCF 负载
-> 提炼出 projector / basis / subspace 共同模式
-> 定义 adjoint-aware primitive
-> 进一步落成 bra/ket 非对称宏簇
```

## 13. 2026-03-21：系统级 workload 复核把“系统对象”钉到 `c_bands`

### 13.1 为什么这一阶段很关键

在 `2026-03-12 ~ 2026-03-18` 这条主线上，我们已经逐渐把叙事重心放到 reduced-space、`projector primitive` 和宏级组织上。

但这里还缺一块非常关键的证据：

- 如果把视角抬回真实 `QE` 全流程
- 真正值得在系统层抓住的对象，到底是不是我们正在讲的这一段
- 以及它究竟应该被叫作 `diaghg`、`Davidson reduced solve`，还是别的东西

[`docs/benchmarks/qe_system_workload_revalidation_report_20260321.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md) 的作用，就是把这个系统级问题重新用真实 rerun 数据钉一遍。

### 13.2 这一阶段新增的关键事实

这份复核报告最重要的贡献，不是又补了几张表，而是把几个系统级判断第一次量化固定了下来。

第一，`electrons` 时间里最值得抓的对象稳定落在 `c_bands`：

- 成功 full-run 的代表 case 中，`c_bands` share 落在 `45.0% ~ 95.2%`
- 即使体系不大，这个判断也已经成立
- 因此真正的系统对象不是“泛泛的 DFT 全流程”，而是 `electrons -> c_bands`

第二，Davidson 路径内部最重的也不是 reduced diag 末端：

- `*egterg` 内部主要时间持续落在 `h_psi`
- `cdiaghg / rdiaghg` 只占较小一块
- 这说明系统对象不能再被定义成“一个 generalized reduced eigensolver IP”

第三，真实 `QE` band solver 不是单一路径：

- `PBE` 小体系在本轮 rerun 中主要走 Davidson
- `PBE0` 的真实输入设置则会把系统切到 `CG`
- 因此系统不能假设“接入 `QE` 后永远只有 Davidson reduced solve”

### 13.3 这一阶段怎样推动后续转向

这一步之后，项目的系统对象发生了一个很重要的抬升：

- 不再把系统目标写成 `diaghg` 或 reduced-space kernel
- 也不再试图把整个 `DFT SoC` 一把吞下
- 而是更准确地收敛到：
  - `QE band-solver workload family`
  - 以及它在系统上的承接对象：`electrons -> c_bands`

这也为后面的系统架构给出了直接约束：

- 第一版系统必须以 `band-solver subsystem` 为对象
- 主线仍然可以聚焦 Davidson
- 但边界上必须允许 `CG companion / fallback path`
- 真正需要被片上闭环承接的，是 `operator application -> reduced build -> closure / update` 这条反复链

### 13.4 这一阶段的代表文档

- [`docs/benchmarks/qe_system_workload_revalidation_report_20260321.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)
- [`tools/benchmarks/run_qe_workload_matrix.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/run_qe_workload_matrix.py)
- [`tools/benchmarks/analyze_qe_workload_revalidation.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/analyze_qe_workload_revalidation.py)

## 14. 2026-03-22 ~ 2026-03-23：行业对照把主流路线与我们的差异化位置讲清楚

### 14.1 为什么这里需要一次“抬头看行业”

在 `2026-03-21` 的系统级 workload 复核之后，我们已经知道：

- 当前最值得抓的系统对象是 `electrons -> c_bands`
- `QE-connected band-solver subsystem` 是最可信的第一版系统边界

但如果只盯着本地项目内部文档，仍然会缺一层很重要的外部参照：

- 近三年行业里真正成熟、真正主流的 DFT 加速路线是什么
- `VASP / QE / PySCF` 三类代表性软件到底各自主要靠什么加速
- 我们这条 `CIM / NML / subsystem` 路线到底是在顺着主流走，还是在做差异化探索

[`docs/survey/dft_acceleration_industry_survey_20260322.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_industry_survey_20260322.md) 和 [`docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md) 的价值，就在于给这件事补上一层外部坐标系。

### 14.2 这一阶段固定下来的几个外部对照结论

第一，当前行业里**最成熟的主线**，并不是专用芯片，而是：

- 把已有生产代码持续 `GPU` 化
- 围绕 `FFT / eigensolver / projector / exact exchange / solver infrastructure` 做库化和可移植性重构

也就是说，主流世界真正稳定投入的，是：

- `GPU + 生产软件`
- `solver / FFT / dense linear algebra` 基础设施

而不是：

- `FPGA / ASIC / PIM / CIM` 这类专用硬件大规模落地

第二，三类代表性软件虽然都在加速 `SCF` 主循环热点，但 workload 结构并不完全一样：

- `VASP / QE` 更像 `plane-wave + band-solver + FFT / projector`
- `PySCF` 更像 `Gaussian / orbital + ERI / J/K / XC / density fitting`

这说明我们后面如果要讲 primitive 共性，必须分清：

- 哪些是 `QE / VASP` 这类 plane-wave 主线特有的
- 哪些才真能跨到 `PySCF`

第三，如果只选一个真实软件入口继续深挖，`QE` 的位置仍然最合理：

- 和 `VASP` 同属 plane-wave 主流
- 又比 `VASP` 更开放、更可插桩、更易复现
- 同时还能帮助我们和 `PySCF` 这类轨道基工作负载形成清晰边界

### 14.3 这一阶段对项目叙事的帮助

这次行业对照没有改变项目主对象，但它把“我们到底在主流版图里的什么位置”讲清楚了。

更准确地说，当前项目不应被讲成：

- 取代主流 `GPU` 生产软件栈的通用方案
- 或者已经具有大规模行业成熟度的 DFT 专用硬件

而应被讲成：

- 以 `QE` 为锚点
- 围绕真实 `band-solver` workload family
- 相对主流 `GPU + library` 路线做差异化的 `DFT-native subsystem` 探索

这一步的价值非常大，因为它同时帮我们守住了两件事：

- 不夸大产业成熟度
- 也不把自己的切口缩回到“只是一个 kernel 小优化”

### 14.4 这一阶段的代表文档

- [`docs/survey/dft_acceleration_industry_survey_20260322.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_industry_survey_20260322.md)
- [`docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md)

## 15. 2026-03-23：系统对象正式抬升到 `QE-connected band-solver subsystem`

### 14.1 这一阶段解决的，不再是单个 kernel 问题

有了 `2026-03-21` 的系统级复核之后，接下来的问题就不再是：

- 我们是不是要再找一个更重的 kernel
- 或者要不要继续把 reduced eigensolver 讲得更细

而是：

- 如果老师要的是一个真正 `DFT-native` 的系统对象
- 那么这个系统到底应该围绕什么来定义
- 它和“完整 `DFT SoC`”以及“孤立 kernel IP”之间的边界到底在哪里

这一步形成的系统叙事升级，现在已经并入 [`docs/architecture/system_design_master_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md)。原先额外承担问题定义、模块规格和审核导航角色的重复文档，也已经在本轮整理中一起并入主规范，不再单独保留。

### 14.2 这一阶段固定下来的四类系统契约

这组文档最重要的，不只是提出了一个新名字，而是把系统层必须回答的契约拆清楚了。

第一类是**算子链契约**：

```text
h_psi / s_psi
-> reduced H/S build
-> generalized reduced solve
-> residual / precondition / basis update
-> repeat
```

这说明系统承接对象不再是单一 `GEMM`，而是一条稳定反复出现的 operator chain。

第二类是**数据流契约**：

- 哪些对象应 resident，例如 `projector / beta`
- 哪些对象应 streaming，例如 `X / band blocks`
- 哪些中间结果值得留在片上，而不是立即回写 Host

第三类是**数值契约**：

- `complex`
- `FP64`
- Hermitian / generalized Hermitian
- `S_sub` 不能忽略
- 必要时必须保留 fallback / companion 路径

第四类是**软件契约**：

- `Host / QE` 继续拥有 `SCF` 外环与全局语义
- `FPGA / runtime` 负责编排、切换和 glue
- `chip` 负责最适合片上固化的 primitive cluster

### 14.3 这一阶段形成的一句话系统定义

到这里，项目终于有了一个比“kernel 加速器”更稳定、又比“完整 `DFT SoC`”更可信的一句话定义：

> 第一版真正该做的，不是 `DFT SoC`，也不是孤立 `GEMM-CIM`，而是一个接入真实 `QE` band-solver 主路径、以 `projector / operator-application + local reduced companion engine` 为核心的异构系统。

也正是在这里，`QE-connected band-solver subsystem` 成为当前最可信的系统级对象。

### 14.4 这一阶段的代表文档

- [`docs/architecture/system_design_master_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md)

## 16. 2026-03-25 ~ 2026-03-26：`v1` 架构口径冻结到以 `CIM Array Core` 为中心的 band-solver subsystem

### 15.1 这一阶段把 chip 内部分工真正写实了

前面几轮文档已经把系统边界和 paper story 往上抬，但到这个阶段之前，chip 内部到底该怎么画，仍然还有含混空间。

尤其有两个风险需要被明确消除：

- 把 `near-SRAM` 说成主体，再把 `CIM` 放成可有可无的 flavor
- 只画模块框图，却不把 episode 执行机制和 transaction handoff 讲清楚

这个阶段形成的统一口径是：

> `v1` 不是“near-memory 为主体、CIM 可有可无”的方案，而是一个以 `CIM Array Core` 为中心的 `QE-only heterogeneous band-solver subsystem`。

对应到 chip 内部，当前固定下来的 `v1` 结构是：

- `CIM Array Core`
- `Near-SRAM Support Domain`
- `Reduction/Closure Digital Companion`
- `Vector/Diag Digital Companion`
- explicit `FFT Companion`

这里最重要的系统判断有两点：

- `Near-SRAM` 是围绕 array 的 support shell，不是替代主核的借口
- `FFT` 不是角落脚注，而是系统执行机制中的显式第二主线

### 15.2 这一阶段把执行口径从“框图”推进到 `c_bands episode` contract

`2026-03-26` 的文档补丁最关键的地方，不只是多画了一张图，而是把整个系统写成了一个明确的 `episode contract`：

```text
Host issue
-> FPGA resident load / dispatch / join
-> Chip-local operator apply
-> FFT-related stage
-> local aggregation
-> reduced closure
-> residual-update
-> complete
```

也就是说，当前架构的表达已经不再只是：

- 哪几个模块放在 chip 上
- 哪几个模块放在 FPGA 上

而是进一步明确了：

- 控制流和数据流必须分开讲
- `instruction / transaction / token` handoff 是架构的一部分
- `Host / FPGA / Chip` 三层之间的事件推进关系必须显式写出来

因此，`c_bands episode` 已经不是一个实现细节，而是当前系统级定义的一部分。

### 15.3 `SystemC v0` demo 的意义

同一阶段并入主仓库的 `SystemC v0` / timed-functional demo，则把这套分工与执行口径落成了一个可运行原型。

它建模的不是完整 `QE`，而是一个单次 `c_bands episode` 的最小闭环：

```text
HostSCF(mock)
-> FPGAOrchestrator
-> ChipTop
-> CIM Array / Near-SRAM / Digital Companions
-> episode complete
-> Host rho update / convergence check
```

这个 demo 的价值不在数值精度，而在于：

- 把 Host / FPGA / Chip 的边界显式可执行化
- 把 `operator / FFT / aggregation / closure / update` 的 transaction 关系固定下来
- 为后续把 timed-functional 模型升级成更强的 trace / capacity / timing faithful 模型提供骨架

### 15.4 这一阶段的代表文档

- [`docs/architecture/qe_band_solver_systemc_overview_20260325.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_systemc_overview_20260325.md)
- [`docs/architecture/qe_band_solver_transaction_semantics_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_transaction_semantics_20260326.md)
- [`model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md)
- `model/qe_band_solver_model/`

## 17. 截至当前已经形成的稳定共识

- 项目必须从真实 `QE / PySCF` 软件路径出发，而不是从人工 benchmark 出发。
- 当前最可信的系统对象，已经不是孤立 reduced kernel，而是 `QE-connected band-solver subsystem`。
- 从行业对照看，当前最成熟的主流路线仍然是 `GPU` 化生产代码 + `solver / FFT / library` 基础设施；我们的切口属于以 `QE` 为锚点的差异化专用体系探索，而不是替代主流 `GPU` 软件栈。
- 真实 workload 应被理解为一个以 `c_bands` 为中心的 band-solver family，而不是永远固定在单一路径上的 `Davidson diaghg`。
- 当前 paper cut 仍然聚焦 `QE Davidson` 子空间路径，但它所依附的系统边界已经扩大到 `operator application -> reduced build -> closure / update` 这条完整反复链。
- generalized Hermitian reduced problem 是主路径，`S_sub` 需要认真进入架构、primitive 与系统合同设计。
- 算法冻结的两条主线仍然是：
  - `Ozaki-II + CRT + Karatsuba 3M` 的 `complex FP64 GEMM`
  - `NML` 侧面向 reduced-space 的 generalized eigensolver 路线
- `transpose` 是机制，不是最终故事；primitive 级语义融合才更像真正的创新点。
- 当前最有希望的 primitive 叙事，仍然是围绕 `Adjoint-Aware Projector Primitive` 展开。
- 当前最贴近实现的宏级组织，仍然是 `Projector-Stationary Asymmetric Bra/Ket Macro Cluster`。
- 当前 `v1` 系统分工已经基本固定为：
  - `CIM Array Core + Near-SRAM Support Domain + Reduction/Closure / Vector/Diag Digital Companions + explicit FFT Companion`
- 当前系统执行口径已经固定为一个明确的 `c_bands episode` contract：
  - `Host issue -> FPGA load/dispatch/join -> Chip-local operator/FFT/aggregation/closure/update -> complete`
- 已经存在一个可运行的 `SystemC v0` / timed-functional 演示，用于表达这套边界、模块和 transaction 语义。

## 18. 仍未完全冻结的问题

- `Ozaki-II / CRT` 路线中，模数个数、residue 调度、CRT 组织和 fallback contract 仍需继续冻结。
- `NML` 侧 generalized eigensolver 到底采用 direct dense 主线，还是 fixed-matrix iterative 主线，仍需更明确地收敛。
- `Davidson main path` 与 `CG companion / fallback path` 的系统边界到底如何定量描述，仍需进一步冻结。
- `FFT Companion` 在 `v1` 里的定量角色还需要继续澄清：哪些路径是必须显式保留的主线，哪些只是辅助支路。
- 当前 `SystemC v0` / timed-functional 规格，后续如何升级成更 trace-faithful、capacity-faithful 或 timing-faithful 的模型，还需要继续规划。
- projector primitive 的论文落点，还需要进一步量化相对于 `GEMM baseline` 和 `transpose-aware macro baseline` 的成本/收益差异。
- `QE / VASP / PySCF` 三类软件之间，primitive 的共性边界和特例边界，还需要继续梳理。

## 19. 原始文档时间序索引

下面按本时间线采用的顺序，把 `docs/` 目录里的原始文档做一个索引。

### 2026-03-12

1. `design.md`
   系统总设计入口，定义长期目标、当前论文切口和系统分工；已并入本文件。
2. `Si体系h_psi局域势数据流分析.md`
   早期从真实 `QE` 数据流理解局域势路径的尝试；已并入本文件。
3. `complex_fp64_gemm_spec_v0.md`
   `complex FP64 GEMM` 子系统规格说明；已并入本文件。
4. [`qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md)
   `QE` 子空间 reduced matrix 采样说明与复现方法。
5. [`agent_handoff_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/agent_handoff_20260312.md)
   对 2026-03-12 阶段工作状态的总结与交接。
6. `benchmarks/qe_subspace_profile_20260312.md`
   `QE Davidson` reduced-space 矩阵画像；已并入本文件。
7. `benchmarks/qe_subspace_dataset_status_20260312.md`
   多体系 `QE` 子空间数据集状态总结；已并入本文件。

### 2026-03-14

1. `conference_session_map_20260314.md`
   2026 顶会 session/category 映射；已并入本文件。
2. `conference_track_fit_20260314.md`
   赛道与创新点匹配评估；已并入本文件。
3. `dual_operator_projection_cim_positioning_20260314.md`
   把工作从应用加速重新包装成 primitive 级芯片创新点；已并入本文件。

### 2026-03-16

1. `algorithm_freeze_status_v0.md`
   算法冻结总状态；已并入本文件。
2. `ozaki_crt_algorithm_freeze_v0.md`
   `complex FP64 GEMM` 主算法冻结草案；已并入本文件。
3. `nml_generalized_eigensolver_freeze_v0.md`
   `NML` 侧 generalized eigensolver 冻结草案；已并入本文件。
4. `complex_fp64_gemm_cost_model_v0.md`
   `complex FP64 GEMM` 成本拆账文档；已并入本文件。
5. `circuit_innovation_candidates_20260316.md`
   从真实负载反推电路创新点候选；已并入本文件。
6. `adjoint_projector_primitive_spec_v0.md`
   `Adjoint-Aware Projector Primitive` 的语义定义；已并入本文件。
7. `projector_primitive_hardware_solution_space_20260316.md`
   与该 primitive 对应的硬件实现路线扫描与筛选；已并入本文件。

### 2026-03-17

1. `seminar_fp64_cim_macro_brief_20260317.md`
   面向研讨讨论的简报版本；已并入本文件。

### 2026-03-18

1. `adjoint_projector_primitive_implementation_v0.md`
   primitive 的实现形态收敛到非对称 Bra/Ket 宏簇；已并入本文件。

### 未显式日期但属于当前主线支撑

1. [`docs/cim/fused_digit_residue_multiply_flow_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/cim/fused_digit_residue_multiply_flow_v0.md)
   对第一创新点里的 `fused digit-residue` 乘法 / project 流做更细粒度展开，重点澄清模数、digit stage 与 promotion 的正确 claim。

### 2026-03-21

1. [`docs/benchmarks/qe_system_workload_revalidation_report_20260321.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)
   用新一轮真实 `QE` rerun 复核系统级 workload，并把系统对象更明确地钉到 `electrons -> c_bands`。
2. [`tools/benchmarks/run_qe_workload_matrix.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/run_qe_workload_matrix.py)
   批量重跑小体系 `QE` workload 的自动化脚本。
3. [`tools/benchmarks/analyze_qe_workload_revalidation.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/analyze_qe_workload_revalidation.py)
   汇总本轮 rerun 结果并生成系统级判断的分析脚本。

### 2026-03-22 ~ 2026-03-23

1. [`docs/survey/dft_acceleration_industry_survey_20260322.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_industry_survey_20260322.md)
   从行业版图角度梳理近三年 `DFT` 加速的主流成熟路线与专用硬件探索位置。
2. [`docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_vasp_qe_pyscf_survey_20260323.md)
   对 `VASP / QE / PySCF` 三种代表性软件的主要加速方式做并排重写，并解释为什么 `QE` 最适合作为当前入口。

### 2026-03-23

1. [`docs/architecture/system_design_master_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md)
   在当前唯一主规范中延续并冻结该系统对象定义，同时吸收了问题定义、模块规格与审核导航的稳定结论。

### 2026-03-25 ~ 2026-03-26

1. [`docs/architecture/qe_band_solver_systemc_overview_20260325.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_systemc_overview_20260325.md)
   总结 `QE band-solver / c_bands episode subsystem` 的 `SystemC v0` 范围、分层和可替换边界。
2. [`docs/architecture/qe_band_solver_transaction_semantics_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/qe_band_solver_transaction_semantics_20260326.md)
   记录 `Host -> FPGA -> Chip` 请求、operator transaction 和 closure transaction 的最小语义。
3. [`model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md)
   记录 merged demo 的构建、运行和 smoke-run 结果。
4. `model/qe_band_solver_model/`
   当前 `QE band-solver subsystem` 的 timed-functional / `SystemC v0` 演示代码。

## 20. 这份总文档应该怎么用

- 如果要快速进入项目背景，先读本文件第 1 到 5 节。
- 如果要找“当前主线是什么”，重点看第 4、13、14、15、16、17、18 节。
- 如果要写汇报、PPT 或论文里的 motivation / system story，重点看第 8、10、13、14、15、16 节。
- 如果要继续做实现与建模，重点看第 9、10、12、16、18 节，并结合 `model/` 下原型代码、[`docs/overview/qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md) 和 [`docs/overview/agent_handoff_20260312.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/agent_handoff_20260312.md)。
- 如果后续又产生新的阶段性说明文档，应优先把它们视作源记录，并尽快回折到本文件，保持这里作为主仓库的统一长文档入口。
- 当前 `docs/` 目录里剩余未回收的文件，建议按两类理解：
  - `docs/benchmarks/`、`docs/qe_inputs/`、`docs/patches/` 属于复现资产
  - 调研 / 架构 / overview 文档属于源记录与查证材料
- 本轮已经清掉明显低价值的占位稿、原始 chat export 与孤立参考附件，避免它们继续占据主仓库入口视野。

这份文档的目标，不是让后续工作替代原始文档，而是让整个 `docs/` 目录从“平铺的文档堆”变成“有主线的项目开发档案”，并把本文件稳定成主仓库里的 canonical long-form development record。
