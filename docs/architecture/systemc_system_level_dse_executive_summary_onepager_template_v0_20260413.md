# 2026-04-13 Executive Summary One-Pager Template — SystemC System-Level DSE v0

## 标题
**System-Level DSE Recommendation for QE-Oriented Soft/Hardware Co-Design**

## 1. 一句话结论
> 在统一 QE gold correctness gate 下，当前推荐 `TODO family` 作为下一阶段主线，因为它在 `correctness_status = TODO`、`confidence = TODO` 的前提下，给出了 `speedup_to_convergence_range = TODO` 与 `energy_to_convergence_range = TODO`，且 CPU/device 分工最适合后续工程化验证。

## 2. 为什么现在要做这个系统架构
- 目标不是先冻结 RTL，而是先选出**最值得继续做**的系统架构族。
- 比较对象不是单一 kernel，而是完整 SCF-shell 下的软硬件协同系统。
- 所有结论都围绕 `time/speedup/energy to convergence`，而不是单 kernel 峰值。

## 3. 比较了什么
| Family | 简述 | 定位 |
|---|---|---|
| `F1` | Host-heavy / Single-hotpath | 保守基线 |
| `F2` | Balanced hybrid / Multi-operator pipeline | 主候选 |
| `F3` | Device-heavy / Full inner-loop offload | 激进候选 |

## 4. 推荐结果（必填）
| 字段 | 内容 |
|---|---|
| Recommended family | `TODO` |
| correctness_status | `TODO` |
| confidence | `TODO` |
| speedup_to_convergence_range | `TODO` |
| energy_to_convergence_range | `TODO` |
| Main reason | `TODO` |
| Main caveat | `TODO` |

## 5. CPU / Device 分工摘要（必填）
### CPU 保留
- `TODO`

### Device runtime 保留
- `TODO`

### Hardware datapath 放入
- `TODO`

## 6. 正确性底线（必填）
- Gold reference: **QE CPU-only baseline**
- 必须对齐：
  - final `total energy`
  - final `residual threshold` state
  - final converged/not-converged state
- Tolerance schema ID: `TODO`
- Gold gate result: `TODO`

## 7. 为什么不是另外两类架构
### Why not F1
- `TODO`

### Why not F3
- `TODO`

## 8. 这份结论能支持什么，不能支持什么
### 能支持
- 继续哪一类系统架构主线
- 推荐 CPU/device/datapath 分工
- 下一阶段 FPGA/RTL 原型是否值得做

### 不能支持
- RTL 参数最终冻结
- 最终 DMA / buffer / memory budget 结论
- 最终 board-level power claim

## 9. 建议下一步
1. `TODO`
2. `TODO`
3. `TODO`

## 10. 口头汇报 30 秒版
> 我们不是先去做很细的 DMA/buffer 调参，而是先用 system-level DSE 在统一 QE correctness gate 下比较三类系统架构。当前 `TODO` 最值得继续做，因为它在正确性不失真的前提下，给出了 `TODO` 的 speedup-to-convergence 区间和 `TODO` 的 energy-to-convergence 区间，同时保留了比较合理的 CPU/device 分工。当前结论已经足够支持下一阶段工程化方向选择，但还不足以直接冻结 RTL 或板级功耗。
