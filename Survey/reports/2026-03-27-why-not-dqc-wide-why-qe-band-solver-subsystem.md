# 2026-03-27 为什么当前不继续停留在更宽的 DQC-wide cut，而要收口到 QE-connected band-solver subsystem

## 1. 这份短对照要回答什么

这份笔记只回答一个当前非常关键、但又必须先在本地材料里收紧的问题：

- 为什么像 `Liu et al. 2023` 这种更宽的 `DQC-wide / FFT + loops` 切法，**对我们现在这条主线来说还不够合适**；
- 为什么我们当前应该继续把系统对象收口到 **`QE-connected band-solver subsystem`**，并进一步以 **`c_bands episode`** 作为执行与验证合同。

这里不是否定 `Liu 2023` 的价值。相反，这篇文章已经很有力地证明了：

> `real software + heterogeneous mixed system + runtime/offload + memory-centric accelerator`

这种系统叙事本身是成立的。

当前真正要做的判断是：**在这条大方向成立的前提下，我们自己的 cut 应该切多宽。**

## 2. 先说结论

基于当前主仓库文档、`Liu 2023` 结构化精读，以及已经冻结到 `Host / QE + FPGA / runtime + Chip` 的系统定义，当前最稳妥的结论是：

> 我们现在不应该继续停留在更宽的 `DQC-wide` cut，而应该继续收口到 `QE-connected band-solver subsystem`。

更具体地说：

1. `Liu 2023` 证明了“真实软件连接的混合系统对象”是合理的；
2. 但它的工作负载边界是围绕 `FFT + time-consuming loops` 的更宽对象，适合回答“PIM 如何广义加速 quantum chemistry simulation”；
3. 我们当前要解决的不是这个宽问题，而是一个更窄、更需要数值合同冻结的问题：
   - `QE` 里的 `c_bands` 主链到底能否被定义成一个稳定的异构子系统；
   - 这个子系统的 chip-local 主核到底是不是 `CIM Array Core + Near-SRAM Support Domain + Digital / FFT Companions`；
   - `Adjoint-Aware Projector Primitive` 相对 `GEMM baseline` 和 `transpose-aware macro baseline` 的收益，能否沿着这个子系统对象被清晰证明。

所以当前阶段最重要的不是把系统切得更宽，而是把 **对象、合同、primitive、baseline 与证据链继续收紧**。

## 3. `Liu 2023` 给了我们什么，没给我们什么

### 3.1 它给我们的核心帮助

`Liu 2023` 最重要的帮助，不是替我们直接决定最终 cut，而是帮我们确认了下面这件事：

- 真实系统对象完全可以不是“单个 kernel accelerator”；
- 它可以是 `CPU/Host + accelerator + runtime + real scientific software` 的混合系统；
- 软件侧可以保留真实应用入口，硬件侧抓住主热点阶段；
- 评价也可以围绕系统级速度、能耗、利用率，而不只是孤立峰值算子。

这对我们非常重要，因为它直接支撑了用户已经明确纠正过的那一点：

> 真实系统对象不是单独芯片，而是一个 `Host + FPGA + Chip` 混合系统。

换句话说，`Liu 2023` 让“我们不是只在讲 chip”这件事更站得住。

### 3.2 它没有替我们解决的核心问题

但 `Liu 2023` 没有替我们解决下面这件事：

- **在真实软件连接的混合系统前提下，我们自己的最佳边界到底是更宽，还是更窄。**

它的回答偏向：

- 以 `QE / quantum chemistry` 为真实软件锚点；
- 抓 `FFT + loops` 这类宽热点；
- 通过 heterogeneous PIM + runtime 去覆盖较大的软件阶段。

而我们现在更需要回答的是：

- 如果我们的主创新点已经逐渐从“通用 `GEMM-CIM + transpose`”收口到 `Adjoint-Aware Projector Primitive`；
- 如果我们的系统已经冻结成 `Host / QE + FPGA / runtime + Chip`；
- 如果 chip 内部也已经冻结成 `CIM Array Core + Near-SRAM Support Domain + Digital Companions + explicit FFT Companion`；

那我们到底应不应该继续把故事维持在 `FFT + loops` 这种更宽的层面？

当前答案是：**不应该。**

## 4. 为什么更宽的 DQC-wide cut 对我们现在不够合适

### 4.1 它会稀释当前最明确的创新主线

从主仓库时间线看，当前最明确、最连续、也最有可能形成电路/系统共振的主线已经不是“广义 FFT + loops 加速”，而是：

- workload 入口锚在真实 `QE`；
- 系统对象收口到 `QE-connected band-solver subsystem`；
- primitive 中心从 `transpose` 转向 `Adjoint-Aware Projector Primitive`；
- 执行合同收口到一个明确的 `c_bands episode`。

