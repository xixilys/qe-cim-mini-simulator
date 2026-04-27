#pragma once

#include "architecture_config.hpp"
#include "chip_top.hpp"
#include "fpga_orchestrator.hpp"
#include "host_scf.hpp"
#include "interconnect.hpp"

namespace qebs {

class DFTHybridSystem : public sc_core::sc_module {
 public:
  DFTHybridSystem(sc_core::sc_module_name name, const ArchitectureConfig& config);
  
  explicit DFTHybridSystem(sc_core::sc_module_name name);
  
  SCFState run_demo(const SystemRunConfig& run_config) const;
  SCFRunReport run_full_flow(const SystemRunConfig& run_config) const;

 private:
  ArchitectureConfig config_;
  Interconnect fabric_;
  ChipTop chip_;
  FPGAOrchestrator fpga_;
  HostSCF host_;
};

}  // namespace qebs
