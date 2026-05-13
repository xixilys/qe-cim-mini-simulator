#include "offload_runtime.h"

#include <string.h>

enum {
    OFFLOAD_STATUS_READY = 1u << 0,
    OFFLOAD_STATUS_BUSY = 1u << 1,
    OFFLOAD_STATUS_ERROR = 1u << 2,
    OFFLOAD_STATUS_COMPUTE_DONE = 1u << 4,
    OFFLOAD_ROI_MARK_BEGIN = 1u << 1,
    OFFLOAD_ROI_MARK_END = 1u << 2,
};

static size_t reg_index(uint32_t offset) {
    return (size_t)(offset / sizeof(uint32_t));
}

static int has_reg(const offload_runtime* runtime, uint32_t offset) {
    return runtime != NULL && runtime->regs != NULL &&
           reg_index(offset) * sizeof(uint32_t) < runtime->reg_bytes;
}

static void mmio_write(offload_runtime* runtime, uint32_t offset, uint32_t value) {
    if (has_reg(runtime, offset)) {
        runtime->regs[reg_index(offset)] = value;
    }
    if (runtime != NULL) {
        runtime->metrics.mmio_write_count++;
    }
}

static uint32_t mmio_read(offload_runtime* runtime, uint32_t offset) {
    uint32_t value = 0;
    if (has_reg(runtime, offset)) {
        value = runtime->regs[reg_index(offset)];
    }
    if (runtime != NULL) {
        runtime->metrics.mmio_read_count++;
    }
    return value;
}

static uint64_t nz_u32(uint32_t value) {
    return value != 0 ? (uint64_t)value : 1u;
}

static uint64_t deterministic_device_cycles(const offload_command_descriptor* desc) {
    uint64_t work = nz_u32(desc->work_dim0) *
                    nz_u32(desc->work_dim1) *
                    nz_u32(desc->work_dim2) *
                    nz_u32(desc->work_dim3);
    uint64_t iterations = nz_u32(desc->max_iterations);
    return work * iterations * 100u;
}

static void offload_m5_reset_stats(void) {
    /* Link a platform-specific m5op implementation here for gem5 SE/FS runs. */
}

static void offload_m5_dump_stats(void) {
    /* Link a platform-specific m5op implementation here for gem5 SE/FS runs. */
}

void offload_runtime_init(offload_runtime* runtime,
                          volatile uint32_t* register_window,
                          size_t register_window_bytes) {
    if (runtime == NULL) {
        return;
    }
    memset(runtime, 0, sizeof(*runtime));
    runtime->regs = register_window;
    runtime->reg_bytes = register_window_bytes;
    if (register_window != NULL && register_window_bytes >= 0x400) {
        mmio_write(runtime, OFFLOAD_REG_STATUS, OFFLOAD_STATUS_READY);
    }
}

void offload_runtime_set_use_m5ops(offload_runtime* runtime, int enabled) {
    if (runtime != NULL) {
        runtime->use_m5ops = enabled != 0;
    }
}

void offload_runtime_mark_roi_begin(offload_runtime* runtime) {
    if (runtime == NULL) {
        return;
    }
    if (runtime->use_m5ops) {
        offload_m5_reset_stats();
    }
    mmio_write(runtime, OFFLOAD_REG_ROI_CONTROL, OFFLOAD_ROI_MARK_BEGIN);
}

void offload_runtime_mark_roi_end(offload_runtime* runtime) {
    if (runtime == NULL) {
        return;
    }
    mmio_write(runtime, OFFLOAD_REG_ROI_CONTROL, OFFLOAD_ROI_MARK_END);
    if (runtime->use_m5ops) {
        offload_m5_dump_stats();
    }
}

