# 2026-03-27 本地论文栈种子扫描（local-only，暂不联网）

## 1. 目标

这一步只做 **local-first** 的第一轮种子扫描，不进行外部联网调研。

目的不是立刻回答“外部社区最终怎么做 DFT / scientific computing acceleration”，而是先判断：

1. 当前本地论文栈能不能支撑第一轮问题分解；
2. 它更擅长支撑哪一类问题；
3. 哪些关键证据本地明显缺失，后续必须再补外部检索。

## 2. 使用的本地资源

- 项目内部设计与时间线：`docs/overview/project_development_timeline.md`
- 主论文查询库：`/Volumes/remote/research_data/paper_db/paper_catalog.sqlite`
- PDF 主仓：`/Volumes/extend_2/research_data`
- Zotero 附件层：`/Volumes/remote/Zotero/storage`
- Zotero 本地 CLI：`/Users/xixilys/.codex/skills/zotero-cli/scripts/zotero_tool.py`

## 3. 本地库的整体画像

对 `paper_db` 的第一轮抽样显示：

- 当前库规模约为 `502` 篇；
- 主题分布明显偏向 `ISSCC / VLSI / DAC / JSSC / CIM / AI accelerator`；
- 对 `DFT / QE / VASP / PySCF / generalized eigensolver / scientific-computing workflow integration` 的覆盖明显不足。

高频 venue 抽样结果显示，这个库更像一个 **IC / accelerator / CIM 侧的工作库**，而不是一个已经覆盖 `DFT scientific software + HPC workflow + solver integration` 的平衡库。

## 4. 第一轮本地命中情况

### 4.1 直接相关的种子很少，但不是完全没有

按 `LIKE` 检索后，和当前项目最接近的本地种子包括：

1. `Zeshi Liu`, *A heterogeneous processing-in-memory approach to accelerate quantum chemistry simulation*, `Parallel Computing`, 2023, DOI: `10.1016/j.parco.2023.103017`
2. `Qingcai Jiang`, *NDFT: accelerating density functional theory calculations via hardware/software Co-design on near-data...*, 2025, DOI: `10.48550/arXiv.2504.03451`
3. `Orian Leitersdorf`, *FourierPIM: High-Throughput In-Memory Fast Fourier Transform and Polynomial Multiplication*, 2023, DOI: `10.1016/j.memori.2023.100034`
4. `Rui Liu`, *CIM-BLAS: Computing-in-Memory Accelerator for BLAS*, DAC 2025, DOI: `10.1109/DAC63849.2025.11133288`
5. `Alan Ayala`, *Performance Analysis of Parallel FFT on Large Multi-GPU Systems*, IPDPSW 2022, DOI: `10.1109/IPDPSW55747.2022.00072`
6. `Sebastien Cayrols`, *Lossy all-to-all exchange for accelerating parallel 3-D FFTs on hybrid architectures with GPUs*, CLUSTER 2022, DOI: `10.1109/CLUSTER51413.2022.00029`
7. `David E. Shaw`, *Anton 2: Raising the Bar for Performance and Programmability in a Special-Purpose Molecular Dynamics Supercomputer*, SC 2014

### 4.2 本地库更强的是哪一边

当前本地库更强的是下面这些问题：

- `IC` 风格的 accelerator 组织方式；
- `CIM / PIM / BLAS / FFT` 这样的 primitive 或近邻子模块；
- `ISSCC / VLSI / DAC` 的实现口径与表述风格。

当前本地库明显更弱的是：

- `QE / VASP / PySCF / ABINIT` 这类真实科学计算软件路径；
- `eigensolver + FFT + workflow/runtime` 如何在生产软件中协同；
- `DFT` 社区常见的 `baseline`、`end-to-end` 证据链和公平比较方式；
- `scientific computing accelerator` 在系统层究竟通常切到哪一层边界。

## 5. 已经定位到的一个强种子

本地 Zotero 中已经能解析到下面这篇：

- Zotero item key: `YHZGZQ44`
- 标题：`A heterogeneous processing-in-memory approach to accelerate quantum chemistry simulation`
- 本地 PDF：`/Volumes/remote/Zotero/storage/PD99BZQX/Liu 等 - 2023 - A heterogeneous processing-in-memory approach to accelerate quantum chemistry simulation.pdf`

这篇的重要性在于：

- 它不是泛泛的 AI-CIM，而是直接碰到了 `quantum chemistry simulation`；
- 它可能为我们提供一个很关键的对照：别人把“真实科学计算对象”切在什么层，系统对象到底是 kernel、solver、runtime，还是更大的混合系统。

## 6. 对当前项目的初步含义

### 6.1 本地库现在能支持什么

本地库已经足够支持第一阶段的两类工作：

1. **IC / accelerator 侧问题拆解**
   - primitive 怎么讲；
   - FFT / BLAS / PIM / CIM 怎么对照；
   - 实现论文通常怎样组织贡献与 baseline。

2. **找局部交叉点**
   - 哪些文章开始把 `quantum chemistry / density functional theory / near-data` 和 accelerator 系统结合；
   - 哪些论文能作为“我们的系统边界是否合理”的种子参照。

### 6.2 本地库现在还不能单独回答什么

本地库目前 **不能单独决定**：

- 外部 DFT 社区现在主流到底如何加速 `QE / VASP / PySCF`；
- `scientific computing` 论文里别人到底如何处理 `solver/runtime/software integration`；
- 我们的 `Host/QE + FPGA/runtime + Chip` mixed-system cut 是否已经对齐外部最有说服力的做法。

这说明后续确实还需要联网检索，但那应该发生在 **本地种子阅读和问题框架先收紧之后**，而不是现在立刻跳出去大搜。

## 7. 当前最重要的本地阶段性结论

第一轮 local-only 扫描后，可以先得到三个结论：

1. **本地论文库对 IC / accelerator / CIM 很强，但对 DFT software/system 侧明显偏弱。**
2. **它足够支撑第一步问题分解，但不足以独立完成最终赛道判断。**
3. **下一步最合理的动作不是直接大规模外网调研，而是先精读少数本地强种子，抽取系统边界、baseline、证据链和架构切分方式。**

## 8. 建议的下一个本地步骤

按照当前 `survey-first` 流程，下一步建议只做下面这一件事：

- 精读 `Liu 2023 Parallel Computing` 这篇本地已定位 PDF 的文章；
- 输出一个结构化笔记，专门回答：
  - 它的真实系统对象是什么；
  - 它把边界切在 `kernel / module / subsystem / full workflow` 的哪一层；
  - 它的 baseline 是谁；
  - 它怎么证明“真的解决了问题”；
  - 这对我们当前 `Host/QE + FPGA/runtime + Chip` mixed-system 方案意味着什么。

在完成这一步之前，不建议直接把外部联网调研铺得太开。
