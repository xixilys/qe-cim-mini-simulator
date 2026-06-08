#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_streaming_reduction_accumulator(const double *real_in, const double *imag_in, double *real_out, double *imag_out, int n);
int main() {
    const int n = 64;
    double real_in[n], imag_in[n], real_out[1], imag_out[1];
    double expected_re = 0.0, expected_im = 0.0;
    for (int i = 0; i < n; ++i) {
        real_in[i] = 0.125 * (double)(i + 1);
        imag_in[i] = -0.0625 * (double)((i % 11) + 1);
        double wr = 1.0 + 0.0005 * (double)(i & 7);
        double wi = 0.00025 * (double)((i + 3) & 5);
        expected_re += real_in[i] * wr - imag_in[i] * wi;
        expected_im += real_in[i] * wi + imag_in[i] * wr;
    }
    qeic_real_streaming_reduction_accumulator(real_in, imag_in, real_out, imag_out, n);
    if (fabs(real_out[0] - expected_re) > 1.0e-8 || fabs(imag_out[0] - expected_im) > 1.0e-8) {
        printf("DSE_REAL_HLS_FAIL expected %.12f %.12f got %.12f %.12f\n", expected_re, expected_im, real_out[0], imag_out[0]);
        return 1;
    }
    printf("DSE_REAL_HLS_PASS qeic_real_streaming_reduction_accumulator %.12f %.12f\n", real_out[0], imag_out[0]);
    return 0;
}
