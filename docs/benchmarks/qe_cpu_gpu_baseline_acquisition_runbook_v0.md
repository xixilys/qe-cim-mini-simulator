# QE-only `CPU + GPU` baseline acquisition runbook（v0，2026-04-14）

## 0. 目的与适用范围

本文把 phase-1 的 `CPU + GPU` fairness contract 从“原则说明”翻成**可执行的 baseline acquisition 序列**。它服务于：

- `.omx/plans/ralplan-final-qe-fpga-fullstack-co-design-20260413.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`
- `docs/benchmarks/qe_cpu_gpu_fpga_shell_comparison_plan_v0.md`
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`
- `docs/benchmarks/qe_shell_level_comparison_metrics_contract_v0.md`

它不是新的 thesis，也不是新的结果报告。它只回答一件事：

> **phase-1 应该怎样逐行获取、命名、筛选、停表（stop）`CPU + GPU` baseline，直到得到一组可用于 per-case decisive selection 的结果。**

默认边界保持为：

- `QE-only`
- `single CPU + single GPU`
- end-to-end QE shell accounting
- same correctness / same tolerance contract
- whole-node power boundary
- workload-group 聚合，不允许只凭单个 case 宣称 thesis 成立

与本文配套的 machine-readable run manifest template：

- `docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json`
- `tools/benchmarks/init_qe_phase1_artifact_bundle.py`
- 若目标是把当前 proxy 指标升级成工程级实测，请同时阅读：
  - `docs/benchmarks/qe_engineering_grade_measurement_handbook_v0.md`

与本文直接配套的 validator / 执行入口：

- `docs/benchmarks/qe_algorithm_rewrite_manifest_contract_v0.md`：定义 `algorithm_rewrite_manifest_id`、`rewrite_mode` 与 GPU applicability 的填写边界；
- `tools/benchmarks/compare_qe_gold_correctness.py`：用于生成/复查 `correctness.json`；
- `tools/benchmarks/check_qe_gold_contract_regression.py`：用于回归检查 same-correctness / same-tolerance contract 是否漂移。
- `tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py`：用于把采集后的 GPU row 归类为 `deferred / reference_only / thesis_eligible`，并用 `decisive_for_case` 标记当前 case 的最优 row。

---

## 1. baseline acquisition 的总原则

### 1.4 machine-readable 承接要求

本文中的每一条 `CPU + GPU` baseline row，都应首先实例化：

- `docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json`

推荐做法是先复制该模板生成每次 run 的 `cpu_gpu_baseline_manifest.json`，再补齐：

- `case_id`
- `gpu_mode`
- `workload_group_id`
- `fairness_policy_id`
- `power_boundary_id`
- `algorithm_rewrite_manifest_id`
- `correctness_contract_id`
- `qe_tolerance_schema_id`

如果 `cpu_gpu_baseline_manifest.json` 缺这些冻结字段，则该 row 只能停留在 `pending / reference_only`，不能进入 `decisive_for_case` 选择。

### 1.5 execution-ready baseline bundle example

如果希望直接生成同口径 scaffold，优先使用：

```bash
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  baseline \
  --out-dir "$RUN_DIR" \
  --workload-id si4_pbe_uspp_small \
  --gpu-mode strict_fp64 \
  --run-tag 20260414-120000
