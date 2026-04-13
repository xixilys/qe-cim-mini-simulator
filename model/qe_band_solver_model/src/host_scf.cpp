#include <algorithm>
#include <cmath>

#include "architecture_template.hpp"
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

  log_line(name(), "Host CPU seeds host-managed run context for " +
                       run_config.brief());
  return state;
}

ResidentSetDesc HostSCF::make_resident_set_desc(const SCFState& state,
                                                const SystemRunConfig& run_config,
                                                int episode_id) const {
  const auto template_config = resolve_architecture_template(run_config);
  ResidentSetDesc resident;
  resident.resident_set_id =
      state_prefix(run_config.software_family, run_config.flow_family) + "_" +
      projector_mode_for(run_config.software_family, run_config.flow_family) +
      "_" + template_config.template_id + "_resident";
  resident.generation = state.projector_object.version;
  resident.software_family = run_config.software_family;
  resident.projector_mode =
      projector_mode_for(run_config.software_family, run_config.flow_family);
  resident.projector_object = state.projector_object;
  resident.potential_slice_object = {
      state_prefix(run_config.software_family, run_config.flow_family) +
          "_veff_slice_" + std::to_string(episode_id),
      state.potential_object.version,
      state.potential_object.resident_buffer_tag,
      "HOST_VEFF_SLICE",
      "episode-window"};

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    resident.support_grid_mode = "AUX_GRID";
    resident.resident_kib = 84.0;
    resident.preload_kib = 52.0;
  } else if (run_config.software_family == "CP2K") {
    resident.support_grid_mode = "FFT_AUX";
    resident.resident_kib = 124.0;
    resident.preload_kib = 72.0;
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    resident.support_grid_mode = "ADDGRID";
    resident.resident_kib = 188.0;
    resident.preload_kib = 116.0;
  } else if (run_config.software_family == "VASP") {
    resident.support_grid_mode = "FINE_GRID";
    resident.resident_kib = 236.0;
    resident.preload_kib = 144.0;
  } else {
    resident.support_grid_mode = "BYPASS";
    resident.resident_kib = 108.0;
    resident.preload_kib = 64.0;
  }

  resident.resident_kib *= template_config.resident_budget_scale;
  resident.preload_kib *= template_config.resident_budget_scale;
  resident.reuse_fft_support =
      template_config.enable_device_fft &&
      (state.scf_iteration > 1 || run_config.software_family != "QE");
  return resident;
}

