#ifndef CIM_MACRO_H
#define CIM_MACRO_H

#include <systemc.h>
#include <vector>
#include <cstdint>
#include <cstring>

// BF16 truncation: keep only top 8 bits of mantissa (drop 44 bits for FP64)
// Simulates the quantization noise of BF16 precision
inline double bf16_truncate(double val) {
    // Simulate BF16 by rounding to ~3 decimal digits of mantissa precision
    // BF16 has 8-bit mantissa -> ~2.4 decimal digits
    if (val == 0.0) return 0.0;
    float f = static_cast<float>(val);         // FP64 -> FP32 (drop 29 bits)
    // Further truncate to BF16: zero out lower 16 bits of FP32 mantissa
    uint32_t bits;
    memcpy(&bits, &f, sizeof(bits));
    bits &= 0xFFFF0000u;  // Keep sign(1) + exp(8) + mantissa_high(7) = BF16
    memcpy(&f, &bits, sizeof(f));
    return static_cast<double>(f);
}

inline double fp32_truncate(double val) {
    return static_cast<double>(static_cast<float>(val));
}

// CIM Macro Array Module with actual numerical computation
SC_MODULE(CIM_Macro) {
    // Inputs
    sc_in<bool> clk;
    sc_in<bool> rst_n;
    
    // Commands and data
    sc_in<bool>   cmd_valid;
    sc_in<int>    cmd_type;       // 0: write_a, 1: write_b, 2: compute_a, 3: compute_b
    sc_in<int>    precision_mode; // 0: BF16, 1: FP64, 2: FP32, 3: INT8_EMU
    sc_in<int>    rows_to_process;
    sc_in<int>    cols_to_process;
    sc_in<double> sparsity_ratio; // Emulate actual zero skipping
    
    // Status
    sc_out<bool>  busy_a;
    sc_out<bool>  busy_b;
    sc_out<bool>  result_valid;

    // SC_HAS_PROCESS
    void compute_thread();
    
    // Internal state
    bool is_busy_a;
    bool is_busy_b;

    // ---- Data interface (set by testbench before issuing compute) ----
    // Weight matrix (stored in SRAM bank): weight[rows][cols]
    const double* weight_data;   // pointer to weight matrix (row-major)
    int weight_rows;
    int weight_cols;

    // Input vector/matrix: input[cols][out_cols] or input[rows]
    const double* input_data;    // pointer to input matrix (row-major)
    int input_rows;              // == weight_cols (inner dimension)
    int input_cols;              // output columns (e.g., nbnd)

    // Output result buffer (allocated by testbench)
    double* result_data;         // pointer to output matrix (row-major)
    // result shape: weight_rows x input_cols

    // Accumulated numerical error for this compute
    double accumulated_noise;

    SC_CTOR(CIM_Macro) {
        SC_THREAD(compute_thread);
        sensitive << clk.pos();
        async_reset_signal_is(rst_n, false);
        
        is_busy_a = false;
        is_busy_b = false;
        weight_data = nullptr;
        input_data = nullptr;
        result_data = nullptr;
        weight_rows = 0;
        weight_cols = 0;
        input_rows = 0;
        input_cols = 0;
        accumulated_noise = 0.0;
    }
};

#endif
