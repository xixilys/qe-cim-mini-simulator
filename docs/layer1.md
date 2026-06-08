下面是**第一层完整设计手册**，目标是直接指导 Codex 实现。范围只到 **Layer-1：QE-IC workload suite definition**，不做 profiling、不生成架构、不做性能估计。

---

# Layer-1 设计手册：QE-IC Device Workload Suite

## 1. 背景与知识依据

Quantum ESPRESSO 是 DFT / DFPT / plane-wave / pseudopotential 第一性原理材料模拟套件，包含 PWscf、PHonon、PostProc、NEB、CP 等组件，不是单一 `scf` 程序。QE 近年也持续支持 GPU / heterogeneous acceleration，因此 GPU baseline 必须作为后续系统比较对象。([维基百科][1])

EPW 使用 DFPT 和 Wannier interpolation 计算 electron-phonon coupling，并支持 transport、scattering rate、mobility、conductivity 等相关计算；EPW v4 已集成进 Quantum ESPRESSO。([arXiv][2]) Perturbo 也面向 first-principles electron-phonon interaction、charge transport、carrier mobility、conductivity、Seebeck coefficient 等计算，使用 DFT/DFPT 结果和 Wannier interpolation。([arXiv][3]) 2026 年 EPW GPU 工作也说明 electron-phonon / Wannier interpolation 本身已经有强 GPU baseline，因此后续 DSE 必须显式比较 GPU，而不能只比较 CPU/FPGA。([arXiv][4])

---

# 2. Layer-1 的系统定位

Layer-1 负责定义：

```text
我们要加速哪些 IC-device-oriented DFT workloads？
这些 workloads 之间有什么依赖？
每类 workload 预期包含哪些计算 motif？
不同 IC 设计场景下，各 workload 的重要程度如何？
哪些 workflow 第一版暂不纳入？
```

Layer-1 **不负责**：

```text
不做真实 profiling
不生成 GPU / FPGA / GPU+FPGA candidate
不做 cost model
不做 target viability test
不做 promotion decision
不做性能比较
```

Layer-1 的输出必须能被后续层直接消费：

```text
Layer-1: workload suite definition
    ↓
Layer-2: motif profiling
    ↓
Layer-3: GPU / FPGA / GPU+FPGA target viability
    ↓
Layer-4: budgeted promotion policy
```

---

# 3. 核心设计原则

## 3.1 不能做成脚本集合

禁止实现成：

```text
一个脚本生成 JSON
另一个脚本做 validation
逻辑散落在 CLI 中
后续模块靠手动路径拼接读取
```

必须实现成：

```text
稳定 Python package
统一 registry
明确 public API
标准 artifact contract
薄 CLI wrapper
可被后续 DSE pipeline import
```

## 3.2 Suite 不能写死

第一版是 mobility-centered IC device suite，但系统必须支持未来新增：

```text
NEGF
GW / BSE
TDDFT
thermal transport
defect high-throughput
ab initio MD
```

所以设计必须是：

```text
workload family registry
+ motif registry
+ scenario weights
+ validation contract
```

而不是固定五个 case 的硬编码列表。

## 3.3 权重属于 scenario，不属于 workload

同一个 workload 在不同 IC 场景下重要性不同。例如 mobility-centered scenario 中 electron-phonon mobility 权重大；interface-centered scenario 中 defect/interface 权重大。

---

# 4. 推荐代码结构

新增目录：

```text
dse_v2/workloads/qe_ic/
  __init__.py
  schema.py
  registry.py
  suite.py
  validation.py
  artifacts.py
```

新增 CLI：

```text
dse_v2/scripts/dse/build_qe_ic_workload_suite.py
```

新增测试：

```text
dse_v2/tests/test_qe_ic_workload_suite.py
```

各文件职责：

```text
schema.py       定义 schema_version、artifact names、required fields
registry.py     注册 workload families、motifs、scenarios、excluded workflows
suite.py        构建默认 QE-IC workload suite
validation.py   校验 suite contract
artifacts.py    写出 suite / validation / manifest / readme
CLI             只调用 package API，不写核心逻辑
```

---

