# 2026-04-13 Executive Summary One-Pager Template — SystemC System-Level DSE v0

## 标题
**System-Level DSE Recommendation for QE-Oriented Soft/Hardware Co-Design**

## 0. 文档定位

这份 one-pager 不是“填空题”，而是一页式汇报规则。它的目标是：

- 在一页内说明当前是否已经形成 **recommendation-grade** 结论；
- 如果已经形成，说明推荐哪一个 family、为什么可信、下一步值不值得继续；
- 如果还没有形成，明确告诉老师：**结论暂缓的原因是什么，下一步缺什么证据**。

当前 next-stage 的 frozen scope 是：

- `QE-only`
- mainline DSE cases：`si4_pbe_uspp_small`、`graphene_pbe_uspp`
- correctness anchor：`si8_pbe_nc`
- objective stack：`time_to_convergence_s` first，`energy_to_convergence_j` second，`bytes_moved_to_convergence / fallback_ratio / spill_ratio` 作为约束/解释指标

---

## 1. 一句话结论写法

### 1.1 若已经形成 recommendation-grade 结论
> 在统一 QE gold correctness gate 下，当前推荐 `F?` 作为下一阶段主线；该 recommendation 至少应满足 `correctness_status=[status]` 与 `confidence=[level]`。如果 `recommendation_type = projection-grade`，才额外展示 `speedup_to_convergence_range=[range]` 与 `energy_to_convergence_range=[range]`。其核心价值在于：在不突破当前 correctness/tolerance contract 的前提下，提供最可辩护的 CPU/device/datapath 分工与下一阶段工程化方向。

### 1.2 若尚未形成 recommendation-grade 结论（evidence-incomplete 示例）
> 在统一 QE gold correctness gate 下，下一阶段 QE-only 双层仿真框架已经冻结，但当前 mainline fast-layer bundle 仍处于 `insufficient_evidence`：`si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 还没有产出足够完整的 ranking-grade 指标，因此本轮不提升任何 family 为 projection-grade recommendation。当前最重要的下一步不是改写 thesis story，而是补齐 fast-layer metric population、完成 shortlist closure，并用 `si8_pbe_nc` 准层继续兜底 correctness-capable validation。

---

## 2. 为什么现在要做这个系统架构筛选器

- 目标不是先冻结 RTL，而是先选出**最值得继续做**的系统架构族；
- 比较对象不是单一 kernel，而是完整 SCF-shell 下的软硬件协同系统；
- 所有结论都围绕 `time/speedup/energy to convergence`，而不是单 kernel 峰值；
- 只有在 QE gold correctness gate 不失真的情况下，system-level projection 才允许进入正式 recommendation。

---

## 3. 比较了什么

| Family | 简述 | 当前定位 |
|---|---|---|
| `F1` | Host-heavy / Single-hotpath | planned comparison lane；最终角色必须由 artifact-backed ranking/summary 决定 |
| `F2` | Balanced hybrid / Multi-operator pipeline | planned comparison lane；不得在无证据时预写成当前推荐 family |
| `F3` | Device-heavy / Full inner-loop offload | planned comparison lane；只有当当前 bundle 实际包含 `F3` 行时，才允许填写 artifact-backed 结论 |

如果当前还没有可 promoted 的 family，首页必须同时写：

- `recommended_family = none-yet`
- `recommendation_type = evidence-incomplete`
- `correctness_status = partial`
- `confidence = exploratory`（证据未闭合时的默认对外写法）

---

## 4. Recommendation card（首页必填）

| 字段 | 填写规则 |
|---|---|
| `Recommended family` | 填 `F1 / F2 / F3 / none-yet`。若 `fast_layer.shortlists[*].selection_status != ready`，必须填 `none-yet`。 |
| `recommendation_type` | 填 `evidence-incomplete / ranking-grade / projection-grade`。 |
| `correctness_status` | 只能填 rubric-backed 值：`gold_pass / gold_fail / portability_only / partial`。证据未闭合时默认写 `partial`。 |
| `confidence` | 只能填 `high / medium / exploratory`。证据未闭合时默认写 `exploratory`。 |
| `speedup_to_convergence_range` | 只在 `recommendation_type = projection-grade` 时填写；否则留空，并在 `Main caveat` 说明为什么当前不展示 range。 |
| `energy_to_convergence_range` | 同上。 |
| `Main reason` | 用一句话概括推荐依据；若 `none-yet`，改写成“当前不提升任何 family 的阻塞原因”。 |
| `Main caveat` | 写当前最关键的单一限制项，例如 `shortlist still insufficient_evidence`、`accurate-layer not yet closed`、`board observability not yet available`。 |

---

## 5. CPU / Device 分工摘要（首页必填）

### CPU 保留
- outer SCF control
- `rho -> Veff`
- convergence decision
- exception / fallback governance

### Device runtime 承担
- descriptor scheduling
- resident / spill policy execution
- DMA / completion orchestration
- policy-specific runtime bookkeeping

### Hardware datapath 放入
- 当前 family 真正固化进 datapath 的 operator set
- 必须用 `h_psi / s_psi / reduced build / refresh / residual / diag path` 这类功能名来写，而不是只写 cluster 名称

若没有 promoted family，则本节写成：
- “当前 CPU/device/datapath 分工仍以 family comparison contract 为准，尚不冻结到单一推荐 family。”

---

## 6. 正确性底线（首页必填）

- Gold reference：**QE CPU-only baseline**
- 必须对齐：
  - final `total energy`
  - final `residual threshold` state
  - final converged/not-converged state
- Tolerance schema：`docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- 当前 canonical gold matrix（v0）中的 gate-required case：`si8_pbe_nc`、`si8_pbe_uspp`
- 若该页使用任何 projection-grade 表述，必须同时写出：
  - `correctness_status`
  - `confidence`
  - `assumption_set_id`

