#include <algorithm>

#include "cluster_graph_frontdoor_sequence.hpp"
#include "cluster_a_operator_sweep.hpp"

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

ClusterAOperatorSweep::ClusterAOperatorSweep(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      near_memory_domain_(sc_core::sc_module_name("cluster_a_near_memory_domain")),
      cim_subchain_(sc_core::sc_module_name("cluster_a_cim_subchain")),
      fft_companion_(sc_core::sc_module_name("cluster_a_fft_companion")) {}

ClusterAOutput ClusterAOperatorSweep::run(const ClusterAInput& input) const {
  const auto config = make_phase_b_config(input.descriptor);
  log_line(name(),
           "Cluster A operator sweep begins: " + input.descriptor.brief() +
               ", inner_step=" + std::to_string(input.inner_step + 1));

  ClusterAOutput output;
  output.panels = near_memory_domain_.stage_panels(config);
  if (input.descriptor.enable_fft ||
      input.descriptor.support_grid_mode != "BYPASS") {
    for (auto& panel : output.panels) {
      fft_companion_.transform(panel);
    }
  }

  const auto report = cim_subchain_.run(config, output.panels, input.inner_step);
  output.partials = report.partials;
  output.resident_context = report.resident_context;
  output.lcw_words_issued = report.lcw_words_issued;
  output.row_blocks_processed = report.row_blocks_processed;
  const int panel_stage_cycles = 6 * static_cast<int>(output.panels.size());
  const int fft_stage_cycles =
      ((input.descriptor.enable_fft ||
        input.descriptor.support_grid_mode != "BYPASS")
           ? 5 * static_cast<int>(output.panels.size())
           : 0);
  int graph_ref_cycle_adjust = 0;
  int graph_backpressure_adjust = 0;
  double graph_data_scale = 1.0;
  std::string graph_detail;
  if (!input.descriptor.graph_frontdoor_mode.empty()) {
    const std::string post_a_token = graph_frontdoor::next_token_after(
        input.descriptor.graph_resolved_cluster_sequence, "A");
    const bool sequence_reordered = graph_frontdoor::sequence_differs(
        input.descriptor.graph_requested_cluster_sequence,
        input.descriptor.graph_resolved_cluster_sequence);
    const int stage_pack_pressure = std::max(
        0,
        input.descriptor.graph_module_count -
            input.descriptor.graph_leaf_component_count);
    graph_ref_cycle_adjust +=
        std::min(8, input.descriptor.graph_leaf_component_count / 2);
    graph_ref_cycle_adjust += std::min(4, input.descriptor.graph_flow_count);
    graph_backpressure_adjust +=
        std::min(2, std::max(0, input.descriptor.graph_flow_count - 1));
    if (!input.descriptor.graph_has_leaf_hotpath_flow) {
      graph_ref_cycle_adjust -= 6;
      graph_backpressure_adjust -= 1;
      graph_data_scale *= 0.82;
    }
    if (!input.descriptor.graph_has_fft_unit) {
      graph_ref_cycle_adjust -= std::min(3, static_cast<int>(output.panels.size()));
      graph_data_scale *= 0.92;
    }
    if (post_a_token == "B_bypass") {
      graph_ref_cycle_adjust -= 2;
      graph_backpressure_adjust -= 1;
      graph_data_scale *= 0.96;
    } else if (post_a_token == "B") {
      graph_ref_cycle_adjust += std::min(3, stage_pack_pressure / 4);
    }
    if (sequence_reordered) {
      graph_backpressure_adjust += 1;
    }
    if (stage_pack_pressure > 0) {
      graph_data_scale *=
          1.0 + 0.01 * static_cast<double>(std::min(4, stage_pack_pressure));
    }
    graph_detail =
        " | graph_leaf_flow=" +
        std::string(input.descriptor.graph_has_leaf_hotpath_flow ? "present" : "absent") +
        ", graph_leaf_components=" +
        std::to_string(input.descriptor.graph_leaf_component_count) +
        ", graph_modules=" +
        std::to_string(input.descriptor.graph_module_count) +
        ", graph_fft=" +
        std::string(input.descriptor.graph_has_fft_unit ? "yes" : "no") +
        ", graph_flow_count=" + std::to_string(input.descriptor.graph_flow_count) +
        ", graph_post_a=" + (post_a_token.empty() ? "unset" : post_a_token) +
        ", graph_seq_reordered=" + (sequence_reordered ? "yes" : "no");
  }
  output.metrics.cluster_name = "ClusterA";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles =
      std::max(
          1,
          report.structural.total_ref_cycles + panel_stage_cycles +
              fft_stage_cycles + graph_ref_cycle_adjust);
  output.metrics.backpressure_ref_cycles =
      std::max(
          0,
          report.structural.row_block_visits / 2 + graph_backpressure_adjust);
  output.metrics.data_movement_kib =
      0.125 * static_cast<double>(input.descriptor.band_count *
                                  input.descriptor.panel_count *
                                  input.descriptor.panel_size) *
      graph_data_scale;
  output.metrics.dominant_resource = report.structural.critical_domain;
  output.metrics.detail =
      "panel staging + fused h_psi/s_psi sweep with resident-context issue" +
      graph_detail;

  log_line(name(), "Cluster A complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
