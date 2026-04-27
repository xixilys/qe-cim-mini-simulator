#include "fpga_systemc_wrapper.h"
#include "dft_hybrid_system_gem5.hpp"
#include <systemc>
#include <cstring>
#include <cstdio>

using namespace sc_core;
using namespace qebs;

static DFTHybridSystemGem5* g_dft_system = nullptr;
static char g_error_msg[256] = {0};
static bool g_initialized = false;

static void set_error(const char* msg) {
    snprintf(g_error_msg, sizeof(g_error_msg), "%s", msg);
}

int systemc_fpga_init(const char* architecture) {
    if (g_initialized) {
        set_error("SystemC already initialized");
        return -1;
    }
    
    try {
        ArchitectureConfig config = ArchitectureConfig::create_default();
        
        g_dft_system = new DFTHybridSystemGem5("dft_system", config, false);
        g_initialized = true;
        
        printf("[SystemC] FPGA model initialized with architecture: %s (using default F2)\n", architecture);
        return 0;
        
    } catch (const std::exception& e) {
        set_error(e.what());
        return -1;
    }
}

int systemc_fpga_electrons(
    const systemc_electrons_request_t* req,
    systemc_electrons_result_t* result
) {
    if (!g_initialized || !g_dft_system) {
        set_error("SystemC not initialized (call systemc_fpga_init first)");
        return -1;
    }
    
    if (!req || !result) {
        set_error("NULL pointer in request or result");
        return -1;
    }
    
    try {
        DFTHybridSystemGem5::ElectronsRequest sc_req;
        sc_req.n_bands = req->n_bands;
        sc_req.n_basis = req->n_basis;
        sc_req.n_kpoints = req->n_kpoints;
        sc_req.n_spin = req->n_spin;
        sc_req.max_iterations = req->max_iterations;
        sc_req.conv_threshold = req->conv_threshold;
        sc_req.diag_threshold = req->diag_threshold;
        sc_req.mixing_beta = req->mixing_beta;
        sc_req.mixing_ndim = req->mixing_ndim;
        sc_req.enable_cim = req->enable_cim;
        
        printf("[SystemC] Executing electrons loop: n_bands=%d, max_iter=%d, conv_thr=%.2e\n",
               req->n_bands, req->max_iterations, req->conv_threshold);
        
        DFTHybridSystemGem5::ElectronsResult sc_result = 
            g_dft_system->execute_electrons_from_gem5(sc_req);
        
        result->converged = sc_result.converged;
        result->iterations = sc_result.iterations;
        result->final_error = sc_result.final_error;
        result->total_energy = sc_result.total_energy;
        result->total_time_ns = sc_result.total_time_ns;
        
        printf("[SystemC] Electrons loop complete: converged=%d, iterations=%d, energy=%.6f\n",
               result->converged, result->iterations, result->total_energy);
        
        return 0;
        
    } catch (const std::exception& e) {
        set_error(e.what());
        return -1;
    }
}

int systemc_fpga_c_bands(const systemc_c_bands_request_t* req) {
    if (!g_initialized || !g_dft_system) {
        set_error("SystemC not initialized (call systemc_fpga_init first)");
        return -1;
    }
    
    if (!req) {
        set_error("NULL pointer in request");
        return -1;
    }
    
    try {
        DFTHybridSystemGem5::CBandsRequest sc_req;
        sc_req.n = req->n;
        sc_req.m = req->m;
        sc_req.k = req->k;
        sc_req.h_matrix_addr = 0x100000000ULL;
        sc_req.s_matrix_addr = 0x200000000ULL;
        sc_req.result_addr = 0x300000000ULL;
        
        printf("[SystemC] Executing c_bands: n=%d, m=%d, k=%d\n", req->n, req->m, req->k);
        
        g_dft_system->execute_c_bands_from_gem5(sc_req);
        
        printf("[SystemC] c_bands complete\n");
        
        return 0;
        
    } catch (const std::exception& e) {
        set_error(e.what());
        return -1;
    }
}

void systemc_fpga_finalize(void) {
    if (g_initialized && g_dft_system) {
        delete g_dft_system;
        g_dft_system = nullptr;
        g_initialized = false;
        printf("[SystemC] FPGA model finalized\n");
    }
}

const char* systemc_fpga_get_error(void) {
    return g_error_msg;
}
