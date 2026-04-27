/*
 * QE FPGA Offload Benchmark
 * Tests electrons() offload with various problem sizes
 */

#include "fpga_pci_wrapper.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include <sys/time.h>

// Workload definitions
typedef struct {
    const char* name;
    uint32_t n_bands;
    uint32_t n_basis;
    uint32_t n_kpoints;
    uint32_t n_spin;
    uint32_t max_iter;
    float conv_thr;
} Workload;

static const Workload workloads[] = {
    {"si_small",   16,   64,  1, 1, 50,  1e-6f},
    {"si_medium",  32,  128,  1, 1, 50,  1e-6f},
    {"si_large",   64,  256,  1, 1, 50,  1e-6f},
    {"graphene",   48,  192,  4, 1, 50,  1e-6f},
    {"au_slab",    64,  256,  8, 1, 50,  1e-6f},
};

static const int num_workloads = sizeof(workloads) / sizeof(workloads[0]);

uint64_t get_time_us(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000000 + tv.tv_usec;
}

int run_workload(fpga_pci_device_t* dev, const Workload* wl) {
    fpga_electrons_params_t params = {
        .n_bands = wl->n_bands,
        .n_basis = wl->n_basis,
        .n_kpoints = wl->n_kpoints,
        .n_spin = wl->n_spin,
        .max_iter = wl->max_iter,
        .conv_thr = wl->conv_thr,
        .diag_thr = 1e-3f,
        .mixing_beta = 0.7f,
        .mixing_ndim = 8,
        .enable_cim = 1
    };

    fpga_electrons_result_t result;

    uint64_t start_us = get_time_us();

    if (fpga_pci_electrons(dev, &params, &result) != 0) {
        fprintf(stderr, "  ERROR: electrons offload failed\n");
        return -1;
    }

    uint64_t end_us = get_time_us();
    double elapsed_ms = (end_us - start_us) / 1000.0;

    printf("  %-12s: %4u bands, %4u basis, %2u kpoints\n",
           wl->name, wl->n_bands, wl->n_basis, wl->n_kpoints);
    printf("  %12s: converged=%s, iter=%u, error=%.2e\n",
           "", result.converged ? "YES" : "NO", result.iterations, result.final_error);
    printf("  %12s: energy=%.6f Ry, time=%.3f ms\n",
           "", result.total_energy, elapsed_ms);

    return 0;
}

int main(void) {
    printf("============================================================\n");
    printf("QE FPGA Offload Benchmark Suite\n");
    printf("============================================================\n\n");

    // Check FPGA availability
    if (!fpga_pci_is_available(NULL)) {
        fprintf(stderr, "ERROR: FPGA PCI device not available\n");
        return 1;
    }
    printf("[OK] FPGA PCI device detected\n\n");

    // Initialize FPGA device
    fpga_pci_device_t dev;
    if (fpga_pci_init(&dev, NULL) != 0) {
        fprintf(stderr, "ERROR: Failed to initialize FPGA device\n");
        return 1;
    }
    printf("[OK] FPGA device initialized\n\n");

    // Run benchmark suite
    printf("Running benchmark suite...\n");
    printf("------------------------------------------------------------\n\n");

    int passed = 0;
    int failed = 0;

    for (int i = 0; i < num_workloads; i++) {
        printf("[%d/%d] Workload: %s\n", i + 1, num_workloads, workloads[i].name);

        if (run_workload(&dev, &workloads[i]) == 0) {
            passed++;
        } else {
            failed++;
        }
        printf("\n");
    }

    // Summary
    printf("============================================================\n");
    printf("Benchmark Summary\n");
    printf("============================================================\n");
    printf("Total workloads: %d\n", num_workloads);
    printf("Passed: %d\n", passed);
    printf("Failed: %d\n", failed);
    printf("============================================================\n");

    // Cleanup
    fpga_pci_cleanup(&dev);

    return failed > 0 ? 1 : 0;
}
