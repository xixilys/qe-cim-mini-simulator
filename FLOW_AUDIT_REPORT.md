# 3层DSE框架完整流程审核报告

**日期**: 2026-05-08  
**审核人**: Sisyphus Agent  
**测试状态**: 158 passed, 0 failed, 3 skipped

---

## 1. 最初设计要求回顾

根据 `.opencode/plans/3layer_dse_team_plan.md`:

### 架构设计
- **Layer 1**: 解析模型（秒级）- 初筛不可行设计点
- **Layer 2**: Python TLM（分钟级）- 中等精度时序估计
- **Layer 3**: SystemC（小时级）- 高保真仿真
- **晋升逻辑**: 自动化L1→L2→L3数据流
- **目标**: 支持7家族(F1-F7)，>95%置信度

### 关键要求
1. ✅ Layer 1输出包含: design_point_id, latency, throughput, power, family, confidence
2. ✅ Layer 2输出包含: tlm_latency, tlm_throughput, accuracy_vs_layer1, promotion_recommendation
3. ✅ Promotion Request包含: source_layer, target_layer, justification, metrics_snapshot
4. ✅ 接口定义: Python dataclasses + JSON schemas
5. ⚠️ SystemC通用图执行引擎（部分完成 - 骨架已创建）

---

## 2. 实际流程验证

### 2.1 Layer 1 (FastPerformanceModel)

**输入**: DesignPoint + Workload
**输出**: EvaluationResult (L1)

验证结果:
- ✅ 使用真实7家族模型(F1PipelineModel, F2SystolicModel, etc.)
- ✅ Iteration scaling已修复（iterations线性影响latency/energy）
- ✅ 输出包含: latency_ms, throughput_gops, power_w, area_mm2
- ✅ Confidence计算基于resource_margin
- ✅ Promotion score基于accuracy + confidence + resource_margin
- ✅ Unknown family (F8) 返回failed状态

**代码**: `dse_v2/models/fast/performance_model.py` + `family_models.py`

### 2.2 Layer 1 → Layer 2 晋升

**晋升条件**:
- Status == 'passed'
- Resource utilization <= 100%
- Score >= threshold (family-specific: F1=0.70, F4=0.70)
- Confidence >= min_confidence
- Pareto frontier passed
- Budget available

验证结果:
- ✅ 所有检查项实现正确
- ✅ Budget exhaustion正确阻止晋升
- ✅ Promotion trace记录完整决策

### 2.3 Layer 2 (PythonTLM)

**输入**: DesignPoint + Workload
**输出**: Layer2Output

验证结果:
- ✅ 计算h_psi和cdiaghg的compute/transfer时间
- ✅ Family-specific timing scale (F1=1.50, F2=1.25, F3=1.00)
- ✅ Iterations影响flops计算
- ✅ 输出包含: latency_ms, throughput_gops, power_w, confidence

**代码**: `dse_v2/models/mid/python_tlm.py`

### 2.4 Layer 2 → Layer 3 晋升

**晋升条件**:
- Status in {'passed', 'projection_only'}
- Score >= threshold (family-specific: F1=0.80, F4=0.82)
- Confidence >= min_confidence (projection时>=0.90)
- MAPE <= 20%
- Pareto frontier passed

验证结果:
- ✅ Projection stricter confidence check生效
- ✅ MAPE检查实现
- ✅ Promotion trace记录L2→L3决策

### 2.5 Layer 3 (当前: projection_only)

**输入**: L2 Result
**输出**: Projected L3 Result

验证结果:
- ✅ 明确标记 `is_projection=True`
- ✅ Projection uncertainty = 0.20
- ✅ Metrics调整: latency*0.92, throughput*1.08, power*0.97
- ✅ Status = 'projection_only'
- ⚠️ **未接入真实SystemC**（用户明确要求"不要使用投影"）

**代码**: `dse_v2/orchestrator.py::_project_l3()`

### 2.6 SystemC Backend骨架

验证结果:
- ✅ 环境变量组装: QEBS_ARCH_FAMILY, QEBS_MAX_SCF_ITERS, etc.
- ✅ 命令组装: `qe_band_solver_model`
- ✅ JSON输出解析结构
- ⚠️ `run_episode()` 抛出NotImplementedError

**代码**: `dse_v2/backends/systemc_backend.py`

---

## 3. 端到端流程测试

### 场景1: 正常流程 (F4, iterations=8)
```
L1 → L2: Promote (score=0.708, confidence=0.708)
L2 → L3: Promote (score=0.849, confidence=0.871)
L2 → L3: Promote (score=0.879, confidence=0.911)
结果: Fidelity=L3, Status=projection_only
```
✅ **通过**

### 场景2: Budget Exhaustion
```
L1 → L2: Block (reason=budget_exhausted)
结果: Fidelity=L1, Recommendation=hold
```
✅ **通过**

### 场景3: Unknown Family (F8)
```
L1: Status=failed, Model=unknown_family
结果: Fidelity=L1, Status=failed
```
✅ **通过**

### 场景4: SystemC Execution Mode
```
l3_mode='systemc_execution' + backend=None
结果: NotImplementedError
```
✅ **通过**（正确报错）

---

## 4. 与最初设计的符合度评估

| 设计要求 | 状态 | 说明 |
|----------|------|------|
| 3层架构 (L1/L2/L3) | ✅ | 完整实现 |
| Layer 1解析模型 | ✅ | 7家族模型，iteration scaling |
| Layer 2 Python TLM | ✅ | 计算+传输时间模型 |
| Layer 3 SystemC | ⚠️ | 当前为projection_only |
| 晋升逻辑 | ✅ | L1→L2→L3完整决策链 |
| 接口定义 | ✅ | Dataclasses + JSON schemas |
| Confidence >95% | ❌ | 当前约75%（研究型框架） |
| 7家族支持 | ✅ | F1-F7完整 |
| Workload特异化 | ✅ | h_psi/cdiaghg区分 |
| GPU Baseline | ⚠️ | 15-case状态报告，11 deferred |
| SystemC通用图 | ⚠️ | 骨架已创建，待实现 |

---

## 5. 关键发现

### 5.1 正确实现的
1. ✅ 3层数据流完整
2. ✅ 晋升逻辑正确（score/confidence/budget/pareto）
3. ✅ Projection标记明确
4. ✅ Unknown family拒绝
5. ✅ Iteration scaling修复
6. ✅ Promotion trace记录完整

### 5.2 需要改进的
1. ⚠️ **L3仍是projection**：用户明确要求"不要使用投影"
2. ⚠️ **SystemC未接入**：backend骨架待实现
3. ⚠️ **GPU baseline未闭合**：需要真实GPU测量
4. ⚠️ **Confidence未达95%**：当前约75%

### 5.3 发现的Bug（已修复）
1. ✅ Promotion trace显示"L1→L3"应为"L2→L3"
2. ✅ Iterations未影响family模型latency
3. ✅ 校准阈值过于宽松(500/100)

---

## 6. 结论

### 当前状态
**研究型3层DSE框架，功能完整但L3为projection_only**

### 是否符合最初设计？
- **架构层面**: ✅ 符合（3层+晋升逻辑）
- **功能层面**: ⚠️ 部分符合（L3未接入SystemC）
- **性能层面**: ❌ 不符合（confidence约75%，未达>95%）

### 建议
1. **短期**: 发布RC版本（projection_only口径）
2. **中期**: 接入真实SystemC执行
3. **长期**: 完成GPU baseline，达到>95% confidence

---

*审核完成时间: 2026-05-08*  
*测试证据: 158 tests passed*