# 5. Public API 要求

`dse_v2/workloads/qe_ic/__init__.py` 必须导出：

```python
from dse_v2.workloads.qe_ic.suite import build_default_qe_ic_workload_suite
from dse_v2.workloads.qe_ic.validation import validate_qe_ic_workload_suite
from dse_v2.workloads.qe_ic.artifacts import (
    write_qe_ic_workload_suite_artifacts,
    load_qe_ic_workload_suite,
)
```

必须提供 API：

```python
def build_default_qe_ic_workload_suite() -> dict:
    """Build the default QE-IC workload suite contract."""

def validate_qe_ic_workload_suite(suite: Mapping[str, Any]) -> dict:
    """Validate suite structure, registry consistency, dependencies, and scenario weights."""

def write_qe_ic_workload_suite_artifacts(
    out_dir: Path,
    suite: Mapping[str, Any] | None = None,
) -> dict:
    """Write suite, validation, manifest, and README artifacts."""

def load_qe_ic_workload_suite(path: Path) -> dict:
    """Load a persisted suite artifact and validate it fail-closed."""
```

---

# 6. Registry 设计

## 6.1 Motif registry

放在 `registry.py`：

```python
MOTIF_REGISTRY = {
    "fft_transpose": {...},
    "hpsi": {...},
    "projector_nonlocal": {...},
    "dense_linear_algebra": {...},
    "diagonalization": {...},
    "density_update": {...},
    "reduction_collective": {...},
    "wavefunction_memory": {...},
    "q_point_sweep": {...},
    "perturbation_rhs": {...},
    "response_accumulation": {...},
    "dense_kq_interpolation": {...},
    "electron_phonon_matrix": {...},
    "bte_collision_integral": {...},
    "memory_bandwidth": {...},
    "large_data_staging": {...},
    "io_checkpoint": {...},
    "workflow_parameter_sweep": {...},
    "cross_run_reuse": {...},
    "batch_scheduling": {...},
    "large_supercell": {...},
    "localized_state_analysis": {...},
    "potential_alignment": {...},
    "charge_density_analysis": {...},
    "memory_capacity": {...},
}
```

要求：

```text
expected_motifs 中出现的 motif 必须存在于 MOTIF_REGISTRY
允许 future/provisional motif，但必须显式标记 provisional=true
```

---

# 7. Workload family registry

第一版必须包含 5 个 family。

## W1. `ground_state_band_structure`

```python
{
    "family_id": "ground_state_band_structure",
    "family_name": "Ground-state and band-structure",
    "priority": "required",
    "representative_programs": ["pw.x", "bands.x", "dos.x"],
    "depends_on_families": [],
    "device_relevance": [
        "band_structure",
        "effective_mass",
        "wavefunction_generation",
        "density_generation",
        "input_to_phonon_and_transport",
    ],
    "expected_motifs": [
        "fft_transpose",
        "hpsi",
        "projector_nonlocal",
        "dense_linear_algebra",
        "diagonalization",
        "density_update",
        "reduction_collective",
        "wavefunction_memory",
    ],
    "first_version_required": True,
}
```

## W2. `phonon_dfpt`

```python
{
    "family_id": "phonon_dfpt",
    "family_name": "Phonon and DFPT",
    "priority": "required",
    "representative_programs": ["ph.x"],
    "depends_on_families": ["ground_state_band_structure"],
    "device_relevance": [
        "phonon_dispersion",
        "dielectric_response",
        "born_effective_charge",
        "input_to_electron_phonon_transport",
    ],
    "expected_motifs": [
        "q_point_sweep",
        "perturbation_rhs",
        "response_accumulation",
        "fft_transpose",
        "hpsi",
        "small_dense_linear_algebra",
        "reduction_collective",
        "communication",
    ],
    "first_version_required": True,
}
```

## W3. `electron_phonon_mobility`

