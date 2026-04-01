# VASP / QE / PySCF 主要加速方式专题调研（2023-01-01 至 2026-03-23）

## 0. 摘要

这份文档只回答一个更具体的问题：如果把视角收窄到 `VASP`、`Quantum ESPRESSO`、`PySCF` 三种最有代表性的电子结构软件，它们各自**主要靠什么加速**，这些加速方式的共同模式是什么，差异又在哪里。

先给结论：

- `VASP` 和 `QE` 的主线更像 **plane-wave / pseudopotential / band-solver 加速**，重点落在 `blocked-Davidson / RMM-DIIS / CG`、`FFT`、`projector/nonlocal operator`、`exact exchange` 和相关并行/库栈协同。
- `PySCF` 的主线更像 **Gaussian/orbital/ERI-tensor contraction 加速**，重点落在 `J/K/XC`、`density fitting`、`ERI`、梯度/Hessian，以及 Python 对 GPU 的快速接入。
- 三者的共同点不是“都在加速某一个统一内核”，而是：
  - 都围绕 `SCF` 主循环反复调用的热点做加速；
  - 都越来越依赖 `GPU + FFT/BLAS/solver/tensor` 基础设施；
  - `hybrid / exact exchange` 都是高价值但高成本方向。
- 三者的最大差异不在语言，而在 workload 结构：
  - `VASP/QE` 更像 `plane-wave + subspace/band solver + FFT/projector`
  - `PySCF` 更像 `Gaussian/orbital + ERI/JK/XC + density fitting`
- 如果只选一个后续深入研究和专用加速入口，**`QE` 最合适**：
  - 和 `VASP` 同属 plane-wave 主流；
  - 比 `VASP` 更开放、更易复现；
  - 比 `PySCF` 更接近材料 DFT 的主流生产路径。

这份文档是总览调研 [dft_acceleration_industry_survey_20260322.md](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_industry_survey_20260322.md) 的“按软件重写版”。总览报告强调行业版图；本文强调三家软件本身的加速路径、对比与落点。
如果进一步关心 `VASP/QE` 的 `GPU` 支持究竟是何时出现、何时从实验性分支转为主线工程路线，可继续阅读补充时间线文档 [vasp_qe_gpu_support_evolution_20260330.md](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/vasp_qe_gpu_support_evolution_20260330.md)。

## 1. 导言

### 1.1 为什么选这三家

这三种软件刚好覆盖了电子结构 DFT 世界里三种最重要的软件性格：

- `VASP`
  - 商业闭源、产业接受度高、plane-wave 主流生产代表
- `Quantum ESPRESSO`
  - 开源、plane-wave 主流、最适合作为真实软件路径入口
- `PySCF`
  - 开源、Python 生态、Gaussian/orbital 路线、算法试验和快速迭代非常强

也就是说，这三家并不是“换个界面做同一件事”，而是恰好能把 DFT 加速的两条主要软件范式同时覆盖出来：

- `VASP / QE`：plane-wave 路线
- `PySCF`：Gaussian/orbital 路线

### 1.2 时间窗口与证据口径

- 时间窗口：**2023-01-01 至 2026-03-23**
- 官方资料优先：
  - 官网
  - wiki
  - user guide
  - release notes
  - 官方仓库
- 代表性论文补强：
  - 近三年优先
  - 必要时保留少量更早基础论文，并明确标注为“背景锚点”
- 证据不对称说明：
  - `VASP` 为闭源软件，因此内部实现主要依赖公开 wiki、官方文档和论文
  - `QE` 与 `PySCF` 为开源软件，可以额外参考公开源码和本地已有补充材料
