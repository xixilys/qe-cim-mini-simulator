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

using i128 = __int128_t;
using u128 = __uint128_t;

struct ComplexMatrix {
    int rows;
    int cols;
    std::vector<double> real;
    std::vector<double> imag;

    ComplexMatrix(int r = 0, int c = 0) : rows(r), cols(c), real(r * c, 0.0), imag(r * c, 0.0) {}

    inline int idx(int r, int c) const { return r * cols + c; }
};

struct OzakiConfig {
    std::vector<int> moduli;
    int block_n;
};

struct FusedDigitScalarConfig {
    std::vector<int> stored_moduli;
    std::vector<int> promote_g1;
    std::vector<int> promote_g2;
    int redundant_mod;
    int digit_bits;
    int digit_stages;
    int first_promotion_stage;
    int second_promotion_stage;
};

struct BaseExtensionContext {
    std::vector<int> base_moduli;
    int redundant_mod = 0;
    i128 base_product = 1;
    std::vector<std::vector<int>> inv_mod;
};

struct ErrorStats {
    double rms_abs;
    double rel_frob;
    double max_abs;
};

static std::string env_string(const char* name, const std::string& defv) {
    const char* s = std::getenv(name);
    return s ? std::string(s) : defv;
}

static int env_int(const char* name, int defv) {
    const char* s = std::getenv(name);
    return s ? std::atoi(s) : defv;
}

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

static std::vector<int> default_zgemm_moduli() {
    return {251, 241, 239, 233, 229, 227, 223, 211,
            199, 197, 193, 191, 181, 179, 173, 167};
}

static FusedDigitScalarConfig default_fused_digit_scalar_config() {
    return {
        {251, 241, 239, 233, 229, 227, 223, 211},
        {199, 197, 193},
        {191, 181, 179},
        173,
        8,
        7,
        1,
        4
    };
}

static i128 mod_positive(i128 x, i128 p) {
    i128 r = x % p;
    if (r < 0) r += p;
    return r;
}

static long long sym_mod_ll(long long x, int p) {
    long long r = x % p;
    if (r < 0) r += p;
    if (r > p / 2) r -= p;
    return r;
}

