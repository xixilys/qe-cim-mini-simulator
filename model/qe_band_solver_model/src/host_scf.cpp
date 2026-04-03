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

bool uses_body10_extension(const SystemRunConfig& run_config) {
  return run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT";
}

bool matches_name(const std::string& name,
                  const std::vector<std::string>& candidates) {
  for (const auto& candidate : candidates) {
    if (name == candidate) {
      return true;
    }
  }
  return false;
}

int sum_busy_ref_cycles(const std::vector<ModuleOccupancy>& occupancy,
                        const std::vector<std::string>& module_names) {
  int total = 0;
  for (const auto& item : occupancy) {
    if (matches_name(item.module_name, module_names)) {
      total += item.busy_ref_cycles;
    }
  }
  return total;
}

int sum_blocked_ref_cycles(const std::vector<FlowControlStageSummary>& stages,
                           const std::vector<std::string>& stage_names) {
  int total = 0;
  for (const auto& stage : stages) {
    if (matches_name(stage.stage_name, stage_names)) {
      total += stage.blocked_ref_cycles;
    }
  }
  return total;
}

int split_ref_cycles(int total, int numerator, int denominator) {
  if (denominator <= 0) {
    return 0;
  }
  return (total * numerator + denominator / 2) / denominator;
}

double small_solve_boundary_kib(const EpisodeSummary& summary) {
  const double reduced_dim = static_cast<double>(summary.reduced.reduced_dim);
  const double active_vectors = static_cast<double>(summary.ritz.active_vectors);
  const double reduced_matrices_kib = 2.0 * reduced_dim * reduced_dim * 8.0 / 1024.0;
  const double coeff_return_kib = reduced_dim * active_vectors * 8.0 / 1024.0;
  const double eval_return_kib = active_vectors * 8.0 / 1024.0;
  return reduced_matrices_kib + coeff_return_kib + eval_return_kib;
}

