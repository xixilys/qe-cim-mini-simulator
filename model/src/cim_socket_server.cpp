#include <arpa/inet.h>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>

#include <systemc.h>
#include "cim_macro.h"
#include "fft_engine.h"

struct FComplex { double r; double i; };

struct CimSockReq {
    uint32_t magic;
    uint32_t version;
    uint32_t op;      // 0:GEMM 1:FFT
    uint32_t fft_size;
    uint32_t op_tag;
    uint32_t transa;
    uint32_t transb;
    uint32_t m, n, k;
    uint32_t lda, ldb, ldc;
    uint32_t precision;
    uint32_t kahan;
    double alpha_r, alpha_i;
    double beta_r, beta_i;
    uint32_t a_count;
    uint32_t b_count;
    uint32_t c_count;
};

struct CimSockResp {
    uint32_t magic;
    uint32_t version;
    uint32_t status;
    uint32_t reserved;
    long long real_macs;
    long long skipped_macs;
    long long elements;
    double energy_pj;
    double latency_ns;
};

static constexpr uint32_t CIM_SOCK_MAGIC = 0x43494D32u;
static constexpr uint32_t CIM_SOCK_VERSION = 1u;

static int recv_all(int fd, void* buf, size_t len) {
    char* p = static_cast<char*>(buf);
    size_t off = 0;
    while (off < len) {
        ssize_t n = recv(fd, p + off, len - off, 0);
        if (n <= 0) return -1;
        off += static_cast<size_t>(n);
    }
    return 0;
}

static int send_all(int fd, const void* buf, size_t len) {
    const char* p = static_cast<const char*>(buf);
    size_t off = 0;
    while (off < len) {
        ssize_t n = send(fd, p + off, len - off, 0);
        if (n <= 0) return -1;
        off += static_cast<size_t>(n);
    }
    return 0;
}

static double trunc_prec(double v, uint32_t p) {
    if (p == 16) return bf16_truncate(v);
    if (p == 32) return static_cast<double>(static_cast<float>(v));
    return v;
}

static int req_prec_to_mode(uint32_t p) {
    if (p == 16) return 0;
    if (p == 32) return 2;
    return 1;
}

static int env_int(const char* name, int defv) {
    const char* s = std::getenv(name);
    return s ? std::atoi(s) : defv;
}

static double env_double(const char* name, double defv) {
    const char* s = std::getenv(name);
    return s ? std::atof(s) : defv;
}

static void get_sparse_policy(uint32_t op_tag, double* out_abs_thr, double* out_nnz_ratio_thr) {
    // default global thresholds
    double abs_thr = env_double("CIM_BLOCK_SPARSE_THR", 0.0);
    double nnz_thr = env_double("CIM_BLOCK_NNZ_RATIO_THR", 0.0);

    // tag-specific override (if set)
    if (op_tag == 1) { // exx
        abs_thr = env_double("CIM_BLOCK_SPARSE_THR_EXX", abs_thr);
        nnz_thr = env_double("CIM_BLOCK_NNZ_RATIO_THR_EXX", nnz_thr);
    } else if (op_tag == 2) { // vuspsi
        abs_thr = env_double("CIM_BLOCK_SPARSE_THR_VUSPSI", abs_thr);
        nnz_thr = env_double("CIM_BLOCK_NNZ_RATIO_THR_VUSPSI", nnz_thr);
    } else if (op_tag == 3) { // subspace
        abs_thr = env_double("CIM_BLOCK_SPARSE_THR_SUBSPACE", abs_thr);
        nnz_thr = env_double("CIM_BLOCK_NNZ_RATIO_THR_SUBSPACE", nnz_thr);
    } else if (op_tag == 4) { // calbec
        abs_thr = env_double("CIM_BLOCK_SPARSE_THR_CALBEC", abs_thr);
        nnz_thr = env_double("CIM_BLOCK_NNZ_RATIO_THR_CALBEC", nnz_thr);
    }
    *out_abs_thr = abs_thr;
    *out_nnz_ratio_thr = nnz_thr;
}

static bool sparse_use_b_side(uint32_t op_tag) {
    // vuspsi-like kernels are typically sparse on B-side in current QE traces
    return op_tag == 2;
}

