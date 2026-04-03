# QE clustered v1 分 cluster 设计分析与审查（2026-04-02）

## 1. 目的

这份文档用于审查当前 `QE clustered v1` 分 cluster 设计的：

- 完成度；
- 设计合理性；
- 兼容性策略是否成立；
- 跨文档合同是否一致；
- 下一步应先修什么，而不是继续扩写抽象设计。

它的定位不是替代：

- `freeze spec`
- `implementation package`
- `module interface / buffer budget / workload bucket` 三张统一表

而是给这些文档做一次 implementation-facing 的设计审查。

## 2. 审查范围

本次审查覆盖以下文件：

- `docs/architecture/qe_fpga_clustered_v1_freeze_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_implementation_package_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_module_interface_table_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_buffer_memory_budget_table_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_workload_bucket_mapping_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_cluster_d_refresh_spec_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_intercluster_exchange_spec_20260402.md`
- `.pipeline/docs/research_brief.json`
- `docs/benchmarks/qe_device_oriented_workload_matrix_v0.md`

本次审查不覆盖：

- 数值正确性复现实验；
- SystemC/RTL/HLS 运行结果；
- 板级时序、功耗、面积 closure。

## 3. 总体判断

当前 clustered v1 设计的总体方向是对的，而且比继续沿用 `BODY_01/02/03/04` 作为物理边界明显更合理。

最重要的正面结论有四个：

- 已经明确把 `body` 降级为 `shell contract layer`，把真正的实现视角切换到 `persistent episode controller + Cluster A/B/C/D`。
- 已经形成一套 implementation-facing 设计包，而不是只有 cluster 命名。
- 已经开始把 compatibility 当成一等公民处理，采用 `size bucket + mode axis + bounded fallback`，而不是为每个 case 单独造硬件。
- 已经把 resident object、FIFO、spill、controller sync、fallback 和 per-cluster KPI 写进统一口径，这比只谈算力要成熟得多。

但当前还不能把这套方案叫做 `implementation-ready FPGA design`。

更准确的状态是：

- 它已经进入 `implementation-facing architecture package`
- 但还没有进入 `implementation-ready FPGA design`

## 4. 完成度判断

### 4.1 分层完成度

| 层 | 当前判断 | 说明 |
| --- | --- | --- |
| 系统切分 | 较高 | `Host / persistent controller / A/B/C/D` 已经稳定 |
| 模块接口 | 中高 | 主要 ingress/egress、局部 buffer、backpressure 来源已列出 |
| buffer / resident / spill 合同 | 中高 | 已形成统一预算表，但仍是参数级，不是端口级实现 |
| workload 兼容性策略 | 中高 | 已有 bucket 和 mode axis，但规则尚未完全自洽 |
| cycle-approx 建模 | 中等 | 已有参数化公式，但尚未形成可直接扫表的完整 design-point 数据集 |
| 实现级收口 | 偏低 | 端口宽度、仲裁、时钟、跨域、精确 memory budget 尚未冻结 |
| RTL / HLS 可下推程度 | 低 | 目前还缺若干跨文档一致性修正和关键参数冻结 |

### 4.2 量化判断

如果把当前工作分成两个目标来看：

- 作为 `架构冻结包`：完成度约 `70/100`
- 作为 `implementation-ready FPGA design`：完成度约 `35-45/100`

这个判断的核心原因不是切分思路错，而是：

- 关键合同已经有了；
- 但还没有收口到可直接驱动 HLS/RTL 设计的程度。

## 5. 设计合理性判断

### 5.1 整体切分

当前切分总体合理。

合理性主要体现在：

- `Cluster A = fused h_psi + s_psi` 符合数据复用逻辑；
- `Cluster B = build H_sub / S_sub` 把 full-space 到 reduced-space 的收缩边界显式化；
- `Cluster C = hardware cdiaghg` 把原本最摇摆的 reduced solve 收到主路径；
- `Cluster D = refresh / residual -> P_next` 负责 loop-carried state 更新，保证 episode 闭环；
- `persistent episode controller` 避免 `CPU + FPGA` 退化成 `CPU + GPU` 式的小 kernel launch。

这套切分符合下面这些工程方法论：

- 先 profile 再切分；
- 算法-硬件共设计；
- Host-Accelerator 分工明确；
- dataflow/FIFO 驱动；
- 先 FPGA，后更硬化实现；
- 明确把 memory wall 放进主叙事。

### 5.2 compatibility-first 方向

当前兼容性方向也是对的。

当前已经采取的正确动作包括：

- 不追求“一核通吃”；
- 用 `descriptor-driven execution` 承接 case 差异；
- 用 `small / medium / large` 和 `NC-light / USPP/PAW-heavy` 管理 datapath 模式；
- 保留 `bounded fallback`，而不是为少数大 case 让整个 v1 设计失控。

