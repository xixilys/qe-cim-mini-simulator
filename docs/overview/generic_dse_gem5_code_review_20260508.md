# Generic DSE / GenericAccel 代码审核报告（2026-05-08）

## 0. 结论

**审核结论：REQUEST CHANGES**

**Architectural Status：BLOCK**

当前实现可以作为 scaffold / prototype 继续推进，但还不能支撑以下完成态表述：

- “通用 DSE 框架全部完成”；
- “Generic SystemC 后端已能有效区分 GPU / FPGA / CIM 架构点”；
- “gem5 GenericAccel 设备模型已经完成端到端 smoke”；
- “L3 / SystemC fidelity 已经是通用后端主路径”。

主要阻塞点：

1. gem5 smoke 配置当前无法运行，GenericAccel PIO 端口连接方向错误。
2. `model/generic_sim_backend` 的 C++ JSON parser 没有正确解析 accelerators / edges / capabilities，导致 L3 后端实际不消费架构差异。
3. DSE evaluator 返回类型从 `EvaluationResult` 变成 `dict`，导致既有集成测试失败。
4. 多个性能模型存在单位错误，会让 DSE ranking 或 L3 timing 失真。
5. GenericAccel 文档描述的 DMA / descriptor / TLM bridge 与当前 C++ 实现不一致，当前仍是 fixed 1-GFLOP timed stub。

---

## 1. 审核范围

本次审核覆盖用户汇报中的三条主线：

### 1.1 gem5 GenericAccel

相关路径：

- `gem5_integration/src/dev/generic_accel/`
- `gem5_integration/gem5/src/dev/generic_accel/`（本地 ignored gem5 源码树中的实际编译副本）
- `gem5_integration/gem5/src/dev/SConscript`
- `gem5_integration/configs/generic_accel_smoke_test.py`

### 1.2 dse_v2 通用 DSE 框架

相关路径：

- `dse_v2/core/ir/compute_graph.py`
- `dse_v2/core/ir/dft_workload.py`
- `dse_v2/core/ir/task_graph.py`
- `dse_v2/core/ir/execution.py`
- `dse_v2/core/architecture/accelerator.py`
- `dse_v2/dse/orchestrator.py`
- `dse_v2/dse/analytical_evaluator.py`
- `dse_v2/dse/multi_fidelity.py`
- `dse_v2/dse/systemc_evaluator.py`
- `dse_v2/dse/tlm_evaluator.py`
- `dse_v2/tests/`

### 1.3 通用 SystemC 后端

相关路径：

- `model/generic_sim_backend/`
- `dse_v2/backends/generic_systemc_bridge.py`
- `dse_v2/tests/test_generic_systemc_backend.py`

---

## 2. 验证命令与结果

### 2.1 Generic SystemC 后端构建

命令：

```bash
cmake --build model/generic_sim_backend/build -j4
```

结果：

```text
[100%] Built target generic_sim
```

状态：**通过**。

### 2.2 Generic SystemC bridge 局部测试

命令：

```bash
python3 dse_v2/tests/test_generic_systemc_backend.py
```

结果：

```text
All tests passed!
```

状态：**通过**，但测试主要覆盖 request builder 和 executable missing error path，没有覆盖 C++ parser 是否真实消费 accelerators / edges / capabilities。

### 2.3 dse_v2 全量测试

命令：

```bash
python3 -m pytest -q dse_v2/tests
```

结果：

```text
2 failed, 27 passed, 3 warnings
```

失败点：

```text
dse_v2/tests/test_integration.py::test_dse
AttributeError: 'dict' object has no attribute 'latency_ms'

dse_v2/tests/test_integration.py::test_end_to_end
AttributeError: 'dict' object has no attribute 'latency_ms'
```

状态：**失败**。

### 2.4 gem5 GenericAccel smoke

命令：

```bash
gem5_integration/gem5/build/X86/gem5.opt \
  gem5_integration/configs/generic_accel_smoke_test.py
```

结果：

```text
fatal: Ports <orphan System>.generic_accel.pio and <orphan System>.membus.cpu_side_ports[4]
with roles 'GEM5 RESPONDER' and 'GEM5 RESPONDER' are not compatible
```

