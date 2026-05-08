# DesignPoint 数据结构

`DesignPoint` 是 Layer 1 解析模型输出给后续 DSE 评估层的设计点描述。它保留既有 `design_point_v1` Schema 的 `architecture_spec_ref`、`constraints`、`provenance` 字段，同时新增面向 3 层 DSE 的显式家族、拓扑、工作负载专用化与资源上限字段。

## 字段定义

| 字段 (Field) | 类型 (Type) | 必填 | 说明 |
|--------------|-------------|------|------|
| `schema_version` | string | 是 | 固定为 `design_point_v1`。 |
| `design_point_id` | string | 是 | 设计点唯一 ID，仅允许字母、数字、下划线和连字符。 |
| `family` | string | 新接口必填 | 架构家族，支持 `F1` 至 `F7`。 |
| `topology_type` | string | 新接口必填 | 拓扑类型，例如 `mesh_2d`、`noc`、`chiplet`。 |
| `parameters` | object | 是 | 参数集合。保留既有 `system_level`、`kernel_mapping`、`microarchitecture` 分组。 |
| `workload_specialization` | object | 新接口必填 | 工作负载专用化描述，包含 `workload_id`、`kernels`、`precision`。 |
| `target_layers` | array | 新接口必填 | 目标保真度层级，取值为 `L0` 至 `L4`。 |
| `resource_limits` | object | 新接口必填 | 面积、功耗、时延、吞吐和成本上限。 |
| `architecture_spec_ref` | string | 兼容字段 | 输入 `ArchitectureSpec` 的 SHA-256。 |
| `constraints` | object | 兼容字段 | 旧版约束字段；语义与 `resource_limits` 保持一致。 |
| `provenance` | object | 兼容字段 | 输入哈希、生成时间和工具版本。 |

说明：JSON Schema 为保持旧版 artifact 可读，未把新增 Layer 1 字段加入全局 `required`。但 Wave 1 之后的 Layer 1 producer 必须输出 `family`、`topology_type`、`workload_specialization`、`target_layers` 和 `resource_limits`。

## 架构家族

`family` 与 `parameters.system_level.family` 使用同一枚举：

- `F1`：CPU / host-only baseline。
- `F2`：GPU / accelerator baseline。
- `F3`：FPGA offload baseline。
- `F4`：cluster-first tile architecture。
- `F5`：CIM-oriented near-memory architecture。
- `F6`：heterogeneous multichiplet NoC architecture。
- `F7`：adaptive fabric architecture。

## JSON 示例

```json
{
  "schema_version": "design_point_v1",
  "design_point_id": "dp_f4_001",
  "family": "F4",
  "topology_type": "mesh_2d",
  "parameters": {
    "system_level": {
      "family": "F4",
      "n_gemm_tiles": 4,
      "n_eigen_tiles": 2,
      "tile_local_mem_kb": 1024
    }
  },
  "workload_specialization": {
    "workload_id": "qe_cbands_si8",
    "kernels": ["h_psi", "build_H_sub", "cdiaghg"],
    "precision": "FP64"
  },
  "target_layers": ["L1", "L2"],
  "resource_limits": {
    "max_area_mm2": 120.0,
    "max_power_w": 80.0,
    "max_latency_ms": 1000.0
  },
  "architecture_spec_ref": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "constraints": {
    "max_area_mm2": 120.0,
    "max_power_w": 80.0
  },
  "provenance": {
    "input_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generated_at": "2026-01-01T00:00:00",
    "tool_version": "layer1"
  }
}
```

## 兼容性约定

- 旧版消费者仍可读取 `architecture_spec_ref`、`constraints` 和 `provenance`。
- 新版消费者优先读取 `family`、`workload_specialization`、`target_layers` 和 `resource_limits`。
- 当 `constraints` 与 `resource_limits` 同时存在时，数值应保持一致；若不一致，后续评估层应优先使用 `resource_limits` 并记录告警。
- Schema 兼容旧版 artifact；生产新的 Layer 1 artifact 时应按上表的「新接口必填」字段生成完整结构。
