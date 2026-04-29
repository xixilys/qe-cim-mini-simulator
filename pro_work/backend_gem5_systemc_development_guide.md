
# 后端 gem5 + SystemC 软硬件协同仿真开发推进文档

**适用范围**：本文件面向项目后端，即负责 SystemC/timed-functional model、gem5 CPU/设备模型、TLM/MMIO/DMA 接口、soft runtime/proxy driver、benchmark 执行、结果报告和后端 feedback artifact 生成的部分。

**目标定位**：把当前后端从“QE/DFT FPGA proxy demo + gem5 integration scaffold”推进为一个**通用软硬件协同评估服务**，能接收前端 DSE 生成的候选设计 descriptor，执行相应保真度的仿真/benchmark，并回传可校验的 metrics 和 claim ceiling。

---

## 1. 当前后端状态判断

当前后端有三块。

第一块是 `model/qe_band_solver_model/`：这是当前最完整的 SystemC-style/timed-functional 系统模型。它已经有：

```text
DFTHybridSystem
  -> HostSCF
  -> FPGAOrchestrator
  -> ChipTop
  -> ClusterGraphExecutor
  -> Cluster A/B/C/D
```

其中 HostSCF 负责初始化 SCF state、构造 resident set、band batch、diag policy 和 iteration request；FPGAOrchestrator 负责 resident preload、band batch streaming、device execution、CPU fallback diag、completion summary；ClusterGraphExecutor 能执行 Cluster A/B/C/D，也能在 graph frontdoor 模式下用 bypass cluster 处理缺失模块。

这部分的优点是：

- 目标系统抽象清晰。
- Host/runtime/hardware datapath 分层基本正确。
- 已经能表达 resident reuse、spill、fallback、device busy cycles、DMA cycles、cluster metrics。
- 已经能支持 QE/CP2K/VASP 风格的软件 family tag。

它的问题是：

- 仍是 timed-functional/proxy，不是 numerical DFT equivalent。
- 部分 workload energy/shape 是启发式规则，不是来自真实 trace 或 gold baseline。
- Cluster C 是 hardware-first diagonalization proxy，不应被声明为真实 cdiaghg 实现。
- 输出还需要统一成前端可消费的 backend feedback artifact。

第二块是 `gem5_integration/src/dev/fpga/`：这是 gem5 里的 FPGA PCIe/MMIO/DMA 设备模型。它已经有：

- `FPGAAccelerator` PCI endpoint。
- 控制寄存器、DMA 寄存器、electrons loop 寄存器、H/S/rho/Veff 地址寄存器。
- `executeElectrons()`，能设置状态寄存器、生成 TLM 请求、返回 converged/iterations/error/energy/time 等结果。
- 在 `USE_SYSTEMC` 下有 `FPGATLMMediator` 和 `FPGATLMStub`。

这部分的优点是：

- gem5 侧设备形态已经存在。
- MMIO register map 和 guest polling 路径已经有雏形。
- SE-mode smoke test 方向可行。

它的问题是：

- 当前 `executeElectrons()` 为了 atomic CPU/smoke 方便，会同步设置完成寄存器，然后再调度事件。这适合 smoke，不适合 timed correctness。
- `FPGATLMStub` 还不是完整连接到 `model/qe_band_solver_model` 的真实 SystemC model。
- 设备模型与 `gem5_integration/systemc_model/` 之间存在重复 timing stub。
- 需要严格区分 `smoke_mode`、`timed_proxy_mode`、`real_bridge_mode`。

第三块是 `gem5_integration/systemc_model/`：这是 gem5-facing SystemC TLM target/bridge。它已经有：

- `Gem5Bridge`。
- `Gem5TLMTarget`。
- `DFTHybridSystemGem5`。
- standalone test。

这部分的优点是：

- TLM target、device memory、register access、DMA timing、electrons command timing 都有雏形。
- `DFTHybridSystemGem5::execute_electrons_from_gem5()` 能跑一个完整 electrons loop proxy。

它的问题是：

- `DFTHybridSystemGem5::run_scf()` 当前仍是 stub 风格，返回的 report 没有真正执行 HostSCF/FPGAOrchestrator/ClusterGraphExecutor。
- `execute_electrons_from_gem5()` 使用固定 timing 常量，不等价于 `qe_band_solver_model` 主路径。
- `Gem5TLMTarget` 中 register address route 需要复查。当前代码形态类似：

```cpp
if (addr >= DEVICE_MEMORY_SIZE && addr < 0x10000) { ... }
```

如果 `DEVICE_MEMORY_SIZE = 1GB`，这个条件对 0x0000-0xFFFF register address 永远不成立。建议改成明确的地址空间：

```text
0x0000_0000 - 0x3fff_ffff: device memory
0x4000_0000 - 0x4000_ffff: register window
```

或者把 TLM transaction address 在进入 target 前先归一化成 BAR offset。

---

## 2. 后端应该如何重新定位

后端不应该只被定义成“跑 QE 的 gem5+SystemC”。更好的定位是：

