#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_tiled_complex_axpy(const double *x_re, const double *x_im, const double *y_re, const double *y_im, double *out_re, double *out_im, int n);
int main() {
    const int n = 64;
    double x_re[n], x_im[n], y_re[n], y_im[n], out_re[n], out_im[n];
    const double alpha_re = 0.75;
    const double alpha_im = -0.125;
    for (int i = 0; i < n; ++i) {
        x_re[i] = 0.03125 * (double)(i + 2);
        x_im[i] = -0.015625 * (double)(i + 3);
        y_re[i] = 0.0078125 * (double)(i + 5);
        y_im[i] = -0.00390625 * (double)(i + 7);
        out_re[i] = 0.0;
        out_im[i] = 0.0;
    }
    qeic_real_tiled_complex_axpy(x_re, x_im, y_re, y_im, out_re, out_im, n);
    for (int i = 0; i < n; ++i) {
        double expected_re = y_re[i] + alpha_re * x_re[i] - alpha_im * x_im[i];
        double expected_im = y_im[i] + alpha_re * x_im[i] + alpha_im * x_re[i];
        if (fabs(out_re[i] - expected_re) > 1.0e-9 || fabs(out_im[i] - expected_im) > 1.0e-9) {
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\n", i, expected_re, expected_im, out_re[i], out_im[i]);
            return 1;
        }
    }
    printf("DSE_REAL_HLS_PASS qeic_real_tiled_complex_axpy %d\n", n);
    return 0;
}
