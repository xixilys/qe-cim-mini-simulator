# QE unified DSE framework v0

## 1. Purpose and claim boundary

本文档定义一个 bounded v0 的 Unified DSE Framework 架构和实施计划。它面向后续 implementation agents，说明如何把当前 `QE` architecture-family DSE、design-space spec、SystemC timed-functional proxy、adjudicator intake 和结果分析组织成一套可导入的 Python 标准库包与薄 CLI。

v0 的核心目标是整理和固定证据流，而不是升级当前证据等级。当前 canonical Stage-A 路径仍然是 `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` 生成 DSE evidence，再由 adjudicator 合同约束 public claim。Unified DSE v0 只能产生 Stage-A evidence-only、adjudicator-ready 的中间产物，不能作为 public decision authority。

本文件继承以下现有边界：

- `docs/benchmarks/qe_complete_architecture_family_dse_framework_v0.md` 定义 architecture-family DSE 的完整对象模型和 evidence-first 原则。
- `docs/benchmarks/qe_dse_framework_user_manual_v0.md` 定义当前 DSE 工具链的用户读法、claim boundary 和 artifact 阅读顺序。
- `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json` 是 v0 design-space 的机器可读意图来源。
- `docs/benchmarks/qe_architecture_family_design_space_schema_v0.json` 是 design-space spec 的结构约束。
- `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` 冻结 adjudicator 是唯一 public decision authority。
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` 仍是当前 Stage-A family sweep 的 canonical runner。

因此，Unified DSE Framework v0 的 claim boundary 如下：

1. v0 是 Stage-A evidence-only 和 adjudicator-ready 组织层，不是 public decision authority。
2. v0 可以读取、规范化、筛选、搜索、解释和打包候选点，但不能声明最终 best family、release posture 或 claim permission。
3. SystemC backend 是 timed-functional/proxy backend，且 SystemC execution 必须是 opt-in。默认 dry-run 或 proposal-only 路径不得隐式运行模型。
4. `implementation_backend` 只暴露显式 `stub`、`reserved`、`projection_only` 状态。v0 不声称真实 HLS、RTL、OpenROAD 或 FPGA board backend 已完成。
5. `dse_v2` 只作为 optional proposal/search PoC，不能替代现有 runner、schema、phase runner 或 adjudicator。
6. `F4`、`F5`、`custom` 以及新增 family/template 默认是 projection/scaffold，除非同一 artifact bundle 内存在明确 executor evidence。
7. v0 不声称 GPU baseline、whole-node power、board-grounded timing、public performance 或 thesis-grade capability 已经闭合。

一句话规则：

```text
Unified DSE v0 organizes Stage-A evidence.
Adjudicator controls public claims.
```

### 1.1 Stage contract-lane artifacts

The staged DSE flow now has companion contract/readiness documents:

- `docs/benchmarks/qe_dse_systemc_feedback_contract_v0.md` defines the dry-run SystemC feedback object. Default rows are `planned_not_executed`, `not_executed`, `subprocess_invoked = false`, and capped at `timed_functional_proxy_contract_only`.
- `docs/benchmarks/qe_dse_gem5_systemc_handoff_contract_v0.md` defines the Stage B gem5/SystemC handoff object. Default rows are `planned_for_stage_b`, `not_executed`, `requires_linux_x86_validation`, and capped at `stage_b_handoff_contract_only`.
- `docs/benchmarks/qe_unified_dse_stage_a_readiness_checklist_v0.md` defines QE anchor defaults and pre-adjudication ranking semantics: `qe_equivalent_scf_claim = false`, `pareto_membership = not_evaluated`, `ranking_claim_ceiling = stage_a_screening_only`, and `final_public_family_winner = null`.
- `docs/benchmarks/qe_dse_qe_correctness_report_contract_v0.md` defines the Stage C external QE-equivalent correctness report accepted by `--qe-correctness-report`.
- `docs/benchmarks/qe_dse_fpga_asic_implementation_evidence_contract_v0.md` defines the Stage D external FPGA/ASIC implementation evidence accepted by `--implementation-evidence`.

These artifacts preserve the same claim ceiling as this framework: the CLI does
not generate RTL/HLS/board evidence, does not make cycle-accurate claims, does
not lock into CIM, does not hide gem5/SystemC execution, and does not claim
QE-equivalent SCF without a validated external correctness report.
Advisor-facing language should stay aligned with
`docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md`
and `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md`.

## 2. Module architecture

v0 实施形态建议为一个标准库 Python package：

```text
tools/benchmarks/unified_dse/
```

再配一个薄 CLI：

```text
tools/benchmarks/run_unified_dse_v0.py
```

CLI 只负责参数解析、调用 package、写出 artifacts 和返回退出码。核心逻辑必须放在 package 内，便于单元测试和后续 adjudicator/phase runner 复用。

v0 必须包含且只以以下 8 个模块作为主边界。模块名为规范名，implementation agents 不应重命名。

### 2.1 `workload_frontend`

`workload_frontend` 负责把 workload 输入转成统一的 workload descriptor。v0 只需要覆盖当前 Stage-A 可用字段，包括 workload id、case id、workload group、source trace summary、tolerance schema id、fairness policy id、power boundary id、observability contract id 和 workload signature。

允许输入包括：

- 显式 JSON workload descriptor；
- 现有 DSE runner 输出中的 workload 字段；
- 由 trace summary 或 case pack 派生的最小 descriptor。

v0 不需要重新采样 `QE`，也不需要生成新的 raw trace。缺字段时应写入 `missing_fields` 和 `support_status: explain_only`，而不是猜测。

### 2.2 `architecture_space`

`architecture_space` 负责读取 design-space spec、schema、template metadata 和 candidate identity。它必须保留 candidate identity 与 runtime projection 的区别。

核心职责：

- 读取 `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json`；
- 使用 `docs/benchmarks/qe_architecture_family_design_space_schema_v0.json` 做结构检查；
- 输出 normalized candidate records；
- 标注 `candidate_family`、`architecture_template_id`、`runtime_projection_family`、`design_axes`、`join_keys`；
- 对 `F4`、`F5`、`custom` 写入 `support_status: projection_only`，除非输入 evidence 明确给出 executor support。

该模块不得把 `runtime_projection_family` 覆盖成 `candidate_family`，也不得把 template metadata 当成 executor evidence。

### 2.3 `fast_model`

`fast_model` 负责低成本 proxy 估计、筛选和排序前的 sanity checks。v0 fast model 必须可解释，且要保留假设来源。

允许输出：

- `estimated_time_proxy_s`；
- `estimated_energy_proxy_j`；
- `estimated_bytes_proxy`；
- `resource_pressure`；
- `fallback_risk`；
- `spill_risk`；
- `assumption_set_id`；
- `source_kind`，例如 `stub`、`timed_functional_proxy`、`trace_calibrated_proxy`、`mixed`。

如果没有足够输入，模块应输出 `support_status: reserved` 或 `projection_only`，并列出 blocker。它不能伪造测量值，也不能把估计值描述成 measured result。

### 2.4 `search_engine`

`search_engine` 负责候选点生成、约束过滤、proposal 排序和 shortlist 形成。

v0 搜索策略应从简单、可复现的策略开始：

- grid 或 enumerated spec traversal；
- deterministic pruning；
- tie-band 内保留 primary、fallback 和 extra candidates；
- optional `dse_v2` proposal/search PoC adapter。

`dse_v2` 必须保持 optional。它只能提出 candidates 或排序建议，不能成为 canonical evaluator，不能替代 `run_systemc_architecture_family_dse_sweep.py`，也不能绕过 adjudicator authority。

### 2.5 `systemc_backend`

`systemc_backend` 负责把 candidate 转成当前 timed-functional/proxy SystemC runner 可读的 config，并在显式 opt-in 时调用现有 runner 或模型入口。

边界如下：

- 默认不执行 SystemC，只生成 planned execution records。
- 只有 CLI 参数或配置显式允许时，才可以调用 SystemC 路径。
- 所有 SystemC evidence 都必须标注为 timed-functional/proxy，不得标注为 board-measured。
- 对当前 runner 的调用应优先复用 `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`，而不是复制一套 authority surface。
- 如果只生成 config sidecar，则结果必须是 projection/scaffold，不是 executor-backed evidence。

### 2.6 `implementation_backend`

`implementation_backend` 负责预留未来 HLS、RTL、OpenROAD、FPGA board 或其他 implementation-level 后端的接口形状。v0 只允许显式 stub 状态。

允许状态：

```text
stub
reserved
projection_only
```

禁止状态：

```text
hls_completed
rtl_completed
openroad_completed
board_measured
production_ready
```

除非未来任务真的加入对应 executor、artifact schema、validator 和 evidence bundle，否则该模块不得输出 real implementation evidence。v0 中它的主要作用是防止用户把 projection rows 误读为 implementation-backed rows。

### 2.7 `calibration_engine`

`calibration_engine` 负责记录 proxy assumption、calibration source、residual、uncertainty 和 evidence join。v0 可以读取现有校准或 correctness artifacts，但不得自己升级证据等级。

核心输出：

- `calibration_status`；
- `calibration_source_kind`；
- `calibration_artifacts`；
- `uncertainty_notes`；
- `join_key_status`；
- `claim_ceiling`。

如果没有 measured 或 trace-calibrated evidence，模块应明确写 `calibration_status: missing` 或 `not_applicable`。缺失校准不是错误，但必须进入 result evidence 和 adjudicator intake。

### 2.8 `result_analysis`

`result_analysis` 负责把候选、fast model、backend evidence 和 calibration metadata 合成 Stage-A result bundle。

允许输出：

- row-level normalized results；
- Pareto membership；
- blocker summary；
- projection summary；
- family summary；
- promotion state，取值应保持 `reject`、`explain-only`、`promotion-eligible`；
- adjudicator intake manifest 或 intake-ready sidecar。

该模块不能输出 final public recommendation。任何 `recommended` 风格字段都必须写成 pre-adjudication evidence package，并在字段说明中标明非 authority。

## 3. Module-to-repo artifact map

| Module | Proposed files | Existing repo anchors | v0 artifact role |
| --- | --- | --- | --- |
| `workload_frontend` | `tools/benchmarks/unified_dse/workload_frontend.py` | `docs/overview/qe_subspace_sampling.md`, `tools/benchmarks/summarize_qe_subspace_trace.py`, `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md` | Normalize workload descriptor and missing-field evidence. |
| `architecture_space` | `tools/benchmarks/unified_dse/architecture_space.py` | `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json`, `docs/benchmarks/qe_architecture_family_design_space_schema_v0.json`, `docs/benchmarks/qe_complete_architecture_family_dse_framework_v0.md` | Load candidates, preserve identity, mark projection/scaffold support. |
| `fast_model` | `tools/benchmarks/unified_dse/fast_model.py` | `docs/benchmarks/qe_dse_fidelity_ladder_and_execution_loop_v0.md`, `docs/benchmarks/qe_fast_layer_proxy_assumption_set_v0.json` | Produce explainable proxy estimates with source kind and assumptions. |
| `search_engine` | `tools/benchmarks/unified_dse/search_engine.py` | `docs/benchmarks/qe_next_stage_dse_strategy_v0.md`, `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` | Deterministic traversal, pruning, tie-band shortlist, optional `dse_v2` proposals. |
| `systemc_backend` | `tools/benchmarks/unified_dse/systemc_backend.py` | `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`, `model/qe_band_solver_model/README.md` | Generate SystemC execution plans and opt-in timed-functional/proxy runs. |
| `implementation_backend` | `tools/benchmarks/unified_dse/implementation_backend.py` | `docs/benchmarks/qe_simulator_board_observability_contract_v0.md`, `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` | Expose only `stub`、`reserved`、`projection_only` statuses in v0. |
| `calibration_engine` | `tools/benchmarks/unified_dse/calibration_engine.py` | `docs/benchmarks/qe_ic_simulator_calibration_contract_v0.md`, `tools/benchmarks/compare_qe_gold_correctness.py`, `tools/benchmarks/normalize_qe_gold_baseline.py` | Attach calibration status and uncertainty without upgrading claim authority. |
| `result_analysis` | `tools/benchmarks/unified_dse/result_analysis.py` | `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`, `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` | Emit Stage-A evidence bundle and adjudicator-ready intake sidecar. |
| CLI | `tools/benchmarks/run_unified_dse_v0.py` | Existing benchmark `run_*.py` pattern | Thin entry point for dry-run, proposal-only, and explicit opt-in SystemC execution. |
| Tests | `tools/benchmarks/test_unified_dse_*.py` | Existing benchmark `test_*.py` pattern | Unit and contract tests for each module and CLI mode. |

The proposed package is additive. It must not rename existing files, must not modify the canonical runner by default, and must not require existing users to switch away from `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`.

## 4. Runtime/evidence flow

The bounded v0 flow is:

```text
workload inputs
  -> workload_frontend
  -> architecture_space
  -> search_engine
  -> fast_model
  -> backend selection
       -> systemc_backend, opt-in timed-functional/proxy only
       -> implementation_backend, explicit stub/reserved/projection-only only
  -> calibration_engine
  -> result_analysis
  -> adjudicator-ready evidence bundle
