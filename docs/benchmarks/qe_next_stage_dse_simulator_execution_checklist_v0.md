# QE 下一阶段 DSE / Simulator 执行清单 v0

## 0. 定位

本文把已经冻结的下一阶段方向收口成一份可执行 checklist。

当前冻结前提：

- `QE-only`
- 模拟器 / DSE 为主线
- `RTL` 暂不作为下一阶段主结果
- 采用 **双层仿真框架**：
  - **快层**：DSE 用的 system simulator
  - **准层**：只对 anchor / shortlisted candidates 跑的 correctness-capable path

来源：

- `.omx/specs/deep-interview-qe-next-stage-dse-simulator.md`
- `docs/architecture/qe_system_optimized_delta_20260413.md`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`

## 1. 冻结后的最小 case set

### 1.1 DSE 主结果 case

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`

这两个 case 用于：

- 形成下一阶段的主 ranking 结果
- 覆盖 small-Si bring-up 与 2D/generalized shape
- 作为 candidate selection 的 primary cases

### 1.2 correctness anchor

- `si8_pbe_nc`

这个 case 用于：

- 保持 frozen QE gold correctness lane
- 作为 correctness / convergence 的第一优先 anchor
- 给 shortlisted candidates 的“准层”验证提供同口径锚点

### 1.3 canonical coverage case

- `si8_pbe_uspp`

这个 case 用于：

- 扩展第二个 canonical QE gold case 的正确性覆盖
- 检查当前 accurate-layer / simulator 对 USPP canonical coverage 的可用性
- 作为 recommendation-grade 之后的 coverage sanity check，而不是替代 `si8_pbe_nc` 的第一优先 anchor 角色

## 2. 双层仿真框架

### 2.1 快层：system simulator / DSE evaluator

快层必须输出：

- `time_to_convergence_s`
- `energy_to_convergence_j`
- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

其职责是：

- 大量 sweep design points
- 做 candidate ranking
- 拒绝明显不可信点（spill 太高、fallback 太高、搬运太大）

### 2.2 准层：correctness-capable path

准层不要求覆盖所有 design points。

准层只对以下对象运行：

- `si8_pbe_nc` anchor
- 每个 mainline shortlisted candidate

准层至少要回答：

- `gold_pass`
- `convergence_comparable_pass`
- `final_total_energy_ry` 是否满足冻结容差
- `final_converged`
- `final_residual_threshold_reached`

## 3. 冻结后的目标函数

### 3.1 主优化目标

1. **第一优先**：`time_to_convergence_s` 最小
2. **第二优先**：`energy_to_convergence_j` 最小

### 3.2 约束 / 解释指标

下面这些指标不作为隐藏主目标，而作为约束或解释器：

- `bytes_moved_to_convergence`
- `fallback_ratio`
- `spill_ratio`

### 3.3 推荐判断规则

- 先按 `time_to_convergence_s` 排序
- 再用 `energy_to_convergence_j` 打破主目标相近的 tie
- `fast_layer` 的三态分类冻结为：`reject` / `explain-only` / `promotion-eligible`
- 若 `result_status ∈ {model_error, candidate_missing, baseline_missing, baseline_normalization_error, compare_error}`，该点直接记为 `reject`
- 若 `time_to_convergence_s`、`energy_to_convergence_j`、`bytes_moved_to_convergence`、`fallback_ratio`、`spill_ratio` 有任一缺失，或 `ranking_grade_ready != true`，该点只能记为 `explain-only`
- 只有 `promotion-eligible` 的点才允许进入 `primary candidate / fallback candidate` shortlist
- 若按 `time_to_convergence_s` 排序后的额外候选点，在 `energy_to_convergence_j` 打破前序 tie 后，仍与 `primary candidate` 的时间差落在 `<= 5%` tie-band 内，则该点允许作为额外 promoted candidate 进入准层；否则只保留 `primary candidate + fallback candidate`

## 4. 下一阶段的执行顺序

### Step 1 — 冻结输入集合

- [ ] 把 `si4_pbe_uspp_small`、`graphene_pbe_uspp` 标成 next-stage DSE 主结果 case
- [ ] 把 `si8_pbe_nc` 标成 correctness anchor
- [ ] 确认所有 case 都绑定同一 `qe_tolerance_schema_id`

### Step 2 — 快层运行

- [ ] 用 DSE runner 对 `F1/F2` 为主、`F3` 为条件性候选做 sweep
- [ ] 输出 candidate ranking
- [ ] 对每个 swept point 输出 `reject / explain-only / promotion-eligible` 分类
- [ ] 至少给出每个主结果 case 的：
  - primary candidate
  - fallback candidate

### Step 3 — 准层校验

- [ ] 对 `si8_pbe_nc` 跑 correctness-capable 路径
- [ ] 对 `si8_pbe_uspp` 跑 canonical coverage 路径
- [ ] 对每个 shortlisted candidate 跑 correctness-capable 路径
- [ ] 若 `gold_pass` 或 `convergence_comparable_pass` 不成立，则该 candidate 降级

### Step 3.1 — 非阻塞 generalization coverage（建议）

- [ ] 对 `si4_pbe_uspp_small`、`graphene_pbe_uspp`、`graphene_pbe_paw`、`h2_tiny` 跑 nonblocking generalization coverage compare
- [ ] 把结果作为 broader confidence / generalization evidence 记录下来
- [ ] 这些结果默认不直接阻塞当前 release-facing recommendation，但必须显式标注为 nonblocking

### Step 4 — 汇总报告

- [ ] 对 `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 给出 mainline DSE ranking 结果
- [ ] 用 `si8_pbe_nc` 给出 correctness/convergence anchoring
- [ ] 若 stage 已到 `projection_eligible`，生成 `projection review package`
- [ ] 若 stage 已到 `projection_eligible`，生成 `stage-main recommendation package`
- [ ] 若 package 已进入 release-facing 使用阶段，生成 `stage artifact bundle manifest`
- [ ] 明确哪些结论是 grounded，哪些仍是 projected

## 5. 这一阶段不做什么

- 不把 RTL 作为这一阶段主结果
- 不要求每个 DSE 点都跑完整 golden closure
- 不提前宣称最终 FPGA / ASIC superiority
- 不让 `F3` 在没有额外证据时自动升级为主推荐 family

## 6. 下一阶段的完成标准

若下面条件都满足，则可认为下一阶段主线建立完成：

- `si4_pbe_uspp_small` 与 `graphene_pbe_uspp` 都有可解释的 DSE ranking 结果
- `si8_pbe_nc` 的 correctness-capable anchor 保持可用
- shortlisted candidates 至少能进入准层复核
- 主结果文档中明确写出：
  - 快层筛选
  - 准层兜底
  - time first / energy second / bytes+fallback+spill as constraints

## 7. 一句话工作定义

> 下一阶段的工作不是直接冲 RTL，而是先把 QE-only 的双层仿真框架做成 decision-grade：快层负责筛选 candidate，准层负责保证 anchor 和 shortlisted candidates 仍然算得对。