如果 accurate-layer 结果还没闭合，本节必须明确写：
- `Gold gate result: partial`（若 accurate-layer 尚未闭合）

---

## 7. 为什么不是另外两类架构

### Why not `F1`
常见写法：
- 若当前推荐的不是 `F1`，必须写明：`F1` 在当前 artifact-backed 排名、correctness 或工程推进条件下，为什么还不是最优主线；
- 若当前没有 promoted family，则写“`F1` 也尚未被提升，因为 mainline evidence 还不足以支持 decisive recommendation”。

### Why not `F2`
常见写法：
- 若当前推荐的不是 `F2`，必须写明：`F2` 在当前 artifact-backed 排名、correctness 或工程推进条件下，为什么还不是最优主线；
- 若当前没有 promoted family，则写“`F2` 也尚未被提升，因为 mainline evidence 还不足以支持 decisive recommendation”。

### Why not `F3`
常见写法：
- 若当前推荐的不是 `F3`，必须写明：`F3` 在当前 artifact-backed 排名、correctness 或工程推进条件下，为什么还不是最优主线；
- 若当前没有 promoted family，则写“`F3` 仍保留为 hypothesis-grade lane，不参与当前对外 decisive recommendation”。

---

## 8. 这份结论能支持什么，不能支持什么

### 能支持
- 下一阶段是否继续以 simulator/DSE 为主线
- 是否已经形成 family-level recommendation
- CPU/device/datapath 的候选分工方向
- 是否值得继续进入更细的 FPGA / RTL / runtime 工程化验证

### 不能支持
- RTL 参数最终冻结
- 最终 DMA / buffer / memory budget 结论
- 最终 board-level power claim
- 在 fast-layer/accurate-layer 证据未闭合时，强行宣称某个 family 已经“胜出”

---

## 9. 建议下一步

如果已经有 promoted family：
1. 补齐该 family 的 accurate-layer 和 board-facing observability closure；
2. 进入更细的 runtime / memory-system / FPGA prototype 验证；
3. 继续保留其他 family 作为 sanity baseline 或 fallback path。

如果当前仍是 `none-yet`（**当前默认**）：
1. 补齐 fast-layer metric population，至少让 mainline cases 形成 `primary_candidate + fallback_candidate`；
2. 用 `si8_pbe_nc` 和 shortlisted candidates 继续跑 correctness-capable validation；
3. 在不放松 correctness/tolerance contract 的前提下完成 ranking-grade / projection-grade closure。

如果当前已经进入 `projection_eligible`：
1. 先从 `qe_next_stage_artifact_bundle_manifest.json / .md` 读取顶层 readiness 与 artifact 路径；
2. 从 `qe_next_stage_projection_review.json / .md` 读取所有 accurate-layer-passing shortlisted candidates；
3. 从 `qe_next_stage_stage_main_recommendation.json / .md` 读取最终 recommended family、recommended primary candidates 和 validated alternatives；
4. 用 stage-main recommendation package 作为首页 recommendation card 的直接机器可核对来源。

---

## 10. 口头汇报 30 秒版

### 10.1 recommendation-grade 版本
> 我们这一步不是直接冲 RTL，而是先用 QE-only 的双层仿真框架比较 `F1 / F2 / F3`。当前已经能把 system-level recommendation 收口到 `F?`，因为它在统一 correctness gate 下，给出了最可辩护的 convergence-scoped range 和 CPU/device 分工，所以值得继续做工程化验证。

### 10.2 evidence-incomplete 版本（示例）
> 我们已经把 QE-only 的双层仿真框架和 shortlist policy 冻结好了，但目前还没有把任何 family 升成 projection-grade recommendation。原因不是 story 不清楚，而是 fast-layer ranking metrics 还没填实；下一步应该先把 `si4_pbe_uspp_small` 和 `graphene_pbe_uspp` 的 shortlist closure 做出来，再由 `si8_pbe_nc` 的准确层继续兜底 correctness。