ShellIterationSummary build_qe_shell_iteration_summary(
    const SCFState& entering_state,
    const EpisodeSummary& phase_b,
    const Body04BundleSummary& body04) {
  ShellIterationSummary shell;

  const std::vector<std::string> operator_modules = {
      "NearSRAMSupport.stage_panel",
      "FFTCompanion",
      "CommandScheduler",
      "ResidentContextController",
      "ContextLoader",
      "DigitSerialInputBoundary",
      "ConjugateSignSelector",
      "Residue3MCore",
      "CoefficientAccumulator",
      "NearSRAMCoeffBuffer",
      "RowMergeTree",
      "NearSRAMRowBuffer"};
  const std::vector<std::string> operator_stages = {
      "NearSRAMSupport.stage_panel",
      "FFTCompanion.Transform",
      "ContextLoader",
      "DigitSerialInputBoundary",
      "ProjectConjugateSignSelector",
      "Residue3MCore.PROJECT",
      "CoefficientAccumulator",
      "NearSRAMCoeffBuffer",
      "BackprojectConjugateSignSelector",
      "Residue3MCore.BACKPROJECT",
      "RowMergeTree",
      "NearSRAMRowBuffer"};
  const std::vector<std::string> build_modules = {
      "NearSRAMSupport.aggregate",
      "ReductionClosureEngine"};
  const std::vector<std::string> build_stages = {
      "NearSRAMSupport.aggregate",
      "ReductionClosureEngine.InputAssembler",
      "ReductionClosureEngine.HermitianClosureBuilder",
      "ReductionClosureEngine.SmallSolveFrontEnd"};
  const std::vector<std::string> companion_modules = {"VectorDiagCompanion"};
  const std::vector<std::string> companion_stages = {"VectorDiagCompanion.RitzUpdate"};

  const int operator_ref_cycles =
      sum_busy_ref_cycles(phase_b.structural.module_occupancy, operator_modules);
  const int operator_bp_ref_cycles =
      sum_blocked_ref_cycles(phase_b.flow_control.stages, operator_stages);
  const int build_ref_cycles =
      sum_busy_ref_cycles(phase_b.structural.module_occupancy, build_modules);
  const int build_bp_ref_cycles =
      sum_blocked_ref_cycles(phase_b.flow_control.stages, build_stages);
  const int companion_ref_cycles =
      sum_busy_ref_cycles(phase_b.structural.module_occupancy, companion_modules);
  const int companion_bp_ref_cycles =
      sum_blocked_ref_cycles(phase_b.flow_control.stages, companion_stages);
  const int cdiaghg_ref_cycles = split_ref_cycles(companion_ref_cycles, 4, 7);
  const int refresh_ref_cycles = companion_ref_cycles - cdiaghg_ref_cycles;
  const int cdiaghg_bp_ref_cycles = split_ref_cycles(companion_bp_ref_cycles, 4, 7);
  const int refresh_bp_ref_cycles = companion_bp_ref_cycles - cdiaghg_bp_ref_cycles;
  const double companion_boundary_move_kib = small_solve_boundary_kib(phase_b);

  ShellStageSummary rho_to_veff;
  rho_to_veff.shell_order = 1;
  rho_to_veff.execution_order = 7;
  rho_to_veff.stage_kind = "rho -> Veff";
  rho_to_veff.phase_anchor = "BODY_04B_POTENTIAL_REFRESH";
  rho_to_veff.execution_domain = "FPGA_RUNTIME";
  rho_to_veff.accounting_mode = "loop_carried";
  rho_to_veff.loop_carried = true;
  rho_to_veff.input_handle = entering_state.density_object.object_handle;
  rho_to_veff.output_handle = body04.potential.potential_object.object_handle;
  rho_to_veff.residency_contract = "mixed-density resident, grid exchange visible";
  rho_to_veff.data_movement_kib = body04.potential_stage.data_movement_kib;
  rho_to_veff.accounted_ref_cycles = body04.potential_stage.total_ref_cycles;
  rho_to_veff.backpressure_ref_cycles =
      body04.potential_stage.flow_control.total_backpressure_ref_cycles;
  rho_to_veff.dominant_resource = body04.potential_stage.critical_unit;
  rho_to_veff.detail =
      "Loop-carried stage: current BODY_04B produces the entering Veff/projector state "
      "for the next band episode.";
  shell.stages.push_back(rho_to_veff);

  ShellStageSummary h_psi;
  h_psi.shell_order = 2;
  h_psi.execution_order = 1;
  h_psi.stage_kind = "h_psi";
  h_psi.phase_anchor = "BODY_01_PROJECTOR_APPLY";
  h_psi.execution_domain = "FPGA_RUNTIME";
  h_psi.accounting_mode = "fused_primary";
  h_psi.input_handle = entering_state.wave_object.object_handle;
  h_psi.output_handle = "phase_b/full_hs.partial_h";
  h_psi.residency_contract = "resident wave/projector sweep with on-chip row reuse";
  h_psi.data_movement_kib = 0.0;
  h_psi.accounted_ref_cycles = operator_ref_cycles;
  h_psi.backpressure_ref_cycles = operator_bp_ref_cycles;
  h_psi.dominant_resource = "CIM_PROJECT_BACKPROJECT_CHAIN";
  h_psi.detail =
      "Counted once as the primary fused projector sweep; boundary-visible movement is "
      "kept at zero because the panel/row working set stays resident inside Phase B.";
  shell.stages.push_back(h_psi);

  ShellStageSummary s_psi;
  s_psi.shell_order = 3;
  s_psi.execution_order = 2;
  s_psi.stage_kind = "s_psi";
  s_psi.phase_anchor = "BODY_01_PROJECTOR_APPLY";
  s_psi.execution_domain = "FPGA_RUNTIME";
  s_psi.accounting_mode = "fused_shadow";
  s_psi.input_handle = entering_state.wave_object.object_handle;
  s_psi.output_handle = "phase_b/full_hs.partial_s";
  s_psi.residency_contract = "shares the same resident projector sweep as h_psi";
  s_psi.data_movement_kib = 0.0;
  s_psi.accounted_ref_cycles = 0;
  s_psi.backpressure_ref_cycles = 0;
  s_psi.dominant_resource = "CIM_PROJECT_BACKPROJECT_CHAIN";
  s_psi.detail =
      "Present as an explicit shell stage, but not double-counted because the current "
      "Phase-B proxy forms H and S partials in the same row-block sweep.";
  shell.stages.push_back(s_psi);

  ShellStageSummary build;
  build.shell_order = 4;
  build.execution_order = 3;
  build.stage_kind = "build H_sub/S_sub";
  build.phase_anchor = "BODY_02_REDUCED_CLOSURE";
  build.execution_domain = "FPGA_RUNTIME";
  build.accounting_mode = "exclusive";
  build.input_handle = "phase_b/full_hs";
  build.output_handle = "phase_b/reduced_matrices";
  build.residency_contract = "reduced matrices assembled on chip before companion handoff";
  build.data_movement_kib = 0.0;
  build.accounted_ref_cycles = build_ref_cycles;
  build.backpressure_ref_cycles = build_bp_ref_cycles;
  build.dominant_resource = "ReductionClosureEngine";
  build.detail =
      "Includes local H/S aggregation plus Hermitian closure builder before the companion "
      "solver boundary.";
  shell.stages.push_back(build);

  ShellStageSummary cdiaghg;
  cdiaghg.shell_order = 5;
  cdiaghg.execution_order = 4;
  cdiaghg.stage_kind = "cdiaghg";
  cdiaghg.phase_anchor = "COMPANION_CDIAGHG_PROXY";
  cdiaghg.execution_domain = "CPU_OR_SOFTCORE_COMPANION";
  cdiaghg.accounting_mode = "exclusive";
  cdiaghg.input_handle = "phase_b/reduced_matrices";
  cdiaghg.output_handle = "phase_b/ritz_coefficients";
  cdiaghg.residency_contract = "small reduced-space handoff across FPGA-companion boundary";
  cdiaghg.data_movement_kib = companion_boundary_move_kib;
  cdiaghg.accounted_ref_cycles = cdiaghg_ref_cycles;
  cdiaghg.backpressure_ref_cycles = cdiaghg_bp_ref_cycles;
  cdiaghg.dominant_resource = "VectorDiagCompanion.solve_proxy";
  cdiaghg.detail =
      "The current timed-functional proxy only exposes one VectorDiagCompanion block; the "
      "7-cycle proxy is split 4/3 between cdiaghg and refresh to keep the frozen v1 cut explicit.";
  shell.stages.push_back(cdiaghg);

  ShellStageSummary refresh;
  refresh.shell_order = 6;
  refresh.execution_order = 5;
  refresh.stage_kind = "refresh/residual -> P_next";
  refresh.phase_anchor = "BODY_03_REFRESH_COMMIT_PROXY";
  refresh.execution_domain = "FPGA_RUNTIME";
  refresh.accounting_mode = "exclusive";
  refresh.input_handle = "phase_b/ritz_coefficients";
  refresh.output_handle = entering_state.wave_object.object_handle + ":P_next";
  refresh.residency_contract = "updated search vectors return to resident episode context";
  refresh.data_movement_kib = 0.0;
  refresh.accounted_ref_cycles = refresh_ref_cycles;
  refresh.backpressure_ref_cycles = refresh_bp_ref_cycles;
  refresh.dominant_resource = "BODY_03.commit_boundary";
  refresh.detail =
      "Residual/update production is currently co-modeled with the companion return path; "
      "this split is a contract-preserving proxy, not a frozen microarchitectural statement.";
  shell.stages.push_back(refresh);

  ShellStageSummary psi_to_rho;
  psi_to_rho.shell_order = 7;
  psi_to_rho.execution_order = 6;
  psi_to_rho.stage_kind = "psi -> rho_out";
  psi_to_rho.phase_anchor = "BODY_04A_DENSITY_ACCUM";
  psi_to_rho.execution_domain = "FPGA_RUNTIME";
  psi_to_rho.accounting_mode = "exclusive";
  psi_to_rho.input_handle = body04.density_stage.input_handle;
  psi_to_rho.output_handle = body04.density.density_object.object_handle;
  psi_to_rho.residency_contract = "band outputs reduced into shell-visible density object";
  psi_to_rho.data_movement_kib = body04.density_stage.data_movement_kib;
  psi_to_rho.accounted_ref_cycles = body04.density_stage.total_ref_cycles;
  psi_to_rho.backpressure_ref_cycles =
      body04.density_stage.flow_control.total_backpressure_ref_cycles;
  psi_to_rho.dominant_resource = body04.density_stage.critical_unit;
  psi_to_rho.detail = "Density accumulation closes the band episode and emits rho_out.";
  shell.stages.push_back(psi_to_rho);

  ShellStageSummary mix_rho;
  mix_rho.shell_order = 8;
  mix_rho.execution_order = 8;
  mix_rho.stage_kind = "mix_rho / convergence gate";
  mix_rho.phase_anchor = "BODY_04C_MIX_CONVERGE";
  mix_rho.execution_domain = "HOST_VISIBLE_FPGA_RUNTIME";
  mix_rho.accounting_mode = "exclusive";
  mix_rho.input_handle = body04.mixing_stage.input_handle;
  mix_rho.output_handle = body04.mixing.mixed_density_object.object_handle;
  mix_rho.residency_contract = "history-carrying density object survives across SCF iterations";
  mix_rho.data_movement_kib = body04.mixing_stage.data_movement_kib;
  mix_rho.accounted_ref_cycles = body04.mixing_stage.total_ref_cycles;
  mix_rho.backpressure_ref_cycles =
      body04.mixing_stage.flow_control.total_backpressure_ref_cycles;
  mix_rho.dominant_resource = body04.mixing_stage.critical_unit;
  mix_rho.detail =
      "Not part of the inner band loop, but kept in the shell view because it decides the "
      "next loop-carried rho/Veff state and the SCF stop condition.";
  shell.stages.push_back(mix_rho);

  for (const auto& stage : shell.stages) {
    shell.accounted_data_movement_kib += stage.data_movement_kib;
    shell.accounted_ref_cycles += stage.accounted_ref_cycles;
    shell.accounted_backpressure_ref_cycles += stage.backpressure_ref_cycles;
  }
  return shell;
}

