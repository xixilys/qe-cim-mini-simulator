#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_sum_band_density_accumulator(const double *psi_re, const double *psi_im, const double *weights, double *rho_out, int ngrid, int nbands);
int main() {
    const int ngrid = 32;
    const int nbands = 4;
    const int n = 128;
    double psi_re[n], psi_im[n], weights[nbands], rho_out[ngrid], expected[ngrid];
    for (int b = 0; b < nbands; ++b) {
        weights[b] = 0.5 + 0.125 * (double)(b + 1);
    }
    for (int g = 0; g < ngrid; ++g) {
        expected[g] = 0.0;
        rho_out[g] = 0.0;
    }
    for (int b = 0; b < nbands; ++b) {
        for (int g = 0; g < ngrid; ++g) {
            int idx = b * ngrid + g;
            psi_re[idx] = 0.01 * (double)(idx + 1) + 0.001 * (double)(g & 3);
            psi_im[idx] = -0.0075 * (double)(idx + 2) + 0.0005 * (double)(b & 1);
            expected[g] += weights[b] * (psi_re[idx] * psi_re[idx] + psi_im[idx] * psi_im[idx]);
        }
    }
    qeic_real_sum_band_density_accumulator(psi_re, psi_im, weights, rho_out, ngrid, nbands);
    for (int g = 0; g < ngrid; ++g) {
        if (fabs(rho_out[g] - expected[g]) > 1.0e-8) {
            printf("DSE_REAL_HLS_FAIL %d expected %.12f got %.12f\n", g, expected[g], rho_out[g]);
            return 1;
        }
    }
    printf("DSE_REAL_HLS_PASS qeic_real_sum_band_density_accumulator %d %d\n", ngrid, nbands);
    return 0;
}