```

The flow has three supported runtime modes.

### 4.1 `dry_run`

`dry_run` is the safest default mode. It loads workload and architecture inputs, validates schema shape, emits candidate records, marks support status, and writes planned execution records. It does not run SystemC and does not call implementation backends.

Expected evidence posture:

```text
source_kind: stub or projection_only
execution_status: not_executed
claim_ceiling: Stage-A evidence only
```

### 4.2 `proposal_only`

`proposal_only` extends `dry_run` with search and fast-model estimates. It can rank candidates for screening and can emit shortlist artifacts for later runner/adjudicator intake. It still does not execute SystemC unless an explicit opt-in flag is present.

Expected evidence posture:

```text
source_kind: projection_only or trace_calibrated_proxy, depending on inputs
execution_status: proposed
claim_ceiling: Stage-A evidence only
```

### 4.3 `systemc_opt_in`

`systemc_opt_in` is the only mode allowed to invoke SystemC. It must require an explicit CLI/config field such as:

```text
--execute-systemc
```

or an equivalent config key:

```json
{
  "execution_mode": "systemc_opt_in",
  "execute_systemc": true
}
```

The backend must record the exact runner path, config path, workload id, candidate id, environment fields, exit status, parsed outputs and any missing fields. Even when the run succeeds, evidence remains timed-functional/proxy unless a future validated board or implementation backend adds stronger evidence through separate contracts.

Expected evidence posture:

```text
source_kind: timed_functional_proxy
execution_status: executed
claim_ceiling: Stage-A evidence only unless adjudicator and closure gates say otherwise
```

## 5. Implementation plan by phase

### Phase 0: Documentation and scope freeze

Goal: freeze v0 module names, claim boundary and artifact ownership before code starts.

Tasks:

1. Add this document as `docs/benchmarks/qe_unified_dse_framework_v0.md`.
2. Confirm implementation agents use the 8 module names exactly: `workload_frontend`, `architecture_space`, `fast_model`, `search_engine`, `systemc_backend`, `implementation_backend`, `calibration_engine`, `result_analysis`.
3. Keep existing README/index files unchanged in the docs-only task.
4. Treat this document as an implementation plan, not as proof that the framework is implemented.

Acceptance:

- The document includes all required claim boundaries.
- No implementation capability is claimed before code and evidence exist.

### Phase 1: Package skeleton and shared types

Goal: create an importable package with no external dependencies beyond Python stdlib.

Files:

- `tools/benchmarks/unified_dse/__init__.py`
- `tools/benchmarks/unified_dse/types.py`
- `tools/benchmarks/unified_dse/io_utils.py`
- `tools/benchmarks/test_unified_dse_types.py`

Implementation notes:

- Use dataclasses or plain dictionaries consistently.
- Define shared enums or constants for `support_status`, `source_kind`, `execution_status`, `promotion_state` and `claim_ceiling`.
- Reject unknown support statuses rather than silently accepting them.
- Keep JSON reading/writing deterministic with sorted keys where possible.

Acceptance:

- Package imports from repository root.
- Tests cover allowed and disallowed status values.
- No CLI side effects on import.

### Phase 2: Workload and architecture input normalization

Goal: load workload and architecture inputs into normalized records.

Files:

- `tools/benchmarks/unified_dse/workload_frontend.py`
- `tools/benchmarks/unified_dse/architecture_space.py`
- `tools/benchmarks/test_unified_dse_workload_frontend.py`
- `tools/benchmarks/test_unified_dse_architecture_space.py`

Implementation notes:

- `workload_frontend` must preserve missing fields instead of inventing defaults.
- `architecture_space` must preserve candidate identity and runtime projection separately.
- `F4`、`F5`、`custom` must default to `projection_only` unless executor evidence is present.
- Schema validation can start with stdlib JSON shape checks. If a stronger validator is added later, it must not change claim authority.

Acceptance:

- Design-space JSON loads successfully.
- Candidate identity fields survive normalization.
- Tests prove `runtime_projection_family` does not overwrite `candidate_family`.

### Phase 3: Search and fast-model evidence

Goal: produce deterministic Stage-A proposals and proxy estimates.

Files:

- `tools/benchmarks/unified_dse/search_engine.py`
- `tools/benchmarks/unified_dse/fast_model.py`
- `tools/benchmarks/test_unified_dse_search_engine.py`
- `tools/benchmarks/test_unified_dse_fast_model.py`

Implementation notes:

- Start with deterministic traversal over normalized candidates.
- Add pruning only when the blocker can be written into the result row.
- `dse_v2` adapter, if present, must be optional and must emit proposal metadata only.
- Fast-model outputs must include `source_kind` and `assumption_set_id`.

Acceptance:

- Same input yields byte-stable candidate order.
- Missing inputs produce `explain-only` or blocked rows, not crashes unless the input is structurally invalid.
- `dse_v2` cannot be selected as canonical evaluator in tests.

### Phase 4: Backend boundary implementation

Goal: implement SystemC opt-in boundary and implementation backend stubs.

Files:

- `tools/benchmarks/unified_dse/systemc_backend.py`
- `tools/benchmarks/unified_dse/implementation_backend.py`
- `tools/benchmarks/test_unified_dse_systemc_backend.py`
- `tools/benchmarks/test_unified_dse_implementation_backend.py`

Implementation notes:

- `systemc_backend` default path must generate planned execution records only.
- Actual SystemC invocation requires explicit opt-in.
- If execution is disabled, output `execution_status: not_executed`.
- `implementation_backend` must expose only `stub`、`reserved`、`projection_only` statuses in v0.
- Tests must fail if any implementation backend reports HLS, RTL, OpenROAD or board completion.

Acceptance:

- Default CLI/package path never executes SystemC.
- Opt-in mode records a runner command plan before execution.
- Implementation backend cannot emit real backend completion states.

### Phase 5: Calibration and result analysis

Goal: attach calibration metadata and emit adjudicator-ready evidence.

Files:

- `tools/benchmarks/unified_dse/calibration_engine.py`
- `tools/benchmarks/unified_dse/result_analysis.py`
- `tools/benchmarks/test_unified_dse_calibration_engine.py`
- `tools/benchmarks/test_unified_dse_result_analysis.py`

Implementation notes:

- Calibration must preserve join-key status.
- Missing calibration should be recorded as evidence, not hidden.
- `result_analysis` may emit row summaries, family summaries, blockers and Pareto membership.
- `result_analysis` must not emit final public recommendation fields.
- Promotion state must stay within `reject`、`explain-only`、`promotion-eligible`.

Acceptance:

- Output bundle is deterministic for fixed input.
- Missing calibration appears in blocker or evidence notes.
- Tests confirm no final public decision fields are present.

### Phase 6: CLI and regression coverage

Goal: expose a thin runnable entry point and cover the expected modes.

Files:

- `tools/benchmarks/run_unified_dse_v0.py`
- `tools/benchmarks/test_run_unified_dse_v0.py`

Implementation notes:

- CLI should accept input paths, output directory, execution mode and optional `--execute-systemc`.
- CLI must default to dry-run or proposal-only without SystemC execution.
- CLI output should include a manifest with module versions, input paths, mode, timestamp and claim boundary.
- CLI must return nonzero for invalid schema, unknown mode or illegal backend status.

Acceptance:

- Dry-run fixture writes candidate summary and manifest.
- Proposal-only fixture writes shortlist and blocker summary.
- SystemC execution is not triggered unless opt-in is explicit.

## 6. Test and acceptance plan

v0 tests should be stdlib-friendly and local to `docs/benchmarks/`, matching the existing benchmark test style.

Minimum test groups:

| Test group | Required checks |
| --- | --- |
| Import tests | `tools/benchmarks/unified_dse` imports without side effects. |
| Status tests | Allowed statuses pass; forbidden backend completion states fail. |
| Workload tests | Missing optional fields become `missing_fields`; required identity drift is reported. |
| Architecture tests | `candidate_family` and `runtime_projection_family` remain distinct. |
| Scaffold tests | `F4`、`F5`、`custom` default to `projection_only` without executor evidence. |
| Search tests | Deterministic traversal and tie-band shortlist are stable. |
| `dse_v2` tests | `dse_v2` can only appear as optional proposal/search PoC, not canonical evaluator. |
| SystemC tests | Default mode does not execute SystemC; opt-in is required. |
| Implementation backend tests | HLS、RTL、OpenROAD、board completion states are rejected in v0. |
| Result tests | Output is Stage-A evidence-only and has no final public recommendation authority. |

Acceptance criteria for v0 implementation:

1. All proposed modules exist under `tools/benchmarks/unified_dse/` and use the exact module names in this document.
2. `tools/benchmarks/run_unified_dse_v0.py` can run in dry-run mode on a small fixture without invoking SystemC.
3. Output manifest states `claim_boundary: Stage-A evidence-only` or equivalent wording.
4. SystemC execution is opt-in and records timed-functional/proxy provenance.
5. `implementation_backend` cannot report real HLS、RTL、OpenROAD or board completion.
6. `dse_v2` cannot replace the existing runner or adjudicator in any accepted config.
7. `F4`、`F5`、`custom` are projection/scaffold unless executor evidence is explicitly present.
8. Result analysis produces adjudicator-ready evidence, not public decision authority.

Suggested command shape after implementation:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --dry-run \
  --max-design-points 4 \
  --output-dir tmp/unified_dse_v0_dry_run
```

