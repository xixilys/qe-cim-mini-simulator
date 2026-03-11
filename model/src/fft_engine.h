#ifndef FFT_ENGINE_H
#define FFT_ENGINE_H

#include <systemc.h>

SC_MODULE(FFT_Engine) {
    sc_in<bool> clk;
    sc_in<bool> rst_n;
    
    sc_in<bool> start;
    sc_in<int>  size; // N1*N2*N3
    
    sc_out<bool> busy;
    sc_out<bool> done;

    SC_HAS_PROCESS(FFT_Engine);
    
    void process();

    SC_CTOR(FFT_Engine) {
        SC_THREAD(process);
        sensitive << clk.pos();
        async_reset_signal_is(rst_n, false);
    }
};

#endif
