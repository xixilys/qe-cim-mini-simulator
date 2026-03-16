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

struct CompareCase {
    std::string tag;
    int n = 0;
    int m = 0;
    std::vector<std::complex<double>> h;
    std::vector<std::complex<double>> s;
};

struct SolverMetrics {
    bool ok = false;
    double eig_max_rel = 0.0;
    double residual_max = 0.0;
    double b_orth_defect = 0.0;
    int cycles = 0;
    int qhqx_ops = 0;
    int reduced_build_ops = 0;
    int reduced_cholesky_ops = 0;
    int reduced_standardize_ops = 0;
    int reduced_jacobi_ops = 0;
    int reduced_backtransform_ops = 0;
};

static std::string env_string(const char* name, const std::string& defv) {
    const char* s = std::getenv(name);
    return s ? std::string(s) : defv;
}

static int env_int(const char* name, int defv) {
    const char* s = std::getenv(name);
    return s ? std::atoi(s) : defv;
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

static std::vector<CompareCase> collect_cases(const std::vector<std::string>& dirs, int max_cases) {
    std::vector<CompareCase> cases;
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

            CompareCase item;
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

static std::vector<std::complex<double>> matmul_hermitian(const std::vector<std::complex<double>>& a,
                                                          int n,
                                                          const std::vector<std::complex<double>>& x,
                                                          int cols) {
    std::vector<std::complex<double>> y(n * cols, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < cols; col++) {
        for (int row = 0; row < n; row++) {
            std::complex<double> acc(0.0, 0.0);
            for (int k = 0; k < n; k++) acc += a[row + k * n] * x[k + col * n];
            y[row + col * n] = acc;
        }
    }
    return y;
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

static double reduced_residual_max(const std::vector<std::complex<double>>& a,
                                   const std::vector<std::complex<double>>& b,
                                   const std::vector<double>& evals,
                                   const std::vector<std::complex<double>>& z,
                                   int k) {
    double max_res = 0.0;
    for (int col = 0; col < k; col++) {
        long double sq = 0.0L;
        long double denom = 0.0L;
        for (int row = 0; row < k; row++) {
            std::complex<long double> az(0.0L, 0.0L);
            std::complex<long double> bz(0.0L, 0.0L);
            for (int j = 0; j < k; j++) {
                az += std::complex<long double>(a[row + j * k].real(), a[row + j * k].imag()) *
                      std::complex<long double>(z[j + col * k].real(), z[j + col * k].imag());
                bz += std::complex<long double>(b[row + j * k].real(), b[row + j * k].imag()) *
                      std::complex<long double>(z[j + col * k].real(), z[j + col * k].imag());
            }
            const std::complex<long double> diff = az - static_cast<long double>(evals[col]) * bz;
            sq += std::norm(diff);
            denom += std::norm(az) + std::norm(static_cast<long double>(evals[col]) * bz);
        }
        max_res = std::max(max_res, std::sqrt(static_cast<double>(sq / std::max(1e-30L, denom))));
    }
    return max_res;
}

static double b_orth_defect(const std::vector<std::complex<double>>& b,
                            const std::vector<std::complex<double>>& z,
                            int k) {
    long double acc = 0.0L;
    for (int i = 0; i < k; i++) {
        for (int j = 0; j < k; j++) {
            std::complex<long double> gij(0.0L, 0.0L);
            for (int row = 0; row < k; row++) {
                std::complex<long double> bz(0.0L, 0.0L);
                for (int col = 0; col < k; col++) {
                    bz += std::complex<long double>(b[row + col * k].real(), b[row + col * k].imag()) *
                          std::complex<long double>(z[col + j * k].real(), z[col + j * k].imag());
                }
                const std::complex<long double> zi(z[row + i * k].real(), z[row + i * k].imag());
                gij += std::conj(zi) * bz;
            }
            if (i == j) gij -= std::complex<long double>(1.0L, 0.0L);
            acc += std::norm(gij);
        }
    }
    return std::sqrt(static_cast<double>(acc));
}

static SolverMetrics run_solver_mode(const Reduced_Generalized_MicroSolver& solver,
                                     const std::vector<std::complex<double>>& q,
                                     const std::vector<std::complex<double>>& hq,
                                     const std::vector<std::complex<double>>& sq,
                                     const std::vector<std::complex<double>>& a,
                                     const std::vector<std::complex<double>>& b,
                                     const std::vector<double>& eval_ref,
                                     int n, int k, int mode) {
    SolverMetrics out;
    IterativeStats stats;
    std::vector<double> evals;
    std::vector<std::complex<double>> z;
    out.ok = solver.solve_q_subspace(q, hq, sq, n, k, mode, evals, z, stats);
    if (!out.ok) return out;

    for (int i = 0; i < k; i++) {
        const double rel = std::abs(evals[i] - eval_ref[i]) / std::max(1e-30, std::abs(eval_ref[i]));
        out.eig_max_rel = std::max(out.eig_max_rel, rel);
    }
    out.residual_max = reduced_residual_max(a, b, evals, z, k);
    out.b_orth_defect = b_orth_defect(b, z, k);
    out.cycles = stats.cycles;
    out.qhqx_ops = stats.qhqx_ops;
    out.reduced_build_ops = stats.reduced_build_ops;
    out.reduced_cholesky_ops = stats.reduced_cholesky_ops;
    out.reduced_standardize_ops = stats.reduced_standardize_ops;
    out.reduced_jacobi_ops = stats.reduced_jacobi_ops;
    out.reduced_backtransform_ops = stats.reduced_backtransform_ops;
    return out;
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    const std::string default_dirs =
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump";
    const std::vector<std::string> dirs = split_csv_list(env_string("ITER_SUBSPACE_DIRS", default_dirs));
    const int max_cases = env_int("ITER_MICRO_MAX_CASES", 4);

    std::vector<CompareCase> cases = collect_cases(dirs, max_cases);
    const bool using_random_fallback = cases.empty();
    if (cases.empty()) {
        std::mt19937 gen(20260313);
        const int random_cases = std::max(1, max_cases);
        for (int case_idx = 0; case_idx < random_cases; case_idx++) {
            CompareCase fallback;
            fallback.tag = "random_" + std::to_string(case_idx);
            fallback.n = env_int("ITER_N", 16);
            fallback.m = env_int("ITER_M", std::min(8, fallback.n));
            fallback.h = random_dense(fallback.n, fallback.n, gen, 0.2);
            hermitianize_col_major(fallback.h, fallback.n);
            const std::vector<std::complex<double>> b = random_dense(fallback.n, fallback.n, gen, 0.2);
            const std::vector<std::complex<double>> bh = conj_transpose(b, fallback.n, fallback.n);
            fallback.s = matmul(bh, b, fallback.n, fallback.n, fallback.n);
            for (int i = 0; i < fallback.n; i++) fallback.s[i + i * fallback.n] += std::complex<double>(2.0, 0.0);
            hermitianize_col_major(fallback.s, fallback.n);
            cases.push_back(std::move(fallback));
        }
    }

    Reduced_Generalized_MicroSolver solver;
    Reduced_Projection_Unit projector;
    Subspace_Ortho_Unit ortho;
    std::mt19937 gen(20260313);

    std::cout << "=== Iterative Reduced Micro Solver Compare ===\n";
    std::cout << "cases=" << cases.size() << "\n";
    std::cout << "input_source=" << (using_random_fallback ? "random_fallback" : "qe_dump") << "\n";
    std::cout << std::left << std::setw(28) << "case"
              << std::right << std::setw(6) << "k"
              << std::setw(16) << "mode"
              << std::setw(14) << "eig_max_rel"
              << std::setw(14) << "res_max"
              << std::setw(14) << "Borth"
              << std::setw(10) << "cycles"
              << std::setw(8) << "chol"
              << std::setw(8) << "std"
              << std::setw(8) << "jac"
              << std::setw(8) << "back"
              << std::setw(10) << "status"
              << "\n";

    double chol_eig_sum = 0.0;
    double chol_res_sum = 0.0;
    double chol_borth_sum = 0.0;
    double approx_eig_sum = 0.0;
    double approx_res_sum = 0.0;
    double approx_borth_sum = 0.0;
    int sample_count = 0;

    for (size_t case_idx = 0; case_idx < cases.size(); case_idx++) {
        const CompareCase& item = cases[case_idx];
        const int expand = std::min(item.m, item.n - item.m);
        const int ks[2] = {
            std::max(1, std::min(item.m, item.n)),
            std::max(1, std::min(item.n, item.m + std::max(0, expand)))
        };

        for (int pass = 0; pass < 2; pass++) {
            const int k = ks[pass];
            std::vector<std::complex<double>> q = random_dense(item.n, k, gen, 0.2);
            IterativeStats ortho_stats;
            ortho.orthonormalize(item.s, q, item.n, k, ortho_stats);
            const std::vector<std::complex<double>> hq = matmul_hermitian(item.h, item.n, q, k);
            const std::vector<std::complex<double>> sq = matmul_hermitian(item.s, item.n, q, k);

            IterativeStats proj_stats;
            std::vector<std::complex<double>> a;
            std::vector<std::complex<double>> b;
            projector.build_projected(q, hq, sq, item.n, k, a, b, proj_stats);
            hermitianize_col_major(a, k);
            hermitianize_col_major(b, k);

            std::vector<double> eval_ref;
            std::vector<std::complex<double>> z_ref;
            const bool ref_ok = solve_generalized_reference(a, b, k, eval_ref, z_ref);

            const SolverMetrics chol = ref_ok
                ? run_solver_mode(solver, q, hq, sq, a, b, eval_ref, item.n, k, REDUCED_SOLVER_CHOLESKY_JACOBI)
                : SolverMetrics{};
            const SolverMetrics approx = ref_ok
                ? run_solver_mode(solver, q, hq, sq, a, b, eval_ref, item.n, k, REDUCED_SOLVER_BINV_JACOBI)
                : SolverMetrics{};

            auto print_metrics = [&](const char* mode_name, const SolverMetrics& metrics) {
                std::cout << std::left << std::setw(28) << (item.tag + (pass == 0 ? "/x" : "/q"))
                          << std::right << std::setw(6) << k
                          << std::setw(16) << mode_name
                          << std::scientific << std::setprecision(3)
                          << std::setw(14) << metrics.eig_max_rel
                          << std::setw(14) << metrics.residual_max
                          << std::setw(14) << metrics.b_orth_defect
                          << std::defaultfloat
                          << std::setw(10) << metrics.cycles
                          << std::setw(8) << metrics.reduced_cholesky_ops
                          << std::setw(8) << metrics.reduced_standardize_ops
                          << std::setw(8) << metrics.reduced_jacobi_ops
                          << std::setw(8) << metrics.reduced_backtransform_ops
                          << std::setw(10) << (metrics.ok ? "OK" : "FAIL")
                          << "\n";
            };

            print_metrics("chol_jacobi", chol);
            print_metrics("binv_jacobi", approx);

            if (chol.ok) {
                chol_eig_sum += chol.eig_max_rel;
                chol_res_sum += chol.residual_max;
                chol_borth_sum += chol.b_orth_defect;
            }
            if (approx.ok) {
                approx_eig_sum += approx.eig_max_rel;
                approx_res_sum += approx.residual_max;
                approx_borth_sum += approx.b_orth_defect;
            }
            sample_count++;
        }
    }

    if (sample_count > 0) {
        std::cout << "\n";
        std::cout << "avg_chol_jacobi eig_max_rel=" << std::scientific << std::setprecision(6)
                  << chol_eig_sum / sample_count
                  << " res_max=" << chol_res_sum / sample_count
                  << " Borth=" << chol_borth_sum / sample_count << "\n";
        std::cout << "avg_binv_jacobi eig_max_rel=" << approx_eig_sum / sample_count
                  << " res_max=" << approx_res_sum / sample_count
                  << " Borth=" << approx_borth_sum / sample_count << "\n";
    }

    return 0;
}
