# QE 系统 DSE 前端输入：kernel characterization matrix v0

## 0. 定位

这份文档把当前仓库里已经完成的 **workload characterization** 证据收口成一个可以直接喂给后续

- `host / FPGA / chip` 功能切分；
- system-level DSE 轴选择；
- kernel mapping / tile / dataflow / buffer 探索；
- fast-layer proxy / next-stage phase runner

的 **Step-1 输入 artifact**。

这里不重新做新的 QE rerun，而是把已有证据整理成对后续 DSE 最有用的形式：

1. 先确认哪些 kernel 真正值得作为 accelerator 候选；
2. 再明确它们更偏 compute-bound 还是 memory/buffer-sensitive；
3. 最后把这些判断翻译成后续 DSE 的参数与边界输入。

---

## 1. 证据来源

当前矩阵只使用仓库内已经存在的本地证据：

- 顶层 workload 复核：
  - `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_system_workload_revalidation_report_20260321.md`
  - `docs/benchmarks/archive/results/qe_workload_revalidation/summary.json`
  - `docs/benchmarks/archive/results/qe_workload_revalidation/summary_tables.md`
- 子空间与 generalized 主路径采样：
  - `docs/overview/qe_subspace_sampling.md`
- 算子级 / 数据流级分析：
  - `docs/benchmarks/si8_scf_operator_load_experiment_plan.md`
  - `tools/benchmarks/analyze_qe_scf_operator_load.py`
- 计算模式与硬件亲和性分析：
  - `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_step1_computational_pattern_analysis_report.md`
  - `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_multi_case_analysis_report.md`
- kernel mapping 层 DSE：
  - `docs/benchmarks/archive/reports/docs/benchmarks/archive/reports/qe_step2_kernel_mapping_dse_report.md`
  - `tools/benchmarks/qe_kernel_mapping_dse_step2.py`
- 系统级 DSE 主线与开放轴：
  - `docs/benchmarks/qe_ic_system_level_dse_axes_v0.md`
  - `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`
  - `docs/overview/agent_handoff_20260312.md`
- 当前 system-level runnable model 对 shell stage 的映射：
  - `model/qe_band_solver_model/README.md`
  - `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`

---

## 2. Step-1 冻结结论

从现有 workload characterization 里，先冻结 5 条对后续 DSE 最关键的判断：

1. 在成功 full-run 的真实 `QE` case 中，`electrons` 时间主热点稳定落在 **`c_bands`**，其 share 大约在 `45% ~ 95%`。
2. Davidson 主路径里，真正最重的不是 reduced diag，而是 **`h_psi / s_psi` operator application**；其中 `h_psi` 在 `*egterg` 中经常占 `80% ~ 98%`。
3. generalized Hermitian / overlap 不是边角路径，`S_sub` 与 `s_psi` 在大量 case 中都必须保留。
4. `functional / pseudo` 会改变系统路径：`PBE` 常走 Davidson，而当前真实输入下的 `PBE0` 会切到 `CG`，因此系统边界必须允许 `CG fallback / companion path`。
5. 当前系统级对象应被表述为 **QE-connected band-solver subsystem**，不是“完整 DFT SoC”，也不是“只做 `cdiaghg` 的芯片”。

---

## 3. Kernel characterization matrix

下表面向后续 DSE，而不是为了再解释一次软件算法。每一行都回答：

- 这个 kernel 在系统里是不是热点；
- 它更偏 compute-bound 还是 memory/buffer-sensitive；
- 它需要什么样的复用 / buffer / interface；
- 第一波更适合放在 host、FPGA 还是 chip。

