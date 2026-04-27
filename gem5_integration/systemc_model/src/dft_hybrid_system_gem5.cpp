#include "dft_hybrid_system_gem5.hpp"
#include "gem5_bridge.hpp"
#include <iostream>
#include <iomanip>
#include <cmath>

// Cycle-accurate timing parameters
// Assuming 200 MHz clock = 5ns period
namespace DFT Timing {
    // Cluster execution times per operation
    constexpr double CLUSTER_A_TIME_PER_PAIR = 500.0;    // ps per band pair (op sweep)
    constexpr double CLUSTER_B_TIME_PER_PANEL = 250.0;    // ps per panel (reduced build)
    constexpr double CLUSTER_C_TIME_PER_BAND = 10000.0;   // ps per band (hardware diag)
    constexpr double CLUSTER_D_TIME = 150.0;             // ps (residual refresh)

    // Fixed overhead per k-point
    constexpr double KPOINT_OVERHEAD = 50000.0;  // 50 ns overhead

    // Mixing time per iteration
    constexpr double MIXING_TIME_PER_ITER = 500000.0;  // 500 ns
}

namespace qebs {

DFTHybridSystemGem5::DFTHybridSystemGem5(sc_core::sc_module_name name,
                                         const ArchitectureConfig& config,
                                         bool enable_gem5_bridge)
    : sc_module(name),
      config_(config),
      fabric_("fabric"),
      chip_("chip", config),
      gem5_bridge_(nullptr) {
  if (enable_gem5_bridge) {
    gem5_bridge_ = new Gem5Bridge("gem5_bridge", this);
  }
}

DFTHybridSystemGem5::DFTHybridSystemGem5(sc_core::sc_module_name name)
    : DFTHybridSystemGem5(name, ArchitectureConfig::create_default(), true) {}

SCFState DFTHybridSystemGem5::run_demo(const SystemRunConfig& run_config) const {
  SCFState state;
  state.scf_iteration = 0;
  state.total_energy = 0.0;
  state.converged = false;

  std::cout << "[DFTHybridSystemGem5] run_demo called (gem5-enabled mode)" << std::endl;

  return state;
}

SCFRunReport DFTHybridSystemGem5::run_scf(const SystemRunConfig& run_config) const {
  SCFRunReport report;
  report.run_config = run_config;
  report.final_state.converged = false;
  report.total_episodes = 0;

  std::cout << "[DFTHybridSystemGem5] run_scf called (gem5-enabled mode)" << std::endl;

  return report;
}

void DFTHybridSystemGem5::execute_c_bands_from_gem5(const CBandsRequest& req) {
  sc_time start_time = sc_time_stamp();

  std::cout << "[DFTHybridSystemGem5] Received c_bands request from gem5:" << std::endl;
  std::cout << "  Matrix dimensions: n=" << req.n << " m=" << req.m << " k=" << req.k << std::endl;
  std::cout << "  H matrix address: 0x" << std::hex << req.h_matrix_addr << std::dec << std::endl;
  std::cout << "  S matrix address: 0x" << std::hex << req.s_matrix_addr << std::dec << std::endl;
  std::cout << "  Result address: 0x" << std::hex << req.result_addr << std::dec << std::endl;

  // Calculate cycle-accurate execution time
  // T = (n * m / panel_size) * cluster_time_per_panel
  int num_panels = (req.n * req.m + 7) / 8;  // Assuming panel_size = 8
  double panel_time_ps = DFT::CLUSTER_A_TIME_PER_PAIR * 8 + DFT::CLUSTER_B_TIME_PER_PANEL;
  double total_time_ps = num_panels * panel_time_ps + DFT::KPOINT_OVERHEAD * 1000;

  std::cout << "  Estimated panels: " << num_panels << std::endl;
  std::cout << "  Estimated time: " << total_time_ps / 1e6 << " ms" << std::endl;

  // Execute with timing
  EpisodeDescriptor descriptor;
  descriptor.band_count = req.n;
  descriptor.panel_size = req.m;

  // Simulate hardware execution with accurate timing
  sc_time execution_time(total_time_ps / 1000.0, SC_NS);  // Convert ps to ns for sc_time
  wait(execution_time);

  sc_time end_time = sc_time_stamp();
  std::cout << "[DFTHybridSystemGem5] c_bands computation completed"
            << " time=" << (end_time - start_time).to_double() / 1e6 << " ms" << std::endl;
}

DFTHybridSystemGem5::ElectronsResult
DFTHybridSystemGem5::execute_electrons_from_gem5(const ElectronsRequest& req) {
  sc_time start_time = sc_time_stamp();

  std::cout << "[DFTHybridSystemGem5] Starting complete electrons loop from gem5" << std::endl;
  std::cout << "  System: nbnd=" << req.n_bands << " npwx=" << req.n_basis
            << " nks=" << req.n_kpoints << " nspin=" << req.n_spin << std::endl;
  std::cout << "  Convergence: max_iter=" << req.max_iterations
            << " tr2=" << req.conv_threshold << " ethr=" << req.diag_threshold << std::endl;
  std::cout << "  CIM: " << (req.enable_cim ? "enabled" : "disabled") << std::endl;

  ElectronsResult result;
  result.converged = false;
  result.iterations = 0;
  result.final_error = 1.0;
  result.total_energy = 0.0;
  result.c_bands_time_ns = 0.0;
  result.sum_band_time_ns = 0.0;
  result.mix_rho_time_ns = 0.0;

  double dr2 = 1.0;
  double ethr = req.diag_threshold;

  for (int iter = 1; iter <= req.max_iterations; iter++) {
    sc_time iter_start = sc_time_stamp();
    std::cout << "[DFTHybridSystemGem5] SCF iteration " << iter << std::endl;

    // === Cluster A: Operator sweep ===
    sc_time c_bands_start = sc_time_stamp();
    double c_bands_iter_time_ns = 0.0;
    for (int ik = 0; ik < req.n_kpoints; ik++) {
      // Calculate time for this k-point
      // T_clusterA = n_bands * n_basis * time_per_pair
      double cluster_a_ps = req.n_bands * req.n_basis * DFT::CLUSTER_A_TIME_PER_PAIR;

      // T_clusterB = n_basis / panel_size * time_per_panel
      int num_panels = (req.n_bands * req.n_basis + 7) / 8;
      double cluster_b_ps = num_panels * DFT::CLUSTER_B_TIME_PER_PANEL;

      // T_clusterC = n_bands * time_per_band
      double cluster_c_ps = req.n_bands * DFT::CLUSTER_C_TIME_PER_BAND;

      // T_clusterD = fixed time
      double cluster_d_ps = DFT::CLUSTER_D_TIME;

      double kpoint_time_ps = cluster_a_ps + cluster_b_ps + cluster_c_ps + cluster_d_ps;
      kpoint_time_ps += DFT::KPOINT_OVERHEAD;

      // Execute with timing
      sc_time kpoint_time(kpoint_time_ps / 1000.0, SC_NS);
      wait(kpoint_time);

      c_bands_iter_time_ns += kpoint_time_ps / 1e6;
    }
    sc_time c_bands_end = sc_time_stamp();
    result.c_bands_time_ns += c_bands_iter_time_ns;

    // === Sum band (post-processing) ===
    double sum_band_time_ns = DFT::MIXING_TIME_PER_ITER / 1000.0;
    wait(sc_time(sum_band_time_ns, SC_NS));
    result.sum_band_time_ns += sum_band_time_ns;

    // === Mix rho (charge density mixing) ===
    double mix_rho_time_ns = DFT::MIXING_TIME_PER_ITER / 1000.0;
    wait(sc_time(mix_rho_time_ns, SC_NS));
    result.mix_rho_time_ns += mix_rho_time_ns;

    // Convergence check
    dr2 = dr2 * 0.3;

    sc_time iter_end = sc_time_stamp();
    double iter_time_ns = (iter_end - iter_start).to_double();

    std::cout << "  Iteration " << iter << ": dr2 = " << dr2
              << " time = " << iter_time_ns / 1e6 << " ms" << std::endl;

    if (dr2 < req.conv_threshold) {
      result.converged = true;
      result.iterations = iter;
      result.final_error = dr2;
      break;
    }

    // Adaptive threshold adjustment
    if (iter == 1 && dr2 < ethr * req.n_bands) {
      ethr = 0.1 * dr2 / req.n_bands;
      std::cout << "  Lowering ethr to " << ethr << std::endl;
    }

    result.iterations = iter;
    result.final_error = dr2;
  }

  sc_time end_time = sc_time_stamp();
  result.total_time_ns = (end_time - start_time).to_seconds() * 1e9;

  // Calculate total energy (mock calculation)
  result.total_energy = -15.8 - 0.1 * result.iterations;

  std::cout << "[DFTHybridSystemGem5] Electrons loop completed: "
            << (result.converged ? "CONVERGED" : "NOT CONVERGED")
            << " in " << result.iterations << " iterations" << std::endl;
  std::cout << "  Final error: " << result.final_error << std::endl;
  std::cout << "  Total energy: " << result.total_energy << " Ry" << std::endl;
  std::cout << "  Total time: " << result.total_time_ns / 1e6 << " ms" << std::endl;
  std::cout << "    c_bands:  " << result.c_bands_time_ns / 1e6 << " ms" << std::endl;
  std::cout << "    sum_band: " << result.sum_band_time_ns / 1e6 << " ms" << std::endl;
  std::cout << "    mix_rho:  " << result.mix_rho_time_ns / 1e6 << " ms" << std::endl;

  return result;
}

}
