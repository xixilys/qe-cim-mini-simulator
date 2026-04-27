#pragma once

#include "architecture_config.hpp"
#include "clusters/cluster_graph_executor.hpp"

namespace qebs {

class ChipTop : public sc_core::sc_module {
 public:
  ChipTop(sc_core::sc_module_name name, const ArchitectureConfig& config);
  
  explicit ChipTop(sc_core::sc_module_name name);

  EpisodeResult run_episode(const EpisodeDescriptor& descriptor) const;

  EpisodeSummary run_episode(const EpisodeConfig& config) const;
  EpisodeSummary run_replay_bundle(const ReplayBundleDescriptor& descriptor) const;

 private:
  ArchitectureConfig config_;
  EpisodeController episode_controller_;
  ClusterGraphExecutor cluster_graph_executor_;
};

}  // namespace qebs