static int inverse_mod(int a, int mod) {
    int t = 0, new_t = 1;
    int r = mod, new_r = a % mod;
    while (new_r != 0) {
        int q = r / new_r;
        int tmp_t = t - q * new_t;
        t = new_t;
        new_t = tmp_t;
        int tmp_r = r - q * new_r;
        r = new_r;
        new_r = tmp_r;
    }
    if (r != 1) return 0;
    if (t < 0) t += mod;
    return t;
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

static std::string i128_to_string(i128 value) {
    if (value == 0) return "0";
    bool neg = value < 0;
    u128 mag = neg ? static_cast<u128>(-(value + 1)) + 1 : static_cast<u128>(value);
    std::string out;
    while (mag != 0) {
        out.push_back(static_cast<char>('0' + (mag % 10)));
        mag /= 10;
    }
    if (neg) out.push_back('-');
    std::reverse(out.begin(), out.end());
    return out;
}

static i128 crt_reconstruct_signed(const std::vector<long long>& residues,
                                   const std::vector<int>& moduli);

static std::vector<int> concat_moduli(const std::vector<int>& lhs, const std::vector<int>& rhs) {
    std::vector<int> out = lhs;
    out.insert(out.end(), rhs.begin(), rhs.end());
    return out;
}

static int64_t quantized_mod(int64_t value, int mod) {
    return static_cast<int64_t>(mod_positive(static_cast<i128>(value), static_cast<i128>(mod)));
}

static std::vector<int> msb_twos_complement_digits(int64_t value, int digit_bits, int digit_stages) {
    const int total_bits = digit_bits * digit_stages;
    const u128 mask = (static_cast<u128>(1) << total_bits) - 1;
    const u128 packed = static_cast<u128>(static_cast<uint64_t>(value)) & mask;
    std::vector<int> digits(digit_stages, 0);
    for (int stage = 0; stage < digit_stages; stage++) {
        const int shift = digit_bits * (digit_stages - 1 - stage);
        int digit = static_cast<int>((packed >> shift) & ((static_cast<u128>(1) << digit_bits) - 1));
        if (stage == 0 && digit >= (1 << (digit_bits - 1))) digit -= (1 << digit_bits);
        digits[stage] = digit;
    }
    return digits;
}

static bool quantize_fp64_mantissa(double value, int& shift, int64_t& q) {
    if (value == 0.0) {
        shift = 0;
        q = 0;
        return true;
    }
    if (!std::isfinite(value)) return false;
    int exp = 0;
    std::frexp(std::fabs(value), &exp);
    shift = 53 - exp;
    const long double scaled = std::ldexpl(static_cast<long double>(value), shift);
    const long double q_ld = std::truncl(scaled);
    if (q_ld > static_cast<long double>(std::numeric_limits<int64_t>::max())) return false;
    if (q_ld < static_cast<long double>(std::numeric_limits<int64_t>::min())) return false;
    q = static_cast<int64_t>(q_ld);
    return true;
}

static double random_real_scalar(int exp_span, std::mt19937& gen) {
    std::uniform_real_distribution<double> mant(0.5, 1.0);
    std::uniform_int_distribution<int> expo(-exp_span, exp_span);
    std::uniform_int_distribution<int> sign(0, 1);
    const double mag = std::ldexp(mant(gen), expo(gen));
    return sign(gen) ? mag : -mag;
}

static BaseExtensionContext make_base_extension_context(const std::vector<int>& base_moduli,
                                                       int redundant_mod) {
    BaseExtensionContext ctx;
    ctx.base_moduli = base_moduli;
    ctx.redundant_mod = redundant_mod;
    ctx.base_product = 1;
    for (int mod : base_moduli) ctx.base_product *= static_cast<i128>(mod);
    ctx.inv_mod.assign(base_moduli.size(), std::vector<int>(base_moduli.size(), 0));
    for (size_t i = 0; i < base_moduli.size(); i++) {
        for (size_t j = 0; j < i; j++) {
            ctx.inv_mod[i][j] = inverse_mod(base_moduli[j] % base_moduli[i], base_moduli[i]);
        }
    }
    return ctx;
}

static std::vector<int64_t> mixed_radix_digits(const std::vector<int64_t>& base_residues,
                                               const BaseExtensionContext& ctx) {
    std::vector<int64_t> digits(base_residues.size(), 0);
    for (size_t i = 0; i < base_residues.size(); i++) {
        const int mod = ctx.base_moduli[i];
        int64_t digit = static_cast<int64_t>(mod_positive(base_residues[i], mod));
        for (size_t j = 0; j < i; j++) {
            digit = static_cast<int64_t>(mod_positive(
                static_cast<i128>(digit - digits[j]) * static_cast<i128>(ctx.inv_mod[i][j]), mod));
        }
        digits[i] = digit;
    }
    return digits;
}

static int64_t eval_mixed_radix_mod(const std::vector<int64_t>& digits,
                                    const std::vector<int>& base_moduli,
                                    int target_mod,
                                    int64_t* product_mod_out = nullptr) {
    int64_t acc = 0;
    int64_t product_mod = 1 % target_mod;
    for (size_t i = 0; i < digits.size(); i++) {
        acc = static_cast<int64_t>(mod_positive(static_cast<i128>(acc) +
                                                static_cast<i128>(digits[i]) * static_cast<i128>(product_mod),
                                                target_mod));
        product_mod = static_cast<int64_t>(mod_positive(static_cast<i128>(product_mod) *
                                                        static_cast<i128>(base_moduli[i]),
                                                        target_mod));
    }
    if (product_mod_out) *product_mod_out = product_mod;
    return acc;
}

static std::vector<int64_t> base_extend_residues(const std::vector<int64_t>& base_residues,
                                                 int64_t redundant_residue,
                                                 const BaseExtensionContext& ctx,
                                                 const std::vector<int>& target_moduli) {
    const std::vector<int64_t> digits = mixed_radix_digits(base_residues, ctx);
    int64_t base_product_mod_redundant = 0;
    const int64_t unsigned_mod_redundant =
        eval_mixed_radix_mod(digits, ctx.base_moduli, ctx.redundant_mod, &base_product_mod_redundant);
    const bool negative_value =
        mod_positive(unsigned_mod_redundant, ctx.redundant_mod) != mod_positive(redundant_residue, ctx.redundant_mod);

    std::vector<int64_t> out(target_moduli.size(), 0);
    for (size_t t = 0; t < target_moduli.size(); t++) {
        int64_t base_product_mod_target = 0;
        int64_t value_mod_target =
            eval_mixed_radix_mod(digits, ctx.base_moduli, target_moduli[t], &base_product_mod_target);
        if (negative_value) {
            value_mod_target = static_cast<int64_t>(mod_positive(
                static_cast<i128>(value_mod_target - base_product_mod_target), target_moduli[t]));
        }
        out[t] = value_mod_target;
    }
    return out;
}

static i128 direct_rns_scalar_multiply(int64_t a, int64_t b, const std::vector<int>& moduli) {
    std::vector<long long> residues(moduli.size(), 0);
    for (size_t i = 0; i < moduli.size(); i++) {
        const int mod = moduli[i];
        const int64_t ar = quantized_mod(a, mod);
        const int64_t br = quantized_mod(b, mod);
        residues[i] = static_cast<long long>(mod_positive(static_cast<i128>(ar) * static_cast<i128>(br), mod));
    }
    return crt_reconstruct_signed(residues, moduli);
}

static i128 fused_digit_scalar_multiply(int64_t a, int64_t b,
                                        const FusedDigitScalarConfig& cfg) {
    const std::vector<int> g01 = concat_moduli(cfg.stored_moduli, cfg.promote_g1);
    const std::vector<int> g012 = concat_moduli(g01, cfg.promote_g2);
    const BaseExtensionContext ext_g0 = make_base_extension_context(cfg.stored_moduli, cfg.redundant_mod);
    const BaseExtensionContext ext_g1 = make_base_extension_context(g01, cfg.redundant_mod);

    std::vector<int> active_moduli = cfg.stored_moduli;
    std::vector<int64_t> a_active(active_moduli.size(), 0);
    std::vector<int64_t> u_active(active_moduli.size(), 0);
    for (size_t i = 0; i < active_moduli.size(); i++) a_active[i] = quantized_mod(a, active_moduli[i]);

    const int64_t a_redundant = quantized_mod(a, cfg.redundant_mod);
    int64_t u_redundant = 0;
    const std::vector<int> digits = msb_twos_complement_digits(b, cfg.digit_bits, cfg.digit_stages);

    for (int stage = 0; stage < cfg.digit_stages; stage++) {
        for (size_t i = 0; i < active_moduli.size(); i++) {
            const int mod = active_moduli[i];
            const int64_t c_mod = static_cast<int64_t>(mod_positive(static_cast<i128>(1) << cfg.digit_bits, mod));
            const int64_t digit_mod = static_cast<int64_t>(mod_positive(digits[stage], mod));
            u_active[i] = static_cast<int64_t>(mod_positive(static_cast<i128>(c_mod) * static_cast<i128>(u_active[i]) +
                                                            static_cast<i128>(a_active[i]) * static_cast<i128>(digit_mod),
                                                            mod));
        }
        const int64_t c_redundant =
            static_cast<int64_t>(mod_positive(static_cast<i128>(1) << cfg.digit_bits, cfg.redundant_mod));
        const int64_t digit_redundant = static_cast<int64_t>(mod_positive(digits[stage], cfg.redundant_mod));
        u_redundant = static_cast<int64_t>(mod_positive(static_cast<i128>(c_redundant) * static_cast<i128>(u_redundant) +
                                                        static_cast<i128>(a_redundant) * static_cast<i128>(digit_redundant),
                                                        cfg.redundant_mod));

        if (stage + 1 == cfg.first_promotion_stage) {
            const std::vector<int64_t> u_new = base_extend_residues(u_active, u_redundant, ext_g0, cfg.promote_g1);
            const std::vector<int64_t> a_new = base_extend_residues(a_active, a_redundant, ext_g0, cfg.promote_g1);
            active_moduli = g01;
            u_active.insert(u_active.end(), u_new.begin(), u_new.end());
            a_active.insert(a_active.end(), a_new.begin(), a_new.end());
        }
        if (stage + 1 == cfg.second_promotion_stage) {
            const std::vector<int64_t> u_new = base_extend_residues(u_active, u_redundant, ext_g1, cfg.promote_g2);
            const std::vector<int64_t> a_new = base_extend_residues(a_active, a_redundant, ext_g1, cfg.promote_g2);
            active_moduli = g012;
            u_active.insert(u_active.end(), u_new.begin(), u_new.end());
            a_active.insert(a_active.end(), a_new.begin(), a_new.end());
        }
    }

    std::vector<long long> residues(u_active.begin(), u_active.end());
    return crt_reconstruct_signed(residues, g012);
}

static i128 crt_reconstruct_signed(const std::vector<long long>& residues,
                                   const std::vector<int>& moduli) {
    i128 value = mod_positive(residues[0], moduli[0]);
    i128 prod = moduli[0];
    for (size_t i = 1; i < moduli.size(); i++) {
        const int mod = moduli[i];
        const int value_mod = static_cast<int>(value % mod);
        const int delta = static_cast<int>(mod_positive(residues[i] - value_mod, mod));
        const int prod_mod = static_cast<int>(prod % mod);
        const int inv = inverse_mod(prod_mod, mod);
        const int step = static_cast<int>(mod_positive(static_cast<i128>(delta) * inv, mod));
        value += prod * step;
        prod *= mod;
    }
    const i128 half = prod / 2;
    if (value > half) value -= prod;
    return value;
}

static long double pow2_floor(long double x) {
    if (!(x > 0.0L)) return 1.0L;
    int exp = 0;
    std::frexpl(x, &exp);
    return std::ldexpl(1.0L, exp - 1);
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

static ComplexMatrix random_complex_matrix(int rows, int cols, int exp_span, std::mt19937& gen) {
    std::uniform_real_distribution<double> mant(0.5, 1.0);
    std::uniform_int_distribution<int> expo(-exp_span, exp_span);
    std::uniform_int_distribution<int> sign(0, 1);
    ComplexMatrix out(rows, cols);
    for (int i = 0; i < rows * cols; i++) {
        double mr = std::ldexp(mant(gen), expo(gen));
        double mi = std::ldexp(mant(gen), expo(gen));
        out.real[i] = sign(gen) ? mr : -mr;
        out.imag[i] = sign(gen) ? mi : -mi;
    }
    return out;
}

static std::vector<long double> compute_mu_bar(const ComplexMatrix& a) {
    std::vector<long double> mu(a.rows, 1.0L);
    for (int i = 0; i < a.rows; i++) {
        long double row_max = 0.0L;
        for (int k = 0; k < a.cols; k++) {
            row_max = std::max(row_max, std::fabsl(a.real[a.idx(i, k)]));
            row_max = std::max(row_max, std::fabsl(a.imag[a.idx(i, k)]));
        }
        if (row_max > 0.0L) mu[i] = pow2_floor(63.0L / row_max);
    }
    return mu;
}

static std::vector<long double> compute_nu_bar(const ComplexMatrix& b) {
    std::vector<long double> nu(b.cols, 1.0L);
    for (int j = 0; j < b.cols; j++) {
        long double col_max = 0.0L;
        for (int k = 0; k < b.rows; k++) {
            col_max = std::max(col_max, std::fabsl(b.real[b.idx(k, j)]));
            col_max = std::max(col_max, std::fabsl(b.imag[b.idx(k, j)]));
        }
        if (col_max > 0.0L) nu[j] = pow2_floor(63.0L / col_max);
    }
    return nu;
}

static std::vector<unsigned long long> scaled_abs_upper(const std::vector<double>& vals,
                                                        const std::vector<long double>& scale,
                                                        int rows, int cols, bool row_scale) {
    std::vector<unsigned long long> out(rows * cols, 0);
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            long double s = row_scale ? scale[i] : scale[j];
            long double v = std::ceill(std::fabsl(vals[i * cols + j]) * s);
            out[i * cols + j] = static_cast<unsigned long long>(std::max(0.0L, v));
        }
    }
    return out;
}

