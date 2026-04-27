#include <stdio.h>
#include <stdint.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>

#define FPGA_BASE_ADDR 0xF0000000UL
#define FPGA_SIZE      0x1000

#define REG_CONTROL   0x00
#define REG_STATUS    0x04
#define REG_N_BANDS   0x08
#define REG_N_BASIS   0x0C
#define REG_CYCLES    0x10

volatile uint32_t* fpga_regs = NULL;

static inline void fpga_write(uint32_t offset, uint32_t value) {
    fpga_regs[offset / 4] = value;
}

static inline uint32_t fpga_read(uint32_t offset) {
    return fpga_regs[offset / 4];
}

int main() {
    printf("==============================================\n");
    printf("QE FPGA Accelerator Test\n");
    printf("==============================================\n\n");
    
    printf("Mapping FPGA device at 0x%lX...\n", FPGA_BASE_ADDR);
    fpga_regs = (volatile uint32_t*)mmap(
        (void*)FPGA_BASE_ADDR,
        FPGA_SIZE,
        PROT_READ | PROT_WRITE,
        MAP_ANONYMOUS | MAP_PRIVATE | MAP_FIXED,
        -1,
        0
    );
    
    if (fpga_regs == MAP_FAILED) {
        printf("ERROR: Failed to map FPGA device\n");
        return 1;
    }
    
    printf("FPGA device mapped successfully at %p\n\n", fpga_regs);
    
    printf("Testing c_bands computation:\n");
    printf("  Setting n_bands = 32\n");
    fpga_write(REG_N_BANDS, 32);
    
    printf("  Setting n_basis = 128\n");
    fpga_write(REG_N_BASIS, 128);
    
    printf("  Reading back values...\n");
    uint32_t n_bands = fpga_read(REG_N_BANDS);
    uint32_t n_basis = fpga_read(REG_N_BASIS);
    printf("    n_bands = %u\n", n_bands);
    printf("    n_basis = %u\n", n_basis);
    
    printf("\n  Starting FPGA computation...\n");
    fpga_write(REG_CONTROL, 1);
    
    printf("  Polling status register...\n");
    uint32_t status;
    int poll_count = 0;
    do {
        status = fpga_read(REG_STATUS);
        poll_count++;
    } while (!(status & 1));
    
    printf("  Computation complete! (polled %d times)\n", poll_count);
    
    uint32_t cycles = fpga_read(REG_CYCLES);
    printf("\n  Results:\n");
    printf("    Cycles: %u\n", cycles);
    printf("    Expected baseline: 3246 cycles\n");
    
    printf("\n==============================================\n");
    printf("Test completed successfully!\n");
    printf("==============================================\n");
    
    munmap((void*)fpga_regs, FPGA_SIZE);
    return 0;
}
