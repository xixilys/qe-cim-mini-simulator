#ifndef ITERATIVE_SUBSPACE_ENGINE_H
#define ITERATIVE_SUBSPACE_ENGINE_H

#include <systemc.h>

#include <complex>
#include <cstdint>
#include <vector>

struct IterativeStats {
    int cycles = 0;
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
    int row_buffer_hits = 0;
    int row_buffer_misses = 0;
    int residue_encodes = 0;
    int crt_reconstructs = 0;
};

struct IterativeConfig {
    int n = 0;
    int m = 0;
    int steps = 0;
};

struct ComplexDenseView {
    const double* real = nullptr;
    const double* imag = nullptr;
};

struct IterativeResultView {
    double* eval = nullptr;
    double* vec_real = nullptr;
    double* vec_imag = nullptr;
};

struct EncodedComplexRow {
    int n = 0;
    int shift = 0;
    std::vector<int64_t> real_residues;
    std::vector<int64_t> imag_residues;
};

struct EncodedVectorBlock {
    int n = 0;
    int cols = 0;
    std::vector<int> col_shifts;
    std::vector<int64_t> real_residues;
    std::vector<int64_t> imag_residues;
};

enum ReducedSolverMode {
    REDUCED_SOLVER_CHOLESKY_JACOBI = 0,
    REDUCED_SOLVER_BINV_JACOBI = 1,
    REDUCED_SOLVER_HYBRID = 2
};

class Complex_Row_Bank {
public:
    void load(const ComplexDenseView& view, int n_dim);
    void read_row(int row, std::vector<double>& out_real, std::vector<double>& out_imag) const;
    double row_max_abs(int row) const;

private:
    int n = 0;
    std::vector<double> real_bank;
    std::vector<double> imag_bank;
    std::vector<double> row_abs_max;
};

class Row_Residue_Buffer {
public:
    void configure(int matrix_count, int rows);
    void clear();
    bool lookup(int matrix_tag, int row, int shift, EncodedComplexRow& encoded) const;
    void fill(int matrix_tag, int row, int shift, const EncodedComplexRow& encoded);

private:
    struct Entry {
        bool valid = false;
        int shift = 0;
        EncodedComplexRow encoded;
    };

    int matrix_count = 0;
    int rows_per_matrix = 0;
    std::vector<Entry> entries;
};

class Mod_Encode_Unit {
public:
    EncodedComplexRow encode(const std::vector<double>& row_real, const std::vector<double>& row_imag, int shift) const;
};

class Residue_3M_MAC {
public:
    void accumulate_row_block(const EncodedComplexRow& encoded_row,
                              const EncodedVectorBlock& encoded_x,
                              int n, int cols, int row,
                              IterativeStats& stats,
                              std::vector<std::complex<double>>& out) const;
};

class Subspace_Ortho_Unit {
public:
    void orthonormalize(const std::vector<std::complex<double>>& s,
                        std::vector<std::complex<double>>& x,
                        int n, int m,
                        IterativeStats& stats) const;
};

class Basis_Update_Unit {
public:
    std::vector<std::complex<double>> apply_transform(const std::vector<std::complex<double>>& basis,
                                                      const std::vector<std::complex<double>>& coeff,
                                                      int rows, int in_cols, int out_cols,
                                                      IterativeStats& stats) const;
};

class Reduced_Projection_Unit {
public:
    void build_projected(const std::vector<std::complex<double>>& q,
                         const std::vector<std::complex<double>>& hq,
                         const std::vector<std::complex<double>>& sq,
                         int n, int k,
                         std::vector<std::complex<double>>& a,
                         std::vector<std::complex<double>>& b,
                         IterativeStats& stats) const;
};

class Reduced_Cholesky_Unit {
public:
    bool factorize_spd(const std::vector<std::complex<double>>& b,
                       int k,
                       std::vector<std::complex<double>>& l,
                       IterativeStats& stats) const;
};

class Reduced_Standardize_Unit {
public:
    bool build_standard(const std::vector<std::complex<double>>& a,
                        const std::vector<std::complex<double>>& l,
                        int k,
                        std::vector<std::complex<double>>& c,
                        IterativeStats& stats) const;
};

class Hermitian_Jacobi_Unit {
public:
    bool diagonalize(const std::vector<std::complex<double>>& a,
                     int k,
                     std::vector<double>& evals,
                     std::vector<std::complex<double>>& y,
                     IterativeStats& stats) const;
};

