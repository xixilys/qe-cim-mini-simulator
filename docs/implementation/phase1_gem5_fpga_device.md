# Phase 1: gem5 FPGA加速器设备实现

**目标：** 在gem5中创建FPGAAccelerator PCIe设备，支持MMIO和DMA

---

## 1. 文件结构

```
gem5/
├── src/dev/fpga/
│   ├── FPGAAccelerator.py          # Python配置
│   ├── fpga_accelerator.hh         # C++头文件
│   ├── fpga_accelerator.cc         # C++实现
│   ├── fpga_dma.hh                 # DMA引擎头文件
│   ├── fpga_dma.cc                 # DMA引擎实现
│   └── SConscript                  # 编译配置
└── configs/fpga/
    └── qe_fpga_system.py           # 系统配置脚本
```

---

## 2. 设备类定义

### 2.1 头文件：fpga_accelerator.hh

```cpp
// src/dev/fpga/fpga_accelerator.hh
#ifndef __DEV_FPGA_FPGA_ACCELERATOR_HH__
#define __DEV_FPGA_FPGA_ACCELERATOR_HH__

#include "dev/pci/device.hh"
#include "dev/io_device.hh"
#include "params/FPGAAccelerator.hh"
#include "systemc/tlm"

namespace gem5 {

class FPGAAccelerator : public PciDevice {
  public:
    typedef FPGAAcceleratorParams Params;
    FPGAAccelerator(const Params &p);
    ~FPGAAccelerator();

    // PCI配置空间访问
    Tick readConfig(PacketPtr pkt) override;
    Tick writeConfig(PacketPtr pkt) override;

    // BAR空间访问（MMIO寄存器）
    Tick read(PacketPtr pkt) override;
    Tick write(PacketPtr pkt) override;

    // 初始化
    void init() override;
    void startup() override;

    // 序列化（checkpoint支持）
    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

  private:
    // MMIO寄存器地址映射
    enum Registers {
        REG_CONTROL       = 0x0000,  // 控制寄存器
        REG_STATUS        = 0x0004,  // 状态寄存器
        REG_INTERRUPT     = 0x0008,  // 中断控制
        REG_DMA_SRC_LO    = 0x0010,  // DMA源地址（低32位）
        REG_DMA_SRC_HI    = 0x0014,  // DMA源地址（高32位）
        REG_DMA_DST_LO    = 0x0018,  // DMA目标地址（低32位）
        REG_DMA_DST_HI    = 0x001C,  // DMA目标地址（高32位）
        REG_DMA_SIZE      = 0x0020,  // DMA传输大小
        REG_DMA_CONTROL   = 0x0024,  // DMA控制
        REG_MATRIX_N      = 0x0030,  // 矩阵维度N
        REG_MATRIX_M      = 0x0034,  // 矩阵维度M
        REG_MATRIX_K      = 0x0038,  // 矩阵维度K
        REG_COMPUTE_CMD   = 0x0040,  // 计算命令
        REG_COMPUTE_STATUS= 0x0044,  // 计算状态
        REG_RESULT_ADDR   = 0x0050,  // 结果地址
        REG_RESULT_SIZE   = 0x0054,  // 结果大小
    };

    // 控制寄存器位定义
    enum ControlBits {
        CTRL_RESET        = (1 << 0),
        CTRL_ENABLE       = (1 << 1),
        CTRL_IRQ_ENABLE   = (1 << 2),
    };

    // 状态寄存器位定义
    enum StatusBits {
        STATUS_READY      = (1 << 0),
        STATUS_BUSY       = (1 << 1),
        STATUS_ERROR      = (1 << 2),
        STATUS_DMA_DONE   = (1 << 3),
        STATUS_COMPUTE_DONE = (1 << 4),
    };

    // 寄存器存储
    uint32_t controlReg;
    uint32_t statusReg;
    uint32_t interruptReg;
    uint64_t dmaSrcAddr;
    uint64_t dmaDstAddr;
    uint32_t dmaSize;
    uint32_t matrixN, matrixM, matrixK;

    // DMA引擎
    class DMAEngine {
      public:
        DMAEngine(FPGAAccelerator *parent);
        void startTransfer(Addr src, Addr dst, size_t size, bool toDevice);
        void onTransferComplete();
        bool isBusy() const { return busy; }

      private:
        FPGAAccelerator *parent;
        bool busy;
        Addr currentSrc, currentDst;
        size_t remainingBytes;
        
        // DMA回调
        void dmaReadDone();
        void dmaWriteDone();
    };
    
    DMAEngine *dmaEngine;

    // TLM-2.0 socket连接到SystemC
    tlm_utils::simple_initiator_socket<FPGAAccelerator> *tlmSocket;
    
    // SystemC通信
    void sendTLMTransaction(tlm::tlm_command cmd, uint64_t addr, 
                           uint8_t *data, size_t size);
    void executeCompute();

    // 中断控制
    void raiseInterrupt();
    void clearInterrupt();

    // 辅助函数
    uint32_t readRegister(Addr offset);
    void writeRegister(Addr offset, uint32_t value);
};

} // namespace gem5

#endif // __DEV_FPGA_FPGA_ACCELERATOR_HH__
```

