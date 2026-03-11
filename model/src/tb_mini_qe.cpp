#include <systemc.h>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <vector>

#include "cim_macro.h"
#include "fft_engine.h"
#include "fpga_controller.h"

static void gemm_fp64(const double* A, const double* B, double* C, int M, int K, int N) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            double acc = 0.0;
            for (int kk = 0; kk < K; kk++) acc += A[i * K + kk] * B[kk * N + j];
            C[i * N + j] = acc;
        }
    }
}

static void gemm_bf16(const double* A, const double* B, double* C, int M, int K, int N) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            double acc = 0.0;
            for (int kk = 0; kk < K; kk++) {
                double a = bf16_truncate(A[i * K + kk]);
                double b = bf16_truncate(B[kk * N + j]);
                acc += a * b;
                if ((kk & 0xF) == 0xF) acc = bf16_truncate(acc);
            }
            C[i * N + j] = bf16_truncate(acc);
        }
    }
}

static void gemm_cim(const double* A, const double* B, double* C, int M, int K, int N, int prec) {
    if (prec == 0) gemm_bf16(A, B, C, M, K, N);
    else gemm_fp64(A, B, C, M, K, N);
}

static int gemm_dsp_zeroskip(const double* deeq, const double* becp, double* ps, int nkb, int nbnd) {
    int macs = 0;
    for (int i = 0; i < nkb; i++) {
        for (int j = 0; j < nbnd; j++) {
            double acc = 0.0;
            for (int k = 0; k < nkb; k++) {
                double d = deeq[i * nkb + k];
                if (d != 0.0) {
                    acc += d * becp[k * nbnd + j];
                    macs++;
                }
            }
            ps[i * nbnd + j] = acc;
        }
    }
    return macs;
}

static void transpose(const double* A, double* AT, int M, int N) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) AT[j * M + i] = A[i * N + j];
    }
}

static double rms_diff(const double* A, const double* B, int len) {
    double s = 0.0;
    for (int i = 0; i < len; i++) {
        double d = A[i] - B[i];
        s += d * d;
    }
    return std::sqrt(s / std::max(1, len));
}

static double frob_norm(const double* A, int len) {
    double s = 0.0;
    for (int i = 0; i < len; i++) s += A[i] * A[i];
    return std::sqrt(s);
}

static double trace_mat(const double* A, int n) {
    double t = 0.0;
    for (int i = 0; i < n; i++) t += A[i * n + i];
    return t;
}

struct EnergyTerms {
    double eband;
    double ehart;
    double exc;
    double eewald;
    double eexx;
    double etot;
};


static EnergyTerms compute_energy_terms(const double* hc, const double* rmexx, const double* rho,
                                        int nbnd, int npw) {
    EnergyTerms t{};
    t.eband = trace_mat(hc, nbnd);

    double rho2 = 0.0;
    double rho43 = 0.0;
    for (int i = 0; i < npw; i++) {
        double r = std::max(1e-14, rho[i]);
        rho2 += r * r;
        rho43 += std::pow(r, 4.0 / 3.0);
    }
    // Proxy Hartree/XC without empirical fitting coefficients.
    // Hartree > 0, LDA-like exchange < 0.
    t.ehart = 0.5 * (rho2 / std::max(1, npw));
    t.exc = -0.75 * (rho43 / std::max(1, npw));

    double rm2 = 0.0;
    for (int i = 0; i < nbnd * nbnd; i++) rm2 += rmexx[i] * rmexx[i];
    // Exact-exchange contribution (stabilizing negative term)
    t.eexx = -0.5 * (rm2 / std::max(1, nbnd * nbnd));

    // Constant ionic background term for fixed cell/atoms in this toy model
    t.eewald = -1.0;
    t.etot = t.eband + t.ehart + t.exc + t.eewald + t.eexx;
    return t;
}

static void charge_from_psi(const double* psi, double* rho, int npw, int nbnd) {
    for (int g = 0; g < npw; g++) {
        double acc = 0.0;
        for (int b = 0; b < nbnd; b++) {
            double v = psi[g * nbnd + b];
            acc += v * v;
        }
        rho[g] = acc;
    }
}

static void mix_density(double* rho_inout, const double* rho_out, int n, double beta) {
    for (int i = 0; i < n; i++) {
        rho_inout[i] = (1.0 - beta) * rho_inout[i] + beta * rho_out[i];
    }
}

