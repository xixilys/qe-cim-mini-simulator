#pragma once

#include "fpga_orchestrator.hpp"

namespace qebs {

class HostSCF : public sc_core::sc_module {
 public:
  HostSCF(sc_core::sc_module_name name, Interconnect& fabric, FPGAOrchestrator& fpga);
  SCFState run_demo(const SystemRunConfig& run_config = SystemRunConfig()) const;
  DFTRunReport run_full_flow(const SystemRunConfig& run_config = SystemRunConfig()) const;

 private:
  SCFState initialize_state(const SystemRunConfig& run_config) const;
  EpisodeConfig make_episode_config(const SCFState& state,
                                    const SystemRunConfig& run_config,
                                    int episode_id) const;
  ReplayBundleDescriptor make_phase_b_bundle(const EpisodeConfig& config) const;
  ReplayBundleDescriptor make_body10_bundle(const Body10BundleRequest& request) const;
  ReplayBundleDescriptor make_body04_bundle(const Body04BundleRequest& request) const;
  void update_state_from_iteration(const EpisodeSummary& summary,
                                   const Body04BundleSummary& body04_summary,
                                   const Body10BundleSummary* body10_summary,
                                   SCFState& state) const;

  Interconnect& fabric_;
  FPGAOrchestrator& fpga_;
};

}  // namespace qebs