void log_shell_iteration_summary(const std::string& who,
                                 const ShellIterationSummary& shell) {
  log_line(who, "QE shell-stage summary => " + shell.brief());
  for (const auto& stage : shell.stages) {
    log_line(who, "QE shell-stage => " + stage.brief());
  }
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
  state.wave_object = {prefix + "_wave_seed", 0, 100, "BODY_00", "full-run"};
  state.density_object = {prefix + "_rho_seed", 0, 101, "BODY_00", "full-run"};
  state.potential_object = {prefix + "_veff_seed", 0, 102, "BODY_00", "scf-iteration"};
  state.projector_object = {prefix + "_proj_seed", 0, 103, "BODY_00", "episode-window"};
  state.history_object = {prefix + "_scf_hist_seed", 0, 104, "BODY_05", "full-run"};
  state.completed_bodies = 2;

  log_line(name(), "BODY_05 outer_scf_control_body seeds Host/FPGA/Chip run context for " +
                       run_config.brief());
  log_line(name(), "BODY_00 basis_seed_and_bind_body bound initial objects: wave=" +
                       state.wave_object.brief() + ", rho=" +
                       state.density_object.brief() + ", potential=" +
                       state.potential_object.brief());
  return state;
}

EpisodeConfig HostSCF::make_episode_config(const SCFState& state,
                                           const SystemRunConfig& run_config,
                                           int episode_id) const {
  EpisodeConfig config;
  config.scf_iteration = state.scf_iteration;
  config.episode_id = episode_id;
  config.kpoint_batch = 0;
  config.band_begin = 0;
  config.enable_fft = run_config.enable_fft;
  config.software_family = run_config.software_family;
  config.flow_family = run_config.flow_family;

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    config.band_count = 12 + 2 * (state.scf_iteration - 1);
    config.panel_count = 2 + (state.scf_iteration > 2 ? 1 : 0);
    config.panel_size = 12;
    config.resident_row_block_size = 3;
    config.max_inner_steps = 2;
    config.band_batch = 6;
    config.solver_mode = "OT_PRECOND_CG";
    config.support_grid_mode = "AUX_GRID";
    config.precision_constraint = "fp64-ot-constrained";
    config.future_upgrade_hint = "cp2k-ot-body10-enabled";
  } else if (run_config.software_family == "CP2K") {
    config.band_count = 20 + 2 * (state.scf_iteration - 1);
    config.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    config.panel_size = 10;
    config.resident_row_block_size = 5;
    config.max_inner_steps = 2;
    config.band_batch = 8;
    config.solver_mode = "DBCSR_DIAG";
    config.support_grid_mode = "FFT_AUX";
    config.precision_constraint = "fp64-qs-diag-constrained";
    config.future_upgrade_hint = "cp2k-diag-grid-compatible";
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    config.band_count = 24 + 2 * (state.scf_iteration - 1);
    config.panel_count = 4 + (state.scf_iteration > 2 ? 1 : 0);
    config.panel_size = 12;
    config.resident_row_block_size = 6;
    config.max_inner_steps = 2;
    config.band_batch = 8;
    config.solver_mode = state.scf_iteration == 1 ? "BLOCKED_DAVIDSON" : "RMM_DIIS";
    config.support_grid_mode = "ADDGRID";
    config.precision_constraint = "fp64-vasp-paw-constrained";
    config.future_upgrade_hint = "vasp-fast-mode-switch";
  } else if (run_config.software_family == "VASP") {
    config.band_count = 24 + 4 * (state.scf_iteration - 1);
    config.panel_count = 4 + (state.scf_iteration > 1 ? 1 : 0);
    config.panel_size = 12;
    config.resident_row_block_size = 6;
    config.max_inner_steps = 3;
    config.band_batch = 8;
    config.solver_mode = "BLOCKED_DAVIDSON";
    config.support_grid_mode = "FINE_GRID";
    config.precision_constraint = "fp64-vasp-paw-constrained";
    config.future_upgrade_hint = "vasp-paw-support-grid";
  } else {
    config.band_count = 16 + 4 * (state.scf_iteration - 1);
    config.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    config.panel_size = 8;
    config.resident_row_block_size = 4;
    config.max_inner_steps = 3;
    config.band_batch = 4;
    config.solver_mode = "DAVIDSON";
    config.support_grid_mode = "BYPASS";
  }

  return config;
}

