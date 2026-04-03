#pragma once

#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace qebs {

struct ObjectRecord {
  std::string object_handle;
  int version = 0;
  int resident_buffer_tag = 0;
  std::string producer_body = "BODY_00";
  std::string validity_scope = "scf-iteration";

  std::string brief() const {
    std::ostringstream oss;
    oss << object_handle << "@v" << version
        << ", tag=" << resident_buffer_tag
        << ", producer=" << producer_body
        << ", scope=" << validity_scope;
    return oss.str();
  }
};

struct SystemRunConfig {
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  int max_scf_iters = 3;
  bool enable_fft = true;

  std::string brief() const {
    std::ostringstream oss;
    oss << "software=" << software_family
        << ", flow=" << flow_family
        << ", max_scf_iters=" << max_scf_iters
        << ", fft=" << (enable_fft ? "on" : "off");
    return oss.str();
  }
};

struct EpisodeConfig {
  int scf_iteration = 0;
  int episode_id = 0;
  int kpoint_batch = 0;
  int band_begin = 0;
  int band_count = 16;
  int panel_count = 3;
  int panel_size = 8;
  int resident_row_block_size = 4;
  int max_inner_steps = 3;
  int band_batch = 4;
  bool enable_fft = true;
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  std::string solver_mode = "DAVIDSON";
  std::string support_grid_mode = "BYPASS";
  std::string precision_constraint = "fp64-constrained";
  std::string future_upgrade_hint = "future-CIM-style-backend-upgrade";

  std::string brief() const {
    std::ostringstream oss;
    oss << "sw=" << software_family
        << ", flow=" << flow_family
        << ", solver=" << solver_mode
        << ", scf=" << scf_iteration
        << ", episode=" << episode_id
        << ", bands=[" << band_begin << "," << (band_begin + band_count) << ")"
        << ", panels=" << panel_count
        << ", batch=" << band_batch
        << ", row_block=" << resident_row_block_size
        << ", grid=" << support_grid_mode
        << ", fft=" << (enable_fft ? "on" : "off")
        << ", precision=" << precision_constraint;
    return oss.str();
  }
};

struct WavePanel {
  int panel_id = 0;
  int resident_slot = 0;
  double amplitude_norm = 1.0;
  std::vector<double> samples;

  std::string brief() const {
    std::ostringstream oss;
    oss << "panel=" << panel_id << ", slot=" << resident_slot
        << ", norm=" << std::fixed << std::setprecision(3) << amplitude_norm
        << ", samples=" << samples.size();
    return oss.str();
  }
};

struct ResidentContextDesc {
  int resident_context_id = 0;
  int generation = 0;
  int row_block_count = 0;
  int column_group_count = 3;
  int resident_words = 0;
  std::string software_family = "QE";
  std::string projector_family = "projector-beta-family";
  std::string lifecycle_state = "READY";

  std::string brief() const {
    std::ostringstream oss;
    oss << "ctx=" << resident_context_id
        << ", gen=" << generation
        << ", row_blocks=" << row_block_count
        << ", col_groups=" << column_group_count
        << ", words=" << resident_words
        << ", state=" << lifecycle_state;
    return oss.str();
  }
};

struct RowBlockWindowDesc {
  int row_block_id = 0;
  int row_begin = 0;
  int row_count = 0;
  int active_mod_group_mask = 0x7;
  bool fft_preconditioned = false;
  std::string conjugate_policy = "PROJECT_CONJ";

  std::string brief() const {
    std::ostringstream oss;
    oss << "row_block=" << row_block_id
        << ", row_begin=" << row_begin
        << ", row_count=" << row_count
        << ", mod_mask=0x" << std::hex << active_mod_group_mask << std::dec
        << ", fft_pre=" << (fft_preconditioned ? "yes" : "no")
        << ", conj=" << conjugate_policy;
    return oss.str();
  }
};

struct LCWCommand {
  int word_id = 0;
  int inner_step = 0;
  int resident_context_id = 0;
  int resident_generation = 0;
  int row_block_id = 0;
  int active_mod_group_mask = 0x7;
  std::string body_kind = "BODY_01";
  std::string cim_mode = "PROJECTOR_APPLY_CHAIN";
  std::string fft_mode = "BYPASS";
  std::string sram_mode = "STAGE_PROJECT_BACKPROJECT";
  std::string solve_mode = "IDLE";

  std::string brief() const {
    std::ostringstream oss;
    oss << "word=" << word_id
        << ", step=" << inner_step
        << ", ctx=" << resident_context_id
        << ", gen=" << resident_generation
        << ", row_block=" << row_block_id
        << ", mod_mask=0x" << std::hex << active_mod_group_mask << std::dec
        << ", cim=" << cim_mode
        << ", fft=" << fft_mode
        << ", sram=" << sram_mode;
    return oss.str();
  }
};

struct DigitStreamSlice {
  int panel_id = 0;
  int row_block_id = 0;
  int digit_count = 0;
  double magnitude_checksum = 0.0;
  std::vector<double> digits;

  std::string brief() const {
    std::ostringstream oss;
    oss << "panel=" << panel_id
        << ", row_block=" << row_block_id
        << ", digits=" << digit_count
        << ", checksum=" << std::fixed << std::setprecision(4)
        << magnitude_checksum;
    return oss.str();
  }
};

