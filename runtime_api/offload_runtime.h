#ifndef QEBS_OFFLOAD_RUNTIME_H
#define QEBS_OFFLOAD_RUNTIME_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "command_descriptor.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct qebs_runtime {
    volatile uint32_t* regs;
    size_t reg_bytes;
    qebs_runtime_metrics metrics;
    int use_m5ops;
} qebs_runtime;
typedef qebs_runtime offload_runtime;

void qebs_runtime_init(qebs_runtime* runtime,
                       volatile uint32_t* register_window,
                       size_t register_window_bytes);

void qebs_runtime_set_use_m5ops(qebs_runtime* runtime, int enabled);
void qebs_runtime_mark_roi_begin(qebs_runtime* runtime);
void qebs_runtime_mark_roi_end(qebs_runtime* runtime);

int qebs_runtime_submit_sync(qebs_runtime* runtime,
                             const qebs_command_descriptor* descriptor);

void qebs_runtime_write_report_json(FILE* out,
                                    const char* schema_version,
                                    const char* workload_id,
                                    const char* adapter,
                                    const qebs_runtime_metrics* metrics);

#define offload_runtime_init qebs_runtime_init
#define offload_runtime_set_use_m5ops qebs_runtime_set_use_m5ops
#define offload_runtime_mark_roi_begin qebs_runtime_mark_roi_begin
#define offload_runtime_mark_roi_end qebs_runtime_mark_roi_end
#define offload_runtime_submit_sync qebs_runtime_submit_sync
#define offload_runtime_write_report_json qebs_runtime_write_report_json

#ifdef __cplusplus
}
#endif

#endif
