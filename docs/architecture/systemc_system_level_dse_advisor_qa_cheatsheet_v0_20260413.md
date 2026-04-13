# 2026-04-13 Advisor Q&A Cheatsheet — SystemC System-Level DSE v0

## 1. 文档定位

这份 cheatsheet 用于 team 在老师汇报或阶段答辩时统一口径。它不是新的技术规范，而是把已有 family matrix、report template、confidence rubric 与 advisor-pack checklist 收成一份口头答辩辅助稿。

适用场景：

- 向老师解释为什么 system-level DSE 先做 family 选型
- 解释为什么当前只报 `speedup_to_convergence_range` / `energy_to_convergence_range`
- 回答正确性、confidence、CPU/device 分工、以及后续工程化的追问

## 2. 开场 20 秒版本

> 我们这版工作的目标不是直接冻结 RTL，而是先在统一 QE gold correctness gate 下比较 `F1 / F2 / F3` 三类系统架构族，判断哪一类更值得继续做。所有结论都按 SCF-shell convergence scope 汇报，并且 projection 只报区间，不报无边界单点值。

## 3. 高频问题与建议回答

### Q1. 为什么不先做 DMA / buffer / HBM 预算优化？
**建议回答**
> 因为当前阶段的关键风险不是工程参数没有调到最优，而是系统架构族选错。DMA/buffer 优化是在某一类架构被证明值得继续做之后再细化的工程问题。第一版 system-level DSE 先回答哪类 CPU/device/datapath 分工更有前景。

### Q2. 为什么你们只比较 `F1 / F2 / F3`，没有把更灵活的可编排架构一起纳入？
**建议回答**
> 因为 brownfield 现状更适合比较三类 grounded family：保守、平衡、激进。更通用的 coarse-grain programmable fabric 作为 `F4` 已经记为 phase-2 exploratory，但当前 repo 还不支持把它作为 v1 等价候选架构来做公平比较。

### Q3. 为什么推荐 `F2` 而不是 `F1` 或 `F3`？
**建议回答模板**
> `F1` 太保守，只能证明浅 offload 是否够用；`F3` 更激进，但容易把复杂度、fallback 和 resident/spill 风险引入主线。`F2` 通常是我们最希望看到的平衡点：保留 Host 管 outer SCF 与异常路径，同时把高复用、可流水的 inner hotpath 固定在 device datapath 中。最终是否真的推荐 `F2`，还要以 gold correctness 与 projection range 为准。

### Q4. 为什么 speedup / energy 只报 range，不报精确数值？
**建议回答**
> 因为当前是 system-level proxy 模型，不是最终 RTL 或板级实测。为了避免过度承诺，第一版 projection-grade 结论只报 `speedup_to_convergence_range` 和 `energy_to_convergence_range`，并且同时给 `confidence` 与 `assumption_set_id`。

### Q5. 你们怎么保证这个模型不是只会讲故事？
**建议回答**
> 我们把正确性单独做成 QE gold gate。只有在 QE CPU-only baseline 下，最终 `total energy`、`residual threshold` 状态和最终收敛状态都对齐，结论才允许进入 projection-grade。否则最多只能保留 ranking-grade 或 exploratory 观察。

### Q6. portability lane 的作用是什么？
**建议回答**
> portability lane 不是用来替代 QE gold correctness，而是用来检查架构族在不同 workload trait 下是否稳定。它能帮助判断某个 family 是否只对单一 QE case 有效，但它不能单独支撑主推荐。

### Q7. 如果 gold correctness 过不了，是否整个 DSE 就没价值？
**建议回答**
> 不是完全没价值，但价值会降级。如果 gold gate 失败，我们仍然可以保留一些 ranking-grade 观察，用来判断哪里可能有潜力；但不应该把它包装成老师可以直接采纳的 projection-grade 推荐。

### Q8. 现在这套结论能支持走到哪一步？
**建议回答**
> 当前结论足以支持下一阶段系统架构方向选择，也能支持是否值得继续进入 FPGA / 更高 fidelity 建模。但它还不该直接用于 RTL 参数冻结、板级功耗承诺或 DMA/buffer 最终预算决策。

## 4. CPU / Device 分工答辩口径

### CPU 侧
优先强调：

- outer SCF loop
- `rho -> Veff`
- mixing / convergence
- case orchestration
- fallback decision

### Device runtime 侧
优先强调：

- resident management
- descriptor / DMA / completion
- host assist / fallback bridge
- family policy 到内部 datapath 的映射

### Hardware datapath 侧
优先强调：

- `h_psi / s_psi`
- `H_sub / S_sub`
- refresh / residual
- `diag` 是策略敏感路径，不要求在 v1 完全硬化

## 5. 被追问时不要说的句子

以下说法应避免：

- “我们已经证明最终 RTL 一定最优。”
- “这个数就是最终板级 power。”
- “只要 VASP / CP2K 趋势对，就能说明 QE 也没问题。”
- “虽然 gold gate 没过，但我觉得推荐还是成立。”

## 6. 被追问时最好补充的证据

如果老师继续深问，优先补这几类证据：

1. QE gold correctness table
2. family ranking summary
3. confidence / claims rubric
4. one-page executive summary

## 7. 汇报结束时的收口句式

> 所以当前这套 system-level DSE 的价值，不是直接告诉我们 RTL 该怎么收敛，而是先把系统架构族选对，并用 QE gold correctness 把这个推荐约束住。只有当这个 family 在 correctness、confidence 和 convergence-scoped projection 上都站得住，我们才值得继续往工程实现里投入。
