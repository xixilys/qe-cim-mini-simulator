#include <systemc.h>

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
        int row = std::stoi(toks[0]) - 1;
        int col = std::stoi(toks[1]) - 1;
        out[row + col * n] = std::complex<double>(std::stod(toks[2]), std::stod(toks[3]));
    }
    return out;
}

static bool load_first_qe_case(std::vector<std::complex<double>>& h,
                               std::vector<std::complex<double>>& s,
                               int& n, int& m) {
    std::string default_dirs =
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump";
    std::vector<std::string> dirs = split_csv_list(env_string("ITER_SUBSPACE_DIRS", default_dirs));
    std::regex h_pat(R"((.+)_H_call(\d+)_n(\d+)_m(\d+)\.csv$)");

    for (const auto& dir : dirs) {
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
            n = std::stoi(match[3].str());
            m = std::stoi(match[4].str());
            std::filesystem::path s_path = root / (prefix + "_S_call" + call_id + "_n" +
                                                   std::to_string(n) + "_m" + std::to_string(m) + ".csv");
            if (!std::filesystem::exists(s_path)) continue;

            h = load_dump_csv(path.string(), n);
            s = load_dump_csv(s_path.string(), n);
            return true;
        }
    }
    return false;
}

static std::vector<std::complex<double>> random_dense(int rows, int cols, std::mt19937& gen, double scale) {
    std::uniform_real_distribution<double> dist(-scale, scale);
    std::vector<std::complex<double>> out(rows * cols, std::complex<double>(0.0, 0.0));
    for (int j = 0; j < cols; j++) {
        for (int i = 0; i < rows; i++) out[i + j * rows] = std::complex<double>(dist(gen), dist(gen));
    }
    return out;
}

static std::vector<std::complex<double>> matmul(const std::vector<std::complex<double>>& a,
                                                const std::vector<std::complex<double>>& b,
                                                int m, int k, int n) {
    std::vector<std::complex<double>> c(m * n, std::complex<double>(0.0, 0.0));
    for (int j = 0; j < n; j++) {
        for (int p = 0; p < k; p++) {
            std::complex<double> bp = b[p + j * k];
            for (int i = 0; i < m; i++) c[i + j * m] += a[i + p * m] * bp;
        }
    }
    return c;
}

static std::vector<std::complex<double>> conj_transpose(const std::vector<std::complex<double>>& a, int rows, int cols) {
    std::vector<std::complex<double>> out(cols * rows, std::complex<double>(0.0, 0.0));
    for (int j = 0; j < cols; j++) {
        for (int i = 0; i < rows; i++) out[j + i * cols] = std::conj(a[i + j * rows]);
    }
    return out;
}

static std::vector<std::complex<double>> random_hermitian(int n, std::mt19937& gen) {
    std::uniform_real_distribution<double> dist(-0.3, 0.3);
    std::vector<std::complex<double>> h(n * n, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < n; i++) {
        h[i + i * n] = std::complex<double>(1.0 + dist(gen), 0.0);
        for (int j = i + 1; j < n; j++) {
            std::complex<double> z(dist(gen), dist(gen));
            h[i + j * n] = z;
            h[j + i * n] = std::conj(z);
        }
    }
    return h;
}

static std::vector<std::complex<double>> random_hpd(int n, std::mt19937& gen) {
    std::vector<std::complex<double>> b = random_dense(n, n, gen, 0.2);
    std::vector<std::complex<double>> bh = conj_transpose(b, n, n);
    std::vector<std::complex<double>> s = matmul(bh, b, n, n, n);
    for (int i = 0; i < n; i++) s[i + i * n] += std::complex<double>(1.5, 0.0);
    return s;
}