static std::vector<unsigned long long> matmul_u64(const std::vector<unsigned long long>& a,
                                                  const std::vector<unsigned long long>& b,
                                                  int m, int k, int n) {
    std::vector<unsigned long long> c(m * n, 0);
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            unsigned long long acc = 0;
            for (int kk = 0; kk < k; kk++) {
                acc += a[i * k + kk] * b[kk * n + j];
            }
            c[i * n + j] = acc;
        }
    }
    return c;
}

static long double product_long_double(const std::vector<int>& moduli) {
    long double p = 1.0L;
    for (int mod : moduli) p *= static_cast<long double>(mod);
    return p;
}

static std::vector<long long> quantize_real(const std::vector<double>& vals,
                                            const std::vector<long double>& scale,
                                            int rows, int cols, bool row_scale) {
    std::vector<long long> out(rows * cols, 0);
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            long double s = row_scale ? scale[i] : scale[j];
            long double v = std::truncl(static_cast<long double>(vals[i * cols + j]) * s);
            out[i * cols + j] = static_cast<long long>(v);
        }
    }
    return out;
}

static bool uniqueness_holds(const std::vector<long long>& ar,
                             const std::vector<long long>& ai,
                             const std::vector<long long>& br,
                             const std::vector<long long>& bi,
                             int m, int k, int n, long double p_half) {
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            long double bound_r = 0.0L;
            long double bound_i = 0.0L;
            for (int kk = 0; kk < k; kk++) {
                long double arr = std::llabs(ar[i * k + kk]);
                long double aii = std::llabs(ai[i * k + kk]);
                long double brr = std::llabs(br[kk * n + j]);
                long double bii = std::llabs(bi[kk * n + j]);
                bound_r += arr * brr + aii * bii;
                bound_i += arr * bii + aii * brr;
            }
            if (bound_r >= p_half || bound_i >= p_half) return false;
        }
    }
    return true;
}

