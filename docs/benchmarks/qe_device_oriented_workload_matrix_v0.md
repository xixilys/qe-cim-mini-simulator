# QE 器件导向 DFT 工作负载矩阵（v0，2026-04-02）

## 0. 目的

这份矩阵用于冻结本项目在 `Task 2` 中采用的代表性 `QE` 工作负载集合。

从 `2026-04-16` 起，这份矩阵不再单独承担“器件导向语义”解释职责；它现在与下面两份新 artifact 联动：

- `docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md`
- `docs/benchmarks/qe_ic_case_signature_matrix_v0.json`

这里不再把“本地最容易运行的小系统”当作主比较对象，而是按照导师给出的方向，把工作负载收口到：

- 面向集成电路器件设计；
- 与迁移率、输运、有效质量、接触/界面、缺陷/掺杂相关；
- 其中需要调用 `DFT / DFPT / band-solver / electron-phonon` 路径的那一部分。

因此，这份矩阵区分三类对象：

1. **Primary device-oriented workloads**：后续必须优先覆盖的主负载；
2. **Local proxy workloads**：当前仓库已有、可用于先做 `SystemC / shell-level` 建模的代理系统；
3. **Excluded / secondary cases**：可做调试或压力测试，但不应主导“器件导向”叙事。

换句话说：

- 本文负责冻结 **case roster / role / bring-up priority**；
- `qe_ic_computational_signature_taxonomy_v0.md` 负责冻结 **signature vocabulary**；
- `qe_ic_case_signature_matrix_v0.json` 负责冻结 **case × signature map**。

## 1. 冻结原则

### 1.1 系统对象

我们比较的系统对象仍然是：

- `QE-connected band-solver subsystem`
- 不是完整 `DFT SoC`
- 也不是单独的 `cdiaghg` 芯片

### 1.2 工作负载选择原则

工作负载矩阵优先覆盖：

- bulk semiconductor transport baseline；
- wide-bandgap semiconductor transport / power-device-relevant baseline；
- metal-semiconductor / slab / interface baseline；
- 2D channel / high-mobility transport baseline；
- projector-heavy 或 basis-heavy 的 stress case。

### 1.3 指标字段

每个 frozen case 至少要能给出：

- `npw`
- projector count / `nkb`
- basis size / `max_subspace_n`
- block size / `max_subspace_m`
- FFT grid
- 迭代结构（`c_bands` 次数、dominant solver、generalized ratio）

## 2. 为什么要按器件导向重排矩阵

当前本地 `QE` case 很适合做系统探索，但其中有些系统更像：

- parser / trace smoke；
- shape / projector stress；
- 子空间路径结构参考；

而不是“器件设计中的主要 DFT 负载”。

如果后续目标是器件设计里的迁移率或相关参数，那么主负载更应该贴近：

- `Si` 类 bulk channel；
- `SiC / GaN` 类 wide-bandgap channel 或 power device 材料；
- `Au slab / metal-semiconductor interface` 类接触问题；
- `graphene / 2D channel` 类二维输运路径。

外部方法参考上，`EPW` 官方文档明确把 `SiC`、`GaN`、`GaN-II` 和输运/mobility tutorial 作为标准教程方向；这说明“迁移率/输运”确实是 `QE/EPW` 生态中的主应用路径，而不是边缘用法：

- `EPW Tutorials`: <https://docs.epw-code.org/doc/Tutorials.html>
- `EPW GaN-II` intrinsic mobility tutorial: <https://docs.epw-code.org/tutorials/GaN-II.html>
- `EPW SiC` tutorial: <https://docs.epw-code.org/doc/SiC.html>
- `EPW transport and mobility school/tutorial material`: <https://docs.epw-code.org/doc/School2024.html>

## 3. 冻结后的 workload matrix

