#pragma once

#include "chip_top.hpp"
#include "fpga_orchestrator.hpp"
#include "host_scf.hpp"
#include "interconnect.hpp"

namespace qebs {

class DFTHybridSystem : public sc_core::sc_module {
 public:
  explicit DFTHybridSystem(sc_core::sc_module_name name);
  SCFState run_demo(const SystemRunConfig& run_config) const;
  DFTRunReport run_full_flow(const SystemRunConfig& run_config) const;

 private:
  Interconnect fabric_;
  ChipTop chip_;
  FPGAOrchestrator fpga_;
  HostSCF host_;
};

}  // namespace qebs