如果现在重新回到更宽的 `DQC-wide` cut，就会出现一个直接问题：

- `FFT`、一般 loop、控制路径、runtime 灵活性，会重新成为叙事中心；
- 而 `projector primitive`、`generalized Hermitian`、`S_sub`、`reduced build / closure` 这些真正需要冻结的点，反而会被淹没。

也就是说，更宽的 cut 会让我们重新落回“广义应用加速”的说法，而不是继续巩固当前已经显出来的 **domain-specific accelerator / digital processing** 主线。

### 4.2 它会让 chip-local 对象重新变糊

用户已经强调过，真实系统对象是混合系统；但这并不意味着 chip-local 对象也应该无限变宽。

当前我们对 chip-local 对象其实已经有了相对清楚的定义：

- `CIM Array Core`
- `Near-SRAM Support Domain`
- `Digital Companions`
- explicit `FFT Companion`

并且这四部分不是随便拼起来的，而是围绕 `c_bands episode` 的本地闭环关系组织的。

如果把 cut 拉回 `DQC-wide`：

- chip 侧到底是在承接“band solver 主链”，还是“更大范围的 FFT + loops 杂合热点”；
- `FFT Companion` 到底是第二主线，还是主对象本身；
- `Near-SRAM Support` 是在支撑 `CIM Array Core`，还是在替代更大的 near-memory execution shell；

这些本来已经开始变清楚的问题又会重新模糊。

### 4.3 它会把数值合同和验证合同同时做宽

当前项目最难冻结、但也最该冻结的部分，不在“应用热点是不是够多”，而在：

- generalized Hermitian 路径如何稳定进入系统合同；
- `S_sub` 不能忽略这一点如何进入 primitive 和架构；
- `projector primitive` 的收益到底怎么相对 `GEMM baseline` 与 `transpose-aware macro baseline` 量化；
- `c_bands episode` 的端到端时间 / 能耗 / 数据移动证据链怎么建立。

如果系统 cut 做得更宽，验证负担会立刻变成两层放大：

1. **数值负担变宽**：不仅要解释 band-solver 子链，还要解释更大范围 `FFT + loops` 的协同与边界；
2. **证据负担变宽**：不仅要证明一个主线子系统有效，还要证明广义大阶段切法本身公平且优于其他宽系统方案。

这会把“先冻结主对象”的任务推迟，而不是帮助它。

### 4.4 它会让 baseline ladder 更难公平

当前最危险的未冻结项之一，本来就是 baseline 问题。时间线已经明确指出：

- primitive 相对 `GEMM baseline` 与 `transpose-aware macro baseline` 的成本/收益差异还没收住。

如果现在继续讲更宽的 `DQC-wide` cut，就需要同时面对更多层 baseline：

- primitive baseline
- macro baseline
- band-solver subsystem baseline
- 更宽的 `FFT + loops` mixed-system baseline
- 甚至 GPU / CPU + library / software-stack 级 baseline

这不是说这些 baseline 永远不做，而是说：

> 在当前主线还没冻结时，过早把 baseline 梯子拉得太高、太宽，会直接削弱论证质量。

### 4.5 它更像“证明可以做系统”，而不是“冻结我们现在该做的系统”

`Liu 2023` 这样的宽 cut 更擅长回答：

- 真正的软件连接 mixed system 能不能成立；
- PIM/runtime 在大热点阶段上有没有潜力；
- 较宽系统级 speedup/energy story 能不能讲通。

但我们当前阶段更需要的是另一类判断：

- 我们自己的 **对象是否已经收敛到足够可落地**；
- 我们的 chip-local 设计是否和真实 `QE` 路径对得上；
- 我们的 primitive 是否正好服务于这个对象；
- 我们能不能沿着这个对象建立更紧的证据链。

宽 cut 对“证明可以做系统”是有帮助的；但对“冻结我们现在该做的系统”帮助有限。

## 5. 为什么现在更应该收口到 QE-connected band-solver subsystem

### 5.1 因为它和当前主创新点是同向收敛的

当前主仓库里最连续的一条主线是：

- 从 `QE` 真实 workload 出发；
- 从 generalized Hermitian / `S_sub` 的存在出发；
- 从 `transpose` 机制继续抬升到 `Adjoint-Aware Projector Primitive`；
- 再把 primitive 落到一个明确的异构系统对象上。

`QE-connected band-solver subsystem` 正好处在这条链路的中间：

- 向上能连到真实 `QE`；
- 向下能连到 primitive、macro 和 chip 架构；
- 在中间能自然承接 `Host -> FPGA -> Chip -> closure -> Host` 的执行合同。

