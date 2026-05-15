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

### Python reference sidecar

The sidecar Python model consumes the same `gsim.request.v1` request emitted by
`GenericSystemCBackend` and produces a replayable model invocation record plus
deterministic numerical/timing artifacts:

```bash
python3 model/generic_sim_backend/tools/python_reference_model.py \
  --request path/to/simulation_request.json \
  --result path/to/python_model_result.json \
  --trace path/to/python_model_trace.json
```

Output is described by
`schemas/systemc_python_model_contract_v1.json`.  The contract intentionally
marks its claim boundary as `model_contract_and_projection_only`:

- `trusted_speedup: false`
- `trusted_qe_correctness: false`
- `requires_l4_full_flow_for_trusted_speedup: true`
- `requires_external_correctness_oracle_for_qe: true`

This prevents a timing-only C++ result, or a standalone Python reference run,
from being mistaken for QE physics correctness or L4 gem5 full-flow closure.

## JSON Schema

- Request: `schemas/simulation_request_v1.json`
- Result: `schemas/simulation_result_v1.json`
- Python sidecar contract: `schemas/systemc_python_model_contract_v1.json`

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