| Kernel / stage | 热点证据 | 代表尺寸 / 工作集 | compute-vs-memory 倾向 | 复用 / 访存 / 依赖 | 精度要求 | Step-1 placement judgement | 后续 DSE 主要 knobs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `h_psi` | `si8_pbe_uspp` 中 `h_psi = 0.28 s / 53 calls`；在 `cegterg` 中约占 `68%`；在 Davidson case 中 `*egterg -> h_psi = 80% ~ 98%` | `npw=2945`, `nkb=144`, `m=1~32`; `psi(G)` `736.25 KiB`; `psi(r)` `11.39 MiB`; `beta(G)` `6.47 MiB`；`m=16` 时约 `227.447M` real-flops | **混合型**：`m=16~32` 时 AI 约 `11~13`，偏 compute-bound；`m=1~4` 时 AI 约 `3~5`，更 balanced / bandwidth-sensitive；FFT 展开会放大工作集 | `beta` 可常驻，`psi` 更像 streaming；FFT + pointwise multiply + projector chain 构成双路径；对 resident row reuse 很敏感 | 当前基线是 complex FP64；可讨论 mixed precision，但不能先破坏收敛/广义路径 | **第一波 chip 主热点**。优先作为 accelerator 主核来刻画与筛选 | `tile_npw / tile_nkb / tile_m`、FFT companion、dataflow、resident policy、buffer hierarchy、offload scope、partition strategy |
| `s_psi` | `si8_pbe_uspp` 中 `s_psi = 0.06 s / 53 calls`；在 generalized/USPP case 中持续出现；`NC` case 可退化为弱路径甚至消失 | 与 `h_psi` 同级的 `npw / nkb / m`；无 FFT；中间 `bec / d_S` 仅 `36 KiB` 量级；`m=16` 时约 `110.080M` real-flops | **更规则的 projector-dense kernel**：`m=16~32` 时 AI 约 `11~13`；`m=1~4` 时 AI 约 `3~5`；整体比 `h_psi` 更接近 pure projector chain | `beta` 常驻重用强；`psi` 流式；无 FFT，数据流比 `h_psi` 更规整；对 generalized overlap contract 关键 | 当前应保持 FP64 / generalized contract 一致；可在后续评估局部 mixed precision | **第一波 chip 主热点**，应与 `h_psi` 作为成对候选一起评估，而不是后补 | `tile_npw / tile_nkb / tile_m`、weight-stationary、buffer banking、resident context、是否与 `h_psi` 保持 fused sweep |
| `build H_sub / S_sub` | 真实 QE 中不是顶层主热点；在当前 system model 中对应 `Cluster B`；现有 operator plan 里第一次 expand 的输出矩阵总共仅 `32 KiB`，但已有 `3,015,680` complex MAC 量级 | 典型 `n_prev=16`, `p=16`, `n=32`；输出 `H_sub + S_sub` 约 `32 KiB` | **小输出、计算较密集**；更像 compute-dense companion，而不是 bandwidth 大户 | resident basis 与 `HP / SP` 投影后形成 reduced blocks，依赖前序 `h_psi / s_psi` 完成；有 reduction / closure / accumulation tree 结构 | 建议维持 complex FP64；这是 correctness-sensitive reduced-space boundary | **第一波 companion candidate**，适合与 operator sweep 紧邻放在 chip/FPGA 边界，不建议单独作为唯一主故事 | reduction topology、accumulator tree、small-matrix assembly policy、overlap/barrier、partition strategy |
| `cdiaghg / rdiaghg` | 真实 QE `si8_pbe_uspp` 中仅约 `0.01 s / 52 calls`，约占 `cegterg` 的 `2%`；远小于 `h_psi`；当前 system model 虽有 `Cluster C` proxy，但原始软件热点地位仍低于 operator path | 峰值 `n=32` 时输入矩阵总共约 `32 KiB`，输出 `C + Lambda` 约 `8.12 KiB` | **小矩阵 compute kernel**，但系统级 leverage 低；不是当前主吞吐瓶颈 | 强依赖 `H_sub / S_sub` 完整性；工作集小，数据移动小；更像 companion solver / fallback point | **必须维持 FP64 与数值稳定性**；不宜把第一波探索建立在激进降精度上 | **第一波保持在 CPU / soft-core companion 更合理**；后续可保留 hardware-first proxy 做系统 DSE，但不应先把它当成唯一 accelerator 核心 | `diag_policy`、device-diag max dim、host fallback policy、companion bandwidth / handoff latency |
| `refresh / residual -> P_next` | 真实 QE 中是 band-solver 迭代闭环的一部分；当前 system model 显式给成 `Cluster D`，时间占比约 `5%` | `Psi[2945×32]` 约 `1.44 MiB`；`X/HX/SX` 各约 `736.25 KiB`；伴随 residual / orthogonalization / precondition 路径 | **中等计算 + 中等数据移动**；不是顶层主热点，但直接影响下一轮 basis 扩展节奏 | 依赖 reduced coefficient 回代；与 resident episode context、search-vector 生命周期、orthogonalization 强相关 | 建议保持 FP64 基线；数值路径比纯 GEMM 更脆弱 | **第一波 companion candidate**。应与 `h_psi/s_psi` 和 reduced build 一起定义边界，但不是第一优先独立 offload 对象 | residual policy、refresh granularity、resident context budget、spill / reuse policy、partition strategy |
| `rho -> Veff` | 顶层 share 一般明显低于 `c_bands`；例如 `si8_pbe_uspp` 中 `v_of_rho = 6.4%`；system model 当前仍作为 shell-visible stage 保留 | 以 real-space grid 为主；`Veff(r)` 约 `364.50 KiB`；含 FFT / Hartree / XC / potential assemble | **更偏 memory/grid-oriented + control-integrated**；不是当前 band-solver accelerator 主核 | 与 density history、mixing、outer SCF control 绑定强；并不天然形成第一波独立 chip primitive | 当前不建议脱离 host-side correctness path 做激进改写 | **第一波保留在 host / FPGA runtime 侧**，不作为 chip 主核 | host/device boundary、grid transfer visibility、loop-carried residency、control/data overlap |
| `psi -> rho_out` | 顶层一般对应 `sum_band` share，典型在 `8% ~ 23%`，低于 `c_bands` 但不可忽略 | `psi(r)` 可达 `11.39 MiB`；最终 `rho_out(r)` `364.50 KiB` | **明显带有数据归约/带宽特征**；不是最值得先做专用加速的热点 | 多 band reduction、grid-domain accumulation；与后续 mixing/SCF outer loop 耦合 | 建议维持 FP64 correctness 基线 | **第一波不作为独立 chip 主核**；更适合保留为 host-visible FPGA runtime stage | reduction policy、grid buffering、band batching、shell-level accounting boundary |
| `mix_rho / convergence gate` | 顶层 share 很小（例如 `0% ~ 1.2%` 量级），属于控制与 history 路径 | grid 级对象但算子简单 | **控制/历史状态主导，不是计算热点** | 强依赖 SCF 历史与 convergence policy；几乎不构成 accelerator 算力优势来源 | 应保持原始数值/收敛语义 | **保留在 host** | 不作为当前 accelerator DSE 主轴 |

