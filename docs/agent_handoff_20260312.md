# Agent Handoff 2026-03-12

## 1. 作用

这份 handoff 现在只保留仓库级指导信息。

项目的完整设计演进、阶段判断和历史思路，已经统一整理到：

- [`docs/project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/project_development_timeline.md)

如果要快速理解项目背景，先读总时间线；如果要继续做 `QE` 采样与复现实验，再读：

- [`docs/qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/qe_subspace_sampling.md)

## 2. 项目目标

当前项目的长期目标是：

- 面向 `QE / PySCF` 这类 DFT 科学计算软件
- 设计一套以 `NML + CIM` 为核心的科学计算加速系统
- 当前论文切口聚焦在 `QE Davidson` 子空间里的 Hermitian / generalized Hermitian 对角化
- 同时原生支持其中用到的 `complex FP64 GEMM`

## 3. 硬约束

### 3.1 绝对不要碰主目录 QE

- **不要修改** `/Users/xixilys/project/qe-7.5`
- 所有 `QE` 相关工作都必须只在工作区副本 [`soft/qe-7.5`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5) 中进行

### 3.2 当前可用的本地 QE 二进制

- [`soft/qe-7.5/build_subspace_trace/bin/pw.x`](/Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace/bin/pw.x)

这个版本已经包含对子空间对角化入口的采样 hook。

## 4. 当前稳定结论

- 真实 `QE` 子空间样本已经覆盖 `Si`、`Fe`、`C6H6`、`graphene`、`Au slab`、`SiC32`
- generalized Hermitian 是主路径，不是边角情况
- `S_sub` 不能被忽略，单一 `Si` case 不能代表整体 workload
- `complex FP64 GEMM` 仍是关键算力底座
- 电路叙事已经从“通用 GEMM-CIM + transpose”转向“adjoint-aware projector primitive”

这些判断的上下文和来龙去脉，都在 [`docs/project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/project_development_timeline.md) 中。

## 5. 当前优先级

当前最重要的不是重新做 workload 画像，而是继续把下面几条主线收敛下来：

1. `Ozaki-II / CRT / 3M` 这一条 `complex FP64 GEMM` 主算法
2. `NML` 侧 generalized eigensolver 的冻结路线
3. `Adjoint-Aware Projector Primitive` 相对 `GEMM baseline` 与 `transpose-aware baseline` 的收益表达

## 6. 可直接复用的命令

### 6.1 重新编译工作区 QE copy

```bash
cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4
```

### 6.2 运行 trace 摘要

```bash
python3 /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/summarize_qe_subspace_trace.py /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_fe_trace.csv
```

### 6.3 构建 generalized_subspace_eval

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
make bin/generalized_subspace_eval
```

### 6.4 运行 generalized_subspace_eval

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/model
./bin/generalized_subspace_eval
```

## 7. 给下一位 agent 的一句话

不要重新铺陈历史设计文档，也不要从零重建工作负载画像。  
先以 [`docs/project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/project_development_timeline.md) 为入口，在现有样本和原型基础上继续推进算法冻结与 primitive 建模。
