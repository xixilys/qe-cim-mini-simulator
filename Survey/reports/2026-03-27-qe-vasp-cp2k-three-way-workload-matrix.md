# 2026-03-27 QE / VASP / CP2K 三列负载与系统对象对照表

## 1. 目的

这份对照表只服务一个问题：

> 如果我们的 chip 顶层未来要尽量兼容 `QE`、`VASP`、`CP2K`，那么哪些对象是三者共享的，哪些对象只属于其中一类软件，哪些差异会直接决定顶层不能写成固定单流水。

这里不追求把三个软件的全部实现细节讲全，而是只保留会影响：

- `real system object`
- `chip-local object`
- `top-level command / scheduling`
- `kernel family coverage`

的部分。

## 2. 三列对照表

| 维度 | QE | VASP | CP2K |
|---|---|---|---|
| **主方法学对象** | plane-wave Kohn-Sham DFT | plane-wave Kohn-Sham DFT + PAW | GPW / GAPW，Gaussian basis + plane-wave/grid |
| **当前我们最贴近的内层对象** | `c_bands` / band-solver episode | electronic minimization / band update path | `Quickstep` SCF inner loop |
| **表示法中心** | reciprocal-space wavefunctions + projector/nonlocal + FFT | reciprocal-space wavefunctions + PAW/projector + FFT | Gaussian basis matrices + grid/FFT coupling |
| **FFT 角色** | 核心主链组成部分 | 核心主链组成部分 | 重要，但更多是 grid/Hartree/support 路径的一部分 |
| **projector / nonlocal role** | 很强，和当前 primitive 主线高度相关 | 很强，尤其 PAW/nonlocal 路径 | 有相关 operator/path，但不再是唯一中心对象 |
| **典型 solver / minimizer path** | Davidson / generalized eigensolver / band solver path | `Blocked-Davidson`, `RMM-DIIS`, 以及其他 `ALGO` 变体 | `DIAGONALIZATION` 或 `OT` |
| **显式 reduced eigensolver 重要性** | 很高 | 很高，但 solver path 可切换 | 重要但不是唯一核心，`OT` 会削弱其中心性 |
| **dense linear algebra 重要性** | 高 | 高 | 高，但常与 sparse/block path 混合出现 |
| **sparse / block-sparse 重要性** | 相对较低，不是主故事中心 | 相对较低，不是主故事中心 | 很高，`DBCSR` 是关键基础设施 |
| **自然并行结构** | k-point / band / panel / tile | k-point / band / `NSIM` batch / tile | basis block / matrix block / grid task / SCF branch |
| **更像固定 episode 还是任务图** | 最容易被表述为固定 episode | 介于 episode 与可切换 solver path 之间 | 更像任务图 / descriptor-driven multi-kernel orchestration |
| **和当前 `CIM Array Core + FFT + reduced solve` 的贴合度** | 最高 | 高 | 中等，必须扩成更一般的 kernel family |
| **对 chip 顶层的直接要求** | 可先用 `episode contract` 驱动 | 要支持 solver path 切换与 batched bands | 要支持多 kernel family、稀疏/块运算和 OT/DIAG 分支 |
| **对 command/ISA 的启发** | `episode descriptor` 已经能工作 | 需要 `solver mode + batch mode + projector/FFT path toggles` | 需要 `kernel descriptor + data-layout descriptor + branch mode` |
| **是否适合“单一固定深流水”** | 短期内最适合 | 勉强可做，但会开始变僵硬 | 不适合 |
| **是否适合“fixed engines + command processor + lightweight SIMD/vector companion”** | 适合 | 很适合 | 更适合 |

## 3. 这张表最重要的三个观察

### 3.1 `QE` 和 `VASP` 支持我们保留当前主资产

如果只看 `QE` 和 `VASP`，其实当前主资产完全没必要推翻：

- `FFT Companion`
- `CIM / projector-apply engine`
- `reduction / closure / reduced solve`
- `Near-SRAM Support Domain`

