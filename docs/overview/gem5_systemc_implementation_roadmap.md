# gem5+SystemC 协同仿真实施路线图

**项目：** DFT加速系统 - CPU+FPGA协同仿真  
**目标：** 实现软硬件协同调试能力，支持完整QE electrons循环仿真  
**开始日期：** 2026-04-20  
**预计完成：** 2026-06-15 (8周)

---

## 📊 总体进度

```
Phase 0: 环境搭建          [████████░░] 80% (文档完成，待执行)
Phase 1: gem5 FPGA设备     [████████░░] 80% (文档完成，待执行)
Phase 2: SystemC TLM接口   [████████░░] 80% (文档完成，待执行)
Phase 3: QE代码修改        [░░░░░░░░░░]  0% (待开始)
Phase 4: 端到端集成        [░░░░░░░░░░]  0% (待开始)
Phase 5: 优化和验证        [░░░░░░░░░░]  0% (待开始)

总体进度: [████░░░░░░] 40% (设计阶段完成)
```

---

## 🎯 里程碑

| 里程碑 | 目标 | 预计日期 | 状态 |
|--------|------|----------|------|
| M0: 设计完成 | 架构设计和实施方案文档 | 2026-04-20 | ✅ 完成 |
| M1: gem5环境就绪 | gem5编译成功，TLM示例运行 | 2026-04-27 | 🔄 进行中 |
| M2: FPGA设备就绪 | FPGAAccelerator设备工作 | 2026-05-04 | ⏳ 待开始 |
| M3: TLM通信就绪 | gem5 ↔ SystemC双向通信 | 2026-05-11 | ⏳ 待开始 |
| M4: QE集成完成 | QE能调用FPGA加速器 | 2026-05-25 | ⏳ 待开始 |
| M5: 端到端验证 | 完整electrons循环运行 | 2026-06-08 | ⏳ 待开始 |
| M6: 项目完成 | 性能验证和文档交付 | 2026-06-15 | ⏳ 待开始 |

---

## 📅 详细时间表

### Week 1 (2026-04-20 ~ 2026-04-27): Phase 0 环境搭建

**目标：** gem5编译成功，SystemC TLM示例运行

**任务清单：**
- [x] 创建Phase 0实施文档
- [ ] 安装SystemC 2.3.3
- [ ] 克隆gem5仓库
- [ ] 配置gem5编译选项（USE_SYSTEMC=True）
- [ ] 编译gem5.opt（预计30-60分钟）
- [ ] 运行hello world测试
- [ ] 编译gem5 TLM示例
- [ ] 运行TLM示例验证通信

**交付物：**
- gem5可执行文件：`build/X86/gem5.opt`
- TLM示例可执行文件：`util/tlm/build/gem5.opt.sc`
- 环境验证报告

**风险：**
- macOS编译兼容性问题（缓解：使用Homebrew安装依赖）
- SystemC版本不匹配（缓解：使用2.3.3稳定版）

---

### Week 2 (2026-04-27 ~ 2026-05-04): Phase 1 gem5 FPGA设备

**目标：** FPGAAccelerator PCIe设备实现并测试

**任务清单：**
- [x] 创建Phase 1实施文档
- [ ] 创建文件结构（src/dev/fpga/）
- [ ] 实现fpga_accelerator.hh头文件
- [ ] 实现fpga_accelerator.cc核心逻辑
- [ ] 实现MMIO寄存器读写
- [ ] 实现DMA引擎基础功能
- [ ] 添加TLM initiator socket
- [ ] 创建Python配置文件
- [ ] 编译gem5（增量编译）
- [ ] 创建MMIO测试程序
- [ ] 运行测试验证设备功能

**交付物：**
- FPGAAccelerator设备源码（~1000行C++）
- Python配置文件
- MMIO测试程序
- 设备功能验证报告

**风险：**
- PciDevice接口变化（缓解：参考gem5现有PCIe设备）
- TLM socket集成问题（缓解：参考gem5 TLM示例）

---

### Week 3 (2026-05-04 ~ 2026-05-11): Phase 2 SystemC TLM接口

**目标：** SystemC侧TLM target实现，gem5 ↔ SystemC通信成功

**任务清单：**
- [x] 创建Phase 2实施文档
- [ ] 创建gem5_tlm_target.hpp头文件
- [ ] 实现gem5_tlm_target.cpp核心逻辑
- [ ] 实现b_transport方法
- [ ] 实现寄存器读写处理
- [ ] 实现DMA传输模拟
- [ ] 实现计算命令处理
- [ ] 修改DFTHybridSystem集成TLM接口
- [ ] 更新CMakeLists.txt
- [ ] 创建独立TLM测试程序
- [ ] 运行测试验证通信

