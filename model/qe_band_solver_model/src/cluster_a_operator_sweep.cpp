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
  output.metrics.cluster_name = "ClusterA";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles =
      report.structural.total_ref_cycles +
      6 * static_cast<int>(output.panels.size()) +
      ((input.descriptor.enable_fft ||
        input.descriptor.support_grid_mode != "BYPASS")
           ? 5 * static_cast<int>(output.panels.size())
           : 0);
  output.metrics.backpressure_ref_cycles =
      report.structural.row_block_visits / 2;
  output.metrics.data_movement_kib =
      0.125 * static_cast<double>(input.descriptor.band_count *
                                  input.descriptor.panel_count *
                                  input.descriptor.panel_size);
  output.metrics.dominant_resource = report.structural.critical_domain;
  output.metrics.detail =
      "panel staging + fused h_psi/s_psi sweep with resident-context issue";

  log_line(name(), "Cluster A complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
