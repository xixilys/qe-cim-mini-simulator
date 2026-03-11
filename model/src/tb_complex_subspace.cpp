#include <systemc.h>

#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <vector>

#include "cim_macro.h"

struct ComplexMatrix {
    int rows;
    int cols;
    std::vector<double> real;
    std::vector<double> imag;

    ComplexMatrix(int r = 0, int c = 0) : rows(r), cols(c), real(r * c, 0.0), imag(r * c, 0.0) {}

    inline int idx(int r, int c) const { return r * cols + c; }
};

struct ErrorStats {
    double rms_abs;
    double rel_frob;
    double max_abs;
};

struct Aggregate {
    double sum_hx_rel = 0.0;
    double sum_sx_rel = 0.0;
    double sum_hsub_rel = 0.0;
    double sum_ssub_rel = 0.0;
    double sum_hsub_herm = 0.0;
    double sum_ssub_herm = 0.0;
    double max_hsub_rel = 0.0;
    double max_ssub_rel = 0.0;
    int raw_chol_ok = 0;
    int sym_chol_ok = 0;
    int trials = 0;
};

enum class ComplexSchedule {
    FourMul,
    ThreeMul,
};

static double frob_norm(const ComplexMatrix& a) {
    double acc = 0.0;
    for (size_t i = 0; i < a.real.size(); i++) {
        acc += a.real[i] * a.real[i] + a.imag[i] * a.imag[i];
    }
    return std::sqrt(acc);
}

static ErrorStats compare_complex(const ComplexMatrix& ref, const ComplexMatrix& test) {
    ErrorStats s{};
    double sq = 0.0;
    double max_abs = 0.0;
    for (size_t i = 0; i < ref.real.size(); i++) {
        double dr = test.real[i] - ref.real[i];
        double di = test.imag[i] - ref.imag[i];
        double ab = std::sqrt(dr * dr + di * di);
        sq += ab * ab;
        max_abs = std::max(max_abs, ab);
    }
    double ref_norm = std::max(1e-30, frob_norm(ref));
    s.rms_abs = std::sqrt(sq / std::max<size_t>(1, ref.real.size()));
    s.rel_frob = std::sqrt(sq) / ref_norm;
    s.max_abs = max_abs;
    return s;
}

static ComplexMatrix hermitianize(const ComplexMatrix& a) {
    ComplexMatrix out = a;
    for (int i = 0; i < a.rows; i++) {
        out.imag[out.idx(i, i)] = 0.0;
        for (int j = i + 1; j < a.cols; j++) {
            int ij = a.idx(i, j);
            int ji = a.idx(j, i);
            double rr = 0.5 * (a.real[ij] + a.real[ji]);
            double ii = 0.5 * (a.imag[ij] - a.imag[ji]);
            out.real[ij] = rr;
            out.real[ji] = rr;
            out.imag[ij] = ii;
            out.imag[ji] = -ii;
        }
    }
    return out;
}

static double hermitian_defect(const ComplexMatrix& a) {
    double num = 0.0;
    double den = std::max(1e-30, frob_norm(a));
    for (int i = 0; i < a.rows; i++) {
        for (int j = 0; j < a.cols; j++) {
            int ij = a.idx(i, j);
            int ji = a.idx(j, i);
            double dr = a.real[ij] - a.real[ji];
            double di = a.imag[ij] + a.imag[ji];
            num += dr * dr + di * di;
        }
    }
    return std::sqrt(num) / den;
}

static ComplexMatrix conj_transpose(const ComplexMatrix& a) {
    ComplexMatrix out(a.cols, a.rows);
    for (int i = 0; i < a.rows; i++) {
        for (int j = 0; j < a.cols; j++) {
            int src = a.idx(i, j);
            int dst = out.idx(j, i);
            out.real[dst] = a.real[src];
            out.imag[dst] = -a.imag[src];
        }
    }
    return out;
}

