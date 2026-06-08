#include <stdint.h>
extern "C" void hls_hybrid_dma_or_memory_staging_sidecar(const double *in, double *out, int n) {
#pragma HLS INTERFACE m_axi port=in offset=slave bundle=gmem0
#pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem1
#pragma HLS INTERFACE s_axilite port=in bundle=control
#pragma HLS INTERFACE s_axilite port=out bundle=control
#pragma HLS INTERFACE s_axilite port=n bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    for (int i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        out[i] = in[i] * 1.003000;
    }
}
