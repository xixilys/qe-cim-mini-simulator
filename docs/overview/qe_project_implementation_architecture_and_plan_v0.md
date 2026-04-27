# QE/DFT 加速项目整体实现架构与实施计划 v0

## 0. 文档定位

本文是当前仓库的**项目级实现架构与实施计划文档**。它的目标是在继续开发前，把整个项目的系统对象、代码模型、算法验证、DSE/evidence 流水线、QE 集成边界、验证 gate 和后续里程碑统一收口成一份可执行规划。

本文不是 DSE user manual，也不是单个模块的设计规格。DSE 的使用方式见 `docs/benchmarks/qe_dse_framework_user_manual_v0.md`；系统级设计规范仍以 `docs/architecture/system_design_master_spec_v0.md` 为最高系统入口；对外 claim 权限仍以 `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` 和 adjudicator memo 为准。

本文回答的是：

1. 整个项目最终要实现什么系统；
2. 现在已有代码和文档分别处在什么成熟度；
3. 哪些 workstream 必须先冻结，哪些可以并行推进；
4. 每个阶段的输入、输出、验证命令和 acceptance gate 是什么；
5. 哪些结论当前可以作为规划目标，哪些不能作为已证明事实；
6. 后续开发应该按什么顺序推进，避免一点点补丁式扩张。

一句话定位：

```text
本项目要实现的是一个 QE-facing Host + FPGA/runtime + Chip 的 DFT 混合加速系统，
以真实 QE c_bands / subspace diagonalization 主路径为第一闭环，
以 standalone 数值验证、timed-functional 系统模型和 DSE/adjudicator evidence pipeline 共同支撑后续实现。
```

---

## 1. 权威层级与规划边界

### 1.1 本文的权威位置

本文是 planning / coordination document。它可以规定后续开发如何排序、如何验收、如何组织 evidence，但不替代以下文档：

| 上游文档 | 权威内容 |
| --- | --- |
| `docs/architecture/system_design_master_spec_v0.md` | 系统对象、三层结构、descriptor/replay/LCW、对象生命周期、模块责任。 |
| `docs/architecture/host_managed_full_scf_architecture_v1_20260409.md` | 当前 runnable model 的 Host-managed full-SCF shell 合同。 |
| `docs/architecture/qe_system_optimized_delta_20260413.md` | optimized system-level redesign 的最新口径。 |
| `model/qe_band_solver_model/README.md` | 当前 runnable model truth。 |
| `model/ozaki_subspace_model/AGENTS.md` | standalone algorithm validation stack 的 build/run/validation 合同。 |
| `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` | 唯一 public decision authority。 |

本文可以引用这些结论，但不能擅自改变它们。

### 1.2 Claim boundary

当前规划必须遵守以下规则：

- 当前 SystemC / TLM-style 模型是 timed-functional / proxy-level evidence，不是 board-equivalent 或 RTL-equivalent 证据；
- standalone Ozaki / generalized subspace evaluator 是算法和数值验证路径，不是系统级性能 claim；
- DSE runner、projection review、stage-main recommendation 都是 evidence input，不是 public authority；
- `F4/F5/custom` 当前仍主要是 projection/scaffold，除非未来有明确 native executor evidence；
- gem5/SystemC co-sim 当前只能作为 future / reserved backend 规划项，不能写成已完成能力；
- 任何 `CPU + FPGA beats CPU + GPU`、whole-node power、board-grounded causality、thesis-grade final family claim，都必须等 Stage-B closure 和 adjudicator permission。

### 1.3 本文不做的事

本文不直接：

- 写 RTL；
- 改 SystemC 代码；
- 改 QE 源码；
- 重新跑 DSE；
- 重写 benchmark contract；
- 宣布最终 family winner；
- 把当前 planning target 当成已验证结果。

---

## 2. 当前项目状态快照

### 2.1 仓库的四个主系统面

当前仓库可以按四个主系统面理解：

