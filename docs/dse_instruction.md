结论先说：**对 QE/VASP 这类平面波 DFT，最合适的 DSE 不是“直接把全流程搬到 FPGA/ASIC”，而是做“完整 SCF time-to-solution 驱动的、分层多保真、瓶颈引导、约束 Pareto 的软硬件联合设计空间探索”。** 也就是：先把 SCF 流程拆成 FFT/transpose、Hψ、非局域赝势投影、正交化/子空间对角化、charge density、mixing、通信与 I/O 等模块；再用低成本解析模型大范围搜索，用少量 HLS/RTL/FPGA 实测校准；最后在完整 QE/VASP 工作流上闭环验证能量、力、应力和收敛步数。

### 1. 近几年顶会顶刊工作的主线

硬件 DSE 的主流已经从“穷举 RTL/单点手调”转向 **architecture + mapping + memory hierarchy + software schedule 联合探索**。Timeloop/Accelergy 强调用可配置架构模型和 mapper 同时评估数据流与存储层次；MAESTRO 用解析模型快速估算 DNN 数据流的性能/能耗；ZigZag 进一步把算法、存储层次、mapping 统一到 memory-centric DSE；Gemmini 则是 DAC 2021 的 full-stack DNN accelerator generator，把 accelerator、SoC、软件栈一起纳入评估。([accelergy.mit.edu][1])

搜索算法方面，GAMMA 用遗传算法做 DNN accelerator mapping space exploration，ConfuciuX 用强化学习做硬件资源分配并用 GA 微调，AutoDSE 则是 FPGA/HLS 场景下的 bottleneck-guided coordinate optimization。这几类方法对你们有启发：**先用领域模型快速评分，再用少量真实实现校准，不要一开始就全量 HLS/RTL。**([ACM数字图书馆][2])

针对大模型/LLM 的近年 DAC/ICCAD 工作也很有参考价值。DAC 2024 的 KnownBO 是 spec-driven transformed Bayesian optimization，用于面向 LLM 任务的 RISC-V SoC 架构 DSE；ICCAD 2024 的 MCT-Explorer 针对上百维 LLM SoC 设计空间，用 MCTS 分析参数重要性并做多目标优化；ICCAD 2024 的 BinaryLLM 提出面向边缘 LLM accelerator 的 agile framework，并用 multi-fidelity representation 缓解后端准确数据不足的问题；ICCAD 2025 的 LLM-Augmented Multi-Modal Fusion for SoC DSE 把自然语言设计语义和 RTL 图结构结合，再用不确定性建模与贝叶斯优化提升小样本 DSE 效率。([lu0de.github.io][3])

与你们的 DFT 方向最直接相关的是 DAC 2025 的 **NDFT**：它针对 LR-TDDFT 提出 near-data DFT framework，核心判断是 DFT/TDDFT 里很多步骤本质上受数据搬运限制，因此用 CPU-NDP 异构系统做任务划分、调度和硬软协同，比单纯加速算术单元更关键。这个结论对平面波 QE/VASP 很重要：**FPGA/ASIC 的 DSE 首先要优化数据驻留、HBM/NoC/transpose/collective，而不是先追求峰值 FLOPS。**([arXiv][4])

### 2. DFT 和 LLM/DNN accelerator DSE 的关键差异

LLM accelerator 的核心多是 GEMM/attention/KV cache/quantization；平面波 DFT 的核心则是 **复数 FP64、3D FFT、全局 transpose/all-to-all、BLAS/LAPACK、正交化/对角化、SCF 迭代收敛**。QE 官方文档显示，QE 的并行层次包括 images、pools、bands、PW 并行，3D FFT 用于 G-space 和 real-space 之间变换，子空间对角化/正交化还需要独立的 linear-algebra group。([Quantum Espresso][5])

QE 的核心包 PWscf 本身就是用于 DFT 的 plane-wave self-consistent field，采用 plane-wave basis 和 pseudopotentials；现代 QE GPU 加速主要依赖 FFT、矩阵乘、OpenACC loop offload 等路径。VASP 官方也明确 OpenACC GPU port 是 NVIDIA GPU 的推荐方向，并且 VASP 构建时强依赖 FFT、BLAS、LAPACK、ScaLAPACK；官方还提醒普通 gaming GPU 不适合 VASP，因为 FP64 性能和 ECC/显存能力不足。([Quantum Espresso][6])

PWDFT-SW/TPDS 2025 这类大规模平面波 DFT 工作也说明，PW-DFT 的痛点是计算和内存双高，常规方法有接近 O(N³) 浮点开销和 O(N²) 内存足迹；FFT 带来的全局通信是平面波方法的重要瓶颈，优化里大量收益来自减少冗余数据、减少小消息、in-place/packing 数据转换，而不是只堆算力。

### 3. 我建议的 DSE 总策略

**最优策略应当是“SCF-loop aware + communication/memory first + multi-fidelity Bayesian/EA hybrid search”。**

