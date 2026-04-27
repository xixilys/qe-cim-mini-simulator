# gem5 Full System Mode - Current Status

## 完成的工作

### Phase 8.1-8.4: gem5基础设施 ✅
- gem5编译成功，包含SystemC支持（HAVE_SYSTEMC=True, USE_SYSTEMC=True）
- FPGA设备（FPGAAcceleratorSE）成功创建并注册
- 解决了sc_main链接问题（sc_main_stub.cc + extern "C"）

### Phase 8.6: Full System模式配置 ✅
- 成功配置X86 FS模式
- 添加完整PC平台（Pc对象，包含串口、定时器、中断控制器等）
- 正确连接CPU、内存、IO总线
- 配置E820内存映射表
- FPGA设备映射到0xF0000000

### 最小化Linux环境 ✅
- 创建静态链接init程序（889KB）
- 生成initramfs.cpio.gz（338KB）
- init程序包含/dev/mem访问FPGA设备的测试代码

## 当前问题

### 内核启动失败
**现象：**
- gem5运行完成（10秒仿真时间）
- 串口输出文件（m5out/system.pc.com_1.device）为空
- 没有任何内核启动消息

**可能原因：**
1. 内核没有找到initramfs
2. 内核启动参数不正确
3. 内核版本与gem5不兼容
4. 缺少必要的硬件设备（磁盘控制器等）

## 配置文件

### 当前配置（fpga_fs_complete.py）
```python
# 系统配置
- CPU: X86TimingSimpleCPU @ 1GHz
- Memory: 512MB DDR3-1600
- Platform: Pc (完整PC平台)
- FPGA: FPGAAcceleratorSE @ 0xF0000000

# 内核参数
command_line = 'earlyprintk=ttyS0 console=ttyS0 lpj=7999923 rdinit=/init'

# 内核
kernel = x86-linux-kernel-6.8.0-52-generic-1.0.0
```

## 下一步调试方向

### 方案A：使用gem5标准磁盘镜像
- 下载gem5官方Ubuntu镜像
- 使用标准FS配置验证平台工作
- 然后添加FPGA设备

### 方案B：简化到最小配置
- 移除PC平台，只保留必要设备
- 使用更简单的内核（如busybox）
- 逐步添加设备直到工作

### 方案C：调试内核启动
- 启用gem5的详细调试输出（--debug-flags=Exec,Faults）
- 检查内核是否真的开始执行
- 查看CPU指令执行情况

### 方案D：回到SE模式 + 自定义系统调用
- 放弃FS模式的复杂性
- 在SE模式中添加自定义系统调用访问FPGA
- 更简单但功能受限

## 技术细节

### FPGA设备实现
```cpp
class FPGAAcceleratorSE : public BasicPioDevice {
    // 寄存器
    uint32_t deviceIdReg = 0xFABCDEF0;
    uint32_t statusReg = 0;
    uint32_t controlReg = 0;
    uint32_t dataReg = 0;
    
    // 计算参数
    uint32_t nBands = 0;
    uint32_t nBasis = 0;
    uint32_t cycles = 0;
    
    // 地址映射
    0x00: deviceIdReg (RO)
    0x04: statusReg (RO)
    0x08: controlReg (RW)
    0x0C: dataReg (RW)
    0x10: nBands (RW)
    0x14: nBasis (RW)
    0x18: cycles (RO)
};
```

### init程序测试代码
```c
// 通过/dev/mem访问FPGA
int fd = open("/dev/mem", O_RDWR | O_SYNC);
void *fpga_mem = mmap(NULL, 0x1000, PROT_READ|PROT_WRITE, 
                      MAP_SHARED, fd, 0xF0000000);
volatile uint32_t *regs = (volatile uint32_t *)fpga_mem;

// 读取设备ID
printf("FPGA Device ID: 0x%08x\n", regs[0]);

// 启动计算
regs[2] = 0x1;  // controlReg

// 读取状态
printf("Status: 0x%08x\n", regs[1]);
```

## 时间投入

- Phase 8.1-8.4: ~4小时（gem5编译、SystemC集成）
- Phase 8.5: ~2小时（交叉编译环境、测试程序）
- Phase 8.6: ~3小时（FS模式配置、调试）
- **总计：~9小时**

## 建议

鉴于FS模式的复杂性和当前的阻塞状态，建议：

1. **短期（1-2小时）：** 尝试方案C，启用详细调试查看内核是否执行
2. **中期（2-4小时）：** 如果内核确实没启动，尝试方案A使用标准镜像
3. **长期（重新评估）：** 如果FS模式持续困难，考虑方案D回到SE模式

**关键决策点：** 是否值得继续投入时间在FS模式上？还是应该采用更实用的方案（如Mock模式已经工作良好）？
