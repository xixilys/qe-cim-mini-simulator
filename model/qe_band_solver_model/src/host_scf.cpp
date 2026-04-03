#include <cmath>

#include "host_scf.hpp"

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

std::string projector_mode_for(const std::string& software_family,
                               const std::string& flow_family) {
  if (software_family == "VASP") {
    return "PAW-heavy";
  }
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "NC-light";
  }
  if (software_family == "CP2K") {
    return "NC-light";
  }
  return "USPP";
}

std::string workload_bucket_for(int band_count) {
  if (band_count <= 12) {
    return "small";
  }
  if (band_count <= 24) {
    return "medium";
  }
  return "large";
}

}  // namespace

HostSCF::HostSCF(sc_core::sc_module_name name, Interconnect& fabric,
                 FPGAOrchestrator& fpga)
    : sc_core::sc_module(name), fabric_(fabric), fpga_(fpga) {}

SCFState HostSCF::initialize_state(const SystemRunConfig& run_config) const {
  SCFState state;
  state.software_family = run_config.software_family;
  state.flow_family = run_config.flow_family;
  state.rho_norm = 1.0;
  if (run_config.software_family == "CP2K") {
    state.total_energy = -19.5;
  } else if (run_config.software_family == "VASP") {
    state.total_energy = -15.2;
  } else {
    state.total_energy = -11.0;
  }

  const auto prefix = state_prefix(run_config.software_family, run_config.flow_family);
  state.wave_object = {prefix + "_wave_seed", 0, 100, "HOST_INIT", "full-run"};
  state.density_object = {prefix + "_rho_seed", 0, 101, "HOST_INIT", "full-run"};
  state.potential_object = {prefix + "_veff_seed", 0, 102, "HOST_INIT", "scf-iteration"};
  state.projector_object = {prefix + "_proj_seed", 0, 103, "HOST_INIT", "episode-window"};
  state.history_object = {prefix + "_hist_seed", 0, 104, "HOST_INIT", "full-run"};

  log_line(name(), "HostSCF seeds cluster-first run context for " +
                       run_config.brief());
  return state;
}

EpisodeDescriptor HostSCF::make_episode_descriptor(const SCFState& state,
                                                   const SystemRunConfig& run_config,
                                                   int episode_id) const {
  EpisodeDescriptor descriptor;
  descriptor.scf_iteration = state.scf_iteration;
  descriptor.episode_id = episode_id;
  descriptor.band_begin = 0;
  descriptor.enable_fft = run_config.enable_fft;
  descriptor.software_family = run_config.software_family;
  descriptor.flow_family = run_config.flow_family;
  descriptor.precision_mode = "fp64-constrained";
  descriptor.wave_object = state.wave_object;
  descriptor.density_object = state.density_object;
  descriptor.potential_object = state.potential_object;
  descriptor.projector_object = state.projector_object;
  descriptor.history_object = state.history_object;

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    descriptor.band_count = 12 + 2 * (state.scf_iteration - 1);
    descriptor.panel_count = 2 + (state.scf_iteration > 2 ? 1 : 0);
    descriptor.panel_size = 12;
    descriptor.resident_row_block_size = 3;
    descriptor.max_inner_steps = 2;
    descriptor.band_batch = 6;
    descriptor.solver_mode = "OT_PRECOND_CG";
    descriptor.support_grid_mode = "AUX_GRID";
  } else if (run_config.software_family == "CP2K") {
    descriptor.band_count = 20 + 2 * (state.scf_iteration - 1);
    descriptor.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    descriptor.panel_size = 10;
    descriptor.resident_row_block_size = 5;
    descriptor.max_inner_steps = 2;
    descriptor.band_batch = 8;
    descriptor.solver_mode = "DBCSR_DIAG";
    descriptor.support_grid_mode = "FFT_AUX";
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    descriptor.band_count = 24 + 2 * (state.scf_iteration - 1);
    descriptor.panel_count = 4 + (state.scf_iteration > 2 ? 1 : 0);
    descriptor.panel_size = 12;
    descriptor.resident_row_block_size = 6;
    descriptor.max_inner_steps = 2;
    descriptor.band_batch = 8;
    descriptor.solver_mode =
        state.scf_iteration == 1 ? "BLOCKED_DAVIDSON" : "RMM_DIIS";
    descriptor.support_grid_mode = "ADDGRID";
  } else if (run_config.software_family == "VASP") {
    descriptor.band_count = 24 + 4 * (state.scf_iteration - 1);
    descriptor.panel_count = 4 + (state.scf_iteration > 1 ? 1 : 0);
    descriptor.panel_size = 12;
    descriptor.resident_row_block_size = 6;
    descriptor.max_inner_steps = 3;
    descriptor.band_batch = 8;
    descriptor.solver_mode = "BLOCKED_DAVIDSON";
    descriptor.support_grid_mode = "FINE_GRID";
  } else {
    descriptor.band_count = 16 + 4 * (state.scf_iteration - 1);
    descriptor.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    descriptor.panel_size = 8;
    descriptor.resident_row_block_size = 4;
    descriptor.max_inner_steps = 3;
    descriptor.band_batch = 4;
    descriptor.solver_mode = "DAVIDSON";
    descriptor.support_grid_mode = "BYPASS";
  }

  descriptor.workload_bucket = workload_bucket_for(descriptor.band_count);
  descriptor.projector_mode =
      projector_mode_for(run_config.software_family, run_config.flow_family);
  descriptor.preferred_diag_mode = "hardware";
  return descriptor;
}