第一层是 **workload characterization**。不要只测一个 Si bulk 或一个 Gamma-only case。至少构造 6 类 benchmark：小体系多 k 点、金属体系、绝缘体、slab/真空大 FFT grid、Gamma-only 大 supercell、hybrid functional/HSE 或 exact exchange。记录 `Npw`、FFT grid、`nbnd`、`nk`、`ecutwfc/ecutrho`、赝势类型、spin、diagonalization method、SCF 迭代数、通信量、HBM/DDR 访问量。

第二层是 **DFT kernel model**。建立如下形式的性能模型：

`T_scf = N_iter × (T_Hpsi + T_fft/transpose + T_projector + T_ortho + T_diag + T_density + T_mixing + T_comm + T_io)`

这里最重要的是把 `N_iter` 放进去。很多硬件设计只优化单 kernel，但 DFT 真正的 time-to-solution 还取决于 SCF 收敛步数。最近也有工作用 Bayesian optimization 调 charge mixing 参数来减少 VASP 的 SCF iterations，这说明软件参数本身也应纳入 DSE。([科学直达][7])

第三层是 **硬件架构空间分解**。建议不要先设计“DFT 专用大一统处理器”，而是定义几个可组合 block：

| 模块                                        | 优先级 | DSE 参数                                                                     |
| ----------------------------------------- | --: | -------------------------------------------------------------------------- |
| batched 1D/3D FFT + transpose engine      |  最高 | radix、pipeline 深度、HBM channel 数、tile size、in-place/out-of-place、twiddle 存储 |
| complex vector / pointwise engine         |   高 | FP64/FP32/mixed、SIMD width、fusion depth                                    |
| nonlocal pseudopotential projector engine |   高 | complex GEMM/GEMV 阵列规模、projector 数据布局、batching                             |
| reduction/dot/orthogonalization engine    |  中高 | tree reduction、Gram matrix buffer、host/device 分工                           |
| small/medium dense linear algebra         |   中 | 是否专用 systolic、是否调用外部 BLAS、矩阵尺寸门限                                           |
| data movement / DMA / collective engine   |  最高 | gather/scatter、G-vector layout、PCIe/CXL/NoC、HBM scratchpad 策略              |

第四层是 **搜索算法**。我会用以下组合，而不是单一 GA/RL/LLM：

1. **解析模型 + roofline/communication model** 做 10⁴–10⁶ 个点的粗筛。
2. **NSGA-II / CMA-ES / GA** 探索离散架构参数，例如 FFT engine 数、HBM channel 分配、buffer bank、radix 组合。
3. **多目标 Bayesian optimization/EHVI** 在小样本昂贵评估上找 Pareto front，目标包括 time/SCF、energy/SCF、area、power、HBM 容量、数值误差。
4. **bottleneck-guided coordinate optimization** 做局部 refinement：如果当前瓶颈是 transpose，就只动 NoC/HBM/tile；如果瓶颈是 orthogonalization，就动 reduction/GEMM/host-device 分工。
5. **multi-fidelity calibration**：解析模型 → HLS estimate → RTL/cycle sim → FPGA board measurement → ASIC PPA。BinaryLLM 和近期 SoC DSE 工作已经显示，多保真建模很适合这种后端真实数据稀缺的场景。([The Chinese University of Hong Kong][8])

LLM 可以辅助，但不要让 LLM 当真实性能 oracle。比较合理的用法是：根据 profiling 自动提出 DSE 参数、生成 HLS pragma、解释瓶颈、剪掉物理上无效的设计点、写实验脚本。真正评分必须来自解析模型、仿真或实测。

### 4. 对 FPGA/ASIC 架构的具体建议

**FPGA 原型阶段**：优先选 HBM FPGA，先做 QE 后端。QE 开源、模块边界更清楚，适合作为研究平台。先替换/外挂 FFT、pointwise、projector、batched GEMM、reduction 这些 kernel，不要一开始改完整 SCF 控制流。关键工程原则是让 wavefunction、potential、projector 尽量驻留在 FPGA/HBM 上，避免每个小 kernel 都 PCIe 往返。

**ASIC 阶段**：更适合做 “HBM + FFT/transpose fabric + complex MAC + near-memory reduction” 的 DFT tile/chiplet，而不是纯 systolic GEMM ASIC。LLM ASIC 的经验不能直接套，因为 DFT 的全局 FFT transpose、复数 FP64、正交化 collective 会让片上/片间网络和 HBM 带宽成为一等公民。DAC 2025 的 3D-CIMlet 等 transformer chiplet DSE 工作说明，2.5D/3D chiplet 与异构内存已经成为 accelerator DSE 的重要方向；对 DFT 来说，这个方向更应偏向 HBM/near-memory/transpose，而不是只做 CIM MAC。([engineering.purdue.edu][9])

