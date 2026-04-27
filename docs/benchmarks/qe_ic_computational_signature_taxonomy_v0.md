# QE IC-oriented computational signature taxonomy v0

## 0. Purpose

这份文档把“面向 IC 的 DFT 特化方向”从 narrative label 收紧成 **machine-readable / DSE-usable signature taxonomy**。

目标不是直接把系统切成 `band gap system`、`mobility system` 这类单一应用专机，
而是先把不同器件导向工作负载在 `QE-connected SCF / band-solver shell` 上触发的
**计算签名**冻结下来，供后续：

- case descriptor；
- case-signature matrix；
- overlay phase-config；
- strategy-aware DSE；
- GPU baseline mapping；

统一使用。

## 1. 设计原则

1. **Signature first, slogan second**  
   先定义“会触发哪些计算路径/数据压力/数值敏感点”，再定义应用叙事。
2. **Orthogonal fields only**  
   赝势家族、软件路径敏感性、拓扑、目标物性不能混成一个字段。
3. **Keep the shell object fixed**  
   当前 taxonomy 仍围绕 `QE-connected SCF / band-solver shell`，不直接跳到 EPW/mobility 专线实现。
4. **Descriptor-friendly**  
   每个 taxonomy 维度都必须可落到 JSON/CSV descriptor 中。

## 2. Core taxonomy fields

### 2.1 `property_target`

表示当前 case/experiment 的主要器件导向目标。

| value | meaning |
| --- | --- |
| `band_structure` | 主要用于能带路径/色散分析 |
| `band_gap` | 主要关心价带顶/导带底与 gap 相关量 |
| `effective_mass` | 主要关心 band-edge 周围曲率/局部二阶性质 |
| `transport_proxy` | 当前仍停留在 shell-level / pre-EPW 的输运代理 |

### 2.2 `pseudopotential_family`

只表达赝势家族本身，不表达路径或复杂度判断。

| value | meaning |
| --- | --- |
| `NC` | norm-conserving / NC-light |
| `USPP` | ultrasoft pseudopotential |
| `PAW` | projector augmented-wave |
| `hybrid` | hybrid-functional-sensitive / exact-exchange-sensitive family |

### 2.3 `solver_path_class`

表达 band-solver / shell 主路径的数学/软件路径敏感性。

| value | meaning |
| --- | --- |
| `standard_band` | 标准 band-solver 主线，非明显 generalized-heavy |
| `generalized_overlap` | generalized Hermitian / overlap-sensitive 主线 |
| `hybrid_sensitive` | 受 hybrid / exact-exchange / path switch 影响明显 |
| `post_scf_extension_sensitive` | 当前 shell 对下游 NSCF/DFPT/EPW 扩展敏感 |

### 2.4 `operator_signature`

表达当前 case 在算子与数据流上的主压力来源。

| field | meaning | suggested bucket |
| --- | --- | --- |
| `projector_pressure` | projector / nonlocal apply 压力 | `low / medium / high` |
| `nonlocal_pressure` | 非局域项与 projector state 更新压力 | `low / medium / high` |
| `generalized_ratio_bucket` | generalized overlap/solve 占比 | `low / medium / high` |
| `diag_dominance` | `diag` 在 shell 中的重要程度 | `low / medium / high` |
| `fft_grid_pressure` | FFT/support-grid 压力 | `low / medium / high` |

### 2.5 `workload_topology`

表示材料/器件结构拓扑。

| value | meaning |
| --- | --- |
| `bulk` | 体材料 / bulk semiconductor |
| `2D` | 二维 channel / layered system |
| `slab_interface` | slab / interface / contact-like system |
| `wide_bandgap` | SiC / GaN 等 wide-bandgap system |
| `defect_doped` | defect / doped / impurity-sensitive system |

### 2.6 `post_scf_extension_level`

表示当前 shell case 对下游工作流的关系。

| value | meaning |
| --- | --- |
| `shell_only` | 当前主要是 shell-level case |
| `nscf_extension` | 预期直接延展到 NSCF / band-path |
| `dfpt_expected` | 预期后续进入 DFPT-sensitive 路径 |
| `epw_expected` | 预期后续进入 EPW / mobility-sensitive 路径 |
| `mobility_extension_expected` | 当前 case 主要作为后续 mobility-oriented extension proxy |

## 3. Derived helper fields

下面这些字段不是独立 taxonomy 主轴，但建议在 case-signature map 中保留：

| field | meaning |
| --- | --- |
| `signature_id` | 当前 signature 组合的稳定 id，用于 `best_performance_candidate` |
| `topology_role` | `bringup_proxy / accurate_anchor / coverage_followon / stage_b_nonblocking / stress_aux` |
| `signature_confidence` | `measured / inferred / provisional` |
| `machine_workload_id` | repo 内 machine-readable workload_id |
| `display_label` | 面向文档的人类可读标签 |

## 4. Orthogonality rules

### Rule A
`pseudopotential_family` 不能拿来替代 `solver_path_class`。

### Rule B
`property_target` 不能拿来替代 `post_scf_extension_level`。

### Rule C
`workload_topology` 不能拿来替代 `operator_signature`。

### Rule D
`signature_id` 必须由上面这些正交字段稳定组合生成，而不是手写随意命名。

## 5. Recommended minimal signature tuple

当前阶段建议最少冻结这组字段：

```text
signature_id
property_target
pseudopotential_family
solver_path_class
workload_topology
post_scf_extension_level
projector_pressure
nonlocal_pressure
generalized_ratio_bucket
diag_dominance
fft_grid_pressure
machine_workload_id
display_label
```

## 6. Initial mapping intent

当前阶段的 intent 不是“所有 case 一次性精确标完”，而是：

1. 先对 bring-up closure set 完整标注；
2. 再对 Stage B backlog (`au_slab_subspace`, `sic32_subspace`) 标注；
3. 再让 overlay phase-config 和 DSE 读取这些字段。

## 7. Non-goals

- 不把当前 taxonomy 直接当作 mobility / EPW implementation 计划；
- 不把 taxonomy 当成新的 release gate；
- 不以 taxonomy 替代现有 fairness / correctness / observability contracts；
- 不把 `A/B/C/D` cluster 结构直接写成 taxonomy 结论。
