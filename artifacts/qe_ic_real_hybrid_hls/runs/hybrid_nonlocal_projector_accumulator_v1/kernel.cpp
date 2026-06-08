extern "C" void qeic_real_nonlocal_projector_accumulator(const double *beta_re, const double *beta_im, const double *psi_re, const double *psi_im, double *proj_re, double *proj_im, int ngrid, int nbands, int nproj) {
#pragma HLS INTERFACE m_axi port=beta_re depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=beta_im depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=psi_re depth=64 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=psi_im depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE m_axi port=proj_re depth=16 offset=slave bundle=gmem4
#pragma HLS INTERFACE m_axi port=proj_im depth=16 offset=slave bundle=gmem5
#pragma HLS INTERFACE s_axilite port=beta_re bundle=control
#pragma HLS INTERFACE s_axilite port=beta_im bundle=control
#pragma HLS INTERFACE s_axilite port=psi_re bundle=control
#pragma HLS INTERFACE s_axilite port=psi_im bundle=control
#pragma HLS INTERFACE s_axilite port=proj_re bundle=control
#pragma HLS INTERFACE s_axilite port=proj_im bundle=control
#pragma HLS INTERFACE s_axilite port=ngrid bundle=control
#pragma HLS INTERFACE s_axilite port=nbands bundle=control
#pragma HLS INTERFACE s_axilite port=nproj bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int p = 0; p < nproj; ++p) {
        for (int b = 0; b < nbands; ++b) {
            double acc_re = 0.0;
            double acc_im = 0.0;
            for (int g = 0; g < ngrid; ++g) {
#pragma HLS PIPELINE II=1
                int pg = p * ngrid + g;
                int bg = b * ngrid + g;
                double pr = psi_re[bg];
                double pi = psi_im[bg];
                acc_re += beta_re[pg] * pr + beta_im[pg] * pi;
                acc_im += beta_re[pg] * pi - beta_im[pg] * pr;
            }
            int idx = p * nbands + b;
            proj_re[idx] = acc_re;
            proj_im[idx] = acc_im;
        }
    }
}
