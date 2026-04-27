# macOS ARM64 平台测试方案总结

**问题**: gem5 X86 模式需要 x86 ELF 二进制文件,但 macOS ARM64 只能生成 Mach-O ARM64 格式

**解决方案**: 4 种可行方案

---

## ✅ 方案 1: Docker (推荐,正在设置中)

### 优点
- ✅ **最简单** - 一键启动
- ✅ **隔离环境** - 不影响主系统
- ✅ **可复现** - 完全一致的测试环境
- ✅ **已准备就绪** - Docker 已安装,镜像正在构建

### 性能
- 使用 Rosetta 2 转译 x86_64
- 性能约为原生 x86 的 **50-70%**
- 对 gem5 仿真足够 (gem5 本身就慢)

### 使用步骤
```bash
# 1. 构建环境 (正在进行中...)
cd gem5_integration
./run_docker_test.sh

# 2. 进入容器
docker run -it --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest

# 3. 在容器内编译 gem5 (如果需要)
cd gem5
scons build/X86/gem5.opt -j4

# 4. 运行测试
./build/X86/gem5.opt ../configs/fpga_device_test.py --binary=../test_fpga
```

### 预计时间
- 镜像构建: 5-10 分钟 (首次)
- gem5 编译: 30-60 分钟 (首次)
- 后续测试: 秒级启动

---

## ✅ 方案 2: gem5 ARM64 模式

### 优点
- ✅ **原生性能** - 无转译开销
- ✅ **无需 Docker** - 直接在 macOS 运行
- ✅ **快速编译** - ARM64 编译更快

### 缺点
- ❌ 需要修改 FPGA 设备代码
- ❌ 与 x86 QE 二进制不兼容

### 实施步骤
```bash
# 1. 编译 ARM64 版本 gem5
cd gem5_integration/gem5
scons build/ARM/gem5.opt -j8

# 2. 修改 FPGA 设备
# 将 FPGAAccelerator 从 PciDevice 改为 BasicPioDevice
# (ARM 不使用 PCI,使用内存映射 I/O)

# 3. 编译 ARM64 测试程序
gcc -o test_fpga test_fpga.c

# 4. 运行
./build/ARM/gem5.opt configs/fpga_device_test_arm.py --binary=test_fpga
```

### 代码修改示例
```cpp
// 修改前 (X86 PCI)
class FPGAAccelerator : public PciDevice {
    // PCI 配置空间
    // BAR0 映射
};

// 修改后 (ARM PIO)
class FPGAAccelerator : public BasicPioDevice {
    // 直接内存映射
    // 固定地址 0xF0000000
};
```

---

## ✅ 方案 3: QEMU 用户模式

### 优点
- ✅ 轻量级
- ✅ 无需容器

### 缺点
- ❌ 配置复杂
- ❌ 交叉编译工具链难获取

### 实施步骤
```bash
# 1. 安装 QEMU
brew install qemu

# 2. 尝试运行 x86 二进制
qemu-x86_64 test_fpga

# 注意: 可能需要额外配置
```

---

## ✅ 方案 4: 远程 Linux 服务器

### 优点
- ✅ **原生 x86 性能**
- ✅ 真实生产环境

### 缺点
- ❌ 需要服务器访问权限
- ❌ 网络延迟

### 实施步骤
```bash
# 1. 同步代码
rsync -avz gem5_integration/ user@server:/path/to/gem5_integration/

# 2. SSH 登录
ssh user@server

# 3. 运行测试
cd /path/to/gem5_integration
./run_tests.sh
```

---

## 📊 方案对比

| 方案 | 设置时间 | 性能 | 复杂度 | 推荐度 |
|------|---------|------|--------|--------|
| Docker | 10 分钟 | 50-70% | 低 | ⭐⭐⭐⭐⭐ |
| ARM64 模式 | 1 小时 | 100% | 中 | ⭐⭐⭐ |
| QEMU | 30 分钟 | 30-50% | 高 | ⭐⭐ |
| 远程服务器 | 5 分钟 | 100% | 低 | ⭐⭐⭐⭐ |

---

## 🎯 推荐路线

### 立即开始 (Docker)
```bash
# 等待 Docker 镜像构建完成
# 然后运行:
cd gem5_integration
docker run -it --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest
```

### 长期使用 (ARM64 模式)
如果 Docker 性能不满意,可以花 1 小时修改为 ARM64 模式,获得原生性能。

### 生产验证 (远程服务器)
最终的性能测试建议在真实 Linux x86 服务器上进行。

---

## 📝 当前状态

### ✅ 已完成
- Docker 已安装
- Dockerfile 已创建
- docker-compose.yml 已创建
- 测试脚本已创建
- **Docker 镜像正在构建中...**

### ⏳ 进行中
- Docker 镜像构建 (预计 5-10 分钟)

### 📋 下一步
1. 等待 Docker 镜像构建完成
2. 进入容器
3. 编译测试程序 (已自动完成)
4. 运行 gem5 测试

---

## 🚀 快速命令参考

### Docker 基础命令
```bash
# 构建镜像
docker build --platform linux/amd64 -t gem5-test:latest .

# 进入容器
docker run -it --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest

# 在容器内编译程序
gcc -o test test.c -static

# 检查二进制格式
file test  # 应该显示: ELF 64-bit LSB executable, x86-64
```

### gem5 测试命令
```bash
# 在容器内
cd gem5

# 编译 gem5 (首次,30-60分钟)
scons build/X86/gem5.opt -j4

# 运行测试
./build/X86/gem5.opt ../configs/fpga_device_test.py --binary=../test_fpga
```

### 性能优化
```bash
# 增加 Docker 资源
# Docker Desktop → Settings → Resources
# - CPUs: 4-8
# - Memory: 8-16 GB

# 使用编译缓存
apt-get install ccache
export PATH=/usr/lib/ccache:$PATH
```

---

## 📚 相关文档

- `DOCKER_TESTING_GUIDE.md` - 详细的 Docker 使用指南
- `TEST_RESULTS_SUMMARY.md` - SystemC 测试结果
- `README.md` - 项目总览
- `GEM5_INTEGRATION_COMPLETE.md` - gem5 集成完成报告

---

**最后更新**: 2026-04-22 21:52  
**状态**: Docker 镜像构建中...  
**预计完成**: 5-10 分钟
