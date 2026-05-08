# Architecture Taxonomy for DFT Acceleration v1

## Overview

This document defines a comprehensive architecture taxonomy with **15+ architecture variants** across 5 major families. Each variant has detailed parameters, analytical models, and evaluation criteria.

**Architecture Space Dimensions**:
1. **Compute Organization**: Pipeline vs Systolic vs Dataflow vs Tile-based vs Reconfigurable
2. **Memory Hierarchy**: Distributed vs Unified vs Hybrid
3. **Interconnect**: FIFO vs Crossbar vs Mesh vs NoC
4. **Control**: Centralized vs Distributed vs Dataflow-driven
5. **Specialization**: Fixed-function vs Flexible vs Reconfigurable

---

## Family 1: Pipeline-Based Architectures

### 1.1 4-Cluster Pipeline (Baseline)

**Description**: Fixed 4-stage pipeline with specialized clusters

**Parameters**:
```json
{
  "n_clusters": 4,
  "cluster_types": ["operator", "build", "diag", "refresh"],
  "interconnect": "FIFO",
  "buffer_per_cluster_kb": [2048, 512, 1024, 512],
  "control_model": "distributed",
  "pipeline_stages": 4,
  "barrier_sync": true
}
```

**Variants**:
- **1.1a Standard**: Fixed A→B→C→D pipeline
- **1.1b Fused-AB**: Merge operator sweep + reduced build (A+B→AB)
- **1.1c Fused-CD**: Merge diag + refresh (C+D→CD)
- **1.1d Fused-ABC**: Merge A+B+C, D separate
- **1.1e Dynamic-Pipeline**: Runtime configurable pipeline stages

**Performance Model**:
```
T_total = max(T_A, T_B, T_C, T_D) + T_barrier_overhead
Utilization = Σ(T_i) / (N_clusters × T_total)
```

---

### 1.2 Multi-Stage Pipeline

**Description**: Variable number of stages with flexible routing

**Parameters**:
```json
{
  "n_stages": "variable(2-8)",
  "stage_types": ["compute", "memory", "sync"],
  "routing": "configurable",
  "bypass_paths": true,
  "stage_fusion": "runtime"
}
```

**Variants**:
- **1.2a 2-Stage**: Coarse-grained (compute → memory)
- **1.2b 3-Stage**: Medium-grained (load → compute → store)
- **1.2c 6-Stage**: Fine-grained (decomposed operations)
- **1.2d Adaptive**: Runtime stage creation/destruction

---

## Family 2: Systolic Array Architectures

### 2.1 Unified Systolic Array

**Description**: Single large systolic array for all GEMM operations

**Parameters**:
```json
{
  "array_dimensions": ["32x32", "64x64", "128x128", "256x256"],
  "pe_type": "MAC",
  "dataflow": ["weight_stationary", "output_stationary", "row_stationary"],
  "memory_hierarchy": {
    "l1_pe_buffer": "4KB",
    "l2_scratchpad": "512KB-2MB",
    "l3_global": "4MB-16MB"
  },
  "interconnect": "mesh",
  "control": "centralized"
}
```

**Variants**:
- **2.1a Small-Array**: 32×32 PEs, for small workloads
- **2.1b Medium-Array**: 64×64 PEs, balanced
- **2.1c Large-Array**: 128×128 PEs, high throughput
- **2.1d XL-Array**: 256×256 PEs, data center scale
- **2.1e Multi-Array**: Multiple smaller arrays with shared memory
- **2.1f Hierarchical-Array**: Tree-structured PE organization

**Performance Model**:
```
T_GEMM = (M × N × K) / (array_size × pe_frequency)
Utilization = min(1, workload_size / array_size)
```

---

### 2.2 Specialized Systolic Arrays

**Description**: Multiple specialized systolic arrays for different operations

**Parameters**:
```json
{
  "arrays": [
    {"type": "GEMM", "size": "64x64", "count": 2},
    {"type": "EIGEN", "size": "16x16", "count": 1},
    {"type": "VECTOR", "size": "1x64", "count": 4}
  ],
  "shared_memory": "2MB",
  "inter_array_interconnect": "crossbar"
}
```

**Variants**:
- **2.2a Dual-GEMM**: Two GEMM arrays + eigen unit
- **2.2b GEMM+Vector**: GEMM array + wide vector units
- **2.2c Heterogeneous-PE**: Mixed PE types in single array

---

## Family 3: Dataflow Architectures

### 3.1 Static Dataflow Fabric

**Description**: Fixed dataflow graph with configurable routing

**Parameters**:
```json
{
  "pe_types": ["MAC", "ALU", "MEM", "CTRL"],
  "pe_counts": {"MAC": 64, "ALU": 16, "MEM": 8, "CTRL": 4},
  "interconnect": "2D_mesh",
  "routing": "static",
  "buffer_per_pe": "16KB-64KB"
}
```

**Variants**:
- **3.1a Homogeneous**: All PEs identical
- **3.1b Heterogeneous**: Mixed PE types
- **3.1c Hierarchical**: Clusters of PEs with hierarchy

