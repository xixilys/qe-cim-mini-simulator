# VASP / QE GPU 支持演化与异构加速路线时间线（截至 2026-03-30）

## 0. 摘要

这份文档回答一个比“现在谁更快”更基础的问题：`VASP` 和 `Quantum ESPRESSO (QE)` 分别是从什么时候开始支持 `GPU` 的，这种支持是以什么形式出现的，又是从什么时候开始从“实验性分支”转向“主线工程路线”。

先给结论：

- 如果只问“什么时候第一次出现 GPU 支持”，`QE` 很早，在 `2011-05-05` 就发布了首个 `GPU-enabled beta` [1]；`VASP` 至少在 `VASP.5.4.1.05Feb16` 时已经公开提供 `CUDA-C` GPU 端口 [2]。
- 但如果问“什么时候真正把异构加速当成主线工程方向”，答案明显更晚，主要落在 `2019-2021`：`QE` 在 `2019-03-04` 重新公开与 `QE 6.4` 对齐的 GPU alpha [3]，并在 `2021-07-19` 的 `QE 6.8` 将 `CUDA Fortran` GPU 支持带入主仓库 [4]；`VASP` 则在 `2021-01-18` 的 `VASP 6.2.0` 明确把 `OpenACC` GPU 版作为官方推荐路线 [5][6]。
- 如果再把“异构”理解成不只支持 `NVIDIA`，而是走向 `CPU + NVIDIA/AMD/Intel` 的可移植路线，则更晚：`VASP` 到 `2026-03-10` 的 `6.6.0` 才发布面向 `AMD/Intel` 的实验性 `OpenMP offloading` GPU 端口 [6][7]；`QE` 官方 roadmap 与 `7.5.0` user guide 则显示，它已经把 `CPU/GPU code unification` 和多厂商 GPU 支持作为持续主线，但口径上仍保留“`NVIDIA` 稳定、`AMD` 支持中”的渐进状态 [8][9]。

因此，更准确的历史叙述不是“科学计算很晚才想到异构加速”，而是：

1. `2010-2012`：社区已经开始认真试水 GPU；
2. `2016-2021`：GPU 从早期专门分支逐步转为生产代码主线；
3. `2021-2026`：焦点从“有没有 GPU 版”转向“如何把 CPU/GPU 分叉重新统一，并扩展到多厂商异构平台”。

下面关于“科学计算领域何时才认真把异构加速作为技术路线”的判断，是基于 `VASP/QE` 的官方页面、`QE` 本地代码 survey、代表性论文与 release artifacts 做的综合推断，不代表某个单一官方机构的统一表述。

## 1. 研究问题、方法与证据口径

### 1.1 研究问题

本文聚焦三个问题：

1. `VASP` 和 `QE` 各自何时第一次出现可公开确认的 GPU 支持；
2. 这些支持何时从“外部分支/实验版”升级为“主仓库/官方推荐”；
3. 这条演化路径对“科学计算领域何时真正把异构加速当成主线技术路线”意味着什么。

### 1.2 方法

按照 `inno-deep-research` 与 `academic-researcher` 的工作流，本文优先采用以下证据顺序：

- `官方新闻页 / wiki / user guide / roadmap / release notes`；
- `官方仓库 release artifact`；
- `代表性论文`，用于补足“学术界何时开始做”这一层；
- `本地源码 code survey`，用于补足“当前代码形态是否已经体现 CPU/GPU 统一维护”这一层。

按照 `inno-code-survey` 的思路，本文还对本地 `QE` 工作区副本做了轻量代码 survey，重点看了：

- `soft/qe-7.5/README_GPU.md`；
- `soft/qe-7.5/KS_Solvers/ParO/paro_gamma_new.f90`；
- `soft/qe-7.5/KS_Solvers/ParO/paro_k_new.f90`；
- `soft/qe-7.5/LAXlib/la_module.f90`。

按照 `biorxiv-database` 与 `dataset-discovery` 的流程，我还做了两个辅助检索：

