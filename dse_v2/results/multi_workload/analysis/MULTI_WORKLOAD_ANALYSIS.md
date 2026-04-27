# Multi-Workload DSE Analysis Report

## Executive Summary

- **Total Trials**: 50
- **Workloads Tested**: 5 representative materials
- **Performance Range**: 11.79× speedup
- **Energy Range**: 6.00× variation

## Best Design (Average Performance)

**Trial 48**

### Performance Metrics
- Average Time: 1.939348e-05s (19.39μs)
- Average Energy: 0.001416J (1.42mJ)
- Max Time: 4.472235e-05s (44.72μs)
- Std Time: 1.368915e-05s
- CV (Time): 0.706
- Worst-Case Penalty: 2.31×

### Configuration
- Parallel Units: 8
- Pipeline Depth: 4
- Offload Strategy: `include_diag`
- Dataflow Pattern: `hybrid`
- Overlap Policy: `compute_dma`

### Resource Utilization
- Average DSP: 7.16%
- Average BRAM: 1.13%

## Most Robust Design (Lowest Variability)

**Trial 8**

- CV (Time): 0.706
- Worst-Case Penalty: 2.31×
- Average Time: 174.54μs
- Configuration: PU=1, PD=2, h_psi_only

## Top 5 Designs

| Rank | Trial | Avg Time (μs) | Avg Energy (mJ) | CV | WCP | PU | PD | Strategy |
|------|-------|---------------|-----------------|----|----|----|----|----------|
| 1 | 48 | 19.39 | 1.42 | 0.706 | 2.31× | 8 | 4 | include_diag |
| 2 | 44 | 20.53 | 1.46 | 0.706 | 2.31× | 8 | 3 | full_operator_sweep |
| 3 | 47 | 20.53 | 1.46 | 0.706 | 2.31× | 8 | 3 | h_psi_only |
| 4 | 7 | 21.82 | 1.51 | 0.706 | 2.31× | 8 | 2 | include_diag |
| 5 | 13 | 21.82 | 1.51 | 0.706 | 2.31× | 8 | 2 | full_operator_sweep |

## Key Findings

### Parameter Impact

1. **Parallel Units**: Strong impact on performance
   - PU=1: 200.21μs average
   - PU=2: 113.35μs average
   - PU=4: 48.39μs average
   - PU=8: 23.27μs average
   - Best: PU=8 (23.27μs)

2. **Pipeline Depth**: Moderate impact
   - PD=2: 66.75μs average
   - PD=3: 54.69μs average
   - PD=4: 99.88μs average
   - PD=5: 125.55μs average
   - Best: PD=3 (54.69μs)

3. **Offload Strategy**: Significant impact
   - `h_psi_only`: 67.06μs average
   - `full_operator_sweep`: 67.52μs average
   - `include_diag`: 76.96μs average
   - `h_s_psi_fused`: 125.30μs average
   - Best: `h_psi_only` (67.06μs)

### Robustness Analysis

- Mean CV (Time): 0.765
- Mean Worst-Case Penalty: 2.44×
- Most Robust Design: Trial 8 (CV=0.706)

## Design Recommendations

### For Average-Case Performance
- Use Trial 48 configuration
- Expected performance: 19.39μs average
- Variability: ±70.6%

### For Worst-Case Performance
- Use Trial 48 configuration
- Worst-case time: 44.72μs

### For Robustness
- Use Trial 8 configuration
- Lowest variability: CV=0.706
- Predictable performance across workloads

## Visualizations

See the following generated plots:

1. `pareto_frontier_multi_workload.png` - Time vs Energy tradeoff
2. `robustness_analysis.png` - Performance vs Variability
3. `worst_case_penalty_dist.png` - Distribution of worst-case penalties
4. `parameter_impact_heatmap.png` - PU/PD impact on time and energy
5. `offload_strategy_comparison.png` - Strategy comparison
6. `resource_utilization.png` - DSP/BRAM usage vs performance