**软件协同策略**：
第一，SCF 控制、收敛判断、输入解析、I/O 保持在 CPU；FFT/Hψ/projector/reduction 交给 FPGA/ASIC。第二，搜索 diagonalization method、band/k-point/PW parallelization、FFT task group、batch size、mixing 参数。QE 已经暴露多级并行参数，这些参数应和硬件资源一起探索。第三，混合精度只能“受控使用”：例如 inner residual、局部投影、预条件、初猜可以尝试 FP32/BF16/定点，但总能、力、应力、最终残差必须用 FP64 或迭代 refinement 校验；VASP 官方对 FP64 能力的提醒也说明，材料模拟不能像 LLM 那样激进量化。([Quantum Espresso][5])

### 5. 一个可执行的研究路线

**第 0 阶段：profiling 基线。** 用 QE/PWscf 跑 6–10 个代表性 case，采集每个 SCF step 的 FFT、Hψ、ortho、diag、density、mixing、MPI/all-to-all、I/O 时间。类似 QE profiling dataset 的思路，先找出不同体系和并行参数下的真实瓶颈。([科学直达][10])

**第 1 阶段：DFT-DSE 中间表示。** 定义一个 workload descriptor：

`{Npw, FFT_grid, nbnd, nk, nspin, pseudopotential_type, diagonalization, precision, parallel_layout, SCF_iter}`

再定义 hardware descriptor：

`{FFT_tiles, GEMM_tiles, vector_lanes, HBM_channels, scratchpad_size, NoC_bw, DMA_policy, precision_modes}`

这样才能像 Timeloop/ZigZag 对 DNN 做 architecture-mapping DSE 那样，对 DFT 做 architecture-algorithm-layout DSE。

**第 2 阶段：先做 Hψ/FFT fusion。** 最值得优先验证的是：

`G-space wavefunction → inverse FFT → V_loc(r) pointwise multiply → forward FFT → add kinetic/nonlocal terms`

这个链条是平面波 DFT 的高频路径，适合 streaming/dataflow。重点不是单独 FFT 多快，而是中间数据是否能少落 DDR/HBM、少过 PCIe、少做 layout conversion。

**第 3 阶段：把 nonlocal projector 和 reduction 加进去。** 这里要探索 dense/sparse projector layout、batching、complex GEMM 阵列规模、reduction tree。很多体系下 projector 和正交化会和 FFT 竞争 HBM 带宽。

**第 4 阶段：完整 SCF 闭环。** 最终评价必须是：总 wall time、energy-to-solution、SCF 迭代数、能量误差、力误差、应力误差、不同体系泛化能力。只报告 kernel speedup 没有说服力。

### 6. 关键判断

我认为你们最有机会做出贡献的点不是“又一个 FPGA FFT”，而是：

**面向平面波 DFT 的 DSE 框架 + 硬件/软件/并行策略联合搜索 + HBM/transpose/FFT/projector 的原型验证。**

一句话方案是：

> 以 QE 为开源验证平台，建立 SCF-loop aware 的解析/多保真 DSE；以 HBM-FPGA 验证 FFT-Hψ-projector-reduction 数据流；以 ASIC 方向探索 HBM/near-memory/transpose-aware DFT tile；用 Bayesian/EA/MCTS 做多目标 Pareto 搜索，用 LLM 只做知识注入和实验自动化，不做性能判定。

这样做最符合近几年 DAC/ICCAD 的趋势，也最符合平面波 DFT 的真实瓶颈。

[1]: https://accelergy.mit.edu/timeloop.pdf?utm_source=chatgpt.com "Timeloop: A Systematic Approach to DNN Accelerator Evaluation"
[2]: https://dl.acm.org/doi/epdf/10.1145/3400302.3415639?utm_source=chatgpt.com "GAMMA: Automating the HW Mapping of DNN Models on Accelerators via ..."
[3]: https://lu0de.github.io/ "Donger Luo (骆东迩) - Ph.D. Student | Electronic Design Automation"
[4]: https://arxiv.org/html/2504.03451v1?utm_source=chatgpt.com "NDFT: Accelerating Density Functional Theory Calculations via Hardware ..."
[5]: https://quantum-espresso.org/Doc/user_guide/node20.html "3.3 Parallelization levels"
[6]: https://www.quantum-espresso.org/documentation/ "Documentation for quantum espresso"
[7]: https://www.sciencedirect.com/science/article/pii/S2352214325000115 "Simple approach to more efficient density functional theory simulations - ScienceDirect"
[8]: https://research.cuhk.edu.hk/en/publications/an-agile-framework-for-efficient-llm-accelerator-development-and-/ "
        An Agile Framework for Efficient LLM Accelerator Development and Model Inference
      \-  The Chinese University of Hong Kong"
[9]: https://engineering.purdue.edu/NanoX/assets/pdf/2025_DAC_3D-CIMlet_AAM.pdf?utm_source=chatgpt.com "3D-CIMlet: A Chiplet Co-Design Framework for Heterogeneous In-Memory ..."
[10]: https://www.sciencedirect.com/science/article/pii/S2352340923006996 "Performance and profiling data of plane-wave calculations in quantum ESPRESSO simulation on three supercomputing centres - ScienceDirect"
