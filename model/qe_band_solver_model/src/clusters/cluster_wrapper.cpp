#include "clusters/cluster_wrapper.hpp"
#include "architecture_config.hpp"
#include "clusters/cluster_a_operator_sweep.hpp"
#include "clusters/cluster_b_reduced_build.hpp"
#include "clusters/cluster_c_hardware_diag.hpp"
#include "clusters/cluster_d_refresh_residual.hpp"

namespace qebs {

ClusterAWrapper::ClusterAWrapper(ClusterAOperatorSweep* cluster, ClusterType type, const std::string& id)
    : cluster_(cluster), type_(type), id_(id) {}

sc_core::sc_module* ClusterAWrapper::get_module() {
  return cluster_;
}

ClusterAOutput ClusterAWrapper::run_a(const ClusterAInput& input) const {
  return cluster_->run(input);
}

ClusterBWrapper::ClusterBWrapper(ClusterBReducedBuild* cluster, ClusterType type, const std::string& id)
    : cluster_(cluster), type_(type), id_(id) {}

sc_core::sc_module* ClusterBWrapper::get_module() {
  return cluster_;
}

ClusterBOutput ClusterBWrapper::run_b(const ClusterBInput& input) const {
  return cluster_->run(input);
}

ClusterCWrapper::ClusterCWrapper(ClusterCHardwareDiag* cluster, ClusterType type, const std::string& id)
    : cluster_(cluster), type_(type), id_(id) {}

sc_core::sc_module* ClusterCWrapper::get_module() {
  return cluster_;
}

ClusterCOutput ClusterCWrapper::run_c(const ClusterCInput& input) const {
  return cluster_->run(input);
}

ClusterDWrapper::ClusterDWrapper(ClusterDRefreshResidual* cluster, ClusterType type, const std::string& id)
    : cluster_(cluster), type_(type), id_(id) {}

sc_core::sc_module* ClusterDWrapper::get_module() {
  return cluster_;
}

ClusterDOutput ClusterDWrapper::run_d(const ClusterDInput& input) const {
  return cluster_->run(input);
}

}
