#include "fpga_controller.h"

double FPGA_Controller::evaluate_sparsity(int m, int k, int prec) {
    if (prec == 0) return 0.75; // 75% sparse with 1e-4 cutoff
    return 0.10; // 10% sparse with 1e-8 cutoff
}

void FPGA_Controller::control_loop() {
    ready.write(false);
    done.write(false);
    cim_cmd_valid.write(false);
    cim_cmd_type.write(0);
    cim_precision_mode.write(0);
    cim_rows.write(0);
    cim_cols.write(0);
    cim_sparsity.write(0.0);
    
    total_cycles_used.write(0);
    total_skipped_cycles.write(0);
    dsp_cycles_used.write(0);

    wait();

    while (true) {
        ready.write(true);
        if (start_cmd.read()) {
            ready.write(false);
            
            int op = op_type.read();
            int m = matrix_m.read();
            int n = matrix_n.read();
            int k = matrix_k.read();
            int prec = precision.read();
            
            int cycles = 0;
            int skipped = 0;

            if (op == 5) {
                // ========== DSP Engine: ps = Deeq * becp ==========
                // Deeq is nkb x nkb (75% sparse, block-diagonal)
                // becp is nkb x nbnd
                // ps   is nkb x nbnd
                // NOT mapped to CIM — computed digitally with zero-skipping
                int dsp_cyc = 0;
                
                if (dsp_deeq_data != nullptr && dsp_becp_data != nullptr && dsp_ps_data != nullptr
                    && dsp_nkb > 0 && dsp_nbnd > 0) {
                    
                    int nk = dsp_nkb;
                    int nb = dsp_nbnd;
                    
                    for (int i = 0; i < nk; i++) {
                        for (int j = 0; j < nb; j++) {
                            double acc = 0.0;
                            for (int kk = 0; kk < nk; kk++) {
                                double dval = dsp_deeq_data[i * nk + kk];
                                if (dval != 0.0) {
                                    // Non-zero: 1 DSP cycle per MAC
                                    acc += dval * dsp_becp_data[kk * nb + j];
                                    dsp_cyc++;
                                }
                                // Zero elements: skipped (zero-skipping), 0 cycles
                            }
                            dsp_ps_data[i * nb + j] = acc;
                        }
                    }
                }
                
                // Model DSP latency: 1 ns per non-zero MAC
                if (dsp_cyc < 1) dsp_cyc = 1;
                wait(dsp_cyc, SC_NS);
                
                int theoretical = dsp_nkb * dsp_nkb * dsp_nbnd; // without skipping
                skipped = theoretical - dsp_cyc;
                if (skipped < 0) skipped = 0;
                
                dsp_cycles_acc += dsp_cyc;
                skipped_cycles_acc += skipped;
                cycles_elapsed += dsp_cyc;
                
                total_cycles_used.write(cycles_elapsed);
                total_skipped_cycles.write(skipped_cycles_acc);
                dsp_cycles_used.write(dsp_cycles_acc);
                
                done.write(true);
                wait(1, SC_NS);
                done.write(false);

            } else {
                // ========== CIM Macro path (unchanged logic) ==========
                double sparsity = evaluate_sparsity(m, k, prec);
                int cycles_start = (int)sc_time_stamp().to_double();
                
                // Logic based on Mapping Schemes
                if (op == 1) { // Ping-Pong WS (rmexx)
                    // Write Bank A
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(0); // Write A
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    // Wait for Write A
                    while (cim_busy_a.read()) wait();
                    
                    // Write B while Computing A
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(1); // Write B
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    // Overlap: Compute A
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(2); // Compute A
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    // Wait for all to finish
                    while (cim_busy_a.read() || cim_busy_b.read()) wait();
                    
                } else if (op == 2) { // Absolute WS (calbec)
                    // Write once
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(0); // Write A
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    while (cim_busy_a.read()) wait();
                    
                    // Stream compute
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(2); // Compute A
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    while (cim_busy_a.read()) wait();
                    
                } else if (op == 3) { // Transpose (hpsi / wavefunction rotation)
                    // Transpose mapping: small matrix as weight, large matrix streamed as input
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(0); // Write A
                    cim_precision_mode.write(prec);
                    cim_rows.write(k); // Small dimension
                    cim_cols.write(m);
                    cim_sparsity.write(0); // No sparsity for dense vectors
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    while (cim_busy_a.read()) wait();
                    
                    // Compute
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(2); // Compute A
                    cim_precision_mode.write(prec);
                    cim_rows.write(k);
                    cim_cols.write(m);
                    cim_sparsity.write(0);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    while (cim_busy_a.read()) wait();
                    
                } else if (op == 4) { // WS (hc)
                    // Simple stream to Bank A
                    cim_cmd_valid.write(true);
                    cim_cmd_type.write(2); // Compute A directly assuming weights are there
                    cim_precision_mode.write(prec);
                    cim_rows.write(m);
                    cim_cols.write(k);
                    cim_sparsity.write(sparsity);
                    wait(1, SC_NS);
                    cim_cmd_valid.write(false);
                    
                    while (cim_busy_a.read()) wait();
                }
                
                int cycles_end = (int)sc_time_stamp().to_double();
                cycles = cycles_end - cycles_start;
                
                // Calculate theoretical non-sparse cycles to find skipped
                int concurrent_elements = (prec == 0) ? 512 : 128;
                int theoretical_cycles = (op == 1 || op == 2) ? 
                    m * ((k + concurrent_elements - 1) / concurrent_elements) :
                    k * ((m + concurrent_elements - 1) / concurrent_elements);
                
                skipped = theoretical_cycles - (int)(theoretical_cycles * (1.0 - sparsity));
                if (skipped < 0) skipped = 0; // Prevent negative skip
                
                cycles_elapsed += cycles;
                skipped_cycles_acc += skipped;
                
                total_cycles_used.write(cycles_elapsed);
                total_skipped_cycles.write(skipped_cycles_acc);
                
                done.write(true);
                wait(1, SC_NS);
                done.write(false);
            }
        }
        wait();
    }
}
