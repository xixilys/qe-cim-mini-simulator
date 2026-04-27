# Architecture Taxonomy for DFT Acceleration

## Overview

This document defines 5 architecture families for systematic comparison. Each architecture is evaluated on the same workload characterization data.

---

## Architecture 1: 4-Cluster Pipeline (Baseline)

### Description
Current design with fixed 4-stage pipeline: Cluster A (operator sweep) → Cluster B (reduced build) → Cluster C (hardware diag) → Cluster D (refresh/residual).

### Key Characteristics
- **Topology**: Linear pipeline with barriers
- **Compute Units**: 4 specialized clusters
- **Memory**: Distributed buffers per cluster
- **Interconnect**: FIFO-based with barriers (A→B, B→C, C→D)
- **Control**: Distributed episode controllers

### Strengths
- ✅ Clear module boundaries
- ✅ Well-defined interfaces
- ✅ Easy to verify independently

### Weaknesses
- ❌ Severe load imbalance (68% / 4% / 23% / 5%)
- ❌ Pipeline bubbles due to barriers
- ❌ Low average utilization (~25%)
- ❌ Buffer fragmentation
- ❌ Fixed topology, hard to adapt

### Resource Estimates
- **Compute**: 4 independent clusters
- **Memory**: ~4-8 MB distributed (projector banks, staging buffers, FIFOs)
- **Interconnect**: 3 FIFOs + control channels
- **Area**: Baseline (1.0x)

### Performance Model
```
T_total = T_A + T_barrier_AB + T_B + T_barrier_BC + T_C + T_D
Utilization = (T_A + T_B + T_C + T_D) / (4 × T_total) ≈ 25%
```

---

## Architecture 2: Unified Systolic Array

### Description
Single large systolic array handles all GEMM operations (h_psi, s_psi, build H_sub/S_sub, refresh). Specialized eigensolver unit for cdiaghg. Unified memory hierarchy.

### Key Characteristics
- **Topology**: Centralized systolic array + specialized units
- **Compute Units**: 
  - Main: 64×64 systolic array (configurable)
  - Specialized: Eigensolver unit (n≤32)
- **Memory**: Unified L2 cache + scratchpad
- **Interconnect**: Crossbar / shared bus
- **Control**: Centralized scheduler

### Strengths
- ✅ High utilization (systolic array always busy)
- ✅ Simple control logic
- ✅ Unified memory reduces fragmentation
- ✅ Natural fit for GEMM-heavy workload (83%)
- ✅ Can dynamically partition array

### Weaknesses
- ❌ Less modular (harder to verify)
- ❌ Eigensolver unit may be underutilized
- ❌ Potential memory bandwidth bottleneck

### Resource Estimates
- **Compute**: 64×64 PE array + eigensolver (16 parallel lanes)
- **Memory**: ~2-4 MB unified L2 + 512 KB scratchpad
- **Interconnect**: Crossbar (64-port)
- **Area**: 0.8-1.2x (less FIFO overhead, but larger array)

### Performance Model
```
T_total = T_GEMM_ops + T_eigen + T_memory_overhead
Utilization = (T_GEMM + T_eigen) / (Array_size × T_total) ≈ 60-70%
```

### Design Parameters
- `array_size`: 32×32, 64×64, 128×128
- `eigen_parallelism`: 4, 8, 16, 32
- `l2_cache_size`: 1MB, 2MB, 4MB
- `scratchpad_size`: 256KB, 512KB, 1MB

---

## Architecture 3: Dataflow Fabric

### Description
Reconfigurable dataflow architecture with multiple heterogeneous PEs connected via flexible NoC. Runtime reconfigurable for different kernels.

### Key Characteristics
- **Topology**: 2D mesh of heterogeneous PEs
- **Compute Units**: 
  - 8-16 GEMM PEs
  - 2-4 Reduction PEs
  - 1-2 Eigensolver PEs
  - 1-2 FFT PEs
