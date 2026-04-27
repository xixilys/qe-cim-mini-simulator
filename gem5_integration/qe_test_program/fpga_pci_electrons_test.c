#include <errno.h>
#include <fcntl.h>
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define FPGA_RESOURCE_PATH "/sys/bus/pci/devices/0000:00:08.0/resource0"
#define FPGA_DEVICE_PATH   "/sys/bus/pci/devices/0000:00:08.0"
#define FPGA_CONFIG_PATH   "/sys/bus/pci/devices/0000:00:08.0/config"
#define FPGA_RESOURCE_FILE "/sys/bus/pci/devices/0000:00:08.0/resource"
#define FPGA_BAR_SIZE      0x10000

#define PCI_COMMAND_OFFSET        0x04
#define PCI_COMMAND_MEMORY_SPACE  0x0002
#define PCI_COMMAND_BUS_MASTER    0x0004

#define REG_CONTROL                 0x0000
#define REG_STATUS                  0x0004
#define REG_ELECTRONS_N_BANDS       0x0100
#define REG_ELECTRONS_N_BASIS       0x0104
#define REG_ELECTRONS_N_KPOINTS     0x0108
#define REG_ELECTRONS_N_SPIN        0x010C
#define REG_ELECTRONS_MAX_ITER      0x0110
#define REG_ELECTRONS_CONV_THR      0x0114
#define REG_ELECTRONS_DIAG_THR      0x0118
#define REG_ELECTRONS_MIXING_BETA   0x011C
#define REG_ELECTRONS_MIXING_NDIM   0x0120
#define REG_ELECTRONS_ENABLE_CIM    0x0124
#define REG_ELECTRONS_CMD           0x0128
#define REG_ELECTRONS_STATUS        0x012C
#define REG_ELECTRONS_CONVERGED     0x0130
#define REG_ELECTRONS_ITERATIONS    0x0134
#define REG_ELECTRONS_FINAL_ERROR   0x0138
#define REG_ELECTRONS_TOTAL_ENERGY  0x013C

static volatile uint32_t *regs;

static inline void write_reg(uint32_t offset, uint32_t value)
{
    regs[offset / 4] = value;
}

static inline uint32_t read_reg(uint32_t offset)
{
    return regs[offset / 4];
}

static inline uint32_t float_to_bits(float value)
{
    union {
        float f;
        uint32_t u;
    } conv;
    conv.f = value;
    return conv.u;
}

static inline float bits_to_float(uint32_t value)
{
    union {
        float f;
        uint32_t u;
    } conv;
    conv.u = value;
    return conv.f;
}

static void list_pci_devices(void)
{
    DIR *dir = opendir("/sys/bus/pci/devices");
    if (!dir) {
        fprintf(stderr, "Failed to open /sys/bus/pci/devices: %s\n", strerror(errno));
        return;
    }

    printf("PCI devices visible in /sys/bus/pci/devices:\n");
    struct dirent *de;
    while ((de = readdir(dir)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) {
            continue;
        }
        printf("  %s\n", de->d_name);
    }
    closedir(dir);
}

static void probe_path(const char *path)
{
    struct stat st;
    int rc = stat(path, &st);
    if (rc == 0) {
        printf("Path exists: %s\n", path);
    } else {
        printf("Path missing: %s (%s)\n", path, strerror(errno));
    }
}

static void dump_text_file(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        printf("Could not open %s: %s\n", path, strerror(errno));
        return;
    }

    printf("Contents of %s:\n", path);
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        fputs(line, stdout);
    }
    printf("\n");
    fclose(f);
}

static void dump_config_header(const char *path)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        printf("Could not open %s for config dump: %s\n", path, strerror(errno));
        return;
    }

    unsigned char buf[64];
    ssize_t n = read(fd, buf, sizeof(buf));
    close(fd);
    if (n <= 0) {
        printf("Could not read PCI config header from %s: %s\n", path, strerror(errno));
        return;
    }

    printf("First %zd bytes of PCI config header from %s:\n", n, path);
    for (ssize_t i = 0; i < n; ++i) {
        if (i % 16 == 0) {
            printf("  %02zx:", (size_t)i);
        }
        printf(" %02x", buf[i]);
        if (i % 16 == 15 || i == n - 1) {
            printf("\n");
        }
    }
    printf("\n");
}