这说明我们不需要因为“想兼容更多软件”就立刻放弃当前 `QE` 主线。

### 3.2 `CP2K` 不是否定当前对象，而是在提醒顶层不能写死

`CP2K` 最重要的意义，不是说我们现在对象错了，而是它告诉我们：

- 当前对象更像一个重要 kernel family / subsystem family；
- 但 chip 顶层不能只允许这一族对象存在；
- 以后至少还要允许：
  - grid/FFT support path
  - sparse/block path
  - `OT` / `DIAGONALIZATION` 分支路径
  - 更一般的 basis/block-oriented batched commands

所以它主要推动的是 **top-level contract 的泛化**，而不是立刻推翻 `CIM-centered` 主核。

### 3.3 最该泛化的是顶层合同，不是马上把底层全做通用

这张表给出的最关键架构结论是：

> 真正需要先做“通用化”的，不是底层每一个 kernel，而是顶层的 command / descriptor / scheduling contract。

也就是说，更合理的动作顺序是：

1. 底层继续保留当前最有把握的固定引擎；
2. 顶层先从 `QE-only episode` 合同，升级成更一般的 `descriptor-driven subsystem`；
3. 再逐步决定未来要不要新增 sparse/block engine、OT support path 等扩展单元。

## 4. 对 chip 顶层设计的直接含义

如果这张表要直接转成设计语言，我建议当前这样改口：

### 4.1 不再把顶层定义为“完整固定流水”

不建议继续写成：

- 一个只服务 `QE c_bands` 的深流水硬件；
- 所有对象都必须顺着单一路径依次经过每个模块。

因为这会让 `VASP` 的 solver path 切换与 `CP2K` 的多 kernel family 很难接入。

### 4.2 改成“多引擎 + descriptor 调度”的 domain-specific cluster

更合理的顶层口径是：

- `Command / Descriptor Scheduler`
- `FFT engine`
- `Projector / apply engine`
- `Reduction / closure / reduced solve engine`
- optional future `sparse/block engine`
- lightweight `SIMD / vector companion`
- `Near-SRAM Support Domain`

### 4.3 当前最值得保留的两层合同

建议明确分成两层：

1. **Software-visible episode/subgraph contract**
   - `QE`: `c_bands episode`
   - `VASP`: minimization / band-update subgraph
   - `CP2K`: SCF inner-loop subgraph or kernel bundle

2. **Chip-visible kernel descriptor contract**
   - `FFT`
   - `project/apply/backproject`
   - `reduced build`
   - `closure/update`
   - `dense block op`
   - `sparse/block op`
   - `vector post/pre processing`

## 5. 当前最稳妥的收口

如果把这张表压成一句判断，那就是：

> `QE` 决定了我们当前最有把握的主线，`VASP` 说明这条主线仍具有很强延展性，`CP2K` 则迫使我们承认：未来兼容性的关键不在于继续把底层流水写死，而在于把 chip 顶层先升级成 descriptor-driven、multi-engine、可批处理的 domain-specific execution cluster。

## 参考来源

- VASP Wiki, Self-consistency cycle: https://www.vasp.at/wiki/index.php/Self-consistency_cycle
- VASP Wiki, ALGO: https://www.vasp.at/wiki/ALGO
- VASP Wiki, OpenACC GPU port of VASP: https://www.vasp.at/wiki/index.php/OpenACC_GPU_port_of_VASP
- CP2K, GPW method overview: https://www.cp2k.org/gpw
- CP2K input reference, SCF / OT: https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/SCF/OT.html
- CP2K input reference, SCF / DIAGONALIZATION: https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/DFT/SCF/DIAGONALIZATION.html
- CP2K / DBCSR project page: https://www.cp2k.org/dbcsr
- `Survey/reports/2026-03-27-vasp-cp2k-workload-and-chip-top-compatibility-note.md`