- `bioRxiv` 用关键词 `density functional theory` + `GPU` 搜索 `2016-04-01` 到 `2026-03-30`，结果为 `0` 条；
- 数据集搜索脚本以 `quantum espresso dft benchmark` 查询 `GitHub + papers`，未找到可作为本题主证据的标准数据集。

这两个负结果本身也说明：这个问题更适合通过 `official release history + code survey` 来回答，而不是通过生命科学预印本或标准 ML 数据集来回答。

按照 `gemini-deep-research` 的要求，本应优先尝试 Gemini 的 deep research 脚本；但本 session 中 `GEMINI_API_KEY` 未设置，因此该技能无法真正调用脚本执行，本文采用多源手工深研作为回退路径。

## 2. 一条更准确的三阶段时间线

如果把 `VASP/QE` 的 GPU 演化压成一条更便于写论文或汇报的主线，可以分成三段：

### 2.1 第一阶段：早期试水（2011-2016）

这一阶段的特点是：

- GPU 支持已经存在，但更多是 `beta`、`alpha`、专门端口或研究型路线；
- 目标是证明“这条路可行”，而不是把所有生产工作流都统一进去；
- GPU 支持通常强绑定 `NVIDIA` 生态。

`QE` 的标志性节点是 `2011-05-05` 的官方新闻：首个 `GPU-enabled beta release` 可下载 [1]。这说明平面波 DFT 社区并不是到 2020 年代才想到 GPU；实际上在 Fermi/Kepler 前后，已有主流代码开始明确试水。

`VASP` 的公开产品化痕迹稍晚但也不算晚。官方 `CUDA-C GPU port of VASP` 页面写明，`as of VASP.5.4.1.05Feb16`，VASP 的若干核心算法已经被移植到 GPU 加速硬件上 [2]。也就是说，到 `2016` 年时，`VASP` 已经不再只是“论文级 proof-of-concept”，而是存在一个可识别的 GPU 端口。

### 2.2 第二阶段：主线化与重新公开（2019-2021）

这一阶段的特点是：

- GPU 路线开始重新对齐主版本号，而不是长期漂在孤立分支；
- 官方 release 与官方 wiki 开始明确给出推荐口径；
- “是否支持 GPU”逐渐变成生产级软件竞争力的一部分。

`QE` 的关键转折点是 `2019-03-04`。官方新闻页在发布 `QE 6.4` 的同时，宣布新的 GPU-enabled QE 已重新公开，并给出“与 `QE 6.4` 对齐的首个 alpha 版” [3]。这件事的重要性不只是“又有了 GPU 版”，而是意味着 GPU 路线重新被拉回主版本叙事。

`VASP` 的关键转折点是 `2021-01-18` 的 `VASP 6.2.0`。官方 `GPU ports of VASP` 页明确写到：从 `VASP 6.2.0` 起，`OpenACC` GPU port 被“正式发布”，并且“官方强烈推荐”在 `NVIDIA` GPU 系统上使用这个版本 [6]。这表明 `VASP` 不再把 GPU 看成一个附属的旧端口，而是转成了正式维护的主路线。

### 2.3 第三阶段：从 GPU 化走向异构化（2021-2026）

这一阶段的特点是：

- 问题不再只是“有没有 GPU 版”；
- 真正困难的问题变成“怎样统一 CPU/GPU 代码，并扩展到多厂商平台”；
- `solver / FFT / communication / data layout` 与程序结构重构开始比单个 kernel 更重要。

`QE` 在 `2021-07-19` 的 `6.8` release 中明确写道：`Support for GPU via CUDA Fortran brought to the main repository` [4]。到 `2021-12-21` 的 `7.0`，release notes 又继续写明 `PWscf` 和 `CP` 的 GPU 支持被显著扩展 [10]。与此同时，官方 roadmap 把 `GPU porting` 扩展与 `CPU/GPU code unification` 并列为自 `2015` 以来的重要项目 [8]。

