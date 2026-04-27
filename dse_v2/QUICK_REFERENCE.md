# Quick Reference - DSE v2

## 🚀 Quick Start

```bash
cd /Volumes/remote/phd/year_2/project/dft加速/dse_v2
source venv/bin/activate

# Run Bayesian DSE (50 trials)
python3 scripts/dse/run_bayesian_dse.py

# Generate visualizations
python3 scripts/analysis/visualize_dse_results.py
```

---

## 📊 Key Results

**Optimal Design**: 16.5 μs, 1.23 mJ  
**Speedup**: 15.6× vs worst design  
**Convergence**: Trial 43-47 (identical solutions)

**Configuration**:
- Parallel Units: 8
- Pipeline Depth: 5
- Offload: h_psi_only
- Dataflow: streaming
- Overlap: full_pipeline

---

## 📁 Important Files

| File | Description |
|------|-------------|
| `docs/BAYESIAN_DSE_ANALYSIS.md` | Full technical analysis |
| `results/pareto/all_trials_v2.csv` | All 50 trials data |
| `results/visualizations/*.png` | 6 visualization plots |
| `workloads/definitions/workload_matrix_v2.json` | 12 materials |
| `scripts/dse/run_bayesian_dse.py` | Main DSE engine |

---

## 🎯 Design Principles

1. **Maximize parallelism** (8 units) → 15.6× speedup
2. **Maximize pipeline depth** (5 stages) → 2× speedup
3. **Minimize offload** (h_psi_only) → reduce communication
4. **Use streaming** → no buffering overhead
5. **Enable full overlap** → maximum throughput

---

## 📈 Performance Metrics

| Metric | Best | Worst | Range |
|--------|------|-------|-------|
| Time | 16.5 μs | 256.7 μs | 15.6× |
| Energy | 1.23 mJ | 8.73 mJ | 7.07× |
| DSP | 7.3% | 1.1% | - |
| BRAM | 3.8% | 0.4% | - |

---

## 🔍 Key Insights

**Strong Correlations**:
- Parallel Units ↔ Time: r=-0.874
- Pipeline Depth ↔ Time: r=-0.518
- Time ↔ Energy: r=0.997

**Insensitive Parameters**:
- intermediate_buffer_kb (512 vs 1024)
- tile_nkb (16 vs 32)
- dma_channels (2 vs 4)

---

## 📋 Next Steps

1. [ ] Save optimal config to JSON
2. [ ] Generate QE inputs for 8 new workloads
3. [ ] Run multi-workload DSE
4. [ ] Add 3rd objective (area)
5. [ ] Validate with SystemC

---

## 🔗 Links

- [Full Analysis](docs/BAYESIAN_DSE_ANALYSIS.md)
- [Project Status](PROJECT_STATUS.md)
- [Session Summary](SESSION_SUMMARY.md)
- [Execution Guide](docs/EXECUTION_GUIDE.md)
