// Generated non-claimable HLS stub for qeic_l4_fpga_candidate_ground_state_band_structure_fft_transpose_fpga_only_fpga_fft_transpose_engine_9bfbea2b1f
#include <stdint.h>

extern "C" void qeic_l4_fpga_candidate_ground_state_band_structure_fft_transpose_fpga_only_fpga__hls_stub(const double *in, double *out, int n) {
#pragma HLS INTERFACE m_axi port=in offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem1
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        out[i] = in[i];
    }
}
