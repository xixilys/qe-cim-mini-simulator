#include "fpga_pci_wrapper.h"
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    printf("==============================================\n");
    printf("Minimal QE-like FPGA offload test\n");
    printf("==============================================\n\n");

    if (!fpga_pci_is_available(NULL)) {
        fprintf(stderr, "FPGA PCI device not available\n");
        return 1;
    }
    printf("FPGA PCI device detected\n\n");

    fpga_pci_device_t dev;
    if (fpga_pci_init(&dev, NULL) != 0) {
        fprintf(stderr, "Failed to initialize FPGA device\n");
        return 1;
    }
    printf("FPGA device initialized successfully\n\n");

    fpga_electrons_params_t params = {
        .n_bands = 32,
        .n_basis = 128,
        .n_kpoints = 1,
        .n_spin = 1,
        .max_iter = 12,
        .conv_thr = 1.0e-6f,
        .diag_thr = 1.0e-3f,
        .mixing_beta = 0.7f,
        .mixing_ndim = 8,
        .enable_cim = 1
    };

    fpga_electrons_result_t result;
    
    printf("Executing electrons() offload:\n");
    printf("  n_bands=%u, n_basis=%u, n_kpoints=%u, n_spin=%u\n",
           params.n_bands, params.n_basis, params.n_kpoints, params.n_spin);
    printf("  max_iter=%u, conv_thr=%.1e, enable_cim=%u\n\n",
           params.max_iter, params.conv_thr, params.enable_cim);

    if (fpga_pci_electrons(&dev, &params, &result) != 0) {
        fprintf(stderr, "electrons() offload failed\n");
        fpga_pci_cleanup(&dev);
        return 1;
    }

    printf("electrons() offload completed:\n");
    printf("  Converged:     %s\n", result.converged ? "YES" : "NO");
    printf("  Iterations:    %u\n", result.iterations);
    printf("  Final error:   %.6e\n", result.final_error);
    printf("  Total energy:  %.6f\n\n", result.total_energy);

    fpga_pci_cleanup(&dev);

    printf("==============================================\n");
    printf("QE-like offload test PASSED\n");
    printf("==============================================\n");

    return 0;
}
