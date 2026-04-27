# 2026-04-13 Advisor Cover Memo Template — SystemC System-Level DSE v0

## 使用说明

这份 memo 是 advisor pack 的“一页先读版”。它的任务不是替代主报告，而是用最少文字回答三个问题：

1. 当前是否已经能推荐某个 family？
2. 如果能，为什么现在推荐它？
3. 如果还不能，最关键的阻塞是什么？

默认上游输入：

- executive summary one-pager
- advisor-facing report
- stage artifact bundle manifest（release-facing 顶层入口）
- QE gold correctness gate 结果
- confidence / claims rubric
- next-stage phase summary / shortlist output
- projection review package（若 stage 已到 `projection_eligible`）
- stage-main recommendation package（若已经形成正式对外推荐包）

如果这些输入还不齐，memo 也必须完整，但要明确写成 **evidence-incomplete memo**，而不是假装已经有了 projection-grade 结论。

---

## Memo 标题
**Subject: System-Level DSE Recommendation for QE-Oriented Soft/Hardware Co-Design**

## Memo 正文写法

### A. 若已经形成 recommendation-grade 结论
老师您好，

这轮我们基于当前 brownfield 的 SystemC/timed-functional 模型，对 `F1 / F2 / F3` 三类软硬件协同系统架构做了第一版 system-level DSE。当前 recommendation 不是 RTL 定版，而是在统一 QE correctness/tolerance contract 下，对“下一阶段最值得继续做的系统架构方向”给出判断。

本轮推荐 **`[recommended_family]`** 作为下一阶段主线。该 recommendation 的证据边界如下：

- `recommendation_type = [ranking-grade or projection-grade]`
- `correctness_status = [status]`
- `confidence = [level]`
- 若 `recommendation_type = projection-grade`，再补：`speedup_to_convergence_range = [range]` 与 `energy_to_convergence_range = [range]`
- 若当前 package 已进入 release-facing 使用阶段，优先从 `qe_next_stage_artifact_bundle_manifest.json / .md` 下钻到 `stage_main_recommendation_package` 与 `projection_review`

从系统分工上看，这个 family 最合适的原因是：

- CPU 继续保留 outer SCF、`rho -> Veff`、convergence decision 与 exception governance；
- Device runtime 承担 descriptor / resident / spill / DMA / completion orchestration；
- Hardware datapath 固化 `[operator_set]`，因此能在当前 contract 下提供最可辩护的 system-level 收益。

与另外两类架构相比：

- 对每个非推荐 family，都必须引用 artifact-backed why-not；
- 若当前 artifact 还不足以支持 why-not 细化，就写“该 family 仍待后续 shortlist / accurate-layer 证据闭合”，而不是预设 baseline / winner / stretch 身份。

因此，这轮工作的实际价值是：

1. 先把系统架构族方向选对；
2. 给出可辩护的 CPU/device/datapath 分工；
3. 判断是否值得继续进入更细的 FPGA / RTL / memory-system 工程化验证。

### B. 若尚未形成 recommendation-grade 结论（evidence-incomplete 示例）
老师您好，

这轮我们已经把 QE-only 的双层仿真框架、mainline case set、shortlist policy 与 correctness anchor 冻结下来，但当前还**没有**把任何 family 提升为 projection-grade recommendation。原因不是 thesis story 缺失，而是 mainline fast-layer bundle 仍处于 `insufficient_evidence`：`si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 还没有产出足够完整的 ranking-grade 指标，因此目前只能给出“框架已冻结、证据仍待补齐”的中间结论。

当前最重要的下一步不是更换研究方向，而是：

1. 补齐 fast-layer metric population；
2. 形成每个 mainline case 的 `primary_candidate + fallback_candidate`；
3. 用 `si8_pbe_nc` 与 shortlisted candidates 持续完成 correctness-capable validation。

因此，这一轮 memo 的推荐语应写成：
- `recommended_family = none-yet`
- `recommendation_type = evidence-incomplete`
- `main_blocker = fast-layer shortlist still insufficient_evidence`

---

## 附：一句话电梯版

### recommendation-grade 版本
> 当前 system-level DSE 的核心结论是：在 QE gold correctness gate 约束下，`[recommended_family]` 是现阶段最值得继续做的系统架构族，并且保留了最合理的 CPU/device/datapath 分工。若本轮 recommendation 已达到 `projection-grade`，再附带展示可辩护的 convergence-scoped range。

### evidence-incomplete 版本（示例）
> 当前 system-level DSE 的核心结论还不是“哪一个 family 已经胜出”，而是：QE-only 的双层仿真框架已经冻结，下一步必须先补齐 fast-layer ranking metrics 和 shortlist closure，之后才能把任何 family 升成正式 recommendation。