状态：**失败**。

### 2.5 Generic SystemC 后端架构区分能力 probe

手动 probe：同一个 workload 分别映射到 GPU / FPGA / CIM。

结果：

```text
gpu  5.01376  12  0  0
fpga 5.01376  12  0  0
cim  5.01376  12  0  0
```

含义：三个 accelerator 得到完全相同 latency / throughput / power / data movement，说明当前 L3 generic backend 没有真实消费 accelerator capability 或 mapping 差异。

---

## 3. HIGH 问题

### HIGH-1：gem5 smoke config 当前无法运行

位置：

- `gem5_integration/configs/generic_accel_smoke_test.py:32-35`

当前代码：

```python
generic_accel = GenericAccel()
generic_accel.pio_addr = 0x100000000
system.generic_accel = generic_accel
system.generic_accel.pio = system.membus.cpu_side_ports
```

实际错误：

```text
Ports ... generic_accel.pio and ... membus.cpu_side_ports ...
with roles 'GEM5 RESPONDER' and 'GEM5 RESPONDER' are not compatible
```

风险：

- 只能证明 `build/X86/gem5.opt` 编译成功；
- 不能证明 GenericAccel 可以被 gem5 config 实例化并执行 MMIO smoke；
- 不能作为 gem5 GenericAccel 设备模型完成证据。

建议：

- 修正 PIO 端口方向，通常需要接到 `membus.mem_side_ports` 或通过合适 IO bridge；
- 增加最小 MMIO read smoke，例如读 `REG_VERSION` 和 `REG_CAPABILITIES`；
- 将 smoke 命令纳入可重复验证文档。

---

### HIGH-2：Generic SystemC C++ 后端没有解析 accelerators / edges / capabilities

位置：

- `model/generic_sim_backend/src/json_parser.cpp:76-84`
- `model/generic_sim_backend/src/graph_executor.cpp:128-132`

问题：

`JsonParser::parse_request()` 目前只解析了 host 的部分字段，没有解析：

- `architecture.accelerators`
- accelerator `capabilities`
- accelerator `power`
- `architecture.interconnect`
- workload `edges`
- edge `tensor_shape`

后果：

`GraphExecutor` 中：

```cpp
const AcceleratorDesc* accel = find_accelerator(accel_id);
if (!accel) {
    accel_id = "host";
    accel = nullptr;
}
```

由于 `req_.architecture.accelerators` 为空，所有 mapped node 都 fallback 到 host。

风险：

- L3 / Generic SystemC 后端无法用于 DSE 排名；
- GPU / FPGA / CIM 的性能、功耗、capability 差异被完全忽略；
- output 中 `power_w = 0`、`resource_utilization = {}`、`events = []` 这类结果会误导报告。

建议：

- 使用可靠 JSON parser；如果坚持无依赖，至少实现 schema-bound object/array parser；
- 增加 regression test：同一 workload 在 GPU / FPGA / CIM 上必须产生不同 latency / power；
- 增加 parser test，检查 `req.architecture.accelerators.size() > 0`、`req.workload.edges.size() > 0`。

---

### HIGH-3：C++ JSON node parser 会把字段名误解析为 node id

位置：

- `model/generic_sim_backend/src/json_parser.cpp:58-72`

当前逻辑扫描 `nodes_str` 中所有引号：

```cpp
while ((pos = nodes_str.find("\"", pos)) != std::string::npos) {
    size_t id_end = nodes_str.find("\"", pos + 1);
    std::string node_id = nodes_str.substr(pos + 1, id_end - pos - 1);
    ...
    req.workload.nodes[node_id] = node;
}
```

这会把以下字段名也当作 node id：

- `op_type`
- `inputs`
- `outputs`
- `estimated_flops`
- `estimated_memory_bytes`
- `attributes`

风险：

- workload graph 中会出现伪节点；
- topological sort / metrics 可能基于错误 graph；
- 当前 probe 的 5.01376ms 很可能来自错误解析后的字段节点，而不是原始 4-node graph。

建议：