```python
{
    "family_id": "electron_phonon_mobility",
    "family_name": "Electron-phonon mobility and transport",
    "priority": "primary",
    "representative_programs": ["epw.x", "perturbo"],
    "external_programs": ["perturbo"],
    "depends_on_families": [
        "ground_state_band_structure",
        "phonon_dfpt",
    ],
    "device_relevance": [
        "carrier_mobility",
        "conductivity",
        "phonon_limited_transport",
        "scattering_rate",
    ],
    "expected_motifs": [
        "dense_kq_interpolation",
        "electron_phonon_matrix",
        "bte_collision_integral",
        "dense_linear_algebra",
        "memory_bandwidth",
        "large_data_staging",
        "io_checkpoint",
    ],
    "first_version_required": True,
}
```

注意：`perturbo` 不属于 QE 主发行版。第一版可以把它放入 `external_programs`，作为 transport workload reference。若项目严格限定 QE 生态，应只保留 `epw.x`，并把 Perturbo 标记为 reference external.

## W4. `strain_doping_field_sweep`

```python
{
    "family_id": "strain_doping_field_sweep",
    "family_name": "Strain, doping, field, and operating-condition sweep",
    "priority": "required",
    "representative_programs": ["pw.x", "ph.x", "epw.x"],
    "depends_on_families": [
        "ground_state_band_structure",
        "phonon_dfpt",
        "electron_phonon_mobility",
    ],
    "device_relevance": [
        "strain_effect",
        "carrier_concentration_dependence",
        "electric_field_dependence",
        "temperature_dependence",
        "channel_orientation_sweep",
    ],
    "expected_motifs": [
        "workflow_parameter_sweep",
        "repeated_runs",
        "cross_run_reuse",
        "batch_scheduling",
        "incremental_update",
    ],
    "first_version_required": True,
}
```

## W5. `interface_band_offset_defect`

```python
{
    "family_id": "interface_band_offset_defect",
    "family_name": "Interface, band-offset, and defect",
    "priority": "required",
    "representative_programs": ["pw.x", "pp.x", "projwfc.x"],
    "depends_on_families": ["ground_state_band_structure"],
    "device_relevance": [
        "semiconductor_oxide_interface",
        "high_k_interface",
        "metal_semiconductor_contact",
        "band_offset",
        "defect_trap_level",
        "formation_energy",
    ],
    "expected_motifs": [
        "large_supercell",
        "repeated_ground_state_solve",
        "localized_state_analysis",
        "potential_alignment",
        "charge_density_analysis",
        "memory_capacity",
        "parameter_sweep",
    ],
    "first_version_required": True,
}
```

---

# 8. Scenario registry

## Scenario A：`mobility_centered_ic_device`

默认主场景。

```python
{
    "scenario_id": "mobility_centered_ic_device",
    "description": "IC device workload distribution centered on carrier mobility and electron-phonon transport.",
    "weights": {
        "ground_state_band_structure": 0.20,
        "phonon_dfpt": 0.20,
        "electron_phonon_mobility": 0.35,
        "strain_doping_field_sweep": 0.15,
        "interface_band_offset_defect": 0.10,
    },
}
```

## Scenario B：`interface_centered_ic_device`

扩展场景。

```python
{
    "scenario_id": "interface_centered_ic_device",
    "description": "IC device workload distribution centered on interfaces, band offsets, and defects.",
    "weights": {
        "ground_state_band_structure": 0.20,
        "phonon_dfpt": 0.10,
        "electron_phonon_mobility": 0.20,
        "strain_doping_field_sweep": 0.15,
        "interface_band_offset_defect": 0.35,
    },
}
```

要求：

```text
每个 scenario 的 weights sum 必须等于 1.0
所有 weights key 必须对应已注册 workload family
primary_scenario_id 必须存在
```

---

# 9. Excluded workflow registry

第一版必须显式记录未纳入项：

```python
EXCLUDED_WORKFLOW_REGISTRY = [
    {
        "workflow": "NEB",
        "reason": "deferred; image-level scheduling is a separate system-level problem",
    },
    {
        "workflow": "CP_MD",
        "reason": "deferred; time-step stability and trajectory validation increase scope",
    },
    {
        "workflow": "GW_BSE",
        "reason": "deferred; many-body and optical workflows are outside mobility-centered v1",
    },
    {
        "workflow": "TDDFT",
        "reason": "deferred; time-propagation motifs require separate modeling",
    },
    {
        "workflow": "NEGF",
        "reason": "deferred; device-level quantum transport may require a non-QE software stack",
    },
]
```

