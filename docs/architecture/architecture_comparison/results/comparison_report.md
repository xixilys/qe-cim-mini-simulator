# Architecture Comparison Report
## Summary
| Architecture | Speedup | Utilization | Energy (MJ) | Efficiency (GFLOPS/W) | Area |
|--------------|---------|-------------|-------------|----------------------|------|
| 4cluster | 1.00x | 23.9% | 4691.44 | 3.91 | 1.00x |
| systolic | 2.15x | 101.4% | 3653.42 | 5.02 | 0.85x |
| dataflow | 3.07x | 70.0% | 2594.93 | 7.07 | 1.25x |

## Detailed Analysis

### 4-Cluster Pipeline
**Configuration:**
- Peak GFLOPS: 512
- Compute Units: 4
- Memory: L1=512KB, L2=4096KB
- Off-chip BW: 200 GB/s
- Interconnect: fifo

**Performance:**
- Total Time: 172748046.8750 s
- Effective GFLOPS: 106.22
- Utilization: 23.9%

**Energy:**
- Total Energy: 4691.44 MJ
- Energy Efficiency: 3.91 GFLOPS/W

**Roofline Analysis:**
- Achievable GFLOPS: 512.00
- Bottleneck: compute_bound

### Unified Systolic Array
**Configuration:**
- Peak GFLOPS: 512
- Compute Units: 1
- Memory: L1=512KB, L2=2048KB
- Off-chip BW: 200 GB/s
- Interconnect: crossbar

**Performance:**
- Total Time: 80191650.3906 s
- Effective GFLOPS: 228.83
- Utilization: 101.4%

**Energy:**
- Total Energy: 3653.42 MJ
- Energy Efficiency: 5.02 GFLOPS/W

**Roofline Analysis:**
- Achievable GFLOPS: 512.00
- Bottleneck: compute_bound

### Dataflow Fabric
**Configuration:**
- Peak GFLOPS: 512
- Compute Units: 16
- Memory: L1=1024KB, L2=3072KB
- Off-chip BW: 200 GB/s
- Interconnect: noc

**Performance:**
- Total Time: 56319754.4643 s
- Effective GFLOPS: 325.82
- Utilization: 70.0%

**Energy:**
- Total Energy: 2594.93 MJ
- Energy Efficiency: 7.07 GFLOPS/W

**Roofline Analysis:**
- Achievable GFLOPS: 512.00
- Bottleneck: compute_bound

## Recommendations
- **Best Performance**: dataflow (325.82 GFLOPS)
- **Best Energy Efficiency**: dataflow (7.07 GFLOPS/W)
- **Smallest Area**: systolic (0.85x)
