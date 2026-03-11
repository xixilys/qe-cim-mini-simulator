# 硬件调度流水设计

> 版本：v1.1 | 日期：2026-03-03  
> 本版已按当前代码状态校准：QE → bridge → socket server → SystemC(CIM/FFT)

---

## 1. 当前可执行调用链（已实现）

```
QE pw.x
  ├─ BLAS/CBLAS GEMM 调用
  │    -> qe_cim_bridge.c (全局拦截 z/d/c/sgemm + cblas_*)
  │    -> socket 请求(op=0, GEMM)
  │    -> cim_socket_server(sc_main)
  │    -> SystemC CIM_Macro (时序 + 数值)
  │    -> 返回 C 矩阵结果
  └─ (可选) FFT 统计调用 cim_fft_track_
       -> socket 请求(op=1, FFT)
       -> SystemC FFT_Engine
```

说明：
- GEMM 主链路已实测全走 socket（无 fallback）
- FFT 目前是“有接口、有 server 实现”，但 QE 主路径默认未全量插桩

---

## 2. GEMM 调度流水（v1.1）

### 2.1 单次 GEMM 执行
1. bridge 拦截 GEMM，按调用形态决定精度（混合策略）
2. bridge 做 A/B 权重侧判断（A 或 B 为 weight）
3. bridge 查询驻留命中（2-bank 缓存模型）
4. 发 socket 到 server（op=0）
5. server 侧将复数 GEMM 分解为 4 个实数 GEMM，逐个喂给 `CIM_Macro`
6. 合成复数输出并回传
7. bridge 记录能耗/延迟/命中率/是否 fallback

### 2.2 关键并行关系
```
CPU(QE)      : dispatch GEMM -> wait result -> continue SCF
Bridge       : precision choose + residency scheduler + socket
SystemC CIM  : cmd_valid/cmd_type/busy/result_valid 周期级推进
FFT Engine   : 由 op=1 单独触发（当前非每次 h_psi 必经）
```

---

## 3. 混合精度调度（已实现）

目标策略：
- 前段循环：关键路径 FP32，非关键 BF16
- 后段循环：关键路径 FP64，非关键 FP32

当前实现入口：`choose_call_precision(...)`（bridge）

判据（当前版本）：
- 关键路径启发式：
  - 存在共轭转置 (`C`)；或
  - 小方阵/小维关键子空间（m,n <= 16 / m==n<=64）
- 阶段切换：按 GEMM 调用序号 `CIM_PHASE_SWITCH_CALL`

环境变量：
- `CIM_MIXED_MODE=1`
- `CIM_PHASE_SWITCH_CALL=<N>`

---

## 4. 驻留与容量（修正）

### 4.1 已实现
- A/B 双 bank 的“逻辑驻留”
- 基于复用和形态的 weight 侧选择
- hit/miss 统计与写入开销扣减
- **硬切片执行**：按 SRAM 容量约束推导 tile_n，执行 M/K/N 分块
- **块稀疏跳过**：在 tiling 阶段对 A 子块做 block-level 稀疏判定并直接跳过

### 4.2 未实现（必须标注）
- 跨调用的物理地址映射与 bank 冲突建模
- DMA/NoC 真实传输拥塞模型

因此 v1.1 的“驻留时间收益”属于架构级近似，不等价于最终 RTL 结果。

---

## 5. fallback 机制（已实现）

当 socket 不可达/超时：
- bridge 强制打印 `[CIM][FALLBACK] ...`（不依赖 verbose）
- trace 写入 `FALLBACK,...`
- summary 给出：
  - `Socket Success`
  - `Socket Fallback`

---

## 6. 文档修正结论

与 v1.0 相比，以下内容已修正为“当前事实”：
- 不再宣称 FFT 已完全替代 QE 主路径
- 不再宣称 SRAM 硬容量映射已完成
- 精度切换从“固定 80/20”改为“混合策略 + 可配置切换点”
