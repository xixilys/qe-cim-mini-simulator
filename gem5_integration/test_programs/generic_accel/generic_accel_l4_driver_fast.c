#include <stddef.h>
#include <stdint.h>

#include "../../../runtime_api/command_descriptor.h"

/*
 * Minimal no-libc SE-mode GenericAccel driver.
 *
 * The regular test driver is intentionally readable and libc-based.  For short
 * QE bridge measurements, static libc startup and large helper routines become
 * a material part of the gem5 critical path.  This driver keeps the same
 * guest-visible MMIO descriptor/request/completion contract while using direct
 * Linux syscalls and a tiny _start entry point so driver overhead does not
 * dominate L4 value attempts.
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
#define POLL_LIMIT 100000000

#define SYS_READ 0
#define SYS_WRITE 1
#define SYS_CLOSE 3
#define SYS_EXIT 60
#define SYS_OPENAT 257
#define AT_FDCWD (-100)

#define GSIM_DRIVER_FLAGS \
    (OFFLOAD_GSIM_DESCRIPTOR_FLAG_REQUEST_JSON | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_RESULT_JSON | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPLETION_DESC | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_EXTENSION_PAYLOAD | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_CANDIDATE_IDENTITY | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_COMPILE_SCHEDULE | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_RUNTIME_SCHEDULE | \
     OFFLOAD_GSIM_DESCRIPTOR_FLAG_SIDECAR_DISPATCH)

static long syscall1(long n, long a0) {
    long ret;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(n), "D"(a0)
                     : "rcx", "r11", "memory");
    return ret;
}

static long syscall3(long n, long a0, long a1, long a2) {
    long ret;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(n), "D"(a0), "S"(a1), "d"(a2)
                     : "rcx", "r11", "memory");
    return ret;
}

static long syscall4(long n, long a0, long a1, long a2, long a3) {
    long ret;
    register long r10 __asm__("r10") = a3;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(n), "D"(a0), "S"(a1), "d"(a2), "r"(r10)
                     : "rcx", "r11", "memory");
    return ret;
}

static void write_buf(const char *buf, size_t len) {
    while (len > 0) {
        long n = syscall3(SYS_WRITE, 1, (long)buf, (long)len);
        if (n <= 0) return;
        buf += (size_t)n;
        len -= (size_t)n;
    }
}

static size_t cstr_len(const char *s) {
    size_t n = 0;
    const volatile char *p = (const volatile char *)s;
    while (s && p[n]) n++;
    return n;
}

static void write_str(const char *s) {
    write_buf(s, cstr_len(s));
}

static void write_dec_u64(uint64_t value) {
    char buf[32];
    size_t pos = sizeof(buf);
    if (value == 0) {
        write_str("0");
        return;
    }
    while (value > 0 && pos > 0) {
        buf[--pos] = (char)('0' + (value % 10));
        value /= 10;
    }
    write_buf(&buf[pos], sizeof(buf) - pos);
}

static void write_hex_u64(uint64_t value, int digits) {
    static const char hex[] = "0123456789abcdef";
    char buf[18];
    buf[0] = '0';
    buf[1] = 'x';
    for (int i = 0; i < digits; i++) {
        int shift = (digits - 1 - i) * 4;
        buf[2 + i] = hex[(value >> shift) & 0xfU];
    }
    write_buf(buf, (size_t)digits + 2);
}

static int cstr_eq(const char *a, const char *b) {
    size_t i = 0;
    while (a[i] && b[i] && a[i] == b[i]) i++;
    return a[i] == '\0' && b[i] == '\0';
}

static int parse_positive_int(const char *s) {
    int value = 0;
    while (*s >= '0' && *s <= '9') {
        value = value * 10 + (*s - '0');
        s++;
    }
    return value > 0 ? value : 1;
}

static int parse_repeat(int argc, char **argv) {
    int repeat = 1;
    for (int i = 2; i + 1 < argc; i++) {
        if (cstr_eq(argv[i], "--repeat")) {
            repeat = parse_positive_int(argv[i + 1]);
            i++;
        }
    }
    return repeat > 0 ? repeat : 1;
}

static void zero_bytes(void *ptr, size_t n) {
    volatile uint8_t *p = (volatile uint8_t *)ptr;
    for (size_t i = 0; i < n; i++) p[i] = 0;
}

static int load_request(const char *path, char *dst, size_t capacity) {
    long fd = syscall4(SYS_OPENAT, AT_FDCWD, (long)path, 0, 0);
    if (fd < 0) {
        write_str("open_request_failed\n");
        return 1;
    }
    size_t used = 0;
    while (used + 1 < capacity) {
        long n = syscall3(SYS_READ, fd, (long)(dst + used), (long)(capacity - 1 - used));
        if (n < 0) {
            syscall1(SYS_CLOSE, fd);
            write_str("read_request_failed\n");
            return 2;
        }
        if (n == 0) break;
        used += (size_t)n;
    }
    syscall1(SYS_CLOSE, fd);
    dst[used] = '\0';
    return 0;
}

static int contains(const char *haystack, const char *needle) {
    size_t nlen = cstr_len(needle);
    if (nlen == 0) return 1;
    for (size_t i = 0; haystack[i]; i++) {
        size_t j = 0;
        while (j < nlen && haystack[i + j] == needle[j]) j++;
        if (j == nlen) return 1;
    }
    return 0;
}

static void mmio_write32(uintptr_t offset, uint32_t value) {
    volatile uint32_t *reg = (volatile uint32_t *)(MMIO_BASE + offset);
    *reg = value;
    __asm__ volatile("" ::: "memory");
}

static uint32_t mmio_read32(uintptr_t offset) {
    volatile uint32_t *reg = (volatile uint32_t *)(MMIO_BASE + offset);
    uint32_t value = *reg;
    __asm__ volatile("" ::: "memory");
    return value;
}

static int driver_main(int argc, char **argv) {
    if (argc < 2) {
        write_str("usage: generic_accel_l4_driver_fast simulation_request.json [--repeat N]\n");
        return 2;
    }

    offload_gsim_command_descriptor *desc =
        (offload_gsim_command_descriptor *)WORK_BASE;
    char *request = (char *)(WORK_BASE + REQUEST_OFFSET);
    offload_gsim_completion_descriptor *completion =
        (offload_gsim_completion_descriptor *)(WORK_BASE + COMPLETION_OFFSET);
    char *result = (char *)(WORK_BASE + RESULT_OFFSET);

    int rc = load_request(argv[1], request, REQUEST_BYTES);
    if (rc != 0) return rc;
    size_t request_len = cstr_len(request) + 1;
    int repeat = parse_repeat(argc, argv);
    write_str("generic_accel_l4_driver_repeat=");
    write_dec_u64((uint64_t)repeat);
    write_str("\n");

    for (int iter = 0; iter < repeat; iter++) {
        zero_bytes(desc, sizeof(*desc));
        zero_bytes(completion, sizeof(*completion));
        result[0] = '\0';

        desc->magic = OFFLOAD_GSIM_MAGIC;
        desc->version = OFFLOAD_GSIM_DESCRIPTOR_VERSION;
        desc->type = OFFLOAD_GSIM_COMMAND_TYPE_GRAPH;
        desc->flags = GSIM_DRIVER_FLAGS;
        desc->request_addr = (uint64_t)(uintptr_t)request;
        desc->result_addr = (uint64_t)(uintptr_t)result;
        desc->workspace_addr = WORK_BASE;
        desc->workspace_size = REQUEST_BYTES;
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

        write_str("generic_accel_l4_iteration=");
        write_dec_u64((uint64_t)(iter + 1));
        write_str(" status=");
        write_dec_u64(status);
        write_str(" error_code=");
        write_dec_u64(error_code);
        write_str("\n");
        write_str("generic_accel_l4_status=");
        write_dec_u64(status);
        write_str(" error_code=");
        write_dec_u64(error_code);
        write_str("\ncompletion_magic=");
        write_hex_u64(completion->magic, 8);
        write_str(" completion_status=");
        write_dec_u64(completion->status);
        write_str(" cycles=");
        write_dec_u64(completion->cycles);
        write_str(" result_addr=");
        write_hex_u64(completion->result_addr, 16);
        write_str("\nresult_prefix=");
        size_t prefix = 0;
        while (prefix < 160 && result[prefix]) prefix++;
        write_buf(result, prefix);
        write_str("\n");

        if (status != 1 || error_code != 0) return 3;
        if (completion->magic != OFFLOAD_GSIM_MAGIC || completion->status != 0) return 4;
        if (!contains(result, "\"status\": \"passed\"") &&
            !contains(result, "\"status\":\"passed\"")) {
            return 5;
        }
    }
    return 0;
}

__attribute__((used, noinline, noreturn)) void start_c(long *sp) {
    int argc = (int)sp[0];
    char **argv = (char **)&sp[1];
    int rc = driver_main(argc, argv);
    syscall1(SYS_EXIT, rc);
    __builtin_unreachable();
}

__attribute__((naked, noreturn)) void _start(void) {
    __asm__ volatile(
        "mov %rsp, %rdi\n"
        "andq $-16, %rsp\n"
        "call start_c\n"
    );
}
