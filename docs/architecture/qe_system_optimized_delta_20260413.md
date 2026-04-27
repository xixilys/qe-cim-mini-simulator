# 2026-04-13 QE System Optimized Delta Note v0

## 1. 文档定位

本文只回答一件事：**当前“优化后的 system-level 设计”到底相对主规范和旧的 brownfield 读法变了什么**。

它服务于 `WS0 / M0.2 optimized-system delta`，用于给后续 DSE、benchmark、FPGA 验证和汇报统一口径。

主要 grounding 来源：

- `model/qe_band_solver_model/README.md`
- `docs/architecture/system_design_master_spec_v0.md`
- `docs/architecture/host_managed_full_scf_architecture_v1_20260409.md`
- `model/qe_band_solver_model/include/types.hpp`
- `model/qe_band_solver_model/src/{architecture_template,host_scf,fpga_orchestrator,interconnect,episode_controller,cluster_graph_executor,cluster_c_hardware_diag,dft_hybrid_system}.cpp`
- `model/qe_band_solver_model/sc_main.cpp`

## 2. 一句话 delta

当前 runnable model 已经从“**descriptor/replay/body catalog 为主叙事的系统草图**”前移到“**QE-facing、host-managed full-SCF shell demo**”，并且把 phase-1 的系统主接口冻结为 **Host-visible request / completion objects**，把 replay/body/LCW 明确降为**内部 lowering**。

因此，这次优化不是简单调了几个 proxy 参数，而是把：

- **系统对象**
- **public control contract**
- **runtime/accounting boundary**
- **family-template policy wiring**

都做成了更接近后续 DSE / FPGA / benchmark 可直接复用的形态。

## 3. 本轮优化后，真正变化了什么

| 维度 | 之前更像什么 | 现在更像什么 | 当前代码/文档锚点 |
| --- | --- | --- | --- |
| 系统主抽象 | `descriptor -> replay body -> LCW` 驱动的系统草图 | `HostSCF -> FPGAOrchestrator -> ChipTop` 的 host-managed full-SCF shell | `README.md`, `dft_hybrid_system.cpp` |
| 对外接口 | cluster/replay 读法容易被当作系统主接口 | 对外冻结为 `ResidentSetDesc / BandBatchDesc / ScfIterationRequest / DiagPolicy / CompletionSummary` | `README.md`, `types.hpp`, `host_scf.cpp` |
| 设备运行时定位 | 更像 replay 调度中层 | 明确成 **thin device runtime / firmware bridge**，负责 preload、DMA、fallback、completion 汇总 | `README.md`, `fpga_orchestrator.cpp` |
| 互连/accounting | 行为上存在，但系统级边界不够强 | `Interconnect` 明确区分 control / DMA / completion 三类事务，并用 TLM-style `b_transport` 记账 | `interconnect.cpp` |
| inner-hotpath 执行 | `Cluster A/B/C/D` 更像直接暴露给系统层 | `Cluster A/B/C/D` 继续存在，但只作为 chip 内部 datapath 执行器 | `cluster_graph_executor.cpp`, `README.md` |
| family DSE 支架 | `F1/F2/F3` 更多还是概念层 | family 已进入 `SystemRunConfig -> ArchitectureTemplateConfig -> Request/Completion/Report` 主路径 | `architecture_template.cpp`, `types.hpp`, `sc_main.cpp` |
| 结果导出 | 以 log/文档解释为主 | 已支持 canonical candidate JSON，能进入 QE gold lane 和 family DSE sweep | `README.md`, `sc_main.cpp` |

## 4. 哪些假设被移动了

### 4.1 从“replay/body 是 planning 主接口”移动到“replay/body 是内部 lowering”

主规范里 `descriptor -> replay body -> LCW` 仍然成立，但在当前 optimized runnable model 里：

- phase-1 planning / DSE / FPGA integration 不再直接以 replay/body 当 public API；
- 真正对 Host 和 benchmark lane 可见的是 request/completion 五对象；
- replay/body/LCW 继续保留为 chip 内实现与 legacy 兼容路径。

