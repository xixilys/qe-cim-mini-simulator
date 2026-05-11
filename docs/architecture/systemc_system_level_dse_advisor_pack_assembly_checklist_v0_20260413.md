# 2026-04-13 Advisor Pack Assembly Checklist — SystemC System-Level DSE v0

## 1. 文档定位

这份 checklist 给 team 的最后汇总阶段使用，目的是把当前多 lane 产物收成一份**老师可读、口径一致、不过度承诺**的 advisor pack。

它假设以下文档已经存在并作为上游输入：

- family responsibility matrix
- advisor-facing report template
- confidence and claims rubric
- executive summary one-pager template
- QE gold correctness report
- sweep / summary ranking outputs
- projection review package（若 stage 已到 `projection_eligible`）
- stage-main recommendation package（若已经形成正式对外推荐包）
- stage artifact bundle manifest（若已经形成 release-facing 推荐总包）

## 2. Advisor pack 最小组成

最终汇报包至少应包含 4 部分：

1. **One-page executive summary**
   - 推荐 family
   - `correctness_status`
   - `confidence`
   - `speedup_to_convergence_range`
   - `energy_to_convergence_range`

2. **Main report**
   - family ranking
   - CPU/device 分工
   - QE gold correctness gate
   - portability evidence
   - risk / assumptions / limitations

3. **Correctness appendix**
   - QE gold reference 定义
   - tolerance schema ID
   - `total energy` / `residual threshold` / convergence match

4. **Projection appendix**
   - assumption set
   - range 生成依据
   - 为什么是 range 而不是 point estimate

5. **Recommendation package appendix**（projection-grade 时）
   - projection review package
   - stage-main recommendation package
   - recommended primary candidates
   - validated alternatives

6. **Release bundle appendix**（release-facing 时）
   - stage artifact bundle manifest
   - phase summary / projection review / stage-main recommendation package 的统一路径索引

## 3. 汇总前检查（必须全部通过）

### 3.1 输入完整性
- [ ] family comparator 已覆盖 `F1 / F2 / F3`
- [ ] QE gold correctness report 已生成
- [ ] 已引用 `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_correctness_contract_v0.md`
- [ ] 已引用 `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/qe_gold_numerical_tolerance_schema_v0.json`
- [ ] sweep / summary 已输出区间型 projection
- [ ] 若 stage 已到 `projection_eligible`，`projection_review` 已生成
- [ ] 若 stage 已到 `projection_eligible`，`stage_main_recommendation_package` 已生成
- [ ] 若当前 package 已进入 release-facing 使用阶段，`stage_artifact_bundle_manifest` 已生成
- [ ] 已引用 `/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`
- [ ] 已引用 `/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
- [ ] `assumption_set_id` 已冻结
- [ ] `QE baseline ID` 已冻结（不再是临时占位）
- [ ] `QE numerical tolerance schema ID` 已冻结（不再是 `pending_*` 占位）

### 3.2 首页字段完整性
- [ ] `recommended_family`
- [ ] `correctness_status`
- [ ] `confidence`
- [ ] `speedup_to_convergence_range`
- [ ] `energy_to_convergence_range`（若引用 schema，确认对应字段 `energy_to_convergence_range_j` 已正确转成 Joule口径）
- [ ] `algorithm_contract_deviation`
- [ ] `ranking_grade_ready` / `projection_grade_ready` 状态已核对
- [ ] `main_reason`
- [ ] `main_caveat`
- [ ] `recommended_primary_candidates`（projection-grade 时）
- [ ] `validated_alternative_candidates`（projection-grade 时）
- [ ] `stage_artifact_bundle_manifest`（release-facing 时）

### 3.3 Claim discipline
- [ ] ranking-grade 与 projection-grade 未混写
- [ ] 所有 projection 都是 range，不是单点值
- [ ] `gold_fail` 时未给出强推荐
- [ ] `portability_only` 未单独支撑主推荐
- [ ] `algorithm_contract_deviation = yes` 时已显式降级 confidence

## 4. 讲给老师时必须能回答的 6 个问题

1. **为什么先做 family 选型，而不是先调 DMA/buffer？**
2. **为什么推荐的是这个 family，而不是另外两个？**
3. **这个 recommendation 的 correctness 证据到底有多强？**
4. **为什么 speedup / energy 只报 range？**
5. **哪些结论现在能信，哪些还只是 exploratory？**
6. **下一步如果继续做，最值得花时间的工程点是什么？**
7. **stage-main recommendation package 和 projection review package 的区别是什么？**
8. **release-facing 时应该先看哪个 artifact？**

## 5. 常见失败模式

### 5.1 过度承诺
错误例子：
- 把 system-level proxy 说成最终 RTL 结论
- 把区间 projection 说成精确板级数值

### 5.2 正确性不足却继续强推
错误例子：
- QE gold gate 没过，仍然给强 recommendation
- 只凭 portability lane 就推 family

### 5.3 讲不清 CPU/device 分工
错误例子：
- 报告里只讲 cluster，不讲 host/device 合同
- 报告里说不清 `diag` 留在哪边以及为什么

## 6. 推荐的成包顺序

1. 先填 **family matrix** 对应的 CPU/device/datapath 叙事
2. 再填 **QE gold correctness gate**
3. 再填 **family ranking + projection ranges**
4. 最后按 **confidence rubric** 做一次 claims sanity check
5. 再生成 **one-page executive summary**

## 7. 最终放行条件

只有当以下条件都满足时，advisor pack 才应进入正式汇报：

- [ ] `correctness_status` 已明确
- [ ] `confidence` 已按 rubric 定级
- [ ] `speedup_to_convergence_range` 已有 assumption set 支撑
- [ ] `energy_to_convergence_range` 已有 assumption set 支撑
- [ ] 若 stage 已到 `projection_eligible`，projection review / stage-main recommendation package 已齐全且互相一致
- [ ] 若当前 package 已进入 release-facing 使用阶段，stage artifact bundle manifest 已存在且正确索引 phase summary / projection review / stage-main package
- [ ] 报告明确声明 v1 不是 RTL 参数冻结器
- [ ] 报告明确声明未直接外推 board-level power

## 8. 交付后建议

如果老师认可当前主推荐，下一阶段应优先进入：

1. 更细的 faithfulness / tolerance 校准
2. DMA / buffer / resident 工程化 refinement
3. FPGA prototype 或更高 fidelity 的 runtime / interconnect 建模

如果老师认为 projection 风险仍高，则优先进入：

1. QE gold correctness 深化
2. assumption-set 缩窄
3. confidence 从 `medium` 提升到 `high` 的证据补充
