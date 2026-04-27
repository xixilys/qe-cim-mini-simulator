# Phase 2: SystemC TLM接口实现

**目标：** 在SystemC侧创建TLM target模块，实现gem5 ↔ SystemC双向通信

---

## 1. 文件结构

```
model/qe_band_solver_model/
├── include/
│   ├── gem5_tlm_target.hpp         # TLM target接口
│   ├── gem5_bridge.hpp             # gem5桥接层
│   └── fpga_device_model.hpp       # FPGA设备模型
├── src/
│   ├── gem5_tlm_target.cpp         # TLM target实现
│   ├── gem5_bridge.cpp             # 桥接层实现
│   └── fpga_device_model.cpp       # 设备模型实现
└── CMakeLists.txt                  # 更新编译配置
```

---

## 2. TLM Target模块设计

### 2.1 头文件：gem5_tlm_target.hpp

```cpp
// model/qe_band_solver_model/include/gem5_tlm_target.hpp
#ifndef GEM5_TLM_TARGET_HPP
#define GEM5_TLM_TARGET_HPP

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>
#include "dft_hybrid_system.hpp"

using namespace sc_core;
using namespace tlm;

class Gem5TLMTarget : public sc_module {
 public:
  // TLM-2.0 target socket
  tlm_utils::simple_target_socket<Gem5TLMTarget> target_socket;

  SC_HAS_PROCESS(Gem5TLMTarget);

  Gem5TLMTarget(sc_module_name name, DFTHybridSystem* dft_sys);
  ~Gem5TLMTarget();

  // TLM-2.0 blocking transport接口
  void b_transport(tlm_generic_payload& trans, sc_time& delay);

  // TLM-2.0 debug transport接口（可选）
  unsigned int transport_dbg(tlm_generic_payload& trans);

  // TLM-2.0 DMI接口（可选，用于加速）
  bool get_direct_mem_ptr(tlm_generic_payload& trans, tlm_dmi& dmi_data);

 private:
  DFTHybridSystem* dft_system_;

  // 寄存器地址映射（与gem5侧一致）
  enum Registers {
    REG_CONTROL       = 0x0000,
    REG_STATUS        = 0x0004,
    REG_INTERRUPT     = 0x0008,
    REG_DMA_SRC_LO    = 0x0010,
    REG_DMA_SRC_HI    = 0x0014,
    REG_DMA_DST_LO    = 0x0018,
    REG_DMA_DST_HI    = 0x001C,
    REG_DMA_SIZE      = 0x0020,
    REG_DMA_CONTROL   = 0x0024,
    REG_MATRIX_N      = 0x0030,
    REG_MATRIX_M      = 0x0034,
    REG_MATRIX_K      = 0x0038,
    REG_COMPUTE_CMD   = 0x0040,
    REG_COMPUTE_STATUS= 0x0044,
    REG_RESULT_ADDR   = 0x0050,
    REG_RESULT_SIZE   = 0x0054,
  };

  // 寄存器存储
  uint32_t control_reg_;
  uint32_t status_reg_;
  uint32_t interrupt_reg_;
  uint64_t dma_src_addr_;
  uint64_t dma_dst_addr_;
  uint32_t dma_size_;
  uint32_t matrix_n_, matrix_m_, matrix_k_;

  // 设备内存（模拟FPGA HBM）
  std::vector<uint8_t> device_memory_;
  static const size_t DEVICE_MEMORY_SIZE = 1024 * 1024 * 1024;  // 1GB

  // 事务处理
  void handle_read(tlm_generic_payload& trans, sc_time& delay);
  void handle_write(tlm_generic_payload& trans, sc_time& delay);

  // 寄存器访问
  uint32_t read_register(uint64_t addr);
  void write_register(uint64_t addr, uint32_t value);

  // DMA处理
  void handle_dma_transfer();

  // 计算命令处理
  void handle_compute_command();

  // 辅助函数
  void log_transaction(const tlm_generic_payload& trans, const char* phase);
};

#endif // GEM5_TLM_TARGET_HPP
```

### 2.2 实现文件：gem5_tlm_target.cpp