struct ProjectCoeffPacket {
  int panel_id = 0;
  int resident_context_id = 0;
  int resident_generation = 0;
  int row_block_id = 0;
  double coeff_energy = 0.0;
  double coeff_condition = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "panel=" << panel_id
        << ", ctx=" << resident_context_id
        << ", gen=" << resident_generation
        << ", row_block=" << row_block_id
        << ", coeff_energy=" << std::fixed << std::setprecision(4)
        << coeff_energy
        << ", cond=" << coeff_condition;
    return oss.str();
  }
};

struct BackprojectRowPacket {
  int panel_id = 0;
  int resident_context_id = 0;
  int resident_generation = 0;
  int row_block_id = 0;
  double row_energy = 0.0;
  double overlap_energy = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "panel=" << panel_id
        << ", ctx=" << resident_context_id
        << ", gen=" << resident_generation
        << ", row_block=" << row_block_id
        << ", row_energy=" << std::fixed << std::setprecision(4)
        << row_energy
        << ", overlap=" << overlap_energy;
    return oss.str();
  }
};

struct ModuleTrace {
  std::string module_name;
  std::string action;
  std::string detail;
  double simulated_ns = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << module_name << ": " << action << " @" << simulated_ns << "ns"
        << ", detail=" << detail;
    return oss.str();
  }
};

struct PartialHS {
  int panel_id = 0;
  double h_contrib = 0.0;
  double s_contrib = 0.0;
  double local_condition = 0.0;
};

struct ModuleOccupancy {
  std::string module_name;
  int activation_count = 0;
  int busy_ref_cycles = 0;
  int transfer_count = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << module_name
        << ": activations=" << activation_count
        << ", busy_ref_cycles=" << busy_ref_cycles
        << ", transfers=" << transfer_count;
    return oss.str();
  }
};

struct PhaseBStructuralSummary {
  std::string model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY";
  int panel_visits = 0;
  int row_block_visits = 0;
  int control_ref_cycles = 0;
  int fft_ref_cycles = 0;
  int near_sram_ref_cycles = 0;
  int cim_ref_cycles = 0;
  int solve_ref_cycles = 0;
  int vector_ref_cycles = 0;
  int total_ref_cycles = 0;
  std::string critical_domain = "CIM";
  std::vector<ModuleOccupancy> module_occupancy;

  std::string brief() const {
    std::ostringstream oss;
    oss << "level=" << model_level
        << ", panels=" << panel_visits
        << ", row_visits=" << row_block_visits
        << ", ctrl=" << control_ref_cycles
        << ", fft=" << fft_ref_cycles
        << ", sram=" << near_sram_ref_cycles
        << ", cim=" << cim_ref_cycles
        << ", solve=" << solve_ref_cycles
        << ", vector=" << vector_ref_cycles
        << ", total_ref_cycles=" << total_ref_cycles
        << ", critical=" << critical_domain;
    return oss.str();
  }
};

struct FlowControlStageSummary {
  std::string stage_name;
  int ingress_queue_depth = 0;
  int accept_count = 0;
  int complete_count = 0;
  int busy_ref_cycles = 0;
  int blocked_ref_cycles = 0;
  int max_queue_occupancy = 0;
  std::string accept_condition = "ingress_queue_not_full";
  std::string busy_condition = "service_cycles_active_or_output_hold";
  std::string complete_condition = "service_done_and_egress_ready";
  std::string ingress_owner = "upstream_issue_window";
  std::string egress_owner = "downstream_ingress_queue";
  std::string arbitration_domain = "LOCAL";
  std::string datapath_domain = "UNSPECIFIED";

  std::string brief() const {
    std::ostringstream oss;
    oss << stage_name
        << ": qdepth=" << ingress_queue_depth
        << ", accept=" << accept_count
        << ", complete=" << complete_count
        << ", busy_ref_cycles=" << busy_ref_cycles
        << ", blocked_ref_cycles=" << blocked_ref_cycles
        << ", max_q=" << max_queue_occupancy
        << ", accept_cond=" << accept_condition
        << ", busy_cond=" << busy_condition
        << ", complete_cond=" << complete_condition
        << ", ingress_owner=" << ingress_owner
        << ", egress_owner=" << egress_owner
        << ", arb=" << arbitration_domain
        << ", domain=" << datapath_domain;
    return oss.str();
  }
};

struct RouteBackpressureSummary {
  std::string route_name;
  int stall_ref_cycles = 0;
  int conflict_count = 0;
  std::string cause = "downstream_queue_full";
  std::string source_stage = "SOURCE";
  std::string sink_stage = "SINK";
  std::string arbitration_domain = "LOCAL";

  std::string brief() const {
    std::ostringstream oss;
    oss << route_name
        << ": stall_ref_cycles=" << stall_ref_cycles
        << ", conflicts=" << conflict_count
        << ", cause=" << cause
        << ", src=" << source_stage
        << ", sink=" << sink_stage
        << ", arb=" << arbitration_domain;
    return oss.str();
  }
};