**交付物：**
- Gem5TLMTarget模块源码（~800行C++）
- 修改后的DFTHybridSystem
- TLM测试程序
- 通信验证报告

**风险：**
- 时间同步问题（缓解：使用sc_time和gem5 Tick转换）
- 内存一致性问题（缓解：显式DMA传输，避免共享内存）

---

### Week 4-5 (2026-05-11 ~ 2026-05-25): Phase 3 QE代码修改

**目标：** QE能够通过FPGA加速器offload c_bands计算

**任务清单：**
- [ ] 分析QE c_bands代码结构
- [ ] 设计FPGA offload接口
- [ ] 创建fpga_driver.c用户态驱动
- [ ] 实现mmap映射FPGA寄存器
- [ ] 实现ioctl控制接口（如需要）
- [ ] 修改c_bands.f90添加offload路径
- [ ] 实现矩阵数据打包逻辑
- [ ] 实现结果解包逻辑
- [ ] 处理Fortran/C接口
- [ ] 编译修改后的QE
- [ ] 创建简单测试用例
- [ ] 在gem5中运行QE测试

**交付物：**
- 修改后的QE源码
- FPGA驱动代码（~500行C）
- QE编译脚本
- 功能测试报告

**风险：**
- Fortran/C接口复杂（缓解：使用ISO_C_BINDING）
- QE编译依赖问题（缓解：使用静态链接）
- gem5中运行QE性能慢（缓解：使用KVM模式加速非关键路径）

---

### Week 6 (2026-05-25 ~ 2026-06-01): Phase 4 端到端集成

**目标：** 完整electrons循环在gem5+SystemC中运行

**任务清单：**
- [ ] 准备QE输入文件（si4 workload）
- [ ] 配置gem5系统（CPU、内存、FPGA）
- [ ] 配置SystemC模型（4-Cluster架构）
- [ ] 运行完整electrons循环
- [ ] 收集性能数据（CPU cycles、FPGA cycles）
- [ ] 对比standalone SystemC结果
- [ ] 调试数值精度问题
- [ ] 调试性能异常
- [ ] 运行多个workloads（si8、graphene）
- [ ] 生成性能报告

**交付物：**
- 端到端运行脚本
- 性能数据（CSV格式）
- 数值精度验证报告
- 性能对比报告

**风险：**
- 仿真速度过慢（缓解：使用checkpoint跳过初始化）
- 数值精度问题（缓解：检查数据传输和类型转换）
- 内存不足（缓解：使用较小的workload）

---

### Week 7-8 (2026-06-01 ~ 2026-06-15): Phase 5 优化和验证

**目标：** 性能优化、调试工具集成、文档完善

**任务清单：**
- [ ] 实现KVM加速模式
- [ ] 实现checkpoint/restore
- [ ] 优化仿真速度（目标：1 SCF迭代 < 30分钟）
- [ ] 集成GDB调试
- [ ] 集成SystemC波形查看器
- [ ] 实现统一时间轴分析工具
- [ ] 运行完整workload集（5个）
- [ ] 生成最终性能报告
- [ ] 编写用户手册
- [ ] 编写开发者文档
- [ ] 代码清理和注释

**交付物：**
- 优化后的仿真系统
- 调试工具集
- 性能分析工具
- 用户手册
- 开发者文档
- 最终项目报告

**风险：**
- 优化效果有限（缓解：接受较慢的仿真速度，使用采样分析）
- 调试工具集成复杂（缓解：使用现有工具，不重新开发）

---

## 📦 交付物清单

### 代码交付物

1. **gem5扩展**
   - `src/dev/fpga/fpga_accelerator.{hh,cc}` - FPGA PCIe设备
   - `src/dev/fpga/fpga_dma.{hh,cc}` - DMA引擎
   - `src/dev/fpga/FPGAAccelerator.py` - Python配置
   - `configs/fpga/qe_fpga_system.py` - 系统配置脚本

2. **SystemC扩展**
   - `model/qe_band_solver_model/include/gem5_tlm_target.hpp`
   - `model/qe_band_solver_model/src/gem5_tlm_target.cpp`
   - `model/qe_band_solver_model/include/gem5_bridge.hpp`
   - `model/qe_band_solver_model/src/gem5_bridge.cpp`

3. **QE修改**
   - `soft/qe-7.5/PW/src/c_bands_fpga.f90` - FPGA offload路径
   - `soft/qe-7.5/PW/src/fpga_driver.c` - 用户态驱动
   - `soft/qe-7.5/PW/src/fpga_driver.h` - 驱动头文件

