# macOS ARM64 平台下的 gem5 测试指南

本指南介绍如何在 macOS ARM64 平台上使用 Docker 运行 x86_64 gem5 测试。

---

## 方案概览

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| Docker (x86_64) | 简单,隔离,可复现 | 性能较慢 (Rosetta 2) | ⭐⭐⭐⭐⭐ |
| gem5 ARM64 模式 | 原生性能 | 需要重新编译 FPGA 设备 | ⭐⭐⭐ |
| QEMU 用户模式 | 轻量级 | 配置复杂 | ⭐⭐ |
| 远程 Linux 服务器 | 原生 x86 性能 | 需要服务器访问 | ⭐⭐⭐⭐ |

---

## 方案 1: Docker (推荐)

### 前置要求
- Docker Desktop for Mac (已安装 ✓)
- 至少 8GB 可用内存
- 至少 20GB 可用磁盘空间

### 快速开始

#### 步骤 1: 构建 Docker 镜像
```bash
cd gem5_integration
./run_docker_test.sh
```

这个脚本会:
1. 构建 Ubuntu 22.04 x86_64 镜像
2. 安装编译依赖
3. 创建并编译测试程序

#### 步骤 2: 进入容器
```bash
docker run -it --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest
```

#### 步骤 3: 在容器内编译 gem5 (如果需要)
```bash
# 容器内
cd gem5
scons build/X86/gem5.opt -j4
```

#### 步骤 4: 运行测试
```bash
# 容器内
./build/X86/gem5.opt ../configs/fpga_device_test.py --binary=../test_fpga
```

### 性能说明
- Docker 在 macOS ARM64 上运行 x86_64 容器使用 **Rosetta 2** 转译
- 性能约为原生 x86 的 **50-70%**
- 对于 gem5 仿真来说是可接受的 (gem5 本身就很慢)

---

## 方案 2: gem5 ARM64 模式

如果 Docker 性能不满意,可以编译 ARM64 版本的 gem5:

### 步骤 1: 重新编译 gem5 为 ARM64
```bash
cd gem5_integration/gem5
scons build/ARM/gem5.opt -j8
```

### 步骤 2: 修改 FPGA 设备配置
需要将 `FPGAAccelerator` 从 `PciDevice` 改为 `BasicPioDevice`,因为 ARM 不使用 PCI。

### 步骤 3: 编译 ARM64 测试程序
```bash
gcc -o test_fpga test_fpga.c
```

### 步骤 4: 运行
```bash
./build/ARM/gem5.opt configs/fpga_device_test_arm.py --binary=test_fpga
```

### 优缺点
- ✅ 原生 ARM64 性能
- ✅ 无需 Docker
- ❌ 需要修改 FPGA 设备代码 (PCI → PIO)
- ❌ 与 x86 QE 二进制不兼容

---

## 方案 3: QEMU 用户模式

使用 QEMU 运行 x86_64 二进制文件:

### 安装 QEMU
```bash
brew install qemu
```

### 编译 x86_64 静态二进制
```bash
# 需要 x86_64 交叉编译工具链
brew install x86_64-elf-gcc
x86_64-elf-gcc -static -o test_fpga test_fpga.c
```

### 运行
```bash
qemu-x86_64 test_fpga
```

### 优缺点
- ✅ 轻量级
- ❌ 配置复杂
- ❌ 交叉编译工具链难以获取

---

## 方案 4: 远程 Linux 服务器

如果有访问 Linux x86_64 服务器的权限:

### 同步代码
```bash
rsync -avz gem5_integration/ user@server:/path/to/gem5_integration/
```

### SSH 登录并测试
```bash
ssh user@server
cd /path/to/gem5_integration
./run_tests.sh
```

### 优缺点
- ✅ 原生 x86 性能
- ✅ 无需本地资源
- ❌ 需要服务器访问权限
- ❌ 网络延迟

---

## 推荐方案对比

### 对于快速验证 (推荐 Docker)
```bash
# 5 分钟内开始测试
cd gem5_integration
./run_docker_test.sh
docker run -it --rm --platform linux/amd64 -v $(pwd):/workspace -w /workspace gem5-test:latest
```