BandBatchDesc HostSCF::make_band_batch_desc(const SCFState& state,
                                            const SystemRunConfig& run_config,
                                            int episode_id) const {
  BandBatchDesc batch;
  batch.batch_id = episode_id;
  batch.kpoint_id = 0;
  batch.band_begin = 0;
  batch.wave_object = state.wave_object;

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    batch.band_count = 12 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 2 + (state.scf_iteration > 2 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 6;
  } else if (run_config.software_family == "CP2K") {
    batch.band_count = 20 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 10;
    batch.band_batch = 8;
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    batch.band_count = 24 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 4 + (state.scf_iteration > 2 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 8;
  } else if (run_config.software_family == "VASP") {
    batch.band_count = 24 + 4 * (state.scf_iteration - 1);
    batch.panel_count = 4 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 8;
  } else {
    batch.band_count = 16 + 4 * (state.scf_iteration - 1);
    batch.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 8;
    batch.band_batch = 4;
  }

  batch.input_wave_kib =
      static_cast<double>(batch.band_batch * batch.panel_count * batch.panel_size) *
      16.0 / 1024.0;
  batch.output_wave_kib =
      static_cast<double>(batch.band_batch * batch.panel_size) * 16.0 / 1024.0;
  batch.double_buffered = batch.panel_count >= 3;
  return batch;
}

DiagPolicy HostSCF::make_diag_policy(const SystemRunConfig& run_config,
                                     const BandBatchDesc& batch) const {
  const auto template_config = resolve_architecture_template(run_config);
  DiagPolicy policy;
  policy.preferred_device_mode =
      template_config.force_host_diag ? "fallback_companion" : "hardware";
  policy.max_device_diag_dim =
      std::max(batch.band_batch, template_config.device_diag_max_dim);
  policy.max_condition_estimate =
      run_config.software_family == "VASP" ? 1.45 : 1.65;
  policy.require_resident_fit = template_config.resident_policy != "spill_tolerant";
  policy.allow_cpu_fallback = template_config.allow_cpu_diag_fallback;
  policy.force_cpu_diag = template_config.force_host_diag;
  return policy;
}

ScfIterationRequest HostSCF::make_iteration_request(
    const SCFState& state, const SystemRunConfig& run_config, int episode_id) const {
  const auto template_config = resolve_architecture_template(run_config);
  ScfIterationRequest request;
  request.request_id = 1000 + episode_id;
  request.scf_iteration = state.scf_iteration;
  request.episode_id = episode_id;
  request.software_family = run_config.software_family;
  request.flow_family = run_config.flow_family;
  request.architecture_family = template_config.template_id;
  request.assumption_set_id = run_config.assumption_set_id;
  request.offload_scope = template_config.offload_scope;
  request.resident_policy = template_config.resident_policy;
  request.confidence_label = template_config.confidence_label;
  request.algorithm_contract_deviation =
      template_config.algorithm_contract_deviation;
  request.enable_fft = run_config.enable_fft && template_config.enable_device_fft;
  request.resident_set = make_resident_set_desc(state, run_config, episode_id);
  request.band_batch = make_band_batch_desc(state, run_config, episode_id);
  request.diag_policy = make_diag_policy(run_config, request.band_batch);
  request.density_object = state.density_object;
  request.potential_object = state.potential_object;
  request.history_object = state.history_object;
  request.completion_policy = "BLOCKING";
  return request;
}

SCFIterationClusteredReport HostSCF::finalize_iteration(
    const ScfIterationRequest& request, const CompletionSummary& completion,
    SCFState& state) const {
  const auto& episode = completion.episode_result;
  const auto& descriptor = episode.descriptor;
  const bool is_cp2k = descriptor.software_family == "CP2K";
  const bool is_vasp = descriptor.software_family == "VASP";
  const bool is_fast = descriptor.flow_family == "FAST";
  const bool is_ot = descriptor.flow_family == "QS_OT";
  const auto prefix =
      state_prefix(descriptor.software_family, descriptor.flow_family);

  SCFIterationClusteredReport iteration;
  iteration.scf_iteration = descriptor.scf_iteration;
  iteration.request = request;
  iteration.completion = completion;
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
      0.005 * (completion.cpu_diag_fallback
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
  state.last_data_movement_kib = completion.total_data_movement_kib;
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
  if (descriptor.software_family == "VASP") {
    state.projector_object = {
        prefix + "_proj_state_iter_" + std::to_string(descriptor.scf_iteration),
        descriptor.scf_iteration,
        320 + descriptor.scf_iteration,
        "HOST_OUTER_SHELL",
        "episode-window"};
  }
  state.history_object = {prefix + "_hist_iter_" + std::to_string(descriptor.scf_iteration),
                          descriptor.scf_iteration,
                          420 + descriptor.scf_iteration,
                          "HOST_OUTER_SHELL",
                          "full-run"};

  log_line(name(), "Host-managed iteration report => " + iteration.brief());
  log_line(name(), "Completion summary => " + completion.brief());
  log_line(name(), "Device controller => " + episode.controller_state.brief());
  log_line(name(), "Hardware datapath Cluster A => " + episode.cluster_a.brief());
  log_line(name(), "Hardware datapath Cluster B => " + episode.cluster_b.brief());
  log_line(name(), "Hardware datapath Cluster C => " + episode.cluster_c.brief());
  log_line(name(), "Hardware datapath Cluster D => " + episode.cluster_d.brief());
  log_line(name(), "Host SCF state update => " + state.brief());

  return iteration;
}

SCFRunReport HostSCF::run_full_flow(const SystemRunConfig& run_config) const {
  SCFRunReport report;
  report.run_config = run_config;
  report.architecture_family = run_config.architecture_family;
  report.assumption_set_id = run_config.assumption_set_id;

  SCFState state = initialize_state(run_config);
  for (int iter = 1; iter <= run_config.max_scf_iters; ++iter) {
    state.scf_iteration = iter;
    sc_core::wait(8.0, sc_core::SC_NS);
    log_line(name(), "Host CPU completes rho->Veff stage for iter " +
                         std::to_string(iter));

    const auto request = make_iteration_request(state, run_config, 100 + iter);
    log_line(name(), "Host CPU submits inner hot-path request: " + request.brief());
    const auto completion = fpga_.execute_iteration(request);

    sc_core::wait(6.0, sc_core::SC_NS);
    log_line(name(), "Host CPU consumes returned wave/density summary for iter " +
                         std::to_string(iter));

    auto iteration = finalize_iteration(request, completion, state);
    report.total_episodes += 1;
    report.total_lcw_words_issued += completion.lcw_words_issued;
    report.total_row_blocks_processed += completion.row_blocks_processed;
    report.total_ref_cycles += completion.episode_result.total_ref_cycles;
    report.total_backpressure_ref_cycles +=
        completion.episode_result.total_backpressure_ref_cycles;
    report.total_device_busy_ref_cycles += completion.device_busy_ref_cycles;
    report.total_dma_ref_cycles += completion.dma_ref_cycles;
    report.total_host_assist_ref_cycles += completion.host_assist_ref_cycles;
    report.total_cpu_fallbacks += completion.cpu_diag_fallback ? 1 : 0;
    report.resident_reuse_hits += completion.resident_reused ? 1 : 0;
    report.total_data_movement_kib += completion.total_data_movement_kib;
    report.total_dma_read_kib += completion.dma_read_kib;
    report.total_dma_write_kib += completion.dma_write_kib;
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
  log_line(name(), "Host-managed full-SCF report => " + report.brief());
  return report;
}

SCFState HostSCF::run_demo(const SystemRunConfig& run_config) const {
  return run_full_flow(run_config).final_state;
}

}  // namespace qebs
