#include "fft_engine.h"

void FFT_Engine::process() {
    busy.write(false);
    done.write(false);
    
    wait();

    while (true) {
        if (start.read()) {
            busy.write(true);
            int fft_size = size.read();
            
            // O(N log N) cycle model, scaled down
            int cycles = 100 + (int)(fft_size * log2(fft_size)) / 100;
            
            // Wait for completion
            wait(cycles, SC_NS);
            
            busy.write(false);
            done.write(true);
            wait(1, SC_NS);
            done.write(false);
        }
        wait();
    }
}