### 2.2 实现文件：fpga_accelerator.cc

```cpp
// src/dev/fpga/fpga_accelerator.cc
#include "dev/fpga/fpga_accelerator.hh"
#include "base/trace.hh"
#include "debug/FPGAAccelerator.hh"
#include "mem/packet.hh"
#include "mem/packet_access.hh"

namespace gem5 {

FPGAAccelerator::FPGAAccelerator(const Params &p)
    : PciDevice(p),
      controlReg(0),
      statusReg(STATUS_READY),
      interruptReg(0),
      dmaSrcAddr(0),
      dmaDstAddr(0),
      dmaSize(0),
      matrixN(0),
      matrixM(0),
      matrixK(0)
{
    // 配置PCI设备
    config.vendor = 0x1234;  // 自定义vendor ID
    config.device = 0x5678;  // 自定义device ID
    config.command = 0x0000;
    config.status = 0x0000;
    config.revision = 0x00;
    config.progIF = 0x00;
    config.subClassCode = 0x80;  // Other system peripheral
    config.classCode = 0x08;     // Base system peripheral
    config.cacheLineSize = 0;
    config.latencyTimer = 0;
    config.headerType = 0x00;
    config.bist = 0x00;

    // 配置BAR0：MMIO寄存器空间（4KB）
    BARSize[0] = 4096;
    BARAddrs[0] = 0;

    // 创建DMA引擎
    dmaEngine = new DMAEngine(this);

    // 创建TLM socket（如果启用SystemC）
    #ifdef USE_SYSTEMC
    tlmSocket = new tlm_utils::simple_initiator_socket<FPGAAccelerator>(
        "tlm_socket");
    #endif

    DPRINTF(FPGAAccelerator, "FPGAAccelerator created\n");
}

FPGAAccelerator::~FPGAAccelerator() {
    delete dmaEngine;
    #ifdef USE_SYSTEMC
    delete tlmSocket;
    #endif
}

void FPGAAccelerator::init() {
    PciDevice::init();
    DPRINTF(FPGAAccelerator, "FPGAAccelerator initialized\n");
}

void FPGAAccelerator::startup() {
    PciDevice::startup();
    DPRINTF(FPGAAccelerator, "FPGAAccelerator started\n");
}

Tick FPGAAccelerator::read(PacketPtr pkt) {
    Addr offset = pkt->getAddr() - BARAddrs[0];
    assert(pkt->getSize() == 4);  // 只支持32位访问

    uint32_t value = readRegister(offset);
    pkt->setUintX(value, ByteOrder::little);

    DPRINTF(FPGAAccelerator, "MMIO read: offset=0x%x value=0x%x\n", 
            offset, value);

    pkt->makeAtomicResponse();
    return pioDelay;
}

Tick FPGAAccelerator::write(PacketPtr pkt) {
    Addr offset = pkt->getAddr() - BARAddrs[0];
    assert(pkt->getSize() == 4);

    uint32_t value = pkt->getUintX(ByteOrder::little);
    writeRegister(offset, value);

    DPRINTF(FPGAAccelerator, "MMIO write: offset=0x%x value=0x%x\n", 
            offset, value);

    pkt->makeAtomicResponse();
    return pioDelay;
}

uint32_t FPGAAccelerator::readRegister(Addr offset) {
    switch (offset) {
        case REG_CONTROL:
            return controlReg;
        case REG_STATUS:
            return statusReg;
        case REG_INTERRUPT:
            return interruptReg;
        case REG_DMA_SRC_LO:
            return (uint32_t)(dmaSrcAddr & 0xFFFFFFFF);
        case REG_DMA_SRC_HI:
            return (uint32_t)(dmaSrcAddr >> 32);
        case REG_DMA_DST_LO:
            return (uint32_t)(dmaDstAddr & 0xFFFFFFFF);
        case REG_DMA_DST_HI:
            return (uint32_t)(dmaDstAddr >> 32);
        case REG_DMA_SIZE:
            return dmaSize;
        case REG_MATRIX_N:
            return matrixN;
        case REG_MATRIX_M:
            return matrixM;
        case REG_MATRIX_K:
            return matrixK;
        case REG_COMPUTE_STATUS:
            return statusReg;
        default:
            warn("FPGAAccelerator: read from unknown register 0x%x\n", offset);
            return 0;
    }
}

void FPGAAccelerator::writeRegister(Addr offset, uint32_t value) {
    switch (offset) {
        case REG_CONTROL:
            controlReg = value;
            if (value & CTRL_RESET) {
                // 复位设备
                statusReg = STATUS_READY;
                controlReg &= ~CTRL_RESET;
                DPRINTF(FPGAAccelerator, "Device reset\n");
            }
            break;

        case REG_DMA_SRC_LO:
            dmaSrcAddr = (dmaSrcAddr & 0xFFFFFFFF00000000ULL) | value;
            break;

        case REG_DMA_SRC_HI:
            dmaSrcAddr = (dmaSrcAddr & 0xFFFFFFFF) | ((uint64_t)value << 32);
            break;

        case REG_DMA_DST_LO:
            dmaDstAddr = (dmaDstAddr & 0xFFFFFFFF00000000ULL) | value;
            break;

        case REG_DMA_DST_HI:
            dmaDstAddr = (dmaDstAddr & 0xFFFFFFFF) | ((uint64_t)value << 32);
            break;

        case REG_DMA_SIZE:
            dmaSize = value;
            break;

        case REG_DMA_CONTROL:
            if (value == 1 && !dmaEngine->isBusy()) {
                // 启动DMA传输
                statusReg |= STATUS_BUSY;
                statusReg &= ~STATUS_DMA_DONE;
                bool toDevice = (value & 0x2) != 0;  // bit 1: direction
                dmaEngine->startTransfer(dmaSrcAddr, dmaDstAddr, dmaSize, toDevice);
                DPRINTF(FPGAAccelerator, "DMA started: src=0x%lx dst=0x%lx size=%d\n",
                        dmaSrcAddr, dmaDstAddr, dmaSize);
            }
            break;

        case REG_MATRIX_N:
            matrixN = value;
            break;

        case REG_MATRIX_M:
            matrixM = value;
            break;

        case REG_MATRIX_K:
            matrixK = value;
            break;

        case REG_COMPUTE_CMD:
            if (value == 1) {
                // 启动计算
                executeCompute();
            }
            break;

        default:
            warn("FPGAAccelerator: write to unknown register 0x%x\n", offset);
            break;
    }
}

void FPGAAccelerator::executeCompute() {
    DPRINTF(FPGAAccelerator, "Starting compute: N=%d M=%d K=%d\n",
            matrixN, matrixM, matrixK);

    statusReg |= STATUS_BUSY;
    statusReg &= ~STATUS_COMPUTE_DONE;

    #ifdef USE_SYSTEMC
    // 通过TLM发送计算请求到SystemC
    uint8_t cmd_data[16];
    *(uint32_t*)&cmd_data[0] = matrixN;
    *(uint32_t*)&cmd_data[4] = matrixM;
    *(uint32_t*)&cmd_data[8] = matrixK;
    *(uint32_t*)&cmd_data[12] = 1;  // compute command

    sendTLMTransaction(tlm::TLM_WRITE_COMMAND, REG_COMPUTE_CMD, 
                      cmd_data, sizeof(cmd_data));
    #else
    // 模拟计算延迟
    schedule(computeDoneEvent, curTick() + 1000000);  // 1ms
    #endif
}

void FPGAAccelerator::sendTLMTransaction(tlm::tlm_command cmd, uint64_t addr,
                                         uint8_t *data, size_t size) {
    #ifdef USE_SYSTEMC
    tlm::tlm_generic_payload trans;
    trans.set_command(cmd);
    trans.set_address(addr);
    trans.set_data_ptr(data);
    trans.set_data_length(size);
    trans.set_streaming_width(size);
    trans.set_byte_enable_ptr(nullptr);
    trans.set_dmi_allowed(false);
    trans.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);

    sc_time delay = sc_time(0, SC_NS);
    (*tlmSocket)->b_transport(trans, delay);

    if (trans.is_response_error()) {
        warn("TLM transaction failed\n");
    }

    // 根据SystemC返回的delay调度gem5事件
    if (delay.value() > 0) {
        Tick gem5_delay = delay.value() * SimClock::Int::ns;
        schedule(tlmResponseEvent, curTick() + gem5_delay);
    }
    #endif
}

void FPGAAccelerator::raiseInterrupt() {
    interruptReg = 1;
    if (controlReg & CTRL_IRQ_ENABLE) {
        intrPost();
        DPRINTF(FPGAAccelerator, "Interrupt raised\n");
    }
}

void FPGAAccelerator::clearInterrupt() {
    interruptReg = 0;
    intrClear();
    DPRINTF(FPGAAccelerator, "Interrupt cleared\n");
}

// DMA引擎实现
FPGAAccelerator::DMAEngine::DMAEngine(FPGAAccelerator *p)
    : parent(p), busy(false), currentSrc(0), currentDst(0), remainingBytes(0) {
}

void FPGAAccelerator::DMAEngine::startTransfer(Addr src, Addr dst, 
                                               size_t size, bool toDevice) {
    busy = true;
    currentSrc = src;
    currentDst = dst;
    remainingBytes = size;

    // 简化实现：一次性传输
    // 实际应该分块传输，考虑PCIe带宽限制
    
    // 计算传输延迟：bytes / bandwidth
    // PCIe Gen4 x16: 16 GB/s = 16 * 1e9 bytes/s
    double bandwidth_bytes_per_ns = 16.0;  // 16 bytes/ns
    Tick transfer_delay = (Tick)(size / bandwidth_bytes_per_ns);

    DPRINTF(FPGAAccelerator, "DMA transfer: %d bytes, delay=%d ticks\n",
            size, transfer_delay);

    // 调度DMA完成事件
    parent->schedule(parent->dmaCompleteEvent, curTick() + transfer_delay);
}

void FPGAAccelerator::DMAEngine::onTransferComplete() {
    busy = false;
    parent->statusReg &= ~STATUS_BUSY;
    parent->statusReg |= STATUS_DMA_DONE;
    parent->raiseInterrupt();
    
    DPRINTF(FPGAAccelerator, "DMA transfer complete\n");
}

void FPGAAccelerator::serialize(CheckpointOut &cp) const {
    PciDevice::serialize(cp);
    SERIALIZE_SCALAR(controlReg);
    SERIALIZE_SCALAR(statusReg);
    SERIALIZE_SCALAR(dmaSrcAddr);
    SERIALIZE_SCALAR(dmaDstAddr);
    SERIALIZE_SCALAR(dmaSize);
}

void FPGAAccelerator::unserialize(CheckpointIn &cp) {
    PciDevice::unserialize(cp);
    UNSERIALIZE_SCALAR(controlReg);
    UNSERIALIZE_SCALAR(statusReg);
    UNSERIALIZE_SCALAR(dmaSrcAddr);
    UNSERIALIZE_SCALAR(dmaDstAddr);
    UNSERIALIZE_SCALAR(dmaSize);
}

} // namespace gem5
```