`VASP` 则进一步从 `NVIDIA-only` 向“更广义异构”推进。官方 `GPU ports of VASP` 页面说明，旧 `CUDA-C` 端口在 `6.3.0` 被完全移除，而 `6.6.0` 则首次发布面向 `AMD` 与 `Intel` 数据中心 GPU 的实验性 `OpenMP GPU-port` [6]。这一步的象征意义很强：重点已经从“把代码搬到 CUDA 上”转为“如何让生产代码跨 GPU 厂商演化”。

## 3. VASP 的 GPU / 异构演化时间线

### 3.1 压缩版时间表

| 时间 | 事件 | 性质 | 解释 |
| --- | --- | --- | --- |
| 2011 | `VASP on a GPU` 代表性论文发表 [11] | 学术验证 | 说明 VASP 社区很早就开始探索 GPU，尤其是 exact exchange 一类高成本路径 |
| 2016-02-05 | `VASP.5.4.1.05Feb16` 已有 `CUDA-C` GPU port [2] | 产品级端口 | 可视为最迟在此时已经存在公开可识别的 GPU 端口 |
| 2021-01-18 | `VASP 6.2.0` 发布 [5] | 主线转折 | `OpenACC` GPU port 成为官方推荐的 `NVIDIA` 路线 [6] |
| 2021 之后 | `VASP 6.3.0` 移除旧 `CUDA-C` 端口 [2][6] | 路线清理 | 从定制 CUDA 分支切向更可维护的 OpenACC 主线 |
| 2026-03-10 | `VASP 6.6.0` 发布 [7] | 异构扩展 | 开始提供面向 `AMD/Intel` 的实验性 `OpenMP` GPU port [6] |

### 3.2 这一演化的核心含义

`VASP` 的演化特别能体现一个现实：

- 早期 GPU 支持可以靠高度定制的 `CUDA-C` 端口实现；
- 但当 GPU 成为主流生产环境时，维护成本与可移植性会反过来倒逼软件架构调整；
- 最终主线不是“继续把 CUDA 写得更深”，而是转向 `OpenACC`，再进一步走向 `OpenMP offload`。

这说明对生产级科学计算代码来说，真正的难点从来不只是“写出 GPU kernel”，而是：

- 如何把一大批旧代码迁进新模型；
- 如何维持正确性与可维护性；
- 如何减少厂商绑定带来的长期成本。

### 3.3 对科学计算异构路线的启示

如果只看 `VASP`，可以得到一个很清楚的结论：

- `2010s` 前半段：GPU 已经被认真看待，但仍主要是“加速选定热点”；
- `2021` 左右：GPU 已经足够重要，必须进入官方主版本叙事；
- `2026` 左右：真正的焦点已从“GPU 支持”转向“跨厂商异构支持”。

换句话说，`VASP` 不是在 2020 年代才想到异构，而是在 2020 年代才不得不把异构问题当成长期工程主线。

## 4. QE 的 GPU / 异构演化时间线

### 4.1 压缩版时间表

| 时间 | 事件 | 性质 | 解释 |
| --- | --- | --- | --- |
| 2011-05-05 | 首个 `GPU-enabled beta release` [1] | 早期试水 | 说明 QE 很早就开始公开 GPU 路线 |
| 2012 | `phiGEMM` 等早期 CPU-GPU porting 工作出现 [12] | 学术/工程探索 | 反映混合系统 porting 早已成为显式问题 |
| 2019-03-04 | `QE 6.4` 同时重新公开 GPU alpha [3] | 主线重新对齐 | GPU 版不再只是遗留分支，而是重新挂到主版本叙事上 |
| 2020 | `Quantum ESPRESSO toward the exascale` 发表 [13] | 路线固化 | 说明 GPU/可扩展并行已进入官方论文叙事 |
| 2021-07-19 | `QE 6.8` 把 `CUDA Fortran` GPU 支持带入主仓库 [4] | 主仓库合并 | 这是 QE GPU 路线真正进入主线工程的强信号 |
| 2021-12-21 | `QE 7.0` 显著扩展 `PWscf` 与 `CP` 的 GPU 支持 [10] | 覆盖面扩展 | 从“支持存在”走向“主模块覆盖更广” |
| 2026 当前文档口径 | `NVIDIA` 稳定，`AMD` 支持中但未完全进入主仓库稳定版 [9] | 异构演进中 | 仍处于 CPU/GPU 统一与多平台扩展的持续阶段 |

