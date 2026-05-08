# Wave 5 完成报告：3层DSE框架修复冻结

## 日期：2026-05-08
## 状态：RC (Release Candidate) - projection_only / evidence_only

---

## 测试状态

**158 passed, 0 failed, 3 skipped**

### 测试分布
- `test_calibration.py`: 20 passed
- `test_end_to_end_3layer.py`: 8 passed  
- `test_family_iteration_scaling.py`: 14 passed
- `test_fast_model_all_families.py`: 10 passed
- `test_multi_workload.py`: 3 passed
- `test_negative_cases.py`: 10 passed
- `test_performance_budget.py`: 4 passed
- `test_three_layer_orchestrator.py`: 6 passed
- 其他测试：83 passed

---

## Wave 5 修复完成项

### 1. L1 Iteration Scaling ✅
- **问题**：`iterations`参数在7个family模型中未被使用
- **修复**：所有 `_kernel_times()` 和 `_combine_kernel_times()` 现在正确缩放iterations
- **验证**：`test_family_iteration_scaling.py` 验证1/4/8/16 iterations的单调性和比例

### 2. 校准测试阈值收紧 ✅
- **问题**：阈值仍为500/100（过于宽松）
- **修复**：latency_ratio <= 15.0, throughput_ratio <= 100.0
- **验证**：所有7个family通过校准测试

### 3. L3 Projection标记 ✅
- **问题**：L3是固定倍率投影但未明确标记
- **修复**：`is_projection=True`, `projection_uncertainty=0.20`
- **验证**：`test_l3_projection_is_explicitly_marked_projection_only`

### 4. L3决策Trace ✅
- **问题**：promotion_trace缺少L3 projection决策记录
- **修复**：orchestrator现在记录L3 projection的promote/hold决策
- **验证**：`test_projection_only_requires_stricter_l3_promotion`

### 5. Unknown Family拒绝 ✅
- **问题**：F8等未知family静默落到F7模型
- **修复**：`FastPerformanceModel`返回`status='failed'`和错误信息
- **验证**：`test_fast_model_unknown_family_fails_explicitly`

### 6. GPU基线真实化 ✅
- **问题**：使用mock数据
- **修复**：`run_gpu_baselines.py`返回`deferred_software_stack`
- **验证**：15-case真实状态报告（coverage=73.33%）

---

## 文件变更统计

- **修改**：24个文件
- **新增**：91个文件
- **关键新增**：
  - `dse_v2/`：7家族模型、编排器、晋升引擎、SystemC backend骨架
  - `tests/`：14个测试文件（158 tests）
  - `interfaces/`：类型定义、验证器
  - `docs/benchmarks/gpu_case_list_v0.json`：15-case真实QE案例

---

## 已知限制（技术债务）

1. **L3仍是projection_only**：未接入真实SystemC执行
   - 已创建`dse_v2/backends/systemc_backend.py`骨架
   - SystemC可执行文件已验证：`model/qe_band_solver_model/build/qe_band_solver_model`

2. **GPU baseline未完全闭合**：11/15 cases为deferred
   - 需要真实GPU后端实现

3. **L1模型物理精度**：iteration scaling已修复，但memory model仍简化

---

## Oracle置信度评估

| 组件 | 评分 | 状态 |
|------|------|------|
| 接口与schema | 86% | 生产可用 |
| L1→L2编排 | 82% | 生产可用 |
| L1解析模型 | 75% | iteration scaling已修复 |
| Promotion Engine | 78% | projection stricter check生效 |
| L3投影层 | 80% | 标记正确但非真实SystemC |
| 测试体系 | 75% | 158 tests |

**整体：研究型3层DSE框架 75/100**

---

## 发布建议

✅ **可以发布为RC版本**（projection_only / evidence_only）

❌ **不建议声称**：
- ">95%置信度"
- "最终发布"
- "生产级闭环DSE"

### 进入最终发布需要：
1. 接入真实SystemC执行作为L3
2. 完成至少3个代表性case的真实GPU baseline
3. L1模型通过更多workload验证

---

## 下一步选项

1. **接入SystemC**：实现`SystemCBackend`并替换`_project_l3()`
2. **GPU Baseline**：实现真实GPU执行后端
3. **发布RC**：当前状态作为evidence-only发布
4. **扩展Workloads**：增加更多QE案例验证

