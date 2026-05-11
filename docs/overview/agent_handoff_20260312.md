# Agent Handoff 2026-03-12

## 1. 作用

这份 handoff 现在只保留仓库级指导信息。

项目的完整设计演进、阶段判断和历史思路，已经统一整理到：

- [`docs/overview/project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/project_development_timeline.md)

如果要快速理解项目背景，先读总时间线；如果要继续做 `QE` 采样与复现实验，再读：

- [`docs/overview/qe_subspace_sampling.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/qe_subspace_sampling.md)

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

这些判断的上下文和来龙去脉，都在 [`docs/overview/project_development_timeline.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/overview/project_development_timeline.md) 中。

## 5. 当前优先级

当前最重要的不是重新做 workload 画像，也不是继续优先下钻更深一层 body catalog 冻结；
当前已经切换到一个新的阶段：

> 先做 `QE` 主线 `SCF iteration shell` 的 modeling / system exploration

当前建议优先推进的是：

1. 把下面这条主线作为一个完整系统对象建模：
   - `rho -> Veff`
   - `while bands not converged:`
     - `h_psi`
     - `s_psi`
     - `build H_sub / S_sub`
     - `cdiaghg`
     - `refresh / residual -> P_next`
   - `psi -> rho_out`
2. 先探索 `Host / FPGA / Chip` 三层分工、resident object 和边界数据量；
3. 第一版允许把 `cdiaghg` 暂时保留在 `CPU / soft-core companion solver`，优先把 `h_psi / s_psi + build + refresh` 做成系统闭环；
4. 在 shell-level modeling 稳定之后，再决定哪些 body、route 和 exception path 继续往冻结规格推进。

## 6. 可直接复用的命令

### 6.1 重新编译工作区 QE copy

```bash
cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4
```

### 6.2 运行 trace 摘要

```bash
python3 /Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/summarize_qe_subspace_trace.py /Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_fe_trace.csv
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
当前已经进入 `modeling / system exploration phase`：先以 [`docs/architecture/system_design_master_spec_v0.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/system_design_master_spec_v0.md) 和 [`docs/benchmarks/si8_scf_operator_load_experiment_plan.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/si8_scf_operator_load_experiment_plan.md) 为入口，把 `QE` 的 `SCF iteration shell` 作为系统对象继续推进分工、驻留和边界流量建模。
