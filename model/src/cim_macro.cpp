#include "cim_macro.h"
#include <cstring>  // for memcpy in bf16_truncate
#include <cmath>

void CIM_Macro::compute_thread() {
    // Reset state
    busy_a.write(false);
    busy_b.write(false);
    result_valid.write(false);
    is_busy_a = false;
    is_busy_b = false;

    wait(); // Wait for first clock

    while (true) {
        if (cmd_valid.read()) {
            int cmd = cmd_type.read();
            int prec = precision_mode.read();
            int rows = rows_to_process.read();
            int cols = cols_to_process.read();
            double sparsity = sparsity_ratio.read();
            
            int cycles = 0;
            
            // Model calculation logic based on architecture
            if (cmd == 0 || cmd == 1) { // Write Bank A or B
                // Write latency model: assume 1 cycle per 128 elements for write
                int write_bandwidth = 128;
                cycles = (rows * cols + write_bandwidth - 1) / write_bandwidth;
                
                if (cmd == 0) {
                    is_busy_a = true;
                    busy_a.write(true);
                    wait(cycles, SC_NS); // Model latency
                    is_busy_a = false;
                    busy_a.write(false);
                } else {
                    is_busy_b = true;
                    busy_b.write(true);
                    wait(cycles, SC_NS);
                    is_busy_b = false;
                    busy_b.write(false);
                }
            } else if (cmd == 2 || cmd == 3) { // Compute A or B
                // 1 MB = 1024 rows * 8192 cols
                // Bank A/B = 512 rows each
                
                // Concurrency
                int concurrent_elements = (prec == 0) ? 512 : ((prec == 2) ? 256 : 128); // BF16/FP32/FP64
                
                // Effective rows after zero skipping
                int effective_rows = (int)(rows * (1.0 - sparsity));
                if (effective_rows < 1) effective_rows = 1; // At least one computation cycle
                
                // Cycles for MAC operations
                int num_batches = (cols + concurrent_elements - 1) / concurrent_elements;
                cycles = effective_rows * num_batches;
                
                // ========== ACTUAL NUMERICAL COMPUTATION ==========
                // Perform real matrix multiplication: result = weight * input
                // weight: [weight_rows x weight_cols], input: [input_rows x input_cols]
                // result: [weight_rows x input_cols]
                // weight_cols must == input_rows (inner dimension K)
                
                accumulated_noise = 0.0;
                
                if (weight_data != nullptr && input_data != nullptr && result_data != nullptr
                    && weight_rows > 0 && weight_cols > 0 && input_cols > 0) {
                    
                    int M = weight_rows;
                    int K = weight_cols;
                    int N = input_cols;
                    
                    for (int i = 0; i < M; i++) {
                        for (int j = 0; j < N; j++) {
                            double acc = 0.0;
                            for (int kk = 0; kk < K; kk++) {
                                double w = weight_data[i * K + kk];
                                double x = input_data[kk * N + j];
                                
                                if (prec == 0) {
                                    // BF16 mode: truncate both operands, accumulate with truncation
                                    w = bf16_truncate(w);
                                    x = bf16_truncate(x);
                                    acc += w * x;
                                    // Periodically truncate accumulator to simulate limited precision
                                    if ((kk & 0xF) == 0xF) {
                                        acc = bf16_truncate(acc);
                                    }
                                } else if (prec == 2) {
                                    // FP32 mode
                                    w = fp32_truncate(w);
                                    x = fp32_truncate(x);
                                    acc += w * x;
                                    if ((kk & 0xF) == 0xF) {
                                        acc = fp32_truncate(acc);
                                    }
                                } else {
                                    // FP64 mode: exact computation
                                    acc += w * x;
                                }
                            }
                            
                            if (prec == 0) {
                                acc = bf16_truncate(acc);
                            } else if (prec == 2) {
                                acc = fp32_truncate(acc);
                            }
                            
                            result_data[i * N + j] = acc;
                        }
                    }
                    
                    // Compute accumulated noise: sum of |result_bf16 - result_fp64|
                    // (only meaningful in BF16 mode; in FP64 noise = 0)
                    if (prec == 0 || prec == 2) {
                        // Re-compute FP64 reference inline and measure total error
                        double total_err = 0.0;
                        for (int i = 0; i < M; i++) {
                            for (int j = 0; j < N; j++) {
                                double exact = 0.0;
                                for (int kk = 0; kk < K; kk++) {
                                    exact += weight_data[i * K + kk] * input_data[kk * N + j];
                                }
                                double diff = result_data[i * N + j] - exact;
                                total_err += diff * diff;
                            }
                        }
                        accumulated_noise = std::sqrt(total_err / (M * N)); // RMS error
                    }
                }
                // ========== END NUMERICAL COMPUTATION ==========
                
                if (cmd == 2) {
                    is_busy_a = true;
                    busy_a.write(true);
                    wait(cycles, SC_NS);
                    is_busy_a = false;
                    busy_a.write(false);
                } else {
                    is_busy_b = true;
                    busy_b.write(true);
                    wait(cycles, SC_NS);
                    is_busy_b = false;
                    busy_b.write(false);
                }
                
                // Result out
                result_valid.write(true);
                wait(1, SC_NS);
                result_valid.write(false);
            }
        }
        wait();
    }
}