- **Memory**: Distributed local memory per PE + shared L2
- **Interconnect**: 2D mesh NoC with packet switching
- **Control**: Distributed dataflow tokens

### Strengths
- ✅ High flexibility (can adapt to different algorithms)
- ✅ Good load balancing (dynamic PE allocation)
- ✅ Scalable (add more PEs)
- ✅ Fault tolerant (route around failed PEs)
- ✅ Can overlap operations naturally

### Weaknesses
- ❌ Complex control (dataflow scheduling)
- ❌ NoC overhead (latency, power)
- ❌ Harder to achieve peak utilization
- ❌ Requires sophisticated compiler/mapper

### Resource Estimates
- **Compute**: 16 heterogeneous PEs
- **Memory**: ~3-6 MB (distributed + shared)
- **Interconnect**: 2D mesh NoC (16 routers)
- **Area**: 1.2-1.5x (NoC overhead)

### Performance Model
```
T_total = max(T_PE_i) + T_NoC_overhead + T_reconfiguration
Utilization = Σ(T_PE_i_busy) / (N_PE × T_total) ≈ 50-60%
```

### Design Parameters
- `n_gemm_pe`: 8, 12, 16
- `n_reduce_pe`: 2, 4
- `n_eigen_pe`: 1, 2
- `noc_topology`: mesh, torus, crossbar
- `noc_bandwidth`: 32GB/s, 64GB/s, 128GB/s

---

## Architecture 4: Heterogeneous Tiles

### Description
Multiple specialized tiles, each with compute + local memory. Tiles communicate via 2D mesh. Similar to AMD MI300 / Intel Ponte Vecchio.

### Key Characteristics
- **Topology**: 4-8 tiles in 2D mesh
- **Compute Units**: 
  - Tile 0-2: GEMM tiles (systolic arrays)
  - Tile 3: Eigensolver tile
  - Tile 4: FFT/Vector tile
  - Tile 5-7: General-purpose tiles
- **Memory**: Local SRAM per tile (256-512 KB) + shared HBM
- **Interconnect**: 2D mesh with tile-to-tile links
- **Control**: Per-tile controller + global coordinator

### Strengths
- ✅ Modular (tiles can be designed independently)
- ✅ Heterogeneous (each tile optimized for its task)
- ✅ Scalable (add more tiles)
- ✅ Good balance of flexibility and efficiency
- ✅ Fault tolerance (disable bad tiles)

### Weaknesses
- ❌ Tile-to-tile communication overhead
- ❌ Load balancing across tiles
- ❌ Requires careful tile partitioning

### Resource Estimates
- **Compute**: 6-8 heterogeneous tiles
- **Memory**: ~4-8 MB (distributed) + HBM interface
- **Interconnect**: 2D mesh (6-8 routers)
- **Area**: 1.1-1.4x

### Performance Model
```
T_total = max(T_tile_i) + T_tile_communication
Utilization = Σ(T_tile_i_busy) / (N_tile × T_total) ≈ 55-65%
```

### Design Parameters
- `n_gemm_tiles`: 2, 3, 4
- `n_eigen_tiles`: 1, 2
- `tile_local_mem`: 256KB, 512KB, 1MB
- `mesh_topology`: 2×3, 2×4, 3×3
- `tile_link_bw`: 16GB/s, 32GB/s, 64GB/s

---

## Architecture 5: CGRA-based

### Description
Coarse-grained reconfigurable array with runtime reconfigurable functional units and interconnect. Inspired by SambaNova RDU / Tenstorrent.

### Key Characteristics
- **Topology**: 2D array of reconfigurable FUs
- **Compute Units**: 
  - 64-256 FUs (each can be MAC/ALU/Memory)
  - Runtime reconfigurable datapath
- **Memory**: Distributed register files + scratchpad
- **Interconnect**: Reconfigurable crossbar/mesh
- **Control**: Configuration memory + sequencer

