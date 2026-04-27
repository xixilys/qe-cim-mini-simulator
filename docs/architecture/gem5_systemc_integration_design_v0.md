# gem5 + SystemC 协同模拟系统设计 (v0)

**日期：** 2026-04-20  
**目标：** 实现CPU(gem5) + FPGA(SystemC)的软硬件协同调试能力

---

## 1. 系统架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                    完整异构系统模拟器                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────┐         ┌─────────────────────────┐│
│  │   gem5 (CPU侧)         │         │  SystemC (FPGA侧)       ││
│  │                        │         │                         ││
│  │  ┌──────────────────┐ │         │  ┌──────────────────┐  ││
│  │  │ QE Full Binary   │ │         │  │ ChipTop          │  ││
│  │  │ - electrons()    │ │         │  │ - 4-Cluster      │  ││
│  │  │ - v_of_rho()     │ │         │  │ - CIM Array Core │  ││
│  │  │ - c_bands()      │ │         │  │ - Eigensolver    │  ││
│  │  │ - sum_band()     │ │         │  │                  │  ││
│  │  │ - mix_rho()      │ │         │  └──────────────────┘  ││
│  │  └──────────────────┘ │         │                         ││
│  │                        │         │                         ││
│  │  ┌──────────────────┐ │  TLM    │  ┌──────────────────┐  ││
│  │  │ CPU Model        │ │  2.0    │  │ FPGA Controller  │  ││
│  │  │ - Cache          │◄├─────────┤─►│ - DMA Engine     │  ││
│  │  │ - MMU            │ │ Socket  │  │ - Interrupt      │  ││
│  │  │ - Branch Pred    │ │         │  │ - Status Regs    │  ││
│  │  └──────────────────┘ │         │  └──────────────────┘  ││
│  │                        │         │                         ││
│  │  ┌──────────────────┐ │         │                         ││
│  │  │ PCIe FPGA Device │ │         │                         ││
│  │  │ - Config Space   │ │         │                         ││
│  │  │ - BAR Mapping    │ │         │                         ││
│  │  │ - DMA Engine     │ │         │                         ││
│  │  │ - Interrupt Ctrl │ │         │                         ││
│  │  └──────────────────┘ │         │                         ││
│  │                        │         │                         ││
│  └────────────────────────┘         └─────────────────────────┘│
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              协同调试接口                                 │  │
│  │  - GDB (CPU侧断点、单步、变量查看)                       │  │
│  │  - SystemC波形查看器 (FPGA侧信号追踪)                   │  │
│  │  - 统一时间轴 (CPU cycles ↔ FPGA cycles)                │  │
│  │  - 跨域断点 (CPU调用FPGA时触发)                         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心设计挑战

### 2.1 时间同步

**问题：** gem5和SystemC使用不同的时间模型
- gem5: Tick-based (1 tick = 1 ps)
- SystemC: sc_time (可配置单位)

**解决方案：**
```cpp
// 时间转换层
class TimeSync {
 public:
  // gem5 Tick → SystemC sc_time
  sc_core::sc_time tick_to_sc_time(Tick tick) {
    return sc_core::sc_time(tick, sc_core::SC_PS);
  }
  
  // SystemC sc_time → gem5 Tick
  Tick sc_time_to_tick(sc_core::sc_time t) {
    return t.value() / sc_core::SC_PS;
  }
  
  // 同步点：每次DMA传输、中断、寄存器访问
  void sync_at_transaction() {
    Tick gem5_now = curTick();
    sc_core::sc_time systemc_now = sc_core::sc_time_stamp();
    
    // 确保两边时间一致
    if (gem5_now > sc_time_to_tick(systemc_now)) {
      // SystemC需要追赶
      sc_core::wait(tick_to_sc_time(gem5_now) - systemc_now);
    }
  }
};
```

### 2.2 内存一致性

**问题：** CPU和FPGA共享内存，需要保证Cache一致性

**解决方案：**
```cpp
// gem5侧：FPGA DMA访问触发Cache invalidate
class FPGADMAPort : public MasterPort {
 public:
  void dma_read(Addr addr, size_t size) {
    // 1. 通知Cache系统：FPGA要读这块内存
    cache_->invalidate(addr, size);
    
    // 2. 从内存读取最新数据
    auto data = memory_->read(addr, size);
    
    // 3. 发送到SystemC
    systemc_bridge_->send_dma_data(data);
  }
  
  void dma_write(Addr addr, const uint8_t* data, size_t size) {
    // 1. 写入内存
    memory_->write(addr, data, size);
    
    // 2. 通知Cache系统：这块内存被FPGA修改了
    cache_->invalidate(addr, size);
  }
};
```

### 2.3 通信接口

**问题：** gem5和SystemC运行在同一进程还是不同进程？

**方案A：同进程（推荐）**
- gem5和SystemC编译到同一个可执行文件
- 通过函数调用直接通信
- 优点：速度快，调试方便
- 缺点：需要解决符号冲突

**方案B：不同进程（备选）**
- gem5和SystemC分别运行
- 通过Socket/共享内存通信
- 优点：隔离性好，可以分别调试
- 缺点：通信开销大，同步复杂