- 截至 **2026-03-23** 的版本说明：
  - `QE` 官网新闻页最新公开下载消息是 **2025-03-14** 的 `QE 7.4.1`
  - 但官网当前 `User Guide` 页面已经标注为 **version 7.5.0**
  - 因此，本文把 `QE 7.5.0 User Guide` 视为“当前官网文档状态”，不把它简单等价成单独发布公告  
    见 [Quantum ESPRESSO version 7.4.1 available for download](https://www.quantum-espresso.org/quantum-espresso-v7-4-1-available-on-the-download-page/) 与 [QE User Guide 7.5.0](https://www.quantum-espresso.org/Doc/user_guide/node2.html)。

### 1.3 本文统一使用的四个判断轴

每个软件和每种加速方式都按四个轴来写：

- `主要加速对象`
- `主要实现方式`
- `成熟度`
- `对专用加速的启发`

## 2. VASP：plane-wave 主流生产代码的加速方式

### 2.1 软件定位

`VASP` 是最典型的产业级 plane-wave DFT 生产软件之一。它的特点不是“最开放”，而是：

- 用户群成熟
- 生产工作流稳定
- 方法学覆盖广
- 对 plane-wave 材料 DFT 社区的代表性很强

这也决定了它的加速策略整体更偏务实：优先把真正吃时间、最常用、最能直接改善用户体验的路径推到 GPU 和高性能并行上。

### 2.2 主要加速热点

`VASP` 当前最核心的加速对象可以压成五类：

1. `band solver / electronic minimization`
   - `blocked-Davidson`
   - `RMM-DIIS`
   - `Fast = Davidson + RMM-DIIS` 混合路径
2. `plane-wave 相关核心内核`
   - `FFT`
   - real-space projection operators
   - 相关 BLAS/LAPACK/scaLAPACK 调用
3. `hybrid DFT / exact exchange`
4. `response / GW / BSE / RPA` 一类更高成本方法
5. `MPI + GPU + collective` 的整体并行组织

官方 wiki 对 `ALGO` 和 `IALGO` 的说明很清楚：

- `ALGO=Normal` 选 `blocked-Davidson`
- `ALGO=VeryFast` 选 `RMM-DIIS`
- `ALGO=Fast` 是前期 `blocked-Davidson`、后期切到 `RMM-DIIS` 的混合策略  
  见 [ALGO](https://vasp.at/wiki/ALGO) 与 [IALGO](https://www.vasp.at/wiki/index.php/IALGO)。

这说明 `VASP` 的核心加速对象，本质上还是**电子优化主循环**，而不是某个孤立后处理步骤。

### 2.3 代表性实现路径

#### 2.3.1 GPU 端口策略

根据截至 **2026-03-23** 仍在线的官方 GPU 文档，`VASP` 现在同时维护两条 GPU 路线：

- `OpenACC` 端口，面向 `NVIDIA GPU`
- `OpenMP offload` 端口，面向 `AMD` 与 `Intel GPU`

当前官方表述是：

- `VASP` “offers two different GPU ports”
- `OpenACC GPU-port` 自 `VASP 6.2.0` 起成为官方推荐的 `NVIDIA` 路线
- 旧的 `CUDA-C GPU-port` 已废弃，并在 `VASP 6.3.0` 被彻底移除
- `OpenMP GPU-port` 自 `VASP 6.6.0` 起面向 `AMD` 与 `Intel` datacenter GPU 发布，但官方仍明确标注为 **experimental**，理由是不够完整的文档和真实科学工作负载覆盖仍有限  
  见 [GPU ports of VASP](https://www.vasp.at/wiki/index.php/OpenACC_GPU_port_of_VASP)。

这条演进非常有代表性：`VASP` 不是继续维护一条高度定制的旧 CUDA 分支，而是转向更可维护的 `OpenACC + OpenMP offload` 组合。

#### 2.3.2 库与并行栈

官方 GPU 页面明确列出 `FFTW`、`BLAS`、`LAPACK`、`scaLAPACK`、`MPI`、`NCCL/RCCL` 等为关键依赖，并且直接提醒：

- `GPU` 版本更适合一 GPU 一 MPI rank
- `NCORE > 1` 的 wave-function parallel FFT 不利于 GPU 性能

同时，官方 `Precompiler options` 已把 `-DACC_OFFLOAD` 与 `-DOMP_OFFLOAD` 分开列成 GPU 端口必需编译选项，这说明两条 GPU 路线已经进入正式构建体系，而不是仅靠外部分支维护。  
见 [Precompiler options](https://vasp.at/wiki/Precompiler_options)。

这说明 `VASP` 的 GPU 加速不是简单“把算子搬上 GPU”，而是连并行粒度和 FFT 组织都要一起重排。  
见 [GPU ports of VASP](https://www.vasp.at/wiki/index.php/OpenACC_GPU_port_of_VASP)。

#### 2.3.3 Hybrid / exact exchange

`VASP` 的 hybrid functional 文档也很有代表性。官方明确写到：

- hybrid functionals 在 `VASP` 中按 generalized KS 方式实现
- 对周期固体来说，短程 hybrid 如 `HSE06` 更实用
- hybrid 比 semilocal 方法明显更贵  
  见 [Category:Hybrid functionals](https://www.vasp.at/wiki/index.php/Category:Hybrid_functionals)。

这意味着 `VASP` 的高价值加速对象之一，不是普通 GGA，而是 **hybrid / exact exchange**。这也是早期 GPU 论文常常挑它下手的原因。

### 2.4 近三年状态判断

| 维度 | 判断 |
| --- | --- |
| 主要加速对象 | `blocked-Davidson/RMM-DIIS`、FFT、projection operators、exact exchange |
| 主要实现方式 | `OpenACC` for NVIDIA，`OpenMP offload` for AMD/Intel，外加 FFT/BLAS/scaLAPACK/MPI/NCCL 协同 |
| 成熟度 | **高** |
| 当前限制 | 闭源、近年细节主要体现在 wiki/release 而非每年独立论文；OpenMP GPU port 仍明显弱于 NVIDIA 主线；GW/RPA/BSE 相关 GPU 覆盖不完整 |

### 2.5 对专用加速的隐含启发

`VASP` 最值得借鉴的不是某个单独宏，而是它暴露出来的 **plane-wave 主流软件真实热点**：

- 电子优化主循环比后处理更重要
- `FFT + projector/nonlocal + band solver` 是核心链
- `hybrid / exact exchange` 是高价值但高难度路径

对专用加速而言，`VASP` 更像**代表性外部对照**，而不是第一落地方：

- 它很能代表主流 plane-wave DFT
- 但闭源使其不适合作为第一验证入口

## 3. Quantum ESPRESSO：开源 plane-wave 真实入口的加速方式

### 3.1 软件定位

`Quantum ESPRESSO` 是最典型的开源 plane-wave / pseudopotential DFT 套件之一。和 `VASP` 相比，它最大的优势不是“更强”，而是：

- 开源
- 可插桩
- 可做真实 workload 追踪
- 更适合作为后续软件-硬件协同入口

官方用户指南 7.5.0 明确写明：

- 核心包包括 `PWscf` 与 `CP`
- 基于 plane-wave 基组和赝势
- 自 `2021-02` 起稳定版支持 `NVIDIA GPU`
- `AMD GPU` 已支持，但按该 guide 的表述，还未进入主仓库稳定版  
  见 [QE User Guide 7.5.0](https://www.quantum-espresso.org/Doc/user_guide/node2.html)。

因此，截至 **2026-03-23**，`QE` 的官方状态更适合概括成：

- `NVIDIA GPU` 是公开文档里的稳定主线
- `AMD GPU` 路线已存在，但官方文档仍把它放在“支持中、尚未进入稳定主仓库”的位置
- GPU 路线的核心工作仍是持续扩展热点内核覆盖，并把 CPU/GPU 分叉重新收敛

### 3.2 主要加速热点

从公开官方路线和本地补充证据一起看，`QE` 的主要加速热点有六类：

1. `c_bands / band solver`
   - Davidson
   - CG
   - reduced subspace diagonalization
2. `Hamiltonian / overlap application`
   - `h_psi`
   - `s_psi`
3. `FFT`
4. `projector / nonlocal operator`
5. `exact exchange`
6. `更低通信量的 diagonalization 与 parallelization`

官方 roadmap 对这一点非常直白，直接列出：

- GPU porting 扩展与 CPU/GPU 代码统一
- 更少、更小 subspace diagonalization 的新 diagonalization 算法
- 用 OpenMP 重构 FFT task groups
- 改进 band parallelization
- 重构 exact-exchange 代码  
  见 [QE Road Map](https://www.quantum-espresso.org/road-map/)。

### 3.3 代表性实现路径

#### 3.3.1 GPU 与并行化

`QE` 近年的官方信息显示，它的 GPU 路线更像**逐步接管关键内核**，而不是一次性重写整个代码：

- 用户指南里稳定支持的重点仍是 `NVIDIA GPU`
- roadmap 继续强调 `GPU porting` 与 `GPU/CPU unification`
- 同时在 FFT、band parallelization、diagonalization 和 exact exchange 上持续重构

这说明 `QE` 的真实加速策略是：

> 先围绕主路径热点做异构化，再逐步把 CPU/GPU 分叉收敛成统一维护路径。

#### 3.3.2 代表性论文路径

`QE` 的代表性论文有三层：

- 背景层：
  - 官方用户指南要求 GPU 版用户引用 `J. Chem. Phys. 152, 154105 (2020)`  
    见 [Terms of use](https://www.quantum-espresso.org/Doc/user_guide/node6.html)。
- 代码演进层：
  - [Quantum ESPRESSO: One Further Step toward the Exascale](https://pubs.acs.org/doi/10.1021/acs.jctc.3c00249)
- 特定加速层：
  - [An alternative GPU acceleration for a pseudopotential plane-waves density functional theory code with applications to metallic systems (2024)](https://arxiv.org/abs/2412.01695)

其中 2024 这篇很有代表性，因为它不是泛泛地说“GPU 更快”，而是明确把重点放在：

- 对 Kohn-Sham 方程对角化的 GPU 加速
- 对线性系统求解的 GPU 加速
- 重写 `Hamiltonian application`，让 GPU 同时处理多个 `k` 点波函数

这和 `QE` 的真实热点是对齐的。

### 3.4 本地补充证据：QE 的真实热点长什么样

下面这些不是行业唯一证据，而是仓库内已有的本地补充材料，用来帮助判断 `QE` 为什么特别适合作为后续入口：

- [qe_system_workload_revalidation_report_20260321.md](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)
- [qe_subspace_sampling.md](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md)

这些本地结果的关键信号是：

- `electrons` 时间里，主热点稳定落在 `c_bands`
- Davidson case 中，`h_psi/s_psi` 远重于 reduced diagonalization
- `generalized Hermitian` 不是边角情况
- `functional` 会切换 `Davidson` 与 `CG` 主路径  
  见 [qe_system_workload_revalidation_report_20260321.md](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)。

这使得 `QE` 既有行业代表性，又有比 `VASP` 更强的“可证据化入口”价值。

### 3.5 近三年状态判断

| 维度 | 判断 |
| --- | --- |
| 主要加速对象 | `c_bands`、`h_psi/s_psi`、FFT、projector/nonlocal、reduced diagonalization、exact exchange |
| 主要实现方式 | `GPU porting + OpenMP/OpenACC + FFT/BLAS/solver` 重构，辅以并行层和代码统一 |
| 成熟度 | **中高** |
| 当前限制 | GPU 支持跨厂商成熟度不均衡；代码历史包袱仍大；同一软件内部存在 Davidson/CG 等多路径 family |

### 3.6 对专用加速的隐含启发

`QE` 最有价值的地方在于它同时满足三件事：

- 代表主流 plane-wave DFT
- 能直接看到真实热点链路
- 能被真实插桩与复现实验

因此，`QE` 不只是“又一个主流软件”，而是：

> 三家里最适合作为后续真实入口、共性抽取入口和专用加速验证入口的软件。

## 4. PySCF：Python 生态与 ERI/tensor contraction 路线的加速方式

### 4.1 软件定位

`PySCF` 和 `VASP/QE` 的根本差异不是“一个是 Python”，而是它代表了另一类软件范式：

- Gaussian/orbital 路线
- ERI/J/K/XC 与 density fitting 更居中
- Python 驱动，方法创新和工作流组合极快

官方 `About PySCF` 页面明确写到：

- `PySCF` 是开源量化化学代码
- 基于 GitHub，Apache-2.0 许可
- 已被 100 多个学术和工业团队日常使用  
  见 [About PySCF](https://pyscf.org/about.html)。

### 4.2 主要加速热点

`PySCF` 当前最关键的加速对象，不是 plane-wave FFT，而是：

1. `SCF / DFT`
2. `density fitting`
3. `J/K/XC`
4. `ERI / tensor contraction`
5. `gradient / Hessian`
6. 一部分后 `HF/DFT` 的 `MP2 / CCSD`

这条线的核心特征是：

- workload 更像张量 contraction 和积分相关计算
- 很适合和 `CuPy / cuTENSOR`、Python 调度与高层工作流整合
- 但也更依赖 GPU 内存与张量库生态

### 4.3 代表性实现路径

#### 4.3.1 GPU4PySCF

`PySCF` 近三年的标志性路线就是 `GPU4PySCF`。

官方 GPU 文档与官方仓库给出的信息非常具体：

- `GPU4PySCF` 是 `PySCF` 的 GPU 插件
- 可以通过 `to_gpu()` / `to_cpu()` 在 CPU 与 GPU 对象间切换
- 设计目标是尽量保持 PySCF 接口兼容
- `density fitting` 在 `A100-80G` 上相对单核 CPU 可达到很高加速，而 `direct SCF` 提速较低  
  见 [GPU Acceleration (GPU4PySCF)](https://pyscf.org/user/gpu.html) 与 [GPU4PySCF GitHub](https://github.com/pyscf/gpu4pyscf)。

这条路线和 `VASP/QE` 的差别很大：

- 它不是“在一个大型 Fortran 主程序里逐步迁移 GPU”
- 而是“在 Python 框架里用插件方式接管高价值模块”

#### 4.3.2 支持功能与限制

官方 GPU 页面和仓库都列得很清楚：

- 已优化或支持：
  - `SCF`
  - `DFT`
  - `density fitting`
  - `gradient`
  - `Hessian`
  - `LDA/GGA/mGGA/hybrid`
  - `PCM/SMD`
  - 一部分 `TDDFT/TDA`
- 仍在实验阶段或覆盖不完整：
  - `MP2/DF-MP2`
  - `CCSD`
  - `multi-GPU`
  - `PBC SCF/DFT`
  - 若干 response / analysis 功能
- 仍有明确限制：
  - `double hybrid` 不支持
  - `TDDFT Hessian` 不支持
  - 一些模块仍是 CPU-only  
  见 [GPU Acceleration (GPU4PySCF)](https://pyscf.org/user/gpu.html) 与 [GPU4PySCF GitHub](https://github.com/pyscf/gpu4pyscf)。

#### 4.3.3 代表性论文路径

`PySCF` 在这一轮里的代表论文非常明确：

- [Introducing GPU Acceleration into the Python-Based Simulations of Chemistry Framework (JPCA 2024)](https://pubs.acs.org/doi/10.1021/acs.jpca.4c05876)

这篇论文的重要意义，不只是“又做了一个 GPU 版量化化学”，而是把下面这套组合正式拉通了：

- Python 量化化学框架
- GPU 插件
- CuPy / cuTENSOR 张量生态
- SCF/DFT 与导数
- 高层工作流兼容

### 4.4 近三年状态判断

| 维度 | 判断 |
| --- | --- |
| 主要加速对象 | `SCF/DFT`、`density fitting`、`J/K/XC`、ERI/tensor contraction、gradient/Hessian |
| 主要实现方式 | `GPU4PySCF` 插件、`to_gpu()/to_cpu()`、`CuPy/cuTENSOR`、CUDA 版本化二进制包 |
| 成熟度 | **中高，快速升温** |
| 当前限制 | 更偏 `NVIDIA + CUDA` 生态；`MP2/CCSD`、多 GPU 与 PBC 仍部分实验性；不等同于 plane-wave 主流材料 DFT 路线 |

### 4.5 对专用加速的隐含启发

`PySCF` 给出的启发和 `VASP/QE` 明显不同：

- 它说明 `DFT/quantum chemistry` 加速不一定只能围绕 FFT 与 band solver
- `ERI/J/K/XC + density fitting + tensor contraction` 也是一条很完整的加速主线

但如果目标是寻找**跨 `VASP/QE/PySCF` 三者都讲得通的共同 primitive**，那么 `PySCF` 更像：

- 一个非常强的算法创新入口
- 一个很好的 GPU/张量编程入口
- 但不是最适合作为“共同 plane-wave workload 原语”第一入口的对象

## 5. 三者横向对比

### 5.1 软件 -> 主要加速方式总表

| 软件 | 主要加速对象 | 主要实现方式 | 成熟度 | 典型限制 |
| --- | --- | --- | --- | --- |
| `VASP` | `blocked-Davidson / RMM-DIIS`、FFT、projection operators、exact exchange | `OpenACC`、`OpenMP offload`、FFTW/BLAS/LAPACK/scaLAPACK/MPI/NCCL | 高 | 闭源、跨厂商 GPU 端口成熟度不均 |
| `QE` | `c_bands`、`h_psi/s_psi`、FFT、projector、reduced diagonalization、exact exchange | GPU porting、OpenMP/OpenACC、并行层和代码统一、外部数值库 | 中高 | 路径多、历史包袱重、跨平台支持仍演进 |
| `PySCF` | `SCF/DFT`、density fitting、`J/K/XC`、ERI/tensor contraction、gradient/Hessian | `GPU4PySCF`、CuPy/cuTENSOR、对象级 `to_gpu()/to_cpu()` | 中高 | CUDA/NVIDIA 依赖明显，多 GPU/PBC 仍在推进 |

### 5.2 内核/数据流对比表

| 维度 | `VASP` | `QE` | `PySCF` |
| --- | --- | --- | --- |
| eigensolver / electronic minimization | `blocked-Davidson`、`RMM-DIIS`、`Fast` 混合 | Davidson、CG、reduced subspace diagonalization | 有 SCF 迭代，但不是 plane-wave 子空间问题主叙事 |
| FFT | 核心主线之一 | 核心主线之一 | 不是主叙事 |
| projector / nonlocal operator | 重要 | 重要，且本地证据非常强 | 不构成主共性 |
| exact exchange / hybrid | 高价值热点 | 重要热点，官方 roadmap 明确列出 | 同样重要，尤其 `J/K/XC` 与 hybrid |
| ERI / tensor contraction | 非主叙事 | 非主叙事 | 核心主线之一 |
| SCF acceleration | 核心 | 核心 | 核心 |
| 数据流风格 | plane-wave + band solver + FFT/projector | plane-wave + band solver + FFT/projector | orbital/Gaussian + ERI/J/K/XC + DF |

### 5.3 共同模式 vs 特例总表

| 类别 | 三者共同模式 | `VASP/QE` 特征 | `PySCF` 特征 |
| --- | --- | --- | --- |
| 共同热点 | SCF 主循环内重复调用的高成本对象 | band solver、FFT、projector、exact exchange | DF、ERI、J/K/XC、导数 |
| 共同实现趋势 | GPU 化 + 基础库/张量库/并行栈协同 | OpenACC/OpenMP offload + FFT/BLAS/scaLAPACK | GPU 插件 + CuPy/cuTENSOR + Python 生态 |
| 共同困难 | 不是单一 kernel，而是数据流 + 库栈 + 数值稳定性一起决定性能 | FFT、subspace、parallelization | GPU 内存、张量库、方法覆盖 |
| 共同误区 | 不能把“加速方式”简化成“换个硬件跑 GEMM” | 需处理波函数、投影、k 点、subspace | 需处理积分、DF、对象转换、方法兼容 |

### 5.4 工程与生态对比表

| 维度 | `VASP` | `QE` | `PySCF` |
| --- | --- | --- | --- |
| 开放性 | 低，闭源 | 高，开源 | 高，开源 |
| 代表性 | 很高，工业/主流 plane-wave 代表 | 很高，开源 plane-wave 代表 | 高，开源量化化学/算法实验代表 |
| GPU 支持成熟度 | 高，但 NVIDIA 主线最成熟 | 中高，持续演进中 | 中高，插件化推进很快 |
| 可移植性 | 正在增强 | 正在增强 | 当前更偏 NVIDIA/CUDA |
| 可复现实验便利性 | 低 | 高 | 高 |
| 可对接性 | 低到中 | 高 | 高 |

### 5.5 后续入口选择总表

| 维度 | `VASP` | `QE` | `PySCF` |
| --- | --- | --- | --- |
| 代表性 | 很高 | 很高 | 中高 |
| 开放性 | 低 | 高 | 高 |
| 可复现实验便利性 | 低 | 很高 | 高 |
| 对专用加速友好度 | 中 | 很高 | 中高 |
| 讲故事能力 | 很强，但实现受限 | 很强，且可验证 | 很强，偏方法创新 |
| 作为第一入口的综合判断 | 不推荐 | **推荐** | 适合做第二入口或平行入口 |

## 6. 对 CIM / 专用加速的启发

### 6.1 三者共同最值得专用化的对象

如果只从这三家软件的共同性出发，最值得专用化的并不是“整个 DFT”，而是：

1. `SCF` 主循环中反复调用的高价值算子链
2. `hybrid / exact exchange` 相关高成本路径
3. 大量重复的 dense/small-dense、projector、tensor contraction 类内核

再压缩一层：

> 三者共同真正值得盯住的，是“重复调用、数据搬运重、且不只是一次性后处理”的主链对象。

### 6.2 哪些热点更像 GPU / 库优化问题，而不适合直接上 CIM

下面这些方向更像 GPU、库栈和并行组织问题，而不是直接适合上 CIM：

- 通用 `FFT` 生态
- 大型通用 eigensolver 基础设施
- 完整软件栈的多层并行调度
- `PySCF` 整体对象模型和 Python 工作流本身

原因不是它们不重要，而是：

- 它们强依赖成熟软件生态
- 控制与接口复杂
- 很难只靠一个专用阵列替代

### 6.3 哪些 kernel 或数据流最接近共同 primitive

如果要在三者里找最接近共同 primitive 的对象：

- `VASP / QE`
  - 更接近 `projector / basis / subspace` 这一类 `project -> small transform -> back-project` 风格模式
- `PySCF`
  - 更接近 `ERI / density fitting / J/K/XC` 的 contraction 模式

因此，真正跨三者最强的共同 primitive 不一定是单一公式，而更像：

- 一类高复用 contraction / operator-application 模式
- 但其中 `plane-wave` 和 `Gaussian/orbital` 仍有明显分叉

### 6.4 三者里如果要选第一入口，为什么是 QE

如果目标是为后续专用加速或 `CIM` 路线找第一入口，最推荐的是 `QE`，原因是：

1. 它和 `VASP` 同属 plane-wave 主流，代表性足够强
2. 它是开源软件，能直接看真实代码路径
3. 仓库内已经有本地 `QE workload` 补充证据，可以把“行业共性”与“本地可验证入口”接起来
4. 它比 `PySCF` 更接近主流材料 DFT 的共同瓶颈

更直接一点：

- `VASP` 最适合当外部对照
- `QE` 最适合当第一验证入口
- `PySCF` 最适合当快速算法创新与第二平行入口

## 7. 结论与建议

### 7.1 共同模式结论

- `VASP / QE / PySCF` 的共同点不是“都在加速同一个 GEMM”，而是都在围绕 `SCF` 主循环里的高价值热点做加速。
- 三者当前最成熟的实现路径，都是 **GPU 化 + 基础库/张量库/并行模型协同**。
- `hybrid / exact exchange` 是三者都很重要、也都很贵的共同热点。

### 7.2 优先入口结论

- `最共性的加速对象`
  - `SCF` 主循环内重复调用的高成本 operator/contraction
- `最成熟的实现路径`
  - `GPU + FFT/BLAS/solver/tensor` 基础设施协同
- `最适合作为后续入口的软件`
  - **`Quantum ESPRESSO`**
- `对 CIM 最友好的候选对象`
  - 更接近 `VASP/QE` 的 plane-wave projector / basis / subspace 主链，而不是直接试图接管完整软件栈
- `不建议误判为 CIM 主线的方向`
  - 把通用 FFT、完整 eigensolver 生态、整套软件调度层直接等价成“适合做 CIM”

### 7.3 一句话压缩

> 如果只看 `VASP / QE / PySCF` 三家软件，当前最成熟的加速方式仍然是围绕真实主循环热点做 GPU 化与基础设施重构；  
> 如果只选一个后续入口，`QE` 最平衡，因为它既代表主流 plane-wave 路线，又开放到足以做真实工作负载与专用加速研究。

---

## 参考来源

### A. 官方资料

- VASP
  - [VASP Wiki](https://www.vasp.at/wiki/)
  - [GPU ports of VASP](https://www.vasp.at/wiki/OpenACC_GPU_port_of_VASP)
  - [Precompiler options](https://vasp.at/wiki/Precompiler_options)
  - [ALGO](https://vasp.at/wiki/ALGO)
  - [IALGO](https://www.vasp.at/wiki/index.php/IALGO)
  - [Category:Hybrid functionals](https://www.vasp.at/wiki/index.php/Category:Hybrid_functionals)
- Quantum ESPRESSO
  - [QE User Guide 7.5.0](https://www.quantum-espresso.org/Doc/user_guide/node2.html)
  - [QE Terms of use](https://www.quantum-espresso.org/Doc/user_guide/node6.html)
  - [Quantum ESPRESSO 7.2](https://www.quantum-espresso.org/quantum-espresso-7-2/)
  - [Quantum ESPRESSO version 7.4.1 available for download](https://www.quantum-espresso.org/quantum-espresso-v7-4-1-available-on-the-download-page/)
  - [QE Road Map](https://www.quantum-espresso.org/road-map/)
  - [How to use QuantumESPRESSO on GPU based HPC systems](https://www.quantum-espresso.org/how-to-use-quantumespresso-on-gpu-based-hpc-systems/)
- PySCF
  - [PySCF About](https://pyscf.org/about.html)
  - [GPU Acceleration (GPU4PySCF)](https://pyscf.org/user/gpu.html)
  - [GPU4PySCF GitHub](https://github.com/pyscf/gpu4pyscf)
  - [PySCF User Guide](https://pyscf.org/user/)

### B. 代表性论文

- VASP
  - [VASP on a GPU: application to exact-exchange calculations of the stability of elemental boron (2011, 背景锚点)](https://arxiv.org/abs/1111.0716)
- Quantum ESPRESSO
  - [Quantum ESPRESSO toward the exascale, J. Chem. Phys. 152, 154105 (2020, 官方引用锚点)](https://doi.org/10.1063/5.0005082)
  - [Quantum ESPRESSO: One Further Step toward the Exascale (2023)](https://pubs.acs.org/doi/10.1021/acs.jctc.3c00249)
  - [An alternative GPU acceleration for a pseudopotential plane-waves density functional theory code with applications to metallic systems (2024)](https://arxiv.org/abs/2412.01695)
- PySCF
  - [Introducing GPU Acceleration into the Python-Based Simulations of Chemistry Framework (2024)](https://pubs.acs.org/doi/10.1021/acs.jpca.4c05876)
  - [Introducing GPU-acceleration into the Python-based Simulations of Chemistry Framework (arXiv preprint)](https://arxiv.org/abs/2407.09700)

### C. 本地补充材料

- [dft_acceleration_industry_survey_20260322.md](/Volumes/remote/phd/year_2/project/dft加速/docs/survey/dft_acceleration_industry_survey_20260322.md)
- [qe_system_workload_revalidation_report_20260321.md](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_system_workload_revalidation_report_20260321.md)
- [qe_subspace_sampling.md](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md)

### D. 说明

- `VASP` 因为闭源，本文对其实现路径的判断主要依赖官方 wiki 和公开论文，而不是代码级核验。
- `QE` 与 `PySCF` 允许辅以开源与本地补充资料，但正文判断仍以公开官方资料和代表论文为主。
- `VASP` 的代表论文锚点早于 2023；之所以保留，是因为近年的 GPU 端口演化更多体现在官方 wiki/release 中，而不是每年一篇独立论文。