static std::vector<long long> residue_matrix(const std::vector<long long>& src, int p) {
    std::vector<long long> out(src.size(), 0);
    for (size_t i = 0; i < src.size(); i++) out[i] = sym_mod_ll(src[i], p);
    return out;
}

static std::vector<long long> add_mod(const std::vector<long long>& a,
                                      const std::vector<long long>& b, int p) {
    std::vector<long long> out(a.size(), 0);
    for (size_t i = 0; i < a.size(); i++) out[i] = sym_mod_ll(a[i] + b[i], p);
    return out;
}

static std::vector<long long> gemm_mod_blocked(const std::vector<long long>& a,
                                               const std::vector<long long>& b,
                                               int m, int k, int n, int p, int block_n) {
    std::vector<long long> c(m * n, 0);
    for (int j0 = 0; j0 < n; j0 += block_n) {
        int cur_n = std::min(block_n, n - j0);
        for (int i = 0; i < m; i++) {
            for (int j = 0; j < cur_n; j++) {
                long long acc = 0;
                for (int kk = 0; kk < k; kk++) {
                    acc += a[i * k + kk] * b[kk * n + (j0 + j)];
                }
                c[i * n + (j0 + j)] = sym_mod_ll(acc, p);
            }
        }
    }
    return c;
}

