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
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

using LapackInt = __CLPK_integer;
using LapackComplex = __CLPK_doublecomplex;

struct ComplexMatrix {
    int rows;
    int cols;
    std::vector<std::complex<double>> data;  // row-major

    ComplexMatrix(int r = 0, int c = 0) : rows(r), cols(c), data(r * c, std::complex<double>(0.0, 0.0)) {}

    inline int idx(int r, int c) const { return r * cols + c; }
};

struct CaseInput {
    std::string tag;
    std::string h_path;
    std::string s_path;
    int n = 0;
    int m = 0;
    ComplexMatrix h;
    ComplexMatrix s;
};

struct CaseMetrics {
    bool ok = false;
    std::string status = "UNSET";
    int n = 0;
    int m = 0;
    double eig_max_abs = 0.0;
    double eig_max_rel = 0.0;
    double eig_rms_rel = 0.0;
    double residual_max = 0.0;
    double residual_rms = 0.0;
    double s_orth_defect = 0.0;
    double iter_eig_max_rel = 0.0;
    double iter_eig_rms_rel = 0.0;
    double iter_residual_max = 0.0;
    double iter_residual_rms = 0.0;
    double iter_s_orth_defect = 0.0;
    int iter_steps = 0;
};

static double sq_abs(const std::complex<double>& z) {
    return z.real() * z.real() + z.imag() * z.imag();
}

static double frob_norm(const ComplexMatrix& a) {
    double acc = 0.0;
    for (const auto& z : a.data) acc += sq_abs(z);
    return std::sqrt(acc);
}

static ComplexMatrix hermitianize(const ComplexMatrix& a) {
    ComplexMatrix out = a;
    for (int i = 0; i < a.rows; i++) {
        out.data[out.idx(i, i)] = std::complex<double>(a.data[a.idx(i, i)].real(), 0.0);
        for (int j = i + 1; j < a.cols; j++) {
            std::complex<double> avg = 0.5 * (a.data[a.idx(i, j)] + std::conj(a.data[a.idx(j, i)]));
            out.data[out.idx(i, j)] = avg;
            out.data[out.idx(j, i)] = std::conj(avg);
        }
    }
    return out;
}

static std::vector<std::complex<double>> to_col_major(const ComplexMatrix& a) {
    std::vector<std::complex<double>> out(a.rows * a.cols);
    for (int i = 0; i < a.rows; i++) {
        for (int j = 0; j < a.cols; j++) {
            out[i + j * a.rows] = a.data[a.idx(i, j)];
        }
    }
    return out;
}

static void hermitianize_col_major(std::vector<std::complex<double>>& a, int n) {
    for (int i = 0; i < n; i++) {
        a[i + i * n] = std::complex<double>(a[i + i * n].real(), 0.0);
        for (int j = i + 1; j < n; j++) {
            std::complex<double> avg = 0.5 * (a[i + j * n] + std::conj(a[j + i * n]));
            a[i + j * n] = avg;
            a[j + i * n] = std::conj(avg);
        }
    }
}

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

static ComplexMatrix load_dump_csv(const std::string& path, int n) {
    ComplexMatrix out(n, n);
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
        int row = std::stoi(toks[0]) - 1;
        int col = std::stoi(toks[1]) - 1;
        double rr = std::stod(toks[2]);
        double ii = std::stod(toks[3]);
        out.data[out.idx(row, col)] = std::complex<double>(rr, ii);
    }
    return out;
}

