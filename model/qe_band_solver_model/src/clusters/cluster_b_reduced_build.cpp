#include <algorithm>

#include "cluster_graph_frontdoor_sequence.hpp"
#include "cluster_b_reduced_build.hpp"

namespace qebs {

namespace {

EpisodeConfig make_phase_b_config(const EpisodeDescriptor& descriptor) {
  EpisodeConfig config;
  config.scf_iteration = descriptor.scf_iteration;
  config.episode_id = descriptor.episode_id;
  config.band_begin = descriptor.band_begin;
  config.band_count = descriptor.band_count;
  config.panel_count = descriptor.panel_count;
  config.panel_size = descriptor.panel_size;
  config.resident_row_block_size = descriptor.resident_row_block_size;
  config.max_inner_steps = descriptor.max_inner_steps;
  config.band_batch = descriptor.band_batch;
  config.enable_fft = descriptor.enable_fft;
  config.software_family = descriptor.software_family;
  config.flow_family = descriptor.flow_family;
  config.solver_mode = descriptor.solver_mode;
  config.support_grid_mode = descriptor.support_grid_mode;
  config.precision_constraint = descriptor.precision_mode;
  return config;
}

}  // namespace

ClusterBReducedBuild::ClusterBReducedBuild(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      near_memory_domain_(sc_core::sc_module_name("cluster_b_near_memory_domain")),
      reduction_closure_engine_(
          sc_core::sc_module_name("cluster_b_reduction_closure_engine")) {}

ClusterBOutput ClusterBReducedBuild::run(const ClusterBInput& input) const {
  const auto config = make_phase_b_config(input.descriptor);
  log_line(name(), "Cluster B reduced build begins: inner_step=" +
                       std::to_string(input.inner_step + 1) +
                       ", partials=" + std::to_string(input.partials.size()));

  ClusterBOutput output;
  output.full_hs = near_memory_domain_.local_aggregate(config, input.partials);
  output.reduced = reduction_closure_engine_.close(config, output.full_hs);
  output.spill_flag = input.descriptor.workload_bucket == "large" &&
                      output.reduced.reduced_dim >= 8;
  int graph_ref_cycle_adjust = 0;
  int graph_backpressure_adjust = 0;
  double graph_data_scale = 1.0;
  std::string graph_detail;
  if (!input.descriptor.graph_frontdoor_mode.empty()) {
    const std::string post_b_token = graph_frontdoor::next_token_after(
        input.descriptor.graph_resolved_cluster_sequence, "B");
    const int stage_tail_pressure = std::max(
        0,
        input.descriptor.graph_module_count -
            input.descriptor.graph_leaf_component_count);
    graph_ref_cycle_adjust += std::min(4, input.descriptor.graph_flow_count);
    if (input.descriptor.graph_has_vector_diag_companion) {
      graph_ref_cycle_adjust += 2;
    }
    if (!input.descriptor.graph_has_leaf_hotpath_flow) {
      graph_ref_cycle_adjust -= 2;
      graph_backpressure_adjust -= 1;
      graph_data_scale *= 0.90;
    }
    if (post_b_token == "C_bypass") {
      graph_ref_cycle_adjust -= 3;
      graph_data_scale *= 0.88;
    } else if (post_b_token == "C") {
      graph_ref_cycle_adjust += std::min(2, stage_tail_pressure / 6);
    }
    if (input.descriptor.graph_prefers_refresh_before_diag &&
        post_b_token == "C") {
      graph_ref_cycle_adjust += 1;
      graph_backpressure_adjust += 1;
    }
    graph_detail =
        " | graph_vdiag=" +
        std::string(input.descriptor.graph_has_vector_diag_companion ? "yes" : "no") +
        ", graph_leaf_flow=" +
        std::string(input.descriptor.graph_has_leaf_hotpath_flow ? "present" : "absent") +
        ", graph_flow_count=" + std::to_string(input.descriptor.graph_flow_count) +
        ", graph_modules=" + std::to_string(input.descriptor.graph_module_count) +
        ", graph_post_b=" + (post_b_token.empty() ? "unset" : post_b_token) +
        ", graph_refresh_before_diag=" +
        std::string(input.descriptor.graph_prefers_refresh_before_diag ? "yes" : "no");
  }
  output.metrics.cluster_name = "ClusterB";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = std::max(8, 18 + graph_ref_cycle_adjust);
  output.metrics.backpressure_ref_cycles =
      std::max(0, (output.spill_flag ? 4 : 1) + graph_backpressure_adjust);
  output.metrics.data_movement_kib =
      2.0 * static_cast<double>(output.reduced.reduced_dim *
                                output.reduced.reduced_dim) *
      8.0 / 1024.0 * graph_data_scale;
  output.metrics.dominant_resource = "ReductionClosureEngine";
  output.metrics.detail =
      "partial aggregation + reduced H_sub/S_sub closure before diag handoff" +
      graph_detail;

  log_line(name(), "Cluster B complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
