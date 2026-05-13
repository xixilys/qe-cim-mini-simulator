#ifndef OFFLOAD_RUNTIME_H
#define OFFLOAD_RUNTIME_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "command_descriptor.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct offload_runtime {
    volatile uint32_t* regs;
    size_t reg_bytes;
    offload_runtime_metrics metrics;
    int use_m5ops;
} offload_runtime;

void offload_runtime_init(offload_runtime* runtime,
                          volatile uint32_t* register_window,
                          size_t register_window_bytes);

void offload_runtime_set_use_m5ops(offload_runtime* runtime, int enabled);
void offload_runtime_mark_roi_begin(offload_runtime* runtime);
void offload_runtime_mark_roi_end(offload_runtime* runtime);

int offload_runtime_submit_sync(offload_runtime* runtime,
                                const offload_command_descriptor* descriptor);

void offload_runtime_write_report_json(FILE* out,
                                       const char* schema_version,
                                       const char* workload_id,
                                       const char* backend_label,
                                       const offload_runtime_metrics* metrics);

#ifdef __cplusplus
}
#endif

#endif