static std::vector<CaseInput> collect_qe_cases(const std::vector<std::string>& dirs, int max_cases) {
    std::vector<CaseInput> cases;
    std::regex h_pat(R"((.+)_H_call(\d+)_n(\d+)_m(\d+)\.csv$)");
    for (const std::string& dir : dirs) {
        std::filesystem::path root(dir);
        if (!std::filesystem::exists(root) || !std::filesystem::is_directory(root)) continue;
        std::vector<std::filesystem::path> files;
        for (const auto& ent : std::filesystem::directory_iterator(root)) {
            if (ent.is_regular_file()) files.push_back(ent.path());
        }
        std::sort(files.begin(), files.end());
        for (const auto& path : files) {
            std::smatch match;
            std::string name = path.filename().string();
            if (!std::regex_match(name, match, h_pat)) continue;
            std::string prefix = match[1].str();
            std::string call_id = match[2].str();
            int n = std::stoi(match[3].str());
            int m = std::stoi(match[4].str());
            std::filesystem::path s_path = root / (prefix + "_S_call" + call_id + "_n" +
                                                   std::to_string(n) + "_m" + std::to_string(m) + ".csv");
            if (!std::filesystem::exists(s_path)) continue;

            CaseInput item;
            item.tag = root.filename().string() + "/call" + call_id;
            item.h_path = path.string();
            item.s_path = s_path.string();
            item.n = n;
            item.m = m;
            item.h = load_dump_csv(item.h_path, n);
            item.s = load_dump_csv(item.s_path, n);
            cases.push_back(std::move(item));
            if (max_cases > 0 && static_cast<int>(cases.size()) >= max_cases) return cases;
        }
    }
    return cases;
}

static bool solve_standard_hermitian(std::vector<std::complex<double>>& a, int n, std::vector<double>& evals) {
    evals.assign(n, 0.0);
    LapackInt lda = n;
    LapackInt ln = n;
    LapackInt lwork = -1;
    LapackInt info = 0;
    char jobz = 'V';
    char uplo = 'U';
    std::complex<double> work_query(0.0, 0.0);
    std::vector<double> rwork(std::max(1, 3 * n - 2), 0.0);

    zheev_(&jobz, &uplo, &ln, reinterpret_cast<LapackComplex*>(a.data()), &lda,
           evals.data(), reinterpret_cast<LapackComplex*>(&work_query), &lwork, rwork.data(), &info);
    if (info != 0) return false;

    lwork = std::max<LapackInt>(1, static_cast<LapackInt>(std::llround(work_query.real())));
    std::vector<std::complex<double>> work(lwork);
    zheev_(&jobz, &uplo, &ln, reinterpret_cast<LapackComplex*>(a.data()), &lda,
           evals.data(), reinterpret_cast<LapackComplex*>(work.data()), &lwork, rwork.data(), &info);
    return info == 0;
}

static bool solve_generalized_direct(const ComplexMatrix& h_in, const ComplexMatrix& s_in,
                                     std::vector<double>& evals,
                                     std::vector<std::complex<double>>& eigvecs) {
    ComplexMatrix h = hermitianize(h_in);
    ComplexMatrix s = hermitianize(s_in);
    eigvecs = to_col_major(h);
    std::vector<std::complex<double>> b = to_col_major(s);

    LapackInt n = h.rows;
    LapackInt lda = n;
    LapackInt ldb = n;
    LapackInt itype = 1;
    LapackInt lwork = -1;
    LapackInt info = 0;
    char jobz = 'V';
    char uplo = 'U';
    evals.assign(static_cast<int>(n), 0.0);
    std::complex<double> work_query(0.0, 0.0);
    std::vector<double> rwork(std::max<LapackInt>(1, 3 * n - 2), 0.0);

    zhegv_(&itype, &jobz, &uplo, &n,
           reinterpret_cast<LapackComplex*>(eigvecs.data()), &lda,
           reinterpret_cast<LapackComplex*>(b.data()), &ldb,
           evals.data(), reinterpret_cast<LapackComplex*>(&work_query), &lwork, rwork.data(), &info);
    if (info != 0) return false;

    lwork = std::max<LapackInt>(1, static_cast<LapackInt>(std::llround(work_query.real())));
    std::vector<std::complex<double>> work(lwork);
    zhegv_(&itype, &jobz, &uplo, &n,
           reinterpret_cast<LapackComplex*>(eigvecs.data()), &lda,
           reinterpret_cast<LapackComplex*>(b.data()), &ldb,
           evals.data(), reinterpret_cast<LapackComplex*>(work.data()), &lwork, rwork.data(), &info);
    return info == 0;
}

