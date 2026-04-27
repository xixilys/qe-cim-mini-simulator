#include "chip_top.hpp"
#include "logging.hpp"

namespace qebs {

namespace {

EpisodeDescriptor make_descriptor_from_legacy_config(const EpisodeConfig& config) {
  EpisodeDescriptor descriptor;
  descriptor.scf_iteration = config.scf_iteration;
  descriptor.episode_id = config.episode_id;
  descriptor.band_begin = config.band_begin;
  descriptor.band_count = config.band_count;
  descriptor.panel_count = config.panel_count;
  descriptor.panel_size = config.panel_size;
  descriptor.resident_row_block_size = config.resident_row_block_size;
  descriptor.max_inner_steps = config.max_inner_steps;
  descriptor.band_batch = config.band_batch;
  descriptor.enable_fft = config.enable_fft;
  descriptor.software_family = config.software_family;
  descriptor.flow_family = config.flow_family;
  descriptor.solver_mode = config.solver_mode;
  descriptor.support_grid_mode = config.support_grid_mode;
  descriptor.precision_mode = config.precision_constraint;
  descriptor.workload_bucket =
      config.band_count <= 12 ? "small" : (config.band_count <= 24 ? "medium" : "large");
  descriptor.projector_mode =
      config.software_family == "QE" ? "USPP" : "NC-light";
  descriptor.preferred_diag_mode = "hardware";
  descriptor.wave_object = {"legacy_wave_seed", 0, 100, "BODY_00", "episode-window"};
  descriptor.density_object = {"legacy_rho_seed", 0, 101, "BODY_00", "scf-iteration"};
  descriptor.potential_object = {"legacy_veff_seed", 0, 102, "BODY_00", "scf-iteration"};
  descriptor.projector_object = {"legacy_proj_seed", 0, 103, "BODY_00", "episode-window"};
  descriptor.history_object = {"legacy_hist_seed", 0, 104, "BODY_05", "full-run"};
  return descriptor;
}

EpisodeSummary make_legacy_episode_summary(const EpisodeResult& result) {
  EpisodeSummary summary;
  summary.config.scf_iteration = result.descriptor.scf_iteration;
  summary.config.episode_id = result.descriptor.episode_id;
  summary.config.band_begin = result.descriptor.band_begin;
  summary.config.band_count = result.descriptor.band_count;
  summary.config.panel_count = result.descriptor.panel_count;
  summary.config.panel_size = result.descriptor.panel_size;
  summary.config.resident_row_block_size = result.descriptor.resident_row_block_size;
  summary.config.max_inner_steps = result.descriptor.max_inner_steps;
  summary.config.band_batch = result.descriptor.band_batch;
  summary.config.enable_fft = result.descriptor.enable_fft;
  summary.config.software_family = result.descriptor.software_family;
  summary.config.flow_family = result.descriptor.flow_family;
  summary.config.solver_mode = result.descriptor.solver_mode;
  summary.config.support_grid_mode = result.descriptor.support_grid_mode;
  summary.config.precision_constraint = result.descriptor.precision_mode;
  summary.full_hs = result.full_hs;
  summary.reduced = result.reduced;
  summary.ritz.active_vectors = result.diag_solution.eigenpair_count;
  summary.ritz.et = result.diag_solution.lambda_base;
  summary.ritz.evc_norm = result.diag_solution.coeff_norm;
  summary.residual.residual_norm = result.residual_norm;
  summary.residual.updated_vector_norm = result.updated_vector_norm;
  summary.residual.episode_done = result.converged_inner_loop;
  summary.resident_context_id = result.resident_context.resident_context_id;
  summary.resident_generation = result.resident_context.generation;
  summary.lcw_words_issued = result.lcw_words_issued;
  summary.row_blocks_processed = result.row_blocks_processed;
  summary.structural.total_ref_cycles = result.total_ref_cycles;
  summary.flow_control.total_backpressure_ref_cycles =
      result.total_backpressure_ref_cycles;
  summary.status = result.status;
  return summary;
}

}  // namespace

ChipTop::ChipTop(sc_core::sc_module_name name, const ArchitectureConfig& config)
    : sc_core::sc_module(name),
      config_(config),
      episode_controller_(sc_core::sc_module_name("episode_controller")),
      cluster_graph_executor_(sc_core::sc_module_name("cluster_graph_executor"), config) {
  log_line(std::string(name), "ChipTop initialized with architecture: " + config.template_label);
}

ChipTop::ChipTop(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      config_(ArchitectureConfig::create_default()),
      episode_controller_(sc_core::sc_module_name("episode_controller")),
      cluster_graph_executor_(sc_core::sc_module_name("cluster_graph_executor"), config_) {
  log_line(std::string(name), "ChipTop initialized with default architecture");
}

EpisodeResult ChipTop::run_episode(const EpisodeDescriptor& descriptor) const {
  log_line(name(), "ChipTop cluster-first episode begins: " + descriptor.brief());
  auto result =
      cluster_graph_executor_.run_episode(descriptor, episode_controller_);
  log_line(name(), "ChipTop cluster-first episode complete: " + result.brief());
  log_line(name(), "Cluster A => " + result.cluster_a.brief());
  log_line(name(), "Cluster B => " + result.cluster_b.brief());
  log_line(name(), "Cluster C => " + result.cluster_c.brief());
  log_line(name(), "Cluster D => " + result.cluster_d.brief());
  return result;
}

EpisodeSummary ChipTop::run_episode(const EpisodeConfig& config) const {
  return make_legacy_episode_summary(run_episode(make_descriptor_from_legacy_config(config)));
}

EpisodeSummary ChipTop::run_replay_bundle(
    const ReplayBundleDescriptor& descriptor) const {
  if (!descriptor.has_phase_b_config) {
    EpisodeSummary rejected;
    rejected.status = "legacy-replay-rejected";
    return rejected;
  }
  return run_episode(descriptor.phase_b_config);
}

}  // namespace qebs
