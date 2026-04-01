# 2026-03-28 QE executable flow recovery v0

## 1. 目标

这份笔记记录当前自主推进路线中的第一条真实执行证据：

> 直接运行本地 `QE`，确认最小 case 是否可跑，并从真实输出里恢复第一层计算流程与负载分配结构。

本次只追求：

- 确认可执行性
- 恢复第一层 phase 结构
- 确认 `c_bands`、`h_psi`、`s_psi`、`fft`、`rdiaghg` 这些对象确实出现在真实运行链路中

## 2. 本次执行对象

### 可执行程序

- `soft/qe-7.5/build_subspace_trace/bin/pw.x`

### 输入文件

- `docs/qe_inputs/h2_tiny_gamma.in`

### 输出目录

- `docs/benchmarks/results/qe_autonomous_h2_tiny/`

### 本次环境变量

- `OMP_NUM_THREADS=1`
- `QE_HPSI_TRACE_FILE=docs/benchmarks/results/qe_autonomous_h2_tiny/hpsi_trace.csv`
- `QE_BANDSOLVER_TRACE_FILE=docs/benchmarks/results/qe_autonomous_h2_tiny/bandsolver_trace.csv`
- `QE_SUBSPACE_TRACE_FILE=docs/benchmarks/results/qe_autonomous_h2_tiny/subspace_trace.csv`
- `QE_SUBSPACE_MIN_N=0`

## 3. 结果：当前 QE 可直接执行

本次 `h2_tiny` case 已成功跑通。

从 `stdout.out` 可直接确认：

- `End of self-consistent calculation`
- `convergence has been achieved in 8 iterations`
- `JOB DONE.`

因此，当前主仓库里的 `QE` 路线不是停留在“理论上可跑”，而是：

- **当前可直接执行**
- **当前可直接抽 trace**
- **当前可作为软件到架构映射的第一执行入口**

## 4. 第一层真实计算流程

从本次真实输出可以直接恢复出一个很清楚的第一层执行结构：

### 4.1 顶层

- `init_run`
- `electrons`

### 4.2 `electrons` 下主要子阶段

- `c_bands`
- `sum_band`
- `v_of_rho`
- `newd`
- `mix_rho`

这说明当前对系统对象的理解仍然成立：

- 真实主对象在 SCF 里确实可以被理解成一个 `electrons` 驱动过程
- 而其中 `c_bands` 是最关键的 band-solver 相关子阶段之一

### 4.3 `c_bands` 下主要子阶段

- `init_us_2`
- `regterg`

### 4.4 `*egterg` 下主要子阶段

- `rdiaghg`
- `h_psi`
- `s_psi`
- `g_psi`

### 4.5 `h_psi` 下主要子阶段

- `h_psi:calbec`
- `vloc_psi`
- `add_vuspsi`

### 4.6 general routines

- `calbec`
- `fft`
- `ffts`
- `fftw`

## 5. 这次真实运行对架构抽象的直接意义

这次运行最重要的不是 case 本身小，而是它在真实输出里已经把几个关键对象都钉住了。

### 5.1 `c_bands` 确实是可以被单独抓住的阶段

虽然本次 case 很小，但输出里明确存在：

- `electrons -> c_bands`

这继续支持当前系统切口：

- 先抓 band-solver family
- 再向外扩展完整 DFT flow

### 5.2 `h_psi / s_psi / rdiaghg / fft` 的组合是现实存在的

这非常关键，因为它说明当前我们一直在文档里反复收口的几类对象并不是假想拼装，而是在真实运行里共同出现：

- `h_psi`
- `s_psi`
- `rdiaghg`
- `fft`
- `calbec`
- `vloc_psi`
- `add_vuspsi`

因此，后续硬件单元抽取完全可以围绕这些对象展开，而不是从空想 primitive 出发。

### 5.3 `calbec` 和 `add_vuspsi` 进一步支持 projector / nonlocal 路线

对当前项目尤其重要的是：

- `h_psi:calbec`
- `calbec`
- `add_vuspsi`

