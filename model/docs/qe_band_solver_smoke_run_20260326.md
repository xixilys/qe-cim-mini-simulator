# QE full-SCF system model smoke run

## 1. 目的

这份记录对应当前 `model/qe_band_solver_model` 的最新 smoke run。

它验证的已经不再只是一个孤立的 `QE c_bands episode subsystem`，而是一个提升后的行为级全流程闭环：

- `HostSCF -> FPGAOrchestrator -> ReplayBundleExecutor -> ChipTop -> c_bands episode -> Body04FamilyController -> OuterUpdateRuntimeDomain -> sum_band -> v_of_rho/newd -> mix_rho -> next SCF iteration`
- 并生成显式的 `ReplayBundleDescriptor / ReplayBundleCompletion`
- 以及 `Body04LoweringPlan` / `DFTRunReport` / `SCFIterationReport` / `BODY_04` stage summaries

其中：

- `Phase A` 对应 setup / seed / object bind
- `Phase B` 对应 `BODY_01-03` 的 `c_bands` episode
- `Phase C` 对应 `sum_band`
- `Phase D` 对应 `v_of_rho` / `newd`
- `Phase E` 对应 `mix_rho` / convergence gate

## 2. 构建与运行

构建命令：

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j4
```

运行命令：

```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

环境变量：

- 无

## 3. 结果

本次在默认 fallback compatibility path 下的结果为：

- Build: success
- Run: success
- Mode: structured timed-functional C++ skeleton with SystemC-compatible structure and Phase-B / BODY-04 leaf-block `L2 proxy` flow-control
- Scope: `QE` full-SCF control loop with `BODY_01-05` coverage, explicit replay-bundle dispatch, full-run summary objects, `Phase B` module-occupancy / reference-cycle reporting, and `BODY_04` stage/unit-level reference-cycle / flow-control reporting

最终状态行为：

