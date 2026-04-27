#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class EpisodeController : public sc_core::sc_module {
 public:
  explicit EpisodeController(sc_core::sc_module_name name);

  EpisodeControllerState begin_episode(const EpisodeDescriptor& descriptor) const;
  void observe_cluster_a(const ClusterAOutput& output,
                         EpisodeControllerState& state) const;
  void observe_cluster_b(const ClusterBOutput& output,
                         EpisodeControllerState& state) const;
  void observe_cluster_c(const ClusterCOutput& output,
                         EpisodeControllerState& state) const;
  void observe_cluster_d(const ClusterDOutput& output,
                         EpisodeControllerState& state) const;
  bool should_continue(const ClusterDOutput& output,
                       const EpisodeDescriptor& descriptor,
                       int inner_step) const;
  void finalize_episode(EpisodeResult& result) const;
};

}  // namespace qebs
