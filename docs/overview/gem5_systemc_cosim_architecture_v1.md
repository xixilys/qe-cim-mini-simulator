# gem5+SystemC 协同仿真架构设计 v1

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         gem5 Simulator                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  CPU Model (X86/ARM)                                      │  │
│  │  - Timing/Detailed/KVM modes                              │  │
│  │  - Running QE binary (electrons, c_bands, etc.)           │  │
│  └─────────────────┬─────────────────────────────────────────┘  │
│                    │ Memory Bus                                 │
│  ┌─────────────────┴─────────────────────────────────────────┐  │
│  │  PCIe Device: FPGAAccelerator                             │  │
│  │  - MMIO registers (control/status)                        │  │
│  │  - DMA engine (host ↔ device memory)                      │  │
│  │  - Interrupt controller                                   │  │
│  │  - TLM-2.0 initiator socket → SystemC                     │  │
│  └─────────────────┬─────────────────────────────────────────┘  │
└────────────────────┼─────────────────────────────────────────────┘
                     │ TLM-2.0 Interface
                     │ (b_transport / nb_transport)
┌────────────────────┼─────────────────────────────────────────────┐
│                    ▼                                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SystemC TLM-2.0 Target: FPGA_Top                       │    │
│  │  - Transaction decoder                                  │    │
│  │  - Address routing                                      │    │
│  └─────────────────┬───────────────────────────────────────┘    │
│                    │                                             │
│  ┌─────────────────┴───────────────────────────────────────┐    │
│  │  DFTHybridSystem (existing SystemC model)               │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │  ChipTop                                        │    │    │
│  │  │  ┌───────────────────────────────────────────┐ │    │    │
│  │  │  │  ClusterGraphExecutor                     │ │    │    │
│  │  │  │  - ClusterA (CIM/Traditional GEMM)        │ │    │    │
│  │  │  │  - ClusterB (Reduced Build)               │ │    │    │
│  │  │  │  - ClusterC (Hardware Diag)               │ │    │    │
│  │  │  │  - ClusterD (Refresh/Residual)            │ │    │    │
│  │  │  └───────────────────────────────────────────┘ │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                     SystemC Kernel                               │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 关键设计决策

### 2.1 集成方式选择

**选择：gem5作为主仿真器，SystemC作为协处理器模型**

理由：
- gem5提供完整的CPU/内存/总线模型，支持运行真实QE二进制
- SystemC专注于FPGA加速器的cycle-accurate建模
- 通过TLM-2.0实现松耦合，各自独立演进

### 2.2 时间同步策略

**选择：事件驱动同步 (Event-Driven Synchronization)**

```cpp
// gem5侧：每次MMIO/DMA操作触发SystemC事件
void FPGAAccelerator::write(PacketPtr pkt) {
    // 1. 解析gem5 packet
    Addr addr = pkt->getAddr();
    uint64_t data = pkt->getUintX(ByteOrder::little);
    
    // 2. 转换为TLM transaction
    tlm::tlm_generic_payload trans;
    trans.set_command(tlm::TLM_WRITE_COMMAND);
    trans.set_address(addr);
    trans.set_data_ptr((unsigned char*)&data);
    
    // 3. 调用SystemC (blocking)
    sc_time delay = sc_time(0, SC_NS);
    tlm_socket->b_transport(trans, delay);
    
    // 4. 根据SystemC返回的delay调度gem5事件
    schedule(responseEvent, curTick() + delay.value() * SimClock::Int::ns);
}
```

### 2.3 内存模型

**选择：Shared Memory + DMA Copy**

- gem5维护主内存（host memory）
- SystemC维护设备内存（device memory）
- DMA引擎负责数据传输，模拟真实PCIe带宽

```cpp
// DMA传输模型
class DMAEngine : public sc_module {
    void transfer(uint64_t host_addr, uint64_t dev_addr, size_t bytes) {
        // 计算传输时间：bytes / PCIe_bandwidth
        double transfer_time_ns = bytes / (16.0 * 1e9 / 8); // PCIe Gen4 x16
        wait(transfer_time_ns, SC_NS);
        
        // 通过gem5回调读取host memory
        gem5_read_memory(host_addr, dev_buffer, bytes);
        
        // 写入SystemC device memory
        memcpy(device_memory + dev_addr, dev_buffer, bytes);
    }
};
```

## 3. 实施路线图

### Phase 0: 环境搭建 (Week 1)
- [ ] 编译gem5 (支持SystemC TLM)
- [ ] 验证gem5-SystemC示例运行
- [ ] 准备QE交叉编译工具链

### Phase 1: gem5 FPGA设备骨架 (Week 2)
- [ ] 创建FPGAAccelerator PCIe设备类
- [ ] 实现MMIO寄存器空间
- [ ] 实现基础DMA引擎
- [ ] 添加TLM-2.0 initiator socket

