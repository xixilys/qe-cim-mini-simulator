# comparison results 目录说明

`comparison_results.json` 目前应视为生成的历史证据，除非后续引用扫描证明它仍然是活跃输入。

## 目录边界

- `comparison_results.json`，默认属于 generated / historical evidence。
- `comparison_report.md` 和 `architecture_comparison.png`，属于同一轮比较产物。
- 任何移动或删除前，都要先扫描 `docs/architecture/architecture_comparison/README.md`、工具脚本和下游引用。

## 快速验证清单

```bash
rg -n 'comparison_results.json|results/' docs/architecture/architecture_comparison/README.md docs/architecture/architecture_comparison/archive/results/README.md
rg --files docs/architecture/architecture_comparison/archive/results | rg 'comparison_results.json|comparison_report.md|architecture_comparison\.png'
rg --files tools/architecture_comparison | rg 'run_architecture_comparison.py|comparison_framework.py|__init__.py'
```
