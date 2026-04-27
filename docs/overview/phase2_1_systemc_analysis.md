# Phase 2.1 Analysis: SystemC Configuration Mechanism

**Date**: 2026-04-20  
**Status**: In Progress

---

## Task 2.1.1: Configuration Entry Point ✓ COMPLETED

### Configuration Loading (sc_main.cpp)

**Entry Point**: `load_run_config()` function (line 321-390)

**Configuration Method**: Environment variables

```cpp
qebs::SystemRunConfig load_run_config() {
  qebs::SystemRunConfig config;
  config.architecture_family = env_or_default("QEBS_ARCH_FAMILY", "F2");
  config.software_family = env_or_default("QEBS_SOFTWARE_FAMILY", "QE");
  config.flow_family = env_or_default("QEBS_FLOW_FAMILY", "CBANDS_DIAG");
  config.case_id = env_or_default("QEBS_CASE_ID", "systemc_candidate");
  // ... 30+ more configuration fields
  return config;
}
```

**Key Configuration Fields**:
- `architecture_family`: "F1" / "F2" / "F3" (default: "F2")
- `software_family`: "QE" / "CP2K" / "VASP"
- `flow_family`: "CBANDS_DIAG" / "QS_DIAG" / "BLOCKED_DAVIDSON"
- `offload_scope_override`: Controls what gets offloaded to FPGA
- `resident_policy_override`: Controls persistent object management
- `graph_frontdoor_mode`: Graph-based architecture configuration (optional)

### Main Execution Flow (sc_main.cpp)

```cpp
int sc_main(int argc, char** argv) {
  const auto run_config = load_run_config();                    // Line 402
  qebs::DFTHybridSystem system("dft_hybrid_system");           // Line 404
  const auto report = system.run_full_flow(run_config);        // Line 406
  write_candidate_result_json(report, ...);                     // Line 411
  return 0;
}
```

**Flow**:
1. Load configuration from environment variables
2. Instantiate DFTHybridSystem (hardcoded 4-cluster architecture)
3. Run full SCF flow with configuration
4. Write results to JSON

---

## Task 2.1.2: Hardcoded Architecture ✓ IDENTIFIED

### DFTHybridSystem Constructor (dft_hybrid_system.cpp)

```cpp
DFTHybridSystem::DFTHybridSystem(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      fabric_(sc_core::sc_module_name("interconnect")),
      chip_(sc_core::sc_module_name("chip_top")),
      fpga_(sc_core::sc_module_name("fpga_orchestrator"), fabric_, chip_),
      host_(sc_core::sc_module_name("host_scf"), fabric_, fpga_) {}
```

**Hardcoded Components**:
- `fabric_`: Interconnect (always present)
- `chip_`: ChipTop (always present)
- `fpga_`: FPGAOrchestrator (always present)
- `host_`: HostSCF (always present)

**Problem**: No configuration parameter passed to constructor!

### ClusterGraphExecutor (cluster_graph_executor.hpp)

```cpp
class ClusterGraphExecutor : public sc_core::sc_module {
 private:
  ClusterAOperatorSweep cluster_a_;      // HARDCODED
  ClusterBReducedBuild cluster_b_;       // HARDCODED
  ClusterCHardwareDiag cluster_c_;       // HARDCODED
  ClusterDRefreshResidual cluster_d_;    // HARDCODED
};
```

**Problem**: 4 clusters are hardcoded as member variables!

**Impact**:
- Cannot change cluster count (always 4)
- Cannot change cluster types
- Cannot disable clusters
- Cannot reorder clusters

---

## Key Findings

### 1. Configuration Flow Gap

**Current**:
```
sc_main → load_run_config() → SystemRunConfig
                                     ↓
                              DFTHybridSystem(name)  ← NO CONFIG!
                                     ↓
                              Hardcoded 4-Cluster
```

**Problem**: Configuration is loaded but NOT passed to DFTHybridSystem constructor!

### 2. Architecture Family Usage

**Where is "F1"/"F2"/"F3" used?**
- Loaded in `load_run_config()` as `config.architecture_family`
- Passed to `system.run_full_flow(run_config)`
- **Hypothesis**: Used at runtime, not at construction time

**Need to investigate**:
- Where does `architecture_family` affect behavior?
- Does it control cluster execution order?
- Does it control offload decisions?

### 3. Hardcoded Cluster Architecture