这比更宽的 `DQC-wide` cut 更符合当前已有积累。

### 5.2 因为 `c_bands episode` 已经是一个可执行合同，而不只是概念边界

当前系统不是停留在“模块框图”阶段，而是已经有了：

- `Host / QE + FPGA / runtime + Chip` 分层；
- `c_bands episode` 的 request/response 合同；
- chip 内部 `operator / FFT / aggregation / closure / update` 的 transaction 关系；
- `SystemC v0` timed-functional demo。

这意味着：

> `QE-connected band-solver subsystem` 已经不是一句抽象口号，而是一个正在被执行语义和模型支撑的对象。

反过来说，当前更宽的 `DQC-wide` cut 在我们这里还没有被同等程度地事务化、合同化、可执行化。

### 5.3 因为它更适合冻结“真实系统对象”与“chip-local 对象”的分工

用户已经明确指出：

- 真实系统对象：`Host + FPGA + Chip` 混合系统；
- chip-local 对象：不是完整软件，而是围绕特定主链组织的局部执行域。

`QE-connected band-solver subsystem` 正好允许我们把这两个层次分开：

- **真实系统对象**：`Host / QE + FPGA / runtime + Chip`
- **chip-local 对象**：`CIM Array Core + Near-SRAM Support Domain + Digital Companions + explicit FFT Companion`

这个二层划分当前已经清楚；如果 cut 变宽，二者之间又容易重新缠在一起。

### 5.4 因为它更利于建立“primitive -> subsystem -> episode”证据链

现在最需要建立的，不是一条宽泛的“全系统都会更快”的口号链，而是更紧的一条：

1. `Adjoint-Aware Projector Primitive` 为什么比 `GEMM` / `transpose-aware` 宏更合适；
2. 这个 primitive 为什么自然落到 `CIM Array Core + Near-SRAM Support` 这一组 chip-local 对象上；
3. 这组对象为什么能缩短 `c_bands episode` 的时间/能耗/数据移动；
4. 这个 `episode` 改善如何回到真实 `QE` 的系统证据里。

`QE-connected band-solver subsystem` 正好是这条证据链的中间层。没有这层，primitive 会太孤立；再宽很多，证据链又会过松。

### 5.5 因为它更符合“先冻结主线，再决定是否外扩”的长期 IC 节奏

用户已经明确说过，这不是一个应该优先围绕投稿包装的短周期工作，而是一个长周期 IC 项目。

对这种项目来说，更合理的节奏通常不是：

- 先把系统切得尽可能宽，再试图证明所有部分都成立；

而是：

- 先冻结一个最有把握的、能上下贯通的主对象；
- 让 primitive、chip、runtime、系统合同先在这个对象上闭合；
- 之后再判断是否向外扩展到更宽的软件阶段。

当前 `QE-connected band-solver subsystem` 明显更像这个“可冻结主对象”。

## 6. 当前最该保持的判断

基于现有材料，当前最该保持的判断不是“我们已经最终证明更宽 cut 不行”，而是下面这组更谨慎的结论：

### 6.1 可以保留的判断

- `Liu 2023` 成功证明了真实软件连接 mixed-system 路线的合法性；
- 我们不应该回到“只讲孤立芯片 / 单 kernel”的叙事；
- 更宽的 `FFT + loops` cut 未来仍然可能成为外扩方向；
- explicit `FFT Companion` 依然需要保留在当前系统图和执行机制里。

### 6.2 当前不该做的事

- 不要把当前主线重新包装成宽泛的 `DQC-wide` 应用加速；
- 不要在 primitive / subsystem / episode 还没收住时，把系统边界重新做大；
- 不要过早把 baseline / KPI / 证据链扩展到一个我们还没法公平守住的宽系统对象。

### 6.3 当前应继续推进的方向

当前最合理的推进方式是：

1. 继续把 `QE-connected band-solver subsystem` 作为主系统对象；
2. 继续把 `c_bands episode` 作为执行与验证合同；
3. 继续围绕 `Adjoint-Aware Projector Primitive` 收紧 primitive-level 论证；
4. 把 `FFT Companion` 的角色进一步定量化，但不让它重新吞掉主故事；
5. 在这个对象上逐步冻结 KPI、baseline ladder 和 end-to-end 证据链。

## 7. 一句话收口

如果用一句话总结当前阶段的判断，那就是：

> `Liu 2023` 帮我们证明了“真实软件连接的混合系统”这条大路是对的；但对我们现在这条主线来说，更重要的不是把路继续铺宽，而是把对象继续收口到一个已经开始具备 `primitive -> architecture -> episode contract` 闭环的 `QE-connected band-solver subsystem`。
