#pragma once

#include "chip_top.hpp"
#include "interconnect.hpp"
#include "replay_bundle_executor.hpp"

namespace qebs {

class FPGAOrchestrator : public sc_core::sc_module {
 public:
  FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric, ChipTop& chip);
  ReplayBundleCompletion execute_replay_bundle(
      const ReplayBundleDescriptor& descriptor) const;
  EpisodeSummary execute_episode(const EpisodeConfig& config) const;
  EpisodeSummary execute_phase_b_episode(const EpisodeConfig& config) const;
  Body10BundleSummary execute_body10_family(const Body10BundleRequest& request) const;
  Body04BundleSummary execute_body04_family(const Body04BundleRequest& request) const;

 private:
  Interconnect& fabric_;
  ChipTop& chip_;
  ReplayBundleExecutor replay_bundle_executor_;
};

}  // namespace qebs
