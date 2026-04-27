# QE clustered v1 端口与 memory hierarchy 冻结说明（v0，2026-04-03）

## 1. 目的

这份文档对应 `design_analysis` 中的第二优先级：

> 冻结端口宽度与 memory hierarchy

它的作用不是直接给出板级时序 closure，也不是替代后续 RTL/HLS 细化，而是把 clustered v1 从“有模块接口与 buffer 合同”继续推进到“有统一端口宽度、统一 memory tier、统一仲裁基线”的阶段。

这份文档冻结的是：

- v0 architecture / cycle-approx / first-HLS baseline 的端口宽度
- object 到 memory tier 的落位规则
- off-chip / on-chip / controller sideband 的基本位宽
- burst / alignment / arbitration 的基线合同

这份文档**不冻结**：

- 最终板卡特定的 AXI/HBM/DDR IP 配置
- 时钟频率与 CDC 细节
- 最终 RTL 级端口命名
- floorplan / placement / routing 约束

## 2. 冻结层级

当前冻结层级定义为：

- **board-agnostic frozen baseline**
- 用于：
  - cycle-approx 参数表
  - HLS 入口接口假设
  - per-cluster memory budget 切分
  - CPU+FPGA shell-level steady-state 评估

如果后续板级实现需要偏离本说明，必须同时更新：

- `docs/architecture/qe_fpga_clustered_v1_implementation_package_20260402.md`
- `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md`
- `docs/architecture/qe_fpga_clustered_v1_architecture_model_template_v0.csv`

## 3. 冻结的端口宽度

### 3.1 全局端口宽度表

| 路径 | 冻结位宽 | 用途 | 备注 |
| --- | ---: | --- | --- |
| Host episode descriptor ingress | `128 bit` | episode descriptor / doorbell / coarse command | 控制面，不用于 bulk data |
| Host status / export egress | `128 bit` | status summary / host-visible export descriptor | 仅用于 `host_export` |
| Off-chip bulk DMA data | `512 bit` | `Psi` panel / spill / refill / fallback bulk transfer | v0 baseline，优先按 64B 对齐 |
| A→B stream data | `128 bit` | `partial_HS_packet` data lane | 与当前 exchange spec 的 packet 粒度保持一致 |
| B→C stream data | `128 bit` | reduced descriptor / matrix payload lane | 维持 reduced-path 的统一 packet 节奏 |
| C→D stream data | `128 bit` | diag solution stream | 与 D 的 writeback 节奏匹配 |
| Controller token path | `64 bit` | `panel_serial` / cluster gate / episode token | 控制 token 与 bulk 数据分离 |
| Credit / ack path | `32 bit` | FIFO credits / dequeue ack / throttle signal | sideband，单独计入 `controller_sync_us` |
| Spill / commit metadata | `128 bit` | `spill_commit` / `resident_commit` / `host_export` descriptor | 只传 metadata，不传 bulk payload |

### 3.2 冻结解释

- `128 bit` inter-cluster stream width 现在从“provisional default”提升为：
  - **v0 frozen architecture baseline**
  - 用于 cycle-approx、HLS 接口和设计空间对照
- 这依然**不是**最终板级实现不可更改的物理口宽；如果后续板上实现改成 `256 bit`，必须作为新 revision 明确记录，而不能悄悄替换
- `512 bit` off-chip DMA width 是为了把：
  - `Psi_panel` 拉取
  - spill / refill
  - host / companion fallback bulk transfer
  统一到一个足够宽的 memory-wall baseline

## 4. 冻结的 burst 与 alignment 合同

| 路径 | 对齐 | 默认 burst | 最大连续 burst | 说明 |
| --- | --- | --- | --- | --- |
| Host descriptor / status | `16 B` | `1 beat` | `4 beats` | 控制面，不做大 burst |
| Off-chip bulk DMA | `64 B` | `1024 B` | `4096 B` | 以 `Psi_panel` / spill block 为主 |
| A→B / B→C / C→D streams | `16 B` | packet-driven | packet-driven | FIFO stream，不以 AXI burst 记 |
| Spill / commit metadata | `16 B` | `1 beat` | `8 beats` | metadata 队列，非 bulk |

当前 v0 冻结规则是：

- 所有 off-chip bulk object 默认 `64 B` 对齐
- `Psi_panel`、spill block、reduced refill block 优先切成 `1 KiB` 基础块
- 若某 case 的 object 太小，不强行扩到大 burst；保持 packet-native 传输

## 5. 冻结的 memory hierarchy

### 5.1 Memory tiers

| Tier | 介质 | v0 预算 | 主要对象 | 角色 |
| --- | --- | ---: | --- | --- |
| Tier-0 | Register / LUTRAM | `64 KiB` | controller state, credit counters, small descriptors, status words | 低延迟控制层 |
| Tier-1 | BRAM | `1024 KiB` | ping/pong panel buffers, FIFOs, short scratch, reduction staging front buffers | streaming / buffering 层 |
| Tier-2 | URAM | `2048 KiB` | projector / overlap resident banks, reduced-stage rear buffers, diag buffers, `P_next` slots, residual state | resident / capacity 层 |
| Tier-3 | Off-chip bulk memory | not fixed in KiB | `Psi`, spill data, large-case refill, fallback transfer payload | 容量 / spill 层 |
| Tier-4 | Host memory | host-side | coarse descriptors, exported results, companion path payload | 软件可见层 |

由此冻结：