static void issue_cim_real_gemm(CIM_Macro& cim,
                                sc_signal<bool>& cim_cmd_valid,
                                sc_signal<int>& cim_cmd_type,
                                sc_signal<int>& cim_precision_mode,
                                sc_signal<int>& cim_rows,
                                sc_signal<int>& cim_cols,
                                sc_signal<double>& cim_sparsity,
                                sc_signal<bool>& cim_busy_a,
                                sc_signal<bool>& cim_busy_b,
                                sc_signal<bool>& cim_result_valid,
                                const std::vector<double>& A,
                                const std::vector<double>& B,
                                std::vector<double>& C,
                                int M, int K, int N,
                                int prec_mode) {
    cim.weight_data = A.data();
    cim.weight_rows = M;
    cim.weight_cols = K;
    cim.input_data = B.data();
    cim.input_rows = K;
    cim.input_cols = N;
    cim.result_data = C.data();

    cim_precision_mode.write(prec_mode);
    cim_rows.write(M);
    cim_cols.write(K);
    cim_sparsity.write(0.0);
    cim_cmd_type.write(2);
    cim_cmd_valid.write(true);
    sc_start(1, SC_NS);
    cim_cmd_valid.write(false);
    while (cim_busy_a.read() || cim_busy_b.read()) sc_start(1, SC_NS);
    while (!cim_result_valid.read()) sc_start(1, SC_NS);
    sc_start(1, SC_NS);
}

static bool block_is_sparse(const std::vector<double>& A, int A_rows, int A_cols, double thr) {
    double maxabs = 0.0;
    for (int i = 0; i < A_rows * A_cols; i++) {
        double v = std::abs(A[i]);
        if (v > maxabs) maxabs = v;
    }
    return maxabs <= thr;
}

static bool block_is_sparse_structured(const std::vector<double>& A, int A_rows, int A_cols,
                                       double abs_thr, double nnz_ratio_thr) {
    const bool enable_ratio_skip = env_int("CIM_ENABLE_RATIO_SKIP", 0) == 1;

    if (abs_thr <= 0.0) {
        // Do not allow ratio-only hard skipping: it can drop high-magnitude sparse tiles.
        return false;
    }

    int nnz = 0;
    double maxabs = 0.0;
    int total = A_rows * A_cols;
    for (int i = 0; i < total; i++) {
        double v = std::abs(A[i]);
        if (v > maxabs) maxabs = v;
        if (v > abs_thr) nnz++;
    }
    if (maxabs <= abs_thr) return true;

    if (!enable_ratio_skip) return false;
    if (nnz_ratio_thr <= 0.0) return false;

    const double ratio_mag_factor = env_double("CIM_BLOCK_RATIO_MAG_FACTOR", 4.0);
    if (maxabs > abs_thr * std::max(1.0, ratio_mag_factor)) {
        return false;
    }

    double ratio = (total > 0) ? (double)nnz / (double)total : 0.0;
    return ratio <= nnz_ratio_thr;
}