For SystemC opt-in only:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --execute-systemc \
  --output-dir tmp/unified_dse_v0_systemc_proxy
```

The second command is a future implementation target. This documentation task does not run it and does not claim that the CLI already exists.

### 6.1 Stage B0 descriptor-only handoff

The implemented CLI can optionally emit Stage B0 handoff descriptors without running
SystemC or gem5:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir tmp/unified_dse_stage_b0_descriptors \
  --dry-run \
  --max-design-points 4 \
  --emit-stage-b0-descriptors
```

The output sidecars are:

- `systemc_configs/{candidate_id}.json`
- `gem5_systemc_handoff/{candidate_id}.json`
- `stage_b0_descriptor_manifest_v0.json`

This is descriptor generation only. It records `not_executed` status and a
descriptor-only claim ceiling so later Stage B work can connect real SystemC
feedback or gem5/SystemC control without changing the Stage A evidence boundary.

### 6.2 SystemC feedback ingest and full-stage status

The next claim-safe step after descriptor generation is artifact ingest. The CLI
can read a SystemC feedback JSON and merge metrics back into DSE rows:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --systemc-feedback tmp/systemc_feedback.json \
  --output-dir tmp/unified_dse_stage_b1_b2 \
  --dry-run \
  --max-design-points 4
```

This reads an external feedback artifact; it does not launch SystemC. If the
artifact provides ranking-grade proxy metrics, rows may become
`promotion-eligible`, but the claim ceiling remains timed-functional feedback
only and `final_public_family_winner` remains `null`.

For a complete staged status surface, use:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --output-dir tmp/unified_dse_full_stage_status \
  --dry-run \
  --emit-stage-b0-descriptors \
  --emit-full-stage-status
```

