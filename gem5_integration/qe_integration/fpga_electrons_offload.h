/*
 * FPGA Offload Interface for Complete Electrons Loop
 * 
 * This header defines the interface for offloading the entire electrons
 * self-consistency loop to the FPGA accelerator, including:
 * - c_bands: Band structure calculation (4-Cluster pipeline)
 * - sum_band: Charge density summation
 * - mix_rho: Density mixing
 * - Convergence checking
 */

#ifndef FPGA_ELECTRONS_OFFLOAD_H
#define FPGA_ELECTRONS_OFFLOAD_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Data Structures
 * ============================================================================ */

/**
 * @brief Complete electrons loop request
 * 
 * Contains all parameters needed to run the full SCF loop on FPGA
 */
typedef struct {
    /* System dimensions */
    int n_bands;              /**< Number of bands (nbnd) */
    int n_basis;              /**< Number of basis functions (npwx) */
    int n_kpoints;            /**< Number of k-points (nks) */
    int n_spin;               /**< Number of spin channels (nspin) */
    int n_electrons;          /**< Number of electrons (nelec) */
    
    /* SCF convergence parameters */
    int max_iterations;       /**< Maximum SCF iterations (niter) */
    double conv_threshold;    /**< Convergence threshold on density (tr2) */
    double diag_threshold;    /**< Diagonalization threshold (ethr) */
    bool adaptive_threshold;  /**< Use adaptive ethr (adapt_thr) */
    
    /* Mixing parameters */
    double mixing_beta;       /**< Mixing parameter (mixing_beta) */
    int mixing_ndim;          /**< Mixing history dimension (nmix) */
    char mixing_mode[32];     /**< Mixing mode: "plain", "TF", "local-TF" */
    
    /* Physical parameters */
    double temperature;       /**< Electronic temperature (degauss) */
    char occupations[32];     /**< Occupation mode: "smearing", "tetrahedra", "fixed" */
    
    /* Flags */
    bool use_paw;             /**< PAW calculation (okpaw) */
    bool use_uspp;            /**< Ultrasoft pseudopotentials (okvan) */
    bool lda_plus_u;          /**< DFT+U calculation */
    bool noncolin;            /**< Non-collinear magnetism */
    
    /* FPGA-specific parameters */
    char architecture[32];    /**< Architecture: "F1", "F2", "F3", "custom" */
    char resident_policy[32]; /**< Data residency: "persistent", "transient" */
    bool enable_cim;          /**< Enable CIM acceleration */
    
} fpga_electrons_request_t;

/**
 * @brief Electrons loop result
 */
typedef struct {
    /* Convergence status */
    bool converged;           /**< SCF converged */
    int iterations;           /**< Number of iterations performed */
    double final_error;       /**< Final density error (dr2) */
    
    /* Energies (in Ry) */
    double total_energy;      /**< Total energy (etot) */
    double band_energy;       /**< Band energy (eband) */
    double hartree_energy;    /**< Hartree energy (ehart) */
    double xc_energy;         /**< Exchange-correlation energy (etxc) */
    double ewald_energy;      /**< Ewald energy (ewld) */
    double paw_energy;        /**< PAW one-center energy (epaw) */
    
    /* Fermi energy */
    double fermi_energy;      /**< Fermi energy (ef) */
    double fermi_energy_up;   /**< Fermi energy spin-up (ef_up) */
    double fermi_energy_down; /**< Fermi energy spin-down (ef_dw) */
    
    /* Performance metrics */
    double total_time_ns;     /**< Total execution time (ns) */
    double c_bands_time_ns;   /**< c_bands time (ns) */
    double sum_band_time_ns;  /**< sum_band time (ns) */
    double mix_rho_time_ns;   /**< mix_rho time (ns) */
    
    /* Detailed timing per iteration */
    double* iter_times_ns;    /**< Time per iteration (array of size iterations) */
    double* iter_errors;      /**< Error per iteration (array of size iterations) */
    
} fpga_electrons_result_t;

/**
 * @brief Individual c_bands request (for single k-point)
 */
typedef struct {
    int ik;                   /**< k-point index */
    int npw;                  /**< Number of plane waves for this k-point */
    int nbnd;                 /**< Number of bands */
    
    /* Matrix addresses in device memory */
    uint64_t h_matrix_addr;   /**< Hamiltonian matrix H */
    uint64_t s_matrix_addr;   /**< Overlap matrix S */
    uint64_t evc_addr;        /**< Wavefunctions (input/output) */
    uint64_t et_addr;         /**< Eigenvalues (output) */
    
    /* Diagonalization parameters */
    double ethr;              /**< Threshold for iterative diagonalization */
    int max_iter;             /**< Maximum iterations for diagonalization */
    
} fpga_c_bands_kpoint_request_t;

