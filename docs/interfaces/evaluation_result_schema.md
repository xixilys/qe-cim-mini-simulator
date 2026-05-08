# EvaluationResult 数据结构

`EvaluationResult` 描述一个 `DesignPoint` 在一个或多个保真度层级上的评估结果。Wave 1 扩展在既有 `evaluation_result_v1` 单结果字段基础上增加 `design_point_id` 与 `layer_results`，用于承载多层 DSE 评估轨迹。

## 字段定义

| 字段 (Field) | 类型 (Type) | 必填 | 说明 |
|--------------|-------------|------|------|
| `schema_version` | string | 是 | 固定为 `evaluation_result_v1`。 |
| `result_id` | string | 是 | 结果唯一 ID。 |
| `design_point_id` | string | 新接口必填 | 被评估的 `DesignPoint` ID。 |
| `evaluation_config_ref` | string | 兼容字段 | 输入 `EvaluationConfig` 的 SHA-256。 |
| `fidelity_level_achieved` | string | 新接口必填 | 已完成的最高保真度层级，取值为 `L0` 至 `L4`。 |
| `layer_results` | array | 新接口必填 | 多保真度或多层评估结果列表。 |
| `metrics` | object | 兼容字段 | 汇总指标；默认对应最高已完成层级。 |
| `status` | string | 兼容字段 | 汇总状态：`passed`、`failed`、`inconclusive`、`timeout` 或 `error`。 |
| `promotion_recommendation` | string | 是 | 晋级建议：`promote`、`hold` 或 `reject`。 |
| `promotion_score` | number | 是 | 晋级评分，范围 `[0, 1]`。 |
| `uncertainty` | object | 兼容字段 | 汇总不确定性，例如 95% 置信区间。 |
| `resource_utilization` | object | 兼容字段 | 汇总资源利用率。 |
| `provenance` | object | 兼容字段 | 输入哈希、生成时间、工具版本和执行耗时。 |

说明：JSON Schema 为保持旧版 artifact 可读，未把新增 Layer 1 字段加入全局 `required`。但 Wave 1 之后的 Layer 1 evaluator 必须输出 `design_point_id`、`fidelity_level_achieved`、`layer_results`、`promotion_recommendation` 和 `promotion_score`。

## LayerResult 字段

| 字段 (Field) | 类型 (Type) | 必填 | 说明 |
|--------------|-------------|------|------|
| `layer_id` | string | 是 | 层级 ID，通常与 `fidelity_level` 相同。 |
| `fidelity_level` | string | 是 | 保真度层级：`L0` 至 `L4`。 |
| `status` | string | 是 | 该层级评估状态。 |
| `metrics` | object | 是 | 该层级指标，如 `latency_ms`、`throughput_gops`、`power_w`。 |
| `uncertainty` | object | 否 | 该层级不确定性。 |
| `resource_utilization` | object | 否 | 该层级资源利用率。 |
| `promotion_score` | number | 否 | 该层级晋级评分。 |
| `model_used` | string | 否 | 该层级使用的模型，例如 `python_tlm`、`systemc_tlm`。 |
| `execution_time_seconds` | number | 否 | 该层级执行耗时。 |

## JSON 示例

```json
{
  "schema_version": "evaluation_result_v1",
  "result_id": "res_dp_f4_001",
  "design_point_id": "dp_f4_001",
  "evaluation_config_ref": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "fidelity_level_achieved": "L2",
  "layer_results": [
    {
      "layer_id": "L1",
      "fidelity_level": "L1",
      "status": "passed",
      "metrics": {
        "latency_ms": 120.0,
        "throughput_gops": 410.0,
        "power_w": 54.0,
        "accuracy_vs_reference": 0.72
      },
      "promotion_score": 0.72
    },
    {
      "layer_id": "L2",
      "fidelity_level": "L2",
      "status": "passed",
      "metrics": {
        "latency_ms": 96.0,
        "throughput_gops": 520.0,
        "power_w": 63.0,
        "accuracy_vs_reference": 0.86
      },
      "promotion_score": 0.86
    }
  ],
  "metrics": {
    "latency_ms": 96.0,
    "throughput_gops": 520.0,
    "power_w": 63.0,
    "accuracy_vs_reference": 0.86
  },
  "status": "passed",
  "promotion_recommendation": "promote",
  "promotion_score": 0.86,
  "provenance": {
    "input_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generated_at": "2026-01-01T00:00:00",
    "tool_version": "layer1",
    "execution_time_seconds": 2.0
  }
}
```

## 兼容性约定

- 旧版消费者可继续读取顶层 `metrics`、`status`、`promotion_recommendation` 和 `promotion_score`。
- 新版消费者应读取 `layer_results`，并将 `fidelity_level_achieved` 对应层级作为默认汇总层。
- 顶层 `metrics` 应与最高已完成层级的 `metrics` 保持一致，便于旧版流程无改造运行。
- Schema 兼容旧版 artifact；生产新的 Layer 1 artifact 时应按上表的「新接口必填」字段生成完整结构。