This writes `unified_dse_full_stage_status_v0.json`. Stages without external
evidence are reported as blocked, for example
`blocked_waiting_gem5_systemc_smoke_report`,
`blocked_waiting_qe_equivalent_correctness_report`, and
`blocked_waiting_fpga_asic_implementation_evidence`.

### 6.3 Stage B3 gem5/SystemC smoke report intake

Stage B3 becomes referenced only when an external smoke report is supplied and
validated:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --gem5-smoke-report tmp/gem5_smoke_report.json \
  --output-dir tmp/unified_dse_stage_b3 \
  --dry-run \
  --emit-full-stage-status
```

The smoke report schema is `qe_dse_gem5_systemc_smoke_report_v0`. Required
safe fields include `execution_status = executed`,
`claim_ceiling = gem5_systemc_smoke_only`,
`scf_control_loop_status`, `systemc_bridge_status`, `environment`, `metrics`,
and `correctness_gate.qe_equivalent_scf_claim = false`. The CLI rejects a
Stage B3 smoke report that attempts to claim QE-equivalent SCF.

### 6.4 Stage C QE-equivalent correctness report intake

Stage C can now be represented by an external correctness report reference:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --qe-correctness-report tmp/qe_correctness_report.json \
  --output-dir tmp/unified_dse_stage_c \
  --dry-run \
  --emit-full-stage-status
```

