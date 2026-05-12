# benchmark evidence archive

`docs/benchmarks/archive/results/` 保存已经完成的 benchmark 生成证据、历史结果、trace bundles 和可复现实验产物。这里是归档区，不是新实验的默认输出目录。

## 主要内容

- `systemc_architecture_family_dse_bootstrap/`：SystemC architecture-family DSE bootstrap 证据包。
- `qe_workload_revalidation/`：QE 工作负载再验证 trace bundle。
- 根目录下的 JSON、CSV 和 `.out` 文件：历史 baseline、smoke report、case pack 和 trace 摘要。

## 规则

- 保留 timestamped result、QE traces 和 dumps 的原始内容。
- 新结果写入 `tmp/`，通过审查后再作为新的 evidence bundle 归档。
- active contract、schema、template、catalog JSON 仍保留在 `docs/architecture/` 和 `docs/benchmarks/` 的原始稳定路径。

## 快速验证清单

```bash
rg --files docs/benchmarks/archive/results | rg '\.json$|\.md$|\.csv$|\.out$|\.sh$'
rg --files docs/benchmarks/archive/results/systemc_architecture_family_dse_bootstrap/graph_evidence | rg '\.json$' | wc -l
rg -n 'docs/benchmarks/results/systemc_architecture_family_dse_bootstrap|docs/benchmarks/results/qe_workload_revalidation' docs tools backend openspec -g '!docs/benchmarks/archive/results/**'
```
