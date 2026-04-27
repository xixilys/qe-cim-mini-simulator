#include "fpga_pci_wrapper.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define PCI_COMMAND_OFFSET        0x04
#define PCI_COMMAND_MEMORY_SPACE  0x0002
#define PCI_COMMAND_BUS_MASTER    0x0004

#define FPGA_BAR_SIZE             0x10000

// Register offsets matching gem5 FPGAAccelerator
#define REG_STATUS                0x0004
#define REG_ELECTRONS_N_BANDS     0x0100
#define REG_ELECTRONS_N_BASIS     0x0104
#define REG_ELECTRONS_N_KPOINTS   0x0108
#define REG_ELECTRONS_N_SPIN      0x010C
#define REG_ELECTRONS_MAX_ITER    0x0110
#define REG_ELECTRONS_CONV_THR    0x0114
#define REG_ELECTRONS_DIAG_THR    0x0118
#define REG_ELECTRONS_MIXING_BETA 0x011C
#define REG_ELECTRONS_MIXING_NDIM 0x0120
#define REG_ELECTRONS_ENABLE_CIM  0x0124
#define REG_ELECTRONS_CMD         0x0128
#define REG_ELECTRONS_STATUS      0x012C
#define REG_ELECTRONS_CONVERGED   0x0130
#define REG_ELECTRONS_ITERATIONS  0x0134
#define REG_ELECTRONS_FINAL_ERROR 0x0138
#define REG_ELECTRONS_TOTAL_ENERGY 0x013C

static inline void write_reg(fpga_pci_device_t* dev, uint32_t offset, uint32_t value) {
    volatile uint32_t* reg = (volatile uint32_t*)((char*)dev->bar0_base + offset);
    *reg = value;
}

static inline uint32_t read_reg(fpga_pci_device_t* dev, uint32_t offset) {
    volatile uint32_t* reg = (volatile uint32_t*)((char*)dev->bar0_base + offset);
    return *reg;
}

static inline uint32_t float_to_bits(float value) {
    union { float f; uint32_t u; } conv;
    conv.f = value;
    return conv.u;
}

static inline float bits_to_float(uint32_t value) {
    union { float f; uint32_t u; } conv;
    conv.u = value;
    return conv.f;
}

static int enable_pci_memory(const char* config_path) {
    int fd = open(config_path, O_RDWR);
    if (fd < 0) {
        return -1;
    }

    uint16_t command = 0;
    if (pread(fd, &command, sizeof(command), PCI_COMMAND_OFFSET) != sizeof(command)) {
        close(fd);
        return -1;
    }

    uint16_t new_command = command | PCI_COMMAND_MEMORY_SPACE | PCI_COMMAND_BUS_MASTER;
    if (new_command != command) {
        if (pwrite(fd, &new_command, sizeof(new_command), PCI_COMMAND_OFFSET) != sizeof(new_command)) {
            close(fd);
            return -1;
        }
    }

    close(fd);
    return 0;
}

int fpga_pci_init(fpga_pci_device_t* dev, const char* pci_device_path) {
    if (!dev) return -1;
    
    memset(dev, 0, sizeof(fpga_pci_device_t));
    
    if (!pci_device_path) {
        pci_device_path = "/sys/bus/pci/devices/0000:00:08.0";
    }
    
    char config_path[256];
    char resource_path[256];
    snprintf(config_path, sizeof(config_path), "%s/config", pci_device_path);
    snprintf(resource_path, sizeof(resource_path), "%s/resource0", pci_device_path);
    
    if (enable_pci_memory(config_path) != 0) {
        fprintf(stderr, "Failed to enable PCI memory space\n");
        return -1;
    }
    
    dev->resource_fd = open(resource_path, O_RDWR | O_SYNC);
    if (dev->resource_fd < 0) {
        fprintf(stderr, "Failed to open %s: %s\n", resource_path, strerror(errno));
        return -1;
    }
    
    dev->bar0_base = mmap(NULL, FPGA_BAR_SIZE, PROT_READ | PROT_WRITE,
                          MAP_SHARED, dev->resource_fd, 0);
    if (dev->bar0_base == MAP_FAILED) {
        fprintf(stderr, "Failed to mmap BAR0: %s\n", strerror(errno));
        close(dev->resource_fd);
        return -1;
    }
    
    dev->bar0_size = FPGA_BAR_SIZE;
    dev->initialized = true;
    
    uint32_t status = read_reg(dev, REG_STATUS);
    if ((status & 0x01) == 0) {
        fprintf(stderr, "FPGA device not ready (status=0x%x)\n", status);
        fpga_pci_cleanup(dev);
        return -1;
    }
    
    return 0;
}

void fpga_pci_cleanup(fpga_pci_device_t* dev) {
    if (!dev) return;
    
    if (dev->bar0_base && dev->bar0_base != MAP_FAILED) {
        munmap(dev->bar0_base, dev->bar0_size);
        dev->bar0_base = NULL;
    }
    
    if (dev->resource_fd >= 0) {
        close(dev->resource_fd);
        dev->resource_fd = -1;
    }
    
    dev->initialized = false;
}

int fpga_pci_electrons(fpga_pci_device_t* dev,
                       const fpga_electrons_params_t* params,
                       fpga_electrons_result_t* result) {
    if (!dev || !dev->initialized || !params || !result) {
        return -1;
    }
    
    write_reg(dev, REG_ELECTRONS_N_BANDS, params->n_bands);
    write_reg(dev, REG_ELECTRONS_N_BASIS, params->n_basis);
    write_reg(dev, REG_ELECTRONS_N_KPOINTS, params->n_kpoints);
    write_reg(dev, REG_ELECTRONS_N_SPIN, params->n_spin);
    write_reg(dev, REG_ELECTRONS_MAX_ITER, params->max_iter);
    write_reg(dev, REG_ELECTRONS_CONV_THR, float_to_bits(params->conv_thr));
    write_reg(dev, REG_ELECTRONS_DIAG_THR, float_to_bits(params->diag_thr));
    write_reg(dev, REG_ELECTRONS_MIXING_BETA, float_to_bits(params->mixing_beta));
    write_reg(dev, REG_ELECTRONS_MIXING_NDIM, params->mixing_ndim);
    write_reg(dev, REG_ELECTRONS_ENABLE_CIM, params->enable_cim);
    
    write_reg(dev, REG_ELECTRONS_CMD, 1);
    
    for (int i = 0; i < 1000; ++i) {
        uint32_t status = read_reg(dev, REG_ELECTRONS_STATUS);
        if (status & 0x1) {
            break;
        }
        usleep(1000);
    }
    
    result->converged = read_reg(dev, REG_ELECTRONS_CONVERGED);
    result->iterations = read_reg(dev, REG_ELECTRONS_ITERATIONS);
    result->final_error = bits_to_float(read_reg(dev, REG_ELECTRONS_FINAL_ERROR));
    result->total_energy = bits_to_float(read_reg(dev, REG_ELECTRONS_TOTAL_ENERGY));
    
    return 0;
}

bool fpga_pci_is_available(const char* pci_device_path) {
    if (!pci_device_path) {
        pci_device_path = "/sys/bus/pci/devices/0000:00:08.0";
    }
    
    char resource_path[256];
    snprintf(resource_path, sizeof(resource_path), "%s/resource0", pci_device_path);
    
    struct stat st;
    return (stat(resource_path, &st) == 0);
}
