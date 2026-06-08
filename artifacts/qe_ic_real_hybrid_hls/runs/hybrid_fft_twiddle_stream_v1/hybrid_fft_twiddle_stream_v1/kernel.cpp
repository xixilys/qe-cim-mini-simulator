#include <math.h>
extern "C" void qeic_real_fft_twiddle_stream(const double *in_re, const double *in_im, double *out_re, double *out_im, int n) {
#pragma HLS INTERFACE m_axi port=in_re depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=in_im depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=out_re depth=64 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=out_im depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=in_re bundle=control
#pragma HLS INTERFACE s_axilite port=in_im bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        int dst = (i * 17) & (n - 1);
        double angle = 0.02454369260617026 * (double)i;
        double c = cos(angle);
        double s = sin(angle);
        out_re[dst] = in_re[i] * c - in_im[i] * s;
        out_im[dst] = in_re[i] * s + in_im[i] * c;
    }
}
