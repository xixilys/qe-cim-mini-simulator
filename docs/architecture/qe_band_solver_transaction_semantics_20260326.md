# 2026-03-26 SystemC `c_bands episode subsystem` 最小事务/语义输入

> 目标：给 `code-builder` 的 **SystemC v0 timed-functional demo** 一个能直接落代码、能做 smoke run 的最小事务语义。
>
> 范围严格限定为 **`QE band-solver / c_bands episode subsystem`**，不是完整 QE / SCF 全流程。

## 0. v0 总原则

- **大对象** `X(G), Hpsi, Spsi, residual`：v0 中尽量用 `object handle + shape` 表示，不要求真实数值。
- **小对象** `<beta|psi>, H_sub/S_sub, Ritz coeffs`：可直接作为轻量 payload 或小矩阵 mock。
- **低频全局对象** `rho, V_eff, vloc, convergence state`：只在 episode 边界上传 `epoch/id/summary`，不在 chip 内完整展开。
- 事务风格：**loosely timed / timed-functional**，每个 transaction 可带 `issue_ts / done_ts / counter`，先跑通语义闭环。

---

## 1. `Host -> FPGA -> Chip` episode request / response 最小字段

### 1.1 EpisodeRequest

```text
EpisodeRequest {
  episode_id           // 唯一 id
  scf_iter_id          // 属于哪一轮 SCF
  kpoint_id            // k 点
  spin_id              // 自旋通道
  nbnd                 // 目标 band 数
  npw                  // G-space 尺寸摘要
  panel_cols           // 本次 panel/block 列数
  max_local_iters      // 本地 c_bands mock 迭代上限
  generalized_overlap  // 是否需要 Spsi 路径
  need_fft             // 本 episode 是否走 FFT companion
  projector_set_id     // resident projector/beta 集 id
  vloc_slice_id        // resident/local vloc slice id
  x_init_handle        // 初始 X(G) / psi panel object handle
  potential_epoch      // V_eff / vloc 对应版本
}
```

### 1.2 EpisodeResponse

```text
EpisodeResponse {
  episode_id
  status               // OK / LOCAL_MAX_ITER / ERROR
  local_iters_done
  converged_bands      // mock: 已收敛 band 数
  final_residual_max
  used_fft             // 是否实际走了 FFT 路径
  et_handle            // 特征值结果 object handle 或小向量 id
  evc_handle           // 特征向量/子空间结果 object handle
  summary_state_id     // 指向 episode 完成摘要
}
```

---

## 2. `CIM Array Core` 的 operator transaction 最小语义

### 2.1 OperatorTxn

```text
OperatorTxn {
  episode_id
  op_kind              // PROJECT / BACKPROJECT / APPLY_H / APPLY_S
  panel_id
  in_handle            // X(G)/psi/residual/correction object handle
  resident_set_id      // projector/beta/vkb resident state id
  coeff_handle         // 对 BACKPROJECT 可选；其他可空
  out_handle           // partial <beta|psi> 或 partial Hpsi/Spsi object handle
}
```

### 2.2 语义约束

- `CIM Array Core` 只做 **resident-state apply** 主合同：
  - `PROJECT`: `psi -> <beta|psi>`
  - `BACKPROJECT`: `coeff -> |beta>*coeff`
  - `APPLY_H`: 产出 partial `Hpsi`
  - `APPLY_S`: 产出 partial `Spsi`
- v0 不要求真实线代正确；只要求：
  - 输入输出 object handle 连续；
  - 支持 panel 化；
  - 输出直接交给 `Near-SRAM Support`，不回 Host。

---

## 3. `Near-SRAM Support` 的 staging / aggregation transaction 最小语义

### 3.1 StageTxn

```text
StageTxn {
  episode_id
  panel_id
  obj_kind             // X_PANEL / HPSI_PARTIAL / SPSI_PARTIAL / RESIDUAL
  obj_handle
  action               // STAGE_IN / HOLD / FORWARD / RECYCLE
}
```

### 3.2 AggregateTxn

```text
AggregateTxn {
  episode_id
  panel_id
  partial_h_handle
  partial_s_handle
  x_handle
  agg_mode             // MERGE_PARTIAL / ASSEMBLE_FULL / FEED_REDUCED
  full_h_handle        // 输出 FullHS/Hpsi object handle
  full_s_handle        // 输出 FullHS/Spsi object handle
}
```

### 3.3 语义约束

- `Near-SRAM Support` 负责：
  - panel staging；
  - partial `Hpsi/Spsi` 聚合；
  - residual / correction 暂存；
  - 向 `Reduction/Closure` 喂入 `FullHS` 或 reduced-build 输入。
- 它是 **array-near continuity domain**：array 输出先到这里，再继续本地闭环。

---

## 4. `Reduction/Closure` 与 `Vector/Diag` 的局部闭环最小事务

### 4.1 ReductionTxn

```text
ReductionTxn {
  episode_id
  x_handle
  full_h_handle
  full_s_handle
  basis_size
  reduced_handle       // H_sub/S_sub object handle
}
```

### 4.2 DiagTxn

```text
DiagTxn {
  episode_id
  reduced_handle
  active_bands
  diag_mode            // GENERALIZED / STANDARD
  ritz_handle          // Ritz coeffs / eigenvalues object handle
}
```

### 4.3 ClosureTxn

```text
ClosureTxn {
  episode_id
  x_handle
  full_h_handle
  full_s_handle
  ritz_handle
  residual_handle
  next_x_handle
  not_converged_count
  done                 // 本地是否可结束
}
```

### 4.4 最小闭环顺序

```text
Near-SRAM assembled Hpsi/Spsi + X
  -> ReductionTxn
  -> DiagTxn
  -> ClosureTxn (生成 residual / next X object handle)
  -> 若 done=false，则 next X handle 回送到下一轮 operator path
```

---

## 5. `episode complete` 状态摘要建议字段

```text
EpisodeCompleteSummary {
  episode_id
  scf_iter_id
  kpoint_id
  status
  local_iters_done
  converged_bands
  final_basis_size
  final_residual_max
  used_fft
  x_final_handle
  et_handle
  evc_handle
  traffic_big_object_count   // 可选：大对象事务数
  traffic_small_object_count // 可选：小对象事务数
}
```

建议 `HostSCF` 在 v0 只消费：
- `status`
- `local_iters_done`
- `converged_bands`
- `final_residual_max`
- `et_handle`
- `evc_handle`

这样就足够驱动一个 mock 的：
`Host SCF iteration -> FPGA issue episode -> Chip local loop -> episode complete -> Host rho/convergence mock`。

---

## 6. 给代码实现者的一句直白建议

如果今天只做 smoke run：
- 把 **大对象** 都做成 `object handle + rows/cols + origin`；
- 把 **小对象** 做成小 struct；
- 把模块接口按上面 5 类 txn 串起来；
- 每轮 loop 打印 `episode_id / iter / object-handle flow / residual` 即可。
