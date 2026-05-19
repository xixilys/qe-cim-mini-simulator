# Generic MMIO Protocol for Accelerator Device

## Register Map

### Control/Status (0x0000 - 0x0FFF)

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0x0000 | REG_CONTROL | RW | Device control |
| 0x0004 | REG_STATUS | RO | Device status |
| 0x0008 | REG_VERSION | RO | Protocol version |
| 0x000C | REG_CAPABILITIES | RO | Device capabilities |

### Command Queue (0x1000 - 0x1FFF)

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0x1000 | REG_CMD_DOORBELL | WO | Submit command |
| 0x1004 | REG_CMD_DESC_ADDR_LO | RW | Command descriptor address (low) |
| 0x1008 | REG_CMD_DESC_ADDR_HI | RW | Command descriptor address (high) |
| 0x100C | REG_CMD_DESC_SIZE | RW | Command descriptor size |
| 0x1010 | REG_CMD_QUEUE_HEAD | RO | Queue head pointer |
| 0x1014 | REG_CMD_QUEUE_TAIL | RO | Queue tail pointer |

### DMA Engine (0x2000 - 0x2FFF)

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0x2000 | REG_DMA_CTRL | RW | DMA control |
| 0x2004 | REG_DMA_STATUS | RO | DMA status |
| 0x2008 | REG_DMA_SRC_LO | RW | Source address (low) |
| 0x200C | REG_DMA_SRC_HI | RW | Source address (high) |
| 0x2010 | REG_DMA_DST_LO | RW | Destination address (low) |
| 0x2014 | REG_DMA_DST_HI | RW | Destination address (high) |
| 0x2018 | REG_DMA_SIZE | RW | Transfer size |

### Completion Mailbox (0x3000 - 0x3FFF)

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0x3000 | REG_COMP_STATUS | RO | Completion status |
| 0x3004 | REG_COMP_DESC_ADDR_LO | RW | Completion descriptor address (low) |
| 0x3008 | REG_COMP_DESC_ADDR_HI | RW | Completion descriptor address (high) |
| 0x300C | REG_COMP_ERROR_CODE | RO | Error code |

### Metrics (0x4000 - 0x4FFF)

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0x4000 | REG_METRIC_CYCLES | RO | Total cycles |
| 0x4004 | REG_METRIC_OPS | RO | Total operations |
| 0x4008 | REG_METRIC_BYTES_READ | RO | Bytes read |
| 0x400C | REG_METRIC_BYTES_WRITTEN | RO | Bytes written |

## Command Descriptor Format

```c
struct CommandDescriptor {
    uint32_t magic;        // 'GSIM' = 0x4753494D
    uint32_t version;      // 1
    uint32_t type;         // 1=graph, 2=op, 3=dma
    uint32_t flags;
    uint64_t request_addr;  // Address of simulation request JSON
    uint64_t result_addr;   // Address for simulation result JSON
    uint64_t workspace_addr;// Address of workspace memory
    uint64_t workspace_size;
    // Optional V1 extension fields.  Descriptors may stop after workspace_size
    // for legacy 48-byte requests; extended descriptors expose schedule and
    // sidecar payloads without adding application-specific ABI fields.
    uint64_t extension_payload_addr;
    uint64_t extension_payload_bytes;
    uint64_t candidate_identity_addr;
    uint64_t candidate_identity_bytes;
    uint64_t compile_schedule_addr;
    uint64_t compile_schedule_bytes;
    uint64_t runtime_schedule_addr;
    uint64_t runtime_schedule_bytes;
    uint64_t sidecar_dispatch_addr;
    uint64_t sidecar_dispatch_bytes;
};
```

### Descriptor flags

| Bit | Name | Meaning |
|-----|------|---------|
| 0 | `REQUEST_JSON` | `request_addr` points at the simulation request JSON. |
| 1 | `RESULT_JSON` | `result_addr` points at the result JSON buffer. |
| 2 | `COMPLETION_DESC` | Completion descriptor writeback is expected. |
| 3 | `EXTENSION_PAYLOAD` | Generic plugin/adapter extension payload is present. |
| 4 | `CANDIDATE_IDENTITY` | Candidate identity payload is present. |
| 5 | `COMPILE_SCHEDULE` | Compile-time schedule payload is present. |
| 6 | `RUNTIME_SCHEDULE` | Runtime scheduling payload is present. |
| 7 | `SIDECAR_DISPATCH` | SystemC/Python sidecar dispatch metadata is present. |

Candidate identity, schedule, adapter extension payloads, and sidecar model
details remain JSON payloads.  The C/gem5 ABI only records generic pointer/size
pairs so workload-specific semantics do not become mandatory core fields.

## Completion Descriptor Format

```c
struct CompletionDescriptor {
    uint32_t magic;        // 'GSIM' = 0x4753494D
    uint32_t status;       // 0=success, 1=error
    uint64_t result_addr;  // Address of result JSON
    uint64_t cycles;       // Execution cycles
    uint32_t error_code;
};
```

## Usage Flow

1. CPU writes simulation request JSON to memory
2. CPU writes command descriptor to command queue
3. CPU rings doorbell (writes REG_CMD_DOORBELL)
4. Accelerator reads request JSON
5. Accelerator executes simulation
6. Accelerator writes result JSON
7. Accelerator writes completion descriptor
8. Accelerator triggers interrupt (optional)
9. CPU reads completion status
10. CPU reads result JSON

## Claim Boundary

The register map above is the required L4 descriptor/request/completion
contract. A run is trusted only when the log proves all of these events:

1. `descriptor_read`: GenericAccel read the GSIM command descriptor from guest
   memory.
2. `uarch_request_decode`: GenericAccel parsed the request payload and built the
   microarchitecture schedule.
3. `microarchitecture_execute`: the in-gem5 microarchitecture model executed
   the scheduled micro-ops from the device path.
4. `completion_writeback`: the result JSON and completion descriptor were
   written back to guest-visible memory.

The extended feasibility-spike path also logs these observability markers when
the corresponding descriptor flags or JSON payloads are present:

- `candidate_identity_trace`
- `compile_schedule_trace`
- `runtime_schedule_trace`
- `sidecar_dispatch_trace`
- `extension_payload_trace`

These markers are integration evidence for `vertical_slice_only` rows.  They do
not by themselves prove numerical correctness, trusted speedup, or release
closure.

`extension_payload_trace` is a transport-only signal: it shows that
adapter-owned metadata moved through the JSON extension lane.  The generic C ABI
and GenericAccel device do not parse or re-emit workload-specific numeric
evidence, and the DSE runner must separately validate independent source
artifacts plus numerical deltas before any correctness claim is eligible.

If any item is missing, the correct result is a blocked verdict, not an
L4-complete claim.
