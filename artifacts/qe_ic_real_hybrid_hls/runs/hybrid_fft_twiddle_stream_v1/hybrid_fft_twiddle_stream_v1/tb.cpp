#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_fft_twiddle_stream(const double *in_re, const double *in_im, double *out_re, double *out_im, int n);
int main() {
    const int n = 64;
    double in_re[n], in_im[n], out_re[n], out_im[n], expected_re[n], expected_im[n];
    for (int i = 0; i < n; ++i) {
        in_re[i] = 0.02 * (double)(i + 1);
        in_im[i] = -0.01 * (double)(i + 2);
        out_re[i] = 0.0;
        out_im[i] = 0.0;
        expected_re[i] = 0.0;
        expected_im[i] = 0.0;
    }
    for (int i = 0; i < n; ++i) {
        int dst = (i * 17) & (n - 1);
        double angle = 0.02454369260617026 * (double)i;
        double c = cos(angle);
        double s = sin(angle);
        expected_re[dst] = in_re[i] * c - in_im[i] * s;
        expected_im[dst] = in_re[i] * s + in_im[i] * c;
    }
    qeic_real_fft_twiddle_stream(in_re, in_im, out_re, out_im, n);
    for (int i = 0; i < n; ++i) {
        if (fabs(out_re[i] - expected_re[i]) > 1.0e-8 || fabs(out_im[i] - expected_im[i]) > 1.0e-8) {
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\n", i, expected_re[i], expected_im[i], out_re[i], out_im[i]);
            return 1;
        }
    }
    printf("DSE_REAL_HLS_PASS qeic_real_fft_twiddle_stream %d\n", n);
    return 0;
}