### 4.2 本地源码 survey 给出的结构性旁证

`QE` 的一个优势是可以直接看本地源码形态。当前工作区副本显示了三条很有代表性的线索：

第一，`soft/qe-7.5/README_GPU.md` 已直接把 GPU 版视作同一仓库的一部分，并说明 GPU 支持默认开启，构建依赖 `nvfortran` / `NVIDIA HPC SDK`，同时指出 `OpenACC` 已不再是可选项，而是 GPU 版本必需路径 [14]。这说明 GPU 已不是“外部补丁”，而是仓库内正式维护对象。

第二，`soft/qe-7.5/KS_Solvers/ParO/paro_gamma_new.f90` 与 `soft/qe-7.5/KS_Solvers/ParO/paro_k_new.f90` 内部都保留了 `2022-05-30` 的说明：这两个求解器文件已被改写为 `OpenACC` 端口，旧的 `CUF` 专用版本被移除，现有文件同时服务于 CPU 与 GPU 执行 [15][16]。这类注释很能说明异构路线的真实难点：不是“再多加一个 GPU 文件”，而是把 CPU/GPU 路径重新统一成同一份可维护代码。

第三，`soft/qe-7.5/LAXlib/la_module.f90` 已经有 `Parallel GPU version with full data distribution` 的接口，但对若干并行 generalized eigensolver 路径仍保留 `place-holder, ... not implemented yet` 的说明 [17]。这恰恰反映了大型科学软件的真实状态：异构支持通常先覆盖主路径，然后再逐步填补更复杂、通信更重、结构更特殊的边角路径。

### 4.3 QE 演化的核心含义

`QE` 的历史说明了一件事：

- 早期 GPU 路线出现得很早；
- 但从“可以下载的 GPU beta/alpha”到“正式并入主仓库”，中间隔了接近十年；
- 真正困难的不是证明一个 kernel 能在 GPU 上跑，而是把整个软件栈的维护、版本、并行、通信与数值正确性一起收回来。

因此，如果从 `QE` 的角度问“科学计算何时认真考虑异构加速”，更准确的回答是：

- `2011` 就开始公开试验；
- `2019-2021` 才真正进入主线工程化阶段；
- 到 `2026` 仍在继续处理 CPU/GPU 统一与多厂商支持问题。

## 5. 这说明科学计算领域何时真正把异构加速当成路线

### 5.1 一个可以直接写进汇报的判断

如果只用一句话概括：

> 科学计算领域并不是在 2020 年代才“想到”异构加速，而是在 2010 年代早期就开始试水；只是直到 2019-2021 前后，异构加速才真正从局部试验上升为主流生产代码必须面对的主线工程问题。

### 5.2 为什么会晚于“学术上可做”

从 `VASP/QE` 两条线都可以看到，工程化明显晚于概念验证。原因至少有四类：

1. **数值软件比通用 HPC kernel 更保守**  
   电子结构代码要同时守住数值稳定性、物理可重复性与长期可维护性，不能因为单点加速而轻易破坏主线。

2. **热点不是单个 GEMM，而是整条求解链**  
   真正耗时的往往是 `FFT + projector + Hamiltonian application + subspace solver + communication` 的组合，而不是一个孤立 kernel。单点 GPU 化容易，整链 GPU 化难。

3. **旧代码包袱与多平台维护成本极高**  
   早期可以通过 `CUDA-C`、`CUDA Fortran`、`CUF` 路线快速证明价值，但真正进入生产后，代码分叉会变成负担，于是又必须走向 `OpenACC`、`OpenMP offload` 和 CPU/GPU 统一维护。

