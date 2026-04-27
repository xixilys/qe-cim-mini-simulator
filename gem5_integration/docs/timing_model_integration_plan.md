# Timing-Accurate SystemC Model Integration for gem5

## Current Status

### What We Have
- **Timing-accurate stub model**: Cycle-accurate timing in gem5 (USE_SYSTEMC build)
- **TLM transaction path**: gem5 → TLM → Stub (timing-accurate)
- **Cluster timing model**: Cluster A/B/C/D with accurate per-operation timing
- **Register access latency**: Per-address-range timing annotations
- **Computation time calculation**: Full SCF iteration timing with convergence modeling

### Timing Parameters (Implemented)
| Cluster | Time | Notes |
|---------|------|-------|
| Cluster A | 500 ps/pair | Operator sweep |
| Cluster B | 250 ps/panel | Reduced build |
| Cluster C | 10000 ps/band | Hardware diag |
| Cluster D | 150 ps | Residual refresh |
| K-point overhead | 50 ns | Per k-point |
| Mix/sum | 500 ns | Per iteration |

### Register Latencies (Implemented)
| Range | Latency |
|-------|---------|
| Control/Status | 5 ns |
| Configuration | 10 ns |
| DMA registers | 10 ns |
| Electrons cmd | 50 ns |

## Timing Model Architecture

### gem5 Side
```
TimingSimpleCPU → PCIe transaction → DMA/PIO latency → FPGA device
                    ↓
              gem5 cycle count
```

### SystemC Side
```
TLM transaction → register read/write
                    ↓
              Hardware latency model
                    ↓
              Cycle-accurate response
```

### Synchronization Points
1. **Transaction initiation**: gem5 tick → SystemC time
2. **Transaction completion**: SystemC time → gem5 tick (via callback)
3. **Interrupt latency**: SystemC interrupt → gem5 interrupt handling

## Implementation Plan

### Phase 1: Enable Timing CPU Mode
```python
# configs/fpga_fs_pci_smoke.py
system.cpu = X86TimingSimpleCPU()  # Instead of AtomicSimpleCPU
system.mem_mode = 'timing'
```

### Phase 2: Add TLM Delay Annotations
```cpp
// In gem5_tlm_target.cpp
void Gem5TLMTarget::b_transport(...) {
    // Add realistic delay based on register access
    if (addr >= 0x100 && addr < 0x200) {
        // Control register: 1 cycle
        delay += sc_time(1, SC_NS);
    } else if (addr >= 0x200 && addr < 0x300) {
        // Data register: 10 cycles (memory access)
        delay += sc_time(10, SC_NS);
    }
}
```

### Phase 3: Cycle-Accurate DFT Model
```cpp
// In dft_hybrid_system_gem5.cpp
SCFState DFTHybridSystemGem5::execute_electrons_from_gem5(...) {
    // For each k-point (k):
    for (int ik = 0; ik < req.n_kpoints; ik++) {
        // Cluster A: Operator sweep - 100 cycles per band pair
        wait(100 * req.n_bands * req.n_basis / 16, SC_NS);

        // Cluster B: Reduced build - 50 cycles per panel
        wait(50 * req.n_basis / 8, SC_NS);

        // Cluster C: Hardware diagonalization - variable
        wait(200 + 10 * req.n_bands, SC_NS);

        // Cluster D: Residual refresh - 30 cycles
        wait(30, SC_NS);
    }
}
```

### Phase 4: gem5-SystemC Time Synchronization
```cpp
// In fpga_accelerator.cc
void FPGAAccelerator::sendTLMTransaction(...) {
    sc_core::sc_time delay;

    // Synchronize: gem5 tick (1ns = 1ns in this model)
    // Convert gem5 tick to SystemC time
    sc_core::sc_time gem5_time(curTick(), SC_NS);

    tlmMediator->tlmSocket->b_transport(trans, delay);

    // Schedule gem5 event after SystemC completes
    // 1 SystemC ns = 1 gem5 tick (configurable ratio)
    Tick gem5_delay = (delay.to_seconds() * 1e9);
    schedule(tlmResponseEvent, curTick() + gem5_delay);
}
```

