#pragma once

#include "cluster_graph_executor.hpp"

namespace qebs {

class ChipTop : public sc_core::sc_module {
 public:
  explicit ChipTop(sc_core::sc_module_name name);

  EpisodeResult run_episode(const EpisodeDescriptor& descriptor) const;

  // Legacy adapters retained only so archive-era sources still compile.
  EpisodeSummary run_episode(const EpisodeConfig& config) const;
  EpisodeSummary run_replay_bundle(const ReplayBundleDescriptor& descriptor) const;

 private:
  EpisodeController episode_controller_;
  ClusterGraphExecutor cluster_graph_executor_;
};

}  // namespace qebs
