# 结果目录说明

`docs/benchmarks/results/` 只保留当前入口说明，不再作为历史证据堆放区。已归档的生成结果、trace bundles 和可复现实验产物位于 `docs/benchmarks/archive/results/`。

## 目录边界

- 新实验默认写入 `tmp/` 或显式指定的输出目录。
- 需要引用历史证据时，使用 `docs/benchmarks/archive/results/` 下的稳定路径。
- QE traces、dumps、timestamped result 和生成报告不要直接改写；需要更新时重新生成新 evidence bundle。
- `docs/benchmarks/testdata/` 仍是测试夹具和 adjudicator 输入，不属于 results archive。

## 继续阅读

- `docs/benchmarks/archive/results/`：历史 benchmark evidence 总入口。
- `docs/benchmarks/archive/results/systemc_architecture_family_dse_bootstrap/`：bootstrap DSE 证据包。
- `docs/benchmarks/archive/results/qe_workload_revalidation/`：QE 工作负载再验证证据。

## 快速验证清单

```bash
rg --files docs/benchmarks/results
rg --files docs/benchmarks/archive/results | rg '\.json$|\.md$|\.csv$'
rg -n 'docs/benchmarks/results/(systemc_architecture_family_dse_bootstrap|qe_workload_revalidation)' docs tools backend openspec
```