| 类别 | 冻结角色 | 目标器件语义 | 当前代表 case | 当前状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Small semiconductor proxy | Primary | 更小尺度的半导体 bring-up / sanity proxy；目标是 3–4 个 `Si` 原子级别或最小可行周期 Si 单元 | `si4_pbe_uspp_small` | 本地 trace 就绪 | 新增并已实测的 small-Si proxy |
| Bulk Si transport baseline | Primary | CMOS / bulk semiconductor channel；有效质量、band edge、迁移率前置参考 | `si8_pbe_uspp`, `si8_pbe_nc` | 本地 trace 就绪 | 这是当前最稳的 bulk semiconductor 主负载 |
| Wide-bandgap semiconductor baseline | Primary | `SiC / GaN` 类 power device / high-field channel 相关负载 | `SiC32`（本地旧样本）, `GaN`（外部目标） | `SiC32` 需重新整理；`GaN` 需后续采样 | 这是最贴近“器件/迁移率”导师方向的主负载之一 |
| Metal-semiconductor contact / interface | Primary | 接触、电极、slab/interface 相关 DFT 子路径 | `Au slab`（本地旧样本） | 需重新整理 | 这是器件系统里比小分子更相关的表面/界面负载 |
| 2D channel transport baseline | Primary-Secondary | 2D channel / high-mobility transport 路径 | `graphene_pbe_uspp`, `graphene_pbe_paw` | 本地 trace 就绪 | `graphene` 可作为现阶段 2D 输运代理；后续如需要可升级到 `MoS2/WSe2` |
| Projector-heavy stress case | Secondary | 检验 projector / overlap / basis build 的系统压力 | `bn32_pbe_uspp` | 本地 trace 就绪 | 不是主器件叙事，但对架构边界和缓存压力很有价值 |
| Functional / solver-path stress case | Secondary | 检验软件路径变化对系统建模的影响 | `bn32_pbe0_uspp` | 本地 trace 就绪 | 用于比较 `PBE -> PBE0` 时 solver path 是否切换，不作为主器件 case |
| Molecule / toy parser case | Excluded from primary matrix | 调试或 smoke | `benzene`, `h2_tiny` | 本地 trace 就绪 | 可保留做调试与模型 sanity check，但不用于器件导向主结论 |
| Magnetic legacy case | Excluded by default | 仅在自旋/磁器件方向需要时再纳入 | `fe_scf_old` | 旧输出可参考 | 当前器件主线默认不纳入 primary matrix |

## 3.1 显示标签与 machine-readable workload_id 对照

从当前版本开始，文档里的显示标签与后续 machine-readable join key 必须区分：

| display label | machine-readable workload_id | current role |
| --- | --- | --- |
| `Small semiconductor proxy` | `si4_pbe_uspp_small` | Stage-A bring-up proxy |
| `Bulk Si anchor (NC)` | `si8_pbe_nc` | accurate-layer anchor |
| `Bulk Si coverage (USPP)` | `si8_pbe_uspp` | follow-on coverage |
| `2D channel transport proxy` | `graphene_pbe_uspp` | Stage-A bring-up proxy |
| `2D channel PAW coverage` | `graphene_pbe_paw` | signature coverage |
| `Au slab` | `au_slab_subspace` | Stage-B nonblocking signature coverage |
| `SiC32` | `sic32_subspace` | Stage-B nonblocking signature coverage |

这张表的作用是：

1. 防止 `Au slab` / `SiC32` 这类显示标签与后续 artifact join key 脱节；
2. 为 signature-aware DSE、GPU baseline ingest、release-bundle validation 提供一致的 workload_id。

## 4. 当前推荐的最小主矩阵

如果现在必须先冻结一个**最小但 defensible** 的器件导向工作负载矩阵，我建议是：

0. `si4_pbe_uspp_small`
   - 代表更小尺度的半导体 bring-up / sanity workload
   - 当前已经有 ready 输入与 trace
1. `si8_pbe_uspp` 或 `si8_pbe_nc`
   - 代表 bulk semiconductor baseline
2. `graphene_pbe_uspp` 或 `graphene_pbe_paw`
   - 代表 2D channel / transport proxy
3. `Au slab`
   - 代表 contact / surface / interface baseline
4. `SiC32`
   - 代表 wide-bandgap / power-device-relevant baseline
5. `bn32_pbe_uspp`
   - 代表 projector-heavy stress case

这里面：

