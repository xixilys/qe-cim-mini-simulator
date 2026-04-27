# QE shell-level `CPU only` / `CPU + GPU` / `CPU + FPGA` 对比计划（v0，2026-04-02）

## 0. 目的

这份文档对应 `Task 6`：

- 在**同一个 QE shell** 上比较 `CPU only`、`CPU + GPU`、`CPU + FPGA`；
- 不拿孤立 kernel 峰值做宣传；
- 只在公平 shell-level 语义下判断 `CPU + FPGA` 是否赢、赢在哪里、为什么赢。

从 `2026-04-13` 起，本文不再单独承载所有冻结项；以下三份合同文件应与本文一起阅读：

- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`

### 当前本地执行阶段的收口

虽然最终合同仍保留 `CPU + GPU` 行作为完整 fairness contract 的一部分，但**当前本地可执行阶段**已经收口为：

- `CPU only`
- `CPU + FPGA`

原因如下：

- 当前本地已经拿到了 `CPU only` 的真实 QE timing；
- 当前本地还没有可声明 precision mode 的 `CPU + GPU` shell baseline 机器与运行结果；
- 因此 Task 6 的当前推进重点，是先把 `CPU only` 与 `CPU + FPGA` 的同 shell 口径打实，再把 GPU 行保留为后续补齐项，而不是用替代值冒充。

当前项目的被研究对象仍然是：

- `QE-connected band-solver subsystem`
- 不是完整 `DFT SoC`
- 也不是单独的 reduced eigensolver 芯片

因此这里的比较对象是：

`rho -> Veff -> while bands not converged { h_psi, s_psi, build H_sub / S_sub, cdiaghg, refresh / residual -> P_next } -> psi -> rho_out -> mix_rho`

## 1. 冻结后的 baseline 口径

### 1.1 `CPU only`

定义：

- 相同 `QE` shell 全部由 host CPU / software path 执行；
- 不引入 GPU 或 FPGA offload；
- 所有 shell-visible 调用、同步、layout transform、memory traffic 都算在内。

### 1.2 `CPU + GPU`

定义：

- 保持相同 `QE` shell 语义；
- 允许 dense / FFT / operator kernels 使用 GPU library 或 kernel offload；
- CPU 仍负责 orchestration、异常路径、未下沉阶段；
- 所有 Host-GPU launch / sync / transfer / temporary layout cost 必须计入。

这里必须区分两种 GPU baseline：

1. **Strict-FP64 GPU baseline**
   - 尽量保持 `FP64`、与软件参考接近的数学路径；
   - 这是和 `CPU + FPGA` 做“同精度公平对比”的首选 baseline。
2. **Practical GPU baseline**
   - 允许采用现实工程里更常见的 vendor-library / batched / mixed-precision-friendly path；
   - 这是“现实部署吞吐”口径下的辅助 baseline。

如果后续只能拿到其中一种 GPU baseline，也必须在结果表里明确写出是哪一种，不能把两者混写成一个抽象的 “GPU”。

### 1.3 `CPU + FPGA`

定义：

- 相同 `QE` shell 语义；
- 当前 v1 首选 clustered hardware path 包含 `h_psi`、`s_psi`、`build H_sub / S_sub`、`cdiaghg`、`refresh / residual -> P_next`；
- `cdiaghg` 的 host CPU 或 FPGA-local soft-core companion 只作为 fallback / overflow / bring-up contingency；
- 所有 Host-FPGA、FPGA-companion、FPGA-off-chip-memory 的成本都必须计入。

### 1.4 当前比较结论的范围

因为本项目本身是 `CPU + FPGA` 方向，所以当前真正需要回答的问题只有两个：

1. 相对 `CPU only`，`CPU + FPGA` 是否带来明确 shell-level 系统收益；
2. 相对 `CPU + GPU`，`CPU + FPGA` 是否存在明确的 win region，或者至少存在不同的 trade-off 优势。

## 2. 冻结后的 workload 口径

### 2.1 总原则

工作负载必须来自真实 `QE` trace-backed case，而不是单一 toy example。

### 2.2 两层 workload 组织

从 `2026-04-13` 起，**phase-1 decisive roster 以**
`docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
**为准**。本节保留的是较早期的 workload 叙事分层，用于解释为什么这些 family 曾被纳入候选池；
若与冻结后的 phase-1 roster 不一致，应以后者为准。

为兼顾当前本地样本与器件导向叙事，比较矩阵分成两层：