> 一个可插拔的 co-simulation backend service，接收 DSE candidate descriptor，执行指定 fidelity 的软件/硬件协同仿真，并输出可被前端验证的 evidence artifact。

后端应支持四类 fidelity：

| Fidelity | 目标 | 当前对应 |
|---|---|---|
| B1 SystemC standalone | 快速测试 accelerator/system model | `model/qe_band_solver_model`、`systemc_model/standalone_test.cpp` |
| B2 timed-functional proxy | 运行候选硬件数据流，输出 latency/DMA/fallback | `qe_band_solver_model` 主路径 |
| B3 gem5-SystemC smoke | 验证 host 控制、MMIO/TLM、completion | `gem5_integration` |
| B4 gem5-SystemC timed proxy | 评估 host overhead/cache/sync/driver | 需要继续实现 |

每个 fidelity 都要输出相同基本 schema，只是 `claim_ceiling` 不同。

---

## 3. 后端输入：BackendExecutionRequest

前端 Stage-B0 应输出一个通用请求，后端只读这个请求执行，不直接理解 DSE 内部结构。

```json
{
  "schema_version": "backend_execution_request_v0",
  "candidate_id": "...",
  "workload_identity": {
    "workload_id": "...",
    "domain": "dft",
    "adapter": "qe"
  },
  "candidate_identity": {
    "architecture_template_id": "F2_balanced_pipeline",
    "target_class": "fpga",
    "design_axes": {
      "family": "F2",
      "diag_policy": "device_first_fallback",
      "offload_scope": "balanced",
      "resident_policy": "fit_first",
      "partition_strategy": "operator__build__diag__refresh"
    }
  },
  "execution_mode": "systemc_timed_functional | gem5_systemc_smoke | gem5_systemc_timed_proxy",
  "systemc_config": {
    "cluster_graph": [],
    "resident_object_map": {},
    "dma_plan": {},
    "timing_profile_id": "default_proxy_v0"
  },
  "software_runtime": {
    "mode": "proxy_runtime | native_binary | trace_replay",
    "control_policy": "sync | async | double_buffered"
  },
  "expected_report_schema": "backend_execution_report_v0"
}
```

对于 QE，`adapter=qedft` 可以把字段扩展为：

```json
"domain_extension": {
  "qe": {
    "case_id": "si8_pbe_nc",
    "pseudopotential_family": "NC",
    "solver_path_class": "standard_band",
    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0"
  }
}
```

---

## 4. 后端输出：BackendExecutionReport

后端必须输出前端可验证的报告。

```json
{
  "schema_version": "backend_execution_report_v0",
  "candidate_id": "...",
  "execution_status": "executed | failed | partial",
  "fidelity": "gem5_systemc_smoke",
  "claim_ceiling": "gem5_systemc_smoke_only",
  "environment": {
    "host": "linux-x86_64",
    "gem5_mode": "SE | FS | none",
    "systemc_version": "...",
    "git_commit": "..."
  },
  "control_path": {
    "host_launch_count": 1,
    "completion_count": 1,
    "fallback_count": 0,
    "deadlock": false
  },
  "metrics": {
    "time_to_completion_s": 0.0,
    "cycle_proxy": 0,
    "host_wait_s": 0.0,
    "device_busy_s": 0.0,
    "dma_read_bytes": 0,
    "dma_write_bytes": 0,
    "bytes_moved_to_convergence": 0,
    "resident_reuse_ratio": 0.0,
    "spill_ratio": 0.0,
    "fallback_ratio": 0.0
  },
  "correctness_gate": {
    "workload_equivalent_claim": false,
    "domain": "dft",
    "domain_equivalence_claim": false
  },
  "non_claims": [
    "not_qe_equivalent_scf",
    "not_fpga_board_measured",
    "not_cycle_accurate_rtl"
  ]
}
```

---

## 5. 后端需要继续深入推进的工作

### 5.1 明确三种运行模式

建议后端显式支持：

```text
smoke_mode:
  目标：能跑通控制路径。
  允许：同步设置完成寄存器、简化 timing、mock correctness。
  claim_ceiling：gem5_systemc_smoke_only。

timed_proxy_mode:
  目标：SystemC time 与 DMA/cluster/report 一致。
  要求：不能立即假完成；必须等待 SystemC/TLM timing。
  claim_ceiling：systemc_timed_functional_proxy_only。

calibrated_proxy_mode:
  目标：用前端 calibration 更新 timing 参数。
  要求：加载 calibration profile。
  claim_ceiling：calibrated_proxy_only。
```

`executeElectrons()` 里立即设置完成状态的逻辑应该被包进 `smoke_mode`，不能作为默认 timed path。

### 5.2 打通真实 SystemC bridge，而不是 stub bridge

当前 gem5 设备内部有 `FPGATLMStub`，而 `gem5_integration/systemc_model/` 又有 `Gem5TLMTarget` 和 `DFTHybridSystemGem5`。建议统一为：

```text
gem5 FPGAAccelerator
  -> Gem5SlaveTransactor / explicit TLM bridge
  -> SystemC Backend Target
  -> BackendExecutionRequest dispatcher
  -> qebs::DFTHybridSystem or selected accelerator model
  -> BackendExecutionReport writer
```