ReplayBundleDescriptor HostSCF::make_phase_b_bundle(const EpisodeConfig& config) const {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = config.episode_id;
  descriptor.bundle_kind = "BODY_01_03_REPLAY";
  descriptor.owner_domain = "HOST_VISIBLE_RUNTIME";
  descriptor.execution_domain = "CHIP_TOP";
  descriptor.software_family = config.software_family;
  descriptor.flow_family = config.flow_family;
  descriptor.scf_iteration = config.scf_iteration;
  descriptor.phase_b_config = config;
  descriptor.has_phase_b_config = true;
  return descriptor;
}

ReplayBundleDescriptor HostSCF::make_body10_bundle(
    const Body10BundleRequest& request) const {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = request.bundle_id;
  descriptor.bundle_kind = request.phase_family;
  descriptor.owner_domain = "HOST_VISIBLE_RUNTIME";
  descriptor.execution_domain = "FPGA_RUNTIME";
  descriptor.software_family = request.software_family;
  descriptor.flow_family = request.flow_family;
  descriptor.scf_iteration = request.incoming_state.scf_iteration;
  descriptor.body10_request = request;
  descriptor.has_body10_request = true;
  return descriptor;
}

ReplayBundleDescriptor HostSCF::make_body04_bundle(
    const Body04BundleRequest& request) const {
  ReplayBundleDescriptor descriptor;
  descriptor.bundle_id = request.bundle_id;
  descriptor.bundle_kind = request.phase_family;
  descriptor.owner_domain = "HOST_VISIBLE_RUNTIME";
  descriptor.execution_domain = "FPGA_RUNTIME";
  descriptor.software_family = request.software_family;
  descriptor.flow_family = request.flow_family;
  descriptor.scf_iteration = request.incoming_state.scf_iteration;
  descriptor.body04_request = request;
  descriptor.has_body04_request = true;
  return descriptor;
}

