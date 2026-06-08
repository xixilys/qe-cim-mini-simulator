#include <math.h>
#include <stdio.h>
extern "C" void qeic_real_hpsi_local_potential(const double *psi_re, const double *psi_im, const double *vloc, double *out_re, double *out_im, int ngrid);
int main() {
    const int ngrid = 96;
    const double kinetic_scale = -0.5;
    double psi_re[ngrid], psi_im[ngrid], vloc[ngrid], out_re[ngrid], out_im[ngrid], expected_re[ngrid], expected_im[ngrid];
    for (int g = 0; g < ngrid; ++g) {
        psi_re[g] = 0.0125 * (double)(g + 1) + 0.00025 * (double)(g & 7);
        psi_im[g] = -0.009 * (double)(g + 2) + 0.000125 * (double)((g + 3) & 5);
        vloc[g] = 0.2 + 0.00075 * (double)((g * 13) & 31);
        out_re[g] = 0.0;
        out_im[g] = 0.0;
    }
    for (int g = 0; g < ngrid; ++g) {
        int left = (g == 0) ? 0 : g - 1;
        int right = (g == ngrid - 1) ? ngrid - 1 : g + 1;
        double lap_re = psi_re[left] - 2.0 * psi_re[g] + psi_re[right];
        double lap_im = psi_im[left] - 2.0 * psi_im[g] + psi_im[right];
        expected_re[g] = kinetic_scale * lap_re + vloc[g] * psi_re[g];
        expected_im[g] = kinetic_scale * lap_im + vloc[g] * psi_im[g];
    }
    qeic_real_hpsi_local_potential(psi_re, psi_im, vloc, out_re, out_im, ngrid);
    for (int g = 0; g < ngrid; ++g) {
        if (fabs(out_re[g] - expected_re[g]) > 1.0e-8 || fabs(out_im[g] - expected_im[g]) > 1.0e-8) {
            printf("DSE_REAL_HLS_FAIL %d expected %.12f %.12f got %.12f %.12f\n", g, expected_re[g], expected_im[g], out_re[g], out_im[g]);
            return 1;
        }
    }
    printf("DSE_REAL_HLS_PASS qeic_real_hpsi_local_potential %d\n", ngrid);
    return 0;
}