struct PhaseBFlowControlSummary {
  std::string model_level = "L2_PROXY_FLOW_CONTROL_WITH_LEAF_CONTRACTS";
  int bundle_accept_count = 0;
  int bundle_complete_count = 0;
  int lcw_issue_credit_limit = 0;
  int lcw_issue_stall_ref_cycles = 0;
  int total_backpressure_ref_cycles = 0;
  int route_conflict_count = 0;
  std::string dominant_backpressure_route = "NONE";
  std::vector<FlowControlStageSummary> stages;
  std::vector<RouteBackpressureSummary> routes;

  std::string brief() const {
    std::ostringstream oss;
    oss << "level=" << model_level
        << ", bundle_accept=" << bundle_accept_count
        << ", bundle_complete=" << bundle_complete_count
        << ", credit_limit=" << lcw_issue_credit_limit
        << ", issue_stall_ref_cycles=" << lcw_issue_stall_ref_cycles
        << ", total_backpressure_ref_cycles=" << total_backpressure_ref_cycles
        << ", route_conflicts=" << route_conflict_count
        << ", dominant_route=" << dominant_backpressure_route;
    return oss.str();
  }
};

struct OperatorChainReport {
  ResidentContextDesc resident_context;
  int lcw_words_issued = 0;
  int row_blocks_processed = 0;
  PhaseBStructuralSummary structural;
  std::vector<PartialHS> partials;
};

struct FullHS {
  int episode_id = 0;
  int aggregated_panels = 0;
  double h_total = 0.0;
  double s_total = 0.0;
  double locality_score = 0.0;
};

struct ReducedMatrices {
  int reduced_dim = 0;
  double h_small = 0.0;
  double s_small = 0.0;
  double closure_score = 0.0;
};

struct RitzResult {
  double et = 0.0;
  double evc_norm = 0.0;
  int active_vectors = 0;
  std::vector<double> eigenvalues;
};

struct ResidualPacket {
  double residual_norm = 0.0;
  double updated_vector_norm = 0.0;
  bool episode_done = false;
  int updates_applied = 0;
};

struct DensityAccumStats {
  double rho_out_norm = 0.0;
  double occupation_checksum = 0.0;
  double data_movement_kib = 0.0;
  int accumulated_bands = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "rho_out=" << std::fixed << std::setprecision(4) << rho_out_norm
        << ", occ_sum=" << occupation_checksum
        << ", move_kib=" << data_movement_kib
        << ", bands=" << accumulated_bands;
    return oss.str();
  }
};

struct DensitySummary {
  ObjectRecord density_object;
  double rho_out_norm = 0.0;
  double occupation_checksum = 0.0;
  double data_movement_kib = 0.0;
  int accumulated_bands = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << density_object.brief()
        << ", rho_out=" << std::fixed << std::setprecision(4) << rho_out_norm
        << ", occ_sum=" << occupation_checksum
        << ", move_kib=" << data_movement_kib;
    return oss.str();
  }
};

struct PotentialFieldStats {
  double potential_norm = 0.0;
  double grid_exchange_kib = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "v_norm=" << std::fixed << std::setprecision(4) << potential_norm
        << ", grid_kib=" << grid_exchange_kib;
    return oss.str();
  }
};

struct ProjectorStateStats {
  ObjectRecord projector_object;
  double projector_refresh_score = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << projector_object.brief()
        << ", projector_score=" << std::fixed << std::setprecision(4)
        << projector_refresh_score;
    return oss.str();
  }
};

struct PotentialSummary {
  ObjectRecord potential_object;
  ObjectRecord projector_object;
  double potential_norm = 0.0;
  double projector_refresh_score = 0.0;
  double grid_exchange_kib = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << potential_object.brief()
        << ", projector=" << projector_object.object_handle
        << "@v" << projector_object.version
        << ", v_norm=" << std::fixed << std::setprecision(4)
        << potential_norm
        << ", projector_score=" << projector_refresh_score
        << ", grid_kib=" << grid_exchange_kib;
    return oss.str();
  }
};

struct DensityMixStats {
  double mixed_rho_norm = 0.0;
  double density_delta = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "mixed_rho=" << std::fixed << std::setprecision(4) << mixed_rho_norm
        << ", drho=" << density_delta;
    return oss.str();
  }
};

struct ConvergenceDecision {
  ObjectRecord history_object;
  double energy_delta = 0.0;
  bool converged = false;
  int history_depth = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << history_object.brief()
        << ", dE=" << std::fixed << std::setprecision(4) << energy_delta
        << ", converged=" << (converged ? "yes" : "no")
        << ", depth=" << history_depth;
    return oss.str();
  }
};

struct MixingSummary {
  ObjectRecord mixed_density_object;
  ObjectRecord history_object;
  double mixed_rho_norm = 0.0;
  double density_delta = 0.0;
  double energy_delta = 0.0;
  bool converged = false;
  int history_depth = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << mixed_density_object.brief()
        << ", history=" << history_object.object_handle
        << "@v" << history_object.version
        << ", mixed_rho=" << std::fixed << std::setprecision(4)
        << mixed_rho_norm
        << ", drho=" << density_delta
        << ", dE=" << energy_delta
        << ", converged=" << (converged ? "yes" : "no");
    return oss.str();
  }
};

