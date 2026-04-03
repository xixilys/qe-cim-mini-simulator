#pragma once

#include "cluster_a_operator_sweep.hpp"
#include "cluster_b_reduced_build.hpp"
#include "cluster_c_hardware_diag.hpp"
#include "cluster_d_refresh_residual.hpp"
#include "episode_controller.hpp"

namespace qebs {

class ClusterGraphExecutor : public sc_core::sc_module {
 public:
  explicit ClusterGraphExecutor(sc_core::sc_module_name name);

  EpisodeResult run_episode(const EpisodeDescriptor& descriptor,
                            const EpisodeController& controller) const;

 private:
  ClusterAOperatorSweep cluster_a_;
  ClusterBReducedBuild cluster_b_;
  ClusterCHardwareDiag cluster_c_;
  ClusterDRefreshResidual cluster_d_;
};

}  // namespace qebs