static bool solve_generalized_pipeline(const ComplexMatrix& h_in, const ComplexMatrix& s_in,
                                       std::vector<double>& evals,
                                       std::vector<std::complex<double>>& eigvecs) {
    ComplexMatrix h = hermitianize(h_in);
    ComplexMatrix s = hermitianize(s_in);
    std::vector<std::complex<double>> s_col = to_col_major(s);
    std::vector<std::complex<double>> l = s_col;
    int n = h.rows;
    LapackInt ln = n;
    LapackInt lda = n;
    LapackInt info = 0;
    char lower = 'L';
    zpotrf_(&lower, &ln, reinterpret_cast<LapackComplex*>(l.data()), &lda, &info);
    if (info != 0) return false;

    std::vector<std::complex<double>> a = to_col_major(h);
    const std::complex<double> one(1.0, 0.0);
    cblas_ztrsm(CblasColMajor, CblasLeft, CblasLower, CblasNoTrans, CblasNonUnit,
                n, n, &one, l.data(), n, a.data(), n);
    cblas_ztrsm(CblasColMajor, CblasRight, CblasLower, CblasConjTrans, CblasNonUnit,
                n, n, &one, l.data(), n, a.data(), n);
    hermitianize_col_major(a, n);

    if (!solve_standard_hermitian(a, n, evals)) return false;

    eigvecs = a;
    cblas_ztrsm(CblasColMajor, CblasLeft, CblasLower, CblasConjTrans, CblasNonUnit,
                n, n, &one, l.data(), n, eigvecs.data(), n);

    const double eps = 1e-30;
    for (int col = 0; col < n; col++) {
        std::complex<double> acc(0.0, 0.0);
        for (int i = 0; i < n; i++) {
            std::complex<double> vi = eigvecs[i + col * n];
            for (int j = 0; j < n; j++) {
                acc += std::conj(vi) * s_col[i + j * n] * eigvecs[j + col * n];
            }
        }
        double scale = 1.0 / std::sqrt(std::max(eps, acc.real()));
        for (int i = 0; i < n; i++) eigvecs[i + col * n] *= scale;
    }
    return true;
}

static std::complex<double> dot_with_metric(const std::vector<std::complex<double>>& s, int n,
                                            const std::vector<std::complex<double>>& v, int c0, int c1);

static std::vector<std::complex<double>> matmul_col_major(const std::vector<std::complex<double>>& a,
                                                          const std::vector<std::complex<double>>& b,
                                                          int m, int k, int n) {
    std::vector<std::complex<double>> c(m * n, std::complex<double>(0.0, 0.0));
    for (int j = 0; j < n; j++) {
        for (int p = 0; p < k; p++) {
            std::complex<double> bpj = b[p + j * k];
            for (int i = 0; i < m; i++) c[i + j * m] += a[i + p * m] * bpj;
        }
    }
    return c;
}

static std::vector<std::complex<double>> matmul_hermitian(const std::vector<std::complex<double>>& a,
                                                          int n,
                                                          const std::vector<std::complex<double>>& x,
                                                          int m) {
    std::vector<std::complex<double>> y(n * m, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < m; col++) {
        for (int i = 0; i < n; i++) {
            std::complex<double> acc(0.0, 0.0);
            for (int j = 0; j < n; j++) acc += a[i + j * n] * x[j + col * n];
            y[i + col * n] = acc;
        }
    }
    return y;
}

static void s_orthonormalize(const std::vector<std::complex<double>>& s, int n,
                             std::vector<std::complex<double>>& x, int m) {
    const double eps = 1e-30;
    for (int c = 0; c < m; c++) {
        for (int p = 0; p < c; p++) {
            std::complex<double> proj = dot_with_metric(s, n, x, p, c);
            for (int i = 0; i < n; i++) x[i + c * n] -= x[i + p * n] * proj;
        }
        double nrm = std::sqrt(std::max(eps, dot_with_metric(s, n, x, c, c).real()));
        for (int i = 0; i < n; i++) x[i + c * n] /= nrm;
    }
}