class Reduced_Backtransform_Unit {
public:
    bool apply_inverse_lh(const std::vector<std::complex<double>>& l,
                          const std::vector<std::complex<double>>& y,
                          const std::vector<std::complex<double>>& b,
                          int k,
                          std::vector<std::complex<double>>& z,
                          IterativeStats& stats) const;
};

class Matrix_Resident_Tile {
public:
    void bind(const ComplexDenseView& h_view, const ComplexDenseView& s_view, int n_dim);

    std::vector<std::complex<double>> compute_hx(const std::vector<std::complex<double>>& x, int cols, IterativeStats& stats) const;
    std::vector<std::complex<double>> compute_sx(const std::vector<std::complex<double>>& x, int cols, IterativeStats& stats) const;

private:
    std::vector<std::complex<double>> compute_operator(const Complex_Row_Bank& bank, int matrix_tag,
                                                       const std::vector<std::complex<double>>& x,
                                                       int cols, IterativeStats& stats) const;

    int n = 0;
    Complex_Row_Bank h_bank;
    Complex_Row_Bank s_bank;
    mutable Row_Residue_Buffer row_buffer;
    Mod_Encode_Unit mod_encode;
    Residue_3M_MAC mac;
};

class Reduced_Generalized_MicroSolver {
public:
    bool solve_x_subspace(const std::vector<std::complex<double>>& x,
                          const std::vector<std::complex<double>>& hx,
                          const std::vector<std::complex<double>>& sx,
                          int n, int m,
                          int solver_mode,
                          std::vector<double>& evals,
                          std::vector<std::complex<double>>& z,
                          IterativeStats& stats) const;

    bool solve_q_subspace(const std::vector<std::complex<double>>& q,
                          const std::vector<std::complex<double>>& hq,
                          const std::vector<std::complex<double>>& sq,
                          int n, int q_cols,
                          int solver_mode,
                          std::vector<double>& evals,
                          std::vector<std::complex<double>>& z,
                          IterativeStats& stats) const;

private:
    bool solve_projected(std::vector<std::complex<double>> a,
                         std::vector<std::complex<double>> b,
                         int k,
                         int solver_mode,
                         std::vector<double>& evals,
                         std::vector<std::complex<double>>& z,
                         IterativeStats& stats) const;

    Reduced_Projection_Unit projector;
    Reduced_Cholesky_Unit cholesky_unit;
    Reduced_Standardize_Unit standardize_unit;
    Hermitian_Jacobi_Unit jacobi_unit;
    Reduced_Backtransform_Unit backtransform_unit;
};

SC_MODULE(Iterative_Subspace_Engine) {
    sc_in<bool> clk;
    sc_in<bool> rst_n;

    sc_in<bool> start;
    sc_out<bool> busy;
    sc_out<bool> done;

    sc_in<int> matrix_n;
    sc_in<int> block_m;
    sc_in<int> fixed_steps;
    sc_in<int> micro_solver_mode;
    sc_in<bool> use_history_p;

    sc_out<int> total_cycles_used;
    sc_out<int> hx_ops_used;
    sc_out<int> sx_ops_used;
    sc_out<int> qhqx_ops_used;
    sc_out<int> ortho_ops_used;
    sc_out<int> basis_update_ops_used;
    sc_out<int> reduced_build_ops_used;
    sc_out<int> reduced_cholesky_ops_used;
    sc_out<int> reduced_standardize_ops_used;
    sc_out<int> reduced_jacobi_ops_used;
    sc_out<int> reduced_backtransform_ops_used;
    sc_out<int> row_buffer_hits_used;
    sc_out<int> row_buffer_misses_used;
    sc_out<int> residue_encodes_used;
    sc_out<int> crt_reconstructs_used;

    const double* h_real;
    const double* h_imag;
    const double* s_real;
    const double* s_imag;
    const double* x0_real;
    const double* x0_imag;

    double* out_eval;
    double* out_vec_real;
    double* out_vec_imag;

    void run();

    SC_CTOR(Iterative_Subspace_Engine) {
        SC_THREAD(run);
        sensitive << clk.pos();
        async_reset_signal_is(rst_n, false);

        h_real = nullptr;
        h_imag = nullptr;
        s_real = nullptr;
        s_imag = nullptr;
        x0_real = nullptr;
        x0_imag = nullptr;
        out_eval = nullptr;
        out_vec_real = nullptr;
        out_vec_imag = nullptr;
    }

private:
    Matrix_Resident_Tile tile;
    Reduced_Generalized_MicroSolver microsolver;
    Subspace_Ortho_Unit ortho_unit;
    Basis_Update_Unit update_unit;
};

#endif