```cpp
// model/qe_band_solver_model/src/gem5_tlm_target.cpp
#include "gem5_tlm_target.hpp"
#include <iostream>
#include <iomanip>

Gem5TLMTarget::Gem5TLMTarget(sc_module_name name, DFTHybridSystem* dft_sys)
    : sc_module(name),
      target_socket("target_socket"),
      dft_system_(dft_sys),
      control_reg_(0),
      status_reg_(0x00000001),  // STATUS_READY
      interrupt_reg_(0),
      dma_src_addr_(0),
      dma_dst_addr_(0),
      dma_size_(0),
      matrix_n_(0),
      matrix_m_(0),
      matrix_k_(0)
{
  // 注册TLM回调
  target_socket.register_b_transport(this, &Gem5TLMTarget::b_transport);
  target_socket.register_transport_dbg(this, &Gem5TLMTarget::transport_dbg);
  target_socket.register_get_direct_mem_ptr(this, &Gem5TLMTarget::get_direct_mem_ptr);

  // 分配设备内存
  device_memory_.resize(DEVICE_MEMORY_SIZE, 0);

  std::cout << "[" << sc_time_stamp() << "] " << name 
            << ": TLM target initialized" << std::endl;
}

Gem5TLMTarget::~Gem5TLMTarget() {
}

void Gem5TLMTarget::b_transport(tlm_generic_payload& trans, sc_time& delay) {
  log_transaction(trans, "b_transport");

  tlm_command cmd = trans.get_command();
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  // 检查地址范围
  if (addr >= DEVICE_MEMORY_SIZE && addr < 0x10000) {
    // MMIO寄存器空间（0x0000 - 0xFFFF）
    if (cmd == TLM_READ_COMMAND) {
      handle_read(trans, delay);
    } else if (cmd == TLM_WRITE_COMMAND) {
      handle_write(trans, delay);
    } else {
      trans.set_response_status(TLM_COMMAND_ERROR_RESPONSE);
      return;
    }
  } else if (addr < DEVICE_MEMORY_SIZE) {
    // 设备内存空间
    if (cmd == TLM_READ_COMMAND) {
      memcpy(data_ptr, &device_memory_[addr], data_length);
      delay += sc_time(10, SC_NS);  // 内存访问延迟
    } else if (cmd == TLM_WRITE_COMMAND) {
      memcpy(&device_memory_[addr], data_ptr, data_length);
      delay += sc_time(10, SC_NS);
    }
    trans.set_response_status(TLM_OK_RESPONSE);
  } else {
    trans.set_response_status(TLM_ADDRESS_ERROR_RESPONSE);
    return;
  }

  trans.set_response_status(TLM_OK_RESPONSE);
}

void Gem5TLMTarget::handle_read(tlm_generic_payload& trans, sc_time& delay) {
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (data_length != 4) {
    trans.set_response_status(TLM_BURST_ERROR_RESPONSE);
    return;
  }

  uint32_t value = read_register(addr);
  *(uint32_t*)data_ptr = value;

  // 寄存器访问延迟
  delay += sc_time(1, SC_NS);

  std::cout << "[" << sc_time_stamp() << "] TLM READ: addr=0x" 
            << std::hex << addr << " value=0x" << value << std::dec << std::endl;
}

void Gem5TLMTarget::handle_write(tlm_generic_payload& trans, sc_time& delay) {
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (data_length != 4) {
    trans.set_response_status(TLM_BURST_ERROR_RESPONSE);
    return;
  }

  uint32_t value = *(uint32_t*)data_ptr;
  write_register(addr, value);

  // 寄存器访问延迟
  delay += sc_time(1, SC_NS);

  std::cout << "[" << sc_time_stamp() << "] TLM WRITE: addr=0x" 
            << std::hex << addr << " value=0x" << value << std::dec << std::endl;
}

uint32_t Gem5TLMTarget::read_register(uint64_t addr) {
  switch (addr) {
    case REG_CONTROL:
      return control_reg_;
    case REG_STATUS:
      return status_reg_;
    case REG_INTERRUPT:
      return interrupt_reg_;
    case REG_DMA_SRC_LO:
      return (uint32_t)(dma_src_addr_ & 0xFFFFFFFF);
    case REG_DMA_SRC_HI:
      return (uint32_t)(dma_src_addr_ >> 32);
    case REG_DMA_DST_LO:
      return (uint32_t)(dma_dst_addr_ & 0xFFFFFFFF);
    case REG_DMA_DST_HI:
      return (uint32_t)(dma_dst_addr_ >> 32);
    case REG_DMA_SIZE:
      return dma_size_;
    case REG_MATRIX_N:
      return matrix_n_;
    case REG_MATRIX_M:
      return matrix_m_;
    case REG_MATRIX_K:
      return matrix_k_;
    case REG_COMPUTE_STATUS:
      return status_reg_;
    default:
      std::cerr << "Warning: read from unknown register 0x" 
                << std::hex << addr << std::dec << std::endl;
      return 0;
  }
}

void Gem5TLMTarget::write_register(uint64_t addr, uint32_t value) {
  switch (addr) {
    case REG_CONTROL:
      control_reg_ = value;
      if (value & 0x01) {  // CTRL_RESET
        status_reg_ = 0x00000001;  // STATUS_READY
        control_reg_ &= ~0x01;
        std::cout << "[" << sc_time_stamp() << "] Device reset" << std::endl;
      }
      break;

    case REG_DMA_SRC_LO:
      dma_src_addr_ = (dma_src_addr_ & 0xFFFFFFFF00000000ULL) | value;
      break;

    case REG_DMA_SRC_HI:
      dma_src_addr_ = (dma_src_addr_ & 0xFFFFFFFF) | ((uint64_t)value << 32);
      break;

    case REG_DMA_DST_LO:
      dma_dst_addr_ = (dma_dst_addr_ & 0xFFFFFFFF00000000ULL) | value;
      break;

    case REG_DMA_DST_HI:
      dma_dst_addr_ = (dma_dst_addr_ & 0xFFFFFFFF) | ((uint64_t)value << 32);
      break;

    case REG_DMA_SIZE:
      dma_size_ = value;
      break;

    case REG_DMA_CONTROL:
      if (value == 1) {
        handle_dma_transfer();
      }
      break;

    case REG_MATRIX_N:
      matrix_n_ = value;
      break;

    case REG_MATRIX_M:
      matrix_m_ = value;
      break;

    case REG_MATRIX_K:
      matrix_k_ = value;
      break;

    case REG_COMPUTE_CMD:
      if (value == 1) {
        handle_compute_command();
      }
      break;

    default:
      std::cerr << "Warning: write to unknown register 0x" 
                << std::hex << addr << std::dec << std::endl;
      break;
  }
}

void Gem5TLMTarget::handle_dma_transfer() {
  std::cout << "[" << sc_time_stamp() << "] DMA transfer started: "
            << "src=0x" << std::hex << dma_src_addr_ 
            << " dst=0x" << dma_dst_addr_ 
            << " size=" << std::dec << dma_size_ << std::endl;

  // 模拟DMA传输延迟
  // PCIe Gen4 x16: 16 GB/s = 16 bytes/ns
  double transfer_time_ns = dma_size_ / 16.0;
  wait(transfer_time_ns, SC_NS);

  // 设置状态
  status_reg_ |= 0x00000008;  // STATUS_DMA_DONE
  interrupt_reg_ = 1;

  std::cout << "[" << sc_time_stamp() << "] DMA transfer complete" << std::endl;
}

void Gem5TLMTarget::handle_compute_command() {
  std::cout << "[" << sc_time_stamp() << "] Compute command: "
            << "N=" << matrix_n_ << " M=" << matrix_m_ 
            << " K=" << matrix_k_ << std::endl;

  // 设置忙状态
  status_reg_ |= 0x00000002;  // STATUS_BUSY
  status_reg_ &= ~0x00000010;  // Clear STATUS_COMPUTE_DONE

  // 调用DFTHybridSystem执行c_bands
  // TODO: 实现实际的计算调用
  
  // 模拟计算延迟（从现有SystemC模型获取）
  // 这里应该调用dft_system_->run_c_bands_episode()
  wait(1000, SC_NS);  // 临时：1us延迟

  // 设置完成状态
  status_reg_ &= ~0x00000002;  // Clear STATUS_BUSY
  status_reg_ |= 0x00000010;  // STATUS_COMPUTE_DONE
  interrupt_reg_ = 1;

  std::cout << "[" << sc_time_stamp() << "] Compute complete" << std::endl;
}

unsigned int Gem5TLMTarget::transport_dbg(tlm_generic_payload& trans) {
  // Debug transport：不消耗时间，用于调试
  tlm_command cmd = trans.get_command();
  uint64_t addr = trans.get_address();
  unsigned char* data_ptr = trans.get_data_ptr();
  unsigned int data_length = trans.get_data_length();

  if (addr < DEVICE_MEMORY_SIZE) {
    if (cmd == TLM_READ_COMMAND) {
      memcpy(data_ptr, &device_memory_[addr], data_length);
    } else if (cmd == TLM_WRITE_COMMAND) {
      memcpy(&device_memory_[addr], data_ptr, data_length);
    }
    return data_length;
  }

  return 0;
}

bool Gem5TLMTarget::get_direct_mem_ptr(tlm_generic_payload& trans, 
                                       tlm_dmi& dmi_data) {
  // DMI（Direct Memory Interface）：允许initiator直接访问内存
  // 用于加速仿真，但需要小心处理一致性
  
  // 暂不支持DMI
  return false;
}

void Gem5TLMTarget::log_transaction(const tlm_generic_payload& trans, 
                                    const char* phase) {
  std::cout << "[" << sc_time_stamp() << "] " << phase << ": "
            << (trans.get_command() == TLM_READ_COMMAND ? "READ" : "WRITE")
            << " addr=0x" << std::hex << trans.get_address()
            << " len=" << std::dec << trans.get_data_length()
            << std::endl;
}
```