---

## 3. Python配置

### 3.1 设备参数定义：FPGAAccelerator.py

```python
# src/dev/fpga/FPGAAccelerator.py
from m5.params import *
from m5.proxy import *
from m5.objects.PciDevice import PciDevice

class FPGAAccelerator(PciDevice):
    type = 'FPGAAccelerator'
    cxx_header = "dev/fpga/fpga_accelerator.hh"
    cxx_class = 'gem5::FPGAAccelerator'

    # PCI配置
    VendorID = 0x1234
    DeviceID = 0x5678
    SubsystemID = 0x0000
    SubsystemVendorID = 0x0000
    RevisionID = 0x00
    ClassCode = 0x08  # Base system peripheral
    SubClassCode = 0x80  # Other
    ProgIF = 0x00

    # BAR配置
    BAR0 = 0x00000000
    BAR0Size = '4kB'
    BAR0LegacyIO = False
    BAR0IsMemory = True

    # 中断配置
    InterruptLine = 0x0B
    InterruptPin = 0x01

    # SystemC TLM配置
    systemc_kernel = Param.SystemC_Kernel(NULL, "SystemC kernel instance")
```

### 3.2 编译配置：SConscript

```python
# src/dev/fpga/SConscript
Import('*')

if env['USE_SYSTEMC']:
    SimObject('FPGAAccelerator.py', sim_objects=['FPGAAccelerator'])
    Source('fpga_accelerator.cc')
    Source('fpga_dma.cc')
    
    DebugFlag('FPGAAccelerator', 'FPGA Accelerator device')
    DebugFlag('FPGADMA', 'FPGA DMA engine')
```