### Phase 2: SystemC TLM接口 (Week 3)
- [ ] 创建FPGA_Top TLM target模块
- [ ] 实现b_transport方法
- [ ] 连接到现有DFTHybridSystem
- [ ] 添加事务解码和路由逻辑

### Phase 3: QE代码修改 (Week 4-5)
- [ ] 在c_bands中添加FPGA offload路径
- [ ] 实现用户态驱动接口（mmap, ioctl）
- [ ] 添加矩阵数据打包/解包逻辑
- [ ] 处理Fortran/C接口

### Phase 4: 端到端集成 (Week 6)
- [ ] 完整electrons循环测试
- [ ] 性能数据收集
- [ ] 调试工具集成（GDB + SystemC波形）

### Phase 5: 优化和验证 (Week 7-8)
- [ ] KVM加速模式（快速跳过非关键代码）
- [ ] Checkpoint/Restore支持
- [ ] 多workload验证（si4, si8, graphene等）

## 4. 关键代码模块

### 4.1 gem5侧：FPGAAccelerator设备

```cpp
// src/dev/fpga/fpga_accelerator.hh
class FPGAAccelerator : public PciDevice {
  public:
    // MMIO寄存器地址
    enum Registers {
        REG_CONTROL = 0x0000,      // 控制寄存器
        REG_STATUS = 0x0004,       // 状态寄存器
        REG_DMA_SRC = 0x0008,      // DMA源地址
        REG_DMA_DST = 0x0010,      // DMA目标地址
        REG_DMA_SIZE = 0x0018,     // DMA传输大小
        REG_MATRIX_N = 0x0020,     // 矩阵维度N
        REG_MATRIX_M = 0x0024,     // 矩阵维度M
        REG_COMPUTE_START = 0x0028 // 启动计算
    };
    
    Tick read(PacketPtr pkt) override;
    Tick write(PacketPtr pkt) override;
    
  private:
    // TLM-2.0 socket连接到SystemC
    tlm_utils::simple_initiator_socket<FPGAAccelerator> tlm_socket;
    
    // DMA引擎
    void startDMA();
    void onDMAComplete();
    
    // 中断控制
    void raiseInterrupt();
};
```

### 4.2 SystemC侧：TLM Target接口

```cpp
// model/qe_band_solver_model/include/fpga_top_tlm.hpp
class FPGA_Top_TLM : public sc_module {
  public:
    // TLM-2.0 target socket
    tlm_utils::simple_target_socket<FPGA_Top_TLM> target_socket;
    
    SC_CTOR(FPGA_Top_TLM) : target_socket("target_socket") {
        target_socket.register_b_transport(this, &FPGA_Top_TLM::b_transport);
        
        // 实例化现有的DFTHybridSystem
        dft_system = new DFTHybridSystem("dft_hybrid_system", config);
    }
    
    void b_transport(tlm::tlm_generic_payload& trans, sc_time& delay) {
        tlm::tlm_command cmd = trans.get_command();
        uint64_t addr = trans.get_address();
        unsigned char* data = trans.get_data_ptr();
        
        if (cmd == tlm::TLM_WRITE_COMMAND) {
            handle_write(addr, data, delay);
        } else {
            handle_read(addr, data, delay);
        }
        
        trans.set_response_status(tlm::TLM_OK_RESPONSE);
    }
    
  private:
    DFTHybridSystem* dft_system;
    
    void handle_write(uint64_t addr, unsigned char* data, sc_time& delay);
    void handle_read(uint64_t addr, unsigned char* data, sc_time& delay);
};
```

### 4.3 QE侧：FPGA Offload接口

```fortran
! QE-7.5/PW/src/c_bands_fpga.f90
SUBROUTINE c_bands_fpga(...)
    USE fpga_driver, ONLY: fpga_init, fpga_offload_subspace, fpga_finalize
    
    ! 初始化FPGA设备
    CALL fpga_init()
    
    DO ik = 1, nks
        ! ... 准备数据 ...
        
        ! Offload到FPGA
        CALL fpga_offload_subspace(h_matrix, s_matrix, n, m, eigenvalues, eigenvectors)
        
        ! ... 后处理 ...
    END DO
    
    CALL fpga_finalize()
END SUBROUTINE
```