```text
[822.0 ns] [chip_top] phase-b structural summary: level=STRUCTURAL_TIMED_FUNCTIONAL, panels=9, row_visits=18, ctrl=33, fft=45, sram=240, cim=396, solve=30, vector=21, total_ref_cycles=765, critical=CIM_PROJECT_BACKPROJECT_CHAIN
[822.0 ns] [chip_top] phase-b flow-control summary: level=L2_PROXY_FLOW_CONTROL_WITH_LEAF_CONTRACTS, bundle_accept=1, bundle_complete=1, credit_limit=2, issue_stall_ref_cycles=6, total_backpressure_ref_cycles=66, route_conflicts=60, dominant_route=ProjectConjugateSignSelector->Residue3MCore.PROJECT
[822.0 ns] [chip_top] phase-b flow stage: ReductionClosureEngine.InputAssembler: qdepth=1, accept=3, complete=3, busy_ref_cycles=12, blocked_ref_cycles=0, max_q=1, accept_cond=closure_input_fifo_not_full, busy_cond=closure_input_assemble_busy_or_output_hold, complete_cond=closure_matrix_tiles_ready, ingress_owner=ReductionClosureEngine.input_fifo, egress_owner=ReductionClosureEngine.closure_fifo, arb=CLOSURE_ENGINE_DOMAIN, domain=CLOSURE_INPUT_ASSEMBLE
[822.0 ns] [chip_top] phase-b flow stage: ReductionClosureEngine.HermitianClosureBuilder: qdepth=1, accept=3, complete=3, busy_ref_cycles=12, blocked_ref_cycles=0, max_q=1, accept_cond=closure_builder_slot_free, busy_cond=closure_builder_busy_or_output_hold, complete_cond=hermitian_reduced_matrices_ready, ingress_owner=ReductionClosureEngine.closure_fifo, egress_owner=ReductionClosureEngine.solve_frontend_fifo, arb=CLOSURE_ENGINE_DOMAIN, domain=HERMITIAN_CLOSURE_BUILD
[822.0 ns] [chip_top] phase-b flow stage: ReductionClosureEngine.SmallSolveFrontEnd: qdepth=1, accept=3, complete=3, busy_ref_cycles=6, blocked_ref_cycles=0, max_q=1, accept_cond=solve_frontend_slot_free, busy_cond=small_solve_frontend_busy_or_output_hold, complete_cond=reduced_matrix_descriptor_ready, ingress_owner=ReductionClosureEngine.solve_frontend_fifo, egress_owner=VectorDiagCompanion.solve_ingress, arb=SMALL_SOLVE_DOMAIN, domain=SMALL_SOLVE_PREP
[822.0 ns] [chip_top] phase-b flow stage: VectorDiagCompanion.RitzUpdate: qdepth=1, accept=3, complete=3, busy_ref_cycles=21, blocked_ref_cycles=0, max_q=1, accept_cond=vector_diag_slot_free, busy_cond=vector_diag_busy_or_output_hold, complete_cond=residual_refresh_packet_ready, ingress_owner=VectorDiagCompanion.solve_ingress, egress_owner=BODY_03.commit_boundary, arb=VECTOR_DIAG_DOMAIN, domain=RITZ_UPDATE
[928.0 ns] [outer_update_runtime_domain] BODY_04 stage summary => stage=BODY_04C_DENSITY_ACCUM, input=qe_wave_seed, output=qe_rho_iter_1, move_kib=288.0000, ref_cycles=12, bp_ref_cycles=0, critical_unit=DensityAccumulatorUnit.Reduce, accepted=yes, completion=SYNC, join=HARD_BARRIER
[942.0 ns] [outer_update_runtime_domain] BODY_04 stage summary => stage=BODY_04D_POTENTIAL_REFRESH, input=qe_rho_iter_1, output=qe_veff_iter_1, move_kib=196.8000, ref_cycles=14, bp_ref_cycles=0, critical_unit=PotentialFieldUnit.Build, accepted=yes, completion=SYNC, join=HARD_BARRIER
[952.0 ns] [outer_update_runtime_domain] BODY_04 stage summary => stage=BODY_04E_MIX_GATE, input=qe_rho_iter_1/qe_veff_iter_1, output=qe_rho_mixed_iter_1, move_kib=0.0000, ref_cycles=10, bp_ref_cycles=0, critical_unit=DensityMixerUnit.Mix, accepted=yes, completion=SYNC, join=HARD_BARRIER
[1427.0 ns] [outer_update_runtime_domain] Outer-update runtime bundle complete: bundle=403, phase_family=BODY_04_FAMILY, software=QE, flow=CBANDS_DIAG, domain=OuterUpdateRuntimeDomain, continue_scf=no, density=qe_rho_iter_3, potential=qe_veff_iter_3, mixed=qe_rho_mixed_iter_3, est_ns=36.0, ref_cycles=36, bp_ref_cycles=0, critical_stage=BODY_04D_POTENTIAL_REFRESH, move_kib=953.6000
[3466.0 ns] [sc_main] Full-flow report: software=QE, flow=CBANDS_DIAG, iters=3, phase_b=3, body04=3, body10=0, lcw=18, row_blocks=66, phase_b_ref_cycles=2745, phase_b_bp_ref_cycles=372, body04_ref_cycles=108, body04_bp_ref_cycles=0, total_move_kib=2238.4000, body04_move_kib=2238.4000, body10_move_kib=0.0000, reason=mix_gate_converged, final_density=qe_rho_mixed_iter_3, model_level=STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_AND_BODY04_LEAF_FLOW_CONTROL_PROXY, converged=yes
[3466.0 ns] [sc_main] Demo finished: software=QE, flow=CBANDS_DIAG, completed_episodes=3, completed_bodies=20, rho_norm=0.654900, energy=-11.526950, density=qe_rho_mixed_iter_3, converged=yes
```

## 4. 运行时观察到的闭环

从日志可以确认以下顺序已经打通：

1. `HostSCF` 执行 `BODY_05 outer_scf_control_body`
2. `HostSCF` 执行 `BODY_00 basis_seed_and_bind_body`
3. Host 将每轮 `SCF` 降成统一 `ReplayBundleDescriptor`
4. `FPGAOrchestrator` 将 replay bundle 转交 `ReplayBundleExecutor`
5. `ReplayBundleExecutor` 对 `Phase B` 调用 `ChipTop::run_replay_bundle(...)`
6. `ChipTop` 内部依次驱动：
   - `NearMemoryDomain` / `NearSRAMSupport` panel staging
   - `FFTCompanion` 频域视图更新
   - `CIMEligibleOperatorSubchain -> CIMArrayCore` operator tile 执行
   - `NearSRAMSupport` 局部 `H/S` 聚合
   - `ReductionClosureEngine` reduced-space closure
   - `VectorDiagCompanion` 产生 `et/evc + residual update`
7. Host / runtime 侧继续执行：
   - `Body10FamilyController`（仅 `CP2K/QS_OT`）
   - `Body04FamilyController` 将 `BODY_04` family 转交 `OuterUpdateRuntimeDomain`
   - `OuterUpdateRuntimeDomain` 先生成 `Body04LoweringPlan`
   - 再执行 `DensityAccumulationStage` (`sum_band`)
   - `PotentialRefreshStage` (`v_of_rho/newd`)
   - `MixingConvergenceStage` (`mix_rho` / convergence gate)