这一步把**系统主接口**和**内部实现层次**分开了。

### 4.2 从“完整 demo = 尽快覆盖所有热点硬化”移动到“完整 demo = QE shell closure”

当前更稳的含义是：

- Host 继续保留 outer `SCF`、`rho -> Veff`、`mix_rho`、收敛判断；
- device runtime 负责 resident / DMA / fallback / completion；
- chip 负责 inner hotpath；
- 用户视角上仍然是一个完整 QE-facing shell。

因此，“完整 QE demo”**不再等价于**“第一版就把所有热点都硬接管”。

### 4.3 从“`cdiaghg` 完全硬化是默认前提”移动到“hardware-first proxy + formal fallback”

`Cluster C` 现在是：

- hardware-first diagonalization proxy；
- 但 `DiagPolicy`、`ClusterCHardwareDiag`、`FPGAOrchestrator` 已经把 **force CPU / dimension overflow / condition overflow / spill / crossover losing** 都写成了正式 fallback 合同。

这使得 `diag` 不再是模糊的“以后再说”，而是当前系统级协同边界里最明确的一条合同。

### 4.4 从“resident / spill 是隐式背景条件”移动到“resident-fit 是显式决策变量”

`EpisodeControllerState` 现在显式暴露：

- `resident_budget_kib`
- `estimated_resident_footprint_kib`
- `estimated_spill_kib`
- `resident_fit`
- `spill_active`

这意味着 family 比较不再只是算子 proxy 差异，而是开始包含真正的 **resident / spill / fallback** 系统行为。

### 4.5 从“family tag 只是命名”移动到“family tag 真实改动 request/runtime/report 行为”

`F1/F2/F3` 现在不是 report 标签，而是实际驱动：

- `offload_scope`
- `resident_policy`
- `diag_policy`
- `confidence_label`
- `resident_budget_scale`
- `device_diag_max_dim`
- `enable_device_fft`

因此 family 选择已经能改变系统行为，而不只是改变汇报文案。

## 5. 当前 authoritative public control objects

phase-1 应以以下五个对象作为 authoritative public contract：

| 对象 | 作用 | 主要 owner |
| --- | --- | --- |
| `ResidentSetDesc` | 定义 resident projector/support-grid/potential-slice 及 preload/reuse 预算 | `HostSCF` 生成，`FPGAOrchestrator` 执行 |
| `BandBatchDesc` | 定义本次活动 wave batch 的 band/panel 组织和 DMA 规模 | `HostSCF` 生成，`FPGAOrchestrator` 搬运 |
| `DiagPolicy` | 定义 device-vs-host `diag` 边界 | `HostSCF` 生成，`Cluster C + FPGAOrchestrator` 共同执行 |
| `ScfIterationRequest` | Host 到 device runtime 的主请求对象 | `HostSCF -> FPGAOrchestrator` |
| `CompletionSummary` | device runtime 回给 Host 的主完成对象，带 runtime/accounting/fallback 摘要 | `FPGAOrchestrator -> HostSCF` |

对应地：

- `EpisodeDescriptor`
- `EpisodeControllerState`
- `EpisodeResult`
- replay/body/LCW

都应视为 **internal lowering / internal execution state**，而不是 phase-1 的上层 planning 接口。

## 6. 这次变化对 `F1/F2/F3` 的影响

### 6.1 不是“已经重排 family 排名”

当前代码和文档**还没有**直接证明：

- `F2` 一定优于 `F1`
- 或 `F3` 已经可以升级为主线推荐

因此，这次优化**不是直接给出新的最终 family ranking**。

### 6.2 但它确实改变了“哪些 family 已经 decision-grade”

更准确地说，这次优化让 family search space **不再完全对称**：

- `F1`：现在是更扎实的 conservative / convergence-first family；
- `F2`：现在是更扎实的 balanced primary candidate；
- `F3`：family 钩子已经存在，但仍明显更依赖 proxy、spill、fallback 和后续 calibration。

所以这次变化对 family 的影响是：

1. **先改变 family 的成熟度与可判定性**；
2. **再影响 family 内部参数调优**。

