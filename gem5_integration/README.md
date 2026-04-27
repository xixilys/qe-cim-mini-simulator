# gem5+SystemC 协同仿真系统

**DFT加速系统的CPU+FPGA软硬件协同调试平台**

---

## 🎯 项目概述

本项目实现了基于gem5和SystemC的异构系统仿真平台，用于Quantum ESPRESSO (QE) DFT计算的FPGA加速研究。

**核心功能：**
- ✅ gem5模拟CPU执行QE程序
- ✅ SystemC模拟FPGA加速器（4-Cluster流水线）
- ✅ TLM-2.0实现CPU-FPGA通信
- ✅ QE c_bands计算offload到FPGA
- ✅ 端到端性能评估

---

## 📁 目录结构

```
gem5_integration/
├── src/dev/fpga/              # gem5 FPGA PCIe设备
│   ├── fpga_accelerator.hh    # 设备头文件
│   ├── fpga_accelerator.cc    # 设备实现
│   ├── FPGAAccelerator.py     # Python配置
│   └── SConscript             # 编译配置
├── configs/fpga/              # gem5系统配置
│   └── qe_fpga_system.py      # QE+FPGA系统配置
├── systemc_model/             # SystemC TLM模型
│   ├── include/               # 头文件
│   │   ├── gem5_tlm_target.hpp
│   │   ├── gem5_bridge.hpp
│   │   └── dft_hybrid_system_gem5.hpp
│   ├── src/                   # 实现文件
│   │   ├── gem5_tlm_target.cpp
│   │   ├── gem5_bridge.cpp
│   │   ├── dft_hybrid_system_gem5.cpp
│   │   └── standalone_test.cpp
│   └── CMakeLists.txt         # 构建配置
└── qe_integration/            # QE代码集成
    ├── fpga_offload.h         # C接口
    ├── fpga_offload.c         # FPGA驱动
    ├── fpga_offload_module.f90 # Fortran接口
    ├── c_bands_fpga.patch     # QE补丁
    └── Makefile               # 构建脚本
```

---

## 🚀 快速开始

### 前置要求

- **操作系统：** macOS 或 Linux
- **编译器：** GCC 11+ 或 Clang 14+
- **Python：** 3.9+
- **内存：** 16GB+（推荐32GB）
- **磁盘：** 50GB可用空间

### Step 1: 安装SystemC

```bash
cd /tmp
wget https://www.accellera.org/images/downloads/standards/systemc/systemc-2.3.3.tar.gz
tar xzf systemc-2.3.3.tar.gz
cd systemc-2.3.3
mkdir build && cd build
../configure --prefix=/opt/systemc-2.3.3
make -j8 && sudo make install

# 设置环境变量
export SYSTEMC_HOME=/opt/systemc-2.3.3
export DYLD_LIBRARY_PATH=$SYSTEMC_HOME/lib-macosx64:$DYLD_LIBRARY_PATH
```

### Step 2: 克隆和编译gem5

```bash
# 克隆gem5
cd /Volumes/remote/phd/year_2/project/dft加速
mkdir -p gem5_workspace && cd gem5_workspace
git clone https://gem5.googlesource.com/public/gem5
cd gem5 && git checkout stable

# 复制FPGA设备代码到gem5
cp -r ../gem5_integration/src/dev/fpga src/dev/
cp -r ../gem5_integration/configs/fpga configs/

# 编译gem5（预计30-60分钟）
scons build/X86/gem5.opt -j8 \
    USE_SYSTEMC=True \
    SYSTEMC_INC=/opt/systemc-2.3.3/include \
    SYSTEMC_LIB=/opt/systemc-2.3.3/lib-macosx64
```

### Step 3: 编译SystemC模型

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/gem5_integration/systemc_model
mkdir build && cd build
cmake .. -DCMAKE_PREFIX_PATH=/opt/systemc-2.3.3
make -j4

# 运行独立测试
./gem5_systemc_standalone
```

**预期输出：**
```
=== gem5-SystemC Integration Standalone Test ===
SystemC modules instantiated successfully
TLM target socket: gem5_bridge.gem5_tlm_target.target_socket
=== Simulating c_bands request from gem5 ===
[DFTHybridSystemGem5] Received c_bands request from gem5:
  Matrix dimensions: n=32 m=128 k=1
=== Test completed successfully ===
```

### Step 4: 编译QE集成

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/gem5_integration/qe_integration
make

# 应用QE补丁
cd /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5
patch -p1 < ../../gem5_integration/qe_integration/c_bands_fpga.patch

# 重新编译QE（添加FPGA库链接）
# 编辑 make.inc，添加：
# LDFLAGS += -L/path/to/gem5_integration/qe_integration -lfpga_offload
make pw
```

### Step 5: 运行端到端测试

```bash
cd gem5_workspace/gem5

# 运行gem5+QE（简单测试）
./build/X86/gem5.opt \
    --debug-flags=FPGAAccelerator \
    configs/fpga/qe_fpga_system.py \
    --binary=/path/to/qe/pw.x \
    --options="-in si.in"
```