- `onchip_resident_budget_kib = 3072`
- 其中：
  - `bram_stream_budget_kib = 1024`
  - `uram_resident_budget_kib = 2048`
  - `lutram_ctrl_budget_kib = 64` 单独记，不并入 `onchip_resident_budget_kib`

### 5.2 Object-to-tier mapping

| 对象 | 首选 tier | 次选 tier | 不允许默认落位 | 说明 |
| --- | --- | --- | --- | --- |
| `episode_status_register`, credits, control queues | Tier-0 | Tier-1 | Tier-3/4 | 控制面必须片上 |
| `Psi_panel_ping/pong` | Tier-1 | Tier-2 | Tier-4 | A 的高频 staging |
| `projector_state`, `overlap_state` | Tier-2 | Tier-3(spill only) | Tier-4 | resident object，默认不上 host |
| `partial_HS_fifo`, `fifo_ab/bc/cd` | Tier-1 | Tier-0(headers only) | Tier-4 | stream buffering |
| `partial_HS_accum_buffer` | Tier-1 | Tier-2 | Tier-4 | B 的局部累加优先 BRAM |
| `H_sub/S_sub` staging | Tier-2 | Tier-1(front staging) | Tier-4 | reduced-space 结果优先片上 |
| `diag_input`, `eigvec`, `eigval` | Tier-2 | Tier-3(spill/fallback only) | Tier-4 | C 的核心 resident/scratch |
| `refresh_scratch_buffer` | Tier-1 | Tier-2 | Tier-4 | D 的入口 scratch |
| `P_next_slots`, `residual_buffer` | Tier-2 | Tier-3(spill only) | Tier-4 | loop-carried state 默认 resident |

## 6. 每个 cluster 的端口与 memory 基线

### 6.1 Episode Controller

| 项 | 冻结值 |
| --- | --- |
| descriptor ingress | `128 bit` |
| token egress | `64 bit` |
| credit/ack | `32 bit` |
| local storage | Tier-0 |
| host-visible export | 仅 `host_export` 时走 `128 bit` status/export path |

### 6.2 Cluster A

| 项 | 冻结值 |
| --- | --- |
| off-chip panel read width | `512 bit` |
| `Psi_panel` staging | Tier-1 |
| projector / overlap banks | Tier-2 |
| A→B stream width | `128 bit` |
| A local arbitration | `Psi_panel load > projector refill > optional spill` |

### 6.3 Cluster B

| 项 | 冻结值 |
| --- | --- |
| A→B ingress | `128 bit` |
| local accum buffer | Tier-1 |
| `H_sub/S_sub` stage | Tier-2 with Tier-1 front staging |
| B→C stream width | `128 bit` |
| B local arbitration | `partial reduce commit > stage write > spill` |

### 6.4 Cluster C

| 项 | 冻结值 |
| --- | --- |
| B→C ingress | `128 bit` |
| diag buffers | Tier-2 |
| fallback / spill bulk path | `512 bit` off-chip DMA |
| C→D stream width | `128 bit` |
| C local arbitration | `diag input fill > compute scratch reuse > spill/fallback pack` |

### 6.5 Cluster D

| 项 | 冻结值 |
| --- | --- |
| C→D ingress | `128 bit` |
| refresh scratch | Tier-1 |
| `P_next` / residual resident state | Tier-2 |
| commit metadata egress | `128 bit` |
| D local arbitration | `resident commit > spill commit > host export` |

## 7. 仲裁基线

### 7.1 Off-chip DMA arbitration

v0 冻结顺序：

1. Cluster A `Psi_panel` read
2. Cluster D spill / resident-overflow writeback
3. Cluster C fallback / spill read-write
4. Cluster B spill
5. host-visible export

理由是：

- A 的断粮会直接拖住整条 episode
- D 的 spill 会阻塞 loop-carried state 提交
- C 的 fallback 需要保证不会把主路径彻底饿死，但优先级不能高于 A
- host export 不是 steady-state 主路径

### 7.2 Credit / ack arbitration

冻结为：

- 每条 FIFO 独立 credit counter
- controller 侧 round-robin 轮询 `ab -> bc -> cd`
- 若某条 FIFO 连续高于 `90%` 且超过 `controller_sync_us`，优先给该链路处理 ack / throttle

## 8. 进入模型模板的新增参数

这一步冻结后，architecture model template 必须新增下面这些字段：

- `host_desc_w_bits`
- `host_status_w_bits`
- `dma_data_w_bits`
- `dma_burst_bytes`
- `dma_align_bytes`
- `cluster_stream_w_bits`
- `controller_token_w_bits`
- `credit_ack_w_bits`
- `lutram_ctrl_budget_kib`
- `bram_stream_budget_kib`
- `uram_resident_budget_kib`

这些参数的默认值就是本说明冻结的 v0 baseline。

## 9. 当前仍未解决的部分

即使这一步冻结完成，下面这些问题仍然未完成：

- 最终 HBM / DDR 类型与具体 IP 选择
- clock target 与 CDC 方案
- BRAM / URAM 在具体 cluster 内的 block-level 精确切分
- actual board floorplan
- RTL / HLS 验证后的位宽回退或扩展

因此，这份文档的结论应理解为：

> clustered v1 已完成端口宽度与 memory hierarchy 的 v0 baseline freeze，可以进入 cycle-approx 参数表与 first-HLS interface planning；
> 但还没有进入板级 physical closure。