---

### 3.2 Dynamic Dataflow Fabric

**Description**: Runtime reconfigurable dataflow

**Parameters**:
```json
{
  "reconfiguration_granularity": ["cycle", "kernel", "episode"],
  "reconfiguration_time": "1-100_cycles",
  "pe_flexibility": "full",
  "interconnect": "circuit_switched"
}
```

**Variants**:
- **3.2a Coarse-Grain**: Kernel-level reconfiguration
- **3.2b Fine-Grain**: Cycle-level reconfiguration
- **3.2c Hybrid**: Static + dynamic regions

---

### 3.3 Systolic-Dataflow Hybrid

**Description**: Combines systolic array efficiency with dataflow flexibility

**Parameters**:
```json
{
  "systolic_regions": 2,
  "dataflow_regions": 1,
  "reconfiguration": "partial",
  "shared_memory": "1MB"
}
```

**Variants**:
- **3.3a Fixed-Hybrid**: Fixed systolic + dataflow regions
- **3.3b Reconfigurable-Hybrid**: Runtime partition between modes

---

## Family 4: Tile-Based Architectures

### 4.1 Homogeneous Tiles

**Description**: Multiple identical tiles

**Parameters**:
```json
{
  "tile_type": "unified",
  "n_tiles": [4, 8, 16],
  "tile_compute": "systolic_array_32x32",
  "tile_memory": "512KB",
  "interconnect": "2D_mesh",
  "coherence": "directory"
}
```

**Variants**:
- **4.1a Small-Grid**: 2×2 tiles
- **4.1b Medium-Grid**: 4×2 tiles
- **4.1c Large-Grid**: 4×4 tiles

---

### 4.2 Heterogeneous Tiles

**Description**: Specialized tiles for different functions

**Parameters**:
```json
{
  "tiles": [
    {"type": "GEMM", "count": 4, "compute": "systolic_64x64", "memory": "1MB"},
    {"type": "EIGEN", "count": 2, "compute": "eigen_unit", "memory": "512KB"},
    {"type": "VECTOR", "count": 2, "compute": "vector_unit", "memory": "256KB"}
  ],
  "interconnect": "2D_mesh",
  "shared_l3": "4MB"
}
```

**Variants**:
- **4.2a Compute-Heavy**: More GEMM tiles
- **4.2b Balance**: Equal mix
- **4.2c Memory-Heavy**: Larger memory per tile
- **4.2d Custom**: User-defined tile mix

---

### 4.3 Chiplet-Based Tiles

**Description**: Tiles as separate chiplets with advanced packaging

**Parameters**:
```json
{
  "chiplet_technology": "2.5D/3D",
  "inter_chiplet_interconnect": "UCIe",
  "chiplet_types": ["compute", "memory", "io"],
  "thermal_design": "advanced"
}
```

**Variants**:
- **4.3a 2.5D-CoWoS**: Silicon interposer
- **4.3b 3D-Stacked**: Memory on logic
- **4.3c EMIB**: Intel packaging

---

## Family 5: Reconfigurable Architectures

### 5.1 CGRA (Coarse-Grained Reconfigurable Array)

**Description**: Runtime reconfigurable functional units

**Parameters**:
```json
{
  "fu_types": ["ALU", "MUL", "MEM", "CTRL"],
  "fu_count": 128,
  "interconnect": "crossbar",
  "config_memory": "256KB",
  "reconfiguration_time": "1_cycle"
}
```

**Variants**:
- **5.1a Small-CGRA**: 64 FUs
- **5.1b Medium-CGRA**: 128 FUs
- **5.1c Large-CGRA**: 256 FUs
- **5.1d Hierarchical-CGRA**: Multi-level reconfiguration

---

### 5.2 FPGA-Based

**Description**: Traditional FPGA with soft cores

**Parameters**:
```json
{
  "fpga_family": "Xilinx/Intel",
  "lut_count": "1M-5M",
  "dsp_count": "1000-5000",
  "bram": "50MB-200MB",
  "soft_cores": "0-8"
}
```

**Variants**:
- **5.2a Pure-FPGA**: All soft logic
- **5.2b FPGA+Hard**: With hardened accelerators
- **5.2b FPGA+SoC**: With ARM cores

---

### 5.3 Adaptive Compute

**Description**: Fine-grained reconfiguration with near-ASIC efficiency

**Parameters**:
```json
{
  "granularity": "bit-level",
  "reconfiguration": "runtime",
  "efficiency": "near-asic",
  "programming": "compiler"
}
```

**Variants**:
- **5.3a SambaNova-Style**: DataScale architecture
- **5.3b Tenstorrent-Style**: Wormhole architecture
- **5.3c Groq-Style**: Tensor Streaming Processor

---

## Family 6: Hybrid Architectures

### 6.1 CPU+Accelerator

**Description**: Host CPU with tightly coupled accelerator

**Parameters**:
```json
{
  "cpu_cores": 8,
  "accelerator_type": "systolic_array",
  "coupling": "tight",
  "shared_memory": "coherent"
}
```