struct Body10PrecondStats {
  double block_update_norm = 0.0;
  double data_movement_kib = 0.0;
  int active_blocks = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "update_norm=" << std::fixed << std::setprecision(4)
        << block_update_norm
        << ", move_kib=" << data_movement_kib
        << ", active_blocks=" << active_blocks;
    return oss.str();
  }
};

struct Body10PrecondSummary {
  ObjectRecord wave_candidate_object;
  double block_update_norm = 0.0;
  double data_movement_kib = 0.0;
  int active_blocks = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << wave_candidate_object.brief()
        << ", update_norm=" << std::fixed << std::setprecision(4)
        << block_update_norm
        << ", move_kib=" << data_movement_kib
        << ", active_blocks=" << active_blocks;
    return oss.str();
  }
};

struct Body10OrthoStats {
  double orthogonality_score = 0.0;
  double data_movement_kib = 0.0;
  int active_blocks = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "ortho=" << std::fixed << std::setprecision(4)
        << orthogonality_score
        << ", move_kib=" << data_movement_kib
        << ", active_blocks=" << active_blocks;
    return oss.str();
  }
};

struct Body10OrthoSummary {
  ObjectRecord updated_wave_object;
  ObjectRecord updated_projector_object;
  double orthogonality_score = 0.0;
  double data_movement_kib = 0.0;
  int active_blocks = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << updated_wave_object.brief()
        << ", projector=" << updated_projector_object.object_handle
        << "@v" << updated_projector_object.version
        << ", ortho=" << std::fixed << std::setprecision(4)
        << orthogonality_score
        << ", move_kib=" << data_movement_kib
        << ", active_blocks=" << active_blocks;
    return oss.str();
  }
};

struct Body10HistoryStats {
  bool accepted = true;
  int history_depth = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "accepted=" << (accepted ? "yes" : "no")
        << ", depth=" << history_depth;
    return oss.str();
  }
};

struct Body10HistorySummary {
  ObjectRecord search_history_object;
  ObjectRecord decision_summary_object;
  bool accepted = true;
  int history_depth = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << search_history_object.brief()
        << ", decision=" << decision_summary_object.object_handle
        << "@v" << decision_summary_object.version
        << ", accepted=" << (accepted ? "yes" : "no")
        << ", depth=" << history_depth;
    return oss.str();
  }
};

struct SCFState {
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  int scf_iteration = 0;
  double rho_norm = 1.0;
  double total_energy = 0.0;
  bool converged = false;
  int completed_episodes = 0;
  int completed_bodies = 0;
  double last_density_delta = 0.0;
  double last_data_movement_kib = 0.0;
  ObjectRecord wave_object;
  ObjectRecord density_object;
  ObjectRecord potential_object;
  ObjectRecord projector_object;
  ObjectRecord history_object;

  std::string brief() const {
    std::ostringstream oss;
    oss << "software=" << software_family
        << ", flow=" << flow_family
        << ", iter=" << scf_iteration
        << ", rho=" << std::fixed << std::setprecision(4) << rho_norm
        << ", energy=" << total_energy
        << ", episodes=" << completed_episodes
        << ", bodies=" << completed_bodies
        << ", density=" << density_object.object_handle
        << ", potential=" << potential_object.object_handle
        << ", converged=" << (converged ? "yes" : "no");
    return oss.str();
  }
};

struct EpisodeSummary {
  EpisodeConfig config;
  FullHS full_hs;
  ReducedMatrices reduced;
  RitzResult ritz;
  ResidualPacket residual;
  PhaseBStructuralSummary structural;
  PhaseBFlowControlSummary flow_control;
  bool fft_used = false;
  int resident_context_id = 0;
  int resident_generation = 0;
  int lcw_words_issued = 0;
  int row_blocks_processed = 0;
  std::string status = "created";

  std::string brief() const {
    std::ostringstream oss;
    oss << "status=" << status
        << ", et=" << std::fixed << std::setprecision(4) << ritz.et
        << ", evc_norm=" << ritz.evc_norm
        << ", residual=" << residual.residual_norm
        << ", ctx=" << resident_context_id
        << ", gen=" << resident_generation
        << ", lcw=" << lcw_words_issued
        << ", row_blocks=" << row_blocks_processed
        << ", ref_cycles=" << structural.total_ref_cycles
        << ", bp_ref_cycles=" << flow_control.total_backpressure_ref_cycles
        << ", fft=" << (fft_used ? "yes" : "no");
    return oss.str();
  }
};

struct Body10BundleRequest {
  int bundle_id = 0;
  std::string phase_family = "BODY_10_FAMILY";
  std::string software_family = "CP2K";
  std::string flow_family = "QS_OT";
  SCFState incoming_state;
  EpisodeSummary phase_b_summary;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", scf_iter=" << incoming_state.scf_iteration;
    return oss.str();
  }
};

struct Body10FlowControlSummary {
  std::string model_level = "L2_PROXY_FLOW_CONTROL_WITH_LEAF_CONTRACTS";
  int stage_accept_count = 0;
  int stage_complete_count = 0;
  int issue_credit_limit = 0;
  int issue_stall_ref_cycles = 0;
  int total_backpressure_ref_cycles = 0;
  int route_conflict_count = 0;
  std::string dominant_backpressure_route = "NONE";
  std::vector<FlowControlStageSummary> stages;
  std::vector<RouteBackpressureSummary> routes;

