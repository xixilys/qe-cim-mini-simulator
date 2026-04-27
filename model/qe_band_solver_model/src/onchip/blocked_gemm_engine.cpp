#include "blocked_gemm_engine.hpp"
#include "logging.hpp"
#include <algorithm>
#include <cmath>
#include <cstdlib>

namespace qebs {

BlockedGEMMEngine::BlockedGEMMEngine(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {
  log_line(this->name(), "BlockedGEMMEngine initialized");
}

int64_t BlockedGEMMEngine::compute(
    const GEMMConfig& config,
    const std::vector<std::complex<double>>& A,
    const std::vector<std::complex<double>>& B,
    std::vector<std::complex<double>>& C,
    std::complex<double> alpha,
    std::complex<double> beta) const {
  
  if (A.size() != static_cast<size_t>(config.m * config.k) ||
      B.size() != static_cast<size_t>(config.k * config.n) ||
      C.size() != static_cast<size_t>(config.m * config.n)) {
    log_line(name(), "ERROR: Matrix dimension mismatch in GEMM");
    return 0;
  }
  
  blocked_gemm_kernel(
      config.m, config.n, config.k, config.block_size,
      A.data(), B.data(), C.data(),
      alpha, beta);
  
  int64_t cycles = compute_cycles(
      config.m, config.n, config.k,
      config.block_size, config.dsp_array_dim);
  
  log_line(name(), "BlockedGEMM completed: m=" + std::to_string(config.m) +
                   ", n=" + std::to_string(config.n) +
                   ", k=" + std::to_string(config.k) +
                   ", cycles=" + std::to_string(cycles));
  
  return cycles;
}

int64_t BlockedGEMMEngine::estimate_cycles(const GEMMConfig& config) const {
  return compute_cycles(
      config.m, config.n, config.k,
      config.block_size, config.dsp_array_dim);
}

BlockedGEMMEngine::ResourceEstimate 
BlockedGEMMEngine::estimate_resources(const GEMMConfig& config) const {
  ResourceEstimate est;
  est.dsp_blocks = estimate_dsp_blocks(config.dsp_array_dim);
  est.bram_18k = estimate_bram_blocks(config.m, config.n, config.k, config.block_size);
  est.uram = estimate_uram_blocks(config.m, config.n, config.k);
  est.lut = estimate_luts(config.dsp_array_dim);
  est.ff = estimate_ffs(config.dsp_array_dim);
  return est;
}

void BlockedGEMMEngine::blocked_gemm_kernel(
    int m, int n, int k, int block_size,
    const std::complex<double>* A,
    const std::complex<double>* B,
    std::complex<double>* C,
    std::complex<double> alpha,
    std::complex<double> beta) const {
  
  for (int i = 0; i < m * n; ++i) {
    C[i] = beta * C[i];
  }
  
  for (int ii = 0; ii < m; ii += block_size) {
    for (int jj = 0; jj < n; jj += block_size) {
      for (int kk = 0; kk < k; kk += block_size) {
        
        int i_end = std::min(ii + block_size, m);
        int j_end = std::min(jj + block_size, n);
        int k_end = std::min(kk + block_size, k);
        
        for (int i = ii; i < i_end; ++i) {
          for (int j = jj; j < j_end; ++j) {
            std::complex<double> sum = {0.0, 0.0};
            for (int kk_inner = kk; kk_inner < k_end; ++kk_inner) {
              sum += A[i * k + kk_inner] * B[kk_inner * n + j];
            }
            C[i * n + j] += alpha * sum;
          }
        }
      }
    }
  }
}

int64_t BlockedGEMMEngine::compute_cycles(
    int m, int n, int k,
    int block_size,
    int dsp_array_dim) const {
  
  int64_t flops = 8LL * m * n * k;
  
  int dsp_count = dsp_array_dim * dsp_array_dim;
  int64_t compute_cycles = flops / (2 * dsp_count);
  
  int64_t memory_accesses = static_cast<int64_t>(m) * n + 
                            static_cast<int64_t>(m) * k + 
                            static_cast<int64_t>(k) * n;
  int64_t memory_cycles = memory_accesses / 3;
  
  int64_t total_cycles = std::max(compute_cycles, memory_cycles);
  
  total_cycles = static_cast<int64_t>(total_cycles * 1.1);
  
  return total_cycles;
}

int BlockedGEMMEngine::estimate_dsp_blocks(int dsp_array_dim) const {
  return dsp_array_dim * dsp_array_dim;
}

int BlockedGEMMEngine::estimate_bram_blocks(
    int m, int n, int k, int block_size) const {
  int buffer_size = 3 * block_size * block_size;
  int bram_per_buffer = (buffer_size * 16 + 18431) / 18432;
  return bram_per_buffer * 3;
}

int BlockedGEMMEngine::estimate_uram_blocks(int m, int n, int k) const {
  int64_t total_elements = static_cast<int64_t>(m) * n + 
                           static_cast<int64_t>(m) * k + 
                           static_cast<int64_t>(k) * n;
  int64_t total_bytes = total_elements * 16;
  
  if (total_bytes > 1024 * 1024) {
    int uram_count = static_cast<int>((total_bytes + 294911) / 294912);
    return uram_count;
  }
  return 0;
}

int BlockedGEMMEngine::estimate_luts(int dsp_array_dim) const {
  int base_lut = 5000;
  int per_dsp_lut = 50;
  return base_lut + per_dsp_lut * dsp_array_dim * dsp_array_dim;
}

int BlockedGEMMEngine::estimate_ffs(int dsp_array_dim) const {
  int base_ff = 8000;
  int per_dsp_ff = 80;
  return base_ff + per_dsp_ff * dsp_array_dim * dsp_array_dim;
}

}  // namespace qebs
