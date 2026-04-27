# gem5 + SystemC WSL 联合调试迁移方案（2026-04-27）

## 1. 目的

把当前 macOS 侧 `gem5_integration/`、`model/qe_band_solver_model/`、DSE 文档和 QE workspace 迁移到 WSL/Linux 侧继续开发，解决 macOS 上 x86 ELF、KVM、SystemC/gem5 FS 调试链路不顺的问题。

本方案不是替代现有架构文档，而是面向“现在怎么在 WSL 上接着调”的执行 runbook。核心路径是：

```text
macOS repo
  /Volumes/remote/phd/year_2/project/dft加速
        │  rsync over ssh alias: wsl
        ▼
WSL repo
  /mnt/f/phd/year_2/project/dft加速
        │
        ├── model/qe_band_solver_model/      # 先验证 SystemC timed-functional model
        ├── gem5_integration/                # 再验证 gem5 FS/PCI/DMA/TLM 路径
        ├── docs/benchmarks/                 # DSE / evidence / result adapters
        └── soft/qe-7.5/                     # QE workspace copy only; 不碰 /Users/xixilys/project/qe-7.5
```

## 2. 当前仓库状态摘要

### 已有资产

- `model/qe_band_solver_model/`：SystemC timed-functional band-solver model，含 Host/FPGA/Chip 与 A/B/C/D 四簇流水线。
- `gem5_integration/gem5/`：已集成过 FPGA device 的 gem5 source tree；本地 build 产物是平台相关产物，迁移到 WSL 后应重编。
- `gem5_integration/src/dev/fpga/`：FPGAAccelerator PCI/MMIO/DMA/TLM 侧源码，可重新复制到 gem5 tree。
- `gem5_integration/configs/`：SE/FS/PCI smoke 配置脚本；FS 路线已有 minimal initramfs、PCI BAR、DMA smoke 的工作记录。
- `gem5_integration/PROJECT_PLAN.md`：记录了截至 2026-04-23 的 gem5 FS + SystemC 进展，优先作为联调状态入口。
- `gem5_integration/docs/timing_model_integration_plan.md`：记录 timing stub / register latency / cluster timing 接入思路。
- `docs/overview/gem5_systemc_cosim_architecture_v1.md` 与 `docs/overview/gem5_systemc_implementation_roadmap.md`：更长期的协同仿真设计与路线图。

### macOS 侧主要限制

- 无 KVM，gem5 FS 只能用较慢 CPU model，长流程调试成本高。
- macOS ARM64 生成 Mach-O/ARM64 二进制；gem5 X86 测试需要 Linux x86 ELF 或交叉编译。
- SystemC/gem5 链接、`sc_main` stub、TLM socket 调试在 Linux 上更直接。
- Ubuntu/rootfs/gem5 resource 下载和断点续传工具在 Linux/WSL 更方便。

### WSL 侧优先级

1. 先把 `ssh wsl` 作为统一入口，避免路径和认证反复配置。
2. 先跑 standalone SystemC smoke，确保基础编译链路可用。
3. 再跑 gem5 FPGA device / PCI BAR / DMA smoke，避免一开始就进入完整 QE FS。
4. 最后接入真实 QE offload 或 DSE Stage-B 证据链。

## 3. WSL 目录与同步策略

### 目标目录

```bash
/mnt/f/phd/year_2/project/dft加速
```

### 同步原则

- 同步源码、文档、未提交修改、QE workspace copy、gem5 source tree。
- 不同步 macOS/Linux 无法复用的重型构建产物：gem5 build、CMake build、venv、m5out、Python cache。
- 不使用 `--delete`，避免误删 WSL 侧后续调试产物。
- 第一次同步后，WSL 侧作为 gem5/SystemC 联调主工作区；macOS 侧继续只做文档/轻量编辑时，需再 rsync 增量同步。

建议同步命令：