int offload_runtime_submit_sync(offload_runtime* runtime,
                                const offload_command_descriptor* descriptor) {
    if (runtime == NULL || descriptor == NULL) {
        return -1;
    }
    if (descriptor->version != OFFLOAD_COMMAND_DESCRIPTOR_VERSION) {
        return -2;
    }

    const uint64_t device_cycles = deterministic_device_cycles(descriptor);
    const uint64_t payload_bytes =
        descriptor->payload_bytes ? descriptor->payload_bytes :
        nz_u32(descriptor->work_dim0) * nz_u32(descriptor->work_dim1) *
        (uint64_t)(descriptor->precision_bits ? descriptor->precision_bits / 8u : 8u);

    mmio_write(runtime, OFFLOAD_REG_WORK_DIM0, descriptor->work_dim0);
    mmio_write(runtime, OFFLOAD_REG_WORK_DIM1, descriptor->work_dim1);
    mmio_write(runtime, OFFLOAD_REG_WORK_DIM2, descriptor->work_dim2);
    mmio_write(runtime, OFFLOAD_REG_WORK_DIM3, descriptor->work_dim3);
    mmio_write(runtime, OFFLOAD_REG_WORK_ITERATIONS, descriptor->max_iterations);
    mmio_write(runtime, OFFLOAD_REG_WORK_PRECISION_BITS, descriptor->precision_bits);
    mmio_write(runtime, OFFLOAD_REG_ACCELERATOR_HINT, descriptor->accelerator_hint);

    runtime->metrics.command_count++;
    runtime->metrics.dma_read_bytes += payload_bytes;
    runtime->metrics.dma_write_bytes += payload_bytes / 2u;
    runtime->metrics.device_busy_cycles += device_cycles;

    mmio_write(runtime, OFFLOAD_REG_WORK_CMD, 1);
    mmio_write(runtime, OFFLOAD_REG_STATUS, OFFLOAD_STATUS_BUSY);

    if (descriptor->control_policy == OFFLOAD_CONTROL_INTERRUPT) {
        runtime->metrics.interrupt_count++;
    } else {
        uint64_t polls = descriptor->control_policy == OFFLOAD_CONTROL_POLLING ? 3u : 1u;
        for (uint64_t i = 0; i < polls; ++i) {
            (void)mmio_read(runtime, OFFLOAD_REG_WORK_STATUS);
            runtime->metrics.polling_iterations++;
        }
    }

    runtime->metrics.host_wait_cycles += device_cycles / 10u + 1u;
    runtime->metrics.completion_count++;
    mmio_write(runtime, OFFLOAD_REG_WORK_DONE, 1);
    mmio_write(runtime, OFFLOAD_REG_WORK_COMPLETIONS, (uint32_t)runtime->metrics.completion_count);
    mmio_write(runtime, OFFLOAD_REG_WORK_TOTAL_TIME, (uint32_t)device_cycles);
    mmio_write(runtime, OFFLOAD_REG_STATUS, OFFLOAD_STATUS_READY | OFFLOAD_STATUS_COMPUTE_DONE);
    return 0;
}

void offload_runtime_write_report_json(FILE* out,
                                       const char* schema_version,
                                       const char* workload_id,
                                       const char* backend_label,
                                       const offload_runtime_metrics* metrics) {
    const offload_runtime_metrics zero = {0};
    const offload_runtime_metrics* m = metrics != NULL ? metrics : &zero;
    if (out == NULL) {
        return;
    }
    fprintf(out,
            "{\n"
            "  \"schema_version\": \"%s\",\n"
            "  \"workload_id\": \"%s\",\n"
            "  \"backend\": \"%s\",\n"
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
            "    \"no_domain_correctness_claim\",\n"
            "    \"no_cycle_accuracy_claim\",\n"
            "    \"no_rtl_hls_board_or_asic_implementation_claim\"\n"
            "  ]\n"
            "}\n",
            schema_version != NULL ? schema_version : "offload_proxy_runtime_report_v0",
            workload_id != NULL ? workload_id : "generic_proxy",
            backend_label != NULL ? backend_label : "generic",
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
