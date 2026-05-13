#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
#define GSIM_MAGIC 0x4753494DU

struct CommandDescriptor {
    uint32_t magic;
    uint32_t version;
    uint32_t type;
    uint32_t flags;
    uint64_t request_addr;
    uint64_t result_addr;
    uint64_t workspace_addr;
    uint64_t workspace_size;
} __attribute__((packed));

struct CompletionDescriptor {
    uint32_t magic;
    uint32_t status;
    uint64_t result_addr;
    uint64_t cycles;
    uint32_t error_code;
} __attribute__((packed));

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

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s simulation_request.json\n", argv[0]);
        return 2;
    }

    struct CommandDescriptor *desc = (struct CommandDescriptor *)WORK_BASE;
    char *request = (char *)(WORK_BASE + REQUEST_OFFSET);
    struct CompletionDescriptor *completion = (struct CompletionDescriptor *)(WORK_BASE + COMPLETION_OFFSET);
    char *result = (char *)(WORK_BASE + RESULT_OFFSET);

    memset((void *)WORK_BASE, 0, WORK_BYTES);
    int rc = load_request(argv[1], request, REQUEST_BYTES);
    if (rc != 0) return rc;

    desc->magic = GSIM_MAGIC;
    desc->version = 1;
    desc->type = 1;
    desc->flags = 0x7;
    desc->request_addr = (uint64_t)(uintptr_t)request;
    desc->result_addr = (uint64_t)(uintptr_t)result;
    desc->workspace_addr = WORK_BASE;
    desc->workspace_size = REQUEST_BYTES;

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
    printf("generic_accel_l4_status=%u error_code=%u\n", status, error_code);
    printf("completion_magic=0x%08x completion_status=%u cycles=%llu result_addr=0x%llx\n",
           completion->magic,
           completion->status,
           (unsigned long long)completion->cycles,
           (unsigned long long)completion->result_addr);
    printf("result_prefix=%.160s\n", result);

    if (status != 1 || error_code != 0) return 3;
    if (completion->magic != GSIM_MAGIC || completion->status != 0) return 4;
    if (strstr(result, "\"status\": \"passed\"") == NULL && strstr(result, "\"status\":\"passed\"") == NULL) {
        return 5;
    }
    return 0;
}