- `si4_pbe_uspp_small` 是新加入并已实测的小尺度半导体 workload；
- `Si` 与 `graphene` 当前本地 trace 最完整；
- `Au slab` 与 `SiC32` 在本地 handoff 中已被确认存在样本，但需要整理进统一 summary；
- `bn32_pbe_uspp` 不是器件主对象，但对系统压力建模很有价值，适合作为辅助 stress case。

## 4.1 与 signature-driven specialization 的关系

当前版本之后，最小主矩阵还要再按两个阶段解释：

### Stage A — bring-up closure set

先闭合：

- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`
- `si8_pbe_nc`

其中：

- `si4_pbe_uspp_small` 和 `graphene_pbe_uspp` 是 decisive bring-up lanes；
- `si8_pbe_nc` 是 bulk-Si accurate-layer anchor；
- `si8_pbe_uspp` 是 follow-on coverage，不与 `si8_pbe_nc` 混成同一角色。

### Stage B — nonblocking signature coverage

后续再扩到：

- `au_slab_subspace`
- `sic32_subspace`

在当前 release/readiness 规则里，它们先作为 **nonblocking signature coverage**，不自动进入当前 blocking gate。

## 5. 当前可直接用的本地代理数值

下面列出现阶段已整理好的、最能服务于系统建模的本地代理参数。

| case | `npw` | `nkb` | `max_subspace_n` | `max_subspace_m` | FFT grid | dominant solver | generalized ratio |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `si8_pbe_uspp` | 2945 | 144 | 32 | 16 | `36×36×36` | davidson | 0.865 |
| `si8_pbe_nc` | 4553 | 64 | 32 | 16 | `45×45×45` | davidson | 0.894 |
| `si4_pbe_uspp_small` | 1473 | 72 | 16 | 8 | `36×36×18` | davidson | measured-shell-aggregate-ready |
| `graphene_pbe_uspp` | 1105 | 16 | 8 | 4 | `20×20×60` | davidson | 0.767 |
| `graphene_pbe_paw` | 1105 | 16 | 8 | 4 | `20×20×60` | davidson | 0.768 |
| `bn32_pbe_uspp` | 2245 | 256 | 128 | 64 | `60×60×15` | davidson | 0.762 |
| `bn32_pbe0_uspp` | 2245 | 256 | 128 | 64 | `60×60×15` | cg | 0.333 |
| `benzene` | 7412 | 6 | 48 | 24 | `72×72×54` | davidson | 0.923 |

## 6. 冻结结论

因此，`Task 2` 的冻结结论是：

- **主矩阵不再以“小分子/简单系统”为中心**；
- **主矩阵转为器件导向**，以 `Si`、`SiC/GaN`、`Au-slab/interface`、`2D channel` 为核心；
- 当前本地最可立即用于 `SystemC / shell-level` 建模的 ready cases 是：
  - `si4_pbe_uspp_small`
  - `si8_pbe_uspp` / `si8_pbe_nc`
  - `graphene_pbe_uspp` / `graphene_pbe_paw`
  - `bn32_pbe_uspp`（stress）
- 当前需要尽快整理进统一 summary 的器件相关样本是：
  - `Au slab`
  - `SiC32`
- `benzene`、`h2_tiny`、`fe_scf_old` 不作为当前器件导向主比较矩阵的核心 case。

## 7. 对下一步的直接支持

这份矩阵冻结后，下一步 `Task 3` 可以直接基于它定义：

- latency metrics
- traffic metrics
- utilization / stall metrics
- energy-per-episode metrics

也就是说，后续所有 `CPU only / CPU+GPU / CPU+FPGA` 的公平比较，都应首先在这份器件导向矩阵上展开，而不是在 `benzene/h2` 这类简单系统上展开。

从 signature-driven specialization 的角度看，后续推进还应同步读取：

- `docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md`
- `docs/benchmarks/qe_ic_case_signature_matrix_v0.json`
- `docs/benchmarks/qe_ic_full_flow_phase_config_v0.json`

这样后续 DSE 不再只回答：

- 哪个 family 当前最可信

而会进一步回答：

- 对哪一类 `signature_id`
- 哪种 `family + policy + partition_strategy`
- 是更合适的 **best trusted point**
- 哪个又是更激进的 **best performance candidate**
