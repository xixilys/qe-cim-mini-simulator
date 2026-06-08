#include <math.h>
extern "C" void qeic_real_streaming_reduction_accumulator(const double *real_in, const double *imag_in, double *real_out, double *imag_out, int n) {
#pragma HLS INTERFACE m_axi port=real_in depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=imag_in depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=real_out depth=1 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=imag_out depth=1 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=real_in bundle=control
#pragma HLS INTERFACE s_axilite port=imag_in bundle=control
#pragma HLS INTERFACE s_axilite port=real_out bundle=control
#pragma HLS INTERFACE s_axilite port=imag_out bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    double acc_re = 0.0;
    double acc_im = 0.0;
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        double wr = 1.0 + 0.0005 * (double)(i & 7);
        double wi = 0.00025 * (double)((i + 3) & 5);
        acc_re += real_in[i] * wr - imag_in[i] * wi;
        acc_im += real_in[i] * wi + imag_in[i] * wr;
    }
    real_out[0] = acc_re;
    imag_out[0] = acc_im;
}
