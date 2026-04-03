#pragma once

#include "fpga_orchestrator.hpp"

namespace qebs {

class HostSCF : public sc_core::sc_module {
 public:
  HostSCF(sc_core::sc_module_name name, Interconnect& fabric, FPGAOrchestrator& fpga);
  SCFState run_demo(const SystemRunConfig& run_config = SystemRunConfig()) const;
  SCFRunReport run_full_flow(const SystemRunConfig& run_config = SystemRunConfig()) const;

 private:
  SCFState initialize_state(const SystemRunConfig& run_config) const;
  EpisodeDescriptor make_episode_descriptor(const SCFState& state,
                                           const SystemRunConfig& run_config,
                                           int episode_id) const;
  SCFIterationClusteredReport finalize_iteration(const EpisodeResult& episode,
                                                 SCFState& state) const;

  Interconnect& fabric_;
  FPGAOrchestrator& fpga_;
};

}  // namespace qebs
