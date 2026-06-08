extern "C" void qeic_real_sum_band_density_accumulator(const double *psi_re, const double *psi_im, const double *weights, double *rho_out, int ngrid, int nbands) {
#pragma HLS INTERFACE m_axi port=psi_re depth=128 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=psi_im depth=128 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=weights depth=4 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=rho_out depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE s_axilite port=psi_re bundle=control
#pragma HLS INTERFACE s_axilite port=psi_im bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=rho_out bundle=control
#pragma HLS INTERFACE s_axilite port=ngrid bundle=control
#pragma HLS INTERFACE s_axilite port=nbands bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int g = 0; g < ngrid; ++g) {
#pragma HLS PIPELINE II=1
        double acc = 0.0;
        for (int b = 0; b < nbands; ++b) {
            int idx = b * ngrid + g;
            double re = psi_re[idx];
            double im = psi_im[idx];
            acc += weights[b] * (re * re + im * im);
        }
        rho_out[g] = acc;
    }
}