**Variants**:
- **6.1a CPU+Systolic**: Apple M-style
- **6.1b CPU+GPU**: NVIDIA Grace Hopper-style
- **6.1c CPU+FPGA**: Xilinx Versal-style

---

### 6.2 Multi-Chip System

**Description**: Multiple chips with different roles

**Parameters**:
```json
{
  "chips": [
    {"role": "host", "type": "CPU", "count": 1},
    {"role": "compute", "type": "accelerator", "count": 4},
    {"role": "memory", "type": "HBM", "count": 8}
  ],
  "interconnect": "NVLink/CXL"
}
```

**Variants**:
- **6.2a Scale-Up**: Large shared memory system
- **6.2b Scale-Out**: Distributed system
- **6.2c Near-Memory**: Processing in memory

---

## Family 7: Near-Memory Computing

### 7.1 PIM (Processing-in-Memory)

**Description**: Compute inside memory arrays

**Parameters**:
```json
{
  "memory_type": "DRAM/HBM",
  "compute_location": "bank/subarray",
  "compute_type": "logic/analog",
  "bandwidth_advantage": "10-100x"
}
```

**Variants**:
- **7.1a DRAM-PIM**: Samsung HBM-PIM
- **7.1b SRAM-PIM**: TSMC
- **7.1c ReRAM-PIM**: Analog compute

---

### 7.2 CIM (Compute-in-Memory)

**Description**: Analog compute using memory arrays

**Parameters**:
```json
{
  "memory_technology": "SRAM/ReRAM/PCM",
  "compute_precision": "analog/digital",
  "adc_dac": "required",
  "accuracy": "approximate"
}
```

**Variants**:
- **7.2a Digital-CIM**: Precise digital compute
- **7.2b Analog-CIM**: Approximate analog compute
- **7.2c Mixed-Signal**: Hybrid approach

---

## Evaluation Framework

### Multi-Fidelity Evaluation

| Fidelity | Method | Time | Accuracy | Purpose |
|----------|--------|------|----------|---------|
| **L0** | Analytical/Roofline | Minutes | ±50% | Initial screening |
| **L1** | Python TLM | Hours | ±30% | Architecture ranking |
| **L2** | SystemC TLM | Days | ±15% | Detailed comparison |
| **L3** | Cycle-Accurate | Weeks | ±5% | Final validation |
| **L4** | RTL/Silicon | Months | Measured | Ground truth |

### Evaluation Metrics

**Performance**:
- Speedup vs CPU baseline
- Throughput (GFLOPS)
- Latency (ms)
- Scalability

**Efficiency**:
- Energy per operation (pJ/op)
- Power consumption (W)
- Area efficiency (GFLOPS/mm²)
- Energy-Delay Product (EDP)

**Flexibility**:
- Workload coverage
- Reconfiguration overhead
- Programmability
- Compiler support

**Implementation**:
- Area (mm²)
- Design effort (person-months)
- Verification complexity
- Time-to-market

---

## Architecture Selection Decision Tree

```
Start
├── Workload Analysis
│   ├── GEMM-heavy (>80%)? 
│   │   ├── YES → Systolic Array (2.1) or Tiles (4.2)
│   │   └── NO → Continue
│   ├── Algorithm evolving?
│   │   ├── YES → Dataflow (3.x) or CGRA (5.1)
│   │   └── NO → Continue
│   ├── Tight power constraint?
│   │   ├── YES → Near-Memory (7.x) or PIM
│   │   └── NO → Continue
│   └── Design time < 6 months?
│       ├── YES → Pipeline (1.x) or Simple Systolic
│       └── NO → Any architecture
│
├── Resource Constraints
│   ├── Area budget < 50mm²?
│   │   └── Consider: Small Systolic, CGRA
│   ├── Power budget < 50W?
│   │   └── Consider: Near-Memory, Dataflow
│   └── Memory bandwidth > 500GB/s?
│       └── Consider: HBM, 3D stacking
│
└── Final Selection
    ├── Multi-objective optimization
    ├── Pareto frontier analysis
    └── Sensitivity analysis
```

---

## Current Recommendation for QE DFT

**Primary**: Unified Systolic Array (2.1b - Medium 64×64)
- Best performance for GEMM-heavy workload
- Good utilization
- Manageable complexity

**Alternative 1**: Heterogeneous Tiles (4.2a - Compute-Heavy)
- Better flexibility for algorithm evolution
- Modular design

**Alternative 2**: Systolic-Dataflow Hybrid (3.3b)
- Balance efficiency and flexibility
- Runtime adaptability

**Future Exploration**:
- Near-Memory (7.x) for extreme bandwidth
- Multi-Chip (6.2) for scalability
- CGRA (5.1) for maximum flexibility

---

## Version History

- **v0**: Initial 5 architectures (4-Cluster, Systolic, Dataflow, Tiles, CGRA)
- **v1**: Expanded to 15+ variants across 7 families with detailed parameters