4. **异构化的真正终点不是“NVIDIA 跑起来”**  
   从最近的 `VASP 6.6.0` 与 `QE` roadmap/user guide 看，真正的难题是 `NVIDIA + AMD + Intel` 的长期可移植支持。这是 2020 年代中期才更突出的目标。

### 5.3 一条更适合论文背景的阶段划分

如果需要在论文背景部分快速概括，可以直接使用下面这组阶段定义：

- **阶段 A：GPU proof-of-concept 期（约 2011-2016）**  
  代表特征是：已有主流代码开始出现 GPU beta、GPU port、CPU-GPU 混合 porting 论文，但多数仍是专门路线。

- **阶段 B：主版本工程化期（约 2019-2021）**  
  代表特征是：GPU 支持开始重新对齐主版本号，并进入官方 release / wiki / main repository 叙事。

- **阶段 C：异构可移植期（约 2021-2026）**  
  代表特征是：焦点从“有无 GPU”升级为“如何统一 CPU/GPU 代码，并扩展到多厂商 GPU 平台”。

在这个意义上，`VASP/QE` 的历史可以作为一个相当有代表性的样本，说明：

- 科学计算对异构加速的重视并不晚；
- 但把它做成生产级主路线，确实要比学术原型晚很多；
- 多厂商异构支持更是直到 2020 年代中后期才越来越成为显性目标。

## 6. 对本项目的直接启发

对当前这个以 `QE` 子空间路径为入口的项目，这段历史有三条直接启发。

第一，`QE` 作为切口是合理的。它和 `VASP` 同属主流 plane-wave DFT 路线，但又比 `VASP` 更开放、更适合作 workload trace、源码 survey 与软件-硬件协同。

第二，历史已经反复说明，真正难加速的不是“某个浮点核”，而是 `FFT / operator chain / subspace solver / communication` 组成的整条 band-solver 路径。这与当前项目从通用 `complex FP64 GEMM` 叙事逐步转向 `QE-connected band-solver subsystem`、再转向 `adjoint-aware projector primitive` 的方向是对齐的。

第三，`VASP/QE` 的 GPU 演化都说明：当某条加速路线真正进入生产级工程时，中心问题会从“单点算得快”变成“结构上是否更接近真实软件主路径”。从这个角度看，本项目若要形成有说服力的硬件叙事，最好继续坚持 `QE-native operator / projector / reduced-space chain` 这条叙事，而不是退回到孤立 GEMM IP 的说法。

## 7. 辅助检索结果

### 7.1 bioRxiv 检索

- 工具：`biorxiv-database`
- 查询：`density functional theory` + `GPU`
- 时间范围：`2016-04-01` 至 `2026-03-30`
- 结果：`0` 条

这说明，本题的有效证据并不来自生命科学预印本渠道。

### 7.2 数据集检索

- 工具：`dataset-discovery`
- 查询：`quantum espresso dft benchmark`
- 数据源：`GitHub + papers`
- 结果：未找到可直接支撑“VASP/QE GPU 支持时间线”的标准数据集

这意味着本题最可靠的证据，仍应回到软件官方历史、release notes 和代码结构本身。

## 8. 参考资料

[1] Quantum ESPRESSO 官方新闻：`Quantum ESPRESSO for GPU`, `2011-05-05`.  
https://www.quantum-espresso.org/quantum-espresso-for-gpu/  
证据性质：官方新闻页。

[2] VASP Wiki：`CUDA-C GPU port of VASP`.  
https://vasp.at/wiki/CUDA-C_GPU_port_of_VASP  
证据性质：官方 wiki；给出 `VASP.5.4.1.05Feb16` 与 `6.3.0` 路线说明。

[3] Quantum ESPRESSO 官方新闻：`Quantum ESPRESSO v.6.4 and Quantum ESPRESSO for gpu`, `2019-03-04`.  
https://www.quantum-espresso.org/quantum-espresso-v-6-4-and-quantum-espresso-for-gpu/  
证据性质：官方新闻页；给出与 `QE 6.4` 对齐的 GPU alpha。

