# 2026-04-09 Host-Managed Full-SCF 软硬件协同架构 v1

## 1. 文档定位

这份文档是对当前 runnable model 的一次重新收口：

- 不再把 `Cluster A/B/C/D` 作为系统级主抽象；
- 把系统对象改写为 `Host CPU -> thin device runtime -> hardware datapath`；
- 把完整 `SCF shell` 的软硬件分工、数据边界、DMA 路径、diag fallback 路径明确成实现级合同。

它建立在以下两份文档之上：

- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md)
- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_interface_contract_v0.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_interface_contract_v0.md)

但本文件的主角不是 replay/body catalog，而是：

1. 哪些工作留在 CPU
2. 哪些工作交给 device runtime
3. 哪些工作固定在 hardware datapath
4. Host 和 device 之间搬什么数据、什么时候搬、谁做决策

## 2. 系统对象

当前 v1 系统对象固定为三层：

1. `Host CPU / software runtime`
2. `Thin device runtime / firmware bridge`
3. `Hardware datapath`

对 `QE / CP2K / VASP` 风格 full-SCF shell，当前主控制口径为：

```text
Host CPU:
  rho -> Veff
  build iteration request
  submit resident/batch/diag policy
  wait completion
  mix_rho / convergence / next iteration

Thin device runtime:
  resident preload
  batch DMA
  device launch
  host-diag fallback bridge
  completion/perf summary

Hardware datapath:
  h_psi / s_psi
  H_sub / S_sub build
  hardware-first diag proxy
  refresh / residual / P_next
```

## 3. 分工冻结

### 3.1 Host CPU

Host CPU 固定负责以下职责：

- 外层 `SCF` 循环
- `rho -> Veff`
- `mix_rho`
- 全局收敛判断
- `k-point / band batch` 组织
- resident set 和 batch request 生成
- `DiagPolicy` 生成
- host-side diagonalization fallback
- 不同 workload trait 的策略切换

Host CPU 不直接负责：

- 逐条 `LCW` 下发
- cluster/fifo 级资源管理
- 片上 resident window 生命周期

### 3.2 Thin Device Runtime

Thin device runtime 是软件语义与 hardware datapath 之间的隔离层，固定负责：

- resident preload / reuse 判断
- `Host DRAM <-> Device HBM` DMA
- request 到内部 `EpisodeDescriptor` 的映射
- device execute launch
- `diag` fallback 的导出、回传、同步
- `CompletionSummary` 和性能计数汇总

它不是：

- 纯 RTL 状态机
- 完整操作系统
- QE 控制平面的副本

### 3.3 Hardware Datapath

当前 v1 强制放进硬件的数据通路：

- `Cluster A`: `h_psi / s_psi` projector-apply 主链
- `Cluster B`: `H_sub / S_sub` reduced build
- `Cluster D`: refresh / residual / `P_next`
- 相关片上 `buffer / fifo / double-buffer` 支撑

`Cluster C` 的定位是：

- 设备优先的 diagonalization proxy
- 但必须允许回退到 Host CPU
- 不能把 “diag 完全硬化” 当作 v1 成功标准

## 4. Public Interface

当前对上层软件暴露的接口对象固定为 5 类：

### 4.1 `ResidentSetDesc`

表达 device 侧应预加载并尽量复用的常驻对象：

- projector/beta family
- support-grid mode
- potential slice metadata
- resident footprint / preload budget

### 4.2 `BandBatchDesc`

表达本次 inner hot path 的活动 batch：

- `band_begin / band_count`
- `panel_count / panel_size`
- `band_batch`
- wave input / output 数据量
- 是否双缓冲

### 4.3 `DiagPolicy`

表达 host 对 `diag` 的策略约束：

- 设备优先还是强制 CPU
- `max_device_diag_dim`
- `max_condition_estimate`
- 是否要求 resident fit
- 是否允许 CPU fallback

### 4.4 `ScfIterationRequest`

这是 Host 到 device runtime 的主请求对象，包含：

- resident set
- band batch
- diag policy
- density / potential / history object
- completion policy

### 4.5 `CompletionSummary`

这是 device 到 Host 的主返回对象，包含：

- 执行状态
- `diag_path`
- resident reuse / spill 状态
- device busy / DMA / host assist 开销
- DMA read/write 数据量
- exported wave handle
- 内部 `EpisodeResult`

## 5. 数据所有权与搬运

### 5.1 Host DRAM

保留以下全局对象：

- `rho`
- `Veff`
- mixing history
- 全局收敛状态
- host fallback solver 的输入输出

### 5.2 Device HBM / DDR

保留以下 episode 级对象：

- resident projector set
- support-grid metadata
- potential slice
- active wave batch
- reduced matrices
- temporary refresh/update objects

### 5.3 On-chip SRAM / BRAM / URAM

只保留局部对象：

- tile
- FIFO
- double buffer
- row-block window
- temporary reduction packets

