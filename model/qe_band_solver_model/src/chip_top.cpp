#include "chip_top.hpp"

namespace qebs {

namespace {

struct StageSpec {
  std::string stage_name;
  int ingress_queue_depth = 1;
  int service_cycles = 1;
  std::string route_name;
  std::string accept_condition = "ingress_queue_not_full";
  std::string busy_condition = "service_cycles_active_or_output_hold";
  std::string complete_condition = "service_done_and_egress_ready";
  std::string ingress_owner = "upstream_issue_window";
  std::string egress_owner = "downstream_ingress_queue";
  std::string arbitration_domain = "LOCAL";
  std::string datapath_domain = "UNSPECIFIED";
  std::string route_cause = "downstream_queue_full";
};

StageSpec make_stage_spec(const std::string& stage_name,
                         int ingress_queue_depth,
                         int service_cycles,
                         const std::string& route_name,
                         const std::string& accept_condition,
                         const std::string& busy_condition,
                         const std::string& complete_condition,
                         const std::string& ingress_owner,
                         const std::string& egress_owner,
                         const std::string& arbitration_domain,
                         const std::string& datapath_domain,
                         const std::string& route_cause = "downstream_queue_full") {
  StageSpec spec;
  spec.stage_name = stage_name;
  spec.ingress_queue_depth = ingress_queue_depth;
  spec.service_cycles = service_cycles;
  spec.route_name = route_name;
  spec.accept_condition = accept_condition;
  spec.busy_condition = busy_condition;
  spec.complete_condition = complete_condition;
  spec.ingress_owner = ingress_owner;
  spec.egress_owner = egress_owner;
  spec.arbitration_domain = arbitration_domain;
  spec.datapath_domain = datapath_domain;
  spec.route_cause = route_cause;
  return spec;
}

ModuleOccupancy make_occupancy(const std::string& module_name,
                               int activation_count,
                               int busy_ref_cycles,
                               int transfer_count) {
  ModuleOccupancy occupancy;
  occupancy.module_name = module_name;
  occupancy.activation_count = activation_count;
  occupancy.busy_ref_cycles = busy_ref_cycles;
  occupancy.transfer_count = transfer_count;
  return occupancy;
}

void add_module_occupancy(PhaseBStructuralSummary& structural,
                          const ModuleOccupancy& occupancy) {
  for (auto& existing : structural.module_occupancy) {
    if (existing.module_name == occupancy.module_name) {
      existing.activation_count += occupancy.activation_count;
      existing.busy_ref_cycles += occupancy.busy_ref_cycles;
      existing.transfer_count += occupancy.transfer_count;
      return;
    }
  }
  structural.module_occupancy.push_back(occupancy);
}

void refresh_structural_totals(PhaseBStructuralSummary& structural) {
  structural.total_ref_cycles = structural.control_ref_cycles +
                                structural.fft_ref_cycles +
                                structural.near_sram_ref_cycles +
                                structural.cim_ref_cycles +
                                structural.solve_ref_cycles +
                                structural.vector_ref_cycles;

  structural.critical_domain = "CONTROL";
  int critical_cycles = structural.control_ref_cycles;
  if (structural.fft_ref_cycles > critical_cycles) {
    structural.critical_domain = "FFT";
    critical_cycles = structural.fft_ref_cycles;
  }
  if (structural.near_sram_ref_cycles > critical_cycles) {
    structural.critical_domain = "NEAR_SRAM";
    critical_cycles = structural.near_sram_ref_cycles;
  }
  if (structural.cim_ref_cycles > critical_cycles) {
    structural.critical_domain = "CIM_PROJECT_BACKPROJECT_CHAIN";
    critical_cycles = structural.cim_ref_cycles;
  }
  if (structural.solve_ref_cycles > critical_cycles) {
    structural.critical_domain = "REDUCTION_CLOSURE";
    critical_cycles = structural.solve_ref_cycles;
  }
  if (structural.vector_ref_cycles > critical_cycles) {
    structural.critical_domain = "VECTOR_UPDATE";
  }
}

void accumulate_structural(PhaseBStructuralSummary& dst,
                           const PhaseBStructuralSummary& src) {
  dst.panel_visits += src.panel_visits;
  dst.row_block_visits += src.row_block_visits;
  dst.control_ref_cycles += src.control_ref_cycles;
  dst.fft_ref_cycles += src.fft_ref_cycles;
  dst.near_sram_ref_cycles += src.near_sram_ref_cycles;
  dst.cim_ref_cycles += src.cim_ref_cycles;
  dst.solve_ref_cycles += src.solve_ref_cycles;
  dst.vector_ref_cycles += src.vector_ref_cycles;
  for (const auto& occupancy : src.module_occupancy) {
    add_module_occupancy(dst, occupancy);
  }
  refresh_structural_totals(dst);
}

void add_flow_stage_summary(PhaseBFlowControlSummary& flow_control,
                            const FlowControlStageSummary& stage) {
  for (auto& existing : flow_control.stages) {
    if (existing.stage_name == stage.stage_name) {
      existing.accept_count += stage.accept_count;
      existing.complete_count += stage.complete_count;
      existing.busy_ref_cycles += stage.busy_ref_cycles;
      existing.blocked_ref_cycles += stage.blocked_ref_cycles;
      if (stage.ingress_queue_depth > existing.ingress_queue_depth) {
        existing.ingress_queue_depth = stage.ingress_queue_depth;
      }
      if (stage.max_queue_occupancy > existing.max_queue_occupancy) {
        existing.max_queue_occupancy = stage.max_queue_occupancy;
      }
      existing.accept_condition = stage.accept_condition;
      existing.busy_condition = stage.busy_condition;
      existing.complete_condition = stage.complete_condition;
      existing.ingress_owner = stage.ingress_owner;
      existing.egress_owner = stage.egress_owner;
      existing.arbitration_domain = stage.arbitration_domain;
      existing.datapath_domain = stage.datapath_domain;
      return;
    }
  }
  flow_control.stages.push_back(stage);
}

void add_route_summary(PhaseBFlowControlSummary& flow_control,
                       const RouteBackpressureSummary& route) {
  for (auto& existing : flow_control.routes) {
    if (existing.route_name == route.route_name) {
      existing.stall_ref_cycles += route.stall_ref_cycles;
      existing.conflict_count += route.conflict_count;
      existing.cause = route.cause;
      existing.source_stage = route.source_stage;
      existing.sink_stage = route.sink_stage;
      existing.arbitration_domain = route.arbitration_domain;
      return;
    }
  }
  flow_control.routes.push_back(route);
}

void refresh_flow_control(PhaseBFlowControlSummary& flow_control) {
  flow_control.total_backpressure_ref_cycles = flow_control.lcw_issue_stall_ref_cycles;
  flow_control.route_conflict_count = 0;
  int dominant_stall = -1;
  flow_control.dominant_backpressure_route = "NONE";
  for (const auto& route : flow_control.routes) {
    flow_control.total_backpressure_ref_cycles += route.stall_ref_cycles;
    flow_control.route_conflict_count += route.conflict_count;
    if (route.stall_ref_cycles > dominant_stall) {
      dominant_stall = route.stall_ref_cycles;
      flow_control.dominant_backpressure_route = route.route_name;
    }
  }
  if (flow_control.lcw_issue_stall_ref_cycles > dominant_stall) {
    flow_control.dominant_backpressure_route = "LCW_ISSUE";
  }
}

void accumulate_flow_control(PhaseBFlowControlSummary& dst,
                             const PhaseBFlowControlSummary& src) {
  if (src.lcw_issue_credit_limit > dst.lcw_issue_credit_limit) {
    dst.lcw_issue_credit_limit = src.lcw_issue_credit_limit;
  }
  dst.lcw_issue_stall_ref_cycles += src.lcw_issue_stall_ref_cycles;
  for (const auto& stage : src.stages) {
    add_flow_stage_summary(dst, stage);
  }
  for (const auto& route : src.routes) {
    add_route_summary(dst, route);
  }
  refresh_flow_control(dst);
}

bool pipeline_active(const std::vector<int>& queue_occupancy,
                     const std::vector<int>& busy_remaining,
                     const std::vector<bool>& holding_output) {
  for (std::size_t i = 0; i < queue_occupancy.size(); ++i) {
    if (queue_occupancy[i] > 0 || busy_remaining[i] > 0 || holding_output[i]) {
      return true;
    }
  }
  return false;
}

PhaseBFlowControlSummary simulate_pipeline(const std::vector<StageSpec>& specs,
                                           int work_items,
                                           int issue_credit_limit,
                                           const std::string& source_route_name) {
  PhaseBFlowControlSummary summary;
  if (work_items <= 0 || specs.empty()) {
    summary.lcw_issue_credit_limit = issue_credit_limit;
    return summary;
  }

  summary.lcw_issue_credit_limit = issue_credit_limit;
  for (const auto& spec : specs) {
    FlowControlStageSummary stage;
    stage.stage_name = spec.stage_name;
    stage.ingress_queue_depth = spec.ingress_queue_depth;
    stage.accept_condition = spec.accept_condition;
    stage.busy_condition = spec.busy_condition;
    stage.complete_condition = spec.complete_condition;
    stage.ingress_owner = spec.ingress_owner;
    stage.egress_owner = spec.egress_owner;
    stage.arbitration_domain = spec.arbitration_domain;
    stage.datapath_domain = spec.datapath_domain;
    summary.stages.push_back(stage);
  }
  RouteBackpressureSummary source_route;
  source_route.route_name = source_route_name;
  source_route.cause = "first_stage_queue_full";
  source_route.source_stage = "LCW_ISSUE_WINDOW";
  source_route.sink_stage = specs.front().stage_name;
  source_route.arbitration_domain = "LCW_ISSUE_WINDOW";
  summary.routes.push_back(source_route);
  for (std::size_t spec_id = 0; spec_id < specs.size(); ++spec_id) {
    const auto& spec = specs[spec_id];
    RouteBackpressureSummary route;
    route.route_name = spec.route_name;
    route.cause = spec.route_cause;
    route.source_stage = spec.stage_name;
    route.sink_stage = spec_id + 1 < specs.size() ? specs[spec_id + 1].stage_name
                                                  : std::string("BODY_COMMIT");
    route.arbitration_domain = spec.arbitration_domain;
    summary.routes.push_back(route);
  }

  std::vector<int> queue_occupancy(specs.size(), 0);
  std::vector<int> busy_remaining(specs.size(), 0);
  std::vector<bool> holding_output(specs.size(), false);

  int injected = 0;
  int completed = 0;
  while (injected < work_items || completed < work_items ||
         pipeline_active(queue_occupancy, busy_remaining, holding_output)) {
    for (int stage_id = static_cast<int>(specs.size()) - 1; stage_id >= 0; --stage_id) {
      if (!holding_output[static_cast<std::size_t>(stage_id)]) {
        continue;
      }
      if (stage_id + 1 == static_cast<int>(specs.size())) {
        holding_output[static_cast<std::size_t>(stage_id)] = false;
        summary.stages[static_cast<std::size_t>(stage_id)].complete_count += 1;
        completed += 1;
        continue;
      }
      if (queue_occupancy[static_cast<std::size_t>(stage_id + 1)] <
          specs[static_cast<std::size_t>(stage_id + 1)].ingress_queue_depth) {
        queue_occupancy[static_cast<std::size_t>(stage_id + 1)] += 1;
        summary.stages[static_cast<std::size_t>(stage_id + 1)].accept_count += 1;
        if (queue_occupancy[static_cast<std::size_t>(stage_id + 1)] >
            summary.stages[static_cast<std::size_t>(stage_id + 1)].max_queue_occupancy) {
          summary.stages[static_cast<std::size_t>(stage_id + 1)].max_queue_occupancy =
              queue_occupancy[static_cast<std::size_t>(stage_id + 1)];
        }
        holding_output[static_cast<std::size_t>(stage_id)] = false;
        summary.stages[static_cast<std::size_t>(stage_id)].complete_count += 1;
      } else {
        summary.stages[static_cast<std::size_t>(stage_id)].blocked_ref_cycles += 1;
        summary.routes[static_cast<std::size_t>(stage_id + 1)].stall_ref_cycles += 1;
        summary.routes[static_cast<std::size_t>(stage_id + 1)].conflict_count += 1;
      }
    }

    for (std::size_t stage_id = 0; stage_id < specs.size(); ++stage_id) {
      if (busy_remaining[stage_id] > 0) {
        summary.stages[stage_id].busy_ref_cycles += 1;
        busy_remaining[stage_id] -= 1;
        if (busy_remaining[stage_id] == 0) {
          if (stage_id + 1 == specs.size()) {
            summary.stages[stage_id].complete_count += 1;
            completed += 1;
          } else if (queue_occupancy[stage_id + 1] < specs[stage_id + 1].ingress_queue_depth) {
            queue_occupancy[stage_id + 1] += 1;
            summary.stages[stage_id + 1].accept_count += 1;
            if (queue_occupancy[stage_id + 1] > summary.stages[stage_id + 1].max_queue_occupancy) {
              summary.stages[stage_id + 1].max_queue_occupancy = queue_occupancy[stage_id + 1];
            }
            summary.stages[stage_id].complete_count += 1;
          } else {
            holding_output[stage_id] = true;
            summary.stages[stage_id].blocked_ref_cycles += 1;
            summary.routes[stage_id + 1].stall_ref_cycles += 1;
            summary.routes[stage_id + 1].conflict_count += 1;
          }
        }
      }
    }

    for (std::size_t stage_id = 0; stage_id < specs.size(); ++stage_id) {
      if (busy_remaining[stage_id] == 0 && !holding_output[stage_id] &&
          queue_occupancy[stage_id] > 0) {
        queue_occupancy[stage_id] -= 1;
        busy_remaining[stage_id] = specs[stage_id].service_cycles;
      }
    }

    if (injected < work_items) {
      const int effective_credit_limit =
          issue_credit_limit < specs.front().ingress_queue_depth
              ? issue_credit_limit
              : specs.front().ingress_queue_depth;
      if (queue_occupancy.front() < effective_credit_limit) {
        queue_occupancy.front() += 1;
        summary.stages.front().accept_count += 1;
        if (queue_occupancy.front() > summary.stages.front().max_queue_occupancy) {
          summary.stages.front().max_queue_occupancy = queue_occupancy.front();
        }
        injected += 1;
      } else {
        summary.lcw_issue_stall_ref_cycles += 1;
        summary.routes.front().stall_ref_cycles += 1;
        summary.routes.front().conflict_count += 1;
      }
    }
  }

  refresh_flow_control(summary);
  return summary;
}

}  // namespace

ChipTop::ChipTop(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      cim_subchain_(sc_core::sc_module_name("cim_eligible_operator_subchain")),
      near_memory_domain_(sc_core::sc_module_name("near_memory_domain")),
      reduction_closure_engine_(sc_core::sc_module_name("reduction_closure_engine")),
      vector_diag_companion_(sc_core::sc_module_name("vector_diag_companion")),
      fft_companion_(sc_core::sc_module_name("fft_companion")) {}

EpisodeSummary ChipTop::run_episode(const EpisodeConfig& config) const {
  return execute_phase_b_sequence(config);
}

EpisodeSummary ChipTop::run_replay_bundle(
    const ReplayBundleDescriptor& descriptor) const {
  if (!descriptor.has_phase_b_config || descriptor.bundle_kind != "BODY_01_03_REPLAY") {
    EpisodeSummary rejected;
    rejected.status = "unsupported-replay-bundle";
    log_line(name(), "ChipTop rejected replay bundle: " + descriptor.brief());
    return rejected;
  }

  log_line(name(), "ChipTop accepted replay bundle: " + descriptor.brief());
  return execute_phase_b_sequence(descriptor.phase_b_config);
}

EpisodeSummary ChipTop::execute_phase_b_sequence(const EpisodeConfig& config) const {
  log_line(name(), "ChipTop accepted DFT episode: " + config.brief());
  log_line(name(), "On-chip partition = Command Scheduler + Resident Context Controller + "
                       "CIM / Projector-Apply + FFT + Near-SRAM Support + "
                       "Reduction / Closure / Solve + SIMD Companion");

  EpisodeSummary summary;
  summary.config = config;
  summary.fft_used = config.enable_fft;
  summary.status = "running";
  summary.structural.model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY";
  summary.flow_control.model_level = "L2_PROXY_FLOW_CONTROL_WITH_LEAF_CONTRACTS";
  summary.flow_control.bundle_accept_count = 1;
  summary.flow_control.lcw_issue_credit_limit = 2;

  if (config.support_grid_mode != "BYPASS") {
    log_line(name(), "Near-memory support-grid staging active: " +
                         config.support_grid_mode + ", batch=" +
                         std::to_string(config.band_batch));
    sc_core::wait(4.0, sc_core::SC_NS);
    summary.structural.control_ref_cycles += 4;
    add_module_occupancy(summary.structural,
                         make_occupancy("NearMemorySupportGridGate", 1, 4, 1));
    refresh_structural_totals(summary.structural);
  }

  for (int inner_step = 0; inner_step < config.max_inner_steps; ++inner_step) {
    log_line(name(), "micro-iteration " + std::to_string(inner_step + 1) +
                         " begins under solver mode " + config.solver_mode);

    log_line(name(), "BODY_01 projector_apply_body begins");
    auto panels = near_memory_domain_.stage_panels(config);
    summary.structural.near_sram_ref_cycles += 6 * static_cast<int>(panels.size());
    add_module_occupancy(summary.structural,
                         make_occupancy("NearSRAMSupport.stage_panel",
                                        static_cast<int>(panels.size()),
                                        6 * static_cast<int>(panels.size()),
                                        static_cast<int>(panels.size())));

    std::vector<StageSpec> panel_specs;
    panel_specs.push_back(make_stage_spec(
        "NearSRAMSupport.stage_panel",
        2,
        6,
        "NearSRAMSupport.stage_panel->FFTCompanion.Transform",
        "panel_stage_fifo_not_full",
        "panel_stage_engine_busy_or_output_hold",
        "panel_window_ready_for_fft_or_context_loader",
        "NearSRAM.panel_stage_fifo",
        config.enable_fft ? std::string("FFTCompanion.ingress")
                          : std::string("ContextLoader.panel_ingress"),
        "PANEL_STAGE_DOMAIN",
        "NEAR_SRAM_PANEL"));
    if (config.enable_fft) {
      for (auto& panel : panels) {
        fft_companion_.transform(panel);
      }
      summary.structural.fft_ref_cycles += 5 * static_cast<int>(panels.size());
      add_module_occupancy(summary.structural,
                           make_occupancy("FFTCompanion",
                                          static_cast<int>(panels.size()),
                                          5 * static_cast<int>(panels.size()),
                                          static_cast<int>(panels.size())));
      panel_specs.push_back(make_stage_spec(
          "FFTCompanion.Transform",
          1,
          5,
          "FFTCompanion.Transform->ContextLoader",
          "fft_ingress_slot_free",
          "fft_pipeline_busy_or_output_hold",
          "fft_panel_ready_for_context_load",
          "FFTCompanion.ingress",
          "ContextLoader.panel_ingress",
          "FFT_SHARED_DOMAIN",
          "FFT_PANEL_REORDER"));
    }
    accumulate_flow_control(summary.flow_control,
                            simulate_pipeline(panel_specs,
                                              static_cast<int>(panels.size()),
                                              2,
                                              "PANEL_ISSUE"));

    const auto operator_report = cim_subchain_.run(config, panels, inner_step);
    accumulate_structural(summary.structural, operator_report.structural);
    summary.resident_context_id = operator_report.resident_context.resident_context_id;
    summary.resident_generation = operator_report.resident_context.generation;
    summary.lcw_words_issued += operator_report.lcw_words_issued;
    summary.row_blocks_processed += operator_report.row_blocks_processed;

    const int row_work_items = operator_report.row_blocks_processed;
    std::vector<StageSpec> row_specs = {
        make_stage_spec(
            "ContextLoader",
            2,
            2,
            "ContextLoader->DigitSerialInputBoundary",
            "row_window_fifo_not_full",
            "context_loader_busy_or_output_hold",
            "row_window_ready_for_digit_pack",
            "ContextLoader.row_window_fifo",
            "DigitSerialInputBoundary.digit_pack_fifo",
            "ROW_WINDOW_DOMAIN",
            "ROW_WINDOW_LOAD"),
        make_stage_spec(
            "DigitSerialInputBoundary",
            2,
            2,
            "DigitSerialInputBoundary->ProjectConjugateSignSelector",
            "digit_pack_fifo_not_full",
            "digit_serial_pack_busy_or_output_hold",
            "digit_stream_slice_ready",
            "DigitSerialInputBoundary.digit_pack_fifo",
            "ProjectConjugateSignSelector.project_policy_slot",
            "DIGIT_STREAM_DOMAIN",
            "DIGIT_STREAM_PACK"),
        make_stage_spec(
            "ProjectConjugateSignSelector",
            2,
            1,
            "ProjectConjugateSignSelector->Residue3MCore.PROJECT",
            "project_policy_slot_free",
            "project_policy_logic_busy_or_output_hold",
            "project_conjugate_policy_applied",
            "ProjectConjugateSignSelector.project_policy_slot",
            "Residue3MCore.PROJECT.ingress_lane",
            "PROJECT_SELECTOR_DOMAIN",
            "PROJECT_POLICY_SELECT"),
        make_stage_spec(
            "Residue3MCore.PROJECT",
            1,
            6,
            "Residue3MCore.PROJECT->CoefficientAccumulator",
            "project_mac_lane_available",
            "project_residue_mac_busy_or_output_hold",
            "project_coeff_packet_ready",
            "Residue3MCore.PROJECT.ingress_lane",
            "CoefficientAccumulator.coeff_hold_reg",
            "PROJECT_ARRAY_DOMAIN",
            "PROJECT_RESIDUE_MAC"),
        make_stage_spec(
            "CoefficientAccumulator",
            1,
            3,
            "CoefficientAccumulator->NearSRAMCoeffBuffer",
            "coeff_accum_slot_free",
            "coeff_accum_busy_or_output_hold",
            "coeff_accumulation_complete",
            "CoefficientAccumulator.coeff_hold_reg",
            "NearSRAMCoeffBuffer.coeff_fifo",
            "COEFF_ACCUM_DOMAIN",
            "COEFF_ACCUMULATE"),
        make_stage_spec(
            "NearSRAMCoeffBuffer",
            2,
            4,
            "NearSRAMCoeffBuffer->BackprojectConjugateSignSelector",
            "coeff_buffer_slot_free",
            "coeff_buffer_transform_busy_or_output_hold",
            "coeff_transform_complete",
            "NearSRAMCoeffBuffer.coeff_fifo",
            "BackprojectConjugateSignSelector.backproject_policy_slot",
            "COEFF_BUFFER_DOMAIN",
            "COEFF_RESHAPE"),
        make_stage_spec(
            "BackprojectConjugateSignSelector",
            2,
            1,
            "BackprojectConjugateSignSelector->Residue3MCore.BACKPROJECT",
            "backproject_policy_slot_free",
            "backproject_policy_logic_busy_or_output_hold",
            "backproject_policy_applied",
            "BackprojectConjugateSignSelector.backproject_policy_slot",
            "Residue3MCore.BACKPROJECT.ingress_lane",
            "BACKPROJECT_SELECTOR_DOMAIN",
            "BACKPROJECT_POLICY_SELECT"),
        make_stage_spec(
            "Residue3MCore.BACKPROJECT",
            1,
            6,
            "Residue3MCore.BACKPROJECT->RowMergeTree",
            "backproject_mac_lane_available",
            "backproject_residue_mac_busy_or_output_hold",
            "backproject_row_packet_ready",
            "Residue3MCore.BACKPROJECT.ingress_lane",
            "RowMergeTree.partial_row_fifo",
            "BACKPROJECT_ARRAY_DOMAIN",
            "BACKPROJECT_RESIDUE_MAC"),
        make_stage_spec(
            "RowMergeTree",
            1,
            3,
            "RowMergeTree->NearSRAMRowBuffer",
            "row_merge_slot_free",
            "row_merge_busy_or_output_hold",
            "partial_hs_ready",
            "RowMergeTree.partial_row_fifo",
            "NearSRAMRowBuffer.row_fifo",
            "ROW_MERGE_DOMAIN",
            "ROW_REDUCE"),
        make_stage_spec(
            "NearSRAMRowBuffer",
            1,
            3,
            "NearSRAMRowBuffer->BODY_02_HS_AGGREGATE",
            "row_buffer_slot_free",
            "row_buffer_commit_busy_or_output_hold",
            "partial_commit_complete",
            "NearSRAMRowBuffer.row_fifo",
            "NearSRAMSupport.aggregate.partial_ingress",
            "ROW_BUFFER_DOMAIN",
            "PARTIAL_COMMIT")};
    accumulate_flow_control(summary.flow_control,
                            simulate_pipeline(row_specs,
                                              row_work_items,
                                              2,
                                              "LCW_ISSUE->ContextLoader"));

    log_line(name(), "BODY_02 reduced_closure_solve_body begins");
    summary.full_hs = near_memory_domain_.local_aggregate(config, operator_report.partials);
    summary.structural.near_sram_ref_cycles += 8;
    add_module_occupancy(summary.structural,
                         make_occupancy("NearSRAMSupport.aggregate", 1, 8, 1));
    summary.reduced = reduction_closure_engine_.close(config, summary.full_hs);
    summary.structural.solve_ref_cycles += 10;
    add_module_occupancy(summary.structural,
                         make_occupancy("ReductionClosureEngine", 1, 10, 1));
    auto solve_result =
        vector_diag_companion_.solve_and_update(config, summary.reduced, inner_step);
    summary.structural.vector_ref_cycles += 7;
    add_module_occupancy(summary.structural,
                         make_occupancy("VectorDiagCompanion", 1, 7, 2));
    refresh_structural_totals(summary.structural);
    summary.ritz = solve_result.first;
    summary.residual = solve_result.second;

    std::vector<StageSpec> closure_specs = {
        make_stage_spec(
            "NearSRAMSupport.aggregate",
            1,
            8,
            "NearSRAMSupport.aggregate->ReductionClosureEngine.InputAssembler",
            "aggregate_partial_fifo_not_full",
            "aggregate_reduce_busy_or_output_hold",
            "full_hs_ready_for_closure_input",
            "NearSRAMSupport.aggregate.partial_ingress",
            "ReductionClosureEngine.input_fifo",
            "CLOSURE_INPUT_DOMAIN",
            "HS_AGGREGATE"),
        make_stage_spec(
            "ReductionClosureEngine.InputAssembler",
            1,
            4,
            "ReductionClosureEngine.InputAssembler->ReductionClosureEngine.HermitianClosureBuilder",
            "closure_input_fifo_not_full",
            "closure_input_assemble_busy_or_output_hold",
            "closure_matrix_tiles_ready",
            "ReductionClosureEngine.input_fifo",
            "ReductionClosureEngine.closure_fifo",
            "CLOSURE_ENGINE_DOMAIN",
            "CLOSURE_INPUT_ASSEMBLE"),
        make_stage_spec(
            "ReductionClosureEngine.HermitianClosureBuilder",
            1,
            4,
            "ReductionClosureEngine.HermitianClosureBuilder->ReductionClosureEngine.SmallSolveFrontEnd",
            "closure_builder_slot_free",
            "closure_builder_busy_or_output_hold",
            "hermitian_reduced_matrices_ready",
            "ReductionClosureEngine.closure_fifo",
            "ReductionClosureEngine.solve_frontend_fifo",
            "CLOSURE_ENGINE_DOMAIN",
            "HERMITIAN_CLOSURE_BUILD"),
        make_stage_spec(
            "ReductionClosureEngine.SmallSolveFrontEnd",
            1,
            2,
            "ReductionClosureEngine.SmallSolveFrontEnd->VectorDiagCompanion.RitzUpdate",
            "solve_frontend_slot_free",
            "small_solve_frontend_busy_or_output_hold",
            "reduced_matrix_descriptor_ready",
            "ReductionClosureEngine.solve_frontend_fifo",
            "VectorDiagCompanion.solve_ingress",
            "SMALL_SOLVE_DOMAIN",
            "SMALL_SOLVE_PREP"),
        make_stage_spec(
            "VectorDiagCompanion.RitzUpdate",
            1,
            7,
            "VectorDiagCompanion.RitzUpdate->BODY_03",
            "vector_diag_slot_free",
            "vector_diag_busy_or_output_hold",
            "residual_refresh_packet_ready",
            "VectorDiagCompanion.solve_ingress",
            "BODY_03.commit_boundary",
            "VECTOR_DIAG_DOMAIN",
            "RITZ_UPDATE")};
    accumulate_flow_control(summary.flow_control,
                            simulate_pipeline(closure_specs,
                                              1,
                                              1,
                                              "CLOSURE_ISSUE"));

    log_line(name(), "BODY_03 refresh_compact_rebind_body commits refreshed wave objects");
    if (summary.residual.episode_done) {
      summary.status = "episode done";
      break;
    }
  }

  if (!summary.residual.episode_done) {
    summary.status = "max-inner-steps reached";
  }
  summary.flow_control.bundle_complete_count = 1;
  refresh_flow_control(summary.flow_control);

  log_line(name(), "episode complete summary: " + summary.brief());
  log_line(name(), "phase-b structural summary: " + summary.structural.brief());
  for (const auto& occupancy : summary.structural.module_occupancy) {
    log_line(name(), "phase-b module occupancy: " + occupancy.brief());
  }
  log_line(name(), "phase-b flow-control summary: " + summary.flow_control.brief());
  for (const auto& stage : summary.flow_control.stages) {
    log_line(name(), "phase-b flow stage: " + stage.brief());
  }
  for (const auto& route : summary.flow_control.routes) {
    log_line(name(), "phase-b backpressure route: " + route.brief());
  }
  return summary;
}

}  // namespace qebs
