#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_nonlocal_projector_accumulator(const double *beta_re, const double *beta_im, const double *psi_re, const double *psi_im, double *proj_re, double *proj_im, int ngrid, int nbands, int nproj);
int main() {
    const int ngrid = 16;
    const int nbands = 4;
    const int nproj = 4;
    const int beta_n = 64;
    const int psi_n = 64;
    const int out_n = 16;
    double beta_re[beta_n], beta_im[beta_n], psi_re[psi_n], psi_im[psi_n];
    double proj_re[out_n], proj_im[out_n], expected_re[out_n], expected_im[out_n];
    for (int p = 0; p < nproj; ++p) {
        for (int g = 0; g < ngrid; ++g) {
            int pg = p * ngrid + g;
            beta_re[pg] = 0.003 * (double)(pg + 1) + 0.00025 * (double)(p + 1);
            beta_im[pg] = -0.002 * (double)(pg + 2) + 0.000125 * (double)(g & 3);
        }
    }
    for (int b = 0; b < nbands; ++b) {
        for (int g = 0; g < ngrid; ++g) {
            int bg = b * ngrid + g;
            psi_re[bg] = 0.011 * (double)(bg + 1) + 0.0005 * (double)(b & 3);
            psi_im[bg] = -0.007 * (double)(bg + 3) + 0.00025 * (double)(g & 7);
        }
    }
    for (int p = 0; p < nproj; ++p) {
        for (int b = 0; b < nbands; ++b) {
            int idx = p * nbands + b;
            expected_re[idx] = 0.0;
            expected_im[idx] = 0.0;
            proj_re[idx] = 0.0;
            proj_im[idx] = 0.0;
            for (int g = 0; g < ngrid; ++g) {
                int pg = p * ngrid + g;
                int bg = b * ngrid + g;
                expected_re[idx] += beta_re[pg] * psi_re[bg] + beta_im[pg] * psi_im[bg];
                expected_im[idx] += beta_re[pg] * psi_im[bg] - beta_im[pg] * psi_re[bg];
            }
        }
    }
    qeic_real_nonlocal_projector_accumulator(beta_re, beta_im, psi_re, psi_im, proj_re, proj_im, ngrid, nbands, nproj);
    for (int idx = 0; idx < out_n; ++idx) {
        if (fabs(proj_re[idx] - expected_re[idx]) > 1.0e-8 || fabs(proj_im[idx] - expected_im[idx]) > 1.0e-8) {
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\n", idx, expected_re[idx], expected_im[idx], proj_re[idx], proj_im[idx]);
            return 1;
        }
    }
    printf("DSE_REAL_HLS_PASS qeic_real_nonlocal_projector_accumulator %d %d %d\n", ngrid, nbands, nproj);
    return 0;
}