---

# 10. Suite artifact schema

输出文件：

```text
qe_ic_workload_suite.json
```

顶层结构：

```json
{
  "schema_version": "dse.qe_ic.workload_suite.v1",
  "suite_id": "qe_ic_device_suite_v1",
  "suite_scope": "IC-device-oriented DFT workload suite",
  "primary_scenario_id": "mobility_centered_ic_device",
  "workload_families": [],
  "scenarios": [],
  "motif_registry": {},
  "excluded_workflows": [],
  "downstream_contract": {
    "next_layer": "motif_profiling",
    "required_consumers": [
      "layer2_motif_profiling",
      "layer3_target_viability_test",
      "promotion_policy"
    ]
  },
  "claim_boundary": "This artifact defines workload scope only. It does not contain profiling results, architecture candidates, performance estimates, target viability results, or promotion decisions."
}
```

每个 workload family 必须包含 `profiling_contract`：

```json
{
  "profiling_contract": {
    "required_next_layer": "motif_profiling",
    "expected_profile_fields": [
      "runtime_breakdown",
      "op_mix",
      "memory_movement",
      "communication_pattern",
      "parallel_axes",
      "reuse_opportunities",
      "gpu_baseline_required"
    ],
    "gpu_baseline_required": true
  }
}
```

---

# 11. Manifest artifact schema

输出文件：

```text
qe_ic_workload_suite_manifest.json
```

结构：

```json
{
  "schema_version": "dse.qe_ic.workload_suite_manifest.v1",
  "artifact_role": "dse_layer1_workload_suite",
  "suite_artifact": "qe_ic_workload_suite.json",
  "validation_artifact": "qe_ic_workload_suite_validation.json",
  "readme_artifact": "qe_ic_workload_suite_readme.md",
  "producer": "dse_v2.workloads.qe_ic",
  "layer": "layer1_workload_suite_definition",
  "downstream_consumers": [
    "layer2_motif_profiling",
    "layer3_target_viability_test",
    "promotion_policy"
  ],
  "claim_boundary": "This manifest registers Layer-1 workload-suite artifacts only. It is not profiling, architecture generation, performance estimation, target viability, or validation evidence."
}
```

---

# 12. Validation artifact schema

输出文件：

```text
qe_ic_workload_suite_validation.json
```

成功示例：

```json
{
  "schema_version": "dse.qe_ic.workload_suite_validation.v1",
  "status": "passed",
  "errors": [],
  "warnings": [],
  "family_count": 5,
  "scenario_count": 2,
  "motif_count": 0,
  "excluded_workflow_count": 5
}
```

必须检查：

```text
schema_version 正确
suite_id 正确
primary_scenario_id 存在
必须包含五个 first_version_required workload families
family_id 唯一
depends_on_families 全部存在
expected_motifs 非空
expected_motifs 均在 MOTIF_REGISTRY 中
device_relevance 非空
scenario weights sum == 1.0
scenario weights 只引用已存在 family
excluded_workflows 非空
每个 excluded workflow 有 reason
每个 family 有 profiling_contract
claim_boundary 明确说明不包含 profiling / architecture / performance / viability / promotion
manifest 引用的 artifact 名称一致
```

失败时：

```json
{
  "schema_version": "dse.qe_ic.workload_suite_validation.v1",
  "status": "failed",
  "errors": [
    {
      "field": "scenarios[0].weights",
      "message": "scenario weights must sum to 1.0"
    }
  ],
  "warnings": []
}
```

---

# 13. README artifact 要求

输出文件：

```text
qe_ic_workload_suite_readme.md
```

必须包含：

```text
1. suite 目标
2. 为什么面向 IC device
3. 为什么 mobility 是主场景
4. 五类 workload family 简述
5. scenario weights 的含义
6. 暂不纳入 workflow 的理由
7. 与下一层 motif profiling 的接口
8. 明确声明本层不做性能判断
```

---

# 14. CLI 要求