### 对于长期开发 (推荐 ARM64 模式)
```bash
# 一次性修改,长期使用
cd gem5_integration/gem5
scons build/ARM/gem5.opt -j8
# 修改 FPGA 设备为 BasicPioDevice
```

### 对于生产环境测试 (推荐远程服务器)
```bash
# 使用真实 x86 Linux 环境
ssh production-server
./run_full_tests.sh
```

---

## Docker 详细使用

### 常用命令

#### 构建镜像
```bash
docker build --platform linux/amd64 -t gem5-test:latest .
```

#### 运行交互式容器
```bash
docker run -it --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest \
    /bin/bash
```

#### 运行单个命令
```bash
docker run --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    -w /workspace \
    gem5-test:latest \
    gcc -o test test.c
```

#### 使用 docker-compose
```bash
docker-compose up -d
docker-compose exec gem5-test /bin/bash
```

### 性能优化

#### 增加 Docker 资源
Docker Desktop → Settings → Resources:
- CPUs: 4-8 核
- Memory: 8-16 GB
- Disk: 50 GB

#### 使用缓存加速编译
```bash
# 在容器内安装 ccache
apt-get install ccache
export PATH=/usr/lib/ccache:$PATH
```

---

## 故障排查

### 问题 1: Docker 镜像构建失败
```bash
# 清理并重试
docker system prune -a
docker build --no-cache --platform linux/amd64 -t gem5-test:latest .
```

### 问题 2: 容器内无法访问文件
```bash
# 检查卷挂载
docker run --rm --platform linux/amd64 \
    -v $(pwd):/workspace \
    gem5-test:latest \
    ls -la /workspace
```

### 问题 3: gem5 编译内存不足
```bash
# 减少并行编译任务
scons build/X86/gem5.opt -j2  # 而不是 -j8
```

### 问题 4: Rosetta 2 性能太慢
```bash
# 方案 A: 使用 ARM64 模式
scons build/ARM/gem5.opt -j8

# 方案 B: 使用远程 Linux 服务器
```

---

## 测试检查清单

### ✅ Docker 环境验证
- [ ] Docker 已安装并运行
- [ ] 镜像构建成功
- [ ] 容器可以启动
- [ ] 卷挂载正常
- [ ] x86_64 二进制可以编译

### ✅ gem5 编译验证
- [ ] gem5.opt 编译成功
- [ ] FPGA 设备代码包含在内
- [ ] 无编译错误或警告

### ✅ FPGA 设备验证
- [ ] 设备可以实例化
- [ ] PCI 配置正确
- [ ] MMIO 寄存器可访问
- [ ] DMA 引擎工作正常

### ✅ SystemC 集成验证
- [ ] TLM socket 连接成功
- [ ] 事务传递正常
- [ ] 延迟返回正确

---

## 下一步

完成 Docker 环境设置后,继续:

1. **gem5 运行时测试**
   ```bash
   ./build/X86/gem5.opt configs/fpga_device_test.py --binary=test_fpga
   ```

2. **QE 集成测试**
   ```bash
   # 编译 QE
   cd soft/qe-7.5
   ./configure
   make pw
   
   # 运行 gem5 + QE
   cd ../../gem5_integration/gem5
   ./build/X86/gem5.opt configs/fpga/qe_fpga_system.py \
       --binary=../../soft/qe-7.5/bin/pw.x \
       --options="-in si.in"
   ```

3. **性能对比测试**
   ```bash
   # CPU-only baseline
   ./run_cpu_baseline.sh
   
   # CPU+FPGA
   ./run_fpga_accelerated.sh
   
   # 对比结果
   ./compare_results.sh
   ```

---

## 参考资料

- [Docker Desktop for Mac](https://docs.docker.com/desktop/mac/install/)
- [gem5 Documentation](https://www.gem5.org/documentation/)
- [SystemC TLM-2.0](https://www.accellera.org/downloads/standards/systemc)
- [Rosetta 2 Performance](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment)

---

**最后更新**: 2026-04-22  
**测试环境**: macOS ARM64 + Docker  
**状态**: ✅ 就绪
