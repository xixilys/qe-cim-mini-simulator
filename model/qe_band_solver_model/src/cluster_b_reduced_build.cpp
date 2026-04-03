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
  output.metrics.cluster_name = "ClusterB";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = 18;
  output.metrics.backpressure_ref_cycles = output.spill_flag ? 4 : 1;
  output.metrics.data_movement_kib =
      2.0 * static_cast<double>(output.reduced.reduced_dim *
                                output.reduced.reduced_dim) *
      8.0 / 1024.0;
  output.metrics.dominant_resource = "ReductionClosureEngine";
  output.metrics.detail =
      "partial aggregation + reduced H_sub/S_sub closure before diag handoff";

  log_line(name(), "Cluster B complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