#### Layer A：主结论 case（优先决定最终结论）

- `Si`
- `small-Si proxy`
- `graphene`
- `Au slab`
- `SiC32`（近期待补齐）
- `bn32_pbe_uspp`（作为 projector-heavy stress）

这些 case 更贴近：

- bulk semiconductor
- small semiconductor sanity / bring-up proxy
- 2D transport proxy
- contact / interface
- wide-bandgap / device-relevant path
- basis / projector stress

#### Layer B：本地辅助 case（可纳入首轮表格，但不主导最终器件结论）

- `Fe`
- `benzene / C6H6`

这两个 family 可以保留在首轮对比矩阵中，原因是：

- 本地已有资料和历史 trace 更容易复用；
- 它们对 solver path、projector pattern、shape 多样性仍有参考价值。

但最终论文或主叙事中，`Fe` 和 `benzene/C6H6` 只能作为：

- auxiliary stress / sanity cases；
- 不能替代器件导向主负载。

### 2.3 每个 case 至少要冻结的字段

每个 case 至少记录：

- `npw`
- projector count / `nkb`
- basis size / subspace size
- FFT grid
- dominant solver path
- `c_bands` / `SCF iteration` 结构
- generalized ratio 或 overlap-path 特征

### 2.4 关于新增 small-Si workload 的当前结论

当前仓库里已经新增并跑通了一个真实 `small-Si` 负载：

- case id：`si4_pbe_uspp_small`
- input：`docs/qe_inputs/si4_pbe_uspp_small.in`

它当前承担的角色是：

- 3–4 atom class 小尺度半导体 bring-up / sanity proxy

因此：

- `small-Si` 不再是 pending 槽位；
- 当前最近的 ready Si family 现在包括：
  - `si4_pbe_uspp_small`
  - `si8_pbe_uspp`
  - `si8_pbe_nc`

## 3. 冻结后的比较指标

### 3.1 主性能指标

- `c_bands episode` latency
- `SCF iteration` latency
- shell-level wall time
- speedup vs `CPU only`
- speedup vs `CPU + GPU`

### 3.2 系统流量指标

- Host-device traffic
- FPGA off-chip-memory traffic
- GPU memory / Host-GPU traffic
- resident / spill accounting
- companion-solver boundary traffic

### 3.3 利用率指标

- stage stall ratio
- overlap efficiency
- dominant backpressure path
- effective utilization

### 3.4 能耗指标

- energy per `c_bands episode`
- energy per `SCF iteration`
- breakdown by host / device / memory / companion if available

### 3.5 数值一致性 / 精度 / 可复现性指标

这部分是当前用户新增、而且值得保留的次级比较维度。

但这里必须写得严谨：

> 不能预设“GPU 精度一定比 FPGA 差”；只能把它表述为一个待验证的 secondary claim。

后续应该检查的不是抽象“精度更高”，而是以下可比较对象：

- `H_sub` / `S_sub` 的最大绝对误差与相对误差
- `C` / `Lambda` 的偏差
- residual norm 偏差
- density norm / mixed-density 偏差
- `SCF iteration` 数漂移（是否因数值路径不同导致多迭代或少迭代）
- reproducibility class
  - bitwise repeatable
  - numerically stable but non-bitwise-repeatable
  - mixed-precision / nondeterministic

### 3.6 为什么这一项可以成为故事的一部分

更稳妥的表述应是：

- 很多现实 GPU baseline 为了吞吐会使用 vendor-library path、batched reduction、甚至 mixed-precision-friendly route；
- `CPU + FPGA` 路径则可能更容易保持受控的 `FP64` datapath、固定归约顺序、或更接近软件参考的累加次序；
- 因此 `CPU + FPGA` **可能** 在数值一致性、可复现性或 strict-FP64 fidelity 上更有优势；
- 但这一点必须依赖实际 baseline 配置与测量，不能在没有对照的情况下先下结论。

## 4. 当前 Task 6 的公平性规则

只有满足下面这些条件，结果才可用于结论：

1. 比较的是**同一个 shell**，不是不同软件路径拼接出来的数字；
2. 所有 baseline 都用相同 case 描述字段；
3. 所有 launch / sync / transfer / companion / layout-transform cost 都在 steady-state 统计中；
4. 任何精度结论都必须标明对应 baseline 的 precision mode；
5. 不允许拿“理论 GPU 峰值”去和“包含系统开销的 FPGA shell”直接比较；
6. 不允许用单个 hand-picked case 宣称普遍胜利。