```

它会先生成符合 phase-1 contract 的：

- `cpu_gpu_baseline_manifest.json`
- `algorithm_rewrite_manifest.json`

随后再由人工或采集脚本补齐实测 artifact。

若当前机器上还没有专门的 bundle helper，phase-1 也可直接从 template 起步。下面示例展示一条 `si4_pbe_uspp_small / strict_fp64` row 的最小落盘方式：

```bash
RUN_DIR=tmp/qe_cpu_gpu_baseline/si4_pbe_uspp_small/strict_fp64/20260414-120000
mkdir -p "$RUN_DIR"
cp docs/benchmarks/qe_cpu_gpu_baseline_manifest_template_v0.json "$RUN_DIR/cpu_gpu_baseline_manifest.json"
python3 - <<'PY'
import json
from pathlib import Path
path = Path("tmp/qe_cpu_gpu_baseline/si4_pbe_uspp_small/strict_fp64/20260414-120000/cpu_gpu_baseline_manifest.json")
data = json.loads(path.read_text())
data["case_id"] = "si4_pbe_uspp_small"
data["gpu_mode"] = "strict_fp64"
data["run_tag"] = "20260414-120000"
data["host_id"] = "fill-real-host"
data["gpu_id"] = "fill-real-gpu"
data["qe_rev"] = "fill-real-qe-rev"
data["command"] = "fill-real-qe-launch-command"
data["artifact_paths"] = {
    "stdout": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.stdout.txt",
    "stderr": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.stderr.txt",
    "timing": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.timing.json",
    "correctness": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.correctness.json",
    "convergence": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.convergence.json",
    "power": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.power.json",
    "summary": "qe_si4_pbe_uspp_small__cpu_gpu__strict_fp64__20260414-120000.summary.md"
}
path.write_text(json.dumps(data, indent=2) + "\n")
PY
```

完成实际运行后，再把 `stdout/stderr/timing/correctness/convergence/power/summary` 按 `artifact_paths` 填齐；若缺件，则该 row 只能停在 `reference_only` 或 `deferred`。

### 1.6 execution-ready readiness assessment example

当一个或多个 GPU row 已经采集完毕后，推荐立即运行：

```bash
python3 tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py \
  --baseline-dir <strict-fp64-row-dir> \
  --baseline-dir <practical-row-dir>
