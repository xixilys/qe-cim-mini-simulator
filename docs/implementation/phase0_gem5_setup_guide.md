# Phase 0: gem5环境搭建指南

**目标：** 编译支持SystemC TLM的gem5，验证基础功能

---

## 1. 系统要求

### 1.1 硬件要求
- CPU: 4核以上（推荐8核）
- 内存: 16GB以上（推荐32GB）
- 磁盘: 50GB可用空间

### 1.2 软件依赖
```bash
# macOS (当前环境)
brew install python@3.9 scons protobuf boost m4 pkg-config

# 安装SystemC 2.3.3
cd /tmp
wget https://www.accellera.org/images/downloads/standards/systemc/systemc-2.3.3.tar.gz
tar xzf systemc-2.3.3.tar.gz
cd systemc-2.3.3
mkdir build && cd build
../configure --prefix=/opt/systemc-2.3.3
make -j8 && sudo make install

# 设置环境变量
export SYSTEMC_HOME=/opt/systemc-2.3.3
export LD_LIBRARY_PATH=$SYSTEMC_HOME/lib-macosx64:$LD_LIBRARY_PATH
```

---

## 2. gem5下载和编译

### 2.1 克隆gem5仓库

```bash
cd /Volumes/remote/phd/year_2/project/dft加速
mkdir -p gem5_workspace
cd gem5_workspace

# 克隆gem5（使用stable分支）
git clone https://gem5.googlesource.com/public/gem5
cd gem5
git checkout stable

# 查看版本
git log -1 --oneline
```

### 2.2 配置SystemC支持

gem5从v21.0开始原生支持SystemC TLM-2.0。检查配置：

```bash
# 检查SystemC配置
cat build_opts/X86

# 应该包含：
# PROTOCOL = 'MI_example'
# USE_SYSTEMC = True
```

如果没有，创建自定义配置：

```bash
cat > build_opts/X86_SYSTEMC << 'EOF'
TARGET_ISA = 'x86'
CPU_MODELS = 'AtomicSimpleCPU,TimingSimpleCPU,O3CPU'
PROTOCOL = 'MI_example'
USE_SYSTEMC = True
SYSTEMC_INC = '/opt/systemc-2.3.3/include'
SYSTEMC_LIB = '/opt/systemc-2.3.3/lib-macosx64'
EOF
```

### 2.3 编译gem5

```bash
# 编译（使用8个并行任务）
scons build/X86/gem5.opt -j8 \
    SYSTEMC_INC=/opt/systemc-2.3.3/include \
    SYSTEMC_LIB=/opt/systemc-2.3.3/lib-macosx64

# 预计编译时间：30-60分钟（首次编译）
```

**常见编译错误和解决方案：**

1. **错误：找不到SystemC头文件**
   ```bash
   # 解决：显式指定SystemC路径
   export SYSTEMC_HOME=/opt/systemc-2.3.3
   ```

2. **错误：Python版本不兼容**
   ```bash
   # 解决：使用Python 3.9
   brew install python@3.9
   export PATH="/opt/homebrew/opt/python@3.9/bin:$PATH"
   ```

3. **错误：protobuf版本冲突**
   ```bash
   # 解决：重新安装protobuf
   brew reinstall protobuf
   ```

### 2.4 验证编译成功

```bash
# 运行简单测试
./build/X86/gem5.opt configs/example/se.py -c tests/test-progs/hello/bin/x86/linux/hello

# 应该输出：
# Hello world!
# Exiting @ tick 5123000 because exiting with last active thread context
```

---

## 3. gem5-SystemC TLM示例

### 3.1 gem5内置TLM示例

gem5提供了TLM桥接示例：

```bash
# 查看TLM相关文件
ls -la util/tlm/

# 应该看到：
# - src/sc_master_port.cc      # gem5 → SystemC
# - src/sc_slave_port.cc       # SystemC → gem5
# - examples/                  # 示例程序
```

### 3.2 编译TLM示例

```bash
cd util/tlm
mkdir build && cd build

# 配置
cmake .. \
    -DCMAKE_PREFIX_PATH=/opt/systemc-2.3.3 \
    -DGEM5_ROOT=../../..

# 编译
make -j8

# 应该生成：
# - gem5.opt.sc              # gem5+SystemC集成可执行文件
# - examples/slave_port/gem5.opt.sc
# - examples/master_port/gem5.opt.sc
```

### 3.3 运行TLM示例

```bash
# 示例1: gem5作为master，SystemC作为slave
cd examples/slave_port
./gem5.opt.sc ../../../../configs/example/se.py \
    --cpu-type=TimingSimpleCPU \
    -c ../../../../tests/test-progs/hello/bin/x86/linux/hello

# 示例2: SystemC作为master，gem5作为slave
cd examples/master_port
./gem5.opt.sc
```

**预期输出：**
```
gem5 Simulator System.  http://gem5.org
...
SystemC 2.3.3 --- Apr 20 2026 10:00:00
...
TLM-2.0 transaction: WRITE addr=0x1000 data=0x42
TLM-2.0 transaction: READ addr=0x1000 data=0x42
...
Hello world!
Simulation complete.
```

---

## 4. 验证清单

完成以下验证后，Phase 0完成：

- [ ] gem5编译成功（`build/X86/gem5.opt`存在）
- [ ] gem5能运行简单程序（hello world）
- [ ] SystemC库正确安装（`/opt/systemc-2.3.3`）
- [ ] TLM示例编译成功
- [ ] TLM示例运行成功（gem5 ↔ SystemC通信）

---

## 5. 故障排除

### 5.1 macOS特定问题

**问题：dyld: Library not loaded: libsystemc-2.3.3.dylib**

解决：
```bash
# 添加到~/.zshrc或~/.bash_profile
export DYLD_LIBRARY_PATH=/opt/systemc-2.3.3/lib-macosx64:$DYLD_LIBRARY_PATH
source ~/.zshrc
```

**问题：clang++编译错误（C++标准不兼容）**

解决：
```bash
# gem5需要C++17
export CXXFLAGS="-std=c++17"
scons build/X86/gem5.opt -j8 CXXFLAGS="-std=c++17"
```

### 5.2 性能优化

**加速编译：**
```bash
# 使用ccache
brew install ccache
export PATH="/opt/homebrew/opt/ccache/libexec:$PATH"

# 重新编译
scons build/X86/gem5.opt -j8
```

**减少内存占用：**
```bash
# 使用更少的并行任务
scons build/X86/gem5.opt -j4
```

---

## 6. 下一步

Phase 0完成后，进入Phase 1：
1. 创建FPGAAccelerator PCIe设备类
2. 实现MMIO寄存器空间
3. 添加TLM initiator socket

**预计时间：** Phase 0需要1-2天（包括下载、编译、调试）

---

## 参考资料

- gem5官方文档：https://www.gem5.org/documentation/
- gem5 SystemC TLM：https://www.gem5.org/documentation/general_docs/systemc/
- SystemC TLM-2.0：https://www.accellera.org/downloads/standards/systemc
- gem5 TLM示例：https://github.com/gem5/gem5/tree/stable/util/tlm
