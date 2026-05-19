#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../../runtime_api/command_descriptor.h"

/*
 * Keep the accelerator MMIO window outside the 512 MiB SE-mode DRAM range.
 * The gem5 config maps this virtual window to the GenericAccel PIO range.
 */
#define MMIO_BASE 0xF0000000UL
#define WORK_BASE 0x08000000UL

#define REG_CMD_DOORBELL 0x1000
#define REG_CMD_DESC_ADDR_LO 0x1004
#define REG_CMD_DESC_ADDR_HI 0x1008
#define REG_CMD_DESC_SIZE 0x100C
#define REG_COMP_STATUS 0x3000
#define REG_COMP_DESC_ADDR_LO 0x3004
#define REG_COMP_DESC_ADDR_HI 0x3008
#define REG_COMP_ERROR_CODE 0x300C

#define REQUEST_OFFSET 0x1000
#define REQUEST_BYTES (1UL << 20)
#define COMPLETION_OFFSET 0x110000
#define RESULT_OFFSET 0x120000
#define RESULT_BYTES (1UL << 20)
#define WORK_BYTES 0x240000UL
#define POLL_LIMIT 100000000

#define GSIM_DRIVER_FLAGS \
    (OFFLOAD_GSIM_DESCRIPTOR_FLAG_REQUEST_JSON | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_RESULT_JSON | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPLETION_DESC | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_EXTENSION_PAYLOAD | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_CANDIDATE_IDENTITY | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPILE_SCHEDULE | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_RUNTIME_SCHEDULE | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_SIDECAR_DISPATCH)

static void mmio_write32(uintptr_t offset, uint32_t value) {
    volatile uint32_t *reg = (volatile uint32_t *)(MMIO_BASE + offset);
    *reg = value;
    __sync_synchronize();
}

static uint32_t mmio_read32(uintptr_t offset) {
    volatile uint32_t *reg = (volatile uint32_t *)(MMIO_BASE + offset);
    uint32_t value = *reg;
    __sync_synchronize();
    return value;
}

static int load_request(const char *path, char *dst, size_t capacity) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror("fopen request");
        return 1;
    }
    size_t n = fread(dst, 1, capacity - 1, f);
    if (ferror(f)) {
        perror("fread request");
        fclose(f);
        return 2;
    }
    fclose(f);
    dst[n] = '\0';
    return 0;
}

static int parse_repeat(int argc, char **argv) {
    int repeat = 1;
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--repeat") == 0 && i + 1 < argc) {
            repeat = atoi(argv[i + 1]);
            i++;
        }
    }
    if (repeat < 1) repeat = 1;
    return repeat;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s simulation_request.json [--repeat N]\n", argv[0]);
        return 2;
    }

    offload_gsim_command_descriptor *desc = (offload_gsim_command_descriptor *)WORK_BASE;
    char *request = (char *)(WORK_BASE + REQUEST_OFFSET);
    offload_gsim_completion_descriptor *completion =
        (offload_gsim_completion_descriptor *)(WORK_BASE + COMPLETION_OFFSET);
    char *result = (char *)(WORK_BASE + RESULT_OFFSET);

    int rc = load_request(argv[1], request, REQUEST_BYTES);
    if (rc != 0) return rc;

    size_t request_len = strlen(request) + 1;
    int repeat = parse_repeat(argc, argv);
    printf("generic_accel_l4_driver_repeat=%d\n", repeat);

    for (int iter = 0; iter < repeat; iter++) {
        memset((void *)desc, 0, sizeof(*desc));
        memset((void *)completion, 0, sizeof(*completion));
        /*
         * The device writes a NUL-terminated result JSON and a completion
         * descriptor on every successful command.  Avoid clearing the whole
         * 2.25 MiB guest workspace or 1 MiB result window here: under gem5 SE
         * mode those stores are simulated one-by-one and dominate short L4
         * bridge measurements without adding descriptor/completion evidence.
         * A single-byte sentinel is enough to keep failure prints bounded
         * before the device writes the real result payload.
         */
        result[0] = '\0';

        desc->magic = OFFLOAD_GSIM_MAGIC;
        desc->version = OFFLOAD_GSIM_DESCRIPTOR_VERSION;
        desc->type = OFFLOAD_GSIM_COMMAND_TYPE_GRAPH;
        desc->flags = GSIM_DRIVER_FLAGS;
        desc->request_addr = (uint64_t)(uintptr_t)request;
        desc->result_addr = (uint64_t)(uintptr_t)result;
        desc->workspace_addr = WORK_BASE;
        desc->workspace_size = REQUEST_BYTES;
        /*
         * Optional V1 extension lanes are intentionally generic.  The JSON request
         * carries candidate identity, compile/runtime schedules, adapter payloads,
         * and sidecar-dispatch metadata through extension/plugin boundaries without
         * hard-coding application fields into this C ABI.
         */
        desc->extension_payload_addr = (uint64_t)(uintptr_t)request;
        desc->extension_payload_bytes = (uint64_t)request_len;
        desc->candidate_identity_addr = (uint64_t)(uintptr_t)request;
        desc->candidate_identity_bytes = (uint64_t)request_len;
        desc->compile_schedule_addr = (uint64_t)(uintptr_t)request;
        desc->compile_schedule_bytes = (uint64_t)request_len;
        desc->runtime_schedule_addr = (uint64_t)(uintptr_t)request;
        desc->runtime_schedule_bytes = (uint64_t)request_len;
        desc->sidecar_dispatch_addr = (uint64_t)(uintptr_t)request;
        desc->sidecar_dispatch_bytes = (uint64_t)request_len;

        mmio_write32(REG_CMD_DESC_ADDR_LO, (uint32_t)((uintptr_t)desc & 0xffffffffU));
        mmio_write32(REG_CMD_DESC_ADDR_HI, (uint32_t)(((uint64_t)(uintptr_t)desc) >> 32));
        mmio_write32(REG_CMD_DESC_SIZE, (uint32_t)sizeof(*desc));
        mmio_write32(REG_COMP_DESC_ADDR_LO, (uint32_t)((uintptr_t)completion & 0xffffffffU));
        mmio_write32(REG_COMP_DESC_ADDR_HI, (uint32_t)(((uint64_t)(uintptr_t)completion) >> 32));
        mmio_write32(REG_CMD_DOORBELL, 1);

        uint32_t status = 0;
        for (int i = 0; i < POLL_LIMIT; i++) {
            status = mmio_read32(REG_COMP_STATUS);
            if (status == 1 || status == 2) break;
        }

        uint32_t error_code = mmio_read32(REG_COMP_ERROR_CODE);
        printf("generic_accel_l4_iteration=%d status=%u error_code=%u\n",
               iter + 1, status, error_code);
        printf("generic_accel_l4_status=%u error_code=%u\n", status, error_code);
        printf("completion_magic=0x%08x completion_status=%u cycles=%llu result_addr=0x%llx\n",
               completion->magic,
               completion->status,
               (unsigned long long)completion->cycles,
               (unsigned long long)completion->result_addr);
        printf("result_prefix=%.160s\n", result);

        if (status != 1 || error_code != 0) return 3;
        if (completion->magic != OFFLOAD_GSIM_MAGIC || completion->status != 0) return 4;
        if (strstr(result, "\"status\": \"passed\"") == NULL && strstr(result, "\"status\":\"passed\"") == NULL) {
            return 5;
        }
    }
    return 0;
}