- 不要用全局字符串扫描解析 JSON 对象；
- 至少先解析 `nodes` object 的顶层 key，再解析每个 node object 的字段；
- 加一个 fixture request，断言 C++ 解析出的 node 数量等于 Python request 中 node 数量。

---

### HIGH-4：DSE evaluator 返回类型回归，导致既有集成测试失败

位置：

- `dse_v2/dse/orchestrator.py:216-227`
- `dse_v2/dse/analytical_evaluator.py:301-312`
- `dse_v2/tests/test_integration.py:111`
- `dse_v2/tests/test_integration.py:144`

问题：

`Evaluator.evaluate()` 和原 `AnalyticalEvaluator.evaluate()` 的返回契约是 `EvaluationResult`，但新的 `EnhancedAnalyticalEvaluator.evaluate()` 返回 `dict`。

失败：

```text
AttributeError: 'dict' object has no attribute 'latency_ms'
```

风险：

- `DSEOrchestrator.results` 类型不稳定；
- 调用者必须到处判断 `dict` vs dataclass；
- Pareto / get_best_design 已开始混合处理两套类型，维护成本上升。

建议：

二选一统一：

1. 保持 `EvaluationResult` dataclass 作为标准返回类型；或
2. 全面迁移为 dict，并同步修改 type hints、tests、report 脚本、downstream caller。

不建议长期混用。

---

### HIGH-5：GenericSystemCBridge 中 peak_gops 单位多乘了 1000

位置：

- `dse_v2/backends/generic_systemc_bridge.py:151-155`

当前代码：

```python
peak_gflops = accel.compute.get_peak_flops("FP64") / 1e9
accel_desc["capabilities"][op_type] = {
    "peak_gops": peak_gflops * 1000,
    "efficiency": efficiency,
}
```

如果 `get_peak_flops()` 单位是 FLOP/s，那么 GOPS 应该是：

```python
peak_gops = peak_flops / 1e9
```

风险：

- A100 FP64 会从约 `9700 GOPS` 被写成 `9,700,000 GOPS`；
- 一旦 C++ parser 修好，L3 latency 会被低估约 1000 倍；
- DSE ranking 会强烈偏向错误计算。

建议：

- 修正单位；
- 在 request builder test 中断言 A100 FP64 `peak_gops` 约为 `9700`，不是 `9700000`。

---

### HIGH-6：Analytical DSE 数据搬运时间单位错误

位置：

- `dse_v2/core/ir/task_graph.py:73-75`

当前代码：

```python
return (self.size_bytes * 8.0 / max(self.bandwidth_gbps, 1.0)) / 1000.0 + self.latency_ms
```

若 `bandwidth_gbps` 表示 Gbit/s，正确换算应考虑 `1e9 bit/s` 和 `1000 ms/s`。例如 1MB @ 64Gb/s 约为 0.131ms。当前公式会得到约 131ms，偏大约 1000 倍。

风险：

- multi-accelerator design point 被过度惩罚；
- Pareto frontier 和 best design 失真；
- “data movement aware” 的结论不可信。

建议：

使用明确单位公式，例如：

```python
transfer_ms = self.size_bytes * 8.0 / (self.bandwidth_gbps * 1e9) * 1000.0
return transfer_ms + self.latency_ms
```

并增加单元测试：1MiB @ 64Gb/s 应约 0.131ms，加上 latency 后在合理范围。

---

### HIGH-7：MultiFidelityEvaluator 的 L3 仍使用 QE-specific SystemCEvaluator

位置：

- `dse_v2/dse/multi_fidelity.py:21-23`
- `dse_v2/dse/multi_fidelity.py:36-39`
- `dse_v2/dse/systemc_evaluator.py:101-109`

问题：

`MultiFidelityEvaluator(enable_systemc=True)` 目前 L3 路径是：

```python
from dse_v2.dse.systemc_evaluator import SystemCEvaluator
self.l3_evaluator = SystemCEvaluator() if enable_systemc else None
```

但 `SystemCEvaluator` hardcode QEBS 环境变量：

```python
QEBS_ARCH_FAMILY = F4
QEBS_NPW / QEBS_NKB / QEBS_M
QEBS_MAPPING_OPERATOR_SWEEP
QEBS_MAPPING_REDUCED_BUILD
QEBS_MAPPING_DIAG
QEBS_MAPPING_REFRESH
```

