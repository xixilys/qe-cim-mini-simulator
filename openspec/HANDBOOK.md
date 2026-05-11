# OpenSpec 治理手册

OpenSpec 用于管理有边界的设计变更。它不是全局设计文档，也不是运行手册。

## 1. 职责边界

| 对象 | 职责 | 不承担的职责 |
| --- | --- | --- |
| `openspec/specs/*/spec.md` | 当前已接受能力的规范要求。 | 不记录实现流水账。 |
| `openspec/changes/<name>/proposal.md` | 说明一次变更为什么存在。 | 不承载全局架构设计。 |
| `openspec/changes/<name>/design.md` | 说明一次变更的设计决策和权衡。 | 不复制所有背景文档。 |
| `openspec/changes/<name>/tasks.md` | 跟踪这次变更的可验证任务。 | 不作为长期路线图。 |
| `openspec/changes/archive/*` | 保存已完成变更的历史记录。 | 不再显示为 active work。 |

## 2. 当前 active change 规则

active change 只应包含仍需实现或仍需决策的工作。任务全部完成并验证通过后，应执行归档。

当前预期状态：

| Change | 状态 | 处理方式 |
| --- | --- | --- |
| `remove-dft-qe-core-adapter` | 进行中 | 保留 active。 |
| `enhance-openspec-config-and-spec-hierarchy` | 进行中或需复核 | 保留 active，直到任务和验证闭合。 |
| 已完成的 Step1/Step2/Step3、workload、gem5 L4 变更 | 已完成 | 归档到 `openspec/changes/archive/`。 |

## 3. 阅读顺序

审查 Generic DSE 系统时，先读全局设计，再读 OpenSpec：

1. `docs/architecture/generic_dse_global_system_design_v0.md`
2. `docs/architecture/generic_dse_framework_design_spec_v2.md`
3. `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`
4. `openspec/specs/*/spec.md`
5. 相关 active 或 archived change

不要从 `openspec/changes/` 反推全局设计。change 只表达增量，不表达系统全貌。

## 4. 归档规则

归档前必须满足：

- `tasks.md` 中所有任务均为 `- [x]`。
- `openspec status --change <name> --json` 显示 artifacts 完成。
- 相关 delta specs 已同步或明确无需同步。
- `openspec validate --all --strict` 通过，或明确记录失败原因。

推荐命令：

```bash
openspec archive <change-name> --yes
openspec validate --all --strict
```

归档是 git 可追溯操作。需要恢复时，通过 git 历史恢复对应目录。

## 5. 文档写作规则

- proposal 写“为什么”，不写实现流水账。
- design 写决策、替代方案、边界和风险，不写长篇背景材料。
- spec 使用可测试的 MUST / SHALL 需求和 WHEN / THEN 场景。
- tasks 写可验证任务，不写愿望清单。
- 完成后的 change 必须归档，避免 active 列表膨胀。
