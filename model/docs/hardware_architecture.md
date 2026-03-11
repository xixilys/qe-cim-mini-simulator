# CIM-QE 异构系统架构（实现对齐版）

> 版本：v1.1 | 日期：2026-03-03  
> 本文档区分“已实现链路”与“目标硬件形态”，避免过度宣称。

---

## 1. 系统分层

### 1.1 已实现软件-硬件协同层

```
QE pw.x
  -> qe_cim_bridge.c
  -> socket protocol
  -> cim_socket_server (SystemC sc_main)
      -> CIM_Macro
      -> FFT_Engine
```

### 1.2 目标硬件形态（尚未全实现）

```
CPU + FPGA Controller + CIM Macro Array + FFT Core + NoC/Buffer
```

说明：
- 当前 server 已调用 SystemC 模块，但 FPGA 控制器完整仲裁尚未全部下沉到 server
- 目前重点是 GEMM 正确性 + 周期级近似

---

## 2. 模块职责

### 2.1 Bridge (`qe_cim_bridge.c`)
- 全局拦截 GEMM：`zgemm_/dgemm_/cgemm_/sgemm_` + `cblas_*gemm`
- 混合精度调度（关键路径/非关键路径）
- 驻留调度（A/B weight 侧选择 + hit/miss）
- socket 通信与 fallback

### 2.2 Socket Server (`cim_socket_server.cpp`)
- `op=0`：GEMM 请求
  - 复数分解为 4 个实数 GEMM
  - 通过 `CIM_Macro` 执行（数值 + 时序）
  - 按 `CIM_SRAM_BITS` 做硬切片（M/K/N tiling）
  - 在 tile 阶段做块稀疏跳过（block-level prune）
- `op=1`：FFT 请求
  - 调用 `FFT_Engine` 返回 latency/energy 估计

### 2.3 SystemC 模块
- `CIM_Macro`
  - cmd/busy/result_valid 时序
  - BF16/FP32/FP64 量化行为
  - 周期模型（并发度/稀疏度）
- `FFT_Engine`
  - O(N log N) 周期估算流程

---

## 3. 当前能力边界（关键）

### 已有
- QE GEMM 全局替代可运行
- socket 成功/失败可观测（success/fallback）
- FP64 下与基准结果一致（Si 测例）

### 仍缺
- 真正的多 Macro 并行与 NoC 聚合
- FFT 在 QE 主路径的全量替换插桩

---

## 4. 推荐运行配置

### 准确性验证
- `CIM_SOCKET=1`
- `CIM_MIXED_MODE=0`
- `CIM_PRECISION=fp64`

### 混合精度研究
- `CIM_MIXED_MODE=1`
- `CIM_PHASE_SWITCH_CALL=<N>`
- `CIM_PRECISION=bf16`（基准精度）

---

## 5. 修订摘要（相对 v1.0）

- 删除“替代绝大部分 FFT 负载”的已实现表述，改为“FFT 有接口与模块实现，主路径待全量插桩”
- 删除“vkb/xi 绝不重写”等过强表述，改为“逻辑驻留模型”
- 保留目标架构，但明确当前是软件可运行版本，不是 RTL 等价模型
