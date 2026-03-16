#include <systemc.h>

#include <Accelerate/Accelerate.h>

#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

#include "iterative_subspace_engine.h"

using LapackInt = __CLPK_integer;
using LapackComplex = __CLPK_doublecomplex;

struct RegressionCase {
    std::string tag;
    int n = 0;
    int m = 0;
    std::vector<std::complex<double>> h;  // col-major
    std::vector<std::complex<double>> s;  // col-major
};

struct ReferenceResult {
    bool ok = false;
    std::vector<double> evals;
    std::vector<std::complex<double>> eigvecs;
};

struct ModeMetrics {
    bool ok = false;
    std::string status = "UNSET";
    int n = 0;
    int m = 0;
    int steps = 0;
    int mode = 0;
    double eig_max_rel = 0.0;
    double residual_max = 0.0;
    double s_orth_defect = 0.0;
    double hit_rate = 0.0;
    int cycles = 0;
    int row_hits = 0;
    int row_misses = 0;
    int residue_encodes = 0;
    int crt_reconstructs = 0;
    int hx_ops = 0;
    int sx_ops = 0;
    int qhqx_ops = 0;
    int ortho_ops = 0;
    int basis_update_ops = 0;
    int reduced_build_ops = 0;
    int reduced_cholesky_ops = 0;
    int reduced_standardize_ops = 0;
    int reduced_jacobi_ops = 0;
    int reduced_backtransform_ops = 0;
};

struct ModeSummary {
    int runs = 0;
    int ok_runs = 0;
    double eig_sum = 0.0;
    double eig_max = 0.0;
    double residual_sum = 0.0;
    double residual_max = 0.0;
    double sorth_sum = 0.0;
    double sorth_max = 0.0;
    double cycles_sum = 0.0;
    double hit_rate_sum = 0.0;
    double speedup_sum = 0.0;
    int speedup_count = 0;
};

static std::string env_string(const char* name, const std::string& defv) {
    const char* s = std::getenv(name);
    return s ? std::string(s) : defv;
}

static int env_int(const char* name, int defv) {
    const char* s = std::getenv(name);
    return s ? std::atoi(s) : defv;
}

static double env_double(const char* name, double defv) {
    const char* s = std::getenv(name);
    return s ? std::atof(s) : defv;
}

static std::vector<std::string> split_csv_list(const std::string& text) {
    std::vector<std::string> out;
    std::stringstream ss(text);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (!item.empty()) out.push_back(item);
    }
    return out;
}

static double sq_abs(const std::complex<double>& z) {
    return z.real() * z.real() + z.imag() * z.imag();
}

static double frob_norm(const std::vector<std::complex<double>>& a) {
    double acc = 0.0;
    for (const auto& z : a) acc += sq_abs(z);
    return std::sqrt(acc);
}

static std::vector<std::complex<double>> load_dump_csv(const std::string& path, int n) {
    std::vector<std::complex<double>> out(n * n, std::complex<double>(0.0, 0.0));
    std::ifstream fin(path);
    std::string line;
    bool first = true;
    while (std::getline(fin, line)) {
        if (line.empty()) continue;
        if (first) {
            first = false;
            if (line.rfind("row,col,real,imag", 0) == 0) continue;
        }
        std::stringstream ss(line);
        std::string token;
        std::vector<std::string> toks;
        while (std::getline(ss, token, ',')) toks.push_back(token);
        if (toks.size() != 4) continue;
        const int row = std::stoi(toks[0]) - 1;
        const int col = std::stoi(toks[1]) - 1;
        out[row + col * n] = std::complex<double>(std::stod(toks[2]), std::stod(toks[3]));
    }
    return out;
}

