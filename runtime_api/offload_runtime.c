#include "offload_runtime.h"

#include <string.h>

enum {
    QEBS_STATUS_READY = 1u << 0,
    QEBS_STATUS_BUSY = 1u << 1,
    QEBS_STATUS_ERROR = 1u << 2,
    QEBS_STATUS_COMPUTE_DONE = 1u << 4,
    QEBS_ROI_MARK_BEGIN = 1u << 1,
    QEBS_ROI_MARK_END = 1u << 2,
};

static size_t reg_index(uint32_t offset) {
    return (size_t)(offset / sizeof(uint32_t));
}

static int has_reg(const qebs_runtime* runtime, uint32_t offset) {
    return runtime != NULL && runtime->regs != NULL &&
           reg_index(offset) * sizeof(uint32_t) < runtime->reg_bytes;
}

static void mmio_write(qebs_runtime* runtime, uint32_t offset, uint32_t value) {
    if (has_reg(runtime, offset)) {
        runtime->regs[reg_index(offset)] = value;
    }
    if (runtime != NULL) {
        runtime->metrics.mmio_write_count++;
    }
}

static uint32_t mmio_read(qebs_runtime* runtime, uint32_t offset) {
    uint32_t value = 0;
    if (has_reg(runtime, offset)) {
        value = runtime->regs[reg_index(offset)];
    }
    if (runtime != NULL) {
        runtime->metrics.mmio_read_count++;
    }
    return value;
}

static uint64_t deterministic_device_cycles(const qebs_command_descriptor* desc) {
    uint64_t bands = desc->n_bands ? desc->n_bands : 1;
    uint64_t basis = desc->n_basis ? desc->n_basis : 1;
    uint64_t kpoints = desc->n_kpoints ? desc->n_kpoints : 1;
    uint64_t iterations = desc->max_iterations ? desc->max_iterations : 1;
    return bands * basis * kpoints * iterations * 100u;
}

static void qebs_m5_reset_stats(void) {
    /* Link a platform-specific m5op implementation here for gem5 SE/FS runs. */
}

static void qebs_m5_dump_stats(void) {
    /* Link a platform-specific m5op implementation here for gem5 SE/FS runs. */
}

void qebs_runtime_init(qebs_runtime* runtime,
                       volatile uint32_t* register_window,
                       size_t register_window_bytes) {
    if (runtime == NULL) {
        return;
    }
    memset(runtime, 0, sizeof(*runtime));
    runtime->regs = register_window;
    runtime->reg_bytes = register_window_bytes;
    if (register_window != NULL && register_window_bytes >= 0x400) {
        mmio_write(runtime, QEBS_REG_STATUS, QEBS_STATUS_READY);
    }
}

void qebs_runtime_set_use_m5ops(qebs_runtime* runtime, int enabled) {
    if (runtime != NULL) {
        runtime->use_m5ops = enabled != 0;
    }
}

void qebs_runtime_mark_roi_begin(qebs_runtime* runtime) {
    if (runtime == NULL) {
        return;
    }
    if (runtime->use_m5ops) {
        qebs_m5_reset_stats();
    }
    mmio_write(runtime, QEBS_REG_ROI_CONTROL, QEBS_ROI_MARK_BEGIN);
}

void qebs_runtime_mark_roi_end(qebs_runtime* runtime) {
    if (runtime == NULL) {
        return;
    }
    mmio_write(runtime, QEBS_REG_ROI_CONTROL, QEBS_ROI_MARK_END);
    if (runtime->use_m5ops) {
        qebs_m5_dump_stats();
    }
}