The report schema is `qe_dse_qe_equivalent_correctness_report_v0`. A report may
set `qe_equivalent_scf_claim = true` only when it records
`execution_status = executed`, `correctness_status = pass`, the frozen tolerance
schema `qe_gold_numerical_tolerance_schema_v0`, and a compare payload whose
`overall_pass = true`. This is a correctness-only claim ceiling
(`qe_equivalent_scf_correctness_only`), not a performance, implementation, or
final-winner claim. Failed/mismatch reports are still valid evidence references
but keep Stage C in `external_correctness_report_referenced_not_proven`.

### 6.5 Stage D FPGA/ASIC implementation evidence intake

Stage D is also an external-artifact intake surface:

```bash
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload docs/benchmarks/testdata/unified_dse/minimal_workload.json \
  --implementation-evidence tmp/implementation_evidence.json \
  --output-dir tmp/unified_dse_stage_d \
  --dry-run \
  --emit-full-stage-status
```

The evidence schema is `qe_dse_fpga_asic_implementation_evidence_v0`. It accepts
explicit FPGA/ASIC evidence kinds such as `hls_synthesis`, `rtl_simulation`,
`fpga_board`, `openroad_physical`, `asic_ppa`, or
`implementation_projection`, each with a narrow claim ceiling such as
`hls_synthesis_only` or `fpga_board_measurement_only`. The DSE CLI only
validates and references the artifact; it does not run HLS, RTL simulation,
OpenROAD, gem5, SystemC, or board measurement. The schema rejects public winner
claims and production release readiness claims.

