# QE shell 面向 FPGA 的 clustered v1 架构规划说明（2026-04-02）

## 0. 目的

这份说明的目的，是把当前 `BODY_01/02/03/04` 为主的 shell-level SystemC 模型，明确降级为：

- **软件合同层 / shell-accounting 层**
- 而不是最终 FPGA 实现的物理分块

并把后续 v1 的实现探索转向一个更接近真实硬件的 clustered architecture。

## 1. 为什么不能再把 body 当最终硬件边界

当前 `model/qe_band_solver_model` 的价值在于：

- 保留 `QE` 的 shell 语义；
- 保留 `Host / FPGA / Chip` 的事务边界；
- 提供 `Phase B / BODY_04` 的流量、ref-cycle、backpressure 和 shell-stage 汇总。

但它的问题也很明显：

- `BODY_01/02/03/04` 更接近软件与系统建模边界，而不是数据复用驱动的硬件边界；
- 如果把 body 直接当成 FPGA 模块边界，那么建模结果主要回答的是“这种 body 切法的性能”，而不是“更合理硬件组织的性能”；
- 对真正硬件有决定意义的 resident object、buffer capacity、cluster fusion、persistent controller 粒度，在 body 视角下不够直接。

因此，后续必须明确区分：

1. **Contract layer**
   - 继续用当前 shell / body 模型保留软件语义与对比口径；
2. **Implementation layer**
   - 改用 clustered architecture 作为实际 FPGA 设计探索对象。

## 2. v1 推荐的 clustered architecture

### 2.1 顶层原则

v1 不建议做成：

- 一个覆盖整个 shell 的超深单流水；
- 或者把当前 `BODY_01/02/03/04` 原样物理实现为若干分散模块。

v1 更适合：

- **persistent episode controller + clustered dataflow architecture**
- cluster 间用 FIFO / stream / double buffer 连接；
- cluster 内部再按局部数学规律做中深流水、小阵列、归约树或 SIMD。

### 2.2 建议的 v1 clusters

#### Cluster A：Fused Operator Sweep Cluster

负责：

- `h_psi`
- `s_psi`

实现要点：

- 物理上不分成两个独立大模块；
- 共享 `psi / projector / row-block / panel` 数据流；
- 用一次 sweep 同时形成 `H/S` 相关 partials；
- 内部可以是 streaming datapath + local array / SIMD / reduction support。

这是 v1 的第一主热点。

#### Cluster B：Subspace Build Cluster

负责：

- `build H_sub / S_sub`

实现要点：

- 接收 Cluster A 的 partials 或局部聚合结果；
- 强调局部 accumulation、reduction tree、小 buffer 驱动；
- 输出 reduced matrices 给后续 `cdiaghg` cluster；
- 重点不是超深流水，而是低 spill 和稳定聚合路径。

#### Cluster C：Hardware cdiaghg Cluster

负责：

- `cdiaghg`

这是这次规划变化的关键：

- 不再默认把它放在 CPU / soft-core companion；
- v1 更倾向于把 reduced generalized diagonalization 放进硬件主路径；
- companion `cdiaghg` 只保留为 fallback contingency。

实现关注点：

- reduced matrices 的输入缓存组织；
- eigensolver / generalized eigensolver 的微结构选择；
- 返回 `C / Lambda / residual-visible` 信息的节奏；
- 这块带来的面积、buffer、控制复杂度是否值得。

#### Cluster D：Basis Refresh Cluster

负责：

- `refresh / residual -> P_next`

实现要点：

- loop-carried state 更新；
- residual / precondition / basis slot update；
- 写回下一轮 resident state；
- 要和 Cluster C 的输出边界严密配合。

这块如果设计差，整个闭环收益会被破坏。

### 2.3 Wrapper / shell-support path

在 v1 中，下面几项可以单独建模，不必一开始全部和内环 cluster 强绑定：

- `psi -> rho_out`
- `rho -> Veff`
- `mix_rho`

