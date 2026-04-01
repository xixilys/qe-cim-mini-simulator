# DFT 加速行业热点调研报告（2023-01 至 2026-03-22）

## 0. 摘要

这份报告不以本地项目为出发点，而是从近三年的开源代码、商用软件、硬件厂商动向和代表性论文出发，回答四个问题：

1. 现在 DFT 加速的热点主要集中在哪里；
2. 各方向在做什么，做到什么成熟度；
3. 哪些方向最火、最成熟、最好做；
4. 如果从宏观层面选择任务，应该优先把人力投向哪几类问题。

先给结论：

- **最成熟的主线**不是“重新发明 DFT”，而是**把已有生产代码持续 GPU 化**，并把 `FFT / 稠密线代 / 特征值求解 / exact exchange / projector` 这些核心瓶颈拆成更可维护、可移植的库层。
- **最稳的工程抓手**是**库化与求解器基础设施**：`ELPA`、`ELSI`、`SIRIUS`、`DLA-Future`、`MAGMA/cuSOLVERMp` 这类东西虽然论文热度不如“新芯片”或“端到端 AI”，但是真正进入主流软件栈的恰恰是它们。
- **最热的算法方向**是三类：`GPU 化的 Hamiltonian application / FFT / projector`，`hybrid DFT / exact exchange`，以及 `ML 用于缩短 SCF`。
- **最有行业成熟度的硬件方向**依然是 `NVIDIA GPU` 主导，`AMD GPU` 明显升温，`Intel GPU` 仍在进入期；`FPGA / ASIC / PIM / CIM` 在 DFT 这一具体赛道上仍主要停留在原型和论文探索。
- **ML 方向很热，但要分清两件事**：一类是在“加速传统 DFT 的 SCF 收敛”，另一类是在“用 ML potential 或 learned XC 旁路/替代部分 DFT 工作流”。后者产业热度很高，但它不等于“把 KS-DFT 主循环本身加速了”。
- 如果只问“现在行业最认、最好落地的主战场是什么”，答案是：**GPU 化生产代码 + solver/FFT/线代基础设施重构**。

## 1. 范围、方法与评价口径

### 1.1 范围

- 时间窗口：**2023-01 至 2026-03-22**
- 主对象：**Kohn-Sham DFT 主线**
- 纳入对象：
  - 开源生产代码
  - 商业电子结构软件
  - 基础求解器与线代/FFT 基础设施
  - ML 加速与工作流替代方向
  - 前沿硬件探索
- 不作为主线展开：
  - `TDDFT / GW / BSE`，除非它们明显影响主流加速版图
  - 纯材料 AI 工作流，除非其作用是替代或旁路 DFT

### 1.2 三条评价轴

下文的“热度 / 成熟度 / 可做性”是基于官方文档、近期发布状态和代表性论文做的**综合判断**，属于推断，不是单一来源的原话。

- `热度`
  - 看近三年的官方功能推进、发布节奏、论文密度、厂商参与度
- `成熟度`
  - 看是否进入官方主线、是否可复现、是否已有真实用户群和工程路径
- `可做性`
  - 看进入门槛、依赖生态、是否可复用现有库、工程闭环是否清楚

### 1.3 一个重要观察

如果把行业视角压缩成一句话：

> 近三年 DFT 加速的行业重心，不在“发明一个全新的 DFT 计算范式”，而在“让已有主流代码和关键瓶颈在 GPU 与异构平台上持续跑得更快、更稳、更可移植”。

## 2. DFT 加速版图：现在的热点都在哪

### 2.1 四层版图

| 层 | 当前热点 | 典型问题 | 当前行业状态 |
| --- | --- | --- | --- |
| 软件层 | 生产代码 GPU 化、性能可移植、模块化重构 | 老代码难移植，CUDA-only 维护成本高，AMD/Intel 兼容性不足 | **主流成熟** |
| 算法层 | eigensolver、FFT、projector、exact exchange、低标度解法 | 稠密对角化贵、Fock exchange 贵、数据搬运重 | **主流成熟 + 局部升温** |
| 硬件层 | NVIDIA/AMD/Intel GPU；库与通信栈协同优化 | 如何把求解器、FFT、稠密线代真正吃满 GPU | **主战场明确** |
| ML 层 | SCF 初猜、density/Hamiltonian 预测、learned XC、ML potential | 缩短 SCF、绕开部分 DFT 工作流 | **快速升温，但分化明显** |

### 2.2 宏观结论

- **软件层的热点最清楚**：`QE`、`VASP`、`CP2K`、`ABINIT`、`PySCF/GPU4PySCF`、`Q-Chem/BrianQC`、`TeraChem` 都在不同程度推进 GPU 或异构支持。
- **算法层的热点非常集中**：真正反复被投入资源的还是 `eigensolver`、`FFT`、`projector/nonlocal operator`、`exact exchange`、`稠密/稀疏 contraction`。
- **硬件层几乎一边倒**：产业级、生产级投入仍主要在 GPU；专用硬件在 DFT 赛道的公开成熟案例很少。
- **ML 层很热，但目标不一致**：有的是要“更快收敛到同一个 DFT 解”，有的是要“直接用 ML 逼近 DFT 输出”，后者产业价值高，但研究问题已经不是同一个。