[4] QEF 官方 GitHub release：`qe-6.8`, `2021-07-19`.  
https://github.com/QEF/q-e/releases/tag/qe-6.8  
证据性质：官方 release；写明 GPU via CUDA Fortran 进入主仓库。

[5] VASP 官方新闻索引：`NEW RELEASE: VASP.6.2.0`, `2021-01-18`.  
https://www.vasp.at/info/post/page/3/  
证据性质：官方新闻索引页；给出发布日期。

[6] VASP Wiki：`GPU ports of VASP`.  
https://vasp.at/wiki/GPU_ports_of_VASP  
证据性质：官方 wiki；给出 `6.2.0`、`6.3.0`、`6.6.0` 的 GPU 路线说明。

[7] VASP 官方新闻索引：`NEW RELEASE: VASP.6.6.0`, `2026-03-10`.  
https://www.vasp.at/info/post/  
证据性质：官方新闻索引页；给出发布日期。

[8] Quantum ESPRESSO 官方 roadmap：`Quantum espresso development roadmap`.  
https://www.quantum-espresso.org/road-map/  
证据性质：官方 roadmap；写明 GPU porting 扩展与 CPU/GPU 统一是主线项目。

[9] Quantum ESPRESSO User Guide 7.5.0：`Introduction`.  
https://www.quantum-espresso.org/Doc/user_guide/node2.html  
证据性质：官方用户手册；给出 `Since Feb.2021 NVidia GPU's are supported by the stable releases. AMD GPU's are also supported but not yet in the main repository` 的当前口径。

[10] QEF 官方 GitHub release：`qe-7.0`, `2021-12-21`.  
https://github.com/QEF/q-e/releases/tag/qe-7.0  
证据性质：官方 release；写明 `PWscf` 与 `CP` GPU 支持显著扩展。

[11] Hutchinson, M., Widom, M., Rajagopal, G., Winget, P., Qian, X., Roring, M., Chiesa, S., Chen, J., and Fattebert, J.-L. `VASP on a GPU: Application to exact-exchange calculations of the stability of elemental boron`. *Computer Physics Communications* (2012). DOI: `10.1016/j.cpc.2012.02.017`.  
证据性质：代表性学术论文；说明 VASP 社区早期 GPU 探索。

[12] Fabregat-Traver, D., Quintana-Ortí, G., and Dongarra, J. `phiGEMM: A CPU-GPU Library for Porting Quantum ESPRESSO on Hybrid Systems`. *PDP 2012*. DOI: `10.1109/PDP.2012.72`.  
证据性质：代表性工程论文；说明 QE/混合系统 porting 的早期背景。

[13] Giannozzi, P., Baseggio, O., Bonfà, P., Brunato, D., Car, R., Carnimeo, I., Cavazzoni, C., de Gironcoli, S., Delugas, P., Ferrari Ruffino, F., Ferretti, A., Marzari, N., Timrov, I., Urru, A., and Baroni, S. `Quantum ESPRESSO toward the exascale`. *The Journal of Chemical Physics* 152, 154105 (2020). DOI: `10.1063/5.0005082`.  
证据性质：官方代表性论文；说明 GPU / exascale 已进入 QE 正式论文叙事。

[14] 本地 QE 代码 survey：`soft/qe-7.5/README_GPU.md:1`.  
证据性质：本地仓库文件；说明 GPU 版已作为主仓库内维护对象存在。

[15] 本地 QE 代码 survey：`soft/qe-7.5/KS_Solvers/ParO/paro_gamma_new.f90:40`.  
证据性质：本地仓库文件；记录 `2022-05-30` OpenACC 统一 CPU/GPU 路线的注释。

[16] 本地 QE 代码 survey：`soft/qe-7.5/KS_Solvers/ParO/paro_k_new.f90:40`.  
证据性质：本地仓库文件；记录 `2022-05-30` OpenACC 统一 CPU/GPU 路线的注释。

[17] 本地 QE 代码 survey：`soft/qe-7.5/LAXlib/la_module.f90:419`.  
证据性质：本地仓库文件；显示并行 GPU generalized eigensolver 路径的当前接口与占位状态。
