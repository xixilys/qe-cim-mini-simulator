#include "offload_runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static int env_int(const char* name, int fallback) {
    const char* value = getenv(name);
    return value != NULL && value[0] != '\0' ? atoi(value) : fallback;
}

int main(void) {
    volatile uint32_t regs[0x400 / sizeof(uint32_t)] = {0};
    qebs_runtime runtime;
    qebs_runtime_init(&runtime, regs, sizeof(regs));
    qebs_runtime_set_use_m5ops(&runtime, env_int("QEBS_PROXY_USE_M5OPS", 0));

    qebs_command_descriptor desc = qebs_command_descriptor_default();
    desc.opcode = QEBS_OPCODE_GENERIC_SCF;
    desc.n_bands = (uint32_t)env_int("QEBS_PROXY_NBANDS", (int)desc.n_bands);
    desc.n_basis = (uint32_t)env_int("QEBS_PROXY_NBASIS", (int)desc.n_basis);
    desc.n_kpoints = (uint32_t)env_int("QEBS_PROXY_NKPOINTS", (int)desc.n_kpoints);
    desc.max_iterations =
        (uint32_t)env_int("QEBS_PROXY_ITERATIONS", (int)desc.max_iterations);
    desc.control_policy =
        (uint32_t)env_int("QEBS_PROXY_CONTROL_POLICY", QEBS_CONTROL_POLLING);
    desc.payload_bytes =
        (uint64_t)desc.n_bands * (uint64_t)desc.n_basis * 16u;

    qebs_runtime_mark_roi_begin(&runtime);
    int rc = qebs_runtime_submit_sync(&runtime, &desc);
    qebs_runtime_mark_roi_end(&runtime);
    if (rc != 0) {
        fprintf(stderr, "qebs_runtime_submit_sync failed: %d\n", rc);
        return 1;
    }

    qebs_runtime_write_report_json(stdout,
                                   "qebs_proxy_runtime_report_v0",
                                   "generic_scf_proxy",
                                   "generic",
                                   &runtime.metrics);
    return 0;
}