static int enable_pci_device_memory(const char *path)
{
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "Failed to open %s for command update: %s\n",
                path, strerror(errno));
        return -1;
    }

    uint16_t command = 0;
    ssize_t n = pread(fd, &command, sizeof(command), PCI_COMMAND_OFFSET);
    if (n != (ssize_t)sizeof(command)) {
        fprintf(stderr, "Failed to read PCI command register: %s\n",
                n < 0 ? strerror(errno) : "short read");
        close(fd);
        return -1;
    }

    printf("PCI command before enable: 0x%04x\n", command);

    uint16_t new_command = command | PCI_COMMAND_MEMORY_SPACE |
                           PCI_COMMAND_BUS_MASTER;
    if (new_command != command) {
        n = pwrite(fd, &new_command, sizeof(new_command), PCI_COMMAND_OFFSET);
        if (n != (ssize_t)sizeof(new_command)) {
            fprintf(stderr, "Failed to write PCI command register: %s\n",
                    n < 0 ? strerror(errno) : "short write");
            close(fd);
            return -1;
        }
    }

    command = 0;
    n = pread(fd, &command, sizeof(command), PCI_COMMAND_OFFSET);
    if (n != (ssize_t)sizeof(command)) {
        fprintf(stderr, "Failed to re-read PCI command register: %s\n",
                n < 0 ? strerror(errno) : "short read");
        close(fd);
        return -1;
    }

    printf("PCI command after enable:  0x%04x\n\n", command);
    close(fd);
    return (command & PCI_COMMAND_MEMORY_SPACE) ? 0 : -1;
}

int main(void)
{
    printf("==============================================\n");
    printf("PCIe FPGA electrons() smoke test\n");
    printf("==============================================\n\n");

    list_pci_devices();
    probe_path(FPGA_DEVICE_PATH);
    probe_path(FPGA_CONFIG_PATH);
    probe_path(FPGA_RESOURCE_FILE);
    probe_path(FPGA_RESOURCE_PATH);
    printf("\n");
    dump_text_file(FPGA_RESOURCE_FILE);
    dump_config_header(FPGA_CONFIG_PATH);
    if (enable_pci_device_memory(FPGA_CONFIG_PATH) != 0) {
        fprintf(stderr, "Failed to enable PCI memory space for FPGA device\n");
        return 1;
    }
    dump_config_header(FPGA_CONFIG_PATH);

    int fd = open(FPGA_RESOURCE_PATH, O_RDWR | O_SYNC);
    if (fd < 0) {
        fprintf(stderr, "Failed to open %s: %s\n", FPGA_RESOURCE_PATH, strerror(errno));
        return 1;
    }

    regs = (volatile uint32_t *)mmap(NULL, FPGA_BAR_SIZE, PROT_READ | PROT_WRITE,
                                     MAP_SHARED, fd, 0);
    if (regs == MAP_FAILED) {
        fprintf(stderr, "Failed to mmap BAR0: %s\n", strerror(errno));
        close(fd);
        return 1;
    }

    printf("BAR0 mapped successfully.\n");
    printf("Initial status: 0x%08x\n", read_reg(REG_STATUS));

    write_reg(REG_ELECTRONS_N_BANDS, 32);
    write_reg(REG_ELECTRONS_N_BASIS, 128);
    write_reg(REG_ELECTRONS_N_KPOINTS, 1);
    write_reg(REG_ELECTRONS_N_SPIN, 1);
    write_reg(REG_ELECTRONS_MAX_ITER, 12);
    write_reg(REG_ELECTRONS_CONV_THR, float_to_bits(1.0e-6f));
    write_reg(REG_ELECTRONS_DIAG_THR, float_to_bits(1.0e-3f));
    write_reg(REG_ELECTRONS_MIXING_BETA, float_to_bits(0.7f));
    write_reg(REG_ELECTRONS_MIXING_NDIM, 8);
    write_reg(REG_ELECTRONS_ENABLE_CIM, 1);

    printf("Parameters written. Launching electrons command...\n");
    write_reg(REG_ELECTRONS_CMD, 1);

    for (int i = 0; i < 1000; ++i) {
        uint32_t status = read_reg(REG_ELECTRONS_STATUS);
        if (status & 0x1) {
            break;
        }
        usleep(1000);
    }

    printf("Electrons status:      0x%08x\n", read_reg(REG_ELECTRONS_STATUS));
    printf("Converged:             %u\n", read_reg(REG_ELECTRONS_CONVERGED));
    printf("Iterations:            %u\n", read_reg(REG_ELECTRONS_ITERATIONS));
    printf("Final error (float):   %.6e\n", bits_to_float(read_reg(REG_ELECTRONS_FINAL_ERROR)));
    printf("Total energy (float):  %.6f\n", bits_to_float(read_reg(REG_ELECTRONS_TOTAL_ENERGY)));

    munmap((void *)regs, FPGA_BAR_SIZE);
    close(fd);

    printf("\nSmoke test complete.\n");
    return 0;
}
