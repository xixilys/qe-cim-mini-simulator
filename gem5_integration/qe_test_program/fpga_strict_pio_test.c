#include <stdint.h>
#include <stdio.h>

#define FPGA_BASE_ADDR 0xF0000000UL

#define REG_CONTROL 0x00
#define REG_STATUS 0x04
#define REG_N_BANDS 0x08
#define REG_N_BASIS 0x0C
#define REG_CYCLES 0x10
#define REG_OBSERVED_READ_COUNT 0x20
#define REG_OBSERVED_WRITE_COUNT 0x24
#define REG_POLLING_READ_COUNT 0x28
#define REG_EVENT_DELTA_TICKS_LO 0x44
#define REG_EVENT_DELTA_TICKS_HI 0x48

static volatile uint32_t *fpga_regs = (volatile uint32_t *)FPGA_BASE_ADDR;

static inline void fpga_write(uint32_t offset, uint32_t value)
{
    fpga_regs[offset / 4] = value;
}

static inline uint32_t fpga_read(uint32_t offset)
{
    return fpga_regs[offset / 4];
}

int main(void)
{
    printf("QE strict B4 FPGA PIO test at 0x%lx\n", FPGA_BASE_ADDR);

    fpga_write(REG_N_BANDS, 32);
    fpga_write(REG_N_BASIS, 128);
    fpga_write(REG_CONTROL, 1);

    uint32_t status = 0;
    uint32_t polls = 0;
    while ((status & 1) == 0 && polls < 1000000) {
        status = fpga_read(REG_STATUS);
        ++polls;
    }

    if ((status & 1) == 0) {
        fprintf(stderr, "strict PIO test timed out after %u polls\n", polls);
        return 2;
    }

    uint32_t cycles = fpga_read(REG_CYCLES);
    uint32_t reads = fpga_read(REG_OBSERVED_READ_COUNT);
    uint32_t writes = fpga_read(REG_OBSERVED_WRITE_COUNT);
    uint32_t polling_reads = fpga_read(REG_POLLING_READ_COUNT);
    uint64_t event_delta =
        ((uint64_t)fpga_read(REG_EVENT_DELTA_TICKS_HI) << 32) |
        fpga_read(REG_EVENT_DELTA_TICKS_LO);

    printf("strict PIO complete: cycles=%u reads=%u writes=%u polling=%u event_delta=%lu\n",
           cycles, reads, writes, polling_reads, (unsigned long)event_delta);

    return (reads > 0 && writes > 0 && event_delta > 0) ? 0 : 3;
}
