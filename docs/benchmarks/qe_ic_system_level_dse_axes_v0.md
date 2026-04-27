# QE IC system-level DSE axes v0

## 1. 目标

这份文档冻结 **system-level DSE v1** 允许开放的架构维度。

当前原则：
> 先系统级，后细粒度硬件维度。

---

## 2. 当前开放维度（v1）

### 2.1 组件选择维度
- 是否启用 `FFTUnit`
- 是否启用独立 `ReductionUnit`
- 是否启用独立 `DiagUnit`
- 是否保留 host-side 某些控制/回退路径

### 2.2 模块连接维度
- 模块之间的连接方式
- CIM / FFT / Diag / DMA 的连接拓扑
- 是否共享某些 transfer / residency path

### 2.3 计算流程维度
- stage 顺序
- 流程拆分方式
- overlap / barrier 策略
- host 与 fpga 之间的协同流程切分

### 2.4 host/fpga 功能切分维度
- 哪些步骤放在 host
- 哪些步骤放在 fpga
- 哪些步骤允许 fallback

### 2.5 兼容性维度（继承当前 brownfield）
- `family`
- `diag_policy`
- `offload_scope`
- `resident_policy`
- `partition_strategy`

---

## 3. 当前不开放的维度

这些维度属于下一阶段：
- cluster 数量
- on-chip buffer 容量
- DMA 档位 / 通道数
- device diag 规模上限
- module replication 因子
- local scheduling micro-policy

---

## 4. 设计意图

当前 system-level axes 的职责是：
- 先定义系统对象；
- 先比较流程与拓扑；
- 先找到端到端 total time 最优的架构候选；
- 然后再决定细粒度硬件维度是否值得展开。