但是，兼容性口径还没有完全收口，主要问题见第 6 节。

## 6. 主要问题与风险

下面按严重程度排序。

### 6.1 高风险：workload bucket 规则与实际 case 映射存在直接冲突

当前 `workload bucket mapping` 中的 bucket 规则定义为：

- `small`: `npw <= 2000`
- `medium`: `2000 < npw <= 3500`
- `large`: `npw > 3500`

但同一文档又把 `si8_pbe_nc` 映射为：

- `medium / NC-light`
- 同时写明 `npw = 4553`

这意味着：

- 如果后续脚本按 bucket 规则自动选参数，`si8_pbe_nc` 应落在 `large`
- 如果后续设计按 case mapping 手工选参数，`si8_pbe_nc` 又被当成 `medium`

这会直接影响：

- `psi_panel_kib`
- `fifo_ab_kib`
- `resident budget`
- controller 对 `Cluster A` 的调度策略

结论：

- bucket 规则和 case 映射必须二选一统一
- 否则 compatibility-first 只是叙事，不是可执行合同

### 6.2 高风险：Cluster C 的 capacity 假设与 trace-backed workload 不一致

`Cluster C` 文档中的兼容性描述把几个 case 的 `n_active` 估得明显高于当前冻结 workload matrix：

- `small-Si` 被描述成 `< 64`
- `Si8` 被描述成 `80~128`
- `graphene` 被描述成可能接近 `160`

但当前器件导向 workload matrix 给出的对应 `max_subspace_n` 是：

- `si4_pbe_uspp_small`: `16`
- `si8_pbe_uspp`: `32`
- `si8_pbe_nc`: `32`
- `graphene_pbe_uspp`: `8`

这会让下面这些关键参数丧失可信度：

- `c_reduced_dim_cap`
- `fallback` 触发阈值
- `crossover_margin`
- `c_input_buffer_kib`
- `c_eigvec_buffer_kib`

结论：

- `Cluster C` 需要明确区分“当前 trace-backed 包络”和“未来预留包络”
- 不能把未来可能扩展的 `n_active` 直接写成当前冻结 case 的实现约束

### 6.3 高风险：`T_C_input` 与 `T_C_compute` 定义不一致

当前跨文档存在一个直接影响 latency model 的问题：

- `architecture model` 中，`T_C_input` 是 reduced matrices 装载
- `T_C_compute` 是 hardware `cdiaghg` 计算

但 `Cluster C` 规格中：

- 一处把 factorization 放进 `T_C_input`
- 后面又把 factorization / transform / solver 都算进 `T_C_compute`

这会污染：

- `T_episode_cluster_lb`
- `T_hw_diag`
- `T_companion` 对比
- `crossover_margin`

结论：

- 必须给 `T_C_input / factorize / transform / solver / emit` 一个单一定义
- 否则 Cluster C 的所有 design-space 扫描都不可靠

### 6.4 中风险：`P_next` 的 resident 与 host 边界没有完全收口

当前有两种写法并存：

- 一处写 Episode Controller 会把 `P_next descriptors` 送到 host memory
- 另一处又把 `P_next` 当成下一轮 inner step 的 resident loop-carried state

从 v1 主路径意图看，更合理的语义应当是：

- `P_next` 默认 resident
- 只有 spill 或 episode exit 时才 host-visible

如果不明确，会影响：

- `Bytes_host_fpga`
- `Bytes_offchip`
- `resident_fit`
- `Cluster D` 的真实系统价值

结论：

- 需要在接口表和 inter-cluster 交换规格中明确区分：
  - `resident commit`
  - `spill commit`
  - `host-visible export`

### 6.5 中风险：interconnect 宽度像是“已定义”，又像“未冻结”

`inter-cluster exchange spec` 已经写出：

- 全部 handoff 都采用 `128-bit lanes`

但总包又明确写出：

- `interconnect 端口宽度与仲裁规则` 仍是下一步未冻结项

这会导致后续实现人员不知道：

- `128-bit` 是 contract
- 还是仅仅是 placeholder

结论：

- 需要把 `128-bit` 改写为：
  - `provisional default`
  - 或 `frozen baseline width`
- 不能保持当前这种双重语义

### 6.6 低风险：Cluster A 的一个 KPI 写错了归因对象

`Cluster A/B spec` 中把：

- `partial_HS_bandwidth_utilization`

定义成相对：

- `b_reduced_emit_bw_kib_per_us`

但这个参数本质上属于：

- `Cluster B -> Cluster C`

而不是：

- `Cluster A -> Cluster B`

这不是结构性错误，但会让 A 的瓶颈判断混入 B 的参数。