void HostSCF::update_state_from_iteration(const EpisodeSummary& summary,
                                          const Body04BundleSummary& body04_summary,
                                          const Body10BundleSummary* body10_summary,
                                          SCFState& state) const {
  state.completed_episodes += 1;
  state.completed_bodies +=
      3 + body04_summary.phase_count +
      (body10_summary != nullptr ? body10_summary->phase_count : 0);
  state.rho_norm = body04_summary.mixing.mixed_rho_norm;
  state.total_energy = 0.65 * state.total_energy + 0.35 * summary.ritz.et;
  state.converged = body04_summary.mixing.converged;
  state.last_density_delta = body04_summary.mixing.density_delta;
  state.last_data_movement_kib = body04_summary.bundle_data_movement_kib +
                                 (body10_summary != nullptr ? body10_summary->data_movement_kib
                                                            : 0.0);

  if (body10_summary != nullptr && state.software_family == "CP2K" &&
      state.flow_family == "QS_OT") {
    state.wave_object = body10_summary->updated_wave_object;
  } else {
    const auto prefix = state_prefix(state.software_family, state.flow_family);
    state.wave_object.object_handle =
        prefix + "_wave_iter_" + std::to_string(summary.config.scf_iteration);
    state.wave_object.version = summary.config.scf_iteration;
    state.wave_object.resident_buffer_tag = 120 + summary.config.scf_iteration;
    state.wave_object.producer_body = "BODY_03";
    state.wave_object.validity_scope = "scf-iteration";
  }

  state.density_object = body04_summary.mixing.mixed_density_object;
  state.potential_object = body04_summary.potential.potential_object;
  state.projector_object = body04_summary.potential.projector_object;
  state.history_object = body04_summary.mixing.history_object;

  log_line(name(), "SCF state update => " + state.brief());
  log_line(name(), "Resident objects => wave=" + state.wave_object.brief() +
                       ", projector=" + state.projector_object.brief());
  log_line(name(), "Phase B summary => ctx=" +
                       std::to_string(summary.resident_context_id) +
                       ", gen=" + std::to_string(summary.resident_generation) +
                       ", lcw=" + std::to_string(summary.lcw_words_issued) +
                       ", row_blocks=" +
                       std::to_string(summary.row_blocks_processed));
  log_line(name(), "Phase B structural => " + summary.structural.brief());
  log_line(name(), "Phase B flow-control => " + summary.flow_control.brief());
  if (body10_summary != nullptr) {
    log_line(name(), "BODY_10 stage summary => " + body10_summary->precond_stage.brief());
    log_line(name(), "BODY_10 stage summary => " + body10_summary->ortho_stage.brief());
    log_line(name(), "BODY_10 stage summary => " + body10_summary->history_stage.brief());
    log_line(name(), "BODY_10 summary => " + body10_summary->brief());
  }
  log_line(name(), "BODY_04 stage summary => " + body04_summary.density_stage.brief());
  log_line(name(), "BODY_04 stage summary => " + body04_summary.potential_stage.brief());
  log_line(name(), "BODY_04 stage summary => " + body04_summary.mixing_stage.brief());
  log_line(name(), "BODY_04 summary => " + body04_summary.brief());
  log_line(name(), "Data movement summary => total_kib=" +
                       std::to_string(state.last_data_movement_kib));
}

