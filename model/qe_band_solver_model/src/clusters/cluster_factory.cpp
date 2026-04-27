#include "clusters/cluster_factory.hpp"
#include <stdexcept>
#include <sstream>

namespace qebs {

sc_core::sc_module* ClusterFactory::create_cluster(
    const ClusterConfig& config,
    sc_core::sc_module_name name) {
  
  switch (config.type) {
    case ClusterType::OPERATOR_SWEEP:
      return new ClusterAOperatorSweep(name);
    
    case ClusterType::REDUCED_BUILD:
      return new ClusterBReducedBuild(name);
    
    case ClusterType::HARDWARE_DIAG:
      return new ClusterCHardwareDiag(name);
    
    case ClusterType::REFRESH_RESIDUAL:
      return new ClusterDRefreshResidual(name);
    
    default: {
      std::ostringstream oss;
      oss << "Unknown cluster type: " << static_cast<int>(config.type);
      throw std::runtime_error(oss.str());
    }
  }
}

std::string ClusterFactory::get_default_name(ClusterType type, int index) {
  std::ostringstream oss;
  
  switch (type) {
    case ClusterType::OPERATOR_SWEEP:
      oss << "cluster_a_" << index;
      break;
    case ClusterType::REDUCED_BUILD:
      oss << "cluster_b_" << index;
      break;
    case ClusterType::HARDWARE_DIAG:
      oss << "cluster_c_" << index;
      break;
    case ClusterType::REFRESH_RESIDUAL:
      oss << "cluster_d_" << index;
      break;
    default:
      oss << "cluster_unknown_" << index;
      break;
  }
  
  return oss.str();
}

}