8. `BODY_04` 内部 `density/potential/mixing` 三阶段都会产生显式 stage summary，并带有 stage route / residency / latency lowering 信息
9. 三个 stage 内部又细化成 6 个支撑 block，并在日志中可见
10. 默认运行在第 `3` 轮 `SCF` iteration 后收敛并停止

## 5. 对当前主仓库的意义

这份 smoke run 说明：

- 主仓库中的 `qe_band_solver_model` 已经从单次 `c_bands` 子系统 demo，提升成一个行为级 `QE full DFT flow` 控制骨架
- 当前 `Host -> FPGA -> Chip` 的真实系统对象已经能表达 `BODY_00-05` 的主线关系
- `ReplayBundleDescriptor / ReplayBundleCompletion` 已经把 host-visible runtime bundle 合同写成显式对象
- `Body04LoweringPlan` 已经把 `BODY_04` 的 stage route / residency / estimated latency 写成显式对象
- `DensityAccumulatorUnit / DensityCommitUnit / PotentialFieldUnit / ProjectorStateUpdater / DensityMixerUnit / ConvergenceTracker` 已经在运行日志里显式可见
- `object handle`、`version`、`resident buffer tag` 已经开始跨 phase 显式流动
- 后续如果要接 `CP2K / VASP`，问题会更接近“哪些 replay body 需要扩展”，而不是“系统对象是不是要推翻重来”

## 6. 当前边界

这份验证依然没有覆盖：

- 真实 `QE` 数值 payload
- cycle-accurate 的片上时序
- 多 `k-point` / 多 batch / 更复杂调度
- `Phase C/D/E` 的真实 kernel lowering
- 最终冻结的 chip-visible body 编号 catalog

因此它的定位应理解为：

- 一个已经能运行的 `QE-connected full-SCF system model`
- 一个已经具备统一 runtime replay-bundle 接口的系统对象
- `Phase B` 已经进入带 `module occupancy`、`reference-cycle`、projector/closure leaf-block queue depth、accept/busy/complete、ingress/egress owner 和 backpressure 的结构化 timed-functional + `L2 proxy` 层
- `Phase C/D/E` 已经进入 runtime-domain 内带 six-block leaf contract 的结构化 timed-functional + `L2 proxy` 阶段
- 不是完整 `QE` 数值模拟器
- 也不是最终硬件微架构模型


## 7. 2026-03-28 追加重编译与双路径 smoke 复核

在 `BODY_04A/B/C`、`BODY_10A/B/C`、`Phase B leaf-block contract` 和 `Phase B model_level` 调整之后，又追加进行了一次完整复核。

复核命令：

```bash
cmake --build model/qe_band_solver_model/build -j4
./model/qe_band_solver_model/build/qe_band_solver_model
QEBS_SOFTWARE_FAMILY=CP2K QEBS_FLOW_FAMILY=QS_OT ./model/qe_band_solver_model/build/qe_band_solver_model
```

这次复核确认了三件事：

1. `Phase B structural` 的当前正式层级已经更新为 `STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY`；
2. `BODY_04` 的当前正式 stage 名已经稳定为 `BODY_04A_DENSITY_ACCUM / BODY_04B_POTENTIAL_REFRESH / BODY_04C_MIX_CONVERGE`；
3. `BODY_10` 的当前正式 stage 名已经稳定为 `BODY_10A_PRECOND_UPDATE / BODY_10B_ORTHO_REBIND / BODY_10C_HISTORY_COMMIT`。

### 7.1 `QE / CBANDS_DIAG` 复核结果

关键日志摘要：

```text
[3466.0 ns] [host_scf] Phase B structural => level=STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY, panels=12, row_visits=24, ctrl=39, fft=60, sram=312, cim=528, solve=30, vector=21, total_ref_cycles=990, critical=CIM_PROJECT_BACKPROJECT_CHAIN
[3466.0 ns] [host_scf] BODY_04 stage summary => stage=BODY_04A_DENSITY_ACCUM, input=qe_wave_iter_2, output=qe_rho_iter_3, move_kib=576.0000, ref_cycles=12, bp_ref_cycles=0, critical_unit=DensityAccumulatorUnit.Reduce, accepted=yes, completion=SYNC, join=HARD_BARRIER
[3466.0 ns] [host_scf] BODY_04 stage summary => stage=BODY_04B_POTENTIAL_REFRESH, input=qe_rho_iter_3, output=qe_veff_iter_3, move_kib=377.6000, ref_cycles=14, bp_ref_cycles=0, critical_unit=PotentialFieldUnit.Build, accepted=yes, completion=SYNC, join=HARD_BARRIER
[3466.0 ns] [host_scf] BODY_04 stage summary => stage=BODY_04C_MIX_CONVERGE, input=qe_rho_iter_3/qe_veff_iter_3, output=qe_rho_mixed_iter_3, move_kib=0.0000, ref_cycles=10, bp_ref_cycles=0, critical_unit=DensityMixerUnit.Mix, accepted=yes, completion=QUERYABLE, join=SOFT_JOIN
[3466.0 ns] [host_scf] Full DFT run report => software=QE, flow=CBANDS_DIAG, iters=3, phase_b=3, body04=3, body10=0, lcw=18, row_blocks=66, phase_b_ref_cycles=2745, phase_b_bp_ref_cycles=372, body10_ref_cycles=0, body10_bp_ref_cycles=0, body04_ref_cycles=108, body04_bp_ref_cycles=0, total_move_kib=2238.4000, body04_move_kib=2238.4000, body10_move_kib=0.0000, reason=mix_gate_converged, final_density=qe_rho_mixed_iter_3, model_level=STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_BODY10_BODY04_LEAF_FLOW_CONTROL_PROXY, converged=yes
```