DFTRunReport HostSCF::run_full_flow(const SystemRunConfig& run_config) const {
  DFTRunReport report;
  report.run_config = run_config;
  report.convergence_reason = "max_scf_iters_reached";

  SCFState state = initialize_state(run_config);

  for (int iter = 1; iter <= run_config.max_scf_iters; ++iter) {
    const SCFState entering_state = state;
    state.scf_iteration = iter;
    log_line(name(), "BODY_05 outer_scf_control_body begins SCF iteration " +
                         std::to_string(iter) + " for " + state.software_family +
                         "/" + state.flow_family);

    const auto config = make_episode_config(state, run_config, 100 + iter);
    const auto phase_b_bundle = make_phase_b_bundle(config);
    log_line(name(), "Launching Phase B replay bundle from HostSCF: " +
                         phase_b_bundle.brief());
    fabric_.host_to_fpga("dispatch replay bundle " + phase_b_bundle.brief());

    const auto phase_b_completion = fpga_.execute_replay_bundle(phase_b_bundle);
    fabric_.fpga_to_host("replay return " + phase_b_completion.brief());
    const auto summary = phase_b_completion.phase_b;
    report.total_phase_b_episodes += 1;
    report.total_lcw_words_issued += phase_b_completion.lcw_words_issued;
    report.total_row_blocks_processed += phase_b_completion.row_blocks_processed;
    report.total_phase_b_ref_cycles += summary.structural.total_ref_cycles;
    report.total_phase_b_backpressure_ref_cycles += summary.flow_control.total_backpressure_ref_cycles;

    SCFState body04_input_state = state;
    Body10BundleSummary body10_summary;
    const Body10BundleSummary* body10_ptr = nullptr;
    bool has_body10 = false;
    if (uses_body10_extension(run_config)) {
      Body10BundleRequest body10_request;
      body10_request.bundle_id = 500 + iter;
      body10_request.software_family = run_config.software_family;
      body10_request.flow_family = run_config.flow_family;
      body10_request.incoming_state = state;
      body10_request.phase_b_summary = summary;

      const auto body10_bundle = make_body10_bundle(body10_request);
      fabric_.host_to_fpga("dispatch replay bundle " + body10_bundle.brief());
      const auto body10_completion = fpga_.execute_replay_bundle(body10_bundle);
      fabric_.fpga_to_host("replay return " + body10_completion.brief());
      body10_summary = body10_completion.body10;
      body10_ptr = &body10_summary;
      has_body10 = true;
      report.total_body10_bundles += 1;
      report.total_body10_data_movement_kib += body10_completion.data_movement_kib;
      report.total_body10_ref_cycles += body10_summary.total_ref_cycles;
      report.total_body10_backpressure_ref_cycles +=
          body10_summary.total_backpressure_ref_cycles;
      body04_input_state.wave_object = body10_summary.updated_wave_object;
      body04_input_state.projector_object = body10_summary.updated_projector_object;
      body04_input_state.history_object = body10_summary.search_history_object;
    }

    Body04BundleRequest body04_request;
    body04_request.bundle_id = 400 + iter;
    body04_request.software_family = run_config.software_family;
    body04_request.flow_family = run_config.flow_family;
    body04_request.incoming_state = body04_input_state;
    body04_request.phase_b_summary = summary;

    const auto body04_bundle = make_body04_bundle(body04_request);
    fabric_.host_to_fpga("dispatch replay bundle " + body04_bundle.brief());
    const auto body04_completion = fpga_.execute_replay_bundle(body04_bundle);
    fabric_.fpga_to_host("replay return " + body04_completion.brief());
    const auto body04_summary = body04_completion.body04;
    report.total_body04_bundles += 1;
    report.total_body04_data_movement_kib += body04_completion.data_movement_kib;
    report.total_body04_ref_cycles += body04_summary.total_ref_cycles;
    report.total_body04_backpressure_ref_cycles +=
        body04_summary.total_backpressure_ref_cycles;

    update_state_from_iteration(summary, body04_summary, body10_ptr, state);

    SCFIterationReport iteration;
    iteration.scf_iteration = iter;
    iteration.config = config;
    iteration.phase_b = summary;
    iteration.has_body10 = has_body10;
    if (has_body10) {
      iteration.body10 = body10_summary;
    }
    iteration.body04 = body04_summary;
    if (run_config.software_family == "QE" && run_config.flow_family == "CBANDS_DIAG") {
      iteration.has_shell_view = true;
      iteration.shell = build_qe_shell_iteration_summary(entering_state, summary, body04_summary);
      report.total_shell_data_movement_kib += iteration.shell.accounted_data_movement_kib;
      report.total_shell_ref_cycles += iteration.shell.accounted_ref_cycles;
      report.total_shell_backpressure_ref_cycles +=
          iteration.shell.accounted_backpressure_ref_cycles;
    }
    iteration.iteration_data_movement_kib = state.last_data_movement_kib;
    iteration.energy_after_iteration = state.total_energy;
    iteration.converged = state.converged;
    report.total_data_movement_kib += iteration.iteration_data_movement_kib;
    report.iterations.push_back(iteration);
    log_line(name(), "SCF iteration report => " + iteration.brief());
    if (iteration.has_shell_view) {
      log_shell_iteration_summary(name(), iteration.shell);
    }

    if (state.converged) {
      report.convergence_reason = "mix_gate_converged";
      log_line(name(), "Stopping after SCF convergence gate accepted the mixed density");
      break;
    }
    if (!body04_summary.continue_scf) {
      report.convergence_reason = "body04_family_stop";
      log_line(name(), "Stopping after BODY_04 family requested outer-loop stop");
      break;
    }
    sc_core::wait(20.0, sc_core::SC_NS);
  }

  report.final_state = state;
  log_line(name(), "Full DFT run report => " + report.brief());
  return report;
}

SCFState HostSCF::run_demo(const SystemRunConfig& run_config) const {
  return run_full_flow(run_config).final_state;
}

}  // namespace qebs