static ComplexMatrix ozaki_complex_gemm(const ComplexMatrix& a, const ComplexMatrix& b,
                                        const OzakiConfig& cfg) {
    const int m = a.rows;
    const int k = a.cols;
    const int n = b.cols;
    const long double P_ld = product_long_double(cfg.moduli);

    std::vector<long double> mu_bar = compute_mu_bar(a);
    std::vector<long double> nu_bar = compute_nu_bar(b);

    std::vector<unsigned long long> abar_r = scaled_abs_upper(a.real, mu_bar, m, k, true);
    std::vector<unsigned long long> abar_i = scaled_abs_upper(a.imag, mu_bar, m, k, true);
    std::vector<unsigned long long> bbar_r = scaled_abs_upper(b.real, nu_bar, k, n, false);
    std::vector<unsigned long long> bbar_i = scaled_abs_upper(b.imag, nu_bar, k, n, false);

    std::vector<unsigned long long> cbar_r = matmul_u64(abar_r, bbar_r, m, k, n);
    std::vector<unsigned long long> tmp = matmul_u64(abar_i, bbar_i, m, k, n);
    for (size_t i = 0; i < cbar_r.size(); i++) cbar_r[i] += tmp[i];
    std::vector<unsigned long long> cbar_i = matmul_u64(abar_i, bbar_r, m, k, n);
    tmp = matmul_u64(abar_r, bbar_i, m, k, n);
    for (size_t i = 0; i < cbar_i.size(); i++) cbar_i[i] += tmp[i];

    unsigned long long max_cbar = 1;
    for (size_t i = 0; i < cbar_r.size(); i++) {
        max_cbar = std::max(max_cbar, cbar_r[i]);
        max_cbar = std::max(max_cbar, cbar_i[i]);
    }

    long double extra = pow2_floor(std::sqrt((P_ld / 8.0L) / static_cast<long double>(max_cbar)));
    if (extra < 1.0L) extra = 1.0L;

    std::vector<long double> mu(m, 1.0L), nu(n, 1.0L);
    std::vector<long long> ar, ai, br, bi;
    while (true) {
        for (int i = 0; i < m; i++) mu[i] = mu_bar[i] * extra;
        for (int j = 0; j < n; j++) nu[j] = nu_bar[j] * extra;

        ar = quantize_real(a.real, mu, m, k, true);
        ai = quantize_real(a.imag, mu, m, k, true);
        br = quantize_real(b.real, nu, k, n, false);
        bi = quantize_real(b.imag, nu, k, n, false);

        if (uniqueness_holds(ar, ai, br, bi, m, k, n, P_ld / 2.0L)) break;
        extra *= 0.5L;
        if (extra < std::numeric_limits<long double>::min() * 2.0L) break;
    }

    std::vector<std::vector<long long>> real_res(cfg.moduli.size(), std::vector<long long>(m * n, 0));
    std::vector<std::vector<long long>> imag_res(cfg.moduli.size(), std::vector<long long>(m * n, 0));

    for (size_t l = 0; l < cfg.moduli.size(); l++) {
        int p = cfg.moduli[l];
        std::vector<long long> ar_l = residue_matrix(ar, p);
        std::vector<long long> ai_l = residue_matrix(ai, p);
        std::vector<long long> br_l = residue_matrix(br, p);
        std::vector<long long> bi_l = residue_matrix(bi, p);
        std::vector<long long> sum_a = add_mod(ar_l, ai_l, p);
        std::vector<long long> sum_b = add_mod(br_l, bi_l, p);

        std::vector<long long> d = gemm_mod_blocked(ar_l, br_l, m, k, n, p, cfg.block_n);
        std::vector<long long> e = gemm_mod_blocked(ai_l, bi_l, m, k, n, p, cfg.block_n);
        std::vector<long long> f = gemm_mod_blocked(sum_a, sum_b, m, k, n, p, cfg.block_n);

        for (int idx = 0; idx < m * n; idx++) {
            real_res[l][idx] = sym_mod_ll(d[idx] - e[idx], p);
            imag_res[l][idx] = sym_mod_ll(f[idx] - d[idx] - e[idx], p);
        }
    }

    ComplexMatrix c(m, n);
    std::vector<long long> residues_r(cfg.moduli.size(), 0);
    std::vector<long long> residues_i(cfg.moduli.size(), 0);
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            for (size_t l = 0; l < cfg.moduli.size(); l++) {
                residues_r[l] = real_res[l][i * n + j];
                residues_i[l] = imag_res[l][i * n + j];
            }
            const i128 c_r = crt_reconstruct_signed(residues_r, cfg.moduli);
            const i128 c_i = crt_reconstruct_signed(residues_i, cfg.moduli);
            const long double scale = mu[i] * nu[j];
            c.real[c.idx(i, j)] = static_cast<double>(i128_to_long_double(c_r) / scale);
            c.imag[c.idx(i, j)] = static_cast<double>(i128_to_long_double(c_i) / scale);
        }
    }
    return c;
}