结论：

- A 的 emit utilization 应绑定 `fifo_ab_kib`、`a_partial_fifo_kib` 或 A→B 实际 stream throughput
- 不应绑定 B→C 参数

## 7. 分 cluster 评价

| cluster | 设计合理性 | 当前完成度 | 主要优点 | 主要缺口 |
| --- | --- | --- | --- | --- |
| Episode Control | 高 | 中高 | 已明确 persistent scheduling、credit、spill、fallback | `controller_sync_us` 仍是 proxy，仲裁规则未冻结 |
| Cluster A | 高 | 中高 | 融合 `h_psi + s_psi` 的方向正确，抓住数据复用 | off-chip load、A→B emit 和局部 array 结构还未收成端口/位宽级 |
| Cluster B | 高 | 中高 | `H_sub/S_sub` build 边界清楚，stage/reduce/fifo 逻辑成立 | descriptor packing、triangular layout、B→C barrier 细节仍偏粗 |
| Cluster C | 中高 | 中等 | 把 `cdiaghg` 收进主路径是正确战略动作 | 是当前最大风险点；capacity、fallback、latency 分解和 workload 包络仍不稳 |
| Cluster D | 中高 | 中等 | loop-carried state、`P_next`、`episode_continue_flag` 已成形 | resident/host 语义、orthogonality 代价、writeback 合同还需进一步收口 |

其中最需要继续重点盯住的是 `Cluster C`。

不是因为它的方向错，而是因为：

- 它最容易把“架构意图”误写成“实现已定”
- 也是最可能让后续 board bring-up 偏离 workload 真实边界的地方

## 8. 当前设计最值得保留的部分

即使后续要继续修改，下面这些内容应尽量保留，不要回退：

- `body -> shell contract layer only`
- `persistent episode controller`
- `Cluster A/B/C/D` 的主边界
- `resident + FIFO + spill + fallback` 作为统一语言
- `compatibility-first`
- `descriptor-driven execution`
- `bounded fallback`
- `per-cluster KPI freeze`

这些是当前 clustered v1 从“抽象设计笔记”走向“实现设计包”的关键跃迁。

## 9. 当前最合理的下一步

### 9.1 第一优先级：先做一致性修正，不要直接冲 HLS/RTL

当前最合理的第一步不是继续补更多模块笔记，而是先收口一份：

> `clustered_v1_consistency_fixlist`

至少要修下面六项：

1. 统一 `size bucket` 规则与 case 映射
2. 统一 `Cluster C` 的 trace-backed capacity 口径
3. 统一 `T_C_input / T_C_compute / T_C_emit` 定义
4. 明确 `P_next` 的 resident / spill / host-visible 语义
5. 明确 `128-bit lanes` 是 placeholder 还是 baseline contract
6. 修正 `Cluster A` 中串到 B 的 KPI 归因

### 9.2 第二优先级：冻结端口宽度与 memory hierarchy

在一致性修正完成后，下一步最值得做的是：

- 每个 cluster 的 ingress/egress width
- `BRAM / URAM / HBM` 预算
- on-chip resident budget 的分域分配
- stream width / burst size / alignment
- controller 和 cluster 间的 credit/ack width

这一步完成后，设计才会从“参数化架构模型”变成“可以下推的实现规格”。

### 9.3 第三优先级：形成 cycle-approx 参数表

在端口和 memory hierarchy 有初稿之后，再做：

- `cycle-approx` design-point table
- 每个 workload bucket 的 baseline parameter row
- `Cluster C` hardware/fallback crossover 扫描
- `fifo_*`、`stall_ratio_*`、`Bytes_spill` 的批量 sweep

这比现在直接写 HLS/RTL 更值，因为它能先验证：

- 这套切法是不是值得继续硬化
- 哪个 cluster 最先撞墙

## 10. 结论

当前 `QE clustered v1` 的分 cluster 设计：

- **方向正确**
- **比 body-based implementation view 明显更合理**
- **已经具备 implementation-facing package 的雏形**

但它还没有完成到可以直接说：

> “这已经是一套 implementation-ready 的 FPGA 设计”

更准确的结论应当是：

> 当前 clustered v1 已经完成了从 shell-contract 视角向 implementation-facing architecture package 的转变；
> 下一步不应再争论是否按 cluster 切，而应优先修正跨文档合同不一致，并把端口宽度、memory hierarchy、cycle-approx 参数表冻结下来。

## 11. 附注

本次文档结论基于文档与合同审查得出：

- 已检查设计包、接口表、预算表、bucket 映射和 research brief 的一致性
- 未运行 RTL / SystemC / FPGA 测试
- 因此这里给出的判断属于 implementation-facing design review，而不是数值或板级实验结论
