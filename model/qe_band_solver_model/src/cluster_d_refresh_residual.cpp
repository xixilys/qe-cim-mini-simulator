#include <algorithm>

#include "cluster_d_refresh_residual.hpp"

namespace qebs {

namespace {

std::string state_prefix(const std::string& software_family,
                         const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "CP2K") {
    return "cp2k_diag";
  }
  if (software_family == "VASP" && flow_family == "FAST") {
    return "vasp_fast";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

}  // namespace

ClusterDRefreshResidual::ClusterDRefreshResidual(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ClusterDOutput ClusterDRefreshResidual::run(const ClusterDInput& input) const {
  const int t_refresh = 5 + input.descriptor.band_batch;
  const int t_residual = 4 + input.inner_step;
  const int t_writeback = 3 + input.descriptor.panel_count;
  sc_core::wait(static_cast<double>(t_refresh + t_residual + t_writeback),
                sc_core::SC_NS);

  ClusterDOutput output;
  const std::string prefix =
      state_prefix(input.descriptor.software_family, input.descriptor.flow_family);
  output.p_next_object.object_handle =
      prefix + "_p_next_iter_" + std::to_string(input.descriptor.scf_iteration) +
      "_step_" + std::to_string(input.inner_step + 1);
  output.p_next_object.version = input.descriptor.scf_iteration;
  output.p_next_object.resident_buffer_tag = 500 + input.inner_step;
  output.p_next_object.producer_body = "ClusterD";
  output.p_next_object.validity_scope = "episode-window";
  output.residual_norm =
      0.72 / static_cast<double>(input.inner_step + 1) +
      0.02 * static_cast<double>(input.diag_solution.fallback_used ? 1 : 0) +
      0.01 * static_cast<double>(input.descriptor.scf_iteration - 1);
  output.updated_vector_norm =
      0.60 * input.diag_solution.coeff_norm + 0.25 * output.residual_norm;
  output.episode_continue_flag =
      output.residual_norm > 0.24 &&
      (input.inner_step + 1) < input.descriptor.max_inner_steps;
  output.metrics.cluster_name = "ClusterD";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = t_refresh + t_residual + t_writeback;
  output.metrics.backpressure_ref_cycles =
      input.diag_solution.fallback_used ? 4 : 2;
  output.metrics.data_movement_kib = input.diag_solution.emitted_kib * 1.25;
  output.metrics.dominant_resource = "ClusterD.RefreshWriteback";
  output.metrics.detail =
      "T_D_refresh=" + std::to_string(t_refresh) +
      ", T_D_residual=" + std::to_string(t_residual) +
      ", T_D_writeback=" + std::to_string(t_writeback);

  log_line(name(), "Cluster D complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
