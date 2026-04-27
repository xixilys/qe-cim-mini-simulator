#include <stdio.h>
#include <stdint.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>

#define FPGA_BASE_ADDR 0xF0000000UL
#define FPGA_SIZE 4096

#define REG_CONTROL   0x00
#define REG_STATUS    0x04
#define REG_N_BANDS   0x08
#define REG_N_BASIS   0x0C
#define REG_CYCLES    0x10

#define CMD_START 0x1
#define STATUS_DONE 0x1

volatile uint32_t* fpga_regs = (volatile uint32_t*)FPGA_BASE_ADDR;

void fpga_write(uint32_t offset, uint32_t value) {
    fpga_regs[offset / 4] = value;
}

uint32_t fpga_read(uint32_t offset) {
    return fpga_regs[offset / 4];
}

int main() {
    printf("FPGA Accelerator Test\n");
    printf("=====================\n\n");
    
    printf("Testing c_bands computation:\n");
    fpga_write(REG_N_BANDS, 10);
    fpga_write(REG_N_BASIS, 100);
    
    printf("  n_bands = %u\n", fpga_read(REG_N_BANDS));
    printf("  n_basis = %u\n", fpga_read(REG_N_BASIS));
    
    printf("  Starting computation...\n");
    fpga_write(REG_CONTROL, CMD_START);
    
    while (!(fpga_read(REG_STATUS) & STATUS_DONE)) {
    }
    
    uint32_t cycles = fpga_read(REG_CYCLES);
    printf("  Computation complete!\n");
    printf("  Cycles: %u\n", cycles);
    printf("  Expected: ~3246 cycles\n\n");
    
    double speedup = 3246.0 / cycles;
    printf("Performance: %.2fx vs baseline\n", speedup);
    
    return 0;
}