不在片上长期保存：

- 全局 `rho`
- 全局 `Veff`
- 全局 `SCF` 历史

### 5.4 传输协议

当前固定采用三类通道：

1. 控制描述符通道
2. bulk DMA 通道
3. completion / perf summary 通道

标准时序为：

```text
Host register/pin objects
-> preload resident set
-> stream active band batch
-> device execute
-> optional reduced export for host diag
-> optional diag solution import
-> export updated wave
-> return completion summary
-> Host decides continue / fallback / reuse / release
```

## 6. `diag` Fallback 合同

`diag` 是当前最关键的软硬件协同边界。

### 6.1 设备侧可直接执行的条件

以下条件同时满足时，允许保持在 device 侧：

- `diag_dim <= max_device_diag_dim`
- 估计条件数不超过 `max_condition_estimate`
- resident fit 成立
- 设备路径不比 companion/host 更慢

### 6.2 必须回退到 Host 的条件

满足以下任一条件时，切换到 Host CPU：

- Host 显式 `force_cpu_diag`
- `diag_dim` 超界
- 估计条件数超界
- resident spill 导致 device 路径不再合适
- device runtime 判定 `hardware-first` 只是低效代理

### 6.3 回退流程

回退流程固定为：

1. device export `reduced_matrices`
2. Host CPU 执行 diagonalization assist
3. device import `diag_solution`
4. hardware datapath 继续 refresh / residual / `P_next`

因此，CPU fallback 不是错误路径，而是正式合同的一部分。

## 7. workload compatibility

兼容性不再按 cluster mode 表达，而按 workload trait 表达。

当前 v1 目标至少覆盖：

- `QE USPP-heavy`
- `NC-light`
- `VASP / PAW-heavy`
- `CP2K OT-like small batch`

其中：

- `si8_pbe_uspp` 对应 `QE USPP-heavy`
- `si8_pbe_nc` 应作为 `NC-light` 的中等半导体 case
- `VASP BLOCKED_DAVIDSON` 对应 `PAW-heavy`

当前 runnable model 已经在控制口径上体现：

- `QE -> USPP`
- `CP2K/QS_OT -> NC-light`
- `VASP -> PAW-heavy`

## 8. 与当前代码的映射

当前代码中的主映射如下：

- [host_scf.cpp](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/host_scf.cpp)
  - Host CPU 侧 `SCF` 控制、request 生成、completion 消费
- [fpga_orchestrator.cpp](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/fpga_orchestrator.cpp)
  - thin device runtime、resident reuse、DMA、host-diag assist
- [interconnect.cpp](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/interconnect.cpp)
  - 控制描述符、DMA、completion 的 TLM-style `b_transport`
- [types.hpp](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/include/types.hpp)
  - host-device-first public types
- [cluster_c_hardware_diag.cpp](/Volumes/remote/phd/year_2/project/dft加速/model/qe_band_solver_model/src/clusters/cluster_c_hardware_diag.cpp)
  - 设备优先 / host fallback 的判定门限

## 9. 当前实现状态

### 9.1 已完成

- public API 已改成 host-device-first
- thin device runtime 已具备 resident preload / batch DMA / completion 汇总
- `diag` 已支持显式 host CPU fallback
- 运行日志已统计：
  - `device_busy_ref_cycles`
  - `dma_ref_cycles`
  - `host_assist_ref_cycles`
  - `cpu_fallbacks`
  - `resident_reuse_hits`
  - DMA read/write 数据量

### 9.2 仍是近似模型

- 仍不是数值 faithful QE 实现
- 仍不是完整标准 socket 级 TLM-2.0 网络
- hardware datapath 仍复用 cluster-first 内部执行器
- host fallback 仍是 timed-functional proxy，不是 LAPACK faithful solver

### 9.3 下一步

如果继续推进，优先级建议是：

1. 把 `Interconnect` 进一步升级成标准 initiator/target socket 级 TLM
2. 把 Host fallback solver 从 timed proxy 换成真实 companion path
3. 把 resident/batch/diag policy 参数表拉成 sweep harness
4. 用真实 `si8_pbe_nc`/`si8_pbe_uspp` trace 去校准 DMA 与 resident reuse

## 10. 验证命令

### 默认 QE / USPP 路径

```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

### 强制 Host `diag` fallback

```bash
QEBS_MAX_SCF_ITERS=1 QEBS_FORCE_HOST_DIAG=1 \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### `NC-light` 路径

```bash
QEBS_SOFTWARE_FAMILY=CP2K QEBS_FLOW_FAMILY=QS_OT QEBS_MAX_SCF_ITERS=1 \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### `PAW-heavy` 路径

```bash
QEBS_SOFTWARE_FAMILY=VASP QEBS_FLOW_FAMILY=BLOCKED_DAVIDSON QEBS_MAX_SCF_ITERS=1 \
./model/qe_band_solver_model/build/qe_band_solver_model
```