---

## 4. 系统配置脚本

### 4.1 configs/fpga/qe_fpga_system.py

```python
# configs/fpga/qe_fpga_system.py
import m5
from m5.objects import *
from m5.util import addToPath

addToPath('../')
from common import Options, Simulation, CacheConfig, MemConfig

def create_fpga_system():
    # 创建系统
    system = System()
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = '3GHz'
    system.clk_domain.voltage_domain = VoltageDomain()

    # 内存配置
    system.mem_mode = 'timing'
    system.mem_ranges = [AddrRange('8GB')]

    # CPU配置
    system.cpu = X86TimingSimpleCPU()
    system.cpu.createInterruptController()

    # 内存总线
    system.membus = SystemXBar()
    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports

    # 内存控制器
    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR4_2400_16x4()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports

    # PCIe总线
    system.iobus = IOXBar()
    system.membus.mem_side_ports = system.iobus.cpu_side_ports

    # FPGA加速器
    system.fpga = FPGAAccelerator()
    system.fpga.pio = system.iobus.mem_side_ports
    system.fpga.dma = system.iobus.cpu_side_ports

    # 中断控制器
    system.intrctrl = IntrControl()

    return system

# 主函数
if __name__ == "__m5_main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    Options.addCommonOptions(parser)
    parser.add_argument("--binary", type=str, required=True,
                       help="Path to QE binary")
    args = parser.parse_args()

    # 创建系统
    system = create_fpga_system()

    # 设置工作负载
    process = Process()
    process.cmd = [args.binary]
    system.cpu.workload = process
    system.cpu.createThreads()

    # 实例化系统
    root = Root(full_system=False, system=system)
    m5.instantiate()

    # 运行仿真
    print("Beginning simulation!")
    exit_event = m5.simulate()
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
```

