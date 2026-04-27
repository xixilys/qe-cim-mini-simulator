#include <Accelerate/Accelerate.h>
#include <fftw3.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int cmp_double(const void* a, const void* b) {
    double da = *(const double*)a;
    double db = *(const double*)b;
    return (da > db) - (da < db);
}

static double median_time(double* arr, int n) {
    qsort(arr, n, sizeof(double), cmp_double);
    return arr[n / 2];
}

static unsigned long long rng_state = 88172645463325252ull;
static double rnd_uniform(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return ((double)(rng_state & 0xFFFFFFFFull) / 4294967296.0) - 0.5;
}

static void fill_colmajor(double* a, int rows, int cols, double scale) {
    int i, j;
    for (j = 0; j < cols; ++j) {
        for (i = 0; i < rows; ++i) {
            a[i + (size_t)j * rows] = rnd_uniform() * scale;
        }
    }
}

static void bench_gemm(int m, int k, int n) {
    const int warmup = 2;
    const int repeat = 7;
    char trans = 'N';
    double alpha = 1.0, beta = 0.0;
    int lda = m, ldb = k, ldc = m;

    double* a = (double*)malloc(sizeof(double) * (size_t)m * k);
    double* b = (double*)malloc(sizeof(double) * (size_t)k * n);
    double* c = (double*)malloc(sizeof(double) * (size_t)m * n);
    if (!a || !b || !c) {
        fprintf(stderr, "alloc failed in GEMM\n");
        exit(1);
    }

    fill_colmajor(a, m, k, 1.0);
    fill_colmajor(b, k, n, 1.0);

    int t;
    for (t = 0; t < warmup; ++t) {
        dgemm_(&trans, &trans, &m, &n, &k, &alpha, a, &lda, b, &ldb, &beta, c, &ldc);
    }

    double ts[16];
    for (t = 0; t < repeat; ++t) {
        double t0 = now_sec();
        dgemm_(&trans, &trans, &m, &n, &k, &alpha, a, &lda, b, &ldb, &beta, c, &ldc);
        ts[t] = now_sec() - t0;
    }
    double med = median_time(ts, repeat);
    double gflops = 2.0 * (double)m * k * n / med / 1e9;
    printf("QE_GEMM shape=%dx%dx%d median_s=%.9f gflops=%.6f\n", m, k, n, med, gflops);

    free(a);
    free(b);
    free(c);
}

static void bench_fft(int n, int nthreads) {
    const int warmup = 2;
    const int repeat = 7;

    long long total = (long long)n * n * n;
    fftw_complex* in = (fftw_complex*)fftw_malloc(sizeof(fftw_complex) * total);
    fftw_complex* out = (fftw_complex*)fftw_malloc(sizeof(fftw_complex) * total);
    if (!in || !out) {
        fprintf(stderr, "alloc failed in FFT\n");
        exit(1);
    }

    long long i;
    for (i = 0; i < total; ++i) {
        in[i][0] = rnd_uniform();
        in[i][1] = rnd_uniform();
    }

    fftw_plan p = fftw_plan_dft_3d(n, n, n, in, out, FFTW_FORWARD, FFTW_MEASURE);
    if (!p) {
        fprintf(stderr, "fftw plan failed\n");
        exit(1);
    }

    int t;
    for (t = 0; t < warmup; ++t) fftw_execute(p);
    double ts[16];
    for (t = 0; t < repeat; ++t) {
        double t0 = now_sec();
        fftw_execute(p);
        ts[t] = now_sec() - t0;
    }
    double med = median_time(ts, repeat);
    double points_per_sec = (double)total / med;
    printf(
        "QE_FFT size=%d^3 threads=%d median_s=%.9f points_per_sec=%.6f\n",
        n, nthreads, med, points_per_sec
    );

    fftw_destroy_plan(p);
    fftw_free(in);
    fftw_free(out);
}

static void make_spd_from_b(int n, double* b, double* s) {
    char transa = 'T', transb = 'N';
    double alpha = 1.0, beta = 0.0;
    int lda = n, ldb = n, ldc = n;
    dgemm_(&transa, &transb, &n, &n, &n, &alpha, b, &lda, b, &ldb, &beta, s, &ldc);
    int i;
    for (i = 0; i < n; ++i) s[i + (size_t)i * n] += 1e-2;
}

