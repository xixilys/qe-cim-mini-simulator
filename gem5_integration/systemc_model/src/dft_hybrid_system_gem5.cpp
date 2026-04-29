#include "dft_hybrid_system_gem5.hpp"
#include "dft_hybrid_system.hpp"
#include "gem5_bridge.hpp"
#include <iostream>
#include <iomanip>
#include <cmath>
#include <algorithm>

// Timed-functional proxy parameters; these are not RTL/cycle-accurate claims.
// Assuming proxy 200 MHz clock = 5ns period.
namespace DFT {
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
      gem5_bridge_(nullptr),
      main_system_(new DFTHybridSystem(
          sc_core::sc_module_name(sc_core::sc_gen_unique_name("qebs_main_path")), config)) {
  if (enable_gem5_bridge) {
    gem5_bridge_ = new Gem5Bridge("gem5_bridge", this);
  }
}

DFTHybridSystemGem5::DFTHybridSystemGem5(sc_core::sc_module_name name)
    : DFTHybridSystemGem5(name, ArchitectureConfig::create_default(), true) {}

DFTHybridSystemGem5::~DFTHybridSystemGem5() {
  delete gem5_bridge_;
  delete main_system_;
}

SCFState DFTHybridSystemGem5::run_demo(const SystemRunConfig& run_config) const {
  return run_scf(run_config).final_state;
}

SCFRunReport DFTHybridSystemGem5::run_scf(const SystemRunConfig& run_config) const {
  std::cout << "[DFTHybridSystemGem5] run_scf delegates to qe_band_solver_model main path"
            << std::endl;
  if (!main_system_) {
    SCFRunReport report;
    report.run_config = run_config;
    report.final_state.converged = false;
    report.convergence_reason = "main_path_unavailable";
    return report;
  }
  return main_system_->run_full_flow(run_config);
}

void DFTHybridSystemGem5::execute_c_bands_from_gem5(const CBandsRequest& req) {
  sc_time start_time = sc_time_stamp();

  std::cout << "[DFTHybridSystemGem5] Received c_bands request from gem5:" << std::endl;
  std::cout << "  Matrix dimensions: n=" << req.n << " m=" << req.m << " k=" << req.k << std::endl;
  std::cout << "  H matrix address: 0x" << std::hex << req.h_matrix_addr << std::dec << std::endl;
  std::cout << "  S matrix address: 0x" << std::hex << req.s_matrix_addr << std::dec << std::endl;
  std::cout << "  Result address: 0x" << std::hex << req.result_addr << std::dec << std::endl;

  // Calculate proxy execution time
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

  // Simulate proxy hardware execution time
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
  result.device_busy_ns = 0;
  result.dma_read_bytes = 0;
  result.dma_write_bytes = 0;
  result.bytes_moved_to_convergence = 0;
  result.fallback_ratio = 0.0;
  result.resident_reuse_ratio = 0.0;
  result.spill_ratio = 0.0;

  SystemRunConfig run_config;
  run_config.software_family = "QE";
  run_config.flow_family = "CBANDS_DIAG";
  run_config.case_id = "gem5_electrons_proxy";
  run_config.architecture_family =
      config_.architecture_family.empty() ? "F2" : config_.architecture_family;
  run_config.assumption_set_id = "gem5_systemc_timed_proxy";
  run_config.max_scf_iters = std::max(1, req.max_iterations);
  run_config.enable_fft = req.enable_cim;
  run_config.device_diag_max_dim =
      std::max(4, std::min(req.n_bands > 0 ? req.n_bands : 16, 64));
  run_config.force_host_diag = !req.enable_cim;
  run_config.allow_cpu_diag_fallback = true;

  const SCFRunReport report = run_scf(run_config);

  result.converged = report.final_state.converged;
  result.iterations = static_cast<int>(report.iterations.size());
  result.final_error = report.final_state.last_density_delta;
  if (!report.iterations.empty()) {
    result.final_error = report.iterations.back().completion.residual_norm;
  }
  result.total_energy = report.final_state.total_energy;
  result.device_busy_ns = static_cast<uint64_t>(std::max(0, report.total_device_busy_ref_cycles));
  result.total_time_ns = static_cast<double>(std::max(0, report.total_ref_cycles));
  result.c_bands_time_ns = static_cast<double>(std::max(0, report.total_device_busy_ref_cycles));
  result.sum_band_time_ns = static_cast<double>(std::max(0, report.total_host_assist_ref_cycles));
  result.mix_rho_time_ns = static_cast<double>(std::max(0, report.total_backpressure_ref_cycles));
  result.dma_read_bytes = static_cast<uint64_t>(
      std::max(0.0, report.total_dma_read_kib) * 1024.0);
  result.dma_write_bytes = static_cast<uint64_t>(
      std::max(0.0, report.total_dma_write_kib) * 1024.0);
  result.bytes_moved_to_convergence = static_cast<uint64_t>(
      std::max(0.0, report.total_data_movement_kib) * 1024.0);
  const double total_episodes =
      std::max(1.0, static_cast<double>(report.total_episodes));
  result.fallback_ratio =
      static_cast<double>(report.total_cpu_fallbacks) / total_episodes;
  result.resident_reuse_ratio =
      static_cast<double>(report.resident_reuse_hits) / total_episodes;
  int spill_count = 0;
  for (const auto& iteration : report.iterations) {
    if (iteration.completion.spill_active) {
      ++spill_count;
    }
  }
  result.spill_ratio = static_cast<double>(spill_count) / total_episodes;

  sc_time end_time = sc_time_stamp();
  const double elapsed_time_ns = (end_time - start_time).to_seconds() * 1e9;
  result.total_time_ns = std::max(result.total_time_ns, elapsed_time_ns);

  std::cout << "[DFTHybridSystemGem5] Electrons loop completed: "
            << (result.converged ? "CONVERGED" : "NOT CONVERGED")
            << " in " << result.iterations << " iterations" << std::endl;
  std::cout << "  Final error: " << result.final_error << std::endl;
  std::cout << "  Total energy: " << result.total_energy << " Ry" << std::endl;
  std::cout << "  Total time: " << result.total_time_ns / 1e6 << " ms" << std::endl;
  std::cout << "    device_busy: " << result.device_busy_ns << " ns" << std::endl;
  std::cout << "    dma_read:    " << result.dma_read_bytes << " bytes" << std::endl;
  std::cout << "    dma_write:   " << result.dma_write_bytes << " bytes" << std::endl;

  return result;
}

}
