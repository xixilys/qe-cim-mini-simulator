# DSE v2 实现入口

`dse_v2/` 是 Generic DSE 框架的当前 Python 实现目录。全局设计请先读 `docs/architecture/generic_dse_global_system_design_v0.md`，本文件只说明代码入口、运行命令和测试命令。

## 1. 定位

DSE v2 负责把不同 workload adapter 生成的 `WorkloadPackage` / `ComputeGraph` 送入架构映射、SystemC/gem5+SystemC 证据流程和最终报告。QE 仅作为 `dft_qe` reference adapter，不是 core schema。

```text
workload adapter
    -> WorkloadPackage / ComputeGraph
    -> Step2 architecture + mapping artifacts
    -> Step3 simulation evidence
    -> final report + claim validation
```

## 2. 主要目录

| 目录 | 职责 |
| --- | --- |
| `core/workload/` | workload adapter、workflow metadata、package 和 graph lowering。 |
| `core/ir/` | `ComputeGraph`、execution timeline 等中间表示。 |
| `mapping/` | Step2 architecture/mapping workflow、search 和 promotion artifacts。 |
| `backends/` | SystemC、generic SystemC bridge、gem5+SystemC adapter。 |
| `evidence/` | Step3 workflow、full-flow evidence bundle 和 proof gate。 |
| `reporting/` | final report 和 claim validation。 |
| `registry/` | experiment registry、campaign 和 trial ledger。 |
| `scripts/dse/` | full-flow pilot 和端到端入口脚本。 |
| `tests/` | 回归测试。 |

## 3. 常用命令

### Workload adapter 回归

```bash
python3 -m pytest -q dse_v2/tests/test_workload_adapter_registry.py dse_v2/tests/test_workload_workflows.py
```

### Step2/Step3 回归

```bash
python3 -m pytest -q \
  dse_v2/tests/test_step2_architecture_mapping_workflow.py \
  dse_v2/tests/test_step3_cross_step_workflow.py
```

### Full-flow pilot

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j4
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --workload qe_scf_shell \
  --backend systemc \
  --out runs/dse/qe_scf_shell_systemc
```

### 全量 DSE v2 测试

```bash
python3 -m pytest -q dse_v2/tests
```

## 4. 报告与 claim 边界

Full-flow pilot 会生成 `manifest.json`、`verdict.json`、`final_report.json`、`final_report.md` 和 `claim_validation.json` 等 artifacts。单个 pilot 只能作为 feasibility 或 timing evidence，不能直接声称最终 best architecture 或 Pareto frontier。

详细报告规则见：

- `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md`
- `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`

## 5. 非目标

- 本目录不是全局设计文档。
- 本目录不定义 adjudicator authority。
- QE 相关代码不得回流为 core IR 必需字段。
- optimizer/search 不得绕过 evidence 和 claim gate。