| 系统面 | 路径 | 当前职责 | 成熟度 |
| --- | --- | --- | --- |
| 算法/数值验证 | `model/ozaki_subspace_model/` | Ozaki-II complex FP64 GEMM、generalized Hermitian eigensolver、iterative subspace engine。 | 自包含 evaluator 已成型，算法冻结仍需继续收口。 |
| 系统级 runnable model | `model/qe_band_solver_model/` | Host-managed full-SCF shell，Host → FPGA/runtime → Chip timed-functional proxy。 | 可构建可运行，仍是 proxy-level；非 numerically faithful DFT solver。 |
| DSE / benchmark / evidence | `docs/benchmarks/` | architecture-family sweep、next-stage phase、gold gate、baseline readiness、closure、adjudicator。 | 工具链和合同已较完整，claim 权限仍由 adjudicator 控制。 |
| QE instrumentation workspace | `soft/qe-7.5/` | 工作区 QE 副本，用于 subspace trace / dump / instrumentation。 | 只能改 workspace copy，不能改外部 QE install。 |

### 2.2 当前已比较稳定的结论

当前稳定结论来自 `project_development_timeline.md`、`agent_handoff_20260312.md`、master spec 和 optimized delta：

- 项目长期目标是面向 `QE / PySCF / VASP / CP2K` 这类 DFT 软件的科学计算加速系统，而不是孤立 numerical IP；
- 当前第一主线聚焦 `QE`，尤其是 `c_bands` / subspace diagonalization / Davidson 子空间路径；
- generalized Hermitian 是主路径，`S_sub` 不能被忽略；
- complex FP64 GEMM、Hermitian/generalized Hermitian reduced problem、residual/refresh 共同构成核心数值闭环；
- 系统对象已经收敛为 `Host + FPGA/runtime + Chip`；
- 当前 runnable model 已经前移到 `HostSCF -> FPGAOrchestrator -> ChipTop` 的 host-managed full-SCF shell；
- public control contract 已从 replay/body 口径前移到五个 request/completion objects；
- replay/body/LCW 保留为内部 lowering，而不是 phase-1 public API；
- `F1/F2` 是更成熟的 phase-1 first-class candidate，`F3` 更偏 conditional/exploratory，`F4/F5/custom` 仍以 projection/scaffold 为主。

### 2.3 当前主要缺口

当前缺口不是“缺一个脚本”，而是几条实现链还没有统一冻结：

1. 算法验证链和 SystemC 模型之间的接口尚未完全冻结；
2. generalized eigensolver / `S_sub` 处理的系统级集成仍需明确；
3. SystemC model 中哪些模块保持 proxy，哪些需要更精确建模，还需要阶段化决策；
4. fast-layer metric closure、accurate-layer coverage、generalization coverage 与 release/adjudicator 的关系需要作为 roadmap gate 管理；
5. board / whole-node / GPU baseline closure 尚未成为 thesis-grade claim surface。

---

## 3. 项目目标架构

### 3.1 顶层系统对象

目标系统固定为三层：

```text
Host CPU / software runtime
    -> Thin device runtime / FPGA firmware bridge
        -> Hardware datapath / Chip
```

职责划分：

| 层级 | 职责 | 不负责 |
| --- | --- | --- |
| Host CPU / software runtime | outer SCF、`rho -> Veff`、`mix_rho`、全局收敛、batch 组织、resident/diag policy 生成、host diag fallback。 | 逐条 LCW 下发、cluster/FIFO 级管理、片上 resident window 生命周期。 |
| Thin device runtime / FPGA bridge | resident preload/reuse、Host DRAM ↔ Device HBM DMA、request→episode mapping、device launch、diag fallback bridge、completion/perf summary。 | 完整操作系统、QE 控制平面副本、纯 RTL 状态机。 |
| Hardware datapath / Chip | `h_psi/s_psi`、`H_sub/S_sub` build、hardware-first diag proxy、refresh/residual、on-chip buffer/FIFO/double-buffer。 | 全局 `rho/Veff`、全局 SCF history、所有 outer SCF phase。 |