static std::vector<RegressionCase> collect_qe_cases(const std::vector<std::string>& dirs, int max_cases) {
    std::vector<RegressionCase> cases;
    const std::regex h_pat(R"((.+)_H_call(\d+)_n(\d+)_m(\d+)\.csv$)");

    for (const auto& dir : dirs) {
        const std::filesystem::path root(dir);
        if (!std::filesystem::exists(root) || !std::filesystem::is_directory(root)) continue;

        std::vector<std::filesystem::path> files;
        for (const auto& ent : std::filesystem::directory_iterator(root)) {
            if (ent.is_regular_file()) files.push_back(ent.path());
        }
        std::sort(files.begin(), files.end());

        for (const auto& path : files) {
            std::smatch match;
            const std::string name = path.filename().string();
            if (!std::regex_match(name, match, h_pat)) continue;

            const std::string prefix = match[1].str();
            const std::string call_id = match[2].str();
            const int n = std::stoi(match[3].str());
            const int m = std::stoi(match[4].str());
            const std::filesystem::path s_path = root / (prefix + "_S_call" + call_id + "_n" +
                                                         std::to_string(n) + "_m" + std::to_string(m) + ".csv");
            if (!std::filesystem::exists(s_path)) continue;

            RegressionCase item;
            item.tag = root.filename().string() + "/call" + call_id;
            item.n = n;
            item.m = m;
            item.h = load_dump_csv(path.string(), n);
            item.s = load_dump_csv(s_path.string(), n);
            cases.push_back(std::move(item));
            if (max_cases > 0 && static_cast<int>(cases.size()) >= max_cases) return cases;
        }
    }

    return cases;
}

static std::vector<std::complex<double>> random_dense(int rows, int cols, std::mt19937& gen, double scale) {
    std::uniform_real_distribution<double> dist(-scale, scale);
    std::vector<std::complex<double>> out(rows * cols, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < cols; col++) {
        for (int row = 0; row < rows; row++) out[row + col * rows] = std::complex<double>(dist(gen), dist(gen));
    }
    return out;
}

static std::vector<std::complex<double>> conj_transpose(const std::vector<std::complex<double>>& a, int rows, int cols) {
    std::vector<std::complex<double>> out(cols * rows, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < cols; col++) {
        for (int row = 0; row < rows; row++) out[col + row * cols] = std::conj(a[row + col * rows]);
    }
    return out;
}

static std::vector<std::complex<double>> matmul(const std::vector<std::complex<double>>& a,
                                                const std::vector<std::complex<double>>& b,
                                                int m, int k, int n) {
    std::vector<std::complex<double>> c(m * n, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < n; col++) {
        for (int kk = 0; kk < k; kk++) {
            const std::complex<double> bk = b[kk + col * k];
            for (int row = 0; row < m; row++) c[row + col * m] += a[row + kk * m] * bk;
        }
    }
    return c;
}

static std::vector<std::complex<double>> random_hermitian(int n, std::mt19937& gen) {
    std::uniform_real_distribution<double> dist(-0.3, 0.3);
    std::vector<std::complex<double>> h(n * n, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < n; i++) {
        h[i + i * n] = std::complex<double>(1.0 + dist(gen), 0.0);
        for (int j = i + 1; j < n; j++) {
            const std::complex<double> z(dist(gen), dist(gen));
            h[i + j * n] = z;
            h[j + i * n] = std::conj(z);
        }
    }
    return h;
}

static std::vector<std::complex<double>> random_hpd(int n, std::mt19937& gen) {
    const std::vector<std::complex<double>> b = random_dense(n, n, gen, 0.2);
    const std::vector<std::complex<double>> bh = conj_transpose(b, n, n);
    std::vector<std::complex<double>> s = matmul(bh, b, n, n, n);
    for (int i = 0; i < n; i++) s[i + i * n] += std::complex<double>(1.5, 0.0);
    return s;
}

static void hermitianize_col_major(std::vector<std::complex<double>>& a, int n) {
    for (int i = 0; i < n; i++) {
        a[i + i * n] = std::complex<double>(a[i + i * n].real(), 0.0);
        for (int j = i + 1; j < n; j++) {
            const std::complex<double> avg = 0.5 * (a[i + j * n] + std::conj(a[j + i * n]));
            a[i + j * n] = avg;
            a[j + i * n] = std::conj(avg);
        }
    }
}

