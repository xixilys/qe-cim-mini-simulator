#pragma once

#include "systemc_compat.hpp"
#include "types.hpp"
#include <complex>
#include <vector>

namespace qebs {

// Blocked GEMM Engine for Traditional FPGA Architecture
// Implements C = alpha * A * B + beta * C using block tiling
// Optimized for DSP48E2 blocks on Xilinx UltraScale+ FPGAs
class BlockedGEMMEngine : public sc_core::sc_module {
 public:
  explicit BlockedGEMMEngine(sc_core::sc_module_name name);

  // GEMM configuration parameters
  struct GEMMConfig {
    int m;              // Number of rows in A
    int n;              // Number of columns in B
    int k;              // Number of columns in A / rows in B
    int block_size;     // Tile size for blocking (default: 32)
    int dsp_array_dim;  // DSP array dimension (default: 16)
    int clock_freq_mhz; // Clock frequency in MHz (default: 300)
    
    GEMMConfig() 
        : m(0), n(0), k(0), 
          block_size(32), 
          dsp_array_dim(16), 
          clock_freq_mhz(300) {}
  };

  // Execute GEMM: C = alpha * A * B + beta * C
  // Returns cycle count
  int64_t compute(
      const GEMMConfig& config,
      const std::vector<std::complex<double>>& A,
      const std::vector<std::complex<double>>& B,
      std::vector<std::complex<double>>& C,
      std::complex<double> alpha = {1.0, 0.0},
      std::complex<double> beta = {0.0, 0.0}) const;

  // Estimate cycle count without executing computation
  int64_t estimate_cycles(const GEMMConfig& config) const;

  // Resource utilization estimate
  struct ResourceEstimate {
    int dsp_blocks;     // DSP48E2 blocks
    int bram_18k;       // 18Kb BRAM blocks
    int uram;           // UltraRAM blocks
    int lut;            // LUTs
    int ff;             // Flip-flops
    
    ResourceEstimate() 
        : dsp_blocks(0), bram_18k(0), uram(0), lut(0), ff(0) {}
  };
  ResourceEstimate estimate_resources(const GEMMConfig& config) const;

 private:
  // Blocked GEMM kernel implementation
  void blocked_gemm_kernel(
      int m, int n, int k, int block_size,
      const std::complex<double>* A,
      const std::complex<double>* B,
      std::complex<double>* C,
      std::complex<double> alpha,
      std::complex<double> beta) const;

  // Cycle computation model for Traditional FPGA
  int64_t compute_cycles(
      int m, int n, int k,
      int block_size,
      int dsp_array_dim) const;
  
  // Resource estimation helpers
  int estimate_dsp_blocks(int dsp_array_dim) const;
  int estimate_bram_blocks(int m, int n, int k, int block_size) const;
  int estimate_uram_blocks(int m, int n, int k) const;
  int estimate_luts(int dsp_array_dim) const;
  int estimate_ffs(int dsp_array_dim) const;
};

}  // namespace qebs
