#ifndef FPGA_PCI_WRAPPER_H
#define FPGA_PCI_WRAPPER_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Minimal wrapper around the working PCI BAR path
// Maps to the REG_ELECTRONS_* register layout in gem5 FPGAAccelerator

typedef struct {
    int config_fd;
    int resource_fd;
    void* bar0_base;
    size_t bar0_size;
    bool initialized;
} fpga_pci_device_t;

typedef struct {
    uint32_t n_bands;
    uint32_t n_basis;
    uint32_t n_kpoints;
    uint32_t n_spin;
    uint32_t max_iter;
    float conv_thr;
    float diag_thr;
    float mixing_beta;
    uint32_t mixing_ndim;
    uint32_t enable_cim;
} fpga_electrons_params_t;

typedef struct {
    uint32_t converged;
    uint32_t iterations;
    float final_error;
    float total_energy;
} fpga_electrons_result_t;

// Initialize FPGA device using sysfs PCI BAR path
int fpga_pci_init(fpga_pci_device_t* dev, const char* pci_device_path);

void fpga_pci_cleanup(fpga_pci_device_t* dev);

int fpga_pci_electrons(fpga_pci_device_t* dev,
                       const fpga_electrons_params_t* params,
                       fpga_electrons_result_t* result);

bool fpga_pci_is_available(const char* pci_device_path);

#ifdef __cplusplus
}
#endif

#endif