static long long real_gemm_tiled_sparse(CIM_Macro& cim,
                                   sc_signal<bool>& cim_cmd_valid,
                                   sc_signal<int>& cim_cmd_type,
                                   sc_signal<int>& cim_precision_mode,
                                   sc_signal<int>& cim_rows,
                                   sc_signal<int>& cim_cols,
                                   sc_signal<double>& cim_sparsity,
                                   sc_signal<bool>& cim_busy_a,
                                   sc_signal<bool>& cim_busy_b,
                                   sc_signal<bool>& cim_result_valid,
                                    const std::vector<double>& A,  // [M x K]
                                    const std::vector<double>& B,  // [K x N]
                                    std::vector<double>& Out,       // [M x N], accumulate +=
                                    int M, int K, int N,
                                    uint32_t op_tag,
                                    int req_prec_bits,
                                    int prec_mode,
                                    double sparse_thr,
                                    double sparse_nnz_ratio,
                                    long long* out_skipped_macs) {
    const int sram_bits = env_int("CIM_SRAM_BITS", 4 * 1024 * 1024);
    const int block_m = std::max(1, env_int("CIM_BLOCK_M", 16));
    const int block_k = std::max(1, env_int("CIM_BLOCK_K", 16));
    const int max_elems = std::max(1, sram_bits / std::max(1, req_prec_bits));
    int tile_n = (max_elems - block_m * block_k) / std::max(1, block_k + block_m);
    if (tile_n < 1) tile_n = 1;

    struct ActiveABlock {
        int k0;
        int curK;
        std::vector<double> Ablk;
    };

    long long macs = 0;
    long long skipped_macs = 0;
    const bool use_b_sparse = sparse_use_b_side(op_tag);
    for (int i0 = 0; i0 < M; i0 += block_m) {
        int curM = std::min(block_m, M - i0);
        std::vector<ActiveABlock> active_blocks;

        for (int k0 = 0; k0 < K; k0 += block_k) {
            int curK = std::min(block_k, K - k0);

            std::vector<double> Ablk(curM * curK);
            for (int i = 0; i < curM; i++) {
                for (int k2 = 0; k2 < curK; k2++) {
                    Ablk[i * curK + k2] = A[(i0 + i) * K + (k0 + k2)];
                }
            }

            if (!use_b_sparse &&
                block_is_sparse_structured(Ablk, curM, curK, sparse_thr, sparse_nnz_ratio)) {
                skipped_macs += (long long)curM * curK * N;
                continue; // hard skip sparse tile at tiling stage
            }

            ActiveABlock blk;
            blk.k0 = k0;
            blk.curK = curK;
            blk.Ablk.swap(Ablk);
            active_blocks.push_back(std::move(blk));
        }

        if (active_blocks.empty()) continue;

        for (int j0 = 0; j0 < N; j0 += tile_n) {
            int curN = std::min(tile_n, N - j0);
            for (const auto& blk : active_blocks) {
                int k0 = blk.k0;
                int curK = blk.curK;
                const std::vector<double>& Ablk = blk.Ablk;

                std::vector<double> Bblk(curK * curN);
                for (int k2 = 0; k2 < curK; k2++) {
                    for (int j = 0; j < curN; j++) {
                        Bblk[k2 * curN + j] = B[(k0 + k2) * N + (j0 + j)];
                    }
                }

                if (use_b_sparse &&
                    block_is_sparse_structured(Bblk, curK, curN, sparse_thr, sparse_nnz_ratio)) {
                    skipped_macs += (long long)curM * curK * curN;
                    continue;
                }

                std::vector<double> Cblk(curM * curN, 0.0);
                issue_cim_real_gemm(cim, cim_cmd_valid, cim_cmd_type, cim_precision_mode,
                                    cim_rows, cim_cols, cim_sparsity,
                                    cim_busy_a, cim_busy_b, cim_result_valid,
                                    Ablk, Bblk, Cblk, curM, curK, curN, prec_mode);
                macs += (long long)curM * curK * curN;

                for (int i = 0; i < curM; i++) {
                    for (int j = 0; j < curN; j++) {
                        Out[(i0 + i) * N + (j0 + j)] += Cblk[i * curN + j];
                    }
                }
            }
        }
    }
    if (out_skipped_macs) *out_skipped_macs = skipped_macs;
    return macs;
}