---

## 4. 第一波 accelerator 候选冻结

基于上表，当前系统 DSE 的 **第一波 accelerator candidate kernels** 冻结为：

### 4.1 Primary hot kernels

1. `h_psi`
2. `s_psi`

这两个 kernel 进入第一波的原因不是“它们数学上更优雅”，而是因为：

- 在真实 `QE` 路径里它们的**系统时间贡献最大**；
- 它们具备稳定的 tensor 形状和接口；
- `beta` 常驻 / `psi` 流式 / row reuse 这些特征，使它们天然适合产生可调的 hardware knobs；
- 它们的 `m` 维动态范围又足够大，能直接驱动后续 tile / resident / policy DSE。

### 4.2 Companion kernels

3. `build H_sub / S_sub`
4. `refresh / residual -> P_next`

这两个 kernel 不应主导第一波“算力宣传”，但必须进入系统对象，因为：

- 它们决定 `operator -> reduced-space -> next basis` 的闭环是否完整；
- 后续 `partition_strategy` 与 `resident_policy` 很大程度上取决于这两段边界怎么收；
- 只看孤立 `h_psi / s_psi` 会低估 reduced-space handoff 和 context lifecycle 的系统代价。

### 4.3 First-wave keep-on-host / companion

5. `cdiaghg / rdiaghg`
6. `rho -> Veff`
7. `psi -> rho_out`
8. `mix_rho / convergence`

