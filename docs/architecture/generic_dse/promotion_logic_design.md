# Layer 2 TLM 与晋升逻辑设计

## 目标

本文定义三层 DSE 流水线中的晋升逻辑，覆盖 `L1 → L2` 与 `L2 → L3` 两个决策点。晋升逻辑服务于 Wave 1 框架：先用确定、可测试的规则控制候选设计进入更高保真度模型，后续 Wave 再替换或校准具体模型参数。

## 晋升输入

晋升引擎消费每一层模型输出中的以下字段：

| 字段 | 含义 | 说明 |
|------|------|------|
| `family` | 架构家族 | 取值为 `F1` 至 `F7`，未知家族按 `F1` 保守处理。 |
| `fidelity_level_achieved` | 当前层级 | `L1` 或 `L2`。 |
| `status` | 本层评估状态 | 只有 `passed` 可以晋升。 |
| `resource_legal` | 资源合法性 | 用于 `L1 → L2`，表示设计点满足面积、功耗、带宽等硬约束。 |
| `resource_utilization` | 资源利用率 | 任一数值型利用率超过 100% 时视为资源非法。 |
| `promotion_score` | 晋升分数 | 若模型已给出该字段，晋升引擎直接使用。 |
| `confidence` | 置信度 | 可直接给出，也可由 `uncertainty.confidence_level` 派生。 |
| `uncertainty.mape_percent` | 相对误差 | 用于 `L2 → L3`，要求 MAPE 不超过 20%。 |

## L1 → L2 晋升规则

候选设计必须同时满足以下条件：

1. `status == "passed"`。
2. 资源合法：`resource_legal != False`，且 `resource_utilization` 中所有数值型百分比不超过 100%。
3. `promotion_score ≥ threshold[family].l1_to_l2`。
4. `confidence ≥ threshold[family].min_confidence_l1`。
5. `L2` 晋升预算未耗尽。

默认基线规则为：`status == passed + 资源合法 + promotion_score ≥ 0.70 + confidence ≥ 0.55`。

## L2 → L3 晋升规则

候选设计必须同时满足以下条件：

1. `status == "passed"`。
2. `promotion_score ≥ threshold[family].l2_to_l3`。
3. `confidence ≥ threshold[family].min_confidence_l2`。
4. `MAPE ≤ 20%`。
5. `L3` 晋升预算未耗尽。

默认基线规则为：`status == passed + promotion_score ≥ 0.80 + confidence ≥ 0.75 + MAPE ≤ 20%`。

## 家族特异化阈值表

| 家族 | `L1 → L2` 分数阈值 | `L2 → L3` 分数阈值 | L1 最小置信度 | L2 最小置信度 | 设计意图 |
|------|-------------------|-------------------|---------------|---------------|----------|
| `F1` | 0.70 | 0.80 | 0.55 | 0.75 | 基线家族，采用任务给定默认阈值。 |
| `F2` | 0.65 | 0.75 | 0.50 | 0.70 | 早期探索家族，降低门槛以保留候选。 |
| `F3` | 0.68 | 0.78 | 0.55 | 0.72 | 中等风险家族，略低于基线但保持置信度要求。 |
| `F4` | 0.72 | 0.82 | 0.58 | 0.76 | 均衡 tile 架构，要求略高于基线。 |
| `F5` | 0.74 | 0.84 | 0.60 | 0.78 | 更复杂映射，晋升前要求更稳定证据。 |
| `F6` | 0.76 | 0.86 | 0.62 | 0.80 | 异构或多 chiplet 候选，采用保守阈值。 |
| `F7` | 0.78 | 0.88 | 0.65 | 0.82 | 自适应 fabric 候选，最高不确定性，阈值最严格。 |

对应代码配置位于 `dse_v2/promotion/thresholds.py`。

## 晋升分数计算公式

晋升引擎优先使用模型输出中的 `promotion_score`。当该字段缺失时，使用以下归一化后备公式：

```text
promotion_score = clamp(
    0.45 × accuracy
  + 0.25 × efficiency
  + 0.20 × resource_margin
  + 0.10 × confidence,
  0.0,
  1.0
)
```

其中：

- `accuracy = metrics.accuracy_vs_reference`；若缺失，则使用 `confidence`。
- `efficiency = min(metrics.energy_efficiency_gops_per_w / 10.0, 1.0)`。
- `resource_margin = 1.0 - max(resource_utilization.values()) / 100.0`；若缺失，则取 `0.5`。
- `confidence` 来自顶层 `confidence`，若缺失则取 `uncertainty.confidence_level`。

该公式只作为 Wave 1 的兜底逻辑。后续 Wave 可使用校准后的误差模型、Pareto 排名或 BO acquisition score 替换，但必须保持输出范围为 `[0, 1]`。

## 预算检查

`PromotionEngine` 支持按目标层级设置预算，例如：

```python
PromotionEngine(budgets={"L2": 32, "L3": 8})
```

当目标层级预算为 0 时，晋升结果为 `promote == False`，原因标记为 `budget_exhausted`。预算只在实际晋升成功时消耗。

## Layer 2 Python TLM 输出契约

`dse_v2/models/mid/python_tlm.py` 提供 `PythonTLM.run_episode(design_point, workload)` 骨架。当前 Wave 1 简化模型返回 `Layer2Output`，包含：

- `status`
- `metrics.latency_ms`
- `metrics.throughput_gops`
- `metrics.power_w`
- `metrics.area_mm2`
- `metrics.energy_efficiency_gops_per_w`
- `uncertainty.confidence_level`
- `uncertainty.mape_percent`
- `uncertainty.sample_size`（整数）
- `resource_utilization`
- `promotion_score`
- `confidence`
- `family`
- `fidelity_level_achieved == "L2"`

`resource_utilization` 保留原始百分比；当任一利用率超过 100% 时，`status` 应为 `failed`，避免把非法设计点伪装成边界合法点。

该输出可直接传给 `PromotionEngine.evaluate()`，也可通过 `Layer2Output.to_dict()` 转为字典后进入流水线 artifact 系统。`family` 字段会随输出传递，确保 F2-F7 的家族特异化阈值不会退回到默认 `F1`。