int qebs_runtime_submit_sync(qebs_runtime* runtime,
                             const qebs_command_descriptor* descriptor) {
    if (runtime == NULL || descriptor == NULL) {
        return -1;
    }
    if (descriptor->version != QEBS_COMMAND_DESCRIPTOR_VERSION) {
        return -2;
    }

    const uint64_t device_cycles = deterministic_device_cycles(descriptor);
    const uint64_t payload_bytes =
        descriptor->payload_bytes ? descriptor->payload_bytes :
        (uint64_t)descriptor->n_bands * (uint64_t)descriptor->n_basis * 16u;

    mmio_write(runtime, QEBS_REG_ELECTRONS_N_BANDS, descriptor->n_bands);
    mmio_write(runtime, QEBS_REG_ELECTRONS_N_BASIS, descriptor->n_basis);
    mmio_write(runtime, QEBS_REG_ELECTRONS_N_KPOINTS, descriptor->n_kpoints);
    mmio_write(runtime, QEBS_REG_ELECTRONS_N_SPIN, descriptor->n_spin);
    mmio_write(runtime, QEBS_REG_ELECTRONS_MAX_ITER, descriptor->max_iterations);
    mmio_write(runtime, QEBS_REG_ELECTRONS_MIXING_NDIM, descriptor->mixing_ndim);
    mmio_write(runtime, QEBS_REG_ELECTRONS_ENABLE_CIM, descriptor->enable_cim);

    runtime->metrics.command_count++;
    runtime->metrics.dma_read_bytes += payload_bytes;
    runtime->metrics.dma_write_bytes += payload_bytes / 2u;
    runtime->metrics.device_busy_cycles += device_cycles;

    mmio_write(runtime, QEBS_REG_ELECTRONS_CMD, 1);
    mmio_write(runtime, QEBS_REG_STATUS, QEBS_STATUS_BUSY);

    if (descriptor->control_policy == QEBS_CONTROL_INTERRUPT) {
        runtime->metrics.interrupt_count++;
    } else {
        uint64_t polls = descriptor->control_policy == QEBS_CONTROL_POLLING ? 3u : 1u;
        for (uint64_t i = 0; i < polls; ++i) {
            (void)mmio_read(runtime, QEBS_REG_ELECTRONS_STATUS);
            runtime->metrics.polling_iterations++;
        }
    }

    runtime->metrics.host_wait_cycles += device_cycles / 10u + 1u;
    runtime->metrics.completion_count++;
    mmio_write(runtime, QEBS_REG_ELECTRONS_CONVERGED, 1);
    mmio_write(runtime, QEBS_REG_ELECTRONS_ITERATIONS, descriptor->max_iterations);
    mmio_write(runtime, QEBS_REG_ELECTRONS_TOTAL_TIME, (uint32_t)device_cycles);
    mmio_write(runtime, QEBS_REG_STATUS, QEBS_STATUS_READY | QEBS_STATUS_COMPUTE_DONE);
    return 0;
}

void qebs_runtime_write_report_json(FILE* out,
                                    const char* schema_version,
                                    const char* workload_id,
                                    const char* adapter,
                                    const qebs_runtime_metrics* metrics) {
    const qebs_runtime_metrics zero = {0};
    const qebs_runtime_metrics* m = metrics != NULL ? metrics : &zero;
    if (out == NULL) {
        return;
    }
    fprintf(out,
            "{\n"
            "  \"schema_version\": \"%s\",\n"
            "  \"workload_id\": \"%s\",\n"
            "  \"adapter\": \"%s\",\n"
            "  \"claim_ceiling\": \"proxy_runtime_smoke_only\",\n"
            "  \"metrics\": {\n"
            "    \"command_count\": %llu,\n"
            "    \"completion_count\": %llu,\n"
            "    \"mmio_read_count\": %llu,\n"
            "    \"mmio_write_count\": %llu,\n"
            "    \"dma_read_bytes\": %llu,\n"
            "    \"dma_write_bytes\": %llu,\n"
            "    \"polling_iterations\": %llu,\n"
            "    \"interrupt_count\": %llu,\n"
            "    \"host_wait_cycles\": %llu,\n"
            "    \"device_busy_cycles\": %llu\n"
            "  },\n"
            "  \"non_claims\": [\n"
            "    \"no_qe_equivalent_scf_claim\",\n"
            "    \"no_cycle_accuracy_claim\",\n"
            "    \"no_rtl_hls_board_or_asic_implementation_claim\"\n"
            "  ]\n"
            "}\n",
            schema_version != NULL ? schema_version : "qebs_proxy_runtime_report_v0",
            workload_id != NULL ? workload_id : "generic_proxy",
            adapter != NULL ? adapter : "generic",
            (unsigned long long)m->command_count,
            (unsigned long long)m->completion_count,
            (unsigned long long)m->mmio_read_count,
            (unsigned long long)m->mmio_write_count,
            (unsigned long long)m->dma_read_bytes,
            (unsigned long long)m->dma_write_bytes,
            (unsigned long long)m->polling_iterations,
            (unsigned long long)m->interrupt_count,
            (unsigned long long)m->host_wait_cycles,
            (unsigned long long)m->device_busy_cycles);
}