static bool solve_generalized_reference(std::vector<std::complex<double>> a,
                                        std::vector<std::complex<double>> b,
                                        int n,
                                        std::vector<double>& evals,
                                        std::vector<std::complex<double>>& eigvecs) {
    hermitianize_col_major(a, n);
    hermitianize_col_major(b, n);

    LapackInt ln = n;
    LapackInt lda = n;
    LapackInt ldb = n;
    LapackInt itype = 1;
    LapackInt lwork = -1;
    LapackInt info = 0;
    char jobz = 'V';
    char uplo = 'U';
    evals.assign(n, 0.0);
    eigvecs = a;
    std::complex<double> work_query(0.0, 0.0);
    std::vector<double> rwork(std::max(1, 3 * n - 2), 0.0);

    zhegv_(&itype, &jobz, &uplo, &ln,
           reinterpret_cast<LapackComplex*>(eigvecs.data()), &lda,
           reinterpret_cast<LapackComplex*>(b.data()), &ldb,
           evals.data(), reinterpret_cast<LapackComplex*>(&work_query), &lwork, rwork.data(), &info);
    if (info != 0) return false;

    lwork = std::max<LapackInt>(1, static_cast<LapackInt>(std::llround(work_query.real())));
    std::vector<std::complex<double>> work(lwork);
    zhegv_(&itype, &jobz, &uplo, &ln,
           reinterpret_cast<LapackComplex*>(eigvecs.data()), &lda,
           reinterpret_cast<LapackComplex*>(b.data()), &ldb,
           evals.data(), reinterpret_cast<LapackComplex*>(work.data()), &lwork, rwork.data(), &info);
    return info == 0;
}

static std::complex<double> dot_with_metric(const std::vector<std::complex<double>>& s, int n,
                                            const std::vector<std::complex<double>>& v, int c0, int c1) {
    std::complex<double> acc(0.0, 0.0);
    for (int i = 0; i < n; i++) {
        std::complex<double> svi(0.0, 0.0);
        for (int j = 0; j < n; j++) svi += s[i + j * n] * v[j + c1 * n];
        acc += std::conj(v[i + c0 * n]) * svi;
    }
    return acc;
}

static double metric_orth_defect(const std::vector<std::complex<double>>& s, int n,
                                 const std::vector<std::complex<double>>& v, int m) {
    double num = 0.0;
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < m; j++) {
            std::complex<double> gij = dot_with_metric(s, n, v, i, j);
            if (i == j) gij -= std::complex<double>(1.0, 0.0);
            num += sq_abs(gij);
        }
    }
    return std::sqrt(num);
}

static double residual_norm(const std::vector<std::complex<double>>& h,
                            const std::vector<std::complex<double>>& s,
                            int n,
                            const std::vector<std::complex<double>>& v,
                            int col,
                            double eval,
                            double h_norm,
                            double s_norm) {
    double sq = 0.0;
    for (int i = 0; i < n; i++) {
        std::complex<double> hv(0.0, 0.0);
        std::complex<double> sv(0.0, 0.0);
        for (int j = 0; j < n; j++) {
            hv += h[i + j * n] * v[j + col * n];
            sv += s[i + j * n] * v[j + col * n];
        }
        sq += sq_abs(hv - eval * sv);
    }
    const double denom = std::max(1e-30, h_norm + std::abs(eval) * s_norm);
    return std::sqrt(sq) / denom;
}

static const char* solver_mode_name(int mode) {
    switch (mode) {
        case REDUCED_SOLVER_CHOLESKY_JACOBI:
            return "chol_jacobi";
        case REDUCED_SOLVER_BINV_JACOBI:
            return "binv_jacobi";
        case REDUCED_SOLVER_HYBRID:
            return "hybrid";
        default:
            return "unknown";
    }
}