```

它会输出：

- 每条 row 是 `deferred / reference_only / thesis_eligible` 哪一种；
- 同一 `case_id` 下哪一条 row 当前是 `decisive_for_case = true`。

### 1.1 两种 GPU 模式必须显式区分

phase-1 里每一条 `CPU + GPU` row 必须显式属于以下之一：

1. `strict_fp64`
   - 优先保持 `FP64` / 接近 software reference 的数学路径；
   - 目标是形成最强的“同精度公平” baseline。

2. `practical`
   - 允许现实工程里会采用的 GPU path（vendor library、batching、可能的 mixed-precision-friendly route）；
   - 前提是最终仍满足冻结后的 correctness / tolerance contract。

**禁止**把两者混成一条抽象 `GPU` 结果。

### 1.2 decisive baseline 不是先到先得

对任一 case：

- 若 `strict_fp64` 与 `practical` 都通过 correctness/tolerance gate，
- 且都具有完整 shell-level artifact，

则 **更快的那条** 是该 case 的 `decisive_cpu_gpu_row`。

如果只测到其中一条，另一条必须标成 `deferred`，不能省略不写。

### 1.3 algorithmic rewrite fairness 继承主合同

若某项 rewrite 在数学语义与工程上同样适用于 `CPU + GPU`，则 GPU baseline **必须允许采用**。因此每条 row 都必须挂接：

- `fairness_policy_id`
- `algorithm_rewrite_manifest_id`
- `rewrite_mode`（`none` / `shared_semantic` / `shared_engineering` / `fpga_specific_arch`）

若某项 rewrite 仍处于 `gpu_applicable = unclear`，该 row 不能进入 decisive 比较，只能作为 `reference_only`。

---

## 2. phase-1 per-case run matrix

### 2.1 候选 case 来源

以 `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md` 为准。当前 phase-1 acquisition 优先级如下：

#### A. correctness / convergence anchors（先跑）
- `si8_pbe_nc`
- `si8_pbe_uspp`

用途：
- 验证 GPU path 是否满足 same-correctness / same-tolerance / convergence-comparable gate；
- 这些 case 可以是 `gate_only`，不一定进入 thesis-counted aggregation。

#### B. thesis performance candidates（后跑）
- `si4_pbe_uspp_small`
- `graphene_pbe_uspp`
- `au_slab_subspace`
- `sic32_subspace`

用途：
- 构成最终 workload-group 的候选行；
- 只有通过 anchor 级 correctness gate 后，才允许进入该批。

### 2.2 每个 case 的运行矩阵

对每个 case，默认矩阵如下：

| case_id | gpu_mode | rewrite_mode | required? | 说明 |
| --- | --- | --- | --- | --- |
| `<case>` | `strict_fp64` | `none/shared_*` | yes | phase-1 首要公平基线 |
| `<case>` | `practical` | `none/shared_*` | yes | 现实部署辅助基线；若更快则可被标记为 `decisive_for_case = true` |

默认顺序：

1. `strict_fp64`
2. `practical`

只有当 `strict_fp64` 因环境/软件栈不可获得而无法执行，才允许先跑 `practical`；但结果必须标注为：

- `baseline_state = deferred`
- 并在 `mode_attempt_exemption_note` 或 `notes` 中明确记录 `strict_fp64` 尚未闭合的原因

### 2.3 每条 row 的状态机

每条 row 必须进入以下之一：

- `pending`
- `running`
- `measured_not_yet_validated`
- `reference_only`
- `deferred`
- `thesis_eligible`

`decisive` **不是** `baseline_state`。  
它由 readiness assessor 通过独立字段 `decisive_for_case = true/false` 给出，用于标记同一 `case_id` 下当前最快且已闭合 admission gates 的 row。

状态推进规则：

1. 采集开始前：`pending`
2. 运行中：`running`
3. 运行完成且 artifact 产出：`measured_not_yet_validated`
4. 若 correctness / tolerance / accounting / power 任一不完整：`reference_only`
5. 若环境缺失、GPU mode 缺失、rewrite policy 未冻结：`deferred`
6. 若通过所有 admission gate：`thesis_eligible`
7. 若同 case 下是可接受 GPU rows 中最快者：`baseline_state` 保持 `thesis_eligible`，并额外标记 `decisive_for_case = true`

---

## 3. 单条 row 的执行序列

对每个 `case_id × gpu_mode` 组合，必须按下面顺序执行。

### Step 1 — freeze run header

在运行前先冻结：

- `case_id`
- `gpu_mode`
- `host_id`
- `gpu_id`
- `qe_git_rev` 或 workspace rev note
- `fairness_policy_id`
- `power_boundary_id`
- `algorithm_rewrite_manifest_id`
- `correctness_contract_id`
- `qe_tolerance_schema_id`
- `workload_group_id`

若其中任一缺失，**不得开跑**。

### Step 2 — preflight eligibility check

运行前必须检查：

- 当前 case 是否已有 normalized gold / compare path；
- 当前 GPU mode 是否具备明确 software stack；
- 当前 rewrite 是否已明确 `gpu_applicable`；
- 当前 shell accounting boundary 是否与 `CPU only` / `CPU + FPGA` 一致；
- 当前 power path 是否满足 whole-node 边界。

若失败：
- 能补则记录 blocker 并转 `deferred`
- 不能补则转 `reference_only`

### Step 3 — run acquisition

每条 row 至少要产生：

1. QE 原始 stdout / stderr
2. shell timing summary
3. per-stage timing（若可得）
4. correctness compare output
5. convergence-comparable 判定输出
6. host/device transfer or launch note
7. whole-node power/energy 测量输出
8. run manifest（记录环境、命令、模式、rewrite）

### Step 4 — post-run validation

验证顺序固定为：

1. `gold correctness pass`
2. `tolerance pass`
3. `convergence_comparable pass`
4. shell accounting boundary 完整
5. power boundary 完整
6. artifact naming / manifest 完整

若 1–3 任一失败：
- 不得进入 thesis table；
- 该 row 至少记为 `reference_only`。

若 4–6 任一失败：
- 该 row 不得进入 decisive selection；
- 可留作 `measured_not_yet_validated` 或 `reference_only`。

### Step 5 — decisive selection

对同一 `case_id`：

- 在全部 `thesis_eligible` GPU rows 中，选 shell-level end-to-end time 最短者；
- 保持其 `baseline_state = thesis_eligible`；
- 额外记为 `decisive_for_case = true`；
- 其余保留，但不能删。

---

## 4. artifact naming 规则

### 4.1 目录建议

phase-1 建议将所有 `CPU + GPU` baseline artifact 放在：

- `tmp/qe_cpu_gpu_baseline/<case_id>/`

每个 `case_id` 目录下再按 `gpu_mode` 分层：

- `strict_fp64/`
- `practical/`

### 4.2 文件名前缀

统一使用：

`qe_<case_id>__cpu_gpu__<gpu_mode>__<run_tag>`

其中：

- `<case_id>`：如 `si8_pbe_nc`
- `<gpu_mode>`：`strict_fp64` 或 `practical`
- `<run_tag>`：建议 `YYYYMMDD-HHMMSS` 或等价唯一 tag

### 4.3 最低要求文件集合

每条 row 至少应输出：

- `cpu_gpu_baseline_manifest.json`
- `qe_<case>__cpu_gpu__<mode>__<tag>.stdout.txt`
- `qe_<case>__cpu_gpu__<mode>__<tag>.stderr.txt`
- `qe_<case>__cpu_gpu__<mode>__<tag>.timing.json`
- `qe_<case>__cpu_gpu__<mode>__<tag>.correctness.json`
- `qe_<case>__cpu_gpu__<mode>__<tag>.convergence.json`
- `qe_<case>__cpu_gpu__<mode>__<tag>.power.json`
- `qe_<case>__cpu_gpu__<mode>__<tag>.summary.md`

如使用 helper 初始化，同目录下还应保留配套的 `algorithm_rewrite_manifest.json`。

若当前环境无法提供独立的 `stderr` 或 `power.json`，必须在 `cpu_gpu_baseline_manifest.json` 与 `summary.md` 中写明原因；否则该 row 只能记为 `reference_only`。

### 4.4 manifest 最低字段

每个 `cpu_gpu_baseline_manifest.json` 至少包含：

- `case_id`
- `gpu_mode`
- `run_tag`
- `host_id`
- `gpu_id`
- `qe_rev`
- `command`
- `env`
- `fairness_policy_id`
- `power_boundary_id`
- `correctness_contract_id`
- `qe_tolerance_schema_id`
- `algorithm_rewrite_manifest_id`
- `rewrite_mode`
- `baseline_state`
- `notes`

---

## 5. minimum required outputs 与 admission gates

### 5.1 单条 row 进入 thesis table 的最低条件

某条 `CPU + GPU` row 只有在满足以下全部条件时，才可记为 `thesis_eligible`：

1. `gold correctness pass = yes`
2. `tolerance pass = yes`
3. `convergence_comparable pass = yes`
4. `gpu_mode` 已明确（`strict_fp64` 或 `practical`）
5. `algorithm_rewrite_manifest_id` 已存在，且 `gpu_applicable` 未处于 `unclear`
6. shell-level timing artifact 完整
7. whole-node power artifact 完整，或至少达到公平合同中允许的次优路径并明确 gap
8. 与 `CPU only` / `CPU + FPGA` 使用相同 workload/correctness/accounting IDs

### 5.2 case 进入 final workload-group aggregation 的最低条件

某个 `case_id` 只有在存在至少一条 `baseline_state = thesis_eligible` 且 `decisive_for_case = true` 的 `CPU + GPU` row 时，才可进入最终 `CPU + GPU` vs `CPU + FPGA` 聚合表。

否则该 case 必须标注为以下之一：

- `reference_only`
- `deferred`
- `gate_only`

### 5.3 phase-1 decisive baseline selection

最终用于 thesis pass/fail 的 `CPU + GPU` baseline 必须由**每个 thesis-counted case 的 `decisive_for_case = true` row**组成，而不是随意挑选某个模式拼表。

因此：

> final workload-group table 的 GPU 列，是一组 `per-case decisive_for_case = true` rows 的组合，而不是“全部 strict_fp64”或“全部 practical”的预设单模式表。

---

## 6. stop conditions（必须显式停表的情况）

以下任一情况出现时，该 row 或该 case 必须**停在 `decisive_for_case != true` 状态**，不能继续被包装成可用于主结论的 baseline。

### 6.1 row-level stop

以下任一情况，该 row 直接停在 `reference_only` 或 `deferred`：

1. 无法满足 gold correctness / tolerance / convergence-comparable
2. shell accounting boundary 与 phase-1 合同不一致
3. whole-node power boundary 缺失且无法补齐
4. rewrite 可适用于 GPU，但 baseline 未允许采用
5. artifact 缺失到无法复核 run context
6. 结果只提供 device kernel time，没有 end-to-end shell total
7. 当前 row 使用的 host/gpu 环境与其他 rows 明显不可比，且无 normalization note

### 6.2 case-level stop

以下任一情况，该 case 不得进入 final thesis-counted workload group：

1. `strict_fp64` 与 `practical` 都没有一条达到 `thesis_eligible`
2. 只有 `reference_only` / `deferred` rows，或虽有 `thesis_eligible` row 但没有 `decisive_for_case = true` row
3. 当前 case 的 gold artifact / tolerance schema 仍未归一
4. 该 case 的 GPU path 仍依赖未冻结的 fairness policy
5. 该 case 的 power measurement 在 GPU 或 FPGA 一侧长期缺失，导致无法形成同边界比较

### 6.3 phase-level stop

以下任一情况出现时，应暂停继续扩大 GPU baseline 矩阵，而先修合同或工具：

1. anchor cases 连续无法通过 convergence-comparable gate
2. `strict_fp64` 与 `practical` 的模式边界无法被稳定陈述
3. shared-rewrite manifest 长期无法冻结
4. end-to-end timing 与 power artifact 在多 case 上反复缺失
5. 出现大量“参考值”但仍无法形成至少一个完整 thesis-counted GPU 列

此时必须回到：

- fairness/power contract
- workload/correctness contract
- shell metrics contract

进行修订，而不是继续积累不可比较结果。

---

## 7. 最小执行顺序（phase-1 推荐）

推荐的 acquisition 顺序如下：

### Batch A — anchors first
1. `si8_pbe_nc / strict_fp64`
2. `si8_pbe_nc / practical`
3. `si8_pbe_uspp / strict_fp64`
4. `si8_pbe_uspp / practical`

目标：
- 先证明 GPU baseline 在 correctness / tolerance / convergence 上可闭环；
- 若 anchors 都长期停在 `reference_only/deferred`，则暂停 thesis-counted case 采集。

### Batch B — thesis candidates
5. `si4_pbe_uspp_small / strict_fp64`
6. `si4_pbe_uspp_small / practical`
7. `graphene_pbe_uspp / strict_fp64`
8. `graphene_pbe_uspp / practical`
9. `au_slab_subspace / strict_fp64`
10. `au_slab_subspace / practical`
11. `sic32_subspace / strict_fp64`
12. `sic32_subspace / practical`

目标：
- 为 workload-group 聚合形成 per-case `decisive_for_case = true` rows；
- 若某些 case 仍只有 reference-only/deferred，则必须在最终表中显式剔除，并记录原因。

---

## 8. phase-1 输出物

完成本 runbook 后，至少应形成以下 3 类输出：

### 8.1 row ledger
记录每个 `case_id × gpu_mode` 的：
- `baseline_state`
- artifact path
- correctness/tolerance/convergence 结果
- power completeness
- `decisive_for_case` 与否
- stop reason

### 8.2 case decision sheet
每个 case 一页，记录：
- 可用 GPU rows
- `decisive_for_case = true` row
- 被剔除 rows 及原因
- 是否进入 workload-group aggregation

### 8.3 workload-group GPU column manifest
最终用于 thesis 比较的 GPU 列清单，至少包括：
- `workload_group_id`
- thesis-counted cases
- each case 的 `decisive_for_case = true` row path
- excluded cases and reasons
- unresolved deferred/reference-only rows

---

## 9. 当前已知 open items

基于当前仓库状态，这份 runbook 默认承认以下 open items 仍未解决：

- `CPU + GPU` real shell baseline 仍未补齐；
- 部分 thesis candidate cases 的 gold / normalized compare artifact 仍待闭环；
- workload-group aggregation 规则仍需进一步冻结；
- strict/practical 两种 GPU mode 的具体命令与环境矩阵仍需落到实际机器；
- whole-node power path 仍需与实际 GPU host 环境对齐。

因此，当前阶段的要求不是“先写出 GPU 很强/很弱的结论”，而是：

> **先把 `CPU + GPU` baseline acquisition 变成一套可执行、可停表、可审计的流程。**