static void run_gemm_systemc(const CimSockReq& req,
                             CIM_Macro& cim,
                             sc_signal<bool>& cim_cmd_valid,
                             sc_signal<int>& cim_cmd_type,
                             sc_signal<int>& cim_precision_mode,
                             sc_signal<int>& cim_rows,
                             sc_signal<int>& cim_cols,
                             sc_signal<double>& cim_sparsity,
                             sc_signal<bool>& cim_busy_a,
                             sc_signal<bool>& cim_busy_b,
                             sc_signal<bool>& cim_result_valid,
                             bool sparse_enabled,
                             const FComplex* a, const FComplex* b, FComplex* c,
                             long long* out_real_macs) {
    char ta = static_cast<char>(req.transa);
    char tb = static_cast<char>(req.transb);
    bool trans_a = (ta == 'T' || ta == 't' || ta == 'C' || ta == 'c');
    bool conj_a = (ta == 'C' || ta == 'c');
    bool trans_b = (tb == 'T' || tb == 't' || tb == 'C' || tb == 'c');
    bool conj_b = (tb == 'C' || tb == 'c');

    int M = (int)req.m;
    int N = (int)req.n;
    int K = (int)req.k;
    int prec_mode = req_prec_to_mode(req.precision);
    double sparse_thr = 0.0, sparse_nnz_ratio = 0.0;
    if (sparse_enabled) {
        get_sparse_policy(req.op_tag, &sparse_thr, &sparse_nnz_ratio);

        if (req.op_tag != 2) {
            // Keep ratio-skip strictly scoped to vuspsi-like path for stability.
            sparse_nnz_ratio = 0.0;
        } else {
            const int ratio_min_n = env_int("CIM_RATIO_MIN_N", 17);
            const int ratio_min_k = env_int("CIM_RATIO_MIN_K", 16);
            if (N < ratio_min_n || K < ratio_min_k) {
                sparse_nnz_ratio = 0.0;
            }
        }
    }

    std::vector<double> ar(M * K), ai(M * K), br(K * N), bi(K * N);
    for (int i = 0; i < M; i++) {
        for (int l = 0; l < K; l++) {
            double xr, xi;
            if (trans_a) {
                xr = a[l + i * req.lda].r;
                xi = a[l + i * req.lda].i;
                if (conj_a) xi = -xi;
            } else {
                xr = a[i + l * req.lda].r;
                xi = a[i + l * req.lda].i;
            }
            ar[i * K + l] = trunc_prec(xr, req.precision);
            ai[i * K + l] = trunc_prec(xi, req.precision);
        }
    }
    for (int l = 0; l < K; l++) {
        for (int j = 0; j < N; j++) {
            double yr, yi;
            if (trans_b) {
                yr = b[j + l * req.ldb].r;
                yi = b[j + l * req.ldb].i;
                if (conj_b) yi = -yi;
            } else {
                yr = b[l + j * req.ldb].r;
                yi = b[l + j * req.ldb].i;
            }
            br[l * N + j] = trunc_prec(yr, req.precision);
            bi[l * N + j] = trunc_prec(yi, req.precision);
        }
    }

    std::vector<double> t1(M * N, 0.0), t2(M * N, 0.0), t3(M * N, 0.0), t4(M * N, 0.0);
    long long s1 = 0, s2 = 0, s3 = 0, s4 = 0;
    long long m1 = real_gemm_tiled_sparse(cim, cim_cmd_valid, cim_cmd_type, cim_precision_mode, cim_rows, cim_cols,
                           cim_sparsity, cim_busy_a, cim_busy_b, cim_result_valid,
                           ar, br, t1, M, K, N, req.op_tag,
                           (int)req.precision, prec_mode, sparse_thr, sparse_nnz_ratio, &s1);
    long long m2 = real_gemm_tiled_sparse(cim, cim_cmd_valid, cim_cmd_type, cim_precision_mode, cim_rows, cim_cols,
                           cim_sparsity, cim_busy_a, cim_busy_b, cim_result_valid,
                           ai, bi, t2, M, K, N, req.op_tag,
                           (int)req.precision, prec_mode, sparse_thr, sparse_nnz_ratio, &s2);
    long long m3 = real_gemm_tiled_sparse(cim, cim_cmd_valid, cim_cmd_type, cim_precision_mode, cim_rows, cim_cols,
                           cim_sparsity, cim_busy_a, cim_busy_b, cim_result_valid,
                           ar, bi, t3, M, K, N, req.op_tag,
                           (int)req.precision, prec_mode, sparse_thr, sparse_nnz_ratio, &s3);
    long long m4 = real_gemm_tiled_sparse(cim, cim_cmd_valid, cim_cmd_type, cim_precision_mode, cim_rows, cim_cols,
                           cim_sparsity, cim_busy_a, cim_busy_b, cim_result_valid,
                           ai, br, t4, M, K, N, req.op_tag,
                           (int)req.precision, prec_mode, sparse_thr, sparse_nnz_ratio, &s4);
    if (env_int("CIM_DEBUG_SKIP", 0) == 1) {
        std::cerr << "[SERVER][TILESKIP] op_tag=" << req.op_tag
                  << " m=" << M << " n=" << N << " k=" << K
                  << " skipped_real_macs=" << (s1 + s2 + s3 + s4)
                  << "\n";
    }
    if (out_real_macs) *out_real_macs = 4LL * (m1 + m2 + m3 + m4);

    for (int j = 0; j < N; j++) {
        for (int i = 0; i < M; i++) {
            int idx = i + j * req.ldc;
            int id2 = i * N + j;
            double sum_r = t1[id2] - t2[id2];
            double sum_i = t3[id2] + t4[id2];
            double out_r = req.alpha_r * sum_r - req.alpha_i * sum_i;
            double out_i = req.alpha_r * sum_i + req.alpha_i * sum_r;
            if (req.beta_r != 0.0 || req.beta_i != 0.0) {
                double old_r = c[idx].r;
                double old_i = c[idx].i;
                out_r += req.beta_r * old_r - req.beta_i * old_i;
                out_i += req.beta_r * old_i + req.beta_i * old_r;
            }
            c[idx].r = out_r;
            c[idx].i = out_i;
        }
    }
}