---

## 3. 集成到现有SystemC模型

### 3.1 修改DFTHybridSystem

```cpp
// model/qe_band_solver_model/include/dft_hybrid_system.hpp
class DFTHybridSystem : public sc_core::sc_module {
 public:
  // ... 现有成员 ...

  // 新增：gem5接口
  Gem5TLMTarget* gem5_interface_;

  // 新增：从gem5接收的c_bands请求
  struct CBandsRequest {
    uint32_t n, m, k;
    uint64_t h_matrix_addr;
    uint64_t s_matrix_addr;
    uint64_t result_addr;
  };

  // 新增：执行c_bands（从gem5调用）
  void execute_c_bands_from_gem5(const CBandsRequest& req);
};
```

```cpp
// model/qe_band_solver_model/src/dft_hybrid_system.cpp
DFTHybridSystem::DFTHybridSystem(...) {
  // ... 现有初始化 ...

  // 创建gem5接口
  gem5_interface_ = new Gem5TLMTarget("gem5_tlm_target", this);
}

void DFTHybridSystem::execute_c_bands_from_gem5(const CBandsRequest& req) {
  // 从设备内存读取矩阵数据
  // TODO: 通过gem5_interface_->device_memory_访问

  // 调用现有的c_bands执行逻辑
  // auto result = run_c_bands_episode(...);

  // 将结果写回设备内存
  // TODO: 写入result_addr
}
```

