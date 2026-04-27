/*
 * SystemC FPGA Model C Wrapper
 * 
 * This provides a C interface to the SystemC DFT FPGA model,
 * allowing direct integration with QE Fortran code without gem5.
 */

#ifndef FPGA_SYSTEMC_WRAPPER_H
#define FPGA_SYSTEMC_WRAPPER_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Data Structures (matching SystemC model)
 * ============================================================================ */

/**
 * @brief Electrons loop request (simplified for SystemC)
 */
typedef struct {
    int n_bands;
    int n_basis;
    int n_kpoints;
    int n_spin;
    int max_iterations;
    double conv_threshold;
    double diag_threshold;
    double mixing_beta;
    int mixing_ndim;
    bool enable_cim;
} systemc_electrons_request_t;

/**
 * @brief Electrons loop result
 */
typedef struct {
    bool converged;
    int iterations;
    double final_error;
    double total_energy;
    double total_time_ns;
} systemc_electrons_result_t;

/**
 * @brief c_bands request (single call)
 */
typedef struct {
    int n;      /* Number of bands */
    int m;      /* Number of basis functions */
    int k;      /* Number of k-points */
} systemc_c_bands_request_t;

/* ============================================================================
 * API Functions
 * ============================================================================ */

/**
 * @brief Initialize SystemC simulation
 * 
 * Must be called once before any other functions.
 * Initializes the SystemC kernel and creates the DFT FPGA model.
 * 
 * @param architecture Architecture name: "F1", "F2", "F3"
 * @return 0 on success, negative on error
 */
int systemc_fpga_init(const char* architecture);

/**
 * @brief Execute complete electrons loop on SystemC FPGA model
 * 
 * Runs the full SCF loop with 4-Cluster pipeline.
 * 
 * @param req Request parameters
 * @param result Result structure (output)
 * @return 0 on success, negative on error
 */
int systemc_fpga_electrons(
    const systemc_electrons_request_t* req,
    systemc_electrons_result_t* result
);

/**
 * @brief Execute single c_bands computation
 * 
 * Runs one c_bands call through the 4-Cluster pipeline.
 * 
 * @param req Request parameters
 * @return 0 on success, negative on error
 */
int systemc_fpga_c_bands(
    const systemc_c_bands_request_t* req
);

/**
 * @brief Finalize SystemC simulation
 * 
 * Cleans up SystemC kernel and destroys the DFT model.
 * Must be called at the end of the program.
 */
void systemc_fpga_finalize(void);

/**
 * @brief Get last error message
 * 
 * @return Error message string (valid until next call)
 */
const char* systemc_fpga_get_error(void);

#ifdef __cplusplus
}
#endif

#endif /* FPGA_SYSTEMC_WRAPPER_H */
