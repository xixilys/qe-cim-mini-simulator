# QE 算子到加速路径映射（v1.1）

> 日期：2026-03-03  
> 本文档仅记录“当前可验证映射”，并标注“目标映射（待实现）”。

---

## 1. 已实现映射

### 1.1 GEMM 全局拦截

拦截入口：`qe_cim_bridge.c`

覆盖符号：
- Fortran BLAS: `zgemm_`, `dgemm_`, `cgemm_`, `sgemm_`
- CBLAS: `cblas_zgemm`, `cblas_dgemm`, `cblas_cgemm`, `cblas_sgemm`

执行路径：
```
QE GEMM -> bridge -> socket(op=0) -> SystemC server -> CIM_Macro -> result back
```

备注：
- socket 失败会 fallback 本地 C，并强制记录日志

---

## 2. EXX/ACE 关键路径（已对齐）

源码锚点：`PW/src/exx.f90`（`rns_cim_zgemm` 注入点）

当前行为：
- EXX 中 `ZGEMM` 由 bridge 统一处理
- 在 server 端通过 CIM_Macro 执行周期化 GEMM

---

## 3. USPP / add_vuspsi / calbec 映射状态

### 已实现
- 相关 GEMM 调用会被全局拦截并走统一路径

### 未实现的细分映射
- 未在 server 中按算子语义区分独立 `op_type`（例如 calbec/vuspsi/deeq）
- Deeq 专用 DSP 路径仍是模型层概念，尚未在 server 做独立模块化执行

---

## 4. FFT 映射状态

### 已实现
- 协议支持 `op=1` FFT
- server 调用 `FFT_Engine`
- bridge 提供 `cim_fft_track_` socket 调用

### 未实现
- QE 主调用链（`fwfft/invfft`）尚未全量插入 `cim_fft_track_`
- 因此默认运行时 FFT 替代比例未达 100%

---

## 5. 精度与调度映射

当前策略：
- 前段：关键路径 FP32，非关键 BF16
- 后段：关键路径 FP64，非关键 FP32

判据入口：`choose_call_precision(...)`（bridge）

环境变量：
- `CIM_MIXED_MODE`
- `CIM_PHASE_SWITCH_CALL`

---

## 6. 文档修正点（相对旧版）

- 删除固定规模参数（Si_8/16/32 表）作为“已实现事实”的描述
- 删除“DSP Engine 已独立处理 Deeq”的确定性表述，改为“目标映射”
- 删除“FFT 已与 CIM 全程并行流水”的确定性表述，改为“部分实现 + 待插桩”