这并不表示这些路径永远不值得加速，而是表示：

- 在当前证据下，它们不是 **Step-1** 最应优先抓住的 accelerator 主矛盾；
- 其中 `cdiaghg` 更适合作为 CPU/soft-core companion / fallback；
- 其余三者更适合继续放在 host-visible shell runtime 边界上。

---

## 5. 对 Step-2 / Step-3 DSE 的直接含义

### 5.1 先开的 system-level knobs

基于 `qe_ic_system_level_dse_axes_v0.md`，当前最应该优先打开的是：

1. `offload_scope`
2. `resident_policy`
3. `partition_strategy`
4. `diag_policy`
5. `FFTUnit / ReductionUnit / DiagUnit` 是否独立存在

理由是：

- 当前主矛盾还在系统对象与数据流边界，而不是细粒度 PE 数；
- `h_psi/s_psi` 是否与 reduced build / refresh 紧耦合，会先改变系统最优点；
- 在这一步之前，先不要把 cluster 数量、memory ports、micro-scheduling 当成主轴。

### 5.2 先开的 kernel-mapping knobs

对 `h_psi / s_psi` 的 projector/GEMM 主链，优先级最高的映射参数是：

1. `tile_npw`
2. `tile_nkb`
3. `tile_m`
4. loop ordering
5. dataflow (`weight_stationary / output_stationary / row_stationary`)
6. `L1 / L2 / L3` buffer hierarchy

当前已有 `docs/benchmarks/archive/reports/qe_step2_kernel_mapping_dse_report.md` 给出的局部结论可直接作为默认先验：

- `weight-stationary` 优先；
- `beta resident, psi streaming` 优先；
- 小 tile 往往 utilization 更高，但 AI 更低；
- 大 tile 往往 AI 更高，但更吃 buffer 和数据流设计。

### 5.3 Block-size-aware search rule

当前 characterization 已经足够支持一个很实用的初始规则：

- `m < 8`：默认更偏 host / GPU / explain-only lane
- `8 <= m <= 16`：作为 first-wave offload 候选区间
- `m > 16`：作为 accelerator main-path 候选区间

这条规则不是最终真理，但它适合作为 Step-2/3 的第一层剪枝启发式。

---

## 6. 当前 Step-1 artifact 的作用边界

这份 matrix 的作用是：

- 给后续 `host / FPGA / chip` 划分提供 **kernel-level 输入**；
- 给 system-level axes 与 kernel mapping axes 提供 **优先级排序**；
- 作为 fast-layer proxy / next-stage DSE 的**前端解释层**。

它**不直接宣称**：

- 某个 `family` 已经最终胜出；
- 某个 kernel 一定应该做成 CIM 或 systolic RTL；
- 当前 proxy/runtime 结果已经足以形成 thesis-grade 结论。

这些仍要留给后续：

- Step-2 partition artifact；
- Step-3 parameterization artifact；
- Step-4/5 的 DSE runner；
- accurate-layer / closure / adjudicator。

---

## 7. 一句话收口

当前 Step-1 的正式输入可以收成一句话：

> 这个系统的第一波 DSE 不应从 `cdiaghg` 或完整 DFT 外围开始，而应从 **`c_bands` 内部最稳定、最重、最具复用特征的 `h_psi / s_psi` operator path** 开始，再把 `build H_sub/S_sub` 与 `refresh/residual` 作为 companion path 一起纳入系统对象。