## 3. 软件生态地图：谁在做什么

下表按“代码家族”而不是按论文组织。证据列里每项都给出至少一个官方来源和一个代表性论文或实现来源。

| 类别 | 项目 | 主要在加速什么 | 主要做法 | 当前判断 | 主要限制 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 平面波主流 | Quantum ESPRESSO | `pw.x`、phonon、部分 GPU 路径 | OpenACC/OpenMP 逐步迁移，7.2 明确写到面向 AMD/Intel 的 OpenMP GPU 起步 | **主流成熟，但演进式** | 历史包袱重，GPU 化不是“一次性重写” | [官方发布](https://www.quantum-espresso.org/release-notes/release-notes-QE7-2.html) [官方概览](https://www.quantum-espresso.org/quantum-espresso-7-2/) |
| 平面波主流 | VASP | blocked-Davidson、RMM-DIIS、Fock exchange 等 | 官方主推 OpenACC GPU port；CUDA-C 老路径已弃用 | **主流成熟** | 对 NVIDIA 生态依赖强，部分功能如 RPA/GW 仍在推进 | [官方 Wiki](https://www.vasp.at/wiki/OpenACC_GPU_port_of_VASP) [编译选项](https://vasp.at/wiki/Precompiler_options) |
| 平面波/混合基 | CP2K | GPW/GAPW、线性标度 SCF、plane-wave DFT、MP2/RPA、对角化 | 明确按库层拆分：`DBCSR`、`grid`、`SIRIUS`、`ELPA`、`DLA-Future`、`SpFFT` 等分别上 GPU，且同时支持 CUDA/HIP | **主流成熟，且最像未来形态** | 体系复杂，学习曲线高；不是单内核优化能解决 | [官方 GPU 状态页](https://www.cp2k.org/gpu) [CUDA 文档](https://manual.cp2k.org/trunk/technologies/accelerators/cuda.html) [DLA-Future](https://manual.cp2k.org/trunk/technologies/eigensolvers/dlaf.html) |
| 平面波主流 | ABINIT | ground-state DFT、迭代 eigensolver | 2024 起新 GPU 路线以 OpenMP offload 为主，同时保留 Kokkos+CUDA/YAKL 路线 | **快速升温，但仍偏实验** | 官方文档明确写明 GPU 支持“高度实验性” | [官方 GPU 文档](https://docs.abinit.org/INSTALL_gpu/) [并行变量](https://docs.abinit.org/variables/paral/) |
| Python/开放生态 | PySCF + GPU4PySCF | HF/DFT、梯度、Hessian、QM/MM、张量 contraction | 以 Python 生态为中心，ERI CUDA kernel + CuPy/cuTENSOR + 线代组合 | **快速升温，开源影响力很强** | 目前仍高度绑定 NVIDIA；大系统内存与分布式问题仍在推进 | [官方仓库](https://github.com/pyscf/gpu4pyscf) [JPCA 2024](https://pubs.acs.org/doi/10.1021/acs.jpca.4c05876) |
| 商业量化化学 | Q-Chem + BrianQC | HF/DFT 的 `J/K/XC` 与导数 | BrianQC 作为 GPU 模块接入 Q-Chem，强调 mixed precision 但维持双精度精度目标 | **主流成熟** | 闭源/商用路径，研究可见度弱于开源生态 | [Q-Chem 官方](https://www.q-chem.com/explore/performance/brianqc/) [BrianQC 官方](https://www.brianqc.com/) |
| 商业量化化学 | TeraChem | 分子量化化学、HF/DFT、hybrid、AIMD | 从一开始就面向 GPU 设计；2024 开始把周期体系 hybrid DFT 也推上单 GPU/多 GPU | **主流成熟，且以“GPU 原生”见长** | 更偏分子量化化学，和主流平面波材料 DFT 生态并不相同 | [官方主页](https://petachem.com/) [周期 hybrid DFT 论文](https://arxiv.org/abs/2410.22278) |
| 实空间/PAW | GPAW | PW / FD / LCAO，多种离散化下的 DFT | 维护 GPU 文档和 CuPy 路径，持续演进 Python 化 DFT | **成熟度中等** | 在大规模生产材料 DFT 里的行业主导性不如 VASP/QE/CP2K | [官方主页](https://gpaw.readthedocs.io/) [GPU 文档](https://gpaw.readthedocs.io/documentation/gpu.html) |
| 实空间 | Octopus | 实空间 DFT/TDDFT，多 GPU 运行 | 官方维护 GPU tutorial、GPU Docker image、CUDA/OpenCL 相关路径 | **成熟度中等** | 更偏专门用户群，主战场不是常规平面波材料生产流 | [GPU 教程](https://www.octopus-code.org/documentation/main/tutorial/hpc/gpu/) [GPU 镜像](https://octopus-code.org/documentation/16/manual/docker_images/) |
| 有限元/替代离散化 | DFT-FE | 大规模 KS-DFT，稀疏/局部 operator application，CheFSI | 自适应有限元 + Chebyshev filtered subspace iteration + 近年的 matrix-free 算法与 CPU-GPU 异构扩展 | **快速升温，差异化很强** | 生态和用户群小于平面波主流代码 | [官方仓库](https://github.com/dftfeDevelopers/dftfe) [2025 matrix-free 论文](https://arxiv.org/abs/2512.08571) |
| 基础设施 | ELPA | 对称/Hermitian 稠密特征值问题 | 高效直接 eigensolver，官方用户手册明确支持 GPU 路径 | **主流成熟** | 它是基础设施，不直接解决完整 DFT 数据流问题 | [官方介绍](https://elpa.mpcdf.mpg.de/ABOUT_ELPA.html) [用户手册](https://elpa.mpcdf.mpg.de/documentation/userguide/ELPA_USERGUIDE.html) |
| 基础设施 | ELSI | Kohn-Sham solver 接口层 | 把 `ELPA`、`PEXSI`、`libOMM`、`MAGMA`、`NTPoly` 等统一到一个接口里 | **主流成熟** | 更像“整合层”，不是单点性能魔法 | [官方主页](https://wordpress.elsi-interchange.org/) [用户手册](https://wordpress.elsi-interchange.org/wp-content/uploads/2022/04/elsi-manual-2.9.0.pdf) |
| 低标度/绕开对角化 | PEXSI | 通过 pole expansion + selected inversion 绕开显式对角化 | 面向大规模 KS-DFT 的替代解法，复杂度低于传统 O(N^3) | **成熟度中等，应用面有门槛** | 更适合特定矩阵结构与代码路径，不是通用替换件 | [ELSI 中的 PEXSI](https://wordpress.elsi-interchange.org/) [PEXSI 论文](https://arxiv.org/abs/1708.04323) [原始方法论文](https://arxiv.org/abs/1202.2159) |
| 基础设施/plane-wave 库 | SIRIUS | plane-wave DFT building blocks、GPU 加速 | 把 plane-wave DFT building blocks 库化，并作为 QE/CP2K 等的 GPU 加速后端 | **成熟度中等偏高** | 更适合作为库接入，不是所有代码都愿意重构到这个形态 | [官方仓库](https://github.com/electronic-structure/SIRIUS) |
| 新兴开源 GPU 套件 | ByteQC | mean-field DFT、PBC、MP2、CC、embedding | 直接把大规模量化化学栈搬到现代 GPU 上，2025 年开源 | **快速升温** | 生态仍在形成，生产级广泛 adoption 还需要时间 | [官方仓库](https://github.com/bytedance/byteqc) [2025 论文](https://arxiv.org/abs/2502.17963) |

### 3.1 从软件生态里能看出的五个趋势

1. **GPU 化不是单一代码级优化，而是库化重构**
   - `CP2K` 是最典型样本：不是只说“把某个 kernel 写成 CUDA”，而是把 `DBCSR`、`grid`、`SIRIUS`、`ELPA`、`DLA-Future` 这种层次拆开分别推进。
2. **性能可移植正在取代“只做 NVIDIA 特化”**
   - `QE` 的 OpenMP 路线、`ABINIT` 的 OpenMP offload、`CP2K` 的 CUDA/HIP 双栈都说明社区已经在为 AMD/Intel 做准备。
3. **商业软件更务实**
   - `VASP`、`Q-Chem/BrianQC`、`TeraChem` 都非常明确地围绕用户最常用、最值钱的方法学做 GPU 化，而不是追求“所有功能一次覆盖”。
4. **Python 生态在快速抬升**
   - `GPU4PySCF` 的意义不只在速度，还在于它把 GPU 量化化学和 ML/自动化工作流放进了同一个生态。
5. **另起炉灶的替代离散化确实存在，但还不是行业主路**
   - `DFT-FE`、`Octopus`、`GPAW` 都有很强技术内容，但就“行业主战场”而言，影响力仍不如主流平面波/量化化学代码。

### 3.2 各主流方向的代表论文抓手

对老牌生产代码来说，近年的 GPU/异构推进经常先体现在 `release notes`、`wiki`、`user guide` 和代码提交里，而不是每个版本都配一篇独立学术论文。因此下面这组文献更适合作为“方向抓手”，而不是“每个项目唯一对应的一篇论文”。

- `平面波主流`
  - [An alternative GPU acceleration for a pseudopotential plane-waves density functional theory code (2024)](https://arxiv.org/abs/2412.01695)
  - [VASP on a GPU: application to exact-exchange calculations of the stability of elemental boron (2011, 作为 VASP GPU 路线的基础背景)](https://arxiv.org/abs/1111.0716)
- `Python/开放生态`
  - [Introducing GPU Acceleration into the Python-Based Simulations of Chemistry Framework (GPU4PySCF, 2024)](https://pubs.acs.org/doi/10.1021/acs.jpca.4c05876)
- `实空间/有限元`
  - [Matrix-free algorithms for fast ab initio calculations on distributed CPU architectures using finite-element discretization (DFT-FE, 2025)](https://arxiv.org/abs/2512.08571)
  - [Graphics Processing Unit acceleration of the Random Phase Approximation in the projector augmented wave method (GPAW, 2013, 作为早期 GPU 背景)](https://arxiv.org/abs/1307.8052)
- `求解器与基础设施`
  - [ELSI: A Unified Software Interface for Kohn-Sham Electronic Structure Solvers](https://arxiv.org/abs/1705.11191)
  - [Robust Determination of the Chemical Potential in the PEXSI Method](https://arxiv.org/abs/1708.04323)

## 4. 算法热点：大家在反复投入什么

### 4.1 热点总表

| 热点 | 为什么热 | 典型载体 | 现在主流在做什么 | 判断 |
| --- | --- | --- | --- | --- |
| 生产代码 GPU 化 | 这是最直接、最可见的性能收益来源 | `VASP`、`QE`、`CP2K`、`GPU4PySCF`、`TeraChem` | 迁移关键内核、减少 CPU/GPU 往返、重构并行模型 | **主流成熟** |
| eigensolver 与 solver 基础设施 | SCF 内部总会碰到本征问题；传统稠密对角化成本高 | `ELPA`、`ELSI`、`DLA-Future`、`SIRIUS`、`ABINIT` | 直接稠密 solver 优化、GPU solver、统一接口、迭代 solver | **主流成熟** |
| Hamiltonian application / projector / FFT | 真实时间常常更花在反复应用算子而不是“最后一次对角化” | `CP2K grid`、`SIRIUS`、`VASP`、`QE`、`Octopus`、`DFT-FE` | 优化 FFT、非局域 projector、稀疏/稠密 contraction、数据布局 | **主流成熟** |
| Hybrid DFT / exact exchange | `Fock exchange` 是普遍公认的高成本热点 | `VASP`、`CP2K`、`Q-Chem`、`TeraChem`、`GPU4PySCF` | GPU 化 Fock build、RI/LRI、screening、分布式实现 | **快速升温** |
| 低标度与绕开对角化 | 大系统上 O(N^3) 本征求解不可持续 | `PEXSI`、`libOMM`、`NTPoly`、有限元/实空间路线 | 密度矩阵法、FOE、selected inversion、orbital minimization | **成熟度中等** |
| 混合精度与容错迭代 | GPU 性能与带宽优势常常要靠低精度释放 | `BrianQC`、`GPU4PySCF`、`DFT-FE`、各类 solver 库 | 在不破坏收敛的前提下把部分 contraction / operator 迁到较低精度 | **快速升温** |
| ML-SCF 初猜 | 直接减少 SCF 步数，收益非常直观 | `NeuralSCF`、density/Hamiltonian prediction | 学习 density map、density matrix、Hamiltonian 或初猜密度 | **快速升温** |
| ML 替代 DFT 工作流 | 高通量、AIMD、筛选任务中收益极大 | `DeePMD-kit`、foundation potentials、learned XC | 用 ML potential/functional 替代大部分重复 DFT 调用 | **产业很热，但不等于直接加速 KS-DFT** |
| FPGA / ASIC / PIM / CIM | 论文吸引力强，能讲能效与数据流 | 零散原型、专用加速器论文 | 试图把 Hamiltonian、对角化或相关子核固化到硬件 | **仍偏探索** |

### 4.2 SCF 与本征求解

这是最老、也是最稳定的热点之一。原因很简单：无论是平面波、Gaussian、实空间还是有限元，最终都绕不开以下两件事：

- 反复应用 Hamiltonian 或相关算子；
- 在子空间或全空间上解本征问题，或用别的方法绕过本征问题。

现在的行业做法大致分两类：

- **继续把直接稠密或块迭代 solver 做快**
  - `ELPA`、`DLA-Future`、`MAGMA/cuSOLVERMp`、`ABINIT` 的 `LOBPCG/Chebyshev` 路线都是这一类。
- **干脆绕过显式对角化**
  - `PEXSI`、`libOMM`、`NTPoly`、一部分有限元和实空间路线属于这一类。

判断：

- 这条线**很成熟**，因为它已经深度进入主流代码和基础设施。
- 但它也**不容易只靠一个“新想法”打穿**，往往要和矩阵结构、离散化方式、并行栈一起协同。

### 4.3 Hamiltonian application、projector、FFT、数据搬运

从行业实际投入看，这一块往往比“最后的对角化器”更像主时间黑洞。

原因：

- KS-DFT 的 SCF 循环本来就是“反复应用算子”；
- FFT、projector/nonlocal term、稠密与稀疏 contraction、gather/scatter 这些操作的数据搬运成本很重；
- 它们更容易受到 GPU 内存层次、通信和数据布局的影响。

这也是为什么：

- `CP2K` 把 `grid`、`PW`、`DBCSR`、`DBM` 拆开推进；
- `SIRIUS` 把 plane-wave DFT 的 building blocks 库化；
- `DFT-FE` 在 2025 年还专门继续往 `matrix-free operator application` 上发力。

判断：

- 这是**最值得认真看的“真实热点”**之一；
- 它往往比“单个 eigensolver 创新”更贴近端到端 wall-time。

### 4.4 Hybrid DFT 与 exact exchange

这一块这几年明显更热。

原因：

- 产业和材料/催化应用里，对 hybrid functional 的需求一直在上升；
- 但 `Fock exchange` 极贵，经常成为阻碍 hybrid DFT 普及的关键成本项；
- GPU 特别适合吃一部分积分、tensor contraction 和 screening 后的高算强比任务。

行业代表：

- `VASP` 官方 GPU 路线一直把 hybrid functionals 列为关键场景；
- `Q-Chem/BrianQC` 明确强调 `J/K/XC` 与导数的 GPU 加速；
- `GPU4PySCF`、`TeraChem`、`ByteQC` 都在把 hybrid/mean-field 推上现代 GPU；
- `CP2K` 的 GPU 状态页里也明确把 `HFX` 和相关库列为重点方向。

判断：

- **很热，也很值钱**；
- 但它通常比“普通 semilocal DFT GPU 化”更难，需要算法与实现双重功力。

### 4.5 低标度与绕开对角化

这是一个“成熟度不如 GPU 化主线，但很有差异化”的方向。

代表问题：

- 大体系上 O(N^3) 的 dense diagonalization 不可持续；
- 稀疏矩阵、局域基组、弱相互作用体系下可能有更低标度路径。

代表路线：

- `PEXSI`
- `libOMM`
- `NTPoly`
- 一些实空间/有限元路径上的 `Chebyshev filtering`

判断：

- 这是一个**很适合做差异化研究**的方向；
- 但它通常**不是“最好上手”的工程入口**，因为对矩阵结构、体系类别和代码路径都有要求。

### 4.6 混合精度与容错迭代

这条线的重要性在上升，但多数工作还不是把“低精度本身”当卖点，而是把它当加速手段。

行业趋势：

- 商业工具如 `BrianQC` 已经公开强调 mixed precision，同时追求双精度精度目标；
- `GPU4PySCF` 和若干新论文也把 tensor contraction、积分、JIT kernel、GPU 内核调度与数值稳定性一起考虑；
- `DFT-FE` 2025 的 matrix-free 论文明确提到混合精度 intrinsics。

判断：

- 这是**非常现实**的工程热点；
- 但它通常不是单独成立的研究方向，而是和 solver、operator、GPU kernel 设计绑定在一起。

## 5. ML 加速：很热，但要分清它在替代什么

### 5.1 ML 加速的四个子方向

| 子方向 | 代表工作 | 它到底在做什么 | 判断 |
| --- | --- | --- | --- |
| SCF 初猜 / density map 学习 | [NeuralSCF](https://arxiv.org/abs/2406.15873)、[Towards A Universally Transferable Acceleration Method for DFT](https://arxiv.org/abs/2509.25724)、[Predicting the One-Particle Density Matrix](https://arxiv.org/abs/2401.06533) | 减少 SCF 迭代数，让传统 KS-DFT 更快收敛 | **快速升温** |
| 直接学习 Hamiltonian / density matrix | density-matrix / Hamiltonian prediction 一类论文 | 把更难的中间量学出来，帮助构造更优初猜 | **快速升温，但泛化难** |
| learned XC / ML functional | [Skala](https://github.com/microsoft/skala)、[NeuralXC](https://github.com/semodi/neuralxc) | 不再只加速 SCF，而是直接改写 functional 近似 | **仍偏探索** |
| ML potential 旁路 DFT 工作流 | [DeePMD-kit](https://github.com/deepmodeling/deepmd-kit) | 在高通量/AIMD 中用 ML 势大量替代 DFT 调用 | **产业很热，但不是直接加速 KS 主循环** |

### 5.2 这条线为什么会热

因为它回答了 GPU/HPC 路线不容易回答的问题：

- 不是把每一步都跑快一点，而是**直接少做几步**；
- 在高通量筛选、结构优化、AIMD 这种长工作流里，少一次 SCF、少一次 DFT 调用就很值钱；
- 和 Python/自动化/材料 AI 平台更容易结合。

### 5.3 但 ML 加速有两个根本限制

1. **可迁移性仍是核心难点**
   - 体系、基组、泛函、化学空间一变，模型经常退化。
2. **“加速 DFT”与“替代 DFT”不是同一件事**
   - `NeuralSCF` 更接近前者；
   - `DeePMD-kit` 这类 ML potential 更接近后者。

### 5.4 对任务选择的含义

- 如果团队偏 `ML + 数据`，`SCF 初猜 / density map` 是最自然的切入点；
- 如果团队偏 `HPC + 生产代码`，ML 不是最稳的第一落点；
- 如果目标是产业影响，**ML potential/工作流替代**的热度可能比“直接加速 KS-DFT”还高，但那已经是另一条赛道。

## 6. 硬件层：主战场与前沿探索

### 6.1 主战场：GPU 已经没有悬念

从官方支持状态看：

- `NVIDIA GPU` 仍是主战场；
- `AMD GPU` 正在快速进入，尤其是通过 `HIP`、`OpenMP offload`、性能可移植库；
- `Intel GPU` 也在进入，但整体存在感还明显弱于前两者。

这不是因为其他硬件不值得做，而是因为：

- DFT 代码栈庞大，真实应用需要完整软件生态；
- 稠密线代、FFT、通信、调试、性能分析、运维，全都已经围绕 GPU 形成了成熟基础设施；
- 这让 GPU 路线具备**极强的路径依赖**。

### 6.2 配套基础设施：真正支撑行业演进的是这些库

如果只盯着“哪个 DFT 代码支持 GPU”，容易看漏真正重要的层：

- `ELPA`
- `ELSI`
- `MAGMA`
- `cuSOLVERMp`
- `DLA-Future`
- `SIRIUS`
- `SpFFT`
- `DBCSR`

真正的行业趋势不是“每个代码各写一套 GPU 内核”，而是：

> 把最关键的线代、求解器、FFT、稀疏/块稀疏数据结构做成可复用基础设施，再让上层代码拼起来。

### 6.3 前沿探索：FPGA / ASIC / PIM / CIM 现在处于什么位置

就 DFT 这条具体赛道而言，公开可复核证据显示：

- **生产级主流软件并没有把专用硬件作为当前主战场**；
- 公开论文型成果相对少；
- 到 2026 年 2 月，仍然能把“首次 hardware-native 的 semi-empirical electronic structure FPGA 实现”当成论文亮点，这本身就说明该方向仍然很早期。

一个很有代表性的例子是 2026 年的 FPGA 论文：

- [A Hardware-Native Realisation of Semi-Empirical Electronic Structure Theory on FPGAs](https://arxiv.org/abs/2602.11702)

它实现的是 `EHT/DFTB0`，而不是完整的生产级 KS-DFT 主线。它的重要意义是：

- 证明“硬件原生电子结构求解”可以做；
- 但也反过来说明：**连 semi-empirical/DFTB 级别都还处于 proof-of-principle，离主流 KS-DFT 的行业成熟度还很远**。

### 6.4 硬件层判断

| 方向 | 热度 | 成熟度 | 可做性 | 判断 |
| --- | --- | --- | --- | --- |
| NVIDIA/AMD GPU 上的软件栈加速 | 高 | 高 | 高 | **主战场** |
| 求解器/FFT/线代库层协同优化 | 中高 | 高 | 中高 | **最稳的长期价值** |
| 统一内存/性能可移植 GPU 编程 | 中高 | 中 | 中 | **未来 3-5 年重要** |
| FPGA/ASIC/PIM/CIM 做 DFT 子核 | 中 | 低 | 低到中 | **论文感强，但工程成熟度低** |

## 7. 哪些方向最火、最成熟、最好做

### 7.1 最火

如果只看近三年的社区热度和产业动向，最火的大致是：

1. **GPU 化生产代码**
2. **Hybrid DFT / exact exchange**
3. **ML-SCF 与 ML 工作流替代**

原因：

- 这三类都直接对应真实 wall-time 或真实业务价值；
- 都有持续的官方推进或高密度论文输出。

### 7.2 最成熟

最成熟的不是最“新颖”的，而是：

1. **GPU 化已有生产代码**
2. **solver / FFT / 稠密线代 / 接口基础设施**
3. **商业量化化学 GPU 套件**

判断依据：

- 都已经有官方支持路径；
- 已经存在真实用户和运行手册；
- 不是“能不能做”，而是“怎么做得更好”。

### 7.3 最好做

这里必须分团队类型。

#### 对 HPC / 系统团队

最好做的顺序通常是：

1. **库级加速与单类瓶颈内核加速**
2. **solver infrastructure / 接口层**
3. **某个真实软件中的 GPU/异构移植子模块**

因为它们：

- 问题边界清楚；
- 验证指标明确；
- 更容易复用现有生态。

#### 对 ML 团队

最好做的顺序通常是：

1. **SCF 初猜 / density map**
2. **density matrix / Hamiltonian prediction**
3. **工作流层 ML 替代**

因为它们：

- 数据和模型设计空间大；
- paper 产出节奏快；
- 但要接受泛化风险。

### 7.4 最难但论文感很强

- **专用硬件做 DFT 主核**
- **完整低标度替代路线进入生产代码**
- **端到端 learned XC / learned KS**

这几类方向往往最容易讲“新”，但也最容易卡在：

- 生态不成熟；
- 与主流软件脱节；
- benchmark 不容易被行业接受。

## 8. 任务落点矩阵：如果现在要选方向，应该怎么放

### 8.1 总表

| 任务类型 | 热度 | 成熟度 | 入场门槛 | 主要玩家 | 更适合跟进还是突破 |
| --- | --- | --- | --- | --- | --- |
| GPU 化生产代码中的核心内核/库 | 高 | 高 | 中 | `VASP`、`QE`、`CP2K`、`PySCF`、`TeraChem` | **跟进型工作最好做** |
| solver infrastructure / eigensolver / 接口层 | 中高 | 高 | 中高 | `ELPA`、`ELSI`、`SIRIUS`、`DLA-Future` | **跟进与局部突破都可做** |
| Hybrid DFT / exact exchange 加速 | 高 | 中高 | 高 | `VASP`、`Q-Chem`、`CP2K`、`GPU4PySCF`、`TeraChem` | **高价值，但竞争激烈** |
| 低标度 / 绕开对角化 | 中 | 中 | 高 | `PEXSI`、`libOMM`、实空间/有限元团队 | **适合差异化突破** |
| ML-SCF / density-map 加速 | 高 | 中低 | 中 | `NeuralSCF`、学术 ML 团队 | **适合快速做出新故事** |
| ML potential 替代工作流 | 很高 | 中高 | 中 | `DeePMD`、foundation potentials 团队 | **更偏新赛道，不是直接 DFT kernel 加速** |
| FPGA / ASIC / PIM / CIM 做 DFT 子核 | 中 | 低 | 很高 | 零散原型团队 | **突破感强，但风险最高** |

### 8.2 五类最值得考虑的任务落点

#### 任务 1：跟随主流软件的 GPU 化与性能可移植

适合目标：

- 想快速对齐行业主流；
- 想做能被同行立即理解的成果；
- 想要强工程复用。

为什么值得做：

- 这是最成熟的行业主战场；
- 直接连接真实用户和真实 workload；
- 最容易产生“可复现 benchmark + 可上线代码”。

#### 任务 2：做 solver / FFT / 线代 / 接口基础设施

适合目标：

- 不想和每个大软件绑死；
- 想做更“平台型”的贡献；
- 想在多个 DFT 代码之间复用成果。

为什么值得做：

- 这类工作虽然不一定最炫，但行业价值很高；
- 进入主流软件栈的概率往往高于“新硬件”或“新范式”。

#### 任务 3：攻 hybrid DFT / exact exchange

适合目标：

- 想做高价值热点；
- 团队既懂算法也懂实现。

为什么值得做：

- 这是最真实的成本痛点之一；
- 用户愿意为这类加速买单；
- 论文和软件贡献都容易成立。

#### 任务 4：做 ML-SCF / density-map 加速

适合目标：

- 团队有 ML 能力；
- 想快速切入热点；
- 可以接受泛化和 benchmark 设计上的研究风险。

为什么值得做：

- 这条线很热；
- 直接对准“减少 SCF 步数”这个清晰目标；
- 比“端到端 learned DFT”更容易落地。

#### 任务 5：做专用硬件上的 DFT 子核或数据流 primitive

适合目标：

- 明确追求差异化；
- 能接受长周期、高风险；
- 不把短期成熟度作为主要目标。

为什么值得做：

- 行业里公开成熟案例少，因而差异化空间大；
- 但要明确：这不是主流成熟方向，而是**前沿探索方向**。

## 9. 建议排序：如果只能选 3 类任务

如果目标是**对齐行业主流、容易被接受、容易形成可交付结果**，推荐排序：

1. **GPU 化生产代码中的核心内核/库**
2. **solver infrastructure / eigensolver / FFT / 线代层**
3. **hybrid DFT / exact exchange**

如果目标是**更强的新颖性，但还想和真实 DFT 保持联系**，推荐排序：

1. **solver infrastructure + 新算法结合**
2. **ML-SCF / density-map**
3. **低标度 / 绕开对角化**

如果目标是**做非常差异化、论文感强的路线**，推荐排序：

1. **专用硬件上的 DFT 子核**
2. **learned XC / end-to-end learned KS**
3. **硬件原生的非主流电子结构路线**

## 10. 最后一句话：行业共识是什么

如果把整个调研压缩成一句最重要的话：

> 当前 DFT 加速行业最稳、最热、最成熟的主线，是围绕真实生产代码做 GPU 化与基础设施重构；  
> ML 方向是快速升温的新热点，但更多是在缩短 SCF 或替代工作流；  
> 专用硬件很有研究吸引力，但在 DFT 赛道上离行业主流仍明显更远。

---

## 参考来源

### A. 官方文档与官方发布

- Quantum ESPRESSO:
  - [Quantum ESPRESSO 7.2 官方发布](https://www.quantum-espresso.org/quantum-espresso-7-2/)
  - [QE 7.2 release notes](https://www.quantum-espresso.org/release-notes/release-notes-QE7-2.html)
  - [QE 用户指南](https://www.quantum-espresso.org/Doc/user_guide/node2.html)
- VASP:
  - [OpenACC GPU port of VASP](https://www.vasp.at/wiki/OpenACC_GPU_port_of_VASP)
  - [VASP precompiler options](https://vasp.at/wiki/Precompiler_options)
- CP2K:
  - [CP2K GPU 支持状态页](https://www.cp2k.org/gpu)
  - [CP2K CUDA 文档](https://manual.cp2k.org/trunk/technologies/accelerators/cuda.html)
  - [CP2K DLA-Future 文档](https://manual.cp2k.org/trunk/technologies/eigensolvers/dlaf.html)
- ABINIT:
  - [ABINIT GPU support](https://docs.abinit.org/INSTALL_gpu/)
  - [ABINIT parallel/GPU variables](https://docs.abinit.org/variables/paral/)
- PySCF / GPU4PySCF:
  - [GPU4PySCF 官方仓库](https://github.com/pyscf/gpu4pyscf)
- Q-Chem / BrianQC:
  - [Q-Chem BrianQC 页面](https://www.q-chem.com/explore/performance/brianqc/)
  - [BrianQC 官方主页](https://www.brianqc.com/)
- TeraChem / PetaChem:
  - [PetaChem 官方主页](https://petachem.com/)
- GPAW:
  - [GPAW 官方文档](https://gpaw.readthedocs.io/)
  - [GPAW GPU 文档](https://gpaw.readthedocs.io/documentation/gpu.html)
- Octopus:
  - [Octopus GPU 教程](https://www.octopus-code.org/documentation/main/tutorial/hpc/gpu/)
  - [Octopus GPU Docker image](https://octopus-code.org/documentation/16/manual/docker_images/)
- DFT-FE:
  - [DFT-FE 官方仓库](https://github.com/dftfeDevelopers/dftfe)
- ELPA:
  - [ELPA 官方介绍](https://elpa.mpcdf.mpg.de/ABOUT_ELPA.html)
  - [ELPA 用户手册](https://elpa.mpcdf.mpg.de/documentation/userguide/ELPA_USERGUIDE.html)
- ELSI:
  - [ELSI 官方主页](https://wordpress.elsi-interchange.org/)
  - [ELSI 用户手册](https://wordpress.elsi-interchange.org/wp-content/uploads/2022/04/elsi-manual-2.9.0.pdf)
- SIRIUS:
  - [SIRIUS 官方仓库](https://github.com/electronic-structure/SIRIUS)
- ByteQC:
  - [ByteQC 官方仓库](https://github.com/bytedance/byteqc)
- DeePMD:
  - [DeePMD-kit 官方仓库](https://github.com/deepmodeling/deepmd-kit)
- ML XC:
  - [Skala 官方仓库](https://github.com/microsoft/skala)
  - [NeuralXC 官方仓库](https://github.com/semodi/neuralxc)

### B. 代表性论文与研究来源

- [Introducing GPU Acceleration into the Python-Based Simulations of Chemistry Framework (GPU4PySCF, 2024)](https://pubs.acs.org/doi/10.1021/acs.jpca.4c05876)
- [An alternative GPU acceleration for a pseudopotential plane-waves density functional theory code (2024)](https://arxiv.org/abs/2412.01695)
- [VASP on a GPU: application to exact-exchange calculations of the stability of elemental boron (2011, 作为 VASP GPU 基础背景)](https://arxiv.org/abs/1111.0716)
- [Fast and Scalable GPU-Accelerated Quantum Chemistry for Periodic Systems with Gaussian Orbitals (TeraChem, 2024)](https://arxiv.org/abs/2410.22278)
- [ByteQC: GPU-Accelerated Quantum Chemistry Package for Large-Scale Systems (2025)](https://arxiv.org/abs/2502.17963)
- [Matrix-free algorithms for fast ab initio calculations on distributed CPU architectures using finite-element discretization (DFT-FE, 2025)](https://arxiv.org/abs/2512.08571)
- [Graphics Processing Unit acceleration of the Random Phase Approximation in the projector augmented wave method (GPAW, 2013, 作为 GPU 背景)](https://arxiv.org/abs/1307.8052)
- [NeuralSCF: Neural network self-consistent fields for density functional theory (2024)](https://arxiv.org/abs/2406.15873)
- [Towards A Universally Transferable Acceleration Method for Density Functional Theory (2025)](https://arxiv.org/abs/2509.25724)
- [Predicting The One-Particle Density Matrix With Machine Learning (2024)](https://arxiv.org/abs/2401.06533)
- [D4FT: A Deep Learning Approach to Kohn-Sham Density Functional Theory (2023)](https://arxiv.org/abs/2303.00399)
- [Robust Determination of the Chemical Potential in the PEXSI Method (2017, 作为低标度背景方法来源)](https://arxiv.org/abs/1708.04323)
- [Accelerating Atomic Orbital-based Electronic Structure Calculation via PEXSI (2012, 作为原始方法来源)](https://arxiv.org/abs/1202.2159)
- [ELSI: A Unified Software Interface for Kohn-Sham Electronic Structure Solvers](https://arxiv.org/abs/1705.11191)
- [A Hardware-Native Realisation of Semi-Empirical Electronic Structure Theory on FPGAs (2026)](https://arxiv.org/abs/2602.11702)

### C. 说明

- 本文关于“热度 / 成熟度 / 可做性”的判断是综合推断，不是单个来源的原始表述。
- `PEXSI` 与部分 solver infrastructure 的代表论文早于 2023；之所以保留，是因为它们仍是 2023-2026 期间行业路线选择的重要基础方法，而不是历史陈列。
- `VASP`、`GPAW` 这类成熟代码的部分代表性 GPU 论文也早于 2023；之所以保留，是为了补足当前官方 release/wiki 之外的学术背景脉络。
