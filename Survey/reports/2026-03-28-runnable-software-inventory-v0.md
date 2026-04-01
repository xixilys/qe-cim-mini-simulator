# 2026-03-28 Runnable software inventory v0

## 1. 目标

这份笔记是当前自主推进路线里的第一步：

> 先盘点本地到底哪些 `QE / VASP / CP2K` 相关软件对象是真正可运行的，哪些只是源码或文档可读，哪些在当前环境下无法直接执行。

这一步的作用不是做架构判断，而是给后续“通过跑能跑的软件恢复计算流程与负载分配”建立一个明确边界。

## 2. 当前 workspace 中可见的软件对象

当前仓库内与三类软件相关的对象主要有：

- `soft/qe-7.5/`
- `soft/cp2k/`
- 若干 `QE` 相关输入、补丁、trace 摘要脚本与临时 dump 目录
- 没有看到本地 `VASP` 可执行程序

同时，当前仓库里已经存在与 `QE` band-solver 子系统相关的 SystemC / evaluator 对象：

- `model/qe_band_solver_model/`
- `model/bin/iterative_qe_regression_eval`
- `docs/architecture/qe_band_solver_systemc_overview_20260325.md`
- `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`

## 3. QE 当前状态

### 3.1 结论

`QE` 是当前最有希望直接执行并提取真实流程证据的软件对象。

### 3.2 依据

仓库内存在：

- `soft/qe-7.5/` 完整 workspace copy
- `docs/qe_inputs/` 下若干输入样例
- `docs/benchmarks/` 下针对 `QE` 的 trace/benchmark 脚本
- handoff 文档明确指出一个当前可用的二进制入口：
  - `soft/qe-7.5/build_subspace_trace/bin/pw.x`

同时 handoff 中给出了重编命令：

- `cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4`

这说明：

- 至少在项目设计口径上，`QE` 被视为本地可执行对象；
- 后续可以优先从 `QE` 开始恢复真实运行流程、主要阶段与 `c_bands` 相关负载。

### 3.3 当前阶段判断

`QE` 当前判断为：

- **可优先执行 / 可优先追真实流程**

但仍需在下一步里实际确认：

- `pw.x` 是否当前仍存在且可直接运行
- 现成输入是否能成功跑通
- trace hook / workload dump 是否仍与当前 build 对齐

## 4. CP2K 当前状态

### 4.1 结论

`CP2K` 当前在本地仓库里更像是：

- **源码与 benchmark 可见**
- **但当前环境下不宜直接在本机立即构建运行**

### 4.2 依据

仓库内存在：

- `soft/cp2k/` 完整源码树
- 大量 benchmark 目录
- 官方构建脚本：`soft/cp2k/make_cp2k.sh`

但该脚本明确写了：

- `Darwin` / macOS 当前不支持直接构建
- 更建议在容器或 Linux 环境中构建

这意味着：

- 虽然 `CP2K` 本地源码齐全，适合静态分析与流程恢复；
- 但如果要走“通过跑软件恢复流程”这条路线，当前更合理的是：
  - 先做源码级与 benchmark 级流程识别；
  - 若后续需要真实执行，再转到合适的 Linux/container 环境。

### 4.3 当前阶段判断

`CP2K` 当前判断为：

- **源码可读 / benchmark 可用 / 当前本机不优先执行**

## 5. VASP 当前状态

### 5.1 结论

当前仓库内没有发现 `VASP` 本地可执行对象，也没有发现明显的本地源码树。

### 5.2 依据

当前只看到：

- 早前已经写出的 `VASP/QE/CP2K` 对比分析文档
- 但没有看到 `vasp_std` / `vasp_gam` / `vasp_ncl` 等本地可执行程序
- 也没有看到完整 `VASP` 源码目录

因此当前最稳的判断是：

- `VASP` 目前在这个 workspace 中不属于“立刻可跑”的软件对象
- 后续对 `VASP` 的流程恢复，短期内应来自：
  - 既有文档
  - 源码/补丁（若后续提供）
  - 文献与外部资料

### 5.3 当前阶段判断

`VASP` 当前判断为：

- **当前 workspace 中不可直接执行**

## 6. 第一轮可运行性分类

基于当前盘点，先做一个保守分类：

### 6.1 `QE`

- `可优先执行`
- `可优先恢复真实运行流程`
- `可优先获取阶段负载分配`

### 6.2 `CP2K`

- `源码与 benchmark 可读`
- `当前 macOS 环境下不优先本机构建`
- `先做源码/benchmark/文档级流程恢复`

### 6.3 `VASP`

- `当前 workspace 中未见可执行对象`
- `短期内不能按“本地直接运行”路线推进`
- `先保留为非执行型参考对象`

## 7. 对后续自主推进路线的直接影响

这意味着接下来的顺序不应该平均展开，而应该按下面这个节奏：

1. **先做 QE**
   - 确认 `pw.x` 与输入是否仍可跑
   - 从真实运行里恢复阶段流与负载分配
   - 尽量把 `c_bands`、FFT、projector、subspace solve 这些对象落到真实 evidence 上

2. **再做 CP2K**
   - 不急着先编译
   - 先从 benchmark、源码树和关键入口恢复其主流程与主要计算路径
   - 后续若必须执行，再迁移到更合适的 Linux/container 环境

3. **VASP 先做非执行型恢复**
   - 当前不按“本地跑”推进
   - 先保持它作为 architecture pressure test，而不是第一执行入口

## 8. 当前最合理的下一步

基于这轮盘点，下一步最合理的动作已经比较明确：

- 优先验证 `QE` 当前可执行入口
- 跑一个最小可运行 case
- 记录：
  - 实际运行链路
  - 输入/输出边界
  - 主要阶段
  - 是否能继续抽 workload/trace

然后再写一份：

- `QE executable flow recovery v0`

那份文档会成为后面：

- `QE/VASP/CP2K` 软件流程矩阵
- 硬件单元抽取
- LCW replay body 设计
- SystemC 全流程扩展

的第一块真实执行证据。
