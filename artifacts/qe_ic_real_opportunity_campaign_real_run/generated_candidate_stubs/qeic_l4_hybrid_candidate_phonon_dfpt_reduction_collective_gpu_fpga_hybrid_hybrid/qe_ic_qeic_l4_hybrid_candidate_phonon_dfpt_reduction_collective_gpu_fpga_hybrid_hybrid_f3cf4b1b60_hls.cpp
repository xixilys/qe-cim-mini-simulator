// Generated non-claimable HLS stub for qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_dma_overlap_sidecar_9a9fa929fc
#include <stdint.h>

extern "C" void qeic_l4_hybrid_candidate_phonon_dfpt_reduction_collective_gpu_fpga_hybrid_hybrid_hls_stub(const double *in, double *out, int n) {
#pragma HLS INTERFACE m_axi port=in offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem1
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        out[i] = in[i];
    }
}