```c
// QE-7.5/PW/src/fpga_driver.c
#include <fcntl.h>
#include <sys/mman.h>

static int fpga_fd;
static volatile uint32_t* fpga_regs;

void fpga_init_() {
    fpga_fd = open("/dev/fpga0", O_RDWR);
    fpga_regs = mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fpga_fd, 0);
}

void fpga_offload_subspace_(double* h, double* s, int* n, int* m, 
                            double* evals, double* evecs) {
    // 1. DMA传输矩阵到设备
    fpga_regs[REG_DMA_SRC] = (uint64_t)h;
    fpga_regs[REG_DMA_DST] = DEVICE_H_ADDR;
    fpga_regs[REG_DMA_SIZE] = (*n) * (*m) * sizeof(double);
    fpga_regs[REG_CONTROL] = CMD_DMA_START;
    
    // 2. 等待DMA完成
    while (!(fpga_regs[REG_STATUS] & STATUS_DMA_DONE));
    
    // 3. 启动计算
    fpga_regs[REG_MATRIX_N] = *n;
    fpga_regs[REG_MATRIX_M] = *m;
    fpga_regs[REG_COMPUTE_START] = 1;
    
    // 4. 等待计算完成（中断或轮询）
    while (!(fpga_regs[REG_STATUS] & STATUS_COMPUTE_DONE));
    
    // 5. DMA传输结果回host
    fpga_regs[REG_DMA_SRC] = DEVICE_RESULT_ADDR;
    fpga_regs[REG_DMA_DST] = (uint64_t)evals;
    fpga_regs[REG_DMA_SIZE] = (*m) * sizeof(double);
    fpga_regs[REG_CONTROL] = CMD_DMA_START;
    
    while (!(fpga_regs[REG_STATUS] & STATUS_DMA_DONE));
}
```

## 5. 性能预期

### 5.1 仿真速度

- **KVM模式**：接近原生速度（用于快速跳过初始化代码）
- **Timing模式**：~1 MIPS（用于关键路径详细分析）
- **SystemC部分**：cycle-accurate，取决于FPGA时钟频率设置

### 5.2 精度

- **CPU执行**：指令级精确（gem5 Detailed CPU）
- **内存访问**：时序精确（gem5 memory system）
- **FPGA计算**：cycle-accurate（SystemC模型）
- **PCIe传输**：带宽/延迟模型（可配置）

### 5.3 覆盖范围

完整的QE electrons循环：
- Phase A: 初始化（CPU，gem5模拟）
- Phase B: c_bands主循环（CPU+FPGA协同）
  - CPU: 矩阵准备、结果后处理
  - FPGA: 子空间迭代、特征值求解
- Phase C: 电荷密度更新（CPU，gem5模拟）
- Phase D: 收敛检查（CPU，gem5模拟）

## 6. 调试和验证工具

### 6.1 GDB集成

```bash
# 启动gem5并等待GDB连接
./build/X86/gem5.opt --debug-flags=FPGAAccelerator \
    --remote-gdb-port=7000 configs/qe_fpga.py

# 另一个终端连接GDB
gdb soft/qe-7.5/bin/pw.x
(gdb) target remote :7000
(gdb) break c_bands_fpga_
(gdb) continue
```

### 6.2 SystemC波形查看

```cpp
// 在sc_main中启用VCD trace
sc_trace_file* tf = sc_create_vcd_trace_file("fpga_trace");
sc_trace(tf, dft_system->chip_->cluster_graph_executor_->cluster_a_->signal, "cluster_a");
// ... 添加更多信号 ...
sc_start();
sc_close_vcd_trace_file(tf);
```

```bash
# 使用GTKWave查看波形
gtkwave fpga_trace.vcd
```

### 6.3 性能分析

```python
# 解析gem5统计数据
import m5.stats
stats.dump()  # 输出到m5out/stats.txt

# 关键指标：
# - system.cpu.numCycles: CPU总周期数
# - system.fpga.dma_bytes: DMA传输字节数
# - system.fpga.compute_cycles: FPGA计算周期数
# - system.fpga.offload_count: Offload次数
```

## 7. 风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| gem5-SystemC时间同步复杂 | 高 | 使用成熟的TLM-2.0标准接口 |
| QE Fortran代码修改困难 | 中 | 最小化修改，只在c_bands添加offload |
| 仿真速度过慢 | 中 | KVM模式加速非关键路径 |
| 内存一致性问题 | 高 | 显式DMA传输，避免共享内存 |
| 调试困难 | 中 | 分阶段验证，先单独测试再集成 |

## 8. 下一步行动

1. **立即开始**：Phase 0环境搭建
2. **Week 1目标**：gem5编译成功，运行TLM示例
3. **Week 2目标**：FPGAAccelerator设备骨架完成
4. **Week 3目标**：SystemC TLM接口连接成功
5. **Week 4目标**：QE代码修改完成，首次端到端运行

## 9. 成功标准

- [ ] gem5能够运行完整的QE pw.x二进制
- [ ] c_bands中的矩阵计算能够offload到SystemC FPGA模型
- [ ] 端到端仿真能够完成至少1个SCF迭代
- [ ] 性能数据与standalone SystemC模型一致（±5%）
- [ ] 支持GDB调试和SystemC波形查看
- [ ] 仿真速度可接受（1个SCF迭代 < 1小时）
