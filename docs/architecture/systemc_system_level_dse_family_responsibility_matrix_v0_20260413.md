# 2026-04-13 SystemC System-Level DSE Architecture Family Responsibility Matrix v0

## 1. 文档定位

这份文档服务于第一版 system-level DSE 的 advisor-facing/bootstrap 叙事：

- 把 `F1 / F2 / F3` 的职责边界固定到 `Host CPU -> Device Runtime -> Hardware Datapath` 三层；
- 让后续 DSE 报告用统一口径解释“为什么推荐某个 family”；
- 避免把内部 `Cluster A/B/C/D` 直接当成系统级主接口。

本矩阵与以下文档保持一致：

- [/Volumes/remote/phd/year_2/project/dft加速/.omx/plans/prd-systemc-system-level-dse.md](/Volumes/remote/phd/year_2/project/dft加速/.omx/plans/prd-systemc-system-level-dse.md)
- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/host_managed_full_scf_architecture_v1_20260409.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/host_managed_full_scf_architecture_v1_20260409.md)

## 1.1 与团队其它交付物的关系

这份矩阵主要给以下两类后续交付做统一口径：

- family-template / runtime-mapping lane：把 `F1 / F2 / F3` 映射到同一 host/device/datapath 合同；
- advisor-facing report lane：在汇报里用一致语言解释推荐 family 的 CPU/device 分工与 `diag` 路径。

如果后续 sweep 或 correctness harness 发现某个 family 的有效数值路径发生变化，本矩阵不应被静默沿用，而应同步更新 `algorithm_contract_deviation` 标记。

## 2. 固定比较合同

`F1 / F2 / F3` 做系统级比较时，默认固定以下条件：

- 相同 input case
- 相同 pseudopotential
- 相同 convergence threshold
- 相同 outer SCF accounting boundary
- 相同 QE gold correctness gate

允许变化的只有：

- CPU / device 分工
- offload scope
- runtime 调度路径
- diag 策略
- resident / spill 策略

如果某个 family 改变了有效数值路径，必须显式标记：

- `algorithm_contract_deviation = yes`
- 对应结论自动降级 confidence

## 2.1 当前已落地的 brownfield 实现锚点

当前 family-level 架构模板已经在 runnable model 里有明确落点：

- family resolver 接口：`/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/architecture_template.hpp`
- family resolver 实现：`/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/architecture_template.cpp`
- family config 类型：`/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/types.hpp` 中的 `ArchitectureTemplateConfig` 与 `SystemRunConfig`

当前代码里已落地的默认模板标签为：

- `F1 -> HostHeavySingleHotpath`
- `F2 -> BalancedHybrid`
- `F3 -> DeviceHeavyFullInnerLoop`

因此这份责任矩阵不再只是抽象规划文档，而是可以直接对照当前 brownfield family-template 实现来解释。

## 3. Family 责任矩阵

| Family | 系统定位 | Host CPU 负责 | Device Runtime 负责 | Hardware Datapath 负责 | `diag` 路径 | DSE 主要回答的问题 |
|---|---|---|---|---|---|---|
| `F1` | Host-heavy / Single-hotpath | outer SCF、`rho -> Veff`、mix/convergence、`diag`、异常路径 | resident preload、batch DMA、最小 completion 汇总、有限 spill 处理 | `h_psi / s_psi`、`H_sub / S_sub` reduced build | `cpu_only` 默认 | “只把最热主链放硬件，是否已经足够产生系统级加速？” |
| `F2` | Balanced hybrid / Multi-operator pipeline | outer SCF、`rho -> Veff`、mix/convergence、异常路径、最终收敛判断 | resident reuse / spill、descriptor queue、DMA overlap、device-first `diag` fallback 桥接、completion/perf 汇总 | `h_psi / s_psi`、`H_sub / S_sub`、refresh/residual、device-first `diag` companion | `device_first_fallback` 默认 | “适度多算子协同，能否在正确性和复杂度之间取得最好平衡？” |
| `F3` | Device-heavy / Full inner-loop offload | outer SCF、最终收敛判断、不可避免的异常 / 超阈值 fallback | 深度 resident 管理、更激进的 launch / completion 协调、host assist / re-import、复杂 spill 与 fallback 桥接 | 尽可能覆盖完整 inner loop；`Cluster A/B/C/D` 全部作为内部实现候选 | `aggressive_device` 默认，超阈值 fallback | “更深 offload 是否真的带来更高 `speedup_to_convergence` / 更低 `energy_to_convergence`，还是被复杂度和回退吞掉收益？” |

## 4. 统一解释口径

### 4.1 Host CPU

所有 family 中，Host CPU 都继续保留：

- 上层软件语义与 case 组织
- outer SCF loop
- `rho -> Veff`
- mixing / convergence
- 报告汇总与 family 排序解释

差异只在于：Host 是否还要承担 `diag` 和更多 inner-loop 子路径。

### 4.2 Device Runtime

所有 family 中，Device Runtime 都是薄协调层，而不是完整软件副本：

- 接收 host-visible request
- 管理 resident / DMA / completion
- 把 family 策略映射到内部 datapath 路径
- 向 Host 返回 correctness/perf 所需摘要

差异只在于：Runtime 是否只做轻量桥接，还是承担更复杂的 fallback / spill / overlap 协调。

### 4.3 Hardware Datapath

所有 family 中，Hardware Datapath 都只表现为设备内实现，不直接暴露 cluster 语义给上层报告。

- `F1`：最小 hotpath datapath
- `F2`：主候选多算子 datapath
- `F3`：更深 inner-loop datapath

## 5. Advisor-facing 默认叙事角色

| Family | 默认叙事角色 | 报告中的典型作用 |
|---|---|---|
| `F1` | Conservative baseline | 证明“浅 offload”是否已经足够；也是所有 projection 的保守下界参照 |
| `F2` | Primary candidate | 默认首选推荐对象；如果 correctness 与 projection 都稳定，优先作为老师汇报主线 |
| `F3` | Stretch candidate | 用来检验“更激进设备化”是否值得继续；若收益不稳定，应作为 exploratory 结果呈现 |

## 6. v1 不应从本矩阵直接推出的结论

这份责任矩阵不用于直接冻结以下工程参数：

- DMA width
- buffer depth
- BRAM / URAM / HBM 最终预算
- RTL 资源/频率/功耗最终值
- board-level power claim

这些内容只能在 family 排序明确之后，再进入后续工程化阶段。