static ComplexMatrix complex_gemm_ref(const ComplexMatrix& a, const ComplexMatrix& b) {
    ComplexMatrix c(a.rows, b.cols);
    for (int i = 0; i < a.rows; i++) {
        for (int j = 0; j < b.cols; j++) {
            double rr = 0.0;
            double ii = 0.0;
            for (int k = 0; k < a.cols; k++) {
                int ak = a.idx(i, k);
                int bk = b.idx(k, j);
                double ar = a.real[ak];
                double ai = a.imag[ak];
                double br = b.real[bk];
                double bi = b.imag[bk];
                rr += ar * br - ai * bi;
                ii += ar * bi + ai * br;
            }
            c.real[c.idx(i, j)] = rr;
            c.imag[c.idx(i, j)] = ii;
        }
    }
    return c;
}

static ComplexMatrix random_dense(int rows, int cols, std::mt19937& gen, double scale) {
    std::uniform_real_distribution<double> dist(-scale, scale);
    ComplexMatrix a(rows, cols);
    for (int i = 0; i < rows * cols; i++) {
        a.real[i] = dist(gen);
        a.imag[i] = dist(gen);
    }
    return a;
}

static ComplexMatrix random_hermitian(int n, std::mt19937& gen) {
    std::uniform_real_distribution<double> dist(-0.35, 0.35);
    ComplexMatrix h(n, n);
    for (int i = 0; i < n; i++) {
        h.real[h.idx(i, i)] = 0.8 + dist(gen);
        h.imag[h.idx(i, i)] = 0.0;
        for (int j = i + 1; j < n; j++) {
            double rr = dist(gen);
            double ii = dist(gen);
            h.real[h.idx(i, j)] = rr;
            h.imag[h.idx(i, j)] = ii;
            h.real[h.idx(j, i)] = rr;
            h.imag[h.idx(j, i)] = -ii;
        }
    }
    return h;
}

static ComplexMatrix random_hpd(int n, std::mt19937& gen) {
    ComplexMatrix b = random_dense(n, n, gen, 0.2);
    ComplexMatrix bh = conj_transpose(b);
    ComplexMatrix s = complex_gemm_ref(bh, b);
    for (int i = 0; i < n; i++) {
        s.real[s.idx(i, i)] += 1.5;
        s.imag[s.idx(i, i)] = 0.0;
    }
    return s;
}

static std::complex<double> column_dot(const ComplexMatrix& x, int c0, int c1) {
    std::complex<double> acc(0.0, 0.0);
    for (int r = 0; r < x.rows; r++) {
        int i0 = x.idx(r, c0);
        int i1 = x.idx(r, c1);
        std::complex<double> v0(x.real[i0], -x.imag[i0]);
        std::complex<double> v1(x.real[i1], x.imag[i1]);
        acc += v0 * v1;
    }
    return acc;
}

static void normalize_columns(ComplexMatrix& x) {
    for (int c = 0; c < x.cols; c++) {
        for (int p = 0; p < c; p++) {
            std::complex<double> proj = column_dot(x, p, c);
            for (int r = 0; r < x.rows; r++) {
                int pc = x.idx(r, p);
                int cc = x.idx(r, c);
                std::complex<double> vp(x.real[pc], x.imag[pc]);
                std::complex<double> vc(x.real[cc], x.imag[cc]);
                vc -= vp * proj;
                x.real[cc] = vc.real();
                x.imag[cc] = vc.imag();
            }
        }
        double nrm = std::sqrt(std::max(1e-30, column_dot(x, c, c).real()));
        for (int r = 0; r < x.rows; r++) {
            int cc = x.idx(r, c);
            x.real[cc] /= nrm;
            x.imag[cc] /= nrm;
        }
    }
}

static bool cholesky_ok(const ComplexMatrix& a) {
    if (a.rows != a.cols) return false;
    int n = a.rows;
    std::vector<std::complex<double>> l(n * n, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < n; i++) {
        for (int j = 0; j <= i; j++) {
            std::complex<double> sum(a.real[a.idx(i, j)], a.imag[a.idx(i, j)]);
            for (int k = 0; k < j; k++) {
                sum -= l[i * n + k] * std::conj(l[j * n + k]);
            }
            if (i == j) {
                if (std::abs(sum.imag()) > 1e-8) return false;
                if (sum.real() <= 1e-10) return false;
                l[i * n + j] = std::complex<double>(std::sqrt(sum.real()), 0.0);
            } else {
                if (std::abs(l[j * n + j]) <= 1e-12) return false;
                l[i * n + j] = sum / l[j * n + j];
            }
        }
    }
    return true;
}