```bash
rsync -az --human-readable --info=progress2 \
  --exclude='.DS_Store' \
  --exclude='.opencode/' \
  --exclude='.venv/' \
  --exclude='dse_v2/venv/' \
  --exclude='**/__pycache__/' \
  --exclude='**/.pytest_cache/' \
  --exclude='m5out/' \
  --exclude='**/m5out/' \
  --exclude='gem5_integration/gem5/build/' \
  --exclude='gem5_integration/gem5/build.log' \
  --exclude='gem5_src/build/' \
  --exclude='model/qe_band_solver_model/build/' \
  --exclude='model/ozaki_subspace_model/bin/' \
  --exclude='soft/qe-7.5/build/' \
  --exclude='soft/qe-7.5/build_subspace_trace/' \
  /Volumes/remote/phd/year_2/project/dft加速/ \
  wsl:/mnt/f/phd/year_2/project/dft加速/
```

> 说明：`soft/qe-7.5/external/` 暂时保留，因为 QE workspace 可能依赖外部子树；如果 WSL 空间紧张，再单独裁剪。

## 4. WSL 环境检查与依赖

进入 WSL：

```bash
ssh wsl
cd /mnt/f/phd/year_2/project/dft加速
```

基础检查：

```bash
uname -a
which gcc g++ cmake make python3 scons || true
python3 --version
```

推荐 Ubuntu/WSL 依赖（如缺失再装）：

```bash
sudo apt update
sudo apt install -y \
  build-essential git cmake ninja-build pkg-config python3 python3-venv python3-pip \
  scons m4 zlib1g-dev libprotobuf-dev protobuf-compiler libgoogle-perftools-dev \
  libboost-all-dev libhdf5-dev libpng-dev libelf-dev wget curl gdb rsync
```

SystemC 可选路径：

```bash
# 若已有系统包或手工安装，优先设置：
export SYSTEMC_HOME=/usr/local/systemc
export LD_LIBRARY_PATH="$SYSTEMC_HOME/lib-linux64:$SYSTEMC_HOME/lib:$LD_LIBRARY_PATH"
```

## 5. 分阶段联调路线

### Phase A：确认 WSL copy 和文档/源码完整性

```bash
cd /mnt/f/phd/year_2/project/dft加速
find gem5_integration -maxdepth 2 -type f | head
find model/qe_band_solver_model -maxdepth 2 -type f | head
git status --short | head -80
```

成功标准：

- `gem5_integration/PROJECT_PLAN.md`、`gem5_integration/src/dev/fpga/fpga_accelerator.cc` 存在。
- `model/qe_band_solver_model/CMakeLists.txt` 存在。
- dirty tree 与 macOS 侧一致或至少包含当前未提交工作。

### Phase B：先跑 standalone SystemC / compatibility smoke

```bash
cd /mnt/f/phd/year_2/project/dft加速/model/qe_band_solver_model
rm -rf build
mkdir -p build
cd build
cmake ..
make -j"$(nproc)"
./qe_band_solver_model
```

如果 WSL 安装了真实 SystemC，再跑：

```bash
cmake .. -DQE_BAND_SOLVER_USE_SYSTEMC=ON -DSYSTEMC_HOME="$SYSTEMC_HOME"
make -j"$(nproc)"
./qe_band_solver_model
```

成功标准：

- 可执行文件生成。
- basic workload 输出四簇 timing / SCF orchestration 信息。
- 如果真实 SystemC 失败，先保留 compatibility layer 结果，不阻塞 gem5 stub 路线。

### Phase C：重建 gem5 + FPGA device

```bash
cd /mnt/f/phd/year_2/project/dft加速/gem5_integration
./scripts/setup_gem5.sh
cd gem5
scons build/X86/gem5.opt USE_SYSTEMC=1 -j"$(nproc)"
```

成功标准：

```bash
grep -R "USE_SYSTEMC" build/X86/python/m5/defines.py
./build/X86/gem5.opt --version
```

注意：

- macOS 侧的 `gem5_integration/gem5/build/` 不迁移；WSL 必须本地重编。
- 如果 `USE_SYSTEMC=1` 链接失败，先用非 SystemC build 验证 PCI/MMIO/DMA，再回头处理 SystemC link/stub。

### Phase D：gem5 device / FS smoke 顺序

按从小到大的顺序跑，避免一上来完整 QE：