static int run_fused_digit_scalar_validation() {
    const int trials = env_int("OZAKI_TRIALS", 256);
    const int exp_span = env_int("OZAKI_EXP_SPAN", 24);
    const int seed = env_int("OZAKI_SEED", 20260318);

    const FusedDigitScalarConfig cfg = default_fused_digit_scalar_config();
    const std::vector<int> active_moduli = concat_moduli(concat_moduli(cfg.stored_moduli, cfg.promote_g1),
                                                         cfg.promote_g2);
    std::mt19937 gen(seed);

    int exact_matches = 0;
    int direct_rns_matches = 0;
    double max_abs_err = 0.0;
    double max_rel_err = 0.0;
    double sum_rel_err = 0.0;
    int reported_mismatches = 0;

    std::cout << "=== Fused Digit-Residue Scalar Multiply Validation ===\n";
    std::cout << "trials=" << trials
              << " exp_span=" << exp_span
              << " stored_moduli=" << cfg.stored_moduli.size()
              << " active_schedule=8->11->14"
              << " redundant_mod=" << cfg.redundant_mod
              << " digit_bits=" << cfg.digit_bits
              << " digit_stages=" << cfg.digit_stages << "\n";

    for (int t = 0; t < trials; t++) {
        const double a = random_real_scalar(exp_span, gen);
        const double b = random_real_scalar(exp_span, gen);
        int shift_a = 0;
        int shift_b = 0;
        int64_t qa = 0;
        int64_t qb = 0;
        if (!quantize_fp64_mantissa(a, shift_a, qa) || !quantize_fp64_mantissa(b, shift_b, qb)) {
            std::cerr << "mantissa quantization failed at trial " << (t + 1) << "\n";
            return 1;
        }

        const i128 exact = static_cast<i128>(qa) * static_cast<i128>(qb);
        const i128 fused = fused_digit_scalar_multiply(qa, qb, cfg);
        const i128 direct_rns = direct_rns_scalar_multiply(qa, qb, active_moduli);

        if (fused == exact) exact_matches++;
        if (fused == direct_rns) direct_rns_matches++;

        if ((fused != exact || fused != direct_rns) && reported_mismatches < 5) {
            reported_mismatches++;
            std::cout << "mismatch trial " << (t + 1)
                      << ": qa=" << qa
                      << " qb=" << qb
                      << " fused=" << i128_to_string(fused)
                      << " direct_rns=" << i128_to_string(direct_rns)
                      << " exact=" << i128_to_string(exact)
                      << "\n";
        }

        const int total_shift = shift_a + shift_b;
        const double out = static_cast<double>(std::ldexpl(i128_to_long_double(fused), -total_shift));
        const double ref = a * b;
        const double abs_err = std::fabs(out - ref);
        const double rel_err = abs_err / std::max(1e-30, std::fabs(ref));
        max_abs_err = std::max(max_abs_err, abs_err);
        max_rel_err = std::max(max_rel_err, rel_err);
        sum_rel_err += rel_err;
    }

    std::cout << "\nSummary:\n";
    std::cout << "exact_integer_match=" << exact_matches << "/" << trials << "\n";
    std::cout << "direct_rns_match=" << direct_rns_matches << "/" << trials << "\n";
    std::cout << "avg_rel_vs_double=" << std::scientific << std::setprecision(6)
              << (sum_rel_err / std::max(1, trials)) << "\n";
    std::cout << "max_rel_vs_double=" << max_rel_err << "\n";
    std::cout << "max_abs_vs_double=" << max_abs_err << "\n";

    return (exact_matches == trials && direct_rns_matches == trials) ? 0 : 1;
}

