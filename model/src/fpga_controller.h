#ifndef FPGA_CONTROLLER_H
#define FPGA_CONTROLLER_H

#include <systemc.h>
#include <vector>

// FPGA controller to manage CIM tasks, Data movement and Sparsity
SC_MODULE(FPGA_Controller) {
    sc_in<bool> clk;
    sc_in<bool> rst_n;
    
    // Command Interface from TestBench (CPU)
    sc_in<bool>  start_cmd;
    sc_in<int>   op_type;        // 1: rmexx (PingPong), 2: calbec (AbsWS), 3: hpsi/ps (Transp), 4: hc (WS), 5: dsp_deeq
    sc_in<int>   matrix_m;       
    sc_in<int>   matrix_n;       
    sc_in<int>   matrix_k;       
    sc_in<int>   precision;      // 0: BF16, 1: FP64
    
    // Status to TestBench
    sc_out<bool> ready;
    sc_out<bool> done;
    sc_out<int>  total_cycles_used;
    sc_out<int>  total_skipped_cycles;
    sc_out<int>  dsp_cycles_used;      // cycles consumed by DSP engine
    
    // Interface to CIM Macro
    sc_out<bool>   cim_cmd_valid;
    sc_out<int>    cim_cmd_type;
    sc_out<int>    cim_precision_mode;
    sc_out<int>    cim_rows;
    sc_out<int>    cim_cols;
    sc_out<double> cim_sparsity;
    
    sc_in<bool>    cim_busy_a;
    sc_in<bool>    cim_busy_b;
    sc_in<bool>    cim_result_valid;

    SC_HAS_PROCESS(FPGA_Controller);
    void control_loop();

    int cycles_elapsed;
    int skipped_cycles_acc;
    int dsp_cycles_acc;

    // ---- DSP Engine data interface (set by testbench) ----
    const double* dsp_deeq_data;    // Deeq matrix [nkb x nkb], 75% sparse
    const double* dsp_becp_data;    // becp (calbec result) [nkb x nbnd]
    double*       dsp_ps_data;      // output ps = Deeq * becp [nkb x nbnd]
    int dsp_nkb;
    int dsp_nbnd;

    SC_CTOR(FPGA_Controller) {
        SC_THREAD(control_loop);
        sensitive << clk.pos();
        async_reset_signal_is(rst_n, false);
        
        cycles_elapsed = 0;
        skipped_cycles_acc = 0;
        dsp_cycles_acc = 0;
        dsp_deeq_data = nullptr;
        dsp_becp_data = nullptr;
        dsp_ps_data = nullptr;
        dsp_nkb = 0;
        dsp_nbnd = 0;
    }
    
private:
    double evaluate_sparsity(int m, int k, int prec);
};

#endif