```bash
cd /mnt/f/phd/year_2/project/dft加速/gem5_integration

# 1. Python object availability
python3 test_fpga_device.py

# 2. FPGA device instantiation/config smoke
./gem5/build/X86/gem5.opt configs/fpga_device_test.py --binary=qe_test_program/fpga_test

# 3. FS minimal/PCI smoke（按已有 PROJECT_PLAN.md 状态继续）
GEM5_CPU_TYPE=atomic GEM5_MAX_TICKS=1000000000000 \
  ./gem5/build/X86/gem5.opt configs/fpga_fs_complete.py
```

成功标准：

- `FPGAAccelerator` 能从 `m5.objects` 导入并实例化。
- PCI BAR / MMIO read-write 在 debug log 中可见。
- DMA smoke 先完成 4/4，再接 QE-like offload。

### Phase E：接回 SystemC timing model

目标不是马上做真实全 QE，而是先完成三层闭环：

```text
MMIO START
  → gem5 FPGA device writeRegister()
  → TLM/stub/SystemC timing model
  → gem5 event schedule computeDoneEvent
  → guest 轮询或中断看到 done
```

建议调试点：

- gem5：`--debug-flags=FPGAAccelerator,FPGADMA`。
- SystemC：给 TLM target / timing stub 增加事务计数和 `sc_time_stamp()` 输出。
- 统一时间轴：记录 `curTick()`、TLM delay、cluster cycles、guest-visible done tick。

最小验收字段：

```text
case_id, command, guest_start_tick, mmio_start_tick, dma_bytes,
systemc_delay_ns, compute_done_tick, guest_done_tick, status_reg, pass/fail
```

## 6. 调试策略

### gem5 侧

```bash
./gem5/build/X86/gem5.opt \
  --debug-flags=FPGAAccelerator,FPGADMA \
  --debug-file=fpga_debug.log \
  configs/fpga_fs_complete.py
```

看点：

- BAR0 地址是否与 guest 访问地址一致。
- `read()` / `write()` 是否被触发。
- DMA state 是否按 IDLE → READING → WRITING → DONE 走完。
- `computeDoneEvent` 是否调度，`STATUS_COMPUTE_DONE` 是否置位。

### guest / initramfs 侧

- 优先使用已有 minimal rootfs 和静态测试程序，不先移植完整 QE。
- `/dev/mem` 或 sysfs `resource0` 访问必须输出寄存器读写地址和值。
- 每个 smoke 程序退出码要可被 gem5 run script 捕获。

### SystemC 侧

- standalone model 先保持可运行。
- gem5 bridge 先用 timing stub 验证时间同步，再接完整 `DFTHybridSystem`。
- 对每个 command 输出 `command_id`、输入矩阵/SCF 参数摘要、cluster cycles、总 delay。

## 7. 推荐当前执行顺序

1. 完成 rsync 到 `/mnt/f/phd/year_2/project/dft加速`。
2. WSL 上跑 Phase A 检查。
3. WSL 上跑 Phase B compatibility SystemC smoke。
4. WSL 上重编 gem5，先不要求完整 FS QE。
5. 跑 Python object/device smoke。
6. 跑 PCI BAR/MMIO smoke。
7. 跑 DMA smoke。
8. 跑 QE-like offload smoke。
9. 再接完整 SystemC timing model。
10. 最后才进入完整 QE electrons / DSE evidence 采集。

## 8. 风险和边界

- `/mnt/f` 是 Windows 挂载盘，编译大量小文件可能慢；如果 gem5 build 太慢，可把 `gem5_integration/gem5/build/` 放到 WSL ext4（如 `~/build/gem5-dft`），源码仍在 `/mnt/f`。
- `rsync` 本方案不删除目标端文件；后续若 WSL 侧成为主工作区，反向同步前必须确认方向，避免覆盖新调试结果。
- `soft/qe-7.5/` 是 workspace copy，可以改；不要把任何操作指向 `/Users/xixilys/project/qe-7.5`。
- 当前 DSE/benchmark 结论仍服从 adjudicator authority contract；gem5/SystemC 联调结果是 evidence input，不自动升级为 thesis-grade final claim。
