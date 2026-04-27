# QE IC fine-grained hardware axes v0

## 1. 目标

这份文档定义未来可扩展的 **细粒度硬件设计空间维度**。

这些维度当前阶段 **先冻结接口，不全面打开搜索**。

---

## 2. 预留维度

### 2.1 并行度 / 组件数量
- cluster count
- compute unit replication count
- resident bank count

### 2.2 存储容量
- resident buffer capacity
- near-memory scratch capacity
- host-device staging window size

### 2.3 传输维度
- DMA class / bandwidth tier
- transfer channel multiplicity
- overlap-capable link mode

### 2.4 算法-硬件耦合维度
- max device diag dimension
- supported FFT grid class
- reduction granularity
- fallback threshold policy

---

## 3. 当前阶段限制

这些维度当前只允许：
- 出现在 contract / schema / future interfaces 中；
- 作为 graph/evaluator 的 optional extension；
- 不能成为 v1 主搜索空间的核心。

---

## 4. 进入主搜索空间的前提

至少需要同时满足：
1. system-level graph schema 已稳定；
2. round-trip/export gate 已通过；
3. phase/release 主链未被 graph sidecar 打断；
4. 至少一个 canonical workload class 已能在新框架下稳定评估。
