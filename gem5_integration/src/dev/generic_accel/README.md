# Generic Accelerator Device Model for gem5

This directory contains a generic accelerator device model for gem5 that replaces the QE-specific FPGA device.

**Status: MMIO Timed Stub** - The current implementation provides basic MMIO register access and a fixed-timing command completion model. DMA, descriptor parsing, TLM-2.0 bridge, and SystemC integration are planned but not yet implemented.

## Architecture

```
gem5 CPU
    |
    | MMIO
    v
GenericAccel (MMIO Device) [TIMED STUB]
    |
    |-- Control Registers (implemented)
    |-- DMA Engine (planned)
    |-- Command Queue (planned)
    |-- Completion Mailbox (partial)
    |
    | TLM-2.0 (planned)
    v
SystemC Generic Backend (planned)
    |
    |-- GraphExecutor
    |-- Accelerator Models
```

## Files

- `generic_accel.hh/cc` - gem5 device model
- `GenericAccel.py` - SimObject definition
- `SConscript` - Build configuration
- `generic_mmio_protocol.md` - MMIO register map

## Integration

The generic accelerator uses a standard MMIO protocol:

```
0x0000 - 0x0FFF: Control/Status
0x1000 - 0x1FFF: Command Queue
0x2000 - 0x2FFF: DMA Descriptor Ring
0x3000 - 0x3FFF: Completion Mailbox
0x4000 - 0x4FFF: Metrics Counters
```

## Usage

```python
# In gem5 config
from m5.objects import GenericAccel

accel = GenericAccel()
accel.pio_addr = 0x10000000
accel.dma_buffer_size = '16MB'
```

## Differences from QE-specific FPGA

| Feature | QE FPGA | GenericAccel |
|---------|---------|--------------|
| Op types | Hardcoded (h_psi, cdiaghg) | Generic (gemm, fft, eigen) |
| Architecture | 4-cluster | Configurable |
| Workload | QE SCF only | Any ComputeGraph |
| Protocol | QEBS env vars | JSON request/result |

## Implementation Status

### Completed
- Basic MMIO register read/write
- Control/Status/Version/Capabilities registers
- Command doorbell trigger
- Fixed-timing command completion (1 GFLOP default)
- gem5 SimObject integration and compilation

### Planned (Not Yet Implemented)
1. **DMA Engine**: Read command descriptors from guest memory
2. **Command Descriptor Parsing**: Parse JSON simulation requests
3. **TLM-2.0 Bridge**: Connect to SystemC generic backend
4. **Result JSON Writing**: Write simulation results back to memory
5. **Interrupt Handling**: Proper interrupt/completion notification
6. **gem5 Stats Integration**: Connect to gem5 statistics system
7. **Dynamic Timing Model**: Replace fixed 1-GFLOP stub with actual workload-based estimation