static const char* prec_name(int prec) {
    switch (prec) {
        case 0: return "BF16";
        case 1: return "FP64";
        case 2: return "FP32";
        case 3: return "INT8_EMU";
        default: return "UNKNOWN";
    }
}

static const char* sched_name(ComplexSchedule s) {
    return (s == ComplexSchedule::FourMul) ? "4M" : "3M";
}

static void issue_real_gemm(CIM_Macro& cim,
                            sc_signal<bool>& cmd_valid,
                            sc_signal<int>& cmd_type,
                            sc_signal<int>& precision_mode,
                            sc_signal<int>& rows_to_process,
                            sc_signal<int>& cols_to_process,
                            sc_signal<double>& sparsity_ratio,
                            sc_signal<bool>& busy_a,
                            sc_signal<bool>& busy_b,
                            sc_signal<bool>& result_valid,
                            const std::vector<double>& a,
                            const std::vector<double>& b,
                            std::vector<double>& c,
                            int m, int k, int n, int prec) {
    cim.weight_data = a.data();
    cim.weight_rows = m;
    cim.weight_cols = k;
    cim.input_data = b.data();
    cim.input_rows = k;
    cim.input_cols = n;
    cim.result_data = c.data();

    precision_mode.write(prec);
    rows_to_process.write(m);
    cols_to_process.write(k);
    sparsity_ratio.write(0.0);
    cmd_type.write(2);
    cmd_valid.write(true);
    sc_start(1, SC_NS);
    cmd_valid.write(false);

    while (busy_a.read() || busy_b.read()) sc_start(1, SC_NS);
    while (!result_valid.read()) sc_start(1, SC_NS);
    sc_start(1, SC_NS);
}

static ComplexMatrix complex_gemm_cim(CIM_Macro& cim,
                                      sc_signal<bool>& cmd_valid,
                                      sc_signal<int>& cmd_type,
                                      sc_signal<int>& precision_mode,
                                      sc_signal<int>& rows_to_process,
                                      sc_signal<int>& cols_to_process,
                                      sc_signal<double>& sparsity_ratio,
                                      sc_signal<bool>& busy_a,
                                      sc_signal<bool>& busy_b,
                                      sc_signal<bool>& result_valid,
                                      const ComplexMatrix& a,
                                      const ComplexMatrix& b,
                                      int prec,
                                      ComplexSchedule schedule) {
    ComplexMatrix out(a.rows, b.cols);
    std::vector<double> t1(a.rows * b.cols, 0.0);
    std::vector<double> t2(a.rows * b.cols, 0.0);
    std::vector<double> t3(a.rows * b.cols, 0.0);

    issue_real_gemm(cim, cmd_valid, cmd_type, precision_mode, rows_to_process, cols_to_process, sparsity_ratio,
                    busy_a, busy_b, result_valid, a.real, b.real, t1, a.rows, a.cols, b.cols, prec);
    issue_real_gemm(cim, cmd_valid, cmd_type, precision_mode, rows_to_process, cols_to_process, sparsity_ratio,
                    busy_a, busy_b, result_valid, a.imag, b.imag, t2, a.rows, a.cols, b.cols, prec);

    if (schedule == ComplexSchedule::FourMul) {
        std::vector<double> t4(a.rows * b.cols, 0.0);
        issue_real_gemm(cim, cmd_valid, cmd_type, precision_mode, rows_to_process, cols_to_process, sparsity_ratio,
                        busy_a, busy_b, result_valid, a.real, b.imag, t3, a.rows, a.cols, b.cols, prec);
        issue_real_gemm(cim, cmd_valid, cmd_type, precision_mode, rows_to_process, cols_to_process, sparsity_ratio,
                        busy_a, busy_b, result_valid, a.imag, b.real, t4, a.rows, a.cols, b.cols, prec);
        for (int i = 0; i < a.rows * b.cols; i++) {
            out.real[i] = t1[i] - t2[i];
            out.imag[i] = t3[i] + t4[i];
        }
    } else {
        std::vector<double> as(a.rows * a.cols, 0.0);
        std::vector<double> bs(b.rows * b.cols, 0.0);
        for (int i = 0; i < a.rows * a.cols; i++) as[i] = a.real[i] + a.imag[i];
        for (int i = 0; i < b.rows * b.cols; i++) bs[i] = b.real[i] + b.imag[i];
        issue_real_gemm(cim, cmd_valid, cmd_type, precision_mode, rows_to_process, cols_to_process, sparsity_ratio,
                        busy_a, busy_b, result_valid, as, bs, t3, a.rows, a.cols, b.cols, prec);
        for (int i = 0; i < a.rows * b.cols; i++) {
            out.real[i] = t1[i] - t2[i];
            out.imag[i] = t3[i] - t1[i] - t2[i];
        }
    }
    return out;
}