### 3.2 QE shell 主闭环

第一实现闭环应以 `QE / CBANDS_DIAG` 为锚点：

```text
Host:
  rho -> Veff
  while bands not converged:
    build ScfIterationRequest
    submit resident/batch/diag policy
    wait CompletionSummary
    consume updated wave/update objects
  psi -> rho_out
  mix_rho / convergence

Device runtime:
  resident preload / reuse
  batch DMA
  launch device episode
  optional host diag export/import
  completion/perf summary

Chip datapath:
  Cluster A: h_psi / s_psi
  Cluster B: H_sub / S_sub build
  Cluster C: hardware-first diag proxy with fallback boundary
  Cluster D: refresh / residual / P_next
```

### 3.3 Public control objects

Phase-1 public control contract 固定为五个对象：

| Object | Owner / direction | Role |
| --- | --- | --- |
| `ResidentSetDesc` | `HostSCF -> FPGAOrchestrator` | 描述 device 侧应预加载和复用的 resident objects。 |
| `BandBatchDesc` | `HostSCF -> FPGAOrchestrator` | 描述当前 active wave/band/panel batch 与 DMA 规模。 |
| `DiagPolicy` | `HostSCF -> FPGAOrchestrator / Cluster C` | 描述 device-vs-host diag 边界、阈值与 fallback 规则。 |
| `ScfIterationRequest` | `HostSCF -> FPGAOrchestrator` | Host 到 device runtime 的主请求对象。 |
| `CompletionSummary` | `FPGAOrchestrator -> HostSCF` | 返回执行状态、fallback、resident/spill、DMA、perf summary。 |

Internal lowering 包括：

```text
EpisodeDescriptor
EpisodeControllerState
EpisodeResult
```

这些属于内部实现层，不应作为 phase-1 的上层 planning API。

### 3.4 Chip 内部实现形态

当前 chip 内部按 cluster-first timed-functional path 组织：

| Cluster / domain | Role | Planning status |
| --- | --- | --- |
| Cluster A | `h_psi + s_psi` operator sweep / projector-apply 主链。 | 第一优先硬件主路径。 |
| Cluster B | `H_sub / S_sub` reduced build。 | 与 Cluster A 强耦合，需保持 generalized path。 |
| Cluster C | hardware-first generalized diag proxy。 | 必须保留 host fallback，不能把完全硬化作为 v1 成功标准。 |
| Cluster D | refresh / residual / `P_next`。 | 是形成 QE shell closure 的必要路径。 |
| Near-memory / resident domain | resident context、row-block、near-SRAM support、DMA locality。 | 决定 family comparison 的真实系统意义。 |
| LCW / scheduler | 内部多引擎数据流编排。 | 当前保留为内部 lowering，不直接暴露给 Host。 |

---

## 4. 代码与文档实现面

### 4.1 Algorithm validation stack

路径：`model/ozaki_subspace_model/`

职责：在进入 system model 或硬件实现前，先冻结数值行为。

主要 executable：

| Executable | Role | Minimal command |
| --- | --- | --- |
| `bin/complex_ozaki_eval` | complex FP64 GEMM / Ozaki-II / CRT / Karatsuba validation。 | `make -C model/ozaki_subspace_model bin/complex_ozaki_eval && ./model/ozaki_subspace_model/bin/complex_ozaki_eval` |
| `bin/generalized_subspace_eval` | generalized Hermitian eigensolver validation。 | `make -C model/ozaki_subspace_model bin/generalized_subspace_eval && ./model/ozaki_subspace_model/bin/generalized_subspace_eval` |
| `bin/iterative_subspace_eval` | iterative refinement / reduced-space flow。 | `make -C model/ozaki_subspace_model bin/iterative_subspace_eval && ./model/ozaki_subspace_model/bin/iterative_subspace_eval` |
| `bin/iterative_tile_gemm_eval` | tiled GEMM / resident-tile validation。 | `make -C model/ozaki_subspace_model bin/iterative_tile_gemm_eval && ./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval` |
| `bin/iterative_qe_regression_eval` | QE dump regression。 | `make -C model/ozaki_subspace_model bin/iterative_qe_regression_eval && ./model/ozaki_subspace_model/bin/iterative_qe_regression_eval` |