### 3.2 更新CMakeLists.txt

```cmake
# model/qe_band_solver_model/CMakeLists.txt

# 添加新的源文件
set(SOURCES
    # ... 现有源文件 ...
    src/gem5_tlm_target.cpp
    src/gem5_bridge.cpp
)

# 添加新的头文件
set(HEADERS
    # ... 现有头文件 ...
    include/gem5_tlm_target.hpp
    include/gem5_bridge.hpp
)

# 链接TLM库
target_link_libraries(qe_band_solver_model
    SystemC::systemc
    # TLM通常包含在SystemC中，无需额外链接
)
```

---

## 4. 端到端测试

### 4.1 创建测试程序

```cpp
// model/qe_band_solver_model/test/test_gem5_tlm.cpp
#include <systemc>
#include <tlm>
#include "gem5_tlm_target.hpp"
#include "dft_hybrid_system.hpp"

using namespace sc_core;
using namespace tlm;

// 简单的TLM initiator（模拟gem5）
class TestInitiator : public sc_module {
 public:
  tlm_utils::simple_initiator_socket<TestInitiator> initiator_socket;

  SC_CTOR(TestInitiator) : initiator_socket("initiator_socket") {
    SC_THREAD(test_process);
  }

  void test_process() {
    wait(10, SC_NS);

    // 测试1: 读取状态寄存器
    {
      tlm_generic_payload trans;
      sc_time delay = SC_ZERO_TIME;
      uint32_t data;

      trans.set_command(TLM_READ_COMMAND);
      trans.set_address(0x0004);  // REG_STATUS
      trans.set_data_ptr((unsigned char*)&data);
      trans.set_data_length(4);
      trans.set_streaming_width(4);
      trans.set_byte_enable_ptr(nullptr);
      trans.set_dmi_allowed(false);
      trans.set_response_status(TLM_INCOMPLETE_RESPONSE);

      initiator_socket->b_transport(trans, delay);

      if (trans.is_response_ok()) {
        std::cout << "Status register: 0x" << std::hex << data << std::dec << std::endl;
      }

      wait(delay);
    }

    // 测试2: 写入矩阵维度
    {
      tlm_generic_payload trans;
      sc_time delay = SC_ZERO_TIME;
      uint32_t data = 128;

      trans.set_command(TLM_WRITE_COMMAND);
      trans.set_address(0x0030);  // REG_MATRIX_N
      trans.set_data_ptr((unsigned char*)&data);
      trans.set_data_length(4);
      trans.set_streaming_width(4);
      trans.set_byte_enable_ptr(nullptr);
      trans.set_dmi_allowed(false);
      trans.set_response_status(TLM_INCOMPLETE_RESPONSE);

      initiator_socket->b_transport(trans, delay);

      if (trans.is_response_ok()) {
        std::cout << "Matrix N set to " << data << std::endl;
      }

      wait(delay);
    }

    // 测试3: 启动计算
    {
      tlm_generic_payload trans;
      sc_time delay = SC_ZERO_TIME;
      uint32_t data = 1;

      trans.set_command(TLM_WRITE_COMMAND);
      trans.set_address(0x0040);  // REG_COMPUTE_CMD
      trans.set_data_ptr((unsigned char*)&data);
      trans.set_data_length(4);
      trans.set_streaming_width(4);
      trans.set_byte_enable_ptr(nullptr);
      trans.set_dmi_allowed(false);
      trans.set_response_status(TLM_INCOMPLETE_RESPONSE);

      initiator_socket->b_transport(trans, delay);

      if (trans.is_response_ok()) {
        std::cout << "Compute command sent" << std::endl;
      }

      wait(delay);
    }

    wait(2000, SC_NS);  // 等待计算完成

    // 测试4: 读取计算状态
    {
      tlm_generic_payload trans;
      sc_time delay = SC_ZERO_TIME;
      uint32_t data;

      trans.set_command(TLM_READ_COMMAND);
      trans.set_address(0x0044);  // REG_COMPUTE_STATUS
      trans.set_data_ptr((unsigned char*)&data);
      trans.set_data_length(4);
      trans.set_streaming_width(4);
      trans.set_byte_enable_ptr(nullptr);
      trans.set_dmi_allowed(false);
      trans.set_response_status(TLM_INCOMPLETE_RESPONSE);

      initiator_socket->b_transport(trans, delay);

      if (trans.is_response_ok()) {
        std::cout << "Compute status: 0x" << std::hex << data << std::dec << std::endl;
      }

      wait(delay);
    }

    sc_stop();
  }
};

int sc_main(int argc, char* argv[]) {
  // 创建DFT系统
  ArchitectureConfig config = ArchitectureConfig::create_default();
  DFTHybridSystem dft_system("dft_system", config);

  // 创建测试initiator
  TestInitiator initiator("test_initiator");

  // 连接socket
  initiator.initiator_socket.bind(dft_system.gem5_interface_->target_socket);

  // 运行仿真
  std::cout << "Starting TLM test..." << std::endl;
  sc_start();
  std::cout << "TLM test complete at " << sc_time_stamp() << std::endl;

  return 0;
}
```