### 4.1 正确性与替代方法披露规则

用户已进一步冻结一条执行原则：

> 要优先保证计算结果与比较口径的正确性；如果使用任何 proxy / surrogate / contract-layer substitute，就必须显式汇报，不能静默混入主结果表。

因此本阶段再增加三条硬规则：

1. **不允许**把 analytical lower bound、body-level proxy、contract-layer ref-cycle、或 architecture design-point 推导值，直接写成“已验证的 shell latency / speedup”；
2. 如果某一行结果仍来自 proxy，则该行必须显式标注：
   - `proxy_type`
   - `why_proxy_is_used`
   - `what_real_measurement_is_still_missing`
3. 当前 `model/qe_band_solver_model` 的 shell-stage totals 只能作为：
   - shell contract 对齐；
   - traffic / stall / boundary accounting proxy；
   - implementation-facing clustered model 的上层约束；
   不能被当作已经完成的 hardware-`cdiaghg` v1 实测结果。

## 5. 当前推荐的 Task 6 执行顺序

### Step 1：冻结 case list

先冻结首轮比较表的 case 清单：

- 主表至少覆盖 `Si`、`graphene`、`Au slab`
- 辅助表可补 `Fe`、`benzene/C6H6`
- 若本地整理及时，补进 `SiC32`

### Step 2：先填 `CPU only`

先用已有 analytical model + local scripts 填 `CPU only` 列：

- `docs/benchmarks/qe_shell_stage_analytical_bounds_model_v0.md`
- `docs/benchmarks/run_cpu_baseline.py`

这里的作用不是直接给出最终 shell time，而是冻结：

- per-stage accounting 口径
- CPU 侧参考 micro-benchmark
- case descriptor fields

### Step 3：定义 `CPU + GPU` baseline contract

在没有完整 GPU 数据之前，先冻结 GPU baseline 的**报告模板**：

- GPU mode = `Strict-FP64` or `Practical`
- offloaded stages
- Host-GPU transfer path
- launch / sync granularity
- precision mode
- reproducibility class

### Step 4：提取 `CPU + FPGA` shell numbers

从当前 `model/qe_band_solver_model` 提取：

- per-iteration shell-stage totals
- shell-level traffic totals
- backpressure / stall totals
- companion boundary traffic proxy

当前可直接复用：

- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`

但这里必须加一个当前阶段限制：

- 现有 runnable shell model 仍然是 **shell-contract / body-accounting proxy**；
- 它现在能提供公平 shell 边界上的 traffic / ref-cycle / stall accounting；
- 但它还不是 Task 6 最终要比较的 **hardware-`cdiaghg` clustered v1** 实现证据。

因此本步骤应拆成两个子步骤：

1. 先从 runnable shell model 提取 **contract-layer totals**；
2. 再把这些 totals 与 `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md` 的 cluster-level design-point 结果合并，形成真正对应“hardware `cdiaghg` 优先”架构的 `CPU + FPGA` 行。

### Step 5：生成统一对比表头

统一表头建议为：

- case id
- baseline class
- precision mode
- episode latency
- SCF iteration latency
- shell wall time
- host-device bytes
- off-chip bytes
- stall ratio
- energy / episode
- residual / density fidelity
- reproducibility class
- notes

### Step 6：只在 win region 明确后再写结论

当前允许写的结论应分成三类：

- `CPU + FPGA` clearly wins
- `CPU + FPGA` competitive but traffic-limited
- `CPU + GPU` remains stronger under this case / precision mode

而不能先写一个无条件的“FPGA 一定优于 GPU”。

## 6. 当前阶段的交付物

Task 6 的当前版本至少应产出：

1. 一份冻结后的 shell-level comparison contract
2. 一份 case matrix（主 case + 辅助 case）
3. 一份 baseline reporting template
4. 一份关于 precision/fidelity story 的可验证表述
5. 一份显式的执行状态记录，区分“已经跑出的 contract-layer 结果”和“仍待补齐的 CPU/GPU/clustered-FPGA 实测或建模结果”
6. 一份替代方法披露记录，明确哪些数字是真实执行结果，哪些数字仍然只是 proxy / contract-layer / analytical support

本文件即是第 1、3、4 项的 v0 冻结件。
当前第 5 项的执行记录见 `docs/benchmarks/qe_cpu_gpu_fpga_shell_comparison_status_20260402.md`。