**推荐：方案A（同进程）**

---

## 3. gem5侧实现

### 3.1 PCIe FPGA设备模型

```cpp
// src/dev/pci/fpga_accelerator.hh
class FPGAAccelerator : public PciDevice {
 public:
  FPGAAccelerator(const Params& p);
  
  // PCIe配置空间
  Tick readConfig(PacketPtr pkt) override;
  Tick writeConfig(PacketPtr pkt) override;
  
  // BAR空间访问（寄存器读写）
  Tick read(PacketPtr pkt) override;
  Tick write(PacketPtr pkt) override;
  
  // DMA传输
  void startDMA(Addr src, Addr dst, size_t size);
  void dmaComplete();
  
  // 中断
  void sendInterrupt();
  
 private:
  // SystemC桥接
  SystemCBridge* systemc_bridge_;
  
  // 寄存器
  uint32_t control_reg_;
  uint32_t status_reg_;
  uint32_t dma_src_addr_;
  uint32_t dma_dst_addr_;
  uint32_t dma_size_;
  
  // DMA引擎
  DmaPort dma_port_;
};
```

### 3.2 SystemC桥接层

```cpp
// src/systemc/systemc_bridge.hh
class SystemCBridge {
 public:
  SystemCBridge();
  
  // 初始化SystemC模拟器
  void init_systemc();
  
  // 寄存器访问
  uint32_t read_register(uint32_t offset);
  void write_register(uint32_t offset, uint32_t value);
  
  // DMA传输
  void dma_to_fpga(Addr addr, const uint8_t* data, size_t size);
  void dma_from_fpga(Addr addr, uint8_t* data, size_t size);
  
  // 执行c_bands
  void execute_c_bands(const CBandsRequest& req, CBandsResult& result);
  
  // 时间同步
  void sync_time(Tick gem5_tick);
  
 private:
  // SystemC顶层模块
  DFTHybridSystem* systemc_top_;
  
  // 时间同步
  TimeSync time_sync_;
};
```

### 3.3 QE驱动修改

```c
// QE中添加FPGA offload路径
// PW/src/c_bands.f90

subroutine c_bands(...)
  use fpga_offload_module
  implicit none
  
  ! 检查是否有FPGA加速器
  if (fpga_available()) then
    ! 准备FPGA输入
    call prepare_fpga_input(h_psi_data, s_psi_data)
    
    ! 调用FPGA（通过ioctl）
    call fpga_execute_c_bands(h_psi_data, s_psi_data, result)
    
    ! 处理FPGA输出
    call process_fpga_output(result)
  else
    ! CPU路径（原始代码）
    call cpu_c_bands(...)
  endif
end subroutine
```

```c
// 用户态驱动（C代码）
// fpga_offload.c

#include <fcntl.h>
#include <sys/ioctl.h>

int fpga_fd = -1;

int fpga_available() {
  if (fpga_fd < 0) {
    fpga_fd = open("/dev/fpga0", O_RDWR);
  }
  return fpga_fd >= 0;
}

void fpga_execute_c_bands(void* h_psi, void* s_psi, void* result) {
  struct fpga_request req;
  req.h_psi_addr = (uint64_t)h_psi;
  req.s_psi_addr = (uint64_t)s_psi;
  req.result_addr = (uint64_t)result;
  
  // ioctl触发gem5中的PCIe设备
  ioctl(fpga_fd, FPGA_IOCTL_EXECUTE, &req);
}
```

---

## 4. SystemC侧实现

### 4.1 gem5接口模块

```cpp
// model/qe_band_solver_model/src/gem5_interface.hpp
class Gem5Interface : public sc_core::sc_module {
 public:
  SC_HAS_PROCESS(Gem5Interface);
  
  Gem5Interface(sc_core::sc_module_name name);
  
  // 接收gem5的寄存器访问
  uint32_t read_register(uint32_t offset);
  void write_register(uint32_t offset, uint32_t value);
  
  // 接收gem5的DMA数据
  void receive_dma_data(const uint8_t* data, size_t size);
  
  // 发送DMA数据到gem5
  void send_dma_data(const uint8_t* data, size_t size);
  
  // 发送中断到gem5
  void send_interrupt();
  
  // 执行c_bands请求
  void execute_c_bands_request();
  
 private:
  // 连接到DFTHybridSystem
  DFTHybridSystem* dft_system_;
  
  // 寄存器
  uint32_t control_reg_;
  uint32_t status_reg_;
  
  // DMA缓冲区
  std::vector<uint8_t> dma_buffer_;
  
  // gem5回调函数指针
  std::function<void(const uint8_t*, size_t)> gem5_dma_callback_;
  std::function<void()> gem5_interrupt_callback_;
};
```

### 4.2 修改DFTHybridSystem

