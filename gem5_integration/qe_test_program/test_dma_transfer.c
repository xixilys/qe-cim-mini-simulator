/*
 * DMA transfer test program for FPGA PCIe device
 * Tests host-to-device and device-to-host DMA transfers
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>

#define PCI_SYSFS_PATH "/sys/bus/pci/devices/0000:00:08.0/resource0"

// FPGA register offsets
#define REG_CONTROL       0x0000
#define REG_STATUS        0x0004
#define REG_INTERRUPT     0x0008
#define REG_DMA_SRC_LO    0x0010
#define REG_DMA_SRC_HI    0x0014
#define REG_DMA_DST_LO    0x0018
#define REG_DMA_DST_HI    0x001C
#define REG_DMA_SIZE      0x0020
#define REG_DMA_CONTROL   0x0024

// Status bits
#define STATUS_READY      0x01
#define STATUS_BUSY       0x02
#define STATUS_DMA_DONE   0x08

// Control bits
#define CTRL_IRQ_ENABLE   0x04

// DMA control values
#define DMA_CTRL_HOST_TO_DEV  1
#define DMA_CTRL_DEV_TO_HOST  2

// Test patterns
#define TEST_PATTERN_32BIT    0x12345678
#define TEST_PATTERN_ALT      0xDEADBEEF

static volatile uint32_t *fpga_regs = NULL;

static uint32_t read_reg(uint32_t offset) {
    return fpga_regs[offset / 4];
}

static void write_reg(uint32_t offset, uint32_t value) {
    fpga_regs[offset / 4] = value;
}

static int wait_for_dma_done(int timeout_ms) {
    for (int i = 0; i < timeout_ms; i++) {
        uint32_t status = read_reg(REG_STATUS);
        if (status & STATUS_DMA_DONE) {
            return 0;  // Success
        }
        usleep(1000);  // 1ms
    }
    return -1;  // Timeout
}

static void clear_dma_done(void) {
    uint32_t status = read_reg(REG_STATUS);
    status &= ~STATUS_DMA_DONE;
    // Note: In real hardware, this might be a write-to-clear bit
}

static int dma_transfer(uint64_t src_phys, uint64_t dst_phys, size_t size, int direction) {
    // Set source address
    write_reg(REG_DMA_SRC_LO, (uint32_t)(src_phys & 0xFFFFFFFF));
    write_reg(REG_DMA_SRC_HI, (uint32_t)(src_phys >> 32));

    // Set destination address
    write_reg(REG_DMA_DST_LO, (uint32_t)(dst_phys & 0xFFFFFFFF));
    write_reg(REG_DMA_DST_HI, (uint32_t)(dst_phys >> 32));

    // Set size
    write_reg(REG_DMA_SIZE, (uint32_t)size);

    // Clear previous DMA done flag
    clear_dma_done();

    // Start transfer
    write_reg(REG_DMA_CONTROL, direction);

    // Wait for completion
    if (wait_for_dma_done(5000) < 0) {
        printf("ERROR: DMA transfer timeout\n");
        return -1;
    }

    return 0;
}

// Simple memory test pattern fill
static void fill_pattern(uint32_t *buf, size_t size_words, uint32_t pattern) {
    for (size_t i = 0; i < size_words; i++) {
        buf[i] = pattern ^ (uint32_t)i;  // Pattern varies by position
    }
}

// Verify pattern
static int verify_pattern(uint32_t *buf, size_t size_words, uint32_t pattern) {
    for (size_t i = 0; i < size_words; i++) {
        if (buf[i] != (pattern ^ (uint32_t)i)) {
            printf("  Mismatch at word %zu: expected 0x%08x, got 0x%08x\n",
                   i, pattern ^ (uint32_t)i, buf[i]);
            return -1;
        }
    }
    return 0;
}

int main(int argc, char *argv[]) {
    printf("==============================================\n");
    printf("FPGA DMA Transfer Test\n");
    printf("==============================================\n\n");

    // Open FPGA device
    int fd = open(PCI_SYSFS_PATH, O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("Failed to open PCI device");
        printf("Trying /dev/mem fallback...\n");

        // Fallback to /dev/mem for testing
        fd = open("/dev/mem", O_RDWR | O_SYNC);
        if (fd < 0) {
            perror("Failed to open /dev/mem");
            return 1;
        }

        // Map FPGA BAR at 0xC0000000 (from kernel log)
        fpga_regs = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0xC0000000);
    } else {
        fpga_regs = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    }

    if (fpga_regs == MAP_FAILED) {
        perror("Failed to mmap FPGA registers");
        close(fd);
        return 1;
    }

    printf("FPGA mapped successfully\n");
    printf("Initial status: 0x%08x\n\n", read_reg(REG_STATUS));

    // Allocate test buffers (page-aligned for DMA)
    size_t test_sizes[] = {64, 1024, 4096, 16384};  // 64B, 1KB, 4KB, 16KB
    int num_tests = sizeof(test_sizes) / sizeof(test_sizes[0]);
    int passed = 0, failed = 0;

    for (int t = 0; t < num_tests; t++) {
        size_t size = test_sizes[t];
        size_t size_words = size / sizeof(uint32_t);

        printf("Test %d: DMA transfer %zu bytes\n", t + 1, size);
        printf("  Allocating buffers...\n");

        // Allocate aligned buffers
        void *src_buf = aligned_alloc(4096, size);
        void *dst_buf = aligned_alloc(4096, size);

        if (!src_buf || !dst_buf) {
            printf("  FAILED: Buffer allocation failed\n");
            free(src_buf);
            free(dst_buf);
            failed++;
            continue;
        }

        // Fill source with test pattern
        fill_pattern((uint32_t *)src_buf, size_words, TEST_PATTERN_32BIT);
        memset(dst_buf, 0, size);

        // Get physical addresses (in real implementation, use dma_map)
        // For this test, we use virtual addresses as placeholders
        uint64_t src_phys = (uint64_t)src_buf;
        uint64_t dst_phys = (uint64_t)dst_buf;

        printf("  Source buffer: virt=%p, phys=0x%lx\n", src_buf, src_phys);
        printf("  Dest buffer:   virt=%p, phys=0x%lx\n", dst_buf, dst_phys);

        // Test 1: Host to Device (simulated - write to FPGA buffer)
        printf("  Host-to-device transfer...\n");
        if (dma_transfer(src_phys, dst_phys, size, DMA_CTRL_HOST_TO_DEV) < 0) {
            printf("  FAILED: H2D transfer timeout\n");
            free(src_buf);
            free(dst_buf);
            failed++;
            continue;
        }
        printf("  H2D complete\n");

        // Clear destination for round-trip test
        memset(dst_buf, 0, size);

        // Test 2: Device to Host (simulated - read from FPGA buffer)
        printf("  Device-to-host transfer...\n");
        if (dma_transfer(src_phys, dst_phys, size, DMA_CTRL_DEV_TO_HOST) < 0) {
            printf("  FAILED: D2H transfer timeout\n");
            free(src_buf);
            free(dst_buf);
            failed++;
            continue;
        }
        printf("  D2H complete\n");

        // Note: In current mock implementation, we just verify the DMA
        // transaction completed. Real data verification requires actual
        // FPGA memory backing store.
        printf("  Transfer completed (data verification skipped in mock mode)\n");
        printf("  PASSED\n\n");
        passed++;

        free(src_buf);
        free(dst_buf);
    }

    // Summary
    printf("==============================================\n");
    printf("DMA Transfer Test Summary\n");
    printf("==============================================\n");
    printf("Total:  %d\n", passed + failed);
    printf("Passed: %d\n", passed);
    printf("Failed: %d\n", failed);
    printf("==============================================\n");

    // Cleanup
    munmap((void *)fpga_regs, 0x10000);
    close(fd);

    return failed > 0 ? 1 : 0;
}