  std::string brief() const {
    std::ostringstream oss;
    oss << "level=" << model_level
        << ", stage_accept=" << stage_accept_count
        << ", stage_complete=" << stage_complete_count
        << ", credit_limit=" << issue_credit_limit
        << ", issue_stall_ref_cycles=" << issue_stall_ref_cycles
        << ", total_backpressure_ref_cycles=" << total_backpressure_ref_cycles
        << ", route_conflicts=" << route_conflict_count
        << ", dominant_route=" << dominant_backpressure_route;
    return oss.str();
  }
};

struct Body10StageRequest {
  int bundle_id = 0;
  std::string stage_kind = "BODY_10A_PRECOND_UPDATE";
  std::string software_family = "CP2K";
  std::string flow_family = "QS_OT";
  std::string completion_mode = "SYNC";
  std::string join_mode = "HARD_BARRIER";
  SCFState incoming_state;
  EpisodeSummary phase_b_summary;
  ObjectRecord primary_input_object;
  ObjectRecord secondary_input_object;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", stage=" << stage_kind
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", in0=" << primary_input_object.object_handle
        << ", in1=" << secondary_input_object.object_handle
        << ", completion=" << completion_mode
        << ", join=" << join_mode;
    return oss.str();
  }
};

struct Body10StageSummary {
  std::string stage_kind = "BODY_10A_PRECOND_UPDATE";
  std::string completion_mode = "SYNC";
  std::string join_mode = "HARD_BARRIER";
  std::string model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_LEAF_FLOW_CONTROL_PROXY";
  std::string input_handle;
  std::string output_handle;
  double data_movement_kib = 0.0;
  int total_ref_cycles = 0;
  std::string critical_unit = "NONE";
  bool accepted = true;
  std::vector<ModuleOccupancy> unit_occupancy;
  Body10FlowControlSummary flow_control;
  std::string detail;

  std::string brief() const {
    std::ostringstream oss;
    oss << "stage=" << stage_kind
        << ", input=" << input_handle
        << ", output=" << output_handle
        << ", move_kib=" << std::fixed << std::setprecision(4)
        << data_movement_kib
        << ", ref_cycles=" << total_ref_cycles
        << ", bp_ref_cycles=" << flow_control.total_backpressure_ref_cycles
        << ", critical_unit=" << critical_unit
        << ", accepted=" << (accepted ? "yes" : "no")
        << ", completion=" << completion_mode
        << ", join=" << join_mode;
    return oss.str();
  }
};

struct Body10StageDescriptor {
  std::string stage_kind = "BODY_10A_PRECOND_UPDATE";
  std::string execution_domain = "BODY10_RUNTIME";
  std::string engine_route = "SIMD|SRAM_STAGE";
  std::string primary_input_handle;
  std::string secondary_input_handle;
  std::string expected_output_handle;
  std::string residency_action = "STREAM_IN_STAGE_COMMIT";
  double estimated_latency_ns = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "stage=" << stage_kind
        << ", exec=" << execution_domain
        << ", route=" << engine_route
        << ", in0=" << primary_input_handle
        << ", in1=" << secondary_input_handle
        << ", out=" << expected_output_handle
        << ", residency=" << residency_action
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << estimated_latency_ns;
    return oss.str();
  }
};

struct Body10LoweringPlan {
  int bundle_id = 0;
  std::string phase_family = "BODY_10_FAMILY";
  std::string software_family = "CP2K";
  std::string flow_family = "QS_OT";
  std::string domain_name = "Body10FamilyController";
  Body10StageDescriptor precond_stage;
  Body10StageDescriptor ortho_stage;
  Body10StageDescriptor history_stage;
  double total_estimated_latency_ns = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", domain=" << domain_name
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << total_estimated_latency_ns;
    return oss.str();
  }
};

struct Body10BundleSummary {
  int bundle_id = 0;
  std::string phase_family = "BODY_10_FAMILY";
  std::string software_family = "CP2K";
  std::string flow_family = "QS_OT";
  std::string model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_BODY10_LEAF_FLOW_CONTROL_PROXY";
  int phase_count = 3;
  bool accepted = true;
  ObjectRecord wave_candidate_object;
  ObjectRecord updated_wave_object;
  ObjectRecord updated_projector_object;
  ObjectRecord search_history_object;
  ObjectRecord decision_summary_object;
  double block_update_norm = 0.0;
  double orthogonality_score = 0.0;
  double data_movement_kib = 0.0;
  int active_blocks = 0;
  int total_ref_cycles = 0;
  int total_backpressure_ref_cycles = 0;
  std::string critical_stage_kind = "NONE";
  std::string dominant_backpressure_stage_kind = "NONE";
  Body10LoweringPlan lowering_plan;
  Body10StageSummary precond_stage;
  Body10StageSummary ortho_stage;
  Body10StageSummary history_stage;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", domain=" << lowering_plan.domain_name
        << ", accepted=" << (accepted ? "yes" : "no")
        << ", wave=" << updated_wave_object.object_handle
        << ", projector=" << updated_projector_object.object_handle
        << ", history=" << search_history_object.object_handle
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << lowering_plan.total_estimated_latency_ns
        << ", ref_cycles=" << total_ref_cycles
        << ", bp_ref_cycles=" << total_backpressure_ref_cycles
        << ", critical_stage=" << critical_stage_kind
        << ", update_norm=" << std::setprecision(4)
        << block_update_norm
        << ", ortho=" << orthogonality_score
        << ", move_kib=" << data_movement_kib;
    return oss.str();
  }
};