static void make_sym_h(int n, double* h) {
    int i, j;
    for (j = 0; j < n; ++j) {
        for (i = j; i < n; ++i) {
            double v = rnd_uniform();
            h[i + (size_t)j * n] = v;
            h[j + (size_t)i * n] = v;
        }
    }
}

static void bench_diag(int n) {
    const int warmup = 1;
    const int repeat = 5;

    __CLPK_integer itype = 1;
    __CLPK_integer nn = n, lda = n, ldb = n, info = 0;
    char jobz = 'V', uplo = 'U';

    double* h0 = (double*)malloc(sizeof(double) * (size_t)n * n);
    double* s0 = (double*)malloc(sizeof(double) * (size_t)n * n);
    double* h = (double*)malloc(sizeof(double) * (size_t)n * n);
    double* s = (double*)malloc(sizeof(double) * (size_t)n * n);
    double* b = (double*)malloc(sizeof(double) * (size_t)n * n);
    double* w = (double*)malloc(sizeof(double) * (size_t)n);
    if (!h0 || !s0 || !h || !s || !b || !w) {
        fprintf(stderr, "alloc failed in DIAG\n");
        exit(1);
    }

    fill_colmajor(b, n, n, 1.0 / sqrt((double)n));
    make_spd_from_b(n, b, s0);
    make_sym_h(n, h0);
    memcpy(h, h0, sizeof(double) * (size_t)n * n);
    memcpy(s, s0, sizeof(double) * (size_t)n * n);

    __CLPK_integer lwork = -1, liwork = -1;
    double wkopt;
    __CLPK_integer iwkopt;
    dsygvd_(
        &itype, &jobz, &uplo, &nn, h, &lda, s, &ldb, w, &wkopt, &lwork, &iwkopt, &liwork, &info
    );
    if (info != 0) {
        fprintf(stderr, "dsygvd workspace query failed info=%d\n", (int)info);
        exit(1);
    }
    lwork = (__CLPK_integer)wkopt;
    liwork = iwkopt;
    double* work = (double*)malloc(sizeof(double) * (size_t)lwork);
    __CLPK_integer* iwork = (__CLPK_integer*)malloc(sizeof(__CLPK_integer) * (size_t)liwork);
    if (!work || !iwork) {
        fprintf(stderr, "alloc failed work arrays in DIAG\n");
        exit(1);
    }

    int t;
    for (t = 0; t < warmup; ++t) {
        memcpy(h, h0, sizeof(double) * (size_t)n * n);
        memcpy(s, s0, sizeof(double) * (size_t)n * n);
        dsygvd_(
            &itype, &jobz, &uplo, &nn, h, &lda, s, &ldb, w, work, &lwork, iwork, &liwork, &info
        );
        if (info != 0) {
            fprintf(stderr, "dsygvd warmup failed info=%d\n", (int)info);
            exit(1);
        }
    }

    double ts[16];
    for (t = 0; t < repeat; ++t) {
        memcpy(h, h0, sizeof(double) * (size_t)n * n);
        memcpy(s, s0, sizeof(double) * (size_t)n * n);
        double t0 = now_sec();
        dsygvd_(
            &itype, &jobz, &uplo, &nn, h, &lda, s, &ldb, w, work, &lwork, iwork, &liwork, &info
        );
        ts[t] = now_sec() - t0;
        if (info != 0) {
            fprintf(stderr, "dsygvd run failed info=%d\n", (int)info);
            exit(1);
        }
    }
    double med = median_time(ts, repeat);
    printf("QE_DIAG size=%d median_s=%.9f\n", n, med);

    free(h0);
    free(s0);
    free(h);
    free(s);
    free(b);
    free(w);
    free(work);
    free(iwork);
}

int main(int argc, char** argv) {
    int nthreads = 1;
    if (argc > 1) {
        nthreads = atoi(argv[1]);
        if (nthreads < 1) nthreads = 1;
    }

    if (nthreads > 1) {
        if (!fftw_init_threads()) {
            fprintf(stderr, "fftw_init_threads failed\n");
            return 1;
        }
        fftw_plan_with_nthreads(nthreads);
    }

    printf("QE_BENCH threads=%d\n", nthreads);
    bench_gemm(3072, 256, 64);
    bench_gemm(2048, 512, 256);
    bench_fft(64, nthreads);
    bench_fft(96, nthreads);
    bench_fft(128, nthreads);
    bench_diag(256);
    bench_diag(512);
    bench_diag(768);

    if (nthreads > 1) fftw_cleanup_threads();
    fftw_cleanup();
    return 0;
}

