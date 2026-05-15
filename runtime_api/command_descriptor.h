#ifndef OFFLOAD_COMMAND_DESCRIPTOR_H
#define OFFLOAD_COMMAND_DESCRIPTOR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OFFLOAD_COMMAND_DESCRIPTOR_VERSION 0x00000001u
#define OFFLOAD_GSIM_MAGIC 0x4753494du
#define OFFLOAD_GSIM_DESCRIPTOR_VERSION 0x00000001u
#define OFFLOAD_GSIM_LEGACY_COMMAND_DESCRIPTOR_BYTES 48u

enum offload_opcode {
    OFFLOAD_OPCODE_GENERIC_WORKLOAD = 1,
    OFFLOAD_OPCODE_EXTENSION_DEFINED = 0x80000000u,
};

enum offload_gsim_command_type {
    OFFLOAD_GSIM_COMMAND_TYPE_GRAPH = 1,
    OFFLOAD_GSIM_COMMAND_TYPE_OP = 2,
    OFFLOAD_GSIM_COMMAND_TYPE_DMA = 3,
};

enum offload_gsim_descriptor_flag {
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_REQUEST_JSON = 1u << 0,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_RESULT_JSON = 1u << 1,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPLETION_DESC = 1u << 2,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_EXTENSION_PAYLOAD = 1u << 3,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_CANDIDATE_IDENTITY = 1u << 4,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPILE_SCHEDULE = 1u << 5,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_RUNTIME_SCHEDULE = 1u << 6,
    OFFLOAD_GSIM_DESCRIPTOR_FLAG_SIDECAR_DISPATCH = 1u << 7,
};

enum offload_control_policy {
    OFFLOAD_CONTROL_SYNC = 0,
    OFFLOAD_CONTROL_ASYNC_QUEUE = 1,
    OFFLOAD_CONTROL_POLLING = 2,
    OFFLOAD_CONTROL_INTERRUPT = 3,
};

enum offload_mmio_register {
    OFFLOAD_REG_CONTROL = 0x0000,
    OFFLOAD_REG_STATUS = 0x0004,
    OFFLOAD_REG_INTERRUPT = 0x0008,

    OFFLOAD_REG_DMA_SRC_LO = 0x0010,
    OFFLOAD_REG_DMA_SRC_HI = 0x0014,
    OFFLOAD_REG_DMA_DST_LO = 0x0018,
    OFFLOAD_REG_DMA_DST_HI = 0x001c,
    OFFLOAD_REG_DMA_SIZE = 0x0020,
    OFFLOAD_REG_DMA_CONTROL = 0x0024,

    OFFLOAD_REG_WORK_DIM0 = 0x0100,
    OFFLOAD_REG_WORK_DIM1 = 0x0104,
    OFFLOAD_REG_WORK_DIM2 = 0x0108,
    OFFLOAD_REG_WORK_DIM3 = 0x010c,
    OFFLOAD_REG_WORK_ITERATIONS = 0x0110,
    OFFLOAD_REG_WORK_PRECISION_BITS = 0x0114,
    OFFLOAD_REG_ACCELERATOR_HINT = 0x0118,
    OFFLOAD_REG_WORK_CMD = 0x011c,
    OFFLOAD_REG_WORK_STATUS = 0x0120,

    OFFLOAD_REG_WORK_DONE = 0x0130,
    OFFLOAD_REG_WORK_COMPLETIONS = 0x0134,
    OFFLOAD_REG_WORK_ERROR = 0x0138,
    OFFLOAD_REG_WORK_TOTAL_TIME = 0x013c,

    OFFLOAD_REG_ROI_CONTROL = 0x0300,
    OFFLOAD_REG_ROI_STATUS = 0x0304,
};

typedef struct offload_command_descriptor {
    uint32_t version;
    uint32_t opcode;
    uint32_t control_policy;
    uint32_t flags;

    uint32_t work_dim0;
    uint32_t work_dim1;
    uint32_t work_dim2;
    uint32_t work_dim3;
    uint32_t max_iterations;
    uint32_t precision_bits;
    uint32_t accelerator_hint;
    uint32_t reserved0;

    uint64_t input_addr;
    uint64_t output_addr;
    uint64_t payload_bytes;
} offload_command_descriptor;

typedef struct offload_runtime_metrics {
    uint64_t command_count;
    uint64_t completion_count;
    uint64_t mmio_read_count;
    uint64_t mmio_write_count;
    uint64_t dma_read_bytes;
    uint64_t dma_write_bytes;
    uint64_t polling_iterations;
    uint64_t interrupt_count;
    uint64_t host_wait_cycles;
    uint64_t device_busy_cycles;
} offload_runtime_metrics;

/*
 * Software-visible gem5 GenericAccel command ABI.
 *
 * The first 48 bytes intentionally match the legacy GSIM descriptor consumed by
 * existing gem5 runs.  Fields after workspace_size are optional extension
 * pointers.  A device must treat absent extension fields as zero when
 * cmd_desc_size is OFFLOAD_GSIM_LEGACY_COMMAND_DESCRIPTOR_BYTES.
 */
#pragma pack(push, 1)
typedef struct offload_gsim_command_descriptor {
    uint32_t magic;
    uint32_t version;
    uint32_t type;
    uint32_t flags;
    uint64_t request_addr;
    uint64_t result_addr;
    uint64_t workspace_addr;
    uint64_t workspace_size;
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
} offload_gsim_command_descriptor;

typedef struct offload_gsim_completion_descriptor {
    uint32_t magic;
    uint32_t status;
    uint64_t result_addr;
    uint64_t cycles;
    uint32_t error_code;
} offload_gsim_completion_descriptor;
#pragma pack(pop)

static inline offload_command_descriptor offload_command_descriptor_default(void) {
    offload_command_descriptor desc;
    desc.version = OFFLOAD_COMMAND_DESCRIPTOR_VERSION;
    desc.opcode = OFFLOAD_OPCODE_GENERIC_WORKLOAD;
    desc.control_policy = OFFLOAD_CONTROL_POLLING;
    desc.flags = 0;
    desc.work_dim0 = 8;
    desc.work_dim1 = 32;
    desc.work_dim2 = 1;
    desc.work_dim3 = 1;
    desc.max_iterations = 2;
    desc.precision_bits = 64;
    desc.accelerator_hint = 0;
    desc.reserved0 = 0;
    desc.input_addr = 0;
    desc.output_addr = 0;
    desc.payload_bytes = 0;
    return desc;
}

#ifdef __cplusplus
}
#endif

#endif