static int env_int(const char* name, int defv) {
    const char* s = std::getenv(name);
    return s ? std::atoi(s) : defv;
}

static void print_summary(const std::string& label, const Aggregate& agg) {
    const double denom = std::max(1, agg.trials);
    std::cout << std::left << std::setw(12) << label
              << std::right << std::setw(12) << agg.sum_hx_rel / denom
              << std::setw(12) << agg.sum_sx_rel / denom
              << std::setw(14) << agg.sum_hsub_rel / denom
              << std::setw(14) << agg.sum_ssub_rel / denom
              << std::setw(12) << agg.sum_hsub_herm / denom
              << std::setw(12) << agg.sum_ssub_herm / denom
              << std::setw(12) << agg.max_hsub_rel
              << std::setw(12) << agg.max_ssub_rel
              << std::setw(9) << agg.raw_chol_ok << "/" << agg.trials
              << std::setw(9) << agg.sym_chol_ok << "/" << agg.trials
              << "\n";
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    sc_clock clk("clk", 1, SC_NS);
    sc_signal<bool> rst_n;
    sc_signal<bool> cmd_valid, busy_a, busy_b, result_valid;
    sc_signal<int> cmd_type, precision_mode, rows_to_process, cols_to_process;
    sc_signal<double> sparsity_ratio;

    CIM_Macro cim("CIM_ComplexEval");
    cim.clk(clk);
    cim.rst_n(rst_n);
    cim.cmd_valid(cmd_valid);
    cim.cmd_type(cmd_type);
    cim.precision_mode(precision_mode);
    cim.rows_to_process(rows_to_process);
    cim.cols_to_process(cols_to_process);
    cim.sparsity_ratio(sparsity_ratio);
    cim.busy_a(busy_a);
    cim.busy_b(busy_b);
    cim.result_valid(result_valid);

    rst_n.write(false);
    cmd_valid.write(false);
    sc_start(5, SC_NS);
    rst_n.write(true);
    sc_start(5, SC_NS);

    const int n = env_int("SUBSPACE_N", 24);
    const int m = env_int("SUBSPACE_M", 8);
    const int trials = env_int("SUBSPACE_TRIALS", 12);
    const int seed = env_int("SUBSPACE_SEED", 20260312);

    std::mt19937 gen(seed);
    std::vector<std::pair<int, ComplexSchedule>> modes = {
        {1, ComplexSchedule::FourMul},
        {2, ComplexSchedule::FourMul},
        {2, ComplexSchedule::ThreeMul},
        {0, ComplexSchedule::FourMul},
        {0, ComplexSchedule::ThreeMul},
        {3, ComplexSchedule::FourMul},
        {3, ComplexSchedule::ThreeMul},
    };
    std::vector<Aggregate> agg(modes.size());

    std::cout << "=== Complex Subspace Behavior Validation ===\n";
    std::cout << "N=" << n << " m=" << m << " trials=" << trials << " seed=" << seed << "\n";
    std::cout << "Metrics are relative Frobenius errors unless otherwise noted.\n\n";
    std::cout << std::left << std::setw(12) << "Mode"
              << std::right << std::setw(12) << "HX_rel"
              << std::setw(12) << "SX_rel"
              << std::setw(14) << "Hsub_rel"
              << std::setw(14) << "Ssub_rel"
              << std::setw(12) << "Hherm"
              << std::setw(12) << "Sherm"
              << std::setw(12) << "Hsub_max"
              << std::setw(12) << "Ssub_max"
              << std::setw(9) << "rawSPD"
              << std::setw(9) << "symSPD"
              << "\n";

    for (int t = 0; t < trials; t++) {
        ComplexMatrix h = random_hermitian(n, gen);
        ComplexMatrix s = random_hpd(n, gen);
        ComplexMatrix x = random_dense(n, m, gen, 0.25);
        normalize_columns(x);
        ComplexMatrix xh = conj_transpose(x);

        ComplexMatrix ref_hx = complex_gemm_ref(h, x);
        ComplexMatrix ref_sx = complex_gemm_ref(s, x);
        ComplexMatrix ref_hsub = complex_gemm_ref(xh, ref_hx);
        ComplexMatrix ref_ssub = complex_gemm_ref(xh, ref_sx);
        ref_hsub = hermitianize(ref_hsub);
        ref_ssub = hermitianize(ref_ssub);

        for (size_t mi = 0; mi < modes.size(); mi++) {
            int prec = modes[mi].first;
            ComplexSchedule sched = modes[mi].second;

            ComplexMatrix out_hx = complex_gemm_cim(cim, cmd_valid, cmd_type, precision_mode,
                                                    rows_to_process, cols_to_process, sparsity_ratio,
                                                    busy_a, busy_b, result_valid,
                                                    h, x, prec, sched);
            ComplexMatrix out_sx = complex_gemm_cim(cim, cmd_valid, cmd_type, precision_mode,
                                                    rows_to_process, cols_to_process, sparsity_ratio,
                                                    busy_a, busy_b, result_valid,
                                                    s, x, prec, sched);
            ComplexMatrix out_hsub = complex_gemm_cim(cim, cmd_valid, cmd_type, precision_mode,
                                                      rows_to_process, cols_to_process, sparsity_ratio,
                                                      busy_a, busy_b, result_valid,
                                                      xh, out_hx, prec, sched);
            ComplexMatrix out_ssub = complex_gemm_cim(cim, cmd_valid, cmd_type, precision_mode,
                                                      rows_to_process, cols_to_process, sparsity_ratio,
                                                      busy_a, busy_b, result_valid,
                                                      xh, out_sx, prec, sched);

            ErrorStats hx_err = compare_complex(ref_hx, out_hx);
            ErrorStats sx_err = compare_complex(ref_sx, out_sx);
            ErrorStats hsub_err = compare_complex(ref_hsub, out_hsub);
            ErrorStats ssub_err = compare_complex(ref_ssub, out_ssub);

            Aggregate& a = agg[mi];
            a.sum_hx_rel += hx_err.rel_frob;
            a.sum_sx_rel += sx_err.rel_frob;
            a.sum_hsub_rel += hsub_err.rel_frob;
            a.sum_ssub_rel += ssub_err.rel_frob;
            a.sum_hsub_herm += hermitian_defect(out_hsub);
            a.sum_ssub_herm += hermitian_defect(out_ssub);
            a.max_hsub_rel = std::max(a.max_hsub_rel, hsub_err.rel_frob);
            a.max_ssub_rel = std::max(a.max_ssub_rel, ssub_err.rel_frob);
            a.raw_chol_ok += cholesky_ok(out_ssub) ? 1 : 0;
            a.sym_chol_ok += cholesky_ok(hermitianize(out_ssub)) ? 1 : 0;
            a.trials++;
        }
    }

    for (size_t mi = 0; mi < modes.size(); mi++) {
        std::string label = std::string(prec_name(modes[mi].first)) + "-" + sched_name(modes[mi].second);
        print_summary(label, agg[mi]);
    }

    return 0;
}