struct Body04StageRequest {
  int bundle_id = 0;
  std::string stage_kind = "BODY_04A_DENSITY_ACCUM";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  std::string completion_mode = "SYNC";
  std::string join_mode = "HARD_BARRIER";
  SCFState incoming_state;
  EpisodeSummary phase_b_summary;
  ObjectRecord primary_input_object;
  ObjectRecord secondary_input_object;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", stage=" << stage_kind
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", in0=" << primary_input_object.object_handle
        << ", in1=" << secondary_input_object.object_handle
        << ", completion=" << completion_mode
        << ", join=" << join_mode;
    return oss.str();
  }
};

struct Body04FlowControlSummary {
  std::string model_level = "L2_PROXY_FLOW_CONTROL_WITH_LEAF_CONTRACTS";
  int stage_accept_count = 0;
  int stage_complete_count = 0;
  int issue_credit_limit = 0;
  int issue_stall_ref_cycles = 0;
  int total_backpressure_ref_cycles = 0;
  int route_conflict_count = 0;
  std::string dominant_backpressure_route = "NONE";
  std::vector<FlowControlStageSummary> stages;
  std::vector<RouteBackpressureSummary> routes;

  std::string brief() const {
    std::ostringstream oss;
    oss << "level=" << model_level
        << ", stage_accept=" << stage_accept_count
        << ", stage_complete=" << stage_complete_count
        << ", credit_limit=" << issue_credit_limit
        << ", issue_stall_ref_cycles=" << issue_stall_ref_cycles
        << ", total_backpressure_ref_cycles=" << total_backpressure_ref_cycles
        << ", route_conflicts=" << route_conflict_count
        << ", dominant_route=" << dominant_backpressure_route;
    return oss.str();
  }
};

struct Body04StageSummary {
  std::string stage_kind = "BODY_04A_DENSITY_ACCUM";
  std::string completion_mode = "SYNC";
  std::string join_mode = "HARD_BARRIER";
  std::string model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_LEAF_FLOW_CONTROL_PROXY";
  std::string input_handle;
  std::string output_handle;
  double data_movement_kib = 0.0;
  int total_ref_cycles = 0;
  std::string critical_unit = "NONE";
  bool accepted = true;
  std::vector<ModuleOccupancy> unit_occupancy;
  Body04FlowControlSummary flow_control;
  std::string detail;

  std::string brief() const {
    std::ostringstream oss;
    oss << "stage=" << stage_kind
        << ", input=" << input_handle
        << ", output=" << output_handle
        << ", move_kib=" << std::fixed << std::setprecision(4)
        << data_movement_kib
        << ", ref_cycles=" << total_ref_cycles
        << ", bp_ref_cycles=" << flow_control.total_backpressure_ref_cycles
        << ", critical_unit=" << critical_unit
        << ", accepted=" << (accepted ? "yes" : "no")
        << ", completion=" << completion_mode
        << ", join=" << join_mode;
    return oss.str();
  }
};

struct Body04StageDescriptor {
  std::string stage_kind = "BODY_04A_DENSITY_ACCUM";
  std::string execution_domain = "OUTER_UPDATE_RUNTIME";
  std::string engine_route = "SIMD|NEAR_SRAM_ACCUM";
  std::string primary_input_handle;
  std::string secondary_input_handle;
  std::string expected_output_handle;
  std::string residency_action = "STREAM_IN_STREAM_OUT";
  double estimated_latency_ns = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "stage=" << stage_kind
        << ", exec=" << execution_domain
        << ", route=" << engine_route
        << ", in0=" << primary_input_handle
        << ", in1=" << secondary_input_handle
        << ", out=" << expected_output_handle
        << ", residency=" << residency_action
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << estimated_latency_ns;
    return oss.str();
  }
};

struct Body04LoweringPlan {
  int bundle_id = 0;
  std::string phase_family = "BODY_04_FAMILY";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  std::string domain_name = "OuterUpdateRuntimeDomain";
  Body04StageDescriptor density_stage;
  Body04StageDescriptor potential_stage;
  Body04StageDescriptor mixing_stage;
  double total_estimated_latency_ns = 0.0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", domain=" << domain_name
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << total_estimated_latency_ns;
    return oss.str();
  }
};


struct Body04BundleRequest {
  int bundle_id = 0;
  std::string phase_family = "BODY_04_FAMILY";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  SCFState incoming_state;
  EpisodeSummary phase_b_summary;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", scf_iter=" << incoming_state.scf_iteration;
    return oss.str();
  }
};

