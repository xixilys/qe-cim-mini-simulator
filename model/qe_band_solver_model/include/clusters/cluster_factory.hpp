#pragma once

#include "architecture_config.hpp"
#include "cluster_a_operator_sweep.hpp"
#include "cluster_b_reduced_build.hpp"
#include "cluster_c_hardware_diag.hpp"
#include "cluster_d_refresh_residual.hpp"
#include "systemc_compat.hpp"

namespace qebs {

class ClusterFactory {
 public:
  static sc_core::sc_module* create_cluster(
      const ClusterConfig& config,
      sc_core::sc_module_name name);
  
  static std::string get_default_name(ClusterType type, int index);
};

}  // namespace qebs
