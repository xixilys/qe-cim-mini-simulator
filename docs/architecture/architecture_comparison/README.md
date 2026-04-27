# Architecture Comparison Framework

## Purpose

This directory contains a systematic framework for comparing multiple hardware architecture candidates for DFT acceleration, beyond the current 4-cluster pipeline design.

## Architecture Candidates

We compare 5 different architecture families:

1. **4-Cluster Pipeline** (Baseline) - Current design
2. **Unified Systolic Array** - Single large systolic array + specialized units
3. **Dataflow Fabric** - Reconfigurable dataflow with flexible interconnect
4. **Heterogeneous Tiles** - Multiple specialized tiles with 2D mesh
5. **CGRA-based** - Coarse-grained reconfigurable array

## Evaluation Methodology

### Metrics
- **Performance**: Speedup, throughput, latency
- **Energy**: Total energy, energy efficiency (GFLOPS/W)
- **Area**: Resource utilization, mm²
- **Flexibility**: Workload adaptability, reconfigurability
- **Complexity**: Design effort, verification cost

### Workloads
- si4_pbe_uspp_small
- si8_pbe_nc
- si8_pbe_uspp
- graphene_pbe_uspp

## Files

- `architecture_taxonomy.md` - Detailed description of each architecture
- `comparison_framework.py` - Python framework for architecture modeling
- `run_architecture_comparison.py` - Main comparison script
- `architecture_models/` - Individual architecture models
- `results/` - Comparison results and analysis

## Quick Start

```bash
# Run full architecture comparison
python3 run_architecture_comparison.py --all-architectures --all-workloads

# Compare specific architectures
python3 run_architecture_comparison.py \
  --architectures 4cluster,systolic,dataflow \
  --workloads si8_pbe_nc

# Generate comparison report
python3 generate_comparison_report.py --output-dir results/
```

## Status

- [x] Framework design
- [ ] Architecture models implementation
- [ ] Baseline calibration
- [ ] Full comparison sweep
- [ ] Results analysis