SCFIterationClusteredReport HostSCF::finalize_iteration(
    const EpisodeResult& episode, SCFState& state) const {
  const auto& descriptor = episode.descriptor;
  const bool is_cp2k = descriptor.software_family == "CP2K";
  const bool is_vasp = descriptor.software_family == "VASP";
  const bool is_fast = descriptor.flow_family == "FAST";
  const bool is_ot = descriptor.flow_family == "QS_OT";
  const auto prefix =
      state_prefix(descriptor.software_family, descriptor.flow_family);

  SCFIterationClusteredReport iteration;
  iteration.scf_iteration = descriptor.scf_iteration;
  iteration.descriptor = descriptor;
  iteration.episode = episode;
  iteration.rho_out_norm =
      std::max(1e-6, 0.58 * episode.updated_vector_norm + 0.12 * state.rho_norm +
                         0.01 * static_cast<double>(descriptor.band_batch));
  iteration.potential_norm =
      std::max(1e-6, 0.82 * iteration.rho_out_norm +
                         0.04 * static_cast<double>(descriptor.panel_count) +
                         0.02 * static_cast<double>(descriptor.band_batch));
  iteration.density_delta =
      0.18 / static_cast<double>(descriptor.scf_iteration) +
      0.015 * episode.residual_norm +
      0.005 * (episode.controller_state.cdiaghg_mode_selected == "fallback_companion"
                   ? 1.0
                   : 0.0);
  iteration.mixed_rho_norm = std::max(1e-6, state.rho_norm - iteration.density_delta);
  const double energy_delta =
      std::abs(episode.diag_solution.lambda_base - state.total_energy) *
      (is_cp2k ? 0.24 : (is_vasp ? 0.28 : 0.30));
  iteration.energy_after_iteration =
      0.65 * state.total_energy + 0.35 * episode.diag_solution.lambda_base;
  iteration.converged =
      iteration.density_delta <=
          (is_ot ? 0.085 : (is_fast ? 0.080 : (is_vasp ? 0.078 : 0.075))) &&
      energy_delta <= (is_cp2k ? 0.24 : (is_vasp ? 0.22 : 0.18)) &&
      iteration.rho_out_norm <= (is_cp2k ? 0.55 : (is_vasp ? 0.50 : 0.43));

  state.completed_episodes += 1;
  state.completed_bodies += 4;
  state.rho_norm = iteration.mixed_rho_norm;
  state.total_energy = iteration.energy_after_iteration;
  state.converged = iteration.converged;
  state.last_density_delta = iteration.density_delta;
  state.last_data_movement_kib = episode.total_data_movement_kib;
  state.wave_object = episode.p_next_object;
  state.density_object = {prefix + "_rho_iter_" + std::to_string(descriptor.scf_iteration),
                          descriptor.scf_iteration,
                          200 + descriptor.scf_iteration,
                          "HOST_OUTER_SHELL",
                          "scf-iteration"};
  state.potential_object = {
      prefix + "_veff_iter_" + std::to_string(descriptor.scf_iteration),
      descriptor.scf_iteration,
      300 + descriptor.scf_iteration,
      "HOST_OUTER_SHELL",
      "scf-iteration"};
  state.projector_object = {
      prefix + "_proj_state_iter_" + std::to_string(descriptor.scf_iteration),
      descriptor.scf_iteration,
      320 + descriptor.scf_iteration,
      "HOST_OUTER_SHELL",
      "episode-window"};
  state.history_object = {prefix + "_hist_iter_" + std::to_string(descriptor.scf_iteration),
                          descriptor.scf_iteration,
                          420 + descriptor.scf_iteration,
                          "HOST_OUTER_SHELL",
                          "full-run"};

  log_line(name(), "Cluster-first iteration report => " + iteration.brief());
  log_line(name(), "Episode controller => " + episode.controller_state.brief());
  log_line(name(), "Cluster A => " + episode.cluster_a.brief());
  log_line(name(), "Cluster B => " + episode.cluster_b.brief());
  log_line(name(), "Cluster C => " + episode.cluster_c.brief());
  log_line(name(), "Cluster D => " + episode.cluster_d.brief());
  log_line(name(), "SCF state update => " + state.brief());

  return iteration;
}

SCFRunReport HostSCF::run_full_flow(const SystemRunConfig& run_config) const {
  SCFRunReport report;
  report.run_config = run_config;

  SCFState state = initialize_state(run_config);
  for (int iter = 1; iter <= run_config.max_scf_iters; ++iter) {
    state.scf_iteration = iter;
    const auto descriptor = make_episode_descriptor(state, run_config, 100 + iter);
    log_line(name(), "HostSCF launches cluster-first episode: " + descriptor.brief());
    fabric_.host_to_fpga("dispatch cluster-first episode " + descriptor.brief());
    const auto episode = fpga_.execute_episode(descriptor);
    fabric_.fpga_to_host("cluster-first episode return " + episode.brief());

    auto iteration = finalize_iteration(episode, state);
    report.total_episodes += 1;
    report.total_lcw_words_issued += episode.lcw_words_issued;
    report.total_row_blocks_processed += episode.row_blocks_processed;
    report.total_ref_cycles += episode.total_ref_cycles;
    report.total_backpressure_ref_cycles += episode.total_backpressure_ref_cycles;
    report.total_data_movement_kib += episode.total_data_movement_kib;
    report.iterations.push_back(iteration);

    if (state.converged) {
      report.convergence_reason = "mixed_density_converged";
      break;
    }
  }

  report.final_state = state;
  if (!state.converged) {
    report.convergence_reason = "max_scf_iters_reached";
  }
  log_line(name(), "Cluster-first full-flow report => " + report.brief());
  return report;
}

SCFState HostSCF::run_demo(const SystemRunConfig& run_config) const {
  return run_full_flow(run_config).final_state;
}

}  // namespace qebs
