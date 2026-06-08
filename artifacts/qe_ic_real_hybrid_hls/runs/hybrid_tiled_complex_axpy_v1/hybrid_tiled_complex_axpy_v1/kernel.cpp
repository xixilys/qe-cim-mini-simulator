extern "C" void qeic_real_tiled_complex_axpy(const double *x_re, const double *x_im, const double *y_re, const double *y_im, double *out_re, double *out_im, int n) {
#pragma HLS INTERFACE m_axi port=x_re depth=64 offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=x_im depth=64 offset=slave bundle=gmem1
#pragma HLS INTERFACE m_axi port=y_re depth=64 offset=slave bundle=gmem2
#pragma HLS INTERFACE m_axi port=y_im depth=64 offset=slave bundle=gmem3
#pragma HLS INTERFACE m_axi port=out_re depth=64 offset=slave bundle=gmem4
#pragma HLS INTERFACE m_axi port=out_im depth=64 offset=slave bundle=gmem5
#pragma HLS INTERFACE s_axilite port=x_re bundle=control
#pragma HLS INTERFACE s_axilite port=x_im bundle=control
#pragma HLS INTERFACE s_axilite port=y_re bundle=control
#pragma HLS INTERFACE s_axilite port=y_im bundle=control
#pragma HLS INTERFACE s_axilite port=out_re bundle=control
#pragma HLS INTERFACE s_axilite port=out_im bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    const double alpha_re = 0.75;
    const double alpha_im = -0.125;
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        double xr = x_re[i];
        double xi = x_im[i];
        out_re[i] = y_re[i] + alpha_re * xr - alpha_im * xi;
        out_im[i] = y_im[i] + alpha_re * xi + alpha_im * xr;
    }
}
