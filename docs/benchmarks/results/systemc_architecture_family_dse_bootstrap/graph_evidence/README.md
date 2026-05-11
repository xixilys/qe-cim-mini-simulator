# graph evidence 目录说明

这个目录包含 540 个 graph JSON 证据文件，是当前 docs 树里最集中的 JSON 热点。

## 处理原则

- 文件默认原地保留，不要为了整理而迁移。
- 只有在后续获得明确批准的 archive move，并且完成引用更新后，才考虑移动。
- 这里的文件属于生成证据，不是活跃 contract、schema 或 template。

## 快速验证清单

```bash
rg --files docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/graph_evidence | rg '\.json$' | wc -l
rg -n 'graph_evidence|systemc_architecture_family_dse_bootstrap' docs/README.md docs/benchmarks/results/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/graph_evidence/README.md
rg --files tools/benchmarks | rg 'run_systemc_architecture_family_dse_sweep.py|run_qe_system_design_adjudicator.py|check_qe_ic_component_graph_v1.py'
```
