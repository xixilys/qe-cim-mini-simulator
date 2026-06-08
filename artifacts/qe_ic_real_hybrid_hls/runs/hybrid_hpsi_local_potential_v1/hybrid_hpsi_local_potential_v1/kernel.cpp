extern "C" void qeic_real_hpsi_local_potential(const double *psi_re, const double *psi_im, const double *vloc, double *out_re, double *out_im, int ngrid) {
#pragma HLS INTERFACE m_axi port=psi_re depth=96 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=psi_im depth=96 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=vloc depth=96 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=out_re depth=96 offset=slave bundle=gmem3
#pragma HLS INTERFACE m_axi port=out_im depth=96 offset=slave bundle=gmem4
#pragma HLS INTERFACE s_axilite port=psi_re bundle=control
#pragma HLS INTERFACE s_axilite port=psi_im bundle=control
#pragma HLS INTERFACE s_axilite port=vloc bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=ngrid bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    const double kinetic_scale = -0.5;
    for (int g = 0; g < ngrid; ++g) {
#pragma HLS PIPELINE II=1
        int left = (g == 0) ? 0 : g - 1;
        int right = (g == ngrid - 1) ? ngrid - 1 : g + 1;
        double lap_re = psi_re[left] - 2.0 * psi_re[g] + psi_re[right];
        double lap_im = psi_im[left] - 2.0 * psi_im[g] + psi_im[right];
        out_re[g] = kinetic_scale * lap_re + vloc[g] * psi_re[g];
        out_im[g] = kinetic_scale * lap_im + vloc[g] * psi_im[g];
    }
}
