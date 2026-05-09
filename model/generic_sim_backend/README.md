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

## gem5 + SystemC Closure Boundary

The L4 path is claim-gated. A trusted L4 result requires evidence that gem5
software wrote a GSIM command descriptor, GenericAccel ingested the descriptor
and request payload, the SystemC timing backend was invoked from that path, and
completion/result data was written back to guest-visible memory. Until those
items appear in `gem5.log` plus descriptor/completion artifacts, the backend
must emit a `blocked` / `blocked_prototype` verdict rather than a passed result.

Use `dse_v2.backends.gem5_systemc_adapter.Gem5SystemCClosureAdapter` or
`GenericSystemCBackend(mode="gem5_systemc_blocked")` to generate the blocked
verdict artifacts:

- `simulation_request.json`
- `simulation_result.json` with `status: "blocked"`
- `gem5_command_descriptor.json`
- `gem5_completion_descriptor.json`
- `gem5.log`
- `verdict.json`

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
