# 2026-04-13 Advisor Cover Memo Template — SystemC System-Level DSE v0

## 使用说明

这份 memo 模板用于把完整 advisor pack 收口成一页“先读版”。它面向老师/PI，目标是：

- 先说清楚**推荐哪类系统架构 family**；
- 再说清楚**为什么这个 recommendation 可以信到什么程度**；
- 最后明确**下一步值不值得继续投入**。

这份 memo 不替代主报告；它应建立在以下上游材料已经齐备的前提下：

- executive summary one-pager
- advisor-facing report
- QE gold correctness gate 结果
- confidence / claims rubric

---

## Memo 标题
**Subject: System-Level DSE Recommendation for QE-Oriented Soft/Hardware Co-Design**

## Memo 正文模板

老师您好，

这轮我们基于当前 brownfield 的 SystemC/timed-functional 模型，对 `F1 / F2 / F3` 三类软硬件协同系统架构做了第一版 **system-level DSE**。这次工作的目标不是直接冻结 RTL 或板级参数，而是先回答：**哪一类系统架构最值得继续做**。

在统一 **QE CPU-only baseline** 的正确性约束下，我们当前推荐 **`TODO family`** 作为下一阶段主线。推荐的直接依据是：

- **correctness_status**：`TODO`
- **confidence**：`TODO`
- **speedup_to_convergence_range**：`TODO`
- **energy_to_convergence_range**：`TODO`

从系统分工上看，这个 family 最合适的原因是：

- **CPU 保留**：`TODO`
- **Device runtime 承担**：`TODO`
- **Hardware datapath 固化**：`TODO`

与另外两类架构相比：

- **`F1`**：`TODO why not`
- **`F3`**：`TODO why not`

需要特别说明的是，这轮结论是 **SCF-shell convergence scope** 下的系统级结论，而不是最终 RTL 定版结论。因此当前 projection 只报告区间，不报告无边界单点值；并且只有在 QE gold correctness gate 通过的前提下，projection-grade recommendation 才成立。

因此，这轮工作的实际价值是：

1. 先把系统架构族方向选对；
2. 给出一套可辩护的 CPU/device/datapath 分工；
3. 判断是否值得继续进入更细的 FPGA / RTL / memory-system 工程化验证。

如果认可当前推荐，我们建议下一步优先投入：

1. `TODO`
2. `TODO`
3. `TODO`

如果您希望，我们也可以在下一轮把当前推荐 family 继续下钻到：

- 更细的 faithfulness / tolerance 校准；
- DMA / buffer / resident 工程化 refinement；
- 更高 fidelity 的 runtime / interconnect 建模或 FPGA prototype。

谢谢。

---

## 附：一句话电梯版

> 当前 system-level DSE 的核心结论不是“RTL 已经定了”，而是：在 QE gold correctness gate 约束下，`TODO family` 是现阶段最值得继续做的系统架构族，它给出了 `TODO` 的 speedup-to-convergence 区间和 `TODO` 的 energy-to-convergence 区间，同时保留了最合理的 CPU/device 分工。