### Strengths
- ✅ Extreme flexibility (reconfigure for any kernel)
- ✅ High efficiency (near-ASIC performance)
- ✅ Can adapt to different algorithms (Davidson/CG/LOBPCG)
- ✅ Fast reconfiguration (cycle-level)
- ✅ Good for irregular workloads

### Weaknesses
- ❌ Complex programming model (requires compiler)
- ❌ Configuration memory overhead
- ❌ Harder to achieve peak utilization
- ❌ Verification complexity

### Resource Estimates
- **Compute**: 128-256 reconfigurable FUs
- **Memory**: ~2-4 MB (distributed RF + scratchpad)
- **Interconnect**: Reconfigurable network
- **Area**: 1.0-1.3x

### Performance Model
```
T_total = T_compute + T_reconfiguration + T_memory
Utilization = T_FU_active / (N_FU × T_total) ≈ 50-70%
```

### Design Parameters
- `n_fu`: 64, 128, 256
- `fu_type`: homogeneous, heterogeneous
- `reconfig_granularity`: cycle, kernel, episode
- `interconnect_type`: crossbar, mesh, hybrid

---

## Comparison Dimensions

### 1. Performance
- **Metric**: Speedup vs CPU baseline
- **Target**: >10× for h_psi/s_psi, >5× end-to-end
- **Measurement**: Cycle-accurate simulation

### 2. Energy Efficiency
- **Metric**: GFLOPS/W, Energy-Delay Product (EDP)
- **Target**: >100 GFLOPS/W
- **Measurement**: Power model + performance

### 3. Area
- **Metric**: mm² (at 7nm/5nm), Resource utilization
- **Target**: <100 mm² at 7nm
- **Measurement**: Synthesis estimates

### 4. Flexibility
- **Metric**: Workload coverage, Reconfiguration cost
- **Target**: Support Davidson/CG/LOBPCG without redesign
- **Measurement**: Qualitative + reconfiguration overhead

### 5. Design Complexity
- **Metric**: Lines of RTL, Verification effort, Time-to-market
- **Target**: <6 months design + verification
- **Measurement**: Qualitative assessment

### 6. Memory Bandwidth
- **Metric**: Required off-chip BW (GB/s)
- **Target**: <200 GB/s (achievable with HBM2)
- **Measurement**: Roofline analysis

### 7. Utilization
- **Metric**: Average compute utilization (%)
- **Target**: >60%
- **Measurement**: Simulation

---

## Evaluation Methodology

### Phase 1: Analytical Modeling (1 week)
- Roofline analysis for each architecture
- Theoretical performance bounds
- Resource estimates

### Phase 2: High-Level Simulation (2 weeks)
- Python/SystemC TLM models
- Cycle-approximate performance
- Energy estimates (McPAT/CACTI)

### Phase 3: Detailed Comparison (1 week)
- Multi-dimensional scoring
- Pareto frontier analysis
- Sensitivity analysis

### Phase 4: Recommendation (1 week)
- Architecture selection
- Rationale documentation
- Next steps

---

## Decision Criteria

### Must-Have
- ✅ >10× speedup on h_psi/s_psi
- ✅ >5× end-to-end speedup
- ✅ <200 GB/s memory bandwidth
- ✅ Support si4/si8/graphene workloads

### Nice-to-Have
- ✅ >100 GFLOPS/W energy efficiency
- ✅ <100 mm² area at 7nm
- ✅ Support future algorithms (CG/LOBPCG)
- ✅ <6 months design time

### Trade-offs
- **Performance vs Flexibility**: ASIC-like (fast but rigid) vs CGRA (flexible but complex)
- **Area vs Performance**: Larger arrays (more area) vs smaller (less performance)
- **Design Complexity vs Optimality**: Simple (faster to market) vs optimal (better metrics)

---

## Next Steps

1. Implement analytical models for all 5 architectures
2. Run Roofline analysis on workload characterization data
3. Build Python simulators for performance estimation
4. Generate Pareto frontier (Performance vs Area vs Energy)
5. Select top 2-3 architectures for detailed exploration
6. Proceed with SystemC modeling of selected architectures