```cpp
// model/qe_band_solver_model/src/dft_hybrid_system.cpp

// 添加gem5接口
DFTHybridSystem::DFTHybridSystem(...) {
  // 原有初始化...
  
  // 添加gem5接口
  gem5_interface_ = new Gem5Interface("gem5_interface");
  gem5_interface_->set_dft_system(this);
}

// 从gem5接收c_bands请求
void DFTHybridSystem::handle_gem5_request(const CBandsRequest& req) {
  // 执行c_bands（复用现有代码）
  auto result = run_c_bands_episode(req);
  
  // 通过DMA返回结果到gem5
  gem5_interface_->send_dma_data(
    reinterpret_cast<const uint8_t*>(&result), 
    sizeof(result)
  );
  
  // 发送中断通知gem5
  gem5_interface_->send_interrupt();
}
```

---

## 5. 协同调试能力

### 5.1 GDB调试（CPU侧）

```bash
# 启动gem5并等待GDB连接
./build/X86/gem5.opt --debug-flags=FPGAAccelerator \
  --remote-gdb-port=7000 \
  configs/qe_fpga_system.py

# 另一个终端连接GDB
gdb /path/to/qe.x
(gdb) target remote localhost:7000
(gdb) break c_bands_  # Fortran函数断点
(gdb) break fpga_execute_c_bands  # FPGA调用断点
(gdb) continue
```

### 5.2 SystemC波形查看

```cpp
// 在SystemC中启用VCD波形输出
int sc_main(int argc, char* argv[]) {
  // 创建VCD文件
  sc_trace_file* tf = sc_create_vcd_trace_file("fpga_waveform");
  
  // 追踪关键信号
  sc_trace(tf, dft_system->chip_top->cluster_a->ref_cycles, "cluster_a_cycles");
  sc_trace(tf, dft_system->chip_top->cluster_b->ref_cycles, "cluster_b_cycles");
  sc_trace(tf, dft_system->chip_top->cluster_c->ref_cycles, "cluster_c_cycles");
  sc_trace(tf, dft_system->chip_top->cluster_d->ref_cycles, "cluster_d_cycles");
  
  // 运行仿真
  sc_start();
  
  // 关闭VCD文件
  sc_close_vcd_trace_file(tf);
  return 0;
}
```

### 5.3 统一时间轴

```python
# 分析脚本：合并gem5和SystemC的trace
import pandas as pd

# 读取gem5 trace
gem5_trace = pd.read_csv('gem5_trace.csv')
gem5_trace['time_ps'] = gem5_trace['tick']  # gem5 tick = ps

# 读取SystemC trace
systemc_trace = pd.read_csv('systemc_trace.csv')
systemc_trace['time_ps'] = systemc_trace['time_ns'] * 1000

# 合并到统一时间轴
merged = pd.merge_asof(
  gem5_trace.sort_values('time_ps'),
  systemc_trace.sort_values('time_ps'),
  on='time_ps',
  direction='nearest'
)

# 可视化
import matplotlib.pyplot as plt
plt.figure(figsize=(15, 8))
plt.subplot(2, 1, 1)
plt.plot(merged['time_ps'], merged['cpu_ipc'], label='CPU IPC')
plt.subplot(2, 1, 2)
plt.plot(merged['time_ps'], merged['fpga_utilization'], label='FPGA Utilization')
plt.show()
```

---

## 6. 实施计划（待探索任务完成后细化）

### Phase 1: gem5基础环境（Week 1-2）
- [ ] 搭建gem5 Full System环境
- [ ] 交叉编译QE到gem5目标架构
- [ ] 验证QE在gem5中运行

### Phase 2: PCIe设备模型（Week 3-4）
- [ ] 实现FPGAAccelerator PCIe设备
- [ ] 实现DMA引擎
- [ ] 实现中断控制器

### Phase 3: SystemC桥接（Week 5-6）
- [ ] 实现SystemCBridge
- [ ] 实现时间同步机制
- [ ] 实现内存一致性协议

### Phase 4: QE驱动修改（Week 7-8）
- [ ] 修改c_bands添加FPGA offload路径
- [ ] 实现用户态驱动
- [ ] 实现内核态驱动（如果需要）

### Phase 5: 集成测试（Week 9-12）
- [ ] 端到端测试：QE完整流程
- [ ] 性能验证：对比真实trace
- [ ] 调试工具验证：GDB + 波形查看器

### Phase 6: 优化和文档（Week 13-16）
- [ ] 仿真速度优化
- [ ] 协同调试工具完善
- [ ] 用户文档和示例

---

## 7. 待探索任务完成后补充

**等待中的探索任务：**
1. ✅ gem5-SystemC集成架构（已完成）
2. ⏳ QE代码gem5移植
3. ⏳ gem5 FPGA加速器建模

**待补充内容：**
- gem5-SystemC TLM接口的具体实现
- QE交叉编译的详细步骤
- PCIe设备模型的代码示例
- 时间同步的详细协议
- 内存一致性的实现细节

---

## 参考文档

- gem5官方文档：https://www.gem5.org/documentation/
- SystemC TLM 2.0规范：https://www.accellera.org/downloads/standards/systemc
- PCIe规范：https://pcisig.com/specifications
- QE源码：https://gitlab.com/QEF/q-e

**状态：** 初步架构设计完成，等待探索任务结果补充细节