其中：

- `rho -> Veff` 是否进入 FPGA 主域，可以作为参数点探索；
- `mix_rho` 更像 shell-support / host-visible path；
- `psi -> rho_out` 是否并入硬件主路径，也可以作为参数点。

## 3. 顶层调度与 CPU+GPU 的本质差异

如果目标是构建 `CPU + FPGA` 的系统性优势，那么调度方式不能只是“像 CPU 调 GPU 一样调几个小 kernel”。

### 3.1 GPU 风格

`CPU + GPU` 更像：

- CPU 发 kernel
- GPU 以通用大并行库执行
- 每个 kernel 边界往往是显式的软件调度边界

### 3.2 FPGA v1 应该是什么

`CPU + FPGA` 更适合：

- Host 只发 coarse-grain episode descriptor；
- FPGA 内部 persistent controller 自己轮转：
  - tile / panel / row-block
  - resident context
  - inter-cluster flow control
  - `cdiaghg` rendezvous
  - refresh writeback

所以 FPGA 的优势不应该来自“模仿 GPU kernel offload”，而应该来自：

- 跨 kernel 融合；
- resident object 复用；
- 更少 host 介入；
- 更可控的数值与归约顺序。

## 4. 这次规划后，SystemC 模型应该怎么重新定位

当前已有的 shell model 不应被废弃。

它应该继续承担：

- QE shell 合同层；
- Host / FPGA / Chip 边界；
- shell-stage 汇总；
- baseline comparison 的统一语义口径。

但新加的一层 architecture model 应该承担：

- cluster 边界；
- resident object；
- buffer capacity；
- inter-cluster FIFOs；
- hardware `cdiaghg` latency / traffic / sync cost；
- companion fallback crossover 点。

也就是说：

- **旧模型回答“系统语义怎么闭环”**；
- **新模型回答“真实 FPGA 顶层该怎么组织”**。

## 5. v1 需要冻结的关键设计参数

后续 architecture exploration 至少要扫这些参数：

### 5.1 Resident objects

- `psi` 哪些块常驻
- projector / overlap state 哪些常驻
- `H_sub / S_sub` 的 staging 位置
- `P_next` / refreshed basis 的常驻方式

### 5.2 Buffer / memory hierarchy

- Cluster A 输入 buffer / output partial buffer
- Cluster B 聚合 buffer
- Cluster C reduced-matrix / eigvec / eigval buffer
- Cluster D basis refresh buffer
- spill 条件与 spill 成本

### 5.3 Cluster interconnect

- FIFO 深度
- double buffer 粒度
- stream width
- 是否允许 A-B-C-D overlap
- 哪些边界必须 barrier

### 5.4 cdiaghg design-space

- hardware `cdiaghg` latency
- hardware `cdiaghg` area / buffer proxy
- hardware path是否会拖累主系统时钟或 buffer 配置
- companion fallback 何时更优

## 6. 对下一步任务的影响

这次规划意味着后续不应该直接沿着旧 body 继续加细节，而应该新增两个优先任务：

1. 冻结 clustered v1 architecture（包含 hardware `cdiaghg` 优先方向）
2. 建 cluster-level architecture model，比较它与 fallback companion `cdiaghg` 的 crossover

在这两个任务完成前，`CPU only / CPU + GPU / CPU + FPGA` 的最终比较不应该继续提前下结论。

进一步地，如果要把 clustered v1 真正推进到 implementation-ready FPGA design，下一步不应再只停留在 cluster 命名层，而应直接转入模块级实现方案。当前对应的模块级草案见：

- `docs/architecture/qe_fpga_clustered_v1_module_realization_outline_20260402.md`

## 7. 当前一句话结论

当前 `BODY_01/02/03/04` SystemC 模型仍然有价值，但它应被视为：

> shell contract model

而不是：

> final FPGA implementation plan

后续真正要探索的对象，是：

> clustered FPGA architecture with persistent control and hardware `cdiaghg` preference