风险：

- 多保真度框架中的 L3 不是通用后端；
- “通用 SystemC 后端完成”与实际调用路径不一致；
- 报告中的 L3 fidelity comparison 可能混用 QE-specific 和 Generic backend 结果。

建议：

- 为 `MultiFidelityEvaluator` 增加 L3 backend injection；
- 或默认 L3 使用 `GenericSystemCBackend`，QE-specific backend 作为显式选项；
- 输出中明确 `backend_name` 和 `backend_contract`，避免把两套 L3 混成一个 fidelity。

---

## 4. MEDIUM 问题

### MEDIUM-1：GenericAccel 文档/实现不一致，当前仍是 timed stub

位置：

- `gem5_integration/src/dev/generic_accel/README.md`
- `gem5_integration/src/dev/generic_accel/generic_mmio_protocol.md`
- `gem5_integration/src/dev/generic_accel/generic_accel.cc:127-154`

文档描述：

- DMA engine
- command descriptor
- completion descriptor
- result JSON
- TLM-2.0 bridge
- SystemC Generic Backend

实现实际：

- 不读取 command descriptor；
- 不读取 guest memory；
- 不解析 request JSON；
- 不写 result JSON；
- 不实现 DMA；
- 不实现 interrupt；
- 固定 `flops = 1e9`；
- 固定 `opType = 1`。

风险：

- 文档容易造成 overclaim；
- 后续汇报中容易把 scaffold 当成可执行 bridge。

建议：

- README 明确标注当前实现为 `MMIO timed stub`；
- 把 DMA / descriptor / TLM 标注为 planned 或 TODO；
- 完成 descriptor 读取前，不应称为完整 command queue。

---

### MEDIUM-2：GenericAccel metric register 64-bit 读写与 offset 布局冲突

位置：

- `gem5_integration/src/dev/generic_accel/generic_accel.hh:32-33`
- `gem5_integration/src/dev/generic_accel/generic_accel.cc:66-70`

当前定义：

```cpp
static constexpr Addr REG_METRIC_CYCLES = 0x4000;
static constexpr Addr REG_METRIC_OPS = 0x4004;
```

但读时：

```cpp
pkt->setLE<uint64_t>(metric_cycles);
pkt->setLE<uint64_t>(metric_ops);
```

风险：

- 两个 64-bit register 在地址空间上重叠；
- 如果 guest 用 32-bit MMIO 访问，行为不明确；
- 与 protocol 文档中的 32-bit offset 表不一致。

建议：

- 改成 `CYCLES_LO / CYCLES_HI`、`OPS_LO / OPS_HI`；或
- 调整 offset 为 0x4000 / 0x4008 并要求 64-bit MMIO；
- 同步更新 `generic_mmio_protocol.md`。

---

### MEDIUM-3：tracked scaffold 与实际编译进入 gem5 的 ignored tree 不一致

位置：

- tracked scaffold：`gem5_integration/src/dev/generic_accel/`
- actual compiled copy：`gem5_integration/gem5/src/dev/generic_accel/`

差异示例：

- tracked `GenericAccel.py` 继承 `SimObject`；
- ignored gem5 tree 中 `GenericAccel.py` 继承 `BasicPioDevice`。

风险：

- 当前机器上能编译，不等于 repo checkout 后可复现；
- review / commit 时可能只提交 scaffold，不提交真正工作版本；
- 后续 agent 可能修改错目录。

建议：

- 保留一个 tracked patch 或 sync script，把 `gem5_integration/src/dev/generic_accel/` 同步到 vendored gem5 tree；
- 或明确把 `gem5_integration/src/dev/generic_accel/` 作为 source-of-truth，并让 build process 从那里复制；
- 保证 tracked 文件与实际编译文件一致。

---

### MEDIUM-4：`model/generic_sim_backend/build/` 未被 `.gitignore` 覆盖

位置：

- `model/generic_sim_backend/build/`
- `.gitignore`

当前 `.gitignore` 已覆盖：

```text
model/ozaki_subspace_model/build/
model/qe_band_solver_model/build/
gem5_integration/systemc_model/build/
```