struct Body04BundleSummary {
  int bundle_id = 0;
  std::string phase_family = "BODY_04_FAMILY";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  std::string model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_BODY04_LEAF_FLOW_CONTROL_PROXY";
  int phase_count = 3;
  bool continue_scf = true;
  double bundle_data_movement_kib = 0.0;
  int total_ref_cycles = 0;
  int total_backpressure_ref_cycles = 0;
  std::string critical_stage_kind = "NONE";
  std::string dominant_backpressure_stage_kind = "NONE";
  Body04LoweringPlan lowering_plan;
  DensitySummary density;
  PotentialSummary potential;
  MixingSummary mixing;
  Body04StageSummary density_stage;
  Body04StageSummary potential_stage;
  Body04StageSummary mixing_stage;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", phase_family=" << phase_family
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", domain=" << lowering_plan.domain_name
        << ", continue_scf=" << (continue_scf ? "yes" : "no")
        << ", density=" << density.density_object.object_handle
        << ", potential=" << potential.potential_object.object_handle
        << ", mixed=" << mixing.mixed_density_object.object_handle
        << ", est_ns=" << std::fixed << std::setprecision(1)
        << lowering_plan.total_estimated_latency_ns
        << ", ref_cycles=" << total_ref_cycles
        << ", bp_ref_cycles=" << total_backpressure_ref_cycles
        << ", critical_stage=" << critical_stage_kind
        << ", move_kib=" << std::setprecision(4)
        << bundle_data_movement_kib;
    return oss.str();
  }
};


struct ReplayBundleDescriptor {
  int bundle_id = 0;
  std::string bundle_kind = "BODY_01_03_REPLAY";
  std::string owner_domain = "HOST_VISIBLE_RUNTIME";
  std::string execution_domain = "CHIP_TOP";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  int scf_iteration = 0;
  bool has_phase_b_config = false;
  bool has_body10_request = false;
  bool has_body04_request = false;
  EpisodeConfig phase_b_config;
  Body10BundleRequest body10_request;
  Body04BundleRequest body04_request;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", kind=" << bundle_kind
        << ", owner=" << owner_domain
        << ", exec=" << execution_domain
        << ", software=" << software_family
        << ", flow=" << flow_family
        << ", scf_iter=" << scf_iteration;
    return oss.str();
  }
};

struct ReplayBundleCompletion {
  int bundle_id = 0;
  std::string bundle_kind = "BODY_01_03_REPLAY";
  std::string owner_domain = "FPGA_RUNTIME";
  std::string execution_domain = "CHIP_TOP";
  std::string software_family = "QE";
  std::string flow_family = "CBANDS_DIAG";
  bool accepted = true;
  bool has_phase_b = false;
  bool has_body10 = false;
  bool has_body04 = false;
  EpisodeSummary phase_b;
  Body10BundleSummary body10;
  Body04BundleSummary body04;
  int lcw_words_issued = 0;
  int row_blocks_processed = 0;
  double data_movement_kib = 0.0;
  std::string completion_note;

  std::string brief() const {
    std::ostringstream oss;
    oss << "bundle=" << bundle_id
        << ", kind=" << bundle_kind
        << ", accepted=" << (accepted ? "yes" : "no")
        << ", exec=" << execution_domain
        << ", lcw=" << lcw_words_issued
        << ", row_blocks=" << row_blocks_processed
        << ", move_kib=" << std::fixed << std::setprecision(4)
        << data_movement_kib
        << ", note=" << completion_note;
    return oss.str();
  }
};

struct ShellStageSummary {
  int shell_order = 0;
  int execution_order = 0;
  std::string stage_kind = "rho -> Veff";
  std::string phase_anchor = "BODY_04B_POTENTIAL_REFRESH";
  std::string execution_domain = "FPGA_RUNTIME";
  std::string accounting_mode = "exclusive";
  bool loop_carried = false;
  std::string input_handle;
  std::string output_handle;
  std::string residency_contract = "resident-on-chip";
  double data_movement_kib = 0.0;
  int accounted_ref_cycles = 0;
  int backpressure_ref_cycles = 0;
  std::string dominant_resource = "NONE";
  std::string detail;

  std::string brief() const {
    std::ostringstream oss;
    oss << "shell_order=" << shell_order
        << ", exec_order=" << execution_order
        << ", stage=" << stage_kind
        << ", anchor=" << phase_anchor
        << ", domain=" << execution_domain
        << ", mode=" << accounting_mode
        << ", loop_carried=" << (loop_carried ? "yes" : "no")
        << ", in=" << input_handle
        << ", out=" << output_handle
        << ", residency=" << residency_contract
        << ", move_kib=" << std::fixed << std::setprecision(4)
        << data_movement_kib
        << ", ref_cycles=" << accounted_ref_cycles
        << ", bp_ref_cycles=" << backpressure_ref_cycles
        << ", dominant=" << dominant_resource;
    if (!detail.empty()) {
      oss << ", detail=" << detail;
    }
    return oss.str();
  }
};

struct ShellIterationSummary {
  std::string shell_family = "QE_SCF_SHELL_V1";
  std::string frozen_contract =
      "rho -> Veff -> while bands not converged { h_psi, s_psi, build H_sub/S_sub, "
      "cdiaghg, refresh/residual -> P_next } -> psi -> rho_out -> mix_rho";
  bool cdiaghg_on_companion = true;
  std::string companion_domain = "CPU_OR_SOFTCORE";
  std::vector<ShellStageSummary> stages;
  double accounted_data_movement_kib = 0.0;
  int accounted_ref_cycles = 0;
  int accounted_backpressure_ref_cycles = 0;