新增：

```text
dse_v2/scripts/dse/build_qe_ic_workload_suite.py
```

用法：

```bash
python3 dse_v2/scripts/dse/build_qe_ic_workload_suite.py \
  --out artifacts/qe_ic_workload_suite
```

CLI 必须是薄封装，不允许内联 registry。

伪代码：

```python
def main() -> int:
    args = parse_args()
    result = write_qe_ic_workload_suite_artifacts(Path(args.out))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1
```

stdout 成功格式：

```json
{
  "status": "passed",
  "out_dir": "artifacts/qe_ic_workload_suite",
  "artifacts": [
    "qe_ic_workload_suite.json",
    "qe_ic_workload_suite_validation.json",
    "qe_ic_workload_suite_manifest.json",
    "qe_ic_workload_suite_readme.md"
  ]
}
```

---

# 15. 测试要求

新增：

```text
dse_v2/tests/test_qe_ic_workload_suite.py
```

必须包含：

```text
test_public_api_exports_expected_functions
test_registry_contains_required_families
test_suite_contains_required_families
test_family_ids_are_unique
test_family_dependencies_are_valid
test_expected_motifs_are_registered
test_each_family_has_device_relevance
test_each_family_has_profiling_contract
test_primary_scenario_exists
test_scenario_weights_sum_to_one
test_scenario_weights_reference_known_families
test_excluded_workflows_have_reasons
test_validation_passes_default_suite
test_writer_emits_required_artifacts
test_manifest_declares_downstream_consumers
test_artifacts_are_consistent_with_manifest
test_suite_can_be_loaded_and_revalidated
test_cli_emits_passed_status
test_core_logic_not_in_cli
test_claim_boundary_blocks_profiling_architecture_performance_viability_promotion
```

`test_core_logic_not_in_cli` 至少检查：

```text
CLI imports dse_v2.workloads.qe_ic
CLI 文件中不定义 WORKLOAD_FAMILY_REGISTRY
CLI 文件中不定义 SCENARIO_REGISTRY
CLI 文件中不定义 MOTIF_REGISTRY
```

---

# 16. Codex 完成标准

运行：

```bash
pytest dse_v2/tests/test_qe_ic_workload_suite.py
```

必须通过。

并且 CLI 能生成：

```text
artifacts/qe_ic_workload_suite/qe_ic_workload_suite.json
artifacts/qe_ic_workload_suite/qe_ic_workload_suite_validation.json
artifacts/qe_ic_workload_suite/qe_ic_workload_suite_manifest.json
artifacts/qe_ic_workload_suite/qe_ic_workload_suite_readme.md
```

并且其他模块可以直接 import：

```python
from dse_v2.workloads.qe_ic import build_default_qe_ic_workload_suite

suite = build_default_qe_ic_workload_suite()
```

---

# 17. Layer-1 最终定义

Layer-1 的最终定义是：

> `QE-IC-Device-Suite-v1` 是面向集成电路器件 DFT 计算的 workload-suite registry。它以 carrier mobility / electron-phonon transport 为主场景，同时覆盖 ground-state electronic structure、phonon/DFPT、strain/doping/field sweep、interface/band-offset/defect 等相关负载。它只定义系统级 DSE 的 workload scope、family dependency、expected motifs、scenario weights 和 excluded workflows，不执行 profiling、不生成架构、不做 target viability 或 promotion。

[1]: https://en.wikipedia.org/wiki/Quantum_ESPRESSO?utm_source=chatgpt.com "Quantum ESPRESSO"
[2]: https://arxiv.org/abs/1604.03525?utm_source=chatgpt.com "EPW: Electron-phonon coupling, transport and superconducting properties using maximally localized Wannier functions"
[3]: https://arxiv.org/abs/2002.02045?utm_source=chatgpt.com "Perturbo: a software package for ab initio electron-phonon interactions, charge transport and ultrafast dynamics"
[4]: https://arxiv.org/abs/2603.10295?utm_source=chatgpt.com "Electron-phonon physics at the exascale: A hybrid MPI-GPU-OpenMP framework for scalable Wannier interpolation"
