# 验证计划（实现对齐版）

> 版本：v1.1 | 日期：2026-03-03

---

## 1. 验证目标（修订）

1. **矩阵替代正确性**：在 FP64 下，全局 GEMM 替代与 QE 基线一致
2. **协同链路完整性**：socket server 成功处理请求，fallback 可观测
3. **混合精度可收敛**：策略模式下 Si 测例可收敛，能量误差可控
4. **调度可解释性**：输出命中率、精度选择、socket success/fallback 统计

---

## 2. 验证阶段

### Phase A: 全局 GEMM 替代正确性（必须）
- 配置：`CIM_SOCKET=1`, `CIM_MIXED_MODE=0`, `CIM_PRECISION=fp64`
- 判据：
  - 最终总能与基线一致
  - 收敛轮数一致
  - `Socket Fallback = 0`

### Phase B: fallback 可见性验证（必须）
- 配置：故意设置不可达端口（如 `CIM_SOCKET_PORT=7799`）
- 判据：
  - 日志出现 `[CIM][FALLBACK] ...`
  - trace 出现 `FALLBACK,...`
  - summary 统计 fallback 次数 > 0

### Phase C: 混合精度稳定性（必须）
- 配置：`CIM_MIXED_MODE=1`, `CIM_PHASE_SWITCH_CALL=<N>`
- 判据：
  - SCF 收敛
  - 最终能量与 FP64 基线差值在目标阈值内

### Phase D: FFT 协同验证（当前部分）
- 验证 `op=1` 可用（server 端 FFT_Engine 正常工作）
- 若完成 QE 插桩，再升级为“端到端 FFT 替代验证”

---

## 3. 成功判定标准

| 项目 | 条件 |
|------|------|
| FP64 全局 GEMM 替代 | 总能与基线一致，收敛轮数一致 |
| socket 链路可靠性 | `Socket Success > 0` 且可控 fallback |
| fallback 透明性 | 日志和 trace 均有显式记录 |
| 混合精度可用性 | SCF 收敛，能量误差受控 |

---

## 4. 不再使用的旧标准（删除）

- 删除“Si_8/Si_16/Si_32 全通过”作为当前必达目标（尚未完成多 Macro 硬容量映射）
- 删除“FFT 全替代已完成”表述
- 删除“BF16 误差固定 < 1e-3”硬阈值（应以收敛与最终能量偏差联合评估）