## 7. Explicit non-goals

Unified DSE Framework v0 explicitly does not do the following:

- It does not replace `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` as the canonical current Stage-A runner.
- It does not replace `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` or any adjudicator output.
- It does not make public best-family, release-ready or thesis-grade decisions.
- It does not claim real HLS backend completion.
- It does not claim RTL backend completion.
- It does not claim OpenROAD backend completion.
- It does not claim FPGA board execution or board-measured evidence.
- It does not claim GPU baseline closure or decisive `CPU + GPU` comparison capability.
- It does not claim whole-node power or energy evidence beyond existing contract-bounded proxy fields.
- It does not claim public-performance capability.
- It does not treat `dse_v2` as canonical evaluator or replacement for current runner/adjudicator.
- It does not treat `F4`、`F5`、`custom` scaffolds as executor-backed without explicit executor evidence.
- It does not modify QE source, SystemC model code, architecture templates or existing result bundles as part of v0 documentation.

## 8. Future integration points

The following integrations are allowed as future work, but each requires its own implementation, tests, schema updates and authority review.

### 8.1 Adjudicator intake manifest

`result_analysis` can emit an adjudicator intake sidecar that follows the adjudicator input-manifest contract. This should remain an evidence input. The adjudicator still decides public family decision, release posture and claim permission.

### 8.2 Existing runner adapter

`systemc_backend` can wrap `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` instead of duplicating its logic. The adapter should preserve existing result schema fields and add only clearly namespaced Unified DSE metadata.

### 8.3 `dse_v2` proposal/search PoC

A future `dse_v2` adapter may propose candidate order or search points. It must emit proposal provenance and must project candidates back through the same design-space schema, runner path and adjudicator boundary before any claim-bearing use.

### 8.4 Accurate-layer and correctness gates

Future work can connect shortlisted candidates to correctness-capable validation using existing gold/tolerance contracts. This integration may improve evidence quality, but it still cannot bypass adjudicator authority.

### 8.5 Implementation-level backend evidence

Future HLS、RTL、OpenROAD or FPGA board backends may be added only when they have concrete executor code, artifact schemas, validator tests, observability metadata and fairness/power boundary checks. Until then, `implementation_backend` must remain stub/reserved/projection-only.

### 8.6 Documentation index update

After implementation exists and tests pass, a separate task may add this document and the new CLI to README/index files. This task intentionally does not edit those files.