static std::vector<std::complex<double>> initial_guess_by_diag(const ComplexMatrix& h, int n, int m) {
    std::vector<std::pair<double, int>> score;
    score.reserve(n);
    for (int i = 0; i < n; i++) score.push_back({h.data[h.idx(i, i)].real(), i});
    std::sort(score.begin(), score.end());

    std::vector<std::complex<double>> x(n * m, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < m; col++) x[score[col % n].second + col * n] = std::complex<double>(1.0, 0.0);
    return x;
}

static bool solve_reduced_generalized(const std::vector<std::complex<double>>& q,
                                      const std::vector<std::complex<double>>& hq,
                                      const std::vector<std::complex<double>>& sq,
                                      int n, int k,
                                      std::vector<double>& evals,
                                      std::vector<std::complex<double>>& z) {
    ComplexMatrix a(k, k);
    ComplexMatrix b(k, k);
    for (int i = 0; i < k; i++) {
        for (int j = 0; j < k; j++) {
            std::complex<double> acc_h(0.0, 0.0);
            std::complex<double> acc_s(0.0, 0.0);
            for (int r = 0; r < n; r++) {
                acc_h += std::conj(q[r + i * n]) * hq[r + j * n];
                acc_s += std::conj(q[r + i * n]) * sq[r + j * n];
            }
            a.data[a.idx(i, j)] = acc_h;
            b.data[b.idx(i, j)] = acc_s;
        }
    }
    a = hermitianize(a);
    b = hermitianize(b);
    for (int i = 0; i < k; i++) b.data[b.idx(i, i)] += std::complex<double>(1e-12, 0.0);
    return solve_generalized_direct(a, b, evals, z);
}

static bool solve_generalized_iterative_cim(const ComplexMatrix& h_in, const ComplexMatrix& s_in,
                                            int keep, int steps,
                                            std::vector<double>& evals,
                                            std::vector<std::complex<double>>& eigvecs) {
    ComplexMatrix h = hermitianize(h_in);
    ComplexMatrix s = hermitianize(s_in);
    std::vector<std::complex<double>> h_col = to_col_major(h);
    std::vector<std::complex<double>> s_col = to_col_major(s);

    std::vector<std::complex<double>> x = initial_guess_by_diag(h, h.rows, keep);
    s_orthonormalize(s_col, h.rows, x, keep);

    for (int iter = 0; iter < steps; iter++) {
        std::vector<std::complex<double>> hx = matmul_hermitian(h_col, h.rows, x, keep);
        std::vector<std::complex<double>> sx = matmul_hermitian(s_col, s.rows, x, keep);

        std::vector<double> theta_small;
        std::vector<std::complex<double>> u_small;
        if (!solve_reduced_generalized(x, hx, sx, h.rows, keep, theta_small, u_small)) return false;

        x = matmul_col_major(x, u_small, h.rows, keep, keep);
        hx = matmul_col_major(hx, u_small, h.rows, keep, keep);
        sx = matmul_col_major(sx, u_small, h.rows, keep, keep);
        s_orthonormalize(s_col, h.rows, x, keep);
        hx = matmul_hermitian(h_col, h.rows, x, keep);
        sx = matmul_hermitian(s_col, s.rows, x, keep);

        int expand = std::min(keep, h.rows - keep);
        if (expand <= 0) {
            evals.assign(theta_small.begin(), theta_small.begin() + keep);
            continue;
        }

        std::vector<std::complex<double>> r(h.rows * expand, std::complex<double>(0.0, 0.0));
        for (int col = 0; col < expand; col++) {
            for (int i = 0; i < h.rows; i++) r[i + col * h.rows] = hx[i + col * h.rows] - theta_small[col] * sx[i + col * h.rows];
        }

        int q_cols = keep + expand;
        std::vector<std::complex<double>> q(h.rows * q_cols, std::complex<double>(0.0, 0.0));
        for (int col = 0; col < keep; col++) {
            for (int i = 0; i < h.rows; i++) {
                q[i + col * h.rows] = x[i + col * h.rows];
            }
        }
        for (int col = 0; col < expand; col++) {
            for (int i = 0; i < h.rows; i++) q[i + (col + keep) * h.rows] = r[i + col * h.rows];
        }
        s_orthonormalize(s_col, h.rows, q, q_cols);

        std::vector<std::complex<double>> hq = matmul_hermitian(h_col, h.rows, q, q_cols);
        std::vector<std::complex<double>> sq = matmul_hermitian(s_col, s.rows, q, q_cols);

        std::vector<double> theta_big;
        std::vector<std::complex<double>> y_big;
        if (!solve_reduced_generalized(q, hq, sq, h.rows, q_cols, theta_big, y_big)) return false;

        std::vector<std::complex<double>> y_keep(q_cols * keep, std::complex<double>(0.0, 0.0));
        for (int col = 0; col < keep; col++) {
            for (int row = 0; row < q_cols; row++) y_keep[row + col * q_cols] = y_big[row + col * q_cols];
        }
        x = matmul_col_major(q, y_keep, h.rows, q_cols, keep);
        s_orthonormalize(s_col, h.rows, x, keep);
        evals.assign(theta_big.begin(), theta_big.begin() + keep);
    }

    eigvecs = x;
    if (evals.empty()) {
        std::vector<std::complex<double>> hx = matmul_hermitian(h_col, h.rows, x, keep);
        std::vector<std::complex<double>> sx = matmul_hermitian(s_col, s.rows, x, keep);
        std::vector<double> theta_small;
        std::vector<std::complex<double>> u_small;
        if (!solve_reduced_generalized(x, hx, sx, h.rows, keep, theta_small, u_small)) return false;
        evals = theta_small;
        eigvecs = matmul_col_major(x, u_small, h.rows, keep, keep);
        s_orthonormalize(s_col, h.rows, eigvecs, keep);
    }
    return true;
}

