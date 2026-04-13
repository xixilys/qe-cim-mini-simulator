#include "dft_hybrid_system.hpp"

namespace qebs {

DFTHybridSystem::DFTHybridSystem(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      fabric_(sc_core::sc_module_name("interconnect")),
      chip_(sc_core::sc_module_name("chip_top")),
      fpga_(sc_core::sc_module_name("fpga_orchestrator"), fabric_, chip_),
      host_(sc_core::sc_module_name("host_scf"), fabric_, fpga_) {}

SCFRunReport DFTHybridSystem::run_full_flow(const SystemRunConfig& run_config) const {
  log_line(name(), "DFTHybridSystem starts run: " + run_config.brief());
  auto report = host_.run_full_flow(run_config);
  log_line(name(), "DFTHybridSystem host-managed run complete: " + report.brief());
  return report;
}

SCFState DFTHybridSystem::run_demo(const SystemRunConfig& run_config) const {
  return run_full_flow(run_config).final_state;
}

}  // namespace qebs