/**
 * @brief sum_band request
 */
typedef struct {
    int n_bands;
    int n_kpoints;
    int n_spin;
    
    /* Input: eigenvalues and wavefunctions */
    uint64_t et_addr;         /**< Eigenvalues et(nbnd, nks) */
    uint64_t evc_addr;        /**< Wavefunctions evc(npwx, nbnd, nks) */
    uint64_t wg_addr;         /**< Weights wg(nbnd, nks) - output */
    
    /* Output: charge density */
    uint64_t rho_addr;        /**< Charge density rho(nnr, nspin) */
    
    /* Parameters */
    double fermi_energy;      /**< Fermi energy (input/output) */
    double temperature;       /**< Electronic temperature */
    
} fpga_sum_band_request_t;

/**
 * @brief mix_rho request
 */
typedef struct {
    int nnr;                  /**< FFT grid size */
    int nspin;                /**< Number of spin channels */
    
    /* Input/output densities */
    uint64_t rho_in_addr;     /**< Input density (mixed) */
    uint64_t rho_out_addr;    /**< Output density (from sum_band) */
    
    /* Mixing parameters */
    double mixing_beta;
    int mixing_ndim;
    int iteration;
    
    /* Output */
    double* dr2;              /**< Density error (output) */
    bool* converged;          /**< Convergence flag (output) */
    
} fpga_mix_rho_request_t;

/* ============================================================================
 * Main API Functions
 * ============================================================================ */

/**
 * @brief Offload complete electrons loop to FPGA
 * 
 * This function offloads the entire SCF self-consistency loop to the FPGA,
 * including c_bands, sum_band, mix_rho, and convergence checking.
 * 
 * @param dev FPGA device handle
 * @param req Electrons loop request parameters
 * @param initial_rho Initial charge density (host memory)
 * @param initial_wfc Initial wavefunctions (host memory, can be NULL)
 * @param result Result structure (output)
 * @param final_rho Final converged charge density (host memory, output)
 * @param final_wfc Final wavefunctions (host memory, output)
 * @param final_et Final eigenvalues (host memory, output)
 * @return 0 on success, negative on error
 */
int fpga_electrons_offload(
    fpga_device_t* dev,
    const fpga_electrons_request_t* req,
    const void* initial_rho,
    const void* initial_wfc,
    fpga_electrons_result_t* result,
    void* final_rho,
    void* final_wfc,
    void* final_et
);

/**
 * @brief Offload single c_bands iteration for one k-point
 * 
 * This executes the 4-Cluster pipeline for a single k-point:
 * - Cluster A: h_psi and s_psi computation
 * - Cluster B: Build subspace matrices H_sub and S_sub
 * - Cluster C: Diagonalize subspace (cdiaghg)
 * - Cluster D: Refresh wavefunctions
 * 
 * @param dev FPGA device handle
 * @param req c_bands request for single k-point
 * @return 0 on success, negative on error
 */
int fpga_c_bands_kpoint_offload(
    fpga_device_t* dev,
    const fpga_c_bands_kpoint_request_t* req
);

/**
 * @brief Offload sum_band computation
 * 
 * Computes charge density from eigenvalues and wavefunctions
 * 
 * @param dev FPGA device handle
 * @param req sum_band request
 * @return 0 on success, negative on error
 */
int fpga_sum_band_offload(
    fpga_device_t* dev,
    const fpga_sum_band_request_t* req
);

/**
 * @brief Offload mix_rho computation
 * 
 * Mixes input and output charge densities
 * 
 * @param dev FPGA device handle
 * @param req mix_rho request
 * @return 0 on success, negative on error
 */
int fpga_mix_rho_offload(
    fpga_device_t* dev,
    const fpga_mix_rho_request_t* req
);

/* ============================================================================
 * Utility Functions
 * ============================================================================ */

/**
 * @brief Initialize electrons request with default values
 */
void fpga_electrons_request_init(fpga_electrons_request_t* req);

/**
 * @brief Free resources in electrons result
 */
void fpga_electrons_result_free(fpga_electrons_result_t* result);

/**
 * @brief Print electrons result summary
 */
void fpga_electrons_result_print(const fpga_electrons_result_t* result);

#ifdef __cplusplus
}
#endif

#endif /* FPGA_ELECTRONS_OFFLOAD_H */