static std::complex<double> dot_with_metric(const std::vector<std::complex<double>>& s, int n,
                                            const std::vector<std::complex<double>>& v, int c0, int c1) {
    std::complex<double> acc(0.0, 0.0);
    for (int i = 0; i < n; i++) {
        std::complex<double> svi(0.0, 0.0);
        for (int j = 0; j < n; j++) {
            svi += s[i + j * n] * v[j + c1 * n];
        }
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

static double residual_norm(const std::vector<std::complex<double>>& h, const std::vector<std::complex<double>>& s,
                            int n, const std::vector<std::complex<double>>& v, int col, double eval,
                            double h_norm, double s_norm) {
    double sq = 0.0;
    for (int i = 0; i < n; i++) {
        std::complex<double> hv(0.0, 0.0);
        std::complex<double> sv(0.0, 0.0);
        for (int j = 0; j < n; j++) {
            hv += h[i + j * n] * v[j + col * n];
            sv += s[i + j * n] * v[j + col * n];
        }
        std::complex<double> diff = hv - eval * sv;
        sq += sq_abs(diff);
    }
    double denom = std::max(1e-30, h_norm + std::abs(eval) * s_norm);
    return std::sqrt(sq) / denom;
}

static CaseMetrics evaluate_case(const CaseInput& input) {
    CaseMetrics out;
    out.n = input.n;
    out.m = input.m;

    ComplexMatrix h = hermitianize(input.h);
    ComplexMatrix s = hermitianize(input.s);
    std::vector<std::complex<double>> h_col = to_col_major(h);
    std::vector<std::complex<double>> s_col = to_col_major(s);
    double h_norm = std::max(1e-30, frob_norm(h));
    double s_norm = std::max(1e-30, frob_norm(s));

    std::vector<double> eval_ref;
    std::vector<double> eval_pipe;
    std::vector<double> eval_iter;
    std::vector<std::complex<double>> vec_ref;
    std::vector<std::complex<double>> vec_pipe;
    std::vector<std::complex<double>> vec_iter;
    int iter_steps = std::max(1, env_int("GEN_SUBSPACE_ITER_STEPS", 6));

    if (!solve_generalized_direct(h, s, eval_ref, vec_ref)) {
        out.status = "DIRECT_FAIL";
        return out;
    }
    if (!solve_generalized_pipeline(h, s, eval_pipe, vec_pipe)) {
        out.status = "PIPELINE_FAIL";
        return out;
    }
    if (!solve_generalized_iterative_cim(h, s, std::min(input.m, input.n), iter_steps, eval_iter, vec_iter)) {
        out.status = "ITER_FAIL";
        return out;
    }

    const int keep = std::min(input.m, input.n);
    double eig_sq_rel = 0.0;
    double iter_eig_sq_rel = 0.0;
    for (int i = 0; i < keep; i++) {
        double abs_err = std::abs(eval_pipe[i] - eval_ref[i]);
        double rel_err = abs_err / std::max(1e-30, std::abs(eval_ref[i]));
        out.eig_max_abs = std::max(out.eig_max_abs, abs_err);
        out.eig_max_rel = std::max(out.eig_max_rel, rel_err);
        eig_sq_rel += rel_err * rel_err;

        double iter_abs_err = std::abs(eval_iter[i] - eval_ref[i]);
        double iter_rel_err = iter_abs_err / std::max(1e-30, std::abs(eval_ref[i]));
        out.iter_eig_max_rel = std::max(out.iter_eig_max_rel, iter_rel_err);
        iter_eig_sq_rel += iter_rel_err * iter_rel_err;
    }
    out.eig_rms_rel = std::sqrt(eig_sq_rel / std::max(1, keep));
    out.iter_eig_rms_rel = std::sqrt(iter_eig_sq_rel / std::max(1, keep));

    double res_sq = 0.0;
    double iter_res_sq = 0.0;
    for (int i = 0; i < keep; i++) {
        double res = residual_norm(h_col, s_col, input.n, vec_pipe, i, eval_pipe[i], h_norm, s_norm);
        out.residual_max = std::max(out.residual_max, res);
        res_sq += res * res;

        double iter_res = residual_norm(h_col, s_col, input.n, vec_iter, i, eval_iter[i], h_norm, s_norm);
        out.iter_residual_max = std::max(out.iter_residual_max, iter_res);
        iter_res_sq += iter_res * iter_res;
    }
    out.residual_rms = std::sqrt(res_sq / std::max(1, keep));
    out.iter_residual_rms = std::sqrt(iter_res_sq / std::max(1, keep));
    out.s_orth_defect = metric_orth_defect(s_col, input.n, vec_pipe, keep);
    out.iter_s_orth_defect = metric_orth_defect(s_col, input.n, vec_iter, keep);
    out.iter_steps = iter_steps;
    out.ok = true;
    out.status = "OK";
    return out;
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    std::string default_dirs =
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump";
    std::vector<std::string> dirs = split_csv_list(env_string("GEN_SUBSPACE_DIRS", default_dirs));
    int max_cases = env_int("GEN_SUBSPACE_MAX_CASES", 0);

    std::vector<CaseInput> cases = collect_qe_cases(dirs, max_cases);
    std::cout << "=== Generalized Hermitian Subspace Validation ===\n";
    std::cout << "Case dirs:\n";
    for (const auto& dir : dirs) std::cout << "  " << dir << "\n";
    std::cout << "Collected cases: " << cases.size() << "\n\n";
    std::cout << "Iterative model steps: " << std::max(1, env_int("GEN_SUBSPACE_ITER_STEPS", 6)) << "\n\n";

    if (cases.empty()) {
        std::cout << "No QE dump pairs found.\n";
        return 1;
    }

    std::vector<std::pair<std::string, CaseMetrics>> metrics;
    metrics.reserve(cases.size());
    for (const auto& item : cases) {
        metrics.push_back({item.tag, evaluate_case(item)});
    }

    std::cout << std::left << std::setw(28) << "Case"
              << std::right << std::setw(6) << "n"
              << std::setw(6) << "m"
              << std::setw(14) << "eig_max_rel"
              << std::setw(14) << "iter_eig"
              << std::setw(14) << "eig_rms_rel"
              << std::setw(14) << "res_max"
              << std::setw(14) << "iter_res"
              << std::setw(14) << "res_rms"
              << std::setw(14) << "Sorth"
              << std::setw(14) << "iter_Sorth"
              << std::setw(14) << "status"
              << "\n";

    double max_eig_rel = 0.0;
    double max_res = 0.0;
    double max_sorth = 0.0;
    double max_iter_eig_rel = 0.0;
    double max_iter_res = 0.0;
    double max_iter_sorth = 0.0;
    double sum_eig_rel = 0.0;
    double sum_res = 0.0;
    double sum_sorth = 0.0;
    double sum_iter_eig_rel = 0.0;
    double sum_iter_res = 0.0;
    double sum_iter_sorth = 0.0;
    int ok_cases = 0;

    for (const auto& item : metrics) {
        const CaseMetrics& m = item.second;
        std::cout << std::left << std::setw(28) << item.first
                  << std::right << std::setw(6) << m.n
                  << std::setw(6) << m.m
                  << std::setw(14) << std::scientific << std::setprecision(3) << m.eig_max_rel
                  << std::setw(14) << m.iter_eig_max_rel
                  << std::setw(14) << m.eig_rms_rel
                  << std::setw(14) << m.residual_max
                  << std::setw(14) << m.iter_residual_max
                  << std::setw(14) << m.residual_rms
                  << std::setw(14) << m.s_orth_defect
                  << std::setw(14) << m.iter_s_orth_defect
                  << std::setw(14) << m.status
                  << "\n";
        if (m.ok) {
            ok_cases++;
            max_eig_rel = std::max(max_eig_rel, m.eig_max_rel);
            max_res = std::max(max_res, m.residual_max);
            max_sorth = std::max(max_sorth, m.s_orth_defect);
            max_iter_eig_rel = std::max(max_iter_eig_rel, m.iter_eig_max_rel);
            max_iter_res = std::max(max_iter_res, m.iter_residual_max);
            max_iter_sorth = std::max(max_iter_sorth, m.iter_s_orth_defect);
            sum_eig_rel += m.eig_max_rel;
            sum_res += m.residual_max;
            sum_sorth += m.s_orth_defect;
            sum_iter_eig_rel += m.iter_eig_max_rel;
            sum_iter_res += m.iter_residual_max;
            sum_iter_sorth += m.iter_s_orth_defect;
        }
    }

    std::cout << "\nSummary\n";
    std::cout << "  ok_cases         : " << ok_cases << " / " << cases.size() << "\n";
    if (ok_cases > 0) {
        std::cout << "  avg eig_max_rel  : " << std::scientific << std::setprecision(6)
                  << (sum_eig_rel / ok_cases) << "\n";
        std::cout << "  max eig_max_rel  : " << max_eig_rel << "\n";
        std::cout << "  avg iter_eig_rel : " << (sum_iter_eig_rel / ok_cases) << "\n";
        std::cout << "  max iter_eig_rel : " << max_iter_eig_rel << "\n";
        std::cout << "  avg residual_max : " << (sum_res / ok_cases) << "\n";
        std::cout << "  max residual_max : " << max_res << "\n";
        std::cout << "  avg iter_res_max : " << (sum_iter_res / ok_cases) << "\n";
        std::cout << "  max iter_res_max : " << max_iter_res << "\n";
        std::cout << "  avg S-orth defect: " << (sum_sorth / ok_cases) << "\n";
        std::cout << "  max S-orth defect: " << max_sorth << "\n";
        std::cout << "  avg iter S-orth  : " << (sum_iter_sorth / ok_cases) << "\n";
        std::cout << "  max iter S-orth  : " << max_iter_sorth << "\n";
    }

    return (ok_cases == static_cast<int>(cases.size())) ? 0 : 2;
}