  std::string brief() const {
    std::ostringstream oss;
    oss << "family=" << shell_family
        << ", stages=" << stages.size()
        << ", cdiaghg_on_companion=" << (cdiaghg_on_companion ? "yes" : "no")
        << ", companion=" << companion_domain
        << ", move_kib=" << std::fixed << std::setprecision(4)
        << accounted_data_movement_kib
        << ", ref_cycles=" << accounted_ref_cycles
        << ", bp_ref_cycles=" << accounted_backpressure_ref_cycles;
    return oss.str();
  }
};

struct SCFIterationReport {
  int scf_iteration = 0;
  EpisodeConfig config;
  EpisodeSummary phase_b;
  bool has_body10 = false;
  Body10BundleSummary body10;
  Body04BundleSummary body04;
  bool has_shell_view = false;
  ShellIterationSummary shell;
  double iteration_data_movement_kib = 0.0;
  double energy_after_iteration = 0.0;
  bool converged = false;

  std::string brief() const {
    std::ostringstream oss;
    oss << "iter=" << scf_iteration
        << ", solver=" << config.solver_mode
        << ", phase_b=" << phase_b.status
        << ", body10=" << (has_body10 ? body10.phase_family : std::string("none"))
        << ", body10_move_kib=" << (has_body10 ? body10.data_movement_kib : 0.0)
        << ", body10_ref_cycles=" << (has_body10 ? body10.total_ref_cycles : 0)
        << ", body10_bp_ref_cycles=" <<
               (has_body10 ? body10.total_backpressure_ref_cycles : 0)
        << ", body04_move_kib=" << body04.bundle_data_movement_kib
        << ", body04_ref_cycles=" << body04.total_ref_cycles
        << ", body04_bp_ref_cycles=" << body04.total_backpressure_ref_cycles
        << ", shell_stages=" << (has_shell_view ? shell.stages.size() : 0)
        << ", shell_ref_cycles=" << (has_shell_view ? shell.accounted_ref_cycles : 0)
        << ", shell_bp_ref_cycles="
        << (has_shell_view ? shell.accounted_backpressure_ref_cycles : 0)
        << ", iter_move_kib=" << iteration_data_movement_kib
        << ", energy=" << energy_after_iteration
        << ", converged=" << (converged ? "yes" : "no");
    return oss.str();
  }
};

struct DFTRunReport {
  SystemRunConfig run_config;
  SCFState final_state;
  std::vector<SCFIterationReport> iterations;
  std::string model_level =
      "STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_BODY10_BODY04_LEAF_FLOW_CONTROL_PROXY";
  int total_phase_b_episodes = 0;
  int total_body04_bundles = 0;
  int total_body10_bundles = 0;
  int total_lcw_words_issued = 0;
  int total_row_blocks_processed = 0;
  int total_phase_b_ref_cycles = 0;
  int total_phase_b_backpressure_ref_cycles = 0;
  double total_body04_data_movement_kib = 0.0;
  int total_body04_ref_cycles = 0;
  int total_body04_backpressure_ref_cycles = 0;
  double total_body10_data_movement_kib = 0.0;
  int total_body10_ref_cycles = 0;
  int total_body10_backpressure_ref_cycles = 0;
  double total_data_movement_kib = 0.0;
  double total_shell_data_movement_kib = 0.0;
  int total_shell_ref_cycles = 0;
  int total_shell_backpressure_ref_cycles = 0;
  std::string convergence_reason = "max_scf_iters_reached";

  std::string brief() const {
    std::ostringstream oss;
    oss << "software=" << run_config.software_family
        << ", flow=" << run_config.flow_family
        << ", iters=" << iterations.size()
        << ", phase_b=" << total_phase_b_episodes
        << ", body04=" << total_body04_bundles
        << ", body10=" << total_body10_bundles
        << ", lcw=" << total_lcw_words_issued
        << ", row_blocks=" << total_row_blocks_processed
        << ", phase_b_ref_cycles=" << total_phase_b_ref_cycles
        << ", phase_b_bp_ref_cycles=" << total_phase_b_backpressure_ref_cycles
        << ", body10_ref_cycles=" << total_body10_ref_cycles
        << ", body10_bp_ref_cycles=" << total_body10_backpressure_ref_cycles
        << ", body04_ref_cycles=" << total_body04_ref_cycles
        << ", body04_bp_ref_cycles=" << total_body04_backpressure_ref_cycles
        << ", total_move_kib=" << std::fixed << std::setprecision(4)
        << total_data_movement_kib
        << ", shell_move_kib=" << total_shell_data_movement_kib
        << ", shell_ref_cycles=" << total_shell_ref_cycles
        << ", shell_bp_ref_cycles=" << total_shell_backpressure_ref_cycles
        << ", body04_move_kib=" << total_body04_data_movement_kib
        << ", body10_move_kib=" << total_body10_data_movement_kib
        << ", reason=" << convergence_reason
        << ", final_density=" << final_state.density_object.object_handle
        << ", model_level=" << model_level
        << ", converged=" << (final_state.converged ? "yes" : "no");
    return oss.str();
  }
};

}  // namespace qebs