static void symmetrize(double* A, int n) {
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            double v = 0.5 * (A[i * n + j] + A[j * n + i]);
            A[i * n + j] = v;
            A[j * n + i] = v;
        }
    }
}

static void jacobi_eigh(const double* A_in, int n, std::vector<double>& eigvals, std::vector<double>& eigvecs,
                        int max_sweeps, double tol) {
    std::vector<double> A(A_in, A_in + n * n);
    eigvecs.assign(n * n, 0.0);
    for (int i = 0; i < n; i++) eigvecs[i * n + i] = 1.0;

    for (int sweep = 0; sweep < max_sweeps; sweep++) {
        double off = 0.0;
        for (int p = 0; p < n; p++) {
            for (int q = p + 1; q < n; q++) off += std::abs(A[p * n + q]);
        }
        if (off < tol) break;

        for (int p = 0; p < n; p++) {
            for (int q = p + 1; q < n; q++) {
                double apq = A[p * n + q];
                if (std::abs(apq) < tol) continue;
                double app = A[p * n + p];
                double aqq = A[q * n + q];
                double tau = (aqq - app) / (2.0 * apq);
                double t = (tau >= 0.0) ? 1.0 / (tau + std::sqrt(1.0 + tau * tau))
                                        : -1.0 / (-tau + std::sqrt(1.0 + tau * tau));
                double c = 1.0 / std::sqrt(1.0 + t * t);
                double s = t * c;

                for (int k = 0; k < n; k++) {
                    double aik = A[p * n + k];
                    double aqk = A[q * n + k];
                    A[p * n + k] = c * aik - s * aqk;
                    A[q * n + k] = s * aik + c * aqk;
                }
                for (int k = 0; k < n; k++) {
                    double akp = A[k * n + p];
                    double akq = A[k * n + q];
                    A[k * n + p] = c * akp - s * akq;
                    A[k * n + q] = s * akp + c * akq;
                }
                for (int k = 0; k < n; k++) {
                    double vkp = eigvecs[k * n + p];
                    double vkq = eigvecs[k * n + q];
                    eigvecs[k * n + p] = c * vkp - s * vkq;
                    eigvecs[k * n + q] = s * vkp + c * vkq;
                }
            }
        }
    }

    eigvals.resize(n);
    for (int i = 0; i < n; i++) eigvals[i] = A[i * n + i];

    std::vector<int> idx(n);
    for (int i = 0; i < n; i++) idx[i] = i;
    std::sort(idx.begin(), idx.end(), [&](int a, int b) { return eigvals[a] < eigvals[b]; });

    std::vector<double> eval_sorted(n), evec_sorted(n * n);
    for (int c = 0; c < n; c++) {
        eval_sorted[c] = eigvals[idx[c]];
        for (int r = 0; r < n; r++) evec_sorted[r * n + c] = eigvecs[r * n + idx[c]];
    }
    eigvals.swap(eval_sorted);
    eigvecs.swap(evec_sorted);
}

static void issue_op(sc_signal<bool>& start, sc_signal<int>& op, sc_signal<int>& m, sc_signal<int>& n,
                     sc_signal<int>& k, sc_signal<int>& prec, sc_signal<bool>& done,
                     int opv, int mv, int nv, int kv, int pv) {
    op.write(opv);
    m.write(mv);
    n.write(nv);
    k.write(kv);
    prec.write(pv);
    start.write(true);
    sc_start(1, SC_NS);
    start.write(false);
    while (!done.read()) sc_start(1, SC_NS);
    sc_start(1, SC_NS);
}

