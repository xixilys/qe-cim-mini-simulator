#include <algorithm>
#include <vector>

#include "body10_family_controller.hpp"

namespace qebs {

namespace {

std::string body10_prefix(const std::string& software_family,
                          const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

std::string wave_candidate_handle(const Body10BundleRequest& request) {
  return body10_prefix(request.software_family, request.flow_family) +
         "_wave_body10_candidate_iter_" +
         std::to_string(request.incoming_state.scf_iteration);
}

std::string wave_output_handle(const Body10BundleRequest& request) {
  return body10_prefix(request.software_family, request.flow_family) +
         "_wave_body10_iter_" + std::to_string(request.incoming_state.scf_iteration);
}

std::string projector_output_handle(const Body10BundleRequest& request) {
  return body10_prefix(request.software_family, request.flow_family) +
         "_proj_body10_iter_" + std::to_string(request.incoming_state.scf_iteration);
}

std::string history_output_handle(const Body10BundleRequest& request) {
  return body10_prefix(request.software_family, request.flow_family) +
         "_search_hist_iter_" + std::to_string(request.incoming_state.scf_iteration);
}

std::string decision_output_handle(const Body10BundleRequest& request) {
  return body10_prefix(request.software_family, request.flow_family) +
         "_ot_decision_iter_" + std::to_string(request.incoming_state.scf_iteration);
}

ObjectRecord make_body10_object(const std::string& object_handle,
                                int version,
                                int resident_buffer_tag,
                                const std::string& producer_body,
                                const std::string& validity_scope) {
  ObjectRecord object;
  object.object_handle = object_handle;
  object.version = version;
  object.resident_buffer_tag = resident_buffer_tag;
  object.producer_body = producer_body;
  object.validity_scope = validity_scope;
  return object;
}

ObjectRecord make_phase_b_residual_object(const Body10BundleRequest& request) {
  const int iter = request.incoming_state.scf_iteration;
  return make_body10_object(
      body10_prefix(request.software_family, request.flow_family) +
          "_residual_iter_" + std::to_string(iter),
      iter,
      600 + iter,
      "BODY_03",
      "episode-window");
}

struct Body10LeafSpec {
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

Body10LeafSpec make_body10_leaf_spec(const std::string& stage_name,
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
                                     const std::string& route_cause =
                                         "downstream_queue_full") {
  Body10LeafSpec spec;
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

std::string pick_critical_unit(const std::vector<ModuleOccupancy>& occupancy) {
  std::string critical_unit = "NONE";
  int critical_cycles = -1;
  for (const auto& unit : occupancy) {
    if (unit.busy_ref_cycles > critical_cycles) {
      critical_cycles = unit.busy_ref_cycles;
      critical_unit = unit.module_name;
    }
  }
  return critical_unit;
}

int sum_busy_ref_cycles(const std::vector<ModuleOccupancy>& occupancy) {
  int total_ref_cycles = 0;
  for (const auto& unit : occupancy) {
    total_ref_cycles += unit.busy_ref_cycles;
  }
  return total_ref_cycles;
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

void refresh_body10_flow_control(Body10FlowControlSummary& flow_control) {
  flow_control.total_backpressure_ref_cycles = flow_control.issue_stall_ref_cycles;
  flow_control.route_conflict_count = 0;
  int dominant_stall = 0;
  flow_control.dominant_backpressure_route = "NONE";
  for (const auto& route : flow_control.routes) {
    flow_control.total_backpressure_ref_cycles += route.stall_ref_cycles;
    flow_control.route_conflict_count += route.conflict_count;
    if (route.stall_ref_cycles > dominant_stall) {
      dominant_stall = route.stall_ref_cycles;
      flow_control.dominant_backpressure_route = route.route_name;
    }
  }
  if (flow_control.issue_stall_ref_cycles > dominant_stall) {
    flow_control.dominant_backpressure_route = "BODY_10_ISSUE";
  }
}

Body10FlowControlSummary simulate_body10_pipeline(
    const std::vector<Body10LeafSpec>& specs,
    int work_items,
    int issue_credit_limit,
    const std::string& source_route_name) {
  Body10FlowControlSummary summary;
  summary.issue_credit_limit = issue_credit_limit;
  if (work_items <= 0 || specs.empty()) {
    return summary;
  }

  summary.stage_accept_count = 1;
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
  source_route.source_stage = "BODY_10_ISSUE_WINDOW";
  source_route.sink_stage = specs.front().stage_name;
  source_route.arbitration_domain = "BODY_10_ISSUE_WINDOW";
  summary.routes.push_back(source_route);

  for (std::size_t spec_id = 0; spec_id < specs.size(); ++spec_id) {
    const auto& spec = specs[spec_id];
    RouteBackpressureSummary route;
    route.route_name = spec.route_name;
    route.cause = spec.route_cause;
    route.source_stage = spec.stage_name;
    route.sink_stage = spec_id + 1 < specs.size()
                           ? specs[spec_id + 1].stage_name
                           : std::string("BODY_10_STAGE_COMMIT");
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
        summary.stages[static_cast<std::size_t>(stage_id + 1)].max_queue_occupancy =
            std::max(summary.stages[static_cast<std::size_t>(stage_id + 1)].max_queue_occupancy,
                     queue_occupancy[static_cast<std::size_t>(stage_id + 1)]);
        holding_output[static_cast<std::size_t>(stage_id)] = false;
        summary.stages[static_cast<std::size_t>(stage_id)].complete_count += 1;
      } else {
        summary.stages[static_cast<std::size_t>(stage_id)].blocked_ref_cycles += 1;
        summary.routes[static_cast<std::size_t>(stage_id) + 1].stall_ref_cycles += 1;
        summary.routes[static_cast<std::size_t>(stage_id) + 1].conflict_count += 1;
      }
    }

    for (std::size_t stage_id = 0; stage_id < specs.size(); ++stage_id) {
      if (busy_remaining[stage_id] > 0) {
        summary.stages[stage_id].busy_ref_cycles += 1;
        busy_remaining[stage_id] -= 1;
        if (busy_remaining[stage_id] == 0) {
          holding_output[stage_id] = true;
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
      if (queue_occupancy[0] < specs[0].ingress_queue_depth) {
        queue_occupancy[0] += 1;
        summary.stages[0].accept_count += 1;
        summary.stages[0].max_queue_occupancy =
            std::max(summary.stages[0].max_queue_occupancy, queue_occupancy[0]);
        injected += 1;
      } else {
        summary.issue_stall_ref_cycles += 1;
        summary.routes.front().stall_ref_cycles += 1;
        summary.routes.front().conflict_count += 1;
      }
    }
  }

  summary.stage_complete_count = completed;
  refresh_body10_flow_control(summary);
  return summary;
}

Body10StageDescriptor make_stage_descriptor(const Body10StageRequest& request,
                                            const std::string& engine_route,
                                            const std::string& expected_output_handle,
                                            const std::string& residency_action,
                                            double estimated_latency_ns) {
  Body10StageDescriptor descriptor;
  descriptor.stage_kind = request.stage_kind;
  descriptor.execution_domain = "BODY10_RUNTIME";
  descriptor.engine_route = engine_route;
  descriptor.primary_input_handle = request.primary_input_object.object_handle;
  descriptor.secondary_input_handle = request.secondary_input_object.object_handle;
  descriptor.expected_output_handle = expected_output_handle;
  descriptor.residency_action = residency_action;
  descriptor.estimated_latency_ns = estimated_latency_ns;
  return descriptor;
}

Body10StageRequest make_precond_request(const Body10BundleRequest& request) {
  Body10StageRequest stage;
  stage.bundle_id = request.bundle_id;
  stage.stage_kind = "BODY_10A_PRECOND_UPDATE";
  stage.software_family = request.software_family;
  stage.flow_family = request.flow_family;
  stage.completion_mode = "SYNC";
  stage.join_mode = "HARD_BARRIER";
  stage.incoming_state = request.incoming_state;
  stage.phase_b_summary = request.phase_b_summary;
  stage.primary_input_object = request.incoming_state.wave_object;
  stage.secondary_input_object = make_phase_b_residual_object(request);
  return stage;
}

Body10StageRequest make_ortho_request(const Body10BundleRequest& request,
                                      const ObjectRecord& wave_candidate) {
  Body10StageRequest stage;
  stage.bundle_id = request.bundle_id;
  stage.stage_kind = "BODY_10B_ORTHO_REBIND";
  stage.software_family = request.software_family;
  stage.flow_family = request.flow_family;
  stage.completion_mode = "SYNC";
  stage.join_mode = "HARD_BARRIER";
  stage.incoming_state = request.incoming_state;
  stage.phase_b_summary = request.phase_b_summary;
  stage.primary_input_object = wave_candidate;
  stage.secondary_input_object = request.incoming_state.projector_object;
  return stage;
}

Body10StageRequest make_history_request(const Body10BundleRequest& request,
                                        const ObjectRecord& rebound_wave) {
  Body10StageRequest stage;
  stage.bundle_id = request.bundle_id;
  stage.stage_kind = "BODY_10C_HISTORY_COMMIT";
  stage.software_family = request.software_family;
  stage.flow_family = request.flow_family;
  stage.completion_mode = "QUERYABLE";
  stage.join_mode = "SOFT_JOIN";
  stage.incoming_state = request.incoming_state;
  stage.phase_b_summary = request.phase_b_summary;
  stage.primary_input_object = rebound_wave;
  stage.secondary_input_object = request.incoming_state.history_object;
  return stage;
}

std::string pick_critical_stage(const Body10BundleSummary& summary) {
  const std::vector<const Body10StageSummary*> stages = {
      &summary.precond_stage, &summary.ortho_stage, &summary.history_stage};
  std::string critical_stage = "NONE";
  int max_cycles = -1;
  for (const auto* stage : stages) {
    if (stage->total_ref_cycles > max_cycles) {
      max_cycles = stage->total_ref_cycles;
      critical_stage = stage->stage_kind;
    }
  }
  return critical_stage;
}

std::string pick_dominant_backpressure_stage(const Body10BundleSummary& summary) {
  const std::vector<const Body10StageSummary*> stages = {
      &summary.precond_stage, &summary.ortho_stage, &summary.history_stage};
  std::string dominant_stage = "NONE";
  int max_backpressure = 0;
  for (const auto* stage : stages) {
    if (stage->flow_control.total_backpressure_ref_cycles > max_backpressure) {
      max_backpressure = stage->flow_control.total_backpressure_ref_cycles;
      dominant_stage = stage->stage_kind;
    }
  }
  return dominant_stage;
}

}  // namespace

Body10FamilyController::Body10FamilyController(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      preconditioned_update_vector_(sc_core::sc_module_name("preconditioned_update_vector")),
      wave_candidate_commit_(sc_core::sc_module_name("wave_candidate_commit")),
      orthogonalize_unit_(sc_core::sc_module_name("orthogonalize_unit")),
      rebind_commit_(sc_core::sc_module_name("rebind_commit")),
      history_integrator_(sc_core::sc_module_name("history_integrator")),
      ot_summary_commit_(sc_core::sc_module_name("ot_summary_commit")) {}

Body10BundleSummary Body10FamilyController::execute(
    const Body10BundleRequest& request) const {
  log_line(name(), "BODY_10 family bundle begins: " + request.brief());

  Body10BundleSummary summary;
  summary.bundle_id = request.bundle_id;
  summary.phase_family = request.phase_family;
  summary.software_family = request.software_family;
  summary.flow_family = request.flow_family;
  summary.active_blocks = std::max(2, request.phase_b_summary.config.panel_count - 1);

  const int iter = request.incoming_state.scf_iteration;

  const auto precond_request = make_precond_request(request);
  const auto predicted_wave_candidate = make_body10_object(
      wave_candidate_handle(request),
      iter,
      520 + iter,
      "BODY_10A",
      "stage-window");
  const auto ortho_seed_request = make_ortho_request(request, predicted_wave_candidate);
  const auto predicted_wave_object = make_body10_object(
      wave_output_handle(request),
      iter,
      540 + iter,
      "BODY_10B",
      "episode-window");
  const auto predicted_projector_object = make_body10_object(
      projector_output_handle(request),
      iter,
      560 + iter,
      "BODY_10B",
      "episode-window");
  const auto history_seed_request = make_history_request(request, predicted_wave_object);

  summary.lowering_plan.bundle_id = request.bundle_id;
  summary.lowering_plan.phase_family = request.phase_family;
  summary.lowering_plan.software_family = request.software_family;
  summary.lowering_plan.flow_family = request.flow_family;
  summary.lowering_plan.domain_name = "Body10FamilyController";
  summary.lowering_plan.precond_stage = make_stage_descriptor(
      precond_request,
      "SIMD|SRAM_STAGE",
      predicted_wave_candidate.object_handle,
      "PHASE_B_WAVE_IN->WAVE_CANDIDATE_STAGE",
      8.0);
  summary.lowering_plan.ortho_stage = make_stage_descriptor(
      ortho_seed_request,
      "SIMD|SRAM_STAGE|SRAM_META",
      predicted_wave_object.object_handle + "/" +
          predicted_projector_object.object_handle,
      "WAVE_CANDIDATE_READ->REBOUND_WAVE_COMMIT->PROJECTOR_STATE_COMMIT",
      7.0);
  summary.lowering_plan.history_stage = make_stage_descriptor(
      history_seed_request,
      "SIMD|SRAM_META|SCF_CONTROL",
      history_output_handle(request) + "/" + decision_output_handle(request),
      "HISTORY_READ->SUMMARY_COMMIT",
      3.0);
  summary.lowering_plan.total_estimated_latency_ns =
      summary.lowering_plan.precond_stage.estimated_latency_ns +
      summary.lowering_plan.ortho_stage.estimated_latency_ns +
      summary.lowering_plan.history_stage.estimated_latency_ns;

  log_line(name(), "BODY_10 lowering plan => " + summary.lowering_plan.brief());
  log_line(name(), "BODY_10 lowering stage => " +
                       summary.lowering_plan.precond_stage.brief());
  log_line(name(), "BODY_10 lowering stage => " +
                       summary.lowering_plan.ortho_stage.brief());
  log_line(name(), "BODY_10 lowering stage => " +
                       summary.lowering_plan.history_stage.brief());

  auto log_stage = [this](const Body10StageSummary& stage) {
    log_line(name(), "BODY_10 stage summary => " + stage.brief());
    log_line(name(), "BODY_10 stage flow-control => " + stage.flow_control.brief());
    for (const auto& unit : stage.unit_occupancy) {
      log_line(name(), "BODY_10 unit occupancy => " + unit.brief());
    }
    for (const auto& flow_stage : stage.flow_control.stages) {
      log_line(name(), "BODY_10 flow stage => " + flow_stage.brief());
    }
    for (const auto& route : stage.flow_control.routes) {
      log_line(name(), "BODY_10 backpressure route => " + route.brief());
    }
  };

  log_line(name(), "BODY_10 stage request => " + precond_request.brief());
  const auto precond_stats = preconditioned_update_vector_.apply(precond_request);
  const auto precond_result =
      wave_candidate_commit_.commit(precond_request, precond_stats);
  summary.wave_candidate_object = precond_result.wave_candidate_object;
  summary.block_update_norm = precond_result.block_update_norm;
  summary.active_blocks = precond_result.active_blocks;
  summary.precond_stage.stage_kind = precond_request.stage_kind;
  summary.precond_stage.completion_mode = precond_request.completion_mode;
  summary.precond_stage.join_mode = precond_request.join_mode;
  summary.precond_stage.input_handle = precond_request.primary_input_object.object_handle +
                                       "/" +
                                       precond_request.secondary_input_object.object_handle;
  summary.precond_stage.output_handle = summary.wave_candidate_object.object_handle;
  summary.precond_stage.data_movement_kib = precond_result.data_movement_kib;
  summary.precond_stage.detail =
      "wave_candidate=" + summary.wave_candidate_object.brief() +
      ", update_norm=" + std::to_string(summary.block_update_norm) +
      ", active_blocks=" + std::to_string(summary.active_blocks);
  summary.precond_stage.unit_occupancy.push_back(
      make_occupancy("PreconditionedUpdateVector.Apply", 1, 5, 1));
  summary.precond_stage.unit_occupancy.push_back(
      make_occupancy("WaveCandidateCommit.Commit", 1, 3, 1));
  summary.precond_stage.total_ref_cycles =
      sum_busy_ref_cycles(summary.precond_stage.unit_occupancy);
  summary.precond_stage.critical_unit =
      pick_critical_unit(summary.precond_stage.unit_occupancy);
  summary.precond_stage.flow_control = simulate_body10_pipeline(
      {make_body10_leaf_spec(
           "PreconditionedUpdateVector.Apply",
           1,
           5,
           "PreconditionedUpdateVector.Apply->WaveCandidateCommit.Commit",
           "precond_vector_fifo_not_full",
           "precond_vector_busy_or_output_hold",
           "wave_candidate_ready_for_commit",
           "Body10PrecondStage.vector_fifo",
           "WaveCandidateCommit.commit_fifo",
           "OT_PRECOND_DOMAIN",
           "OT_PRECOND_UPDATE"),
       make_body10_leaf_spec(
           "WaveCandidateCommit.Commit",
           1,
           3,
           "WaveCandidateCommit.Commit->BODY_10A_STAGE_COMMIT",
           "wave_candidate_slot_free",
           "wave_candidate_commit_busy_or_output_hold",
           "wave_candidate_committed",
           "WaveCandidateCommit.commit_fifo",
           "BODY_10A.stage_boundary",
           "OT_PRECOND_COMMIT_DOMAIN",
           "OT_PRECOND_COMMIT")},
      1,
      1,
      "BODY_10A_ISSUE->PreconditionedUpdateVector.Apply");
  log_line(name(), "BODY_10A preconditioned block update => wave_candidate=" +
                       summary.wave_candidate_object.brief() +
                       ", update_norm=" + std::to_string(summary.block_update_norm));
  log_stage(summary.precond_stage);

  const auto ortho_request = make_ortho_request(request, summary.wave_candidate_object);
  log_line(name(), "BODY_10 stage request => " + ortho_request.brief());
  const auto ortho_stats = orthogonalize_unit_.project(ortho_request, precond_result);
  const auto ortho_result = rebind_commit_.commit(ortho_request, ortho_stats);
  summary.updated_wave_object = ortho_result.updated_wave_object;
  summary.updated_projector_object = ortho_result.updated_projector_object;
  summary.orthogonality_score = ortho_result.orthogonality_score;
  summary.data_movement_kib = precond_result.data_movement_kib + ortho_result.data_movement_kib;
  summary.ortho_stage.stage_kind = ortho_request.stage_kind;
  summary.ortho_stage.completion_mode = ortho_request.completion_mode;
  summary.ortho_stage.join_mode = ortho_request.join_mode;
  summary.ortho_stage.input_handle = ortho_request.primary_input_object.object_handle +
                                     "/" +
                                     ortho_request.secondary_input_object.object_handle;
  summary.ortho_stage.output_handle = summary.updated_wave_object.object_handle + "/" +
                                      summary.updated_projector_object.object_handle;
  summary.ortho_stage.data_movement_kib = ortho_result.data_movement_kib;
  summary.ortho_stage.detail =
      "rebound_wave=" + summary.updated_wave_object.brief() +
      ", projector=" + summary.updated_projector_object.brief() +
      ", ortho=" + std::to_string(summary.orthogonality_score);
  summary.ortho_stage.unit_occupancy.push_back(
      make_occupancy("OrthogonalizeUnit.Project", 1, 4, 1));
  summary.ortho_stage.unit_occupancy.push_back(
      make_occupancy("RebindCommit.Commit", 1, 3, 2));
  summary.ortho_stage.total_ref_cycles =
      sum_busy_ref_cycles(summary.ortho_stage.unit_occupancy);
  summary.ortho_stage.critical_unit =
      pick_critical_unit(summary.ortho_stage.unit_occupancy);
  summary.ortho_stage.flow_control = simulate_body10_pipeline(
      {make_body10_leaf_spec(
           "OrthogonalizeUnit.Project",
           1,
           4,
           "OrthogonalizeUnit.Project->RebindCommit.Commit",
           "orthogonalize_fifo_not_full",
           "orthogonalize_busy_or_output_hold",
           "rebound_wave_ready_for_commit",
           "Body10OrthoStage.ortho_fifo",
           "RebindCommit.commit_fifo",
           "OT_ORTHO_DOMAIN",
           "OT_ORTHOGONALIZE"),
       make_body10_leaf_spec(
           "RebindCommit.Commit",
           1,
           3,
           "RebindCommit.Commit->BODY_10B_STAGE_COMMIT",
           "rebind_slot_free",
           "rebind_commit_busy_or_output_hold",
           "rebound_wave_and_projector_committed",
           "RebindCommit.commit_fifo",
           "BODY_10B.stage_boundary",
           "OT_REBIND_DOMAIN",
           "OT_REBIND_COMMIT")},
      1,
      1,
      "BODY_10B_ISSUE->OrthogonalizeUnit.Project");
  log_line(name(), "BODY_10B orthogonalize/rebind => wave=" +
                       summary.updated_wave_object.brief() +
                       ", projector=" + summary.updated_projector_object.brief() +
                       ", ortho=" + std::to_string(summary.orthogonality_score) +
                       ", move_kib=" + std::to_string(summary.data_movement_kib));
  log_stage(summary.ortho_stage);

  const auto history_request = make_history_request(request, summary.updated_wave_object);
  log_line(name(), "BODY_10 stage request => " + history_request.brief());
  const auto history_stats = history_integrator_.integrate(history_request, ortho_result);
  const auto history_result =
      ot_summary_commit_.export_summary(history_request, history_stats);
  summary.search_history_object = history_result.search_history_object;
  summary.decision_summary_object = history_result.decision_summary_object;
  summary.accepted = history_result.accepted;
  summary.history_stage.stage_kind = history_request.stage_kind;
  summary.history_stage.completion_mode = history_request.completion_mode;
  summary.history_stage.join_mode = history_request.join_mode;
  summary.history_stage.input_handle = history_request.primary_input_object.object_handle +
                                       "/" +
                                       history_request.secondary_input_object.object_handle;
  summary.history_stage.output_handle =
      summary.search_history_object.object_handle + "/" +
      summary.decision_summary_object.object_handle;
  summary.history_stage.data_movement_kib = 0.0;
  summary.history_stage.detail =
      "history=" + summary.search_history_object.brief() +
      ", decision=" + summary.decision_summary_object.brief() +
      ", accepted=" + std::string(summary.accepted ? "yes" : "no");
  summary.history_stage.unit_occupancy.push_back(
      make_occupancy("HistoryIntegrator.Commit", 1, 2, 1));
  summary.history_stage.unit_occupancy.push_back(
      make_occupancy("OTSummaryCommit.Export", 1, 1, 1));
  summary.history_stage.total_ref_cycles =
      sum_busy_ref_cycles(summary.history_stage.unit_occupancy);
  summary.history_stage.critical_unit =
      pick_critical_unit(summary.history_stage.unit_occupancy);
  summary.history_stage.flow_control = simulate_body10_pipeline(
      {make_body10_leaf_spec(
           "HistoryIntegrator.Commit",
           1,
           2,
           "HistoryIntegrator.Commit->OTSummaryCommit.Export",
           "history_fifo_not_full",
           "history_commit_busy_or_output_hold",
           "history_ready_for_summary_export",
           "Body10HistoryStage.history_fifo",
           "OTSummaryCommit.summary_fifo",
           "OT_HISTORY_DOMAIN",
           "OT_HISTORY_COMMIT"),
       make_body10_leaf_spec(
           "OTSummaryCommit.Export",
           1,
           1,
           "OTSummaryCommit.Export->BODY_10C_STAGE_EXIT",
           "ot_summary_slot_free",
           "ot_summary_export_busy_or_output_hold",
           "ot_summary_committed",
           "OTSummaryCommit.summary_fifo",
           "BODY_10C.query_boundary",
           "OT_SUMMARY_DOMAIN",
           "OT_SUMMARY_EXPORT")},
      1,
      1,
      "BODY_10C_ISSUE->HistoryIntegrator.Commit");
  log_line(name(), "BODY_10C history/summary commit => history=" +
                       summary.search_history_object.brief() +
                       ", decision=" + summary.decision_summary_object.brief() +
                       ", accepted=" + std::string(summary.accepted ? "yes" : "no"));
  log_stage(summary.history_stage);

  summary.total_ref_cycles = summary.precond_stage.total_ref_cycles +
                             summary.ortho_stage.total_ref_cycles +
                             summary.history_stage.total_ref_cycles;
  summary.total_backpressure_ref_cycles =
      summary.precond_stage.flow_control.total_backpressure_ref_cycles +
      summary.ortho_stage.flow_control.total_backpressure_ref_cycles +
      summary.history_stage.flow_control.total_backpressure_ref_cycles;
  summary.critical_stage_kind = pick_critical_stage(summary);
  summary.dominant_backpressure_stage_kind =
      pick_dominant_backpressure_stage(summary);

  log_line(name(), "BODY_10 family bundle complete: " + summary.brief());
  return summary;
}

}  // namespace qebs
