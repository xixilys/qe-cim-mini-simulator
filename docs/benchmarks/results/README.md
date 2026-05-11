# 结果与证据目录说明

`docs/benchmarks/results/` 存放生成证据、历史结果、trace bundles 和可复现实验产物。这里不是临时缓存目录，也不是可以随手整理的杂项目录。

## 目录边界

- timestamped result 文件保持原样，不要改写。
- QE traces、dumps 和相关 bundle 保持原样，不要重排或重命名。
- `docs/benchmarks/testdata/` 属于 fixture 和 adjudicator 输入，应按稳定路径使用。
- 任何生成证据的迁移、删除或归档，都必须先扫描引用，再取得明确的用户批准。

## 继续阅读

- `systemc_architecture_family_dse_bootstrap/`，bootstrap DSE 证据包。
- `qe_workload_revalidation/`，QE 工作负载再验证证据。

## 快速验证清单

```bash
rg --files docs/benchmarks/results | rg '\.json$|\.md$|\.csv$'
rg -n 'docs/benchmarks/results/|docs/benchmarks/testdata/' docs/README.md docs/benchmarks/results/README.md
rg --files tools/benchmarks | rg 'assess_qe_phase1_evidence_closure.py|render_qe_phase1_evidence_closure_md.py|summarize_qe_subspace_trace.py'
```