static double residual_norm(const std::vector<std::complex<double>>& h,
                            const std::vector<std::complex<double>>& s,
                            const std::vector<std::complex<double>>& v,
                            int n, int col, double eval) {
    double sq = 0.0;
    double denom = 0.0;
    for (int i = 0; i < n; i++) {
        std::complex<double> hv(0.0, 0.0);
        std::complex<double> sv(0.0, 0.0);
        for (int j = 0; j < n; j++) {
            hv += h[i + j * n] * v[j + col * n];
            sv += s[i + j * n] * v[j + col * n];
        }
        std::complex<double> diff = hv - eval * sv;
        sq += std::norm(diff);
        denom += std::norm(hv) + std::norm(eval * sv);
    }
    return std::sqrt(sq / std::max(1e-30, denom));
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    int n = env_int("ITER_N", 16);
    int m = env_int("ITER_M", 8);
    int steps = env_int("ITER_STEPS", 6);
    bool use_qe_case = env_int("ITER_USE_QE_CASE", 1) != 0;
    int micro_solver_mode = env_int("ITER_MICRO_SOLVER_MODE", REDUCED_SOLVER_CHOLESKY_JACOBI);
    bool use_history_p = env_int("ITER_USE_HISTORY_P", 0) != 0;

    std::mt19937 gen(20260312);
    std::vector<std::complex<double>> h;
    std::vector<std::complex<double>> s;
    const bool loaded_qe_case = use_qe_case && load_first_qe_case(h, s, n, m);
    if (!loaded_qe_case) {
        h = random_hermitian(n, gen);
        s = random_hpd(n, gen);
    }
    std::vector<std::complex<double>> x0 = random_dense(n, m, gen, 0.2);

    std::vector<double> h_real(n * n), h_imag(n * n), s_real(n * n), s_imag(n * n);
    std::vector<double> x0_real(n * m), x0_imag(n * m), evals(m, 0.0), vec_real(n * m), vec_imag(n * m);
    for (int i = 0; i < n * n; i++) {
        h_real[i] = h[i].real();
        h_imag[i] = h[i].imag();
        s_real[i] = s[i].real();
        s_imag[i] = s[i].imag();
    }
    for (int i = 0; i < n * m; i++) {
        x0_real[i] = x0[i].real();
        x0_imag[i] = x0[i].imag();
    }

    sc_clock clk("clk", 1, SC_NS);
    sc_signal<bool> rst_n, start, busy, done;
    sc_signal<bool> sig_use_history_p;
    sc_signal<int> sig_n, sig_m, sig_steps, sig_micro_mode, cycles, hx_ops, sx_ops, qhqx_ops;
    sc_signal<int> ortho_ops, basis_update_ops, reduced_build_ops;
    sc_signal<int> reduced_cholesky_ops, reduced_standardize_ops, reduced_jacobi_ops, reduced_backtransform_ops;
    sc_signal<int> row_hits, row_misses, residue_encodes, crt_reconstructs;

    Iterative_Subspace_Engine engine("ITER_ENGINE");
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
    engine.h_real = h_real.data();
    engine.h_imag = h_imag.data();
    engine.s_real = s_real.data();
    engine.s_imag = s_imag.data();
    engine.x0_real = x0_real.data();
    engine.x0_imag = x0_imag.data();
    engine.out_eval = evals.data();
    engine.out_vec_real = vec_real.data();
    engine.out_vec_imag = vec_imag.data();

    rst_n.write(false);
    start.write(false);
    sig_n.write(n);
    sig_m.write(m);
    sig_steps.write(steps);
    sig_micro_mode.write(micro_solver_mode);
    sig_use_history_p.write(use_history_p);
    sc_start(5, SC_NS);
    rst_n.write(true);
    sc_start(5, SC_NS);

    start.write(true);
    sc_start(1, SC_NS);
    start.write(false);
    while (!done.read()) sc_start(1, SC_NS);
    sc_start(1, SC_NS);

    std::vector<std::complex<double>> vec(n * m, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < n * m; i++) vec[i] = std::complex<double>(vec_real[i], vec_imag[i]);

    double max_res = 0.0;
    for (int col = 0; col < m; col++) max_res = std::max(max_res, residual_norm(h, s, vec, n, col, evals[col]));

    std::cout << "=== Iterative Subspace Engine Test ===\n";
    std::cout << "n=" << n << " m=" << m << " steps=" << steps << "\n";
    std::cout << "input_source=" << (loaded_qe_case ? "qe_dump" : "random_fallback") << "\n";
    std::cout << "micro_solver_mode=" << micro_solver_mode << "\n";
    std::cout << "use_history_p=" << (use_history_p ? 1 : 0) << "\n";
    std::cout << "cycles=" << cycles.read()
              << " hx_ops=" << hx_ops.read()
              << " sx_ops=" << sx_ops.read()
              << " qhqx_ops=" << qhqx_ops.read()
              << " ortho_ops=" << ortho_ops.read()
              << " basis_update_ops=" << basis_update_ops.read()
              << " reduced_build_ops=" << reduced_build_ops.read()
              << " reduced_cholesky_ops=" << reduced_cholesky_ops.read()
              << " reduced_standardize_ops=" << reduced_standardize_ops.read()
              << " reduced_jacobi_ops=" << reduced_jacobi_ops.read()
              << " reduced_backtransform_ops=" << reduced_backtransform_ops.read() << "\n";
    std::cout << "row_hits=" << row_hits.read()
              << " row_misses=" << row_misses.read()
              << " residue_encodes=" << residue_encodes.read()
              << " crt_reconstructs=" << crt_reconstructs.read() << "\n";
    std::cout << std::scientific << std::setprecision(6);
    std::cout << "max_residual=" << max_res << "\n";
    std::cout << "lowest evals:";
    for (int i = 0; i < std::min(m, 4); i++) std::cout << " " << evals[i];
    std::cout << "\n";

    return (std::isfinite(max_res) && max_res < 5e-1) ? 0 : 2;
}
