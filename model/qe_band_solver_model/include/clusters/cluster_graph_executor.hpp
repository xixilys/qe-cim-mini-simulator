#pragma once

#include <memory>
#include <vector>
#include "architecture_config.hpp"
#include "cluster_wrapper.hpp"
#include "episode_controller.hpp"

namespace qebs {

class ClusterGraphExecutor : public sc_core::sc_module {
 public:
  ClusterGraphExecutor(sc_core::sc_module_name name, const ArchitectureConfig& config);
  
  explicit ClusterGraphExecutor(sc_core::sc_module_name name);

  EpisodeResult run_episode(const EpisodeDescriptor& descriptor,
                            const EpisodeController& controller) const;

 private:
  void initialize_clusters();
  
  ArchitectureConfig config_;
  std::vector<std::unique_ptr<ClusterWrapper>> clusters_;
  
  ClusterWrapper* find_cluster_by_type(ClusterType type) const;
};

}  // namespace qebs