短期路线：

1. 保留 stub，用于 smoke。
2. 新增 `real_bridge_mode` flag。
3. 在 real bridge mode 下，TLM 请求进入 `Gem5TLMTarget`。
4. `Gem5TLMTarget` 根据 command/address 解码成 `BackendExecutionRequest` 或 compact hardware command。
5. 真正调用 `model/qe_band_solver_model` 主路径，而不是单独的 fixed-constant electrons loop。

### 5.3 修正 TLM address map 和 register semantics

建议统一 address map：

```text
BAR0 offset 0x0000 - 0x0fff: control/status registers
BAR0 offset 0x1000 - 0x1fff: command queue
BAR0 offset 0x2000 - 0x2fff: DMA descriptors
BAR0 offset 0x3000 - 0x3fff: result/status mailbox
Device memory/HBM: separate TLM memory window
```

不要混淆 register offset 和 device memory offset。

需要增加 regression tests：

- MMIO read/write offset 是否命中正确寄存器。
- `REG_ELECTRONS_CMD` 是否触发 exactly one command。
- DMA descriptor 是否写入/读出一致。
- invalid address 是否返回 error。

### 5.4 让 SystemC 主模型输出 structured report

当前模型主要通过 log 输出。建议新增：

```cpp
BackendExecutionReport run_backend_request(const BackendExecutionRequest& request);
```

并写出 JSON：

```text
reports/<candidate_id>.json
```

这个 report 至少来自：

- `SCFRunReport`
- `CompletionSummary`
- `EpisodeResult`
- cluster metrics
- DMA metrics
- fallback metrics
- SystemC elapsed time

### 5.5 给 gem5 增加 ROI 和 stats collection

后端要可比较，就必须明确 ROI。

建议 guest/proxy runtime 支持：

```text
m5_reset_stats before offload loop
m5_dump_stats after offload loop
```

报告中保存：

```text
cpu cycles
cache misses
MMIO access count
DMA bytes
polling iterations
interrupt count
host wait cycles
device busy cycles
```

### 5.6 SE mode 和 FS mode 分层

当前 `qe_fpga_system.py` 使用 `Root(full_system=False)`，这是 SE mode。它适合 proxy runtime 和 smoke，但不适合真实驱动/中断/OS 行为。

建议分层：

```text
SE smoke:
  快速验证用户态 offload API、MMIO/polling、TLM command。

FS smoke:
  验证 Linux driver、interrupt、mmap、DMA buffer、cache flush。

FS timed proxy:
  评估控制开销和系统行为。
```

不要把 SE smoke 结果写成完整系统级性能。

### 5.7 把 QE integration 改成 adapter/proxy runtime

`qe_integration/` 现在有 C/Fortran 接口和 patch，这是可以保留的，但为了通用框架，建议拆成：

```text
runtime_api/
  offload_runtime.h
  offload_runtime.c
  command_descriptor.h

adapters/qe_runtime/
  qe_fpga_offload.f90
  c_bands_patch_or_wrapper

proxy_programs/
  generic_scf_proxy.c
  qe_cbands_proxy.c
  dft_inner_loop_proxy.c
```

第一阶段优先把 proxy runtime 跑稳，不要立刻追求完整 QE patch。

---

## 6. 后端近期任务清单

### P0：两周内必须完成

1. 后端能读取前端 `BackendExecutionRequest` JSON。
2. SystemC standalone 能输出 `BackendExecutionReport` JSON。
3. gem5 SE smoke 能输出 `gem5_systemc_smoke_only` report。
4. 修正/明确 TLM address map。
5. 把 `executeElectrons()` 中 immediate complete 与 timed path 分离。
6. 给 MMIO、DMA、TLM command 做最小 regression test。

### P1：一个月内完成

1. 真正连接 gem5 device 和 SystemC backend target。
2. `DFTHybridSystemGem5` 调用 `qe_band_solver_model` 主路径，而不是独立 fixed-constant loop。
3. 增加 ROI stats。
4. 加入 async command queue / polling / interrupt 三种控制策略。
5. 让后端报告包含 host_wait、device_busy、dma_read/write、fallback、resident reuse。

### P2：两到三个月完成

1. FS mode smoke。
2. QE proxy runtime 或最小 QE patch 跑通。
3. SystemC/gem5 feedback 与前端 calibration 闭环。
4. HLS/RTL evidence parser 接入。
5. 支持非 QE workload 的 proxy runtime。

---

## 7. 后端成功标准

后端推进成功的标志是：

1. 任意 candidate descriptor 都能被后端解释为明确执行模式或明确拒绝。
2. 后端输出的 report 被前端 schema validator 接收。
3. smoke/timed/correctness/implementation 的 claim ceiling 不混淆。
4. gem5 侧能观察到 host 控制开销，而 SystemC 侧能观察到硬件 datapath 和 DMA 开销。
5. QE 只是其中一个 runtime adapter，后端仍能跑 generic proxy workload。