但未覆盖：

```text
model/generic_sim_backend/build/
```

风险：

- CMakeCache、Makefile、binary 等 build artifact 可能被误提交；
- 影响跨机器复现。

建议添加：

```gitignore
model/generic_sim_backend/build/
```

---

## 5. LOW / 风格与维护性建议

### LOW-1：报告型脚本放在 `tests/` 下但没有断言核心正确性

位置：

- `dse_v2/tests/test_dft_report.py`
- `dse_v2/tests/test_complete_dse_report.py`

这些文件更像 demo/report generator，而不是 pytest-style unit test。建议：

- 如果作为 demo，移动到 `dse_v2/scripts/analysis/` 或 `dse_v2/docs/`；
- 如果作为 test，加入 assertions，例如 L1/L2/L3 输出必须满足 schema、latency > 0、power 非负、backend 名称明确。

### LOW-2：`GraphExecutor` 输出没有序列化 events/resource utilization

位置：

- `model/generic_sim_backend/src/json_parser.cpp:128-153`

`SimulationResult` 中有 `events` 和 `resource_utilization`，但 `serialize_result()` 没写出这些字段。建议补齐，否则 Python 端的 `simulation_details.events` 永远为空。

---

## 6. 建议修复顺序

### Phase 1：先恢复测试与单位正确性

1. 统一 evaluator 返回类型：`EvaluationResult` 或 dict 二选一。
2. 修复 `dse_v2/core/ir/task_graph.py` 数据搬运时间单位。
3. 修复 `dse_v2/backends/generic_systemc_bridge.py` 的 `peak_gops` 单位。
4. 跑：

```bash
python3 -m pytest -q dse_v2/tests
```

目标：全量通过，且无 `dict` / dataclass contract 漂移。

### Phase 2：让 Generic SystemC 后端成为有效 L3

1. 替换或修复 C++ JSON parser。
2. 解析 accelerators / capabilities / edges / interconnect。
3. 输出 events / resource utilization / device_time / dma_time。
4. 增加 regression：GPU / FPGA / CIM 同 workload 结果必须不同。
5. 跑：

```bash
cmake --build model/generic_sim_backend/build -j4
python3 dse_v2/tests/test_generic_systemc_backend.py
```

### Phase 3：修复 gem5 GenericAccel smoke

1. 修正 PIO 端口连接。
2. 增加 MMIO read/write smoke。
3. 明确 GenericAccel 当前是 stub 还是 descriptor-backed device。
4. 跑：

```bash
gem5_integration/gem5/build/X86/gem5.opt \
  gem5_integration/configs/generic_accel_smoke_test.py
```

### Phase 4：文档与可复现性

1. 同步 tracked scaffold 与 ignored gem5 tree。
2. 增加 `model/generic_sim_backend/build/` 到 `.gitignore`。
3. 更新 README，避免把 planned DMA/TLM/descriptor 写成已完成。

---

## 7. 当前可安全表述的进展

建议当前汇报口径改为：

- gem5 GenericAccel：**已完成可编译 MMIO timed-stub 设备模型雏形；gem5.opt 编译通过；smoke config 仍需修复端口连接和 MMIO 验证。**
- dse_v2：**已形成分层 IR / accelerator description / multi-fidelity scaffold；但 evaluator 返回契约和单位问题需修复，全量测试当前 2 项失败。**
- Generic SystemC backend：**C++ executable 与 Python bridge 已能构建/调用；但 C++ request parser 尚未正确解析 accelerators / graph edges，因此当前不能作为有效架构排名后端。**

不建议当前说：

- “通用 DSE 框架全部完成”；
- “Generic SystemC 后端完成”；
- “gem5 + GenericAccel 已通过 smoke”；
- “L3 能支持 GPU / FPGA / CIM 可比评估”。

---

## 8. 审核产生的关键文件路径

本报告文件：

```text
/mnt/f/phd/year_2/project/dft_accelerate/docs/overview/generic_dse_gem5_code_review_20260508.md
```

报告目录：

```text
/mnt/f/phd/year_2/project/dft_accelerate/docs/overview/
```