**Current Structure**:
```
ClusterGraphExecutor
├── cluster_a_: ClusterAOperatorSweep
├── cluster_b_: ClusterBReducedBuild
├── cluster_c_: ClusterCHardwareDiag
└── cluster_d_: ClusterDRefreshResidual
```

**Limitations**:
- Fixed 4 clusters
- Fixed cluster types
- Fixed member variable names
- Cannot support 2/3/5-cluster architectures

---

## Refactoring Strategy

### Option 1: Constructor-Time Configuration (Recommended)

**Pros**:
- Clean separation of configuration and execution
- Easier to test different architectures
- Follows SystemC best practices

**Cons**:
- Requires significant refactoring
- Need to change constructor signatures

**Approach**:
```cpp
// New constructor signature
DFTHybridSystem::DFTHybridSystem(
    sc_core::sc_module_name name,
    const ArchitectureConfig& arch_config  // NEW!
)
```

### Option 2: Runtime Configuration

**Pros**:
- Minimal changes to constructors
- Can reuse existing modules

**Cons**:
- Configuration and instantiation separated
- Harder to validate architecture at construction time
- May have unused modules

**Approach**:
```cpp
// Keep current constructor, configure at runtime
system.configure_architecture(arch_config);
system.run_full_flow(run_config);
```

### Option 3: Hybrid Approach (Recommended)

**Pros**:
- Backward compatible
- Gradual migration path
- Can support both old and new styles

**Cons**:
- More complex implementation
- Need to maintain two code paths temporarily

**Approach**:
```cpp
// Support both old and new constructors
DFTHybridSystem(sc_core::sc_module_name name);  // Old, uses default F2
DFTHybridSystem(sc_core::sc_module_name name, 
                const ArchitectureConfig& arch_config);  // New
```

---

## Next Steps

### Waiting for Background Tasks:
1. ✓ Configuration flow analysis (bg_f976cca9)
2. ✓ Cluster module structure (bg_ff397ae8)
3. ✓ Hardcoded parameter locations (bg_f50d3b15)
4. ✓ Compute unit switching logic (bg_b343dfd0)

### After Background Tasks Complete:
1. Synthesize findings into comprehensive analysis
2. Design ArchitectureConfig structure
3. Design ClusterFactory pattern
4. Create detailed refactoring plan

---

## Questions to Answer

1. **Where is architecture_family actually used?**
   - Need to grep for "architecture_family" usage
   - Understand F1/F2/F3 behavior differences

2. **How are compute units selected?**
   - CIM Array vs Traditional FPGA
   - Is it hardcoded or configurable?

3. **What is the cluster execution order?**
   - Always A→B→C→D?
   - Can it be changed?

4. **What configuration affects cluster behavior?**
   - offload_scope_override
   - resident_policy_override
   - graph_frontdoor_mode

---

## Files Identified So Far

### Configuration Entry
- `sc_main.cpp` (424 lines) - Configuration loading and main entry

### System Hierarchy
- `dft_hybrid_system.cpp` (23 lines) - Top-level system
- `chip_top.cpp` - FPGA chip container
- `cluster_graph_executor.cpp` - Cluster orchestration (HARDCODED 4-cluster)

### Cluster Implementations
- `cluster_a_operator_sweep.cpp` - h_psi/s_psi operator sweep
- `cluster_b_reduced_build.cpp` - H_sub/S_sub reduction
- `cluster_c_hardware_diag.cpp` - Eigensolver
- `cluster_d_refresh_residual.cpp` - Residual and refresh

### Compute Units
- `cim_array_core.cpp` - CIM Array with Ozaki-II
- `traditional_fpga_gemm_core.cpp` - Traditional FPGA GEMM
- `blocked_gemm_engine.cpp` - Blocked GEMM implementation

---

## Preliminary Refactoring Estimate

**Complexity**: Medium-High

**Files to Modify**: ~10-15 files
- Constructor signatures: 5 files
- Cluster instantiation: 2-3 files
- Configuration structures: 2-3 files
- Factory patterns: 2-3 files

**Lines of Code**: ~500-800 LOC changes

**Risk Level**: Medium
- SystemC module hierarchy changes are delicate
- Need to preserve timing semantics
- Backward compatibility concerns

**Estimated Time**: 3-5 days
- Day 1: Design ArchitectureConfig and factories
- Day 2-3: Implement refactoring
- Day 4: Testing and validation
- Day 5: Bug fixes and polish
