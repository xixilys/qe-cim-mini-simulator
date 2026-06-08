#include <math.h>
#include <stdio.h>
extern "C" void hls_hybrid_reduction_sidecar(const double *in, double *out, int n);
int main() {
    const int n = 16;
    double in[n];
    double out[n];
    for (int i = 0; i < n; ++i) { in[i] = (double)(i + 1); out[i] = 0.0; }
    hls_hybrid_reduction_sidecar(in, out, n);
    for (int i = 0; i < n; ++i) {
        if (!isfinite(out[i])) {
            printf("DSE_HLS_PROBE_FAIL %d\n", i);
            return 1;
        }
    }
    printf("DSE_HLS_PROBE_OK\n");
    return 0;
}
