#include <stdio.h>
#include <stdint.h>
#include <sys/mman.h>
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
    printf("  [DEBUG] Writing 0x%08X to offset 0x%02X (addr=%p)\n", 
           value, offset, &fpga_regs[offset / 4]);
    fpga_regs[offset / 4] = value;
}

static inline uint32_t fpga_read(uint32_t offset) {
    uint32_t value = fpga_regs[offset / 4];
    printf("  [DEBUG] Read 0x%08X from offset 0x%02X (addr=%p)\n", 
           value, offset, &fpga_regs[offset / 4]);
    return value;
}

int main() {
    printf("==============================================\n");
    printf("QE FPGA Accelerator Simple Test\n");
    printf("==============================================\n\n");
    
    printf("Step 1: Mapping FPGA device at 0x%lX...\n", FPGA_BASE_ADDR);
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
    
    printf("  Mapped at %p\n\n", fpga_regs);
    
    printf("Step 2: Writing parameters...\n");
    fpga_write(REG_N_BANDS, 32);
    fpga_write(REG_N_BASIS, 128);
    
    printf("\nStep 3: Reading back parameters...\n");
    uint32_t n_bands = fpga_read(REG_N_BANDS);
    uint32_t n_basis = fpga_read(REG_N_BASIS);
    printf("  n_bands = %u (expected 32)\n", n_bands);
    printf("  n_basis = %u (expected 128)\n", n_basis);
    
    printf("\nStep 4: Starting computation...\n");
    fpga_write(REG_CONTROL, 1);
    
    printf("\nStep 5: Reading status (max 10 attempts)...\n");
    uint32_t status;
    int poll_count = 0;
    for (poll_count = 0; poll_count < 10; poll_count++) {
        status = fpga_read(REG_STATUS);
        if (status & 1) {
            printf("  Computation complete!\n");
            break;
        }
        printf("  Status not ready yet (attempt %d/10)\n", poll_count + 1);
    }
    
    if (!(status & 1)) {
        printf("  ERROR: Computation did not complete after 10 attempts\n");
        return 1;
    }
    
    printf("\nStep 6: Reading results...\n");
    uint32_t cycles = fpga_read(REG_CYCLES);
    printf("  Cycles: %u\n", cycles);
    
    printf("\n==============================================\n");
    printf("Test completed successfully!\n");
    printf("==============================================\n");
    
    munmap((void*)fpga_regs, FPGA_SIZE);
    return 0;
}
