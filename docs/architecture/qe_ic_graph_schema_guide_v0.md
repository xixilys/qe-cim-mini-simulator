# QE IC graph schema guide v0

## 1. 目标

graph schema v0 用来描述：
- 模块实例
- 模块连接关系
- 数据流与流程顺序
- placement
- 约束
- observability 需求

当前它是 **family-compatible overlay schema**，而不是任意自由拓扑描述语言。

---

## 2. 顶层字段

最小顶层字段：
- `graph_schema_version`
- `graph_id`
- `seed_template_id`
- `workload_class`
- `join_keys`
- `modules`
- `links`
- `flows`
- `placement`
- `estimation_profile`
- `constraints`
- `observability_requirements`

---

## 3. 设计原则

1. 先支持系统级表达，再支持细粒度硬件扩展。
2. graph 必须能导出当前 `design_point` 主身份。
3. graph 内部新增信息若无法 lossless export，只能进入 sidecar evidence。
4. v0 中 `seed_template_id` 是 round-trip 的 canonical anchor。

---

## 4. v0 推荐表达内容

### modules
描述：
- 实例 id
- 引用的组件类型
- 在流程中的角色
- placement
- port 定义

### links
描述：
- source / destination
- payload kind
- direction
- bandwidth / latency class

### flows
描述：
- stage sequence
- control dependency
- data dependency
- barrier / overlap semantics

### constraints
描述：
- family-compatible 边界
- host/fpga 分工约束
- resource / placement / fallback 约束

### observability_requirements
描述：
- 哪些 graph-level 现象必须能投影为 runtime_observability
- 哪些瓶颈必须解释

---

## 5. v0 非目标

- 任意 DAG/任意拓扑搜索
- 全细粒度 micro-arch 参数建模
- 直接取代现有 release-facing schema