4. **测试和工具**
   - `test/test_fpga_mmio.c` - MMIO测试
   - `test/test_gem5_tlm.cpp` - TLM测试
   - `scripts/run_qe_gem5.sh` - 运行脚本
   - `scripts/analyze_performance.py` - 性能分析工具

### 文档交付物

1. **设计文档**
   - ✅ `docs/overview/gem5_systemc_cosim_architecture_v1.md` - 架构设计
   - ✅ `docs/architecture/gem5_systemc_integration_design_v0.md` - 集成设计
   - ✅ `docs/architecture/gem5_integration_decision_analysis_v0.md` - 决策分析

2. **实施文档**
   - ✅ `docs/implementation/phase0_gem5_setup_guide.md` - Phase 0指南
   - ✅ `docs/implementation/phase1_gem5_fpga_device.md` - Phase 1指南
   - ✅ `docs/implementation/phase2_systemc_tlm_interface.md` - Phase 2指南
   - ⏳ `docs/implementation/phase3_qe_modification.md` - Phase 3指南（待创建）
   - ⏳ `docs/implementation/phase4_integration_testing.md` - Phase 4指南（待创建）
   - ⏳ `docs/implementation/phase5_optimization.md` - Phase 5指南（待创建）

3. **用户文档**
   - ⏳ `docs/user_guide/quick_start.md` - 快速开始
   - ⏳ `docs/user_guide/running_qe.md` - 运行QE
   - ⏳ `docs/user_guide/debugging.md` - 调试指南
   - ⏳ `docs/user_guide/performance_analysis.md` - 性能分析

4. **验证报告**
   - ⏳ `docs/validation/phase0_validation.md` - Phase 0验证
   - ⏳ `docs/validation/phase1_validation.md` - Phase 1验证
   - ⏳ `docs/validation/phase2_validation.md` - Phase 2验证
   - ⏳ `docs/validation/end_to_end_validation.md` - 端到端验证
   - ⏳ `docs/validation/performance_report.md` - 性能报告

---

## 🎓 技术栈

### 工具和框架
- **gem5**: v23.0+ (stable分支)
- **SystemC**: 2.3.3
- **TLM**: 2.0
- **QE**: 7.5
- **编译器**: GCC 11+ / Clang 14+
- **Python**: 3.9+
- **CMake**: 3.20+
- **SCons**: 4.0+

### 开发环境
- **操作系统**: macOS (当前) / Linux (推荐用于生产)
- **CPU**: 8核以上
- **内存**: 32GB以上
- **磁盘**: 100GB可用空间

---

## 🚨 风险管理

### 高风险项

1. **gem5-SystemC时间同步复杂度**
   - 影响：可能导致仿真结果不准确
   - 概率：中
   - 缓解：使用TLM-2.0标准接口，参考成功案例

2. **仿真速度过慢**
   - 影响：影响开发效率和实用性
   - 概率：高
   - 缓解：KVM加速、checkpoint、采样分析

3. **QE Fortran代码修改困难**
   - 影响：可能延误进度
   - 概率：中
   - 缓解：最小化修改范围，使用ISO_C_BINDING

### 中风险项

1. **内存一致性问题**
   - 缓解：显式DMA传输，避免共享内存

2. **调试困难**
   - 缓解：分阶段验证，使用日志和断点

3. **数值精度问题**
   - 缓解：仔细检查数据类型和传输

---

## 📈 成功标准

### 功能标准
- [ ] gem5能运行完整QE pw.x二进制
- [ ] c_bands计算能offload到SystemC FPGA模型
- [ ] 端到端仿真完成至少1个SCF迭代
- [ ] 支持5个workloads（si4, si8, graphene, au_slab, sic32）

### 性能标准
- [ ] 仿真速度：1个SCF迭代 < 1小时（可接受）
- [ ] 数值精度：与standalone SystemC一致（±1e-10）
- [ ] 性能数据：与standalone SystemC一致（±5%）

### 质量标准
- [ ] 代码通过编译（无警告）
- [ ] 所有测试通过
- [ ] 文档完整（设计、实施、用户、验证）
- [ ] 支持GDB调试和SystemC波形查看

---

## 📞 联系和支持

**项目负责人：** [用户]  
**技术支持：** Sisyphus (AI Agent)  
**文档位置：** `/Volumes/remote/phd/year_2/project/dft加速/docs/`  
**代码仓库：** `/Volumes/remote/phd/year_2/project/dft加速/`

---

## 📝 变更日志

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-04-20 | v1.0 | 初始版本，完成Phase 0-2设计 | Sisyphus |

---

**下一步行动：** 开始执行Phase 0.1 - 安装gem5并编译支持SystemC TLM的版本

**当前状态：** 🟢 设计阶段完成，准备进入实施阶段