### 4.2 编译和运行测试

```bash
cd model/qe_band_solver_model/build
cmake .. && make -j4

# 运行TLM测试
./test_gem5_tlm

# 预期输出：
# Starting TLM test...
# [10 ns] TLM READ: addr=0x4 value=0x1
# Status register: 0x1
# [11 ns] TLM WRITE: addr=0x30 value=0x80
# Matrix N set to 128
# [12 ns] TLM WRITE: addr=0x40 value=0x1
# [12 ns] Compute command: N=128 M=0 K=0
# Compute command sent
# [1012 ns] Compute complete
# [2013 ns] TLM READ: addr=0x44 value=0x11
# Compute status: 0x11
# TLM test complete at 2014 ns
```

---

## 5. 验证清单

Phase 2完成标准：

- [ ] Gem5TLMTarget类编译成功
- [ ] TLM target socket正确注册回调
- [ ] b_transport方法正常工作
- [ ] 寄存器读写功能正确
- [ ] DMA传输模拟正常
- [ ] 计算命令处理正确
- [ ] 独立测试程序运行成功
- [ ] 与DFTHybridSystem集成无错误

---

## 6. 下一步

Phase 2完成后，进入Phase 3：
1. 修改QE代码添加FPGA offload路径
2. 实现用户态驱动（mmap/ioctl）
3. 端到端集成测试（gem5运行QE + SystemC FPGA）

**预计时间：** Phase 2需要3-5天
