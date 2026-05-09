# Generic SystemC Simulation Backend

Generic SystemC/gem5 simulation backend for DSE framework.

## Architecture

```
Python DSE Framework
    |
    | JSON Request
    v
GenericSystemCBackend (Python)
    |
    | subprocess.run()
    v
generic_sim (C++ executable)
    |
    |-- SimTop
        |-- Host Model
        |-- Interconnect Model
        |-- Memory System
        |-- Accelerator Devices
        |   |-- GPUAccelerator
        |   |-- FPGAAccelerator
        |   |-- CIMAccelerator
        |   |-- GenericAccelerator
        |-- Graph Executor
        |-- Trace Recorder
    |
    | JSON Result
    v
Python DSE Framework
```

## Build

```bash
cd model/generic_sim_backend
mkdir -p build && cd build
cmake ..
make -j4
```

## Usage

### Standalone

```bash
./generic_sim \
  --request path/to/request.json \
  --result path/to/result.json
```

### From Python

```python
from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend

backend = GenericSystemCBackend()
result = backend.evaluate(design_point, compute_graph)
```

## JSON Schema

- Request: `schemas/simulation_request_v1.json`
- Result: `schemas/simulation_result_v1.json`

## Fidelity Levels

- L1: Analytical model (Python)
- L2: Python TLM model
- L3: Standalone SystemC (this backend)
- L4: gem5 + SystemC co-simulation

## Supported Operations

- gemm
- fft
- eigen
- reduction
- elementwise
- transfer
- generic_op

## Supported Accelerator Types

- gpu
- fpga
- cim
- asic
- cpu
