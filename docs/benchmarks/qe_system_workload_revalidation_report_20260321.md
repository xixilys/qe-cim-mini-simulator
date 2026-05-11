# QE 系统级 Workload 复核与定量报告

## 0. 证据范围与说明

这份报告只使用本轮 **重新运行的小体系 QE 真实路径** 作为主证据，不直接复述旧 benchmark 结论。

本轮使用的自动化脚本与汇总产物如下：

- 运行脚本：
  - [`run_qe_workload_matrix.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/run_qe_workload_matrix.py)
- 分析脚本：
  - [`analyze_qe_workload_revalidation.py`](/Volumes/remote/phd/year_2/project/dft加速/tools/benchmarks/analyze_qe_workload_revalidation.py)
- 原始结果根目录：
  - [`qe_workload_revalidation`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation)
- 自动汇总表：
  - [`summary_tables.md`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/summary_tables.md)
  - [`summary.json`](/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/results/qe_workload_revalidation/summary.json)

本轮覆盖到的关键维度：

- `Gamma + real + molecule`: `h2_tiny`
- `k-point + complex + periodic`: `graphene_pbe_paw` / `graphene_pbe_uspp`
- `USPP`: `h2_tiny`, `si8_pbe_uspp`, `bn32_*`
- `PAW`: `graphene_pbe_paw`
- `NC`: `si8_pbe_nc`
- `PBE0`: `si8_pbe0_uspp`, `bn32_pbe0_uspp`
- `>10 atoms`: `benzene`（部分完成）, `bn32_*`
- `~32 atoms`: `bn32_pbe_uspp`, `bn32_pbe0_uspp`

注意两点：

1. `benzene` 轻量输入在第 4 个 SCF iteration 进入 Davidson 后异常退出，退出码为 `82`。  
   因此它只能作为 **前 3 个 SCF iteration 的结构性样本**，不能作为 full-run 收敛结论。
2. `PBE0` case 保持了本轮选定的 **真实输入路径**，其自然表现为 `CG` 分支，而不是强行改成 `Davidson`。  
   因此下面关于 `PBE vs PBE0` 的结论，应理解为：
   - `functional + 现实输入设置` 是否改变系统路径与负载抽象  
   而不是“纯 functional、其他一切严格固定”。

---

## 1. 系统级真实需求

### 1.1 顶层时间占比

| case | atoms | dominant solver | `c_bands` share | `sum_band` share | `v_of_rho` share | 结论 |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `h2_tiny` | 2 | Davidson | 50.0% | 0.0% | 50.0% | 最小体系里 band solve 已经和 `v_of_rho` 同量级 |
| `si8_pbe_uspp` | 8 | Davidson | 50.0% | 23.4% | 6.4% | `c_bands` 已经是单项最大块 |
| `si8_pbe_nc` | 8 | Davidson | 76.7% | 8.1% | 14.0% | `c_bands` 明显主导 |
| `graphene_pbe_paw` | 2 | Davidson | 45.0% | 10.0% | 10.0% | 顶层还要承担 `PAW_pot`，但 `c_bands` 仍是单项最大块 |
| `graphene_pbe_uspp` | 2 | Davidson | 64.3% | 14.3% | 14.3% | `c_bands` 主导更明显 |
| `bn32_pbe_uspp` | 32 | Davidson | 77.7% | 12.6% | 5.8% | 大一些的真实小体系里 `c_bands` 已经压倒性主导 |
| `si8_pbe0_uspp` | 8 | CG | 63.4% | 16.9% | 5.6% | 即使换成 `CG`，热点仍然在 band solver |
| `bn32_pbe0_uspp` | 32 | CG | 95.2% | 2.8% | 1.2% | `PBE0 + CG` 下 band solver 几乎吃掉全部 `electrons` 时间 |

### 1.2 直接判断

本轮 rerun 给出的最稳结论是：

- 在成功完成的 full-run case 里，`electrons` 时间的主热点稳定落在 `c_bands`
- 这件事不依赖于体系一定大到不可控，小体系 `Si8 / graphene / BN32` 上已经成立
- 因此系统级真正值得抓的不是“泛泛的 DFT 全流程”，而是 **反复出现、反复调用的 band-solver subsystem**

也就是说，PPT 第一个问题的答案可以收成一句话：

> 真实 `QE` 路径里，最值得系统级抓住的是 `electrons -> c_bands` 这一段，而不是完整 DFT SoC 的所有子模块。

---

## 2. 赛道与系统边界

### 2.1 真实调用链

本轮成功 rerun 的调用链可以压缩成两类。

| 路径类型 | 真实路径 | 本轮代表 case | 数据含义 |
| --- | --- | --- | --- |
| Davidson 路径 | `electrons -> c_bands -> regterg/cegterg -> h_psi/s_psi/g_psi + rdiaghg/cdiaghg` | `h2_tiny`, `si8_pbe_uspp`, `si8_pbe_nc`, `graphene_*`, `bn32_pbe_uspp` | 这是我们当前最关心的 reduced-space + operator-application 主线 |
| CG 路径 | `electrons -> c_bands -> rcgdiagg/ccgdiagg -> h_psi/s_psi` | `si8_pbe0_uspp`, `bn32_pbe0_uspp` | 说明真实 QE 输入设置下，functional 也可能把系统带到另一条 band solver 路径 |

### 2.2 为什么不是“完整 DFT SoC”

Davidson case 里，`c_bands` 内部进一步分解后：

- `si8_pbe_uspp`: `c_bands -> *egterg = 97.6%`
- `si8_pbe_nc`: `c_bands -> *egterg = 98.5%`
- `graphene_pbe_paw`: `c_bands -> *egterg = 96.3%`
- `bn32_pbe_uspp`: `c_bands -> *egterg = 98.7%`

而 `*egterg` 内部：

- `h_psi` share 大约在 `80% ~ 98%`
- `cdiaghg/rdiaghg` share 大约在 `1.9% ~ 9.3%`

这意味着：

- 我们当然不是只做 `cdiaghg/rdiaghg`
- 但也没有必要把 `mix_rho / v_of_rho / IO / 全部 DFT 外围` 一起打包成一颗完整 SoC

因此本轮更准确的系统边界定义是：

> 我们做的是一个 **QE-connected band-solver subsystem**，主覆盖 `c_bands` 内反复出现的 band iteration 数据流，而不是完整 DFT SoC。

---

## 3. functional / pseudo 会不会改变流程

### 3.1 `Si8 + PBE`: `USPP vs NC`

| metric | `si8_pbe_uspp` | `si8_pbe_nc` | 变化 |
| --- | ---: | ---: | --- |
| dominant solver | Davidson | Davidson | solver 分支不变 |
| `c_bands` share | 50.0% | 76.7% | NC 更偏向 band solver 主导 |
| `*egterg -> h_psi` | 80.0% | 98.1% | NC 下 `h_psi` 更绝对主导 |
| `*egterg -> s_psi` | 17.1% | 0.0% | `NC` 直接把显式 `s_psi` 主路径去掉 |
| generalized ratio | 86.5% | 89.4% | 两者都明显 generalized-like |
| representative `npw` | 2945 | 4553 | `NC` 带来更高 plane-wave 规模 |
| `nkb` | 144 | 64 | projector 结构也变了 |
| max `nbase` | 32 | 32 | subspace 宽度量级没变 |

结论：

- pseudo family 不一定改变 solver 分支
- 但会明显改变：
  - `s_psi` 是否成为显式主路径
  - `npw`
  - projector/beta 结构
  - 因而也会改变 `h_psi` 内 FFT / projector 权重

### 3.2 `graphene + PBE`: `PAW vs USPP`

| metric | `graphene_pbe_paw` | `graphene_pbe_uspp` | 变化 |
| --- | ---: | ---: | --- |
| dominant solver | Davidson | Davidson | solver 分支不变 |
| `c_bands` share | 45.0% | 64.3% | USPP 更偏向 band solver 主导 |
| `*egterg -> h_psi` | 84.2% | 83.3% | 几乎不变 |
| `*egterg -> s_psi` | 10.5% | 11.1% | 几乎不变 |
| `*egterg -> diag` | 5.3% | 5.6% | 几乎不变 |
| generalized ratio | 76.8% | 76.7% | 几乎不变 |
| max `nbase` | 8 | 8 | 不变 |

结论：

- 对这个 `graphene` 小体系来说，`PAW vs USPP` **没有改变主流程结构**
- 但 `PAW` 在顶层引入了更明显的非 `c_bands` 开销（`other` 里主要是 `PAW_pot`）
- 也就是说，PAW 在这个 case 上更像是“顶层外围成本变化”，而不是“band solver 结构范式变化”

### 3.3 `PBE vs PBE0`

#### `Si8`

| metric | `si8_pbe_uspp` | `si8_pbe0_uspp` | 变化 |
| --- | ---: | ---: | --- |
| dominant solver | Davidson | CG | **主 solver 分支改变** |
| `c_bands` share | 50.0% | 63.4% | `PBE0 + CG` 更集中在 band solver |
| `c_bands -> *egterg` | 97.6% | 0.0% | Davidson 主线消失 |
| `c_bands -> cg` | 0.0% | 87.5% | CG 成为主路径 |
| max `nbase` | 32 | 0 | Davidson basis-expansion 不再是主系统对象 |
| subspace trace rows | 52 | 4 | reduced solve 只剩辅助性调用 |

#### `BN32`

| metric | `bn32_pbe_uspp` | `bn32_pbe0_uspp` | 变化 |
| --- | ---: | ---: | --- |
| dominant solver | Davidson | CG | **主 solver 分支改变** |
| `c_bands` share | 77.7% | 95.2% | `PBE0 + CG` 更进一步把热点压进 band solver |
| `c_bands -> *egterg` | 98.7% | 0.0% | Davidson 主线消失 |
| `c_bands -> cg` | 0.0% | 93.5% | CG 主导 |
| max `nbase` | 128 | 0 | Davidson local reduced engine 不再是主系统对象 |
| subspace trace rows | 21 | 3 | reduced solve 只剩少量辅助调用 |

结论：

- 在这轮“真实输入路径”复核里，`functional` 的影响不只是数值差异
- 它会直接改变 **band solver branch**
- 这件事是系统级结论，不是噪声

因此在 PPT 的系统问题上，不能再默认说：

> “一旦接入 QE，主路就永远是 Davidson reduced solve”

更准确的说法应该是：

> 对 `PBE` 这类常规 SCF 小体系，本轮主路确实是 Davidson；  
> 但对本轮采用的 `PBE0` 真实输入设置，系统已经切到 `CG`，所以系统边界必须允许 `CG fallback / companion path`。

---

## 4. workload 范式抽象

### 4.1 稳定部分

| 维度 | 观察到的稳定项 | 证据 |
| --- | --- | --- |
| 顶层 | `c_bands` 持续主导 `electrons` | 成功 full-run case 中 `c_bands` share 落在 `45.0% ~ 95.2%` |
| Davidson 内部 | `h_psi` 持续大于 reduced diag | `*egterg -> h_psi = 80.0% ~ 98.1%`; `diag = 1.9% ~ 9.3%` |
| generalized 特征 | Davidson 的真实 rerun case 多数不是标准问题 | `generalized ratio` 多落在 `76% ~ 89%` |
| 数据流风格 | `basis expand -> H/S subspace update -> reduced diag -> repeat` | `bandsolver_trace.csv` 在 `Si8 / graphene / BN32` 上都稳定出现 |

### 4.2 变化部分

| 维度 | 变化项 | 代表证据 |
| --- | --- | --- |
| atom count | `nbase` 和 reduced-space 尺度上升 | `h2: 4`, `graphene: 8`, `si8: 32`, `bn32: 128` |
| pseudo | `s_psi` 是否显式重、`npw`、`nkb`、FFT/projector 权重 | `Si8 USPP vs NC` |
| functional | solver branch 是否从 Davidson 切到 CG | `Si8 PBE vs PBE0`, `BN32 PBE vs PBE0` |
| PAW | 顶层外围成本是否变重 | `graphene_pbe_paw` 的 `other = 35.0%`，明显高于 `graphene_pbe_uspp` |

### 4.3 这一页 PPT 能收成的 workload 抽象

如果只保留系统叙事需要的那一句抽象，可以写成：

> QE 的可复核主 workload 不是“统一的一种矩阵对角化”，而是一个以 `c_bands` 为中心、在 `Davidson` 与 `CG` 两条 band-solver 路径间切换的 workload family。  
> 其中 Davidson 情况下，热点主要落在 `h_psi/s_psi` 反复应用与 basis 扩展数据流，而 reduced diag 本身只占其中较小一块。

---

## 5. 对 chip + FPGA 边界的直接启发

### 5.1 组件分工建议

| 层级 | 建议承接内容 | 本轮数据依据 |
| --- | --- | --- |
| host / QE software | SCF 外层循环、输入输出、`mix_rho`、`v_of_rho`、路径选择 | 这些模块存在但不是主创新点；而且 functional 会改 solver branch |
| FPGA | 控制流编排、数据搬运、fallback solver path、必要时承接部分 FFT / 非核心算子 | 系统必须兼容 `Davidson` 与 `CG`; 不能把第一版叙事绑死在单一路径 |
| chip | 反复出现且适合做成片上 primitive 的 operator-application 主核；Davidson 情况下可加 local reduced companion engine | Davidson case 中 `h_psi` 占 `*egterg` 的 `80% ~ 98%`，显著高于 reduced diag |

### 5.2 这次应该怎么讲系统故事

如果要把这页 PPT 的系统级故事压成一条最可防守的话，我建议直接写：

> 第一版系统不是完整 DFT SoC，而是一个 **QE-connected heterogeneous band-solver accelerator**。  
> 芯片重点抓 `c_bands` 中反复出现、最适合做成片上 primitive 的 `h_psi/s_psi` 数据流与其 Davidson companion reduced engine；  
> FPGA 保留控制、分支兼容、部分 FFT/补充计算，并负责把芯片接进真实 `QE` demo。

更直白一点：

- **主故事不要再讲成“我们做的是 cdiaghg 芯片”**
- 也**不要讲成“我们这版要接管整个 DFT”**
- 这轮 rerun 支持的最稳系统叙事是：
  - `QE-connected band-solver subsystem`
  - `host + FPGA + chip`
  - `chip` 主抓重复率最高的 operator-application hot path
  - `FPGA` 兜住路径差异与系统集成

---

## 附：本轮缺口

1. `benzene` 只能用于前 3 个 SCF iteration 的结构性参考，不能作为 full-run 收敛样本。
2. `PBE vs PBE0` 这轮保留了真实输入路径，因此它回答的是“现实接入时系统会不会变路”，不是“严格控制变量的纯 functional 对照”。
3. `Si8 USPP vs NC` 使用的是 pseudo-compatible cutoff，而不是完全相同 cutoff；因此该对照更接近“真实可运行 pseudo family 对照”，不是“纯数学隔离对照”。

但就 **系统级叙事复核** 这个目标而言，这轮证据已经足够回答 PPT 上最关键的 4 个问题：

- 真实值得抓的是哪段：`c_bands`
- 我们做的系统边界是什么：`QE-connected band-solver subsystem`
- functional / pseudo 会不会改变流程：**会**
- chip + FPGA 的边界应该怎么讲：chip 抓 operator hot path，FPGA 保持系统兼容与集成
