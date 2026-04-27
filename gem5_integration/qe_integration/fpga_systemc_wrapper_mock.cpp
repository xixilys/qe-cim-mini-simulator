#include "fpga_systemc_wrapper.h"
#include <cstring>
#include <cstdio>
#include <cmath>

static char g_error_msg[256] = {0};
static bool g_initialized = false;
static char g_architecture[32] = "F2";

static void set_error(const char* msg) {
    snprintf(g_error_msg, sizeof(g_error_msg), "%s", msg);
}

int systemc_fpga_init(const char* architecture) {
    if (g_initialized) {
        set_error("SystemC already initialized");
        return -1;
    }
    
    strncpy(g_architecture, architecture, sizeof(g_architecture) - 1);
    g_initialized = true;
    
    printf("[SystemC Mock] FPGA model initialized with architecture: %s\n", architecture);
    printf("[SystemC Mock] Using DSE-derived performance model (mock mode)\n");
    return 0;
}

int systemc_fpga_electrons(
    const systemc_electrons_request_t* req,
    systemc_electrons_result_t* result
) {
    if (!g_initialized) {
        set_error("SystemC not initialized (call systemc_fpga_init first)");
        return -1;
    }
    
    if (!req || !result) {
        set_error("NULL pointer in request or result");
        return -1;
    }
    
    printf("[SystemC Mock] Executing electrons loop: n_bands=%d, max_iter=%d, conv_thr=%.2e\n",
           req->n_bands, req->max_iterations, req->conv_threshold);
    
    double base_cycles_per_cbands = 3246.0;
    double band_scaling = (double)req->n_bands / 32.0;
    double basis_scaling = (double)req->n_basis / 128.0;
    double cycles_per_cbands = base_cycles_per_cbands * band_scaling * basis_scaling;
    
    double clock_period_ns = 5.0;
    
    int converged_iter = (int)(req->max_iterations * 0.7);
    if (converged_iter < 3) converged_iter = 3;
    if (converged_iter > req->max_iterations) converged_iter = req->max_iterations;
    
    double total_cbands_time = 0.0;
    for (int iter = 0; iter < converged_iter; iter++) {
        double iter_cycles = cycles_per_cbands * req->n_kpoints;
        total_cbands_time += iter_cycles * clock_period_ns;
    }
    
    double sum_band_time_per_iter = 100.0;
    double mix_rho_time_per_iter = 50.0;
    double total_sum_band_time = sum_band_time_per_iter * converged_iter;
    double total_mix_rho_time = mix_rho_time_per_iter * converged_iter;
    
    result->converged = true;
    result->iterations = converged_iter;
    result->final_error = req->conv_threshold * 0.1;
    result->total_energy = -15.8 - 0.1 * converged_iter;
    result->total_time_ns = total_cbands_time + total_sum_band_time + total_mix_rho_time;
    
    printf("[SystemC Mock] Electrons loop complete: converged=%d, iterations=%d, energy=%.6f\n",
           result->converged, result->iterations, result->total_energy);
    printf("[SystemC Mock] Total time: %.3f ms (c_bands: %.3f ms)\n",
           result->total_time_ns / 1e6, total_cbands_time / 1e6);
    
    return 0;
}

int systemc_fpga_c_bands(const systemc_c_bands_request_t* req) {
    if (!g_initialized) {
        set_error("SystemC not initialized (call systemc_fpga_init first)");
        return -1;
    }
    
    if (!req) {
        set_error("NULL pointer in request");
        return -1;
    }
    
    printf("[SystemC Mock] Executing c_bands: n=%d, m=%d, k=%d\n", req->n, req->m, req->k);
    
    double base_cycles = 3246.0;
    double band_scaling = (double)req->n / 32.0;
    double basis_scaling = (double)req->m / 128.0;
    double cycles = base_cycles * band_scaling * basis_scaling;
    
    printf("[SystemC Mock] c_bands complete: %.0f cycles (%.3f ms @ 200MHz)\n",
           cycles, cycles * 5.0 / 1e6);
    
    return 0;
}

void systemc_fpga_finalize(void) {
    if (g_initialized) {
        g_initialized = false;
        printf("[SystemC Mock] FPGA model finalized\n");
    }
}

const char* systemc_fpga_get_error(void) {
    return g_error_msg;
}
