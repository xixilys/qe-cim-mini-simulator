#ifndef QEBS_COMMAND_DESCRIPTOR_H
#define QEBS_COMMAND_DESCRIPTOR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define QEBS_COMMAND_DESCRIPTOR_VERSION 0x00000001u
#define OFFLOAD_COMMAND_DESCRIPTOR_VERSION QEBS_COMMAND_DESCRIPTOR_VERSION

enum qebs_opcode {
    QEBS_OPCODE_GENERIC_SCF = 1,
    QEBS_OPCODE_ADAPTER_DEFINED = 0x80000000u,
};
typedef enum qebs_opcode offload_opcode;
#define OFFLOAD_OPCODE_GENERIC_WORKLOAD QEBS_OPCODE_GENERIC_SCF
#define OFFLOAD_OPCODE_ADAPTER_DEFINED QEBS_OPCODE_ADAPTER_DEFINED

enum qebs_control_policy {
    QEBS_CONTROL_SYNC = 0,
    QEBS_CONTROL_ASYNC_QUEUE = 1,
    QEBS_CONTROL_POLLING = 2,
    QEBS_CONTROL_INTERRUPT = 3,
};
typedef enum qebs_control_policy offload_control_policy;
#define OFFLOAD_CONTROL_SYNC QEBS_CONTROL_SYNC
#define OFFLOAD_CONTROL_ASYNC_QUEUE QEBS_CONTROL_ASYNC_QUEUE
#define OFFLOAD_CONTROL_POLLING QEBS_CONTROL_POLLING
#define OFFLOAD_CONTROL_INTERRUPT QEBS_CONTROL_INTERRUPT

enum qebs_mmio_register {
    QEBS_REG_CONTROL = 0x0000,
    QEBS_REG_STATUS = 0x0004,
    QEBS_REG_INTERRUPT = 0x0008,

    QEBS_REG_DMA_SRC_LO = 0x0010,
    QEBS_REG_DMA_SRC_HI = 0x0014,
    QEBS_REG_DMA_DST_LO = 0x0018,
    QEBS_REG_DMA_DST_HI = 0x001c,
    QEBS_REG_DMA_SIZE = 0x0020,
    QEBS_REG_DMA_CONTROL = 0x0024,

    QEBS_REG_ELECTRONS_N_BANDS = 0x0100,
    QEBS_REG_ELECTRONS_N_BASIS = 0x0104,
    QEBS_REG_ELECTRONS_N_KPOINTS = 0x0108,
    QEBS_REG_ELECTRONS_N_SPIN = 0x010c,
    QEBS_REG_ELECTRONS_MAX_ITER = 0x0110,
    QEBS_REG_ELECTRONS_CONV_THR = 0x0114,
    QEBS_REG_ELECTRONS_DIAG_THR = 0x0118,
    QEBS_REG_ELECTRONS_MIXING_BETA = 0x011c,
    QEBS_REG_ELECTRONS_MIXING_NDIM = 0x0120,
    QEBS_REG_ELECTRONS_ENABLE_CIM = 0x0124,
    QEBS_REG_ELECTRONS_CMD = 0x0128,
    QEBS_REG_ELECTRONS_STATUS = 0x012c,

    QEBS_REG_ELECTRONS_CONVERGED = 0x0130,
    QEBS_REG_ELECTRONS_ITERATIONS = 0x0134,
    QEBS_REG_ELECTRONS_FINAL_ERROR = 0x0138,
    QEBS_REG_ELECTRONS_TOTAL_ENERGY = 0x013c,
    QEBS_REG_ELECTRONS_TOTAL_TIME = 0x0140,
    QEBS_REG_ELECTRONS_CBANDS_TIME = 0x0144,
    QEBS_REG_ELECTRONS_SUMBAND_TIME = 0x0148,
    QEBS_REG_ELECTRONS_MIXRHO_TIME = 0x014c,

    QEBS_REG_ROI_CONTROL = 0x0300,
    QEBS_REG_ROI_STATUS = 0x0304,
};

typedef struct qebs_command_descriptor {
    uint32_t version;
    uint32_t opcode;
    uint32_t control_policy;
    uint32_t flags;

    uint32_t n_bands;
    uint32_t n_basis;
    uint32_t n_kpoints;
    uint32_t n_spin;
    uint32_t max_iterations;
    float conv_threshold;
    float diag_threshold;
    float mixing_beta;
    uint32_t mixing_ndim;
    uint32_t enable_cim;

    uint64_t input_addr;
    uint64_t output_addr;
    uint64_t payload_bytes;
} qebs_command_descriptor;
typedef qebs_command_descriptor offload_command_descriptor;

typedef struct qebs_runtime_metrics {
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
} qebs_runtime_metrics;
typedef qebs_runtime_metrics offload_runtime_metrics;

static inline qebs_command_descriptor qebs_command_descriptor_default(void) {
    qebs_command_descriptor desc;
    desc.version = QEBS_COMMAND_DESCRIPTOR_VERSION;
    desc.opcode = QEBS_OPCODE_GENERIC_SCF;
    desc.control_policy = QEBS_CONTROL_POLLING;
    desc.flags = 0;
    desc.n_bands = 8;
    desc.n_basis = 32;
    desc.n_kpoints = 1;
    desc.n_spin = 1;
    desc.max_iterations = 2;
    desc.conv_threshold = 1.0e-3f;
    desc.diag_threshold = 1.0e-6f;
    desc.mixing_beta = 0.7f;
    desc.mixing_ndim = 8;
    desc.enable_cim = 1;
    desc.input_addr = 0;
    desc.output_addr = 0;
    desc.payload_bytes = 0;
    return desc;
}

static inline offload_command_descriptor offload_command_descriptor_default(void) {
    return qebs_command_descriptor_default();
}

#ifdef __cplusplus
}
#endif

#endif