static bool metrics_within_tolerance(const ModeMetrics& metrics, double eig_tol, double res_tol, double orth_tol) {
    if (!std::isfinite(metrics.eig_max_rel) || !std::isfinite(metrics.residual_max) || !std::isfinite(metrics.s_orth_defect)) {
        return false;
    }
    if (metrics.eig_max_rel > eig_tol) return false;
    if (metrics.residual_max > res_tol) return false;
    if (metrics.s_orth_defect > orth_tol) return false;
    return true;
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    const std::string default_dirs =
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_actual_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_actual_case16,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump";
    const std::vector<std::string> dirs = split_csv_list(env_string("ITER_REG_DIRS", default_dirs));
    const int max_cases = env_int("ITER_REG_MAX_CASES", 8);
    const int steps = std::max(1, env_int("ITER_REG_STEPS", env_int("ITER_STEPS", 6)));
    const bool use_history_p = env_int("ITER_REG_USE_HISTORY_P", env_int("ITER_USE_HISTORY_P", 0)) != 0;
    const double eig_tol = env_double("ITER_REG_EIG_TOL", 1e-8);
    const double res_tol = env_double("ITER_REG_RES_TOL", 1e-8);
    const double orth_tol = env_double("ITER_REG_ORTH_TOL", 1e-8);

    std::vector<RegressionCase> cases = collect_qe_cases(dirs, max_cases);
    if (cases.empty()) {
        std::mt19937 gen(20260313);
        RegressionCase fallback;
        fallback.tag = "random_fallback";
        fallback.n = env_int("ITER_N", 16);
        fallback.m = env_int("ITER_M", std::min(8, fallback.n));
        fallback.h = random_hermitian(fallback.n, gen);
        fallback.s = random_hpd(fallback.n, gen);
        cases.push_back(std::move(fallback));
    }

    sc_clock clk("clk", 1, SC_NS);
    sc_signal<bool> rst_n, start, busy, done;
    sc_signal<bool> sig_use_history_p;
    sc_signal<int> sig_n, sig_m, sig_steps, sig_micro_mode, cycles, hx_ops, sx_ops, qhqx_ops;
    sc_signal<int> ortho_ops, basis_update_ops, reduced_build_ops;
    sc_signal<int> reduced_cholesky_ops, reduced_standardize_ops, reduced_jacobi_ops, reduced_backtransform_ops;
    sc_signal<int> row_hits, row_misses, residue_encodes, crt_reconstructs;

    Iterative_Subspace_Engine engine("ITER_QE_REG_ENGINE");
    engine.clk(clk);
    engine.rst_n(rst_n);
    engine.start(start);
    engine.busy(busy);
    engine.done(done);
    engine.matrix_n(sig_n);
    engine.block_m(sig_m);
    engine.fixed_steps(sig_steps);
    engine.micro_solver_mode(sig_micro_mode);
    engine.use_history_p(sig_use_history_p);
    engine.total_cycles_used(cycles);
    engine.hx_ops_used(hx_ops);
    engine.sx_ops_used(sx_ops);
    engine.qhqx_ops_used(qhqx_ops);
    engine.ortho_ops_used(ortho_ops);
    engine.basis_update_ops_used(basis_update_ops);
    engine.reduced_build_ops_used(reduced_build_ops);
    engine.reduced_cholesky_ops_used(reduced_cholesky_ops);
    engine.reduced_standardize_ops_used(reduced_standardize_ops);
    engine.reduced_jacobi_ops_used(reduced_jacobi_ops);
    engine.reduced_backtransform_ops_used(reduced_backtransform_ops);
    engine.row_buffer_hits_used(row_hits);
    engine.row_buffer_misses_used(row_misses);
    engine.residue_encodes_used(residue_encodes);
    engine.crt_reconstructs_used(crt_reconstructs);

    rst_n.write(false);
    start.write(false);
    sig_n.write(1);
    sig_m.write(1);
    sig_steps.write(steps);
    sig_micro_mode.write(REDUCED_SOLVER_CHOLESKY_JACOBI);
    sig_use_history_p.write(use_history_p);
    sc_start(5, SC_NS);
    rst_n.write(true);
    sc_start(5, SC_NS);

    std::cout << "=== Iterative QE Regression ===\n";
    std::cout << "cases=" << cases.size() << "\n";
    std::cout << "input_source=" << (cases.front().tag == "random_fallback" ? "random_fallback" : "qe_dump") << "\n";
    std::cout << "steps=" << steps << "\n";
    std::cout << "use_history_p=" << (use_history_p ? 1 : 0) << "\n";
    std::cout << "tolerances eig=" << std::scientific << std::setprecision(3)
              << eig_tol << " res=" << res_tol << " Sorth=" << orth_tol << "\n";
    std::cout << std::defaultfloat;
    std::cout << "dirs:\n";
    for (const auto& dir : dirs) std::cout << "  " << dir << "\n";
    std::cout << "\n";

    std::cout << std::left << std::setw(28) << "case"
              << std::right << std::setw(6) << "n"
              << std::setw(6) << "m"
              << std::setw(14) << "mode"
              << std::setw(14) << "eig_max_rel"
              << std::setw(14) << "res_max"
              << std::setw(14) << "Sorth"
              << std::setw(10) << "cycles"
              << std::setw(10) << "hit_rate"
              << std::setw(8) << "hits"
              << std::setw(8) << "miss"
              << std::setw(8) << "enc"
              << std::setw(8) << "crt"
              << std::setw(10) << "status"
              << "\n";

    const int modes[3] = {
        REDUCED_SOLVER_CHOLESKY_JACOBI,
        REDUCED_SOLVER_BINV_JACOBI,
        REDUCED_SOLVER_HYBRID
    };
    ModeSummary summaries[3];
    bool all_ok = true;

    for (size_t case_idx = 0; case_idx < cases.size(); case_idx++) {
        RegressionCase item = cases[case_idx];
        hermitianize_col_major(item.h, item.n);
        hermitianize_col_major(item.s, item.n);

        ReferenceResult ref;
        ref.ok = solve_generalized_reference(item.h, item.s, item.n, ref.evals, ref.eigvecs);
        if (!ref.ok) {
            std::cout << std::left << std::setw(28) << item.tag
                      << std::right << std::setw(6) << item.n
                      << std::setw(6) << item.m
                      << std::setw(14) << "reference"
                      << std::setw(14) << "-"
                      << std::setw(14) << "-"
                      << std::setw(14) << "-"
                      << std::setw(10) << "-"
                      << std::setw(10) << "-"
                      << std::setw(8) << "-"
                      << std::setw(8) << "-"
                      << std::setw(8) << "-"
                      << std::setw(8) << "-"
                      << std::setw(10) << "REF_FAIL"
                      << "\n";
            all_ok = false;
            continue;
        }

        std::mt19937 gen(20260313 + static_cast<unsigned>(case_idx) * 131u +
                         static_cast<unsigned>(item.n) * 17u + static_cast<unsigned>(item.m));
        const std::vector<std::complex<double>> x0 = random_dense(item.n, item.m, gen, 0.2);
        const double h_norm = std::max(1e-30, frob_norm(item.h));
        const double s_norm = std::max(1e-30, frob_norm(item.s));

        double mode0_cycles = 0.0;

        for (int mode_slot = 0; mode_slot < 3; mode_slot++) {
            const int mode = modes[mode_slot];
            ModeMetrics metrics;
            metrics.n = item.n;
            metrics.m = item.m;
            metrics.steps = steps;
            metrics.mode = mode;

            std::vector<double> h_real(item.n * item.n, 0.0);
            std::vector<double> h_imag(item.n * item.n, 0.0);
            std::vector<double> s_real(item.n * item.n, 0.0);
            std::vector<double> s_imag(item.n * item.n, 0.0);
            std::vector<double> x0_real(item.n * item.m, 0.0);
            std::vector<double> x0_imag(item.n * item.m, 0.0);
            std::vector<double> evals(item.m, 0.0);
            std::vector<double> vec_real(item.n * item.m, 0.0);
            std::vector<double> vec_imag(item.n * item.m, 0.0);

            for (int i = 0; i < item.n * item.n; i++) {
                h_real[i] = item.h[i].real();
                h_imag[i] = item.h[i].imag();
                s_real[i] = item.s[i].real();
                s_imag[i] = item.s[i].imag();
            }
            for (int i = 0; i < item.n * item.m; i++) {
                x0_real[i] = x0[i].real();
                x0_imag[i] = x0[i].imag();
            }

            engine.h_real = h_real.data();
            engine.h_imag = h_imag.data();
            engine.s_real = s_real.data();
            engine.s_imag = s_imag.data();
            engine.x0_real = x0_real.data();
            engine.x0_imag = x0_imag.data();
            engine.out_eval = evals.data();
            engine.out_vec_real = vec_real.data();
            engine.out_vec_imag = vec_imag.data();

            sig_n.write(item.n);
            sig_m.write(item.m);
            sig_steps.write(steps);
            sig_micro_mode.write(mode);
            sig_use_history_p.write(use_history_p);

            start.write(true);
            sc_start(1, SC_NS);
            start.write(false);
            while (!done.read()) sc_start(1, SC_NS);
            sc_start(1, SC_NS);

            std::vector<std::complex<double>> vec(item.n * item.m, std::complex<double>(0.0, 0.0));
            for (int i = 0; i < item.n * item.m; i++) vec[i] = std::complex<double>(vec_real[i], vec_imag[i]);

            const int keep = std::min(item.n, item.m);
            for (int col = 0; col < keep; col++) {
                const double rel = std::abs(evals[col] - ref.evals[col]) / std::max(1e-30, std::abs(ref.evals[col]));
                metrics.eig_max_rel = std::max(metrics.eig_max_rel, rel);
                metrics.residual_max = std::max(metrics.residual_max,
                                                residual_norm(item.h, item.s, item.n, vec, col, evals[col], h_norm, s_norm));
            }
            metrics.s_orth_defect = metric_orth_defect(item.s, item.n, vec, keep);
            metrics.cycles = cycles.read();
            metrics.row_hits = row_hits.read();
            metrics.row_misses = row_misses.read();
            metrics.residue_encodes = residue_encodes.read();
            metrics.crt_reconstructs = crt_reconstructs.read();
            metrics.hx_ops = hx_ops.read();
            metrics.sx_ops = sx_ops.read();
            metrics.qhqx_ops = qhqx_ops.read();
            metrics.ortho_ops = ortho_ops.read();
            metrics.basis_update_ops = basis_update_ops.read();
            metrics.reduced_build_ops = reduced_build_ops.read();
            metrics.reduced_cholesky_ops = reduced_cholesky_ops.read();
            metrics.reduced_standardize_ops = reduced_standardize_ops.read();
            metrics.reduced_jacobi_ops = reduced_jacobi_ops.read();
            metrics.reduced_backtransform_ops = reduced_backtransform_ops.read();
            metrics.hit_rate = static_cast<double>(metrics.row_hits) /
                               std::max(1.0, static_cast<double>(metrics.row_hits + metrics.row_misses));
            metrics.ok = metrics_within_tolerance(metrics, eig_tol, res_tol, orth_tol);
            metrics.status = metrics.ok ? "OK" : "BAD_NUM";

            summaries[mode_slot].runs++;
            if (metrics.ok) {
                summaries[mode_slot].ok_runs++;
                summaries[mode_slot].eig_sum += metrics.eig_max_rel;
                summaries[mode_slot].eig_max = std::max(summaries[mode_slot].eig_max, metrics.eig_max_rel);
                summaries[mode_slot].residual_sum += metrics.residual_max;
                summaries[mode_slot].residual_max = std::max(summaries[mode_slot].residual_max, metrics.residual_max);
                summaries[mode_slot].sorth_sum += metrics.s_orth_defect;
                summaries[mode_slot].sorth_max = std::max(summaries[mode_slot].sorth_max, metrics.s_orth_defect);
                summaries[mode_slot].cycles_sum += metrics.cycles;
                summaries[mode_slot].hit_rate_sum += metrics.hit_rate;
            }

            if (mode == REDUCED_SOLVER_CHOLESKY_JACOBI && metrics.ok) mode0_cycles = static_cast<double>(metrics.cycles);
            if (mode != REDUCED_SOLVER_CHOLESKY_JACOBI && metrics.ok && mode0_cycles > 0.0) {
                summaries[mode_slot].speedup_sum += mode0_cycles / std::max(1.0, static_cast<double>(metrics.cycles));
                summaries[mode_slot].speedup_count++;
            }

            std::cout << std::left << std::setw(28) << item.tag
                      << std::right << std::setw(6) << item.n
                      << std::setw(6) << item.m
                      << std::setw(14) << solver_mode_name(mode)
                      << std::scientific << std::setprecision(3)
                      << std::setw(14) << metrics.eig_max_rel
                      << std::setw(14) << metrics.residual_max
                      << std::setw(14) << metrics.s_orth_defect
                      << std::defaultfloat
                      << std::setw(10) << metrics.cycles
                      << std::fixed << std::setprecision(3)
                      << std::setw(10) << metrics.hit_rate
                      << std::defaultfloat
                      << std::setw(8) << metrics.row_hits
                      << std::setw(8) << metrics.row_misses
                      << std::setw(8) << metrics.residue_encodes
                      << std::setw(8) << metrics.crt_reconstructs
                      << std::setw(10) << metrics.status
                      << "\n";

            if (!metrics.ok) all_ok = false;
        }
    }

    std::cout << "\n";
    std::cout << std::left << std::setw(14) << "mode"
              << std::right << std::setw(10) << "ok/runs"
              << std::setw(16) << "avg_eig"
              << std::setw(16) << "max_eig"
              << std::setw(16) << "avg_res"
              << std::setw(16) << "max_res"
              << std::setw(16) << "avg_Sorth"
              << std::setw(16) << "max_Sorth"
              << std::setw(12) << "avg_cycles"
              << std::setw(12) << "avg_hit"
              << std::setw(12) << "speedup"
              << "\n";

    for (int mode_slot = 0; mode_slot < 3; mode_slot++) {
        const ModeSummary& summary = summaries[mode_slot];
        const double denom = std::max(1, summary.ok_runs);
        const double avg_eig = summary.eig_sum / denom;
        const double avg_res = summary.residual_sum / denom;
        const double avg_sorth = summary.sorth_sum / denom;
        const double avg_cycles = summary.cycles_sum / denom;
        const double avg_hit = summary.hit_rate_sum / denom;
        const double avg_speedup = (mode_slot == 0 || summary.speedup_count == 0)
            ? 1.0
            : summary.speedup_sum / std::max(1, summary.speedup_count);

        std::ostringstream ok_runs_ss;
        ok_runs_ss << summary.ok_runs << "/" << summary.runs;

        std::cout << std::left << std::setw(14) << solver_mode_name(modes[mode_slot])
                  << std::right << std::setw(10) << ok_runs_ss.str()
                  << std::scientific << std::setprecision(3)
                  << std::setw(16) << avg_eig
                  << std::setw(16) << summary.eig_max
                  << std::setw(16) << avg_res
                  << std::setw(16) << summary.residual_max
                  << std::setw(16) << avg_sorth
                  << std::setw(16) << summary.sorth_max
                  << std::defaultfloat
                  << std::setw(12) << static_cast<int>(std::llround(avg_cycles))
                  << std::fixed << std::setprecision(3)
                  << std::setw(12) << avg_hit
                  << std::setw(12) << avg_speedup
                  << std::defaultfloat
                  << "\n";
    }

    return all_ok ? 0 : 2;
}