int sc_main(int argc, char** argv) {
    int port = 7788;
    if (argc >= 2) port = std::atoi(argv[1]);

    sc_clock clk("clk", 1, SC_NS);
    sc_signal<bool> rst_n;

    sc_signal<bool> cim_cmd_valid, cim_busy_a, cim_busy_b, cim_result_valid;
    sc_signal<int> cim_cmd_type, cim_precision_mode, cim_rows, cim_cols;
    sc_signal<double> cim_sparsity;

    sc_signal<bool> fft_start, fft_busy, fft_done;
    sc_signal<int> fft_size;

    CIM_Macro cim("CIM");
    cim.clk(clk); cim.rst_n(rst_n);
    cim.cmd_valid(cim_cmd_valid); cim.cmd_type(cim_cmd_type);
    cim.precision_mode(cim_precision_mode);
    cim.rows_to_process(cim_rows); cim.cols_to_process(cim_cols);
    cim.sparsity_ratio(cim_sparsity);
    cim.busy_a(cim_busy_a); cim.busy_b(cim_busy_b); cim.result_valid(cim_result_valid);

    FFT_Engine fft("FFT");
    fft.clk(clk); fft.rst_n(rst_n);
    fft.start(fft_start); fft.size(fft_size); fft.busy(fft_busy); fft.done(fft_done);

    rst_n.write(false);
    cim_cmd_valid.write(false);
    fft_start.write(false);
    sc_start(5, SC_NS);
    rst_n.write(true);
    sc_start(5, SC_NS);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        std::cerr << "socket() failed\n";
        return 1;
    }
    int one = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        std::cerr << "bind() failed on port " << port << "\n";
        close(server_fd);
        return 1;
    }
    if (listen(server_fd, 16) != 0) {
        std::cerr << "listen() failed\n";
        close(server_fd);
        return 1;
    }

    std::cout << "CIM SystemC socket server listening on 0.0.0.0:" << port << "\n";
    const int sparse_disable_after_call = env_int("CIM_BLOCK_SPARSE_DISABLE_AFTER_CALL", 0);
    const double max_skip_ratio = env_double("CIM_MAX_SKIP_RATIO", 0.0);
    const bool debug_skip = env_int("CIM_DEBUG_SKIP", 0) == 1;
    long long gemm_call_seq = 0;

    while (true) {
        int client_fd = accept(server_fd, nullptr, nullptr);
        if (client_fd < 0) continue;

        CimSockReq req{};
        if (recv_all(client_fd, &req, sizeof(req)) != 0 || req.magic != CIM_SOCK_MAGIC || req.version != CIM_SOCK_VERSION) {
            close(client_fd);
            continue;
        }

        CimSockResp resp{};
        resp.magic = CIM_SOCK_MAGIC;
        resp.version = CIM_SOCK_VERSION;
        resp.status = 0;

        if (req.op == 1) {
            sc_time t0 = sc_time_stamp();
            fft_size.write((int)req.fft_size);
            fft_start.write(true);
            sc_start(1, SC_NS);
            fft_start.write(false);
            while (!fft_done.read()) sc_start(1, SC_NS);
            sc_start(1, SC_NS);
            sc_time t1 = sc_time_stamp();

            resp.real_macs = 0;
            resp.skipped_macs = 0;
            resp.elements = (long long)req.fft_size;
            resp.energy_pj = (double)req.fft_size * std::log2(std::max(2u, req.fft_size)) * 6.0;
            resp.latency_ns = (t1 - t0).to_double();
            (void)send_all(client_fd, &resp, sizeof(resp));
            close(client_fd);
            continue;
        }

        size_t a_bytes = sizeof(FComplex) * req.a_count;
        size_t b_bytes = sizeof(FComplex) * req.b_count;
        size_t c_bytes = sizeof(FComplex) * req.c_count;
        std::vector<FComplex> a(req.a_count), b(req.b_count), c(req.c_count);

        if (recv_all(client_fd, a.data(), a_bytes) != 0 ||
            recv_all(client_fd, b.data(), b_bytes) != 0 ||
            recv_all(client_fd, c.data(), c_bytes) != 0) {
            close(client_fd);
            continue;
        }

        sc_time t0 = sc_time_stamp();
        long long real_macs = 0;
        gemm_call_seq++;
        bool sparse_enabled = (sparse_disable_after_call <= 0) ||
                              (gemm_call_seq <= (long long)sparse_disable_after_call);
        const int sparse_min_n = env_int("CIM_SPARSE_MIN_N", 8);
        if ((int)req.n < sparse_min_n) sparse_enabled = false;
        std::vector<FComplex> c_orig;
        if (max_skip_ratio > 0.0 && sparse_enabled) c_orig = c;

        run_gemm_systemc(req,
                         cim,
                         cim_cmd_valid,
                         cim_cmd_type,
                         cim_precision_mode,
                         cim_rows,
                         cim_cols,
                         cim_sparsity,
                         cim_busy_a,
                         cim_busy_b,
                         cim_result_valid,
                         sparse_enabled,
                         a.data(), b.data(), c.data(),
                         &real_macs);

        bool forced_dense_rerun = false;
        {
            long long theo = 8LL * (long long)req.m * req.n * req.k;
            double skip_ratio = (theo > 0) ? (double)(theo - std::min(theo, real_macs)) / (double)theo : 0.0;
            if (max_skip_ratio > 0.0 && sparse_enabled && skip_ratio > max_skip_ratio) {
                forced_dense_rerun = true;
                c = c_orig;
                run_gemm_systemc(req,
                                 cim,
                                 cim_cmd_valid,
                                 cim_cmd_type,
                                 cim_precision_mode,
                                 cim_rows,
                                 cim_cols,
                                 cim_sparsity,
                                 cim_busy_a,
                                 cim_busy_b,
                                 cim_result_valid,
                                 false,
                                 a.data(), b.data(), c.data(),
                                 &real_macs);
            }
            if (debug_skip) {
                std::cerr << "[SERVER][SKIP] call=" << gemm_call_seq
                          << " op_tag=" << req.op_tag
                          << " sparse=" << (sparse_enabled ? 1 : 0)
                          << " forced_dense=" << (forced_dense_rerun ? 1 : 0)
                          << " real_macs=" << real_macs
                          << " theo_macs=" << theo
                          << " skip_ratio=" << skip_ratio
                          << " m=" << req.m << " n=" << req.n << " k=" << req.k
                          << "\n";
            }
        }
        sc_time t1 = sc_time_stamp();

        // Extra FFT model invocation per request to emulate pipeline control overhead
        fft_size.write(std::max(64, (int)(req.m * req.n)));
        fft_start.write(true);
        sc_time t_fft0 = sc_time_stamp();
        sc_start(1, SC_NS);
        fft_start.write(false);
        while (!fft_done.read()) sc_start(1, SC_NS);
        sc_start(1, SC_NS);
        sc_time t2 = sc_time_stamp();

        resp.real_macs = real_macs;
        {
            long long theo = 8LL * (long long)req.m * req.n * req.k;
            resp.skipped_macs = (theo > real_macs) ? (theo - real_macs) : 0;
        }
        resp.elements = (long long)req.m * req.n;
        resp.energy_pj = real_macs * 1.0 + (double)req.m * req.k * req.precision * 0.5;
        resp.latency_ns = (t1 - t0).to_double() + (t2 - t_fft0).to_double();

        if (send_all(client_fd, &resp, sizeof(resp)) == 0) {
            (void)send_all(client_fd, c.data(), c_bytes);
        }
        close(client_fd);
    }

    close(server_fd);
    return 0;
}