因此：

- 对 `F1/F2`，这次优化更像是把它们推进成 **phase-1 first-class candidates**；
- 对 `F3`，这次优化更像是把它保留为 **conditional / exploratory family**；
- 具体 `band_batch / row_block / resident_budget_scale / diag threshold` 怎么调，仍属于下一步 DSE 的参数层工作。

### 6.3 当前推荐解释

对接后续 plan 时，建议统一写成：

> 本轮 optimized system-level design **主要改变的是 family comparison 的 grounding 与 maturity，不是立即冻结新的最终排序**。当前应把 `F1/F2` 作为 decision-grade primary families，把 `F3` 视作仍需额外证据封口的条件性候选。

## 7. 现在哪些 claim 更扎实，哪些仍是 provisional

### 7.1 更扎实的 claim

| 现在更扎实的 claim | 为什么 |
| --- | --- |
| 当前系统对象是 `Host + Device Runtime + Chip` 三层混合系统 | README、主规范、`dft_hybrid_system.cpp`、`host_scf.cpp`、`fpga_orchestrator.cpp` 已经一致 |
| phase-1 public control contract 应该是五个 request/completion objects | README、`types.hpp`、`host_managed_full_scf_architecture_v1_20260409.md` 一致 |
| QE shell closure 已经是 runnable model 的主路径 | `HostSCF::run_full_flow` + `DFTHybridSystem::run_full_flow` + README shell view |
| control / DMA / completion 可以按系统边界记账 | `interconnect.cpp` + `CompletionSummary` + `SCFRunReport` |
| resident reuse / spill / host-assist/fallback 已经进入主路径统计 | `episode_controller.cpp`, `fpga_orchestrator.cpp`, `types.hpp`, `sc_main.cpp` |
| family policy 已经真正落在 runtime 行为和 report 字段里 | `architecture_template.cpp`, `host_scf.cpp`, `fpga_orchestrator.cpp` |

### 7.2 仍然 provisional 的 claim

| 仍然 provisional 的 claim | 原因 |
| --- | --- |
| `CPU+FPGA` 可对 `CPU+GPU` 实现 `>2x` end-to-end 且 whole-node power 更低 | 这是当前 plan target，不是 repo 已证明事实 |
| `F3` 值得升级为 phase-1 主线 | 仍受 `Cluster C` proxy、spill/fallback、board calibration 约束 |
| 当前 `diag` 路径已经代表最终 device-heavy diagonalization 方案 | 目前仍是 hardware-first proxy + formal host fallback |
| whole-node power claim 已可直接用于对外结论 | 目前只有 power-boundary freeze 需求，没有同等强度的实测封口 |
| `VASP / CP2K` 已与 `QE` 同等 grounded | README 已明确：本地 executable anchor 仍是 QE |
| 这套 system model 已足够支撑 ASIC 级结论 | 目前最多支撑 system-level DSE / FPGA-facing architecture selection，不支撑最终 ASIC PPA 宣称 |

## 8. 对 spec 更新的直接含义

这份 optimized delta 应直接推动后续 spec/plan 统一采用下面的写法：

1. **外部 contract** 用五个 public objects 表达；
2. `descriptor -> replay body -> LCW` 保留为 **internal lowering**；
3. “完整 QE demo”定义为 **QE shell closure**；
4. `F1/F2` 作为 phase-1 decision-grade families；
5. `F3` 继续保留，但所有推荐语气都必须带 conditional / exploratory 限定；
6. 任何 CPU+GPU superiority、whole-node power、F3 推荐、full-device diag 的对外 claim，都仍需要后续 benchmark / observability / FPGA 校准来封口。

## 9. 当前建议的一句话口径

> 这次 optimized system-level redesign 的核心，不是把系统直接推成 device-heavy 胜负结论，而是把 QE-facing host-managed full-SCF contract、family-template policy wiring 和 runtime accounting boundary 先做实；它首先提升的是 `F1/F2/F3` 比较的可信度与可执行性，其中 `F1/F2` 已进入 decision-grade 区间，而 `F3` 仍属条件性候选。