Planning concern：

- 哪些 evaluator 结果成为 SystemC integration 的 numerical contract；
- 哪些 remain standalone reference；
- generalized eigensolver 与 `S_sub` 处理必须保留；
- 不能把 algorithm evaluator 的性能数字直接当系统性能。

### 4.2 System-level runnable model

路径：`model/qe_band_solver_model/`

职责：表达 `HostSCF -> FPGAOrchestrator -> ChipTop -> ClusterGraphExecutor` 的 timed-functional system flow。

构建：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

运行：

```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

核心模块：

| File / group | Role |
| --- | --- |
| `sc_main.cpp` | executable entry，runtime env/config，candidate JSON export。 |
| `src/dft_hybrid_system.*` | top-level Host + device + chip system object。 |
| `src/host_scf.*` | Host-side SCF control/runtime。 |
| `src/fpga_orchestrator.*` | thin device runtime, DMA, resident, fallback, completion。 |
| `src/interconnect.*` | control / DMA / completion transaction accounting。 |
| `src/chip_top.*` | chip execution facade。 |
| `src/clusters/*` | Episode controller 与 Cluster A/B/C/D。 |
| `src/onchip/*` | CIM / near-SRAM / reduction / companion domains。 |
| `legacy/` | archived replay/body compatibility subtree。 |

Planning concern：

- 保持 public five-object contract；
- 将 replay/body/LCW 限定为内部 lowering；
- 定义 proxy formula 升级顺序；
- 定义 JSON/result/export 与 DSE schema 的契合点。

### 4.3 DSE / benchmark / adjudicator stack

路径：`docs/benchmarks/`

职责：组织 evidence，而非直接做实现或 public decision。

主入口：

| Script | Role |
| --- | --- |
| `run_systemc_architecture_family_dse_sweep.py` | Stage-A architecture-family DSE sweep。 |
| `run_unified_dse_v0.py` | Unified DSE v0 的 additive bounded wrapper；详细架构和实施计划见 `docs/benchmarks/qe_unified_dse_framework_v0.md`，其输出只作为 Stage-A evidence-only、adjudicator-ready 材料。 |
| `run_qe_next_stage_dse_phase.py` | fast/accurate/generalization/release phase runner。 |
| `run_qe_system_design_adjudicator.py` | adjudicator memo generator。 |
| `check_qe_next_stage_dse_simulator_contracts.py` | DSE simulator contract validator。 |
| `check_qe_next_stage_release_bundle.py` | release bundle validator。 |
| `assess_qe_cpu_gpu_baseline_readiness.py` | CPU/GPU baseline readiness assessment。 |
| `run_qe_phase1_closure_pipeline.py` | phase-1 evidence closure pipeline。 |

Planning concern：

- DSE 只负责 rank/screen/explain/nominate；
- Unified DSE v0 是 bounded implementation architecture / plan，不改变 adjudicator authority，也不替代当前 Stage-A family sweep orchestrator；
- release-ready 不等于 thesis-ready；
- baseline/fairness/power/board closure 是 Stage-B gate；
- adjudicator 是唯一 public decision authority。

### 4.4 QE instrumentation workspace

路径：`soft/qe-7.5/`

职责：真实 QE workspace copy，用于 trace、dump、instrumentation 和 baseline extraction。

硬约束：

```text
Do not modify /Users/xixilys/project/qe-7.5.
Only touch soft/qe-7.5/ when QE changes are explicitly required.
```

重建 workspace QE copy 的常用命令：

```bash
cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4
```

trace summary：

```bash
python3 docs/benchmarks/summarize_qe_subspace_trace.py /abs/path/qe_subspace_trace.csv
```

Planning concern：

- instrumentation 必须 narrow/stable；
- 真实 QE 样本是 workload truth，不应被 synthetic-only evaluator 替代；
- QE trace/dump 与 algorithm evaluator 的 case identity 必须可追溯。

---

## 5. 实施 workstreams

后续开发按六个 workstream 管理，而不是按零散脚本推进。

### WS-A: Workload and QE evidence

目标：保持真实 QE workload 作为系统设计的源头。

输入：

- `docs/overview/qe_subspace_sampling.md`
- `soft/qe-7.5/`
- existing trace/dump artifacts

输出：

- 可复现 QE trace / dump case set；
- workload signature matrix；
- generalized vs standard Hermitian coverage；
- case identity 与 evaluator input 的映射。

Acceptance gate：

- 至少覆盖当前稳定 case families；
- 每个 case 能追溯到 QE input / dump / trace；
- `S_sub` 不被默认忽略；
- trace summary command 可复现。

### WS-B: Algorithm validation and numerical contracts

目标：冻结进入 system model 的数值行为。

输入：

- QE dumps / synthetic stress cases；
- `model/ozaki_subspace_model/` evaluators。

输出：

- complex Ozaki FP64 GEMM validation；
- generalized subspace validation；
- iterative subspace / tile GEMM validation；
- regression suite 和 acceptance tolerances。

Acceptance gate：

- `complex_ozaki_eval` pass；
- `generalized_subspace_eval` pass；
- `iterative_subspace_eval` / `iterative_tile_gemm_eval` pass for configured cases；
- regression case 记录 executable、env vars、case path、abs/rel error。

### WS-C: Host-managed SystemC/timed-functional model

目标：把 QE shell closure 做成稳定 runnable system object。

输入：

- master spec；
- host-managed full-SCF architecture；
- optimized delta；
- algorithm contracts。

输出：

- stable public five-object API；
- stable internal Episode/Cluster execution path；
- candidate JSON export；
- run-level accounting for control/DMA/completion/resident/spill/fallback。

Acceptance gate：

- CMake build pass；
- default run pass；
- candidate JSON export pass；
- F1/F2/F3 family policy changes runtime/report behavior；
- `diag` fallback contract preserved。

### WS-D: DSE and evidence management

目标：用统一 schema 和 fidelity ladder 组织架构候选与证据。

输入：

- component catalog；
- graph seed；
- architecture templates；
- SystemC candidate JSON；
- gold/tolerance schemas。

输出：

- Stage-A DSE bundle；
- fast-layer / accurate-layer / coverage bundles；
- release artifact manifest；
- adjudicator intake artifacts。

Acceptance gate：

- `check_qe_next_stage_dse_simulator_contracts.py` pass；
- release bundle validator pass for generated package；
- `candidate_family` / `runtime_projection_family` separation preserved；
- `projection_only` cannot become native support accidentally。

### WS-E: Baseline, fairness, board, and closure

目标：把 current proxy evidence 逐步推进到 Stage-B claim prerequisites。

输入：

- CPU/GPU baseline run manifests；
- board/observability bundle；
- closure contracts；
- fairness/power/rewrite contracts。

输出：

- CPU/GPU baseline readiness report；
- phase-1 evidence closure report；
- board observability/calibration evidence；
- adjudicator-ready claim-permission matrix。

Acceptance gate：

- workload admissibility；
- same-correctness / same-tolerance；
- fairness/power boundary satisfied；
- measured evidence does not conflict with proxy evidence；
- adjudicator memo explicitly unlocks any stronger claim。

### WS-F: Documentation, release, and adjudication

目标：让项目状态、规划、结果和 claim 口径稳定可交付。

输入：

- this planning document；
- master spec；
- DSE user manual；
- release artifacts；
- timeline / handoff。

输出：

- updated docs index；
- project timeline updates；
- release memo；
- adjudicator memo；
- advisor-facing report / one-pager。

Acceptance gate：

- 文档中 claim language 与 adjudicator contract 一致；
- 新阶段性文档最终折叠回 `project_development_timeline.md` 或被明确索引；
- 不产生互相冲突的 authority surface。

---

## 6. 分阶段实施路线

### Phase 0: Planning freeze

目标：冻结整体实现架构和后续工作分解。

主要任务：

1. 建立本文档作为 project-level plan；
2. 在 `docs/README.md` 中索引；
3. 明确 DSE user manual 与 implementation plan 的区别；
4. 明确后续 workstreams 和 validation gates。

完成条件：

- 本文档存在并通过 reference check；
- docs navigation 已更新；
- 无代码实现变更混入 Phase 0。

### Phase 1: Algorithm contract freeze

目标：把 standalone algorithm validation 转成可被 SystemC integration 引用的 contract。

主要任务：

1. 运行并记录 `complex_ozaki_eval`；
2. 运行并记录 `generalized_subspace_eval`；
3. 运行并记录 `iterative_subspace_eval` / `iterative_tile_gemm_eval`；
4. 明确哪些 algorithm paths 进入 system model，哪些保留为 reference；
5. 为 generalized path 冻结 tolerance、matrix layout、case identity。

验证命令：

```bash
make -C model/ozaki_subspace_model bin/complex_ozaki_eval && ./model/ozaki_subspace_model/bin/complex_ozaki_eval
make -C model/ozaki_subspace_model bin/generalized_subspace_eval && ./model/ozaki_subspace_model/bin/generalized_subspace_eval
make -C model/ozaki_subspace_model bin/iterative_subspace_eval && ./model/ozaki_subspace_model/bin/iterative_subspace_eval
make -C model/ozaki_subspace_model bin/iterative_tile_gemm_eval && ./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval
```

Gate：

- 数值误差和残差在文档化 tolerance 内；
- `S_sub` path 被保留；
- 失败 case 被记录而不是隐藏。

### Phase 2: Runnable model public API stabilization

目标：稳定 host-managed full-SCF shell 的 public objects 和 runtime accounting。

主要任务：

1. 审查 `ResidentSetDesc / BandBatchDesc / DiagPolicy / ScfIterationRequest / CompletionSummary` 字段；
2. 确认 `EpisodeDescriptor / EpisodeResult / LCW` 仍为 internal lowering；
3. 确认 `diag` fallback 条件覆盖 dimension、condition、resident fit、crossover losing；
4. 确认 family policy 改变 request/runtime/report 行为。

验证命令：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
./model/qe_band_solver_model/build/qe_band_solver_model
```

Gate：

- default run pass；
- candidate JSON export 可生成；
- run report 包含 control/DMA/completion/resident/spill/fallback accounting；
- Host / device runtime / chip 边界不回退成 cluster-first public API。

### Phase 3: DSE metric closure and equal-candidate evidence

目标：让 Stage-A / next-stage DSE 成为稳定 evidence manager。

主要任务：

1. 检查 fast-layer core metrics 是否完整；
2. 保持 equal-candidate semantics；
3. 防止 projection-only 误升级；
4. 确认 release artifact chain ready；
5. 将 DSE outputs 送入 adjudicator intake。

验证命令：

```bash
python3 docs/benchmarks/check_qe_next_stage_dse_simulator_contracts.py
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_sweep_results
python3 docs/benchmarks/run_qe_next_stage_dse_phase.py \
  --output-dir tmp/qe_next_stage_release \
  --execute-model
python3 docs/benchmarks/check_qe_next_stage_release_bundle.py \
  --summary tmp/qe_next_stage_release/qe_next_stage_dse_phase_summary.json
```

Gate：

- contract validator pass；
- release bundle validator pass；
- `reject/explain-only/promotion-eligible` state machine respected；
- no final public family winner without adjudicator。

### Phase 4: QE trace and gold correctness expansion

目标：把真实 QE evidence 与 algorithm/system validation 连接得更稳。

主要任务：

1. 复核 workspace QE trace hooks；
2. 扩充/整理 canonical case set；
3. 运行 QE gold gate；
4. 让 algorithm evaluator 和 SystemC candidate JSON 共享 case identity。

验证命令：

```bash
cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4
python3 docs/benchmarks/summarize_qe_subspace_trace.py /abs/path/qe_subspace_trace.csv
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --gold-required-only \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F1 F2 F3 \
  --canonical-only \
  --execute-model \
  --auto-match-baseline-iters \
  --fail-on-gold-mismatch \
  --output-dir tmp/qe_gold_lane
```

Gate：

- QE workspace build pass；
- trace summary pass；
- selected gold-required rows pass；
- case identity 可从 QE input/trace/dump 追溯到 candidate artifact。

### Phase 5: Baseline, board, and Stage-B readiness

目标：为更强论文/汇报 claim 准备 closure evidence。

主要任务：

1. 按 runbook 获取 CPU/GPU baseline；
2. 初始化/验证 board observability bundle；
3. 跑 phase-1 closure pipeline；
4. 处理 proxy evidence 与 measured evidence 的冲突。

验证命令：

```bash
python3 docs/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py \
  --baseline-dir tmp/cpu_gpu_baselines \
  --output tmp/baseline_readiness.json
python3 docs/benchmarks/run_qe_phase1_closure_pipeline.py \
  --output-dir tmp/closure_results
```

Gate：

- baseline readiness 不再只是 `reference_only`；
- workload/fairness/power/rewrite/observability contracts 均满足；
- adjudicator 可明确指出哪些 claim allowed / guarded / forbidden。

### Phase 6: Implementation hardening / future backend expansion

目标：在前面证据闭合后，再进入更重实现路线。

候选方向：

- 更精确的 Cluster A/B cycle model；
- generalized eigensolver hardware model refinement；
- Ozaki-II path 与 SystemC model 的接口化集成；
- board-facing runtime/export alignment；
- gem5/SystemC co-sim backend；
- RTL/PPA-oriented microarchitecture package。

Gate：

- 不能跳过 Phase 1-5 的 evidence closure；
- 每个 future backend 必须先定义 evidence tuple 和 claim boundary；
- 新 backend 不得覆盖已有 candidate identity semantics。

---

## 7. 当前优先级排序

后续开发建议按以下顺序推进：

1. **先冻结整体规划文档**：本文档完成并被索引。
2. **算法 contract freeze**：确保 Ozaki/generalized/iterative evaluator 的结果可作为 system integration contract。
3. **SystemC public API freeze**：五个 request/completion objects、diag fallback、resident/spill accounting 稳定。
4. **DSE metric closure**：减少 `explain-only`，提升 ranking-grade evidence，但不越权 claim。
5. **QE gold/case coverage closure**：把真实 QE case identity 与 candidate evidence 接上。
6. **baseline/board closure**：只有这一步之后才讨论更强对外 claim。
7. **更重实现**：gem5/RTL/board/PPA 等 heavy work 放在 closure 之后。

这一路径避免两个常见失败模式：

- 过早进入实现，导致 public API / numerical contract 反复变；
- 过早解读 DSE 排名，导致 claim 超出 evidence。

---

## 8. 风险与缓解策略

| 风险 | 表现 | 缓解 |
| --- | --- | --- |
| 规划再次退化成 DSE runbook | 文档只列命令，不定义系统实现路线。 | 本文以 workstream/phase/gate 组织，DSE 只作为 evidence workstream。 |
| 算法验证与系统模型脱节 | evaluator pass，但 SystemC 用了不同假设。 | Phase 1 输出 explicit numerical contract，再进入 Phase 2 integration。 |
| `diag` 过早硬化 | 把 Cluster C proxy 当作最终 eigensolver hardware。 | 保留 `DiagPolicy` 与 host fallback，硬化作为未来 backend。 |
| Projection-only 被误读 | F4/F5/custom 被写成 native support。 | 保持 `candidate_family` 与 support/evidence tuple 分离。 |
| Stage-A claim 越权 | DSE ranking 变 public winner。 | 所有对外 claim 必须经 adjudicator。 |
| QE workspace 污染 | 修改外部 QE 或不可复现 trace。 | 只改 `soft/qe-7.5/`，记录 build/run/path。 |
| 文档权威冲突 | 新文档和 master spec / README / contract 不一致。 | 本文只做 planning，系统事实回引 canonical docs。 |

---

## 9. Non-goals

以下内容不是当前规划阶段的完成标准：

- 完整 RTL 实现；
- ASIC PPA closure；
- 完整 QE/VASP/CP2K production plugin；
- 全 DFT workflow 数值 faithful simulator；
- gem5/SystemC co-sim 实测结论；
- board-grounded power claim；
- `CPU + FPGA` 对 `CPU + GPU` 的最终胜负 claim；
- `F3/F4/F5/custom` 的最终主线推荐；
- 完整自动化编译栈。

这些可以作为未来方向，但不能作为 v0 plan 的默认验收项。

---

## 10. Acceptance checklist for future work

任何后续开发任务在开始前应能回答：

- [ ] 它属于 WS-A/B/C/D/E/F 哪个 workstream？
- [ ] 它依赖哪个 canonical doc 或 contract？
- [ ] 它的输出是 code、artifact、evidence bundle、validator，还是 adjudicator memo？
- [ ] 它是否改变 public API？如果是，是否需要更新 master/host-managed docs？
- [ ] 它是否改变 numerical contract？如果是，是否需要 rerun Ozaki/subspace evaluators？
- [ ] 它是否改变 DSE schema / phase config？如果是，是否需要 contract validator？
- [ ] 它是否会影响 claim language？如果是，是否需要 adjudicator update？
- [ ] 它是否触碰 QE？如果是，是否只在 `soft/qe-7.5/` 内操作？

任何阶段完成前至少应记录：

```text
changed files
build command
input cases
output artifacts
known failures / pre-existing failures
claim boundary
```

---

## 11. 本文档后的第一批建议任务

本文完成后，下一批任务不应直接“随便开发”，而应按 gate 推进：

1. **规划校验**：确认本文档与 master spec、host-managed full-SCF doc、model README、adjudicator contract 无冲突。
2. **Algorithm freeze review**：整理 `complex_ozaki_eval`、`generalized_subspace_eval`、`iterative_*` 当前结果，形成 system-integration numerical contract。
3. **SystemC API audit**：审查五个 public objects 与 run report 是否足以支撑 Phase 2 gate。
4. **DSE metric closure audit**：列出当前 `explain-only` 的 root causes，不直接改代码。
5. **QE case identity audit**：确认 trace/dump/candidate/gold artifacts 的 join key 是否一致。
6. **Adjudicator intake audit**：确认 current release bundle 能否完整进入 adjudicator intake。

只有这些 planning/audit 任务明确后，才进入具体实现修改。

---

## 12. 一句话总结

本项目的整体实现路线应从“真实 QE workload → 数值算法验证 → host-managed timed-functional system model → DSE/evidence packaging → adjudicator claim control → baseline/board closure → 更重实现”逐步推进。

当前最重要的不是继续零散补功能，而是先把：

```text
系统对象
+ public API
+ numerical contract
+ evidence pipeline
+ validation gates
+ claim boundary
+ milestone roadmap
```

统一冻结。本文即作为该冻结点的 v0 planning artifact。
