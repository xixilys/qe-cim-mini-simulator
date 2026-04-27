#include <algorithm>

#include "cluster_graph_frontdoor_sequence.hpp"
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
  int t_refresh = 5 + input.descriptor.band_batch;
  const int t_residual = 4 + input.inner_step;
  int t_writeback = 3 + input.descriptor.panel_count;
  std::string graph_detail;
  bool deferred_refresh_after_diag = false;
  if (!input.descriptor.graph_frontdoor_mode.empty()) {
    const std::string post_c_token = graph_frontdoor::next_token_after(
        input.descriptor.graph_resolved_cluster_sequence, "C");
    const int downstream_module_pressure = std::max(
        0,
        input.descriptor.graph_module_count -
            input.descriptor.graph_leaf_component_count);
    deferred_refresh_after_diag =
        input.descriptor.graph_prefers_refresh_before_diag && post_c_token == "D";
    t_refresh += std::min(3, input.descriptor.graph_flow_count);
    if (input.descriptor.graph_has_vector_diag_companion) {
      t_refresh += 1;
    }
    if (deferred_refresh_after_diag) {
      t_refresh += 2;
      t_writeback += 1;
    }
    if (!input.descriptor.graph_has_leaf_hotpath_flow) {
      t_writeback = std::max(1, t_writeback - 1);
    }
    t_writeback += std::min(2, downstream_module_pressure / 8);
    graph_detail =
        " | graph_refresh=yes, graph_vdiag=" +
        std::string(input.descriptor.graph_has_vector_diag_companion ? "yes" : "no") +
        ", graph_leaf_flow=" +
        std::string(input.descriptor.graph_has_leaf_hotpath_flow ? "present" : "absent") +
        ", graph_flow_count=" + std::to_string(input.descriptor.graph_flow_count) +
        ", graph_modules=" + std::to_string(input.descriptor.graph_module_count) +
        ", graph_refresh_before_diag=" +
        std::string(input.descriptor.graph_prefers_refresh_before_diag ? "yes" : "no") +
        ", graph_post_c=" + (post_c_token.empty() ? "unset" : post_c_token);
  }
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
      0.01 * static_cast<double>(input.descriptor.scf_iteration - 1) -
      (!input.descriptor.graph_frontdoor_mode.empty() &&
               input.descriptor.graph_has_vector_diag_companion
           ? 0.01
           : 0.0);
  if (deferred_refresh_after_diag) {
    output.residual_norm -= 0.01;
  }
  output.updated_vector_norm =
      0.60 * input.diag_solution.coeff_norm + 0.25 * output.residual_norm;
  output.episode_continue_flag =
      output.residual_norm > 0.24 &&
      (input.inner_step + 1) < input.descriptor.max_inner_steps;
  output.metrics.cluster_name = "ClusterD";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = t_refresh + t_residual + t_writeback;
  output.metrics.backpressure_ref_cycles =
      (input.diag_solution.fallback_used ? 4 : 2) +
      (deferred_refresh_after_diag ? 1 : 0);
  output.metrics.data_movement_kib = input.diag_solution.emitted_kib * 1.25;
  output.metrics.dominant_resource = "ClusterD.RefreshWriteback";
  output.metrics.detail =
      "T_D_refresh=" + std::to_string(t_refresh) +
      ", T_D_residual=" + std::to_string(t_residual) +
      ", T_D_writeback=" + std::to_string(t_writeback) + graph_detail;

  log_line(name(), "Cluster D complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