这些名字本身就继续支持：

- projector/nonlocal 路线不是文档层强行解释
- 它确实在真实执行链路里有稳定位置

这会直接影响后面：

- `CIM / projector-apply engine`
- `Near-SRAM partial / assemble path`
- `Solve / reduced-space closure`

的职责划分。

## 6. 第一层负载观察

本次是极小 case，所以不能拿绝对时间下结论，但可以先提炼结构性观察。

### 6.1 `electrons`

- `electrons : 0.02s WALL`

### 6.2 `c_bands`

- `c_bands : 0.01s WALL (8 calls)`

### 6.3 `*egterg` 内部

- `rdiaghg : 31 calls`
- `h_psi : 32 calls`
- `s_psi : 32 calls`
- `g_psi : 23 calls`

### 6.4 通用支撑

- `fft : 81 calls`
- `fftw : 72 calls`
- `calbec : 40 calls`

### 6.5 当前可得出的保守结论

即使在极小 case 下，也已经能看出：

- band solver 并不是单一 dense solve
- 它本质上是一个多阶段循环体
- 内部包含：
  - operator apply
  - overlap-related path
  - reduced solve
  - FFT support
  - projector/nonlocal-related support

这正好与当前 `LCW + replay body` 的方向一致。

## 7. 与当前 LCW/硬件单元划分的对应关系

这次真实运行已经足够支持第一版映射。

### 7.1 `CIM / Projector-Apply Engine`

优先对应：

- `h_psi:calbec`
- `calbec`
- `add_vuspsi`
- 以及后续需要进一步核清的 `h_psi` 内 projector/nonlocal path

### 7.2 `FFT Engine`

优先对应：

- `fft`
- `ffts`
- `fftw`
- `g_psi` 中与表示切换相关的部分

### 7.3 `Solve Engine`

优先对应：

- `rdiaghg`
- `regterg` 中的 reduced-space 求解闭环

### 7.4 `Near-SRAM Support Domain`

虽然输出里不会直接打印它，但从结构上它应承接：

- `h_psi / s_psi` partial
- reduced-build 输入组织
- local replay 中对象的连续驻留

### 7.5 `Vector Companion`

优先承接：

- 小对象更新
- residual / band-state 相关后处理
- loop decision support

## 8. 这次运行还不能回答的事

这次 `h2_tiny` 仍然只是第一步，因此它还不能直接回答：

- 中大规模 case 下的真实负载占比
- generalized Hermitian 路径在更多 case 下的稳定性
- 不同输入族下 `c_bands` 内部结构是否显著变化
- `QE -> VASP -> CP2K` 之间共性边界到底收在哪里

所以这份笔记的定位必须保持克制：

- 它是**真实执行入口验证**
- 不是最终 workload 结论

## 9. 当前最合理的下一步

基于这次真实运行，后面最自然的动作已经明确：

1. 跑一个比 `h2_tiny` 更有代表性的 `QE` case
   - 优先考虑已有 `docs/qe_inputs/` 里的更典型输入
   - 尽量拿到更有区分度的 `c_bands` / `fft` / `h_psi` 结构证据

2. 写一份 `QE phase-to-unit mapping v0`
   - 把这次真实出现的阶段名系统映射到硬件单元
   - 形成后续 `QE/VASP/CP2K` 三向对比的模板

3. 再开始 `CP2K` 的源码级主流程恢复
   - 不急着先跑
   - 先把其主流程、主 solver、主稠密/稀疏/FFT/grid 路线提出来

## 10. 一句话结论

当前主仓库里的 `QE` 路线已经能直接提供真实执行证据，而这次最小运行已经确认：

> `electrons -> c_bands -> (rdiaghg, h_psi, s_psi, g_psi, fft, calbec, add_vuspsi)` 这条多阶段循环体是真实存在的，因此后续硬件单元划分、LCW replay body 设计和 SystemC 全流程扩展都可以开始建立在真实执行链路上，而不再只是架构直觉。