---

## 5. 编译和测试

### 5.1 编译

```bash
cd gem5
scons build/X86/gem5.opt -j8 USE_SYSTEMC=True
```

### 5.2 测试MMIO访问

创建简单测试程序：

```c
// test_fpga_mmio.c
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>

#define FPGA_BAR_SIZE 4096

int main() {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 1;
    }

    // 假设FPGA BAR0映射到0xFEBC0000
    volatile uint32_t *fpga_regs = mmap(NULL, FPGA_BAR_SIZE,
                                        PROT_READ | PROT_WRITE,
                                        MAP_SHARED, fd, 0xFEBC0000);

    // 读取状态寄存器
    uint32_t status = fpga_regs[0x0004 / 4];
    printf("FPGA Status: 0x%08x\n", status);

    // 写入控制寄存器
    fpga_regs[0x0000 / 4] = 0x00000002;  // CTRL_ENABLE
    printf("FPGA enabled\n");

    munmap((void*)fpga_regs, FPGA_BAR_SIZE);
    close(fd);
    return 0;
}
```

运行测试：

```bash
./build/X86/gem5.opt --debug-flags=FPGAAccelerator \
    configs/fpga/qe_fpga_system.py \
    --binary=test_fpga_mmio
```

---

## 6. 验证清单

Phase 1完成标准：

- [ ] FPGAAccelerator类编译成功
- [ ] 设备在gem5中正确实例化
- [ ] MMIO寄存器读写功能正常
- [ ] DMA引擎基础功能实现
- [ ] TLM socket创建成功（如果启用SystemC）
- [ ] 调试输出正常（--debug-flags=FPGAAccelerator）

---

## 7. 下一步

Phase 1完成后，进入Phase 2：
1. 创建SystemC侧的TLM target模块
2. 实现gem5 ↔ SystemC的双向通信
3. 连接到现有的DFTHybridSystem

**预计时间：** Phase 1需要3-5天
