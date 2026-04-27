#include "iterative_subspace_engine.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>

namespace {

using i128 = __int128_t;
using u128 = __uint128_t;

static constexpr std::array<int64_t, 16> k_moduli = {
    251, 241, 239, 233, 229, 227, 223, 211,
    199, 197, 193, 191, 181, 179, 173, 167
};
static constexpr long double k_scale_cap = 63.0L;

static std::vector<std::complex<double>> to_complex_cols(const double* real, const double* imag, int rows, int cols) {
    std::vector<std::complex<double>> out(rows * cols, std::complex<double>(0.0, 0.0));
    for (int j = 0; j < cols; j++) {
        for (int i = 0; i < rows; i++) {
            int idx = i + j * rows;
            out[idx] = std::complex<double>(real[idx], imag ? imag[idx] : 0.0);
        }
    }
    return out;
}

static int clamp_cols(int cols, int n) {
    if (cols < 1) return 1;
    if (cols > n) return n;
    return cols;
}

static int floor_log2_ld(long double value) {
    if (!(value > 0.0L) || !std::isfinite(value)) return 0;
    int exp = 0;
    std::frexpl(value, &exp);
    return exp - 1;
}

static int choose_scale_shift(double max_abs) {
    if (!(max_abs > 0.0) || !std::isfinite(max_abs)) return 0;
    return floor_log2_ld(k_scale_cap / static_cast<long double>(max_abs));
}

static int choose_extra_shift(int inner_dim) {
    long double prod = 1.0L;
    for (int64_t mod : k_moduli) prod *= static_cast<long double>(mod);
    const long double max_cbar = std::max(1.0L, 2.0L * static_cast<long double>(inner_dim) * k_scale_cap * k_scale_cap);
    const long double target = std::sqrt((prod / 8.0L) / max_cbar);
    if (!(target > 1.0L)) return 0;
    return floor_log2_ld(target);
}

static bool quantize_to_i64(double value, int shift, int64_t& out) {
    const long double scaled = std::ldexpl(static_cast<long double>(value), shift);
    if (!std::isfinite(scaled)) return false;
    const long double q = std::truncl(scaled);
    if (q > static_cast<long double>(std::numeric_limits<int64_t>::max())) return false;
    if (q < static_cast<long double>(std::numeric_limits<int64_t>::min())) return false;
    out = static_cast<int64_t>(q);
    return true;
}

static long double i128_to_long_double(i128 value) {
    const bool neg = value < 0;
    const u128 mag = neg ? static_cast<u128>(-(value + 1)) + 1 : static_cast<u128>(value);
    const uint64_t lo = static_cast<uint64_t>(mag);
    const uint64_t hi = static_cast<uint64_t>(mag >> 64);
    long double out = std::ldexpl(static_cast<long double>(hi), 64);
    out += static_cast<long double>(lo);
    return neg ? -out : out;
}

static int64_t mod_pos(int64_t value, int64_t mod) {
    int64_t out = value % mod;
    return (out < 0) ? (out + mod) : out;
}

static int64_t mod_mul(int64_t a, int64_t b, int64_t mod) {
    return static_cast<int64_t>((static_cast<i128>(a) * static_cast<i128>(b)) % mod);
}

static int64_t egcd_inv(int64_t a, int64_t mod) {
    int64_t t = 0;
    int64_t new_t = 1;
    int64_t r = mod;
    int64_t new_r = a;
    while (new_r != 0) {
        int64_t q = r / new_r;
        int64_t tmp_t = t - q * new_t;
        t = new_t;
        new_t = tmp_t;
        int64_t tmp_r = r - q * new_r;
        r = new_r;
        new_r = tmp_r;
    }
    if (r != 1) return 0;
    if (t < 0) t += mod;
    return t;
}

static i128 crt_reconstruct_signed(const std::vector<int64_t>& residues) {
    i128 value = mod_pos(residues[0], k_moduli[0]);
    i128 prod = k_moduli[0];
    for (size_t i = 1; i < k_moduli.size(); i++) {
        const int64_t mod = k_moduli[i];
        const int64_t value_mod = static_cast<int64_t>(value % mod);
        const int64_t delta = mod_pos(residues[i] - value_mod, mod);
        const int64_t prod_mod = static_cast<int64_t>(prod % mod);
        const int64_t inv = egcd_inv(prod_mod, mod);
        const int64_t step = mod_mul(delta, inv, mod);
        value += prod * step;
        prod *= mod;
    }
    const i128 half = prod / 2;
    if (value > half) value -= prod;
    return value;
}

static EncodedComplexRow encode_row_fixed(const std::vector<double>& row_real,
                                          const std::vector<double>& row_imag,
                                          int shift) {
    EncodedComplexRow encoded;
    encoded.n = static_cast<int>(row_real.size());
    encoded.shift = shift;
    encoded.real_residues.assign(static_cast<int>(k_moduli.size()) * encoded.n, 0);
    encoded.imag_residues.assign(static_cast<int>(k_moduli.size()) * encoded.n, 0);
    for (int k = 0; k < encoded.n; k++) {
        int64_t qr = 0;
        int64_t qi = 0;
        quantize_to_i64(row_real[k], encoded.shift, qr);
        quantize_to_i64(row_imag[k], encoded.shift, qi);
        for (size_t l = 0; l < k_moduli.size(); l++) {
            encoded.real_residues[l * encoded.n + k] = mod_pos(qr, k_moduli[l]);
            encoded.imag_residues[l * encoded.n + k] = mod_pos(qi, k_moduli[l]);
        }
    }
    return encoded;
}

static EncodedVectorBlock encode_vector_block(const std::vector<std::complex<double>>& x,
                                              int n, int cols,
                                              const std::vector<int>& col_shifts) {
    EncodedVectorBlock encoded;
    encoded.n = n;
    encoded.cols = cols;
    encoded.col_shifts = col_shifts;
    encoded.real_residues.assign(static_cast<int>(k_moduli.size()) * n * cols, 0);
    encoded.imag_residues.assign(static_cast<int>(k_moduli.size()) * n * cols, 0);
    for (int col = 0; col < cols; col++) {
        for (int row = 0; row < n; row++) {
            const int idx = row + col * n;
            int64_t qr = 0;
            int64_t qi = 0;
            quantize_to_i64(x[idx].real(), encoded.col_shifts[col], qr);
            quantize_to_i64(x[idx].imag(), encoded.col_shifts[col], qi);
            for (size_t l = 0; l < k_moduli.size(); l++) {
                const int base = static_cast<int>(l) * n * cols + idx;
                encoded.real_residues[base] = mod_pos(qr, k_moduli[l]);
                encoded.imag_residues[base] = mod_pos(qi, k_moduli[l]);
            }
        }
    }
    return encoded;
}

static void write_back_complex_cols(const std::vector<std::complex<double>>& in,
                                    double* real, double* imag, int rows, int cols) {
    for (int j = 0; j < cols; j++) {
        for (int i = 0; i < rows; i++) {
            int idx = i + j * rows;
            real[idx] = in[idx].real();
            imag[idx] = in[idx].imag();
        }
    }
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

static double column_norm_sq(const std::vector<std::complex<double>>& a, int rows, int col) {
    long double acc = 0.0L;
    for (int i = 0; i < rows; i++) acc += std::norm(a[i + col * rows]);
    return static_cast<double>(acc);
}

static std::vector<int> top_k_columns(const std::vector<double>& score, int keep) {
    keep = std::min(keep, static_cast<int>(score.size()));
    if (keep <= 0) return {};
    std::vector<int> idx(score.size(), 0);
    for (size_t i = 0; i < idx.size(); i++) idx[i] = static_cast<int>(i);
    std::partial_sort(idx.begin(), idx.begin() + keep, idx.end(),
                      [&](int lhs, int rhs) { return score[lhs] > score[rhs]; });
    idx.resize(keep);
    std::sort(idx.begin(), idx.end());
    return idx;
}

static std::vector<std::complex<double>> gather_columns(const std::vector<std::complex<double>>& a,
                                                        int rows, const std::vector<int>& cols) {
    std::vector<std::complex<double>> out(rows * static_cast<int>(cols.size()), std::complex<double>(0.0, 0.0));
    for (size_t c = 0; c < cols.size(); c++) {
        const int src_col = cols[c];
        for (int i = 0; i < rows; i++) out[i + static_cast<int>(c) * rows] = a[i + src_col * rows];
    }
    return out;
}

static void append_columns(std::vector<std::complex<double>>& dst, int rows,
                           const std::vector<std::complex<double>>& src, int src_cols) {
    const int old_cols = static_cast<int>(dst.size()) / rows;
    dst.resize(rows * (old_cols + src_cols), std::complex<double>(0.0, 0.0));
    for (int col = 0; col < src_cols; col++) {
        for (int row = 0; row < rows; row++) dst[row + (old_cols + col) * rows] = src[row + col * rows];
    }
}

static std::vector<double> residual_column_scores(const std::vector<std::complex<double>>& hx,
                                                  const std::vector<std::complex<double>>& sx,
                                                  const std::vector<double>& theta,
                                                  int n, int cols) {
    std::vector<double> score(cols, 0.0);
    for (int col = 0; col < cols; col++) {
        long double acc = 0.0L;
        for (int i = 0; i < n; i++) {
            const std::complex<double> r = hx[i + col * n] - theta[col] * sx[i + col * n];
            acc += std::norm(r);
        }
        score[col] = static_cast<double>(acc);
    }
    return score;
}

static void project_out_current_block(const std::vector<std::complex<double>>& s,
                                      std::vector<std::complex<double>>& p,
                                      const std::vector<std::complex<double>>& x,
                                      int n, int m) {
    for (int col = 0; col < m; col++) {
        for (int basis = 0; basis < m; basis++) {
            std::complex<double> proj(0.0, 0.0);
            for (int i = 0; i < n; i++) {
                std::complex<double> sp(0.0, 0.0);
                for (int j = 0; j < n; j++) sp += s[i + j * n] * p[j + col * n];
                proj += std::conj(x[i + basis * n]) * sp;
            }
            for (int i = 0; i < n; i++) p[i + col * n] -= x[i + basis * n] * proj;
        }
    }
}

static std::complex<double> metric_dot(const std::vector<std::complex<double>>& s,
                                       const std::vector<std::complex<double>>& x,
                                       int n, int c0, int c1) {
    std::complex<double> acc(0.0, 0.0);
    for (int i = 0; i < n; i++) {
        std::complex<double> sx(0.0, 0.0);
        for (int j = 0; j < n; j++) sx += s[i + j * n] * x[j + c1 * n];
        acc += std::conj(x[i + c0 * n]) * sx;
    }
    return acc;
}

static void s_orthonormalize(const std::vector<std::complex<double>>& s,
                             std::vector<std::complex<double>>& x, int n, int m) {
    const double eps = 1e-30;
    for (int c = 0; c < m; c++) {
        for (int p = 0; p < c; p++) {
            std::complex<double> proj = metric_dot(s, x, n, p, c);
            for (int i = 0; i < n; i++) x[i + c * n] -= x[i + p * n] * proj;
        }
        double nrm = std::sqrt(std::max(eps, metric_dot(s, x, n, c, c).real()));
        for (int i = 0; i < n; i++) x[i + c * n] /= nrm;
    }
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

static bool normalize_generalized_columns(const std::vector<std::complex<double>>& b,
                                          int k,
                                          std::vector<std::complex<double>>& z) {
    const double eps = 1e-30;
    for (int col = 0; col < k; col++) {
        std::complex<long double> acc(0.0L, 0.0L);
        for (int i = 0; i < k; i++) {
            std::complex<long double> bz(0.0L, 0.0L);
            for (int j = 0; j < k; j++) {
                const std::complex<double> bij = b[i + j * k];
                bz += std::complex<long double>(bij.real(), bij.imag()) *
                      std::complex<long double>(z[j + col * k].real(), z[j + col * k].imag());
            }
            const std::complex<long double> zi(z[i + col * k].real(), z[i + col * k].imag());
            acc += std::conj(zi) * bz;
        }
        const double norm = std::sqrt(std::max(eps, static_cast<double>(acc.real())));
        if (!std::isfinite(norm) || !(norm > 0.0)) return false;
        for (int i = 0; i < k; i++) z[i + col * k] /= norm;
    }
    return true;
}

static int clamp_reduced_solver_mode(int mode) {
    if (mode == REDUCED_SOLVER_HYBRID) return REDUCED_SOLVER_HYBRID;
    if (mode == REDUCED_SOLVER_BINV_JACOBI) return REDUCED_SOLVER_BINV_JACOBI;
    return REDUCED_SOLVER_CHOLESKY_JACOBI;
}

static int select_runtime_solver_mode(int requested_mode, bool history_enabled, bool expanded_subspace) {
    const int clamped = clamp_reduced_solver_mode(requested_mode);
    if (clamped != REDUCED_SOLVER_HYBRID) return clamped;
    if (history_enabled) return REDUCED_SOLVER_CHOLESKY_JACOBI;
    return expanded_subspace ? REDUCED_SOLVER_CHOLESKY_JACOBI : REDUCED_SOLVER_BINV_JACOBI;
}

static bool solve_binv_jacobi_approx(std::vector<std::complex<double>> a,
                                     std::vector<std::complex<double>> b,
                                     int k,
                                     std::vector<double>& evals,
                                     std::vector<std::complex<double>>& z,
                                     IterativeStats& stats) {
    stats.reduced_standardize_ops++;
    stats.cycles += std::max(1, (k * k * std::max(1, k) + 15) / 16);

    for (int i = 0; i < k; i++) b[i + i * k] += std::complex<double>(1e-12, 0.0);

    std::vector<std::complex<double>> binv_a(k * k, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < k; col++) {
        std::vector<std::complex<double>> rhs(k, std::complex<double>(0.0, 0.0));
        for (int i = 0; i < k; i++) rhs[i] = a[i + col * k];

        std::vector<std::complex<double>> m = b;
        for (int piv = 0; piv < k; piv++) {
            int best = piv;
            double best_abs = std::abs(m[piv + piv * k]);
            for (int row = piv + 1; row < k; row++) {
                const double v = std::abs(m[row + piv * k]);
                if (v > best_abs) {
                    best = row;
                    best_abs = v;
                }
            }
            if (best_abs < 1e-18) return false;
            if (best != piv) {
                for (int c = piv; c < k; c++) std::swap(m[piv + c * k], m[best + c * k]);
                std::swap(rhs[piv], rhs[best]);
            }

            const std::complex<double> diag = m[piv + piv * k];
            for (int c = piv; c < k; c++) m[piv + c * k] /= diag;
            rhs[piv] /= diag;
            for (int row = 0; row < k; row++) {
                if (row == piv) continue;
                const std::complex<double> factor = m[row + piv * k];
                if (std::abs(factor) < 1e-18) continue;
                for (int c = piv; c < k; c++) m[row + c * k] -= factor * m[piv + c * k];
                rhs[row] -= factor * rhs[piv];
            }
        }
        for (int i = 0; i < k; i++) binv_a[i + col * k] = rhs[i];
    }

    hermitianize_col_major(binv_a, k);
    Hermitian_Jacobi_Unit jacobi;
    if (!jacobi.diagonalize(binv_a, k, evals, z, stats)) return false;

    std::vector<std::complex<double>> metric = b;
    hermitianize_col_major(metric, k);
    return normalize_generalized_columns(metric, k, z);
}

} // namespace

void Row_Residue_Buffer::configure(int matrix_count_in, int rows) {
    matrix_count = std::max(0, matrix_count_in);
    rows_per_matrix = std::max(0, rows);
    entries.assign(matrix_count * rows_per_matrix, Entry{});
}

void Complex_Row_Bank::load(const ComplexDenseView& view, int n_dim) {
    n = n_dim;
    real_bank.assign(n * n, 0.0);
    imag_bank.assign(n * n, 0.0);
    row_abs_max.assign(n, 0.0);
    for (int col = 0; col < n; col++) {
        for (int row = 0; row < n; row++) {
            int idx = row + col * n;
            real_bank[idx] = view.real ? view.real[idx] : 0.0;
            imag_bank[idx] = view.imag ? view.imag[idx] : 0.0;
            row_abs_max[row] = std::max(row_abs_max[row], std::abs(real_bank[idx]));
            row_abs_max[row] = std::max(row_abs_max[row], std::abs(imag_bank[idx]));
        }
    }
}

void Complex_Row_Bank::read_row(int row, std::vector<double>& out_real, std::vector<double>& out_imag) const {
    out_real.assign(n, 0.0);
    out_imag.assign(n, 0.0);
    for (int col = 0; col < n; col++) {
        int idx = row + col * n;
        out_real[col] = real_bank[idx];
        out_imag[col] = imag_bank[idx];
    }
}

double Complex_Row_Bank::row_max_abs(int row) const {
    if (row < 0 || row >= n) return 0.0;
    return row_abs_max[row];
}

void Row_Residue_Buffer::clear() {
    for (auto& entry : entries) entry = Entry{};
}

bool Row_Residue_Buffer::lookup(int matrix_tag, int row, int shift, EncodedComplexRow& encoded) const {
    if (matrix_tag < 0 || matrix_tag >= matrix_count) return false;
    if (row < 0 || row >= rows_per_matrix) return false;
    const Entry& entry = entries[matrix_tag * rows_per_matrix + row];
    if (!entry.valid || entry.shift != shift) return false;
    encoded = entry.encoded;
    return true;
}

void Row_Residue_Buffer::fill(int matrix_tag, int row, int shift, const EncodedComplexRow& encoded) {
    if (matrix_tag < 0 || matrix_tag >= matrix_count) return;
    if (row < 0 || row >= rows_per_matrix) return;
    Entry& entry = entries[matrix_tag * rows_per_matrix + row];
    entry.valid = true;
    entry.shift = shift;
    entry.encoded = encoded;
}

EncodedComplexRow Mod_Encode_Unit::encode(const std::vector<double>& row_real,
                                          const std::vector<double>& row_imag,
                                          int shift) const {
    return encode_row_fixed(row_real, row_imag, shift);
}

void Residue_3M_MAC::accumulate_row_block(const EncodedComplexRow& encoded_row,
                                          const EncodedVectorBlock& encoded_x,
                                          int n, int cols, int row,
                                          IterativeStats& stats,
                                          std::vector<std::complex<double>>& out) const {
    for (int col = 0; col < cols; col++) {
        std::vector<int64_t> acc_real_mod(k_moduli.size(), 0);
        std::vector<int64_t> acc_imag_mod(k_moduli.size(), 0);
        for (size_t l = 0; l < k_moduli.size(); l++) {
            const int64_t mod = k_moduli[l];
            int64_t sum_real = 0;
            int64_t sum_imag = 0;
            for (int k = 0; k < n; k++) {
                const int row_idx = static_cast<int>(l) * encoded_row.n + k;
                const int x_idx = static_cast<int>(l) * n * cols + k + col * n;
                const int64_t ar = encoded_row.real_residues[row_idx];
                const int64_t ai = encoded_row.imag_residues[row_idx];
                const int64_t br = encoded_x.real_residues[x_idx];
                const int64_t bi = encoded_x.imag_residues[x_idx];
                const int64_t p0 = mod_mul(ar, br, mod);
                const int64_t p1 = mod_mul(ai, bi, mod);
                const int64_t p2 = mod_mul(mod_pos(ar + ai, mod), mod_pos(br + bi, mod), mod);
                sum_real = mod_pos(sum_real + p0 - p1, mod);
                sum_imag = mod_pos(sum_imag + p2 - p0 - p1, mod);
            }
            acc_real_mod[l] = sum_real;
            acc_imag_mod[l] = sum_imag;
        }
        const i128 real_fixed = crt_reconstruct_signed(acc_real_mod);
        const i128 imag_fixed = crt_reconstruct_signed(acc_imag_mod);
        const int total_shift = encoded_row.shift + encoded_x.col_shifts[col];
        out[row + col * n] = std::complex<double>(
            static_cast<double>(std::ldexpl(i128_to_long_double(real_fixed), -total_shift)),
            static_cast<double>(std::ldexpl(i128_to_long_double(imag_fixed), -total_shift)));
        stats.crt_reconstructs += 2;
    }
}

void Subspace_Ortho_Unit::orthonormalize(const std::vector<std::complex<double>>& s,
                                         std::vector<std::complex<double>>& x,
                                         int n, int m,
                                         IterativeStats& stats) const {
    stats.ortho_ops++;
    stats.cycles += std::max(1, (n * m * std::max(1, m) + 31) / 32);
    s_orthonormalize(s, x, n, m);
}

std::vector<std::complex<double>> Basis_Update_Unit::apply_transform(const std::vector<std::complex<double>>& basis,
                                                                     const std::vector<std::complex<double>>& coeff,
                                                                     int rows, int in_cols, int out_cols,
                                                                     IterativeStats& stats) const {
    stats.basis_update_ops++;
    stats.cycles += std::max(1, (rows * in_cols * std::max(1, out_cols) + 31) / 32);
    return matmul(basis, coeff, rows, in_cols, out_cols);
}

void Reduced_Projection_Unit::build_projected(const std::vector<std::complex<double>>& q,
                                              const std::vector<std::complex<double>>& hq,
                                              const std::vector<std::complex<double>>& sq,
                                              int n, int k,
                                              std::vector<std::complex<double>>& a,
                                              std::vector<std::complex<double>>& b,
                                              IterativeStats& stats) const {
    stats.reduced_build_ops++;
    stats.cycles += std::max(1, (n * k * std::max(1, k) + 15) / 16);
    a.assign(k * k, std::complex<double>(0.0, 0.0));
    b.assign(k * k, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < k; i++) {
        for (int j = 0; j < k; j++) {
            std::complex<double> ah(0.0, 0.0);
            std::complex<double> bs(0.0, 0.0);
            for (int r = 0; r < n; r++) {
                ah += std::conj(q[r + i * n]) * hq[r + j * n];
                bs += std::conj(q[r + i * n]) * sq[r + j * n];
            }
            a[i + j * k] = ah;
            b[i + j * k] = bs;
        }
    }
}

bool Reduced_Cholesky_Unit::factorize_spd(const std::vector<std::complex<double>>& b,
                                          int k,
                                          std::vector<std::complex<double>>& l,
                                          IterativeStats& stats) const {
    stats.reduced_cholesky_ops++;
    stats.cycles += std::max(1, (k * k * std::max(1, k) + 15) / 16);

    const long double eps = 1e-18L;
    l = b;
    hermitianize_col_major(l, k);
    for (int i = 0; i < k; i++) l[i + i * k] += std::complex<double>(1e-12, 0.0);

    for (int col = 0; col < k; col++) {
        long double diag_acc = l[col + col * k].real();
        for (int p = 0; p < col; p++) diag_acc -= std::norm(l[col + p * k]);
        if (!(diag_acc > eps) || !std::isfinite(static_cast<double>(diag_acc))) return false;

        const double diag = std::sqrt(static_cast<double>(diag_acc));
        l[col + col * k] = std::complex<double>(diag, 0.0);
        for (int row = col + 1; row < k; row++) {
            std::complex<double> acc = l[row + col * k];
            for (int p = 0; p < col; p++) acc -= l[row + p * k] * std::conj(l[col + p * k]);
            l[row + col * k] = acc / diag;
        }
        for (int upper = col + 1; upper < k; upper++) l[col + upper * k] = std::complex<double>(0.0, 0.0);
    }
    return true;
}

bool Reduced_Standardize_Unit::build_standard(const std::vector<std::complex<double>>& a,
                                              const std::vector<std::complex<double>>& l,
                                              int k,
                                              std::vector<std::complex<double>>& c,
                                              IterativeStats& stats) const {
    stats.reduced_standardize_ops++;
    stats.cycles += std::max(1, (2 * k * k * std::max(1, k) + 15) / 16);

    const double eps = 1e-18;
    c = a;
    hermitianize_col_major(c, k);

    for (int col = 0; col < k; col++) {
        for (int row = 0; row < k; row++) {
            std::complex<double> acc = c[row + col * k];
            for (int p = 0; p < row; p++) acc -= l[row + p * k] * c[p + col * k];
            const double diag = l[row + row * k].real();
            if (!(diag > eps)) return false;
            c[row + col * k] = acc / diag;
        }
    }

    for (int row = 0; row < k; row++) {
        for (int col = k - 1; col >= 0; col--) {
            std::complex<double> acc = c[row + col * k];
            for (int p = col + 1; p < k; p++) acc -= c[row + p * k] * std::conj(l[p + col * k]);
            const double diag = l[col + col * k].real();
            if (!(diag > eps)) return false;
            c[row + col * k] = acc / diag;
        }
    }

    hermitianize_col_major(c, k);
    return true;
}

bool Hermitian_Jacobi_Unit::diagonalize(const std::vector<std::complex<double>>& a,
                                        int k,
                                        std::vector<double>& evals,
                                        std::vector<std::complex<double>>& y,
                                        IterativeStats& stats) const {
    stats.reduced_jacobi_ops++;

    static constexpr int k_max_sweeps = 32;
    std::vector<std::complex<double>> work = a;
    hermitianize_col_major(work, k);
    y.assign(k * k, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < k; i++) y[i + i * k] = std::complex<double>(1.0, 0.0);

    int sweeps_used = 0;
    for (int sweep = 0; sweep < k_max_sweeps; sweep++) {
        sweeps_used++;
        double off = 0.0;
        for (int p = 0; p < k; p++) {
            for (int q = p + 1; q < k; q++) off += std::abs(work[p + q * k]);
        }
        if (off < 1e-12) break;

        for (int p = 0; p < k; p++) {
            for (int q = p + 1; q < k; q++) {
                const std::complex<double> apq = work[p + q * k];
                if (std::abs(apq) < 1e-12) continue;

                const double app = work[p + p * k].real();
                const double aqq = work[q + q * k].real();
                const double mag = std::abs(apq);
                const double tau = (aqq - app) / (2.0 * mag);
                const double t = (tau >= 0.0) ? 1.0 / (tau + std::sqrt(1.0 + tau * tau))
                                              : -1.0 / (-tau + std::sqrt(1.0 + tau * tau));
                const double crot = 1.0 / std::sqrt(1.0 + t * t);
                const std::complex<double> srot = (apq / mag) * t * crot;

                for (int idx = 0; idx < k; idx++) {
                    const std::complex<double> wip = work[idx + p * k];
                    const std::complex<double> wiq = work[idx + q * k];
                    work[idx + p * k] = crot * wip - std::conj(srot) * wiq;
                    work[idx + q * k] = srot * wip + crot * wiq;
                }
                for (int idx = 0; idx < k; idx++) {
                    const std::complex<double> wpj = work[p + idx * k];
                    const std::complex<double> wqj = work[q + idx * k];
                    work[p + idx * k] = crot * wpj - srot * wqj;
                    work[q + idx * k] = std::conj(srot) * wpj + crot * wqj;
                }
                for (int idx = 0; idx < k; idx++) {
                    const std::complex<double> yip = y[idx + p * k];
                    const std::complex<double> yiq = y[idx + q * k];
                    y[idx + p * k] = crot * yip - std::conj(srot) * yiq;
                    y[idx + q * k] = srot * yip + crot * yiq;
                }
            }
        }
    }

    stats.cycles += std::max(1, (sweeps_used * k * std::max(1, k - 1) + 7) / 8);

    evals.resize(k);
    for (int i = 0; i < k; i++) evals[i] = work[i + i * k].real();

    std::vector<int> idx(k, 0);
    for (int i = 0; i < k; i++) idx[i] = i;
    std::sort(idx.begin(), idx.end(), [&](int lhs, int rhs) { return evals[lhs] < evals[rhs]; });

    std::vector<double> eval_sorted(k, 0.0);
    std::vector<std::complex<double>> y_sorted(k * k, std::complex<double>(0.0, 0.0));
    for (int col = 0; col < k; col++) {
        eval_sorted[col] = evals[idx[col]];
        for (int row = 0; row < k; row++) y_sorted[row + col * k] = y[row + idx[col] * k];
    }
    evals.swap(eval_sorted);
    y.swap(y_sorted);
    return true;
}

bool Reduced_Backtransform_Unit::apply_inverse_lh(const std::vector<std::complex<double>>& l,
                                                  const std::vector<std::complex<double>>& y,
                                                  const std::vector<std::complex<double>>& b,
                                                  int k,
                                                  std::vector<std::complex<double>>& z,
                                                  IterativeStats& stats) const {
    stats.reduced_backtransform_ops++;
    stats.cycles += std::max(1, (k * k * std::max(1, k) + 15) / 16);

    const double eps = 1e-18;
    z = y;
    for (int col = 0; col < k; col++) {
        for (int row = k - 1; row >= 0; row--) {
            std::complex<double> acc = z[row + col * k];
            for (int p = row + 1; p < k; p++) acc -= std::conj(l[p + row * k]) * z[p + col * k];
            const double diag = l[row + row * k].real();
            if (!(diag > eps)) return false;
            z[row + col * k] = acc / diag;
        }
    }

    std::vector<std::complex<double>> metric = b;
    hermitianize_col_major(metric, k);
    return normalize_generalized_columns(metric, k, z);
}

void Matrix_Resident_Tile::bind(const ComplexDenseView& h_view, const ComplexDenseView& s_view, int n_dim) {
    n = n_dim;
    h_bank.load(h_view, n);
    s_bank.load(s_view, n);
    row_buffer.configure(2, n);
    row_buffer.clear();
}

std::vector<std::complex<double>> Matrix_Resident_Tile::compute_hx(const std::vector<std::complex<double>>& x,
                                                                    int cols, IterativeStats& stats) const {
    stats.hx_ops++;
    stats.cycles += std::max(1, (n * cols + 31) / 32);
    return compute_operator(h_bank, 0, x, cols, stats);
}

std::vector<std::complex<double>> Matrix_Resident_Tile::compute_sx(const std::vector<std::complex<double>>& x,
                                                                    int cols, IterativeStats& stats) const {
    stats.sx_ops++;
    stats.cycles += std::max(1, (n * cols + 31) / 32);
    return compute_operator(s_bank, 1, x, cols, stats);
}

std::vector<std::complex<double>> Matrix_Resident_Tile::compute_operator(const Complex_Row_Bank& bank, int matrix_tag,
                                                                         const std::vector<std::complex<double>>& x,
                                                                         int cols, IterativeStats& stats) const {
    cols = clamp_cols(cols, n);
    std::vector<std::complex<double>> out(n * cols, std::complex<double>(0.0, 0.0));
    std::vector<double> row_real;
    std::vector<double> row_imag;
    EncodedComplexRow encoded;
    std::vector<int> row_shifts(n, 0);
    std::vector<int> col_shifts(cols, 0);
    const int extra_shift = choose_extra_shift(n);

    for (int row = 0; row < n; row++) row_shifts[row] = choose_scale_shift(bank.row_max_abs(row)) + extra_shift;
    for (int col = 0; col < cols; col++) {
        double col_max = 0.0;
        for (int row = 0; row < n; row++) {
            const std::complex<double> v = x[row + col * n];
            col_max = std::max(col_max, std::abs(v.real()));
            col_max = std::max(col_max, std::abs(v.imag()));
        }
        col_shifts[col] = choose_scale_shift(col_max) + extra_shift;
    }
    const EncodedVectorBlock encoded_x = encode_vector_block(x, n, cols, col_shifts);
    for (int row = 0; row < n; row++) {
        if (!row_buffer.lookup(matrix_tag, row, row_shifts[row], encoded)) {
            bank.read_row(row, row_real, row_imag);
            encoded = mod_encode.encode(row_real, row_imag, row_shifts[row]);
            row_buffer.fill(matrix_tag, row, row_shifts[row], encoded);
            stats.row_buffer_misses++;
            stats.residue_encodes++;
            stats.cycles += 1;
        } else {
            stats.row_buffer_hits++;
        }
        mac.accumulate_row_block(encoded, encoded_x, n, cols, row, stats, out);
    }
    return out;
}

bool Reduced_Generalized_MicroSolver::solve_x_subspace(const std::vector<std::complex<double>>& x,
                                                       const std::vector<std::complex<double>>& hx,
                                                       const std::vector<std::complex<double>>& sx,
                                                       int n, int m,
                                                       int solver_mode,
                                                       std::vector<double>& evals,
                                                       std::vector<std::complex<double>>& z,
                                                       IterativeStats& stats) const {
    stats.qhqx_ops++;
    stats.cycles += std::max(1, (m * m + 7) / 8);
    std::vector<std::complex<double>> a;
    std::vector<std::complex<double>> b;
    projector.build_projected(x, hx, sx, n, m, a, b, stats);
    return solve_projected(std::move(a), std::move(b), m, clamp_reduced_solver_mode(solver_mode), evals, z, stats);
}

bool Reduced_Generalized_MicroSolver::solve_q_subspace(const std::vector<std::complex<double>>& q,
                                                       const std::vector<std::complex<double>>& hq,
                                                       const std::vector<std::complex<double>>& sq,
                                                       int n, int q_cols,
                                                       int solver_mode,
                                                       std::vector<double>& evals,
                                                       std::vector<std::complex<double>>& z,
                                                       IterativeStats& stats) const {
    stats.qhqx_ops++;
    stats.cycles += std::max(1, (q_cols * q_cols + 7) / 8);
    std::vector<std::complex<double>> a;
    std::vector<std::complex<double>> b;
    projector.build_projected(q, hq, sq, n, q_cols, a, b, stats);
    return solve_projected(std::move(a), std::move(b), q_cols, clamp_reduced_solver_mode(solver_mode), evals, z, stats);
}

bool Reduced_Generalized_MicroSolver::solve_projected(std::vector<std::complex<double>> a,
                                                      std::vector<std::complex<double>> b,
                                                      int k,
                                                      int solver_mode,
                                                      std::vector<double>& evals,
                                                      std::vector<std::complex<double>>& z,
                                                      IterativeStats& stats) const {
    hermitianize_col_major(a, k);
    hermitianize_col_major(b, k);

    if (solver_mode == REDUCED_SOLVER_BINV_JACOBI) {
        return solve_binv_jacobi_approx(std::move(a), std::move(b), k, evals, z, stats);
    }

    std::vector<std::complex<double>> l;
    std::vector<std::complex<double>> c;
    std::vector<std::complex<double>> y;
    if (!cholesky_unit.factorize_spd(b, k, l, stats)) return false;
    if (!standardize_unit.build_standard(a, l, k, c, stats)) return false;
    if (!jacobi_unit.diagonalize(c, k, evals, y, stats)) return false;
    return backtransform_unit.apply_inverse_lh(l, y, b, k, z, stats);
}

void Iterative_Subspace_Engine::run() {
    busy.write(false);
    done.write(false);
    total_cycles_used.write(0);
    hx_ops_used.write(0);
    sx_ops_used.write(0);
    qhqx_ops_used.write(0);
    ortho_ops_used.write(0);
    basis_update_ops_used.write(0);
    reduced_build_ops_used.write(0);
    reduced_cholesky_ops_used.write(0);
    reduced_standardize_ops_used.write(0);
    reduced_jacobi_ops_used.write(0);
    reduced_backtransform_ops_used.write(0);
    row_buffer_hits_used.write(0);
    row_buffer_misses_used.write(0);
    residue_encodes_used.write(0);
    crt_reconstructs_used.write(0);

    wait();

    while (true) {
        if (!rst_n.read()) {
            busy.write(false);
            done.write(false);
            total_cycles_used.write(0);
            hx_ops_used.write(0);
            sx_ops_used.write(0);
            qhqx_ops_used.write(0);
            ortho_ops_used.write(0);
            basis_update_ops_used.write(0);
            reduced_build_ops_used.write(0);
            reduced_cholesky_ops_used.write(0);
            reduced_standardize_ops_used.write(0);
            reduced_jacobi_ops_used.write(0);
            reduced_backtransform_ops_used.write(0);
            row_buffer_hits_used.write(0);
            row_buffer_misses_used.write(0);
            residue_encodes_used.write(0);
            crt_reconstructs_used.write(0);
            wait();
            continue;
        }

        if (start.read()) {
            busy.write(true);
            done.write(false);

            IterativeConfig cfg;
            cfg.n = matrix_n.read();
            cfg.m = block_m.read();
            cfg.steps = fixed_steps.read();
            const int solver_mode = clamp_reduced_solver_mode(micro_solver_mode.read());
            if (cfg.n < 1) cfg.n = 1;
            if (cfg.m < 1) cfg.m = 1;
            if (cfg.m > cfg.n) cfg.m = cfg.n;
            if (cfg.steps < 1) cfg.steps = 1;

            tile.bind({h_real, h_imag}, {s_real, s_imag}, cfg.n);
            std::vector<std::complex<double>> x = to_complex_cols(x0_real, x0_imag, cfg.n, cfg.m);
            ComplexDenseView s_view{s_real, s_imag};
            std::vector<std::complex<double>> s = to_complex_cols(s_view.real, s_view.imag, cfg.n, cfg.n);
            IterativeStats stats;
            ortho_unit.orthonormalize(s, x, cfg.n, cfg.m, stats);
            std::vector<double> theta(cfg.m, 0.0);
            std::vector<std::complex<double>> p_hist;
            const bool history_enabled = use_history_p.read();

            for (int iter = 0; iter < cfg.steps; iter++) {
                std::vector<std::complex<double>> hx = tile.compute_hx(x, cfg.m, stats);
                std::vector<std::complex<double>> sx = tile.compute_sx(x, cfg.m, stats);

                std::vector<double> theta_x;
                std::vector<std::complex<double>> u_x;
                const int x_solver_mode = select_runtime_solver_mode(solver_mode, history_enabled, false);
                if (!microsolver.solve_x_subspace(x, hx, sx, cfg.n, cfg.m, x_solver_mode, theta_x, u_x, stats)) break;

                std::vector<std::complex<double>> x_rr = update_unit.apply_transform(x, u_x, cfg.n, cfg.m, cfg.m, stats);
                ortho_unit.orthonormalize(s, x_rr, cfg.n, cfg.m, stats);

                hx = tile.compute_hx(x_rr, cfg.m, stats);
                sx = tile.compute_sx(x_rr, cfg.m, stats);

                if (!history_enabled) {
                    const int expand = std::min(cfg.m, cfg.n - cfg.m);
                    if (expand <= 0) {
                        x = x_rr;
                        theta = theta_x;
                        p_hist.clear();
                        continue;
                    }

                    std::vector<std::complex<double>> w(cfg.n * expand, std::complex<double>(0.0, 0.0));
                    for (int col = 0; col < expand; col++) {
                        for (int i = 0; i < cfg.n; i++) w[i + col * cfg.n] = hx[i + col * cfg.n] - theta_x[col] * sx[i + col * cfg.n];
                    }

                    std::vector<std::complex<double>> q(cfg.n * (cfg.m + expand), std::complex<double>(0.0, 0.0));
                    for (int col = 0; col < cfg.m; col++) {
                        for (int i = 0; i < cfg.n; i++) q[i + col * cfg.n] = x_rr[i + col * cfg.n];
                    }
                    for (int col = 0; col < expand; col++) {
                        for (int i = 0; i < cfg.n; i++) q[i + (col + cfg.m) * cfg.n] = w[i + col * cfg.n];
                    }
                    ortho_unit.orthonormalize(s, q, cfg.n, cfg.m + expand, stats);

                    std::vector<std::complex<double>> hq = tile.compute_hx(q, cfg.m + expand, stats);
                    std::vector<std::complex<double>> sq = tile.compute_sx(q, cfg.m + expand, stats);

                    std::vector<double> theta_q;
                    std::vector<std::complex<double>> y_q;
                    const int q_solver_mode = select_runtime_solver_mode(solver_mode, history_enabled, true);
                    if (!microsolver.solve_q_subspace(q, hq, sq, cfg.n, cfg.m + expand, q_solver_mode, theta_q, y_q, stats)) {
                        x = x_rr;
                        theta = theta_x;
                        p_hist.clear();
                        break;
                    }

                    std::vector<std::complex<double>> y_keep((cfg.m + expand) * cfg.m, std::complex<double>(0.0, 0.0));
                    for (int col = 0; col < cfg.m; col++) {
                        for (int row = 0; row < cfg.m + expand; row++) y_keep[row + col * (cfg.m + expand)] = y_q[row + col * (cfg.m + expand)];
                    }
                    x = update_unit.apply_transform(q, y_keep, cfg.n, cfg.m + expand, cfg.m, stats);
                    ortho_unit.orthonormalize(s, x, cfg.n, cfg.m, stats);
                    theta.assign(theta_q.begin(), theta_q.begin() + cfg.m);
                    p_hist.clear();
                    continue;
                }

                const int room = std::max(0, cfg.n - cfg.m);
                if (room <= 0) {
                    x = x_rr;
                    theta = theta_x;
                    p_hist.clear();
                    continue;
                }

                std::vector<std::complex<double>> w_full(cfg.n * cfg.m, std::complex<double>(0.0, 0.0));
                for (int col = 0; col < cfg.m; col++) {
                    for (int i = 0; i < cfg.n; i++) w_full[i + col * cfg.n] = hx[i + col * cfg.n] - theta_x[col] * sx[i + col * cfg.n];
                }
                const std::vector<double> w_score = residual_column_scores(hx, sx, theta_x, cfg.n, cfg.m);

                std::vector<double> p_score(cfg.m, 0.0);
                if (!p_hist.empty()) {
                    for (int col = 0; col < cfg.m; col++) p_score[col] = column_norm_sq(p_hist, cfg.n, col);
                }

                int p_cols = 0;
                if (!p_hist.empty()) p_cols = std::min(cfg.m, std::max(1, room / 4));
                int w_cols = std::min(cfg.m, room - p_cols);
                if (w_cols <= 0) {
                    w_cols = std::min(cfg.m, room);
                    p_cols = 0;
                }
                p_cols = std::min(p_cols, room - w_cols);

                const std::vector<int> w_idx = top_k_columns(w_score, w_cols);
                const std::vector<int> p_idx = top_k_columns(p_score, p_cols);
                const std::vector<std::complex<double>> w = gather_columns(w_full, cfg.n, w_idx);
                const std::vector<std::complex<double>> p = gather_columns(p_hist, cfg.n, p_idx);

                std::vector<std::complex<double>> q = x_rr;
                append_columns(q, cfg.n, w, w_cols);
                append_columns(q, cfg.n, p, p_cols);
                const int q_cols = cfg.m + w_cols + p_cols;
                ortho_unit.orthonormalize(s, q, cfg.n, q_cols, stats);

                std::vector<std::complex<double>> hq = tile.compute_hx(q, q_cols, stats);
                std::vector<std::complex<double>> sq = tile.compute_sx(q, q_cols, stats);

                std::vector<double> theta_q;
                std::vector<std::complex<double>> y_q;
                const int q_solver_mode = select_runtime_solver_mode(solver_mode, history_enabled, true);
                if (!microsolver.solve_q_subspace(q, hq, sq, cfg.n, q_cols, q_solver_mode, theta_q, y_q, stats)) {
                    x = x_rr;
                    theta = theta_x;
                    p_hist.clear();
                    break;
                }

                std::vector<std::complex<double>> y_keep(q_cols * cfg.m, std::complex<double>(0.0, 0.0));
                for (int col = 0; col < cfg.m; col++) {
                    for (int row = 0; row < q_cols; row++) y_keep[row + col * q_cols] = y_q[row + col * q_cols];
                }
                x = update_unit.apply_transform(q, y_keep, cfg.n, q_cols, cfg.m, stats);
                ortho_unit.orthonormalize(s, x, cfg.n, cfg.m, stats);
                p_hist.resize(cfg.n * cfg.m, std::complex<double>(0.0, 0.0));
                for (int col = 0; col < cfg.m; col++) {
                    for (int i = 0; i < cfg.n; i++) p_hist[i + col * cfg.n] = x[i + col * cfg.n] - x_rr[i + col * cfg.n];
                }
                project_out_current_block(s, p_hist, x, cfg.n, cfg.m);
                theta.assign(theta_q.begin(), theta_q.begin() + cfg.m);
            }

            if (out_eval != nullptr) {
                for (int i = 0; i < cfg.m; i++) out_eval[i] = (i < static_cast<int>(theta.size())) ? theta[i] : 0.0;
            }
            if (out_vec_real != nullptr && out_vec_imag != nullptr) write_back_complex_cols(x, out_vec_real, out_vec_imag, cfg.n, cfg.m);

            total_cycles_used.write(stats.cycles);
            hx_ops_used.write(stats.hx_ops);
            sx_ops_used.write(stats.sx_ops);
            qhqx_ops_used.write(stats.qhqx_ops);
            ortho_ops_used.write(stats.ortho_ops);
            basis_update_ops_used.write(stats.basis_update_ops);
            reduced_build_ops_used.write(stats.reduced_build_ops);
            reduced_cholesky_ops_used.write(stats.reduced_cholesky_ops);
            reduced_standardize_ops_used.write(stats.reduced_standardize_ops);
            reduced_jacobi_ops_used.write(stats.reduced_jacobi_ops);
            reduced_backtransform_ops_used.write(stats.reduced_backtransform_ops);
            row_buffer_hits_used.write(stats.row_buffer_hits);
            row_buffer_misses_used.write(stats.row_buffer_misses);
            residue_encodes_used.write(stats.residue_encodes);
            crt_reconstructs_used.write(stats.crt_reconstructs);
            busy.write(false);
            done.write(true);
            wait(1, SC_NS);
            done.write(false);
        }
        wait();
    }
}