static int run_complex_ozaki_gemm() {
    const int m = env_int("OZAKI_M", 16);
    const int n = env_int("OZAKI_N", 16);
    const int k = env_int("OZAKI_K", 32);
    const int trials = env_int("OZAKI_TRIALS", 6);
    const int exp_span = env_int("OZAKI_EXP_SPAN", 24);
    const int seed = env_int("OZAKI_SEED", 20260312);
    const int block_n = env_int("OZAKI_BLOCK_N", 8192);

    OzakiConfig cfg{default_zgemm_moduli(), block_n};
    std::mt19937 gen(seed);

    double sum_rel = 0.0;
    double sum_rms = 0.0;
    double max_rel = 0.0;
    double max_abs = 0.0;

    std::cout << "=== Complex Ozaki-II FP64 GEMM Emulation ===\n";
    std::cout << "m=" << m << " n=" << n << " k=" << k
              << " trials=" << trials
              << " exp_span=" << exp_span
              << " moduli=" << cfg.moduli.size()
              << " block_n=" << cfg.block_n << "\n";

    for (int t = 0; t < trials; t++) {
        ComplexMatrix a = random_complex_matrix(m, k, exp_span, gen);
        ComplexMatrix b = random_complex_matrix(k, n, exp_span, gen);
        ComplexMatrix ref = complex_gemm_ref(a, b);
        ComplexMatrix out = ozaki_complex_gemm(a, b, cfg);
        ErrorStats err = compare_complex(ref, out);
        sum_rel += err.rel_frob;
        sum_rms += err.rms_abs;
        max_rel = std::max(max_rel, err.rel_frob);
        max_abs = std::max(max_abs, err.max_abs);
        std::cout << "trial " << (t + 1)
                  << ": rel_frob=" << std::scientific << std::setprecision(6) << err.rel_frob
                  << " rms_abs=" << err.rms_abs
                  << " max_abs=" << err.max_abs << "\n";
    }

    std::cout << "\nSummary:\n";
    std::cout << "avg_rel_frob=" << std::scientific << std::setprecision(6) << (sum_rel / std::max(1, trials)) << "\n";
    std::cout << "avg_rms_abs=" << (sum_rms / std::max(1, trials)) << "\n";
    std::cout << "max_rel_frob=" << max_rel << "\n";
    std::cout << "max_abs=" << max_abs << "\n";

    return 0;
}

int sc_main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;
    const std::string mode = env_string("OZAKI_MODE", "gemm");
    if (mode == "gemm") return run_complex_ozaki_gemm();
    if (mode == "fused_scalar") return run_fused_digit_scalar_validation();

    std::cerr << "Unknown OZAKI_MODE: " << mode << "\n";
    return 1;
}
