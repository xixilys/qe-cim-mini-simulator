#include <fftw3.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double now_sec() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int cmp_double(const void* a, const void* b) {
    double da = *(const double*)a;
    double db = *(const double*)b;
    return (da > db) - (da < db);
}

int main(int argc, char** argv) {
    int nthreads = 1;
    if (argc > 1) {
        nthreads = atoi(argv[1]);
        if (nthreads < 1) nthreads = 1;
    }

    int sizes[] = {64, 96, 128};
    int warmup = 2;
    int repeat = 7;

    if (nthreads > 1) {
        if (!fftw_init_threads()) {
            fprintf(stderr, "fftw_init_threads failed\n");
            return 1;
        }
        fftw_plan_with_nthreads(nthreads);
    }

    for (int si = 0; si < 3; ++si) {
        int n = sizes[si];
        long long total = (long long)n * n * n;
        fftw_complex* in = (fftw_complex*)fftw_malloc(sizeof(fftw_complex) * total);
        fftw_complex* out = (fftw_complex*)fftw_malloc(sizeof(fftw_complex) * total);
        if (!in || !out) {
            fprintf(stderr, "alloc failed for n=%d\n", n);
            return 2;
        }

        for (long long i = 0; i < total; ++i) {
            in[i][0] = (double)(i % 17) * 0.1;
            in[i][1] = (double)(i % 13) * 0.1;
        }

        fftw_plan p = fftw_plan_dft_3d(n, n, n, in, out, FFTW_FORWARD, FFTW_MEASURE);
        if (!p) {
            fprintf(stderr, "plan failed for n=%d\n", n);
            return 3;
        }

        for (int i = 0; i < warmup; ++i) fftw_execute(p);

        double times[32];
        for (int i = 0; i < repeat; ++i) {
            double t0 = now_sec();
            fftw_execute(p);
            times[i] = now_sec() - t0;
        }
        qsort(times, repeat, sizeof(double), cmp_double);

        double med = times[repeat / 2];
        double points_per_sec = (double)total / med;
        printf(
            "FFTW3D n=%d threads=%d median_s=%.9f points_per_sec=%.3f\n",
            n, nthreads, med, points_per_sec
        );

        fftw_destroy_plan(p);
        fftw_free(in);
        fftw_free(out);
    }

    if (nthreads > 1) fftw_cleanup_threads();
    fftw_cleanup();
    return 0;
}

