# systemc architecture family DSE bootstrap 证据包

这个目录保存 bootstrap 阶段的 DSE 证据包、判定材料和汇总产物。它是历史证据链的一部分，不是可随意重排的中间区。

## 目录内容

- `graph_evidence/`，graph JSON 证据文件集合。
- `adjudicator/`，判定输入和判定输出相关材料。
- 根目录下的 CSV、JSON 和 Markdown 文件，都是当前证据包的一部分。

## 规则

- `graph_evidence/` 与 `adjudicator/` 应保持在稳定路径。
- 任何迁移、删除或归档前，都要先扫描引用。
- timestamped 或已生成的证据文件不要直接改写。

## 快速验证清单

```bash
rg --files docs/benchmarks/results/systemc_architecture_family_dse_bootstrap | rg 'graph_evidence|adjudicator|\.json$|\.md$|\.csv$'
rg -n 'systemc_architecture_family_dse_bootstrap|graph_evidence|adjudicator' docs/README.md docs/benchmarks/results/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/README.md docs/benchmarks/results/systemc_architecture_family_dse_bootstrap/graph_evidence/README.md
rg --files tools/benchmarks | rg 'run_systemc_architecture_family_dse_sweep.py|check_qe_ic_component_graph_v1.py|run_qe_system_design_adjudicator.py'
```
