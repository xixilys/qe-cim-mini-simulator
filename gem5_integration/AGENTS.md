# AGENTS Guide - gem5 Integration

## Purpose

gem5 + SystemC co-simulation platform for CPU-FPGA heterogeneous system validation. Provides full-system simulation where gem5 models the CPU executing QE, and SystemC models the FPGA accelerator with 4-Cluster pipeline.

**Key Capabilities:**
- gem5 CPU simulation with QE offload hooks
- SystemC FPGA accelerator model (TLM-2.0)
- CPU-FPGA communication via PCIe/DMA simulation
- End-to-end performance evaluation for c_bands offloading

## Directory Structure

```
gem5_integration/
├── src/dev/fpga/              # gem5 FPGA device model
│   ├── fpga_accelerator.hh    # Device header
│   ├── fpga_accelerator.cc    # Device implementation
│   ├── FPGAAccelerator.py     # Python configuration
│   └── SConscript             # Build config
├── configs/fpga/              # gem5 system configurations
│   └── qe_fpga_system.py      # QE+FPGA system config
├── systemc_model/             # SystemC TLM model
│   ├── include/               # Headers (gem5_tlm_target, bridge)
│   ├── src/                   # Implementation
│   └── CMakeLists.txt         # CMake build
├── qe_integration/            # QE code hooks
│   ├── fpga_offload.h/.c      # C offload API
│   ├── fpga_offload_module.f90 # Fortran interface
│   ├── c_bands_fpga.patch     # QE patch
│   └── Makefile               # Build script
├── docker/                    # Docker environment
├── docs/                      # Integration docs
├── scripts/                   # Helper scripts
└── m5out*/                    # Simulation outputs
```

## Build Systems

- **gem5**: SCons (`scons build/X86/gem5.opt`)
- **SystemC model**: CMake
- **QE integration**: Makefile
- **Docker**: `docker-compose.yml`

## Quick Start

```bash
# Build SystemC model
cd gem5_integration/systemc_model
mkdir build && cd build
cmake .. -DCMAKE_PREFIX_PATH=/opt/systemc-2.3.3
make -j4

# Run standalone test
./gem5_systemc_standalone

# Build QE integration
cd ../qe_integration
make
```

## Key Files

- `src/dev/fpga/fpga_accelerator.cc` - gem5 FPGA device
- `systemc_model/src/dft_hybrid_system_gem5.cpp` - SystemC accelerator
- `configs/fpga/qe_fpga_system.py` - System configuration
- `qe_integration/fpga_offload.c` - QE offload driver

## Integration Points

- **With model/**: SystemC model reuses `model/qe_band_solver_model/` architecture
- **With soft/qe-7.5/**: QE patch applied to workspace copy
- **With docs/**: Architecture specs in `docs/architecture/`

## Critical Rules

- Do not modify system gem5 installation; use vendored tree
- QE patch targets `soft/qe-7.5/` only
- Simulation outputs (m5out*) are ephemeral; archive important results
- Docker environment is optional but recommended for reproducibility

## Documentation

- Architecture: `docs/overview/gem5_systemc_cosim_architecture_v1.md`
- Roadmap: `docs/overview/gem5_systemc_implementation_roadmap.md`
- API: `qe_integration/fpga_offload.h`

## Next Steps

- For SystemC model: see `model/qe_band_solver_model/AGENTS.md`
- For QE workspace: see `soft/qe-7.5/` (instrumented copy)
- For architecture: see `docs/architecture/AGENTS.md`