int sc_main(int argc, char* argv[]) {
    sc_clock clk("clk", 1, SC_NS);
    sc_signal<bool> rst_n;

    sc_signal<bool> cim_cmd_valid, cim_busy_a, cim_busy_b, cim_result_valid;
    sc_signal<int> cim_cmd_type, cim_precision_mode, cim_rows, cim_cols;
    sc_signal<double> cim_sparsity;

    sc_signal<bool> fpga_start, fpga_ready, fpga_done;
    sc_signal<int> fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec;
    sc_signal<int> fpga_cycles, fpga_skipped, fpga_dsp_cycles;

    sc_signal<bool> fft_start, fft_busy, fft_done;
    sc_signal<int> fft_size;

    CIM_Macro cim("CIM");
    cim.clk(clk);
    cim.rst_n(rst_n);
    cim.cmd_valid(cim_cmd_valid);
    cim.cmd_type(cim_cmd_type);
    cim.precision_mode(cim_precision_mode);
    cim.rows_to_process(cim_rows);
    cim.cols_to_process(cim_cols);
    cim.sparsity_ratio(cim_sparsity);
    cim.busy_a(cim_busy_a);
    cim.busy_b(cim_busy_b);
    cim.result_valid(cim_result_valid);

    FPGA_Controller fpga("FPGA");
    fpga.clk(clk);
    fpga.rst_n(rst_n);
    fpga.start_cmd(fpga_start);
    fpga.op_type(fpga_op);
    fpga.matrix_m(fpga_m);
    fpga.matrix_n(fpga_n);
    fpga.matrix_k(fpga_k);
    fpga.precision(fpga_prec);
    fpga.ready(fpga_ready);
    fpga.done(fpga_done);
    fpga.total_cycles_used(fpga_cycles);
    fpga.total_skipped_cycles(fpga_skipped);
    fpga.dsp_cycles_used(fpga_dsp_cycles);
    fpga.cim_cmd_valid(cim_cmd_valid);
    fpga.cim_cmd_type(cim_cmd_type);
    fpga.cim_precision_mode(cim_precision_mode);
    fpga.cim_rows(cim_rows);
    fpga.cim_cols(cim_cols);
    fpga.cim_sparsity(cim_sparsity);
    fpga.cim_busy_a(cim_busy_a);
    fpga.cim_busy_b(cim_busy_b);
    fpga.cim_result_valid(cim_result_valid);

    FFT_Engine fft("FFT");
    fft.clk(clk);
    fft.rst_n(rst_n);
    fft.start(fft_start);
    fft.size(fft_size);
    fft.busy(fft_busy);
    fft.done(fft_done);

    rst_n.write(false);
    fpga_start.write(false);
    fft_start.write(false);
    sc_start(10, SC_NS);
    rst_n.write(true);
    sc_start(10, SC_NS);

    auto getenv_int = [](const char* name, int defv) {
        const char* s = std::getenv(name);
        return s ? std::atoi(s) : defv;
    };
    auto getenv_double = [](const char* name, double defv) {
        const char* s = std::getenv(name);
        return s ? std::atof(s) : defv;
    };

    // Step-1: align simulation scale to QE test_si by default
    const int npw = getenv_int("SIM_NPW", 64);
    const int nbnd = getenv_int("SIM_NBND", 4);
    const int nkb = getenv_int("SIM_NKB", 4);

    std::vector<double> psi(npw * nbnd), psi_new(npw * nbnd);
    std::vector<double> xi(npw * nbnd), vkb(npw * nkb), deeq(nkb * nkb);
    std::vector<double> U(nbnd * nbnd), eigvals(nbnd);

    std::vector<double> vkb_T(nkb * npw), xi_T(nbnd * npw), psi_T(nbnd * npw);
    std::vector<double> becp(nkb * nbnd), ps(nkb * nbnd), vkb_ps(npw * nbnd);
    std::vector<double> rmexx(nbnd * nbnd), exx(npw * nbnd), h_psi(npw * nbnd), hc(nbnd * nbnd);

    std::vector<double> becp_ref(nkb * nbnd), ps_ref(nkb * nbnd), vkb_ps_ref(npw * nbnd);
    std::vector<double> rmexx_ref(nbnd * nbnd), exx_ref(npw * nbnd), h_psi_ref(npw * nbnd), hc_ref(nbnd * nbnd);

    srand(42);
    for (int i = 0; i < npw * nbnd; i++) psi[i] = ((double)rand() / RAND_MAX) * 0.1;
    for (int i = 0; i < npw * nbnd; i++) xi[i] = ((double)rand() / RAND_MAX) * 0.1;
    for (int i = 0; i < npw * nkb; i++) vkb[i] = ((double)rand() / RAND_MAX) * 0.05;
    for (int i = 0; i < nkb * nkb; i++) {
        deeq[i] = (((double)rand() / RAND_MAX) > 0.75) ? ((double)rand() / RAND_MAX) * 0.01 : 0.0;
    }

    transpose(vkb.data(), vkb_T.data(), npw, nkb);
    transpose(xi.data(), xi_T.data(), npw, nbnd);

    int deeq_nnz = 0;
    for (int i = 0; i < nkb * nkb; i++) if (deeq[i] != 0.0) deeq_nnz++;

    fpga.dsp_deeq_data = deeq.data();
    fpga.dsp_becp_data = becp.data();
    fpga.dsp_ps_data = ps.data();
    fpga.dsp_nkb = nkb;
    fpga.dsp_nbnd = nbnd;

    const int max_scf = 20;
    const int max_diag = 12;
    const double scf_tol = getenv_double("SCF_CONV_THR", 1e-6);   // QE-like conv_thr
    const double diag_tol = getenv_double("DIAG_CONV_THR", 1e-7);
    double ethr = getenv_double("DIAGO_THR_INIT", 1e-2);          // QE-like diagonalization threshold
    const double mixing_beta = getenv_double("MIXING_BETA", 0.7);

    // Adaptive mixed-precision switch (BF16 -> FP64)
    // Switch to FP64 when SCF is close to convergence, not by fixed iteration count.
    const double mp_switch_abs_delta_e = getenv_double("MP_SWITCH_ABS_DE", 1e-2);
    const double mp_switch_rel_delta_e = getenv_double("MP_SWITCH_REL_DE", 1e-5);
    const double mp_switch_diag_res = getenv_double("MP_SWITCH_DIAG_RES", 5e-5);
    const double mp_plateau_ratio = getenv_double("MP_PLATEAU_RATIO", 0.90);
    const int mp_plateau_steps = getenv_int("MP_PLATEAU_STEPS", 3);
    const double mp_plateau_diag_res = getenv_double("MP_PLATEAU_DIAG_RES", 2e-3);
    const double mp_switch_mid_delta_e = getenv_double("MP_SWITCH_MID_DE", 2e2);
    const double mp_switch_frac_initial = getenv_double("MP_SWITCH_FRAC_INIT_DE", 0.45);
    const double mp_switch_dr2 = getenv_double("MP_SWITCH_DR2", 5e-4);

    std::cout << "=== QE-like CIM Co-Sim ===\n";
    std::cout << "npw=" << npw << " nbnd=" << nbnd << " nkb=" << nkb << "\n";
    std::cout << "Deeq sparsity=" << std::fixed << std::setprecision(1)
              << (1.0 - (double)deeq_nnz / (nkb * nkb)) * 100.0 << "%\n";
    std::cout << std::scientific << std::setprecision(3);
    std::cout << "SCF config: conv_thr=" << scf_tol << " diag_thr=" << diag_tol << " ethr_init=" << ethr << "\n";
    std::cout << "MP config: abs=" << mp_switch_abs_delta_e
              << " rel=" << mp_switch_rel_delta_e
              << " diag=" << mp_switch_diag_res
              << " plateau_ratio=" << mp_plateau_ratio
              << " plateau_steps=" << mp_plateau_steps
              << " plateau_diag=" << mp_plateau_diag_res
              << " mid_de=" << mp_switch_mid_delta_e
              << " frac_init=" << mp_switch_frac_initial
              << " switch_dr2=" << mp_switch_dr2
              << " mixing_beta=" << mixing_beta << "\n";
    std::cout << "Energy model: fixed (no fitting coefficients)\n";
    std::cout << std::scientific << std::setprecision(6);

    double e_prev = std::numeric_limits<double>::infinity();
    bool converged = false;
    bool use_fp64 = false;
    double prev_delta_scf = std::numeric_limits<double>::infinity();
    int plateau_count = 0;
    double delta_scf_initial = std::numeric_limits<double>::quiet_NaN();
    const double nelec_eff = std::max(1.0, 2.0 * nbnd);

    std::vector<double> rho_in(npw, 0.0), rho_out(npw, 0.0);
    charge_from_psi(psi.data(), rho_in.data(), npw, nbnd);

    for (int scf = 1; scf <= max_scf; scf++) {
        int prec = use_fp64 ? 1 : 0;
        std::cout << "\n==== SCF " << scf << " (" << (prec == 0 ? "BF16" : "FP64") << ") ====\n";

        double diag_residual = 0.0;
        double hpsi_rel = 0.0;
        double e_cim = 0.0;
        double e_ref = 0.0;
        double delta_quant = 0.0;
        double delta_scf = 0.0;
        double dr2 = 0.0;
        EnergyTerms et_cim{}, et_ref{};

        bool first_scf = (scf == 1);
        int scf_repeat = 0;
        while (true) {
            scf_repeat++;

            // QE-like: diagonalization effort tightens with ethr
            int diag_budget = std::max(2, std::min(max_diag, (int)std::ceil(-std::log10(std::max(1e-13, ethr))) + 2));

            double tr2_min = first_scf ? ethr * nelec_eff : 0.0;
            diag_residual = 0.0;

            for (int it = 1; it <= diag_budget; it++) {
            std::fill(h_psi.begin(), h_psi.end(), 0.0);
            std::fill(h_psi_ref.begin(), h_psi_ref.end(), 0.0);

            // 1) calbec: becp = vkb^H * psi
            gemm_cim(vkb_T.data(), psi.data(), becp.data(), nkb, npw, nbnd, prec);
            gemm_fp64(vkb_T.data(), psi.data(), becp_ref.data(), nkb, npw, nbnd);
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     2, npw, nbnd, nkb, prec);

            // 1.5) DSP Deeq path: ps = Deeq * becp
            int dsp_macs = gemm_dsp_zeroskip(deeq.data(), becp.data(), ps.data(), nkb, nbnd);
            gemm_fp64(deeq.data(), becp_ref.data(), ps_ref.data(), nkb, nkb, nbnd);
            fpga.dsp_becp_data = becp.data();
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     5, nkb, nbnd, nkb, prec);

            // 2) h_psi += vkb * ps
            gemm_cim(vkb.data(), ps.data(), vkb_ps.data(), npw, nkb, nbnd, prec);
            gemm_fp64(vkb.data(), ps_ref.data(), vkb_ps_ref.data(), npw, nkb, nbnd);
            for (int i = 0; i < npw * nbnd; i++) {
                h_psi[i] += vkb_ps[i];
                h_psi_ref[i] += vkb_ps_ref[i];
            }
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     3, npw, nbnd, nkb, prec);

            // launch FFT in parallel style
            fft_size.write(64 * 64 * 64);
            fft_start.write(true);
            sc_start(1, SC_NS);
            fft_start.write(false);

            // 3) rmexx = xi^H * psi
            gemm_cim(xi_T.data(), psi.data(), rmexx.data(), nbnd, npw, nbnd, prec);
            gemm_fp64(xi_T.data(), psi.data(), rmexx_ref.data(), nbnd, npw, nbnd);
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     1, npw, nbnd, npw, prec);

            // 3b) h_psi -= xi * rmexx
            gemm_cim(xi.data(), rmexx.data(), exx.data(), npw, nbnd, nbnd, prec);
            gemm_fp64(xi.data(), rmexx_ref.data(), exx_ref.data(), npw, nbnd, nbnd);
            for (int i = 0; i < npw * nbnd; i++) {
                h_psi[i] -= exx[i];
                h_psi_ref[i] -= exx_ref[i];
            }

            // 4) hc = psi^H * h_psi
            transpose(psi.data(), psi_T.data(), npw, nbnd);
            gemm_fp64(psi_T.data(), h_psi.data(), hc.data(), nbnd, npw, nbnd);
            gemm_fp64(psi_T.data(), h_psi_ref.data(), hc_ref.data(), nbnd, npw, nbnd);
            symmetrize(hc.data(), nbnd);
            symmetrize(hc_ref.data(), nbnd);
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     4, npw, nbnd, nbnd, prec);

            while (!fft_done.read()) sc_start(1, SC_NS);

            // Inner diagonalization: hc * U = U * eps
            jacobi_eigh(hc.data(), nbnd, eigvals, U, 40, 1e-12);

            // 5) psi_new = psi * U (wavefunction rotation)
            gemm_cim(psi.data(), U.data(), psi_new.data(), npw, nbnd, nbnd, prec);
            issue_op(fpga_start, fpga_op, fpga_m, fpga_n, fpga_k, fpga_prec, fpga_done,
                     3, npw, nbnd, nbnd, prec);

            double n0 = std::max(1e-30, frob_norm(psi.data(), npw * nbnd));
            diag_residual = rms_diff(psi_new.data(), psi.data(), npw * nbnd) / n0;

            std::cout << "  [Diag " << it << "] res=" << diag_residual
                      << " becp_err=" << rms_diff(becp.data(), becp_ref.data(), nkb * nbnd)
                      << " rmexx_err=" << rms_diff(rmexx.data(), rmexx_ref.data(), nbnd * nbnd)
                      << " dsp_macs=" << dsp_macs << "\n";

                std::copy(psi_new.begin(), psi_new.end(), psi.begin());
                if (diag_residual < diag_tol) break;
            }

            hpsi_rel = rms_diff(h_psi.data(), h_psi_ref.data(), npw * nbnd) /
                       std::max(1e-30, frob_norm(h_psi_ref.data(), npw * nbnd));
            charge_from_psi(psi.data(), rho_out.data(), npw, nbnd);
            dr2 = rms_diff(rho_out.data(), rho_in.data(), npw);

            et_cim = compute_energy_terms(hc.data(), rmexx.data(), rho_out.data(), nbnd, npw);
            et_ref = compute_energy_terms(hc_ref.data(), rmexx_ref.data(), rho_out.data(), nbnd, npw);
            e_cim = et_cim.etot;
            e_ref = et_ref.etot;
            delta_quant = std::abs(e_cim - e_ref);
            delta_scf = std::abs(e_cim - e_prev);

            // QE electrons.f90 behavior: first SCF may re-diagonalize with reduced ethr
            if (first_scf && dr2 < tr2_min && scf_repeat < 3) {
                std::cout << "  Threshold (ethr) on eigenvalues was too large; re-diagonalizing with lowered threshold\n";
                ethr = std::max(0.1 * dr2 / nelec_eff, 1e-13);
                continue;
            }
            break;
        }

        // QE-like charge mixing: rho_in <- mix(rho_out, rho_in)
        mix_density(rho_in.data(), rho_out.data(), npw, mixing_beta);

        // QE-like threshold update (electrons.f90 style)
        if (scf > 1) {
            if (scf == 2) ethr = 1e-2;
            ethr = std::min(ethr, 0.1 * dr2 / nelec_eff);
            ethr = std::max(ethr, 1e-13);
        }

        std::cout << "  E_cim=" << std::fixed << std::setprecision(10) << e_cim
                  << " E_ref=" << e_ref << std::scientific << std::setprecision(6) << "\n";
        std::cout << "  terms_cim: band=" << et_cim.eband
                  << " hart=" << et_cim.ehart
                  << " xc=" << et_cim.exc
                  << " ewald=" << et_cim.eewald
                  << " exx=" << et_cim.eexx << "\n";
        std::cout << "  Delta_scf=" << delta_scf
                  << " Delta_quant=" << delta_quant
                  << " dr2=" << dr2
                  << " hpsi_rel=" << hpsi_rel
                  << " diag_res=" << diag_residual
                  << " ethr=" << ethr << "\n";
        std::cout << "  estimated scf accuracy < " << (dr2 * std::max(1.0, std::abs(e_cim))) << " Ry\n";

        bool conv_elec = (dr2 < scf_tol);
        if (conv_elec && diag_residual < diag_tol && scf > 1) {
            converged = true;
            std::cout << "  -> SCF converged\n";
            break;
        }

        // Adaptive precision escalation: switch once, then stay FP64.
        if (!use_fp64 && std::isfinite(delta_scf)) {
            if (!std::isfinite(delta_scf_initial) && scf > 1) delta_scf_initial = delta_scf;
            double rel_delta = delta_scf / std::max(1.0, std::abs(e_cim));
            if (std::isfinite(prev_delta_scf)) {
                double ratio = delta_scf / std::max(1e-30, prev_delta_scf);
                if (ratio > mp_plateau_ratio) plateau_count++;
                else plateau_count = 0;
            }

            bool near_conv = (delta_scf < mp_switch_abs_delta_e) ||
                             (rel_delta < mp_switch_rel_delta_e) ||
                             (diag_residual < mp_switch_diag_res) ||
                             (dr2 < mp_switch_dr2);
            bool plateau_near = (plateau_count >= mp_plateau_steps) &&
                                (diag_residual < mp_plateau_diag_res);
            bool mid_refine = (delta_scf < mp_switch_mid_delta_e);
            bool frac_refine = std::isfinite(delta_scf_initial) &&
                               (delta_scf < mp_switch_frac_initial * delta_scf_initial);
            if (near_conv || plateau_near || mid_refine || frac_refine) {
                use_fp64 = true;
                std::cout << "  -> Mixed precision switch: "
                          << (near_conv ? "near-convergence" :
                              (plateau_near ? "BF16 plateau" :
                               (mid_refine ? "SCF residual threshold" : "fraction-of-initial Delta_scf")))
                          << " detected, enter FP64 refine\n";
            }
        }
        prev_delta_scf = delta_scf;
        e_prev = e_cim;
    }

    std::cout << "\n=== Finished ===\n";
    std::cout << "Converged: " << (converged ? "YES" : "NO") << "\n";
    std::cout << "Total active cycles: " << fpga_cycles.read() << "\n";
    std::cout << "Total skipped cycles: " << fpga_skipped.read() << "\n";
    std::cout << "Total DSP cycles: " << fpga_dsp_cycles.read() << "\n";

    return 0;
}
