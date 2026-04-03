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

struct ErrorStats {
    double rms_abs = 0.0;
    double rel_frob = 0.0;
    double max_abs = 0.0;
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

static bool load_first_qe_case(std::vector<std::complex<double>>& h,
                               std::vector<std::complex<double>>& s,
                               int& n, int& m) {
    const std::string default_dirs =
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_medium_dump,"
        "/Volumes/remote/phd/year_2/project/dft加速/tmp_qe_si_large_dump";
    const std::vector<std::string> dirs = split_csv_list(env_string("ITER_SUBSPACE_DIRS", default_dirs));
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
            n = std::stoi(match[3].str());
            m = std::stoi(match[4].str());
            const std::filesystem::path s_path = root / (prefix + "_S_call" + call_id + "_n" +
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
    for (int col = 0; col < cols; col++) {
        for (int row = 0; row < rows; row++) out[row + col * rows] = std::complex<double>(dist(gen), dist(gen));
    }
    return out;
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

static std::vector<std::complex<double>> random_hpd(int n, std::mt19937& gen) {
    const std::vector<std::complex<double>> b = random_dense(n, n, gen, 0.2);
    const std::vector<std::complex<double>> bh = conj_transpose(b, n, n);
    std::vector<std::complex<double>> s = matmul(bh, b, n, n, n);
    for (int i = 0; i < n; i++) s[i + i * n] += std::complex<double>(1.5, 0.0);
    return s;
}

static double frob_norm(const std::vector<std::complex<double>>& a) {
    long double acc = 0.0L;
    for (const auto& z : a) acc += std::norm(z);
    return std::sqrt(static_cast<double>(acc));
}

static ErrorStats compare_complex(const std::vector<std::complex<double>>& ref,
                                  const std::vector<std::complex<double>>& test) {
    ErrorStats out;
    long double sq = 0.0L;
    for (size_t i = 0; i < ref.size(); i++) {
        const double ab = std::abs(test[i] - ref[i]);
        sq += static_cast<long double>(ab) * static_cast<long double>(ab);
        out.max_abs = std::max(out.max_abs, ab);
    }
    out.rms_abs = std::sqrt(static_cast<double>(sq / std::max<size_t>(1, ref.size())));
    out.rel_frob = std::sqrt(static_cast<double>(sq)) / std::max(1e-30, frob_norm(ref));
    return out;
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    int n = env_int("ITER_N", 16);
    int m = env_int("ITER_M", 8);
    const bool use_qe_case = env_int("ITER_USE_QE_CASE", 1) != 0;

    std::mt19937 gen(20260312);
    std::vector<std::complex<double>> h;
    std::vector<std::complex<double>> s;
    if (!use_qe_case || !load_first_qe_case(h, s, n, m)) {
        h = random_hermitian(n, gen);
        s = random_hpd(n, gen);
    }
    const std::vector<std::complex<double>> x = random_dense(n, m, gen, 0.2);

    std::vector<double> h_real(n * n), h_imag(n * n), s_real(n * n), s_imag(n * n);
    for (int i = 0; i < n * n; i++) {
        h_real[i] = h[i].real();
        h_imag[i] = h[i].imag();
        s_real[i] = s[i].real();
        s_imag[i] = s[i].imag();
    }

    Matrix_Resident_Tile tile;
    tile.bind({h_real.data(), h_imag.data()}, {s_real.data(), s_imag.data()}, n);

    IterativeStats stats;
    const std::vector<std::complex<double>> hx = tile.compute_hx(x, m, stats);
    const std::vector<std::complex<double>> sx = tile.compute_sx(x, m, stats);
    const std::vector<std::complex<double>> hx_reuse = tile.compute_hx(x, m, stats);
    const std::vector<std::complex<double>> sx_reuse = tile.compute_sx(x, m, stats);
    const std::vector<std::complex<double>> hx_ref = matmul(h, x, n, n, m);
    const std::vector<std::complex<double>> sx_ref = matmul(s, x, n, n, m);

    const ErrorStats hx_err = compare_complex(hx_ref, hx);
    const ErrorStats sx_err = compare_complex(sx_ref, sx);
    const ErrorStats hx_reuse_err = compare_complex(hx_ref, hx_reuse);
    const ErrorStats sx_reuse_err = compare_complex(sx_ref, sx_reuse);
    const double max_rel = std::max(std::max(hx_err.rel_frob, sx_err.rel_frob),
                                    std::max(hx_reuse_err.rel_frob, sx_reuse_err.rel_frob));

    std::cout << "=== Iterative Tile GEMM Test ===\n";
    std::cout << "n=" << n << " m=" << m << "\n";
    std::cout << std::scientific << std::setprecision(6);
    std::cout << "hx_rel_frob=" << hx_err.rel_frob
              << " hx_rms_abs=" << hx_err.rms_abs
              << " hx_max_abs=" << hx_err.max_abs << "\n";
    std::cout << "sx_rel_frob=" << sx_err.rel_frob
              << " sx_rms_abs=" << sx_err.rms_abs
              << " sx_max_abs=" << sx_err.max_abs << "\n";
    std::cout << "hx_reuse_rel_frob=" << hx_reuse_err.rel_frob
              << " sx_reuse_rel_frob=" << sx_reuse_err.rel_frob << "\n";
    std::cout << "row_hits=" << stats.row_buffer_hits
              << " row_misses=" << stats.row_buffer_misses
              << " residue_encodes=" << stats.residue_encodes
              << " crt_reconstructs=" << stats.crt_reconstructs << "\n";

    return (std::isfinite(max_rel) && max_rel < 1e-12) ? 0 : 2;
}
