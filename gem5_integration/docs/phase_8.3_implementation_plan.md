# Phase 8.3 Implementation Plan: SystemC Bridge

## Objective
Connect gem5 FPGA device to SystemC DFT model via TLM-2.0 interface for cycle-accurate co-simulation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ gem5 Simulation (C++)                                       │
│                                                              │
│  ┌──────────────┐         ┌─────────────────────────────┐  │
│  │ CPU          │◄───────►│ FPGAAcceleratorSE           │  │
│  │ (X86)        │  MMIO   │                             │  │
│  └──────────────┘         │  ┌───────────────────────┐  │  │
│                           │  │ TLM Initiator Socket  │  │  │
│                           │  └───────────┬───────────┘  │  │
│                           └──────────────┼──────────────┘  │
└────────────────────────────────────────┼─────────────────┘
                                         │ TLM-2.0
                                         │ Transactions
┌────────────────────────────────────────┼─────────────────┐
│ SystemC Simulation (C++)               │                  │
│                           ┌────────────┴──────────────┐   │
│                           │ TLM Target Socket         │   │
│                           │ (gem5_tlm_target)         │   │
│                           └────────────┬──────────────┘   │
│                                        │                  │
│  ┌─────────────────────────────────────▼───────────────┐ │
│  │ DFTHybridSystemGem5                                  │ │
│  │  ┌────────────────────────────────────────────────┐ │ │
│  │  │ ClusterGraphExecutor (4-Cluster Pipeline)      │ │ │
│  │  │  - Cluster A: CIM Array + h_psi (68%)          │ │ │
│  │  │  - Cluster B: Reduction (4%)                    │ │ │
│  │  │  - Cluster C: Eigensolver (23%)                 │ │ │
│  │  │  - Cluster D: Refresh (5%)                      │ │ │
│  │  └────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Tasks

### Task 8.3.1: Add TLM Support to gem5 FPGA Device
**File**: `src/dev/fpga/fpga_accelerator_se.hh`
- Add `#include <systemc>` and `#include <tlm>`
- Add TLM initiator socket member
- Add transaction methods: `sendTransaction()`, `handleResponse()`

### Task 8.3.2: Implement Transaction Forwarding
**File**: `src/dev/fpga/fpga_accelerator_se.cc`
- Convert MMIO writes to TLM transactions
- Forward to SystemC model via socket
- Handle blocking/non-blocking transport

### Task 8.3.3: Build SystemC Bridge Library
**File**: `gem5_integration/systemc_model/CMakeLists.txt`
- Enable gem5 mode compilation
- Link against gem5 libraries
- Build `libgem5_systemc_bridge.so`

### Task 8.3.4: Integrate SystemC into gem5 Build
**File**: `gem5/SConstruct` or `gem5/src/dev/fpga/SConscript`
- Add SystemC include paths
- Link SystemC library
- Link bridge library

### Task 8.3.5: Test TLM Communication
**File**: `configs/fpga_systemc_test.py`
- Create test configuration
- Send test transactions
- Verify SystemC model receives data

## Technical Challenges

### Challenge 1: gem5 + SystemC Integration
**Problem**: gem5 and SystemC have different event-driven simulation kernels
**Solution**: Use TLM-2.0 loosely-timed (LT) transport for synchronization

### Challenge 2: Memory Management
**Problem**: gem5 uses `Packet*`, SystemC uses `tlm_generic_payload*`
**Solution**: Create conversion layer in bridge

### Challenge 3: Simulation Time Synchronization
**Problem**: gem5 uses `Tick` (ps), SystemC uses `sc_time`
**Solution**: Convert at transaction boundary: `sc_time(ticks, SC_PS)`

## Data Flow

### MMIO Write Flow
```
1. CPU writes to 0xF0000000 (CONTROL register)
2. gem5 calls FPGAAcceleratorSE::write(PacketPtr pkt)
3. Extract data: nBands, nBasis, start command
4. Create TLM transaction:
   - Command: TLM_WRITE_COMMAND
   - Address: CMD_EXECUTE_C_BANDS
   - Data: {nBands, nBasis, ...}
5. Send via initiator socket: socket->b_transport(trans, delay)
6. SystemC model receives in gem5_tlm_target::b_transport()
7. Execute DFT computation in SystemC
8. Return response with cycle count
9. gem5 updates STATUS and CYCLES registers
10. CPU reads STATUS to check completion
```

## Interface Definition

### TLM Transaction Format
```cpp
struct FPGACommand {
    uint32_t cmd_type;      // 0=c_bands, 1=electrons
    uint32_t n_bands;
    uint32_t n_basis;
    uint64_t h_matrix_addr; // DMA address
    uint64_t s_matrix_addr;
    uint64_t result_addr;
};

struct FPGAResponse {
    uint32_t status;        // 0=success, 1=error
    uint64_t cycles;        // Execution cycles
    uint32_t error_code;
};
```

## Success Criteria
- ✅ gem5 compiles with SystemC support
- ✅ TLM transactions sent from gem5 to SystemC
- ✅ SystemC model receives and processes transactions
- ✅ Response data returned to gem5
- ✅ CPU can read FPGA status and results

## Estimated Effort
- Task 8.3.1: 1 hour (add TLM socket to gem5 device)
- Task 8.3.2: 2 hours (implement transaction forwarding)
- Task 8.3.3: 1 hour (build SystemC bridge library)
- Task 8.3.4: 2 hours (integrate into gem5 build system)
- Task 8.3.5: 1 hour (testing and validation)
- **Total**: 7 hours

## Dependencies
- gem5 compiled with SystemC support (HAVE_SYSTEMC=True)
- SystemC library installed (/opt/homebrew/lib/libsystemc.a)
- TLM-2.0 headers available
- DFTHybridSystemGem5 model compiled

## Next Steps
1. Start with Task 8.3.1: Add TLM socket to FPGAAcceleratorSE
2. Implement basic transaction send/receive
3. Test with simple ping-pong transaction
4. Integrate full DFT computation
5. Measure end-to-end latency

---
**Status**: 📋 Planning Complete, Ready to Implement