当前解释应以这组名字为准：

- `Phase B`：带叶块流控代理的结构化 timed-functional
- `BODY_04`：已经冻结成 `A/B/C` 三段，而不再沿用旧的 `C/D/E` stage 临时命名
- 整个 full-flow 对象：`STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_BODY10_BODY04_LEAF_FLOW_CONTROL_PROXY`

### 7.2 `CP2K / QS_OT` 复核结果

关键日志摘要：

```text
[3204.0 ns] [host_scf] Phase B structural => level=STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY, panels=6, row_visits=24, ctrl=42, fft=30, sram=268, cim=528, solve=20, vector=14, total_ref_cycles=902, critical=CIM_PROJECT_BACKPROJECT_CHAIN
[3204.0 ns] [host_scf] BODY_10 stage summary => stage=BODY_10A_PRECOND_UPDATE, input=cp2k_ot_wave_body10_iter_2/cp2k_ot_residual_iter_3, output=cp2k_ot_wave_body10_candidate_iter_3, move_kib=44.3520, ref_cycles=8, bp_ref_cycles=0, critical_unit=PreconditionedUpdateVector.Apply, accepted=yes, completion=SYNC, join=HARD_BARRIER
[3204.0 ns] [host_scf] BODY_10 stage summary => stage=BODY_10B_ORTHO_REBIND, input=cp2k_ot_wave_body10_candidate_iter_3/cp2k_ot_proj_body10_iter_2, output=cp2k_ot_wave_body10_iter_3/cp2k_ot_proj_body10_iter_3, move_kib=82.3680, ref_cycles=7, bp_ref_cycles=0, critical_unit=OrthogonalizeUnit.Project, accepted=yes, completion=SYNC, join=HARD_BARRIER
[3204.0 ns] [host_scf] BODY_10 stage summary => stage=BODY_10C_HISTORY_COMMIT, input=cp2k_ot_wave_body10_iter_3/cp2k_ot_scf_hist_iter_2, output=cp2k_ot_search_hist_iter_3/cp2k_ot_ot_decision_iter_3, move_kib=0.0000, ref_cycles=3, bp_ref_cycles=0, critical_unit=HistoryIntegrator.Commit, accepted=yes, completion=QUERYABLE, join=SOFT_JOIN
[3224.0 ns] [host_scf] Full DFT run report => software=CP2K, flow=QS_OT, iters=3, phase_b=3, body04=3, body10=3, lcw=24, row_blocks=56, phase_b_ref_cycles=2150, phase_b_bp_ref_cycles=362, body10_ref_cycles=54, body10_bp_ref_cycles=0, body04_ref_cycles=120, body04_bp_ref_cycles=0, total_move_kib=2590.5600, body04_move_kib=2326.5600, body10_move_kib=264.0000, reason=max_scf_iters_reached, final_density=cp2k_ot_rho_mixed_iter_3, model_level=STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_BODY10_BODY04_LEAF_FLOW_CONTROL_PROXY, converged=no
```

这说明当前 `CP2K/QS_OT` 行为级对象已经具备：

- `BODY_10A/B/C` 的显式 stage summary；
- `BODY_10C` 的 queryable history/decision 提交边界；
- `BODY_04A/B/C` 与 `BODY_10A/B/C` 并存时的统一 full-run 汇总。

### 7.3 对本文历史内容的校正说明

因此，本文前面较早阶段记录里出现的以下旧表达，现在都应视为**历史记录**而不是当前 canonical 命名：

- `BODY_04C_DENSITY_ACCUM / BODY_04D_POTENTIAL_REFRESH / BODY_04E_MIX_GATE`
- `STRUCTURAL_TIMED_FUNCTIONAL`
- `STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_AND_BODY04_LEAF_FLOW_CONTROL_PROXY`

当前 canonical 命名应以第 `7` 节和主规格书为准。