---

## 📖 详细文档

### 设计文档
- [架构设计](../docs/overview/gem5_systemc_cosim_architecture_v1.md) - 系统架构和设计决策
- [实施路线图](../docs/overview/gem5_systemc_implementation_roadmap.md) - 8周实施计划
- [代码实施总结](../docs/overview/gem5_systemc_code_implementation_summary.md) - 已完成工作总结

### 实施指南
- [Phase 0: gem5环境搭建](../docs/implementation/phase0_gem5_setup_guide.md)
- [Phase 1: gem5 FPGA设备](../docs/implementation/phase1_gem5_fpga_device.md)
- [Phase 2: SystemC TLM接口](../docs/implementation/phase2_systemc_tlm_interface.md)

### API文档
- [FPGA Offload API](qe_integration/fpga_offload.h) - C接口
- [Fortran接口模块](qe_integration/fpga_offload_module.f90) - Fortran绑定

---

## 🔧 配置选项

### gem5配置

编辑 `configs/fpga/qe_fpga_system.py`：

```python
system.clk_domain.clock = '3GHz'      # CPU时钟频率
system.mem_ranges = [AddrRange('8GB')] # 内存大小
system.cpu = X86TimingSimpleCPU()     # CPU模型（可选KVM加速）
```

### FPGA设备配置

编辑 `src/dev/fpga/FPGAAccelerator.py`：

```python
BAR0Size = '64kB'          # MMIO空间大小
pio_latency = '1ns'        # MMIO访问延迟
```

### SystemC配置

编辑 `systemc_model/src/dft_hybrid_system_gem5.cpp`：

```cpp
ArchitectureConfig config = ArchitectureConfig::create_default();
// 或者加载自定义配置
```

---

## 🐛 调试

### 启用gem5调试输出

```bash
./build/X86/gem5.opt \
    --debug-flags=FPGAAccelerator,FPGADMA,FPGATL M \
    --debug-file=fpga_debug.txt \
    configs/fpga/qe_fpga_system.py ...
```

### 启用SystemC波形

编辑 `systemc_model/src/standalone_test.cpp`：

```cpp
sc_trace_file* tf = sc_create_vcd_trace_file("fpga_trace");
sc_trace(tf, signal, "signal_name");
// ...
sc_start();
sc_close_vcd_trace_file(tf);
```

查看波形：
```bash
gtkwave fpga_trace.vcd
```

### GDB调试

```bash
# 启动gem5并等待GDB
./build/X86/gem5.opt --remote-gdb-port=7000 ...

# 另一个终端连接GDB
gdb /path/to/qe/pw.x
(gdb) target remote :7000
(gdb) break c_bands_
(gdb) continue
```

---

## 📊 性能分析

### 收集gem5统计数据

```bash
# 运行后查看统计
cat m5out/stats.txt

# 关键指标：
# - system.cpu.numCycles: CPU总周期数
# - system.fpga.dma_bytes: DMA传输字节数
# - system.fpga.compute_cycles: FPGA计算周期数
```

### SystemC性能数据

SystemC模型会输出时序信息：
```
[1000 ns] DMA transfer started: src=0x100000000 dst=0x0 size=65536
[1004 ns] DMA transfer complete
[1005 ns] Compute command: N=32 M=128 K=1
[2005 ns] Compute complete
```

---

## ⚠️ 已知问题

1. **仿真速度慢**
   - gem5 Timing模式：~1 MIPS
   - 解决方案：使用KVM模式加速非关键路径

2. **内存占用大**
   - gem5+SystemC：~8GB内存
   - 解决方案：使用较小的workload或增加swap

3. **QE补丁未完全测试**
   - 可能需要调整Fortran接口
   - 解决方案：参考QE现有的C接口实现

---

## 🤝 贡献

欢迎提交Issue和Pull Request！

### 开发流程

1. Fork本仓库
2. 创建feature分支
3. 提交代码并测试
4. 提交Pull Request

### 代码规范

- C++: 遵循gem5代码风格
- Fortran: 遵循QE代码风格
- 提交信息: 使用清晰的描述

---

## 📄 许可证

本项目代码遵循以下许可证：
- gem5部分: BSD 3-Clause License
- SystemC部分: Apache License 2.0
- QE集成部分: GPL v2

---

## 📞 联系方式

- **项目负责人：** [用户]
- **技术支持：** 参考文档或提交Issue
- **文档位置：** `/Volumes/remote/phd/year_2/project/dft加速/docs/`

---

## 🎓 引用

如果本项目对您的研究有帮助，请引用：

```bibtex
@misc{gem5_systemc_dft_2026,
  title={gem5+SystemC Co-simulation Platform for DFT Acceleration},
  author={[Your Name]},
  year={2026},
  howpublished={\url{https://github.com/...}}
}
```

---

**最后更新：** 2026-04-20  
**版本：** v1.0  
**状态：** 🟢 核心代码完成，待测试验证