## Timing Parameters

### FPGA Register Access Latency
| Register Range | Access Type | Latency |
|----------------|-------------|---------|
| 0x000-0x0FF    | Control/Status | 1-5 ns |
| 0x100-0x1FF    | Config | 10-50 ns |
| 0x200-0x2FF    | Data | 100-500 ns |
| 0x300+         | Matrix | 1-10 μs |

### DFT Computation Timing
| Operation | Cycles | Time @ 200MHz |
|-----------|--------|---------------|
| Cluster A (op sweep) | 100/pair | 500 ps/pair |
| Cluster B (red build) | 50/panel | 250 ps/panel |
| Cluster C (diag) | 200+10n | 1-5 ns |
| Cluster D (refresh) | 30 | 150 ps |

### DMA Transfer Timing
| Size | Bandwidth | Time |
|------|-----------|------|
| 64B  | 4 GB/s    | 16 ns |
| 1KB  | 4 GB/s    | 250 ns |
| 4KB  | 4 GB/s    | 1 μs |
| 64KB | 4 GB/s    | 16 μs |

## Verification Plan

### Test 1: Timing CPU Mode
```bash
GEM5_CPU_TYPE=timing GEM5_MAX_TICKS=1000000000000 ./gem5.opt ...
# Verify: gem5 reports correct cycle counts
```

### Test 2: TLM Latency Propagation
```bash
# Check DPRINTF output
TLM transaction: delay=XXX ns
gem5 event scheduled: tick=XXX
```

### Test 3: End-to-End Timing
```bash
# Compare gem5 time vs SystemC time
gem5 reported: 1234567 ticks
SystemC time:  1234.567 μs
# Should match within 1%
```

## Files to Modify

1. `fpga_accelerator.cc` - Add timing annotations
2. `fpga_accelerator.hh` - Add timing parameters
3. `configs/fpga_fs_pci_smoke.py` - Switch to timing CPU
4. `gem5_tlm_target.cpp` - Add delay annotations
5. `dft_hybrid_system_gem5.cpp` - Cycle-accurate computation

## Implementation Status

### Phase 1: Enable Timing CPU Mode ✅
```python
# configs/fpga_fs_pci_smoke.py
system.cpu = X86TimingSimpleCPU()  # Timing CPU mode
system.mem_mode = 'timing'
```

### Phase 2: Add TLM Delay Annotations ✅
```cpp
// In fpga_accelerator.cc - Timing-accurate stub
static double get_register_latency(uint64_t addr) {
    if (addr >= 0x0000 && addr < 0x0100)
        return CTRL_REG_LATENCY_NS;  // 5 ns
    else if (addr == 0x0128)
        return ELECTRONS_CMD_LATENCY_NS;  // 50 ns
    // ...
}
```

### Phase 3: Cycle-Accurate DFT Model ✅
```cpp
// In fpga_accelerator.cc
static uint64_t calculate_electrons_time_ns(...) {
    // For each k-point: Cluster A + B + C + D timing
    // For each iteration: sum_band + mix_rho timing
    // Convergence check with exponential decay
}
```

### Phase 4: gem5-SystemC Time Synchronization ✅
```cpp
// In fpga_accelerator.cc - sendTLMTransaction
sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
tlmMediator->tlmSocket->b_transport(trans, delay);
Tick gem5_delay = delay.value() * 1000;
schedule(tlmResponseEvent, curTick() + gem5_delay);
```

## Next Steps

### For Full SystemC Model (x86_64 Linux)
1. Build SystemC model on x86_64 Linux host
2. Create `libgem5_systemc_bridge.a` for x86_64
3. Link against gem5 on Linux for real SystemC timing

### For Enhanced Timing Accuracy
1. Add memory bandwidth modeling to DMA transfers
2. Implement cache coherency timing
3. Add power/energy modeling
4. Validate against real FPGA measurements
